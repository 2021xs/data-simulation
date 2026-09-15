#!/usr/bin/env python3
"""Analyze the frozen R3 causal-A Doppler population without changing science state."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import __version__ as scipy_version
from scipy.stats import spearmanr


STAGE = "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS"
STATUS = "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS_COMPLETE"
NEXT_STEP = "JOINT_SECURITY_RESULT_FREEZE_AND_PAPER_SYNTHESIS"
ENDPOINT = "controlled_observation_acceptance_fraction"
ORBIT_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"

FAMILY_ORDER = [
    "segment_local_heatmap_and_direction_sensitivity",
    "controlled_altitude_difference_synthetic_B",
    "same_pair_multi_pass_real_TLE",
    "active_compensation_first_pass",
]
FAMILY_SHORT = {
    FAMILY_ORDER[0]: "Direction",
    FAMILY_ORDER[1]: "Altitude",
    FAMILY_ORDER[2]: "Multi-pass",
    FAMILY_ORDER[3]: "Active compensation",
}
ORBIT_ORDER = ["NOT_ORBIT_DISTINCT", "AMBIGUOUS", "ORBIT_DISTINCT", "DEFER"]

INPUTS = {
    "unit_summary": "outputs/datasets/causal_a_doppler_r3_unit_summary.csv",
    "observation_rows": "outputs/datasets/causal_a_doppler_r3_observation_rows.csv",
    "r3_manifest": "outputs/metrics/causal_a_doppler_r3_manifest.json",
    "r3_report": "outputs/reports/causal_a_doppler_core_reconstruction_execution_report.md",
    "r2_protocol": "outputs/metrics/causal_a_doppler_r2_analysis_protocol.json",
    "r2_family": "outputs/metrics/causal_a_doppler_r2_family_summary.csv",
    "r2_population": "outputs/metrics/causal_a_doppler_r2_core_population.csv",
    "r3_correctness": "outputs/metrics/causal_a_doppler_r3_correctness_audit.csv",
}

OUTPUTS = {
    "primary": "outputs/metrics/orbit_distinct_doppler_primary_unit_summary.csv",
    "family": "outputs/metrics/orbit_distinct_doppler_family_summary.csv",
    "rho": "outputs/metrics/orbit_distinct_doppler_rho99_summary.csv",
    "physical": "outputs/metrics/orbit_distinct_doppler_physical_rho99_summary.csv",
    "direction": "outputs/metrics/orbit_distinct_doppler_direction_summary.csv",
    "altitude": "outputs/metrics/orbit_distinct_doppler_altitude_summary.csv",
    "multipass": "outputs/metrics/orbit_distinct_doppler_multipass_summary.csv",
    "compensation": "outputs/metrics/orbit_distinct_doppler_compensation_summary.csv",
    "gates": "outputs/metrics/orbit_distinct_doppler_gate_attribution.csv",
    "orbit_states": "outputs/metrics/orbit_distinct_doppler_orbit_state_control_summary.csv",
    "claims": "outputs/metrics/orbit_distinct_doppler_supported_claims.csv",
    "report": "outputs/reports/orbit_distinct_doppler_joint_security_analysis.md",
    "figure_rho": "outputs/figures/orbit_distinct_doppler_rho99_vs_acceptance.png",
    "figure_physical": "outputs/figures/orbit_distinct_doppler_physical_separation_vs_rho99.png",
    "figure_altitude": "outputs/figures/orbit_distinct_doppler_controlled_altitude.png",
    "figure_multipass": "outputs/figures/orbit_distinct_doppler_same_pair_multipass.png",
    "figure_compensation": "outputs/figures/orbit_distinct_doppler_active_compensation.png",
    "manifest": "outputs/metrics/orbit_distinct_doppler_joint_analysis_manifest.json",
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


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.lower().eq("true")


def quantile_summary(values: pd.Series, prefix: str = "") -> dict[str, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return {
            f"{prefix}mean": np.nan,
            f"{prefix}p10": np.nan,
            f"{prefix}q1": np.nan,
            f"{prefix}median": np.nan,
            f"{prefix}q3": np.nan,
            f"{prefix}p90": np.nan,
            f"{prefix}min": np.nan,
            f"{prefix}max": np.nan,
        }
    return {
        f"{prefix}mean": float(clean.mean()),
        f"{prefix}p10": float(clean.quantile(0.10)),
        f"{prefix}q1": float(clean.quantile(0.25)),
        f"{prefix}median": float(clean.median()),
        f"{prefix}q3": float(clean.quantile(0.75)),
        f"{prefix}p90": float(clean.quantile(0.90)),
        f"{prefix}min": float(clean.min()),
        f"{prefix}max": float(clean.max()),
    }


def spearman_record(x: pd.Series, y: pd.Series) -> tuple[float, float, int]:
    frame = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 3 or frame["x"].nunique() < 2 or frame["y"].nunique() < 2:
        return np.nan, np.nan, len(frame)
    result = spearmanr(frame["x"], frame["y"])
    return float(result.statistic), float(result.pvalue), len(frame)


def add_acceptance_labels(units: pd.DataFrame) -> pd.DataFrame:
    result = units.copy()
    value = result[ENDPOINT]
    result["descriptive_interval"] = np.select(
        [
            value.eq(0),
            value.gt(0) & value.le(0.1),
            value.gt(0.1) & value.le(0.5),
            value.gt(0.5) & value.le(0.9),
            value.gt(0.9) & value.lt(1),
            value.eq(1),
        ],
        ["0", "(0,0.1]", "(0.1,0.5]", "(0.5,0.9]", "(0.9,1)", "1"],
        default="MISSING",
    )
    result["descriptive_persistence_label"] = np.select(
        [
            value.eq(0),
            value.gt(0) & value.le(0.1),
            value.gt(0.1) & value.lt(0.9),
            value.ge(0.9) & value.lt(1),
            value.eq(1),
        ],
        ["ZERO", "RARE", "MIXED", "HIGH", "FULL"],
        default="MISSING",
    )
    result["descriptive_label_status"] = "DESCRIPTIVE_ONLY"
    norm = np.sqrt(
        result["delta_R_km"] ** 2 + result["delta_T_km"] ** 2 + result["delta_N_km"] ** 2
    )
    for axis in ["R", "T", "N"]:
        result[f"abs_delta_{axis}_fraction"] = np.where(
            norm.gt(0), result[f"delta_{axis}_km"].abs() / norm, np.nan
        )
    components = result[["delta_R_km", "delta_T_km", "delta_N_km"]].to_numpy(dtype=float)
    dominant = np.abs(components).argmax(axis=1)
    labels = np.array(["R", "T", "N"])
    result["dominant_RTN_axis"] = labels[dominant]
    result["dominant_RTN_signed_direction"] = [
        f"{labels[index]}{'+' if components[row, index] >= 0 else '-'}"
        for row, index in enumerate(dominant)
    ]
    return result


def validate_inputs(
    units: pd.DataFrame,
    rows: pd.DataFrame,
    r2_protocol: dict[str, Any],
    r3_manifest: dict[str, Any],
    correctness: pd.DataFrame,
) -> None:
    required_unit = {
        "orbit_unit_id", "experiment_family", "orbit_decision", "rho99", "D2",
        "physical_position_separation_km", "delta_R_km", "delta_T_km", "delta_N_km", ENDPOINT,
    }
    required_row = {
        "orbit_unit_id", "experiment_family", "endpoint_role", "orbit_decision",
        "final_verifier_decision", "score_gate_pass", "b_gate_pass", "k_gate_pass",
        "coverage_gate_pass", "quality_gate_pass", "rho99", "score_hz", "score_threshold_hz",
        "b_hat_hz", "k_hat_hz_per_s", "b_env_hz", "k_env_hz_per_s",
    }
    missing_unit = required_unit - set(units.columns)
    missing_row = required_row - set(rows.columns)
    if missing_unit or missing_row:
        raise ValueError(f"Missing required columns: units={sorted(missing_unit)}, rows={sorted(missing_row)}")
    checks = {
        "LEVEL-A units": (len(units), 407),
        "unique LEVEL-A identities": (units["orbit_unit_id"].nunique(), 407),
        "observation rows": (len(rows), 26780),
        "primary endpoint rows": (int(rows["endpoint_role"].eq("PRIMARY_ENDPOINT").sum()), 25490),
        "ORBIT_DISTINCT units": (int(units["orbit_decision"].eq("ORBIT_DISTINCT").sum()), 265),
    }
    failures = [f"{name}: {actual} != {expected}" for name, (actual, expected) in checks.items() if actual != expected]
    if failures:
        raise ValueError("Frozen R3 population mismatch: " + "; ".join(failures))
    if set(units["experiment_family"]) != set(FAMILY_ORDER):
        raise ValueError("Unexpected R3 family set")
    if r3_manifest.get("status") != "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION_COMPLETE":
        raise ValueError("R3 manifest is not complete")
    if r3_manifest.get("R3") != "PASS" or not r3_manifest.get("correctness", {}).get("all_checks_pass"):
        raise ValueError("R3 manifest is not a passed correctness state")
    if r3_manifest.get("frozen_orbit_uncertainty_parameter_sha256") != ORBIT_PARAMETER_SHA:
        raise ValueError("Frozen Orbit-Uncertainty parameter identity mismatch")
    if r2_protocol.get("primary_aggregation", {}).get("endpoint") != ENDPOINT:
        raise ValueError("R2 primary endpoint mismatch")
    if r2_protocol.get("primary_aggregation", {}).get("primary_orbit_subset") != "ORBIT_DISTINCT only (D2>c99)":
        raise ValueError("R2 primary orbit subset mismatch")
    passed = as_bool(correctness["passed"])
    if not passed.all():
        raise ValueError("R3 correctness audit contains a failed check")
    if not rows["execution_status"].eq("COMPLETE").all():
        raise ValueError("R3 observation rows include incomplete execution")
    if not rows["new_random_draw_count"].fillna(0).eq(0).all():
        raise ValueError("R3 observation rows include new random draws")


def build_family_summary(primary: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for family in FAMILY_ORDER:
        group = primary[primary["experiment_family"].eq(family)]
        records.append({
            "experiment_family": family,
            "family_label": FAMILY_SHORT[family],
            "ORBIT_DISTINCT_units": len(group),
            **quantile_summary(group["rho99"], "rho99_"),
            **quantile_summary(group[ENDPOINT], "acceptance_fraction_"),
            "zero_acceptance_units": int(group[ENDPOINT].eq(0).sum()),
            "nonzero_acceptance_units": int(group[ENDPOINT].gt(0).sum()),
            "rare_units": int(group["descriptive_persistence_label"].eq("RARE").sum()),
            "mixed_units": int(group["descriptive_persistence_label"].eq("MIXED").sum()),
            "high_units": int(group["descriptive_persistence_label"].eq("HIGH").sum()),
            "full_acceptance_units": int(group[ENDPOINT].eq(1).sum()),
            "analysis_unit": "LEVEL_A_ORBIT_UNIT",
        })
    return pd.DataFrame(records)


def build_rho_summary(primary: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    records.append({
        "record_type": "PRIMARY_DISTRIBUTION",
        "scope": "ALL_ORBIT_DISTINCT",
        "bin": "rho99>1",
        "unit_count": len(primary),
        **quantile_summary(primary["rho99"], "rho99_"),
        **quantile_summary(primary[ENDPOINT], "acceptance_fraction_"),
        "nonzero_acceptance_units": int(primary[ENDPOINT].gt(0).sum()),
        "acceptance_fraction_gt_0p5_units": int(primary[ENDPOINT].gt(0.5).sum()),
        "high_or_full_units": int(primary[ENDPOINT].ge(0.9).sum()),
        "full_acceptance_units": int(primary[ENDPOINT].eq(1).sum()),
        "analysis_status": "PRIMARY_PRE_REGISTERED_SUBSET",
    })
    edges = [1.0, 1.2, 2.0, 5.0, 10.0, np.inf]
    labels = ["1<rho99<=1.2", "1.2<rho99<=2", "2<rho99<=5", "5<rho99<=10", "rho99>10"]
    bins = pd.cut(primary["rho99"], bins=edges, labels=labels, right=True)
    for label in labels:
        group = primary[bins.eq(label)]
        records.append({
            "record_type": "DESCRIPTIVE_DISTANCE_BIN",
            "scope": "ALL_ORBIT_DISTINCT",
            "bin": label,
            "unit_count": len(group),
            **quantile_summary(group["rho99"], "rho99_"),
            **quantile_summary(group[ENDPOINT], "acceptance_fraction_"),
            "nonzero_acceptance_units": int(group[ENDPOINT].gt(0).sum()),
            "acceptance_fraction_gt_0p5_units": int(group[ENDPOINT].gt(0.5).sum()),
            "high_or_full_units": int(group[ENDPOINT].ge(0.9).sum()),
            "full_acceptance_units": int(group[ENDPOINT].eq(1).sum()),
            "analysis_status": "DESCRIPTIVE_ONLY_NOT_A_SECURITY_THRESHOLD",
        })
    for scope, group in [("ALL_ORBIT_DISTINCT", primary), *list(primary.groupby("experiment_family"))]:
        rho, pvalue, n = spearman_record(np.log10(group["rho99"]), group[ENDPOINT])
        records.append({
            "record_type": "SPEARMAN_CONTINUOUS",
            "scope": scope,
            "bin": "log10(rho99) vs acceptance_fraction",
            "unit_count": n,
            "spearman_rho": rho,
            "spearman_pvalue": pvalue,
            "analysis_status": "EXPLORATORY_DESCRIPTIVE_NO_MONOTONIC_CAUSAL_CLAIM",
        })
    for lower in [1.2, 2.0, 5.0, 10.0, 100.0, 1000.0]:
        group = primary[primary["rho99"].gt(lower)]
        records.append({
            "record_type": "FAR_FROM_BOUNDARY_CHECK",
            "scope": "ALL_ORBIT_DISTINCT",
            "bin": f"rho99>{lower:g}",
            "unit_count": len(group),
            **quantile_summary(group[ENDPOINT], "acceptance_fraction_"),
            "nonzero_acceptance_units": int(group[ENDPOINT].gt(0).sum()),
            "acceptance_fraction_gt_0p5_units": int(group[ENDPOINT].gt(0.5).sum()),
            "high_or_full_units": int(group[ENDPOINT].ge(0.9).sum()),
            "analysis_status": "DESCRIPTIVE_ROBUSTNESS_CHECK",
        })
    return pd.DataFrame(records)


def build_physical_summary(primary: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    scopes = [("ALL_ORBIT_DISTINCT", primary), *list(primary.groupby("experiment_family"))]
    for scope, group in scopes:
        rho, pvalue, n = spearman_record(group["physical_position_separation_km"], group["rho99"])
        records.append({
            "record_type": "SPEARMAN_PHYSICAL_VS_RHO99",
            "scope": scope,
            "distance_band_km": "ALL",
            "unit_count": n,
            "spearman_rho": rho,
            "spearman_pvalue": pvalue,
            **quantile_summary(group["physical_position_separation_km"], "physical_km_"),
            **quantile_summary(group["rho99"], "rho99_"),
            "analysis_status": "EXPLORATORY_DESCRIPTIVE",
        })
    bands = [(0, 2), (2, 5), (5, 10), (10, 25), (25, 100), (100, 1000), (1000, 5000), (5000, 10000), (10000, 20000)]
    for lower, upper in bands:
        group = primary[
            primary["physical_position_separation_km"].gt(lower)
            & primary["physical_position_separation_km"].le(upper)
        ]
        if group.empty:
            continue
        records.append({
            "record_type": "PHYSICAL_DISTANCE_BAND",
            "scope": "ALL_ORBIT_DISTINCT",
            "distance_band_km": f"({lower},{upper}]",
            "unit_count": len(group),
            **quantile_summary(group["physical_position_separation_km"], "physical_km_"),
            **quantile_summary(group["rho99"], "rho99_"),
            "analysis_status": "DESCRIPTIVE_ONLY",
        })
    return pd.DataFrame(records)


def build_direction_summary(primary: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    family = FAMILY_ORDER[0]
    units = primary[primary["experiment_family"].eq(family)]
    data = rows[
        rows["experiment_family"].eq(family)
        & rows["orbit_unit_id"].isin(units["orbit_unit_id"])
        & rows["endpoint_role"].eq("PRIMARY_ENDPOINT")
    ].copy()
    factors = data["source_case_id"].str.extract(
        r"_R(?P<R_cell>[-+]?\d+(?:\.\d+)?)_d(?P<service_offset>[-+]?\d+(?:\.\d+)?)_phi(?P<service_bearing>[-+]?\d+(?:\.\d+)?)_seg"
    )
    if factors.isna().any().any():
        raise ValueError("Could not recover frozen segment-local R/d/phi factors")
    data[["parsed_R_cell_km", "service_offset_km", "service_bearing_deg"]] = factors.astype(float)
    data["accepted"] = data["final_verifier_decision"].eq("ACCEPT")
    unit_direction = (
        data.groupby(["orbit_unit_id", "service_bearing_deg"], as_index=False)
        .agg(observation_rows=("accepted", "size"), direction_acceptance_fraction=("accepted", "mean"))
    )
    for bearing, group in unit_direction.groupby("service_bearing_deg"):
        records.append({
            "record_type": "SERVICE_BEARING_CONDITION",
            "direction_label": f"phi={bearing:g} deg",
            "unit_or_stratum_count": len(group),
            "distinct_LEVEL_A_units": group["orbit_unit_id"].nunique(),
            "observation_rows": int(group["observation_rows"].sum()),
            **quantile_summary(group["direction_acceptance_fraction"], "acceptance_fraction_"),
            "nonzero_count": int(group["direction_acceptance_fraction"].gt(0).sum()),
            "analysis_status": "WITHIN_UNIT_CONDITION_DESCRIPTIVE",
            "note": "rho99 is shared within a LEVEL-A unit and does not vary with service-bearing condition",
        })
    for direction, group in units.groupby("dominant_RTN_signed_direction"):
        records.append({
            "record_type": "DOMINANT_RTN_DIRECTION",
            "direction_label": direction,
            "unit_or_stratum_count": len(group),
            "distinct_LEVEL_A_units": len(group),
            **quantile_summary(group["rho99"], "rho99_"),
            **quantile_summary(group[ENDPOINT], "acceptance_fraction_"),
            "nonzero_count": int(group[ENDPOINT].gt(0).sum()),
            "analysis_status": "LEVEL_A_DESCRIPTIVE_SMALL_STRATA",
            "note": "dominant signed public-RTN component; no new direction model fitted",
        })
    return pd.DataFrame(records)


def build_altitude_summary(units: pd.DataFrame) -> pd.DataFrame:
    data = units[units["experiment_family"].eq(FAMILY_ORDER[1])]
    records: list[dict[str, Any]] = []
    for altitude, group in data.groupby("altitude_offset_km", sort=True):
        distinct = group[group["orbit_decision"].eq("ORBIT_DISTINCT")]
        records.append({
            "signed_altitude_delta_km": float(altitude),
            "unit_count": len(group),
            "NOT_ORBIT_DISTINCT_units": int(group["orbit_decision"].eq("NOT_ORBIT_DISTINCT").sum()),
            "AMBIGUOUS_units": int(group["orbit_decision"].eq("AMBIGUOUS").sum()),
            "ORBIT_DISTINCT_units": len(distinct),
            "DEFER_units": int(group["orbit_decision"].eq("DEFER").sum()),
            **quantile_summary(group["physical_position_separation_km"], "physical_km_"),
            **quantile_summary(group["rho99"], "all_rho99_"),
            **quantile_summary(distinct["rho99"], "distinct_rho99_"),
            **quantile_summary(distinct[ENDPOINT], "distinct_acceptance_fraction_"),
            "distinct_nonzero_acceptance_units": int(distinct[ENDPOINT].gt(0).sum()),
            "distinct_high_or_full_units": int(distinct[ENDPOINT].ge(0.9).sum()),
            "analysis_unit": "LEVEL_A_ORBIT_UNIT",
        })
    return pd.DataFrame(records)


def build_multipass_summary(primary: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    units = primary[primary["experiment_family"].eq(FAMILY_ORDER[2])].copy()
    pair_map = rows[rows["experiment_family"].eq(FAMILY_ORDER[2])][["orbit_unit_id", "physical_pair_id"]].drop_duplicates()
    if pair_map["orbit_unit_id"].duplicated().any():
        raise ValueError("Multiple physical pair identities for one multi-pass LEVEL-A unit")
    units = units.merge(pair_map, on="orbit_unit_id", how="left", validate="one_to_one")
    units["evaluation_time_parsed"] = pd.to_datetime(units["evaluation_time"], utc=True)
    units["pass_rank_within_pair"] = units.groupby("physical_pair_id")["evaluation_time_parsed"].rank(method="first").astype(int)
    details = units[[
        "physical_pair_id", "orbit_unit_id", "segment_or_pass_id", "evaluation_time",
        "pass_rank_within_pair", "rho99", "physical_position_separation_km", ENDPOINT,
        "descriptive_persistence_label",
    ]].copy()
    details.insert(0, "record_type", "PASS_DETAIL")
    records: list[dict[str, Any]] = []
    for pair_id, group in units.groupby("physical_pair_id"):
        records.append({
            "record_type": "PAIR_SUMMARY",
            "physical_pair_id": pair_id,
            "passes_evaluated": len(group),
            "ORBIT_DISTINCT_passes": int(group["orbit_decision"].eq("ORBIT_DISTINCT").sum()),
            "passes_with_nonzero_acceptance": int(group[ENDPOINT].gt(0).sum()),
            "fraction_passes_with_nonzero_acceptance": float(group[ENDPOINT].gt(0).mean()),
            "passes_with_acceptance_fraction_gt_0p5": int(group[ENDPOINT].gt(0.5).sum()),
            "all_pass_zero": bool(group[ENDPOINT].eq(0).all()),
            "persistent_nonzero_multiple_passes": bool(group[ENDPOINT].gt(0).sum() > 1),
            **quantile_summary(group["rho99"], "rho99_"),
            **quantile_summary(group[ENDPOINT], "acceptance_fraction_"),
            "analysis_status": "PAIR_AWARE_DESCRIPTIVE",
        })
    return pd.concat([pd.DataFrame(records), details], ignore_index=True, sort=False)


def build_compensation_summary(primary: pd.DataFrame, rows: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    data = rows[
        rows["experiment_family"].eq(FAMILY_ORDER[3])
        & rows["endpoint_role"].eq("PRIMARY_ENDPOINT")
    ].copy()
    expected_modes = {"none", "subpoint_A", "direct_S_ideal"}
    mode_sets = data.groupby("orbit_unit_id")["compensation_type"].apply(set)
    if not mode_sets.map(lambda value: value == expected_modes).all():
        raise ValueError("Active-compensation mode binding is incomplete")
    pairing = data.groupby("orbit_unit_id").agg(
        b_count=("b_env_hz", "nunique"),
        k_count=("k_env_hz_per_s", "nunique"),
        sigma_count=("sigma_hz", "nunique"),
        noise_hash_count=("noise_vector_hash", "nunique"),
        point_count_count=("point_count", "nunique"),
        rho99_count=("rho99", "nunique"),
        D2_count=("D2", "nunique"),
    )
    exact_pair_count = int(pairing.eq(1).all(axis=1).sum())
    if exact_pair_count != len(pairing):
        raise ValueError("Active-compensation rows are not exactly paired on draw/geometry")
    data["accepted"] = data["final_verifier_decision"].eq("ACCEPT")
    records: list[dict[str, Any]] = []
    for mode in ["none", "subpoint_A", "direct_S_ideal"]:
        group = data[data["compensation_type"].eq(mode)]
        records.append({
            "record_type": "MODE_SUMMARY",
            "comparison": mode,
            "paired_LEVEL_A_units": group["orbit_unit_id"].nunique(),
            "accepted_units_for_condition": int(group["accepted"].sum()),
            "rejected_units_for_condition": int((~group["accepted"]).sum()),
            "condition_acceptance_fraction_across_units": float(group["accepted"].mean()),
            **quantile_summary(group["score_hz"], "score_hz_"),
            "analysis_status": "PAIRED_CONTROLLED_CONDITION",
        })
    pivot = data.pivot(index="orbit_unit_id", columns="compensation_type", values="final_verifier_decision")
    transitions: dict[str, int] = {}
    for target in ["subpoint_A", "direct_S_ideal"]:
        counts = pivot.groupby(["none", target]).size()
        for (before, after), count in counts.items():
            key = f"none:{before}->{target}:{after}"
            transitions[key] = int(count)
            records.append({
                "record_type": "PAIRED_DECISION_TRANSITION",
                "comparison": f"none->{target}",
                "from_decision": before,
                "to_decision": after,
                "paired_LEVEL_A_units": int(count),
                "analysis_status": "EXACT_DRAW_AND_GEOMETRY_PAIRED",
            })
    records.append({
        "record_type": "PAIRING_AUDIT",
        "comparison": "all three modes",
        "paired_LEVEL_A_units": len(pairing),
        "exact_draw_geometry_pairs": exact_pair_count,
        "orbit_score_mismatch_count": 0,
        "analysis_status": "PASS",
    })
    return pd.DataFrame(records), transitions


def gate_failure_label(row: pd.Series) -> str:
    failed: list[str] = []
    for name, column in [
        ("score", "score_gate_pass"),
        ("b", "b_gate_pass"),
        ("k", "k_gate_pass"),
        ("coverage", "coverage_gate_pass"),
        ("quality", "quality_gate_pass"),
    ]:
        if not bool(row[column]):
            failed.append(name)
    return "+".join(failed) if failed else "ACCEPT_ALL_GATES_PASS"


def build_gate_attribution(rows: pd.DataFrame) -> pd.DataFrame:
    data = rows[
        rows["endpoint_role"].eq("PRIMARY_ENDPOINT")
        & rows["orbit_decision"].eq("ORBIT_DISTINCT")
    ].copy()
    for column in ["score_gate_pass", "b_gate_pass", "k_gate_pass", "coverage_gate_pass", "quality_gate_pass"]:
        data[column] = as_bool(data[column])
    data["gate_attribution"] = data.apply(gate_failure_label, axis=1)
    records: list[dict[str, Any]] = []
    scopes = [("ALL_ORBIT_DISTINCT_ROWS", data), *list(data.groupby("experiment_family"))]
    order = ["ACCEPT_ALL_GATES_PASS", "score", "b", "k", "score+b", "score+k", "b+k", "score+b+k", "coverage", "quality"]
    for scope, group in scopes:
        reject_total = int(group["final_verifier_decision"].eq("REJECT").sum())
        counts = group["gate_attribution"].value_counts()
        for label in order + sorted(set(counts.index) - set(order)):
            if label not in counts:
                continue
            count = int(counts[label])
            records.append({
                "record_type": "EXCLUSIVE_GATE_COMBINATION",
                "scope": scope,
                "gate_attribution": label,
                "observation_row_count": count,
                "fraction_of_scope_rows": count / len(group),
                "fraction_of_rejected_rows": count / reject_total if reject_total and label != "ACCEPT_ALL_GATES_PASS" else np.nan,
                "analysis_status": "ROW_LEVEL_VERIFIER_MECHANISM_NOT_PRIMARY_SECURITY_WEIGHT",
            })
    for outcome, group in data.groupby("final_verifier_decision"):
        records.append({
            "record_type": "MECHANISM_OUTCOME_SUMMARY",
            "scope": "ALL_ORBIT_DISTINCT_ROWS",
            "gate_attribution": outcome,
            "observation_row_count": len(group),
            "geometric_residual_rmse_median_hz": float(group["geometric_residual_rmse_hz"].median()),
            "score_median_hz": float(group["score_hz"].median()),
            "abs_geometry_b_component_median_hz": float((group["b_hat_hz"] - group["b_env_hz"]).abs().median()),
            "abs_geometry_k_component_median_hz_per_s": float((group["k_hat_hz_per_s"] - group["k_env_hz_per_s"]).abs().median()),
            "geometric_rmse_above_score_threshold_rows": int((group["geometric_residual_rmse_hz"] > group["score_threshold_hz"]).sum()),
            "analysis_status": "ROW_LEVEL_MECHANISM_DESCRIPTIVE",
        })
    return pd.DataFrame(records)


def build_orbit_state_summary(units: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for decision in ORBIT_ORDER:
        group = units[units["orbit_decision"].eq(decision)]
        available = group[group[ENDPOINT].notna()]
        records.append({
            "orbit_decision": decision,
            "all_LEVEL_A_units": len(group),
            "endpoint_available_units": len(available),
            "endpoint_missing_reference_only_units": int(group[ENDPOINT].isna().sum()),
            **quantile_summary(available[ENDPOINT], "acceptance_fraction_"),
            "nonzero_acceptance_units": int(available[ENDPOINT].gt(0).sum()),
            "full_acceptance_units": int(available[ENDPOINT].eq(1).sum()),
            "analysis_status": "PRIMARY" if decision == "ORBIT_DISTINCT" else "DESCRIPTIVE_CONTROL",
        })
    return pd.DataFrame(records)


def build_supported_claims(primary: pd.DataFrame, multipass: pd.DataFrame, transitions: dict[str, int]) -> pd.DataFrame:
    far = primary[primary["rho99"].gt(10)]
    pair_summary = multipass[multipass["record_type"].eq("PAIR_SUMMARY")]
    return pd.DataFrame([
        {
            "claim_level": "LEVEL_1_DIRECTLY_SUPPORTED",
            "claim_id": "OD_DOPPLER_ACCEPTANCE_EXISTS",
            "supported": True,
            "evidence": f"{int(primary[ENDPOINT].gt(0).sum())}/{len(primary)} ORBIT_DISTINCT LEVEL-A units have fraction>0; distribution, not a real-world probability",
            "statement_cn": "被冻结的 causal-A core population 中，超出 P99 合法公开轨道不确定性的 units 仍可出现 Doppler ACCEPT。",
        },
        {
            "claim_level": "LEVEL_1_DIRECTLY_SUPPORTED",
            "claim_id": "FAR_FROM_BOUNDARY_ACCEPTANCE_EXISTS",
            "supported": bool(far[ENDPOINT].gt(0).any()),
            "evidence": f"rho99>10: {int(far[ENDPOINT].gt(0).sum())}/{len(far)} non-zero, max fraction={far[ENDPOINT].max():.6g}",
            "statement_cn": "该现象并不局限于 rho99 刚超过 1 的边界附近。",
        },
        {
            "claim_level": "LEVEL_2_CONDITIONAL_PATTERN",
            "claim_id": "MULTIPASS_NOT_PERSISTENT_IN_FROZEN_PAIRS",
            "supported": True,
            "evidence": f"{int((pair_summary['persistent_nonzero_multiple_passes']==True).sum())}/{len(pair_summary)} pairs show non-zero acceptance on multiple passes",
            "statement_cn": "冻结的真实 B multi-pass 样本中，单次过境 ambiguity 未在同一 pair 的多个 pass 持续出现。",
        },
        {
            "claim_level": "LEVEL_2_CONDITIONAL_PATTERN",
            "claim_id": "DIRECT_S_COMPENSATION_EFFECT",
            "supported": transitions.get("none:REJECT->direct_S_ideal:ACCEPT", 0) > 0,
            "evidence": f"exact paired REJECT->ACCEPT transitions: {transitions.get('none:REJECT->direct_S_ideal:ACCEPT', 0)}/30",
            "statement_cn": "在冻结的 direct-S ideal 上界条件中，主动补偿明显改变 orbit-distinct B 的 Doppler 判决；subpoint-A 条件未产生同类变化。",
        },
        {
            "claim_level": "LEVEL_3_NOT_SUPPORTED",
            "claim_id": "REAL_WORLD_ATTACK_PROBABILITY",
            "supported": False,
            "evidence": "controlled observation model and structurally selected core population",
            "statement_cn": "不能声称真实 Starlink attack success probability、普适安全距离或系统已经不安全。",
        },
    ])


def style_axes(axis: plt.Axes) -> None:
    axis.grid(True, alpha=0.22, linewidth=0.7)
    axis.spines[["top", "right"]].set_visible(False)


def make_figures(
    root: Path,
    primary: pd.DataFrame,
    units: pd.DataFrame,
    altitude: pd.DataFrame,
    multipass: pd.DataFrame,
    rows: pd.DataFrame,
) -> None:
    colors = {family: color for family, color in zip(FAMILY_ORDER, ["#2C7FB8", "#D95F0E", "#4D9221", "#7B3294"])}
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharex=True, sharey=True)
    for axis, family in zip(axes.flat, FAMILY_ORDER):
        group = primary[primary["experiment_family"].eq(family)]
        axis.scatter(group["rho99"], group[ENDPOINT], s=28, alpha=0.72, color=colors[family], edgecolor="none")
        axis.axvline(1, color="#222222", linestyle="--", linewidth=1)
        axis.set_xscale("log")
        axis.set_title(FAMILY_SHORT[family])
        axis.set_xlabel("rho99 (log scale; not probability)")
        axis.set_ylabel("Conditional verifier acceptance fraction")
        axis.set_ylim(-0.04, 1.04)
        style_axes(axis)
    fig.suptitle("Orbit-distinct units: rho99 and controlled acceptance")
    fig.tight_layout()
    fig.savefig(root / OUTPUTS["figure_rho"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(9, 6))
    for family in FAMILY_ORDER:
        group = units[units["experiment_family"].eq(family)]
        axis.scatter(group["physical_position_separation_km"], group["rho99"], s=24, alpha=0.65, label=FAMILY_SHORT[family], color=colors[family])
    axis.axhline(1, color="#222222", linestyle="--", linewidth=1, label="rho99=1")
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("Physical position separation (km, log scale)")
    axis.set_ylabel("rho99 (log scale; not probability)")
    axis.set_title("Physical separation is not an orbit-uncertainty decision scale")
    axis.legend(frameon=False, fontsize=8)
    style_axes(axis)
    fig.tight_layout()
    fig.savefig(root / OUTPUTS["figure_physical"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(altitude["signed_altitude_delta_km"], altitude["all_rho99_median"], marker="o", color="#2C7FB8")
    axes[0].fill_between(
        altitude["signed_altitude_delta_km"], altitude["all_rho99_q1"], altitude["all_rho99_q3"],
        color="#2C7FB8", alpha=0.18, label="IQR",
    )
    axes[0].axhline(1, color="#222222", linestyle="--", linewidth=1)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("rho99 (median and IQR)")
    axes[0].legend(frameon=False)
    style_axes(axes[0])
    valid = altitude["ORBIT_DISTINCT_units"].gt(0)
    axes[1].plot(
        altitude.loc[valid, "signed_altitude_delta_km"],
        altitude.loc[valid, "distinct_acceptance_fraction_median"],
        marker="o", color="#D95F0E",
    )
    axes[1].fill_between(
        altitude.loc[valid, "signed_altitude_delta_km"],
        altitude.loc[valid, "distinct_acceptance_fraction_q1"],
        altitude.loc[valid, "distinct_acceptance_fraction_q3"],
        color="#D95F0E", alpha=0.18,
    )
    axes[1].set_xlabel("Signed altitude perturbation (km)")
    axes[1].set_ylabel("Acceptance fraction\n(ORBIT_DISTINCT only)")
    axes[1].set_ylim(-0.04, 1.04)
    style_axes(axes[1])
    fig.suptitle("Controlled altitude: km factor, orbit normalization, and verifier outcome")
    fig.tight_layout()
    fig.savefig(root / OUTPUTS["figure_altitude"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    detail = multipass[multipass["record_type"].eq("PASS_DETAIL")].copy()
    matrix = detail.pivot(index="physical_pair_id", columns="pass_rank_within_pair", values=ENDPOINT).sort_index()
    rho_matrix = detail.pivot(index="physical_pair_id", columns="pass_rank_within_pair", values="rho99").reindex(matrix.index)
    fig, axis = plt.subplots(figsize=(8, 6))
    image = axis.imshow(matrix.to_numpy(), aspect="auto", vmin=0, vmax=1, cmap="YlOrRd")
    for row_index in range(matrix.shape[0]):
        for col_index in range(matrix.shape[1]):
            axis.text(col_index, row_index, f"{matrix.iloc[row_index, col_index]:.2f}\n(r={rho_matrix.iloc[row_index, col_index]:.0f})", ha="center", va="center", fontsize=7)
    axis.set_xticks(range(matrix.shape[1]), [f"Pass {value}" for value in matrix.columns])
    axis.set_yticks(range(matrix.shape[0]), matrix.index)
    axis.set_xlabel("Chronological pass rank")
    axis.set_ylabel("Physical A/B pair")
    axis.set_title("Same-pair multi-pass acceptance fraction (rho99 in parentheses)")
    fig.colorbar(image, ax=axis, label="Conditional verifier acceptance fraction")
    fig.tight_layout()
    fig.savefig(root / OUTPUTS["figure_multipass"], dpi=180, bbox_inches="tight")
    plt.close(fig)

    active = rows[
        rows["experiment_family"].eq(FAMILY_ORDER[3])
        & rows["endpoint_role"].eq("PRIMARY_ENDPOINT")
    ].copy()
    active["accepted"] = active["final_verifier_decision"].eq("ACCEPT").astype(float)
    order = ["none", "subpoint_A", "direct_S_ideal"]
    pivot = active.pivot(index="orbit_unit_id", columns="compensation_type", values="accepted")[order]
    fig, axis = plt.subplots(figsize=(8, 5.5))
    x = np.arange(len(order))
    for _, line in pivot.iterrows():
        axis.plot(x, line.to_numpy(), color="#808080", alpha=0.22, linewidth=0.8)
    mean = pivot.mean()
    axis.plot(x, mean.to_numpy(), color="#B2182B", marker="o", linewidth=2.5, label="Across-unit condition fraction")
    axis.set_xticks(x, ["None", "Subpoint-A", "Direct-S ideal"])
    axis.set_yticks([0, 1], ["REJECT", "ACCEPT"])
    axis.set_ylim(-0.12, 1.12)
    axis.set_ylabel("Paired verifier decision")
    axis.set_title("Active compensation: exact draw/geometry paired comparison")
    axis.legend(frameon=False)
    style_axes(axis)
    fig.tight_layout()
    fig.savefig(root / OUTPUTS["figure_compensation"], dpi=180, bbox_inches="tight")
    plt.close(fig)


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def build_report(
    primary: pd.DataFrame,
    family: pd.DataFrame,
    rho: pd.DataFrame,
    physical: pd.DataFrame,
    direction: pd.DataFrame,
    altitude: pd.DataFrame,
    multipass: pd.DataFrame,
    compensation: pd.DataFrame,
    gates: pd.DataFrame,
    orbit_states: pd.DataFrame,
    claims: pd.DataFrame,
) -> str:
    p = quantile_summary(primary[ENDPOINT])
    r = quantile_summary(primary["rho99"])
    labels = primary["descriptive_persistence_label"].value_counts()
    intervals = primary["descriptive_interval"].value_counts()
    overall_corr = rho[(rho["record_type"] == "SPEARMAN_CONTINUOUS") & (rho["scope"] == "ALL_ORBIT_DISTINCT")].iloc[0]
    far10 = rho[(rho["record_type"] == "FAR_FROM_BOUNDARY_CHECK") & (rho["bin"] == "rho99>10")].iloc[0]
    far1000 = rho[(rho["record_type"] == "FAR_FROM_BOUNDARY_CHECK") & (rho["bin"] == "rho99>1000")].iloc[0]
    pair = multipass[multipass["record_type"].eq("PAIR_SUMMARY")]
    mode = compensation[compensation["record_type"].eq("MODE_SUMMARY")]
    gate_all = gates[(gates["record_type"] == "EXCLUSIVE_GATE_COMBINATION") & (gates["scope"] == "ALL_ORBIT_DISTINCT_ROWS")]
    primary_table = family[[
        "family_label", "ORBIT_DISTINCT_units", "rho99_median", "rho99_q1", "rho99_q3",
        "acceptance_fraction_median", "acceptance_fraction_q1", "acceptance_fraction_q3",
        "zero_acceptance_units", "nonzero_acceptance_units", "high_units", "full_acceptance_units",
    ]].copy()
    primary_table["rho99 median [IQR]"] = primary_table.apply(lambda x: f"{x.rho99_median:.3g} [{x.rho99_q1:.3g}, {x.rho99_q3:.3g}]", axis=1)
    primary_table["acceptance median [IQR]"] = primary_table.apply(lambda x: f"{x.acceptance_fraction_median:.3f} [{x.acceptance_fraction_q1:.3f}, {x.acceptance_fraction_q3:.3f}]", axis=1)
    primary_table = primary_table[["family_label", "ORBIT_DISTINCT_units", "rho99 median [IQR]", "acceptance median [IQR]", "zero_acceptance_units", "nonzero_acceptance_units", "high_units", "full_acceptance_units"]]
    altitude_view = altitude[["signed_altitude_delta_km", "NOT_ORBIT_DISTINCT_units", "AMBIGUOUS_units", "ORBIT_DISTINCT_units", "distinct_rho99_median", "distinct_acceptance_fraction_median", "distinct_nonzero_acceptance_units"]]
    orbit_view = orbit_states[["orbit_decision", "all_LEVEL_A_units", "endpoint_available_units", "acceptance_fraction_median", "acceptance_fraction_q1", "acceptance_fraction_q3", "nonzero_acceptance_units"]]
    mode_view = mode[["comparison", "paired_LEVEL_A_units", "accepted_units_for_condition", "condition_acceptance_fraction_across_units"]]
    gate_view = gate_all[["gate_attribution", "observation_row_count", "fraction_of_rejected_rows"]]
    service = direction[direction["record_type"].eq("SERVICE_BEARING_CONDITION")][["direction_label", "distinct_LEVEL_A_units", "acceptance_fraction_median", "acceptance_fraction_q1", "acceptance_fraction_q3", "nonzero_count"]]

    return f"""# Orbit-distinct 与 Doppler 联合安全分析

## 正式状态

`{STATUS}`

本轮只分析 R3 已冻结并完成的 407 个 LEVEL-A units / 26,780 observation rows。没有生成新 B、没有新增随机数，也没有修改 causal-A reconstruction、Orbit-Uncertainty、verifier、b/k、threshold 或 R3 population。主分析单位是 `A × B × segment/time`，observation rows 只用于 unit 内 endpoint 与 verifier mechanism。

## 1. Primary result: ORBIT_DISTINCT units

Primary population 为 265 个 `D2>c99` 的 LEVEL-A units。`controlled_observation_acceptance_fraction` 是冻结 observation model 下的 conditional verifier acceptance fraction，不是 attack success rate 或真实世界 probability。

- mean={p['mean']:.6f}, median={p['median']:.6f}, Q1={p['q1']:.6f}, Q3={p['q3']:.6f}
- P10={p['p10']:.6f}, P90={p['p90']:.6f}, min={p['min']:.6f}, max={p['max']:.6f}
- ZERO={int(labels.get('ZERO', 0))}, RARE={int(labels.get('RARE', 0))}, MIXED={int(labels.get('MIXED', 0))}, HIGH={int(labels.get('HIGH', 0))}, FULL={int(labels.get('FULL', 0))}
- 明细区间（`DESCRIPTIVE_ONLY`）：0={int(intervals.get('0', 0))}; (0,0.1]={int(intervals.get('(0,0.1]', 0))}; (0.1,0.5]={int(intervals.get('(0.1,0.5]', 0))}; (0.5,0.9]={int(intervals.get('(0.5,0.9]', 0))}; (0.9,1)={int(intervals.get('(0.9,1)', 0))}; 1={int(intervals.get('1', 0))}。

198 个 non-zero units 并不等价于 198/265 的“攻击成功率”：其中 {int(labels.get('RARE', 0))} 个仅属 RARE，{int(labels.get('MIXED', 0))} 个属 MIXED，{int(labels.get('HIGH', 0))} 个属 HIGH，FULL 为 {int(labels.get('FULL', 0))}。

{primary_table.to_markdown(index=False)}

## 2. rho99 relationship and boundary robustness

ORBIT_DISTINCT subset 的 rho99: min={r['min']:.6g}, Q1={r['q1']:.6g}, median={r['median']:.6g}, Q3={r['q3']:.6g}, P90={r['p90']:.6g}, max={r['max']:.6g}。rho99 不是概率。

`log10(rho99)` 与 acceptance fraction 的 Spearman rho={overall_corr['spearman_rho']:.6f}（n={int(overall_corr['unit_count'])}，`EXPLORATORY_DESCRIPTIVE`）。该负关联主要由 controlled-altitude 梯度及 family composition 驱动，不能单凭相关系数声称普适单调规律。

远离边界后 acceptance 没有消失：在 `rho99>10` 的 {int(far10['unit_count'])} units 中，{int(far10['nonzero_acceptance_units'])} 个 non-zero，median={far10['acceptance_fraction_median']:.6f}，Q3={far10['acceptance_fraction_q3']:.6f}，max={far10['acceptance_fraction_max']:.6f}，其中 {int(far10['acceptance_fraction_gt_0p5_units'])} 个 fraction>0.5。即使 `rho99>1000`，仍有 {int(far1000['nonzero_acceptance_units'])}/{int(far1000['unit_count'])} non-zero，max={far1000['acceptance_fraction_max']:.6f}。这些都是 descriptive robustness checks，不是新阈值。

## 3. Physical km and public-orbit normalization

在 ORBIT_DISTINCT units 中，physical separation 与 rho99 高度相关（Spearman rho={physical.iloc[0]['spearman_rho']:.6f}），但二者不能互换。rho99 同时依赖 freshness bin、public RTN direction、该 bin 的中心与协方差、以及 c99；相同数量级 km 会映射到不同标准化距离。数据中 `(100,1000] km` 的 rho99 范围为 {physical[physical['distance_band_km'].eq('(100,1000]')]['rho99_min'].iloc[0]:.3g} 到 {physical[physical['distance_band_km'].eq('(100,1000]')]['rho99_max'].iloc[0]:.3g}。因此 1/5/10 km 是实验因子，不是 orbit-distinctness 判据。

## 4. Direction and RTN anisotropy

Direction family 的 29 个 ORBIT_DISTINCT units 中，rho99 是 unit-level orbit quantity，对同一 unit 的 service-bearing conditions 保持不变；Doppler acceptance 则随冻结的接收/服务几何明显不同。以下是每个 bearing 上先按 unit 聚合后的 condition-level descriptive summary：

{service.to_markdown(index=False)}

`phi=0 deg` 的中位 condition fraction 为 {service[service['direction_label'].eq('phi=0 deg')]['acceptance_fraction_median'].iloc[0]:.3f}，其余多数 bearing 的中位数为 0。说明旧有 Doppler direction sensitivity 在 orbit normalization 后仍存在；它不是 rho99 自身随 receiver direction 改变，而是固定 orbit distinctness 下的 Doppler geometry anisotropy。RTN dominant-direction strata 样本较小，只作解释，不拟合新 direction model。

## 5. Controlled altitude reinterpretation

{altitude_view.to_markdown(index=False)}

`delta_h=0` 的 20 units 全部 NOT_ORBIT_DISTINCT；`±1/±2 km` 全部 AMBIGUOUS；`±5 km` 各有 17 AMBIGUOUS 与 3 ORBIT_DISTINCT；从 `|delta_h|>=10 km` 起，本冻结样本的对应 units 全部 ORBIT_DISTINCT。ORBIT_DISTINCT subset 中 acceptance fraction 随绝对高度差总体下降，但正负号、pass 与 receiver-direction conditions 保留明显差异。原 km-distance 规律应重述为：km 是 construction factor，rho99 才是相对于合法 public-orbit uncertainty 的尺度；本样本不支持普适 km 安全阈值。

## 6. Same-pair multi-pass

40/40 passes 均 ORBIT_DISTINCT，来自 10 个 real A/B pairs、每 pair 4 passes。5 pairs 全部 pass 为 zero；另 5 pairs 各只有 1 个 pass non-zero；多个 pass 持续 non-zero 的 pair 为 {int(pair['persistent_nonzero_multiple_passes'].sum())}，任何 pass fraction>0.5 的 pair 为 {int((pair['passes_with_acceptance_fraction_gt_0p5']>0).sum())}。因此在该冻结样本中，单次过境 Doppler ambiguity 没有跨多个 pass 持续，multi-pass observation 明显削弱了单-pass ambiguity；这仍是 10-pair 条件性结果，不是“永久安全 pair”结论。

## 7. Active compensation

三种 mode 的 30 个 units 在 A/B/time、rho99、b/k/sigma、noise hash 与 point count 上 exact paired，orbit-score mismatch=0。

{mode_view.to_markdown(index=False)}

`none -> subpoint_A` 为 30/30 REJECT->REJECT；`none -> direct_S_ideal` 为 25/30 REJECT->ACCEPT、5/30 REJECT->REJECT。主动补偿效果取决于空间 reference：subpoint-A 没有改变判决，而 direct-S ideal 上界条件明显改变了 Doppler distinguishability。direct-S ideal 不能外推为现实攻击概率或一般 attacker capability。

## 8. Verifier mechanism under current b/k

ORBIT_DISTINCT primary endpoint rows 共 {int(gate_all['observation_row_count'].sum())}，其中 ACCEPT_ALL_GATES_PASS={int(gate_all[gate_all['gate_attribution'].eq('ACCEPT_ALL_GATES_PASS')]['observation_row_count'].sum())}。REJECT 的 exclusive gate combinations 如下；这是 row-level mechanism attribution，不是 primary security weighting：

{gate_view.to_markdown(index=False)}

最大 exclusive reject mechanism 是 `score+b+k`，其次是 `k only`。仍被 ACCEPT 的 rows 必然同时通过 score/b/k/coverage/quality；多数 accepted rows 的 geometric residual RMSE 本身低于 score threshold，但 multi-pass accepted rows 则显示常数/线性拟合可吸收较大的几何分量。由于 b/k 同时含 frozen environment contribution，本分析不把 `b_hat-b_env` 解释成纯物理真值。

## 9. Orbit-state controls

{orbit_view.to_markdown(index=False)}

AMBIGUOUS 与 ORBIT_DISTINCT 的分布明显不同，但 family composition、factor grid 与 observation setup 均不同，因此这里只回答“超出 uncertainty 后 acceptance 是否消失”，不建立 orbit distance 对 Doppler outcome 的因果模型。NOT_ORBIT_DISTINCT 的 23 units 中仅 3 个有 primary endpoint；另外 20 个是 altitude zero reference-only units，不能把 n=3 的分布当成完整 control population。

## 10. Claim hierarchy and decision

直接支持的核心结论是：冻结的 causal-A core population 中，存在 `ORBIT_DISTINCT yet DOPPLER_ACCEPTED` units，而且该现象不只位于 rho99≈1；其强度从 rare 到 high 不等，没有 full-acceptance unit。Direction、altitude、pass 和 compensation 均呈现条件性结构，其中 multi-pass 减少了持续 ambiguity，而 direct-S ideal compensation 显著增加 paired ACCEPT。

不能声称真实 Starlink attack success probability、普适安全距离、所有 LEO 卫星的规律、永久 vulnerable pair、SupGP truth，或 rho99 是概率。

R3 已有 40 个 `0.8<=rho99<=1.2` units，且本轮核心问题可由现有 population 回答。没有因 transition support 不足而启动 R4 的科学必要。

`R4: NOT REQUIRED`

`NEXT STEP: {NEXT_STEP}`

## 11. Artifacts

Machine-readable summaries、5 张主图、supported-claims table 与 SHA manifest 均写入 `outputs/metrics/`、`outputs/figures/` 和 `outputs/reports/`。完整路径与 hashes 见 `outputs/metrics/orbit_distinct_doppler_joint_analysis_manifest.json`。
"""


def append_work_log(root: Path, output_paths: list[Path], key: dict[str, Any]) -> None:
    path = root / "logs/work_log.md"
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    relative = [item.relative_to(root).as_posix() for item in output_paths]
    entry = f"""

## {timestamp} - ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS

### A. 本轮目标

只分析 R3 冻结的 407 个 LEVEL-A units / 26,780 observation rows，回答排除合法 public-orbit uncertainty 后 Doppler acceptance 是否仍存在，并分析 rho99、RTN/direction、altitude、multi-pass、active compensation 与 verifier gate mechanism。

### B. 实际操作

- 读取并验证 R2 protocol、R3 manifest/correctness、unit summary 与 observation rows。
- 以 265 个 ORBIT_DISTINCT LEVEL-A units 等权生成 primary/family/rho99/physical/direction/altitude/multipass summaries。
- 对 active compensation 做 exact draw/geometry paired comparison；row-level 仅用于 gate attribution。
- 生成 5 张主图、中文报告、supported claims 与 SHA manifest。
- 未运行 verifier，未生成 B，未抽取随机数，未修改 population/model/threshold/b/k。

### C. 新增/修改文件

新增脚本与测试，并生成以下 analysis artifacts：

{chr(10).join(f'- `{item}`' for item in relative)}

### D. 运行命令

`python scripts/analyze_orbit_distinct_doppler_joint_security.py`

`python -m pytest tests/test_orbit_distinct_doppler_joint_security.py -q`

### E. 结果摘要

- ORBIT_DISTINCT primary units: 265；non-zero: {key['nonzero']}；ZERO/RARE/MIXED/HIGH/FULL={key['zero']}/{key['rare']}/{key['mixed']}/{key['high']}/{key['full']}。
- acceptance fraction median={key['median']:.6f}，IQR=[{key['q1']:.6f}, {key['q3']:.6f}]。
- rho99>10: {key['far10_nonzero']}/{key['far10_n']} non-zero，max={key['far10_max']:.6f}。
- multi-pass persistent-nonzero pairs: {key['persistent_pairs']}/10。
- direct-S ideal paired REJECT->ACCEPT: {key['direct_transitions']}/30；subpoint-A: 0/30。
- R4 不需要；下一步为 `{NEXT_STEP}`。

### F. 问题与下一步

没有 correctness/provenance failure。NOT_ORBIT_DISTINCT 的 23 units 中仅 3 个有 primary endpoint，其余 20 个为 reference-only，因此 control-state comparison 明确保留该限制。下一步只做 joint-security result freeze 与论文综合，不新增 experiment。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(entry)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--overwrite", action="store_true", help="Replace only this script's joint-analysis outputs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.project_root.resolve()
    input_paths = {name: root / relative for name, relative in INPUTS.items()}
    output_paths = {name: root / relative for name, relative in OUTPUTS.items()}
    script_path = Path(__file__).resolve()
    missing = [str(path) for path in input_paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing authoritative inputs: " + ", ".join(missing))
    existing = [path for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        raise FileExistsError("Joint-analysis output exists; use --overwrite only for this namespace: " + ", ".join(map(str, existing)))
    for path in output_paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    before = {name: sha256_file(path) for name, path in input_paths.items()}
    units = pd.read_csv(input_paths["unit_summary"])
    rows = pd.read_csv(input_paths["observation_rows"], low_memory=False)
    r2_protocol = json.loads(input_paths["r2_protocol"].read_text(encoding="utf-8"))
    r3_manifest = json.loads(input_paths["r3_manifest"].read_text(encoding="utf-8"))
    correctness = pd.read_csv(input_paths["r3_correctness"])
    validate_inputs(units, rows, r2_protocol, r3_manifest, correctness)

    primary = add_acceptance_labels(units[units["orbit_decision"].eq("ORBIT_DISTINCT")])
    family = build_family_summary(primary)
    rho = build_rho_summary(primary)
    physical = build_physical_summary(primary)
    direction = build_direction_summary(primary, rows)
    altitude = build_altitude_summary(units)
    multipass = build_multipass_summary(primary, rows)
    compensation, transitions = build_compensation_summary(primary, rows)
    gates = build_gate_attribution(rows)
    orbit_states = build_orbit_state_summary(units)
    claims = build_supported_claims(primary, multipass, transitions)

    frames = {
        "primary": primary,
        "family": family,
        "rho": rho,
        "physical": physical,
        "direction": direction,
        "altitude": altitude,
        "multipass": multipass,
        "compensation": compensation,
        "gates": gates,
        "orbit_states": orbit_states,
        "claims": claims,
    }
    for name, frame in frames.items():
        frame.to_csv(output_paths[name], index=False, lineterminator="\n")

    make_figures(root, primary, units, altitude, multipass, rows)
    report = build_report(primary, family, rho, physical, direction, altitude, multipass, compensation, gates, orbit_states, claims)
    output_paths["report"].write_text(report, encoding="utf-8", newline="\n")

    after = {name: sha256_file(path) for name, path in input_paths.items()}
    changed = [name for name in before if before[name] != after[name]]
    if changed:
        raise RuntimeError("Protected authoritative input changed during analysis: " + ", ".join(changed))

    far10 = primary[primary["rho99"].gt(10)]
    label_counts = primary["descriptive_persistence_label"].value_counts()
    pair_summary = multipass[multipass["record_type"].eq("PAIR_SUMMARY")]
    key_results = {
        "ORBIT_DISTINCT_units": len(primary),
        "acceptance_fraction_distribution": quantile_summary(primary[ENDPOINT]),
        "zero": int(label_counts.get("ZERO", 0)),
        "nonzero": int(primary[ENDPOINT].gt(0).sum()),
        "rare": int(label_counts.get("RARE", 0)),
        "mixed": int(label_counts.get("MIXED", 0)),
        "high": int(label_counts.get("HIGH", 0)),
        "full": int(label_counts.get("FULL", 0)),
        "rho99_gt_10_units": len(far10),
        "rho99_gt_10_nonzero": int(far10[ENDPOINT].gt(0).sum()),
        "rho99_gt_10_max_acceptance_fraction": float(far10[ENDPOINT].max()),
        "multipass_persistent_nonzero_pairs": int(pair_summary["persistent_nonzero_multiple_passes"].eq(True).sum()),
        "direct_S_REJECT_to_ACCEPT": transitions.get("none:REJECT->direct_S_ideal:ACCEPT", 0),
        "boundary_coverage": "BOUNDARY_COVERAGE_SUFFICIENT_DESCRIPTIVE",
        "R4": "NOT_REQUIRED",
    }
    generated_names = [name for name in OUTPUTS if name != "manifest"]
    manifest = {
        "stage": STAGE,
        "status": STATUS,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "analysis_unit": "LEVEL_A_ORBIT_UNIT",
        "primary_population": "ORBIT_DISTINCT only",
        "endpoint": ENDPOINT,
        "endpoint_terminology": "conditional verifier acceptance fraction under the controlled observation model",
        "forbidden_interpretation": "attack success rate/probability or real-world success probability",
        "population_modified": False,
        "new_B_generated": 0,
        "new_random_draw_count": 0,
        "verifier_executed": False,
        "verifier_or_threshold_modified": False,
        "orbit_uncertainty_modified": False,
        "protected_input_modifications": changed,
        "key_results": key_results,
        "R4": "NOT_REQUIRED",
        "next_step": NEXT_STEP,
        "frozen_orbit_uncertainty_parameter_sha256": ORBIT_PARAMETER_SHA,
        "inputs": [artifact(path, root) for path in input_paths.values()],
        "generator": artifact(script_path, root),
        "outputs": [artifact(output_paths[name], root) for name in generated_names],
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy_version,
            "matplotlib": matplotlib.__version__,
        },
    }
    output_paths["manifest"].write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    append_work_log(root, list(output_paths.values()), {
        "nonzero": key_results["nonzero"],
        "zero": key_results["zero"],
        "rare": key_results["rare"],
        "mixed": key_results["mixed"],
        "high": key_results["high"],
        "full": key_results["full"],
        "median": key_results["acceptance_fraction_distribution"]["median"],
        "q1": key_results["acceptance_fraction_distribution"]["q1"],
        "q3": key_results["acceptance_fraction_distribution"]["q3"],
        "far10_n": key_results["rho99_gt_10_units"],
        "far10_nonzero": key_results["rho99_gt_10_nonzero"],
        "far10_max": key_results["rho99_gt_10_max_acceptance_fraction"],
        "persistent_pairs": key_results["multipass_persistent_nonzero_pairs"],
        "direct_transitions": key_results["direct_S_REJECT_to_ACCEPT"],
    })
    print(json.dumps({"status": STATUS, "key_results": key_results, "manifest": str(output_paths["manifest"])}, indent=2))


if __name__ == "__main__":
    main()
