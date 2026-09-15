#!/usr/bin/env python
"""Plot pass-quality-aware attacker search results and write Chinese report."""

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
    p.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_search_sequence_eval.csv"))
    p.add_argument("--summary", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_search_summary.csv"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_hard_cases.csv"))
    p.add_argument("--multipass-summary", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_multipass_summary.csv"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/pass_quality_aware_attacker"))
    p.add_argument("--report", type=Path, default=Path("outputs/reports/pass_quality_aware_attacker_summary.md"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def heatmap(data: pd.DataFrame, value: str, title: str, out: Path, cmap: str = "viridis") -> None:
    p95 = data[data["threshold_type"] == "p95"].copy()
    pivot = p95.pivot_table(index="delta_h_km", columns="phase_offset", values=value, aggfunc="mean")
    pivot = pivot.sort_index(ascending=True)
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", origin="lower", cmap=cmap)
    ax.set_xticks(np.arange(len(pivot.columns)), [f"{v:g}" for v in pivot.columns], rotation=45, ha="right")
    ax.set_yticks(np.arange(len(pivot.index)), [f"{v:g}" for v in pivot.index])
    ax.set_xlabel("phase_offset_s")
    ax.set_ylabel("delta_h_km")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label=value)
    save(fig, out)


def write_report(args, seq, summary, multipass) -> None:
    p95 = seq[seq["threshold_type"] == "p95"]
    p99 = seq[seq["threshold_type"] == "p99"]
    p95_v3 = int(p95["accepted_v3_single_pass"].sum())
    p99_v3 = int(p99["accepted_v3_single_pass"].sum())
    p95_score = int(p95["accepted_score_only"].sum())
    p95_k = int(p95["accepted_per_pass_k_p01_p99"].sum())
    best = p95.sort_values("normalized_score").head(10)
    best_table = best[["target_name", "pass_id", "delta_h_km", "phase_offset_s", "normalized_score", "k_hat", "accepted_score_only", "accepted_per_pass_k_p01_p99"]].to_markdown(index=False)
    accepted = p95[p95["accepted_v3_single_pass"]]
    if len(accepted):
        accepted_table = accepted[["target_name", "pass_id", "delta_h_km", "phase_offset_s", "normalized_score", "k_hat"]].head(20).to_markdown(index=False)
        regions = accepted.groupby(["delta_h_km", "phase_offset_s"]).size().sort_values(ascending=False).head(10).to_string()
    else:
        accepted_table = "未发现 p95 high-quality full-pass score+k accepted attack samples。"
        regions = "无 accepted 区域。"
    mp95 = multipass[multipass["threshold_type"] == "p95"]
    any_count = int(mp95["any_high_quality_accept"].sum()) if len(mp95) else 0
    two_count = int(mp95["two_high_quality_accept"].sum()) if len(mp95) else 0
    all_count = int(mp95["all_high_quality_accept"].sum()) if len(mp95) else 0
    text = f"""# Pass-Quality-Aware Attacker Summary

## 1. 实验目的

防御侧 verifier v3 已经收口：low-quality full-pass 只 DEFER，high-quality full-pass 需要 score threshold 与 per-pass k p01-p99 gate 同时通过。本轮进入攻击增强阶段，假设攻击者知道 pass quality 规则，在受约束的 same-plane altitude / phase perturbation 空间中寻找能在 medium/high-quality full-pass 上通过的攻击轨道 B。

## 2. 搜索空间

- `delta_h_km`: `[-5, -4, -3, -2, -1.5, -1, -0.5, 0.5, 1, 1.5, 2, 3, 4, 5]`
- `phase_offset_s`: `[-120, -60, -30, -10, 0, 10, 30, 60, 120]`
- 只评估 `max_elevation_deg >= 20` 的完整 pass。
- 每个 pass 使用 legitimate calibration samples 校准 score threshold 与 per-pass k range；attack observation 仍只使用 observation/model residual terms，不把 b/k/noise 写成攻击者精确可控参数。

本轮不做 active frequency compensation、不做 multi-station、不做 multi-window，也不做全星座无约束搜索。

## 3. Single High-Quality Pass 攻击结果

- p95 score-only accepted rows = `{p95_score}`
- p95 score+k accepted rows = `{p95_k}`
- p95 accepted_v3_single_pass rows = `{p95_v3}`
- p99 accepted_v3_single_pass rows = `{p99_v3}`

score+k accepted 样本区域：

{regions}

最小 normalized_score Top 10：

{best_table}

accepted 样本明细：

{accepted_table}

## 4. Multi-Pass-Aware 攻击结果

p95 下：

- `any_high_quality_accept` 可通过的 candidate perturbations = `{any_count}`
- `two_high_quality_accept` 可通过的 candidate perturbations = `{two_count}`
- `all_high_quality_accept` 可通过的 candidate perturbations = `{all_count}`

这用于判断同一个扰动 B 是否能跨多个 high-quality pass 稳定通过。

## 5. 对 Verifier v3 的影响

如果 p95/p99 均没有 high-quality score+k accepted attack，说明当前 v3 规则仍成立，可以继续扩大 constrained search 或整理组会材料。如果出现 single-pass accepted 但没有 multi-pass accepted，则应考虑把推荐聚合从 `any_high_quality_accept` 提升到 `two_high_quality_accept`。如果同一 B 在多个 high-quality pass 上通过，则需要进入 multi-station consistency 或更强特征。

## 6. 下一步建议

基于本轮输出，优先按结果决定：无 accepted 则扩大受约束搜索维度；single-pass accepted 则测试更严格 full-pass aggregation；multi-pass accepted 则进入 multi-station consistency。
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    for p in [args.sequence_eval, args.summary, args.hard_cases, args.multipass_summary]:
        if not p.exists():
            fail(f"missing input: {p}")
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    seq = pd.read_csv(args.sequence_eval)
    summary = pd.read_csv(args.summary)
    hard = pd.read_csv(args.hard_cases)
    multipass = pd.read_csv(args.multipass_summary)
    for col in ["accepted_score_only", "accepted_per_pass_k_p01_p99", "accepted_v3_single_pass"]:
        seq[col] = seq[col].astype(str).str.lower().isin(["true", "1", "yes"])

    heat = summary.copy()
    heat["accept_rate"] = heat["v3_single_pass_accepts"] / heat["total_sequences"].replace(0, np.nan)
    heatmap(heat, "accept_rate", "Attacker V3 Accept Rate by Altitude / Phase", args.figures_dir / "attacker_accept_heatmap_altitude_phase.png", cmap="magma")
    heatmap(heat, "min_normalized_score", "Attacker Min Normalized Score by Altitude / Phase", args.figures_dir / "attacker_min_normalized_score_heatmap.png", cmap="viridis_r")

    p95 = seq[seq["threshold_type"] == "p95"]
    fig, ax = plt.subplots(figsize=(7, 5))
    colors = np.where(p95["accepted_v3_single_pass"], "#d94841", np.where(p95["accepted_score_only"], "#e0a42b", "#4777b3"))
    ax.scatter(p95["normalized_score"], p95["k_hat"], c=colors, s=16, alpha=0.55)
    ax.axvline(1.0, color="black", linestyle="--", label="threshold")
    ax.set_xlabel("normalized_score")
    ax.set_ylabel("k_hat")
    ax.set_title("Attacker k_hat vs Normalized Score")
    ax.grid(True, alpha=0.25)
    save(fig, args.figures_dir / "attacker_k_hat_vs_normalized_score.png")

    acc_by_quality = seq.groupby(["threshold_type"]).agg(
        score_only_accept_rate=("accepted_score_only", "mean"),
        k_gate_accept_rate=("accepted_per_pass_k_p01_p99", "mean"),
        v3_accept_rate=("accepted_v3_single_pass", "mean"),
    ).reset_index()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(acc_by_quality))
    ax.bar(x - 0.25, acc_by_quality["score_only_accept_rate"], width=0.25, label="score-only")
    ax.bar(x, acc_by_quality["k_gate_accept_rate"], width=0.25, label="score+k")
    ax.bar(x + 0.25, acc_by_quality["v3_accept_rate"], width=0.25, label="v3")
    ax.set_xticks(x, acc_by_quality["threshold_type"])
    ax.set_ylabel("accept rate")
    ax.set_title("Attacker Accepts on High-Quality Passes")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, args.figures_dir / "attacker_accepts_by_pass_quality.png")

    mp = multipass.groupby("threshold_type")[["any_high_quality_accept", "two_high_quality_accept", "all_high_quality_accept"]].mean().reset_index()
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x = np.arange(len(mp))
    ax.bar(x - 0.25, mp["any_high_quality_accept"], width=0.25, label="any")
    ax.bar(x, mp["two_high_quality_accept"], width=0.25, label="two")
    ax.bar(x + 0.25, mp["all_high_quality_accept"], width=0.25, label="all")
    ax.set_xticks(x, mp["threshold_type"])
    ax.set_ylabel("candidate pass rate")
    ax.set_title("Attacker Multipass Accept Summary")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, args.figures_dir / "attacker_multipass_accept_summary.png")

    write_report(args, seq, summary, multipass)
    print(f"wrote figures in {args.figures_dir}")
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
