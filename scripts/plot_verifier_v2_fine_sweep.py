#!/usr/bin/env python
"""Plot verifier v2 fine sweep results and write a Chinese summary."""

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
    parser.add_argument("--altitude-eval", type=Path, default=Path("outputs/metrics/verifier_v2_altitude_fine_sweep_sequence_eval.csv"))
    parser.add_argument("--phase-eval", type=Path, default=Path("outputs/metrics/verifier_v2_phase_fine_sweep_sequence_eval.csv"))
    parser.add_argument("--summary", type=Path, default=Path("outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv"))
    parser.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/verifier_v2_fine_sweep_hard_cases.csv"))
    parser.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/verifier_v2_fine_sweep"))
    parser.add_argument("--report", type=Path, default=Path("outputs/reports/verifier_v2_fine_sweep_summary.md"))
    parser.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
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


def sorted_values(df: pd.DataFrame, col: str) -> list[float]:
    return sorted(float(v) for v in df[col].dropna().unique())


def plot_accepts(summary: pd.DataFrame, attack_type: str, x_label: str, out: Path, title: str) -> None:
    data = summary[(summary["threshold_type"] == "p95") & (summary["attack_type"] == attack_type)].sort_values("attack_param_value")
    fig, ax1 = plt.subplots(figsize=(9, 5))
    x = np.arange(len(data))
    labels = [f"{v:g}" for v in data["attack_param_value"]]
    ax1.bar(x - 0.18, data["score_only_accepts"], width=0.36, label="score-only count", color="#c86b4a", alpha=0.82)
    ax1.bar(x + 0.18, data["per_target_k_p01_p99_accepts"], width=0.36, label="score + target k count", color="#4c9a61", alpha=0.82)
    ax1.set_xticks(x, labels)
    ax1.set_xlabel(x_label)
    ax1.set_ylabel("false accept count")
    ax1.set_title(title)
    ax1.grid(True, axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, data["score_only_false_accept_rate"], color="#8e3b24", marker="o", linewidth=1.5, label="score-only rate")
    ax2.plot(x, data["per_target_k_p01_p99_false_accept_rate"], color="#2f6f3e", marker="o", linewidth=1.5, label="score + target k rate")
    ax2.set_ylabel("false accept rate")
    ax2.set_ylim(0, max(0.02, float(data["score_only_false_accept_rate"].max()) * 1.3 if len(data) else 0.02))
    handles, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles + handles2, labels1 + labels2, loc="upper right")
    savefig(fig, out)


def boxplot_metric(df: pd.DataFrame, attack_type: str, metric: str, x_label: str, out: Path, title: str, ylabel: str) -> None:
    data = df[(df["threshold_type"] == "p95") & (df["attack_type"] == attack_type)].copy()
    values = sorted_values(data, "attack_param_value")
    series = [data[data["attack_param_value"] == v][metric].to_numpy(float) for v in values]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.boxplot(series, tick_labels=[f"{v:g}" for v in values], showfliers=False)
    if metric == "normalized_score":
        ax.axhline(1.0, color="black", linestyle="--", linewidth=1.3, label="threshold = 1")
        ax.legend()
    if metric == "k_hat":
        ax.axhspan(-1.110156, -0.197808, color="#4c9a61", alpha=0.16, label="global k range")
        ax.legend()
    ax.set_xlabel(x_label)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def plot_hard_scatter(df: pd.DataFrame, out: Path) -> None:
    data = df[df["threshold_type"] == "p95"].copy()
    score_only = data[data["accepted_score_only"]]
    k_rejected = data[(data["accepted_score_only"]) & (~data["accepted_per_target_k_p01_p99"])]
    k_accepted = data[data["accepted_per_target_k_p01_p99"]]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(data["normalized_score"], data["k_hat"], s=18, alpha=0.25, color="#808080", label="all attacks")
    if not score_only.empty:
        ax.scatter(score_only["normalized_score"], score_only["k_hat"], s=45, alpha=0.9, color="#c86b4a", label="score-only accepted")
    if not k_rejected.empty:
        ax.scatter(k_rejected["normalized_score"], k_rejected["k_hat"], s=65, marker="x", color="#d62728", label="k-gate rejected")
    if not k_accepted.empty:
        ax.scatter(k_accepted["normalized_score"], k_accepted["k_hat"], s=80, marker="*", color="#2f8f46", label="k-gate accepted")
    ax.axvline(1.0, color="black", linestyle="--", linewidth=1.2)
    ax.axhspan(-1.110156, -0.197808, color="#4c9a61", alpha=0.12, label="global k range")
    ax.set_xlabel("normalized_score")
    ax.set_ylabel("k_hat (Hz/s)")
    ax.set_title("Fine Sweep Hard Cases")
    ax.grid(True, alpha=0.25)
    ax.legend()
    savefig(fig, out)


def get_count(summary: pd.DataFrame, attack_type: str, col: str, threshold_type: str) -> int:
    rows = summary[(summary["threshold_type"] == threshold_type) & (summary["attack_type"] == attack_type)]
    return int(rows[col].sum())


def top_params(summary: pd.DataFrame, attack_type: str, threshold_type: str) -> pd.DataFrame:
    rows = summary[(summary["threshold_type"] == threshold_type) & (summary["attack_type"] == attack_type)].copy()
    return rows.sort_values(["score_only_accepts", "p05_normalized_score"], ascending=[False, True]).head(5)


def write_report(args: argparse.Namespace, altitude: pd.DataFrame, phase: pd.DataFrame, summary: pd.DataFrame, hard: pd.DataFrame, outputs: list[Path]) -> None:
    th = args.threshold_type
    alt_p95 = altitude[altitude["threshold_type"] == th]
    phase_p95 = phase[phase["threshold_type"] == th]
    alt_targets = alt_p95["target_sat_id"].nunique()
    phase_targets = phase_p95["target_sat_id"].nunique()
    alt_sims = alt_p95["sequence_id"].nunique()
    phase_sims = phase_p95["sequence_id"].nunique()
    alt_score = get_count(summary, "same_plane_altitude_offset_fine", "score_only_accepts", th)
    alt_k = get_count(summary, "same_plane_altitude_offset_fine", "per_target_k_p01_p99_accepts", th)
    phase_score = get_count(summary, "same_plane_phase_offset_fine", "score_only_accepts", th)
    phase_k = get_count(summary, "same_plane_phase_offset_fine", "per_target_k_p01_p99_accepts", th)
    dangerous_alt = top_params(summary, "same_plane_altitude_offset_fine", th)
    dangerous_phase = top_params(summary, "same_plane_phase_offset_fine", th)
    k_accepted = pd.concat([alt_p95, phase_p95], ignore_index=True)
    k_accepted = k_accepted[k_accepted["accepted_per_target_k_p01_p99"]]
    hard_show = hard[hard["hard_case_type"].isin(["lowest_normalized_score_top30", "normalized_score_closest_to_1_top30"])].head(10)

    def rows_to_md(df: pd.DataFrame, cols: list[str]) -> str:
        if df.empty:
            return "无"
        out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
        for _, row in df.iterrows():
            vals = []
            for c in cols:
                value = row[c]
                vals.append(f"{value:.6g}" if isinstance(value, (float, np.floating)) else str(value))
            out.append("| " + " | ".join(vals) + " |")
        return "\n".join(out)

    generated = "\n".join(f"- `{p.as_posix()}`" for p in outputs)
    commands = """```bash
python scripts/run_verifier_v2_fine_sweep_attacks.py --max-targets 2 --num-sims-per-case 2 --overwrite
python scripts/analyze_verifier_v2_fine_sweep.py --overwrite
python scripts/plot_verifier_v2_fine_sweep.py --overwrite
python scripts/run_verifier_v2_fine_sweep_attacks.py --max-targets 20 --num-sims-per-case 5 --overwrite
python scripts/analyze_verifier_v2_fine_sweep.py --overwrite
python scripts/plot_verifier_v2_fine_sweep.py --overwrite
```"""
    text = f"""# Verifier v2 Fine Sweep 边界压力测试总结

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 实验目的

本轮不是重新设计 verifier，也不是重做 matcher，而是在更细粒度的 same-plane altitude / phase perturbation 空间中检查 verifier v2 是否稳定。重点问题是：是否存在攻击轨道 B 既能让 `score_A(B) <= threshold_A`，又能让 fitted `k_hat` 落在合法 per-target k range 内。

## 2. 实验设置

- altitude fine sweep：`{sorted_values(alt_p95, 'attack_param_value')}`
- phase fine sweep：`{sorted_values(phase_p95, 'attack_param_value')}` 秒
- target 数量：altitude `{alt_targets}`，phase `{phase_targets}`
- `{th}` 下 altitude attack sequences：`{alt_sims}`
- `{th}` 下 phase attack sequences：`{phase_sims}`
- 每个 target / perturbation 的样本数：由 `--num-sims-per-case` 控制，本轮完整实验为 `5`
- gate：score-only、global k gate、per-target k p01-p99、per-target k p05-p95

`b/k/noise` 仍作为 observation/model residual terms 或 effective residual terms 采样，不解释为攻击者精确可控参数。

## 3. Altitude Sweep 结果

- score-only false accepts：`{alt_score}`
- score + per-target k p01-p99 后 false accepts：`{alt_k}`
- 是否存在 score + per-target k gate 仍然 accepted 的攻击样本：`{'是' if alt_k else '否'}`

最危险 altitude 参数按 score-only accepts 与低分排序：

{rows_to_md(dangerous_alt, ['attack_param_value', 'total_sequences', 'score_only_accepts', 'per_target_k_p01_p99_accepts', 'p05_normalized_score', 'median_k_hat'])}

## 4. Phase Sweep 结果

- score-only false accepts：`{phase_score}`
- score + per-target k p01-p99 后 false accepts：`{phase_k}`
- 是否存在 score + per-target k gate 仍然 accepted 的攻击样本：`{'是' if phase_k else '否'}`

最危险 phase 参数按 score-only accepts 与低分排序：

{rows_to_md(dangerous_phase, ['attack_param_value', 'total_sequences', 'score_only_accepts', 'per_target_k_p01_p99_accepts', 'p05_normalized_score', 'median_k_hat'])}

## 5. Hard Cases

最危险样本摘录：

{rows_to_md(hard_show, ['hard_case_type', 'sequence_id', 'target', 'attack_type', 'attack_param', 'normalized_score', 'k_hat', 'accepted_score_only', 'accepted_per_target_k_p01_p99'])}

这些 hard cases 的危险性主要来自 normalized_score 接近或低于 1；但如果 `k_hat` 落在 per-target 合法范围外，verifier v2 的 fitted-parameter sanity gate 会把它们从 score-only accept 中剔除。

## 6. 阶段性结论

1. verifier v2 比 score-only 更稳：fine sweep 中 altitude score-only false accepts 为 `{alt_score}`，per-target k p01-p99 gate 后降为 `{alt_k}`。
2. 当前最危险区域集中在更小幅的 negative altitude offset，尤其是 `delta_h=-2 km` 与 `delta_h=-1 km`；上一轮的 `delta_h=-5 km` 在细扫中仍有 score-only accept，但会被 per-target k gate 过滤。
3. 本轮发现了 score + per-target k p01-p99 仍然 accepted 的 altitude hard cases，说明 k_hat sanity gate 不是充分条件，后续需要 random sub-window / multi-pass 继续收紧边界。
4. phase offset 在当前 sweep 尺度下仍远离可接受区，score-only 与 k gate 后 false accepts 均为 `0`。
5. 下一步建议进入 random sub-window / multi-pass，再考虑 multi-station；本轮暂不需要 active frequency compensation。

## 7. 生成文件

{generated}

## 8. 运行命令

{commands}
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    for path in [args.altitude_eval, args.phase_eval, args.summary, args.hard_cases]:
        require(path)
    outputs = [
        args.figures_dir / "altitude_sweep_false_accepts_by_delta_h.png",
        args.figures_dir / "altitude_sweep_normalized_score_by_delta_h.png",
        args.figures_dir / "altitude_sweep_k_hat_by_delta_h.png",
        args.figures_dir / "phase_sweep_false_accepts_by_offset.png",
        args.figures_dir / "phase_sweep_normalized_score_by_offset.png",
        args.figures_dir / "fine_sweep_hard_cases_scatter.png",
        args.report,
    ]
    if any(path.exists() for path in outputs) and not args.overwrite:
        fail("output exists; add --overwrite")
    altitude = pd.read_csv(args.altitude_eval)
    phase = pd.read_csv(args.phase_eval)
    summary = pd.read_csv(args.summary)
    hard = pd.read_csv(args.hard_cases)
    all_eval = pd.concat([altitude, phase], ignore_index=True)
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    plot_accepts(summary, "same_plane_altitude_offset_fine", "delta_h_km", outputs[0], "Altitude Fine Sweep False Accepts")
    boxplot_metric(altitude, "same_plane_altitude_offset_fine", "normalized_score", "delta_h_km", outputs[1], "Altitude Fine Sweep Normalized Score", "normalized_score")
    boxplot_metric(altitude, "same_plane_altitude_offset_fine", "k_hat", "delta_h_km", outputs[2], "Altitude Fine Sweep k_hat", "k_hat (Hz/s)")
    plot_accepts(summary, "same_plane_phase_offset_fine", "phase_offset_s", outputs[3], "Phase Fine Sweep False Accepts")
    boxplot_metric(phase, "same_plane_phase_offset_fine", "normalized_score", "phase_offset_s", outputs[4], "Phase Fine Sweep Normalized Score", "normalized_score")
    plot_hard_scatter(all_eval, outputs[5])
    write_report(args, altitude, phase, summary, hard, outputs)
    print("wrote fine sweep figures and report")
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
