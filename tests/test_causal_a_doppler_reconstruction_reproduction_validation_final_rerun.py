import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_manifest() -> dict:
    return json.loads((METRICS / "causal_a_doppler_r1_final_manifest.json").read_text(encoding="utf-8"))


def test_final_population_and_execution_guards():
    manifest = load_manifest()
    assert manifest["stage"] == "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN"
    assert manifest["primary_population"] == {
        "units_expected": 64, "units_actual": 64,
        "rows_expected": 6280, "rows_actual": 6280,
    }
    assert manifest["secondary_population"] == {"rows_expected": 200, "rows_actual": 200}
    assert manifest["execution_counters"]["semantics_mismatch_units"] == 0
    assert manifest["execution_counters"]["new_random_draws"] == 0
    assert manifest["population_changed"] is False
    assert manifest["scientific_thresholds_modified"] is False
    assert manifest["effective_reproduction_tolerances_modified"] is False


def test_effective_tolerances_are_exactly_bound_and_reproduction_only():
    manifest = load_manifest()
    binding = manifest["effective_reproduction_tolerance_protocol"]
    assert binding["scope"] == "HISTORICAL_SERIALIZED_ARTIFACT_REPRODUCTION_ONLY"
    assert binding["modified_during_final_rerun"] is False
    assert binding["values"] == {
        "time": 1e-12,
        "A_position": 1e-6, "A_velocity": 1e-9,
        "B_position": 1e-6, "B_velocity": 1e-9,
        "geometry": 3.9e-6, "compensation": 8e-6,
        "residual": 1.6e-5, "b": 1.7e-5,
        "k": 2e-7, "b_score": 1.6e-5,
    }
    assert sha256(ROOT / binding["path"]) == binding["sha256"]


def test_primary_categorical_and_numerical_requirements():
    manifest = load_manifest()
    assert manifest["R1_primary"] == "PASS"
    assert manifest["status"] == "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATED"
    assert manifest["all_frozen_numerical_tolerances_pass"] is True
    assert manifest["earliest_divergence_layer"] == "NONE"
    assert all(value == 0 for value in manifest["categorical_mismatches"].values())
    assert manifest["spotcheck"] == {
        "selection_rule": "deterministic stratified SHA256(R1_SPOTCHECK_V1|stable_row_identity)",
        "rows": 30, "passed": 30,
    }
    assert manifest["R2_authorized"] is True


def test_final_rows_secondary_and_output_hashes():
    manifest = load_manifest()
    rows = pd.read_csv(DATASETS / "causal_a_doppler_r1_final_reproduction_rows.csv")
    v2 = pd.read_csv(METRICS / "causal_a_doppler_r1_final_verifier_v2_crosscheck.csv")
    assert len(rows) == 6280 and rows["orbit_unit_id"].nunique() == 64
    assert rows["reproduction_pass"].astype(bool).all()
    assert int(rows["spotcheck_selected"].sum()) == 30
    assert rows.loc[rows["spotcheck_selected"], "spotcheck_pass"].astype(bool).all()
    assert len(v2) == 200 and v2["crosscheck_pass"].astype(bool).all()
    assert manifest["verifier_v2_crosscheck"] == "PASS"
    assert manifest["protected_artifact_changes"] == []
    for artifact in manifest["outputs"]:
        assert sha256(ROOT / artifact["path"]) == artifact["sha256"]
