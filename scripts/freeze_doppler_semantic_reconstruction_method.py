#!/usr/bin/env python3
"""Freeze the causal-A-aligned Doppler semantic reconstruction method.

This is a read-only dependency and protocol audit. It does not propagate an
orbit, generate a candidate, build a Doppler curve, or execute a verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

FROZEN_PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
FROZEN_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
ORBIT_INTERFACE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
COMPATIBILITY = METRICS / "orbit_distinct_existing_doppler_artifact_compatibility.csv"
RELABEL_REPORT = REPORTS / "existing_doppler_case_orbit_distinct_relabeling_report.md"
RELABEL_MANIFEST = METRICS / "orbit_distinct_relabel_manifest.json"
RELABEL_READINESS = METRICS / "orbit_distinct_relabel_family_readiness.csv"
RELABEL_STATE_AUDIT = METRICS / "orbit_distinct_ab_state_reconstruction_audit.csv"
ALTITUDE_MANIFEST = METRICS / "controlled_altitude_difference_manifest.json"

CODE_INPUTS = [
    ROOT / "scripts" / "run_doppler_verifier_initial_experiments.py",
    ROOT / "scripts" / "run_active_compensation_attack_first_pass.py",
    ROOT / "scripts" / "run_segmented_service_center_compensation.py",
    ROOT / "scripts" / "run_segment_local_expanded_sample_confirmation.py",
    ROOT / "scripts" / "run_same_pair_multi_pass_confirmation.py",
    ROOT / "scripts" / "run_controlled_altitude_difference_risk_experiment.py",
]
AUTHORITATIVE_INPUTS = [
    FROZEN_PARAMETERS, ORBIT_INTERFACE, COMPATIBILITY, RELABEL_REPORT,
    RELABEL_MANIFEST, RELABEL_READINESS, RELABEL_STATE_AUDIT,
    ALTITUDE_MANIFEST, *CODE_INPUTS,
]

REPORT_OUTPUT = REPORTS / "doppler_semantic_reconstruction_method_decision.md"
FAMILY_OUTPUT = METRICS / "doppler_semantic_reconstruction_family_matrix.csv"
DEPENDENCY_OUTPUT = METRICS / "doppler_semantic_reconstruction_dependency_audit.csv"
PROTOCOL_OUTPUT = METRICS / "doppler_semantic_reconstruction_protocol.json"
MANIFEST_OUTPUT = METRICS / "doppler_semantic_reconstruction_manifest.json"
OUTPUTS = [REPORT_OUTPUT, FAMILY_OUTPUT, DEPENDENCY_OUTPUT, PROTOCOL_OUTPUT, MANIFEST_OUTPUT]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def validate_inputs(overwrite: bool) -> tuple[dict[str, str], dict[str, Any], pd.DataFrame]:
    missing = [rel(path) for path in AUTHORITATIVE_INPUTS if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Output exists; use --overwrite: " + ", ".join(existing))
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen orbit-uncertainty parameter SHA mismatch")
    interface = json.loads(ORBIT_INTERFACE.read_text(encoding="utf-8"))
    if interface.get("frozen_parameter_sha256") != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen bridge interface parameter binding mismatch")
    relabel = json.loads(RELABEL_MANIFEST.read_text(encoding="utf-8"))
    expected = {
        "status": "EXISTING_DOPPLER_RELABEL_BLOCKED_BY_A_SEMANTICS",
        "unique_pair_segment_orbit_units": 885,
        "causal_A_recovered": 885,
        "A_semantic_compatible": 64,
        "B_state_recoverable": 885,
        "within_support": 885,
        "formally_scored": 64,
    }
    observed = {"status": relabel.get("status"), **relabel.get("counts", {})}
    mismatch = {key: (observed.get(key), value) for key, value in expected.items() if observed.get(key) != value}
    if mismatch:
        raise SystemExit(f"Relabel authoritative fact mismatch: {mismatch}")
    readiness = pd.read_csv(RELABEL_READINESS)
    return {rel(path): sha256(path) for path in AUTHORITATIVE_INPUTS}, relabel, readiness


def dependency_matrix() -> pd.DataFrame:
    rows = [
        ("evaluation_time_and_t_rel_grid", "saved segment bounds/time grid", "A_INDEPENDENT", False, False, False, "REUSE_EXACT", "The segment/time convention is frozen and is not inferred from a new orbit."),
        ("selected_A_GP_and_state", "causal selector and propagation", "A_DEPENDENT", True, False, False, "RECOMPUTE", "Must select CREATION_DATE<=t and use the same A state everywhere."),
        ("fixed_controlled_station_S", "configured station coordinates", "A_INDEPENDENT", False, False, False, "REUSE_EXACT", "A fixed station is an experiment input."),
        ("A_relative_service_center_C", "A subpoint/segment-center track", "A_DEPENDENT", True, False, False, "RECOMPUTE_WHEN_USED", "C is generated from A in segment-local and subpoint compensation families."),
        ("A_relative_receiver_S", "destination(C,distance,direction)", "A_DEPENDENT", True, False, False, "RECOMPUTE_WHEN_USED", "Preserve distance/direction factors, not legacy cached coordinates."),
        ("F_A_S_t", "geometric Doppler of A at verifier receiver", "A_DEPENDENT", True, False, False, "RECOMPUTE", "This is the claimed Doppler curve."),
        ("F_A_C_t", "geometric Doppler of A at compensation center", "A_DEPENDENT", True, False, False, "RECOMPUTE_WHEN_USED", "Required by service-center/subpoint active compensation."),
        ("F_B_S_t", "geometric Doppler of B at verifier receiver", "B_DEPENDENT", False, True, False, "RECOMPUTE_FROM_PRESERVED_B_SEMANTICS", "Changes for A-relative synthetic B; real B provenance is retained."),
        ("F_B_C_t", "geometric Doppler of B at compensation center", "A_DEPENDENT+B_DEPENDENT", True, True, False, "RECOMPUTE_WHEN_USED", "C can change with A even when real B is fixed."),
        ("u_C_t", "F_A(C,t)-F_B(C,t)", "A_DEPENDENT+B_DEPENDENT", True, True, False, "RECOMPUTE", "Active compensation cannot reuse the legacy curve after A changes."),
        ("b_env", "saved draw or deterministic seed replay", "OBSERVATION_RANDOMNESS_DEPENDENT", False, False, True, "REUSE_DRAW", "The effective bias draw is held fixed across semantic reconstruction."),
        ("k_env", "saved draw or deterministic seed replay", "OBSERVATION_RANDOMNESS_DEPENDENT", False, False, True, "REUSE_DRAW", "The slow-drift draw is held fixed."),
        ("sigma_and_noise_vector", "saved draw/hash or deterministic seed replay", "OBSERVATION_RANDOMNESS_DEPENDENT", False, False, True, "REUSE_DRAW", "Do not silently sample new noise."),
        ("passive_observation_y", "F_B(S,t)+b+k(t-t0)+noise", "B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", False, True, True, "REBUILD_IF_B_CHANGES_ELSE_REUSE_VECTOR", "Real-B passive y can be reused only if its full saved vector is bound."),
        ("active_observation_y", "F_B(S,t)+u_C(t)+b+k(t-t0)+noise", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "RECOMPUTE", "Both compensation and possibly B geometry change."),
        ("claimed_Doppler_curve", "F_A(S,t)", "A_DEPENDENT", True, False, False, "RECOMPUTE", "The verifier reference must be causal-A aligned."),
        ("raw_residual", "y(t)-F_A(S,t)", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "RECOMPUTE", "No aggregate old-to-new transform exists."),
        ("OLS_b_hat", "intercept of raw residual", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "REFIT_SAME_OLS", "Must fit the unchanged OLS to the reconstructed residual."),
        ("OLS_k_hat", "slope of raw residual", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "REFIT_SAME_OLS", "Must fit the unchanged OLS to the reconstructed residual."),
        ("residual_score", "RMSE after unchanged b+k projection", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "RECOMPUTE", "The score is nonlinear in the changed residual after projection."),
        ("score_threshold", "existing legitimate calibration threshold", "A_INDEPENDENT", False, False, True, "REUSE_FROZEN", "With the same time grid and residual distribution, F_A cancels in legitimate calibration."),
        ("b_k_gate_limits", "current b/k frozen ranges or calibrated limits", "A_INDEPENDENT", False, False, True, "REUSE_FROZEN", "Gate limits are scientifically frozen; only fitted values change."),
        ("coverage_and_visibility", "A/B/site geometry over segment", "A_DEPENDENT+B_DEPENDENT", True, True, False, "RECOMPUTE", "Derived C/S coordinates and both orbit states can change visibility."),
        ("score_b_k_coverage_gate_results", "threshold comparisons", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "RECOMPUTE", "Inputs to every gate may change even though limits do not."),
        ("ACCEPT_REJECT_DEFER", "unchanged verifier decision rule", "A_DEPENDENT+B_DEPENDENT+OBSERVATION_RANDOMNESS_DEPENDENT", True, True, True, "RECOMPUTE", "Final decision cannot be inherited for A-mismatched units."),
        ("orbit_D2_rho99_decision", "frozen public-RTN ellipsoid", "A_DEPENDENT+B_DEPENDENT", True, True, False, "RECOMPUTE_WITH_FROZEN_PARAMETERS", "Computed once at segment center; no uncertainty refit."),
    ]
    columns = [
        "quantity", "formula_or_source", "dependency_class", "A_dependent",
        "B_dependent", "observation_randomness_dependent", "reconstruction_policy", "reason",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    frame["old_aggregate_deterministic_transform_allowed"] = False
    frame.loc[frame.reconstruction_policy.isin(["REUSE_EXACT", "REUSE_DRAW", "REUSE_FROZEN"]), "old_aggregate_deterministic_transform_allowed"] = True
    return frame


def family_matrix(readiness: pd.DataFrame) -> pd.DataFrame:
    readiness_by_family = readiness.set_index("experiment_family").to_dict("index")
    definitions = [
        {
            "family": "score_only_verifier_and_synthetic_orbit_attacks",
            "scientific_purpose": "Legacy full-pass score-only baseline and altitude/phase synthetic attack history",
            "A_semantics": "static TLE claimed A",
            "B_class": "SYNTHETIC_RELATIVE_TO_A",
            "B_policy": "For any future reconstruction use Perturb(A_causal, frozen altitude/phase rule); do not retain B_old absolute state",
            "randomness_reproducible": "YES_SAVED_DRAWS_AND_SEED",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH; NO_FOR_64_SET_MATCHED_UNITS",
            "priority_for_final_mainline": "KEEP_HISTORICAL_ONLY",
            "scope_decision": "Use only as R1 implementation reproduction and historical baseline; superseded by current segment-local verifier",
        },
        {
            "family": "verifier_v2_gate_ablation",
            "scientific_purpose": "Derived score/b/k gate view over the initial attack observations",
            "A_semantics": "inherits initial static TLE A",
            "B_class": "INHERITED_SYNTHETIC_RELATIVE_TO_A",
            "B_policy": "No independent B reconstruction; inherit the causal-A reconstructed initial-family observation",
            "randomness_reproducible": "YES_INHERITED",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH; NO_FOR_MATCHED_READ_ONLY_VIEW",
            "priority_for_final_mainline": "KEEP_HISTORICAL_ONLY",
            "scope_decision": "Do not count as a separate experiment family or geometry unit",
        },
        {
            "family": "controlled_multitarget_legitimate_baseline",
            "scientific_purpose": "Legitimate A-only calibration/baseline",
            "A_semantics": "static TLE A-only",
            "B_class": "NOT_APPLICABLE",
            "B_policy": "Do not manufacture candidate B",
            "randomness_reproducible": "YES_BUT_PAIR_GATE_NOT_APPLICABLE",
            "verifier_rerun_required": "NO_FOR_JOINT_MAINLINE",
            "priority_for_final_mainline": "DROP_FROM_FINAL_MAINLINE",
            "scope_decision": "Retain as historical legitimate baseline only",
        },
        {
            "family": "active_compensation_first_pass",
            "scientific_purpose": "Test none/subpoint/direct active compensation against claimed identity",
            "A_semantics": "static TLE A; F_A enters claimed curve, subpoint C, and u_C",
            "B_class": "REAL_B",
            "B_policy": "Keep original real B identity/TLE physical state; recompute C, F_A, F_B and compensation with causal A",
            "randomness_reproducible": "YES_SAVED_TIMESERIES_DRAWS_AND_SEED",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH",
            "priority_for_final_mainline": "RECONSTRUCT_CORE",
            "scope_decision": "Current attack-model core; use current b/k primary and minimize target/pair/compensation strata",
        },
        {
            "family": "fixed_point_active_compensation_summary",
            "scientific_purpose": "Legacy fixed-point/window summary diagnostic",
            "A_semantics": "legacy A with relative summaries",
            "B_class": "SYNTHETIC_RELATIVE_TO_A",
            "B_policy": "Summary rows are insufficient; any upstream reconstruction would require causal-A-relative B semantics and is redundant with retained core families",
            "randomness_reproducible": "NO_FROM_SUMMARY_ALONE",
            "verifier_rerun_required": "NOT_SELECTED",
            "priority_for_final_mainline": "DROP_FROM_FINAL_MAINLINE",
            "scope_decision": "Stop maintaining as a formal joint-security family",
        },
        {
            "family": "segment_local_heatmap_and_direction_sensitivity",
            "scientific_purpose": "Segment-local real-B and controlled relative-synthetic direction/geometry evidence",
            "A_semantics": "static TLE A defines claimed curve and A-relative C/S geometry",
            "B_class": "MIXED_REAL_B_AND_SYNTHETIC_RELATIVE_TO_A",
            "B_policy": "Keep real B physical orbit; rebuild synthetic B and A-relative C/S from causal A with frozen factors",
            "randomness_reproducible": "YES_WITH_BOUND_MASTER_SEED_AND_SAVED_LEGACY_DRAWS; FREEZE_EXPLICIT_DRAW_MAP_BEFORE_R2",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH",
            "priority_for_final_mainline": "RECONSTRUCT_CORE",
            "scope_decision": "Reconstruct a reduced current_bk subset; do not rerun all 89,280 legacy rows",
        },
        {
            "family": "same_pair_multi_pass_real_TLE",
            "scientific_purpose": "Real-B pair x pass repeatability under the same candidate provenance",
            "A_semantics": "static TLE A",
            "B_class": "REAL_B",
            "B_policy": "Keep original B identity/TLE state at each frozen segment; replace only A with causal A",
            "randomness_reproducible": "YES_EXPLICIT_ENVIRONMENT_NOISE_CALIBRATION_SEEDS_AND_HASHES",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH",
            "priority_for_final_mainline": "RECONSTRUCT_CORE",
            "scope_decision": "Core temporal-repeatability evidence; current_bk primary",
        },
        {
            "family": "historical_TLE_multi_pass_real_TLE",
            "scientific_purpose": "Exploratory different-date real-B/TLE sensitivity for two physical pairs",
            "A_semantics": "historical TLE A without publication provenance",
            "B_class": "REAL_B",
            "B_policy": "Keep historical B identity/TLE physical state; causal-select A at each segment",
            "randomness_reproducible": "YES_EXPLICIT_ENVIRONMENT_NOISE_CALIBRATION_SEEDS_AND_HASHES",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH",
            "priority_for_final_mainline": "RECONSTRUCT_SENSITIVITY",
            "scope_decision": "Do not include in pooled core claim; retain as date/TLE sensitivity",
        },
        {
            "family": "controlled_altitude_difference_synthetic_B",
            "scientific_purpose": "Physical-km altitude perturbation comparison across pass/direction conditions",
            "A_semantics": "static TLE A is the synthetic construction base and claimed curve",
            "B_class": "SYNTHETIC_RELATIVE_TO_A",
            "B_policy": "Rebuild B=Perturb(A_causal, same signed delta_h and Keplerian rule); preserve factors/seeds, not B_old state",
            "randomness_reproducible": "YES_EXPLICIT_ENVIRONMENT_NOISE_CALIBRATION_SEEDS_AND_HASHES",
            "verifier_rerun_required": "YES_FOR_A_MISMATCH",
            "priority_for_final_mainline": "RECONSTRUCT_CORE",
            "scope_decision": "Use current_bk primary; no_bk/wide_bk sensitivity; delta_h=0 remains reference only",
        },
        {
            "family": "differential_doppler_mechanism_representatives",
            "scientific_purpose": "Derived explanatory representative traces",
            "A_semantics": "inherited legacy pair-instance A",
            "B_class": "DERIVED_MIXED_PROVENANCE",
            "B_policy": "Do not infer states from relative-time summary; regenerate diagnostics only from selected core outputs if later needed",
            "randomness_reproducible": "NO_FROM_REPRESENTATIVE_ARTIFACT_ALONE",
            "verifier_rerun_required": "NOT_SELECTED",
            "priority_for_final_mainline": "DROP_FROM_FINAL_MAINLINE",
            "scope_decision": "Stop maintaining as an independent formal family",
        },
    ]
    records: list[dict[str, Any]] = []
    for item in definitions:
        fact = readiness_by_family.get(item["family"], {})
        records.append({
            **item,
            "A_reconstruction_possible": "YES" if int(fact.get("A_causal_GP_recoverable", 0)) > 0 else "NOT_APPLICABLE_OR_UPSTREAM_REQUIRED",
            "B_semantic_reconstruction_possible": (
                "YES" if int(fact.get("B_state_recoverable", 0)) > 0
                else "NO_FROM_THIS_ARTIFACT_ALONE" if item["family"] in {"fixed_point_active_compensation_summary", "differential_doppler_mechanism_representatives"}
                else "NOT_APPLICABLE"
            ),
            "legacy_orbit_units": int(fact.get("unique_pair_segment_orbit_units", 0)),
            "A_semantics_compatible_units": int(fact.get("A_verifier_semantic_compatible", 0)),
            "legacy_relabel_status": str(fact.get("status", "NOT_IN_RELABEL_INVENTORY")),
        })
    return pd.DataFrame(records)


def build_protocol(relabel: dict[str, Any], family: pd.DataFrame, dependency: pd.DataFrame) -> dict[str, Any]:
    primary_rows = {
        "initial_score_only": 300,
        "active_compensation": 60,
        "same_pair_multi_pass": 720,
        "controlled_altitude": 5400,
    }
    return {
        "protocol_name": "CAUSAL_A_ALIGNED_DOPPLER_RECONSTRUCTION_V1",
        "status": "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN",
        "stage": "R0_METHOD_DECISION_ONLY",
        "scientific_execution_performed": False,
        "legacy_direct_relabel": "NOT_SUFFICIENT",
        "core_strategy": "CAUSAL-A-ALIGNED DOPPLER RECONSTRUCTION",
        "old_verifier_output": "REUSE ONLY WHEN A SEMANTICS MATCH",
        "semantic_invariant": "The identical causally selected A public prediction must drive orbit scoring, claimed-A Doppler, active compensation when applicable, and verifier residuals.",
        "frozen_orbit_interface": {
            "model": "Freshness-Conditioned Robust Empirical RTN Ellipsoid",
            "parameter_sha256": FROZEN_PARAMETER_SHA,
            "application_rtn": "PUBLIC_DEFINED_RTN",
            "score_vector": "z_B=RTN_public(x_A_public-x_B)",
            "support": "0<element_age_hours<=36",
            "outside_support": "DEFER",
            "modified": False,
        },
        "analysis_units": {
            "orbit": "A x B x segment/time",
            "joint": "A x B x segment/time x observation_realization",
            "orbit_evaluation_time": "SEGMENT_CENTER",
            "doppler_evaluation": "FULL_SAVED_SEGMENT_TIMESERIES",
        },
        "B_semantic_policy": {
            "REAL_B": "Preserve original real-B identity and historical physical orbit state at the frozen evaluation segment.",
            "SYNTHETIC_RELATIVE_TO_A": "Rebuild B_new=Perturb(A_causal,delta) with the identical perturbation rule, factor values, direction and seeds; do not preserve B_old absolute state.",
            "SYNTHETIC_ABSOLUTE_STATE": "Preserve absolute B only where the authoritative experiment definition explicitly freezes B independently of A; no selected core family currently relies on this class.",
        },
        "deterministic_transform_decision": "FULL_DOPPLER_RECOMPUTATION_REQUIRED_FOR_A_SEMANTICS_MISMATCH",
        "deterministic_transform_reason": "Aggregate score, b_hat, k_hat and residual do not retain the time-varying claimed-curve difference; active compensation and A-relative B additionally change the observation itself.",
        "scientifically_frozen": [
            "verifier algorithm", "score threshold", "current b/k limits", "observation parameter distribution",
            "compensation formula", "segment-local/fixed-site-segment-center/single-window convention",
        ],
        "legacy_replaced": ["old A TLE/state", "legacy A-dependent cached Doppler geometry", "legacy A-relative C/S coordinates"],
        "randomness_policy": {
            "priority": ["reuse exact saved observation draws", "replay explicit per-realization seeds and verify hashes", "freeze an explicit draw map before R2"],
            "new_sampling_allowed": False,
            "missing_draw_action": "RANDOMNESS_RECONSTRUCTION_REQUIRED",
        },
        "core_families": family.loc[family.priority_for_final_mainline.eq("RECONSTRUCT_CORE"), "family"].tolist(),
        "sensitivity_families": family.loc[family.priority_for_final_mainline.eq("RECONSTRUCT_SENSITIVITY"), "family"].tolist(),
        "historical_only_families": family.loc[family.priority_for_final_mainline.eq("KEEP_HISTORICAL_ONLY"), "family"].tolist(),
        "dropped_mainline_families": family.loc[family.priority_for_final_mainline.eq("DROP_FROM_FINAL_MAINLINE"), "family"].tolist(),
        "mode_policy": {"primary": "current_bk", "sensitivity": ["no_bk", "wide_bk"]},
        "minimum_core_questions": [
            "Whether any ORBIT_DISTINCT B remains Doppler accepted",
            "Dependence on orbit displacement/geometry direction",
            "Dependence on rho99 while retaining physical distance",
            "Whether multipass evidence reduces orbit-distinct yet Doppler-accepted cases",
            "Impact of active compensation",
            "Impact of the frozen current b/k gate",
        ],
        "R1_reproduction_gate": {
            "orbit_unit_count": int(relabel["counts"]["A_semantic_compatible"]),
            "primary_source_rows_bound_to_units": sum(primary_rows.values()),
            "primary_source_row_breakdown": primary_rows,
            "derived_verifier_v2_view_rows": 200,
            "required_scope": "all 64 compatible orbit units and all bound primary source realization/mode rows; V2 view is a duplicate cross-check",
            "tolerances": {
                "evaluation_time_and_time_grid": "exact string/value equality; t_rel absolute error <=1e-12 s",
                "selected_A_GP_ID_and_TLE": "exact equality",
                "A_position": "max vector norm error <=1e-6 km",
                "A_velocity": "max vector norm error <=1e-9 km/s",
                "B_position": "max vector norm error <=1e-6 km",
                "B_velocity": "max vector norm error <=1e-9 km/s",
                "Doppler_geometry_curves": "max absolute error <=1e-6 Hz",
                "active_compensation_curve": "max absolute error <=1e-6 Hz when applicable",
                "observation_and_raw_residual": "max absolute error <=1e-6 Hz",
                "b_hat_and_score": "absolute error <=1e-6 Hz",
                "k_hat": "absolute error <=1e-9 Hz/s",
                "gate_booleans_and_final_decision": "exact equality; zero mismatches",
                "saved_random_seeds_and_vector_hashes": "exact equality where available",
            },
            "pass_rule": "ALL checks must pass; this is an implementation equivalence gate, not a statistical acceptance rate.",
        },
        "minimum_reconstruction_policy": {
            "rerun_all_158520_rows": False,
            "selection_rules": [
                "directly answers a final joint-security question", "A/B semantics are fully reconstructable",
                "randomness is exactly replayable", "current_bk primary rows are retained",
                "redundant derived views and legacy summaries are excluded", "rho99 transition coverage is audited after R2",
            ],
            "boundary_expansion": "R4 only, and only if reconstructed existing perturbation grids do not cover the rho99 transition region",
        },
        "joint_states": [
            "DEFER", "NOT_ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED", "NOT_ORBIT_DISTINCT_AND_DOPPLER_REJECTED",
            "AMBIGUOUS_AND_DOPPLER_ACCEPTED", "AMBIGUOUS_AND_DOPPLER_REJECTED",
            "ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED", "ORBIT_DISTINCT_AND_DOPPLER_REJECTED",
        ],
        "terminology_guard": "ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED is a security-relevant case, not an attack success rate.",
        "stages": [
            "R0 method decision (this artifact)", "R1 64-compatible-unit reproduction validation",
            "R2 reduced core-family causal-A reconstruction", "R3 joint orbit-distinct plus Doppler analysis",
            "R4 optional targeted rho99-boundary expansion only if required",
        ],
        "output_namespace": {
            "datasets": "outputs/datasets/doppler_causal_a_reconstruction_*",
            "metrics": "outputs/metrics/doppler_causal_a_reconstruction_*",
            "legacy_outputs_mutable": False,
        },
        "next_step": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION",
        "dependency_row_count": len(dependency),
    }


def build_report(family: pd.DataFrame, dependency: pd.DataFrame, protocol: dict[str, Any]) -> str:
    recompute = dependency.loc[dependency.reconstruction_policy.str.contains("RECOMPUTE|REFIT|REBUILD", regex=True), "quantity"].tolist()
    return f"""# Doppler semantic reconstruction method decision

## 1. Decision

本轮冻结 `CAUSAL_A_ALIGNED_DOPPLER_RECONSTRUCTION_V1`。旧 verifier aggregate outputs 不能从 `A_old` 严格代数转换为 `A_causal` 结果。对 A semantics mismatch units，正式结论是 `FULL_DOPPLER_RECOMPUTATION_REQUIRED`；这表示复用原 case、factor、draw、threshold 和 verifier，仅重建依赖 A 的几何与下游量，不是重新设计实验。

`LEGACY_DIRECT_RELABEL = NOT_SUFFICIENT`。

## 2. Dependency audit

{dependency.to_markdown(index=False)}

必须重新计算或按 B 语义重建的主要量为：`{recompute}`。`score threshold` 与 frozen `current b/k` limits 保持不变；变化的是 fitted values、gate outcomes 和最终 decision。

不存在从旧 `score/b_hat/k_hat/residual` aggregate 到 causal-A result 的严格 deterministic transform。被动 REAL_B 若保存了完整 observation vector，可以复用该 vector，但仍必须针对新 `F_A(S,t)` 执行同一 OLS/verifier；A-relative synthetic B 与 active compensation 还必须重建 observation curve。

## 3. B semantics

- `REAL_B`：保持原真实 B identity、原 historical/static orbit provenance 和同一 segment 的 physical state，不人工 perturb，也不要求 B 遵循 A 的 causal-publication policy。
- `SYNTHETIC_RELATIVE_TO_A`：必须执行 `B_new=Perturb(A_causal,delta)`；保留 delta、direction、orbital rule 和 randomness，不保留 `B_old` absolute state。
- `SYNTHETIC_ABSOLUTE_STATE`：只有 authoritative definition 明确与 A 无关时才保留 absolute B；当前选定 core family 没有依赖这一类别。

## 4. Family method matrix

{family.to_markdown(index=False)}

### Core reconstruction

{protocol['core_families']}

### Sensitivity only

{protocol['sensitivity_families']}

### Historical only / stopped mainline maintenance

历史保留：{protocol['historical_only_families']}。

停止作为 final mainline family 维护：{protocol['dropped_mainline_families']}。

不重跑全部 158,520 rows。segment-local 只冻结 reduced `current_bk` subset；`no_bk/wide_bk` 只作 sensitivity。verifier v2 view 不重复计算 geometry units。

## 5. Minimum sufficient formal set

最小 core 由四类科学证据组成：

1. Segment-local real-B + A-relative synthetic geometry/direction subset，用于 real/synthetic 对照、方向与 rho99。
2. Controlled signed-altitude perturbation，用于保留 km 物理对照。
3. Same-pair real-B multipass，用于时间重复性。
4. Active-compensation real-B family，用于最终攻击假设。

Historical-TLE multipass 只作不同日期/TLE sensitivity。只有 R2 后 existing frozen perturbation grid 明显缺失 rho99≈1 coverage，才允许 R4 最小 boundary expansion。

## 6. R1 reproduction gate

64 个 A-semantics-compatible units 足以作为 implementation reproduction set，因为它们覆盖 initial synthetic、active compensation、same-pair multipass 和 controlled altitude 四类路径，并已有 30-case orbit bridge end-to-end audit。R1 必须验证全部 64 units 及其绑定的 6,480 条非重复 primary source realization/mode rows；200 条 verifier-v2 derived rows只作交叉检查。

冻结 correctness thresholds：

{pd.DataFrame([{'quantity': key, 'threshold': value} for key, value in protocol['R1_reproduction_gate']['tolerances'].items()]).to_markdown(index=False)}

所有 checks 必须通过，decision mismatch 必须为 0。无法恢复 randomness 时不得新采样，状态为 `RANDOMNESS_RECONSTRUCTION_REQUIRED`。

## 7. Segment and joint-row protocol

Orbit label 在 frozen segment center 计算一次；Doppler verifier 继续使用整个 segment timeseries。每条正式 joint row 绑定 causal A GP_ID/freshness、B semantic definition、D2/rho99/orbit decision、score/b_hat/k_hat/verifier decision。`rho99` 与 physical displacement 同时报告，rho99 不是 probability。

安全主关注为 `ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED`，不得称为 attack success rate。

## 8. Answers to the method questions

1. Aggregate old verifier outputs不能 deterministic transform；semantics-compatible cases可直接复用，mismatch cases必须执行 unchanged verifier recomputation。
2. 必须重建所有 A-dependent curves、A-relative C/S/B、active compensation、residual、OLS、score、gates 和 decision。
3. REAL_B 保持原 identity 与 physical orbit state。
4. SYNTHETIC_RELATIVE_TO_A 必须围绕 causal A 重新构造。
5. Core：segment-local、controlled altitude、same-pair real-B multipass、active compensation。
6. Historical-TLE multipass 和 no_bk/wide_bk 只作 sensitivity。
7. Fixed-point summary、differential representatives、A-only pair-inapplicable baseline停止 mainline 维护；initial/V2只保留历史与R1。
8. 64 compatible units足以作为 implementation reproduction set，但不能替代R2 scientific reconstruction。
9. R1 使用上表 floating tolerances、exact seed/hash和zero decision mismatch。
10. 不需要重跑全部158,520 rows。
11. 最小充分集合是四个 core families，不重复 derived views。
12. 下一步是 `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION`。

## 9. Formal status

`DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN`

`LEGACY_DIRECT_RELABEL: NOT SUFFICIENT`

`CORE STRATEGY: CAUSAL-A-ALIGNED DOPPLER RECONSTRUCTION`

`OLD VERIFIER OUTPUT: REUSE ONLY WHEN A SEMANTICS MATCH`

`NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION`
"""


def build_manifest(
    before: dict[str, str], family: pd.DataFrame, dependency: pd.DataFrame,
    protocol: dict[str, Any], generated: datetime,
) -> dict[str, Any]:
    return {
        "stage": "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_DECISION",
        "status": "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN",
        "generated_utc": iso_z(generated),
        "action_type": "READ_ONLY_DEPENDENCY_AUDIT_AND_PROTOCOL_FREEZE_NO_SCIENTIFIC_EXECUTION",
        "legacy_direct_relabel": "NOT_SUFFICIENT",
        "core_strategy": "CAUSAL-A-ALIGNED DOPPLER RECONSTRUCTION",
        "old_verifier_output": "REUSE ONLY WHEN A SEMANTICS MATCH",
        "full_doppler_recomputation_for_A_mismatch": True,
        "rerun_all_158520_rows": False,
        "R1_compatible_orbit_units": 64,
        "R1_primary_source_rows": 6480,
        "family_status_counts": family.priority_for_final_mainline.value_counts().to_dict(),
        "dependency_rows": len(dependency),
        "frozen_parameter_sha256": sha256(FROZEN_PARAMETERS),
        "fitted_parameter_count": 0,
        "verifier_execution_count": 0,
        "orbit_propagation_count": 0,
        "candidate_generation_count": 0,
        "authoritative_inputs": [
            {"path": path, "sha256": digest, "size_bytes": (ROOT / path).stat().st_size}
            for path, digest in before.items()
        ],
        "generator": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "outputs": [
            {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in [REPORT_OUTPUT, FAMILY_OUTPUT, DEPENDENCY_OUTPUT, PROTOCOL_OUTPUT]
        ],
        "protected_input_changes": [],
        "next_step": protocol["next_step"],
        "software": {"python": platform.python_version(), "pandas": pd.__version__},
    }


def append_log() -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    entry = f"""

## {now} - Doppler semantic reconstruction method decision (R0)

### A. 本轮目标
冻结 causal-A-aligned Doppler reconstruction protocol，审计 claimed-A dependencies、B provenance、randomness replay 和最小 formal family set。

### B. 实际操作
只读检查 frozen orbit interface、existing relabel audit、family outputs/manifests 与 production verifier code；生成 dependency/family matrices、protocol、report 和 manifest。未传播轨道、未生成 B、未重算 Doppler/residual/score/decision、未运行 verifier。

### C. 新增/修改文件
新增 `freeze_doppler_semantic_reconstruction_method.py`、method report、family matrix、dependency audit、protocol JSON、manifest及测试；仅追加本日志。

### D. 运行命令
`python scripts/freeze_doppler_semantic_reconstruction_method.py`
`python -m pytest tests/test_doppler_semantic_reconstruction_method.py -q`

### E. 结果摘要
状态=`DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN`；legacy direct relabel不充分；A mismatch必须重算unchanged verifier；不重跑全部158,520 rows；core为segment-local、controlled altitude、same-pair multipass、active compensation。64 compatible units冻结为R1 reproduction set。

### F. 问题与下一步
segment-local randomness在R2前需冻结explicit draw map；R1所有state/curve/fit/gate/decision equivalence checks必须全通过。下一步=`CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION`，本轮未自动进入。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def run(args: argparse.Namespace) -> None:
    before, relabel, readiness = validate_inputs(args.overwrite)
    dependency = dependency_matrix()
    family = family_matrix(readiness)
    protocol = build_protocol(relabel, family, dependency)
    report = build_report(family, dependency, protocol)

    write_csv(DEPENDENCY_OUTPUT, dependency)
    write_csv(FAMILY_OUTPUT, family)
    write_text(PROTOCOL_OUTPUT, json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    write_text(REPORT_OUTPUT, report)

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        raise SystemExit("Protected authoritative input changed: " + ", ".join(changed))
    manifest = build_manifest(before, family, dependency, protocol, datetime.now(timezone.utc))
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    append_log()
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA changed after method freeze")
    print("DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN")
    print("LEGACY_DIRECT_RELABEL: NOT SUFFICIENT")
    print("CORE STRATEGY: CAUSAL-A-ALIGNED DOPPLER RECONSTRUCTION")
    print("OLD VERIFIER OUTPUT: REUSE ONLY WHEN A SEMANTICS MATCH")
    print("NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION")


if __name__ == "__main__":
    run(parse_args())
