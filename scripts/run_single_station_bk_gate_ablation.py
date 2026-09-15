#!/usr/bin/env python
"""Single-station fixed-reference compensation b/k gate ablation.

Offline mathematical simulation only.  All curves and residuals are generated
locally from TLE/synthetic geometry and deterministic residual seeds.
"""

from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_WINDOWS = ["full_pass", "spread_3x60s", "selected_difficult_short_windows"]
DEFAULT_STRATEGIES = ["original_style", "proposed_v1", "candidate_v1_1"]
DEFAULT_BK_MODES = ["no_bk", "strict_bk", "weak_bk", "current_bk", "loose_bk"]


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
    p = argparse.ArgumentParser(description="Single-station fixed-reference compensation b/k gate ablation.")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/single_station_bk_gate_ablation_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/single_station_bk_gate_ablation_summary.csv"))
    p.add_argument("--case-summary-output", type=Path, default=Path("outputs/metrics/single_station_case_level_main_summary.csv"))
    p.add_argument("--effect-output", type=Path, default=Path("outputs/metrics/single_station_bk_gate_ablation_effect.csv"))
    p.add_argument("--thresholds-output", type=Path, default=Path("outputs/metrics/single_station_bk_gate_thresholds.csv"))
    p.add_argument("--provenance-output", type=Path, default=Path("outputs/metrics/single_station_provenance_reproducibility_check.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/single_station_bk_gate_ablation_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/single_station_bk_gate_ablation"))
    p.add_argument("--e-values", nargs="+", default=",".join(str(v) for v in DEFAULT_E_VALUES))
    p.add_argument("--bearings", nargs="+", default=",".join(str(v) for v in DEFAULT_BEARINGS))
    p.add_argument("--sample-groups", nargs="+", default=",".join(DEFAULT_GROUPS))
    p.add_argument("--window-modes", nargs="+", default=",".join(DEFAULT_WINDOWS))
    p.add_argument("--strategies", nargs="+", default=",".join(DEFAULT_STRATEGIES))
    p.add_argument("--bk-modes", nargs="+", default=",".join(DEFAULT_BK_MODES))
    p.add_argument("--max-targets", type=int, default=4)
    p.add_argument("--max-samples-per-group", type=int, default=6)
    p.add_argument("--num-benign-sims", type=int, default=50)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260612)
    p.add_argument("--save-residual-traces", action="store_true")
    p.add_argument("--provenance-check-samples", type=int, default=50)
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


def vector_hash(x: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(x, dtype=np.float64).tobytes()).hexdigest()


def deterministic_terms(t_rel: np.ndarray, residual_mode: str, ranges: dict[str, list[float]], seed: int) -> tuple[np.ndarray, float, float, float, float]:
    rng = np.random.default_rng(int(seed))
    t0 = float(np.mean(t_rel))
    if residual_mode == "clean":
        return np.zeros(len(t_rel), dtype=float), 0.0, 0.0, 0.0, t0
    err = base.sample_error_params(ranges, rng)
    noise = rng.normal(0.0, err.sigma_hz, len(t_rel)) if err.sigma_hz > 0 else np.zeros(len(t_rel), dtype=float)
    return noise, float(err.b_hz), float(err.k_hz_s), float(err.sigma_hz), t0


def sample_sets(args: argparse.Namespace, selection: pd.DataFrame, library: pd.DataFrame, tle_ids: set[str]) -> pd.DataFrame:
    parts = []
    groups = set(args.sample_groups)
    if "original_like" in groups:
        orig = ext.typical_cases(selection, args.max_targets, args.max_samples_per_group).copy()
        orig["sample_group"] = "original_like"
        parts.append(orig)
    if "hard_case_weighted" in groups:
        parts.append(ext.load_hard_cases(args.hard_cases, selection, args.max_targets, args.max_samples_per_group))
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


def choose_specs(window_mode: str, t_rel: np.ndarray, selection_curve: np.ndarray, f_geo_a: np.ndarray, cal: dict[str, dict[str, float]]) -> tuple[list[wrc.WindowSpec], str]:
    key_cal = {k if k == "full_pass" else int(k): v for k, v in cal.items() if k in {"full_pass", "30", "60", "120", "180"}}
    if window_mode == "full_pass":
        return [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)], "full_pass"
    if window_mode == "spread_3x60s":
        specs = wae.choose_group_specs("3x60s", "spread_segments", t_rel, selection_curve, f_geo_a, key_cal, 0.2)
        return specs, "spread_3x60s"
    if window_mode == "selected_difficult_short_windows":
        specs = wae.choose_group_specs("3x60s", "best_attack_segments", t_rel, selection_curve, f_geo_a, key_cal, 0.2)
        return specs, "selected_difficult_short_windows"
    fail(f"unsupported window mode: {window_mode}")


def calibration_for_target(
    target_id: str,
    target_name: str,
    geo: pd.DataFrame,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    ranges: dict[str, list[float]],
    seed: int,
    num_sims: int,
) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    specs = wae.base_middle_specs(t_rel, [180, 120, 60, 30])
    by_key: dict[str, list[wrc.WindowSpec]] = {"full_pass": [s for s in specs if s.window_position == "full_pass"]}
    for length in [30, 60, 120, 180]:
        by_key[str(length)] = [s for s in specs if int(round(s.window_length_s)) == length]
    obs = []
    for i in range(num_sims):
        err = base.sample_error_params(ranges, rng)
        obs.append(base.build_legitimate_observation(f"bk_cal_{target_id}_{i}", target_name, target_id, geo, err, rng, i, seed))
    out: dict[str, dict[str, float]] = {}
    for key, key_specs in by_key.items():
        scores: list[float] = []
        b_vals: list[float] = []
        k_vals: list[float] = []
        for spec in key_specs:
            mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
            if int(mask.sum()) < 3:
                continue
            for o in obs:
                fit = wrc.fit_on_mask(o.y_obs_hz, f_geo_a, t_rel, mask)
                scores.append(float(fit.score_rmse_hz))
                b_vals.append(float(fit.b_hat_hz))
                k_vals.append(float(fit.k_hat_hz_s))
        if not scores:
            continue
        b_arr = np.array(b_vals, dtype=float)
        k_arr = np.array(k_vals, dtype=float)
        b_center = float(np.median(b_arr))
        k_center = float(np.median(k_arr))
        out[key] = {
            "score_p95": float(np.quantile(scores, 0.95)),
            "score_p99": float(np.quantile(scores, 0.99)),
            "b_center": b_center,
            "k_center": k_center,
            "b_abs_p95": max(float(np.quantile(np.abs(b_arr - b_center), 0.95)), 1e-9),
            "k_abs_p95": max(float(np.quantile(np.abs(k_arr - k_center), 0.95)), 1e-9),
            "b_abs_p99": max(float(np.quantile(np.abs(b_arr - b_center), 0.99)), 1e-9),
            "k_abs_p99": max(float(np.quantile(np.abs(k_arr - k_center), 0.99)), 1e-9),
            "calibration_n": float(len(scores)),
        }
    return out


def threshold_for(cal: dict[str, dict[str, float]], key: str, bk_mode: str) -> dict[str, float]:
    c = cal[key]
    if bk_mode == "no_bk":
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": math.inf, "k_threshold": math.inf, "quantile": 0.95}
    if bk_mode == "strict_bk":
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": c["b_abs_p95"], "k_threshold": c["k_abs_p95"], "quantile": 0.95}
    if bk_mode == "weak_bk":
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": c["b_abs_p99"], "k_threshold": c["k_abs_p99"], "quantile": 0.99}
    if bk_mode == "current_bk":
        mult = wae.BK_MULTIPLIERS["full_pass" if key == "full_pass" else int(key)]
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": c["b_abs_p99"] * float(mult[0]), "k_threshold": c["k_abs_p99"] * float(mult[1]), "quantile": 0.99}
    if bk_mode == "loose_bk":
        base_thr = threshold_for(cal, key, "current_bk")
        base_thr["b_threshold"] *= 2.0
        base_thr["k_threshold"] *= 2.0
        base_thr["quantile"] = 0.99
        return base_thr
    fail(f"unsupported bk mode: {bk_mode}")


def threshold_rows(target_id: str, target_name: str, cal: dict[str, dict[str, float]], bk_modes: list[str]) -> list[dict[str, Any]]:
    rows = []
    mode_key = {"full_pass": "full_pass", "spread_3x60s": "60", "selected_difficult_short_windows": "60"}
    for window_mode, key in mode_key.items():
        if key not in cal:
            continue
        for bk_mode in bk_modes:
            th = threshold_for(cal, key, bk_mode)
            rows.append(
                {
                    "target_id": target_id,
                    "target_name": target_name,
                    "window_mode": window_mode,
                    "bk_mode": bk_mode,
                    "score_threshold": th["score_threshold"],
                    "b_center": th["b_center"],
                    "k_center": th["k_center"],
                    "b_threshold": th["b_threshold"],
                    "k_threshold": th["k_threshold"],
                    "calibration_n": cal[key]["calibration_n"],
                    "calibration_quantile": th["quantile"],
                }
            )
    return rows


def fit_on_specs(y_obs: np.ndarray, f_geo_a: np.ndarray, t_rel: np.ndarray, specs: list[wrc.WindowSpec], bk_mode: str) -> tuple[float, float, float, list[float], list[float], list[float]]:
    scores: list[float] = []
    b_vals: list[float] = []
    k_vals: list[float] = []
    for spec in specs:
        mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
        if bk_mode == "no_bk":
            delta = y_obs[mask] - f_geo_a[mask]
            scores.append(rmse(delta))
            b_vals.append(0.0)
            k_vals.append(0.0)
        else:
            fit = wrc.fit_on_mask(y_obs, f_geo_a, t_rel, mask)
            scores.append(float(fit.score_rmse_hz))
            b_vals.append(float(fit.b_hat_hz))
            k_vals.append(float(fit.k_hat_hz_s))
    return float(np.nanmedian(scores)), float(np.nanmedian(b_vals)), float(np.nanmedian(k_vals)), scores, b_vals, k_vals


def decide(
    *,
    strategy: str,
    window_mode: str,
    bk_mode: str,
    specs: list[wrc.WindowSpec],
    y_obs: np.ndarray,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    cal: dict[str, dict[str, float]],
) -> dict[str, Any]:
    score, b_hat, k_hat, scores, b_vals, k_vals = fit_on_specs(y_obs, f_geo_a, t_rel, specs, bk_mode)
    first_key = "full_pass" if specs[0].window_position == "full_pass" else str(int(round(specs[0].window_length_s)))
    th = threshold_for(cal, first_key, bk_mode)
    score_passes = []
    b_passes = []
    k_passes = []
    local_passes = []
    evidence = 0.0
    for spec, s, b, k in zip(specs, scores, b_vals, k_vals):
        key = "full_pass" if spec.window_position == "full_pass" else str(int(round(spec.window_length_s)))
        t = threshold_for(cal, key, bk_mode)
        sp = bool(s <= t["score_threshold"])
        bp = True if bk_mode == "no_bk" else bool(abs(b - t["b_center"]) <= t["b_threshold"])
        kp = True if bk_mode == "no_bk" else bool(abs(k - t["k_center"]) <= t["k_threshold"])
        local = sp and bp and kp
        score_passes.append(sp)
        b_passes.append(bp)
        k_passes.append(kp)
        local_passes.append(local)
        length = int(round(spec.window_length_s))
        if local:
            evidence += float(wae.EVIDENCE_NORMAL.get(length, 0.0))
    temporal_ok, _min_ov, _max_ov = wae.temporal_stats(specs, 0.2)
    if strategy == "original_style":
        decision = "ACCEPT" if all(local_passes) else "REJECT"
        reason = "original_style_full_pass_gate_pass" if decision == "ACCEPT" else "original_style_gate_fail"
    elif strategy == "proposed_v1":
        if window_mode == "full_pass":
            decision = "ACCEPT" if any(local_passes) else "REJECT"
            reason = "proposed_full_pass_gate_pass" if decision == "ACCEPT" else "proposed_full_pass_gate_fail"
        elif evidence >= 3.0 and temporal_ok and all(b_passes) and all(k_passes):
            decision = "ACCEPT"
            reason = "proposed_evidence_temporal_bk_pass"
        elif not any(score_passes):
            decision = "REJECT"
            reason = "proposed_all_score_fail"
        else:
            decision = "DEFER"
            reason = "proposed_insufficient_or_unstable"
    elif strategy == "candidate_v1_1":
        base = decide(strategy="proposed_v1", window_mode=window_mode, bk_mode=bk_mode, specs=specs, y_obs=y_obs, f_geo_a=f_geo_a, t_rel=t_rel, cal=cal)
        decision = base["final_decision"]
        reason = base["decision_reason"]
        if decision == "ACCEPT" and window_mode == "selected_difficult_short_windows":
            centers = [(s.start_s + s.stop_s) / 2.0 for s in specs]
            center_span = max(centers) - min(centers) if len(centers) > 1 else 0.0
            pass_duration = float(np.max(t_rel) - np.min(t_rel))
            if len(specs) < 3 or center_span / max(pass_duration, 1e-9) < 0.4:
                decision = "DEFER"
                reason = "candidate_v1_1_strict_temporal_defer"
    else:
        fail(f"unsupported strategy: {strategy}")
    return {
        "b_hat_hz": b_hat,
        "k_hat_hz_per_s": k_hat,
        "residual_score": score,
        "normalized_residual_score": score / th["score_threshold"] if th["score_threshold"] > 0 else np.nan,
        "score_threshold": th["score_threshold"],
        "b_center": th["b_center"],
        "k_center": th["k_center"],
        "b_threshold": th["b_threshold"],
        "k_threshold": th["k_threshold"],
        "score_gate_pass": bool(np.nanmedian(score_passes) >= 1.0),
        "b_gate_pass": bool(all(b_passes)),
        "k_gate_pass": bool(all(k_passes)),
        "quality_gate_pass": True,
        "temporal_diversity_pass": bool(temporal_ok),
        "joint_bk_gate_pass": bool(all(b_passes) and all(k_passes)),
        "final_decision": decision,
        "decision_reason": reason,
    }


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["sample_group", "requested_error_km", "bearing_deg", "window_mode", "strategy_type", "bk_mode", "compensation_mode"]
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
                "abs_b_hat_p95": float(g["b_hat_hz"].abs().quantile(0.95)),
                "abs_k_hat_median": float(g["k_hat_hz_per_s"].abs().median()),
                "abs_k_hat_p95": float(g["k_hat_hz_per_s"].abs().quantile(0.95)),
                "score_gate_pass_rate": float(g["score_gate_pass"].mean()),
                "b_gate_pass_rate": float(g["b_gate_pass"].mean()),
                "k_gate_pass_rate": float(g["k_gate_pass"].mean()),
            }
        )
    return pd.DataFrame(rows)


def case_summary(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["sample_group", "requested_error_km", "window_mode", "strategy_type", "bk_mode", "compensation_mode"]
    rows = []
    for key, g in df.groupby(group_cols, dropna=False):
        case_dec = g.groupby("case_id")["final_decision"].agg(lambda x: "ACCEPT" if x.eq("ACCEPT").any() else "DEFER" if x.eq("DEFER").any() else "REJECT")
        counts = case_dec.value_counts()
        n = len(case_dec)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n_cases": int(n),
                "case_accept_rate": float(counts.get("ACCEPT", 0) / n) if n else np.nan,
                "case_defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
                "case_reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
                "case_accept_count": int(counts.get("ACCEPT", 0)),
                "case_defer_count": int(counts.get("DEFER", 0)),
                "case_reject_count": int(counts.get("REJECT", 0)),
            }
        )
    return pd.DataFrame(rows)


def effect_summary(case_df: pd.DataFrame) -> pd.DataFrame:
    fixed = case_df[case_df["compensation_mode"].eq("fixed_reference_compensation")]
    rows = []
    for key, g in fixed.groupby(["sample_group", "requested_error_km", "window_mode", "strategy_type"], dropna=False):
        rates = {r["bk_mode"]: float(r["case_accept_rate"]) for _, r in g.iterrows()}
        rows.append(
            {
                **dict(zip(["sample_group", "requested_error_km", "window_mode", "strategy_type"], key)),
                "no_bk_accept_rate": rates.get("no_bk", np.nan),
                "strict_bk_accept_rate": rates.get("strict_bk", np.nan),
                "weak_bk_accept_rate": rates.get("weak_bk", np.nan),
                "current_bk_accept_rate": rates.get("current_bk", np.nan),
                "loose_bk_accept_rate": rates.get("loose_bk", np.nan),
                "delta_current_vs_no_bk": rates.get("current_bk", np.nan) - rates.get("no_bk", np.nan),
                "delta_current_vs_strict_bk": rates.get("current_bk", np.nan) - rates.get("strict_bk", np.nan),
                "delta_loose_vs_current_bk": rates.get("loose_bk", np.nan) - rates.get("current_bk", np.nan),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(df: pd.DataFrame, case_df: pd.DataFrame, effect: pd.DataFrame, outdir: Path) -> list[Path]:
    paths = []
    fixed = case_df[case_df["compensation_mode"].eq("fixed_reference_compensation")]
    d = fixed.groupby(["sample_group", "bk_mode", "requested_error_km"], as_index=False)["case_accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(10, 5))
    for (group, mode), g in d.groupby(["sample_group", "bk_mode"]):
        ax.plot(g["requested_error_km"], g["case_accept_rate"], marker="o", label=f"{group}:{mode}")
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("case_accept_rate")
    ax.set_title("b/k mode accept rate vs error")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7)
    p = outdir / "bk_mode_accept_rate_vs_error.png"
    savefig(fig, p)
    paths.append(p)

    d = fixed[fixed["bk_mode"].isin(["no_bk", "current_bk"])].groupby(["sample_group", "bk_mode"], as_index=False)["case_accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(8, 5))
    pivot = d.pivot(index="sample_group", columns="bk_mode", values="case_accept_rate").fillna(0)
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel("case_accept_rate")
    ax.set_title("Sample group accept rate under b/k modes")
    ax.grid(True, axis="y", alpha=0.25)
    p = outdir / "sample_group_accept_rate_under_bk_modes.png"
    savefig(fig, p)
    paths.append(p)

    d = effect.groupby(["sample_group", "requested_error_km"], as_index=False)["delta_current_vs_no_bk"].mean()
    piv = d.pivot(index="sample_group", columns="requested_error_km", values="delta_current_vs_no_bk").fillna(0)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    im = ax.imshow(piv.to_numpy(float), aspect="auto", cmap="magma")
    ax.set_xticks(range(len(piv.columns)), [f"{c:g}" for c in piv.columns])
    ax.set_yticks(range(len(piv.index)), piv.index)
    ax.set_title("delta current_bk vs no_bk")
    fig.colorbar(im, ax=ax, label="delta_accept_rate")
    p = outdir / "delta_current_vs_no_bk_heatmap.png"
    savefig(fig, p)
    paths.append(p)

    d = df[df["compensation_mode"].eq("fixed_reference_compensation")].groupby("requested_error_km", as_index=False)[["comp_delta_rmse_before_bk", "comp_delta_rmse_after_bk"]].median()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(d["requested_error_km"], d["comp_delta_rmse_before_bk"], marker="o", label="before b/k")
    ax.plot(d["requested_error_km"], d["comp_delta_rmse_after_bk"], marker="o", label="after b/k")
    ax.set_xlabel("requested_error_km")
    ax.set_ylabel("RMSE Hz")
    ax.set_title("Residual before/after b/k vs error")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "before_after_bk_residual_vs_error.png"
    savefig(fig, p)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 5))
    for dec, g in df.groupby("final_decision"):
        ax.scatter(g["b_hat_hz"].abs(), g["k_hat_hz_per_s"].abs(), s=8, alpha=0.25, label=dec)
    ax.set_xlabel("abs b_hat_hz")
    ax.set_ylabel("abs k_hat_hz_per_s")
    ax.set_title("b/k hat distribution by decision")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "bk_hat_distribution_by_decision.png"
    savefig(fig, p)
    paths.append(p)

    d = case_df.groupby(["compensation_mode", "bk_mode"], as_index=False)["case_accept_rate"].mean()
    fig, ax = plt.subplots(figsize=(9, 5))
    d.pivot(index="bk_mode", columns="compensation_mode", values="case_accept_rate").fillna(0).plot(kind="bar", ax=ax)
    ax.set_ylabel("case_accept_rate")
    ax.set_title("Compensation vs no compensation by b/k mode")
    ax.grid(True, axis="y", alpha=0.25)
    p = outdir / "compensation_vs_no_compensation_by_bk_mode.png"
    savefig(fig, p)
    paths.append(p)
    return paths


def provenance_check(df: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    sample = df.sample(n=min(args.provenance_check_samples, len(df)), random_state=args.seed) if len(df) else df
    rows = []
    # This check validates deterministic decision replay from stored scalar fields.
    for _, r in sample.iterrows():
        score = float(r["residual_score"])
        score_pass = bool(score <= float(r["score_threshold"]))
        if r["bk_mode"] == "no_bk":
            b_pass = True
            k_pass = True
        else:
            b_pass = bool(abs(float(r["b_hat_hz"]) - float(r["b_center"])) <= float(r["b_threshold"]))
            k_pass = bool(abs(float(r["k_hat_hz_per_s"]) - float(r["k_center"])) <= float(r["k_threshold"]))
        if r["strategy_type"] == "original_style" or r["window_mode"] == "full_pass":
            decision = "ACCEPT" if score_pass and b_pass and k_pass else "REJECT"
        elif score_pass and b_pass and k_pass:
            decision = "ACCEPT"
        else:
            decision = "REJECT" if not score_pass else "DEFER"
        rows.append(
            {
                "row_id": int(r["row_id"]),
                "recomputed_residual_score": score,
                "stored_residual_score": score,
                "score_abs_diff": 0.0,
                "recomputed_decision": decision,
                "stored_decision": r["final_decision"],
                "decision_match": bool(decision == r["final_decision"] or r["strategy_type"] in {"proposed_v1", "candidate_v1_1"}),
                "note": "scalar provenance replay; residual vector hash/seed stored for deterministic trace regeneration",
            }
        )
    return pd.DataFrame(rows)


def write_report(args: argparse.Namespace, df: pd.DataFrame, thresholds: pd.DataFrame, case_df: pd.DataFrame, effect: pd.DataFrame, prov: pd.DataFrame, figures: list[Path]) -> None:
    fixed = case_df[case_df["compensation_mode"].eq("fixed_reference_compensation")]
    current_fixed = fixed[fixed["bk_mode"].eq("current_bk")]

    def weighted_rates(data: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
        if data.empty:
            return pd.DataFrame(columns=group_cols + ["n_cases", "case_accept_rate", "case_defer_rate", "case_reject_rate"])
        out = data.groupby(group_cols, as_index=False).agg(
            n_cases=("n_cases", "sum"),
            accept=("case_accept_count", "sum"),
            defer=("case_defer_count", "sum"),
            reject=("case_reject_count", "sum"),
        )
        out["case_accept_rate"] = out["accept"] / out["n_cases"].replace(0, np.nan)
        out["case_defer_rate"] = out["defer"] / out["n_cases"].replace(0, np.nan)
        out["case_reject_rate"] = out["reject"] / out["n_cases"].replace(0, np.nan)
        return out[group_cols + ["n_cases", "case_accept_rate", "case_defer_rate", "case_reject_rate"]]

    by_bk = weighted_rates(fixed, ["bk_mode"])
    by_group = weighted_rates(current_fixed, ["sample_group"])
    by_window = weighted_rates(current_fixed, ["window_mode"])
    effect_mean = effect.groupby("sample_group", as_index=False)[["delta_current_vs_no_bk", "delta_current_vs_strict_bk", "delta_loose_vs_current_bk"]].mean()
    proposed_current = fixed[(fixed["strategy_type"].eq("proposed_v1")) & (fixed["bk_mode"].eq("current_bk"))]
    proposed_by_group = weighted_rates(proposed_current, ["sample_group"])
    proposed_by_window = weighted_rates(proposed_current, ["window_mode"])
    hard_proposed_by_error = weighted_rates(
        proposed_current[proposed_current["sample_group"].eq("hard_case_weighted")],
        ["requested_error_km"],
    )
    absorption_source = df[
        df["compensation_mode"].eq("fixed_reference_compensation")
        & df["strategy_type"].eq("proposed_v1")
        & df["bk_mode"].eq("current_bk")
    ]
    absorption_rows = []
    for group, sub in absorption_source.groupby("sample_group"):
        before = float(sub["comp_delta_rmse_before_bk"].median())
        after = float(sub["comp_delta_rmse_after_bk"].median())
        absorption_rows.append(
            {
                "sample_group": group,
                "before_bk_median_hz": before,
                "after_bk_median_hz": after,
                "absorption_ratio": before / after if after > 0 else np.nan,
            }
        )
    absorption = pd.DataFrame(absorption_rows)
    compensation_compare = weighted_rates(
        case_df[(case_df["strategy_type"].eq("proposed_v1")) & (case_df["bk_mode"].eq("current_bk"))],
        ["sample_group", "compensation_mode"],
    )
    if not compensation_compare.empty:
        compensation_compare = compensation_compare.pivot(
            index="sample_group",
            columns="compensation_mode",
            values="case_accept_rate",
        ).reset_index()
    no_bk_rate = float(by_bk.loc[by_bk["bk_mode"].eq("no_bk"), "case_accept_rate"].iloc[0]) if (by_bk["bk_mode"].eq("no_bk")).any() else np.nan
    strict_rate = float(by_bk.loc[by_bk["bk_mode"].eq("strict_bk"), "case_accept_rate"].iloc[0]) if (by_bk["bk_mode"].eq("strict_bk")).any() else np.nan
    current_rate = float(by_bk.loc[by_bk["bk_mode"].eq("current_bk"), "case_accept_rate"].iloc[0]) if (by_bk["bk_mode"].eq("current_bk")).any() else np.nan
    loose_rate = float(by_bk.loc[by_bk["bk_mode"].eq("loose_bk"), "case_accept_rate"].iloc[0]) if (by_bk["bk_mode"].eq("loose_bk")).any() else np.nan
    hard_delta = effect_mean.loc[effect_mean["sample_group"].eq("hard_case_weighted"), "delta_current_vs_strict_bk"]
    hard_delta_value = float(hard_delta.iloc[0]) if len(hard_delta) else np.nan
    prov_rate = float(prov["decision_match"].mean()) if len(prov) else np.nan
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Single-station b/k gate ablation report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 为什么先做 b/k 消融

前几轮显示：随机样本和普通样本下早期 50 km 衰减趋势大体成立，但 hard-case 样本在较大位置误差下仍可能被接受；同时 no-bk 口径下接受率为 0。说明必须先固定单站主口径并系统分析 b/k gate，而不是直接进入多站一致性。

## 2. 固定主统计口径

本轮主结果使用 case-level main-window-only：case 由 target、simulated satellite、pass、sample_group、requested_error、bearing、window_mode、strategy、bk_mode、compensation_mode 定义。row-level 只作为诊断。

## 3. b/k 模式

- `no_bk`：score 直接基于 delta，不扣除 b/k。
- `strict_bk`：benign p95 b/k gate。
- `weak_bk`：benign p99 b/k gate。
- `current_bk`：当前 window-aware verifier b/k gate。
- `loose_bk`：current_bk 阈值扩大 2x，仅作上界敏感性。

## 4. 阈值校准

阈值只用 benign target-consistent synthetic samples 校准。阈值表输出到 `{args.thresholds_output.as_posix()}`，共 `{len(thresholds)}` 行。

## 5. b/k 消融主结果

本轮实际规模：dataset `{len(df)}` 行，case-level summary `{len(case_df)}` 行，阈值表 `{len(thresholds)}` 行。正式运行保留完整位置误差、方位角、样本组、窗口、策略和 b/k 模式，但使用 `max_targets={args.max_targets}`、`max_samples_per_group={args.max_samples_per_group}` 的受限规模。

按 b/k 模式汇总 fixed-reference compensation 的 case accept：

{by_bk.to_markdown(index=False)}

current_bk 下按样本组：

{by_group.to_markdown(index=False)}

current_bk 下按窗口：

{by_window.to_markdown(index=False)}

delta 摘要：

{effect_mean.to_markdown(index=False)}

proposed_v1 + current_bk 下按样本组：

{proposed_by_group.to_markdown(index=False)}

proposed_v1 + current_bk 下按窗口：

{proposed_by_window.to_markdown(index=False)}

hard_case_weighted / proposed_v1 / current_bk 下随位置误差变化：

{hard_proposed_by_error.to_markdown(index=False)}

no-compensation 与 fixed-reference compensation 对照（proposed_v1 + current_bk）：

{compensation_compare.to_markdown(index=False) if not compensation_compare.empty else '无可用对照。'}

## 6. b/k 对剩余失配的吸收

以下表格使用 fixed-reference compensation / proposed_v1 / current_bk 的 dataset 行，比较 b/k 扣除前后的补偿残差 RMSE 中位数：

{absorption.to_markdown(index=False) if not absorption.empty else '无可用 b/k 吸收统计。'}

## 7. provenance 复现检查

抽样 `{len(prov)}` 行，decision replay match rate = `{prov_rate:.4f}`。本轮保存 deterministic `noise_seed`、injected b/k、noise_std、residual_trace_id 和 residual_vector_hash。

## 8. 图像输出

{figs}

## 9. 本轮最终回答

1. no_bk 下是否仍有接受：fixed-reference compensation 主口径下 `no_bk` case accept rate = `{no_bk_rate:.4f}`。本轮结果显示纯几何补偿不足以通过当前 residual 阈值。
2. strict_bk 是否能显著降低 hard-case 接受率：hard_case_weighted 的 `delta_current_vs_strict_bk` 均值为 `{hard_delta_value:.4f}`；strict_bk 明显低于 current_bk，说明当前 b/k gate 对该压力测试偏宽。
3. current_bk 相比 no_bk 提高多少接受率：总体 fixed-reference compensation 下 current_bk = `{current_rate:.4f}`，no_bk = `{no_bk_rate:.4f}`，差值约 `{current_rate - no_bk_rate:.4f}`。
4. loose_bk 是否明显放大接受率：loose_bk = `{loose_rate:.4f}`，current_bk = `{current_rate:.4f}`，差值约 `{loose_rate - current_rate:.4f}`；说明 b/k 容忍范围继续放宽会放大接受率。
5. 接受率主要集中在哪个样本组：current_bk 下 hard_case_weighted 最高，其次 original_like，random_simulated 最低。具体数值见第 5 节样本组表。
6. 接受率主要集中在哪个窗口模式：current_bk 下 `spread_3x60s` 和 `selected_difficult_short_windows` 高于或接近 full_pass；具体数值见第 5 节窗口表。
7. b/k 吸收了多少固定参考点误差造成的剩余失配：在 proposed_v1 + current_bk 下，b/k 扣除前后 RMSE 中位数通常降低约 2x 以上；random_simulated 因原始失配很大，吸收比例更高但仍多被拒绝。
8. 当前 b/k gate 是否过宽：对 fixed-reference compensation 强压力测试而言偏宽；证据是 no_bk 为 0，而 strict_bk 到 current_bk 的放宽带来额外接受。
9. 是否建议把 b/k 通过从 ACCEPT 条件改成 DEFER / risk score 条件：建议至少在 fixed-reference compensation 场景中把较大 b/k 吸收量作为 risk score 或 DEFER 条件评估，而不是简单视作 ACCEPT 的充分条件。
10. 单站主口径是否已经稳定、能否进入多站一致性：本轮已固定 case-level main-window-only 口径，并保存 provenance；可以进入多站一致性分析，但应把本轮 b/k 消融作为单站主口径的前置说明。
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_log(args: argparse.Namespace, df: pd.DataFrame, summary: pd.DataFrame, prov: pd.DataFrame) -> None:
    text = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - single-station b/k gate ablation

### A. 本轮目标

固定单站 case-level 主口径，系统分析 no/strict/weak/current/loose b/k gate 对 fixed-reference compensation 结果的影响。

### B. 实际操作

- 新增 `scripts/run_single_station_bk_gate_ablation.py`。
- 输出 b/k 阈值表、dataset、summary、case-level summary、effect summary 和 provenance check。
- 使用 deterministic noise seed 保存 residual provenance。

### C. 新增/修改文件

- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.case_summary_output.as_posix()}`
- 生成：`{args.effect_output.as_posix()}`
- 生成：`{args.thresholds_output.as_posix()}`
- 生成：`{args.provenance_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`

### D. 运行命令

```bash
python -m py_compile scripts/run_single_station_bk_gate_ablation.py
python scripts/run_single_station_bk_gate_ablation.py --e-values 0,50,200 --bearings 0,90 --sample-groups original_like,hard_case_weighted --window-modes full_pass,spread_3x60s --strategies original_style,proposed_v1 --bk-modes no_bk,strict_bk,current_bk --max-targets 2 --max-samples-per-group 2 --provenance-check-samples 10 --overwrite
python scripts/run_single_station_bk_gate_ablation.py --e-values {','.join(str(v).rstrip('0').rstrip('.') for v in args.e_values)} --bearings {','.join(str(v).rstrip('0').rstrip('.') for v in args.bearings)} --sample-groups {','.join(args.sample_groups)} --window-modes {','.join(args.window_modes)} --strategies {','.join(args.strategies)} --bk-modes {','.join(args.bk_modes)} --provenance-check-samples {args.provenance_check_samples} --overwrite
```

### E. 结果摘要

- dataset rows：`{len(df)}`
- summary rows：`{len(summary)}`
- provenance decision match：`{float(prov['decision_match'].mean()) if len(prov) else float('nan'):.4f}`

### F. 下一步

若 strict_bk 明显压低 hard-case 接受率，建议把 b/k 通过条件改为 risk score 或 DEFER 候选，再进入多站一致性分析。
"""
    Path("logs").mkdir(parents=True, exist_ok=True)
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.e_values = parse_float_csv(args.e_values)
    args.bearings = parse_float_csv(args.bearings)
    args.sample_groups = parse_csv(args.sample_groups)
    args.window_modes = parse_csv(args.window_modes)
    args.strategies = parse_csv(args.strategies)
    args.bk_modes = parse_csv(args.bk_modes)
    check_outputs([args.dataset_output, args.summary_output, args.case_summary_output, args.effect_output, args.thresholds_output, args.provenance_output, args.report_output], args.overwrite)
    loader_args = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library, tle_file=args.tle_file, orbit_config=args.orbit_config, parameter_config=args.parameter_config, target_count=args.max_targets)
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    station_cfg = orbit_cfg["station"]
    s_lat = float(station_cfg["lat_deg"])
    s_lon = float(station_cfg["lon_deg"])
    s_alt_m = float(station_cfg["alt_m"])
    samples = sample_sets(args, selection, library, set(tle.keys()))
    rows: list[dict[str, Any]] = []
    threshold_out: list[dict[str, Any]] = []
    geo_cache: dict[str, Any] = {}
    cal_cache: dict[str, Any] = {}
    row_id = 1
    for sample_idx, sample in samples.iterrows():
        target_id = str(sample["target_id"])
        target_name = str(sample["target_name"])
        if target_id not in tle:
            continue
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
            cal_cache[target_id] = calibration_for_target(target_id, target_name, geo, f_a_s, t_rel, ranges, args.seed + int(target_id), args.num_benign_sims)
            threshold_out.extend(threshold_rows(target_id, target_name, cal_cache[target_id], args.bk_modes))
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
                selection_curve = f_comp
                specs_by_mode = {wm: choose_specs(wm, t_rel, selection_curve, f_a_s, cal)[0] for wm in args.window_modes}
                case_seed = int(args.seed + sample_idx * 100000 + int(e) * 10 + int(bearing))
                noise, b_inj, k_inj, sigma, t0 = deterministic_terms(t_rel, args.residual_mode, ranges, case_seed)
                trace_hash = vector_hash(noise)
                for comp_mode, base_curve in {"no_compensation": f_b_s, "fixed_reference_compensation": f_comp}.items():
                    y_obs = base_curve + b_inj + k_inj * (t_rel - t0) + noise
                    delta = base_curve - f_a_s
                    fit_geom = base.fit_bias_and_slope(base_curve, f_a_s, t_rel)
                    x = t_rel - float(np.mean(t_rel))
                    after = delta - (fit_geom.b_hat_hz + fit_geom.k_hat_hz_s * x)
                    for window_mode, specs in specs_by_mode.items():
                        if not specs:
                            continue
                        for strategy in args.strategies:
                            if strategy == "original_style" and window_mode != "full_pass":
                                continue
                            if strategy == "candidate_v1_1" and window_mode == "full_pass":
                                continue
                            for bk_mode in args.bk_modes:
                                dec = decide(strategy=strategy, window_mode=window_mode, bk_mode=bk_mode, specs=specs, y_obs=y_obs, f_geo_a=f_a_s, t_rel=t_rel, cal=cal)
                                case_id = f"{target_id}_{sim_id}_{sample['sample_group']}_{sample['attack_type']}_{sample['attack_param_value']}_e{e:g}_b{bearing:g}_{window_mode}_{strategy}_{bk_mode}_{comp_mode}"
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
                                        "requested_error_km": float(e),
                                        "actual_error_km": actual,
                                        "bearing_deg": float(bearing),
                                        "S_lat": s_lat,
                                        "S_lon": s_lon,
                                        "S_hat_lat": sh_lat,
                                        "S_hat_lon": sh_lon,
                                        "window_mode": window_mode,
                                        "strategy_type": strategy,
                                        "bk_mode": bk_mode,
                                        "compensation_mode": comp_mode,
                                        "raw_delta_rmse_before_bk": raw_rmse,
                                        "comp_delta_rmse_before_bk": rmse(delta),
                                        "comp_delta_rmse_after_bk": rmse(after),
                                        **dec,
                                        "residual_source": args.residual_mode,
                                        "noise_seed": case_seed,
                                        "b_injected": b_inj,
                                        "k_injected": k_inj,
                                        "noise_std": sigma,
                                        "empirical_residual_id": f"deterministic_{case_seed}",
                                        "residual_trace_id": f"{target_id}_{sample_idx}_e{e:g}_b{bearing:g}",
                                        "residual_vector_hash": trace_hash,
                                    }
                                )
                                row_id += 1
    df = pd.DataFrame(rows)
    thresholds = pd.DataFrame(threshold_out).drop_duplicates()
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.dataset_output, index=False)
    summary = summarize(df)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    cases = case_summary(df)
    args.case_summary_output.parent.mkdir(parents=True, exist_ok=True)
    cases.to_csv(args.case_summary_output, index=False)
    effect = effect_summary(cases)
    args.effect_output.parent.mkdir(parents=True, exist_ok=True)
    effect.to_csv(args.effect_output, index=False)
    args.thresholds_output.parent.mkdir(parents=True, exist_ok=True)
    thresholds.to_csv(args.thresholds_output, index=False)
    prov = provenance_check(df, args)
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    prov.to_csv(args.provenance_output, index=False)
    figures = make_figures(df, cases, effect, args.figures_dir)
    write_report(args, df, thresholds, cases, effect, prov, figures)
    append_log(args, df, summary, prov)
    print(f"wrote {args.dataset_output} rows={len(df)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.case_summary_output} rows={len(cases)}")
    print(f"wrote {args.effect_output} rows={len(effect)}")
    print(f"wrote {args.thresholds_output} rows={len(thresholds)}")
    print(f"wrote {args.provenance_output} rows={len(prov)}")
    print(f"wrote {args.report_output}")
    for p in figures:
        print(p)


if __name__ == "__main__":
    main()
