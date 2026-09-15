import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_corrected_primary_and_secondary_are_kept_separate():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_rerun_manifest.json").read_text(encoding="utf-8"))
    assert manifest["primary_population"] == {"units_expected": 64, "units_actual": 64, "rows_expected": 6280, "rows_actual": 6280}
    assert manifest["secondary_population"]["rows_expected"] == 200
    if manifest["R1_primary"] == "PASS":
        assert manifest["secondary_population"]["rows_actual"] == 200
    else:
        assert manifest["secondary_population"]["rows_actual"] == 0
        assert manifest["verifier_v2_crosscheck"] == "LIMITATION"
    assert manifest["execution_counters"]["semantics_mismatch_units"] == 0
    assert manifest["execution_counters"]["new_random_draws"] == 0


def test_primary_status_is_derived_from_frozen_requirements():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_rerun_manifest.json").read_text(encoding="utf-8"))
    numerical_pass = manifest["all_frozen_numerical_tolerances_pass"] is True
    categorical_pass = all(value == 0 for value in manifest["categorical_mismatches"].values())
    expected_pass = numerical_pass and categorical_pass
    assert (manifest["R1_primary"] == "PASS") is expected_pass
    assert (manifest["status"] == "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATED") is expected_pass
    assert manifest["R2_authorized"] is expected_pass
    assert (manifest["earliest_divergence_layer"] == "NONE") is expected_pass


def test_all_rows_units_and_spotchecks_are_accounted_for():
    rows = pd.read_csv(DATASETS / "causal_a_doppler_r1_rerun_reproduction_rows.csv")
    state = pd.read_csv(METRICS / "causal_a_doppler_r1_rerun_state_reproduction.csv")
    geometry = pd.read_csv(METRICS / "causal_a_doppler_r1_rerun_geometry_reproduction.csv")
    v2 = pd.read_csv(METRICS / "causal_a_doppler_r1_rerun_verifier_v2_crosscheck.csv")
    assert len(rows) == 6280 and rows["orbit_unit_id"].nunique() == 64
    assert len(state) == 64 and state["state_pass"].astype(bool).all()
    assert len(geometry) == 64
    assert int(rows["spotcheck_selected"].sum()) == 30
    manifest = json.loads((METRICS / "causal_a_doppler_r1_rerun_manifest.json").read_text(encoding="utf-8"))
    if manifest["R1_primary"] == "PASS":
        assert rows.loc[rows["spotcheck_selected"], "spotcheck_pass"].astype(bool).all()
        assert rows["reproduction_pass"].astype(bool).all()
        assert geometry["geometry_pass"].astype(bool).all()
        assert len(v2) == 200 and v2["crosscheck_pass"].astype(bool).all()
    else:
        assert not rows["reproduction_pass"].astype(bool).all()
        assert not geometry["geometry_pass"].astype(bool).all()
        assert int(rows.loc[rows["spotcheck_selected"], "spotcheck_pass"].sum()) == manifest["spotcheck"]["passed"]
        assert len(v2) == 1 and v2.iloc[0]["reason"] == "PRIMARY_FAILED"


def test_manifest_output_hashes_and_frozen_binding():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_rerun_manifest.json").read_text(encoding="utf-8"))
    assert manifest["frozen_parameter_sha256"] == "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
    assert manifest["protected_artifact_changes"] == []
    assert manifest["scientific_method_changed"] is False
    for artifact in manifest["outputs"]:
        assert sha256(ROOT / artifact["path"]) == artifact["sha256"]
