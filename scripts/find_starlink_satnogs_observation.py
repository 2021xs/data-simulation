#!/usr/bin/env python
"""Find a real Starlink SatNOGS observation whose NORAD exists in local Starlink TLE."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


API_ROOT = "https://network.satnogs.org/api"


class SearchError(ValueError):
    pass


def fail(message: str) -> None:
    raise SearchError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tle-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--max-starlinks", type=int, default=50)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def validate_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def parse_starlink_tle(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        fail(f"TLE 文件不存在: {path}")
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows: list[dict[str, Any]] = []
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 ") and name.upper().startswith("STARLINK"):
            try:
                rows.append(
                    {
                        "satellite_name": name,
                        "norad_id": int(line1[2:7].strip()),
                        "line0": name,
                        "line1": line1,
                        "line2": line2,
                        "inclination_deg": float(line2[8:16]),
                        "mean_motion_rev_per_day": float(line2[52:63]),
                    }
                )
            except ValueError:
                pass
            i += 3
        else:
            i += 1
    if not rows:
        fail("TLE 文件中没有有效 Starlink 条目")
    preferred = sorted(rows, key=lambda r: (0 if r["satellite_name"].upper() == "STARLINK-1008" else 1, r["satellite_name"]))
    return preferred[:limit]


def request_json(path: str, params: dict[str, Any]) -> tuple[str, Any]:
    url = f"{API_ROOT}/{path.strip('/')}/"
    response = requests.get(
        url,
        params=params,
        timeout=30,
        headers={"User-Agent": "data-simulation-starlink-observation-search/1.0"},
    )
    if response.status_code != 200:
        raise requests.RequestException(f"{response.status_code}: {response.text[:200]}")
    return response.url, response.json()


def duration_s(obs: dict[str, Any]) -> float | None:
    from datetime import datetime, timezone

    start = obs.get("start") or obs.get("start_utc")
    end = obs.get("end") or obs.get("end_utc")
    if not start or not end:
        return None
    def parse(v: str):
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        d = datetime.fromisoformat(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return (parse(end) - parse(start)).total_seconds()


def is_complete(obs: dict[str, Any], starlink_norads: set[int]) -> tuple[bool, list[str]]:
    missing = []
    if obs.get("id") == 9424971:
        missing.append("excluded_9424971")
    norad = obs.get("norad_cat_id") or obs.get("norad_id")
    if norad not in starlink_norads:
        missing.append("norad_not_in_starlink_tle")
    if not (obs.get("start") or obs.get("start_utc")):
        missing.append("start")
    if not (obs.get("end") or obs.get("end_utc")):
        missing.append("end")
    if duration_s(obs) is None or duration_s(obs) < 120:
        missing.append("duration_lt_120")
    if not (obs.get("station_lat") is not None and (obs.get("station_lng") is not None or obs.get("station_lon") is not None) and obs.get("station_alt") is not None):
        if not (obs.get("ground_station") or obs.get("station_id")):
            missing.append("station")
    freq = obs.get("observation_frequency") or obs.get("center_frequency")
    if not freq:
        missing.append("frequency")
    return len(missing) == 0, missing


def score_observation(obs: dict[str, Any]) -> float:
    score = 0.0
    if str(obs.get("vetted_status", "")).lower() == "good":
        score += 100
    if obs.get("waterfall"):
        score += 50
    score += float(obs.get("max_altitude") or 0)
    dur = duration_s(obs) or 0
    score += min(dur / 10.0, 60)
    return score


def main() -> int:
    args = parse_args()
    try:
        validate_outputs([args.output, args.report], args.overwrite)
        starlinks = parse_starlink_tle(args.tle_file, args.max_starlinks)
        norads = {r["norad_id"] for r in starlinks}
        tle_by_norad = {r["norad_id"]: r for r in starlinks}
        candidates: list[dict[str, Any]] = []
        attempts: list[str] = []
        params_variants = [
            lambda n: {"norad_cat_id": n, "limit": 25},
            lambda n: {"satellite__norad_cat_id": n, "limit": 25},
            lambda n: {"norad_cat_id": n, "vetted_status": "good", "limit": 25},
        ]
        for item in starlinks:
            for make_params in params_variants:
                params = make_params(item["norad_id"])
                try:
                    url, data = request_json("observations", params)
                    attempts.append(f"{url} -> {len(data) if isinstance(data, list) else 'non-list'}")
                except Exception as exc:
                    attempts.append(f"ERROR {params}: {exc}")
                    continue
                if not isinstance(data, list):
                    continue
                for obs in data:
                    ok, missing = is_complete(obs, norads)
                    if (obs.get("norad_cat_id") or obs.get("norad_id")) in norads and obs.get("id") != 9424971:
                        tle = tle_by_norad[int(obs.get("norad_cat_id") or obs.get("norad_id"))]
                        candidates.append(
                            {
                                "observation_id": obs.get("id"),
                                "norad_id": obs.get("norad_cat_id") or obs.get("norad_id"),
                                "satellite_name": tle["satellite_name"],
                                "start_utc": obs.get("start") or obs.get("start_utc"),
                                "end_utc": obs.get("end") or obs.get("end_utc"),
                                "duration_s": duration_s(obs),
                                "station_id": obs.get("ground_station") or obs.get("station_id"),
                                "station_name": obs.get("station_name"),
                                "station_lat": obs.get("station_lat"),
                                "station_lon": obs.get("station_lng") if obs.get("station_lng") is not None else obs.get("station_lon"),
                                "station_alt": obs.get("station_alt"),
                                "frequency_hz": obs.get("observation_frequency") or obs.get("center_frequency"),
                                "vetted_status": obs.get("vetted_status"),
                                "status": obs.get("status"),
                                "waterfall": obs.get("waterfall"),
                                "max_altitude": obs.get("max_altitude"),
                                "is_complete": ok,
                                "missing_fields": ";".join(missing),
                                "selection_score": score_observation(obs),
                            }
                        )
                if any(c["is_complete"] for c in candidates):
                    break
            if any(c["is_complete"] for c in candidates):
                break
        result = pd.DataFrame(candidates).drop_duplicates("observation_id") if candidates else pd.DataFrame()
        if not result.empty:
            result = result.sort_values(["is_complete", "selection_score"], ascending=[False, False])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(args.output, index=False)
        selected = result[result["is_complete"]].head(1) if not result.empty else pd.DataFrame()
        found_text = "未找到字段完整的真实 Starlink SatNOGS observation。" if selected.empty else f"找到候选 observation_id={int(selected.iloc[0]['observation_id'])}，NORAD={int(selected.iloc[0]['norad_id'])}。"
        report = f"""# Starlink SatNOGS Observation 搜索报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 本轮目标

从 `data/tle/starlink_tle.txt` 中抽取前 {args.max_starlinks} 个 Starlink NORAD，调用 SatNOGS Network observations API，寻找真实 Starlink observation。不能使用 `9424971`，不能使用非 Starlink observation。

## 搜索结果

{found_text}

- API 尝试次数：{len(attempts)}
- 保存候选数：{0 if result.empty else len(result)}
- 字段完整候选数：{0 if result.empty else int(result['is_complete'].sum())}

## API 尝试摘要

```text
{chr(10).join(attempts[:80])}
```

## 边界说明

如果候选列表为空或没有完整候选，说明本轮不能生成真实 Starlink SatNOGS observation 条件数据；脚本不会编造 observation，也不会 fallback 到 fixed station。
"""
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    except SearchError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except requests.RequestException as exc:
        print(f"错误: SatNOGS API 请求失败: {exc}", file=sys.stderr)
        return 2
    if selected.empty:
        print("未找到字段完整的真实 Starlink SatNOGS observation")
        return 3
    print(f"找到 observation_id={int(selected.iloc[0]['observation_id'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
