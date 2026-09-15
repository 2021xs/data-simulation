#!/usr/bin/env python
"""Build controlled Starlink candidate geometry library."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load, wgs84


C_MPS = 299_792_458.0


class InputError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build orbit candidate geometry library.")
    parser.add_argument("--tle-file", required=True, type=Path)
    parser.add_argument("--orbit-dataset", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise InputError(message)


def validate_output(path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        fail(f"输出文件已存在，若确认覆盖请添加 --overwrite: {path}")


def parse_tle(path: Path, ts) -> list[dict[str, Any]]:
    if not path.exists():
        fail(f"TLE 文件不存在: {path}")
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: list[dict[str, Any]] = []
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            i += 1
            continue
        if not name.upper().startswith("STARLINK"):
            i += 3
            continue
        sat = EarthSatellite(line1, line2, name, ts)
        entries.append(
            {
                "candidate_name": name,
                "candidate_norad_id": line1[2:7].strip(),
                "line1": line1,
                "line2": line2,
                "tle_epoch": sat.epoch.utc_iso(),
                "inclination_deg": float(line2[8:16]),
                "mean_motion_rev_per_day": float(line2[52:63]),
                "satellite": sat,
            }
        )
        i += 3
    if not entries:
        fail("TLE 文件中没有解析到 Starlink 候选")
    return entries


def select_candidates(entries: list[dict[str, Any]], target_name: str, target_norad: str, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        fail("--candidate-limit 必须为正整数")
    target = next(
        (
            e
            for e in entries
            if e["candidate_name"].upper() == target_name.upper()
            or str(e["candidate_norad_id"]) == str(target_norad)
        ),
        None,
    )
    if target is None:
        fail(f"target 不在 Starlink TLE 候选中: {target_name} / {target_norad}")
    for entry in entries:
        entry["similarity_score"] = abs(entry["inclination_deg"] - target["inclination_deg"]) + 10.0 * abs(
            entry["mean_motion_rev_per_day"] - target["mean_motion_rev_per_day"]
        )
    selected = sorted(entries, key=lambda e: (e["similarity_score"], e["candidate_name"]))[:limit]
    if not any(e["candidate_norad_id"] == target["candidate_norad_id"] for e in selected):
        selected = [target] + selected[: max(0, limit - 1)]
    selected = sorted(selected, key=lambda e: (0 if e["candidate_norad_id"] == target["candidate_norad_id"] else 1, e["similarity_score"], e["candidate_name"]))
    for rank, entry in enumerate(selected, start=1):
        entry["candidate_rank"] = rank
        entry["is_target"] = entry["candidate_norad_id"] == target["candidate_norad_id"]
    return selected


def load_context(dataset_path: Path, manifest_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not dataset_path.exists():
        fail(f"orbit dataset 不存在: {dataset_path}")
    if not manifest_path.exists():
        fail(f"manifest 不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("mode") != "controlled_starlink":
        fail("当前 candidate library 只支持 controlled_starlink manifest")
    df = pd.read_csv(dataset_path)
    required = ["t_abs_utc", "t_rel_s", "station_lat_deg", "station_lon_deg", "station_alt_m", "center_freq_hz", "target_name", "target_norad_id"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        fail(f"orbit dataset 缺少字段: {', '.join(missing)}")
    base = df.drop_duplicates("t_abs_utc").sort_values("t_rel_s").reset_index(drop=True)
    if len(base) != int(manifest["num_time_points"]):
        fail("orbit dataset 时间点数与 manifest.num_time_points 不一致")
    return base, manifest


def parse_utc_series(values: pd.Series) -> list[datetime]:
    from datetime import datetime, timezone

    times = []
    for value in values:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        times.append(dt.astimezone(timezone.utc))
    return times


def build_library(base: pd.DataFrame, manifest: dict[str, Any], candidates: list[dict[str, Any]], ts) -> pd.DataFrame:
    station = manifest["station"]
    site = wgs84.latlon(float(station["lat_deg"]), float(station["lon_deg"]), elevation_m=float(station["alt_m"]))
    center_freq_hz = float(manifest["center_freq_hz"])
    times_dt = parse_utc_series(base["t_abs_utc"])
    times = ts.from_datetimes(times_dt)
    t_rel = base["t_rel_s"].to_numpy(float)
    step_s = float(manifest["step_s"])
    target_name = manifest["target_name"]
    target_norad = str(manifest["target_norad_id"])
    rows: list[pd.DataFrame] = []

    for candidate in candidates:
        topocentric = (candidate["satellite"] - site).at(times)
        elevation = topocentric.altaz()[0].degrees
        range_m = topocentric.distance().m
        range_rate_mps = np.gradient(range_m, step_s)
        doppler_hz = -center_freq_hz * range_rate_mps / C_MPS
        geo_hz = center_freq_hz + doppler_hz
        rows.append(
            pd.DataFrame(
                {
                    "candidate_name": candidate["candidate_name"],
                    "candidate_norad_id": candidate["candidate_norad_id"],
                    "candidate_rank": candidate["candidate_rank"],
                    "is_target": candidate["is_target"],
                    "target_name": target_name,
                    "target_norad_id": target_norad,
                    "mode": manifest["mode"],
                    "station_name": station["name"],
                    "station_lat_deg": float(station["lat_deg"]),
                    "station_lon_deg": float(station["lon_deg"]),
                    "station_alt_m": float(station["alt_m"]),
                    "center_freq_hz": center_freq_hz,
                    "t_abs_utc": base["t_abs_utc"],
                    "t_rel_s": t_rel,
                    "elevation_deg": elevation,
                    "range_m": range_m,
                    "range_rate_mps": range_rate_mps,
                    "doppler_hz": doppler_hz,
                    "f_geo_candidate_hz": geo_hz,
                    "tle_epoch": candidate["tle_epoch"],
                    "inclination_deg": candidate["inclination_deg"],
                    "mean_motion_rev_per_day": candidate["mean_motion_rev_per_day"],
                    "similarity_score": candidate["similarity_score"],
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


def make_overlay_plot(library: pd.DataFrame) -> None:
    plots_dir = Path("outputs/plots")
    plots_dir.mkdir(parents=True, exist_ok=True)
    top = library[library["candidate_rank"] <= 8]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, group in top.groupby("candidate_name", sort=False):
        width = 2.0 if bool(group["is_target"].iloc[0]) else 1.0
        alpha = 1.0 if bool(group["is_target"].iloc[0]) else 0.65
        ax.plot(group["t_rel_s"], group["doppler_hz"], label=name, linewidth=width, alpha=alpha)
    ax.set_title("Controlled Starlink candidate Doppler overlay")
    ax.set_xlabel("t_rel_s (s)")
    ax.set_ylabel("doppler_hz")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(plots_dir / "orbit_candidate_doppler_overlay.png", dpi=160)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    try:
        validate_output(args.output, args.overwrite)
        ts = load.timescale()
        base, manifest = load_context(args.orbit_dataset, args.manifest)
        entries = parse_tle(args.tle_file, ts)
        candidates = select_candidates(entries, manifest["target_name"], str(manifest["target_norad_id"]), args.candidate_limit)
        library = build_library(base, manifest, candidates, ts)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        library.to_csv(args.output, index=False)
        make_overlay_plot(library)
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    print(f"候选几何库生成完成: {args.output}")
    print(f"候选数: {library['candidate_norad_id'].nunique()}")
    print(f"target: {manifest['target_name']} / {manifest['target_norad_id']}")
    print(f"时间点: {library['t_abs_utc'].nunique()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
