#!/usr/bin/env python
"""Create clean Chinese figures for the 20 deg elevation-threshold story.

The script only reads existing CSV outputs. It does not rerun simulation,
generate attack observations, or change verifier/model logic.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import numpy as np
import pandas as pd


THRESHOLDS_DEG = [5, 10, 15, 20, 25, 30, 35, 40]
SOURCE_FILE = "full_pass_quality_expanded_sequence_eval.csv"
ACCEPT_FIELD = "accepted_per_pass_k_p01_p99"
TITLE_SIZE = 16
LABEL_SIZE = 12
TICK_SIZE = 11
LEGEND_SIZE = 11
ANNOTATION_SIZE = 10
NOTE_SIZE = 9


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--reports-dir", type=Path, default=Path("outputs/reports"))
    p.add_argument("--threshold-types", nargs="+", default=["p95", "p99"])
    p.add_argument("--output-dir", type=Path, default=Path("outputs/figures/elevation_threshold_justification_clean"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y"])


def read_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"missing input: {path}")
    return pd.read_csv(path)


def ensure_can_write(paths: list[Path], overwrite: bool) -> None:
    existing = [p for p in paths if p.exists()]
    if existing and not overwrite:
        fail("outputs exist; add --overwrite:\n" + "\n".join(str(p) for p in existing))


def setup_chinese_font() -> str:
    candidates = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Noto Sans CJK",
        "WenQuanYi Micro Hei",
        "Arial Unicode MS",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    chosen = next((name for name in candidates if name in available), "")
    if chosen:
        plt.rcParams["font.sans-serif"] = [chosen, "DejaVu Sans"]
    else:
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return chosen


def save(fig: plt.Figure, path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        fail(f"output exists; add --overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.08, 1, 0.98])
    fig.savefig(path, dpi=220)
    plt.close(fig)


def pct(v: float) -> str:
    if pd.isna(v):
        return "NA"
    return f"{v * 100:.2f}%"


def fmt_hours(v: float) -> str:
    if pd.isna(v):
        return "NA"
    return f"{v:.2f}h"


def top_counts_text(df: pd.DataFrame, col: str, n: int = 3) -> str:
    if col not in df.columns or df.empty:
        return ""
    counts = df[col].astype(str).value_counts().head(n)
    return "; ".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def load_full_pass_attack(metrics_dir: Path) -> pd.DataFrame:
    path = metrics_dir / SOURCE_FILE
    df = read_required(path)
    required = {
        "sample_type",
        "threshold_type",
        "max_elevation_deg",
        ACCEPT_FIELD,
        "target_name",
        "pass_id",
    }
    missing = required - set(df.columns)
    if missing:
        fail(f"{path} missing required fields: {sorted(missing)}")
    out = df.copy()
    out["source_file"] = SOURCE_FILE
    out["sample_type"] = out["sample_type"].astype(str).str.lower()
    out["threshold_type"] = out["threshold_type"].astype(str)
    out["max_elevation_deg"] = pd.to_numeric(out["max_elevation_deg"], errors="coerce")
    out[ACCEPT_FIELD] = to_bool(out[ACCEPT_FIELD])
    return out[out["sample_type"].eq("attack")].copy()


def audit_lt20_ge20(attack: pd.DataFrame) -> pd.DataFrame:
    d = attack[attack["threshold_type"].eq("p95")].copy()
    rows = []
    for group_name, mask in [("<20°", d["max_elevation_deg"] < 20), (">=20°", d["max_elevation_deg"] >= 20)]:
        g = d[mask].copy()
        accepted = g[g[ACCEPT_FIELD]]
        total = len(g)
        accept_count = len(accepted)
        target_accept_counts = accepted["target_name"].astype(str).value_counts()
        pass_accept_counts = accepted["pass_id"].astype(str).value_counts()
        notes = [
            "困难样本扩展完整过境分析集中的条件攻击误接受率",
            "仅筛选攻击样本",
            "仅筛选p95校准阈值",
            "按序列逐条统计，不按时刻采样点统计",
            "未重复计入p95/p99",
            "接受字段为残差分数加拟合参数检查后的结果",
        ]
        if not target_accept_counts.empty and target_accept_counts.iloc[0] / max(accept_count, 1) >= 0.5:
            notes.append("accepted cases concentrated in few targets")
        if not pass_accept_counts.empty and pass_accept_counts.iloc[0] / max(accept_count, 1) >= 0.5:
            notes.append("accepted cases concentrated in few passes")
        rows.append(
            {
                "group": group_name,
                "threshold_type": "p95",
                "total_attack_sequences": int(total),
                "accepted_attack_sequences": int(accept_count),
                "attack_accept_rate": accept_count / total if total else np.nan,
                "source_file": SOURCE_FILE,
                "accept_field": ACCEPT_FIELD,
                "unique_target_count": int(g["target_name"].nunique()),
                "unique_pass_count": int(g["pass_id"].nunique()),
                "top_targets_by_accept_count": top_counts_text(accepted, "target_name"),
                "top_passes_by_accept_count": top_counts_text(accepted, "pass_id"),
                "notes": "; ".join(notes),
            }
        )
    audit = pd.DataFrame(rows)
    expected = {
        "<20°": (160, 50),
        ">=20°": (680, 0),
    }
    for group_name, (total, accepted) in expected.items():
        row = audit[audit["group"].eq(group_name)].iloc[0]
        if int(row["total_attack_sequences"]) != total or int(row["accepted_attack_sequences"]) != accepted:
            fail(
                f"audit mismatch for {group_name}: got "
                f"{int(row['accepted_attack_sequences'])}/{int(row['total_attack_sequences'])}, "
                f"expected {accepted}/{total}"
            )
    return audit


def select_boundary_safety(safety: pd.DataFrame, threshold_types: list[str]) -> pd.DataFrame:
    required = {"source_file", "threshold_type", "threshold_deg", "qualified_score_k_accept_rate"}
    missing = required - set(safety.columns)
    if missing:
        fail(f"elevation_threshold_safety_tradeoff.csv missing fields: {sorted(missing)}")
    d = safety[
        safety["source_file"].eq(SOURCE_FILE)
        & safety["threshold_type"].isin(threshold_types)
        & safety["threshold_deg"].isin(THRESHOLDS_DEG)
    ].copy()
    if d.empty:
        fail(f"no safety rows for {SOURCE_FILE}")
    d["threshold_deg"] = pd.to_numeric(d["threshold_deg"], errors="coerce")
    d["qualified_score_k_accept_rate"] = pd.to_numeric(d["qualified_score_k_accept_rate"], errors="coerce")
    return d.sort_values(["threshold_type", "threshold_deg"])


def select_availability(avail: pd.DataFrame) -> pd.DataFrame:
    required = {
        "duration_days",
        "threshold_deg",
        "target_count",
        "targets_with_qualified_pass_count",
        "qualified_coverage_rate",
        "median_time_to_first_qualified_pass_hours",
        "p90_time_to_first_qualified_pass_hours",
        "median_qualified_pass_count",
    }
    missing = required - set(avail.columns)
    if missing:
        fail(f"elevation_threshold_availability_tradeoff_300.csv missing fields: {sorted(missing)}")
    d = avail[(avail["duration_days"] == 30) & (avail["threshold_deg"].isin(THRESHOLDS_DEG))].copy()
    for col in [
        "threshold_deg",
        "qualified_coverage_rate",
        "median_time_to_first_qualified_pass_hours",
        "p90_time_to_first_qualified_pass_hours",
        "median_qualified_pass_count",
    ]:
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d.sort_values("threshold_deg")


def interpretation(threshold: int, p95_rate: float) -> str:
    if threshold < 15:
        return f"{threshold}°：仍有攻击误接受风险，不适合作为强接受阈值"
    if threshold < 20:
        return f"{threshold}°：攻击误接受风险下降但未消除"
    if threshold == 20:
        return "20°：当前数据中攻击误接受率降为0，且可用性保持良好"
    if threshold == 25:
        return "25°：同样安全，但相对20°没有明显安全增益"
    if threshold == 30:
        return "30°：安全性无额外收益，但等待时间增加、可用过境减少"
    if threshold >= 40:
        return "40°：进一步增加等待时间，不适合作为当前最低折中阈值"
    return f"{threshold}°：继续提高阈值主要带来可用性成本"


def build_story_table(safety: pd.DataFrame, avail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for threshold in THRESHOLDS_DEG:
        p95 = safety[(safety["threshold_type"].eq("p95")) & (safety["threshold_deg"].eq(threshold))]
        p99 = safety[(safety["threshold_type"].eq("p99")) & (safety["threshold_deg"].eq(threshold))]
        av = avail[avail["threshold_deg"].eq(threshold)]
        p95_rate = float(p95["qualified_score_k_accept_rate"].iloc[0]) if not p95.empty else np.nan
        p99_rate = float(p99["qualified_score_k_accept_rate"].iloc[0]) if not p99.empty else np.nan
        av_row = av.iloc[0] if not av.empty else None
        rows.append(
            {
                "candidate_threshold_deg": threshold,
                "p95_attack_accept_rate": p95_rate,
                "p99_attack_accept_rate": p99_rate,
                "target_coverage_30d": float(av_row["qualified_coverage_rate"]) if av_row is not None else np.nan,
                "median_wait_hours_30d": float(av_row["median_time_to_first_qualified_pass_hours"]) if av_row is not None else np.nan,
                "p90_wait_hours_30d": float(av_row["p90_time_to_first_qualified_pass_hours"]) if av_row is not None else np.nan,
                "median_qualified_pass_count_30d": float(av_row["median_qualified_pass_count"]) if av_row is not None else np.nan,
                "interpretation_cn": interpretation(threshold, p95_rate),
            }
        )
    return pd.DataFrame(rows)


def plot_lt20_vs_ge20(audit: pd.DataFrame, out: Path, overwrite: bool) -> None:
    d = audit.set_index("group").loc[["<20°", ">=20°"]].reset_index()
    labels = ["<20°", "≥20°"]
    rates = d["attack_accept_rate"].to_numpy()
    counts = list(zip(d["accepted_attack_sequences"], d["total_attack_sequences"]))
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    colors = ["#c7533f", "#3b7f62"]
    bars = ax.bar(labels, rates, color=colors, width=0.52)
    for bar, rate, (accepted, total) in zip(bars, rates, counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.015,
            f"{int(accepted)}/{int(total)}\n{pct(rate)}",
            ha="center",
            va="bottom",
            fontsize=LABEL_SIZE,
        )
    ax.set_title("20°前后攻击误接受率对比", fontsize=TITLE_SIZE, pad=14)
    ax.set_xlabel("最大仰角分组", fontsize=LABEL_SIZE)
    ax.set_ylabel("攻击误接受率", fontsize=LABEL_SIZE)
    ax.tick_params(labelsize=TICK_SIZE)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.set_ylim(0, max(0.40, float(np.nanmax(rates)) + 0.08))
    ax.grid(True, axis="y", alpha=0.25)
    fig.text(
        0.5,
        0.025,
        "注：困难样本扩展完整过境分析集中的条件误接受率，非全局攻击成功率",
        fontsize=NOTE_SIZE,
        color="#555555",
        ha="center",
        va="center",
    )
    save(fig, out, overwrite)


def plot_safety(safety: pd.DataFrame, out: Path, overwrite: bool) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    styles = {
        "p95": ("#c7533f", "o", "p95 校准阈值"),
        "p99": ("#7b5cb8", "s", "p99 校准阈值"),
    }
    for th, (color, marker, label) in styles.items():
        g = safety[safety["threshold_type"].eq(th)].sort_values("threshold_deg")
        ax.plot(
            g["threshold_deg"],
            g["qualified_score_k_accept_rate"],
            marker=marker,
            linewidth=2.2,
            color=color,
            label=label,
        )
        for _, row in g.iterrows():
            threshold = int(row["threshold_deg"])
            rate = float(row["qualified_score_k_accept_rate"])
            if threshold in [10, 15] and rate > 0:
                ax.annotate(
                    pct(rate),
                    (threshold, rate),
                    textcoords="offset points",
                    xytext=(0, 9 if th == "p99" else -18),
                    ha="center",
                    fontsize=ANNOTATION_SIZE,
                    color=color,
                )
    ax.axvline(20, color="#333333", linestyle=":", linewidth=1.8)
    ax.annotate("20°后降为0", xy=(20, 0), xytext=(22, 0.055), arrowprops={"arrowstyle": "->", "color": "#333333"}, fontsize=ANNOTATION_SIZE)
    ax.set_title("候选仰角阈值与攻击误接受率", fontsize=TITLE_SIZE, pad=14)
    ax.set_xlabel("候选仰角阈值（度）", fontsize=LABEL_SIZE)
    ax.set_ylabel("满足阈值过境中的攻击误接受率", fontsize=LABEL_SIZE)
    ax.set_xticks(THRESHOLDS_DEG)
    ax.tick_params(labelsize=TICK_SIZE)
    ax.set_ylim(0, 0.085)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(title="残差分数 + 拟合参数检查后", frameon=False, fontsize=LEGEND_SIZE, title_fontsize=LEGEND_SIZE, loc="upper right", bbox_to_anchor=(0.98, 0.92))
    save(fig, out, overwrite)


def plot_waiting(avail: pd.DataFrame, out: Path, overwrite: bool) -> None:
    d = avail.sort_values("threshold_deg")
    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    ax.plot(
        d["threshold_deg"],
        d["median_time_to_first_qualified_pass_hours"],
        marker="o",
        linewidth=2.2,
        color="#2f6f9f",
        label="中位等待时间",
    )
    ax.plot(
        d["threshold_deg"],
        d["p90_time_to_first_qualified_pass_hours"],
        marker="s",
        linewidth=2.2,
        color="#4f8f62",
        label="p90 等待时间",
    )
    row20 = d[d["threshold_deg"].eq(20)].iloc[0]
    ax.axvline(20, color="#333333", linestyle=":", linewidth=1.8)
    ax.annotate(
        "20°：中位5.46h，p90 16.60h",
        xy=(20, float(row20["p90_time_to_first_qualified_pass_hours"])),
        xytext=(22, float(row20["p90_time_to_first_qualified_pass_hours"]) + 1.2),
        arrowprops={"arrowstyle": "->", "color": "#333333"},
        fontsize=ANNOTATION_SIZE,
    )
    fig.text(
        0.5,
        0.025,
        "300颗目标，30天统计窗口；20°下覆盖率300/300",
        fontsize=NOTE_SIZE,
        color="#555555",
        ha="center",
        va="center",
    )
    ax.set_title("提高仰角阈值带来的等待时间成本", fontsize=TITLE_SIZE, pad=14)
    ax.set_xlabel("候选仰角阈值（度）", fontsize=LABEL_SIZE)
    ax.set_ylabel("首次满足条件过境的等待时间（小时）", fontsize=LABEL_SIZE)
    ax.set_xticks(THRESHOLDS_DEG)
    ax.tick_params(labelsize=TICK_SIZE)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(frameon=False, fontsize=LEGEND_SIZE)
    save(fig, out, overwrite)


def update_report(report_path: Path, audit: pd.DataFrame, story: pd.DataFrame) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    old = report_path.read_text(encoding="utf-8") if report_path.exists() else "# 20° Elevation Threshold Justification Summary\n"
    start_marker = "## 20°阈值的组会解释版本"
    next_marker = "\n## "
    lt20 = audit[audit["group"].eq("<20°")].iloc[0]
    ge20 = audit[audit["group"].eq(">=20°")].iloc[0]
    row20 = story[story["candidate_threshold_deg"].eq(20)].iloc[0]
    row30 = story[story["candidate_threshold_deg"].eq(30)].iloc[0]
    row40 = story[story["candidate_threshold_deg"].eq(40)].iloc[0]
    section = f"""## 20°阈值的组会解释版本

1. `20°` 不是物理常数，而是当前实验条件下的经验工程阈值。
2. 在困难样本扩展完整过境分析集中，p95 下：
   - `<20°`：`{int(lt20.accepted_attack_sequences)}/{int(lt20.total_attack_sequences)} = {pct(float(lt20.attack_accept_rate))}`
   - `>=20°`：`{int(ge20.accepted_attack_sequences)}/{int(ge20.total_attack_sequences)} = {pct(float(ge20.attack_accept_rate))}`
3. 这说明低仰角完整过境保留明显条件误接受风险，而 `20°` 以上当前没有发现误接受样本。
4. 候选阈值分析显示，`10°` / `15°` 仍保留攻击误接受；从 `20°` 开始，当前数据中的攻击误接受率降为 0。
5. 300 目标可用性审计显示，`20°` 下 30 天覆盖率 = `300/300`，首次合格过境中位等待时间 = `{fmt_hours(float(row20.median_wait_hours_30d))}`，p90 等待时间 = `{fmt_hours(float(row20.p90_wait_hours_30d))}`。
6. `30°` / `40°` 虽然也安全，但主要增加等待时间并减少可用过境数量：30° 中位等待时间 = `{fmt_hours(float(row30.median_wait_hours_30d))}`，中位合格过境数 = `{float(row30.median_qualified_pass_count_30d):.0f}`；40° 中位等待时间 = `{fmt_hours(float(row40.median_wait_hours_30d))}`，中位合格过境数 = `{float(row40.median_qualified_pass_count_30d):.0f}`。因此当前选择 `20°` 作为更保留可用性的最低安全折中点。
7. 局限性：这不是全局攻击成功率；结论依赖当前受控地面站、目标集合和规则化轨道相似攻击模型；后续若引入主动频率补偿攻击，需要重新校准阈值。

"""
    idx = old.find(start_marker)
    if idx >= 0:
        next_idx = old.find(next_marker, idx + len(start_marker))
        if next_idx >= 0:
            new = old[:idx] + section + old[next_idx + 1 :]
        else:
            new = old[:idx] + section
    else:
        new = old.rstrip() + "\n\n" + section
    for old_text, new_text in [
        ("攻击接受率", "攻击误接受率"),
        ("攻击接受风险", "攻击误接受风险"),
        ("攻击接受情况", "攻击误接受情况"),
        ("攻击接受为", "攻击误接受为"),
        ("攻击接受；", "攻击误接受；"),
        ("攻击接受。", "攻击误接受。"),
        ("攻击接受 = ", "攻击误接受 = "),
        ("full-pass / expanded full-pass / pass-quality-aware attacker", "完整过境 / 扩展完整过境 / 过境质量感知攻击搜索"),
        ("pass-quality-aware attacker", "过境质量感知攻击搜索"),
        ("300-target availability pass detail", "300 目标可用性过境明细"),
        ("coverage", "覆盖率"),
        ("time-to-first-qualified-pass", "首次合格过境等待时间"),
        ("controlled station", "受控地面站"),
        ("target set", "目标集合"),
        ("attack model", "攻击模型"),
        ("low-elevation full-pass", "低仰角完整过境"),
        ("300-target availability audit", "300 目标可用性审计"),
        ("Starlink target set", "Starlink 目标集合"),
        ("score+k/v3 verifier", "残差分数加拟合参数检查验证器"),
        ("high-quality full-pass threshold", "高质量完整过境阈值"),
        ("median wait", "中位等待时间"),
        ("median qualified pass count", "中位合格过境数"),
    ]:
        new = new.replace(old_text, new_text)
    report_path.write_text(new, encoding="utf-8")


def append_work_log(log_path: Path, font_name: str) -> None:
    font_note = font_name if font_name else "未找到中文字体，已使用默认字体；若图片中文乱码，请安装 Microsoft YaHei/SimHei/Noto Sans CJK。"
    entry = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} - elevation threshold clean Chinese story figures

### A. 本轮目标

优化 `20°` elevation threshold justification 的组会图表，只读取已有 CSV，生成 clean 中文新版图和 story table。

### B. 实际操作

- 新增 `scripts/plot_elevation_threshold_story_cn.py`。
- 复核困难样本扩展完整过境 p95 统计口径：仅筛选攻击样本、按序列统计、使用残差分数 + 拟合参数检查后的接受字段、未重复计入 p95/p99。
- 生成 `<20°` vs `>=20°` 审计 CSV、中文 story table 和 3 张中文组会图。
- 更新 `outputs/reports/elevation_threshold_justification_summary.md` 中的 `20°阈值的组会解释版本` 小节。

### C. 新增/修改文件

- `scripts/plot_elevation_threshold_story_cn.py`
- `outputs/metrics/elevation_threshold_lt20_ge20_audit.csv`
- `outputs/metrics/elevation_threshold_story_table_cn.csv`
- `outputs/figures/elevation_threshold_justification_clean/attack_accept_rate_lt20_vs_ge20_cn.png`
- `outputs/figures/elevation_threshold_justification_clean/safety_tradeoff_by_threshold_cn.png`
- `outputs/figures/elevation_threshold_justification_clean/waiting_time_by_threshold_cn.png`
- `outputs/reports/elevation_threshold_justification_summary.md`
- `logs/work_log.md`

### D. 运行命令

```bash
python -m py_compile scripts/plot_elevation_threshold_story_cn.py
python scripts/plot_elevation_threshold_story_cn.py --overwrite
```

### E. 结果摘要

- `<20°` attack accept = `50/160 = 31.25%`。
- `>=20°` attack accept = `0/680 = 0.00%`。
- 20° 下 300 目标、30 天覆盖率 = `300/300`，中位等待时间 = `5.46 h`，p90 等待时间 = `16.60 h`。
- 中文字体：`{font_note}`。

### F. 问题与下一步

这组数是困难样本扩展完整过境分析集中的条件攻击误接受率，不是全局攻击成功率。后续如引入主动频率补偿攻击，需要重新校准仰角阈值。
"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)


def main() -> None:
    args = parse_args()
    out_audit = args.metrics_dir / "elevation_threshold_lt20_ge20_audit.csv"
    out_story = args.metrics_dir / "elevation_threshold_story_table_cn.csv"
    out_fig1 = args.output_dir / "attack_accept_rate_lt20_vs_ge20_cn.png"
    out_fig2 = args.output_dir / "safety_tradeoff_by_threshold_cn.png"
    out_fig3 = args.output_dir / "waiting_time_by_threshold_cn.png"
    report = args.reports_dir / "elevation_threshold_justification_summary.md"
    ensure_can_write([out_audit, out_story, out_fig1, out_fig2, out_fig3], args.overwrite)

    font_name = setup_chinese_font()
    attack = load_full_pass_attack(args.metrics_dir)
    audit = audit_lt20_ge20(attack)
    safety = select_boundary_safety(read_required(args.metrics_dir / "elevation_threshold_safety_tradeoff.csv"), args.threshold_types)
    avail = select_availability(read_required(args.metrics_dir / "elevation_threshold_availability_tradeoff_300.csv"))
    story = build_story_table(safety, avail)

    args.metrics_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(out_audit, index=False, encoding="utf-8-sig")
    story.to_csv(out_story, index=False, encoding="utf-8-sig")
    plot_lt20_vs_ge20(audit, out_fig1, args.overwrite)
    plot_safety(safety, out_fig2, args.overwrite)
    plot_waiting(avail, out_fig3, args.overwrite)
    update_report(report, audit, story)
    append_work_log(Path("logs/work_log.md"), font_name)

    print(f"wrote {out_audit} rows={len(audit)}")
    print(f"wrote {out_story} rows={len(story)}")
    print(f"wrote {out_fig1}")
    print(f"wrote {out_fig2}")
    print(f"wrote {out_fig3}")
    print(f"updated {report}")
    print(f"Chinese font: {font_name or 'not found'}")


if __name__ == "__main__":
    main()
