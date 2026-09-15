import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"


def test_erratum_is_reproduction_only():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_numerical_tolerance_erratum_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED"
    assert manifest["scientific_method_changed"] is False
    assert manifest["scientific_threshold_changed"] is False
    assert manifest["verifier_behavior_changed"] is False
    assert manifest["population_changed"] is False
    assert manifest["categorical_match_requirement"] == "UNCHANGED_EXACT_ZERO_MISMATCH"
    assert manifest["R1_rerun_performed"] is False
    assert manifest["R2_authorized"] is False


def test_bounds_are_independent_and_cover_validation_values():
    derivation = pd.read_csv(METRICS / "causal_a_doppler_r1_numerical_tolerance_bound_derivation.csv")
    bounds = derivation[derivation.record_type.eq("INDEPENDENT_BOUND")]
    assert len(bounds) == 6
    assert not bounds.bound_construction_uses_observed_R1_max.astype(bool).any()
    assert (bounds.proposed_reproduction_tolerance.astype(float) >= bounds.derived_conservative_bound.astype(float)).all()
    assert bounds.observed_within_proposed.astype(bool).all()


def test_state_tolerances_stay_and_numerical_reproduction_tolerances_are_separate():
    erratum = pd.read_csv(METRICS / "causal_a_doppler_r1_numerical_tolerance_erratum.csv")
    kept = erratum[erratum.decision.eq("KEEP")]
    changed = erratum[erratum.decision.eq("ERRATUM_REQUIRED")]
    assert set(["A_position", "A_velocity", "B_position", "B_velocity"]).issubset(set(kept.quantity))
    assert set(["Doppler_geometry", "active_compensation_curve", "observation_and_raw_residual", "k_hat"]).issubset(set(changed.quantity))
    assert erratum.scientific_effect.eq("NONE").all()
    assert erratum.scope.eq("HISTORICAL_REPRODUCTION_ONLY").all()


def test_output_hashes_are_bound():
    manifest = json.loads((METRICS / "causal_a_doppler_r1_numerical_tolerance_erratum_manifest.json").read_text(encoding="utf-8"))
    assert manifest["protected_artifact_changes"] == []
    for item in manifest["outputs"]:
        digest = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest().upper()
        assert digest == item["sha256"]
