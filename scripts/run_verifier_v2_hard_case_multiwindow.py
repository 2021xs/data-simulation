#!/usr/bin/env python
"""Multi-window consistency test for selected verifier v2 hard cases."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from skyfield.api import load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_doppler_verifier_initial_experiments as base  # noqa: E402

ALTITUDE_DELTAS_KM = [-10, -7.5, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7.5, 10]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--selected-pairs", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_selected_pairs.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multiwindow_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv"))
    p.add_argument("--max-targets", type=int, default=20)
    p.add_argument("--num-sims-per-case", type=int, default=20)
    p.add_argument("--window-lengths", nargs="+", type=int, default=[30, 60, 120])
    p.add_argument("--num-windows", type=int, default=8)
    p.add_argument("--threshold-type", choices=["p95", "p99", "all"], default="all")
    p.add_argument("--seed", type=int, default=20260519)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def th_types(v: str) -> list[str]:
    return ["p95", "p99"] if v == "all" else [v]


def load_common(args):
    loader_args = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library, tle_file=args.tle_file, orbit_config=args.orbit_config, parameter_config=args.parameter_config, target_count=20)
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    return selection, library, orbit_cfg, ranges, tle, ts


def windows_for(t_rel: np.ndarray, length: int, n: int, rng: np.random.Generator) -> list[tuple[float, float]]:
    start_min, start_max = float(t_rel.min()), float(t_rel.max() - length)
    if start_max <= start_min:
        return [(float(t_rel.min()), float(t_rel.max()))]
    starts = rng.uniform(start_min, start_max, n)
    return [(float(s), float(s + length)) for s in starts]


def fit_window(y, f_geo, t_rel, start, end):
    mask = (t_rel >= start) & (t_rel <= end)
    fit = base.fit_bias_and_slope(y[mask], f_geo[mask], t_rel[mask])
    return fit, int(mask.sum())


def build_full_observations(args, selected, selection, library, orbit_cfg, ranges, tle, ts):
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    rng = np.random.default_rng(args.seed)
    needed = set(selected["sequence_id"].astype(str))
    out = {}
    counter = 1
    selected_targets = set(selected["target_sat_id"].astype(str))
    for _, target in selection.iterrows():
        tid = str(target["target_norad_id"])
        geo = base.target_geo_from_library(library, tid)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
        sat = tle[tid]["sat"]
        for dh in ALTITUDE_DELTAS_KM:
            f_geo_b = base.synthetic_same_plane_geo(sat, station, ts, times, freq, altitude_offset_km=float(dh), phase_offset_s=0.0)
            spec = dict(attack_type="same_plane_altitude_offset_fine", attack_variant=f"delta_h_{dh:+g}km", altitude_offset_km=float(dh), phase_offset_s=0.0, inclination_offset_deg=0.0, raan_offset_deg=0.0)
            for sample_id in range(1, 6):
                err = base.sample_error_params(ranges, rng)
                sid = f"alt_fine_{counter:06d}"
                counter += 1
                obs = base.build_attack_observation(sid, str(target["target_name"]), tid, geo, f_geo_b, spec, err, rng, sample_id, args.seed)
                if tid in selected_targets and sid in needed:
                    out[sid] = (geo, obs, f_geo_a)
    return out


def main() -> None:
    args = parse_args()
    if (args.sequence_output.exists() or args.summary_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    if not args.selected_pairs.exists():
        fail("selected pairs missing")
    selected = pd.read_csv(args.selected_pairs)
    selected = selected.head(9999)
    targets = set(selected["target_sat_id"].astype(str).drop_duplicates().head(args.max_targets))
    selected = selected[selected["target_sat_id"].astype(str).isin(targets)].copy()
    selection, library, orbit_cfg, ranges, tle, ts = load_common(args)
    full = build_full_observations(args, selected, selection, library, orbit_cfg, ranges, tle, ts)
    rng = np.random.default_rng(args.seed + 99)
    seq_rows = []
    agg_rows = []
    for tid in targets:
        target_sel = selected[selected["target_sat_id"].astype(str) == tid]
        geo = base.target_geo_from_library(library, tid)
        f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
        t_rel = geo["t_rel_s"].to_numpy(float)
        # Legitimate full observations for subwindow calibration and accept-rate reporting.
        legit_obs = []
        for i in range(1, args.num_sims_per_case + 1):
            err = base.sample_error_params(ranges, rng)
            legit_obs.append(base.build_legitimate_observation(f"mw_legit_{tid}_{i:03d}", str(target_sel["target_name"].iloc[0]), tid, geo, err, rng, i, args.seed))
        for length in args.window_lengths:
            wins = windows_for(t_rel, int(length), args.num_windows, rng)
            thresholds = {}
            k_ranges = {}
            for wid, (start, end) in enumerate(wins, 1):
                vals = []
                kvals = []
                for obs in legit_obs:
                    fit, npts = fit_window(obs.y_obs_hz, f_geo_a, t_rel, start, end)
                    vals.append(fit.score_rmse_hz)
                    kvals.append(fit.k_hat_hz_s)
                thresholds[wid] = {"p95": float(np.quantile(vals, 0.95)), "p99": float(np.quantile(vals, 0.99))}
                k_ranges[wid] = (float(np.quantile(kvals, 0.01)), float(np.quantile(kvals, 0.99)))
            for sample_type, items in [("legit", [(obs.sequence_id, obs, np.nan, "") for obs in legit_obs]), ("attack", [(str(r.sequence_id), full[str(r.sequence_id)][1], float(r.delta_h_km), str(r.attack_source_name)) for _, r in target_sel.iterrows() if str(r.sequence_id) in full])]:
                for sid, obs, dh, src in items:
                    per_rule = {th: [] for th in th_types(args.threshold_type)}
                    for wid, (start, end) in enumerate(wins, 1):
                        fit, npts = fit_window(obs.y_obs_hz, f_geo_a, t_rel, start, end)
                        klo, khi = k_ranges[wid]
                        for th in th_types(args.threshold_type):
                            threshold = thresholds[wid][th]
                            score_ok = fit.score_rmse_hz <= threshold
                            k_ok = klo <= fit.k_hat_hz_s <= khi
                            accepted = bool(score_ok and k_ok)
                            per_rule[th].append((fit.score_rmse_hz / threshold, accepted))
                            seq_rows.append(
                                dict(
                                    sequence_id=sid,
                                    target=f"{obs.claimed_target_name} / {tid}",
                                    attack_source=src,
                                    delta_h_km=dh,
                                    sample_type=sample_type,
                                    threshold_type=th,
                                    subwindow_id=wid,
                                    subwindow_start_offset_s=start,
                                    subwindow_end_offset_s=end,
                                    subwindow_length_s=length,
                                    score=fit.score_rmse_hz,
                                    threshold=threshold,
                                    normalized_score=fit.score_rmse_hz / threshold,
                                    b_hat=fit.b_hat_hz,
                                    k_hat=fit.k_hat_hz_s,
                                    accepted_score_only=score_ok,
                                    accepted_k_gate=accepted,
                                    num_points=npts,
                                )
                            )
                    for th, vals in per_rule.items():
                        norm = np.array([v[0] for v in vals])
                        acc = np.array([v[1] for v in vals])
                        rules = {
                            "all_windows_accept": bool(acc.all()),
                            "majority_windows_accept": bool(acc.mean() > 0.5),
                            "mean_normalized_score_accept": bool(norm.mean() <= 1.0 and acc.mean() > 0.5),
                            "max_normalized_score_accept": bool(norm.max() <= 1.0 and acc.all()),
                        }
                        for rule, accepted in rules.items():
                            agg_rows.append(dict(target=f"{obs.claimed_target_name} / {tid}", attack_source=src, delta_h_km=dh, sample_type=sample_type, threshold_type=th, window_length_s=length, aggregation_rule=rule, accepted=accepted))
    seq = pd.DataFrame(seq_rows)
    agg = pd.DataFrame(agg_rows)
    summ_rows = []
    for key, g in agg.groupby(["target", "attack_source", "delta_h_km", "window_length_s", "threshold_type", "aggregation_rule"], dropna=False):
        target, src, dh, length, th, rule = key
        legit = g[g["sample_type"] == "legit"]
        attack = g[g["sample_type"] == "attack"]
        summ_rows.append(dict(target=target, attack_source=src, delta_h_km=dh, window_length_s=length, threshold_type=th, aggregation_rule=rule, legit_total=len(legit), legit_accept_rate=float(legit["accepted"].mean()) if len(legit) else np.nan, attack_total=len(attack), attack_accept_rate=float(attack["accepted"].mean()) if len(attack) else np.nan, attack_reject_rate=1.0 - float(attack["accepted"].mean()) if len(attack) else np.nan, notes="subwindow thresholds and k ranges calibrated from legitimate subwindow samples"))
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    seq.to_csv(args.sequence_output, index=False)
    pd.DataFrame(summ_rows).to_csv(args.summary_output, index=False)
    print(f"wrote {args.sequence_output} rows={len(seq)}")
    print(f"wrote {args.summary_output} rows={len(summ_rows)}")


if __name__ == "__main__":
    main()
