#!/usr/bin/env python
"""Plot target pass-quality availability audit outputs."""

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
    p.add_argument("--availability", type=Path, default=Path("outputs/metrics/target_pass_quality_availability.csv"))
    p.add_argument("--pass-detail", type=Path, default=Path("outputs/metrics/target_pass_quality_availability_pass_detail.csv"))
    p.add_argument("--summary", type=Path, default=Path("outputs/metrics/target_pass_quality_availability_summary.csv"))
    p.add_argument("--bin-summary", type=Path, default=Path("outputs/metrics/target_pass_quality_bin_summary.csv"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/pass_quality_availability"))
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--report", type=Path, default=Path("outputs/reports/target_pass_quality_availability_summary.md"))
    p.add_argument("--input-suffix", default="")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=170)
    plt.close(fig)


def with_suffix(path: Path, suffix: str) -> Path:
    if not suffix:
        return path
    clean = suffix.strip("_")
    return path.with_name(f"{path.stem}_{clean}{path.suffix}")


def figure_name(name: str, suffix: str) -> str:
    if not suffix:
        return name
    clean = suffix.strip("_")
    p = Path(name)
    return f"{p.stem}_{clean}{p.suffix}"


def write_report(args, availability: pd.DataFrame, detail: pd.DataFrame, summary: pd.DataFrame, bin_summary: pd.DataFrame) -> None:
    latest_duration = int(summary["duration_days"].max())
    latest = availability[availability["duration_days"] == latest_duration]
    s30 = summary[summary["duration_days"] == latest_duration].iloc[0]
    lines = []
    for _, row in summary.sort_values("duration_days").iterrows():
        lines.append(
            f"- {int(row.duration_days)} days: high-quality targets = `{int(row.targets_with_high_quality_pass_count)}/{int(row.total_targets)}`, "
            f"only-low = `{int(row.only_low_single_station_count)}`, no-visible = `{int(row.no_visible_target_count)}`, "
            f"median time-to-first-HQ = `{row.median_time_to_first_high_quality_pass_hours:.2f} h`, "
            f"p90 = `{row.p90_time_to_first_high_quality_pass_hours:.2f} h`"
        )
    only_low = latest[latest["availability_class"] == "only_low_single_station"]
    only_low_text = only_low[["target_name", "target_sat_id", "total_visible_passes", "max_elevation_deg_max"]].to_markdown(index=False) if len(only_low) else "30 天窗口内没有 only-low target。"
    delayed = latest[latest["availability_class"] == "delayed_authentication"]
    delayed_text = delayed[["target_name", "target_sat_id", "time_to_first_high_quality_pass_hours", "high_quality_pass_count"]].to_markdown(index=False) if len(delayed) else "30 天窗口内没有 delayed target。"
    target_count = int(s30.target_count if "target_count" in s30.index else s30.total_targets)
    comparison_text = "未读取 20-target baseline summary。"
    baseline_path = Path("outputs/metrics/target_pass_quality_availability_summary.csv")
    if baseline_path.exists() and target_count != 20:
        baseline = pd.read_csv(baseline_path)
        if not baseline.empty:
            b30 = baseline[baseline["duration_days"] == 30]
            if len(b30):
                b = b30.iloc[0]
                comparison_text = (
                    f"- 20-target baseline: `{int(b.targets_with_high_quality_pass_count)}/{int(b.total_targets)}` 有 high-quality pass，"
                    f"only-low = `{int(b.only_low_single_station_count)}`，"
                    f"median time-to-first-HQ = `{b.median_time_to_first_high_quality_pass_hours:.2f} h`，"
                    f"p90 = `{b.p90_time_to_first_high_quality_pass_hours:.2f} h`。\n"
                    f"- 本轮 {target_count}-target: `{int(s30.targets_with_high_quality_pass_count)}/{target_count}` 有 high-quality pass，"
                    f"only-low = `{int(s30.only_low_single_station_count)}`，"
                    f"median time-to-first-HQ = `{s30.median_time_to_first_high_quality_pass_hours:.2f} h`，"
                    f"p90 = `{s30.p90_time_to_first_high_quality_pass_hours:.2f} h`。"
                )
    only_low_count = int(s30.only_low_single_station_count)
    only_low_frac = only_low_count / target_count if target_count else 0.0
    scan_step = "unknown"
    if "notes" in detail.columns and len(detail):
        notes = str(detail["notes"].dropna().iloc[0])
        for part in notes.split(";"):
            if part.startswith("scan_step_s="):
                scan_step = part.split("=", 1)[1]
    selection_rule = "controlled_starlink_20target_selection_table"
    if "target_selection_rule" in availability.columns and availability["target_selection_rule"].notna().any():
        vals = [str(v) for v in availability["target_selection_rule"].dropna().unique() if str(v)]
        if vals:
            selection_rule = vals[0]
    text = f"""# Target Pass-Quality Availability Summary

## 1. 实验目的

verifier v3 使用 pass-quality-aware DEFER 规则：low-quality full-pass 不直接 ACCEPT，而是等待 high-quality full-pass。本轮检查该规则在当前单站设置下的可用性，回答目标卫星是否能在合理时间内等到 `max_elevation_deg >= 20` 的认证窗口。

## 2. 设置

- station: `controlled_example_station`, lat=`52.2100`, lon=`5.1600`, alt=`14 m`
- target selection: `{selection_rule}`
- target_count: `{target_count}`
- visible pass finder: 复用现有 Skyfield / SGP4 `find_pass` 逻辑
- visible mask: 使用当前 time_window 的 `min_elevation_deg`
- audit scan step: `{scan_step} s`；用于 availability 统计，elevation 定义与当前 verifier/pass finder 一致
- low: `max_elevation_deg < 20`
- medium: `20 <= max_elevation_deg < 40`
- high: `max_elevation_deg >= 40`
- high-quality pass for verifier v3: `max_elevation_deg >= 20`

## 3. 总体结果

{chr(10).join(lines)}

30 天窗口下：

- total targets = `{target_count}`
- visible target count = `{int(s30.visible_target_count)}`
- targets with high-quality pass = `{int(s30.targets_with_high_quality_pass_count)}`
- only-low targets = `{only_low_count}`，占比 `{only_low_frac:.2%}`
- mean time-to-first-high-quality = `{s30.mean_time_to_first_high_quality_pass_hours:.2f} h`
- median time-to-first-high-quality = `{s30.median_time_to_first_high_quality_pass_hours:.2f} h`
- p90 time-to-first-high-quality = `{s30.p90_time_to_first_high_quality_pass_hours:.2f} h`

## 4. Only-Low Target 分析

{only_low_text}

如果存在 only-low target，说明单站 v3 可能长期 DEFER，需要考虑更长 audit window、多个低仰角 pass 聚合，或 multi-station consistency。

## 5. Delayed Target 分析

{delayed_text}

## 6. 与 20-Target 结果对比

{comparison_text}

## 7. 对 Verifier v3 的影响

如果大多数目标在 7/14/30 天内都有 high-quality pass，则当前 v3 的可用性较好；如果 only-low 或 delayed target 比例高，则单站规则会带来较多 DEFER，需要进入 multi-station availability audit。

本轮仍支持 `max_elevation_deg >= 20` 作为当前 high-quality pass 初步规则；它不会被可用性结果自动推翻，但如果目标长期无法等到 20 度以上 pass，则需要从系统层面补站或延长等待窗口。

## 8. 阶段性结论

1. 当前单站 availability audit 给出了 v3 DEFER 规则的可用性边界。
2. high-quality pass 的覆盖率决定 v3 能否从 DEFER 进入 ACCEPT。
3. only-low targets 是 multi-station consistency 的优先候选。
4. delayed targets 更适合调度式 high-quality pass challenge。
5. 下一步应根据 only-low / delayed 比例决定是否进入 multi-station availability audit。
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.availability = with_suffix(args.availability, args.input_suffix)
    args.pass_detail = with_suffix(args.pass_detail, args.input_suffix)
    args.summary = with_suffix(args.summary, args.input_suffix)
    args.bin_summary = with_suffix(args.bin_summary, args.input_suffix)
    if args.output_dir is not None:
        args.figures_dir = args.output_dir
    if args.input_suffix:
        clean = args.input_suffix.strip("_")
        if args.report == Path("outputs/reports/target_pass_quality_availability_summary.md"):
            args.report = Path(f"outputs/reports/target_pass_quality_availability_{clean}_summary.md")
        else:
            args.report = with_suffix(args.report, args.input_suffix)
    for p in [args.availability, args.pass_detail, args.summary, args.bin_summary]:
        if not p.exists():
            fail(f"missing input: {p}")
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    availability = pd.read_csv(args.availability)
    detail = pd.read_csv(args.pass_detail)
    summary = pd.read_csv(args.summary)
    bin_summary = pd.read_csv(args.bin_summary)

    order = ["readily_authenticatable", "delayed_authentication", "only_low_single_station", "no_visible_pass"]
    class_counts = availability.groupby(["duration_days", "availability_class"]).size().reset_index(name="count")
    latest_duration = int(availability["duration_days"].max())
    latest = availability[availability["duration_days"] == latest_duration]
    latest_counts = latest["availability_class"].value_counts().reindex(order).fillna(0)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(latest_counts.index, latest_counts.values)
    ax.set_ylabel("target count")
    ax.set_title(f"Target Availability Class Counts ({latest_duration} days)")
    ax.tick_params(axis="x", rotation=25)
    save(fig, args.figures_dir / figure_name("target_availability_class_counts.png", args.input_suffix))

    hq = availability[availability["has_high_quality_pass"]]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(hq["time_to_first_high_quality_pass_hours"].dropna(), bins=20, color="#4f7cac", edgecolor="white")
    ax.set_xlabel("time_to_first_high_quality_pass_hours")
    ax.set_ylabel("target-window count")
    ax.set_title("Time to First High-Quality Pass")
    save(fig, args.figures_dir / figure_name("time_to_first_high_quality_pass_distribution.png", args.input_suffix))

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.hist(latest["high_quality_pass_count"], bins=range(0, int(latest["high_quality_pass_count"].max()) + 3), color="#65a765", edgecolor="white")
    ax.set_xlabel("high_quality_pass_count")
    ax.set_ylabel("target count")
    ax.set_title(f"High-Quality Pass Count Distribution ({latest_duration} days)")
    save(fig, args.figures_dir / figure_name("high_quality_pass_count_distribution.png", args.input_suffix))

    sorted_latest = latest.sort_values("max_elevation_deg_max")
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(sorted_latest["target_name"], sorted_latest["max_elevation_deg_max"])
    ax.axhline(20, color="black", linestyle="--", label="20 deg")
    ax.axhline(40, color="gray", linestyle=":", label="40 deg")
    ax.set_ylabel("max_elevation_deg_max")
    ax.set_title(f"Max Elevation by Target ({latest_duration} days)")
    ax.tick_params(axis="x", rotation=70)
    ax.legend()
    save(fig, args.figures_dir / figure_name("max_elevation_distribution_by_target.png", args.input_suffix))

    fig, ax = plt.subplots(figsize=(8, 4.8))
    d = bin_summary[bin_summary["duration_days"] == latest_duration].set_index("elevation_bin").reindex(["low", "medium", "high"]).fillna(0)
    ax.bar(d.index, d["total_passes"])
    ax.set_ylabel("pass count")
    ax.set_title(f"Elevation Bin Pass Counts ({latest_duration} days)")
    save(fig, args.figures_dir / figure_name("elevation_bin_pass_counts.png", args.input_suffix))

    only_low = latest[latest["availability_class"] == "only_low_single_station"].sort_values("max_elevation_deg_max")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    if len(only_low):
        ax.bar(only_low["target_name"], only_low["max_elevation_deg_max"])
        ax.axhline(20, color="black", linestyle="--")
        ax.tick_params(axis="x", rotation=60)
    else:
        ax.text(0.5, 0.5, "No only-low targets", ha="center", va="center", transform=ax.transAxes)
        ax.set_xticks([])
    ax.set_ylabel("max_elevation_deg_max")
    ax.set_title(f"Only-Low Targets ({latest_duration} days)")
    save(fig, args.figures_dir / figure_name("only_low_targets_bar.png", args.input_suffix))

    write_report(args, availability, detail, summary, bin_summary)
    print(f"wrote figures in {args.figures_dir}")
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
