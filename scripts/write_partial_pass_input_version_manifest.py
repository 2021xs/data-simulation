#!/usr/bin/env python
"""Write input version manifest for partial-pass stress."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path: Path) -> dict:
    rec = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        return rec
    stat = path.stat()
    rec.update(
        {
            "file_size_bytes": stat.st_size,
            "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "sha256": sha256(path),
        }
    )
    if path.suffix.lower() == ".csv":
        rec["row_count"] = int(sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore")) - 1)
    return rec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"输出文件已存在，请添加 --overwrite: {args.output}")
    paths = [
        Path("outputs/datasets/controlled_starlink_ku_band_near_neighbor_stress_dataset.csv"),
        Path("outputs/datasets/controlled_starlink_ku_band_near_neighbor_candidate_library_1000.csv"),
        Path("outputs/metrics/controlled_starlink_ku_band_near_neighbor_stress_matching_results.csv"),
        Path("outputs/reports/controlled_starlink_near_neighbor_failure_case_diagnosis.md"),
    ]
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "fix Stage 2 / Stage 2.5 input versions before Stage 3A partial-pass stress",
        "files": [file_record(path) for path in paths],
        "notes": [
            "mode remains controlled_starlink",
            "observation_id remains null",
            "9424971 is not used for Starlink controlled simulation",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"input version manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
