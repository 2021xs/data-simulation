#!/usr/bin/env python
"""Build Ku-band candidate libraries for near-neighbor stress testing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load, wgs84

C_MPS = 299_792_458.0


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    raise InputError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tle-file", required=True, type=Path)
    parser.add_argument("--stress-dataset", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--candidate-limits", nargs="+", type=int, default=[200, 500, 1000])
    parser.add_argument("--known-neighbor-norad-id", default="66274")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def parse_utc_series(values: pd.Series) -> list[datetime]:
    out = []
    for value in values:
        text = str(value)
        text = text[:-1] + "+00:00" if text.endswith("Z") else text
        dt = datetime.fromisoformat(text)
        out.append((dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc))
    return out


def parse_tle(path: Path, ts: Any) -> list[dict[str, Any]]:
    if not path.exists():
        fail(f"TLE 文件不存在: {path}")
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: list[dict[str, Any]] = []
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 ") and name.upper().startswith("STARLINK"):
            try:
                sat = EarthSatellite(line1, line2, name, ts)
                entries.append(
                    {
                        "name": name,
                        "norad": line1[2:7].strip(),
                        "epoch": sat.epoch.utc_iso(),
                        "inclination": float(line2[8:16]),
                        "mean_motion": float(line2[52:63]),
                        "sat": sat,
                    }
                )
            except Exception:
                pass
            i += 3
        else:
            i += 1
    if not entries:
        fail("未解析到有效 Starlink TLE")
    return entries


def select_candidates(entries: list[dict[str, Any]], target_norad: str, known_neighbor_norad: str, limit: int) -> list[dict[str, Any]]:
    target = next((entry for entry in entries if entry["norad"] == target_norad), None)
    if not target:
        fail(f"true target 不在 TLE 文件中: {target_norad}")
    neighbor = next((entry for entry in entries if entry["norad"] == known_neighbor_norad), None)
    if not neighbor:
        fail(f"known nearest neighbor 不在 TLE 文件中: {known_neighbor_norad}")
    for entry in entries:
        entry["score"] = abs(entry["inclination"] - target["inclination"]) + 10 * abs(entry["mean_motion"] - target["mean_motion"])
    selected = sorted(entries, key=lambda entry: (entry["score"], entry["name"]))[:limit]
    selected_by_norad = {entry["norad"]: entry for entry in selected}
    for forced in [target, neighbor]:
        if forced["norad"] not in selected_by_norad:
            selected.append(forced)
    selected = sorted(selected, key=lambda entry: (0 if entry["norad"] == target_norad else 1, entry["score"], entry["name"]))
    if len(selected) > limit:
        keep = selected[:limit]
        keep_norads = {entry["norad"] for entry in keep}
        if known_neighbor_norad not in keep_norads:
            keep[-1] = neighbor
        selected = sorted(keep, key=lambda entry: (0 if entry["norad"] == target_norad else 1, entry["score"], entry["name"]))
    for rank, entry in enumerate(selected, 1):
        entry["rank"] = rank
        entry["is_true"] = entry["norad"] == target_norad
        entry["is_known_neighbor"] = entry["norad"] == known_neighbor_norad
    if target_norad not in {entry["norad"] for entry in selected}:
        fail(f"candidate_limit={limit} 未包含 true target")
    if known_neighbor_norad not in {entry["norad"] for entry in selected}:
        fail(f"candidate_limit={limit} 未包含 known nearest neighbor")
    return selected


def build_library(dataset: pd.DataFrame, entries: list[dict[str, Any]], limit: int, known_neighbor_norad: str) -> pd.DataFrame:
    full = dataset.drop_duplicates("t_abs_utc").sort_values("t_rel_s").reset_index(drop=True)
    target_norad = str(full["target_norad_id"].iloc[0])
    target_name = str(full["target_name"].iloc[0])
    candidates = select_candidates(entries, target_norad, known_neighbor_norad, limit)
    site = wgs84.latlon(float(full["station_lat_deg"].iloc[0]), float(full["station_lon_deg"].iloc[0]), elevation_m=float(full["station_alt_m"].iloc[0]))
    ts = load.timescale()
    times = ts.from_datetimes(parse_utc_series(full["t_abs_utc"]))
    step_s = float(np.median(np.diff(full["t_rel_s"]))) if len(full) > 1 else 1.0
    freq_hz = float(full["center_freq_hz"].iloc[0])
    rows: list[pd.DataFrame] = []
    for candidate in candidates:
        topo = (candidate["sat"] - site).at(times)
        elevation = topo.altaz()[0].degrees
        range_m = topo.distance().m
        range_rate_mps = np.gradient(range_m, step_s)
        doppler_hz = -freq_hz * range_rate_mps / C_MPS
        rows.append(
            pd.DataFrame(
                {
                    "pass_id": str(full["pass_id"].iloc[0]),
                    "target_name": target_name,
                    "target_norad_id": target_norad,
                    "candidate_name": candidate["name"],
                    "candidate_norad_id": candidate["norad"],
                    "candidate_rank": candidate["rank"],
                    "is_true_target": candidate["is_true"],
                    "is_known_nearest_neighbor": candidate["is_known_neighbor"],
                    "candidate_limit": limit,
                    "station_name": full["station_name"].iloc[0] if "station_name" in full.columns else "controlled_example_station",
                    "center_freq_hz": freq_hz,
                    "t_abs_utc": full["t_abs_utc"],
                    "t_rel_s": full["t_rel_s"],
                    "elevation_deg": elevation,
                    "range_m": range_m,
                    "range_rate_mps": range_rate_mps,
                    "doppler_hz": doppler_hz,
                    "f_geo_candidate_hz": freq_hz + doppler_hz,
                    "tle_epoch": candidate["epoch"],
                    "inclination_deg": candidate["inclination"],
                    "mean_motion_rev_per_day": candidate["mean_motion"],
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def main() -> int:
    args = parse_args()
    try:
        if not args.stress_dataset.exists():
            fail(f"stress dataset 不存在: {args.stress_dataset}")
        outputs = [args.output_dir / f"controlled_starlink_ku_band_near_neighbor_candidate_library_{limit}.csv" for limit in args.candidate_limits]
        existing = [str(path) for path in outputs if path.exists()]
        if existing and not args.overwrite:
            fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))
        dataset = pd.read_csv(args.stress_dataset)
        required = ["target_name", "target_norad_id", "t_abs_utc", "t_rel_s", "center_freq_hz", "station_lat_deg", "station_lon_deg", "station_alt_m"]
        missing = [field for field in required if field not in dataset.columns]
        if missing:
            fail("stress dataset 缺少字段: " + ", ".join(missing))
        ts = load.timescale()
        entries = parse_tle(args.tle_file, ts)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for limit, output in zip(args.candidate_limits, outputs):
            library = build_library(dataset, entries, limit, str(args.known_neighbor_norad_id))
            library.to_csv(output, index=False)
            print(f"candidate library {limit} 完成: {output}, rows={len(library)}")
    except InputError as exc:
        print(f"错误: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
