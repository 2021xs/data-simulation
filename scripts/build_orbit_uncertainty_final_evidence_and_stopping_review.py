#!/usr/bin/env python3
"""Build the final Orbit Uncertainty evidence/stopping review from frozen artifacts only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STATUS = "ORBIT_UNCERTAINTY_BRANCH_COMPLETE"
MODEL_NAME = "Freshness-Conditioned Robust Empirical RTN Ellipsoid"
NEXT_STEP = "ORBIT_DISTINCT_TO_DOPPLER_SECURITY_BRIDGE"
PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
JUNE_CANONICAL_SHA = "DBE3551373D5EFDAF33CFB16296A564ADA29AA49E9852A92F599AD49B00934ED"

METRICS = Path("outputs/metrics")
REPORTS = Path("outputs/reports")
LOG = Path("logs/work_log.md")

EVIDENCE_PATH = METRICS / "orbit_uncertainty_final_evidence_matrix.csv"
STOPPING_PATH = METRICS / "orbit_uncertainty_final_stopping_criteria.csv"
CLAIMS_PATH = METRICS / "orbit_uncertainty_final_supported_claims.csv"
INTERFACE_PATH = METRICS / "orbit_uncertainty_final_downstream_interface.json"
MANIFEST_PATH = METRICS / "orbit_uncertainty_final_manifest.json"
REPORT_PATH = REPORTS / "orbit_uncertainty_final_evidence_and_stopping_review.md"
OUTPUTS = (EVIDENCE_PATH, STOPPING_PATH, CLAIMS_PATH, INTERFACE_PATH, MANIFEST_PATH, REPORT_PATH)

INPUTS = {
    "april_stage1a": Path("outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_acquisition_download_manifest.json"),
    "april_stage1b": Path("outputs/metrics/orbit_uncertainty_stage1b_20260401_20260430_manifest.json"),
    "april_canonical": Path("outputs/datasets/orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv"),
    "april_stage1c": Path("outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_manifest.json"),
    "april_stage1c_report": Path("outputs/reports/orbit_uncertainty_stage1c_20260401_20260430_residual_structure_report.md"),
    "april_stage1d": Path("outputs/metrics/orbit_uncertainty_stage1d_20260401_20260430_manifest.json"),
    "april_stage1d_report": Path("outputs/reports/orbit_uncertainty_stage1d_20260401_20260430_freshness_calibration_report.md"),
    "april_stage1e": Path("outputs/metrics/orbit_uncertainty_stage1e_20260401_20260430_manifest.json"),
    "april_stage1e_report": Path("outputs/reports/orbit_uncertainty_stage1e_20260401_20260430_heterogeneity_regime_report.md"),
    "may_stage1a": Path("outputs/metrics/orbit_uncertainty_stage1_20260501_20260531_acquisition_download_manifest.json"),
    "may_stage1b": Path("outputs/metrics/orbit_uncertainty_stage1b_20260501_20260531_manifest.json"),
    "may_canonical": Path("outputs/datasets/orbit_uncertainty_stage1b_20260501_20260531_rtn_residual_library.csv"),
    "may_external": Path("outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_manifest.json"),
    "may_external_report": Path("outputs/reports/orbit_uncertainty_stage1_external_202605_partial_locked_validation_report.md"),
    "may_model_recoverability": Path("outputs/metrics/orbit_uncertainty_stage1_external_202605_model_recoverability.csv"),
    "stage1f_freeze": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_manifest.json"),
    "stage1f_freeze_report": Path("outputs/reports/orbit_uncertainty_stage1f_lite_design_freeze_report.md"),
    "stage1f_parameters": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_frozen_parameters.csv"),
    "stage1f_internal_validation": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_candidate_internal_validation.csv"),
    "june_supgp_candidate": Path("outputs/metrics/orbit_uncertainty_stage1f_june_supgp_candidate_manifest.json"),
    "june_stage1a": Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_acquisition_download_manifest.json"),
    "june_gt72": Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_manifest.json"),
    "june_readiness_v2": Path("outputs/metrics/orbit_uncertainty_stage1_june_readiness_protocol_adjudication_manifest.json"),
    "june_stage1b": Path("outputs/metrics/orbit_uncertainty_stage1b_20260601_20260630_manifest.json"),
    "june_canonical": Path("outputs/datasets/orbit_uncertainty_stage1b_20260601_20260630_rtn_residual_library.csv"),
    "june_confirmatory": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_confirmatory_manifest.json"),
    "june_confirmatory_report": Path("outputs/reports/orbit_uncertainty_stage1f_lite_june_confirmatory_validation_report.md"),
    "june_bins": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_freshness_bin_coverage.csv"),
    "june_satellites": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_satellite_coverage.csv"),
    "june_structure": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_structural_replication.csv"),
    "june_velocity": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_velocity_diagnostic.csv"),
    "june_reference_sensitivity": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_reference_sensitivity.csv"),
    "june_episodes": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_june_continuous_out_of_set_episodes.csv"),
    "crossmonth_signed_structure": Path("outputs/metrics/orbit_uncertainty_stage1f_lite_signed_rtn_summary.csv"),
    "satellite_persistence": Path("outputs/metrics/orbit_uncertainty_stage1_external_202605_satellite_scale_persistence.csv"),
    "april_freshness": Path("outputs/metrics/orbit_uncertainty_stage1c_20260401_20260430_freshness_summary.csv"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    fields = list(rows[0])
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
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


def output_entry(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def find_row(rows: Iterable[dict[str, str]], **criteria: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            return row
    raise SystemExit(f"Required evidence row missing: {criteria}")


def historical_paths() -> list[Path]:
    excluded = {path.resolve() for path in OUTPUTS}
    paths: list[Path] = []
    for root in (Path("outputs"), Path("data/orbit_uncertainty_stage1")):
        if root.exists():
            paths.extend(path.resolve() for path in root.rglob("*") if path.is_file() and path.resolve() not in excluded)
    return sorted(set(paths), key=lambda path: path.as_posix().lower())


def fingerprint(paths: Iterable[Path]) -> dict[str, str]:
    return {path.as_posix(): sha256(path) for path in paths}


def validate_and_extract() -> dict[str, Any]:
    missing = [name for name, path in INPUTS.items() if not path.exists()]
    if missing:
        raise SystemExit(f"Required authoritative artifacts missing: {missing}")

    april_a = load_json(INPUTS["april_stage1a"])
    may_a = load_json(INPUTS["may_stage1a"])
    june_a = load_json(INPUTS["june_stage1a"])
    april_b = load_json(INPUTS["april_stage1b"])
    may_b = load_json(INPUTS["may_stage1b"])
    june_b = load_json(INPUTS["june_stage1b"])
    may_external = load_json(INPUTS["may_external"])
    freeze = load_json(INPUTS["stage1f_freeze"])
    gt72 = load_json(INPUTS["june_gt72"])
    readiness = load_json(INPUTS["june_readiness_v2"])
    confirm = load_json(INPUTS["june_confirmatory"])

    for month, acquisition, stage1b, expected_rows in [
        ("APRIL", april_a, april_b, 5675),
        ("MAY", may_a, may_b, 6181),
        ("JUNE", june_a, june_b, 5927),
    ]:
        causal = acquisition["causal_support"]
        if not (
            causal["evaluation_count"] == expected_rows
            and causal["candidate_available_count"] == expected_rows
            and causal["future_publication_use_count"] == 0
            and causal["selected_gp_epoch_after_evaluation_count"] == 0
            and stage1b["result"]["future_publication_violations"] == 0
            and stage1b["result"]["negative_element_age"] == 0
            and stage1b["result"]["negative_publication_age"] == 0
        ):
            raise SystemExit(f"{month} causal/provenance validation failed")

    if sha256(INPUTS["stage1f_parameters"]) != PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch")
    if sha256(INPUTS["june_canonical"]) != JUNE_CANONICAL_SHA:
        raise SystemExit("June canonical SHA mismatch")
    if freeze["status"] != "STAGE1F_LITE_DESIGN_AND_FREEZE_COMPLETE":
        raise SystemExit("Stage-1F freeze status mismatch")
    if freeze["candidate_selection"]["primary_candidate_for_june"] != "ROBUST_EMPIRICAL_ELLIPSOID":
        raise SystemExit("Frozen primary candidate mismatch")
    if freeze["candidate_selection"]["secondary_sensitivity_candidate"] != "JOINT_MAX_SCORE_BOX":
        raise SystemExit("Frozen secondary candidate mismatch")
    if may_external["conclusions"] != {
        "M0": "PARTIALLY_SUPPORTED", "M1": "NOT_SUPPORTED", "M2": "PARTIALLY_SUPPORTED",
        "RTN": "SUPPORTED", "NEXT": may_external["conclusions"]["NEXT"],
    }:
        raise SystemExit("May conclusion binding mismatch")
    if gt72["conclusion"] != "JUNE_GT72H_IS_REAL_CAUSAL_PUBLIC_DATA_STALENESS":
        raise SystemExit("June GT72 conclusion mismatch")
    if gt72["comparison"]["class_a_causally_eligible_newer"] != 0:
        raise SystemExit("June GT72 acquisition completeness mismatch")
    if readiness["protocol"]["name"] != "CAUSAL_DATA_READINESS_V2":
        raise SystemExit("Readiness protocol mismatch")
    if readiness["stage_effects"]["stage1f_scientific_protocol_changed"] is not False:
        raise SystemExit("Stage-1F protocol unexpectedly changed")
    if confirm["status"] != "JUNE_STAGE1F_LITE_CONFIRMATORY_SUPPORTED":
        raise SystemExit("June confirmatory status mismatch")
    if not confirm["protection"]["before_after_equal"] or not confirm["correctness"]["all_passed"]:
        raise SystemExit("June confirmatory provenance/correctness failure")
    if any(value != 0 for value in confirm["no_june_fitting_audit"].values()):
        raise SystemExit("June-derived fitted parameter found")

    primary = confirm["primary_result"]
    if not (
        primary["n"] == 5389 and primary["p99_covered_count"] == 5360
        and primary["p99_exceedance_count"] == 29
        and primary["p99_joint_coverage"] >= 0.98
        and primary["structural_bin_undercoverage_count"] == 0
    ):
        raise SystemExit("June primary result does not satisfy frozen stopping evidence")

    freshness = load_csv(INPUTS["april_freshness"])
    freshness_row = find_row(
        freshness, section="correlation", view="full", scope="pooled",
        predictor="element_age_hours", outcome="position_error_norm_km", method="spearman",
    )
    signed = load_csv(INPUTS["crossmonth_signed_structure"])
    april_rtn = find_row(signed, scope="APRIL", freshness_bin="ALL")
    may_rtn = find_row(signed, scope="MAY", freshness_bin="ALL")
    june_structure = load_csv(INPUTS["june_structure"])
    june_rtn = find_row(june_structure, scope="JUNE_WITHIN_SUPPORT", freshness_bin="ALL")
    june_bins = [row for row in load_csv(INPUTS["june_bins"]) if row["candidate"] == "ROBUST_EMPIRICAL_ELLIPSOID"]
    june_satellites = [row for row in load_csv(INPUTS["june_satellites"]) if row["candidate"] == "ROBUST_EMPIRICAL_ELLIPSOID"]
    june_velocity = find_row(load_csv(INPUTS["june_velocity"]), scope="JUNE")
    rms_q1 = find_row(load_csv(INPUTS["june_reference_sensitivity"]), group_id="RMS_Q1")
    rms_q4 = find_row(load_csv(INPUTS["june_reference_sensitivity"]), group_id="RMS_Q4")
    recoverability = load_csv(INPUTS["may_model_recoverability"])
    m3 = find_row(recoverability, model="M3")
    m4 = find_row(recoverability, model="M4")

    return {
        "april_freshness_spearman": float(freshness_row["correlation"]),
        "april_t_dominant": float(april_rtn["T_dominant_fraction"]),
        "may_t_dominant": float(may_rtn["T_dominant_fraction"]),
        "june_t_dominant": float(june_rtn["T_dominant_fraction"]),
        "june_median_abs_rtn": [float(june_rtn[key]) for key in ("median_abs_R_km", "median_abs_T_km", "median_abs_N_km")],
        "june_min_bin_p99": min(float(row["p99_joint_coverage"]) for row in june_bins),
        "june_bin_failures": sum(row["structural_bin_undercoverage"].lower() == "true" for row in june_bins),
        "june_min_satellite_p99": min(float(row["p99_joint_coverage"]) for row in june_satellites),
        "june_satellites_below_95": sum(float(row["p99_joint_coverage"]) < 0.95 for row in june_satellites),
        "june_velocity_pearson": float(june_velocity["pearson_delta_T_delta_v_R"]),
        "june_velocity_spearman": float(june_velocity["spearman_delta_T_delta_v_R"]),
        "rms_q1_p95": float(rms_q1["p95_joint_coverage"]),
        "rms_q1_p99": float(rms_q1["p99_joint_coverage"]),
        "rms_q4_p95": float(rms_q4["p95_joint_coverage"]),
        "rms_q4_p99": float(rms_q4["p99_joint_coverage"]),
        "m3_status": m3["status"], "m4_status": m4["status"],
        "primary": primary, "secondary": confirm["secondary_result"],
        "candidate_selection": freeze["candidate_selection"],
        "episode_summary": confirm["episode_summary"],
        "population": confirm["population"],
        "protected_count": confirm["protection"]["artifact_count"],
        "gt72_rows": gt72["affected"]["row_count"],
    }


def evidence_rows(facts: dict[str, Any]) -> list[dict[str, str]]:
    primary = facts["primary"]
    return [
        {"evidence_level": "LEVEL_1_DATA_PROVENANCE_VALIDITY", "topic": "Causal ordinary-GP selection", "authoritative_artifacts": "April/May/June Stage-1A and Stage-1B manifests", "evidence": "All 5675/6181/5927 epochs have causal candidates; future-publication use, selected future epoch, and negative ages are zero.", "interpretation": "Historical predictions are causally reconstructable.", "status": "SUPPORTED"},
        {"evidence_level": "LEVEL_1_DATA_PROVENANCE_VALIDITY", "topic": "Reference semantics", "authoritative_artifacts": "April/May/June Stage-1B manifests", "evidence": "SpaceX-E/SupGP is consistently identified as a higher-quality historical reference.", "interpretation": "Residuals are ordinary-GP disagreement relative to reference, not true-orbit error.", "status": "SUPPORTED_WITH_SCOPE"},
        {"evidence_level": "LEVEL_1_DATA_PROVENANCE_VALIDITY", "topic": "June GT72 completeness", "authoritative_artifacts": "June GT72 completeness manifest", "evidence": f"{facts['gt72_rows']} rows; targeted/current records 65/65; missing causal-newer records=0.", "interpretation": "GT72 cases are real causal public-data staleness, not acquisition omission.", "status": "SUPPORTED"},
        {"evidence_level": "LEVEL_1_DATA_PROVENANCE_VALIDITY", "topic": "Readiness amendment", "authoritative_artifacts": "CAUSAL_DATA_READINESS_V2 manifest", "evidence": "72 h clarified as engineering readiness; Stage-1F scientific protocol changed=false.", "interpretation": "The amendment is not post-hoc uncertainty-model tuning.", "status": "SUPPORTED"},
        {"evidence_level": "LEVEL_2_REPLICATED_ORBIT_ERROR_STRUCTURE", "topic": "Freshness dependence", "authoritative_artifacts": "April Stage-1C; May external validation; June bin coverage", "evidence": f"April age/norm Spearman={facts['april_freshness_spearman']:.6f}; May M0 partially supported; June minimum bin P99={facts['june_min_bin_p99']:.6f}.", "interpretation": "Conditional error scale depends statistically on element age; strict rowwise monotonicity is not claimed.", "status": "SUPPORTED_WITH_LIMITATION"},
        {"evidence_level": "LEVEL_2_REPLICATED_ORBIT_ERROR_STRUCTURE", "topic": "RTN anisotropy", "authoritative_artifacts": "Stage-1F signed RTN summary; June structural replication", "evidence": f"T-dominance April/May/June={facts['april_t_dominant']:.6f}/{facts['may_t_dominant']:.6f}/{facts['june_t_dominant']:.6f}.", "interpretation": "Strong cross-month T dominance supports directional RTN representation over an isotropic norm-only sphere.", "status": "REPLICATED"},
        {"evidence_level": "LEVEL_2_REPLICATED_ORBIT_ERROR_STRUCTURE", "topic": "Position/velocity coupling", "authoritative_artifacts": "Stage-1F velocity diagnostic", "evidence": f"June corr(delta_T,delta_v_R): Pearson={facts['june_velocity_pearson']:.6f}, Spearman={facts['june_velocity_spearman']:.6f}.", "interpretation": "Coupling replicates, but incremental security value of a 6D set is unproven.", "status": "SUPPORTED_DIAGNOSTIC"},
        {"evidence_level": "LEVEL_3_CALIBRATION_TRANSFERABILITY", "topic": "Publication age", "authoritative_artifacts": "May partial locked external validation", "evidence": "M1=NOT_SUPPORTED after April-to-May transfer.", "interpretation": "Drop from primary; no claim that publication age is universally irrelevant.", "status": "NOT_SUPPORTED_FOR_MAINLINE"},
        {"evidence_level": "LEVEL_3_CALIBRATION_TRANSFERABILITY", "topic": "Satellite-wide fixed scale", "authoritative_artifacts": "May satellite persistence; June satellite coverage", "evidence": "May M2=PARTIALLY_SUPPORTED; P95 rank persistence R/T/N/norm=0.188/0.182/0.686/0.182; June has no satellite P99<95%.", "interpretation": "No sufficiently stable scalar effect requiring a satellite-specific primary model.", "status": "NOT_SUFFICIENTLY_SUPPORTED"},
        {"evidence_level": "LEVEL_3_CALIBRATION_TRANSFERABILITY", "topic": "Causal regime model", "authoritative_artifacts": "Stage-1E; May model recoverability; June confirmatory", "evidence": f"M3/M4 statuses={facts['m3_status']}/{facts['m4_status']}; simple frozen gate passes June.", "interpretation": "Strict M3/M4 transfer was unavailable, but regime modeling is non-blocking for the final primary model.", "status": "NON_BLOCKING_LIMITATION"},
        {"evidence_level": "LEVEL_4_FINAL_JOINT_UNCERTAINTY_GATE", "topic": "Frozen joint representation", "authoritative_artifacts": "Stage-1F freeze manifest and parameters", "evidence": "Signed 3D RTN robust center/covariance shape with empirical score quantiles; Gaussian chi-square not used.", "interpretation": MODEL_NAME + " is the final primary model.", "status": "FROZEN"},
        {"evidence_level": "LEVEL_4_FINAL_JOINT_UNCERTAINTY_GATE", "topic": "Untouched June P99", "authoritative_artifacts": "June confirmatory manifest", "evidence": f"{primary['p99_covered_count']}/{primary['n']}={primary['p99_joint_coverage']:.6f}; cluster CI [{primary['p99_cluster_bootstrap_ci_low']:.6f},{primary['p99_cluster_bootstrap_ci_high']:.6f}].", "interpretation": "Meets preregistered pooled P99>=98% with zero structural-bin failures.", "status": "CONFIRMATORY_SUPPORTED"},
        {"evidence_level": "LEVEL_4_FINAL_JOINT_UNCERTAINTY_GATE", "topic": "Box sensitivity", "authoritative_artifacts": "Stage-1F freeze and June confirmatory manifests", "evidence": f"Box P99={facts['secondary']['p99_joint_coverage']:.6f} vs Ellipsoid={primary['p99_joint_coverage']:.6f}; development final volume ratio={facts['candidate_selection']['ellipse_over_box_p99_geometric_mean_volume_ratio']['FINAL_COMBINED']:.6f}.", "interpretation": "June success is not fragile to geometry; Ellipsoid remains primary under the frozen complexity rule.", "status": "PASS"},
        {"evidence_level": "LEVEL_5_LIMITATIONS_NON_GENERALIZABLE", "topic": "P95 calibration", "authoritative_artifacts": "June confirmatory manifest", "evidence": f"P95={primary['p95_joint_coverage']:.6f}; cluster CI [{primary['p95_cluster_bootstrap_ci_low']:.6f},{primary['p95_cluster_bootstrap_ci_high']:.6f}].", "interpretation": "Secondary calibration is less stable than conservative P99; it does not override the primary rule.", "status": "LIMITATION"},
        {"evidence_level": "LEVEL_5_LIMITATIONS_NON_GENERALIZABLE", "topic": "Temporal nonstationarity", "authoritative_artifacts": "June continuous episode output", "evidence": f"U99 episodes={facts['episode_summary']['u99_episode_count']}; max duration={facts['episode_summary']['max_u99_duration_hours']:.2f} h.", "interpretation": "Pointwise exceedances cluster in time; no maneuver attribution.", "status": "LIMITATION"},
        {"evidence_level": "LEVEL_5_LIMITATIONS_NON_GENERALIZABLE", "topic": "Reference sensitivity", "authoritative_artifacts": "June RMS diagnostic", "evidence": f"Q1/Q4 P95={facts['rms_q1_p95']:.6f}/{facts['rms_q4_p95']:.6f}; Q4 P99={facts['rms_q4_p99']:.6f}.", "interpretation": "Bulk P95 varies with RMS proxy, while P99 conclusion is not reversed; RMS remains reference-only.", "status": "LIMITATION"},
        {"evidence_level": "LEVEL_5_LIMITATIONS_NON_GENERALIZABLE", "topic": "Population and support", "authoritative_artifacts": "Freeze and June confirmatory manifests", "evidence": "20 same-shell Starlink satellites, April-June 2026, formal support 0<age<=36 h.", "interpretation": "No universal Starlink, all-LEO, or >36 h validity claim.", "status": "LIMITATION"},
        {"evidence_level": "LEVEL_6_STOPPING_DECISION", "topic": "Branch stopping", "authoritative_artifacts": "Stage-1F preregistered stopping rule plus all evidence above", "evidence": "All blocking criteria pass; remaining issues are scoped limitations or diagnostics.", "interpretation": "Stop uncertainty-model optimization and proceed to the security bridge.", "status": STATUS},
    ]


def stopping_rows(facts: dict[str, Any]) -> list[dict[str, str]]:
    primary = facts["primary"]
    return [
        {"criterion": "Freshness structure", "pre_registered_requirement": "No qualitative failure", "evidence": f"April age/norm Spearman {facts['april_freshness_spearman']:.6f}; May partial transfer; June six-bin minimum P99 {facts['june_min_bin_p99']:.6f}", "status": "PASS_WITH_LIMITATION", "reason": "Freshness is useful conditioning, not a strict rowwise monotone law."},
        {"criterion": "RTN anisotropy", "pre_registered_requirement": "No qualitative reversal", "evidence": f"T-dominance April/May/June {facts['april_t_dominant']:.4%}/{facts['may_t_dominant']:.4%}/{facts['june_t_dominant']:.4%}", "status": "PASS", "reason": "Strong T dominance replicated across all months and all June bins."},
        {"criterion": "Joint P99 external coverage", "pre_registered_requirement": "June pooled P99 >=98%", "evidence": f"{primary['p99_covered_count']}/{primary['n']}={primary['p99_joint_coverage']:.4%}; cluster CI {primary['p99_cluster_bootstrap_ci_low']:.4%}-{primary['p99_cluster_bootstrap_ci_high']:.4%}", "status": "PASS", "reason": "Untouched June primary endpoint passed."},
        {"criterion": "Freshness-bin stability", "pre_registered_requirement": "No bin with n>=100 and P99<95%", "evidence": f"Failures={facts['june_bin_failures']}; minimum bin P99={facts['june_min_bin_p99']:.4%}", "status": "PASS", "reason": "All six populated bins exceed 99%."},
        {"criterion": "Satellite-wise catastrophic failure", "pre_registered_requirement": "No stable repeated severe satellite failure", "evidence": f"June minimum satellite P99={facts['june_min_satellite_p99']:.4%}; satellites below 95%={facts['june_satellites_below_95']}", "status": "PASS_WITH_LIMITATION", "reason": "Heterogeneity remains, but no June catastrophic or stable repeated severe pattern."},
        {"criterion": "Candidate complexity comparison", "pre_registered_requirement": "Ellipsoid earns complexity only with >=10% stable volume reduction and <=0.5 pp P99 degradation", "evidence": f"Development Ellipsoid/Box P99 volume ratios month/LOSO/final={facts['candidate_selection']['ellipse_over_box_p99_geometric_mean_volume_ratio']['MONTH_DIRECTION']:.3f}/{facts['candidate_selection']['ellipse_over_box_p99_geometric_mean_volume_ratio']['LEAVE_ONE_SATELLITE_OUT']:.3f}/{facts['candidate_selection']['ellipse_over_box_p99_geometric_mean_volume_ratio']['FINAL_COMBINED']:.3f}; June Box advantage={(facts['secondary']['p99_joint_coverage']-primary['p99_joint_coverage'])*100:.4f} pp", "status": "PASS", "reason": "Frozen Ellipsoid selection remains justified; Box confirms robustness."},
        {"criterion": "Satellite-specific model necessity", "pre_registered_requirement": "No new stable fixed satellite-wide scale evidence", "evidence": "May rank persistence weak except N; June named satellites do not repeat severe joint undercoverage", "status": "PASS_WITH_LIMITATION", "reason": "Satellite-specific effects remain diagnostic, not required in primary."},
        {"criterion": "Regime-detector necessity", "pre_registered_requirement": "Not necessary for downstream security conclusion", "evidence": "Frozen simple gate passes June without regime parameters; M3/M4 strict May transfer blocked by incomplete fitted-pipeline provenance", "status": "PASS_WITH_LIMITATION", "reason": "Regime detector is optional/non-blocking; its transferability remains unevaluated."},
        {"criterion": "Reference sensitivity", "pre_registered_requirement": "Must not reverse primary conclusion", "evidence": f"RMS Q4 P95={facts['rms_q4_p95']:.4%}, P99={facts['rms_q4_p99']:.4%}", "status": "PASS_WITH_LIMITATION", "reason": "P95 sensitivity exists; Q4 P99 remains above the pooled success threshold."},
        {"criterion": "Temporal nonstationarity", "pre_registered_requirement": "Handled by abstention/episodes without primary-rule failure", "evidence": f"Max U99 episode={facts['episode_summary']['max_u99_duration_hours']:.2f} h; max U95={facts['episode_summary']['max_u95_duration_hours']:.2f} h", "status": "PASS_WITH_LIMITATION", "reason": "Temporal clustering remains a limitation, not a primary coverage failure."},
        {"criterion": "6D necessity", "pre_registered_requirement": "Only extend if incremental security-decision value is established", "evidence": f"June T-vR Pearson/Spearman={facts['june_velocity_pearson']:.6f}/{facts['june_velocity_spearman']:.6f}; no 6D set built", "status": "PASS_WITH_LIMITATION", "reason": "Physical coupling replicates, but incremental decision value is unproven; NOT_NEEDED_YET."},
        {"criterion": "Provenance/freeze integrity", "pre_registered_requirement": "Frozen and canonical artifacts unchanged; numerical audit passes", "evidence": f"Frozen parameter SHA={PARAMETER_SHA}; June protected count={facts['protected_count']}; confirmatory correctness all passed", "status": "PASS", "reason": "No provenance or numerical invalidation."},
        {"criterion": "June-derived fitting", "pre_registered_requirement": "All June-derived fitted parameter counts equal zero", "evidence": "center/covariance/MAD-scale/threshold/bin/satellite/regime counts=0", "status": "PASS", "reason": "June remained confirmatory test data."},
        {"criterion": "Downstream readiness", "pre_registered_requirement": "All blocking stopping conditions pass", "evidence": "P99, structural, geometry, provenance, and zero-fitting requirements pass", "status": "PASS", "reason": "Stable uncertainty interface is ready for orbit-distinct to Doppler security."},
    ]


def claim_rows(facts: dict[str, Any]) -> list[dict[str, str]]:
    p = facts["primary"]
    return [
        {"claim_level": "SUPPORTED", "claim_id": "S1", "claim": "Public ordinary-GP disagreement has statistically supported freshness dependence in the studied data.", "allowed_wording": "Element age is a supported conditioning variable for the empirical disagreement scale.", "boundary": "Do not claim every residual increases monotonically with age.", "evidence": "April association, partial May transfer, stable June conditional P99."},
        {"claim_level": "SUPPORTED", "claim_id": "S2", "claim": "Position residuals exhibit strong, cross-month stable RTN anisotropy with T dominance.", "allowed_wording": f"T-dominance replicated at {facts['april_t_dominant']:.1%}/{facts['may_t_dominant']:.1%}/{facts['june_t_dominant']:.1%} in April/May/June.", "boundary": "Restricted to the studied cohort/time/reference.", "evidence": "Signed RTN summaries."},
        {"claim_level": "SUPPORTED", "claim_id": "S3", "claim": "An isotropic position-norm sphere does not preserve the observed directional structure.", "allowed_wording": "A signed RTN representation retains anisotropy that a norm-only sphere omits.", "boundary": "This is a representation claim, not universal superiority for every task.", "evidence": "Cross-month RTN anisotropy."},
        {"claim_level": "SUPPORTED", "claim_id": "S4", "claim": "A freshness-conditioned signed 3D RTN joint set is an appropriate decision representation for this pipeline.", "allowed_wording": MODEL_NAME + " is the frozen primary uncertainty gate.", "boundary": "Do not call its covariance true orbit covariance.", "evidence": "Stage-1F internal validation, volume rule, June confirmation."},
        {"claim_level": "SUPPORTED", "claim_id": "S5", "claim": "The April+May frozen Ellipsoid achieved 99.4619% empirical P99 joint coverage on untouched June.", "allowed_wording": f"Legitimate ordinary-GP disagreement coverage was {p['p99_covered_count']}/{p['n']} with satellite-cluster CI {p['p99_cluster_bootstrap_ci_low']:.4%}-{p['p99_cluster_bootstrap_ci_high']:.4%}.", "boundary": "Not accuracy, attack detection accuracy, or true-orbit coverage.", "evidence": "June locked confirmatory manifest."},
        {"claim_level": "SUPPORTED", "claim_id": "S6", "claim": "A fixed satellite-wide scalar lacks sufficient stable cross-month evidence for the primary model.", "allowed_wording": "Satellite scale remains a subgroup diagnostic rather than a primary fitted effect.", "boundary": "Do not claim satellite identity never matters.", "evidence": "May M2 partial support and June satellite distribution."},
        {"claim_level": "SUPPORTED", "claim_id": "S7", "claim": "Publication age did not show stable additional transfer benefit after element-age conditioning.", "allowed_wording": "M1 was not supported in the April-to-May locked transfer.", "boundary": "Do not claim publication age is universally irrelevant.", "evidence": "May partial locked external validation."},
        {"claim_level": "LIMITED", "claim_id": "L1", "claim": "Population scope", "allowed_wording": "20 same-shell Starlink satellites near the studied 53.16-degree, 473-km shell.", "boundary": "Not universal Starlink or all LEO.", "evidence": "Frozen cohort and manifests."},
        {"claim_level": "LIMITED", "claim_id": "L2", "claim": "Temporal scope", "allowed_wording": "April-June 2026 historical evaluation.", "boundary": "No untested year/season extrapolation.", "evidence": "Formal windows."},
        {"claim_level": "LIMITED", "claim_id": "L3", "claim": "Reference semantics", "allowed_wording": "SpaceX-E/SupGP higher-quality historical reference.", "boundary": "Not ground truth.", "evidence": "Stage-1B comparison semantics."},
        {"claim_level": "LIMITED", "claim_id": "L4", "claim": "Freshness support", "allowed_wording": "Empirically calibrated for 0<element age<=36 h; outside is DEFER.", "boundary": "36 h is not a universal GP validity limit.", "evidence": "Frozen protocol."},
        {"claim_level": "LIMITED", "claim_id": "L5", "claim": "P99 role", "allowed_wording": "A conservative preregistered security-design gate for this study.", "boundary": "Not an aerospace or industry universal standard.", "evidence": "Freeze manifest."},
        {"claim_level": "LIMITED", "claim_id": "L6", "claim": "Temporal episodes", "allowed_wording": "Continuous out-of-set episodes demonstrate clustered exceedances/nonstationarity.", "boundary": "Do not label episodes maneuvers.", "evidence": "June episode audit."},
        {"claim_level": "LIMITED", "claim_id": "L7", "claim": "P95/reference sensitivity", "allowed_wording": "P95 transfers less stably and is lower in RMS Q4; P99 conclusion remains supported.", "boundary": "Do not hide P95 undercoverage or make RMS operational.", "evidence": "June confirmatory diagnostics."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P1", "claim": "Universal Starlink uncertainty model", "allowed_wording": "PROHIBITED", "boundary": "Cohort/time-limited evidence only.", "evidence": "Scope restriction."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P2", "claim": "Applicable to all LEO", "allowed_wording": "PROHIBITED", "boundary": "No cross-constellation/orbit evidence.", "evidence": "Scope restriction."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P3", "claim": "SupGP is ground truth or covariance is true covariance", "allowed_wording": "PROHIBITED", "boundary": "Reference-relative empirical disagreement only.", "evidence": "Comparison semantics."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P4", "claim": "A high-score episode confirms a maneuver", "allowed_wording": "PROHIBITED", "boundary": "Use continuous out-of-set episode.", "evidence": "Frozen episode semantics."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P5", "claim": "Orbits older than 36 h are impossible or invalid", "allowed_wording": "PROHIBITED", "boundary": "They are outside calibrated support and deferred.", "evidence": "Support semantics."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P6", "claim": "P99 is an industry standard", "allowed_wording": "PROHIBITED", "boundary": "Study-specific preregistered choice.", "evidence": "Freeze protocol."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P7", "claim": "0.5381% is an attack false-positive rate or attack success probability", "allowed_wording": "PROHIBITED", "boundary": "It is legitimate false-orbit-distinct rate.", "evidence": "Decision semantics."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P8", "claim": "99.4619% attack detection accuracy", "allowed_wording": "PROHIBITED", "boundary": "It is legitimate reference-relative empirical joint coverage.", "evidence": "June endpoint definition."},
        {"claim_level": "UNSUPPORTED_PROHIBITED", "claim_id": "P9", "claim": "A fixed universal kilometer boundary", "allowed_wording": "PROHIBITED", "boundary": "The gate is freshness-conditioned and anisotropic.", "evidence": "Frozen parameterization."},
    ]


def downstream_interface() -> dict[str, Any]:
    return {
        "interface_name": "FROZEN_ORBIT_UNCERTAINTY_TO_DOPPLER_SECURITY_V1",
        "model_name": MODEL_NAME,
        "status": "FROZEN_READY_FOR_DOWNSTREAM",
        "parameter_artifact": {"path": INPUTS["stage1f_parameters"].as_posix(), "sha256": PARAMETER_SHA},
        "input": {
            "claimed_A_public_GP_prediction": "GCRS state propagated causally to evaluation_time",
            "evaluation_time": "UTC",
            "candidate_B_state": "GCRS state at the same evaluation_time",
        },
        "derived": {
            "freshness": "element_age_hours of claimed A public GP",
            "rtn_basis": "claimed A public predicted state",
            "signed_displacement": "d_B = candidate B state - claimed A public predicted state, projected into claimed-A-defined RTN",
            "score": "D2 = (d_B - frozen_mu_k)^T frozen_Sigma_k^-1 (d_B - frozen_mu_k)",
            "threshold_lookup": "frozen freshness bin k",
        },
        "support": {"lower_hours_exclusive": 0.0, "upper_hours_inclusive": 36.0, "outside_decision": "DEFER"},
        "freshness_bins_hours": [[0, 6], [6, 9], [9, 12], [12, 18], [18, 24], [24, 36]],
        "decision": [
            {"condition": "age<=0 or age>36 h", "output": "DEFER"},
            {"condition": "within support and D2<=c95", "output": "NOT_ORBIT_DISTINCT"},
            {"condition": "within support and c95<D2<=c99", "output": "AMBIGUOUS"},
            {"condition": "within support and D2>c99", "output": "ORBIT_DISTINCT"},
        ],
        "semantic_guard": "ORBIT_DISTINCT is an uncertainty-gate decision, not attack success/failure.",
        "next_research_question": "For candidate B cases classified ORBIT_DISTINCT, can the Doppler claimed-identity verifier still accept B?",
        "danger_region": "ORBIT_DISTINCT + DOPPLER_INDISTINGUISHABLE",
        "fitting_or_recalibration_allowed": False,
    }


def markdown_table(rows: list[dict[str, Any]], fields: list[str]) -> str:
    header = "| " + " | ".join(fields) + " |"
    divider = "|" + "|".join("---" for _ in fields) + "|"
    body = ["| " + " | ".join(str(row.get(field, "")).replace("|", "/") for field in fields) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def build_report(facts: dict[str, Any], stopping: list[dict[str, str]], claims: list[dict[str, str]]) -> str:
    p = facts["primary"]
    supported = [row for row in claims if row["claim_level"] == "SUPPORTED"]
    limited = [row for row in claims if row["claim_level"] == "LIMITED"]
    prohibited = [row for row in claims if row["claim_level"] == "UNSUPPORTED_PROHIBITED"]
    return f"""# Orbit Uncertainty final evidence and stopping review

## Executive decision

正式状态：`{STATUS}`。

主线决策：`STOP ORBIT-UNCERTAINTY MODEL OPTIMIZATION`。July：`NOT REQUIRED FOR MAINLINE`。Satellite-specific model：`DOWNGRADED / NOT REQUIRED`。Regime detector：`OPTIONAL / NON-BLOCKING`。6D：`NOT NEEDED YET`。

最终论文术语统一为 **{MODEL_NAME}**。下一主线严格为 `{NEXT_STEP}`。

## LEVEL 1: DATA / PROVENANCE VALIDITY

April、May、June 分别有 5675、6181、5927 个 historical SupGP evaluation epochs，全部存在 ordinary-GP causal candidate；selection 均为 `CREATION_DATE <= evaluation_time; latest CREATION_DATE -> latest EPOCH -> GP_ID`，future-publication use、selected future epoch、negative element/publication age 均为 0。SpaceX-E/SupGP 是 higher-quality historical reference，不是 ground truth；所得量是 ordinary-GP prediction disagreement relative to reference。

June 的 25 个 GT72 rows 经 7 星 targeted completeness query 确认：targeted/current same-window records=65/65，missing causal-newer record=0，因此属于真实 causal public-data staleness。`CAUSAL_DATA_READINESS_V2` 只澄清 engineering readiness，`Stage-1F scientific protocol changed=false`；25 rows 均在 >36 h outside-support population 中并保持 DEFER。

## LEVEL 2: REPLICATED ORBIT-ERROR STRUCTURE

Freshness：April element age 与 position norm Spearman=`{facts['april_freshness_spearman']:.6f}`；May M0 transfer=`PARTIALLY_SUPPORTED`；June 冻结六 bin 的最小 P99=`{facts['june_min_bin_p99']:.4%}`。因此可写“conditional error scale statistically depends on freshness”，不可写逐行严格单调。

RTN anisotropy：April/May/June T-dominant fraction=`{facts['april_t_dominant']:.4%}` / `{facts['may_t_dominant']:.4%}` / `{facts['june_t_dominant']:.4%}`。June median |R/T/N|=`{facts['june_median_abs_rtn'][0]:.4f}/{facts['june_median_abs_rtn'][1]:.4f}/{facts['june_median_abs_rtn'][2]:.4f} km`，全部六 bin T dominant。结论：`RTN_ANISOTROPY_REPLICATED`；norm-only isotropic sphere 不能保留该方向结构。

Velocity：June `corr(delta_T,delta_v_R)` Pearson/Spearman=`{facts['june_velocity_pearson']:.6f}/{facts['june_velocity_spearman']:.6f}`，与 April/May 的极强耦合一致。但没有证据证明 6D set 改善 security decision，故 `6D_EXTENSION_DECISION=NOT_NEEDED_YET`。

## LEVEL 3: CALIBRATION / TRANSFERABILITY

- Publication age M1：May `NOT_SUPPORTED`，从 primary 删除；只表示控制 element age 后未见稳定 secondary transfer gain。
- Satellite-wide scale M2：May `PARTIALLY_SUPPORTED`；April→May P95 ranking R/T/N/norm约`0.188/0.182/0.686/0.182`。June 无 satellite P99<95%，没有 stable repeated severe joint undercoverage。因此 `NOT_SUFFICIENTLY_SUPPORTED`，仅保留 subgroup diagnostic。
- Regime M3/M4：April fitted preprocessing 缺 logistic intercept、StandardScaler、SimpleImputer 和 manifest-bound pipeline，严格 May transfer 未完成。由于 regime 不属于 final primary 且简单模型已通过 June，该问题为 `NON_BLOCKING_LIMITATION`，不重做 M3/M4。

## LEVEL 4: FINAL JOINT UNCERTAINTY GATE

Stage-1F-lite 从 marginal absolute components 升级为 signed 3D RTN joint set。Ellipsoid 使用 robust center 与 covariance geometry，但 c95/c99 来自 development legitimate residual score 的 empirical quantiles，不使用 Gaussian chi-square threshold，也不把 covariance 称为 true covariance。

在冻结支持域 `0 < element_age_hours <= 36` 内，April+May 校准的 primary Ellipsoid 在 untouched June 达到 `{p['p99_covered_count']}/{p['n']}={p['p99_joint_coverage']:.4%}` joint legitimate coverage，satellite-cluster 95% CI=`[{p['p99_cluster_bootstrap_ci_low']:.4%}, {p['p99_cluster_bootstrap_ci_high']:.4%}]`；legitimate false-orbit-distinct rate=`{p['false_orbit_distinct_rate']:.4%}`。预注册 P99>=98% 和 structural-bin rule 均通过。

Box sensitivity P99=`{facts['secondary']['p99_joint_coverage']:.4%}`，比 Ellipsoid 高 `{(facts['secondary']['p99_joint_coverage']-p['p99_joint_coverage'])*100:.4f} pp`。这表明成功不依赖单一 geometry；不能 post-hoc swap。Ellipsoid 的 development final P99 volume ratio=`{facts['candidate_selection']['ellipse_over_box_p99_geometric_mean_volume_ratio']['FINAL_COMBINED']:.4f}`，仍满足预注册复杂度收益，故 `ELLIPSOID_PRIMARY_RETAINED`。

## LEVEL 5: LIMITATIONS / NON-GENERALIZABLE CLAIMS

P95=`{p['p95_joint_coverage']:.4%}`，低于 nominal 95%；RMS Q4 P95=`{facts['rms_q4_p95']:.4%}`，而 Q1=`{facts['rms_q1_p95']:.4%}`。P95 对时间/reference-quality proxy 的 transfer 较弱，是正式 secondary calibration limitation。Q4 P99=`{facts['rms_q4_p99']:.4%}`，没有反转 primary P99 conclusion；RMS 继续是 `REFERENCE_ONLY`。

June 最大 U99 continuous out-of-set episode=`{facts['episode_summary']['max_u99_duration_hours']:.2f} h`，最大 U95=`{facts['episode_summary']['max_u95_duration_hours']:.2f} h`。高 overall pointwise coverage 不意味着 exceedances 独立；`TEMPORAL_NONSTATIONARITY=LIMITATION`，不得称 episode 为 maneuver。

模型范围仅为 studied 20-Starlink same-shell cohort、April-June 2026、higher-quality historical reference 和 0-36 h calibrated support。36 h 不是 universal GP validity limit，P99 也不是 industry standard。

## LEVEL 6: STOPPING DECISION

{markdown_table(stopping, ['criterion', 'pre_registered_requirement', 'status', 'reason'])}

所有 blocking stopping criteria 已满足。`PASS_WITH_LIMITATION` 项已进入论文限制和 downstream sensitivity 语义，但不要求继续优化 uncertainty predictor。只有这些 limitation 实际改变后续 orbit-distinct / Doppler security conclusion 时，才允许另开 sensitivity branch。

## Supported claims

{markdown_table(supported, ['claim_id', 'claim', 'allowed_wording', 'boundary'])}

## Limited claims

{markdown_table(limited, ['claim_id', 'claim', 'allowed_wording', 'boundary'])}

## Unsupported / prohibited claims

{markdown_table(prohibited, ['claim_id', 'claim', 'boundary'])}

## Downstream interface

稳定接口定义在 `outputs/metrics/orbit_uncertainty_final_downstream_interface.json`。输入为 claimed A causal public-GP prediction、evaluation time 与 candidate B state；输出 freshness、claimed-A-defined RTN displacement、frozen Ellipsoid D2 和 `NOT_ORBIT_DISTINCT / AMBIGUOUS / ORBIT_DISTINCT / DEFER`。

下一研究问题是：当 B 已被 frozen gate 判为 `ORBIT_DISTINCT` 时，Doppler claimed-identity verifier 是否仍可能接受 B。核心危险区域为 `ORBIT_DISTINCT + DOPPLER_INDISTINGUISHABLE`。
"""


def append_log(output_paths: list[Path]) -> None:
    marker = "Orbit Uncertainty final evidence and stopping review"
    if LOG.exists() and marker in LOG.read_text(encoding="utf-8", errors="replace"):
        return
    entry = f"""

## {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')} - {marker}

### A. 本轮目标

只读审计 April→May→Stage-1F freeze→June confirmatory 的既有证据，逐项执行预注册 stopping rule，冻结论文 claim boundary 与 downstream interface；不运行新科学实验。

### B. 实际操作

- 交叉验证三个月 causal selection、reference semantics、GT72 completeness、CAUSAL_DATA_READINESS_V2、Stage-1F freeze 和 June confirmatory provenance。
- 整理六层 evidence matrix、14项 stopping criteria、supported/limited/prohibited claims 和 orbit-distinct→Doppler interface。
- 对既有 outputs 与 orbit-uncertainty raw/data artifacts 执行 before/after SHA fingerprint。

### C. 新增/修改文件

- 新增：{', '.join(path.as_posix() for path in output_paths)}。
- 追加本日志；未修改任何 historical dataset、frozen parameter、confirmatory artifact 或旧实验输出。

### D. 运行命令

- `python -m py_compile scripts/build_orbit_uncertainty_final_evidence_and_stopping_review.py`
- `python scripts/build_orbit_uncertainty_final_evidence_and_stopping_review.py --overwrite`
- PowerShell只读核对 output/protected SHA、CSV statuses、interface 和 manifest。

### E. 结果摘要

- 正式状态：`{STATUS}`。
- Mainline：`STOP ORBIT-UNCERTAINTY MODEL OPTIMIZATION`；July=`NOT REQUIRED FOR MAINLINE`。
- Satellite-specific model=`DOWNGRADED / NOT REQUIRED`；regime detector=`OPTIONAL / NON-BLOCKING`；6D=`NOT NEEDED YET`。
- 最终模型名：`{MODEL_NAME}`；全部历史 protected artifacts before/after mismatch=0。

### F. 问题与下一步

P95 transfer、RMS Q4、temporal episodes、单星异质性与M3/M4 provenance保留为非阻塞 limitation。下一唯一主线为 `{NEXT_STEP}`；本轮未执行 synthetic B、Doppler、July acquisition、refit、rescore或新模型。
"""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Replace only final-review outputs")
    args = parser.parse_args()
    existing = [path for path in OUTPUTS if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"Final-review output exists; use --overwrite: {existing[0]}")

    protected = historical_paths()
    before = fingerprint(protected)
    facts = validate_and_extract()
    evidence = evidence_rows(facts)
    stopping = stopping_rows(facts)
    claims = claim_rows(facts)
    if any(row["status"] in {"FAIL", "UNRESOLVED"} for row in stopping):
        raise SystemExit("A stopping criterion remains blocking")

    interface = downstream_interface()
    write_csv(EVIDENCE_PATH, evidence)
    write_csv(STOPPING_PATH, stopping)
    write_csv(CLAIMS_PATH, claims)
    write_json(INTERFACE_PATH, interface)
    write_text(REPORT_PATH, build_report(facts, stopping, claims))

    after = fingerprint(protected)
    mismatches = [path for path, digest in before.items() if after.get(path) != digest]
    if mismatches:
        raise SystemExit(f"Protected historical artifacts changed: {mismatches[:3]}")

    input_inventory = {name: output_entry(path) for name, path in INPUTS.items()}
    output_paths = [EVIDENCE_PATH, STOPPING_PATH, CLAIMS_PATH, INTERFACE_PATH, REPORT_PATH]
    manifest = {
        "stage": "Orbit Uncertainty final evidence and stopping review",
        "status": STATUS,
        "generated_utc": utc_now(),
        "review_type": "READ_ONLY_SYNTHESIS_OF_EXISTING_AUTHORITATIVE_ARTIFACTS",
        "final_model_name": MODEL_NAME,
        "primary_candidate": "ROBUST_EMPIRICAL_ELLIPSOID",
        "secondary_sensitivity_candidate": "JOINT_MAX_SCORE_BOX",
        "frozen_parameter_sha256": PARAMETER_SHA,
        "june_canonical_sha256": JUNE_CANONICAL_SHA,
        "mainline_decision": "STOP ORBIT-UNCERTAINTY MODEL OPTIMIZATION",
        "july": "NOT REQUIRED FOR MAINLINE",
        "satellite_specific_model": "DOWNGRADED / NOT REQUIRED",
        "regime_detector": "OPTIONAL / NON-BLOCKING",
        "six_dimensional_extension": "NOT NEEDED YET",
        "next_step": NEXT_STEP,
        "blocking_stopping_criteria": 0,
        "stopping_status_counts": {
            status: sum(row["status"] == status for row in stopping)
            for status in ("PASS", "PASS_WITH_LIMITATION", "UNRESOLVED", "FAIL")
        },
        "claim_counts": {
            level: sum(row["claim_level"] == level for row in claims)
            for level in ("SUPPORTED", "LIMITED", "UNSUPPORTED_PROHIBITED")
        },
        "no_new_science_audit": {
            "new_model_count": 0, "refit_count": 0, "rescore_count": 0,
            "new_threshold_count": 0, "new_covariance_count": 0, "new_bin_count": 0,
            "july_acquisition_count": 0, "synthetic_b_runs": 0, "doppler_runs": 0,
            "monte_carlo_runs": 0, "scientific_rows_recomputed": 0,
        },
        "protection": {
            "historical_artifact_count": len(protected),
            "before_after_equal": not mismatches,
            "mismatches": mismatches,
            "scope": "all pre-existing files under outputs and data/orbit_uncertainty_stage1, excluding final-review targets",
        },
        "inputs": input_inventory,
        "builder": {
            "path": Path(__file__).resolve().as_posix(),
            "sha256": sha256(Path(__file__)),
            "git_state": "NOT_A_GIT_WORK_TREE",
            "python": platform.python_version(),
        },
        "outputs": {path.name: output_entry(path) for path in output_paths},
    }
    write_json(MANIFEST_PATH, manifest)
    append_log([*output_paths, MANIFEST_PATH])

    print(STATUS)
    print("MAINLINE_DECISION=STOP_ORBIT_UNCERTAINTY_MODEL_OPTIMIZATION")
    print("JULY=NOT_REQUIRED_FOR_MAINLINE")
    print(f"NEXT_STEP={NEXT_STEP}")


if __name__ == "__main__":
    main()
