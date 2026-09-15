#!/usr/bin/env python
"""First-pass active frequency compensation attack experiment.

This runner compares three single-station attack signals against the existing
claimed-identity Doppler verifier:

* none: no active compensation, f_attack = f_geo(B, S, t)
* subpoint_A: compensation referenced to A's instantaneous subpoint C(t)
* direct_S_ideal: ideal compensation to the real verifier station S

The moving-reference helper treats C(t) as a per-sample instantaneous ground
reference point.  It does not add receiver trajectory velocity from adjacent
subpoints.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402


COMPENSATION_TYPES = ["none", "subpoint_A", "direct_S_ideal"]
RESIDUAL_MODES = ["clean", "empirical"]
REFERENCE_MODES = ["subpoint_A", "controlled_R"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    p.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/active_compensation_first_pass_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/active_compensation_first_pass_summary.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/active_compensation_first_pass_dataset.csv"))
    p.add_argument("--pairwise-output", type=Path, default=Path("outputs/metrics/active_compensation_first_pass_pairwise_compare.csv"))
    p.add_argument("--distance-bins-output", type=Path, default=Path("outputs/metrics/active_compensation_first_pass_distance_bins.csv"))
    p.add_argument("--controlled-r-summary-output", type=Path, default=Path("outputs/metrics/active_compensation_controlled_R_summary.csv"))
    p.add_argument("--controlled-r-pairwise-output", type=Path, default=Path("outputs/metrics/active_compensation_controlled_R_pairwise.csv"))
    p.add_argument("--max-targets", type=int, default=2)
    p.add_argument("--max-attackers-per-target", type=int, default=3)
    p.add_argument("--residual-mode", choices=["clean", "empirical", "both"], default="clean")
    p.add_argument("--reference-mode", choices=["subpoint_A", "controlled_R", "both"], default="subpoint_A")
    p.add_argument("--R-km-list", "--controlled-r-km", dest="R_km_list", default="0,50,100,200,500,1000,2000")
    p.add_argument("--bearing-deg-list", default="0,45,90,135,180,225,270,315")
    p.add_argument("--seed", type=int, default=20260603)
    p.add_argument("--elevation-min-deg", type=float, default=20.0)
    p.add_argument("--moving-reference-diff-step-s", type=float, default=0.5)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("outputs exist; add --overwrite: " + ", ".join(existing))


def require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{name} missing columns: {', '.join(missing)}")


def residual_modes(arg: str) -> list[str]:
    return RESIDUAL_MODES if arg == "both" else [arg]


def reference_modes(arg: str) -> list[str]:
    return REFERENCE_MODES if arg == "both" else [arg]


def parse_float_list(text: str, name: str) -> list[float]:
    try:
        values = [float(x.strip()) for x in str(text).split(",") if x.strip()]
    except ValueError as exc:
        fail(f"invalid {name}: {text}")
        raise exc
    if not values:
        fail(f"{name} must not be empty")
    return values


def load_common_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, tuple[float, float]], dict[str, tuple[float, float]], dict[str, list[float]]]:
    for path in [args.selection_table, args.candidate_library, args.tle_file, args.orbit_config, args.parameter_config, args.thresholds, args.legit_results]:
        if not path.exists():
            fail(f"missing input: {path}")

    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=args.max_targets,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    selection = selection.head(args.max_targets).copy()
    library = library.copy()
    library["target_norad_id"] = library["target_norad_id"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)

    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)

    thresholds = pd.read_csv(args.thresholds)
    require_columns(thresholds, ["target_norad", "threshold_95_hz", "threshold_99_hz"], "thresholds")
    threshold_map = {
        str(r.target_norad): (float(r.threshold_95_hz), float(r.threshold_99_hz))
        for r in thresholds.itertuples(index=False)
    }

    legit = pd.read_csv(args.legit_results)
    require_columns(legit, ["target_norad", "k_hat_hz_s"], "legit results")
    k_map: dict[str, tuple[float, float]] = {}
    for tid, g in legit.groupby(legit["target_norad"].astype(str), sort=False):
        k_map[str(tid)] = (float(g["k_hat_hz_s"].quantile(0.01)), float(g["k_hat_hz_s"].quantile(0.99)))

    for tid in selection["target_norad_id"].astype(str):
        if tid not in tle:
            fail(f"target not found in TLE: {tid}")
        if tid not in threshold_map:
            fail(f"target not found in thresholds: {tid}")
        if tid not in k_map:
            fail(f"target not found in legit k ranges: {tid}")

    return selection, library, orbit_cfg, tle, threshold_map, k_map, ranges


def target_geo_from_library(library: pd.DataFrame, target_norad: str) -> pd.DataFrame:
    geo = base.target_geo_from_library(library, target_norad)
    require_columns(geo, ["candidate_name", "candidate_norad_id", "t_abs_utc", "t_rel_s", "f_geo_candidate_hz"], "target geo")
    return geo


def select_attackers(library: pd.DataFrame, target_norad: str, tle: dict[str, dict[str, Any]], limit: int) -> pd.DataFrame:
    rows = library[library["target_norad_id"].astype(str) == str(target_norad)].copy()
    rows = rows[rows["candidate_norad_id"].astype(str) != str(target_norad)]
    rows = rows[rows["candidate_norad_id"].astype(str).isin(tle.keys())]
    if rows.empty:
        fail(f"no usable real-TLE attacker candidates for target {target_norad}")
    sort_cols = [c for c in ["candidate_rank_or_selection_order", "candidate_rank", "candidate_norad_id"] if c in rows.columns]
    if sort_cols:
        rows = rows.sort_values(sort_cols)
    attackers = rows[["candidate_name", "candidate_norad_id"]].drop_duplicates().head(limit)
    if attackers.empty:
        fail(f"no distinct attacker candidates for target {target_norad}")
    return attackers.reset_index(drop=True)


def candidate_geo_from_library(library: pd.DataFrame, target_norad: str, attacker_norad: str, target_t_rel: np.ndarray) -> pd.DataFrame:
    rows = library[
        (library["target_norad_id"].astype(str) == str(target_norad))
        & (library["candidate_norad_id"].astype(str) == str(attacker_norad))
    ].copy()
    if rows.empty:
        fail(f"candidate library missing attacker geometry: target={target_norad}, attacker={attacker_norad}")
    rows = rows.sort_values("t_rel_s").reset_index(drop=True)
    if len(rows) != len(target_t_rel) or not np.allclose(rows["t_rel_s"].to_numpy(float), target_t_rel):
        fail(f"attacker geometry time grid mismatch: target={target_norad}, attacker={attacker_norad}")
    return rows


def compute_subpoint_series(sat_A: Any, times: list[Any], ts: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sky_times = ts.from_datetimes(times)
    subpoint = sat_A.at(sky_times).subpoint()
    lat_deg = np.asarray(subpoint.latitude.degrees, dtype=float)
    lon_deg = np.asarray(subpoint.longitude.degrees, dtype=float)
    alt_m = np.zeros_like(lat_deg, dtype=float)
    return lat_deg, lon_deg, alt_m


def geo_curve_moving_reference(
    sat: Any,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    alt_m: np.ndarray,
    times: list[Any],
    ts: Any,
    freq_hz: float,
    diff_step_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    if not (len(lat_deg) == len(lon_deg) == len(alt_m) == len(times)):
        fail("moving reference inputs must have identical lengths")
    if diff_step_s <= 0:
        fail("--moving-reference-diff-step-s must be positive")

    f_geo: list[float] = []
    range_rates: list[float] = []
    half_step = timedelta(seconds=float(diff_step_s))
    for lat, lon, alt, dt in zip(lat_deg, lon_deg, alt_m, times):
        site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt))
        t0 = ts.from_datetime(dt)
        tm = ts.from_datetime(dt - half_step)
        tp = ts.from_datetime(dt + half_step)
        r_minus_m = (sat - site).at(tm).distance().m
        r_plus_m = (sat - site).at(tp).distance().m
        range_rate_mps = float((r_plus_m - r_minus_m) / (2.0 * float(diff_step_s)))
        doppler_hz = -float(freq_hz) * range_rate_mps / base.C_MPS
        f_geo.append(float(freq_hz) + doppler_hz)
        range_rates.append(range_rate_mps)
        _ = t0  # keep the per-sample time explicit for readability and future diagnostics
    return np.asarray(f_geo, dtype=float), np.asarray(range_rates, dtype=float)


def apply_residual_mode(
    f_attack_base: np.ndarray,
    t_rel: np.ndarray,
    residual_mode: str,
    ranges: dict[str, list[float]],
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, float, float, float, float]:
    t0_s = float(np.mean(t_rel))
    if residual_mode == "clean":
        return f_attack_base.copy(), np.zeros(len(t_rel), dtype=float), 0.0, 0.0, 0.0, t0_s
    if residual_mode != "empirical":
        fail(f"unsupported residual mode: {residual_mode}")
    err = base.sample_error_params(ranges, rng)
    noise = rng.normal(0.0, err.sigma_hz, len(t_rel)) if err.sigma_hz > 0 else np.zeros(len(t_rel), dtype=float)
    f_obs = f_attack_base + err.b_hz + err.k_hz_s * (t_rel - t0_s) + noise
    return f_obs, noise, err.b_hz, err.k_hz_s, err.sigma_hz, t0_s


def build_observation(
    sequence_id: str,
    target_name: str,
    target_norad: str,
    geo: pd.DataFrame,
    f_obs_attack: np.ndarray,
    f_source: np.ndarray,
    noise_hz: np.ndarray,
    b_injected_hz: float,
    k_injected_hz_s: float,
    noise_sigma_hz: float,
    t0_s: float,
    compensation_type: str,
    attacker_name: str,
    attacker_norad: str,
    residual_mode: str,
) -> base.ObservationSequence:
    t_rel = geo["t_rel_s"].to_numpy(float)
    return base.ObservationSequence(
        sequence_id=sequence_id,
        source_type="ATTACK",
        claimed_target_name=target_name,
        claimed_target_norad=target_norad,
        t_abs_utc=geo["t_abs_utc"].to_numpy(str),
        t_rel_s=t_rel,
        y_obs_hz=f_obs_attack,
        f_geo_source_hz=f_source,
        noise_hz=noise_hz,
        b_true_hz=float(b_injected_hz),
        k_true_hz_s=float(k_injected_hz_s),
        sigma_true_hz=float(noise_sigma_hz),
        t0_s=float(t0_s),
        sample_id=1,
        attack_type="active_frequency_compensation_first_pass",
        attack_variant=compensation_type,
        metadata={"attacker_name": attacker_name, "attacker_norad": attacker_norad, "residual_mode": residual_mode},
    )


def tri_state_decision(accepted_score_k: bool, max_elevation_deg: float, elevation_min_deg: float) -> str:
    if float(max_elevation_deg) < float(elevation_min_deg):
        return "DEFER" if accepted_score_k else "REJECT"
    return "ACCEPT" if accepted_score_k else "REJECT"


def finite_check(name: str, values: np.ndarray) -> None:
    if not np.all(np.isfinite(values)):
        fail(f"{name} contains NaN or inf")


def rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(values, dtype=float) ** 2)))


def haversine_distance_km(lat1_deg: np.ndarray, lon1_deg: np.ndarray, lat2_deg: float, lon2_deg: float) -> np.ndarray:
    earth_radius_km = 6371.0088
    lat1 = np.radians(np.asarray(lat1_deg, dtype=float))
    lon1 = np.radians(np.asarray(lon1_deg, dtype=float))
    lat2 = np.radians(float(lat2_deg))
    lon2 = np.radians(float(lon2_deg))
    dlat = lat1 - lat2
    dlon = lon1 - lon2
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * earth_radius_km * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def destination_point(lat_deg: float, lon_deg: float, distance_km: float, bearing_deg: float) -> tuple[float, float]:
    earth_radius_km = 6371.0088
    if abs(distance_km) < 1e-12:
        return float(lat_deg), float(lon_deg)
    lat1 = np.radians(float(lat_deg))
    lon1 = np.radians(float(lon_deg))
    bearing = np.radians(float(bearing_deg))
    angular_distance = float(distance_km) / earth_radius_km
    lat2 = np.arcsin(np.sin(lat1) * np.cos(angular_distance) + np.cos(lat1) * np.sin(angular_distance) * np.cos(bearing))
    lon2 = lon1 + np.arctan2(
        np.sin(bearing) * np.sin(angular_distance) * np.cos(lat1),
        np.cos(angular_distance) - np.sin(lat1) * np.sin(lat2),
    )
    lon2 = (lon2 + np.pi) % (2.0 * np.pi) - np.pi
    return float(np.degrees(lat2)), float(np.degrees(lon2))


def controlled_reference_cases(
    station_lat_deg: float,
    station_lon_deg: float,
    station_alt_m: float,
    r_values_km: list[float],
    bearing_values_deg: list[float],
) -> list[dict[str, float]]:
    cases: list[dict[str, float]] = []
    for r_km in r_values_km:
        bearings = [0.0] if abs(float(r_km)) < 1e-12 else bearing_values_deg
        for bearing in bearings:
            lat, lon = destination_point(station_lat_deg, station_lon_deg, float(r_km), float(bearing))
            actual = float(haversine_distance_km(np.array([lat]), np.array([lon]), station_lat_deg, station_lon_deg)[0])
            cases.append(
                {
                    "R_km": float(r_km),
                    "bearing_deg": float(bearing),
                    "C_lat_deg": lat,
                    "C_lon_deg": lon,
                    "C_alt_m": float(station_alt_m),
                    "C_S_distance_km": actual,
                }
            )
    return cases


def geo_curve_fixed_reference(sat: Any, lat_deg: float, lon_deg: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float, step_s: float) -> tuple[np.ndarray, np.ndarray]:
    site = orbit_builder.wgs84.latlon(float(lat_deg), float(lon_deg), elevation_m=float(alt_m))
    geo = orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))
    return geo["f_geo_tle_hz"].to_numpy(float), geo["range_rate_mps"].to_numpy(float)


def sample_residual_terms(
    t_rel: np.ndarray,
    residual_mode: str,
    ranges: dict[str, list[float]],
    rng: np.random.Generator,
) -> tuple[np.ndarray, float, float, float, float]:
    t0_s = float(np.mean(t_rel))
    if residual_mode == "clean":
        return np.zeros(len(t_rel), dtype=float), 0.0, 0.0, 0.0, t0_s
    if residual_mode != "empirical":
        fail(f"unsupported residual mode: {residual_mode}")
    err = base.sample_error_params(ranges, rng)
    noise = rng.normal(0.0, err.sigma_hz, len(t_rel)) if err.sigma_hz > 0 else np.zeros(len(t_rel), dtype=float)
    return noise, err.b_hz, err.k_hz_s, err.sigma_hz, t0_s


def apply_residual_terms(
    f_attack_base: np.ndarray,
    t_rel: np.ndarray,
    terms: tuple[np.ndarray, float, float, float, float],
) -> tuple[np.ndarray, np.ndarray, float, float, float, float]:
    noise, b_hz, k_hz_s, sigma_hz, t0_s = terms
    f_obs = f_attack_base + b_hz + k_hz_s * (t_rel - t0_s) + noise
    return f_obs, noise, b_hz, k_hz_s, sigma_hz, t0_s


def summarize(seq: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (mode, comp), g in seq.groupby(["residual_mode", "compensation_type"], sort=False):
        counts = g["tri_state_decision"].value_counts()
        n = len(g)
        rows.append(
            {
                "residual_mode": mode,
                "compensation_type": comp,
                "case_count": int(n),
                "accept_count_p95": int(g["accepted_p95"].sum()),
                "accept_rate_p95": float(g["accepted_p95"].mean()) if n else 0.0,
                "accept_count_p99": int(g["accepted_p99"].sum()),
                "accept_rate_p99": float(g["accepted_p99"].mean()) if n else 0.0,
                "tri_state_accept_count": int(counts.get("ACCEPT", 0)),
                "tri_state_accept_rate": float(counts.get("ACCEPT", 0) / n) if n else 0.0,
                "tri_state_reject_count": int(counts.get("REJECT", 0)),
                "tri_state_reject_rate": float(counts.get("REJECT", 0) / n) if n else 0.0,
                "tri_state_defer_count": int(counts.get("DEFER", 0)),
                "tri_state_defer_rate": float(counts.get("DEFER", 0) / n) if n else 0.0,
                "score_median_hz": float(g["score_A_rmse_hz"].median()),
                "score_p95_hz": float(g["score_A_rmse_hz"].quantile(0.95)),
                "attack_delta_rmse_median_hz": float(g["attack_delta_rmse_hz"].median()),
                "attack_delta_rmse_p95_hz": float(g["attack_delta_rmse_hz"].quantile(0.95)),
                "b_hat_median_hz": float(g["b_hat_hz"].median()),
                "k_hat_median_hz_s": float(g["k_hat_hz_s"].median()),
                "b_injected_median_hz": float(g["b_injected_hz"].median()),
                "k_injected_median_hz_s": float(g["k_injected_hz_s"].median()),
                "noise_sigma_median_hz": float(g["noise_sigma_hz"].median()),
            }
        )
    return pd.DataFrame(rows)


def safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if abs(float(denominator)) > 1e-12 else np.nan


def build_pairwise_compare(seq: pd.DataFrame) -> pd.DataFrame:
    keys = ["target_id", "target_name", "attacker_id", "attacker_name", "pass_start_utc", "pass_end_utc", "residual_mode"]
    base_cols = keys + [
        "max_elevation_deg",
        "C_S_distance_min_km",
        "C_S_distance_mean_km",
        "C_S_distance_max_km",
        "C_S_distance_at_mid_km",
    ]
    none = seq[(seq["reference_mode"] == "subpoint_A") & (seq["compensation_type"] == "none")].copy()
    sub = seq[(seq["reference_mode"] == "subpoint_A") & (seq["compensation_type"] == "subpoint_A")].copy()
    merged = none.merge(sub, on=keys, suffixes=("_none", "_subpoint"))
    rows: list[dict[str, Any]] = []
    for _, r in merged.iterrows():
        none_score = float(r["score_A_rmse_hz_none"])
        sub_score = float(r["score_A_rmse_hz_subpoint"])
        none_delta = float(r["attack_delta_rmse_hz_none"])
        sub_delta = float(r["attack_delta_rmse_hz_subpoint"])
        score_improvement = none_score - sub_score
        delta_improvement = none_delta - sub_delta
        score_improvement_ratio = safe_ratio(score_improvement, none_score)
        delta_improvement_ratio = safe_ratio(delta_improvement, none_delta)
        reasons: list[str] = []
        if bool(r["accepted_p95_subpoint"]):
            reasons.append("subpoint_p95_accept")
        if str(r["tri_state_decision_subpoint"]) == "ACCEPT":
            reasons.append("subpoint_tri_ACCEPT")
        if str(r["tri_state_decision_subpoint"]) == "DEFER":
            reasons.append("subpoint_tri_DEFER")
        threshold = float(r["threshold_95_hz_subpoint"])
        if threshold > 0 and (sub_score - threshold) / threshold < 0.20:
            reasons.append("subpoint_score_margin_lt_20pct")
        if np.isfinite(score_improvement_ratio) and score_improvement_ratio > 0.30:
            reasons.append("score_improved_gt_30pct")
        if np.isfinite(delta_improvement_ratio) and delta_improvement_ratio > 0.30:
            reasons.append("raw_delta_improved_gt_30pct")
        dist_min = float(r["C_S_distance_min_km_subpoint"])
        if dist_min < 200.0:
            reasons.append("near_C_to_S_lt_200km")
        elif dist_min < 500.0 and np.isfinite(score_improvement_ratio) and score_improvement_ratio > 0:
            reasons.append("near_C_to_S_lt_500km_with_score_improvement")
        rows.append(
            {
                "target_id": r["target_id"],
                "target_name": r["target_name"],
                "attacker_id": r["attacker_id"],
                "attacker_name": r["attacker_name"],
                "pass_start_utc": r["pass_start_utc"],
                "pass_end_utc": r["pass_end_utc"],
                "max_elevation_deg": float(r["max_elevation_deg_subpoint"]),
                "residual_mode": r["residual_mode"],
                "none_score_hz": none_score,
                "subpoint_score_hz": sub_score,
                "score_delta_hz": sub_score - none_score,
                "score_improvement_hz": score_improvement,
                "score_improvement_ratio": score_improvement_ratio,
                "none_attack_delta_rmse_hz": none_delta,
                "subpoint_attack_delta_rmse_hz": sub_delta,
                "attack_delta_improvement_hz": delta_improvement,
                "attack_delta_improvement_ratio": delta_improvement_ratio,
                "none_p95_accept": bool(r["accepted_p95_none"]),
                "subpoint_p95_accept": bool(r["accepted_p95_subpoint"]),
                "none_tri_state_decision": r["tri_state_decision_none"],
                "subpoint_tri_state_decision": r["tri_state_decision_subpoint"],
                "none_b_hat_hz": float(r["b_hat_hz_none"]),
                "subpoint_b_hat_hz": float(r["b_hat_hz_subpoint"]),
                "none_k_hat_hz_s": float(r["k_hat_hz_s_none"]),
                "subpoint_k_hat_hz_s": float(r["k_hat_hz_s_subpoint"]),
                "C_S_distance_min_km": dist_min,
                "C_S_distance_mean_km": float(r["C_S_distance_mean_km_subpoint"]),
                "C_S_distance_max_km": float(r["C_S_distance_max_km_subpoint"]),
                "C_S_distance_at_mid_km": float(r["C_S_distance_at_mid_km_subpoint"]),
                "danger_flag": bool(reasons),
                "danger_reason": ";".join(reasons),
            }
        )
    return pd.DataFrame(rows)


def build_controlled_r_summary(seq: pd.DataFrame) -> pd.DataFrame:
    d = seq[seq["reference_mode"] == "controlled_R"].copy()
    d = d[d["compensation_type"] == "controlled_R"]
    if d.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (mode, r_km), g in d.groupby(["residual_mode", "R_km"], sort=True):
        n = len(g)
        counts = g["tri_state_decision"].value_counts()
        rows.append(
            {
                "residual_mode": mode,
                "R_km": float(r_km),
                "case_count": int(n),
                "p95_accept_count": int(g["accepted_p95"].sum()),
                "p95_accept_rate": float(g["accepted_p95"].mean()) if n else 0.0,
                "p99_accept_count": int(g["accepted_p99"].sum()),
                "p99_accept_rate": float(g["accepted_p99"].mean()) if n else 0.0,
                "tri_ACCEPT_count": int(counts.get("ACCEPT", 0)),
                "tri_DEFER_count": int(counts.get("DEFER", 0)),
                "tri_REJECT_count": int(counts.get("REJECT", 0)),
                "tri_ACCEPT_rate": float(counts.get("ACCEPT", 0) / n) if n else 0.0,
                "tri_DEFER_rate": float(counts.get("DEFER", 0) / n) if n else 0.0,
                "tri_REJECT_rate": float(counts.get("REJECT", 0) / n) if n else 0.0,
                "score_median_hz": float(g["score_A_rmse_hz"].median()),
                "score_p95_hz": float(g["score_A_rmse_hz"].quantile(0.95)),
                "attack_delta_rmse_median_hz": float(g["attack_delta_rmse_hz"].median()),
                "attack_delta_rmse_p95_hz": float(g["attack_delta_rmse_hz"].quantile(0.95)),
                "b_hat_median_hz": float(g["b_hat_hz"].median()),
                "k_hat_median_hz_s": float(g["k_hat_hz_s"].median()),
            }
        )
    return pd.DataFrame(rows)


def build_controlled_r_pairwise(seq: pd.DataFrame) -> pd.DataFrame:
    d = seq[seq["reference_mode"] == "controlled_R"].copy()
    if d.empty:
        return pd.DataFrame()
    keys = ["target_id", "target_name", "attacker_id", "attacker_name", "pass_start_utc", "pass_end_utc", "residual_mode"]
    none = d[d["compensation_type"] == "none"].copy()
    ctrl = d[d["compensation_type"] == "controlled_R"].copy()
    merged = ctrl.merge(none, on=keys, suffixes=("_controlled_R", "_none"))
    rows: list[dict[str, Any]] = []
    for _, r in merged.iterrows():
        none_score = float(r["score_A_rmse_hz_none"])
        ctrl_score = float(r["score_A_rmse_hz_controlled_R"])
        none_delta = float(r["attack_delta_rmse_hz_none"])
        ctrl_delta = float(r["attack_delta_rmse_hz_controlled_R"])
        rows.append(
            {
                "target_id": r["target_id"],
                "target_name": r["target_name"],
                "attacker_id": r["attacker_id"],
                "attacker_name": r["attacker_name"],
                "pass_start_utc": r["pass_start_utc"],
                "pass_end_utc": r["pass_end_utc"],
                "max_elevation_deg": float(r["max_elevation_deg_controlled_R"]),
                "residual_mode": r["residual_mode"],
                "R_km": float(r["R_km_controlled_R"]),
                "bearing_deg": float(r["bearing_deg_controlled_R"]),
                "none_score_hz": none_score,
                "controlled_R_score_hz": ctrl_score,
                "score_improvement_hz": none_score - ctrl_score,
                "score_improvement_ratio": safe_ratio(none_score - ctrl_score, none_score),
                "none_attack_delta_rmse_hz": none_delta,
                "controlled_R_attack_delta_rmse_hz": ctrl_delta,
                "attack_delta_improvement_hz": none_delta - ctrl_delta,
                "attack_delta_improvement_ratio": safe_ratio(none_delta - ctrl_delta, none_delta),
                "controlled_R_p95_accept": bool(r["accepted_p95_controlled_R"]),
                "controlled_R_p99_accept": bool(r["accepted_p99_controlled_R"]),
                "controlled_R_tri_state_decision": r["tri_state_decision_controlled_R"],
                "controlled_R_b_hat_hz": float(r["b_hat_hz_controlled_R"]),
                "controlled_R_k_hat_hz_s": float(r["k_hat_hz_s_controlled_R"]),
                "threshold_95_hz": float(r["threshold_95_hz_controlled_R"]),
                "target_k_min_p01": float(r["target_k_min_p01_controlled_R"]),
                "target_k_max_p99": float(r["target_k_max_p99_controlled_R"]),
            }
        )
    return pd.DataFrame(rows)


def distance_bin(value: float) -> str:
    if value < 100:
        return "0-100 km"
    if value < 200:
        return "100-200 km"
    if value < 500:
        return "200-500 km"
    if value < 1000:
        return "500-1000 km"
    if value < 2000:
        return "1000-2000 km"
    return "2000+ km"


def build_distance_bins(pairwise: pd.DataFrame) -> pd.DataFrame:
    if pairwise.empty:
        return pd.DataFrame()
    out = pairwise.copy()
    out["distance_bin"] = out["C_S_distance_min_km"].astype(float).map(distance_bin)
    rows: list[dict[str, Any]] = []
    for (mode, bin_name), g in out.groupby(["residual_mode", "distance_bin"], sort=False):
        rows.append(
            {
                "residual_mode": mode,
                "distance_bin": bin_name,
                "case_count": int(len(g)),
                "subpoint_p95_accept_count": int(g["subpoint_p95_accept"].sum()),
                "subpoint_tri_ACCEPT_count": int((g["subpoint_tri_state_decision"] == "ACCEPT").sum()),
                "subpoint_tri_DEFER_count": int((g["subpoint_tri_state_decision"] == "DEFER").sum()),
                "subpoint_tri_REJECT_count": int((g["subpoint_tri_state_decision"] == "REJECT").sum()),
                "subpoint_score_median_hz": float(g["subpoint_score_hz"].median()),
                "subpoint_score_p95_hz": float(g["subpoint_score_hz"].quantile(0.95)),
                "score_improvement_ratio_median": float(g["score_improvement_ratio"].median()),
                "attack_delta_improvement_ratio_median": float(g["attack_delta_improvement_ratio"].median()),
                "danger_count": int(g["danger_flag"].sum()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    check_outputs(
        [
            args.sequence_output,
            args.summary_output,
            args.dataset_output,
            args.pairwise_output,
            args.distance_bins_output,
            args.controlled_r_summary_output,
            args.controlled_r_pairwise_output,
        ],
        args.overwrite,
    )
    selection, library, _orbit_cfg, tle, threshold_map, k_map, ranges = load_common_inputs(args)
    ts = load.timescale()
    rng = np.random.default_rng(args.seed)
    selected_residual_modes = residual_modes(args.residual_mode)
    selected_reference_modes = reference_modes(args.reference_mode)
    r_values_km = parse_float_list(args.R_km_list, "--R-km-list")
    bearing_values_deg = parse_float_list(args.bearing_deg_list, "--bearing-deg-list")
    station_cfg = _orbit_cfg["station"]
    station_lat_deg = float(station_cfg["lat_deg"])
    station_lon_deg = float(station_cfg["lon_deg"])
    station_alt_m = float(station_cfg["alt_m"])
    controlled_cases = controlled_reference_cases(station_lat_deg, station_lon_deg, station_alt_m, r_values_km, bearing_values_deg)

    sequence_rows: list[dict[str, Any]] = []
    dataset_rows: list[pd.DataFrame] = []
    seq_counter = 1

    for _, target in selection.iterrows():
        target_id = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        sat_A = tle[target_id]["sat"]
        geo_A = target_geo_from_library(library, target_id)
        times = [base.parse_utc(v) for v in geo_A["t_abs_utc"].astype(str)]
        t_rel = geo_A["t_rel_s"].to_numpy(float)
        f_geo_A_S = geo_A["f_geo_candidate_hz"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        freq_hz = float(geo_A["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo_A.columns else 11_325_000_000.0
        max_elevation_deg = float(target["max_elevation_deg"]) if "max_elevation_deg" in target else np.nan
        pass_start = str(target["pass_start_utc"]) if "pass_start_utc" in target else str(geo_A["t_abs_utc"].iloc[0])
        pass_end = str(target["pass_end_utc"]) if "pass_end_utc" in target else str(geo_A["t_abs_utc"].iloc[-1])
        threshold_95, threshold_99 = threshold_map[target_id]
        k_min, k_max = k_map[target_id]

        C_lat, C_lon, C_alt = compute_subpoint_series(sat_A, times, ts)
        if float(np.ptp(C_lat)) == 0.0 and float(np.ptp(C_lon)) == 0.0:
            fail(f"C(t) appears fixed for target {target_id}; expected changing subpoint")
        C_S_distance_km = haversine_distance_km(C_lat, C_lon, station_lat_deg, station_lon_deg)
        C_S_distance_min_km = float(np.min(C_S_distance_km))
        C_S_distance_mean_km = float(np.mean(C_S_distance_km))
        C_S_distance_max_km = float(np.max(C_S_distance_km))
        C_S_distance_at_mid_km = float(C_S_distance_km[len(C_S_distance_km) // 2])
        f_geo_A_C, rr_A_C = geo_curve_moving_reference(sat_A, C_lat, C_lon, C_alt, times, ts, freq_hz, args.moving_reference_diff_step_s)

        finite_check("f_geo_A_S_hz", f_geo_A_S)
        finite_check("f_geo_A_C_hz", f_geo_A_C)
        finite_check("range_rate_A_C_mps", rr_A_C)

        attackers = select_attackers(library, target_id, tle, args.max_attackers_per_target)
        for _, attacker in attackers.iterrows():
            attacker_id = str(attacker["candidate_norad_id"])
            attacker_name = str(attacker["candidate_name"])
            sat_B = tle[attacker_id]["sat"]
            geo_B = candidate_geo_from_library(library, target_id, attacker_id, t_rel)
            f_geo_B_S = geo_B["f_geo_candidate_hz"].to_numpy(float)
            f_geo_B_C, rr_B_C = geo_curve_moving_reference(sat_B, C_lat, C_lon, C_alt, times, ts, freq_hz, args.moving_reference_diff_step_s)

            for name, values in [
                ("f_geo_B_S_hz", f_geo_B_S),
                ("f_geo_B_C_hz", f_geo_B_C),
                ("range_rate_B_C_mps", rr_B_C),
            ]:
                finite_check(name, values)

            u_by_type = {
                "none": np.zeros_like(f_geo_A_S),
                "subpoint_A": f_geo_A_C - f_geo_B_C,
                "direct_S_ideal": f_geo_A_S - f_geo_B_S,
            }
            residual_terms_by_mode = {
                mode: sample_residual_terms(t_rel, mode, ranges, rng)
                for mode in selected_residual_modes
            }
            compensation_cases: list[dict[str, Any]] = []
            if "subpoint_A" in selected_reference_modes:
                for comp in COMPENSATION_TYPES:
                    compensation_cases.append(
                        {
                            "reference_mode": "subpoint_A",
                            "compensation_type": comp,
                            "R_km": np.nan,
                            "bearing_deg": np.nan,
                            "C_lat_series": C_lat,
                            "C_lon_series": C_lon,
                            "C_alt_series": C_alt,
                            "C_lat_scalar": np.nan,
                            "C_lon_scalar": np.nan,
                            "C_alt_scalar": np.nan,
                            "C_S_distance_series": C_S_distance_km,
                            "C_S_distance_scalar": np.nan,
                            "f_geo_A_C": f_geo_A_C,
                            "f_geo_B_C": f_geo_B_C,
                            "rr_A_C": rr_A_C,
                            "rr_B_C": rr_B_C,
                            "u_comp": u_by_type[comp],
                        }
                    )
            if "controlled_R" in selected_reference_modes:
                for case in controlled_cases:
                    c_lat = float(case["C_lat_deg"])
                    c_lon = float(case["C_lon_deg"])
                    c_alt = float(case["C_alt_m"])
                    f_geo_A_C_fixed, rr_A_C_fixed = geo_curve_fixed_reference(sat_A, c_lat, c_lon, c_alt, times, ts, freq_hz, step_s)
                    f_geo_B_C_fixed, rr_B_C_fixed = geo_curve_fixed_reference(sat_B, c_lat, c_lon, c_alt, times, ts, freq_hz, step_s)
                    controlled_u = f_geo_A_C_fixed - f_geo_B_C_fixed
                    dist_value = float(case["C_S_distance_km"])
                    dist_series = np.full(len(t_rel), dist_value, dtype=float)
                    compensation_cases.append(
                        {
                            "reference_mode": "controlled_R",
                            "compensation_type": "controlled_R",
                            "R_km": float(case["R_km"]),
                            "bearing_deg": float(case["bearing_deg"]),
                            "C_lat_series": np.full(len(t_rel), c_lat, dtype=float),
                            "C_lon_series": np.full(len(t_rel), c_lon, dtype=float),
                            "C_alt_series": np.full(len(t_rel), c_alt, dtype=float),
                            "C_lat_scalar": c_lat,
                            "C_lon_scalar": c_lon,
                            "C_alt_scalar": c_alt,
                            "C_S_distance_series": dist_series,
                            "C_S_distance_scalar": dist_value,
                            "f_geo_A_C": f_geo_A_C_fixed,
                            "f_geo_B_C": f_geo_B_C_fixed,
                            "rr_A_C": rr_A_C_fixed,
                            "rr_B_C": rr_B_C_fixed,
                            "u_comp": controlled_u,
                        }
                    )

            if "controlled_R" in selected_reference_modes:
                # Add one no-compensation baseline per A/B/mode inside controlled_R,
                # so controlled-R pairwise comparison can join on residual_mode.
                compensation_cases.append(
                    {
                        "reference_mode": "controlled_R",
                        "compensation_type": "none",
                        "R_km": np.nan,
                        "bearing_deg": np.nan,
                        "C_lat_series": np.full(len(t_rel), station_lat_deg, dtype=float),
                        "C_lon_series": np.full(len(t_rel), station_lon_deg, dtype=float),
                        "C_alt_series": np.full(len(t_rel), station_alt_m, dtype=float),
                        "C_lat_scalar": station_lat_deg,
                        "C_lon_scalar": station_lon_deg,
                        "C_alt_scalar": station_alt_m,
                        "C_S_distance_series": np.zeros(len(t_rel), dtype=float),
                        "C_S_distance_scalar": 0.0,
                        "f_geo_A_C": f_geo_A_S,
                        "f_geo_B_C": f_geo_B_S,
                        "rr_A_C": np.full(len(t_rel), np.nan),
                        "rr_B_C": np.full(len(t_rel), np.nan),
                        "u_comp": np.zeros_like(f_geo_A_S),
                    }
                )

            for comp_case in compensation_cases:
                reference_mode = str(comp_case["reference_mode"])
                compensation_type = str(comp_case["compensation_type"])
                u_comp = np.asarray(comp_case["u_comp"], dtype=float)
                f_attack_base = f_geo_B_S + u_comp
                finite_check(f"u_comp_hz:{compensation_type}", u_comp)
                finite_check(f"f_attack_base_hz:{compensation_type}", f_attack_base)
                base_delta = f_attack_base - f_geo_A_S

                for residual_mode in selected_residual_modes:
                    f_obs_attack, noise_injected, b_inj, k_inj, sigma_inj, t0_s = apply_residual_terms(
                        f_attack_base,
                        t_rel,
                        residual_terms_by_mode[residual_mode],
                    )
                    finite_check(f"f_obs_attack_hz:{residual_mode}:{compensation_type}", f_obs_attack)
                    delta_obs = f_obs_attack - f_geo_A_S
                    sequence_id = f"active_comp_{seq_counter:06d}"
                    seq_counter += 1

                    observation = build_observation(
                        sequence_id,
                        target_name,
                        target_id,
                        geo_A,
                        f_obs_attack,
                        f_geo_B_S,
                        noise_injected,
                        b_inj,
                        k_inj,
                        sigma_inj,
                        t0_s,
                        compensation_type,
                        attacker_name,
                        attacker_id,
                        residual_mode,
                    )
                    verification = base.verify_claimed_identity(observation, f_geo_A_S, threshold_95, threshold_99)
                    accepted_score_k = bool(verification.accepted_95 and k_min <= verification.k_hat_hz_s <= k_max)
                    decision = tri_state_decision(accepted_score_k, max_elevation_deg, args.elevation_min_deg)
                    is_upper_bound_sanity = bool(
                        compensation_type == "direct_S_ideal"
                        or (reference_mode == "controlled_R" and compensation_type == "controlled_R" and abs(float(comp_case["R_km"])) < 1e-12)
                    )
                    score_only_sanity_pass = bool(
                        residual_mode == "clean"
                        and is_upper_bound_sanity
                        and rmse(base_delta) <= 1e-3
                        and verification.accepted_95
                        and verification.accepted_99
                    )
                    tri_state_applicable = not (residual_mode == "clean" and is_upper_bound_sanity)

                    sequence_rows.append(
                        {
                            "sequence_id": sequence_id,
                            "residual_mode": residual_mode,
                            "reference_mode": reference_mode,
                            "target_id": target_id,
                            "target_name": target_name,
                            "attacker_id": attacker_id,
                            "attacker_name": attacker_name,
                            "pass_start_utc": pass_start,
                            "pass_end_utc": pass_end,
                            "max_elevation_deg": max_elevation_deg,
                            "compensation_type": compensation_type,
                            "R_km": comp_case["R_km"],
                            "bearing_deg": comp_case["bearing_deg"],
                            "C_lat_deg": comp_case["C_lat_scalar"],
                            "C_lon_deg": comp_case["C_lon_scalar"],
                            "C_alt_m": comp_case["C_alt_scalar"],
                            "C_S_distance_km": comp_case["C_S_distance_scalar"],
                            "sanity_check_role": "upper_bound_sanity" if is_upper_bound_sanity else "attack_case",
                            "score_only_sanity_pass": score_only_sanity_pass,
                            "tri_state_applicable": tri_state_applicable,
                            "score_A_rmse_hz": verification.score_A_rmse_hz,
                            "b_hat_hz": verification.b_hat_hz,
                            "k_hat_hz_s": verification.k_hat_hz_s,
                            "threshold_95_hz": threshold_95,
                            "threshold_99_hz": threshold_99,
                            "accepted_p95": verification.accepted_95,
                            "accepted_p99": verification.accepted_99,
                            "target_k_min_p01": k_min,
                            "target_k_max_p99": k_max,
                            "accepted_per_target_k_p01_p99": accepted_score_k,
                            "tri_state_decision": decision,
                            "b_injected_hz": float(b_inj),
                            "k_injected_hz_s": float(k_inj),
                            "noise_sigma_hz": float(sigma_inj),
                            "u_comp_mean_hz": float(np.mean(u_comp)),
                            "u_comp_std_hz": float(np.std(u_comp, ddof=0)),
                            "u_comp_p95_abs_hz": float(np.quantile(np.abs(u_comp), 0.95)),
                            "attack_delta_rmse_hz": rmse(base_delta),
                            "attack_delta_mean_hz": float(np.mean(base_delta)),
                            "attack_delta_std_hz": float(np.std(base_delta, ddof=0)),
                            "observed_delta_rmse_hz": rmse(delta_obs),
                            "observed_delta_mean_hz": float(np.mean(delta_obs)),
                            "observed_delta_std_hz": float(np.std(delta_obs, ddof=0)),
                            "C_lat_min_deg": float(np.min(comp_case["C_lat_series"])),
                            "C_lat_max_deg": float(np.max(comp_case["C_lat_series"])),
                            "C_lon_min_deg": float(np.min(comp_case["C_lon_series"])),
                            "C_lon_max_deg": float(np.max(comp_case["C_lon_series"])),
                            "C_S_distance_min_km": float(np.min(comp_case["C_S_distance_series"])),
                            "C_S_distance_mean_km": float(np.mean(comp_case["C_S_distance_series"])),
                            "C_S_distance_max_km": float(np.max(comp_case["C_S_distance_series"])),
                            "C_S_distance_at_mid_km": float(comp_case["C_S_distance_series"][len(t_rel) // 2]),
                            "num_points": int(len(t_rel)),
                            "center_freq_hz": freq_hz,
                            "random_seed": int(args.seed),
                            "moving_reference_diff_step_s": float(args.moving_reference_diff_step_s),
                        }
                    )

                    dataset_rows.append(
                        pd.DataFrame(
                            {
                                "sequence_id": sequence_id,
                                "residual_mode": residual_mode,
                                "reference_mode": reference_mode,
                                "target_id": target_id,
                                "target_name": target_name,
                                "attacker_id": attacker_id,
                                "attacker_name": attacker_name,
                                "compensation_type": compensation_type,
                                "R_km": comp_case["R_km"],
                                "bearing_deg": comp_case["bearing_deg"],
                                "t_rel_s": t_rel,
                                "time_utc": geo_A["t_abs_utc"].to_numpy(str),
                                "f_geo_A_S_hz": f_geo_A_S,
                                "f_geo_B_S_hz": f_geo_B_S,
                                "f_geo_A_C_hz": comp_case["f_geo_A_C"],
                                "f_geo_B_C_hz": comp_case["f_geo_B_C"],
                                "u_comp_hz": u_comp,
                                "f_attack_base_hz": f_attack_base,
                                "b_injected_hz": float(b_inj),
                                "k_injected_hz_s": float(k_inj),
                                "noise_sigma_hz": float(sigma_inj),
                                "noise_injected_hz": noise_injected,
                                "f_attack_hz": f_obs_attack,
                                "delta_to_claimed_hz": delta_obs,
                                "delta_base_to_claimed_hz": base_delta,
                                "C_lat_deg": comp_case["C_lat_series"],
                                "C_lon_deg": comp_case["C_lon_series"],
                                "C_alt_m": comp_case["C_alt_series"],
                                "C_S_distance_km": comp_case["C_S_distance_series"],
                                "range_rate_A_C_mps": comp_case["rr_A_C"],
                                "range_rate_B_C_mps": comp_case["rr_B_C"],
                            }
                        )
                    )

    seq = pd.DataFrame(sequence_rows)
    data = pd.concat(dataset_rows, ignore_index=True) if dataset_rows else pd.DataFrame()
    summary = summarize(seq) if not seq.empty else pd.DataFrame()
    pairwise = build_pairwise_compare(seq) if not seq.empty else pd.DataFrame()
    distance_bins = build_distance_bins(pairwise) if not pairwise.empty else pd.DataFrame()
    controlled_r_summary = build_controlled_r_summary(seq) if not seq.empty else pd.DataFrame()
    controlled_r_pairwise = build_controlled_r_pairwise(seq) if not seq.empty else pd.DataFrame()

    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    args.pairwise_output.parent.mkdir(parents=True, exist_ok=True)
    args.distance_bins_output.parent.mkdir(parents=True, exist_ok=True)
    args.controlled_r_summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.controlled_r_pairwise_output.parent.mkdir(parents=True, exist_ok=True)
    seq.to_csv(args.sequence_output, index=False)
    summary.to_csv(args.summary_output, index=False)
    data.to_csv(args.dataset_output, index=False)
    pairwise.to_csv(args.pairwise_output, index=False)
    distance_bins.to_csv(args.distance_bins_output, index=False)
    controlled_r_summary.to_csv(args.controlled_r_summary_output, index=False)
    controlled_r_pairwise.to_csv(args.controlled_r_pairwise_output, index=False)

    print(f"wrote {args.sequence_output} rows={len(seq)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.dataset_output} rows={len(data)}")
    print(f"wrote {args.pairwise_output} rows={len(pairwise)}")
    print(f"wrote {args.distance_bins_output} rows={len(distance_bins)}")
    print(f"wrote {args.controlled_r_summary_output} rows={len(controlled_r_summary)}")
    print(f"wrote {args.controlled_r_pairwise_output} rows={len(controlled_r_pairwise)}")
    if not summary.empty:
        print(summary.to_string(index=False))
    direct = seq[seq["compensation_type"] == "direct_S_ideal"] if not seq.empty else pd.DataFrame()
    if not direct.empty:
        max_direct_delta = float(direct["attack_delta_rmse_hz"].max())
        direct_accepts = int(direct["accepted_p95"].sum())
        print(f"direct_S_ideal max attack_delta_rmse_hz={max_direct_delta:.6g}; accepted_p95={direct_accepts}/{len(direct)}")


if __name__ == "__main__":
    main()
