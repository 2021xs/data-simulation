#!/usr/bin/env python
"""Directed analysis for selected Doppler ambiguity pairs."""

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

import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_best_claim_impersonation_first_pass as bestclaim  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_short_window_best_claim_first_pass as shortwin  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    p.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    p.add_argument("--pairs", nargs="+", default=["65409:65410", "65410:65409", "65411:47749", "48458:58380", "65693:47749"])
    p.add_argument("--window-duration-s", nargs="+", default=["30", "45", "60", "90", "120", "180", "full"])
    p.add_argument("--window-position", nargs="+", choices=["first", "middle", "last", "best_margin", "best_score"], default=["first", "middle", "last", "best_margin", "best_score"])
    p.add_argument("--window-step-s", type=float, default=10.0)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--eval-output", type=Path, default=Path("outputs/metrics/top_ambiguity_pair_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/top_ambiguity_pair_summary.csv"))
    p.add_argument("--curves-output", type=Path, default=Path("outputs/datasets/top_ambiguity_pair_window_curves.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/top_ambiguity_pair_analysis_summary.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures"))
    p.add_argument("--elevation-min-deg", type=float, default=20.0)
    p.add_argument("--seed", type=int, default=20260610)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def parse_pairs(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        if ":" not in value:
            active.fail(f"invalid pair format, expected true:claim: {value}")
        a, b = value.split(":", 1)
        pairs.append((a.strip(), b.strip()))
    return pairs


def parse_durations(values: list[str]) -> list[float | str]:
    out: list[float | str] = []
    for value in values:
        if str(value).lower() in {"full", "full_pass"}:
            out.append("full")
        else:
            out.append(float(value))
    return out


def check_outputs(args: argparse.Namespace) -> None:
    outputs = [args.eval_output, args.summary_output, args.curves_output, args.report_output]
    if not args.overwrite:
        existing = [str(p) for p in outputs if p.exists()]
        if existing:
            active.fail("outputs exist; add --overwrite: " + ", ".join(existing))
    for path in outputs:
        if args.overwrite and path.exists():
            path.unlink()


def append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, mode="a", index=False, header=not path.exists())


def load_common(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, tuple[float, float]], dict[str, dict[str, float]], dict[str, list[float]]]:
    ns = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        thresholds=args.thresholds,
        legit_results=args.legit_results,
        max_true_sats=9999,
        max_claim_candidates=9999,
    )
    return bestclaim.load_inputs(ns)


def fit_residual(y_obs: np.ndarray, f_geo: np.ndarray, t_rel: np.ndarray, mask: np.ndarray) -> tuple[base.FitResult, np.ndarray]:
    fit = base.fit_bias_and_slope(y_obs[mask], f_geo[mask], t_rel[mask])
    x = t_rel[mask] - float(np.mean(t_rel[mask]))
    delta = y_obs[mask] - f_geo[mask]
    residual = delta - (fit.b_hat_hz + fit.k_hat_hz_s * x)
    return fit, residual


def fixed_window(t_rel: np.ndarray, duration: float | str, position: str) -> dict[str, Any]:
    if duration == "full":
        mask = np.ones(len(t_rel), dtype=bool)
        return {"duration": "full", "position": "full_pass", "start": float(t_rel[0]), "end": float(t_rel[-1]), "mask": mask}
    wins = shortwin.fixed_windows(t_rel, float(duration), [position])
    if not wins:
        active.fail(f"no fixed window: duration={duration}, position={position}")
    w = wins[0]
    return {"duration": float(duration), "position": position, "start": w["window_start"], "end": w["window_end"], "mask": w["mask"]}


def best_window(
    t_rel: np.ndarray,
    duration: float,
    step_s: float,
    selector: str,
    y_obs: np.ndarray,
    f_self: np.ndarray,
    f_claim: np.ndarray,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_value = np.inf
    for w in shortwin.sliding_windows(t_rel, float(duration), float(step_s)):
        self_fit, _ = fit_residual(y_obs, f_self, t_rel, w["mask"])
        claim_fit, _ = fit_residual(y_obs, f_claim, t_rel, w["mask"])
        value = claim_fit.score_rmse_hz - self_fit.score_rmse_hz if selector == "best_margin" else claim_fit.score_rmse_hz
        if np.isfinite(value) and value < best_value:
            best_value = value
            best = {"duration": float(duration), "position": selector, "start": w["window_start"], "end": w["window_end"], "mask": w["mask"]}
    return best


def tle_metrics(tle: dict[str, dict[str, Any]], sat_id: str) -> dict[str, float]:
    model = tle[sat_id]["sat"].model
    return {
        "inclination_deg": float(np.degrees(model.inclo)),
        "raan_deg": float(np.degrees(model.nodeo) % 360.0),
        "mean_motion_rad_min": float(model.no_kozai),
        "mean_motion_rev_day": float(model.no_kozai * 1440.0 / (2.0 * np.pi)),
    }


def evaluate_pair_window(
    pair_id: str,
    true_id: str,
    claim_id: str,
    true_name: str,
    claim_name: str,
    t_rel: np.ndarray,
    y_obs: np.ndarray,
    f_self: np.ndarray,
    f_claim: np.ndarray,
    rr_self: np.ndarray,
    rr_claim: np.ndarray,
    elev_self: np.ndarray,
    elev_claim: np.ndarray,
    max_elev: dict[str, float],
    threshold_map: dict[str, tuple[float, float]],
    prior_map: dict[str, dict[str, float]],
    tle: dict[str, dict[str, Any]],
    window: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    mask = window["mask"]
    self_fit, self_residual = fit_residual(y_obs, f_self, t_rel, mask)
    claim_fit, claim_residual = fit_residual(y_obs, f_claim, t_rel, mask)
    claim_threshold_95, _ = threshold_map[claim_id]
    self_threshold_95, _ = threshold_map[true_id]
    self_prior = prior_map[true_id]
    claim_prior = prior_map[claim_id]
    self_b_gate = bool(self_prior["b_min"] <= self_fit.b_hat_hz <= self_prior["b_max"])
    self_k_gate = bool(self_prior["k_min"] <= self_fit.k_hat_hz_s <= self_prior["k_max"])
    claim_b_gate = bool(claim_prior["b_min"] <= claim_fit.b_hat_hz <= claim_prior["b_max"])
    claim_k_gate = bool(claim_prior["k_min"] <= claim_fit.k_hat_hz_s <= claim_prior["k_max"])
    claim_p95 = bool(claim_fit.score_rmse_hz <= claim_threshold_95)
    self_p95 = bool(self_fit.score_rmse_hz <= self_threshold_95)
    quality_ok = bool(max_elev.get(claim_id, -999.0) >= args.elevation_min_deg)
    strong_claim_accept = bool(claim_p95 and claim_k_gate and quality_ok)
    weak_claim_accept = bool(claim_p95 and quality_ok)
    strong_decision = active.tri_state_decision(bool(claim_p95 and claim_k_gate), max_elev.get(claim_id, np.nan), args.elevation_min_deg)
    weak_decision = active.tri_state_decision(claim_p95, max_elev.get(claim_id, np.nan), args.elevation_min_deg)
    rr_delta = rr_self[mask] - rr_claim[mask]
    delta = f_self[mask] - f_claim[mask]
    rr_corr = float(np.corrcoef(rr_self[mask], rr_claim[mask])[0, 1]) if int(mask.sum()) > 2 else np.nan
    doppler_corr = float(np.corrcoef(f_self[mask], f_claim[mask])[0, 1]) if int(mask.sum()) > 2 else np.nan
    true_geo = tle_metrics(tle, true_id)
    claim_geo = tle_metrics(tle, claim_id)
    inc_diff = abs(true_geo["inclination_deg"] - claim_geo["inclination_deg"])
    mm_diff = abs(true_geo["mean_motion_rev_day"] - claim_geo["mean_motion_rev_day"])
    raan_diff = abs((true_geo["raan_deg"] - claim_geo["raan_deg"] + 180.0) % 360.0 - 180.0)
    row = {
        "pair_id": pair_id,
        "true_sat": true_id,
        "claim_sat": claim_id,
        "true_name": true_name,
        "claim_name": claim_name,
        "window_duration_s": window["duration"],
        "window_position": window["position"],
        "window_start": float(window["start"]),
        "window_end": float(window["end"]),
        "window_step_s": float(args.window_step_s),
        "num_points": int(mask.sum()),
        "self_score": float(self_fit.score_rmse_hz),
        "claim_score": float(claim_fit.score_rmse_hz),
        "score_margin": float(claim_fit.score_rmse_hz - self_fit.score_rmse_hz),
        "strong_claim_decision": strong_decision,
        "weak_claim_decision": weak_decision,
        "strong_claim_accept": strong_claim_accept,
        "weak_claim_accept": weak_claim_accept,
        "weak_only_claim_accept": bool(weak_claim_accept and not strong_claim_accept),
        "claim_p95_accept": claim_p95,
        "self_p95_accept": self_p95,
        "self_b_hat": float(self_fit.b_hat_hz),
        "self_k_hat": float(self_fit.k_hat_hz_s),
        "claim_b_hat": float(claim_fit.b_hat_hz),
        "claim_k_hat": float(claim_fit.k_hat_hz_s),
        "self_b_gate_pass": self_b_gate,
        "self_k_gate_pass": self_k_gate,
        "claim_b_gate_pass": claim_b_gate,
        "claim_k_gate_pass": claim_k_gate,
        "range_rate_corr": rr_corr,
        "doppler_corr": doppler_corr,
        "range_rate_rmse_before_fit": float(np.sqrt(np.mean(rr_delta**2))),
        "residual_rmse_after_bk_fit": float(claim_fit.score_rmse_hz),
        "true_max_elevation": float(np.max(elev_self)),
        "claim_max_elevation": float(np.max(elev_claim)),
        "true_mean_elevation": float(np.mean(elev_self[mask])),
        "claim_mean_elevation": float(np.mean(elev_claim[mask])),
        "true_range_rate_start": float(rr_self[mask][0]),
        "true_range_rate_end": float(rr_self[mask][-1]),
        "claim_range_rate_start": float(rr_claim[mask][0]),
        "claim_range_rate_end": float(rr_claim[mask][-1]),
        "pass_time_overlap_s": float(window["end"] - window["start"]),
        "relative_pass_phase": float((window["start"] + window["end"]) / 2.0 / max(t_rel[-1], 1.0)),
        "true_inclination_deg": true_geo["inclination_deg"],
        "claim_inclination_deg": claim_geo["inclination_deg"],
        "true_raan_deg": true_geo["raan_deg"],
        "claim_raan_deg": claim_geo["raan_deg"],
        "true_mean_motion_rev_day": true_geo["mean_motion_rev_day"],
        "claim_mean_motion_rev_day": claim_geo["mean_motion_rev_day"],
        "inclination_diff_deg": float(inc_diff),
        "raan_diff_deg": float(raan_diff),
        "mean_motion_diff_rev_day": float(mm_diff),
        "same_orbital_plane_flag": bool(inc_diff < 0.05 and raan_diff < 1.0),
        "nearby_satellite_flag": bool(inc_diff < 0.05 and mm_diff < 0.02),
    }
    curve_rows: list[dict[str, Any]] = []
    masked_indices = np.flatnonzero(mask)
    for local_idx, idx in enumerate(masked_indices):
        curve_rows.append(
            {
                "pair_id": pair_id,
                "true_sat": true_id,
                "claim_sat": claim_id,
                "window_duration_s": window["duration"],
                "window_position": window["position"],
                "time_rel_s": float(t_rel[idx]),
                "f_obs_true": float(y_obs[idx]),
                "f_geo_self": float(f_self[idx]),
                "f_geo_claim": float(f_claim[idx]),
                "self_residual_after_bk": float(self_residual[local_idx]),
                "claim_residual_after_bk": float(claim_residual[local_idx]),
                "range_rate_true": float(rr_self[idx]),
                "range_rate_claim": float(rr_claim[idx]),
            }
        )
    return row, curve_rows


def summarize(eval_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (pair_id, true_sat, claim_sat, duration), g in eval_df.groupby(["pair_id", "true_sat", "claim_sat", "window_duration_s"], sort=False):
        min_idx = g["score_margin"].idxmin()
        rows.append(
            {
                "pair_id": pair_id,
                "true_sat": true_sat,
                "claim_sat": claim_sat,
                "window_duration_s": duration,
                "n_windows": int(len(g)),
                "min_score_margin": float(g["score_margin"].min()),
                "median_score_margin": float(g["score_margin"].median()),
                "p10_score_margin": float(g["score_margin"].quantile(0.10)),
                "best_margin_window_position": str(eval_df.loc[min_idx, "window_position"]),
                "num_nonself_best": int((g["score_margin"] < 0).sum()),
                "strong_accept_count": int(g["strong_claim_accept"].astype(bool).sum()),
                "weak_accept_count": int(g["weak_claim_accept"].astype(bool).sum()),
                "weak_only_accept_count": int(g["weak_only_claim_accept"].astype(bool).sum()),
                "median_range_rate_corr": float(g["range_rate_corr"].median()),
                "median_residual_rmse_after_bk_fit": float(g["residual_rmse_after_bk_fit"].median()),
                "claim_k_gate_fail_count": int((~g["claim_k_gate_pass"].astype(bool)).sum()),
                "claim_b_gate_fail_count": int((~g["claim_b_gate_pass"].astype(bool)).sum()),
            }
        )
    return pd.DataFrame(rows)


def plot_margin(summary: pd.DataFrame, out_dir: Path) -> Path | None:
    plot_df = summary[summary["window_duration_s"].astype(str) != "full"].copy()
    if plot_df.empty:
        return None
    plot_df["duration_float"] = plot_df["window_duration_s"].astype(float)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "top_ambiguity_pair_margin_vs_duration.png"
    fig, ax = plt.subplots(figsize=(9, 5))
    for pair_id, g in plot_df.groupby("pair_id", sort=False):
        gg = g.sort_values("duration_float")
        ax.plot(gg["duration_float"], gg["min_score_margin"], marker="o", label=str(pair_id))
    ax.axhline(0, color="#333333", linewidth=1, linestyle="--")
    ax.set_xlabel("Window duration (s)")
    ax.set_ylabel("Minimum score margin: claim - self (Hz)")
    ax.set_title("Top ambiguity pairs: minimum score margin vs window duration")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def plot_residual_example(curves: pd.DataFrame, eval_df: pd.DataFrame, out_dir: Path) -> Path | None:
    candidates = eval_df[
        (eval_df["true_sat"].astype(str) == "65409")
        & (eval_df["claim_sat"].astype(str) == "65410")
        & (eval_df["window_duration_s"].astype(str) == "30.0")
        & (eval_df["window_position"].astype(str) == "best_margin")
    ]
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    g = curves[
        (curves["pair_id"] == row["pair_id"])
        & (curves["window_duration_s"].astype(str) == str(row["window_duration_s"]))
        & (curves["window_position"].astype(str) == str(row["window_position"]))
    ]
    if g.empty:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "top_pair_65409_65410_30s_residuals.png"
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(g["time_rel_s"], g["self_residual_after_bk"], label="self residual after b/k")
    ax.plot(g["time_rel_s"], g["claim_residual_after_bk"], label="claim residual after b/k")
    ax.set_xlabel("t_rel_s")
    ax.set_ylabel("Residual after b/k fit (Hz)")
    ax.set_title("65409 -> 65410, 30s best-margin window")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def write_report(args: argparse.Namespace, eval_df: pd.DataFrame, summary: pd.DataFrame, figures: list[Path]) -> None:
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    summary_text = summary.to_markdown(index=False)
    weak = eval_df[eval_df["weak_claim_accept"].astype(bool)]
    strong = eval_df[eval_df["strong_claim_accept"].astype(bool)]
    k_fail = eval_df[(eval_df["weak_claim_accept"].astype(bool)) & (~eval_df["strong_claim_accept"].astype(bool))]
    focus_654 = summary[summary["pair_id"].astype(str).isin(["65409_to_65410", "65410_to_65409"])]
    other = summary[~summary["pair_id"].astype(str).isin(["65409_to_65410", "65410_to_65409"])]
    fig_text = "\n".join(f"- `{p}`" for p in figures) if figures else "未生成图。"
    text = f"""# Top Ambiguity Pair 定向分析总结

生成时间：{datetime.now().isoformat(timespec="seconds")}

## 1. 实验目的

上一轮 short-window best-claim 发现 30s 窗口会放大 ranking-level ambiguity，并在 weak-prior 下出现 `65409 <-> 65410` 的 non-self accept。本轮针对这些 top ambiguity pairs 做定向复测，判断它们是偶发现象还是稳定的 Doppler ambiguity pair。

## 2. 实验设置

- pairs：`{', '.join(args.pairs)}`
- window_duration_s：`{', '.join(args.window_duration_s)}`
- window_position：`{', '.join(args.window_position)}`
- window_step_s：`{args.window_step_s}`
- residual_mode：`{args.residual_mode}`
- strong-prior：residual score + claim k gate + quality gate
- weak-prior：residual score + quality gate，不用 b/k gate 直接拒绝

输出文件：

- `{args.eval_output}`
- `{args.summary_output}`
- `{args.curves_output}`
- `{args.report_output}`

图表：

{fig_text}

## 3. 65409 <-> 65410 重点分析

{focus_654.to_markdown(index=False) if not focus_654.empty else '无 65409/65410 结果。'}

weak-prior accept 总数为 `{len(weak)}`，strong-prior accept 总数为 `{len(strong)}`。weak-only claim accept 数为 `{len(k_fail)}`。如果 weak-only 样本存在，说明 residual score 已能通过 weak-prior，但 strong-prior 由 k gate 或质量门控拒绝。

## 4. 其他 Ambiguity Pairs

{other.to_markdown(index=False) if not other.empty else '无其他 pair 结果。'}

## 5. 总体结论

Ranking-level ambiguity 指短窗口下 claim score 接近 self 或进入 top-k，但未通过验证。Verification-level ambiguity 指 non-self claim 被 strong 或 weak-prior 接受。本轮中若接受只发生在 weak-prior，应解释为弱先验边界现象，不代表 strong-prior 被突破。

后续建议：对出现 weak-only accept 或负 margin 的 pair 进入正式 ambiguity cluster；并做 TLE误差、真实噪声敏感性以及多窗口一致性策略评估。短窗口 verifier 若不稳定，应优先输出 DEFER，而不是直接 ACCEPT。
"""
    args.report_output.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    check_outputs(args)
    pairs = parse_pairs(args.pairs)
    durations = parse_durations(args.window_duration_s)
    selection, library, orbit_cfg, tle, threshold_map, prior_map, ranges = load_common(args)
    station = bestclaim.make_station(orbit_cfg)
    ts = load.timescale()
    rng = np.random.default_rng(args.seed)
    eval_rows: list[dict[str, Any]] = []
    curve_rows_all: list[dict[str, Any]] = []

    for true_id, claim_id in pairs:
        rows = bestclaim.candidate_rows_for_true_window(library, true_id)
        geos = bestclaim.candidate_geometries(rows)
        names = bestclaim.claim_name_map(rows)
        if true_id not in geos or claim_id not in geos:
            print(f"warning: missing geometry for pair {true_id}->{claim_id}; skipped", file=sys.stderr)
            continue
        true_geo = geos[true_id].copy()
        claim_geo = geos[claim_id].copy()
        t_rel = true_geo["t_rel_s"].to_numpy(float)
        times = [base.parse_utc(v) for v in true_geo["t_abs_utc"].astype(str)]
        f_self = true_geo["f_geo_candidate_hz"].to_numpy(float)
        f_claim = claim_geo["f_geo_candidate_hz"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        freq_hz = float(true_geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in true_geo else 11_325_000_000.0
        geo_self_exact = bestclaim.station_geo_for_sat(tle[true_id]["sat"], times, ts, station, freq_hz, step_s)
        geo_claim_exact = bestclaim.station_geo_for_sat(tle[claim_id]["sat"], times, ts, station, freq_hz, step_s)
        rr_self = geo_self_exact["range_rate_mps"].to_numpy(float)
        rr_claim = geo_claim_exact["range_rate_mps"].to_numpy(float)
        elev_self = geo_self_exact["elevation_deg"].to_numpy(float)
        elev_claim = geo_claim_exact["elevation_deg"].to_numpy(float)
        max_elev = {true_id: float(np.nanmax(elev_self)), claim_id: float(np.nanmax(elev_claim))}
        terms = active.sample_residual_terms(t_rel, args.residual_mode, ranges, rng)
        y_obs, _noise, _b, _k, _sigma, _t0 = active.apply_residual_terms(f_self, t_rel, terms)
        pair_id = f"{true_id}_to_{claim_id}"

        for duration in durations:
            windows: list[dict[str, Any]] = []
            if duration == "full":
                windows.append(fixed_window(t_rel, "full", "full_pass"))
            else:
                for pos in args.window_position:
                    if pos in {"first", "middle", "last"}:
                        windows.append(fixed_window(t_rel, float(duration), pos))
                    elif pos == "best_margin":
                        w = best_window(t_rel, float(duration), args.window_step_s, "best_margin", y_obs, f_self, f_claim)
                        if w is not None:
                            windows.append(w)
                    elif pos == "best_score":
                        w = best_window(t_rel, float(duration), args.window_step_s, "best_score", y_obs, f_self, f_claim)
                        if w is not None:
                            windows.append(w)
            for w in windows:
                row, curves = evaluate_pair_window(
                    pair_id,
                    true_id,
                    claim_id,
                    names.get(true_id, true_id),
                    names.get(claim_id, claim_id),
                    t_rel,
                    y_obs,
                    f_self,
                    f_claim,
                    rr_self,
                    rr_claim,
                    elev_self,
                    elev_claim,
                    max_elev,
                    threshold_map,
                    prior_map,
                    tle,
                    w,
                    args,
                )
                eval_rows.append(row)
                curve_rows_all.extend(curves)
                append_rows(args.eval_output, [row])
                append_rows(args.curves_output, curves)
                print(f"checkpoint {pair_id} duration={w['duration']} position={w['position']} margin={row['score_margin']:.3f}")

    eval_df = pd.DataFrame(eval_rows)
    summary = summarize(eval_df)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    figures: list[Path] = []
    p = plot_margin(summary, args.figures_dir)
    if p is not None:
        figures.append(p)
    curves_df = pd.DataFrame(curve_rows_all)
    p = plot_residual_example(curves_df, eval_df, args.figures_dir)
    if p is not None:
        figures.append(p)
    write_report(args, eval_df, summary, figures)
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.report_output}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
