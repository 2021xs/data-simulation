#!/usr/bin/env python
"""Run pass-quality-aware constrained same-plane attacker search."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_full_pass_quality_coverage_expansion as quality  # noqa: E402


DEFAULT_ALTITUDE_DELTAS_KM = [-5, -4, -3, -2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2, 3, 4, 5]
DEFAULT_PHASE_OFFSETS_S = [-120, -60, -30, -10, 0, 10, 30, 60, 120]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selected-pairs", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_selected_pairs.csv"))
    p.add_argument("--existing-sequence-eval", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--output", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_search_sequence_eval.csv"))
    p.add_argument("--max-targets", type=int, default=20)
    p.add_argument("--max-passes", type=int, default=None)
    p.add_argument("--num-medium-passes", type=int, default=3)
    p.add_argument("--num-high-passes", type=int, default=2)
    p.add_argument("--num-legit-sims-per-pass", type=int, default=50)
    p.add_argument("--num-sims-per-case", type=int, default=5)
    p.add_argument("--threshold-type", choices=["p95", "p99", "all"], default="all")
    p.add_argument("--altitude-deltas-km", nargs="+", type=float, default=DEFAULT_ALTITUDE_DELTAS_KM)
    p.add_argument("--phase-offsets-s", nargs="+", type=float, default=DEFAULT_PHASE_OFFSETS_S)
    p.add_argument("--seed", type=int, default=20260520)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def threshold_types(v: str) -> list[str]:
    return ["p95", "p99"] if v == "all" else [v]


def calibrate_pass(target_name: str, tid: str, pass_id: str, geo: pd.DataFrame, ranges: dict[str, list[float]], args: argparse.Namespace, rng: np.random.Generator) -> dict[str, Any]:
    f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
    t_rel = geo["t_rel_s"].to_numpy(float)
    fits = []
    for i in range(1, args.num_legit_sims_per_pass + 1):
        err = base.sample_error_params(ranges, rng)
        obs = base.build_legitimate_observation(f"legit_cal_{pass_id}_{i:03d}", target_name, tid, geo, err, rng, i, args.seed)
        fits.append(quality.fit_score(obs.y_obs_hz, f_geo_a, t_rel))
    scores = np.array([x[0] for x in fits], dtype=float)
    kvals = np.array([x[2] for x in fits], dtype=float)
    return {
        "thresholds": {"p95": float(np.quantile(scores, 0.95)), "p99": float(np.quantile(scores, 0.99))},
        "pass_k_min_p01": float(np.quantile(kvals, 0.01)),
        "pass_k_max_p99": float(np.quantile(kvals, 0.99)),
        "pass_k_min_p05": float(np.quantile(kvals, 0.05)),
        "pass_k_max_p95": float(np.quantile(kvals, 0.95)),
        "legit_calibration_count": int(args.num_legit_sims_per_pass),
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
    existing = pd.read_csv(args.existing_sequence_eval)
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=20,
    )
    _selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    th_types = threshold_types(args.threshold_type)
    rng = np.random.default_rng(args.seed)
    rows: list[dict[str, Any]] = []
    seq_counter = 1

    for _, target in targets.iterrows():
        tid = str(target["target_sat_id"])
        target_name = str(target["target_name"])
        sat = tle[tid]["sat"]
        existing_starts = set(existing[existing["target_sat_id"].astype(str) == tid]["pass_start_utc"].astype(str))
        passes = quality.find_candidate_passes(
            sat,
            station,
            ts,
            orbit_cfg["time_window"],
            args.num_medium_passes,
            args.num_high_passes,
            existing_starts,
        )
        high_quality = [(times, info) for times, info in passes if float(info["max_elevation_deg"]) >= 20.0]
        if args.max_passes is not None:
            high_quality = high_quality[: args.max_passes]
        for pass_idx, (times, info) in enumerate(high_quality, 1):
            pass_id = f"{tid}_attacker_{pass_idx:02d}_{quality.elevation_bin(float(info['max_elevation_deg']))}"
            geo = quality.geo_from_times(sat, station, ts, times, freq, float(info["step_s"]))
            f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
            t_rel = geo["t_rel_s"].to_numpy(float)
            cal = calibrate_pass(target_name, tid, pass_id, geo, ranges, args, rng)
            pass_times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
            for dh in [float(v) for v in args.altitude_deltas_km if float(v) != 0.0]:
                for phase_s in [float(v) for v in args.phase_offsets_s]:
                    f_geo_b = base.synthetic_same_plane_geo(
                        sat=sat,
                        station=station,
                        ts=ts,
                        times=pass_times,
                        simulation_center_freq_hz=freq,
                        altitude_offset_km=dh,
                        phase_offset_s=phase_s,
                    )
                    attack_name = f"delta_h_{dh:+g}km_phase_{phase_s:+g}s"
                    attack_spec = {
                        "attack_type": "pass_quality_aware_same_plane_perturbation",
                        "attack_variant": attack_name,
                        "altitude_offset_km": dh,
                        "phase_offset_s": phase_s,
                        "inclination_offset_deg": 0.0,
                        "raan_offset_deg": 0.0,
                    }
                    for sample_id in range(1, args.num_sims_per_case + 1):
                        err = base.sample_error_params(ranges, rng)
                        sequence_id = f"pqa_{seq_counter:07d}"
                        seq_counter += 1
                        obs = base.build_attack_observation(
                            sequence_id,
                            target_name,
                            tid,
                            geo,
                            f_geo_b,
                            attack_spec,
                            err,
                            rng,
                            sample_id,
                            args.seed,
                        )
                        score, b_hat, k_hat = quality.fit_score(obs.y_obs_hz, f_geo_a, t_rel)
                        for th in th_types:
                            threshold = float(cal["thresholds"][th])
                            score_ok = bool(score <= threshold)
                            k_ok = bool(cal["pass_k_min_p01"] <= k_hat <= cal["pass_k_max_p99"])
                            accepted = bool(score_ok and k_ok and float(info["max_elevation_deg"]) >= 20.0)
                            notes = []
                            if not score_ok:
                                notes.append("score_above_threshold")
                            if score_ok and not k_ok:
                                notes.append("k_hat_out_of_per_pass_range")
                            if accepted:
                                notes.append("accepted_v3_single_pass")
                            rows.append(
                                {
                                    "target_sat_id": tid,
                                    "target_name": target_name,
                                    "pass_id": pass_id,
                                    "pass_start_utc": info["pass_start_utc"],
                                    "pass_end_utc": info["pass_end_utc"],
                                    "max_elevation_deg": float(info["max_elevation_deg"]),
                                    "attack_source_sat_id": "synthetic_same_plane_orbit",
                                    "attack_source_name": attack_name,
                                    "delta_h_km": dh,
                                    "phase_offset_s": phase_s,
                                    "threshold_type": th,
                                    "score": float(score),
                                    "threshold": threshold,
                                    "normalized_score": float(score / threshold),
                                    "b_hat": float(b_hat),
                                    "k_hat": float(k_hat),
                                    "pass_k_min_p01": float(cal["pass_k_min_p01"]),
                                    "pass_k_max_p99": float(cal["pass_k_max_p99"]),
                                    "pass_k_min_p05": float(cal["pass_k_min_p05"]),
                                    "pass_k_max_p95": float(cal["pass_k_max_p95"]),
                                    "k_range_width": float(cal["pass_k_max_p99"] - cal["pass_k_min_p01"]),
                                    "legit_calibration_count": int(cal["legit_calibration_count"]),
                                    "accepted_score_only": score_ok,
                                    "accepted_per_pass_k_p01_p99": bool(score_ok and k_ok),
                                    "accepted_v3_single_pass": accepted,
                                    "num_points": int(len(obs.t_abs_utc)),
                                    "sample_id": int(sample_id),
                                    "notes": ";".join(notes) if notes else "rejected_by_v3_single_pass",
                                }
                            )
    out = pd.DataFrame(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"wrote {args.output} rows={len(out)}")
    if not out.empty:
        print(out.groupby(["threshold_type"])[["accepted_score_only", "accepted_per_pass_k_p01_p99", "accepted_v3_single_pass"]].sum().to_string())
        print(out[["target_sat_id", "pass_id", "max_elevation_deg"]].drop_duplicates().to_string(index=False))


if __name__ == "__main__":
    main()
