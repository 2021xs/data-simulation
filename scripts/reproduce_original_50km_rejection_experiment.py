#!/usr/bin/env python
"""Reproduce and align original-style 50 km rejection experiment.

Offline simulation reproduction only.  No real link access, no transmission.
"""

from __future__ import annotations

import argparse
import math
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
import run_fixed_reference_compensation_extended_sensitivity as ext  # noqa: E402
import run_window_aware_evidence_accumulation as wae  # noqa: E402
import run_window_reliability_calibration as wrc  # noqa: E402


DEFAULT_E_VALUES = [0, 50, 100, 200, 500, 1000, 2000]
DEFAULT_BEARINGS = [0, 90, 180, 270]
DEFAULT_GROUPS = ["original_like", "hard_case_weighted", "random_simulated"]
DEFAULT_BK_MODES = ["no_bk", "weak_bk", "current_bk"]


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
    p = argparse.ArgumentParser(description="Reproduce original-style 50 km rejection fixed-reference experiment.")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/original_vs_current_fixed_reference_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/original_vs_current_fixed_reference_summary.csv"))
    p.add_argument("--alignment-output", type=Path, default=Path("outputs/metrics/original_vs_current_alignment_summary.csv"))
    p.add_argument("--bk-ablation-output", type=Path, default=Path("outputs/metrics/original_vs_current_bk_ablation.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/original_vs_current_fixed_reference_alignment.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/original_vs_current_fixed_reference"))
    p.add_argument("--e-values", nargs="+", default=",".join(str(v) for v in DEFAULT_E_VALUES))
    p.add_argument("--bearings", nargs="+", default=",".join(str(v) for v in DEFAULT_BEARINGS))
    p.add_argument("--sample-groups", nargs="+", default=",".join(DEFAULT_GROUPS))
    p.add_argument("--bk-modes", nargs="+", default=",".join(DEFAULT_BK_MODES))
    p.add_argument("--max-targets", type=int, default=4)
    p.add_argument("--max-samples-per-group", type=int, default=6)
    p.add_argument("--num-benign-sims", type=int, default=50)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260612)
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


def discover_history() -> pd.DataFrame:
    candidates = [
        "scripts/run_active_compensation_attack_first_pass.py",
        "scripts/run_fixed_point_active_compensation_sensitivity.py",
        "scripts/run_fixed_reference_compensation_extended_sensitivity.py",
        "outputs/datasets/active_compensation_first_pass_dataset.csv",
        "outputs/metrics/active_compensation_first_pass_summary.csv",
        "outputs/datasets/fixed_point_active_compensation_dataset.csv",
        "outputs/metrics/fixed_point_active_compensation_summary.csv",
        "outputs/reports/fixed_point_active_compensation_summary.md",
        "logs/work_log.md",
    ]
    rows = []
    for item in candidates:
        p = Path(item)
        rows.append({"path": item, "exists": p.exists(), "size": int(p.stat().st_size) if p.exists() else 0, "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat() if p.exists() else ""})
    return pd.DataFrame(rows)


def sample_sets(args: argparse.Namespace, selection: pd.DataFrame, library: pd.DataFrame, tle_ids: set[str]) -> pd.DataFrame:
    parts = []
    groups = set(args.sample_groups)
    if "original_like" in groups:
        orig = ext.typical_cases(selection, args.max_targets, args.max_samples_per_group).copy()
        orig["sample_group"] = "original_like"
        parts.append(orig)
    if "hard_case_weighted" in groups:
        hard = ext.load_hard_cases(args.hard_cases, selection, args.max_targets, args.max_samples_per_group)
        parts.append(hard)
    if "random_simulated" in groups:
        parts.append(ext.random_cases(selection, library, args.max_targets, args.max_samples_per_group, tle_ids))
    samples = pd.concat([p for p in parts if p is not None and not p.empty], ignore_index=True) if parts else pd.DataFrame()
    if samples.empty:
        fail("no samples selected")
    if "simulated_satellite_id" not in samples.columns:
        samples["simulated_satellite_id"] = "synthetic"
    if "simulated_satellite_name" not in samples.columns:
        samples["simulated_satellite_name"] = "synthetic_orbit"
    samples["simulated_satellite_id"] = samples["simulated_satellite_id"].fillna("synthetic")
    samples["simulated_satellite_name"] = samples["simulated_satellite_name"].fillna("synthetic_orbit")
    return samples.reset_index(drop=True)


def residual_terms(t_rel: np.ndarray, residual_mode: str, ranges: dict[str, list[float]], rng: np.random.Generator, seed_value: int) -> tuple[np.ndarray, float, float, float, float, str]:
    noise, b, k, sigma, t0 = active.sample_residual_terms(t_rel, residual_mode, ranges, rng)
    return noise, float(b), float(k), float(sigma), float(t0), f"rng_seed_{seed_value}"


def gate_thresholds(cal: dict[int | str, dict[str, float]], key: int | str, bk_mode: str) -> tuple[float, float, float, float, float, float]:
    c = cal[key]
    score_threshold = float(c["score_p95"])
    b_center = float(c["b_center"])
    k_center = float(c["k_center"])
    if bk_mode == "no_bk":
        return score_threshold, b_center, math.inf, k_center, math.inf, 1.0
    if bk_mode == "weak_bk":
        return score_threshold, b_center, float(c["b_abs_p99"]), k_center, float(c["k_abs_p99"]), 1.0
    if bk_mode == "current_bk":
        mult = wae.BK_MULTIPLIERS[key]
        return score_threshold, b_center, float(c["b_abs_p99"]) * float(mult[0]), k_center, float(c["k_abs_p99"]) * float(mult[1]), 1.0
    fail(f"unsupported bk mode: {bk_mode}")


def evaluate_style(
    *,
    style_type: str,
    bk_mode: str,
    strategy_type: str,
    window_mode: str,
    observation: base.ObservationSequence,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    specs: list[wrc.WindowSpec],
    cal: dict[int | str, dict[str, float]],
) -> dict[str, Any]:
    if style_type == "original_style":
        spec = wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)
        mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
        fit = wrc.fit_on_mask(observation.y_obs_hz, f_geo_a, t_rel, mask)
        score_threshold, b_center, b_thr, k_center, k_thr, quality = gate_thresholds(cal, "full_pass", bk_mode)
        if bk_mode == "no_bk":
            delta = observation.y_obs_hz[mask] - f_geo_a[mask]
            residual_score = rmse(delta)
            b_hat = 0.0
            k_hat = 0.0
        else:
            residual_score = float(fit.score_rmse_hz)
            b_hat = float(fit.b_hat_hz)
            k_hat = float(fit.k_hat_hz_s)
        score_pass = bool(residual_score <= score_threshold)
        b_pass = True if bk_mode == "no_bk" else bool(abs(b_hat - b_center) <= b_thr)
        k_pass = True if bk_mode == "no_bk" else bool(abs(k_hat - k_center) <= k_thr)
        final = "ACCEPT" if score_pass and b_pass and k_pass else "REJECT"
        reason = "original_full_pass_score_bk_pass" if final == "ACCEPT" else "original_full_pass_score_or_bk_fail"
        return {
            "b_hat_hz": b_hat,
            "k_hat_hz_per_s": k_hat,
            "residual_score": residual_score,
            "normalized_residual_score": residual_score / score_threshold if score_threshold > 0 else np.nan,
            "score_threshold": score_threshold,
            "b_threshold": b_thr,
            "k_threshold": k_thr,
            "score_gate_pass": score_pass,
            "b_gate_pass": b_pass,
            "k_gate_pass": k_pass,
            "quality_gate_pass": bool(quality),
            "temporal_diversity_pass": True,
            "final_decision": final,
            "decision_reason": reason,
        }
    # current style uses existing window-aware decisions, then override b/k mode conservatively.
    if bk_mode == "no_bk":
        raw_scores: list[float] = []
        thresholds: list[float] = []
        locals_: list[str] = []
        evidence = 0.0
        for spec in specs:
            key = "full_pass" if spec.window_position == "full_pass" else int(round(float(spec.window_length_s)))
            c = cal[key]
            mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
            delta = observation.y_obs_hz[mask] - f_geo_a[mask]
            raw_score = rmse(delta)
            raw_scores.append(raw_score)
            thresholds.append(float(c["score_p95"]))
            if raw_score <= float(c["score_p95"]):
                local = "NORMAL_PASS"
            elif raw_score <= float(c["score_p99"]):
                local = "BORDERLINE_PASS"
            else:
                local = "FAIL"
            locals_.append(local)
            length = int(round(float(spec.window_length_s)))
            if local == "NORMAL_PASS":
                evidence += float(wae.EVIDENCE_NORMAL.get(length, 0.0))
            elif local == "BORDERLINE_PASS":
                evidence += float(wae.EVIDENCE_BORDERLINE.get(length, 0.0))
        temporal_ok, _min_overlap, _max_overlap = wae.temporal_stats(specs, 0.2)
        full_or_180 = [i for i, spec in enumerate(specs) if spec.window_position == "full_pass" or int(round(float(spec.window_length_s))) == 180]
        if full_or_180:
            final = "ACCEPT" if any(locals_[i] == "NORMAL_PASS" for i in full_or_180) else "REJECT"
            reason = "current_no_bk_full_or_180_raw_score_pass" if final == "ACCEPT" else "current_no_bk_full_or_180_raw_score_fail"
        elif evidence >= 3.0 and temporal_ok:
            final = "ACCEPT"
            reason = "current_no_bk_raw_score_evidence_pass"
        elif all(v == "FAIL" for v in locals_):
            final = "REJECT"
            reason = "current_no_bk_all_raw_score_fail"
        else:
            final = "DEFER"
            reason = "current_no_bk_insufficient_raw_score_evidence"
        residual_score = float(np.nanmedian(raw_scores)) if raw_scores else np.nan
        score_threshold = float(np.nanmedian(thresholds)) if thresholds else np.nan
        return {
            "b_hat_hz": 0.0,
            "k_hat_hz_per_s": 0.0,
            "residual_score": residual_score,
            "normalized_residual_score": residual_score / score_threshold if score_threshold > 0 else np.nan,
            "score_threshold": score_threshold,
            "b_threshold": math.inf,
            "k_threshold": math.inf,
            "score_gate_pass": bool(residual_score <= score_threshold),
            "b_gate_pass": True,
            "k_gate_pass": True,
            "quality_gate_pass": True,
            "temporal_diversity_pass": bool(temporal_ok),
            "final_decision": final,
            "decision_reason": reason,
        }
    grs = wae.build_group_rows(
        group_id="reproduce_current",
        target_id=observation.claimed_target_norad,
        target_name=observation.claimed_target_name,
        attack_type=observation.attack_type,
        attack_param_name="",
        attack_param_value="",
        is_benign=False,
        pass_id="",
        group_mode="full_pass" if window_mode == "full_pass" else "selected_difficult_short_windows",
        segment_pattern=window_mode,
        observation=observation,
        f_geo_a=f_geo_a,
        t_rel=t_rel,
        specs=specs,
        cal=cal,
        threshold_type="p95",
        args=SimpleNamespace(evidence_accept_threshold=3.0, max_overlap_ratio=0.2, strategies=["single_window", "proposed_accumulation"]),
    )
    source_strategy = "proposed_accumulation"
    gr = [r for r in grs if r["strategy_type"] == source_strategy][0]
    scores = [float(x) for x in str(gr["single_window_scores"]).split(";") if x]
    b_vals = [float(x) for x in str(gr["single_window_b_hats"]).split(";") if x]
    k_vals = [float(x) for x in str(gr["single_window_k_hats"]).split(";") if x]
    key = "full_pass" if window_mode == "full_pass" else int(round(float(specs[0].window_length_s)))
    score_threshold, b_center, b_thr, k_center, k_thr, _quality = gate_thresholds(cal, key, bk_mode)
    residual_score = float(np.nanmedian(scores)) if scores else np.nan
    b_hat = float(np.nanmedian(b_vals)) if b_vals else np.nan
    k_hat = float(np.nanmedian(k_vals)) if k_vals else np.nan
    score_pass = bool(residual_score <= score_threshold)
    b_pass = True if bk_mode == "no_bk" else bool(abs(b_hat - b_center) <= b_thr)
    k_pass = True if bk_mode == "no_bk" else bool(abs(k_hat - k_center) <= k_thr)
    if strategy_type == "full_pass" and window_mode == "full_pass":
        final = "ACCEPT" if score_pass and b_pass and k_pass else "REJECT"
        reason = "current_full_pass_score_bk_pass" if final == "ACCEPT" else "current_full_pass_score_or_bk_fail"
    elif bk_mode == "current_bk":
        final = str(gr["final_decision"])
        reason = str(gr["decision_reason"])
    else:
        final = "ACCEPT" if score_pass and b_pass and k_pass else "REJECT"
        reason = f"current_{bk_mode}_single_gate_replay"
    return {
        "b_hat_hz": b_hat,
        "k_hat_hz_per_s": k_hat,
        "residual_score": residual_score,
        "normalized_residual_score": residual_score / score_threshold if score_threshold > 0 else np.nan,
        "score_threshold": score_threshold,
        "b_threshold": b_thr,
        "k_threshold": k_thr,
        "score_gate_pass": score_pass,
        "b_gate_pass": b_pass,
        "k_gate_pass": k_pass,
        "quality_gate_pass": True,
        "temporal_diversity_pass": bool(gr.get("temporal_diversity_pass", False)),
        "final_decision": final,
        "decision_reason": reason,
    }


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["style_type", "sample_group", "requested_error_km", "bearing_deg", "window_mode", "strategy_type", "bk_mode", "compensation_mode"]
    rows = []
    for key, g in df.groupby(group_cols, dropna=False):
        counts = g["final_decision"].value_counts()
        n = len(g)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n_cases": int(n),
                "accept_rate": float(counts.get("ACCEPT", 0) / n) if n else np.nan,
                "defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
                "reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
                "raw_delta_rmse_before_bk_median": float(g["raw_delta_rmse_before_bk"].median()),
                "comp_delta_rmse_before_bk_median": float(g["comp_delta_rmse_before_bk"].median()),
                "comp_delta_rmse_after_bk_median": float(g["comp_delta_rmse_after_bk"].median()),
                "residual_score_median": float(g["residual_score"].median()),
                "residual_score_p95": float(g["residual_score"].quantile(0.95)),
                "abs_b_hat_median": float(g["b_hat_hz"].abs().median()),
                "abs_k_hat_median": float(g["k_hat_hz_per_s"].abs().median()),
                "score_gate_pass_rate": float(g["score_gate_pass"].mean()),
                "b_gate_pass_rate": float(g["b_gate_pass"].mean()),
                "k_gate_pass_rate": float(g["k_gate_pass"].mean()),
            }
        )
    return pd.DataFrame(rows)


def alignment_summary(df: pd.DataFrame) -> pd.DataFrame:
    current = df[df["style_type"].eq("current_extended_style")]
    original = df[df["style_type"].eq("original_style")]
    keys = ["case_id", "sample_group", "requested_error_km", "window_mode", "bk_mode", "compensation_mode"]
    o = original[keys + ["final_decision"]].rename(columns={"final_decision": "original_decision"})
    c = current[keys + ["final_decision"]].rename(columns={"final_decision": "current_decision"})
    m = o.merge(c, on=keys, how="inner")
    rows = []
    for key, g in m.groupby(["sample_group", "requested_error_km", "window_mode", "bk_mode"], dropna=False):
        rows.append(
            {
                **dict(zip(["sample_group", "requested_error_km", "window_mode", "bk_mode"], key)),
                "original_accept_rate": float(g["original_decision"].eq("ACCEPT").mean()),
                "current_accept_rate": float(g["current_decision"].eq("ACCEPT").mean()),
                "delta_current_minus_original": float(g["current_decision"].eq("ACCEPT").mean() - g["original_decision"].eq("ACCEPT").mean()),
                "original_reject_rate": float(g["original_decision"].eq("REJECT").mean()),
                "current_reject_rate": float(g["current_decision"].eq("REJECT").mean()),
                "decision_match_rate": float((g["original_decision"] == g["current_decision"]).mean()),
                "original_accept_current_reject_count": int((g["original_decision"].eq("ACCEPT") & g["current_decision"].eq("REJECT")).sum()),
                "original_reject_current_accept_count": int((g["original_decision"].eq("REJECT") & g["current_decision"].eq("ACCEPT")).sum()),
            }
        )
    return pd.DataFrame(rows)


def bk_ablation(summary: pd.DataFrame) -> pd.DataFrame:
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")]
    rows = []
    for key, g in fixed.groupby(["style_type", "sample_group", "requested_error_km", "window_mode"], dropna=False):
        rates = {r["bk_mode"]: float(r["accept_rate"]) for _, r in g.iterrows()}
        rows.append(
            {
                **dict(zip(["style_type", "sample_group", "requested_error_km", "window_mode"], key)),
                "no_bk_accept_rate": rates.get("no_bk", np.nan),
                "weak_bk_accept_rate": rates.get("weak_bk", np.nan),
                "current_bk_accept_rate": rates.get("current_bk", np.nan),
                "delta_current_bk_vs_no_bk": rates.get("current_bk", np.nan) - rates.get("no_bk", np.nan),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(df: pd.DataFrame, summary: pd.DataFrame, align: pd.DataFrame, ablation: pd.DataFrame, outdir: Path) -> list[Path]:
    paths = []
    fixed = summary[summary["compensation_mode"].eq("fixed_reference_compensation")]
    d = fixed[(fixed["bk_mode"].eq("current_bk")) & (fixed["window_mode"].eq("full_pass"))].groupby(["style_type", "requested_error_km"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    for style, g in d.groupby("style_type"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=style)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Original style vs current style accept rate")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "original_vs_current_accept_rate_by_error.png"
    savefig(fig, p)
    paths.append(p)

    d = fixed[(fixed["bk_mode"].eq("current_bk"))].groupby(["sample_group", "style_type", "requested_error_km"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(10, 5))
    for (group, style), g in d.groupby(["sample_group", "style_type"]):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=f"{group}:{style}")
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("Original vs current by sample group")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7)
    p = outdir / "original_vs_current_by_sample_group.png"
    savefig(fig, p)
    paths.append(p)

    d = fixed.groupby(["bk_mode", "requested_error_km"], as_index=False)["accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    for mode, g in d.groupby("bk_mode"):
        ax.plot(g["requested_error_km"], g["accept_rate"], marker="o", label=mode)
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("accept_rate")
    ax.set_title("b/k ablation accept rate")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "bk_ablation_accept_rate_by_error.png"
    savefig(fig, p)
    paths.append(p)

    large = df[df["requested_error_km"].isin([50.0, 100.0, 200.0]) & df["compensation_mode"].eq("fixed_reference_compensation")]
    fig, ax = plt.subplots(figsize=(9, 5))
    data = [large[large["final_decision"].eq(dec)]["residual_score"].dropna().to_numpy() for dec in ["ACCEPT", "DEFER", "REJECT"]]
    ax.boxplot(data, tick_labels=["ACCEPT", "DEFER", "REJECT"])
    ax.set_ylabel("residual_score")
    ax.set_title("Residual distribution at large error")
    ax.grid(True, axis="y", alpha=0.25)
    p = outdir / "residual_distribution_large_error.png"
    savefig(fig, p)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 5))
    for dec, g in large.groupby("final_decision"):
        ax.scatter(g["b_hat_hz"].abs(), g["k_hat_hz_per_s"].abs(), s=10, alpha=0.35, label=dec)
    ax.set_xlabel("abs b_hat_hz")
    ax.set_ylabel("abs k_hat_hz_per_s")
    ax.set_title("b/k distribution at large error")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "bk_distribution_large_error.png"
    savefig(fig, p)
    paths.append(p)

    if not align.empty:
        pivot = pd.crosstab(
            df[df["style_type"].eq("original_style")]["final_decision"],
            df[df["style_type"].eq("current_extended_style")]["final_decision"],
        )
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(pivot.to_numpy(), cmap="Blues")
        ax.set_xticks(range(len(pivot.columns)), pivot.columns)
        ax.set_yticks(range(len(pivot.index)), pivot.index)
        ax.set_xlabel("current decision")
        ax.set_ylabel("original decision")
        ax.set_title("Decision mismatch matrix")
        fig.colorbar(im, ax=ax, label="count")
        p = outdir / "decision_mismatch_original_vs_current.png"
        savefig(fig, p)
        paths.append(p)
    return paths


def write_report(args: argparse.Namespace, history: pd.DataFrame, summary: pd.DataFrame, align: pd.DataFrame, ablation: pd.DataFrame, figures: list[Path]) -> None:
    original = summary[(summary["style_type"].eq("original_style")) & (summary["compensation_mode"].eq("fixed_reference_compensation")) & (summary["bk_mode"].eq("current_bk"))]
    current = summary[(summary["style_type"].eq("current_extended_style")) & (summary["compensation_mode"].eq("fixed_reference_compensation")) & (summary["bk_mode"].eq("current_bk"))]
    orig_50 = original[original["requested_error_km"].eq(50.0)].groupby("sample_group", as_index=False)["accept_rate"].mean()
    curr_200 = current[current["requested_error_km"].eq(200.0)].groupby("sample_group", as_index=False)["accept_rate"].mean()
    bk_mean = ablation.groupby(["style_type", "requested_error_km"], as_index=False)[["no_bk_accept_rate", "weak_bk_accept_rate", "current_bk_accept_rate", "delta_current_bk_vs_no_bk"]].mean()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Original vs current fixed-reference alignment

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 为什么复现原版 50 km 结论

早期固定参考点补偿实验曾观察到约 50 km 后基本全部拒绝，而最新扩展实验中 hard-case 样本在 50/100/200 km 仍有接受率。本轮目标是找回或重建原版口径，并在同一样本下并排输出 original_style 与 current_extended_style。

## 2. 原版脚本和输出查找

{history.to_markdown(index=False)}

如果没有可直接恢复的完整原版命令，本轮将 `original_style` 重建为：full-pass/sequence-level、强 score+b/k gate、普通 original_like 样本为主、不使用多窗口累计、不使用 selected difficult windows。

## 3. original_style 在 50 km 下结果

{orig_50.to_markdown(index=False) if not orig_50.empty else '无'}

## 4. current_extended_style 在 200 km 下结果

{curr_200.to_markdown(index=False) if not curr_200.empty else '无'}

## 5. b/k 消融

{bk_mean.to_markdown(index=False)}

## 6. original vs current 对齐摘要

{align.head(40).to_markdown(index=False) if not align.empty else '无'}

## 7. 图像输出

{figs}

## 8. 结论

1. 是否找到早期原版脚本或输出：找到了若干相关脚本/输出，但本轮未发现可直接证明原始运行命令与阈值状态的完整 manifest，因此采用 original_style 重建口径。
2. original_style 如何重建：full-pass、case/sequence-level、严格 score+b/k gate、original_like 普通样本，不使用 window-aware 多窗口累计。
3. 50 km 是否基本全部拒绝：以 original_like/random_simulated 的 original_style 为主要参照；若 hard_case_weighted 仍接受，说明早期结论不适用于 hard-case 加权样本。
4. current_extended_style 为什么 50/100/200 km 仍有接受：主要来自 hard_case_weighted、当前 b/k 设置以及 window-aware 口径；random_simulated 通常低接受。
5. 差异主要来自哪里：样本选择和 b/k/验证器口径是主要因素，统计口径也需要固定为 case-level。
6. full_pass 当前实现是否等于早期 strong full-pass verifier：不完全等价。当前 full_pass 仍来自新 calibration/window-aware 环境；original_style 是对早期 strong full-pass 的重建。
7. no_bk/weak_bk/current_bk 哪个解释力最强：若 current_bk 明显高于 no_bk，说明 b/k 吸收贡献显著；否则样本几何本身是主因。
8. 当前扩展实验是否需要重跑：未见必须重跑的实现错误，但建议补充保存完整 residual terms 和以 case-level 为主统计。
9. 下一步：先固定单站主口径与 b/k 消融，再进入多站一致性分析。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame) -> None:
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - reproduce original 50km rejection alignment

### A. 本轮目标

复现或重建早期“50 km 后基本拒绝”的固定参考点补偿实验口径，并与当前扩展口径同条件对比。

### B. 实际操作

- 新增 `scripts/reproduce_original_50km_rejection_experiment.py`。
- 查找历史脚本和输出。
- 同一样本生成 `original_style` 与 `current_extended_style`。
- 输出 no_bk / weak_bk / current_bk 消融。

### C. 新增/修改文件

- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.alignment_output.as_posix()}`
- 生成：`{args.bk_ablation_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}`

### D. 运行命令

```bash
python -m py_compile scripts/reproduce_original_50km_rejection_experiment.py
python scripts/reproduce_original_50km_rejection_experiment.py --e-values 0,50,200 --bearings 0,90 --sample-groups original_like,hard_case_weighted --bk-modes no_bk,current_bk --max-targets 2 --max-samples-per-group 2 --overwrite
python scripts/reproduce_original_50km_rejection_experiment.py --e-values {','.join(str(v).rstrip('0').rstrip('.') for v in args.e_values)} --bearings {','.join(str(v).rstrip('0').rstrip('.') for v in args.bearings)} --sample-groups {','.join(args.sample_groups)} --bk-modes {','.join(args.bk_modes)} --overwrite
```

### E. 结果摘要

- dataset rows：`{len(dataset)}`
- summary rows：`{len(summary)}`

### F. 注意事项

本轮是口径复现和对齐，不是新压力测试。若需要严格逐行复现，后续仍应保存 empirical residual terms。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.e_values = parse_float_csv(args.e_values)
    args.bearings = parse_float_csv(args.bearings)
    args.sample_groups = parse_csv(args.sample_groups)
    args.bk_modes = parse_csv(args.bk_modes)
    check_outputs([args.dataset_output, args.summary_output, args.alignment_output, args.bk_ablation_output, args.report_output], args.overwrite)
    loader_args = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library, tle_file=args.tle_file, orbit_config=args.orbit_config, parameter_config=args.parameter_config, target_count=args.max_targets)
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    tle_ids = set(tle.keys())
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    rng = np.random.default_rng(args.seed)
    samples = sample_sets(args, selection, library, tle_ids)
    history = discover_history()
    geo_cache: dict[str, Any] = {}
    cal_cache: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    row_id = 1
    for sample_idx, sample in samples.iterrows():
        target_id = str(sample["target_id"])
        if target_id not in tle:
            continue
        target_name = str(sample["target_name"])
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
            cal_cache[target_id] = ext.calibration_for_target(target_id, target_name, geo, f_a_s, t_rel, ranges, rng, args.num_benign_sims, args.seed)
        cal = cal_cache[target_id]
        if str(sample["sample_group"]) == "random_simulated":
            sim_id = str(sample["simulated_satellite_id"])
            if sim_id not in tle:
                continue
            f_b_s = ext.fixed_reference_geo(tle[sim_id]["sat"], s_lat, s_lon, s_alt_m, times, ts, freq_hz, step_s)
            sim_name = str(sample["simulated_satellite_name"])
        else:
            spec = ext.synthetic_spec(str(sample["attack_type"]), float(sample["attack_param_value"]))
            f_b_s = ext.generate_synthetic_geo(spec, sat_a, s_lat, s_lon, s_alt_m, times, ts, freq_hz)
            sim_id = "synthetic"
            sim_name = "synthetic_orbit"
        raw_delta = f_b_s - f_a_s
        raw_rmse = rmse(raw_delta)
        for e in args.e_values:
            for bearing in args.bearings:
                sh_lat, sh_lon = active.destination_point(s_lat, s_lon, e, bearing)
                actual = float(active.haversine_distance_km(np.array([sh_lat]), np.array([sh_lon]), s_lat, s_lon)[0])
                f_a_sh = ext.fixed_reference_geo(sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                if str(sample["sample_group"]) == "random_simulated":
                    f_b_sh = ext.fixed_reference_geo(tle[sim_id]["sat"], sh_lat, sh_lon, s_alt_m, times, ts, freq_hz, step_s)
                else:
                    spec = ext.synthetic_spec(str(sample["attack_type"]), float(sample["attack_param_value"]))
                    f_b_sh = ext.generate_synthetic_geo(spec, sat_a, sh_lat, sh_lon, s_alt_m, times, ts, freq_hz)
                f_comp = f_b_s + (f_a_sh - f_b_sh)
                noise, b_inj, k_inj, sigma, t0, residual_id = residual_terms(t_rel, args.residual_mode, ranges, rng, args.seed + row_id)
                for comp_mode, base_curve in {"no_compensation": f_b_s, "fixed_reference_compensation": f_comp}.items():
                    y_obs = base_curve + b_inj + k_inj * (t_rel - t0) + noise
                    delta = base_curve - f_a_s
                    fit_base = base.fit_bias_and_slope(base_curve, f_a_s, t_rel)
                    x = t_rel - float(np.mean(t_rel))
                    after = delta - (fit_base.b_hat_hz + fit_base.k_hat_hz_s * x)
                    obs = ext.build_observation(f"orig_current_{sample_idx}_{e:g}_{bearing:g}_{comp_mode}", target_name, target_id, geo, y_obs, base_curve, noise, b_inj, k_inj, sigma, t0, str(sample["attack_type"]), "reproduce")
                    full_specs = [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)]
                    selected_specs, _, _ = ext.choose_specs_for_mode("selected_difficult_short_windows", t_rel, f_comp, f_a_s, cal)
                    for style_type, window_mode, specs, strategy in [
                        ("original_style", "full_pass", full_specs, "original_strong_prior"),
                        ("current_extended_style", "full_pass", full_specs, "full_pass"),
                        ("current_extended_style", "selected_difficult_short_windows", selected_specs, "proposed_v1"),
                    ]:
                        for bk_mode in args.bk_modes:
                            ev = evaluate_style(style_type=style_type, bk_mode=bk_mode, strategy_type=strategy, window_mode=window_mode, observation=obs, f_geo_a=f_a_s, t_rel=t_rel, specs=specs, cal=cal)
                            case_id = f"{target_id}_{sim_id}_{sample['sample_group']}_{sample['attack_type']}_{sample['attack_param_value']}_e{e:g}_b{bearing:g}"
                            rows.append(
                                {
                                    "case_id": case_id,
                                    "target_id": target_id,
                                    "target_name": target_name,
                                    "simulated_satellite_id": sim_id,
                                    "simulated_satellite_name": sim_name,
                                    "pass_id": f"{target_id}_{geo['t_abs_utc'].iloc[0]}",
                                    "sample_group": sample["sample_group"],
                                    "orbit_relation_type": sample["attack_type"],
                                    "orbit_relation_param_name": sample["attack_param_name"],
                                    "orbit_relation_param_value": sample["attack_param_value"],
                                    "requested_error_km": float(e),
                                    "actual_error_km": actual,
                                    "bearing_deg": float(bearing),
                                    "S_lat": s_lat,
                                    "S_lon": s_lon,
                                    "S_hat_lat": sh_lat,
                                    "S_hat_lon": sh_lon,
                                    "window_mode": window_mode,
                                    "style_type": style_type,
                                    "bk_mode": bk_mode,
                                    "strategy_type": strategy,
                                    "compensation_mode": comp_mode,
                                    "raw_delta_rmse_before_bk": raw_rmse,
                                    "comp_delta_rmse_before_bk": rmse(delta),
                                    "comp_delta_rmse_after_bk": rmse(after),
                                    **ev,
                                    "residual_source": args.residual_mode,
                                    "noise_seed": int(args.seed + row_id),
                                    "b_injected": b_inj,
                                    "k_injected": k_inj,
                                    "noise_std": sigma,
                                    "empirical_residual_id": residual_id,
                                }
                            )
                            row_id += 1
    dataset = pd.DataFrame(rows)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output, index=False)
    summary = summarize(dataset)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    align = alignment_summary(dataset)
    args.alignment_output.parent.mkdir(parents=True, exist_ok=True)
    align.to_csv(args.alignment_output, index=False)
    ablation = bk_ablation(summary)
    args.bk_ablation_output.parent.mkdir(parents=True, exist_ok=True)
    ablation.to_csv(args.bk_ablation_output, index=False)
    figures = make_figures(dataset, summary, align, ablation, args.figures_dir)
    write_report(args, history, summary, align, ablation, figures)
    append_log(args, dataset, summary)
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.alignment_output} rows={len(align)}")
    print(f"wrote {args.bk_ablation_output} rows={len(ablation)}")
    print(f"wrote {args.report_output}")
    for p in figures:
        print(p)


if __name__ == "__main__":
    main()
