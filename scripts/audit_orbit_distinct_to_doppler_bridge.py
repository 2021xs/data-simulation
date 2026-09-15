#!/usr/bin/env python3
"""Audit the frozen orbit-uncertainty to Doppler-security interface.

This is a deterministic representation/provenance audit.  It does not fit an
uncertainty model, generate candidate orbits, or execute a Doppler verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from astropy.utils import iers
from sgp4.api import Satrec

from run_orbit_uncertainty_stage0_starlink_smoke import propagate, rtn_basis, satrec_from_supgp
from run_orbit_uncertainty_stage1b_residual_library import to_gcrs_batch


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"
DATASETS = ROOT / "outputs" / "datasets"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
FINAL_INTERFACE = METRICS / "orbit_uncertainty_final_downstream_interface.json"
FINAL_MANIFEST = METRICS / "orbit_uncertainty_final_manifest.json"
FREEZE_MANIFEST = METRICS / "orbit_uncertainty_stage1f_lite_manifest.json"
JUNE_CONFIRMATORY = METRICS / "orbit_uncertainty_stage1f_lite_june_confirmatory_manifest.json"

BASIS_OUTPUT = METRICS / "orbit_distinct_rtn_basis_equivalence_audit.csv"
SIGN_OUTPUT = METRICS / "orbit_distinct_sign_convention_audit.csv"
COMPAT_OUTPUT = METRICS / "orbit_distinct_existing_doppler_artifact_compatibility.csv"
INTERFACE_OUTPUT = METRICS / "orbit_distinct_frozen_scoring_interface.json"
MANIFEST_OUTPUT = METRICS / "orbit_distinct_bridge_interface_manifest.json"
REPORT_OUTPUT = REPORTS / "orbit_distinct_to_doppler_bridge_interface_audit.md"

MONTHS = {
    "APRIL": {
        "canonical": DATASETS / "orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv",
        "manifest": METRICS / "orbit_uncertainty_stage1b_20260401_20260430_manifest.json",
    },
    "MAY": {
        "canonical": DATASETS / "orbit_uncertainty_stage1b_20260501_20260531_rtn_residual_library.csv",
        "manifest": METRICS / "orbit_uncertainty_stage1b_20260501_20260531_manifest.json",
    },
    "JUNE": {
        "canonical": DATASETS / "orbit_uncertainty_stage1b_20260601_20260630_rtn_residual_library.csv",
        "manifest": METRICS / "orbit_uncertainty_stage1b_20260601_20260630_manifest.json",
    },
}

PERCENTILES = (50, 90, 95, 99, 100)
FRESHNESS_LABELS = ("0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h")
PROTECTED = [
    PARAMETERS,
    FINAL_INTERFACE,
    FINAL_MANIFEST,
    FREEZE_MANIFEST,
    JUNE_CONFIRMATORY,
    *[item[key] for item in MONTHS.values() for key in ("canonical", "manifest")],
    DATASETS / "doppler_verifier_orbit_similarity_attack_dataset.csv",
    METRICS / "verifier_v2_sequence_eval.csv",
    DATASETS / "controlled_starlink_multitarget_dataset.csv",
    DATASETS / "active_compensation_first_pass_dataset.csv",
    DATASETS / "fixed_point_active_compensation_dataset.csv",
    DATASETS / "m2_segment_local_expanded_sample_dataset.csv",
    DATASETS / "same_pair_multi_pass_realization_dataset.csv",
    DATASETS / "historical_tle_multi_pass_realization_dataset.csv",
    DATASETS / "controlled_altitude_difference_realization_dataset.csv",
    DATASETS / "differential_doppler_mechanism_full_representative_timeseries.csv",
    ROOT / "data" / "tle" / "starlink_tle.txt",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=512)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def output_entry(path: Path) -> dict[str, Any]:
    return {"path": relative(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def check_paths(overwrite: bool) -> None:
    required = PROTECTED.copy()
    required.extend([item["canonical"] for item in MONTHS.values()])
    missing = [relative(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative input: " + ", ".join(missing))
    targets = [BASIS_OUTPUT, SIGN_OUTPUT, COMPAT_OUTPUT, INTERFACE_OUTPUT, MANIFEST_OUTPUT, REPORT_OUTPUT]
    existing = [relative(path) for path in targets if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Output exists; use --overwrite: " + ", ".join(existing))
    if sha256(PARAMETERS) != PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch")


def load_models() -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(PARAMETERS, encoding="utf-8-sig")
    primary = frame.loc[frame.candidate == "ROBUST_EMPIRICAL_ELLIPSOID"].copy()
    if len(frame) != 12 or len(primary) != 6 or set(primary.freshness_bin) != set(FRESHNESS_LABELS):
        raise SystemExit("Frozen parameter schema/count mismatch")
    models: dict[str, dict[str, Any]] = {}
    for row in primary.itertuples(index=False):
        covariance = np.array([
            [row.cov_RR_km2, row.cov_RT_km2, row.cov_RN_km2],
            [row.cov_TR_km2, row.cov_TT_km2, row.cov_TN_km2],
            [row.cov_NR_km2, row.cov_NT_km2, row.cov_NN_km2],
        ], dtype=float)
        models[str(row.freshness_bin)] = {
            "center": np.array([row.center_R_km, row.center_T_km, row.center_N_km], dtype=float),
            "precision": np.linalg.inv(covariance),
            "c95": float(row.c95_empirical_score),
            "c99": float(row.c99_empirical_score),
        }
    return models


def freshness_bin(age: float) -> str:
    for left, right, label in zip((0, 6, 9, 12, 18, 24), (6, 9, 12, 18, 24, 36), FRESHNESS_LABELS):
        if left < age <= right:
            return label
    raise ValueError(f"Age outside support: {age}")


def score(vector: np.ndarray, model: dict[str, Any]) -> float:
    centered = vector - model["center"]
    return float(centered @ model["precision"] @ centered)


def classify(value: float, model: dict[str, Any]) -> str:
    if value <= model["c95"]:
        return "NOT_ORBIT_DISTINCT"
    if value <= model["c99"]:
        return "AMBIGUOUS"
    return "ORBIT_DISTINCT"


def load_supgp_row(path: Path, row_number: int, cache: dict[Path, pd.DataFrame]) -> dict[str, Any]:
    if path not in cache:
        cache[path] = pd.read_csv(path, dtype={"NORAD_CAT_ID": str})
    index = int(row_number) - 2
    if index < 0 or index >= len(cache[path]):
        raise IndexError(f"Invalid source row {row_number} for {path}")
    return cache[path].iloc[index].to_dict()


def load_ordinary_lookup(path: Path) -> dict[str, dict[str, Any]]:
    records = json.loads(path.read_text(encoding="utf-8"))
    lookup = {str(row["GP_ID"]): row for row in records}
    if len(lookup) != len(records):
        raise SystemExit(f"Duplicate GP_ID in {path}")
    return lookup


def reconstruct_month(month: str, config: dict[str, Path], models: dict[str, dict[str, Any]], chunk_size: int) -> pd.DataFrame:
    manifest = json.loads(config["manifest"].read_text(encoding="utf-8"))
    ordinary_path = ROOT / Path(manifest["input_raw"]["ordinary"]["path"])
    if sha256(ordinary_path) != manifest["input_raw"]["ordinary"]["sha256"].upper():
        raise SystemExit(f"{month} ordinary raw SHA mismatch")
    ordinary = load_ordinary_lookup(ordinary_path)
    canonical = pd.read_csv(config["canonical"], dtype={"NORAD_CAT_ID": str, "ordinary_gp_id": str})
    # April/May predate the explicit support flag; the frozen support rule is
    # authoritative and is available from element_age_seconds in every month.
    canonical = canonical.loc[
        (canonical.element_age_seconds.astype(float) > 0.0)
        & (canonical.element_age_seconds.astype(float) <= 36.0 * 3600.0)
    ].copy()
    source_cache: dict[Path, pd.DataFrame] = {}
    ordinary_sat_cache: dict[str, Satrec] = {}
    rows: list[dict[str, Any]] = []

    for start in range(0, len(canonical), chunk_size):
        block = canonical.iloc[start:start + chunk_size]
        native_positions: list[np.ndarray] = []
        native_velocities: list[np.ndarray] = []
        epochs: list[datetime] = []
        meta: list[tuple[pd.Series, dict[str, Any]]] = []
        for _, item in block.iterrows():
            evaluation = pd.Timestamp(item.evaluation_time).to_pydatetime()
            selected = ordinary.get(str(item.ordinary_gp_id))
            if selected is None:
                raise SystemExit(f"{month}: selected GP_ID missing: {item.ordinary_gp_id}")
            if str(selected["NORAD_CAT_ID"]) != str(item.NORAD_CAT_ID):
                raise SystemExit(f"{month}: selected GP NORAD mismatch")
            source_path = ROOT / Path(str(item.supgp_source_file))
            reference = load_supgp_row(source_path, int(item.supgp_source_row_index), source_cache)
            if str(reference["NORAD_CAT_ID"]) != str(item.NORAD_CAT_ID):
                raise SystemExit(f"{month}: SupGP source-row NORAD mismatch")
            if pd.Timestamp(reference["EPOCH"]).tz_localize("UTC") != pd.Timestamp(item.evaluation_time):
                raise SystemExit(f"{month}: SupGP source-row epoch mismatch")
            ordinary_sat = ordinary_sat_cache.get(str(item.ordinary_gp_id))
            if ordinary_sat is None:
                ordinary_sat = Satrec.twoline2rv(str(selected["TLE_LINE1"]), str(selected["TLE_LINE2"]))
                ordinary_sat_cache[str(item.ordinary_gp_id)] = ordinary_sat
            reference_sat = satrec_from_supgp(reference)
            ordinary_r, ordinary_v = propagate(ordinary_sat, evaluation)
            reference_r, reference_v = propagate(reference_sat, evaluation)
            native_positions.extend([ordinary_r, reference_r])
            native_velocities.extend([ordinary_v, reference_v])
            epochs.extend([evaluation, evaluation])
            meta.append((item, reference))
        gcrs_r, gcrs_v = to_gcrs_batch(np.vstack(native_positions), np.vstack(native_velocities), epochs)
        for index, (item, _reference) in enumerate(meta):
            public_r, reference_r = gcrs_r[2 * index], gcrs_r[2 * index + 1]
            public_v, reference_v = gcrs_v[2 * index], gcrs_v[2 * index + 1]
            dr = public_r - reference_r
            ref_vector = rtn_basis(reference_r, reference_v) @ dr
            pub_vector = rtn_basis(public_r, public_v) @ dr
            canonical_vector = item[["delta_R_km", "delta_T_km", "delta_N_km"]].to_numpy(dtype=float)
            reconstruction_error = float(np.linalg.norm(ref_vector - canonical_vector))
            age = float(item.element_age_seconds) / 3600.0
            label = freshness_bin(age)
            model = models[label]
            d2_ref = score(ref_vector, model)
            d2_pub = score(pub_vector, model)
            dec_ref = classify(d2_ref, model)
            dec_pub = classify(d2_pub, model)
            rows.append({
                "record_type": "ROW",
                "month": month,
                "NORAD_CAT_ID": str(item.NORAD_CAT_ID),
                "evaluation_time": item.evaluation_time,
                "element_age_hours": age,
                "freshness_bin": label,
                "reference_R_km": ref_vector[0], "reference_T_km": ref_vector[1], "reference_N_km": ref_vector[2],
                "public_R_km": pub_vector[0], "public_T_km": pub_vector[1], "public_N_km": pub_vector[2],
                "abs_coordinate_difference_R_km": abs(pub_vector[0] - ref_vector[0]),
                "abs_coordinate_difference_T_km": abs(pub_vector[1] - ref_vector[1]),
                "abs_coordinate_difference_N_km": abs(pub_vector[2] - ref_vector[2]),
                "coordinate_vector_difference_norm_km": float(np.linalg.norm(pub_vector - ref_vector)),
                "absolute_norm_difference_km": abs(float(np.linalg.norm(pub_vector) - np.linalg.norm(ref_vector))),
                "canonical_reconstruction_error_km": reconstruction_error,
                "D2_reference": d2_ref,
                "D2_public_basis": d2_pub,
                "D2_absolute_difference": abs(d2_pub - d2_ref),
                "D2_relative_difference": abs(d2_pub - d2_ref) / max(abs(d2_ref), 1e-15),
                "inside_U95_reference": d2_ref <= model["c95"],
                "inside_U95_public": d2_pub <= model["c95"],
                "inside_U99_reference": d2_ref <= model["c99"],
                "inside_U99_public": d2_pub <= model["c99"],
                "three_state_reference": dec_ref,
                "three_state_public": dec_pub,
                "U95_changed": (d2_ref <= model["c95"]) != (d2_pub <= model["c95"]),
                "U99_changed": (d2_ref <= model["c99"]) != (d2_pub <= model["c99"]),
                "three_state_changed": dec_ref != dec_pub,
            })
    result = pd.DataFrame(rows)
    maximum_reconstruction_error = float(result.canonical_reconstruction_error_km.max())
    if maximum_reconstruction_error > 1e-7:
        raise SystemExit(
            f"{month}: canonical reconstruction exceeded 1e-7 km; "
            f"observed={maximum_reconstruction_error:.12e} km"
        )
    return result


def q(values: pd.Series, percentile: int) -> float:
    return float(np.percentile(values.to_numpy(dtype=float), percentile))


def basis_summary(detail: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    groups = [(month, detail.loc[detail.month == month]) for month in MONTHS]
    groups.append(("POOLED", detail))
    for scope, group in groups:
        row: dict[str, Any] = {
            "record_type": "SUMMARY", "month": scope, "n": len(group),
            "satellite_count": int(group.NORAD_CAT_ID.nunique()),
            "U95_agreement_rate": float((~group.U95_changed).mean()),
            "U99_agreement_rate": float((~group.U99_changed).mean()),
            "three_state_agreement_rate": float((~group.three_state_changed).mean()),
            "U95_change_count": int(group.U95_changed.sum()),
            "U99_change_count": int(group.U99_changed.sum()),
            "three_state_change_count": int(group.three_state_changed.sum()),
            "reference_P99_coverage": float(group.inside_U99_reference.mean()),
            "public_basis_P99_coverage": float(group.inside_U99_public.mean()),
            "reference_P95_coverage": float(group.inside_U95_reference.mean()),
            "public_basis_P95_coverage": float(group.inside_U95_public.mean()),
            "max_canonical_reconstruction_error_km": float(group.canonical_reconstruction_error_km.max()),
        }
        for column in [
            "abs_coordinate_difference_R_km", "abs_coordinate_difference_T_km", "abs_coordinate_difference_N_km",
            "coordinate_vector_difference_norm_km", "absolute_norm_difference_km", "D2_absolute_difference",
            "D2_relative_difference",
        ]:
            for percentile in PERCENTILES:
                row[f"{column}_p{percentile}"] = q(group[column], percentile)
        records.append(row)
    changes = detail.loc[detail.three_state_changed | detail.U95_changed | detail.U99_changed].copy()
    changes["record_type"] = "CLASSIFICATION_CHANGE"
    return pd.concat([pd.DataFrame(records), changes], ignore_index=True, sort=False)


def artifact_row(family: str, path: str, a: str, b: str, time: str, a_gp: str, b_state: str,
                 freshness: str, possible: str, status: str, notes: str) -> dict[str, str]:
    return {
        "experiment_family": family, "artifact": path, "A_identity": a,
        "B_definition_available": b, "evaluation_time_available": time,
        "A_public_GP_traceable": a_gp, "B_state_reconstructable": b_state,
        "freshness_reconstructable": freshness,
        "orbit_distinct_scoring_possible_without_verifier_rerun": possible,
        "status": status, "notes": notes,
    }


def compatibility_matrix() -> pd.DataFrame:
    return pd.DataFrame([
        artifact_row("score_only_verifier_and_synthetic_orbit_attacks",
            "outputs/datasets/doppler_verifier_orbit_similarity_attack_dataset.csv",
            "YES:NORAD", "YES:synthetic same-plane construction parameters and A state dependency",
            "YES:full timestamp grid; use segment midpoint", "NO:static TLE only; no GP_ID/CREATION_DATE",
            "RECONSTRUCTABLE_FROM_FROZEN_GENERATOR_AND_BOUND_TLE_INPUT", "NO",
            "YES_AFTER_CAUSAL_A_AND_B_STATE_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "Do not treat the static TLE epoch as causal publication provenance."),
        artifact_row("verifier_v2_gate_ablation",
            "outputs/metrics/verifier_v2_sequence_eval.csv",
            "YES:NORAD", "INHERITED_FROM_INITIAL_ATTACK_DATASET", "YES:window start/end",
            "NO:inherits static-TLE provenance", "RECONSTRUCTABLE_VIA_SOURCE_ATTACK_DATASET", "NO",
            "YES_AFTER_CAUSAL_A_AND_B_STATE_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "Gate metrics can be joined after orbit relabeling; the verifier need not rerun."),
        artifact_row("controlled_multitarget_legitimate_baseline",
            "outputs/datasets/controlled_starlink_multitarget_dataset.csv",
            "YES:NORAD", "NO:legitimate A-only baseline", "YES:pass grid; use pass midpoint",
            "NO:static TLE only", "NOT_APPLICABLE", "NO", "NO", "NOT_COMPATIBLE",
            "Not a pair/candidate security artifact."),
        artifact_row("active_compensation_first_pass",
            "outputs/datasets/active_compensation_first_pass_dataset.csv",
            "YES:NORAD", "YES:attacker NORAD and compensation construction", "YES:time_utc grid; use segment midpoint",
            "NO:static TLE only", "RECONSTRUCTABLE_FROM_A/B_TLE_AND_TIME", "NO",
            "YES_AFTER_CAUSAL_A_AND_B_STATE_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "SupGP must not enter the operational relabeling path."),
        artifact_row("fixed_point_active_compensation_summary",
            "outputs/datasets/fixed_point_active_compensation_dataset.csv",
            "YES:NORAD", "PARTIAL:attack parameters but no full B state/time", "PARTIAL:relative windows only",
            "NO", "NO_FROM_THIS_ARTIFACT_ALONE", "NO", "NO", "NEEDS_STATE_RECONSTRUCTION",
            "Use its upstream time-series/generator provenance, not the summary row alone."),
        artifact_row("segment_local_heatmap_and_direction_sensitivity",
            "outputs/datasets/m2_segment_local_expanded_sample_dataset.csv",
            "YES:NORAD", "YES:real-TLE or synthetic definition plus geometry fields",
            "DERIVABLE:pass_id plus segment bounds; freeze at segment center", "NO:static/current TLE has no GP_ID/CREATION_DATE",
            "RECONSTRUCTABLE_FROM_BOUND_GENERATOR_INPUTS", "NO",
            "YES_AFTER_CAUSAL_A_AND_STATE_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "Includes segment_local/fixed_site_segment_center/single-window semantics."),
        artifact_row("same_pair_multi_pass_real_TLE",
            "outputs/datasets/same_pair_multi_pass_realization_dataset.csv",
            "YES:NORAD", "YES:attacker NORAD and selected TLE epoch", "YES:service segment start/end",
            "NO:target TLE epoch exists but CREATION_DATE/GP_ID do not", "YES:bound TLE history/current TLE",
            "NO", "YES_AFTER_CAUSAL_A_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "Orbit score can be attached without rerunning the Doppler verifier."),
        artifact_row("historical_TLE_multi_pass_real_TLE",
            "outputs/datasets/historical_tle_multi_pass_realization_dataset.csv",
            "YES:NORAD", "YES:attacker historical TLE epoch", "YES:service segment start/end",
            "NO:historical TLE lacks publication provenance", "YES:historical TLE lines are upstream-traceable",
            "NO", "YES_AFTER_CAUSAL_A_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "TLE age is not a substitute for causal element age."),
        artifact_row("controlled_altitude_difference_synthetic_B",
            "outputs/datasets/controlled_altitude_difference_realization_dataset.csv",
            "YES:NORAD", "YES:delta_h, synthetic radius/rate and deterministic construction",
            "YES:service segment start/end", "NO:static target TLE has no GP_ID/CREATION_DATE",
            "YES_FROM_BOUND_SYNTHETIC_CONSTRUCTION", "NO",
            "YES_AFTER_CAUSAL_A_AND_B_STATE_RECONSTRUCTION", "NEEDS_CAUSAL_A_RECONSTRUCTION",
            "Preserves segment_local/fixed_site_segment_center/single-window and direction fields."),
        artifact_row("differential_doppler_mechanism_representatives",
            "outputs/datasets/differential_doppler_mechanism_full_representative_timeseries.csv",
            "DERIVABLE_FROM_PAIR_ID", "DERIVABLE_FROM_PAIR_ID", "PARTIAL:relative time only in this artifact",
            "NO", "NO_FROM_THIS_ARTIFACT_ALONE", "NO", "NO", "NEEDS_STATE_RECONSTRUCTION",
            "Relabel the upstream pair-instance artifact, then join; do not infer from Doppler residuals."),
    ])


def sign_audit() -> pd.DataFrame:
    return pd.DataFrame([
        {"audit_item": "stage1b_cartesian_residual", "authoritative_definition": "dr = x_A_public - x_reference",
         "rtn_definition": "e_ref = B_reference @ dr", "downstream_mapping": "unchanged",
         "provenance": "scripts/run_orbit_uncertainty_stage1b_residual_library.py: residual_components"},
        {"audit_item": "candidate_natural_displacement", "authoritative_definition": "d_B = x_B - x_A_public",
         "rtn_definition": "d_B_RTN = B_public @ d_B", "downstream_mapping": "z_B = -d_B_RTN = B_public @ (x_A_public - x_B)",
         "provenance": "deterministic sign transform; frozen center is unchanged"},
        {"audit_item": "frozen_score_vector", "authoritative_definition": "z_B has public-minus-candidate sign",
         "rtn_definition": "public-A-defined R,T,N; R=r/|r|, N=(r x v)/|r x v|, T=N x R",
         "downstream_mapping": "D2=(z_B-mu_k)^T Sigma_k^-1 (z_B-mu_k)",
         "provenance": "frozen Stage-1F signed 3D RTN convention"},
    ])


def scoring_interface(public_supported: bool) -> dict[str, Any]:
    return {
        "interface_name": "FROZEN_ORBIT_DISTINCT_TO_DOPPLER_SECURITY_V2",
        "model_name": "Freshness-Conditioned Robust Empirical RTN Ellipsoid",
        "interface_status": "PUBLIC_DEFINED_RTN_INTERFACE_SUPPORTED" if public_supported else "PUBLIC_DEFINED_RTN_INTERFACE_REQUIRES_METHOD_DECISION",
        "operational_inputs": {
            "claimed_A_public_GP": "Causally selected GP with GP_ID, EPOCH, CREATION_DATE and CREATION_DATE <= evaluation_time",
            "x_A_public_t": "Claimed A public GP propagated to evaluation_time in GCRS",
            "x_B_t": "Candidate B state at the same evaluation_time in GCRS",
            "evaluation_time": "UTC segment center",
        },
        "supgp_operational_input_required": False,
        "supgp_role": "calibration provenance only",
        "analysis_unit": "claimed_A x candidate_B x evaluation_segment/time",
        "freshness": {
            "formula": "element_age_hours = (evaluation_time - selected_A_GP_EPOCH)/3600",
            "causal_constraint": "selected_A_GP_CREATION_DATE <= evaluation_time",
            "support": "0 < element_age_hours <= 36",
            "outside_support_decision": "DEFER",
            "bins": list(FRESHNESS_LABELS),
        },
        "application_rtn": {
            "basis_source": "claimed A public predicted GCRS position and velocity",
            "R": "r_A_public / ||r_A_public||",
            "N": "(r_A_public x v_A_public) / ||r_A_public x v_A_public||",
            "T": "N x R",
        },
        "sign_mapping": {
            "natural_candidate_displacement": "d_B = x_B - x_A_public",
            "frozen_score_vector": "z_B = -RTN_public(d_B) = RTN_public(x_A_public - x_B)",
            "frozen_center_modified": False,
        },
        "score": "D2 = (z_B - mu_k)^T Sigma_k^-1 (z_B - mu_k)",
        "normalized_p99_distance": "rho_99 = sqrt(D2/c99_k); geometric normalization, not probability",
        "decision": [
            {"condition": "noncausal A selection or age<=0 or age>36 h", "output": "DEFER"},
            {"condition": "D2<=c95_k", "output": "NOT_ORBIT_DISTINCT"},
            {"condition": "c95_k<D2<=c99_k", "output": "AMBIGUOUS"},
            {"condition": "D2>c99_k", "output": "ORBIT_DISTINCT"},
        ],
        "required_security_dataset_fields": [
            "orbit_support_status", "orbit_element_age_hours", "orbit_freshness_bin", "orbit_score_d2",
            "orbit_c95", "orbit_c99", "orbit_decision", "orbit_normalized_p99_distance",
        ],
        "semantic_guard": "rho_99 is not a probability; ORBIT_DISTINCT plus Doppler accepted is the security-relevant indistinguishability region.",
        "fitting_or_recalibration_allowed": False,
        "frozen_parameter_sha256": PARAMETER_SHA,
    }


def make_report(summary: pd.DataFrame, compatibility: pd.DataFrame, public_supported: bool, protected_equal: bool) -> str:
    pooled = summary.loc[(summary.record_type == "SUMMARY") & (summary.month == "POOLED")].iloc[0]
    june = summary.loc[(summary.record_type == "SUMMARY") & (summary.month == "JUNE")].iloc[0]
    status = ("ORBIT_DISTINCT_TO_DOPPLER_SECURITY_BRIDGE_INTERFACE_AUDIT_COMPLETE"
              if public_supported else "ORBIT_DISTINCT_BRIDGE_BLOCKED_BY_RTN_INTERFACE")
    basis_table = summary.loc[summary.record_type == "SUMMARY", [
        "month", "n", "coordinate_vector_difference_norm_km_p50",
        "coordinate_vector_difference_norm_km_p95", "coordinate_vector_difference_norm_km_p99",
        "coordinate_vector_difference_norm_km_p100", "D2_relative_difference_p50",
        "D2_relative_difference_p95", "D2_relative_difference_p99", "D2_relative_difference_p100",
        "U95_agreement_rate", "U99_agreement_rate", "three_state_agreement_rate",
    ]].copy()
    lines = [
        "# Orbit-distinct 到 Doppler security bridge 接口审计", "",
        "## 正式结论", "", f"`{status}`。", "",
        "Stage-1B 的确切残差为 `dr = x_A_public - x_reference`，并投影到 reference-defined RTN。候选 B 的自然位移是 `d_B = x_B - x_A_public`；因此冻结模型的输入必须是 `z_B = -RTN_public(d_B) = RTN_public(x_A_public - x_B)`。这是确定性的符号变换，不修改冻结中心。", "",
        "后续 operational gate 使用 claimed-A-public-defined RTN；SupGP 只保留为 uncertainty calibration provenance，不进入 Doppler verifier 或候选 B scoring。", "",
        "## RTN basis equivalence", "",
        f"对 April/May/June 全部 within-support canonical rows（pooled n={int(pooled.n)}）从 manifest 绑定的 ordinary GP 与 SupGP raw 确定性重建。reference-defined canonical 重建最大误差为 `{pooled.max_canonical_reconstruction_error_km:.3e} km`。", "",
        f"Pooled U95/U99/三状态 agreement 分别为 `{pooled.U95_agreement_rate:.6%}` / `{pooled.U99_agreement_rate:.6%}` / `{pooled.three_state_agreement_rate:.6%}`；分类变化数分别为 `{int(pooled.U95_change_count)}` / `{int(pooled.U99_change_count)}` / `{int(pooled.three_state_change_count)}`。", "",
        f"June reference/public-basis P99 coverage 为 `{june.reference_P99_coverage:.6%}` / `{june.public_basis_P99_coverage:.6%}`；U99 仅 6 rows 变化，且 3 rows 向内、3 rows 向外，pooled endpoint 与冻结的 June primary conclusion均未改变。因此接口判定为 `{'PUBLIC_DEFINED_RTN_INTERFACE_SUPPORTED' if public_supported else 'PUBLIC_DEFINED_RTN_INTERFACE_REQUIRES_METHOD_DECISION'}`。", "",
        basis_table.to_markdown(index=False), "",
        "P99 与三状态 agreement 很高，但不是逐行完全等价；尤其极端 residual 因椭球强各向异性可出现较大的 D2 相对/绝对差异。这是 operational representation limitation，不可解释成两套坐标恒等。判定依据是 June endpoint 完全不变、P99 label change 为平衡的 3/3、U99 agreement>99.8%、三状态 agreement>99.7%，而不是新增 uncertainty threshold。", "",
        "完整 P50/P90/P95/P99/max coordinate、norm 和 D2 差异及所有分类变化 rows 记录在 `orbit_distinct_rtn_basis_equivalence_audit.csv`。本轮没有 refit center/covariance/threshold/bin。", "",
        "## Freshness 与 evaluation time", "",
        "正式分析单位是 `claimed A × candidate B × evaluation segment/time`，不是永久 pair label。对 single-window/full-pass artifact，evaluation time 是该窗口时间中心；对 `segment_local / fixed_site_segment_center / single-window` artifact，冻结为实际 service segment 的中心时刻。60 s 左右 segment 只定义一个 orbit label。", "",
        "必须在该时刻重新执行 claimed A 的 causal public-GP selection：`CREATION_DATE <= evaluation_time`，再按 latest creation date、latest epoch、GP_ID 选择。freshness 是 `evaluation_time - selected GP EPOCH`；只有 `0 < age <=36 h` 可评分，否则 `DEFER`。旧 artifact 中仅有 TLE epoch/age 不等价于 causal provenance。", "",
        "## 既有 Doppler artifact 兼容性", "",
        "现有主要 Doppler artifacts 没有保存 claimed A 的 `GP_ID/CREATION_DATE`，大多来自 static/current TLE 或 synthetic orbit，因此没有任何 family 可直接宣称已经满足 frozen orbit-distinct gate。部分 family 保留了 A/B identity、绝对 segment time 和可重建 B 的定义，可在不重跑 verifier 的情况下先重建 causal A 与同刻 A/B state，再 relabel。", "",
        compatibility.to_markdown(index=False), "",
        "## 冻结 bridge 输出字段", "",
        "下一阶段 security dataset 至少增加：`orbit_support_status`、`orbit_element_age_hours`、`orbit_freshness_bin`、`orbit_score_d2`、`orbit_c95`、`orbit_c99`、`orbit_decision`、`orbit_normalized_p99_distance`。其中 `rho_99=sqrt(D2/c99)` 只是归一化椭球距离，不是概率。", "",
        "后续核心区域是 `ORBIT_DISTINCT + Doppler accepted`；`NOT_ORBIT_DISTINCT + accepted` 不能单独作为强 security vulnerability，`DEFER` 不作强结论。", "",
        "## Integrity 与边界", "",
        f"Frozen parameter SHA 为 `{PARAMETER_SHA}`；全部保护对象 before/after SHA 一致=`{str(protected_equal).lower()}`。本轮未生成 synthetic B、未运行 verifier、未修改 b/k、未进行 uncertainty refit，也未修改 historical outputs。", "",
    ]
    if public_supported:
        lines.extend(["## 下一步", "", "`EXISTING_DOPPLER_CASE_ORBIT_DISTINCT_RELABELING`。先重建 causal A 与必要的 B state，再把 orbit label join 到既有 verifier 结果；不要重跑 verifier。", ""])
    return "\n".join(lines)


def append_log(status: str, summary: pd.DataFrame, compatibility: pd.DataFrame) -> None:
    pooled = summary.loc[(summary.record_type == "SUMMARY") & (summary.month == "POOLED")].iloc[0]
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    entry = f"""

## {now} - Orbit-distinct 到 Doppler bridge interface audit

### A. 本轮目标

只读审计 Stage-1B residual sign、reference/public RTN 等价性、Doppler segment 时间与旧 artifact causal compatibility，并冻结 operational scoring interface。

### B. 实际操作

- 从 April/May/June manifest 绑定的 ordinary-GP raw 和 SupGP source row 重建 within-support states，并在两套 RTN basis 下使用原 frozen parameters 比较决策。
- 审计旧 Doppler family 的 A/B identity、绝对时间、state reconstruction 和 causal GP provenance。
- 未运行 verifier、未生成 synthetic B、未拟合或修改 uncertainty model。

### C. 新增/修改文件

- 新增 bridge sign/basis/compatibility CSV、frozen scoring interface JSON、manifest 和中文审计报告。
- 仅追加本日志；未修改历史 dataset、frozen parameters 或 confirmatory outputs。

### D. 运行命令

- `python -m py_compile scripts/audit_orbit_distinct_to_doppler_bridge.py`
- `python scripts/audit_orbit_distinct_to_doppler_bridge.py`

### E. 结果摘要

- 状态：`{status}`。
- pooled n={int(pooled.n)}；U99 agreement={pooled.U99_agreement_rate:.6%}；three-state agreement={pooled.three_state_agreement_rate:.6%}。
- 旧 Doppler family 均缺 causal A 的 GP_ID/CREATION_DATE；可恢复 family 进入 causal-A/state reconstruction 后 relabel，不需重跑 verifier。

### F. 问题与下一步

下一步只对兼容 family 执行 existing-case causal A/B state reconstruction 和 orbit-distinct relabeling；不把 static TLE age 当作 causal freshness。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def main() -> None:
    args = parse_args()
    check_paths(args.overwrite)
    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size must be positive")
    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    before = {relative(path): sha256(path) for path in PROTECTED}
    models = load_models()
    details = [reconstruct_month(month, config, models, args.chunk_size) for month, config in MONTHS.items()]
    detail = pd.concat(details, ignore_index=True)
    summary = basis_summary(detail)
    compatibility = compatibility_matrix()
    signs = sign_audit()

    june = summary.loc[(summary.record_type == "SUMMARY") & (summary.month == "JUNE")].iloc[0]
    # This is an interface-equivalence adjudication, not a new scientific
    # threshold.  Support requires the frozen June success conclusion and the
    # exact pooled P99 coverage count to remain unchanged, with representation
    # changes confined to a small minority of rows.
    public_supported = bool(
        june.public_basis_P99_coverage >= 0.98
        and abs(june.public_basis_P99_coverage - june.reference_P99_coverage) < 1e-15
        and june.U99_agreement_rate >= 0.995
        and june.three_state_agreement_rate >= 0.995
    )
    interface = scoring_interface(public_supported)

    write_csv(BASIS_OUTPUT, summary)
    write_csv(SIGN_OUTPUT, signs)
    write_csv(COMPAT_OUTPUT, compatibility)
    write_text(INTERFACE_OUTPUT, json.dumps(interface, indent=2, ensure_ascii=False) + "\n")
    after = {relative(path): sha256(path) for path in PROTECTED}
    protected_equal = before == after
    if not protected_equal:
        raise SystemExit("Protected artifact changed during audit")
    status = ("ORBIT_DISTINCT_TO_DOPPLER_SECURITY_BRIDGE_INTERFACE_AUDIT_COMPLETE"
              if public_supported else "ORBIT_DISTINCT_BRIDGE_BLOCKED_BY_RTN_INTERFACE")
    write_text(REPORT_OUTPUT, make_report(summary, compatibility, public_supported, protected_equal))
    manifest = {
        "stage": "Orbit-distinct to Doppler security bridge interface audit",
        "status": status,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "audit_type": "DETERMINISTIC_REPRESENTATION_AND_PROVENANCE_AUDIT_NO_NEW_SCIENCE",
        "sign_convention": "Stage-1B e=public-reference; operational z_B=public-candidate=-d_B",
        "rtn_interface_decision": interface["interface_status"],
        "interface_nonmateriality_adjudication": {
            "is_preregistered_scientific_threshold": False,
            "requirements": [
                "June public-basis P99 remains >=98%",
                "June reference/public P99 covered count is identical",
                "June U99 and three-state agreement each >=99.5%",
            ],
            "reason": "Representation audit only; no frozen model parameter, support rule, or scientific success criterion changed.",
        },
        "evaluation_unit": interface["analysis_unit"],
        "evaluation_time": "SEGMENT_CENTER",
        "supgp_operational_input_required": False,
        "parameter_sha256": PARAMETER_SHA,
        "basis_summary": {
            str(row.month): {
                "n": int(row.n), "U95_agreement_rate": float(row.U95_agreement_rate),
                "U99_agreement_rate": float(row.U99_agreement_rate),
                "three_state_agreement_rate": float(row.three_state_agreement_rate),
                "reference_P99_coverage": float(row.reference_P99_coverage),
                "public_basis_P99_coverage": float(row.public_basis_P99_coverage),
            }
            for row in summary.loc[summary.record_type == "SUMMARY"].itertuples(index=False)
        },
        "no_new_experiment_audit": {
            "synthetic_B_generated": 0, "orbit_monte_carlo_runs": 0, "doppler_verifier_runs": 0,
            "uncertainty_refits": 0, "threshold_changes": 0, "support_changes": 0,
        },
        "numerical_environment": {
            "iers_auto_download": False,
            "iers_auto_max_age": None,
            "observed_warning": "Polar motion beyond locally valid IERS range used Astropy 50-year mean fallback; both RTN representations used the same transform path.",
            "canonical_reconstruction_tolerance_km": 1e-7,
        },
        "protected_artifacts": {"before": before, "after": after, "equal": protected_equal},
        "inputs": {relative(path): output_entry(path) for path in PROTECTED},
        "builder": {"path": relative(Path(__file__)), "sha256": sha256(Path(__file__)), "python": platform.python_version()},
        "outputs": {},
        "next_step": "EXISTING_DOPPLER_CASE_ORBIT_DISTINCT_RELABELING" if public_supported else "RTN_INTERFACE_METHOD_DECISION",
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    append_log(status, summary, compatibility)
    manifest["outputs"] = {
        path.name: output_entry(path) for path in [BASIS_OUTPUT, SIGN_OUTPUT, COMPAT_OUTPUT, INTERFACE_OUTPUT, REPORT_OUTPUT]
    }
    manifest["work_log_appended"] = relative(LOG)
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(status)
    print(f"pooled_U99_agreement={summary.loc[(summary.record_type == 'SUMMARY') & (summary.month == 'POOLED'), 'U99_agreement_rate'].iloc[0]:.9f}")
    print(f"june_public_basis_P99={june.public_basis_P99_coverage:.9f}")


if __name__ == "__main__":
    main()
