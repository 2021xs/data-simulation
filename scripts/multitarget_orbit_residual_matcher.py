#!/usr/bin/env python
"""Controlled Starlink multi-target orbit residual matcher."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    raise InputError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--candidate-library", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--confusion", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def output_prefix(output_path: Path) -> str:
    stem = output_path.stem
    for suffix in ["_matching_result_summary", "_result_summary"]:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def score_candidate(t_rel_s: np.ndarray, f_sim_hz: np.ndarray, f_geo_hz: np.ndarray) -> tuple[float, float, float]:
    x = t_rel_s - float(np.mean(t_rel_s))
    delta = f_sim_hz - f_geo_hz
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    residual = delta - design @ coef
    return float(np.sqrt(np.mean(residual**2))), float(coef[0]), float(coef[1])


def load_inputs(dataset_path: Path, library_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not dataset_path.exists():
        fail(f"dataset 不存在: {dataset_path}")
    if not library_path.exists():
        fail(f"candidate library 不存在: {library_path}")
    dataset = pd.read_csv(dataset_path)
    library = pd.read_csv(library_path)
    required_dataset = [
        "sim_id",
        "pass_id",
        "target_name",
        "target_norad_id",
        "scenario",
        "parameter_range_type",
        "t_rel_s",
        "f_sim_hz",
        "label",
    ]
    required_library = ["pass_id", "candidate_name", "candidate_norad_id", "t_rel_s", "f_geo_candidate_hz"]
    missing_dataset = [field for field in required_dataset if field not in dataset.columns]
    missing_library = [field for field in required_library if field not in library.columns]
    if missing_dataset:
        fail("dataset 缺少字段: " + ", ".join(missing_dataset))
    if missing_library:
        fail("candidate library 缺少字段: " + ", ".join(missing_library))
    dataset["label"] = dataset["label"].astype(str)
    dataset["target_norad_id"] = dataset["target_norad_id"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    return dataset, library


def build_library_maps(library: pd.DataFrame) -> dict[str, dict[str, dict[str, object]]]:
    maps: dict[str, dict[str, dict[str, object]]] = {}
    for pass_id, pass_group in library.groupby("pass_id"):
        candidate_map: dict[str, dict[str, object]] = {}
        for norad_id, candidate_group in pass_group.groupby("candidate_norad_id"):
            candidate_group = candidate_group.sort_values("t_rel_s")
            candidate_map[str(norad_id)] = {
                "name": str(candidate_group["candidate_name"].iloc[0]),
                "t": candidate_group["t_rel_s"].to_numpy(float),
                "f": candidate_group["f_geo_candidate_hz"].to_numpy(float),
            }
        maps[str(pass_id)] = candidate_map
    return maps


def match_sequences(dataset: pd.DataFrame, library: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    library_maps = build_library_maps(library)
    groups = dataset.groupby("sim_id", sort=True)
    total = len(groups)
    for idx, (sim_id, seq) in enumerate(groups, 1):
        if idx % 200 == 0:
            print(f"已匹配 {idx}/{total} 条序列")
        seq = seq.sort_values("t_rel_s")
        first = seq.iloc[0]
        pass_id = str(first["pass_id"])
        true_norad = str(first["label"])
        if pass_id not in library_maps:
            fail(f"pass_id 不在 candidate library 中: {pass_id}")
        t_rel_s = seq["t_rel_s"].to_numpy(float)
        f_sim_hz = seq["f_sim_hz"].to_numpy(float)
        scores: dict[str, tuple[float, float, float]] = {}
        for norad_id, candidate in library_maps[pass_id].items():
            candidate_t = candidate["t"]
            if len(candidate_t) != len(t_rel_s) or not np.allclose(candidate_t, t_rel_s, rtol=0, atol=1e-9):
                fail(f"时间网格不一致: {sim_id}/{norad_id}")
            scores[norad_id] = score_candidate(t_rel_s, f_sim_hz, candidate["f"])
        if true_norad not in scores:
            fail(f"true target 不在 pass candidate library 中: {true_norad}")
        ranked = sorted(scores.items(), key=lambda item: item[1][0])
        predicted_norad, predicted_fit = ranked[0]
        true_fit = scores[true_norad]
        best_wrong_norad, best_wrong_fit = [item for item in ranked if item[0] != true_norad][0]
        error_model_variant = str(first["error_model_variant"]) if "error_model_variant" in seq.columns else "baseline"
        rows.append(
            {
                "sim_id": sim_id,
                "sequence_id": sim_id,
                "pass_id": pass_id,
                "target_name": first["target_name"],
                "target_norad_id": str(first["target_norad_id"]),
                "true_target_norad_id": true_norad,
                "true_label": true_norad,
                "predicted_name": library_maps[pass_id][predicted_norad]["name"],
                "predicted_norad_id": predicted_norad,
                "scenario": first["scenario"],
                "error_model_variant": error_model_variant,
                "parameter_range_type": first["parameter_range_type"],
                "is_correct": predicted_norad == true_norad,
                "best_score_rmse_hz": predicted_fit[0],
                "true_score_rmse_hz": true_fit[0],
                "best_wrong_name": library_maps[pass_id][best_wrong_norad]["name"],
                "best_wrong_norad_id": best_wrong_norad,
                "best_wrong_score_rmse_hz": best_wrong_fit[0],
                "margin_hz": best_wrong_fit[0] - true_fit[0],
                "fitted_b_hz_for_pred": predicted_fit[1],
                "fitted_k_hz_per_s_for_pred": predicted_fit[2],
                "fitted_b_hz_for_true": true_fit[1],
                "fitted_k_hz_per_s_for_true": true_fit[2],
                "num_candidates_evaluated": len(scores),
            }
        )
    return pd.DataFrame(rows)


def summaries(results: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    scenario = (
        results.groupby("scenario")
        .agg(
            sequences=("sim_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_margin=("margin_hz", "mean"),
            median_margin=("margin_hz", "median"),
            mean_true_rmse=("true_score_rmse_hz", "mean"),
            mean_best_wrong_rmse=("best_wrong_score_rmse_hz", "mean"),
            error_count=("is_correct", lambda values: int((~values).sum())),
        )
        .reset_index()
    )
    target = (
        results.groupby(["target_name", "target_norad_id"])
        .agg(
            sequences=("sim_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_margin=("margin_hz", "mean"),
            median_margin=("margin_hz", "median"),
            min_margin=("margin_hz", "min"),
            error_count=("is_correct", lambda values: int((~values).sum())),
        )
        .reset_index()
    )
    return scenario, target


def write_plots(results: pd.DataFrame, confusion: pd.DataFrame, plots_dir: Path, prefix: str) -> list[Path]:
    plots_dir.mkdir(parents=True, exist_ok=True)
    scenario, target = summaries(results)
    paths: list[Path] = []
    for suffix, data, xcol, ycol, ylabel in [
        ("accuracy_by_scenario.png", scenario, "scenario", "accuracy", "accuracy"),
        ("margin_by_scenario.png", scenario, "scenario", "mean_margin", "mean margin (Hz)"),
        ("accuracy_by_target.png", target, "target_name", "accuracy", "accuracy"),
        ("margin_by_target.png", target, "target_name", "mean_margin", "mean margin (Hz)"),
    ]:
        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.bar(data[xcol].astype(str), data[ycol], color="#2f6f8f")
        if ycol == "accuracy":
            ax.set_ylim(0, 1.05)
        ax.set_ylabel(ylabel)
        ax.set_title(f"{prefix}_{suffix.replace('.png', '')}")
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        path = plots_dir / f"{prefix}_{suffix}"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path)

    fig, ax = plt.subplots(figsize=(8, 6))
    image = ax.imshow(confusion.to_numpy(float), cmap="Blues")
    ax.set_xticks(range(len(confusion.columns)))
    ax.set_xticklabels(confusion.columns, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(confusion.index)))
    ax.set_yticklabels(confusion.index, fontsize=7)
    ax.set_title(f"{prefix}_confusion_matrix")
    fig.colorbar(image, ax=ax)
    fig.tight_layout()
    path = plots_dir / f"{prefix}_confusion_matrix.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)

    hardest = results.sort_values("margin_hz").head(10)
    labels = [f"{row.target_name}->{row.best_wrong_name}" for _, row in hardest.iterrows()]
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.bar(labels, hardest["margin_hz"], color="#8f7a2f")
    ax.tick_params(axis="x", rotation=45, labelsize=7)
    ax.set_ylabel("margin (Hz)")
    ax.set_title(f"{prefix}_hardest_pairs")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    path = plots_dir / f"{prefix}_hardest_pairs.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)
    return paths


def write_report(path: Path, results: pd.DataFrame, library: pd.DataFrame, dataset: pd.DataFrame, confusion: pd.DataFrame) -> None:
    scenario, target = summaries(results)
    hardest = results.sort_values("margin_hz").iloc[0]
    candidate_counts = library.groupby("pass_id")["candidate_norad_id"].nunique()
    scenario_lines = "\n".join(
        f"| `{row.scenario}` | {int(row.sequences)} | {row.accuracy:.4f} | {row.mean_true_rmse:.6f} | {row.mean_best_wrong_rmse:.6f} | {row.mean_margin:.6f} | {int(row.error_count)} |"
        for _, row in scenario.iterrows()
    )
    target_lines = "\n".join(
        f"| `{row.target_name}` | `{row.target_norad_id}` | {row.accuracy:.4f} | {row.mean_margin:.6f} | {row.min_margin:.6f} | {int(row.error_count)} |"
        for _, row in target.iterrows()
    )
    variant = results["error_model_variant"].iloc[0] if "error_model_variant" in results.columns else "baseline"
    text = f"""# Controlled Starlink Multi-target Matcher 报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 本轮目标

在 `controlled_starlink` 模式下，对多 target Starlink 仿真数据运行 candidate-conditioned `b+k` profile least-squares Doppler matcher。本报告对应 `error_model_variant={variant}`。

## 输入数据

- dataset 序列数：{results.sim_id.nunique()}
- dataset 行数：{len(dataset)}
- candidate library 行数：{len(library)}
- pass 数：{library.pass_id.nunique()}
- 每个 pass candidate 数：{int(candidate_counts.min())} 到 {int(candidate_counts.max())}
- center_freq_hz：{float(dataset.center_freq_hz.iloc[0]):.0f}
- mode：controlled_starlink
- observation_id：null
- 9424971：未参与本轮 Starlink 仿真

## 匹配方法

对每条仿真序列和同一 `pass_id` 下的每个候选曲线，拟合 `delta_i = b + k(t_i-t0) + e_i`，并用 `RMSE(e_i)` 作为 score。拟合 `b+k` 是为了吸收 registered offset 和一阶慢漂移，让比较聚焦在 Doppler 曲线形状上。

## 总体结果

- accuracy：{results.is_correct.mean():.4f}
- min margin：{results.margin_hz.min():.6f} Hz

## 按 scenario 统计

| scenario | 序列数 | accuracy | mean true RMSE | mean best wrong RMSE | mean margin | error count |
|---|---:|---:|---:|---:|---:|---:|
{scenario_lines}

## 按 target 统计

| target | NORAD | accuracy | mean margin | min margin | error count |
|---|---|---:|---:|---:|---:|
{target_lines}

## 最容易混淆的样本对

- target：`{hardest.target_name}` / `{hardest.target_norad_id}`
- best wrong candidate：`{hardest.best_wrong_name}` / `{hardest.best_wrong_norad_id}`
- min margin：{hardest.margin_hz:.6f} Hz

## 边界说明

当前只是 controlled Starlink TLE-based simulation baseline，不是真实 SatNOGS observation，不是攻击场景，不说明攻击成功率，也不说明 pure CFO truth。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；噪声是第一版高斯近似。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    prefix = output_prefix(args.output)
    plot_probe = args.plots_dir / f"{prefix}_accuracy_by_scenario.png"
    try:
        check_outputs([args.output, args.confusion, args.report, plot_probe], args.overwrite)
        dataset, library = load_inputs(args.dataset, args.candidate_library)
        results = match_sequences(dataset, library)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output, index=False)
        labels = sorted(results["true_label"].unique(), key=str)
        columns = sorted(results["predicted_norad_id"].unique(), key=str)
        confusion = pd.crosstab(results["true_label"], results["predicted_norad_id"]).reindex(index=labels, columns=columns, fill_value=0)
        confusion.index.name = "true_label"
        args.confusion.parent.mkdir(parents=True, exist_ok=True)
        confusion.to_csv(args.confusion)
        write_plots(results, confusion, args.plots_dir, prefix)
        write_report(args.report, results, library, dataset, confusion)
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    print(f"多 target matcher 完成: {args.output}")
    print(f"总体 accuracy: {results.is_correct.mean():.4f}")
    print(f"min margin: {results.margin_hz.min():.6f} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
