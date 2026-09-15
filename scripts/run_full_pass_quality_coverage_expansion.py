#!/usr/bin/env python
"""Expand hard-case full-pass coverage with medium/high elevation passes."""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selected-pairs", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_selected_pairs.csv"))
    p.add_argument("--existing-sequence-eval", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--output", type=Path, default=Path("outputs/metrics/full_pass_quality_expansion_sequence_eval.csv"))
    p.add_argument("--max-targets", type=int, default=20)
    p.add_argument("--num-medium-passes", type=int, default=3)
    p.add_argument("--num-high-passes", type=int, default=2)
    p.add_argument("--num-legit-sims-per-pass", type=int, default=None)
    p.add_argument("--num-sims-per-case", type=int, default=5)
    p.add_argument("--threshold-type", choices=["p95", "p99", "all"], default="all")
    p.add_argument("--seed", type=int, default=20260520)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def th_types(v: str) -> list[str]:
    return ["p95", "p99"] if v == "all" else [v]


def elevation_bin(v: float) -> str:
    if v < 20:
        return "low"
    if v < 40:
        return "medium"
    return "high"


def load_common(args):
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=20,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    return selection, library, orbit_cfg, ranges, tle, ts


def find_candidate_passes(sat, station, ts, base_tw: dict[str, Any], desired_medium: int, desired_high: int, existing_starts: set[str]):
    medium = []
    high = []
    seen = set(existing_starts)
    tw = dict(base_tw)
    search_start = base.parse_utc(str(tw["search_start_utc"]))
    attempts = 0
    while (len(medium) < desired_medium or len(high) < desired_high) and attempts < 220:
        tw["search_start_utc"] = search_start.isoformat().replace("+00:00", "Z")
        result, _reason = orbit_builder.find_pass(sat, station, ts, tw)
        if result is None:
            search_start = search_start + timedelta(hours=float(tw.get("search_duration_h", 24)))
            attempts += 1
            continue
        times, info = result
        start = str(info["pass_start_utc"])
        if start not in seen:
            seen.add(start)
            b = elevation_bin(float(info["max_elevation_deg"]))
            if b == "medium" and len(medium) < desired_medium:
                medium.append((times, info))
            elif b == "high" and len(high) < desired_high:
                high.append((times, info))
        search_start = base.parse_utc(info["pass_end_utc"]) + timedelta(minutes=20)
        attempts += 1
    return medium + high


def geo_from_times(sat, station, ts, times, freq: float, step: float) -> pd.DataFrame:
    g = orbit_builder.geo_curve(sat, station, ts, times, freq, step)
    return g.rename(columns={"f_geo_tle_hz": "f_geo_candidate_hz"})


def fit_score(y: np.ndarray, f_geo: np.ndarray, t_rel: np.ndarray):
    fit = base.fit_bias_and_slope(y, f_geo, t_rel)
    return fit.score_rmse_hz, fit.b_hat_hz, fit.k_hat_hz_s


def eval_pass(target_name, tid, pass_id, info, geo, sat, station, ts, freq, ranges, deltas, args, rng):
    f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
    t_rel = geo["t_rel_s"].to_numpy(float)
    num_legit = int(args.num_legit_sims_per_pass or args.num_sims_per_case)
    legit_scores = []
    for i in range(1, num_legit + 1):
        err = base.sample_error_params(ranges, rng)
        obs = base.build_legitimate_observation(f"legit_{pass_id}_{i:03d}", target_name, tid, geo, err, rng, i, args.seed)
        legit_scores.append(fit_score(obs.y_obs_hz, f_geo_a, t_rel))
    scores = np.array([x[0] for x in legit_scores])
    kvals = np.array([x[2] for x in legit_scores])
    thresholds = {"p95": float(np.quantile(scores, 0.95)), "p99": float(np.quantile(scores, 0.99))}
    kmin, kmax = float(np.quantile(kvals, 0.01)), float(np.quantile(kvals, 0.99))
    kmin05, kmax95 = float(np.quantile(kvals, 0.05)), float(np.quantile(kvals, 0.95))
    rows = []
    for th in th_types(args.threshold_type):
        for score, b, k in legit_scores:
            rows.append(base_row(tid, target_name, pass_id, info, "", "", np.nan, "legit", th, score, thresholds[th], b, k, kmin, kmax, kmin05, kmax95, num_legit, len(t_rel)))
    times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
    for dh in deltas:
        f_geo_b = base.synthetic_same_plane_geo(sat, station, ts, times, freq, altitude_offset_km=float(dh), phase_offset_s=0.0)
        spec = dict(attack_type="same_plane_altitude_offset_quality_expansion", attack_variant=f"delta_h_{dh:+g}km", altitude_offset_km=float(dh), phase_offset_s=0.0, inclination_offset_deg=0.0, raan_offset_deg=0.0)
        for i in range(1, args.num_sims_per_case + 1):
            err = base.sample_error_params(ranges, rng)
            obs = base.build_attack_observation(f"attack_{pass_id}_{dh}_{i:03d}", target_name, tid, geo, f_geo_b, spec, err, rng, i, args.seed)
            score, b, k = fit_score(obs.y_obs_hz, f_geo_a, t_rel)
            for th in th_types(args.threshold_type):
                rows.append(base_row(tid, target_name, pass_id, info, "synthetic_same_plane_orbit", spec["attack_variant"], float(dh), "attack", th, score, thresholds[th], b, k, kmin, kmax, kmin05, kmax95, num_legit, len(t_rel)))
    return rows


def base_row(tid, target_name, pass_id, info, source_id, source_name, dh, sample_type, th, score, threshold, b, k, kmin, kmax, kmin05, kmax95, legit_count, npts):
    accepted_score = score <= threshold
    accepted_k = accepted_score and (kmin <= k <= kmax)
    return {
        "target_sat_id": tid,
        "target_name": target_name,
        "pass_id": pass_id,
        "pass_start_utc": info["pass_start_utc"],
        "pass_end_utc": info["pass_end_utc"],
        "pass_duration_s": float(info["duration_s"]),
        "max_elevation_deg": float(info["max_elevation_deg"]),
        "elevation_bin": elevation_bin(float(info["max_elevation_deg"])),
        "sample_type": sample_type,
        "attack_source_sat_id": source_id,
        "attack_source_name": source_name,
        "delta_h_km": dh,
        "threshold_type": th,
        "score": float(score),
        "threshold": float(threshold),
        "normalized_score": float(score / threshold),
        "b_hat": float(b),
        "k_hat": float(k),
        "pass_k_min_p01": float(kmin),
        "pass_k_max_p99": float(kmax),
        "pass_k_min_p05": float(kmin05),
        "pass_k_max_p95": float(kmax95),
        "k_range_width": float(kmax - kmin),
        "legit_calibration_count": int(legit_count),
        "score_threshold_source": "same_pass_legitimate_samples",
        "k_range_source": "same_pass_legitimate_samples",
        "accepted_score_only": bool(accepted_score),
        "accepted_per_pass_k_p01_p99": bool(accepted_k),
        "num_points": int(npts),
    }


def main() -> None:
    args = parse_args()
    if args.output.exists() and not args.overwrite:
        fail("output exists; add --overwrite")
    for p in [args.selected_pairs, args.existing_sequence_eval]:
        if not p.exists():
            fail(f"missing input: {p}")
    selected = pd.read_csv(args.selected_pairs)
    targets = selected[["target_sat_id", "target_name"]].drop_duplicates().head(args.max_targets)
    deltas = sorted(selected["delta_h_km"].drop_duplicates().astype(float))
    existing = pd.read_csv(args.existing_sequence_eval)
    selection, library, orbit_cfg, ranges, tle, ts = load_common(args)
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    rng = np.random.default_rng(args.seed)
    rows = []
    for _, target in targets.iterrows():
        tid = str(target["target_sat_id"])
        name = str(target["target_name"])
        existing_starts = set(existing[existing["target_sat_id"].astype(str) == tid]["pass_start_utc"].astype(str))
        sat = tle[tid]["sat"]
        passes = find_candidate_passes(sat, station, ts, orbit_cfg["time_window"], args.num_medium_passes, args.num_high_passes, existing_starts)
        for idx, (times, info) in enumerate(passes, 1):
            pass_id = f"{tid}_exp_{idx:02d}_{elevation_bin(float(info['max_elevation_deg']))}"
            geo = geo_from_times(sat, station, ts, times, freq, float(info["step_s"]))
            rows.extend(eval_pass(name, tid, pass_id, info, geo, sat, station, ts, freq, ranges, deltas, args, rng))
    out = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"wrote {args.output} rows={len(out)}")
    if not out.empty:
        print(out[["target_sat_id", "pass_id", "max_elevation_deg", "elevation_bin"]].drop_duplicates().to_string(index=False))
        print(out.groupby(["threshold_type", "elevation_bin", "sample_type"]).size().to_string())


if __name__ == "__main__":
    main()
