#!/usr/bin/env python
"""Run controlled Starlink multi-candidate orbit residual matcher."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DATASET_FIELDS = ["sim_id", "target_name", "target_norad_id", "scenario", "parameter_range_type", "t_rel_s", "f_sim_hz", "label"]
LIB_FIELDS = ["candidate_name", "candidate_norad_id", "t_rel_s", "f_geo_candidate_hz", "candidate_rank", "is_target"]


class InputError(ValueError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run orbit-based residual matcher.")
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--candidate-library", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confusion", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise InputError(message)


def validate_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def load_inputs(dataset_path: Path, library_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not dataset_path.exists():
        fail(f"orbit dataset 不存在: {dataset_path}")
    if not library_path.exists():
        fail(f"candidate library 不存在: {library_path}")
    dataset = pd.read_csv(dataset_path)
    library = pd.read_csv(library_path)
    miss_dataset = [c for c in DATASET_FIELDS if c not in dataset.columns]
    miss_lib = [c for c in LIB_FIELDS if c not in library.columns]
    if miss_dataset:
        fail(f"dataset 缺少字段: {', '.join(miss_dataset)}")
    if miss_lib:
        fail(f"candidate library 缺少字段: {', '.join(miss_lib)}")
    dataset["target_norad_id"] = dataset["target_norad_id"].astype(str)
    dataset["label"] = dataset["label"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    dataset["t_rel_s"] = pd.to_numeric(dataset["t_rel_s"], errors="coerce")
    library["t_rel_s"] = pd.to_numeric(library["t_rel_s"], errors="coerce")
    if dataset["t_rel_s"].isna().any() or library["t_rel_s"].isna().any():
        fail("输入时间字段存在非数值")
    return dataset, library


def fit_score(t_rel: np.ndarray, f_sim: np.ndarray, f_geo: np.ndarray) -> tuple[float, float, float]:
    x = t_rel - float(np.mean(t_rel))
    delta = f_sim - f_geo
    design = np.column_stack([np.ones_like(x), x])
    coeff, *_ = np.linalg.lstsq(design, delta, rcond=None)
    residual = delta - design @ coeff
    rmse = float(np.sqrt(np.mean(residual**2)))
    return rmse, float(coeff[0]), float(coeff[1])


def prepare_candidate_map(library: pd.DataFrame, reference_t: np.ndarray) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for norad, group in library.groupby("candidate_norad_id"):
        group = group.sort_values("t_rel_s")
        t = group["t_rel_s"].to_numpy(float)
        if len(t) != len(reference_t) or not np.allclose(t, reference_t, rtol=0, atol=1e-9):
            fail(f"candidate {norad} 的时间网格与 orbit dataset 不一致")
        result[str(norad)] = {
            "name": str(group["candidate_name"].iloc[0]),
            "norad": str(norad),
            "rank": int(group["candidate_rank"].iloc[0]),
            "is_target": bool(group["is_target"].iloc[0]),
            "f_geo": group["f_geo_candidate_hz"].to_numpy(float),
        }
    return result


def match(dataset: pd.DataFrame, library: pd.DataFrame) -> pd.DataFrame:
    reference = dataset.drop_duplicates("t_rel_s").sort_values("t_rel_s")["t_rel_s"].to_numpy(float)
    candidate_map = prepare_candidate_map(library, reference)
    rows: list[dict[str, Any]] = []
    groups = dataset.groupby("sim_id", sort=True)
    for index, (sim_id, seq) in enumerate(groups, start=1):
        if index % 100 == 0:
            print(f"已匹配 {index}/{len(groups)} 条序列")
        seq = seq.sort_values("t_rel_s")
        t = seq["t_rel_s"].to_numpy(float)
        if len(t) != len(reference) or not np.allclose(t, reference, rtol=0, atol=1e-9):
            fail(f"sim_id={sim_id} 时间网格与 candidate library 不一致")
        f_sim = seq["f_sim_hz"].to_numpy(float)
        first = seq.iloc[0]
        true_norad = str(first["label"])
        if true_norad not in candidate_map:
            fail(f"真实 target {true_norad} 不在 candidate library 中")
        scores: dict[str, tuple[float, float, float]] = {}
        for norad, cand in candidate_map.items():
            scores[norad] = fit_score(t, f_sim, cand["f_geo"])
        ranked = sorted(scores.items(), key=lambda item: item[1][0])
        pred_norad, pred_fit = ranked[0]
        true_fit = scores[true_norad]
        wrong = [(norad, fit) for norad, fit in ranked if norad != true_norad]
        best_wrong_norad, best_wrong_fit = wrong[0]
        rows.append(
            {
                "sim_id": sim_id,
                "target_name": str(first["target_name"]),
                "target_norad_id": str(first["target_norad_id"]),
                "true_label": true_norad,
                "predicted_name": candidate_map[pred_norad]["name"],
                "predicted_norad_id": pred_norad,
                "scenario": str(first["scenario"]),
                "parameter_range_type": str(first["parameter_range_type"]),
                "is_correct": pred_norad == true_norad,
                "best_score_rmse_hz": pred_fit[0],
                "true_score_rmse_hz": true_fit[0],
                "best_wrong_name": candidate_map[best_wrong_norad]["name"],
                "best_wrong_norad_id": best_wrong_norad,
                "best_wrong_score_rmse_hz": best_wrong_fit[0],
                "margin_hz": best_wrong_fit[0] - true_fit[0],
                "fitted_b_hz_for_pred": pred_fit[1],
                "fitted_k_hz_per_s_for_pred": pred_fit[2],
                "fitted_b_hz_for_true": true_fit[1],
                "fitted_k_hz_per_s_for_true": true_fit[2],
                "num_candidates_evaluated": len(candidate_map),
            }
        )
    return pd.DataFrame(rows)


def scenario_summary(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby("scenario")
        .agg(
            sequences=("sim_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_true_rmse=("true_score_rmse_hz", "mean"),
            median_true_rmse=("true_score_rmse_hz", "median"),
            mean_best_wrong_rmse=("best_wrong_score_rmse_hz", "mean"),
            median_best_wrong_rmse=("best_wrong_score_rmse_hz", "median"),
            mean_margin=("margin_hz", "mean"),
            median_margin=("margin_hz", "median"),
            error_count=("is_correct", lambda s: int((~s).sum())),
        )
        .reset_index()
    )


def write_confusion(results: pd.DataFrame, path: Path) -> pd.DataFrame:
    cols = sorted(results["predicted_norad_id"].unique(), key=str)
    idx = sorted(results["true_label"].unique(), key=str)
    confusion = pd.crosstab(results["true_label"], results["predicted_norad_id"]).reindex(index=idx, columns=cols, fill_value=0)
    confusion.index.name = "true_label"
    path.parent.mkdir(parents=True, exist_ok=True)
    confusion.to_csv(path)
    return confusion


def make_plots(results: pd.DataFrame, library: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    summary = scenario_summary(results)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(summary["scenario"], summary["accuracy"], color="#2f6f8f")
    ax.set_ylim(0, 1.05)
    ax.set_title("Orbit matching accuracy by scenario")
    ax.set_ylabel("accuracy")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "orbit_matching_accuracy_by_scenario.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    order = summary["scenario"].tolist()
    ax.boxplot([results.loc[results["scenario"] == s, "margin_hz"] for s in order], tick_labels=order, showfliers=False)
    ax.axhline(0, color="#8f2f2f", linestyle="--", linewidth=1)
    ax.set_title("Orbit matching margin by scenario")
    ax.set_ylabel("best_wrong_rmse - true_rmse (Hz)")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "orbit_matching_margin_by_scenario.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(summary))
    width = 0.36
    ax.bar(x - width / 2, summary["mean_true_rmse"], width, label="mean true RMSE", color="#2f6f8f")
    ax.bar(x + width / 2, summary["mean_best_wrong_rmse"], width, label="mean best wrong RMSE", color="#8f7a2f")
    ax.set_xticks(x)
    ax.set_xticklabels(summary["scenario"], rotation=20, ha="right")
    ax.set_title("Orbit true vs best wrong RMSE")
    ax.set_ylabel("RMSE (Hz)")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "orbit_matching_true_vs_best_wrong_rmse.png", dpi=160)
    plt.close(fig)

    top = results.drop_duplicates("best_wrong_norad_id").sort_values("best_wrong_score_rmse_hz").head(8)
    labels = ["true"] + [f"{r.best_wrong_name}\n{r.best_wrong_norad_id}" for _, r in top.iterrows()]
    values = [float(results["true_score_rmse_hz"].mean())] + [float(r.best_wrong_score_rmse_hz) for _, r in top.iterrows()]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(range(len(values)), values, color=["#2f6f8f"] + ["#8f7a2f"] * (len(values) - 1))
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax.set_title("Orbit candidate RMSE top-k")
    ax.set_ylabel("RMSE (Hz)")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "orbit_candidate_rmse_topk.png", dpi=160)
    plt.close(fig)


def write_report(path: Path, results: pd.DataFrame, library: pd.DataFrame, dataset: pd.DataFrame) -> None:
    summary = scenario_summary(results)
    candidate_count = library["candidate_norad_id"].nunique()
    target_name = str(dataset["target_name"].iloc[0])
    target_norad = str(dataset["target_norad_id"].iloc[0])
    station_name = str(dataset["station_name"].iloc[0])
    center_freq = float(dataset["center_freq_hz"].iloc[0])
    time_start = str(dataset.sort_values("t_rel_s")["t_abs_utc"].iloc[0])
    time_end = str(dataset.sort_values("t_rel_s")["t_abs_utc"].iloc[-1])
    closest = results.sort_values("best_wrong_score_rmse_hz").iloc[0]
    summary_lines = "\n".join(
        f"| `{row.scenario}` | {int(row.sequences)} | {row.accuracy:.4f} | {row.mean_true_rmse:.6f} | {row.median_true_rmse:.6f} | {row.mean_best_wrong_rmse:.6f} | {row.median_best_wrong_rmse:.6f} | {row.mean_margin:.6f} | {row.median_margin:.6f} | {int(row.error_count)} |"
        for _, row in summary.iterrows()
    )
    report = f"""# Controlled Starlink 多候选 Orbit-Based Matcher 报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 本轮目标

在 `controlled_starlink` 模式下，为多个 Starlink candidate 生成同一 station / frequency / time window 下的 `f_geo_candidate_hz`，并用 candidate-conditioned profile least-squares Doppler matcher 判断 target 仿真序列是否能匹配回 `STARLINK-1008`。本轮不使用 SatNOGS observation_id，`9424971` 不参与。

## 2. 输入数据

- target dataset：`outputs/datasets/orbit_based_frequency_dataset.csv`
- candidate library：`outputs/datasets/orbit_candidate_geometry_library.csv`
- mode：`controlled_starlink`
- target：`{target_name}`
- target NORAD：`{target_norad}`
- candidate 数量：{candidate_count}
- station：`{station_name}`
- center frequency：{center_freq:.0f} Hz
- time window：{time_start} 至 {time_end}

## 3. Candidate Library 构建方法

候选来自 `data/tle/starlink_tle.txt`，只选择 Starlink。target 必须包含在库中。其他候选按简单轨道相似度排序：

```text
abs(inclination_deg - target_inclination_deg)
+ 10 * abs(mean_motion_rev_per_day - target_mean_motion_rev_per_day)
```

所有候选使用与 target dataset 完全一致的时间网格、station、center frequency 和 Doppler 公式。

## 4. 匹配方法

对每条 `sim_id` 序列和每个 candidate，计算：

```text
delta_i = f_sim_i - f_geo_candidate_i
delta_i = b + k * (t_i - t0) + e_i
score = sqrt(mean(e_i^2))
```

先拟合 `b+k` 是为了吸收 registered offset 和线性慢漂移，使 RMSE 更集中反映候选轨道 Doppler 曲线形状差异。不能直接用原始 RMSE，因为常数偏置会主导结果。

## 5. 总体结果

- 总序列数：{len(results)}
- 总体 accuracy：{results['is_correct'].mean():.4f}
- 每条序列评估候选数：{int(results['num_candidates_evaluated'].iloc[0])}

## 6. 按 scenario 统计

| scenario | 序列数 | accuracy | mean true RMSE | median true RMSE | mean best wrong RMSE | median best wrong RMSE | mean margin | median margin | error count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{summary_lines}

## 7. 最接近 target 的错误 candidate

- candidate：`{closest.best_wrong_name}`
- NORAD：`{closest.best_wrong_norad_id}`
- best wrong RMSE：{closest.best_wrong_score_rmse_hz:.6f} Hz
- margin：{closest.margin_hz:.6f} Hz

## 8. 当前结果说明什么

- 在受控 Starlink 场景下，多候选 matcher 是否能识别目标；
- target 与相近 Starlink 候选的 Doppler 曲线差距可通过 true RMSE、best wrong RMSE 和 margin 初步观察；
- 当前只是 controlled Starlink 多候选匹配 sanity check。

## 9. 当前结果不能说明什么

- 不能说明真实 SatNOGS observation；
- 不能说明攻击成功率；
- 不能说明 pure CFO truth；
- 图表只用于 sanity check，不是强证明。

## 10. 下一步建议

- 扩展多 target；
- 寻找真实 Starlink SatNOGS observation；
- 在此基础上再加入 altitude difference / TCA shift / similar orbit 攻击场景。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        validate_outputs(
            [
                args.output,
                args.confusion,
                args.report,
                args.plots_dir / "orbit_candidate_rmse_topk.png",
                args.plots_dir / "orbit_matching_accuracy_by_scenario.png",
                args.plots_dir / "orbit_matching_margin_by_scenario.png",
                args.plots_dir / "orbit_matching_true_vs_best_wrong_rmse.png",
            ],
            args.overwrite,
        )
        dataset, library = load_inputs(args.dataset, args.candidate_library)
        results = match(dataset, library)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output, index=False)
        confusion = write_confusion(results, args.confusion)
        make_plots(results, library, args.plots_dir)
        write_report(args.report, results, library, dataset)
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    print(f"匹配完成: {args.output}")
    print(f"总体 accuracy: {results['is_correct'].mean():.4f}")
    print(f"候选数: {int(results['num_candidates_evaluated'].iloc[0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
