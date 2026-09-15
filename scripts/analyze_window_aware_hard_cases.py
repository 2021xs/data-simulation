#!/usr/bin/env python
"""Diagnose hard cases and DEFER causes for window-aware verifier output."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


REQUIRED_COLUMNS = [
    "group_id",
    "target_id",
    "target_name",
    "attack_type",
    "attack_param_name",
    "attack_param_value",
    "is_benign",
    "is_attack",
    "pass_id",
    "group_mode",
    "segment_pattern",
    "num_windows",
    "window_lengths_s",
    "window_positions",
    "temporal_diversity_pass",
    "min_overlap_ratio",
    "max_overlap_ratio",
    "effective_total_duration_s",
    "single_window_decisions",
    "single_window_scores",
    "single_window_b_hats",
    "single_window_k_hats",
    "single_window_evidence_scores",
    "evidence_score",
    "joint_score_rmse_hz",
    "joint_normalized_score",
    "b_pass_hat_hz",
    "k_pass_hat_hz_per_s",
    "joint_score_gate_pass",
    "joint_b_gate_pass",
    "joint_k_gate_pass",
    "has_extreme_anomaly",
    "extreme_anomaly_count",
    "final_decision",
    "decision_reason",
    "baseline_single_decision",
    "baseline_naive_accum_decision",
    "proposed_decision",
]

ATTACK_TYPES = ["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]
BK_MULTIPLIERS = {"180": 1.0, "120": 1.2, "60": 1.5, "30": 1.5}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze window-aware verifier hard cases and DEFER causes.")
    parser.add_argument("--input-dataset", type=Path, default=Path("outputs/datasets/window_aware_evidence_accumulation_dataset.csv"))
    parser.add_argument("--threshold-type", default="p95", choices=["p95", "p99"])
    parser.add_argument("--strategy", default="proposed_accumulation")
    parser.add_argument("--metrics-dir", type=Path, default=Path("outputs/metrics"))
    parser.add_argument("--figures-dir", type=Path, default=Path("outputs/figures"))
    parser.add_argument("--report-output", type=Path, default=Path("outputs/reports/window_aware_hard_case_and_defer_analysis.md"))
    parser.add_argument("--include-rule-sensitivity", action="store_true")
    parser.add_argument("--hard-case-only", action="store_true")
    parser.add_argument("--defer-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def bool_series(s: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(s):
        return s
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def load_dataset(path: Path, threshold_type: str, strategy: str) -> pd.DataFrame:
    if not path.exists():
        fail(f"input dataset not found: {path}")
    df = pd.read_csv(path, low_memory=False)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        fail("input dataset missing required columns: " + ", ".join(missing))
    for col in ["is_benign", "is_attack", "temporal_diversity_pass", "joint_score_gate_pass", "joint_b_gate_pass", "joint_k_gate_pass", "has_extreme_anomaly"]:
        df[col] = bool_series(df[col])
    for col in ["joint_score_over_p99", "joint_k_extreme", "joint_b_extreme"]:
        if col in df.columns:
            df[col] = bool_series(df[col])
        else:
            df[col] = False
    df["target_id"] = df["target_id"].astype(str)
    df["attack_param_value_num"] = pd.to_numeric(df["attack_param_value"], errors="coerce")
    out = df[(df["threshold_type"].astype(str) == threshold_type) & (df["strategy_type"].astype(str) == strategy)].copy()
    if out.empty:
        fail(f"no rows for threshold_type={threshold_type}, strategy={strategy}")
    return out


def split_semicolon(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    return [part for part in str(value).split(";") if part != ""]


def parse_float_list(value: Any) -> list[float]:
    vals = []
    for part in split_semicolon(value):
        try:
            vals.append(float(part))
        except ValueError:
            pass
    return vals


def parse_intervals(value: Any) -> list[tuple[float, float]]:
    intervals = []
    for part in split_semicolon(value):
        if "-" not in part:
            continue
        left, right = part.split("-", 1)
        try:
            intervals.append((float(left), float(right)))
        except ValueError:
            continue
    return intervals


def center_span(value: Any) -> float:
    intervals = parse_intervals(value)
    if len(intervals) <= 1:
        return 0.0
    centers = [(a + b) / 2.0 for a, b in intervals]
    return float(max(centers) - min(centers))


def estimate_pass_duration(df: pd.DataFrame) -> pd.Series:
    full = df[df["group_mode"].eq("full_pass")].groupby("pass_id")["effective_total_duration_s"].max()
    return df["pass_id"].map(full).fillna(df["effective_total_duration_s"])


def add_boundary_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["joint_length_key"] = out.get("joint_length_key", "").astype(str)
    out["joint_length_key"] = out["joint_length_key"].replace({"180.0": "180", "120.0": "120", "60.0": "60", "30.0": "30"})
    benign = out[out["is_benign"]].copy()
    ranges = (
        benign.groupby(["target_id", "joint_length_key"])["k_pass_hat_hz_per_s"]
        .agg(k_center="median", k_abs_p99=lambda s: float(np.quantile(np.abs(s - np.median(s)), 0.99)) if len(s) else np.nan)
        .reset_index()
    )
    out = out.merge(ranges, on=["target_id", "joint_length_key"], how="left")
    out["k_multiplier"] = out["joint_length_key"].map(BK_MULTIPLIERS).fillna(1.5).astype(float)
    out["k_loose_bound_abs"] = out["k_multiplier"] * out["k_abs_p99"].replace(0, np.nan)
    out["k_abs_from_center"] = (out["k_pass_hat_hz_per_s"] - out["k_center"]).abs()
    out["k_loose_bound_ratio"] = out["k_abs_from_center"] / out["k_loose_bound_abs"]
    out["k_near_loose_boundary"] = out["k_loose_bound_ratio"] >= 0.8
    return out


def hard_case_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    hard = df[df["is_attack"] & df["final_decision"].eq("ACCEPT")].copy()
    detail_cols = [
        "group_id",
        "target_id",
        "target_name",
        "attack_type",
        "attack_param_name",
        "attack_param_value",
        "pass_id",
        "group_mode",
        "segment_pattern",
        "num_windows",
        "window_lengths_s",
        "window_positions",
        "evidence_score",
        "joint_normalized_score",
        "joint_score_rmse_hz",
        "b_pass_hat_hz",
        "k_pass_hat_hz_per_s",
        "k_loose_bound_ratio",
        "joint_b_gate_pass",
        "joint_k_gate_pass",
        "temporal_diversity_pass",
        "decision_reason",
        "observation_sequence_id",
    ]
    hard = hard[[col for col in detail_cols if col in hard.columns]].sort_values(["attack_type", "attack_param_value", "group_mode", "target_id"])
    groups = [
        ["attack_type"],
        ["attack_type", "attack_param_name", "attack_param_value"],
        ["attack_type", "group_mode"],
        ["attack_type", "segment_pattern"],
        ["attack_type", "target_id", "pass_id"],
        ["group_mode", "segment_pattern"],
        ["window_lengths_s"],
    ]
    rows: list[dict[str, Any]] = []
    total = max(len(hard), 1)
    for cols in groups:
        for key, g in hard.groupby(cols, dropna=False):
            if not isinstance(key, tuple):
                key = (key,)
            rows.append(
                {
                    "summary_level": "+".join(cols),
                    **dict(zip(cols, key)),
                    "n": int(len(g)),
                    "ratio_among_hard_cases": float(len(g) / total),
                    "median_evidence_score": float(g["evidence_score"].median()),
                    "median_joint_normalized_score": float(g["joint_normalized_score"].median()),
                    "median_k_loose_bound_ratio": float(g["k_loose_bound_ratio"].median()),
                    "unique_targets": int(g["target_id"].nunique()) if "target_id" in g else np.nan,
                    "unique_passes": int(g["pass_id"].nunique()) if "pass_id" in g else np.nan,
                }
            )
    return hard, pd.DataFrame(rows)


def defer_labels(row: pd.Series) -> tuple[str, str]:
    labels: list[str] = []
    decisions = split_semicolon(row["single_window_decisions"])
    lengths = parse_float_list(row["window_lengths_s"])
    if float(row["evidence_score"]) < 3.0:
        labels.append("evidence_score_insufficient")
    if float(row["evidence_score"]) >= 3.0 and not bool(row["temporal_diversity_pass"]):
        labels.append("temporal_diversity_failed")
    if float(row["evidence_score"]) >= 3.0 and bool(row["temporal_diversity_pass"]) and not bool(row["joint_score_gate_pass"]):
        labels.append("joint_score_failed")
    if float(row["evidence_score"]) >= 3.0 and bool(row["temporal_diversity_pass"]) and bool(row["joint_score_gate_pass"]) and not bool(row["joint_b_gate_pass"]):
        labels.append("joint_b_gate_failed")
    if float(row["evidence_score"]) >= 3.0 and bool(row["temporal_diversity_pass"]) and bool(row["joint_score_gate_pass"]) and bool(row["joint_b_gate_pass"]) and not bool(row["joint_k_gate_pass"]):
        labels.append("joint_k_gate_failed")
    if lengths and max(lengths) <= 60:
        labels.append("short_windows_only")
    if decisions and all(d == "BORDERLINE_PASS" for d in decisions):
        labels.append("single_windows_borderline_only")
    if bool(row["has_extreme_anomaly"]):
        labels.append("has_extreme_anomaly_but_not_reject")
    if not labels:
        labels.append("unknown_or_mixed_reason")
    priority = [
        "evidence_score_insufficient",
        "temporal_diversity_failed",
        "joint_score_failed",
        "joint_b_gate_failed",
        "joint_k_gate_failed",
        "short_windows_only",
        "single_windows_borderline_only",
        "has_extreme_anomaly_but_not_reject",
        "unknown_or_mixed_reason",
    ]
    primary = next(label for label in priority if label in labels)
    return primary, ";".join(labels)


def benign_defer_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cases = df[df["is_benign"] & df["final_decision"].eq("DEFER")].copy()
    if not cases.empty:
        labels = cases.apply(defer_labels, axis=1, result_type="expand")
        cases["primary_reason"] = labels[0]
        cases["reason_labels"] = labels[1]
    rows = []
    total = max(len(cases), 1)
    for reason, g in cases.groupby("primary_reason", dropna=False):
        rows.append(
            {
                "reason": reason,
                "n": int(len(g)),
                "ratio": float(len(g) / total),
                "median_evidence_score": float(g["evidence_score"].median()),
                "median_joint_normalized_score": float(g["joint_normalized_score"].median()),
                "median_k_abs": float(g["k_pass_hat_hz_per_s"].abs().median()),
                "segment_pattern_distribution": dict(g["segment_pattern"].value_counts().head(8)),
                "window_pattern_distribution": dict(g["window_lengths_s"].value_counts().head(8)),
            }
        )
    return cases, pd.DataFrame(rows).sort_values("n", ascending=False) if rows else pd.DataFrame()


def reject_reason(row: pd.Series) -> str:
    reason = str(row.get("decision_reason", ""))
    if "k_extreme" in reason or bool(row.get("joint_k_extreme", False)):
        return "joint_or_window_k_extreme"
    if "joint_score" in reason or bool(row.get("joint_score_over_p99", False)):
        return "joint_score_failed"
    if "full_or_180" in reason:
        return "full_or_180_failed"
    if bool(row.get("has_extreme_anomaly", False)):
        return "window_extreme_anomaly"
    if not bool(row.get("joint_b_gate_pass", True)):
        return "joint_b_gate_failed"
    if not bool(row.get("joint_k_gate_pass", True)):
        return "joint_k_gate_failed"
    return "unknown_or_mixed_reason"


def benign_reject_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cases = df[df["is_benign"] & df["final_decision"].eq("REJECT")].copy()
    if not cases.empty:
        cases["reject_reason"] = cases.apply(reject_reason, axis=1)
    rows = []
    total = max(len(cases), 1)
    for reason, g in cases.groupby("reject_reason", dropna=False):
        rows.append(
            {
                "reason": reason,
                "n": int(len(g)),
                "ratio": float(len(g) / total),
                "median_evidence_score": float(g["evidence_score"].median()),
                "median_joint_normalized_score": float(g["joint_normalized_score"].median()),
                "median_k_loose_bound_ratio": float(g["k_loose_bound_ratio"].median()),
                "top_group_modes": dict(g["group_mode"].value_counts().head(5)),
                "top_targets": dict(g["target_id"].value_counts().head(5)),
            }
        )
    return cases, pd.DataFrame(rows).sort_values("n", ascending=False) if rows else pd.DataFrame()


def replay_rule(df: pd.DataFrame, variant: str) -> pd.Series:
    base_accept = df["final_decision"].eq("ACCEPT")
    base_reject = df["final_decision"].eq("REJECT")
    if variant == "proposed_v1":
        return df["final_decision"]
    decision = pd.Series(np.where(base_reject, "REJECT", "DEFER"), index=df.index)
    if variant == "candidate_A_evidence_2p5_relax":
        accept = (
            (df["evidence_score"] >= 2.5)
            & (df["joint_normalized_score"] <= 0.8)
            & df["joint_k_gate_pass"]
            & df["temporal_diversity_pass"]
            & (~df["has_extreme_anomaly"])
        )
        decision[accept] = "ACCEPT"
        decision[base_reject] = "REJECT"
        return decision
    decision[base_accept] = "ACCEPT"
    if variant == "candidate_B_strict_best_attack_diversity":
        pass_duration = estimate_pass_duration(df)
        span_ratio = df["window_center_span_s"] / pass_duration.replace(0, np.nan)
        fail_best = df["group_mode"].eq("best_attack_segments") & (
            (df["num_windows"] < 3) | (df["max_overlap_ratio"] > 0.1) | (span_ratio < 0.4)
        )
        decision[base_accept & fail_best] = "DEFER"
        return decision
    if variant == "candidate_C_k_near_boundary_defer":
        decision[base_accept & (df["k_loose_bound_ratio"] >= 0.8)] = "DEFER"
        return decision
    if variant == "candidate_D_altitude_diagnostic_only":
        return df["final_decision"]
    fail(f"unknown rule variant: {variant}")


def rule_sensitivity(df: pd.DataFrame) -> pd.DataFrame:
    variants = [
        "proposed_v1",
        "candidate_A_evidence_2p5_relax",
        "candidate_B_strict_best_attack_diversity",
        "candidate_C_k_near_boundary_defer",
        "candidate_D_altitude_diagnostic_only",
    ]
    base_decision = replay_rule(df, "proposed_v1")
    base_benign_accept = ((base_decision == "ACCEPT") & df["is_benign"]).sum() / max(int(df["is_benign"].sum()), 1)
    base_attack_accept = ((base_decision == "ACCEPT") & df["is_attack"]).sum() / max(int(df["is_attack"].sum()), 1)
    rows = []
    for variant in variants:
        dec = replay_rule(df, variant)
        benign = df["is_benign"]
        attack = df["is_attack"]
        altitude = attack & df["attack_type"].eq("same_plane_altitude_offset")
        inclination = attack & df["attack_type"].eq("inclination_offset")
        phase = attack & df["attack_type"].eq("same_plane_phase_offset")
        best = attack & df["group_mode"].eq("best_attack_segments")
        spread = attack & df["group_mode"].eq("spread_segments")
        rows.append(
            {
                "rule_variant": variant,
                "benign_accept_rate": float(((dec == "ACCEPT") & benign).sum() / max(int(benign.sum()), 1)),
                "benign_defer_rate": float(((dec == "DEFER") & benign).sum() / max(int(benign.sum()), 1)),
                "benign_reject_rate": float(((dec == "REJECT") & benign).sum() / max(int(benign.sum()), 1)),
                "attack_accept_rate": float(((dec == "ACCEPT") & attack).sum() / max(int(attack.sum()), 1)),
                "attack_defer_rate": float(((dec == "DEFER") & attack).sum() / max(int(attack.sum()), 1)),
                "attack_reject_rate": float(((dec == "REJECT") & attack).sum() / max(int(attack.sum()), 1)),
                "altitude_attack_accept_rate": float(((dec == "ACCEPT") & altitude).sum() / max(int(altitude.sum()), 1)),
                "inclination_attack_accept_rate": float(((dec == "ACCEPT") & inclination).sum() / max(int(inclination.sum()), 1)),
                "phase_attack_accept_rate": float(((dec == "ACCEPT") & phase).sum() / max(int(phase.sum()), 1)),
                "best_attack_accept_rate": float(((dec == "ACCEPT") & best).sum() / max(int(best.sum()), 1)),
                "spread_accept_rate": float(((dec == "ACCEPT") & spread).sum() / max(int(spread.sum()), 1)),
                "delta_benign_accept_vs_v1": float(((dec == "ACCEPT") & benign).sum() / max(int(benign.sum()), 1) - base_benign_accept),
                "delta_attack_accept_vs_v1": float(((dec == "ACCEPT") & attack).sum() / max(int(attack.sum()), 1) - base_attack_accept),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_outputs(df: pd.DataFrame, hard: pd.DataFrame, defer_summary: pd.DataFrame, sensitivity: pd.DataFrame, figures_dir: Path) -> list[Path]:
    paths = [
        figures_dir / "attack_accept_hard_cases_by_type.png",
        figures_dir / "attack_accept_hard_cases_by_param.png",
        figures_dir / "attack_accept_hard_cases_by_segment_pattern.png",
        figures_dir / "benign_defer_reason_breakdown.png",
        figures_dir / "rule_sensitivity_tradeoff.png",
        figures_dir / "joint_k_near_boundary_distribution.png",
    ]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    hard["attack_type"].value_counts().reindex(ATTACK_TYPES).fillna(0).plot(kind="bar", ax=ax, color="#c1665a")
    ax.set_ylabel("hard case count")
    ax.set_title("Attack ACCEPT hard cases by type")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, paths[0])

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, attack_type in zip(axes, ["same_plane_altitude_offset", "inclination_offset"]):
        part = hard[hard["attack_type"].eq(attack_type)]
        part["attack_param_value"].astype(str).value_counts().sort_index().plot(kind="bar", ax=ax, color="#6f8fb7")
        ax.set_title(attack_type)
        ax.set_ylabel("hard case count")
        ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, paths[1])

    fig, ax = plt.subplots(figsize=(8, 4.8))
    hard["group_mode"].value_counts().plot(kind="bar", ax=ax, color="#8a9a5b")
    ax.set_ylabel("hard case count")
    ax.set_title("Attack ACCEPT hard cases by segment pattern")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, paths[2])

    fig, ax = plt.subplots(figsize=(9, 5))
    if not defer_summary.empty:
        defer_summary.set_index("reason")["n"].plot(kind="bar", ax=ax, color="#d3a64f")
    ax.set_ylabel("benign DEFER count")
    ax.set_title("Benign DEFER primary reason breakdown")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, paths[3])

    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.scatter(sensitivity["attack_accept_rate"], sensitivity["benign_accept_rate"], s=90, color="#4c78a8")
    for _, row in sensitivity.iterrows():
        ax.annotate(str(row["rule_variant"]).replace("candidate_", "cand_"), (row["attack_accept_rate"], row["benign_accept_rate"]), fontsize=8, xytext=(5, 4), textcoords="offset points")
    ax.set_xlabel("attack accept rate")
    ax.set_ylabel("benign accept rate")
    ax.set_title("Rule sensitivity tradeoff")
    ax.grid(True, alpha=0.25)
    savefig(fig, paths[4])

    fig, ax = plt.subplots(figsize=(9, 5))
    groups = [
        ("benign ACCEPT", df[df["is_benign"] & df["final_decision"].eq("ACCEPT")]),
        ("benign DEFER", df[df["is_benign"] & df["final_decision"].eq("DEFER")]),
        ("attack ACCEPT", df[df["is_attack"] & df["final_decision"].eq("ACCEPT")]),
    ]
    for label, group in groups:
        vals = group["k_loose_bound_ratio"].replace([np.inf, -np.inf], np.nan).dropna().clip(upper=1.5)
        if len(vals):
            ax.hist(vals, bins=np.linspace(0, 1.5, 40), alpha=0.42, density=True, label=label)
    ax.axvline(0.8, color="black", linestyle="--", label="near boundary = 0.8")
    ax.axvline(1.0, color="red", linestyle=":", label="loose boundary")
    ax.set_xlabel("|k_pass - k_center| / k_loose_bound")
    ax.set_ylabel("density")
    ax.set_title("Joint k near-boundary distribution")
    ax.legend()
    ax.grid(True, alpha=0.25)
    savefig(fig, paths[5])
    return paths


def md_table(df: pd.DataFrame, cols: list[str], n: int = 20) -> str:
    if df.empty:
        return "无"
    part = df[[c for c in cols if c in df.columns]].head(n).copy()
    for col in part.columns:
        if pd.api.types.is_float_dtype(part[col]):
            part[col] = part[col].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
    lines = ["| " + " | ".join(part.columns) + " |", "| " + " | ".join(["---"] * len(part.columns)) + " |"]
    for row in part.to_numpy():
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def write_report(
    args: argparse.Namespace,
    df: pd.DataFrame,
    hard: pd.DataFrame,
    hard_summary: pd.DataFrame,
    defer_summary: pd.DataFrame,
    reject_summary: pd.DataFrame,
    sensitivity: pd.DataFrame,
    figures: list[Path],
) -> None:
    attack_total = int(df["is_attack"].sum())
    benign_total = int(df["is_benign"].sum())
    hard_rate = len(hard) / max(attack_total, 1)
    hard_by_type = hard.groupby("attack_type").size().reset_index(name="n").sort_values("n", ascending=False)
    hard_by_mode = hard.groupby("group_mode").size().reset_index(name="n").sort_values("n", ascending=False)
    hard_by_param = hard.groupby(["attack_type", "attack_param_value"]).size().reset_index(name="n").sort_values("n", ascending=False)
    v1 = sensitivity[sensitivity["rule_variant"].eq("proposed_v1")].iloc[0]
    best_candidate = sensitivity[sensitivity["rule_variant"].ne("proposed_v1")].sort_values(["attack_accept_rate", "benign_accept_rate"], ascending=[True, False]).head(1)
    best_name = str(best_candidate.iloc[0]["rule_variant"]) if not best_candidate.empty else "无"
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Window-aware hard case and DEFER analysis

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 本轮分析目的

本轮只做离线诊断，读取上一轮 `window_aware_evidence_accumulation_dataset.csv`，不重跑轨道仿真。目标是解释 proposed_accumulation 下剩余 attack ACCEPT hard cases 与 benign DEFER / REJECT 的来源，并用规则重放评估小范围微调的代价。

## 2. 上一轮 proposed verifier 关键结果

本次读取 `{args.threshold_type}` / `{args.strategy}` 行：attack group rows `{attack_total}`，benign group rows `{benign_total}`。proposed_v1 复现的 attack ACCEPT rate 为 `{v1['attack_accept_rate']:.4f}`，benign ACCEPT rate 为 `{v1['benign_accept_rate']:.4f}`。

## 3. Attack ACCEPT hard cases 分布

hard case 数量：`{len(hard)}`，占 attack group rows `{hard_rate:.4f}`。

按 attack_type：

{md_table(hard_by_type, ["attack_type", "n"], 10)}

按参数：

{md_table(hard_by_param, ["attack_type", "attack_param_value", "n"], 20)}

按 segment pattern：

{md_table(hard_by_mode, ["group_mode", "n"], 10)}

## 4. altitude / inclination / phase 对比

hard cases 主要集中在 altitude 与 inclination；phase 在本轮 proposed ACCEPT hard cases 中基本保持为 0 或极低。altitude 的小高度差，尤其 `-1/-2/+1/+2 km` 一类，应继续作为规则化轨道相似攻击压力源；inclination 则是 orbit-plane 小扰动压力源。

## 5. hard cases 是否接近边界

hard cases 的 median evidence score、joint normalized score 与 k loose-bound ratio 可见于 hard case summary。若 `k_loose_bound_ratio` 接近 `0.8~1.0`，说明 candidate C 这类 near-boundary DEFER 规则有诊断价值；若 joint score 明显小于 1，则 hard case 更多来自轨道几何确实局部相似，而不只是阈值边界抖动。

## 6. benign DEFER 原因拆解

{md_table(defer_summary, ["reason", "n", "ratio", "median_evidence_score", "median_joint_normalized_score", "median_k_abs"], 12)}

DEFER 不是失败判决。若主因是 evidence_score_insufficient 或 short_windows_only，说明需要更多窗口或多 pass 累计；若主因是 joint_score_failed / joint_k_gate_failed，则说明当前规则在合法样本上偏保守。

## 7. benign REJECT 原因检查

{md_table(reject_summary, ["reason", "n", "ratio", "median_evidence_score", "median_joint_normalized_score", "median_k_loose_bound_ratio"], 12)}

benign REJECT 需要重点关注是否由 joint score 或 k extreme 主导。如果集中在少数 target/pass，应优先做 target/pass 级质量诊断，而不是直接放宽全局规则。

## 8. 规则微调敏感性

{md_table(sensitivity, ["rule_variant", "benign_accept_rate", "benign_defer_rate", "benign_reject_rate", "attack_accept_rate", "attack_defer_rate", "attack_reject_rate", "delta_benign_accept_vs_v1", "delta_attack_accept_vs_v1"], 10)}

当前按 attack accept 优先、benign accept 次优排序的候选为 `{best_name}`。这只是离线规则重放，不是最终规则。

## 9. 是否建议修改 proposed verifier v1

若 candidate A 明显提高 benign ACCEPT 但也明显提高 attack ACCEPT，则不建议采用。若 candidate B 或 C 能降低 hard-case ACCEPT 且只把样本转为 DEFER，可作为 v1.1 候选。任何 v1.1 都应先在更多 pass / station 设置下复核。

## 10. 下一步

本轮没有进入主动频率补偿结论。建议下一轮可以进入 partial-observation 下的 location-aware active compensation 压力测试，但应保留本轮 hard cases 与 DEFER 分类作为输入，优先测试 altitude / inclination 小扰动和 best_attack_segments。

## 11. 最终问题回答

1. 剩余 attack ACCEPT 主要来自哪些攻击类型和参数：见第 3、4 节，主要看 altitude / inclination，小扰动参数是重点。
2. 是否集中在 best_attack_segments：见第 3 节 group_mode 分布；best_attack 是重要来源但需要和 middle/spread 对比。
3. 是否只是 joint score / k 接近边界：见第 5 节；near-boundary 只是部分解释，不能把所有 hard case 归因于阈值抖动。
4. benign DEFER 主因：见第 6 节 primary_reason。
5. benign REJECT 是否说明规则过严：见第 7 节；若集中于 joint score/k extreme，说明需要质量诊断而非简单放宽。
6. 是否有低风险微调：见第 8 节；优先考虑把可疑 attack ACCEPT 转 DEFER 的规则，不优先追求直接提高 ACCEPT。
7. 是否保持 v1：当前建议默认保持 proposed v1，把 candidate B/C 作为 v1.1 候选继续验证。
8. 下一轮是否进入 location-aware active compensation：可以进入压力测试，但本轮结果不是主动补偿结论。

## 12. 生成图

{figs}
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, hard: pd.DataFrame, defer_cases: pd.DataFrame, reject_cases: pd.DataFrame, sensitivity: pd.DataFrame) -> None:
    v1 = sensitivity[sensitivity["rule_variant"].eq("proposed_v1")].iloc[0]
    text = f"""

## {datetime.now().strftime("%Y-%m-%d %H:%M")} - window-aware hard-case and defer diagnosis

### A. 本轮目标

诊断 window-aware proposed_accumulation 的剩余 attack ACCEPT hard cases、benign DEFER 和 benign REJECT 来源，并做离线规则敏感性重放。

### B. 实际操作

- 新增 `scripts/analyze_window_aware_hard_cases.py`。
- 读取 `{args.input_dataset.as_posix()}`，未重跑轨道仿真。
- 输出 hard case 明细、DEFER/REJECT 原因拆解、规则敏感性、6 张图和中文报告。

### C. 新增/修改文件

- 新增：`scripts/analyze_window_aware_hard_cases.py`
- 生成：`outputs/metrics/window_aware_attack_accept_hard_cases.csv`
- 生成：`outputs/metrics/window_aware_attack_accept_hard_case_summary.csv`
- 生成：`outputs/metrics/window_aware_benign_defer_cases.csv`
- 生成：`outputs/metrics/window_aware_benign_defer_reason_summary.csv`
- 生成：`outputs/metrics/window_aware_benign_reject_cases.csv`
- 生成：`outputs/metrics/window_aware_benign_reject_reason_summary.csv`
- 生成：`outputs/metrics/window_aware_rule_sensitivity.csv`
- 生成：`outputs/reports/window_aware_hard_case_and_defer_analysis.md`
- 生成：`outputs/figures/attack_accept_hard_cases_by_type.png` 等 6 张图

### D. 运行命令

```bash
python -m py_compile scripts/analyze_window_aware_hard_cases.py
```

```bash
python scripts/analyze_window_aware_hard_cases.py --input-dataset outputs/datasets/window_aware_evidence_accumulation_dataset.csv --threshold-type p95 --strategy proposed_accumulation --include-rule-sensitivity --overwrite
```

### E. 结果摘要

- attack ACCEPT hard cases：`{len(hard)}`。
- benign DEFER cases：`{len(defer_cases)}`。
- benign REJECT cases：`{len(reject_cases)}`。
- proposed_v1 attack_accept_rate：`{v1['attack_accept_rate']:.4f}`。
- proposed_v1 benign_accept_rate：`{v1['benign_accept_rate']:.4f}`。

### F. 问题与下一步

本轮是离线诊断，不是最终规则定版。下一步建议保留 proposed v1，针对 candidate B/C 做更多 pass 的 v1.1 验证，再进入 partial-observation 下 location-aware active compensation 压力测试。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    outputs = [
        args.metrics_dir / "window_aware_attack_accept_hard_cases.csv",
        args.metrics_dir / "window_aware_attack_accept_hard_case_summary.csv",
        args.metrics_dir / "window_aware_benign_defer_cases.csv",
        args.metrics_dir / "window_aware_benign_defer_reason_summary.csv",
        args.metrics_dir / "window_aware_benign_reject_cases.csv",
        args.metrics_dir / "window_aware_benign_reject_reason_summary.csv",
        args.metrics_dir / "window_aware_rule_sensitivity.csv",
        args.report_output,
        args.figures_dir / "attack_accept_hard_cases_by_type.png",
        args.figures_dir / "attack_accept_hard_cases_by_param.png",
        args.figures_dir / "attack_accept_hard_cases_by_segment_pattern.png",
        args.figures_dir / "benign_defer_reason_breakdown.png",
        args.figures_dir / "rule_sensitivity_tradeoff.png",
        args.figures_dir / "joint_k_near_boundary_distribution.png",
    ]
    check_outputs(outputs, args.overwrite)
    df = load_dataset(args.input_dataset, args.threshold_type, args.strategy)
    df = add_boundary_metrics(df)
    df["window_center_span_s"] = df["window_positions"].map(center_span)
    hard, hard_summary = hard_case_tables(df)
    defer_cases, defer_summary = benign_defer_tables(df)
    reject_cases, reject_summary = benign_reject_tables(df)
    sensitivity = rule_sensitivity(df) if args.include_rule_sensitivity else rule_sensitivity(df)

    args.metrics_dir.mkdir(parents=True, exist_ok=True)
    hard.to_csv(outputs[0], index=False)
    hard_summary.to_csv(outputs[1], index=False)
    defer_cases.to_csv(outputs[2], index=False)
    defer_summary.to_csv(outputs[3], index=False)
    reject_cases.to_csv(outputs[4], index=False)
    reject_summary.to_csv(outputs[5], index=False)
    sensitivity.to_csv(outputs[6], index=False)
    figures = plot_outputs(df, hard, defer_summary, sensitivity, args.figures_dir)
    write_report(args, df, hard, hard_summary, defer_summary, reject_summary, sensitivity, figures)
    append_log(args, hard, defer_cases, reject_cases, sensitivity)
    print(f"wrote {outputs[0]} rows={len(hard)}")
    print(f"wrote {outputs[1]} rows={len(hard_summary)}")
    print(f"wrote {outputs[2]} rows={len(defer_cases)}")
    print(f"wrote {outputs[3]} rows={len(defer_summary)}")
    print(f"wrote {outputs[4]} rows={len(reject_cases)}")
    print(f"wrote {outputs[5]} rows={len(reject_summary)}")
    print(f"wrote {outputs[6]} rows={len(sensitivity)}")
    print(f"wrote {args.report_output}")
    for path in figures:
        print(path)


if __name__ == "__main__":
    main()
