#!/usr/bin/env python
"""Window reliability calibration for Starlink claimed-identity verifier.

This diagnostic experiment reuses the existing controlled Starlink geometry,
empirical residual error model, and b+k residual fitting code.  It evaluates
full-pass and partial-window reliability for benign samples and three
regularized orbit-similarity attack families.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from skyfield.api import load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_doppler_verifier_initial_experiments as base  # noqa: E402


DEFAULT_ALTITUDE_DELTAS_KM = [-10, -5, -2, -1, 1, 2, 5, 10]
DEFAULT_PHASE_OFFSETS_S = [-120, -60, -30, 30, 60, 120]
DEFAULT_INCLINATION_DELTAS_DEG = [-0.20, -0.10, -0.05, 0.05, 0.10, 0.20]
DEFAULT_WINDOW_LENGTHS = [180, 120, 60, 30]
DEFAULT_THRESHOLD_TYPES = ["p95", "p99"]
DEFAULT_VERIFIER_TYPES = ["shape_only", "weak_prior", "strong_prior"]
FULL_PASS_LENGTH_SENTINEL = -1


@dataclass(frozen=True)
class WindowSpec:
    window_type: str
    window_length_s: float
    window_position: str
    start_s: float
    stop_s: float
    selection_score: float | None = None
    skip_reason: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run window reliability calibration for controlled Starlink verifier.")
    parser.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    parser.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    parser.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    parser.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    parser.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    parser.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/window_reliability_calibration_dataset.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/window_reliability_calibration_summary.csv"))
    parser.add_argument("--bk-output", type=Path, default=Path("outputs/metrics/window_reliability_bk_gate_contribution.csv"))
    parser.add_argument("--report-output", type=Path, default=Path("outputs/reports/window_reliability_calibration_summary.md"))
    parser.add_argument("--figures-dir", type=Path, default=Path("outputs/figures"))
    parser.add_argument("--max-targets", type=int, default=20)
    parser.add_argument("--max-passes-per-target", type=int, default=1)
    parser.add_argument("--num-sims-per-attack", type=int, default=5)
    parser.add_argument("--num-benign-sims", type=int, default=None)
    parser.add_argument("--window-lengths", nargs="+", default=[str(v) for v in DEFAULT_WINDOW_LENGTHS])
    parser.add_argument("--include-best-attack", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--threshold-types", nargs="+", choices=DEFAULT_THRESHOLD_TYPES, default=DEFAULT_THRESHOLD_TYPES)
    parser.add_argument("--verifier-types", nargs="+", choices=DEFAULT_VERIFIER_TYPES, default=DEFAULT_VERIFIER_TYPES)
    parser.add_argument("--altitude-deltas-km", nargs="+", type=float, default=DEFAULT_ALTITUDE_DELTAS_KM)
    parser.add_argument("--phase-offsets-s", nargs="+", type=float, default=DEFAULT_PHASE_OFFSETS_S)
    parser.add_argument("--inclination-deltas-deg", nargs="+", type=float, default=DEFAULT_INCLINATION_DELTAS_DEG)
    parser.add_argument("--weak-prior-factor", type=float, default=3.0)
    parser.add_argument("--strong-min-points", type=int, default=20)
    parser.add_argument("--weak-min-points", type=int, default=10)
    parser.add_argument("--quality-min-mean-elevation-deg", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260611)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def parse_window_lengths(values: list[str]) -> list[int]:
    out: list[int] = []
    for raw in values:
        text = str(raw).strip().lower()
        if text in {"full", "full_pass"}:
            out.append(FULL_PASS_LENGTH_SENTINEL)
        else:
            out.append(int(float(text)))
    return out


def quantile_type_to_q(threshold_type: str) -> float:
    return 0.95 if threshold_type == "p95" else 0.99


def load_global_ranges(parameter_config: Path) -> tuple[tuple[float, float], tuple[float, float]]:
    cfg = base.read_yaml(parameter_config)
    params = cfg.get("parameters", {})
    b_range = tuple(float(v) for v in params["b_hz"]["main_range"])
    k_range = tuple(float(v) for v in params["k_hz_per_s"]["main_range"])
    return b_range, k_range  # type: ignore[return-value]


def station_from_cfg(orbit_cfg: dict[str, Any]) -> Any:
    station_cfg = orbit_cfg["station"]
    return wgs84.latlon(
        float(station_cfg["lat_deg"]),
        float(station_cfg["lon_deg"]),
        elevation_m=float(station_cfg["alt_m"]),
    )


def ensure_target_elevation(geo: pd.DataFrame, sat: Any, station: Any, ts: Any) -> pd.DataFrame:
    out = geo.copy()
    if "elevation_deg" in out.columns and out["elevation_deg"].notna().any():
        return out
    times = [base.parse_utc(v) for v in out["t_abs_utc"].astype(str)]
    sky_times = ts.from_datetimes(times)
    elevation = (sat - station).at(sky_times).altaz()[0].degrees
    out["elevation_deg"] = elevation
    return out


def utc_to_iso(value: str | datetime) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def slice_mask(t_rel: np.ndarray, start_s: float, stop_s: float) -> np.ndarray:
    eps = 1e-9
    return (t_rel >= start_s - eps) & (t_rel <= stop_s + eps)


def window_metrics(geo: pd.DataFrame, spec: WindowSpec, mask: np.ndarray) -> dict[str, Any]:
    times = geo.loc[mask, "t_abs_utc"].astype(str).to_numpy()
    elev = geo.loc[mask, "elevation_deg"].to_numpy(float) if "elevation_deg" in geo.columns else np.full(mask.sum(), np.nan)
    finite_elev = elev[np.isfinite(elev)]
    return {
        "window_type": spec.window_type,
        "window_length_s": float(spec.window_length_s),
        "window_position": spec.window_position,
        "window_start_time": str(times[0]) if len(times) else "",
        "window_stop_time": str(times[-1]) if len(times) else "",
        "window_center_time": str(times[len(times) // 2]) if len(times) else "",
        "n_points": int(mask.sum()),
        "max_elevation_deg": float(np.max(finite_elev)) if len(finite_elev) else np.nan,
        "mean_elevation_deg": float(np.mean(finite_elev)) if len(finite_elev) else np.nan,
    }


def fit_on_mask(y_obs: np.ndarray, f_geo_claimed: np.ndarray, t_rel_s: np.ndarray, mask: np.ndarray) -> base.FitResult:
    return base.fit_bias_and_slope(y_obs[mask], f_geo_claimed[mask], t_rel_s[mask])


def residual_stats(y_obs: np.ndarray, f_geo_claimed: np.ndarray, t_rel_s: np.ndarray, mask: np.ndarray, fit: base.FitResult) -> dict[str, float]:
    t = t_rel_s[mask]
    x = t - float(np.mean(t))
    delta = y_obs[mask] - f_geo_claimed[mask]
    residual = delta - (fit.b_hat_hz + fit.k_hat_hz_s * x)
    return {
        "raw_delta_rmse_hz": float(np.sqrt(np.mean(delta**2))),
        "detrended_residual_std_hz": float(np.std(residual, ddof=0)),
        "residual_p95_abs_hz": float(np.quantile(np.abs(residual), 0.95)),
    }


def sliding_window_starts(t_rel: np.ndarray, length_s: float) -> np.ndarray:
    start_min = float(np.min(t_rel))
    start_max = float(np.max(t_rel) - length_s)
    if start_max < start_min:
        return np.array([], dtype=float)
    step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
    return np.arange(start_min, start_max + 0.5 * step_s, max(step_s, 1.0), dtype=float)


def build_middle_window(t_rel: np.ndarray, length_s: int) -> WindowSpec:
    if length_s == FULL_PASS_LENGTH_SENTINEL:
        return WindowSpec("full_pass", float(np.max(t_rel) - np.min(t_rel)), "full_pass", float(np.min(t_rel)), float(np.max(t_rel)))
    full_len = float(np.max(t_rel) - np.min(t_rel))
    if full_len < float(length_s):
        return WindowSpec(f"{length_s}s_middle", float(length_s), "middle", np.nan, np.nan, skip_reason="full_pass_shorter_than_window")
    center = 0.5 * (float(np.min(t_rel)) + float(np.max(t_rel)))
    return WindowSpec(f"{length_s}s_middle", float(length_s), "middle", center - length_s / 2.0, center + length_s / 2.0)


def choose_best_attack_window(
    y_obs: np.ndarray,
    f_geo_claimed: np.ndarray,
    t_rel_s: np.ndarray,
    length_s: int,
    threshold_value: float,
) -> WindowSpec:
    full_len = float(np.max(t_rel_s) - np.min(t_rel_s))
    if full_len < float(length_s):
        return WindowSpec(f"{length_s}s_best_attack", float(length_s), "best_attack", np.nan, np.nan, skip_reason="full_pass_shorter_than_window")
    best_start = float("nan")
    best_score = float("inf")
    for start in sliding_window_starts(t_rel_s, float(length_s)):
        stop = float(start + length_s)
        mask = slice_mask(t_rel_s, start, stop)
        if int(mask.sum()) < 3:
            continue
        fit = fit_on_mask(y_obs, f_geo_claimed, t_rel_s, mask)
        normalized = fit.score_rmse_hz / threshold_value if threshold_value > 0 else float("inf")
        if normalized < best_score:
            best_score = float(normalized)
            best_start = float(start)
    if not np.isfinite(best_start):
        return WindowSpec(f"{length_s}s_best_attack", float(length_s), "best_attack", np.nan, np.nan, skip_reason="no_valid_sliding_window")
    return WindowSpec(f"{length_s}s_best_attack", float(length_s), "best_attack", best_start, best_start + float(length_s), best_score)


def rodrigues_rotate(vector: np.ndarray, axis: np.ndarray, angle_rad: float) -> np.ndarray:
    axis = base.normalize(axis)
    return (
        vector * math.cos(angle_rad)
        + np.cross(axis, vector) * math.sin(angle_rad)
        + axis * float(np.dot(axis, vector)) * (1.0 - math.cos(angle_rad))
    )


def synthetic_inclination_offset_geo(
    sat: Any,
    station: Any,
    ts: Any,
    times: list[datetime],
    simulation_center_freq_hz: float,
    inclination_offset_deg: float,
) -> np.ndarray:
    """Minimal reproducible circular-orbit inclination perturbation.

    The construction follows the existing same-plane synthetic orbit builder.
    It uses the target mid-pass ECI state as phase anchor, keeps radius and
    phase, and rotates the orbital angular-momentum vector around the line of
    nodes so that only inclination changes in the inertial frame.
    """
    sky_times = ts.from_datetimes(times)
    geocentric = sat.at(sky_times)
    pos_km = geocentric.position.km.T
    vel_km_s = geocentric.velocity.km_per_s.T
    mid = len(times) // 2
    r0 = pos_km[mid]
    v0 = vel_km_s[mid]
    h_hat = base.normalize(np.cross(r0, v0))
    z_hat = np.array([0.0, 0.0, 1.0])
    node_hat = np.cross(z_hat, h_hat)
    if float(np.linalg.norm(node_hat)) < 1e-8:
        node_hat = base.normalize(r0)
    else:
        node_hat = base.normalize(node_hat)
    target_delta_i = math.radians(float(inclination_offset_deg))
    candidates = [
        rodrigues_rotate(h_hat, node_hat, target_delta_i),
        rodrigues_rotate(h_hat, node_hat, -target_delta_i),
    ]
    current_i = math.acos(float(np.clip(np.dot(h_hat, z_hat), -1.0, 1.0)))
    desired_i = current_i + target_delta_i
    h_new = min(candidates, key=lambda h: abs(math.acos(float(np.clip(np.dot(h, z_hat), -1.0, 1.0))) - desired_i))
    p_hat = base.normalize(r0)
    q_hat = base.normalize(np.cross(h_new, p_hat))
    if float(np.dot(v0, q_hat)) < 0:
        q_hat = -q_hat
    radius_km = float(np.linalg.norm(r0))
    angular_rate_rad_s = float(np.sqrt(base.MU_EARTH_KM3_S2 / radius_km**3))
    t_centered = np.array([(dt - times[mid]).total_seconds() for dt in times], dtype=float)
    theta = angular_rate_rad_s * t_centered
    attack_pos_km = radius_km * (np.cos(theta)[:, None] * p_hat + np.sin(theta)[:, None] * q_hat)
    station_pos_km = station.at(sky_times).position.km.T
    range_m = np.linalg.norm(attack_pos_km - station_pos_km, axis=1) * 1000.0
    step_s = float(np.median(np.diff([dt.timestamp() for dt in times]))) if len(times) > 1 else 1.0
    range_rate_mps = np.gradient(range_m, step_s)
    doppler_hz = -simulation_center_freq_hz * range_rate_mps / base.C_MPS
    return simulation_center_freq_hz + doppler_hz


def attack_specs(args: argparse.Namespace) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for value in args.altitude_deltas_km:
        if float(value) == 0.0:
            continue
        specs.append(
            {
                "attack_type": "same_plane_altitude_offset",
                "attack_variant": f"delta_h_{float(value):+g}km",
                "attack_param_name": "delta_h_km",
                "attack_param_value": float(value),
                "altitude_offset_km": float(value),
                "phase_offset_s": 0.0,
                "inclination_offset_deg": 0.0,
                "raan_offset_deg": 0.0,
            }
        )
    for value in args.phase_offsets_s:
        if float(value) == 0.0:
            continue
        specs.append(
            {
                "attack_type": "same_plane_phase_offset",
                "attack_variant": f"phase_offset_{float(value):+g}s",
                "attack_param_name": "phase_offset_s",
                "attack_param_value": float(value),
                "altitude_offset_km": 0.0,
                "phase_offset_s": float(value),
                "inclination_offset_deg": 0.0,
                "raan_offset_deg": 0.0,
            }
        )
    for value in args.inclination_deltas_deg:
        if float(value) == 0.0:
            continue
        specs.append(
            {
                "attack_type": "inclination_offset",
                "attack_variant": f"delta_i_{float(value):+g}deg",
                "attack_param_name": "delta_inclination_deg",
                "attack_param_value": float(value),
                "altitude_offset_km": 0.0,
                "phase_offset_s": 0.0,
                "inclination_offset_deg": float(value),
                "raan_offset_deg": 0.0,
            }
        )
    return specs


def generate_attack_geo(spec: dict[str, Any], sat: Any, station: Any, ts: Any, times: list[datetime], freq: float) -> np.ndarray:
    if spec["attack_type"] == "inclination_offset":
        return synthetic_inclination_offset_geo(sat, station, ts, times, freq, float(spec["inclination_offset_deg"]))
    return base.synthetic_same_plane_geo(
        sat=sat,
        station=station,
        ts=ts,
        times=times,
        simulation_center_freq_hz=freq,
        altitude_offset_km=float(spec["altitude_offset_km"]),
        phase_offset_s=float(spec["phase_offset_s"]),
    )


def calibrate_thresholds_and_gates(
    *,
    target_name: str,
    target_id: str,
    geo: pd.DataFrame,
    f_geo_a: np.ndarray,
    ranges: dict[str, list[float]],
    window_specs: list[WindowSpec],
    threshold_types: list[str],
    num_benign_sims: int,
    seed: int,
    rng: np.random.Generator,
    b_global: tuple[float, float],
    k_global: tuple[float, float],
    weak_factor: float,
) -> tuple[dict[tuple[str, str], dict[str, float]], list[base.ObservationSequence]]:
    benign_obs: list[base.ObservationSequence] = []
    for sample_id in range(1, num_benign_sims + 1):
        err = base.sample_error_params(ranges, rng)
        benign_obs.append(base.build_legitimate_observation(f"benign_{target_id}_{sample_id:04d}", target_name, target_id, geo, err, rng, sample_id, seed))
    cal: dict[tuple[str, str], dict[str, float]] = {}
    t_rel = geo["t_rel_s"].to_numpy(float)
    for spec in window_specs:
        if spec.skip_reason:
            continue
        mask = slice_mask(t_rel, spec.start_s, spec.stop_s)
        if int(mask.sum()) < 3:
            continue
        fits = [fit_on_mask(obs.y_obs_hz, f_geo_a, t_rel, mask) for obs in benign_obs]
        scores = np.array([fit.score_rmse_hz for fit in fits], dtype=float)
        b_vals = np.array([fit.b_hat_hz for fit in fits], dtype=float)
        k_vals = np.array([fit.k_hat_hz_s for fit in fits], dtype=float)
        for th in threshold_types:
            q = quantile_type_to_q(th)
            b_lo, b_hi = float(np.quantile(b_vals, 1.0 - q)), float(np.quantile(b_vals, q))
            k_lo, k_hi = float(np.quantile(k_vals, 1.0 - q)), float(np.quantile(k_vals, q))
            b_mid, k_mid = 0.5 * (b_lo + b_hi), 0.5 * (k_lo + k_hi)
            weak_b_half = 0.5 * (b_hi - b_lo) * weak_factor
            weak_k_half = 0.5 * (k_hi - k_lo) * weak_factor
            cal[(spec.window_type, th)] = {
                "threshold": float(np.quantile(scores, q)),
                "strong_b_min": max(float(b_global[0]), b_lo),
                "strong_b_max": min(float(b_global[1]), b_hi),
                "strong_k_min": max(float(k_global[0]), k_lo),
                "strong_k_max": min(float(k_global[1]), k_hi),
                "weak_b_min": max(float(b_global[0]), b_mid - weak_b_half),
                "weak_b_max": min(float(b_global[1]), b_mid + weak_b_half),
                "weak_k_min": max(float(k_global[0]), k_mid - weak_k_half),
                "weak_k_max": min(float(k_global[1]), k_mid + weak_k_half),
                "calibration_n": float(len(scores)),
                "threshold_source": f"window_specific_{th}_benign_A",
            }
    return cal, benign_obs


def calibrate_existing_benign_for_spec(
    *,
    benign_obs: list[base.ObservationSequence],
    geo: pd.DataFrame,
    f_geo_a: np.ndarray,
    spec: WindowSpec,
    threshold_types: list[str],
    b_global: tuple[float, float],
    k_global: tuple[float, float],
    weak_factor: float,
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    t_rel = geo["t_rel_s"].to_numpy(float)
    mask = slice_mask(t_rel, spec.start_s, spec.stop_s)
    if int(mask.sum()) < 3:
        return out
    fits = [fit_on_mask(obs.y_obs_hz, f_geo_a, t_rel, mask) for obs in benign_obs]
    scores = np.array([fit.score_rmse_hz for fit in fits], dtype=float)
    b_vals = np.array([fit.b_hat_hz for fit in fits], dtype=float)
    k_vals = np.array([fit.k_hat_hz_s for fit in fits], dtype=float)
    for th in threshold_types:
        q = quantile_type_to_q(th)
        b_lo, b_hi = float(np.quantile(b_vals, 1.0 - q)), float(np.quantile(b_vals, q))
        k_lo, k_hi = float(np.quantile(k_vals, 1.0 - q)), float(np.quantile(k_vals, q))
        b_mid, k_mid = 0.5 * (b_lo + b_hi), 0.5 * (k_lo + k_hi)
        weak_b_half = 0.5 * (b_hi - b_lo) * weak_factor
        weak_k_half = 0.5 * (k_hi - k_lo) * weak_factor
        out[th] = {
            "threshold": float(np.quantile(scores, q)),
            "strong_b_min": max(float(b_global[0]), b_lo),
            "strong_b_max": min(float(b_global[1]), b_hi),
            "strong_k_min": max(float(k_global[0]), k_lo),
            "strong_k_max": min(float(k_global[1]), k_hi),
            "weak_b_min": max(float(b_global[0]), b_mid - weak_b_half),
            "weak_b_max": min(float(b_global[1]), b_mid + weak_b_half),
            "weak_k_min": max(float(k_global[0]), k_mid - weak_k_half),
            "weak_k_max": min(float(k_global[1]), k_mid + weak_k_half),
            "calibration_n": float(len(scores)),
            "threshold_source": f"window_specific_{th}_benign_A_at_best_attack_position",
        }
    return out


def decision_for(
    verifier_type: str,
    fit: base.FitResult,
    threshold: float,
    cal: dict[str, float],
    n_points: int,
    mean_elevation: float,
    args: argparse.Namespace,
) -> dict[str, Any]:
    score_gate = bool(fit.score_rmse_hz <= threshold)
    if verifier_type == "shape_only":
        b_gate = True
        k_gate = True
        quality_gate = True
        final = "ACCEPT" if score_gate else "REJECT"
    elif verifier_type == "weak_prior":
        b_gate = bool(cal["weak_b_min"] <= fit.b_hat_hz <= cal["weak_b_max"])
        k_gate = bool(cal["weak_k_min"] <= fit.k_hat_hz_s <= cal["weak_k_max"])
        quality_gate = bool(n_points >= args.weak_min_points)
        if not quality_gate:
            final = "DEFER"
        else:
            final = "ACCEPT" if (score_gate and b_gate and k_gate) else "REJECT"
    else:
        b_gate = bool(cal["strong_b_min"] <= fit.b_hat_hz <= cal["strong_b_max"])
        k_gate = bool(cal["strong_k_min"] <= fit.k_hat_hz_s <= cal["strong_k_max"])
        quality_gate = bool(n_points >= args.strong_min_points and mean_elevation >= args.quality_min_mean_elevation_deg)
        if not quality_gate:
            final = "DEFER"
        else:
            final = "ACCEPT" if (score_gate and b_gate and k_gate) else "REJECT"
    return {
        "score_gate_pass": score_gate,
        "b_gate_pass": bool(b_gate),
        "k_gate_pass": bool(k_gate),
        "quality_gate_pass": bool(quality_gate),
        "final_decision": final,
    }


def append_eval_rows(
    rows: list[dict[str, Any]],
    *,
    observation: base.ObservationSequence,
    target_id: str,
    target_name: str,
    attack_type: str,
    attack_param_name: str,
    attack_param_value: float | str,
    is_benign: bool,
    f_geo_a: np.ndarray,
    geo: pd.DataFrame,
    window_specs: list[WindowSpec],
    calibration: dict[tuple[str, str], dict[str, float]],
    threshold_types: list[str],
    verifier_types: list[str],
    args: argparse.Namespace,
) -> None:
    t_rel = geo["t_rel_s"].to_numpy(float)
    for spec in window_specs:
        if spec.skip_reason:
            continue
        mask = slice_mask(t_rel, spec.start_s, spec.stop_s)
        if int(mask.sum()) < 3:
            continue
        metrics = window_metrics(geo, spec, mask)
        fit = fit_on_mask(observation.y_obs_hz, f_geo_a, t_rel, mask)
        extra = residual_stats(observation.y_obs_hz, f_geo_a, t_rel, mask, fit)
        for th in threshold_types:
            cal = calibration.get((spec.window_type, th))
            if cal is None:
                continue
            threshold = float(cal["threshold"])
            for verifier_type in verifier_types:
                dec = decision_for(verifier_type, fit, threshold, cal, int(metrics["n_points"]), float(metrics["mean_elevation_deg"]), args)
                rows.append(
                    {
                        "sequence_id": observation.sequence_id,
                        "target_id": target_id,
                        "target_name": target_name,
                        "attack_type": attack_type,
                        "attack_param_name": attack_param_name,
                        "attack_param_value": attack_param_value,
                        **metrics,
                        "verifier_type": verifier_type,
                        "threshold_type": th,
                        "threshold_value_hz": threshold,
                        "score_rmse_hz": float(fit.score_rmse_hz),
                        "normalized_score": float(fit.score_rmse_hz / threshold) if threshold > 0 else np.nan,
                        "b_hat_hz": float(fit.b_hat_hz),
                        "k_hat_hz_per_s": float(fit.k_hat_hz_s),
                        **dec,
                        "is_benign": bool(is_benign),
                        "is_attack": bool(not is_benign),
                        **extra,
                        "best_attack_selection_score": spec.selection_score,
                        "skip_reason": "",
                        "threshold_source": cal["threshold_source"],
                        "weak_prior_definition": f"per-window benign b/k quantile range widened by factor {args.weak_prior_factor:g}, clipped to global main_range",
                        "strong_prior_definition": "per-window benign b/k quantile range intersected with global b/k main_range plus quality gate",
                    }
                )


def add_skip_rows(rows: list[dict[str, Any]], target_id: str, target_name: str, spec: WindowSpec, reason: str) -> None:
    rows.append(
        {
            "sequence_id": f"skip_{target_id}_{spec.window_type}",
            "target_id": target_id,
            "target_name": target_name,
            "attack_type": "skip",
            "attack_param_name": "",
            "attack_param_value": "",
            "window_type": spec.window_type,
            "window_length_s": spec.window_length_s,
            "window_position": spec.window_position,
            "window_start_time": "",
            "window_stop_time": "",
            "window_center_time": "",
            "n_points": 0,
            "max_elevation_deg": np.nan,
            "mean_elevation_deg": np.nan,
            "verifier_type": "",
            "threshold_type": "",
            "threshold_value_hz": np.nan,
            "score_rmse_hz": np.nan,
            "normalized_score": np.nan,
            "b_hat_hz": np.nan,
            "k_hat_hz_per_s": np.nan,
            "score_gate_pass": False,
            "b_gate_pass": False,
            "k_gate_pass": False,
            "quality_gate_pass": False,
            "final_decision": "SKIP",
            "is_benign": False,
            "is_attack": False,
            "raw_delta_rmse_hz": np.nan,
            "detrended_residual_std_hz": np.nan,
            "residual_p95_abs_hz": np.nan,
            "best_attack_selection_score": np.nan,
            "skip_reason": reason,
        }
    )


def aggregate_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    data = dataset[dataset["final_decision"].isin(["ACCEPT", "REJECT", "DEFER"])].copy()
    group_cols = ["window_type", "window_length_s", "window_position", "attack_type", "attack_param_value", "verifier_type", "threshold_type"]
    rows: list[dict[str, Any]] = []
    for key, g in data.groupby(group_cols, dropna=False):
        benign = g[g["is_benign"]]
        attack = g[g["is_attack"]]
        accepted = g["final_decision"].eq("ACCEPT")
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n": int(len(g)),
                "benign_accept_rate": float(benign["final_decision"].eq("ACCEPT").mean()) if len(benign) else np.nan,
                "benign_reject_rate": float(benign["final_decision"].eq("REJECT").mean()) if len(benign) else np.nan,
                "attack_accept_rate": float(attack["final_decision"].eq("ACCEPT").mean()) if len(attack) else np.nan,
                "attack_defer_rate": float(attack["final_decision"].eq("DEFER").mean()) if len(attack) else np.nan,
                "attack_reject_rate": float(attack["final_decision"].eq("REJECT").mean()) if len(attack) else np.nan,
                "score_gate_pass_rate": float(g["score_gate_pass"].mean()) if len(g) else np.nan,
                "b_gate_pass_rate": float(g["b_gate_pass"].mean()) if len(g) else np.nan,
                "k_gate_pass_rate": float(g["k_gate_pass"].mean()) if len(g) else np.nan,
                "quality_gate_pass_rate": float(g["quality_gate_pass"].mean()) if len(g) else np.nan,
                "score_median_hz": float(g["score_rmse_hz"].median()),
                "score_p95_hz": float(g["score_rmse_hz"].quantile(0.95)),
                "normalized_score_median": float(g["normalized_score"].median()),
                "normalized_score_p95": float(g["normalized_score"].quantile(0.95)),
                "b_hat_median": float(g["b_hat_hz"].median()),
                "b_hat_p95_abs": float(g["b_hat_hz"].abs().quantile(0.95)),
                "k_hat_median": float(g["k_hat_hz_per_s"].median()),
                "k_hat_p95_abs": float(g["k_hat_hz_per_s"].abs().quantile(0.95)),
                "accepted_sequences": int(accepted.sum()),
            }
        )
    return pd.DataFrame(rows)


def bk_contribution_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    attack = dataset[(dataset["is_attack"]) & (dataset["final_decision"].isin(["ACCEPT", "REJECT", "DEFER"]))].copy()
    group_cols = ["window_type", "window_length_s", "window_position", "attack_type", "attack_param_value", "threshold_type"]
    rows: list[dict[str, Any]] = []
    for key, g in attack.groupby(group_cols, dropna=False):
        rates: dict[str, float] = {}
        for verifier in ["shape_only", "weak_prior", "strong_prior"]:
            part = g[g["verifier_type"] == verifier]
            rates[verifier] = float(part["final_decision"].eq("ACCEPT").mean()) if len(part) else np.nan
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "shape_only_attack_accept_rate": rates["shape_only"],
                "weak_prior_attack_accept_rate": rates["weak_prior"],
                "strong_prior_attack_accept_rate": rates["strong_prior"],
                "bk_gate_delta": rates["shape_only"] - rates["strong_prior"] if np.isfinite(rates["shape_only"]) and np.isfinite(rates["strong_prior"]) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_attack_accept_rate(summary: pd.DataFrame, out: Path) -> None:
    data = summary[(summary["threshold_type"] == "p95") & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))].copy()
    data = data.groupby(["window_length_s", "window_position", "attack_type", "verifier_type"], as_index=False)["attack_accept_rate"].mean()
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharey=True)
    for ax, attack_type in zip(axes, ["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]):
        part = data[(data["attack_type"] == attack_type) & (data["window_position"].isin(["full_pass", "middle", "best_attack"]))]
        for verifier, g in part.groupby("verifier_type"):
            agg = g.groupby("window_length_s", as_index=False)["attack_accept_rate"].mean().sort_values("window_length_s")
            ax.plot(agg["window_length_s"], agg["attack_accept_rate"], marker="o", label=verifier)
        ax.set_title(attack_type.replace("_", " "))
        ax.set_xlabel("window length (s)")
        ax.grid(True, alpha=0.25)
    axes[0].set_ylabel("attack accept rate")
    axes[-1].legend(fontsize=8)
    savefig(fig, out)


def plot_benign_accept_rate(summary: pd.DataFrame, out: Path) -> None:
    benign = summary[(summary["threshold_type"] == "p95") & (summary["attack_type"] == "benign_A")].copy()
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for verifier, g in benign.groupby("verifier_type"):
        agg = g.groupby("window_length_s", as_index=False)["benign_accept_rate"].mean().sort_values("window_length_s")
        ax.plot(agg["window_length_s"], agg["benign_accept_rate"], marker="o", label=verifier)
    ax.set_xlabel("window length (s)")
    ax.set_ylabel("benign accept rate")
    ax.set_ylim(0, 1.05)
    ax.set_title("Benign Accept Rate vs Window Length")
    ax.legend()
    ax.grid(True, alpha=0.25)
    savefig(fig, out)


def plot_bk_contribution(bk: pd.DataFrame, out: Path) -> None:
    data = bk[bk["threshold_type"] == "p95"].copy()
    data = data.groupby(["window_length_s", "attack_type"], as_index=False)["bk_gate_delta"].mean()
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    for attack_type, g in data.groupby("attack_type"):
        ax.plot(g.sort_values("window_length_s")["window_length_s"], g.sort_values("window_length_s")["bk_gate_delta"], marker="o", label=attack_type)
    ax.set_xlabel("window length (s)")
    ax.set_ylabel("shape_only accept rate - strong_prior accept rate")
    ax.set_title("b/k Gate Contribution by Window")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)
    savefig(fig, out)


def plot_middle_vs_best(summary: pd.DataFrame, out: Path) -> None:
    data = summary[
        (summary["threshold_type"] == "p95")
        & (summary["verifier_type"] == "strong_prior")
        & (summary["window_position"].isin(["middle", "best_attack"]))
        & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))
    ].copy()
    piv = data.groupby(["window_length_s", "window_position"], as_index=False)["attack_accept_rate"].mean().pivot(index="window_length_s", columns="window_position", values="attack_accept_rate")
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    piv.sort_index().plot(kind="bar", ax=ax, color=["#4c78a8", "#c1665a"])
    ax.set_xlabel("window length (s)")
    ax.set_ylabel("attack accept rate")
    ax.set_title("Middle vs Best-Attack Window")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def plot_attack_type_comparison(summary: pd.DataFrame, out: Path) -> None:
    data = summary[
        (summary["threshold_type"] == "p95")
        & (summary["verifier_type"] == "strong_prior")
        & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))
    ].copy()
    piv = data.groupby(["window_length_s", "attack_type"], as_index=False)["attack_accept_rate"].mean().pivot(index="window_length_s", columns="attack_type", values="attack_accept_rate")
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    piv.sort_index().plot(kind="bar", ax=ax)
    ax.set_xlabel("window length (s)")
    ax.set_ylabel("attack accept rate")
    ax.set_title("Attack Type Comparison by Window")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    savefig(fig, out)


def plot_score_distribution(dataset: pd.DataFrame, out: Path) -> None:
    data = dataset[(dataset["threshold_type"] == "p95") & (dataset["verifier_type"] == "shape_only") & (dataset["final_decision"].isin(["ACCEPT", "REJECT"]))].copy()
    fig, ax = plt.subplots(figsize=(9, 5))
    for label, group, color in [
        ("benign", data[data["is_benign"]], "#4c78a8"),
        ("attack", data[data["is_attack"]], "#c1665a"),
    ]:
        vals = group["normalized_score"].dropna().clip(upper=5.0).to_numpy(float)
        if len(vals):
            ax.hist(vals, bins=60, density=True, alpha=0.45, label=label, color=color)
    ax.axvline(1.0, color="black", linestyle="--", linewidth=1.2, label="threshold")
    ax.set_xlabel("normalized_score")
    ax.set_ylabel("density")
    ax.set_title("Normalized Score Distribution by Window")
    ax.legend()
    ax.grid(True, alpha=0.25)
    savefig(fig, out)


def make_plots(dataset: pd.DataFrame, summary: pd.DataFrame, bk: pd.DataFrame, figures_dir: Path) -> list[Path]:
    paths = [
        figures_dir / "attack_accept_rate_vs_window_length.png",
        figures_dir / "benign_accept_rate_vs_window_length.png",
        figures_dir / "bk_gate_contribution_by_window.png",
        figures_dir / "middle_vs_best_attack_accept_rate.png",
        figures_dir / "attack_type_comparison_by_window.png",
        figures_dir / "normalized_score_distribution_by_window.png",
    ]
    plot_attack_accept_rate(summary, paths[0])
    plot_benign_accept_rate(summary, paths[1])
    plot_bk_contribution(bk, paths[2])
    plot_middle_vs_best(summary, paths[3])
    plot_attack_type_comparison(summary, paths[4])
    plot_score_distribution(dataset, paths[5])
    return paths


def md_table(df: pd.DataFrame, columns: list[str], n: int = 20) -> str:
    if df.empty:
        return "无"
    part = df.loc[:, [c for c in columns if c in df.columns]].head(n).copy()
    for c in part.columns:
        if pd.api.types.is_float_dtype(part[c]):
            part[c] = part[c].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
    headers = list(part.columns)
    rows = [[str(value) for value in row] for row in part.to_numpy()]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def write_report(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, bk: pd.DataFrame, figure_paths: list[Path]) -> None:
    valid = dataset[dataset["final_decision"].isin(["ACCEPT", "REJECT", "DEFER"])].copy()
    target_n = int(valid["target_id"].nunique()) if not valid.empty else 0
    benign_seq = int(valid[valid["is_benign"]]["sequence_id"].nunique())
    attack_seq = int(valid[valid["is_attack"]]["sequence_id"].nunique())
    p95_strong = summary[(summary["threshold_type"] == "p95") & (summary["verifier_type"] == "strong_prior")]
    attack_compare = p95_strong[p95_strong["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"])].groupby("attack_type", as_index=False)["attack_accept_rate"].mean().sort_values("attack_accept_rate", ascending=False)
    most_dangerous = str(attack_compare.iloc[0]["attack_type"]) if not attack_compare.empty else "样本不足"
    full_attack = p95_strong[(p95_strong["window_position"] == "full_pass") & (p95_strong["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))]["attack_accept_rate"].mean()
    short_attack = p95_strong[(p95_strong["window_length_s"].isin([30.0, 60.0])) & (p95_strong["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))]["attack_accept_rate"].mean()
    middle = p95_strong[p95_strong["window_position"] == "middle"]["attack_accept_rate"].mean()
    best = p95_strong[p95_strong["window_position"] == "best_attack"]["attack_accept_rate"].mean()
    bk_by_len = bk[bk["threshold_type"] == "p95"].groupby("window_length_s", as_index=False)["bk_gate_delta"].mean().sort_values("window_length_s")
    main_table = p95_strong.groupby(["window_type", "window_length_s", "window_position", "attack_type"], as_index=False).agg(
        attack_accept_rate=("attack_accept_rate", "mean"),
        benign_accept_rate=("benign_accept_rate", "mean"),
        normalized_score_median=("normalized_score_median", "mean"),
    )
    figures = "\n".join(f"- `{p.as_posix()}`" for p in figure_paths)
    text = f"""# Window reliability calibration summary

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 实验目的

本轮实验标定当前单站 Doppler residual claimed-identity verifier 在不完整观测窗口下的可靠性。它只评估 controlled station、真实 Starlink TLE、受控 Ku-band 载频、经验 effective residual 误差模型和规则化轨道相似攻击集合下的经验现象，不评价主动频率补偿攻击，也不把短窗口直接设计成最终 ACCEPT 策略。

## 2. 为什么加入 inclination_offset

已有高度偏移和相位偏移主要改变同轨道面内的径向/沿轨几何。`inclination_offset` 属于 orbit-plane offset，用于检查 cross-track / 轨道面相似性是否会在短窗口中形成新的高风险样本。本轮只改变 inclination，不同时加入 RAAN offset，避免变量耦合。

## 3. 实验矩阵

- target 数量：`{target_n}`
- benign_A 序列数：`{benign_seq}`
- attack 序列数：`{attack_seq}`
- attack 类型：`same_plane_altitude_offset`、`same_plane_phase_offset`、`inclination_offset`
- window：`full_pass`、`180/120/60/30s_middle`，以及 `{ '180/120/60/30s_best_attack' if args.include_best_attack else '未启用 best_attack' }`
- threshold：window-specific `p95` / `p99`
- verifier：`shape_only`、`weak_prior`、`strong_prior`

best_attack 选择标准：对每个 target / attack 参数，在完整过境内按 1 s 步长滑动，使用无噪声 `f_geo_B(t) - f_geo_A(t)` 几何差异选择 `normalized_score = score / window_specific_p95_threshold` 最低的窗口；随后在该窗口位置用 benign_A 样本重新校准 window-specific threshold。该设置是 diagnostic 风险上界，不表示攻击源能利用随机噪声或主动调频。

## 4. verifier 三版本定义

- `shape_only`：只使用 residual RMSE score gate。
- `weak_prior`：score gate + per-window benign b/k quantile gate 放宽 `{args.weak_prior_factor:g}` 倍，并裁剪到全局 main_range；质量门限仅要求 `n_points >= {args.weak_min_points}`。
- `strong_prior`：score gate + per-window benign b/k quantile gate 与全局 b/k main_range 的交集，并要求 `n_points >= {args.strong_min_points}` 与 mean elevation 下限 `{args.quality_min_mean_elevation_deg:g}` deg。

这里的 `b_hat/k_hat` 是 claimed target A 条件下拟合出的 effective residual 线性参数，不是 true CFO，也不是攻击源精确可控变量。

## 5. 主要结果表

以下为 `p95 + strong_prior` 的聚合结果节选：

{md_table(main_table, ["window_type", "window_length_s", "window_position", "attack_type", "attack_accept_rate", "benign_accept_rate", "normalized_score_median"], 30)}

## 6. 三类轨道相似攻击对比

{md_table(attack_compare, ["attack_type", "attack_accept_rate"], 10)}

当前设置下平均 attack accept rate 最高的是：`{most_dangerous}`。如果 inclination_offset 排在前列，应作为下一轮轨道相似攻击扩展重点；如果不是，也说明本轮 cross-track 小扰动在当前 station/pass 组合下未比高度或相位偏移更危险。

## 7. b/k gate 对不同窗口的贡献

`bk_gate_delta = shape_only_attack_accept_rate - strong_prior_attack_accept_rate`：

{md_table(bk_by_len, ["window_length_s", "bk_gate_delta"], 20)}

该表用于拆分完整曲线形状与 fitted-parameter sanity gate 的贡献。短窗口中如果 `bk_gate_delta` 明显上升，说明短窗口更依赖 b/k gate 来拒绝可由线性项吸收的轨道几何差异。

## 8. middle 与 best_attack 差异

- `p95 + strong_prior` middle 平均 attack accept rate：`{middle:.4f}`
- `p95 + strong_prior` best_attack 平均 attack accept rate：`{best:.4f}`

best_attack 是 diagnostic 上界搜索，不代表攻击源主动调频或在线挑选窗口；它用于标定同一 full-pass 内局部片段最危险的位置。

## 9. 阶段性回答

1. full-pass 相比短窗口是否显著降低误接受率：当前 full-pass 平均 attack accept rate 为 `{full_attack:.4f}`，30s/60s 平均为 `{short_attack:.4f}`。若后者更高，说明短窗口形状证据更弱，应作为弱证据累计或 DEFER。
2. 30s / 60s 是否更依赖 b/k gate：见第 7 节 `bk_gate_delta`。短窗口 delta 越大，依赖越强。
3. middle 与 best_attack 差异：见第 8 节。best_attack 高于 middle 表示认证窗口位置会显著影响风险。
4. 三类攻击中哪类最危险：本轮均值最高为 `{most_dangerous}`。
5. strong evidence / weak evidence：full-pass 和较长窗口可作为 strong evidence 的候选；30s/60s 若出现较高 attack accept rate 或强依赖 b/k gate，应只作为 weak evidence 或输出 DEFER。
6. 下一轮是否进入 location-aware active compensation under partial observation：建议先基于本轮结果设计 window-aware evidence accumulation verifier；只有在短窗口风险被清楚标定后，再进入 location-aware active compensation under partial observation。

## 10. 生成文件

- `{args.dataset_output.as_posix()}`
- `{args.summary_output.as_posix()}`
- `{args.bk_output.as_posix()}`
- `{args.report_output.as_posix()}`
{figures}

## 11. 局限和下一步

本轮仍是 controlled orbit-based diagnostic。它没有复现真实 SatNOGS Starlink observation，没有评价真实 Ku-band residual 分布，也没有实现主动频率补偿。下一步应把窗口结果转成 window-aware evidence accumulation verifier，并把短窗口通过策略改为累计证据或 DEFER，而不是单窗口直接 ACCEPT。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_work_log(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, bk: pd.DataFrame, commands: list[str]) -> None:
    log = Path("logs/work_log.md")
    valid = dataset[dataset["final_decision"].isin(["ACCEPT", "REJECT", "DEFER"])]
    p95_strong = summary[(summary["threshold_type"] == "p95") & (summary["verifier_type"] == "strong_prior")]
    attack_mean = p95_strong[p95_strong["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"])]["attack_accept_rate"].mean()
    benign_mean = p95_strong[p95_strong["attack_type"] == "benign_A"]["benign_accept_rate"].mean()
    command_text = "\n\n".join(f"```bash\n{cmd}\n```" for cmd in commands)
    text = f"""

## {datetime.now().strftime("%Y-%m-%d %H:%M")} - window reliability calibration

### A. 本轮目标

完成第一轮不完整观测窗口可靠性标定，比较 full-pass、180s、120s、60s、30s middle/best_attack 窗口下 shape_only、weak_prior、strong_prior verifier 对 benign_A 和三类规则化轨道相似攻击的通过率。

### B. 实际操作

- 新增 `scripts/run_window_reliability_calibration.py`。
- 复用 controlled Starlink selection/candidate library、TLE、经验 effective residual 参数采样、residual b+k 拟合。
- 新增 `inclination_offset` 最小圆轨道近似扰动；未加入 RAAN offset，未加入主动频率补偿 `u(t)`。
- 运行 smoke test 后运行主实验。

### C. 新增/修改文件

- 新增/修改：`scripts/run_window_reliability_calibration.py`
- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.bk_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}/attack_accept_rate_vs_window_length.png` 等 6 张图
- 追加：`logs/work_log.md`

### D. 运行命令

{command_text}

### E. 结果摘要

- 有效逐序列判决行数：`{len(valid)}`。
- target 数量：`{valid['target_id'].nunique() if not valid.empty else 0}`。
- p95 strong_prior 平均 benign accept rate：`{benign_mean:.4f}`。
- p95 strong_prior 平均 attack accept rate：`{attack_mean:.4f}`。
- b/k gate contribution 输出行数：`{len(bk)}`。

### F. 问题与下一步

本轮是 window reliability diagnostic，不是最终防御策略。下一步建议依据短窗口风险和 b/k gate 贡献，设计 window-aware evidence accumulation verifier；短窗口高风险时优先作为 weak evidence 或 DEFER。
"""
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    outputs = [args.dataset_output, args.summary_output, args.bk_output, args.report_output]
    outputs.extend(
        [
            args.figures_dir / "attack_accept_rate_vs_window_length.png",
            args.figures_dir / "benign_accept_rate_vs_window_length.png",
            args.figures_dir / "bk_gate_contribution_by_window.png",
            args.figures_dir / "middle_vs_best_attack_accept_rate.png",
            args.figures_dir / "attack_type_comparison_by_window.png",
            args.figures_dir / "normalized_score_distribution_by_window.png",
        ]
    )
    check_outputs(outputs, args.overwrite)
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=args.max_targets,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    if orbit_cfg.get("mode") != "controlled_starlink" or orbit_cfg.get("observation_id") is not None:
        fail("current experiment requires controlled_starlink mode and observation_id=null")
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    station = station_from_cfg(orbit_cfg)
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    b_global, k_global = load_global_ranges(args.parameter_config)
    rng = np.random.default_rng(args.seed)
    window_lengths = parse_window_lengths(args.window_lengths)
    if FULL_PASS_LENGTH_SENTINEL not in window_lengths:
        window_lengths = [FULL_PASS_LENGTH_SENTINEL] + window_lengths
    n_benign = int(args.num_benign_sims or max(50, args.num_sims_per_attack * 10))
    rows: list[dict[str, Any]] = []
    seq_counter = 1
    specs = attack_specs(args)

    for _, target in selection.head(args.max_targets).iterrows():
        target_id = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        if target_id not in tle:
            fail(f"target NORAD not found in TLE: {target_id}")
        sat = tle[target_id]["sat"]
        geo = ensure_target_elevation(base.target_geo_from_library(library, target_id), sat, station, ts)
        f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
        t_rel = geo["t_rel_s"].to_numpy(float)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        window_specs = [build_middle_window(t_rel, length) for length in window_lengths]
        for spec in window_specs:
            if spec.skip_reason:
                add_skip_rows(rows, target_id, target_name, spec, spec.skip_reason)
        valid_base_windows = [spec for spec in window_specs if not spec.skip_reason]
        calibration, benign_obs = calibrate_thresholds_and_gates(
            target_name=target_name,
            target_id=target_id,
            geo=geo,
            f_geo_a=f_geo_a,
            ranges=ranges,
            window_specs=valid_base_windows,
            threshold_types=args.threshold_types,
            num_benign_sims=n_benign,
            seed=args.seed,
            rng=rng,
            b_global=b_global,
            k_global=k_global,
            weak_factor=args.weak_prior_factor,
        )
        for obs in benign_obs:
            append_eval_rows(
                rows,
                observation=obs,
                target_id=target_id,
                target_name=target_name,
                attack_type="benign_A",
                attack_param_name="none",
                attack_param_value="none",
                is_benign=True,
                f_geo_a=f_geo_a,
                geo=geo,
                window_specs=valid_base_windows,
                calibration=calibration,
                threshold_types=args.threshold_types,
                verifier_types=args.verifier_types,
                args=args,
            )
        for spec in specs:
            f_geo_b = generate_attack_geo(spec, sat, station, ts, times, freq)
            best_windows_by_length: list[WindowSpec] = []
            if args.include_best_attack:
                for length in [v for v in window_lengths if v != FULL_PASS_LENGTH_SENTINEL]:
                    threshold = calibration.get((f"{length}s_middle", "p95"), {}).get("threshold")
                    if threshold is None:
                        continue
                    # Select once per target/attack geometry using the no-noise
                    # source curve. This avoids granting the attacker access to
                    # random noise while still finding the easiest geometric
                    # partial-window segment.
                    best_spec = choose_best_attack_window(f_geo_b, f_geo_a, t_rel, int(length), float(threshold))
                    if best_spec.skip_reason:
                        add_skip_rows(rows, target_id, target_name, best_spec, best_spec.skip_reason)
                        continue
                    best_windows_by_length.append(best_spec)
                    best_cal = calibrate_existing_benign_for_spec(
                        benign_obs=benign_obs,
                        geo=geo,
                        f_geo_a=f_geo_a,
                        spec=best_spec,
                        threshold_types=args.threshold_types,
                        b_global=b_global,
                        k_global=k_global,
                        weak_factor=args.weak_prior_factor,
                    )
                    for th, values in best_cal.items():
                        calibration[(best_spec.window_type, th)] = values
            for sample_id in range(1, args.num_sims_per_attack + 1):
                err = base.sample_error_params(ranges, rng)
                seq_id = f"wrc_attack_{seq_counter:07d}"
                seq_counter += 1
                obs = base.build_attack_observation(seq_id, target_name, target_id, geo, f_geo_b, spec, err, rng, sample_id, args.seed)
                windows = list(valid_base_windows) + best_windows_by_length
                append_eval_rows(
                    rows,
                    observation=obs,
                    target_id=target_id,
                    target_name=target_name,
                    attack_type=str(spec["attack_type"]),
                    attack_param_name=str(spec["attack_param_name"]),
                    attack_param_value=float(spec["attack_param_value"]),
                    is_benign=False,
                    f_geo_a=f_geo_a,
                    geo=geo,
                    window_specs=windows,
                    calibration=calibration,
                    threshold_types=args.threshold_types,
                    verifier_types=args.verifier_types,
                    args=args,
                )

    dataset = pd.DataFrame(rows)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output, index=False)
    summary = aggregate_summary(dataset)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    bk = bk_contribution_summary(dataset)
    args.bk_output.parent.mkdir(parents=True, exist_ok=True)
    bk.to_csv(args.bk_output, index=False)
    figure_paths = make_plots(dataset, summary, bk, args.figures_dir)
    write_report(args, dataset, summary, bk, figure_paths)
    commands = [
        "python -m py_compile scripts/run_window_reliability_calibration.py",
        "python scripts/run_window_reliability_calibration.py --max-targets 2 --max-passes-per-target 1 --num-sims-per-attack 2 --dataset-output outputs/datasets/window_reliability_calibration_smoke_dataset.csv --summary-output outputs/metrics/window_reliability_calibration_smoke_summary.csv --bk-output outputs/metrics/window_reliability_smoke_bk_gate_contribution.csv --report-output outputs/reports/window_reliability_calibration_smoke_summary.md --figures-dir outputs/figures/window_reliability_smoke --overwrite",
        "python scripts/run_window_reliability_calibration.py --overwrite",
    ]
    append_work_log(args, dataset, summary, bk, commands)
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.bk_output} rows={len(bk)}")
    print(f"wrote {args.report_output}")
    for path in figure_paths:
        print(path)


if __name__ == "__main__":
    main()
