#!/usr/bin/env python
"""Prepare orbit simulation case config from SatNOGS observation metadata."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml


ACCEPTED_FALLBACK_IDS = ["8535896", "8641460", "8707816", "8733468", "9424971"]
REPORT_PATH = Path("outputs/reports/orbit_case_prepare_report.md")


class PrepareError(ValueError):
    """User-facing preparation error."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare orbit simulation case from SatNOGS observation conditions."
    )
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--local-root", default=Path("data/satnogs_observations"), type=Path)
    parser.add_argument("--tle-file", required=True, type=Path)
    parser.add_argument("--allow-api", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise PrepareError(message)


def parse_utc(text: str) -> datetime:
    if not text:
        fail("UTC 时间字段为空")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def duration_s(start_utc: str, end_utc: str) -> float:
    return (parse_utc(end_utc) - parse_utc(start_utc)).total_seconds()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_catalog_tle(path: Path) -> dict[str, str]:
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 3:
        fail(f"catalog.tle 不符合三行 TLE 格式: {path}")
    return {"line0": lines[0].strip(), "line1": lines[1].strip(), "line2": lines[2].strip()}


def extract_client_metadata_frequency(data: dict[str, Any]) -> int | None:
    raw = data.get("client_metadata")
    if not raw:
        return None
    try:
        meta = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return None
    candidates = [
        meta.get("frequency") if isinstance(meta, dict) else None,
        meta.get("radio", {}).get("parameters", {}).get("rx-freq") if isinstance(meta, dict) else None,
    ]
    for value in candidates:
        if value not in (None, ""):
            return int(float(value))
    return None


def normalize_local_case(obs_id: str, strf_path: Path, catalog_path: Path | None) -> tuple[dict, dict]:
    data = read_json(strf_path)
    missing: list[str] = []

    def first(*names: str) -> Any:
        for name in names:
            if data.get(name) not in (None, ""):
                return data.get(name)
        return None

    start = first("start_utc", "start")
    end = first("end_utc", "end")
    freq = first("center_freq_hz", "observation_frequency", "frequency")
    norad = first("norad_id", "norad_cat_id")
    lat = first("site_lat", "station_lat", "lat")
    lon = first("site_lon", "station_lng", "station_lon", "lon")
    alt = first("site_elev", "station_alt", "site_alt", "alt_m")
    station_id = first("station_id", "satnogs_station_id", "ground_station")
    station_name = first("station_name", "site_name")

    for label, value in [
        ("start_utc", start),
        ("end_utc", end),
        ("center_freq_hz", freq),
        ("norad_id", norad),
        ("site_lat", lat),
        ("site_lon", lon),
        ("site_elev", alt),
    ]:
        if value in (None, ""):
            missing.append(label)

    tle = read_catalog_tle(catalog_path) if catalog_path and catalog_path.exists() else None
    if tle is None:
        missing.append("catalog.tle")

    info = {
        "source": "local_strf_ready",
        "strf_path": str(strf_path),
        "catalog_path": str(catalog_path) if catalog_path else "",
        "missing": missing,
        "actual_fields": sorted(data.keys()),
    }
    if missing:
        return {}, info

    config = build_config(
        obs_id=obs_id,
        source="local_strf_ready",
        start_utc=str(start),
        end_utc=str(end),
        norad_id=str(norad),
        station_name=str(station_name or f"satnogs_station_{station_id or 'unknown'}"),
        station_id=station_id,
        lat=float(lat),
        lon=float(lon),
        alt=float(alt),
        center_freq_hz=int(float(freq)),
        tle=tle,
        tle_source="local_catalog_tle",
    )
    return config, info


def find_local_case(obs_id: str, local_root: Path) -> tuple[dict, dict] | None:
    roots = [
        local_root,
        Path("data/source_observations"),
        Path("bridge/input"),
    ]
    for root in roots:
        strf_path = root / str(obs_id) / "strf_ready.json"
        catalog_path = root / str(obs_id) / "catalog.tle"
        if strf_path.exists():
            return normalize_local_case(obs_id, strf_path, catalog_path if catalog_path.exists() else None)
    return None


def fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "data-simulation-orbit-prepare/1.0"},
    )
    if response.status_code != 200:
        fail(f"SatNOGS API 请求失败: {url} status={response.status_code}")
    data = response.json()
    if not isinstance(data, dict):
        fail(f"SatNOGS API 返回不是 JSON object: {url}")
    return data


def find_tle_by_norad(tle_file: Path, norad_id: str) -> dict[str, str] | None:
    if not tle_file.exists():
        return None
    lines = [line.rstrip() for line in tle_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    for i in range(0, len(lines) - 2):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 ") and line1[2:7].strip() == str(norad_id):
            return {"line0": name, "line1": line1, "line2": line2}
    return None


def normalize_api_case(obs_id: str, tle_file: Path) -> tuple[dict, dict]:
    url = f"https://network.satnogs.org/api/observations/{obs_id}/"
    data = fetch_json(url)
    actual_fields = sorted(data.keys())
    missing: list[str] = []

    start = data.get("start_utc") or data.get("start")
    end = data.get("end_utc") or data.get("end")
    freq = data.get("observation_frequency") or data.get("center_frequency") or extract_client_metadata_frequency(data)
    norad = data.get("norad_cat_id") or data.get("norad_id")
    station_id = data.get("ground_station") or data.get("station_id") or data.get("station")
    station_name = data.get("station_name") or f"satnogs_station_{station_id or 'unknown'}"
    lat = data.get("station_lat")
    lon = data.get("station_lng") if data.get("station_lng") is not None else data.get("station_lon")
    alt = data.get("station_alt")

    station_api_used = False
    station_fields: list[str] = []
    if (lat is None or lon is None or alt is None) and station_id:
        station_data = fetch_json(f"https://network.satnogs.org/api/stations/{station_id}/")
        station_api_used = True
        station_fields = sorted(station_data.keys())
        lat = lat if lat is not None else station_data.get("lat")
        lon = lon if lon is not None else station_data.get("lng", station_data.get("lon"))
        alt = alt if alt is not None else station_data.get("alt")
        station_name = station_name or station_data.get("name")

    tle = None
    tle_source = ""
    if data.get("tle1") and data.get("tle2"):
        tle = {
            "line0": str(data.get("tle0") or data.get("sat_id") or f"NORAD {norad}"),
            "line1": str(data["tle1"]),
            "line2": str(data["tle2"]),
        }
        tle_source = "satnogs_api"
    elif norad is not None:
        tle = find_tle_by_norad(tle_file, str(norad))
        if tle:
            tle_source = "local_starlink_tle"

    for label, value in [
        ("start_utc", start),
        ("end_utc", end),
        ("center_freq_hz", freq),
        ("norad_id", norad),
        ("station_lat", lat),
        ("station_lon", lon),
        ("station_alt", alt),
        ("tle", tle),
    ]:
        if value in (None, ""):
            missing.append(label)

    info = {
        "source": "satnogs_api",
        "api_url": url,
        "actual_fields": actual_fields,
        "station_api_used": station_api_used,
        "station_api_fields": station_fields,
        "tle_source": tle_source,
        "missing": missing,
        "frequency_field": "observation_frequency"
        if data.get("observation_frequency") is not None
        else ("center_frequency" if data.get("center_frequency") is not None else "client_metadata"),
        "station_field_source": "observation_api"
        if data.get("station_lat") is not None and (data.get("station_lng") is not None or data.get("station_lon") is not None)
        else ("station_api" if station_api_used else "missing"),
    }
    if missing:
        return {}, info

    config = build_config(
        obs_id=obs_id,
        source="satnogs_api",
        start_utc=str(start),
        end_utc=str(end),
        norad_id=str(norad),
        station_name=str(station_name),
        station_id=station_id,
        lat=float(lat),
        lon=float(lon),
        alt=float(alt),
        center_freq_hz=int(float(freq)),
        tle=tle,
        tle_source=tle_source,
    )
    return config, info


def build_config(
    obs_id: str,
    source: str,
    start_utc: str,
    end_utc: str,
    norad_id: str,
    station_name: str,
    station_id: Any,
    lat: float,
    lon: float,
    alt: float,
    center_freq_hz: int,
    tle: dict[str, str],
    tle_source: str,
) -> dict[str, Any]:
    tle_norad_id = str(tle["line1"])[2:7].strip()
    if str(norad_id) != tle_norad_id:
        fail("observation NORAD does not match target TLE NORAD; refusing to mix SatNOGS observation with unrelated TLE")
    start_iso = parse_utc(start_utc).isoformat().replace("+00:00", "Z")
    end_iso = parse_utc(end_utc).isoformat().replace("+00:00", "Z")
    return {
        "mode": "satnogs_observation",
        "observation": {
            "observation_id": int(obs_id),
            "source": source,
            "start_utc": start_iso,
            "end_utc": end_iso,
            "duration_s": duration_s(start_iso, end_iso),
            "norad_id": int(norad_id),
        },
        "station": {
            "name": station_name,
            "station_id": int(station_id) if station_id not in (None, "") else None,
            "lat_deg": lat,
            "lon_deg": lon,
            "alt_m": alt,
        },
        "frequency": {"center_freq_hz": center_freq_hz},
        "tle": {
            "target_name": tle["line0"],
            "target_norad_id": int(norad_id),
            "line0": tle["line0"],
            "line1": tle["line1"],
            "line2": tle["line2"],
            "source": tle_source,
        },
        "simulation": {
            "scenarios": ["clean", "offset_only", "offset_plus_noise", "offset_linear_noise"],
            "range_type": "main",
            "num_sims_per_target": 100,
            "seed": 42,
            "step_s": 1,
        },
    }


def write_config(path: Path, config: dict[str, Any], overwrite: bool) -> str | None:
    backup_path = None
    if path.exists():
        if not overwrite:
            fail(f"输出配置已存在，若确认覆盖请添加 --overwrite: {path}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak_{timestamp}")
        shutil.copy2(path, backup_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(backup_path) if backup_path else None


def write_report(
    config: dict[str, Any] | None,
    attempts: list[dict[str, Any]],
    selected_obs_id: str | None,
    backup_path: str | None,
    output: Path,
) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    attempt_lines = "\n".join(
        f"- `{a.get('observation_id')}`: source={a.get('source')}, missing={a.get('missing')}, note={a.get('note','')}"
        for a in attempts
    )
    detail_blocks = []
    for a in attempts:
        fields = a.get("actual_fields")
        if fields:
            detail_blocks.append(
                f"### observation_id `{a.get('observation_id')}` / `{a.get('source')}`\n\n"
                f"- API / 文件实际字段：`{', '.join(fields)}`\n"
                f"- station 字段来源：`{a.get('station_field_source', 'local_or_not_applicable')}`\n"
                f"- frequency 字段来源：`{a.get('frequency_field', 'local_or_not_applicable')}`\n"
                f"- TLE 字段来源：`{a.get('tle_source', a.get('source'))}`\n"
                f"- 是否调用 station API：`{a.get('station_api_used', False)}`\n"
            )
    detail_text = "\n".join(detail_blocks) if detail_blocks else "无额外字段详情。"
    if config:
        obs = config["observation"]
        station = config["station"]
        tle = config["tle"]
        freq = config["frequency"]["center_freq_hz"]
        real_line = "是" if obs["source"] in ["local_strf_ready", "satnogs_api"] else "否"
        summary = f"""
## 最终配置摘要

- observation_id：`{obs['observation_id']}`
- observation 条件来源：`{obs['source']}`
- station 字段来源：见尝试记录；最终 station_id=`{station.get('station_id')}`，lat={station['lat_deg']}，lon={station['lon_deg']}，alt={station['alt_m']} m
- frequency 字段来源：见尝试记录；最终 center_freq_hz=`{freq}`
- TLE 字段来源：`{tle['source']}`
- target：`{tle['target_name']}`
- NORAD ID：`{tle['target_norad_id']}`
- start/end：`{obs['start_utc']}` 至 `{obs['end_utc']}`
- duration_s：`{obs['duration_s']}`
- 是否真正使用 SatNOGS observation 条件：{real_line}
- 是否使用 fallback：{'是' if obs['source'] == 'fallback_manual' else '否'}
- 输出配置：`{output}`
- 备份文件：`{backup_path or '无'}`
"""
    else:
        summary = "\n## 最终配置摘要\n\n未生成可用配置。\n"
    text = f"""# Orbit Simulation Case 准备报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 本轮目标

优先使用本地迁移文件，其次使用 SatNOGS Network API，准备真实 SatNOGS observation 条件下的 orbit simulation 配置。本轮不生成仿真数据，不做攻击场景。

## 尝试记录

{attempt_lines}

## 实际字段详情

{detail_text}

{summary}

## 缺失字段或异常字段

若某次尝试的 `missing` 非空，表示该来源不能单独构成真实 observation 配置。API 返回字段名如与预期不同，以尝试记录中的 actual_fields 为准；本报告不编造字段。

## 边界说明

- `registered_frequency_offset_hz` 后续只作为 registered offset / effective constant frequency bias，不是 pure CFO truth；
- 如果 observation 条件来自 `satnogs_api` 或 `local_strf_ready`，后续生成报告应写明使用真实 SatNOGS observation 条件；
- 如果最终为 `fallback_manual`，必须写明本轮没有使用真实 SatNOGS observation 条件。
"""
    REPORT_PATH.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    attempts: list[dict[str, Any]] = []
    selected_config: dict[str, Any] | None = None
    selected_obs_id: str | None = None
    try:
        candidate_ids = [str(args.observation_id)]
        for obs_id in candidate_ids:
            local_result = find_local_case(obs_id, args.local_root)
            if local_result is not None:
                config, info = local_result
                info["observation_id"] = obs_id
                attempts.append(info)
                if config:
                    selected_config = config
                    selected_obs_id = obs_id
                    break
            else:
                attempts.append(
                    {
                        "observation_id": obs_id,
                        "source": "local_strf_ready",
                        "missing": ["strf_ready.json"],
                        "note": "本地优先路径未找到 strf_ready.json/catalog.tle",
                    }
                )
            if args.allow_api:
                config, info = normalize_api_case(obs_id, args.tle_file)
                info["observation_id"] = obs_id
                attempts.append(info)
                if config:
                    selected_config = config
                    selected_obs_id = obs_id
                    break
            else:
                attempts.append(
                    {
                        "observation_id": obs_id,
                        "source": "satnogs_api",
                        "missing": ["allow_api"],
                        "note": "未传入 --allow-api，跳过 API",
                    }
                )

        if selected_config is None:
            write_report(None, attempts, None, None, args.output)
            fail("本地文件和 API 均未能提供完整 observation 条件，未生成 fallback 配置。")
        backup_path = write_config(args.output, selected_config, args.overwrite)
        write_report(selected_config, attempts, selected_obs_id, backup_path, args.output)
    except PrepareError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        write_report(selected_config, attempts, selected_obs_id, None, args.output)
        print(f"错误: SatNOGS API 请求异常: {exc}", file=sys.stderr)
        return 2

    print(f"配置生成完成: {args.output}")
    print(f"准备报告: {REPORT_PATH}")
    print(
        f"observation_id={selected_config['observation']['observation_id']}, "
        f"source={selected_config['observation']['source']}, "
        f"target={selected_config['tle']['target_name']}, "
        f"norad={selected_config['tle']['target_norad_id']}"
    )
    if backup_path:
        print(f"已备份旧配置: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
