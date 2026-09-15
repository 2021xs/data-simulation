import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def manifest() -> dict:
    return json.loads((METRICS / "causal_a_doppler_r3_manifest.json").read_text(encoding="utf-8"))


def test_r3_formal_status_and_population_completeness():
    data = manifest()
    assert data["status"] == "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION_COMPLETE"
    assert data["R3"] == "PASS"
    assert data["next_step"] == "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS"
    assert data["population"] == {
        "candidate_units": 477,
        "included_LEVEL_A_units_expected": 407,
        "included_LEVEL_A_units_executed": 407,
        "observation_rows_expected": 26780,
        "observation_rows_executed": 26780,
        "endpoint_rows": 25490,
        "diagnostic_reference_rows": 1290,
    }


def test_exact_family_population_and_row_binding():
    family = pd.read_csv(METRICS / "causal_a_doppler_r3_family_execution_summary.csv")
    expected = {
        "segment_local_heatmap_and_direction_sensitivity": (37, 6200),
        "controlled_altitude_difference_synthetic_B": (300, 18000),
        "same_pair_multi_pass_real_TLE": (40, 2400),
        "active_compensation_first_pass": (30, 180),
    }
    observed = {
        row.experiment_family: (int(row.executed_units), int(row.executed_rows))
        for row in family.itertuples(index=False)
    }
    assert observed == expected
    assert (family["planned_units"] == family["executed_units"]).all()
    assert (family["planned_rows"] == family["executed_rows"]).all()
    assert family["failed_rows"].sum() == 0
    assert family["new_randomness_rows"].sum() == 0
    assert family["provenance_failures"].sum() == 0

    rows = pd.read_csv(DATASETS / "causal_a_doppler_r3_observation_rows.csv", low_memory=False)
    frozen = pd.read_csv(METRICS / "causal_a_doppler_r2_randomness_binding.csv", usecols=["planned_row_identity"])
    assert len(rows) == 26780
    assert rows["planned_row_identity"].nunique() == 26780
    assert set(rows["planned_row_identity"]) == set(frozen["planned_row_identity"])
    assert rows["execution_status"].eq("COMPLETE").all()
    assert rows["new_random_draw_count"].sum() == 0
    assert rows["SupGP_operational_use"].sum() == 0
    assert rows["R1_validated_production_path"].all()


def test_orbit_scoring_semantics_and_decisions():
    units = pd.read_csv(DATASETS / "causal_a_doppler_r3_unit_summary.csv")
    assert len(units) == 407
    assert units["orbit_unit_id"].nunique() == 407
    assert units["future_publication_violation"].sum() == 0
    assert units["orbit_decision"].value_counts().to_dict() == {
        "ORBIT_DISTINCT": 265,
        "AMBIGUOUS": 119,
        "NOT_ORBIT_DISTINCT": 23,
    }
    assert units["orbit_decision"].ne("DEFER").all()
    assert (units["element_age_hours"] > 0).all()
    assert (units["element_age_hours"] <= 36).all()
    assert np.allclose(units["rho99"], np.sqrt(units["D2"] / units["c99"]), rtol=1e-13, atol=1e-13)
    assert (units["rtn_orthonormality_error"] <= 1e-12).all()
    assert (units["sign_mapping_error_km"] <= 1e-12).all()


def test_boundary_spotcheck_and_correctness_audits():
    boundary = pd.read_csv(METRICS / "causal_a_doppler_r3_boundary_coverage_diagnostic.csv")
    overall = boundary[boundary["scope"].eq("OVERALL")].iloc[0]
    assert (int(overall.rho99_lt_0p8), int(overall.rho99_0p8_to_1p2), int(overall.rho99_gt_1p2)) == (108, 40, 259)
    assert overall.coverage_status == "BOUNDARY_COVERAGE_SUFFICIENT_DESCRIPTIVE"
    assert overall.hard_minimum_rule == "NOT_FROZEN; descriptive band presence only"

    spot = pd.read_csv(METRICS / "causal_a_doppler_r3_spotcheck_audit.csv")
    assert len(spot) == 30 and spot["orbit_unit_id"].nunique() == 30
    assert spot["experiment_family"].nunique() == 4
    assert spot["spotcheck_pass"].all()
    assert spot["categorical_mismatch_count"].sum() == 0

    audit = pd.read_csv(METRICS / "causal_a_doppler_r3_correctness_audit.csv")
    assert audit["passed"].all()


def test_manifest_hash_bindings_and_no_post_result_expansion():
    data = manifest()
    assert data["correctness"]["all_checks_pass"] is True
    assert data["correctness"]["future_publication_violations"] == 0
    assert data["correctness"]["new_random_draw_count"] == 0
    assert data["correctness"]["SupGP_operational_use"] == 0
    assert data["correctness"]["verifier_execution_failures"] == 0
    assert data["correctness"]["spotcheck_passed"] == 30
    assert data["correctness"]["categorical_mismatch_count"] == 0
    assert data["correctness"]["protected_artifact_changes"] == []
    assert data["post_result_population_expansion"] is False
    assert data["science_interpretation_performed"] is False
    assert data["frozen_orbit_uncertainty_parameter_sha256"] == "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
    for record in data["R2_bindings"] + [data["R1_validated_manifest"], data["bridge_scoring_interface"]] + data["outputs"]:
        assert sha256(ROOT / record["path"]) == record["sha256"]
    assert sha256(ROOT / data["generator"]["path"]) == data["generator"]["sha256"]
