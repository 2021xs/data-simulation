import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"


def test_r1_fails_closed_on_frozen_population_inconsistency():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED"
    assert manifest["failure_subtype"] == "FROZEN_POPULATION_INCONSISTENCY"
    assert manifest["counts"]["actual_units"] == 64
    assert manifest["counts"]["expected_primary_rows"] == 6480
    assert manifest["counts"]["actual_primary_rows"] == 6280
    assert manifest["counts"]["actual_secondary_v2_rows"] == 200
    assert manifest["counts"]["actual_bound_total_rows"] == 6480
    assert manifest["R2_authorized"] is False


def test_population_binding_is_complete_and_disjoint():
    rows = pd.read_csv(DATASETS / "causal_a_doppler_r1_reproduction_rows.csv", dtype=str)
    assert len(rows) == 6480
    assert rows["orbit_unit_id"].nunique() == 64
    assert int(rows["r1_role"].eq("PRIMARY_SOURCE").sum()) == 6280
    assert int(rows["r1_role"].eq("SECONDARY_VERIFIER_V2").sum()) == 200
    assert not rows.duplicated(["source_artifact", "case_id", "source_view"]).any()


def test_no_numerical_or_verifier_execution_occurred():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_manifest.json").read_text(encoding="utf-8"))
    for key in [
        "orbit_propagation_count", "doppler_geometry_execution_count", "random_draw_count",
        "OLS_execution_count", "verifier_execution_count", "spotcheck_count",
    ]:
        assert manifest[key] == 0
    failure = pd.read_csv(METRICS / "causal_a_doppler_r1_failure_attribution.csv")
    assert failure.loc[0, "failure_category"] == "PROVENANCE_UNKNOWN"
    assert failure.loc[0, "earliest_divergence_level"] == "PRE_LEVEL_1_POPULATION_GATE"


def test_frozen_parameter_and_sources_are_protected():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_manifest.json").read_text(encoding="utf-8"))
    assert manifest["frozen_parameter_sha256"] == "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
    assert manifest["protected_input_changes"] == []
