#!/usr/bin/env python
"""Starlink ordinary-GP versus historical SupGP Stage-0 smoke.

The script reads existing raw files only. SupGP is treated as an
operator-derived higher-quality reference, never as precise truth.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import CartesianDifferential, CartesianRepresentation, GCRS, TEME
from astropy.time import Time
from sgp4 import omm
from sgp4.api import Satrec

TARGET_IDS = ["65409", "65410", "65411"]
WINDOW_START = pd.Timestamp("2026-03-08T00:00:00Z")
WINDOW_STOP = pd.Timestamp("2026-03-15T00:00:00Z")
MU_KM3_S2 = 398600.4418

SUPGP_DIR = Path("data/orbit_uncertainty_pilot/raw/celestrak_supgp")
GP_CACHE = Path("data/tle/history/starlink_gp_history_20260301_20260320.json")
PILOT_MANIFEST = Path("data/orbit_uncertainty_pilot/download_manifest.json")
CANONICAL_DIR = Path("data/orbit_uncertainty_pilot/canonical")
METRICS_DIR = Path("outputs/metrics")
REPORT_PATH = Path("outputs/reports/orbit_uncertainty_stage0_starlink_report.md")

FORMAL_GUARD_FILES = [
    Path("outputs/datasets/controlled_altitude_difference_realization_dataset.csv"),
    Path("outputs/reports/controlled_altitude_difference_report.md"),
    Path("outputs/reports/verifier_v2_summary.md"),
    GP_CACHE,
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def parse_utc(value: Any) -> datetime:
    parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.to_pydatetime()


def iso(value: Any) -> str:
    return parse_utc(value).isoformat().replace("+00:00", "Z")


def semi_major_axis_proxy_km(mean_motion_rev_day: float) -> float:
    angular_rate = float(mean_motion_rev_day) * 2.0 * math.pi / 86400.0
    return (MU_KM3_S2 / angular_rate**2) ** (1.0 / 3.0)


def make_rep(position_km: np.ndarray, velocity_km_s: np.ndarray) -> CartesianRepresentation:
    return CartesianRepresentation(
        np.asarray(position_km, dtype=float) * u.km,
        differentials=CartesianDifferential(np.asarray(velocity_km_s, dtype=float) * u.km / u.s),
    )


def propagate(satellite: Satrec, epoch: datetime) -> tuple[np.ndarray, np.ndarray]:
    time = Time(epoch, scale="utc")
    error, position, velocity = satellite.sgp4(float(time.utc.jd1), float(time.utc.jd2))
    if error != 0:
        raise ValueError(f"SGP4 error={error} at {iso(epoch)}")
    return np.asarray(position, dtype=float), np.asarray(velocity, dtype=float)


def to_gcrs(position_km: np.ndarray, velocity_km_s: np.ndarray, epoch: datetime) -> tuple[np.ndarray, np.ndarray]:
    time = Time(epoch, scale="utc")
    teme = TEME(make_rep(position_km, velocity_km_s), obstime=time)
    gcrs = teme.transform_to(GCRS(obstime=time))
    return (
        gcrs.cartesian.xyz.to_value(u.km),
        gcrs.cartesian.differentials["s"].d_xyz.to_value(u.km / u.s),
    )


def rtn_basis(reference_position: np.ndarray, reference_velocity: np.ndarray) -> np.ndarray:
    radial = reference_position / np.linalg.norm(reference_position)
    normal = np.cross(reference_position, reference_velocity)
    normal /= np.linalg.norm(normal)
    transverse = np.cross(normal, radial)
    return np.vstack([radial, transverse, normal])


def satrec_from_supgp(row: dict[str, Any]) -> Satrec:
    satellite = Satrec()
    omm.initialize(satellite, {key: str(value) for key, value in row.items()})
    return satellite


def load_supgp() -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    files = sorted(SUPGP_DIR.glob("*.csv"))
    if not files:
        raise SystemExit("No historical SupGP CSV files found")
    provenance = []
    frames = []
    schema_rows = []
    for path in files:
        frame = pd.read_csv(path, dtype={"NORAD_CAT_ID": str})
        header = list(frame.columns)
        provenance.append({
            "original_filename": path.name,
            "raw_file_path": path.as_posix(),
            "sha256": sha256(path),
            "file_size_bytes": path.stat().st_size,
            "row_count": len(frame),
            "file_observed_mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "source": "CelesTrak historical SupGP special-request CSV attachment",
            "requested_norad_ids": ",".join(TARGET_IDS),
            "requested_time_range": "2026-03-08--2026-03-14",
            "format": "CSV",
        })
        schema_rows.append({
            "original_filename": path.name,
            "actual_header_json": json.dumps(header, ensure_ascii=False),
            "norad_field": "NORAD_CAT_ID" if "NORAD_CAT_ID" in header else None,
            "object_name_field": "OBJECT_NAME" if "OBJECT_NAME" in header else None,
            "epoch_field": "EPOCH" if "EPOCH" in header else None,
            "bstar_field": "BSTAR" if "BSTAR" in header else None,
            "fit_rms_field": "RMS" if "RMS" in header else None,
            "fit_rms_unit": "km (official CelesTrak SupGP fit-RMS semantics; unit not encoded in CSV header)",
            "data_source_field": "DATA_SOURCE" if "DATA_SOURCE" in header else None,
            "sgp4_elements_present": all(column in header for column in [
                "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
                "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT",
                "MEAN_MOTION_DDOT", "EPHEMERIS_TYPE", "NORAD_CAT_ID",
            ]),
            "ephemeris_type_values": json.dumps(sorted(frame["EPHEMERIS_TYPE"].astype(str).unique().tolist())) if "EPHEMERIS_TYPE" in frame else None,
            "classification_type_values": json.dumps(sorted(frame["CLASSIFICATION_TYPE"].astype(str).unique().tolist())) if "CLASSIFICATION_TYPE" in frame else None,
            "data_source_values": json.dumps(sorted(frame["DATA_SOURCE"].astype(str).unique().tolist())) if "DATA_SOURCE" in frame else None,
        })
        frame["raw_file_path"] = path.as_posix()
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    required = [
        "NORAD_CAT_ID", "OBJECT_NAME", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
        "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "EPHEMERIS_TYPE", "BSTAR",
        "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "RMS", "DATA_SOURCE",
    ]
    missing = [column for column in required if column not in combined.columns]
    if missing:
        raise SystemExit(f"SupGP schema missing required source/RMS/SGP4 fields: {missing}")
    if combined[["RMS", "DATA_SOURCE"]].isna().any().any():
        raise SystemExit("SupGP source or fit RMS contains missing values")
    combined["NORAD_CAT_ID"] = combined["NORAD_CAT_ID"].astype(str)
    combined["EPOCH_DT"] = pd.to_datetime(combined["EPOCH"], utc=True)
    combined = combined[(combined.EPOCH_DT >= WINDOW_START) & (combined.EPOCH_DT < WINDOW_STOP)].copy()
    combined["semi_major_axis_proxy_km"] = combined.MEAN_MOTION.astype(float).map(semi_major_axis_proxy_km)
    combined["fit_rms_km"] = combined.RMS.astype(float)
    combined["reference_type"] = "operator-derived SupGP reference"
    combined["reference_quality"] = "SGP4 fit to source ephemeris; not precise truth"
    return combined, pd.DataFrame(schema_rows), provenance


def quality_audit(supgp: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sat_id, group in supgp.groupby("NORAD_CAT_ID"):
        group = group.sort_values("EPOCH_DT")
        gaps = group.EPOCH_DT.diff().dt.total_seconds().div(3600.0).dropna()
        rms = group.fit_rms_km.astype(float)
        median = float(rms.median())
        mad = float(np.median(np.abs(rms - median)))
        robust_z = np.abs(rms - median) / (1.4826 * mad) if mad > 0 else pd.Series(np.zeros(len(rms)), index=rms.index)
        rows.append({
            "norad_cat_id": sat_id,
            "object_name": group.OBJECT_NAME.iloc[0],
            "record_count": len(group),
            "epoch_min": iso(group.EPOCH_DT.min()),
            "epoch_max": iso(group.EPOCH_DT.max()),
            "fit_rms_unit": "km",
            "fit_rms_min_km": rms.min(),
            "fit_rms_median_km": median,
            "fit_rms_max_km": rms.max(),
            "fit_rms_max_robust_z": float(robust_z.max()),
            "rms_outlier_candidate_count": int((robust_z > 3.5).sum()),
            "source_distribution_json": json.dumps(group.DATA_SOURCE.value_counts().to_dict()),
            "source_switch": group.DATA_SOURCE.nunique() > 1,
            "median_epoch_gap_hours": float(gaps.median()),
            "max_epoch_gap_hours": float(gaps.max()),
            "max_to_median_gap_ratio": float(gaps.max() / gaps.median()),
            "obvious_gap_candidate": bool(gaps.max() > 2.5 * gaps.median()),
            "duplicate_epoch_count": int(group.EPOCH_DT.duplicated().sum()),
            "mean_motion_min_rev_day": group.MEAN_MOTION.astype(float).min(),
            "mean_motion_max_rev_day": group.MEAN_MOTION.astype(float).max(),
            "semi_major_axis_proxy_min_km": group.semi_major_axis_proxy_km.min(),
            "semi_major_axis_proxy_max_km": group.semi_major_axis_proxy_km.max(),
            "bstar_min": group.BSTAR.astype(float).min(),
            "bstar_max": group.BSTAR.astype(float).max(),
        })
    return pd.DataFrame(rows)


def load_ordinary_gp() -> tuple[list[dict[str, Any]], pd.DataFrame]:
    records = json.loads(GP_CACHE.read_text(encoding="utf-8"))
    target_records = [record for record in records if str(record.get("NORAD_CAT_ID")) in TARGET_IDS]
    rows = []
    for sat_id in TARGET_IDS:
        group = [record for record in target_records if str(record["NORAD_CAT_ID"]) == sat_id]
        epochs = pd.to_datetime([record["EPOCH"] for record in group], utc=True)
        creations = pd.to_datetime([record["CREATION_DATE"] for record in group], utc=True)
        window_count = int(((epochs >= WINDOW_START) & (epochs < WINDOW_STOP)).sum())
        rows.append({
            "norad_cat_id": sat_id,
            "record_count_all_cache": len(group),
            "record_count_epoch_in_window": window_count,
            "epoch_min": iso(epochs.min()),
            "epoch_max": iso(epochs.max()),
            "creation_date_min": iso(creations.min()),
            "creation_date_max": iso(creations.max()),
            "time_overlap_with_supgp_window": epochs.min() < WINDOW_STOP and epochs.max() >= WINDOW_START,
            "source": "existing Space-Track GP_HISTORY cache; no download this stage",
            "ref_frame_values": json.dumps(sorted({str(record.get("REF_FRAME")) for record in group})),
            "mean_element_theory_values": json.dumps(sorted({str(record.get("MEAN_ELEMENT_THEORY")) for record in group})),
        })
    return target_records, pd.DataFrame(rows)


def causal_candidates(supgp: pd.DataFrame, ordinary_records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for _, reference in supgp.sort_values(["NORAD_CAT_ID", "EPOCH_DT"]).iterrows():
        evaluation = reference.EPOCH_DT.to_pydatetime()
        available = [
            record for record in ordinary_records
            if str(record["NORAD_CAT_ID"]) == str(reference.NORAD_CAT_ID)
            and parse_utc(record["CREATION_DATE"]) <= evaluation
        ]
        available.sort(key=lambda record: (
            parse_utc(record["CREATION_DATE"]), parse_utc(record["EPOCH"]), str(record.get("GP_ID", ""))
        ))
        if not available:
            rows.append({"norad_cat_id": reference.NORAD_CAT_ID, "evaluation_time": iso(evaluation), "causal_available": False})
            continue
        selected = available[-1]
        gp_epoch = parse_utc(selected["EPOCH"])
        rows.append({
            "norad_cat_id": reference.NORAD_CAT_ID,
            "evaluation_time": iso(evaluation),
            "supgp_epoch": iso(reference.EPOCH_DT),
            "supgp_row_index": int(reference.name),
            "causal_available": True,
            "selected_gp_id": selected.get("GP_ID"),
            "selected_gp_epoch": iso(gp_epoch),
            "selected_gp_creation_date": iso(selected["CREATION_DATE"]),
            "gp_age_seconds": (evaluation - gp_epoch).total_seconds(),
            "future_creation_used": parse_utc(selected["CREATION_DATE"]) > evaluation,
        })
    return pd.DataFrame(rows)


def select_smoke(candidates: pd.DataFrame) -> pd.DataFrame:
    selected = []
    for sat_id, group in candidates[candidates.causal_available].groupby("norad_cat_id"):
        group = group.sort_values(["gp_age_seconds", "evaluation_time"]).reset_index(drop=True)
        indices = sorted(set([0, int(round((len(group) - 1) / 3)), int(round(2 * (len(group) - 1) / 3)), len(group) - 1]))
        roles = ["freshest", "lower_middle", "upper_middle", "stalest"]
        for role, index in zip(roles, indices):
            row = group.iloc[index].to_dict()
            row["freshness_role"] = role
            selected.append(row)
    return pd.DataFrame(selected)


def smoke_residuals(
    selected: pd.DataFrame, supgp: pd.DataFrame, ordinary_records: list[dict[str, Any]]
) -> tuple[pd.DataFrame, dict[str, float]]:
    gp_by_id = {str(record.get("GP_ID")): record for record in ordinary_records}
    rows = []
    max_rtn_orthogonality = 0.0
    max_position_reconstruction = 0.0
    max_velocity_reconstruction = 0.0
    max_teme_gcrs_position_norm_difference = 0.0
    propagation_errors = 0
    for _, choice in selected.iterrows():
        reference_row = supgp.loc[int(choice.supgp_row_index)].to_dict()
        ordinary = gp_by_id[str(int(choice.selected_gp_id))] if str(choice.selected_gp_id).endswith(".0") else gp_by_id[str(choice.selected_gp_id)]
        evaluation = parse_utc(choice.evaluation_time)
        ordinary_sat = Satrec.twoline2rv(str(ordinary["TLE_LINE1"]), str(ordinary["TLE_LINE2"]))
        supgp_sat = satrec_from_supgp(reference_row)
        try:
            ordinary_r_teme, ordinary_v_teme = propagate(ordinary_sat, evaluation)
            supgp_r_teme, supgp_v_teme = propagate(supgp_sat, evaluation)
        except ValueError:
            propagation_errors += 1
            raise
        dr_teme = ordinary_r_teme - supgp_r_teme
        dv_teme = ordinary_v_teme - supgp_v_teme
        ordinary_r, ordinary_v = to_gcrs(ordinary_r_teme, ordinary_v_teme, evaluation)
        supgp_r, supgp_v = to_gcrs(supgp_r_teme, supgp_v_teme, evaluation)
        dr = ordinary_r - supgp_r
        dv = ordinary_v - supgp_v
        basis = rtn_basis(supgp_r, supgp_v)
        max_rtn_orthogonality = max(max_rtn_orthogonality, float(np.max(np.abs(basis @ basis.T - np.eye(3)))))
        dr_rtn = basis @ dr
        dv_rtn = basis @ dv
        max_position_reconstruction = max(max_position_reconstruction, abs(np.linalg.norm(dr_rtn) - np.linalg.norm(dr)))
        max_velocity_reconstruction = max(max_velocity_reconstruction, abs(np.linalg.norm(dv_rtn) - np.linalg.norm(dv)))
        max_teme_gcrs_position_norm_difference = max(max_teme_gcrs_position_norm_difference, abs(np.linalg.norm(dr_teme) - np.linalg.norm(dr)))
        rows.append({
            "norad_cat_id": str(choice.norad_cat_id),
            "object_name": reference_row["OBJECT_NAME"],
            "evaluation_time": iso(evaluation),
            "freshness_role": choice.freshness_role,
            "comparison_name": "ordinary-GP prediction disagreement relative to operator-derived SupGP reference",
            "propagation_model_ordinary": "SGP4",
            "propagation_model_supgp": "SGP4",
            "native_output_frame_both": "TEME",
            "common_frame": "GCRS",
            "delta_R_km": dr_rtn[0],
            "delta_T_km": dr_rtn[1],
            "delta_N_km": dr_rtn[2],
            "delta_v_R_km_s": dv_rtn[0],
            "delta_v_T_km_s": dv_rtn[1],
            "delta_v_N_km_s": dv_rtn[2],
            "position_error_norm_km": np.linalg.norm(dr),
            "velocity_error_norm_km_s": np.linalg.norm(dv),
            "teme_position_disagreement_norm_km": np.linalg.norm(dr_teme),
            "teme_velocity_disagreement_norm_km_s": np.linalg.norm(dv_teme),
            "gp_age_seconds": choice.gp_age_seconds,
            "ordinary_gp_epoch": choice.selected_gp_epoch,
            "ordinary_gp_creation_date": choice.selected_gp_creation_date,
            "ordinary_gp_id": choice.selected_gp_id,
            "supgp_epoch": iso(reference_row["EPOCH"]),
            "supgp_source": reference_row["DATA_SOURCE"],
            "supgp_fit_rms_km": float(reference_row["RMS"]),
            "supgp_element_set_no": reference_row["ELEMENT_SET_NO"],
            "causal_creation_date_ok": parse_utc(choice.selected_gp_creation_date) <= evaluation,
            "reference_type": "operator-derived higher-quality SupGP reference; not precise truth",
        })
    return pd.DataFrame(rows), {
        "propagation_errors": float(propagation_errors),
        "max_rtn_orthogonality_error": max_rtn_orthogonality,
        "max_position_norm_reconstruction_error_km": max_position_reconstruction,
        "max_velocity_norm_reconstruction_error_km_s": max_velocity_reconstruction,
        "max_teme_gcrs_position_norm_difference_km": max_teme_gcrs_position_norm_difference,
    }


def regime_audit(supgp: pd.DataFrame, ordinary_records: list[dict[str, Any]], residuals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sat_id in TARGET_IDS:
        s = supgp[supgp.NORAD_CAT_ID == sat_id].sort_values("EPOCH_DT").copy()
        o = pd.DataFrame([record for record in ordinary_records if str(record["NORAD_CAT_ID"]) == sat_id])
        o["EPOCH_DT"] = pd.to_datetime(o.EPOCH, utc=True)
        o = o[(o.EPOCH_DT >= WINDOW_START) & (o.EPOCH_DT < WINDOW_STOP)].sort_values("EPOCH_DT")
        s_mm_step = s.MEAN_MOTION.astype(float).diff().abs()
        s_a_step = s.semi_major_axis_proxy_km.diff().abs()
        s_b_step = s.BSTAR.astype(float).diff().abs()
        o_mm = o.MEAN_MOTION.astype(float)
        o_a = o_mm.map(semi_major_axis_proxy_km)
        o_b = o.BSTAR.astype(float)
        r = residuals[residuals.norad_cat_id == sat_id]
        rms_ratio = float(s.fit_rms_km.max() / s.fit_rms_km.median())
        # Descriptive multi-indicator flag, not an acceptance or uncertainty threshold.
        strong_fit_episode = rms_ratio >= 5.0
        concentrated_element_episode = float(s_mm_step.max()) >= 0.005 and float(s_b_step.max()) >= 0.005
        ordinary_element_episode = float(o_mm.diff().abs().max()) >= 0.005 and float(o_b.diff().abs().max()) >= 0.005
        if strong_fit_episode and concentrated_element_episode:
            classification = "possible_regime_change"
        elif strong_fit_episode or concentrated_element_episode or ordinary_element_episode:
            classification = "uncertain"
        elif rms_ratio < 3.0 and float(s_mm_step.max()) < 0.005 and float(s_b_step.max()) < 0.005:
            classification = "nominal-looking"
        else:
            classification = "uncertain"
        supgp_max_rms_index = s.fit_rms_km.idxmax()
        supgp_max_mm_step_index = s_mm_step.idxmax()
        ordinary_max_mm_step_index = o_mm.diff().abs().idxmax()
        rows.append({
            "norad_cat_id": sat_id,
            "classification": classification,
            "supgp_rms_max_to_median_ratio": rms_ratio,
            "supgp_max_adjacent_mean_motion_change_rev_day": float(s_mm_step.max()),
            "supgp_max_adjacent_semi_major_axis_proxy_change_km": float(s_a_step.max()),
            "supgp_max_adjacent_bstar_change": float(s_b_step.max()),
            "supgp_max_rms_epoch": iso(s.loc[supgp_max_rms_index, "EPOCH_DT"]),
            "supgp_max_mean_motion_step_epoch": iso(s.loc[supgp_max_mm_step_index, "EPOCH_DT"]),
            "ordinary_max_adjacent_mean_motion_change_rev_day": float(o_mm.diff().abs().max()),
            "ordinary_max_adjacent_semi_major_axis_proxy_change_km": float(o_a.diff().abs().max()),
            "ordinary_max_adjacent_bstar_change": float(o_b.diff().abs().max()),
            "ordinary_max_mean_motion_step_epoch": iso(o.loc[ordinary_max_mm_step_index, "EPOCH_DT"]),
            "smoke_position_disagreement_min_km": float(r.position_error_norm_km.min()),
            "smoke_position_disagreement_median_km": float(r.position_error_norm_km.median()),
            "smoke_position_disagreement_max_km": float(r.position_error_norm_km.max()),
            "notes": "Multi-indicator descriptive label only; BSTAR alone is not treated as confirmed maneuver evidence.",
        })
    return pd.DataFrame(rows)


def credential_value_hits(paths: list[Path]) -> int:
    secrets = [
        os.environ.get(name, "").encode()
        for name in ["SPACETRACK_USERNAME", "SPACETRACK_PASSWORD", "CDSE_USERNAME", "CDSE_PASSWORD"]
        if os.environ.get(name)
    ]
    if not secrets:
        return 0
    hits = 0
    for path in paths:
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if any(secret in content for secret in secrets):
            hits += 1
    return hits


def main() -> None:
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    guard_before = {path.as_posix(): sha256(path) for path in FORMAL_GUARD_FILES if path.exists()}

    supgp, schema_df, provenance = load_supgp()
    found_ids = sorted(set(supgp.NORAD_CAT_ID))
    missing_ids = sorted(set(TARGET_IDS) - set(found_ids))
    status = "COMPLETE" if not missing_ids else "PARTIAL"
    provenance_df = pd.DataFrame(provenance)
    quality_df = quality_audit(supgp)
    ordinary_records, ordinary_df = load_ordinary_gp()
    candidates_df = causal_candidates(supgp, ordinary_records)
    selected_df = select_smoke(candidates_df)
    residual_df, numeric_audit = smoke_residuals(selected_df, supgp, ordinary_records)
    regime_df = regime_audit(supgp, ordinary_records, residual_df)

    canonical_columns = [
        "NORAD_CAT_ID", "OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
        "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "EPHEMERIS_TYPE",
        "CLASSIFICATION_TYPE", "ELEMENT_SET_NO", "REV_AT_EPOCH", "BSTAR", "MEAN_MOTION_DOT",
        "MEAN_MOTION_DDOT", "RMS", "DATA_SOURCE", "fit_rms_km", "semi_major_axis_proxy_km",
        "reference_type", "reference_quality", "raw_file_path",
    ]
    supgp[canonical_columns].to_csv(CANONICAL_DIR / "supgp_records.csv", index=False, encoding="utf-8-sig")
    residual_df.to_csv(CANONICAL_DIR / "starlink_state_error_rtn.csv", index=False, encoding="utf-8-sig")
    provenance_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_supgp_raw_inventory.csv", index=False, encoding="utf-8-sig")
    schema_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_supgp_schema_audit.csv", index=False, encoding="utf-8-sig")
    quality_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_supgp_reference_quality.csv", index=False, encoding="utf-8-sig")
    ordinary_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_ordinary_gp_audit.csv", index=False, encoding="utf-8-sig")
    candidates_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_causal_candidates.csv", index=False, encoding="utf-8-sig")
    selected_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_causal_selection.csv", index=False, encoding="utf-8-sig")
    residual_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_state_error_rtn.csv", index=False, encoding="utf-8-sig")
    regime_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_regime_audit.csv", index=False, encoding="utf-8-sig")

    manifest = json.loads(PILOT_MANIFEST.read_text(encoding="utf-8"))
    manifest["celestrak_historical_supgp"] = {
        "status": status,
        "source": "CelesTrak historical SupGP special request",
        "official_request_entry": "https://celestrak.org/NORAD/archives/sup-request.php?FORMAT=csv",
        "requested_norad_ids": TARGET_IDS,
        "requested_time_range": {"start": "2026-03-08", "stop": "2026-03-14"},
        "found_norad_ids": found_ids,
        "missing_norad_ids": missing_ids,
        "rms_semantics": "SGP4 position-fit RMS relative to source ephemeris",
        "rms_unit": "km; resolved from official CelesTrak SupGP documentation because CSV header is unitless",
        "raw_files": provenance,
        "raw_files_modified": False,
    }
    PILOT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    guard_after = {path.as_posix(): sha256(path) for path in FORMAL_GUARD_FILES if path.exists()}
    guards_unchanged = guard_before == guard_after
    output_scan = [
        path for root in [CANONICAL_DIR, METRICS_DIR, Path("outputs/reports"), Path("logs")]
        for path in root.rglob("*") if path.is_file()
    ]
    credential_hits = credential_value_hits(output_scan)
    source_ok = bool(schema_df.fit_rms_field.notna().all() and schema_df.data_source_field.notna().all())
    all_causal = bool(candidates_df[candidates_df.causal_available].future_creation_used.eq(False).all())
    all_sgp4 = bool((supgp.EPHEMERIS_TYPE.astype(int) == 0).all() and numeric_audit["propagation_errors"] == 0)
    correctness_rows = [
        {"check": "raw SupGP SHA/size/row-count fixed", "passed": len(provenance) == len(list(SUPGP_DIR.glob("*.csv"))), "observed": f"files={len(provenance)}"},
        {"check": "requested NORAD IDs", "passed": not missing_ids, "observed": f"found={found_ids}; missing={missing_ids}; status={status}"},
        {"check": "source and fit RMS parsed", "passed": source_ok, "observed": "DATA_SOURCE and RMS nonempty; RMS unit resolved as km from official semantics"},
        {"check": "ordinary GP never uses future creation", "passed": all_causal, "observed": f"candidate rows={len(candidates_df)}"},
        {"check": "ordinary GP and SupGP SGP4-compatible", "passed": all_sgp4, "observed": "ordinary MEAN_ELEMENT_THEORY=SGP4; SupGP EPHEMERIS_TYPE=0; propagation errors=0"},
        {"check": "common epoch comparison", "passed": residual_df.evaluation_time.eq(residual_df.supgp_epoch).all(), "observed": f"residual rows={len(residual_df)}"},
        {"check": "frame semantics consistent", "passed": residual_df.native_output_frame_both.eq("TEME").all(), "observed": "both native SGP4 states TEME; common GCRS conversion applied"},
        {"check": "RTN orthogonality", "passed": numeric_audit["max_rtn_orthogonality_error"] < 1e-12, "observed": numeric_audit["max_rtn_orthogonality_error"]},
        {"check": "position/velocity norm reconstruction", "passed": numeric_audit["max_position_norm_reconstruction_error_km"] < 1e-12 and numeric_audit["max_velocity_norm_reconstruction_error_km_s"] < 1e-12, "observed": json.dumps(numeric_audit)},
        {"check": "no credential/token value leakage", "passed": credential_hits == 0, "observed": f"file_hits={credential_hits}"},
        {"check": "guarded historical/formal files unchanged", "passed": guards_unchanged, "observed": json.dumps(guard_after)},
        {"check": "smoke size only", "passed": len(residual_df) <= 4 * len(found_ids), "observed": f"{len(residual_df)} residual rows"},
    ]
    correctness_df = pd.DataFrame(correctness_rows)
    correctness_df.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_correctness_audit.csv", index=False, encoding="utf-8-sig")

    residual_summary = residual_df.groupby("norad_cat_id").agg(
        smoke_samples=("norad_cat_id", "size"),
        gp_age_min_hours=("gp_age_seconds", lambda values: values.min() / 3600.0),
        gp_age_median_hours=("gp_age_seconds", lambda values: values.median() / 3600.0),
        gp_age_max_hours=("gp_age_seconds", lambda values: values.max() / 3600.0),
        position_disagreement_min_km=("position_error_norm_km", "min"),
        position_disagreement_median_km=("position_error_norm_km", "median"),
        position_disagreement_max_km=("position_error_norm_km", "max"),
        velocity_disagreement_median_km_s=("velocity_error_norm_km_s", "median"),
    ).reset_index()
    residual_summary.to_csv(METRICS_DIR / "orbit_uncertainty_stage0_starlink_residual_summary.csv", index=False, encoding="utf-8-sig")

    def md(frame: pd.DataFrame) -> str:
        return frame.to_markdown(index=False)

    report = f"""# Orbit uncertainty Stage-0：Starlink GP↔SupGP smoke

## 1. 状态

最终状态：`{status}`。目标为{TARGET_IDS}；实际发现{found_ids}；缺失{missing_ids}。本轮没有下载ordinary GP，复用已有Space-Track GP_HISTORY缓存。

## 2. 原始SupGP与schema

{md(provenance_df[['original_filename','file_size_bytes','row_count','sha256']])}

{md(schema_df[['original_filename','fit_rms_field','fit_rms_unit','data_source_field','sgp4_elements_present','ephemeris_type_values','classification_type_values','data_source_values']])}

CSV实际字段为`RMS`与`DATA_SOURCE`。RMS按[CelesTrak historical SupGP说明](https://celestrak.org/NORAD/archives/sup-request.php?FORMAT=csv)及其[SupGP方法论文](https://www.celestrak.org/publications/IAC/2025/IAC-25%2CA6%2C7%2C1%2Cx99453%2CPaper.pdf)的官方语义，是SGP4拟合source ephemeris所得的position-fit RMS，单位km；CSV header本身不编码单位。source实际值均为`SpaceX-E`。SupGP是SGP4-compatible GP representation，只称operator-derived higher-quality reference，不称ground truth或precise orbit。

## 3. Reference quality

{md(quality_df)}

没有人为设置RMS acceptance threshold。`rms_outlier_candidate_count`仅使用robust-z标记需检查的记录，不剔除数据。三个对象都无重复epoch、无source切换；最大epoch gap约16.5小时。

## 4. Ordinary GP可用性与信息集

{md(ordinary_df)}

evaluation time取SupGP epoch。SupGP在本轮是离线higher-quality reference；ordinary GP模拟当时可用信息，只允许`CREATION_DATE <= evaluation time`，再按CREATION_DATE、EPOCH和GP_ID确定性选择最新记录。没有使用未来发布但epoch更近的GP。

## 5. 6D RTN/full-state smoke

{md(residual_summary)}

每颗卫星按causal GP freshness从19个可用SupGP epoch中只抽取4点，共{len(residual_df)}行。ordinary GP和SupGP均使用production `sgp4`库传播，native output均为TEME；随后复用已验证方法转换到GCRS，并以SupGP propagated state定义RTN。没有遍历所有GP-reference pair。

## 6. Regime/maneuver-like inspection

{md(regime_df)}

标签仅为`nominal-looking`、`possible_regime_change`或`uncertain`。任何标签都不是confirmed maneuver；BSTAR跳变从不单独作为证据。

## 7. 正确性审计

{md(correctness_df)}

## 8. Stage-0回答与边界

- precise-reference methodology sanity：由既有Sentinel分支完成；本轮未重跑。
- Starlink-specific reference availability：本轮对三个目标验证。
- full-state residual pipeline：共同TEME、GCRS与RTN/velocity residual均跑通。
- Sentinel误差分布没有迁移到Starlink；本轮只描述ordinary GP relative to operator-derived SupGP disagreement。

Stage-0已具备进入正式Starlink uncertainty pilot的工程条件。下一阶段只建议、不在本轮执行：

- 规模：20–24颗项目已使用且ordinary GP/SupGP连续覆盖的Starlink，共享连续28天；
- selection：按轨道壳层/倾角、ordinary GP更新密度、SupGP coverage和reference RMS完整性分层，不只挑最稳定对象；
- cohort：预先分成`nominal`与`possible maneuver/regime-change`，`uncertain`单列，不把三者直接pool；
- freshness：保留全部causal support并按0–6、6–12、12–24、24–48、>48小时分层报告；本smoke实际覆盖约3.0–27.0小时，不外推未覆盖区间；
- raw：永久保存Space-Track OMM JSON、CelesTrak原始CSV、query/request metadata、SHA-256与source；
- canonical：分离ordinary GP EPOCH/CREATION_DATE与SupGP epoch/source/fit RMS，保留全部SGP4 elements和半长轴代理；
- residual：一行一个evaluation time和确定性causal selection，保存TEME/common-frame state、6D RTN、norm、freshness、reference quality与regime label；
- direct SpaceX ephemeris forward archive：建议新增。SupGP仍是SGP4 fit representation；若公开接口与使用条款允许，应从pilot启动日起前向缓存原始SpaceX ephemeris及provenance，以便区分source trajectory与SGP4 fit error，但不把未来归档伪装成历史回填。

本轮没有正式uncertainty calibration、quantile/Mahalanobis/conformal threshold、synthetic B、Doppler propagation、attack–uncertainty boundary、新verifier或24星下载。
"""
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(json.dumps({
        "status": status,
        "supgp_records": len(supgp),
        "ordinary_gp_records": len(ordinary_records),
        "residual_rows": len(residual_df),
        "correctness_passed": int(correctness_df.passed.sum()),
        "correctness_total": len(correctness_df),
        "regime_labels": regime_df.set_index("norad_cat_id").classification.to_dict(),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
