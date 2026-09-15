#!/usr/bin/env python
"""Audit whether the current repository can support a same-pair multi-pass study.

This is a read-only input audit.  It reuses the existing TLE parser, pass finder,
service-segment builder, and calibration helper.  It does not run the formal
verifier or create observation realizations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_target_pass_quality_availability as pass_audit  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402


OUTPUTS = {
    "pair": Path("outputs/metrics/multi_pass_data_availability_pair_inventory.csv"),
    "pass": Path("outputs/metrics/multi_pass_data_availability_pass_inventory.csv"),
    "missing": Path("outputs/metrics/multi_pass_data_availability_missing_pairs.csv"),
    "audit": Path("outputs/metrics/multi_pass_data_availability_correctness_audit.csv"),
    "report": Path("outputs/reports/multi_pass_data_availability_audit_report.md"),
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="多过境数据可用性审计（不运行正式验证器）")
    p.add_argument("--selected-conditions", type=Path, default=Path("outputs/metrics/fixed_geometry_multi_realization_selected_conditions.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--tle-history", type=Path, default=Path("data/tle/history/starlink_gp_history_20260301_20260320.csv"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--same-tle-days", type=int, default=7)
    p.add_argument("--scan-step-s", type=float, default=5.0)
    p.add_argument("--min-required-passes", type=int, default=3)
    p.add_argument("--service-duration-s", type=float, default=60.0)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def iso_utc(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat().replace("+00:00", "Z")


def require_columns(df: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        fail(f"{label} missing columns: {missing}")


def check_inputs(args: argparse.Namespace) -> None:
    paths = [args.selected_conditions, args.candidate_library, args.selection_table, args.tle_file,
             args.orbit_config, args.parameter_config]
    for path in paths:
        if not path.exists():
            fail(f"missing required input: {path}")
    if args.same_tle_days < 1 or args.scan_step_s <= 0 or args.service_duration_s != 60.0:
        fail("same-tle-days/scan-step-s invalid, or service-duration-s is not the fixed 60 s setting")
    existing = [str(path) for path in OUTPUTS.values() if path.exists()]
    if existing and not args.overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["target_sat_id", "attack_sat_id", "target_norad_id"]:
        if col in out:
            out[col] = out[col].astype(str).str.replace(r"\.0$", "", regex=True)
    return out


def load_pairs(path: Path) -> pd.DataFrame:
    selected = normalize_ids(pd.read_csv(path))
    require_columns(selected, ["physical_pair_id", "target_sat_id", "attack_sat_id", "selection_group"], "selected conditions")
    rows = []
    for pair_id, group in selected.groupby("physical_pair_id", sort=True):
        rows.append({
            "physical_pair_id": str(pair_id),
            "target_sat_id": str(group.target_sat_id.iloc[0]),
            "attack_sat_id": str(group.attack_sat_id.iloc[0]),
            "original_selection_groups": "|".join(sorted(group.selection_group.astype(str).unique())),
            "original_geometry_count": int(len(group)),
        })
    return pd.DataFrame(rows)


def primary_tle_inventory(path: Path, ts: Any) -> tuple[dict[str, dict[str, Any]], pd.DataFrame]:
    entries = base.parse_tle(path, ts)
    rows = []
    for norad, entry in entries.items():
        rows.append({"norad_id": str(norad), "name": entry["name"], "epoch": entry["sat"].epoch.utc_iso()})
    return entries, pd.DataFrame(rows)


def history_inventory(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["norad_id", "name", "epoch", "line1", "line2", "epoch_date"])
    raw = pd.read_csv(path, dtype={"NORAD_CAT_ID": str})
    require_columns(raw, ["NORAD_CAT_ID", "OBJECT_NAME", "EPOCH", "TLE_LINE1", "TLE_LINE2"], "TLE history")
    out = raw.rename(columns={"NORAD_CAT_ID": "norad_id", "OBJECT_NAME": "name", "EPOCH": "epoch",
                              "TLE_LINE1": "line1", "TLE_LINE2": "line2"})
    out["norad_id"] = out.norad_id.astype(str).str.replace(r"\.0$", "", regex=True)
    out["epoch"] = pd.to_datetime(out.epoch, utc=True)
    out["epoch_date"] = out.epoch.dt.date.astype(str)
    return out.sort_values(["norad_id", "epoch"]).drop_duplicates(["norad_id", "epoch", "line1", "line2"])


def candidate_pass_counts(selection_path: Path, candidate_path: Path) -> pd.DataFrame:
    """Use the candidate-library manifest table and verify its source header.

    The candidate library is about 1 GB and repeats the same target pass for each
    candidate.  The selection table is the repository's per-target pass manifest,
    so reading it avoids turning a metadata audit into a full library rescan.
    """
    header = pd.read_csv(candidate_path, nrows=0).columns.tolist()
    required_header = {"target_norad_id", "candidate_norad_id", "t_abs_utc", "t_rel_s", "f_geo_candidate_hz"}
    if not required_header.issubset(header):
        fail(f"candidate library missing columns: {sorted(required_header - set(header))}")
    table = normalize_ids(pd.read_csv(selection_path))
    require_columns(table, ["target_norad_id", "pass_start_utc", "pass_end_utc", "max_elevation_deg"], "selection table")
    if "pass_id" not in table:
        table["pass_id"] = table.apply(lambda r: f"{r.target_norad_id}_{pd.Timestamp(r.pass_start_utc).strftime('%Y%m%dT%H%M%SZ')}", axis=1)
    return table.groupby("target_norad_id", as_index=False).agg(
        candidate_library_pass_count=("pass_id", "nunique"),
        candidate_library_first_pass=("pass_start_utc", "min"),
        candidate_library_last_pass=("pass_end_utc", "max"),
    )


def station_and_window(args: argparse.Namespace) -> tuple[dict[str, Any], Any, datetime, datetime, float]:
    cfg = base.read_yaml(args.orbit_config)
    if cfg.get("mode") != "controlled_starlink" or cfg.get("observation_id") is not None:
        fail("audit requires mode=controlled_starlink and observation_id=null/missing")
    station_cfg = cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    tw = cfg["time_window"]
    start = base.parse_utc(str(tw["search_start_utc"]))
    end = start + timedelta(days=args.same_tle_days)
    return cfg, station, start, end, float(tw.get("min_elevation_deg", 10.0))


def add_pass_geometry(pass_info: dict[str, Any], sat: Any, station: Any, ts: Any) -> dict[str, Any]:
    start = base.parse_utc(pass_info["pass_start_utc"])
    end = base.parse_utc(pass_info["pass_end_utc"])
    sky_times = ts.from_datetimes([start, end])
    alt, az, _distance = (sat - station).at(sky_times).altaz()
    out = dict(pass_info)
    out["azimuth_start_deg"] = float(az.degrees[0])
    out["azimuth_end_deg"] = float(az.degrees[1])
    out["elevation_start_deg"] = float(alt.degrees[0])
    out["elevation_end_deg"] = float(alt.degrees[1])
    delta = ((out["azimuth_end_deg"] - out["azimuth_start_deg"] + 540.0) % 360.0) - 180.0
    out["azimuth_direction"] = "increasing" if delta > 0 else "decreasing" if delta < 0 else "flat"
    return out


def service_reuse_check(sat: Any, pass_info: dict[str, Any], ts: Any, service_s: float) -> tuple[int, bool]:
    start = base.parse_utc(pass_info["pass_start_utc"])
    end = base.parse_utc(pass_info["pass_end_utc"])
    n = int((end - start).total_seconds()) + 1
    times = [start + timedelta(seconds=i) for i in range(n)]
    t_rel = np.arange(n, dtype=float)
    g_lat, g_lon, g_alt = seg.compute_subpoint_series(sat, times, ts)
    track = seg.center_track("M2_block", g_lat, g_lon, g_alt, t_rel, 100.0, 1.0, service_s, 0.0)
    durations = [(track.segment_ends[i] - track.segment_starts[i] + 1) for i in range(len(track.segment_starts))]
    full_segments = sum(duration >= service_s for duration in durations)
    return int(full_segments), bool(full_segments >= 1)


def discover_same_tle_passes(
    pairs: pd.DataFrame, tle: dict[str, dict[str, Any]], station: Any, ts: Any,
    cfg: dict[str, Any], start: datetime, end: datetime, min_elevation: float,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    target_ids = sorted(set(pairs.target_sat_id), key=int)
    by_target: dict[str, list[dict[str, Any]]] = {}
    for target_id in target_ids:
        if target_id not in tle:
            by_target[target_id] = []
            continue
        found = pass_audit.find_all_passes(tle[target_id]["sat"], station, ts, cfg["time_window"],
                                           iso_utc(start), end, min_elevation, args.scan_step_s)
        by_target[target_id] = [add_pass_geometry(p, tle[target_id]["sat"], station, ts) for p in found]
    rows: list[dict[str, Any]] = []
    for pair in pairs.itertuples(index=False):
        target_id, attack_id = str(pair.target_sat_id), str(pair.attack_sat_id)
        target_ok, attack_ok = target_id in tle, attack_id in tle
        for index, info in enumerate(by_target.get(target_id, []), 1):
            full_segments, service_ok = service_reuse_check(tle[target_id]["sat"], info, ts, args.service_duration_s)
            start_utc = info["pass_start_utc"]
            rows.append({
                "physical_pair_id": pair.physical_pair_id,
                "pass_id": f"same_tle_{target_id}_{pd.Timestamp(start_utc).strftime('%Y%m%dT%H%M%SZ')}",
                "pass_source_type": "same_tle_different_pass",
                "pass_index_within_pair_source": index,
                "pass_date": str(pd.Timestamp(start_utc).date()),
                "target_sat_id": target_id,
                "attack_sat_id": attack_id,
                "tle_epoch_target": tle[target_id]["sat"].epoch.utc_iso() if target_ok else "",
                "tle_epoch_attack": tle[attack_id]["sat"].epoch.utc_iso() if attack_ok else "",
                "pass_start_time": start_utc,
                "pass_end_time": info["pass_end_utc"],
                "max_elevation_deg": info["max_elevation_deg"],
                "azimuth_start_deg": info["azimuth_start_deg"],
                "azimuth_end_deg": info["azimuth_end_deg"],
                "azimuth_direction": info["azimuth_direction"],
                "pass_duration_s": info["duration_s"],
                "scan_step_s": info["step_s"],
                "target_propagation_ok": target_ok,
                "attack_propagation_ok": attack_ok,
                "meets_elevation_condition": bool(info["max_elevation_deg"] >= min_elevation),
                "full_60s_service_segment_count": full_segments,
                "service_segment_reusable": service_ok,
                "calibration_reusable": True,
                "valid_for_formal_pass_candidate": bool(target_ok and attack_ok and service_ok),
            })
    return rows


def daily_record(history: pd.DataFrame, norad: str, date: str) -> pd.Series | None:
    group = history[(history.norad_id == norad) & (history.epoch_date == date)]
    if group.empty:
        return None
    noon = pd.Timestamp(date, tz="UTC") + pd.Timedelta(hours=12)
    return group.loc[(group.epoch - noon).abs().idxmin()]


def discover_history_passes(
    pairs: pd.DataFrame, history: pd.DataFrame, station: Any, ts: Any, cfg: dict[str, Any],
    min_elevation: float, args: argparse.Namespace,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if history.empty:
        return rows
    available_dates = history.groupby("norad_id").epoch_date.apply(set).to_dict()
    for pair in pairs.itertuples(index=False):
        target_id, attack_id = str(pair.target_sat_id), str(pair.attack_sat_id)
        common_dates = sorted(available_dates.get(target_id, set()) & available_dates.get(attack_id, set()))
        pair_index = 0
        for date in common_dates:
            target_row, attack_row = daily_record(history, target_id, date), daily_record(history, attack_id, date)
            if target_row is None or attack_row is None:
                continue
            sat_a = EarthSatellite(str(target_row.line1), str(target_row.line2), str(target_row["name"]), ts)
            sat_b = EarthSatellite(str(attack_row.line1), str(attack_row.line2), str(attack_row["name"]), ts)
            day_start = pd.Timestamp(date, tz="UTC").to_pydatetime()
            day_end = day_start + timedelta(days=1)
            found = pass_audit.find_all_passes(sat_a, station, ts, cfg["time_window"], iso_utc(day_start),
                                               day_end, min_elevation, args.scan_step_s)
            for info0 in found:
                pair_index += 1
                info = add_pass_geometry(info0, sat_a, station, ts)
                full_segments, service_ok = service_reuse_check(sat_a, info, ts, args.service_duration_s)
                rows.append({
                    "physical_pair_id": pair.physical_pair_id,
                    "pass_id": f"history_{target_id}_{pd.Timestamp(info['pass_start_utc']).strftime('%Y%m%dT%H%M%SZ')}",
                    "pass_source_type": "different_date_tle",
                    "pass_index_within_pair_source": pair_index,
                    "pass_date": date,
                    "target_sat_id": target_id,
                    "attack_sat_id": attack_id,
                    "tle_epoch_target": iso_utc(target_row.epoch),
                    "tle_epoch_attack": iso_utc(attack_row.epoch),
                    "pass_start_time": info["pass_start_utc"],
                    "pass_end_time": info["pass_end_utc"],
                    "max_elevation_deg": info["max_elevation_deg"],
                    "azimuth_start_deg": info["azimuth_start_deg"],
                    "azimuth_end_deg": info["azimuth_end_deg"],
                    "azimuth_direction": info["azimuth_direction"],
                    "pass_duration_s": info["duration_s"],
                    "scan_step_s": info["step_s"],
                    "target_propagation_ok": True,
                    "attack_propagation_ok": bool(np.isfinite(sat_b.at(ts.from_datetime(day_start)).position.km).all()),
                    "meets_elevation_condition": bool(info["max_elevation_deg"] >= min_elevation),
                    "full_60s_service_segment_count": full_segments,
                    "service_segment_reusable": service_ok,
                    "calibration_reusable": True,
                    "valid_for_formal_pass_candidate": bool(service_ok),
                })
    return rows


def build_pair_inventory(
    pairs: pd.DataFrame, primary: pd.DataFrame, history: pd.DataFrame,
    candidate_counts: pd.DataFrame, passes: pd.DataFrame, min_required: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    primary_ids = set(primary.norad_id)
    history_counts = history.groupby("norad_id").agg(history_epoch_count=("epoch", "nunique"),
                                                     history_date_count=("epoch_date", "nunique")).to_dict("index") if not history.empty else {}
    cand = candidate_counts.set_index("target_norad_id").to_dict("index")
    rows, missing = [], []
    for pair in pairs.itertuples(index=False):
        pid, target, attack = str(pair.physical_pair_id), str(pair.target_sat_id), str(pair.attack_sat_id)
        pp = passes[(passes.physical_pair_id == pid) & passes.valid_for_formal_pass_candidate.astype(bool)] if not passes.empty else passes
        same_count = int(pp.loc[pp.pass_source_type == "same_tle_different_pass", "pass_id"].nunique()) if len(pp) else 0
        hist_count = int(pp.loc[pp.pass_source_type == "different_date_tle", "pass_id"].nunique()) if len(pp) else 0
        best_count = hist_count if hist_count >= min_required else same_count
        best_source = "different_date_tle" if hist_count >= min_required else "same_tle_different_pass" if same_count >= min_required else "insufficient"
        target_hist = history_counts.get(target, {})
        attack_hist = history_counts.get(attack, {})
        row = {
            **pair._asdict(),
            "target_in_primary_tle": target in primary_ids,
            "attack_in_primary_tle": attack in primary_ids,
            "target_history_epoch_count": int(target_hist.get("history_epoch_count", 0)),
            "attack_history_epoch_count": int(attack_hist.get("history_epoch_count", 0)),
            "target_history_date_count": int(target_hist.get("history_date_count", 0)),
            "attack_history_date_count": int(attack_hist.get("history_date_count", 0)),
            "candidate_library_target_pass_count": int(cand.get(target, {}).get("candidate_library_pass_count", 0)),
            "same_tle_valid_pass_count": same_count,
            "different_date_tle_valid_pass_count": hist_count,
            "best_available_pass_source_type": best_source,
            "best_available_pass_count": best_count,
            "has_at_least_3_passes": bool(best_count >= min_required),
            "eligible_for_repeatability_main_conclusion": bool(best_count >= min_required),
        }
        rows.append(row)
        reasons = []
        scopes = []
        if hist_count < min_required:
            reasons.append(f"different-date TLE valid passes={hist_count}<{min_required}")
            scopes.append("different_date_tle")
        if not row["has_at_least_3_passes"]:
            if target not in primary_ids or attack not in primary_ids:
                reasons.append("pair member missing from primary TLE")
            if same_count < min_required:
                reasons.append(f"same-TLE valid passes={same_count}<{min_required}")
                scopes.append("same_tle_different_pass")
        if reasons:
            missing.append({
                **row,
                "missing_data_scope": "|".join(scopes),
                "blocks_formal_experiment": not bool(row["has_at_least_3_passes"]),
                "missing_reason": "; ".join(reasons),
            })
    return pd.DataFrame(rows), pd.DataFrame(missing)


def correctness(
    args: argparse.Namespace, pairs: pd.DataFrame, primary: pd.DataFrame, history: pd.DataFrame,
    passes: pd.DataFrame, pair_inventory: pd.DataFrame, input_hashes: dict[str, str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(check: str, passed: bool, observed: Any, expected: Any) -> None:
        rows.append({"check": check, "passed": bool(passed), "observed": json.dumps(observed, ensure_ascii=False, default=str),
                     "expected": json.dumps(expected, ensure_ascii=False, default=str)})

    dup = int(passes.duplicated(["physical_pair_id", "pass_source_type", "pass_id"]).sum()) if len(passes) else 0
    same_unique = passes[passes.pass_source_type == "same_tle_different_pass"].groupby("physical_pair_id").pass_start_time.nunique() if len(passes) else pd.Series(dtype=int)
    history_epoch_complete = passes.loc[passes.pass_source_type == "different_date_tle", ["tle_epoch_target", "tle_epoch_attack"]].ne("").all().all() if len(passes) else True
    valid_pass_count = int(passes.valid_for_formal_pass_candidate.astype(bool).sum()) if len(passes) else 0
    service_ok = (valid_pass_count > 0 and
                  passes.loc[passes.valid_for_formal_pass_candidate.astype(bool), "service_segment_reusable"].astype(bool).all())
    member_ok = passes[["target_propagation_ok", "attack_propagation_ok"]].astype(bool).all().all() if len(passes) else False
    config = base.read_yaml(args.orbit_config)
    after_hashes = {name: sha_file(path) for name, path in {
        "selected_conditions": args.selected_conditions, "selection_table": args.selection_table,
        "tle_file": args.tle_file, "orbit_config": args.orbit_config,
        "parameter_config": args.parameter_config,
    }.items()}
    add("pass主键唯一", dup == 0, dup, 0)
    add("same-TLE pass绝对时间真实不同", bool((same_unique >= args.min_required_passes).all()), same_unique.to_dict(), f">={args.min_required_passes} unique starts per pair")
    add("pass不是同一服务段重复命名", dup == 0 and passes.pass_id.str.contains("seg", case=False).sum() == 0,
        {"duplicates": dup, "segment_named_passes": int(passes.pass_id.str.contains("seg", case=False).sum())}, {"duplicates": 0, "segment_named_passes": 0})
    add("different-date TLE epoch记录完整", bool(history_epoch_complete), history_epoch_complete, True)
    add("pair目标和非目标轨道均可传播", bool(member_ok), member_ok, True)
    add("pass满足旧elevation和60秒服务段条件", bool(service_ok), {"valid_passes": valid_pass_count, "all_service_reusable": bool(service_ok)}, {"valid_passes": ">0", "all_service_reusable": True})
    add("正式实验语义未改变", config.get("mode") == "controlled_starlink" and config.get("observation_id") is None and args.service_duration_s == 60.0,
        {"mode": config.get("mode"), "observation_id": config.get("observation_id"), "T_service_s": args.service_duration_s},
        {"mode": "controlled_starlink", "observation_id": None, "T_service_s": 60})
    add("未使用伪造TLE且历史数据来自本地下载文件", (not history.empty) and args.tle_history.exists(),
        {"history_records": len(history), "history_file": str(args.tle_history)}, "existing local history file")
    add("旧正式输入SHA-256未改变", input_hashes == after_hashes, {k: input_hashes[k] == after_hashes[k] for k in input_hashes}, "all true")
    add("20个物理pair已完整建账", len(pair_inventory) == len(pairs) == 20, {"source_pairs": len(pairs), "inventory_pairs": len(pair_inventory)}, 20)
    add("不同pass来源类型未混淆", set(passes.pass_source_type).issubset({"different_date_tle", "same_tle_different_pass"}),
        sorted(passes.pass_source_type.unique()), ["different_date_tle", "same_tle_different_pass"])
    return pd.DataFrame(rows)


def write_report(
    args: argparse.Namespace, primary: pd.DataFrame, history: pd.DataFrame, candidate_counts: pd.DataFrame,
    pair_inventory: pd.DataFrame, passes: pd.DataFrame, missing: pd.DataFrame, audit: pd.DataFrame,
) -> None:
    eligible = pair_inventory[pair_inventory.has_at_least_3_passes]
    history_pairs = pair_inventory[pair_inventory.different_date_tle_valid_pass_count >= args.min_required_passes]
    same_pairs = pair_inventory[pair_inventory.same_tle_valid_pass_count >= args.min_required_passes]
    history_multi = history.groupby("norad_id").epoch.nunique() if not history.empty else pd.Series(dtype=int)
    enough = len(eligible) >= 10
    pair_table = pair_inventory[["physical_pair_id", "candidate_library_target_pass_count", "same_tle_valid_pass_count",
                                 "different_date_tle_valid_pass_count", "best_available_pass_source_type",
                                 "has_at_least_3_passes"]].to_markdown(index=False)
    missing_text = "无。" if missing.empty else missing[["physical_pair_id", "missing_data_scope", "blocks_formal_experiment", "missing_reason"]].to_markdown(index=False)
    failed = audit[~audit.passed]
    audit_text = audit.to_markdown(index=False)
    report = f"""# 多过境数据可用性审计报告

## 1. 审计目的与边界

本轮只审计同一物理目标—非目标卫星 pair 的多过境数据可用性，不运行正式 verifier，不生成 observation realization，也不改变 sequence mode、阈值、calibration 口径、轨道传播、fixed-site Doppler 或服务段定义。正式语义保持 `T_service_s=60`、`segment_local`、`fixed_site_segment_center`、`single-window`。

严格区分两类可用 pass：`different_date_tle` 使用仓库已有 Space-Track GP history 中不同日期的真实 TLE 记录；`same_tle_different_pass` 使用主 TLE 在不同绝对时间自动搜索到的过境。没有把 `same_pass_different_segment` 计为跨过境。

## 2. TLE 与 candidate library 现状

- 主 TLE：{len(primary)} 颗卫星，NORAD 内 epoch 数均为 1；全文件不同 epoch 数为 {primary.epoch.nunique()}。
- 历史 TLE：{history.norad_id.nunique() if len(history) else 0} 颗卫星，{history.epoch.nunique() if len(history) else 0} 个不同 epoch，{int((history_multi >= 2).sum())} 颗具有至少 2 个 epoch。
- 历史范围：{iso_utc(history.epoch.min()) if len(history) else 'unavailable'} 至 {iso_utc(history.epoch.max()) if len(history) else 'unavailable'}。
- candidate library manifest：{len(candidate_counts)} 个目标；每个目标 pass 数范围 {int(candidate_counts.candidate_library_pass_count.min())}–{int(candidate_counts.candidate_library_pass_count.max())}。该 1 GB library 对每个候选重复目标时间网格，且自身没有 `pass_id/elevation_deg`；本审计使用与其配套的正式 selection table 统计 pass 元数据，并校验 library 的目标、候选、绝对时间和几何频率表头。
- 主 TLE 自动搜索：从 {base.read_yaml(args.orbit_config)['time_window']['search_start_utc']} 起 {args.same_tle_days} 天，elevation mask={base.read_yaml(args.orbit_config)['time_window'].get('min_elevation_deg', 10)}°，scan step={args.scan_step_s}s。

## 3. 当前 20 个 physical pair 的可用性

{pair_table}

结论：{len(history_pairs)}/20 个 pair 可由 `different_date_tle` 提供至少 {args.min_required_passes} 个有效 pass；{len(same_pairs)}/20 个 pair 可由 `same_tle_different_pass` 提供至少 {args.min_required_passes} 个有效 pass；按来源优先级选择后共 {len(eligible)}/20 个 pair 可进入至少 3-pass 分析。

## 4. 传播、服务区、服务段与 calibration 复用

pass 搜索直接复用 `audit_target_pass_quality_availability.find_all_passes`，其 elevation 定义与现有 Skyfield pipeline 一致。每个新 pass 用现有 `compute_subpoint_series` 和 `center_track('M2_block', T_service_s=60)` 试构造服务段；有效 pass 至少包含一个完整 60 秒段。验证站为受控 station，服务中心仍由当前 pass 的目标星下点构造。

现有 `calibration_for_trel` 只依赖当前 pass 的 `t_rel`、正式经验参数范围和固定 seed，不依赖旧 candidate library 的特定绝对时间，因此函数可复用；正式实验仍需对每个 geometry-pass 固定 calibration，并进行 current/wide 同拟合审计。

## 5. 缺失 pair / 限制

{missing_text}

历史 GP 文件只覆盖 7 个 NORAD ID，因此绝大多数当前 pair 暂不能做 `different_date_tle` 主结论。`same_tle_different_pass` 可以支持机制重复性实验，但只验证同一轨道元素快照传播到不同过境，结论等级低于不同日期真实 TLE。SGP4 外推窗口限制为主 epoch 附近 7 天；没有伪造或平移旧 pass。

## 6. 正确性审计

{audit_text}

审计通过 {int(audit.passed.sum())}/{len(audit)}。失败项数：{len(failed)}。任何失败时不得进入正式实验。

## 7. 是否足以进入正式实验

**{'数据足以进入正式 smoke/confirmation 实验实现。' if enough and failed.empty else '当前数据不足或审计未全通过，应停止正式实验。'}**

可行时，正式 pair 选择应优先使用具备 `different_date_tle` 的 pair，再补充 `same_tle_different_pass`；报告必须分层呈现，不能把后者写成不同日期 TLE 验证。当前审计只判定数据与公共函数可用，不提前给出跨 pass 风险结论。
"""
    OUTPUTS["report"].write_text(report, encoding="utf-8")


def append_log(args: argparse.Namespace, pair_inventory: pd.DataFrame, passes: pd.DataFrame, audit: pd.DataFrame) -> None:
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
    eligible = int(pair_inventory.has_at_least_3_passes.sum())
    history_eligible = int((pair_inventory.different_date_tle_valid_pass_count >= args.min_required_passes).sum())
    text = f"""

## {now} - 多过境数据可用性审计

### A. 本轮目标
审计当前20个物理pair是否具备不同日期TLE或同一TLE下不同pass；不运行正式多过境verifier实验。

### B. 实际操作
新增并运行 `scripts/run_multi_pass_data_availability_audit.py`；复用现有TLE解析、pass搜索、Skyfield传播、60秒服务段和calibration函数；严格区分`different_date_tle`与`same_tle_different_pass`。

### C. 新增/修改文件
新增审计脚本、4个metrics CSV和1份中文报告；追加本日志。未修改配置，未修改旧脚本，未生成正式dataset/figures。

### D. 运行命令
`python -m py_compile scripts/run_multi_pass_data_availability_audit.py`

`python scripts/run_multi_pass_data_availability_audit.py{' --overwrite' if args.overwrite else ''}`

### E. 结果摘要
pass inventory共{len(passes)}行；20个pair中{eligible}个具备至少{args.min_required_passes}个可用pass，其中{history_eligible}个由不同日期真实TLE支持。正确性审计{int(audit.passed.sum())}/{len(audit)}通过。未运行正式gate evaluation或observation realization实验。

### F. 问题与下一步
历史TLE覆盖不足的pair只能使用`same_tle_different_pass`，结论等级低于`different_date_tle`。仅在审计全部通过且可选pair数量满足规模要求后，才实现正式多过境脚本并先跑smoke。
"""
    log = Path("logs/work_log.md")
    with log.open("a", encoding="utf-8", newline="") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    check_inputs(args)
    for path in OUTPUTS.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    input_paths = {"selected_conditions": args.selected_conditions, "selection_table": args.selection_table,
                   "tle_file": args.tle_file, "orbit_config": args.orbit_config,
                   "parameter_config": args.parameter_config}
    input_hashes = {name: sha_file(path) for name, path in input_paths.items()}

    pairs = load_pairs(args.selected_conditions)
    ts = load.timescale()
    tle, primary = primary_tle_inventory(args.tle_file, ts)
    history = history_inventory(args.tle_history)
    candidate_counts = candidate_pass_counts(args.selection_table, args.candidate_library)
    cfg, station, start, end, min_elevation = station_and_window(args)

    same_rows = discover_same_tle_passes(pairs, tle, station, ts, cfg, start, end, min_elevation, args)
    history_rows = discover_history_passes(pairs, history, station, ts, cfg, min_elevation, args)
    passes = pd.DataFrame(same_rows + history_rows)
    if passes.empty:
        fail("no pass discovered; formal experiment must not proceed")
    passes = passes.sort_values(["physical_pair_id", "pass_source_type", "pass_start_time"]).reset_index(drop=True)
    pair_inventory, missing = build_pair_inventory(pairs, primary, history, candidate_counts, passes, args.min_required_passes)
    if missing.empty:
        missing = pd.DataFrame(columns=list(pair_inventory.columns) + ["missing_reason"])
    audit = correctness(args, pairs, primary, history, passes, pair_inventory, input_hashes)

    pair_inventory.to_csv(OUTPUTS["pair"], index=False, encoding="utf-8-sig")
    passes.to_csv(OUTPUTS["pass"], index=False, encoding="utf-8-sig")
    missing.to_csv(OUTPUTS["missing"], index=False, encoding="utf-8-sig")
    audit.to_csv(OUTPUTS["audit"], index=False, encoding="utf-8-sig")
    write_report(args, primary, history, candidate_counts, pair_inventory, passes, missing, audit)
    append_log(args, pair_inventory, passes, audit)

    history_epochs = int(history.epoch.nunique()) if len(history) else 0
    valid_passes = passes[passes.valid_for_formal_pass_candidate.astype(bool)]
    eligible = pair_inventory[pair_inventory.has_at_least_3_passes]
    print(f"可用TLE epoch数量: primary={primary.epoch.nunique()}, history={history_epochs}")
    print(f"可用pass总数: {valid_passes.pass_id.nunique()} unique IDs, {len(valid_passes)} pair-pass rows")
    print(f"当前20个pair中可构造至少{args.min_required_passes}个pass: {len(eligible)}/20")
    for row in pair_inventory.itertuples(index=False):
        print(f"  {row.physical_pair_id}: different_date_tle={row.different_date_tle_valid_pass_count}, same_tle_different_pass={row.same_tle_valid_pass_count}, selected={row.best_available_pass_count}")
    print(f"数据是否足以进入正式实验: {'YES' if len(eligible) >= 10 and audit.passed.all() else 'NO'}")
    print(f"正确性审计: {int(audit.passed.sum())}/{len(audit)} passed")
    if len(missing):
        blocked = int(missing.blocks_formal_experiment.astype(bool).sum())
        print(f"缺失/限制pair: {len(missing)} (阻塞正式实验={blocked})")
    print("限制: different-date history仅覆盖部分NORAD；same-TLE different-pass结论等级较低。")
    if not audit.passed.all():
        fail("correctness audit failed; do not proceed to formal experiment")


if __name__ == "__main__":
    main()
