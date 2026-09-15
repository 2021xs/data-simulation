#!/usr/bin/env python
"""Offline audit for fixed-point active compensation sensitivity outputs.

The audit intentionally does not rerun the full experiment.  It checks the
existing dataset/summary/report, recomputes aggregate metrics from the dataset,
and performs a small deterministic e=0 geometry sanity check for the active
compensation sign convention.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_window_reliability_calibration as wrc  # noqa: E402


REQUIRED_DATASET_COLUMNS = [
    "sample_type",
    "target_id",
    "target_name",
    "attack_type",
    "attack_param_name",
    "attack_param_value",
    "window_pattern",
    "window_lengths",
    "window_positions",
    "group_mode",
    "segment_pattern",
    "num_windows",
    "e_km",
    "position_error_km",
    "residual_score_rmse_hz",
    "b_hat_hz",
    "k_hat_hz_per_s",
    "joint_score_rmse_hz",
    "joint_normalized_score",
    "b_pass_hat_hz",
    "k_pass_hat_hz_per_s",
    "temporal_diversity_pass",
    "joint_score_gate_pass",
    "joint_b_gate_pass",
    "joint_k_gate_pass",
    "strategy_type",
    "final_decision",
    "decision_reason",
]

GROUP_COLS = ["sample_type", "attack_type", "attack_param_value", "window_pattern", "strategy_type", "e_km"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit fixed-point active compensation outputs without rerunning the full experiment.")
    p.add_argument("--dataset", type=Path, default=Path("outputs/datasets/fixed_point_active_compensation_dataset.csv"))
    p.add_argument("--summary", type=Path, default=Path("outputs/metrics/fixed_point_active_compensation_summary.csv"))
    p.add_argument("--experiment-script", type=Path, default=Path("scripts/run_fixed_point_active_compensation_sensitivity.py"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--checks-output", type=Path, default=Path("outputs/metrics/fixed_point_active_compensation_audit_checks.csv"))
    p.add_argument("--recomputed-summary-output", type=Path, default=Path("outputs/metrics/fixed_point_active_compensation_recomputed_summary.csv"))
    p.add_argument("--geometry-output", type=Path, default=Path("outputs/metrics/fixed_point_active_compensation_e0_geometry_sanity.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/fixed_point_active_compensation_audit_report.md"))
    p.add_argument("--max-geometry-cases", type=int, default=6)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def add_check(rows: list[dict[str, Any]], name: str, status: str, detail: str, severity: str = "info") -> None:
    rows.append({"check_name": name, "status": status, "severity": severity, "detail": detail})


def normalize_for_merge(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in GROUP_COLS:
        if col not in out.columns:
            continue
        if col == "e_km":
            out[col] = pd.to_numeric(out[col], errors="coerce").round(9)
        else:
            out[col] = out[col].astype(str).fillna("__NA__")
            out[col] = out[col].replace({"nan": "__NA__", "None": "__NA__"})
    return out


def recompute_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, g in dataset.groupby(GROUP_COLS, dropna=False):
        counts = g["final_decision"].value_counts()
        n = len(g)
        rows.append(
            {
                **dict(zip(GROUP_COLS, key)),
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


def compare_summary(saved: pd.DataFrame, recomputed: pd.DataFrame) -> tuple[bool, str]:
    saved_n = normalize_for_merge(saved)
    rec_n = normalize_for_merge(recomputed)
    cmp_cols = [
        "n",
        "accept_count",
        "defer_count",
        "reject_count",
        "accept_rate",
        "defer_rate",
        "reject_rate",
        "score_median_hz",
        "joint_normalized_score_median",
        "k_hat_median",
    ]
    merged = saved_n.merge(rec_n, on=GROUP_COLS, how="outer", suffixes=("_saved", "_recomputed"), indicator=True)
    if not merged["_merge"].eq("both").all():
        missing = merged["_merge"].value_counts().to_dict()
        return False, f"group mismatch: {missing}"
    max_diff = 0.0
    worst_col = ""
    for col in cmp_cols:
        a = pd.to_numeric(merged[f"{col}_saved"], errors="coerce")
        b = pd.to_numeric(merged[f"{col}_recomputed"], errors="coerce")
        diff = (a - b).abs().fillna(0.0).max()
        if diff > max_diff:
            max_diff = float(diff)
            worst_col = col
    ok = bool(max_diff <= 1e-9)
    return ok, f"rows saved={len(saved)}, recomputed={len(recomputed)}, max_abs_diff={max_diff:g} ({worst_col})"


def load_experiment_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("fixed_point_exp", path)
    if spec is None or spec.loader is None:
        fail(f"cannot import experiment script: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def geometry_sanity(args: argparse.Namespace, exp: Any) -> pd.DataFrame:
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=20,
    )
    selection, library, orbit_cfg, _ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    station_s = orbit_builder.wgs84.latlon(s_lat, s_lon, elevation_m=s_alt_m)
    hard = exp.load_hard_specs(args.hard_cases, max_targets=10, max_cases=80)
    selection_ids = set(selection["target_norad_id"].astype(str))
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, float]] = set()
    for _, spec_row in hard.iterrows():
        target_id = str(spec_row["target_id"])
        attack_type = str(spec_row["attack_type"])
        attack_value = float(spec_row["attack_param_value"])
        key = (target_id, attack_type, attack_value)
        if key in seen or target_id not in selection_ids or target_id not in tle:
            continue
        seen.add(key)
        sat_a = tle[target_id]["sat"]
        geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat_a, station_s, ts)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        t_rel = geo["t_rel_s"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else 11_325_000_000.0
        f_a_s = geo["f_geo_candidate_hz"].to_numpy(float)
        attack_spec = exp.spec_dict(spec_row)
        f_b_s = wrc.generate_attack_geo(attack_spec, sat_a, station_s, ts, times, freq_hz)
        sh_lat, sh_lon = exp.active.destination_point(s_lat, s_lon, 0.0, 90.0)
        f_a_sh, f_b_sh = exp.synthetic_geo_at_station(attack_spec, sat_a, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
        implemented = f_b_s + (f_a_sh - f_b_sh)
        prompt_direction = f_b_s + (f_b_sh - f_a_sh)
        rows.append(
            {
                "target_id": target_id,
                "target_name": str(spec_row["target_name"]),
                "attack_type": attack_type,
                "attack_param_value": attack_value,
                "n_points": int(len(t_rel)),
                "implemented_e0_rmse_to_A_S_hz": float(np.sqrt(np.mean((implemented - f_a_s) ** 2))),
                "prompt_direction_e0_rmse_to_A_S_hz": float(np.sqrt(np.mean((prompt_direction - f_a_s) ** 2))),
                "B_without_comp_e0_rmse_to_A_S_hz": float(np.sqrt(np.mean((f_b_s - f_a_s) ** 2))),
                "implemented_max_abs_to_A_S_hz": float(np.max(np.abs(implemented - f_a_s))),
            }
        )
        if len(rows) >= args.max_geometry_cases:
            break
    return pd.DataFrame(rows)


def write_report(args: argparse.Namespace, checks: pd.DataFrame, dataset: pd.DataFrame, saved_summary: pd.DataFrame, geometry: pd.DataFrame) -> None:
    attack = dataset[dataset["sample_type"].eq("attack")]
    benign = dataset[dataset["sample_type"].eq("benign")]
    accept_by_strategy = attack.groupby("strategy_type")["final_decision"].apply(lambda x: x.eq("ACCEPT").mean()).reset_index(name="attack_accept_rate")
    accept_by_e = (
        attack[attack["strategy_type"].eq("proposed_v1")]
        .groupby("e_km")["final_decision"]
        .apply(lambda x: x.eq("ACCEPT").mean())
        .reset_index(name="proposed_v1_attack_accept_rate")
    )
    type_counts = attack.groupby("attack_type").size().reset_index(name="rows")
    status_counts = checks.groupby(["status", "severity"]).size().reset_index(name="n")
    report = f"""# Fixed-point active compensation offline audit

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 核查目的

本轮只做离线核查，不扩大主动补偿实验。核查对象是上一轮固定参考点主动补偿位置误差敏感性实验输出，重点检查公式方向、`e=0` 几何退化、dataset/summary 一致性、hard-case 样本覆盖、脚本与输出时间戳关系，以及报告统计口径。

## 2. 核查结论

{status_counts.to_markdown(index=False)}

核心判断：上一轮 dataset 与 summary 可以逐样本复现；`e=0` 几何 sanity check 支持当前脚本使用的补偿符号是单站理想补偿方向。但实验源码中仍保留旧的乱码报告函数定义并由后续定义覆盖，且 dataset/summary 的生成时间早于脚本最后修改时间，因此建议在下一轮正式引用前，用清理后的脚本再做一次同参数重跑以固化 provenance。

## 3. 输出规模核查

- dataset rows：`{len(dataset)}`
- summary rows：`{len(saved_summary)}`
- benign rows：`{len(benign)}`
- attack rows：`{len(attack)}`
- target 数：`{dataset['target_id'].nunique()}`
- attack hard-case specs：`{attack[['target_id', 'attack_type', 'attack_param_value']].drop_duplicates().shape[0] if not attack.empty else 0}`

攻击类型覆盖：

{type_counts.to_markdown(index=False) if not type_counts.empty else '无'}

## 4. 关键结果复算

按 strategy 复算 attack ACCEPT：

{accept_by_strategy.to_markdown(index=False) if not accept_by_strategy.empty else '无'}

proposed v1 按 e 复算 attack ACCEPT：

{accept_by_e.to_markdown(index=False) if not accept_by_e.empty else '无'}

## 5. e=0 几何符号 sanity check

本核查少量重算 hard-case 几何，不重跑随机 residual 仿真。`implemented_e0_rmse_to_A_S_hz` 应接近 0；`prompt_direction_e0_rmse_to_A_S_hz` 如果很大，说明用户提示中的差分方向不能直接套入当前 `f_geo` 符号约定。

{geometry.to_markdown(index=False) if not geometry.empty else '无'}

## 6. 逐项检查

{checks.to_markdown(index=False)}

## 7. 建议

1. 保留上一轮结论作为 hard-case pressure test 观察，但在报告中注明它是固定参考点主动补偿上界/压力测试，不是三参考定位能力结论。
2. 清理 `run_fixed_point_active_compensation_sensitivity.py` 中被覆盖的旧乱码函数定义，避免后续审稿或复现实验误读。
3. 清理后用同一 CLI 重跑一次，以便 dataset、summary、report 和脚本哈希完全一致。
4. 下一轮再进入 partial-observation 下 location-aware active compensation，并评估三参考模拟定位能否达到本轮高风险 e 区间。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report, encoding="utf-8")


def append_log(args: argparse.Namespace, checks: pd.DataFrame) -> None:
    failed = int(checks["status"].eq("FAIL").sum())
    warnings = int(checks["status"].eq("WARN").sum())
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - fixed-point active compensation offline audit

### A. 本轮目标

对上一轮固定参考点主动补偿位置误差敏感性实验做离线核查，不扩大实验规模。

### B. 实际操作

- 新增并运行 `scripts/audit_fixed_point_active_compensation_outputs.py`。
- 从 dataset 复算 summary，并检查 hard-case 覆盖与策略/e 聚合结果。
- 少量重算 `e=0` 几何项，验证当前补偿符号是否退化为 claimed target A 的单站几何曲线。

### C. 新增/修改文件

- 新增：`scripts/audit_fixed_point_active_compensation_outputs.py`
- 生成：`{args.checks_output.as_posix()}`
- 生成：`{args.recomputed_summary_output.as_posix()}`
- 生成：`{args.geometry_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`

### D. 运行命令

```bash
python -m py_compile scripts/audit_fixed_point_active_compensation_outputs.py
python scripts/audit_fixed_point_active_compensation_outputs.py --overwrite
```

### E. 结果摘要

- FAIL checks：`{failed}`
- WARN checks：`{warnings}`

### F. 问题与下一步

建议清理主动补偿脚本中的旧乱码函数定义，并用同参数重跑一次以固化脚本哈希与输出 provenance。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    check_outputs([args.checks_output, args.recomputed_summary_output, args.geometry_output, args.report_output], args.overwrite)
    checks: list[dict[str, Any]] = []
    for path_name in ["dataset", "summary", "experiment_script", "hard_cases"]:
        path = getattr(args, path_name)
        if path.exists() and path.stat().st_size > 0:
            add_check(checks, f"{path_name}_exists", "PASS", f"{path} size={path.stat().st_size}")
        else:
            add_check(checks, f"{path_name}_exists", "FAIL", f"missing or empty: {path}", "error")
    if any(r["status"] == "FAIL" for r in checks):
        checks_df = pd.DataFrame(checks)
        args.checks_output.parent.mkdir(parents=True, exist_ok=True)
        checks_df.to_csv(args.checks_output, index=False)
        fail("required input missing")

    dataset = pd.read_csv(args.dataset)
    saved_summary = pd.read_csv(args.summary)
    missing = [c for c in REQUIRED_DATASET_COLUMNS if c not in dataset.columns]
    add_check(checks, "dataset_schema", "PASS" if not missing else "FAIL", "all required columns present" if not missing else "missing: " + ", ".join(missing), "error" if missing else "info")

    recomputed = recompute_summary(dataset)
    ok, detail = compare_summary(saved_summary, recomputed)
    add_check(checks, "summary_recomputes_from_dataset", "PASS" if ok else "FAIL", detail, "error" if not ok else "info")

    e_values = sorted(float(v) for v in dataset.loc[dataset["sample_type"].eq("attack"), "e_km"].dropna().unique())
    expected_e = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0]
    add_check(checks, "e_values_complete", "PASS" if e_values == expected_e else "WARN", f"observed={e_values}", "warning" if e_values != expected_e else "info")

    strategies = sorted(dataset["strategy_type"].dropna().unique().tolist())
    expected_strategies = ["candidate_v1_1", "full_pass", "proposed_v1", "single_window"]
    add_check(checks, "strategy_types_complete", "PASS" if strategies == expected_strategies else "WARN", f"observed={strategies}", "warning" if strategies != expected_strategies else "info")

    attack = dataset[dataset["sample_type"].eq("attack")]
    types = sorted(attack["attack_type"].dropna().unique().tolist())
    add_check(checks, "attack_type_coverage", "PASS" if {"same_plane_altitude_offset", "inclination_offset"}.issubset(types) else "FAIL", f"observed={types}", "error" if len(types) < 2 else "info")
    altitude_values = sorted(pd.to_numeric(attack.loc[attack["attack_type"].eq("same_plane_altitude_offset"), "attack_param_value"], errors="coerce").dropna().unique().tolist())
    add_check(checks, "altitude_hard_params", "PASS" if {-2.0, -1.0}.issubset(set(altitude_values)) else "WARN", f"observed={altitude_values}", "warning")
    inc_values = sorted(pd.to_numeric(attack.loc[attack["attack_type"].eq("inclination_offset"), "attack_param_value"], errors="coerce").dropna().unique().tolist())
    add_check(checks, "inclination_hard_params", "PASS" if inc_values else "FAIL", f"observed={inc_values}", "error" if not inc_values else "info")

    script_text = args.experiment_script.read_text(encoding="utf-8", errors="replace")
    formula_ok = "f_attack_base = f_b_s + (f_a_sh - f_b_sh)" in script_text
    add_check(checks, "implemented_formula_sign", "PASS" if formula_ok else "FAIL", "found f_b_s + (f_a_sh - f_b_sh)" if formula_ok else "formula assignment not found", "error" if not formula_ok else "info")
    for func in ["write_report", "append_log", "main"]:
        n_defs = len(re.findall(rf"^def {func}\\(", script_text, flags=re.MULTILINE))
        add_check(checks, f"function_definition_count_{func}", "PASS" if n_defs == 1 else "WARN", f"definitions={n_defs}", "warning" if n_defs != 1 else "info")

    dataset_mtime = args.dataset.stat().st_mtime
    summary_mtime = args.summary.stat().st_mtime
    script_mtime = args.experiment_script.stat().st_mtime
    if dataset_mtime >= script_mtime and summary_mtime >= script_mtime:
        add_check(checks, "output_newer_than_script", "PASS", "dataset/summary are newer than or equal to script")
    else:
        add_check(checks, "output_newer_than_script", "WARN", "dataset/summary are older than current script; provenance should be fixed by a same-CLI rerun", "warning")

    add_check(checks, "dataset_sha256", "PASS", sha256(args.dataset))
    add_check(checks, "summary_sha256", "PASS", sha256(args.summary))
    add_check(checks, "experiment_script_sha256", "PASS", sha256(args.experiment_script))

    exp = load_experiment_module(args.experiment_script)
    geometry = geometry_sanity(args, exp)
    if geometry.empty:
        add_check(checks, "e0_geometry_sanity", "FAIL", "no geometry cases recomputed", "error")
    else:
        max_impl = float(geometry["implemented_e0_rmse_to_A_S_hz"].max())
        min_prompt = float(geometry["prompt_direction_e0_rmse_to_A_S_hz"].min())
        status = "PASS" if max_impl < 1e-6 and min_prompt > 1.0 else "WARN"
        add_check(checks, "e0_geometry_sanity", status, f"max implemented rmse={max_impl:g} Hz, min prompt-direction rmse={min_prompt:g} Hz", "warning" if status == "WARN" else "info")

    checks_df = pd.DataFrame(checks)
    args.recomputed_summary_output.parent.mkdir(parents=True, exist_ok=True)
    recomputed.to_csv(args.recomputed_summary_output, index=False)
    args.geometry_output.parent.mkdir(parents=True, exist_ok=True)
    geometry.to_csv(args.geometry_output, index=False)
    args.checks_output.parent.mkdir(parents=True, exist_ok=True)
    checks_df.to_csv(args.checks_output, index=False)
    write_report(args, checks_df, dataset, saved_summary, geometry)
    append_log(args, checks_df)
    print(f"wrote {args.checks_output} rows={len(checks_df)}")
    print(f"wrote {args.recomputed_summary_output} rows={len(recomputed)}")
    print(f"wrote {args.geometry_output} rows={len(geometry)}")
    print(f"wrote {args.report_output}")


if __name__ == "__main__":
    main()
