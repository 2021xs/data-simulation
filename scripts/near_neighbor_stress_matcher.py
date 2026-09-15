#!/usr/bin/env python
"""Run controlled Starlink Ku-band near-neighbor stress matcher."""

from __future__ import annotations

import argparse
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
    parser.add_argument("--stress-dataset", required=True, type=Path)
    parser.add_argument("--candidate-libraries", nargs="+", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--confusion", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--known-neighbor-norad-id", default="66274")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def required_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [field for field in columns if field not in df.columns]
    if missing:
        fail(f"{name} 缺少字段: " + ", ".join(missing))


def load_inputs(dataset_path: Path, library_paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not dataset_path.exists():
        fail(f"stress dataset 不存在: {dataset_path}")
    dataset = pd.read_csv(dataset_path)
    required_columns(
        dataset,
        [
            "experiment_name",
            "sequence_id",
            "target_name",
            "target_norad_id",
            "known_nearest_neighbor_name",
            "known_nearest_neighbor_norad_id",
            "error_model_variant",
            "sigma_multiplier",
            "partial_pass_window",
            "scenario",
            "t_rel_s",
            "f_sim_hz",
            "label",
            "n_time_points",
            "window_duration_s",
        ],
        "stress dataset",
    )
    libraries = []
    for path in library_paths:
        if not path.exists():
            fail(f"candidate library 不存在: {path}")
        lib = pd.read_csv(path)
        required_columns(
            lib,
            ["candidate_name", "candidate_norad_id", "candidate_rank", "candidate_limit", "t_rel_s", "f_geo_candidate_hz"],
            f"candidate library {path}",
        )
        libraries.append(lib)
    library = pd.concat(libraries, ignore_index=True)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    dataset["target_norad_id"] = dataset["target_norad_id"].astype(str)
    dataset["known_nearest_neighbor_norad_id"] = dataset["known_nearest_neighbor_norad_id"].astype(str)
    dataset["label"] = dataset["label"].astype(str)
    return dataset, library


def batch_scores(t_rel_s: np.ndarray, fsim_matrix: np.ndarray, candidate_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return RMSE, fitted b, fitted k arrays with shape [n_sequences, n_candidates]."""
    x = t_rel_s - float(np.mean(t_rel_s))
    n = float(len(t_rel_s))
    denom = float(np.sum(x * x))
    sum_fsim = fsim_matrix.sum(axis=1)
    sum_fsim_x = fsim_matrix @ x
    sum_fsim2 = np.sum(fsim_matrix * fsim_matrix, axis=1)
    sum_fgeo = candidate_matrix.sum(axis=1)
    sum_fgeo_x = candidate_matrix @ x
    sum_fgeo2 = np.sum(candidate_matrix * candidate_matrix, axis=1)
    cross = fsim_matrix @ candidate_matrix.T
    sum_delta = sum_fsim[:, None] - sum_fgeo[None, :]
    sum_delta_x = sum_fsim_x[:, None] - sum_fgeo_x[None, :]
    sum_delta2 = sum_fsim2[:, None] - 2.0 * cross + sum_fgeo2[None, :]
    fitted_b = sum_delta / n
    fitted_k = np.zeros_like(fitted_b) if denom == 0 else sum_delta_x / denom
    sse = sum_delta2 - (sum_delta * sum_delta) / n
    if denom != 0:
        sse = sse - (sum_delta_x * sum_delta_x) / denom
    rmse = np.sqrt(np.maximum(sse / n, 0.0))
    return rmse, fitted_b, fitted_k


def prepare_library(library: pd.DataFrame) -> dict[int, pd.DataFrame]:
    out: dict[int, pd.DataFrame] = {}
    for limit, group in library.groupby("candidate_limit"):
        group = group.sort_values(["candidate_rank", "t_rel_s"]).copy()
        out[int(limit)] = group
    return out


def candidate_matrix_for_window(limit_lib: pd.DataFrame, t_rel_s: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    wanted = pd.DataFrame({"t_rel_s": t_rel_s})
    merged = limit_lib.merge(wanted, on="t_rel_s", how="inner")
    candidate_meta = merged.drop_duplicates("candidate_norad_id").sort_values("candidate_rank")
    if candidate_meta.empty:
        fail("candidate library 与窗口时间点没有交集")
    n_candidates = len(candidate_meta)
    counts = merged.groupby("candidate_norad_id")["t_rel_s"].nunique()
    if counts.min() != len(t_rel_s) or counts.max() != len(t_rel_s):
        fail("candidate library 未覆盖 partial window 的完整时间点")
    pivot = merged.pivot(index="candidate_norad_id", columns="t_rel_s", values="f_geo_candidate_hz").loc[candidate_meta["candidate_norad_id"]]
    pivot = pivot[t_rel_s]
    if pivot.shape != (n_candidates, len(t_rel_s)):
        fail("candidate matrix 形状异常")
    return candidate_meta.reset_index(drop=True), pivot.to_numpy(float)


def match(dataset: pd.DataFrame, library: pd.DataFrame, known_neighbor_norad: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    libraries = prepare_library(library)
    cache: dict[tuple[int, str], tuple[pd.DataFrame, np.ndarray]] = {}
    setting_cols = ["error_model_variant", "sigma_multiplier", "partial_pass_window", "scenario"]
    setting_groups = list(dataset.groupby(setting_cols, sort=True))
    for group_idx, (setting, setting_df) in enumerate(setting_groups, 1):
        print(f"已匹配 setting {group_idx}/{len(setting_groups)}: {setting}")
        setting_df = setting_df.sort_values(["sequence_id", "t_rel_s"])
        first_setting = setting_df.iloc[0]
        window = str(first_setting["partial_pass_window"])
        sequence_ids = list(setting_df["sequence_id"].drop_duplicates())
        t_rel = setting_df[setting_df["sequence_id"] == sequence_ids[0]].sort_values("t_rel_s")["t_rel_s"].to_numpy(float)
        fsim_wide = setting_df.pivot(index="sequence_id", columns="t_rel_s", values="f_sim_hz").loc[sequence_ids, t_rel]
        fsim_matrix = fsim_wide.to_numpy(float)
        first_by_sequence = setting_df.drop_duplicates("sequence_id").set_index("sequence_id").loc[sequence_ids]
        true_norad = str(first_setting["label"])
        for candidate_limit, limit_lib in libraries.items():
            cache_key = (candidate_limit, window)
            if cache_key not in cache:
                cache[cache_key] = candidate_matrix_for_window(limit_lib, t_rel)
            meta, matrix = cache[cache_key]
            rmse, fitted_b, fitted_k = batch_scores(t_rel, fsim_matrix, matrix)
            true_matches = np.flatnonzero(meta["candidate_norad_id"].astype(str).to_numpy() == true_norad)
            known_matches = np.flatnonzero(meta["candidate_norad_id"].astype(str).to_numpy() == str(known_neighbor_norad))
            if len(true_matches) == 0:
                fail(f"candidate_limit={candidate_limit} 未包含 true target {true_norad}")
            if len(known_matches) == 0:
                fail(f"candidate_limit={candidate_limit} 未包含 known neighbor {known_neighbor_norad}")
            true_idx = int(true_matches[0])
            known_idx = int(known_matches[0])
            wrong_rmse = rmse.copy()
            wrong_rmse[:, true_idx] = np.inf
            pred_idx = np.argmin(rmse, axis=1)
            best_wrong_idx = np.argmin(wrong_rmse, axis=1)
            for row_i, sequence_id in enumerate(sequence_ids):
                first = first_by_sequence.loc[sequence_id]
                pred_i = int(pred_idx[row_i])
                wrong_i = int(best_wrong_idx[row_i])
                pred_norad = str(meta.iloc[pred_i]["candidate_norad_id"])
                rows.append(
                    {
                        "experiment_name": first["experiment_name"],
                        "sequence_id": sequence_id,
                        "target_name": first["target_name"],
                        "target_norad_id": true_norad,
                        "predicted_name": meta.iloc[pred_i]["candidate_name"],
                        "predicted_norad_id": pred_norad,
                        "best_wrong_name": meta.iloc[wrong_i]["candidate_name"],
                        "best_wrong_norad_id": str(meta.iloc[wrong_i]["candidate_norad_id"]),
                        "known_nearest_neighbor_name": first["known_nearest_neighbor_name"],
                        "known_nearest_neighbor_norad_id": str(known_neighbor_norad),
                        "known_neighbor_score_rmse_hz": float(rmse[row_i, known_idx]),
                        "true_score_rmse_hz": float(rmse[row_i, true_idx]),
                        "best_score_rmse_hz": float(rmse[row_i, pred_i]),
                        "best_wrong_score_rmse_hz": float(rmse[row_i, wrong_i]),
                        "margin_hz": float(rmse[row_i, wrong_i] - rmse[row_i, true_idx]),
                        "known_neighbor_margin_hz": float(rmse[row_i, known_idx] - rmse[row_i, true_idx]),
                        "is_correct": pred_norad == true_norad,
                        "is_predicted_known_neighbor": pred_norad == str(known_neighbor_norad),
                        "error_model_variant": first["error_model_variant"],
                        "sigma_multiplier": float(first["sigma_multiplier"]),
                        "partial_pass_window": window,
                        "scenario": first["scenario"],
                        "candidate_limit": candidate_limit,
                        "n_time_points": int(first["n_time_points"]),
                        "window_duration_s": float(first["window_duration_s"]),
                        "fitted_b_hz_for_pred": float(fitted_b[row_i, pred_i]),
                        "fitted_k_hz_per_s_for_pred": float(fitted_k[row_i, pred_i]),
                        "fitted_b_hz_for_true": float(fitted_b[row_i, true_idx]),
                        "fitted_k_hz_per_s_for_true": float(fitted_k[row_i, true_idx]),
                    }
                )
    return pd.DataFrame(rows)


def build_summary(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby(["error_model_variant", "sigma_multiplier", "partial_pass_window", "scenario", "candidate_limit"])
        .agg(
            sequence_count=("sequence_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_margin_hz=("margin_hz", "mean"),
            median_margin_hz=("margin_hz", "median"),
            min_margin_hz=("margin_hz", "min"),
            p05_margin_hz=("margin_hz", lambda values: float(np.quantile(values, 0.05))),
            mean_known_neighbor_margin_hz=("known_neighbor_margin_hz", "mean"),
            min_known_neighbor_margin_hz=("known_neighbor_margin_hz", "min"),
            mean_true_score_rmse_hz=("true_score_rmse_hz", "mean"),
            mean_best_wrong_score_rmse_hz=("best_wrong_score_rmse_hz", "mean"),
            wrong_count=("is_correct", lambda values: int((~values).sum())),
            predicted_known_neighbor_count=("is_predicted_known_neighbor", "sum"),
        )
        .reset_index()
    )


def write_plots(results: pd.DataFrame, summary: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    base = summary[summary["candidate_limit"] == summary["candidate_limit"].min()]
    fig, ax = plt.subplots(figsize=(10, 5))
    for (variant, scenario), group in base.groupby(["error_model_variant", "scenario"]):
        g = group.groupby("sigma_multiplier")["mean_margin_hz"].mean().reset_index()
        ax.plot(g["sigma_multiplier"], g["mean_margin_hz"], marker="o", label=f"{variant}/{scenario}")
    ax.set_xlabel("sigma_multiplier")
    ax.set_ylabel("mean margin (Hz)")
    ax.set_title("controlled_starlink_near_neighbor_stress_margin_vs_sigma")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_near_neighbor_stress_margin_vs_sigma.png", dpi=160)
    plt.close(fig)

    heat = summary.pivot_table(index="partial_pass_window", columns="sigma_multiplier", values="min_margin_hz", aggfunc="min")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    im = ax.imshow(heat.to_numpy(float), cmap="viridis")
    ax.set_xticks(range(len(heat.columns)))
    ax.set_xticklabels(heat.columns)
    ax.set_yticks(range(len(heat.index)))
    ax.set_yticklabels(heat.index)
    ax.set_title("controlled_starlink_near_neighbor_stress_min_margin_heatmap")
    fig.colorbar(im, ax=ax, label="min margin (Hz)")
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_near_neighbor_stress_min_margin_heatmap.png", dpi=160)
    plt.close(fig)

    heat_acc = summary.pivot_table(index="partial_pass_window", columns="sigma_multiplier", values="accuracy", aggfunc="min")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    im = ax.imshow(heat_acc.to_numpy(float), cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(heat_acc.columns)))
    ax.set_xticklabels(heat_acc.columns)
    ax.set_yticks(range(len(heat_acc.index)))
    ax.set_yticklabels(heat_acc.index)
    ax.set_title("controlled_starlink_near_neighbor_stress_accuracy_heatmap")
    fig.colorbar(im, ax=ax, label="accuracy")
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_near_neighbor_stress_accuracy_heatmap.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5))
    order = list(summary["partial_pass_window"].drop_duplicates())
    for variant, group in summary.groupby("error_model_variant"):
        g = group.groupby("partial_pass_window")["min_margin_hz"].min().reindex(order)
        ax.plot(order, g, marker="o", label=variant)
    ax.set_ylabel("min margin (Hz)")
    ax.set_title("controlled_starlink_near_neighbor_stress_partial_window_margin")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_near_neighbor_stress_partial_window_margin.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    for variant, group in summary.groupby("error_model_variant"):
        g = group.groupby("candidate_limit")["min_margin_hz"].min().reset_index()
        ax.plot(g["candidate_limit"], g["min_margin_hz"], marker="o", label=variant)
    ax.set_xlabel("candidate_limit")
    ax.set_ylabel("min margin (Hz)")
    ax.set_title("controlled_starlink_near_neighbor_stress_candidate_limit_margin")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_near_neighbor_stress_candidate_limit_margin.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    for variant, group in results.groupby("error_model_variant"):
        ax.scatter(group["true_score_rmse_hz"], group["known_neighbor_score_rmse_hz"], s=12, alpha=0.35, label=variant)
    ax.set_xlabel("true score RMSE (Hz)")
    ax.set_ylabel("known neighbor score RMSE (Hz)")
    ax.set_title("controlled_starlink_near_neighbor_stress_true_vs_known_neighbor_rmse")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_near_neighbor_stress_true_vs_known_neighbor_rmse.png", dpi=160)
    plt.close(fig)


def table(df: pd.DataFrame, columns: list[str]) -> str:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in df[columns].iterrows():
        vals = []
        for val in row:
            vals.append(f"{val:.6f}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_report(path: Path, results: pd.DataFrame, summary: pd.DataFrame, dataset: pd.DataFrame, libraries: pd.DataFrame) -> None:
    hard = results.sort_values("margin_hz").iloc[0]
    wrongs_by_limit = results.groupby("candidate_limit")["best_wrong_norad_id"].agg(lambda s: ", ".join(sorted(set(map(str, s)))))
    by_sigma = summary.groupby(["error_model_variant", "sigma_multiplier"]).agg(mean_margin_hz=("mean_margin_hz", "mean"), min_margin_hz=("min_margin_hz", "min")).reset_index()
    by_window = summary.groupby("partial_pass_window").agg(min_margin_hz=("min_margin_hz", "min"), accuracy=("accuracy", "min")).reset_index().sort_values("min_margin_hz")
    by_limit = summary.groupby("candidate_limit").agg(min_margin_hz=("min_margin_hz", "min"), accuracy=("accuracy", "min")).reset_index()
    text = f"""# Controlled Starlink Ku-band Near-neighbor Stress Report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 实验目的

本轮是 near-neighbor stress test，用于观察当前最难 pair 在噪声放大、观测窗口变短、候选库变大时的 matcher 稳定性。它不是攻击实验，不是攻击成功率，不是真实 SatNOGS Starlink observation replay，也不是 Starlink CFO truth 验证。

## 2. 输入配置

- target：STARLINK-1008 / 44714
- known nearest neighbor：STARLINK-35760 / 66274
- center frequency：{float(dataset.center_freq_hz.iloc[0]):.0f} Hz
- station：{dataset.station_name.iloc[0]} / lat={dataset.station_lat_deg.iloc[0]} / lon={dataset.station_lon_deg.iloc[0]} / alt_m={dataset.station_alt_m.iloc[0]}
- error_model_variants：{', '.join(map(str, sorted(dataset.error_model_variant.unique())))}
- sigma_multipliers：{', '.join(map(str, sorted(dataset.sigma_multiplier.unique())))}
- partial_pass_windows：{', '.join(map(str, dataset.partial_pass_window.drop_duplicates()))}
- candidate_limits：{', '.join(map(str, sorted(results.candidate_limit.unique())))}
- scenarios：{', '.join(map(str, sorted(dataset.scenario.unique())))}
- num_sims_per_setting：{int(dataset.groupby(['error_model_variant','sigma_multiplier','partial_pass_window','scenario']).sequence_id.nunique().iloc[0])}
- mode：controlled_starlink
- observation_id：null

## 3. 数据集规模

- total_sequences：{dataset.sequence_id.nunique()}
- total_rows：{len(dataset)}
- matcher result rows：{len(results)}
- candidate library rows：{len(libraries)}
- skipped windows：无

## 4. 总体结果

- overall accuracy：{results.is_correct.mean():.6f}
- overall min margin：{results.margin_hz.min():.6f} Hz
- 是否出现误匹配：{'是' if (~results.is_correct).any() else '否'}
- 是否预测成 known nearest neighbor 66274：{'是' if results.is_predicted_known_neighbor.any() else '否'}

## 5. sigma_multiplier 影响

{table(by_sigma, ['error_model_variant', 'sigma_multiplier', 'mean_margin_hz', 'min_margin_hz'])}

## 6. partial pass 影响

{table(by_window, ['partial_pass_window', 'min_margin_hz', 'accuracy'])}

## 7. candidate_limit 影响

{table(by_limit, ['candidate_limit', 'min_margin_hz', 'accuracy'])}

candidate_limit 对应 best wrong 候选集合：
{chr(10).join(f'- {limit}: {values}' for limit, values in wrongs_by_limit.items())}

## 8. 最危险 setting

- error_model_variant：{hard.error_model_variant}
- sigma_multiplier：{hard.sigma_multiplier}
- partial_pass_window：{hard.partial_pass_window}
- scenario：{hard.scenario}
- candidate_limit：{hard.candidate_limit}
- min_margin_hz：{hard.margin_hz:.6f}
- best_wrong candidate：{hard.best_wrong_name} / {hard.best_wrong_norad_id}
- known_neighbor_score_rmse_hz：{hard.known_neighbor_score_rmse_hz:.6f}
- true_score_rmse_hz：{hard.true_score_rmse_hz:.6f}
- n_time_points：{hard.n_time_points}
- window_duration_s：{hard.window_duration_s:.1f}

## 9. 结论边界

当前仍是 controlled stress baseline。accuracy 为 1 只能说明当前 stress 条件下 matcher 仍稳定；如果未来出现误匹配，也只能说明在该 controlled stress 条件下存在 near-neighbor confusion 风险。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；`frequency_scaled` 只是 frequency sensitivity setting，不是真实 Starlink Ku-band CFO 分布。

## 10. 下一步建议

若 margin 仍远大于 0，继续加大 sigma_multiplier 或缩短窗口；若 partial window 显著降低 margin，进入 partial-pass attack / time alignment stress；若 66274 接近 true target，进入 near-neighbor replay attack；若 candidate_limit 1000 出现新 hard wrong，后续攻击场景应优先使用新的 hard wrong。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        check_outputs(
            [
                args.output,
                args.summary,
                args.confusion,
                args.report,
                args.plots_dir / "controlled_starlink_near_neighbor_stress_margin_vs_sigma.png",
            ],
            args.overwrite,
        )
        dataset, library = load_inputs(args.stress_dataset, args.candidate_libraries)
        results = match(dataset, library, str(args.known_neighbor_norad_id))
        summary = build_summary(results)
        confusion = pd.crosstab(results["target_norad_id"], results["predicted_norad_id"])
        confusion.index.name = "true_label"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output, index=False)
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(args.summary, index=False)
        args.confusion.parent.mkdir(parents=True, exist_ok=True)
        confusion.to_csv(args.confusion)
        write_plots(results, summary, args.plots_dir)
        write_report(args.report, results, summary, dataset, library)
    except InputError as exc:
        print(f"错误: {exc}")
        return 2
    print(f"near-neighbor stress matcher 完成: {args.output}")
    print(f"overall accuracy: {results.is_correct.mean():.6f}")
    print(f"min margin: {results.margin_hz.min():.6f} Hz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
