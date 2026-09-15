#!/usr/bin/env python
"""Short-window best-claim Doppler ambiguity first pass."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_best_claim_impersonation_first_pass as bestclaim  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    p.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/short_window_best_claim_sequence_eval.csv"))
    p.add_argument("--candidate-scores-output", type=Path, default=Path("outputs/datasets/short_window_best_claim_candidate_scores.csv"))
    p.add_argument("--ambiguity-pairs-output", type=Path, default=Path("outputs/metrics/short_window_doppler_ambiguity_pairs.csv"))
    p.add_argument("--ambiguity-summary-output", type=Path, default=Path("outputs/metrics/short_window_doppler_ambiguity_summary.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/short_window_best_claim_summary.md"))
    p.add_argument("--max-true-sats", type=int, default=5)
    p.add_argument("--max-claim-candidates", type=int, default=100)
    p.add_argument("--candidate-pool", choices=["visible", "all_sampled"], default="all_sampled")
    p.add_argument("--residual-mode", choices=["clean", "empirical", "both"], default="empirical")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--window-mode", nargs="+", choices=["full_pass", "fixed_duration", "best_duration"], default=["fixed_duration"])
    p.add_argument("--window-duration-s", nargs="+", type=float, default=[60.0, 120.0])
    p.add_argument("--window-position", nargs="+", choices=["first", "middle", "last"], default=["first", "middle", "last"])
    p.add_argument("--window-step-s", type=float, default=10.0)
    p.add_argument("--elevation-min-deg", type=float, default=20.0)
    p.add_argument("--visible-elevation-min-deg", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=20260609)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def check_outputs(args: argparse.Namespace) -> None:
    outputs = [
        args.sequence_output,
        args.candidate_scores_output,
        args.ambiguity_pairs_output,
        args.ambiguity_summary_output,
        args.report_output,
    ]
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


def selected_modes(mode: str) -> list[str]:
    return ["clean", "empirical"] if mode == "both" else [mode]


def contiguous_mask(t_rel: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    return (t_rel >= float(start_s) - 1e-9) & (t_rel <= float(end_s) + 1e-9)


def fixed_windows(t_rel: np.ndarray, duration_s: float, positions: list[str]) -> list[dict[str, Any]]:
    span = float(t_rel[-1] - t_rel[0])
    duration = min(float(duration_s), span)
    starts: dict[str, float] = {
        "first": float(t_rel[0]),
        "middle": float(t_rel[0] + (span - duration) / 2.0),
        "last": float(t_rel[-1] - duration),
    }
    windows: list[dict[str, Any]] = []
    for pos in positions:
        start = starts[pos]
        end = start + duration
        mask = contiguous_mask(t_rel, start, end)
        if int(mask.sum()) >= 3:
            windows.append({"window_position": pos, "window_start": start, "window_end": end, "mask": mask})
    return windows


def sliding_windows(t_rel: np.ndarray, duration_s: float, step_s: float) -> list[dict[str, Any]]:
    span = float(t_rel[-1] - t_rel[0])
    duration = min(float(duration_s), span)
    if duration <= 0:
        return []
    starts = np.arange(float(t_rel[0]), float(t_rel[-1] - duration) + 1e-9, float(step_s))
    windows: list[dict[str, Any]] = []
    for idx, start in enumerate(starts):
        end = float(start + duration)
        mask = contiguous_mask(t_rel, float(start), end)
        if int(mask.sum()) >= 3:
            windows.append({"window_position": f"best_{idx:03d}", "window_start": float(start), "window_end": end, "mask": mask})
    return windows


def fit_window(
    y_obs: np.ndarray,
    f_geo_claim: np.ndarray,
    t_rel: np.ndarray,
    mask: np.ndarray,
) -> base.FitResult:
    return base.fit_bias_and_slope(y_obs[mask], f_geo_claim[mask], t_rel[mask])


def tri_decision(score_ok: bool, max_elev: float, elevation_min: float) -> str:
    return active.tri_state_decision(bool(score_ok), float(max_elev), float(elevation_min))


def evaluate_window(
    sequence_id: str,
    true_id: str,
    true_name: str,
    claim_ids: list[str],
    names: dict[str, str],
    geos: dict[str, pd.DataFrame],
    f_geo_true: np.ndarray,
    y_obs: np.ndarray,
    t_rel: np.ndarray,
    max_elev: dict[str, float],
    threshold_map: dict[str, tuple[float, float]],
    prior_map: dict[str, dict[str, float]],
    mask: np.ndarray,
    args: argparse.Namespace,
    mode: str,
    window_mode: str,
    duration_s: float,
    window_position: str,
    window_start: float,
    window_end: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate_rows: list[dict[str, Any]] = []
    for claim_id in claim_ids:
        f_geo_claim = geos[claim_id]["f_geo_candidate_hz"].to_numpy(float)
        fit = fit_window(y_obs, f_geo_claim, t_rel, mask)
        threshold_95, threshold_99 = threshold_map[claim_id]
        prior = prior_map[claim_id]
        b_gate = bool(prior["b_min"] <= fit.b_hat_hz <= prior["b_max"])
        k_gate = bool(prior["k_min"] <= fit.k_hat_hz_s <= prior["k_max"])
        p95_accept = bool(fit.score_rmse_hz <= threshold_95)
        quality_ok = bool(max_elev.get(claim_id, -999.0) >= float(args.elevation_min_deg))
        strong_accept = bool(p95_accept and k_gate and quality_ok)
        weak_accept = bool(p95_accept and quality_ok)
        corr = float(np.corrcoef(f_geo_true[mask], f_geo_claim[mask])[0, 1]) if int(mask.sum()) > 2 else np.nan
        candidate_rows.append(
            {
                "sequence_id": sequence_id,
                "true_sat": true_id,
                "true_sat_name": true_name,
                "claim_sat": claim_id,
                "claim_sat_name": names.get(claim_id, claim_id),
                "candidate_pool": args.candidate_pool,
                "residual_mode": mode,
                "window_mode": window_mode,
                "window_duration_s": float(duration_s),
                "window_position": window_position,
                "window_start": float(window_start),
                "window_end": float(window_end),
                "score": float(fit.score_rmse_hz),
                "threshold_95_hz": float(threshold_95),
                "p95_accept": p95_accept,
                "b_hat": float(fit.b_hat_hz),
                "k_hat": float(fit.k_hat_hz_s),
                "b_gate_pass": b_gate,
                "k_gate_pass": k_gate,
                "strong_accept": strong_accept,
                "weak_accept": weak_accept,
                "strong_tri_decision": tri_decision(bool(p95_accept and k_gate), max_elev.get(claim_id, np.nan), args.elevation_min_deg),
                "weak_tri_decision": tri_decision(p95_accept, max_elev.get(claim_id, np.nan), args.elevation_min_deg),
                "max_elevation_claim": float(max_elev.get(claim_id, np.nan)),
                "range_rate_corr": corr,
            }
        )
    candidate_rows = sorted(candidate_rows, key=lambda r: (float(r["score"]), str(r["claim_sat"])))
    for rank, row in enumerate(candidate_rows, start=1):
        row["candidate_rank"] = int(rank)

    best = candidate_rows[0]
    self_rows = [r for r in candidate_rows if str(r["claim_sat"]) == true_id]
    nonself_rows = [r for r in candidate_rows if str(r["claim_sat"]) != true_id]
    self_row = self_rows[0] if self_rows else None
    best_nonself = nonself_rows[0] if nonself_rows else None
    self_score = float(self_row["score"]) if self_row else np.nan
    best_nonself_score = float(best_nonself["score"]) if best_nonself else np.nan
    margin = best_nonself_score - self_score if np.isfinite(self_score) and np.isfinite(best_nonself_score) else np.nan
    strong_nonself = int(sum(bool(r["strong_accept"]) for r in nonself_rows))
    weak_nonself = int(sum(bool(r["weak_accept"]) for r in nonself_rows))
    sequence_row = {
        "sequence_id": sequence_id,
        "true_sat": true_id,
        "true_sat_name": true_name,
        "candidate_pool": args.candidate_pool,
        "residual_mode": mode,
        "window_mode": window_mode,
        "window_duration_s": float(duration_s),
        "window_position": window_position,
        "window_start": float(window_start),
        "window_end": float(window_end),
        "num_claim_candidates": int(len(candidate_rows)),
        "best_claim_sat": best["claim_sat"],
        "is_self_best": bool(str(best["claim_sat"]) == true_id),
        "self_score": self_score,
        "self_rank": int(self_row["candidate_rank"]) if self_row else -1,
        "best_nonself_claim_sat": best_nonself["claim_sat"] if best_nonself else "",
        "best_nonself_score": best_nonself_score,
        "best_nonself_rank": int(best_nonself["candidate_rank"]) if best_nonself else -1,
        "score_margin_self_to_best_nonself": margin,
        "strong_best_claim_decision": best["strong_tri_decision"],
        "weak_best_claim_decision": best["weak_tri_decision"],
        "strong_best_claim_accept": bool(best["strong_accept"]),
        "weak_best_claim_accept": bool(best["weak_accept"]),
        "strong_self_accept": bool(self_row["strong_accept"]) if self_row else False,
        "weak_self_accept": bool(self_row["weak_accept"]) if self_row else False,
        "strong_nonself_accept": bool(strong_nonself > 0),
        "weak_nonself_accept": bool(weak_nonself > 0),
        "weak_only_nonself_accept": bool(weak_nonself > strong_nonself),
        "strong_nonself_accept_count": strong_nonself,
        "weak_nonself_accept_count": weak_nonself,
        "self_b_hat": float(self_row["b_hat"]) if self_row else np.nan,
        "self_k_hat": float(self_row["k_hat"]) if self_row else np.nan,
        "best_nonself_b_hat": float(best_nonself["b_hat"]) if best_nonself else np.nan,
        "best_nonself_k_hat": float(best_nonself["k_hat"]) if best_nonself else np.nan,
        "top5_self": bool((int(self_row["candidate_rank"]) if self_row else 999999) <= 5),
    }
    return sequence_row, candidate_rows


def summarize(seq: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = ["candidate_pool", "residual_mode", "window_mode", "window_duration_s"]
    for keys, g in seq.groupby(group_cols, sort=True):
        pool, mode, window_mode, duration = keys
        sg = scores[
            (scores["candidate_pool"] == pool)
            & (scores["residual_mode"] == mode)
            & (scores["window_mode"] == window_mode)
            & (scores["window_duration_s"].astype(float) == float(duration))
        ]
        n = len(g)
        rows.append(
            {
                "candidate_pool": pool,
                "residual_mode": mode,
                "window_mode": window_mode,
                "window_duration_s": float(duration),
                "n_sequences": int(n),
                "n_candidate_scores": int(len(sg)),
                "num_claim_candidates_median": float(g["num_claim_candidates"].median()),
                "top1_self_rate": float(g["is_self_best"].mean()) if n else np.nan,
                "top5_self_rate": float(g["top5_self"].mean()) if n else np.nan,
                "non_self_best_count": int((~g["is_self_best"].astype(bool)).sum()),
                "non_self_best_rate": float((~g["is_self_best"].astype(bool)).mean()) if n else np.nan,
                "strong_nonself_accept_count": int(g["strong_nonself_accept_count"].sum()),
                "weak_nonself_accept_count": int(g["weak_nonself_accept_count"].sum()),
                "weak_only_nonself_accept_count": int(g["weak_only_nonself_accept"].astype(bool).sum()),
                "self_score_median": float(g["self_score"].median()),
                "best_nonself_score_median": float(g["best_nonself_score"].median()),
                "score_margin_self_to_best_nonself_median": float(g["score_margin_self_to_best_nonself"].median()),
                "score_margin_self_to_best_nonself_p10": float(g["score_margin_self_to_best_nonself"].quantile(0.10)),
                "score_margin_self_to_best_nonself_min": float(g["score_margin_self_to_best_nonself"].min()),
            }
        )
    return pd.DataFrame(rows)


def ambiguity_pairs(seq: pd.DataFrame, scores: pd.DataFrame, top_k: int) -> pd.DataFrame:
    top = scores[scores["candidate_rank"] <= int(top_k)].copy()
    margins = seq.set_index("sequence_id")["score_margin_self_to_best_nonself"].to_dict()
    top["score_margin_to_self"] = top["sequence_id"].map(seq.set_index("sequence_id")["self_score"].to_dict())
    top["score_margin_to_self"] = top["score"] - top["score_margin_to_self"]
    rows: list[dict[str, Any]] = []
    group_cols = ["true_sat", "claim_sat", "window_duration_s"]
    totals = seq.groupby(["true_sat", "window_duration_s"]).size().to_dict()
    best_nonself = set(zip(seq["sequence_id"], seq["best_nonself_claim_sat"].astype(str)))
    for (true_sat, claim_sat, duration), g in top.groupby(group_cols, sort=True):
        count = len(g)
        rows.append(
            {
                "true_sat": true_sat,
                "claim_sat": claim_sat,
                "window_duration_s": float(duration),
                "count_in_topk": int(count),
                "count_as_nonself_best": int(sum((sid, str(claim_sat)) in best_nonself and str(true_sat) != str(claim_sat) for sid in g["sequence_id"])),
                "mean_rank": float(g["candidate_rank"].mean()),
                "median_rank": float(g["candidate_rank"].median()),
                "median_score": float(g["score"].median()),
                "median_score_margin_to_self": float(g["score_margin_to_self"].median()),
                "median_range_rate_corr": float(g["range_rate_corr"].median()),
                "strong_accept_count": int(g["strong_accept"].astype(bool).sum()),
                "weak_accept_count": int(g["weak_accept"].astype(bool).sum()),
                "confusion_rate": float(count / totals.get((true_sat, duration), count)),
                "is_self_pair": bool(str(true_sat) == str(claim_sat)),
            }
        )
    return pd.DataFrame(rows).sort_values(["is_self_pair", "count_in_topk", "mean_rank"], ascending=[True, False, True]).reset_index(drop=True)


def ambiguity_summary(seq: pd.DataFrame, scores: pd.DataFrame, pairs: pd.DataFrame, top_k: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (pool, mode, window_mode, duration), g in seq.groupby(["candidate_pool", "residual_mode", "window_mode", "window_duration_s"], sort=True):
        rows.append(
            {
                "candidate_pool": pool,
                "residual_mode": mode,
                "window_mode": window_mode,
                "window_duration_s": float(duration),
                "top_k": int(top_k),
                "num_sequences": int(len(g)),
                "num_non_self_best": int((~g["is_self_best"].astype(bool)).sum()),
                "num_pairs_in_topk": int(len(pairs[pairs["window_duration_s"].astype(float) == float(duration)])),
                "strong_nonself_accept_count": int(g["strong_nonself_accept_count"].sum()),
                "weak_nonself_accept_count": int(g["weak_nonself_accept_count"].sum()),
                "median_margin": float(g["score_margin_self_to_best_nonself"].median()),
            }
        )
    return pd.DataFrame(rows)


def write_report(args: argparse.Namespace, summary: pd.DataFrame, pairs: pd.DataFrame) -> None:
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    summary_text = summary.to_markdown(index=False) if not summary.empty else "无 summary 输出。"
    nonself_pairs = pairs[pairs["true_sat"].astype(str) != pairs["claim_sat"].astype(str)].copy() if not pairs.empty else pd.DataFrame()
    pair_cols = ["true_sat", "claim_sat", "window_duration_s", "count_in_topk", "count_as_nonself_best", "mean_rank", "median_score", "median_score_margin_to_self", "median_range_rate_corr", "strong_accept_count", "weak_accept_count"]
    by_count = nonself_pairs.sort_values(["count_in_topk", "count_as_nonself_best", "mean_rank"], ascending=[False, False, True]).head(20)
    by_score = nonself_pairs.sort_values(["median_score", "mean_rank"], ascending=[True, True]).head(20)
    pair_count_text = by_count[pair_cols].to_markdown(index=False) if not by_count.empty else "无 non-self top-k pair。"
    pair_score_text = by_score[pair_cols].to_markdown(index=False) if not by_score.empty else "无 non-self top-k pair。"
    text = f"""# Short-Window Best-Claim / Ambiguity First Pass

生成时间：{datetime.now().isoformat(timespec="seconds")}

## 1. 实验目的

完整窗口 best-claim 实验中，真实身份稳定 top-1，未发现 non-self accept。本轮测试窗口缩短后，多普勒身份可区分性是否下降，以及 ranking-level ambiguity 是否会放大为 verification-level ambiguity。

## 2. 实验设置

- max_true_sats：`{args.max_true_sats}`
- candidate_pool：`{args.candidate_pool}`
- max_claim_candidates：`{args.max_claim_candidates}`
- residual_mode：`{args.residual_mode}`
- window_mode：`{', '.join(args.window_mode)}`
- window_duration_s：`{', '.join(str(v) for v in args.window_duration_s)}`
- window_step_s：`{args.window_step_s}`
- strong-prior：score + per-target k gate + quality gate
- weak-prior：score + quality gate，不用 b/k gate 直接拒绝
- incremental write：每条窗口 sequence 完成后追加写入 sequence/candidate CSV

输出文件：

- `{args.sequence_output}`
- `{args.candidate_scores_output}`
- `{args.ambiguity_pairs_output}`
- `{args.ambiguity_summary_output}`

## 3. 短窗口 Best-Claim 结果

{summary_text}

如果短窗口出现 non-self best 或 non-self accept，应进入定向 ambiguity cluster 分析。如果只是 margin 变小但未接受，说明仍停留在 ranking-level ambiguity。

## 4. Ambiguity Pair 结果

Top pairs by count_in_topk：

{pair_count_text}

Top pairs by lowest median_score：

{pair_score_text}

## 5. 结论与下一步

短窗口是可识别性边界测试，不应直接作为最终身份判定。如果短窗口不稳定，最终 verifier 对短窗口应倾向输出 DEFER，而不是 ACCEPT。后续方向根据本轮结果选择：ambiguity cluster 定向分析、open-set unknown rejection，或 TLE误差 / 真实噪声敏感性。
"""
    args.report_output.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    check_outputs(args)
    selection, library, orbit_cfg, tle, threshold_map, prior_map, ranges = bestclaim.load_inputs(args)
    station = bestclaim.make_station(orbit_cfg)
    ts = load.timescale()
    rng = np.random.default_rng(args.seed)
    modes = selected_modes(args.residual_mode)
    seq_counter = 1

    for _, true_row in selection.iterrows():
        true_id = str(true_row["target_norad_id"])
        true_name = str(true_row["target_name"])
        rows = bestclaim.candidate_rows_for_true_window(library, true_id)
        geos = bestclaim.candidate_geometries(rows)
        names = bestclaim.claim_name_map(rows)
        if true_id not in geos:
            active.fail(f"true sat not available in claim geos: {true_id}")
        true_geo = geos[true_id]
        t_rel = true_geo["t_rel_s"].to_numpy(float)
        times = [base.parse_utc(v) for v in true_geo["t_abs_utc"].astype(str)]
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else float(true_row.get("step_s", 1.0))
        freq_hz = float(true_geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in true_geo else 11_325_000_000.0
        claim_ids_all = [cid for cid in geos if cid in threshold_map and cid in prior_map and cid in tle]
        max_elev = bestclaim.max_elevation_for_claims(claim_ids_all, tle, times, ts, station, freq_hz, step_s)
        claim_ids = bestclaim.choose_claim_pool(rows, claim_ids_all, max_elev, args)
        if true_id not in claim_ids and true_id in claim_ids_all:
            claim_ids = ([true_id] + claim_ids)[: max(1, int(args.max_claim_candidates))]
        f_geo_true = true_geo["f_geo_candidate_hz"].to_numpy(float)

        for mode in modes:
            terms = active.sample_residual_terms(t_rel, mode, ranges, rng)
            y_obs, _noise, _b, _k, _sigma, _t0 = active.apply_residual_terms(f_geo_true, t_rel, terms)
            eval_jobs: list[dict[str, Any]] = []
            if "full_pass" in args.window_mode:
                mask = np.ones(len(t_rel), dtype=bool)
                eval_jobs.append({"window_mode": "full_pass", "duration": float(t_rel[-1] - t_rel[0]), "position": "full", "start": float(t_rel[0]), "end": float(t_rel[-1]), "mask": mask})
            if "fixed_duration" in args.window_mode:
                for duration in args.window_duration_s:
                    for win in fixed_windows(t_rel, duration, args.window_position):
                        eval_jobs.append({"window_mode": "fixed_duration", "duration": float(duration), "position": win["window_position"], "start": win["window_start"], "end": win["window_end"], "mask": win["mask"]})
            if "best_duration" in args.window_mode:
                for duration in args.window_duration_s:
                    best_job = None
                    best_margin = np.inf
                    for win in sliding_windows(t_rel, duration, args.window_step_s):
                        tmp_seq, _tmp_scores = evaluate_window(
                            "candidate",
                            true_id,
                            true_name,
                            claim_ids,
                            names,
                            geos,
                            f_geo_true,
                            y_obs,
                            t_rel,
                            max_elev,
                            threshold_map,
                            prior_map,
                            win["mask"],
                            args,
                            mode,
                            "best_duration",
                            float(duration),
                            win["window_position"],
                            win["window_start"],
                            win["window_end"],
                        )
                        margin = float(tmp_seq["score_margin_self_to_best_nonself"])
                        if np.isfinite(margin) and margin < best_margin:
                            best_margin = margin
                            best_job = win
                    if best_job is not None:
                        eval_jobs.append({"window_mode": "best_duration", "duration": float(duration), "position": best_job["window_position"], "start": best_job["window_start"], "end": best_job["window_end"], "mask": best_job["mask"]})

            for job in eval_jobs:
                sequence_id = f"sw_best_claim_{seq_counter:06d}"
                seq_counter += 1
                seq_row, score_rows = evaluate_window(
                    sequence_id,
                    true_id,
                    true_name,
                    claim_ids,
                    names,
                    geos,
                    f_geo_true,
                    y_obs,
                    t_rel,
                    max_elev,
                    threshold_map,
                    prior_map,
                    job["mask"],
                    args,
                    mode,
                    job["window_mode"],
                    job["duration"],
                    job["position"],
                    job["start"],
                    job["end"],
                )
                append_rows(args.sequence_output, [seq_row])
                append_rows(args.candidate_scores_output, score_rows)
                print(f"checkpoint {sequence_id} true_sat={true_id} mode={job['window_mode']} duration={job['duration']} candidates={len(score_rows)}")

    seq = pd.read_csv(args.sequence_output)
    scores = pd.read_csv(args.candidate_scores_output)
    summary = summarize(seq, scores)
    pairs = ambiguity_pairs(seq, scores, args.top_k)
    amb_summary = ambiguity_summary(seq, scores, pairs, args.top_k)
    for path, df in [
        (args.ambiguity_pairs_output, pairs),
        (args.ambiguity_summary_output, amb_summary),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        print(f"wrote {path} rows={len(df)}")
    write_report(args, summary, pairs)
    print(f"wrote {args.report_output}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
