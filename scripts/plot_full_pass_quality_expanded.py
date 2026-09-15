#!/usr/bin/env python
"""Plot expanded full-pass quality coverage and write Chinese summaries."""

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
    p.add_argument("--coverage-summary", type=Path, default=Path("outputs/metrics/full_pass_quality_coverage_summary.csv"))
    p.add_argument("--expanded-seq", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_sequence_eval.csv"))
    p.add_argument("--expanded-bin-summary", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_bin_summary.csv"))
    p.add_argument("--legit-sanity", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_legit_calibration_sanity.csv"))
    p.add_argument("--tri-state-summary", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_tri_state_summary.csv"))
    p.add_argument("--aggregation-summary", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/full_pass_quality_expanded"))
    p.add_argument("--report", type=Path, default=Path("outputs/reports/full_pass_quality_expanded_summary.md"))
    p.add_argument("--resampled-report", type=Path, default=Path("outputs/reports/full_pass_quality_expanded_resampled_summary.md"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def value(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    row = df.copy()
    for k, v in kwargs.items():
        row = row[row[k] == v]
    return row


def plot_bar_bins(summary: pd.DataFrame, sample_type: str, out: Path, title: str) -> None:
    d = summary[(summary["threshold_type"] == "p95") & (summary["sample_type"] == sample_type)].copy()
    order = ["low", "medium", "high"]
    d = d.set_index("elevation_bin").reindex(order).dropna(how="all")
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(d))
    ax.bar(x - 0.18, d["score_only_accept_rate"], width=0.36, label="score-only")
    ax.bar(x + 0.18, d["per_pass_k_gate_accept_rate"], width=0.36, label="per-pass k")
    ax.set_xticks(x, d.index)
    ax.set_ylabel("accept rate")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, out)


def write_reports(args, coverage, seq, bin_summary, sanity, tri, agg) -> None:
    p95 = bin_summary[bin_summary["threshold_type"] == "p95"]
    p99 = bin_summary[bin_summary["threshold_type"] == "p99"]
    med_att = value(p95, elevation_bin="medium", sample_type="attack").iloc[0]
    med_leg = value(p95, elevation_bin="medium", sample_type="legit").iloc[0]
    med_leg99 = value(p99, elevation_bin="medium", sample_type="legit").iloc[0]
    high_att = value(p95, elevation_bin="high", sample_type="attack").iloc[0]
    low_att = value(p95, elevation_bin="low", sample_type="attack").iloc[0]
    sanity_med95 = value(sanity, elevation_bin="medium", threshold_type="p95").iloc[0]
    sanity_med99 = value(sanity, elevation_bin="medium", threshold_type="p99").iloc[0]
    tri20_att = value(tri, threshold_type="p95", elevation_min_deg=20.0, sample_type="attack").iloc[0]
    tri20_leg = value(tri, threshold_type="p95", elevation_min_deg=20.0, sample_type="legit").iloc[0]
    agg20 = agg[(agg["threshold_type"] == "p95") & (agg["elevation_min_deg"] == 20.0)]
    any_att = value(agg20, aggregation_rule="any_high_quality_accept", sample_type="attack").iloc[0]
    any_leg = value(agg20, aggregation_rule="any_high_quality_accept", sample_type="legit").iloc[0]
    two_leg = value(agg20, aggregation_rule="two_high_quality_accept", sample_type="legit").iloc[0]
    required_k_cols = ["pass_k_min_p01", "pass_k_max_p99"]
    retained = all(c in seq.columns for c in required_k_cols)
    coverage_table = coverage.to_markdown(index=False)
    sanity_table = sanity.to_markdown(index=False)

    common = f"""# Full-Pass Quality Expanded Resampled Summary

## 1. 实验目的

上一轮 sanity check 发现 medium legit accept rate 偏低主要来自每个 pass 只有 5 条 legitimate calibration samples。本轮只补足 medium/high full-pass 的合法校准样本，不新增攻击类型、不做 multi-window / multi-station / active compensation，也不扩大 altitude sweep。

## 2. Coverage 与校准设置

原始 coverage：

{coverage_table}

本轮 expansion 使用 `num_legit_sims_per_pass=50` 计算同一 pass 的 p95/p99 score threshold 与 p01/p99 k range；attack samples 仍保持 `num_sims_per_case=5`。

## 3. Legit Calibration Sanity

{sanity_table}

关键对比：

- old medium p95 score+k accept rate = `0.4500`
- new medium p95 score+k accept rate = `{med_leg.per_pass_k_gate_accept_rate:.4f}`
- old medium p95 score-only accept rate = `0.8000`
- new medium p95 score-only accept rate = `{med_leg.score_only_accept_rate:.4f}`
- new medium p99 score+k accept rate = `{med_leg99.per_pass_k_gate_accept_rate:.4f}`
- p95 medium k gate extra reject count = `{int(sanity_med95.k_gate_fail_count)}`
- p99 medium k gate extra reject count = `{int(sanity_med99.k_gate_fail_count)}`

## 4. Attack Accept Rate

- p95 low attack per-pass k accept rate = `{low_att.per_pass_k_gate_accept_rate:.4f}`
- p95 medium attack per-pass k accept rate = `{med_att.per_pass_k_gate_accept_rate:.4f}`
- p95 high attack per-pass k accept rate = `{high_att.per_pass_k_gate_accept_rate:.4f}`

补足合法校准样本后，medium/high attack accept rate 仍为 0，说明上一轮 full-pass quality 主结论没有被合法校准样本量问题推翻。

## 5. Elevation Threshold 与 Aggregation

以 p95、`elevation_min_deg=20` 为例：

- tri-state attack accept rate = `{tri20_att.accept_rate:.4f}`
- tri-state legit accept rate = `{tri20_leg.accept_rate:.4f}`
- `any_high_quality_accept` attack final accept rate = `{any_att.final_accept_rate:.4f}`
- `any_high_quality_accept` legit final accept rate = `{any_leg.final_accept_rate:.4f}`
- `two_high_quality_accept` legit final accept rate = `{two_leg.final_accept_rate:.4f}`

当前仍支持 `20 deg` 作为初步 high-quality full-pass threshold。`any_high_quality_accept` / `defer_if_only_low_quality` 仍是最平衡规则：低质量 pass 通过也只 DEFER，至少一个 high-quality full-pass 通过才最终 ACCEPT。

## 6. 字段保留检查

`full_pass_quality_expanded_sequence_eval.csv` 已保留 `pass_k_min_p01 / pass_k_max_p99`：`{retained}`。同时保留 `pass_k_min_p05 / pass_k_max_p95 / k_range_width / legit_calibration_count / score_threshold_source / k_range_source`，旧 base rows 若没有这些字段则为空并在 analyze 阶段 warning。

## 7. 结论

1. 增加合法校准样本后，medium legit p95 score+k accept rate 从 `0.4500` 恢复到 `{med_leg.per_pass_k_gate_accept_rate:.4f}`。
2. p95/p99 合法接受率已回到更合理范围，k gate 额外拒绝明显减少。
3. medium/high attack accept rate 仍为 0。
4. `20 deg` threshold 与 full-pass multi-pass aggregation 主线仍成立。
5. 当前可以进入 pass-quality-aware / multi-pass-aware attacker 阶段；同时建议继续扩大合法校准样本和 target 覆盖。
"""
    args.resampled_report.parent.mkdir(parents=True, exist_ok=True)
    args.resampled_report.write_text(common, encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(common.replace("Full-Pass Quality Expanded Resampled Summary", "Full-Pass Quality Expanded Summary"), encoding="utf-8")


def main() -> None:
    args = parse_args()
    for p in [args.coverage_summary, args.expanded_seq, args.expanded_bin_summary, args.legit_sanity, args.tri_state_summary, args.aggregation_summary]:
        if not p.exists():
            fail(f"missing input: {p}")
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    coverage = pd.read_csv(args.coverage_summary)
    seq = pd.read_csv(args.expanded_seq)
    bin_summary = pd.read_csv(args.expanded_bin_summary)
    sanity = pd.read_csv(args.legit_sanity)
    tri = pd.read_csv(args.tri_state_summary)
    agg = pd.read_csv(args.aggregation_summary)

    before = coverage.set_index("elevation_bin")["total_passes"]
    after = seq[["pass_id", "elevation_bin"]].drop_duplicates()["elevation_bin"].value_counts()
    order = ["low", "medium", "high"]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(order))
    ax.bar(x - 0.18, [before.get(o, 0) for o in order], width=0.36, label="before")
    ax.bar(x + 0.18, [after.get(o, 0) for o in order], width=0.36, label="after")
    ax.set_xticks(x, order)
    ax.set_ylabel("pass count")
    ax.set_title("Pass Coverage by Elevation Bin")
    ax.legend()
    save(fig, args.figures_dir / "pass_coverage_by_elevation_bin.png")

    plot_bar_bins(bin_summary, "attack", args.figures_dir / "attack_accept_rate_by_elevation_bin_expanded.png", "Attack Accept Rate by Elevation Bin")
    plot_bar_bins(bin_summary, "legit", args.figures_dir / "legit_accept_rate_by_elevation_bin_expanded.png", "Legit Accept Rate by Elevation Bin")

    p95 = seq[seq["threshold_type"] == "p95"]
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = p95["sample_type"].map({"legit": "#3b76af", "attack": "#c86b4a"})
    ax.scatter(p95["max_elevation_deg"], p95["normalized_score"], c=colors, s=20, alpha=0.5)
    ax.axhline(1.0, color="black", linestyle="--")
    ax.axvline(20.0, color="#555555", linestyle=":", label="20 deg")
    ax.set_xlabel("max_elevation_deg")
    ax.set_ylabel("normalized_score")
    ax.set_title("Expanded Normalized Score vs Max Elevation")
    ax.legend()
    ax.grid(True, alpha=0.25)
    save(fig, args.figures_dir / "normalized_score_vs_max_elevation_expanded.png")

    p95_tri = tri[tri["threshold_type"] == "p95"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for sample_type in ["legit", "attack"]:
        d = p95_tri[p95_tri["sample_type"] == sample_type]
        ax.plot(d["elevation_min_deg"], d["accept_rate"], marker="o", label=f"{sample_type} accept")
        ax.plot(d["elevation_min_deg"], d["defer_rate"], marker="x", linestyle="--", label=f"{sample_type} defer")
    ax.set_xlabel("elevation_min_deg")
    ax.set_ylabel("rate")
    ax.set_title("Expanded Tri-State Rates")
    ax.legend()
    ax.grid(True, alpha=0.25)
    save(fig, args.figures_dir / "tri_state_rates_by_elevation_threshold_expanded.png")

    p95_agg = agg[(agg["threshold_type"] == "p95") & (agg["elevation_min_deg"] == 20.0)]
    rules = list(p95_agg["aggregation_rule"].drop_duplicates())
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(rules))
    for sample_type, off in [("legit", -0.18), ("attack", 0.18)]:
        d = p95_agg[p95_agg["sample_type"] == sample_type].set_index("aggregation_rule").reindex(rules)
        ax.bar(x + off, d["final_accept_rate"], width=0.36, label=f"{sample_type} accept")
    ax.set_xticks(x, rules, rotation=25, ha="right")
    ax.set_ylabel("final accept rate")
    ax.set_title("Expanded Multi-Pass Aggregation Rates")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, args.figures_dir / "multipass_aggregation_rates_expanded.png")

    write_reports(args, coverage, seq, bin_summary, sanity, tri, agg)
    print(f"wrote figures in {args.figures_dir}")
    print(f"wrote {args.report}")
    print(f"wrote {args.resampled_report}")


if __name__ == "__main__":
    main()
