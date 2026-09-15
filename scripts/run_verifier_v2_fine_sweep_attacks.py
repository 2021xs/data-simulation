#!/usr/bin/env python
"""Run verifier v2 fine-grained same-plane attack sweeps.

This script reuses the existing claimed-identity verifier attack builder:
synthetic_same_plane_geo -> build_attack_observation -> verify_claimed_identity.
It writes per-sequence evaluation rows for altitude and phase sweeps.
"""

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


DEFAULT_ALTITUDE_DELTAS_KM = [-10, -7.5, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7.5, 10]
DEFAULT_PHASE_OFFSETS_S = [-300, -120, -60, -30, -10, -5, 5, 10, 30, 60, 120, 300]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    parser.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    parser.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    parser.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    parser.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    parser.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    parser.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    parser.add_argument("--altitude-output", type=Path, default=Path("outputs/metrics/verifier_v2_altitude_fine_sweep_sequence_eval.csv"))
    parser.add_argument("--phase-output", type=Path, default=Path("outputs/metrics/verifier_v2_phase_fine_sweep_sequence_eval.csv"))
    parser.add_argument("--max-targets", type=int, default=20)
    parser.add_argument("--num-sims-per-case", type=int, default=5)
    parser.add_argument("--threshold-type", choices=["p95", "p99", "all"], default="all")
    parser.add_argument("--altitude-deltas-km", nargs="+", type=float, default=DEFAULT_ALTITUDE_DELTAS_KM)
    parser.add_argument("--phase-offsets", nargs="+", type=float, default=DEFAULT_PHASE_OFFSETS_S)
    parser.add_argument("--seed", type=int, default=20260519)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def load_base_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, list[float]], dict[str, dict[str, Any]]]:
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
    tle_entries = base.parse_tle(args.tle_file, ts)
    return selection.head(args.max_targets).copy(), library, orbit_cfg, ranges, tle_entries


def threshold_types(arg: str) -> list[str]:
    return ["p95", "p99"] if arg == "all" else [arg]


def load_threshold_map(path: Path) -> dict[str, tuple[float, float]]:
    if not path.exists():
        fail(f"thresholds not found: {path}")
    thresholds = pd.read_csv(path)
    base.require_columns = getattr(base, "require_columns", None)
    needed = ["target_norad", "threshold_95_hz", "threshold_99_hz"]
    missing = [c for c in needed if c not in thresholds.columns]
    if missing:
        fail("thresholds missing columns: " + ", ".join(missing))
    return {
        str(row.target_norad): (float(row.threshold_95_hz), float(row.threshold_99_hz))
        for row in thresholds.itertuples(index=False)
    }


def load_k_ranges(legit_results_path: Path, parameter_config_path: Path) -> tuple[pd.DataFrame, tuple[float, float]]:
    if not legit_results_path.exists():
        fail(f"legit score results not found: {legit_results_path}")
    legit = pd.read_csv(legit_results_path)
    missing = [c for c in ["target_norad", "k_hat_hz_s"] if c not in legit.columns]
    if missing:
        fail("legit score results missing columns: " + ", ".join(missing))
    legit["target_sat_id"] = legit["target_norad"].astype(str)
    ranges = legit.groupby("target_sat_id").agg(
        target_k_min_p01=("k_hat_hz_s", lambda s: float(s.quantile(0.01))),
        target_k_max_p99=("k_hat_hz_s", lambda s: float(s.quantile(0.99))),
        target_k_min_p05=("k_hat_hz_s", lambda s: float(s.quantile(0.05))),
        target_k_max_p95=("k_hat_hz_s", lambda s: float(s.quantile(0.95))),
    ).reset_index()
    cfg = base.read_yaml(parameter_config_path)
    k_range = tuple(float(v) for v in cfg["parameters"]["k_hz_per_s"]["main_range"])
    return ranges, k_range  # type: ignore[return-value]


def reason(score_ok: bool, global_ok: bool, p01_ok: bool, p05_ok: bool) -> str:
    if p01_ok:
        return "accepted_by_score_and_per_target_k_p01_p99"
    reasons: list[str] = []
    if not score_ok:
        reasons.append("score_above_threshold")
    if score_ok and not global_ok:
        reasons.append("k_hat_out_of_global_range")
    if score_ok and not p01_ok:
        reasons.append("k_hat_out_of_per_target_k_p01_p99")
    if score_ok and not p05_ok:
        reasons.append("k_hat_out_of_per_target_k_p05_p95")
    return ";".join(reasons) if reasons else "rejected"


def eval_rows_for_sweep(
    *,
    selection: pd.DataFrame,
    library: pd.DataFrame,
    orbit_cfg: dict[str, Any],
    ranges: dict[str, list[float]],
    tle_entries: dict[str, dict[str, Any]],
    threshold_map: dict[str, tuple[float, float]],
    k_ranges: pd.DataFrame,
    global_k_range: tuple[float, float],
    sweep_type: str,
    values: list[float],
    threshold_type_list: list[str],
    num_sims_per_case: int,
    seed: int,
) -> pd.DataFrame:
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
    k_range_map = k_ranges.set_index("target_sat_id").to_dict(orient="index")
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    seq_counter = 1
    attack_type = "same_plane_altitude_offset_fine" if sweep_type == "altitude" else "same_plane_phase_offset_fine"
    param_name = "delta_h_km" if sweep_type == "altitude" else "phase_offset_s"

    for _, target in selection.iterrows():
        target_norad = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        if target_norad not in tle_entries:
            fail(f"target NORAD not found in TLE: {target_norad}")
        if target_norad not in threshold_map:
            fail(f"target NORAD not found in thresholds: {target_norad}")
        if target_norad not in k_range_map:
            fail(f"target NORAD not found in legit k ranges: {target_norad}")
        geo = base.target_geo_from_library(library, target_norad)
        times = [base.parse_utc(value) for value in geo["t_abs_utc"].astype(str)]
        f_geo_claimed = geo["f_geo_candidate_hz"].to_numpy(float)
        threshold_95, threshold_99 = threshold_map[target_norad]
        sat = tle_entries[target_norad]["sat"]
        target_k = k_range_map[target_norad]

        for raw_value in values:
            value = float(raw_value)
            if value == 0.0:
                continue
            altitude_offset_km = value if sweep_type == "altitude" else 0.0
            phase_offset_s = value if sweep_type == "phase" else 0.0
            attack_variant = {
                "attack_type": attack_type,
                "attack_variant": f"delta_h_{value:+g}km" if sweep_type == "altitude" else f"delta_t_{value:+g}s",
                "altitude_offset_km": float(altitude_offset_km),
                "phase_offset_s": float(phase_offset_s),
                "inclination_offset_deg": 0.0,
                "raan_offset_deg": 0.0,
            }
            f_geo_attack = base.synthetic_same_plane_geo(
                sat=sat,
                station=station,
                ts=ts,
                times=times,
                simulation_center_freq_hz=simulation_center_freq_hz,
                altitude_offset_km=altitude_offset_km,
                phase_offset_s=phase_offset_s,
            )
            for sample_id in range(1, num_sims_per_case + 1):
                error_model = base.sample_error_params(ranges, rng)
                sequence_id = f"{'alt' if sweep_type == 'altitude' else 'phase'}_fine_{seq_counter:06d}"
                seq_counter += 1
                observation = base.build_attack_observation(
                    sequence_id=sequence_id,
                    claimed_target_name=target_name,
                    claimed_target_norad=target_norad,
                    pass_geo=geo,
                    f_geo_attack_b_hz=f_geo_attack,
                    attack_variant=attack_variant,
                    error_model=error_model,
                    rng=rng,
                    sample_id=sample_id,
                    random_seed=seed,
                )
                verification = base.verify_claimed_identity(
                    observation_sequence=observation,
                    f_geo_claimed_hz=f_geo_claimed,
                    threshold_95_hz=threshold_95,
                    threshold_99_hz=threshold_99,
                )
                scores = {
                    "p95": (verification.score_A_rmse_hz, threshold_95),
                    "p99": (verification.score_A_rmse_hz, threshold_99),
                }
                global_ok_base = global_k_range[0] <= verification.k_hat_hz_s <= global_k_range[1]
                p01_ok_base = target_k["target_k_min_p01"] <= verification.k_hat_hz_s <= target_k["target_k_max_p99"]
                p05_ok_base = target_k["target_k_min_p05"] <= verification.k_hat_hz_s <= target_k["target_k_max_p95"]
                for threshold_type in threshold_type_list:
                    score, threshold = scores[threshold_type]
                    score_ok = bool(score <= threshold)
                    global_ok = bool(score_ok and global_ok_base)
                    p01_ok = bool(score_ok and p01_ok_base)
                    p05_ok = bool(score_ok and p05_ok_base)
                    row = {
                        "sequence_id": sequence_id,
                        "target_sat_id": target_norad,
                        "target_name": target_name,
                        "attack_source_sat_id": "synthetic_same_plane_orbit",
                        "attack_source_name": attack_variant["attack_variant"],
                        "attack_type": attack_type,
                        param_name: value,
                        "attack_param_name": param_name,
                        "attack_param_value": value,
                        "threshold_type": threshold_type,
                        "score": float(score),
                        "threshold": float(threshold),
                        "normalized_score": float(score / threshold),
                        "b_hat": float(verification.b_hat_hz),
                        "k_hat": float(verification.k_hat_hz_s),
                        "target_k_min_p01": float(target_k["target_k_min_p01"]),
                        "target_k_max_p99": float(target_k["target_k_max_p99"]),
                        "target_k_min_p05": float(target_k["target_k_min_p05"]),
                        "target_k_max_p95": float(target_k["target_k_max_p95"]),
                        "accepted_score_only": score_ok,
                        "accepted_global_k_gate": global_ok,
                        "accepted_per_target_k_p01_p99": p01_ok,
                        "accepted_per_target_k_p05_p95": p05_ok,
                        "rejection_reason": reason(score_ok, global_ok, p01_ok, p05_ok),
                        "num_points": int(len(observation.t_abs_utc)),
                        "window_start_utc": str(observation.t_abs_utc[0]),
                        "window_end_utc": str(observation.t_abs_utc[-1]),
                        "sample_id": int(sample_id),
                        "random_seed": int(seed),
                        "b_model_term_hz": float(observation.b_true_hz),
                        "k_model_term_hz_s": float(observation.k_true_hz_s),
                        "sigma_model_term_hz": float(observation.sigma_true_hz),
                    }
                    rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    check_outputs([args.altitude_output, args.phase_output], args.overwrite)
    args.altitude_output.parent.mkdir(parents=True, exist_ok=True)
    args.phase_output.parent.mkdir(parents=True, exist_ok=True)
    selection, library, orbit_cfg, ranges, tle_entries = load_base_inputs(args)
    threshold_map = load_threshold_map(args.thresholds)
    k_ranges, global_k_range = load_k_ranges(args.legit_results, args.parameter_config)
    th_types = threshold_types(args.threshold_type)

    altitude = eval_rows_for_sweep(
        selection=selection,
        library=library,
        orbit_cfg=orbit_cfg,
        ranges=ranges,
        tle_entries=tle_entries,
        threshold_map=threshold_map,
        k_ranges=k_ranges,
        global_k_range=global_k_range,
        sweep_type="altitude",
        values=[float(v) for v in args.altitude_deltas_km],
        threshold_type_list=th_types,
        num_sims_per_case=args.num_sims_per_case,
        seed=args.seed,
    )
    phase = eval_rows_for_sweep(
        selection=selection,
        library=library,
        orbit_cfg=orbit_cfg,
        ranges=ranges,
        tle_entries=tle_entries,
        threshold_map=threshold_map,
        k_ranges=k_ranges,
        global_k_range=global_k_range,
        sweep_type="phase",
        values=[float(v) for v in args.phase_offsets],
        threshold_type_list=th_types,
        num_sims_per_case=args.num_sims_per_case,
        seed=args.seed + 1,
    )
    altitude.to_csv(args.altitude_output, index=False)
    phase.to_csv(args.phase_output, index=False)
    print(f"wrote {args.altitude_output} rows={len(altitude)}")
    print(f"wrote {args.phase_output} rows={len(phase)}")
    for name, df in [("altitude", altitude), ("phase", phase)]:
        for th in sorted(df["threshold_type"].unique()):
            sub = df[df["threshold_type"] == th]
            print(
                f"{name} {th}: sequences={sub['sequence_id'].nunique()} "
                f"score_only={int(sub['accepted_score_only'].sum())} "
                f"per_target_k_p01_p99={int(sub['accepted_per_target_k_p01_p99'].sum())}"
            )


if __name__ == "__main__":
    main()
