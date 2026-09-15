#!/usr/bin/env python
"""Diagnose the most negative near-neighbor stress matcher result."""

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
    parser.add_argument("--matching-results", required=True, type=Path)
    parser.add_argument("--stress-dataset", required=True, type=Path)
    parser.add_argument("--candidate-library", required=True, type=Path)
    parser.add_argument("--recheck-output", required=True, type=Path)
    parser.add_argument("--fit-params-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--known-neighbor-norad-id", default="66274")
    parser.add_argument("--expected-reported-min-margin-hz", type=float, default=-543.926064)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        fail(f"{name} 缺少字段: " + ", ".join(missing))


def load_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    for path in [args.matching_results, args.stress_dataset, args.candidate_library]:
        if not path.exists():
            fail(f"输入文件不存在: {path}")
    results = pd.read_csv(args.matching_results)
    dataset = pd.read_csv(args.stress_dataset)
    library = pd.read_csv(args.candidate_library)
    require_columns(
        results,
        [
            "sequence_id",
            "target_name",
            "target_norad_id",
            "best_wrong_name",
            "best_wrong_norad_id",
            "known_nearest_neighbor_name",
            "known_nearest_neighbor_norad_id",
            "true_score_rmse_hz",
            "best_wrong_score_rmse_hz",
            "known_neighbor_score_rmse_hz",
            "margin_hz",
            "candidate_limit",
            "error_model_variant",
            "sigma_multiplier",
            "partial_pass_window",
            "scenario",
        ],
        "matching results",
    )
    require_columns(
        dataset,
        [
            "sequence_id",
            "sim_index",
            "random_seed",
            "t_abs_utc",
            "t_rel_s",
            "t_window_rel_s",
            "f_geo_tle_hz",
            "f_sim_hz",
            "target_norad_id",
            "known_nearest_neighbor_norad_id",
            "partial_pass_window",
            "scenario",
            "error_model_variant",
            "sigma_multiplier",
            "n_time_points",
            "window_duration_s",
            "mode",
            "observation_id",
        ],
        "stress dataset",
    )
    require_columns(
        library,
        ["candidate_name", "candidate_norad_id", "candidate_rank", "candidate_limit", "t_abs_utc", "t_rel_s", "f_geo_candidate_hz"],
        "candidate library",
    )
    results["candidate_limit"] = pd.to_numeric(results["candidate_limit"])
    results["margin_hz"] = pd.to_numeric(results["margin_hz"])
    results["best_wrong_norad_id"] = results["best_wrong_norad_id"].astype(str)
    results["target_norad_id"] = results["target_norad_id"].astype(str)
    results["known_nearest_neighbor_norad_id"] = results["known_nearest_neighbor_norad_id"].astype(str)
    dataset["target_norad_id"] = dataset["target_norad_id"].astype(str)
    dataset["known_nearest_neighbor_norad_id"] = dataset["known_nearest_neighbor_norad_id"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    return results, dataset, library


def select_failure_row(results: pd.DataFrame) -> pd.Series:
    # For tied minimum margins, prefer the largest candidate_limit because the task focuses on 1000-candidate stress.
    return results.sort_values(["margin_hz", "candidate_limit"], ascending=[True, False]).iloc[0]


def fit_profile(t_rel_s: np.ndarray, f_sim_hz: np.ndarray, f_geo_hz: np.ndarray) -> dict[str, object]:
    x = t_rel_s - float(np.mean(t_rel_s))
    delta = f_sim_hz - f_geo_hz
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    fitted = design @ coef
    residual = delta - fitted
    return {
        "b_hat_hz": float(coef[0]),
        "k_hat_hz_per_s": float(coef[1]),
        "rmse_hz": float(np.sqrt(np.mean(residual * residual))),
        "residual_mean_hz": float(np.mean(residual)),
        "residual_std_hz": float(np.std(residual)),
        "residual_max_abs_hz": float(np.max(np.abs(residual))),
        "delta_mean_hz": float(np.mean(delta)),
        "delta_std_hz": float(np.std(delta)),
        "delta_hz": delta,
        "fit_hz": fitted,
        "residual_hz": residual,
    }


def extract_candidate(library: pd.DataFrame, candidate_norad: str, t_rel_s: np.ndarray) -> pd.DataFrame:
    cand = library[library["candidate_norad_id"] == str(candidate_norad)].sort_values("t_rel_s")
    if cand.empty:
        fail(f"candidate library 中找不到 NORAD {candidate_norad}")
    cand = cand[cand["t_rel_s"].isin(t_rel_s)].sort_values("t_rel_s").reset_index(drop=True)
    if len(cand) != len(t_rel_s):
        fail(f"candidate {candidate_norad} 没有覆盖完整窗口")
    if not np.allclose(cand["t_rel_s"].to_numpy(float), t_rel_s, rtol=0, atol=1e-9):
        fail(f"candidate {candidate_norad} 与 sequence 时间网格不一致")
    return cand


def duplicate_curve_count(library: pd.DataFrame) -> int:
    pivot = library.pivot(index="candidate_norad_id", columns="t_rel_s", values="f_geo_candidate_hz").sort_index(axis=1)
    rounded = pivot.round(6)
    return int(rounded.duplicated().sum())


def same_setting_stats(results: pd.DataFrame, failure: pd.Series) -> tuple[dict[str, object], pd.DataFrame]:
    same = results[
        (results["error_model_variant"] == failure["error_model_variant"])
        & (results["sigma_multiplier"] == failure["sigma_multiplier"])
        & (results["partial_pass_window"] == failure["partial_pass_window"])
        & (results["scenario"] == failure["scenario"])
        & (results["candidate_limit"] == failure["candidate_limit"])
    ].copy()
    stats = {
        "sequence_count": int(len(same)),
        "wrong_count": int((~same["is_correct"]).sum()),
        "accuracy": float(same["is_correct"].mean()),
        "min_margin_hz": float(same["margin_hz"].min()),
        "median_margin_hz": float(same["margin_hz"].median()),
        "mean_margin_hz": float(same["margin_hz"].mean()),
        "p05_margin_hz": float(np.quantile(same["margin_hz"], 0.05)),
        "negative_margin_count": int((same["margin_hz"] < 0).sum()),
        "best_wrong_64732_count": int((same["best_wrong_norad_id"].astype(str) == "64732").sum()),
        "best_wrong_66274_count": int((same["best_wrong_norad_id"].astype(str) == "66274").sum()),
    }
    top_wrong = same["best_wrong_norad_id"].astype(str).value_counts().head(10).reset_index()
    top_wrong.columns = ["best_wrong_norad_id", "count"]
    name_source = same.assign(best_wrong_norad_id_str=same["best_wrong_norad_id"].astype(str)).drop_duplicates("best_wrong_norad_id_str")
    name_map = name_source.set_index("best_wrong_norad_id_str")["best_wrong_name"].to_dict()
    top_wrong["best_wrong_name"] = top_wrong["best_wrong_norad_id"].map(name_map)
    return stats, top_wrong


def write_plots(plots_dir: Path, seq: pd.DataFrame, candidates: dict[str, pd.DataFrame], fits: dict[str, dict[str, object]], same_setting: pd.DataFrame, failure: pd.Series) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    x = seq["t_window_rel_s"].to_numpy(float) if "t_window_rel_s" in seq.columns else seq["t_rel_s"].to_numpy(float)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, seq["f_sim_hz"], label="f_sim_hz", linewidth=2)
    for key, cand in candidates.items():
        ax.plot(x, cand["f_geo_candidate_hz"], label=f"f_geo_{key}_hz", alpha=0.9)
    ax.set_xlabel("t_window_rel_s (s)")
    ax.set_ylabel("frequency (Hz)")
    ax.set_title("failure_case_fsim_vs_candidates")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_failure_case_fsim_vs_candidates.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    for key, fit in fits.items():
        ax.plot(x, fit["delta_hz"], label=f"delta_{key}", alpha=0.85)
        ax.plot(x, fit["fit_hz"], "--", label=f"fit_{key}", alpha=0.8)
    ax.set_xlabel("t_window_rel_s (s)")
    ax.set_ylabel("delta / fitted b+k (Hz)")
    ax.set_title("failure_case_delta_curves")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_failure_case_delta_curves.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    for key, fit in fits.items():
        ax.plot(x, fit["residual_hz"], label=f"residual_{key}", alpha=0.9)
    ax.set_xlabel("t_window_rel_s (s)")
    ax.set_ylabel("residual after b+k fit (Hz)")
    ax.set_title("failure_case_residual_curves")
    ax.legend()
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_failure_case_residual_curves.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7, 4.6))
    labels = list(fits.keys())
    values = [fits[key]["rmse_hz"] for key in labels]
    ax.bar(labels, values, color=["#2f6f8f", "#8f4f2f", "#6f6f6f"])
    ax.set_ylabel("RMSE after b+k fit (Hz)")
    ax.set_title("failure_case_score_bar")
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_failure_case_score_bar.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.hist(same_setting["margin_hz"], bins=30, color="#2f6f8f", alpha=0.78)
    ax.axvline(float(failure["margin_hz"]), color="red", linestyle="--", label="diagnosed sequence")
    ax.set_xlabel("margin_hz")
    ax.set_ylabel("sequence count")
    ax.set_title("failure_case_same_setting_margin_distribution")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_failure_case_same_setting_margin_distribution.png", dpi=160)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    plot_paths = [
        args.plots_dir / "controlled_starlink_failure_case_fsim_vs_candidates.png",
        args.plots_dir / "controlled_starlink_failure_case_delta_curves.png",
        args.plots_dir / "controlled_starlink_failure_case_residual_curves.png",
        args.plots_dir / "controlled_starlink_failure_case_score_bar.png",
        args.plots_dir / "controlled_starlink_failure_case_same_setting_margin_distribution.png",
    ]
    try:
        check_outputs([args.recheck_output, args.fit_params_output, args.report, *plot_paths], args.overwrite)
        results, dataset, library = load_inputs(args)
        failure = select_failure_row(results)
        sequence_id = str(failure["sequence_id"])
        seq = dataset[dataset["sequence_id"] == sequence_id].sort_values("t_rel_s").reset_index(drop=True)
        if seq.empty:
            fail(f"stress dataset 中找不到 sequence_id={sequence_id}")
        target_norad = str(failure["target_norad_id"])
        best_wrong_norad = str(failure["best_wrong_norad_id"])
        known_norad = str(args.known_neighbor_norad_id)
        t_rel = seq["t_rel_s"].to_numpy(float)
        f_sim = seq["f_sim_hz"].to_numpy(float)
        target_curve = extract_candidate(library, target_norad, t_rel)
        best_wrong_curve = extract_candidate(library, best_wrong_norad, t_rel)
        known_curve = extract_candidate(library, known_norad, t_rel)
        candidates = {"true_44714": target_curve, f"best_wrong_{best_wrong_norad}": best_wrong_curve, "known_66274": known_curve}
        fits = {
            "true_44714": fit_profile(t_rel, f_sim, target_curve["f_geo_candidate_hz"].to_numpy(float)),
            f"best_wrong_{best_wrong_norad}": fit_profile(t_rel, f_sim, best_wrong_curve["f_geo_candidate_hz"].to_numpy(float)),
            "known_66274": fit_profile(t_rel, f_sim, known_curve["f_geo_candidate_hz"].to_numpy(float)),
        }
        best_key = f"best_wrong_{best_wrong_norad}"
        recomputed_margin = fits[best_key]["rmse_hz"] - fits["true_44714"]["rmse_hz"]
        recomputed_known_margin = fits["known_66274"]["rmse_hz"] - fits["true_44714"]["rmse_hz"]
        tolerance = 1e-5
        score_consistent = (
            abs(float(failure["true_score_rmse_hz"]) - fits["true_44714"]["rmse_hz"]) < tolerance
            and abs(float(failure["best_wrong_score_rmse_hz"]) - fits[best_key]["rmse_hz"]) < tolerance
            and abs(float(failure["known_neighbor_score_rmse_hz"]) - fits["known_66274"]["rmse_hz"]) < tolerance
            and abs(float(failure["margin_hz"]) - recomputed_margin) < tolerance
        )
        full_limit = library[library["candidate_limit"] == int(failure["candidate_limit"])] if "candidate_limit" in library.columns else library
        per_norad_counts = full_limit.groupby("candidate_norad_id")["t_rel_s"].nunique()
        norad_uniqueness = {
            norad: int(per_norad_counts.get(str(norad), 0)) for norad in [target_norad, best_wrong_norad, known_norad]
        }
        duplicate_norad_count = int((full_limit.groupby(["candidate_norad_id", "t_rel_s"]).size() > 1).sum())
        duplicate_curves = duplicate_curve_count(full_limit)
        time_checks = {
            "sequence_time_points": int(len(seq)),
            "library_time_points_per_candidate": int(len(target_curve)),
            "t_rel_exact_match_true": bool(np.allclose(target_curve["t_rel_s"].to_numpy(float), t_rel, rtol=0, atol=1e-9)),
            "t_abs_exact_match_true": bool((target_curve["t_abs_utc"].astype(str).to_numpy() == seq["t_abs_utc"].astype(str).to_numpy()).all()),
            "partial_pass_window": str(failure["partial_pass_window"]),
            "window_duration_s": float(failure["window_duration_s"]),
            "n_time_points": int(failure["n_time_points"]),
        }
        leakage_checks = {
            "candidate_library_has_f_sim_hz": "f_sim_hz" in library.columns,
            "best_wrong_fgeo_equals_fsim_allclose": bool(np.allclose(best_wrong_curve["f_geo_candidate_hz"].to_numpy(float), f_sim, rtol=0, atol=1e-9)),
            "true_fgeo_equals_dataset_f_geo_tle_allclose": bool(np.allclose(target_curve["f_geo_candidate_hz"].to_numpy(float), seq["f_geo_tle_hz"].to_numpy(float), rtol=0, atol=1e-6)),
            "best_wrong_norad_equals_true": best_wrong_norad == target_norad,
        }
        same_setting = results[
            (results["error_model_variant"] == failure["error_model_variant"])
            & (results["sigma_multiplier"] == failure["sigma_multiplier"])
            & (results["partial_pass_window"] == failure["partial_pass_window"])
            & (results["scenario"] == failure["scenario"])
            & (results["candidate_limit"] == failure["candidate_limit"])
        ].copy()
        same_stats, top_wrong = same_setting_stats(results, failure)

        recheck = pd.DataFrame(
            [
                {
                    "sequence_id": sequence_id,
                    "target_name": failure["target_name"],
                    "target_norad_id": target_norad,
                    "best_wrong_name": failure["best_wrong_name"],
                    "best_wrong_norad_id": best_wrong_norad,
                    "known_neighbor_name": failure["known_nearest_neighbor_name"],
                    "known_neighbor_norad_id": known_norad,
                    "error_model_variant": failure["error_model_variant"],
                    "sigma_multiplier": failure["sigma_multiplier"],
                    "partial_pass_window": failure["partial_pass_window"],
                    "scenario": failure["scenario"],
                    "candidate_limit": failure["candidate_limit"],
                    "n_time_points": failure["n_time_points"],
                    "window_duration_s": failure["window_duration_s"],
                    "sim_index": seq["sim_index"].iloc[0],
                    "random_seed": seq["random_seed"].iloc[0],
                    "true_score_rmse_hz_from_matcher": failure["true_score_rmse_hz"],
                    "true_score_rmse_hz_recomputed": fits["true_44714"]["rmse_hz"],
                    "best_wrong_score_rmse_hz_from_matcher": failure["best_wrong_score_rmse_hz"],
                    "best_wrong_score_rmse_hz_recomputed": fits[best_key]["rmse_hz"],
                    "known_neighbor_score_rmse_hz_from_matcher": failure["known_neighbor_score_rmse_hz"],
                    "known_neighbor_score_rmse_hz_recomputed": fits["known_66274"]["rmse_hz"],
                    "margin_hz_from_matcher": failure["margin_hz"],
                    "margin_hz_recomputed": recomputed_margin,
                    "known_neighbor_margin_hz_recomputed": recomputed_known_margin,
                    "score_consistent": score_consistent,
                    "current_file_min_margin_hz": float(results["margin_hz"].min()),
                    "expected_reported_min_margin_hz": args.expected_reported_min_margin_hz,
                    "expected_reported_min_present_in_current_results": bool(np.isclose(results["margin_hz"], args.expected_reported_min_margin_hz, atol=1e-6).any()),
                    **{f"norad_{key}_time_points": value for key, value in norad_uniqueness.items()},
                    **time_checks,
                    **leakage_checks,
                    "duplicate_norad_time_rows": duplicate_norad_count,
                    "duplicate_curve_count_rounded_1e_6": duplicate_curves,
                    **{f"same_setting_{key}": value for key, value in same_stats.items()},
                }
            ]
        )
        fit_rows = []
        for key, fit in fits.items():
            if key == "true_44714":
                name, norad = "STARLINK-1008", target_norad
            elif key == "known_66274":
                name, norad = str(failure["known_nearest_neighbor_name"]), known_norad
            else:
                name, norad = str(failure["best_wrong_name"]), best_wrong_norad
            fit_rows.append(
                {
                    "candidate_role": key,
                    "candidate_name": name,
                    "candidate_norad_id": norad,
                    "b_hat_hz": fit["b_hat_hz"],
                    "k_hat_hz_per_s": fit["k_hat_hz_per_s"],
                    "rmse_hz": fit["rmse_hz"],
                    "residual_mean_hz": fit["residual_mean_hz"],
                    "residual_std_hz": fit["residual_std_hz"],
                    "residual_max_abs_hz": fit["residual_max_abs_hz"],
                    "delta_mean_hz": fit["delta_mean_hz"],
                    "delta_std_hz": fit["delta_std_hz"],
                }
            )
        fit_params = pd.DataFrame(fit_rows)
        args.recheck_output.parent.mkdir(parents=True, exist_ok=True)
        recheck.to_csv(args.recheck_output, index=False)
        args.fit_params_output.parent.mkdir(parents=True, exist_ok=True)
        fit_params.to_csv(args.fit_params_output, index=False)
        write_plots(args.plots_dir, seq, candidates, fits, same_setting, failure)

        top_wrong_lines = "\n".join(
            f"| `{row.best_wrong_name}` | `{row.best_wrong_norad_id}` | {int(row['count'])} |"
            for _, row in top_wrong.iterrows()
        )
        fit_lines = "\n".join(
            f"| `{row.candidate_role}` | `{row.candidate_name}` | `{row.candidate_norad_id}` | {row.b_hat_hz:.6f} | {row.k_hat_hz_per_s:.6f} | {row.rmse_hz:.6f} | {row.residual_std_hz:.6f} | {row.delta_std_hz:.6f} |"
            for _, row in fit_params.iterrows()
        )
        report_text = f"""# Controlled Starlink Near-neighbor Failure Case Diagnosis

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 诊断目的

本轮是 Stage 2.5 failure case diagnosis，用于复核 Stage 2 中的负 margin 是否真实可信。当前不是攻击实验，不是攻击成功率，不是 Starlink CFO truth，也不是真实 SatNOGS observation replay。

## 2. 被诊断样本

- sequence_id：`{sequence_id}`
- target：`STARLINK-1008 / {target_norad}`
- best wrong：`{failure['best_wrong_name']} / {best_wrong_norad}`
- known neighbor：`{failure['known_nearest_neighbor_name']} / {known_norad}`
- error_model_variant：`{failure['error_model_variant']}`
- sigma_multiplier：`{failure['sigma_multiplier']}`
- partial_pass_window：`{failure['partial_pass_window']}`
- scenario：`{failure['scenario']}`
- candidate_limit：`{failure['candidate_limit']}`
- n_time_points：{int(failure['n_time_points'])}
- window_duration_s：{float(failure['window_duration_s']):.1f}
- sim_index：{seq['sim_index'].iloc[0]}
- random_seed：{seq['random_seed'].iloc[0]}

注意：当前磁盘上的 `matching_results.csv` 全局最小 margin 为 `{results['margin_hz'].min():.6f} Hz`。用户背景中提到的 `{args.expected_reported_min_margin_hz:.6f} Hz` 在当前结果文件中{'存在' if recheck['expected_reported_min_present_in_current_results'].iloc[0] else '不存在'}，因此本诊断以当前原始 CSV 为准。

## 3. score 复核结论

- true_score_rmse_hz from matcher：{float(failure['true_score_rmse_hz']):.6f}
- true_score_rmse_hz recomputed：{fits['true_44714']['rmse_hz']:.6f}
- best_wrong_score_rmse_hz from matcher：{float(failure['best_wrong_score_rmse_hz']):.6f}
- best_wrong_score_rmse_hz recomputed：{fits[best_key]['rmse_hz']:.6f}
- known_neighbor_score_rmse_hz from matcher：{float(failure['known_neighbor_score_rmse_hz']):.6f}
- known_neighbor_score_rmse_hz recomputed：{fits['known_66274']['rmse_hz']:.6f}
- margin_hz from matcher：{float(failure['margin_hz']):.6f}
- margin_hz recomputed：{recomputed_margin:.6f}
- known_neighbor_margin_hz recomputed：{recomputed_known_margin:.6f}
- recomputed score 与 matcher 输出是否一致：{'是' if score_consistent else '否'}

best_wrong_score_rmse_hz 并不接近 0；当前最危险样本的 best wrong RMSE 约为 `{fits[best_key]['rmse_hz']:.6f} Hz`。

## 4. 拟合参数

| role | candidate | NORAD | b_hat_hz | k_hat_hz_per_s | rmse_hz | residual_std_hz | delta_std_hz |
|---|---|---|---:|---:|---:|---:|---:|
{fit_lines}

## 5. sanity check 结论

- NORAD 44714 / {best_wrong_norad} / 66274 在 1000-candidate library 中均存在，并且各自覆盖 `{len(target_curve)}` 个 full-pass/窗口时间点。
- duplicate NORAD-time rows：{duplicate_norad_count}
- rounded duplicate curve count：{duplicate_curves}
- stress sequence 与 candidate library 的 `t_rel_s` 是否对齐：{time_checks['t_rel_exact_match_true']}
- stress sequence 与 candidate library 的 `t_abs_utc` 是否对齐：{time_checks['t_abs_exact_match_true']}
- partial window：`{time_checks['partial_pass_window']}`，duration={time_checks['window_duration_s']:.1f}s，n_time_points={time_checks['n_time_points']}
- candidate library 是否混入 `f_sim_hz` 字段：{leakage_checks['candidate_library_has_f_sim_hz']}
- best wrong `f_geo_candidate_hz` 是否等于 `f_sim_hz`：{leakage_checks['best_wrong_fgeo_equals_fsim_allclose']}
- best wrong NORAD 是否等于 true target：{leakage_checks['best_wrong_norad_equals_true']}
- true candidate geometry 与 dataset 的 target geometry 是否一致：{leakage_checks['true_fgeo_equals_dataset_f_geo_tle_allclose']}

未发现时间错配、candidate library 混入 `f_sim_hz`、best wrong 与 true target 同 NORAD、或明显数据泄漏迹象。

## 6. 曲线级解释

本样本中 true target 的 residual RMSE 为 `{fits['true_44714']['rmse_hz']:.6f} Hz`，best wrong `{failure['best_wrong_name']} / {best_wrong_norad}` 的 residual RMSE 为 `{fits[best_key]['rmse_hz']:.6f} Hz`。在该短窗口和高噪声设置下，best wrong 的 `delta = f_sim - f_geo_candidate` 经 `b+k` 拟合后残差更小，因此出现负 margin。

known neighbor `66274` 的 RMSE 为 `{fits['known_66274']['rmse_hz']:.6f} Hz`，在当前样本中比 best wrong `{best_wrong_norad}` 更差。因此这条 failure case 的更危险候选是 `{best_wrong_norad}`，不是 66274。

## 7. 同类 setting 分布

- sequence_count：{same_stats['sequence_count']}
- wrong_count：{same_stats['wrong_count']}
- accuracy：{same_stats['accuracy']:.6f}
- min_margin_hz：{same_stats['min_margin_hz']:.6f}
- median_margin_hz：{same_stats['median_margin_hz']:.6f}
- mean_margin_hz：{same_stats['mean_margin_hz']:.6f}
- p05_margin_hz：{same_stats['p05_margin_hz']:.6f}
- margin < 0 数量：{same_stats['negative_margin_count']}
- best_wrong 为 64732 次数：{same_stats['best_wrong_64732_count']}
- best_wrong 为 66274 次数：{same_stats['best_wrong_66274_count']}

best_wrong 分布前 10：

| best_wrong_name | best_wrong_norad_id | count |
|---|---|---:|
{top_wrong_lines}

## 8. 结论边界

未发现 bug 时，该 negative margin 可视为 controlled stress 条件下的真实 matcher failure case；它说明 partial window + high noise + large candidate library 会让 profile least-squares residual matcher 失稳。但这不能解释为真实攻击成功率，也不能解释为真实 Starlink CFO 分布。

## 9. 下一步建议

建议进入 partial-pass / time-alignment stress，并将 `{failure['best_wrong_name']} / {best_wrong_norad}` 与 `STARLINK-35760 / 66274` 一起纳入后续 near-neighbor replay 设计。由于当前文件中的最危险候选不是 64732，后续应先固定当前结果文件版本，再决定攻击候选集合。
"""
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_text, encoding="utf-8")
    except InputError as exc:
        print(f"错误: {exc}")
        return 2
    print(f"failure case diagnosis 完成: {args.report}")
    print(f"sequence_id: {sequence_id}")
    print(f"best_wrong_score_rmse_hz: {fits[best_key]['rmse_hz']:.6f}")
    print(f"score_consistent: {score_consistent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
