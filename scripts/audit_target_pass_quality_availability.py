#!/usr/bin/env python
"""Audit target pass-quality availability for verifier v3."""

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
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--start-utc", default=None)
    p.add_argument("--duration-days", nargs="+", type=int, default=[7, 14, 30])
    p.add_argument("--target-limit", type=int, default=None)
    p.add_argument("--min-elevation-deg", type=float, default=None)
    p.add_argument("--scan-step-s", type=float, default=None)
    p.add_argument("--high-quality-elevation-deg", type=float, default=20.0)
    p.add_argument("--medium-elevation-deg", type=float, default=40.0)
    p.add_argument("--readily-hours", type=float, default=24.0)
    p.add_argument("--output", type=Path, default=Path("outputs/metrics/target_pass_quality_availability.csv"))
    p.add_argument("--pass-detail-output", type=Path, default=Path("outputs/metrics/target_pass_quality_availability_pass_detail.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/target_pass_quality_availability_summary.csv"))
    p.add_argument("--bin-summary-output", type=Path, default=Path("outputs/metrics/target_pass_quality_bin_summary.csv"))
    p.add_argument("--only-low-output", type=Path, default=Path("outputs/metrics/target_pass_quality_only_low_targets.csv"))
    p.add_argument("--delayed-output", type=Path, default=Path("outputs/metrics/target_pass_quality_delayed_targets.csv"))
    p.add_argument("--readily-output", type=Path, default=Path("outputs/metrics/target_pass_quality_readily_authenticatable_targets.csv"))
    p.add_argument("--output-suffix", default="")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)


def with_suffix(path: Path, suffix: str) -> Path:
    if not suffix:
        return path
    clean = suffix.strip("_")
    return path.with_name(f"{path.stem}_{clean}{path.suffix}")


def elevation_bin(max_el: float, high_quality_min: float, high_min: float) -> str:
    if max_el < high_quality_min:
        return "low"
    if max_el < high_min:
        return "medium"
    return "high"


def load_common(args: argparse.Namespace):
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=int(args.target_limit or 20),
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    if args.target_limit:
        selection = selection.head(args.target_limit).copy()
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    requested = int(args.target_limit or len(selection))
    selection_rule = "controlled_starlink_20target_selection_table"
    if requested > len(selection):
        existing = set(selection["target_norad_id"].astype(str))
        extra_rows = []
        for norad in sorted(tle.keys(), key=lambda v: int(v)):
            if norad in existing:
                continue
            entry = tle[norad]
            extra_rows.append(
                {
                    "target_index": len(selection) + len(extra_rows) + 1,
                    "target_name": entry["name"],
                    "target_norad_id": norad,
                    "selected_reason": "tle_norad_sorted_extension",
                    "notes": "extended availability audit target from local TLE",
                }
            )
            if len(selection) + len(extra_rows) >= requested:
                break
        if extra_rows:
            selection = pd.concat([selection, pd.DataFrame(extra_rows)], ignore_index=True)
            selection_rule = f"20-target table plus local TLE NORAD-sorted extension to {len(selection)} targets"
    elif args.target_limit:
        selection_rule = f"first {len(selection)} rows from controlled_starlink_20target_selection_table"
    return selection, library, orbit_cfg, ranges, tle, ts


def find_all_passes(sat: Any, station: Any, ts: Any, base_tw: dict[str, Any], start_utc: str, end_dt, min_elevation: float, scan_step_s: float | None = None) -> list[dict[str, Any]]:
    """Find all visible segments using the same Skyfield elevation definition as find_pass.

    The original helper returns the first segment in a search window.  Repeating it
    for long audits is unnecessarily slow, so this scans each day once and applies
    the same visible-index segmentation and max-pass-duration cap.
    """
    step = float(scan_step_s if scan_step_s is not None else base_tw.get("step_s", 1))
    max_pass_duration_s = float(base_tw.get("max_pass_duration_s", 600))
    max_points = int(max_pass_duration_s // step) + 1
    start_dt = base.parse_utc(start_utc)
    chunk_start = start_dt
    raw_segments: list[tuple[list[Any], np.ndarray]] = []
    while chunk_start < end_dt:
        chunk_end = min(chunk_start + timedelta(hours=float(base_tw.get("search_duration_h", 24))), end_dt)
        n = int((chunk_end - chunk_start).total_seconds() // step) + 1
        times = [chunk_start + timedelta(seconds=i * step) for i in range(n)]
        skyfield_times = ts.from_datetimes(times)
        elevation = (sat - station).at(skyfield_times).altaz()[0].degrees
        visible_idx = np.flatnonzero(elevation >= min_elevation)
        if len(visible_idx):
            seg_start = previous = int(visible_idx[0])
            for raw_idx in visible_idx[1:]:
                idx = int(raw_idx)
                if idx == previous + 1:
                    previous = idx
                else:
                    raw_segments.append((times[seg_start : previous + 1], elevation[seg_start : previous + 1]))
                    seg_start = previous = idx
            raw_segments.append((times[seg_start : previous + 1], elevation[seg_start : previous + 1]))
        chunk_start = chunk_end + timedelta(seconds=step)

    merged: list[tuple[list[Any], np.ndarray]] = []
    for times, elev in raw_segments:
        if not merged:
            merged.append((times, elev))
            continue
        prev_times, prev_elev = merged[-1]
        gap_s = (times[0] - prev_times[-1]).total_seconds()
        if gap_s <= step * 1.5:
            merged[-1] = (prev_times + times, np.concatenate([prev_elev, elev]))
        else:
            merged.append((times, elev))

    passes: list[dict[str, Any]] = []
    for times, elev in merged:
        start_idx = 0
        while start_idx < len(times):
            end_idx = min(start_idx + max_points, len(times)) - 1
            selected_times = times[start_idx : end_idx + 1]
            selected_elevation = elev[start_idx : end_idx + 1]
            if selected_times:
                passes.append(
                    {
                        "pass_start_utc": selected_times[0].isoformat().replace("+00:00", "Z"),
                        "pass_end_utc": selected_times[-1].isoformat().replace("+00:00", "Z"),
                        "duration_s": float((selected_times[-1] - selected_times[0]).total_seconds()),
                        "step_s": step,
                        "num_time_points": len(selected_times),
                        "max_elevation_deg": float(np.max(selected_elevation)),
                        "min_elevation_deg": float(np.min(selected_elevation)),
                    }
                )
            start_idx = end_idx + 1
    return passes


def time_gaps_hours(values: list[pd.Timestamp]) -> list[float]:
    if len(values) < 2:
        return []
    ordered = sorted(values)
    return [(ordered[i] - ordered[i - 1]).total_seconds() / 3600.0 for i in range(1, len(ordered))]


def classify(total_visible: int, high_quality_count: int, time_to_first_hq: float | None, readily_hours: float) -> str:
    if total_visible == 0:
        return "no_visible_pass"
    if high_quality_count == 0:
        return "only_low_single_station"
    if time_to_first_hq is not None and time_to_first_hq <= readily_hours:
        return "readily_authenticatable"
    return "delayed_authentication"


def target_availability_rows(selection: pd.DataFrame, all_passes: dict[str, list[dict[str, Any]]], audit_start, durations: list[int], args: argparse.Namespace):
    summary_rows = []
    detail_rows = []
    for duration in durations:
        audit_end = audit_start + timedelta(days=int(duration))
        for _, target in selection.iterrows():
            tid = str(target["target_norad_id"])
            name = str(target["target_name"])
            rows = []
            for idx, info in enumerate(all_passes.get(tid, []), 1):
                start = base.parse_utc(info["pass_start_utc"])
                if not (audit_start <= start < audit_end):
                    continue
                max_el = float(info["max_elevation_deg"])
                bin_name = elevation_bin(max_el, args.high_quality_elevation_deg, args.medium_elevation_deg)
                rows.append(
                    {
                        "target_sat_id": tid,
                        "target_name": name,
                        "pass_id": f"{tid}_availability_{duration}d_{idx:03d}",
                        "pass_start_utc": info["pass_start_utc"],
                        "pass_end_utc": info["pass_end_utc"],
                        "pass_duration_s": float(info["duration_s"]),
                        "max_elevation_deg": max_el,
                        "elevation_bin": bin_name,
                        "is_high_quality_pass": bool(max_el >= args.high_quality_elevation_deg),
                        "time_since_audit_start_hours": (start - audit_start).total_seconds() / 3600.0,
                    }
                )
            hq_starts = [base.parse_utc(r["pass_start_utc"]) for r in rows if r["is_high_quality_pass"]]
            next_hq_by_time = sorted(hq_starts)
            for r in rows:
                current = base.parse_utc(r["pass_start_utc"])
                future = [v for v in next_hq_by_time if v >= current]
                r["next_high_quality_wait_hours"] = ((future[0] - current).total_seconds() / 3600.0) if future else np.nan
                r["duration_days"] = int(duration)
                r["notes"] = f"current_station_single_station_availability;scan_step_s={args.scan_step_s}"
                detail_rows.append(r)

            total = len(rows)
            low = sum(1 for r in rows if r["elevation_bin"] == "low")
            medium = sum(1 for r in rows if r["elevation_bin"] == "medium")
            high = sum(1 for r in rows if r["elevation_bin"] == "high")
            hq = medium + high
            first_visible = min([base.parse_utc(r["pass_start_utc"]) for r in rows], default=None)
            first_hq = min(hq_starts, default=None)
            time_to_first_hq = ((first_hq - audit_start).total_seconds() / 3600.0) if first_hq else np.nan
            gaps = time_gaps_hours([pd.Timestamp(v) for v in hq_starts])
            max_els = [float(r["max_elevation_deg"]) for r in rows]
            durations_s = [float(r["pass_duration_s"]) for r in rows]
            availability_class = classify(total, hq, None if np.isnan(time_to_first_hq) else float(time_to_first_hq), args.readily_hours)
            summary_rows.append(
                {
                    "target_sat_id": tid,
                    "target_name": name,
                    "norad_id": tid,
                    "duration_days": int(duration),
                    "audit_start_utc": audit_start.isoformat().replace("+00:00", "Z"),
                    "audit_end_utc": audit_end.isoformat().replace("+00:00", "Z"),
                    "total_visible_passes": int(total),
                    "low_pass_count": int(low),
                    "medium_pass_count": int(medium),
                    "high_pass_count": int(high),
                    "high_quality_pass_count": int(hq),
                    "low_pass_fraction": low / total if total else 0.0,
                    "medium_pass_fraction": medium / total if total else 0.0,
                    "high_pass_fraction": high / total if total else 0.0,
                    "high_quality_pass_fraction": hq / total if total else 0.0,
                    "first_visible_pass_start_utc": first_visible.isoformat().replace("+00:00", "Z") if first_visible else "",
                    "first_high_quality_pass_start_utc": first_hq.isoformat().replace("+00:00", "Z") if first_hq else "",
                    "time_to_first_high_quality_pass_hours": time_to_first_hq,
                    "median_time_between_high_quality_passes_hours": float(np.median(gaps)) if gaps else np.nan,
                    "max_gap_between_high_quality_passes_hours": float(np.max(gaps)) if gaps else np.nan,
                    "max_elevation_deg_max": float(np.max(max_els)) if max_els else np.nan,
                    "max_elevation_deg_median": float(np.median(max_els)) if max_els else np.nan,
                    "pass_duration_s_median": float(np.median(durations_s)) if durations_s else np.nan,
                    "only_low_target": bool(total > 0 and hq == 0),
                    "has_high_quality_pass": bool(hq > 0),
                    "availability_class": availability_class,
                    "target_selection_rule": getattr(args, "target_selection_rule", ""),
                }
            )
    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)


def make_summaries(avail: pd.DataFrame, detail: pd.DataFrame):
    rows = []
    for duration, g in avail.groupby("duration_days"):
        visible = g[g["total_visible_passes"] > 0]
        hq = g[g["has_high_quality_pass"]]
        rows.append(
            {
                "duration_days": int(duration),
                "target_count": int(len(g)),
                "total_targets": int(len(g)),
                "visible_target_count": int(len(visible)),
                "no_visible_target_count": int((g["total_visible_passes"] == 0).sum()),
                "readily_authenticatable_count": int((g["availability_class"] == "readily_authenticatable").sum()),
                "delayed_authentication_count": int((g["availability_class"] == "delayed_authentication").sum()),
                "only_low_single_station_count": int((g["availability_class"] == "only_low_single_station").sum()),
                "only_low_fraction": float((g["availability_class"] == "only_low_single_station").mean()) if len(g) else 0.0,
                "targets_with_high_quality_pass_count": int(g["has_high_quality_pass"].sum()),
                "targets_without_high_quality_pass_count": int((~g["has_high_quality_pass"]).sum()),
                "mean_time_to_first_high_quality_pass_hours": float(hq["time_to_first_high_quality_pass_hours"].mean()) if len(hq) else np.nan,
                "median_time_to_first_high_quality_pass_hours": float(hq["time_to_first_high_quality_pass_hours"].median()) if len(hq) else np.nan,
                "p90_time_to_first_high_quality_pass_hours": float(hq["time_to_first_high_quality_pass_hours"].quantile(0.90)) if len(hq) else np.nan,
                "max_time_to_first_high_quality_pass_hours": float(hq["time_to_first_high_quality_pass_hours"].max()) if len(hq) else np.nan,
                "mean_high_quality_pass_count": float(g["high_quality_pass_count"].mean()),
                "median_high_quality_pass_count": float(g["high_quality_pass_count"].median()),
                "p10_high_quality_pass_count": float(g["high_quality_pass_count"].quantile(0.10)),
                "p90_high_quality_pass_count": float(g["high_quality_pass_count"].quantile(0.90)),
                "notes": "single controlled station; high_quality=max_elevation>=20deg",
            }
        )
    summary = pd.DataFrame(rows)
    bin_rows = []
    if not detail.empty:
        for (duration, bin_name), g in detail.groupby(["duration_days", "elevation_bin"], dropna=False):
            bin_rows.append(
                {
                    "duration_days": int(duration),
                    "elevation_bin": bin_name,
                    "total_passes": int(len(g)),
                    "target_count_with_this_bin": int(g["target_sat_id"].nunique()),
                    "median_max_elevation_deg": float(g["max_elevation_deg"].median()),
                    "median_pass_duration_s": float(g["pass_duration_s"].median()),
                }
            )
    return summary, pd.DataFrame(bin_rows).sort_values(["duration_days", "elevation_bin"]) if bin_rows else pd.DataFrame()


def write_lists(avail: pd.DataFrame, args: argparse.Namespace) -> None:
    latest_duration = int(max(avail["duration_days"]))
    latest = avail[avail["duration_days"] == latest_duration].copy()
    only_low = latest[latest["availability_class"] == "only_low_single_station"].copy()
    if only_low.empty:
        only_low_out = pd.DataFrame(columns=["target_sat_id", "target_name", "total_visible_passes", "low_pass_count", "max_elevation_deg_max", "max_elevation_deg_median", "recommended_next_step"])
    else:
        only_low_out = only_low[["target_sat_id", "target_name", "total_visible_passes", "low_pass_count", "max_elevation_deg_max", "max_elevation_deg_median"]].copy()
        only_low_out["recommended_next_step"] = "longer audit window; multi-station consistency"
    only_low_out.to_csv(args.only_low_output, index=False)

    delayed = latest[latest["availability_class"] == "delayed_authentication"].copy()
    delayed_out = delayed[["target_sat_id", "target_name", "time_to_first_high_quality_pass_hours", "high_quality_pass_count", "max_gap_between_high_quality_passes_hours"]].copy()
    delayed_out["recommended_next_step"] = "longer audit window; schedule high-quality pass challenge"
    delayed_out.to_csv(args.delayed_output, index=False)

    readily = latest[latest["availability_class"] == "readily_authenticatable"].copy()
    readily_out = readily[["target_sat_id", "target_name", "time_to_first_high_quality_pass_hours", "high_quality_pass_count", "max_elevation_deg_max", "max_elevation_deg_median"]].copy()
    readily_out.to_csv(args.readily_output, index=False)


def main() -> None:
    args = parse_args()
    args.output = with_suffix(args.output, args.output_suffix)
    args.pass_detail_output = with_suffix(args.pass_detail_output, args.output_suffix)
    args.summary_output = with_suffix(args.summary_output, args.output_suffix)
    args.bin_summary_output = with_suffix(args.bin_summary_output, args.output_suffix)
    args.only_low_output = with_suffix(args.only_low_output, args.output_suffix)
    args.delayed_output = with_suffix(args.delayed_output, args.output_suffix)
    args.readily_output = with_suffix(args.readily_output, args.output_suffix)
    outputs = [args.output, args.pass_detail_output, args.summary_output, args.bin_summary_output, args.only_low_output, args.delayed_output, args.readily_output]
    check_outputs(outputs, args.overwrite)
    selection, _library, orbit_cfg, _ranges, tle, ts = load_common(args)
    args.target_selection_rule = selection["selected_reason"].iloc[0] if "selected_reason" in selection.columns and len(selection) else ""
    if "tle_norad_sorted_extension" in set(selection.get("selected_reason", pd.Series(dtype=str)).astype(str)):
        args.target_selection_rule = f"20-target table plus local TLE NORAD-sorted extension to {len(selection)} targets"
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    start_utc = args.start_utc or orbit_cfg["time_window"]["search_start_utc"]
    audit_start = base.parse_utc(start_utc)
    durations = sorted(set(int(v) for v in args.duration_days))
    audit_end_max = audit_start + timedelta(days=max(durations))
    min_elevation = float(args.min_elevation_deg if args.min_elevation_deg is not None else orbit_cfg["time_window"].get("min_elevation_deg", 10.0))
    if args.scan_step_s is None:
        args.scan_step_s = float(orbit_cfg["time_window"].get("step_s", 1.0))
    all_passes: dict[str, list[dict[str, Any]]] = {}
    for _, target in selection.iterrows():
        tid = str(target["target_norad_id"])
        if tid not in tle:
            fail(f"target not found in TLE: {tid}")
        all_passes[tid] = find_all_passes(tle[tid]["sat"], station, ts, orbit_cfg["time_window"], start_utc, audit_end_max, min_elevation, args.scan_step_s)
        print(f"{target['target_name']} / {tid}: passes={len(all_passes[tid])}")
    avail, detail = target_availability_rows(selection, all_passes, audit_start, durations, args)
    summary, bin_summary = make_summaries(avail, detail)
    avail.to_csv(args.output, index=False)
    detail.to_csv(args.pass_detail_output, index=False)
    summary.to_csv(args.summary_output, index=False)
    bin_summary.to_csv(args.bin_summary_output, index=False)
    write_lists(avail, args)
    print(f"wrote {args.output} rows={len(avail)}")
    print(f"wrote {args.pass_detail_output} rows={len(detail)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.bin_summary_output} rows={len(bin_summary)}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
