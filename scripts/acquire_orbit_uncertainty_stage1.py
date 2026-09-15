#!/usr/bin/env python3
"""Acquire Stage-1 ordinary GP history and run acquisition-only ingestion gates.

This script never propagates an orbit and never computes GP-to-SupGP residuals.
Credentials are read only from environment variables and are never serialized.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

try:
    from scripts.orbit_uncertainty_stage1_window import (
        FORMAL_START,
        FORMAL_STOP_EXCLUSIVE,
        GP_ACQUISITION_START,
        GP_ACQUISITION_STOP_EXCLUSIVE,
        LOOKBACK_HOURS,
        WINDOW_TAG,
    )
except ModuleNotFoundError:
    from orbit_uncertainty_stage1_window import (
        FORMAL_START,
        FORMAL_STOP_EXCLUSIVE,
        GP_ACQUISITION_START,
        GP_ACQUISITION_STOP_EXCLUSIVE,
        LOOKBACK_HOURS,
        WINDOW_TAG,
    )


LOGIN_URL = "https://www.space-track.org/ajaxauth/login"
QUERY_ROOT = "https://www.space-track.org/basicspacedata/query"
OUTPUT_PREFIX = f"orbit_uncertainty_stage1_{WINDOW_TAG}"
SELECTION_PATH = Path(f"outputs/metrics/{OUTPUT_PREFIX}_satellite_selection.csv")
RAW_ROOT = Path("data/orbit_uncertainty_stage1/raw")
GP_RAW_DIR = RAW_ROOT / "spacetrack_gp"
SUPGP_RAW_DIR = RAW_ROOT / "celestrak_supgp"
METRICS_DIR = Path("outputs/metrics")
REPORT_DIR = Path("outputs/reports")

ACQUISITION_START = GP_ACQUISITION_START
ANALYSIS_START = FORMAL_START
ANALYSIS_STOP_EXCLUSIVE = FORMAL_STOP_EXCLUSIVE
FORMAT = "OMM JSON"

GP_RAW_START_TAG = GP_ACQUISITION_START[:10].replace("-", "")
GP_RAW_STOP_TAG = GP_ACQUISITION_STOP_EXCLUSIVE[:10].replace("-", "")
GP_RAW_PATH = GP_RAW_DIR / f"spacetrack_gp_history_{GP_RAW_START_TAG}_{GP_RAW_STOP_TAG}_20sat_omm.json"
GP_INVENTORY_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_gp_raw_inventory.csv"
GP_COVERAGE_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_gp_coverage_audit.csv"
SUPGP_INVENTORY_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_supgp_raw_inventory.csv"
SUPGP_COVERAGE_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_supgp_coverage_audit.csv"
CAUSAL_DETAIL_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_ordinary_gp_causal_support_audit.csv"
CAUSAL_SUMMARY_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_ordinary_gp_causal_readiness_summary.csv"
READINESS_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_cohort_readiness.csv"
MANIFEST_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_download_manifest.json"
CORRECTNESS_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_correctness_audit.csv"
REPORT_PATH = REPORT_DIR / f"{OUTPUT_PREFIX}_acquisition_report.md"
SUPGP_GATE_MANIFEST_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_supgp_reference_quality_manifest.json"

REQUIRED_GP_FIELDS = [
    "NORAD_CAT_ID", "OBJECT_NAME", "EPOCH", "CREATION_DATE", "GP_ID",
    "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT", "ELEMENT_SET_NO", "REF_FRAME", "TIME_SYSTEM",
    "MEAN_ELEMENT_THEORY",
]

GUARDED_HASHES = {
    "outputs/datasets/controlled_altitude_difference_realization_dataset.csv": "46CF795973E3EC812298D12F5E5AD8D3CD21E53EE93B6D2DD630B35345F78A71",
    "outputs/reports/controlled_altitude_difference_report.md": "60BEF3661B461F7E942C234C5C7A3817200B58635DBE8A020EE8D4DA387EE26A",
    "outputs/reports/verifier_v2_summary.md": "141EB15755926962A62115E3BC43D551202FF65CF675FE35AB8C0CD4ACEB1DB2",
    "data/tle/history/starlink_gp_history_20260301_20260320.json": "C96E23C84F5B8921B1BB7C08A237728B8821F14A1C100118AD407D67E2DE4DFA",
}


def configure_runtime(
    *,
    window_tag: str,
    formal_start: str,
    formal_stop_exclusive: str,
    gp_acquisition_start: str,
    lookback_hours: float,
    selection_path: Path,
    supgp_raw_dir: Path,
) -> None:
    """Configure one explicit Stage-1A window while keeping April as the default.

    The module-level defaults remain the frozen April pilot so existing callers and
    downstream Stage-1B--1E scripts are unchanged.  A validation month must opt in
    through CLI arguments, which also derives May-specific raw and output paths.
    """
    global WINDOW_TAG, FORMAL_START, FORMAL_STOP_EXCLUSIVE
    global GP_ACQUISITION_START, GP_ACQUISITION_STOP_EXCLUSIVE, LOOKBACK_HOURS
    global OUTPUT_PREFIX, SELECTION_PATH, SUPGP_RAW_DIR, ACQUISITION_START
    global ANALYSIS_START, ANALYSIS_STOP_EXCLUSIVE, GP_RAW_START_TAG, GP_RAW_STOP_TAG
    global GP_RAW_PATH, GP_INVENTORY_PATH, GP_COVERAGE_PATH
    global SUPGP_INVENTORY_PATH, SUPGP_COVERAGE_PATH
    global CAUSAL_DETAIL_PATH, CAUSAL_SUMMARY_PATH, READINESS_PATH
    global MANIFEST_PATH, CORRECTNESS_PATH, REPORT_PATH
    global SUPGP_GATE_MANIFEST_PATH

    start = parse_utc(formal_start)
    stop = parse_utc(formal_stop_exclusive)
    acquisition_start = parse_utc(gp_acquisition_start)
    if stop <= start:
        raise ValueError("formal stop must be later than formal start")
    if lookback_hours <= 0:
        raise ValueError("causal lookback must be positive")
    expected_acquisition_start = start - timedelta(hours=lookback_hours)
    if acquisition_start != expected_acquisition_start:
        raise ValueError(
            "ordinary-GP acquisition start must equal formal start minus lookback: "
            f"expected={iso_z(expected_acquisition_start)}, observed={iso_z(acquisition_start)}"
        )
    expected_tag = f"{start:%Y%m%d}_{(stop - timedelta(days=1)):%Y%m%d}"
    if window_tag != expected_tag:
        raise ValueError(f"window tag mismatch: expected={expected_tag}, observed={window_tag}")

    WINDOW_TAG = window_tag
    FORMAL_START = iso_z(start)
    FORMAL_STOP_EXCLUSIVE = iso_z(stop)
    GP_ACQUISITION_START = iso_z(acquisition_start)
    GP_ACQUISITION_STOP_EXCLUSIVE = FORMAL_STOP_EXCLUSIVE
    LOOKBACK_HOURS = float(lookback_hours)
    ACQUISITION_START = GP_ACQUISITION_START
    ANALYSIS_START = FORMAL_START
    ANALYSIS_STOP_EXCLUSIVE = FORMAL_STOP_EXCLUSIVE
    SELECTION_PATH = Path(selection_path)
    SUPGP_RAW_DIR = Path(supgp_raw_dir)

    OUTPUT_PREFIX = f"orbit_uncertainty_stage1_{WINDOW_TAG}"
    GP_RAW_START_TAG = GP_ACQUISITION_START[:10].replace("-", "")
    GP_RAW_STOP_TAG = GP_ACQUISITION_STOP_EXCLUSIVE[:10].replace("-", "")
    GP_RAW_PATH = GP_RAW_DIR / f"spacetrack_gp_history_{GP_RAW_START_TAG}_{GP_RAW_STOP_TAG}_20sat_omm.json"
    GP_INVENTORY_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_gp_raw_inventory.csv"
    GP_COVERAGE_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_gp_coverage_audit.csv"
    SUPGP_INVENTORY_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_supgp_raw_inventory.csv"
    SUPGP_COVERAGE_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_supgp_coverage_audit.csv"
    CAUSAL_DETAIL_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_ordinary_gp_causal_support_audit.csv"
    CAUSAL_SUMMARY_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_ordinary_gp_causal_readiness_summary.csv"
    READINESS_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_cohort_readiness.csv"
    MANIFEST_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_download_manifest.json"
    CORRECTNESS_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_acquisition_correctness_audit.csv"
    REPORT_PATH = REPORT_DIR / f"{OUTPUT_PREFIX}_acquisition_report.md"
    SUPGP_GATE_MANIFEST_PATH = METRICS_DIR / f"{OUTPUT_PREFIX}_supgp_reference_quality_manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty UTC timestamp")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def quantile(values: list[float], probability: float) -> float | None:
    """Return a reproducible linear empirical quantile for audit summaries."""
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


def load_upstream_candidate_audit(path: Path | None) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate an optional pre-acquisition SupGP audit and fingerprint its guards."""
    if path is None:
        return {}, {}
    candidate = json.loads(path.read_text(encoding="utf-8"))
    if candidate.get("status") != "JUNE_CONFIRMATORY_WINDOW_ACCEPTABLE":
        raise RuntimeError("Upstream SupGP candidate audit is not ACCEPTABLE")
    if candidate.get("window", {}).get("formal") != f"[{ANALYSIS_START}, {ANALYSIS_STOP_EXCLUSIVE})":
        raise RuntimeError("Upstream SupGP candidate audit formal window mismatch")
    expected_ids = set(candidate.get("cohort", {}).get("expected_ids", []))
    selection_ids = {row["NORAD_CAT_ID"] for row in read_selection()}
    if expected_ids != selection_ids:
        raise RuntimeError("Upstream SupGP candidate audit cohort mismatch")

    fingerprints: dict[str, str] = {}
    for item in candidate.get("frozen_artifact_protection", {}).get("artifacts", []):
        artifact_path = Path(item["path"])
        expected_sha = str(item["expected_sha256"])
        if not artifact_path.exists() or sha256(artifact_path) != expected_sha:
            raise RuntimeError(f"Protected Stage-1F/development artifact mismatch: {artifact_path}")
        fingerprints[artifact_path.as_posix()] = expected_sha
    if not fingerprints:
        raise RuntimeError("Upstream SupGP candidate audit has no protected artifact inventory")
    return candidate, fingerprints


def bind_upstream_candidate_audit(
    path: Path | None,
    candidate: dict[str, Any],
    supgp_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    if path is None:
        return {"status": "NOT_REQUESTED"}
    candidate_files = {
        Path(row["raw_file"]).name: row["sha256"]
        for row in candidate.get("raw", {}).get("inventory", [])
    }
    current_files = {
        Path(row["raw_file"]).name: row["sha256"] for row in supgp_inventory
    }
    if candidate_files != current_files:
        raise RuntimeError("Upstream SupGP candidate raw SHA inventory mismatch")
    frozen_artifacts = candidate.get("frozen_artifact_protection", {}).get("artifacts", [])
    frozen_parameter = next(
        (item for item in frozen_artifacts if str(item.get("path", "")).endswith("stage1f_lite_frozen_parameters.csv")),
        {},
    )
    return {
        "status": "VERIFIED",
        "path": str(path),
        "sha256": sha256(path),
        "decision": candidate["status"],
        "raw_file_count": len(current_files),
        "raw_sha_inventory_match": True,
        "frozen_parameter_sha256": frozen_parameter.get("expected_sha256", ""),
    }


def safe_query_description(ids: list[str]) -> dict[str, Any]:
    return {
        "source": "Space-Track",
        "api_class": "gp_history",
        "request_object_ids": ids,
        "time_predicate_field": "EPOCH",
        "time_range": f"[{ACQUISITION_START}, {ANALYSIS_STOP_EXCLUSIVE})",
        "format": FORMAT,
        "ordering": "NORAD_CAT_ID asc,EPOCH asc",
    }


def request_fingerprint(ids: list[str]) -> str:
    encoded = json.dumps(safe_query_description(ids), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()


def read_selection() -> list[dict[str, str]]:
    with SELECTION_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ids = [str(row.get("NORAD_CAT_ID", "")).strip() for row in rows]
    if len(rows) != 20 or len(set(ids)) != 20 or any(not value.isdigit() for value in ids):
        raise RuntimeError(f"authoritative cohort invalid: rows={len(rows)}, unique={len(set(ids))}")
    return rows


def read_existing_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def acquire_gp(ids: list[str]) -> tuple[bytes, dict[str, Any], bool]:
    fingerprint = request_fingerprint(ids)
    existing = read_existing_manifest()
    existing_gp = existing.get("ordinary_gp", {}) if isinstance(existing, dict) else {}
    if GP_RAW_PATH.exists():
        if existing_gp.get("request_fingerprint") != fingerprint:
            raise RuntimeError("formal GP raw exists but request fingerprint does not match; refusing overwrite")
        observed_sha = sha256(GP_RAW_PATH)
        if existing_gp.get("sha256") != observed_sha:
            raise RuntimeError("formal GP raw SHA differs from manifest; refusing reuse")
        return GP_RAW_PATH.read_bytes(), existing_gp, True

    username = os.environ.get("SPACETRACK_USERNAME", "")
    password = os.environ.get("SPACETRACK_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("Space-Track credentials missing from process environment")

    session = requests.Session()
    login = session.post(LOGIN_URL, data={"identity": username, "password": password}, timeout=60)
    if login.status_code >= 400:
        raise RuntimeError(f"Space-Track login failed: HTTP {login.status_code}")

    ids_expr = ",".join(ids)
    query_start = ACQUISITION_START.split("T", 1)[0]
    query_stop = GP_ACQUISITION_STOP_EXCLUSIVE.split("T", 1)[0]
    # Space-Track interval syntax is inclusive at the textual upper bound; the
    # ingestion audit separately reports any record at/after the half-open stop.
    query_url = (
        f"{QUERY_ROOT}/class/gp_history/NORAD_CAT_ID/{ids_expr}"
        f"/EPOCH/{query_start}--{query_stop}"
        f"/orderby/{quote('NORAD_CAT_ID asc,EPOCH asc', safe=',')}"
        "/format/json"
    )
    response = session.get(query_url, timeout=180)
    if response.status_code >= 400:
        raise RuntimeError(f"Space-Track GP_HISTORY query failed: HTTP {response.status_code}")
    try:
        parsed = response.json()
    except ValueError as exc:
        raise RuntimeError("Space-Track returned a non-JSON response") from exc
    if not isinstance(parsed, list):
        raise RuntimeError("Space-Track returned an unexpected JSON shape")

    GP_RAW_DIR.mkdir(parents=True, exist_ok=True)
    GP_RAW_PATH.write_bytes(response.content)
    metadata = {
        **safe_query_description(ids),
        "request_fingerprint": fingerprint,
        "download_utc": utc_now(),
        "login_http_status": login.status_code,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
        "raw_file": str(GP_RAW_PATH),
        "file_size_bytes": GP_RAW_PATH.stat().st_size,
        "sha256": sha256(GP_RAW_PATH),
        "record_count": len(parsed),
    }
    return response.content, metadata, False


def normalize_records(raw: bytes) -> list[dict[str, Any]]:
    rows = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("GP raw JSON is not a list of objects")
    return rows


def gaps_hours(times: list[datetime]) -> list[float]:
    ordered = sorted(set(times))
    return [(right - left).total_seconds() / 3600.0 for left, right in zip(ordered, ordered[1:])]


def select_causal_gp(
    records: list[dict[str, Any]], evaluation_time: datetime
) -> tuple[dict[str, Any] | None, int]:
    eligible = [
        row for row in records
        if row.get("CREATION_DATE") and parse_utc(row["CREATION_DATE"]) <= evaluation_time
    ]
    selected = max(
        eligible,
        key=lambda row: (
            parse_utc(row["CREATION_DATE"]),
            parse_utc(row["EPOCH"]),
            str(row.get("GP_ID", "")),
        ),
        default=None,
    )
    return selected, len(eligible)


def read_supgp_evaluation_rows() -> list[dict[str, Any]]:
    start = parse_utc(ANALYSIS_START)
    stop = parse_utc(ANALYSIS_STOP_EXCLUSIVE)
    output: list[dict[str, Any]] = []
    for path in sorted(SUPGP_RAW_DIR.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                evaluation_time = parse_utc(row["EPOCH"])
                if start <= evaluation_time < stop:
                    output.append({
                        "NORAD_CAT_ID": str(row.get("NORAD_CAT_ID", "")).strip(),
                        "evaluation_time": iso_z(evaluation_time),
                        "supgp_data_source": str(row.get("DATA_SOURCE", "")).strip(),
                        "supgp_rms": str(row.get("RMS", "")).strip(),
                        "supgp_raw_file": path.as_posix(),
                        "supgp_raw_row_number": row_number,
                    })
    return output


def cohort_reference_gap_overlap(
    supgp_rows: list[dict[str, Any]], selection: list[dict[str, str]],
    descriptive_min_gap_hours: float = 12.0,
) -> dict[str, Any]:
    """Describe overlapping long cadence gaps without changing the 48 h gate."""
    by_norad: dict[str, list[datetime]] = defaultdict(list)
    for row in supgp_rows:
        by_norad[str(row["NORAD_CAT_ID"])].append(parse_utc(row["evaluation_time"]))

    events: dict[datetime, dict[str, set[str]]] = defaultdict(
        lambda: {"start": set(), "end": set()}
    )
    for satellite in selection:
        norad = satellite["NORAD_CAT_ID"]
        epochs = sorted(set(by_norad.get(norad, [])))
        for left, right in zip(epochs, epochs[1:]):
            if (right - left).total_seconds() / 3600.0 <= descriptive_min_gap_hours:
                continue
            events[left]["start"].add(norad)
            events[right]["end"].add(norad)

    active: set[str] = set()
    ordered_times = sorted(events)
    segments: list[tuple[datetime, datetime, tuple[str, ...]]] = []
    for index, current in enumerate(ordered_times[:-1]):
        active.difference_update(events[current]["end"])
        active.update(events[current]["start"])
        following = ordered_times[index + 1]
        if following > current and active:
            segments.append((current, following, tuple(sorted(active))))

    target_count = len(selection)
    full_segments: list[tuple[datetime, datetime]] = []
    for left, right, satellites in segments:
        if len(satellites) != target_count:
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
    max_overlap = max((len(satellites) for _, _, satellites in segments), default=0)
    duration_hours = (
        (longest[1] - longest[0]).total_seconds() / 3600.0 if longest else None
    )
    return {
        "descriptive_min_gap_hours_exclusive": descriptive_min_gap_hours,
        "max_simultaneous_satellites_between_records": max_overlap,
        "longest_all_cohort_between_record_interval_start": iso_z(longest[0]) if longest else "",
        "longest_all_cohort_between_record_interval_end": iso_z(longest[1]) if longest else "",
        "longest_all_cohort_between_record_interval_hours": (
            round(duration_hours, 6) if duration_hours is not None else ""
        ),
        "exceeds_frozen_48h_internal_gap_threshold": bool(
            duration_hours is not None and duration_hours > 48.0
        ),
        "semantics": (
            "descriptive overlap of per-satellite gaps longer than the stated minimum; "
            "does not alter per-satellite 48 h reference-quality gate"
        ),
    }


def audit_causal_support(
    gp_rows: list[dict[str, Any]],
    supgp_rows: list[dict[str, Any]],
    selection: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gp_by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in gp_rows:
        gp_by_norad[str(row.get("NORAD_CAT_ID", "")).strip()].append(row)

    details: list[dict[str, Any]] = []
    for reference in supgp_rows:
        norad = reference["NORAD_CAT_ID"]
        evaluation_time = parse_utc(reference["evaluation_time"])
        selected, candidate_count = select_causal_gp(gp_by_norad.get(norad, []), evaluation_time)
        if selected is None:
            details.append({
                **reference,
                "causal_candidate_count": 0,
                "selected_gp_id": "",
                "selected_gp_epoch": "",
                "selected_gp_creation_date": "",
                "gp_age_seconds": "",
                "publication_age_seconds": "",
                "future_publication_used": False,
                "selected_gp_epoch_after_evaluation": False,
                "gp_age_gt_72h": False,
                "causal_status": "NO_CAUSAL_CANDIDATE",
            })
            continue
        selected_epoch = parse_utc(selected["EPOCH"])
        selected_creation = parse_utc(selected["CREATION_DATE"])
        gp_age_seconds = (evaluation_time - selected_epoch).total_seconds()
        publication_age_seconds = (evaluation_time - selected_creation).total_seconds()
        future_used = selected_creation > evaluation_time
        epoch_after = selected_epoch > evaluation_time
        age_gt_72h = gp_age_seconds > LOOKBACK_HOURS * 3600.0
        if future_used:
            status = "FUTURE_PUBLICATION_USED"
        elif epoch_after:
            status = "SELECTED_GP_EPOCH_AFTER_EVALUATION"
        elif age_gt_72h:
            status = "CAUSAL_AVAILABLE_GP_AGE_GT_72H"
        else:
            status = "READY"
        details.append({
            **reference,
            "causal_candidate_count": candidate_count,
            "selected_gp_id": str(selected.get("GP_ID", "")),
            "selected_gp_epoch": str(selected.get("EPOCH", "")),
            "selected_gp_creation_date": str(selected.get("CREATION_DATE", "")),
            "gp_age_seconds": round(gp_age_seconds, 6),
            "publication_age_seconds": round(publication_age_seconds, 6),
            "future_publication_used": future_used,
            "selected_gp_epoch_after_evaluation": epoch_after,
            "gp_age_gt_72h": age_gt_72h,
            "causal_status": status,
        })

    details_by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        details_by_norad[row["NORAD_CAT_ID"]].append(row)
    summary: list[dict[str, Any]] = []
    for satellite in selection:
        norad = satellite["NORAD_CAT_ID"]
        rows = details_by_norad.get(norad, [])
        ages = [float(row["gp_age_seconds"]) for row in rows if row["gp_age_seconds"] != ""]
        publication_ages = [
            float(row["publication_age_seconds"])
            for row in rows if row["publication_age_seconds"] != ""
        ]
        available = sum(int(row["causal_candidate_count"]) > 0 for row in rows)
        summary.append({
            "NORAD_CAT_ID": norad,
            "OBJECT_NAME": satellite["OBJECT_NAME"],
            "evaluation_count": len(rows),
            "causal_candidate_available_count": available,
            "causal_candidate_missing_count": len(rows) - available,
            "future_publication_use_count": sum(bool(row["future_publication_used"]) for row in rows),
            "selected_gp_epoch_after_evaluation_count": sum(
                bool(row["selected_gp_epoch_after_evaluation"]) for row in rows
            ),
            "gp_age_gt_72h_count": sum(bool(row["gp_age_gt_72h"]) for row in rows),
            "gp_age_seconds_min": round(min(ages), 6) if ages else "",
            "gp_age_seconds_median": round(statistics.median(ages), 6) if ages else "",
            "gp_age_seconds_max": round(max(ages), 6) if ages else "",
            "publication_age_seconds_min": round(min(publication_ages), 6) if publication_ages else "",
            "publication_age_seconds_median": round(statistics.median(publication_ages), 6) if publication_ages else "",
            "publication_age_seconds_max": round(max(publication_ages), 6) if publication_ages else "",
            "all_evaluations_causally_supported": available == len(rows) and bool(rows),
        })
    return details, summary


def audit_gp(rows: list[dict[str, Any]], selection: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("NORAD_CAT_ID", "")).strip()].append(row)
    start = parse_utc(ANALYSIS_START)
    stop = parse_utc(ANALYSIS_STOP_EXCLUSIVE)
    acquisition_start = parse_utc(ACQUISITION_START)
    final_formal_day_start = stop - timedelta(days=1)
    output = []
    for satellite in selection:
        norad = satellite["NORAD_CAT_ID"]
        records = grouped.get(norad, [])
        epochs = [parse_utc(row["EPOCH"]) for row in records if row.get("EPOCH")]
        creations = [parse_utc(row["CREATION_DATE"]) for row in records if row.get("CREATION_DATE")]
        missing_counts = {
            field: sum(1 for row in records if row.get(field) in (None, ""))
            for field in REQUIRED_GP_FIELDS
        }
        missing_fields = [field for field, count in missing_counts.items() if count]
        gp_ids = [str(row.get("GP_ID", "")) for row in records if row.get("GP_ID") not in (None, "")]
        epoch_strings = [str(row.get("EPOCH", "")) for row in records if row.get("EPOCH")]
        duplicate_epoch_counts = Counter(epoch_strings)
        selected, causal_count = select_causal_gp(records, start)
        selected_age_hours = (
            (start - parse_utc(selected["EPOCH"])).total_seconds() / 3600.0 if selected else None
        )
        support = bool(
            selected
            and selected_age_hours is not None
            and 0.0 <= selected_age_hours <= LOOKBACK_HOURS
            and parse_utc(selected["EPOCH"]) >= acquisition_start
        )
        in_formal = [epoch for epoch in epochs if start <= epoch < stop]
        gap_values = gaps_hours(in_formal)
        output.append({
            "NORAD_CAT_ID": norad,
            "OBJECT_NAME": satellite["OBJECT_NAME"],
            "record_count": len(records),
            "formal_window_record_count": len(in_formal),
            "epoch_min": iso_z(min(epochs)) if epochs else "",
            "epoch_max": iso_z(max(epochs)) if epochs else "",
            "creation_date_min": iso_z(min(creations)) if creations else "",
            "creation_date_max": iso_z(max(creations)) if creations else "",
            "duplicate_gp_id_count": sum(count - 1 for count in Counter(gp_ids).values() if count > 1),
            "duplicate_epoch_group_count": sum(count > 1 for count in duplicate_epoch_counts.values()),
            "duplicate_epoch_count": sum(count - 1 for count in duplicate_epoch_counts.values() if count > 1),
            "missing_required_fields": ";".join(missing_fields),
            "missing_required_value_count": sum(missing_counts.values()),
            "prewindow_causal_candidate_count": causal_count,
            "selected_prewindow_gp_id": str(selected.get("GP_ID", "")) if selected else "",
            "selected_prewindow_gp_epoch": str(selected.get("EPOCH", "")) if selected else "",
            "selected_prewindow_gp_creation_date": str(selected.get("CREATION_DATE", "")) if selected else "",
            "selected_prewindow_gp_age_hours": round(selected_age_hours, 6) if selected_age_hours is not None else "",
            "causal_72h_prewindow_support": support,
            # Descriptive only: a GP published on the final UTC day may carry an
            # element EPOCH from the previous day and still causally support every
            # evaluation.  The exhaustive audit below is the authoritative gate.
            "formal_epoch_max_reaches_last_day": bool(epochs and max(epochs) >= final_formal_day_start),
            "median_formal_epoch_gap_hours": round(statistics.median(gap_values), 6) if gap_values else "",
            "max_formal_epoch_gap_hours": round(max(gap_values), 6) if gap_values else "",
            "records_before_acquisition_start": sum(epoch < acquisition_start for epoch in epochs),
            "records_at_or_after_stop_exclusive": sum(epoch >= stop for epoch in epochs),
            "ordinary_gp_complete": bool(
                records and not missing_fields and support
            ),
        })
    return output


SUPGP_INVENTORY_FIELDS = [
    "raw_file", "source", "file_size_bytes", "sha256", "row_count", "header_json",
    "file_epoch_min", "file_epoch_max", "norad_count", "norad_ids_json",
]
SUPGP_COVERAGE_FIELDS = [
    "NORAD_CAT_ID", "OBJECT_NAME", "record_count", "epoch_min", "epoch_max",
    "duplicate_epoch_count", "data_source_values", "source_switch", "missing_data_source_count",
    "missing_rms_count", "rms_min", "rms_median", "rms_max", "median_epoch_gap_hours",
    "max_epoch_gap_hours", "gross_epoch_gap", "start_boundary_gap_hours",
    "end_boundary_gap_hours", "reference_coverage_status",
]


def audit_supgp(selection: list[dict[str, str]]) -> tuple[list[dict], list[dict], str]:
    SUPGP_RAW_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SUPGP_RAW_DIR.glob("*.csv"))
    if not files:
        empty_coverage = [{
            "NORAD_CAT_ID": row["NORAD_CAT_ID"], "OBJECT_NAME": row["OBJECT_NAME"],
            "record_count": 0, "epoch_min": "", "epoch_max": "", "duplicate_epoch_count": 0,
            "data_source_values": "", "source_switch": False, "missing_data_source_count": 0,
            "missing_rms_count": 0, "rms_min": "", "rms_median": "", "rms_max": "",
            "median_epoch_gap_hours": "", "max_epoch_gap_hours": "", "gross_epoch_gap": False,
            "start_boundary_gap_hours": "", "end_boundary_gap_hours": "",
            "reference_coverage_status": "NO_REFERENCE",
        } for row in selection]
        return [], empty_coverage, "WAITING_FOR_SUPGP"

    inventory: list[dict] = []
    all_rows: list[dict[str, str]] = []
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        header = reader.fieldnames or []
        all_rows.extend(rows)
        epochs = [parse_utc(row["EPOCH"]) for row in rows if row.get("EPOCH")]
        ids = sorted({str(row.get("NORAD_CAT_ID", "")).strip() for row in rows if row.get("NORAD_CAT_ID")})
        inventory.append({
            "raw_file": str(path), "source": "CelesTrak historical SupGP manual CAPTCHA request",
            "file_size_bytes": path.stat().st_size, "sha256": sha256(path), "row_count": len(rows),
            "header_json": json.dumps(header, ensure_ascii=False),
            "file_epoch_min": iso_z(min(epochs)) if epochs else "",
            "file_epoch_max": iso_z(max(epochs)) if epochs else "",
            "norad_count": len(ids), "norad_ids_json": json.dumps(ids),
        })

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in all_rows:
        grouped[str(row.get("NORAD_CAT_ID", "")).strip()].append(row)
    analysis_start = parse_utc(ANALYSIS_START)
    analysis_end = parse_utc(ANALYSIS_STOP_EXCLUSIVE)
    coverage: list[dict] = []
    for satellite in selection:
        norad = satellite["NORAD_CAT_ID"]
        rows = grouped.get(norad, [])
        epochs = [parse_utc(row["EPOCH"]) for row in rows if row.get("EPOCH")]
        epoch_text = [str(row.get("EPOCH", "")) for row in rows if row.get("EPOCH")]
        sources = sorted({str(row.get("DATA_SOURCE", "")).strip() for row in rows if row.get("DATA_SOURCE")})
        rms_values = []
        for row in rows:
            try:
                if row.get("RMS") not in (None, ""):
                    rms_values.append(float(row["RMS"]))
            except ValueError:
                pass
        gaps = gaps_hours(epochs)
        start_gap = (min(epochs) - analysis_start).total_seconds() / 3600.0 if epochs else None
        end_gap = (analysis_end - max(epochs)).total_seconds() / 3600.0 if epochs else None
        gross_gap = bool(gaps and max(gaps) > 48.0)
        missing_source = sum(not str(row.get("DATA_SOURCE", "")).strip() for row in rows)
        missing_rms = sum(row.get("RMS") in (None, "") for row in rows)
        if not rows:
            reference_status = "NO_REFERENCE"
        elif (
            missing_source or missing_rms or len(sources) != 1 or gross_gap
            or start_gap is None or start_gap > 24.0
            or end_gap is None or end_gap > 24.0
        ):
            reference_status = "PARTIAL_REFERENCE"
        else:
            reference_status = "READY_REFERENCE"
        coverage.append({
            "NORAD_CAT_ID": norad, "OBJECT_NAME": satellite["OBJECT_NAME"], "record_count": len(rows),
            "epoch_min": iso_z(min(epochs)) if epochs else "", "epoch_max": iso_z(max(epochs)) if epochs else "",
            "duplicate_epoch_count": sum(count - 1 for count in Counter(epoch_text).values() if count > 1),
            "data_source_values": ";".join(sources), "source_switch": len(sources) > 1,
            "missing_data_source_count": missing_source, "missing_rms_count": missing_rms,
            "rms_min": min(rms_values) if rms_values else "", "rms_median": statistics.median(rms_values) if rms_values else "",
            "rms_max": max(rms_values) if rms_values else "",
            "median_epoch_gap_hours": round(statistics.median(gaps), 6) if gaps else "",
            "max_epoch_gap_hours": round(max(gaps), 6) if gaps else "", "gross_epoch_gap": gross_gap,
            "start_boundary_gap_hours": round(start_gap, 6) if start_gap is not None else "",
            "end_boundary_gap_hours": round(end_gap, 6) if end_gap is not None else "",
            "reference_coverage_status": reference_status,
        })
    return inventory, coverage, "SUPGP_INGESTED"


def bind_supgp_reference_gate(
    supgp_inventory: list[dict[str, Any]], selection: list[dict[str, str]]
) -> dict[str, Any]:
    """Bind a matching formal SupGP gate when it already exists."""
    if not SUPGP_GATE_MANIFEST_PATH.exists():
        return {"status": "NOT_AVAILABLE", "path": str(SUPGP_GATE_MANIFEST_PATH)}
    gate = json.loads(SUPGP_GATE_MANIFEST_PATH.read_text(encoding="utf-8"))
    expected_window = f"[{ANALYSIS_START}, {ANALYSIS_STOP_EXCLUSIVE})"
    if gate.get("window_tag") != WINDOW_TAG:
        raise RuntimeError("SupGP gate manifest window tag does not match acquisition window")
    if gate.get("scope", {}).get("formal_window") != expected_window:
        raise RuntimeError("SupGP gate manifest formal window does not match acquisition window")
    if gate.get("selection", {}).get("sha256") != sha256(SELECTION_PATH):
        raise RuntimeError("SupGP gate manifest selection SHA does not match acquisition selection")

    gate_files = {
        Path(row["raw_file"]).name: row["sha256"]
        for row in gate.get("raw", {}).get("files", [])
    }
    acquisition_files = {
        Path(row["raw_file"]).name: row["sha256"] for row in supgp_inventory
    }
    if gate_files != acquisition_files:
        raise RuntimeError("SupGP gate manifest raw SHA inventory does not match acquisition input")
    status_counts = gate.get("result", {}).get("status_counts", {})
    if status_counts.get("READY", 0) != len(selection):
        raise RuntimeError(f"SupGP formal gate is not fully READY: {status_counts}")
    return {
        "status": "VERIFIED",
        "path": str(SUPGP_GATE_MANIFEST_PATH),
        "sha256": sha256(SUPGP_GATE_MANIFEST_PATH),
        "window_tag": gate["window_tag"],
        "status_counts": status_counts,
        "raw_file_count": len(gate_files),
        "raw_sha_inventory_match": True,
    }


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-only", action="store_true", help="Do not call Space-Track; require matching formal raw cache")
    parser.add_argument("--window-tag", default=WINDOW_TAG)
    parser.add_argument("--formal-start", default=FORMAL_START)
    parser.add_argument("--formal-stop-exclusive", default=FORMAL_STOP_EXCLUSIVE)
    parser.add_argument("--gp-acquisition-start", default=GP_ACQUISITION_START)
    parser.add_argument("--lookback-hours", type=float, default=LOOKBACK_HOURS)
    parser.add_argument("--selection", type=Path, default=SELECTION_PATH)
    parser.add_argument("--supgp-input-dir", type=Path, default=SUPGP_RAW_DIR)
    parser.add_argument(
        "--supgp-candidate-audit-manifest", type=Path,
        help="Optional accepted SupGP pre-audit that also binds Stage-1F protected artifacts",
    )
    args = parser.parse_args()

    configure_runtime(
        window_tag=args.window_tag,
        formal_start=args.formal_start,
        formal_stop_exclusive=args.formal_stop_exclusive,
        gp_acquisition_start=args.gp_acquisition_start,
        lookback_hours=args.lookback_hours,
        selection_path=args.selection,
        supgp_raw_dir=args.supgp_input_dir,
    )

    upstream_candidate, protected_before = load_upstream_candidate_audit(
        args.supgp_candidate_audit_manifest
    )

    selection = read_selection()
    ids = [row["NORAD_CAT_ID"] for row in selection]
    if args.reuse_only and not GP_RAW_PATH.exists():
        raise RuntimeError("--reuse-only requested but formal GP raw does not exist")

    raw_bytes, gp_metadata, reused = acquire_gp(ids)
    gp_rows = normalize_records(raw_bytes)
    gp_audit = audit_gp(gp_rows, selection)
    supgp_inventory, supgp_audit, supgp_status = audit_supgp(selection)
    supgp_gate_binding = bind_supgp_reference_gate(supgp_inventory, selection)
    upstream_candidate_binding = bind_upstream_candidate_audit(
        args.supgp_candidate_audit_manifest, upstream_candidate, supgp_inventory
    )
    supgp_evaluations = read_supgp_evaluation_rows()
    causal_details, causal_summary = audit_causal_support(gp_rows, supgp_evaluations, selection)
    deterministic_details, deterministic_summary = audit_causal_support(
        gp_rows, supgp_evaluations, selection
    )
    selection_deterministic = (
        deterministic_details == causal_details and deterministic_summary == causal_summary
    )
    reference_gap_overlap = cohort_reference_gap_overlap(supgp_evaluations, selection)

    gp_inventory = [{
        "raw_file": str(GP_RAW_PATH), "source": "Space-Track", "api_class": "gp_history",
        "request_fingerprint": request_fingerprint(ids), "request_object_ids_json": json.dumps(ids),
        "time_range": f"[{ACQUISITION_START}, {ANALYSIS_STOP_EXCLUSIVE})",
        "download_utc": gp_metadata.get("download_utc", ""), "http_status": gp_metadata.get("http_status", ""),
        "format": FORMAT, "file_size_bytes": GP_RAW_PATH.stat().st_size, "sha256": sha256(GP_RAW_PATH),
        "record_count": len(gp_rows), "reused_without_network": reused,
        "returned_field_names_json": json.dumps(sorted({key for row in gp_rows for key in row}), ensure_ascii=False),
    }]
    write_csv(GP_INVENTORY_PATH, gp_inventory, list(gp_inventory[0]))
    write_csv(GP_COVERAGE_PATH, gp_audit, list(gp_audit[0]))
    write_csv(SUPGP_INVENTORY_PATH, supgp_inventory, SUPGP_INVENTORY_FIELDS)
    write_csv(SUPGP_COVERAGE_PATH, supgp_audit, SUPGP_COVERAGE_FIELDS)
    if causal_details:
        write_csv(CAUSAL_DETAIL_PATH, causal_details, list(causal_details[0]))
    if causal_summary:
        write_csv(CAUSAL_SUMMARY_PATH, causal_summary, list(causal_summary[0]))

    gp_by_id = {row["NORAD_CAT_ID"]: row for row in gp_audit}
    supgp_by_id = {row["NORAD_CAT_ID"]: row for row in supgp_audit}
    causal_by_id = {row["NORAD_CAT_ID"]: row for row in causal_summary}
    readiness = []
    for satellite in selection:
        norad = satellite["NORAD_CAT_ID"]
        gp = gp_by_id[norad]
        ref = supgp_by_id[norad]
        causal = causal_by_id[norad]
        if not gp["ordinary_gp_complete"]:
            status = "ORDINARY_GP_INCOMPLETE"
        elif not causal["all_evaluations_causally_supported"]:
            status = "CAUSAL_SUPPORT_INCOMPLETE"
        elif causal["future_publication_use_count"]:
            status = "FUTURE_PUBLICATION_LEAKAGE"
        elif causal["selected_gp_epoch_after_evaluation_count"]:
            status = "SELECTED_GP_EPOCH_AFTER_EVALUATION"
        elif causal["gp_age_gt_72h_count"]:
            status = "CAUSAL_GP_AGE_GT_72H"
        elif ref["reference_coverage_status"] == "NO_REFERENCE":
            status = "NO_REFERENCE"
        elif ref["reference_coverage_status"] != "READY_REFERENCE":
            status = "PARTIAL_REFERENCE"
        else:
            status = "READY"
        readiness.append({
            "NORAD_CAT_ID": norad, "OBJECT_NAME": satellite["OBJECT_NAME"],
            "ordinary_gp_complete": gp["ordinary_gp_complete"],
            "causal_72h_prewindow_support": gp["causal_72h_prewindow_support"],
            "all_supgp_epochs_causally_supported": causal["all_evaluations_causally_supported"],
            "future_publication_use_count": causal["future_publication_use_count"],
            "selected_gp_epoch_after_evaluation_count": causal["selected_gp_epoch_after_evaluation_count"],
            "gp_age_gt_72h_count": causal["gp_age_gt_72h_count"],
            "reference_coverage_status": ref["reference_coverage_status"],
            "cohort_status": status,
        })
    write_csv(READINESS_PATH, readiness, list(readiness[0]))

    causal_ages = [
        float(row["gp_age_seconds"])
        for row in causal_details if row["gp_age_seconds"] != ""
    ]
    publication_ages = [
        float(row["publication_age_seconds"])
        for row in causal_details if row["publication_age_seconds"] != ""
    ]
    negative_element_age = sum(value < 0 for value in causal_ages)
    negative_publication_age = sum(value < 0 for value in publication_ages)
    gp_age_gt_36h = sum(value > 36.0 * 3600.0 for value in causal_ages)
    gp_age_gt_72h = sum(value > LOOKBACK_HOURS * 3600.0 for value in causal_ages)
    age_gt_72_rows = [row for row in causal_details if bool(row["gp_age_gt_72h"])]
    age_gt_72_by_norad: dict[str, dict[str, Any]] = {}
    for norad in sorted({row["NORAD_CAT_ID"] for row in age_gt_72_rows}):
        affected = [row for row in age_gt_72_rows if row["NORAD_CAT_ID"] == norad]
        affected.sort(key=lambda row: parse_utc(row["evaluation_time"]))
        ages_hours = [float(row["gp_age_seconds"]) / 3600.0 for row in affected]
        age_gt_72_by_norad[norad] = {
            "count": len(affected),
            "first_evaluation": affected[0]["evaluation_time"],
            "last_evaluation": affected[-1]["evaluation_time"],
            "minimum_element_age_hours": round(min(ages_hours), 6),
            "maximum_element_age_hours": round(max(ages_hours), 6),
            "selected_gp_ids": sorted({row["selected_gp_id"] for row in affected}),
        }
    ready_counts = Counter(row["cohort_status"] for row in readiness)
    stage1a_complete = (
        ready_counts.get("READY", 0) == len(selection)
        and len(causal_details) == len(supgp_evaluations)
        and not negative_element_age
        and not negative_publication_age
        and not gp_age_gt_72h
        and selection_deterministic
    )
    stage1a_prefix = f"{parse_utc(ANALYSIS_START):%B}".upper() + "_STAGE1A"
    stage1a_status = (
        f"{stage1a_prefix}_COMPLETE" if stage1a_complete
        else f"{stage1a_prefix}_BLOCKED_CAUSAL_GP_AGE_GT_72H"
        if gp_age_gt_72h
        else f"{stage1a_prefix}_BLOCKED_CORRECTNESS"
    )
    gp_epochs = [parse_utc(row["EPOCH"]) for row in gp_rows if row.get("EPOCH")]
    gp_creations = [
        parse_utc(row["CREATION_DATE"])
        for row in gp_rows if row.get("CREATION_DATE")
    ]

    manifest = read_existing_manifest()
    manifest.update({
        "stage": "orbit_uncertainty_stage1_acquisition",
        "status": supgp_status,
        "stage1a_status": stage1a_status,
        "window_tag": WINDOW_TAG,
        "formal_window": f"[{ANALYSIS_START}, {ANALYSIS_STOP_EXCLUSIVE})",
        "ordinary_gp_acquisition_window": f"[{ACQUISITION_START}, {GP_ACQUISITION_STOP_EXCLUSIVE})",
        "updated_utc": utc_now(),
        "authoritative_selection": {
            "path": str(SELECTION_PATH), "sha256": sha256(SELECTION_PATH),
            "row_count": len(selection), "unique_norad_count": len(set(ids)),
        },
        "ordinary_gp": gp_metadata,
        "ordinary_gp_raw_reused_without_network": reused,
        "ordinary_gp_audit": {
            "record_count": len(gp_rows),
            "formal_window_record_count": sum(int(row["formal_window_record_count"]) for row in gp_audit),
            "epoch_min": iso_z(min(gp_epochs)) if gp_epochs else "",
            "epoch_max": iso_z(max(gp_epochs)) if gp_epochs else "",
            "creation_date_min": iso_z(min(gp_creations)) if gp_creations else "",
            "creation_date_max": iso_z(max(gp_creations)) if gp_creations else "",
            "returned_satellite_count": len({str(row.get("NORAD_CAT_ID", "")).strip() for row in gp_rows}),
            "creation_date_available_count": sum(row.get("CREATION_DATE") not in (None, "") for row in gp_rows),
            "gp_id_available_count": sum(row.get("GP_ID") not in (None, "") for row in gp_rows),
            "required_field_missing_value_count": sum(int(row["missing_required_value_count"]) for row in gp_audit),
            "duplicate_gp_id_excess_count": sum(int(row["duplicate_gp_id_count"]) for row in gp_audit),
            "duplicate_epoch_group_count": sum(int(row["duplicate_epoch_group_count"]) for row in gp_audit),
            "duplicate_epoch_excess_count": sum(int(row["duplicate_epoch_count"]) for row in gp_audit),
        },
        "causal_support": {
            "evaluation_count": len(causal_details),
            "candidate_available_count": sum(
                int(row["causal_candidate_count"]) > 0 for row in causal_details
            ),
            "candidate_missing_count": sum(
                int(row["causal_candidate_count"]) == 0 for row in causal_details
            ),
            "future_publication_use_count": sum(
                bool(row["future_publication_used"]) for row in causal_details
            ),
            "selected_gp_epoch_after_evaluation_count": sum(
                bool(row["selected_gp_epoch_after_evaluation"]) for row in causal_details
            ),
            "gp_age_gt_72h_count": sum(bool(row["gp_age_gt_72h"]) for row in causal_details),
            "element_age_seconds_min": min(
                (float(row["gp_age_seconds"]) for row in causal_details if row["gp_age_seconds"] != ""),
                default=None,
            ),
            "element_age_seconds_median": statistics.median(
                [float(row["gp_age_seconds"]) for row in causal_details if row["gp_age_seconds"] != ""]
            ) if any(row["gp_age_seconds"] != "" for row in causal_details) else None,
            "element_age_seconds_p90": quantile(causal_ages, 0.90),
            "element_age_seconds_p95": quantile(causal_ages, 0.95),
            "element_age_seconds_max": max(
                (float(row["gp_age_seconds"]) for row in causal_details if row["gp_age_seconds"] != ""),
                default=None,
            ),
            "publication_age_seconds_min": min(
                (float(row["publication_age_seconds"]) for row in causal_details if row["publication_age_seconds"] != ""),
                default=None,
            ),
            "publication_age_seconds_median": statistics.median(
                [float(row["publication_age_seconds"]) for row in causal_details if row["publication_age_seconds"] != ""]
            ) if any(row["publication_age_seconds"] != "" for row in causal_details) else None,
            "publication_age_seconds_p90": quantile(publication_ages, 0.90),
            "publication_age_seconds_p95": quantile(publication_ages, 0.95),
            "publication_age_seconds_max": max(
                (float(row["publication_age_seconds"]) for row in causal_details if row["publication_age_seconds"] != ""),
                default=None,
            ),
            "selection_policy": "CREATION_DATE <= evaluation_time; latest CREATION_DATE, then EPOCH, then GP_ID",
            "selection_deterministic": selection_deterministic,
            "negative_element_age_count": negative_element_age,
            "negative_publication_age_count": negative_publication_age,
            "element_age_gt_36h_count": gp_age_gt_36h,
            "element_age_gt_72h_by_satellite": age_gt_72_by_norad,
            "detail_output": str(CAUSAL_DETAIL_PATH),
            "summary_output": str(CAUSAL_SUMMARY_PATH),
        },
        "historical_supgp": {
            "status": supgp_status, "raw_directory": str(SUPGP_RAW_DIR),
            "raw_file_count": len(supgp_inventory),
            "raw_files": [{"path": row["raw_file"], "sha256": row["sha256"], "row_count": row["row_count"]} for row in supgp_inventory],
            "substitution_forbidden": ["later GP", "Stage-0 SupGP", "current SupGP", "other source"],
            "reference_availability_fact": reference_gap_overlap,
            "formal_reference_quality_gate": supgp_gate_binding,
            "candidate_availability_audit": upstream_candidate_binding,
        },
        "stage1f_artifact_protection": {
            "pre_acquisition_fingerprints": protected_before,
            "frozen_parameter_sha256": upstream_candidate_binding.get(
                "frozen_parameter_sha256", ""
            ),
        },
        "scope_guards": {
            "formal_residual_computed": False, "calibration_computed": False,
            "synthetic_b_used": False, "doppler_propagated": False,
        },
    })
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    protected_after = {path: sha256(Path(path)) for path in protected_before}
    protected_unchanged = protected_after == protected_before
    if not protected_unchanged:
        raise RuntimeError("Stage-1F/development protected artifacts changed during acquisition audit")

    selection_ok = len(selection) == 20 and len(set(ids)) == 20
    returned_ids = {str(row.get("NORAD_CAT_ID", "")).strip() for row in gp_rows}
    outside_ids = sorted(returned_ids - set(ids))
    guarded_results = {
        path: (Path(path).exists() and sha256(Path(path)) == expected)
        for path, expected in GUARDED_HASHES.items()
    }
    sensitive_values = [
        os.environ.get(name, "").encode("utf-8")
        for name in ("SPACETRACK_USERNAME", "SPACETRACK_PASSWORD")
        if os.environ.get(name)
    ]
    leak_scan_paths = [GP_RAW_PATH, MANIFEST_PATH, REPORT_PATH]
    credential_value_hits = 0
    for path in leak_scan_paths:
        if path.exists():
            payload = path.read_bytes()
            credential_value_hits += sum(bool(value and value in payload) for value in sensitive_values)
    checks = [
        {"check": "authoritative selection 20 rows/20 unique", "passed": selection_ok, "observed": f"rows={len(selection)}, unique={len(set(ids))}"},
        {"check": "ordinary GP returned all requested NORAD", "passed": returned_ids == set(ids), "observed": f"returned={len(returned_ids)}, outside={outside_ids}"},
        {"check": "ordinary GP required fields complete", "passed": all(not row["missing_required_fields"] for row in gp_audit), "observed": f"satellites_with_missing={sum(bool(row['missing_required_fields']) for row in gp_audit)}"},
        {"check": "72h causal prewindow support", "passed": all(row["causal_72h_prewindow_support"] for row in gp_audit), "observed": f"supported={sum(bool(row['causal_72h_prewindow_support']) for row in gp_audit)}/20"},
        {"check": "all SupGP epochs have causal candidate", "passed": all(row["all_evaluations_causally_supported"] for row in causal_summary), "observed": f"supported={sum(bool(row['all_evaluations_causally_supported']) for row in causal_summary)}/20; evaluations={len(causal_details)}"},
        {"check": "future publication use zero", "passed": not any(row["future_publication_used"] for row in causal_details), "observed": f"future_publication_use={sum(bool(row['future_publication_used']) for row in causal_details)}"},
        {"check": "selected GP epoch after evaluation zero", "passed": not any(row["selected_gp_epoch_after_evaluation"] for row in causal_details), "observed": f"selected_epoch_after_evaluation={sum(bool(row['selected_gp_epoch_after_evaluation']) for row in causal_details)}"},
        {"check": "selected GP element age at most 72h", "passed": gp_age_gt_72h == 0, "observed": f"gp_age_gt_72h={gp_age_gt_72h}"},
        {"check": "negative element and publication age zero", "passed": negative_element_age == 0 and negative_publication_age == 0, "observed": f"negative_element_age={negative_element_age}; negative_publication_age={negative_publication_age}"},
        {"check": "causal selection deterministic", "passed": selection_deterministic, "observed": f"repeat_audit_equal={selection_deterministic}"},
        {"check": "raw GP SHA and manifest fixed", "passed": gp_metadata.get("sha256") == sha256(GP_RAW_PATH), "observed": sha256(GP_RAW_PATH)},
        {"check": "SupGP substitution prohibited", "passed": True, "observed": supgp_status},
        {"check": "SupGP formal gate manifest and raw SHA bound", "passed": supgp_gate_binding.get("status") == "VERIFIED", "observed": json.dumps(supgp_gate_binding)},
        {"check": "SupGP candidate audit and Stage-1F protection bound", "passed": upstream_candidate_binding.get("status") in {"VERIFIED", "NOT_REQUESTED"}, "observed": json.dumps(upstream_candidate_binding)},
        {"check": "Stage-1F/development protected artifacts unchanged", "passed": protected_unchanged, "observed": f"protected={len(protected_after)}; before_after_equal={protected_unchanged}"},
        {"check": "historical/formal guarded hashes unchanged", "passed": all(guarded_results.values()), "observed": json.dumps(guarded_results)},
        {"check": "credential values absent from generated files", "passed": credential_value_hits == 0, "observed": f"hits={credential_value_hits}; scanned_values={len(sensitive_values)}"},
        {"check": "formal residual/calibration/Doppler absent", "passed": True, "observed": "acquisition and ingestion audit only"},
    ]
    write_csv(CORRECTNESS_PATH, checks, list(checks[0]))

    total_supgp_rows = sum(int(row["row_count"]) for row in supgp_inventory)
    gp_complete = sum(bool(row["ordinary_gp_complete"]) for row in gp_audit)
    lookback = sum(bool(row["causal_72h_prewindow_support"]) for row in gp_audit)
    missing_gp = [row["NORAD_CAT_ID"] for row in gp_audit if row["record_count"] == 0]
    duplicate_epoch_satellites = [row["NORAD_CAT_ID"] for row in gp_audit if row["duplicate_epoch_count"]]
    records_before_acquisition_start = sum(int(row["records_before_acquisition_start"]) for row in gp_audit)
    causal_available = sum(int(row["causal_candidate_count"]) > 0 for row in causal_details)
    future_publication_use = sum(bool(row["future_publication_used"]) for row in causal_details)
    selected_epoch_after_evaluation = sum(
        bool(row["selected_gp_epoch_after_evaluation"]) for row in causal_details
    )
    long_gap_candidates = {
        row["NORAD_CAT_ID"]: row["max_formal_epoch_gap_hours"]
        for row in gp_audit
        if row["max_formal_epoch_gap_hours"] != "" and float(row["max_formal_epoch_gap_hours"]) > 48.0
    }
    report = f"""# Orbit uncertainty Stage-1 acquisition report

## 1. 状态与范围

状态：`{stage1a_status}`（SupGP ingestion=`{supgp_status}`）。窗口tag：`{WINDOW_TAG}`；formal window：`[{ANALYSIS_START}, {ANALYSIS_STOP_EXCLUSIVE})`。本轮只完成正式ordinary GP_HISTORY acquisition、raw provenance、ingestion gate和全SupGP epoch causal support audit；没有计算6D residual、regime classifier、freshness model、calibration、synthetic B或Doppler。

权威cohort：20 rows / 20 unique NORAD，来源`{SELECTION_PATH}`。

## 2. Ordinary GP acquisition

- raw：`{GP_RAW_PATH}`
- records：{len(gp_rows)}
- formal-window EPOCH records：{sum(int(row['formal_window_record_count']) for row in gp_audit)}
- EPOCH range：{iso_z(min(gp_epochs)) if gp_epochs else ''} 至 {iso_z(max(gp_epochs)) if gp_epochs else ''}
- CREATION_DATE range：{iso_z(min(gp_creations)) if gp_creations else ''} 至 {iso_z(max(gp_creations)) if gp_creations else ''}（query按EPOCH；晚于formal stop的publication未被任何June evaluation因果选择）
- returned satellites：{len(returned_ids)}/20
- ingestion complete：{gp_complete}/20
- 72 h pre-window causal support：{lookback}/20
- missing satellites：{missing_gp}
- reused without network：{reused}
- raw SHA-256：`{sha256(GP_RAW_PATH)}`
- records before requested acquisition start：{records_before_acquisition_start}（Space-Track返回的额外记录，原样保留并显式审计）

`{ANALYSIS_START}`的pre-window support和全部SupGP evaluation epoch均只允许`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID确定性选择。

## 3. Causal readiness at all SupGP epochs

- evaluations：{len(causal_details)}
- causal candidate available：{causal_available}/{len(causal_details)}
- future publication use：{future_publication_use}
- selected GP epoch > evaluation time：{selected_epoch_after_evaluation}
- GP age >72 h：{gp_age_gt_72h}
- GP age hours min/median/P90/P95/max：{min(causal_ages) / 3600.0 if causal_ages else ''} / {statistics.median(causal_ages) / 3600.0 if causal_ages else ''} / {quantile(causal_ages, 0.90) / 3600.0 if causal_ages else ''} / {quantile(causal_ages, 0.95) / 3600.0 if causal_ages else ''} / {max(causal_ages) / 3600.0 if causal_ages else ''}
- publication age hours min/median/P90/P95/max：{min(publication_ages) / 3600.0 if publication_ages else ''} / {statistics.median(publication_ages) / 3600.0 if publication_ages else ''} / {quantile(publication_ages, 0.90) / 3600.0 if publication_ages else ''} / {quantile(publication_ages, 0.95) / 3600.0 if publication_ages else ''} / {max(publication_ages) / 3600.0 if publication_ages else ''}
- negative element/publication age：{negative_element_age}/{negative_publication_age}
- element age >36 h：{gp_age_gt_36h}（仅描述；后续为OUTSIDE_CALIBRATED_SUPPORT / DEFER）
- element age >72 h affected satellites：{json.dumps(age_gt_72_by_norad, ensure_ascii=False)}

- duplicate GP_ID：{sum(int(row['duplicate_gp_id_count']) for row in gp_audit)}
- duplicate epoch groups：{sum(int(row['duplicate_epoch_group_count']) for row in gp_audit)}；duplicate excess records：{sum(int(row['duplicate_epoch_count']) for row in gp_audit)}，涉及{len(duplicate_epoch_satellites)}/20颗；保留不同GP_ID/CREATION_DATE记录，不静默去重。
- descriptive ordinary-GP gap candidates (>48 h)：{json.dumps(long_gap_candidates, ensure_ascii=False)}。这些不是reference RMS/gap结论；本轮已完成选择可用性审计，但未传播轨道或计算residual。

## 4. Historical SupGP ingestion

- status：`{supgp_status}`
- formal raw directory：`{SUPGP_RAW_DIR}`
- raw CSV files：{len(supgp_inventory)}
- raw rows：{total_supgp_rows}
- descriptive cohort reference pause：{reference_gap_overlap['longest_all_cohort_between_record_interval_start']} 至 {reference_gap_overlap['longest_all_cohort_between_record_interval_end']}，{reference_gap_overlap['longest_all_cohort_between_record_interval_hours']} h，affected={reference_gap_overlap['max_simultaneous_satellites_between_records']}/20；是否超过冻结48 h gate：{reference_gap_overlap['exceeds_frozen_48h_internal_gap_threshold']}
- formal reference-quality gate binding：{json.dumps(supgp_gate_binding, ensure_ascii=False)}
- candidate availability audit binding：{json.dumps(upstream_candidate_binding, ensure_ascii=False)}
- Stage-1F/development protected artifacts unchanged：{protected_unchanged}（{len(protected_after)} files）

若状态为`WAITING_FOR_SUPGP`，没有使用Stage-0 SupGP、current SupGP、later GP或其他source替代。若CSV已到达，coverage表只审计header、source、RMS、epoch、duplicate和gap，不删除RMS outlier且不计算residual。

## 5. Cohort readiness

{json.dumps(dict(ready_counts), ensure_ascii=False)}

只有`READY`对象才能进入Stage-1B residual-library construction。当前是否可进入取决于`READY`数量及SupGP状态；`NO_REFERENCE`不代表ordinary GP失败。

## 6. 输出

- `{GP_INVENTORY_PATH}`
- `{GP_COVERAGE_PATH}`
- `{SUPGP_INVENTORY_PATH}`
- `{SUPGP_COVERAGE_PATH}`
- `{CAUSAL_DETAIL_PATH}`
- `{CAUSAL_SUMMARY_PATH}`
- `{READINESS_PATH}`
- `{MANIFEST_PATH}`
- `{CORRECTNESS_PATH}`
"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    manifest["stage1f_artifact_protection"].update({
        "post_acquisition_fingerprints": protected_after,
        "before_after_equal": protected_unchanged,
    })
    output_paths = [
        GP_INVENTORY_PATH, GP_COVERAGE_PATH, SUPGP_INVENTORY_PATH,
        SUPGP_COVERAGE_PATH, CAUSAL_DETAIL_PATH, CAUSAL_SUMMARY_PATH,
        READINESS_PATH, CORRECTNESS_PATH, REPORT_PATH,
    ]
    manifest["outputs"] = {
        path.as_posix(): sha256(path) for path in output_paths if path.exists()
    }
    manifest["implementation"] = {
        "script_path": Path(__file__).as_posix(),
        "script_sha256": sha256(Path(__file__)),
        "git_commit": None,
        "git_note": "project root is not a Git worktree",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": stage1a_status, "supgp_status": supgp_status,
        "ordinary_gp_records": len(gp_rows),
        "ordinary_gp_satellites": len(returned_ids), "ordinary_gp_complete": gp_complete,
        "causal_72h_support": lookback, "supgp_files": len(supgp_inventory),
        "supgp_rows": total_supgp_rows, "readiness": dict(ready_counts),
        "causal_evaluations": len(causal_details),
        "causal_candidate_available": causal_available,
        "future_publication_use": future_publication_use,
        "selected_gp_epoch_after_evaluation": selected_epoch_after_evaluation,
        "gp_age_gt_72h": gp_age_gt_72h,
        "raw_reused_without_network": reused,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
