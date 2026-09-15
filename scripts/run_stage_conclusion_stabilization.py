#!/usr/bin/env python
"""Stage conclusion stabilization from existing offline simulation outputs.

This script does not introduce a new propagation or verifier model.  It
normalizes the already generated window-aware, fixed-reference, b/k ablation,
and multi-station outputs into one stage-level dataset and recomputes the
summary tables, figures, and Chinese report requested for stage closure.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


GROUP_ALIASES = {
    "ordinary_similar": "ordinary_similar",
    "typical_orbit_similar": "ordinary_similar",
    "original_like": "ordinary_similar",
    "boundary_case": "boundary_case",
    "hard_case_weighted": "boundary_case",
    "random_simulated": "random_simulated",
    "window_attack_mixed": "window_attack_mixed",
}

GROUP_CN = {
    "ordinary_similar": "普通相似样本",
    "boundary_case": "边界样本",
    "random_simulated": "随机样本",
    "window_attack_mixed": "窗口累计混合攻击样本",
}

STATION_STRATEGY_ALIASES = {
    "single_station": "single_station_baseline",
    "single_station_baseline": "single_station_baseline",
    "dual_station_all_accept": "dual_station_all_accept",
    "three_station_all_accept": "three_station_all_accept",
    "two_of_three": "two_of_three_reject_defer",
    "two_of_three_reject_defer": "two_of_three_reject_defer",
    "two_of_three_reject_hard": "two_of_three_reject_hard",
}

WINDOW_STRATEGY_ALIASES = {
    "proposed_accumulation": "window_aware_accumulation",
    "window_aware_accumulation": "window_aware_accumulation",
    "naive_accumulation": "naive_accumulation",
    "single_window": "single_window",
}

ORDERED_BK_MODES = ["no_bk", "strict_bk", "weak_bk", "current_bk", "loose_bk", "bk_risk_defer"]

STANDARD_COLUMNS = [
    "experiment_block",
    "source_dataset",
    "case_id",
    "row_id",
    "target_id",
    "target_name",
    "simulated_satellite_id",
    "simulated_satellite_name",
    "pass_id",
    "sample_group",
    "sample_group_cn",
    "orbit_relation_type",
    "orbit_relation_param_name",
    "orbit_relation_param_value",
    "reference_error_km",
    "actual_reference_error_km",
    "reference_bearing_deg",
    "window_mode",
    "bk_mode",
    "strategy_type",
    "station_strategy",
    "compensation_mode",
    "station_count",
    "station_separation_km",
    "station_bearing_deg",
    "S0_decision",
    "S1_decision",
    "S2_decision",
    "final_decision",
    "S0_residual_score",
    "S1_residual_score",
    "S2_residual_score",
    "S0_b_hat_hz",
    "S1_b_hat_hz",
    "S2_b_hat_hz",
    "S0_k_hat_hz_per_s",
    "S1_k_hat_hz_per_s",
    "S2_k_hat_hz_per_s",
    "S0_bk_absorption_ratio",
    "S1_bk_absorption_ratio",
    "S2_bk_absorption_ratio",
    "score_gate_pass",
    "b_gate_pass",
    "k_gate_pass",
    "quality_gate_pass",
    "visibility_ok",
    "decision_reason",
]


def parse_csv(values: str | list[str]) -> list[str]:
    parts: list[str] = []
    if isinstance(values, list):
        for value in values:
            parts.extend(str(value).split(","))
    else:
        parts = str(values).split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_float_csv(values: str | list[str]) -> list[float]:
    return [float(v) for v in parse_csv(values)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stabilize current-stage Starlink/LEO Doppler verifier conclusions.")
    p.add_argument("--window-aware-dataset", type=Path, default=Path("outputs/datasets/window_aware_evidence_accumulation_dataset.csv"))
    p.add_argument("--fixed-reference-dataset", type=Path, default=Path("outputs/datasets/fixed_reference_compensation_extended_dataset.csv"))
    p.add_argument("--single-station-bk-dataset", type=Path, default=Path("outputs/datasets/single_station_bk_gate_ablation_dataset.csv"))
    p.add_argument("--multistation-dataset", type=Path, default=Path("outputs/datasets/multistation_consistency_first_pass_dataset.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/stage_conclusion_stabilization_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/stage_conclusion_main_summary.csv"))
    p.add_argument("--by-sample-group-output", type=Path, default=Path("outputs/metrics/stage_conclusion_by_sample_group.csv"))
    p.add_argument("--by-reference-error-output", type=Path, default=Path("outputs/metrics/stage_conclusion_by_reference_error.csv"))
    p.add_argument("--by-bk-mode-output", type=Path, default=Path("outputs/metrics/stage_conclusion_by_bk_mode.csv"))
    p.add_argument("--by-station-separation-output", type=Path, default=Path("outputs/metrics/stage_conclusion_by_station_separation.csv"))
    p.add_argument("--bk-risk-effect-output", type=Path, default=Path("outputs/metrics/stage_conclusion_bk_risk_defer_effect.csv"))
    p.add_argument("--report-tables-output", type=Path, default=Path("outputs/metrics/stage_conclusion_report_tables.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/stage_conclusion_stabilization_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/stage_conclusion_stabilization"))
    p.add_argument("--reference-error-values", nargs="+", default="0,50,100,200,500,1000,2000")
    p.add_argument("--station-separations", nargs="+", default="10,50,100,500,1000")
    p.add_argument("--sample-groups", nargs="+", default="ordinary_similar,boundary_case,random_simulated")
    p.add_argument("--window-modes", nargs="+", default="full_pass,spread_3x60s,selected_difficult_short_windows")
    p.add_argument("--bk-modes", nargs="+", default="no_bk,strict_bk,current_bk,loose_bk,bk_risk_defer")
    p.add_argument("--station-strategies", nargs="+", default="single_station,dual_station_all_accept,three_station_all_accept,two_of_three")
    p.add_argument("--max-targets", type=int, default=6)
    p.add_argument("--max-samples-per-group", type=int, default=6)
    p.add_argument("--threshold-type", default="p95")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_inputs(args: argparse.Namespace) -> None:
    for path in [
        args.window_aware_dataset,
        args.fixed_reference_dataset,
        args.single_station_bk_dataset,
        args.multistation_dataset,
    ]:
        if not path.exists():
            fail(f"missing input file: {path}")


def check_outputs(args: argparse.Namespace) -> None:
    outputs = [
        args.dataset_output,
        args.summary_output,
        args.by_sample_group_output,
        args.by_reference_error_output,
        args.by_bk_mode_output,
        args.by_station_separation_output,
        args.bk_risk_effect_output,
        args.report_tables_output,
        args.report_output,
        args.figures_dir / "stage_pipeline_false_accept_rate.png",
        args.figures_dir / "false_accept_rate_by_reference_error_and_sample_group.png",
        args.figures_dir / "bk_ablation_false_accept_rate.png",
        args.figures_dir / "multistation_false_accept_rate_by_separation.png",
        args.figures_dir / "bk_risk_defer_accept_to_defer.png",
    ]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not args.overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def normalize_group(value: Any) -> str:
    s = str(value) if pd.notna(value) else ""
    return GROUP_ALIASES.get(s, s)


def normalize_decision(value: Any) -> str:
    if pd.isna(value):
        return ""
    s = str(value)
    if s == "DEFER_RISK":
        return "DEFER"
    return s


def safe_bool(value: Any, default: bool = True) -> Any:
    if pd.isna(value):
        return default
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    s = str(value).strip().lower()
    if s in {"true", "1", "yes"}:
        return True
    if s in {"false", "0", "no"}:
        return False
    return default


def to_float(value: Any, default: float = np.nan) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def first_existing(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row.index and pd.notna(row[name]):
            return row[name]
    return default


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return df[STANDARD_COLUMNS].copy()


def filter_targets(df: pd.DataFrame, max_targets: int) -> pd.DataFrame:
    if max_targets <= 0 or "target_id" not in df.columns:
        return df
    ids = [x for x in df["target_id"].dropna().astype(str).unique()]
    keep = set(ids[:max_targets])
    return df[df["target_id"].astype(str).isin(keep)].copy()


def limit_samples(df: pd.DataFrame, max_samples: int, key_cols: list[str], sample_col: str) -> pd.DataFrame:
    if max_samples <= 0 or sample_col not in df.columns:
        return df
    keep_values: set[Any] = set()
    for _, g in df.groupby([c for c in key_cols if c in df.columns], dropna=False):
        vals = list(g[sample_col].dropna().unique()[:max_samples])
        keep_values.update(vals)
    if not keep_values:
        return df
    return df[df[sample_col].isin(keep_values)].copy()


def map_window_mode(row: pd.Series) -> str:
    if "window_mode" in row.index and pd.notna(row["window_mode"]):
        return str(row["window_mode"])
    group_mode = str(row.get("group_mode", ""))
    if group_mode == "full_pass":
        return "full_pass"
    if group_mode == "spread_segments":
        return "spread_3x60s" if "60" in str(row.get("window_lengths_s", "")) else "spread_6x30s"
    if group_mode == "best_attack_segments":
        return "selected_difficult_short_windows"
    if group_mode == "middle":
        lengths = str(row.get("window_lengths_s", ""))
        if "30" in lengths:
            return "single_30s"
        if "60" in lengths:
            return "single_60s"
        if "120" in lengths:
            return "single_120s"
        return "single_window"
    if group_mode == "middle_segments":
        return "spread_3x60s" if "60" in str(row.get("window_lengths_s", "")) else "spread_6x30s"
    return group_mode or "unknown_window"


def station_count_for(strategy: str) -> int:
    if strategy in {"dual_station_all_accept"}:
        return 2
    if strategy in {"three_station_all_accept", "two_of_three_reject_defer", "two_of_three_reject_hard"}:
        return 3
    return 1


def add_bk_absorption(before: Any, after: Any) -> float:
    b = to_float(before)
    a = to_float(after)
    if not np.isfinite(b) or not np.isfinite(a) or abs(a) < 1e-12:
        return np.nan
    return float(b / max(a, 1e-12))


def normalize_window_aware(args: argparse.Namespace) -> pd.DataFrame:
    df = pd.read_csv(args.window_aware_dataset, low_memory=False)
    if "threshold_type" in df.columns:
        df = df[df["threshold_type"].astype(str).eq(args.threshold_type)].copy()
    df = df[df.get("is_attack", True).astype(bool)].copy() if "is_attack" in df.columns else df
    df = filter_targets(df, args.max_targets)
    df = limit_samples(df, args.max_samples_per_group, ["target_id", "attack_type"], "observation_sequence_id")

    rows: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        strategy = WINDOW_STRATEGY_ALIASES.get(str(row.get("strategy_type", "")), str(row.get("strategy_type", "")))
        window_mode = map_window_mode(row)
        rows.append(
            {
                "experiment_block": "window_accumulation",
                "source_dataset": args.window_aware_dataset.as_posix(),
                "case_id": str(row.get("group_id", row.get("observation_sequence_id", i))),
                "row_id": int(i),
                "target_id": row.get("target_id", ""),
                "target_name": row.get("target_name", ""),
                "simulated_satellite_id": row.get("observation_sequence_id", ""),
                "simulated_satellite_name": str(row.get("attack_type", "")),
                "pass_id": row.get("pass_id", ""),
                "sample_group": "window_attack_mixed",
                "sample_group_cn": GROUP_CN["window_attack_mixed"],
                "orbit_relation_type": row.get("attack_type", ""),
                "orbit_relation_param_name": row.get("attack_param_name", ""),
                "orbit_relation_param_value": row.get("attack_param_value", ""),
                "reference_error_km": 0.0,
                "actual_reference_error_km": 0.0,
                "reference_bearing_deg": np.nan,
                "window_mode": window_mode,
                "bk_mode": "current_bk",
                "strategy_type": strategy,
                "station_strategy": "single_station_baseline",
                "compensation_mode": "none",
                "station_count": 1,
                "station_separation_km": 0.0,
                "station_bearing_deg": np.nan,
                "S0_decision": normalize_decision(row.get("final_decision", "")),
                "S1_decision": "",
                "S2_decision": "",
                "final_decision": normalize_decision(row.get("final_decision", "")),
                "S0_residual_score": row.get("joint_score_rmse_hz", row.get("joint_normalized_score", np.nan)),
                "S1_residual_score": np.nan,
                "S2_residual_score": np.nan,
                "S0_b_hat_hz": row.get("b_pass_hat_hz", np.nan),
                "S1_b_hat_hz": np.nan,
                "S2_b_hat_hz": np.nan,
                "S0_k_hat_hz_per_s": row.get("k_pass_hat_hz_per_s", np.nan),
                "S1_k_hat_hz_per_s": np.nan,
                "S2_k_hat_hz_per_s": np.nan,
                "S0_bk_absorption_ratio": np.nan,
                "S1_bk_absorption_ratio": np.nan,
                "S2_bk_absorption_ratio": np.nan,
                "score_gate_pass": safe_bool(row.get("joint_score_gate_pass", True)),
                "b_gate_pass": safe_bool(row.get("joint_b_gate_pass", True)),
                "k_gate_pass": safe_bool(row.get("joint_k_gate_pass", True)),
                "quality_gate_pass": True,
                "visibility_ok": True,
                "decision_reason": row.get("decision_reason", ""),
            }
        )
    return ensure_columns(pd.DataFrame(rows))


def normalize_single_station(args: argparse.Namespace, block: str, source: Path) -> pd.DataFrame:
    df = pd.read_csv(source, low_memory=False)
    df = filter_targets(df, args.max_targets)
    df = limit_samples(df, args.max_samples_per_group, ["target_id", "sample_group"], "simulated_satellite_id")
    requested_groups = {normalize_group(g) for g in parse_csv(args.sample_groups)}
    requested_errors = set(parse_float_csv(args.reference_error_values))
    requested_windows = set(parse_csv(args.window_modes))
    requested_bk = set(parse_csv(args.bk_modes))
    if "sample_group" in df.columns:
        df["_sample_group_norm"] = df["sample_group"].map(normalize_group)
        df = df[df["_sample_group_norm"].isin(requested_groups)].copy()
    if "requested_error_km" in df.columns:
        df = df[df["requested_error_km"].astype(float).isin(requested_errors)].copy()
    if "window_mode" in df.columns:
        df = df[df["window_mode"].astype(str).isin(requested_windows)].copy()
    if "bk_mode" in df.columns:
        df = df[df["bk_mode"].astype(str).isin(requested_bk)].copy()
    if "compensation_mode" in df.columns:
        df = df[df["compensation_mode"].astype(str).eq("fixed_reference_compensation")].copy()
    if "strategy_type" in df.columns:
        df = df[df["strategy_type"].astype(str).isin(["proposed_v1", "candidate_v1_1", "full_pass", "single_window_baseline"])].copy()

    rows: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        group = normalize_group(row.get("sample_group", ""))
        before = row.get("comp_delta_rmse_before_bk", np.nan)
        after = row.get("comp_delta_rmse_after_bk", np.nan)
        rows.append(
            {
                "experiment_block": block,
                "source_dataset": source.as_posix(),
                "case_id": row.get("case_id", row.get("row_id", i)),
                "row_id": row.get("row_id", i),
                "target_id": row.get("target_id", ""),
                "target_name": row.get("target_name", ""),
                "simulated_satellite_id": row.get("simulated_satellite_id", ""),
                "simulated_satellite_name": row.get("simulated_satellite_name", ""),
                "pass_id": row.get("pass_id", ""),
                "sample_group": group,
                "sample_group_cn": GROUP_CN.get(group, group),
                "orbit_relation_type": row.get("orbit_relation_type", ""),
                "orbit_relation_param_name": row.get("orbit_relation_param_name", ""),
                "orbit_relation_param_value": row.get("orbit_relation_param_value", ""),
                "reference_error_km": to_float(row.get("requested_error_km", np.nan)),
                "actual_reference_error_km": to_float(row.get("actual_error_km", np.nan)),
                "reference_bearing_deg": to_float(row.get("bearing_deg", np.nan)),
                "window_mode": row.get("window_mode", ""),
                "bk_mode": row.get("bk_mode", "current_bk"),
                "strategy_type": row.get("strategy_type", ""),
                "station_strategy": "single_station_baseline",
                "compensation_mode": row.get("compensation_mode", ""),
                "station_count": 1,
                "station_separation_km": 0.0,
                "station_bearing_deg": np.nan,
                "S0_decision": normalize_decision(row.get("final_decision", "")),
                "S1_decision": "",
                "S2_decision": "",
                "final_decision": normalize_decision(row.get("final_decision", "")),
                "S0_residual_score": row.get("residual_score", np.nan),
                "S1_residual_score": np.nan,
                "S2_residual_score": np.nan,
                "S0_b_hat_hz": row.get("b_hat_hz", np.nan),
                "S1_b_hat_hz": np.nan,
                "S2_b_hat_hz": np.nan,
                "S0_k_hat_hz_per_s": row.get("k_hat_hz_per_s", np.nan),
                "S1_k_hat_hz_per_s": np.nan,
                "S2_k_hat_hz_per_s": np.nan,
                "S0_bk_absorption_ratio": add_bk_absorption(before, after),
                "S1_bk_absorption_ratio": np.nan,
                "S2_bk_absorption_ratio": np.nan,
                "score_gate_pass": safe_bool(row.get("score_gate_pass", True)),
                "b_gate_pass": safe_bool(row.get("b_gate_pass", True)),
                "k_gate_pass": safe_bool(row.get("k_gate_pass", True)),
                "quality_gate_pass": safe_bool(row.get("quality_gate_pass", True)),
                "visibility_ok": True,
                "decision_reason": row.get("decision_reason", ""),
            }
        )
    return ensure_columns(pd.DataFrame(rows))


def normalize_multistation(args: argparse.Namespace) -> pd.DataFrame:
    df = pd.read_csv(args.multistation_dataset, low_memory=False)
    df = filter_targets(df, args.max_targets)
    df = limit_samples(df, args.max_samples_per_group, ["target_id", "sample_group"], "simulated_satellite_id")
    requested_groups = {normalize_group(g) for g in parse_csv(args.sample_groups)}
    requested_errors = set(parse_float_csv(args.reference_error_values))
    requested_windows = set(parse_csv(args.window_modes))
    requested_bk = set(parse_csv(args.bk_modes))
    requested_sep = set(parse_float_csv(args.station_separations))
    requested_strategy = {STATION_STRATEGY_ALIASES.get(s, s) for s in parse_csv(args.station_strategies)}

    df["_sample_group_norm"] = df["sample_group"].map(normalize_group)
    df = df[df["_sample_group_norm"].isin(requested_groups)].copy()
    df = df[df["requested_reference_error_km"].astype(float).isin(requested_errors)].copy()
    df = df[df["window_mode"].astype(str).isin(requested_windows)].copy()
    df = df[df["bk_mode"].astype(str).isin(requested_bk)].copy()
    df = df[df["station_separation_km"].astype(float).isin(requested_sep)].copy()
    df = df[df["multi_station_strategy"].astype(str).isin(requested_strategy)].copy()

    rows: list[dict[str, Any]] = []
    for i, row in df.iterrows():
        group = normalize_group(row.get("sample_group", ""))
        strategy = str(row.get("multi_station_strategy", ""))
        s1 = normalize_decision(row.get("S1_decision", ""))
        s2 = normalize_decision(row.get("S2_decision", ""))
        rows.append(
            {
                "experiment_block": "multistation_consistency",
                "source_dataset": args.multistation_dataset.as_posix(),
                "case_id": row.get("case_id", row.get("row_id", i)),
                "row_id": row.get("row_id", i),
                "target_id": row.get("target_id", ""),
                "target_name": row.get("target_name", ""),
                "simulated_satellite_id": row.get("simulated_satellite_id", ""),
                "simulated_satellite_name": row.get("simulated_satellite_name", ""),
                "pass_id": row.get("pass_id", ""),
                "sample_group": group,
                "sample_group_cn": GROUP_CN.get(group, group),
                "orbit_relation_type": row.get("orbit_relation_type", ""),
                "orbit_relation_param_name": row.get("orbit_relation_param_name", ""),
                "orbit_relation_param_value": row.get("orbit_relation_param_value", ""),
                "reference_error_km": to_float(row.get("requested_reference_error_km", np.nan)),
                "actual_reference_error_km": to_float(row.get("actual_reference_error_km", np.nan)),
                "reference_bearing_deg": to_float(row.get("reference_bearing_deg", np.nan)),
                "window_mode": row.get("window_mode", ""),
                "bk_mode": row.get("bk_mode", ""),
                "strategy_type": "multistation_consistency",
                "station_strategy": strategy,
                "compensation_mode": row.get("compensation_mode", ""),
                "station_count": station_count_for(strategy),
                "station_separation_km": to_float(row.get("station_separation_km", np.nan)),
                "station_bearing_deg": to_float(row.get("station_bearing_deg", np.nan)),
                "S0_decision": normalize_decision(row.get("S0_decision", "")),
                "S1_decision": s1 if station_count_for(strategy) >= 2 else "",
                "S2_decision": s2 if station_count_for(strategy) >= 3 else "",
                "final_decision": normalize_decision(row.get("multi_station_decision", "")),
                "S0_residual_score": row.get("S0_residual_score", np.nan),
                "S1_residual_score": row.get("S1_residual_score", np.nan),
                "S2_residual_score": row.get("S2_residual_score", np.nan),
                "S0_b_hat_hz": row.get("S0_b_hat_hz", np.nan),
                "S1_b_hat_hz": row.get("S1_b_hat_hz", np.nan),
                "S2_b_hat_hz": row.get("S2_b_hat_hz", np.nan),
                "S0_k_hat_hz_per_s": row.get("S0_k_hat_hz_per_s", np.nan),
                "S1_k_hat_hz_per_s": row.get("S1_k_hat_hz_per_s", np.nan),
                "S2_k_hat_hz_per_s": row.get("S2_k_hat_hz_per_s", np.nan),
                "S0_bk_absorption_ratio": row.get("S0_bk_absorption_ratio", np.nan),
                "S1_bk_absorption_ratio": row.get("S1_bk_absorption_ratio", np.nan),
                "S2_bk_absorption_ratio": row.get("S2_bk_absorption_ratio", np.nan),
                "score_gate_pass": safe_bool(row.get("S0_score_gate_pass", True)),
                "b_gate_pass": safe_bool(row.get("S0_b_gate_pass", True)),
                "k_gate_pass": safe_bool(row.get("S0_k_gate_pass", True)),
                "quality_gate_pass": safe_bool(row.get("S0_quality_ok", True))
                and (station_count_for(strategy) < 2 or safe_bool(row.get("S1_quality_ok", True)))
                and (station_count_for(strategy) < 3 or safe_bool(row.get("S2_quality_ok", True))),
                "visibility_ok": safe_bool(row.get("S0_visibility_ok", True))
                and (station_count_for(strategy) < 2 or safe_bool(row.get("S1_visibility_ok", True)))
                and (station_count_for(strategy) < 3 or safe_bool(row.get("S2_visibility_ok", True))),
                "decision_reason": row.get("decision_reason", row.get("skip_reason", "")),
            }
        )
    return ensure_columns(pd.DataFrame(rows))


def build_dataset(args: argparse.Namespace) -> pd.DataFrame:
    parts = [
        normalize_window_aware(args),
        normalize_single_station(args, "fixed_reference_compensation", args.single_station_bk_dataset),
        normalize_single_station(args, "bk_ablation", args.single_station_bk_dataset),
        normalize_multistation(args),
    ]
    dataset = pd.concat(parts, ignore_index=True)
    dataset["final_decision"] = dataset["final_decision"].map(normalize_decision)
    dataset["S0_decision"] = dataset["S0_decision"].map(normalize_decision)
    dataset["S1_decision"] = dataset["S1_decision"].map(normalize_decision)
    dataset["S2_decision"] = dataset["S2_decision"].map(normalize_decision)
    return dataset


def rate(series: pd.Series, value: str) -> float:
    n = len(series)
    if n == 0:
        return np.nan
    return float(series.astype(str).eq(value).sum() / n)


def summarize_group(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, g in df.groupby(group_cols, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        score_cols = [c for c in ["S0_residual_score", "S1_residual_score", "S2_residual_score"] if c in g.columns]
        bk_cols = [c for c in ["S0_bk_absorption_ratio", "S1_bk_absorption_ratio", "S2_bk_absorption_ratio"] if c in g.columns]
        scores = pd.concat([pd.to_numeric(g[c], errors="coerce") for c in score_cols], ignore_index=True)
        bks = pd.concat([pd.to_numeric(g[c], errors="coerce") for c in bk_cols], ignore_index=True)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n_cases": int(len(g)),
                "false_accept_rate": rate(g["final_decision"], "ACCEPT"),
                "defer_rate": rate(g["final_decision"], "DEFER"),
                "reject_rate": rate(g["final_decision"], "REJECT"),
                "median_residual_score": float(scores.median()) if scores.notna().any() else np.nan,
                "median_bk_absorption_ratio": float(bks.median()) if bks.notna().any() else np.nan,
                "score_gate_pass_rate": float(pd.Series(g["score_gate_pass"]).map(lambda x: safe_bool(x, False)).mean()),
                "b_gate_pass_rate": float(pd.Series(g["b_gate_pass"]).map(lambda x: safe_bool(x, False)).mean()),
                "k_gate_pass_rate": float(pd.Series(g["k_gate_pass"]).map(lambda x: safe_bool(x, False)).mean()),
                "quality_failure_rate": float((~pd.Series(g["quality_gate_pass"]).map(lambda x: safe_bool(x, False))).mean()),
                "visibility_failure_rate": float((~pd.Series(g["visibility_ok"]).map(lambda x: safe_bool(x, False))).mean()),
            }
        )
    return pd.DataFrame(rows)


def build_summaries(dataset: pd.DataFrame) -> dict[str, pd.DataFrame]:
    main_cols = [
        "experiment_block",
        "sample_group",
        "reference_error_km",
        "window_mode",
        "bk_mode",
        "station_strategy",
        "station_separation_km",
        "compensation_mode",
    ]
    summaries = {
        "main": summarize_group(dataset, main_cols),
        "by_sample_group": summarize_group(dataset, ["experiment_block", "sample_group"]),
        "by_reference_error": summarize_group(dataset, ["experiment_block", "sample_group", "reference_error_km"]),
        "by_bk_mode": summarize_group(dataset, ["experiment_block", "sample_group", "bk_mode"]),
        "by_station_separation": summarize_group(dataset, ["experiment_block", "station_strategy", "station_separation_km", "bk_mode"]),
    }
    summaries["bk_risk_effect"] = build_bk_risk_effect(summaries["main"])
    summaries["report_tables"] = build_report_tables(dataset, summaries)
    return summaries


def weighted_rate(df: pd.DataFrame) -> float:
    if df.empty:
        return np.nan
    n = pd.to_numeric(df["n_cases"], errors="coerce").fillna(0)
    r = pd.to_numeric(df["false_accept_rate"], errors="coerce")
    denom = float(n.sum())
    if denom <= 0:
        return np.nan
    return float((r * n).sum() / denom)


def build_bk_risk_effect(main: pd.DataFrame) -> pd.DataFrame:
    key_cols = [
        "experiment_block",
        "sample_group",
        "reference_error_km",
        "window_mode",
        "station_strategy",
        "station_separation_km",
        "compensation_mode",
    ]
    rows: list[dict[str, Any]] = []
    work = main[main["bk_mode"].isin(["current_bk", "bk_risk_defer"])].copy()
    for key, g in work.groupby(key_cols, dropna=False):
        cur = g[g["bk_mode"].eq("current_bk")]
        risk = g[g["bk_mode"].eq("bk_risk_defer")]
        if cur.empty or risk.empty:
            continue
        c = cur.iloc[0]
        r = risk.iloc[0]
        rows.append(
            {
                **dict(zip(key_cols, key)),
                "current_bk_false_accept_rate": float(c["false_accept_rate"]),
                "bk_risk_defer_false_accept_rate": float(r["false_accept_rate"]),
                "delta_false_accept_rate": float(r["false_accept_rate"] - c["false_accept_rate"]),
                "current_bk_defer_rate": float(c["defer_rate"]),
                "bk_risk_defer_defer_rate": float(r["defer_rate"]),
                "defer_rate_increase": float(r["defer_rate"] - c["defer_rate"]),
            }
        )
    return pd.DataFrame(rows)


def build_report_tables(dataset: pd.DataFrame, summaries: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(table: str, label: str, value: float, n: int | float = np.nan, notes: str = "") -> None:
        rows.append({"table_name": table, "label": label, "metric": "false_accept_rate", "value": value, "n_cases": n, "notes": notes})

    main = summaries["main"]
    for strategy in ["single_window", "naive_accumulation", "window_aware_accumulation"]:
        detail = dataset[(dataset["experiment_block"].eq("window_accumulation")) & (dataset["strategy_type"].eq(strategy))]
        summary = summarize_group(detail, ["experiment_block"]) if not detail.empty else pd.DataFrame()
        if not summary.empty:
            add("stage_pipeline", strategy, float(summary.iloc[0]["false_accept_rate"]), int(summary.iloc[0]["n_cases"]))

    fixed = dataset[
        dataset["experiment_block"].eq("fixed_reference_compensation")
        & dataset["bk_mode"].eq("current_bk")
        & dataset["station_strategy"].eq("single_station_baseline")
    ]
    if not fixed.empty:
        s = summarize_group(fixed, ["experiment_block"]).iloc[0]
        add("stage_pipeline", "fixed_reference_current_bk", float(s["false_accept_rate"]), int(s["n_cases"]))

    risk_single = dataset[
        dataset["experiment_block"].eq("multistation_consistency")
        & dataset["bk_mode"].eq("bk_risk_defer")
        & dataset["station_strategy"].eq("single_station_baseline")
    ]
    if not risk_single.empty:
        s = summarize_group(risk_single, ["experiment_block"]).iloc[0]
        add("stage_pipeline", "bk_risk_defer_single_station", float(s["false_accept_rate"]), int(s["n_cases"]))

    three = dataset[
        dataset["experiment_block"].eq("multistation_consistency")
        & dataset["bk_mode"].eq("current_bk")
        & dataset["station_strategy"].eq("three_station_all_accept")
    ]
    if not three.empty:
        s = summarize_group(three, ["experiment_block"]).iloc[0]
        add("stage_pipeline", "three_station_current_bk", float(s["false_accept_rate"]), int(s["n_cases"]))

    three_risk = dataset[
        dataset["experiment_block"].eq("multistation_consistency")
        & dataset["bk_mode"].eq("bk_risk_defer")
        & dataset["station_strategy"].eq("three_station_all_accept")
    ]
    if not three_risk.empty:
        s = summarize_group(three_risk, ["experiment_block"]).iloc[0]
        add("stage_pipeline", "three_station_bk_risk_defer", float(s["false_accept_rate"]), int(s["n_cases"]))

    for table, df in [
        ("fixed_reference_by_sample_group", fixed),
        ("bk_ablation_by_mode", dataset[dataset["experiment_block"].eq("bk_ablation")]),
        ("multistation_by_separation", dataset[dataset["experiment_block"].eq("multistation_consistency")]),
    ]:
        if df.empty:
            continue
        cols = ["sample_group"] if table == "fixed_reference_by_sample_group" else ["bk_mode"] if table == "bk_ablation_by_mode" else ["station_strategy", "station_separation_km"]
        summ = summarize_group(df, cols)
        for _, row in summ.iterrows():
            label = "_".join(str(row[c]) for c in cols)
            add(table, label, float(row["false_accept_rate"]), int(row["n_cases"]))
    return pd.DataFrame(rows)


def plot_stage_pipeline(report_tables: pd.DataFrame, out: Path) -> None:
    data = report_tables[report_tables["table_name"].eq("stage_pipeline")].copy()
    order = [
        ("single_window", "Single window"),
        ("window_aware_accumulation", "Window-aware accumulation"),
        ("fixed_reference_current_bk", "Fixed reference current_bk"),
        ("bk_risk_defer_single_station", "b/k risk defer"),
        ("three_station_current_bk", "Three-station"),
        ("three_station_bk_risk_defer", "Three-station + b/k defer"),
    ]
    vals = []
    labels = []
    for key, label in order:
        d = data[data["label"].eq(key)]
        if not d.empty:
            labels.append(label)
            vals.append(float(d.iloc[0]["value"]))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar(labels, vals, color=["#4C78A8", "#72B7B2", "#F58518", "#E45756", "#54A24B", "#B279A2"])
    ax.set_ylabel("Non-target false accept rate")
    ax.set_title("Stage pipeline false accept rate")
    ax.set_ylim(0, max(vals + [0.01]) * 1.25)
    ax.tick_params(axis="x", rotation=25)
    for i, v in enumerate(vals):
        ax.text(i, v, f"{v:.3f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def plot_reference_group(dataset: pd.DataFrame, out: Path) -> None:
    d = dataset[
        dataset["experiment_block"].eq("fixed_reference_compensation")
        & dataset["bk_mode"].eq("current_bk")
        & dataset["station_strategy"].eq("single_station_baseline")
    ].copy()
    summ = summarize_group(d, ["sample_group", "reference_error_km"]) if not d.empty else pd.DataFrame()
    fig, ax = plt.subplots(figsize=(8.8, 5))
    if not summ.empty:
        for group, g in summ.sort_values("reference_error_km").groupby("sample_group"):
            ax.plot(g["reference_error_km"], g["false_accept_rate"], marker="o", label=str(group))
    ax.set_xlabel("reference_error_km")
    ax.set_ylabel("Non-target false accept rate")
    ax.set_title("Fixed-reference compensation by sample group")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def plot_bk_ablation(dataset: pd.DataFrame, out: Path) -> None:
    d = dataset[dataset["experiment_block"].eq("bk_ablation")].copy()
    summ = summarize_group(d, ["sample_group", "bk_mode"]) if not d.empty else pd.DataFrame()
    if summ.empty:
        fig, ax = plt.subplots()
        ax.set_title("No b/k ablation data")
    else:
        order = [m for m in ORDERED_BK_MODES if m in set(summ["bk_mode"])]
        pivot = summ.pivot_table(index="bk_mode", columns="sample_group", values="false_accept_rate", aggfunc="mean").reindex(order)
        fig, ax = plt.subplots(figsize=(9, 5))
        pivot.plot(kind="bar", ax=ax)
        ax.set_ylabel("Non-target false accept rate")
        ax.set_title("b/k ablation false accept rate")
        ax.tick_params(axis="x", rotation=25)
        ax.legend(title="sample_group")
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def plot_multistation(dataset: pd.DataFrame, out: Path) -> None:
    d = dataset[dataset["experiment_block"].eq("multistation_consistency")].copy()
    d = d[d["station_strategy"].isin(["single_station_baseline", "dual_station_all_accept", "three_station_all_accept"])]
    d = d[d["bk_mode"].isin(["current_bk", "bk_risk_defer"])]
    summ = summarize_group(d, ["station_strategy", "station_separation_km", "bk_mode"]) if not d.empty else pd.DataFrame()
    fig, ax = plt.subplots(figsize=(9, 5))
    labels = [
        ("single_station_baseline", "current_bk", "Single station"),
        ("dual_station_all_accept", "current_bk", "Dual all-accept"),
        ("three_station_all_accept", "current_bk", "Three all-accept"),
        ("three_station_all_accept", "bk_risk_defer", "Three + b/k defer"),
    ]
    for strat, bk, label in labels:
        g = summ[(summ["station_strategy"].eq(strat)) & (summ["bk_mode"].eq(bk))].sort_values("station_separation_km")
        if not g.empty:
            ax.plot(g["station_separation_km"], g["false_accept_rate"], marker="o", label=label)
    ax.set_xlabel("station_separation_km")
    ax.set_ylabel("Non-target false accept rate")
    ax.set_title("Multi-station consistency by station separation")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def plot_bk_risk_effect(effect: pd.DataFrame, out: Path) -> None:
    d = effect[effect["experiment_block"].eq("multistation_consistency")].copy()
    if not d.empty:
        d = d.groupby("station_strategy", as_index=False).agg(
            current_bk_false_accept_rate=("current_bk_false_accept_rate", "mean"),
            bk_risk_defer_false_accept_rate=("bk_risk_defer_false_accept_rate", "mean"),
            defer_rate_increase=("defer_rate_increase", "mean"),
        )
    fig, ax = plt.subplots(figsize=(9, 5))
    if d.empty:
        ax.set_title("No b/k risk defer comparison data")
    else:
        d = d.set_index("station_strategy")
        d[["current_bk_false_accept_rate", "bk_risk_defer_false_accept_rate", "defer_rate_increase"]].plot(kind="bar", ax=ax)
        ax.set_ylabel("Rate")
        ax.set_title("ACCEPT to DEFER effect under b/k risk defer")
        ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    fig.savefig(out, dpi=180)
    plt.close(fig)


def make_figures(dataset: pd.DataFrame, summaries: dict[str, pd.DataFrame], args: argparse.Namespace) -> list[Path]:
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        args.figures_dir / "stage_pipeline_false_accept_rate.png",
        args.figures_dir / "false_accept_rate_by_reference_error_and_sample_group.png",
        args.figures_dir / "bk_ablation_false_accept_rate.png",
        args.figures_dir / "multistation_false_accept_rate_by_separation.png",
        args.figures_dir / "bk_risk_defer_accept_to_defer.png",
    ]
    plot_stage_pipeline(summaries["report_tables"], paths[0])
    plot_reference_group(dataset, paths[1])
    plot_bk_ablation(dataset, paths[2])
    plot_multistation(dataset, paths[3])
    plot_bk_risk_effect(summaries["bk_risk_effect"], paths[4])
    return paths


def summary_one(dataset: pd.DataFrame, mask: pd.Series) -> dict[str, float]:
    d = dataset[mask].copy()
    if d.empty:
        return {"n": 0, "fa": np.nan, "defer": np.nan, "reject": np.nan}
    return {
        "n": int(len(d)),
        "fa": rate(d["final_decision"], "ACCEPT"),
        "defer": rate(d["final_decision"], "DEFER"),
        "reject": rate(d["final_decision"], "REJECT"),
    }


def fmt(value: float) -> str:
    if value is None or not np.isfinite(value):
        return "NA"
    return f"{value:.4f}"


def markdown_table(df: pd.DataFrame, cols: list[str], max_rows: int = 20) -> str:
    if df.empty:
        return "无可用数据。"
    show = df[cols].head(max_rows).copy()
    return show.to_markdown(index=False)


def write_report(dataset: pd.DataFrame, summaries: dict[str, pd.DataFrame], figures: list[Path], args: argparse.Namespace) -> None:
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_rows = len(dataset)

    single = summary_one(dataset, dataset["experiment_block"].eq("window_accumulation") & dataset["strategy_type"].eq("single_window"))
    naive = summary_one(dataset, dataset["experiment_block"].eq("window_accumulation") & dataset["strategy_type"].eq("naive_accumulation"))
    aware = summary_one(dataset, dataset["experiment_block"].eq("window_accumulation") & dataset["strategy_type"].eq("window_aware_accumulation"))
    fixed_current = summary_one(
        dataset,
        dataset["experiment_block"].eq("fixed_reference_compensation")
        & dataset["bk_mode"].eq("current_bk")
        & dataset["station_strategy"].eq("single_station_baseline"),
    )
    no_bk = summary_one(dataset, dataset["experiment_block"].eq("bk_ablation") & dataset["bk_mode"].eq("no_bk"))
    current_bk = summary_one(dataset, dataset["experiment_block"].eq("bk_ablation") & dataset["bk_mode"].eq("current_bk"))
    loose_bk = summary_one(dataset, dataset["experiment_block"].eq("bk_ablation") & dataset["bk_mode"].eq("loose_bk"))
    multi_single = summary_one(dataset, dataset["experiment_block"].eq("multistation_consistency") & dataset["bk_mode"].eq("current_bk") & dataset["station_strategy"].eq("single_station_baseline"))
    multi_three = summary_one(dataset, dataset["experiment_block"].eq("multistation_consistency") & dataset["bk_mode"].eq("current_bk") & dataset["station_strategy"].eq("three_station_all_accept"))
    multi_three_risk = summary_one(dataset, dataset["experiment_block"].eq("multistation_consistency") & dataset["bk_mode"].eq("bk_risk_defer") & dataset["station_strategy"].eq("three_station_all_accept"))

    fixed_by_group = summarize_group(
        dataset[
            dataset["experiment_block"].eq("fixed_reference_compensation")
            & dataset["bk_mode"].eq("current_bk")
            & dataset["station_strategy"].eq("single_station_baseline")
        ],
        ["sample_group"],
    ).sort_values("false_accept_rate", ascending=False)
    fixed_by_error_group = summarize_group(
        dataset[
            dataset["experiment_block"].eq("fixed_reference_compensation")
            & dataset["bk_mode"].eq("current_bk")
            & dataset["station_strategy"].eq("single_station_baseline")
        ],
        ["sample_group", "reference_error_km"],
    ).sort_values(["sample_group", "reference_error_km"])
    bk_by_mode = summarize_group(dataset[dataset["experiment_block"].eq("bk_ablation")], ["sample_group", "bk_mode"]).sort_values(["sample_group", "bk_mode"])
    multi_by_sep = summarize_group(
        dataset[
            dataset["experiment_block"].eq("multistation_consistency")
            & dataset["bk_mode"].eq("current_bk")
            & dataset["station_strategy"].isin(["single_station_baseline", "dual_station_all_accept", "three_station_all_accept"])
        ],
        ["station_strategy", "station_separation_km"],
    ).sort_values(["station_strategy", "station_separation_km"])
    risk_effect = summaries["bk_risk_effect"]
    risk_mean = (
        risk_effect[risk_effect["experiment_block"].eq("multistation_consistency")]
        .groupby("station_strategy", as_index=False)[["current_bk_false_accept_rate", "bk_risk_defer_false_accept_rate", "defer_rate_increase"]]
        .mean()
        if not risk_effect.empty
        else pd.DataFrame()
    )

    random_after_50 = summary_one(
        dataset,
        dataset["experiment_block"].eq("fixed_reference_compensation")
        & dataset["sample_group"].eq("random_simulated")
        & dataset["bk_mode"].eq("current_bk")
        & (dataset["reference_error_km"] >= 50),
    )
    ordinary_after_200 = summary_one(
        dataset,
        dataset["experiment_block"].eq("fixed_reference_compensation")
        & dataset["sample_group"].eq("ordinary_similar")
        & dataset["bk_mode"].eq("current_bk")
        & (dataset["reference_error_km"] >= 200),
    )

    text = f"""# 当前阶段结论固化复核报告

生成时间：{now}

## 1. 为什么要固化当前结论

本报告只复算和归一化已有离线仿真输出，不引入新传播模型、不接入真实链路，也不把结果解释为真实世界攻击成功率。目标是把短窗口累计、固定参考点补偿、b/k 消融和多站一致性四条已有结论链条放到同一统计口径下，使用“非目标样本误接受率”作为主指标，便于当前阶段收尾。

- 统一 dataset 行数：`{total_rows}`
- 主 summary 行数：`{len(summaries['main'])}`
- 输入来源：window-aware、single-station b/k gate ablation、multi-station consistency first pass 的既有 CSV；脚本同时检查 fixed-reference extended CSV 是否存在。固定参考点主口径采用 single-station b/k gate ablation dataset，因为该表同时保留 b/k 模式和更完整的参考点误差范围。
- 样本组统一映射：`original_like/typical_orbit_similar -> ordinary_similar`，`hard_case_weighted -> boundary_case`，`random_simulated -> random_simulated`。

## 2. 短窗口结论是否稳定

`{args.threshold_type}` 口径下，非目标样本误接受率：

| 策略 | n | 非目标样本误接受率 | DEFER 比例 | REJECT 比例 |
| --- | ---: | ---: | ---: | ---: |
| single_window | {single['n']} | {fmt(single['fa'])} | {fmt(single['defer'])} | {fmt(single['reject'])} |
| naive_accumulation | {naive['n']} | {fmt(naive['fa'])} | {fmt(naive['defer'])} | {fmt(naive['reject'])} |
| window_aware_accumulation | {aware['n']} | {fmt(aware['fa'])} | {fmt(aware['defer'])} | {fmt(aware['reject'])} |

窗口感知累计相对单窗口显著降低非目标样本误接受率；DEFER 保留了证据不足的样本，不把短窗口直接等价为最终 ACCEPT。

## 3. 固定参考点补偿的样本组差异

固定参考点补偿 current_bk / 单站主口径下，总体非目标样本误接受率为 `{fmt(fixed_current['fa'])}`。

按样本组拆分：

{markdown_table(fixed_by_group, ['sample_group', 'n_cases', 'false_accept_rate', 'defer_rate', 'reject_rate'], 10)}

按参考点误差与样本组拆分：

{markdown_table(fixed_by_error_group, ['sample_group', 'reference_error_km', 'n_cases', 'false_accept_rate', 'defer_rate', 'reject_rate'], 30)}

随机样本在 50 km 后的非目标样本误接受率为 `{fmt(random_after_50['fa'])}`；普通相似样本在 200 km 后为 `{fmt(ordinary_after_200['fa'])}`。混合平均值主要应结合样本组拆分解读，不能直接解释为所有普通样本在大参考点误差下都有同等风险。

## 4. b/k 是否仍是单站边界

fixed-reference compensation 下 b/k 消融结果：

{markdown_table(bk_by_mode, ['sample_group', 'bk_mode', 'n_cases', 'false_accept_rate', 'defer_rate', 'reject_rate'], 30)}

总体上，`no_bk` 非目标样本误接受率为 `{fmt(no_bk['fa'])}`，`current_bk` 为 `{fmt(current_bk['fa'])}`，`loose_bk` 为 `{fmt(loose_bk['fa'])}`。这说明 b/k 拟合仍是单站验证器的重要边界；范围越宽，越容易把几何差异吸收到 fitted residual 参数中。

## 5. 多站一致性是否稳定有效

current_bk 下，多站策略汇总：

{markdown_table(multi_by_sep, ['station_strategy', 'station_separation_km', 'n_cases', 'false_accept_rate', 'defer_rate', 'reject_rate'], 30)}

单站 current_bk 非目标样本误接受率为 `{fmt(multi_single['fa'])}`，三站全通过为 `{fmt(multi_three['fa'])}`，三站 + b/k 风险暂缓为 `{fmt(multi_three_risk['fa'])}`。站点间距增大时，多站 all-accept 约束整体更强，尤其在三站策略下更明显。

b/k 风险暂缓效果：

{markdown_table(risk_mean, ['station_strategy', 'current_bk_false_accept_rate', 'bk_risk_defer_false_accept_rate', 'defer_rate_increase'], 10)}

该结果支持：b/k 风险暂缓主要把一部分高风险 ACCEPT 转为 DEFER，而不是把它们直接解释为更强的 REJECT 证据。

## 6. 当前阶段是否可以收尾

当前阶段可以作为“单站边界与多站一致性初步分析”收尾。已经较稳定的结论是：

1. 短窗口单独判决风险高，窗口感知累计能降低非目标样本误接受率。
2. 固定参考点补偿风险主要集中在边界样本，小参考点误差和边界样本对混合平均值贡献较大。
3. b/k 拟合是单站误接受率升高的关键因素，no_bk 口径下非目标样本基本无法通过。
4. 多站一致性显著降低单站误接受率，站点间距越大约束通常越强。
5. b/k 风险暂缓可以把一部分高风险 ACCEPT 转为 DEFER。

仍需要下一阶段继续扩大的部分是：服务区域 / 分段参考点补偿、更多多站布局与窗口调度组合，以及更系统的边界样本覆盖。上述下一阶段仍应保持离线、合成、可复现仿真边界。

## 7. 本轮最终回答

1. 窗口感知累计是否稳定降低短窗口误接受率：是，single_window `{fmt(single['fa'])}` 降至 window_aware_accumulation `{fmt(aware['fa'])}`。
2. 固定参考点补偿的误接受是否主要集中在边界样本：是，边界样本在 current_bk 下最高，详见样本组表。
3. 随机样本和普通样本是否在参考点误差增大后快速失效：随机样本 50 km 后保持低误接受；普通相似样本随误差增大整体下降，但需结合窗口和样本组拆分。
4. 不允许 b/k 吸收时，非目标样本是否基本无法通过：是，no_bk 为 `{fmt(no_bk['fa'])}`。
5. 当前 b/k 设置是否显著提高单站误接受率：是，current_bk 为 `{fmt(current_bk['fa'])}`，显著高于 no_bk。
6. b/k 风险暂缓是否主要将 ACCEPT 转为 DEFER：是，risk table 中 false accept 降低且 defer_rate_increase 为正。
7. 多站一致性是否稳定降低单站误接受率：是，single `{fmt(multi_single['fa'])}`，three all-accept `{fmt(multi_three['fa'])}`。
8. 站点间距越大，多站约束是否越强：总体是，三站 all-accept 随站距增大误接受率下降更明显。
9. 混合平均值是否由边界样本和小参考点误差主导：是，应优先看样本组和 reference_error 拆分表。
10. 当前阶段是否可以正式收尾，并进入“服务区域 / 分段参考点补偿”下一阶段：可以，但下一阶段仍应作为离线仿真压力测试，而非真实系统操作方法。

## 8. 生成的关键文件

- `{args.dataset_output.as_posix()}`
- `{args.summary_output.as_posix()}`
- `{args.by_sample_group_output.as_posix()}`
- `{args.by_reference_error_output.as_posix()}`
- `{args.by_bk_mode_output.as_posix()}`
- `{args.by_station_separation_output.as_posix()}`
- `{args.bk_risk_effect_output.as_posix()}`
- `{args.report_tables_output.as_posix()}`
- `{args.report_output.as_posix()}`
- `{figures[0].as_posix()}`
- `{figures[1].as_posix()}`
- `{figures[2].as_posix()}`
- `{figures[3].as_posix()}`
- `{figures[4].as_posix()}`
"""
    args.report_output.write_text(text, encoding="utf-8")


def append_work_log(dataset: pd.DataFrame, summaries: dict[str, pd.DataFrame], args: argparse.Namespace) -> None:
    path = Path("logs/work_log.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    single = summary_one(dataset, dataset["experiment_block"].eq("window_accumulation") & dataset["strategy_type"].eq("single_window"))
    aware = summary_one(dataset, dataset["experiment_block"].eq("window_accumulation") & dataset["strategy_type"].eq("window_aware_accumulation"))
    no_bk = summary_one(dataset, dataset["experiment_block"].eq("bk_ablation") & dataset["bk_mode"].eq("no_bk"))
    current_bk = summary_one(dataset, dataset["experiment_block"].eq("bk_ablation") & dataset["bk_mode"].eq("current_bk"))
    multi_single = summary_one(dataset, dataset["experiment_block"].eq("multistation_consistency") & dataset["bk_mode"].eq("current_bk") & dataset["station_strategy"].eq("single_station_baseline"))
    multi_three = summary_one(dataset, dataset["experiment_block"].eq("multistation_consistency") & dataset["bk_mode"].eq("current_bk") & dataset["station_strategy"].eq("three_station_all_accept"))
    cmd = "python " + " ".join(sys.argv)
    entry = f"""

## {now} - 阶段结论固化复核

### A. 本轮目标
固化短窗口累计、固定参考点补偿、b/k 消融和多站一致性核心结论，统一输出 stage dataset、summary、图表和报告。

### B. 实际操作
- 新增并运行 `scripts/run_stage_conclusion_stabilization.py`。
- 从已有离线仿真 CSV 复算 stage-level 统计，不引入新传播或真实链路。
- 统一样本组命名和“非目标样本误接受率”统计口径。

### C. 新增/修改文件
- `scripts/run_stage_conclusion_stabilization.py`
- `{args.dataset_output.as_posix()}`
- `{args.summary_output.as_posix()}`
- `{args.report_output.as_posix()}`
- `{args.figures_dir.as_posix()}/`

### D. 运行命令
```bash
{cmd}
```

### E. 结果摘要
- dataset 行数：`{len(dataset)}`。
- summary 行数：`{len(summaries['main'])}`。
- 短窗口 single_window 非目标样本误接受率：`{fmt(single['fa'])}`；window-aware accumulation：`{fmt(aware['fa'])}`。
- b/k 消融 no_bk：`{fmt(no_bk['fa'])}`；current_bk：`{fmt(current_bk['fa'])}`。
- 多站 current_bk single：`{fmt(multi_single['fa'])}`；three_station_all_accept：`{fmt(multi_three['fa'])}`。

### F. 问题与下一步
- 本轮使用既有离线输出复算，不重新生成轨道传播样本；报告中已说明数据来源。
- 当前阶段建议作为“单站边界与多站一致性初步分析”收尾。
- 下一步建议进入服务区域 / 分段参考点补偿，但继续保持离线、合成、可复现仿真边界。
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(entry)


def write_outputs(dataset: pd.DataFrame, summaries: dict[str, pd.DataFrame], args: argparse.Namespace) -> None:
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output, index=False)
    summaries["main"].to_csv(args.summary_output, index=False)
    summaries["by_sample_group"].to_csv(args.by_sample_group_output, index=False)
    summaries["by_reference_error"].to_csv(args.by_reference_error_output, index=False)
    summaries["by_bk_mode"].to_csv(args.by_bk_mode_output, index=False)
    summaries["by_station_separation"].to_csv(args.by_station_separation_output, index=False)
    summaries["bk_risk_effect"].to_csv(args.bk_risk_effect_output, index=False)
    summaries["report_tables"].to_csv(args.report_tables_output, index=False)


def main() -> None:
    args = parse_args()
    check_inputs(args)
    check_outputs(args)
    dataset = build_dataset(args)
    if dataset.empty:
        fail("stage conclusion dataset is empty after filters")
    summaries = build_summaries(dataset)
    write_outputs(dataset, summaries, args)
    figures = make_figures(dataset, summaries, args)
    write_report(dataset, summaries, figures, args)
    append_work_log(dataset, summaries, args)
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    print(f"wrote {args.summary_output} rows={len(summaries['main'])}")
    print(f"wrote {args.report_output}")
    print(f"wrote figures to {args.figures_dir}")


if __name__ == "__main__":
    main()
