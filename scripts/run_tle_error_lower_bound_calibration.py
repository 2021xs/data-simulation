#!/usr/bin/env python
"""TLE error lower-bound calibration and near-orbit perturbation sweep.

This first-pass runner checks whether the repository contains multi-epoch TLE
records for the same Starlink satellites.  If those records are unavailable, it
still runs a diagnostic along-track perturbation sweep, but does not report a
formal attack/error boundary.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_short_window_best_claim_first_pass as shortwin  # noqa: E402

C_MPS = 299_792_458.0
ERROR_POSITIONS = {"first", "middle", "last", "best_error"}
ATTACK_POSITIONS = {"first", "middle", "last", "best_attack"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--input-tle-history", type=Path, default=None)
    p.add_argument("--target-norad-ids", nargs="*", default=None)
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    p.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    p.add_argument("--max-sats", type=int, default=20)
    p.add_argument("--window-duration-s", nargs="+", default=["30", "45", "60", "90", "120", "180", "full"])
    p.add_argument(
        "--window-position",
        nargs="+",
        choices=["first", "middle", "last", "best_error", "best_attack"],
        default=["first", "middle", "last", "best_error", "best_attack"],
    )
    p.add_argument("--window-step-s", type=float, default=10.0)
    p.add_argument("--delta-km", nargs="+", type=float, default=[0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200])
    p.add_argument("--perturb-direction", nargs="+", choices=["along_pos", "along_neg"], default=["along_pos", "along_neg"])
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--freshness-aware", action="store_true")
    p.add_argument("--min-primary-pairs", type=int, default=30)
    p.add_argument("--tle-error-summary-output", type=Path, default=Path("outputs/metrics/tle_error_calibration_summary.csv"))
    p.add_argument("--tle-error-pair-output", type=Path, default=Path("outputs/datasets/tle_error_pair_scores.csv"))
    p.add_argument("--perturb-output", type=Path, default=Path("outputs/metrics/near_orbit_perturbation_sweep.csv"))
    p.add_argument("--min-delta-output", type=Path, default=Path("outputs/metrics/near_orbit_min_attack_delta.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/tle_error_and_near_orbit_lower_bound_summary.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures"))
    p.add_argument("--seed", type=int, default=20260610)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def epoch_sep_bin(hours: float) -> str:
    if hours <= 24.0:
        return "<=24h"
    if hours <= 72.0:
        return "<=72h"
    if hours <= 168.0:
        return "<=168h"
    return ">168h"


def freshness_bins(max_age_hours: float) -> list[str]:
    bins: list[str] = []
    if max_age_hours <= 6.0:
        bins.append("fresh_6h")
    if max_age_hours <= 12.0:
        bins.append("fresh_12h")
    if max_age_hours <= 24.0:
        bins.append("operational_24h")
    if max_age_hours <= 72.0:
        bins.append("stale_72h")
    bins.append("all")
    return bins


def choose_primary_band(error_summary: pd.DataFrame, min_pairs: int = 30) -> str:
    if error_summary.empty or "freshness_bin" not in error_summary.columns:
        return "not_available"
    for candidate in ["fresh_12h", "operational_24h"]:
        g = error_summary[error_summary["freshness_bin"].astype(str) == candidate]
        usable = g[(g["n_tle_pairs"] >= int(min_pairs)) & np.isfinite(g["tau_error_p95"])]
        if not usable.empty:
            return candidate
    return "not_available"


def parse_durations(values: list[str]) -> list[float | str]:
    durations: list[float | str] = []
    for value in values:
        if str(value).lower() in {"full", "full_pass"}:
            durations.append("full")
        else:
            durations.append(float(value))
    return durations


def output_paths(args: argparse.Namespace) -> list[Path]:
    return [
        args.tle_error_summary_output,
        args.tle_error_pair_output,
        args.perturb_output,
        args.min_delta_output,
        args.report_output,
    ]


def check_outputs(args: argparse.Namespace) -> None:
    existing = [str(p) for p in output_paths(args) if p.exists()]
    if existing and not args.overwrite:
        active.fail("outputs exist; add --overwrite: " + ", ".join(existing))
    if args.overwrite:
        for path in output_paths(args):
            if path.exists():
                path.unlink()


def append_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        pd.DataFrame(rows).to_csv(path, mode="a", index=False, header=not path.exists())
    elif columns and not path.exists():
        pd.DataFrame(columns=columns).to_csv(path, index=False)


def load_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, list[float]]]:
    common_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        thresholds=args.thresholds,
        legit_results=args.legit_results,
        max_targets=9999 if (args.input_tle_history or args.target_norad_ids) else args.max_sats,
    )
    selection, library, orbit_cfg, tle, _threshold_map, _k_map, ranges = active.load_common_inputs(common_args)
    if orbit_cfg.get("mode") != "controlled_starlink":
        active.fail("this runner only supports controlled_starlink mode")
    library = library.copy()
    library["target_norad_id"] = library["target_norad_id"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    if args.target_norad_ids:
        wanted = {str(x) for x in args.target_norad_ids}
        selection = selection[selection["target_norad_id"].astype(str).isin(wanted)].copy()
    elif args.input_tle_history:
        ts = load.timescale()
        history_records, _history_by_sat = parse_tle_records(args.input_tle_history, ts)
        _dedup_records, dedup_by_sat, _duplicate_count = deduplicate_tle_records(history_records)
        selection = selection[selection["target_norad_id"].astype(str).isin(set(dedup_by_sat))].copy()
    selection = selection.head(args.max_sats).copy()
    if selection.empty:
        active.fail("no selected targets remain after applying target/history filters")
    return selection, library, orbit_cfg, tle, ranges


def parse_tle_records(path: Path, ts: Any) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    lines = [line.rstrip("\n") for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    records: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
            i += 3
        elif i + 1 < len(lines) and lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            name, line1, line2 = "", lines[i].strip(), lines[i + 1].strip()
            i += 2
        else:
            i += 1
            continue
        sat_id = line1[2:7].strip()
        epoch = line1[18:32].strip()
        sat = EarthSatellite(line1, line2, name, ts)
        records.append({"sat_id": sat_id, "name": name, "line1": line1, "line2": line2, "epoch": epoch, "epoch_datetime": sat.epoch.utc_datetime(), "sat": sat})
    by_sat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_sat[record["sat_id"]].append(record)
    return records, by_sat


def deduplicate_tle_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], int]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_count = 0
    for record in records:
        key = (str(record["sat_id"]), str(record["epoch"]))
        if key in by_key:
            duplicate_count += 1
            continue
        by_key[key] = record
    deduped = sorted(by_key.values(), key=lambda r: (str(r["sat_id"]), r["epoch_datetime"]))
    by_sat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in deduped:
        by_sat[str(record["sat_id"])].append(record)
    return deduped, by_sat, duplicate_count


def target_geo(library: pd.DataFrame, sat_id: str) -> pd.DataFrame:
    rows = library[
        (library["target_norad_id"].astype(str) == str(sat_id))
        & (library["candidate_norad_id"].astype(str) == str(sat_id))
    ].copy()
    if rows.empty:
        active.fail(f"missing target self geometry in candidate library: {sat_id}")
    return rows.sort_values("t_rel_s").reset_index(drop=True)


def parse_times(values: pd.Series) -> list[datetime]:
    out: list[datetime] = []
    for value in values.astype(str):
        out.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
    return out


def fixed_window(t_rel: np.ndarray, duration: float | str, position: str) -> dict[str, Any]:
    if duration == "full":
        mask = np.ones(len(t_rel), dtype=bool)
        return {"window_duration_s": "full", "window_position": "full_pass", "window_start": float(t_rel[0]), "window_end": float(t_rel[-1]), "mask": mask}
    wins = shortwin.fixed_windows(t_rel, float(duration), [position])
    if not wins:
        active.fail(f"no fixed window: duration={duration}, position={position}")
    w = wins[0]
    return {
        "window_duration_s": float(duration),
        "window_position": position,
        "window_start": float(w["window_start"]),
        "window_end": float(w["window_end"]),
        "mask": w["mask"],
    }


def all_windows(
    t_rel: np.ndarray,
    duration: float | str,
    requested_positions: set[str],
    selector: str,
    score_fn: Any,
    step_s: float,
) -> list[dict[str, Any]]:
    if duration == "full":
        return [fixed_window(t_rel, duration, "full_pass")]
    windows: list[dict[str, Any]] = []
    for pos in ["first", "middle", "last"]:
        if pos in requested_positions:
            windows.append(fixed_window(t_rel, duration, pos))
    if selector in requested_positions:
        best: dict[str, Any] | None = None
        best_score = -np.inf if selector == "best_error" else np.inf
        for w in shortwin.sliding_windows(t_rel, float(duration), float(step_s)):
            value = float(score_fn(w["mask"]))
            if (selector == "best_error" and value > best_score) or (selector == "best_attack" and value < best_score):
                best_score = value
                best = {
                    "window_duration_s": float(duration),
                    "window_position": selector,
                    "window_start": float(w["window_start"]),
                    "window_end": float(w["window_end"]),
                    "mask": w["mask"],
                }
        if best is not None:
            windows.append(best)
    return windows


def fit_delta(reference_hz: np.ndarray, comparison_hz: np.ndarray, t_rel: np.ndarray, mask: np.ndarray) -> base.FitResult:
    return base.fit_bias_and_slope(comparison_hz[mask], reference_hz[mask], t_rel[mask])


def rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(values, dtype=float) ** 2)))


def geocentric_for_sat(sat: Any, station: Any, ts: Any, times: list[datetime], freq_hz: float, step_s: float) -> dict[str, np.ndarray]:
    sky_t = ts.from_datetimes(times)
    sat_at = sat.at(sky_t)
    station_at = station.at(sky_t)
    sat_pos_km = sat_at.position.km.T
    sat_vel_kms = sat_at.velocity.km_per_s.T
    station_pos_km = station_at.position.km.T
    rel_km = sat_pos_km - station_pos_km
    range_km = np.linalg.norm(rel_km, axis=1)
    range_m = range_km * 1000.0
    range_rate_mps = np.gradient(range_m, step_s)
    f_geo_hz = freq_hz - freq_hz * range_rate_mps / C_MPS
    elevation = (sat - station).at(sky_t).altaz()[0].degrees
    return {
        "sat_pos_km": sat_pos_km,
        "sat_vel_kms": sat_vel_kms,
        "station_pos_km": station_pos_km,
        "range_m": range_m,
        "range_rate_mps": range_rate_mps,
        "f_geo_hz": f_geo_hz,
        "elevation_deg": np.asarray(elevation, dtype=float),
    }


def perturb_along_track(base_geo: dict[str, np.ndarray], freq_hz: float, step_s: float, delta_km: float, direction: str) -> dict[str, np.ndarray]:
    sign = 1.0 if direction == "along_pos" else -1.0
    vel = base_geo["sat_vel_kms"]
    norm = np.linalg.norm(vel, axis=1)
    unit = vel / np.maximum(norm[:, None], 1e-12)
    pert_pos = base_geo["sat_pos_km"] + sign * float(delta_km) * unit
    rel_km = pert_pos - base_geo["station_pos_km"]
    range_km = np.linalg.norm(rel_km, axis=1)
    range_m = range_km * 1000.0
    range_rate_mps = np.gradient(range_m, step_s)
    f_geo_hz = freq_hz - freq_hz * range_rate_mps / C_MPS
    return {"range_m": range_m, "range_rate_mps": range_rate_mps, "f_geo_hz": f_geo_hz}


def evaluate_tle_pair(
    sat_id: str,
    ref_record: dict[str, Any],
    alt_record: dict[str, Any],
    times: list[datetime],
    t_rel: np.ndarray,
    freq_hz: float,
    step_s: float,
    station: Any,
    ts: Any,
    durations: list[float | str],
    positions: set[str],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    ref = geocentric_for_sat(ref_record["sat"], station, ts, times, freq_hz, step_s)
    alt = geocentric_for_sat(alt_record["sat"], station, ts, times, freq_hz, step_s)
    sep_hours = abs((alt_record["epoch_datetime"] - ref_record["epoch_datetime"]).total_seconds()) / 3600.0
    sep_bin = epoch_sep_bin(sep_hours)
    rows: list[dict[str, Any]] = []
    for duration in durations:
        def score(mask: np.ndarray) -> float:
            fit = fit_delta(ref["f_geo_hz"], alt["f_geo_hz"], t_rel, mask)
            return fit.score_rmse_hz

        for window in all_windows(t_rel, duration, positions, "best_error", score, args.window_step_s):
            mask = window["mask"]
            fit = fit_delta(ref["f_geo_hz"], alt["f_geo_hz"], t_rel, mask)
            pos_diff = np.linalg.norm(ref["sat_pos_km"][mask] - alt["sat_pos_km"][mask], axis=1)
            vel_diff = np.linalg.norm(ref["sat_vel_kms"][mask] - alt["sat_vel_kms"][mask], axis=1) * 1000.0
            center_rel_s = 0.5 * (float(window["window_start"]) + float(window["window_end"]))
            window_center_time = times[0] + timedelta(seconds=center_rel_s)
            ref_age_h = abs((window_center_time - ref_record["epoch_datetime"]).total_seconds()) / 3600.0
            alt_age_h = abs((window_center_time - alt_record["epoch_datetime"]).total_seconds()) / 3600.0
            min_age_h = min(ref_age_h, alt_age_h)
            max_age_h = max(ref_age_h, alt_age_h)
            rows.append(
                {
                    "sat_id": sat_id,
                    "tle_ref_epoch": ref_record["epoch"],
                    "tle_alt_epoch": alt_record["epoch"],
                    "window_center_time": window_center_time.isoformat().replace("+00:00", "Z"),
                    "ref_age_to_window_hours": float(ref_age_h),
                    "alt_age_to_window_hours": float(alt_age_h),
                    "min_age_to_window_hours": float(min_age_h),
                    "max_age_to_window_hours": float(max_age_h),
                    "freshness_bin": "|".join(freshness_bins(max_age_h)),
                    "epoch_sep_hours": float(sep_hours),
                    "epoch_sep_bin": sep_bin,
                    "window_duration_s": window["window_duration_s"],
                    "window_position": window["window_position"],
                    "window_start": window["window_start"],
                    "window_end": window["window_end"],
                    "raw_doppler_rmse": rmse(alt["f_geo_hz"][mask] - ref["f_geo_hz"][mask]),
                    "residual_rmse_after_bk": fit.score_rmse_hz,
                    "position_diff_km_median": float(np.median(pos_diff)),
                    "position_diff_km_max": float(np.max(pos_diff)),
                    "velocity_diff_mps_median": float(np.median(vel_diff)),
                    "velocity_diff_mps_max": float(np.max(vel_diff)),
                    "b_hat": fit.b_hat_hz,
                    "k_hat": fit.k_hat_hz_s,
                    "num_samples": int(mask.sum()),
                }
            )
    return rows


def select_epoch_pairs(records: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    ordered = sorted(records, key=lambda r: r["epoch_datetime"])
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for i, ref in enumerate(ordered[:-1]):
        chosen: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for alt in ordered[i + 1 :]:
            sep_hours = abs((alt["epoch_datetime"] - ref["epoch_datetime"]).total_seconds()) / 3600.0
            bin_name = epoch_sep_bin(sep_hours)
            if bin_name not in chosen:
                chosen[bin_name] = (ref, alt)
            if len(chosen) == 4:
                break
        for pair in chosen.values():
            key = (str(pair[0]["epoch"]), str(pair[1]["epoch"]))
            if key not in seen:
                pairs.append(pair)
                seen.add(key)
    return pairs


def evaluate_perturbations(
    sat_row: Any,
    geo_df: pd.DataFrame,
    station: Any,
    ts: Any,
    durations: list[float | str],
    positions: set[str],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    sat_id = str(sat_row.target_norad_id)
    times = parse_times(geo_df["t_abs_utc"])
    t_rel = geo_df["t_rel_s"].to_numpy(float)
    f_ref = geo_df["f_geo_candidate_hz"].to_numpy(float)
    freq_hz = float(geo_df["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo_df.columns else float(np.median(f_ref))
    step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
    # Use the already-loaded satellite from the self geometry source.
    base_sat = sat_row._tle_sat
    base_geo = geocentric_for_sat(base_sat, station, ts, times, freq_hz, step_s)
    rows: list[dict[str, Any]] = []
    for delta in args.delta_km:
        for direction in args.perturb_direction:
            pert = perturb_along_track(base_geo, freq_hz, step_s, float(delta), direction)
            for duration in durations:
                def score(mask: np.ndarray) -> float:
                    fit = fit_delta(f_ref, pert["f_geo_hz"], t_rel, mask)
                    return fit.score_rmse_hz

                for window in all_windows(t_rel, duration, positions, "best_attack", score, args.window_step_s):
                    mask = window["mask"]
                    fit = fit_delta(f_ref, pert["f_geo_hz"], t_rel, mask)
                    rows.append(
                        {
                            "sat_id": sat_id,
                            "sat_name": str(sat_row.target_name),
                            "delta_km": float(delta),
                            "direction": direction,
                            "window_duration_s": window["window_duration_s"],
                            "window_position": window["window_position"],
                            "window_start": window["window_start"],
                            "window_end": window["window_end"],
                            "perturb_raw_doppler_rmse": rmse(pert["f_geo_hz"][mask] - f_ref[mask]),
                            "perturb_residual_rmse_after_bk": fit.score_rmse_hz,
                            "b_hat": fit.b_hat_hz,
                            "k_hat": fit.k_hat_hz_s,
                            "num_samples": int(mask.sum()),
                            "is_above_tau_p95": False,
                            "is_above_tau_p99": False,
                            "tau_error_p95": np.nan,
                            "tau_error_p99": np.nan,
                            "tle_error_available": False,
                            "perturbation_model": "instantaneous_along_track_position_offset",
                        }
                    )
    return rows


def summarize_tle_errors(pair_df: pd.DataFrame, durations: list[float | str], requested_positions: set[str], tle_error_available: bool) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    positions = [p for p in ["first", "middle", "last", "best_error"] if p in requested_positions]
    freshness_order = ["fresh_6h", "fresh_12h", "operational_24h", "stale_72h", "all"]
    epoch_bins = ["<=24h", "<=72h", "<=168h", ">168h", "all_pairs"]
    expanded = pd.DataFrame()
    if not pair_df.empty:
        expanded = pair_df.copy()
        expanded["freshness_bin"] = expanded["freshness_bin"].astype(str).str.split("|")
        expanded = expanded.explode("freshness_bin")
    for duration in durations:
        dur_key = "full" if duration == "full" else float(duration)
        dur_positions = ["full_pass"] if duration == "full" else positions
        for position in dur_positions:
            for freshness_bin in freshness_order:
                for sep_bin in epoch_bins:
                    if expanded.empty:
                        g = pd.DataFrame()
                    else:
                        base_g = expanded[
                            (expanded["window_duration_s"].astype(str) == str(dur_key))
                            & (expanded["window_position"].astype(str) == position)
                            & (expanded["freshness_bin"].astype(str) == freshness_bin)
                        ]
                        g = base_g if sep_bin == "all_pairs" else base_g[base_g["epoch_sep_bin"].astype(str) == sep_bin]
                    rows.append(
                        {
                            "window_duration_s": dur_key,
                            "window_position": position,
                            "freshness_bin": freshness_bin,
                            "epoch_sep_bin": sep_bin,
                            "n_tle_pairs": int(len(g)),
                            "n_sats": int(g["sat_id"].astype(str).nunique()) if len(g) else 0,
                            "tau_error_p50": float(g["residual_rmse_after_bk"].quantile(0.50)) if len(g) else np.nan,
                            "tau_error_p95": float(g["residual_rmse_after_bk"].quantile(0.95)) if len(g) else np.nan,
                            "tau_error_p99": float(g["residual_rmse_after_bk"].quantile(0.99)) if len(g) else np.nan,
                            "raw_error_p50": float(g["raw_doppler_rmse"].quantile(0.50)) if len(g) else np.nan,
                            "raw_error_p95": float(g["raw_doppler_rmse"].quantile(0.95)) if len(g) else np.nan,
                            "raw_error_p99": float(g["raw_doppler_rmse"].quantile(0.99)) if len(g) else np.nan,
                            "position_diff_km_p50": float(g["position_diff_km_median"].quantile(0.50)) if len(g) else np.nan,
                            "position_diff_km_p95": float(g["position_diff_km_median"].quantile(0.95)) if len(g) else np.nan,
                            "velocity_diff_mps_p50": float(g["velocity_diff_mps_median"].quantile(0.50)) if len(g) else np.nan,
                            "velocity_diff_mps_p95": float(g["velocity_diff_mps_median"].quantile(0.95)) if len(g) else np.nan,
                            "tle_error_available": bool(tle_error_available and len(g)),
                        }
                    )
    return pd.DataFrame(rows)


def tau_lookup(error_summary: pd.DataFrame, duration: Any, position: str, freshness_bin: str = "fresh_12h", sep_bin: str = "all_pairs") -> tuple[float, float]:
    rows = error_summary[
        (error_summary["window_duration_s"].astype(str) == str(duration))
        & (error_summary["window_position"].astype(str) == str(position))
        & (error_summary["freshness_bin"].astype(str) == freshness_bin)
        & (error_summary["epoch_sep_bin"].astype(str) == sep_bin)
    ]
    if rows.empty:
        return np.nan, np.nan
    return float(rows["tau_error_p95"].iloc[0]), float(rows["tau_error_p99"].iloc[0])


def annotate_perturbation_crossing(perturb_df: pd.DataFrame, error_summary: pd.DataFrame, freshness_bin: str, sep_bin: str = "all_pairs") -> pd.DataFrame:
    if perturb_df.empty:
        return perturb_df
    out = perturb_df.copy()
    tau95_values: list[float] = []
    tau99_values: list[float] = []
    for row in out.itertuples(index=False):
        tau95, tau99 = tau_lookup(error_summary, row.window_duration_s, str(row.window_position), freshness_bin, sep_bin)
        tau95_values.append(tau95)
        tau99_values.append(tau99)
    out["tau_error_p95"] = tau95_values
    out["tau_error_p99"] = tau99_values
    out["is_above_tau_p95"] = out["perturb_residual_rmse_after_bk"] > out["tau_error_p95"]
    out["is_above_tau_p99"] = out["perturb_residual_rmse_after_bk"] > out["tau_error_p99"]
    out["tle_error_available"] = np.isfinite(out["tau_error_p95"]) | np.isfinite(out["tau_error_p99"])
    out["freshness_bin_used_for_tau"] = freshness_bin
    out["epoch_sep_bin_used_for_tau"] = sep_bin
    out["primary_error_band_source"] = freshness_bin if freshness_bin != "not_available" else "not_available"
    return out


def build_min_delta(perturb_df: pd.DataFrame, error_summary: pd.DataFrame, tle_error_available: bool, freshness_bin: str, sep_bin: str = "all_pairs") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (sat_id, direction, duration, position), g in perturb_df.groupby(["sat_id", "direction", "window_duration_s", "window_position"], sort=False):
        tau95, tau99 = tau_lookup(error_summary, duration, str(position), freshness_bin, sep_bin)
        sorted_g = g.sort_values("delta_km")
        if tle_error_available and np.isfinite(tau95):
            above95 = sorted_g[sorted_g["perturb_residual_rmse_after_bk"] > tau95]
            d95 = float(above95["delta_km"].iloc[0]) if len(above95) else np.nan
            crossed95 = bool(len(above95))
        else:
            d95 = np.nan
            crossed95 = False
        if tle_error_available and np.isfinite(tau99):
            above99 = sorted_g[sorted_g["perturb_residual_rmse_after_bk"] > tau99]
            d99 = float(above99["delta_km"].iloc[0]) if len(above99) else np.nan
            crossed99 = bool(len(above99))
        else:
            d99 = np.nan
            crossed99 = False
        rows.append(
            {
                "sat_id": sat_id,
                "direction": direction,
                "window_duration_s": duration,
                "window_position": position,
                "primary_error_band_source": freshness_bin if freshness_bin != "not_available" else "not_available",
                "freshness_bin_used_for_tau": freshness_bin,
                "epoch_sep_bin_used_for_tau": sep_bin,
                "delta_min_p95_km": d95,
                "delta_min_p99_km": d99,
                "crossed_tau_p95": crossed95,
                "crossed_tau_p99": crossed99,
                "tau_error_p95": tau95,
                "tau_error_p99": tau99,
                "tle_error_available": bool(tle_error_available),
                "diagnostic_delta_sweep_only": bool(not tle_error_available),
            }
        )
    return pd.DataFrame(rows)


def plot_error_band(error_summary: pd.DataFrame, out_dir: Path) -> Path | None:
    df = error_summary[
        (error_summary["tle_error_available"].astype(bool))
        & (error_summary["window_position"].astype(str).isin(["middle", "full_pass"]))
        & (error_summary["freshness_bin"].astype(str).isin(["fresh_6h", "fresh_12h", "operational_24h", "stale_72h", "all"]))
        & (error_summary["epoch_sep_bin"].astype(str) == "all_pairs")
    ].copy()
    df = df[df["window_duration_s"].astype(str) != "full"]
    if df.empty:
        return None
    df["duration_float"] = df["window_duration_s"].astype(float)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tle_error_band_by_freshness.png"
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for sep_bin, g in df.groupby("freshness_bin", sort=False):
        gg = g.sort_values("duration_float")
        ax.plot(gg["duration_float"], gg["tau_error_p95"], marker="o", label=f"{sep_bin} p95")
        ax.plot(gg["duration_float"], gg["tau_error_p99"], marker="x", linestyle="--", label=f"{sep_bin} p99")
    ax.set_xlabel("Window duration (s)")
    ax.set_ylabel("Residual RMSE after b/k (Hz)")
    ax.set_title("TLE error band by window")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def plot_delta_curve(perturb_df: pd.DataFrame, out_dir: Path) -> Path | None:
    if perturb_df.empty:
        return None
    df = perturb_df[perturb_df["window_position"].astype(str).isin(["middle", "best_attack", "full_pass"])].copy()
    df = df[df["window_duration_s"].astype(str).isin(["30.0", "60.0", "120.0", "full"])]
    if df.empty:
        df = perturb_df.copy()
    summary = (
        df.groupby(["window_duration_s", "delta_km"], sort=False)["perturb_residual_rmse_after_bk"]
        .median()
        .reset_index()
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "near_orbit_delta_score_curve_fresh_band.png"
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for duration, g in summary.groupby("window_duration_s", sort=False):
        gg = g.sort_values("delta_km")
        ax.plot(gg["delta_km"], gg["perturb_residual_rmse_after_bk"], marker="o", label=str(duration))
    ax.set_xscale("log")
    ax.set_xlabel("Along-track diagnostic delta (km)")
    ax.set_ylabel("Median residual RMSE after b/k (Hz)")
    ax.set_title("Near-orbit diagnostic perturbation sweep")
    ax.legend(title="duration")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def plot_min_delta(min_df: pd.DataFrame, out_dir: Path) -> Path | None:
    df = min_df[(min_df["tle_error_available"].astype(bool)) & (min_df["window_position"].astype(str).isin(["middle", "full_pass"]))].copy()
    df = df[df["window_duration_s"].astype(str) != "full"]
    if df.empty:
        return None
    df["duration_float"] = df["window_duration_s"].astype(float)
    summary = df.groupby("duration_float", sort=True)[["delta_min_p95_km", "delta_min_p99_km"]].median().reset_index()
    if summary[["delta_min_p95_km", "delta_min_p99_km"]].dropna(how="all").empty:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "min_attack_delta_by_window_fresh_band.png"
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(summary["duration_float"], summary["delta_min_p95_km"], marker="o", label="p95")
    ax.plot(summary["duration_float"], summary["delta_min_p99_km"], marker="o", label="p99")
    ax.set_xlabel("Window duration (s)")
    ax.set_ylabel("Median minimum delta (km)")
    ax.set_title("Minimum near-orbit perturbation above TLE error band")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def pivot_error_table(error_summary: pd.DataFrame) -> pd.DataFrame:
    if error_summary.empty:
        return pd.DataFrame()
    keep = error_summary[error_summary["window_position"].astype(str).isin(["middle", "full_pass"])].copy()
    keep = keep[keep["epoch_sep_bin"].astype(str).isin(["<=24h", "<=72h", "all_pairs"])]
    if keep.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (duration, position), g in keep.groupby(["window_duration_s", "window_position"], sort=False):
        row: dict[str, Any] = {"window_duration_s": duration, "window_position": position}
        for sep in ["<=24h", "<=72h", "all_pairs"]:
            gg = g[g["epoch_sep_bin"].astype(str) == sep]
            suffix = "24h" if sep == "<=24h" else "72h" if sep == "<=72h" else "all"
            row[f"tau_error_p95_{suffix}"] = float(gg["tau_error_p95"].iloc[0]) if len(gg) else np.nan
            row[f"tau_error_p99_{suffix}"] = float(gg["tau_error_p99"].iloc[0]) if len(gg) else np.nan
            row[f"n_pairs_{suffix}"] = int(gg["n_tle_pairs"].iloc[0]) if len(gg) else 0
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_min_delta(min_df: pd.DataFrame) -> pd.DataFrame:
    if min_df.empty:
        return pd.DataFrame()
    keep = min_df[min_df["window_position"].astype(str).isin(["middle", "best_attack", "full_pass"])].copy()
    rows: list[dict[str, Any]] = []
    for (duration, position), g in keep.groupby(["window_duration_s", "window_position"], sort=False):
        rows.append(
            {
                "window_duration_s": duration,
                "window_position": position,
                "n": int(len(g)),
                "delta_min_p95_median_km": float(g["delta_min_p95_km"].median()) if g["crossed_tau_p95"].any() else np.nan,
                "delta_min_p99_median_km": float(g["delta_min_p99_km"].median()) if g["crossed_tau_p99"].any() else np.nan,
                "crossed_tau_p95_count": int(g["crossed_tau_p95"].astype(bool).sum()),
                "crossed_tau_p99_count": int(g["crossed_tau_p99"].astype(bool).sum()),
            }
        )
    return pd.DataFrame(rows)


def write_report(
    args: argparse.Namespace,
    tle_records: list[dict[str, Any]],
    multi_epoch_by_sat: dict[str, list[dict[str, Any]]],
    selection: pd.DataFrame,
    error_summary: pd.DataFrame,
    perturb_df: pd.DataFrame,
    min_df: pd.DataFrame,
    figures: list[Path],
    duplicate_epoch_records: int = 0,
) -> None:
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    tle_error_available = any(len(v) > 1 for v in multi_epoch_by_sat.values())
    visible_multi = {k: v for k, v in multi_epoch_by_sat.items() if len(v) > 1}
    tle_source = args.input_tle_history or args.tle_file
    error_pivot = pivot_error_table(error_summary)
    min_summary = summarize_min_delta(min_df)
    sep_counts = (
        error_summary.groupby("epoch_sep_bin", sort=False)["n_tle_pairs"].max().reset_index()
        if not error_summary.empty
        else pd.DataFrame()
    )
    perturb_window = (
        perturb_df[perturb_df["window_position"].astype(str).isin(["best_attack", "middle", "full_pass"])]
        .groupby(["window_duration_s", "window_position"], sort=False)["perturb_residual_rmse_after_bk"]
        .agg(["count", "median", "min", "max"])
        .reset_index()
        if not perturb_df.empty
        else pd.DataFrame()
    )
    delta_summary = (
        perturb_df.groupby("delta_km", sort=True)["perturb_residual_rmse_after_bk"]
        .agg(["count", "median", "min", "max"])
        .reset_index()
        if not perturb_df.empty
        else pd.DataFrame()
    )
    fig_text = "\n".join(f"- `{p}`" for p in figures) if figures else "- ?????"
    text = f"""# TLE Error Calibration ? Near-Orbit Minimum Delta ??

?????{datetime.now().isoformat(timespec="seconds")}

## 1. ?????

multi-epoch TLE ???????? Space-Track GP_History ???? TLE-to-TLE error proxy????????????????????????? near-orbit attacker?

- TLE history source?`{tle_source}`
- latest TLE source?`{args.tle_file}`
- TLE records after dedup?{len(tle_records)}
- duplicate `(NORAD, epoch)` records removed?{duplicate_epoch_records}
- unique NORAD IDs?{len(multi_epoch_by_sat)}
- multi-epoch NORAD IDs?{len(visible_multi)}
- selected targets?{len(selection)}
- tle_error_available?`{str(tle_error_available).lower()}`

TLE-to-TLE ??????????????? TLE / SGP4 ????????? proxy?`<=72h` ????? primary error band?`all_pairs` ??? stale-TLE sensitivity?????????????

## 2. Epoch Separation Bins

{sep_counts.to_markdown(index=False) if not sep_counts.empty else "? TLE pair?"}

## 3. TLE Error Calibration

????? error band?

{error_pivot.to_markdown(index=False) if not error_pivot.empty else "? error band?"}

??????

- `outputs/datasets/tle_error_pair_scores.csv`
- `outputs/metrics/tle_error_calibration_summary.csv`

## 4. Near-Orbit Perturbation Sweep

?????? diagnostic ????????????? A ????????? `delta_km`????? station range-rate ??? Doppler??? A ??? Doppler ?? claimed reference ????? b/k????????????????????????????????????

????????

{perturb_window.to_markdown(index=False) if not perturb_window.empty else "? perturbation sweep?"}

? delta ???

{delta_summary.to_markdown(index=False) if not delta_summary.empty else "? delta summary?"}

## 5. Minimum Attack Delta

`near_orbit_min_attack_delta.csv` ?? primary `<=72h` error band ???????? primary tau band ??????????? near-orbit attacker ???

{min_summary.to_markdown(index=False) if not min_summary.empty else "? min delta summary?"}

?? `crossed_tau_p95_count` ? `crossed_tau_p99_count` ?? `n`????? sat/direction ??? delta grid ????????? tau????? `delta_min_*` ???????????? delta?

## 6. ??

{fig_text}

## 7. ?????

- mild near-orbit attack?? primary `delta_min_p95` ???????????? TLE error band ????
- moderate near-orbit attack??? primary `delta_min_p99` ??? `delta_min_p99` ???
- strong near-orbit attack??????? `delta_min_p99`????? same-shell / near-orbit assumption ????

?????????? attack runner ???????????????????????????????????
"""
    args.report_output.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    check_outputs(args)
    durations = parse_durations(args.window_duration_s)
    requested_positions = set(args.window_position)
    selection, library, orbit_cfg, tle, _ranges = load_inputs(args)
    ts = load.timescale()
    station_cfg = orbit_cfg["station"]
    station = orbit_builder.wgs84.latlon(
        float(station_cfg["lat_deg"]),
        float(station_cfg["lon_deg"]),
        elevation_m=float(station_cfg["alt_m"]),
    )

    history_path = args.input_tle_history or args.tle_file
    if not history_path.exists():
        active.fail(f"missing input TLE history: {history_path}")
    tle_records, by_sat = parse_tle_records(history_path, ts)
    tle_records_dedup, by_sat_dedup, duplicate_epoch_records = deduplicate_tle_records(tle_records)
    by_sat = by_sat_dedup
    multi_epoch_by_sat = {sat_id: records for sat_id, records in by_sat.items() if len({r["epoch"] for r in records}) > 1}
    tle_error_available = bool(multi_epoch_by_sat)

    pair_columns = [
        "sat_id",
        "tle_ref_epoch",
        "tle_alt_epoch",
        "window_center_time",
        "ref_age_to_window_hours",
        "alt_age_to_window_hours",
        "min_age_to_window_hours",
        "max_age_to_window_hours",
        "freshness_bin",
        "epoch_sep_hours",
        "epoch_sep_bin",
        "window_duration_s",
        "window_position",
        "window_start",
        "window_end",
        "raw_doppler_rmse",
        "residual_rmse_after_bk",
        "position_diff_km_median",
        "position_diff_km_max",
        "velocity_diff_mps_median",
        "velocity_diff_mps_max",
        "b_hat",
        "k_hat",
        "num_samples",
    ]
    perturb_columns = [
        "sat_id",
        "sat_name",
        "delta_km",
        "direction",
        "window_duration_s",
        "window_position",
        "window_start",
        "window_end",
        "perturb_raw_doppler_rmse",
        "perturb_residual_rmse_after_bk",
        "b_hat",
        "k_hat",
        "num_samples",
        "is_above_tau_p95",
        "is_above_tau_p99",
        "tau_error_p95",
        "tau_error_p99",
        "tle_error_available",
        "freshness_bin_used_for_tau",
        "epoch_sep_bin_used_for_tau",
        "primary_error_band_source",
        "perturbation_model",
    ]

    tle_pair_rows: list[dict[str, Any]] = []
    if tle_error_available:
        for row in selection.itertuples(index=False):
            sat_id = str(row.target_norad_id)
            records = by_sat.get(sat_id, [])
            unique_records = sorted(records, key=lambda r: r["epoch_datetime"])
            if len(unique_records) < 2:
                continue
            geo = target_geo(library, sat_id)
            times = parse_times(geo["t_abs_utc"])
            t_rel = geo["t_rel_s"].to_numpy(float)
            freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else float(np.median(geo["f_geo_candidate_hz"]))
            step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
            for ref, alt in select_epoch_pairs(unique_records):
                tle_pair_rows.extend(
                    evaluate_tle_pair(
                        sat_id,
                        ref,
                        alt,
                        times,
                        t_rel,
                        freq_hz,
                        step_s,
                        station,
                        ts,
                        durations,
                        requested_positions & ERROR_POSITIONS,
                        args,
                    )
                )
    append_csv(args.tle_error_pair_output, tle_pair_rows, pair_columns)
    tle_pair_df = pd.DataFrame(tle_pair_rows, columns=pair_columns)
    error_summary = summarize_tle_errors(tle_pair_df, durations, requested_positions & ERROR_POSITIONS, tle_error_available)
    error_summary.to_csv(args.tle_error_summary_output, index=False)
    primary_band = choose_primary_band(error_summary, args.min_primary_pairs)

    perturb_rows: list[dict[str, Any]] = []
    for row in selection.itertuples(index=False):
        sat_id = str(row.target_norad_id)
        if sat_id not in tle:
            active.fail(f"target missing in TLE dict: {sat_id}")
        geo = target_geo(library, sat_id)
        row_dict = row._asdict()
        row_dict["_tle_sat"] = tle[sat_id]["sat"]
        row_ns = SimpleNamespace(**row_dict)
        perturb_rows.extend(evaluate_perturbations(row_ns, geo, station, ts, durations, requested_positions & ATTACK_POSITIONS, args))
        append_csv(args.perturb_output, perturb_rows, perturb_columns)
        perturb_rows = []

    perturb_df = pd.read_csv(args.perturb_output) if args.perturb_output.exists() else pd.DataFrame(columns=perturb_columns)
    perturb_df = annotate_perturbation_crossing(perturb_df, error_summary, primary_band, "all_pairs")
    perturb_df.to_csv(args.perturb_output, index=False)
    min_df = build_min_delta(perturb_df, error_summary, tle_error_available and primary_band != "not_available", primary_band, "all_pairs")
    min_df.to_csv(args.min_delta_output, index=False)

    figures: list[Path] = []
    for fig in [plot_error_band(error_summary, args.figures_dir), plot_delta_curve(perturb_df, args.figures_dir), plot_min_delta(min_df, args.figures_dir)]:
        if fig is not None:
            figures.append(fig)

    write_report(args, tle_records_dedup, by_sat, selection, error_summary, perturb_df, min_df, figures, duplicate_epoch_records)
    print(f"TLE records: {len(tle_records)}")
    print(f"TLE records after dedup: {len(tle_records_dedup)}")
    print(f"Duplicate (NORAD, epoch) records removed: {duplicate_epoch_records}")
    print(f"Unique NORAD IDs: {len(by_sat)}")
    print(f"Multi-epoch NORAD IDs: {len(multi_epoch_by_sat)}")
    print(f"tle_error_available={tle_error_available}")
    print(f"primary_error_band_source={primary_band}")
    print(f"Wrote {len(tle_pair_df)} TLE error rows -> {args.tle_error_pair_output}")
    print(f"Wrote {len(perturb_df)} perturbation rows -> {args.perturb_output}")
    print(f"Wrote report -> {args.report_output}")


if __name__ == "__main__":
    main()
