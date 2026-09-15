#!/usr/bin/env python
"""Multi-pass retest for verifier v2 altitude hard-case targets."""

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
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multipass_summary.csv"))
    p.add_argument("--max-targets", type=int, default=20)
    p.add_argument("--num-passes-per-target", type=int, default=4)
    p.add_argument("--num-sims-per-case", type=int, default=20)
    p.add_argument("--threshold-type", choices=["p95", "p99", "all"], default="all")
    p.add_argument("--seed", type=int, default=20260520)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def th_types(v: str) -> list[str]:
    return ["p95", "p99"] if v == "all" else [v]


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


def find_passes(sat, station, ts, base_tw: dict[str, Any], n: int) -> list[tuple[list[Any], dict[str, Any]]]:
    passes = []
    tw = dict(base_tw)
    search_start = base.parse_utc(str(tw["search_start_utc"]))
    attempts = 0
    while len(passes) < n and attempts < n * 8:
        tw["search_start_utc"] = search_start.isoformat().replace("+00:00", "Z")
        result, reason = orbit_builder.find_pass(sat, station, ts, tw)
        if result is None:
            search_start = search_start + timedelta(hours=float(tw.get("search_duration_h", 24)))
        else:
            times, info = result
            passes.append((times, info))
            search_start = base.parse_utc(info["pass_end_utc"]) + timedelta(minutes=20)
        attempts += 1
    return passes


def geo_from_times(sat, station, ts, times, freq: float, step: float) -> pd.DataFrame:
    g = orbit_builder.geo_curve(sat, station, ts, times, freq, step)
    return g.rename(columns={"f_geo_tle_hz": "f_geo_candidate_hz"})


def fit_score(y: np.ndarray, f_geo: np.ndarray, t_rel: np.ndarray) -> tuple[float, float, float]:
    fit = base.fit_bias_and_slope(y, f_geo, t_rel)
    return fit.score_rmse_hz, fit.b_hat_hz, fit.k_hat_hz_s


def eval_pass(target_name, target_norad, pass_id, pass_info, geo, sat, station, ts, freq, ranges, deltas, args, rng, threshold_types):
    f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
    t_rel = geo["t_rel_s"].to_numpy(float)
    legit_rows = []
    legit_scores = []
    for i in range(1, args.num_sims_per_case + 1):
        err = base.sample_error_params(ranges, rng)
        obs = base.build_legitimate_observation(f"legit_{pass_id}_{i:03d}", target_name, target_norad, geo, err, rng, i, args.seed)
        score, b, k = fit_score(obs.y_obs_hz, f_geo_a, t_rel)
        legit_scores.append((score, b, k))
    scores = np.array([x[0] for x in legit_scores])
    k_vals = np.array([x[2] for x in legit_scores])
    thresholds = {"p95": float(np.quantile(scores, 0.95)), "p99": float(np.quantile(scores, 0.99))}
    k_min, k_max = float(np.quantile(k_vals, 0.01)), float(np.quantile(k_vals, 0.99))
    rows = []
    for th in threshold_types:
        for score, b, k in legit_scores:
            rows.append(
                dict(
                    target_sat_id=target_norad,
                    target_name=target_name,
                    pass_id=pass_id,
                    pass_start_utc=pass_info["pass_start_utc"],
                    pass_end_utc=pass_info["pass_end_utc"],
                    attack_source_sat_id="",
                    attack_source_name="",
                    delta_h_km=np.nan,
                    sample_type="legit",
                    threshold_type=th,
                    score=score,
                    threshold=thresholds[th],
                    normalized_score=score / thresholds[th],
                    b_hat=b,
                    k_hat=k,
                    pass_k_min_p01=k_min,
                    pass_k_max_p99=k_max,
                    accepted_score_only=score <= thresholds[th],
                    accepted_per_pass_k_p01_p99=(score <= thresholds[th]) and (k_min <= k <= k_max),
                    num_points=len(t_rel),
                    max_elevation_deg=pass_info["max_elevation_deg"],
                    pass_duration_s=pass_info["duration_s"],
                )
            )
    times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
    for dh in deltas:
        f_geo_b = base.synthetic_same_plane_geo(sat, station, ts, times, freq, altitude_offset_km=float(dh), phase_offset_s=0.0)
        spec = dict(attack_type="same_plane_altitude_offset_multipass", attack_variant=f"delta_h_{dh:+g}km", altitude_offset_km=float(dh), phase_offset_s=0.0, inclination_offset_deg=0.0, raan_offset_deg=0.0)
        for i in range(1, args.num_sims_per_case + 1):
            err = base.sample_error_params(ranges, rng)
            obs = base.build_attack_observation(f"attack_{pass_id}_{dh}_{i:03d}", target_name, target_norad, geo, f_geo_b, spec, err, rng, i, args.seed)
            score, b, k = fit_score(obs.y_obs_hz, f_geo_a, t_rel)
            for th in threshold_types:
                rows.append(
                    dict(
                        target_sat_id=target_norad,
                        target_name=target_name,
                        pass_id=pass_id,
                        pass_start_utc=pass_info["pass_start_utc"],
                        pass_end_utc=pass_info["pass_end_utc"],
                        attack_source_sat_id="synthetic_same_plane_orbit",
                        attack_source_name=spec["attack_variant"],
                        delta_h_km=float(dh),
                        sample_type="attack",
                        threshold_type=th,
                        score=score,
                        threshold=thresholds[th],
                        normalized_score=score / thresholds[th],
                        b_hat=b,
                        k_hat=k,
                        pass_k_min_p01=k_min,
                        pass_k_max_p99=k_max,
                        accepted_score_only=score <= thresholds[th],
                        accepted_per_pass_k_p01_p99=(score <= thresholds[th]) and (k_min <= k <= k_max),
                        num_points=len(t_rel),
                        max_elevation_deg=pass_info["max_elevation_deg"],
                        pass_duration_s=pass_info["duration_s"],
                    )
                )
    return rows


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    att = df[df["sample_type"] == "attack"]
    for key, g in att.groupby(["target_sat_id", "target_name", "delta_h_km", "threshold_type"]):
        target_sat_id, target_name, dh, th = key
        rows.append(
            dict(
                target_sat_id=target_sat_id,
                target_name=target_name,
                delta_h_km=dh,
                threshold_type=th,
                num_passes=g["pass_id"].nunique(),
                total_attack_sequences=len(g),
                score_only_accepts=int(g["accepted_score_only"].sum()),
                per_pass_k_gate_accepts=int(g["accepted_per_pass_k_p01_p99"].sum()),
                score_only_accept_rate=float(g["accepted_score_only"].mean()),
                per_pass_k_gate_accept_rate=float(g["accepted_per_pass_k_p01_p99"].mean()),
                median_normalized_score=float(g["normalized_score"].median()),
                min_normalized_score=float(g["normalized_score"].min()),
                max_normalized_score=float(g["normalized_score"].max()),
                median_k_hat=float(g["k_hat"].median()),
                p05_k_hat=float(g["k_hat"].quantile(0.05)),
                p95_k_hat=float(g["k_hat"].quantile(0.95)),
            )
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    if (args.sequence_output.exists() or args.summary_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    if not args.selected_pairs.exists():
        fail("selected hard case pairs missing; run analyze_verifier_v2_hard_cases.py first")
    selected = pd.read_csv(args.selected_pairs)
    targets = selected[["target_sat_id", "target_name"]].drop_duplicates().head(args.max_targets)
    deltas = sorted(selected["delta_h_km"].drop_duplicates().astype(float))
    selection, library, orbit_cfg, ranges, tle, ts = load_common(args)
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    rng = np.random.default_rng(args.seed)
    rows = []
    for _, t in targets.iterrows():
        tid = str(t["target_sat_id"])
        sat = tle[tid]["sat"]
        passes = find_passes(sat, station, ts, orbit_cfg["time_window"], args.num_passes_per_target)
        for i, (times, info) in enumerate(passes, 1):
            geo = geo_from_times(sat, station, ts, times, freq, float(info["step_s"]))
            rows.extend(eval_pass(str(t["target_name"]), tid, f"{tid}_pass_{i:02d}", info, geo, sat, station, ts, freq, ranges, deltas, args, rng, th_types(args.threshold_type)))
    df = pd.DataFrame(rows)
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.sequence_output, index=False)
    summ = summarize(df)
    summ.to_csv(args.summary_output, index=False)
    print(f"wrote {args.sequence_output} rows={len(df)}")
    print(f"wrote {args.summary_output} rows={len(summ)}")
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
