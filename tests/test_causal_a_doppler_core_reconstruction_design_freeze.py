import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_manifest() -> dict:
    return json.loads((METRICS / "causal_a_doppler_r2_manifest.json").read_text(encoding="utf-8"))


def test_r2_status_and_no_science_execution():
    manifest = load_manifest()
    assert manifest["status"] == "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN"
    assert manifest["R2"] == "PASS"
    assert manifest["R3_authorized"] is True
    assert manifest["science_execution_performed"] is False
    assert all(value == 0 for value in manifest["execution_counters"].values())
    assert manifest["protected_artifact_changes"] == []


def test_core_population_is_exact_causal_and_result_blind():
    population = pd.read_csv(METRICS / "causal_a_doppler_r2_core_population.csv", dtype=str, keep_default_na=False)
    forbidden = {
        "orbit_D2", "orbit_rho99", "orbit_decision", "original_verifier_score",
        "original_verifier_accept", "original_verifier_decision", "security_joint_state",
        "score", "accept_flag", "final_decision",
    }
    assert len(population) == 477
    assert not forbidden.intersection(population.columns)
    assert population["A_causal_GP_reconstructable"].eq("True").all()
    assert population["B_reconstructable"].eq("True").all()
    assert population["randomness_reconstructable"].eq("True").all()
    assert population["selection_uses_causal_A_result"].eq("False").all()
    assert (pd.to_datetime(population["selected_causal_A_GP_CREATION_DATE"], utc=True, format="mixed")
            <= pd.to_datetime(population["evaluation_time"], utc=True, format="mixed")).all()
    included = population[population["include_in_R3"].eq("True")]
    assert len(included) == 407
    assert included.groupby("experiment_family").size().to_dict() == {
        "active_compensation_first_pass": 30,
        "controlled_altitude_difference_synthetic_B": 300,
        "same_pair_multi_pass_real_TLE": 40,
        "segment_local_heatmap_and_direction_sensitivity": 37,
    }
    active = included[included["experiment_family"].eq("active_compensation_first_pass")]
    assert active.groupby("A_id").size().eq(3).all()


def test_planned_rows_randomness_and_family_counts():
    binding = pd.read_csv(METRICS / "causal_a_doppler_r2_randomness_binding.csv", dtype=str, keep_default_na=False)
    summary = pd.read_csv(METRICS / "causal_a_doppler_r2_family_summary.csv")
    core = summary[summary["role"].eq("PRIMARY_CORE")].set_index("experiment_family")
    assert len(binding) == 26780
    assert binding["planned_row_identity"].nunique() == 26780
    assert binding["new_random_draw_allowed"].eq("False").all()
    assert binding.groupby("experiment_family").size().to_dict() == {
        "active_compensation_first_pass": 180,
        "controlled_altitude_difference_synthetic_B": 18000,
        "same_pair_multi_pass_real_TLE": 2400,
        "segment_local_heatmap_and_direction_sensitivity": 6200,
    }
    assert core["included_R3_units"].astype(int).sum() == 407
    assert core["planned_primary_rows"].astype(int).sum() == 26780
    assert core["planned_endpoint_rows"].astype(int).sum() == 25490
    assert core["planned_diagnostic_rows"].astype(int).sum() == 1290


def test_analysis_protocol_and_spotcheck_are_frozen():
    protocol = json.loads((METRICS / "causal_a_doppler_r2_analysis_protocol.json").read_text(encoding="utf-8"))
    spot = pd.read_csv(METRICS / "causal_a_doppler_r2_spotcheck_binding.csv")
    assert protocol["selection_result_blind"] is True
    assert protocol["causal_A_result_used_for_selection"] is False
    assert protocol["modes"]["PRIMARY_BK_MODE"] == "current_bk"
    assert protocol["modes"]["SENSITIVITY_BK_MODES"] == ["no_bk", "wide_bk"]
    assert protocol["analysis_hierarchy"]["LEVEL_A_ORBIT_UNIT"] == "claimed A x candidate B x segment/time"
    assert protocol["primary_aggregation"]["endpoint"] == "controlled_observation_acceptance_fraction"
    assert len(spot) == 30 and spot["orbit_unit_id"].nunique() == 30
    assert spot["experiment_family"].nunique() == 4
    assert spot.groupby("experiment_family").size().ge(4).all()


def test_manifest_binds_outputs_and_frozen_orbit_interface():
    manifest = load_manifest()
    assert manifest["orbit_uncertainty_parameter_sha256"] == "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
    assert manifest["selection"] == {
        "result_blind": True,
        "causal_A_result_used": False,
        "potential_selection_contamination": False,
        "forbidden_fields_absent": True,
    }
    for output in manifest["outputs"]:
        assert sha256(ROOT / output["path"]) == output["sha256"]
    bound = {item["path"]: item["sha256"] for item in manifest["authoritative_inputs"]}
    required = [
        "outputs/metrics/doppler_semantic_reconstruction_protocol.json",
        "outputs/metrics/causal_a_doppler_r1_final_manifest.json",
        "outputs/metrics/orbit_distinct_frozen_scoring_interface.json",
        "data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260226_20260329_20sat_omm.json",
    ]
    assert all(path in bound for path in required)
