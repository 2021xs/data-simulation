#!/usr/bin/env python
"""Plot temporal hard-case diagnostics and write Chinese summary."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--selected-pairs", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_selected_pairs.csv"))
    p.add_argument("--forensic-summary", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_forensic_summary.csv"))
    p.add_argument("--multipass-seq", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv"))
    p.add_argument("--multipass-summary", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multipass_summary.csv"))
    p.add_argument("--multiwindow-summary", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/verifier_v2_hard_case_temporal"))
    p.add_argument("--forensic-figures-dir", type=Path, default=Path("outputs/figures/verifier_v2_hard_case_forensics"))
    p.add_argument("--report", type=Path, default=Path("outputs/reports/verifier_v2_hard_case_temporal_summary.md"))
    p.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str):
    raise SystemExit(msg)


def require(path: Path):
    if not path.exists():
        fail(f"missing input: {path}")


def save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def plots(args, mp_seq, mp_sum, mw_sum):
    th = args.threshold_type
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    att = mp_seq[(mp_seq["sample_type"] == "attack") & (mp_seq["threshold_type"] == th)]
    by_pass = att.groupby("pass_id").agg(score=("accepted_score_only", "mean"), k=("accepted_per_pass_k_p01_p99", "mean")).reset_index()
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(by_pass))
    ax.bar(x - 0.18, by_pass["score"], width=0.36, label="score-only")
    ax.bar(x + 0.18, by_pass["k"], width=0.36, label="per-pass k")
    ax.set_xticks(x, by_pass["pass_id"], rotation=60, ha="right")
    ax.set_ylabel("accept rate")
    ax.set_title("Multipass Accept Rate by Pass")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, args.figures_dir / "multipass_accept_rate_by_pass.png")

    fig, ax = plt.subplots(figsize=(10, 5))
    vals = [g["normalized_score"].to_numpy(float) for _, g in att.groupby("pass_id")]
    labels = [str(k) for k, _ in att.groupby("pass_id")]
    ax.boxplot(vals, tick_labels=labels, showfliers=False)
    ax.axhline(1.0, color="black", linestyle="--")
    ax.set_xticklabels(labels, rotation=60, ha="right")
    ax.set_ylabel("normalized_score")
    ax.set_title("Multipass Normalized Score Distribution")
    ax.grid(True, axis="y", alpha=0.25)
    save(fig, args.figures_dir / "multipass_normalized_score_distribution.png")

    mw = mw_sum[mw_sum["threshold_type"] == th]
    pivot = mw.groupby(["window_length_s", "aggregation_rule"])["attack_accept_rate"].mean().reset_index()
    fig, ax = plt.subplots(figsize=(9, 5))
    for rule, g in pivot.groupby("aggregation_rule"):
        ax.plot(g["window_length_s"], g["attack_accept_rate"], marker="o", label=rule)
    ax.set_xlabel("window_length_s")
    ax.set_ylabel("attack accept rate")
    ax.set_title("Multiwindow Attack Accept Rate")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)
    save(fig, args.figures_dir / "multiwindow_attack_accept_rate_by_window_length.png")

    both = mw.groupby(["window_length_s", "aggregation_rule"]).agg(legit=("legit_accept_rate", "mean"), attack=("attack_accept_rate", "mean")).reset_index()
    fig, ax = plt.subplots(figsize=(10, 5))
    for rule, g in both.groupby("aggregation_rule"):
        ax.plot(g["window_length_s"], g["legit"], marker="o", linestyle="-", label=f"legit {rule}")
        ax.plot(g["window_length_s"], g["attack"], marker="x", linestyle="--", label=f"attack {rule}")
    ax.set_xlabel("window_length_s")
    ax.set_ylabel("accept rate")
    ax.set_title("Multiwindow Legit vs Attack Accept Rate")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(True, alpha=0.25)
    save(fig, args.figures_dir / "multiwindow_legit_vs_attack_accept_rate.png")


def write_report(args, selected, forensic, mp_sum, mw_sum):
    th = args.threshold_type
    mp = mp_sum[mp_sum["threshold_type"] == th]
    mw = mw_sum[mw_sum["threshold_type"] == th]
    mp_score = float(mp["score_only_accept_rate"].mean()) if len(mp) else np.nan
    mp_k = float(mp["per_pass_k_gate_accept_rate"].mean()) if len(mp) else np.nan
    best = mw.groupby("aggregation_rule").agg(legit=("legit_accept_rate", "mean"), attack=("attack_accept_rate", "mean")).reset_index()
    lines = ["| aggregation_rule | legit_accept_rate | attack_accept_rate |", "| --- | --- | --- |"]
    for _, r in best.iterrows():
        lines.append(f"| {r.aggregation_rule} | {r.legit:.4f} | {r.attack:.4f} |")
    forensic_top = forensic.sort_values("normalized_score").head(5)
    flines = ["| sequence_id | target | delta_h_km | normalized_score | k_hat | residual_std | residual_max_abs |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for _, r in forensic_top.iterrows():
        flines.append(f"| {r.sequence_id} | {r.target} | {r.delta_h_km} | {r.normalized_score:.4f} | {r.k_hat:.4f} | {r.residual_std:.3f} | {r.residual_max_abs:.3f} |")
    text = f"""# Verifier v2 Hard Case Temporal Summary

## 1. 实验目的

fine sweep 发现 `delta_h=-1/-2 km` hard cases 后，本轮检验这些 hard cases 是否具有跨 pass / 跨窗口稳定性。这里没有做 multi-station，也没有做 active frequency compensation。

## 2. Hard Case Forensic 结果

selected hard cases 数量：`{len(selected)}`。这些样本的共同特征是完整 pass 下 `f_geo_B(t)` 与 claimed `f_geo_A(t)` 的差异可被 b+k profile 较强吸收，残差 RMSE 低于阈值；部分样本的 k_hat 并不是贴边通过，而是落在 per-target k range 内部。

{chr(10).join(flines)}

## 3. Multi-Pass 结果

hard-case target / delta_h 在多 pass retest 下，平均 score-only accept rate = `{mp_score:.4f}`，per-pass k gate accept rate = `{mp_k:.4f}`。per-pass k gate 重新用每个 pass 的合法样本校准，因此比上一轮固定 per-target k range 更贴合 pass geometry。

## 4. Multi-Window 结果

多子窗口聚合结果如下。短窗口本身可能更弱，所以这里比较的是多窗口一致性聚合，而不是单个 random short window。

{chr(10).join(lines)}

## 5. 阶段性结论

1. `score + k` gate 的边界集中在小幅 altitude offset 且几何曲线天然接近的区域。
2. hard cases 不是单纯 k_hat 贴边问题；部分样本 residual 低且 k_hat 位于合法区间内部。
3. 时间多样性有帮助，尤其是 multi-pass 和多窗口一致性可以暴露单 pass 低 score 的不稳定性。
4. 下一步优先做 multi-pass verifier / random challenge window；multi-station consistency 更适合作为后续更强验证层。
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")


def main():
    args = parse_args()
    for p in [args.selected_pairs, args.forensic_summary, args.multipass_seq, args.multipass_summary, args.multiwindow_summary]:
        require(p)
    selected = pd.read_csv(args.selected_pairs)
    forensic = pd.read_csv(args.forensic_summary)
    mp_seq = pd.read_csv(args.multipass_seq)
    mp_sum = pd.read_csv(args.multipass_summary)
    mw_sum = pd.read_csv(args.multiwindow_summary)
    plots(args, mp_seq, mp_sum, mw_sum)
    # Combine the first few per-case forensic PNGs into a quick overview sheet.
    imgs = sorted(args.forensic_figures_dir.glob("*.png"))[:4]
    if imgs:
        fig, axes = plt.subplots(len(imgs), 1, figsize=(11, 4 * len(imgs)))
        axes = np.atleast_1d(axes)
        for ax, img_path in zip(axes, imgs):
            ax.imshow(plt.imread(img_path))
            ax.set_title(img_path.stem, fontsize=9)
            ax.axis("off")
        save(fig, args.figures_dir / "hard_case_curve_examples.png")
    write_report(args, selected, forensic, mp_sum, mw_sum)
    print(f"wrote figures in {args.figures_dir}")
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
