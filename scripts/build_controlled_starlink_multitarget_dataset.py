#!/usr/bin/env python
"""Build controlled Starlink multi-target orbit simulation dataset."""

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
SCENARIOS = ["clean", "offset_only", "offset_plus_noise", "offset_linear_noise"]
VARIANTS = ["unscaled", "frequency_scaled"]


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
    parser.add_argument("--target-list", required=True, type=Path)
    parser.add_argument("--target-count", type=int, default=None)
    parser.add_argument("--num-sims-per-target", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--simulation-center-freq-hz", type=float, default=None)
    parser.add_argument("--source-center-freq-hz", type=float, default=None)
    parser.add_argument("--error-model-variant", choices=VARIANTS, default="unscaled")
    parser.add_argument("--candidate-limit", type=int, default=None)
    parser.add_argument("--experiment-name", default=None)
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


def select_targets(entries: list[dict[str, Any]], target_count: int) -> list[dict[str, Any]]:
    target = next((e for e in entries if e["name"].upper() == "STARLINK-1008" or e["norad"] == "44714"), None)
    if not target:
        fail("STARLINK-1008 / 44714 不在 TLE 文件中")
    for entry in entries:
        entry["score"] = abs(entry["inclination"] - target["inclination"]) + 10 * abs(entry["mean_motion"] - target["mean_motion"])
    selected = sorted(entries, key=lambda e: (e["score"], e["name"]))[:target_count]
    if target["norad"] not in {entry["norad"] for entry in selected}:
        selected = [target] + selected[: target_count - 1]
    selected = sorted(selected, key=lambda e: (0 if e["norad"] == target["norad"] else 1, e["score"], e["name"]))
    for idx, entry in enumerate(selected, 1):
        entry["target_rank"] = idx
        entry["selection_reason"] = "target_required" if entry["norad"] == target["norad"] else "similar_inclination_mean_motion"
    return selected


def load_ranges(sim_cfg: dict[str, Any], range_type: str) -> tuple[str, dict[str, list[float]]]:
    params = sim_cfg["parameters"]
    ranges: dict[str, list[float]] = {}
    for key in ["b_hz", "k_hz_per_s", "sigma_hz"]:
        values = params[key][f"{range_type}_range"]
        ranges[key] = [float(values[0]), float(values[1])]
    version = sim_cfg.get("model", {}).get("name", "effective_cfo_simulation_v1")
    return version, ranges


def scale_ranges(ranges: dict[str, list[float]], scale_factor: float, variant: str) -> dict[str, list[float]]:
    if variant == "unscaled":
        return {key: list(value) for key, value in ranges.items()}
    return {key: [value[0] * scale_factor, value[1] * scale_factor] for key, value in ranges.items()}


def find_pass(sat: EarthSatellite, station: Any, ts: Any, time_window: dict[str, Any]) -> tuple[tuple[list[datetime], dict[str, Any]] | None, str]:
    step = float(time_window.get("step_s", 1))
    start = parse_utc(time_window["search_start_utc"])
    duration_h = float(time_window.get("search_duration_h", 24))
    min_elevation = float(time_window["min_elevation_deg"])
    max_pass_duration_s = float(time_window["max_pass_duration_s"])
    times = [start + timedelta(seconds=i * step) for i in range(int(duration_h * 3600 // step) + 1)]
    skyfield_times = ts.from_datetimes(times)
    elevation = (sat - station).at(skyfield_times).altaz()[0].degrees
    visible_idx = np.flatnonzero(elevation >= min_elevation)
    if len(visible_idx) == 0:
        return None, "no_visible_pass"
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
    max_points = int(max_pass_duration_s // step) + 1
    if end_idx - start_idx + 1 > max_points:
        end_idx = start_idx + max_points - 1
    selected_times = times[start_idx : end_idx + 1]
    selected_elevation = elevation[start_idx : end_idx + 1]
    pass_info = {
        "pass_start_utc": selected_times[0].isoformat().replace("+00:00", "Z"),
        "pass_end_utc": selected_times[-1].isoformat().replace("+00:00", "Z"),
        "duration_s": float((selected_times[-1] - selected_times[0]).total_seconds()),
        "step_s": step,
        "num_time_points": len(selected_times),
        "max_elevation_deg": float(np.max(selected_elevation)),
        "min_elevation_deg": float(np.min(selected_elevation)),
    }
    return (selected_times, pass_info), ""


def geo_curve(sat: EarthSatellite, station: Any, ts: Any, times: list[datetime], freq_hz: float, step_s: float) -> pd.DataFrame:
    skyfield_times = ts.from_datetimes(times)
    topo = (sat - station).at(skyfield_times)
    elevation = topo.altaz()[0].degrees
    range_m = topo.distance().m
    range_rate_mps = np.gradient(range_m, step_s)
    doppler_hz = -freq_hz * range_rate_mps / C_MPS
    f_geo_hz = freq_hz + doppler_hz
    start = times[0]
    return pd.DataFrame(
        {
            "t_abs_utc": [dt.isoformat().replace("+00:00", "Z") for dt in times],
            "t_rel_s": [(dt - start).total_seconds() for dt in times],
            "elevation_deg": elevation,
            "range_m": range_m,
            "range_rate_mps": range_rate_mps,
            "doppler_hz": doppler_hz,
            "f_geo_tle_hz": f_geo_hz,
        }
    )


def experiment_defaults(orbit_cfg: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    ku_cfg = orbit_cfg.get("ku_band_experiment", {})
    simulation_cfg = orbit_cfg.get("simulation", {})
    source_freq = float(args.source_center_freq_hz or ku_cfg.get("source_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    simulation_freq = float(args.simulation_center_freq_hz or ku_cfg.get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    return {
        "experiment_name": args.experiment_name or ku_cfg.get("experiment_name", "controlled_starlink_multitarget"),
        "source_center_freq_hz": source_freq,
        "simulation_center_freq_hz": simulation_freq,
        "frequency_scale_factor": simulation_freq / source_freq,
        "target_count": int(args.target_count or ku_cfg.get("target_count") or 10),
        "candidate_limit": int(args.candidate_limit or ku_cfg.get("candidate_limit") or 200),
        "num_sims_per_target": int(args.num_sims_per_target or ku_cfg.get("num_sims_per_target") or simulation_cfg.get("num_sims_per_target") or 50),
    }


def build_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ts = load.timescale()
    orbit_cfg = read_yaml(args.orbit_config)
    sim_cfg = read_yaml(args.sim_config)
    if orbit_cfg.get("mode") != "controlled_starlink":
        fail("本脚本只支持 controlled_starlink；不得混用 SatNOGS observation_id 或 9424971")

    defaults = experiment_defaults(orbit_cfg, args)
    entries = parse_tle(args.tle_file, ts)
    targets = select_targets(entries, defaults["target_count"])
    range_type = orbit_cfg["simulation"]["range_type"]
    config_version, base_ranges = load_ranges(sim_cfg, range_type)
    used_ranges = scale_ranges(base_ranges, defaults["frequency_scale_factor"], args.error_model_variant)
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(
        float(station_cfg["lat_deg"]),
        float(station_cfg["lon_deg"]),
        elevation_m=float(station_cfg["alt_m"]),
    )
    rng = np.random.default_rng(args.seed)

    rows: list[pd.DataFrame] = []
    sequences: list[dict[str, Any]] = []
    passes: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    sim_counter = 1
    freq_hz = defaults["simulation_center_freq_hz"]
    scale_factor = defaults["frequency_scale_factor"] if args.error_model_variant == "frequency_scaled" else 1.0

    for target in targets:
        pass_result, reason = find_pass(target["sat"], station, ts, orbit_cfg["time_window"])
        if pass_result is None:
            skipped.append({"target_name": target["name"], "target_norad_id": target["norad"], "reason": reason})
            continue
        times, pass_info = pass_result
        pass_id = f"pass_{target['norad']}"
        geo = geo_curve(target["sat"], station, ts, times, freq_hz, pass_info["step_s"])
        passes.append({"pass_id": pass_id, "target_name": target["name"], "target_norad_id": target["norad"], **pass_info})
        t_rel = geo["t_rel_s"].to_numpy(float)
        f_geo = geo["f_geo_tle_hz"].to_numpy(float)
        t0 = float(np.mean(t_rel))

        for scenario in SCENARIOS:
            for sample_index in range(1, defaults["num_sims_per_target"] + 1):
                base_b = base_k = base_sigma = 0.0
                if scenario in ["offset_only", "offset_plus_noise", "offset_linear_noise"]:
                    base_b = float(rng.uniform(*base_ranges["b_hz"]))
                if scenario == "offset_linear_noise":
                    base_k = float(rng.uniform(*base_ranges["k_hz_per_s"]))
                if scenario in ["offset_plus_noise", "offset_linear_noise"]:
                    base_sigma = float(rng.uniform(*base_ranges["sigma_hz"]))

                b_hz = base_b * scale_factor
                k_hz_per_s = base_k * scale_factor
                sigma_hz = base_sigma * scale_factor
                noise = rng.normal(0, sigma_hz, len(geo)) if sigma_hz > 0 else np.zeros(len(geo))

                seq = geo.copy()
                sim_id = f"mt_orbit_sim_{sim_counter:06d}"
                sim_counter += 1
                seq.insert(0, "sim_id", sim_id)
                seq.insert(1, "sequence_id", sim_id)
                seq.insert(2, "target_name", target["name"])
                seq.insert(3, "target_norad_id", target["norad"])
                seq.insert(4, "scenario", scenario)
                seq.insert(5, "error_model_variant", args.error_model_variant)
                seq.insert(6, "parameter_range_type", range_type)
                seq.insert(7, "sample_index", sample_index)
                seq.insert(8, "station_name", station_cfg["name"])
                seq.insert(9, "station_lat_deg", float(station_cfg["lat_deg"]))
                seq.insert(10, "station_lon_deg", float(station_cfg["lon_deg"]))
                seq.insert(11, "station_alt_m", float(station_cfg["alt_m"]))
                seq.insert(12, "center_freq_hz", freq_hz)
                seq.insert(13, "source_center_freq_hz", defaults["source_center_freq_hz"])
                seq.insert(14, "simulation_center_freq_hz", freq_hz)
                seq.insert(15, "frequency_scale_factor", defaults["frequency_scale_factor"])
                seq.insert(16, "pass_id", pass_id)
                seq.insert(17, "pass_start_utc", pass_info["pass_start_utc"])
                seq.insert(18, "pass_end_utc", pass_info["pass_end_utc"])
                seq["base_b_hz"] = base_b
                seq["base_k_hz_per_s"] = base_k
                seq["base_sigma_hz"] = base_sigma
                seq["b_hz"] = b_hz
                seq["k_hz_per_s"] = k_hz_per_s
                seq["sigma_hz"] = sigma_hz
                seq["noise_hz"] = noise
                seq["t_centered_s"] = t_rel - t0
                seq["f_sim_hz"] = f_geo + b_hz + k_hz_per_s * (t_rel - t0) + noise
                seq["label"] = target["norad"]
                seq["random_seed"] = args.seed
                seq["config_version"] = config_version
                rows.append(seq)
                sequences.append(
                    {
                        "sim_id": sim_id,
                        "pass_id": pass_id,
                        "target_norad_id": target["norad"],
                        "scenario": scenario,
                        "error_model_variant": args.error_model_variant,
                        "row_count": len(seq),
                    }
                )

    if len(passes) < 5:
        print(f"警告: 成功 target 数不足 5: {len(passes)}", file=sys.stderr)
    if not rows:
        fail("没有生成任何序列，请检查 pass 搜索条件")

    dataset = pd.concat(rows, ignore_index=True)
    target_list = pd.DataFrame(
        [
            {
                "target_rank": target["target_rank"],
                "target_name": target["name"],
                "target_norad_id": target["norad"],
                "tle_epoch": target["epoch"],
                "inclination_deg": target["inclination"],
                "mean_motion_rev_per_day": target["mean_motion"],
                "selection_reason": target["selection_reason"],
            }
            for target in targets
        ]
    )
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "experiment_name": defaults["experiment_name"],
        "mode": "controlled_starlink",
        "observation_id": None,
        "observation_source": "controlled_manual",
        "error_model_variant": args.error_model_variant,
        "source_center_freq_hz": defaults["source_center_freq_hz"],
        "simulation_center_freq_hz": freq_hz,
        "center_freq_hz": freq_hz,
        "frequency_scale_factor": defaults["frequency_scale_factor"],
        "target_count": defaults["target_count"],
        "target_count_requested": defaults["target_count"],
        "targets_generated": len(passes),
        "candidate_limit": defaults["candidate_limit"],
        "num_sims_per_target": defaults["num_sims_per_target"],
        "scenarios": SCENARIOS,
        "range_type": range_type,
        "station": station_cfg,
        "tle_source_path": str(args.tle_file),
        "target_list": target_list.to_dict(orient="records"),
        "candidate_selection_summary": {
            "method": "similarity_to_STARLINK_1008_by_inclination_and_mean_motion",
            "candidate_limit": defaults["candidate_limit"],
            "target_required": "STARLINK-1008 / 44714",
        },
        "pass_window_summary": passes,
        "passes": passes,
        "skipped_targets": skipped,
        "parameter_ranges_before_scaling": base_ranges,
        "parameter_ranges_after_scaling": used_ranges,
        "random_seed": args.seed,
        "seed": args.seed,
        "total_sequences": len(sequences),
        "sequence_count": len(sequences),
        "total_rows": len(dataset),
        "row_count": len(dataset),
        "notes": [
            "controlled Starlink Ku-band frequency variant baseline; not SatNOGS observation; not attack evaluation",
            "observation_id is null; 9424971 is not used",
            "registered_frequency_offset_hz is treated as registered offset / effective constant frequency bias, not pure CFO truth",
            "frequency_scaled is a frequency sensitivity setting, not true Starlink Ku-band CFO distribution",
            "noise is a first-order Gaussian approximation",
        ],
    }
    return dataset, target_list, manifest


def main() -> int:
    args = parse_args()
    try:
        check_outputs([args.output, args.manifest, args.target_list], args.overwrite)
        dataset, target_list, manifest = build_dataset(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(args.output, index=False)
        args.target_list.parent.mkdir(parents=True, exist_ok=True)
        target_list.to_csv(args.target_list, index=False)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    print(f"多 target 数据集生成完成: {args.output}")
    print(f"error_model_variant: {args.error_model_variant}")
    print(f"center_freq_hz: {manifest['simulation_center_freq_hz']:.0f}")
    print(f"frequency_scale_factor: {manifest['frequency_scale_factor']:.6f}")
    print(f"成功 target 数: {manifest['targets_generated']}, 序列数: {manifest['total_sequences']}, 行数: {manifest['total_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
