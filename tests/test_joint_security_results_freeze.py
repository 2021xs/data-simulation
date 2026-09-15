from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/freeze_joint_security_results.py"
SPEC = importlib.util.spec_from_file_location("final_freeze", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def load_authoritative() -> dict:
    return {
        "orbit_manifest": MODULE.read_json(ROOT / MODULE.INPUTS["orbit_final_manifest"]),
        "r1_manifest": MODULE.read_json(ROOT / MODULE.INPUTS["r1_manifest"]),
        "r2_manifest": MODULE.read_json(ROOT / MODULE.INPUTS["r2_manifest"]),
        "r3_manifest": MODULE.read_json(ROOT / MODULE.INPUTS["r3_manifest"]),
        "joint_manifest": MODULE.read_json(ROOT / MODULE.INPUTS["joint_manifest"]),
        "orbit_evidence": pd.read_csv(ROOT / MODULE.INPUTS["orbit_evidence_matrix"]),
        "r3_correctness": pd.read_csv(ROOT / MODULE.INPUTS["r3_correctness"]),
        "primary": pd.read_csv(ROOT / MODULE.INPUTS["primary_units"]),
        "family": pd.read_csv(ROOT / MODULE.INPUTS["family_summary"]),
        "rho": pd.read_csv(ROOT / MODULE.INPUTS["rho99_summary"]),
        "multipass": pd.read_csv(ROOT / MODULE.INPUTS["multipass_summary"]),
        "compensation": pd.read_csv(ROOT / MODULE.INPUTS["compensation_summary"]),
        "gates": pd.read_csv(ROOT / MODULE.INPUTS["gate_attribution"]),
    }


def test_authoritative_states_and_population() -> None:
    data = load_authoritative()
    MODULE.validate_states(data)
    assert data["joint_manifest"]["key_results"]["ORBIT_DISTINCT_units"] == 265
    assert data["joint_manifest"]["key_results"]["nonzero"] == 198


def test_six_proposed_claims_are_adjudicated_conservatively() -> None:
    claims = MODULE.build_claim_matrix()
    proposed = claims[claims["CLAIM_ID"].str.match(r"C[1-6]_")].set_index("CLAIM_ID")
    assert len(proposed) == 6
    assert proposed.loc["C1_ORBIT_DISTINCT_ACCEPTANCE_EXISTS", "proposed_claim_adjudication"] == "SUPPORTED"
    assert proposed.loc["C3_KM_NOT_ORBIT_GATE", "proposed_claim_adjudication"] == "SUPPORTED"
    assert (proposed["proposed_claim_adjudication"] == "SUPPORTED_WITH_LIMITATION").sum() == 4


def test_prohibited_wording_covers_required_risks() -> None:
    prohibited = MODULE.build_prohibited_claims()
    text = " ".join(prohibited["prohibited_wording"].tolist())
    for phrase in ["198/265", "5 km", "10 km", "rho99>1", "SupGP", "Multi-pass", "Direct-S", "all LEO"]:
        assert phrase.lower() in text.lower()


def test_figure_inventory_binds_existing_data_figures() -> None:
    figures = MODULE.build_figure_inventory(ROOT)
    existing = figures[figures["status"].eq("EXISTING_FROZEN")]
    assert len(existing) == 5
    assert existing["sha256"].str.fullmatch(r"[0-9A-F]{64}").all()
    assert set(figures[figures["placement"].eq("MAIN")]["figure_id"]) == {"F0", "F1", "F2", "F3", "F4"}


def test_authoritative_numbers_preserve_analysis_units() -> None:
    numbers = MODULE.build_numbers(load_authoritative()).set_index("metric_id")
    assert numbers.loc["OD_NONZERO_UNITS", "authoritative_value"] == 198
    assert numbers.loc["OD_NONZERO_UNITS", "analysis_unit"] == "LEVEL-A unit"
    assert "not an attack success rate" in numbers.loc["OD_NONZERO_UNITS", "interpretation"]
    assert numbers.loc["REJECT_GATE_K_ONLY", "analysis_unit"] == "observation row"
