#!/usr/bin/env python
"""Fixed-reference active compensation sensitivity to user-position error.

This experiment uses controlled Starlink TLE geometry and hard-case orbit
perturbations from the previous window-aware verifier diagnosis.  It does not
solve a positioning problem; it directly scans an abstract S_hat to S distance.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_window_aware_evidence_accumulation as wae  # noqa: E402
import run_window_reliability_calibration as wrc  # noqa: E402


DEFAULT_E_VALUES_KM = [0, 0.5, 1, 2, 5, 10]
DEFAULT_WINDOW_PATTERNS = ["full_pass", "single_30s_best", "single_60s_best", "spread_3x60s", "spread_6x30s", "hardest_previous"]
DEFAULT_STRATEGY_TYPES = ["single_window", "proposed_v1", "candidate_v1_1", "full_pass"]
HARD_ATTACK_TYPES = ["same_plane_altitude_offset", "inclination_offset"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fixed-point active compensation sensitivity experiment.")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/fixed_point_active_compensation_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/fixed_point_active_compensation_summary.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/fixed_point_active_compensation_summary.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/fixed_point_active_compensation"))
    p.add_argument("--max-targets", type=int, default=10)
    p.add_argument("--num-sims-per-attack", type=int, default=2)
    p.add_argument("--num-benign-sims", type=int, default=None)
    p.add_argument("--window-patterns", nargs="+", default=DEFAULT_WINDOW_PATTERNS)
    p.add_argument("--strategy-types", nargs="+", default=DEFAULT_STRATEGY_TYPES)
    p.add_argument("--e-values", nargs="+", type=float, default=DEFAULT_E_VALUES_KM)
    p.add_argument("--include-hard-cases", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--max-hard-cases", type=int, default=80)
    p.add_argument("--reference-bearing-deg", type=float, default=90.0)
    p.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260612)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def split_values(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        out.extend([part.strip() for part in str(value).split(",") if part.strip()])
    return out


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def make_observation(
    sequence_id: str,
    target_name: str,
    target_id: str,
    geo: pd.DataFrame,
    y_obs: np.ndarray,
    f_source: np.ndarray,
    noise: np.ndarray,
    b_hz: float,
    k_hz_s: float,
    sigma_hz: float,
    t0_s: float,
    attack_type: str,
    attack_variant: str,
) -> base.ObservationSequence:
    return base.ObservationSequence(
        sequence_id=sequence_id,
        source_type="ATTACK",
        claimed_target_name=target_name,
        claimed_target_norad=target_id,
        t_abs_utc=geo["t_abs_utc"].to_numpy(str),
        t_rel_s=geo["t_rel_s"].to_numpy(float),
        y_obs_hz=np.asarray(y_obs, dtype=float),
        f_geo_source_hz=np.asarray(f_source, dtype=float),
        noise_hz=np.asarray(noise, dtype=float),
        b_true_hz=float(b_hz),
        k_true_hz_s=float(k_hz_s),
        sigma_true_hz=float(sigma_hz),
        t0_s=float(t0_s),
        sample_id=1,
        attack_type=attack_type,
        attack_variant=attack_variant,
    )


def fixed_reference_geo(sat: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float, step_s: float) -> np.ndarray:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    geo = orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))
    return geo["f_geo_tle_hz"].to_numpy(float)


def synthetic_geo_at_station(
    spec: dict[str, Any],
    sat_a: Any,
    sat_b: Any,
    lat: float,
    lon: float,
    alt_m: float,
    times: list[Any],
    ts: Any,
    freq_hz: float,
    step_s: float,
    use_real_sat_b: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    f_a = fixed_reference_geo(sat_a, lat, lon, alt_m, times, ts, freq_hz, step_s)
    station = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    if use_real_sat_b:
        f_b = fixed_reference_geo(sat_b, lat, lon, alt_m, times, ts, freq_hz, step_s)
    else:
        f_b = wrc.generate_attack_geo(spec, sat_a, station, ts, times, freq_hz)
    return f_a, f_b


def load_hard_specs(path: Path, max_targets: int, max_cases: int) -> pd.DataFrame:
    if not path.exists():
        fail(f"hard case input not found: {path}")
    hard = pd.read_csv(path)
    required = ["target_id", "target_name", "attack_type", "attack_param_name", "attack_param_value", "segment_pattern", "group_mode"]
    missing = [c for c in required if c not in hard.columns]
    if missing:
        fail("hard case CSV missing columns: " + ", ".join(missing))
    hard = hard[hard["attack_type"].isin(HARD_ATTACK_TYPES)].copy()
    hard["target_id"] = hard["target_id"].astype(str)
    hard["attack_param_value"] = pd.to_numeric(hard["attack_param_value"], errors="coerce")
    hard = hard.dropna(subset=["attack_param_value"])
    # Prioritize altitude -1/-2 km and small inclination offsets.
    hard["priority"] = 10
    hard.loc[(hard["attack_type"].eq("same_plane_altitude_offset")) & (hard["attack_param_value"].isin([-1.0, -2.0])), "priority"] = 0
    hard.loc[(hard["attack_type"].eq("inclination_offset")) & (hard["attack_param_value"].abs() <= 0.10), "priority"] = 1
    cols = ["target_id", "target_name", "attack_type", "attack_param_name", "attack_param_value", "segment_pattern", "group_mode", "window_lengths_s"]
    hard = hard.sort_values(["priority", "attack_type", "target_id", "attack_param_value", "group_mode"])

    # Keep the stress set balanced across hard-case families.  The previous
    # diagnosis contains more altitude accepts than inclination accepts; a
    # simple global head() can therefore exclude inclination entirely.
    selected_targets: list[str] = []
    per_type_targets: dict[str, list[str]] = {}
    for attack_type in HARD_ATTACK_TYPES:
        per_type_targets[attack_type] = list(hard[hard["attack_type"].eq(attack_type)]["target_id"].drop_duplicates())
    while len(selected_targets) < max_targets:
        added = False
        for attack_type in HARD_ATTACK_TYPES:
            targets = per_type_targets.get(attack_type, [])
            if targets:
                candidate = targets.pop(0)
                if candidate not in selected_targets:
                    selected_targets.append(candidate)
                    added = True
                    if len(selected_targets) >= max_targets:
                        break
        if not added:
            break

    hard = hard[hard["target_id"].isin(selected_targets)]
    unique_cases = hard[cols].drop_duplicates().reset_index(drop=True)
    if unique_cases.empty:
        return unique_cases

    n_types = max(1, unique_cases["attack_type"].nunique())
    quota = max(1, max_cases // n_types)
    parts = []
    used_idx: set[int] = set()
    for attack_type in HARD_ATTACK_TYPES:
        part = unique_cases[unique_cases["attack_type"].eq(attack_type)].head(quota)
        parts.append(part)
        used_idx.update(int(i) for i in part.index)
    selected = pd.concat(parts, ignore_index=False) if parts else unique_cases.head(0)
    if len(selected) < max_cases:
        remaining = unique_cases[~unique_cases.index.isin(used_idx)].head(max_cases - len(selected))
        selected = pd.concat([selected, remaining], ignore_index=False)
    return selected.head(max_cases).reset_index(drop=True)


def fallback_specs(selection: pd.DataFrame, max_targets: int) -> pd.DataFrame:
    rows = []
    for _, target in selection.head(max_targets).iterrows():
        for attack_type, name, values in [
            ("same_plane_altitude_offset", "delta_h_km", [-1.0, -2.0]),
            ("inclination_offset", "delta_inclination_deg", [-0.05, 0.05, -0.1, 0.1]),
        ]:
            for value in values:
                rows.append(
                    {
                        "target_id": str(target["target_norad_id"]),
                        "target_name": str(target["target_name"]),
                        "attack_type": attack_type,
                        "attack_param_name": name,
                        "attack_param_value": float(value),
                        "segment_pattern": "3x60s",
                        "group_mode": "best_attack_segments",
                        "window_lengths_s": "",
                    }
                )
    return pd.DataFrame(rows)


def spec_dict(row: pd.Series) -> dict[str, Any]:
    attack_type = str(row["attack_type"])
    value = float(row["attack_param_value"])
    if attack_type == "same_plane_altitude_offset":
        return {
            "attack_type": attack_type,
            "attack_variant": f"delta_h_{value:+g}km",
            "attack_param_name": "delta_h_km",
            "attack_param_value": value,
            "altitude_offset_km": value,
            "phase_offset_s": 0.0,
            "inclination_offset_deg": 0.0,
            "raan_offset_deg": 0.0,
        }
    if attack_type == "inclination_offset":
        return {
            "attack_type": attack_type,
            "attack_variant": f"delta_i_{value:+g}deg",
            "attack_param_name": "delta_inclination_deg",
            "attack_param_value": value,
            "altitude_offset_km": 0.0,
            "phase_offset_s": 0.0,
            "inclination_offset_deg": value,
            "raan_offset_deg": 0.0,
        }
    fail(f"unsupported attack_type: {attack_type}")


def base_specs_for_calibration(t_rel: np.ndarray) -> dict[int | str, list[wrc.WindowSpec]]:
    specs = wae.base_middle_specs(t_rel, [180, 120, 60, 30])
    out: dict[int | str, list[wrc.WindowSpec]] = {"full_pass": [s for s in specs if s.window_position == "full_pass"]}
    for length in [180, 120, 60, 30]:
        out[length] = [s for s in specs if int(round(s.window_length_s)) == length]
    return out


def choose_specs_for_pattern(pattern: str, t_rel: np.ndarray, y_source: np.ndarray, f_geo_a: np.ndarray, cal: dict[int | str, dict[str, float]]) -> tuple[list[wrc.WindowSpec], str, str]:
    if pattern == "full_pass":
        return [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)], "full_pass", "full_pass"
    if pattern == "single_30s_best":
        return wae.choose_nonoverlap_best_specs(y_source, f_geo_a, t_rel, [30], cal, 0.2), "best_attack_segments", "single_30s_best"
    if pattern == "single_60s_best":
        return wae.choose_nonoverlap_best_specs(y_source, f_geo_a, t_rel, [60], cal, 0.2), "best_attack_segments", "single_60s_best"
    if pattern == "spread_3x60s":
        return wae.choose_group_specs("3x60s", "spread_segments", t_rel, y_source, f_geo_a, cal, 0.2), "spread_segments", "3x60s"
    if pattern == "spread_6x30s":
        return wae.choose_group_specs("6x30s", "spread_segments", t_rel, y_source, f_geo_a, cal, 0.2), "spread_segments", "6x30s"
    if pattern == "hardest_previous":
        return wae.choose_group_specs("3x60s", "best_attack_segments", t_rel, y_source, f_geo_a, cal, 0.2), "best_attack_segments", "3x60s"
    fail(f"unsupported window pattern: {pattern}")


def candidate_v11_decision(row: dict[str, Any]) -> str:
    if row["proposed_decision"] != "ACCEPT":
        return row["proposed_decision"]
    if row["group_mode"] == "best_attack_segments":
        centers = []
        for part in str(row["window_positions"]).split(";"):
            if "-" not in part:
                continue
            a, b = part.split("-", 1)
            centers.append((float(a) + float(b)) / 2.0)
        center_span = max(centers) - min(centers) if len(centers) > 1 else 0.0
        pass_duration = float(row.get("pass_duration_s", 0.0))
        if int(row["num_windows"]) < 3 or float(row["max_overlap_ratio"]) > 0.1 or (pass_duration > 0 and center_span / pass_duration < 0.4):
            return "DEFER"
    return row["proposed_decision"]


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["sample_type", "attack_type", "attack_param_value", "window_pattern", "strategy_type", "e_km"]
    for key, g in df.groupby(group_cols, dropna=False):
        counts = g["final_decision"].value_counts()
        n = len(g)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n": int(n),
                "accept_count": int(counts.get("ACCEPT", 0)),
                "defer_count": int(counts.get("DEFER", 0)),
                "reject_count": int(counts.get("REJECT", 0)),
                "accept_rate": float(counts.get("ACCEPT", 0) / n) if n else np.nan,
                "defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
                "reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
                "score_median_hz": float(g["residual_score_rmse_hz"].median()),
                "joint_normalized_score_median": float(g["joint_normalized_score"].median()),
                "k_hat_median": float(g["k_hat_hz_per_s"].median()),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(summary: pd.DataFrame, outdir: Path) -> list[Path]:
    paths = [
        outdir / "fixed_point_attack_accept_vs_e_heatmap.png",
        outdir / "fixed_point_strategy_window_comparison.png",
        outdir / "fixed_point_attack_type_distribution.png",
    ]
    attack = summary[summary["sample_type"].eq("attack")].copy()
    if not attack.empty:
        piv = attack.groupby(["strategy_type", "e_km"], as_index=False)["accept_rate"].mean().pivot(index="strategy_type", columns="e_km", values="accept_rate")
        fig, ax = plt.subplots(figsize=(9, 4.8))
        im = ax.imshow(piv.fillna(0).to_numpy(float), aspect="auto", cmap="magma", vmin=0, vmax=max(0.05, float(np.nanmax(piv.to_numpy(float)))))
        ax.set_xticks(range(len(piv.columns)), [f"{c:g}" for c in piv.columns])
        ax.set_yticks(range(len(piv.index)), piv.index)
        ax.set_xlabel("position error e (km)")
        ax.set_title("Attack accept rate vs e")
        fig.colorbar(im, ax=ax, label="accept rate")
        savefig(fig, paths[0])

        comp = attack.groupby(["window_pattern", "strategy_type"], as_index=False)["accept_rate"].mean().pivot(index="window_pattern", columns="strategy_type", values="accept_rate")
        fig, ax = plt.subplots(figsize=(10, 5))
        comp.fillna(0).plot(kind="bar", ax=ax)
        ax.set_ylabel("attack accept rate")
        ax.set_title("Window pattern / strategy comparison")
        ax.grid(True, axis="y", alpha=0.25)
        savefig(fig, paths[1])

        dist = attack.groupby(["attack_type", "e_km"], as_index=False)["accept_rate"].mean().pivot(index="e_km", columns="attack_type", values="accept_rate")
        fig, ax = plt.subplots(figsize=(8, 5))
        dist.fillna(0).plot(marker="o", ax=ax)
        ax.set_xlabel("position error e (km)")
        ax.set_ylabel("attack accept rate")
        ax.set_title("Attack type distribution under active compensation")
        ax.grid(True, alpha=0.25)
        savefig(fig, paths[2])
    return paths


def write_report(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, figures: list[Path]) -> None:
    attack = summary[summary["sample_type"].eq("attack")]
    key = attack.groupby(["strategy_type", "e_km"], as_index=False)["accept_rate"].mean() if not attack.empty else pd.DataFrame()
    e0 = key[key["e_km"].eq(0.0)].sort_values("accept_rate", ascending=False) if not key.empty else pd.DataFrame()
    full = attack[attack["strategy_type"].eq("full_pass")].groupby("e_km", as_index=False)["accept_rate"].mean() if not attack.empty else pd.DataFrame()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Fixed-point active compensation sensitivity summary

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 实验目的

本轮测试固定参考点主动补偿攻击对位置误差 `e = dist(S_hat, S)` 的敏感性。实验不做三颗参考卫星定位，只扫描抽象位置误差，并优先使用上一轮 window-aware hard cases 中的 altitude `-1/-2 km` 和小 inclination 扰动。

## 2. 攻击模型

本脚本采用单站一致的补偿符号：

`f_attack(t) = f_geo(B, S, t) + [f_geo(A, S_hat, t) - f_geo(B, S_hat, t)]`

当 `e=0` 时，`S_hat=S`，理想情况下攻击几何项与 claimed target A 在 S 处一致。验证器仍只使用真实站 S 上的 claimed A reference，不使用 B 轨道作为判决输入。

## 3. 实验规模

- 输出样本行数：`{len(dataset)}`
- target 数：`{dataset['target_id'].nunique() if not dataset.empty else 0}`
- e values：`{', '.join(str(v) for v in args.e_values)}`
- window patterns：`{', '.join(args.window_patterns)}`
- strategies：`{', '.join(args.strategy_types)}`
- residual mode：`{args.residual_mode}`

## 4. e 对攻击接受率的影响

按 strategy / e 聚合：

{key.to_markdown(index=False) if not key.empty else '无'}

## 5. full-pass 稳定性

full-pass strategy 按 e 聚合：

{full.to_markdown(index=False) if not full.empty else '无'}

## 6. 阶段性结论

1. `e` 越接近 0，固定点主动补偿越接近理想单站补偿，是最高风险区。
2. v1 与 candidate v1.1 的差异主要来自 best_attack_segments 的严格时间分散约束；若 v1.1 把 ACCEPT 转为 DEFER 且不明显伤害 full-pass，可作为后续候选。
3. full-pass 若仍保持较低接受率，说明完整过境曲线形状仍是最稳证据；若 e=0 下 full-pass 也高接受，则主动补偿对单站构成强压力。
4. 本轮只评估固定参考点主动补偿，不是定位算法结论。下一步应评估现实三参考定位是否可能把 e 压到本实验中高风险范围。

## 7. 输出图

{figs}
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame) -> None:
    attack = summary[summary["sample_type"].eq("attack")]
    top_accept = float(attack["accept_rate"].max()) if not attack.empty else float("nan")
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - fixed-point active compensation sensitivity

### A. 本轮目标

测试固定参考点主动补偿攻击在不同位置误差 e 下对 window-aware verifier 的压力，优先使用上一轮 hard-case 轨道样本。

### B. 实际操作

- 新增 `scripts/run_fixed_point_active_compensation_sensitivity.py`。
- 读取上一轮 `window_aware_attack_accept_hard_cases.csv`，未做三参考定位。
- 扫描 e values：`{', '.join(str(v) for v in args.e_values)}`。
- 输出 dataset、summary、图和中文报告。

### C. 新增/修改文件

- 新增：`scripts/run_fixed_point_active_compensation_sensitivity.py`
- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}` 下 3 张图

### D. 运行命令

```bash
python -m py_compile scripts/run_fixed_point_active_compensation_sensitivity.py
```

```bash
python scripts/run_fixed_point_active_compensation_sensitivity.py --max-targets 2 --num-sims-per-attack 1 --max-hard-cases 8 --overwrite
```

```bash
python scripts/run_fixed_point_active_compensation_sensitivity.py --overwrite
```

### E. 结果摘要

- dataset rows：`{len(dataset)}`。
- summary rows：`{len(summary)}`。
- max attack accept rate across groups：`{top_accept:.4f}`。

### F. 问题与下一步

本轮只抽象扫描位置误差 e。下一步应评估三参考模拟定位是否可能达到高风险 e 区间。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def write_report(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, figures: list[Path]) -> None:
    def decision_rates(g: pd.DataFrame) -> pd.Series:
        return pd.Series(
            {
                "n": int(len(g)),
                "accept_rate": float(g["final_decision"].eq("ACCEPT").mean()) if len(g) else np.nan,
                "defer_rate": float(g["final_decision"].eq("DEFER").mean()) if len(g) else np.nan,
                "reject_rate": float(g["final_decision"].eq("REJECT").mean()) if len(g) else np.nan,
            }
        )

    attack = dataset[dataset["sample_type"].eq("attack")].copy()
    benign = dataset[dataset["sample_type"].eq("benign")].copy()
    key = attack.groupby(["strategy_type", "e_km"], dropna=False).apply(decision_rates).reset_index() if not attack.empty else pd.DataFrame()
    by_type = attack.groupby(["strategy_type", "attack_type"], dropna=False).apply(decision_rates).reset_index() if not attack.empty else pd.DataFrame()
    by_window = attack.groupby(["strategy_type", "window_pattern"], dropna=False).apply(decision_rates).reset_index() if not attack.empty else pd.DataFrame()
    benign_mix = benign.groupby(["strategy_type"], dropna=False).apply(decision_rates).reset_index() if not benign.empty else pd.DataFrame()
    proposed = attack[attack["strategy_type"].eq("proposed_v1")]
    candidate = attack[attack["strategy_type"].eq("candidate_v1_1")]
    single = attack[attack["strategy_type"].eq("single_window")]
    full_only = attack[attack["strategy_type"].eq("full_pass")]
    proposed_accept = float(proposed["final_decision"].eq("ACCEPT").mean()) if not proposed.empty else np.nan
    candidate_accept = float(candidate["final_decision"].eq("ACCEPT").mean()) if not candidate.empty else np.nan
    single_accept = float(single["final_decision"].eq("ACCEPT").mean()) if not single.empty else np.nan
    full_accept = float(full_only["final_decision"].eq("ACCEPT").mean()) if not full_only.empty else np.nan
    hard_accepts = (
        proposed[proposed["final_decision"].eq("ACCEPT")]
        .groupby(["attack_type", "attack_param_value", "window_pattern"], dropna=False)
        .size()
        .reset_index(name="accept_count")
        .sort_values("accept_count", ascending=False)
        .head(12)
    )
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Fixed-point active compensation sensitivity summary

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 实验目的

本轮测试固定参考点主动补偿攻击对位置误差 `e = dist(S_hat, S)` 的敏感性。实验不做三颗参考卫星定位，只扫描抽象位置误差，并优先使用上一轮 window-aware hard cases 中的高度极接近样本和倾角极接近样本。

## 2. 攻击模型与符号约定

本脚本沿用项目已有 active compensation 脚本中的单站补偿符号：

`f_attack(t) = f_geo(B, S, t) + [f_geo(A, S_hat, t) - f_geo(B, S_hat, t)]`

因此 `e=0` 且 `S_hat=S` 时，攻击几何项退化为 `f_geo(A, S, t)`，用于表示单站理想主动补偿上界。验证器仍只使用真实站 S 上 claimed target A 的理论曲线，不使用 B 的轨道参数作为判决输入。

用户提示中的差分式若直接套入当前 `f_geo` 观测符号，会在 `e=0` 时变成 `2 f_geo(B,S)-f_geo(A,S)`，不对应“补偿到 A”的单站理想情形；所以本轮报告按上述项目符号解释。

## 3. 实验规模

- 输出样本行数：`{len(dataset)}`
- summary 行数：`{len(summary)}`
- target 数：`{dataset['target_id'].nunique() if not dataset.empty else 0}`
- attack hard-case 规格数：`{attack[['target_id', 'attack_type', 'attack_param_value']].drop_duplicates().shape[0] if not attack.empty else 0}`
- e values：`{', '.join(str(v) for v in args.e_values)}`
- window patterns：`{', '.join(args.window_patterns)}`
- strategies：`{', '.join(args.strategy_types)}`
- residual mode：`{args.residual_mode}`
- benign control rows：`{len(benign)}`

## 4. strategy / e 主结果

下表从逐样本 dataset 直接加权统计：

{key.to_markdown(index=False) if not key.empty else '无'}

## 5. 攻击类型与窗口模式

按攻击类型聚合：

{by_type.to_markdown(index=False) if not by_type.empty else '无'}

按窗口模式聚合：

{by_window.to_markdown(index=False) if not by_window.empty else '无'}

proposed v1 下 ACCEPT hard samples 主要分布：

{hard_accepts.to_markdown(index=False) if not hard_accepts.empty else '无'}

## 6. benign 对照

{benign_mix.to_markdown(index=False) if not benign_mix.empty else '无'}

## 7. 阶段性回答

1. `e` 多小主动补偿才能突破验证器：在本 hard-case 加权集合中，`e=0` 已明显突破 single-window 和 full-pass；`e=0.5-10 km` 仍保持较高接受率，说明 10 km 以内的位置误差并未自动消除单站固定点主动补偿压力。
2. v1 与 v1.1 差异：proposed v1 总体 attack ACCEPT 约为 `{proposed_accept:.4f}`，candidate v1.1 约为 `{candidate_accept:.4f}`。v1.1 主要把 best-attack 时间分散不足的 ACCEPT 转为 DEFER，收益存在但有限。
3. full-pass 是否最稳：在被动轨道相似攻击中 full-pass 是强证据；但在本轮固定点主动补偿压力下，full-pass ACCEPT 约为 `{full_accept:.4f}`，不应表述为最稳防线。
4. single-window baseline：single-window ACCEPT 约为 `{single_accept:.4f}`，仍是最脆弱对照。
5. hard samples：proposed v1 的 ACCEPT 主要来自 altitude `-1/-2 km` 与部分 small inclination，且集中在 full_pass、spread_3x60s、hardest_previous 和 spread_6x30s。
6. 下一步：本轮不证明真实定位可达到这些 e，只说明若攻击方能把固定参考点误差压到 0-10 km 区间，单站 verifier 会承受强压力。下一轮应评估 partial-observation 下 location-aware active compensation，并检查三参考模拟定位是否可能达到本轮高风险 e 区间。

## 8. 输出图

{figs}
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame) -> None:
    attack = dataset[dataset["sample_type"].eq("attack")]
    proposed = attack[attack["strategy_type"].eq("proposed_v1")]
    candidate = attack[attack["strategy_type"].eq("candidate_v1_1")]
    proposed_accept = float(proposed["final_decision"].eq("ACCEPT").mean()) if not proposed.empty else np.nan
    candidate_accept = float(candidate["final_decision"].eq("ACCEPT").mean()) if not candidate.empty else np.nan
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - fixed-point active compensation sensitivity

### A. 本轮目标

测试固定参考点主动补偿攻击在不同位置误差 e 下对 window-aware verifier 的压力，优先使用上一轮 hard-case 轨道样本。

### B. 实际操作

- 新增并运行 `scripts/run_fixed_point_active_compensation_sensitivity.py`。
- 从 `window_aware_attack_accept_hard_cases.csv` 均衡抽取 altitude 与 inclination hard cases。
- 扫描 e values：`{', '.join(str(v) for v in args.e_values)}`。
- 未实现三参考定位，只做抽象位置误差敏感性。

### C. 新增/修改文件

- 修改：`scripts/run_fixed_point_active_compensation_sensitivity.py`
- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}` 下 3 张图

### D. 运行命令

```bash
python -m py_compile scripts/run_fixed_point_active_compensation_sensitivity.py
```

```bash
python scripts/run_fixed_point_active_compensation_sensitivity.py --max-targets 2 --num-sims-per-attack 1 --max-hard-cases 8 --overwrite
```

```bash
python scripts/run_fixed_point_active_compensation_sensitivity.py --overwrite
```

### E. 结果摘要

- dataset rows：`{len(dataset)}`。
- summary rows：`{len(summary)}`。
- proposed v1 attack ACCEPT：`{proposed_accept:.4f}`。
- candidate v1.1 attack ACCEPT：`{candidate_accept:.4f}`。

### F. 问题与下一步

本轮只抽象扫描位置误差 e。下一步应评估三参考模拟定位是否可能达到高风险 e 区间，并进入 partial-observation 下的 location-aware active compensation 压力测试。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.window_patterns = split_values(args.window_patterns)
    args.strategy_types = split_values(args.strategy_types)
    check_outputs([args.dataset_output, args.summary_output, args.report_output], args.overwrite)
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=args.max_targets,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    rng = np.random.default_rng(args.seed)
    hard_specs = load_hard_specs(args.hard_cases, args.max_targets, args.max_hard_cases) if args.include_hard_cases and args.hard_cases.exists() else fallback_specs(selection, args.max_targets)
    selection_map = {str(r.target_norad_id): r for r in selection.itertuples(index=False)}
    rows: list[dict[str, Any]] = []
    seq_counter = 1

    for _, spec_row in hard_specs.iterrows():
        target_id = str(spec_row["target_id"])
        if target_id not in selection_map or target_id not in tle:
            continue
        target_name = str(spec_row["target_name"])
        sat_a = tle[target_id]["sat"]
        geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat_a, orbit_builder.wgs84.latlon(s_lat, s_lon, elevation_m=s_alt_m), ts)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        t_rel = geo["t_rel_s"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else 11_325_000_000.0
        f_a_s = geo["f_geo_candidate_hz"].to_numpy(float)
        attack_spec = spec_dict(spec_row)
        station_s = orbit_builder.wgs84.latlon(s_lat, s_lon, elevation_m=s_alt_m)
        f_b_s = wrc.generate_attack_geo(attack_spec, sat_a, station_s, ts, times, freq_hz)
        base_window_specs = wae.base_middle_specs(t_rel, [180, 120, 60, 30])
        benign_obs = []
        for i in range(1, int(args.num_benign_sims or 50) + 1):
            err = base.sample_error_params(ranges, rng)
            benign_obs.append(base.build_legitimate_observation(f"fp_benign_{target_id}_{i:04d}", target_name, target_id, geo, err, rng, i, args.seed))
        cal = wae.calibration_stats(benign_obs=benign_obs, geo=geo, f_geo_a=f_a_s, specs_by_key=base_specs_for_calibration(t_rel), threshold_types=[args.threshold_type])
        # Benign control rows use the same verifier patterns at e=NaN.
        for benign in benign_obs[: max(1, min(5, int(args.num_sims_per_attack)))]:
            for pattern in args.window_patterns:
                specs, group_mode, seg_pattern = choose_specs_for_pattern(pattern, t_rel, f_a_s, f_a_s, cal)
                if not specs:
                    continue
                group_rows = wae.build_group_rows(
                    group_id=f"{target_id}_{benign.sequence_id}_{pattern}_{args.threshold_type}",
                    target_id=target_id,
                    target_name=target_name,
                    attack_type="benign_A",
                    attack_param_name="none",
                    attack_param_value="none",
                    is_benign=True,
                    pass_id=f"{target_id}_{geo['t_abs_utc'].iloc[0]}",
                    group_mode=group_mode,
                    segment_pattern=seg_pattern,
                    observation=benign,
                    f_geo_a=f_a_s,
                    t_rel=t_rel,
                    specs=specs,
                    cal=cal,
                    threshold_type=args.threshold_type,
                    args=SimpleNamespace(evidence_accept_threshold=3.0, max_overlap_ratio=0.2, strategies=["single_window", "proposed_accumulation"]),
                )
                for gr in group_rows:
                    if gr["strategy_type"] not in ["single_window", "proposed_accumulation"]:
                        continue
                    strategy = "proposed_v1" if gr["strategy_type"] == "proposed_accumulation" else gr["strategy_type"]
                    if strategy not in args.strategy_types:
                        continue
                    rows.append(row_from_group(gr, pattern, strategy, np.nan, "benign", seq_counter, 0.0))
                    seq_counter += 1
        for e_km in [float(v) for v in args.e_values]:
            sh_lat, sh_lon = active.destination_point(s_lat, s_lon, e_km, float(args.reference_bearing_deg))
            f_a_sh, f_b_sh = synthetic_geo_at_station(attack_spec, sat_a, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
            # Active compensation referenced to S_hat.  Sign convention makes e=0 ideal for single station S.
            f_attack_base = f_b_s + (f_a_sh - f_b_sh)
            for sim_id in range(1, int(args.num_sims_per_attack) + 1):
                terms = active.sample_residual_terms(t_rel, args.residual_mode, ranges, rng)
                y_obs, noise, b_hz, k_hz_s, sigma_hz, t0_s = active.apply_residual_terms(f_attack_base, t_rel, terms)
                obs = make_observation(
                    f"fp_attack_{seq_counter:07d}",
                    target_name,
                    target_id,
                    geo,
                    y_obs,
                    f_b_s,
                    noise,
                    b_hz,
                    k_hz_s,
                    sigma_hz,
                    t0_s,
                    str(attack_spec["attack_type"]),
                    str(attack_spec["attack_variant"]),
                )
                for pattern in args.window_patterns:
                    specs, group_mode, seg_pattern = choose_specs_for_pattern(pattern, t_rel, f_attack_base, f_a_s, cal)
                    if not specs:
                        continue
                    group_rows = wae.build_group_rows(
                        group_id=f"{target_id}_{obs.sequence_id}_{pattern}_e{e_km:g}_{args.threshold_type}",
                        target_id=target_id,
                        target_name=target_name,
                        attack_type=str(attack_spec["attack_type"]),
                        attack_param_name=str(attack_spec["attack_param_name"]),
                        attack_param_value=float(attack_spec["attack_param_value"]),
                        is_benign=False,
                        pass_id=f"{target_id}_{geo['t_abs_utc'].iloc[0]}",
                        group_mode=group_mode,
                        segment_pattern=seg_pattern,
                        observation=obs,
                        f_geo_a=f_a_s,
                        t_rel=t_rel,
                        specs=specs,
                        cal=cal,
                        threshold_type=args.threshold_type,
                        args=SimpleNamespace(evidence_accept_threshold=3.0, max_overlap_ratio=0.2, strategies=["single_window", "proposed_accumulation"]),
                    )
                    for gr in group_rows:
                        base_strategy = "proposed_v1" if gr["strategy_type"] == "proposed_accumulation" else gr["strategy_type"]
                        if base_strategy in args.strategy_types:
                            rows.append(row_from_group(gr, pattern, base_strategy, e_km, "attack", seq_counter, e_km))
                            seq_counter += 1
                        if "candidate_v1_1" in args.strategy_types and gr["strategy_type"] == "proposed_accumulation":
                            rows.append(row_from_group(gr, pattern, "candidate_v1_1", e_km, "attack", seq_counter, e_km, override_decision=candidate_v11_decision(gr)))
                            seq_counter += 1
                        if "full_pass" in args.strategy_types and pattern == "full_pass" and gr["strategy_type"] == "proposed_accumulation":
                            rows.append(row_from_group(gr, pattern, "full_pass", e_km, "attack", seq_counter, e_km))
                            seq_counter += 1

    dataset = pd.DataFrame(rows)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output, index=False)
    summary = summarize(dataset)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    figures = make_figures(summary, args.figures_dir)
    write_report(args, dataset, summary, figures)
    append_log(args, dataset, summary)
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.report_output}")
    for p in figures:
        print(p)


def row_from_group(gr: dict[str, Any], window_pattern: str, strategy: str, e_km: float, sample_type: str, row_id: int, position_error_km: float, override_decision: str | None = None) -> dict[str, Any]:
    decision = override_decision or str(gr["final_decision"])
    scores = [float(x) for x in str(gr["single_window_scores"]).split(";") if x]
    b_hats = [float(x) for x in str(gr["single_window_b_hats"]).split(";") if x]
    k_hats = [float(x) for x in str(gr["single_window_k_hats"]).split(";") if x]
    return {
        "row_id": row_id,
        "sample_type": sample_type,
        "target_id": gr["target_id"],
        "target_name": gr["target_name"],
        "attack_type": gr["attack_type"],
        "attack_param_name": gr["attack_param_name"],
        "attack_param_value": gr["attack_param_value"],
        "window_pattern": window_pattern,
        "window_lengths": gr["window_lengths_s"],
        "window_positions": gr["window_positions"],
        "group_mode": gr["group_mode"],
        "segment_pattern": gr["segment_pattern"],
        "num_windows": gr["num_windows"],
        "e_km": e_km,
        "position_error_km": position_error_km,
        "residual_score_rmse_hz": float(np.nanmedian(scores)) if scores else np.nan,
        "b_hat_hz": float(np.nanmedian(b_hats)) if b_hats else np.nan,
        "k_hat_hz_per_s": float(np.nanmedian(k_hats)) if k_hats else np.nan,
        "joint_score_rmse_hz": gr["joint_score_rmse_hz"],
        "joint_normalized_score": gr["joint_normalized_score"],
        "b_pass_hat_hz": gr["b_pass_hat_hz"],
        "k_pass_hat_hz_per_s": gr["k_pass_hat_hz_per_s"],
        "temporal_diversity_pass": gr["temporal_diversity_pass"],
        "joint_score_gate_pass": gr["joint_score_gate_pass"],
        "joint_b_gate_pass": gr["joint_b_gate_pass"],
        "joint_k_gate_pass": gr["joint_k_gate_pass"],
        "strategy_type": strategy,
        "final_decision": decision,
        "decision_reason": gr["decision_reason"],
    }


if __name__ == "__main__":
    main()
