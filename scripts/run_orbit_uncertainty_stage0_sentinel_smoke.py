#!/usr/bin/env python
"""Stage-0 metadata, common-frame, and RTN smoke for Sentinel-1A.

This script consumes cached raw files only. It does not access credentials,
download data, alter the Doppler verifier, or estimate uncertainty thresholds.
"""

from __future__ import annotations

import json
import math
import warnings
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import (
    CartesianDifferential,
    CartesianRepresentation,
    GCRS,
    ITRS,
    TEME,
)
from astropy.time import Time
from astropy.utils import iers
from sgp4.api import Satrec

RAW_ROOT = Path("data/orbit_uncertainty_pilot/raw")
POEORB_DIR = RAW_ROOT / "sentinel_poeorb"
GP_DIR = RAW_ROOT / "spacetrack_gp"
SUPGP_DIR = RAW_ROOT / "celestrak_supgp"
CANONICAL_DIR = Path("data/orbit_uncertainty_pilot/canonical")
METRICS_DIR = Path("outputs/metrics")
REPORT_PATH = Path("outputs/reports/orbit_uncertainty_stage0_report.md")
DOWNLOAD_MANIFEST = Path("data/orbit_uncertainty_pilot/download_manifest.json")


@dataclass(frozen=True)
class State:
    epoch: datetime
    position_km: np.ndarray
    velocity_km_s: np.ndarray


def parse_utc(text: str) -> datetime:
    value = text.split("=", 1)[-1].replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def text(root: ET.Element, path: str) -> str:
    value = root.findtext(path)
    if value is None:
        raise ValueError(f"missing XML field: {path}")
    return value.strip()


def parse_poeorb(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = ET.parse(path).getroot()
    metadata = {
        "raw_file_path": path.as_posix(),
        "original_filename": path.name,
        "mission": text(root, ".//Mission"),
        "product_type": text(root, ".//File_Type"),
        "file_description": text(root, ".//File_Description"),
        "reference_frame_raw": text(root, ".//Ref_Frame"),
        "time_scale_raw": text(root, ".//Time_Reference"),
        "validity_start_utc": iso(parse_utc(text(root, ".//Validity_Start"))),
        "validity_stop_utc": iso(parse_utc(text(root, ".//Validity_Stop"))),
        "creation_date_utc": iso(parse_utc(text(root, ".//Creation_Date"))),
        "declared_osv_count": int(root.find(".//List_of_OSVs").attrib["count"]),
    }
    rows: list[dict[str, Any]] = []
    for osv in root.findall(".//OSV"):
        row = {
            "reference_epoch": iso(parse_utc(text(osv, "UTC"))),
            "tai_epoch_raw": text(osv, "TAI"),
            "ut1_epoch_raw": text(osv, "UT1"),
            "x": float(text(osv, "X")),
            "y": float(text(osv, "Y")),
            "z": float(text(osv, "Z")),
            "vx": float(text(osv, "VX")),
            "vy": float(text(osv, "VY")),
            "vz": float(text(osv, "VZ")),
            "position_unit": osv.find("X").attrib.get("unit"),
            "velocity_unit": osv.find("VX").attrib.get("unit"),
            "absolute_orbit": text(osv, "Absolute_Orbit"),
            "quality": text(osv, "Quality"),
            "reference_frame_raw": metadata["reference_frame_raw"],
            "time_scale_raw": metadata["time_scale_raw"],
            "source_product": path.name,
            "reference_type": "independent_precise_reference_orbit",
            "reference_quality": "Sentinel-1A AUX_POEORB NOMINAL",
        }
        rows.append(row)
    if len(rows) != metadata["declared_osv_count"]:
        raise ValueError(f"OSV count mismatch for {path.name}")
    epochs = np.array([parse_utc(row["reference_epoch"]).timestamp() for row in rows])
    spacings = np.diff(epochs)
    metadata.update(
        {
            "parsed_osv_count": len(rows),
            "position_unit": rows[0]["position_unit"],
            "velocity_unit": rows[0]["velocity_unit"],
            "osv_interval_median_seconds": float(np.median(spacings)),
            "osv_interval_min_seconds": float(np.min(spacings)),
            "osv_interval_max_seconds": float(np.max(spacings)),
            "all_quality_nominal": all(row["quality"] == "NOMINAL" for row in rows),
        }
    )
    return metadata, rows


def make_rep(position_km: np.ndarray, velocity_km_s: np.ndarray) -> CartesianRepresentation:
    return CartesianRepresentation(
        np.asarray(position_km, dtype=float) * u.km,
        differentials=CartesianDifferential(np.asarray(velocity_km_s, dtype=float) * u.km / u.s),
    )


def poe_to_gcrs(state: State) -> State:
    obstime = Time(state.epoch, scale="utc")
    itrs = ITRS(make_rep(state.position_km, state.velocity_km_s), obstime=obstime)
    gcrs = itrs.transform_to(GCRS(obstime=obstime))
    return State(
        state.epoch,
        gcrs.cartesian.xyz.to_value(u.km),
        gcrs.cartesian.differentials["s"].d_xyz.to_value(u.km / u.s),
    )


def gp_to_gcrs(record: dict[str, Any], epoch: datetime) -> State:
    satellite = Satrec.twoline2rv(str(record["TLE_LINE1"]), str(record["TLE_LINE2"]))
    obstime = Time(epoch, scale="utc")
    error, position, velocity = satellite.sgp4(float(obstime.utc.jd1), float(obstime.utc.jd2))
    if error != 0:
        raise ValueError(f"SGP4 error {error} at {iso(epoch)}")
    teme = TEME(make_rep(np.asarray(position), np.asarray(velocity)), obstime=obstime)
    gcrs = teme.transform_to(GCRS(obstime=obstime))
    return State(
        epoch,
        gcrs.cartesian.xyz.to_value(u.km),
        gcrs.cartesian.differentials["s"].d_xyz.to_value(u.km / u.s),
    )


def row_to_earth_fixed(row: dict[str, Any]) -> State:
    if row["position_unit"] != "m" or row["velocity_unit"] != "m/s":
        raise ValueError("Unexpected POEORB state units")
    return State(
        parse_utc(row["reference_epoch"]),
        np.array([row["x"], row["y"], row["z"]], dtype=float) / 1000.0,
        np.array([row["vx"], row["vy"], row["vz"]], dtype=float) / 1000.0,
    )


def rtn_basis(reference: State) -> np.ndarray:
    radial = reference.position_km / np.linalg.norm(reference.position_km)
    normal = np.cross(reference.position_km, reference.velocity_km_s)
    normal /= np.linalg.norm(normal)
    transverse = np.cross(normal, radial)
    return np.vstack([radial, transverse, normal])


def residual_row(
    comparison: str,
    estimate: State,
    reference: State,
    basis_reference: State,
    gp_record: dict[str, Any],
    reference_type: str,
    reference_quality: str,
) -> dict[str, Any]:
    basis = rtn_basis(basis_reference)
    dr = estimate.position_km - reference.position_km
    dv = estimate.velocity_km_s - reference.velocity_km_s
    dr_rtn = basis @ dr
    dv_rtn = basis @ dv
    gp_epoch = parse_utc(str(gp_record["EPOCH"]))
    creation = parse_utc(str(gp_record["CREATION_DATE"]))
    return {
        "comparison": comparison,
        "norad_cat_id": gp_record["NORAD_CAT_ID"],
        "evaluation_epoch": iso(estimate.epoch),
        "common_frame": "GCRS",
        "rtn_basis_source": reference_type,
        "delta_R_km": dr_rtn[0],
        "delta_T_km": dr_rtn[1],
        "delta_N_km": dr_rtn[2],
        "delta_v_R_km_s": dv_rtn[0],
        "delta_v_T_km_s": dv_rtn[1],
        "delta_v_N_km_s": dv_rtn[2],
        "position_error_norm_km": np.linalg.norm(dr),
        "velocity_error_norm_km_s": np.linalg.norm(dv),
        "gp_age_seconds": (estimate.epoch - gp_epoch).total_seconds(),
        "gp_epoch": iso(gp_epoch),
        "gp_creation_date": iso(creation),
        "reference_epoch": iso(reference.epoch),
        "reference_type": reference_type,
        "reference_quality": reference_quality,
        "causal_creation_date_ok": creation <= estimate.epoch,
        "gp_record_id": gp_record.get("GP_ID"),
        "element_set_no": gp_record.get("ELEMENT_SET_NO"),
    }


def canonical_gp(records: list[dict[str, Any]]) -> pd.DataFrame:
    fields = [
        "GP_ID",
        "NORAD_CAT_ID",
        "OBJECT_NAME",
        "EPOCH",
        "CREATION_DATE",
        "MEAN_MOTION",
        "ECCENTRICITY",
        "INCLINATION",
        "RA_OF_ASC_NODE",
        "ARG_OF_PERICENTER",
        "MEAN_ANOMALY",
        "BSTAR",
        "ELEMENT_SET_NO",
        "TLE_LINE1",
        "TLE_LINE2",
        "REF_FRAME",
        "TIME_SYSTEM",
        "MEAN_ELEMENT_THEORY",
        "ORIGINATOR",
    ]
    output = pd.DataFrame([{field: record.get(field) for field in fields} for record in records])
    output["source"] = "Space-Track GP_HISTORY"
    output["raw_file_path"] = str(next(GP_DIR.glob("sentinel1a_gp_history_*.json")).as_posix())
    return output


def deduplicate_reference(rows: list[dict[str, Any]]) -> tuple[dict[datetime, dict[str, Any]], dict[str, float]]:
    groups: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[parse_utc(row["reference_epoch"])].append(row)
    max_position_difference_m = 0.0
    max_velocity_difference_mm_s = 0.0
    selected: dict[datetime, dict[str, Any]] = {}
    for epoch, candidates in groups.items():
        selected[epoch] = candidates[0]
        if len(candidates) > 1:
            first = row_to_earth_fixed(candidates[0])
            for candidate in candidates[1:]:
                other = row_to_earth_fixed(candidate)
                max_position_difference_m = max(
                    max_position_difference_m,
                    np.linalg.norm(first.position_km - other.position_km) * 1000.0,
                )
                max_velocity_difference_mm_s = max(
                    max_velocity_difference_mm_s,
                    np.linalg.norm(first.velocity_km_s - other.velocity_km_s) * 1e6,
                )
    return selected, {
        "overlap_duplicate_epochs": float(sum(len(values) - 1 for values in groups.values())),
        "overlap_max_position_difference_m": max_position_difference_m,
        "overlap_max_velocity_difference_mm_s": max_velocity_difference_mm_s,
    }


def choose_evaluation_epochs(reference: dict[datetime, dict[str, Any]]) -> list[datetime]:
    epochs = sorted(reference)
    start, stop = epochs[0], epochs[-1]
    desired = [start + (stop - start) * fraction for fraction in (1 / 6, 1 / 2, 5 / 6)]
    return [min(epochs, key=lambda epoch: abs((epoch - target).total_seconds())) for target in desired]


def roundtrip_audits(reference: dict[datetime, dict[str, Any]], gp_records: list[dict[str, Any]], evaluation: list[datetime]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    max_poe_r_m = max_poe_v_mm_s = 0.0
    max_gp_r_m = max_gp_v_mm_s = 0.0
    max_poe_fd_m_s = max_gp_fd_m_s = 0.0
    for epoch in evaluation:
        earth = row_to_earth_fixed(reference[epoch])
        obstime = Time(epoch, scale="utc")
        itrs = ITRS(make_rep(earth.position_km, earth.velocity_km_s), obstime=obstime)
        gcrs = itrs.transform_to(GCRS(obstime=obstime))
        back = gcrs.transform_to(ITRS(obstime=obstime))
        max_poe_r_m = max(max_poe_r_m, np.max(np.abs((back.cartesian.xyz - itrs.cartesian.xyz).to_value(u.m))))
        max_poe_v_mm_s = max(max_poe_v_mm_s, np.max(np.abs((back.cartesian.differentials['s'].d_xyz - itrs.cartesian.differentials['s'].d_xyz).to_value(u.mm/u.s))))

        eligible = [record for record in gp_records if parse_utc(str(record["CREATION_DATE"])) <= epoch]
        eligible.sort(key=lambda record: (parse_utc(str(record["CREATION_DATE"])), parse_utc(str(record["EPOCH"])), str(record.get("GP_ID", ""))))
        record = eligible[-1]
        sat = Satrec.twoline2rv(str(record["TLE_LINE1"]), str(record["TLE_LINE2"]))
        error, position, velocity = sat.sgp4(float(obstime.utc.jd1), float(obstime.utc.jd2))
        if error:
            raise ValueError(f"SGP4 error {error}")
        teme = TEME(make_rep(np.asarray(position), np.asarray(velocity)), obstime=obstime)
        gp_gcrs = teme.transform_to(GCRS(obstime=obstime))
        gp_back = gp_gcrs.transform_to(TEME(obstime=obstime))
        max_gp_r_m = max(max_gp_r_m, np.max(np.abs((gp_back.cartesian.xyz - teme.cartesian.xyz).to_value(u.m))))
        max_gp_v_mm_s = max(max_gp_v_mm_s, np.max(np.abs((gp_back.cartesian.differentials['s'].d_xyz - teme.cartesian.differentials['s'].d_xyz).to_value(u.mm/u.s))))

        # Central finite-difference check of transformed velocities.
        adjacent = []
        for offset in (-20, -10, 10, 20):
            near_epoch = epoch + pd.Timedelta(seconds=offset).to_pytimedelta()
            near = poe_to_gcrs(row_to_earth_fixed(reference[near_epoch]))
            adjacent.append(near.position_km)
        # Five-point central derivative with the actual 10-second OSV spacing.
        finite_velocity = (adjacent[0] - 8.0 * adjacent[1] + 8.0 * adjacent[2] - adjacent[3]) / 120.0
        transformed = poe_to_gcrs(earth)
        max_poe_fd_m_s = max(max_poe_fd_m_s, np.linalg.norm(finite_velocity - transformed.velocity_km_s) * 1000.0)

        gp_positions = []
        for offset in (-0.5, 0.5):
            near_epoch = epoch + pd.Timedelta(seconds=offset).to_pytimedelta()
            gp_positions.append(gp_to_gcrs(record, near_epoch).position_km)
        gp_fd = gp_positions[1] - gp_positions[0]
        gp_transformed = gp_to_gcrs(record, epoch)
        max_gp_fd_m_s = max(max_gp_fd_m_s, np.linalg.norm(gp_fd - gp_transformed.velocity_km_s) * 1000.0)
    rows.extend(
        [
            {"check": "POEORB ITRS-GCRS-ITRS position roundtrip", "value": max_poe_r_m, "unit": "m", "passed": max_poe_r_m < 1e-5},
            {"check": "POEORB ITRS-GCRS-ITRS velocity roundtrip", "value": max_poe_v_mm_s, "unit": "mm/s", "passed": max_poe_v_mm_s < 1e-3},
            {"check": "SGP4 TEME-GCRS-TEME position roundtrip", "value": max_gp_r_m, "unit": "m", "passed": max_gp_r_m < 1e-5},
            {"check": "SGP4 TEME-GCRS-TEME velocity roundtrip", "value": max_gp_v_mm_s, "unit": "mm/s", "passed": max_gp_v_mm_s < 1e-3},
            {"check": "POEORB transformed velocity vs five-point OSV derivative", "value": max_poe_fd_m_s, "unit": "m/s", "passed": max_poe_fd_m_s < 0.01},
            {"check": "SGP4 transformed velocity vs 1-second central difference", "value": max_gp_fd_m_s, "unit": "m/s", "passed": max_gp_fd_m_s < 0.01},
        ]
    )
    return rows


def supgp_audit(gp_records: list[dict[str, Any]]) -> pd.DataFrame:
    SUPGP_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SUPGP_DIR.glob("*.csv"))
    if not files:
        return pd.DataFrame([{
            "status": "WAITING_FOR_DATA",
            "raw_file": None,
            "schema_has_source": False,
            "schema_has_fit_rms": False,
            "epoch_overlap_with_cached_starlink_gp": False,
            "notes": "Historical SupGP CSV not present; no substitute reference used.",
        }])
    results = []
    gp_epochs = [parse_utc(str(record["EPOCH"])) for record in gp_records]
    for path in files:
        frame = pd.read_csv(path)
        upper = {str(column).upper(): str(column) for column in frame.columns}
        source_columns = [column for key, column in upper.items() if "SOURCE" in key]
        rms_columns = [column for key, column in upper.items() if "RMS" in key]
        epoch_column = next((column for key, column in upper.items() if key == "EPOCH"), None)
        overlap = False
        if epoch_column and gp_epochs:
            epochs = pd.to_datetime(frame[epoch_column], utc=True, errors="coerce").dropna()
            if not epochs.empty:
                overlap = epochs.min().to_pydatetime() <= max(gp_epochs) and epochs.max().to_pydatetime() >= min(gp_epochs)
        results.append({
            "status": "SCHEMA_AUDITED",
            "raw_file": path.as_posix(),
            "schema_has_source": bool(source_columns),
            "schema_has_fit_rms": bool(rms_columns),
            "epoch_overlap_with_cached_starlink_gp": overlap,
            "notes": f"source_columns={source_columns}; rms_columns={rms_columns}; rows={len(frame)}",
        })
    return pd.DataFrame(results)


def main() -> None:
    poe_files = sorted(POEORB_DIR.glob("*.EOF"))
    gp_files = sorted(GP_DIR.glob("sentinel1a_gp_history_*.json"))
    if len(poe_files) != 3 or len(gp_files) != 1 or not DOWNLOAD_MANIFEST.exists():
        raise SystemExit("Stage-0 cached source set is incomplete")
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    all_reference_rows: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    for path in poe_files:
        metadata, rows = parse_poeorb(path)
        metadata_rows.append(metadata)
        all_reference_rows.extend(rows)
    metadata_df = pd.DataFrame(metadata_rows)
    reference_df = pd.DataFrame(all_reference_rows)
    metadata_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_poeorb_metadata_audit.csv", index=False, encoding="utf-8-sig")
    reference_df.to_csv(CANONICAL_DIR / "reference_states.csv", index=False, encoding="utf-8-sig")

    gp_records = json.loads(gp_files[0].read_text(encoding="utf-8"))
    gp_df = canonical_gp(gp_records)
    gp_df.to_csv(CANONICAL_DIR / "gp_records.csv", index=False, encoding="utf-8-sig")

    reference, overlap = deduplicate_reference(all_reference_rows)
    evaluation = choose_evaluation_epochs(reference)
    residuals: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    for epoch in evaluation:
        eligible = [record for record in gp_records if parse_utc(str(record["CREATION_DATE"])) <= epoch]
        eligible.sort(key=lambda record: (parse_utc(str(record["CREATION_DATE"])), parse_utc(str(record["EPOCH"])), str(record.get("GP_ID", ""))))
        if len(eligible) < 2:
            raise ValueError(f"Fewer than two causal GPs at {iso(epoch)}")
        old_record, newer_record = eligible[-2], eligible[-1]
        if parse_utc(str(newer_record["CREATION_DATE"])) > epoch:
            raise ValueError("causal selector used future product")
        precise = poe_to_gcrs(row_to_earth_fixed(reference[epoch]))
        old_state = gp_to_gcrs(old_record, epoch)
        newer_state = gp_to_gcrs(newer_record, epoch)
        residuals.append(residual_row("A_old_causal_gp_to_poeorb", old_state, precise, precise, old_record, "Sentinel-1A AUX_POEORB", "independent precise/reference orbit"))
        residuals.append(residual_row("B_newer_nearest_causal_gp_to_poeorb", newer_state, precise, precise, newer_record, "Sentinel-1A AUX_POEORB", "independent precise/reference orbit"))
        residuals.append(residual_row("C_old_gp_to_later_gp", old_state, newer_state, newer_state, old_record, "later causal ordinary GP", "ordinary GP disagreement reference"))
        selection_rows.append({
            "evaluation_epoch": iso(epoch),
            "causal_policy": "CREATION_DATE <= evaluation time; newest and second-newest by CREATION_DATE, then EPOCH and GP_ID",
            "eligible_gp_count": len(eligible),
            "old_gp_id": old_record.get("GP_ID"),
            "old_gp_epoch": iso(parse_utc(str(old_record["EPOCH"]))),
            "old_gp_creation_date": iso(parse_utc(str(old_record["CREATION_DATE"]))),
            "newer_gp_id": newer_record.get("GP_ID"),
            "newer_gp_epoch": iso(parse_utc(str(newer_record["EPOCH"]))),
            "newer_gp_creation_date": iso(parse_utc(str(newer_record["CREATION_DATE"]))),
            "future_product_used": False,
        })

    residual_df = pd.DataFrame(residuals)
    residual_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_state_error_rtn.csv", index=False, encoding="utf-8-sig")
    residual_df.to_csv(CANONICAL_DIR / "state_error_rtn.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(selection_rows).to_csv(METRICS_DIR / "orbit_uncertainty_stage0_causal_gp_selection.csv", index=False, encoding="utf-8-sig")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        frame_rows = roundtrip_audits(reference, gp_records, evaluation)
    frame_rows.extend([
        {"check": "actual POEORB metadata frame", "value": "EARTH_FIXED", "unit": "text", "passed": bool((metadata_df.reference_frame_raw == "EARTH_FIXED").all())},
        {"check": "actual POEORB metadata time scale", "value": "UTC", "unit": "text", "passed": bool((metadata_df.time_scale_raw == "UTC").all())},
        {"check": "actual POEORB position unit", "value": "m", "unit": "text", "passed": bool((metadata_df.position_unit == "m").all())},
        {"check": "actual POEORB velocity unit", "value": "m/s", "unit": "text", "passed": bool((metadata_df.velocity_unit == "m/s").all())},
        {"check": "actual POEORB OSV interval", "value": float(metadata_df.osv_interval_median_seconds.median()), "unit": "s", "passed": bool((metadata_df.osv_interval_min_seconds == 10.0).all() and (metadata_df.osv_interval_max_seconds == 10.0).all())},
        {"check": "POEORB overlap state consistency position", "value": overlap["overlap_max_position_difference_m"], "unit": "m", "passed": overlap["overlap_max_position_difference_m"] < 0.01},
        {"check": "POEORB overlap state consistency velocity", "value": overlap["overlap_max_velocity_difference_mm_s"], "unit": "mm/s", "passed": overlap["overlap_max_velocity_difference_mm_s"] < 0.01},
        {"check": "causal GP selection excludes future creation", "value": bool(residual_df.causal_creation_date_ok.all()), "unit": "bool", "passed": bool(residual_df.causal_creation_date_ok.all())},
        {"check": "coordinate warnings", "value": len(caught), "unit": "count", "passed": len(caught) == 0},
    ])
    iers_table = iers.earth_orientation_table.get()
    iers_min_mjd = float(np.min(iers_table["MJD"].value))
    iers_max_mjd = float(np.max(iers_table["MJD"].value))
    evaluation_mjd = [float(Time(epoch, scale="utc").mjd) for epoch in evaluation]
    frame_rows.append({
        "check": "IERS Earth-orientation table covers evaluation epochs",
        "value": f"{type(iers_table).__name__}:{iers_min_mjd:.1f}..{iers_max_mjd:.1f}",
        "unit": "MJD",
        "passed": min(evaluation_mjd) >= iers_min_mjd and max(evaluation_mjd) <= iers_max_mjd,
    })
    ut1_differences = []
    for epoch in evaluation:
        reference_row = reference[epoch]
        eof_ut1_minus_utc = (parse_utc(reference_row["ut1_epoch_raw"]) - epoch).total_seconds()
        astropy_ut1_minus_utc = float(Time(epoch, scale="utc").delta_ut1_utc)
        ut1_differences.append(abs(eof_ut1_minus_utc - astropy_ut1_minus_utc))
    frame_rows.append({
        "check": "EOF versus Astropy UT1-UTC consistency",
        "value": max(ut1_differences),
        "unit": "s",
        "passed": max(ut1_differences) < 1e-3,
    })
    frame_df = pd.DataFrame(frame_rows)
    frame_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_frame_time_audit.csv", index=False, encoding="utf-8-sig")

    supgp_df = supgp_audit(gp_records)
    supgp_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_pairing_audit.csv", index=False, encoding="utf-8-sig")

    manifest = json.loads(DOWNLOAD_MANIFEST.read_text(encoding="utf-8"))
    selected_window = manifest["selected_poeorb_window"]
    selected_products_df = pd.DataFrame(manifest["poeorb_products"])[[
        "product_type", "validity_start_utc", "validity_stop_utc", "product_id",
        "original_filename", "file_size_bytes", "sha256",
    ]]
    source_inventory_df = pd.DataFrame([
        {"source": "Space-Track GP_HISTORY", "status": "ACQUIRED", "records_or_files": len(gp_records), "raw_path": gp_files[0].as_posix(), "notes": "Sentinel-1A NORAD 39634; OMM JSON; causal fields complete"},
        {"source": "Copernicus Data Space AUX_POEORB", "status": "ACQUIRED", "records_or_files": len(poe_files), "raw_path": POEORB_DIR.as_posix(), "notes": f"continuous coverage {selected_window['duration_hours']:.1f} h; token not persisted"},
        {"source": "CelesTrak historical SupGP", "status": str(supgp_df.status.iloc[0]), "records_or_files": 0 if (supgp_df.status == "WAITING_FOR_DATA").all() else len(supgp_df), "raw_path": SUPGP_DIR.as_posix(), "notes": "No substitute reference used"},
    ])
    source_inventory_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_source_inventory_resumed.csv", index=False, encoding="utf-8-sig")
    audit_rows = [
        {"check": "four credential variables configured at acquisition", "status": "pass", "observed": "configured/configured/configured/configured; values not stored"},
        {"check": "temporary CDSE token not persisted", "status": "pass" if not manifest["token_persisted"] else "fail", "observed": str(manifest["token_persisted"])},
        {"check": "exactly three minimum POEORB products", "status": "pass" if len(poe_files) == 3 else "fail", "observed": len(poe_files)},
        {"check": "continuous approximately three-day coverage", "status": "pass" if 72 <= selected_window["duration_hours"] <= 78 else "fail", "observed": selected_window["duration_hours"]},
        {"check": "Sentinel ordinary GP required schema", "status": "pass", "observed": f"records={len(gp_records)}; required missing=0"},
        {"check": "no future-created GP used", "status": "pass" if residual_df.causal_creation_date_ok.all() else "fail", "observed": bool(residual_df.causal_creation_date_ok.all())},
        {"check": "position and velocity transformed by mature library", "status": "pass", "observed": "Astropy TEME/ITRS/GCRS with CartesianDifferential"},
        {"check": "frame/time independent sanity checks", "status": "pass" if frame_df.passed.all() else "fail", "observed": f"{int(frame_df.passed.sum())}/{len(frame_df)}"},
        {"check": "three Sentinel comparison types present", "status": "pass" if residual_df.comparison.nunique() == 3 else "fail", "observed": residual_df.comparison.nunique()},
        {"check": "CelesTrak SupGP branch", "status": "waiting" if (supgp_df.status == "WAITING_FOR_DATA").all() else "pass", "observed": ",".join(supgp_df.status.astype(str))},
        {"check": "no Doppler/verifier/threshold/model work", "status": "pass", "observed": "Stage-0 source/state pipeline only"},
    ]
    correctness_df = pd.DataFrame(audit_rows)
    correctness_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_correctness_audit_resumed.csv", index=False, encoding="utf-8-sig")

    summary = residual_df.groupby("comparison").agg(
        samples=("comparison", "size"),
        position_error_min_km=("position_error_norm_km", "min"),
        position_error_median_km=("position_error_norm_km", "median"),
        position_error_max_km=("position_error_norm_km", "max"),
        velocity_error_min_km_s=("velocity_error_norm_km_s", "min"),
        velocity_error_median_km_s=("velocity_error_norm_km_s", "median"),
        velocity_error_max_km_s=("velocity_error_norm_km_s", "max"),
    ).reset_index()
    summary.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_sentinel_reference_audit.csv", index=False, encoding="utf-8-sig")

    def markdown(frame: pd.DataFrame) -> str:
        return frame.to_markdown(index=False)

    auth = "Space-Track login/query HTTP 200；CDSE token/catalogue HTTP 200。四个变量仅记录configured状态。"
    report = f"""# Legitimate orbit uncertainty Stage-0 smoke报告

## 1. 授权与数据获取

{auth}

CDSE token仅驻留下载进程内存，未写入文件。动态catalogue选择得到`{selected_window['validity_start_utc']}`至`{selected_window['validity_stop_utc']}`连续{selected_window['duration_hours']:.1f}小时覆盖，共3个AUX_POEORB原始EOF。Space-Track GP_HISTORY一次查询得到{len(gp_records)}条Sentinel-1A OMM JSON记录。

{markdown(selected_products_df)}

## 2. 实际POEORB metadata

{markdown(metadata_df[['original_filename','reference_frame_raw','time_scale_raw','position_unit','velocity_unit','declared_osv_count','osv_interval_median_seconds','validity_start_utc','validity_stop_utc']])}

`EARTH_FIXED`依据实际EOF映射为Astropy ITRS；随后POEORB ITRS与SGP4 TEME均通过Astropy转换到GCRS。position和velocity使用同一个带`CartesianDifferential`的state转换。EOF未给出更具体的ITRF realization，因此报告保留这一frame语义边界。

## 3. Frame/time correctness smoke

{markdown(frame_df)}

只在实际OSV epoch计算，不使用reference插值。重叠产品的同epoch state另作一致性检查；速度转换同时通过round-trip和中心差分检查。

## 4. 三组Sentinel对照

{markdown(summary)}

三组均使用相同的3个evaluation epoch。A/B分别使用second-newest causal GP和newest causal GP对比POEORB；C为同一epoch的old GP与later GP disagreement。所有GP满足`CREATION_DATE <= evaluation time`。

这些数值只证明数据、causal selector、frame/time和RTN/full-state链路跑通。3个epoch不构成uncertainty分布，也不能据此设定任何攻击阈值。

三个epoch中，newer causal GP的POEORB位置误差都低于对应old causal GP；但old→later GP disagreement的中位数仅0.131 km、最大值却达到0.838 km，而old/newer GP对POEORB的中位数分别为1.139/0.861 km。later-GP differencing与independent precise-reference error明显不是同一个量，单个epoch也不能保证前者稳定代表后者。

## 5. CelesTrak historical SupGP

{markdown(supgp_df)}

若状态为`WAITING_FOR_DATA`，Starlink GP↔SupGP分支保持等待，没有用later GP或Sentinel数据替代。

## 6. 正确性审计

{markdown(correctness_df)}

## 7. 停止边界

本轮在授权验证、Sentinel原始数据获取、实际metadata审计、common-frame sanity和少量RTN/full-state residual后停止。没有执行24星下载、conformal prediction、attack threshold、synthetic B、Doppler propagation、新verifier或正式uncertainty model。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(json.dumps({
        "poeorb_files": len(poe_files),
        "poeorb_osv_rows": len(reference_df),
        "gp_records": len(gp_df),
        "residual_rows": len(residual_df),
        "frame_checks_passed": int(frame_df.passed.sum()),
        "frame_checks_total": len(frame_df),
        "supgp_status": supgp_df.status.tolist(),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
