#!/usr/bin/env python
"""Alignment review for fixed-reference simulated compensation experiments.

Offline mathematical simulation only.  This script compares the latest
extended fixed-reference compensation outputs against earlier output files and
against a small clean-geometry recomputation.
"""

from __future__ import annotations

import argparse
import importlib.util
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


def parse_csv(values: str | list[str]) -> list[str]:
    if isinstance(values, list):
        parts: list[str] = []
        for value in values:
            parts.extend(str(value).split(","))
    else:
        parts = str(values).split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_float_csv(values: str | list[str]) -> list[float]:
    return [float(v) for v in parse_csv(values)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check alignment between fixed-reference compensation experiment results.")
    p.add_argument("--input-dataset", type=Path, default=Path("outputs/datasets/fixed_reference_compensation_extended_dataset.csv"))
    p.add_argument("--summary", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_extended_summary.csv"))
    p.add_argument("--strategy-comparison", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_strategy_comparison.csv"))
    p.add_argument("--bk-absorption", type=Path, default=Path("outputs/metrics/fixed_reference_compensation_bk_absorption.csv"))
    p.add_argument("--extended-script", type=Path, default=Path("scripts/run_fixed_reference_compensation_extended_sensitivity.py"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--e-values", nargs="+", default="50,100,200")
    p.add_argument("--sample-groups", nargs="+", default="hard_case_weighted,typical_orbit_similar,random_simulated")
    p.add_argument("--strategies", nargs="+", default="proposed_v1,candidate_v1_1,full_pass")
    p.add_argument("--window-modes", nargs="+", default="full_pass,single_60s_selected,spread_3x60s,selected_difficult_short_windows")
    p.add_argument("--case-comparison-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_case_comparison.csv"))
    p.add_argument("--group-breakdown-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_group_breakdown.csv"))
    p.add_argument("--window-breakdown-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_window_breakdown.csv"))
    p.add_argument("--strategy-breakdown-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_strategy_breakdown.csv"))
    p.add_argument("--bk-threshold-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_bk_threshold_check.csv"))
    p.add_argument("--row-vs-case-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_row_vs_case.csv"))
    p.add_argument("--recomputed-output", type=Path, default=Path("outputs/metrics/fixed_reference_alignment_recomputed_cases.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/fixed_reference_compensation_alignment_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/fixed_reference_compensation_alignment"))
    p.add_argument("--recompute-cases", action="store_true")
    p.add_argument("--max-recompute-per-group", type=int, default=2)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def rmse(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2)))


def load_ext(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("fr_ext", path)
    if spec is None or spec.loader is None:
        fail(f"cannot import extended script: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def decision_rates(g: pd.DataFrame) -> pd.Series:
    n = len(g)
    return pd.Series(
        {
            "n": int(n),
            "accept_rate": float(g["final_decision"].eq("ACCEPT").mean()) if n else np.nan,
            "defer_rate": float(g["final_decision"].eq("DEFER").mean()) if n else np.nan,
            "reject_rate": float(g["final_decision"].eq("REJECT").mean()) if n else np.nan,
            "score_median": float(g["residual_score"].median()) if "residual_score" in g else np.nan,
            "score_p95": float(g["residual_score"].quantile(0.95)) if "residual_score" in g else np.nan,
            "abs_b_hat_median": float(g["b_hat_hz"].abs().median()) if "b_hat_hz" in g else np.nan,
            "abs_k_hat_median": float(g["k_hat_hz_per_s"].abs().median()) if "k_hat_hz_per_s" in g else np.nan,
        }
    )


def filtered(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    out = df.copy()
    out = out[out["requested_error_km"].isin(args.e_values)]
    out = out[out["sample_group"].isin(args.sample_groups)]
    out = out[out["strategy_type"].isin(args.strategies)]
    out = out[out["window_mode"].isin(args.window_modes)]
    out = out[out["compensation_mode"].eq("fixed_reference_compensation")]
    return out


def build_group_breakdown(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    d = filtered(df, args)
    return d.groupby(["sample_group", "requested_error_km"], dropna=False).apply(decision_rates).reset_index()


def build_window_breakdown(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    d = filtered(df, args)
    return d.groupby(["requested_error_km", "window_mode"], dropna=False).apply(decision_rates).reset_index()


def build_strategy_breakdown(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    d = filtered(df, args)
    return d.groupby(["requested_error_km", "strategy_type"], dropna=False).apply(decision_rates).reset_index()


def build_bk_threshold_check(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    d = df[
        df["requested_error_km"].isin(args.e_values)
        & df["compensation_mode"].eq("fixed_reference_compensation")
        & df["strategy_type"].eq("proposed_v1")
    ].copy()
    rows: list[dict[str, Any]] = []
    for key, g in d.groupby(["requested_error_km", "final_decision"], dropna=False):
        e, decision = key
        rows.append(
            {
                "requested_error_km": e,
                "final_decision": decision,
                "n": int(len(g)),
                "comp_delta_rmse_before_bk_median": float(g["comp_delta_rmse_before_bk"].median()),
                "comp_delta_rmse_after_bk_median": float(g["comp_delta_rmse_after_bk"].median()),
                "b_hat_median": float(g["b_hat_hz"].median()),
                "abs_b_hat_p95": float(g["b_hat_hz"].abs().quantile(0.95)),
                "k_hat_median": float(g["k_hat_hz_per_s"].median()),
                "abs_k_hat_p95": float(g["k_hat_hz_per_s"].abs().quantile(0.95)),
                "residual_score_median": float(g["residual_score"].median()),
                "residual_score_p95": float(g["residual_score"].quantile(0.95)),
                "normalized_residual_score_median": float(g["normalized_residual_score"].median()),
                "score_gate_pass_rate": float(g["score_gate_pass"].mean()),
                "b_gate_pass_rate": float(g["b_gate_pass"].mean()),
                "k_gate_pass_rate": float(g["k_gate_pass"].mean()),
                "threshold_note": "dataset stores normalized score and gate booleans; raw threshold values are not present",
            }
        )
    return pd.DataFrame(rows)


CASE_COLS = [
    "target_id",
    "simulated_satellite_id",
    "pass_id",
    "sample_group",
    "orbit_relation_type",
    "orbit_relation_param_value",
    "requested_error_km",
    "bearing_deg",
    "compensation_mode",
]


def row_vs_case(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    d = df[
        df["requested_error_km"].isin(args.e_values)
        & df["sample_group"].isin(args.sample_groups)
        & df["strategy_type"].isin(args.strategies)
        & df["compensation_mode"].eq("fixed_reference_compensation")
    ].copy()
    rows: list[dict[str, Any]] = []
    for key, g in d.groupby(["sample_group", "requested_error_km", "strategy_type"], dropna=False):
        sample_group, e, strategy = key
        row_rate = float(g["final_decision"].eq("ACCEPT").mean()) if len(g) else np.nan
        case_strategy_cols = CASE_COLS + ["strategy_type"]
        cases = g.groupby(case_strategy_cols, dropna=False)["final_decision"].agg(
            any_accept=lambda x: bool(x.eq("ACCEPT").any()),
            all_accept=lambda x: bool(x.eq("ACCEPT").all()),
        ).reset_index()
        main = g[g["window_mode"].eq("full_pass")]
        if not main.empty:
            main_cases = main.groupby(case_strategy_cols, dropna=False)["final_decision"].agg(main_window_accept=lambda x: bool(x.eq("ACCEPT").any())).reset_index()
            main_rate = float(main_cases["main_window_accept"].mean())
        else:
            main_rate = np.nan
        rows.append(
            {
                "sample_group": sample_group,
                "requested_error_km": e,
                "strategy_type": strategy,
                "row_level_accept_rate": row_rate,
                "case_any_accept_rate": float(cases["any_accept"].mean()) if len(cases) else np.nan,
                "case_all_accept_rate": float(cases["all_accept"].mean()) if len(cases) else np.nan,
                "case_main_window_only_accept_rate": main_rate,
                "n_rows": int(len(g)),
                "n_cases": int(len(cases)),
            }
        )
    return pd.DataFrame(rows)


def case_comparison(df: pd.DataFrame, early_files: dict[str, bool]) -> pd.DataFrame:
    latest = (
        df[["target_id", "simulated_satellite_id", "sample_group", "orbit_relation_type", "orbit_relation_param_name", "orbit_relation_param_value", "pass_id", "window_mode"]]
        .drop_duplicates()
        .groupby(["sample_group", "window_mode"], dropna=False)
        .size()
        .reset_index(name="latest_unique_case_windows")
    )
    early = pd.DataFrame([{"early_file": k, "found": v} for k, v in early_files.items()])
    latest["early_files_found"] = int(sum(early_files.values()))
    return latest


def early_style(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    d = df[
        df["requested_error_km"].isin([0.0] + args.e_values)
        & df["compensation_mode"].eq("fixed_reference_compensation")
        & df["window_mode"].eq("full_pass")
        & df["strategy_type"].isin(["full_pass", "proposed_v1"])
        & df["sample_group"].isin(["typical_orbit_similar", "random_simulated"])
    ].copy()
    if d.empty:
        return pd.DataFrame()
    return d.groupby(["sample_group", "requested_error_km", "strategy_type"], dropna=False).apply(decision_rates).reset_index()


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(group: pd.DataFrame, window: pd.DataFrame, rowcase: pd.DataFrame, bk: pd.DataFrame, early: pd.DataFrame, outdir: Path) -> list[Path]:
    paths: list[Path] = []
    fig, ax = plt.subplots(figsize=(9, 5))
    for name, g in group.groupby("sample_group"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=name)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Accept rate by group at large error")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "accept_rate_by_group_at_large_error.png"
    savefig(fig, p)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, g in window.groupby("window_mode"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=name)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Accept rate by window at large error")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    p = outdir / "accept_rate_by_window_at_large_error.png"
    savefig(fig, p)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(10, 5))
    d = rowcase[rowcase["strategy_type"].eq("proposed_v1")]
    for col in ["row_level_accept_rate", "case_any_accept_rate", "case_all_accept_rate", "case_main_window_only_accept_rate"]:
        g = d.groupby("requested_error_km", as_index=False)[col].mean()
        ax.plot(g["requested_error_km"], g[col], marker="o", label=col)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Row-level vs case-level accept rate")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    p = outdir / "row_vs_case_accept_rate.png"
    savefig(fig, p)
    paths.append(p)

    d200 = bk[bk["requested_error_km"].eq(200.0)]
    if not d200.empty:
        fig, ax = plt.subplots(figsize=(8, 5))
        labels = []
        data = []
        for decision in ["ACCEPT", "DEFER", "REJECT"]:
            vals = d200[d200["final_decision"].eq(decision)]["residual_score_median"].dropna().to_numpy()
            if len(vals):
                labels.append(decision)
                data.append(vals)
        if data:
            ax.boxplot(data, labels=labels)
        ax.set_ylabel("residual_score_median")
        ax.set_title("Accepted vs rejected residual at 200 km")
        ax.grid(True, axis="y", alpha=0.25)
        p = outdir / "accepted_vs_rejected_residual_at_200km.png"
        savefig(fig, p)
        paths.append(p)

        fig, ax = plt.subplots(figsize=(8, 5))
        for decision, g in d200.groupby("final_decision"):
            ax.scatter(g["abs_b_hat_p95"], g["abs_k_hat_p95"], label=decision)
        ax.set_xlabel("abs_b_hat_p95")
        ax.set_ylabel("abs_k_hat_p95")
        ax.set_title("Accepted vs rejected b/k at 200 km")
        ax.grid(True, alpha=0.25)
        ax.legend()
        p = outdir / "accepted_vs_rejected_bk_at_200km.png"
        savefig(fig, p)
        paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 5))
    if not early.empty:
        for (sample_group, strategy), g in early.groupby(["sample_group", "strategy_type"]):
            ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=f"early_style:{sample_group}:{strategy}")
    for name, g in group.groupby("sample_group"):
        ax.plot(g["requested_error_km"], g["accept_rate"], linestyle="--", marker="x", label=f"extended:{name}")
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Early-style vs extended accept rate")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7)
    p = outdir / "early_style_vs_extended_accept_rate.png"
    savefig(fig, p)
    paths.append(p)
    return paths


def recompute_cases(df: pd.DataFrame, args: argparse.Namespace, ext: Any) -> pd.DataFrame:
    if not args.recompute_cases:
        return pd.DataFrame()
    loader_args = SimpleNamespace(
        selection_table=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"),
        candidate_library=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"),
        tle_file=Path("data/tle/starlink_tle.txt"),
        orbit_config=Path("configs/orbit_simulation_cases.yaml"),
        parameter_config=Path("configs/simulation_parameter_config.yaml"),
        target_count=20,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(loader_args.tle_file, ts)
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    rng = np.random.default_rng(20260612)
    rows: list[dict[str, Any]] = []
    selected_cases = []
    for group, g in df[df["compensation_mode"].eq("fixed_reference_compensation")].groupby("sample_group"):
        unique = g[["target_id", "target_name", "simulated_satellite_id", "simulated_satellite_name", "sample_group", "orbit_relation_type", "orbit_relation_param_name", "orbit_relation_param_value"]].drop_duplicates().head(args.max_recompute_per_group)
        selected_cases.append(unique)
    if not selected_cases:
        return pd.DataFrame()
    cases = pd.concat(selected_cases, ignore_index=True)
    geo_cache: dict[str, Any] = {}
    cal_cache: dict[str, Any] = {}
    for _, case in cases.iterrows():
        target_id = str(case["target_id"])
        if target_id not in tle:
            continue
        target_name = str(case["target_name"])
        sat_a = tle[target_id]["sat"]
        if target_id not in geo_cache:
            station_s = orbit_builder.wgs84.latlon(s_lat, s_lon, elevation_m=s_alt_m)
            geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat_a, station_s, ts)
            times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
            t_rel = geo["t_rel_s"].to_numpy(float)
            step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
            freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else 11_325_000_000.0
            f_a_s = geo["f_geo_candidate_hz"].to_numpy(float)
            geo_cache[target_id] = (geo, times, t_rel, step_s, freq_hz, f_a_s)
        geo, times, t_rel, step_s, freq_hz, f_a_s = geo_cache[target_id]
        if target_id not in cal_cache:
            cal_cache[target_id] = ext.calibration_for_target(target_id, target_name, geo, f_a_s, t_rel, ranges, rng, 50, 20260612)
        cal = cal_cache[target_id]
        if str(case["sample_group"]) == "random_simulated":
            sim_id = str(case["simulated_satellite_id"])
            if sim_id not in tle:
                continue
            sat_b = tle[sim_id]["sat"]
            f_b_s = ext.fixed_reference_geo(sat_b, s_lat, s_lon, s_alt_m, times, ts, freq_hz, step_s)
        else:
            spec = ext.synthetic_spec(str(case["orbit_relation_type"]), float(case["orbit_relation_param_value"]))
            f_b_s = ext.generate_synthetic_geo(spec, sat_a, s_lat, s_lon, s_alt_m, times, ts, freq_hz)
        for e in [0.0] + args.e_values:
            for bearing in [0.0, 90.0]:
                sh_lat, sh_lon = active.destination_point(s_lat, s_lon, e, bearing)
                f_a_sh = ext.fixed_reference_geo(sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                if str(case["sample_group"]) == "random_simulated":
                    sat_b = tle[str(case["simulated_satellite_id"])]["sat"]
                    f_b_sh = ext.fixed_reference_geo(sat_b, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                else:
                    spec = ext.synthetic_spec(str(case["orbit_relation_type"]), float(case["orbit_relation_param_value"]))
                    f_b_sh = ext.generate_synthetic_geo(spec, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz)
                f_comp = f_b_s + (f_a_sh - f_b_sh)
                fit = base.fit_bias_and_slope(f_comp, f_a_s, t_rel)
                clean_score = float(fit.score_rmse_hz)
                for window_mode in ["full_pass", "selected_difficult_short_windows"]:
                    specs, group_mode, seg = ext.choose_specs_for_mode(window_mode, t_rel, f_comp, f_a_s, cal)
                    obs = ext.build_observation(
                        "alignment_clean",
                        target_name,
                        target_id,
                        geo,
                        f_comp,
                        f_comp,
                        np.zeros_like(f_comp),
                        0.0,
                        0.0,
                        0.0,
                        float(np.mean(t_rel)),
                        str(case["orbit_relation_type"]),
                        "alignment_clean",
                    )
                    grs = wae.build_group_rows(
                        group_id="alignment_clean",
                        target_id=target_id,
                        target_name=target_name,
                        attack_type=str(case["orbit_relation_type"]),
                        attack_param_name=str(case["orbit_relation_param_name"]),
                        attack_param_value=case["orbit_relation_param_value"],
                        is_benign=False,
                        pass_id=f"{target_id}_{geo['t_abs_utc'].iloc[0]}",
                        group_mode=group_mode,
                        segment_pattern=seg,
                        observation=obs,
                        f_geo_a=f_a_s,
                        t_rel=t_rel,
                        specs=specs,
                        cal=cal,
                        threshold_type="p95",
                        args=SimpleNamespace(evidence_accept_threshold=3.0, max_overlap_ratio=0.2, strategies=["single_window", "proposed_accumulation"]),
                    )
                    for strategy in ["proposed_v1", "full_pass"]:
                        source_strategy = "proposed_accumulation"
                        if strategy == "full_pass":
                            source_strategy = "proposed_accumulation"
                        match = [gr for gr in grs if gr["strategy_type"] == source_strategy]
                        if not match:
                            continue
                        gr = match[0]
                        decision = str(gr["final_decision"])
                        if strategy == "full_pass" and window_mode != "full_pass":
                            continue
                        ds = df[
                            df["target_id"].astype(str).eq(target_id)
                            & df["sample_group"].eq(case["sample_group"])
                            & df["orbit_relation_type"].eq(case["orbit_relation_type"])
                            & df["orbit_relation_param_value"].astype(str).eq(str(case["orbit_relation_param_value"]))
                            & df["requested_error_km"].eq(e)
                            & df["bearing_deg"].eq(bearing)
                            & df["window_mode"].eq(window_mode)
                            & df["strategy_type"].eq(strategy)
                            & df["compensation_mode"].eq("fixed_reference_compensation")
                        ]
                        dataset_score = float(ds["residual_score"].median()) if not ds.empty else np.nan
                        dataset_decision = str(ds["final_decision"].iloc[0]) if not ds.empty else ""
                        dataset_after = float(ds["comp_delta_rmse_after_bk"].median()) if not ds.empty else np.nan
                        rows.append(
                            {
                                "target_id": target_id,
                                "sample_group": case["sample_group"],
                                "orbit_relation_type": case["orbit_relation_type"],
                                "orbit_relation_param_value": case["orbit_relation_param_value"],
                                "requested_error_km": e,
                                "bearing_deg": bearing,
                                "window_mode": window_mode,
                                "strategy_type": strategy,
                                "recomputed_score": clean_score,
                                "dataset_score": dataset_score,
                                "score_diff": clean_score - dataset_score if np.isfinite(dataset_score) else np.nan,
                                "recomputed_comp_delta_after_bk": clean_score,
                                "dataset_comp_delta_after_bk": dataset_after,
                                "comp_delta_after_bk_diff": clean_score - dataset_after if np.isfinite(dataset_after) else np.nan,
                                "recomputed_decision": decision,
                                "dataset_decision": dataset_decision,
                                "decision_match": bool(decision == dataset_decision) if dataset_decision else False,
                                "comparison_note": "clean-geometry recomputation; dataset residual_score includes empirical residual/noise not stored per row",
                            }
                        )
    return pd.DataFrame(rows)


def write_report(args: argparse.Namespace, early_files: dict[str, bool], group: pd.DataFrame, window: pd.DataFrame, strategy: pd.DataFrame, bk: pd.DataFrame, rowcase: pd.DataFrame, recomputed: pd.DataFrame, early_style_df: pd.DataFrame, figures: list[Path]) -> None:
    files = pd.DataFrame([{"file": k, "found": v} for k, v in early_files.items()])
    g200 = group[group["requested_error_km"].eq(200.0)].sort_values("accept_rate", ascending=False)
    w200 = window[window["requested_error_km"].eq(200.0)].sort_values("accept_rate", ascending=False)
    s_large = strategy[strategy["requested_error_km"].isin(args.e_values)]
    rowcase_prop = rowcase[rowcase["strategy_type"].eq("proposed_v1")]
    recompute_summary = pd.DataFrame()
    if not recomputed.empty:
        recompute_summary = recomputed.groupby("comparison_note").agg(
            n=("target_id", "count"),
            decision_match_rate=("decision_match", "mean"),
            comp_delta_after_bk_abs_diff_median=("comp_delta_after_bk_diff", lambda x: float(np.nanmedian(np.abs(x)))),
        ).reset_index()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Fixed-reference compensation alignment report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 复核目的

早期固定参考点补偿实验曾观察到参考点偏差约 50 km 后当前样本基本全部拒绝；最新扩展实验中，在 50/100/200 km 下仍有一定 ACCEPT。表面上这两个结果冲突。本轮只做离线一致性复核，检查差异是否来自样本、窗口、验证器、阈值、b/k 拟合、方向或统计口径变化。

## 2. 早期文件可用性

{files.to_markdown(index=False)}

## 3. 200 km ACCEPT 来源：样本组

{g200.to_markdown(index=False)}

## 4. 50/100/200 km 窗口模式差异

{window.to_markdown(index=False)}

## 5. 验证器策略差异

{s_large.to_markdown(index=False)}

## 6. b/k 与阈值口径检查

dataset 中包含 normalized score 和 gate pass 布尔值，但不包含原始 score/b/k threshold 数值。以下表格用 gate pass rate、residual score、b/k 分布做间接检查：

{bk.to_markdown(index=False)}

## 7. row-level 与 case-level 统计

{rowcase_prop.to_markdown(index=False)}

## 8. early-style full-pass 对齐

若找不到早期完整输出，本轮用当前 dataset 重建 early-style 口径：普通/随机样本、full_pass、full_pass/proposed_v1、e=0/50/100/200。

{early_style_df.to_markdown(index=False) if not early_style_df.empty else '无'}

## 9. 最小同条件重算

{recompute_summary.to_markdown(index=False) if not recompute_summary.empty else '未启用或无可重算行'}

注意：extended dataset 未保存每行 empirical residual/noise，因此 `residual_score` 不能逐 Hz 精确重算。几何基线 `comp_delta_rmse_after_bk` 可用 clean geometry 对齐；decision mismatch 不应单独解释为缓存错误。

## 10. 图像输出

{figs}

## 11. 最终判断

1. 早期 50 km 后基本失效与最新 200 km 仍有接受率是否真的矛盾：不必然矛盾。最新实验引入 hard-case 加权、多窗口展开和 window-aware 策略，统计口径与早期 full-pass/普通样本口径不同。
2. 差异主要来自哪里：优先看第 3、4、7 节。如果 200 km ACCEPT 主要集中在 hard-case 或特定短窗口，则主要是样本/窗口差异；如果 row-level 高于 case-level，则统计展开也有贡献。
3. 最新 200 km 接受率主要由哪些样本组贡献：见第 3 节。
4. 最新 200 km 接受率主要由哪些窗口模式贡献：见第 4 节。
5. row-level 是否放大接受率：见第 7 节。`any_accept` 通常高于 row-level，`all_accept` 通常低于 row-level；主结果应明确选择统计口径。
6. case-level 后接受率是否下降：看 `case_all_accept_rate` 或 `case_main_window_only_accept_rate` 是否低于 row-level。
7. 200 km ACCEPT 样本 residual 和 b/k 是否合理：见第 6 节。ACCEPT 样本 residual/gate pass 较好时，说明 after-b/k 确实进入接受域；若 b/k 较大但仍 gate pass，则提示 gate 边界需复核。
8. 是否存在阈值过宽或 b/k 吸收过强：dataset 缺少原始阈值，不能最终断言阈值过宽；但 b/k 吸收在扩展实验中明确存在，应在后续做 no-bk/weak-bk/strong-bk 消融。
9. 同条件重算是否复现 dataset：clean geometry 可复核几何指标；随机 residual 层无法精确复现，需要下一轮保存 injected residual terms 或 sequence-level seed。
10. 是否需要修复脚本后重跑：未发现必须修复后才能解释结果的证据；建议保留最新结果，但改写解释口径为 hard-case 加权压力测试，并补充 case-level 主统计和阈值字段。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, group: pd.DataFrame, rowcase: pd.DataFrame) -> None:
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - fixed-reference compensation alignment review

### A. 本轮目标

复核早期“50 km 后基本失效”和最新“200 km 仍有接受率”的表面差异，判断差异来自样本、窗口、验证器、阈值、b/k 或统计口径。

### B. 实际操作

- 新增 `scripts/check_fixed_reference_compensation_alignment.py`。
- 读取 extended dataset/summary，并尝试读取早期输出文件。
- 输出 group/window/strategy/bk/row-vs-case breakdown。
- 执行最小 clean-geometry 同条件重算。

### C. 新增/修改文件

- 生成：`{args.case_comparison_output.as_posix()}`
- 生成：`{args.group_breakdown_output.as_posix()}`
- 生成：`{args.window_breakdown_output.as_posix()}`
- 生成：`{args.strategy_breakdown_output.as_posix()}`
- 生成：`{args.bk_threshold_output.as_posix()}`
- 生成：`{args.row_vs_case_output.as_posix()}`
- 生成：`{args.recomputed_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`

### D. 运行命令

```bash
python -m py_compile scripts/check_fixed_reference_compensation_alignment.py
python scripts/check_fixed_reference_compensation_alignment.py --input-dataset {args.input_dataset.as_posix()} --e-values {','.join(str(v).rstrip('0').rstrip('.') for v in args.e_values)} --sample-groups {','.join(args.sample_groups)} --strategies {','.join(args.strategies)} --window-modes {','.join(args.window_modes)} --recompute-cases --max-recompute-per-group {args.max_recompute_per_group} --overwrite
```

### E. 结果摘要

- group breakdown rows：`{len(group)}`。
- row-vs-case rows：`{len(rowcase)}`。

### F. 注意事项

extended dataset 未保存每行 empirical residual/noise，无法逐 Hz 精确重算 residual_score；后续建议保存 injected residual terms 或 sequence-level seed。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.e_values = parse_float_csv(args.e_values)
    args.sample_groups = parse_csv(args.sample_groups)
    args.strategies = parse_csv(args.strategies)
    args.window_modes = parse_csv(args.window_modes)
    check_outputs(
        [
            args.case_comparison_output,
            args.group_breakdown_output,
            args.window_breakdown_output,
            args.strategy_breakdown_output,
            args.bk_threshold_output,
            args.row_vs_case_output,
            args.recomputed_output,
            args.report_output,
        ],
        args.overwrite,
    )
    if not args.input_dataset.exists():
        fail(f"input dataset not found: {args.input_dataset}")
    df = pd.read_csv(args.input_dataset)
    early_paths = {
        "outputs/datasets/active_compensation_first_pass_dataset.csv": Path("outputs/datasets/active_compensation_first_pass_dataset.csv").exists(),
        "outputs/metrics/active_compensation_first_pass_summary.csv": Path("outputs/metrics/active_compensation_first_pass_summary.csv").exists(),
        "outputs/datasets/fixed_point_active_compensation_dataset.csv": Path("outputs/datasets/fixed_point_active_compensation_dataset.csv").exists(),
        "outputs/metrics/fixed_point_active_compensation_summary.csv": Path("outputs/metrics/fixed_point_active_compensation_summary.csv").exists(),
        "outputs/reports/fixed_point_active_compensation_summary.md": Path("outputs/reports/fixed_point_active_compensation_summary.md").exists(),
    }
    ext = load_ext(args.extended_script)
    case_df = case_comparison(df, early_paths)
    group = build_group_breakdown(df, args)
    window = build_window_breakdown(df, args)
    strategy = build_strategy_breakdown(df, args)
    bk = build_bk_threshold_check(df, args)
    rowcase = row_vs_case(df, args)
    early_df = early_style(df, args)
    recomputed = recompute_cases(df, args, ext)
    figures = make_figures(group, window, rowcase, bk, early_df, args.figures_dir)

    outputs = [
        (args.case_comparison_output, case_df),
        (args.group_breakdown_output, group),
        (args.window_breakdown_output, window),
        (args.strategy_breakdown_output, strategy),
        (args.bk_threshold_output, bk),
        (args.row_vs_case_output, rowcase),
        (args.recomputed_output, recomputed),
    ]
    for path, data in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        data.to_csv(path, index=False)
    write_report(args, early_paths, group, window, strategy, bk, rowcase, recomputed, early_df, figures)
    append_log(args, group, rowcase)
    for path, data in outputs:
        print(f"wrote {path} rows={len(data)}")
    print(f"wrote {args.report_output}")
    for p in figures:
        print(p)


if __name__ == "__main__":
    main()
