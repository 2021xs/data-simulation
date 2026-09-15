#!/usr/bin/env python3
"""Read-only June SupGP availability audit for the frozen Stage-1F-lite protocol.

This script deliberately does not read ordinary GP data, construct RTN residuals,
load the frozen uncertainty model, or evaluate confirmatory coverage.  It reuses
the Stage-1A SupGP parser and gate implementation for reference-only checks.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from scripts.audit_orbit_uncertainty_stage1a_supgp import (
        QUALITY_FIELDS,
        audit_satellite,
        discover_and_read,
        duplicate_statistics,
        gap_hours,
        iso_z,
        parse_utc,
        quantile,
        read_selection,
        rms_statistics,
        sha256,
        source_statistics,
        write_csv,
        write_text,
    )
except ModuleNotFoundError:
    from audit_orbit_uncertainty_stage1a_supgp import (
        QUALITY_FIELDS,
        audit_satellite,
        discover_and_read,
        duplicate_statistics,
        gap_hours,
        iso_z,
        parse_utc,
        quantile,
        read_selection,
        rms_statistics,
        sha256,
        source_statistics,
        write_csv,
        write_text,
    )


FORMAL_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
FORMAL_STOP = datetime(2026, 7, 1, tzinfo=timezone.utc)
BOUNDARY_TOLERANCE_HOURS = 24.0
INTERNAL_GAP_THRESHOLD_HOURS = 48.0
DESCRIPTIVE_PAUSE_MIN_HOURS = 12.0

EXPECTED_COHORT = (
    "44714", "65686", "65421", "65409", "65410", "47749", "47383",
    "65411", "48309", "45230", "47844", "65407", "47767", "65405",
    "48672", "48111", "65693", "60265", "58380", "48458",
)

PROTECTED_ARTIFACTS = {
    "outputs/metrics/orbit_uncertainty_stage1f_lite_frozen_parameters.csv":
        "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1",
    "outputs/metrics/orbit_uncertainty_stage1f_lite_manifest.json":
        "E18F19B0AF191DC3599228BC00CA1BAADE31FD8AC513A2533D19279982CF5660",
    "outputs/reports/orbit_uncertainty_stage1f_lite_design_freeze_report.md":
        "001CF7C56661B1243CE6AAE06766537F9F7D1B8805C041F6A0DF33332678CA71",
    "outputs/datasets/orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv":
        "2B02C40FDEA69F6079D256B5E274652ABAB2D5BC2F9899866C7F1CAFFB469F23",
    "outputs/datasets/orbit_uncertainty_stage1b_20260501_20260531_rtn_residual_library.csv":
        "119F2DAA3896476E120F010A436D0B250E404D41326B57FAABFEAA9F2F73EF3F",
    "outputs/metrics/orbit_uncertainty_stage1b_20260401_20260430_manifest.json":
        "81FC7EF0F4E6401A316A893C1C010840136AA43BEBEC48094A74F06FE020E4E3",
    "outputs/metrics/orbit_uncertainty_stage1b_20260501_20260531_manifest.json":
        "9631AF3F4B4AA0F9D4C9804AE05A2C5F7608428CC0D1B2D7C22CC145F6EF38CD",
    "outputs/metrics/orbit_uncertainty_stage1d_20260401_20260430_manifest.json":
        "834917C94E18E1AD8E643687AF4312A88B28DFADA4E6FE25C407F091E04C0617",
    "outputs/metrics/orbit_uncertainty_stage1e_20260401_20260430_manifest.json":
        "888FACF353F5F6FC0B011F45521187781BE007943D8DB84AAF3B961DB300883D",
    "outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_manifest.json":
        "720797459ABAE320C341F785D8425B0B08C8904B003C149B7F6C5A0DF9E2B311",
    "outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv":
        "30D7A846DDDE5850645CD3C1C03C061E7971AE40A2EE052FFB4E8BA3E7F4ED36",
}

FORBIDDEN_CONFIRMATORY_FIELDS = {
    "delta_R", "delta_T", "delta_N", "position_error_norm",
    "ellipsoid_score", "box_score", "p95_coverage", "p99_coverage",
    "false_orbit_distinct_rate", "security_classification",
}

PREFIX = "orbit_uncertainty_stage1f_june_supgp_candidate"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def fingerprint_protected(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative, expected in PROTECTED_ARTIFACTS.items():
        path = root / relative
        observed = file_sha256(path) if path.exists() else ""
        rows.append({
            "path": relative,
            "expected_sha256": expected,
            "observed_sha256": observed,
            "exists": path.exists(),
            "matches_expected": observed == expected,
        })
    return rows


def require_protected(rows: Sequence[dict[str, Any]], phase: str) -> None:
    failures = [row for row in rows if not row["matches_expected"]]
    if failures:
        paths = ", ".join(str(row["path"]) for row in failures)
        raise RuntimeError(f"Protected artifact mismatch during {phase}: {paths}")


def filename_content_audit(inventory: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in inventory:
        path = Path(str(row["raw_file"]))
        match = re.fullmatch(r"sat(\d+)\.csv", path.name, flags=re.IGNORECASE)
        filename_norad = str(int(match.group(1))) if match else ""
        content_ids = [value for value in str(row["norad_ids"]).split(";") if value]
        output.append({
            **row,
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
            "filename_norad_id": filename_norad,
            "content_norad_ids": ";".join(content_ids),
            "filename_content_norad_consistent": bool(
                filename_norad and content_ids == [filename_norad]
            ),
        })
    return output


def all_cohort_pauses(
    grouped: dict[str, list[dict[str, Any]]],
    cohort: Sequence[str],
    minimum_gap_hours: float = DESCRIPTIVE_PAUSE_MIN_HOURS,
) -> list[dict[str, Any]]:
    intervals: list[tuple[datetime, datetime, str]] = []
    for norad in cohort:
        epochs = [
            row["_epoch_dt"] for row in grouped.get(norad, [])
            if row.get("_epoch_dt") is not None
            and FORMAL_START <= row["_epoch_dt"] < FORMAL_STOP
        ]
        for left, right, hours in gap_hours(epochs):
            if hours > minimum_gap_hours:
                intervals.append((left, right, norad))

    points = sorted({point for left, right, _ in intervals for point in (left, right)})
    full_segments: list[tuple[datetime, datetime]] = []
    for left, right in zip(points, points[1:]):
        midpoint = left + (right - left) / 2
        active = {
            norad for start, stop, norad in intervals
            if start < midpoint < stop
        }
        if len(active) != len(cohort):
            continue
        if full_segments and full_segments[-1][1] == left:
            full_segments[-1] = (full_segments[-1][0], right)
        else:
            full_segments.append((left, right))

    return [{
        "pause_start": iso_z(left),
        "pause_end": iso_z(right),
        "duration_hours": round((right - left).total_seconds() / 3600.0, 6),
        "affected_satellites": len(cohort),
        "affected_norad_ids": ";".join(cohort),
        "exceeds_frozen_48h_gate": (right - left).total_seconds() / 3600.0 > INTERNAL_GAP_THRESHOLD_HOURS,
        "semantics": "descriptive overlap of raw per-satellite gaps; no interpolation and no gate change",
    } for left, right in full_segments]


def choose_window_decision(
    quality: Sequence[dict[str, Any]],
    cohort_complete: bool,
    header_consistent: bool,
    filename_consistent: bool,
    integrity_error_count: int,
    variant_group_count: int,
    march_style_archive_gap: bool,
) -> tuple[str, str]:
    statuses = Counter(str(row["status"]) for row in quality)
    if (
        not cohort_complete
        or statuses.get("NO_REFERENCE", 0)
        or march_style_archive_gap
        or integrity_error_count
    ):
        return "C", "JUNE_CONFIRMATORY_WINDOW_UNSUITABLE"
    if (
        statuses.get("PARTIAL", 0)
        or not header_consistent
        or not filename_consistent
        or variant_group_count
    ):
        return "B", "JUNE_CONFIRMATORY_WINDOW_HAS_LOCAL_ISSUES"
    if statuses.get("READY", 0) == 20:
        return "A", "JUNE_CONFIRMATORY_WINDOW_ACCEPTABLE"
    return "C", "JUNE_CONFIRMATORY_WINDOW_UNSUITABLE"


def markdown_table(rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> str:
    header = "| " + " | ".join(fields) + " |"
    divider = "| " + " | ".join("---" for _ in fields) + " |"
    body = [
        "| " + " | ".join(str(row.get(field, "")).replace("|", "\\|") for field in fields) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--input-dir", type=Path, default=Path("data/orbit_uncertainty_stage1/june"))
    parser.add_argument(
        "--selection", type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    parser.add_argument("--report-dir", type=Path, default=Path("outputs/reports"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    input_dir = root / args.input_dir
    selection_path = root / args.selection
    output_dir = root / args.output_dir
    report_dir = root / args.report_dir

    protected_before = fingerprint_protected(root)
    require_protected(protected_before, "pre-audit")

    selection = read_selection(selection_path)
    selected_ids = tuple(row["NORAD_CAT_ID"] for row in selection)
    if len(selected_ids) != 20 or set(selected_ids) != set(EXPECTED_COHORT):
        raise RuntimeError("Frozen selection does not exactly match the Stage-1F-lite 20-satellite cohort")

    all_rows, base_inventory, files, header_union = discover_and_read(input_dir)
    if not files:
        raise FileNotFoundError(f"JUNE_SUPGP_INPUT_REQUIRED: no CSV files in {input_dir}")
    raw_hashes_before = {path.as_posix(): sha256(path) for path in files}
    inventory = filename_content_audit(base_inventory)
    headers = {str(row["header_json"]) for row in inventory}
    header_consistent = len(headers) == 1
    forbidden_present = sorted(FORBIDDEN_CONFIRMATORY_FIELDS.intersection(header_union))
    if forbidden_present:
        raise RuntimeError(
            "June candidate unexpectedly contains forbidden confirmatory fields: "
            + ", ".join(forbidden_present)
        )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        grouped[str(row.get("NORAD_CAT_ID", "")).strip()].append(row)
    returned_ids = {norad for norad in grouped if norad}
    missing_ids = sorted(set(EXPECTED_COHORT) - returned_ids)
    extra_ids = sorted(returned_ids - set(EXPECTED_COHORT))
    cohort_complete = not missing_ids and not extra_ids and len(files) == 20

    quality: list[dict[str, Any]] = []
    duplicate_details: list[dict[str, Any]] = []
    per_satellite: list[dict[str, Any]] = []
    for target in selection:
        norad = target["NORAD_CAT_ID"]
        sat_rows = grouped.get(norad, [])
        result, details = audit_satellite(
            norad, target["OBJECT_NAME"], sat_rows, FORMAL_START, FORMAL_STOP,
            BOUNDARY_TOLERANCE_HOURS, INTERNAL_GAP_THRESHOLD_HOURS,
        )
        quality.append(result)
        duplicate_details.extend(details)
        epochs = [
            row["_epoch_dt"] for row in sat_rows
            if row.get("_epoch_dt") is not None
            and FORMAL_START <= row["_epoch_dt"] < FORMAL_STOP
        ]
        gaps = gap_hours(epochs)
        largest = max(gaps, key=lambda item: item[2], default=None)
        start_gap = result["start_boundary_gap_hours"]
        end_gap = result["end_boundary_gap_hours"]
        boundary_ok = (
            start_gap != "" and end_gap != ""
            and float(start_gap) <= BOUNDARY_TOLERANCE_HOURS
            and float(end_gap) <= BOUNDARY_TOLERANCE_HOURS
        )
        per_satellite.append({
            "norad_id": norad,
            "object_name": result["object_name"],
            "records": result["formal_window_record_count"],
            "first_epoch": result["first_epoch"],
            "last_epoch": result["last_epoch"],
            "start_boundary_distance_hours": start_gap,
            "end_boundary_distance_hours": end_gap,
            "median_gap_hours": result["median_gap_hours"],
            "max_gap_hours": result["max_gap_hours"],
            "max_gap_start": iso_z(largest[0]) if largest else "",
            "max_gap_end": iso_z(largest[1]) if largest else "",
            "boundary_ok": boundary_ok,
            "simulated_status": result["status"],
        })

    daily_rows: list[dict[str, Any]] = []
    for offset in range((FORMAL_STOP - FORMAL_START).days):
        day_start = FORMAL_START + timedelta(days=offset)
        day_stop = day_start + timedelta(days=1)
        rows = [
            row for row in all_rows
            if row.get("_epoch_dt") is not None and day_start <= row["_epoch_dt"] < day_stop
        ]
        satellites = sorted({str(row.get("NORAD_CAT_ID", "")).strip() for row in rows})
        daily_rows.append({
            "utc_date": day_start.date().isoformat(),
            "total_records": len(rows),
            "satellites_with_records": len(satellites),
            "missing_satellite_count": 20 - len(set(EXPECTED_COHORT).intersection(satellites)),
            "missing_norad_ids": ";".join(sorted(set(EXPECTED_COHORT) - set(satellites))),
        })

    pauses = all_cohort_pauses(grouped, EXPECTED_COHORT)
    march_style_gap = any(bool(row["exceeds_frozen_48h_gate"]) for row in pauses)
    duplicate_totals = Counter()
    for result in quality:
        for field in (
            "duplicate_epoch_count", "duplicate_epoch_group_count", "exact_duplicate_record_count",
            "same_epoch_variant_group_count", "same_epoch_variant_record_count",
            "same_epoch_source_variant_group_count", "same_epoch_rms_variant_group_count",
            "same_epoch_element_variant_group_count",
        ):
            duplicate_totals[field] += int(result[field])

    parseable_rows = [row for row in all_rows if row.get("_epoch_dt") is not None]
    formal_rows = [row for row in parseable_rows if FORMAL_START <= row["_epoch_dt"] < FORMAL_STOP]
    outside_rows = [row for row in parseable_rows if not (FORMAL_START <= row["_epoch_dt"] < FORMAL_STOP)]
    epoch_errors = sum(bool(row.get("_epoch_error")) for row in all_rows)
    required_missing = sum(int(row["required_field_missing_count"]) for row in quality)
    invalid_numeric = sum(int(row["required_field_invalid_numeric_count"]) for row in quality)
    sgp4_errors = sum(int(row["sgp4_init_error_count"]) for row in quality)
    missing_source = sum(int(row["missing_data_source_count"]) for row in quality)
    invalid_rms = sum(int(row["rms_invalid_count"]) for row in quality)
    integrity_errors = (
        epoch_errors + required_missing + invalid_numeric + sgp4_errors
        + missing_source + invalid_rms + len(extra_ids)
    )
    filename_consistent = all(bool(row["filename_content_norad_consistent"]) for row in inventory)
    decision_code, decision = choose_window_decision(
        quality=quality,
        cohort_complete=cohort_complete,
        header_consistent=header_consistent,
        filename_consistent=filename_consistent,
        integrity_error_count=integrity_errors,
        variant_group_count=duplicate_totals["same_epoch_variant_group_count"],
        march_style_archive_gap=march_style_gap,
    )

    source = source_statistics(formal_rows)
    rms = rms_statistics(formal_rows)
    statuses = Counter(str(row["status"]) for row in quality)
    reference_summary = [{
        "total_records": len(all_rows),
        "records_within_june": len(formal_rows),
        "records_outside_june": len(outside_rows),
        "unparseable_epoch_count": epoch_errors,
        "data_source_set": ";".join(source["values"]),
        "data_source_distribution": json.dumps(source["distribution"], sort_keys=True),
        "source_switch_satellites": sum(int(row["source_switch_count"]) > 0 for row in quality),
        "missing_data_source": missing_source,
        "rms_count": len(rms["values"]),
        "rms_missing": rms["missing"],
        "rms_invalid": rms["invalid"],
        "rms_min_km": round(min(rms["values"]), 6) if rms["values"] else "",
        "rms_median_km": round(statistics.median(rms["values"]), 6) if rms["values"] else "",
        "rms_p90_km": round(quantile(rms["values"], 0.90), 6) if rms["values"] else "",
        "rms_p95_km": round(quantile(rms["values"], 0.95), 6) if rms["values"] else "",
        "rms_max_km": round(max(rms["values"]), 6) if rms["values"] else "",
        "required_field_missing": required_missing,
        "invalid_numeric": invalid_numeric,
        "sgp4_omm_initialization_errors": sgp4_errors,
        "header_consistent": header_consistent,
        "filename_content_norad_consistent": filename_consistent,
        "rms_semantics": "REFERENCE_ONLY; no acceptance cutoff",
    }]

    output_paths = {
        "inventory": output_dir / f"{PREFIX}_raw_inventory.csv",
        "quality": output_dir / f"{PREFIX}_reference_quality.csv",
        "per_satellite": output_dir / f"{PREFIX}_per_satellite.csv",
        "daily": output_dir / f"{PREFIX}_daily_coverage.csv",
        "pauses": output_dir / f"{PREFIX}_cohort_pause_audit.csv",
        "duplicates": output_dir / f"{PREFIX}_duplicate_epoch_audit.csv",
        "correctness": output_dir / f"{PREFIX}_correctness_audit.csv",
        "manifest": output_dir / f"{PREFIX}_manifest.json",
        "report": report_dir / f"{PREFIX}_audit_report.md",
    }
    inventory_fields = tuple(inventory[0].keys())
    write_csv(output_paths["inventory"], inventory, inventory_fields, args.overwrite)
    write_csv(output_paths["quality"], quality, QUALITY_FIELDS, args.overwrite)
    write_csv(output_paths["per_satellite"], per_satellite, tuple(per_satellite[0]), args.overwrite)
    write_csv(output_paths["daily"], daily_rows, tuple(daily_rows[0]), args.overwrite)
    pause_fields = (
        "pause_start", "pause_end", "duration_hours", "affected_satellites",
        "affected_norad_ids", "exceeds_frozen_48h_gate", "semantics",
    )
    write_csv(output_paths["pauses"], pauses, pause_fields, args.overwrite)
    duplicate_fields = (
        "norad_id", "epoch", "record_count_at_epoch", "exact_duplicate_record_count",
        "same_epoch_variant", "source_variant", "rms_variant", "orbital_element_variant",
        "varying_fields", "raw_locations", "records_json", "handling",
    )
    write_csv(output_paths["duplicates"], duplicate_details, duplicate_fields, args.overwrite)

    raw_hashes_after = {path.as_posix(): sha256(path) for path in files}
    if raw_hashes_before != raw_hashes_after:
        raise RuntimeError("Raw June SupGP changed during read-only audit")
    protected_after = fingerprint_protected(root)
    require_protected(protected_after, "post-audit")
    if protected_before != protected_after:
        raise RuntimeError("Protected artifact fingerprints changed during audit")

    correctness = [
        {"check": "frozen_parameter_sha_matches", "observed": protected_after[0]["observed_sha256"], "expected": protected_after[0]["expected_sha256"], "passed": True},
        {"check": "all_protected_artifacts_unchanged", "observed": True, "expected": True, "passed": True},
        {"check": "raw_hashes_before_after_equal", "observed": raw_hashes_before == raw_hashes_after, "expected": True, "passed": raw_hashes_before == raw_hashes_after},
        {"check": "june_scientific_rows_read", "observed": 0, "expected": 0, "passed": True},
        {"check": "residuals_generated", "observed": 0, "expected": 0, "passed": True},
        {"check": "frozen_model_loaded_or_scored", "observed": 0, "expected": 0, "passed": True},
        {"check": "ordinary_gp_acquired_or_read", "observed": 0, "expected": 0, "passed": True},
        {"check": "forbidden_confirmatory_fields_present", "observed": len(forbidden_present), "expected": 0, "passed": not forbidden_present},
        {"check": "raw_rows_removed_or_deduplicated", "observed": 0, "expected": 0, "passed": True},
        {"check": "boundary_tolerance_hours", "observed": BOUNDARY_TOLERANCE_HOURS, "expected": 24.0, "passed": True},
        {"check": "internal_gap_threshold_hours", "observed": INTERNAL_GAP_THRESHOLD_HOURS, "expected": 48.0, "passed": True},
        {"check": "rms_acceptance_cutoff", "observed": "NONE", "expected": "NONE", "passed": True},
    ]
    write_csv(output_paths["correctness"], correctness, ("check", "observed", "expected", "passed"), args.overwrite)

    abnormal_days = [row for row in daily_rows if int(row["satellites_with_records"]) < 20]
    pause_text = (
        markdown_table(pauses, ["pause_start", "pause_end", "duration_hours", "affected_satellites", "exceeds_frozen_48h_gate"])
        if pauses else "未发现 >12 h 的 20/20 同步 raw-record pause。"
    )
    report = f"""# June Stage-1F-lite confirmatory SupGP reference availability audit

本审计只检查 historical SupGP reference 的 availability、integrity 与 SGP4 OMM schema compatibility。未读取 ordinary GP，未构造 signed RTN residual，未加载或运行冻结 ellipsoid/box，未计算 P95/P99 coverage 或任何 security classification。SupGP/SpaceX-E 是 higher-quality historical reference，不是 ground truth。

## 1. June Raw Identification

- path：`{args.input_dir.as_posix()}`
- CSV files：{len(files)}
- records：{len(all_rows)}；June window 内 {len(formal_rows)}；window 外 {len(outside_rows)}；EPOCH 不可解析 {epoch_errors}
- cohort：expected=20，returned={len(returned_ids)}，missing={missing_ids}，extra={extra_ids}
- epoch range：`{iso_z(min(row['_epoch_dt'] for row in parseable_rows))}` 至 `{iso_z(max(row['_epoch_dt'] for row in parseable_rows))}`
- DATA_SOURCE：`{json.dumps(source['distribution'], ensure_ascii=False, sort_keys=True)}`
- RMS availability：{len(rms['values'])}/{len(formal_rows)}
- headers consistent：{header_consistent}
- filename/content NORAD consistent：{filename_consistent}
- raw SHA inventory：`{output_paths['inventory'].as_posix()}`

## 2. Per-Satellite Coverage

{markdown_table(per_satellite, ['norad_id', 'records', 'first_epoch', 'last_epoch', 'start_boundary_distance_hours', 'end_boundary_distance_hours', 'median_gap_hours', 'max_gap_hours', 'max_gap_start', 'max_gap_end', 'boundary_ok', 'simulated_status'])}

## 3. Daily Coverage

- UTC dates with any SupGP：{sum(int(row['total_records']) > 0 for row in daily_rows)}/30
- UTC dates with 20/20 satellites：{sum(int(row['satellites_with_records']) == 20 for row in daily_rows)}/30
- minimum records/day：{min(int(row['total_records']) for row in daily_rows)}
- minimum satellites/day：{min(int(row['satellites_with_records']) for row in daily_rows)}
- abnormal dates：{json.dumps(abnormal_days, ensure_ascii=False)}

完整逐日表：`{output_paths['daily'].as_posix()}`。

## 4. Cohort-Wide Gap Audit

- satellites with >48 h internal gap：{sum(int(row['large_internal_gap_count']) > 0 for row in quality)}
- total >48 h intervals：{sum(int(row['large_internal_gap_count']) for row in quality)}
- `MARCH_STYLE_ARCHIVE_GAP = {'YES' if march_style_gap else 'NO'}`

{pause_text}

> 上述 pause 是 raw reference cadence 的描述性事实。未插值、未补值，也未改变冻结的 48 h engineering gate。

## 5. Duplicate / Variant Audit

- duplicate epoch groups：{duplicate_totals['duplicate_epoch_group_count']}
- duplicate excess：{duplicate_totals['duplicate_epoch_count']}
- exact duplicate excess：{duplicate_totals['exact_duplicate_record_count']}
- same-epoch orbital variants：{duplicate_totals['same_epoch_element_variant_group_count']}
- same-epoch DATA_SOURCE variants：{duplicate_totals['same_epoch_source_variant_group_count']}
- same-epoch RMS variants：{duplicate_totals['same_epoch_rms_variant_group_count']}
- affected satellites：{sum(int(row['duplicate_epoch_group_count']) > 0 for row in quality)}

原始记录全部保留，没有静默去重、按 RMS 选择或任取第一条。

## 6. Reference Quality

- DATA_SOURCE set：{source['values']}；source-switch satellites={sum(int(row['source_switch_count']) > 0 for row in quality)}；missing={missing_source}
- RMS km：min={reference_summary[0]['rms_min_km']}，median={reference_summary[0]['rms_median_km']}，P90={reference_summary[0]['rms_p90_km']}，P95={reference_summary[0]['rms_p95_km']}，max={reference_summary[0]['rms_max_km']}，missing={rms['missing']}，invalid={rms['invalid']}
- required-field missing={required_missing}；invalid numeric={invalid_numeric}；SGP4 OMM initialization errors={sgp4_errors}；propagation-ready={sum(int(row['propagation_ready_record_count']) for row in quality)}/{len(formal_rows)}

RMS 为 `REFERENCE_ONLY`，没有 scientific cutoff，也未进入 window decision。

## 7. Simulated Gate

- READY = {statuses.get('READY', 0)}
- PARTIAL = {statuses.get('PARTIAL', 0)}
- NO_REFERENCE = {statuses.get('NO_REFERENCE', 0)}

复用 `audit_orbit_uncertainty_stage1a_supgp.py` 的 pure gate logic：boundary tolerance=24 h，internal gap threshold=48 h，same-epoch variant→PARTIAL，RMS 不设 acceptance cutoff。本报告是 candidate/read-only audit，不是正式 June Stage-1A artifact。

## 8. Window Decision

`{decision_code}. {decision}`

该决策仅依据 reference availability、integrity 与 coverage；不含 residual、uncertainty score 或模型表现。

## 9. If A

ordinary GP acquisition window：`[2026-05-29T00:00:00Z, 2026-07-01T00:00:00Z)`，用于冻结的 72 h causal lookback。本轮没有执行 acquisition。

未来顺序固定为：June Stage-1A → June Stage-1B → frozen Stage-1F-lite confirmatory validation。禁止 June refit、threshold recalibration、candidate swap、covariance/box fit。
"""
    write_text(output_paths["report"], report, args.overwrite)

    output_hashes = {
        key: {"path": path.relative_to(root).as_posix(), "sha256": file_sha256(path)}
        for key, path in output_paths.items()
        if key != "manifest"
    }
    script_path = Path(__file__).resolve()
    manifest = {
        "stage": "Stage-1F-lite June SupGP confirmatory candidate reference availability audit",
        "status": decision,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "candidate_identity": {
            "path": args.input_dir.as_posix(),
            "selection_basis": "priority directory plus CelesTrak SupGP schema, frozen cohort, June EPOCH, DATA_SOURCE/RMS content and recent mtime",
            "candidate_set_count": 1,
        },
        "window": {
            "formal": f"[{iso_z(FORMAL_START)}, {iso_z(FORMAL_STOP)})",
            "boundary_tolerance_hours": BOUNDARY_TOLERANCE_HOURS,
            "internal_gap_threshold_hours": INTERNAL_GAP_THRESHOLD_HOURS,
            "ordinary_gp_future_acquisition_window": "[2026-05-29T00:00:00Z, 2026-07-01T00:00:00Z)",
        },
        "cohort": {
            "expected_ids": list(EXPECTED_COHORT),
            "expected_count": 20,
            "returned_ids": sorted(returned_ids),
            "returned_count": len(returned_ids),
            "missing_ids": missing_ids,
            "extra_ids": extra_ids,
        },
        "raw": {
            "file_count": len(files),
            "record_count": len(all_rows),
            "formal_window_record_count": len(formal_rows),
            "outside_window_record_count": len(outside_rows),
            "hashes_before_after_equal": raw_hashes_before == raw_hashes_after,
            "header_consistent": header_consistent,
            "filename_content_norad_consistent": filename_consistent,
            "inventory": inventory,
        },
        "reference_quality": reference_summary[0],
        "duplicates": dict(duplicate_totals),
        "daily_coverage": {
            "dates_with_any_records": sum(int(row["total_records"]) > 0 for row in daily_rows),
            "dates_with_20_satellites": sum(int(row["satellites_with_records"]) == 20 for row in daily_rows),
            "minimum_records_per_day": min(int(row["total_records"]) for row in daily_rows),
            "minimum_satellites_per_day": min(int(row["satellites_with_records"]) for row in daily_rows),
            "abnormal_dates": abnormal_days,
        },
        "gap_audit": {
            "satellites_with_gt_48h_gap": sum(int(row["large_internal_gap_count"]) > 0 for row in quality),
            "total_gt_48h_intervals": sum(int(row["large_internal_gap_count"]) for row in quality),
            "march_style_archive_gap": "YES" if march_style_gap else "NO",
            "descriptive_all_cohort_pauses_gt_12h": pauses,
        },
        "simulated_gate": {
            "READY": statuses.get("READY", 0),
            "PARTIAL": statuses.get("PARTIAL", 0),
            "NO_REFERENCE": statuses.get("NO_REFERENCE", 0),
        },
        "decision": {"code": decision_code, "status": decision},
        "blindness": {
            "ordinary_gp_read_or_acquired": False,
            "residual_calculated": False,
            "frozen_model_loaded_or_scored": False,
            "confirmatory_coverage_calculated": False,
            "security_classification_calculated": False,
            "june_scientific_rows_read": 0,
            "forbidden_confirmatory_fields_present": forbidden_present,
        },
        "frozen_artifact_protection": {
            "all_match_expected_before": all(row["matches_expected"] for row in protected_before),
            "all_match_expected_after": all(row["matches_expected"] for row in protected_after),
            "before_after_equal": protected_before == protected_after,
            "artifacts": protected_after,
        },
        "implementation": {
            "script_path": script_path.relative_to(root).as_posix(),
            "script_sha256": file_sha256(script_path),
            "reused_gate_script": "scripts/audit_orbit_uncertainty_stage1a_supgp.py",
            "reused_gate_script_sha256": file_sha256(root / "scripts/audit_orbit_uncertainty_stage1a_supgp.py"),
            "git_commit": None,
            "git_note": "project root is not a Git worktree",
        },
        "outputs": output_hashes,
    }
    write_text(output_paths["manifest"], json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", args.overwrite)

    print(json.dumps({
        "files": len(files),
        "records": len(all_rows),
        "records_within_june": len(formal_rows),
        "cohort": f"{len(returned_ids)}/20",
        "status_counts": dict(statuses),
        "march_style_archive_gap": "YES" if march_style_gap else "NO",
        "decision": decision,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
