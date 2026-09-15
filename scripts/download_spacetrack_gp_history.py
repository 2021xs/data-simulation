#!/usr/bin/env python
"""Download multi-epoch GP history records from Space-Track.

Credentials are read from SPACETRACK_USERNAME and SPACETRACK_PASSWORD.
Do not place credentials in command lines, logs, reports, or output files.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
QUERY_BASE = "https://www.space-track.org/basicspacedata/query"
DEFAULT_PRIORITY_IDS = ["65409", "65410", "65411", "47749", "48458", "58380", "65693"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input-tle", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--norad-ids", nargs="*", default=None)
    p.add_argument("--max-sats", type=int, default=50)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--output-dir", type=Path, default=Path("data/tle/history"))
    p.add_argument("--format", choices=["tle", "json", "csv"], default="tle")
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--sleep-sec", type=float, default=3.0)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/spacetrack_gp_history_download_summary.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/spacetrack_gp_history_download_summary.md"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def normalize_date(text: str) -> str:
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        fail(f"invalid date, expected YYYY-MM-DD: {text}")
        raise exc


def compact_date(text: str) -> str:
    return normalize_date(text).replace("-", "")


def parse_tle_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = [line.rstrip("\n") for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    ids: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line.startswith("1 ") and len(line) >= 7:
            sat_id = line[2:7].strip()
            if sat_id and sat_id not in seen:
                ids.append(sat_id)
                seen.add(sat_id)
    return ids


def selection_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
    except Exception:
        return []
    if "target_norad_id" not in df.columns:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in df["target_norad_id"].astype(str):
        value = value.strip()
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out


def choose_norad_ids(args: argparse.Namespace) -> list[str]:
    if args.norad_ids:
        ids = [str(x).strip() for x in args.norad_ids if str(x).strip()]
    else:
        controlled = selection_ids(args.selection_table)
        input_ids = parse_tle_ids(args.input_tle)
        ids = []
        for value in DEFAULT_PRIORITY_IDS + controlled + input_ids:
            if value not in ids:
                ids.append(value)
        ids = ids[: max(1, int(args.max_sats))]
    clean: list[str] = []
    seen: set[str] = set()
    for value in ids:
        if not value.isdigit():
            fail(f"invalid NORAD ID: {value}")
        if value not in seen:
            clean.append(value)
            seen.add(value)
    if not clean:
        fail("no NORAD IDs selected")
    return clean


def check_credentials() -> tuple[str, str]:
    username = os.environ.get("SPACETRACK_USERNAME")
    password = os.environ.get("SPACETRACK_PASSWORD")
    if not username or not password:
        fail("Please set SPACETRACK_USERNAME and SPACETRACK_PASSWORD.")
    return username, password


def output_paths(args: argparse.Namespace) -> dict[str, Path]:
    start = compact_date(args.start_date)
    end = compact_date(args.end_date)
    stem = f"starlink_gp_history_{start}_{end}"
    return {
        "tle": args.output_dir / f"{stem}.tle",
        "csv": args.output_dir / f"{stem}.csv",
        "json": args.output_dir / f"{stem}.json",
        "raw_json": args.output_dir / f"{stem}_raw_batches.json",
        "summary": args.summary_output,
        "report": args.report_output,
    }


def check_outputs(paths: dict[str, Path], overwrite: bool) -> None:
    write_paths = [paths["tle"], paths["csv"], paths["json"], paths["raw_json"], paths["summary"], paths["report"]]
    existing = [str(p) for p in write_paths if p.exists()]
    if existing and not overwrite:
        fail("outputs exist; add --overwrite: " + ", ".join(existing))
    if overwrite:
        for path in write_paths:
            if path.exists():
                path.unlink()


def import_requests():
    try:
        import requests  # type: ignore
    except ImportError as exc:
        fail("Python package 'requests' is required for Space-Track download.")
        raise exc
    return requests


def batches(values: list[str], batch_size: int) -> list[list[str]]:
    size = max(1, int(batch_size))
    return [values[i : i + size] for i in range(0, len(values), size)]


def login_session(username: str, password: str):
    requests = import_requests()
    session = requests.Session()
    response = session.post(LOGIN_URL, data={"identity": username, "password": password}, timeout=60)
    if response.status_code in {401, 403}:
        fail("Space-Track login failed with HTTP 401/403. Check credentials.")
    if response.status_code >= 400:
        fail(f"Space-Track login failed with HTTP {response.status_code}.")
    return session


def query_gp_history(session: Any, ids: list[str], start_date: str, end_date: str, max_retries: int) -> list[dict[str, Any]]:
    id_expr = ",".join(ids)
    url = (
        f"{QUERY_BASE}/class/gp_history"
        f"/NORAD_CAT_ID/{id_expr}"
        f"/EPOCH/{start_date}--{end_date}"
        "/orderby/NORAD_CAT_ID%20asc,EPOCH%20asc"
        "/format/json"
    )
    delay = 5.0
    last_error = ""
    for attempt in range(1, max(1, int(max_retries)) + 1):
        response = session.get(url, timeout=120)
        if response.status_code in {401, 403}:
            fail("Space-Track query failed with HTTP 401/403. Check credentials and account access.")
        if response.status_code == 429 or response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            time.sleep(delay)
            delay *= 2.0
            continue
        if response.status_code >= 400:
            fail(f"Space-Track query failed with HTTP {response.status_code}.")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            text = response.text[:200].replace("\n", " ")
            fail(f"Space-Track returned non-JSON response: {text}")
            raise exc
        if isinstance(data, dict) and data.get("error"):
            fail(f"Space-Track query error: {data.get('error')}")
        if not isinstance(data, list):
            fail("Space-Track query returned unexpected JSON shape.")
        return data
    fail(f"Space-Track query failed after retries: {last_error}")
    return []


def record_epoch(record: dict[str, Any]) -> str:
    return str(record.get("EPOCH") or record.get("epoch") or "").strip()


def record_norad(record: dict[str, Any]) -> str:
    return str(record.get("NORAD_CAT_ID") or record.get("norad_cat_id") or "").strip()


def record_name(record: dict[str, Any]) -> str:
    return str(record.get("OBJECT_NAME") or record.get("object_name") or f"NORAD-{record_norad(record)}").strip()


def record_line1(record: dict[str, Any]) -> str:
    return str(record.get("TLE_LINE1") or record.get("tle_line1") or "").rstrip()


def record_line2(record: dict[str, Any]) -> str:
    return str(record.get("TLE_LINE2") or record.get("tle_line2") or "").rstrip()


def sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda r: (record_norad(r), record_epoch(r)))


def write_outputs(paths: dict[str, Path], records: list[dict[str, Any]], raw_batches: list[dict[str, Any]]) -> None:
    for key in ["tle", "csv", "json", "raw_json"]:
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    sorted_records = sort_records(records)

    with paths["json"].open("w", encoding="utf-8") as f:
        json.dump(sorted_records, f, indent=2, ensure_ascii=False)
    with paths["raw_json"].open("w", encoding="utf-8") as f:
        json.dump(raw_batches, f, indent=2, ensure_ascii=False)

    csv_fields = [
        "NORAD_CAT_ID",
        "OBJECT_NAME",
        "EPOCH",
        "MEAN_MOTION",
        "ECCENTRICITY",
        "INCLINATION",
        "RA_OF_ASC_NODE",
        "ARG_OF_PERICENTER",
        "MEAN_ANOMALY",
        "TLE_LINE1",
        "TLE_LINE2",
    ]
    with paths["csv"].open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for record in sorted_records:
            writer.writerow({field: record.get(field, "") for field in csv_fields})

    with paths["tle"].open("w", encoding="utf-8") as f:
        for record in sorted_records:
            line1 = record_line1(record)
            line2 = record_line2(record)
            if not line1 or not line2:
                continue
            f.write(f"{record_name(record)}\n{line1}\n{line2}\n")


def count_multi_epoch_tle_records(tle_path: Path) -> tuple[int, int, dict[str, dict[str, Any]]]:
    lines = [line.rstrip("\n") for line in tle_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    by_sat: dict[str, dict[str, Any]] = defaultdict(lambda: {"epochs": set(), "records": 0, "parse_ok": 0})
    i = 0
    while i < len(lines):
        if i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            line1, line2 = lines[i + 1], lines[i + 2]
            i += 3
        elif i + 1 < len(lines) and lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            line1, line2 = lines[i], lines[i + 1]
            i += 2
        else:
            i += 1
            continue
        sat_id = line1[2:7].strip()
        epoch = line1[18:32].strip()
        by_sat[sat_id]["epochs"].add(epoch)
        by_sat[sat_id]["records"] += 1
        try:
            from skyfield.api import EarthSatellite, load

            ts = load.timescale()
            EarthSatellite(line1, line2, f"NORAD-{sat_id}", ts)
            by_sat[sat_id]["parse_ok"] += 1
        except Exception:
            pass
    total_records = sum(int(v["records"]) for v in by_sat.values())
    multi = sum(1 for v in by_sat.values() if len(v["epochs"]) >= 2)
    return total_records, multi, by_sat


def build_summary(requested_ids: list[str], records: list[dict[str, Any]], paths: dict[str, Path], default_status: str = "no_data", default_error: str = "") -> pd.DataFrame:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        norad = record_norad(record)
        if norad:
            by_id[norad].append(record)
    _total_records, _multi, tle_counts = count_multi_epoch_tle_records(paths["tle"]) if paths["tle"].exists() else (0, 0, {})
    rows: list[dict[str, Any]] = []
    for norad in requested_ids:
        recs = by_id.get(norad, [])
        epochs = sorted({record_epoch(r) for r in recs if record_epoch(r)})
        tle_info = tle_counts.get(norad, {"records": 0, "parse_ok": 0})
        rows.append(
            {
                "norad_id": norad,
                "num_epochs": int(len(epochs)),
                "first_epoch": epochs[0] if epochs else "",
                "last_epoch": epochs[-1] if epochs else "",
                "num_tle_records": int(tle_info.get("records", 0)),
                "download_status": "ok" if recs else default_status,
                "error_message": "" if recs else default_error,
                "sgp4_parse_ok_records": int(tle_info.get("parse_ok", 0)),
            }
        )
    return pd.DataFrame(rows)


def write_report(
    args: argparse.Namespace,
    paths: dict[str, Path],
    requested_ids: list[str],
    summary: pd.DataFrame,
    batch_errors: list[str],
    login_success: bool,
) -> None:
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    with_data = int((summary["download_status"] == "ok").sum()) if not summary.empty else 0
    multi = int((summary["num_epochs"] >= 2).sum()) if not summary.empty else 0
    top = summary.sort_values(["num_epochs", "norad_id"], ascending=[False, True]).head(20) if not summary.empty else pd.DataFrame()
    epoch_counts = summary["num_epochs"].to_numpy(int) if not summary.empty else np.array([], dtype=int)
    if len(epoch_counts):
        epoch_range = f"{int(epoch_counts.min())} - {int(epoch_counts.max())}"
        epoch_median = f"{float(np.median(epoch_counts)):.1f}"
    else:
        epoch_range = "n/a"
        epoch_median = "n/a"
    errors_text = "\n".join(f"- {e}" for e in batch_errors) if batch_errors else "- No batch failures recorded."
    text = f"""# Space-Track GP_History Download Summary

Generated at: {datetime.now().isoformat(timespec="seconds")}

## 1. Download Purpose

Download multi-epoch GP/TLE history for selected Starlink NORAD IDs so that later TLE-to-TLE Doppler error calibration can use same-satellite historical records.

## 2. Query Date Range

- start_date: `{args.start_date}`
- end_date: `{args.end_date}`
- source: Space-Track `gp_history`
- login_success: `{str(login_success).lower()}`

Credentials were read from environment variables and are not written to this report.

## 3. Requested NORAD IDs

- requested_count: {len(requested_ids)}
- requested_ids: `{", ".join(requested_ids)}`

## 4. Download Results

- NORAD IDs with data: {with_data}
- NORAD IDs with >=2 epochs: {multi}
- epoch count range: {epoch_range}
- median epochs per NORAD: {epoch_median}

Top multi-epoch examples:

{top.to_markdown(index=False) if not top.empty else "No records downloaded."}

## 5. Output Files

- TLE: `{paths["tle"]}`
- CSV: `{paths["csv"]}`
- JSON: `{paths["json"]}`
- Raw batch JSON: `{paths["raw_json"]}`
- Summary CSV: `{paths["summary"]}`
- Report: `{paths["report"]}`

## 6. Rate Limit / Failures

Batch size: {args.batch_size}

Sleep between batches: {args.sleep_sec} seconds

{errors_text}

## 7. Next Step

If `NORAD IDs with >=2 epochs` is greater than zero, rerun:

```bash
python scripts/run_tle_error_lower_bound_calibration.py --input-tle-history {paths["tle"]} --max-sats 20 --window-duration-s 30 45 60 90 120 180 full --window-position first middle last best_error best_attack --delta-km 0.1 0.2 0.5 1 2 5 10 20 50 100 200 --perturb-direction along_pos along_neg --residual-mode empirical --overwrite
```

Do not compute or report tau_error from single-epoch records.
"""
    paths["report"].write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.start_date = normalize_date(args.start_date)
    args.end_date = normalize_date(args.end_date)
    paths = output_paths(args)
    check_outputs(paths, args.overwrite)
    requested_ids = choose_norad_ids(args)
    paths["tle"].parent.mkdir(parents=True, exist_ok=True)
    paths["summary"].parent.mkdir(parents=True, exist_ok=True)
    paths["report"].parent.mkdir(parents=True, exist_ok=True)

    username = os.environ.get("SPACETRACK_USERNAME")
    password = os.environ.get("SPACETRACK_PASSWORD")
    if not username or not password:
        empty_records: list[dict[str, Any]] = []
        write_outputs(paths, empty_records, [{"error": "missing_credentials"}])
        summary = build_summary(
            requested_ids,
            empty_records,
            paths,
            default_status="missing_credentials",
            default_error="Please set SPACETRACK_USERNAME and SPACETRACK_PASSWORD.",
        )
        summary.to_csv(paths["summary"], index=False)
        write_report(args, paths, requested_ids, summary, ["missing credentials"], login_success=False)
        fail("Please set SPACETRACK_USERNAME and SPACETRACK_PASSWORD.")

    session = login_session(username, password)
    all_records: list[dict[str, Any]] = []
    raw_batches: list[dict[str, Any]] = []
    batch_errors: list[str] = []
    id_batches = batches(requested_ids, args.batch_size)
    for batch_index, id_batch in enumerate(id_batches, start=1):
        try:
            records = query_gp_history(session, id_batch, args.start_date, args.end_date, args.max_retries)
            all_records.extend(records)
            raw_batches.append({"batch_index": batch_index, "norad_ids": id_batch, "num_records": len(records), "records": records})
            print(f"Batch {batch_index}/{len(id_batches)}: requested={len(id_batch)} records={len(records)}")
        except SystemExit:
            raise
        except Exception as exc:
            msg = f"batch {batch_index} failed for {','.join(id_batch)}: {type(exc).__name__}"
            batch_errors.append(msg)
            raw_batches.append({"batch_index": batch_index, "norad_ids": id_batch, "num_records": 0, "error": msg})
            print(msg)
        if batch_index < len(id_batches):
            time.sleep(max(0.0, float(args.sleep_sec)))

    write_outputs(paths, all_records, raw_batches)
    summary = build_summary(requested_ids, all_records, paths)
    summary.to_csv(paths["summary"], index=False)
    write_report(args, paths, requested_ids, summary, batch_errors, login_success=True)

    with_data = int((summary["download_status"] == "ok").sum()) if not summary.empty else 0
    multi = int((summary["num_epochs"] >= 2).sum()) if not summary.empty else 0
    median_epochs = float(summary["num_epochs"].median()) if not summary.empty else 0.0
    print(f"Total NORAD IDs requested: {len(requested_ids)}")
    print(f"NORAD IDs with data: {with_data}")
    print(f"NORAD IDs with >=2 epochs: {multi}")
    print(f"Median epochs per NORAD: {median_epochs:.1f}")
    print(f"Output TLE: {paths['tle']}")
    print(f"Summary CSV: {paths['summary']}")


if __name__ == "__main__":
    main()
