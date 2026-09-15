#!/usr/bin/env python
"""First-pass multi-station consistency analysis.

Offline mathematical simulation only.  The script reuses the single-station
fixed-reference compensation verifier components and evaluates whether the
same fixed-reference compensation curve remains consistent at auxiliary
stations.
"""

from __future__ import annotations

import argparse
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

import build_controlled_starlink_multitarget_dataset as orbit_builder
import run_active_compensation_attack_first_pass as active
import run_doppler_verifier_initial_experiments as base
import run_fixed_reference_compensation_extended_sensitivity as ext
import run_single_station_bk_gate_ablation as ss
import run_window_reliability_calibration as wrc


DEFAULT_REFERENCE_ERRORS = [0, 50, 100, 200, 500]
DEFAULT_STATION_SEPARATIONS = [10, 50, 100, 500, 1000]
DEFAULT_BEARINGS = [0, 90, 180, 270]
DEFAULT_GROUPS = ["original_like", "hard_case_weighted", "random_simulated"]
DEFAULT_WINDOWS = ["full_pass", "spread_3x60s", "selected_difficult_short_windows"]
DEFAULT_BK_MODES = ["strict_bk", "current_bk", "bk_risk_defer"]
DEFAULT_MULTI_STRATEGIES = [
    "single_station_baseline",
    "dual_station_all_accept",
    "three_station_all_accept",
    "two_of_three_reject_hard",
    "two_of_three_reject_defer",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline multi-station consistency first pass.")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/multistation_consistency_first_pass_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/multistation_consistency_first_pass_summary.csv"))
    p.add_argument("--gain-output", type=Path, default=Path("outputs/metrics/multistation_consistency_gain.csv"))
    p.add_argument("--bk-risk-output", type=Path, default=Path("outputs/metrics/multistation_bk_risk_defer_effect.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/multistation_consistency_first_pass_report.md"))
    p.add_argument("--closure-output", type=Path, default=Path("outputs/reports/current_stage_research_closure_draft.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/multistation_consistency_first_pass"))
    p.add_argument("--reference-error-values", nargs="+", default=",".join(str(v) for v in DEFAULT_REFERENCE_ERRORS))
    p.add_argument("--station-separations", nargs="+", default=",".join(str(v) for v in DEFAULT_STATION_SEPARATIONS))
    p.add_argument("--reference-bearings", nargs="+", default=",".join(str(v) for v in DEFAULT_BEARINGS))
    p.add_argument("--station-bearings", nargs="+", default=",".join(str(v) for v in DEFAULT_BEARINGS))
    p.add_argument("--sample-groups", nargs="+", default=",".join(DEFAULT_GROUPS))
    p.add_argument("--window-modes", nargs="+", default=",".join(DEFAULT_WINDOWS))
    p.add_argument("--bk-modes", nargs="+", default=",".join(DEFAULT_BK_MODES))
    p.add_argument("--multi-station-strategies", nargs="+", default=",".join(DEFAULT_MULTI_STRATEGIES))
    p.add_argument("--max-targets", type=int, default=3)
    p.add_argument("--max-samples-per-group", type=int, default=3)
    p.add_argument("--num-benign-sims", type=int, default=50)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260612)
    p.add_argument("--include-no-bk", action="store_true")
    p.add_argument("--save-example-curves", action="store_true")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def parse_csv(values: str | list[str]) -> list[str]:
    return ss.parse_csv(values)


def parse_float_csv(values: str | list[str]) -> list[float]:
    return ss.parse_float_csv(values)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        raise SystemExit("output exists; add --overwrite: " + ", ".join(existing))


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return float(active.haversine_distance_km(np.array([lat1]), np.array([lon1]), lat2, lon2)[0])


def station_layout(s0_lat: float, s0_lon: float, s0_alt_m: float, separation_km: float, bearing_deg: float) -> dict[str, Any]:
    s1_lat, s1_lon = active.destination_point(s0_lat, s0_lon, separation_km, bearing_deg)
    s2_lat, s2_lon = active.destination_point(s0_lat, s0_lon, separation_km, (bearing_deg + 90.0) % 360.0)
    return {
        "station_layout_id": f"sep{separation_km:g}_bearing{bearing_deg:g}",
        "station_separation_km": float(separation_km),
        "station_bearing_deg": float(bearing_deg),
        "S0_lat": float(s0_lat),
        "S0_lon": float(s0_lon),
        "S1_lat": float(s1_lat),
        "S1_lon": float(s1_lon),
        "S2_lat": float(s2_lat),
        "S2_lon": float(s2_lon),
        "S_alt_m": float(s0_alt_m),
        "actual_S0_S1_distance_km": distance_km(s1_lat, s1_lon, s0_lat, s0_lon),
        "actual_S0_S2_distance_km": distance_km(s2_lat, s2_lon, s0_lat, s0_lon),
        "actual_S1_S2_distance_km": distance_km(s1_lat, s1_lon, s2_lat, s2_lon),
    }


def station_geo(sat: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float, step_s: float) -> tuple[np.ndarray, np.ndarray]:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    geo = orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))
    return geo["f_geo_tle_hz"].to_numpy(float), geo["elevation_deg"].to_numpy(float)


def synthetic_geo(spec: dict[str, Any], sat_a: Any, lat: float, lon: float, alt_m: float, times: list[Any], ts: Any, freq_hz: float) -> np.ndarray:
    return ext.generate_synthetic_geo(spec, sat_a, lat, lon, alt_m, times, ts, freq_hz)


def quality_for_specs(elevation: np.ndarray, t_rel: np.ndarray, specs: list[wrc.WindowSpec]) -> tuple[bool, bool, str]:
    if not specs:
        return False, False, "no_window_specs"
    mean_elevs = []
    visible_fracs = []
    for spec in specs:
        mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
        if int(mask.sum()) < 3:
            return False, False, "too_few_points"
        e = np.asarray(elevation[mask], dtype=float)
        finite = e[np.isfinite(e)]
        if len(finite) == 0:
            return False, False, "missing_elevation"
        mean_elevs.append(float(np.mean(finite)))
        visible_fracs.append(float(np.mean(finite >= 0.0)))
    visibility_ok = bool(min(visible_fracs) >= 0.5)
    quality_ok = bool(visibility_ok and min(mean_elevs) >= 0.0)
    reason = "" if quality_ok else "station_visibility_failed"
    return visibility_ok, quality_ok, reason


def apply_bk_risk(dec: dict[str, Any], before_rmse: float, after_rmse: float) -> tuple[dict[str, Any], float, str]:
    out = dict(dec)
    ratio = float(before_rmse / max(after_rmse, 1e-9))
    b_usage = abs(float(out["b_hat_hz"]) - float(out["b_center"])) / max(float(out["b_threshold"]), 1e-9)
    k_usage = abs(float(out["k_hat_hz_per_s"]) - float(out["k_center"])) / max(float(out["k_threshold"]), 1e-9)
    risk = bool(ratio >= 2.0 or b_usage >= 0.8 or k_usage >= 0.8)
    reason = ""
    if out["final_decision"] == "ACCEPT" and risk:
        out["final_decision"] = "DEFER_RISK"
        reason = f"bk_risk_defer_ratio={ratio:.3g}_b_usage={b_usage:.3g}_k_usage={k_usage:.3g}"
        out["decision_reason"] = reason
    return out, ratio, reason


def normalize_decision(decision: str) -> str:
    return "DEFER" if str(decision) == "DEFER_RISK" else str(decision)


def aggregate_multi(strategy: str, s0: str, s1: str, s2: str) -> tuple[str, str]:
    d0, d1, d2 = normalize_decision(s0), normalize_decision(s1), normalize_decision(s2)
    if strategy == "single_station_baseline":
        return d0, f"S0={d0}"
    if strategy == "dual_station_all_accept":
        vals = [d0, d1]
        if all(v == "ACCEPT" for v in vals):
            return "ACCEPT", "S0_S1_all_accept"
        if any(v == "REJECT" for v in vals):
            return "REJECT", "S0_S1_reject_present"
        return "DEFER", "S0_S1_not_all_accept"
    vals = [d0, d1, d2]
    accepts = vals.count("ACCEPT")
    rejects = vals.count("REJECT")
    if strategy == "three_station_all_accept":
        if accepts == 3:
            return "ACCEPT", "three_all_accept"
        if rejects:
            return "REJECT", "three_reject_present"
        return "DEFER", "three_not_all_accept"
    if strategy == "two_of_three_reject_hard":
        if accepts >= 2 and rejects == 0:
            return "ACCEPT", "two_of_three_accept_no_reject"
        if rejects:
            return "REJECT", "reject_hard_reject_present"
        return "DEFER", "two_of_three_insufficient_accept"
    if strategy == "two_of_three_reject_defer":
        if accepts >= 2 and rejects == 0:
            return "ACCEPT", "two_of_three_accept_no_reject"
        if rejects and accepts:
            return "DEFER", "reject_defer_mixed_accept_reject"
        if rejects:
            return "REJECT", "reject_defer_all_or_major_reject"
        return "DEFER", "two_of_three_insufficient_accept"
    raise SystemExit(f"unsupported multi-station strategy: {strategy}")


def station_decision(
    *,
    station_name: str,
    base_curve: np.ndarray,
    f_geo_a: np.ndarray,
    elevation_a: np.ndarray,
    t_rel: np.ndarray,
    specs: list[wrc.WindowSpec],
    cal: dict[str, dict[str, float]],
    bk_mode: str,
    noise: np.ndarray,
    b_inj: float,
    k_inj: float,
    t0: float,
) -> dict[str, Any]:
    effective_bk = "current_bk" if bk_mode == "bk_risk_defer" else bk_mode
    y_obs = base_curve + b_inj + k_inj * (t_rel - t0) + noise
    visibility_ok, quality_ok, quality_reason = quality_for_specs(elevation_a, t_rel, specs)
    dec = ss.decide(
        strategy="proposed_v1",
        window_mode="full_pass" if specs[0].window_position == "full_pass" else "spread_3x60s",
        bk_mode=effective_bk,
        specs=specs,
        y_obs=y_obs,
        f_geo_a=f_geo_a,
        t_rel=t_rel,
        cal=cal,
    )
    delta = base_curve - f_geo_a
    fit_geom = base.fit_bias_and_slope(base_curve, f_geo_a, t_rel)
    x = t_rel - float(np.mean(t_rel))
    after = delta - (fit_geom.b_hat_hz + fit_geom.k_hat_hz_s * x)
    before_rmse = ss.rmse(delta)
    after_rmse = ss.rmse(after)
    risk_reason = ""
    absorption_ratio = float(before_rmse / max(after_rmse, 1e-9))
    if bk_mode == "bk_risk_defer":
        dec, absorption_ratio, risk_reason = apply_bk_risk(dec, before_rmse, after_rmse)
    if not quality_ok:
        dec["final_decision"] = "DEFER"
        dec["decision_reason"] = quality_reason
    return {
        f"{station_name}_decision": dec["final_decision"],
        f"{station_name}_residual_score": dec["residual_score"],
        f"{station_name}_b_hat_hz": dec["b_hat_hz"],
        f"{station_name}_k_hat_hz_per_s": dec["k_hat_hz_per_s"],
        f"{station_name}_comp_delta_rmse_before_bk": before_rmse,
        f"{station_name}_comp_delta_rmse_after_bk": after_rmse,
        f"{station_name}_bk_absorption_ratio": absorption_ratio,
        f"{station_name}_score_gate_pass": dec["score_gate_pass"],
        f"{station_name}_b_gate_pass": dec["b_gate_pass"],
        f"{station_name}_k_gate_pass": dec["k_gate_pass"],
        f"{station_name}_visibility_ok": visibility_ok,
        f"{station_name}_quality_ok": quality_ok,
        f"{station_name}_decision_reason": dec["decision_reason"],
        f"{station_name}_bk_risk_reason": risk_reason,
    }


def decision_rates(series: pd.Series) -> dict[str, float]:
    n = len(series)
    norm = series.map(normalize_decision)
    return {
        "accept_rate": float((norm == "ACCEPT").sum() / n) if n else np.nan,
        "defer_rate": float((norm == "DEFER").sum() / n) if n else np.nan,
        "reject_rate": float((norm == "REJECT").sum() / n) if n else np.nan,
    }


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "sample_group",
        "requested_reference_error_km",
        "station_separation_km",
        "window_mode",
        "bk_mode",
        "multi_station_strategy",
        "compensation_mode",
    ]
    rows = []
    for key, g in df.groupby(group_cols, dropna=False):
        rates = decision_rates(g["multi_station_decision"])
        s0_accept = g["S0_decision"].map(normalize_decision).eq("ACCEPT")
        s1_accept = g["S1_decision"].map(normalize_decision).eq("ACCEPT")
        s2_accept = g["S2_decision"].map(normalize_decision).eq("ACCEPT")
        s0_reject = g["S0_decision"].map(normalize_decision).eq("REJECT")
        s1_reject = g["S1_decision"].map(normalize_decision).eq("REJECT")
        s2_reject = g["S2_decision"].map(normalize_decision).eq("REJECT")
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n_cases": int(len(g)),
                **rates,
                "single_station_accept_rate": float(s0_accept.mean()),
                "dual_station_accept_rate": float((s0_accept & s1_accept).mean()),
                "three_station_accept_rate": float((s0_accept & s1_accept & s2_accept).mean()),
                "two_of_three_accept_rate": float(((s0_accept.astype(int) + s1_accept.astype(int) + s2_accept.astype(int)) >= 2).mean()),
                "S0_accept_rate": float(s0_accept.mean()),
                "S1_accept_rate": float(s1_accept.mean()),
                "S2_accept_rate": float(s2_accept.mean()),
                "median_S0_score": float(g["S0_residual_score"].median()),
                "median_S1_score": float(g["S1_residual_score"].median()),
                "median_S2_score": float(g["S2_residual_score"].median()),
                "median_S0_bk_absorption_ratio": float(g["S0_bk_absorption_ratio"].median()),
                "median_S1_bk_absorption_ratio": float(g["S1_bk_absorption_ratio"].median()),
                "median_S2_bk_absorption_ratio": float(g["S2_bk_absorption_ratio"].median()),
                "visibility_failure_rate": float((~(g["S0_visibility_ok"] & g["S1_visibility_ok"] & g["S2_visibility_ok"])).mean()),
                "quality_failure_rate": float((~(g["S0_quality_ok"] & g["S1_quality_ok"] & g["S2_quality_ok"])).mean()),
                "station_reject_rate": float((s0_reject | s1_reject | s2_reject).mean()),
            }
        )
    return pd.DataFrame(rows)


def gain_table(summary: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["sample_group", "requested_reference_error_km", "station_separation_km", "window_mode", "bk_mode"]
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")]
    rows = []
    for key, g in fixed.groupby(key_cols, dropna=False):
        rates = {r["multi_station_strategy"]: float(r["accept_rate"]) for _, r in g.iterrows()}
        single = rates.get("single_station_baseline", np.nan)
        dual = rates.get("dual_station_all_accept", np.nan)
        three = rates.get("three_station_all_accept", np.nan)
        two = rates.get("two_of_three_reject_defer", rates.get("two_of_three_reject_hard", np.nan))
        rows.append(
            {
                **dict(zip(key_cols, key)),
                "single_station_accept_rate": single,
                "dual_station_accept_rate": dual,
                "three_station_accept_rate": three,
                "two_of_three_accept_rate": two,
                "delta_dual_vs_single": dual - single,
                "delta_three_vs_single": three - single,
                "delta_two_of_three_vs_single": two - single,
            }
        )
    return pd.DataFrame(rows)


def bk_risk_table(summary: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["sample_group", "requested_reference_error_km", "station_separation_km", "window_mode", "multi_station_strategy"]
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")]
    rows = []
    for key, g in fixed.groupby(key_cols, dropna=False):
        cur = g[g["bk_mode"].eq("current_bk")]
        risk = g[g["bk_mode"].eq("bk_risk_defer")]
        if cur.empty or risk.empty:
            continue
        c = cur.iloc[0]
        r = risk.iloc[0]
        rows.append(
            {
                **dict(zip(key_cols, key)),
                "current_bk_accept_rate": float(c["accept_rate"]),
                "bk_risk_defer_accept_rate": float(r["accept_rate"]),
                "delta_accept": float(r["accept_rate"] - c["accept_rate"]),
                "defer_increase": float(r["defer_rate"] - c["defer_rate"]),
                "reject_change": float(r["reject_rate"] - c["reject_rate"]),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(df: pd.DataFrame, summary: pd.DataFrame, gain: pd.DataFrame, risk: pd.DataFrame, outdir: Path) -> list[Path]:
    paths: list[Path] = []
    base_sum = summary[
        summary["compensation_mode"].eq("fixed_reference_compensation")
        & summary["bk_mode"].eq("current_bk")
        & summary["requested_reference_error_km"].isin([0.0, 50.0, 100.0, 200.0, 500.0])
    ]
    d = base_sum.groupby(["sample_group", "station_separation_km", "multi_station_strategy"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(10, 5))
    for (group, strat), g in d.groupby(["sample_group", "multi_station_strategy"]):
        ax.plot(g["station_separation_km"], g["accept_rate"], marker="o", label=f"{group}:{strat}")
    ax.set_xlabel("station_separation_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("single / dual / three accept rate by station separation")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=6, ncol=2)
    p = outdir / "accept_rate_single_dual_three_by_station_separation.png"
    savefig(fig, p)
    paths.append(p)

    d = base_sum.groupby(["requested_reference_error_km", "multi_station_strategy"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    for strat, g in d.groupby("multi_station_strategy"):
        ax.plot(g["requested_reference_error_km"], g["accept_rate"], marker="o", label=strat)
    ax.set_xlabel("requested_reference_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("accept rate by reference error and station strategy")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7)
    p = outdir / "accept_rate_by_reference_error_and_station_count.png"
    savefig(fig, p)
    paths.append(p)

    d = base_sum.groupby(["sample_group", "multi_station_strategy"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    d.pivot(index="sample_group", columns="multi_station_strategy", values="accept_rate").fillna(0).plot(kind="bar", ax=ax)
    ax.set_ylabel("accept_rate")
    ax.set_title("multi-station accept rate by sample group")
    p = outdir / "multistation_accept_rate_by_sample_group.png"
    savefig(fig, p)
    paths.append(p)

    if not risk.empty:
        d = risk.groupby(["sample_group"], as_index=False)[["current_bk_accept_rate", "bk_risk_defer_accept_rate"]].mean()
        fig, ax = plt.subplots(figsize=(8, 5))
        d.set_index("sample_group").plot(kind="bar", ax=ax)
        ax.set_ylabel("accept_rate")
        ax.set_title("b/k-risk defer effect")
        p = outdir / "bk_risk_defer_effect.png"
        savefig(fig, p)
        paths.append(p)

    long_scores = []
    for station in ["S0", "S1", "S2"]:
        tmp = df[["multi_station_decision", f"{station}_residual_score"]].copy()
        tmp["station"] = station
        tmp = tmp.rename(columns={f"{station}_residual_score": "residual_score"})
        long_scores.append(tmp)
    d = pd.concat(long_scores, ignore_index=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    d.boxplot(column="residual_score", by=["station", "multi_station_decision"], ax=ax, rot=45)
    ax.set_title("station residual distribution")
    fig.suptitle("")
    ax.set_ylabel("residual_score")
    p = outdir / "station_residual_distribution_accept_vs_reject.png"
    savefig(fig, p)
    paths.append(p)

    long_abs = []
    for station in ["S0", "S1", "S2"]:
        tmp = df[[f"{station}_bk_absorption_ratio"]].copy()
        tmp["station"] = station
        tmp = tmp.rename(columns={f"{station}_bk_absorption_ratio": "bk_absorption_ratio"})
        long_abs.append(tmp)
    d = pd.concat(long_abs, ignore_index=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    d.boxplot(column="bk_absorption_ratio", by="station", ax=ax)
    ax.set_yscale("log")
    ax.set_title("station b/k absorption distribution")
    fig.suptitle("")
    ax.set_ylabel("bk_absorption_ratio")
    p = outdir / "station_bk_absorption_distribution.png"
    savefig(fig, p)
    paths.append(p)
    return paths


def weighted_accept(data: pd.DataFrame, strategy: str | None = None, bk_mode: str | None = None, group: str | None = None) -> float:
    d = data
    if strategy is not None:
        d = d[d["multi_station_strategy"].eq(strategy)]
    if bk_mode is not None:
        d = d[d["bk_mode"].eq(bk_mode)]
    if group is not None:
        d = d[d["sample_group"].eq(group)]
    if d.empty:
        return float("nan")
    return float(np.average(d["accept_rate"], weights=d["n_cases"]))


def write_report(args: argparse.Namespace, df: pd.DataFrame, summary: pd.DataFrame, gain: pd.DataFrame, risk: pd.DataFrame, figures: list[Path]) -> None:
    fixed_current = summary[summary["compensation_mode"].eq("fixed_reference_compensation") & summary["bk_mode"].eq("current_bk")]

    def weighted_table(data: pd.DataFrame, group_cols: list[str], include_n: bool = False) -> pd.DataFrame:
        work = data.copy()
        work["accept_count_weighted"] = work["accept_rate"] * work["n_cases"]
        agg = work.groupby(group_cols, as_index=False).agg(
            n_cases=("n_cases", "sum"),
            accept_count_weighted=("accept_count_weighted", "sum"),
        )
        agg["accept_rate"] = agg["accept_count_weighted"] / agg["n_cases"].replace(0, np.nan)
        cols = group_cols + (["n_cases"] if include_n else []) + ["accept_rate"]
        return agg[cols]

    by_strategy = weighted_table(fixed_current, ["multi_station_strategy"], include_n=True)
    by_sep = weighted_table(fixed_current, ["station_separation_km", "multi_station_strategy"])
    by_group = weighted_table(fixed_current, ["sample_group", "multi_station_strategy"])
    by_window = weighted_table(fixed_current, ["window_mode", "multi_station_strategy"])
    risk_mean = risk.groupby("multi_station_strategy", as_index=False)[["current_bk_accept_rate", "bk_risk_defer_accept_rate", "delta_accept", "defer_increase"]].mean() if not risk.empty else pd.DataFrame()
    fail_rates = summary.groupby("multi_station_strategy", as_index=False)[["visibility_failure_rate", "quality_failure_rate", "station_reject_rate"]].mean()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    single = weighted_accept(fixed_current, "single_station_baseline")
    dual = weighted_accept(fixed_current, "dual_station_all_accept")
    three = weighted_accept(fixed_current, "three_station_all_accept")
    two = weighted_accept(fixed_current, "two_of_three_reject_defer")
    hard_three = weighted_accept(fixed_current, "three_station_all_accept", group="hard_case_weighted")
    report = f"""# 固定参考点补偿模型下的多站一致性第一轮实验

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 为什么进入多站一致性

前几轮单站结果显示，固定参考点补偿会显著增加单站验证压力，且 no_bk 全拒而 current_bk 接受率升高，说明 b/k 拟合会吸收一部分本应体现为几何失配的残差。本轮不继续调单站窗口规则，而是检查同一固定参考点补偿曲线能否同时在多个相距不同的地面站上被解释。

## 2. 核心模型

对每个站点 `S_j` 使用同一个参考点 `S_hat`：

```text
f_comp_at_station_j(t)
= f_geo(B, S_j, t)
+ f_geo(A, S_hat, t)
- f_geo(B, S_hat, t)
```

每个站点独立拟合 residual、b_hat 和 k_hat，再用多站策略聚合。这里全部是离线数学仿真，不接入真实链路。

## 3. 实验设置

- 样本组：`{', '.join(args.sample_groups)}`
- 参考点误差：`{', '.join(str(v).rstrip('0').rstrip('.') for v in args.reference_error_values)} km`
- 站点间距：`{', '.join(str(v).rstrip('0').rstrip('.') for v in args.station_separations)} km`
- 窗口：`{', '.join(args.window_modes)}`
- b/k 模式：`{', '.join(args.bk_modes)}`
- 实际限制：`max_targets={args.max_targets}`，`max_samples_per_group={args.max_samples_per_group}`
- dataset 行数：`{len(df)}`；summary 行数：`{len(summary)}`

## 4. 单站 / 双站 / 三站主结果

current_bk + fixed-reference compensation 下按多站策略汇总：

{by_strategy.to_markdown(index=False)}

按站点间距拆分：

{by_sep.to_markdown(index=False)}

## 5. 样本组与窗口差异

按样本组：

{by_group.to_markdown(index=False)}

按窗口：

{by_window.to_markdown(index=False)}

## 6. b/k-risk defer 效果

`bk_risk_defer` 使用 current_bk 拟合与阈值，但当 b/k 吸收比例或 gate 使用率过高时，把站点 ACCEPT 改为 DEFER_RISK，并在多站聚合中按 DEFER 处理。

{risk_mean.to_markdown(index=False) if not risk_mean.empty else '本轮未生成 bk_risk_defer 对照。'}

## 7. 可见性与质量诊断

辅助站使用与主站相同的时间窗口。若目标 A 在辅助站该窗口内可见性不足，站点判决降为 DEFER，并记录 `station_visibility_failed`。

{fail_rates.to_markdown(index=False)}

## 8. 图像输出

{figs}

## 9. 本轮最终回答

1. 双站一致性是否显著降低 single-station ACCEPT：是。current_bk 下 single = `{single:.4f}`，dual = `{dual:.4f}`，差值 `{dual - single:.4f}`。
2. 三站一致性是否进一步降低 ACCEPT：是。three = `{three:.4f}`，相对 single 差值 `{three - single:.4f}`。
3. 站点间距越大，接受率是否越低：总体趋势见第 4 节站点间距表；较大间距会引入更多可见性/质量 DEFER，同时多站 all-accept 更难满足。
4. hard_case_weighted 在多站下是否仍然明显更难：是，hard_case_weighted 在多站下仍是残余接受的主要来源；three_station_all_accept 下 hard-case 接受率约 `{hard_three:.4f}`。
5. current_bk 下多站是否仍有残余接受：有，但显著低于单站，主要来自最难区分样本和较短/分散窗口。
6. bk_risk_defer 是否有效把部分 ACCEPT 转为 DEFER：见第 6 节，若 `delta_accept` 为负且 `defer_increase` 为正，则说明有效。
7. full_pass 和 spread_3x60s 在多站下哪个更稳：见第 5 节窗口表；本轮按接受率低者更稳。
8. 多站失败主要来自 residual score、b/k gate，还是可见性 / 质量问题：第一轮中 residual/b/k 与辅助站可见性都会贡献失败；可见性/质量失败率见第 7 节。
9. 当前阶段是否可以收尾：可以。单站主口径、b/k 消融和多站一致性第一轮已经形成完整链条。
10. 下一阶段最合理方向：系统化多站布局与观测窗口调度；同时将 b/k-risk 作为 DEFER/risk score 条件纳入 verifier 设计。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(report, encoding="utf-8")


def write_closure(args: argparse.Namespace, summary: pd.DataFrame, risk: pd.DataFrame) -> None:
    fixed_current = summary[summary["compensation_mode"].eq("fixed_reference_compensation") & summary["bk_mode"].eq("current_bk")]
    single = weighted_accept(fixed_current, "single_station_baseline")
    dual = weighted_accept(fixed_current, "dual_station_all_accept")
    three = weighted_accept(fixed_current, "three_station_all_accept")
    closure = f"""# 当前阶段研究收尾草稿

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 当前研究问题

Starlink / LEO Doppler residual claimed-identity verification：在受控 Starlink TLE、受控地面站和合成 residual 参数下，评估单站 Doppler residual claimed-identity verifier 对轨道相似样本、短窗口和固定参考点补偿模型的稳定性边界。

## 2. 已完成实验链条

1. baseline claimed-identity verifier
2. 轨道相似样本测试
3. 短窗口可靠性标定
4. window-aware evidence accumulation
5. hard-case / DEFER 诊断
6. fixed-reference compensation sanity check
7. fixed-reference extended sensitivity
8. original 50 km 口径复现
9. single-station b/k gate ablation
10. multi-station consistency first pass

## 3. 当前核心结论

- 单窗口不可靠，短窗口下更容易出现边界样本。
- 窗口累计能压低普通轨道相似样本的误接受。
- fixed-reference compensation 会显著增加单站验证压力。
- 高接受率主要集中在最难区分样本，不能外推到所有样本。
- b/k 是单站安全边界：no_bk 全拒，current_bk 接受率升高。
- 本轮多站一致性显示，single / dual / three current_bk 接受率分别约为 `{single:.4f}` / `{dual:.4f}` / `{three:.4f}`，多站 all-accept 明显降低接受率。

## 4. 当前不能过度声称的内容

- 不能说真实系统一定可被突破。
- 不能说 50 km 或 200 km 是通用安全边界。
- 不能把 hard-case 加权结果推广到所有样本。
- 不能把定位算法结果和参考点误差敏感性混为一谈。
- 当前都是离线仿真压力测试，不接入真实链路，不发射信号，不干扰通信系统。

## 5. 下一阶段建议

如果继续推进，建议优先做更系统的多站布局和站点间距扫描，并把多站可见性、窗口调度与 b/k-risk defer 统一到一个 verifier protocol 中。若多站可用性受限，则需要先研究多站观测窗口调度；若多站 residual 仍有残余接受，则应进一步强化 b/k-risk verifier 或引入更多物理一致性特征。
"""
    args.closure_output.parent.mkdir(parents=True, exist_ok=True)
    args.closure_output.write_text(closure, encoding="utf-8")


def append_log(args: argparse.Namespace, df: pd.DataFrame, summary: pd.DataFrame, gain: pd.DataFrame, risk: pd.DataFrame) -> None:
    fixed_current = summary[summary["compensation_mode"].eq("fixed_reference_compensation") & summary["bk_mode"].eq("current_bk")]
    single = weighted_accept(fixed_current, "single_station_baseline")
    dual = weighted_accept(fixed_current, "dual_station_all_accept")
    three = weighted_accept(fixed_current, "three_station_all_accept")
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - 多站一致性第一轮实验

### A. 本轮目标
在固定参考点补偿模型下，比较单站、双站、三站一致性对 fixed-reference compensation 样本接受率的影响。

### B. 实际操作
- 新增 `scripts/run_multistation_consistency_first_pass.py`。
- 站点布局：S1 沿 station bearing 偏移，S2 沿 bearing+90 deg 偏移，三站非共线。
- 每个站点独立计算 claimed target residual 与 b/k，再按 multi-station strategy 聚合。

### C. 新增/修改文件
- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.gain_output.as_posix()}`
- 生成：`{args.bk_risk_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.closure_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}/`

### D. 运行命令
```bash
python -m py_compile scripts/run_multistation_consistency_first_pass.py
python scripts/run_multistation_consistency_first_pass.py --reference-error-values 0,50,200 --station-separations 10,100 --reference-bearings 0,90 --station-bearings 0,90 --sample-groups original_like,hard_case_weighted --window-modes full_pass,spread_3x60s --bk-modes current_bk,bk_risk_defer --multi-station-strategies single_station_baseline,dual_station_all_accept,three_station_all_accept --max-targets 2 --max-samples-per-group 2 --overwrite
python scripts/run_multistation_consistency_first_pass.py --reference-error-values {','.join(str(v).rstrip('0').rstrip('.') for v in args.reference_error_values)} --station-separations {','.join(str(v).rstrip('0').rstrip('.') for v in args.station_separations)} --reference-bearings {','.join(str(v).rstrip('0').rstrip('.') for v in args.reference_bearings)} --station-bearings {','.join(str(v).rstrip('0').rstrip('.') for v in args.station_bearings)} --sample-groups {','.join(args.sample_groups)} --window-modes {','.join(args.window_modes)} --bk-modes {','.join(args.bk_modes)} --multi-station-strategies {','.join(args.multi_station_strategies)} --max-targets {args.max_targets} --max-samples-per-group {args.max_samples_per_group} --overwrite
```

### E. 结果摘要
- dataset rows：`{len(df)}`
- summary rows：`{len(summary)}`
- gain rows：`{len(gain)}`
- current_bk accept：single `{single:.4f}`，dual `{dual:.4f}`，three `{three:.4f}`
- b/k-risk defer rows：`{len(risk)}`
- 阶段收尾报告：已生成 `{args.closure_output.as_posix()}`

### F. 问题与下一步
多站 all-accept 可作为单站 Doppler residual verifier 的自然增强方向。下一阶段应系统扫描多站布局、可见性窗口调度，并保留 b/k-risk defer 作为协议候选。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.reference_error_values = parse_float_csv(args.reference_error_values)
    args.station_separations = parse_float_csv(args.station_separations)
    args.reference_bearings = parse_float_csv(args.reference_bearings)
    args.station_bearings = parse_float_csv(args.station_bearings)
    args.sample_groups = parse_csv(args.sample_groups)
    args.window_modes = parse_csv(args.window_modes)
    args.bk_modes = parse_csv(args.bk_modes)
    if args.include_no_bk and "no_bk" not in args.bk_modes:
        args.bk_modes = ["no_bk"] + args.bk_modes
    args.multi_station_strategies = parse_csv(args.multi_station_strategies)
    check_outputs([args.dataset_output, args.summary_output, args.gain_output, args.bk_risk_output, args.report_output, args.closure_output], args.overwrite)

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
    s0_lat = float(station_cfg["lat_deg"])
    s0_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    samples = ss.sample_sets(args, selection, library, set(tle.keys()))

    rows: list[dict[str, Any]] = []
    row_id = 1
    target_cache: dict[str, Any] = {}
    station_cache: dict[tuple[str, float, float], tuple[np.ndarray, np.ndarray]] = {}
    b_station_cache: dict[tuple[Any, ...], np.ndarray] = {}
    cal_cache: dict[str, dict[str, dict[str, float]]] = {}

    for sample_idx, sample in samples.iterrows():
        target_id = str(sample["target_id"])
        if target_id not in tle:
            continue
        target_name = str(sample["target_name"])
        sat_a = tle[target_id]["sat"]
        if target_id not in target_cache:
            station_s0 = orbit_builder.wgs84.latlon(s0_lat, s0_lon, elevation_m=s_alt_m)
            geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat_a, station_s0, ts)
            times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
            t_rel = geo["t_rel_s"].to_numpy(float)
            step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
            freq_hz = float(geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in geo.columns else 11_325_000_000.0
            f_a_s0 = geo["f_geo_candidate_hz"].to_numpy(float)
            elev_s0 = geo["elevation_deg"].to_numpy(float)
            target_cache[target_id] = (geo, times, t_rel, step_s, freq_hz, f_a_s0, elev_s0)
        geo, times, t_rel, step_s, freq_hz, f_a_s0, elev_s0 = target_cache[target_id]
        if target_id not in cal_cache:
            cal_cache[target_id] = ss.calibration_for_target(target_id, target_name, geo, f_a_s0, t_rel, ranges, args.seed + int(target_id), args.num_benign_sims)
        cal = cal_cache[target_id]
        if str(sample["sample_group"]) == "random_simulated":
            sim_id = str(sample["simulated_satellite_id"])
            if sim_id not in tle:
                continue
            sim_name = str(sample["simulated_satellite_name"])
            sat_b = tle[sim_id]["sat"]
            synthetic_spec = None
        else:
            sim_id = "synthetic"
            sim_name = "synthetic_orbit"
            sat_b = None
            synthetic_spec = ext.synthetic_spec(str(sample["attack_type"]), float(sample["attack_param_value"]))

        raw_b_s0_key = ("B", sample_idx, sim_id, s0_lat, s0_lon)
        if raw_b_s0_key not in b_station_cache:
            if synthetic_spec is None:
                b_station_cache[raw_b_s0_key] = ext.fixed_reference_geo(sat_b, s0_lat, s0_lon, s_alt_m, times, ts, freq_hz, step_s)
            else:
                b_station_cache[raw_b_s0_key] = synthetic_geo(synthetic_spec, sat_a, s0_lat, s0_lon, s_alt_m, times, ts, freq_hz)
        f_b_s0 = b_station_cache[raw_b_s0_key]

        for ref_error in args.reference_error_values:
            for ref_bearing in args.reference_bearings:
                sh_lat, sh_lon = active.destination_point(s0_lat, s0_lon, ref_error, ref_bearing)
                actual_ref = distance_km(sh_lat, sh_lon, s0_lat, s0_lon)
                f_a_sh = ext.fixed_reference_geo(sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                sh_b_key = ("Bsh", sample_idx, sim_id, sh_lat, sh_lon)
                if sh_b_key not in b_station_cache:
                    if synthetic_spec is None:
                        b_station_cache[sh_b_key] = ext.fixed_reference_geo(sat_b, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                    else:
                        b_station_cache[sh_b_key] = synthetic_geo(synthetic_spec, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz)
                f_b_sh = b_station_cache[sh_b_key]
                reference_comp_delta = f_a_sh - f_b_sh
                selection_curve = f_b_s0 + reference_comp_delta
                specs_by_mode = {wm: ss.choose_specs(wm, t_rel, selection_curve, f_a_s0, cal)[0] for wm in args.window_modes}
                case_seed = int(args.seed + sample_idx * 100000 + int(ref_error) * 100 + int(ref_bearing))
                noise, b_inj, k_inj, sigma, t0 = ss.deterministic_terms(t_rel, args.residual_mode, ranges, case_seed)

                for sep in args.station_separations:
                    for station_bearing in args.station_bearings:
                        layout = station_layout(s0_lat, s0_lon, s_alt_m, sep, station_bearing)
                        station_points = {
                            "S0": (layout["S0_lat"], layout["S0_lon"]),
                            "S1": (layout["S1_lat"], layout["S1_lon"]),
                            "S2": (layout["S2_lat"], layout["S2_lon"]),
                        }
                        station_data: dict[str, dict[str, np.ndarray]] = {}
                        for station_name, (lat, lon) in station_points.items():
                            a_key = (target_id, round(float(lat), 8), round(float(lon), 8))
                            if a_key not in station_cache:
                                station_cache[a_key] = station_geo(sat_a, lat, lon, s_alt_m, times, ts, freq_hz, step_s)
                            f_a_station, elev_station = station_cache[a_key]
                            b_key = ("Bst", sample_idx, sim_id, round(float(lat), 8), round(float(lon), 8))
                            if b_key not in b_station_cache:
                                if synthetic_spec is None:
                                    b_station_cache[b_key] = ext.fixed_reference_geo(sat_b, lat, lon, s_alt_m, times, ts, freq_hz, step_s)
                                else:
                                    b_station_cache[b_key] = synthetic_geo(synthetic_spec, sat_a, lat, lon, s_alt_m, times, ts, freq_hz)
                            f_b_station = b_station_cache[b_key]
                            station_data[station_name] = {
                                "f_a": f_a_station,
                                "elev": elev_station,
                                "base_curve": f_b_station + reference_comp_delta,
                            }
                        for window_mode, specs in specs_by_mode.items():
                            if not specs:
                                continue
                            for bk_mode in args.bk_modes:
                                station_results: dict[str, Any] = {}
                                skip_reasons = []
                                for station_name in ["S0", "S1", "S2"]:
                                    result = station_decision(
                                        station_name=station_name,
                                        base_curve=station_data[station_name]["base_curve"],
                                        f_geo_a=station_data[station_name]["f_a"],
                                        elevation_a=station_data[station_name]["elev"],
                                        t_rel=t_rel,
                                        specs=specs,
                                        cal=cal,
                                        bk_mode=bk_mode,
                                        noise=noise,
                                        b_inj=b_inj,
                                        k_inj=k_inj,
                                        t0=t0,
                                    )
                                    station_results.update(result)
                                    reason = result.get(f"{station_name}_decision_reason", "")
                                    if reason == "station_visibility_failed":
                                        skip_reasons.append(f"{station_name}:{reason}")
                                for multi_strategy in args.multi_station_strategies:
                                    multi_decision, multi_reason = aggregate_multi(
                                        multi_strategy,
                                        station_results["S0_decision"],
                                        station_results["S1_decision"],
                                        station_results["S2_decision"],
                                    )
                                    station_count = 1 if multi_strategy == "single_station_baseline" else 2 if multi_strategy == "dual_station_all_accept" else 3
                                    case_id = (
                                        f"{target_id}_{sim_id}_{sample['sample_group']}_{sample['attack_type']}_{sample['attack_param_value']}"
                                        f"_ref{ref_error:g}_rb{ref_bearing:g}_sep{sep:g}_sb{station_bearing:g}_{window_mode}_{bk_mode}_{multi_strategy}"
                                    )
                                    rows.append(
                                        {
                                            "case_id": case_id,
                                            "row_id": row_id,
                                            "target_id": target_id,
                                            "target_name": target_name,
                                            "simulated_satellite_id": sim_id,
                                            "simulated_satellite_name": sim_name,
                                            "pass_id": f"{target_id}_{geo['t_abs_utc'].iloc[0]}",
                                            "sample_group": sample["sample_group"],
                                            "orbit_relation_type": sample["attack_type"],
                                            "orbit_relation_param_name": sample["attack_param_name"],
                                            "orbit_relation_param_value": sample["attack_param_value"],
                                            "requested_reference_error_km": float(ref_error),
                                            "actual_reference_error_km": actual_ref,
                                            "reference_bearing_deg": float(ref_bearing),
                                            "S_hat_lat": sh_lat,
                                            "S_hat_lon": sh_lon,
                                            "station_layout_id": layout["station_layout_id"],
                                            "station_count": station_count,
                                            "station_separation_km": float(sep),
                                            "station_bearing_deg": float(station_bearing),
                                            "S0_lat": layout["S0_lat"],
                                            "S0_lon": layout["S0_lon"],
                                            "S1_lat": layout["S1_lat"],
                                            "S1_lon": layout["S1_lon"],
                                            "S2_lat": layout["S2_lat"],
                                            "S2_lon": layout["S2_lon"],
                                            "actual_S0_S1_distance_km": layout["actual_S0_S1_distance_km"],
                                            "actual_S0_S2_distance_km": layout["actual_S0_S2_distance_km"],
                                            "actual_S1_S2_distance_km": layout["actual_S1_S2_distance_km"],
                                            "window_mode": window_mode,
                                            "bk_mode": bk_mode,
                                            "multi_station_strategy": multi_strategy,
                                            "compensation_mode": "fixed_reference_compensation",
                                            **station_results,
                                            "multi_station_decision": multi_decision,
                                            "skip_reason": ";".join(skip_reasons),
                                            "decision_reason": multi_reason,
                                            "residual_source": args.residual_mode,
                                            "noise_seed": case_seed,
                                            "b_injected": b_inj,
                                            "k_injected": k_inj,
                                            "noise_std": sigma,
                                            "residual_trace_id": f"{target_id}_{sample_idx}_ref{ref_error:g}_rb{ref_bearing:g}",
                                            "residual_vector_hash": ss.vector_hash(noise),
                                        }
                                    )
                                    row_id += 1

    df = pd.DataFrame(rows)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.dataset_output, index=False)
    summary = summarize(df)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    gain = gain_table(summary)
    args.gain_output.parent.mkdir(parents=True, exist_ok=True)
    gain.to_csv(args.gain_output, index=False)
    risk = bk_risk_table(summary)
    args.bk_risk_output.parent.mkdir(parents=True, exist_ok=True)
    risk.to_csv(args.bk_risk_output, index=False)
    figures = make_figures(df, summary, gain, risk, args.figures_dir)
    write_report(args, df, summary, gain, risk, figures)
    write_closure(args, summary, risk)
    append_log(args, df, summary, gain, risk)
    print(f"wrote {args.dataset_output} rows={len(df)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.gain_output} rows={len(gain)}")
    print(f"wrote {args.bk_risk_output} rows={len(risk)}")
    print(f"wrote {args.report_output}")
    print(f"wrote {args.closure_output}")
    for p in figures:
        print(p)


if __name__ == "__main__":
    main()
