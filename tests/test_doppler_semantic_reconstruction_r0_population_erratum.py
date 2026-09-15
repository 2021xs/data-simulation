import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_corrected_identity_sets_are_exact_and_disjoint():
    binding = pd.read_csv(METRICS / "doppler_semantic_reconstruction_r1_corrected_population_binding.csv", dtype=str)
    primary = binding[binding["row_role"].eq("PRIMARY")]
    secondary = binding[binding["row_role"].eq("VERIFIER_V2_SECONDARY")]
    assert len(primary) == 6280
    assert len(secondary) == 200
    assert len(binding) == 6480
    assert primary["stable_row_identity"].nunique() == 6280
    assert secondary["stable_row_identity"].nunique() == 200
    assert set(primary["stable_row_identity"]).isdisjoint(set(secondary["stable_row_identity"]))


def test_64_unit_accounting_reconciles_to_binding():
    audit = pd.read_csv(METRICS / "doppler_semantic_reconstruction_r0_population_identity_audit.csv")
    assert len(audit) == 64
    assert audit["orbit_unit_id"].nunique() == 64
    assert int(audit["primary_row_count"].sum()) == 6280
    assert int(audit["secondary_row_count"].sum()) == 200
    assert int(audit["total_row_count"].sum()) == 6480
    assert audit["compatible_unit"].astype(bool).all()


def test_erratum_is_accounting_only_and_authorizes_only_r1_rerun():
    manifest = json.loads((METRICS / "doppler_semantic_reconstruction_r0_population_erratum_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "R0_POPULATION_ERRATUM_PUBLISHED"
    assert manifest["scientific_method_changed"] is False
    assert manifest["post_hoc_scientific_tuning"] is False
    assert manifest["result_driven_population_change"] is False
    assert manifest["population_identity_change"] is False
    assert manifest["accounting_correction_only"] is True
    assert manifest["pre_erratum_R1_numerical_results_generated_or_inspected"] is False
    assert manifest["R1_rerun_authorized"] is True
    assert manifest["R2_authorized"] is False
    assert all(value == 0 for value in manifest["execution_counters"].values())


def test_manifest_hashes_and_frozen_parameter_binding():
    manifest = json.loads((METRICS / "doppler_semantic_reconstruction_r0_population_erratum_manifest.json").read_text(encoding="utf-8"))
    assert manifest["frozen_parameter_sha256"] == "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
    assert manifest["protected_artifact_changes"] == []
    for artifact in manifest["outputs"]:
        assert sha256(ROOT / artifact["path"]) == artifact["sha256"]
