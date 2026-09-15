#!/usr/bin/env python
"""Search-grid active compensation first pass for single and two receivers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_multi_receiver_active_compensation_first_pass as multi  # noqa: E402


RESIDUAL_MODES = ["clean", "empirical"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    p.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    p.add_argument("--single-eval-output", type=Path, default=Path("outputs/metrics/best_C_single_station_eval.csv"))
    p.add_argument("--single-summary-output", type=Path, default=Path("outputs/metrics/best_C_single_station_summary.csv"))
    p.add_argument("--single-dataset-output", type=Path, default=Path("outputs/datasets/best_C_single_station_dataset.csv"))
    p.add_argument("--single-exclude-eval-output", type=Path, default=Path("outputs/metrics/best_C_single_station_exclude_eval.csv"))
    p.add_argument("--single-exclude-summary-output", type=Path, default=Path("outputs/metrics/best_C_single_station_exclude_summary.csv"))
    p.add_argument("--single-exclude-dataset-output", type=Path, default=Path("outputs/datasets/best_C_single_station_exclude_dataset.csv"))
    p.add_argument("--multi-station-output", type=Path, default=Path("outputs/metrics/best_C_multi_receiver_station_eval.csv"))
    p.add_argument("--multi-pairwise-output", type=Path, default=Path("outputs/metrics/best_C_multi_receiver_pairwise_consistency.csv"))
    p.add_argument("--multi-summary-output", type=Path, default=Path("outputs/metrics/best_C_multi_receiver_summary.csv"))
    p.add_argument("--multi-dataset-output", type=Path, default=Path("outputs/datasets/best_C_multi_receiver_dataset.csv"))
    p.add_argument("--max-targets", type=int, default=2)
    p.add_argument("--max-attackers-per-target", type=int, default=3)
    p.add_argument("--search-radius-km", nargs="+", type=float, default=[1.0, 2.0, 5.0, 10.0, 20.0, 50.0])
    p.add_argument("--exclude-center-radius-km", nargs="+", type=float, default=[0.0])
    p.add_argument("--station-spacing-km", nargs="+", type=float, default=[50.0, 100.0])
    p.add_argument("--residual-mode", choices=["clean", "empirical", "both"], default="clean")
    p.add_argument("--s2-bearing-deg", type=float, default=90.0)
    p.add_argument("--grid-directions-deg", nargs="+", type=float, default=[0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0])
    p.add_argument("--seed", type=int, default=20260610)
    p.add_argument("--elevation-min-deg", type=float, default=20.0)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def selected_modes(arg: str) -> list[str]:
    return RESIDUAL_MODES if arg == "both" else [arg]


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        active.fail("outputs exist; add --overwrite: " + ", ".join(existing))


def search_grid(center_lat: float, center_lon: float, alt_m: float, radius_km: float, directions_deg: list[float]) -> list[dict[str, float]]:
    cases = [{"C_lat": float(center_lat), "C_lon": float(center_lon), "C_alt_m": float(alt_m), "C_distance_to_center_km": 0.0, "C_bearing_deg": np.nan}]
    for bearing in directions_deg:
        lat, lon = active.destination_point(center_lat, center_lon, float(radius_km), float(bearing))
        actual = float(active.haversine_distance_km(np.array([lat]), np.array([lon]), center_lat, center_lon)[0])
        cases.append({"C_lat": lat, "C_lon": lon, "C_alt_m": float(alt_m), "C_distance_to_center_km": actual, "C_bearing_deg": float(bearing)})
    return cases


def verify_curve(
    sequence_id: str,
    target_name: str,
    target_id: str,
    attacker_name: str,
    attacker_id: str,
    residual_mode: str,
    geo_A: pd.DataFrame,
    f_geo_A: np.ndarray,
    f_geo_B: np.ndarray,
    f_attack_base: np.ndarray,
    terms: tuple[np.ndarray, float, float, float, float],
    threshold_95: float,
    threshold_99: float,
) -> tuple[base.VerificationResult, np.ndarray, np.ndarray, float, float, float, float]:
    t_rel = geo_A["t_rel_s"].to_numpy(float)
    f_obs, noise, b_inj, k_inj, sigma_inj, t0_s = active.apply_residual_terms(f_attack_base, t_rel, terms)
    obs = multi.make_observation(
        sequence_id,
        target_name,
        target_id,
        geo_A.rename(columns={"f_geo_tle_hz": "f_geo_candidate_hz"}),
        f_obs,
        f_geo_B,
        noise,
        b_inj,
        k_inj,
        sigma_inj,
        t0_s,
        "best_C",
        attacker_name,
        attacker_id,
        residual_mode,
    )
    return base.verify_claimed_identity(obs, f_geo_A, threshold_95, threshold_99), f_obs, noise, b_inj, k_inj, sigma_inj, t0_s


def summarize_single(eval_df: pd.DataFrame) -> pd.DataFrame:
    if eval_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    group_cols = ["search_radius_km", "residual_mode"]
    if "exclude_center_radius_km" in eval_df.columns:
        group_cols = ["search_radius_km", "exclude_center_radius_km", "residual_mode"]
    for keys, g in eval_df.groupby(group_cols, sort=True):
        if len(group_cols) == 3:
            radius, exclude_radius, mode = keys
        else:
            radius, mode = keys
            exclude_radius = np.nan
        counts = g["best_tri_decision"].value_counts()
        n = len(g)
        row = {
            "search_radius_km": float(radius),
            "residual_mode": mode,
            "n": int(n),
            "best_accept_rate": float(g["best_p95_accept"].mean()) if n else np.nan,
            "best_defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
            "best_reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
            "best_score_median": float(g["best_score"].median()),
            "best_score_p95": float(g["best_score"].quantile(0.95)),
            "best_C_distance_median": float(g["best_C_distance_to_S_km"].median()),
            "num_candidates_median": float(g["num_candidates"].median()),
        }
        if len(group_cols) == 3:
            row = {"search_radius_km": float(radius), "exclude_center_radius_km": float(exclude_radius), **{k: v for k, v in row.items() if k != "search_radius_km"}}
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_multi(station_df: pd.DataFrame, pairwise_df: pd.DataFrame) -> pd.DataFrame:
    if pairwise_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (strategy, mode, spacing, radius), g in pairwise_df.groupby(["attack_strategy", "residual_mode", "station_spacing_km", "search_radius_km"], sort=True):
        sg = station_df[
            (station_df["attack_strategy"] == strategy)
            & (station_df["residual_mode"] == mode)
            & (station_df["station_spacing_km"].astype(float) == float(spacing))
            & (station_df["search_radius_km"].astype(float) == float(radius))
        ]
        s1 = sg[sg["station_id"] == "S1"]
        s2 = sg[sg["station_id"] == "S2"]
        n = len(g)
        rows.append(
            {
                "attack_strategy": strategy,
                "residual_mode": mode,
                "station_spacing_km": float(spacing),
                "search_radius_km": float(radius),
                "n": int(n),
                "S1_accept_rate": float(s1["p95_accept"].mean()) if len(s1) else np.nan,
                "S2_accept_rate": float(s2["p95_accept"].mean()) if len(s2) else np.nan,
                "both_accept_rate": float(g["both_accept"].mean()) if n else np.nan,
                "any_reject_rate": float(g["any_reject"].mean()) if n else np.nan,
                "S1_score_median": float(g["score_S1"].median()),
                "S2_score_median": float(g["score_S2"].median()),
                "score_gap_median": float(g["score_gap"].median()),
                "pairwise_residual_rmse_median": float(g["pairwise_residual_rmse"].median()),
                "pairwise_residual_rmse_p95": float(g["pairwise_residual_rmse"].quantile(0.95)),
                "best_objective_median": float(g["best_objective"].median()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    check_outputs(
        [
            args.single_eval_output,
            args.single_summary_output,
            args.single_dataset_output,
            args.single_exclude_eval_output,
            args.single_exclude_summary_output,
            args.single_exclude_dataset_output,
            args.multi_station_output,
            args.multi_pairwise_output,
            args.multi_summary_output,
            args.multi_dataset_output,
        ],
        args.overwrite,
    )
    common_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        thresholds=args.thresholds,
        legit_results=args.legit_results,
        max_targets=args.max_targets,
    )
    selection, library, orbit_cfg, tle, threshold_map, k_map, ranges = active.load_common_inputs(common_args)
    ts = load.timescale()
    rng = np.random.default_rng(args.seed)
    modes = selected_modes(args.residual_mode)
    station_cfg = orbit_cfg["station"]
    s1_lat = float(station_cfg["lat_deg"])
    s1_lon = float(station_cfg["lon_deg"])
    s1_alt_m = float(station_cfg["alt_m"])

    single_rows: list[dict[str, Any]] = []
    single_data: list[pd.DataFrame] = []
    single_exclude_rows: list[dict[str, Any]] = []
    single_exclude_data: list[pd.DataFrame] = []
    multi_station_rows: list[dict[str, Any]] = []
    multi_pair_rows: list[dict[str, Any]] = []
    multi_data: list[pd.DataFrame] = []
    seq_counter = 1

    for _, target in selection.iterrows():
        target_id = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        sat_A = tle[target_id]["sat"]
        geo_A_S1 = active.target_geo_from_library(library, target_id)
        times = [base.parse_utc(v) for v in geo_A_S1["t_abs_utc"].astype(str)]
        t_rel = geo_A_S1["t_rel_s"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        freq_hz = float(geo_A_S1["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo_A_S1.columns else 11_325_000_000.0
        f_geo_A_S1 = geo_A_S1["f_geo_candidate_hz"].to_numpy(float)
        max_elev_A_S1 = float(geo_A_S1["elevation_deg"].max()) if "elevation_deg" in geo_A_S1 else float(target.get("max_elevation_deg", np.nan))
        threshold_95, threshold_99 = threshold_map[target_id]
        k_min, k_max = k_map[target_id]
        attackers = active.select_attackers(library, target_id, tle, args.max_attackers_per_target)

        geo_A_C_cache: dict[tuple[float, float, float], np.ndarray] = {}

        for _, attacker in attackers.iterrows():
            attacker_id = str(attacker["candidate_norad_id"])
            attacker_name = str(attacker["candidate_name"])
            sat_B = tle[attacker_id]["sat"]
            geo_B_S1 = active.candidate_geo_from_library(library, target_id, attacker_id, t_rel)
            f_geo_B_S1 = geo_B_S1["f_geo_candidate_hz"].to_numpy(float)

            for mode in modes:
                terms_single = active.sample_residual_terms(t_rel, mode, ranges, rng)
                for radius in args.search_radius_km:
                    all_candidates = search_grid(s1_lat, s1_lon, s1_alt_m, float(radius), args.grid_directions_deg)
                    candidates = all_candidates
                    best: dict[str, Any] | None = None
                    for c in candidates:
                        key = (float(c["C_lat"]), float(c["C_lon"]), float(c["C_alt_m"]))
                        if key not in geo_A_C_cache:
                            geo_A_C_cache[key] = multi.station_geo(sat_A, key[0], key[1], key[2], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                        f_geo_A_C = geo_A_C_cache[key]
                        f_geo_B_C = multi.station_geo(sat_B, key[0], key[1], key[2], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                        u_comp = f_geo_A_C - f_geo_B_C
                        f_attack_base = f_geo_B_S1 + u_comp
                        sequence_id = f"bestC_single_{seq_counter:06d}"
                        verification, f_obs, noise, b_inj, k_inj, sigma_inj, t0_s = verify_curve(
                            sequence_id,
                            target_name,
                            target_id,
                            attacker_name,
                            attacker_id,
                            mode,
                            geo_A_S1,
                            f_geo_A_S1,
                            f_geo_B_S1,
                            f_attack_base,
                            terms_single,
                            threshold_95,
                            threshold_99,
                        )
                        if best is None or verification.score_A_rmse_hz < best["verification"].score_A_rmse_hz:
                            best = {
                                "candidate": c,
                                "verification": verification,
                                "f_obs": f_obs,
                                "noise": noise,
                                "f_attack_base": f_attack_base,
                                "u_comp": u_comp,
                                "b_inj": b_inj,
                                "k_inj": k_inj,
                                "sigma_inj": sigma_inj,
                                "t0_s": t0_s,
                            }
                    assert best is not None
                    sequence_id = f"bestC_single_{seq_counter:06d}"
                    seq_counter += 1
                    v = best["verification"]
                    c = best["candidate"]
                    accepted_score_k = bool(v.accepted_95 and k_min <= v.k_hat_hz_s <= k_max)
                    tri_decision = active.tri_state_decision(accepted_score_k, max_elev_A_S1, args.elevation_min_deg)
                    delta_base = best["f_attack_base"] - f_geo_A_S1
                    single_rows.append(
                        {
                            "sequence_id": sequence_id,
                            "target_sat": target_name,
                            "target_norad_id": target_id,
                            "attacker_sat": attacker_name,
                            "attacker_norad_id": attacker_id,
                            "residual_mode": mode,
                            "search_radius_km": float(radius),
                            "best_C_lat": float(c["C_lat"]),
                            "best_C_lon": float(c["C_lon"]),
                            "best_C_distance_to_S_km": float(c["C_distance_to_center_km"]),
                            "best_C_bearing_deg": c["C_bearing_deg"],
                            "best_score": float(v.score_A_rmse_hz),
                            "best_tri_decision": tri_decision,
                            "best_p95_accept": bool(v.accepted_95),
                            "best_b_hat": float(v.b_hat_hz),
                            "best_k_hat": float(v.k_hat_hz_s),
                            "best_delta_rmse": active.rmse(delta_base),
                            "num_candidates": int(len(candidates)),
                            "threshold_95_hz": threshold_95,
                            "threshold_99_hz": threshold_99,
                        }
                    )
                    single_data.append(
                        pd.DataFrame(
                            {
                                "sequence_id": sequence_id,
                                "target_sat": target_name,
                                "attacker_sat": attacker_name,
                                "residual_mode": mode,
                                "search_radius_km": float(radius),
                                "time_utc": geo_A_S1["t_abs_utc"].to_numpy(str),
                                "t_rel_s": t_rel,
                                "f_geo_A_S_hz": f_geo_A_S1,
                                "f_geo_B_S_hz": f_geo_B_S1,
                                "u_comp_hz": best["u_comp"],
                                "f_attack_base_hz": best["f_attack_base"],
                                "noise_injected_hz": best["noise"],
                                "f_attack_hz": best["f_obs"],
                                "delta_to_claimed_hz": best["f_obs"] - f_geo_A_S1,
                                "delta_base_to_claimed_hz": delta_base,
                                "best_C_lat": float(c["C_lat"]),
                                "best_C_lon": float(c["C_lon"]),
                            }
                        )
                    )

                    for exclude_radius in args.exclude_center_radius_km:
                        filtered = [
                            c0 for c0 in all_candidates
                            if float(c0["C_distance_to_center_km"]) + 1e-12 >= float(exclude_radius)
                        ]
                        if not filtered:
                            continue
                        best_ex: dict[str, Any] | None = None
                        for c0 in filtered:
                            key = (float(c0["C_lat"]), float(c0["C_lon"]), float(c0["C_alt_m"]))
                            if key not in geo_A_C_cache:
                                geo_A_C_cache[key] = multi.station_geo(sat_A, key[0], key[1], key[2], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                            f_geo_A_C = geo_A_C_cache[key]
                            f_geo_B_C = multi.station_geo(sat_B, key[0], key[1], key[2], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                            u_comp = f_geo_A_C - f_geo_B_C
                            f_attack_base = f_geo_B_S1 + u_comp
                            verification, f_obs, noise, b_inj, k_inj, sigma_inj, t0_s = verify_curve(
                                "candidate",
                                target_name,
                                target_id,
                                attacker_name,
                                attacker_id,
                                mode,
                                geo_A_S1,
                                f_geo_A_S1,
                                f_geo_B_S1,
                                f_attack_base,
                                terms_single,
                                threshold_95,
                                threshold_99,
                            )
                            if best_ex is None or verification.score_A_rmse_hz < best_ex["verification"].score_A_rmse_hz:
                                best_ex = {
                                    "candidate": c0,
                                    "verification": verification,
                                    "f_obs": f_obs,
                                    "noise": noise,
                                    "f_attack_base": f_attack_base,
                                    "u_comp": u_comp,
                                }
                        assert best_ex is not None
                        ex_sequence_id = f"bestC_exclude_{seq_counter:06d}"
                        seq_counter += 1
                        ex_v = best_ex["verification"]
                        ex_c = best_ex["candidate"]
                        ex_accepted_score_k = bool(ex_v.accepted_95 and k_min <= ex_v.k_hat_hz_s <= k_max)
                        ex_tri_decision = active.tri_state_decision(ex_accepted_score_k, max_elev_A_S1, args.elevation_min_deg)
                        ex_delta_base = best_ex["f_attack_base"] - f_geo_A_S1
                        single_exclude_rows.append(
                            {
                                "sequence_id": ex_sequence_id,
                                "target_sat": target_name,
                                "target_norad_id": target_id,
                                "attacker_sat": attacker_name,
                                "attacker_norad_id": attacker_id,
                                "residual_mode": mode,
                                "search_radius_km": float(radius),
                                "exclude_center_radius_km": float(exclude_radius),
                                "best_C_lat": float(ex_c["C_lat"]),
                                "best_C_lon": float(ex_c["C_lon"]),
                                "best_C_distance_to_S_km": float(ex_c["C_distance_to_center_km"]),
                                "best_C_bearing_deg": ex_c["C_bearing_deg"],
                                "best_score": float(ex_v.score_A_rmse_hz),
                                "best_tri_decision": ex_tri_decision,
                                "best_p95_accept": bool(ex_v.accepted_95),
                                "best_b_hat": float(ex_v.b_hat_hz),
                                "best_k_hat": float(ex_v.k_hat_hz_s),
                                "best_delta_rmse": active.rmse(ex_delta_base),
                                "num_candidates": int(len(filtered)),
                                "threshold_95_hz": threshold_95,
                                "threshold_99_hz": threshold_99,
                            }
                        )
                        single_exclude_data.append(
                            pd.DataFrame(
                                {
                                    "sequence_id": ex_sequence_id,
                                    "target_sat": target_name,
                                    "attacker_sat": attacker_name,
                                    "residual_mode": mode,
                                    "search_radius_km": float(radius),
                                    "exclude_center_radius_km": float(exclude_radius),
                                    "time_utc": geo_A_S1["t_abs_utc"].to_numpy(str),
                                    "t_rel_s": t_rel,
                                    "f_geo_A_S_hz": f_geo_A_S1,
                                    "f_geo_B_S_hz": f_geo_B_S1,
                                    "u_comp_hz": best_ex["u_comp"],
                                    "f_attack_base_hz": best_ex["f_attack_base"],
                                    "noise_injected_hz": best_ex["noise"],
                                    "f_attack_hz": best_ex["f_obs"],
                                    "delta_to_claimed_hz": best_ex["f_obs"] - f_geo_A_S1,
                                    "delta_base_to_claimed_hz": ex_delta_base,
                                    "best_C_lat": float(ex_c["C_lat"]),
                                    "best_C_lon": float(ex_c["C_lon"]),
                                }
                            )
                        )

            for spacing in args.station_spacing_km:
                s2_lat, s2_lon = active.destination_point(s1_lat, s1_lon, float(spacing), float(args.s2_bearing_deg))
                actual_spacing = float(active.haversine_distance_km(np.array([s2_lat]), np.array([s2_lon]), s1_lat, s1_lon)[0])
                midpoint_lat, midpoint_lon = active.destination_point(s1_lat, s1_lon, actual_spacing / 2.0, float(args.s2_bearing_deg))
                geo_A_S2 = multi.station_geo(sat_A, s2_lat, s2_lon, s1_alt_m, times, ts, freq_hz, step_s)
                geo_B_S2 = multi.station_geo(sat_B, s2_lat, s2_lon, s1_alt_m, times, ts, freq_hz, step_s)
                f_geo_A_S2 = geo_A_S2["f_geo_tle_hz"].to_numpy(float)
                f_geo_B_S2 = geo_B_S2["f_geo_tle_hz"].to_numpy(float)
                max_elev = {"S1": max_elev_A_S1, "S2": float(geo_A_S2["elevation_deg"].max())}
                station_meta = {
                    "S1": multi.station_record("S1", s1_lat, s1_lon, s1_alt_m),
                    "S2": multi.station_record("S2", s2_lat, s2_lon, s1_alt_m),
                }
                for mode in modes:
                    terms = {
                        "S1": active.sample_residual_terms(t_rel, mode, ranges, rng),
                        "S2": active.sample_residual_terms(t_rel, mode, ranges, rng),
                    }
                    for radius in args.search_radius_km:
                        candidates = search_grid(midpoint_lat, midpoint_lon, s1_alt_m, float(radius), args.grid_directions_deg)
                        best_pair: dict[str, Any] | None = None
                        for c in candidates:
                            f_geo_A_C = multi.station_geo(sat_A, c["C_lat"], c["C_lon"], c["C_alt_m"], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                            f_geo_B_C = multi.station_geo(sat_B, c["C_lat"], c["C_lon"], c["C_alt_m"], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                            u_comp = f_geo_A_C - f_geo_B_C
                            candidate_results: dict[str, Any] = {}
                            scores = []
                            for station_id, geo_A_station, f_geo_A_station, f_geo_B_station in [
                                ("S1", geo_A_S1, f_geo_A_S1, f_geo_B_S1),
                                ("S2", geo_A_S2, f_geo_A_S2, f_geo_B_S2),
                            ]:
                                v, f_obs, noise, b_inj, k_inj, sigma_inj, t0_s = verify_curve(
                                    "candidate",
                                    target_name,
                                    target_id,
                                    attacker_name,
                                    attacker_id,
                                    mode,
                                    geo_A_station,
                                    f_geo_A_station,
                                    f_geo_B_station,
                                    f_geo_B_station + u_comp,
                                    terms[station_id],
                                    threshold_95,
                                    threshold_99,
                                )
                                scores.append(float(v.score_A_rmse_hz))
                                candidate_results[station_id] = {
                                    "verification": v,
                                    "f_obs": f_obs,
                                    "noise": noise,
                                    "b_inj": b_inj,
                                    "k_inj": k_inj,
                                    "sigma_inj": sigma_inj,
                                    "t0_s": t0_s,
                                    "f_attack_base": f_geo_B_station + u_comp,
                                }
                            objective = max(scores)
                            score_sum = sum(scores)
                            if best_pair is None or objective < best_pair["objective"]:
                                best_pair = {"candidate": c, "u_comp": u_comp, "results": candidate_results, "objective": objective, "score_sum": score_sum}
                        assert best_pair is not None
                        pair_id = f"bestC_multi_{seq_counter:06d}"
                        seq_counter += 1
                        residuals: dict[str, np.ndarray] = {}
                        score_by_station: dict[str, float] = {}
                        b_by_station: dict[str, float] = {}
                        k_by_station: dict[str, float] = {}
                        decision_by_station: dict[str, str] = {}
                        p95_by_station: dict[str, bool] = {}
                        for station_id, geo_A_station, f_geo_A_station, f_geo_B_station in [
                            ("S1", geo_A_S1, f_geo_A_S1, f_geo_B_S1),
                            ("S2", geo_A_S2, f_geo_A_S2, f_geo_B_S2),
                        ]:
                            r = best_pair["results"][station_id]
                            v = r["verification"]
                            accepted_score_k = bool(v.accepted_95 and k_min <= v.k_hat_hz_s <= k_max)
                            decision = active.tri_state_decision(accepted_score_k, max_elev[station_id], args.elevation_min_deg)
                            residual_after_fit = multi.fit_residual_after_fit(r["f_obs"], f_geo_A_station, t_rel)
                            residuals[station_id] = residual_after_fit
                            score_by_station[station_id] = float(v.score_A_rmse_hz)
                            b_by_station[station_id] = float(v.b_hat_hz)
                            k_by_station[station_id] = float(v.k_hat_hz_s)
                            decision_by_station[station_id] = decision
                            p95_by_station[station_id] = bool(v.accepted_95)
                            delta_base = r["f_attack_base"] - f_geo_A_station
                            meta = station_meta[station_id]
                            multi_station_rows.append(
                                {
                                    "sequence_id": pair_id,
                                    "target_sat": target_name,
                                    "target_norad_id": target_id,
                                    "attacker_sat": attacker_name,
                                    "attacker_norad_id": attacker_id,
                                    "attack_strategy": "best_C_two_station",
                                    "residual_mode": mode,
                                    "station_spacing_km": float(spacing),
                                    "actual_station_spacing_km": actual_spacing,
                                    "search_radius_km": float(radius),
                                    "best_C_lat": float(best_pair["candidate"]["C_lat"]),
                                    "best_C_lon": float(best_pair["candidate"]["C_lon"]),
                                    "best_C_distance_to_midpoint_km": float(best_pair["candidate"]["C_distance_to_center_km"]),
                                    **meta,
                                    "tri_decision": decision,
                                    "p95_accept": bool(v.accepted_95),
                                    "score": float(v.score_A_rmse_hz),
                                    "b_hat": float(v.b_hat_hz),
                                    "k_hat": float(v.k_hat_hz_s),
                                    "max_elevation": max_elev[station_id],
                                    "delta_rmse": active.rmse(delta_base),
                                    "best_objective": float(best_pair["objective"]),
                                    "score_sum": float(best_pair["score_sum"]),
                                    "num_candidates": int(len(candidates)),
                                }
                            )
                            multi_data.append(
                                pd.DataFrame(
                                    {
                                        "sequence_id": pair_id,
                                        "station_id": station_id,
                                        "target_sat": target_name,
                                        "attacker_sat": attacker_name,
                                        "attack_strategy": "best_C_two_station",
                                        "residual_mode": mode,
                                        "station_spacing_km": float(spacing),
                                        "search_radius_km": float(radius),
                                        "time_utc": geo_A_station["t_abs_utc"].to_numpy(str),
                                        "t_rel_s": t_rel,
                                        "f_geo_A_station_hz": f_geo_A_station,
                                        "f_geo_B_station_hz": f_geo_B_station,
                                        "u_comp_hz": best_pair["u_comp"],
                                        "f_attack_base_hz": r["f_attack_base"],
                                        "f_attack_hz": r["f_obs"],
                                        "delta_to_claimed_hz": r["f_obs"] - f_geo_A_station,
                                        "residual_after_fit_hz": residual_after_fit,
                                        "best_C_lat": float(best_pair["candidate"]["C_lat"]),
                                        "best_C_lon": float(best_pair["candidate"]["C_lon"]),
                                    }
                                )
                            )
                        multi_pair_rows.append(
                            {
                                "sequence_id": pair_id,
                                "target_sat": target_name,
                                "target_norad_id": target_id,
                                "attacker_sat": attacker_name,
                                "attacker_norad_id": attacker_id,
                                "attack_strategy": "best_C_two_station",
                                "residual_mode": mode,
                                "station_spacing_km": float(spacing),
                                "actual_station_spacing_km": actual_spacing,
                                "search_radius_km": float(radius),
                                "best_C_lat": float(best_pair["candidate"]["C_lat"]),
                                "best_C_lon": float(best_pair["candidate"]["C_lon"]),
                                "best_objective": float(best_pair["objective"]),
                                "score_sum": float(best_pair["score_sum"]),
                                "decision_S1": decision_by_station["S1"],
                                "decision_S2": decision_by_station["S2"],
                                "both_accept": bool(p95_by_station["S1"] and p95_by_station["S2"]),
                                "any_reject": bool(decision_by_station["S1"] == "REJECT" or decision_by_station["S2"] == "REJECT"),
                                "score_S1": score_by_station["S1"],
                                "score_S2": score_by_station["S2"],
                                "score_gap": abs(score_by_station["S1"] - score_by_station["S2"]),
                                "b_gap": abs(b_by_station["S1"] - b_by_station["S2"]),
                                "k_gap": abs(k_by_station["S1"] - k_by_station["S2"]),
                                "pairwise_residual_rmse": active.rmse(residuals["S1"] - residuals["S2"]),
                                "num_candidates": int(len(candidates)),
                            }
                        )

    single_eval = pd.DataFrame(single_rows)
    single_summary = summarize_single(single_eval)
    single_dataset = pd.concat(single_data, ignore_index=True) if single_data else pd.DataFrame()
    single_exclude_eval = pd.DataFrame(single_exclude_rows)
    single_exclude_summary = summarize_single(single_exclude_eval)
    single_exclude_dataset = pd.concat(single_exclude_data, ignore_index=True) if single_exclude_data else pd.DataFrame()
    multi_station = pd.DataFrame(multi_station_rows)
    multi_pair = pd.DataFrame(multi_pair_rows)
    multi_summary = summarize_multi(multi_station, multi_pair)
    multi_dataset = pd.concat(multi_data, ignore_index=True) if multi_data else pd.DataFrame()

    outputs = [
        (args.single_eval_output, single_eval),
        (args.single_summary_output, single_summary),
        (args.single_dataset_output, single_dataset),
        (args.single_exclude_eval_output, single_exclude_eval),
        (args.single_exclude_summary_output, single_exclude_summary),
        (args.single_exclude_dataset_output, single_exclude_dataset),
        (args.multi_station_output, multi_station),
        (args.multi_pairwise_output, multi_pair),
        (args.multi_summary_output, multi_summary),
        (args.multi_dataset_output, multi_dataset),
    ]
    for path, df in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        print(f"wrote {path} rows={len(df)}")
    if not single_summary.empty:
        print(single_summary.to_string(index=False))
    if not multi_summary.empty:
        print(multi_summary.to_string(index=False))


if __name__ == "__main__":
    main()
