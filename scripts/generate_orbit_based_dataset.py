#!/usr/bin/env python
"""Generate orbit-based v1 frequency-offset simulation datasets."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from skyfield.api import EarthSatellite, load, wgs84


C_MPS = 299_792_458.0
SCENARIOS = ["clean", "offset_only", "offset_plus_noise", "offset_linear_noise"]


class InputError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate orbit-based simulation dataset v1.")
    parser.add_argument("--orbit-config", required=True, type=Path)
    parser.add_argument("--sim-config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise InputError(message)


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"配置文件不存在: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"配置文件不是有效 YAML 字典: {path}")
    return data


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def get_ranges(sim_config: dict[str, Any], range_type: str) -> tuple[str, dict[str, list[float]]]:
    ranges: dict[str, list[float]] = {}
    for name in ["b_hz", "k_hz_per_s", "sigma_hz"]:
        values = sim_config.get("parameters", {}).get(name, {}).get(f"{range_type}_range")
        if not isinstance(values, list) or len(values) != 2:
            fail(f"仿真配置缺少有效范围: {name}.{range_type}_range")
        ranges[name] = [float(values[0]), float(values[1])]
    version = sim_config.get("model", {}).get("name") or "effective_cfo_simulation_v1"
    return version, ranges


def parse_tle_file(path: Path, ts) -> tuple[list[dict[str, Any]], dict[str, EarthSatellite]]:
    if not path.exists():
        fail(f"TLE 文件不存在: {path}")
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: list[dict[str, Any]] = []
    sats: dict[str, EarthSatellite] = {}
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            i += 1
            continue
        sat = EarthSatellite(line1, line2, name, ts)
        norad = line1[2:7].strip()
        entry = {
            "satellite_name": name,
            "norad_id": norad,
            "tle_line1": line1,
            "tle_line2": line2,
            "epoch": sat.epoch.utc_iso(),
            "inclination_deg": float(line2[8:16]),
            "mean_motion_rev_per_day": float(line2[52:63]),
            "tle_source": str(path),
        }
        entries.append(entry)
        sats[name.upper()] = sat
        sats[norad] = sat
        i += 3
    if not entries:
        fail(f"TLE 文件没有解析到标准三行 TLE: {path}")
    return entries, sats


def satellite_from_config(config: dict[str, Any], ts) -> tuple[EarthSatellite, dict[str, Any], int]:
    tle = config.get("tle", {})
    if tle.get("line1") and tle.get("line2"):
        line1 = str(tle["line1"])
        line2 = str(tle["line2"])
        name = str(tle.get("line0") or tle.get("target_name") or f"NORAD {line1[2:7].strip()}")
        sat = EarthSatellite(line1, line2, name, ts)
        entry = {
            "satellite_name": name,
            "norad_id": str(tle.get("target_norad_id") or line1[2:7].strip()),
            "tle_line1": line1,
            "tle_line2": line2,
            "epoch": sat.epoch.utc_iso(),
            "inclination_deg": float(line2[8:16]),
            "mean_motion_rev_per_day": float(line2[52:63]),
            "tle_source": str(tle.get("source", "config_inline_tle")),
        }
        return sat, entry, 1

    tle_file = tle.get("file")
    if not tle_file:
        fail("orbit 配置缺少 tle.line1/line2 或 tle.file")
    entries, sats = parse_tle_file(Path(tle_file), ts)
    key = str(tle.get("target_name") or tle.get("target_norad_id") or "").upper()
    if key not in sats:
        fail(f"target 未在 TLE 文件中找到: {key}")
    entry = next(e for e in entries if e["satellite_name"].upper() == key or e["norad_id"] == key)
    entry["tle_source"] = str(tle_file)
    return sats[key], entry, len(entries)


def validate_mode(config: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    mode = config.get("mode")
    if mode not in ["controlled_starlink", "satnogs_observation", "legacy_iridium_observation"]:
        fail(f"不支持的 mode: {mode}")

    target_norad = str(target["norad_id"])
    tle_cfg_norad = config.get("tle", {}).get("target_norad_id")
    if tle_cfg_norad not in (None, "") and str(tle_cfg_norad) != target_norad:
        fail("配置中的 tle.target_norad_id 与实际 TLE NORAD 不一致")

    if mode == "controlled_starlink":
        if config.get("observation", {}).get("observation_id") not in (None, ""):
            fail("controlled_starlink 模式不得使用 SatNOGS observation_id")
        if not target["satellite_name"].upper().startswith("STARLINK"):
            fail("controlled_starlink 模式必须选择 STARLINK target")
        return {
            "observation_id": None,
            "observation_source": "controlled_manual",
            "station_source": "controlled_manual",
            "frequency_source": "controlled_manual",
            "time_window_source": "auto_pass_search",
        }

    obs = config.get("observation")
    if not isinstance(obs, dict) or obs.get("observation_id") in (None, ""):
        fail(f"{mode} 模式必须包含 observation.observation_id")
    obs_norad = obs.get("norad_id")
    if obs_norad in (None, ""):
        fail(f"{mode} 模式必须包含 observation.norad_id")
    if str(obs_norad) != target_norad:
        fail("observation NORAD does not match target TLE NORAD; refusing to mix SatNOGS observation with unrelated TLE")

    if mode == "legacy_iridium_observation":
        tle_source = str(config.get("tle", {}).get("source", ""))
        tle_file = str(config.get("tle", {}).get("file", ""))
        if "starlink_tle" in tle_file.lower() or tle_source == "local_starlink_tle":
            fail("legacy_iridium_observation 模式不得使用 data/tle/starlink_tle.txt")

    return {
        "observation_id": obs.get("observation_id"),
        "observation_source": obs.get("source", mode),
        "station_source": obs.get("source", mode),
        "frequency_source": obs.get("source", mode),
        "time_window_source": "satnogs_observation",
    }


def build_time_grid(config: dict[str, Any], source_info: dict[str, Any]) -> tuple[list[datetime], dict[str, Any]]:
    mode = config["mode"]
    step_s = float(config.get("simulation", {}).get("step_s", config.get("time_window", {}).get("step_s", 1)))
    if step_s <= 0:
        fail("step_s 必须为正数")
    if mode in ["satnogs_observation", "legacy_iridium_observation"]:
        obs = config["observation"]
        start = parse_utc(obs["start_utc"])
        end = parse_utc(obs["end_utc"])
        if end <= start:
            fail("observation.end_utc 必须晚于 start_utc")
        count = int((end - start).total_seconds() // step_s) + 1
        times = [start + timedelta(seconds=i * step_s) for i in range(count)]
        if times[-1] < end:
            times.append(end)
        return times, {
            **source_info,
            "pass_start_utc": times[0].isoformat().replace("+00:00", "Z"),
            "pass_end_utc": times[-1].isoformat().replace("+00:00", "Z"),
            "duration_s": float((times[-1] - times[0]).total_seconds()),
            "step_s": step_s,
            "num_time_points": len(times),
            "truncated": False,
        }

    tw = config.get("time_window", {})
    if tw.get("mode") != "auto_pass_search":
        fail("controlled_starlink 模式要求 time_window.mode=auto_pass_search")
    start = parse_utc(tw["search_start_utc"])
    duration_h = float(tw["search_duration_h"])
    times = [start + timedelta(seconds=i * step_s) for i in range(int(duration_h * 3600 // step_s) + 1)]
    return times, {
        **source_info,
        "search_min_elevation_deg": float(tw["min_elevation_deg"]),
        "max_pass_duration_s": float(tw["max_pass_duration_s"]),
        "step_s": step_s,
    }


def select_auto_pass(satellite, station, ts, times: list[datetime], info: dict[str, Any]) -> tuple[list[datetime], dict[str, Any]]:
    sf_times = ts.from_datetimes(times)
    elevation = (satellite - station).at(sf_times).altaz()[0].degrees
    visible = elevation >= float(info["search_min_elevation_deg"])
    if not np.any(visible):
        fail("指定搜索窗口内没有找到可见 pass")
    idx = np.flatnonzero(visible)
    segments: list[tuple[int, int]] = []
    start = prev = int(idx[0])
    for raw in idx[1:]:
        current = int(raw)
        if current == prev + 1:
            prev = current
        else:
            segments.append((start, prev))
            start = prev = current
    segments.append((start, prev))
    s, e = segments[0]
    max_points = int(float(info["max_pass_duration_s"]) // float(info["step_s"])) + 1
    if e - s + 1 > max_points:
        e = s + max_points - 1
    selected = times[s : e + 1]
    selected_elev = elevation[s : e + 1]
    info.update(
        {
            "pass_start_utc": selected[0].isoformat().replace("+00:00", "Z"),
            "pass_end_utc": selected[-1].isoformat().replace("+00:00", "Z"),
            "duration_s": float((selected[-1] - selected[0]).total_seconds()),
            "num_time_points": len(selected),
            "max_elevation_deg": float(np.max(selected_elev)),
            "min_elevation_deg": float(np.min(selected_elev)),
        }
    )
    return selected, info


def compute_geo_curve(satellite, station, ts, times: list[datetime], center_freq_hz: float, step_s: float) -> tuple[pd.DataFrame, dict[str, float]]:
    sf_times = ts.from_datetimes(times)
    topocentric = (satellite - station).at(sf_times)
    elevation = topocentric.altaz()[0].degrees
    range_m = topocentric.distance().m
    range_rate_mps = np.gradient(range_m, step_s)
    doppler_hz = -center_freq_hz * range_rate_mps / C_MPS
    f_geo = center_freq_hz + doppler_hz
    start = times[0]
    df = pd.DataFrame(
        {
            "t_abs_utc": [t.isoformat().replace("+00:00", "Z") for t in times],
            "t_rel_s": [(t - start).total_seconds() for t in times],
            "elevation_deg": elevation,
            "range_m": range_m,
            "range_rate_mps": range_rate_mps,
            "doppler_hz": doppler_hz,
            "f_geo_tle_hz": f_geo,
        }
    )
    return df, {
        "max_elevation_deg": float(np.max(elevation)),
        "min_elevation_deg": float(np.min(elevation)),
    }


def generate_simulations(
    geo: pd.DataFrame,
    config: dict[str, Any],
    target: dict[str, Any],
    source_info: dict[str, Any],
    ranges: dict[str, list[float]],
    config_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sim_cfg = config["simulation"]
    scenarios = sim_cfg["scenarios"]
    num_sims = int(sim_cfg["num_sims_per_target"])
    seed = int(sim_cfg["seed"])
    range_type = sim_cfg["range_type"]
    rng = np.random.default_rng(seed)
    t_rel = geo["t_rel_s"].to_numpy(float)
    f_geo = geo["f_geo_tle_hz"].to_numpy(float)
    t0 = float(np.mean(t_rel))
    rows: list[pd.DataFrame] = []
    seq_rows: list[dict[str, Any]] = []
    counter = 1
    station = config["station"]

    for scenario in scenarios:
        if scenario not in SCENARIOS:
            fail(f"不支持的 scenario: {scenario}")
        for sample_index in range(1, num_sims + 1):
            b = k = sigma = 0.0
            if scenario in ["offset_only", "offset_plus_noise", "offset_linear_noise"]:
                b = float(rng.uniform(*ranges["b_hz"]))
            if scenario == "offset_linear_noise":
                k = float(rng.uniform(*ranges["k_hz_per_s"]))
            if scenario in ["offset_plus_noise", "offset_linear_noise"]:
                sigma = float(rng.uniform(*ranges["sigma_hz"]))
            noise = rng.normal(0.0, sigma, len(geo)) if sigma > 0 else np.zeros(len(geo))
            f_sim = f_geo + b + k * (t_rel - t0) + noise
            sim_id = f"orbit_sim_{counter:06d}"
            counter += 1
            seq = geo.copy()
            seq.insert(0, "sim_id", sim_id)
            seq.insert(1, "observation_id", source_info["observation_id"])
            seq.insert(2, "observation_source", source_info["observation_source"])
            seq.insert(3, "target_name", target["satellite_name"])
            seq.insert(4, "target_norad_id", target["norad_id"])
            seq.insert(5, "scenario", scenario)
            seq.insert(6, "parameter_range_type", range_type)
            seq.insert(7, "sample_index", sample_index)
            seq.insert(8, "station_name", station["name"])
            seq.insert(9, "station_id", station.get("station_id"))
            seq.insert(10, "station_lat_deg", float(station["lat_deg"]))
            seq.insert(11, "station_lon_deg", float(station["lon_deg"]))
            seq.insert(12, "station_alt_m", float(station["alt_m"]))
            seq.insert(13, "center_freq_hz", float(config["frequency"]["center_freq_hz"]))
            seq["b_hz"] = b
            seq["k_hz_per_s"] = k
            seq["sigma_hz"] = sigma
            seq["noise_hz"] = noise
            seq["f_sim_hz"] = f_sim
            seq["label"] = str(target["norad_id"])
            seq["random_seed"] = seed
            seq["config_version"] = config_version
            rows.append(seq)
            seq_rows.append({"sim_id": sim_id, "scenario": scenario, "row_count": len(seq)})

    return pd.concat(rows, ignore_index=True), pd.DataFrame(seq_rows)


def make_plots(dataset: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    base = dataset.drop_duplicates("t_abs_utc").sort_values("t_rel_s")

    plots = [
        ("orbit_pass_elevation.png", "elevation_deg", "Orbit pass elevation", "elevation (deg)"),
        ("orbit_geo_doppler_curve.png", "doppler_hz", "Orbit geo Doppler curve", "doppler_hz"),
    ]
    for filename, column, title, ylabel in plots:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(base["t_rel_s"], base[column])
        ax.set_title(title)
        ax.set_xlabel("t_rel_s (s)")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        fig.savefig(plots_dir / filename, dpi=160)
        plt.close(fig)

    example = dataset[dataset["scenario"] == "offset_linear_noise"]
    if not example.empty:
        sim_id = example["sim_id"].iloc[0]
        seq = example[example["sim_id"] == sim_id].sort_values("t_rel_s")
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(seq["t_rel_s"], seq["f_geo_tle_hz"], label="f_geo_tle_hz")
        ax.plot(seq["t_rel_s"], seq["f_sim_hz"], label="f_sim_hz", linewidth=1.1)
        ax.set_title(f"Orbit example simulation: {sim_id}")
        ax.set_xlabel("t_rel_s (s)")
        ax.set_ylabel("frequency (Hz)")
        ax.legend()
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        fig.savefig(plots_dir / "orbit_example_sim_timeseries.png", dpi=160)
        plt.close(fig)

    work = dataset.assign(delta_hz=dataset["f_sim_hz"] - dataset["f_geo_tle_hz"])
    scenarios = [s for s in SCENARIOS if s in set(work["scenario"])]
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(9, max(3, 2.2 * len(scenarios))))
    if len(scenarios) == 1:
        axes = [axes]
    for ax, scenario in zip(axes, scenarios):
        ax.hist(work.loc[work["scenario"] == scenario, "delta_hz"], bins=50, color="#2f6f8f", alpha=0.82)
        ax.set_title(scenario)
        ax.set_xlabel("f_sim_hz - f_geo_tle_hz (Hz)")
        ax.set_ylabel("count")
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "orbit_sim_delta_hist_by_scenario.png", dpi=160)
    plt.close(fig)


def notes_for_mode(mode: str) -> list[str]:
    notes = [
        "Do not mix SatNOGS observation conditions with unrelated TLE.",
        "registered_frequency_offset_hz is treated as registered offset / effective constant frequency bias, not pure CFO truth.",
        "This is not attack evaluation.",
    ]
    if mode == "controlled_starlink":
        notes.insert(1, "9424971 is not used for controlled Starlink simulation.")
    return notes


def write_manifest(
    path: Path,
    config: dict[str, Any],
    target: dict[str, Any],
    source_info: dict[str, Any],
    pass_info: dict[str, Any],
    ranges: dict[str, list[float]],
    dataset: pd.DataFrame,
    sequences: pd.DataFrame,
) -> None:
    sim_cfg = config["simulation"]
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": config["mode"],
        "observation_id": source_info["observation_id"],
        "observation_source": source_info["observation_source"],
        "target_name": target["satellite_name"],
        "target_norad_id": target["norad_id"],
        "tle_source": target["tle_source"],
        "station_source": source_info["station_source"],
        "frequency_source": source_info["frequency_source"],
        "time_window_source": source_info["time_window_source"],
        "station": config["station"],
        "center_freq_hz": float(config["frequency"]["center_freq_hz"]),
        **pass_info,
        "scenarios": sim_cfg["scenarios"],
        "range_type": sim_cfg["range_type"],
        "num_sims_per_target": int(sim_cfg["num_sims_per_target"]),
        "seed": int(sim_cfg["seed"]),
        "total_sequences": int(len(sequences)),
        "total_rows": int(len(dataset)),
        "parameter_ranges_used": ranges,
        "notes": notes_for_mode(config["mode"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(
    path: Path,
    config: dict[str, Any],
    target: dict[str, Any],
    source_info: dict[str, Any],
    pass_info: dict[str, Any],
    ranges: dict[str, list[float]],
    dataset: pd.DataFrame,
    sequences: pd.DataFrame,
) -> None:
    mode = config["mode"]
    if mode == "controlled_starlink":
        mode_text = (
            "本轮使用真实 Starlink TLE，但没有使用真实 SatNOGS observation 条件。"
            "station / frequency / time window 是受控实验配置。"
            "9424971 只是前一阶段 waterfall/residual 提取中的高质量样本，不参与本轮 Starlink orbit-based simulation。"
        )
    elif mode == "satnogs_observation":
        mode_text = "本轮使用真实 SatNOGS observation 条件，并已校验 observation NORAD 与 target TLE NORAD 一致。"
    else:
        mode_text = "本轮使用前期 accepted observation 对应的 TLE，不使用 Starlink TLE。"

    base = dataset.drop_duplicates("t_abs_utc")
    rows_per_scenario = dataset.groupby("scenario").size().astype(int).to_dict()
    seq_per_scenario = sequences.groupby("scenario").size().astype(int).to_dict()
    scenario_lines = "\n".join(
        f"| `{scenario}` | {seq_per_scenario.get(scenario, 0)} | {rows_per_scenario.get(scenario, 0)} |"
        for scenario in SCENARIOS
        if scenario in seq_per_scenario
    )
    stats = dataset.assign(delta_hz=dataset["f_sim_hz"] - dataset["f_geo_tle_hz"]).groupby("scenario")["delta_hz"].agg(["mean", "std", "min", "max", "count"])
    stat_lines = "\n".join(
        f"| `{idx}` | {row['mean']:.6f} | {row['std']:.6f} | {row['min']:.6f} | {row['max']:.6f} | {int(row['count'])} |"
        for idx, row in stats.iterrows()
    )
    report = f"""# Orbit-Based 仿真数据集报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 本轮模式

- mode：`{mode}`
- {mode_text}

## 2. 输入与来源

- target：`{target['satellite_name']}`
- NORAD ID：`{target['norad_id']}`
- TLE 来源：`{target['tle_source']}`
- observation_id：`{source_info['observation_id']}`
- observation_source：`{source_info['observation_source']}`
- station_source：`{source_info['station_source']}`
- frequency_source：`{source_info['frequency_source']}`
- time_window_source：`{source_info['time_window_source']}`

## 3. station / frequency / time window

- station：`{dataset['station_name'].iloc[0]}`，lat={dataset['station_lat_deg'].iloc[0]} deg，lon={dataset['station_lon_deg'].iloc[0]} deg，alt={dataset['station_alt_m'].iloc[0]} m
- center frequency：{dataset['center_freq_hz'].iloc[0]:.0f} Hz
- start：{pass_info['pass_start_utc']}
- end：{pass_info['pass_end_utc']}
- duration：{pass_info['duration_s']:.1f} s
- step：{pass_info['step_s']} s
- time points：{pass_info['num_time_points']}
- elevation range：{base['elevation_deg'].min():.3f} 到 {base['elevation_deg'].max():.3f} deg

## 4. Doppler 计算公式

```text
doppler_hz = - center_freq_hz * range_rate_mps / c
f_geo_tle_hz = center_freq_hz + doppler_hz
```

`range_rate_mps` 使用相邻 range 的有限差分估计。符号约定是第一版工程约定，后续应结合真实样本或 STRF 结果做 sanity check。

## 5. 频率范围

- `f_geo_tle_hz` min：{base['f_geo_tle_hz'].min():.6f} Hz
- `f_geo_tle_hz` max：{base['f_geo_tle_hz'].max():.6f} Hz
- `f_geo_tle_hz` range：{(base['f_geo_tle_hz'].max() - base['f_geo_tle_hz'].min()):.6f} Hz
- `doppler_hz` min：{base['doppler_hz'].min():.6f} Hz
- `doppler_hz` max：{base['doppler_hz'].max():.6f} Hz
- `doppler_hz` range：{(base['doppler_hz'].max() - base['doppler_hz'].min()):.6f} Hz

## 6. 参数范围

| 参数 | main_range |
|---|---|
| `b_hz` | `{ranges['b_hz']}` |
| `k_hz_per_s` | `{ranges['k_hz_per_s']}` |
| `sigma_hz` | `{ranges['sigma_hz']}` |

## 7. 生成场景

| scenario | 序列数 | 行数 |
|---|---:|---:|
{scenario_lines}

## 8. f_sim_hz - f_geo_tle_hz 统计

| scenario | mean | std | min | max | count |
|---|---:|---:|---:|---:|---:|
{stat_lines}

## 9. 当前结果说明什么

本轮结果说明 TLE-based Doppler 生成链路跑通，并能在 `f_geo_tle_hz` 上叠加 registered offset / linear drift / first-order Gaussian noise。

## 10. 当前结果不能说明什么

- 不能说明真实 SatNOGS observation 对齐，除非 mode 为 `satnogs_observation`；
- 不能说明攻击成功率；
- `registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias，不是 pure CFO truth；
- noise 是第一版高斯近似。

## 11. 下一步

下一步应建立多候选 Starlink TLE 库，在同一 station / frequency / time window 下生成候选 `f_geo_tle_hz`，再进入 orbit-based matcher。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        validate_outputs(
            [
                args.output,
                args.manifest,
                args.report,
                args.plots_dir / "orbit_pass_elevation.png",
                args.plots_dir / "orbit_geo_doppler_curve.png",
                args.plots_dir / "orbit_example_sim_timeseries.png",
                args.plots_dir / "orbit_sim_delta_hist_by_scenario.png",
            ],
            args.overwrite,
        )
        config = read_yaml(args.orbit_config)
        sim_config = read_yaml(args.sim_config)
        config_version, ranges = get_ranges(sim_config, config["simulation"]["range_type"])

        ts = load.timescale()
        satellite, target, _tle_count = satellite_from_config(config, ts)
        source_info = validate_mode(config, target)
        station_cfg = config["station"]
        station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
        times, pass_info = build_time_grid(config, source_info)
        if config["mode"] == "controlled_starlink":
            times, pass_info = select_auto_pass(satellite, station, ts, times, pass_info)
        geo, geo_stats = compute_geo_curve(satellite, station, ts, times, float(config["frequency"]["center_freq_hz"]), float(pass_info["step_s"]))
        pass_info.update(geo_stats)
        pass_info.setdefault("pass_start_utc", times[0].isoformat().replace("+00:00", "Z"))
        pass_info.setdefault("pass_end_utc", times[-1].isoformat().replace("+00:00", "Z"))
        pass_info.setdefault("duration_s", float((times[-1] - times[0]).total_seconds()))
        pass_info.setdefault("num_time_points", len(times))

        dataset, sequences = generate_simulations(geo, config, target, source_info, ranges, config_version)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(args.output, index=False)
        write_manifest(args.manifest, config, target, source_info, pass_info, ranges, dataset, sequences)
        make_plots(dataset, args.plots_dir)
        write_report(args.report, config, target, source_info, pass_info, ranges, dataset, sequences)
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    print(f"生成完成: {args.output}")
    print(f"mode={config['mode']}, target={target['satellite_name']}, norad={target['norad_id']}")
    print(f"observation_id={source_info['observation_id']}, source={source_info['observation_source']}")
    print(f"rows={len(dataset)}, sequences={len(sequences)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
