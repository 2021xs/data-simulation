#!/usr/bin/env python
"""First-pass two-receiver common active-compensation attack experiment.

The attacker emits one shared compensation curve u(t).  S1 and S2 each receive
that same u(t), then each station is evaluated by the existing single-station
claimed-identity verifier against its local claimed-target geometry.
"""

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

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402


ATTACK_STRATEGIES = ["target_S1", "service_center", "two_station_average"]
BENIGN_STRATEGY = "benign_A"
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
    p.add_argument("--station-output", type=Path, default=Path("outputs/metrics/multi_receiver_station_eval.csv"))
    p.add_argument("--pairwise-output", type=Path, default=Path("outputs/metrics/multi_receiver_pairwise_consistency.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/multi_receiver_summary.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/multi_receiver_first_pass_dataset.csv"))
    p.add_argument("--max-targets", type=int, default=2)
    p.add_argument("--max-attackers-per-target", type=int, default=3)
    p.add_argument("--station-spacing-km", nargs="+", type=float, default=[50.0, 100.0, 200.0, 500.0])
    p.add_argument("--residual-mode", choices=["clean", "empirical", "both"], default="clean")
    p.add_argument("--attack-strategy", choices=ATTACK_STRATEGIES + [BENIGN_STRATEGY, "all"], default="all")
    p.add_argument("--include-benign", action="store_true")
    p.add_argument("--s2-bearing-deg", type=float, default=90.0)
    p.add_argument("--seed", type=int, default=20260609)
    p.add_argument("--elevation-min-deg", type=float, default=20.0)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def selected_residual_modes(arg: str) -> list[str]:
    return RESIDUAL_MODES if arg == "both" else [arg]


def selected_attack_strategies(arg: str, include_benign: bool) -> list[str]:
    strategies = ATTACK_STRATEGIES if arg == "all" else [arg]
    if include_benign and BENIGN_STRATEGY not in strategies:
        strategies = [BENIGN_STRATEGY] + strategies
    return strategies


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        active.fail("outputs exist; add --overwrite: " + ", ".join(existing))


def fit_residual_after_fit(y_obs_hz: np.ndarray, f_geo_claimed_hz: np.ndarray, t_rel_s: np.ndarray) -> np.ndarray:
    x = np.asarray(t_rel_s, dtype=float) - float(np.mean(t_rel_s))
    delta = np.asarray(y_obs_hz, dtype=float) - np.asarray(f_geo_claimed_hz, dtype=float)
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    return delta - design @ coef


def station_geo(
    sat: Any,
    lat_deg: float,
    lon_deg: float,
    alt_m: float,
    times: list[Any],
    ts: Any,
    freq_hz: float,
    step_s: float,
) -> pd.DataFrame:
    site = orbit_builder.wgs84.latlon(float(lat_deg), float(lon_deg), elevation_m=float(alt_m))
    return orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))


def station_record(
    station_id: str,
    lat_deg: float,
    lon_deg: float,
    alt_m: float,
) -> dict[str, float | str]:
    return {
        "station_id": station_id,
        "station_lat": float(lat_deg),
        "station_lon": float(lon_deg),
        "station_alt_km": float(alt_m) / 1000.0,
    }


def make_observation(
    sequence_id: str,
    target_name: str,
    target_id: str,
    geo_A: pd.DataFrame,
    f_obs: np.ndarray,
    f_geo_B: np.ndarray,
    noise: np.ndarray,
    b_inj: float,
    k_inj: float,
    sigma_inj: float,
    t0_s: float,
    strategy: str,
    attacker_name: str,
    attacker_id: str,
    residual_mode: str,
) -> base.ObservationSequence:
    return base.ObservationSequence(
        sequence_id=sequence_id,
        source_type="ATTACK",
        claimed_target_name=target_name,
        claimed_target_norad=target_id,
        t_abs_utc=geo_A["t_abs_utc"].to_numpy(str),
        t_rel_s=geo_A["t_rel_s"].to_numpy(float),
        y_obs_hz=np.asarray(f_obs, dtype=float),
        f_geo_source_hz=np.asarray(f_geo_B, dtype=float),
        noise_hz=np.asarray(noise, dtype=float),
        b_true_hz=float(b_inj),
        k_true_hz_s=float(k_inj),
        sigma_true_hz=float(sigma_inj),
        t0_s=float(t0_s),
        sample_id=1,
        attack_type="multi_receiver_common_active_compensation_first_pass",
        attack_variant=strategy,
        metadata={"attacker_name": attacker_name, "attacker_norad": attacker_id, "residual_mode": residual_mode},
    )


def build_summary(station_eval: pd.DataFrame, pairwise: pd.DataFrame) -> pd.DataFrame:
    if pairwise.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (strategy, mode, spacing), g in pairwise.groupby(["attack_strategy", "residual_mode", "station_spacing_km"], sort=True):
        station_g = station_eval[
            (station_eval["attack_strategy"] == strategy)
            & (station_eval["residual_mode"] == mode)
            & (station_eval["station_spacing_km"].astype(float) == float(spacing))
        ]
        s1 = station_g[station_g["station_id"] == "S1"]
        s2 = station_g[station_g["station_id"] == "S2"]
        n = len(g)
        rows.append(
            {
                "attack_strategy": strategy,
                "residual_mode": mode,
                "station_spacing_km": float(spacing),
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
                "b_gap_median": float(g["b_gap"].median()),
                "k_gap_median": float(g["k_gap"].median()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    check_outputs([args.station_output, args.pairwise_output, args.summary_output, args.dataset_output], args.overwrite)

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
    modes = selected_residual_modes(args.residual_mode)
    strategies = selected_attack_strategies(args.attack_strategy, args.include_benign)

    station_cfg = orbit_cfg["station"]
    s1_lat = float(station_cfg["lat_deg"])
    s1_lon = float(station_cfg["lon_deg"])
    s1_alt_m = float(station_cfg["alt_m"])

    station_rows: list[dict[str, Any]] = []
    pairwise_rows: list[dict[str, Any]] = []
    dataset_rows: list[pd.DataFrame] = []
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
        pass_start = str(target["pass_start_utc"]) if "pass_start_utc" in target else str(geo_A_S1["t_abs_utc"].iloc[0])
        pass_end = str(target["pass_end_utc"]) if "pass_end_utc" in target else str(geo_A_S1["t_abs_utc"].iloc[-1])
        threshold_95, threshold_99 = threshold_map[target_id]
        k_min, k_max = k_map[target_id]
        attackers = active.select_attackers(library, target_id, tle, args.max_attackers_per_target)

        for spacing_km in args.station_spacing_km:
            s2_lat, s2_lon = active.destination_point(s1_lat, s1_lon, float(spacing_km), float(args.s2_bearing_deg))
            actual_spacing = float(active.haversine_distance_km(np.array([s2_lat]), np.array([s2_lon]), s1_lat, s1_lon)[0])
            c_lat, c_lon = active.destination_point(s1_lat, s1_lon, actual_spacing / 2.0, float(args.s2_bearing_deg))
            c_alt_m = s1_alt_m
            s1_meta = station_record("S1", s1_lat, s1_lon, s1_alt_m)
            s2_meta = station_record("S2", s2_lat, s2_lon, s1_alt_m)

            geo_A_S2 = station_geo(sat_A, s2_lat, s2_lon, s1_alt_m, times, ts, freq_hz, step_s)
            geo_A_C = station_geo(sat_A, c_lat, c_lon, c_alt_m, times, ts, freq_hz, step_s)
            f_geo_A_S1 = geo_A_S1["f_geo_candidate_hz"].to_numpy(float)
            f_geo_A_S2 = geo_A_S2["f_geo_tle_hz"].to_numpy(float)
            f_geo_A_C = geo_A_C["f_geo_tle_hz"].to_numpy(float)
            max_elev_A = {
                "S1": float(geo_A_S1["elevation_deg"].max()) if "elevation_deg" in geo_A_S1 else float(target.get("max_elevation_deg", np.nan)),
                "S2": float(geo_A_S2["elevation_deg"].max()),
            }

            for _, attacker in attackers.iterrows():
                attacker_id = str(attacker["candidate_norad_id"])
                attacker_name = str(attacker["candidate_name"])
                sat_B = tle[attacker_id]["sat"]
                geo_B_S1 = active.candidate_geo_from_library(library, target_id, attacker_id, t_rel)
                geo_B_S1_diag = station_geo(sat_B, s1_lat, s1_lon, s1_alt_m, times, ts, freq_hz, step_s)
                geo_B_S2 = station_geo(sat_B, s2_lat, s2_lon, s1_alt_m, times, ts, freq_hz, step_s)
                geo_B_C = station_geo(sat_B, c_lat, c_lon, c_alt_m, times, ts, freq_hz, step_s)
                f_geo_B_S1 = geo_B_S1["f_geo_candidate_hz"].to_numpy(float)
                f_geo_B_S2 = geo_B_S2["f_geo_tle_hz"].to_numpy(float)
                f_geo_B_C = geo_B_C["f_geo_tle_hz"].to_numpy(float)

                d1 = f_geo_A_S1 - f_geo_B_S1
                d2 = f_geo_A_S2 - f_geo_B_S2
                u_by_strategy = {
                    BENIGN_STRATEGY: np.zeros_like(f_geo_A_S1),
                    "target_S1": d1,
                    "service_center": f_geo_A_C - f_geo_B_C,
                    "two_station_average": 0.5 * (d1 + d2),
                }
                residual_terms = {
                    (mode, station_id): active.sample_residual_terms(t_rel, mode, ranges, rng)
                    for mode in modes
                    for station_id in ["S1", "S2"]
                }

                for strategy in strategies:
                    u_comp = np.asarray(u_by_strategy[strategy], dtype=float)
                    active.finite_check(f"u_comp:{strategy}", u_comp)
                    for mode in modes:
                        pair_sequence_id = f"multi_recv_{seq_counter:06d}"
                        seq_counter += 1
                        station_results: dict[str, dict[str, Any]] = {}
                        station_payload = {
                            "S1": (s1_meta, geo_A_S1, f_geo_A_S1, f_geo_B_S1, geo_B_S1_diag["elevation_deg"].to_numpy(float)),
                            "S2": (s2_meta, geo_A_S2, f_geo_A_S2, f_geo_B_S2, geo_B_S2["elevation_deg"].to_numpy(float)),
                        }
                        for station_id, (meta, geo_A_station, f_geo_A_station, f_geo_B_station, elev_B) in station_payload.items():
                            if strategy == BENIGN_STRATEGY:
                                f_geo_B_station = f_geo_A_station
                                elev_B = (
                                    geo_A_station["elevation_deg"].to_numpy(float)
                                    if "elevation_deg" in geo_A_station
                                    else np.full(len(t_rel), max_elev_A[station_id], dtype=float)
                                )
                            f_attack_base = np.asarray(f_geo_B_station, dtype=float) + u_comp
                            f_obs, noise, b_inj, k_inj, sigma_inj, t0_s = active.apply_residual_terms(
                                f_attack_base,
                                t_rel,
                                residual_terms[(mode, station_id)],
                            )
                            observation = make_observation(
                                f"{pair_sequence_id}_{station_id}",
                                target_name,
                                target_id,
                                geo_A_station.rename(columns={"f_geo_tle_hz": "f_geo_candidate_hz"}),
                                f_obs,
                                f_geo_B_station,
                                noise,
                                b_inj,
                                k_inj,
                                sigma_inj,
                                t0_s,
                                strategy,
                                attacker_name,
                                attacker_id,
                                mode,
                            )
                            verification = base.verify_claimed_identity(observation, f_geo_A_station, threshold_95, threshold_99)
                            accepted_score_k = bool(verification.accepted_95 and k_min <= verification.k_hat_hz_s <= k_max)
                            tri_decision = active.tri_state_decision(accepted_score_k, max_elev_A[station_id], args.elevation_min_deg)
                            residual_after_fit = fit_residual_after_fit(f_obs, f_geo_A_station, t_rel)
                            delta_base = f_attack_base - f_geo_A_station
                            station_results[station_id] = {
                                "decision": tri_decision,
                                "p95_accept": bool(verification.accepted_95),
                                "score": float(verification.score_A_rmse_hz),
                                "b_hat": float(verification.b_hat_hz),
                                "k_hat": float(verification.k_hat_hz_s),
                                "residual_after_fit": residual_after_fit,
                            }
                            station_rows.append(
                                {
                                    "sequence_id": pair_sequence_id,
                                    "target_sat": target_name,
                                    "target_norad_id": target_id,
                                    "attacker_sat": attacker_name,
                                    "attacker_norad_id": attacker_id,
                                    "attack_strategy": strategy,
                                    "residual_mode": mode,
                                    "station_spacing_km": float(spacing_km),
                                    "actual_station_spacing_km": actual_spacing,
                                    **meta,
                                    "service_center_lat": c_lat,
                                    "service_center_lon": c_lon,
                                    "service_center_alt_km": c_alt_m / 1000.0,
                                    "tri_decision": tri_decision,
                                    "p95_accept": bool(verification.accepted_95),
                                    "accepted_per_target_k_p01_p99": accepted_score_k,
                                    "score": float(verification.score_A_rmse_hz),
                                    "b_hat": float(verification.b_hat_hz),
                                    "k_hat": float(verification.k_hat_hz_s),
                                    "max_elevation": max_elev_A[station_id],
                                    "B_max_elevation": float(np.nanmax(elev_B)) if np.any(np.isfinite(elev_B)) else np.nan,
                                    "delta_rmse": active.rmse(delta_base),
                                    "threshold_95_hz": threshold_95,
                                    "threshold_99_hz": threshold_99,
                                    "target_k_min_p01": k_min,
                                    "target_k_max_p99": k_max,
                                    "b_injected_hz": float(b_inj),
                                    "k_injected_hz_s": float(k_inj),
                                    "noise_sigma_hz": float(sigma_inj),
                                    "random_seed": int(args.seed),
                                }
                            )
                            dataset_rows.append(
                                pd.DataFrame(
                                    {
                                        "sequence_id": pair_sequence_id,
                                        "station_id": station_id,
                                        "target_sat": target_name,
                                        "target_norad_id": target_id,
                                        "attacker_sat": attacker_name,
                                        "attacker_norad_id": attacker_id,
                                        "attack_strategy": strategy,
                                        "residual_mode": mode,
                                        "station_spacing_km": float(spacing_km),
                                        "actual_station_spacing_km": actual_spacing,
                                        "time_utc": geo_A_station["t_abs_utc"].to_numpy(str),
                                        "t_rel_s": t_rel,
                                        "f_geo_A_station_hz": f_geo_A_station,
                                        "f_geo_B_station_hz": f_geo_B_station,
                                        "u_comp_hz": u_comp,
                                        "f_attack_base_hz": f_attack_base,
                                        "noise_injected_hz": noise,
                                        "f_attack_hz": f_obs,
                                        "delta_to_claimed_hz": f_obs - f_geo_A_station,
                                        "delta_base_to_claimed_hz": delta_base,
                                        "residual_after_fit_hz": residual_after_fit,
                                        "station_lat": float(meta["station_lat"]),
                                        "station_lon": float(meta["station_lon"]),
                                        "station_alt_km": float(meta["station_alt_km"]),
                                        "service_center_lat": c_lat,
                                        "service_center_lon": c_lon,
                                        "service_center_alt_km": c_alt_m / 1000.0,
                                    }
                                )
                            )

                        s1 = station_results["S1"]
                        s2 = station_results["S2"]
                        pairwise_rows.append(
                            {
                                "sequence_id": pair_sequence_id,
                                "target_sat": target_name,
                                "target_norad_id": target_id,
                                "attacker_sat": attacker_name,
                                "attacker_norad_id": attacker_id,
                                "attack_strategy": strategy,
                                "residual_mode": mode,
                                "station_spacing_km": float(spacing_km),
                                "actual_station_spacing_km": actual_spacing,
                                "service_center_lat": c_lat,
                                "service_center_lon": c_lon,
                                "decision_S1": s1["decision"],
                                "decision_S2": s2["decision"],
                                "both_accept": bool(s1["p95_accept"] and s2["p95_accept"]),
                                "any_reject": bool(s1["decision"] == "REJECT" or s2["decision"] == "REJECT"),
                                "score_S1": float(s1["score"]),
                                "score_S2": float(s2["score"]),
                                "score_gap": abs(float(s1["score"]) - float(s2["score"])),
                                "b_gap": abs(float(s1["b_hat"]) - float(s2["b_hat"])),
                                "k_gap": abs(float(s1["k_hat"]) - float(s2["k_hat"])),
                                "pairwise_residual_rmse": active.rmse(np.asarray(s1["residual_after_fit"]) - np.asarray(s2["residual_after_fit"])),
                            }
                        )

    station_eval = pd.DataFrame(station_rows)
    pairwise = pd.DataFrame(pairwise_rows)
    summary = build_summary(station_eval, pairwise)
    dataset = pd.concat(dataset_rows, ignore_index=True) if dataset_rows else pd.DataFrame()

    for path in [args.station_output, args.pairwise_output, args.summary_output, args.dataset_output]:
        path.parent.mkdir(parents=True, exist_ok=True)
    station_eval.to_csv(args.station_output, index=False)
    pairwise.to_csv(args.pairwise_output, index=False)
    summary.to_csv(args.summary_output, index=False)
    dataset.to_csv(args.dataset_output, index=False)

    print(f"wrote {args.station_output} rows={len(station_eval)}")
    print(f"wrote {args.pairwise_output} rows={len(pairwise)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    if not summary.empty:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
