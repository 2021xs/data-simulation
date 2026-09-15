#!/usr/bin/env python3
"""Build a Stage-1B causal 6D RTN residual library.

The dataset measures ordinary-GP prediction disagreement relative to an
operator-derived higher-quality SupGP reference.  It does not estimate a
ground-truth error, fit an uncertainty boundary, or run any Doppler analysis.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

import astropy
import numpy as np
import pandas as pd
import sgp4
from astropy import units as u
from astropy.coordinates import CartesianDifferential, CartesianRepresentation, GCRS, TEME
from astropy.time import Time
from astropy.utils import iers
from sgp4.api import Satrec

try:
    from scripts.acquire_orbit_uncertainty_stage1 import parse_utc, select_causal_gp
    from scripts.orbit_uncertainty_stage1_window import (
        FORMAL_INTERVAL as DEFAULT_FORMAL_INTERVAL,
        FORMAL_START as DEFAULT_FORMAL_START,
        FORMAL_STOP_EXCLUSIVE as DEFAULT_FORMAL_STOP_EXCLUSIVE,
        LOOKBACK_HOURS,
        WINDOW_TAG as DEFAULT_WINDOW_TAG,
    )
    from scripts.run_orbit_uncertainty_stage0_starlink_smoke import (
        propagate,
        rtn_basis,
        satrec_from_supgp,
        to_gcrs,
    )
except ModuleNotFoundError:
    from acquire_orbit_uncertainty_stage1 import parse_utc, select_causal_gp
    from orbit_uncertainty_stage1_window import (
        FORMAL_INTERVAL as DEFAULT_FORMAL_INTERVAL,
        FORMAL_START as DEFAULT_FORMAL_START,
        FORMAL_STOP_EXCLUSIVE as DEFAULT_FORMAL_STOP_EXCLUSIVE,
        LOOKBACK_HOURS,
        WINDOW_TAG as DEFAULT_WINDOW_TAG,
    )
    from run_orbit_uncertainty_stage0_starlink_smoke import (
        propagate,
        rtn_basis,
        satrec_from_supgp,
        to_gcrs,
    )


WINDOW_TAG = DEFAULT_WINDOW_TAG
FORMAL_START = DEFAULT_FORMAL_START
FORMAL_STOP_EXCLUSIVE = DEFAULT_FORMAL_STOP_EXCLUSIVE
FORMAL_INTERVAL = DEFAULT_FORMAL_INTERVAL

STAGE1_PREFIX = f"orbit_uncertainty_stage1_{WINDOW_TAG}"
STAGE1B_PREFIX = f"orbit_uncertainty_stage1b_{WINDOW_TAG}"

METRICS_DIR = Path("outputs/metrics")
DATASET_DIR = Path("outputs/datasets")
REPORT_DIR = Path("outputs/reports")
RAW_DIR = Path("data/orbit_uncertainty_stage1/raw")
SUPGP_DIR = RAW_DIR / "celestrak_supgp"

DESIGN_MANIFEST = METRICS_DIR / f"{STAGE1_PREFIX}_design_manifest.json"
ACQUISITION_MANIFEST = METRICS_DIR / f"{STAGE1_PREFIX}_acquisition_download_manifest.json"
REFERENCE_MANIFEST = METRICS_DIR / f"{STAGE1_PREFIX}_supgp_reference_quality_manifest.json"
REFERENCE_QUALITY = METRICS_DIR / f"{STAGE1_PREFIX}_supgp_reference_quality.csv"
CAUSAL_AUDIT = METRICS_DIR / f"{STAGE1_PREFIX}_ordinary_gp_causal_support_audit.csv"
COHORT_SELECTION = METRICS_DIR / f"{STAGE1_PREFIX}_satellite_selection.csv"
READINESS_ADJUDICATION_MANIFEST: Path | None = None

DATASET_PATH = DATASET_DIR / f"{STAGE1B_PREFIX}_rtn_residual_library.csv"
SUMMARY_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_residual_summary.csv"
CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_correctness_audit.csv"
FAILURE_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_failure_audit.csv"
MANIFEST_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_manifest.json"
REPORT_PATH = REPORT_DIR / f"{STAGE1B_PREFIX}_report.md"

SMOKE_CROSSCHECK_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_smoke_crosscheck.csv"
SMOKE_CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_smoke_correctness_audit.csv"
SMOKE_MANIFEST_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_smoke_manifest.json"

EXPECTED_FORMAL_ROWS = 5675
APRIL_WINDOW_TAG = "20260401_20260430"
APRIL_DATASET_PATH = DATASET_DIR / "orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv"
APRIL_DATASET_SHA256 = "2B02C40FDEA69F6079D256B5E274652ABAB2D5BC2F9899866C7F1CAFFB469F23"
APRIL_STAGE1B_MANIFEST_PATH = METRICS_DIR / "orbit_uncertainty_stage1b_20260401_20260430_manifest.json"
APRIL_ORDINARY_RAW = RAW_DIR / "spacetrack_gp" / "spacetrack_gp_history_20260329_20260501_20sat_omm.json"
APRIL_SUPGP_DIR = RAW_DIR / "celestrak_supgp"
APRIL_PROTECTED_EXPECTED_COUNT = 81
APRIL_CALIBRATED_FRESHNESS_SECONDS = 36.0 * 3600.0
EXPECTED_STAGE1F_PARAMETER_SHA256 = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
CAUSAL_DATA_READINESS_V2 = "CAUSAL_DATA_READINESS_V2"
NUMERIC_ABS_TOL = 1e-10
NUMERIC_REL_TOL = 1e-12
ORTHONORMAL_TOL = 1e-12

DATASET_FIELDS = [
    "window_tag",
    "NORAD_CAT_ID",
    "object_name",
    "evaluation_time",
    "comparison_semantics",
    "ordinary_gp_id",
    "ordinary_gp_epoch",
    "ordinary_gp_creation_date",
    "gp_age_seconds",
    "element_age_seconds",
    "element_age_hours",
    "publication_age_seconds",
    "publication_age_hours",
    "causal_readiness_protocol",
    "stage1f_support_status",
    "within_stage1f_support",
    "engineering_staleness_gt72h",
    "ordinary_causal_candidate_count",
    "ordinary_selection_rank",
    "ordinary_selection_tie_break",
    "ordinary_raw_file",
    "ordinary_raw_sha256",
    "supgp_epoch",
    "supgp_data_source",
    "supgp_rms_km",
    "supgp_source_file",
    "supgp_source_row_index",
    "supgp_source_file_sha256",
    "supgp_reference_status",
    "native_frame_ordinary",
    "native_frame_supgp",
    "common_frame",
    "time_scale",
    "rtn_basis_source",
    "delta_R_km",
    "delta_T_km",
    "delta_N_km",
    "delta_v_R_km_s",
    "delta_v_T_km_s",
    "delta_v_N_km_s",
    "position_error_norm_km",
    "velocity_error_norm_km_s",
    "delta_x_common_km",
    "delta_y_common_km",
    "delta_z_common_km",
    "delta_vx_common_km_s",
    "delta_vy_common_km_s",
    "delta_vz_common_km_s",
    "rtn_orthonormality_error",
    "rtn_R_unit_norm_error",
    "rtn_T_unit_norm_error",
    "rtn_N_unit_norm_error",
    "rtn_R_dot_T",
    "rtn_R_dot_N",
    "rtn_T_dot_N",
    "rtn_right_handedness_error",
    "position_rtn_reconstruction_abs_error_km",
    "velocity_rtn_reconstruction_abs_error_km_s",
    "cartesian_rtn_position_norm_abs_error_km",
    "cartesian_rtn_velocity_norm_abs_error_km_s",
    "ordinary_sgp4_status",
    "supgp_sgp4_status",
    "frame_transform_status",
    "rtn_status",
    "finite_state_status",
    "nominal_row",
    "exclusion_reason",
    "execution_message",
]

FAILURE_FIELDS = [
    "window_tag",
    "NORAD_CAT_ID",
    "evaluation_time",
    "supgp_source_file",
    "supgp_source_row_index",
    "ordinary_gp_id",
    "exclusion_reason",
    "ordinary_sgp4_status",
    "supgp_sgp4_status",
    "frame_transform_status",
    "rtn_status",
    "execution_message",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_z(value: Any) -> str:
    return parse_utc(value).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def april_protected_inventory() -> dict[str, Any]:
    paths = [path for path in Path("outputs").rglob("*") if path.is_file() and APRIL_WINDOW_TAG in path.name]
    paths.extend(path for path in APRIL_SUPGP_DIR.glob("*.csv") if path.is_file())
    paths.append(APRIL_ORDINARY_RAW)
    unique = sorted({path.as_posix(): path for path in paths}.values(), key=lambda path: path.as_posix())
    missing = [path.as_posix() for path in unique if not path.exists()]
    if missing:
        raise SystemExit(f"April protected artifact missing: {missing}")
    entries = [{"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in unique]
    payload = json.dumps(entries, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    aggregate = hashlib.sha256(payload).hexdigest().upper()
    if len(entries) != APRIL_PROTECTED_EXPECTED_COUNT:
        raise SystemExit(
            f"April protected inventory count changed: expected {APRIL_PROTECTED_EXPECTED_COUNT}, found {len(entries)}"
        )
    dataset_sha = sha256(APRIL_DATASET_PATH)
    if dataset_sha != APRIL_DATASET_SHA256:
        raise SystemExit(f"April canonical Stage-1B dataset SHA mismatch: {dataset_sha}")
    return {
        "artifact_count": len(entries),
        "aggregate_sha256": aggregate,
        "canonical_stage1b_dataset_sha256": dataset_sha,
        "entries": entries,
    }


def readiness_v2_protected_inventory(context: dict[str, Any]) -> dict[str, Any] | None:
    readiness = context.get("readiness_v2")
    if readiness is None:
        return None
    expected: dict[str, str] = {
        normalize_path(path_text).as_posix(): str(expected_sha).upper()
        for path_text, expected_sha in readiness["manifest"]["provenance"]["protected_after"].items()
    }
    for path_text, expected_sha in readiness["manifest"]["outputs"].items():
        expected[normalize_path(path_text).as_posix()] = str(expected_sha).upper()
    expected[readiness["path"].as_posix()] = readiness["sha256"]
    entries = []
    for path_text, expected_sha in sorted(expected.items()):
        path = normalize_path(path_text)
        current_sha = sha256(path) if path.exists() else ""
        if current_sha != expected_sha:
            raise SystemExit(f"Frozen V2 protected artifact mismatch: {path}")
        entries.append({
            "path": path.as_posix(),
            "sha256": current_sha,
            "size_bytes": path.stat().st_size,
        })
    payload = json.dumps(entries, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return {
        "artifact_count": len(entries),
        "aggregate_sha256": hashlib.sha256(payload).hexdigest().upper(),
        "entries": entries,
    }


def credential_value_match_count(paths: list[Path]) -> int:
    pattern = re.compile(
        r"(?i)(?:password|passwd|api[_-]?key|access[_-]?token|space[_-]?track[_-]?identity)\s*[:=]\s*[^\s,}\]]+"
    )
    total = 0
    for path in paths:
        if path.exists():
            total += len(pattern.findall(path.read_text(encoding="utf-8-sig", errors="replace")))
    return total


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Required input manifest missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Required input CSV missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def verify_readiness_adjudication(
    acquisition_sha: str,
    causal_audit_sha: str,
    cohort_selection_sha: str,
) -> dict[str, Any] | None:
    if READINESS_ADJUDICATION_MANIFEST is None:
        return None
    amendment = load_json(READINESS_ADJUDICATION_MANIFEST)
    failures: list[str] = []
    if amendment.get("status") != "JUNE_STAGE1A_PROTOCOL_ADJUDICATED_CAUSAL_READY":
        failures.append("amendment status mismatch")
    if amendment.get("protocol", {}).get("name") != CAUSAL_DATA_READINESS_V2:
        failures.append("amendment protocol name mismatch")
    clarified = amendment.get("protocol", {}).get("new_clarified_rule", {})
    if clarified.get("gt72_alone_blocks_stage1b") is not False:
        failures.append("amendment does not allow causally valid >72 h rows")
    if clarified.get("stage1f_formal_support") != "0 < element_age_hours <= 36":
        failures.append("amendment Stage-1F support mismatch")
    if amendment.get("stage_effects", {}).get("stage1f_scientific_protocol_changed") is not False:
        failures.append("amendment changed the Stage-1F scientific protocol")
    if amendment.get("june", {}).get("stage1b_canonical_eligible_rows") != EXPECTED_FORMAL_ROWS:
        failures.append("amendment Stage-1B eligible row count mismatch")
    if amendment.get("june", {}).get("cohort_readiness_v2_status") != "READY_WITH_GT72H_STALENESS":
        failures.append("amendment cohort readiness status mismatch")
    frozen = amendment.get("frozen_stage1f", {})
    if frozen.get("parameter_sha256") != EXPECTED_STAGE1F_PARAMETER_SHA256:
        failures.append("amendment frozen parameter SHA mismatch")
    parameter_path = normalize_path(frozen.get("parameter_path", ""))
    if not parameter_path.exists() or sha256(parameter_path) != EXPECTED_STAGE1F_PARAMETER_SHA256:
        failures.append("protected Stage-1F parameter artifact SHA mismatch")

    protected_expected = amendment.get("provenance", {}).get("protected_after", {})
    protected_before: dict[str, str] = {}
    for path_text, expected_sha in protected_expected.items():
        path = normalize_path(path_text)
        current = sha256(path) if path.exists() else ""
        protected_before[path.as_posix()] = current
        if current != str(expected_sha).upper():
            failures.append(f"protected artifact mismatch: {path}")
    for path_text, expected_sha in amendment.get("outputs", {}).items():
        path = normalize_path(path_text)
        if not path.exists() or sha256(path) != str(expected_sha).upper():
            failures.append(f"amendment output mismatch: {path}")
    if sha256(READINESS_ADJUDICATION_MANIFEST) == "":
        failures.append("amendment manifest SHA unavailable")

    source_artifacts = amendment.get("provenance", {}).get("source_artifacts", {})
    acquisition_key = ACQUISITION_MANIFEST.as_posix()
    causal_key = CAUSAL_AUDIT.as_posix()
    if str(source_artifacts.get(acquisition_key, "")).upper() != acquisition_sha:
        failures.append("amendment acquisition manifest binding mismatch")
    if str(source_artifacts.get(causal_key, "")).upper() != causal_audit_sha:
        failures.append("amendment causal audit binding mismatch")
    protected_selection_shas = {str(value).upper() for value in protected_expected.values()}
    if cohort_selection_sha not in protected_selection_shas:
        failures.append("amendment cohort selection binding mismatch")
    if failures:
        raise SystemExit(f"CAUSAL_DATA_READINESS_V2 verification failed: {[item for item in failures if item]}")
    return {
        "manifest": amendment,
        "path": READINESS_ADJUDICATION_MANIFEST,
        "sha256": sha256(READINESS_ADJUDICATION_MANIFEST),
        "protected_before": protected_before,
        "parameter_path": parameter_path,
        "parameter_sha256": EXPECTED_STAGE1F_PARAMETER_SHA256,
    }


def normalize_path(value: str | Path) -> Path:
    return Path(str(value).replace("\\", "/"))


def configure_runtime(args: argparse.Namespace) -> None:
    """Bind only window/path context; the frozen numerical implementation is unchanged."""
    global WINDOW_TAG, FORMAL_START, FORMAL_STOP_EXCLUSIVE, FORMAL_INTERVAL
    global STAGE1_PREFIX, STAGE1B_PREFIX, SUPGP_DIR, DESIGN_MANIFEST
    global ACQUISITION_MANIFEST, REFERENCE_MANIFEST, REFERENCE_QUALITY, CAUSAL_AUDIT
    global READINESS_ADJUDICATION_MANIFEST
    global COHORT_SELECTION, DATASET_PATH, SUMMARY_PATH, CORRECTNESS_PATH, FAILURE_PATH
    global MANIFEST_PATH, REPORT_PATH, SMOKE_CROSSCHECK_PATH, SMOKE_CORRECTNESS_PATH
    global SMOKE_MANIFEST_PATH, EXPECTED_FORMAL_ROWS

    start = parse_utc(args.formal_start)
    stop = parse_utc(args.formal_stop)
    if stop <= start:
        raise SystemExit("formal stop must be after formal start")
    WINDOW_TAG = str(args.window_tag)
    FORMAL_START = iso_z(start)
    FORMAL_STOP_EXCLUSIVE = iso_z(stop)
    FORMAL_INTERVAL = f"[{FORMAL_START}, {FORMAL_STOP_EXCLUSIVE})"
    EXPECTED_FORMAL_ROWS = int(args.expected_formal_rows)
    if EXPECTED_FORMAL_ROWS <= 0:
        raise SystemExit("expected formal rows must be positive")

    STAGE1_PREFIX = f"orbit_uncertainty_stage1_{WINDOW_TAG}"
    STAGE1B_PREFIX = f"orbit_uncertainty_stage1b_{WINDOW_TAG}"
    SUPGP_DIR = normalize_path(args.supgp_dir)
    default_design = METRICS_DIR / f"{STAGE1_PREFIX}_design_manifest.json"
    DESIGN_MANIFEST = normalize_path(args.design_manifest) if args.design_manifest else (default_design if default_design.exists() else None)
    ACQUISITION_MANIFEST = normalize_path(args.acquisition_manifest) if args.acquisition_manifest else METRICS_DIR / f"{STAGE1_PREFIX}_acquisition_download_manifest.json"
    REFERENCE_MANIFEST = normalize_path(args.reference_manifest) if args.reference_manifest else METRICS_DIR / f"{STAGE1_PREFIX}_supgp_reference_quality_manifest.json"
    REFERENCE_QUALITY = normalize_path(args.reference_quality) if args.reference_quality else METRICS_DIR / f"{STAGE1_PREFIX}_supgp_reference_quality.csv"
    CAUSAL_AUDIT = normalize_path(args.causal_audit) if args.causal_audit else METRICS_DIR / f"{STAGE1_PREFIX}_ordinary_gp_causal_support_audit.csv"
    COHORT_SELECTION = normalize_path(args.cohort_selection) if args.cohort_selection else METRICS_DIR / f"{STAGE1_PREFIX}_satellite_selection.csv"
    READINESS_ADJUDICATION_MANIFEST = (
        normalize_path(args.readiness_adjudication_manifest)
        if getattr(args, "readiness_adjudication_manifest", None)
        else None
    )

    DATASET_PATH = DATASET_DIR / f"{STAGE1B_PREFIX}_rtn_residual_library.csv"
    SUMMARY_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_residual_summary.csv"
    CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_correctness_audit.csv"
    FAILURE_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_failure_audit.csv"
    MANIFEST_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_manifest.json"
    REPORT_PATH = REPORT_DIR / f"{STAGE1B_PREFIX}_report.md"
    SMOKE_CROSSCHECK_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_smoke_crosscheck.csv"
    SMOKE_CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_smoke_correctness_audit.csv"
    SMOKE_MANIFEST_PATH = METRICS_DIR / f"{STAGE1B_PREFIX}_smoke_manifest.json"


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def ensure_outputs_available(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing Stage-1B outputs: {existing}")


def package_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "astropy": astropy.__version__,
        "sgp4": getattr(sgp4, "__version__", version("sgp4")),
    }


def configure_iers() -> dict[str, Any]:
    # Open the current IERS-A table once (using Astropy's official configured
    # source/cache), bind that exact in-memory table for the whole build, and
    # then disable further downloads so the transform dependency cannot change
    # between rows.
    explicit_data_path = normalize_path(ARGS.iers_data_file) if ARGS.iers_data_file else None
    auto_download_at_open = not bool(ARGS.iers_cache_only or explicit_data_path)
    iers.conf.auto_download = auto_download_at_open
    iers.conf.auto_max_age = None
    table = iers.IERS_A.open(str(explicit_data_path)) if explicit_data_path else iers.IERS_Auto.open()
    iers.earth_orientation_table.set(table)
    iers.conf.auto_download = False
    min_mjd = float(np.min(table["MJD"].value))
    max_mjd = float(np.max(table["MJD"].value))
    start_mjd = float(Time(parse_utc(FORMAL_START), scale="utc").mjd)
    stop_mjd = float(Time(parse_utc(FORMAL_STOP_EXCLUSIVE), scale="utc").mjd)
    data_path_text = str(table.meta.get("data_path", ""))
    data_path = Path(data_path_text) if data_path_text else None
    return {
        "table_class": type(table).__name__,
        "mjd_min": min_mjd,
        "mjd_max": max_mjd,
        "formal_start_mjd": start_mjd,
        "formal_stop_mjd": stop_mjd,
        "formal_window_covered": min_mjd <= start_mjd and max_mjd >= stop_mjd,
        "data_url": str(table.meta.get("data_url", "")),
        "data_path": data_path_text,
        "data_sha256": sha256(data_path) if data_path and data_path.exists() else "",
        "auto_download_at_open": auto_download_at_open,
        "auto_download_during_build": False,
        "auto_max_age": None,
        "explicit_frozen_data_file": bool(explicit_data_path),
    }


def verify_stage1a_inputs() -> dict[str, Any]:
    acquisition = load_json(ACQUISITION_MANIFEST)
    reference = load_json(REFERENCE_MANIFEST)
    expected_interval = FORMAL_INTERVAL

    checks: list[tuple[bool, str]] = []
    checks.append((acquisition.get("window_tag") == WINDOW_TAG, "acquisition window tag"))
    checks.append((reference.get("window_tag") == WINDOW_TAG, "reference window tag"))
    checks.append((acquisition["formal_window"] == expected_interval, "acquisition formal window"))
    checks.append((reference["scope"]["formal_window"] == expected_interval, "reference formal window"))

    authoritative = acquisition.get("authoritative_selection", {})
    configured_selection = COHORT_SELECTION
    if not configured_selection.exists() and authoritative.get("path"):
        configured_selection = normalize_path(authoritative["path"])
    selection_path = configured_selection
    checks.append((selection_path.exists(), "cohort selection exists"))
    selection_sha = sha256(selection_path) if selection_path.exists() else ""
    selection_rows = load_csv(selection_path) if selection_path.exists() else []
    cohort = [str(row["NORAD_CAT_ID"]) for row in selection_rows]
    checks.append((len(cohort) == 20 and len(set(cohort)) == 20, "cohort selection size/uniqueness"))
    checks.append((selection_sha == str(authoritative.get("sha256", "")).upper(), "acquisition cohort selection SHA"))
    checks.append((normalize_path(authoritative.get("path", "")) == selection_path, "acquisition cohort selection path"))
    checks.append((selection_sha == str(reference["selection"]["sha256"]).upper(), "reference cohort selection SHA"))
    checks.append((normalize_path(reference["selection"]["path"]) == selection_path, "reference cohort selection path"))
    checks.append((cohort == [str(value) for value in acquisition["ordinary_gp"]["request_object_ids"]], "ordinary cohort/order"))
    checks.append((reference["result"]["status_counts"] == {"READY": 20}, "reference READY status"))
    checks.append((bool(reference["result"]["full_formal_window_stage1b_ready"]), "reference readiness flag"))
    checks.append((int(reference["result"]["formal_window_record_count"]) == EXPECTED_FORMAL_ROWS, "reference row count"))
    checks.append((int(acquisition["causal_support"]["evaluation_count"]) == EXPECTED_FORMAL_ROWS, "causal evaluation count"))
    checks.append((int(acquisition["causal_support"]["candidate_available_count"]) == EXPECTED_FORMAL_ROWS, "causal availability"))
    checks.append((int(acquisition["causal_support"]["future_publication_use_count"]) == 0, "Stage-1A future publication"))

    design: dict[str, Any] | None = None
    if DESIGN_MANIFEST is not None:
        design = load_json(DESIGN_MANIFEST)
        checks.append((design.get("status") == "APRIL_DESIGN_FROZEN", "design status"))
        checks.append((design.get("window_tag") == WINDOW_TAG, "design window tag"))
        checks.append((design["window"]["formal_half_open_interval"] == expected_interval, "design formal window"))
        checks.append(([str(value) for value in design["cohort"]["norad_cat_ids"]] == cohort, "design cohort/order"))

    ordinary_path = normalize_path(acquisition["ordinary_gp"]["raw_file"])
    checks.append((ordinary_path.exists(), "ordinary raw exists"))
    ordinary_sha = sha256(ordinary_path) if ordinary_path.exists() else ""
    checks.append((ordinary_sha == str(acquisition["ordinary_gp"]["sha256"]).upper(), "ordinary raw SHA"))

    causal_path = CAUSAL_AUDIT
    checks.append((causal_path.exists(), "Stage-1A causal audit exists"))
    causal_rows = load_csv(causal_path) if causal_path.exists() else []
    causal_keys = [(str(row.get("NORAD_CAT_ID", "")), iso_z(row.get("evaluation_time", ""))) for row in causal_rows]
    checks.append((len(causal_rows) == EXPECTED_FORMAL_ROWS, "Stage-1A causal audit row count"))
    checks.append((len(set(causal_keys)) == len(causal_keys), "Stage-1A causal audit key uniqueness"))
    checks.append((set(key[0] for key in causal_keys) == set(cohort), "Stage-1A causal audit cohort"))
    acquisition_sha = sha256(ACQUISITION_MANIFEST)
    causal_sha = sha256(causal_path) if causal_path.exists() else ""
    readiness = verify_readiness_adjudication(acquisition_sha, causal_sha, selection_sha)
    if readiness is None:
        checks.append((int(acquisition["causal_support"]["gp_age_gt_72h_count"]) == 0, "Stage-1A age >72h"))
        checks.append((all(row.get("causal_status") == "READY" for row in causal_rows), "Stage-1A causal row status"))
    else:
        expected_gt72 = int(readiness["manifest"]["june"]["element_age_gt72_rows"])
        actual_gt72 = int(acquisition["causal_support"]["gp_age_gt_72h_count"])
        checks.append((actual_gt72 == expected_gt72, "V2 engineering staleness >72h count"))
        causal_status_valid = all(
            row.get("causal_status") == (
                "CAUSAL_AVAILABLE_GP_AGE_GT_72H"
                if float(row["gp_age_seconds"]) > LOOKBACK_HOURS * 3600.0
                else "READY"
            )
            for row in causal_rows
        )
        checks.append((causal_status_valid, "V2 Stage-1A causal row status"))

    formal_gate = acquisition.get("historical_supgp", {}).get("formal_reference_quality_gate", {})
    checks.append((formal_gate.get("status") == "VERIFIED", "acquisition SupGP gate binding status"))
    checks.append((normalize_path(formal_gate.get("path", "")) == REFERENCE_MANIFEST, "acquisition SupGP gate path"))
    checks.append((str(formal_gate.get("sha256", "")).upper() == sha256(REFERENCE_MANIFEST), "acquisition SupGP gate SHA"))
    checks.append((bool(formal_gate.get("raw_sha_inventory_match")), "acquisition SupGP raw inventory binding"))

    reference_files: list[dict[str, Any]] = []
    for entry in reference["raw"]["files"]:
        path = normalize_path(entry["raw_file"])
        current_sha = sha256(path) if path.exists() else ""
        reference_files.append({
            "path": path.as_posix(),
            "sha256": current_sha,
            "expected_sha256": str(entry["sha256"]).upper(),
            "row_count": int(entry["row_count"]),
        })
        checks.append((path.exists(), f"SupGP raw exists: {path.name}"))
        checks.append((current_sha == str(entry["sha256"]).upper(), f"SupGP raw SHA: {path.name}"))
        checks.append((path.parent == SUPGP_DIR, f"SupGP configured directory: {path.name}"))
    checks.append((len(reference_files) == 20, "SupGP file count"))
    checks.append((sum(item["row_count"] for item in reference_files) == EXPECTED_FORMAL_ROWS, "SupGP manifest records"))

    failures = [label for passed, label in checks if not passed]
    if failures:
        raise SystemExit(f"Stage-1A input verification failed: {failures}")

    return {
        "cohort": cohort,
        "ordinary_path": ordinary_path,
        "ordinary_sha256": ordinary_sha,
        "selection_path": selection_path,
        "selection_sha256": selection_sha,
        "reference_files": reference_files,
        "design_manifest": design,
        "acquisition_manifest": acquisition,
        "reference_manifest": reference,
        "manifest_sha256": {
            "design": sha256(DESIGN_MANIFEST) if DESIGN_MANIFEST is not None else None,
            "acquisition": acquisition_sha,
            "reference_quality": sha256(REFERENCE_MANIFEST),
            "causal_support_audit": causal_sha,
            "cohort_selection": selection_sha,
            "readiness_adjudication": readiness["sha256"] if readiness else None,
        },
        "causal_rows": causal_rows,
        "causal_path": causal_path,
        "archive_pause": acquisition.get("historical_supgp", {}).get("reference_availability_fact", {}),
        "verified_check_count": len(checks),
        "readiness_v2": readiness,
        "readiness_v2_enabled": readiness is not None,
    }


def read_ordinary(context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    records = json.loads(context["ordinary_path"].read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise SystemExit("Ordinary GP raw is not a JSON list")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("NORAD_CAT_ID", ""))].append(record)
    if set(grouped) != set(context["cohort"]):
        raise SystemExit("Ordinary raw cohort differs from frozen Stage-1 cohort")
    if len(records) != int(context["acquisition_manifest"]["ordinary_gp"]["record_count"]):
        raise SystemExit("Ordinary raw record count differs from acquisition manifest")
    return records, grouped


def read_reference_status(context: dict[str, Any]) -> dict[str, str]:
    rows = load_csv(REFERENCE_QUALITY)
    status = {str(row["norad_id"]): str(row["status"]) for row in rows}
    if set(status) != set(context["cohort"]) or any(value != "READY" for value in status.values()):
        raise SystemExit("Reference-quality CSV is not READY for the frozen 20-satellite cohort")
    return status


def read_supgp(context: dict[str, Any]) -> list[dict[str, Any]]:
    start = parse_utc(FORMAL_START)
    stop = parse_utc(FORMAL_STOP_EXCLUSIVE)
    rows: list[dict[str, Any]] = []
    manifest_by_path = {normalize_path(item["path"]).as_posix(): item for item in context["reference_files"]}
    for file_entry in context["reference_files"]:
        path = normalize_path(file_entry["path"])
        parsed_count = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source_row, row in enumerate(csv.DictReader(handle), start=2):
                parsed_count += 1
                evaluation = parse_utc(row["EPOCH"])
                if not (start <= evaluation < stop):
                    raise SystemExit(f"SupGP epoch outside frozen formal window: {path}:{source_row}")
                item = dict(row)
                item["_evaluation_time"] = evaluation
                item["_source_file"] = path.as_posix()
                item["_source_row_index"] = source_row
                item["_source_file_sha256"] = manifest_by_path[path.as_posix()]["sha256"]
                rows.append(item)
        if parsed_count != int(file_entry["row_count"]):
            raise SystemExit(f"SupGP row count differs from manifest: {path}")
    if len(rows) != EXPECTED_FORMAL_ROWS:
        raise SystemExit(f"Expected {EXPECTED_FORMAL_ROWS} SupGP rows, found {len(rows)}")
    if {str(row["NORAD_CAT_ID"]) for row in rows} != set(context["cohort"]):
        raise SystemExit("SupGP cohort differs from frozen Stage-1 cohort")
    rows.sort(key=lambda row: (context["cohort"].index(str(row["NORAD_CAT_ID"])), row["_evaluation_time"], row["_source_row_index"]))
    return rows


def selection_tie_break(records: list[dict[str, Any]], evaluation_time: datetime) -> str:
    eligible = [record for record in records if parse_utc(record["CREATION_DATE"]) <= evaluation_time]
    if not eligible:
        return "NO_CAUSAL_GP"
    latest_creation = max(parse_utc(record["CREATION_DATE"]) for record in eligible)
    creation_tied = [record for record in eligible if parse_utc(record["CREATION_DATE"]) == latest_creation]
    if len(creation_tied) == 1:
        return "LATEST_CREATION_DATE"
    latest_epoch = max(parse_utc(record["EPOCH"]) for record in creation_tied)
    epoch_tied = [record for record in creation_tied if parse_utc(record["EPOCH"]) == latest_epoch]
    if len(epoch_tied) == 1:
        return "LATEST_CREATION_DATE_THEN_EPOCH"
    return "LATEST_CREATION_DATE_THEN_EPOCH_THEN_GP_ID"


def empty_dataset_row(reference: dict[str, Any], reference_status: str, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "window_tag": WINDOW_TAG,
        "NORAD_CAT_ID": str(reference.get("NORAD_CAT_ID", "")),
        "object_name": str(reference.get("OBJECT_NAME", "")),
        "evaluation_time": iso_z(reference["_evaluation_time"]),
        "comparison_semantics": "ordinary-GP prediction disagreement relative to operator-derived higher-quality SupGP reference",
        "ordinary_gp_id": "",
        "ordinary_gp_epoch": "",
        "ordinary_gp_creation_date": "",
        "gp_age_seconds": "",
        "element_age_seconds": "",
        "element_age_hours": "",
        "publication_age_seconds": "",
        "publication_age_hours": "",
        "causal_readiness_protocol": (
            CAUSAL_DATA_READINESS_V2 if context.get("readiness_v2_enabled") else "LEGACY_STAGE1A_CAUSAL_READINESS"
        ),
        "stage1f_support_status": "",
        "within_stage1f_support": "",
        "engineering_staleness_gt72h": "",
        "ordinary_causal_candidate_count": 0,
        "ordinary_selection_rank": "",
        "ordinary_selection_tie_break": "NO_CAUSAL_GP",
        "ordinary_raw_file": context["ordinary_path"].as_posix(),
        "ordinary_raw_sha256": context["ordinary_sha256"],
        "supgp_epoch": iso_z(reference["EPOCH"]),
        "supgp_data_source": str(reference.get("DATA_SOURCE", "")),
        "supgp_rms_km": str(reference.get("RMS", "")),
        "supgp_source_file": reference["_source_file"],
        "supgp_source_row_index": reference["_source_row_index"],
        "supgp_source_file_sha256": reference["_source_file_sha256"],
        "supgp_reference_status": reference_status,
        "native_frame_ordinary": "TEME",
        "native_frame_supgp": "TEME",
        "common_frame": "GCRS",
        "time_scale": "UTC",
        "rtn_basis_source": "SupGP/reference GCRS state",
        "ordinary_sgp4_status": "NOT_RUN",
        "supgp_sgp4_status": "NOT_RUN",
        "frame_transform_status": "NOT_RUN",
        "rtn_status": "NOT_RUN",
        "finite_state_status": "NOT_RUN",
        "nominal_row": False,
        "exclusion_reason": "",
        "execution_message": "",
    }


def finite_arrays(*arrays: np.ndarray) -> bool:
    return all(bool(np.isfinite(np.asarray(array, dtype=float)).all()) for array in arrays)


def residual_components(
    ordinary_position: np.ndarray,
    ordinary_velocity: np.ndarray,
    reference_position: np.ndarray,
    reference_velocity: np.ndarray,
) -> dict[str, Any]:
    basis = rtn_basis(reference_position, reference_velocity)
    dr = ordinary_position - reference_position
    dv = ordinary_velocity - reference_velocity
    dr_rtn = basis @ dr
    dv_rtn = basis @ dv
    position_norm = float(np.linalg.norm(dr))
    velocity_norm = float(np.linalg.norm(dv))
    position_rtn_norm = float(np.linalg.norm(dr_rtn))
    velocity_rtn_norm = float(np.linalg.norm(dv_rtn))
    reconstructed_dr = basis.T @ dr_rtn
    reconstructed_dv = basis.T @ dv_rtn
    radial, transverse, normal = basis
    return {
        "basis": basis,
        "dr": dr,
        "dv": dv,
        "dr_rtn": dr_rtn,
        "dv_rtn": dv_rtn,
        "position_norm": position_norm,
        "velocity_norm": velocity_norm,
        "rtn_orthonormality_error": float(np.max(np.abs(basis @ basis.T - np.eye(3)))),
        "rtn_R_unit_norm_error": abs(float(np.linalg.norm(radial)) - 1.0),
        "rtn_T_unit_norm_error": abs(float(np.linalg.norm(transverse)) - 1.0),
        "rtn_N_unit_norm_error": abs(float(np.linalg.norm(normal)) - 1.0),
        "rtn_R_dot_T": float(np.dot(radial, transverse)),
        "rtn_R_dot_N": float(np.dot(radial, normal)),
        "rtn_T_dot_N": float(np.dot(transverse, normal)),
        "rtn_right_handedness_error": float(np.linalg.norm(np.cross(radial, transverse) - normal)),
        "position_reconstruction_error": float(np.linalg.norm(reconstructed_dr - dr)),
        "velocity_reconstruction_error": float(np.linalg.norm(reconstructed_dv - dv)),
        "cartesian_position_invariance_error": abs(float(np.linalg.norm(dr)) - position_rtn_norm),
        "cartesian_velocity_invariance_error": abs(float(np.linalg.norm(dv)) - velocity_rtn_norm),
    }


def to_gcrs_batch(
    positions_km: np.ndarray,
    velocities_km_s: np.ndarray,
    epochs: list[datetime],
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized equivalent of the Stage-0 scalar TEME->GCRS transform."""
    positions = np.asarray(positions_km, dtype=float)
    velocities = np.asarray(velocities_km_s, dtype=float)
    if positions.ndim != 2 or positions.shape[1] != 3 or velocities.shape != positions.shape:
        raise ValueError("Batch state arrays must both have shape (n, 3)")
    if len(epochs) != len(positions):
        raise ValueError("Batch epoch/state length mismatch")
    times = Time(epochs, scale="utc")
    representation = CartesianRepresentation(
        positions.T * u.km,
        differentials=CartesianDifferential(velocities.T * u.km / u.s),
    )
    teme = TEME(representation, obstime=times)
    gcrs = teme.transform_to(GCRS(obstime=times))
    return (
        gcrs.cartesian.xyz.to_value(u.km).T,
        gcrs.cartesian.differentials["s"].d_xyz.to_value(u.km / u.s).T,
    )


def prepare_native_row(
    reference: dict[str, Any],
    ordinary_records: list[dict[str, Any]],
    reference_status: str,
    context: dict[str, Any],
    ordinary_sat_cache: dict[tuple[str, str, str, str], Satrec],
) -> tuple[dict[str, Any], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None]:
    """Select causal GP and propagate both OMM/TLE representations to TEME."""
    row = empty_dataset_row(reference, reference_status, context)
    evaluation = reference["_evaluation_time"]
    selected, candidate_count = select_causal_gp(ordinary_records, evaluation)
    row["ordinary_causal_candidate_count"] = candidate_count
    row["ordinary_selection_tie_break"] = selection_tie_break(ordinary_records, evaluation)
    if selected is None:
        row["exclusion_reason"] = "NO_CAUSAL_GP"
        row["execution_message"] = "No ordinary GP with CREATION_DATE <= evaluation_time"
        return row, None

    gp_epoch = parse_utc(selected["EPOCH"])
    creation = parse_utc(selected["CREATION_DATE"])
    element_age = (evaluation - gp_epoch).total_seconds()
    publication_age = (evaluation - creation).total_seconds()
    row.update({
        "ordinary_gp_id": str(selected.get("GP_ID", "")),
        "ordinary_gp_epoch": iso_z(gp_epoch),
        "ordinary_gp_creation_date": iso_z(creation),
        "gp_age_seconds": element_age,
        "element_age_seconds": element_age,
        "element_age_hours": element_age / 3600.0,
        "publication_age_seconds": publication_age,
        "publication_age_hours": publication_age / 3600.0,
        "stage1f_support_status": (
            "WITHIN_STAGE1F_SUPPORT"
            if 0.0 < element_age <= APRIL_CALIBRATED_FRESHNESS_SECONDS
            else "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT"
        ),
        "within_stage1f_support": 0.0 < element_age <= APRIL_CALIBRATED_FRESHNESS_SECONDS,
        "engineering_staleness_gt72h": element_age > LOOKBACK_HOURS * 3600.0,
        "ordinary_selection_rank": 1,
    })
    if creation > evaluation:
        row["exclusion_reason"] = "PROVENANCE_ERROR"
        row["execution_message"] = "Selected ordinary GP was published after evaluation_time"
        return row, None
    if element_age < 0:
        row["exclusion_reason"] = "PROVENANCE_ERROR"
        row["execution_message"] = "Selected ordinary GP EPOCH is after evaluation_time"
        return row, None
    if element_age > LOOKBACK_HOURS * 3600.0 and not context.get("readiness_v2_enabled"):
        row["exclusion_reason"] = "GP_AGE_GT_72H"
        row["execution_message"] = f"element_age_seconds={element_age}"
        return row, None

    cache_key = (
        str(selected.get("NORAD_CAT_ID", "")),
        str(selected.get("GP_ID", "")),
        str(selected.get("EPOCH", "")),
        str(selected.get("CREATION_DATE", "")),
    )
    try:
        ordinary_sat = ordinary_sat_cache.get(cache_key)
        if ordinary_sat is None:
            ordinary_sat = Satrec.twoline2rv(str(selected["TLE_LINE1"]), str(selected["TLE_LINE2"]))
            ordinary_sat_cache[cache_key] = ordinary_sat
        ordinary_r_teme, ordinary_v_teme = propagate(ordinary_sat, evaluation)
        row["ordinary_sgp4_status"] = "OK"
    except Exception as exc:
        row["ordinary_sgp4_status"] = "ERROR"
        row["exclusion_reason"] = "ORDINARY_SGP4_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return row, None

    try:
        reference_sat = satrec_from_supgp(reference)
        reference_r_teme, reference_v_teme = propagate(reference_sat, evaluation)
        row["supgp_sgp4_status"] = "OK"
    except Exception as exc:
        row["supgp_sgp4_status"] = "ERROR"
        row["exclusion_reason"] = "SUPGP_SGP4_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return row, None

    if not finite_arrays(ordinary_r_teme, ordinary_v_teme, reference_r_teme, reference_v_teme):
        row["finite_state_status"] = "NONFINITE"
        row["exclusion_reason"] = "NONFINITE_STATE"
        row["execution_message"] = "Nonfinite native TEME state"
        return row, None
    return row, (ordinary_r_teme, ordinary_v_teme, reference_r_teme, reference_v_teme)


def finish_common_frame_row(
    row: dict[str, Any],
    ordinary_r: np.ndarray,
    ordinary_v: np.ndarray,
    reference_r: np.ndarray,
    reference_v: np.ndarray,
) -> None:
    if not finite_arrays(ordinary_r, ordinary_v, reference_r, reference_v):
        row["finite_state_status"] = "NONFINITE"
        row["exclusion_reason"] = "NONFINITE_STATE"
        row["execution_message"] = "Nonfinite common-frame state"
        return
    try:
        values = residual_components(ordinary_r, ordinary_v, reference_r, reference_v)
        row["rtn_status"] = "OK"
    except Exception as exc:
        row["rtn_status"] = "ERROR"
        row["exclusion_reason"] = "RTN_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return
    if not finite_arrays(values["dr"], values["dv"], values["dr_rtn"], values["dv_rtn"], values["basis"]):
        row["finite_state_status"] = "NONFINITE"
        row["exclusion_reason"] = "NONFINITE_STATE"
        row["execution_message"] = "Nonfinite residual or RTN basis"
        return
    dr = values["dr"]
    dv = values["dv"]
    dr_rtn = values["dr_rtn"]
    dv_rtn = values["dv_rtn"]
    row.update({
        "delta_R_km": float(dr_rtn[0]),
        "delta_T_km": float(dr_rtn[1]),
        "delta_N_km": float(dr_rtn[2]),
        "delta_v_R_km_s": float(dv_rtn[0]),
        "delta_v_T_km_s": float(dv_rtn[1]),
        "delta_v_N_km_s": float(dv_rtn[2]),
        "position_error_norm_km": values["position_norm"],
        "velocity_error_norm_km_s": values["velocity_norm"],
        "delta_x_common_km": float(dr[0]),
        "delta_y_common_km": float(dr[1]),
        "delta_z_common_km": float(dr[2]),
        "delta_vx_common_km_s": float(dv[0]),
        "delta_vy_common_km_s": float(dv[1]),
        "delta_vz_common_km_s": float(dv[2]),
        "rtn_orthonormality_error": values["rtn_orthonormality_error"],
        "rtn_R_unit_norm_error": values["rtn_R_unit_norm_error"],
        "rtn_T_unit_norm_error": values["rtn_T_unit_norm_error"],
        "rtn_N_unit_norm_error": values["rtn_N_unit_norm_error"],
        "rtn_R_dot_T": values["rtn_R_dot_T"],
        "rtn_R_dot_N": values["rtn_R_dot_N"],
        "rtn_T_dot_N": values["rtn_T_dot_N"],
        "rtn_right_handedness_error": values["rtn_right_handedness_error"],
        "position_rtn_reconstruction_abs_error_km": values["position_reconstruction_error"],
        "velocity_rtn_reconstruction_abs_error_km_s": values["velocity_reconstruction_error"],
        "cartesian_rtn_position_norm_abs_error_km": values["cartesian_position_invariance_error"],
        "cartesian_rtn_velocity_norm_abs_error_km_s": values["cartesian_velocity_invariance_error"],
        "finite_state_status": "FINITE",
        "nominal_row": True,
        "exclusion_reason": "",
        "execution_message": "",
    })


def build_rows_batched(
    references: list[dict[str, Any]],
    ordinary_by_norad: dict[str, list[dict[str, Any]]],
    reference_status: dict[str, str],
    context: dict[str, Any],
    progress: bool = False,
    chunk_size: int = 512,
) -> list[dict[str, Any]]:
    cache: dict[tuple[str, str, str, str], Satrec] = {}
    rows: list[dict[str, Any]] = []
    native: list[tuple[int, datetime, np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for index, reference in enumerate(references, start=1):
        norad = str(reference["NORAD_CAT_ID"])
        row, state = prepare_native_row(reference, ordinary_by_norad[norad], reference_status[norad], context, cache)
        rows.append(row)
        if state is not None:
            native.append((len(rows) - 1, reference["_evaluation_time"], *state))
        if progress and index % 1000 == 0:
            print(f"native propagation {index}/{len(references)}", flush=True)

    for chunk_start in range(0, len(native), chunk_size):
        chunk = native[chunk_start:chunk_start + chunk_size]
        combined_positions = np.vstack(
            [np.vstack([item[2], item[4]]) for item in chunk]
        )
        combined_velocities = np.vstack(
            [np.vstack([item[3], item[5]]) for item in chunk]
        )
        combined_epochs = [epoch for item in chunk for epoch in [item[1], item[1]]]
        try:
            transformed_r, transformed_v = to_gcrs_batch(combined_positions, combined_velocities, combined_epochs)
            for local_index, item in enumerate(chunk):
                row = rows[item[0]]
                row["frame_transform_status"] = "OK"
                ordinary_offset = 2 * local_index
                finish_common_frame_row(
                    row,
                    transformed_r[ordinary_offset],
                    transformed_v[ordinary_offset],
                    transformed_r[ordinary_offset + 1],
                    transformed_v[ordinary_offset + 1],
                )
        except Exception:
            # Identify individual failures without silently dropping the rest of
            # a failed vectorized chunk.
            for item in chunk:
                row = rows[item[0]]
                try:
                    ordinary_r, ordinary_v = to_gcrs(item[2], item[3], item[1])
                    reference_r, reference_v = to_gcrs(item[4], item[5], item[1])
                    row["frame_transform_status"] = "OK_FALLBACK_SCALAR"
                    finish_common_frame_row(row, ordinary_r, ordinary_v, reference_r, reference_v)
                except Exception as exc:
                    row["frame_transform_status"] = "ERROR"
                    row["exclusion_reason"] = "FRAME_TRANSFORM_ERROR"
                    row["execution_message"] = f"{type(exc).__name__}: {exc}"
        if progress:
            completed = min(chunk_start + len(chunk), len(native))
            print(f"common-frame transform {completed}/{len(native)}", flush=True)
    return rows


def build_residual_row(
    reference: dict[str, Any],
    ordinary_records: list[dict[str, Any]],
    reference_status: str,
    context: dict[str, Any],
    ordinary_sat_cache: dict[tuple[str, str, str, str], Satrec],
) -> dict[str, Any]:
    row = empty_dataset_row(reference, reference_status, context)
    evaluation = reference["_evaluation_time"]
    selected, candidate_count = select_causal_gp(ordinary_records, evaluation)
    row["ordinary_causal_candidate_count"] = candidate_count
    row["ordinary_selection_tie_break"] = selection_tie_break(ordinary_records, evaluation)
    if selected is None:
        row["exclusion_reason"] = "NO_CAUSAL_GP"
        row["execution_message"] = "No ordinary GP with CREATION_DATE <= evaluation_time"
        return row

    gp_epoch = parse_utc(selected["EPOCH"])
    creation = parse_utc(selected["CREATION_DATE"])
    element_age = (evaluation - gp_epoch).total_seconds()
    publication_age = (evaluation - creation).total_seconds()
    row.update({
        "ordinary_gp_id": str(selected.get("GP_ID", "")),
        "ordinary_gp_epoch": iso_z(gp_epoch),
        "ordinary_gp_creation_date": iso_z(creation),
        "gp_age_seconds": element_age,
        "element_age_seconds": element_age,
        "element_age_hours": element_age / 3600.0,
        "publication_age_seconds": publication_age,
        "publication_age_hours": publication_age / 3600.0,
        "stage1f_support_status": (
            "WITHIN_STAGE1F_SUPPORT"
            if 0.0 < element_age <= APRIL_CALIBRATED_FRESHNESS_SECONDS
            else "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT"
        ),
        "within_stage1f_support": 0.0 < element_age <= APRIL_CALIBRATED_FRESHNESS_SECONDS,
        "engineering_staleness_gt72h": element_age > LOOKBACK_HOURS * 3600.0,
        "ordinary_selection_rank": 1,
    })
    if creation > evaluation:
        row["exclusion_reason"] = "PROVENANCE_ERROR"
        row["execution_message"] = "Selected ordinary GP was published after evaluation_time"
        return row
    if element_age < 0:
        row["exclusion_reason"] = "PROVENANCE_ERROR"
        row["execution_message"] = "Selected ordinary GP EPOCH is after evaluation_time"
        return row
    if element_age > LOOKBACK_HOURS * 3600.0 and not context.get("readiness_v2_enabled"):
        row["exclusion_reason"] = "GP_AGE_GT_72H"
        row["execution_message"] = f"element_age_seconds={element_age}"
        return row

    cache_key = (
        str(selected.get("NORAD_CAT_ID", "")),
        str(selected.get("GP_ID", "")),
        str(selected.get("EPOCH", "")),
        str(selected.get("CREATION_DATE", "")),
    )
    try:
        ordinary_sat = ordinary_sat_cache.get(cache_key)
        if ordinary_sat is None:
            ordinary_sat = Satrec.twoline2rv(str(selected["TLE_LINE1"]), str(selected["TLE_LINE2"]))
            ordinary_sat_cache[cache_key] = ordinary_sat
        ordinary_r_teme, ordinary_v_teme = propagate(ordinary_sat, evaluation)
        row["ordinary_sgp4_status"] = "OK"
    except Exception as exc:  # failure is retained and audited
        row["ordinary_sgp4_status"] = "ERROR"
        row["exclusion_reason"] = "ORDINARY_SGP4_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return row

    try:
        reference_sat = satrec_from_supgp(reference)
        reference_r_teme, reference_v_teme = propagate(reference_sat, evaluation)
        row["supgp_sgp4_status"] = "OK"
    except Exception as exc:
        row["supgp_sgp4_status"] = "ERROR"
        row["exclusion_reason"] = "SUPGP_SGP4_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return row

    if not finite_arrays(ordinary_r_teme, ordinary_v_teme, reference_r_teme, reference_v_teme):
        row["finite_state_status"] = "NONFINITE"
        row["exclusion_reason"] = "NONFINITE_STATE"
        row["execution_message"] = "Nonfinite native TEME state"
        return row

    try:
        ordinary_r, ordinary_v = to_gcrs(ordinary_r_teme, ordinary_v_teme, evaluation)
        reference_r, reference_v = to_gcrs(reference_r_teme, reference_v_teme, evaluation)
        row["frame_transform_status"] = "OK"
    except Exception as exc:
        row["frame_transform_status"] = "ERROR"
        row["exclusion_reason"] = "FRAME_TRANSFORM_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return row

    if not finite_arrays(ordinary_r, ordinary_v, reference_r, reference_v):
        row["finite_state_status"] = "NONFINITE"
        row["exclusion_reason"] = "NONFINITE_STATE"
        row["execution_message"] = "Nonfinite common-frame state"
        return row

    try:
        values = residual_components(ordinary_r, ordinary_v, reference_r, reference_v)
        row["rtn_status"] = "OK"
    except Exception as exc:
        row["rtn_status"] = "ERROR"
        row["exclusion_reason"] = "RTN_ERROR"
        row["execution_message"] = f"{type(exc).__name__}: {exc}"
        return row

    if not finite_arrays(values["dr"], values["dv"], values["dr_rtn"], values["dv_rtn"], values["basis"]):
        row["finite_state_status"] = "NONFINITE"
        row["exclusion_reason"] = "NONFINITE_STATE"
        row["execution_message"] = "Nonfinite residual or RTN basis"
        return row

    dr = values["dr"]
    dv = values["dv"]
    dr_rtn = values["dr_rtn"]
    dv_rtn = values["dv_rtn"]
    row.update({
        "delta_R_km": float(dr_rtn[0]),
        "delta_T_km": float(dr_rtn[1]),
        "delta_N_km": float(dr_rtn[2]),
        "delta_v_R_km_s": float(dv_rtn[0]),
        "delta_v_T_km_s": float(dv_rtn[1]),
        "delta_v_N_km_s": float(dv_rtn[2]),
        "position_error_norm_km": values["position_norm"],
        "velocity_error_norm_km_s": values["velocity_norm"],
        "delta_x_common_km": float(dr[0]),
        "delta_y_common_km": float(dr[1]),
        "delta_z_common_km": float(dr[2]),
        "delta_vx_common_km_s": float(dv[0]),
        "delta_vy_common_km_s": float(dv[1]),
        "delta_vz_common_km_s": float(dv[2]),
        "rtn_orthonormality_error": values["rtn_orthonormality_error"],
        "rtn_R_unit_norm_error": values["rtn_R_unit_norm_error"],
        "rtn_T_unit_norm_error": values["rtn_T_unit_norm_error"],
        "rtn_N_unit_norm_error": values["rtn_N_unit_norm_error"],
        "rtn_R_dot_T": values["rtn_R_dot_T"],
        "rtn_R_dot_N": values["rtn_R_dot_N"],
        "rtn_T_dot_N": values["rtn_T_dot_N"],
        "rtn_right_handedness_error": values["rtn_right_handedness_error"],
        "position_rtn_reconstruction_abs_error_km": values["position_reconstruction_error"],
        "velocity_rtn_reconstruction_abs_error_km_s": values["velocity_reconstruction_error"],
        "cartesian_rtn_position_norm_abs_error_km": values["cartesian_position_invariance_error"],
        "cartesian_rtn_velocity_norm_abs_error_km_s": values["cartesian_velocity_invariance_error"],
        "finite_state_status": "FINITE",
        "nominal_row": True,
        "exclusion_reason": "",
        "execution_message": "",
    })
    return row


def smoke_references(
    references: list[dict[str, Any]],
    ordinary_by_norad: dict[str, list[dict[str, Any]]],
    cohort: list[str],
) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for reference in references:
        selected, _ = select_causal_gp(ordinary_by_norad[str(reference["NORAD_CAT_ID"])], reference["_evaluation_time"])
        if selected is not None:
            age = (reference["_evaluation_time"] - parse_utc(selected["EPOCH"])).total_seconds()
            candidates.append((age, reference))
    ordered = sorted(candidates, key=lambda item: (item[0], item[1]["_evaluation_time"]))
    special = {
        "youngest_global": ordered[0][1],
        "median_global": ordered[len(ordered) // 2][1],
        "stalest_global": ordered[-1][1],
    }
    selected_satellites: list[str] = []
    for reference in special.values():
        norad = str(reference["NORAD_CAT_ID"])
        if norad not in selected_satellites:
            selected_satellites.append(norad)
    for norad in cohort:
        if len(selected_satellites) >= 3:
            break
        if norad not in selected_satellites:
            selected_satellites.append(norad)
    selected_satellites = selected_satellites[:3]

    by_key: dict[tuple[str, int], tuple[dict[str, Any], set[str]]] = {}
    formal_start = parse_utc(FORMAL_START)
    formal_stop = parse_utc(FORMAL_STOP_EXCLUSIVE)
    duration = formal_stop - formal_start
    target_times = {
        "month_start": formal_start + timedelta(days=1),
        "month_middle": formal_start + (duration - timedelta(days=1)) / 2,
        "month_end": formal_stop - timedelta(days=1, hours=12),
    }
    for norad in selected_satellites:
        group = [reference for reference in references if str(reference["NORAD_CAT_ID"]) == norad]
        for role, target in target_times.items():
            reference = min(group, key=lambda item: abs((item["_evaluation_time"] - target).total_seconds()))
            key = (reference["_source_file"], int(reference["_source_row_index"]))
            by_key.setdefault(key, (reference, set()))[1].add(role)
    for role, reference in special.items():
        if str(reference["NORAD_CAT_ID"]) in selected_satellites:
            key = (reference["_source_file"], int(reference["_source_row_index"]))
            by_key.setdefault(key, (reference, set()))[1].add(role)
    output = [(reference, "+".join(sorted(roles))) for reference, roles in by_key.values()]
    output.sort(key=lambda item: (selected_satellites.index(str(item[0]["NORAD_CAT_ID"])), item[0]["_evaluation_time"]))
    return output


def legacy_stage0_values(reference: dict[str, Any], ordinary: dict[str, Any]) -> dict[str, float]:
    evaluation = reference["_evaluation_time"]
    ordinary_sat = Satrec.twoline2rv(str(ordinary["TLE_LINE1"]), str(ordinary["TLE_LINE2"]))
    reference_sat = satrec_from_supgp(reference)
    ordinary_r_teme, ordinary_v_teme = propagate(ordinary_sat, evaluation)
    reference_r_teme, reference_v_teme = propagate(reference_sat, evaluation)
    ordinary_r, ordinary_v = to_gcrs(ordinary_r_teme, ordinary_v_teme, evaluation)
    reference_r, reference_v = to_gcrs(reference_r_teme, reference_v_teme, evaluation)
    values = residual_components(ordinary_r, ordinary_v, reference_r, reference_v)
    return {
        "delta_R_km": float(values["dr_rtn"][0]),
        "delta_T_km": float(values["dr_rtn"][1]),
        "delta_N_km": float(values["dr_rtn"][2]),
        "delta_v_R_km_s": float(values["dv_rtn"][0]),
        "delta_v_T_km_s": float(values["dv_rtn"][1]),
        "delta_v_N_km_s": float(values["dv_rtn"][2]),
        "position_error_norm_km": float(values["position_norm"]),
        "velocity_error_norm_km_s": float(values["velocity_norm"]),
    }


def run_smoke(
    context: dict[str, Any],
    references: list[dict[str, Any]],
    ordinary_by_norad: dict[str, list[dict[str, Any]]],
    reference_status: dict[str, str],
    iers_info: dict[str, Any],
) -> dict[str, Any]:
    ensure_outputs_available([SMOKE_CROSSCHECK_PATH, SMOKE_CORRECTNESS_PATH, SMOKE_MANIFEST_PATH], ARGS.overwrite)
    cases = smoke_references(references, ordinary_by_norad, context["cohort"])
    stage1a_rows = load_csv(CAUSAL_AUDIT)
    stage1a_by_key = {(row["NORAD_CAT_ID"], iso_z(row["evaluation_time"])): row for row in stage1a_rows}
    smoke_reference_rows = [reference for reference, _ in cases]
    batched_rows = build_rows_batched(
        smoke_reference_rows,
        ordinary_by_norad,
        reference_status,
        context,
    )
    comparisons: list[dict[str, Any]] = []
    numeric_fields = [
        "delta_R_km", "delta_T_km", "delta_N_km",
        "delta_v_R_km_s", "delta_v_T_km_s", "delta_v_N_km_s",
        "position_error_norm_km", "velocity_error_norm_km_s",
    ]
    for (reference, role), built in zip(cases, batched_rows):
        norad = str(reference["NORAD_CAT_ID"])
        selected, _ = select_causal_gp(ordinary_by_norad[norad], reference["_evaluation_time"])
        if selected is None:
            raise SystemExit("Smoke selection unexpectedly has no causal ordinary GP")
        legacy = legacy_stage0_values(reference, selected)
        stage1a = stage1a_by_key.get((norad, built["evaluation_time"]), {})
        comparison: dict[str, Any] = {
            "case_role": role,
            "NORAD_CAT_ID": norad,
            "evaluation_time": built["evaluation_time"],
            "stage1b_selected_gp_id": built["ordinary_gp_id"],
            "stage1a_selected_gp_id": stage1a.get("selected_gp_id", ""),
            "selected_gp_match": str(built["ordinary_gp_id"]) == str(stage1a.get("selected_gp_id", "")),
            "selected_gp_epoch_match": built["ordinary_gp_epoch"] == iso_z(stage1a.get("selected_gp_epoch", "")),
            "selected_gp_creation_date_match": built["ordinary_gp_creation_date"] == iso_z(stage1a.get("selected_gp_creation_date", "")),
            "element_age_abs_diff_seconds": abs(float(built["element_age_seconds"]) - float(stage1a.get("gp_age_seconds", "nan"))),
            "publication_age_abs_diff_seconds": abs(float(built["publication_age_seconds"]) - float(stage1a.get("publication_age_seconds", "nan"))),
            "evaluation_supgp_epoch_match": built["evaluation_time"] == built["supgp_epoch"],
            "element_age_hours": float(built["element_age_seconds"]) / 3600.0,
            "publication_age_hours": float(built["publication_age_seconds"]) / 3600.0,
            "nominal_row": built["nominal_row"],
        }
        for field in numeric_fields:
            comparison[f"stage1b_{field}"] = built[field]
            comparison[f"stage0_{field}"] = legacy[field]
            comparison[f"abs_diff_{field}"] = abs(float(built[field]) - float(legacy[field]))
        comparisons.append(comparison)

    max_numeric_diff = max(
        float(row[f"abs_diff_{field}"])
        for row in comparisons
        for field in numeric_fields
    )
    roles = "+".join(row["case_role"] for row in comparisons)
    audit = [
        {"check": "three smoke satellites", "passed": len({row["NORAD_CAT_ID"] for row in comparisons}) == 3, "observed": sorted({row["NORAD_CAT_ID"] for row in comparisons})},
        {"check": "month start/middle/end coverage", "passed": all(role in roles for role in ["month_start", "month_middle", "month_end"]), "observed": roles},
        {"check": "young/median/stale age cases", "passed": all(role in roles for role in ["youngest_global", "median_global", "stalest_global"]), "observed": roles},
        {"check": "Stage-1A selected GP agreement", "passed": all(bool(row["selected_gp_match"]) for row in comparisons), "observed": f"matched={sum(bool(row['selected_gp_match']) for row in comparisons)}/{len(comparisons)}"},
        {"check": "Stage-1A selected timestamps and ages agreement", "passed": all(bool(row["selected_gp_epoch_match"]) and bool(row["selected_gp_creation_date_match"]) and float(row["element_age_abs_diff_seconds"]) <= 1e-6 and float(row["publication_age_abs_diff_seconds"]) <= 1e-6 for row in comparisons), "observed": f"max_element_age_diff={max(float(row['element_age_abs_diff_seconds']) for row in comparisons)}; max_publication_age_diff={max(float(row['publication_age_abs_diff_seconds']) for row in comparisons)}"},
        {"check": "evaluation time equals SupGP epoch", "passed": all(bool(row["evaluation_supgp_epoch_match"]) for row in comparisons), "observed": f"matched={sum(bool(row['evaluation_supgp_epoch_match']) for row in comparisons)}/{len(comparisons)}"},
        {"check": "Stage-0 numerical agreement", "passed": max_numeric_diff <= NUMERIC_ABS_TOL, "observed": f"max_abs_diff={max_numeric_diff}"},
        {"check": "all smoke rows nominal", "passed": all(bool(row["nominal_row"]) for row in comparisons), "observed": f"nominal={sum(bool(row['nominal_row']) for row in comparisons)}/{len(comparisons)}"},
        {"check": "IERS covers formal window", "passed": bool(iers_info["formal_window_covered"]), "observed": json.dumps(iers_info)},
    ]
    passed = all(bool(row["passed"]) for row in audit)
    cross_fields = list(comparisons[0]) if comparisons else []
    write_csv(SMOKE_CROSSCHECK_PATH, comparisons, cross_fields)
    write_csv(SMOKE_CORRECTNESS_PATH, audit, ["check", "passed", "observed"])
    manifest = {
        "stage": "Orbit Uncertainty Stage-1B smoke",
        "status": "PASS" if passed else "FAIL",
        "window_tag": WINDOW_TAG,
        "generated_utc": utc_now(),
        "builder": {"path": Path(__file__).as_posix(), "sha256": sha256(Path(__file__))},
        "stage1a_manifest_sha256": context["manifest_sha256"],
        "ordinary_raw_sha256": context["ordinary_sha256"],
        "supgp_raw_sha256": {item["path"]: item["sha256"] for item in context["reference_files"]},
        "case_count": len(comparisons),
        "satellite_count": len({row["NORAD_CAT_ID"] for row in comparisons}),
        "max_numeric_abs_difference": max_numeric_diff,
        "numeric_tolerance": NUMERIC_ABS_TOL,
        "iers": iers_info,
        "april_protection": {
            "artifact_count": context["april_protection_before"]["artifact_count"],
            "aggregate_sha256": context["april_protection_before"]["aggregate_sha256"],
            "canonical_stage1b_dataset_sha256": context["april_protection_before"]["canonical_stage1b_dataset_sha256"],
        },
        "outputs": {
            "crosscheck": {"path": SMOKE_CROSSCHECK_PATH.as_posix(), "sha256": sha256(SMOKE_CROSSCHECK_PATH)},
            "correctness": {"path": SMOKE_CORRECTNESS_PATH.as_posix(), "sha256": sha256(SMOKE_CORRECTNESS_PATH)},
        },
    }
    write_json(SMOKE_MANIFEST_PATH, manifest)
    print(json.dumps({
        "mode": "smoke",
        "status": manifest["status"],
        "cases": len(comparisons),
        "satellites": manifest["satellite_count"],
        "max_numeric_abs_difference": max_numeric_diff,
    }, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit("Stage-1B smoke validation failed; formal run is blocked")
    return manifest


def verify_smoke_precondition(context: dict[str, Any]) -> dict[str, Any]:
    smoke = load_json(SMOKE_MANIFEST_PATH)
    failures = []
    if smoke.get("status") != "PASS":
        failures.append("smoke status is not PASS")
    if smoke.get("window_tag") != WINDOW_TAG:
        failures.append("smoke window tag mismatch")
    if smoke.get("builder", {}).get("sha256") != sha256(Path(__file__)):
        failures.append("builder changed after smoke")
    if smoke.get("stage1a_manifest_sha256") != context["manifest_sha256"]:
        failures.append("Stage-1A manifests changed after smoke")
    if smoke.get("ordinary_raw_sha256") != context["ordinary_sha256"]:
        failures.append("ordinary raw changed after smoke")
    current_supgp = {item["path"]: item["sha256"] for item in context["reference_files"]}
    if smoke.get("supgp_raw_sha256") != current_supgp:
        failures.append("SupGP raw changed after smoke")
    protected_now = april_protected_inventory()
    if smoke.get("april_protection", {}).get("aggregate_sha256") != protected_now["aggregate_sha256"]:
        failures.append("April protected artifacts changed after smoke")
    for key in ["crosscheck", "correctness"]:
        item = smoke.get("outputs", {}).get(key, {})
        path = normalize_path(item.get("path", ""))
        if not path.exists() or sha256(path) != item.get("sha256"):
            failures.append(f"smoke {key} output binding failed")
    if failures:
        raise SystemExit(f"Formal run blocked by smoke precondition: {failures}")
    return smoke


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def descriptive(values: list[float], prefix: str) -> dict[str, float | str]:
    if not values:
        return {
            f"{prefix}_min": "", f"{prefix}_median": "", f"{prefix}_p90": "",
            f"{prefix}_p95": "", f"{prefix}_max": "",
        }
    return {
        f"{prefix}_min": min(values),
        f"{prefix}_median": statistics.median(values),
        f"{prefix}_p90": percentile(values, 90),
        f"{prefix}_p95": percentile(values, 95),
        f"{prefix}_max": max(values),
    }


def build_summary(rows: list[dict[str, Any]], cohort: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for norad in cohort:
        satellite_rows = [row for row in rows if row["NORAD_CAT_ID"] == norad]
        nominal = [row for row in satellite_rows if bool(row["nominal_row"])]
        position = [float(row["position_error_norm_km"]) for row in nominal]
        velocity = [float(row["velocity_error_norm_km_s"]) for row in nominal]
        element_age = [float(row["element_age_seconds"]) for row in nominal]
        publication_age = [float(row["publication_age_seconds"]) for row in nominal]
        rms = [float(row["supgp_rms_km"]) for row in nominal]
        summary: dict[str, Any] = {
            "window_tag": WINDOW_TAG,
            "NORAD_CAT_ID": norad,
            "object_name": satellite_rows[0]["object_name"] if satellite_rows else "",
            "row_count": len(satellite_rows),
            "nominal_rows": len(nominal),
            "excluded_rows": len(satellite_rows) - len(nominal),
        }
        summary.update(descriptive(position, "position_error_norm_km"))
        summary.update(descriptive(velocity, "velocity_error_norm_km_s"))
        summary.update(descriptive(element_age, "element_age_seconds"))
        summary.update(descriptive(publication_age, "publication_age_seconds"))
        rms_desc = descriptive(rms, "supgp_rms_km")
        summary.update({key: value for key, value in rms_desc.items() if not key.endswith("_p90") and not key.endswith("_p95")})
        output.append(summary)
    return output


def relative_error(abs_error: float, reference: float) -> float:
    return abs_error / max(abs(reference), np.finfo(float).tiny)


def freshness_bin_label(age_hours: float) -> str:
    for lower, upper in zip((0.0, 6.0, 9.0, 12.0, 18.0, 24.0), (6.0, 9.0, 12.0, 18.0, 24.0, 36.0)):
        if lower < age_hours <= upper:
            return f"{lower:g}-{upper:g}h"
    return "OUTSIDE_SUPPORT"


def deterministic_correctness_sample(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nominal = sorted(
        (row for row in rows if bool(row["nominal_row"])),
        key=lambda row: (int(row["NORAD_CAT_ID"]), parse_utc(row["evaluation_time"])),
    )
    by_satellite: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in nominal:
        by_satellite[str(row["NORAD_CAT_ID"])].append(row)
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for sat_rows in by_satellite.values():
        for index in (0, len(sat_rows) // 2, len(sat_rows) - 1):
            row = sat_rows[index]
            selected[(row["NORAD_CAT_ID"], row["evaluation_time"])] = row
    for row in nominal:
        if bool(row["engineering_staleness_gt72h"]):
            selected[(row["NORAD_CAT_ID"], row["evaluation_time"])] = row
    for wanted_bin in ("0-6h", "6-9h", "9-12h", "12-18h", "18-24h", "24-36h"):
        candidate = next(
            (
                row
                for row in nominal
                if freshness_bin_label(float(row["element_age_hours"])) == wanted_bin
            ),
            None,
        )
        if candidate is not None:
            selected[(candidate["NORAD_CAT_ID"], candidate["evaluation_time"])] = candidate
    sample = sorted(selected.values(), key=lambda row: (parse_utc(row["evaluation_time"]), int(row["NORAD_CAT_ID"])))
    bin_counts = Counter(freshness_bin_label(float(row["element_age_hours"])) for row in sample)
    metadata = [
        {
            "NORAD_CAT_ID": row["NORAD_CAT_ID"],
            "evaluation_time": row["evaluation_time"],
            "freshness_bin": freshness_bin_label(float(row["element_age_hours"])),
            "stage1f_support_status": row["stage1f_support_status"],
            "engineering_staleness_gt72h": bool(row["engineering_staleness_gt72h"]),
        }
        for row in sample
    ]
    return {
        "selection_rule": "per-satellite earliest/middle/latest union all >72h rows union first available row in each frozen support bin",
        "row_count": len(sample),
        "satellite_count": len({row["NORAD_CAT_ID"] for row in sample}),
        "freshness_bin_counts": dict(sorted(bin_counts.items())),
        "gt36_rows": sum(float(row["element_age_hours"]) > 36.0 for row in sample),
        "gt72_rows": sum(bool(row["engineering_staleness_gt72h"]) for row in sample),
        "early_middle_late_month_covered": all(
            any(
                (1 <= parse_utc(row["evaluation_time"]).day <= 10) if segment == "early" else
                (11 <= parse_utc(row["evaluation_time"]).day <= 20) if segment == "middle" else
                (21 <= parse_utc(row["evaluation_time"]).day <= 30)
                for row in sample
            )
            for segment in ("early", "middle", "late")
        ),
        "max_rtn_orthonormality_error": max(float(row["rtn_orthonormality_error"]) for row in sample),
        "max_position_reconstruction_error_km": max(float(row["position_rtn_reconstruction_abs_error_km"]) for row in sample),
        "max_velocity_reconstruction_error_km_s": max(float(row["velocity_rtn_reconstruction_abs_error_km_s"]) for row in sample),
        "all_propagation_frame_rtn_finite_ok": all(
            row["ordinary_sgp4_status"] == "OK"
            and row["supgp_sgp4_status"] == "OK"
            and str(row["frame_transform_status"]).startswith("OK")
            and row["rtn_status"] == "OK"
            and row["finite_state_status"] == "FINITE"
            for row in sample
        ),
        "rows": metadata,
    }


def correctness_audit(
    rows: list[dict[str, Any]],
    references: list[dict[str, Any]],
    context: dict[str, Any],
    smoke: dict[str, Any],
    iers_info: dict[str, Any],
    input_hashes_before: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    nominal = [row for row in rows if bool(row["nominal_row"])]
    failures = [row for row in rows if not bool(row["nominal_row"])]
    future = sum(parse_utc(row["ordinary_gp_creation_date"]) > parse_utc(row["evaluation_time"]) for row in nominal)
    negative_element = sum(float(row["element_age_seconds"]) < 0 for row in nominal)
    age_gt = sum(float(row["element_age_seconds"]) > LOOKBACK_HOURS * 3600.0 for row in nominal)
    negative_publication = sum(float(row["publication_age_seconds"]) < 0 for row in nominal)
    source_keys = {(row["supgp_source_file"], int(row["supgp_source_row_index"])) for row in rows}
    expected_keys = {(row["_source_file"], int(row["_source_row_index"])) for row in references}
    provenance_missing = sum(
        not all(str(row.get(field, "")) for field in [
            "window_tag", "NORAD_CAT_ID", "evaluation_time", "ordinary_gp_id",
            "ordinary_gp_epoch", "ordinary_gp_creation_date", "ordinary_raw_file",
            "ordinary_raw_sha256", "supgp_source_file", "supgp_source_row_index",
            "supgp_source_file_sha256", "supgp_epoch",
        ])
        for row in nominal
    )
    finite_failures = sum(
        not all(math.isfinite(float(row[field])) for field in [
            "delta_R_km", "delta_T_km", "delta_N_km",
            "delta_v_R_km_s", "delta_v_T_km_s", "delta_v_N_km_s",
            "position_error_norm_km", "velocity_error_norm_km_s",
            "delta_x_common_km", "delta_y_common_km", "delta_z_common_km",
            "delta_vx_common_km_s", "delta_vy_common_km_s", "delta_vz_common_km_s",
        ])
        for row in nominal
    )
    max_position_abs = max((float(row["position_rtn_reconstruction_abs_error_km"]) for row in nominal), default=math.inf)
    max_velocity_abs = max((float(row["velocity_rtn_reconstruction_abs_error_km_s"]) for row in nominal), default=math.inf)
    max_position_rel = max((relative_error(float(row["position_rtn_reconstruction_abs_error_km"]), float(row["position_error_norm_km"])) for row in nominal), default=math.inf)
    max_velocity_rel = max((relative_error(float(row["velocity_rtn_reconstruction_abs_error_km_s"]), float(row["velocity_error_norm_km_s"])) for row in nominal), default=math.inf)
    max_cart_position = max((float(row["cartesian_rtn_position_norm_abs_error_km"]) for row in nominal), default=math.inf)
    max_cart_velocity = max((float(row["cartesian_rtn_velocity_norm_abs_error_km_s"]) for row in nominal), default=math.inf)
    max_orthonormality = max((float(row["rtn_orthonormality_error"]) for row in nominal), default=math.inf)
    max_unit_norm_error = max(
        (
            max(
                float(row["rtn_R_unit_norm_error"]),
                float(row["rtn_T_unit_norm_error"]),
                float(row["rtn_N_unit_norm_error"]),
            )
            for row in nominal
        ),
        default=math.inf,
    )
    max_dot_product = max(
        (
            max(
                abs(float(row["rtn_R_dot_T"])),
                abs(float(row["rtn_R_dot_N"])),
                abs(float(row["rtn_T_dot_N"])),
            )
            for row in nominal
        ),
        default=math.inf,
    )
    max_right_handedness_error = max(
        (float(row["rtn_right_handedness_error"]) for row in nominal), default=math.inf
    )
    evaluation_mismatch = sum(row["evaluation_time"] != row["supgp_epoch"] for row in rows)
    stage1a_by_key = {
        (str(row["NORAD_CAT_ID"]), iso_z(row["evaluation_time"])): row
        for row in context["causal_rows"]
    }
    output_by_key = {(str(row["NORAD_CAT_ID"]), row["evaluation_time"]): row for row in rows}
    stage1a_key_mismatch = len(set(stage1a_by_key).symmetric_difference(output_by_key))
    selected_gp_mismatch = 0
    selected_epoch_mismatch = 0
    selected_creation_mismatch = 0
    max_element_age_audit_diff = 0.0
    max_publication_age_audit_diff = 0.0
    for key in set(stage1a_by_key).intersection(output_by_key):
        expected = stage1a_by_key[key]
        actual = output_by_key[key]
        selected_gp_mismatch += str(actual["ordinary_gp_id"]) != str(expected["selected_gp_id"])
        selected_epoch_mismatch += actual["ordinary_gp_epoch"] != iso_z(expected["selected_gp_epoch"])
        selected_creation_mismatch += actual["ordinary_gp_creation_date"] != iso_z(expected["selected_gp_creation_date"])
        max_element_age_audit_diff = max(
            max_element_age_audit_diff,
            abs(float(actual["element_age_seconds"]) - float(expected["gp_age_seconds"])),
        )
        max_publication_age_audit_diff = max(
            max_publication_age_audit_diff,
            abs(float(actual["publication_age_seconds"]) - float(expected["publication_age_seconds"])),
        )
    element_age_gt_36h = sum(float(row["element_age_seconds"]) > APRIL_CALIBRATED_FRESHNESS_SECONDS for row in nominal)
    within_stage1f_support = sum(bool(row["within_stage1f_support"]) for row in nominal)
    outside_stage1f_support = sum(row["stage1f_support_status"] == "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT" for row in nominal)
    engineering_gt72_flags = sum(bool(row["engineering_staleness_gt72h"]) for row in nominal)
    gt72_subset_outside = all(
        not bool(row["engineering_staleness_gt72h"])
        or row["stage1f_support_status"] == "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT"
        for row in nominal
    )
    stage1a_element_age_gt_36h = sum(
        float(row["gp_age_seconds"]) > APRIL_CALIBRATED_FRESHNESS_SECONDS for row in context["causal_rows"]
    )
    propagation_failures = sum(
        row["ordinary_sgp4_status"] == "ERROR" or row["supgp_sgp4_status"] == "ERROR" for row in rows
    )
    frame_transform_failures = sum(row["frame_transform_status"] == "ERROR" for row in rows)
    invalid_rtn_basis = sum(row["rtn_status"] == "ERROR" for row in rows)
    pause = context.get("archive_pause", {})
    pause_start_text = pause.get("longest_all_cohort_between_record_interval_start", "")
    pause_day_rows = 0
    stage1a_pause_day_rows = 0
    if pause_start_text:
        pause_date = parse_utc(pause_start_text).date()
        pause_day_rows = sum(parse_utc(row["evaluation_time"]).date() == pause_date for row in rows)
        stage1a_pause_day_rows = sum(
            parse_utc(row["evaluation_time"]).date() == pause_date for row in context["causal_rows"]
        )
    input_hashes_after = current_input_hashes(context)
    raw_unchanged = input_hashes_before == input_hashes_after
    sample = deterministic_correctness_sample(rows)
    readiness_v2_enabled = bool(context.get("readiness_v2_enabled"))
    age_readiness_pass = negative_element == 0 and (readiness_v2_enabled or age_gt == 0)
    expected_v2 = context.get("readiness_v2", {}).get("manifest", {}).get("june", {})
    v2_counts_match = not readiness_v2_enabled or (
        within_stage1f_support == int(expected_v2.get("stage1f_primary_confirmatory_rows", -1))
        and outside_stage1f_support == int(expected_v2.get("stage1f_outside_support_rows", -1))
        and age_gt == int(expected_v2.get("element_age_gt72_rows", -1))
    )

    metrics = {
        "rows": len(rows),
        "nominal_rows": len(nominal),
        "excluded_rows": len(failures),
        "future_publication_violations": future,
        "negative_element_age": negative_element,
        "element_age_gt_72h": age_gt,
        "negative_publication_age": negative_publication,
        "evaluation_supgp_epoch_mismatch": evaluation_mismatch,
        "stage1a_causal_key_mismatch": stage1a_key_mismatch,
        "selected_gp_id_mismatch": selected_gp_mismatch,
        "selected_gp_epoch_mismatch": selected_epoch_mismatch,
        "selected_gp_creation_date_mismatch": selected_creation_mismatch,
        "max_element_age_stage1a_abs_diff_seconds": max_element_age_audit_diff,
        "max_publication_age_stage1a_abs_diff_seconds": max_publication_age_audit_diff,
        "element_age_gt_36h": element_age_gt_36h,
        "within_stage1f_support_rows": within_stage1f_support,
        "outside_stage1f_support_rows": outside_stage1f_support,
        "engineering_staleness_gt72h_rows": engineering_gt72_flags,
        "gt72_subset_of_outside_stage1f_support": gt72_subset_outside,
        "stage1a_element_age_gt_36h": stage1a_element_age_gt_36h,
        "propagation_failure_rows": propagation_failures,
        "frame_transform_failure_rows": frame_transform_failures,
        "invalid_rtn_basis_rows": invalid_rtn_basis,
        "archive_pause_calendar_day_evaluation_rows": pause_day_rows,
        "stage1a_archive_pause_calendar_day_evaluation_rows": stage1a_pause_day_rows,
        "provenance_missing_rows": provenance_missing,
        "finite_failure_rows": finite_failures,
        "max_position_rtn_reconstruction_abs_error_km": max_position_abs,
        "max_position_rtn_reconstruction_relative_error": max_position_rel,
        "max_velocity_rtn_reconstruction_abs_error_km_s": max_velocity_abs,
        "max_velocity_rtn_reconstruction_relative_error": max_velocity_rel,
        "max_cartesian_rtn_position_norm_error_km": max_cart_position,
        "max_cartesian_rtn_velocity_norm_error_km_s": max_cart_velocity,
        "max_rtn_orthonormality_error": max_orthonormality,
        "max_rtn_unit_norm_error": max_unit_norm_error,
        "max_rtn_pairwise_dot_abs": max_dot_product,
        "max_rtn_right_handedness_error": max_right_handedness_error,
        "input_raw_hashes_unchanged": raw_unchanged,
        "deterministic_correctness_sample": sample,
    }
    audit = [
        {"check": "Stage-1A manifests and raw verified", "passed": context["verified_check_count"] > 0, "observed": f"checks={context['verified_check_count']}"},
        {"check": "smoke validation bound and passed", "passed": smoke.get("status") == "PASS", "observed": f"cases={smoke.get('case_count')}; max_diff={smoke.get('max_numeric_abs_difference')}"},
        {"check": "formal row completeness", "passed": len(rows) == len(references) == EXPECTED_FORMAL_ROWS, "observed": f"dataset={len(rows)}; raw_reference={len(references)}"},
        {"check": "all formal rows nominal", "passed": len(failures) == 0, "observed": f"nominal={len(nominal)}; excluded={len(failures)}"},
        {"check": "causal publication constraint", "passed": future == 0 and negative_publication == 0, "observed": f"future={future}; negative_publication_age={negative_publication}"},
        {"check": "ordinary element age causal-readiness semantics", "passed": age_readiness_pass, "observed": f"protocol={CAUSAL_DATA_READINESS_V2 if readiness_v2_enabled else 'LEGACY'}; negative={negative_element}; gt72h={age_gt}; gt72_is_blocker={not readiness_v2_enabled}"},
        {"check": "evaluation epochs directly trace raw SupGP", "passed": source_keys == expected_keys and evaluation_mismatch == 0, "observed": f"source_keys={len(source_keys)}; expected={len(expected_keys)}; epoch_mismatch={evaluation_mismatch}"},
        {"check": "Stage-1A causal audit row/key agreement", "passed": stage1a_key_mismatch == 0 and len(stage1a_by_key) == EXPECTED_FORMAL_ROWS, "observed": f"stage1a_rows={len(stage1a_by_key)}; key_mismatch={stage1a_key_mismatch}"},
        {"check": "Stage-1A selected GP_ID agreement", "passed": selected_gp_mismatch == 0, "observed": f"matched={len(output_by_key) - selected_gp_mismatch}/{len(output_by_key)}; mismatch={selected_gp_mismatch}"},
        {"check": "Stage-1A selected GP timestamps agreement", "passed": selected_epoch_mismatch == 0 and selected_creation_mismatch == 0, "observed": f"epoch_mismatch={selected_epoch_mismatch}; creation_mismatch={selected_creation_mismatch}"},
        {"check": "Stage-1A freshness values agreement", "passed": max_element_age_audit_diff <= 1e-6 and max_publication_age_audit_diff <= 1e-6, "observed": f"element_max_abs_diff_s={max_element_age_audit_diff}; publication_max_abs_diff_s={max_publication_age_audit_diff}"},
        {"check": ">36h rows retained exactly", "passed": element_age_gt_36h == stage1a_element_age_gt_36h, "observed": f"dataset={element_age_gt_36h}; stage1a={stage1a_element_age_gt_36h}"},
        {"check": "Stage-1F support metadata counts", "passed": v2_counts_match and within_stage1f_support + outside_stage1f_support == len(nominal), "observed": f"within={within_stage1f_support}; outside={outside_stage1f_support}; expected_match={v2_counts_match}"},
        {"check": ">72h engineering staleness preserved and outside support", "passed": engineering_gt72_flags == age_gt and gt72_subset_outside, "observed": f"age_gt72={age_gt}; flags={engineering_gt72_flags}; subset={gt72_subset_outside}"},
        {"check": "propagation/frame/RTN failures zero", "passed": propagation_failures == 0 and frame_transform_failures == 0 and invalid_rtn_basis == 0, "observed": f"propagation={propagation_failures}; frame={frame_transform_failures}; rtn={invalid_rtn_basis}"},
        {"check": "archive pause provenance preserves real evaluation rows", "passed": not pause_start_text or (pause_day_rows == stage1a_pause_day_rows and (WINDOW_TAG != "20260501_20260531" or pause_day_rows == 17)), "observed": f"pause_start={pause_start_text}; dataset_calendar_day_rows={pause_day_rows}; stage1a_calendar_day_rows={stage1a_pause_day_rows}; interpolation_or_fill=false"},
        {"check": "position RTN reconstruction", "passed": max_position_abs <= NUMERIC_ABS_TOL and max_position_rel <= NUMERIC_REL_TOL, "observed": f"max_abs={max_position_abs}; max_rel={max_position_rel}"},
        {"check": "velocity RTN reconstruction", "passed": max_velocity_abs <= NUMERIC_ABS_TOL and max_velocity_rel <= NUMERIC_REL_TOL, "observed": f"max_abs={max_velocity_abs}; max_rel={max_velocity_rel}"},
        {"check": "Cartesian/RTN norm invariance", "passed": max_cart_position <= NUMERIC_ABS_TOL and max_cart_velocity <= NUMERIC_ABS_TOL, "observed": f"position={max_cart_position}; velocity={max_cart_velocity}"},
        {"check": "RTN orthonormality", "passed": max_orthonormality <= ORTHONORMAL_TOL, "observed": f"max_error={max_orthonormality}"},
        {"check": "RTN unit norms and pairwise dots", "passed": max_unit_norm_error <= ORTHONORMAL_TOL and max_dot_product <= ORTHONORMAL_TOL, "observed": f"max_unit_norm_error={max_unit_norm_error}; max_dot_abs={max_dot_product}"},
        {"check": "RTN right-handedness", "passed": max_right_handedness_error <= ORTHONORMAL_TOL, "observed": f"max_error={max_right_handedness_error}"},
        {"check": "deterministic correctness sample", "passed": sample["row_count"] >= 25 and sample["satellite_count"] == 20 and sample["gt36_rows"] > 0 and sample["gt72_rows"] > 0 and sample["early_middle_late_month_covered"] and len(sample["freshness_bin_counts"]) >= 4 and sample["all_propagation_frame_rtn_finite_ok"], "observed": f"rows={sample['row_count']}; satellites={sample['satellite_count']}; bins={sample['freshness_bin_counts']}; gt36={sample['gt36_rows']}; gt72={sample['gt72_rows']}; time_covered={sample['early_middle_late_month_covered']}"},
        {"check": "finite nominal values", "passed": finite_failures == 0, "observed": f"nonfinite_rows={finite_failures}"},
        {"check": "row provenance complete", "passed": provenance_missing == 0, "observed": f"missing_rows={provenance_missing}"},
        {"check": "failure audit complete", "passed": len(failures) == sum(not bool(row["nominal_row"]) for row in rows), "observed": f"failure_rows={len(failures)}"},
        {"check": "IERS covers formal window", "passed": bool(iers_info["formal_window_covered"]), "observed": json.dumps(iers_info)},
        {"check": "input raw hashes unchanged during build", "passed": raw_unchanged, "observed": f"unchanged={raw_unchanged}"},
    ]
    return audit, metrics


def current_input_hashes(context: dict[str, Any]) -> dict[str, str]:
    values = {context["ordinary_path"].as_posix(): sha256(context["ordinary_path"])}
    for item in context["reference_files"]:
        path = normalize_path(item["path"])
        values[path.as_posix()] = sha256(path)
    return values


def failure_rows(dataset_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in dataset_rows if not bool(row["nominal_row"])]


def overall_descriptive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nominal = [row for row in rows if bool(row["nominal_row"])]
    output: dict[str, Any] = {}
    output.update(descriptive([float(row["position_error_norm_km"]) for row in nominal], "position_error_norm_km"))
    output.update(descriptive([float(row["velocity_error_norm_km_s"]) for row in nominal], "velocity_error_norm_km_s"))
    output.update(descriptive([float(row["element_age_seconds"]) for row in nominal], "element_age_seconds"))
    output.update(descriptive([float(row["publication_age_seconds"]) for row in nominal], "publication_age_seconds"))
    output.update(descriptive([float(row["supgp_rms_km"]) for row in nominal], "supgp_rms_km"))
    for field, prefix in [
        ("delta_R_km", "abs_delta_R_km"),
        ("delta_T_km", "abs_delta_T_km"),
        ("delta_N_km", "abs_delta_N_km"),
        ("delta_v_R_km_s", "abs_delta_v_R_km_s"),
        ("delta_v_T_km_s", "abs_delta_v_T_km_s"),
        ("delta_v_N_km_s", "abs_delta_v_N_km_s"),
    ]:
        output.update(descriptive([abs(float(row[field])) for row in nominal], prefix))
    return output


def directional_dominance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    nominal = [row for row in rows if str(row.get("nominal_row", "")).lower() in {"true", "1"} or row.get("nominal_row") is True]
    position_medians = {
        axis: statistics.median(abs(float(row[f"delta_{axis}_km"])) for row in nominal)
        for axis in ["R", "T", "N"]
    }
    velocity_medians = {
        axis: statistics.median(abs(float(row[f"delta_v_{axis}_km_s"])) for row in nominal)
        for axis in ["R", "T", "N"]
    }
    return {
        "position_median_abs_components_km": position_medians,
        "position_dominant_median_abs_axis": max(position_medians, key=position_medians.get),
        "velocity_median_abs_components_km_s": velocity_medians,
        "velocity_dominant_median_abs_axis": max(velocity_medians, key=velocity_medians.get),
    }


def april_may_descriptive_comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if sha256(APRIL_DATASET_PATH) != APRIL_DATASET_SHA256:
        raise SystemExit("April canonical dataset changed before descriptive comparison")
    april_rows = load_csv(APRIL_DATASET_PATH)
    april_values = overall_descriptive(april_rows)
    may_values = overall_descriptive(rows)
    return {
        "semantics": "descriptive sanity comparison only; not external validation and not model calibration",
        "april": {
            "row_count": len(april_rows),
            "dataset_sha256": APRIL_DATASET_SHA256,
            "descriptive": april_values,
            "directional_dominance": directional_dominance(april_rows),
        },
        "current_window": {
            "window_tag": WINDOW_TAG,
            "row_count": len(rows),
            "descriptive": may_values,
            "directional_dominance": directional_dominance(rows),
        },
    }


def markdown_report(
    status: str,
    rows: list[dict[str, Any]],
    summary: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    metrics: dict[str, Any],
    descriptive_values: dict[str, Any],
    context: dict[str, Any],
    comparison: dict[str, Any],
) -> str:
    passed = sum(bool(row["passed"]) for row in audit)
    summary_table = pd.DataFrame(summary)[[
        "NORAD_CAT_ID", "row_count", "nominal_rows",
        "position_error_norm_km_median", "position_error_norm_km_max",
        "velocity_error_norm_km_s_median", "velocity_error_norm_km_s_max",
        "element_age_seconds_median", "publication_age_seconds_median", "supgp_rms_km_median",
    ]].to_markdown(index=False)
    audit_table = pd.DataFrame(audit).to_markdown(index=False)
    april_desc = comparison["april"]["descriptive"]
    current_dominance = comparison["current_window"]["directional_dominance"]
    april_dominance = comparison["april"]["directional_dominance"]
    pause = context.get("archive_pause", {})
    return f"""# Orbit Uncertainty Stage-1B {WINDOW_TAG} causal 6D RTN residual library

## 1. 状态与范围

状态：`{status}`。窗口：`{FORMAL_INTERVAL}`；window tag：`{WINDOW_TAG}`；cohort：20颗。生成{len(rows)}行，其中nominal={metrics['nominal_rows']}、excluded={metrics['excluded_rows']}。

本数据集表示ordinary-GP prediction相对operator-derived higher-quality SupGP reference的state disagreement。它不是ground-truth error或true orbit error。本轮没有建立uncertainty boundary、没有根据residual/RMS删除记录，也没有运行synthetic B或Doppler verifier。

## 2. 输入与方法

- ordinary GP：`{context['ordinary_path'].as_posix()}`，SHA256=`{context['ordinary_sha256']}`。
- SupGP：`{SUPGP_DIR.as_posix()}/*.csv`，20文件/{len(rows)}记录，逐文件SHA见manifest。
- Stage-1A inputs：ordinary acquisition、SupGP reference-quality、causal-support audit与冻结cohort selection均已核对window tag、cohort、record count与SHA；April运行仍额外绑定design manifest。
- causal selection：只允许`CREATION_DATE <= evaluation_time`，依次取latest CREATION_DATE、latest EPOCH、latest GP_ID。
- ordinary使用Space-Track OMM JSON内嵌的`TLE_LINE1/2`通过`Satrec.twoline2rv`初始化，严格复用Stage-0 Starlink数值口径；SupGP通过`sgp4.omm.initialize`初始化。两者均传播到同一SupGP EPOCH，native state为TEME。
- 两个state均通过Astropy从TEME转换到同一GCRS；以SupGP/reference GCRS state定义RTN basis；保存ordinary-reference的6D RTN与Cartesian delta。
- `element_age_seconds = evaluation_time - ordinary GP EPOCH`；`publication_age_seconds = evaluation_time - CREATION_DATE`；二者分别保存且不混用。

## 3. Correctness audit

{audit_table}

通过：{passed}/{len(audit)}。

## 4. 逐星描述性摘要

{summary_table}

完整min/median/p90/p95/max见`{SUMMARY_PATH.as_posix()}`。

## 5. Cohort描述性范围

- position disagreement norm km，min/median/p90/p95/max：{descriptive_values['position_error_norm_km_min']} / {descriptive_values['position_error_norm_km_median']} / {descriptive_values['position_error_norm_km_p90']} / {descriptive_values['position_error_norm_km_p95']} / {descriptive_values['position_error_norm_km_max']}
- velocity disagreement norm km/s，min/median/p90/p95/max：{descriptive_values['velocity_error_norm_km_s_min']} / {descriptive_values['velocity_error_norm_km_s_median']} / {descriptive_values['velocity_error_norm_km_s_p90']} / {descriptive_values['velocity_error_norm_km_s_p95']} / {descriptive_values['velocity_error_norm_km_s_max']}
- ordinary element age seconds，min/median/p90/p95/max：{descriptive_values['element_age_seconds_min']} / {descriptive_values['element_age_seconds_median']} / {descriptive_values['element_age_seconds_p90']} / {descriptive_values['element_age_seconds_p95']} / {descriptive_values['element_age_seconds_max']}
- ordinary publication age seconds，min/median/p90/p95/max：{descriptive_values['publication_age_seconds_min']} / {descriptive_values['publication_age_seconds_median']} / {descriptive_values['publication_age_seconds_p90']} / {descriptive_values['publication_age_seconds_p95']} / {descriptive_values['publication_age_seconds_max']}
- SupGP RMS km，min/median/max：{descriptive_values['supgp_rms_km_min']} / {descriptive_values['supgp_rms_km_median']} / {descriptive_values['supgp_rms_km_max']}
- position median/P90/P95/max absolute RTN km：R={descriptive_values['abs_delta_R_km_median']}/{descriptive_values['abs_delta_R_km_p90']}/{descriptive_values['abs_delta_R_km_p95']}/{descriptive_values['abs_delta_R_km_max']}；T={descriptive_values['abs_delta_T_km_median']}/{descriptive_values['abs_delta_T_km_p90']}/{descriptive_values['abs_delta_T_km_p95']}/{descriptive_values['abs_delta_T_km_max']}；N={descriptive_values['abs_delta_N_km_median']}/{descriptive_values['abs_delta_N_km_p90']}/{descriptive_values['abs_delta_N_km_p95']}/{descriptive_values['abs_delta_N_km_max']}。
- velocity median/P90/P95/max absolute RTN km/s：vR={descriptive_values['abs_delta_v_R_km_s_median']}/{descriptive_values['abs_delta_v_R_km_s_p90']}/{descriptive_values['abs_delta_v_R_km_s_p95']}/{descriptive_values['abs_delta_v_R_km_s_max']}；vT={descriptive_values['abs_delta_v_T_km_s_median']}/{descriptive_values['abs_delta_v_T_km_s_p90']}/{descriptive_values['abs_delta_v_T_km_s_p95']}/{descriptive_values['abs_delta_v_T_km_s_max']}；vN={descriptive_values['abs_delta_v_N_km_s_median']}/{descriptive_values['abs_delta_v_N_km_s_p90']}/{descriptive_values['abs_delta_v_N_km_s_p95']}/{descriptive_values['abs_delta_v_N_km_s_max']}。

以上仅为canonical dataset construction的描述性统计，不是uncertainty threshold、confidence interval或质量cutoff。

## 6. April与当前窗口的有限描述性比较

| 指标 | April | {WINDOW_TAG} |
|---|---:|---:|
| rows | {comparison['april']['row_count']} | {comparison['current_window']['row_count']} |
| position norm median km | {april_desc['position_error_norm_km_median']} | {descriptive_values['position_error_norm_km_median']} |
| position norm P90 km | {april_desc['position_error_norm_km_p90']} | {descriptive_values['position_error_norm_km_p90']} |
| position norm P95 km | {april_desc['position_error_norm_km_p95']} | {descriptive_values['position_error_norm_km_p95']} |
| position norm max km | {april_desc['position_error_norm_km_max']} | {descriptive_values['position_error_norm_km_max']} |
| velocity norm median km/s | {april_desc['velocity_error_norm_km_s_median']} | {descriptive_values['velocity_error_norm_km_s_median']} |
| velocity norm P95 km/s | {april_desc['velocity_error_norm_km_s_p95']} | {descriptive_values['velocity_error_norm_km_s_p95']} |
| velocity norm max km/s | {april_desc['velocity_error_norm_km_s_max']} | {descriptive_values['velocity_error_norm_km_s_max']} |
| element age median/P95/max h | {april_desc['element_age_seconds_median']/3600.0}/{april_desc['element_age_seconds_p95']/3600.0}/{april_desc['element_age_seconds_max']/3600.0} | {descriptive_values['element_age_seconds_median']/3600.0}/{descriptive_values['element_age_seconds_p95']/3600.0}/{descriptive_values['element_age_seconds_max']/3600.0} |
| publication age median/P95/max h | {april_desc['publication_age_seconds_median']/3600.0}/{april_desc['publication_age_seconds_p95']/3600.0}/{april_desc['publication_age_seconds_max']/3600.0} | {descriptive_values['publication_age_seconds_median']/3600.0}/{descriptive_values['publication_age_seconds_p95']/3600.0}/{descriptive_values['publication_age_seconds_max']/3600.0} |
| median absolute position dominant axis | {april_dominance['position_dominant_median_abs_axis']} | {current_dominance['position_dominant_median_abs_axis']} |
| median absolute velocity dominant axis | {april_dominance['velocity_dominant_median_abs_axis']} | {current_dominance['velocity_dominant_median_abs_axis']} |

该表只是sanity/descriptive comparison，不是April frozen model对May的external validation，不据此判断模型成功或失败。

## 7. 必答审计结论

1. canonical rows：输入{len(rows)}条SupGP，输出{metrics['rows']}条6D RTN rows，nominal={metrics['nominal_rows']}，excluded={metrics['excluded_rows']}。
2. Stage-1A selected GP_ID：mismatch={metrics['selected_gp_id_mismatch']}，匹配={metrics['rows'] - metrics['selected_gp_id_mismatch']}/{metrics['rows']}。
3. future publication use={metrics['future_publication_violations']}；selected GP epoch after evaluation={metrics['negative_element_age']}；negative publication/element age={metrics['negative_publication_age']}/{metrics['negative_element_age']}；element age >72 h={metrics['element_age_gt_72h']}。
4. propagation/frame/invalid RTN/nonfinite failures={metrics['propagation_failure_rows']}/{metrics['frame_transform_failure_rows']}/{metrics['invalid_rtn_basis_rows']}/{metrics['finite_failure_rows']}。
5. position RTN→Cartesian reconstruction最大误差={metrics['max_position_rtn_reconstruction_abs_error_km']} km。
6. velocity RTN→Cartesian reconstruction最大误差={metrics['max_velocity_rtn_reconstruction_abs_error_km_s']} km/s。
7. Cartesian/RTN norm最大差异：position={metrics['max_cartesian_rtn_position_norm_error_km']} km，velocity={metrics['max_cartesian_rtn_velocity_norm_error_km_s']} km/s。
8. element age >36 h：dataset={metrics['element_age_gt_36h']}，Stage-1A audit={metrics['stage1a_element_age_gt_36h']}；全部保留，不外推April 0–36 h calibration。
9. May相对April的数值变化只按上一节描述，不执行或暗示external validation。
10. reference availability pause：{pause.get('longest_all_cohort_between_record_interval_start', '')}至{pause.get('longest_all_cohort_between_record_interval_end', '')}，{pause.get('longest_all_cohort_between_record_interval_hours', '')} h；当日真实evaluation rows={metrics['archive_pause_calendar_day_evaluation_rows']}，没有插值、填补或规则网格构造。
11. April protected artifacts在formal manifest中保存运行前后81项aggregate fingerprint；canonical Stage-1B SHA固定为`{APRIL_DATASET_SHA256}`。

## 8. 输出与局限

- dataset：`{DATASET_PATH.as_posix()}`
- per-satellite summary：`{SUMMARY_PATH.as_posix()}`
- correctness audit：`{CORRECTNESS_PATH.as_posix()}`
- failure audit：`{FAILURE_PATH.as_posix()}`
- manifest：`{MANIFEST_PATH.as_posix()}`

SupGP是operator-derived higher-quality reference的SGP4-compatible representation；residual同时包含ordinary prediction disagreement与reference representation/model差异。本轮不解释极值成因、不做maneuver/regime filtering，也不定义合法轨道不确定性边界。
"""


def construction_only_report(
    status: str,
    rows: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    metrics: dict[str, Any],
    context: dict[str, Any],
    failure_counts: dict[str, int],
) -> str:
    passed = sum(bool(row["passed"]) for row in audit)
    audit_table = pd.DataFrame(audit).to_markdown(index=False)
    sample = metrics["deterministic_correctness_sample"]
    readiness = context["readiness_v2"]
    return f"""# Orbit Uncertainty Stage-1B {WINDOW_TAG} canonical 6D RTN residual library

## 1. Inputs / provenance

状态：`{status}`。Formal window：`{FORMAL_INTERVAL}`。Cohort：20颗。

- ordinary GP raw：`{context['ordinary_path'].as_posix()}`，SHA256=`{context['ordinary_sha256']}`。
- SupGP reference：`{SUPGP_DIR.as_posix()}/*.csv`，20 files / {len(rows)} rows；逐文件SHA由formal reference manifest绑定。
- Stage-1A acquisition manifest：`{ACQUISITION_MANIFEST.as_posix()}`。
- causal support audit：`{context['causal_path'].as_posix()}`。
- readiness amendment：`{readiness['path'].as_posix()}`，SHA256=`{readiness['sha256']}`，protocol=`{CAUSAL_DATA_READINESS_V2}`。
- frozen cohort SHA256=`{context['selection_sha256']}`。
- Stage-1F frozen parameter SHA256=`{readiness['parameter_sha256']}`，本轮仅作protected dependency fingerprint，未读取参数值或用于打分。

本数据集表示ordinary public GP propagated state相对SpaceX-E/SupGP higher-quality historical reference的empirical disagreement，不是ground truth或true orbit-error covariance。

## 2. Causal selection reproduction

每个evaluation仅允许`CREATION_DATE <= evaluation_time`的ordinary GP，并按latest `CREATION_DATE` → latest `EPOCH` → `GP_ID`确定性选择。Stage-1B重新执行同一selector，并逐行与冻结Stage-1A audit核对：GP_ID matched={metrics['rows'] - metrics['selected_gp_id_mismatch']}/{metrics['rows']}；epoch mismatch={metrics['selected_gp_epoch_mismatch']}；creation mismatch={metrics['selected_gp_creation_date_mismatch']}；element/publication age最大差={metrics['max_element_age_stage1a_abs_diff_seconds']}/{metrics['max_publication_age_stage1a_abs_diff_seconds']} s。

## 3. Row accounting

- input SupGP rows：{len(rows)}
- canonical output rows：{metrics['rows']}
- nominal rows：{metrics['nominal_rows']}
- excluded rows：{metrics['excluded_rows']}
- propagation failures：{metrics['propagation_failure_rows']}
- frame-conversion failures：{metrics['frame_transform_failure_rows']}
- RTN failures：{metrics['invalid_rtn_basis_rows']}
- nonfinite failures：{metrics['finite_failure_rows']}
- excluded reasons：{failure_counts}

没有因freshness、RMS、residual magnitude或episode删除、截断、插值或替换任何row。

## 4. Frame / RTN method

ordinary OMM内嵌TLE和SupGP OMM均由与April/May相同的SGP4实现传播到共同UTC evaluation epoch，native frame为TEME，再由Astropy转换到GCRS。RTN basis由SupGP/reference GCRS position/velocity定义。Authoritative residual sign为：

`ordinary propagated state - SupGP/SpaceX-E reference state`

输出signed position `delta_R_km/delta_T_km/delta_N_km`、signed velocity `delta_v_R_km_s/delta_v_T_km_s/delta_v_N_km_s`及Cartesian-consistent norms。

## 5. Numerical correctness

{audit_table}

通过：{passed}/{len(audit)}。

- maximum RTN orthonormality error：{metrics['max_rtn_orthonormality_error']}
- maximum unit-norm error：{metrics['max_rtn_unit_norm_error']}
- maximum pairwise dot absolute value：{metrics['max_rtn_pairwise_dot_abs']}
- maximum right-handedness error：{metrics['max_rtn_right_handedness_error']}
- maximum position/velocity RTN reconstruction error：{metrics['max_position_rtn_reconstruction_abs_error_km']} km / {metrics['max_velocity_rtn_reconstruction_abs_error_km_s']} km/s
- maximum Cartesian/RTN norm difference：{metrics['max_cartesian_rtn_position_norm_error_km']} km / {metrics['max_cartesian_rtn_velocity_norm_error_km_s']} km/s

Fixed deterministic correctness sample：n={sample['row_count']}、satellites={sample['satellite_count']}、bins={sample['freshness_bin_counts']}、>36 h={sample['gt36_rows']}、>72 h={sample['gt72_rows']}，覆盖June early/middle/late。该sample仅用于frame/RTN/numerical checks；未作residual科学解释。

## 6. Freshness eligibility counts

- total canonical rows：{metrics['rows']}
- `WITHIN_STAGE1F_SUPPORT` (`0 < element_age_hours <= 36`)：{metrics['within_stage1f_support_rows']}
- `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`：{metrics['outside_stage1f_support_rows']}
- `ENGINEERING_STALENESS_GT72H=true`：{metrics['engineering_staleness_gt72h_rows']}
- GT72 subset of outside support：{metrics['engineering_staleness_gt72h_rows']}/{metrics['engineering_staleness_gt72h_rows']}

这些仅为eligibility accounting，不是Stage-1F performance result。全部538个outside-support rows均保留，其中25个>72 h rows保留为real causal public-data staleness。

## 7. Artifact SHA

- canonical dataset：`{DATASET_PATH.as_posix()}`，SHA256=`{sha256(DATASET_PATH)}`
- correctness audit：`{CORRECTNESS_PATH.as_posix()}`
- failure audit：`{FAILURE_PATH.as_posix()}`
- manifest：`{MANIFEST_PATH.as_posix()}`

April/May canonical、development artifacts、June Stage-1A/readiness及Stage-1F frozen artifacts的before/after fingerprint见manifest。

## 8. Blindness statement

本轮没有生成residual descriptive summary、figure、ranking、episode或April/May comparison；没有调用Stage-1F scoring code，没有读取frozen parameter values，没有计算ellipsoid D2、box S_inf、P95/P99 coverage、false-orbit-distinct rate或逐星confirmatory performance。Canonical residual仅用于完成Stage-1B construction及数值正确性审计。
"""


def run_formal_construction_only(
    context: dict[str, Any],
    references: list[dict[str, Any]],
    ordinary_by_norad: dict[str, list[dict[str, Any]]],
    reference_status: dict[str, str],
    iers_info: dict[str, Any],
) -> None:
    outputs = [DATASET_PATH, CORRECTNESS_PATH, FAILURE_PATH, MANIFEST_PATH, REPORT_PATH]
    ensure_outputs_available(outputs, ARGS.overwrite)
    if SUMMARY_PATH.exists():
        raise SystemExit(f"Construction-only firewall found a pre-existing June residual summary: {SUMMARY_PATH}")
    smoke = verify_smoke_precondition(context)
    input_hashes_before = current_input_hashes(context)
    frozen_before = readiness_v2_protected_inventory(context)
    rows = build_rows_batched(
        references,
        ordinary_by_norad,
        reference_status,
        context,
        progress=True,
    )
    audit, metrics = correctness_audit(rows, references, context, smoke, iers_info, input_hashes_before)
    failures = failure_rows(rows)
    failure_counts = dict(sorted(Counter(row["exclusion_reason"] or "UNSPECIFIED" for row in failures).items()))

    forbidden_output_columns = {
        "ellipsoid_score", "box_score", "p95_coverage", "p99_coverage",
        "false_orbit_distinct_rate", "orbit_distinct_classification",
    }
    score_columns = sorted(forbidden_output_columns.intersection(DATASET_FIELDS))
    audit.extend([
        {"check": "CAUSAL_DATA_READINESS_V2 bound", "passed": context.get("readiness_v2_enabled") is True, "observed": f"manifest={context['readiness_v2']['path'].as_posix()}"},
        {"check": "Stage-1F score/classification columns absent", "passed": not score_columns, "observed": f"forbidden_columns={score_columns}"},
        {"check": "construction-only residual summary absent", "passed": not SUMMARY_PATH.exists(), "observed": f"path={SUMMARY_PATH.as_posix()}; exists={SUMMARY_PATH.exists()}"},
    ])

    write_csv(DATASET_PATH, rows, DATASET_FIELDS)
    write_csv(FAILURE_PATH, failures, FAILURE_FIELDS)

    april_after = april_protected_inventory()
    april_unchanged = context["april_protection_before"]["aggregate_sha256"] == april_after["aggregate_sha256"]
    frozen_after = readiness_v2_protected_inventory(context)
    frozen_unchanged = frozen_before == frozen_after
    credential_matches = credential_value_match_count([DATASET_PATH, FAILURE_PATH])
    audit.extend([
        {"check": "April protected artifacts unchanged", "passed": april_unchanged and april_after["canonical_stage1b_dataset_sha256"] == APRIL_DATASET_SHA256, "observed": f"artifacts={april_after['artifact_count']}; unchanged={april_unchanged}; canonical={april_after['canonical_stage1b_dataset_sha256']}"},
        {"check": "Stage-1F/May/June readiness protected artifacts unchanged", "passed": frozen_unchanged, "observed": f"artifacts={frozen_after['artifact_count'] if frozen_after else 0}; unchanged={frozen_unchanged}"},
        {"check": "frozen Stage-1F parameter SHA unchanged", "passed": context["readiness_v2"]["parameter_sha256"] == EXPECTED_STAGE1F_PARAMETER_SHA256 and sha256(context["readiness_v2"]["parameter_path"]) == EXPECTED_STAGE1F_PARAMETER_SHA256, "observed": EXPECTED_STAGE1F_PARAMETER_SHA256},
        {"check": "credential values absent from outputs", "passed": credential_matches == 0, "observed": f"credential_value_matches={credential_matches}"},
    ])
    passed = all(bool(row["passed"]) for row in audit)
    status = "JUNE_STAGE1B_RESIDUAL_LIBRARY_COMPLETE" if passed else "STAGE1B_INCOMPLETE"
    write_csv(CORRECTNESS_PATH, audit, ["check", "passed", "observed"])
    report = construction_only_report(status, rows, audit, metrics, context, failure_counts)
    write_text(REPORT_PATH, report)

    april_manifest = load_json(APRIL_STAGE1B_MANIFEST_PATH)
    may_manifest_path = METRICS_DIR / "orbit_uncertainty_stage1b_20260501_20260531_manifest.json"
    may_manifest = load_json(may_manifest_path)
    candidate_manifest_path = METRICS_DIR / "orbit_uncertainty_stage1f_june_supgp_candidate_manifest.json"
    completeness_manifest_path = METRICS_DIR / "orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_manifest.json"
    output_files = [DATASET_PATH, CORRECTNESS_PATH, FAILURE_PATH, REPORT_PATH]
    manifest = {
        "stage": "Orbit Uncertainty Stage-1B",
        "status": status,
        "generated_utc": utc_now(),
        "window_tag": WINDOW_TAG,
        "formal_window": FORMAL_INTERVAL,
        "cohort": context["cohort"],
        "comparison_semantics": "ordinary-GP prediction disagreement relative to SpaceX-E/SupGP higher-quality historical reference; not ground-truth error",
        "selection_policy": "CREATION_DATE <= evaluation_time; latest CREATION_DATE, then EPOCH, then GP_ID",
        "causal_readiness_protocol": CAUSAL_DATA_READINESS_V2,
        "builder": {
            "path": Path(__file__).as_posix(),
            "sha256": sha256(Path(__file__)),
            "version_basis": "builder SHA256; repository is not a git work tree",
            "git_state": "NOT_A_GIT_WORK_TREE",
            "package_versions": package_versions(),
        },
        "authoritative_stage1b_method_binding": {
            "april_manifest": {"path": APRIL_STAGE1B_MANIFEST_PATH.as_posix(), "sha256": sha256(APRIL_STAGE1B_MANIFEST_PATH), "builder_sha256": april_manifest["builder"]["sha256"]},
            "may_manifest": {"path": may_manifest_path.as_posix(), "sha256": sha256(may_manifest_path), "builder_sha256": may_manifest["builder"]["sha256"]},
            "numerical_method_reused": "SGP4 TEME propagation -> Astropy GCRS -> SupGP/reference-defined RTN; ordinary minus reference",
        },
        "input_manifests": {
            "acquisition": {"path": ACQUISITION_MANIFEST.as_posix(), "sha256": context["manifest_sha256"]["acquisition"]},
            "reference_quality": {"path": REFERENCE_MANIFEST.as_posix(), "sha256": context["manifest_sha256"]["reference_quality"]},
            "june_supgp_candidate": {"path": candidate_manifest_path.as_posix(), "sha256": sha256(candidate_manifest_path)},
            "causal_support_audit": {"path": context["causal_path"].as_posix(), "sha256": context["manifest_sha256"]["causal_support_audit"]},
            "gt72_completeness": {"path": completeness_manifest_path.as_posix(), "sha256": sha256(completeness_manifest_path)},
            "readiness_adjudication": {"path": context["readiness_v2"]["path"].as_posix(), "sha256": context["readiness_v2"]["sha256"]},
            "cohort_selection": {"path": context["selection_path"].as_posix(), "sha256": context["selection_sha256"]},
        },
        "input_raw": {
            "ordinary": {"path": context["ordinary_path"].as_posix(), "sha256": context["ordinary_sha256"], "record_count": int(context["acquisition_manifest"]["ordinary_gp"]["record_count"])},
            "supgp": {"directory": SUPGP_DIR.as_posix(), "file_count": len(context["reference_files"]), "record_count": len(references), "files": context["reference_files"]},
            "hashes_before_after_equal": input_hashes_before == current_input_hashes(context),
        },
        "frame_time_assumptions": {
            "ordinary_initialization": "TLE_LINE1/2 embedded in Space-Track OMM JSON via Satrec.twoline2rv",
            "supgp_initialization": "CelesTrak historical SupGP OMM via sgp4.omm.initialize",
            "native_frame_both": "TEME from SGP4",
            "common_frame": "GCRS via Astropy TEME transform at the common UTC evaluation epoch",
            "rtn_basis": "SupGP/reference GCRS position and velocity",
            "residual_sign": "ordinary minus reference",
            "iers": iers_info,
        },
        "freshness_eligibility": {
            "support": "0 < element_age_hours <= 36",
            "within_stage1f_support_rows": metrics["within_stage1f_support_rows"],
            "outside_stage1f_support_rows": metrics["outside_stage1f_support_rows"],
            "engineering_staleness_gt72h_rows": metrics["engineering_staleness_gt72h_rows"],
            "gt72_subset_of_outside_support": metrics["gt72_subset_of_outside_stage1f_support"],
            "outside_support_decision": "DEFER",
            "rows_removed_for_freshness": 0,
        },
        "failure_accounting": {
            "input_rows": len(references),
            "output_rows": len(rows),
            "nominal_rows": metrics["nominal_rows"],
            "excluded_rows": metrics["excluded_rows"],
            "excluded_reasons": failure_counts,
            "propagation_failures": metrics["propagation_failure_rows"],
            "frame_conversion_failures": metrics["frame_transform_failure_rows"],
            "rtn_failures": metrics["invalid_rtn_basis_rows"],
            "nonfinite_failures": metrics["finite_failure_rows"],
        },
        "smoke_binding": {
            "manifest": SMOKE_MANIFEST_PATH.as_posix(),
            "manifest_sha256": sha256(SMOKE_MANIFEST_PATH),
            "status": smoke["status"],
            "case_count": smoke["case_count"],
            "max_numeric_abs_difference": smoke["max_numeric_abs_difference"],
        },
        "protected_artifacts": {
            "april_before": context["april_protection_before"],
            "april_after": april_after,
            "april_unchanged": april_unchanged,
            "stage1f_may_june_readiness_before": frozen_before,
            "stage1f_may_june_readiness_after": frozen_after,
            "stage1f_may_june_readiness_unchanged": frozen_unchanged,
            "stage1f_parameter": {"path": context["readiness_v2"]["parameter_path"].as_posix(), "sha256": EXPECTED_STAGE1F_PARAMETER_SHA256, "role": "PROTECTED_DEPENDENCY_ONLY_NOT_SCORING_INPUT"},
        },
        "result": {
            **metrics,
            "correctness_passed": sum(bool(row["passed"]) for row in audit),
            "correctness_total": len(audit),
        },
        "outputs": {path.name: {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in output_files},
        "blindness_firewall": {
            "residual_descriptive_summary_generated": False,
            "residual_distribution_analyzed": False,
            "residual_ranking_generated": False,
            "figures_generated": False,
            "stage1f_parameter_values_read": False,
            "stage1f_scoring_code_called": False,
            "ellipsoid_d2_computed": False,
            "box_score_computed": False,
            "p95_or_p99_coverage_computed": False,
            "false_orbit_distinct_rate_computed": False,
            "per_satellite_confirmatory_performance_computed": False,
        },
        "scope_guards": {
            "residual_based_exclusion_applied": False,
            "rms_cutoff_applied": False,
            "model_recalibrated": False,
            "stage1f_confirmatory_validation_run": False,
            "synthetic_b_analyzed": False,
            "doppler_verifier_run": False,
        },
    }
    write_json(MANIFEST_PATH, manifest)
    final_credential_matches = credential_value_match_count(output_files + [MANIFEST_PATH])
    final_frozen = readiness_v2_protected_inventory(context)
    if final_credential_matches != credential_matches:
        raise SystemExit(f"Credential-value scan changed after manifest write: {final_credential_matches}")
    if final_frozen != frozen_before:
        raise SystemExit("Frozen artifacts changed after June Stage-1B manifest write")
    print(json.dumps({
        "mode": "formal",
        "status": status,
        "rows": len(rows),
        "nominal": metrics["nominal_rows"],
        "excluded": metrics["excluded_rows"],
        "causal_gp_id_matches": len(rows) - metrics["selected_gp_id_mismatch"],
        "within_stage1f_support": metrics["within_stage1f_support_rows"],
        "outside_stage1f_support": metrics["outside_stage1f_support_rows"],
        "engineering_staleness_gt72h": metrics["engineering_staleness_gt72h_rows"],
        "correctness": f"{sum(bool(row['passed']) for row in audit)}/{len(audit)}",
    }, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit("Stage-1B construction-only dataset generated but correctness audit did not fully pass")


def run_formal(
    context: dict[str, Any],
    references: list[dict[str, Any]],
    ordinary_by_norad: dict[str, list[dict[str, Any]]],
    reference_status: dict[str, str],
    iers_info: dict[str, Any],
) -> None:
    if context.get("readiness_v2_enabled"):
        run_formal_construction_only(context, references, ordinary_by_norad, reference_status, iers_info)
        return
    outputs = [DATASET_PATH, SUMMARY_PATH, CORRECTNESS_PATH, FAILURE_PATH, MANIFEST_PATH, REPORT_PATH]
    ensure_outputs_available(outputs, ARGS.overwrite)
    smoke = verify_smoke_precondition(context)
    input_hashes_before = current_input_hashes(context)
    rows = build_rows_batched(
        references,
        ordinary_by_norad,
        reference_status,
        context,
        progress=True,
    )

    summary = build_summary(rows, context["cohort"])
    audit, metrics = correctness_audit(rows, references, context, smoke, iers_info, input_hashes_before)
    failures = failure_rows(rows)
    descriptive_values = overall_descriptive(rows)
    comparison = april_may_descriptive_comparison(rows)

    write_csv(DATASET_PATH, rows, DATASET_FIELDS)
    write_csv(SUMMARY_PATH, summary, list(summary[0]))
    write_csv(FAILURE_PATH, failures, FAILURE_FIELDS)
    initial_status = "STAGE1B_INCOMPLETE"
    report = markdown_report(initial_status, rows, summary, audit, metrics, descriptive_values, context, comparison)
    write_text(REPORT_PATH, report)

    april_after = april_protected_inventory()
    april_unchanged = context["april_protection_before"]["aggregate_sha256"] == april_after["aggregate_sha256"]
    credential_matches = credential_value_match_count([DATASET_PATH, SUMMARY_PATH, FAILURE_PATH, REPORT_PATH])
    metrics["april_protected_artifacts_unchanged"] = april_unchanged
    metrics["april_protected_artifact_count"] = april_after["artifact_count"]
    metrics["credential_value_matches_in_outputs"] = credential_matches
    audit.extend([
        {"check": "April protected artifacts unchanged", "passed": april_unchanged and april_after["canonical_stage1b_dataset_sha256"] == APRIL_DATASET_SHA256, "observed": f"artifacts={april_after['artifact_count']}; before={context['april_protection_before']['aggregate_sha256']}; after={april_after['aggregate_sha256']}; canonical={april_after['canonical_stage1b_dataset_sha256']}"},
        {"check": "credential values absent from outputs", "passed": credential_matches == 0, "observed": f"credential_value_matches={credential_matches}"},
    ])
    passed = all(bool(row["passed"]) for row in audit)
    complete_status = "MAY_STAGE1B_RESIDUAL_LIBRARY_COMPLETE" if WINDOW_TAG == "20260501_20260531" else "APRIL_STAGE1B_RESIDUAL_LIBRARY_COMPLETE"
    status = complete_status if passed else "STAGE1B_INCOMPLETE"
    write_csv(CORRECTNESS_PATH, audit, ["check", "passed", "observed"])
    report = markdown_report(status, rows, summary, audit, metrics, descriptive_values, context, comparison)
    write_text(REPORT_PATH, report)

    output_files = [DATASET_PATH, SUMMARY_PATH, CORRECTNESS_PATH, FAILURE_PATH, REPORT_PATH]
    manifest = {
        "stage": "Orbit Uncertainty Stage-1B",
        "status": status,
        "generated_utc": utc_now(),
        "window_tag": WINDOW_TAG,
        "formal_window": FORMAL_INTERVAL,
        "cohort": context["cohort"],
        "comparison_semantics": "ordinary-GP prediction disagreement relative to operator-derived higher-quality SupGP reference; not ground-truth error",
        "selection_policy": "CREATION_DATE <= evaluation_time; latest CREATION_DATE, then EPOCH, then GP_ID",
        "builder": {
            "path": Path(__file__).as_posix(),
            "sha256": sha256(Path(__file__)),
            "version_basis": "builder SHA256; repository is not a git work tree",
            "git_state": "NOT_A_GIT_WORK_TREE",
            "package_versions": package_versions(),
        },
        "input_manifests": {
            "design": {"path": DESIGN_MANIFEST.as_posix(), "sha256": context["manifest_sha256"]["design"]} if DESIGN_MANIFEST is not None else None,
            "acquisition": {"path": ACQUISITION_MANIFEST.as_posix(), "sha256": context["manifest_sha256"]["acquisition"]},
            "reference_quality": {"path": REFERENCE_MANIFEST.as_posix(), "sha256": context["manifest_sha256"]["reference_quality"]},
            "causal_support_audit": {"path": context["causal_path"].as_posix(), "sha256": context["manifest_sha256"]["causal_support_audit"]},
            "cohort_selection": {"path": context["selection_path"].as_posix(), "sha256": context["selection_sha256"]},
        },
        "input_raw": {
            "ordinary": {"path": context["ordinary_path"].as_posix(), "sha256": context["ordinary_sha256"], "record_count": int(context["acquisition_manifest"]["ordinary_gp"]["record_count"])},
            "supgp": {"directory": SUPGP_DIR.as_posix(), "file_count": len(context["reference_files"]), "record_count": len(references), "files": context["reference_files"]},
            "hashes_before_after_equal": input_hashes_before == current_input_hashes(context),
        },
        "smoke_binding": {
            "manifest": SMOKE_MANIFEST_PATH.as_posix(),
            "manifest_sha256": sha256(SMOKE_MANIFEST_PATH),
            "status": smoke["status"],
            "case_count": smoke["case_count"],
            "max_numeric_abs_difference": smoke["max_numeric_abs_difference"],
        },
        "frame_time_assumptions": {
            "ordinary_initialization": "TLE_LINE1/2 embedded in the Space-Track OMM JSON via Satrec.twoline2rv; Stage-0 Starlink numerical policy",
            "supgp_initialization": "CelesTrak SupGP OMM via sgp4.omm.initialize",
            "native_frame_both": "TEME from SGP4",
            "common_frame": "GCRS via Astropy TEME transform at the common UTC evaluation epoch",
            "rtn_basis": "SupGP/reference GCRS position and velocity",
            "residual_sign": "ordinary minus reference",
            "iers": iers_info,
        },
        "reference_availability_provenance": {
            **context.get("archive_pause", {}),
            "calendar_day_actual_evaluation_rows": metrics["archive_pause_calendar_day_evaluation_rows"],
            "interpolation_applied": False,
            "fill_applied": False,
            "regular_grid_constructed": False,
        },
        "april_protection": {
            "expected_canonical_stage1b_dataset_sha256": APRIL_DATASET_SHA256,
            "before": context["april_protection_before"],
            "after": april_after,
            "unchanged": april_unchanged,
        },
        "april_current_window_descriptive_comparison": comparison,
        "result": {**metrics, "correctness_passed": sum(bool(row["passed"]) for row in audit), "correctness_total": len(audit), "descriptive": descriptive_values},
        "outputs": {path.name: {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in output_files},
        "scope_guards": {
            "uncertainty_boundary_built": False,
            "synthetic_b_analyzed": False,
            "doppler_verifier_run": False,
            "residual_based_exclusion_applied": False,
            "rms_cutoff_applied": False,
            "april_to_may_external_validation_run": False,
            "model_recalibrated": False,
            "stage1c_episode_discovery_run": False,
            "stage1f_run": False,
        },
    }
    write_json(MANIFEST_PATH, manifest)
    final_credential_matches = credential_value_match_count(output_files + [MANIFEST_PATH])
    if final_credential_matches != credential_matches:
        raise SystemExit(f"Credential-value scan changed after manifest write: {final_credential_matches}")
    print(json.dumps({
        "mode": "formal",
        "status": status,
        "rows": len(rows),
        "nominal": metrics["nominal_rows"],
        "excluded": metrics["excluded_rows"],
        "satellites": len({row["NORAD_CAT_ID"] for row in rows}),
        "correctness": f"{sum(bool(row['passed']) for row in audit)}/{len(audit)}",
    }, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit("Stage-1B formal dataset generated but correctness audit did not fully pass")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["smoke", "formal"], required=True)
    parser.add_argument("--overwrite", action="store_true", help="Replace only Stage-1B outputs for the selected mode")
    parser.add_argument("--window-tag", default=DEFAULT_WINDOW_TAG)
    parser.add_argument("--formal-start", default=DEFAULT_FORMAL_START)
    parser.add_argument("--formal-stop", default=DEFAULT_FORMAL_STOP_EXCLUSIVE)
    parser.add_argument("--expected-formal-rows", type=int, default=5675)
    parser.add_argument("--supgp-dir", default=APRIL_SUPGP_DIR.as_posix())
    parser.add_argument("--design-manifest")
    parser.add_argument("--acquisition-manifest")
    parser.add_argument("--reference-manifest")
    parser.add_argument("--reference-quality")
    parser.add_argument("--causal-audit")
    parser.add_argument("--cohort-selection")
    parser.add_argument(
        "--readiness-adjudication-manifest",
        help="Bind CAUSAL_DATA_READINESS_V2; required to retain causally valid >72 h rows",
    )
    parser.add_argument("--iers-cache-only", action="store_true", help="Use the existing Astropy IERS cache without a network refresh")
    parser.add_argument("--iers-data-file", help="Explicit frozen IERS-A file; its SHA must match the April Stage-1B manifest")
    return parser.parse_args()


def main() -> None:
    global ARGS
    ARGS = parse_args()
    configure_runtime(ARGS)
    context = verify_stage1a_inputs()
    context["april_protection_before"] = april_protected_inventory()
    iers_info = configure_iers()
    if not iers_info["formal_window_covered"]:
        raise SystemExit(f"IERS table does not cover the frozen formal window: {iers_info}")
    april_iers_sha = load_json(APRIL_STAGE1B_MANIFEST_PATH)["frame_time_assumptions"]["iers"]["data_sha256"]
    if iers_info["data_sha256"] != april_iers_sha:
        raise SystemExit(
            f"IERS data SHA differs from April frozen Stage-1B: current={iers_info['data_sha256']}; april={april_iers_sha}"
        )
    _, ordinary_by_norad = read_ordinary(context)
    reference_status = read_reference_status(context)
    references = read_supgp(context)
    if ARGS.mode == "smoke":
        run_smoke(context, references, ordinary_by_norad, reference_status, iers_info)
    else:
        run_formal(context, references, ordinary_by_norad, reference_status, iers_info)


ARGS: argparse.Namespace

if __name__ == "__main__":
    main()
