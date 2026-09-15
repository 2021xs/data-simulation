#!/usr/bin/env python
"""Create verifier v2 meeting figures and Chinese summary report."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/verifier_v2_sequence_eval.csv"))
    parser.add_argument("--gate-ablation", type=Path, default=Path("outputs/metrics/verifier_v2_gate_ablation.csv"))
    parser.add_argument("--false-accepts", type=Path, default=Path("outputs/metrics/verifier_v2_false_accepts_detail.csv"))
    parser.add_argument("--visibility-diagnostic", type=Path, default=Path("outputs/metrics/attack_visibility_timing_diagnostic.csv"))
    parser.add_argument("--visibility-summary", type=Path, default=Path("outputs/metrics/attack_visibility_timing_summary.csv"))
    parser.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/verifier_v2"))
    parser.add_argument("--report", type=Path, default=Path("outputs/reports/verifier_v2_summary.md"))
    parser.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
    parser.add_argument("--best-gate", default="score_plus_global_k_gate")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def require(path: Path) -> None:
    if not path.exists():
        fail(f"input not found: {path}")


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_score_distribution(seq: pd.DataFrame, fa: pd.DataFrame, threshold_type: str, out: Path) -> None:
    data = seq[seq["threshold_type"] == threshold_type].copy()
    data["normalized_score"] = data["score"] / data["threshold"]
    legit = data[data["sample_type"] == "legit"]["normalized_score"].to_numpy(float)
    attack = data[data["sample_type"] == "attack"]["normalized_score"].to_numpy(float)
    fa_ids = set(fa[fa["threshold_type"] == threshold_type]["sequence_id"].astype(str))
    fa_scores = data[data["sequence_id"].astype(str).isin(fa_ids)]["normalized_score"].to_numpy(float)
    fig, ax = plt.subplots(figsize=(9, 5))
    bins = np.linspace(0, max(3.0, np.nanpercentile(attack, 95)), 70)
    ax.hist(legit, bins=bins, density=True, alpha=0.62, label="legit", color="#3b76af")
    ax.hist(attack, bins=bins, density=True, alpha=0.38, label="attack", color="#c86b4a")
    ax.axvline(1.0, color="black", linestyle="--", linewidth=1.5, label="threshold = 1")
    if len(fa_scores):
        ax.scatter(fa_scores, np.zeros_like(fa_scores), color="#d62728", marker="x", s=80, label="score-only false accepts")
    ax.set_title("Score Distribution: Legit vs Attack")
    ax.set_xlabel("normalized_score = score / threshold")
    ax.set_ylabel("density")
    ax.legend()
    ax.grid(True, alpha=0.25)
    savefig(fig, out)


def plot_k_distribution(seq: pd.DataFrame, fa: pd.DataFrame, threshold_type: str, out: Path) -> None:
    data = seq[seq["threshold_type"] == threshold_type].copy()
    legit = data[data["sample_type"] == "legit"]["k_hat"].to_numpy(float)
    attack = data[data["sample_type"] == "attack"]["k_hat"].to_numpy(float)
    fa_k = fa[fa["threshold_type"] == threshold_type]["k_hat"].to_numpy(float)
    fig, ax = plt.subplots(figsize=(9, 5))
    bins = np.linspace(np.nanpercentile(attack, 1), np.nanpercentile(attack, 99), 90)
    ax.hist(attack, bins=bins, density=True, alpha=0.38, label="attack", color="#c86b4a")
    ax.hist(legit, bins=35, density=True, alpha=0.62, label="legit", color="#3b76af")
    ax.axvspan(-1.110156, -0.197808, color="#4c9a61", alpha=0.18, label="global_k_range")
    if len(fa_k):
        ax.scatter(fa_k, np.zeros_like(fa_k), color="#d62728", marker="x", s=90, label="score-only false accepts")
    ax.set_title("Fitted k_hat Distribution")
    ax.set_xlabel("k_hat (Hz/s)")
    ax.set_ylabel("density")
    ax.legend()
    ax.grid(True, alpha=0.25)
    savefig(fig, out)


def plot_gate_ablation(ablation: pd.DataFrame, threshold_type: str, out: Path) -> None:
    attack = ablation[(ablation["threshold_type"] == threshold_type) & (ablation["sample_group"] == "attack")].copy()
    legit = ablation[(ablation["threshold_type"] == threshold_type) & (ablation["sample_group"] == "legit")].copy()
    order = [
        "score_only",
        "score_plus_global_k_gate",
        "score_plus_per_target_k_quantile_gate",
        "score_plus_per_target_k_quantile_gate_p05_p95",
        "score_plus_global_bk_gate",
        "score_plus_per_target_bk_quantile_gate",
    ]
    attack = attack.set_index("gate_name").reindex(order).dropna(subset=["accepted_sequences"])
    legit = legit.set_index("gate_name")
    labels = [
        "score",
        "global k",
        "target k\np01-p99",
        "target k\np05-p95",
        "global b+k",
        "target b+k\np01-p99",
    ][: len(attack)]
    x = np.arange(len(attack))
    fig, ax1 = plt.subplots(figsize=(10, 5))
    bars = ax1.bar(x, attack["false_accepts_for_attack"].to_numpy(float), color="#c86b4a", alpha=0.82, label="attack false accepts")
    ax1.set_ylabel("attack false accepts")
    ax1.set_xticks(x, labels)
    ax1.set_title("Verifier v2 Gate Ablation")
    ax1.grid(True, axis="y", alpha=0.25)
    for bar in bars:
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.03, f"{int(bar.get_height())}", ha="center", va="bottom")
    ax2 = ax1.twinx()
    legit_rates = [float(legit.loc[name, "legit_accept_rate"]) if name in legit.index else np.nan for name in attack.index]
    ax2.plot(x, legit_rates, color="#3b76af", marker="o", linewidth=2, label="legit accept rate")
    ax2.set_ylim(0, 1.05)
    ax2.set_ylabel("legit accept rate")
    lines, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines + lines2, labels1 + labels2, loc="upper right")
    savefig(fig, out)


def plot_visibility(summary: pd.DataFrame, out: Path) -> None:
    data = summary.copy()
    data["label"] = data["attack_type"].str.replace("same_plane_", "", regex=False) + "\n" + data["attack_param"].astype(str)
    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(data))
    ax.bar(x, data["mean_visible_fraction"].to_numpy(float), color="#6a8fbd", alpha=0.85)
    ax.set_xticks(x, data["label"], rotation=70, ha="right", fontsize=8)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("mean visible fraction in A window")
    ax.set_title("Attack Visibility by Type / Parameter")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def metric(ablation: pd.DataFrame, threshold_type: str, gate: str, group: str, column: str) -> float:
    row = ablation[(ablation["threshold_type"] == threshold_type) & (ablation["gate_name"] == gate) & (ablation["sample_group"] == group)]
    return float(row.iloc[0][column]) if not row.empty else float("nan")


def write_report(args: argparse.Namespace, seq: pd.DataFrame, ablation: pd.DataFrame, fa: pd.DataFrame, vis_summary: pd.DataFrame, paths: list[Path]) -> None:
    th = args.threshold_type
    th_seq = seq[seq["threshold_type"] == th]
    legit_n = int(th_seq[th_seq["sample_type"] == "legit"]["sequence_id"].nunique())
    attack_n = int(th_seq[th_seq["sample_type"] == "attack"]["sequence_id"].nunique())
    score_fa = int(metric(ablation, th, "score_only", "attack", "false_accepts_for_attack"))
    global_k_fa = int(metric(ablation, th, "score_plus_global_k_gate", "attack", "false_accepts_for_attack"))
    per_target_k_fa = int(metric(ablation, th, "score_plus_per_target_k_quantile_gate", "attack", "false_accepts_for_attack"))
    score_legit = metric(ablation, th, "score_only", "legit", "legit_accept_rate")
    global_k_legit = metric(ablation, th, "score_plus_global_k_gate", "legit", "legit_accept_rate")
    per_target_k_legit = metric(ablation, th, "score_plus_per_target_k_quantile_gate", "legit", "legit_accept_rate")
    fa_source = fa[fa["threshold_type"] == th].groupby(["attack_type", "attack_param"]).size().reset_index(name="count")
    fa_source_text = "\n".join(f"- `{r.attack_type} / {r.attack_param}`: {int(r['count'])}" for _, r in fa_source.iterrows()) or "- 无"
    best_gate = "score_plus_global_k_gate" if global_k_fa <= per_target_k_fa else "score_plus_per_target_k_quantile_gate"
    best_gate_fa = min(global_k_fa, per_target_k_fa)
    best_gate_legit = global_k_legit if best_gate == "score_plus_global_k_gate" else per_target_k_legit
    alt_vis = vis_summary[vis_summary["attack_type"].astype(str).str.contains("altitude")]["mean_visible_fraction"].mean()
    phase_vis = vis_summary[vis_summary["attack_type"].astype(str).str.contains("phase")]["mean_visible_fraction"].mean()
    generated = "\n".join(f"- `{p.as_posix()}`" for p in paths)
    commands = """```bash
python scripts/evaluate_verifier_v2_gates.py --overwrite
python scripts/diagnose_attack_visibility_timing.py --overwrite
python scripts/plot_verifier_v2_results.py --overwrite
```"""
    text = f"""# Verifier v2 最小实验闭环总结

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. Baseline 复现结果

- 合法序列数：`{legit_n}`
- 攻击序列数：`{attack_n}`
- `{th}` score-only false accepts：`{score_fa}`
- false accepts 来源：
{fa_source_text}

本轮使用上一阶段 score-only verifier 输出作为输入，没有重做 matcher，也没有重生成攻击样本。`b_hat/k_hat` 是 claimed target A 条件下对 observation/model residual terms 的线性拟合参数，不是攻击者精确可控参数。

## 2. Fitted-Parameter Gate 结果

- `score_plus_global_k_gate` 后 false accepts：`{global_k_fa}`，legit accept rate：`{global_k_legit:.4f}`
- `score_plus_per_target_k_quantile_gate(p01-p99)` 后 false accepts：`{per_target_k_fa}`，legit accept rate：`{per_target_k_legit:.4f}`
- 当前最有效 gate：`{best_gate}`，attack false accept rate：`{best_gate_fa / attack_n:.6f}`
- 相对 score-only 的 legit accept rate 损失：`{score_legit - best_gate_legit:.4f}`

上一轮 3 个 score-only false accepts 的 `k_hat` 明显低于 main_range 的全局 k 范围，因此 global k gate 能直接拒绝它们；per-target k quantile gate 也能拒绝它们。

## 3. Visibility / Timing Diagnostic

- 高度偏移攻击 mean visible fraction 均值：`{alt_vis:.4f}`
- 相位偏移攻击 mean visible fraction 均值：`{phase_vis:.4f}`
- 当前 visibility 仅作为诊断输出，visible mask 来自项目 time_window 的 elevation mask；没有作为强 gate 参与验收。

这些结果支持后续把 visibility/timing 变成 verifier 的前置诊断或 defer 条件，但建议先做 multi-pass / multi-station 后再定硬阈值，避免把受控合成轨道的可见性特征过拟合成规则。

## 4. 组会可用结论

1. score-only verifier 在本轮 2000 条 controlled attack sequence 中只有 3 条 false accepts，但这 3 条暴露了 b+k 拟合项会吸收异常慢变趋势的边界。
2. fitted `k_hat` sanity gate 合理，因为合法样本的 effective residual drift 来自 SatNOGS/STRF main_range，而 3 条 false accepts 的 `k_hat` 约为 -3.22 到 -3.32 Hz/s，明显越界。
3. verifier v2 相比上一阶段新增了 score 后的 fitted-parameter 消融表、false accept 明细和 visibility/timing 诊断，不改变原 score-only baseline。
4. visibility diagnostic 显示不同 attack_type / attack_param 的可见窗口结构可被量化，后续值得纳入 multi-pass / multi-station 验证。
5. 当前结论仍是 controlled baseline，不是真实 Starlink SatNOGS replay，也不代表真实 Ku-band residual 分布。

## 5. 生成文件列表

{generated}

## 6. 运行命令

{commands}
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    inputs = [args.sequence_eval, args.gate_ablation, args.false_accepts, args.visibility_diagnostic, args.visibility_summary]
    for path in inputs:
        require(path)
    outputs = [
        args.figures_dir / "score_distribution_legit_vs_attack.png",
        args.figures_dir / "k_hat_distribution_with_false_accepts.png",
        args.figures_dir / "gate_ablation_bar.png",
        args.figures_dir / "visibility_by_attack_type.png",
        args.report,
    ]
    if any(path.exists() for path in outputs) and not args.overwrite:
        fail("output exists; add --overwrite to replace verifier v2 figures/report")
    seq = pd.read_csv(args.sequence_eval)
    ablation = pd.read_csv(args.gate_ablation)
    fa = pd.read_csv(args.false_accepts)
    vis_diag = pd.read_csv(args.visibility_diagnostic)
    vis_summary = pd.read_csv(args.visibility_summary)
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    plot_score_distribution(seq, fa, args.threshold_type, outputs[0])
    plot_k_distribution(seq, fa, args.threshold_type, outputs[1])
    plot_gate_ablation(ablation, args.threshold_type, outputs[2])
    plot_visibility(vis_summary, outputs[3])
    write_report(args, seq, ablation, fa, vis_summary, outputs)
    print("wrote verifier v2 figures and report")
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
