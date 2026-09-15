#!/usr/bin/env python
"""Build controlled Starlink Ku-band near-neighbor stress dataset."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pandas as pd
import yaml
from skyfield.api import EarthSatellite, load, wgs84

C_MPS = 299_792_458.0


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    raise InputError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tle-file", required=True, type=Path)
    parser.add_argument("--orbit-config", required=True, type=Path)
    parser.add_argument("--sim-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"配置文件不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse_utc(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


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
                        "line1": line1,
                        "line2": line2,
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


def parameter_ranges(sim_cfg: dict[str, Any], range_type: str) -> tuple[str, dict[str, list[float]]]:
    params = sim_cfg["parameters"]
    ranges = {}
    for key in ["b_hz", "k_hz_per_s", "sigma_hz"]:
        values = params[key][f"{range_type}_range"]
        ranges[key] = [float(values[0]), float(values[1])]
    version = sim_cfg.get("model", {}).get("name", "effective_cfo_simulation_v1")
    return version, ranges


def scaled_ranges(ranges: dict[str, list[float]], scale_factor: float) -> dict[str, list[float]]:
    return {key: [values[0] * scale_factor, values[1] * scale_factor] for key, values in ranges.items()}


def find_pass(sat: EarthSatellite, station: Any, ts: Any, time_window: dict[str, Any]) -> tuple[list[datetime], dict[str, Any]]:
    step_s = float(time_window.get("step_s", 1))
    start = parse_utc(time_window["search_start_utc"])
    duration_h = float(time_window.get("search_duration_h", 24))
    min_elevation_deg = float(time_window["min_elevation_deg"])
    max_duration_s = float(time_window["max_pass_duration_s"])
    times = [start + timedelta(seconds=i * step_s) for i in range(int(duration_h * 3600 // step_s) + 1)]
    sf_times = ts.from_datetimes(times)
    elevation = (sat - station).at(sf_times).altaz()[0].degrees
    visible_idx = np.flatnonzero(elevation >= min_elevation_deg)
    if len(visible_idx) == 0:
        fail("target 没有找到可见 pass，不能伪造 stress dataset")
    segments: list[tuple[int, int]] = []
    seg_start = previous = int(visible_idx[0])
    for raw_idx in visible_idx[1:]:
        idx = int(raw_idx)
        if idx == previous + 1:
            previous = idx
        else:
            segments.append((seg_start, previous))
            seg_start = previous = idx
    segments.append((seg_start, previous))
    start_idx, end_idx = segments[0]
    max_points = int(max_duration_s // step_s) + 1
    if end_idx - start_idx + 1 > max_points:
        end_idx = start_idx + max_points - 1
    pass_times = times[start_idx : end_idx + 1]
    pass_elevation = elevation[start_idx : end_idx + 1]
    info = {
        "pass_start_utc": pass_times[0].isoformat().replace("+00:00", "Z"),
        "pass_end_utc": pass_times[-1].isoformat().replace("+00:00", "Z"),
        "duration_s": float((pass_times[-1] - pass_times[0]).total_seconds()),
        "step_s": step_s,
        "num_time_points": len(pass_times),
        "max_elevation_deg": float(np.max(pass_elevation)),
        "min_elevation_deg": float(np.min(pass_elevation)),
    }
    return pass_times, info


def geo_curve(sat: EarthSatellite, station: Any, ts: Any, times: list[datetime], freq_hz: float, step_s: float) -> pd.DataFrame:
    sf_times = ts.from_datetimes(times)
    topo = (sat - station).at(sf_times)
    elevation = topo.altaz()[0].degrees
    range_m = topo.distance().m
    range_rate_mps = np.gradient(range_m, step_s)
    doppler_hz = -freq_hz * range_rate_mps / C_MPS
    start = times[0]
    return pd.DataFrame(
        {
            "t_abs_utc": [dt.isoformat().replace("+00:00", "Z") for dt in times],
            "t_rel_s": [(dt - start).total_seconds() for dt in times],
            "elevation_deg": elevation,
            "range_m": range_m,
            "range_rate_mps": range_rate_mps,
            "doppler_hz": doppler_hz,
            "f_geo_tle_hz": freq_hz + doppler_hz,
        }
    )


def window_indices(name: str, n_points: int, step_s: float) -> np.ndarray:
    if name == "full":
        start, end = 0, n_points
    elif name == "first_30_percent":
        start, end = 0, max(1, int(round(n_points * 0.30)))
    elif name == "middle_30_percent":
        width = max(1, int(round(n_points * 0.30)))
        start = max(0, (n_points - width) // 2)
        end = start + width
    elif name == "last_30_percent":
        width = max(1, int(round(n_points * 0.30)))
        start, end = max(0, n_points - width), n_points
    elif name.startswith("center_") and name.endswith("s"):
        duration_s = float(name.replace("center_", "").replace("s", ""))
        width = int(duration_s // step_s) + 1
        center = n_points // 2
        start = max(0, center - width // 2)
        end = min(n_points, start + width)
        start = max(0, end - width)
    else:
        fail(f"未知 partial_pass_window: {name}")
    idx = np.arange(start, end)
    if len(idx) < 5:
        return np.array([], dtype=int)
    return idx


def build_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    orbit_cfg = read_yaml(args.orbit_config)
    sim_cfg = read_yaml(args.sim_config)
    if orbit_cfg.get("mode") != "controlled_starlink":
        fail("本轮 stress 只允许 controlled_starlink mode")
    stress_cfg = orbit_cfg.get("near_neighbor_stress")
    if not stress_cfg:
        fail("orbit config 缺少 near_neighbor_stress 配置块")
    if stress_cfg.get("observation_id") is not None:
        fail("near_neighbor_stress 必须保持 observation_id=null")
    ts = load.timescale()
    entries = parse_tle(args.tle_file, ts)
    target_cfg = stress_cfg["target"]
    neighbor_cfg = stress_cfg["known_nearest_neighbor"]
    target = next((entry for entry in entries if entry["norad"] == str(target_cfg["norad_id"])), None)
    if not target:
        fail(f"target NORAD 不在 Starlink TLE 中: {target_cfg['norad_id']}")
    if not any(entry["norad"] == str(neighbor_cfg["norad_id"]) for entry in entries):
        fail(f"known nearest neighbor NORAD 不在 Starlink TLE 中: {neighbor_cfg['norad_id']}")

    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    source_freq = float(stress_cfg["source_center_freq_hz"])
    simulation_freq = float(stress_cfg["simulation_center_freq_hz"])
    frequency_scale_factor = simulation_freq / source_freq
    pass_times, pass_info = find_pass(target["sat"], station, ts, orbit_cfg["time_window"])
    full_geo = geo_curve(target["sat"], station, ts, pass_times, simulation_freq, pass_info["step_s"])
    config_version, base_ranges = parameter_ranges(sim_cfg, orbit_cfg["simulation"]["range_type"])
    after_scaling = {
        "unscaled": {key: list(value) for key, value in base_ranges.items()},
        "frequency_scaled": scaled_ranges(base_ranges, frequency_scale_factor),
    }
    rng = np.random.default_rng(args.seed)

    rows: list[pd.DataFrame] = []
    skipped_windows: list[dict[str, Any]] = []
    sequence_count = 0
    windows = stress_cfg["partial_pass_windows"]
    scenarios = stress_cfg["scenarios"]
    num_sims = int(stress_cfg["num_sims_per_setting"])
    for window in windows:
        idx = window_indices(window, len(full_geo), pass_info["step_s"])
        if len(idx) == 0:
            skipped_windows.append({"partial_pass_window": window, "reason": "too_few_points"})
            continue
        window_geo = full_geo.iloc[idx].copy().reset_index(drop=True)
        window_geo["t_window_rel_s"] = window_geo["t_rel_s"] - float(window_geo["t_rel_s"].iloc[0])
        window_duration_s = float(window_geo["t_rel_s"].iloc[-1] - window_geo["t_rel_s"].iloc[0]) if len(window_geo) > 1 else 0.0
        t_rel = window_geo["t_rel_s"].to_numpy(float)
        t0 = float(np.mean(t_rel))
        f_geo = window_geo["f_geo_tle_hz"].to_numpy(float)
        for variant in stress_cfg["error_model_variants"]:
            variant_scale = frequency_scale_factor if variant == "frequency_scaled" else 1.0
            for sigma_multiplier in stress_cfg["sigma_multipliers"]:
                sigma_multiplier = float(sigma_multiplier)
                for scenario in scenarios:
                    for sim_index in range(1, num_sims + 1):
                        raw_b = float(rng.uniform(*base_ranges["b_hz"]))
                        raw_k = float(rng.uniform(*base_ranges["k_hz_per_s"])) if scenario == "offset_linear_noise" else 0.0
                        raw_sigma = float(rng.uniform(*base_ranges["sigma_hz"]))
                        b_hz = raw_b * variant_scale
                        k_hz_per_s = raw_k * variant_scale
                        sigma_base_hz = raw_sigma * variant_scale
                        sigma_hz = sigma_base_hz * sigma_multiplier
                        noise = rng.normal(0, sigma_hz, len(window_geo))
                        sequence_count += 1
                        sequence_id = f"nn_stress_{sequence_count:06d}"
                        seq = window_geo.copy()
                        seq.insert(0, "experiment_name", stress_cfg["experiment_name"])
                        seq.insert(1, "sequence_id", sequence_id)
                        seq.insert(2, "sim_id", sequence_id)
                        seq.insert(3, "target_name", target["name"])
                        seq.insert(4, "target_norad_id", target["norad"])
                        seq.insert(5, "known_nearest_neighbor_name", neighbor_cfg["name"])
                        seq.insert(6, "known_nearest_neighbor_norad_id", str(neighbor_cfg["norad_id"]))
                        seq.insert(7, "error_model_variant", variant)
                        seq.insert(8, "sigma_multiplier", sigma_multiplier)
                        seq.insert(9, "partial_pass_window", window)
                        seq.insert(10, "scenario", scenario)
                        seq.insert(11, "sim_index", sim_index)
                        seq.insert(12, "pass_id", f"near_neighbor_pass_{target['norad']}")
                        seq.insert(13, "station_name", station_cfg["name"])
                        seq.insert(14, "station_lat_deg", float(station_cfg["lat_deg"]))
                        seq.insert(15, "station_lon_deg", float(station_cfg["lon_deg"]))
                        seq.insert(16, "station_alt_m", float(station_cfg["alt_m"]))
                        seq.insert(17, "center_freq_hz", simulation_freq)
                        seq.insert(18, "source_center_freq_hz", source_freq)
                        seq.insert(19, "simulation_center_freq_hz", simulation_freq)
                        seq.insert(20, "frequency_scale_factor", frequency_scale_factor)
                        seq["b_hz"] = b_hz
                        seq["k_hz_per_s"] = k_hz_per_s
                        seq["sigma_hz"] = sigma_hz
                        seq["sigma_base_hz"] = sigma_base_hz
                        seq["base_b_hz"] = raw_b
                        seq["base_k_hz_per_s"] = raw_k
                        seq["base_sigma_hz"] = raw_sigma
                        seq["noise_hz"] = noise
                        seq["f_sim_hz"] = f_geo + b_hz + k_hz_per_s * (t_rel - t0) + noise
                        seq["mode"] = "controlled_starlink"
                        seq["observation_id"] = pd.NA
                        seq["label"] = target["norad"]
                        seq["random_seed"] = args.seed
                        seq["config_version"] = config_version
                        seq["n_time_points"] = len(seq)
                        seq["window_duration_s"] = window_duration_s
                        rows.append(seq)
    if not rows:
        fail("没有生成任何 stress 序列")
    dataset = pd.concat(rows, ignore_index=True)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "experiment_name": stress_cfg["experiment_name"],
        "mode": "controlled_starlink",
        "observation_id": None,
        "target": {"name": target["name"], "norad_id": target["norad"]},
        "known_nearest_neighbor": neighbor_cfg,
        "source_center_freq_hz": source_freq,
        "simulation_center_freq_hz": simulation_freq,
        "frequency_scale_factor": frequency_scale_factor,
        "station": station_cfg,
        "tle_source_path": str(args.tle_file),
        "error_model_variants": stress_cfg["error_model_variants"],
        "sigma_multipliers": stress_cfg["sigma_multipliers"],
        "partial_pass_windows": stress_cfg["partial_pass_windows"],
        "candidate_limits": stress_cfg["candidate_limits"],
        "scenarios": scenarios,
        "num_sims_per_setting": num_sims,
        "total_rows": int(len(dataset)),
        "total_sequences": int(dataset["sequence_id"].nunique()),
        "pass_window_summary": pass_info,
        "window_summary": dataset.groupby("partial_pass_window").agg(n_time_points=("t_rel_s", "nunique"), window_duration_s=("window_duration_s", "first")).reset_index().to_dict(orient="records"),
        "random_seed": args.seed,
        "skipped_windows": skipped_windows,
        "parameter_ranges_before_scaling": base_ranges,
        "parameter_ranges_after_scaling": after_scaling,
        "notes": [
            "controlled near-neighbor stress / robustness baseline, not attack evaluation",
            "observation_id is null; 9424971 is not used",
            "registered_frequency_offset_hz is treated as registered offset / effective constant frequency bias, not pure CFO truth",
            "frequency_scaled is a frequency sensitivity setting, not true Starlink Ku-band CFO distribution",
            "sigma_multiplier only scales sigma after the selected error_model_variant scaling",
        ],
    }
    return dataset, manifest


def main() -> int:
    args = parse_args()
    try:
        check_outputs([args.output, args.manifest], args.overwrite)
        dataset, manifest = build_dataset(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(args.output, index=False)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(f"near-neighbor stress dataset 完成: {args.output}")
    print(f"序列数: {manifest['total_sequences']}, 行数: {manifest['total_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
