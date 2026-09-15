#!/usr/bin/env python
"""Plot a simplified Figure 3 for the controlled-R scan."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SUMMARY_PATH = Path("outputs/metrics/active_compensation_controlled_R_summary.csv")
PAIRWISE_PATH = Path("outputs/metrics/active_compensation_controlled_R_pairwise.csv")
ARCHIVE_SUMMARY_PATH = Path("outputs/metrics/archive_controlled_R_v1_3/active_compensation_controlled_R_summary.csv")
ARCHIVE_PAIRWISE_PATH = Path("outputs/metrics/archive_controlled_R_v1_3/active_compensation_controlled_R_pairwise.csv")
FIGURE_PATH = Path("outputs/charts/figure3_controlled_R_summary.png")
NOTES_PATH = Path("outputs/charts/figure3_controlled_R_summary_notes.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--pairwise", type=Path, default=PAIRWISE_PATH)
    parser.add_argument("--figure-output", type=Path, default=FIGURE_PATH)
    parser.add_argument("--notes-output", type=Path, default=NOTES_PATH)
    return parser.parse_args()


def setup_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise SystemExit(f"{name} 缺少必要字段: {', '.join(missing)}")


def read_summary(path: Path, name: str) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size <= 2:
        return None
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return None
    needed = [
        "residual_mode",
        "R_km",
        "case_count",
        "p95_accept_rate",
        "tri_ACCEPT_count",
        "tri_DEFER_count",
        "tri_REJECT_count",
        "score_median_hz",
        "score_p95_hz",
        "attack_delta_rmse_median_hz",
    ]
    require_columns(df, needed, name)
    return df


def load_controlled_r_summary(args: argparse.Namespace) -> tuple[pd.DataFrame, Path, Path, str]:
    summary = read_summary(args.summary, "controlled_R summary")
    source = args.summary
    pairwise = args.pairwise
    note = "使用主 controlled_R summary。"

    if summary is None or summary.empty or summary["R_km"].dropna().empty:
        archive = read_summary(ARCHIVE_SUMMARY_PATH, "archived controlled_R summary")
        if archive is None:
            raise SystemExit("主 controlled_R summary 不可用，且找不到 archive_controlled_R_v1_3 备份。")
        summary = archive
        source = ARCHIVE_SUMMARY_PATH
        pairwise = ARCHIVE_PAIRWISE_PATH
        note = "主 controlled_R summary 不可用或为空，已回退到 archive_controlled_R_v1_3。"

    if "reference_mode" in summary.columns:
        controlled = summary[summary["reference_mode"].astype(str) == "controlled_R"].copy()
        if not controlled.empty:
            summary = controlled
    return summary, source, pairwise, note


def main() -> None:
    args = parse_args()
    setup_chinese_font()

    summary, summary_path, pairwise_path, source_note = load_controlled_r_summary(args)
    empirical = summary[summary["residual_mode"].astype(str) == "empirical"].copy()
    mode_note = "使用 empirical residual_mode。"
    if empirical.empty:
        empirical = summary.copy()
        mode_note = "summary 中没有 empirical，改用全部 residual_mode。"

    empirical["R_km"] = empirical["R_km"].astype(float)
    empirical = empirical.sort_values("R_km")

    plot_r = [0, 50, 100, 200, 500]
    plot_df = empirical[empirical["R_km"].isin(plot_r)].copy()
    if plot_df.empty:
        raise SystemExit("没有可绘制的 R=0/50/100/200/500 controlled_R 数据。")
    plot_df = plot_df.set_index("R_km").loc[[r for r in plot_r if r in set(plot_df["R_km"])]].reset_index()

    x = np.arange(len(plot_df))
    labels = [str(int(r)) for r in plot_df["R_km"]]
    score_median = plot_df["score_median_hz"].to_numpy(float)

    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    ax.plot(x, score_median, marker="o", markersize=7, linewidth=2.4, color="#2b6cb0", label="验证器分数中位数")
    ax.set_title("假想服务中心偏差使攻击效果快速下降", fontsize=17, fontweight="bold", pad=14)
    ax.set_xlabel("补偿参考点距离 R (km)", fontsize=12.5)
    ax.set_ylabel("验证器分数 (Hz)", fontsize=12.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.grid(True, axis="y", linestyle="--", alpha=0.28)
    ax.legend(loc="upper left", frameon=True, fontsize=11)

    y0 = float(score_median[0])
    ax.annotate(
        "R=0：direct-S 上界",
        xy=(x[0], y0),
        xytext=(x[0] + 0.25, max(score_median) * 0.18),
        arrowprops=dict(arrowstyle="->", color="#444444", linewidth=1.0),
        fontsize=11.5,
    )
    if len(x) > 1:
        ax.annotate(
            "R≥50 km：当前样本全部拒绝",
            xy=(x[1], float(score_median[1])),
            xytext=(x[1] + 0.35, max(score_median) * 0.58),
            arrowprops=dict(arrowstyle="->", color="#444444", linewidth=1.0),
            fontsize=11.5,
        )

    args.figure_output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(args.figure_output, dpi=260, bbox_inches="tight")
    plt.close(fig)

    pairwise_note = ""
    if pairwise_path.exists() and pairwise_path.stat().st_size > 2:
        try:
            pairwise_head = pd.read_csv(pairwise_path, nrows=5)
            pairwise_note = f"- pairwise: `{pairwise_path}`；字段 `{', '.join(pairwise_head.columns)}`。"
        except pd.errors.EmptyDataError:
            pairwise_note = f"- pairwise 文件为空: `{pairwise_path}`。"
    else:
        pairwise_note = f"- pairwise 文件不存在或为空: `{pairwise_path}`。"

    full_rows = []
    for _, row in empirical.iterrows():
        total = float(row["case_count"])
        full_rows.append(
            "| {R:g} | {n:.0f} | {med:.3f} | {p95:.3f} | {acc:.0f} | {defer:.0f} | {rej:.0f} | {ar:.3f} | {dr:.3f} | {rr:.3f} |".format(
                R=float(row["R_km"]),
                n=total,
                med=float(row["score_median_hz"]),
                p95=float(row["score_p95_hz"]),
                acc=float(row["tri_ACCEPT_count"]),
                defer=float(row["tri_DEFER_count"]),
                rej=float(row["tri_REJECT_count"]),
                ar=float(row["tri_ACCEPT_count"]) / total if total else float("nan"),
                dr=float(row["tri_DEFER_count"]) / total if total else float("nan"),
                rr=float(row["tri_REJECT_count"]) / total if total else float("nan"),
            )
        )

    r50plus = empirical[empirical["R_km"] >= 50]
    all_reject_50plus = bool((r50plus["tri_REJECT_count"].astype(float) == r50plus["case_count"].astype(float)).all())
    omitted = sorted({int(r) for r in empirical["R_km"].dropna().astype(float) if r not in plot_r})

    notes = [
        "# 图3 受控 R 扫描结果图说明",
        "",
        "## 使用数据",
        f"- summary: `{summary_path}`。",
        f"- {source_note}",
        f"- {mode_note}",
        pairwise_note,
        "",
        "## 使用字段",
        "- `residual_mode`, `R_km`, `case_count`, `score_median_hz`, `score_p95_hz`, `tri_ACCEPT_count`, `tri_DEFER_count`, `tri_REJECT_count`, `p95_accept_rate`。",
        "",
        "## 图中绘制范围",
        f"- 组会简化图绘制 R 列表: `{', '.join(labels)}` km。",
        f"- 未放入图中的 R: `{', '.join(map(str, omitted)) if omitted else '无'}`。",
        "- 1000/2000 km 没放入组会图，是因为它们对近距离边界解释帮助不大，且会拉伸横轴。",
        "",
        "## 解释边界",
        "- R=0 等价于 C=S，即 direct-S 上界。",
        f"- R=50 km 起当前样本全部 REJECT: `{all_reject_50plus}`。",
        "- 这不是普适的 50 km 安全边界，只是当前目标集合、攻击源集合、验证器参数和过境窗口下的观察。",
        "- 如果远距离点不严格单调，应解释为补偿参考点偏差敏感且会快速恶化；bearing 和具体几何关系仍会影响数值。",
        "",
        "## empirical 统计",
        "| R_km | case_count | score_median_hz | score_p95_hz | tri_ACCEPT | tri_DEFER | tri_REJECT | ACCEPT_rate | DEFER_rate | REJECT_rate |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *full_rows,
    ]
    args.notes_output.parent.mkdir(parents=True, exist_ok=True)
    args.notes_output.write_text("\n".join(notes), encoding="utf-8")
    print(f"Wrote {args.figure_output}")
    print(f"Wrote {args.notes_output}")


if __name__ == "__main__":
    main()
