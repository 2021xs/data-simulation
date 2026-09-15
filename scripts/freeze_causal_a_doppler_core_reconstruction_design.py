#!/usr/bin/env python3
"""Freeze the result-blind R2 causal-A Doppler core reconstruction design."""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"
DATASETS = ROOT / "outputs" / "datasets"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

R0_REPORT = REPORTS / "doppler_semantic_reconstruction_method_decision.md"
R0_PROTOCOL = METRICS / "doppler_semantic_reconstruction_protocol.json"
R0_MANIFEST = METRICS / "doppler_semantic_reconstruction_manifest.json"
R0_FAMILY = METRICS / "doppler_semantic_reconstruction_family_matrix.csv"
R0_DEPENDENCY = METRICS / "doppler_semantic_reconstruction_dependency_audit.csv"
POP_ERRATUM = METRICS / "doppler_semantic_reconstruction_r0_population_erratum_manifest.json"
R1_MANIFEST = METRICS / "causal_a_doppler_r1_final_manifest.json"
R1_REPORT = REPORTS / "causal_a_doppler_reconstruction_reproduction_validation_final_rerun_report.md"
R1_TOLERANCES = METRICS / "causal_a_doppler_r1_effective_reproduction_tolerances.json"
BRIDGE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
BRIDGE_MANIFEST = METRICS / "orbit_distinct_bridge_interface_manifest.json"
RELABEL = DATASETS / "existing_doppler_cases_orbit_distinct_relabeling.csv"
RELABEL_MANIFEST = METRICS / "orbit_distinct_relabel_manifest.json"
COMPATIBILITY = METRICS / "orbit_distinct_existing_doppler_artifact_compatibility.csv"
FROZEN_PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
RAW_GP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "spacetrack_gp" / "spacetrack_gp_history_20260226_20260329_20sat_omm.json"
TLE = ROOT / "data" / "tle" / "starlink_tle.txt"
ORBIT_CONFIG = ROOT / "configs" / "orbit_simulation_cases.yaml"
PARAMETER_CONFIG = ROOT / "configs" / "simulation_parameter_config.yaml"

SEGMENT = DATASETS / "m2_segment_local_expanded_sample_dataset.csv"
SEGMENT_SCRIPT = ROOT / "scripts" / "run_segment_local_expanded_sample_confirmation.py"
SEGMENT_HARD_CASES = METRICS / "window_aware_attack_accept_hard_cases.csv"
SEGMENT_LEGACY = DATASETS / "original_vs_current_fixed_reference_dataset.csv"
ALTITUDE = DATASETS / "controlled_altitude_difference_realization_dataset.csv"
ALTITUDE_MANIFEST = METRICS / "controlled_altitude_difference_manifest.json"
ALTITUDE_AUDIT = METRICS / "controlled_altitude_difference_correctness_audit.csv"
ALTITUDE_SCRIPT = ROOT / "scripts" / "run_controlled_altitude_difference_risk_experiment.py"
MULTIPASS = DATASETS / "same_pair_multi_pass_realization_dataset.csv"
MULTIPASS_PAIRS = METRICS / "same_pair_multi_pass_selected_pairs.csv"
MULTIPASS_PASSES = METRICS / "same_pair_multi_pass_selected_passes.csv"
MULTIPASS_AUDIT = METRICS / "same_pair_multi_pass_correctness_audit.csv"
MULTIPASS_SCRIPT = ROOT / "scripts" / "run_same_pair_multi_pass_confirmation.py"
ACTIVE = METRICS / "active_compensation_first_pass_sequence_eval.csv"
ACTIVE_SERIES = DATASETS / "active_compensation_first_pass_dataset.csv"
ACTIVE_SCRIPT = ROOT / "scripts" / "run_active_compensation_attack_first_pass.py"
HISTORICAL = DATASETS / "historical_tle_multi_pass_realization_dataset.csv"

REPORT = REPORTS / "causal_a_doppler_core_reconstruction_design_and_freeze.md"
POPULATION = METRICS / "causal_a_doppler_r2_core_population.csv"
FAMILY_SUMMARY = METRICS / "causal_a_doppler_r2_family_summary.csv"
PROTOCOL = METRICS / "causal_a_doppler_r2_analysis_protocol.json"
RANDOMNESS = METRICS / "causal_a_doppler_r2_randomness_binding.csv"
SPOTCHECK = METRICS / "causal_a_doppler_r2_spotcheck_binding.csv"
MANIFEST = METRICS / "causal_a_doppler_r2_manifest.json"
OUTPUTS = [REPORT, POPULATION, FAMILY_SUMMARY, PROTOCOL, RANDOMNESS, SPOTCHECK, MANIFEST]

CORE_FAMILIES = [
    "segment_local_heatmap_and_direction_sensitivity",
    "controlled_altitude_difference_synthetic_B",
    "same_pair_multi_pass_real_TLE",
    "active_compensation_first_pass",
]
FROZEN_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
FORBIDDEN_SELECTION_FIELDS = {
    "orbit_D2", "orbit_rho99", "orbit_decision", "original_verifier_score",
    "original_verifier_accept", "original_verifier_decision", "security_joint_state",
    "score", "accept_flag", "final_decision",
}

AUTHORITATIVE_INPUTS = [
    R0_REPORT, R0_PROTOCOL, R0_MANIFEST, R0_FAMILY, R0_DEPENDENCY, POP_ERRATUM,
    R1_MANIFEST, R1_REPORT, R1_TOLERANCES, BRIDGE, BRIDGE_MANIFEST, RELABEL,
    RELABEL_MANIFEST, COMPATIBILITY, FROZEN_PARAMETERS, RAW_GP, TLE, ORBIT_CONFIG,
    PARAMETER_CONFIG, SEGMENT, SEGMENT_SCRIPT, SEGMENT_HARD_CASES, SEGMENT_LEGACY,
    ALTITUDE, ALTITUDE_MANIFEST, ALTITUDE_AUDIT, ALTITUDE_SCRIPT, MULTIPASS,
    MULTIPASS_PAIRS, MULTIPASS_PASSES, MULTIPASS_AUDIT, MULTIPASS_SCRIPT,
    ACTIVE, ACTIVE_SERIES, ACTIVE_SCRIPT, HISTORICAL,
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def stable_id(prefix: str, *values: Any) -> str:
    payload = "|".join([prefix, *(str(value) for value in values)])
    return prefix + "_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def validate_inputs() -> dict[str, str]:
    missing = [rel(path) for path in AUTHORITATIVE_INPUTS if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative R2 input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and MANIFEST.exists():
        raise SystemExit("R2 freeze output exists; append-only policy refuses overwrite: " + ", ".join(existing))
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Orbit-Uncertainty frozen parameter SHA changed")
    r0 = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    r1 = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    if r0.get("status") != "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN":
        raise SystemExit("R0 method is not frozen")
    if r0.get("core_families") != [
        "active_compensation_first_pass",
        "segment_local_heatmap_and_direction_sensitivity",
        "same_pair_multi_pass_real_TLE",
        "controlled_altitude_difference_synthetic_B",
    ]:
        raise SystemExit("R0 core family membership changed")
    if r1.get("status") != "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATED" or not r1.get("R2_authorized"):
        raise SystemExit("R1 does not authorize R2")
    return {rel(path): sha256(path) for path in AUTHORITATIVE_INPUTS}


def load_identity_units() -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "experiment_family", "source_view", "source_artifact", "case_id", "orbit_unit_id",
        "A_id", "A_name", "B_id_or_definition", "segment_id", "evaluation_time",
        "original_A_source", "A_reconstruction_status", "selected_A_GP_ID",
        "selected_A_GP_EPOCH", "selected_A_GP_CREATION_DATE", "B_reconstruction_status",
        "original_bk_mode",
    ]
    rows = pd.read_csv(RELABEL, usecols=columns, dtype=str, keep_default_na=False)
    rows = rows[rows["experiment_family"].isin(CORE_FAMILIES + ["historical_TLE_multi_pass_real_TLE"])].copy()
    units = rows.drop_duplicates("orbit_unit_id").copy()
    if units.groupby("experiment_family")["orbit_unit_id"].nunique().to_dict() != {
        "active_compensation_first_pass": 100,
        "controlled_altitude_difference_synthetic_B": 300,
        "historical_TLE_multi_pass_real_TLE": 8,
        "same_pair_multi_pass_real_TLE": 40,
        "segment_local_heatmap_and_direction_sensitivity": 37,
    }:
        raise SystemExit("Authoritative family unit population changed")
    if units["selected_A_GP_ID"].eq("").any():
        raise SystemExit("A causal GP provenance missing")
    if not units["B_reconstruction_status"].isin({"EXACT", "NUMERICALLY_EQUIVALENT"}).all():
        raise SystemExit("B reconstruction provenance changed")
    return rows, units


def selected_active_units(units: pd.DataFrame) -> set[str]:
    active = units[units["experiment_family"].eq("active_compensation_first_pass")].copy()
    active["selection_hash"] = active.apply(
        lambda row: hashlib.sha256(
            f"R2_ACTIVE_PAIR_V1|{row.A_id}|{row.B_id_or_definition}".encode("utf-8")
        ).hexdigest(), axis=1,
    )
    selected = active.sort_values(["A_id", "selection_hash"]).groupby("A_id", sort=True).head(3)
    if len(selected) != 30 or selected["A_id"].nunique() != 10:
        raise SystemExit("Active result-blind pair thinning failed")
    return set(selected["orbit_unit_id"])


def build_population(rows: pd.DataFrame, units: pd.DataFrame, active_selected: set[str]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for unit in units[units["experiment_family"].isin(CORE_FAMILIES)].itertuples(index=False):
        family = str(unit.experiment_family)
        b_text = str(unit.B_id_or_definition)
        if family in {"active_compensation_first_pass", "same_pair_multi_pass_real_TLE"}:
            b_class = "REAL_B"
        elif family == "controlled_altitude_difference_synthetic_B":
            b_class = "SYNTHETIC_RELATIVE_TO_A"
        else:
            b_class = "SYNTHETIC_RELATIVE_TO_A" if "synthetic" in b_text.lower() else "REAL_B"
        include = family != "active_compensation_first_pass" or unit.orbit_unit_id in active_selected
        records.append({
            "experiment_family": family,
            "orbit_unit_id": unit.orbit_unit_id,
            "A_id": unit.A_id, "A_name": unit.A_name,
            "B_class": b_class, "B_identity_or_perturbation_definition": b_text,
            "segment_or_pass_id": unit.segment_id, "evaluation_time": unit.evaluation_time,
            "selected_causal_A_GP_ID": unit.selected_A_GP_ID,
            "selected_causal_A_GP_EPOCH": unit.selected_A_GP_EPOCH,
            "selected_causal_A_GP_CREATION_DATE": unit.selected_A_GP_CREATION_DATE,
            "A_causal_GP_reconstructable": True,
            "B_reconstructable": True,
            "randomness_reconstructable": True,
            "primary_or_sensitivity_role": "PRIMARY_CORE",
            "include_in_R3": include,
            "exclusion_reason": "" if include else "DETERMINISTIC_TARGET_STRATIFIED_ACTIVE_PAIR_THINNING_NOT_FIRST_3_SHA256",
            "selection_uses_causal_A_result": False,
            "selection_rule": (
                "INCLUDE_ALL_R0_CORE_UNITS" if family != "active_compensation_first_pass"
                else "FIRST_3_B_PER_A_BY_SHA256_R2_ACTIVE_PAIR_V1"
            ),
            "A_reconstruction_rule": "latest CREATION_DATE<=evaluation_time, then latest EPOCH, then GP_ID",
            "B_reconstruction_rule": (
                "preserve original real-B identity and frozen historical TLE physical semantics"
                if b_class == "REAL_B" else
                "Perturb(A_causal, frozen original factor/rule); do not preserve legacy absolute B state"
            ),
            "planned_primary_realization_rows": 0,
            "planned_endpoint_rows": 0,
            "planned_diagnostic_rows": 0,
            "planned_sensitivity_rows_available_not_in_core_R3": 0,
        })
    return pd.DataFrame(records).sort_values(["experiment_family", "orbit_unit_id"]).reset_index(drop=True)


def source_case_map(rows: pd.DataFrame, family: str) -> pd.DataFrame:
    frame = rows[rows["experiment_family"].eq(family)][["case_id", "orbit_unit_id"]].drop_duplicates()
    if frame["case_id"].duplicated().any():
        raise SystemExit(f"Duplicate source case identity in {family}")
    return frame


def common_randomness_record(
    family: str, orbit_unit_id: str, case_id: str, source: Path, bk_mode: str,
    condition_id: str, realization_id: str, **values: Any,
) -> dict[str, Any]:
    return {
        "planned_row_identity": stable_id("r3row", family, case_id),
        "experiment_family": family, "orbit_unit_id": orbit_unit_id,
        "source_case_id": case_id, "source_artifact": rel(source), "row_role": "PRIMARY_CORE",
        "bk_mode": bk_mode, "condition_identity": condition_id,
        "realization_identity": realization_id,
        "master_seed": values.get("master_seed", ""),
        "environment_seed": values.get("environment_seed", ""),
        "noise_seed": values.get("noise_seed", ""),
        "random_seed": values.get("random_seed", ""),
        "b_env_hz": values.get("b_env_hz", ""),
        "k_env_hz_per_s": values.get("k_env_hz_per_s", ""),
        "sigma_hz": values.get("sigma_hz", ""),
        "noise_vector_hash": values.get("noise_vector_hash", ""),
        "observation_vector_hash": values.get("observation_vector_hash", ""),
        "draw_provenance": values["draw_provenance"],
        "replay_rule": values["replay_rule"],
        "new_random_draw_allowed": False,
        "endpoint_role": values.get("endpoint_role", "PRIMARY_ENDPOINT"),
    }


def build_randomness_binding(rows: pd.DataFrame, active_selected: set[str]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []

    family = "segment_local_heatmap_and_direction_sensitivity"
    segment = pd.read_csv(SEGMENT, dtype=str, keep_default_na=False)
    numeric_distance = pd.to_numeric(segment["distance_to_center_km"])
    numeric_phi = pd.to_numeric(segment["phi_deg"])
    numeric_r = pd.to_numeric(segment["R_cell_km"])
    keep_factor = (
        ((numeric_distance == 0.0) & (numeric_phi == 0.0))
        | numeric_distance.isin([5.0, 20.0])
        | (numeric_distance == numeric_r)
    )
    segment = segment[
        segment["bk_mode"].eq("current_bk")
        & segment["attack_model"].eq("M2_block")
        & keep_factor
    ].copy()
    segment = segment.merge(source_case_map(rows, family), on="case_id", how="left", validate="one_to_one")
    if len(segment) != 6200 or segment["orbit_unit_id"].isna().any():
        raise SystemExit("Segment-local reduced binding changed")
    for row in segment.itertuples(index=False):
        condition = stable_id("condition", row.orbit_unit_id, row.R_cell_km, row.distance_to_center_km, row.phi_deg, "M2_block")
        records.append(common_randomness_record(
            family, row.orbit_unit_id, row.case_id, SEGMENT, row.bk_mode, condition,
            f"sample_index_global:{row.sample_index_global}", random_seed=row.random_seed,
            b_env_hz=row.b_env, k_env_hz_per_s=row.k_env, sigma_hz=row.sigma_hz,
            draw_provenance="saved b/k/sigma plus frozen master RNG stream and sample_index_global",
            replay_rule="replay PCG64 seed 20260706 in authoritative source-sample order; validate saved b/k/sigma before verifier",
        ))

    family = "controlled_altitude_difference_synthetic_B"
    altitude = pd.read_csv(ALTITUDE, dtype=str, keep_default_na=False)
    altitude = altitude[altitude["bk_mode"].eq("current_bk")].copy()
    altitude["case_id"] = (
        altitude["observation_realization_id"] + ":" + altitude["bk_mode"] + ":"
        + pd.to_numeric(altitude["direction_deg"]).astype(str)
    )
    altitude = altitude.merge(source_case_map(rows, family), on="case_id", how="left", validate="one_to_one")
    if len(altitude) != 18000 or altitude["orbit_unit_id"].isna().any():
        raise SystemExit("Altitude primary binding changed")
    for row in altitude.itertuples(index=False):
        endpoint = "REFERENCE_ONLY" if float(row.delta_h_km) == 0.0 else "PRIMARY_ENDPOINT"
        records.append(common_randomness_record(
            family, row.orbit_unit_id, row.case_id, ALTITUDE, row.bk_mode,
            row.geometry_condition_id, row.observation_realization_id,
            master_seed=row.master_seed, environment_seed=row.environment_seed, noise_seed=row.noise_seed,
            b_env_hz=row.b_env_hz, k_env_hz_per_s=row.k_env_hz_per_s, sigma_hz=row.noise_sigma_hz,
            noise_vector_hash=row.noise_hash, observation_vector_hash=row.observation_vector_hash,
            draw_provenance="explicit environment/noise seeds and vector hashes",
            replay_rule="replay frozen per-realization PCG64 seeds; require exact noise and observation hashes",
            endpoint_role=endpoint,
        ))

    family = "same_pair_multi_pass_real_TLE"
    multipass = pd.read_csv(MULTIPASS, dtype=str, keep_default_na=False)
    multipass = multipass[multipass["bk_mode"].eq("current_bk")].copy()
    multipass["case_id"] = multipass["observation_realization_id"] + ":" + multipass["bk_mode"]
    multipass = multipass.merge(source_case_map(rows, family), on="case_id", how="left", validate="one_to_one")
    if len(multipass) != 2400 or multipass["orbit_unit_id"].isna().any():
        raise SystemExit("Same-pair multipass primary binding changed")
    for row in multipass.itertuples(index=False):
        records.append(common_randomness_record(
            family, row.orbit_unit_id, row.case_id, MULTIPASS, row.bk_mode,
            row.geometry_condition_id, row.observation_realization_id,
            master_seed=row.master_seed, environment_seed=row.environment_seed, noise_seed=row.noise_seed,
            b_env_hz=row.b_env, k_env_hz_per_s=row.k_env, sigma_hz=row.sigma_hz,
            noise_vector_hash=row.noise_hash, observation_vector_hash=row.observation_vector_hash,
            draw_provenance="explicit environment/noise/calibration seeds and vector hashes",
            replay_rule="replay frozen per-realization PCG64 seeds; require exact noise and observation hashes",
        ))

    family = "active_compensation_first_pass"
    active = pd.read_csv(ACTIVE, dtype=str, keep_default_na=False)
    active = active.merge(source_case_map(rows, family), left_on="sequence_id", right_on="case_id", how="left", validate="one_to_one")
    active = active[active["orbit_unit_id"].isin(active_selected)].copy()
    if len(active) != 180 or active["orbit_unit_id"].isna().any():
        raise SystemExit("Active primary binding changed")
    for row in active.itertuples(index=False):
        endpoint = "GEOMETRY_SANITY" if row.residual_mode == "clean" else "PRIMARY_ENDPOINT"
        condition = stable_id("condition", row.orbit_unit_id, row.compensation_type, row.residual_mode)
        records.append(common_randomness_record(
            family, row.orbit_unit_id, row.case_id, ACTIVE_SERIES, "ACTIVE_CURRENT_K_GATE",
            condition, row.sequence_id, random_seed=row.random_seed,
            b_env_hz=row.b_injected_hz, k_env_hz_per_s=row.k_injected_hz_s, sigma_hz=row.noise_sigma_hz,
            draw_provenance="exact saved active timeseries observation/noise variables plus frozen seed",
            replay_rule="read saved b/k/sigma/noise vector; no resampling",
            endpoint_role=endpoint,
        ))

    binding = pd.DataFrame(records).sort_values("planned_row_identity").reset_index(drop=True)
    if len(binding) != 26780 or binding["planned_row_identity"].duplicated().any():
        raise SystemExit("Planned R3 row population mismatch")
    return binding


def attach_counts(population: pd.DataFrame, binding: pd.DataFrame) -> pd.DataFrame:
    primary = binding.groupby("orbit_unit_id").size()
    endpoint = binding[binding["endpoint_role"].eq("PRIMARY_ENDPOINT")].groupby("orbit_unit_id").size()
    diagnostic = binding[~binding["endpoint_role"].eq("PRIMARY_ENDPOINT")].groupby("orbit_unit_id").size()
    population["planned_primary_realization_rows"] = population["orbit_unit_id"].map(primary).fillna(0).astype(int)
    population["planned_endpoint_rows"] = population["orbit_unit_id"].map(endpoint).fillna(0).astype(int)
    population["planned_diagnostic_rows"] = population["orbit_unit_id"].map(diagnostic).fillna(0).astype(int)
    sensitivity_per_primary = {
        "segment_local_heatmap_and_direction_sensitivity": 2,
        "controlled_altitude_difference_synthetic_B": 2,
        "same_pair_multi_pass_real_TLE": 2,
        "active_compensation_first_pass": 0,
    }
    population["planned_sensitivity_rows_available_not_in_core_R3"] = population.apply(
        lambda row: int(row.planned_primary_realization_rows * sensitivity_per_primary[row.experiment_family])
        if row.include_in_R3 else 0, axis=1,
    )
    return population


def family_summary(population: pd.DataFrame, binding: pd.DataFrame) -> pd.DataFrame:
    purposes = {
        "segment_local_heatmap_and_direction_sensitivity": "real/synthetic B comparison and service-direction dependence under segment-local geometry",
        "controlled_altitude_difference_synthetic_B": "signed physical altitude perturbation response across frozen passes and three receiver directions",
        "same_pair_multi_pass_real_TLE": "same real A/B pair repeatability across frozen passes",
        "active_compensation_first_pass": "none/subpoint-A/direct-S compensation comparison under the frozen active attack model",
    }
    selection = {
        "segment_local_heatmap_and_direction_sensitivity": "all 37 units; current_bk, M2_block, four R cells, d in {0,5,20,R}, phi=0 at d=0 otherwise all 8 phi",
        "controlled_altitude_difference_synthetic_B": "all 300 units and all 15 signed delta_h levels including zero reference; current_bk",
        "same_pair_multi_pass_real_TLE": "all 40 original pair-pass units, three frozen directions, 20 realizations; current_bk",
        "active_compensation_first_pass": "three SHA256-ordered B identities per A; all three compensation types and clean/empirical strata",
    }
    rows: list[dict[str, Any]] = []
    for family in CORE_FAMILIES:
        candidates = population[population["experiment_family"].eq(family)]
        included = candidates[candidates["include_in_R3"]]
        planned = binding[binding["experiment_family"].eq(family)]
        rows.append({
            "experiment_family": family, "role": "PRIMARY_CORE",
            "scientific_purpose": purposes[family],
            "candidate_units": len(candidates), "eligible_units": len(candidates),
            "included_R3_units": len(included), "excluded_units": len(candidates) - len(included),
            "planned_primary_rows": len(planned),
            "planned_endpoint_rows": int(planned["endpoint_role"].eq("PRIMARY_ENDPOINT").sum()),
            "planned_diagnostic_rows": int((~planned["endpoint_role"].eq("PRIMARY_ENDPOINT")).sum()),
            "available_no_bk_wide_bk_sensitivity_rows_not_in_core_R3": int(included["planned_sensitivity_rows_available_not_in_core_R3"].sum()),
            "result_blind_selection_rule": selection[family],
        })
    rows.append({
        "experiment_family": "historical_TLE_multi_pass_real_TLE", "role": "REGISTERED_SENSITIVITY_NOT_CORE_R3",
        "scientific_purpose": "different-date historical-TLE sensitivity; excluded from pooled primary core claim",
        "candidate_units": 8, "eligible_units": 8, "included_R3_units": 0, "excluded_units": 8,
        "planned_primary_rows": 0, "planned_endpoint_rows": 0, "planned_diagnostic_rows": 0,
        "available_no_bk_wide_bk_sensitivity_rows_not_in_core_R3": 1440,
        "result_blind_selection_rule": "retain as registered sensitivity family; do not execute in core R3",
    })
    return pd.DataFrame(rows)


def spotcheck_binding(binding: pd.DataFrame) -> pd.DataFrame:
    unit_rows = binding.copy()
    unit_rows["sample_hash"] = unit_rows["planned_row_identity"].map(
        lambda value: hashlib.sha256(f"R3_SPOTCHECK_V1|{value}".encode("utf-8")).hexdigest()
    )
    unit_rows = unit_rows.sort_values("sample_hash").drop_duplicates("orbit_unit_id")
    selected = []
    for family in CORE_FAMILIES:
        selected.append(unit_rows[unit_rows["experiment_family"].eq(family)].head(4))
    first = pd.concat(selected, ignore_index=True)
    remaining = unit_rows[~unit_rows["orbit_unit_id"].isin(set(first["orbit_unit_id"]))].head(14)
    output = pd.concat([first, remaining], ignore_index=True).sort_values("sample_hash").reset_index(drop=True)
    output["spotcheck_rank"] = np.arange(1, len(output) + 1)
    output["selection_rule"] = "4 distinct units per family, then lowest SHA256(R3_SPOTCHECK_V1|planned_row_identity) to 30"
    columns = [
        "spotcheck_rank", "planned_row_identity", "experiment_family", "orbit_unit_id",
        "source_case_id", "condition_identity", "realization_identity", "selection_rule",
    ]
    if len(output) != 30 or output["orbit_unit_id"].nunique() != 30 or output["experiment_family"].nunique() != 4:
        raise SystemExit("R3 deterministic spotcheck construction failed")
    return output[columns]


def analysis_protocol() -> dict[str, Any]:
    return {
        "protocol_name": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_R2_V1",
        "status": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN",
        "science_execution_performed": False,
        "selection_result_blind": True,
        "selection_forbidden_variables": sorted(FORBIDDEN_SELECTION_FIELDS),
        "causal_A_result_used_for_selection": False,
        "analysis_hierarchy": {
            "LEVEL_A_ORBIT_UNIT": "claimed A x candidate B x segment/time",
            "CONDITION_WITHIN_LEVEL_A": "frozen receiver/service direction or active-compensation treatment; shares one orbit decision",
            "LEVEL_B_OBSERVATION_OUTCOME": "frozen b/k/sigma/noise realization within its pre-registered condition",
            "primary_weighting": "LEVEL_A units receive equal weight within pre-registered scientific strata; row count never weights orbit units",
        },
        "primary_aggregation": {
            "endpoint": "controlled_observation_acceptance_fraction",
            "definition": "fraction of frozen observation-model realizations accepted within a LEVEL-A unit and pre-registered condition stratum",
            "terminology": "conditional verifier acceptance fraction under the controlled observation model",
            "forbidden_term": "attack success probability or real-world attack success rate",
            "primary_orbit_subset": "ORBIT_DISTINCT only (D2>c99)",
            "summaries": ["median", "IQR", "P90", "fraction_of_units_with_nonzero_acceptance"],
        },
        "orbit_scoring": {
            "model": "Freshness-Conditioned Robust Empirical RTN Ellipsoid",
            "parameter_sha256": FROZEN_PARAMETER_SHA,
            "unit_frequency": "once per LEVEL-A unit at segment center; shared by all conditions/realizations",
            "z_B": "RTN_public(x_A_public-x_B)",
            "support": "0<element_age_hours<=36; otherwise DEFER",
            "decision": {"D2<=c95": "NOT_ORBIT_DISTINCT", "c95<D2<=c99": "AMBIGUOUS", "D2>c99": "ORBIT_DISTINCT"},
            "rho99": "sqrt(D2/c99); explanatory scale, not probability",
            "supgp_operational_use": False,
        },
        "A_semantics": {
            "selector": "eligible CREATION_DATE<=evaluation_time; latest CREATION_DATE, then EPOCH, then GP_ID",
            "same_A_required_for": ["orbit scoring", "claimed-A Doppler", "active compensation", "verifier residual"],
        },
        "B_semantics": {
            "REAL_B": "preserve real satellite identity and original historical physical-orbit/TLE provenance at frozen time",
            "SYNTHETIC_RELATIVE_TO_A": "rebuild B=Perturb(A_causal,frozen factors/rule); preserve factor semantics, not legacy absolute B state",
            "boundary_targeting_forbidden_in_R3_core": True,
        },
        "modes": {
            "PRIMARY_BK_MODE": "current_bk",
            "ACTIVE_PRIMARY_EQUIVALENT": "existing p95 score plus frozen per-target current k gate",
            "SENSITIVITY_BK_MODES": ["no_bk", "wide_bk"],
            "sensitivity_execution": "registered but excluded from minimal core R3; requires separate post-core authorization without population reselection",
        },
        "randomness": {
            "new_sampling_allowed": False,
            "policy": "reuse exact saved variables/vectors or replay frozen seed and identity; validate available hashes before verifier",
            "realization_count_posthoc_change_allowed": False,
        },
        "time_semantics": {
            "evaluation_scope": "segment_local",
            "doppler_reference_mode": "fixed_site_segment_center",
            "verification_strategy": "single-window",
            "orbit_evaluation": "SEGMENT_CENTER",
            "doppler_evaluation": "FULL_FROZEN_SEGMENT_TIMESERIES",
        },
        "orbit_state_taxonomy": [
            "ORBIT_DEFER", "NOT_ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED",
            "NOT_ORBIT_DISTINCT_AND_DOPPLER_REJECTED", "ORBIT_AMBIGUOUS_AND_DOPPLER_ACCEPTED",
            "ORBIT_AMBIGUOUS_AND_DOPPLER_REJECTED", "ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED",
            "ORBIT_DISTINCT_AND_DOPPLER_REJECTED",
        ],
        "defer_policy": "report count/fraction separately; exclude from ORBIT_DISTINCT denominator",
        "ambiguous_policy": "report separately; never merge into ORBIT_DISTINCT",
        "not_orbit_distinct_policy": "retain as comparison; acceptance is not strong security-relevant indistinguishability evidence",
        "multipass_endpoint": [
            "passes evaluated per pair", "ORBIT_DISTINCT passes", "passes with nonzero conditional acceptance",
            "fraction of passes with nonzero conditional acceptance", "pass-specific conditional acceptance fraction",
        ],
        "R3_correctness_requirements": {
            "A_GP_causal_violation": 0, "future_publication": 0,
            "outside_support_incorrectly_scored": 0, "SupGP_operational_use": 0,
            "new_unintended_random_draw": 0, "R1_validated_verifier_path_reuse_fraction": 1.0,
            "frozen_thresholds_modified": 0, "frozen_uncertainty_parameters_modified": 0,
            "source_artifact_modification": 0,
        },
        "R3_stopping_rule": "execute every frozen included unit/row, audit causal provenance and randomness, assign score or DEFER, complete verifier and correctness audit; never expand based on observed result",
        "post_R3_decision": {
            "adequate_rho99_transition_coverage": "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS",
            "inadequate_rho99_transition_coverage": "TARGETED_ORBIT_DISTINCT_BOUNDARY_CASE_DESIGN (new R4 preregistration)",
        },
    }


def build_report(population: pd.DataFrame, summary: pd.DataFrame, binding: pd.DataFrame, spot: pd.DataFrame) -> str:
    core = summary[summary["role"].eq("PRIMARY_CORE")]
    included = population[population["include_in_R3"]]
    b_counts = included.groupby(["experiment_family", "B_class"]).size().rename("units").reset_index()
    return f"""# Causal-A Doppler core reconstruction design and freeze

## 正式状态

`CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN`

本轮只进行了 identity/provenance/configuration audit 与 protocol freeze。没有传播新的 causal-A/B state，没有计算 Doppler、score、gate、ACCEPT/REJECT、D2、rho99 或 joint-security result。

## 1. Core population

{core.to_markdown(index=False)}

最终 R3 primary core：**{int(core.included_R3_units.sum())} LEVEL-A units / {int(core.planned_primary_rows.sum())} planned rows**。其中 endpoint rows={int(core.planned_endpoint_rows.sum())}，reference/sanity diagnostic rows={int(core.planned_diagnostic_rows.sum())}。相比 158,520 legacy rows，计划重建 {int(core.planned_primary_rows.sum())} rows；不重复 historical-only derived views，也不在 core R3 执行 no_bk/wide_bk。

Active family 的 70 个 exclusion 仅由 `SHA256(R2_ACTIVE_PAIR_V1|A|B)` 每 A 取前三个 B 的 target-stratified thinning 产生。Segment-local 行级 thinning 仅使用 M2/current_bk 和原始 R/d/phi factors；所有 37 个 orbit units 均保留。没有使用 causal-A orbit score、rho99 或 verifier outcome。

## 2. B semantics

{b_counts.to_markdown(index=False)}

- REAL_B：保留真实 B identity 与原 historical TLE physical semantics；不围绕 causal A 生成 B。
- SYNTHETIC_RELATIVE_TO_A：以相同 signed altitude/phase/inclination/factor rule 围绕 `A_causal` 重建；保留科学 factor，不保留 legacy B absolute state。
- Segment-local 是 mixed-B family；controlled-altitude 全部是 A-relative synthetic；same-pair 与 active 全部是 REAL_B。

## 3. Causal A and analysis hierarchy

每个 LEVEL-A unit 冻结为 `claimed A × candidate B × segment/time`。A 使用 `CREATION_DATE<=evaluation_time` 后按 CREATION_DATE、EPOCH、GP_ID 逆序选择的同一个 GP，并统一驱动 orbit score、claimed Doppler、active compensation 和 verifier residual。Orbit decision 只在 segment center 计算一次；condition/realization 共享该 decision。

Receiver direction、service geometry 和 compensation type 是 unit 内预注册 condition strata，不伪装成 observation randomness。Observation realization 只作为 unit/condition 内 outcome。Primary endpoint 是 ORBIT_DISTINCT units 的 `controlled_observation_acceptance_fraction`，正式表述为 controlled observation model 下的 conditional verifier acceptance fraction，不是 attack success probability。

## 4. Modes and randomness

Primary mode=`current_bk`；active family 使用原 p95 score + per-target current k gate。`no_bk/wide_bk` 与 historical-TLE multipass 注册为 sensitivity，但不进入 minimal core R3。所有 planned rows 均绑定 saved draw variables/vector hashes 或 frozen seed/replay identity；new random draw forbidden。Randomness binding 共 {len(binding)} rows。

## 5. Orbit interface and downstream policy

Frozen Orbit-Uncertainty SHA=`{FROZEN_PARAMETER_SHA}`。`rho99=sqrt(D2/c99)` 不是概率。DEFER、AMBIGUOUS、NOT_ORBIT_DISTINCT 分开报告，均不得并入 ORBIT_DISTINCT denominator。Primary security-relevant state 为 `ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED`，但不得称真实攻击成功率。

R3 后才诊断 rho99 transition coverage。若不足，进入独立的 `TARGETED_ORBIT_DISTINCT_BOUNDARY_CASE_DESIGN`，不得回头修改本 core population。

## 6. Spot-check and contamination audit

R3 spot-check 已按 stable identity hash 预先冻结：{len(spot)} rows / {spot.orbit_unit_id.nunique()} distinct units，覆盖 {spot.experiment_family.nunique()} core families。Case selection 使用字段仅限 identity、family、factor、time、mode、seed/provenance。Causal-A `D2/rho99/orbit decision` 与新 Doppler results 均未生成或用于 selection；selection contamination=`FALSE`。

## 7. Formal decision

`R2: PASS`

`R3 AUTHORIZED: YES`

`NEXT STEP: CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION`
"""


def main() -> None:
    before = validate_inputs()
    rows, units = load_identity_units()
    active_selected = selected_active_units(units)
    population = build_population(rows, units, active_selected)
    binding = build_randomness_binding(rows, active_selected)
    population = attach_counts(population, binding)
    summary = family_summary(population, binding)
    spot = spotcheck_binding(binding)
    protocol = analysis_protocol()

    included = population[population["include_in_R3"]]
    if len(included) != 407 or included["planned_primary_realization_rows"].sum() != 26780:
        raise SystemExit("R2 final population size changed")
    if set(population.columns) & FORBIDDEN_SELECTION_FIELDS:
        raise SystemExit("Forbidden result field entered population freeze")
    if population["selection_uses_causal_A_result"].astype(bool).any():
        raise SystemExit("Potential causal-A result selection contamination")

    write_csv(POPULATION, population)
    write_csv(FAMILY_SUMMARY, summary)
    PROTOCOL.write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(RANDOMNESS, binding)
    write_csv(SPOTCHECK, spot)
    REPORT.write_text(build_report(population, summary, binding, spot), encoding="utf-8")

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path, digest in before.items() if after[path] != digest]
    if changed:
        raise SystemExit("Protected artifact changed: " + ", ".join(changed))
    source_bundles = {
        family: [
            {"path": path, "sha256": before[path]}
            for path in before if token in path
        ]
        for family, token in {
            "segment_local_heatmap_and_direction_sensitivity": "m2_segment_local",
            "controlled_altitude_difference_synthetic_B": "controlled_altitude_difference",
            "same_pair_multi_pass_real_TLE": "same_pair_multi_pass",
            "active_compensation_first_pass": "active_compensation_first_pass",
        }.items()
    }
    manifest = {
        "stage": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_AND_FREEZE",
        "status": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN",
        "R2": "PASS", "R3_authorized": True,
        "next_step": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "science_execution_performed": False,
        "execution_counters": {
            "orbit_propagation": 0, "Doppler_geometry": 0, "verifier": 0,
            "score": 0, "ACCEPT_REJECT": 0, "D2_rho99": 0,
            "joint_security_aggregate": 0, "new_B_generation": 0,
        },
        "population": {
            "core_candidate_units": 477, "core_eligible_units": 477,
            "core_included_units": 407, "core_excluded_units": 70,
            "planned_R3_rows": 26780,
            "planned_endpoint_rows": int(binding["endpoint_role"].eq("PRIMARY_ENDPOINT").sum()),
            "planned_diagnostic_rows": int((~binding["endpoint_role"].eq("PRIMARY_ENDPOINT")).sum()),
            "legacy_rows_not_default_rerun": 158520,
        },
        "selection": {
            "result_blind": True, "causal_A_result_used": False,
            "potential_selection_contamination": False,
            "forbidden_fields_absent": True,
        },
        "primary_bk_mode": "current_bk",
        "sensitivity_bk_modes": ["no_bk", "wide_bk"],
        "analysis_unit": "claimed A x candidate B x segment/time",
        "primary_endpoint": "conditional verifier acceptance fraction under the controlled observation model for ORBIT_DISTINCT units",
        "orbit_uncertainty_parameter_sha256": FROZEN_PARAMETER_SHA,
        "family_source_bundles": source_bundles,
        "authoritative_inputs": [
            {"path": path, "sha256": digest, "size_bytes": (ROOT / path).stat().st_size}
            for path, digest in before.items()
        ],
        "generator": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "outputs": [
            {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in [REPORT, POPULATION, FAMILY_SUMMARY, PROTOCOL, RANDOMNESS, SPOTCHECK]
        ],
        "protected_artifact_changes": changed,
        "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"""

## {now} - Causal-A Doppler core reconstruction design and freeze (R2)

### A. 本轮目标
在任何 causal-A security result 生成前，冻结 R3 core population、A/B semantics、randomness、analysis hierarchy、endpoint 和 spot-check。

### B. 实际操作
只读取 authoritative identity/factor/time/seed/provenance；使用 result-blind deterministic thinning。没有执行 orbit propagation、Doppler、verifier、score、decision 或 joint analysis。

### C. 新增/修改文件
新增 `{rel(REPORT)}`、`{rel(POPULATION)}`、`{rel(FAMILY_SUMMARY)}`、`{rel(PROTOCOL)}`、`{rel(RANDOMNESS)}`、`{rel(SPOTCHECK)}`、`{rel(MANIFEST)}`；历史 artifacts 未修改。

### D. 运行命令
`python scripts/freeze_causal_a_doppler_core_reconstruction_design.py`

### E. 结果摘要
`CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN`；407 included LEVEL-A units，26,780 planned R3 rows，30-row/30-unit result-blind spot-check；R3 authorized=YES。

### F. 问题与下一步
`CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION`。本轮未自动执行 R3。
""")
    print("CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN")
    print("R2: PASS")
    print("R3 AUTHORIZED: YES")
    print("PRIMARY CORE: 407 units / 26780 rows")
    print("NEXT STEP: CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION")


if __name__ == "__main__":
    main()
