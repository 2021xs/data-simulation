#!/usr/bin/env python
"""Evaluate full-window multi-pass aggregation rules and write adequacy report."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--bin-summary", type=Path, default=Path("outputs/metrics/full_pass_adequacy_elevation_bin_summary.csv"))
    p.add_argument("--tri-state-summary", type=Path, default=Path("outputs/metrics/full_pass_tri_state_summary.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/full_pass_multipass_aggregation_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/full_pass_multipass_aggregation_summary.csv"))
    p.add_argument("--report", type=Path, default=Path("outputs/reports/full_pass_adequacy_summary.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/full_pass_adequacy"))
    p.add_argument("--elevation-min-deg", nargs="+", type=float, default=[15, 20, 25, 30])
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def add_case_id(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, g in df.groupby(["threshold_type", "sample_type", "target_sat_id", "delta_h_km", "pass_id"], dropna=False, sort=False):
        tmp = g.copy()
        tmp["case_index"] = np.arange(1, len(tmp) + 1)
        parts.append(tmp)
    return pd.concat(parts, ignore_index=True)


def final_decision(group: pd.DataFrame, rule: str, elev_min: float) -> str:
    high = group[group["max_elevation_deg"] >= elev_min]
    low = group[group["max_elevation_deg"] < elev_min]
    high_accept = int(high["accepted_per_pass_k_p01_p99"].sum())
    high_total = len(high)
    low_accept = int(low["accepted_per_pass_k_p01_p99"].sum())
    first = group.sort_values("pass_start_utc").iloc[0]
    if rule == "single_pass_v2_baseline":
        return "ACCEPT" if bool(first["accepted_per_pass_k_p01_p99"]) else "REJECT"
    if rule == "defer_if_only_low_quality":
        if high_accept > 0:
            return "ACCEPT"
        return "DEFER" if low_accept > 0 else "REJECT"
    if rule == "any_high_quality_accept":
        if high_accept >= 1:
            return "ACCEPT"
        return "DEFER" if low_accept > 0 else "REJECT"
    if rule == "two_high_quality_accept":
        if high_accept >= 2:
            return "ACCEPT"
        return "DEFER" if (high_accept == 1 or low_accept > 0) else "REJECT"
    if rule == "all_high_quality_accept":
        if high_total > 0 and high_accept == high_total:
            return "ACCEPT"
        return "DEFER" if (high_accept > 0 or low_accept > 0) else "REJECT"
    raise ValueError(rule)


def aggregate(df: pd.DataFrame, elevation_mins: list[float]) -> pd.DataFrame:
    rules = [
        "single_pass_v2_baseline",
        "defer_if_only_low_quality",
        "any_high_quality_accept",
        "two_high_quality_accept",
        "all_high_quality_accept",
    ]
    rows = []
    case_cols = ["threshold_type", "sample_type", "target_sat_id", "target_name", "delta_h_km", "case_index"]
    for elev in elevation_mins:
        for key, g in df.groupby(case_cols, dropna=False):
            threshold_type, sample_type, target_sat_id, target_name, delta_h_km, case_index = key
            for rule in rules:
                decision = final_decision(g, rule, elev)
                rows.append(
                    {
                        "threshold_type": threshold_type,
                        "elevation_min_deg": elev,
                        "aggregation_rule": rule,
                        "sample_type": sample_type,
                        "target_sat_id": target_sat_id,
                        "target_name": target_name,
                        "delta_h_km": delta_h_km,
                        "case_index": case_index,
                        "num_passes": int(g["pass_id"].nunique()),
                        "high_quality_passes": int((g["max_elevation_deg"] >= elev).sum()),
                        "low_quality_passes": int((g["max_elevation_deg"] < elev).sum()),
                        "accepted_passes": int(g["accepted_per_pass_k_p01_p99"].sum()),
                        "final_decision": decision,
                    }
                )
    return pd.DataFrame(rows)


def summarize(agg: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, g in agg.groupby(["threshold_type", "elevation_min_deg", "aggregation_rule", "sample_type"], dropna=False):
        threshold_type, elev, rule, sample_type = key
        total = len(g)
        counts = g["final_decision"].value_counts()
        accept = int(counts.get("ACCEPT", 0))
        reject = int(counts.get("REJECT", 0))
        defer = int(counts.get("DEFER", 0))
        rows.append(
            {
                "threshold_type": threshold_type,
                "elevation_min_deg": elev,
                "aggregation_rule": rule,
                "sample_type": sample_type,
                "total_cases": int(total),
                "final_accept_count": accept,
                "final_reject_count": reject,
                "final_defer_count": defer,
                "final_accept_rate": accept / total if total else 0.0,
                "final_reject_rate": reject / total if total else 0.0,
                "final_defer_rate": defer / total if total else 0.0,
                "notes": "full-pass aggregation only; no subwindows, no multi-station",
            }
        )
    return pd.DataFrame(rows).sort_values(["threshold_type", "elevation_min_deg", "aggregation_rule", "sample_type"])


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plot_outputs(df: pd.DataFrame, bin_summary: pd.DataFrame, tri: pd.DataFrame, agg_summary: pd.DataFrame, fig_dir: Path) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    p95_bins = bin_summary[bin_summary["threshold_type"] == "p95"].copy()
    order = ["low", "medium", "high"]
    for sample_type, fname, title in [("attack", "attack_accept_rate_by_elevation_bin.png", "Attack Accept Rate by Elevation Bin"), ("legit", "legit_accept_rate_by_elevation_bin.png", "Legit Accept Rate by Elevation Bin")]:
        d = p95_bins[p95_bins["sample_type"] == sample_type].set_index("elevation_bin").reindex(order).dropna(how="all")
        fig, ax = plt.subplots(figsize=(7, 4.5))
        x = np.arange(len(d))
        ax.bar(x - 0.18, d["score_only_accept_rate"], width=0.36, label="score-only")
        ax.bar(x + 0.18, d["per_pass_k_gate_accept_rate"], width=0.36, label="per-pass k")
        ax.set_xticks(x, d.index)
        ax.set_ylabel("accept rate")
        ax.set_title(title)
        ax.legend()
        ax.grid(True, axis="y", alpha=0.25)
        save(fig, fig_dir / fname)

    p95 = df[df["threshold_type"] == "p95"]
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = p95["sample_type"].map({"legit": "#3b76af", "attack": "#c86b4a"})
    ax.scatter(p95["max_elevation_deg"], p95["normalized_score"], c=colors, alpha=0.55, s=22)
    ax.axhline(1.0, color="black", linestyle="--")
    ax.set_xlabel("max_elevation_deg")
    ax.set_ylabel("normalized_score")
    ax.set_title("Normalized Score vs Max Elevation")
    ax.grid(True, alpha=0.25)
    save(fig, fig_dir / "normalized_score_vs_max_elevation.png")

    p95_tri = tri[tri["threshold_type"] == "p95"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for sample_type in ["legit", "attack"]:
        d = p95_tri[p95_tri["sample_type"] == sample_type]
        ax.plot(d["elevation_min_deg"], d["accept_rate"], marker="o", label=f"{sample_type} accept")
        ax.plot(d["elevation_min_deg"], d["defer_rate"], marker="x", linestyle="--", label=f"{sample_type} defer")
    ax.set_xlabel("elevation_min_deg")
    ax.set_ylabel("rate")
    ax.set_title("Tri-State Rates by Elevation Threshold")
    ax.legend()
    ax.grid(True, alpha=0.25)
    save(fig, fig_dir / "tri_state_rates_by_elevation_threshold.png")

    p95_agg = agg_summary[(agg_summary["threshold_type"] == "p95") & (agg_summary["elevation_min_deg"] == 20)]
    fig, ax = plt.subplots(figsize=(10, 5))
    rules = list(p95_agg["aggregation_rule"].drop_duplicates())
    x = np.arange(len(rules))
    for i, sample_type in enumerate(["legit", "attack"]):
        d = p95_agg[p95_agg["sample_type"] == sample_type].set_index("aggregation_rule").reindex(rules)
        ax.bar(x + (-0.18 if sample_type == "legit" else 0.18), d["final_accept_rate"], width=0.36, label=f"{sample_type} accept")
    ax.set_xticks(x, rules, rotation=25, ha="right")
    ax.set_ylabel("final accept rate")
    ax.set_title("Full-Pass Multi-Pass Aggregation Rates (elevation_min=20)")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, fig_dir / "multipass_full_window_aggregation_rates.png")


def row_value(summary: pd.DataFrame, threshold: str, elev: float, rule: str, sample_type: str, col: str) -> float:
    row = summary[
        (summary["threshold_type"] == threshold)
        & (summary["elevation_min_deg"] == elev)
        & (summary["aggregation_rule"] == rule)
        & (summary["sample_type"] == sample_type)
    ]
    return float(row.iloc[0][col]) if len(row) else float("nan")


def write_report(report: Path, bin_summary: pd.DataFrame, tri: pd.DataFrame, agg: pd.DataFrame) -> None:
    low_attack = bin_summary[(bin_summary.threshold_type == "p95") & (bin_summary.elevation_bin == "low") & (bin_summary.sample_type == "attack")].iloc[0]
    high_attack = bin_summary[(bin_summary.threshold_type == "p95") & (bin_summary.elevation_bin == "high") & (bin_summary.sample_type == "attack")].iloc[0]
    low_legit = bin_summary[(bin_summary.threshold_type == "p95") & (bin_summary.elevation_bin == "low") & (bin_summary.sample_type == "legit")].iloc[0]
    high_legit = bin_summary[(bin_summary.threshold_type == "p95") & (bin_summary.elevation_bin == "high") & (bin_summary.sample_type == "legit")].iloc[0]
    elev = 20.0
    baseline_attack = row_value(agg, "p95", elev, "single_pass_v2_baseline", "attack", "final_accept_rate")
    defer_attack = row_value(agg, "p95", elev, "defer_if_only_low_quality", "attack", "final_accept_rate")
    two_attack = row_value(agg, "p95", elev, "two_high_quality_accept", "attack", "final_accept_rate")
    any_legit = row_value(agg, "p95", elev, "any_high_quality_accept", "legit", "final_accept_rate")
    two_legit = row_value(agg, "p95", elev, "two_high_quality_accept", "legit", "final_accept_rate")
    two_defer_attack = row_value(agg, "p95", elev, "two_high_quality_accept", "attack", "final_defer_rate")
    text = f"""# Full-Pass Multi-Pass Adequacy Summary

## 1. 实验目的

本轮先评估多个完整过境窗口 full-pass 是否已经足够支撑认证增强，不做 multi-window，不做 multi-station，也不做 active frequency compensation。

## 2. Full-Pass 分层结果

p95 下 low elevation attack 的 per-pass k gate accept rate 为 `{low_attack.per_pass_k_gate_accept_rate:.4f}`，high elevation attack 为 `{high_attack.per_pass_k_gate_accept_rate:.4f}`。这说明 low elevation pass 是当前 hard-case 接受风险的主要来源。

p95 下 legit 的 per-pass k gate accept rate：low elevation 为 `{low_legit.per_pass_k_gate_accept_rate:.4f}`，high elevation 为 `{high_legit.per_pass_k_gate_accept_rate:.4f}`。合法样本在不同 elevation 下也会有差异，因此 max elevation 更适合作为 pass quality / defer 指标，而不是直接判假指标。

当前数据没有 medium elevation pass，因此 medium bin 不能下结论。

## 3. 三态判决结果

低质量 pass 更适合 `DEFER`，而不是直接 `ACCEPT` 或 `REJECT`。低仰角 pass 中攻击和合法样本都可能通过 score/k；直接 reject 会伤害合法样本，直接 accept 会保留 hard-case 风险。

## 4. Multi-Pass Full-Window 聚合结果

以 `elevation_min_deg = 20`、p95 为例：

- `single_pass_v2_baseline` attack final accept rate = `{baseline_attack:.4f}`
- `defer_if_only_low_quality` attack final accept rate = `{defer_attack:.4f}`
- `two_high_quality_accept` attack final accept rate = `{two_attack:.4f}`
- `any_high_quality_accept` legit final accept rate = `{any_legit:.4f}`
- `two_high_quality_accept` legit final accept rate = `{two_legit:.4f}`，attack defer rate = `{two_defer_attack:.4f}`

`defer_if_only_low_quality` 能把只来自低质量 pass 的 accept 从最终接受中移出；`two_high_quality_accept` 更保守，但会增加 defer / reject 压力。当前最平衡的主线规则是：低质量 pass 不最终 accept，至少等待 high-quality full pass；是否要求两个 high-quality pass 需要结合可用 pass 数量和合法接受率进一步扩样。

## 5. 是否需要 Multi-Window 辅助

当前 high-quality full-pass 已基本能拒绝 hard cases，multi-pass full-window aggregation 表现比单 pass 更有解释力。因此暂不需要把 multi-window 作为主防线；它可以保留为 residual 局部结构 forensic 的附录诊断。

## 6. 推荐下一步

1. 继续扩大 full-pass multi-pass 样本，补充 medium elevation pass。
2. 做 pass-quality-aware threshold calibration。
3. 进入组会材料整理，明确 low elevation defer 策略的边界。
4. multi-window 仅作为 forensic 辅助。
5. multi-station consistency 放在后续更强验证层。
"""
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    outputs = [args.sequence_output, args.summary_output, args.report]
    if any(p.exists() for p in outputs) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    for p in [args.sequence_eval, args.bin_summary, args.tri_state_summary]:
        if not p.exists():
            fail(f"missing input: {p}")
    df = add_case_id(pd.read_csv(args.sequence_eval))
    agg = aggregate(df, args.elevation_min_deg)
    summary = summarize(agg)
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(args.sequence_output, index=False)
    summary.to_csv(args.summary_output, index=False)
    bin_summary = pd.read_csv(args.bin_summary)
    tri = pd.read_csv(args.tri_state_summary)
    plot_outputs(pd.read_csv(args.sequence_eval), bin_summary, tri, summary, args.figures_dir)
    write_report(args.report, bin_summary, tri, summary)
    print(f"wrote {args.sequence_output} rows={len(agg)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.report}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
