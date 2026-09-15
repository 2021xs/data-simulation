from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/analyze_orbit_distinct_doppler_joint_security.py"
SPEC = importlib.util.spec_from_file_location("joint_analysis", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_acceptance_labels_are_mutually_exclusive() -> None:
    frame = pd.DataFrame({
        MODULE.ENDPOINT: [0, 0.01, 0.1, 0.11, 0.5, 0.51, 0.89, 0.9, 0.99, 1.0],
        "delta_R_km": [1.0] * 10,
        "delta_T_km": [0.0] * 10,
        "delta_N_km": [0.0] * 10,
    })
    result = MODULE.add_acceptance_labels(frame)
    assert result["descriptive_persistence_label"].tolist() == [
        "ZERO", "RARE", "RARE", "MIXED", "MIXED", "MIXED", "MIXED", "HIGH", "HIGH", "FULL"
    ]
    assert result["descriptive_interval"].tolist() == [
        "0", "(0,0.1]", "(0,0.1]", "(0.1,0.5]", "(0.1,0.5]",
        "(0.5,0.9]", "(0.5,0.9]", "(0.5,0.9]", "(0.9,1)", "1",
    ]


def test_frozen_primary_population_and_distribution() -> None:
    units = pd.read_csv(ROOT / MODULE.INPUTS["unit_summary"])
    primary = MODULE.add_acceptance_labels(units[units["orbit_decision"].eq("ORBIT_DISTINCT")])
    counts = primary["descriptive_persistence_label"].value_counts().to_dict()
    assert len(primary) == 265
    assert int(primary[MODULE.ENDPOINT].gt(0).sum()) == 198
    assert counts == {"MIXED": 156, "ZERO": 67, "RARE": 37, "HIGH": 5}
    assert int(primary[MODULE.ENDPOINT].eq(1).sum()) == 0


def test_active_compensation_is_exactly_paired() -> None:
    units = pd.read_csv(ROOT / MODULE.INPUTS["unit_summary"])
    rows = pd.read_csv(ROOT / MODULE.INPUTS["observation_rows"], low_memory=False)
    primary = MODULE.add_acceptance_labels(units[units["orbit_decision"].eq("ORBIT_DISTINCT")])
    summary, transitions = MODULE.build_compensation_summary(primary, rows)
    audit = summary[summary["record_type"].eq("PAIRING_AUDIT")].iloc[0]
    assert int(audit["exact_draw_geometry_pairs"]) == 30
    assert transitions["none:REJECT->direct_S_ideal:ACCEPT"] == 25
    assert transitions["none:REJECT->subpoint_A:REJECT"] == 30


def test_multi_pass_summary_is_pair_aware() -> None:
    units = pd.read_csv(ROOT / MODULE.INPUTS["unit_summary"])
    rows = pd.read_csv(ROOT / MODULE.INPUTS["observation_rows"], low_memory=False)
    primary = MODULE.add_acceptance_labels(units[units["orbit_decision"].eq("ORBIT_DISTINCT")])
    summary = MODULE.build_multipass_summary(primary, rows)
    pair = summary[summary["record_type"].eq("PAIR_SUMMARY")]
    assert len(pair) == 10
    assert set(pair["passes_evaluated"].astype(int)) == {4}
    assert int(pair["persistent_nonzero_multiple_passes"].eq(True).sum()) == 0
    assert int(pair["all_pass_zero"].eq(True).sum()) == 5


def test_gate_attribution_partitions_orbit_distinct_endpoint_rows() -> None:
    rows = pd.read_csv(ROOT / MODULE.INPUTS["observation_rows"], low_memory=False)
    summary = MODULE.build_gate_attribution(rows)
    overall = summary[
        summary["record_type"].eq("EXCLUSIVE_GATE_COMBINATION")
        & summary["scope"].eq("ALL_ORBIT_DISTINCT_ROWS")
    ]
    assert int(overall["observation_row_count"].sum()) == 17850
    accepted = overall[overall["gate_attribution"].eq("ACCEPT_ALL_GATES_PASS")]
    assert int(accepted.iloc[0]["observation_row_count"]) == 4530
