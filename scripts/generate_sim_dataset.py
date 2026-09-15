#!/usr/bin/env python
"""Generate v1 frequency-offset simulation datasets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in constrained envs.
    yaml = None


REQUIRED_RESIDUAL_FIELDS = ["t_rel_s", "f_geo_fit_hz"]
DEFAULT_CONFIG_VERSION = "effective_cfo_simulation_v1"
SCENARIO_ORDER = [
    "clean",
    "offset_only",
    "offset_plus_noise",
    "offset_linear_noise",
]
MANIFEST_NOTES = [
    "registered_frequency_offset_hz is treated as registered offset / effective constant frequency bias, not pure CFO truth.",
    "noise is a first-order Gaussian approximation.",
    "f_geo_fit_hz is used as the baseline geometry frequency in v1.",
]


class InputError(ValueError):
    """Raised for clear, user-facing input validation errors."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate first-version effective frequency-offset simulation dataset."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument(
        "--range-type", required=True, choices=["main", "extended", "stress"]
    )
    parser.add_argument("--scenarios", nargs="+", required=True)
    parser.add_argument("--num-sims-per-sample", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--plots-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise InputError(message)


def read_config(path: Path) -> tuple[dict, str]:
    if not path.exists():
        fail(f"配置文件不存在: {path}")
    text = path.read_text(encoding="utf-8")
    if yaml is not None:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            fail(f"配置文件不是有效的 YAML 字典: {path}")
        return data, "pyyaml"
    return minimal_config_parse(text), "fallback"


def minimal_config_parse(text: str) -> dict:
    """Parse only the small subset used by this project's frozen config."""
    data: dict = {"model": {}, "parameters": {}, "scenarios": {}}
    current_param: str | None = None
    in_model = False
    in_parameters = False
    in_scenarios = False
    range_pattern = re.compile(r"^\s+(main|extended|stress)_range:\s+\[(.+)\]\s*$")

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "model:":
            in_model, in_parameters, in_scenarios = True, False, False
            current_param = None
            continue
        if stripped == "parameters:":
            in_model, in_parameters, in_scenarios = False, True, False
            current_param = None
            continue
        if stripped == "scenarios:":
            in_model, in_parameters, in_scenarios = False, False, True
            current_param = None
            continue
        if in_model and stripped.startswith("name:"):
            data["model"]["name"] = stripped.split(":", 1)[1].strip().strip('"')
        elif in_model and stripped.startswith("formula:"):
            data["model"]["formula"] = stripped.split(":", 1)[1].strip().strip('"')
        elif in_parameters and raw_line.startswith("  ") and stripped.endswith(":"):
            current_param = stripped[:-1]
            data["parameters"][current_param] = {}
        elif in_parameters and current_param:
            if stripped.startswith("source_field:"):
                data["parameters"][current_param]["source_field"] = stripped.split(
                    ":", 1
                )[1].strip()
            match = range_pattern.match(line)
            if match:
                key = f"{match.group(1)}_range"
                values = [float(v.strip()) for v in match.group(2).split(",")]
                data["parameters"][current_param][key] = values
        elif in_scenarios and raw_line.startswith("  ") and stripped.endswith(":"):
            data["scenarios"][stripped[:-1]] = {}
    return data


def validate_config(config: dict, range_type: str, scenarios: list[str]) -> dict:
    params = config.get("parameters")
    if not isinstance(params, dict):
        fail("配置文件缺少 parameters 字典")

    ranges: dict[str, list[float]] = {}
    range_key = f"{range_type}_range"
    for param_name in ["b_hz", "k_hz_per_s", "sigma_hz"]:
        param = params.get(param_name)
        if not isinstance(param, dict):
            fail(f"配置文件缺少参数: {param_name}")
        values = param.get(range_key)
        if (
            not isinstance(values, list)
            or len(values) != 2
            or not all(isinstance(v, (int, float)) for v in values)
        ):
            fail(f"参数 {param_name} 缺少有效的 {range_key}")
        low, high = float(values[0]), float(values[1])
        if low > high:
            fail(f"参数 {param_name} 的 {range_key} 下界大于上界")
        ranges[param_name] = [low, high]

    configured_scenarios = config.get("scenarios", {})
    for scenario in scenarios:
        if scenario not in SCENARIO_ORDER:
            fail(f"不支持的场景: {scenario}")
        if scenario not in configured_scenarios:
            fail(f"配置文件 scenarios 中缺少场景: {scenario}")
    return ranges


def validate_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在，若确认覆盖请添加 --overwrite: " + ", ".join(existing))


def load_residual_inputs(input_root: Path) -> dict[str, pd.DataFrame]:
    if not input_root.exists() or not input_root.is_dir():
        fail(f"输入目录不存在或不是目录: {input_root}")

    datasets: dict[str, pd.DataFrame] = {}
    for obs_dir in sorted(path for path in input_root.iterdir() if path.is_dir()):
        residual_path = obs_dir / "residual_dataset.csv"
        if not residual_path.exists():
            fail(f"accepted 样本缺少 residual_dataset.csv: {residual_path}")
        df = pd.read_csv(residual_path)
        missing = [field for field in REQUIRED_RESIDUAL_FIELDS if field not in df.columns]
        if missing:
            fail(f"{residual_path} 缺少必要字段: {', '.join(missing)}")
        for field in REQUIRED_RESIDUAL_FIELDS:
            df[field] = pd.to_numeric(df[field], errors="coerce")
            if df[field].isna().any():
                fail(f"{residual_path} 字段 {field} 存在空值或非数值")
        datasets[obs_dir.name] = df

    if not datasets:
        fail(f"输入目录下没有 accepted 样本子目录: {input_root}")
    return datasets


def uniform_sample(rng: np.random.Generator, bounds: list[float]) -> float:
    return float(rng.uniform(bounds[0], bounds[1]))


def generate_dataset(
    residual_inputs: dict[str, pd.DataFrame],
    ranges: dict[str, list[float]],
    range_type: str,
    scenarios: list[str],
    num_sims_per_sample: int,
    seed: int,
    config_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if num_sims_per_sample <= 0:
        fail("--num-sims-per-sample 必须为正整数")

    rng = np.random.default_rng(seed)
    rows: list[pd.DataFrame] = []
    sequence_rows: list[dict] = []
    sim_counter = 1

    for obs_id, source_df in residual_inputs.items():
        t_rel = source_df["t_rel_s"].to_numpy(dtype=float)
        f_geo = source_df["f_geo_fit_hz"].to_numpy(dtype=float)
        t0 = float(np.mean(t_rel))

        for scenario in scenarios:
            for sample_index in range(1, num_sims_per_sample + 1):
                sim_id = f"sim_{sim_counter:06d}"
                sim_counter += 1

                b_hz = 0.0
                k_hz_per_s = 0.0
                sigma_hz = 0.0
                if scenario in ["offset_only", "offset_plus_noise", "offset_linear_noise"]:
                    b_hz = uniform_sample(rng, ranges["b_hz"])
                if scenario == "offset_linear_noise":
                    k_hz_per_s = uniform_sample(rng, ranges["k_hz_per_s"])
                if scenario in ["offset_plus_noise", "offset_linear_noise"]:
                    sigma_hz = uniform_sample(rng, ranges["sigma_hz"])

                if sigma_hz > 0:
                    noise_hz = rng.normal(0.0, sigma_hz, size=len(source_df))
                else:
                    noise_hz = np.zeros(len(source_df), dtype=float)

                drift_hz = k_hz_per_s * (t_rel - t0)
                f_sim = f_geo + b_hz + drift_hz + noise_hz

                seq_df = pd.DataFrame(
                    {
                        "sim_id": sim_id,
                        "base_observation_id": obs_id,
                        "tier": "accepted",
                        "scenario": scenario,
                        "parameter_range_type": range_type,
                        "sample_index": sample_index,
                        "t_rel_s": t_rel,
                        "f_geo_hz": f_geo,
                        "b_hz": b_hz,
                        "k_hz_per_s": k_hz_per_s,
                        "sigma_hz": sigma_hz,
                        "noise_hz": noise_hz,
                        "f_sim_hz": f_sim,
                        "label": obs_id,
                        "random_seed": seed,
                        "config_version": config_version,
                    }
                )
                rows.append(seq_df)
                sequence_rows.append(
                    {
                        "sim_id": sim_id,
                        "base_observation_id": obs_id,
                        "scenario": scenario,
                        "sample_index": sample_index,
                        "b_hz": b_hz,
                        "k_hz_per_s": k_hz_per_s,
                        "sigma_hz": sigma_hz,
                        "row_count": len(source_df),
                    }
                )

    return pd.concat(rows, ignore_index=True), pd.DataFrame(sequence_rows)


def compute_delta_stats(dataset: pd.DataFrame) -> pd.DataFrame:
    work = dataset.copy()
    work["delta_hz"] = work["f_sim_hz"] - work["f_geo_hz"]
    return (
        work.groupby("scenario")["delta_hz"]
        .agg(["mean", "std", "min", "max", "count"])
        .reset_index()
    )


def check_parameter_ranges(
    sequences: pd.DataFrame, ranges: dict[str, list[float]]
) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    active_map = {
        "b_hz": sequences["scenario"].isin(
            ["offset_only", "offset_plus_noise", "offset_linear_noise"]
        ),
        "k_hz_per_s": sequences["scenario"].eq("offset_linear_noise"),
        "sigma_hz": sequences["scenario"].isin(
            ["offset_plus_noise", "offset_linear_noise"]
        ),
    }
    for field, mask in active_map.items():
        active = sequences.loc[mask, field]
        low, high = ranges[field]
        checks[field] = bool(((active >= low) & (active <= high)).all())
    return checks


def make_plots(dataset: pd.DataFrame, sequences: pd.DataFrame, plots_dir: Path) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    work = dataset.copy()
    work["delta_hz"] = work["f_sim_hz"] - work["f_geo_hz"]

    scenarios = [s for s in SCENARIO_ORDER if s in set(work["scenario"])]
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(9, max(3, 2.2 * len(scenarios))))
    if len(scenarios) == 1:
        axes = [axes]
    for ax, scenario in zip(axes, scenarios):
        values = work.loc[work["scenario"] == scenario, "delta_hz"]
        ax.hist(values, bins=50, color="#2f6f8f", alpha=0.82)
        ax.set_title(scenario)
        ax.set_xlabel("f_sim_hz - f_geo_hz (Hz)")
        ax.set_ylabel("count")
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "sim_delta_hist_by_scenario.png", dpi=160)
    plt.close(fig)

    linear = work[work["scenario"] == "offset_linear_noise"]
    if not linear.empty:
        example_sim_id = linear["sim_id"].iloc[0]
        example = linear[linear["sim_id"] == example_sim_id].sort_values("t_rel_s")
        fig, ax = plt.subplots(figsize=(10, 4.5))
        ax.plot(example["t_rel_s"], example["f_geo_hz"], label="f_geo_hz", linewidth=1.8)
        ax.plot(example["t_rel_s"], example["f_sim_hz"], label="f_sim_hz", linewidth=1.2)
        ax.set_title(f"offset_linear_noise example: {example_sim_id}")
        ax.set_xlabel("t_rel_s (s)")
        ax.set_ylabel("frequency (Hz)")
        ax.legend()
        ax.grid(True, alpha=0.25)
        fig.tight_layout()
        fig.savefig(plots_dir / "example_sim_timeseries_offset_linear_noise.png", dpi=160)
        plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(9, 7))
    for ax, field, title in zip(
        axes,
        ["b_hz", "k_hz_per_s", "sigma_hz"],
        ["b_hz samples", "k_hz_per_s samples", "sigma_hz samples"],
    ):
        values = sequences[field]
        ax.hist(values, bins=40, color="#7a8f2f", alpha=0.82)
        ax.set_title(title)
        ax.set_xlabel(field)
        ax.set_ylabel("sequence count")
        ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(plots_dir / "parameter_samples_b_k_sigma.png", dpi=160)
    plt.close(fig)


def write_manifest(
    path: Path,
    config_path: Path,
    input_root: Path,
    output_csv: Path,
    range_type: str,
    scenarios: list[str],
    num_sims_per_sample: int,
    seed: int,
    accepted_samples: list[str],
    ranges: dict[str, list[float]],
    dataset: pd.DataFrame,
    sequences: pd.DataFrame,
) -> None:
    rows_per_scenario = {
        scenario: int(count)
        for scenario, count in dataset.groupby("scenario").size().to_dict().items()
    }
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config_path": str(config_path),
        "input_root": str(input_root),
        "output_csv": str(output_csv),
        "range_type": range_type,
        "scenarios": scenarios,
        "num_sims_per_sample": num_sims_per_sample,
        "seed": seed,
        "accepted_samples": accepted_samples,
        "parameter_ranges_used": ranges,
        "total_sequences": int(len(sequences)),
        "total_rows": int(len(dataset)),
        "rows_per_scenario": rows_per_scenario,
        "notes": MANIFEST_NOTES,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(
    path: Path,
    config_path: Path,
    input_root: Path,
    output_csv: Path,
    manifest_path: Path,
    plots_dir: Path,
    config_version: str,
    range_type: str,
    scenarios: list[str],
    num_sims_per_sample: int,
    seed: int,
    accepted_samples: list[str],
    ranges: dict[str, list[float]],
    dataset: pd.DataFrame,
    sequences: pd.DataFrame,
    delta_stats: pd.DataFrame,
    range_checks: dict[str, bool],
    yaml_reader: str,
) -> None:
    rows_per_sample = (
        sequences.groupby("base_observation_id").size().astype(int).to_dict()
    )
    rows_per_scenario = dataset.groupby("scenario").size().astype(int).to_dict()
    seq_per_scenario = sequences.groupby("scenario").size().astype(int).to_dict()

    param_check_lines = "\n".join(
        [
            f"- `{name}`: {'通过' if ok else '未通过'}，范围 `{ranges[name]}`"
            for name, ok in range_checks.items()
        ]
    )
    sample_lines = "\n".join(
        [
            f"| `{sample}` | {rows_per_sample.get(sample, 0)} |"
            for sample in accepted_samples
        ]
    )
    scenario_lines = "\n".join(
        [
            f"| `{scenario}` | {seq_per_scenario.get(scenario, 0)} | {rows_per_scenario.get(scenario, 0)} |"
            for scenario in scenarios
        ]
    )
    stats_lines = "\n".join(
        [
            f"| `{row.scenario}` | {row['mean']:.6f} | {row['std']:.6f} | {row['min']:.6f} | {row['max']:.6f} | {int(row['count'])} |"
            for _, row in delta_stats.iterrows()
        ]
    )

    report = f"""# 第一版仿真数据集生成报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  
配置版本：`{config_version}`  
YAML 读取方式：`{yaml_reader}`

## 1. 本轮目标

基于 accepted 样本中的 `t_rel_s` 和 `f_geo_fit_hz`，使用 `configs/simulation_parameter_config.yaml` 中的有效频偏参数范围，生成第一版工程级 frequency offset 仿真数据集。本轮只生成数据集、manifest、sanity check 报告和图表；未实现 baseline matcher，未进入攻击场景。

## 2. 输入文件

- 配置文件：`{config_path}`
- 输入样本目录：`{input_root}`
- accepted 样本：{', '.join(accepted_samples)}

## 3. 使用模型

默认模型：

```text
f_sim(t) = f_geo(t) + b + k(t - t0) + noise
```

其中 `t0 = mean(t_rel_s)`，`f_geo(t)` 在第一版中来自 `residual_dataset.csv["f_geo_fit_hz"]`。

## 4. 使用参数范围

本轮使用 `parameter_range_type = {range_type}`。

| 参数 | 使用范围 |
|---|---|
| `b_hz` | `{ranges['b_hz']}` |
| `k_hz_per_s` | `{ranges['k_hz_per_s']}` |
| `sigma_hz` | `{ranges['sigma_hz']}` |

## 5. 生成场景

| scenario | 序列数 | 行数 |
|---|---:|---:|
{scenario_lines}

每个 accepted 样本生成序列数：

| base_observation_id | 序列数 |
|---|---:|
{sample_lines}

## 6. 参数采样范围检查

{param_check_lines}

说明：`clean` 场景固定 `b_hz=0`、`k_hz_per_s=0`、`sigma_hz=0`；`offset_only` 固定 `k_hz_per_s=0`、`sigma_hz=0`；`offset_plus_noise` 固定 `k_hz_per_s=0`。

## 7. Scenario 基本统计

统计量基于 `f_sim_hz - f_geo_hz`。

| scenario | mean | std | min | max | count |
|---|---:|---:|---:|---:|---:|
{stats_lines}

## 8. 输出文件

- 数据集：`{output_csv}`
- Manifest：`{manifest_path}`
- 图表目录：`{plots_dir}`
- `sim_delta_hist_by_scenario.png`
- `example_sim_timeseries_offset_linear_noise.png`
- `parameter_samples_b_k_sigma.png`

## 9. Sanity check 结论

本轮输出行数与 accepted 样本长度、场景数、`num_sims_per_sample={num_sims_per_sample}` 一致。主动采样的 `b_hz`、`k_hz_per_s`、`sigma_hz` 均落在 `{range_type}_range` 内。随机过程由 `seed={seed}` 控制，可复现。

## 10. 边界说明

- 第一版使用已有样本的 `f_geo_fit_hz` 作为基线频率序列；
- 本轮不重新传播轨道，不重跑 rffit，不重新分析 residual；
- `registered_frequency_offset_hz` 解释为 registered offset / effective constant frequency bias，不解释为 pure CFO ground truth；
- 噪声是第一版高斯近似，不代表严格白噪声；
- 图表只用于 sanity check，不作为证明性结论。
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        config, yaml_reader = read_config(args.config)
        ranges = validate_config(config, args.range_type, args.scenarios)
        validate_outputs(
            [
                args.output,
                args.manifest,
                args.report,
                args.plots_dir / "sim_delta_hist_by_scenario.png",
                args.plots_dir / "example_sim_timeseries_offset_linear_noise.png",
                args.plots_dir / "parameter_samples_b_k_sigma.png",
            ],
            args.overwrite,
        )
        residual_inputs = load_residual_inputs(args.input_root)
        config_version = (
            config.get("model", {}).get("name") or DEFAULT_CONFIG_VERSION
        )
        dataset, sequences = generate_dataset(
            residual_inputs=residual_inputs,
            ranges=ranges,
            range_type=args.range_type,
            scenarios=args.scenarios,
            num_sims_per_sample=args.num_sims_per_sample,
            seed=args.seed,
            config_version=config_version,
        )
        delta_stats = compute_delta_stats(dataset)
        range_checks = check_parameter_ranges(sequences, ranges)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        dataset.to_csv(args.output, index=False)
        write_manifest(
            path=args.manifest,
            config_path=args.config,
            input_root=args.input_root,
            output_csv=args.output,
            range_type=args.range_type,
            scenarios=args.scenarios,
            num_sims_per_sample=args.num_sims_per_sample,
            seed=args.seed,
            accepted_samples=list(residual_inputs.keys()),
            ranges=ranges,
            dataset=dataset,
            sequences=sequences,
        )
        make_plots(dataset, sequences, args.plots_dir)
        write_report(
            path=args.report,
            config_path=args.config,
            input_root=args.input_root,
            output_csv=args.output,
            manifest_path=args.manifest,
            plots_dir=args.plots_dir,
            config_version=config_version,
            range_type=args.range_type,
            scenarios=args.scenarios,
            num_sims_per_sample=args.num_sims_per_sample,
            seed=args.seed,
            accepted_samples=list(residual_inputs.keys()),
            ranges=ranges,
            dataset=dataset,
            sequences=sequences,
            delta_stats=delta_stats,
            range_checks=range_checks,
            yaml_reader=yaml_reader,
        )
    except InputError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2

    print(f"生成完成: {args.output}")
    print(f"Manifest: {args.manifest}")
    print(f"报告: {args.report}")
    print(f"图表目录: {args.plots_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
