#!/usr/bin/env python3
"""Audit historical Starlink SupGP ingestion and assign Stage-1A quality gates.

This script is intentionally limited to reference ingestion.  It reads raw SupGP
CSV files without modifying them, does not propagate any orbit, does not pair an
ordinary GP with a reference, and does not calculate a residual or uncertainty
boundary.
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
from typing import Any, Iterable, Sequence

from sgp4 import omm
from sgp4.api import Satrec

try:
    from scripts.orbit_uncertainty_stage1_window import (
        FORMAL_START,
        FORMAL_STOP_EXCLUSIVE,
        WINDOW_TAG,
    )
except ModuleNotFoundError:
    from orbit_uncertainty_stage1_window import (
        FORMAL_START,
        FORMAL_STOP_EXCLUSIVE,
        WINDOW_TAG,
    )

OUTPUT_PREFIX = f"orbit_uncertainty_stage1_{WINDOW_TAG}"
DEFAULT_SELECTION = Path(f"outputs/metrics/{OUTPUT_PREFIX}_satellite_selection.csv")
DEFAULT_INPUT_DIR = Path("data/orbit_uncertainty_stage1/raw/celestrak_supgp")
DEFAULT_QUALITY_OUTPUT = Path(f"outputs/metrics/{OUTPUT_PREFIX}_supgp_reference_quality.csv")
DEFAULT_INVENTORY_OUTPUT = Path(f"outputs/metrics/{OUTPUT_PREFIX}_supgp_raw_inventory.csv")
DEFAULT_DUPLICATE_OUTPUT = Path(f"outputs/metrics/{OUTPUT_PREFIX}_supgp_duplicate_epoch_audit.csv")
DEFAULT_MANIFEST_OUTPUT = Path(f"outputs/metrics/{OUTPUT_PREFIX}_supgp_reference_quality_manifest.json")
DEFAULT_REPORT_OUTPUT = Path(f"outputs/reports/{OUTPUT_PREFIX}_supgp_ingestion_audit.md")

# This is the SGP4-compatible field set already exercised by the Stage-0
# Starlink SupGP smoke pipeline. RMS and DATA_SOURCE are reference-quality
# metadata and are audited separately.
REQUIRED_ORBITAL_FIELDS = (
    "OBJECT_NAME",
    "OBJECT_ID",
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "EPHEMERIS_TYPE",
    "CLASSIFICATION_TYPE",
    "NORAD_CAT_ID",
    "ELEMENT_SET_NO",
    "REV_AT_EPOCH",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
)

NUMERIC_ORBITAL_FIELDS = (
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "EPHEMERIS_TYPE",
    "NORAD_CAT_ID",
    "ELEMENT_SET_NO",
    "REV_AT_EPOCH",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
)

QUALITY_FIELDS = (
    "norad_id",
    "object_name",
    "status",
    "record_count",
    "formal_window_record_count",
    "propagation_ready_record_count",
    "first_epoch",
    "last_epoch",
    "coverage_span_hours",
    "coverage_span_days",
    "formal_window_coverage_span_fraction",
    "start_boundary_gap_hours",
    "end_boundary_gap_hours",
    "candidate_usable_interval_start",
    "candidate_usable_interval_end",
    "excluded_intervals",
    "data_sources",
    "source_distribution",
    "source_switch_count",
    "source_switch_epochs",
    "missing_data_source_count",
    "rms_count",
    "rms_missing_count",
    "rms_invalid_count",
    "rms_min_km",
    "rms_median_km",
    "rms_p90_km",
    "rms_p95_km",
    "rms_max_km",
    "rms_max_robust_z",
    "rms_robust_outlier_candidate_count",
    "rms_robust_outlier_candidate_epochs",
    "rms_sudden_spike_candidate_count",
    "rms_sudden_spike_candidate_epochs",
    "rms_high_candidate_longest_run",
    "rms_high_candidate_longest_run_start",
    "rms_high_candidate_longest_run_end",
    "rms_high_candidate_longest_run_span_hours",
    "rms_max_adjacent_change_km",
    "median_gap_hours",
    "p95_gap_hours",
    "max_gap_hours",
    "large_internal_gap_count",
    "large_internal_gap_intervals",
    "duplicate_epoch_count",
    "duplicate_epoch_group_count",
    "exact_duplicate_record_count",
    "same_epoch_variant_group_count",
    "same_epoch_variant_record_count",
    "same_epoch_source_variant_group_count",
    "same_epoch_rms_variant_group_count",
    "same_epoch_element_variant_group_count",
    "required_field_missing_count",
    "required_field_missing_fields",
    "required_field_invalid_numeric_count",
    "required_field_invalid_numeric_fields",
    "sgp4_init_error_count",
    "epoch_parse_error_count",
    "epoch_timezone_explicit_count",
    "epoch_utc_assumed_from_schema_count",
    "epoch_obvious_year_anomaly_count",
    "creation_date_field_present",
    "creation_date_parse_error_count",
    "raw_order_inversion_count",
    "raw_file_count",
    "notes",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_z(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> tuple[datetime, bool]:
    """Parse a timestamp as UTC and report whether the raw value had a zone.

    Historical CelesTrak SupGP CSV EPOCH values are UTC by schema but the CSV
    strings in this archive do not carry a literal Z/offset.  Naive values are
    therefore explicitly counted as schema-based UTC assumptions.
    """

    text = str(value or "").strip()
    if not text:
        raise ValueError("empty timestamp")
    explicit = bool(re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", text, flags=re.IGNORECASE))
    normalized = text[:-1] + "+00:00" if text.upper().endswith("Z") else text
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), explicit


def quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def rounded(value: float | None, digits: int = 6) -> float | str:
    return "" if value is None else round(float(value), digits)


def write_csv(path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output without --overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output without --overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_selection(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Stage-1 selection does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    for row in rows:
        norad = str(row.get("NORAD_CAT_ID") or row.get("norad_id") or "").strip()
        name = str(row.get("OBJECT_NAME") or row.get("object_name") or "").strip()
        if not norad.isdigit():
            raise ValueError(f"Invalid NORAD_CAT_ID in selection: {norad!r}")
        output.append({"NORAD_CAT_ID": norad, "OBJECT_NAME": name})
    ids = [row["NORAD_CAT_ID"] for row in output]
    if len(output) != 20 or len(set(ids)) != 20:
        raise ValueError(f"Expected 20 rows / 20 unique NORAD IDs, got {len(output)} / {len(set(ids))}")
    return output


def discover_and_read(
    input_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Path], set[str]]:
    if not input_dir.exists():
        raise FileNotFoundError(f"SupGP raw directory does not exist: {input_dir}")
    files = sorted(input_dir.glob("*.csv"))
    rows: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    headers: set[str] = set()
    for path in files:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            file_rows = list(reader)
        if not fieldnames:
            inventory.append({
                "raw_file": path.as_posix(), "file_size_bytes": path.stat().st_size,
                "sha256": sha256(path), "row_count": 0, "header_json": "[]",
                "norad_ids": "", "first_epoch": "", "last_epoch": "",
                "parse_notes": "missing CSV header",
            })
            continue
        headers.update(fieldnames)
        file_epochs: list[datetime] = []
        file_ids: set[str] = set()
        for row_number, source_row in enumerate(file_rows, start=2):
            row = {str(key).strip(): value for key, value in source_row.items() if key is not None}
            row["_raw_file"] = path.as_posix()
            row["_raw_row_number"] = row_number
            row["_raw_sequence"] = len(rows)
            epoch = None
            epoch_explicit_zone = False
            epoch_error = ""
            try:
                epoch, epoch_explicit_zone = parse_utc(row.get("EPOCH"))
                file_epochs.append(epoch)
            except (TypeError, ValueError) as exc:
                epoch_error = str(exc)
            row["_epoch_dt"] = epoch
            row["_epoch_explicit_zone"] = epoch_explicit_zone
            row["_epoch_error"] = epoch_error
            norad = str(row.get("NORAD_CAT_ID", "")).strip()
            if norad:
                file_ids.add(norad)
            rows.append(row)
        inventory.append({
            "raw_file": path.as_posix(),
            "file_size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "row_count": len(file_rows),
            "header_json": json.dumps(fieldnames, ensure_ascii=False),
            "norad_ids": ";".join(sorted(file_ids)),
            "first_epoch": iso_z(min(file_epochs)) if file_epochs else "",
            "last_epoch": iso_z(max(file_epochs)) if file_epochs else "",
            "parse_notes": "",
        })
    return rows, inventory, files, headers


def gap_hours(epochs: Iterable[datetime]) -> list[tuple[datetime, datetime, float]]:
    ordered = sorted(set(epochs))
    return [
        (left, right, (right - left).total_seconds() / 3600.0)
        for left, right in zip(ordered, ordered[1:])
    ]


def cohort_gap_overlap_statistics(
    grouped_rows: dict[str, list[dict[str, Any]]],
    target_ids: Sequence[str],
    formal_start: datetime,
    formal_stop: datetime,
    descriptive_min_gap_hours: float = 12.0,
) -> dict[str, Any]:
    """Describe cohort overlap of long cadence gaps without changing gate status."""
    intervals: list[tuple[datetime, datetime, str]] = []
    for norad in target_ids:
        epochs = [
            row["_epoch_dt"] for row in grouped_rows.get(norad, [])
            if row.get("_epoch_dt") is not None
            and formal_start <= row["_epoch_dt"] < formal_stop
        ]
        for left, right, hours in gap_hours(epochs):
            if hours > descriptive_min_gap_hours:
                intervals.append((left, right, norad))

    points = sorted({value for left, right, _ in intervals for value in (left, right)})
    segments: list[tuple[datetime, datetime, tuple[str, ...]]] = []
    for left, right in zip(points, points[1:]):
        midpoint = left + (right - left) / 2
        active = tuple(sorted({
            norad for start, stop, norad in intervals if start < midpoint < stop
        }))
        if active:
            segments.append((left, right, active))

    target_count = len(target_ids)
    full_segments: list[tuple[datetime, datetime]] = []
    for left, right, active in segments:
        if len(active) != target_count:
            continue
        if full_segments and full_segments[-1][1] == left:
            full_segments[-1] = (full_segments[-1][0], right)
        else:
            full_segments.append((left, right))
    longest = max(
        full_segments,
        key=lambda pair: (pair[1] - pair[0]).total_seconds(),
        default=None,
    )
    duration_hours = (
        (longest[1] - longest[0]).total_seconds() / 3600.0 if longest else None
    )
    return {
        "descriptive_min_gap_hours_exclusive": descriptive_min_gap_hours,
        "qualifying_interval_count": len(intervals),
        "satellites_with_qualifying_interval": len({norad for _, _, norad in intervals}),
        "max_simultaneous_satellite_overlap": max(
            (len(active) for _, _, active in segments), default=0
        ),
        "longest_all_cohort_overlap_start": iso_z(longest[0]) if longest else "",
        "longest_all_cohort_overlap_end": iso_z(longest[1]) if longest else "",
        "longest_all_cohort_overlap_hours": rounded(duration_hours),
        "exceeds_frozen_48h_internal_gap_threshold": bool(
            duration_hours is not None and duration_hours > 48.0
        ),
        "semantics": (
            "descriptive overlap of per-satellite gaps longer than the stated minimum; "
            "does not alter the frozen per-satellite reference-quality gate"
        ),
    }


def source_statistics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    sources = [str(row.get("DATA_SOURCE", "")).strip() for row in rows]
    nonempty = [source for source in sources if source]
    distribution = Counter(nonempty)
    ordered = sorted(
        (row for row in rows if row.get("_epoch_dt") is not None),
        key=lambda row: (row["_epoch_dt"], row["_raw_sequence"]),
    )
    switch_epochs: list[str] = []
    previous = None
    for row in ordered:
        current = str(row.get("DATA_SOURCE", "")).strip()
        if not current:
            continue
        if previous is not None and current != previous:
            switch_epochs.append(iso_z(row["_epoch_dt"]))
        previous = current
    return {
        "values": sorted(distribution),
        "distribution": distribution,
        "missing": len(sources) - len(nonempty),
        "switch_epochs": switch_epochs,
    }


def rms_statistics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    ordered: list[tuple[datetime, float]] = []
    missing = 0
    invalid = 0
    for row in rows:
        raw = row.get("RMS")
        if raw in (None, ""):
            missing += 1
            continue
        try:
            value = float(raw)
            if not math.isfinite(value) or value < 0:
                raise ValueError("RMS must be finite and nonnegative")
        except (TypeError, ValueError):
            invalid += 1
            continue
        if row.get("_epoch_dt") is not None:
            ordered.append((row["_epoch_dt"], value))
    ordered.sort(key=lambda item: item[0])
    values = [item[1] for item in ordered]
    if not values:
        return {
            "values": [], "missing": missing, "invalid": invalid, "median": None,
            "max_robust_z": None, "outliers": [], "spikes": [],
            "longest_run": 0, "longest_run_start": None, "longest_run_end": None,
            "longest_run_span_hours": None, "max_adjacent_change": None,
        }
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    robust_z = []
    for value in values:
        if mad > 0:
            robust_z.append(abs(value - median) / (1.4826 * mad))
        else:
            robust_z.append(0.0 if value == median else math.inf)
    # Reuse the Stage-0 descriptive robust-z candidate rule. It is not an RMS
    # acceptance threshold and never changes READY/PARTIAL by itself.
    flags = [value > 3.5 for value in robust_z]
    spike_indexes: list[int] = []
    for index in range(1, len(values) - 1):
        if flags[index] and values[index] > values[index - 1] and values[index] > values[index + 1]:
            spike_indexes.append(index)
    longest = current = 0
    longest_end_index: int | None = None
    for index, flag in enumerate(flags):
        current = current + 1 if flag else 0
        if current > longest:
            longest = current
            longest_end_index = index
    longest_start = ordered[longest_end_index - longest + 1][0] if longest_end_index is not None else None
    longest_end = ordered[longest_end_index][0] if longest_end_index is not None else None
    adjacent = [abs(right - left) for left, right in zip(values, values[1:])]
    return {
        "values": values,
        "missing": missing,
        "invalid": invalid,
        "median": median,
        "max_robust_z": max(robust_z),
        "outliers": [ordered[index] for index, flag in enumerate(flags) if flag],
        "spikes": [ordered[index] for index in spike_indexes],
        "longest_run": longest,
        "longest_run_start": longest_start,
        "longest_run_end": longest_end,
        "longest_run_span_hours": (
            (longest_end - longest_start).total_seconds() / 3600.0
            if longest_start is not None and longest_end is not None else None
        ),
        "max_adjacent_change": max(adjacent) if adjacent else None,
    }


def row_payload(row: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(value or "")
        for key, value in row.items()
        if not key.startswith("_")
    }


def duplicate_statistics(rows: Sequence[dict[str, Any]]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    by_epoch: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        epoch = row.get("_epoch_dt")
        if epoch is not None:
            by_epoch[iso_z(epoch)].append(row)
    exact_excess = 0
    variant_groups = 0
    variant_records = 0
    source_variant_groups = 0
    rms_variant_groups = 0
    element_variant_groups = 0
    details: list[dict[str, Any]] = []
    orbital_compare_fields = [field for field in REQUIRED_ORBITAL_FIELDS if field != "EPOCH"]
    duplicate_groups = {epoch: group for epoch, group in by_epoch.items() if len(group) > 1}
    for epoch, group in sorted(duplicate_groups.items()):
        payloads = [row_payload(row) for row in group]
        payload_keys = [json.dumps(payload, ensure_ascii=False, sort_keys=True) for payload in payloads]
        exact_count = len(payload_keys) - len(set(payload_keys))
        exact_excess += exact_count
        varying_fields = sorted(
            field for field in set().union(*(payload.keys() for payload in payloads))
            if len({payload.get(field, "") for payload in payloads}) > 1
        )
        is_variant = bool(varying_fields)
        if is_variant:
            variant_groups += 1
            variant_records += len(group)
        source_variant = "DATA_SOURCE" in varying_fields
        rms_variant = "RMS" in varying_fields
        element_variant = any(field in varying_fields for field in orbital_compare_fields)
        source_variant_groups += int(source_variant)
        rms_variant_groups += int(rms_variant)
        element_variant_groups += int(element_variant)
        details.append({
            "norad_id": str(group[0].get("NORAD_CAT_ID", "")).strip(),
            "epoch": epoch,
            "record_count_at_epoch": len(group),
            "exact_duplicate_record_count": exact_count,
            "same_epoch_variant": is_variant,
            "source_variant": source_variant,
            "rms_variant": rms_variant,
            "orbital_element_variant": element_variant,
            "varying_fields": ";".join(varying_fields),
            "raw_locations": ";".join(f"{row['_raw_file']}:{row['_raw_row_number']}" for row in group),
            "records_json": json.dumps(payloads, ensure_ascii=False, sort_keys=True),
            "handling": "retained_all_raw_records_no_epoch_deduplication",
        })
    return ({
        "duplicate_epoch_count": sum(len(group) - 1 for group in duplicate_groups.values()),
        "duplicate_epoch_group_count": len(duplicate_groups),
        "exact_duplicate_record_count": exact_excess,
        "same_epoch_variant_group_count": variant_groups,
        "same_epoch_variant_record_count": variant_records,
        "same_epoch_source_variant_group_count": source_variant_groups,
        "same_epoch_rms_variant_group_count": rms_variant_groups,
        "same_epoch_element_variant_group_count": element_variant_groups,
    }, details)


def required_field_statistics(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    missing = {
        field: sum(row.get(field) in (None, "") for row in rows)
        for field in REQUIRED_ORBITAL_FIELDS
    }
    invalid: Counter[str] = Counter()
    init_errors = 0
    ready_count = 0
    for row in rows:
        row_missing = any(row.get(field) in (None, "") for field in REQUIRED_ORBITAL_FIELDS)
        row_invalid = False
        for field in NUMERIC_ORBITAL_FIELDS:
            raw = row.get(field)
            if raw in (None, ""):
                continue
            try:
                value = float(raw)
                if not math.isfinite(value):
                    raise ValueError("non-finite")
            except (TypeError, ValueError):
                invalid[field] += 1
                row_invalid = True
        if row.get("_epoch_dt") is None:
            row_invalid = True
        if row_missing or row_invalid:
            continue
        try:
            satellite = Satrec()
            omm.initialize(satellite, {key: str(value) for key, value in row_payload(row).items()})
        except Exception:  # sgp4 reports schema/value-specific exceptions.
            init_errors += 1
            continue
        ready_count += 1
    return {
        "missing": {field: count for field, count in missing.items() if count},
        "invalid": dict(invalid),
        "init_errors": init_errors,
        "ready_count": ready_count,
    }


def raw_order_inversions(rows: Sequence[dict[str, Any]]) -> int:
    by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_file[str(row["_raw_file"])].append(row)
    inversions = 0
    for group in by_file.values():
        previous = None
        for row in sorted(group, key=lambda item: int(item["_raw_row_number"])):
            current = row.get("_epoch_dt")
            if current is not None and previous is not None and current < previous:
                inversions += 1
            if current is not None:
                previous = current
    return inversions


def classify_status(
    record_count: int,
    formal_count: int,
    propagation_ready_count: int,
    required_missing_count: int,
    required_invalid_count: int,
    init_errors: int,
    epoch_errors: int,
    missing_source: int,
    rms_missing_or_invalid: int,
    source_values: Sequence[str],
    source_switch_count: int,
    first_epoch: datetime | None,
    last_epoch: datetime | None,
    formal_start: datetime,
    formal_stop: datetime,
    boundary_tolerance_hours: float,
    large_internal_gap_count: int,
    same_epoch_variant_groups: int,
) -> tuple[str, list[str]]:
    if record_count == 0:
        return "NO_REFERENCE", ["没有返回 SupGP reference 记录"]
    if formal_count == 0:
        return "NO_REFERENCE", ["formal window 内没有 SupGP reference 记录"]
    if propagation_ready_count == 0:
        return "NO_REFERENCE", ["没有可建立 SGP4-compatible state 的 formal-window 记录"]

    reasons: list[str] = []
    if propagation_ready_count < formal_count or required_missing_count or required_invalid_count or init_errors:
        reasons.append("部分记录的 required orbital fields 不完整、无效或无法初始化 SGP4 state")
    if epoch_errors:
        reasons.append("存在不可解析 EPOCH")
    if missing_source or not source_values:
        reasons.append("DATA_SOURCE 缺失")
    if source_switch_count or len(source_values) > 1:
        reasons.append("存在 DATA_SOURCE switch，需在 Stage-1B 分段解释")
    if any(source != "SpaceX-E" for source in source_values):
        reasons.append("存在非 SpaceX-E source，reference 语义需单独确认")
    if rms_missing_or_invalid:
        reasons.append("RMS 缺失或无效，相关记录只能作为受限 reference")
    if first_epoch is None or (first_epoch - formal_start).total_seconds() / 3600.0 > boundary_tolerance_hours:
        reasons.append(f"formal window 起点 reference coverage 超过既有 {boundary_tolerance_hours:g} h 边界容差")
    if last_epoch is None or (formal_stop - last_epoch).total_seconds() / 3600.0 > boundary_tolerance_hours:
        reasons.append(f"formal window 终点 reference coverage 超过既有 {boundary_tolerance_hours:g} h 边界容差")
    if large_internal_gap_count:
        reasons.append("存在超过既有 engineering large-gap rule 的内部时间缺口")
    if same_epoch_variant_groups:
        reasons.append("同一 EPOCH 存在不同 reference 记录，Stage-1B 尚需显式选择规则")
    return ("PARTIAL", reasons) if reasons else ("READY", [])


def audit_satellite(
    norad: str,
    object_name: str,
    rows: Sequence[dict[str, Any]],
    formal_start: datetime,
    formal_stop: datetime,
    boundary_tolerance_hours: float,
    large_gap_hours: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    valid_epochs = [row["_epoch_dt"] for row in rows if row.get("_epoch_dt") is not None]
    formal_rows = [
        row for row in rows
        if row.get("_epoch_dt") is not None and formal_start <= row["_epoch_dt"] < formal_stop
    ]
    formal_epochs = [row["_epoch_dt"] for row in formal_rows]
    first = min(formal_epochs) if formal_epochs else None
    last = max(formal_epochs) if formal_epochs else None
    gaps = gap_hours(formal_epochs)
    gap_values = [item[2] for item in gaps]
    large_gaps = [item for item in gaps if item[2] > large_gap_hours]
    sources = source_statistics(formal_rows)
    rms = rms_statistics(formal_rows)
    duplicates, duplicate_details = duplicate_statistics(formal_rows)
    required = required_field_statistics(formal_rows)
    epoch_errors = sum(bool(row.get("_epoch_error")) for row in rows)
    explicit_zones = sum(bool(row.get("_epoch_explicit_zone")) for row in rows if row.get("_epoch_dt"))
    year_anomalies = sum(epoch.year < 1957 or epoch.year > 2100 for epoch in valid_epochs)
    creation_field_present = any("CREATION_DATE" in row for row in rows)
    creation_errors = 0
    if creation_field_present:
        for row in rows:
            if row.get("CREATION_DATE") in (None, ""):
                creation_errors += 1
                continue
            try:
                parse_utc(row["CREATION_DATE"])
            except (TypeError, ValueError):
                creation_errors += 1

    required_missing_count = sum(required["missing"].values())
    required_invalid_count = sum(required["invalid"].values())
    status, reasons = classify_status(
        record_count=len(rows),
        formal_count=len(formal_rows),
        propagation_ready_count=required["ready_count"],
        required_missing_count=required_missing_count,
        required_invalid_count=required_invalid_count,
        init_errors=required["init_errors"],
        epoch_errors=epoch_errors,
        missing_source=sources["missing"],
        rms_missing_or_invalid=rms["missing"] + rms["invalid"],
        source_values=sources["values"],
        source_switch_count=len(sources["switch_epochs"]),
        first_epoch=first,
        last_epoch=last,
        formal_start=formal_start,
        formal_stop=formal_stop,
        boundary_tolerance_hours=boundary_tolerance_hours,
        large_internal_gap_count=len(large_gaps),
        same_epoch_variant_groups=duplicates["same_epoch_variant_group_count"],
    )
    excluded = []
    if first is not None and first > formal_start:
        excluded.append(f"[{iso_z(formal_start)}, {iso_z(first)})")
    if last is not None and last < formal_stop:
        excluded.append(f"({iso_z(last)}, {iso_z(formal_stop)})")
    for left, right, _ in large_gaps:
        excluded.append(f"({iso_z(left)}, {iso_z(right)})")
    notes = list(reasons)
    if rows and not explicit_zones:
        notes.append("raw EPOCH 无显式时区后缀；沿用 CelesTrak SupGP schema/Stage-0 约定按 UTC 解析")
    if not creation_field_present:
        notes.append("SupGP CSV 不含 CREATION_DATE；其作为离线 higher-quality reference，不用于 ordinary-GP causal availability 判决")
    if rms["outliers"]:
        notes.append("存在 Stage-0 robust-z>3.5 RMS 描述性候选；未用于 quality gate，也不据此判定 maneuver")

    formal_duration_hours = (formal_stop - formal_start).total_seconds() / 3600.0
    coverage_span_hours = (last - first).total_seconds() / 3600.0 if first and last else None
    result: dict[str, Any] = {
        "norad_id": norad,
        "object_name": object_name or (str(rows[0].get("OBJECT_NAME", "")) if rows else ""),
        "status": status,
        "record_count": len(rows),
        "formal_window_record_count": len(formal_rows),
        "propagation_ready_record_count": required["ready_count"],
        "first_epoch": iso_z(first),
        "last_epoch": iso_z(last),
        "coverage_span_hours": rounded(coverage_span_hours),
        "coverage_span_days": rounded(coverage_span_hours / 24.0 if coverage_span_hours is not None else None),
        "formal_window_coverage_span_fraction": rounded(coverage_span_hours / formal_duration_hours if coverage_span_hours is not None else None),
        "start_boundary_gap_hours": rounded((first - formal_start).total_seconds() / 3600.0 if first else None),
        "end_boundary_gap_hours": rounded((formal_stop - last).total_seconds() / 3600.0 if last else None),
        "candidate_usable_interval_start": iso_z(first),
        "candidate_usable_interval_end": iso_z(last),
        "excluded_intervals": ";".join(excluded),
        "data_sources": ";".join(sources["values"]),
        "source_distribution": json.dumps(sources["distribution"], ensure_ascii=False, sort_keys=True),
        "source_switch_count": len(sources["switch_epochs"]),
        "source_switch_epochs": ";".join(sources["switch_epochs"]),
        "missing_data_source_count": sources["missing"],
        "rms_count": len(rms["values"]),
        "rms_missing_count": rms["missing"],
        "rms_invalid_count": rms["invalid"],
        "rms_min_km": rounded(min(rms["values"]) if rms["values"] else None),
        "rms_median_km": rounded(rms["median"]),
        "rms_p90_km": rounded(quantile(rms["values"], 0.90)),
        "rms_p95_km": rounded(quantile(rms["values"], 0.95)),
        "rms_max_km": rounded(max(rms["values"]) if rms["values"] else None),
        "rms_max_robust_z": rounded(rms["max_robust_z"]),
        "rms_robust_outlier_candidate_count": len(rms["outliers"]),
        "rms_robust_outlier_candidate_epochs": ";".join(iso_z(item[0]) for item in rms["outliers"]),
        "rms_sudden_spike_candidate_count": len(rms["spikes"]),
        "rms_sudden_spike_candidate_epochs": ";".join(iso_z(item[0]) for item in rms["spikes"]),
        "rms_high_candidate_longest_run": rms["longest_run"],
        "rms_high_candidate_longest_run_start": iso_z(rms["longest_run_start"]),
        "rms_high_candidate_longest_run_end": iso_z(rms["longest_run_end"]),
        "rms_high_candidate_longest_run_span_hours": rounded(rms["longest_run_span_hours"]),
        "rms_max_adjacent_change_km": rounded(rms["max_adjacent_change"]),
        "median_gap_hours": rounded(statistics.median(gap_values) if gap_values else None),
        "p95_gap_hours": rounded(quantile(gap_values, 0.95)),
        "max_gap_hours": rounded(max(gap_values) if gap_values else None),
        "large_internal_gap_count": len(large_gaps),
        "large_internal_gap_intervals": ";".join(
            f"{iso_z(left)}--{iso_z(right)} ({hours:.6f} h)" for left, right, hours in large_gaps
        ),
        **duplicates,
        "required_field_missing_count": required_missing_count,
        "required_field_missing_fields": ";".join(f"{field}={count}" for field, count in required["missing"].items()),
        "required_field_invalid_numeric_count": required_invalid_count,
        "required_field_invalid_numeric_fields": ";".join(f"{field}={count}" for field, count in required["invalid"].items()),
        "sgp4_init_error_count": required["init_errors"],
        "epoch_parse_error_count": epoch_errors,
        "epoch_timezone_explicit_count": explicit_zones,
        "epoch_utc_assumed_from_schema_count": len(valid_epochs) - explicit_zones,
        "epoch_obvious_year_anomaly_count": year_anomalies,
        "creation_date_field_present": creation_field_present,
        "creation_date_parse_error_count": creation_errors,
        "raw_order_inversion_count": raw_order_inversions(rows),
        "raw_file_count": len({row["_raw_file"] for row in rows}),
        "notes": "；".join(notes),
    }
    return result, duplicate_details


def markdown_table(rows: Sequence[dict[str, Any]], fields: Sequence[str]) -> str:
    if not rows:
        return "（无）"
    header = "| " + " | ".join(fields) + " |"
    divider = "| " + " | ".join("---" for _ in fields) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(field, "")).replace("|", "\\|") for field in fields) + " |")
    return "\n".join([header, divider, *body])


def report_gate_reasons(
    row: dict[str, Any],
    formal_start: datetime,
    formal_stop: datetime,
    boundary_tolerance_hours: float,
) -> list[str]:
    """Recreate report reasons through the authoritative classification function."""
    first_epoch = parse_utc(row["first_epoch"])[0] if row.get("first_epoch") else None
    last_epoch = parse_utc(row["last_epoch"])[0] if row.get("last_epoch") else None
    source_values = [value for value in str(row.get("data_sources", "")).split(";") if value]
    status, reasons = classify_status(
        record_count=int(row["record_count"]),
        formal_count=int(row["formal_window_record_count"]),
        propagation_ready_count=int(row["propagation_ready_record_count"]),
        required_missing_count=int(row["required_field_missing_count"]),
        required_invalid_count=int(row["required_field_invalid_numeric_count"]),
        init_errors=int(row["sgp4_init_error_count"]),
        epoch_errors=int(row["epoch_parse_error_count"]),
        missing_source=int(row["missing_data_source_count"]),
        rms_missing_or_invalid=int(row["rms_missing_count"]) + int(row["rms_invalid_count"]),
        source_values=source_values,
        source_switch_count=int(row["source_switch_count"]),
        first_epoch=first_epoch,
        last_epoch=last_epoch,
        formal_start=formal_start,
        formal_stop=formal_stop,
        boundary_tolerance_hours=boundary_tolerance_hours,
        large_internal_gap_count=int(row["large_internal_gap_count"]),
        same_epoch_variant_groups=int(row["same_epoch_variant_group_count"]),
    )
    if status != row["status"]:
        raise ValueError(
            f"Report status mismatch for NORAD {row['norad_id']}: "
            f"quality={row['status']}, recomputed={status}"
        )
    return reasons


def build_report(
    quality: Sequence[dict[str, Any]],
    inventory: Sequence[dict[str, Any]],
    duplicate_details: Sequence[dict[str, Any]],
    formal_start: datetime,
    formal_stop: datetime,
    boundary_tolerance_hours: float,
    large_gap_hours: float,
    non_target_ids: Sequence[str],
    cohort_gap_stats: dict[str, Any] | None = None,
    output_paths: dict[str, Path] | None = None,
) -> str:
    cohort_gap_stats = cohort_gap_stats or {}
    output_paths = output_paths or {
        "quality": DEFAULT_QUALITY_OUTPUT,
        "inventory": DEFAULT_INVENTORY_OUTPUT,
        "duplicate": DEFAULT_DUPLICATE_OUTPUT,
        "manifest": DEFAULT_MANIFEST_OUTPUT,
        "report": DEFAULT_REPORT_OUTPUT,
    }
    counts = Counter(row["status"] for row in quality)
    formal_duration_days = (formal_stop - formal_start).total_seconds() / 86400.0
    total_records = sum(int(row["record_count"]) for row in quality)
    formal_records = sum(int(row["formal_window_record_count"]) for row in quality)
    all_sources = Counter()
    for row in quality:
        all_sources.update(json.loads(str(row["source_distribution"])))
    rms_candidates = sorted(
        (row for row in quality if int(row["rms_robust_outlier_candidate_count"]) > 0),
        key=lambda row: float(row["rms_max_km"] or 0),
        reverse=True,
    )
    min_first = min((row["first_epoch"] for row in quality if row["first_epoch"]), default="")
    max_last = max((row["last_epoch"] for row in quality if row["last_epoch"]), default="")
    reasons_by_norad = {
        str(row["norad_id"]): report_gate_reasons(
            row, formal_start, formal_stop, boundary_tolerance_hours
        )
        for row in quality
    }
    reason_counts = Counter(
        reason
        for reasons in reasons_by_norad.values()
        for reason in reasons
    )
    boundary_incomplete_count = sum(
        (
            row["start_boundary_gap_hours"] == ""
            or float(row["start_boundary_gap_hours"]) > boundary_tolerance_hours
            or row["end_boundary_gap_hours"] == ""
            or float(row["end_boundary_gap_hours"]) > boundary_tolerance_hours
        )
        for row in quality
    )
    internal_gap_satellites = sum(int(row["large_internal_gap_count"]) > 0 for row in quality)
    variant_satellites = sum(int(row["same_epoch_variant_group_count"]) > 0 for row in quality)
    variant_groups = sum(int(row["same_epoch_variant_group_count"]) for row in quality)
    duplicate_groups = sum(int(row["duplicate_epoch_group_count"]) for row in quality)
    exact_duplicate_excess = sum(int(row["exact_duplicate_record_count"]) for row in quality)
    propagation_ready_satellites = sum(int(row["propagation_ready_record_count"]) > 0 for row in quality)
    full_ready = counts.get("READY", 0) == len(quality) == 20
    stage1b_answer = (
        f"20 颗均可按完整 {formal_duration_days:g} 天 reference coverage 进入 Stage-1B。"
        if full_ready else
        f"当前**不具备按既定 20 星 × {formal_duration_days:g} 天口径进入 formal Stage-1B residual library 的条件**。"
        f"当前 gate 状态为 READY={counts.get('READY', 0)}、PARTIAL={counts.get('PARTIAL', 0)}、"
        f"NO_REFERENCE={counts.get('NO_REFERENCE', 0)}；{propagation_ready_satellites}/{len(quality)} 颗"
        f"具有可初始化的 formal-window reference。完整连续 coverage 未通过的实际 warning 已在逐星表和"
        f" `excluded_intervals` / `large_internal_gap_intervals` 字段中列出。是否采用 segmented pilot"
        f" 必须另行冻结政策，本 gate 不插值、不补值，也不自动选择 same-epoch variant。"
    )
    duplicate_narrative = (
        f"原始记录未修改、未按 EPOCH 去重。当前 duplicate detail 记录 {duplicate_groups} 个 "
        f"duplicate epoch group：exact duplicate excess records={exact_duplicate_excess}，"
        f"same-epoch variant groups={variant_groups}；每组保存 source/RMS/orbital-field 差异和 raw location。"
        if duplicate_groups
        else
        "原始记录未修改、未按 EPOCH 去重。当前没有 duplicate epoch group；duplicate detail 文件保留表头。"
    )
    summary_rows = [{
        "norad_id": row["norad_id"],
        "status": row["status"],
        "records": row["record_count"],
        "first_epoch": row["first_epoch"],
        "last_epoch": row["last_epoch"],
        "rms_median_km": row["rms_median_km"],
        "rms_p95_km": row["rms_p95_km"],
        "rms_max_km": row["rms_max_km"],
        "max_gap_h": row["max_gap_hours"],
        "large_gap_intervals": row["large_internal_gap_intervals"],
        "variant_groups": row["same_epoch_variant_group_count"],
        "reason": "；".join(reasons_by_norad[str(row["norad_id"])]) or "无 gate warning",
    } for row in quality]
    reason_summary_rows = [
        {"gate_warning": reason, "satellites": count}
        for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    candidate_rows = [{
        "norad_id": row["norad_id"],
        "rms_max_km": row["rms_max_km"],
        "robust_candidates": row["rms_robust_outlier_candidate_count"],
        "sudden_spikes": row["rms_sudden_spike_candidate_count"],
        "longest_run": row["rms_high_candidate_longest_run"],
        "run_start": row["rms_high_candidate_longest_run_start"],
        "run_end": row["rms_high_candidate_longest_run_end"],
    } for row in rms_candidates]
    cohort_pause_text = (
        f"最长 20/20 overlap：`{cohort_gap_stats.get('longest_all_cohort_overlap_start')}` 至 "
        f"`{cohort_gap_stats.get('longest_all_cohort_overlap_end')}`，"
        f"{cohort_gap_stats.get('longest_all_cohort_overlap_hours')} h；"
        f"是否超过冻结 48 h gate："
        f"{cohort_gap_stats.get('exceeds_frozen_48h_internal_gap_threshold')}。"
        if cohort_gap_stats.get("longest_all_cohort_overlap_start") else
        "未发现满足描述性最小 gap 条件的 20/20 cohort overlap。"
    )
    return f"""# Orbit Uncertainty Stage-1A：historical SupGP ingestion audit

## 1. 范围与方法边界

本报告只审计 historical SupGP ingestion 与 reference quality，不传播轨道、不执行 ordinary-GP→SupGP pairing、不计算 RTN/residual、不建立 uncertainty boundary，也不运行 synthetic-B 或 Doppler verifier。SupGP 始终按 operator-derived higher-quality reference 表述，不作为 ground truth。

- formal window：`[{iso_z(formal_start)}, {iso_z(formal_stop)})`
- target shell：项目既有 controlled Starlink 20-target cohort，约 53.16° / 473 km proxy；结论不外推至整个 Starlink constellation
- raw CSV 文件：{len(inventory)}
- target coverage：{sum(int(row['record_count']) > 0 for row in quality)}/20
- total records：{total_records}
- formal-window records：{formal_records}
- raw returned span across cohort：`{min_first}` 至 `{max_last}`
- non-target NORAD records：{json.dumps(list(non_target_ids), ensure_ascii=False)}

### 仓库实现审计

- `scripts/prepare_orbit_uncertainty_stage1a_design.py`：Stage-1A 设计/请求清单生成器，属于 acquisition 前的 design artifact，不是 SupGP production ingestion。
- `scripts/acquire_orbit_uncertainty_stage1.py`：ordinary GP acquisition 已是 production-style、支持 `--reuse-only` 并正确保留 duplicate GP records；其 SupGP 部分已有 file discovery、source/RMS/epoch/gap 简化审计，但历史输出仍停在 `WAITING_FOR_SUPGP`，且缺少本轮要求的 formal count、required-field value audit、RMS p90/p95、p95 gap、duplicate variant 分类和三态 gate 明细。
- `scripts/run_orbit_uncertainty_stage0_starlink_smoke.py`：三星 exploratory smoke，已有可复用的 SupGP CSV parser、`sgp4.omm.initialize`、SGP4 propagation、TEME→GCRS 与 RTN 工具。本 gate 只复用其 schema/初始化约定，没有调用 propagation/RTN/residual。
- 既有 Stage-1 acquisition 输出目录为 `outputs/metrics/` 与 `outputs/reports/`；raw 固定在 `data/orbit_uncertainty_stage1/raw/`。本轮沿用该目录，不覆盖旧 acquisition baseline 输出。
- 现有 targeted tests 覆盖 parser、formal-window、duplicate preservation、source、gap、status 与 report semantic consistency。
- actual CSV schema 为 19 列 CelesTrak SupGP CSV，包含 Stage-0 已验证的 17 个 SGP4-compatible orbital fields，以及 `RMS`、`DATA_SOURCE`；不包含 `CREATION_DATE`。

## 2. Reference-quality gate

- READY = {counts.get('READY', 0)}
- PARTIAL = {counts.get('PARTIAL', 0)}
- NO_REFERENCE = {counts.get('NO_REFERENCE', 0)}

READY/PARTIAL 的 coverage 判断沿用 acquisition pipeline 已记录的 engineering rule：formal-window 两端各 {boundary_tolerance_hours:g} h 容差、内部 gap > {large_gap_hours:g} h 记作 large gap。它们只用于 ingestion readiness，不是轨道不确定性的科学阈值。RMS 不设 acceptance cutoff。

{markdown_table(summary_rows, ['norad_id', 'status', 'records', 'first_epoch', 'last_epoch', 'rms_median_km', 'rms_p95_km', 'rms_max_km', 'max_gap_h', 'large_gap_intervals', 'variant_groups', 'reason'])}

逐星 status reason 由与 quality classification 相同的 `classify_status()` 动态重算；如果 report 与 quality status 不一致，报告生成会直接失败。

{markdown_table(reason_summary_rows, ['gate_warning', 'satellites'])}

当前 coverage warning 摘要：formal-window boundary incomplete={boundary_incomplete_count}/{len(quality)}，internal gap > {large_gap_hours:g} h={internal_gap_satellites}/{len(quality)}，same-epoch variant={variant_satellites}/{len(quality)} 颗、共 {variant_groups} 组。逐星原生 reference span、large-gap interval 与全部 excluded intervals 以 quality CSV 为准；这些区间不代表自动插值、补值或批准进入 segmented pilot。

## 3. DATA_SOURCE audit

- distribution：`{json.dumps(all_sources, ensure_ascii=False, sort_keys=True)}`
- source switch satellites：{sum(int(row['source_switch_count']) > 0 for row in quality)}
- missing DATA_SOURCE：{sum(int(row['missing_data_source_count']) for row in quality)}

当前 source 统计由本次输入动态生成。若 source switch satellites 或 missing DATA_SOURCE 非零，相关对象会在逐星 reason 中标记为 PARTIAL；本 gate 不自动合并不同 source。

## 4. RMS descriptive audit

RMS 单位沿用 Stage-0 已记录的 CelesTrak SupGP fit-RMS 语义（km）。本报告给出 min/median/p90/p95/max，并复用 Stage-0 的 robust-z > 3.5 规则标记描述性检查候选；该规则不剔除记录、不改变 quality status，也不能单独证明 maneuver/regime change。

{markdown_table(candidate_rows, ['norad_id', 'rms_max_km', 'robust_candidates', 'sudden_spikes', 'longest_run', 'run_start', 'run_end'])}

`rms_high_candidate_longest_run` 用来观察候选是否连续；所有逐星数值见 quality CSV。Stage-0 对 65411 的 `possible_regime_change` 仍只是 exploratory label，本报告不升级为 confirmed maneuver。

## 5. Coverage / gap audit

- formal-window boundary-incomplete satellites：{boundary_incomplete_count}/{len(quality)}
- internal gap > {large_gap_hours:g} h satellites：{internal_gap_satellites}/{len(quality)}
- cohort max internal gap：{max((float(row['max_gap_hours']) for row in quality if row['max_gap_hours'] != ''), default=float('nan')):.6f} h
- raw-order inversion satellites：{sum(int(row['raw_order_inversion_count']) > 0 for row in quality)}
- EPOCH parse errors：{sum(int(row['epoch_parse_error_count']) for row in quality)}
- obvious-year anomalies：{sum(int(row['epoch_obvious_year_anomaly_count']) for row in quality)}
- descriptive cohort gap overlap（逐星 gap > {cohort_gap_stats.get('descriptive_min_gap_hours_exclusive', 12):g} h）：{cohort_pause_text}

CSV EPOCH 字符串本身无 `Z`/offset；按 CelesTrak SupGP schema 与既有 Stage-0 解析约定显式当作 UTC，并在 quality CSV 中记录 assumed count。CSV 不含 `CREATION_DATE`；这不妨碍其作为离线 reference，但它不能替代 ordinary GP 的 causal `CREATION_DATE <= evaluation_time` 选择逻辑。

## 6. Duplicate audit

- duplicate epoch excess records：{sum(int(row['duplicate_epoch_count']) for row in quality)}
- duplicate epoch groups：{duplicate_groups}
- exact duplicate excess records：{exact_duplicate_excess}
- same-epoch variant groups：{variant_groups}
- same-epoch variant satellites：{variant_satellites}/{len(quality)}

{duplicate_narrative}

## 7. Schema / required-field audit

- required orbital-field missing values：{sum(int(row['required_field_missing_count']) for row in quality)}
- invalid required numeric values：{sum(int(row['required_field_invalid_numeric_count']) for row in quality)}
- SGP4 OMM initialization errors：{sum(int(row['sgp4_init_error_count']) for row in quality)}
- propagation-ready formal records：{sum(int(row['propagation_ready_record_count']) for row in quality)}/{formal_records}

required field set 直接复用 Stage-0 已成功使用的 CelesTrak SupGP→`sgp4.omm.initialize` schema。本轮只初始化 state object 做 schema/value validation，没有执行任何 epoch propagation。

## 8. Stage-1B readiness

{stage1b_answer}

要进入既定 formal 20 × {formal_duration_days:g}-day Stage-1B，必须先解决本次逐星 gate reason 与 `excluded_intervals` 中实际列出的 reference-quality 问题。不得使用 later ordinary GP、插值、current SupGP 或 Stage-0 三星文件冒充缺失 reference；本报告也不替科研决策选择 same-epoch variant 或制定 RMS cutoff。

## 9. 输出与限制

- quality table：`{output_paths['quality'].as_posix()}`
- raw inventory：`{output_paths['inventory'].as_posix()}`
- duplicate audit：`{output_paths['duplicate'].as_posix()}`
- manifest：`{output_paths['manifest'].as_posix()}`
- 本报告：`{output_paths['report'].as_posix()}`

本 pilot 仅代表当前约 53.16° / 473 km proxy 的 Starlink shell。RMS spike、element episode 或 Stage-0 label 均不等于 confirmed maneuver；本轮没有建立 universal km threshold。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--quality-output", type=Path, default=DEFAULT_QUALITY_OUTPUT)
    parser.add_argument("--inventory-output", type=Path, default=DEFAULT_INVENTORY_OUTPUT)
    parser.add_argument("--duplicate-output", type=Path, default=DEFAULT_DUPLICATE_OUTPUT)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_OUTPUT)
    parser.add_argument("--window-tag", default=WINDOW_TAG)
    parser.add_argument("--formal-start", default=FORMAL_START)
    parser.add_argument("--formal-stop-exclusive", default=FORMAL_STOP_EXCLUSIVE)
    parser.add_argument(
        "--boundary-tolerance-hours", type=float, default=24.0,
        help="Existing acquisition engineering coverage rule; not a scientific uncertainty threshold",
    )
    parser.add_argument(
        "--large-gap-hours", type=float, default=48.0,
        help="Existing acquisition engineering gap flag; not a scientific uncertainty threshold",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selection = read_selection(args.selection)
    formal_start, _ = parse_utc(args.formal_start)
    formal_stop, _ = parse_utc(args.formal_stop_exclusive)
    if formal_stop <= formal_start:
        raise ValueError("formal stop must be later than formal start")
    if args.boundary_tolerance_hours < 0 or args.large_gap_hours <= 0:
        raise ValueError("coverage tolerances must be nonnegative/positive")
    expected_tag = f"{formal_start:%Y%m%d}_{(formal_stop - timedelta(days=1)):%Y%m%d}"
    if args.window_tag != expected_tag:
        raise ValueError(f"window tag mismatch: expected={expected_tag}, observed={args.window_tag}")

    all_rows, inventory, files, headers = discover_and_read(args.input_dir)
    hashes_before = {path.as_posix(): sha256(path) for path in files}
    target_ids = {row["NORAD_CAT_ID"] for row in selection}
    returned_ids = {str(row.get("NORAD_CAT_ID", "")).strip() for row in all_rows if row.get("NORAD_CAT_ID")}
    non_target_ids = sorted(returned_ids - target_ids)
    if non_target_ids:
        raise ValueError(f"SupGP raw directory includes non-target NORAD IDs: {non_target_ids}")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        grouped[str(row.get("NORAD_CAT_ID", "")).strip()].append(row)
    quality: list[dict[str, Any]] = []
    duplicate_details: list[dict[str, Any]] = []
    for target in selection:
        result, details = audit_satellite(
            target["NORAD_CAT_ID"], target["OBJECT_NAME"], grouped.get(target["NORAD_CAT_ID"], []),
            formal_start, formal_stop, args.boundary_tolerance_hours, args.large_gap_hours,
        )
        quality.append(result)
        duplicate_details.extend(details)
    cohort_gap_stats = cohort_gap_overlap_statistics(
        grouped,
        [target["NORAD_CAT_ID"] for target in selection],
        formal_start,
        formal_stop,
    )

    write_csv(args.quality_output, quality, QUALITY_FIELDS, args.overwrite)
    inventory_fields = (
        "raw_file", "file_size_bytes", "sha256", "row_count", "header_json",
        "norad_ids", "first_epoch", "last_epoch", "parse_notes",
    )
    write_csv(args.inventory_output, inventory, inventory_fields, args.overwrite)
    duplicate_fields = (
        "norad_id", "epoch", "record_count_at_epoch", "exact_duplicate_record_count",
        "same_epoch_variant", "source_variant", "rms_variant", "orbital_element_variant",
        "varying_fields", "raw_locations", "records_json", "handling",
    )
    write_csv(args.duplicate_output, duplicate_details, duplicate_fields, args.overwrite)

    report = build_report(
        quality, inventory, duplicate_details, formal_start, formal_stop,
        args.boundary_tolerance_hours, args.large_gap_hours, non_target_ids,
        cohort_gap_stats=cohort_gap_stats,
        output_paths={
            "quality": args.quality_output,
            "inventory": args.inventory_output,
            "duplicate": args.duplicate_output,
            "manifest": args.manifest_output,
            "report": args.report_output,
        },
    )
    write_text(args.report_output, report, args.overwrite)

    hashes_after = {path.as_posix(): sha256(path) for path in files}
    if hashes_before != hashes_after:
        raise RuntimeError("Raw SupGP hash changed during read-only audit")
    counts = Counter(row["status"] for row in quality)
    manifest = {
        "stage": "orbit_uncertainty_stage1a_historical_supgp_ingestion_reference_quality_gate",
        "window_tag": args.window_tag,
        "generated_utc": utc_now(),
        "scope": {
            "supgp_reference_semantics": "operator-derived higher-quality reference; not ground truth",
            "formal_window": f"[{iso_z(formal_start)}, {iso_z(formal_stop)})",
            "orbit_propagated": False,
            "ordinary_gp_supgp_paired": False,
            "residual_calculated": False,
            "uncertainty_boundary_calculated": False,
            "synthetic_b_used": False,
            "doppler_verifier_run": False,
        },
        "gate_rules": {
            "boundary_tolerance_hours": args.boundary_tolerance_hours,
            "large_internal_gap_hours": args.large_gap_hours,
            "rule_semantics": "existing acquisition engineering readiness rules; not scientific uncertainty thresholds",
            "rms_acceptance_cutoff": None,
            "rms_descriptive_candidate_rule": "Stage-0 robust-z > 3.5; does not affect status",
        },
        "selection": {"path": args.selection.as_posix(), "sha256": sha256(args.selection), "target_count": len(selection)},
        "raw": {
            "directory": args.input_dir.as_posix(), "file_count": len(files),
            "record_count": len(all_rows), "hashes_before_after_equal": hashes_before == hashes_after,
            "files": inventory,
        },
        "schema": {
            "actual_union_fields": sorted(headers),
            "required_orbital_fields": list(REQUIRED_ORBITAL_FIELDS),
            "creation_date_present": "CREATION_DATE" in headers,
            "timestamp_semantics": "EPOCH strings without an explicit zone are recorded and parsed as UTC per SupGP schema/Stage-0 convention",
        },
        "result": {
            "target_coverage": sum(int(row["record_count"]) > 0 for row in quality),
            "formal_window_record_count": sum(int(row["formal_window_record_count"]) for row in quality),
            "status_counts": dict(counts),
            "full_formal_window_stage1b_ready": counts.get("READY", 0) == 20,
            "cohort_reference_gap_overlap": cohort_gap_stats,
        },
        "outputs": {
            "quality": args.quality_output.as_posix(),
            "inventory": args.inventory_output.as_posix(),
            "duplicate_audit": args.duplicate_output.as_posix(),
            "report": args.report_output.as_posix(),
        },
    }
    write_text(args.manifest_output, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", args.overwrite)
    print(json.dumps({
        "files": len(files),
        "target_coverage": f"{sum(int(row['record_count']) > 0 for row in quality)}/20",
        "records": len(all_rows),
        "formal_window_records": sum(int(row["formal_window_record_count"]) for row in quality),
        "data_sources": dict(Counter(row.get("DATA_SOURCE", "") for row in all_rows)),
        "status_counts": dict(counts),
        "full_formal_window_stage1b_ready": counts.get("READY", 0) == 20,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
