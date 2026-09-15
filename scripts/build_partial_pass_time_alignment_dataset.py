#!/usr/bin/env python
"""Build controlled Starlink partial-pass / time-alignment stress dataset."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    raise InputError(message)


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"配置文件不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def parameter_ranges(sim_cfg: dict[str, Any], range_type: str) -> tuple[str, dict[str, list[float]]]:
    ranges = {}
    for key in ["b_hz", "k_hz_per_s", "sigma_hz"]:
        vals = sim_cfg["parameters"][key][f"{range_type}_range"]
        ranges[key] = [float(vals[0]), float(vals[1])]
    return sim_cfg.get("model", {}).get("name", "effective_cfo_simulation_v1"), ranges


def get_full_pass_geometry(source_dataset: Path) -> pd.DataFrame:
    if not source_dataset.exists():
        fail(f"source stress dataset 不存在: {source_dataset}")
    cols = [
        "target_name",
        "target_norad_id",
        "pass_id",
        "station_name",
        "station_lat_deg",
        "station_lon_deg",
        "station_alt_m",
        "center_freq_hz",
        "source_center_freq_hz",
        "simulation_center_freq_hz",
        "frequency_scale_factor",
        "t_abs_utc",
        "t_rel_s",
        "elevation_deg",
        "range_m",
        "range_rate_mps",
        "doppler_hz",
        "f_geo_tle_hz",
    ]
    df = pd.read_csv(source_dataset, usecols=cols)
    geom = df.drop_duplicates("t_abs_utc").sort_values("t_rel_s").reset_index(drop=True)
    if geom.empty:
        fail("source stress dataset 中无法提取 full pass geometry")
    return geom


def window_indices(full_t: np.ndarray, duration: object, offset_s: float) -> np.ndarray:
    if str(duration) == "full":
        return np.arange(len(full_t))
    dur = float(duration)
    center = (float(full_t[0]) + float(full_t[-1])) / 2.0 + float(offset_s)
    start = center - dur / 2.0
    end = center + dur / 2.0
    idx = np.flatnonzero((full_t >= start - 1e-9) & (full_t <= end + 1e-9))
    return idx


def build_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    orbit = read_yaml(args.orbit_config)
    sim = read_yaml(args.sim_config)
    cfg = orbit.get("partial_pass_time_alignment_stress")
    if not cfg:
        fail("orbit config 缺少 partial_pass_time_alignment_stress 配置块")
    if orbit.get("mode") != "controlled_starlink" or cfg.get("observation_id") is not None:
        fail("Stage 3A 必须保持 controlled_starlink 且 observation_id=null")
    geom = get_full_pass_geometry(args.source_stress_dataset)
    target_cfg = cfg["target"]
    if str(geom["target_norad_id"].iloc[0]) != str(target_cfg["norad_id"]):
        fail("source stress geometry target 与 partial-pass target 不一致")
    config_version, base_ranges = parameter_ranges(sim, orbit["simulation"]["range_type"])
    freq_scale = float(cfg["simulation_center_freq_hz"]) / float(cfg["source_center_freq_hz"])
    scaled_ranges = {key: [value[0] * freq_scale, value[1] * freq_scale] for key, value in base_ranges.items()}
    sigma_multiplier = float(cfg["sigma_multiplier"])
    rng = np.random.default_rng(args.seed)
    full_t = geom["t_rel_s"].to_numpy(float)
    rows: list[pd.DataFrame] = []
    skipped: list[dict[str, object]] = []
    sequence_counter = 1
    windows: list[dict[str, object]] = []

    for duration in cfg["window_durations_s"]:
        offsets = [0] if str(duration) == "full" else cfg["window_center_offsets_s"]
        for offset in offsets:
            idx = window_indices(full_t, duration, float(offset))
            if len(idx) < 10:
                skipped.append({"window_duration_s": duration, "window_center_offset_s": offset, "reason": "too_few_points", "n_time_points": int(len(idx))})
                continue
            win = geom.iloc[idx].copy().reset_index(drop=True)
            start_rel = float(win["t_rel_s"].iloc[0])
            end_rel = float(win["t_rel_s"].iloc[-1])
            actual_duration = end_rel - start_rel
            win["t_window_rel_s"] = win["t_rel_s"] - start_rel
            windows.append(
                {
                    "window_duration_s": duration,
                    "window_center_offset_s": offset,
                    "window_start_rel_s": start_rel,
                    "window_end_rel_s": end_rel,
                    "actual_window_duration_s": actual_duration,
                    "n_time_points": int(len(win)),
                }
            )
            t_rel = win["t_rel_s"].to_numpy(float)
            t0 = float(np.mean(t_rel))
            f_geo = win["f_geo_tle_hz"].to_numpy(float)
            for sim_index in range(1, int(cfg["num_sims_per_setting"]) + 1):
                base_b = float(rng.uniform(*base_ranges["b_hz"]))
                base_sigma = float(rng.uniform(*base_ranges["sigma_hz"]))
                b_hz = base_b * freq_scale
                k_hz_per_s = 0.0
                sigma_base_hz = base_sigma * freq_scale
                sigma_hz = sigma_base_hz * sigma_multiplier
                noise = rng.normal(0, sigma_hz, len(win))
                sequence_id = f"pp_time_align_{sequence_counter:06d}"
                sequence_counter += 1
                seq = win[
                    [
                        "pass_id",
                        "station_name",
                        "station_lat_deg",
                        "station_lon_deg",
                        "station_alt_m",
                        "center_freq_hz",
                        "source_center_freq_hz",
                        "simulation_center_freq_hz",
                        "frequency_scale_factor",
                        "t_abs_utc",
                        "t_rel_s",
                        "t_window_rel_s",
                        "elevation_deg",
                        "range_m",
                        "range_rate_mps",
                        "doppler_hz",
                        "f_geo_tle_hz",
                    ]
                ].copy()
                seq.insert(0, "experiment_name", cfg["experiment_name"])
                seq.insert(1, "sequence_id", sequence_id)
                seq.insert(2, "sim_id", sequence_id)
                seq.insert(3, "target_name", target_cfg["name"])
                seq.insert(4, "target_norad_id", str(target_cfg["norad_id"]))
                seq.insert(5, "error_model_variant", cfg["error_model_variant"])
                seq.insert(6, "sigma_multiplier", sigma_multiplier)
                seq.insert(7, "scenario", cfg["scenario"])
                seq.insert(8, "sim_index", sim_index)
                seq.insert(9, "window_duration_s", str(duration))
                seq.insert(10, "window_center_offset_s", float(offset))
                seq.insert(11, "window_start_rel_s", start_rel)
                seq.insert(12, "window_end_rel_s", end_rel)
                seq["b_hz"] = b_hz
                seq["k_hz_per_s"] = k_hz_per_s
                seq["sigma_hz"] = sigma_hz
                seq["sigma_base_hz"] = sigma_base_hz
                seq["base_b_hz"] = base_b
                seq["base_sigma_hz"] = base_sigma
                seq["noise_hz"] = noise
                seq["f_sim_hz"] = f_geo + b_hz + k_hz_per_s * (t_rel - t0) + noise
                seq["mode"] = "controlled_starlink"
                seq["observation_id"] = pd.NA
                seq["label"] = str(target_cfg["norad_id"])
                seq["random_seed"] = args.seed
                seq["config_version"] = config_version
                seq["n_time_points"] = len(seq)
                seq["actual_window_duration_s"] = actual_duration
                rows.append(seq)
    if not rows:
        fail("没有生成任何 partial-pass sequence")
    dataset = pd.concat(rows, ignore_index=True)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "experiment_name": cfg["experiment_name"],
        "mode": "controlled_starlink",
        "observation_id": None,
        "target": cfg["target"],
        "hard_wrong_candidates": cfg["hard_wrong_candidates"],
        "source_center_freq_hz": cfg["source_center_freq_hz"],
        "simulation_center_freq_hz": cfg["simulation_center_freq_hz"],
        "frequency_scale_factor": freq_scale,
        "station": orbit["station"],
        "tle_source_path": str(args.tle_file),
        "error_model_variant": cfg["error_model_variant"],
        "sigma_multiplier": sigma_multiplier,
        "scenario": cfg["scenario"],
        "candidate_limit": cfg["candidate_limit"],
        "window_durations_s": cfg["window_durations_s"],
        "window_center_offsets_s": cfg["window_center_offsets_s"],
        "num_sims_per_setting": cfg["num_sims_per_setting"],
        "total_rows": int(len(dataset)),
        "total_sequences": int(dataset["sequence_id"].nunique()),
        "full_pass_summary": {
            "pass_start_utc": str(geom["t_abs_utc"].iloc[0]),
            "pass_end_utc": str(geom["t_abs_utc"].iloc[-1]),
            "duration_s": float(full_t[-1] - full_t[0]),
            "num_time_points": int(len(geom)),
        },
        "window_summary": windows,
        "skipped_windows": skipped,
        "parameter_ranges_before_scaling": base_ranges,
        "parameter_ranges_after_scaling": scaled_ranges,
        "random_seed": args.seed,
        "notes": [
            "controlled partial-pass / time-alignment stress, not attack evaluation",
            "observation_id is null; 9424971 is not used",
            "registered_frequency_offset_hz is treated as registered offset / effective constant frequency bias, not pure CFO truth",
            "frequency_scaled is a frequency sensitivity setting, not true Starlink Ku-band CFO distribution",
        ],
    }
    return dataset, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tle-file", required=True, type=Path)
    parser.add_argument("--orbit-config", required=True, type=Path)
    parser.add_argument("--sim-config", required=True, type=Path)
    parser.add_argument("--source-stress-dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        check_outputs([args.output, args.manifest], args.overwrite)
        dataset, manifest = build_dataset(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(args.output, index=False)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except InputError as exc:
        print(f"错误: {exc}")
        return 2
    print(f"partial-pass dataset 完成: {args.output}")
    print(f"sequences={manifest['total_sequences']}, rows={manifest['total_rows']}, skipped={len(manifest['skipped_windows'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
