#!/usr/bin/env python
"""Best-claim Doppler ambiguity first-pass experiment.

This runner keeps the observation model deliberately simple: a true satellite B
generates an uncompensated single-station Doppler curve with the empirical
effective residual model, then the existing claimed-identity residual score is
evaluated against a pool of possible claim identities A_i on the same time grid.
"""

from __future__ import annotations

import argparse
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
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402


RESIDUAL_MODES = ["clean", "empirical"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--thresholds", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_thresholds.csv"))
    p.add_argument("--legit-results", type=Path, default=Path("outputs/metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/best_claim_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/best_claim_summary.csv"))
    p.add_argument("--candidate-scores-output", type=Path, default=Path("outputs/datasets/best_claim_candidate_scores.csv"))
    p.add_argument("--ambiguity-pairs-output", type=Path, default=Path("outputs/metrics/doppler_ambiguity_pairs.csv"))
    p.add_argument("--ambiguity-summary-output", type=Path, default=Path("outputs/metrics/doppler_ambiguity_summary.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/best_claim_ambiguity_first_pass_summary.md"))
    p.add_argument("--max-true-sats", type=int, default=5)
    p.add_argument("--max-claim-candidates", type=int, default=50)
    p.add_argument("--candidate-pool", choices=["visible", "all_sampled"], default="visible")
    p.add_argument("--residual-mode", choices=["clean", "empirical", "both"], default="empirical")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--elevation-min-deg", type=float, default=20.0)
    p.add_argument("--visible-elevation-min-deg", type=float, default=0.0)
    p.add_argument("--seed", type=int, default=20260609)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--flush-every", type=int, default=1)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def selected_modes(mode: str) -> list[str]:
    return RESIDUAL_MODES if mode == "both" else [mode]


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        active.fail("outputs exist; add --overwrite: " + ", ".join(existing))


def prepare_outputs(args: argparse.Namespace) -> set[tuple[str, str]]:
    outputs = [
        args.sequence_output,
        args.summary_output,
        args.candidate_scores_output,
        args.ambiguity_pairs_output,
        args.ambiguity_summary_output,
        args.report_output,
    ]
    if args.resume:
        completed: set[tuple[str, str]] = set()
        if args.sequence_output.exists() and args.sequence_output.stat().st_size > 2:
            existing = pd.read_csv(args.sequence_output)
            if {"true_sat", "residual_mode"}.issubset(existing.columns):
                completed = {
                    (str(r.true_sat), str(r.residual_mode))
                    for r in existing[["true_sat", "residual_mode"]].drop_duplicates().itertuples(index=False)
                }
        return completed
    check_outputs(outputs, args.overwrite)
    if args.overwrite:
        for path in outputs:
            if path.exists():
                path.unlink()
    return set()


def append_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(path, mode="a", index=False, header=not path.exists())


def require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        active.fail(f"{name} missing columns: {', '.join(missing)}")


def load_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, tuple[float, float]], dict[str, dict[str, float]], dict[str, list[float]]]:
    common_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        thresholds=args.thresholds,
        legit_results=args.legit_results,
        max_targets=max(args.max_true_sats, args.max_claim_candidates),
    )
    selection, library, orbit_cfg, tle, threshold_map, _k_map, ranges = active.load_common_inputs(common_args)
    selection = selection.head(args.max_true_sats).copy()

    thresholds = pd.read_csv(args.thresholds)
    require_columns(thresholds, ["target_norad", "threshold_95_hz", "threshold_99_hz"], "thresholds")
    threshold_map = {
        str(r.target_norad): (float(r.threshold_95_hz), float(r.threshold_99_hz))
        for r in thresholds.itertuples(index=False)
    }

    legit = pd.read_csv(args.legit_results)
    require_columns(legit, ["target_norad", "b_hat_hz", "k_hat_hz_s"], "legit results")
    prior_map: dict[str, dict[str, float]] = {}
    for tid, g in legit.groupby(legit["target_norad"].astype(str), sort=False):
        prior_map[str(tid)] = {
            "b_min": float(g["b_hat_hz"].quantile(0.05)),
            "b_max": float(g["b_hat_hz"].quantile(0.95)),
            "k_min": float(g["k_hat_hz_s"].quantile(0.01)),
            "k_max": float(g["k_hat_hz_s"].quantile(0.99)),
        }

    calibrated = set(threshold_map) & set(prior_map)
    if not calibrated:
        active.fail("no calibrated claim identities found in thresholds and legit results")
    library = library[library["candidate_norad_id"].astype(str).isin(calibrated)].copy()
    if library.empty:
        active.fail("candidate library has no rows for calibrated claim identities")

    return selection, library, orbit_cfg, tle, threshold_map, prior_map, ranges


def make_station(orbit_cfg: dict[str, Any]) -> Any:
    station_cfg = orbit_cfg["station"]
    return orbit_builder.wgs84.latlon(
        float(station_cfg["lat_deg"]),
        float(station_cfg["lon_deg"]),
        elevation_m=float(station_cfg["alt_m"]),
    )


def station_geo_for_sat(
    sat: Any,
    times: list[datetime],
    ts: Any,
    station: Any,
    freq_hz: float,
    step_s: float,
) -> pd.DataFrame:
    return orbit_builder.geo_curve(sat, station, ts, times, float(freq_hz), float(step_s))


def candidate_rows_for_true_window(library: pd.DataFrame, true_norad: str) -> pd.DataFrame:
    rows = library[library["target_norad_id"].astype(str) == str(true_norad)].copy()
    if rows.empty:
        active.fail(f"candidate library missing true window: {true_norad}")
    return rows


def candidate_geometries(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for claim_id, g in rows.groupby(rows["candidate_norad_id"].astype(str), sort=False):
        out[str(claim_id)] = g.sort_values("t_rel_s").reset_index(drop=True)
    return out


def claim_name_map(rows: pd.DataFrame) -> dict[str, str]:
    return {
        str(r.candidate_norad_id): str(r.candidate_name)
        for r in rows[["candidate_norad_id", "candidate_name"]].drop_duplicates().itertuples(index=False)
    }


def max_elevation_for_claims(
    claim_ids: list[str],
    tle: dict[str, dict[str, Any]],
    times: list[datetime],
    ts: Any,
    station: Any,
    freq_hz: float,
    step_s: float,
) -> dict[str, float]:
    max_elev: dict[str, float] = {}
    for claim_id in claim_ids:
        if claim_id not in tle:
            continue
        geo = station_geo_for_sat(tle[claim_id]["sat"], times, ts, station, freq_hz, step_s)
        max_elev[claim_id] = float(geo["elevation_deg"].max())
    return max_elev


def choose_claim_pool(
    rows: pd.DataFrame,
    claim_ids: list[str],
    max_elev: dict[str, float],
    args: argparse.Namespace,
) -> list[str]:
    order_map: dict[str, float] = {}
    if "candidate_rank_or_selection_order" in rows.columns:
        rank_rows = rows[["candidate_norad_id", "candidate_rank_or_selection_order"]].drop_duplicates()
        order_map = {str(r.candidate_norad_id): float(r.candidate_rank_or_selection_order) for r in rank_rows.itertuples(index=False)}
    else:
        order_map = {cid: float(i + 1) for i, cid in enumerate(claim_ids)}

    if args.candidate_pool == "visible":
        filtered = [cid for cid in claim_ids if max_elev.get(cid, -999.0) >= float(args.visible_elevation_min_deg)]
        if not filtered:
            filtered = claim_ids.copy()
    else:
        filtered = claim_ids.copy()

    filtered = sorted(filtered, key=lambda cid: (order_map.get(cid, 1e9), cid))
    return filtered[: max(1, int(args.max_claim_candidates))]


def build_observation(
    sequence_id: str,
    true_name: str,
    true_id: str,
    true_geo: pd.DataFrame,
    f_obs: np.ndarray,
    noise: np.ndarray,
    b_inj: float,
    k_inj: float,
    sigma_inj: float,
    t0_s: float,
    residual_mode: str,
) -> base.ObservationSequence:
    return base.ObservationSequence(
        sequence_id=sequence_id,
        source_type="BEST_CLAIM_ATTACK",
        claimed_target_name=true_name,
        claimed_target_norad=true_id,
        t_abs_utc=true_geo["t_abs_utc"].to_numpy(str),
        t_rel_s=true_geo["t_rel_s"].to_numpy(float),
        y_obs_hz=f_obs,
        f_geo_source_hz=true_geo["f_geo_candidate_hz"].to_numpy(float),
        noise_hz=noise,
        b_true_hz=float(b_inj),
        k_true_hz_s=float(k_inj),
        sigma_true_hz=float(sigma_inj),
        t0_s=float(t0_s),
        sample_id=1,
        attack_type="best_claim_uncompensated_first_pass",
        attack_variant=residual_mode,
        metadata={"true_sat": true_name, "true_norad": true_id, "residual_mode": residual_mode},
    )


def summarize_sequences(seq: pd.DataFrame, scores: pd.DataFrame | None = None) -> pd.DataFrame:
    if seq.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (pool, mode), g in seq.groupby(["candidate_pool", "residual_mode"], sort=True):
        n = len(g)
        score_g = pd.DataFrame()
        if scores is not None and not scores.empty:
            score_g = scores[(scores["candidate_pool"] == pool) & (scores["residual_mode"] == mode)]
        nonself_scores = score_g[score_g["true_sat"].astype(str) != score_g["claim_sat"].astype(str)] if not score_g.empty else pd.DataFrame()
        strong_nonself = int(nonself_scores["strong_accept"].astype(bool).sum()) if not nonself_scores.empty else 0
        weak_nonself = int(nonself_scores["weak_accept"].astype(bool).sum()) if not nonself_scores.empty else 0
        non_self_best_count = int((~g["is_self_best"].astype(bool)).sum())
        rows.append(
            {
                "candidate_pool": pool,
                "residual_mode": mode,
                "n_sequences": int(n),
                "n_candidate_scores": int(len(score_g)) if scores is not None else int(g["num_claim_candidates"].sum()),
                "num_claim_candidates_median": float(g["num_claim_candidates"].median()),
                "num_claim_candidates_min": int(g["num_claim_candidates"].min()),
                "num_claim_candidates_max": int(g["num_claim_candidates"].max()),
                "top1_self_rate": float(g["is_self_best"].mean()) if n else np.nan,
                "top5_self_rate": float((g["true_sat_rank"] <= 5).mean()) if n else np.nan,
                "non_self_best_count": non_self_best_count,
                "non_self_best_rate": float(non_self_best_count / n) if n else np.nan,
                "best_claim_accept_rate": float(g["strong_accept"].mean()) if n else np.nan,
                "best_claim_defer_rate": float((g["strong_tri_decision"] == "DEFER").mean()) if n else np.nan,
                "best_claim_reject_rate": float((g["strong_tri_decision"] == "REJECT").mean()) if n else np.nan,
                "strong_best_claim_accept_rate": float(g["strong_accept"].mean()) if n else np.nan,
                "weak_best_claim_accept_rate": float(g["weak_accept"].mean()) if n else np.nan,
                "accept_rate_gap": float(g["weak_accept"].mean() - g["strong_accept"].mean()) if n else np.nan,
                "weak_only_accept_count": int(((~g["strong_accept"].astype(bool)) & g["weak_accept"].astype(bool)).sum()),
                "strong_nonself_accept_count": strong_nonself,
                "weak_nonself_accept_count": weak_nonself,
                "self_score_median": float(g["self_score"].median()),
                "best_nonself_score_median": float(g["best_nonself_score"].median()),
                "score_margin_self_to_best_nonself_median": float(g["score_margin_self_to_best_nonself"].median()),
                "score_margin_self_to_best_nonself_p10": float(g["score_margin_self_to_best_nonself"].quantile(0.10)),
                "score_margin_median": float(g["score_margin"].median()),
                "score_margin_p10": float(g["score_margin"].quantile(0.10)),
                "true_sat_rank_median": float(g["true_sat_rank"].median()),
            }
        )
    return pd.DataFrame(rows)


def ambiguity_pairs(scores: pd.DataFrame, seq: pd.DataFrame, top_k: int) -> pd.DataFrame:
    if scores.empty:
        return pd.DataFrame()
    top = scores[scores["candidate_rank"] <= int(top_k)].copy()
    totals = scores[["sequence_id", "true_sat"]].drop_duplicates().groupby("true_sat").size().to_dict()
    self_score = seq.set_index("sequence_id")["self_score"].to_dict()
    top["score_margin_to_self"] = top["score"] - top["sequence_id"].map(self_score)
    rows: list[dict[str, Any]] = []
    for (true_sat, claim_sat), g in top.groupby(["true_sat", "claim_sat"], sort=True):
        count = len(g)
        rows.append(
            {
                "true_sat": true_sat,
                "claim_sat": claim_sat,
                "count_in_topk": int(count),
                "mean_rank": float(g["candidate_rank"].mean()),
                "median_rank": float(g["candidate_rank"].median()),
                "median_score": float(g["score"].median()),
                "median_score_margin_to_self": float(g["score_margin_to_self"].median()),
                "strong_accept_count": int(g["strong_accept"].astype(bool).sum()),
                "weak_accept_count": int(g["weak_accept"].astype(bool).sum()),
                "confusion_rate": float(count / totals.get(true_sat, count)),
                "is_self_pair": bool(str(true_sat) == str(claim_sat)),
                "median_range_rate_corr": float(g["range_rate_corr"].median()) if "range_rate_corr" in g else np.nan,
                "true_sat_max_elevation": float(g["max_elevation_true"].median()),
                "claim_sat_max_elevation": float(g["max_elevation_claim"].median()),
            }
        )
    return pd.DataFrame(rows).sort_values(["is_self_pair", "confusion_rate", "count_in_topk", "mean_rank"], ascending=[True, False, False, True]).reset_index(drop=True)


def ambiguity_summary(seq: pd.DataFrame, pairs: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    if seq.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for (mode, pool), g in seq.groupby(["residual_mode", "candidate_pool"], sort=True):
        pair_g = pairs
        if "residual_mode" in pairs.columns:
            pair_g = pairs[(pairs["residual_mode"] == mode) & (pairs["candidate_pool"] == pool)]
        rows.append(
            {
                "residual_mode": mode,
                "candidate_pool": pool,
                "top_k": int(args.top_k),
                "num_sequences": int(len(g)),
                "num_non_self_best": int((~g["is_self_best"].astype(bool)).sum()),
                "num_pairs_in_topk": int(len(pair_g)),
                "median_best_score": float(g["best_score"].median()),
                "median_score_margin": float(g["score_margin"].median()),
                "weak_only_accept_count": int(((~g["strong_accept"].astype(bool)) & g["weak_accept"].astype(bool)).sum()),
                "strong_nonself_accept_count": int(g["strong_nonself_accept_count"].sum()) if "strong_nonself_accept_count" in g else np.nan,
                "weak_nonself_accept_count": int(g["weak_nonself_accept_count"].sum()) if "weak_nonself_accept_count" in g else np.nan,
            }
        )
    return pd.DataFrame(rows)


def write_report(args: argparse.Namespace, seq: pd.DataFrame, summary: pd.DataFrame, pairs: pd.DataFrame, ambiguity: pd.DataFrame) -> None:
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    summary_text = summary.to_markdown(index=False) if not summary.empty else "无 summary 输出。"
    amb_text = ambiguity.to_markdown(index=False) if not ambiguity.empty else "无 ambiguity summary 输出。"
    pair_cols = ["true_sat", "claim_sat", "count_in_topk", "mean_rank", "median_score", "median_score_margin_to_self", "confusion_rate", "strong_accept_count", "weak_accept_count", "median_range_rate_corr"]
    nonself_pairs = pairs[pairs["true_sat"].astype(str) != pairs["claim_sat"].astype(str)].copy() if not pairs.empty else pd.DataFrame()
    by_count = nonself_pairs.sort_values(["count_in_topk", "confusion_rate", "mean_rank"], ascending=[False, False, True]).head(20)
    by_score = nonself_pairs.sort_values(["median_score", "mean_rank"], ascending=[True, True]).head(20)
    by_corr = nonself_pairs.assign(abs_corr=nonself_pairs["median_range_rate_corr"].abs()).sort_values(["abs_corr", "median_score"], ascending=[False, True]).head(20) if not nonself_pairs.empty else pd.DataFrame()
    pair_text_count = by_count[pair_cols].to_markdown(index=False) if not by_count.empty else "无 non-self top-k pair。"
    pair_text_score = by_score[pair_cols].to_markdown(index=False) if not by_score.empty else "无 non-self top-k pair。"
    pair_text_corr = by_corr[pair_cols].to_markdown(index=False) if not by_corr.empty else "无 non-self top-k pair。"
    non_self = int((~seq["is_self_best"].astype(bool)).sum()) if not seq.empty else 0
    weak_only = int(((~seq["strong_accept"].astype(bool)) & seq["weak_accept"].astype(bool)).sum()) if not seq.empty else 0
    strong_nonself = int(seq["strong_nonself_accept_count"].sum()) if "strong_nonself_accept_count" in seq else 0
    weak_nonself = int(seq["weak_nonself_accept_count"].sum()) if "weak_nonself_accept_count" in seq else 0
    text = f"""# Best-Claim 多普勒可混淆性规模扩展总结

生成时间：{datetime.now().isoformat(timespec="seconds")}

## 1. 实验目的

上一轮 best-claim first pass 候选池较小，未发现 non-self best claim。本轮扩大 true_sat 与 claim candidate 规模，验证该结论是否在更大候选池下仍稳定。claimed-identity verification 是合理基础模型；best-claim 用于评估攻击者可选择声明身份时的最坏情况。

## 2. 运行规模

- true_sat 数量：`{args.max_true_sats}`
- max claim candidates：`{args.max_claim_candidates}`
- candidate_pool：`{args.candidate_pool}`
- residual_mode：`{args.residual_mode}`
- top-k：`{args.top_k}`
- checkpoint / incremental write：启用；每条 sequence 完成后追加写入 `{args.sequence_output}` 和 `{args.candidate_scores_output}`。`--resume` 可跳过已有 `(true_sat, residual_mode)`。
- strong-prior：`score <= per-target p95 threshold` 且 `k_hat` 落入该 claim 的合法样本 p01/p99 范围，并满足过境质量条件。
- weak-prior：`score <= per-target p95 threshold` 且满足过境质量条件，不使用 b/k gate 直接拒绝。

当前 first pass 的 claim identities 限定在已有合法 threshold 与合法 b/k calibration 的 controlled target 集合内；`visible` pool 会用项目 SGP4/geo_curve 逻辑补算候选在同一时间网格上的最大仰角。

输出文件：

- `{args.sequence_output}`
- `{args.summary_output}`
- `{args.candidate_scores_output}`
- `{args.ambiguity_pairs_output}`
- `{args.ambiguity_summary_output}`

## 3. Best-Claim 结果

{summary_text}

非真实卫星成为 best claim 的序列数为 `{non_self}`。strong-prior non-self accept 数为 `{strong_nonself}`，weak-prior non-self accept 数为 `{weak_nonself}`。

如果没有 non-self best，说明在当前完整窗口与候选池下，真实身份仍稳定排名第一。如果有 non-self top-k 但未接受，属于 ranking-level ambiguity；如果出现 non-self accept，则属于 verification-level ambiguity，需要后续重点分析。

## 4. Weak-Prior Ablation 结果

weak-only accept 样本数为 `{weak_only}`。若 weak-prior 接受率明显高于 strong-prior，说明当前判决较依赖 fitted k sanity gate；若差异很小，则说明 residual shape 和质量条件本身已经提供主要区分力。本轮只量化贡献，不预设 b/k gate 是否合理。

## 5. Ambiguity Set 初步观察

{amb_text}

Top ambiguity pairs by count_in_topk：

{pair_text_count}

Top ambiguity pairs by median_score：

{pair_text_score}

Top ambiguity pairs by |median_range_rate_corr|：

{pair_text_corr}

这些 pair 只表示 first-pass top-k 排名中的可混淆候选，不等价于真实攻击成功率。需要区分 ranking-level ambiguity 与 verification-level ambiguity：前者只是进入 top-k，后者还需要 score 低到可能 ACCEPT / DEFER。

## 6. 下一步建议

- 如果 best-claim 误接受明显：下一步正式研究 adversarial claim selection。
- 如果 weak-prior 明显更脆弱：下一步重点研究 calibration-free / weak-prior verifier 的安全边界。
- 如果 top-k 混淆明显但未接受：下一步做 Doppler ambiguity cluster 和阈值敏感性。
- 如果全部都很稳：说明单站 Doppler residual 在当前设置下具有较强可识别性，后续应考虑 TLE 误差、短窗口、真实噪声和多物理特征。
"""
    args.report_output.write_text(text, encoding="utf-8")


def append_work_log(args: argparse.Namespace, seq: pd.DataFrame, summary: pd.DataFrame, pairs: pd.DataFrame) -> None:
    path = Path("logs/work_log.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    top1 = float(summary["top1_self_rate"].iloc[0]) if not summary.empty else np.nan
    top5 = float(summary["top5_self_rate"].iloc[0]) if not summary.empty else np.nan
    strong = float(summary["strong_best_claim_accept_rate"].iloc[0]) if not summary.empty else np.nan
    weak = float(summary["weak_best_claim_accept_rate"].iloc[0]) if not summary.empty else np.nan
    non_self_best = int(summary["non_self_best_count"].iloc[0]) if not summary.empty else 0
    strong_nonself = int(summary["strong_nonself_accept_count"].iloc[0]) if not summary.empty else 0
    weak_nonself = int(summary["weak_nonself_accept_count"].iloc[0]) if not summary.empty else 0
    n_scores = int(summary["n_candidate_scores"].iloc[0]) if not summary.empty else 0
    log = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} - best-claim 多普勒可混淆性 first pass

### A. 本轮目标

实现 best-claim / untargeted impersonation search，输出 weak-prior ablation 和 Doppler ambiguity top-k 初步分析。

### B. 实际操作

- 新增 `scripts/run_best_claim_impersonation_first_pass.py`。
- 复用 controlled Starlink selection、candidate library、TLE、SGP4 geo_curve、existing residual fitting/scoring 和 empirical residual 参数。
- strong-prior 使用 score + per-target k gate + elevation quality；weak-prior 使用 score + elevation quality，不用 b/k gate 直接拒绝。
- 启用逐 sequence incremental write；`--resume` 可跳过已完成 `(true_sat, residual_mode)`。

### C. 新增/修改文件

- `scripts/run_best_claim_impersonation_first_pass.py`
- `{args.sequence_output}`
- `{args.summary_output}`
- `{args.candidate_scores_output}`
- `{args.ambiguity_pairs_output}`
- `{args.ambiguity_summary_output}`
- `{args.report_output}`
- `logs/work_log.md`

### D. 运行命令

```bash
python scripts/run_best_claim_impersonation_first_pass.py --max-true-sats {args.max_true_sats} --max-claim-candidates {args.max_claim_candidates} --candidate-pool {args.candidate_pool} --residual-mode {args.residual_mode} --top-k {args.top_k} --overwrite
```

### E. 结果摘要

- sequence 数：`{len(seq)}`
- candidate score 数：`{n_scores}`
- top1_self_rate：`{top1:.6f}`
- top5_self_rate：`{top5:.6f}`
- strong_best_claim_accept_rate：`{strong:.6f}`
- weak_best_claim_accept_rate：`{weak:.6f}`
- non_self_best_count：`{non_self_best}`
- strong_nonself_accept_count：`{strong_nonself}`
- weak_nonself_accept_count：`{weak_nonself}`
- ambiguity pair 数：`{len(pairs)}`

### F. 问题与下一步

本轮是 controlled target 集合内的 first pass；claim pool 未扩展到全星座 calibrated verifier。下一步根据 weak-prior gap 和 top-k 非 self pair 决定是否做正式 ambiguity cluster、calibration-free verifier 边界或更大 claim pool。
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(log)


def main() -> None:
    args = parse_args()
    completed = prepare_outputs(args)
    selection, library, orbit_cfg, tle, threshold_map, prior_map, ranges = load_inputs(args)
    station = make_station(orbit_cfg)
    ts = load.timescale()
    rng = np.random.default_rng(args.seed)
    modes = selected_modes(args.residual_mode)

    seq_counter = 1
    written_since_flush = 0

    for _, true_row in selection.iterrows():
        true_id = str(true_row["target_norad_id"])
        true_name = str(true_row["target_name"])
        rows = candidate_rows_for_true_window(library, true_id)
        geos = candidate_geometries(rows)
        names = claim_name_map(rows)
        if true_id not in geos:
            active.fail(f"true sat not available as candidate on its own window: {true_id}")
        true_geo = geos[true_id]
        t_rel = true_geo["t_rel_s"].to_numpy(float)
        times = [base.parse_utc(v) for v in true_geo["t_abs_utc"].astype(str)]
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else float(true_row.get("step_s", 1.0))
        freq_hz = float(true_geo["center_freq_hz"].iloc[0]) if "center_freq_hz" in true_geo else 11_325_000_000.0
        claim_ids_all = [cid for cid in geos if cid in threshold_map and cid in prior_map and cid in tle]
        max_elev = max_elevation_for_claims(claim_ids_all, tle, times, ts, station, freq_hz, step_s)
        claim_ids = choose_claim_pool(rows, claim_ids_all, max_elev, args)
        if true_id not in claim_ids and true_id in claim_ids_all:
            claim_ids = [true_id] + claim_ids
            claim_ids = claim_ids[: max(1, int(args.max_claim_candidates))]

        true_max_elev = float(max_elev.get(true_id, np.nan))
        f_geo_true = true_geo["f_geo_candidate_hz"].to_numpy(float)

        for mode in modes:
            if (true_id, mode) in completed:
                continue
            terms = active.sample_residual_terms(t_rel, mode, ranges, rng)
            f_obs, noise, b_inj, k_inj, sigma_inj, t0_s = active.apply_residual_terms(f_geo_true, t_rel, terms)
            sequence_id = f"best_claim_{seq_counter:06d}"
            seq_counter += 1
            observation = build_observation(sequence_id, true_name, true_id, true_geo, f_obs, noise, b_inj, k_inj, sigma_inj, t0_s, mode)

            per_candidate: list[dict[str, Any]] = []
            for claim_id in claim_ids:
                claim_geo = geos.get(claim_id)
                if claim_geo is None:
                    continue
                if len(claim_geo) != len(t_rel) or not np.allclose(claim_geo["t_rel_s"].to_numpy(float), t_rel):
                    active.fail(f"claim time grid mismatch: true={true_id}, claim={claim_id}")
                f_geo_claim = claim_geo["f_geo_candidate_hz"].to_numpy(float)
                threshold_95, threshold_99 = threshold_map[claim_id]
                v = base.verify_claimed_identity(observation, f_geo_claim, threshold_95, threshold_99)
                prior = prior_map[claim_id]
                b_gate = bool(prior["b_min"] <= v.b_hat_hz <= prior["b_max"])
                k_gate = bool(prior["k_min"] <= v.k_hat_hz_s <= prior["k_max"])
                quality_ok = bool(max_elev.get(claim_id, -999.0) >= float(args.elevation_min_deg))
                strong_accept = bool(v.accepted_95 and k_gate and quality_ok)
                weak_accept = bool(v.accepted_95 and quality_ok)
                strong_tri = active.tri_state_decision(bool(v.accepted_95 and k_gate), max_elev.get(claim_id, np.nan), args.elevation_min_deg)
                weak_tri = active.tri_state_decision(bool(v.accepted_95), max_elev.get(claim_id, np.nan), args.elevation_min_deg)
                delta = f_obs - f_geo_claim
                corr = float(np.corrcoef(f_geo_true, f_geo_claim)[0, 1]) if len(f_geo_true) > 1 else np.nan
                per_candidate.append(
                    {
                        "sequence_id": sequence_id,
                        "true_sat": true_id,
                        "true_sat_name": true_name,
                        "claim_sat": claim_id,
                        "claim_sat_name": names.get(claim_id, tle.get(claim_id, {}).get("name", claim_id)),
                        "candidate_pool": args.candidate_pool,
                        "residual_mode": mode,
                        "score": float(v.score_A_rmse_hz),
                        "threshold_95_hz": float(threshold_95),
                        "threshold_99_hz": float(threshold_99),
                        "p95_accept": bool(v.accepted_95),
                        "b_hat": float(v.b_hat_hz),
                        "k_hat": float(v.k_hat_hz_s),
                        "b_gate_pass": b_gate,
                        "k_gate_pass": k_gate,
                        "strong_accept": strong_accept,
                        "weak_accept": weak_accept,
                        "strong_tri_decision": strong_tri,
                        "weak_tri_decision": weak_tri,
                        "tri_decision": strong_tri,
                        "max_elevation_claim": float(max_elev.get(claim_id, np.nan)),
                        "max_elevation_true": true_max_elev,
                        "delta_rmse": active.rmse(delta),
                        "range_rate_corr": corr,
                    }
                )

            if not per_candidate:
                active.fail(f"no claim candidates evaluated for true sat {true_id}")
            per_candidate = sorted(per_candidate, key=lambda r: (float(r["score"]), str(r["claim_sat"])))
            sequence_score_rows: list[dict[str, Any]] = []
            for rank, row in enumerate(per_candidate, start=1):
                row["candidate_rank"] = int(rank)
                sequence_score_rows.append(row)

            best = per_candidate[0]
            second_score = float(per_candidate[1]["score"]) if len(per_candidate) > 1 else np.nan
            score_margin = second_score - float(best["score"]) if np.isfinite(second_score) else np.nan
            true_candidates = [r for r in per_candidate if str(r["claim_sat"]) == true_id]
            true_rank = int(true_candidates[0]["candidate_rank"]) if true_candidates else -1
            true_score = float(true_candidates[0]["score"]) if true_candidates else np.nan
            nonself_candidates = [r for r in per_candidate if str(r["claim_sat"]) != true_id]
            best_nonself = nonself_candidates[0] if nonself_candidates else None
            best_nonself_score = float(best_nonself["score"]) if best_nonself else np.nan
            best_nonself_rank = int(best_nonself["candidate_rank"]) if best_nonself else -1
            score_margin_self_to_best_nonself = best_nonself_score - true_score if np.isfinite(best_nonself_score) and np.isfinite(true_score) else np.nan
            strong_nonself_accept_count = int(sum(bool(r["strong_accept"]) for r in nonself_candidates))
            weak_nonself_accept_count = int(sum(bool(r["weak_accept"]) for r in nonself_candidates))
            sequence_row = (
                {
                    "sequence_id": sequence_id,
                    "true_sat": true_id,
                    "true_sat_name": true_name,
                    "best_claim_sat": best["claim_sat"],
                    "best_claim_name": best["claim_sat_name"],
                    "is_self_best": bool(str(best["claim_sat"]) == true_id),
                    "best_nonself_claim_sat": best_nonself["claim_sat"] if best_nonself else "",
                    "best_nonself_claim_name": best_nonself["claim_sat_name"] if best_nonself else "",
                    "best_nonself_score": best_nonself_score,
                    "best_nonself_rank": best_nonself_rank,
                    "self_score": true_score,
                    "self_rank": true_rank,
                    "score_margin_self_to_best_nonself": score_margin_self_to_best_nonself,
                    "candidate_pool": args.candidate_pool,
                    "num_claim_candidates": int(len(per_candidate)),
                    "residual_mode": mode,
                    "best_score": float(best["score"]),
                    "second_best_score": second_score,
                    "score_margin": score_margin,
                    "best_tri_decision": best["strong_tri_decision"],
                    "best_p95_accept": bool(best["p95_accept"]),
                    "best_b_hat": float(best["b_hat"]),
                    "best_k_hat": float(best["k_hat"]),
                    "true_sat_score": true_score,
                    "true_sat_rank": true_rank,
                    "strong_nonself_accept_count": strong_nonself_accept_count,
                    "weak_nonself_accept_count": weak_nonself_accept_count,
                    "max_elevation_true": true_max_elev,
                    "max_elevation_best_claim": float(best["max_elevation_claim"]),
                    "b_gate_pass": bool(best["b_gate_pass"]),
                    "k_gate_pass": bool(best["k_gate_pass"]),
                    "strong_tri_decision": best["strong_tri_decision"],
                    "weak_tri_decision": best["weak_tri_decision"],
                    "strong_accept": bool(best["strong_accept"]),
                    "weak_accept": bool(best["weak_accept"]),
                    "weak_only_accept": bool((not bool(best["strong_accept"])) and bool(best["weak_accept"])),
                    "random_seed": int(args.seed),
                }
            )
            append_rows(args.sequence_output, [sequence_row])
            append_rows(args.candidate_scores_output, sequence_score_rows)
            written_since_flush += 1
            if written_since_flush >= max(1, int(args.flush_every)):
                print(f"checkpoint wrote through sequence {sequence_id} true_sat={true_id} mode={mode} candidates={len(sequence_score_rows)}")
                written_since_flush = 0

    if not args.sequence_output.exists() or not args.candidate_scores_output.exists():
        active.fail("no sequence results were written")
    sequence_eval = pd.read_csv(args.sequence_output)
    candidate_scores = pd.read_csv(args.candidate_scores_output)
    summary = summarize_sequences(sequence_eval, candidate_scores)
    pairs = ambiguity_pairs(candidate_scores, sequence_eval, args.top_k)
    if not pairs.empty:
        pairs.insert(0, "candidate_pool", args.candidate_pool)
        pairs.insert(1, "residual_mode", args.residual_mode)
    amb_summary = ambiguity_summary(sequence_eval, pairs, args)

    for path, df in [
        (args.summary_output, summary),
        (args.ambiguity_pairs_output, pairs),
        (args.ambiguity_summary_output, amb_summary),
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        print(f"wrote {path} rows={len(df)}")
    write_report(args, sequence_eval, summary, pairs, amb_summary)
    append_work_log(args, sequence_eval, summary, pairs)
    print(f"wrote {args.report_output}")
    if not summary.empty:
        print(summary.to_string(index=False))
    if not amb_summary.empty:
        print(amb_summary.to_string(index=False))


if __name__ == "__main__":
    main()
