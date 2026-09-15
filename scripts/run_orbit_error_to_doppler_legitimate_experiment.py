"""Legitimate-A ordinary-public-GP versus SpaceX-E/SupGP Doppler experiment.

Execution is split so that population selection is outcome-blind and June science
remains untouched until the protocol and full April-May-June population are frozen.
No observation noise, environmental b/k, candidate source, compensation, final b/k
gate, or false-reject endpoint is used.
"""

from __future__ import annotations

import argparse
import bisect
import concurrent.futures
import hashlib
import json
import math
import platform
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sgp4 import omm
from sgp4.api import Satrec
from skyfield.api import EarthSatellite, load


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_doppler_verifier_initial_experiments as verifier  # noqa: E402


DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
FIGURES = ROOT / "outputs" / "figures" / "orbit_error_to_doppler_legitimate"
LOG = ROOT / "logs" / "work_log.md"

PROTOCOL = METRICS / "orbit_error_to_doppler_legitimate_population_protocol.json"
PROTOCOL_SHA256 = "75C051F0A3D61D38FF043A37D9B4E2DBB5588959FAB6D26C1DFF4EA212AC77B7"
COHORT_SOURCE = METRICS / "orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv"

POPULATION = DATASETS / "orbit_error_to_doppler_legitimate_population.csv"
POPULATION_AUDIT = METRICS / "orbit_error_to_doppler_legitimate_population_audit.csv"
COVERAGE = METRICS / "orbit_error_to_doppler_legitimate_freshness_coverage.csv"
POPULATION_MANIFEST = METRICS / "orbit_error_to_doppler_legitimate_population_manifest.json"

EXPLORATORY_RESULTS = DATASETS / "orbit_error_to_doppler_legitimate_exploratory_segment_results.csv"
EXPLORATORY_SERIES = DATASETS / "orbit_error_to_doppler_legitimate_exploratory_timeseries.csv"
EXPLORATORY_MANIFEST = METRICS / "orbit_error_to_doppler_legitimate_exploratory_manifest.json"
CONFIRMATORY_RESULTS = DATASETS / "orbit_error_to_doppler_legitimate_june_confirmatory_segment_results.csv"
CONFIRMATORY_SERIES = DATASETS / "orbit_error_to_doppler_legitimate_june_confirmatory_timeseries.csv"
CONFIRMATORY_MANIFEST = METRICS / "orbit_error_to_doppler_legitimate_june_confirmatory_manifest.json"

FINAL_SEGMENTS = DATASETS / "legitimate_orbit_error_to_doppler_segments.csv"
FRESHNESS_SUMMARY = METRICS / "legitimate_orbit_error_freshness_summary.csv"
CORRELATIONS = METRICS / "orbit_error_to_doppler_legitimate_spearman_correlations.csv"
GEOMETRY_SUMMARY = METRICS / "legitimate_orbit_error_geometry_summary.csv"
GEOMETRY_AUDIT = METRICS / "orbit_error_to_doppler_legitimate_geometry_effect_audit.csv"
REPLICATION = METRICS / "orbit_error_to_doppler_legitimate_june_replication.csv"
FINAL_MANIFEST = METRICS / "orbit_error_to_doppler_legitimate_final_manifest.json"
PROTECTED_BINDINGS_AUDIT = METRICS / "orbit_error_to_doppler_legitimate_protected_frozen_bindings.csv"
PROTECTED_BINDINGS_MANIFEST = METRICS / "orbit_error_to_doppler_legitimate_protected_frozen_bindings_manifest.json"
REPORT = REPORTS / "legitimate_orbit_error_to_doppler_stage_a_report.md"

MONTHS = {
    "2026-04": (datetime(2026, 4, 1, tzinfo=timezone.utc), datetime(2026, 5, 1, tzinfo=timezone.utc), "EXPLORATORY"),
    "2026-05": (datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc), "EXPLORATORY"),
    "2026-06": (datetime(2026, 6, 1, tzinfo=timezone.utc), datetime(2026, 7, 1, tzinfo=timezone.utc), "CONFIRMATORY"),
}
GP_PATHS = {
    "2026-04": ROOT / "data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260329_20260501_20sat_omm.json",
    "2026-05": ROOT / "data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260428_20260601_20sat_omm.json",
    "2026-06": ROOT / "data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260529_20260701_20sat_omm.json",
}
REFERENCE_DIRS = {
    "2026-04": ROOT / "data/orbit_uncertainty_stage1/raw/celestrak_supgp",
    "2026-05": ROOT / "data/orbit_uncertainty_stage1/respecialdatarequest (4)",
    "2026-06": ROOT / "data/orbit_uncertainty_stage1/june",
}
REFERENCE_MANIFESTS = {
    "2026-04": METRICS / "orbit_uncertainty_stage1b_20260401_20260430_manifest.json",
    "2026-05": METRICS / "orbit_uncertainty_stage1b_20260501_20260531_manifest.json",
    "2026-06": METRICS / "orbit_uncertainty_stage1b_20260601_20260630_manifest.json",
}

STATION_ID = "controlled_example_station"
STATION_LAT = 52.21
STATION_LON = 5.16
STATION_ALT_M = 14.0
CARRIER_HZ = 11_325_000_000.0
MIN_ELEVATION_DEG = 10.0
COARSE_STEP_S = 30
REFINE_STEP_S = 1
SEGMENT_HALF_S = 30
POINTS_PER_SEGMENT = 61
MAX_REFERENCE_SEPARATION_S = 3 * 3600
PASSES_PER_BIN = 2
FRESHNESS_LABELS = ["0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h"]
PHASES = ["RISING_25_PERCENT", "PEAK", "SETTING_75_PERCENT"]
OUTCOMES = ["raw_rms_hz", "abs_delta_b_orbit_hz", "abs_delta_k_orbit_hz_per_s", "score_orbit_hz", "explained_fraction"]
GEOMETRY_OUTCOMES = ["raw_rms_hz", "score_orbit_hz", "abs_delta_k_orbit_hz_per_s"]
_CREATION_CACHE: dict[int, list[datetime]] = {}
_WORKER_GP_CATALOGS: dict[str, dict[str, list[dict[str, Any]]]] = {}
_WORKER_REFERENCE_CATALOGS: dict[str, dict[str, list[dict[str, Any]]]] = {}
_WORKER_COARSE_TIMES: dict[str, list[datetime]] = {}
_WORKER_TS: Any | None = None
_WORKER_SITE: Any | None = None
_REFERENCE_FRAME_CACHE: dict[str, tuple[str, pd.DataFrame]] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["population", "exploratory", "confirmatory", "summarize", "protect", "all"], required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def parse_utc(value: Any) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes(order="C")).hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def stable_id(prefix: str, values: Iterable[Any]) -> str:
    payload = "|".join(str(value) for value in values)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hash_record(path: Path) -> dict[str, Any]:
    return {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def refuse_existing(paths: list[Path], overwrite: bool) -> None:
    existing = [rel(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Outputs exist; use --overwrite only for this independent experiment: " + ", ".join(existing))


def validate_protocol() -> dict[str, Any]:
    if not PROTOCOL.exists() or sha256(PROTOCOL) != PROTOCOL_SHA256:
        raise SystemExit("Frozen legitimate-population protocol is missing or changed")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("protocol_status") != "FROZEN_BEFORE_NUMERICAL_SCIENCE":
        raise SystemExit("Population protocol is not frozen")
    for source in protocol["ordinary_gp"]["source_paths"]:
        path = ROOT / source["path"]
        if not path.exists() or sha256(path) != source["sha256"]:
            raise SystemExit(f"Ordinary GP binding changed: {source['path']}")
    for source in protocol["reference"]["monthly_manifest_bindings"]:
        path = ROOT / source["path"]
        if not path.exists() or sha256(path) != source["sha256"]:
            raise SystemExit(f"Reference manifest binding changed: {source['path']}")
    if sha256(ROOT / protocol["satellite_cohort"]["source"]) != protocol["satellite_cohort"]["source_sha256"]:
        raise SystemExit("Frozen cohort binding changed")
    if sha256(ROOT / protocol["doppler"]["production_function"].split("::")[0]) != protocol["doppler"]["production_function_sha256"]:
        raise SystemExit("Production Doppler implementation changed")
    if sha256(ROOT / protocol["ols_and_score"]["production_function"].split("::")[0]) != protocol["ols_and_score"]["production_function_sha256"]:
        raise SystemExit("Production OLS implementation changed")
    return protocol


def freshness_bin(age_h: float) -> str | None:
    bounds = [(0, 6), (6, 9), (9, 12), (12, 18), (18, 24), (24, 36)]
    for label, (lo, hi) in zip(FRESHNESS_LABELS, bounds):
        if lo < age_h <= hi:
            return label
    return None


def round_second_half_up(value: datetime) -> datetime:
    timestamp = value.timestamp()
    return datetime.fromtimestamp(math.floor(timestamp + 0.5), tz=timezone.utc)


def load_gp_catalog(month: str) -> dict[str, list[dict[str, Any]]]:
    raw = json.loads(GP_PATHS[month].read_text(encoding="utf-8-sig"))
    catalog: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw:
        catalog[str(row["NORAD_CAT_ID"])].append(row)
    for sat_id, records in catalog.items():
        for row in records:
            row["_creation"] = parse_utc(row["CREATION_DATE"])
            row["_epoch"] = parse_utc(row["EPOCH"])
        records.sort(key=lambda row: (row["_creation"], row["_epoch"], str(row.get("GP_ID", ""))))
        _CREATION_CACHE[id(records)] = [row["_creation"] for row in records]
        if not records:
            raise RuntimeError(f"Empty GP catalog for {sat_id}")
    return catalog


def select_causal(records: list[dict[str, Any]], when: datetime) -> dict[str, Any] | None:
    creations = _CREATION_CACHE.get(id(records))
    if creations is None:
        creations = [parse_utc(row["CREATION_DATE"]) for row in records]
        _CREATION_CACHE[id(records)] = creations
    index = bisect.bisect_right(creations, when) - 1
    return records[index] if index >= 0 else None


def load_reference_catalog(month: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(REFERENCE_DIRS[month].glob("sat*.csv")):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        source_sha = sha256(path)
        for zero_index, row in frame.iterrows():
            record = row.to_dict()
            record["_epoch"] = parse_utc(record["EPOCH"])
            record["_source_path"] = rel(path)
            record["_source_sha256"] = source_sha
            record["_source_row_index"] = int(zero_index) + 2
            result[str(record["NORAD_CAT_ID"])].append(record)
    for records in result.values():
        records.sort(key=lambda row: (row["_epoch"], row["_source_row_index"]))
    return result


def select_reference(records: list[dict[str, Any]], when: datetime) -> dict[str, Any] | None:
    if not records:
        return None
    chosen = min(records, key=lambda row: (abs((row["_epoch"] - when).total_seconds()), row["_epoch"] > when, row["_source_row_index"]))
    if abs((chosen["_epoch"] - when).total_seconds()) > MAX_REFERENCE_SEPARATION_S:
        return None
    return chosen


def earth_satellite_from_gp(record: dict[str, Any], ts: Any) -> EarthSatellite:
    return EarthSatellite(str(record["TLE_LINE1"]), str(record["TLE_LINE2"]), str(record.get("OBJECT_NAME", "A")), ts)


def earth_satellite_from_reference(record: dict[str, Any], ts: Any) -> EarthSatellite:
    satrec = Satrec()
    omm.initialize(satrec, {key: str(value) for key, value in record.items() if not key.startswith("_")})
    return EarthSatellite.from_satrec(satrec, ts)


def evaluate_public_elevation(
    records: list[dict[str, Any]], times: list[datetime], ts: Any, site: Any,
) -> tuple[np.ndarray, list[dict[str, Any] | None]]:
    selected = [select_causal(records, when) for when in times]
    elevations = np.full(len(times), np.nan, dtype=float)
    by_key: dict[str, list[int]] = defaultdict(list)
    objects: dict[str, EarthSatellite] = {}
    for index, record in enumerate(selected):
        if record is None:
            continue
        key = str(record.get("GP_ID", "")) + "|" + str(record["EPOCH"]) + "|" + str(record["CREATION_DATE"])
        by_key[key].append(index)
        if key not in objects:
            objects[key] = earth_satellite_from_gp(record, ts)
    for key, indices in by_key.items():
        sky_times = ts.from_datetimes([times[index] for index in indices])
        elevations[indices] = (objects[key] - site).at(sky_times).altaz()[0].degrees
    return elevations, selected


def contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    starts = [int(indices[0])]
    ends: list[int] = []
    for left, right in zip(indices, indices[1:]):
        if int(right) != int(left) + 1:
            ends.append(int(left))
            starts.append(int(right))
    ends.append(int(indices[-1]))
    return list(zip(starts, ends))


def refine_pass(
    records: list[dict[str, Any]], coarse_times: list[datetime], coarse_elevation: np.ndarray,
    start_index: int, end_index: int, ts: Any, site: Any,
) -> dict[str, Any] | None:
    left = coarse_times[start_index] - timedelta(seconds=60)
    right = coarse_times[end_index] + timedelta(seconds=60)
    count = int((right - left).total_seconds()) + 1
    times = [left + timedelta(seconds=index) for index in range(count)]
    elevation, selected = evaluate_public_elevation(records, times, ts, site)
    runs = contiguous_runs(np.isfinite(elevation) & (elevation >= MIN_ELEVATION_DEG))
    coarse_peak_index = start_index + int(np.nanargmax(coarse_elevation[start_index : end_index + 1]))
    coarse_peak_time = coarse_times[coarse_peak_index]
    target = int(round((coarse_peak_time - left).total_seconds()))
    containing = [(start, end) for start, end in runs if start <= target <= end]
    if not containing:
        return None
    start, end = containing[0]
    local = elevation[start : end + 1]
    peak = start + int(np.nanargmax(local))
    if selected[peak] is None:
        return None
    return {
        "start": times[start],
        "end": times[end],
        "peak": times[peak],
        "peak_elevation_deg": float(elevation[peak]),
        "peak_gp": selected[peak],
    }


def phase_centers(pass_record: dict[str, Any]) -> list[tuple[str, datetime]]:
    start, end, peak = pass_record["start"], pass_record["end"], pass_record["peak"]
    duration = (end - start).total_seconds()
    raw = [
        (PHASES[0], max(start + timedelta(seconds=SEGMENT_HALF_S), start + timedelta(seconds=0.25 * duration))),
        (PHASES[1], peak),
        (PHASES[2], min(end - timedelta(seconds=SEGMENT_HALF_S), start + timedelta(seconds=0.75 * duration))),
    ]
    result: list[tuple[str, datetime]] = []
    seen: set[datetime] = set()
    for phase, value in raw:
        center = round_second_half_up(value)
        if center not in seen:
            seen.add(center)
            result.append((phase, center))
    return result


def build_segment_candidate(
    month: str, sat_id: str, sat_name: str, pass_record: dict[str, Any],
    phase: str, center: datetime, records: list[dict[str, Any]], refs: list[dict[str, Any]],
    ts: Any, site: Any,
) -> tuple[dict[str, Any] | None, str]:
    gp = select_causal(records, center)
    if gp is None:
        return None, "NO_CAUSAL_GP_AT_SEGMENT_CENTER"
    age_h = (center - parse_utc(gp["EPOCH"])).total_seconds() / 3600.0
    freshness = freshness_bin(age_h)
    if freshness is None:
        return None, "OUT_OF_SUPPORT"
    reference = select_reference(refs, center)
    if reference is None:
        return None, "NO_REFERENCE_WITHIN_3H"
    times = [center + timedelta(seconds=index - SEGMENT_HALF_S) for index in range(POINTS_PER_SEGMENT)]
    sat = earth_satellite_from_gp(gp, ts)
    sky_times = ts.from_datetimes(times)
    elevation = np.asarray((sat - site).at(sky_times).altaz()[0].degrees, dtype=float)
    if not np.isfinite(elevation).all() or np.any(elevation < MIN_ELEVATION_DEG):
        return None, "SEGMENT_PUBLIC_VISIBILITY_FAIL"
    pass_id = stable_id("legit_pass_", [sat_id, month, iso_z(pass_record["start"]), iso_z(pass_record["end"])])
    segment_id = stable_id("legit_segment_", [pass_id, phase, iso_z(center), STATION_ID])
    duration = (pass_record["end"] - pass_record["start"]).total_seconds()
    phase_fraction = (center - pass_record["start"]).total_seconds() / duration if duration > 0 else math.nan
    return {
        "segment_id": segment_id,
        "pass_id": pass_id,
        "satellite_norad_id": sat_id,
        "satellite_name": sat_name,
        "month": month,
        "analysis_role": MONTHS[month][2],
        "station_id": STATION_ID,
        "station_lat_deg": STATION_LAT,
        "station_lon_deg": STATION_LON,
        "station_alt_m": STATION_ALT_M,
        "carrier_freq_hz": CARRIER_HZ,
        "visibility_threshold_deg": MIN_ELEVATION_DEG,
        "pass_start_utc": iso_z(pass_record["start"]),
        "pass_end_utc": iso_z(pass_record["end"]),
        "pass_duration_s": duration,
        "pass_max_public_elevation_deg": pass_record["peak_elevation_deg"],
        "phase_label": phase,
        "segment_phase_fraction": phase_fraction,
        "segment_center_utc": iso_z(center),
        "segment_start_utc": iso_z(times[0]),
        "segment_end_utc": iso_z(times[-1]),
        "sample_cadence_s": 1.0,
        "point_count": POINTS_PER_SEGMENT,
        "public_min_elevation_deg": float(np.min(elevation)),
        "public_mean_elevation_deg": float(np.mean(elevation)),
        "public_max_elevation_deg": float(np.max(elevation)),
        "ordinary_gp_id": str(gp.get("GP_ID", "")),
        "ordinary_gp_epoch": iso_z(parse_utc(gp["EPOCH"])),
        "ordinary_gp_creation_date": iso_z(parse_utc(gp["CREATION_DATE"])),
        "element_age_hours": age_h,
        "publication_age_hours": (center - parse_utc(gp["CREATION_DATE"])).total_seconds() / 3600.0,
        "freshness_bin": freshness,
        "ordinary_tle_line1": str(gp["TLE_LINE1"]),
        "ordinary_tle_line2": str(gp["TLE_LINE2"]),
        "ordinary_raw_path": rel(GP_PATHS[month]),
        "ordinary_raw_sha256": sha256(GP_PATHS[month]),
        "reference_epoch": iso_z(reference["_epoch"]),
        "reference_abs_epoch_separation_hours": abs((reference["_epoch"] - center).total_seconds()) / 3600.0,
        "reference_source_path": reference["_source_path"],
        "reference_source_sha256": reference["_source_sha256"],
        "reference_source_row_index": reference["_source_row_index"],
        "population_selection_uses_science_outcome": False,
        "population_status": "SELECTED_FROZEN",
    }, "SELECTED"


def scan_satellite_month(
    month: str,
    role: str,
    sat_id: str,
    sat_name: str,
    records: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    coarse_times: list[datetime],
    ts: Any,
    site: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    if not records or not refs:
        audit_rows.append({"month": month, "analysis_role": role, "satellite_norad_id": sat_id, "satellite_name": sat_name, "freshness_bin": "", "candidate_pass_count": 0, "eligible_pass_count": 0, "selected_pass_count": 0, "selected_segment_count": 0, "status": "MISSING_MONTHLY_SOURCE"})
        return selected_rows, audit_rows
    coarse_elevation, _ = evaluate_public_elevation(records, coarse_times, ts, site)
    runs = contiguous_runs(np.isfinite(coarse_elevation) & (coarse_elevation >= MIN_ELEVATION_DEG))
    eligible_by_bin: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    failure_count: dict[str, int] = defaultdict(int)
    for run_start, run_end in runs:
        refined = refine_pass(records, coarse_times, coarse_elevation, run_start, run_end, ts, site)
        if refined is None:
            failure_count["PASS_REFINEMENT_FAIL"] += 1
            continue
        peak_gp = refined["peak_gp"]
        peak_age_h = (refined["peak"] - parse_utc(peak_gp["EPOCH"])).total_seconds() / 3600.0
        peak_bin = freshness_bin(peak_age_h)
        if peak_bin is None:
            failure_count["PEAK_OUT_OF_SUPPORT"] += 1
            continue
        segments: list[dict[str, Any]] = []
        phase_values = phase_centers(refined)
        if len(phase_values) != 3:
            failure_count["DUPLICATE_PHASE_CENTER"] += 1
            continue
        failed = ""
        for phase, center in phase_values:
            candidate, reason = build_segment_candidate(month, sat_id, sat_name, refined, phase, center, records, refs, ts, site)
            if candidate is None:
                failed = reason
                break
            segments.append(candidate)
        if failed:
            failure_count[failed] += 1
            continue
        eligible_by_bin[peak_bin].append(segments)
    for freshness in FRESHNESS_LABELS:
        eligible = sorted(eligible_by_bin.get(freshness, []), key=lambda segments: segments[0]["pass_start_utc"])
        retained = eligible[:PASSES_PER_BIN]
        for segments in retained:
            selected_rows.extend(segments)
        audit_rows.append({
            "month": month,
            "analysis_role": role,
            "satellite_norad_id": sat_id,
            "satellite_name": sat_name,
            "freshness_bin": freshness,
            "candidate_pass_count": len(runs),
            "eligible_pass_count": len(eligible),
            "selected_pass_count": len(retained),
            "selected_segment_count": sum(len(segments) for segments in retained),
            "status": "ADEQUATE_PASS_QUOTA" if len(retained) == PASSES_PER_BIN else "LIMITED_SUPPORT",
            "preselection_failure_counts": json.dumps(failure_count, sort_keys=True),
        })
    return selected_rows, audit_rows


def population_worker(task: tuple[str, str, str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one satellite-month scan with process-local catalogs and Skyfield objects."""
    global _WORKER_TS, _WORKER_SITE
    month, role, sat_id, sat_name = task
    if _WORKER_TS is None:
        _WORKER_TS = load.timescale()
    if _WORKER_SITE is None:
        _WORKER_SITE = orbit_builder.wgs84.latlon(
            STATION_LAT, STATION_LON, elevation_m=STATION_ALT_M
        )
    if month not in _WORKER_GP_CATALOGS:
        _WORKER_GP_CATALOGS[month] = load_gp_catalog(month)
    if month not in _WORKER_REFERENCE_CATALOGS:
        _WORKER_REFERENCE_CATALOGS[month] = load_reference_catalog(month)
    if month not in _WORKER_COARSE_TIMES:
        month_start, month_end, _ = MONTHS[month]
        coarse_count = int((month_end - month_start).total_seconds() // COARSE_STEP_S)
        _WORKER_COARSE_TIMES[month] = [
            month_start + timedelta(seconds=COARSE_STEP_S * index)
            for index in range(coarse_count)
        ]
    return scan_satellite_month(
        month,
        role,
        sat_id,
        sat_name,
        _WORKER_GP_CATALOGS[month].get(sat_id, []),
        _WORKER_REFERENCE_CATALOGS[month].get(sat_id, []),
        _WORKER_COARSE_TIMES[month],
        _WORKER_TS,
        _WORKER_SITE,
    )


def build_population(overwrite: bool) -> None:
    protocol = validate_protocol()
    paths = [POPULATION, POPULATION_AUDIT, COVERAGE, POPULATION_MANIFEST]
    refuse_existing(paths, overwrite)
    cohort = pd.read_csv(COHORT_SOURCE, dtype=str, keep_default_na=False)
    cohort = cohort[cohort["NORAD_CAT_ID"].isin(protocol["satellite_cohort"]["norad_ids"])].copy()
    if len(cohort) != 20:
        raise SystemExit("Frozen 20-satellite cohort is incomplete")
    selected_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    tasks: list[tuple[str, str, str, str]] = []
    for month, (_, _, role) in MONTHS.items():
        for cohort_row in cohort.itertuples(index=False):
            sat_id, sat_name = str(cohort_row.NORAD_CAT_ID), str(cohort_row.OBJECT_NAME)
            tasks.append((month, role, sat_id, sat_name))
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(population_worker, task) for task in tasks]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            selected, audit = future.result()
            selected_rows.extend(selected)
            audit_rows.extend(audit)
            print(f"population progress {completed}/{len(futures)}", flush=True)
    population = pd.DataFrame(selected_rows).sort_values(["month", "satellite_norad_id", "pass_start_utc", "phase_label"]).reset_index(drop=True)
    audit = pd.DataFrame(audit_rows)
    if population.empty or population["segment_id"].duplicated().any():
        raise SystemExit("Population is empty or contains duplicate segment IDs")
    forbidden = {"delta_f_orbit_hz", "raw_rms_hz", "delta_b_orbit_hz", "delta_k_orbit_hz_per_s", "score_orbit_hz", "verifier_outcome"}
    if forbidden.intersection(population.columns):
        raise SystemExit("Population contains forbidden science-outcome columns")
    coverage = (
        population.groupby(["satellite_norad_id", "satellite_name", "month", "analysis_role", "freshness_bin"], observed=True)
        .agg(segment_units=("segment_id", "nunique"), selected_passes=("pass_id", "nunique"), min_age_h=("element_age_hours", "min"), median_age_h=("element_age_hours", "median"), max_age_h=("element_age_hours", "max"))
        .reset_index()
    )
    full_index = pd.MultiIndex.from_product([cohort["NORAD_CAT_ID"], MONTHS.keys(), FRESHNESS_LABELS], names=["satellite_norad_id", "month", "freshness_bin"])
    coverage = coverage.set_index(["satellite_norad_id", "month", "freshness_bin"]).reindex(full_index).reset_index()
    names = cohort.set_index("NORAD_CAT_ID")["OBJECT_NAME"].to_dict()
    coverage["satellite_name"] = coverage["satellite_norad_id"].map(names)
    coverage["analysis_role"] = coverage["month"].map({month: values[2] for month, values in MONTHS.items()})
    coverage["segment_units"] = coverage["segment_units"].fillna(0).astype(int)
    coverage["selected_passes"] = coverage["selected_passes"].fillna(0).astype(int)
    coverage["support_status"] = np.where(coverage["segment_units"] >= 3, "AVAILABLE", "LIMITED_SUPPORT")
    write_csv(POPULATION, population)
    write_csv(POPULATION_AUDIT, audit)
    write_csv(COVERAGE, coverage)
    manifest = {
        "stage": "LEGITIMATE_POPULATION_FREEZE",
        "status": "POPULATION_FROZEN_NO_DOPPLER_SCIENCE",
        "generated_utc": iso_z(datetime.now(timezone.utc)),
        "protocol": hash_record(PROTOCOL),
        "science_execution_performed": False,
        "june_science_touched": False,
        "selection_uses_forbidden_outcomes": False,
        "satellites": int(population["satellite_norad_id"].nunique()),
        "segments": len(population),
        "passes": int(population["pass_id"].nunique()),
        "month_segments": population.groupby("month").size().astype(int).to_dict(),
        "freshness_segments": population.groupby("freshness_bin", observed=True).size().astype(int).to_dict(),
        "inputs": [hash_record(COHORT_SOURCE), *[hash_record(path) for path in GP_PATHS.values()], *[hash_record(path) for path in REFERENCE_MANIFESTS.values()]],
        "outputs": [hash_record(POPULATION), hash_record(POPULATION_AUDIT), hash_record(COVERAGE)],
        "population_sha256": sha256(POPULATION),
        "coverage_sha256": sha256(COVERAGE),
        "new_random_draw_count": 0,
    }
    write_json(POPULATION_MANIFEST, manifest)
    print(json.dumps({"status": manifest["status"], "segments": len(population), "passes": manifest["passes"], "coverage": rel(COVERAGE)}, indent=2))


def validate_population() -> tuple[pd.DataFrame, dict[str, Any]]:
    validate_protocol()
    if not POPULATION.exists() or not POPULATION_MANIFEST.exists():
        raise SystemExit("Frozen population is unavailable")
    manifest = json.loads(POPULATION_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "POPULATION_FROZEN_NO_DOPPLER_SCIENCE" or sha256(POPULATION) != manifest.get("population_sha256") or sha256(COVERAGE) != manifest.get("coverage_sha256"):
        raise SystemExit("Frozen population or coverage changed")
    return pd.read_csv(POPULATION, dtype=str, keep_default_na=False), manifest


def reference_record_for_population(row: pd.Series) -> dict[str, Any]:
    path = ROOT / str(row["reference_source_path"])
    cache_key = str(path.resolve())
    expected_sha = str(row["reference_source_sha256"])
    cached = _REFERENCE_FRAME_CACHE.get(cache_key)
    if cached is None:
        cached = (sha256(path), pd.read_csv(path, dtype=str, keep_default_na=False))
        _REFERENCE_FRAME_CACHE[cache_key] = cached
    source_sha, frame = cached
    if source_sha != expected_sha:
        raise RuntimeError(f"Reference file changed: {path}")
    zero_index = int(row["reference_source_row_index"]) - 2
    record = frame.iloc[zero_index].to_dict()
    if iso_z(parse_utc(record["EPOCH"])) != str(row["reference_epoch"]):
        raise RuntimeError(f"Reference row mismatch: {row['segment_id']}")
    return record


def raw_metrics(delta: np.ndarray) -> dict[str, Any]:
    abs_delta = np.abs(delta)
    return {
        "raw_mean_hz": float(np.mean(delta)),
        "raw_rms_hz": float(np.sqrt(np.mean(delta**2))),
        "raw_p95_abs_hz": float(np.quantile(abs_delta, 0.95)),
        "raw_max_abs_hz": float(np.max(abs_delta)),
        "raw_end_minus_start_hz": float(delta[-1] - delta[0]),
    }


def execute_split(role: str, overwrite: bool) -> None:
    population, population_manifest = validate_population()
    if role == "EXPLORATORY":
        result_path, series_path, manifest_path = EXPLORATORY_RESULTS, EXPLORATORY_SERIES, EXPLORATORY_MANIFEST
        selected = population[population["analysis_role"].eq("EXPLORATORY")].copy()
    else:
        result_path, series_path, manifest_path = CONFIRMATORY_RESULTS, CONFIRMATORY_SERIES, CONFIRMATORY_MANIFEST
        selected = population[population["analysis_role"].eq("CONFIRMATORY")].copy()
        if not EXPLORATORY_MANIFEST.exists():
            raise SystemExit("June confirmatory cannot run before exploratory output is frozen")
    refuse_existing([result_path, series_path, manifest_path], overwrite)
    ts = load.timescale()
    site = orbit_builder.wgs84.latlon(STATION_LAT, STATION_LON, elevation_m=STATION_ALT_M)
    result_rows: list[dict[str, Any]] = []
    series_rows: list[dict[str, Any]] = []
    for _, row in selected.sort_values("segment_id").iterrows():
        center = parse_utc(row["segment_center_utc"])
        times = [center + timedelta(seconds=index - SEGMENT_HALF_S) for index in range(POINTS_PER_SEGMENT)]
        t_rel = np.arange(POINTS_PER_SEGMENT, dtype=float)
        gp = {"TLE_LINE1": row["ordinary_tle_line1"], "TLE_LINE2": row["ordinary_tle_line2"], "OBJECT_NAME": row["satellite_name"]}
        reference = reference_record_for_population(row)
        public_sat = earth_satellite_from_gp(gp, ts)
        reference_sat = earth_satellite_from_reference(reference, ts)
        public_geo = orbit_builder.geo_curve(public_sat, site, ts, times, CARRIER_HZ, 1.0)
        reference_geo = orbit_builder.geo_curve(reference_sat, site, ts, times, CARRIER_HZ, 1.0)
        f_public = public_geo["f_geo_tle_hz"].to_numpy(float)
        f_ref = reference_geo["f_geo_tle_hz"].to_numpy(float)
        delta = f_ref - f_public
        fit = verifier.fit_bias_and_slope(delta, np.zeros_like(delta), t_rel)
        x = t_rel - float(np.mean(t_rel))
        design = np.column_stack([np.ones_like(x), x])
        residual = delta - design @ np.array([fit.b_hat_hz, fit.k_hat_hz_s])
        raw_energy = float(np.sum(delta**2))
        projected_energy = float(np.sum(residual**2))
        if raw_energy <= 1e-24:
            ratio, explained, energy_status = 0.0, 1.0, "NUMERIC_ZERO"
        else:
            ratio = float(np.clip(projected_energy / raw_energy, 0.0, 1.0))
            explained, energy_status = 1.0 - ratio, "FINITE_NONZERO"
        centered_delta = delta - np.mean(delta)
        sst = float(np.sum(centered_delta**2))
        linear_r2 = 1.0 if sst <= 1e-24 else 1.0 - projected_energy / sst
        quad_design = np.column_stack([np.ones_like(x), x, x**2])
        quad_coef, *_ = np.linalg.lstsq(quad_design, delta, rcond=None)
        quad_residual = delta - quad_design @ quad_coef
        quad_energy = float(np.sum(quad_residual**2))
        curvature_gain = 0.0 if projected_energy <= 1e-24 else float(np.clip(1.0 - quad_energy / projected_energy, 0.0, 1.0))
        result = row.drop(labels=["ordinary_tle_line1", "ordinary_tle_line2"]).to_dict()
        result.update(raw_metrics(delta))
        result.update({
            "delta_b_orbit_hz": float(fit.b_hat_hz),
            "abs_delta_b_orbit_hz": abs(float(fit.b_hat_hz)),
            "delta_k_orbit_hz_per_s": float(fit.k_hat_hz_s),
            "abs_delta_k_orbit_hz_per_s": abs(float(fit.k_hat_hz_s)),
            "score_orbit_hz": float(fit.score_rmse_hz),
            "projected_residual_rms_hz": float(np.sqrt(np.mean(residual**2))),
            "raw_energy_hz2": raw_energy,
            "projected_energy_hz2": projected_energy,
            "projection_residual_ratio": ratio,
            "explained_fraction": explained,
            "energy_status": energy_status,
            "linear_r2": linear_r2,
            "quadratic_coefficient_hz_per_s2": float(quad_coef[2]),
            "quadratic_residual_rms_hz": float(np.sqrt(np.mean(quad_residual**2))),
            "curvature_gain_fraction": curvature_gain,
            "obvious_curvature_flag": bool(curvature_gain >= 0.25 and fit.score_rmse_hz >= 1.0),
            "reference_min_elevation_deg": float(reference_geo["elevation_deg"].min()),
            "reference_mean_elevation_deg": float(reference_geo["elevation_deg"].mean()),
            "reference_max_elevation_deg": float(reference_geo["elevation_deg"].max()),
            "delta_vector_sha256": array_hash(delta),
            "production_bk_gate_executed": False,
            "final_verifier_decision": "NOT_APPLICABLE_STAGE_A",
            "execution_status": "COMPLETE",
        })
        result_rows.append(result)
        for index, when in enumerate(times):
            series_rows.append({
                "segment_id": row["segment_id"],
                "satellite_norad_id": row["satellite_norad_id"],
                "month": row["month"],
                "analysis_role": row["analysis_role"],
                "phase_label": row["phase_label"],
                "time_utc": iso_z(when),
                "t_rel_s": float(t_rel[index]),
                "public_elevation_deg": float(public_geo["elevation_deg"].iloc[index]),
                "reference_elevation_deg": float(reference_geo["elevation_deg"].iloc[index]),
                "F_public_hz": float(f_public[index]),
                "F_ref_hz": float(f_ref[index]),
                "delta_f_orbit_hz": float(delta[index]),
                "projected_residual_hz": float(residual[index]),
            })
    results = pd.DataFrame(result_rows).sort_values("segment_id").reset_index(drop=True)
    series = pd.DataFrame(series_rows).sort_values(["segment_id", "t_rel_s"]).reset_index(drop=True)
    write_csv(result_path, results)
    write_csv(series_path, series)
    manifest = {
        "stage": f"LEGITIMATE_ORBIT_ERROR_DOPPLER_{role}",
        "status": "COMPLETE",
        "generated_utc": iso_z(datetime.now(timezone.utc)),
        "protocol": hash_record(PROTOCOL),
        "population_manifest": hash_record(POPULATION_MANIFEST),
        "population_sha256": population_manifest["population_sha256"],
        "months": sorted(results["month"].unique().tolist()),
        "segments": len(results),
        "timeseries_rows": len(series),
        "production_bk_gate_executions": 0,
        "new_random_draw_count": 0,
        "outputs": [hash_record(result_path), hash_record(series_path)],
    }
    write_json(manifest_path, manifest)
    print(json.dumps({"status": "COMPLETE", "role": role, "segments": len(results), "timeseries_rows": len(series)}, indent=2))


def qvalue(values: pd.Series, q: float, minimum_n: int) -> float:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return float(clean.quantile(q)) if len(clean) >= minimum_n else math.nan


def summarize_freshness(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    splits = [("EXPLORATORY_APRIL_MAY", data[data["analysis_role"].eq("EXPLORATORY")]), ("CONFIRMATORY_JUNE", data[data["analysis_role"].eq("CONFIRMATORY")]), ("ALL_DESCRIPTIVE", data)]
    for split, frame in splits:
        for freshness in FRESHNESS_LABELS:
            group = frame[frame["freshness_bin"].eq(freshness)]
            for metric in OUTCOMES:
                values = pd.to_numeric(group[metric], errors="coerce").dropna()
                rows.append({
                    "analysis_split": split,
                    "freshness_bin": freshness,
                    "metric": metric,
                    "n": len(values),
                    "median": float(values.median()) if len(values) else math.nan,
                    "p90": qvalue(values, 0.90, 10),
                    "p95": qvalue(values, 0.95, 20),
                    "p99": qvalue(values, 0.99, 100),
                    "minimum": float(values.min()) if len(values) else math.nan,
                    "maximum": float(values.max()) if len(values) else math.nan,
                    "p99_support_status": "REPORTED" if len(values) >= 100 else "LIMITED_SUPPORT",
                })
    return pd.DataFrame(rows)


def summarize_correlations(data: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    splits = [("EXPLORATORY_APRIL_MAY", data[data["analysis_role"].eq("EXPLORATORY")]), ("CONFIRMATORY_JUNE", data[data["analysis_role"].eq("CONFIRMATORY")]), *[(month, data[data["month"].eq(month)]) for month in MONTHS]]
    for split, frame in splits:
        age = pd.to_numeric(frame["element_age_hours"], errors="coerce")
        for metric in OUTCOMES:
            values = pd.to_numeric(frame[metric], errors="coerce")
            valid = age.notna() & values.notna()
            if int(valid.sum()) >= 10 and age[valid].nunique() > 1 and values[valid].nunique() > 1:
                rho, pvalue = spearmanr(age[valid], values[valid])
            else:
                rho, pvalue = math.nan, math.nan
            rows.append({"analysis_split": split, "metric": metric, "n": int(valid.sum()), "spearman_rho": float(rho), "spearman_pvalue": float(pvalue), "minimum_n_met": bool(valid.sum() >= 10)})
    return pd.DataFrame(rows)


def elevation_bin(value: float) -> str:
    if value < 20:
        return "10-20"
    if value < 40:
        return "20-40"
    if value < 60:
        return "40-60"
    return "60-90"


def summarize_geometry(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = data.copy()
    frame["elevation_bin"] = pd.to_numeric(frame["public_mean_elevation_deg"]).map(elevation_bin)
    rows: list[dict[str, Any]] = []
    for split, split_frame in [("EXPLORATORY_APRIL_MAY", frame[frame["analysis_role"].eq("EXPLORATORY")]), ("CONFIRMATORY_JUNE", frame[frame["analysis_role"].eq("CONFIRMATORY")])]:
        for dimension in ["elevation_bin", "phase_label", "satellite_norad_id", "month", "station_id"]:
            grouped = split_frame.groupby(["freshness_bin", dimension], observed=True)
            for (freshness, level), group in grouped:
                for metric in GEOMETRY_OUTCOMES:
                    values = pd.to_numeric(group[metric], errors="coerce").dropna()
                    rows.append({"analysis_split": split, "freshness_bin": freshness, "geometry_dimension": dimension, "geometry_level": level, "metric": metric, "n": len(values), "median": float(values.median()) if len(values) else math.nan, "p90": qvalue(values, 0.90, 10)})
    summary = pd.DataFrame(rows)
    audits: list[dict[str, Any]] = []
    exploratory = summary[(summary["analysis_split"].eq("EXPLORATORY_APRIL_MAY")) & (summary["geometry_dimension"].isin(["elevation_bin", "phase_label"]))]
    pooled = {metric: float(pd.to_numeric(frame[metric]).median()) for metric in GEOMETRY_OUTCOMES}
    for metric in GEOMETRY_OUTCOMES:
        qualifying_bins = 0
        evidence: list[str] = []
        for freshness in FRESHNESS_LABELS:
            candidates = exploratory[(exploratory["metric"].eq(metric)) & (exploratory["freshness_bin"].eq(freshness)) & (exploratory["n"] >= 5)]
            for dimension in ["elevation_bin", "phase_label"]:
                group = candidates[candidates["geometry_dimension"].eq(dimension)]
                if len(group) < 2 or int(group["n"].sum()) < 20:
                    continue
                medians = pd.to_numeric(group["median"]).dropna()
                if len(medians) < 2:
                    continue
                minimum, maximum = float(medians.min()), float(medians.max())
                ratio = math.inf if minimum <= 1e-15 and maximum > 1e-15 else maximum / max(minimum, 1e-15)
                absolute_range = maximum - minimum
                if ratio >= 2.0 and absolute_range >= pooled[metric]:
                    qualifying_bins += 1
                    evidence.append(f"{freshness}:{dimension}:ratio={ratio:.6g}:range={absolute_range:.6g}")
                    break
        flag = qualifying_bins >= 2
        audits.append({"metric": metric, "qualifying_freshness_bins": qualifying_bins, "geometry_effect_nonnegligible": flag, "status": "GEOMETRY_EFFECT_NONNEGLIGIBLE" if flag else "NO_PREDECLARED_GEOMETRY_FLAG", "evidence": ";".join(evidence)})
    return summary, pd.DataFrame(audits)


def build_replication(correlations: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in OUTCOMES:
        exp = correlations[(correlations["analysis_split"].eq("EXPLORATORY_APRIL_MAY")) & (correlations["metric"].eq(metric))].iloc[0]
        june = correlations[(correlations["analysis_split"].eq("CONFIRMATORY_JUNE")) & (correlations["metric"].eq(metric))].iloc[0]
        exp_rho, june_rho = float(exp.spearman_rho), float(june.spearman_rho)
        signs_agree = bool(np.isfinite(exp_rho) and np.isfinite(june_rho) and np.sign(exp_rho) == np.sign(june_rho))
        structured_exp = bool(np.isfinite(exp_rho) and abs(exp_rho) >= 0.3 and float(exp.spearman_pvalue) < 0.01)
        structured_june = bool(np.isfinite(june_rho) and abs(june_rho) >= 0.3 and float(june.spearman_pvalue) < 0.01)
        rows.append({"metric": metric, "exploratory_rho": exp_rho, "exploratory_pvalue": float(exp.spearman_pvalue), "june_rho": june_rho, "june_pvalue": float(june.spearman_pvalue), "signs_agree": signs_agree, "exploratory_predeclared_structure": structured_exp, "june_predeclared_structure": structured_june, "structure_replicated": bool(signs_agree and structured_exp and structured_june)})
    return pd.DataFrame(rows)


def make_figures(data: pd.DataFrame) -> list[Path]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    order = FRESHNESS_LABELS
    colors = {"EXPLORATORY": "#3569b0", "CONFIRMATORY": "#d95f02"}
    specs = [
        ("raw_rms_hz", "Raw orbit-induced Doppler RMS vs freshness", "Raw RMS (Hz)", "orbit_error_raw_doppler_vs_freshness.png"),
        ("score_orbit_hz", "Post-b+kt production score vs freshness", "Score (Hz)", "orbit_error_score_vs_freshness.png"),
        ("abs_delta_k_orbit_hz_per_s", "Orbit-induced |Δk| vs freshness", "|Δk| (Hz/s)", "orbit_error_delta_k_vs_freshness.png"),
        ("explained_fraction", "b+kt absorption vs freshness", "Explained fraction", "orbit_error_ols_absorption_vs_freshness.png"),
    ]
    outputs: list[Path] = []
    for metric, title, ylabel, filename in specs:
        fig, ax = plt.subplots(figsize=(10, 5.8))
        for role, offset in [("EXPLORATORY", -0.12), ("CONFIRMATORY", 0.12)]:
            groups = [pd.to_numeric(data[(data["analysis_role"].eq(role)) & (data["freshness_bin"].eq(label))][metric], errors="coerce").dropna().to_numpy() for label in order]
            positions = np.arange(len(order), dtype=float) + offset
            nonempty = [(pos, values) for pos, values in zip(positions, groups) if len(values)]
            if nonempty:
                ax.boxplot([values for _, values in nonempty], positions=[pos for pos, _ in nonempty], widths=0.2, patch_artist=True, showfliers=False, boxprops={"facecolor": colors[role], "alpha": 0.55}, medianprops={"color": "black"})
        ax.set_xticks(np.arange(len(order)))
        ax.set_xticklabels(order)
        ax.set_xlabel("Ordinary GP element age bin")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
        ax.plot([], [], color=colors["EXPLORATORY"], linewidth=8, alpha=0.55, label="April+May exploratory")
        ax.plot([], [], color=colors["CONFIRMATORY"], linewidth=8, alpha=0.55, label="June confirmatory")
        ax.legend()
        fig.tight_layout()
        path = FIGURES / filename
        fig.savefig(path, dpi=180)
        plt.close(fig)
        outputs.append(path)
    return outputs


def markdown_table(frame: pd.DataFrame) -> str:
    return frame.to_markdown(index=False) if not frame.empty else "（无记录）"


def summarize(overwrite: bool) -> None:
    validate_protocol()
    population, population_manifest = validate_population()
    required = [EXPLORATORY_RESULTS, CONFIRMATORY_RESULTS, EXPLORATORY_MANIFEST, CONFIRMATORY_MANIFEST]
    if any(not path.exists() for path in required):
        raise SystemExit("Both exploratory and June confirmatory stages must be complete")
    outputs = [FINAL_SEGMENTS, FRESHNESS_SUMMARY, CORRELATIONS, GEOMETRY_SUMMARY, GEOMETRY_AUDIT, REPLICATION, FINAL_MANIFEST, REPORT]
    refuse_existing(outputs, overwrite)
    exp = pd.read_csv(EXPLORATORY_RESULTS, low_memory=False)
    june = pd.read_csv(CONFIRMATORY_RESULTS, low_memory=False)
    data = pd.concat([exp, june], ignore_index=True)
    if set(data["segment_id"]) != set(population["segment_id"]):
        raise SystemExit("Science results do not exactly cover frozen population")
    write_csv(FINAL_SEGMENTS, data.sort_values(["month", "satellite_norad_id", "pass_start_utc", "phase_label"]).reset_index(drop=True))
    freshness = summarize_freshness(data)
    correlations = summarize_correlations(data)
    geometry, geometry_audit = summarize_geometry(data)
    replication = build_replication(correlations)
    figures = make_figures(data)
    write_csv(FRESHNESS_SUMMARY, freshness)
    write_csv(CORRELATIONS, correlations)
    write_csv(GEOMETRY_SUMMARY, geometry)
    write_csv(GEOMETRY_AUDIT, geometry_audit)
    write_csv(REPLICATION, replication)

    exp_corr = correlations[correlations["analysis_split"].eq("EXPLORATORY_APRIL_MAY")]
    june_corr = correlations[correlations["analysis_split"].eq("CONFIRMATORY_JUNE")]
    exp_absorb = float(exp["explained_fraction"].median())
    june_absorb = float(june["explained_fraction"].median())
    geometry_flag = bool(geometry_audit["geometry_effect_nonnegligible"].any())
    replicated = replication.set_index("metric")["structure_replicated"].to_dict()
    raw_rep = bool(replicated.get("raw_rms_hz", False))
    score_rep = bool(replicated.get("score_orbit_hz", False))
    delta_b_rep = bool(replicated.get("abs_delta_b_orbit_hz", False))
    delta_k_rep = bool(replicated.get("abs_delta_k_orbit_hz_per_s", False))
    absorption_rep = bool(replicated.get("explained_fraction", False))
    if geometry_flag:
        verdict = "GEOMETRY_EFFECT_DOMINATES_OR_INTERACTS_STRONGLY"
    elif score_rep or delta_k_rep:
        verdict = "FRESHNESS_EFFECT_REMAINS_AFTER_OLS"
    else:
        verdict = "ORBIT_ERROR_MOSTLY_ABSORBED_BY_EXISTING_OLS"
    stage_b_warranted = bool(score_rep or delta_k_rep or geometry_flag)
    stage_b_focus = ", ".join(
        label for enabled, label in [
            (score_rep, "score"),
            (delta_k_rep, "delta_k"),
            (geometry_flag, "geometry"),
        ] if enabled
    ) or "none"

    key_metrics = freshness[(freshness["metric"].isin(["raw_rms_hz", "score_orbit_hz", "abs_delta_k_orbit_hz_per_s", "explained_fraction"])) & (~freshness["analysis_split"].eq("ALL_DESCRIPTIVE"))][["analysis_split", "freshness_bin", "metric", "n", "median", "p90", "p95", "p99", "p99_support_status"]]
    coverage = pd.read_csv(COVERAGE)
    report = f"""# 合法 A 公开轨道误差 → Doppler / OLS 输出实验报告

## 1. 研究边界与执行状态

本实验独立于旧 frozen joint-security population，只研究合法 A。April/May 为 exploratory，June 在 protocol 与 population SHA 冻结后才执行 confirmatory science。全程没有引入额外发射源、补偿、`b_env`、`k_env`、noise 或随机观测误差；没有执行 production b/k gate，也不报告 false reject rate。

reference 语义固定为 SpaceX-E/SupGP higher-quality historical reference，不是 ground truth、true orbit 或 exact state。

- protocol SHA：`{sha256(PROTOCOL)}`
- population SHA：`{sha256(POPULATION)}`
- population：{len(population)} segments / {population['pass_id'].nunique()} passes / {population['satellite_norad_id'].nunique()} satellites
- April+May：{len(exp)} segments；June：{len(june)} segments
- residual sign：`delta_f_orbit = F_ref - F_public`
- Stage-A final verdict：`{verdict}`

## 2. Freshness coverage

六个 bin 的总 segment 数：

{markdown_table(population.groupby(['analysis_role', 'freshness_bin'], observed=True).size().rename('segments').reset_index())}

satellite×month×bin 的完整 coverage 见 `outputs/metrics/orbit_error_to_doppler_legitimate_freshness_coverage.csv`。P99 只有 n≥100 时报告；不足时保留 `LIMITED_SUPPORT`，没有补窗口。

## 3. Raw Doppler 与 b+kt projection

{markdown_table(key_metrics)}

April/May explained-fraction median=`{exp_absorb:.6f}`；June median=`{june_absorb:.6f}`。`delta_b_orbit` / `delta_k_orbit` 仅表示轨道 disagreement 引起的增量 fitted shift，不是完整 production b/k。

跨 freshness bin 汇总时，April/May 的 raw RMS median/P90/P95/P99 为 `{exp['raw_rms_hz'].median():.2f} / {exp['raw_rms_hz'].quantile(.90):.2f} / {exp['raw_rms_hz'].quantile(.95):.2f} / {exp['raw_rms_hz'].quantile(.99):.2f} Hz`，production score 为 `{exp['score_orbit_hz'].median():.2f} / {exp['score_orbit_hz'].quantile(.90):.2f} / {exp['score_orbit_hz'].quantile(.95):.2f} / {exp['score_orbit_hz'].quantile(.99):.2f} Hz`；June 对应 raw RMS 为 `{june['raw_rms_hz'].median():.2f} / {june['raw_rms_hz'].quantile(.90):.2f} / {june['raw_rms_hz'].quantile(.95):.2f} / {june['raw_rms_hz'].quantile(.99):.2f} Hz`，score 为 `{june['score_orbit_hz'].median():.2f} / {june['score_orbit_hz'].quantile(.90):.2f} / {june['score_orbit_hz'].quantile(.95):.2f} / {june['score_orbit_hz'].quantile(.99):.2f} Hz`。分布有明显长尾，最大 raw RMS 在 April/May 与 June 分别达到 `{exp['raw_rms_hz'].max():.2f} Hz` 和 `{june['raw_rms_hz'].max():.2f} Hz`；这些单位按冻结排除规则保留，没有结果驱动剔除，且不得把它们解释为相对 ground truth 的误差。

预冻结 curvature flag 在 April/May 为 `{int(exp['obvious_curvature_flag'].sum())}/{len(exp)}`，June 为 `{int(june['obvious_curvature_flag'].sum())}/{len(june)}`。因此，“raw energy 大部分可被线性投影吸收”不等价于剩余曲线严格线性或 score 恒为零；curvature 与长尾是 Stage B 前需要继续审计 reference/geometry 分层的诊断信号。

## 4. Freshness association 与 June replication

{markdown_table(pd.concat([exp_corr, june_corr], ignore_index=True)[['analysis_split', 'metric', 'n', 'spearman_rho', 'spearman_pvalue']])}

{markdown_table(replication)}

相关系数只作连续-age描述；结论同时检查 bin median/quantile 与 June 符号、效应量和显著性复现，没有据此修改 bins 或 score。

## 5. Geometry diagnostic

{markdown_table(geometry_audit)}

固定站只有一个，无法估计 station-between effect。可检验的 geometry 包括预冻结 elevation bins、上升/峰值/下降 phase、satellite 与 month。完整分组表见 geometry summary。

## 6. Primary questions

1. raw Doppler 大小：见 freshness summary 的 `raw_rms_hz`；这是 public/reference disagreement 的 observation-space 映射。
2. raw error 是否随 freshness 增大：由 exploratory 与 June 的 bin quantile + Spearman replication 共同判断，见 replication 表。
3. b+kt 吸收量：explained fraction 的 exploratory/June median 分别为 `{exp_absorb:.6f}` / `{june_absorb:.6f}`。
4. projected score 是否仍受 freshness 影响：见 `score_orbit_hz` replication=`{score_rep}`；explained-fraction replication=`{absorption_rep}`。
5. Δb / Δk 是否随 freshness：`abs_delta_b_orbit_hz` replication=`{delta_b_rep}`；`abs_delta_k_orbit_hz_per_s` replication=`{delta_k_rep}`。本轮按协议不执行 b/k gate。
6. rejection attribution：不适用，本轮没有 verifier decision endpoint。
7. 鲁棒性：只能对 b+kt projection 的吸收能力作 Stage-A 诊断，不能转换为 false reject claim。
8. Stage B：warranted=`{stage_b_warranted}`，主要关注 `{stage_b_focus}`；若进入 Stage B，先冻结 nominal legitimate b/k anchor semantics，本轮不设计 threshold。
9. 若 Stage B 不值得，则应停止增加 online uncertainty layer；本轮 verdict 不修改现有 verifier。
10. geometry：predeclared flag=`{geometry_flag}`；若为 true，freshness-only 描述不足。

## 7. 保护与局限

- 旧 332 windows 未复用；407 Level-A、265-unit joint endpoint、orbit uncertainty parameters、thresholds、verifier 和 final synthesis 均未修改。
- population selection 不读取 `F_ref-F_public`、raw error、Δb、Δk、score 或 outcome。
- production Doppler 和 centered-time OLS 通过冻结源码 SHA 绑定。
- reference 最近历元限制为 3 h，使用单个 SupGP OMM propagation，不做状态插值。
- 单一固定站限制了 station heterogeneity 结论。

## 8. 最终 verdict

`{verdict}`

是否值得进入 Stage B：`{stage_b_warranted}`；建议关注：`{stage_b_focus}`。本结论仅针对 ordinary-GP/reference disagreement 对 verifier 内部量的增量影响，不是合法卫星 false-reject rate。
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    manifest = {
        "stage": "LEGITIMATE_ORBIT_ERROR_TO_DOPPLER_FINAL",
        "status": "COMPLETE",
        "generated_utc": iso_z(datetime.now(timezone.utc)),
        "verdict": verdict,
        "stage_b_warranted": stage_b_warranted,
        "stage_b_focus": stage_b_focus,
        "protocol": hash_record(PROTOCOL),
        "population": hash_record(POPULATION),
        "population_manifest": hash_record(POPULATION_MANIFEST),
        "exploratory_manifest": hash_record(EXPLORATORY_MANIFEST),
        "confirmatory_manifest": hash_record(CONFIRMATORY_MANIFEST),
        "segments": len(data),
        "exploratory_segments": len(exp),
        "confirmatory_segments": len(june),
        "production_bk_gate_executions": 0,
        "false_reject_endpoints": 0,
        "new_random_draw_count": 0,
        "protected_source_modifications": [],
        "outputs": [hash_record(path) for path in [FINAL_SEGMENTS, FRESHNESS_SUMMARY, CORRELATIONS, GEOMETRY_SUMMARY, GEOMETRY_AUDIT, REPLICATION, REPORT, *figures]],
        "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    write_json(FINAL_MANIFEST, manifest)
    append_log(manifest, population, exp, june, coverage, geometry_flag)
    print(json.dumps({"status": "COMPLETE", "verdict": verdict, "stage_b_warranted": stage_b_warranted, "stage_b_focus": stage_b_focus, "report": rel(REPORT), "segments": len(data)}, indent=2))


def append_log(manifest: dict[str, Any], population: pd.DataFrame, exp: pd.DataFrame, june: pd.DataFrame, coverage: pd.DataFrame, geometry_flag: bool) -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    limited = int((coverage["support_status"] == "LIMITED_SUPPORT").sum())
    entry = f"""

## {now} - 合法 A 公开轨道误差到 Doppler / OLS Stage-A

### A. 本轮目标

解除 March frozen windows 与 April–June SpaceX-E/SupGP reference 不重叠的 blocker，建立独立合法-A population，量化 ordinary-GP/reference disagreement 对 raw Doppler、增量 Δb/Δk、production score 与 b+kt absorption 的影响。

### B. 实际操作

先冻结 population protocol 与 SHA，再仅用 identity/time/public visibility/station/data availability 建立 April–June population 和 freshness coverage；冻结 population SHA 后执行 April/May exploratory，随后不改协议运行 June confirmatory；最后生成 freshness、Spearman、geometry、replication summaries 和四张图。

### C. 新增/修改文件

新增独立 legitimate population、audit、coverage、April/May results、June results、timeseries、metrics、figures、report、protocol/manifest 和执行脚本。没有修改配置、verifier、threshold、joint-security、orbit uncertainty 或其他 frozen results。

### D. 运行命令

`python scripts/run_orbit_error_to_doppler_legitimate_experiment.py --stage population`

`python scripts/run_orbit_error_to_doppler_legitimate_experiment.py --stage exploratory`

`python scripts/run_orbit_error_to_doppler_legitimate_experiment.py --stage confirmatory`

`python scripts/run_orbit_error_to_doppler_legitimate_experiment.py --stage summarize`

### E. 结果摘要

population={len(population)} segments/{population['pass_id'].nunique()} passes；April+May={len(exp)}，June={len(june)}；limited satellite×month×bin cells={limited}/{len(coverage)}；geometry flag={geometry_flag}；final verdict=`{manifest['verdict']}`；Stage B warranted=`{manifest['stage_b_warranted']}`，focus=`{manifest['stage_b_focus']}`。production b/k gate executions=0，false-reject endpoints=0，new random draws=0。

### F. 问题与下一步

本轮只回答 incremental Stage-A robustness。若 freshness structure 未在 June 复现则停止；若稳定复现，只建议下一阶段 calibration，不在本轮修改 verifier。若 geometry flag 为 true，则不能采用 freshness-only threshold。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def audit_protected_bindings(overwrite: bool) -> None:
    """Recheck pre-existing frozen bindings without changing any protected file."""
    refuse_existing([PROTECTED_BINDINGS_AUDIT, PROTECTED_BINDINGS_MANIFEST], overwrite)
    prior_path = METRICS / "orbit_error_to_doppler_feasibility_manifest.json"
    joint_path = METRICS / "joint_security_final_results_manifest.json"
    if not prior_path.exists() or not joint_path.exists():
        raise SystemExit("Frozen binding sources are unavailable")
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    joint = json.loads(joint_path.read_text(encoding="utf-8"))
    expected: dict[str, tuple[str, str]] = {}
    for record in prior.get("frozen_bindings", []):
        expected[str(record["path"])] = (str(record["expected_sha256"]).upper(), "prior_semantic_blocker_audit")

    def collect_records(value: Any, origin: str) -> None:
        if isinstance(value, dict):
            if "path" in value and "sha256" in value:
                path_text = str(value["path"])
                if not path_text.startswith("scripts/run_orbit_error_to_doppler_legitimate") and not path_text.startswith("outputs/datasets/legitimate_orbit_error"):
                    expected.setdefault(path_text, (str(value["sha256"]).upper(), origin))
            for nested in value.values():
                collect_records(nested, origin)
        elif isinstance(value, list):
            for nested in value:
                collect_records(nested, origin)

    collect_records(joint.get("sources", {}), "joint_security_final_results_manifest")
    collect_records(joint.get("outputs", []), "joint_security_final_results_manifest")
    frozen_parameters = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
    expected[rel(frozen_parameters)] = (
        str(joint["frozen_orbit_uncertainty_parameter_sha256"]).upper(),
        "joint_security_frozen_parameter_binding",
    )
    rows: list[dict[str, Any]] = []
    for path_text, (expected_sha, origin) in sorted(expected.items()):
        path = ROOT / path_text
        actual_sha = sha256(path) if path.exists() else ""
        rows.append({
            "path": path_text,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "binding_status": "PASS" if actual_sha == expected_sha else ("MISSING" if not path.exists() else "MISMATCH"),
            "binding_origin": origin,
        })
    audit = pd.DataFrame(rows)
    write_csv(PROTECTED_BINDINGS_AUDIT, audit)
    failures = audit[~audit["binding_status"].eq("PASS")]
    payload = {
        "stage": "LEGITIMATE_ORBIT_ERROR_PROTECTED_FROZEN_BINDING_AUDIT",
        "status": "PASS" if failures.empty else "FAIL",
        "generated_utc": iso_z(datetime.now(timezone.utc)),
        "checked_bindings": len(audit),
        "passed_bindings": int(audit["binding_status"].eq("PASS").sum()),
        "failed_bindings": len(failures),
        "protected_files_modified": failures["path"].tolist(),
        "source_manifests": [hash_record(prior_path), hash_record(joint_path)],
        "audit": hash_record(PROTECTED_BINDINGS_AUDIT),
    }
    write_json(PROTECTED_BINDINGS_MANIFEST, payload)
    if FINAL_MANIFEST.exists():
        final_manifest = json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))
        final_manifest["protected_frozen_bindings"] = {
            "status": payload["status"],
            "checked_bindings": payload["checked_bindings"],
            "passed_bindings": payload["passed_bindings"],
            "failed_bindings": payload["failed_bindings"],
            "audit": hash_record(PROTECTED_BINDINGS_AUDIT),
            "manifest": hash_record(PROTECTED_BINDINGS_MANIFEST),
        }
        final_manifest["protected_source_modifications"] = payload["protected_files_modified"]
        write_json(FINAL_MANIFEST, final_manifest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not failures.empty:
        raise SystemExit("Protected frozen binding audit failed")


def main() -> int:
    args = parse_args()
    if args.stage in {"population", "all"}:
        build_population(args.overwrite)
    if args.stage in {"exploratory", "all"}:
        execute_split("EXPLORATORY", args.overwrite)
    if args.stage in {"confirmatory", "all"}:
        execute_split("CONFIRMATORY", args.overwrite)
    if args.stage in {"summarize", "all"}:
        summarize(args.overwrite)
    if args.stage in {"protect", "all"}:
        audit_protected_bindings(args.overwrite)
    return 0


if __name__ == "__main__":
    sys.exit(main())
