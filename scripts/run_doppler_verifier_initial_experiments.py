#!/usr/bin/env python
"""Run Doppler-only residual verifier initial experiments.

This script reuses the controlled Starlink 20-target Ku-band pass table and
candidate library.  It calibrates a per-target residual RMSE threshold from
legitimate samples, then evaluates simple controlled orbit-similarity attacks
where an attack orbit B claims to be target A.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from skyfield.api import EarthSatellite, load, wgs84

C_MPS = 299_792_458.0
MU_EARTH_KM3_S2 = 398_600.4418

ALTITUDE_OFFSETS_KM = [-100, -50, -20, -10, -5, 5, 10, 20, 50, 100]
PHASE_OFFSETS_S = [-300, -120, -60, -30, -10, 10, 30, 60, 120, 300]


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class FitResult:
    score_rmse_hz: float
    b_hat_hz: float
    k_hat_hz_s: float
    residual_mean_hz: float
    residual_std_hz: float


@dataclass(frozen=True)
class ErrorModelSample:
    b_hz: float
    k_hz_s: float
    sigma_hz: float


@dataclass(frozen=True)
class ObservationSequence:
    """A timestamped observation curve.

    The verifier consumes y_obs_hz and the claimed target reference curve.  It
    must not consume attack orbit metadata or f_geo_source_hz as its claimed
    reference for attack observations.
    """

    sequence_id: str
    source_type: str
    claimed_target_name: str
    claimed_target_norad: str
    t_abs_utc: np.ndarray
    t_rel_s: np.ndarray
    y_obs_hz: np.ndarray
    f_geo_source_hz: np.ndarray
    noise_hz: np.ndarray
    b_true_hz: float
    k_true_hz_s: float
    sigma_true_hz: float
    t0_s: float
    sample_id: int
    attack_type: str = ""
    attack_variant: str = ""
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class VerificationResult:
    sequence_id: str
    claimed_target_name: str
    claimed_target_norad: str
    score_A_rmse_hz: float
    b_hat_hz: float
    k_hat_hz_s: float
    residual_mean_hz: float
    residual_std_hz: float
    threshold_95_hz: float
    threshold_99_hz: float
    accepted_95: bool
    accepted_99: bool
    score_margin_95_hz: float
    score_margin_99_hz: float


def fail(message: str) -> None:
    raise InputError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    parser.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    parser.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    parser.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    parser.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    parser.add_argument("--legit-dataset", type=Path, default=Path("outputs/datasets/doppler_verifier_legitimate_calibration_dataset.csv"))
    parser.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_legitimate_score_results.csv"))
    parser.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_thresholds.csv"))
    parser.add_argument("--attack-dataset", type=Path, default=Path("outputs/datasets/doppler_verifier_orbit_similarity_attack_dataset.csv"))
    parser.add_argument("--attack-results", type=Path, default=Path("outputs/metrics/doppler_verifier_orbit_similarity_attack_results.csv"))
    parser.add_argument("--attack-summary", type=Path, default=Path("outputs/metrics/doppler_verifier_orbit_similarity_attack_summary.csv"))
    parser.add_argument("--manifest", type=Path, default=Path("outputs/datasets/doppler_verifier_initial_experiments_manifest.json"))
    parser.add_argument("--report", type=Path, default=Path("outputs/reports/doppler_verifier_initial_experiment_report.md"))
    parser.add_argument("--plots-dir", type=Path, default=Path("outputs/plots"))
    parser.add_argument("--target-count", type=int, default=20)
    parser.add_argument("--legit-samples-per-target", type=int, default=50)
    parser.add_argument("--attack-samples-per-variant", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260513)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在；若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"配置文件不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse_utc(value: str) -> datetime:
    text = value[:-1] + "+00:00" if str(value).endswith("Z") else str(value)
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_tle(path: Path, ts: Any) -> dict[str, dict[str, Any]]:
    if not path.exists():
        fail(f"TLE 文件不存在: {path}")
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: dict[str, dict[str, Any]] = {}
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 ") and name.upper().startswith("STARLINK"):
            norad = line1[2:7].strip()
            entries[norad] = {
                "name": name,
                "norad": norad,
                "line1": line1,
                "line2": line2,
                "sat": EarthSatellite(line1, line2, name, ts),
            }
            i += 3
        else:
            i += 1
    if not entries:
        fail("未解析到有效 Starlink TLE")
    return entries


def load_parameter_ranges(path: Path, range_type: str = "main") -> dict[str, list[float]]:
    cfg = read_yaml(path)
    params = cfg["parameters"]
    return {
        "b_hz": [float(v) for v in params["b_hz"][f"{range_type}_range"]],
        "k_hz_per_s": [float(v) for v in params["k_hz_per_s"][f"{range_type}_range"]],
        "sigma_hz": [float(v) for v in params["sigma_hz"][f"{range_type}_range"]],
    }


def load_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, list[float]]]:
    for path in [args.selection_table, args.candidate_library, args.tle_file, args.orbit_config, args.parameter_config]:
        if not path.exists():
            fail(f"输入文件不存在: {path}")
    orbit_cfg = read_yaml(args.orbit_config)
    if orbit_cfg.get("mode") != "controlled_starlink":
        fail("当前实验必须使用 controlled_starlink mode")
    if orbit_cfg.get("observation_id") is not None:
        fail("controlled_starlink mode 下 observation_id 必须为 null 或不存在")

    selection = pd.read_csv(args.selection_table).head(args.target_count).copy()
    library = pd.read_csv(args.candidate_library)
    required_selection = ["target_name", "target_norad_id", "pass_start_utc", "pass_end_utc", "step_s"]
    required_library = [
        "target_name",
        "target_norad_id",
        "candidate_name",
        "candidate_norad_id",
        "t_abs_utc",
        "t_rel_s",
        "f_geo_candidate_hz",
        "is_true_target",
    ]
    missing_selection = [field for field in required_selection if field not in selection.columns]
    missing_library = [field for field in required_library if field not in library.columns]
    if missing_selection:
        fail("selection table 缺少字段: " + ", ".join(missing_selection))
    if missing_library:
        fail("candidate library 缺少字段: " + ", ".join(missing_library))

    selection["target_norad_id"] = selection["target_norad_id"].astype(str)
    library["target_norad_id"] = library["target_norad_id"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    true_rows = library[library["is_true_target"].astype(str).str.lower().isin(["true", "1"])]
    missing_true = sorted(set(selection["target_norad_id"]) - set(true_rows["target_norad_id"]))
    if missing_true:
        fail("candidate library 中缺少 true target 几何曲线: " + ", ".join(missing_true))

    range_type = str(orbit_cfg.get("simulation", {}).get("range_type", "main"))
    ranges = load_parameter_ranges(args.parameter_config, range_type)
    return selection, library, orbit_cfg, ranges


def target_geo_from_library(library: pd.DataFrame, target_norad: str) -> pd.DataFrame:
    target_rows = library[
        (library["target_norad_id"].astype(str) == str(target_norad))
        & (library["candidate_norad_id"].astype(str) == str(target_norad))
    ].copy()
    if target_rows.empty:
        fail(f"candidate library 中找不到 claimed target 几何曲线: {target_norad}")
    return target_rows.sort_values("t_rel_s").reset_index(drop=True)


def fit_bias_and_slope(y_obs: np.ndarray, f_geo_claimed: np.ndarray, t_rel_s: np.ndarray) -> FitResult:
    x = t_rel_s - float(np.mean(t_rel_s))
    delta = y_obs - f_geo_claimed
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    residual = delta - design @ coef
    return FitResult(
        score_rmse_hz=float(np.sqrt(np.mean(residual**2))),
        b_hat_hz=float(coef[0]),
        k_hat_hz_s=float(coef[1]),
        residual_mean_hz=float(np.mean(residual)),
        residual_std_hz=float(np.std(residual, ddof=0)),
    )


def apply_empirical_error_model(
    f_geo_hz: np.ndarray,
    t_rel_s: np.ndarray,
    b_hz: float,
    k_hz_s: float,
    sigma_hz: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, float]:
    t0_s = float(np.mean(t_rel_s))
    noise = rng.normal(0.0, sigma_hz, len(f_geo_hz)) if sigma_hz > 0 else np.zeros(len(f_geo_hz))
    f_obs = f_geo_hz + b_hz + k_hz_s * (t_rel_s - t0_s) + noise
    return f_obs, noise, t0_s


def sample_error_params(ranges: dict[str, list[float]], rng: np.random.Generator) -> ErrorModelSample:
    b_hz = float(rng.uniform(*ranges["b_hz"]))
    k_hz_s = float(rng.uniform(*ranges["k_hz_per_s"]))
    sigma_hz = float(rng.uniform(*ranges["sigma_hz"]))
    return ErrorModelSample(b_hz=b_hz, k_hz_s=k_hz_s, sigma_hz=sigma_hz)


def build_legitimate_observation(
    sequence_id: str,
    target_name: str,
    target_norad: str,
    pass_geo: pd.DataFrame,
    error_model: ErrorModelSample,
    rng: np.random.Generator,
    sample_id: int,
    random_seed: int,
) -> ObservationSequence:
    """Build y_A(t) for legitimate calibration on target A's pass grid."""
    t_rel = pass_geo["t_rel_s"].to_numpy(float)
    f_geo_a = pass_geo["f_geo_candidate_hz"].to_numpy(float)
    y_obs, noise, t0_s = apply_empirical_error_model(
        f_geo_a,
        t_rel,
        error_model.b_hz,
        error_model.k_hz_s,
        error_model.sigma_hz,
        rng,
    )
    return ObservationSequence(
        sequence_id=sequence_id,
        source_type="LEGITIMATE",
        claimed_target_name=target_name,
        claimed_target_norad=target_norad,
        t_abs_utc=pass_geo["t_abs_utc"].to_numpy(str),
        t_rel_s=t_rel,
        y_obs_hz=y_obs,
        f_geo_source_hz=f_geo_a,
        noise_hz=noise,
        b_true_hz=error_model.b_hz,
        k_true_hz_s=error_model.k_hz_s,
        sigma_true_hz=error_model.sigma_hz,
        t0_s=t0_s,
        sample_id=sample_id,
        metadata={"random_seed": random_seed},
    )


def build_attack_observation(
    sequence_id: str,
    claimed_target_name: str,
    claimed_target_norad: str,
    pass_geo: pd.DataFrame,
    f_geo_attack_b_hz: np.ndarray,
    attack_variant: dict[str, Any],
    error_model: ErrorModelSample,
    rng: np.random.Generator,
    sample_id: int,
    random_seed: int,
) -> ObservationSequence:
    """Build y_B(t) on claimed target A's pass grid.

    The returned source curve is f_geo_B(t).  It is diagnostic output for the
    observation builder, not the claimed reference passed to the verifier.
    """
    t_rel = pass_geo["t_rel_s"].to_numpy(float)
    y_obs, noise, t0_s = apply_empirical_error_model(
        f_geo_attack_b_hz,
        t_rel,
        error_model.b_hz,
        error_model.k_hz_s,
        error_model.sigma_hz,
        rng,
    )
    return ObservationSequence(
        sequence_id=sequence_id,
        source_type="ATTACK",
        claimed_target_name=claimed_target_name,
        claimed_target_norad=claimed_target_norad,
        t_abs_utc=pass_geo["t_abs_utc"].to_numpy(str),
        t_rel_s=t_rel,
        y_obs_hz=y_obs,
        f_geo_source_hz=f_geo_attack_b_hz,
        noise_hz=noise,
        b_true_hz=error_model.b_hz,
        k_true_hz_s=error_model.k_hz_s,
        sigma_true_hz=error_model.sigma_hz,
        t0_s=t0_s,
        sample_id=sample_id,
        attack_type=str(attack_variant["attack_type"]),
        attack_variant=str(attack_variant["attack_variant"]),
        metadata={
            "random_seed": random_seed,
            "altitude_offset_km": float(attack_variant["altitude_offset_km"]),
            "phase_offset_s": float(attack_variant["phase_offset_s"]),
            "inclination_offset_deg": float(attack_variant["inclination_offset_deg"]),
            "raan_offset_deg": float(attack_variant["raan_offset_deg"]),
            "attack_orbit_construction": "same-plane circular orbit approximation from target mid-pass ECI state",
        },
    )


def verify_claimed_identity(
    observation_sequence: ObservationSequence,
    f_geo_claimed_hz: np.ndarray,
    threshold_95_hz: float,
    threshold_99_hz: float,
) -> VerificationResult:
    """Verify y(t) against claimed target A.

    This verifier deliberately ignores attack orbit metadata and never uses
    f_geo_source_hz as the claimed reference.  For attack observations it
    computes y_B(t) - f_geo_A(t), not y_B(t) - f_geo_B(t).
    """
    fit = fit_bias_and_slope(observation_sequence.y_obs_hz, f_geo_claimed_hz, observation_sequence.t_rel_s)
    accepted_95 = bool(fit.score_rmse_hz <= threshold_95_hz)
    accepted_99 = bool(fit.score_rmse_hz <= threshold_99_hz)
    return VerificationResult(
        sequence_id=observation_sequence.sequence_id,
        claimed_target_name=observation_sequence.claimed_target_name,
        claimed_target_norad=observation_sequence.claimed_target_norad,
        score_A_rmse_hz=fit.score_rmse_hz,
        b_hat_hz=fit.b_hat_hz,
        k_hat_hz_s=fit.k_hat_hz_s,
        residual_mean_hz=fit.residual_mean_hz,
        residual_std_hz=fit.residual_std_hz,
        threshold_95_hz=threshold_95_hz,
        threshold_99_hz=threshold_99_hz,
        accepted_95=accepted_95,
        accepted_99=accepted_99,
        score_margin_95_hz=fit.score_rmse_hz - threshold_95_hz,
        score_margin_99_hz=fit.score_rmse_hz - threshold_99_hz,
    )


def calibrate_legitimate(
    selection: pd.DataFrame,
    library: pd.DataFrame,
    ranges: dict[str, list[float]],
    args: argparse.Namespace,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dataset_rows: list[pd.DataFrame] = []
    score_rows: list[dict[str, Any]] = []

    seq_counter = 1
    for _, target in selection.iterrows():
        target_norad = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        geo = target_geo_from_library(library, target_norad)
        f_geo = geo["f_geo_candidate_hz"].to_numpy(float)
        for sample_id in range(1, args.legit_samples_per_target + 1):
            error_model = sample_error_params(ranges, rng)
            sequence_id = f"legit_{seq_counter:06d}"
            seq_counter += 1
            observation = build_legitimate_observation(
                sequence_id=sequence_id,
                target_name=target_name,
                target_norad=target_norad,
                pass_geo=geo,
                error_model=error_model,
                rng=rng,
                sample_id=sample_id,
                random_seed=args.seed,
            )
            verification = verify_claimed_identity(
                observation_sequence=observation,
                f_geo_claimed_hz=f_geo,
                threshold_95_hz=float("inf"),
                threshold_99_hz=float("inf"),
            )

            rows = pd.DataFrame(
                {
                    "sequence_id": sequence_id,
                    "source_type": observation.source_type,
                    "target_name": target_name,
                    "target_norad": target_norad,
                    "sample_id": sample_id,
                    "t_abs_utc": observation.t_abs_utc,
                    "time_s": observation.t_rel_s,
                    "t_rel_s": observation.t_rel_s,
                    "t_centered_s": observation.t_rel_s - observation.t0_s,
                    "f_geo_hz": observation.f_geo_source_hz,
                    "f_obs_hz": observation.y_obs_hz,
                    "noise_hz": observation.noise_hz,
                    "b_true_hz": observation.b_true_hz,
                    "k_true_hz_s": observation.k_true_hz_s,
                    "sigma_true_hz": observation.sigma_true_hz,
                    "t0_s": observation.t0_s,
                    "random_seed": args.seed,
                }
            )
            dataset_rows.append(rows)
            score_rows.append(
                {
                    "sequence_id": sequence_id,
                    "target_name": target_name,
                    "target_norad": target_norad,
                    "score_rmse_hz": verification.score_A_rmse_hz,
                    "b_hat_hz": verification.b_hat_hz,
                    "k_hat_hz_s": verification.k_hat_hz_s,
                    "residual_mean_hz": verification.residual_mean_hz,
                    "residual_std_hz": verification.residual_std_hz,
                    "b_true_hz": observation.b_true_hz,
                    "k_true_hz_s": observation.k_true_hz_s,
                    "sigma_true_hz": observation.sigma_true_hz,
                }
            )

    dataset = pd.concat(dataset_rows, ignore_index=True)
    scores = pd.DataFrame(score_rows)
    thresholds = calibrate_thresholds(scores)
    return dataset, scores, thresholds


def calibrate_thresholds(scores: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (target_name, target_norad), group in scores.groupby(["target_name", "target_norad"], sort=False):
        values = group["score_rmse_hz"].to_numpy(float)
        threshold_95 = float(np.quantile(values, 0.95))
        threshold_99 = float(np.quantile(values, 0.99))
        accept_95 = values <= threshold_95
        accept_99 = values <= threshold_99
        rows.append(
            {
                "target_name": target_name,
                "target_norad": str(target_norad),
                "n_legitimate_sequences": int(len(group)),
                "score_mean_hz": float(np.mean(values)),
                "score_std_hz": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
                "score_p50_hz": float(np.quantile(values, 0.50)),
                "score_p90_hz": float(np.quantile(values, 0.90)),
                "score_p95_hz": threshold_95,
                "score_p99_hz": threshold_99,
                "threshold_95_hz": threshold_95,
                "threshold_99_hz": threshold_99,
                "true_accept_rate_95": float(np.mean(accept_95)),
                "true_accept_rate_99": float(np.mean(accept_99)),
                "false_reject_rate_95": float(1.0 - np.mean(accept_95)),
                "false_reject_rate_99": float(1.0 - np.mean(accept_99)),
                "b_hat_mean_hz": float(group["b_hat_hz"].mean()),
                "b_hat_p05_hz": float(group["b_hat_hz"].quantile(0.05)),
                "b_hat_p95_hz": float(group["b_hat_hz"].quantile(0.95)),
                "k_hat_mean_hz_s": float(group["k_hat_hz_s"].mean()),
                "k_hat_p05_hz_s": float(group["k_hat_hz_s"].quantile(0.05)),
                "k_hat_p95_hz_s": float(group["k_hat_hz_s"].quantile(0.95)),
            }
        )
    return pd.DataFrame(rows)


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        fail("轨道向量范数为 0，无法构造攻击轨道")
    return vector / norm


def synthetic_same_plane_geo(
    sat: EarthSatellite,
    station: Any,
    ts: Any,
    times: list[datetime],
    simulation_center_freq_hz: float,
    altitude_offset_km: float = 0.0,
    phase_offset_s: float = 0.0,
) -> np.ndarray:
    sky_times = ts.from_datetimes(times)
    geocentric = sat.at(sky_times)
    pos_km = geocentric.position.km.T
    vel_km_s = geocentric.velocity.km_per_s.T
    mid = len(times) // 2
    r0 = pos_km[mid]
    v0 = vel_km_s[mid]
    h_hat = normalize(np.cross(r0, v0))
    p_hat = normalize(r0)
    q_hat = normalize(np.cross(h_hat, p_hat))
    if float(np.dot(v0, q_hat)) < 0:
        q_hat = -q_hat
    radius_km = float(np.linalg.norm(r0) + altitude_offset_km)
    if radius_km <= 6_300:
        fail(f"攻击轨道半径异常: {radius_km:.3f} km")
    angular_rate_rad_s = float(np.sqrt(MU_EARTH_KM3_S2 / radius_km**3))
    t_centered = np.array([(dt - times[mid]).total_seconds() for dt in times], dtype=float)
    theta = angular_rate_rad_s * (t_centered + phase_offset_s)
    attack_pos_km = radius_km * (np.cos(theta)[:, None] * p_hat + np.sin(theta)[:, None] * q_hat)
    station_pos_km = station.at(sky_times).position.km.T
    range_m = np.linalg.norm(attack_pos_km - station_pos_km, axis=1) * 1000.0
    step_s = float(np.median(np.diff([dt.timestamp() for dt in times]))) if len(times) > 1 else 1.0
    range_rate_mps = np.gradient(range_m, step_s)
    doppler_hz = -simulation_center_freq_hz * range_rate_mps / C_MPS
    return simulation_center_freq_hz + doppler_hz


def run_attack_evaluation(
    selection: pd.DataFrame,
    library: pd.DataFrame,
    thresholds: pd.DataFrame,
    tle_entries: dict[str, dict[str, Any]],
    orbit_cfg: dict[str, Any],
    ranges: dict[str, list[float]],
    args: argparse.Namespace,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ts = load.timescale()
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(
        float(station_cfg["lat_deg"]),
        float(station_cfg["lon_deg"]),
        elevation_m=float(station_cfg["alt_m"]),
    )
    simulation_center_freq_hz = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(
        orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000)
    )
    threshold_map = {
        str(row.target_norad): (float(row.threshold_95_hz), float(row.threshold_99_hz))
        for row in thresholds.itertuples(index=False)
    }
    dataset_rows: list[pd.DataFrame] = []
    result_rows: list[dict[str, Any]] = []
    seq_counter = 1

    attack_specs: list[dict[str, Any]] = []
    for offset_km in ALTITUDE_OFFSETS_KM:
        attack_specs.append(
            {
                "attack_type": "same_plane_altitude_offset",
                "attack_variant": f"delta_h_{offset_km:+g}km",
                "altitude_offset_km": float(offset_km),
                "phase_offset_s": 0.0,
                "inclination_offset_deg": 0.0,
                "raan_offset_deg": 0.0,
            }
        )
    for offset_s in PHASE_OFFSETS_S:
        attack_specs.append(
            {
                "attack_type": "same_plane_phase_offset",
                "attack_variant": f"delta_t_{offset_s:+g}s",
                "altitude_offset_km": 0.0,
                "phase_offset_s": float(offset_s),
                "inclination_offset_deg": 0.0,
                "raan_offset_deg": 0.0,
            }
        )

    for _, target in selection.iterrows():
        target_norad = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        if target_norad not in tle_entries:
            fail(f"TLE 中找不到 target NORAD: {target_norad}")
        geo = target_geo_from_library(library, target_norad)
        times = [parse_utc(value) for value in geo["t_abs_utc"].astype(str)]
        t_rel = geo["t_rel_s"].to_numpy(float)
        f_geo_claimed = geo["f_geo_candidate_hz"].to_numpy(float)
        threshold_95, threshold_99 = threshold_map[target_norad]
        sat = tle_entries[target_norad]["sat"]

        for spec in attack_specs:
            f_geo_attack = synthetic_same_plane_geo(
                sat=sat,
                station=station,
                ts=ts,
                times=times,
                simulation_center_freq_hz=simulation_center_freq_hz,
                altitude_offset_km=float(spec["altitude_offset_km"]),
                phase_offset_s=float(spec["phase_offset_s"]),
            )
            for sample_id in range(1, args.attack_samples_per_variant + 1):
                error_model = sample_error_params(ranges, rng)
                attack_sequence_id = f"attack_{seq_counter:06d}"
                seq_counter += 1
                observation = build_attack_observation(
                    sequence_id=attack_sequence_id,
                    claimed_target_name=target_name,
                    claimed_target_norad=target_norad,
                    pass_geo=geo,
                    f_geo_attack_b_hz=f_geo_attack,
                    attack_variant=spec,
                    error_model=error_model,
                    rng=rng,
                    sample_id=sample_id,
                    random_seed=args.seed,
                )
                verification = verify_claimed_identity(
                    observation_sequence=observation,
                    f_geo_claimed_hz=f_geo_claimed,
                    threshold_95_hz=threshold_95,
                    threshold_99_hz=threshold_99,
                )
                metadata = observation.metadata or {}

                common = {
                    "attack_sequence_id": attack_sequence_id,
                    "source_type": observation.source_type,
                    "claimed_target_name": target_name,
                    "claimed_target_norad": target_norad,
                    "attack_type": spec["attack_type"],
                    "attack_variant": spec["attack_variant"],
                    "altitude_offset_km": spec["altitude_offset_km"],
                    "phase_offset_s": spec["phase_offset_s"],
                    "inclination_offset_deg": spec["inclination_offset_deg"],
                    "raan_offset_deg": spec["raan_offset_deg"],
                    "sample_id": sample_id,
                    "b_true_hz": observation.b_true_hz,
                    "k_true_hz_s": observation.k_true_hz_s,
                    "sigma_true_hz": observation.sigma_true_hz,
                    "score_A_rmse_hz": verification.score_A_rmse_hz,
                    "threshold_95_hz": verification.threshold_95_hz,
                    "threshold_99_hz": verification.threshold_99_hz,
                    "score_margin_95_hz": verification.score_margin_95_hz,
                    "score_margin_99_hz": verification.score_margin_99_hz,
                    "accepted_95": verification.accepted_95,
                    "accepted_99": verification.accepted_99,
                    "b_hat_hz": verification.b_hat_hz,
                    "k_hat_hz_s": verification.k_hat_hz_s,
                    "residual_mean_hz": verification.residual_mean_hz,
                    "residual_std_hz": verification.residual_std_hz,
                    "random_seed": args.seed,
                    "attack_orbit_construction": metadata["attack_orbit_construction"],
                }
                result_rows.append(common)
                dataset_rows.append(
                    pd.DataFrame(
                        {
                            **common,
                            "t_abs_utc": observation.t_abs_utc,
                            "time_s": observation.t_rel_s,
                            "t_rel_s": observation.t_rel_s,
                            "t_centered_s": observation.t_rel_s - observation.t0_s,
                            "f_geo_claimed_A_hz": f_geo_claimed,
                            "f_geo_attack_B_hz": observation.f_geo_source_hz,
                            "f_obs_attack_hz": observation.y_obs_hz,
                            "noise_hz": observation.noise_hz,
                            "t0_s": observation.t0_s,
                        }
                    )
                )

    attack_dataset = pd.concat(dataset_rows, ignore_index=True)
    attack_results = pd.DataFrame(result_rows)
    attack_summary = summarize_attacks(attack_results)
    return attack_dataset, attack_results, attack_summary


def summarize_attacks(results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (attack_type, attack_variant), group in results.groupby(["attack_type", "attack_variant"], sort=False):
        target_summary = (
            group.groupby(["claimed_target_name", "claimed_target_norad"])
            .agg(success_rate=("accepted_95", "mean"), min_margin=("score_margin_95_hz", "min"))
            .reset_index()
            .sort_values(["success_rate", "min_margin"], ascending=[False, True])
            .iloc[0]
        )
        rows.append(
            {
                "attack_type": attack_type,
                "attack_variant": attack_variant,
                "n_sequences": int(len(group)),
                "accepted_count_95": int(group["accepted_95"].sum()),
                "accepted_count_99": int(group["accepted_99"].sum()),
                "attack_success_rate_95": float(group["accepted_95"].mean()),
                "attack_success_rate_99": float(group["accepted_99"].mean()),
                "score_mean_hz": float(group["score_A_rmse_hz"].mean()),
                "score_p50_hz": float(group["score_A_rmse_hz"].quantile(0.50)),
                "score_p95_hz": float(group["score_A_rmse_hz"].quantile(0.95)),
                "min_score_margin_95_hz": float(group["score_margin_95_hz"].min()),
                "min_score_margin_99_hz": float(group["score_margin_99_hz"].min()),
                "b_hat_mean_hz": float(group["b_hat_hz"].mean()),
                "b_hat_p95_abs_hz": float(group["b_hat_hz"].abs().quantile(0.95)),
                "k_hat_mean_hz_s": float(group["k_hat_hz_s"].mean()),
                "k_hat_p95_abs_hz_s": float(group["k_hat_hz_s"].abs().quantile(0.95)),
                "most_vulnerable_target": target_summary["claimed_target_name"],
                "most_vulnerable_target_norad": str(target_summary["claimed_target_norad"]),
            }
        )
    return pd.DataFrame(rows)


def write_plots(scores: pd.DataFrame, thresholds: pd.DataFrame, attack_results: pd.DataFrame, attack_summary: pd.DataFrame, plots_dir: Path) -> list[Path]:
    plots_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(scores["score_rmse_hz"], bins=40, color="#3b6f8f", alpha=0.75)
    ax.axvline(thresholds["threshold_95_hz"].median(), color="#b55a30", linestyle="--", label="median target p95")
    ax.axvline(thresholds["threshold_99_hz"].median(), color="#7a5aa6", linestyle="--", label="median target p99")
    ax.set_xlabel("legitimate verifier score RMSE (Hz)")
    ax.set_ylabel("sequence count")
    ax.set_title("Doppler verifier legitimate score distribution")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = plots_dir / "doppler_verifier_legitimate_score_distribution.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)

    fig, ax = plt.subplots(figsize=(11, 5))
    data = [group["score_margin_95_hz"].to_numpy(float) for _, group in attack_results.groupby("attack_type", sort=False)]
    labels = list(attack_results.groupby("attack_type", sort=False).groups.keys())
    ax.boxplot(data, labels=labels, showfliers=False)
    ax.axhline(0, color="#8f3030", linestyle="--", linewidth=1.2)
    ax.set_ylabel("score_A - threshold_95 (Hz)")
    ax.set_title("Doppler verifier attack score margin by type")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path = plots_dir / "doppler_verifier_attack_score_margin_by_type.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)

    plot_summary = attack_summary.copy()
    plot_summary["label"] = plot_summary["attack_variant"].astype(str)
    for attack_type, group in plot_summary.groupby("attack_type", sort=False):
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.bar(group["label"], group["attack_success_rate_95"], color="#6f8f3b", label="threshold_95")
        ax.plot(group["label"], group["attack_success_rate_99"], color="#3b4f8f", marker="o", label="threshold_99")
        ax.set_ylim(0, 1.05)
        ax.set_ylabel("attack success rate")
        ax.set_title(f"Doppler verifier attack success rate: {attack_type}")
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.grid(True, axis="y", alpha=0.25)
        ax.legend()
        fig.tight_layout()
        path = plots_dir / f"doppler_verifier_attack_success_rate_by_variant_{attack_type}.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(plot_summary["label"], plot_summary["attack_success_rate_95"], color="#6f8f3b")
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("attack success rate under threshold_95")
    ax.set_title("Doppler verifier attack success rate by variant")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path = plots_dir / "doppler_verifier_attack_success_rate_by_variant.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)
    return paths


def markdown_table(df: pd.DataFrame, columns: list[str], max_rows: int | None = None) -> str:
    data = df[columns].copy()
    if max_rows is not None:
        data = data.head(max_rows)
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    lines = [header, sep]
    for _, row in data.iterrows():
        values = []
        for col in columns:
            value = row[col]
            if isinstance(value, float):
                values.append(f"{value:.6g}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(
    path: Path,
    thresholds: pd.DataFrame,
    legit_scores: pd.DataFrame,
    attack_results: pd.DataFrame,
    attack_summary: pd.DataFrame,
    manifest: dict[str, Any],
) -> None:
    overall_legit_accept_95 = float((legit_scores.merge(thresholds[["target_norad", "threshold_95_hz"]], on="target_norad")["score_rmse_hz"] <= legit_scores.merge(thresholds[["target_norad", "threshold_95_hz"]], on="target_norad")["threshold_95_hz"]).mean())
    overall_legit_accept_99 = float((legit_scores.merge(thresholds[["target_norad", "threshold_99_hz"]], on="target_norad")["score_rmse_hz"] <= legit_scores.merge(thresholds[["target_norad", "threshold_99_hz"]], on="target_norad")["threshold_99_hz"]).mean())
    total_success_95 = float(attack_results["accepted_95"].mean())
    total_success_99 = float(attack_results["accepted_99"].mean())
    min_margin_row = attack_results.sort_values("score_margin_95_hz").iloc[0]
    accepted_attacks = attack_results[attack_results["accepted_95"]].copy()
    accepted_note = "threshold_95 下没有 false accept 样本。"
    accepted_table = ""
    if not accepted_attacks.empty:
        accepted_table = "\n\nthreshold_95 下 false accept 样本：\n\n" + markdown_table(
            accepted_attacks,
            [
                "attack_sequence_id",
                "claimed_target_name",
                "claimed_target_norad",
                "attack_type",
                "attack_variant",
                "score_A_rmse_hz",
                "threshold_95_hz",
                "score_margin_95_hz",
                "b_hat_hz",
                "k_hat_hz_s",
            ],
        )
        k_min = float(accepted_attacks["k_hat_hz_s"].min())
        k_max = float(accepted_attacks["k_hat_hz_s"].max())
        accepted_note = (
            f"threshold_95 下共有 `{len(accepted_attacks)}` 条 false accept 样本。"
            f"这些样本的 `k_hat` 范围为 `{k_min:.6f}` 到 `{k_max:.6f}` Hz/s，"
            "明显超出本轮合法误差模型 main_range 的 `k` 采样范围 "
            "[-1.110156, -0.197808] Hz/s；这说明单看 residual RMSE 会漏掉一类"
            "由 b+k 拟合项强吸收的异常样本，后续应考虑 score gate + fitted-parameter sanity gate。"
        )
    type_summary = (
        attack_results.groupby("attack_type")
        .agg(
            n_sequences=("attack_sequence_id", "count"),
            success_95=("accepted_95", "mean"),
            success_99=("accepted_99", "mean"),
            min_margin_95=("score_margin_95_hz", "min"),
            score_p50=("score_A_rmse_hz", "median"),
        )
        .reset_index()
    )

    text = f"""# Doppler-only residual verifier initial experiment report

## 1. Motivation

closed-set residual matcher 会强制从候选库中选出一个 score 最小的 satellite，因此它不适合直接定义“攻击是否成功”。本轮把已有 b+k profile least-squares matcher 改成 single-target verifier：给定 claimed target A 和观测曲线 y(t)，系统只判断这条曲线是否足够像 A，并允许 reject。

## 2. Verifier definition

输入为 claimed target A 与观测曲线 y(t)。本轮使用 candidate library 中 A 自己的 Ku-band 几何曲线 `f_geo_A(t)`，计算 `delta_A(t) = y(t) - f_geo_A(t)`，拟合 `b_hat + k_hat(t - t0)`，再用扣除拟合项后的 residual RMSE 作为 `score_A`。若 `score_A <= threshold_A_95` 或 `score_A <= threshold_A_99`，则在对应阈值下 accept，否则 reject。

本轮阈值是 per-target threshold，不使用单一 global threshold。`threshold_A_95` 和 `threshold_A_99` 分别来自合法仿真样本 score 分布的 95% 与 99% 分位数。

## 3. Legitimate calibration

合法样本使用 controlled Starlink Ku-band full-pass reference，目标列表来自 `{manifest["selection_table"]}`，claimed reference 来自 `{manifest["candidate_library"]}` 中每个 target 的 true-target 几何曲线。每个 target 生成 `{manifest["legit_samples_per_target"]}` 条合法曲线：

`f_legit_A(t) = f_geo_A(t) + b + k(t - t0) + noise`

其中 `b/k/sigma` 均从 main_range 随机采样，random_seed = `{manifest["random_seed"]}`。本轮合法校准总序列数为 `{len(legit_scores)}`，整体 p95 阈值下 true accept rate = `{overall_legit_accept_95:.4f}`，p99 阈值下 true accept rate = `{overall_legit_accept_99:.4f}`。

阈值表前 10 行：

{markdown_table(thresholds, ["target_name", "target_norad", "n_legitimate_sequences", "score_mean_hz", "score_p95_hz", "score_p99_hz", "true_accept_rate_95", "true_accept_rate_99"], 10)}

## 4. Attack orbit construction

攻击曲线来自攻击轨道 B，而不是目标 A。攻击者 B 声称自己是 A；verifier 只使用 A 的 claimed geometry 计算 `score_A`。如果 `score_A <= threshold_A`，则记录为 false accept / attack success。

本轮实现两类初步攻击：

- `same_plane_altitude_offset`：从目标 A 的 mid-pass ECI 位置和速度估计轨道面，构造同轨道面圆轨道近似 B，并设置高度偏移 Δh = {ALTITUDE_OFFSETS_KM} km。
- `same_plane_phase_offset`：使用同一受控圆轨道近似，保持高度不变，用沿轨道相位/时间偏移 Δt = {PHASE_OFFSETS_S} s 构造 B。

这个 B 轨道生成器是受控近似：它由 mid-pass ECI 状态、轨道面法向、圆轨道半径和角速度生成 B 的位置序列，再由 B 到地面站的 range-rate 计算 Doppler。它不是把 A 的 Doppler 曲线直接加扰动来伪装攻击样本。`approximate_orbit_perturbation` 本轮未展开，列为下一步。

## 5. Results

攻击总序列数为 `{len(attack_results)}`。整体 threshold_95 下 attack success rate = `{total_success_95:.4f}`，threshold_99 下 attack success rate = `{total_success_99:.4f}`。

按攻击类型汇总：

{markdown_table(type_summary, ["attack_type", "n_sequences", "success_95", "success_99", "min_margin_95", "score_p50"])}

按 variant 汇总前 20 行：

{markdown_table(attack_summary, ["attack_type", "attack_variant", "n_sequences", "attack_success_rate_95", "attack_success_rate_99", "min_score_margin_95_hz", "most_vulnerable_target", "most_vulnerable_target_norad"], 20)}

最小 p95 margin 样本为 `{min_margin_row.attack_sequence_id}`：claimed target = `{min_margin_row.claimed_target_name} / {min_margin_row.claimed_target_norad}`，attack_type = `{min_margin_row.attack_type}`，variant = `{min_margin_row.attack_variant}`，score_A = `{min_margin_row.score_A_rmse_hz:.6f}` Hz，threshold_95 = `{min_margin_row.threshold_95_hz:.6f}` Hz，score_margin_95 = `{min_margin_row.score_margin_95_hz:.6f}` Hz。

`b_hat/k_hat` 需要和 residual score 一起看：同轨道面相似攻击可能被 b+k 拟合项吸收掉整体频偏和平缓趋势，但如果剩余曲线形状仍不同，RMSE 会高于阈值。完整 `b_hat`、`k_hat` 分布已写入 attack results 与 summary。

{accepted_note}{accepted_table}

## 6. Interpretation

本轮是 controlled simulation，不是现实世界真实攻击成功率。本轮评估的是 Doppler-only residual verifier 在受控轨道相似攻击下的 false accept 风险。

如果攻击者能够完全按目标 A 主动伪造接收频率轨迹，单站 Doppler-only verifier 本身会面临天然局限；本轮没有把攻击曲线生成为 `f_geo_A(t) + b + k + noise`，因此避免了自证循环。`frequency_scaled` 或真实 Starlink Ku-band CFO 分布不是本轮结论，本轮仍使用工程级 effective residual main_range。

## 7. Next steps

- 双阈值灰区：accept / reject / defer。
- 随机子窗口挑战：避免固定窗口被 trajectory-aware attacker 预补偿。
- 多地面站联合：检查跨站 Doppler / TDOA 一致性。
- 近似轨道扰动扩展：加入 Δh、Δi、ΔΩ、Δphase 的小网格。
- 更强攻击者的受限频率补偿实验，同时明确不能把主动完全伪造 A 轨迹与自然轨道相似攻击混为一谈。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_work_log(path: Path, manifest: dict[str, Any], thresholds: pd.DataFrame, attack_results: pd.DataFrame, attack_summary: pd.DataFrame) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_success_95 = float(attack_results["accepted_95"].mean())
    total_success_99 = float(attack_results["accepted_99"].mean())
    min_row = attack_results.sort_values("score_margin_95_hz").iloc[0]
    log = f"""

## {now} - Doppler-only residual verifier initial experiments

### A. 本轮目标

完成一组最小闭环 Doppler-only residual verifier 初步实验：将 closed-set residual matcher 扩展为带 per-target 拒绝阈值的 claimed-target verifier，使用合法仿真样本校准阈值，并测试同轨道面高度偏移与同轨道面相位偏移攻击样本的 false accept 风险。

### B. 实际操作

- 新增 `scripts/run_doppler_verifier_initial_experiments.py`。
- 复用 `outputs/metrics/controlled_starlink_20target_selection_table.csv` 作为 20-target 列表。
- 复用 `outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv` 中 true-target Ku-band 几何曲线作为 claimed target reference。
- 合法样本从 main_range 随机采样 b/k/sigma，按 per-target score p95 / p99 校准阈值。
- 攻击样本由受控同轨道面圆轨道近似 B 生成 Doppler 曲线，B 声称自己是 A；未把攻击曲线写成 A 曲线。

### C. 新增/修改文件

- 新增脚本：`scripts/run_doppler_verifier_initial_experiments.py`
- 新增输出：`outputs/datasets/doppler_verifier_legitimate_calibration_dataset.csv`
- 新增输出：`outputs/metrics/doppler_verifier_legitimate_score_results.csv`
- 新增输出：`outputs/metrics/doppler_verifier_thresholds.csv`
- 新增输出：`outputs/datasets/doppler_verifier_orbit_similarity_attack_dataset.csv`
- 新增输出：`outputs/metrics/doppler_verifier_orbit_similarity_attack_results.csv`
- 新增输出：`outputs/metrics/doppler_verifier_orbit_similarity_attack_summary.csv`
- 新增输出：`outputs/datasets/doppler_verifier_initial_experiments_manifest.json`
- 新增输出：`outputs/reports/doppler_verifier_initial_experiment_report.md`
- 新增输出：`outputs/plots/doppler_verifier_*.png`
- 追加日志：`logs/work_log.md`

### D. 运行命令

```bash
python scripts/run_doppler_verifier_initial_experiments.py
```

### E. 结果摘要

- random_seed：`{manifest["random_seed"]}`。
- target_count：`{manifest["target_count"]}`。
- 合法校准序列数：`{manifest["legitimate_sequence_count"]}`。
- 攻击序列数：`{manifest["attack_sequence_count"]}`。
- 合法阈值：per-target p95 / p99，平均 p95 threshold = `{thresholds["threshold_95_hz"].mean():.6f} Hz`，平均 p99 threshold = `{thresholds["threshold_99_hz"].mean():.6f} Hz`。
- 攻击整体 success rate：threshold_95 = `{total_success_95:.6f}`，threshold_99 = `{total_success_99:.6f}`。
- 最小 p95 margin：`{min_row.score_margin_95_hz:.6f} Hz`，样本 `{min_row.attack_sequence_id}`，claimed target `{min_row.claimed_target_name} / {min_row.claimed_target_norad}`，attack `{min_row.attack_type}` / `{min_row.attack_variant}`。
- 最脆弱 variant 摘要见 `outputs/metrics/doppler_verifier_orbit_similarity_attack_summary.csv`。

### F. 问题与下一步

本轮是 controlled simulation，不是现实世界真实攻击成功率。同轨道面攻击轨道 B 使用 mid-pass ECI 状态导出的圆轨道近似，已在报告中说明；`approximate_orbit_perturbation` 小网格本轮未展开，建议下一步加入 Δh/Δi/ΔΩ/Δphase，并进一步测试双阈值灰区、随机子窗口挑战、多站联合和受限频率补偿攻击。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(log)


def write_outputs(
    args: argparse.Namespace,
    legitimate_dataset: pd.DataFrame,
    legitimate_scores: pd.DataFrame,
    thresholds: pd.DataFrame,
    attack_dataset: pd.DataFrame,
    attack_results: pd.DataFrame,
    attack_summary: pd.DataFrame,
    manifest: dict[str, Any],
) -> None:
    for path in [
        args.legit_dataset,
        args.legit_results,
        args.thresholds,
        args.attack_dataset,
        args.attack_results,
        args.attack_summary,
        args.manifest,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
    legitimate_dataset.to_csv(args.legit_dataset, index=False)
    legitimate_scores.to_csv(args.legit_results, index=False)
    thresholds.to_csv(args.thresholds, index=False)
    attack_dataset.to_csv(args.attack_dataset, index=False)
    attack_results.to_csv(args.attack_results, index=False)
    attack_summary.to_csv(args.attack_summary, index=False)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_paths = [
        args.legit_dataset,
        args.legit_results,
        args.thresholds,
        args.attack_dataset,
        args.attack_results,
        args.attack_summary,
        args.manifest,
        args.report,
        args.plots_dir / "doppler_verifier_legitimate_score_distribution.png",
        args.plots_dir / "doppler_verifier_attack_score_margin_by_type.png",
        args.plots_dir / "doppler_verifier_attack_success_rate_by_variant.png",
    ]
    try:
        check_outputs(output_paths, args.overwrite)
        selection, library, orbit_cfg, ranges = load_inputs(args)
        ts = load.timescale()
        tle_entries = parse_tle(args.tle_file, ts)
        rng = np.random.default_rng(args.seed)

        legitimate_dataset, legitimate_scores, thresholds = calibrate_legitimate(selection, library, ranges, args, rng)
        attack_dataset, attack_results, attack_summary = run_attack_evaluation(
            selection=selection,
            library=library,
            thresholds=thresholds,
            tle_entries=tle_entries,
            orbit_cfg=orbit_cfg,
            ranges=ranges,
            args=args,
            rng=rng,
        )
        plots = write_plots(legitimate_scores, thresholds, attack_results, attack_summary, args.plots_dir)
        manifest = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "script": "scripts/run_doppler_verifier_initial_experiments.py",
            "mode": "controlled_starlink",
            "observation_id": None,
            "experiment_name": "doppler_verifier_initial_experiments",
            "selection_table": str(args.selection_table),
            "candidate_library": str(args.candidate_library),
            "tle_file": str(args.tle_file),
            "orbit_config": str(args.orbit_config),
            "parameter_config": str(args.parameter_config),
            "parameter_range_type": str(orbit_cfg.get("simulation", {}).get("range_type", "main")),
            "parameter_ranges_used": ranges,
            "target_count": int(len(selection)),
            "legit_samples_per_target": args.legit_samples_per_target,
            "attack_samples_per_variant": args.attack_samples_per_variant,
            "legitimate_sequence_count": int(len(legitimate_scores)),
            "legitimate_row_count": int(len(legitimate_dataset)),
            "attack_sequence_count": int(len(attack_results)),
            "attack_row_count": int(len(attack_dataset)),
            "attack_types": ["same_plane_altitude_offset", "same_plane_phase_offset"],
            "altitude_offsets_km": ALTITUDE_OFFSETS_KM,
            "phase_offsets_s": PHASE_OFFSETS_S,
            "random_seed": args.seed,
            "station": orbit_cfg["station"],
            "simulation_center_freq_hz": float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else None,
            "notes": [
                "Controlled simulation only; not real-world attack success rate.",
                "Verifier fits and absorbs b+k before residual RMSE scoring.",
                "Attack curves are generated from controlled attack orbit B, not from target A geometry plus residual noise.",
                "same_plane attack orbit generator uses a circular-orbit approximation from target mid-pass ECI state.",
            ],
            "outputs": {
                "legitimate_dataset": str(args.legit_dataset),
                "legitimate_scores": str(args.legit_results),
                "thresholds": str(args.thresholds),
                "attack_dataset": str(args.attack_dataset),
                "attack_results": str(args.attack_results),
                "attack_summary": str(args.attack_summary),
                "report": str(args.report),
                "plots": [str(path) for path in plots],
            },
        }
        write_outputs(args, legitimate_dataset, legitimate_scores, thresholds, attack_dataset, attack_results, attack_summary, manifest)
        write_report(args.report, thresholds, legitimate_scores, attack_results, attack_summary, manifest)
        append_work_log(Path("logs/work_log.md"), manifest, thresholds, attack_results, attack_summary)
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    print(f"Verifier 初步实验完成: {args.report}")
    print(f"合法校准序列: {len(legitimate_scores)}, 攻击序列: {len(attack_results)}")
    print(f"攻击 success rate p95: {attack_results['accepted_95'].mean():.6f}, p99: {attack_results['accepted_99'].mean():.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
