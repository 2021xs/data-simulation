#!/usr/bin/env python
"""Short-window active compensation verifier evaluation."""

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
import run_best_C_active_compensation as bestc  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_multi_receiver_active_compensation_first_pass as multi  # noqa: E402


STRATEGIES = ["benign_A", "target_S1", "service_center", "two_station_average", "best_C_single_station"]
WINDOW_MODES = ["full_pass", "first_half", "middle_half", "best_60s", "best_120s", "best_180s"]
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
    p.add_argument("--eval-output", type=Path, default=Path("outputs/metrics/short_window_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/short_window_summary.csv"))
    p.add_argument("--max-targets", type=int, default=2)
    p.add_argument("--max-attackers-per-target", type=int, default=3)
    p.add_argument("--window-mode", nargs="+", choices=WINDOW_MODES, default=WINDOW_MODES)
    p.add_argument("--attack-strategy", nargs="+", choices=STRATEGIES, default=STRATEGIES)
    p.add_argument("--residual-mode", choices=["clean", "empirical", "both"], default="clean")
    p.add_argument("--station-spacing-km", type=float, default=50.0)
    p.add_argument("--search-radius-km", nargs="+", type=float, default=[1.0, 2.0, 5.0, 10.0, 20.0, 50.0])
    p.add_argument("--grid-directions-deg", nargs="+", type=float, default=[0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0])
    p.add_argument("--sliding-step-s", type=float, default=10.0)
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


def make_obs(sequence_id: str, target_name: str, target_id: str, t_abs: np.ndarray, t_rel: np.ndarray, y_obs: np.ndarray, f_source: np.ndarray) -> base.ObservationSequence:
    return base.ObservationSequence(
        sequence_id=sequence_id,
        source_type="ATTACK",
        claimed_target_name=target_name,
        claimed_target_norad=target_id,
        t_abs_utc=t_abs,
        t_rel_s=t_rel,
        y_obs_hz=y_obs,
        f_geo_source_hz=f_source,
        noise_hz=np.zeros(len(t_rel), dtype=float),
        b_true_hz=0.0,
        k_true_hz_s=0.0,
        sigma_true_hz=0.0,
        t0_s=float(np.mean(t_rel)),
        sample_id=1,
    )


def fixed_windows(mode: str, t_rel: np.ndarray) -> list[tuple[int, int]]:
    n = len(t_rel)
    if mode == "full_pass":
        return [(0, n)]
    if mode == "first_half":
        return [(0, max(3, n // 2))]
    if mode == "middle_half":
        width = max(3, n // 2)
        start = max(0, (n - width) // 2)
        return [(start, min(n, start + width))]
    raise ValueError(mode)


def sliding_windows(duration_s: float, t_rel: np.ndarray, step_s: float) -> list[tuple[int, int]]:
    if duration_s >= float(t_rel[-1] - t_rel[0]):
        return [(0, len(t_rel))]
    starts = np.arange(float(t_rel[0]), float(t_rel[-1] - duration_s) + 1e-9, float(step_s))
    windows: list[tuple[int, int]] = []
    for start_s in starts:
        end_s = start_s + float(duration_s)
        i0 = int(np.searchsorted(t_rel, start_s, side="left"))
        i1 = int(np.searchsorted(t_rel, end_s, side="right"))
        if i1 - i0 >= 3:
            windows.append((i0, i1))
    return windows or [(0, len(t_rel))]


def choose_window(
    window_mode: str,
    t_abs: np.ndarray,
    t_rel: np.ndarray,
    y_obs: np.ndarray,
    f_geo_A: np.ndarray,
    f_source: np.ndarray,
    target_name: str,
    target_id: str,
    threshold_95: float,
    threshold_99: float,
    step_s: float,
) -> tuple[int, int, base.VerificationResult]:
    if window_mode.startswith("best_"):
        duration_s = float(window_mode.replace("best_", "").replace("s", ""))
        windows = sliding_windows(duration_s, t_rel, step_s)
    else:
        windows = fixed_windows(window_mode, t_rel)
    best: tuple[int, int, base.VerificationResult] | None = None
    for i0, i1 in windows:
        obs = make_obs("short_candidate", target_name, target_id, t_abs[i0:i1], t_rel[i0:i1] - float(t_rel[i0]), y_obs[i0:i1], f_source[i0:i1])
        v = base.verify_claimed_identity(obs, f_geo_A[i0:i1], threshold_95, threshold_99)
        if best is None or v.score_A_rmse_hz < best[2].score_A_rmse_hz:
            best = (i0, i1, v)
    assert best is not None
    return best


def build_summary(eval_df: pd.DataFrame) -> pd.DataFrame:
    if eval_df.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (strategy, window_mode, residual_mode), g in eval_df.groupby(["attack_strategy", "window_mode", "residual_mode"], sort=True):
        counts = g["tri_decision"].value_counts()
        n = len(g)
        rows.append(
            {
                "attack_strategy": strategy,
                "window_mode": window_mode,
                "residual_mode": residual_mode,
                "n": int(n),
                "accept_rate": float(g["p95_accept"].mean()) if n else np.nan,
                "defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
                "reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
                "score_median": float(g["score"].median()),
                "score_p95": float(g["score"].quantile(0.95)),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    check_outputs([args.eval_output, args.summary_output], args.overwrite)
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

    rows: list[dict[str, Any]] = []
    seq_counter = 1
    for _, target in selection.iterrows():
        target_id = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        sat_A = tle[target_id]["sat"]
        geo_A_S1 = active.target_geo_from_library(library, target_id)
        times = [base.parse_utc(v) for v in geo_A_S1["t_abs_utc"].astype(str)]
        t_abs = geo_A_S1["t_abs_utc"].to_numpy(str)
        t_rel = geo_A_S1["t_rel_s"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        freq_hz = float(geo_A_S1["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo_A_S1.columns else 11_325_000_000.0
        f_geo_A_S1 = geo_A_S1["f_geo_candidate_hz"].to_numpy(float)
        max_elev_A = float(geo_A_S1["elevation_deg"].max()) if "elevation_deg" in geo_A_S1 else float(target.get("max_elevation_deg", np.nan))
        threshold_95, threshold_99 = threshold_map[target_id]
        k_min, k_max = k_map[target_id]
        s2_lat, s2_lon = active.destination_point(s1_lat, s1_lon, float(args.station_spacing_km), 90.0)
        mid_lat, mid_lon = active.destination_point(s1_lat, s1_lon, float(args.station_spacing_km) / 2.0, 90.0)
        geo_A_S2 = multi.station_geo(sat_A, s2_lat, s2_lon, s1_alt_m, times, ts, freq_hz, step_s)
        f_geo_A_S2 = geo_A_S2["f_geo_tle_hz"].to_numpy(float)
        attackers = active.select_attackers(library, target_id, tle, args.max_attackers_per_target)

        for _, attacker in attackers.iterrows():
            attacker_id = str(attacker["candidate_norad_id"])
            attacker_name = str(attacker["candidate_name"])
            sat_B = tle[attacker_id]["sat"]
            geo_B_S1 = active.candidate_geo_from_library(library, target_id, attacker_id, t_rel)
            f_geo_B_S1 = geo_B_S1["f_geo_candidate_hz"].to_numpy(float)
            geo_B_S2 = multi.station_geo(sat_B, s2_lat, s2_lon, s1_alt_m, times, ts, freq_hz, step_s)
            f_geo_B_S2 = geo_B_S2["f_geo_tle_hz"].to_numpy(float)
            geo_A_C = multi.station_geo(sat_A, mid_lat, mid_lon, s1_alt_m, times, ts, freq_hz, step_s)
            geo_B_C = multi.station_geo(sat_B, mid_lat, mid_lon, s1_alt_m, times, ts, freq_hz, step_s)
            d1 = f_geo_A_S1 - f_geo_B_S1
            d2 = f_geo_A_S2 - f_geo_B_S2
            u_base = {
                "benign_A": np.zeros_like(f_geo_A_S1),
                "target_S1": d1,
                "service_center": geo_A_C["f_geo_tle_hz"].to_numpy(float) - geo_B_C["f_geo_tle_hz"].to_numpy(float),
                "two_station_average": 0.5 * (d1 + d2),
            }
            for mode in modes:
                terms = active.sample_residual_terms(t_rel, mode, ranges, rng)
                for strategy in args.attack_strategy:
                    if strategy == "best_C_single_station":
                        best_score = np.inf
                        best_u = None
                        for radius in args.search_radius_km:
                            for c in bestc.search_grid(s1_lat, s1_lon, s1_alt_m, float(radius), args.grid_directions_deg):
                                f_A_C = multi.station_geo(sat_A, c["C_lat"], c["C_lon"], c["C_alt_m"], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                                f_B_C = multi.station_geo(sat_B, c["C_lat"], c["C_lon"], c["C_alt_m"], times, ts, freq_hz, step_s)["f_geo_tle_hz"].to_numpy(float)
                                u = f_A_C - f_B_C
                                f_base = f_geo_B_S1 + u
                                f_obs_tmp, *_ = active.apply_residual_terms(f_base, t_rel, terms)
                                obs = make_obs("bestC_tmp", target_name, target_id, t_abs, t_rel, f_obs_tmp, f_geo_B_S1)
                                v = base.verify_claimed_identity(obs, f_geo_A_S1, threshold_95, threshold_99)
                                if v.score_A_rmse_hz < best_score:
                                    best_score = float(v.score_A_rmse_hz)
                                    best_u = u
                        assert best_u is not None
                        f_source = f_geo_B_S1
                        f_base = f_geo_B_S1 + best_u
                    elif strategy == "benign_A":
                        f_source = f_geo_A_S1
                        f_base = f_geo_A_S1
                    else:
                        f_source = f_geo_B_S1
                        f_base = f_geo_B_S1 + u_base[strategy]
                    f_obs, *_ = active.apply_residual_terms(f_base, t_rel, terms)
                    for window_mode in args.window_mode:
                        i0, i1, v = choose_window(
                            window_mode,
                            t_abs,
                            t_rel,
                            f_obs,
                            f_geo_A_S1,
                            f_source,
                            target_name,
                            target_id,
                            threshold_95,
                            threshold_99,
                            max(float(args.sliding_step_s), step_s),
                        )
                        accepted_score_k = bool(v.accepted_95 and k_min <= v.k_hat_hz_s <= k_max)
                        window_max_elev = max_elev_A
                        tri_decision = active.tri_state_decision(accepted_score_k, window_max_elev, args.elevation_min_deg)
                        rows.append(
                            {
                                "sequence_id": f"short_window_{seq_counter:06d}",
                                "target_sat": target_name,
                                "target_norad_id": target_id,
                                "attacker_sat": attacker_name if strategy != "benign_A" else target_name,
                                "attacker_norad_id": attacker_id if strategy != "benign_A" else target_id,
                                "attack_strategy": strategy,
                                "residual_mode": mode,
                                "station_id": "S1",
                                "window_mode": window_mode,
                                "window_start": str(t_abs[i0]),
                                "window_end": str(t_abs[i1 - 1]),
                                "window_duration_s": float(t_rel[i1 - 1] - t_rel[i0]) if i1 > i0 else 0.0,
                                "window_position_fraction": float(i0 / max(1, len(t_rel) - 1)),
                                "tri_decision": tri_decision,
                                "p95_accept": bool(v.accepted_95),
                                "score": float(v.score_A_rmse_hz),
                                "b_hat": float(v.b_hat_hz),
                                "k_hat": float(v.k_hat_hz_s),
                                "max_elevation": window_max_elev,
                                "threshold_95_hz": threshold_95,
                            }
                        )
                        seq_counter += 1

    eval_df = pd.DataFrame(rows)
    summary = build_summary(eval_df)
    for path, df in [(args.eval_output, eval_df), (args.summary_output, summary)]:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        print(f"wrote {path} rows={len(df)}")
    if not summary.empty:
        print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
