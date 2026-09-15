#!/usr/bin/env python
"""Run partial-pass / time-alignment stress matcher."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


HARD = {"44714": "true", "63502": "hard_wrong_63502", "64732": "hard_wrong_64732", "66274": "hard_wrong_66274"}


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    raise InputError(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def batch_scores(t_rel: np.ndarray, fsim: np.ndarray, fgeo: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x = t_rel - float(np.mean(t_rel))
    n = float(len(t_rel))
    denom = float(np.sum(x * x))
    delta = fsim[None, :] - fgeo
    b = delta.mean(axis=1)
    k = np.zeros(len(fgeo)) if denom == 0 else (delta @ x) / denom
    residual = delta - b[:, None] - k[:, None] * x[None, :]
    rmse = np.sqrt(np.mean(residual * residual, axis=1))
    return rmse, b, k, residual.std(axis=1), np.max(np.abs(residual), axis=1)


def candidate_matrix(library: pd.DataFrame, t_rel: np.ndarray) -> tuple[pd.DataFrame, np.ndarray]:
    merged = library.merge(pd.DataFrame({"t_rel_s": t_rel}), on="t_rel_s", how="inner")
    meta = merged.drop_duplicates("candidate_norad_id").sort_values("candidate_rank").reset_index(drop=True)
    counts = merged.groupby("candidate_norad_id")["t_rel_s"].nunique()
    if counts.min() != len(t_rel) or counts.max() != len(t_rel):
        fail("candidate library 未覆盖窗口完整时间点")
    pivot = merged.pivot(index="candidate_norad_id", columns="t_rel_s", values="f_geo_candidate_hz").loc[meta["candidate_norad_id"]]
    pivot = pivot[t_rel]
    return meta, pivot.to_numpy(float)


def match(dataset: pd.DataFrame, library: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    hard_rows = []
    cache: dict[tuple[str, float], tuple[pd.DataFrame, np.ndarray]] = {}
    groups = list(dataset.groupby("sequence_id", sort=True))
    for idx, (sequence_id, seq) in enumerate(groups, 1):
        if idx % 500 == 0:
            print(f"已匹配 {idx}/{len(groups)} 条 partial-pass sequence")
        seq = seq.sort_values("t_rel_s")
        first = seq.iloc[0]
        t_rel = seq["t_rel_s"].to_numpy(float)
        key = (str(first["window_duration_s"]), float(first["window_center_offset_s"]))
        if key not in cache:
            cache[key] = candidate_matrix(library, t_rel)
        meta, mat = cache[key]
        rmse, b, k, rstd, rmax = batch_scores(t_rel, seq["f_sim_hz"].to_numpy(float), mat)
        norads = meta["candidate_norad_id"].astype(str).to_numpy()
        true_idx = int(np.flatnonzero(norads == str(first["target_norad_id"]))[0])
        pred_idx = int(np.argmin(rmse))
        wrong_rmse = rmse.copy()
        wrong_rmse[true_idx] = np.inf
        best_wrong_idx = int(np.argmin(wrong_rmse))
        pred_norad = str(meta.iloc[pred_idx]["candidate_norad_id"])
        rows.append(
            {
                "experiment_name": first["experiment_name"],
                "sequence_id": sequence_id,
                "target_name": first["target_name"],
                "target_norad_id": str(first["target_norad_id"]),
                "predicted_name": meta.iloc[pred_idx]["candidate_name"],
                "predicted_norad_id": pred_norad,
                "best_wrong_name": meta.iloc[best_wrong_idx]["candidate_name"],
                "best_wrong_norad_id": str(meta.iloc[best_wrong_idx]["candidate_norad_id"]),
                "true_score_rmse_hz": float(rmse[true_idx]),
                "best_score_rmse_hz": float(rmse[pred_idx]),
                "best_wrong_score_rmse_hz": float(rmse[best_wrong_idx]),
                "margin_hz": float(rmse[best_wrong_idx] - rmse[true_idx]),
                "is_correct": pred_norad == str(first["target_norad_id"]),
                "window_duration_s": first["window_duration_s"],
                "window_center_offset_s": float(first["window_center_offset_s"]),
                "n_time_points": int(first["n_time_points"]),
                "window_start_rel_s": float(first["window_start_rel_s"]),
                "window_end_rel_s": float(first["window_end_rel_s"]),
                "actual_window_duration_s": float(first["actual_window_duration_s"]),
                "scenario": first["scenario"],
                "error_model_variant": first["error_model_variant"],
                "sigma_multiplier": float(first["sigma_multiplier"]),
                "candidate_limit": int(library["candidate_limit"].iloc[0]),
                "sim_index": int(first["sim_index"]),
            }
        )
        for norad, role in HARD.items():
            loc = np.flatnonzero(norads == norad)
            if len(loc) == 0:
                continue
            ci = int(loc[0])
            hard_rows.append(
                {
                    "sequence_id": sequence_id,
                    "candidate_name": meta.iloc[ci]["candidate_name"],
                    "candidate_norad_id": norad,
                    "candidate_role": role,
                    "score_rmse_hz": float(rmse[ci]),
                    "b_hat_hz": float(b[ci]),
                    "k_hat_hz_per_s": float(k[ci]),
                    "residual_std_hz": float(rstd[ci]),
                    "residual_max_abs_hz": float(rmax[ci]),
                    "window_duration_s": first["window_duration_s"],
                    "window_center_offset_s": float(first["window_center_offset_s"]),
                    "sim_index": int(first["sim_index"]),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(hard_rows)


def summarize(results: pd.DataFrame, hard_scores: pd.DataFrame) -> pd.DataFrame:
    summary = (
        results.groupby(["window_duration_s", "window_center_offset_s"], sort=False)
        .agg(
            sequence_count=("sequence_id", "count"),
            accuracy=("is_correct", "mean"),
            wrong_count=("is_correct", lambda s: int((~s).sum())),
            negative_margin_count=("margin_hz", lambda s: int((s < 0).sum())),
            mean_margin_hz=("margin_hz", "mean"),
            median_margin_hz=("margin_hz", "median"),
            min_margin_hz=("margin_hz", "min"),
            p05_margin_hz=("margin_hz", lambda s: float(np.quantile(s, 0.05))),
            mean_true_score_rmse_hz=("true_score_rmse_hz", "mean"),
            mean_best_wrong_score_rmse_hz=("best_wrong_score_rmse_hz", "mean"),
            count_predicted_63502=("predicted_norad_id", lambda s: int((s.astype(str) == "63502").sum())),
            count_predicted_64732=("predicted_norad_id", lambda s: int((s.astype(str) == "64732").sum())),
            count_predicted_66274=("predicted_norad_id", lambda s: int((s.astype(str) == "66274").sum())),
        )
        .reset_index()
    )
    top = results.groupby(["window_duration_s", "window_center_offset_s"])["best_wrong_norad_id"].agg(lambda s: str(s.value_counts().index[0])).reset_index(name="most_common_best_wrong")
    top5 = results.groupby(["window_duration_s", "window_center_offset_s"])["best_wrong_norad_id"].agg(lambda s: ";".join([f"{k}:{v}" for k, v in s.astype(str).value_counts().head(5).items()])).reset_index(name="best_wrong_top_5")
    summary = summary.merge(top, on=["window_duration_s", "window_center_offset_s"]).merge(top5, on=["window_duration_s", "window_center_offset_s"])
    hp = hard_scores.pivot_table(index=["window_duration_s", "window_center_offset_s"], columns="candidate_norad_id", values="score_rmse_hz", aggfunc="mean").reset_index()
    for norad in ["63502", "64732", "66274"]:
        if norad in hp.columns:
            hp = hp.rename(columns={norad: f"mean_score_{norad}"})
    return summary.merge(hp, on=["window_duration_s", "window_center_offset_s"], how="left")


def write_plots(results: pd.DataFrame, summary: pd.DataFrame, hard_scores: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    nonfull = summary[summary["window_duration_s"].astype(str) != "full"].copy()
    nonfull["duration_num"] = pd.to_numeric(nonfull["window_duration_s"])
    dur = nonfull.groupby("duration_num")["min_margin_hz"].min().reset_index()
    fig, ax = plt.subplots(figsize=(8, 4.8)); ax.plot(dur.duration_num, dur.min_margin_hz, marker="o"); ax.set_xlabel("window_duration_s"); ax.set_ylabel("min margin (Hz)"); ax.set_title("partial_pass_duration_vs_min_margin"); ax.grid(True, alpha=.25); fig.tight_layout(); fig.savefig(plots_dir/"controlled_starlink_partial_pass_duration_vs_min_margin.png", dpi=160); plt.close(fig)
    off = nonfull.groupby(["duration_num", "window_center_offset_s"])["min_margin_hz"].min().reset_index()
    fig, ax = plt.subplots(figsize=(10, 5))
    for d, g in off.groupby("duration_num"):
        ax.plot(g.window_center_offset_s, g.min_margin_hz, marker="o", label=str(int(d)))
    ax.set_xlabel("window_center_offset_s"); ax.set_ylabel("min margin (Hz)"); ax.set_title("partial_pass_offset_vs_min_margin"); ax.grid(True, alpha=.25); ax.legend(fontsize=7); fig.tight_layout(); fig.savefig(plots_dir/"controlled_starlink_partial_pass_offset_vs_min_margin.png", dpi=160); plt.close(fig)
    heat = nonfull.pivot_table(index="duration_num", columns="window_center_offset_s", values="min_margin_hz", aggfunc="min").sort_index()
    fig, ax = plt.subplots(figsize=(10, 6)); im=ax.imshow(heat.to_numpy(float), aspect="auto", cmap="viridis"); ax.set_xticks(range(len(heat.columns))); ax.set_xticklabels(heat.columns); ax.set_yticks(range(len(heat.index))); ax.set_yticklabels([int(x) for x in heat.index]); ax.set_title("partial_pass_margin_heatmap"); fig.colorbar(im, ax=ax, label="min margin (Hz)"); fig.tight_layout(); fig.savefig(plots_dir/"controlled_starlink_partial_pass_margin_heatmap.png", dpi=160); plt.close(fig)
    heat = nonfull.pivot_table(index="duration_num", columns="window_center_offset_s", values="accuracy", aggfunc="min").sort_index()
    fig, ax = plt.subplots(figsize=(10, 6)); im=ax.imshow(heat.to_numpy(float), aspect="auto", cmap="Blues", vmin=0, vmax=1); ax.set_xticks(range(len(heat.columns))); ax.set_xticklabels(heat.columns); ax.set_yticks(range(len(heat.index))); ax.set_yticklabels([int(x) for x in heat.index]); ax.set_title("partial_pass_accuracy_heatmap"); fig.colorbar(im, ax=ax, label="accuracy"); fig.tight_layout(); fig.savefig(plots_dir/"controlled_starlink_partial_pass_accuracy_heatmap.png", dpi=160); plt.close(fig)
    counts = results["best_wrong_norad_id"].astype(str).value_counts().head(12)
    fig, ax = plt.subplots(figsize=(9, 4.8)); ax.bar(counts.index, counts.values); ax.set_xlabel("best_wrong_norad_id"); ax.set_ylabel("count"); ax.set_title("partial_pass_best_wrong_distribution"); ax.tick_params(axis="x", rotation=35); ax.grid(True, axis="y", alpha=.25); fig.tight_layout(); fig.savefig(plots_dir/"controlled_starlink_partial_pass_best_wrong_distribution.png", dpi=160); plt.close(fig)
    hs = hard_scores.groupby(["window_duration_s", "candidate_norad_id"])["score_rmse_hz"].mean().reset_index()
    hs = hs[hs.window_duration_s.astype(str) != "full"]; hs["duration_num"] = pd.to_numeric(hs.window_duration_s)
    fig, ax = plt.subplots(figsize=(9, 5))
    for norad, g in hs.groupby("candidate_norad_id"):
        ax.plot(g.groupby("duration_num").score_rmse_hz.mean().index, g.groupby("duration_num").score_rmse_hz.mean().values, marker="o", label=norad)
    ax.set_xlabel("window_duration_s"); ax.set_ylabel("mean score RMSE (Hz)"); ax.set_title("partial_pass_hard_candidate_score_comparison"); ax.grid(True, alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(plots_dir/"controlled_starlink_partial_pass_hard_candidate_score_comparison.png", dpi=160); plt.close(fig)


def write_report(path: Path, results: pd.DataFrame, summary: pd.DataFrame, dataset: pd.DataFrame, hard_scores: pd.DataFrame, manifest: dict) -> None:
    hard = results.sort_values("margin_hz").iloc[0]
    duration_min = summary[summary.window_duration_s.astype(str) != "full"].copy()
    duration_min["duration_num"] = pd.to_numeric(duration_min.window_duration_s)
    first_neg = duration_min.groupby("duration_num")["min_margin_hz"].min().reset_index()
    first_neg = first_neg[first_neg.min_margin_hz < 0].sort_values("duration_num")
    first_neg_text = "无" if first_neg.empty else f"{int(first_neg.iloc[0].duration_num)} s"
    full = summary[summary.window_duration_s.astype(str) == "full"]
    full_text = "无 full window" if full.empty else f"accuracy={float(full.accuracy.iloc[0]):.4f}, min_margin={float(full.min_margin_hz.iloc[0]):.6f} Hz"
    hard_counts = results["best_wrong_norad_id"].astype(str).value_counts()
    text = f"""# Controlled Starlink Partial-pass / Time-alignment Stress Report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 实验目的

本轮是 partial-pass / time-alignment stress，用于在 Stage 2.5 已确认 negative margin 可信的基础上，定位最危险的窗口长度和窗口中心位置。当前不是攻击实验，不是攻击成功率，不是真实 Starlink observation replay，也不是 Starlink CFO truth。

## 2. 输入配置

- target：STARLINK-1008 / 44714
- hard wrong candidates：63502 / 64732 / 66274
- error_model_variant：frequency_scaled
- sigma_multiplier：10
- scenario：offset_plus_noise
- candidate_limit：1000
- center frequency：{float(dataset.center_freq_hz.iloc[0]):.0f} Hz
- station：{dataset.station_name.iloc[0]} / lat={dataset.station_lat_deg.iloc[0]} / lon={dataset.station_lon_deg.iloc[0]} / alt_m={dataset.station_alt_m.iloc[0]}
- window_durations_s：{manifest.get('window_durations_s')}
- window_center_offsets_s：{manifest.get('window_center_offsets_s')}
- num_sims_per_setting：{manifest.get('num_sims_per_setting')}
- mode：controlled_starlink
- observation_id：null

## 3. 数据集规模

- total_sequences：{dataset.sequence_id.nunique()}
- total_rows：{len(dataset)}
- full pass duration：{manifest['full_pass_summary']['duration_s']} s
- window point range：{int(dataset.n_time_points.min())} - {int(dataset.n_time_points.max())}
- skipped windows：{len(manifest.get('skipped_windows', []))}

## 4. 总体结果

- overall accuracy：{results.is_correct.mean():.6f}
- overall min margin：{results.margin_hz.min():.6f} Hz
- wrong_count：{int((~results.is_correct).sum())}
- negative_margin_count：{int((results.margin_hz < 0).sum())}
- 全局最危险 window setting：duration={hard.window_duration_s}, offset={hard.window_center_offset_s}, best_wrong={hard.best_wrong_name}/{hard.best_wrong_norad_id}, margin={hard.margin_hz:.6f} Hz

## 5. 窗口长度影响

- 最早出现负 margin 的窗口长度：{first_neg_text}
- full window 稳定性：{full_text}
- 最低 min margin 的 duration：{hard.window_duration_s}

## 6. 窗口中心偏移影响

最危险 offset 为 `{hard.window_center_offset_s}` 秒。危险区域是否集中在 pass 中心附近，请结合 heatmap 和 summary CSV 查看。

## 7. hard wrong candidate 对比

- best wrong 计数 top 10：{hard_counts.head(10).to_dict()}
- 63502 作为 best wrong 次数：{int(hard_counts.get('63502', 0))}
- 64732 作为 best wrong 次数：{int(hard_counts.get('64732', 0))}
- 66274 作为 best wrong 次数：{int(hard_counts.get('66274', 0))}

## 8. 最危险 setting

- window_duration_s：{hard.window_duration_s}
- window_center_offset_s：{hard.window_center_offset_s}
- min_margin_hz：{hard.margin_hz:.6f}
- best_wrong candidate：{hard.best_wrong_name} / {hard.best_wrong_norad_id}
- true_score_rmse_hz：{hard.true_score_rmse_hz:.6f}
- best_wrong_score_rmse_hz：{hard.best_wrong_score_rmse_hz:.6f}
- n_time_points：{hard.n_time_points}
- wrong_count in setting：{int(summary[(summary.window_duration_s.astype(str)==str(hard.window_duration_s)) & (summary.window_center_offset_s==hard.window_center_offset_s)].wrong_count.iloc[0])}
- negative_margin_count in setting：{int(summary[(summary.window_duration_s.astype(str)==str(hard.window_duration_s)) & (summary.window_center_offset_s==hard.window_center_offset_s)].negative_margin_count.iloc[0])}

## 9. 结论边界

当前是 controlled partial-pass stress。负 margin 说明 matcher 在该受控条件下失稳；不能解释为真实攻击成功率，不能解释为真实 Starlink observation 结果。后续 attack 需要基于本轮定位出的窗口和 hard wrong 设计。

## 10. 下一步建议

若某个 duration/offset 明显最危险，进入 near-neighbor replay attack；若 time offset 显著影响结果，进入 time-shift attack；若没有明显规律，做更细窗口 sweep。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--candidate-library", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--hard-candidate-scores", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        check_outputs([args.output, args.summary, args.hard_candidate_scores, args.report], args.overwrite)
        dataset = pd.read_csv(args.dataset)
        library = pd.read_csv(args.candidate_library)
        library = library[library["candidate_limit"] == 1000].copy()
        library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
        manifest = __import__("json").loads(args.manifest.read_text(encoding="utf-8"))
        results, hard_scores = match(dataset, library)
        summary = summarize(results, hard_scores)
        args.output.parent.mkdir(parents=True, exist_ok=True); results.to_csv(args.output, index=False)
        args.summary.parent.mkdir(parents=True, exist_ok=True); summary.to_csv(args.summary, index=False)
        args.hard_candidate_scores.parent.mkdir(parents=True, exist_ok=True); hard_scores.to_csv(args.hard_candidate_scores, index=False)
        write_plots(results, summary, hard_scores, args.plots_dir)
        write_report(args.report, results, summary, dataset, hard_scores, manifest)
    except InputError as exc:
        print(f"错误: {exc}")
        return 2
    print(f"partial-pass matcher 完成: {args.output}")
    print(f"accuracy={results.is_correct.mean():.6f}, min_margin={results.margin_hz.min():.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
