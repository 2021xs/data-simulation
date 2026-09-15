#!/usr/bin/env python
"""Controlled synthetic orbit-altitude difference risk experiment.

This is an isolated experiment runner.  It keeps the current formal verifier
unchanged and reuses the formal 60 s segment-local, fixed-site/segment-center,
single-window pipeline.  The smoke preset is intentionally small; the
confirmation preset is defined for a later explicitly-authorized run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from skyfield.api import load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_differential_doppler_mechanism_audit as mech  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_fixed_geometry_multi_realization_confirmation as fixed  # noqa: E402
import run_same_pair_multi_pass_confirmation as multipass  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402


BK_MODES = ["no_bk", "current_bk", "wide_bk"]
DIRECTIONS = list(multipass.DIRECTIONS)
DISTANCE_KM = float(multipass.DISTANCE_KM)
FD_STEPS_KM = list(multipass.FD_STEPS_KM)
FORMAL_TARGET_IDS = ["44714", "65409", "65410", "65421", "65686"]
SMOKE_DELTAS_KM = [-10.0, -1.0, 0.0, 1.0, 10.0]
FORMAL_DELTAS_KM = [-100.0, -50.0, -20.0, -10.0, -5.0, -2.0, -1.0, 0.0,
                    1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0]
MU_EARTH_KM3_S2 = float(base.MU_EARTH_KM3_S2)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="受控合成轨道高度差风险实验")
    p.add_argument("--preset", choices=["smoke", "confirmation"], default="smoke")
    p.add_argument("--target-ids", nargs="+", default=None)
    p.add_argument("--passes-per-target", type=int, default=None)
    p.add_argument("--realizations", type=int, default=None)
    p.add_argument("--delta-h-km", nargs="+", type=float, default=None)
    p.add_argument("--master-seed", type=int, default=20260823)
    p.add_argument("--num-benign-sims", type=int, default=30)
    p.add_argument("--selected-passes", type=Path, default=Path("outputs/metrics/same_pair_multi_pass_selected_passes.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def setup_args(args: argparse.Namespace) -> None:
    if args.target_ids is None:
        args.target_ids = [FORMAL_TARGET_IDS[0]] if args.preset == "smoke" else list(FORMAL_TARGET_IDS)
    args.target_ids = [str(x) for x in args.target_ids]
    if args.passes_per_target is None:
        args.passes_per_target = 1 if args.preset == "smoke" else 4
    if args.realizations is None:
        args.realizations = 2 if args.preset == "smoke" else 20
    if args.delta_h_km is None:
        args.delta_h_km = list(SMOKE_DELTAS_KM if args.preset == "smoke" else FORMAL_DELTAS_KM)
    args.delta_h_km = [float(x) for x in args.delta_h_km]
    if args.passes_per_target <= 0 or args.realizations <= 0:
        raise SystemExit("passes-per-target and realizations must be positive")


def output_paths(preset: str) -> dict[str, Path]:
    stem = "controlled_altitude_difference" + ("_smoke" if preset == "smoke" else "")
    return {
        "dataset": Path(f"outputs/datasets/{stem}_realization_dataset.csv"),
        "directions": Path(f"outputs/metrics/{stem}_direction_candidates.csv"),
        "geometry": Path(f"outputs/metrics/{stem}_geometry_summary.csv"),
        "altitude": Path(f"outputs/metrics/{stem}_altitude_summary.csv"),
        "pass_direction": Path(f"outputs/metrics/{stem}_pass_direction_summary.csv"),
        "visibility": Path(f"outputs/metrics/{stem}_visibility_summary.csv"),
        "validity_signed": Path(f"outputs/metrics/{stem}_validity_by_signed_height.csv"),
        "validity_absolute": Path(f"outputs/metrics/{stem}_validity_by_absolute_height.csv"),
        "validity_pass": Path(f"outputs/metrics/{stem}_validity_by_pass.csv"),
        "absolute_altitude": Path(f"outputs/metrics/{stem}_absolute_altitude_summary.csv"),
        "target_pass_height": Path(f"outputs/metrics/{stem}_target_pass_height_summary.csv"),
        "gate_failures": Path(f"outputs/metrics/{stem}_gate_failure_summary.csv"),
        "relationships": Path(f"outputs/metrics/{stem}_relationship_summary.csv"),
        "transitions": Path(f"outputs/metrics/{stem}_current_to_wide_transitions.csv"),
        "audit": Path(f"outputs/metrics/{stem}_correctness_audit.csv"),
        "manifest": Path(f"outputs/metrics/{stem}_manifest.json"),
        "report": Path(f"outputs/reports/{stem}_report.md"),
    }


def check_outputs(paths: dict[str, Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing and not overwrite:
        raise SystemExit("output exists; add --overwrite: " + ", ".join(existing))
    for p in paths.values():
        p.parent.mkdir(parents=True, exist_ok=True)


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype=np.float64).tobytes()).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def load_inputs(args: argparse.Namespace):
    required = [args.selected_passes, args.selection_table, args.candidate_library,
                args.tle_file, args.orbit_config, args.parameter_config]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("missing input: " + ", ".join(missing))
    loader = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library,
                             tle_file=args.tle_file, orbit_config=args.orbit_config,
                             parameter_config=args.parameter_config, max_targets=20)
    selection, library, orbit_cfg, tle, ranges = expanded.load_base_inputs(loader)
    if orbit_cfg.get("mode") != "controlled_starlink" or orbit_cfg.get("observation_id") is not None:
        raise SystemExit("requires controlled_starlink mode and observation_id=null")
    return selection, library, orbit_cfg, tle, ranges


def choose_passes(args: argparse.Namespace, tle: dict[str, dict[str, Any]]) -> pd.DataFrame:
    d = pd.read_csv(args.selected_passes, dtype={"target_sat_id": str, "attack_sat_id": str})
    needed = ["target_sat_id", "pass_id", "pass_start_time", "pass_end_time", "is_selected",
              "pass_selection_rank", "pass_source_type", "max_elevation_deg"]
    missing = [c for c in needed if c not in d.columns]
    if missing:
        raise SystemExit(f"selected pass input missing columns: {missing}")
    d = d[d["is_selected"].astype(str).str.lower().eq("true")]
    d = d[d["pass_source_type"].eq("same_tle_different_pass")]
    parts = []
    for target in args.target_ids:
        if target not in tle:
            raise SystemExit(f"target not in TLE: {target}")
        g = d[d["target_sat_id"].eq(target)].copy()
        g = g.sort_values(["pass_selection_rank", "pass_start_time", "pass_id"])
        g = g.drop_duplicates(["pass_start_time", "pass_end_time"])
        if len(g) < int(args.passes_per_target):
            raise SystemExit(f"{target}: only {len(g)} unambiguous selected same-TLE passes; need {args.passes_per_target}")
        g = g.head(int(args.passes_per_target)).copy()
        g["target_pass_rank"] = np.arange(1, len(g) + 1)
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def synthetic_state(sat_a: Any, ts: Any, times: list[Any], delta_h_km: float) -> dict[str, Any]:
    """Reconstruct positions for physical audit; formal Doppler still uses the existing generator."""
    sky_times = ts.from_datetimes(times)
    geo = sat_a.at(sky_times)
    pos = geo.position.km.T
    vel = geo.velocity.km_per_s.T
    mid = len(times) // 2
    r0 = pos[mid]
    v0 = vel[mid]
    h_hat = base.normalize(np.cross(r0, v0))
    p_hat = base.normalize(r0)
    q_hat = base.normalize(np.cross(h_hat, p_hat))
    if float(np.dot(v0, q_hat)) < 0:
        q_hat = -q_hat
    reference_radius = float(np.linalg.norm(r0))
    radius = reference_radius + float(delta_h_km)
    if radius <= 6300.0:
        raise SystemExit(f"invalid synthetic orbit radius: {radius}")
    omega = float(math.sqrt(MU_EARTH_KM3_S2 / radius**3))
    centered = np.array([(t - times[mid]).total_seconds() for t in times], dtype=float)
    theta = omega * centered
    positions = radius * (np.cos(theta)[:, None] * p_hat + np.sin(theta)[:, None] * q_hat)
    return {"positions_km": positions, "reference_radius_km": reference_radius,
            "synthetic_radius_km": radius, "angular_rate_rad_s": omega,
            "reference_angular_rate_rad_s": float(math.sqrt(MU_EARTH_KM3_S2 / reference_radius**3))}


def elevation_from_positions(positions_km: np.ndarray, lat: float, lon: float,
                             times: list[Any], ts: Any) -> np.ndarray:
    sky_times = ts.from_datetimes(times)
    surface = wgs84.latlon(float(lat), float(lon), elevation_m=0.0)
    upper = wgs84.latlon(float(lat), float(lon), elevation_m=1000.0)
    surface_pos = surface.at(sky_times).position.km.T
    upper_pos = upper.at(sky_times).position.km.T
    up = upper_pos - surface_pos
    up /= np.linalg.norm(up, axis=1)[:, None]
    los = np.asarray(positions_km) - surface_pos
    los /= np.linalg.norm(los, axis=1)[:, None]
    return np.degrees(np.arcsin(np.clip(np.sum(los * up, axis=1), -1.0, 1.0)))


def visibility_fields(prefix: str, a_elev: np.ndarray, b_elev: np.ndarray, threshold: float) -> dict[str, Any]:
    return {
        f"A_elevation_{prefix}_min_deg": float(np.min(a_elev)),
        f"A_elevation_{prefix}_mean_deg": float(np.mean(a_elev)),
        f"A_elevation_{prefix}_max_deg": float(np.max(a_elev)),
        f"B_elevation_{prefix}_min_deg": float(np.min(b_elev)),
        f"B_elevation_{prefix}_mean_deg": float(np.mean(b_elev)),
        f"B_elevation_{prefix}_max_deg": float(np.max(b_elev)),
        f"B_full60_above_horizon_at_{prefix}": bool(np.all(b_elev >= 0.0)),
        f"B_full60_above_existing_threshold_at_{prefix}": bool(np.all(b_elev >= threshold)),
        f"A_B_simultaneous_above_horizon_at_{prefix}": bool(np.all((a_elev >= 0.0) & (b_elev >= 0.0))),
        f"A_B_simultaneous_above_existing_threshold_at_{prefix}": bool(np.all((a_elev >= threshold) & (b_elev >= threshold))),
    }


def energy_absorption(raw: np.ndarray, remain: np.ndarray) -> float:
    return float(1.0 - np.sum(np.asarray(remain) ** 2) / max(np.sum(np.asarray(raw) ** 2), 1e-18))


def build_geometries(args: argparse.Namespace, passes: pd.DataFrame, orbit_cfg: dict[str, Any],
                     tle: dict[str, dict[str, Any]], ranges: dict[str, list[float]], ts: Any):
    freq = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz")
                 or orbit_cfg["frequency"]["center_freq_hz"])
    visibility_threshold = float(orbit_cfg["time_window"].get("min_elevation_deg", 10.0))
    candidates: list[dict[str, Any]] = []
    geometries: list[dict[str, Any]] = []
    generator_diffs: list[float] = []
    center_cancel: list[float] = []
    for _, pr in passes.sort_values(["target_sat_id", "target_pass_rank"]).iterrows():
        target = str(pr.target_sat_id)
        sat_a = tle[target]["sat"]
        ps = multipass.pass_segment(pr, sat_a, ts)
        et, times = ps["et"], ps["times"]
        cal_seed = fixed.derive_seed(args.master_seed, str(pr.pass_id), 0, "calibration")
        cal = seg.calibration_for_trel(et, ranges, cal_seed, int(args.num_benign_sims))
        fa_c, a_elev_c = seg.geo_curve_fixed(sat_a, ps["C_lat"], ps["C_lon"], 0.0, times, ts, freq, 1.0)
        for delta_h in args.delta_h_km:
            sample = {"sample_source": "legacy_synthetic", "target_sat_id": target,
                      "attack_sat_id": f"synthetic_delta_h_{delta_h:+g}km",
                      "attack_type": "same_plane_altitude_offset", "attack_param_value": float(delta_h)}
            state = synthetic_state(sat_a, ts, times, delta_h)
            fb_c = expanded.attack_geo(sample, sat_a, None, ps["C_lat"], ps["C_lon"], 0.0,
                                       times, ts, freq, 1.0)
            b_elev_c = elevation_from_positions(state["positions_km"], ps["C_lat"], ps["C_lon"], times, ts)
            fds = {h: mech.finite_difference(sample, sat_a, None, ps["C_lat"], ps["C_lon"],
                                              times, ts, freq, 1.0, h) for h in FD_STEPS_KM}
            je, jn = fds[1.0]
            jp = mech.projected_jacobian(np.column_stack([je, jn]), et)
            _u, sv, vt = np.linalg.svd(jp, full_matrices=False)
            scaled_sv = sv / math.sqrt(len(et))
            weak_vec = vt[-1]
            fd_norm = {h: float(np.sqrt(np.mean(np.column_stack(fds[h]) ** 2))) for h in FD_STEPS_KM}
            stability = max(abs(fd_norm[0.5] - fd_norm[1.0]), abs(fd_norm[2.0] - fd_norm[1.0])) / max(fd_norm[1.0], 1e-12)
            pass_candidates = []
            for direction in DIRECTIONS:
                theta = math.radians(direction)
                vec = np.array([math.sin(theta), math.cos(theta)])
                sensitivity = float(np.sqrt(np.mean((jp @ vec) ** 2)))
                pass_candidates.append({
                    "target_sat_id": target, "pass_id": str(pr.pass_id), "delta_h_km": float(delta_h),
                    "abs_delta_h_km": abs(float(delta_h)), "is_reference_delta_h_zero": bool(delta_h == 0.0),
                    "direction_deg": float(direction),
                    "direction_sensitivity_hz_per_km": sensitivity,
                    "weakest_direction_sensitivity_hz_per_km": float(scaled_sv[-1]),
                    "strongest_direction_sensitivity_hz_per_km": float(scaled_sv[0]),
                    "anisotropy_ratio": float(scaled_sv[0] / scaled_sv[-1]) if scaled_sv[-1] > 1e-12 else math.inf,
                    "weakest_direction_deg_continuous": float((math.degrees(math.atan2(weak_vec[0], weak_vec[1])) + 360.0) % 180.0),
                    "finite_difference_norm_0p5km": fd_norm[0.5], "finite_difference_norm_1km": fd_norm[1.0],
                    "finite_difference_norm_2km": fd_norm[2.0],
                    "finite_difference_max_relative_change_0p5_1_2km": stability,
                })
            pc = pd.DataFrame(pass_candidates)
            low = float(pc.loc[pc.direction_sensitivity_hz_per_km.idxmin(), "direction_deg"])
            opposite = (low + 180.0) % 360.0
            remaining = pc[~pc.direction_deg.isin([low, opposite])]
            high = float(remaining.loc[remaining.direction_sensitivity_hz_per_km.idxmax(), "direction_deg"])
            roles = {low: "lowest_sensitivity", opposite: "opposite_of_lowest", high: "high_sensitivity_control"}
            pc["is_selected_direction"] = pc.direction_deg.isin(roles)
            pc["direction_role"] = pc.direction_deg.map(roles).fillna("not_selected")
            candidates.extend(pc.to_dict("records"))
            for direction, role in roles.items():
                s_lat, s_lon = seg.destination(ps["C_lat"], ps["C_lon"], DISTANCE_KM, direction)
                fa_s, a_elev_s = seg.geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, times, ts, freq, 1.0)
                fb_s = expanded.attack_geo(sample, sat_a, None, s_lat, s_lon, 0.0, times, ts, freq, 1.0)
                b_elev_s = elevation_from_positions(state["positions_km"], s_lat, s_lon, times, ts)
                raw = fb_s + fa_c - fb_c - fa_s
                geo_b, geo_k, geo_fit = mech.fit_unbounded(raw, et)
                remain = raw - geo_fit
                gid = stable_id("altitude_geometry", {"target": target, "pass": str(pr.pass_id),
                                                        "delta_h": delta_h, "direction": direction})
                th_current = seg.threshold_for(cal, "full_pass", "current_bk")
                bounded_b, bounded_k, bounded_fit = mech.fit_bounded(
                    raw, et, (-th_current["b_threshold"], th_current["b_threshold"]),
                    (-th_current["k_threshold"], th_current["k_threshold"]))
                b_existing = base.synthetic_same_plane_geo(sat_a, wgs84.latlon(s_lat, s_lon), ts, times,
                                                            freq, float(delta_h), 0.0)
                generator_diffs.append(float(np.max(np.abs(fb_s - b_existing))))
                center_cancel.append(float(np.max(np.abs(fb_c + (fa_c - fb_c) - fa_c))))
                visibility = {}
                visibility.update(visibility_fields("S", a_elev_s, b_elev_s, visibility_threshold))
                visibility.update(visibility_fields("C", a_elev_c, b_elev_c, visibility_threshold))
                visibility["visibility_threshold_deg_existing_pass_definition"] = visibility_threshold
                visibility["physical_visibility_horizon_full60"] = bool(
                    visibility["A_B_simultaneous_above_horizon_at_S"]
                    and visibility["A_B_simultaneous_above_horizon_at_C"])
                visibility["physical_visibility_existing_threshold_full60"] = bool(
                    visibility["A_B_simultaneous_above_existing_threshold_at_S"]
                    and visibility["A_B_simultaneous_above_existing_threshold_at_C"])
                geometries.append({
                    "geometry_condition_id": gid, "target_sat_id": target,
                    "target_name": tle[target]["name"], "pass_id": str(pr.pass_id),
                    "target_pass_rank": int(pr.target_pass_rank), "pass_start_time": str(pr.pass_start_time),
                    "pass_end_time": str(pr.pass_end_time), "pass_max_elevation_deg": float(pr.max_elevation_deg),
                    "service_segment_index": int(ps["segment_index"]),
                    "service_segment_start": ps["service_segment_start"], "service_segment_end": ps["service_segment_end"],
                    "C_lat": float(ps["C_lat"]), "C_lon": float(ps["C_lon"]),
                    "S_lat": float(s_lat), "S_lon": float(s_lon), "distance_km": DISTANCE_KM,
                    "direction_deg": float(direction), "direction_role": role,
                    "direction_sensitivity_hz_per_km": float(pc.loc[pc.direction_deg.eq(direction), "direction_sensitivity_hz_per_km"].iloc[0]),
                    "delta_h_km": float(delta_h), "abs_delta_h_km": abs(float(delta_h)),
                    "is_reference_delta_h_zero": bool(delta_h == 0.0),
                    "non_target_risk_eligible": bool(delta_h != 0.0),
                    "reference_orbit_radius_km": state["reference_radius_km"],
                    "synthetic_B_radius_km": state["synthetic_radius_km"],
                    "reference_angular_rate_rad_s": state["reference_angular_rate_rad_s"],
                    "synthetic_B_angular_rate_rad_s": state["angular_rate_rad_s"],
                    "raw_geo_rmse_hz": float(np.sqrt(np.mean(raw**2))),
                    "raw_geo_max_abs_hz": float(np.max(np.abs(raw))),
                    "unbounded_geometry_b_hat_hz": geo_b,
                    "unbounded_geometry_k_hat_hz_per_s": geo_k,
                    "unbounded_geometry_post_rmse_hz": float(np.sqrt(np.mean(remain**2))),
                    "unbounded_geometry_absorption_ratio": energy_absorption(raw, remain),
                    "geometry_tolerance_budget_b_hz": bounded_b,
                    "geometry_tolerance_budget_k_hz_per_s": bounded_k,
                    "geometry_tolerance_budget_post_rmse_hz": float(np.sqrt(np.mean((raw - bounded_fit)**2))),
                    "geometry_tolerance_budget_absorption_ratio": energy_absorption(raw, raw - bounded_fit),
                    "finite_difference_max_relative_change_0p5_1_2km": stability,
                    "calibration_seed": cal_seed, "point_count": len(et), **visibility,
                    "sat_a": sat_a, "et": et, "full_t": ps["full_t"], "mask": ps["mask"],
                    "fa_s": fa_s, "raw": raw, "cal": cal,
                })
    return pd.DataFrame(candidates), geometries, generator_diffs, center_cancel, visibility_threshold, freq


def generate_realizations(args: argparse.Namespace, geometries: list[dict[str, Any]],
                          ranges: dict[str, list[float]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    hidden = {"sat_a", "et", "full_t", "mask", "fa_s", "raw", "cal"}
    for geo in geometries:
        et = geo["et"]
        coverage = np.ones(len(et), dtype=bool)
        t0 = float(np.mean(geo["full_t"]))
        base_fields = {k: v for k, v in geo.items() if k not in hidden}
        for ridx in range(int(args.realizations)):
            env_seed = fixed.derive_seed(args.master_seed, geo["geometry_condition_id"], ridx, "environment")
            noise_seed = fixed.derive_seed(args.master_seed, geo["geometry_condition_id"], ridx, "noise")
            err = base.sample_error_params(ranges, np.random.default_rng(env_seed))
            full_noise = np.random.default_rng(noise_seed).normal(0.0, err.sigma_hz, len(geo["full_t"]))
            noise = full_noise[geo["mask"]]
            y = geo["fa_s"] + geo["raw"] + err.b_hz + err.k_hz_s * (et - t0) + noise
            obs_id = stable_id("altitude_observation", {"geometry": geo["geometry_condition_id"],
                                                          "realization": ridx, "environment_seed": env_seed,
                                                          "noise_seed": noise_seed, "calibration_seed": geo["calibration_seed"]})
            for mode in BK_MODES:
                dec = seg.evaluate_single_station(y_obs=y, f_geo_a=geo["fa_s"], t_rel=et,
                                                  coverage_mask=coverage, cal=geo["cal"],
                                                  bk_mode=mode, verification_strategy="single-window")
                th = seg.threshold_for(geo["cal"], "full_pass", mode)
                quality = bool(np.isfinite([dec.residual_rmse_hz, dec.b_hat_hz, dec.k_hat_hz_per_s]).all())
                rows.append({**base_fields, "observation_realization_id": obs_id,
                    "realization_index": ridx, "master_seed": int(args.master_seed),
                    "environment_seed": int(env_seed), "noise_seed": int(noise_seed),
                    "noise_hash": array_hash(noise), "observation_vector_hash": array_hash(y),
                    "b_env_hz": float(err.b_hz), "k_env_hz_per_s": float(err.k_hz_s),
                    "noise_sigma_hz": float(err.sigma_hz), "bk_mode": mode,
                    "formal_score_hz": float(dec.residual_rmse_hz),
                    "formal_score_threshold_hz": float(th["score_threshold"]),
                    "formal_b_hat_hz": float(dec.b_hat_hz), "formal_b_center_hz": float(th["b_center"]),
                    "formal_b_threshold_hz": float(th["b_threshold"]),
                    "formal_k_hat_hz_per_s": float(dec.k_hat_hz_per_s),
                    "formal_k_center_hz_per_s": float(th["k_center"]),
                    "formal_k_threshold_hz_per_s": float(th["k_threshold"]),
                    "score_gate_margin_hz": float(th["score_threshold"] - dec.residual_rmse_hz),
                    "b_gate_margin_hz": float(th["b_threshold"] - abs(dec.b_hat_hz - th["b_center"])),
                    "k_gate_margin_hz_per_s": float(th["k_threshold"] - abs(dec.k_hat_hz_per_s - th["k_center"])),
                    "score_gate_pass": bool(dec.score_gate_pass), "b_gate_pass": bool(dec.b_gate_pass),
                    "k_gate_pass": bool(dec.k_gate_pass), "coverage_gate_pass": bool(dec.coverage_gate_pass),
                    "quality_gate_pass": quality, "final_decision": str(dec.decision),
                    "accept_flag": bool(dec.decision == "ACCEPT"),
                    "primary_reject_gate": fixed.primary_gate(dec.score_gate_pass, dec.b_gate_pass,
                                                               dec.k_gate_pass, dec.coverage_gate_pass, quality),
                    "T_service_s": 60.0, "evaluation_scope": "segment_local",
                    "doppler_reference_mode": "fixed_site_segment_center",
                    "verification_strategy": "single-window"})
    return pd.DataFrame(rows)


def geometry_summary(data: pd.DataFrame) -> pd.DataFrame:
    keys = ["geometry_condition_id", "target_sat_id", "pass_id", "delta_h_km", "abs_delta_h_km",
            "is_reference_delta_h_zero", "non_target_risk_eligible", "direction_deg", "direction_role", "bk_mode"]
    rows = []
    for key, g in data.groupby(keys, dropna=False, sort=True):
        first = g.iloc[0]
        rows.append({**dict(zip(keys, key)), "geometry_count": 1,
            "observation_realization_count": len(g), "accept_count": int(g.accept_flag.sum()),
            "accept_fraction": float(g.accept_flag.mean()),
            "raw_geo_rmse_hz": float(first.raw_geo_rmse_hz),
            "direction_sensitivity_hz_per_km": float(first.direction_sensitivity_hz_per_km),
            "unbounded_geometry_b_hat_hz": float(first.unbounded_geometry_b_hat_hz),
            "unbounded_geometry_k_hat_hz_per_s": float(first.unbounded_geometry_k_hat_hz_per_s),
            "unbounded_geometry_post_rmse_hz": float(first.unbounded_geometry_post_rmse_hz),
            "unbounded_geometry_absorption_ratio": float(first.unbounded_geometry_absorption_ratio),
            "score_margin_mean_hz": float(g.score_gate_margin_hz.mean()),
            "b_margin_mean_hz": float(g.b_gate_margin_hz.replace([np.inf, -np.inf], np.nan).mean()),
            "k_margin_mean_hz_per_s": float(g.k_gate_margin_hz_per_s.replace([np.inf, -np.inf], np.nan).mean()),
            "physical_visibility_horizon_full60": bool(first.physical_visibility_horizon_full60),
            "physical_visibility_existing_threshold_full60": bool(first.physical_visibility_existing_threshold_full60)})
    return pd.DataFrame(rows)


def add_paired_reference(geometry: pd.DataFrame) -> pd.DataFrame:
    """Subtract delta_h=0 only when the exact geographic direction is available."""
    keys = ["target_sat_id", "pass_id", "direction_deg", "bk_mode"]
    metrics = ["raw_geo_rmse_hz", "unbounded_geometry_post_rmse_hz",
               "direction_sensitivity_hz_per_km"]
    ref = geometry[geometry.is_reference_delta_h_zero.astype(bool)][keys + metrics].copy()
    ref = ref.rename(columns={m: f"{m}_delta_h_zero_reference" for m in metrics})
    out = geometry.merge(ref, on=keys, how="left", validate="many_to_one")
    out["paired_reference_available_exact_direction"] = out[f"{metrics[0]}_delta_h_zero_reference"].notna()
    for metric in metrics:
        out[f"{metric}_delta_from_zero"] = out[metric] - out[f"{metric}_delta_h_zero_reference"]
    out["paired_reference_basis"] = np.where(
        out.paired_reference_available_exact_direction,
        "same_target_pass_exact_direction_deg", "unavailable_reselected_direction_not_in_zero_reference")
    return out


def summarized_rates(data: pd.DataFrame, group_cols: list[str], scope: str) -> pd.DataFrame:
    rows = []
    eligible = data[data.non_target_risk_eligible.astype(bool)].copy()
    if scope == "horizon_full60":
        eligible = eligible[eligible.physical_visibility_horizon_full60.astype(bool)]
    elif scope == "existing_threshold_full60":
        eligible = eligible[eligible.physical_visibility_existing_threshold_full60.astype(bool)]
    for key, g in eligible.groupby(group_cols, dropna=False, sort=True):
        rows.append({**dict(zip(group_cols, key if isinstance(key, tuple) else (key,))),
            "visibility_scope": scope, "geometry_condition_count": int(g.geometry_condition_id.nunique()),
            "observation_realization_count": int(g.observation_realization_id.nunique()),
            "mode_row_count": len(g), "accept_count": int(g.accept_flag.sum()),
            "accept_fraction": float(g.accept_flag.mean()),
            "raw_geo_rmse_mean_hz": float(g.drop_duplicates("geometry_condition_id").raw_geo_rmse_hz.mean()),
            "direction_sensitivity_mean_hz_per_km": float(g.drop_duplicates("geometry_condition_id").direction_sensitivity_hz_per_km.mean()),
            "post_bk_geometry_rmse_mean_hz": float(g.drop_duplicates("geometry_condition_id").unbounded_geometry_post_rmse_hz.mean()),
            "geometry_k_component_mean_hz_per_s": float(g.drop_duplicates("geometry_condition_id").unbounded_geometry_k_hat_hz_per_s.mean()),
            "score_margin_mean_hz": float(g.score_gate_margin_hz.mean()),
            "b_margin_mean_hz": float(g.b_gate_margin_hz.replace([np.inf, -np.inf], np.nan).mean()),
            "k_margin_mean_hz_per_s": float(g.k_gate_margin_hz_per_s.replace([np.inf, -np.inf], np.nan).mean())})
    return pd.DataFrame(rows)


def visibility_summary(data: pd.DataFrame) -> pd.DataFrame:
    d = data.drop_duplicates("geometry_condition_id")
    rows = []
    for key, g in d.groupby(["delta_h_km", "abs_delta_h_km", "direction_role"], sort=True):
        rows.append({"delta_h_km": key[0], "abs_delta_h_km": key[1], "direction_role": key[2],
            "geometry_condition_count": len(g),
            "horizon_full60_count": int(g.physical_visibility_horizon_full60.sum()),
            "existing_threshold_full60_count": int(g.physical_visibility_existing_threshold_full60.sum()),
            "B_elevation_S_min_deg": float(g.B_elevation_S_min_deg.min()),
            "B_elevation_S_mean_deg": float(g.B_elevation_S_mean_deg.mean()),
            "B_elevation_S_max_deg": float(g.B_elevation_S_max_deg.max()),
            "B_elevation_C_min_deg": float(g.B_elevation_C_min_deg.min()),
            "B_elevation_C_mean_deg": float(g.B_elevation_C_mean_deg.mean()),
            "B_elevation_C_max_deg": float(g.B_elevation_C_max_deg.max())})
    return pd.DataFrame(rows)


def validity_tables(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = data.drop_duplicates("geometry_condition_id").copy()
    def summarize(cols: list[str]) -> pd.DataFrame:
        rows = []
        for key, g in d.groupby(cols, dropna=False, sort=True):
            values = key if isinstance(key, tuple) else (key,)
            n = len(g); n10 = int(g.physical_visibility_existing_threshold_full60.sum()); n0 = int(g.physical_visibility_horizon_full60.sum())
            rows.append({**dict(zip(cols, values)), "generated_geometry_count": n,
                "valid_10deg_full60_geometry_count": n10, "valid_10deg_full60_fraction": n10 / n if n else np.nan,
                "valid_0deg_full60_geometry_count": n0, "valid_0deg_full60_fraction": n0 / n if n else np.nan,
                "reference_geometry_count": int(g.is_reference_delta_h_zero.sum()),
                "non_target_risk_eligible_geometry_count": int(g.non_target_risk_eligible.sum())})
        return pd.DataFrame(rows)
    return (summarize(["delta_h_km"]), summarize(["abs_delta_h_km"]),
            summarize(["target_sat_id", "pass_id", "delta_h_km"]))


def relationship_summary(geometry: pd.DataFrame) -> pd.DataFrame:
    base_geometry = geometry[(geometry.bk_mode == "current_bk") & geometry.non_target_risk_eligible.astype(bool)].copy()
    metrics = ["raw_geo_rmse_hz", "direction_sensitivity_hz_per_km",
               "unbounded_geometry_post_rmse_hz", "unbounded_geometry_k_hat_hz_per_s", "accept_fraction"]
    rows = []
    for scope in ["all", "horizon_full60", "existing_threshold_full60"]:
        d = base_geometry.copy()
        if scope == "horizon_full60":
            d = d[d.physical_visibility_horizon_full60.astype(bool)]
        elif scope == "existing_threshold_full60":
            d = d[d.physical_visibility_existing_threshold_full60.astype(bool)]
        strata = [("all", d)] + [(f"direction:{k}", g) for k, g in d.groupby("direction_role")]
        for stratum, g in strata:
            for x in ["delta_h_km", "abs_delta_h_km"]:
                for metric in metrics:
                    valid = g[[x, metric]].replace([np.inf, -np.inf], np.nan).dropna()
                    if len(valid) >= 3 and valid[x].nunique() >= 2 and valid[metric].nunique() >= 2:
                        rho, p = spearmanr(valid[x], valid[metric])
                    else:
                        rho, p = np.nan, np.nan
                    rows.append({"visibility_scope": scope, "stratum": stratum, "x_variable": x, "metric": metric,
                                 "n_geometry_conditions": len(valid), "spearman_rho": rho, "p_value": p,
                                 "notes": "descriptive rank correlation; geometry condition unit"})
    return pd.DataFrame(rows)


def gate_failure_summary(data: pd.DataFrame) -> pd.DataFrame:
    d = data[data.non_target_risk_eligible.astype(bool) & data.physical_visibility_existing_threshold_full60.astype(bool)
             & data.bk_mode.eq("current_bk")].copy()
    rows = []
    cols = ["delta_h_km", "abs_delta_h_km", "direction_role"]
    for key, g in d.groupby(cols, sort=True):
        rows.append({**dict(zip(cols, key)), "realization_count": len(g), "accept_count": int(g.accept_flag.sum()),
            "score_failure_count": int((~g.score_gate_pass.astype(bool)).sum()),
            "b_failure_count": int((~g.b_gate_pass.astype(bool)).sum()),
            "k_failure_count": int((~g.k_gate_pass.astype(bool)).sum()),
            "score_only_primary_failure_count": int(g.primary_reject_gate.eq("score").sum()),
            "b_only_primary_failure_count": int(g.primary_reject_gate.eq("b").sum()),
            "k_only_primary_failure_count": int(g.primary_reject_gate.eq("k").sum()),
            "multiple_gate_failure_count": int(g.primary_reject_gate.eq("multiple").sum())})
    return pd.DataFrame(rows)


def transition_summary(data: pd.DataFrame) -> pd.DataFrame:
    keys = ["geometry_condition_id", "observation_realization_id"]
    cur = data[data.bk_mode.eq("current_bk")].set_index(keys)
    wide = data[data.bk_mode.eq("wide_bk")].set_index(keys)
    joined = cur[["final_decision", "b_gate_pass", "k_gate_pass", "delta_h_km"]].join(
        wide[["final_decision", "b_gate_pass", "k_gate_pass"]], lsuffix="_current", rsuffix="_wide")
    def reason(r: pd.Series) -> str:
        if r.final_decision_current != "REJECT" or r.final_decision_wide != "ACCEPT":
            return "not_applicable"
        b = (not r.b_gate_pass_current) and r.b_gate_pass_wide
        k = (not r.k_gate_pass_current) and r.k_gate_pass_wide
        return "b/k同时解除" if b and k else "b gate解除" if b else "k gate解除" if k else "其他"
    joined["transition"] = joined.final_decision_current + " -> " + joined.final_decision_wide
    joined["gate_release_reason"] = joined.apply(reason, axis=1)
    return joined.reset_index().groupby(["delta_h_km", "transition", "gate_release_reason"], dropna=False).size().reset_index(name="realization_count")


def correctness_audit(args: argparse.Namespace, passes: pd.DataFrame, directions: pd.DataFrame,
                      data: pd.DataFrame, generator_diffs: list[float], center_cancel: list[float],
                      before_hashes: dict[str, str], after_hashes: dict[str, str]) -> pd.DataFrame:
    rows = []
    def add(check: str, passed: bool, observed: Any, expected: Any) -> None:
        rows.append({"check": check, "passed": bool(passed), "observed": json.dumps(observed, ensure_ascii=False, default=str),
                     "expected": json.dumps(expected, ensure_ascii=False, default=str)})
    add("目标和pass数量", passes.target_sat_id.nunique() == len(args.target_ids)
        and len(passes) == len(args.target_ids) * args.passes_per_target,
        {"targets": passes.target_sat_id.nunique(), "passes": len(passes)},
        {"targets": len(args.target_ids), "passes": len(args.target_ids) * args.passes_per_target})
    pass_counts = passes.groupby("target_sat_id").pass_id.nunique()
    add("每个target恰好指定pass数", pass_counts.eq(args.passes_per_target).all(), pass_counts.to_dict(), args.passes_per_target)
    observed_nonzero = sorted(data.loc[data.non_target_risk_eligible.astype(bool), "delta_h_km"].astype(float).unique().tolist())
    expected_nonzero = sorted(float(x) for x in args.delta_h_km if float(x) != 0.0)
    add("非零signed高度集合完整", observed_nonzero == expected_nonzero, observed_nonzero, expected_nonzero)
    selected = directions[directions.is_selected_direction.astype(bool)]
    counts = selected.groupby(["target_sat_id", "pass_id", "delta_h_km"]).direction_role.nunique()
    add("每个target-pass-height选择三个方向", counts.eq(3).all(), counts.value_counts().to_dict(), 3)
    low = selected[selected.direction_role.eq("lowest_sensitivity")]
    mins = directions.groupby(["target_sat_id", "pass_id", "delta_h_km"]).direction_sensitivity_hz_per_km.min()
    lowv = low.set_index(["target_sat_id", "pass_id", "delta_h_km"]).direction_sensitivity_hz_per_km
    add("lowest为八方向离散最小值", np.allclose(lowv.sort_index(), mins.sort_index()), True, True)
    pivot = selected.pivot_table(index=["target_sat_id", "pass_id", "delta_h_km"], columns="direction_role", values="direction_deg", aggfunc="first")
    add("opposite方向为lowest加180度", np.allclose((pivot.lowest_sensitivity + 180.0) % 360.0, pivot.opposite_of_lowest), True, True)
    expected_rows = len(args.target_ids) * args.passes_per_target * len(args.delta_h_km) * 3 * args.realizations * len(BK_MODES)
    add("realization模式行数", len(data) == expected_rows, len(data), expected_rows)
    realization_counts = data.groupby(["geometry_condition_id", "bk_mode"]).size()
    add("每geometry每mode恰好指定realization数", realization_counts.eq(args.realizations).all(),
        realization_counts.value_counts().to_dict(), args.realizations)
    formal = data[data.non_target_risk_eligible.astype(bool)]
    add("delta_h=0仅为reference且排除正式风险", data[data.delta_h_km.eq(0)].non_target_risk_eligible.eq(False).all()
        and formal.delta_h_km.ne(0).all(), True, True)
    radius_err = float((data.synthetic_B_radius_km - data.reference_orbit_radius_km - data.delta_h_km).abs().max())
    omega_formula = np.sqrt(MU_EARTH_KM3_S2 / data.synthetic_B_radius_km.astype(float) ** 3)
    omega_err = float(np.max(np.abs(data.synthetic_B_angular_rate_rad_s - omega_formula)))
    add("高度差同时改变半径并按开普勒公式改变角速度", radius_err < 1e-9 and omega_err < 1e-15,
        {"radius_error_km": radius_err, "omega_error": omega_err}, {"radius_error_km": "<1e-9", "omega_error": "<1e-15"})
    add("正式B Doppler复用现有synthetic_same_plane_geo", max(generator_diffs, default=np.nan) < 1e-9,
        max(generator_diffs, default=np.nan), "<1e-9 Hz")
    add("主动补偿只按C且C处代数抵消", max(center_cancel, default=np.nan) < 1e-9,
        max(center_cancel, default=np.nan), "<1e-9 Hz")
    keys = ["geometry_condition_id", "observation_realization_id"]
    cur = data[data.bk_mode.eq("current_bk")].set_index(keys).sort_index()
    wide = data[data.bk_mode.eq("wide_bk")].set_index(keys).sort_index()
    fit_delta = {c: float(np.max(np.abs(cur[c] - wide[c]))) for c in ["formal_score_hz", "formal_b_hat_hz", "formal_k_hat_hz_per_s"]}
    add("current和wide共享完全相同正式拟合", all(v < 1e-10 for v in fit_delta.values()), fit_delta, "all <1e-10")
    add("visibility字段完整且有限", data[["B_elevation_S_min_deg", "B_elevation_S_mean_deg", "B_elevation_S_max_deg",
                                             "B_elevation_C_min_deg", "B_elevation_C_mean_deg", "B_elevation_C_max_deg"]].apply(np.isfinite).all().all(), True, True)
    seed_unique = data.drop_duplicates(["geometry_condition_id", "realization_index"])
    add("geometry-realization seed唯一", seed_unique.environment_seed.is_unique and seed_unique.noise_seed.is_unique,
        {"environment": seed_unique.environment_seed.nunique(), "noise": seed_unique.noise_seed.nunique()}, len(seed_unique))
    replay_env = seed_unique.apply(lambda r: fixed.derive_seed(args.master_seed, r.geometry_condition_id,
        int(r.realization_index), "environment") == int(r.environment_seed), axis=1)
    replay_noise = seed_unique.apply(lambda r: fixed.derive_seed(args.master_seed, r.geometry_condition_id,
        int(r.realization_index), "noise") == int(r.noise_seed), axis=1)
    add("全部environment/noise seed派生可重放", bool(replay_env.all() and replay_noise.all()),
        {"environment": int(replay_env.sum()), "noise": int(replay_noise.sum())}, len(seed_unique))
    sample = data.iloc[0]
    regen_err = base.sample_error_params(
        {"b_hz": [3179.0, 3728.0], "k_hz_per_s": [-1.110156, -0.197808], "sigma_hz": [23.215, 32.89]},
        np.random.default_rng(int(sample.environment_seed)))
    seed_replay = abs(regen_err.b_hz - sample.b_env_hz) < 1e-12 and abs(regen_err.k_hz_s - sample.k_env_hz_per_s) < 1e-12 and abs(regen_err.sigma_hz - sample.noise_sigma_hz) < 1e-12
    add("环境seed可重放", seed_replay, seed_replay, True)
    add("旧正式输入运行前后SHA256一致", before_hashes == after_hashes, after_hashes, before_hashes)
    add("正式语义字段固定", data.T_service_s.eq(60).all() and data.evaluation_scope.eq("segment_local").all()
        and data.doppler_reference_mode.eq("fixed_site_segment_center").all()
        and data.verification_strategy.eq("single-window").all(), True, True)
    return pd.DataFrame(rows)


def write_formal_report(args: argparse.Namespace, paths: dict[str, Path], data: pd.DataFrame,
                        geometry: pd.DataFrame, altitude: pd.DataFrame, absolute_altitude: pd.DataFrame,
                        target_pass_height: pd.DataFrame, visibility: pd.DataFrame,
                        validity_signed: pd.DataFrame, validity_absolute: pd.DataFrame,
                        relationships: pd.DataFrame, transitions: pd.DataFrame,
                        gate_failures: pd.DataFrame, audit: pd.DataFrame,
                        visibility_threshold: float) -> None:
    cur_main = geometry[(geometry.bk_mode == "current_bk") & geometry.non_target_risk_eligible.astype(bool)
                        & geometry.physical_visibility_existing_threshold_full60.astype(bool)].copy()
    signed_risk = altitude[(altitude.bk_mode == "current_bk") & altitude.visibility_scope.eq("existing_threshold_full60")]
    absolute_risk = absolute_altitude[(absolute_altitude.bk_mode == "current_bk") & absolute_altitude.visibility_scope.eq("existing_threshold_full60")]
    relation = relationships[(relationships.visibility_scope == "existing_threshold_full60")
                             & (relationships.stratum == "all")]
    direction = cur_main.groupby("direction_role", as_index=False).agg(
        geometry_conditions=("geometry_condition_id", "nunique"), mean_accept_fraction=("accept_fraction", "mean"),
        median_accept_fraction=("accept_fraction", "median"), raw_geo_rmse_median_hz=("raw_geo_rmse_hz", "median"),
        post_bk_geo_rmse_median_hz=("unbounded_geometry_post_rmse_hz", "median"),
        direction_sensitivity_median_hz_per_km=("direction_sensitivity_hz_per_km", "median"))
    pass_cur = target_pass_height[(target_pass_height.bk_mode == "current_bk")
                                  & target_pass_height.visibility_scope.eq("existing_threshold_full60")]
    pass_spread = pass_cur.groupby("delta_h_km", as_index=False).agg(
        target_pass_conditions=("pass_id", "size"), min_target_pass_accept_fraction=("accept_fraction", "min"),
        median_target_pass_accept_fraction=("accept_fraction", "median"),
        max_target_pass_accept_fraction=("accept_fraction", "max"),
        target_passes_with_any_accept=("accept_count", lambda x: int((x > 0).sum())))
    asym = signed_risk[["delta_h_km", "abs_delta_h_km", "accept_fraction"]].copy()
    asym["sign"] = np.where(asym.delta_h_km > 0, "positive", "negative")
    asym = asym.pivot_table(index="abs_delta_h_km", columns="sign", values="accept_fraction", aggfunc="first").reset_index()
    if "positive" in asym and "negative" in asym:
        asym["positive_minus_negative_accept_fraction"] = asym.positive - asym.negative
    paired_nonzero = cur_main[cur_main.non_target_risk_eligible.astype(bool)]
    paired_counts = paired_nonzero.paired_reference_available_exact_direction.value_counts().to_dict()
    largest_accepted = cur_main[cur_main.accept_fraction.gt(0)].sort_values(
        ["abs_delta_h_km", "accept_fraction"], ascending=[False, False]).head(20)
    gate_total = gate_failures.groupby("delta_h_km", as_index=False)[[
        "realization_count", "accept_count", "score_failure_count", "b_failure_count", "k_failure_count",
        "score_only_primary_failure_count", "b_only_primary_failure_count", "k_only_primary_failure_count",
        "multiple_gate_failure_count"]].sum()
    text = f"""# 受控合成轨道高度差风险正式实验报告

## 1. 实验边界与规模

本实验保持合法 A 的真实 Starlink TLE 和 A 定义的 pass 不变；B 是由 A 的 mid-pass 状态构造的同轨道面圆轨道近似，不是真实 Starlink 攻击轨道。高度变化通过半径与开普勒角速度共同变化实现。正式 verifier、score/b/k/coverage 门限和 final decision 均未修改。

- target：{len(args.target_ids)}，ID={args.target_ids}
- 每 target same-TLE pass：{args.passes_per_target}
- signed nonzero delta_h：{[x for x in args.delta_h_km if x != 0]}
- 额外 reference：delta_h=0；不进入非目标风险
- 每 target×pass×height：重新计算8方向，选择 lowest/opposite/high
- 每 geometry realization：{args.realizations}
- 独立 observation：{data.observation_realization_id.nunique()}
- mode rows：{len(data)}；current_bk 为正式主口径

## 2. 数据有效性

正式主筛选为 A/B 在 S、C 全60秒均 `elevation >= {visibility_threshold:g}°`；`>=0°` 仅作敏感性对照。visibility 不进入 final decision，也没有因 B 不可见重选 pass。

### Signed height

{validity_signed.to_markdown(index=False)}

### Absolute height

{validity_absolute.to_markdown(index=False)}

## 3. 高度与几何机制量

下表是 current geometry、10°有效条件、geometry-condition unit 的描述性 Spearman；相关性不解释为普遍因果律。

{relation[["x_variable","metric","n_geometry_conditions","spearman_rho","p_value"]].to_markdown(index=False)}

`delta_h=0` reference 只估计 synthetic circular model 相对真实 SGP4 A 的基线。逐方向 subtraction 仅在同一 target/pass 的 exact `direction_deg` 同时被非零高度和 reference 选中时计算；没有强行把重新选择后的不同方向相减。非零 current 主几何 paired availability：{paired_counts}。

## 4. Current-bk 正式主结果（10° full-60）

### Signed delta_h

{signed_risk.to_markdown(index=False)}

### Absolute delta_h

{absolute_risk.to_markdown(index=False)}

### Direction role

{direction.to_markdown(index=False)}

### Target/pass spread

{pass_spread.to_markdown(index=False)}

## 5. b/k gate机制

### Current gate failures

{gate_total.to_markdown(index=False)}

### Current→wide transitions

{transitions.to_markdown(index=False)}

## 6. 正负高度不对称

{asym.to_markdown(index=False)}

## 7. 非零较大高度下的局部低可分性条件

{largest_accepted[["target_sat_id","pass_id","delta_h_km","direction_role","accept_fraction","raw_geo_rmse_hz","unbounded_geometry_post_rmse_hz","direction_sensitivity_hz_per_km","unbounded_geometry_k_hat_hz_per_s"]].to_markdown(index=False) if len(largest_accepted) else "10°有效条件中未观察到非零接受；这不代表安全。"}

## 8. 对研究问题的事实回答

1. 高度差改变了 raw geometry、post-b/k residual 和方向敏感度；变化量及秩相关见第3节。
2. 是否随 `|delta_h|` 稳定变化不能只看 pooled mean；第4节同时给出每个 signed/absolute height 与 target-pass 的最小/中位/最大接受比例。
3. pass 和 direction 的影响由 direction-role 与 target/pass spread 分层呈现；不把三个方向或所有pass混成唯一概率。
4. b/k，尤其 k gate 的作用以 gate failure 和 current→wide release 原因统计，不以单个案例代替总体。
5. 较大非零高度仍有接受时，必须称为特定 target×pass×direction 的局部低可分性条件；0/20 也不称为安全。

本报告不提供统一安全高度，不把 synthetic B 称为真实 Starlink 轨道，也不把描述相关写成高度的普遍因果律。

## 9. 正确性审计

{audit.to_markdown(index=False)}

审计通过：`{int(audit.passed.sum())}/{len(audit)}`。

## 10. 输出

""" + "\n".join(f"- `{p.as_posix()}`" for p in paths.values()) + "\n"
    paths["report"].write_text(text, encoding="utf-8")


def write_report(args: argparse.Namespace, paths: dict[str, Path], data: pd.DataFrame,
                 geometry: pd.DataFrame, altitude: pd.DataFrame, absolute_altitude: pd.DataFrame,
                 target_pass_height: pd.DataFrame, visibility: pd.DataFrame,
                 validity_signed: pd.DataFrame, validity_absolute: pd.DataFrame,
                 relationships: pd.DataFrame, transitions: pd.DataFrame,
                 gate_failures: pd.DataFrame, audit: pd.DataFrame, visibility_threshold: float) -> None:
    if args.preset == "confirmation":
        write_formal_report(args, paths, data, geometry, altitude, absolute_altitude,
                            target_pass_height, visibility, validity_signed, validity_absolute,
                            relationships, transitions, gate_failures, audit, visibility_threshold)
        return
    cur = geometry[(geometry.bk_mode == "current_bk") & geometry.non_target_risk_eligible.astype(bool)]
    vis_counts = data.drop_duplicates("geometry_condition_id")[["physical_visibility_horizon_full60",
        "physical_visibility_existing_threshold_full60"]].sum().to_dict()
    text = f"""# 受控合成轨道高度差风险实验 Smoke Report

## 1. 实验边界

本轮只完成独立脚本与 smoke test，没有运行计划中的 5×4×14×3×20 正式实验。合法 A 使用真实 Starlink TLE；B 是由 A 的 mid-pass 状态构造的同轨道面圆轨道近似，不是真实 Starlink 轨道。正式 verifier 未修改。

统一口径为 `60 s + segment_local + fixed_site_segment_center + single-window`。攻击补偿仍为 `u(t)=F_A(C)-F_B(C)`；`current_bk` 是主口径，`no_bk/wide_bk` 只作对照。`delta_h=0` 仅为 reference，不进入非目标风险统计。

## 2. Smoke 规模

- target：{args.target_ids}
- pass：每 target {args.passes_per_target}
- delta_h_km：{args.delta_h_km}
- 方向：lowest / opposite / high，共3个
- 每几何 realization：{args.realizations}
- verifier mode：{BK_MODES}
- dataset rows：{len(data)}
- geometry-mode rows：{len(geometry)}

## 3. 轨道和方向 sanity

高度通过 `r_B=r_A_reference+delta_h` 构造，角速度通过 `sqrt(mu/r_B^3)` 重算，没有给 Doppler 曲线人工加偏置。每个 target×pass×delta_h 都重新计算8方向局部敏感度；高敏感对照严格沿用最近多过境脚本规则：排除 lowest/opposite 后，从剩余方向取最大值。站点距离固定为 {DISTANCE_KM} km，局部有限差分步长为 {FD_STEPS_KM} km。

## 4. Visibility smoke

现有 pass 搜索 elevation 门限为 `{visibility_threshold:g}°`。本轮没有把 visibility 加入 verifier，也没有自行确定新强制门限；同时输出两套 experiment-validity 诊断：

1. A/B 在 S 和 C 全60秒均高于地平线；
2. A/B 在 S 和 C 全60秒均高于现有 pass 门限 `{visibility_threshold:g}°`。

几何条件可见计数：{vis_counts}。建议正式实验前明确采用哪一套作为预声明物理有效条件；更保守且与现有 pass 口径一致的候选是第二套，但本 smoke 不替研究设计作最终决定。

{visibility.to_markdown(index=False)}

## 5. Current-bk smoke geometry

{cur[["target_sat_id","pass_id","delta_h_km","direction_role","raw_geo_rmse_hz","direction_sensitivity_hz_per_km","unbounded_geometry_k_hat_hz_per_s","unbounded_geometry_post_rmse_hz","accept_fraction","physical_visibility_existing_threshold_full60"]].to_markdown(index=False)}

## 6. Current→wide

{transitions.to_markdown(index=False)}

## 7. 正确性审计

{audit.to_markdown(index=False)}

审计通过：`{int(audit.passed.sum())}/{len(audit)}`。任何 smoke 接受或零接受都不能解释为真实攻击概率或绝对安全。

## 8. 是否具备正式运行条件

脚本已具备生成 5 target×4 same-TLE pass×14 signed height×3 direction×20 realization 的工程能力，且现有 selected-pass 输入可在运行前严格检查实际可用数量。当前唯一需要科研口径确认的是正式物理可见条件：采用地平线以上，还是沿用现有 pass 的 10° 全窗口门限。在确认前不应运行正式规模。

## 9. 输出

""" + "\n".join(f"- `{p.as_posix()}`" for p in paths.values()) + "\n"
    paths["report"].write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, paths: dict[str, Path], data: pd.DataFrame,
               audit: pd.DataFrame, visibility_threshold: float) -> None:
    path = Path("logs/work_log.md")
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    formal = args.preset == "confirmation"
    task_name = "受控轨道高度差风险正式实验" if formal else "受控轨道高度差风险实验 smoke"
    goal = ("运行5 target×4 pass×15高度（含delta_h=0 reference）×3方向×20 realization正式实验。"
            if formal else
            "新建独立受控合成轨道高度差实验，只运行1 target×1 pass×5高度（含delta_h=0 reference）×3方向×2 realization的smoke，不运行正式规模。")
    command = ("python scripts/run_controlled_altitude_difference_risk_experiment.py --preset confirmation"
               if formal else "python scripts/run_controlled_altitude_difference_risk_experiment.py --preset smoke")
    result_note = ("已完成正式5×4×14非零高度×3方向×20 realization；另含delta_h=0 reference。"
                   if formal else "未运行5×4×14×3×20正式实验。")
    next_note = ("正式实验已完成；后续仅依据独立CSV和报告解释结果，不给出统一安全高度。"
                 if formal else
                 f"正式运行前需确认物理可见条件采用全60秒高于地平线，还是沿用现有pass的{visibility_threshold:g}°门限；在确认前停止。")
    entry = f"""

## {now} - {task_name}

### A. 本轮目标

{goal}

### B. 实际操作

- 复用现有synthetic_same_plane_geo、合成B attack_geo桥接、M2_block中心60秒服务段、方向有限差分、calibration、正式single-window verifier和多realization seed。
- 新增B在S/C的elevation与0°/{visibility_threshold:g}°两套visibility diagnostic；未修改final decision。
- current_bk为主，no_bk/wide_bk为机制对照；delta_h=0不进入正式风险统计。

### C. 新增/修改文件

- `scripts/run_controlled_altitude_difference_risk_experiment.py`
""" + "\n".join(f"- `{p.as_posix()}`" for p in paths.values()) + f"""

### D. 运行命令

`python -m py_compile scripts/run_controlled_altitude_difference_risk_experiment.py`

`{command}`

### E. 结果摘要

- dataset rows={len(data)}；审计={int(audit.passed.sum())}/{len(audit)}。
- {result_note}
- 未修改旧正式verifier、配置、dataset或metrics。

### F. 问题与下一步

{next_note}
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def main() -> None:
    args = parse_args()
    setup_args(args)
    paths = output_paths(args.preset)
    check_outputs(paths, args.overwrite)
    selection, _library, orbit_cfg, tle, ranges = load_inputs(args)
    _ = selection
    passes = choose_passes(args, tle)
    protected = [args.tle_file, args.orbit_config, args.parameter_config, args.selected_passes,
                 Path("outputs/datasets/fixed_geometry_multi_realization_dataset.csv"),
                 Path("outputs/datasets/same_pair_multi_pass_realization_dataset.csv")]
    before = {str(p): sha_file(p) for p in protected if p.exists()}
    ts = load.timescale()
    directions, geometries, generator_diffs, center_cancel, visibility_threshold, freq = build_geometries(
        args, passes, orbit_cfg, tle, ranges, ts)
    data = generate_realizations(args, geometries, ranges)
    geometry = add_paired_reference(geometry_summary(data))
    altitude_parts = [summarized_rates(data, ["delta_h_km", "abs_delta_h_km", "bk_mode"], scope)
                      for scope in ["all", "horizon_full60", "existing_threshold_full60"]]
    altitude = pd.concat([x for x in altitude_parts if len(x)], ignore_index=True)
    absolute_parts = [summarized_rates(data, ["abs_delta_h_km", "bk_mode"], scope)
                      for scope in ["all", "horizon_full60", "existing_threshold_full60"]]
    absolute_altitude = pd.concat([x for x in absolute_parts if len(x)], ignore_index=True)
    pass_direction_parts = [summarized_rates(data, ["target_sat_id", "pass_id", "delta_h_km", "direction_role", "bk_mode"], scope)
                            for scope in ["all", "horizon_full60", "existing_threshold_full60"]]
    pass_direction = pd.concat([x for x in pass_direction_parts if len(x)], ignore_index=True)
    target_pass_parts = [summarized_rates(data, ["target_sat_id", "pass_id", "delta_h_km", "bk_mode"], scope)
                         for scope in ["all", "horizon_full60", "existing_threshold_full60"]]
    target_pass_height = pd.concat([x for x in target_pass_parts if len(x)], ignore_index=True)
    visibility = visibility_summary(data)
    validity_signed, validity_absolute, validity_pass = validity_tables(data)
    relationships = relationship_summary(geometry)
    transitions = transition_summary(data[data.non_target_risk_eligible.astype(bool)])
    gate_failures = gate_failure_summary(data)
    after = {str(p): sha_file(p) for p in protected if p.exists()}
    audit = correctness_audit(args, passes, directions, data, generator_diffs, center_cancel, before, after)
    directions.to_csv(paths["directions"], index=False, encoding="utf-8-sig")
    data.to_csv(paths["dataset"], index=False, encoding="utf-8-sig")
    geometry.to_csv(paths["geometry"], index=False, encoding="utf-8-sig")
    altitude.to_csv(paths["altitude"], index=False, encoding="utf-8-sig")
    absolute_altitude.to_csv(paths["absolute_altitude"], index=False, encoding="utf-8-sig")
    pass_direction.to_csv(paths["pass_direction"], index=False, encoding="utf-8-sig")
    target_pass_height.to_csv(paths["target_pass_height"], index=False, encoding="utf-8-sig")
    visibility.to_csv(paths["visibility"], index=False, encoding="utf-8-sig")
    validity_signed.to_csv(paths["validity_signed"], index=False, encoding="utf-8-sig")
    validity_absolute.to_csv(paths["validity_absolute"], index=False, encoding="utf-8-sig")
    validity_pass.to_csv(paths["validity_pass"], index=False, encoding="utf-8-sig")
    relationships.to_csv(paths["relationships"], index=False, encoding="utf-8-sig")
    transitions.to_csv(paths["transitions"], index=False, encoding="utf-8-sig")
    gate_failures.to_csv(paths["gate_failures"], index=False, encoding="utf-8-sig")
    audit.to_csv(paths["audit"], index=False, encoding="utf-8-sig")
    manifest = {"experiment": "controlled_synthetic_altitude_difference_risk", "preset": args.preset,
                "mode": orbit_cfg.get("mode"), "observation_id": orbit_cfg.get("observation_id"),
                "target_ids": args.target_ids, "passes_per_target": args.passes_per_target,
                "delta_h_km": args.delta_h_km, "realizations": args.realizations, "bk_modes": BK_MODES,
                "frequency_hz": freq, "visibility_threshold_existing_pass_deg": visibility_threshold,
                "reference_delta_h_zero_excluded_from_risk": True, "master_seed": args.master_seed,
                "input_sha256": before, "audit_all_passed": bool(audit.passed.all()),
                "formal_large_run_executed": args.preset == "confirmation"}
    paths["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(args, paths, data, geometry, altitude, absolute_altitude, target_pass_height,
                 visibility, validity_signed, validity_absolute, relationships, transitions,
                 gate_failures, audit, visibility_threshold)
    append_log(args, paths, data, audit, visibility_threshold)
    print(f"dataset_rows={len(data)} geometry_mode_rows={len(geometry)}")
    print(f"audit={int(audit.passed.sum())}/{len(audit)} all_passed={bool(audit.passed.all())}")
    print(f"report={paths['report']}")


if __name__ == "__main__":
    main()
