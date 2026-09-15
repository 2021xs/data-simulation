#!/usr/bin/env python
"""Extended fixed-reference simulated compensation sensitivity experiment.

Offline mathematical simulation only.  The script computes Doppler curves from
local TLE/synthetic geometry and evaluates existing verifier logic.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_window_aware_evidence_accumulation as wae  # noqa: E402
import run_window_reliability_calibration as wrc  # noqa: E402


DEFAULT_E_VALUES = [0, 1, 2, 5, 10, 20, 50, 100, 200]
DEFAULT_BEARINGS = [0, 90, 180, 270]
DEFAULT_GROUPS = ["hard_case_weighted", "typical_orbit_similar", "random_simulated"]
DEFAULT_STRATEGIES = ["single_window_baseline", "proposed_v1", "candidate_v1_1", "full_pass"]
DEFAULT_WINDOW_MODES = [
    "full_pass",
    "single_30s_selected",
    "single_60s_selected",
    "spread_3x60s",
    "spread_6x30s",
    "selected_difficult_short_windows",
]


def parse_csv(values: str | list[str]) -> list[str]:
    if isinstance(values, list):
        parts: list[str] = []
        for value in values:
            parts.extend(str(value).split(","))
    else:
        parts = str(values).split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_float_csv(values: str | list[str]) -> list[float]:
    return [float(v) for v in parse_csv(values)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extended fixed-reference simulated compensation sensitivity.")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/fixed_reference_compensation_extended_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_extended_summary.csv"))
    p.add_argument("--strategy-comparison-output", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_strategy_comparison.csv"))
    p.add_argument("--bk-absorption-output", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_bk_absorption.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/fixed_reference_compensation_extended_summary.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/fixed_reference_compensation_extended"))
    p.add_argument("--e-values", nargs="+", default=",".join(str(v) for v in DEFAULT_E_VALUES))
    p.add_argument("--bearings", nargs="+", default=",".join(str(v) for v in DEFAULT_BEARINGS))
    p.add_argument("--sample-groups", nargs="+", default=",".join(DEFAULT_GROUPS))
    p.add_argument("--strategies", nargs="+", default=",".join(DEFAULT_STRATEGIES))
    p.add_argument("--window-modes", nargs="+", default=",".join(DEFAULT_WINDOW_MODES))
    p.add_argument("--max-targets", type=int, default=4)
    p.add_argument("--max-samples-per-group", type=int, default=6)
    p.add_argument("--num-benign-sims", type=int, default=50)
    p.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260612)
    p.add_argument("--include-500km", action="store_true")
    p.add_argument("--skip-random-simulated", action="store_true")
    p.add_argument("--plot-example-curves", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def rmse(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2)))


def serial(values: list[Any], fmt: str | None = None) -> str:
    out = []
    for value in values:
        out.append(f"{float(value):.6g}" if fmt == "float" else str(value))
    return ";".join(out)


def fixed_reference_geo(sat: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float, step_s: float) -> np.ndarray:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    geo = orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))
    return geo["f_geo_tle_hz"].to_numpy(float)


def synthetic_spec(attack_type: str, value: float) -> dict[str, Any]:
    if attack_type == "same_plane_altitude_offset":
        return {
            "attack_type": attack_type,
            "attack_variant": f"delta_h_{value:+g}km",
            "attack_param_name": "delta_h_km",
            "attack_param_value": float(value),
            "altitude_offset_km": float(value),
            "phase_offset_s": 0.0,
            "inclination_offset_deg": 0.0,
            "raan_offset_deg": 0.0,
        }
    if attack_type == "same_plane_phase_offset":
        return {
            "attack_type": attack_type,
            "attack_variant": f"phase_{value:+g}s",
            "attack_param_name": "phase_offset_s",
            "attack_param_value": float(value),
            "altitude_offset_km": 0.0,
            "phase_offset_s": float(value),
            "inclination_offset_deg": 0.0,
            "raan_offset_deg": 0.0,
        }
    if attack_type == "inclination_offset":
        return {
            "attack_type": attack_type,
            "attack_variant": f"delta_i_{value:+g}deg",
            "attack_param_name": "delta_inclination_deg",
            "attack_param_value": float(value),
            "altitude_offset_km": 0.0,
            "phase_offset_s": 0.0,
            "inclination_offset_deg": float(value),
            "raan_offset_deg": 0.0,
        }
    fail(f"unsupported synthetic attack type: {attack_type}")


def generate_synthetic_geo(spec: dict[str, Any], sat_a: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float) -> np.ndarray:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    return wrc.generate_attack_geo(spec, sat_a, site, ts, times, freq_hz)


def build_observation(
    sequence_id: str,
    target_name: str,
    target_id: str,
    geo: pd.DataFrame,
    y_obs: np.ndarray,
    source_curve: np.ndarray,
    noise: np.ndarray,
    b_hz: float,
    k_hz_s: float,
    sigma_hz: float,
    t0_s: float,
    relation_type: str,
    relation_variant: str,
) -> base.ObservationSequence:
    return base.ObservationSequence(
        sequence_id=sequence_id,
        source_type="ATTACK",
        claimed_target_name=target_name,
        claimed_target_norad=target_id,
        t_abs_utc=geo["t_abs_utc"].to_numpy(str),
        t_rel_s=geo["t_rel_s"].to_numpy(float),
        y_obs_hz=np.asarray(y_obs, dtype=float),
        f_geo_source_hz=np.asarray(source_curve, dtype=float),
        noise_hz=np.asarray(noise, dtype=float),
        b_true_hz=float(b_hz),
        k_true_hz_s=float(k_hz_s),
        sigma_true_hz=float(sigma_hz),
        t0_s=float(t0_s),
        sample_id=1,
        attack_type=relation_type,
        attack_variant=relation_variant,
    )


def base_specs_for_calibration(t_rel: np.ndarray) -> dict[int | str, list[wrc.WindowSpec]]:
    specs = wae.base_middle_specs(t_rel, [180, 120, 60, 30])
    out: dict[int | str, list[wrc.WindowSpec]] = {"full_pass": [s for s in specs if s.window_position == "full_pass"]}
    for length in [180, 120, 60, 30]:
        out[length] = [s for s in specs if int(round(s.window_length_s)) == length]
    return out


def choose_specs_for_mode(mode: str, t_rel: np.ndarray, selection_curve: np.ndarray, f_geo_a: np.ndarray, cal: dict[int | str, dict[str, float]]) -> tuple[list[wrc.WindowSpec], str, str]:
    if mode == "full_pass":
        return [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)], "full_pass", "full_pass"
    if mode == "single_30s_selected":
        return wae.choose_nonoverlap_best_specs(selection_curve, f_geo_a, t_rel, [30], cal, 0.2), "selected_difficult_short_windows", "single_30s_selected"
    if mode == "single_60s_selected":
        return wae.choose_nonoverlap_best_specs(selection_curve, f_geo_a, t_rel, [60], cal, 0.2), "selected_difficult_short_windows", "single_60s_selected"
    if mode == "spread_3x60s":
        return wae.choose_group_specs("3x60s", "spread_segments", t_rel, selection_curve, f_geo_a, cal, 0.2), "spread_segments", "3x60s"
    if mode == "spread_6x30s":
        return wae.choose_group_specs("6x30s", "spread_segments", t_rel, selection_curve, f_geo_a, cal, 0.2), "spread_segments", "6x30s"
    if mode == "selected_difficult_short_windows":
        return wae.choose_group_specs("3x60s", "best_attack_segments", t_rel, selection_curve, f_geo_a, cal, 0.2), "selected_difficult_short_windows", "3x60s"
    fail(f"unsupported window mode: {mode}")


def candidate_v11_decision(gr: dict[str, Any]) -> str:
    if gr["proposed_decision"] != "ACCEPT":
        return str(gr["proposed_decision"])
    if gr["group_mode"] in {"best_attack_segments", "selected_difficult_short_windows"}:
        centers = []
        for part in str(gr["window_positions"]).split(";"):
            if "-" in part:
                a, b = part.split("-", 1)
                centers.append((float(a) + float(b)) / 2.0)
        center_span = max(centers) - min(centers) if len(centers) > 1 else 0.0
        effective = float(gr.get("effective_total_duration_s", 0.0))
        denom = max(float(gr.get("pass_duration_s", 0.0)), effective)
        if int(gr["num_windows"]) < 3 or float(gr["max_overlap_ratio"]) > 0.1 or (denom > 0 and center_span / denom < 0.4):
            return "DEFER"
    return str(gr["proposed_decision"])


def load_hard_cases(path: Path, selection: pd.DataFrame, max_targets: int, max_samples: int) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    hard = pd.read_csv(path)
    cols = ["target_id", "target_name", "attack_type", "attack_param_name", "attack_param_value"]
    if any(c not in hard.columns for c in cols):
        return pd.DataFrame()
    hard = hard[hard["attack_type"].isin(["same_plane_altitude_offset", "inclination_offset"])].copy()
    hard["target_id"] = hard["target_id"].astype(str)
    hard["attack_param_value"] = pd.to_numeric(hard["attack_param_value"], errors="coerce")
    hard = hard.dropna(subset=["attack_param_value"])
    hard["priority"] = 10
    hard.loc[hard["attack_type"].eq("same_plane_altitude_offset") & hard["attack_param_value"].isin([-1.0, -2.0]), "priority"] = 0
    hard.loc[hard["attack_type"].eq("inclination_offset") & (hard["attack_param_value"].abs() <= 0.10), "priority"] = 1
    hard = hard.sort_values(["priority", "attack_type", "target_id", "attack_param_value"])
    allowed_targets = set(selection["target_norad_id"].astype(str).head(max_targets))
    hard = hard[hard["target_id"].isin(allowed_targets)]
    return hard[cols].drop_duplicates().head(max_samples).assign(sample_group="hard_case_weighted")


def typical_cases(selection: pd.DataFrame, max_targets: int, max_samples: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    targets = selection.head(max_targets)
    templates = [
        ("same_plane_altitude_offset", "delta_h_km", -10.0),
        ("same_plane_altitude_offset", "delta_h_km", 10.0),
        ("inclination_offset", "delta_inclination_deg", -0.20),
        ("inclination_offset", "delta_inclination_deg", 0.20),
        ("same_plane_phase_offset", "phase_offset_s", -60.0),
        ("same_plane_phase_offset", "phase_offset_s", 60.0),
    ]
    for _, target in targets.iterrows():
        for attack_type, name, value in templates:
            rows.append(
                {
                    "target_id": str(target["target_norad_id"]),
                    "target_name": str(target["target_name"]),
                    "attack_type": attack_type,
                    "attack_param_name": name,
                    "attack_param_value": float(value),
                    "sample_group": "typical_orbit_similar",
                }
            )
    return pd.DataFrame(rows).head(max_samples)


def random_cases(selection: pd.DataFrame, library: pd.DataFrame, max_targets: int, max_samples: int, tle_ids: set[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    targets = selection.head(max_targets)
    for _, target in targets.iterrows():
        target_id = str(target["target_norad_id"])
        lib = library[library["target_norad_id"].astype(str).eq(target_id)].copy()
        candidates = (
            lib[~lib["candidate_norad_id"].astype(str).eq(target_id)][["candidate_norad_id", "candidate_name", "candidate_rank_or_selection_order"]]
            .drop_duplicates()
            .sort_values("candidate_rank_or_selection_order")
        )
        # Pick moderately separated ranks instead of only nearest neighbors.
        if len(candidates) > 12:
            candidates = candidates.iloc[[5, 25, 75, min(150, len(candidates) - 1)]].drop_duplicates()
        for _, cand in candidates.iterrows():
            cid = str(cand["candidate_norad_id"])
            if cid not in tle_ids:
                continue
            rows.append(
                {
                    "target_id": target_id,
                    "target_name": str(target["target_name"]),
                    "attack_type": "random_simulated_tle",
                    "attack_param_name": "candidate_norad_id",
                    "attack_param_value": cid,
                    "sample_group": "random_simulated",
                    "simulated_satellite_id": cid,
                    "simulated_satellite_name": str(cand["candidate_name"]),
                }
            )
    return pd.DataFrame(rows).head(max_samples)


def select_samples(args: argparse.Namespace, selection: pd.DataFrame, library: pd.DataFrame, tle_ids: set[str]) -> pd.DataFrame:
    parts = []
    groups = set(args.sample_groups)
    if "hard_case_weighted" in groups:
        parts.append(load_hard_cases(args.hard_cases, selection, args.max_targets, args.max_samples_per_group))
    if "typical_orbit_similar" in groups:
        parts.append(typical_cases(selection, args.max_targets, args.max_samples_per_group))
    if "random_simulated" in groups and not args.skip_random_simulated:
        parts.append(random_cases(selection, library, args.max_targets, args.max_samples_per_group, tle_ids))
    samples = pd.concat([p for p in parts if p is not None and not p.empty], ignore_index=True) if parts else pd.DataFrame()
    if samples.empty:
        fail("no samples selected")
    samples["target_id"] = samples["target_id"].astype(str)
    if "simulated_satellite_id" not in samples.columns:
        samples["simulated_satellite_id"] = "synthetic"
    if "simulated_satellite_name" not in samples.columns:
        samples["simulated_satellite_name"] = "synthetic_orbit"
    samples["simulated_satellite_id"] = samples["simulated_satellite_id"].fillna("synthetic")
    samples["simulated_satellite_name"] = samples["simulated_satellite_name"].fillna("synthetic_orbit")
    return samples.reset_index(drop=True)


def calibration_for_target(
    target_id: str,
    target_name: str,
    geo: pd.DataFrame,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    ranges: dict[str, list[float]],
    rng: np.random.Generator,
    num_benign: int,
    seed: int,
) -> dict[int | str, dict[str, float]]:
    benign_obs = []
    for i in range(1, num_benign + 1):
        err = base.sample_error_params(ranges, rng)
        benign_obs.append(base.build_legitimate_observation(f"fr_ext_benign_{target_id}_{i:04d}", target_name, target_id, geo, err, rng, i, seed))
    return wae.calibration_stats(
        benign_obs=benign_obs,
        geo=geo,
        f_geo_a=f_geo_a,
        specs_by_key=base_specs_for_calibration(t_rel),
        threshold_types=["p95"],
    )


def row_from_group(
    gr: dict[str, Any],
    *,
    row_id: int,
    sample: pd.Series,
    pass_id: str,
    window_mode: str,
    strategy_type: str,
    compensation_mode: str,
    requested_error_km: float,
    actual_error_km: float,
    bearing_deg: float,
    s_lat: float,
    s_lon: float,
    sh_lat: float,
    sh_lon: float,
    raw_delta_rmse: float,
    comp_before: float,
    comp_after: float,
    improvement: float,
    override_decision: str | None = None,
) -> dict[str, Any]:
    scores = [float(x) for x in str(gr["single_window_scores"]).split(";") if x]
    b_hats = [float(x) for x in str(gr["single_window_b_hats"]).split(";") if x]
    k_hats = [float(x) for x in str(gr["single_window_k_hats"]).split(";") if x]
    decision = override_decision or str(gr["final_decision"])
    return {
        "row_id": row_id,
        "target_id": str(sample["target_id"]),
        "target_name": str(sample["target_name"]),
        "simulated_satellite_id": str(sample.get("simulated_satellite_id", "synthetic")),
        "simulated_satellite_name": str(sample.get("simulated_satellite_name", "synthetic_orbit")),
        "sample_group": str(sample["sample_group"]),
        "orbit_relation_type": str(sample["attack_type"]),
        "orbit_relation_param_name": str(sample["attack_param_name"]),
        "orbit_relation_param_value": sample["attack_param_value"],
        "pass_id": pass_id,
        "window_mode": window_mode,
        "window_lengths_s": gr["window_lengths_s"],
        "window_positions": gr["window_positions"],
        "strategy_type": strategy_type,
        "requested_error_km": float(requested_error_km),
        "actual_error_km": float(actual_error_km),
        "bearing_deg": float(bearing_deg),
        "S_lat": float(s_lat),
        "S_lon": float(s_lon),
        "S_hat_lat": float(sh_lat),
        "S_hat_lon": float(sh_lon),
        "compensation_mode": compensation_mode,
        "raw_delta_rmse_before_bk": float(raw_delta_rmse),
        "comp_delta_rmse_before_bk": float(comp_before),
        "comp_delta_rmse_after_bk": float(comp_after),
        "improvement_ratio_before_bk": float(improvement),
        "b_hat_hz": float(np.nanmedian(b_hats)) if b_hats else np.nan,
        "k_hat_hz_per_s": float(np.nanmedian(k_hats)) if k_hats else np.nan,
        "residual_score": float(np.nanmedian(scores)) if scores else np.nan,
        "normalized_residual_score": float(gr.get("joint_normalized_score", np.nan)),
        "score_gate_pass": bool(gr.get("joint_score_gate_pass", False)),
        "b_gate_pass": bool(gr.get("joint_b_gate_pass", False)),
        "k_gate_pass": bool(gr.get("joint_k_gate_pass", False)),
        "temporal_diversity_pass": bool(gr.get("temporal_diversity_pass", False)),
        "joint_bk_gate_pass": bool(gr.get("joint_b_gate_pass", False)) and bool(gr.get("joint_k_gate_pass", False)),
        "final_decision": decision,
        "decision_reason": str(gr["decision_reason"]),
    }


def fit_delta_stats(y_base: np.ndarray, f_geo_a: np.ndarray, t_rel: np.ndarray) -> tuple[float, float, float, float]:
    delta = y_base - f_geo_a
    fit = base.fit_bias_and_slope(y_base, f_geo_a, t_rel)
    x = t_rel - float(np.mean(t_rel))
    after = delta - (fit.b_hat_hz + fit.k_hat_hz_s * x)
    return rmse(delta), rmse(after), float(fit.b_hat_hz), float(fit.k_hat_hz_s)


def strategy_rows_for_observation(
    *,
    row_counter: int,
    sample: pd.Series,
    pass_id: str,
    window_mode: str,
    compensation_mode: str,
    observation: base.ObservationSequence,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    specs: list[wrc.WindowSpec],
    group_mode: str,
    segment_pattern: str,
    cal: dict[int | str, dict[str, float]],
    args: argparse.Namespace,
    requested_error_km: float,
    actual_error_km: float,
    bearing_deg: float,
    s_lat: float,
    s_lon: float,
    sh_lat: float,
    sh_lon: float,
    raw_delta_rmse: float,
    comp_before: float,
    comp_after: float,
    improvement: float,
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    group_rows = wae.build_group_rows(
        group_id=f"{sample['target_id']}_{observation.sequence_id}_{window_mode}_{compensation_mode}_e{requested_error_km:g}_b{bearing_deg:g}",
        target_id=str(sample["target_id"]),
        target_name=str(sample["target_name"]),
        attack_type=str(sample["attack_type"]),
        attack_param_name=str(sample["attack_param_name"]),
        attack_param_value=sample["attack_param_value"],
        is_benign=False,
        pass_id=pass_id,
        group_mode=group_mode,
        segment_pattern=segment_pattern,
        observation=observation,
        f_geo_a=f_geo_a,
        t_rel=t_rel,
        specs=specs,
        cal=cal,
        threshold_type="p95",
        args=SimpleNamespace(evidence_accept_threshold=3.0, max_overlap_ratio=0.2, strategies=["single_window", "proposed_accumulation"]),
    )
    for gr in group_rows:
        gr["pass_duration_s"] = float(np.max(t_rel) - np.min(t_rel))
        if gr["strategy_type"] == "single_window" and "single_window_baseline" in args.strategies:
            rows.append(
                row_from_group(
                    gr,
                    row_id=row_counter,
                    sample=sample,
                    pass_id=pass_id,
                    window_mode=window_mode,
                    strategy_type="single_window_baseline",
                    compensation_mode=compensation_mode,
                    requested_error_km=requested_error_km,
                    actual_error_km=actual_error_km,
                    bearing_deg=bearing_deg,
                    s_lat=s_lat,
                    s_lon=s_lon,
                    sh_lat=sh_lat,
                    sh_lon=sh_lon,
                    raw_delta_rmse=raw_delta_rmse,
                    comp_before=comp_before,
                    comp_after=comp_after,
                    improvement=improvement,
                )
            )
            row_counter += 1
        if gr["strategy_type"] == "proposed_accumulation":
            if "proposed_v1" in args.strategies:
                rows.append(
                    row_from_group(
                        gr,
                        row_id=row_counter,
                        sample=sample,
                        pass_id=pass_id,
                        window_mode=window_mode,
                        strategy_type="proposed_v1",
                        compensation_mode=compensation_mode,
                        requested_error_km=requested_error_km,
                        actual_error_km=actual_error_km,
                        bearing_deg=bearing_deg,
                        s_lat=s_lat,
                        s_lon=s_lon,
                        sh_lat=sh_lat,
                        sh_lon=sh_lon,
                        raw_delta_rmse=raw_delta_rmse,
                        comp_before=comp_before,
                        comp_after=comp_after,
                        improvement=improvement,
                    )
                )
                row_counter += 1
            if "candidate_v1_1" in args.strategies:
                rows.append(
                    row_from_group(
                        gr,
                        row_id=row_counter,
                        sample=sample,
                        pass_id=pass_id,
                        window_mode=window_mode,
                        strategy_type="candidate_v1_1",
                        compensation_mode=compensation_mode,
                        requested_error_km=requested_error_km,
                        actual_error_km=actual_error_km,
                        bearing_deg=bearing_deg,
                        s_lat=s_lat,
                        s_lon=s_lon,
                        sh_lat=sh_lat,
                        sh_lon=sh_lon,
                        raw_delta_rmse=raw_delta_rmse,
                        comp_before=comp_before,
                        comp_after=comp_after,
                        improvement=improvement,
                        override_decision=candidate_v11_decision(gr),
                    )
                )
                row_counter += 1
            if "full_pass" in args.strategies and window_mode == "full_pass":
                rows.append(
                    row_from_group(
                        gr,
                        row_id=row_counter,
                        sample=sample,
                        pass_id=pass_id,
                        window_mode=window_mode,
                        strategy_type="full_pass",
                        compensation_mode=compensation_mode,
                        requested_error_km=requested_error_km,
                        actual_error_km=actual_error_km,
                        bearing_deg=bearing_deg,
                        s_lat=s_lat,
                        s_lon=s_lon,
                        sh_lat=sh_lat,
                        sh_lon=sh_lon,
                        raw_delta_rmse=raw_delta_rmse,
                        comp_before=comp_before,
                        comp_after=comp_after,
                        improvement=improvement,
                    )
                )
                row_counter += 1
    return rows, row_counter


def summarize(dataset: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["sample_group", "requested_error_km", "bearing_deg", "window_mode", "strategy_type", "compensation_mode"]
    rows = []
    for key, g in dataset.groupby(group_cols, dropna=False):
        counts = g["final_decision"].value_counts()
        n = len(g)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n": int(n),
                "accept_rate": float(counts.get("ACCEPT", 0) / n) if n else np.nan,
                "defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
                "reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
                "raw_delta_rmse_before_bk_median": float(g["raw_delta_rmse_before_bk"].median()),
                "raw_delta_rmse_before_bk_p95": float(g["raw_delta_rmse_before_bk"].quantile(0.95)),
                "comp_delta_rmse_before_bk_median": float(g["comp_delta_rmse_before_bk"].median()),
                "comp_delta_rmse_before_bk_p95": float(g["comp_delta_rmse_before_bk"].quantile(0.95)),
                "comp_delta_rmse_after_bk_median": float(g["comp_delta_rmse_after_bk"].median()),
                "comp_delta_rmse_after_bk_p95": float(g["comp_delta_rmse_after_bk"].quantile(0.95)),
                "improvement_ratio_before_bk_median": float(g["improvement_ratio_before_bk"].replace([np.inf, -np.inf], np.nan).median()),
                "improvement_ratio_before_bk_p95": float(g["improvement_ratio_before_bk"].replace([np.inf, -np.inf], np.nan).quantile(0.95)),
                "abs_b_hat_median": float(g["b_hat_hz"].abs().median()),
                "abs_b_hat_p95": float(g["b_hat_hz"].abs().quantile(0.95)),
                "abs_k_hat_median": float(g["k_hat_hz_per_s"].abs().median()),
                "abs_k_hat_p95": float(g["k_hat_hz_per_s"].abs().quantile(0.95)),
                "score_median": float(g["residual_score"].median()),
                "score_p95": float(g["residual_score"].quantile(0.95)),
            }
        )
    return pd.DataFrame(rows)


def strategy_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    base_cols = ["sample_group", "requested_error_km", "window_mode", "strategy_type"]
    avg = summary.groupby(base_cols + ["compensation_mode"], as_index=False)[["accept_rate", "defer_rate", "reject_rate"]].mean()
    fixed = avg[avg["compensation_mode"].eq("fixed_reference_compensation")].copy()
    no = avg[avg["compensation_mode"].eq("no_compensation")][base_cols + ["accept_rate"]].rename(columns={"accept_rate": "no_comp_accept_rate"})
    out = fixed.merge(no, on=base_cols, how="left")
    proposed = out[out["strategy_type"].eq("proposed_v1")][["sample_group", "requested_error_km", "window_mode", "accept_rate"]].rename(columns={"accept_rate": "proposed_v1_accept_rate"})
    out = out.merge(proposed, on=["sample_group", "requested_error_km", "window_mode"], how="left")
    out["delta_accept_vs_no_compensation"] = out["accept_rate"] - out["no_comp_accept_rate"]
    out["delta_accept_vs_proposed_v1"] = out["accept_rate"] - out["proposed_v1_accept_rate"]
    return out[["sample_group", "requested_error_km", "window_mode", "strategy_type", "accept_rate", "defer_rate", "reject_rate", "delta_accept_vs_no_compensation", "delta_accept_vs_proposed_v1"]]


def bk_absorption(dataset: pd.DataFrame) -> pd.DataFrame:
    d = dataset[dataset["compensation_mode"].eq("fixed_reference_compensation")].copy()
    group_cols = ["sample_group", "requested_error_km", "bearing_deg", "window_mode"]
    rows = []
    for key, g in d.groupby(group_cols, dropna=False):
        before = float(g["comp_delta_rmse_before_bk"].median())
        after = float(g["comp_delta_rmse_after_bk"].median())
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "before_bk_rmse_median": before,
                "after_bk_rmse_median": after,
                "bk_absorption_ratio": before / after if after > 0 else np.inf,
                "abs_b_hat_median": float(g["b_hat_hz"].abs().median()),
                "abs_k_hat_median": float(g["k_hat_hz_per_s"].abs().median()),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(dataset: pd.DataFrame, summary: pd.DataFrame, bk: pd.DataFrame, figures_dir: Path) -> list[Path]:
    paths: list[Path] = []
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")].copy()
    # 1 group
    d = fixed[fixed["strategy_type"].eq("proposed_v1")].groupby(["sample_group", "requested_error_km"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    for group, g in d.groupby("sample_group"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=group)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Accept rate vs location error by sample group")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = figures_dir / "accept_rate_vs_location_error_by_group.png"
    savefig(fig, p)
    paths.append(p)
    # 2 strategy
    d = fixed.groupby(["strategy_type", "requested_error_km"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    for strategy, g in d.groupby("strategy_type"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=strategy)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Accept rate vs location error by strategy")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = figures_dir / "accept_rate_vs_location_error_by_strategy.png"
    savefig(fig, p)
    paths.append(p)
    # 3 before/after
    d = dataset[dataset["compensation_mode"].eq("fixed_reference_compensation")].groupby("requested_error_km", as_index=False)[["comp_delta_rmse_before_bk", "comp_delta_rmse_after_bk"]].median()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(d["requested_error_km"], d["comp_delta_rmse_before_bk"], marker="o", label="before b/k")
    ax.plot(d["requested_error_km"], d["comp_delta_rmse_after_bk"], marker="o", label="after b/k")
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("RMSE Hz")
    ax.set_title("Before/after b/k RMSE vs location error")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = figures_dir / "before_after_bk_rmse_vs_location_error.png"
    savefig(fig, p)
    paths.append(p)
    # 4 heatmap
    d = fixed[fixed["strategy_type"].eq("proposed_v1")].groupby(["sample_group", "requested_error_km"], as_index=False)["accept_rate"].mean()
    piv = d.pivot(index="sample_group", columns="requested_error_km", values="accept_rate").fillna(0)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    im = ax.imshow(piv.to_numpy(float), aspect="auto", cmap="magma", vmin=0, vmax=max(0.05, float(np.nanmax(piv.to_numpy(float)))))
    ax.set_xticks(range(len(piv.columns)), [f"{c:g}" for c in piv.columns])
    ax.set_yticks(range(len(piv.index)), piv.index)
    ax.set_xlabel("requested_error_km")
    ax.set_title("Accept rate heatmap: group by error")
    fig.colorbar(im, ax=ax, label="accept_rate")
    p = figures_dir / "accept_rate_heatmap_group_by_error_strategy.png"
    savefig(fig, p)
    paths.append(p)
    # 5 compensation comparison
    d = summary[summary["strategy_type"].eq("proposed_v1")].groupby(["compensation_mode", "requested_error_km"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    for mode, g in d.groupby("compensation_mode"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=mode)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Fixed-reference compensation vs no compensation")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = figures_dir / "compensation_vs_no_compensation_accept_rate.png"
    savefig(fig, p)
    paths.append(p)
    return paths


def make_example_curves(curve_examples: dict[tuple[str, float], dict[str, np.ndarray]], figures_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for (group, e_km), data in curve_examples.items():
        suffix = f"{group}_e{e_km:g}km".replace(".", "p")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(data["t_rel"], data["f_a_s"], label="f_geo(A,S)")
        ax.plot(data["t_rel"], data["f_b_s"], label="f_geo(B,S)", alpha=0.8)
        ax.plot(data["t_rel"], data["f_comp"], label="f_comp", alpha=0.8)
        ax.set_xlabel("t_rel_s")
        ax.set_ylabel("frequency_hz")
        ax.set_title(f"Example curves: {group}, e={e_km:g} km")
        ax.legend()
        ax.grid(True, alpha=0.25)
        p = figures_dir / f"example_curves_{suffix}.png"
        savefig(fig, p)
        paths.append(p)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(data["t_rel"], data["delta_raw"], label="delta_raw")
        ax.plot(data["t_rel"], data["delta_comp"], label="delta_comp")
        ax.plot(data["t_rel"], data["delta_comp_after_bk"], label="delta_comp_after_bk")
        ax.set_xlabel("t_rel_s")
        ax.set_ylabel("residual_hz")
        ax.set_title(f"Example residuals: {group}, e={e_km:g} km")
        ax.legend()
        ax.grid(True, alpha=0.25)
        p = figures_dir / f"example_residuals_{suffix}.png"
        savefig(fig, p)
        paths.append(p)
    return paths


def write_report(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, comparison: pd.DataFrame, bk: pd.DataFrame, figures: list[Path]) -> None:
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")]
    no = summary[summary["compensation_mode"].eq("no_compensation")]
    by_group = fixed[fixed["strategy_type"].eq("proposed_v1")].groupby("sample_group", as_index=False)["accept_rate"].mean()
    by_error = fixed[fixed["strategy_type"].eq("proposed_v1")].groupby("requested_error_km", as_index=False)["accept_rate"].mean()
    by_strategy = fixed.groupby("strategy_type", as_index=False)["accept_rate"].mean()
    no_vs = pd.DataFrame()
    if not no.empty:
        no_vs = pd.concat(
            [
                no[no["strategy_type"].eq("proposed_v1")].assign(mode="no_compensation"),
                fixed[fixed["strategy_type"].eq("proposed_v1")].assign(mode="fixed_reference_compensation"),
            ],
            ignore_index=True,
        ).groupby("mode", as_index=False)["accept_rate"].mean()
    bk_mean = bk.groupby("requested_error_km", as_index=False)[["before_bk_rmse_median", "after_bk_rmse_median", "bk_absorption_ratio"]].median()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    sample_counts = dataset[["sample_group", "target_id", "orbit_relation_type", "orbit_relation_param_value"]].drop_duplicates().groupby("sample_group").size().reset_index(name="sample_specs")
    text = f"""# Fixed-reference compensation extended sensitivity summary

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 实验目的

本轮在 sanity check 通过后，扩展固定参考点补偿模型的位置误差范围，并加入普通相似样本和随机对照样本。所有结果仅来自离线、合成、可复现数学仿真，不接入真实链路，不发射信号，也不代表真实系统结论。

## 2. 上一轮 sanity check 结论

上一轮已确认补偿方向为 `f_geo(B,S) + f_geo(A,S_hat) - f_geo(B,S_hat)`，`e=0 km` 时补偿后曲线接近 `f_geo(A,S)`，`S_hat` 会按 e 和方向正确偏移，且未发现明显 e 曲线复用问题。

## 3. 模型与位置误差范围

- e values：`{', '.join(str(v) for v in args.e_values)}`
- bearings：`{', '.join(str(v) for v in args.bearings)}`
- window modes：`{', '.join(args.window_modes)}`
- strategies：`{', '.join(args.strategies)}`
- compensation modes：`no_compensation`, `fixed_reference_compensation`

## 4. 样本规模

- dataset rows：`{len(dataset)}`
- summary rows：`{len(summary)}`
- target 数：`{dataset['target_id'].nunique()}`

样本组规格数：

{sample_counts.to_markdown(index=False)}

## 5. 不同样本组的接受率

proposed v1 + fixed-reference compensation 按 sample group 平均：

{by_group.to_markdown(index=False)}

## 6. 位置误差影响

proposed v1 + fixed-reference compensation 按 e 平均：

{by_error.to_markdown(index=False)}

## 7. 验证策略对比

fixed-reference compensation 下按 strategy 平均：

{by_strategy.to_markdown(index=False)}

## 8. no-compensation 对照

proposed v1 下 compensation mode 对比：

{no_vs.to_markdown(index=False) if not no_vs.empty else '无'}

## 9. b/k 拟合吸收作用

按 e 的 before/after b/k 中位数：

{bk_mean.to_markdown(index=False)}

## 10. 图像输出

{figs}

## 11. 阶段性结论

本轮只能说明当前离线仿真和固定参考点补偿模型下，非目标模拟卫星曲线对单站 Doppler residual 验证器的压力变化。不能外推为真实系统行为。

如果普通样本组接受率明显低于最难区分样本，则上一轮更接近边界压力测试；如果普通样本也较高，则说明该模型在当前仿真设置下对更广样本也有明显压力。若 50/100/200 km 后接受率下降，说明参考点精度是重要限制；若仍不明显下降，需要继续检查 b/k 拟合、窗口长度、样本选择和频率尺度，并进入多站一致性或更严格窗口一致性分析。

## 12. 本轮问题回答

1. 固定参考点补偿效果是否随位置误差扩大下降：见第 6 节和图表，需按样本组解释。
2. 0-10 km 不下降是否主要因为误差范围过小：本轮扩展到 200 km 用于判断；若趋势只在 50 km 后出现，则 0-10 km 范围确实偏小。
3. 20/50/100/200 km 是否出现边界：见 `fixed_reference_compensation_extended_summary.csv`。
4. 现象是否集中在最难区分样本：见第 5 节。
5. no-compensation 与 fixed-reference compensation 差异：见第 8 节。
6. b/k 拟合吸收多少剩余位置失配：见第 9 节和 `fixed_reference_compensation_bk_absorption.csv`。
7. proposed v1 与 candidate v1.1 哪个更稳：见第 7 节，较低 ACCEPT 且较高 DEFER 的策略更保守。
8. full-pass 是否仍高接受：见 strategy 对比中的 `full_pass`。
9. 是否足以进入下一步：若 sanity 与本轮扩展均稳定，建议进入多站一致性或更严格窗口一致性分析。
10. 不能外推的结论：本轮不是真实链路验证，不证明真实系统一定接受或拒绝，只是离线模型压力测试。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame) -> None:
    counts = dataset[["sample_group", "target_id", "orbit_relation_type", "orbit_relation_param_value"]].drop_duplicates().groupby("sample_group").size().to_dict()
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")]
    prop = fixed[fixed["strategy_type"].eq("proposed_v1")]["accept_rate"].mean() if not fixed.empty else np.nan
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - fixed-reference compensation extended sensitivity

### A. 本轮目标

扩展固定参考点补偿模型的位置误差范围，并加入最难区分样本、普通相似样本和随机对照样本。

### B. 实际操作

- 新增 `scripts/run_fixed_reference_compensation_extended_sensitivity.py`。
- 同时输出 no-compensation 与 fixed-reference compensation 对照。
- 扫描 e values：`{', '.join(str(v) for v in args.e_values)}`。
- 扫描 bearings：`{', '.join(str(v) for v in args.bearings)}`。

### C. 新增/修改文件

- 新增：`scripts/run_fixed_reference_compensation_extended_sensitivity.py`
- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.strategy_comparison_output.as_posix()}`
- 生成：`{args.bk_absorption_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}`

### D. 运行命令

```bash
python -m py_compile scripts/run_fixed_reference_compensation_extended_sensitivity.py
python scripts/run_fixed_reference_compensation_extended_sensitivity.py --e-values 0,10,100 --bearings 0,90 --sample-groups hard_case_weighted,typical_orbit_similar --max-targets 2 --max-samples-per-group 3 --overwrite
python scripts/run_fixed_reference_compensation_extended_sensitivity.py --e-values 0,1,2,5,10,20,50,100,200 --bearings 0,90,180,270 --sample-groups hard_case_weighted,typical_orbit_similar,random_simulated --strategies single_window_baseline,proposed_v1,candidate_v1_1,full_pass --overwrite
```

### E. 结果摘要

- dataset rows：`{len(dataset)}`。
- summary rows：`{len(summary)}`。
- sample group specs：`{counts}`。
- proposed v1 fixed-reference mean accept：`{prop:.4f}`。

### F. 注意事项

本轮仍是离线仿真压力测试；结果不能外推为真实系统结论。下一步建议引入多站一致性或更严格窗口一致性分析。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.e_values = parse_float_csv(args.e_values)
    if args.include_500km and 500.0 not in args.e_values:
        args.e_values.append(500.0)
    args.e_values = sorted(set(float(v) for v in args.e_values))
    args.bearings = parse_float_csv(args.bearings)
    args.sample_groups = parse_csv(args.sample_groups)
    args.strategies = parse_csv(args.strategies)
    args.window_modes = parse_csv(args.window_modes)
    check_outputs([args.dataset_output, args.summary_output, args.strategy_comparison_output, args.bk_absorption_output, args.report_output], args.overwrite)

    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=args.max_targets,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    tle_ids = set(tle.keys())
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    rng = np.random.default_rng(args.seed)

    samples = select_samples(args, selection, library, tle_ids)
    selection_map = {str(r.target_norad_id): r for r in selection.itertuples(index=False)}
    cal_cache: dict[str, dict[int | str, dict[str, float]]] = {}
    geo_cache: dict[str, tuple[pd.DataFrame, list[Any], np.ndarray, np.ndarray, float, float, Any]] = {}
    rows: list[dict[str, Any]] = []
    curve_examples: dict[tuple[str, float], dict[str, np.ndarray]] = {}
    row_counter = 1

    for sample_idx, sample in samples.iterrows():
        target_id = str(sample["target_id"])
        if target_id not in selection_map or target_id not in tle:
            continue
        target_name = str(sample["target_name"])
        sat_a = tle[target_id]["sat"]
        if target_id not in geo_cache:
            station_s = orbit_builder.wgs84.latlon(s_lat, s_lon, elevation_m=s_alt_m)
            geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat_a, station_s, ts)
            times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
            t_rel = geo["t_rel_s"].to_numpy(float)
            step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
            freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else 11_325_000_000.0
            f_a_s = geo["f_geo_candidate_hz"].to_numpy(float)
            geo_cache[target_id] = (geo, times, t_rel, f_a_s, step_s, freq_hz, sat_a)
        geo, times, t_rel, f_a_s, step_s, freq_hz, sat_a = geo_cache[target_id]
        if target_id not in cal_cache:
            cal_cache[target_id] = calibration_for_target(target_id, target_name, geo, f_a_s, t_rel, ranges, rng, args.num_benign_sims, args.seed)
        cal = cal_cache[target_id]
        if str(sample["sample_group"]) == "random_simulated":
            sim_id = str(sample["simulated_satellite_id"])
            if sim_id not in tle:
                continue
            sat_b = tle[sim_id]["sat"]
            f_b_s = fixed_reference_geo(sat_b, s_lat, s_lon, s_alt_m, times, ts, freq_hz, step_s)
            relation_variant = f"candidate_{sim_id}"
        else:
            spec = synthetic_spec(str(sample["attack_type"]), float(sample["attack_param_value"]))
            f_b_s = generate_synthetic_geo(spec, sat_a, s_lat, s_lon, s_alt_m, times, ts, freq_hz)
            relation_variant = str(spec["attack_variant"])
        raw_delta = f_b_s - f_a_s
        raw_delta_rmse = rmse(raw_delta)
        pass_id = f"{target_id}_{geo['t_abs_utc'].iloc[0]}"

        for e_km in args.e_values:
            for bearing in args.bearings:
                sh_lat, sh_lon = active.destination_point(s_lat, s_lon, e_km, bearing)
                actual = float(active.haversine_distance_km(np.array([sh_lat]), np.array([sh_lon]), s_lat, s_lon)[0])
                f_a_sh = fixed_reference_geo(sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                if str(sample["sample_group"]) == "random_simulated":
                    sat_b = tle[str(sample["simulated_satellite_id"])]["sat"]
                    f_b_sh = fixed_reference_geo(sat_b, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                else:
                    spec = synthetic_spec(str(sample["attack_type"]), float(sample["attack_param_value"]))
                    f_b_sh = generate_synthetic_geo(spec, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz)
                f_comp_base = f_b_s + (f_a_sh - f_b_sh)
                terms = active.sample_residual_terms(t_rel, args.residual_mode, ranges, rng)
                mode_bases = {
                    "no_compensation": f_b_s,
                    "fixed_reference_compensation": f_comp_base,
                }
                selection_curve = f_comp_base
                specs_by_mode: dict[str, tuple[list[wrc.WindowSpec], str, str]] = {}
                for window_mode in args.window_modes:
                    specs_by_mode[window_mode] = choose_specs_for_mode(window_mode, t_rel, selection_curve, f_a_s, cal)

                for comp_mode, y_base in mode_bases.items():
                    y_obs, noise, b_hz, k_hz_s, sigma_hz, t0_s = active.apply_residual_terms(y_base, t_rel, terms)
                    before, after, _b_fit, _k_fit = fit_delta_stats(y_base, f_a_s, t_rel)
                    comp_before = before
                    comp_after = after
                    improvement = raw_delta_rmse / comp_before if comp_before > 0 else np.inf
                    obs = build_observation(
                        f"fr_ext_{sample_idx:04d}_{comp_mode}_e{e_km:g}_b{bearing:g}",
                        target_name,
                        target_id,
                        geo,
                        y_obs,
                        y_base,
                        noise,
                        b_hz,
                        k_hz_s,
                        sigma_hz,
                        t0_s,
                        str(sample["attack_type"]),
                        relation_variant,
                    )
                    for window_mode, (specs, group_mode, segment_pattern) in specs_by_mode.items():
                        if not specs:
                            continue
                        new_rows, row_counter = strategy_rows_for_observation(
                            row_counter=row_counter,
                            sample=sample,
                            pass_id=pass_id,
                            window_mode=window_mode,
                            compensation_mode=comp_mode,
                            observation=obs,
                            f_geo_a=f_a_s,
                            t_rel=t_rel,
                            specs=specs,
                            group_mode=group_mode,
                            segment_pattern=segment_pattern,
                            cal=cal,
                            args=args,
                            requested_error_km=e_km,
                            actual_error_km=actual,
                            bearing_deg=bearing,
                            s_lat=s_lat,
                            s_lon=s_lon,
                            sh_lat=sh_lat,
                            sh_lon=sh_lon,
                            raw_delta_rmse=raw_delta_rmse,
                            comp_before=comp_before,
                            comp_after=comp_after,
                            improvement=improvement,
                        )
                        rows.extend(new_rows)

                if args.plot_example_curves and bearing == 90.0 and e_km in {0.0, 20.0, 100.0, 200.0}:
                    key = (str(sample["sample_group"]), float(e_km))
                    if key not in curve_examples:
                        delta_comp = f_comp_base - f_a_s
                        fit = base.fit_bias_and_slope(f_comp_base, f_a_s, t_rel)
                        x = t_rel - float(np.mean(t_rel))
                        curve_examples[key] = {
                            "t_rel": t_rel,
                            "f_a_s": f_a_s,
                            "f_b_s": f_b_s,
                            "f_comp": f_comp_base,
                            "delta_raw": raw_delta,
                            "delta_comp": delta_comp,
                            "delta_comp_after_bk": delta_comp - (fit.b_hat_hz + fit.k_hat_hz_s * x),
                        }

    dataset = pd.DataFrame(rows)
    if dataset.empty:
        fail("no rows generated")
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output, index=False)
    summary = summarize(dataset)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    comparison = strategy_comparison(summary)
    args.strategy_comparison_output.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(args.strategy_comparison_output, index=False)
    bk = bk_absorption(dataset)
    args.bk_absorption_output.parent.mkdir(parents=True, exist_ok=True)
    bk.to_csv(args.bk_absorption_output, index=False)
    figures = make_figures(dataset, summary, bk, args.figures_dir)
    if args.plot_example_curves:
        figures.extend(make_example_curves(curve_examples, args.figures_dir))
    write_report(args, dataset, summary, comparison, bk, figures)
    append_log(args, dataset, summary)
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.strategy_comparison_output} rows={len(comparison)}")
    print(f"wrote {args.bk_absorption_output} rows={len(bk)}")
    print(f"wrote {args.report_output}")
    for p in figures:
        print(p)


if __name__ == "__main__":
    main()
