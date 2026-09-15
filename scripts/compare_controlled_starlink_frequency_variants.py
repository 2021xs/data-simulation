#!/usr/bin/env python
"""Compare controlled Starlink Ku-band error model variants."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


class InputError(ValueError):
    pass


def fail(message: str) -> None:
    raise InputError(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unscaled-dataset", required=True, type=Path)
    parser.add_argument("--unscaled-manifest", required=True, type=Path)
    parser.add_argument("--unscaled-results", required=True, type=Path)
    parser.add_argument("--frequency-scaled-dataset", required=True, type=Path)
    parser.add_argument("--frequency-scaled-manifest", required=True, type=Path)
    parser.add_argument("--frequency-scaled-results", required=True, type=Path)
    parser.add_argument("--candidate-library", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def load_json(path: Path) -> dict:
    if not path.exists():
        fail(f"manifest 不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"CSV 不存在: {path}")
    return pd.read_csv(path)


def scenario_summary(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby(["error_model_variant", "scenario"])
        .agg(
            sequences=("sim_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_margin_hz=("margin_hz", "mean"),
            min_margin_hz=("margin_hz", "min"),
            mean_true_score_rmse_hz=("true_score_rmse_hz", "mean"),
            mean_best_wrong_score_rmse_hz=("best_wrong_score_rmse_hz", "mean"),
        )
        .reset_index()
    )


def target_summary(results: pd.DataFrame) -> pd.DataFrame:
    return (
        results.groupby(["error_model_variant", "target_name", "target_norad_id"])
        .agg(
            sequences=("sim_id", "count"),
            accuracy=("is_correct", "mean"),
            mean_margin_hz=("margin_hz", "mean"),
            min_margin_hz=("margin_hz", "min"),
            error_count=("is_correct", lambda values: int((~values).sum())),
        )
        .reset_index()
    )


def variant_overview(dataset: pd.DataFrame, results: pd.DataFrame, manifest: dict, variant: str) -> dict:
    hard = results.sort_values("margin_hz").iloc[0]
    return {
        "variant": variant,
        "total_sequences": int(results["sim_id"].nunique()),
        "total_rows": int(len(dataset)),
        "overall_accuracy": float(results["is_correct"].mean()),
        "min_margin_hz": float(results["margin_hz"].min()),
        "hardest_target": f"{hard.target_name} / {hard.target_norad_id}",
        "most_confusable_pair": f"{hard.target_name} / {hard.target_norad_id} vs {hard.best_wrong_name} / {hard.best_wrong_norad_id}",
        "best_wrong_name": str(hard.best_wrong_name),
        "best_wrong_norad_id": str(hard.best_wrong_norad_id),
        "mean_margin_hz": float(results["margin_hz"].mean()),
        "doppler_min_hz": float(dataset["doppler_hz"].min()),
        "doppler_max_hz": float(dataset["doppler_hz"].max()),
        "target_count": int(dataset["target_norad_id"].nunique()),
        "candidate_limit": int(manifest.get("candidate_limit", 0)),
    }


def write_plots(results: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    scen = scenario_summary(results)
    targ = target_summary(results)

    fig, ax = plt.subplots(figsize=(10, 4.8))
    for variant, group in scen.groupby("error_model_variant"):
        ax.plot(group["scenario"], group["accuracy"], marker="o", label=variant)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("accuracy")
    ax.set_title("controlled_starlink_frequency_variant_accuracy_by_scenario")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_frequency_variant_accuracy_by_scenario.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.8))
    for variant, group in scen.groupby("error_model_variant"):
        ax.plot(group["scenario"], group["mean_margin_hz"], marker="o", label=variant)
    ax.set_ylabel("mean margin (Hz)")
    ax.set_title("controlled_starlink_frequency_variant_margin_by_scenario")
    ax.tick_params(axis="x", rotation=25)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_frequency_variant_margin_by_scenario.png", dpi=160)
    plt.close(fig)

    pivot = targ.pivot(index="target_name", columns="error_model_variant", values="min_margin_hz")
    fig, ax = plt.subplots(figsize=(11, 5.2))
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel("min margin (Hz)")
    ax.set_title("controlled_starlink_frequency_variant_min_margin_by_target")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.grid(True, axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_frequency_variant_min_margin_by_target.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.6, 5.6))
    for variant, group in results.groupby("error_model_variant"):
        ax.scatter(group["true_score_rmse_hz"], group["best_wrong_score_rmse_hz"], s=18, alpha=0.55, label=variant)
    ax.set_xlabel("true score RMSE (Hz)")
    ax.set_ylabel("best wrong score RMSE (Hz)")
    ax.set_title("controlled_starlink_frequency_variant_true_vs_best_wrong_rmse")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "controlled_starlink_frequency_variant_true_vs_best_wrong_rmse.png", dpi=160)
    plt.close(fig)


def markdown_table(df: pd.DataFrame, columns: list[str]) -> str:
    rows = []
    for _, row in df[columns].iterrows():
        values = []
        for value in row:
            if isinstance(value, float):
                values.append(f"{value:.6f}")
            else:
                values.append(str(value))
        rows.append("| " + " | ".join(values) + " |")
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * len(columns)) + " |"
    return "\n".join([header, sep, *rows])


def write_report(
    report_path: Path,
    unscaled_dataset: pd.DataFrame,
    scaled_dataset: pd.DataFrame,
    unscaled_manifest: dict,
    scaled_manifest: dict,
    candidate_library: pd.DataFrame,
    all_results: pd.DataFrame,
) -> dict[str, dict]:
    overviews = {
        "unscaled": variant_overview(unscaled_dataset, all_results[all_results.error_model_variant == "unscaled"], unscaled_manifest, "unscaled"),
        "frequency_scaled": variant_overview(
            scaled_dataset,
            all_results[all_results.error_model_variant == "frequency_scaled"],
            scaled_manifest,
            "frequency_scaled",
        ),
    }
    scen = scenario_summary(all_results)
    targ = target_summary(all_results)
    station = unscaled_manifest.get("station", {})
    passes = unscaled_manifest.get("pass_window_summary", unscaled_manifest.get("passes", []))
    pass_durations = [float(item.get("duration_s", 0.0)) for item in passes]
    freq_scale = float(unscaled_manifest["frequency_scale_factor"])
    source_freq = float(unscaled_manifest["source_center_freq_hz"])
    sim_freq = float(unscaled_manifest["simulation_center_freq_hz"])
    margin_ratio = overviews["frequency_scaled"]["mean_margin_hz"] / overviews["unscaled"]["mean_margin_hz"]
    scenario_table = markdown_table(
        scen,
        [
            "error_model_variant",
            "scenario",
            "sequences",
            "accuracy",
            "mean_margin_hz",
            "min_margin_hz",
            "mean_true_score_rmse_hz",
            "mean_best_wrong_score_rmse_hz",
        ],
    )
    target_min = targ.sort_values(["error_model_variant", "min_margin_hz"]).groupby("error_model_variant").head(1)
    target_table = markdown_table(target_min, ["error_model_variant", "target_name", "target_norad_id", "accuracy", "mean_margin_hz", "min_margin_hz"])
    pass_duration_text = f"{min(pass_durations):.1f} - {max(pass_durations):.1f} s" if pass_durations else "unknown"

    text = f"""# Controlled Starlink Ku-band Frequency Variant 对比报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 实验目的

本轮是 Starlink Ku-band frequency variant + error model sensitivity baseline。它不是攻击实验，不是真实 Starlink observation replay，不是高精度定轨，也不是真实 CFO 分布估计。

## 2. 输入配置

- source_center_freq_hz：{source_freq:.0f}
- simulation_center_freq_hz：{sim_freq:.0f}
- frequency_scale_factor：{freq_scale:.9f}
- target_count：{unscaled_manifest.get('target_count')}
- candidate_limit：{unscaled_manifest.get('candidate_limit')}
- num_sims_per_target：{unscaled_manifest.get('num_sims_per_target')}
- scenarios：{', '.join(unscaled_manifest.get('scenarios', []))}
- station：{station.get('name')} / lat={station.get('lat_deg')} / lon={station.get('lon_deg')} / alt_m={station.get('alt_m')}
- TLE 文件：{unscaled_manifest.get('tle_source_path')}
- mode：controlled_starlink
- observation_id：null
- pass duration 概况：{pass_duration_text}
- candidate library 行数：{len(candidate_library)}

## 3. 两版误差模型说明

`unscaled` 使用前期 SatNOGS / STRF 提取的 effective residual 参数范围，用于 first-order robustness test，不能解释成 Starlink Ku-band 真值。

`frequency_scaled` 按频率比例缩放 `b / k / sigma`，用于 ppm-sensitive sensitivity setting，不能解释成所有误差真实线性缩放，也不能写成真实 Starlink Ku-band CFO 分布。

## 4. 数据集规模

| variant | target 数 | sequence 数 | row 数 | scenario 数 | candidate 数 |
|---|---:|---:|---:|---:|---:|
| unscaled | {overviews['unscaled']['target_count']} | {overviews['unscaled']['total_sequences']} | {overviews['unscaled']['total_rows']} | {unscaled_dataset.scenario.nunique()} | {overviews['unscaled']['candidate_limit']} |
| frequency_scaled | {overviews['frequency_scaled']['target_count']} | {overviews['frequency_scaled']['total_sequences']} | {overviews['frequency_scaled']['total_rows']} | {scaled_dataset.scenario.nunique()} | {overviews['frequency_scaled']['candidate_limit']} |

## 5. Matcher 结果

{scenario_table}

## 6. hardest target / most confusable pair

{target_table}

- unscaled most confusable pair：{overviews['unscaled']['most_confusable_pair']}，min margin={overviews['unscaled']['min_margin_hz']:.6f} Hz
- frequency_scaled most confusable pair：{overviews['frequency_scaled']['most_confusable_pair']}，min margin={overviews['frequency_scaled']['min_margin_hz']:.6f} Hz
- hardest target 是否为 STARLINK-1008 / 44714：unscaled={overviews['unscaled']['hardest_target'] == 'STARLINK-1008 / 44714'}，frequency_scaled={overviews['frequency_scaled']['hardest_target'] == 'STARLINK-1008 / 44714'}
- most confusable pair 是否仍为 STARLINK-1008 / 44714 vs STARLINK-35760 / 66274：unscaled={'STARLINK-1008 / 44714 vs STARLINK-35760 / 66274' in overviews['unscaled']['most_confusable_pair']}，frequency_scaled={'STARLINK-1008 / 44714 vs STARLINK-35760 / 66274' in overviews['frequency_scaled']['most_confusable_pair']}

## 7. 关键结论

- Ku-band 后 Doppler Hz 量级明显变大：本轮 Doppler 范围约为 {unscaled_dataset.doppler_hz.min():.3f} 到 {unscaled_dataset.doppler_hz.max():.3f} Hz。
- unscaled mean margin 为 {overviews['unscaled']['mean_margin_hz']:.6f} Hz；frequency_scaled mean margin 为 {overviews['frequency_scaled']['mean_margin_hz']:.6f} Hz；二者比例约为 {margin_ratio:.6f}。
- `frequency_scaled` 会同步放大 `b / k / noise`，其中 `b+k` 会被 matcher 的 nuisance 拟合吸收，噪声会直接抬高 true RMSE 并可能压低 margin。
- 当前 controlled baseline 下 matcher 是否稳定识别 true target：unscaled accuracy={overviews['unscaled']['overall_accuracy']:.4f}，frequency_scaled accuracy={overviews['frequency_scaled']['overall_accuracy']:.4f}。
- 即使 accuracy 为 1，也不能解释为攻击不可能；当前没有 near-neighbor stress、time shift、replay 或 partial pass 攻击设置。

## 8. 边界说明

本轮不使用真实 SatNOGS observation，不使用 observation_id，不使用 9424971，不混用 Iridium observation 和 Starlink TLE。`registered_frequency_offset_hz` 只作为 registered offset / effective constant frequency bias；`noise` 是第一版高斯近似。

## 9. 后续建议

下一阶段建议优先做 `near-neighbor stress test`，随后加入 `sigma_multiplier = 1 / 2 / 5 / 10`、`candidate_limit = 200 / 500 / 1000`、partial pass、time shift attack 和 near-neighbor replay attack。
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return overviews


def main() -> int:
    args = parse_args()
    plot_paths = [
        args.plots_dir / "controlled_starlink_frequency_variant_accuracy_by_scenario.png",
        args.plots_dir / "controlled_starlink_frequency_variant_margin_by_scenario.png",
        args.plots_dir / "controlled_starlink_frequency_variant_min_margin_by_target.png",
        args.plots_dir / "controlled_starlink_frequency_variant_true_vs_best_wrong_rmse.png",
    ]
    try:
        check_outputs([args.report, *plot_paths], args.overwrite)
        unscaled_dataset = load_csv(args.unscaled_dataset)
        scaled_dataset = load_csv(args.frequency_scaled_dataset)
        unscaled_manifest = load_json(args.unscaled_manifest)
        scaled_manifest = load_json(args.frequency_scaled_manifest)
        unscaled_results = load_csv(args.unscaled_results)
        scaled_results = load_csv(args.frequency_scaled_results)
        candidate_library = load_csv(args.candidate_library)
        all_results = pd.concat([unscaled_results, scaled_results], ignore_index=True)
        write_plots(all_results, args.plots_dir)
        overviews = write_report(args.report, unscaled_dataset, scaled_dataset, unscaled_manifest, scaled_manifest, candidate_library, all_results)
    except InputError as exc:
        print(f"错误: {exc}")
        return 2
    for variant, overview in overviews.items():
        print(
            f"{variant}: sequences={overview['total_sequences']}, rows={overview['total_rows']}, "
            f"accuracy={overview['overall_accuracy']:.4f}, min_margin={overview['min_margin_hz']:.6f}"
        )
    print(f"对比报告完成: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
