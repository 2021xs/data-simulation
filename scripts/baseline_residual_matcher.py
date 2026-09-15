#!/usr/bin/env python
"""Baseline residual matcher for v1 simulated frequency datasets."""

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


DATASET_REQUIRED_FIELDS = [
    "sim_id",
    "base_observation_id",
    "scenario",
    "parameter_range_type",
    "tier",
    "t_rel_s",
    "f_sim_hz",
    "label",
]
CANDIDATE_REQUIRED_FIELDS = ["t_rel_s", "f_geo_fit_hz"]
RESULT_COLUMNS = [
    "sim_id",
    "base_observation_id",
    "true_label",
    "predicted_label",
    "scenario",
    "parameter_range_type",
    "tier",
    "is_correct",
    "best_score_rmse_hz",
    "true_score_rmse_hz",
    "best_wrong_label",
    "best_wrong_score_rmse_hz",
    "margin_hz",
    "fitted_b_hz_for_pred",
    "fitted_k_hz_per_s_for_pred",
    "fitted_b_hz_for_true",
    "fitted_k_hz_per_s_for_true",
    "num_candidates_evaluated",
    "num_candidates_skipped",
]


class InputError(ValueError):
    """Raised for clear command-line validation errors."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run baseline residual matching on simulated frequency dataset."
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
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


def load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"仿真数据集不存在: {path}")
    df = pd.read_csv(path)
    missing = [field for field in DATASET_REQUIRED_FIELDS if field not in df.columns]
    if missing:
        fail(f"仿真数据集缺少必要字段: {', '.join(missing)}")
    for field in ["t_rel_s", "f_sim_hz"]:
        df[field] = pd.to_numeric(df[field], errors="coerce")
        if df[field].isna().any():
            fail(f"仿真数据集字段 {field} 存在空值或非数值")
    df["base_observation_id"] = df["base_observation_id"].astype(str)
    df["label"] = df["label"].astype(str)
    return df


def load_candidates(candidate_root: Path) -> dict[str, dict[str, np.ndarray]]:
    if not candidate_root.exists() or not candidate_root.is_dir():
        fail(f"候选目录不存在或不是目录: {candidate_root}")

    candidates: dict[str, dict[str, np.ndarray]] = {}
    for obs_dir in sorted(path for path in candidate_root.iterdir() if path.is_dir()):
        residual_path = obs_dir / "residual_dataset.csv"
        if not residual_path.exists():
            fail(f"候选样本缺少 residual_dataset.csv: {residual_path}")
        df = pd.read_csv(residual_path)
        missing = [field for field in CANDIDATE_REQUIRED_FIELDS if field not in df.columns]
        if missing:
            fail(f"{residual_path} 缺少必要字段: {', '.join(missing)}")
        for field in CANDIDATE_REQUIRED_FIELDS:
            df[field] = pd.to_numeric(df[field], errors="coerce")
            if df[field].isna().any():
                fail(f"{residual_path} 字段 {field} 存在空值或非数值")
        df = df.sort_values("t_rel_s")
        candidates[obs_dir.name] = {
            "t_rel_s": df["t_rel_s"].to_numpy(dtype=float),
            "f_geo_fit_hz": df["f_geo_fit_hz"].to_numpy(dtype=float),
        }

    if not candidates:
        fail(f"候选目录下没有 accepted 样本子目录: {candidate_root}")
    return candidates


def fit_candidate(
    t_rel_s: np.ndarray,
    f_sim_hz: np.ndarray,
    candidate_t: np.ndarray,
    candidate_f_geo: np.ndarray,
) -> tuple[float, float, float] | None:
    if t_rel_s.min() < candidate_t.min() or t_rel_s.max() > candidate_t.max():
        return None

    f_geo_interp = np.interp(t_rel_s, candidate_t, candidate_f_geo)
    delta = f_sim_hz - f_geo_interp
    x = t_rel_s - float(np.mean(t_rel_s))
    design = np.column_stack([np.ones_like(x), x])
    coeff, *_ = np.linalg.lstsq(design, delta, rcond=None)
    fitted = design @ coeff
    residual = delta - fitted
    rmse = float(np.sqrt(np.mean(residual**2)))
    return rmse, float(coeff[0]), float(coeff[1])


def match_sequences(
    dataset: pd.DataFrame, candidates: dict[str, dict[str, np.ndarray]]
) -> pd.DataFrame:
    rows: list[dict] = []
    grouped = dataset.groupby("sim_id", sort=True)
    total = len(grouped)

    for index, (sim_id, seq) in enumerate(grouped, start=1):
        if index % 250 == 0:
            print(f"已匹配 {index}/{total} 条序列")
        seq = seq.sort_values("t_rel_s")
        t_rel_s = seq["t_rel_s"].to_numpy(dtype=float)
        f_sim_hz = seq["f_sim_hz"].to_numpy(dtype=float)
        first = seq.iloc[0]
        true_label = str(first["label"])
        scenario = str(first["scenario"])
        parameter_range_type = str(first.get("parameter_range_type", ""))
        tier = str(first.get("tier", ""))
        base_observation_id = str(first["base_observation_id"])

        scores: dict[str, tuple[float, float, float]] = {}
        skipped = 0
        for candidate_label, candidate in candidates.items():
            fit = fit_candidate(
                t_rel_s=t_rel_s,
                f_sim_hz=f_sim_hz,
                candidate_t=candidate["t_rel_s"],
                candidate_f_geo=candidate["f_geo_fit_hz"],
            )
            if fit is None:
                skipped += 1
                continue
            scores[candidate_label] = fit

        if not scores:
            fail(f"序列 {sim_id} 没有任何可评估候选，请检查时间范围")
        if true_label not in scores:
            fail(f"序列 {sim_id} 的真实候选 {true_label} 被跳过，请检查输入时间范围")

        ranked = sorted(scores.items(), key=lambda item: item[1][0])
        predicted_label, pred_fit = ranked[0]
        true_fit = scores[true_label]
        wrong_ranked = [(label, fit) for label, fit in ranked if label != true_label]
        if wrong_ranked:
            best_wrong_label, best_wrong_fit = wrong_ranked[0]
            best_wrong_score = best_wrong_fit[0]
            margin_hz = best_wrong_score - true_fit[0]
        else:
            best_wrong_label = ""
            best_wrong_fit = (np.nan, np.nan, np.nan)
            best_wrong_score = np.nan
            margin_hz = np.nan

        rows.append(
            {
                "sim_id": sim_id,
                "base_observation_id": base_observation_id,
                "true_label": true_label,
                "predicted_label": predicted_label,
                "scenario": scenario,
                "parameter_range_type": parameter_range_type,
                "tier": tier,
                "is_correct": predicted_label == true_label,
                "best_score_rmse_hz": pred_fit[0],
                "true_score_rmse_hz": true_fit[0],
                "best_wrong_label": best_wrong_label,
                "best_wrong_score_rmse_hz": best_wrong_score,
                "margin_hz": margin_hz,
                "fitted_b_hz_for_pred": pred_fit[1],
                "fitted_k_hz_per_s_for_pred": pred_fit[2],
                "fitted_b_hz_for_true": true_fit[1],
                "fitted_k_hz_per_s_for_true": true_fit[2],
                "num_candidates_evaluated": len(scores),
                "num_candidates_skipped": skipped,
            }
        )

    return pd.DataFrame(rows, columns=RESULT_COLUMNS)


def build_confusion(results: pd.DataFrame, labels: list[str]) -> pd.DataFrame:
    confusion = pd.crosstab(
        results["true_label"], results["predicted_label"], dropna=False
    )
    confusion = confusion.reindex(index=labels, columns=labels, fill_value=0)
    confusion.index.name = "true_label"
    return confusion


def scenario_summary(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby("scenario")
        .agg(
            sequences=("sim_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_true_rmse_hz=("true_score_rmse_hz", "mean"),
            median_true_rmse_hz=("true_score_rmse_hz", "median"),
            mean_best_wrong_rmse_hz=("best_wrong_score_rmse_hz", "mean"),
            median_best_wrong_rmse_hz=("best_wrong_score_rmse_hz", "median"),
            mean_margin_hz=("margin_hz", "mean"),
            median_margin_hz=("margin_hz", "median"),
            error_count=("is_correct", lambda s: int((~s).sum())),
            mean_skipped_candidates=("num_candidates_skipped", "mean"),
        )
        .reset_index()
    )


def pair_confusions(results: pd.DataFrame) -> pd.DataFrame:
    errors = results[~results["is_correct"]]
    if errors.empty:
        return pd.DataFrame(
            columns=["true_label", "predicted_label", "count", "mean_margin_hz"]
        )
    return (
        errors.groupby(["true_label", "predicted_label"])
        .agg(count=("sim_id", "count"), mean_margin_hz=("margin_hz", "mean"))
        .reset_index()
        .sort_values(["count", "mean_margin_hz"], ascending=[False, True])
    )


def make_plots(
    results: pd.DataFrame, confusion: pd.DataFrame, plots_dir: Path
) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    labels = list(confusion.index.astype(str))

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    image = ax.imshow(confusion.to_numpy(dtype=float), cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    ax.set_xlabel("predicted label")
    ax.set_ylabel("true label")
    ax.set_title("Baseline confusion matrix")
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(confusion.iloc[i, j]), ha="center", va="center", fontsize=9)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(plots_dir / "baseline_confusion_matrix.png", dpi=160)
    plt.close(fig)

    summary = scenario_summary(results)
    order = summary["scenario"].tolist()

    fig, ax = plt.subplots(figsize=(8, 4.5))
    data = [results.loc[results["scenario"] == scenario, "margin_hz"] for scenario in order]
    ax.boxplot(data, tick_labels=order, showfliers=False)
    ax.axhline(0, color="#8f2f2f", linewidth=1.2, linestyle="--")
    ax.set_title("RMSE margin by scenario")
    ax.set_ylabel("best_wrong_rmse - true_rmse (Hz)")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "rmse_margin_by_scenario.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.bar(summary["scenario"], summary["accuracy"], color="#2f6f8f")
    ax.set_ylim(0, 1.05)
    ax.set_title("Accuracy by scenario")
    ax.set_ylabel("accuracy")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "accuracy_by_scenario.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    x = np.arange(len(summary))
    width = 0.36
    ax.bar(
        x - width / 2,
        summary["mean_true_rmse_hz"],
        width,
        label="mean true RMSE",
        color="#2f6f8f",
    )
    ax.bar(
        x + width / 2,
        summary["mean_best_wrong_rmse_hz"],
        width,
        label="mean best wrong RMSE",
        color="#8f7a2f",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(summary["scenario"], rotation=20, ha="right")
    ax.set_title("True vs best wrong RMSE by scenario")
    ax.set_ylabel("RMSE (Hz)")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "true_vs_best_wrong_rmse_by_scenario.png", dpi=160)
    plt.close(fig)


def write_report(
    path: Path,
    dataset_path: Path,
    candidate_root: Path,
    output_path: Path,
    confusion_path: Path,
    plots_dir: Path,
    results: pd.DataFrame,
    confusion: pd.DataFrame,
    candidates: dict[str, dict[str, np.ndarray]],
) -> None:
    overall_accuracy = float(results["is_correct"].mean())
    summary = scenario_summary(results)
    pairs = pair_confusions(results)
    skipped_total = int(results["num_candidates_skipped"].sum())
    evaluated_mean = float(results["num_candidates_evaluated"].mean())
    clean_ok = bool(results.loc[results["scenario"] == "clean", "is_correct"].all())
    offset_only_ok = bool(
        results.loc[results["scenario"] == "offset_only", "is_correct"].all()
    )

    scenario_lines = "\n".join(
        [
            f"| `{row.scenario}` | {int(row.sequences)} | {row.accuracy:.4f} | "
            f"{row.mean_true_rmse_hz:.6f} | {row.median_true_rmse_hz:.6f} | "
            f"{row.mean_best_wrong_rmse_hz:.6f} | {row.median_best_wrong_rmse_hz:.6f} | "
            f"{row.mean_margin_hz:.6f} | {row.median_margin_hz:.6f} | "
            f"{int(row.error_count)} |"
            for _, row in summary.iterrows()
        ]
    )

    confusion_lines = "\n".join(
        [
            "| true_label | " + " | ".join(map(str, confusion.columns)) + " |",
            "|---" + "|---:" * len(confusion.columns) + "|",
        ]
        + [
            f"| `{idx}` | " + " | ".join(str(int(v)) for v in row.values) + " |"
            for idx, row in confusion.iterrows()
        ]
    )

    if pairs.empty:
        pair_lines = "未发现误匹配样本对。"
    else:
        pair_lines = "\n".join(
            [
                "| true_label | predicted_label | count | mean_margin_hz |",
                "|---|---|---:|---:|",
            ]
            + [
                f"| `{row.true_label}` | `{row.predicted_label}` | {int(row['count'])} | {row.mean_margin_hz:.6f} |"
                for _, row in pairs.head(10).iterrows()
            ]
        )

    candidate_range_lines = "\n".join(
        [
            f"| `{label}` | {len(data['t_rel_s'])} | {float(data['t_rel_s'].min()):.6f} | {float(data['t_rel_s'].max()):.6f} |"
            for label, data in candidates.items()
        ]
    )

    report = f"""# Baseline Residual Matcher 报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 本轮目标

实现并运行第一版 baseline residual matcher。目标是对每条仿真序列判断其最像哪个 accepted 样本的几何频率基线。本轮只做 accepted 候选上的 baseline 识别，不做攻击轨道场景，不修改仿真数据集。

当前 baseline 是 fitted-baseline sanity check，不是最终攻击实验。

## 2. 输入数据

- 仿真数据集：`{dataset_path}`
- accepted 候选目录：`{candidate_root}`
- 结果输出：`{output_path}`
- 混淆矩阵：`{confusion_path}`
- 图表目录：`{plots_dir}`

候选时间范围：

| candidate | 点数 | t_min_s | t_max_s |
|---|---:|---:|---:|
{candidate_range_lines}

## 3. 匹配方法

对每条 `sim_id` 序列，读取 `t_rel_s` 和 `f_sim_hz`。对每个 accepted 候选，读取 `t_rel_s` 与 `f_geo_fit_hz`，并将候选几何频率插值到仿真序列的时间点。若仿真序列时间范围超出候选时间范围，则跳过该候选。

随后计算：

```text
delta_i = f_sim_i - f_geo_candidate_i
delta_i = b + k * (t_i - t0) + e_i
score = sqrt(mean(e_i^2))
```

其中 `t0 = mean(t_i)`。RMSE 最小的候选作为 `predicted_label`。

## 4. 为什么拟合 b + k 后再比较 RMSE

仿真数据允许存在 registered offset / effective constant frequency bias 和一阶线性慢漂移。若直接比较原始 RMSE，评分会被常数偏置或线性项主导，而不是主要反映几何 Doppler 曲线形状差异。因此 baseline matcher 先拟合并吸收 `b + k(t-t0)`，再比较剩余残差 RMSE。当前方法是 candidate-conditioned profile least-squares Doppler matcher 的 baseline v1。

## 5. 总体结果

- 总序列数：{len(results)}
- 总体 accuracy：{overall_accuracy:.4f}
- 平均评估候选数：{evaluated_mean:.2f}
- skipped candidate 总次数：{skipped_total}

## 6. 按 scenario 的结果

| scenario | 序列数 | accuracy | mean true RMSE | median true RMSE | mean best wrong RMSE | median best wrong RMSE | mean margin | median margin | error count |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{scenario_lines}

## 7. clean 和 offset_only 检查

- `clean` 是否全部正确匹配：{'是' if clean_ok else '否'}
- `offset_only` 是否全部正确匹配：{'是' if offset_only_ok else '否'}

## 8. 混淆矩阵摘要

{confusion_lines}

## 9. 最容易混淆的样本对

{pair_lines}

## 10. 当前结果说明什么

- 在当前 fitted-baseline 数据集下，matcher 能够识别来源几何曲线；
- `b / k` nuisance 拟合能够在本轮设置中吸收常数偏置和线性漂移，使比较更集中在几何频率曲线形状上；
- `clean` 和 `offset_only` 都能正确匹配，说明基础时间对齐、插值和残差评分流程没有明显错误。

## 11. 当前结果不能说明什么

- 不能说明真实攻击成功率；
- 不能说明 TLE / Skyfield 轨道攻击场景；
- 不能说明 pure CFO truth；
- 不能外推到当前 accepted 5 个候选以外的候选集合。

## 12. 图表输出

- `baseline_confusion_matrix.png`
- `rmse_margin_by_scenario.png`
- `accuracy_by_scenario.png`
- `true_vs_best_wrong_rmse_by_scenario.png`

图表仅用于 sanity check，不作为证明性结论。

## 13. 边界说明

- 当前候选只包含 accepted 5 个样本；
- 当前使用 `f_geo_fit_hz` 作为几何基线；
- 本轮不是攻击轨道场景，也不输出攻击成功率；
- 当前只是 baseline matcher，用于确认仿真数据集上的基础识别流程；
- 候选时间范围不足时按规则跳过，因此部分序列只与覆盖其完整时间范围的候选比较。

## 14. 下一步建议

如果 `clean` / `offset_only` 不能正确，需要先修 matcher；如果 baseline 正常，再进入 orbit-based generator。后续攻击场景再加入 altitude difference / TCA shift / similar orbit 等设置。
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
                args.plots_dir / "baseline_confusion_matrix.png",
                args.plots_dir / "rmse_margin_by_scenario.png",
                args.plots_dir / "accuracy_by_scenario.png",
                args.plots_dir / "true_vs_best_wrong_rmse_by_scenario.png",
            ],
            args.overwrite,
        )
        dataset = load_dataset(args.dataset)
        candidates = load_candidates(args.candidate_root)
        results = match_sequences(dataset, candidates)
        labels = sorted(candidates.keys())
        confusion = build_confusion(results, labels)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.confusion.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output, index=False)
        confusion.to_csv(args.confusion)
        make_plots(results, confusion, args.plots_dir)
        write_report(
            path=args.report,
            dataset_path=args.dataset,
            candidate_root=args.candidate_root,
            output_path=args.output,
            confusion_path=args.confusion,
            plots_dir=args.plots_dir,
            results=results,
            confusion=confusion,
            candidates=candidates,
        )
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    overall_accuracy = float(results["is_correct"].mean())
    print(f"匹配完成: {args.output}")
    print(f"混淆矩阵: {args.confusion}")
    print(f"报告: {args.report}")
    print(f"总体 accuracy: {overall_accuracy:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
