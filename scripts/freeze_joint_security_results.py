#!/usr/bin/env python3
"""Freeze authoritative joint-security results into paper-facing artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


STAGE = "JOINT_SECURITY_RESULT_FREEZE_AND_PAPER_SYNTHESIS"
STATUS = "JOINT_SECURITY_RESULTS_FROZEN"
NEXT_STEP = "PAPER WRITING / GROUP-MEETING SYNTHESIS"
ORBIT_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"

INPUTS = {
    "orbit_final_report": "outputs/reports/orbit_uncertainty_final_evidence_and_stopping_review.md",
    "orbit_downstream_interface": "outputs/metrics/orbit_uncertainty_final_downstream_interface.json",
    "orbit_final_manifest": "outputs/metrics/orbit_uncertainty_final_manifest.json",
    "orbit_evidence_matrix": "outputs/metrics/orbit_uncertainty_final_evidence_matrix.csv",
    "orbit_stopping_criteria": "outputs/metrics/orbit_uncertainty_final_stopping_criteria.csv",
    "orbit_supported_claims": "outputs/metrics/orbit_uncertainty_final_supported_claims.csv",
    "r1_report": "outputs/reports/causal_a_doppler_reconstruction_reproduction_validation_final_rerun_report.md",
    "r1_manifest": "outputs/metrics/causal_a_doppler_r1_final_manifest.json",
    "r2_report": "outputs/reports/causal_a_doppler_core_reconstruction_design_and_freeze.md",
    "r2_protocol": "outputs/metrics/causal_a_doppler_r2_analysis_protocol.json",
    "r2_family": "outputs/metrics/causal_a_doppler_r2_family_summary.csv",
    "r2_population": "outputs/metrics/causal_a_doppler_r2_core_population.csv",
    "r2_manifest": "outputs/metrics/causal_a_doppler_r2_manifest.json",
    "r3_report": "outputs/reports/causal_a_doppler_core_reconstruction_execution_report.md",
    "r3_manifest": "outputs/metrics/causal_a_doppler_r3_manifest.json",
    "r3_correctness": "outputs/metrics/causal_a_doppler_r3_correctness_audit.csv",
    "joint_report": "outputs/reports/orbit_distinct_doppler_joint_security_analysis.md",
    "joint_manifest": "outputs/metrics/orbit_distinct_doppler_joint_analysis_manifest.json",
    "primary_units": "outputs/metrics/orbit_distinct_doppler_primary_unit_summary.csv",
    "family_summary": "outputs/metrics/orbit_distinct_doppler_family_summary.csv",
    "rho99_summary": "outputs/metrics/orbit_distinct_doppler_rho99_summary.csv",
    "physical_rho99_summary": "outputs/metrics/orbit_distinct_doppler_physical_rho99_summary.csv",
    "direction_summary": "outputs/metrics/orbit_distinct_doppler_direction_summary.csv",
    "altitude_summary": "outputs/metrics/orbit_distinct_doppler_altitude_summary.csv",
    "multipass_summary": "outputs/metrics/orbit_distinct_doppler_multipass_summary.csv",
    "compensation_summary": "outputs/metrics/orbit_distinct_doppler_compensation_summary.csv",
    "gate_attribution": "outputs/metrics/orbit_distinct_doppler_gate_attribution.csv",
    "joint_supported_claims": "outputs/metrics/orbit_distinct_doppler_supported_claims.csv",
}

FIGURE_SOURCES = [
    "outputs/figures/orbit_distinct_doppler_physical_separation_vs_rho99.png",
    "outputs/figures/orbit_distinct_doppler_rho99_vs_acceptance.png",
    "outputs/figures/orbit_distinct_doppler_controlled_altitude.png",
    "outputs/figures/orbit_distinct_doppler_same_pair_multipass.png",
    "outputs/figures/orbit_distinct_doppler_active_compensation.png",
]

OUTPUTS = {
    "numbers": "outputs/metrics/joint_security_final_authoritative_numbers.csv",
    "claim_matrix": "outputs/metrics/joint_security_final_claim_evidence_matrix.csv",
    "supported_claims": "outputs/metrics/joint_security_final_supported_claims.csv",
    "prohibited_claims": "outputs/metrics/joint_security_final_prohibited_claims.csv",
    "figures": "outputs/metrics/joint_security_final_figure_inventory.csv",
    "tables": "outputs/metrics/joint_security_final_table_inventory.csv",
    "limitations": "outputs/metrics/joint_security_final_limitations.csv",
    "terminology": "outputs/metrics/joint_security_final_terminology.csv",
    "report": "outputs/reports/joint_security_final_results_freeze_and_paper_synthesis.md",
    "manifest": "outputs/metrics/joint_security_final_results_manifest.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_bound_manifest(manifest: dict[str, Any], root: Path) -> None:
    mismatches: list[str] = []
    for section in ["inputs", "outputs"]:
        for item in manifest.get(section, []):
            path = root / item["path"]
            if not path.exists() or sha256_file(path) != item["sha256"]:
                mismatches.append(item["path"])
    generator = manifest.get("generator")
    if generator:
        path = root / generator["path"]
        if not path.exists() or sha256_file(path) != generator["sha256"]:
            mismatches.append(generator["path"])
    if mismatches:
        raise ValueError("Authoritative manifest SHA mismatch: " + ", ".join(mismatches))


def number_row(
    metric_id: str,
    value: Any,
    unit: str,
    population: str,
    analysis_unit: str,
    source: str,
    interpretation: str,
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "authoritative_value": value,
        "unit": unit,
        "population": population,
        "analysis_unit": analysis_unit,
        "source_artifact": source,
        "interpretation": interpretation,
    }


def build_numbers(data: dict[str, Any]) -> pd.DataFrame:
    joint = data["joint_manifest"]["key_results"]
    dist = joint["acceptance_fraction_distribution"]
    orbit_evidence = data["orbit_evidence"]
    p99 = orbit_evidence[orbit_evidence["topic"].eq("Untouched June P99")].iloc[0]
    rtn = orbit_evidence[orbit_evidence["topic"].eq("RTN anisotropy")].iloc[0]
    rho = data["rho"]
    corr = rho[(rho["record_type"] == "SPEARMAN_CONTINUOUS") & (rho["scope"] == "ALL_ORBIT_DISTINCT")].iloc[0]
    far10 = rho[(rho["record_type"] == "FAR_FROM_BOUNDARY_CHECK") & (rho["bin"] == "rho99>10")].iloc[0]
    far1000 = rho[(rho["record_type"] == "FAR_FROM_BOUNDARY_CHECK") & (rho["bin"] == "rho99>1000")].iloc[0]
    multipass = data["multipass"]
    pair = multipass[multipass["record_type"].eq("PAIR_SUMMARY")]
    comp = data["compensation"]
    mode = comp[comp["record_type"].eq("MODE_SUMMARY")].set_index("comparison")
    gates = data["gates"]
    gate = gates[(gates["record_type"] == "EXCLUSIVE_GATE_COMBINATION") & (gates["scope"] == "ALL_ORBIT_DISTINCT_ROWS")].set_index("gate_attribution")
    family = data["family"]

    rows = [
        number_row("OU_JUNE_P99_COVERAGE", "5360/5389 = 0.994619", "fraction", "untouched June; 0<age<=36h", "historical evaluation epoch", INPUTS["orbit_evidence_matrix"], p99["interpretation"]),
        number_row("OU_JUNE_P99_CLUSTER_CI", "[0.989915, 0.998530]", "95% satellite-cluster interval", "untouched June", "satellite cluster", INPUTS["orbit_final_report"], "Reference-relative legitimate coverage uncertainty"),
        number_row("OU_RTN_T_DOMINANCE", "April/May/June = 0.962204/0.962094/0.972351", "fraction", "20-satellite Apr-Jun 2026 cohort", "historical evaluation epoch", INPUTS["orbit_evidence_matrix"], rtn["interpretation"]),
        number_row("R1_PRIMARY_REPRODUCTION", "64/64 units; 6280/6280 rows", "count", "semantics-compatible R1 population", "unit and row", INPUTS["r1_report"], "Causal-A wrapper is numerically/scientifically equivalent when A/B semantics are unchanged"),
        number_row("R3_FROZEN_POPULATION", "407 units; 26780 rows", "count", "R3 frozen core", "LEVEL-A unit / observation realization", INPUTS["r3_manifest"], "Rows are within-unit outcomes, not independent orbit cases"),
        number_row("ORBIT_DECISIONS", "23/119/265/0", "NOT_ORBIT_DISTINCT/AMBIGUOUS/ORBIT_DISTINCT/DEFER units", "R3 frozen core", "LEVEL-A unit", INPUTS["r3_manifest"], "Primary security population is the 265 ORBIT_DISTINCT units"),
        number_row("OD_ACCEPTANCE_MEAN", dist["mean"], "fraction", "265 ORBIT_DISTINCT units", "LEVEL-A unit", INPUTS["joint_manifest"], "Conditional verifier acceptance fraction under the controlled observation model"),
        number_row("OD_ACCEPTANCE_MEDIAN_IQR", f"{dist['median']} [{dist['q1']}, {dist['q3']}]", "fraction", "265 ORBIT_DISTINCT units", "LEVEL-A unit", INPUTS["joint_manifest"], "Primary descriptive distribution"),
        number_row("OD_ACCEPTANCE_P10_P90_RANGE", f"P10={dist['p10']}; P90={dist['p90']}; range=[{dist['min']}, {dist['max']}]", "fraction", "265 ORBIT_DISTINCT units", "LEVEL-A unit", INPUTS["joint_manifest"], "Primary descriptive distribution"),
        number_row("OD_ZERO_RARE_MIXED_HIGH_FULL", f"{joint['zero']}/{joint['rare']}/{joint['mixed']}/{joint['high']}/{joint['full']}", "unit count", "265 ORBIT_DISTINCT units", "LEVEL-A unit", INPUTS["joint_manifest"], "Descriptive-only persistence labels"),
        number_row("OD_NONZERO_UNITS", joint["nonzero"], "unit count", "265 ORBIT_DISTINCT units", "LEVEL-A unit", INPUTS["joint_manifest"], "Existence count; 198/265 is not an attack success rate"),
        number_row("RHO99_ACCEPTANCE_SPEARMAN", corr["spearman_rho"], "Spearman rho", "265 ORBIT_DISTINCT units", "LEVEL-A unit", INPUTS["rho99_summary"], "EXPLORATORY_DESCRIPTIVE for log10(rho99) vs conditional acceptance"),
        number_row("RHO99_GT10", f"{int(far10['nonzero_acceptance_units'])}/{int(far10['unit_count'])} non-zero; median={far10['acceptance_fraction_median']}; max={far10['acceptance_fraction_max']}", "unit count and fraction", "rho99>10 descriptive subset", "LEVEL-A unit", INPUTS["rho99_summary"], "Acceptance is lower but does not vanish far beyond rho99=1"),
        number_row("RHO99_GT1000", f"{int(far1000['nonzero_acceptance_units'])}/{int(far1000['unit_count'])} non-zero; median={far1000['acceptance_fraction_median']}; max={far1000['acceptance_fraction_max']}", "unit count and fraction", "rho99>1000 descriptive subset", "LEVEL-A unit", INPUTS["rho99_summary"], "Far-from-boundary descriptive robustness check"),
        number_row("MULTIPASS_PERSISTENCE", f"{int(pair['persistent_nonzero_multiple_passes'].eq(True).sum())}/{len(pair)} pairs", "pair count", "10 real pairs; 40 ORBIT_DISTINCT passes", "physical A/B pair", INPUTS["multipass_summary"], "No pair had non-zero conditional acceptance on multiple studied passes"),
        number_row("ACTIVE_COMPENSATION_ACCEPT", f"none={int(mode.loc['none','accepted_units_for_condition'])}/30; subpoint-A={int(mode.loc['subpoint_A','accepted_units_for_condition'])}/30; direct-S ideal={int(mode.loc['direct_S_ideal','accepted_units_for_condition'])}/30", "paired condition count", "30 ORBIT_DISTINCT real-B units", "paired LEVEL-A condition", INPUTS["compensation_summary"], "Direct-S ideal is an idealized upper-bound condition"),
        number_row("REJECT_GATE_SCORE_B_K", int(gate.loc["score+b+k", "observation_row_count"]), "row count", "ORBIT_DISTINCT primary endpoint rows", "observation row", INPUTS["gate_attribution"], "Largest exclusive row-level reject mechanism; not primary security weighting"),
        number_row("REJECT_GATE_K_ONLY", int(gate.loc["k", "observation_row_count"]), "row count", "ORBIT_DISTINCT primary endpoint rows", "observation row", INPUTS["gate_attribution"], "Second-largest exclusive row-level reject mechanism"),
    ]
    for row in family.itertuples(index=False):
        rows.append(number_row(
            f"FAMILY_{str(row.family_label).upper().replace(' ', '_').replace('-', '_')}",
            f"N={row.ORBIT_DISTINCT_units}; rho99 median[IQR]={row.rho99_median}[{row.rho99_q1},{row.rho99_q3}]; acceptance median[IQR]={row.acceptance_fraction_median}[{row.acceptance_fraction_q1},{row.acceptance_fraction_q3}]; zero/nonzero/high/full={row.zero_acceptance_units}/{row.nonzero_acceptance_units}/{row.high_units}/{row.full_acceptance_units}",
            "LEVEL-A summary", "ORBIT_DISTINCT family subset", "LEVEL-A unit", INPUTS["family_summary"], "Paper primary table row",
        ))
    return pd.DataFrame(rows)


def claim(
    claim_id: str,
    text: str,
    strength: str,
    artifact: str,
    metric: str,
    population: str,
    unit: str,
    scope: str,
    limitation: str,
    allowed: str,
    prohibited: str,
    adjudication: str,
) -> dict[str, str]:
    return {
        "CLAIM_ID": claim_id,
        "claim_text": text,
        "claim_strength": strength,
        "supporting_artifact": artifact,
        "supporting_metric": metric,
        "population": population,
        "analysis_unit": unit,
        "scope": scope,
        "limitation": limitation,
        "allowed_wording": allowed,
        "prohibited_stronger_wording": prohibited,
        "proposed_claim_adjudication": adjudication,
    }


def build_claim_matrix() -> pd.DataFrame:
    return pd.DataFrame([
        claim("C1_ORBIT_DISTINCT_ACCEPTANCE_EXISTS", "在 studied cohort / frozen core population 中，超出 legitimate P99 public-orbit uncertainty 的 candidate B 仍存在 Doppler ACCEPT。", "DIRECTLY_SUPPORTED", INPUTS["primary_units"], "198/265 units have acceptance_fraction>0; ZERO/RARE/MIXED/HIGH/FULL=67/37/156/5/0", "265 ORBIT_DISTINCT units", "LEVEL-A unit", "Frozen causal-A core population", "Controlled observation model; structurally selected core families; not operational prevalence.", "Orbit-distinct yet Doppler-accepted units exist in the frozen causal-A core population.", "198/265 attacks succeed; Starlink attack success rate; Doppler verification is insecure in general.", "SUPPORTED"),
        claim("C2_AMBIGUITY_DECAYS_WITH_RHO99", "Ambiguity 随 uncertainty-normalized orbit separation 增大而明显减弱，但不会在 rho99=1 之外立即消失。", "SUPPORTED_WITH_LIMITATION", INPUTS["rho99_summary"], "Spearman rho=-0.750654; rho99>10 has 75/138 non-zero and median=0.02; rho99>1000 has 36/68 non-zero", "265 ORBIT_DISTINCT units", "LEVEL-A unit", "Exploratory descriptive association", "Association is influenced by controlled-altitude gradient and family composition; no causal or universal monotonic model.", "In the frozen population, acceptance generally decreased with rho99 but persisted well beyond the boundary.", "A universal safe rho99 threshold; rho99 causally determines acceptance; rho99>1 means attack.", "SUPPORTED_WITH_LIMITATION"),
        claim("C3_KM_NOT_ORBIT_GATE", "Physical separation in km cannot replace freshness-conditioned RTN uncertainty-normalized distance.", "DIRECTLY_SUPPORTED", INPUTS["physical_rho99_summary"], "Within (100,1000] km, rho99 ranges 1.97 to 86.2; gate depends on freshness, signed RTN, covariance and c99", "407 frozen LEVEL-A units", "LEVEL-A unit", "Frozen empirical ellipsoid interface", "Model is cohort/time/reference limited.", "Fixed physical distance does not imply fixed orbit distinctness under the frozen uncertainty gate.", "5 km is unsafe; 10 km is safe; a universal kilometer boundary.", "SUPPORTED"),
        claim("C4_DIRECTION_GEOMETRY_EFFECT", "Direction / receiver geometry affects Doppler distinguishability among orbit-distinct cases.", "SUPPORTED_WITH_LIMITATION", INPUTS["direction_summary"], "29 ORBIT_DISTINCT direction units; phi=0 condition median=0.25 while most other bearings have median=0", "29 direction-family ORBIT_DISTINCT units", "LEVEL-A unit with frozen condition strata", "Segment-local direction family", "Condition-level descriptive result; RTN dominant-direction strata are small; no formal hypothesis test.", "Doppler acceptance retained direction and receiver-geometry dependence after orbit normalization in the studied direction family.", "Direction universally determines risk; statistically significant direction law; all constellations share this anisotropy.", "SUPPORTED_WITH_LIMITATION"),
        claim("C5_MULTIPASS_REDUCES_PERSISTENCE", "Studied real-pair multi-pass cases do not show stable cross-pass persistence of single-pass ambiguity.", "SUPPORTED_WITH_LIMITATION", INPUTS["multipass_summary"], "0/10 pairs non-zero on multiple passes; 5 all-zero and 5 exactly one non-zero pass", "10 real pairs / 40 ORBIT_DISTINCT passes", "physical A/B pair", "Frozen same-pair multi-pass family", "Limited pairs/passes and geometry; descriptive repeatability, not a guarantee.", "In the studied real pairs, requiring repeatability across passes reduced single-pass ambiguity.", "Multi-pass guarantees security; these pairs are permanently safe; universal multi-pass acceptance rate.", "SUPPORTED_WITH_LIMITATION"),
        claim("C6_DIRECT_S_IDEAL_BOUND", "Ideal direct-S compensation can substantially weaken single-station Doppler discrimination.", "SUPPORTED_WITH_LIMITATION", INPUTS["compensation_summary"], "Exact paired ACCEPT: none 0/30, subpoint-A 0/30, direct-S ideal 25/30", "30 ORBIT_DISTINCT real-B units", "exact paired LEVEL-A condition", "Frozen active-compensation family", "Direct-S ideal is an idealized receiver-specific upper-bound capability; not operational feasibility.", "The direct-S ideal upper-bound condition changed 25/30 paired decisions from REJECT to ACCEPT, unlike subpoint-A.", "Direct-S compensation is realistic; 25/30 is a real attack success rate; one compensation fools all receivers.", "SUPPORTED_WITH_LIMITATION"),
        claim("OU1_FRESHNESS_CONDITIONING", "Public ordinary-GP disagreement depends statistically on freshness in the studied data.", "SUPPORTED_WITH_LIMITATION", INPUTS["orbit_evidence_matrix"], "April age/norm Spearman=0.479595; June minimum freshness-bin P99=99.2708%", "20 same-shell satellites, Apr-Jun 2026", "historical evaluation epoch", "Supporting uncertainty method", "Not strictly rowwise monotonic; reference-relative disagreement only.", "Element age is a supported conditioning variable for this empirical disagreement scale.", "Every error increases monotonically with age; 36 h is universal validity.", "SUPPORTED_WITH_LIMITATION"),
        claim("OU2_RTN_ANISOTROPY", "Position disagreement shows replicated RTN anisotropy with T dominance.", "DIRECTLY_SUPPORTED", INPUTS["orbit_evidence_matrix"], "T dominance April/May/June=96.2204%/96.2094%/97.2351%", "20 same-shell satellites, Apr-Jun 2026", "historical evaluation epoch", "Supporting uncertainty method", "Cohort/time/reference limited.", "Signed RTN representation retains replicated directional structure omitted by a norm-only sphere.", "Universal Starlink/LEO anisotropy; true covariance.", "SUPPORTED"),
        claim("OU3_UNTOUCHED_JUNE_P99", "Frozen April+May ellipsoid transfers at P99 to untouched June within its support.", "DIRECTLY_SUPPORTED", INPUTS["orbit_evidence_matrix"], "5360/5389=99.4619%; satellite-cluster CI 98.9915%-99.8530%", "Untouched June; 0<age<=36h", "historical evaluation epoch", "Supporting uncertainty validation", "SupGP is higher-quality historical reference, not ground truth; P95 undercoverage remains.", "The frozen empirical P99 gate achieved 99.4619% legitimate reference-relative joint coverage on untouched June.", "99.4619% true-orbit accuracy; attack detection accuracy; P99 is an industry standard.", "SUPPORTED"),
        claim("M1_RECONSTRUCTION_EQUIVALENCE", "Causal-A reconstruction wrapper reuses authoritative verifier science without implementation divergence.", "DIRECTLY_SUPPORTED", INPUTS["r1_report"], "64/64 units and 6280/6280 rows; all categorical mismatches=0; verifier-v2 200/200", "R1 semantics-compatible population", "unit and observation row", "Implementation provenance", "Historical reproduction tolerances are not verifier science thresholds.", "When A/B/time/randomness semantics are fixed, the reconstruction wrapper reproduces authoritative verifier behavior.", "R1 proves new causal-A scientific outcomes equal legacy outcomes.", "SUPPORTED"),
        claim("N1_REAL_WORLD_PROBABILITY", "A real-world attack success probability can be estimated from the frozen controlled population.", "NOT_SUPPORTED", INPUTS["joint_report"], "Controlled observation model and result-blind structural population; unequal family designs", "Frozen core population", "N/A", "Outside evidence scope", "No operational attack sampling model or service scheduling reconstruction.", "No probability wording is allowed.", "Starlink attack success rate = 198/265 or any row-pooled fraction.", "TOO_STRONG"),
    ])


def build_prohibited_claims() -> pd.DataFrame:
    claims = [
        ("P01", "Starlink attack success rate = ...", "No real-world attack sampling distribution was modeled.", "Report unit-level conditional verifier acceptance under the controlled observation model."),
        ("P02", "198/265 attacks succeed", "198 is an existence count over structurally selected units.", "198/265 ORBIT_DISTINCT units had at least one accepted controlled realization."),
        ("P03", "Doppler verification is insecure in general", "Evidence is single-station, cohort-, family-, and period-limited.", "The studied single-station verifier retained ambiguity in part of the frozen population."),
        ("P04", "5 km is unsafe", "km is a construction factor, not the uncertainty gate.", "Some +/-5 km cases crossed the P99 boundary in the studied geometry."),
        ("P05", "10 km is safe", "ORBIT_DISTINCT does not imply Doppler rejection, and no universal km threshold exists.", "All studied +/-10 km cases were orbit-distinct, with non-zero controlled acceptance."),
        ("P06", "rho99>1 means attack", "rho99 is a normalized distance and the decision concerns orbit distinctness only.", "rho99>1 means D2>c99 under the frozen empirical gate."),
        ("P07", "P99 is an aerospace universal standard", "P99 is a preregistered security-design choice for this study.", "Use study-specific empirical P99 gate."),
        ("P08", "SupGP is ground truth", "SupGP is a higher-quality historical reference.", "Use reference-relative public-orbit disagreement."),
        ("P09", "Multi-pass guarantees security", "Only 10 real pairs and four passes per pair were studied.", "No studied pair had non-zero acceptance on multiple passes."),
        ("P10", "Direct-S compensation is realistic", "It is an ideal receiver-specific upper-bound condition.", "Use ideal direct-S compensation bound."),
        ("P11", "These pairs are permanently vulnerable", "Pass dependence was observed and future geometry was not tested.", "Describe pass-specific ambiguity only."),
        ("P12", "All Starlink / all LEO satellites", "Cohort is 20 same-shell Starlink satellites in Apr-Jun 2026.", "State the exact studied cohort and period."),
        ("P13", "99.4619% is true-orbit or attack-detection accuracy", "It is legitimate ordinary-GP disagreement coverage relative to SupGP.", "Use empirical reference-relative joint coverage."),
        ("P14", "0.5381% is an attack false-positive rate", "It is the legitimate false-orbit-distinct rate in June validation.", "Use legitimate false-orbit-distinct rate."),
    ]
    return pd.DataFrame(claims, columns=["prohibited_claim_id", "prohibited_wording", "reason", "required_replacement"])


def build_limitations() -> pd.DataFrame:
    rows = [
        ("L01", "Population", "20-satellite same-shell Starlink cohort near the studied shell", "No universal Starlink or all-LEO extrapolation", "MAIN_TEXT"),
        ("L02", "Time", "April-June 2026 historical period", "No untested season/year extrapolation", "MAIN_TEXT"),
        ("L03", "Reference", "SpaceX-E/SupGP is a higher-quality historical reference", "Not ground truth", "MAIN_TEXT"),
        ("L04", "Orbit support", "0<element_age_hours<=36 h", "Outside support is DEFER; 36 h is not universal validity", "MAIN_TEXT"),
        ("L05", "P99 semantics", "Study-specific preregistered conservative security gate", "Not an aerospace or industry standard", "MAIN_TEXT"),
        ("L06", "Observation model", "Controlled b/k/sigma/noise realizations", "Not an operational or real-world attack distribution", "MAIN_TEXT"),
        ("L07", "Receiver scope", "Single-station claimed-satellite verifier", "No multi-receiver spatial consistency conclusion", "MAIN_TEXT"),
        ("L08", "Scheduling", "Public beam/service scheduling was not reconstructed", "No claim about real service availability or traffic", "MAIN_TEXT"),
        ("L09", "Service center C", "Analytical attack reference", "Not a claimed real beam center", "MAIN_TEXT"),
        ("L10", "Compensation", "Direct-S ideal is an idealized upper-bound condition", "No operational feasibility or multi-receiver generalization", "MAIN_TEXT"),
        ("L11", "Multi-pass", "10 real pairs, four studied passes each", "Conditional repeatability evidence, not a guarantee", "MAIN_TEXT"),
        ("L12", "Execution population", "407 result-blind structurally selected LEVEL-A units across four families", "Not a prevalence sample; family endpoints are heterogeneous", "MAIN_TEXT"),
        ("L13", "NOT_ORBIT_DISTINCT control", "Only 3/23 units had a primary endpoint; 20 were reference-only", "Do not treat n=3 distribution as complete control population", "SUPPLEMENT"),
        ("L14", "P95 calibration", "Untouched June P95=93.6909%, with reference-quality sensitivity", "P99 primary conclusion does not erase P95 undercoverage", "MAIN_TEXT"),
        ("L15", "Temporal dependence", "Out-of-set exceedances cluster; max June U99 episode=18.55 h", "Pointwise coverage is not temporal independence; no maneuver attribution", "MAIN_TEXT"),
        ("L16", "Attack execution", "No real attack was executed", "No real-world success or feasibility claim", "MAIN_TEXT"),
    ]
    return pd.DataFrame(rows, columns=["limitation_id", "topic", "frozen_scope", "required_boundary", "placement"])


def build_terminology() -> pd.DataFrame:
    rows = [
        ("claimed satellite A", "被声明卫星 A", "Claimed identity whose causal public GP drives both orbit and Doppler layers", "target truth satellite"),
        ("candidate/non-target satellite B", "候选/非目标卫星 B", "Real or causally reconstructed synthetic candidate evaluated against A", "attacker success sample"),
        ("causal public orbit prediction", "因果公开轨道预测", "Latest eligible GP with CREATION_DATE<=evaluation_time", "future TLE / best later orbit"),
        ("legitimate public-orbit uncertainty", "合法公开轨道不确定性", "Reference-relative empirical disagreement of causal ordinary GP", "true covariance / ground-truth error"),
        ("Freshness-Conditioned Robust Empirical RTN Ellipsoid", "新鲜度条件化稳健经验 RTN 椭球", "Frozen signed 3D empirical uncertainty gate", "Gaussian truth covariance ellipsoid"),
        ("orbit-distinct", "轨道可区分", "Within support and D2>c99", "attack / malicious / physically impossible"),
        ("uncertainty-normalized orbit distance rho99", "不确定性归一化轨道距离 rho99", "sqrt(D2/c99); boundary at 1", "probability / confidence"),
        ("conditional verifier acceptance fraction", "条件验证器接受比例", "Accepted frozen observation realizations within a LEVEL-A unit", "attack success probability/rate"),
        ("orbit-distinct yet Doppler-accepted", "轨道可区分但 Doppler 被接受", "Security-relevant joint state in this study", "successful real attack"),
        ("single-pass ambiguity", "单次过境模糊性", "Non-zero controlled acceptance in a studied pass", "permanent vulnerability"),
        ("multi-pass repeatability", "跨过境重复性", "Pair-aware persistence across frozen passes", "independent satellite-pair trials"),
        ("ideal direct-S compensation", "理想 direct-S 补偿", "Receiver-specific idealized upper-bound condition", "realistic active compensation"),
        ("effective constant frequency bias", "有效常数频偏", "Registered/effective residual parameter b", "true CFO / CFO ground truth"),
    ]
    return pd.DataFrame(rows, columns=["preferred_english", "preferred_chinese", "definition", "avoid"])


def build_figure_inventory(root: Path) -> pd.DataFrame:
    rows = [
        ("F0", "Method framework schematic", "TO_DRAW_DURING_MANUSCRIPT_LAYOUT", "", "Public causal A -> uncertainty ellipsoid -> orbit decision -> Doppler verifier -> joint state", "MAIN", 1, "Non-data schematic; all semantics are frozen; no new science needed"),
        ("F1", "Physical separation versus rho99", "EXISTING_FROZEN", FIGURE_SOURCES[0], "Fixed km is not fixed uncertainty-normalized orbit distinctness", "MAIN", 2, "Use log-log axes and retain rho99=1 line"),
        ("F2", "rho99 versus conditional verifier acceptance fraction", "EXISTING_FROZEN", FIGURE_SOURCES[1], "Acceptance decreases but persists beyond the P99 boundary", "MAIN", 3, "Four family facets; rho99 is not probability"),
        ("F3", "Controlled altitude", "EXISTING_FROZEN", FIGURE_SOURCES[2], "Connect legacy km factors to rho99 and ORBIT_DISTINCT acceptance", "MAIN", 4, "Retain signed altitude and ORBIT_DISTINCT-only endpoint"),
        ("F4", "Same-pair multi-pass", "EXISTING_FROZEN", FIGURE_SOURCES[3], "Show lack of persistent non-zero ambiguity across studied passes", "MAIN", 5, "Pair-aware; do not count passes as independent pairs"),
        ("F5", "Active compensation", "EXISTING_FROZEN", FIGURE_SOURCES[4], "Exact paired none/subpoint-A/direct-S ideal boundary", "SUPPLEMENT_OR_OPTIONAL_MAIN", 6, "Label direct-S ideal as an upper bound"),
    ]
    frame = pd.DataFrame(rows, columns=["figure_id", "title", "status", "artifact_path", "paper_message", "placement", "priority", "caption_guard"])
    frame["sha256"] = frame["artifact_path"].map(lambda value: sha256_file(root / value) if value else "")
    return frame


def build_table_inventory() -> pd.DataFrame:
    rows = [
        ("T1", "Orbit-Uncertainty external validation summary", INPUTS["orbit_evidence_matrix"], "P99 coverage/CI, P95 limitation, T-dominance, support", "historical evaluation epoch", "MAIN", 1),
        ("T2", "ORBIT_DISTINCT family-level joint result", INPUTS["family_summary"], "Family, unit N, rho99 median[IQR], acceptance median[IQR], zero/non-zero/high/full", "LEVEL-A unit", "MAIN", 2),
        ("T3", "Primary acceptance distribution and far-boundary checks", INPUTS["rho99_summary"], "265-unit distribution, descriptive rho99 bins and Spearman", "LEVEL-A unit", "SUPPLEMENT", 3),
        ("T4", "Claim-evidence and limitations matrix", OUTPUTS["claim_matrix"], "Allowed/prohibited wording with scope and evidence", "claim", "SUPPLEMENT_OR_WRITING_CONTROL", 4),
        ("T5", "Verifier gate attribution", INPUTS["gate_attribution"], "Exclusive reject mechanisms", "observation row", "SUPPLEMENT", 5),
    ]
    return pd.DataFrame(rows, columns=["table_id", "title", "source_artifact", "columns_or_content", "analysis_unit", "placement", "priority"])


def build_supported_claims(claims: pd.DataFrame) -> pd.DataFrame:
    return claims[claims["claim_strength"].isin(["DIRECTLY_SUPPORTED", "SUPPORTED_WITH_LIMITATION", "DESCRIPTIVE_ONLY"])][[
        "CLAIM_ID", "claim_strength", "allowed_wording", "population", "analysis_unit", "limitation", "supporting_artifact", "supporting_metric"
    ]].copy()


def build_report(
    numbers: pd.DataFrame,
    claims: pd.DataFrame,
    prohibited: pd.DataFrame,
    figures: pd.DataFrame,
    tables: pd.DataFrame,
    limitations: pd.DataFrame,
) -> str:
    direct = claims[claims["claim_strength"].eq("DIRECTLY_SUPPORTED")][["CLAIM_ID", "allowed_wording", "supporting_metric"]]
    conditional = claims[claims["claim_strength"].eq("SUPPORTED_WITH_LIMITATION")][["CLAIM_ID", "allowed_wording", "limitation"]]
    proposed = claims[claims["CLAIM_ID"].str.match(r"C[1-6]_")][["CLAIM_ID", "proposed_claim_adjudication", "allowed_wording"]]
    main_figures = figures[figures["placement"].eq("MAIN")][["figure_id", "title", "status", "paper_message"]]
    main_tables = tables[tables["placement"].eq("MAIN")][["table_id", "title", "analysis_unit", "source_artifact"]]
    main_limits = limitations[limitations["placement"].eq("MAIN_TEXT")][["limitation_id", "topic", "frozen_scope", "required_boundary"]]
    key = numbers.set_index("metric_id")["authoritative_value"]
    return f"""# Joint-security final results freeze and paper synthesis

## 正式状态

`JOINT_SECURITY_RESULTS_FROZEN`

`EXPERIMENTAL MAINLINE: COMPLETE`

`ORBIT MODEL OPTIMIZATION: STOPPED`

`DOPPLER PIPELINE OPTIMIZATION: STOPPED`

`R4: NOT REQUIRED`

本文件把已经完成的 Orbit-Uncertainty、causal-A reconstruction 和 joint-security evidence 固化为论文可引用的 numbers、claims、figures、tables、terminology 与 limitations。本轮没有运行新实验、传播新轨道、生成 candidate B、执行 verifier、增加 Monte Carlo、拟合模型或调整阈值。

## 1. Frozen paper question

最终主问题：当 candidate/non-target satellite B 已超出 claimed satellite A 的 legitimate, freshness-conditioned public-orbit prediction uncertainty 后，single-station Doppler claimed-satellite verifier 是否仍存在 ambiguity？

Security-relevant joint state 为 `ORBIT_DISTINCT + DOPPLER_ACCEPTED`。ACCEPT 只表示 controlled observation model 下的 verifier outcome；primary response 是 LEVEL-A unit 内的 `conditional verifier acceptance fraction`，不是 attack success probability。

## 2. Three paper contributions

1. 提出 uncertainty-aware claimed-satellite security evaluation framework，用同一 causal public orbit prediction A 区分 physical separation、legitimate public-orbit uncertainty 与 security-relevant orbit distinctness。
2. 构建并冻结 freshness-conditioned signed 3D RTN empirical uncertainty set；April+May 拟合的 ellipsoid 在 untouched June 的 P99 legitimate reference-relative coverage 为 `{key['OU_JUNE_P99_COVERAGE']}`，satellite-cluster interval 为 `{key['OU_JUNE_P99_CLUSTER_CI']}`。这为 downstream orbit gate 提供 transfer evidence，而不是 ground-truth orbit covariance。
3. 在 result-blind、causal-A-aligned core experiments 中表明：orbit distinctness 不自动产生 Doppler distinguishability；rho99、receiver geometry/direction、pass 与 ideal compensation condition 共同界定 single-station verifier boundary。

贡献 2 是 supporting method，贡献 3 是论文结果主线。Orbit-Uncertainty 建议占 Methods+Results 核心篇幅约 20%-25%，用一个方法小节、一个精简 validation table 和必要的 supplement 支撑，而不展开全部 Stage-1 分支。

## 3. Core frozen numbers

- Orbit gate validation: `{key['OU_JUNE_P99_COVERAGE']}`，cluster interval `{key['OU_JUNE_P99_CLUSTER_CI']}`；April/May/June T-dominance `{key['OU_RTN_T_DOMINANCE']}`。
- Primary joint endpoint: 265 ORBIT_DISTINCT LEVEL-A units；mean `{float(key['OD_ACCEPTANCE_MEAN']):.6f}`，median[IQR] `{key['OD_ACCEPTANCE_MEDIAN_IQR']}`；ZERO/RARE/MIXED/HIGH/FULL=`{key['OD_ZERO_RARE_MIXED_HIGH_FULL']}`。
- Non-zero existence: `{key['OD_NONZERO_UNITS']}/265` units；这不是 attack success rate。
- Far-boundary evidence: rho99>10 为 `{key['RHO99_GT10']}`；rho99>1000 为 `{key['RHO99_GT1000']}`。Acceptance 明显降低但未消失。
- Conditional boundaries: multi-pass persistence `{key['MULTIPASS_PERSISTENCE']}`；active compensation `{key['ACTIVE_COMPENSATION_ACCEPT']}`。

## 4. Proposed claim adjudication

{proposed.to_markdown(index=False)}

Claim 1 和 Claim 3 可直接支持。Claim 2、4、5、6 必须使用 matrix 中的限定措辞；特别是 Spearman 属 `EXPLORATORY_DESCRIPTIVE`，direction 属 condition-level descriptive，multi-pass 只有 10 pairs，direct-S ideal 是 receiver-specific upper bound。

## 5. Claim hierarchy

### Directly supported

{direct.to_markdown(index=False)}

### Supported with limitation

{conditional.to_markdown(index=False)}

`198/265` 只能作为“至少一个 controlled realization 被 ACCEPT 的 unit existence count”。论文强度应由完整 fraction distribution 描述：67 ZERO、37 RARE、156 MIXED、5 HIGH、0 FULL。

## 6. Paper story and section structure

故事线保持单一：physical orbit distance 会混淆 true physical difference 与 legitimate public-orbit prediction uncertainty；frozen empirical RTN ellipsoid 先判定 B 是否真正 orbit-distinct；随后用同一 causal A 驱动 Doppler verifier，并研究 orbit-distinct yet Doppler-accepted joint state。

建议 Results：

1. `5.1 Legitimate public-orbit uncertainty`：只保留 freshness dependence、RTN anisotropy、untouched June P99 transfer 与 P95 limitation。
2. `5.2 From physical separation to orbit distinctness`：展示 km 与 rho99 不等价。
3. `5.3 Doppler distinguishability beyond legitimate orbit uncertainty`：265-unit distribution、rho99 relationship 与 far-boundary checks，作为正文中心。
4. `5.4 Geometry and direction dependence`：controlled altitude 和 service-bearing condition。
5. `5.5 Temporal repeatability across passes`：10-pair / 40-pass pair-aware result。
6. `5.6 Strong compensation boundary`：direct-S ideal upper bound，与 subpoint-A 对照。

Joint-security 应占 Methods+Results+Discussion 的主要篇幅，建议约 55%-65%。Discussion 围绕“orbit-distinctness is necessary for security relevance but insufficient for Doppler distinguishability”展开，而不是继续优化 orbit predictor 或 verifier。

## 7. Figure freeze

{main_figures.to_markdown(index=False)}

F0 是 manuscript layout 阶段根据已冻结 semantics 绘制的非数据 schematic，不需要新实验。F1-F4 已存在并由 joint manifest 绑定。F5 active-compensation 图优先放 supplement；版面允许时可作为第五张正文结果图。

## 8. Table freeze

{main_tables.to_markdown(index=False)}

正文只保留 1-2 张核心表：T1 证明 orbit gate 的支持范围，T2 用 LEVEL-A unit N 汇总四个 family。不要以 26,780 rows 作为 security sample size。

## 9. Frozen limitations

{main_limits.to_markdown(index=False)}

最危险的过度表述是把 `198/265` 或 `25/30 direct-S ideal` 写成 Starlink attack success rate。其次是把 rho99、P99、SupGP 或固定 km 误写为 probability、universal standard、ground truth 或普适安全阈值。完整 prohibited wording 见 `joint_security_final_prohibited_claims.csv`。

## 10. Stop decision

现有 evidence 已回答 frozen main question；R3 transition diagnostic 已是 `BOUNDARY_COVERAGE_SUFFICIENT_DESCRIPTIVE`。没有新的 correctness/provenance issue，也没有阻塞论文撰写的科学缺口。剩余工作是非科学性的 method schematic、caption、正文压缩和组会/论文排版。

`NEW SCIENCE: NOT REQUIRED FOR MAINLINE`

`NEXT STEP: PAPER WRITING / GROUP-MEETING SYNTHESIS`
"""


def append_work_log(root: Path, outputs: list[Path]) -> None:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    paths = "\n".join(f"- `{path.relative_to(root).as_posix()}`" for path in outputs)
    entry = f"""

## {timestamp} - JOINT_SECURITY_RESULT_FREEZE_AND_PAPER_SYNTHESIS

### A. 本轮目标

将 Orbit-Uncertainty、R1-R3 causal-A Doppler reconstruction 与 joint-security analysis 固化为论文可引用的 claims、numbers、figures、tables、limitations、terminology 和章节结构，不开展新实验。

### B. 实际操作

- 验证 Orbit final、R1、R2、R3 与 joint-analysis authoritative states 和 SHA bindings。
- 冻结 265-unit primary endpoint、far-boundary、direction、altitude、multi-pass、compensation 与 gate-attribution 数字。
- 审计六条候选核心 claims，并生成 allowed/prohibited wording。
- 选择已有 joint figures 和核心 tables；没有重算 science 或美化后重新生成数据图。

### C. 新增/修改文件

{paths}

### D. 运行命令

`python scripts/freeze_joint_security_results.py`

`python -m pytest tests/test_joint_security_results_freeze.py -q`

### E. 结果摘要

- `JOINT_SECURITY_RESULTS_FROZEN`
- `EXPERIMENTAL MAINLINE: COMPLETE`
- R4: NOT REQUIRED
- NEW SCIENCE: NOT REQUIRED FOR MAINLINE
- 最强贡献压缩为 uncertainty-aware framework、validated empirical RTN gate、orbit-distinct yet Doppler-accepted boundary 三项。

### F. 问题与下一步

没有 correctness/provenance blocker。下一步仅进入 paper writing / group-meeting synthesis；method schematic 属排版工作，不是科学缺口。
"""
    path = root / "logs/work_log.md"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(entry)


def validate_states(data: dict[str, Any]) -> None:
    expected = [
        (data["orbit_manifest"].get("status"), "ORBIT_UNCERTAINTY_BRANCH_COMPLETE"),
        (data["r1_manifest"].get("status"), "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATED"),
        (data["r2_manifest"].get("status"), "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN"),
        (data["r2_manifest"].get("R2"), "PASS"),
        (data["r3_manifest"].get("status"), "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION_COMPLETE"),
        (data["r3_manifest"].get("R3"), "PASS"),
        (data["joint_manifest"].get("status"), "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS_COMPLETE"),
        (data["joint_manifest"].get("R4"), "NOT_REQUIRED"),
    ]
    failures = [(actual, wanted) for actual, wanted in expected if actual != wanted]
    if failures:
        raise ValueError(f"Authoritative stage-state mismatch: {failures}")
    shas = [
        data["orbit_manifest"].get("frozen_parameter_sha256"),
        data["r1_manifest"].get("frozen_parameter_sha256"),
        data["r2_manifest"].get("orbit_uncertainty_parameter_sha256"),
        data["r3_manifest"].get("frozen_orbit_uncertainty_parameter_sha256"),
        data["joint_manifest"].get("frozen_orbit_uncertainty_parameter_sha256"),
    ]
    if any(value != ORBIT_PARAMETER_SHA for value in shas):
        raise ValueError("Orbit-Uncertainty frozen parameter SHA mismatch")
    key = data["joint_manifest"]["key_results"]
    if key["ORBIT_DISTINCT_units"] != 265 or key["nonzero"] != 198:
        raise ValueError("Joint primary population/result mismatch")
    if len(data["primary"]) != 265 or data["primary"]["orbit_unit_id"].nunique() != 265:
        raise ValueError("Primary unit summary is not exactly 265 unique LEVEL-A units")
    if int(data["family"]["ORBIT_DISTINCT_units"].sum()) != 265:
        raise ValueError("Family summary does not partition the primary population")
    if not data["r3_correctness"]["passed"].astype(str).str.lower().eq("true").all():
        raise ValueError("R3 correctness audit contains failure")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--overwrite", action="store_true", help="Replace only this final-freeze namespace")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.project_root.resolve()
    input_paths = {name: root / path for name, path in INPUTS.items()}
    figure_paths = [root / path for path in FIGURE_SOURCES]
    output_paths = {name: root / path for name, path in OUTPUTS.items()}
    missing = [str(path) for path in [*input_paths.values(), *figure_paths] if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing authoritative artifact: " + ", ".join(missing))
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError("Final-freeze artifact exists; use --overwrite only for this namespace: " + ", ".join(map(str, existing)))
    for path in output_paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    protected = [*input_paths.values(), *figure_paths]
    before = {path: sha256_file(path) for path in protected}
    data = {
        "orbit_manifest": read_json(input_paths["orbit_final_manifest"]),
        "r1_manifest": read_json(input_paths["r1_manifest"]),
        "r2_manifest": read_json(input_paths["r2_manifest"]),
        "r3_manifest": read_json(input_paths["r3_manifest"]),
        "joint_manifest": read_json(input_paths["joint_manifest"]),
        "orbit_evidence": pd.read_csv(input_paths["orbit_evidence_matrix"]),
        "r3_correctness": pd.read_csv(input_paths["r3_correctness"]),
        "primary": pd.read_csv(input_paths["primary_units"]),
        "family": pd.read_csv(input_paths["family_summary"]),
        "rho": pd.read_csv(input_paths["rho99_summary"]),
        "multipass": pd.read_csv(input_paths["multipass_summary"]),
        "compensation": pd.read_csv(input_paths["compensation_summary"]),
        "gates": pd.read_csv(input_paths["gate_attribution"]),
    }
    validate_states(data)
    verify_bound_manifest(data["joint_manifest"], root)

    numbers = build_numbers(data)
    claims = build_claim_matrix()
    supported = build_supported_claims(claims)
    prohibited = build_prohibited_claims()
    figures = build_figure_inventory(root)
    tables = build_table_inventory()
    limitations = build_limitations()
    terminology = build_terminology()
    report = build_report(numbers, claims, prohibited, figures, tables, limitations)

    frames = {
        "numbers": numbers,
        "claim_matrix": claims,
        "supported_claims": supported,
        "prohibited_claims": prohibited,
        "figures": figures,
        "tables": tables,
        "limitations": limitations,
        "terminology": terminology,
    }
    for name, frame in frames.items():
        frame.to_csv(output_paths[name], index=False, lineterminator="\n")
    output_paths["report"].write_text(report, encoding="utf-8", newline="\n")

    changed = [path.relative_to(root).as_posix() for path, digest in before.items() if sha256_file(path) != digest]
    if changed:
        raise RuntimeError("Protected source artifact changed: " + ", ".join(changed))

    output_names = [name for name in OUTPUTS if name != "manifest"]
    source_artifacts = [artifact(path, root) for path in protected]
    canonical_numbers_sha = hashlib.sha256(
        numbers.sort_values("metric_id").to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest().upper()
    manifest = {
        "freeze_name": "JOINT_SECURITY_FINAL_RESULTS_FREEZE",
        "stage": STAGE,
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "experimental_mainline": "COMPLETE",
        "orbit_model_optimization": "STOPPED",
        "doppler_pipeline_optimization": "STOPPED",
        "R4": "NOT_REQUIRED",
        "new_science": "NOT_REQUIRED_FOR_MAINLINE",
        "next_step": NEXT_STEP,
        "paper_question": "For ORBIT_DISTINCT candidate B, does the single-station Doppler claimed-satellite verifier retain ambiguity?",
        "primary_analysis_unit": "LEVEL_A: claimed A x candidate B x segment/time",
        "primary_population": "265 ORBIT_DISTINCT LEVEL-A units",
        "primary_endpoint": "conditional verifier acceptance fraction under the controlled observation model",
        "prohibited_endpoint_interpretation": "attack success probability/rate or real-world success probability",
        "frozen_orbit_uncertainty_parameter_sha256": ORBIT_PARAMETER_SHA,
        "canonical_authoritative_numbers_sha256": canonical_numbers_sha,
        "authoritative_numbers": {row.metric_id: row.authoritative_value for row in numbers.itertuples(index=False)},
        "claim_adjudication": {row.CLAIM_ID: row.proposed_claim_adjudication for row in claims.itertuples(index=False) if row.CLAIM_ID.startswith("C")},
        "main_contributions": [
            "Uncertainty-aware claimed-satellite security evaluation framework",
            "Freshness-conditioned signed 3D RTN empirical gate with untouched temporal validation",
            "Causal-A joint evidence that orbit distinctness does not guarantee Doppler distinguishability",
        ],
        "main_figure_ids": ["F0", "F1", "F2", "F3", "F4"],
        "supplementary_or_optional_figure_ids": ["F5"],
        "main_table_ids": ["T1", "T2"],
        "science_execution_counters": {
            "new_experiment": 0,
            "new_candidate_B": 0,
            "new_random_draw": 0,
            "orbit_propagation": 0,
            "verifier_execution": 0,
            "new_score_or_decision": 0,
            "new_model_fit": 0,
            "threshold_or_bk_change": 0,
            "population_change": 0,
        },
        "protected_source_modifications": changed,
        "sources": source_artifacts,
        "generator": artifact(Path(__file__).resolve(), root),
        "outputs": [artifact(output_paths[name], root) for name in output_names],
        "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
    }
    output_paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    append_work_log(root, list(output_paths.values()))
    print(json.dumps({
        "status": STATUS,
        "experimental_mainline": "COMPLETE",
        "R4": "NOT_REQUIRED",
        "new_science": "NOT_REQUIRED_FOR_MAINLINE",
        "next_step": NEXT_STEP,
        "manifest": str(output_paths["manifest"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
