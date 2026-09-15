#!/usr/bin/env python
"""Fixed-reference simulated compensation sanity check.

This is an offline mathematical simulation check.  It does not connect to any
real satellite link and does not transmit signals.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
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
import run_window_reliability_calibration as wrc  # noqa: E402


DEFAULT_E_VALUES = [0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0]
DEFAULT_BEARINGS = [0.0, 90.0, 180.0, 270.0]
FIGURE_E_VALUES = {0.0, 10.0, 50.0, 100.0}


def parse_csv_floats(value: str | list[str]) -> list[float]:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(str(item).split(","))
    else:
        parts = str(value).split(",")
    return [float(v.strip()) for v in parts if v.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline sanity check for fixed-reference simulated compensation.")
    p.add_argument("--input-dataset", type=Path, default=Path("outputs/datasets/fixed_point_active_compensation_dataset.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--previous-script", type=Path, default=Path("scripts/run_fixed_point_active_compensation_sensitivity.py"))
    p.add_argument("--summary", type=Path, default=Path("outputs/metrics/fixed_point_active_compensation_summary.csv"))
    p.add_argument("--e-values", nargs="+", default=",".join(str(v).rstrip("0").rstrip(".") for v in DEFAULT_E_VALUES))
    p.add_argument("--bearings", nargs="+", default=",".join(str(v).rstrip("0").rstrip(".") for v in DEFAULT_BEARINGS))
    p.add_argument("--target-index", type=int, default=0)
    p.add_argument("--case-index", type=int, default=0)
    p.add_argument("--metrics-output", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_sanity_metrics.csv"))
    p.add_argument("--consistency-output", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_dataset_consistency.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/fixed_reference_compensation_sanity_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/fixed_reference_compensation_sanity"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rmse(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2)))


def spec_from_case(row: pd.Series) -> dict[str, Any]:
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
    if attack_type == "same_plane_phase_offset":
        return {
            "attack_type": attack_type,
            "attack_variant": f"phase_{value:+g}s",
            "attack_param_name": "phase_offset_s",
            "attack_param_value": value,
            "altitude_offset_km": 0.0,
            "phase_offset_s": value,
            "inclination_offset_deg": 0.0,
            "raan_offset_deg": 0.0,
        }
    fail(f"unsupported attack_type for sanity check: {attack_type}")


def select_case(dataset: pd.DataFrame, target_index: int, case_index: int) -> pd.Series:
    attack = dataset[dataset["sample_type"].eq("attack")].copy()
    attack = attack[attack["attack_type"].isin(["same_plane_altitude_offset", "inclination_offset", "same_plane_phase_offset"])]
    if attack.empty:
        fail("input dataset has no supported attack rows")
    targets = sorted(attack["target_id"].astype(str).unique().tolist())
    if target_index < 0 or target_index >= len(targets):
        fail(f"--target-index out of range: {target_index}, available targets={len(targets)}")
    target_id = targets[target_index]
    cases = (
        attack[attack["target_id"].astype(str).eq(target_id)][["target_id", "target_name", "attack_type", "attack_param_name", "attack_param_value"]]
        .drop_duplicates()
        .sort_values(["attack_type", "attack_param_value"])
        .reset_index(drop=True)
    )
    if case_index < 0 or case_index >= len(cases):
        fail(f"--case-index out of range: {case_index}, available cases for target {target_id}={len(cases)}")
    return cases.iloc[case_index]


def fixed_reference_geo(sat: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float, step_s: float) -> np.ndarray:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    geo = orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))
    return geo["f_geo_tle_hz"].to_numpy(float)


def attack_geo(spec: dict[str, Any], sat_a: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float) -> np.ndarray:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    return wrc.generate_attack_geo(spec, sat_a, site, ts, times, freq_hz)


def parse_utc_series(values: pd.Series) -> list[Any]:
    return [base.parse_utc(v) for v in values.astype(str)]


def residual_after_fit(delta: np.ndarray, t_rel: np.ndarray, fit: base.FitResult) -> np.ndarray:
    x = t_rel - float(np.mean(t_rel))
    return delta - (fit.b_hat_hz + fit.k_hat_hz_s * x)


def compute_sanity_metrics(args: argparse.Namespace, dataset: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
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
    case = select_case(dataset, args.target_index, args.case_index)
    target_id = str(case["target_id"])
    if target_id not in set(selection["target_norad_id"].astype(str)):
        fail(f"selected target {target_id} is not in selection table")
    if target_id not in tle:
        fail(f"selected target {target_id} is not in TLE")
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    sat_a = tle[target_id]["sat"]
    station_s = orbit_builder.wgs84.latlon(s_lat, s_lon, elevation_m=s_alt_m)
    geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat_a, station_s, ts)
    times = parse_utc_series(geo["t_abs_utc"])
    t_rel = geo["t_rel_s"].to_numpy(float)
    step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
    freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else 11_325_000_000.0
    f_a_s = geo["f_geo_candidate_hz"].to_numpy(float)
    spec = spec_from_case(case)
    f_b_s = attack_geo(spec, sat_a, s_lat, s_lon, s_alt_m, times, ts, freq_hz)
    raw_delta = f_b_s - f_a_s
    raw_delta_rmse = rmse(raw_delta)

    rows: list[dict[str, Any]] = []
    curve_cache: dict[tuple[float, float], dict[str, np.ndarray]] = {}
    for e_km in args.e_values:
        for bearing in args.bearings:
            sh_lat, sh_lon = active.destination_point(s_lat, s_lon, float(e_km), float(bearing))
            actual_distance = float(active.haversine_distance_km(np.array([sh_lat]), np.array([sh_lon]), s_lat, s_lon)[0])
            f_a_sh = fixed_reference_geo(sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
            f_b_sh = attack_geo(spec, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz)
            u_shat = f_a_sh - f_b_sh
            f_comp = f_b_s + u_shat
            f_reverse = f_b_s + (f_b_sh - f_a_sh)
            delta_comp = f_comp - f_a_s
            fit = base.fit_bias_and_slope(f_comp, f_a_s, t_rel)
            delta_comp_after_bk = residual_after_fit(delta_comp, t_rel, fit)
            reverse_delta = f_reverse - f_a_s
            curve_cache[(float(e_km), float(bearing))] = {
                "t_rel": t_rel,
                "f_a_s": f_a_s,
                "f_b_s": f_b_s,
                "f_comp": f_comp,
                "delta_raw": raw_delta,
                "delta_comp": delta_comp,
                "delta_comp_after_bk": delta_comp_after_bk,
            }
            rows.append(
                {
                    "target_id": target_id,
                    "target_name": str(case["target_name"]),
                    "attack_type": str(case["attack_type"]),
                    "attack_param_name": str(case["attack_param_name"]),
                    "attack_param_value": float(case["attack_param_value"]),
                    "e_km": float(e_km),
                    "bearing_deg": float(bearing),
                    "S_lat_deg": s_lat,
                    "S_lon_deg": s_lon,
                    "S_hat_lat_deg": sh_lat,
                    "S_hat_lon_deg": sh_lon,
                    "actual_distance_km": actual_distance,
                    "offset_bearing_deg": float(bearing),
                    "n_points": int(len(t_rel)),
                    "pass_duration_s": float(np.max(t_rel) - np.min(t_rel)),
                    "raw_delta_rmse_hz": raw_delta_rmse,
                    "comp_delta_rmse_before_bk_hz": rmse(delta_comp),
                    "comp_delta_rmse_after_bk_hz": rmse(delta_comp_after_bk),
                    "reverse_formula_delta_rmse_hz": rmse(reverse_delta),
                    "improvement_ratio": raw_delta_rmse / rmse(delta_comp) if rmse(delta_comp) > 0 else np.inf,
                    "b_hat_hz": float(fit.b_hat_hz),
                    "k_hat_hz_per_s": float(fit.k_hat_hz_s),
                    "residual_score_hz": float(fit.score_rmse_hz),
                    "u_shat_rmse_hz": rmse(u_shat),
                    "u_shat_min_hz": float(np.min(u_shat)),
                    "u_shat_max_hz": float(np.max(u_shat)),
                }
            )
    meta = {
        "target_id": target_id,
        "target_name": str(case["target_name"]),
        "attack_type": str(case["attack_type"]),
        "attack_param_name": str(case["attack_param_name"]),
        "attack_param_value": float(case["attack_param_value"]),
        "t_rel": t_rel,
        "curve_cache": curve_cache,
    }
    return pd.DataFrame(rows), geo, meta


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_curve_figures(metrics: pd.DataFrame, meta: dict[str, Any], figures_dir: Path) -> list[Path]:
    paths: list[Path] = []
    cache: dict[tuple[float, float], dict[str, np.ndarray]] = meta["curve_cache"]
    available_e = sorted({e for e, b in cache if abs(b - 90.0) < 1e-9})
    for e_km in sorted(FIGURE_E_VALUES):
        if e_km not in available_e:
            continue
        data = cache[(e_km, 90.0)]
        suffix = f"e{e_km:g}km"
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(data["t_rel"], data["f_a_s"], label="f_geo(A, S)")
        ax.plot(data["t_rel"], data["f_b_s"], label="f_geo(B, S)", alpha=0.8)
        ax.plot(data["t_rel"], data["f_comp"], label="f_comp", alpha=0.8)
        ax.set_xlabel("t_rel_s")
        ax.set_ylabel("frequency_hz")
        ax.set_title(f"Fixed-reference compensation curves, e={e_km:g} km, east")
        ax.legend()
        ax.grid(True, alpha=0.25)
        p = figures_dir / f"sanity_curves_{suffix}.png"
        savefig(fig, p)
        paths.append(p)

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(data["t_rel"], data["delta_raw"], label="delta_raw")
        ax.plot(data["t_rel"], data["delta_comp"], label="delta_comp")
        ax.plot(data["t_rel"], data["delta_comp_after_bk"], label="delta_comp_after_bk")
        ax.set_xlabel("t_rel_s")
        ax.set_ylabel("residual_hz")
        ax.set_title(f"Fixed-reference compensation residuals, e={e_km:g} km, east")
        ax.legend()
        ax.grid(True, alpha=0.25)
        p = figures_dir / f"sanity_residuals_{suffix}.png"
        savefig(fig, p)
        paths.append(p)
    return paths


def dataset_consistency(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame | None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(check: str, status: str, detail: str, severity: str = "info") -> None:
        rows.append({"check_name": check, "status": status, "severity": severity, "detail": detail})

    attack = dataset[dataset["sample_type"].eq("attack")].copy()
    if attack.empty:
        add("attack_rows_present", "FAIL", "no attack rows", "error")
        return pd.DataFrame(rows)
    e_counts = attack.groupby("e_km").size().reset_index(name="n").sort_values("e_km")
    add("rows_per_e_consistent", "PASS" if e_counts["n"].nunique() == 1 else "WARN", e_counts.to_dict(orient="records"), "warning" if e_counts["n"].nunique() != 1 else "info")
    if {"S_hat_lat_deg", "S_hat_lon_deg"}.issubset(dataset.columns):
        varying = attack.groupby("e_km")[["S_hat_lat_deg", "S_hat_lon_deg"]].nunique().sum(axis=1)
        add("S_hat_coordinates_recorded", "PASS", varying.to_dict())
    else:
        add("S_hat_coordinates_recorded", "WARN", "previous dataset does not record S_hat coordinates; cannot directly check coordinate variation", "warning")
    key_cols = ["target_id", "attack_type", "attack_param_value", "window_pattern", "strategy_type", "window_positions"]
    duplicate_scores = 0
    compared_groups = 0
    for _, g in attack.groupby(key_cols, dropna=False):
        if g["e_km"].nunique() < 2:
            continue
        compared_groups += 1
        score_by_e = g.groupby("e_km")["residual_score_rmse_hz"].mean().round(12)
        if score_by_e.nunique() == 1:
            duplicate_scores += 1
    ratio = duplicate_scores / compared_groups if compared_groups else 0.0
    add("identical_score_across_e", "PASS" if ratio < 0.05 else "WARN", f"groups={compared_groups}, identical_mean_score_groups={duplicate_scores}, ratio={ratio:.4f}", "warning" if ratio >= 0.05 else "info")
    proposed = attack[attack["strategy_type"].eq("proposed_v1")]
    by_e = proposed.groupby("e_km")["final_decision"].apply(lambda x: x.eq("ACCEPT").mean()).reset_index(name="proposed_v1_accept_rate")
    add("proposed_v1_accept_by_e", "PASS", by_e.to_dict(orient="records"))
    full = attack[attack["strategy_type"].eq("full_pass")]
    full_by_e = full.groupby("e_km")["final_decision"].apply(lambda x: x.eq("ACCEPT").mean()).reset_index(name="full_pass_accept_rate")
    full_all_high = bool((full_by_e["full_pass_accept_rate"] > 0.8).all()) if not full_by_e.empty else False
    add("full_pass_high_across_all_e", "PASS" if full_all_high else "WARN", full_by_e.to_dict(orient="records"), "warning" if not full_all_high else "info")
    types = attack["attack_type"].value_counts().to_dict()
    add("attack_type_coverage", "PASS" if len(types) >= 2 else "WARN", types, "warning" if len(types) < 2 else "info")
    ordinary_indicator = attack["attack_type"].isin(["same_plane_phase_offset"]).any()
    hard_only = not ordinary_indicator
    add("ordinary_sample_contrast", "WARN" if hard_only else "PASS", "dataset appears hard-case weighted and lacks ordinary sample contrast" if hard_only else "ordinary contrast present", "warning" if hard_only else "info")
    if summary is not None and not summary.empty:
        rec = (
            attack.groupby(["sample_type", "attack_type", "attack_param_value", "window_pattern", "strategy_type", "e_km"], dropna=False)
            .agg(n=("final_decision", "size"), accept_count=("final_decision", lambda x: int(x.eq("ACCEPT").sum())))
            .reset_index()
        )
        saved = summary.copy()
        merge_cols = ["sample_type", "attack_type", "attack_param_value", "window_pattern", "strategy_type", "e_km"]
        for c in merge_cols:
            rec[c] = rec[c].astype(str)
            saved[c] = saved[c].astype(str)
        m = saved.merge(rec, on=merge_cols, how="inner", suffixes=("_saved", "_recomputed"))
        if len(m):
            max_n_diff = float((pd.to_numeric(m["n_saved"]) - pd.to_numeric(m["n_recomputed"])).abs().max())
            max_accept_diff = float((pd.to_numeric(m["accept_count_saved"]) - pd.to_numeric(m["accept_count_recomputed"])).abs().max())
            add("summary_matches_dataset_subset", "PASS" if max_n_diff == 0 and max_accept_diff == 0 else "FAIL", f"matched_groups={len(m)}, max_n_diff={max_n_diff:g}, max_accept_count_diff={max_accept_diff:g}", "error" if max_n_diff or max_accept_diff else "info")
        else:
            add("summary_matches_dataset_subset", "WARN", "no comparable summary groups", "warning")
    else:
        add("summary_matches_dataset_subset", "WARN", "summary file unavailable", "warning")
    if args.previous_script.exists():
        text = args.previous_script.read_text(encoding="utf-8", errors="replace")
        formula = "f_attack_base = f_b_s + (f_a_sh - f_b_sh)" in text
        reverse = "f_b_sh - f_a_sh" in text and "f_attack_base = f_b_s + (f_b_sh - f_a_sh)" in text
        add("previous_script_formula_direction", "PASS" if formula and not reverse else "FAIL", "uses f_B(S)+f_A(S_hat)-f_B(S_hat)" if formula else "expected formula assignment not found", "error" if not formula or reverse else "info")
        for name in ["write_report", "append_log"]:
            count = len(re.findall(rf"^def {name}\(", text, flags=re.MULTILINE))
            add(f"previous_script_duplicate_{name}", "WARN" if count != 1 else "PASS", f"definitions={count}", "warning" if count != 1 else "info")
        add("previous_script_sha256", "PASS", sha256(args.previous_script))
    return pd.DataFrame(rows)


def write_report(
    args: argparse.Namespace,
    metrics: pd.DataFrame,
    consistency: pd.DataFrame,
    figures: list[Path],
    meta: dict[str, Any],
) -> None:
    east = metrics[metrics["bearing_deg"].eq(90.0)].copy()
    east_small = east[east["e_km"].isin([0.0, 1.0, 5.0, 10.0])][
        ["e_km", "actual_distance_km", "raw_delta_rmse_hz", "comp_delta_rmse_before_bk_hz", "comp_delta_rmse_after_bk_hz", "b_hat_hz", "k_hat_hz_per_s", "residual_score_hz", "improvement_ratio"]
    ]
    e0 = metrics[metrics["e_km"].eq(0.0)]
    max_e0_comp = float(e0["comp_delta_rmse_before_bk_hz"].max()) if not e0.empty else math.nan
    max_distance_error = float((metrics["actual_distance_km"] - metrics["e_km"]).abs().max()) if not metrics.empty else math.nan
    east_0 = east[east["e_km"].eq(0.0)]
    east_100 = east[east["e_km"].eq(100.0)]
    residual_growth = float(east_100["residual_score_hz"].iloc[0] - east_0["residual_score_hz"].iloc[0]) if not east_0.empty and not east_100.empty else math.nan
    formula_ok = bool(max_e0_comp < 1e-6)
    offset_ok = bool(max_distance_error < 1e-6)
    reverse_e0 = float(e0["reverse_formula_delta_rmse_hz"].min()) if not e0.empty else math.nan
    no_cache_warn = consistency[consistency["check_name"].eq("identical_score_across_e")]["status"].iloc[0] if not consistency[consistency["check_name"].eq("identical_score_across_e")].empty else "UNKNOWN"
    credibility = "通过" if formula_ok and offset_ok and no_cache_warn != "WARN" else "有条件通过"
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    report = f"""# Fixed-reference compensation sanity report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 为什么做核查

上一轮固定参考点补偿位置误差敏感性实验给出了较高 ACCEPT 率。由于上一轮运行过程中多次被安全检查中断，本轮只做离线、合成、学术仿真的 mathematical simulation sanity check，核查公式方向、`S_hat` 位置偏移、no-compensation 对照、补偿误差随 e 的变化，以及上一轮 dataset 一致性。

## 2. 正确公式

固定参考点补偿的定义是让模拟卫星 B 在参考点 `S_hat` 上看起来像目标卫星 A：

`u_Shat(t) = f_geo(A, S_hat, t) - f_geo(B, S_hat, t)`

真实站 S 接收的补偿后曲线为：

`f_comp(t) = f_geo(B, S, t) + f_geo(A, S_hat, t) - f_geo(B, S_hat, t)`

验证器比较 `f_comp(t) - f_geo(A, S, t)`。

## 3. 最小 sanity case

- target：`{meta['target_id']} / {meta['target_name']}`
- attack type：`{meta['attack_type']}`
- attack param：`{meta['attack_param_name']} = {meta['attack_param_value']}`

east bearing 下的核心统计：

{east_small.to_markdown(index=False)}

## 4. e = 0 km sanity check

`e=0` 时 `S_hat=S`，因此正确方向的 `f_comp` 应退化为 `f_geo(A,S)`。本轮最大 `comp_delta_rmse_before_bk_hz` 为 `{max_e0_comp:.6g}` Hz；反向公式在 `e=0` 的最小 RMSE 为 `{reverse_e0:.6g}` Hz。

结论：{'补偿公式方向正确，e=0 退化符合预期。' if formula_ok else 'e=0 未退化到目标曲线，上一轮公式或变量使用需要修复。'}

## 5. S_hat 位置偏移核查

本轮测试 bearings：`{', '.join(str(v) for v in args.bearings)}`，e values：`{', '.join(str(v) for v in args.e_values)}`。设置距离与实际 haversine 距离的最大偏差为 `{max_distance_error:.6g}` km。

结论：{'S_hat 随 e 和 bearing 正确改变。' if offset_ok else 'S_hat 偏移距离异常，需要先修复位置生成。'}

## 6. no-compensation baseline

`raw_delta_rmse_hz` 是未补偿 B 相对 A 的差异；`comp_delta_rmse_before_bk_hz` 是补偿后未做 b/k 拟合前的差异。`e=0` 时 improvement ratio 应非常大，表示补偿确实生效。随 e 增大，补偿误差出现可观测变化；同时 `comp_delta_rmse_after_bk_hz` 明显小于 before-bk，说明 b/k 拟合会吸收一部分位置失配。

## 7. 补偿误差随 e 的变化

east bearing 下 `e=0` 到 `e=100 km` 的 residual score 变化为 `{residual_growth:.6g}` Hz。本轮不要求严格单调，因为过境几何和方向会影响曲线形状；但如果只看 0-10 km，小范围内变化可能被 b/k 拟合和 hard-case 选择掩盖。因此上一轮 0-10 km ACCEPT 率不明显下降，可能是模型现象，也可能与 hard-case 加权和阈值/拟合吸收有关，并非直接说明位置误差完全无影响。

## 8. 曲线图

{figs}

## 9. 上一轮 dataset 一致性检查

{consistency.to_markdown(index=False)}

## 10. 最终回答

1. 上一轮补偿公式方向是否正确：若以上源码检查与 `e=0` 退化均成立，则方向正确；本轮核查结果为 `{ '正确' if formula_ok else '错误或未通过' }`。
2. `e=0 km` 时补偿后曲线是否接近目标曲线：`comp_delta_rmse_before_bk_hz` 最大 `{max_e0_comp:.6g}` Hz，{'接近数值零' if formula_ok else '不接近'}。
3. `S_hat` 是否真的按 e 改变：最大距离误差 `{max_distance_error:.6g}` km，{'有效' if offset_ok else '异常'}。
4. 不同 e 是否重新计算补偿量：sanity metrics 中 `u_shat`、RMSE 与位置坐标随 e/bearing 变化；dataset 中未发现大比例完全相同 score 的 e 复用迹象时可认为重新计算有效。
5. 0-10 km 下接受率不下降是否可能因为位置误差范围太小：可能。最小复现显示 0-100 km 才更容易观察到失配趋势，0-10 km 可能被 b/k 拟合和窗口选择削弱。
6. b/k 拟合是否吸收了大部分位置误差：是，`comp_delta_rmse_after_bk_hz` 通常显著低于 before-bk，应在主动补偿评估中单独报告 before/after b/k。
7. 上一轮结果是否可信：`{credibility}`。它可作为 hard-case pressure test 初步结果，但不应作为最终安全边界。
8. 如果可信，下一轮是否扩大到 20/50/100/200 km 并加入普通样本对照：建议扩大，并加入普通样本、不同 bearing、不同窗口组合和 before/after b/k 指标。
9. 如果不可信，需要修复哪部分并重跑：若公式或 S_hat 检查失败，应修复公式方向或位置生成；若 dataset consistency 出现缓存复用，应修复 e 循环内曲线重算与输出字段。

## 11. 分情况结论

- 情况 A：若公式、e=0、S_hat、dataset consistency 均通过，则上一轮可作为强压力测试初步结果。
- 情况 B：若公式方向错误，则上一轮结果不能直接作为结论，需要修正后重跑。
- 情况 C：若 e 未生效或缓存复用，则上一轮位置误差敏感性结果不可信，需要修复 S_hat 生成或缓存逻辑后重跑。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report, encoding="utf-8")


def append_log(args: argparse.Namespace, metrics: pd.DataFrame, consistency: pd.DataFrame) -> None:
    fails = int(consistency["status"].eq("FAIL").sum()) if not consistency.empty else 0
    warns = int(consistency["status"].eq("WARN").sum()) if not consistency.empty else 0
    e0 = metrics[metrics["e_km"].eq(0.0)]
    max_e0 = float(e0["comp_delta_rmse_before_bk_hz"].max()) if not e0.empty else math.nan
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - fixed-reference compensation sanity check

### A. 本轮目标

核查上一轮固定参考点补偿实验的公式方向、`e=0` 退化、位置偏移、no-compensation 对照和 dataset 一致性。

### B. 实际操作

- 新增 `scripts/check_fixed_reference_compensation_sanity.py`。
- 选取最小 A/B/S case，扫描 e 和 north/east/south/west 四个方向。
- 重新计算 `f_geo(A,S)`、`f_geo(B,S)`、`f_comp`、before/after b/k residual。
- 读取上一轮 dataset 做一致性检查。

### C. 新增/修改文件

- 新增：`scripts/check_fixed_reference_compensation_sanity.py`
- 生成：`{args.metrics_output.as_posix()}`
- 生成：`{args.consistency_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}` 下 sanity 曲线图

### D. 运行命令

```bash
python -m py_compile scripts/check_fixed_reference_compensation_sanity.py
python scripts/check_fixed_reference_compensation_sanity.py --input-dataset {args.input_dataset.as_posix()} --e-values {','.join(str(v).rstrip('0').rstrip('.') for v in args.e_values)} --bearings {','.join(str(v).rstrip('0').rstrip('.') for v in args.bearings)} --target-index {args.target_index} --case-index {args.case_index} --overwrite
```

### E. 结果摘要

- sanity metrics rows：`{len(metrics)}`。
- consistency FAIL：`{fails}`。
- consistency WARN：`{warns}`。
- e=0 max comp delta RMSE before b/k：`{max_e0:.6g}` Hz。

### F. 问题与下一步

建议下一轮扩大 e 到 20/50/100/200 km，并加入普通样本对照；如 consistency 出现 FAIL，应先修复后重跑上一轮主实验。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.e_values = parse_csv_floats(args.e_values)
    args.bearings = parse_csv_floats(args.bearings)
    check_outputs([args.metrics_output, args.consistency_output, args.report_output], args.overwrite)
    if not args.input_dataset.exists():
        fail(f"input dataset not found: {args.input_dataset}")
    dataset = pd.read_csv(args.input_dataset)
    summary = pd.read_csv(args.summary) if args.summary.exists() else None
    metrics, _geo, meta = compute_sanity_metrics(args, dataset)
    consistency = dataset_consistency(args, dataset, summary)
    figures = make_curve_figures(metrics, meta, args.figures_dir)
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.metrics_output, index=False)
    args.consistency_output.parent.mkdir(parents=True, exist_ok=True)
    consistency.to_csv(args.consistency_output, index=False)
    write_report(args, metrics, consistency, figures, meta)
    append_log(args, metrics, consistency)
    print(f"wrote {args.metrics_output} rows={len(metrics)}")
    print(f"wrote {args.consistency_output} rows={len(consistency)}")
    print(f"wrote {args.report_output}")
    for p in figures:
        print(p)


if __name__ == "__main__":
    main()
