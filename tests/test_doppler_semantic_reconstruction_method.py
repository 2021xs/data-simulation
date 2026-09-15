import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
METRICS = ROOT / "outputs" / "metrics"


def test_frozen_protocol_has_required_semantic_guards():
    protocol = json.loads((METRICS / "doppler_semantic_reconstruction_protocol.json").read_text(encoding="utf-8"))
    assert protocol["status"] == "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN"
    assert protocol["legacy_direct_relabel"] == "NOT_SUFFICIENT"
    assert protocol["deterministic_transform_decision"] == "FULL_DOPPLER_RECOMPUTATION_REQUIRED_FOR_A_SEMANTICS_MISMATCH"
    assert protocol["minimum_reconstruction_policy"]["rerun_all_158520_rows"] is False
    assert protocol["R1_reproduction_gate"]["orbit_unit_count"] == 64
    assert protocol["R1_reproduction_gate"]["primary_source_rows_bound_to_units"] == 6480
    assert protocol["next_step"] == "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION"


def test_family_matrix_uses_only_frozen_status_vocabulary():
    frame = pd.read_csv(METRICS / "doppler_semantic_reconstruction_family_matrix.csv")
    assert len(frame) == 10
    assert set(frame["priority_for_final_mainline"]) <= {
        "RECONSTRUCT_CORE", "RECONSTRUCT_SENSITIVITY", "KEEP_HISTORICAL_ONLY", "DROP_FROM_FINAL_MAINLINE"
    }
    assert int(frame["priority_for_final_mainline"].eq("RECONSTRUCT_CORE").sum()) == 4
    relative = frame[frame["B_class"].str.contains("SYNTHETIC_RELATIVE_TO_A")]
    assert relative["B_policy"].str.contains("causal|A_causal", case=False, regex=True).all()


def test_dependency_audit_requires_recomputation_of_all_A_dependent_outputs():
    frame = pd.read_csv(METRICS / "doppler_semantic_reconstruction_dependency_audit.csv")
    downstream = frame.set_index("quantity")
    for quantity in ["F_A_S_t", "raw_residual", "OLS_b_hat", "OLS_k_hat", "residual_score", "ACCEPT_REJECT_DEFER"]:
        assert bool(downstream.loc[quantity, "A_dependent"])
        assert "RECOMPUTE" in downstream.loc[quantity, "reconstruction_policy"] or "REFIT" in downstream.loc[quantity, "reconstruction_policy"]
    assert downstream.loc["score_threshold", "reconstruction_policy"] == "REUSE_FROZEN"
