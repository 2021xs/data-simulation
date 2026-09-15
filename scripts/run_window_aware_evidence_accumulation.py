#!/usr/bin/env python
"""Window-aware evidence accumulation verifier for controlled Starlink passes.

This is a diagnostic prototype.  It reuses the controlled Starlink geometry,
empirical residual model, attack construction, window fitting, and calibration
helpers from run_window_reliability_calibration.py.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
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

import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_window_reliability_calibration as wrc  # noqa: E402


DEFAULT_SEGMENT_PATTERNS = ["middle_segments", "spread_segments", "best_attack_segments"]
DEFAULT_STRATEGIES = ["single_window", "naive_accumulation", "proposed_accumulation"]
DEFAULT_THRESHOLD_TYPES = ["p95", "p99"]
DEFAULT_WINDOW_LENGTHS = [180, 120, 60, 30]
GROUP_PATTERNS: dict[str, list[int]] = {
    "2x120s": [120, 120],
    "2x60s": [60, 60],
    "3x60s": [60, 60, 60],
    "2x30s": [30, 30],
    "3x30s": [30, 30, 30],
    "4x30s": [30, 30, 30, 30],
    "6x30s": [30, 30, 30, 30, 30, 30],
    "120s+60s": [120, 60],
    "120s+2x60s": [120, 60, 60],
    "60s+2x30s": [60, 30, 30],
}
EVIDENCE_NORMAL = {120: 2.0, 60: 1.0, 30: 0.5}
EVIDENCE_BORDERLINE = {120: 1.0, 60: 0.5, 30: 0.25}
BK_MULTIPLIERS = {
    "full_pass": (1.0, 1.0),
    180: (1.0, 1.0),
    120: (1.2, 1.2),
    60: (1.5, 1.5),
    30: (2.0, 1.5),
}


@dataclass(frozen=True)
class WindowEval:
    spec: wrc.WindowSpec
    fit: base.FitResult
    threshold_p95: float
    threshold_p99: float
    local_decision: str
    evidence_score: float
    b_status: str
    k_status: str
    score_status: str
    b_normal: bool
    k_normal: bool
    b_extreme: bool
    k_extreme: bool
    n_points: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run window-aware evidence accumulation verifier.")
    parser.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    parser.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    parser.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    parser.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    parser.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    parser.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/window_aware_evidence_accumulation_dataset.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/window_aware_evidence_accumulation_summary.csv"))
    parser.add_argument("--comparison-output", type=Path, default=Path("outputs/metrics/window_aware_strategy_comparison.csv"))
    parser.add_argument("--report-output", type=Path, default=Path("outputs/reports/window_aware_evidence_accumulation_summary.md"))
    parser.add_argument("--figures-dir", type=Path, default=Path("outputs/figures"))
    parser.add_argument("--max-targets", type=int, default=20)
    parser.add_argument("--max-passes-per-target", type=int, default=1)
    parser.add_argument("--num-sims-per-attack", type=int, default=5)
    parser.add_argument("--num-benign-sims", type=int, default=None)
    parser.add_argument("--segment-patterns", nargs="+", default=DEFAULT_SEGMENT_PATTERNS)
    parser.add_argument("--strategies", nargs="+", choices=DEFAULT_STRATEGIES, default=DEFAULT_STRATEGIES)
    parser.add_argument("--threshold-types", nargs="+", choices=DEFAULT_THRESHOLD_TYPES, default=DEFAULT_THRESHOLD_TYPES)
    parser.add_argument("--window-lengths", nargs="+", default=[str(v) for v in DEFAULT_WINDOW_LENGTHS])
    parser.add_argument("--include-best-attack", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--altitude-deltas-km", nargs="+", type=float, default=wrc.DEFAULT_ALTITUDE_DELTAS_KM)
    parser.add_argument("--phase-offsets-s", nargs="+", type=float, default=wrc.DEFAULT_PHASE_OFFSETS_S)
    parser.add_argument("--inclination-deltas-deg", nargs="+", type=float, default=wrc.DEFAULT_INCLINATION_DELTAS_DEG)
    parser.add_argument("--evidence-accept-threshold", type=float, default=3.0)
    parser.add_argument("--max-overlap-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=20260612)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def check_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(p) for p in paths if p.exists()]
    if existing and not overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def split_cli_values(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        out.extend([part.strip() for part in str(value).split(",") if part.strip()])
    return out


def parse_window_lengths(values: list[str]) -> list[int]:
    return [int(float(v)) for v in split_cli_values(values) if str(v).lower() not in {"full", "full_pass"}]


def window_key(length: int | str) -> int | str:
    return "full_pass" if str(length) == "full_pass" else int(length)


def threshold_length_for_effective_duration(duration_s: float) -> int:
    if duration_s >= 180:
        return 180
    if duration_s >= 120:
        return 120
    if duration_s >= 60:
        return 60
    return 30


def base_middle_specs(t_rel: np.ndarray, lengths: list[int]) -> list[wrc.WindowSpec]:
    specs = [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)]
    for length in sorted(set(lengths), reverse=True):
        specs.append(wrc.build_middle_window(t_rel, length))
    return [spec for spec in specs if not spec.skip_reason]


def interval_overlap_ratio(a: wrc.WindowSpec, b: wrc.WindowSpec) -> float:
    overlap = max(0.0, min(a.stop_s, b.stop_s) - max(a.start_s, b.start_s))
    denom = max(1e-9, min(a.stop_s - a.start_s, b.stop_s - b.start_s))
    return float(overlap / denom)


def temporal_stats(specs: list[wrc.WindowSpec], max_allowed_overlap: float) -> tuple[bool, float, float]:
    if len(specs) <= 1:
        return False, 0.0, 0.0
    ratios: list[float] = []
    centers = sorted([(s.start_s + s.stop_s) / 2.0 for s in specs])
    min_len = min(float(s.window_length_s) for s in specs)
    min_gap_required = min(30.0, 0.5 * min_len)
    for i, left in enumerate(specs):
        for right in specs[i + 1 :]:
            ratios.append(interval_overlap_ratio(left, right))
    center_gap_ok = all((centers[i + 1] - centers[i]) >= min_gap_required for i in range(len(centers) - 1))
    min_overlap = float(min(ratios)) if ratios else 0.0
    max_overlap = float(max(ratios)) if ratios else 0.0
    return bool(max_overlap < max_allowed_overlap and center_gap_ok), min_overlap, max_overlap


def effective_duration(specs: list[wrc.WindowSpec]) -> float:
    if not specs:
        return 0.0
    intervals = sorted((float(s.start_s), float(s.stop_s)) for s in specs)
    merged: list[list[float]] = []
    for start, stop in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, stop])
        else:
            merged[-1][1] = max(merged[-1][1], stop)
    return float(sum(stop - start for start, stop in merged))


def calibration_stats(
    *,
    benign_obs: list[base.ObservationSequence],
    geo: pd.DataFrame,
    f_geo_a: np.ndarray,
    specs_by_key: dict[int | str, list[wrc.WindowSpec]],
    threshold_types: list[str],
) -> dict[int | str, dict[str, float]]:
    out: dict[int | str, dict[str, float]] = {}
    t_rel = geo["t_rel_s"].to_numpy(float)
    for key, specs in specs_by_key.items():
        scores: list[float] = []
        b_vals: list[float] = []
        k_vals: list[float] = []
        for spec in specs:
            mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
            if int(mask.sum()) < 3:
                continue
            for obs in benign_obs:
                fit = wrc.fit_on_mask(obs.y_obs_hz, f_geo_a, t_rel, mask)
                scores.append(fit.score_rmse_hz)
                b_vals.append(fit.b_hat_hz)
                k_vals.append(fit.k_hat_hz_s)
        if not scores:
            continue
        b_arr = np.array(b_vals, dtype=float)
        k_arr = np.array(k_vals, dtype=float)
        b_center = float(np.median(b_arr))
        k_center = float(np.median(k_arr))
        b_abs_p99 = float(np.quantile(np.abs(b_arr - b_center), 0.99))
        k_abs_p99 = float(np.quantile(np.abs(k_arr - k_center), 0.99))
        stats = {
            "score_p95": float(np.quantile(scores, 0.95)),
            "score_p99": float(np.quantile(scores, 0.99)),
            "b_center": b_center,
            "k_center": k_center,
            "b_abs_p99": max(b_abs_p99, 1e-9),
            "k_abs_p99": max(k_abs_p99, 1e-9),
            "calibration_n": float(len(scores)),
        }
        out[key] = stats
    return out


def classify_bk(value: float, center: float, abs_p99: float, multiplier: float) -> tuple[bool, bool, str]:
    delta = abs(float(value) - float(center))
    if delta <= abs_p99:
        return True, False, "normal"
    if delta <= multiplier * abs_p99:
        return False, False, "suspicious"
    return False, True, "extreme"


def evaluate_window(
    observation: base.ObservationSequence,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    spec: wrc.WindowSpec,
    cal: dict[int | str, dict[str, float]],
) -> WindowEval:
    key = "full_pass" if spec.window_position == "full_pass" else int(round(float(spec.window_length_s)))
    c = cal[key]
    mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
    fit = wrc.fit_on_mask(observation.y_obs_hz, f_geo_a, t_rel, mask)
    score_p95 = float(c["score_p95"])
    score_p99 = float(c["score_p99"])
    if fit.score_rmse_hz <= score_p95:
        score_status = "normal"
    elif fit.score_rmse_hz <= score_p99:
        score_status = "borderline"
    else:
        score_status = "fail"
    b_mult, k_mult = BK_MULTIPLIERS[key]
    b_normal, b_extreme, b_status = classify_bk(fit.b_hat_hz, c["b_center"], c["b_abs_p99"], b_mult)
    k_normal, k_extreme, k_status = classify_bk(fit.k_hat_hz_s, c["k_center"], c["k_abs_p99"], k_mult)
    if b_extreme or k_extreme:
        local = "EXTREME_ANOMALY"
    elif score_status == "normal" and b_normal and k_normal:
        local = "NORMAL_PASS"
    elif score_status in {"normal", "borderline"}:
        local = "BORDERLINE_PASS"
    else:
        local = "FAIL"
    length = int(round(float(spec.window_length_s)))
    evidence = 0.0
    if local == "NORMAL_PASS":
        evidence = EVIDENCE_NORMAL.get(length, 0.0)
    elif local == "BORDERLINE_PASS":
        evidence = EVIDENCE_BORDERLINE.get(length, 0.0)
    return WindowEval(
        spec=spec,
        fit=fit,
        threshold_p95=score_p95,
        threshold_p99=score_p99,
        local_decision=local,
        evidence_score=float(evidence),
        b_status=b_status,
        k_status=k_status,
        score_status=score_status,
        b_normal=b_normal,
        k_normal=k_normal,
        b_extreme=b_extreme,
        k_extreme=k_extreme,
        n_points=int(mask.sum()),
    )


def joint_fit(
    observation: base.ObservationSequence,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    specs: list[wrc.WindowSpec],
    cal: dict[int | str, dict[str, float]],
) -> dict[str, Any]:
    mask = np.zeros(len(t_rel), dtype=bool)
    for spec in specs:
        mask |= wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
    if int(mask.sum()) < 3:
        return {
            "joint_score_rmse_hz": np.nan,
            "joint_normalized_score": np.nan,
            "b_pass_hat_hz": np.nan,
            "k_pass_hat_hz_per_s": np.nan,
            "joint_score_gate_pass": False,
            "joint_b_gate_pass": False,
            "joint_k_gate_pass": False,
            "joint_length_key": "",
            "joint_score_over_p99": False,
            "joint_k_extreme": False,
        }
    fit = wrc.fit_on_mask(observation.y_obs_hz, f_geo_a, t_rel, mask)
    length_key = threshold_length_for_effective_duration(effective_duration(specs))
    c = cal[length_key]
    score_gate = bool(fit.score_rmse_hz <= c["score_p95"])
    score_over_p99 = bool(fit.score_rmse_hz > c["score_p99"])
    b_mult, k_mult = BK_MULTIPLIERS[length_key]
    _bn, b_extreme, _bs = classify_bk(fit.b_hat_hz, c["b_center"], c["b_abs_p99"], b_mult)
    _kn, k_extreme, _ks = classify_bk(fit.k_hat_hz_s, c["k_center"], c["k_abs_p99"], k_mult)
    b_gate = bool(abs(fit.b_hat_hz - c["b_center"]) <= b_mult * c["b_abs_p99"])
    k_gate = bool(abs(fit.k_hat_hz_s - c["k_center"]) <= k_mult * c["k_abs_p99"])
    return {
        "joint_score_rmse_hz": float(fit.score_rmse_hz),
        "joint_normalized_score": float(fit.score_rmse_hz / c["score_p95"]),
        "b_pass_hat_hz": float(fit.b_hat_hz),
        "k_pass_hat_hz_per_s": float(fit.k_hat_hz_s),
        "joint_score_gate_pass": score_gate,
        "joint_b_gate_pass": b_gate,
        "joint_k_gate_pass": k_gate,
        "joint_length_key": str(length_key),
        "joint_score_over_p99": score_over_p99,
        "joint_k_extreme": bool(k_extreme),
        "joint_b_extreme": bool(b_extreme),
    }


def choose_nonoverlap_best_specs(
    y_source: np.ndarray,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    lengths: list[int],
    cal: dict[int | str, dict[str, float]],
    max_overlap: float,
) -> list[wrc.WindowSpec]:
    selected: list[wrc.WindowSpec] = []
    for idx, length in enumerate(sorted(lengths, reverse=True), 1):
        candidates: list[wrc.WindowSpec] = []
        threshold = cal[length]["score_p95"]
        for start in wrc.sliding_window_starts(t_rel, float(length)):
            spec = wrc.WindowSpec(f"{length}s_best_attack_segments", float(length), "best_attack_segments", float(start), float(start + length))
            if any(interval_overlap_ratio(spec, old) >= max_overlap for old in selected):
                continue
            mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
            if int(mask.sum()) < 3:
                continue
            fit = wrc.fit_on_mask(y_source, f_geo_a, t_rel, mask)
            candidates.append(wrc.WindowSpec(spec.window_type, spec.window_length_s, spec.window_position, spec.start_s, spec.stop_s, fit.score_rmse_hz / threshold))
        if not candidates:
            continue
        best = min(candidates, key=lambda s: float(s.selection_score if s.selection_score is not None else np.inf))
        selected.append(wrc.WindowSpec(f"{length}s_best_attack_{idx}", float(length), "best_attack_segments", best.start_s, best.stop_s, best.selection_score))
    return selected


def choose_group_specs(
    pattern: str,
    group_mode: str,
    t_rel: np.ndarray,
    y_source: np.ndarray,
    f_geo_a: np.ndarray,
    cal: dict[int | str, dict[str, float]],
    max_overlap: float,
) -> list[wrc.WindowSpec]:
    lengths = GROUP_PATTERNS[pattern]
    start_min, start_max = float(np.min(t_rel)), float(np.max(t_rel))
    if any(start_max - start_min < length for length in lengths):
        return []
    if group_mode == "best_attack_segments":
        return choose_nonoverlap_best_specs(y_source, f_geo_a, t_rel, lengths, cal, max_overlap)
    full_center = 0.5 * (start_min + start_max)
    if group_mode == "middle_segments":
        total = float(sum(lengths))
        cursor = full_center - total / 2.0
        specs = []
        for i, length in enumerate(lengths, 1):
            start = cursor
            stop = start + float(length)
            specs.append(wrc.WindowSpec(f"{length}s_middle_seg_{i}", float(length), "middle_segments", start, stop))
            cursor = stop
        return specs
    # spread_segments
    n = len(lengths)
    anchors = np.linspace(start_min, start_max, n + 2)[1:-1]
    specs = []
    for i, (center, length) in enumerate(zip(anchors, lengths), 1):
        half = float(length) / 2.0
        start = min(max(start_min, float(center) - half), start_max - float(length))
        specs.append(wrc.WindowSpec(f"{length}s_spread_seg_{i}", float(length), "spread_segments", start, start + float(length)))
    return specs


def decisions_from_windows(
    evals: list[WindowEval],
    joint: dict[str, Any],
    temporal_ok: bool,
    args: argparse.Namespace,
) -> dict[str, tuple[str, str]]:
    if not evals:
        return {strategy: ("DEFER", "no_valid_windows") for strategy in DEFAULT_STRATEGIES}
    full_or_180 = [ev for ev in evals if ev.spec.window_position == "full_pass" or int(round(ev.spec.window_length_s)) == 180]
    if any(ev.local_decision == "NORMAL_PASS" for ev in full_or_180):
        direct = ("ACCEPT", "direct_full_or_180_normal_pass")
    elif any(ev.local_decision in {"FAIL", "EXTREME_ANOMALY"} for ev in full_or_180):
        direct = ("REJECT", "full_or_180_fail_or_extreme")
    else:
        direct = ("DEFER", "no_direct_strong_window_accept")
    if any(ev.local_decision == "NORMAL_PASS" for ev in evals):
        single = ("ACCEPT", "baseline_single_window_any_normal_pass")
    elif any(ev.local_decision == "BORDERLINE_PASS" for ev in evals):
        single = ("DEFER", "baseline_single_window_borderline_defer")
    elif any(ev.local_decision == "EXTREME_ANOMALY" for ev in evals):
        single = ("REJECT", "baseline_single_window_extreme_anomaly")
    else:
        single = ("REJECT", "baseline_single_window_all_fail")

    evidence = float(sum(ev.evidence_score for ev in evals))
    extreme_count = sum(ev.local_decision == "EXTREME_ANOMALY" for ev in evals)
    k_extreme_count = sum(ev.k_extreme for ev in evals)
    fail_count = sum(ev.local_decision == "FAIL" for ev in evals)
    short_evals = [ev for ev in evals if int(round(ev.spec.window_length_s)) < 180]
    short_fail_all = bool(short_evals and fail_count >= len(short_evals) and temporal_ok)
    naive = direct
    if direct[0] == "DEFER":
        if evidence >= args.evidence_accept_threshold and temporal_ok and extreme_count == 0:
            naive = ("ACCEPT", "naive_evidence_score_and_temporal_diversity_pass")
        elif k_extreme_count >= 1 or extreme_count >= 2 or short_fail_all:
            naive = ("REJECT", "naive_extreme_or_all_short_windows_fail")
        else:
            naive = ("DEFER", "naive_insufficient_evidence_or_temporal_diversity")

    proposed = direct
    if direct[0] == "DEFER":
        if k_extreme_count >= 1:
            proposed = ("REJECT", "k_extreme_anomaly")
        elif extreme_count >= 2:
            proposed = ("REJECT", "multiple_extreme_anomalies")
        elif bool(joint.get("joint_score_over_p99", False)):
            proposed = ("REJECT", "joint_score_above_p99")
        elif bool(joint.get("joint_k_extreme", False)):
            proposed = ("REJECT", "joint_k_extreme")
        elif short_fail_all:
            proposed = ("REJECT", "all_time_distributed_short_windows_fail")
        elif (
            evidence >= args.evidence_accept_threshold
            and temporal_ok
            and bool(joint["joint_score_gate_pass"])
            and bool(joint["joint_b_gate_pass"])
            and bool(joint["joint_k_gate_pass"])
            and extreme_count == 0
        ):
            proposed = ("ACCEPT", "evidence_temporal_diversity_and_joint_bk_pass")
        else:
            proposed = ("DEFER", "insufficient_or_unstable_accumulated_evidence")
    return {
        "single_window": single,
        "naive_accumulation": naive,
        "proposed_accumulation": proposed,
    }


def serial(values: list[Any], fmt: str | None = None) -> str:
    out: list[str] = []
    for value in values:
        if fmt == "float":
            out.append(f"{float(value):.6g}")
        else:
            out.append(str(value))
    return ";".join(out)


def build_group_rows(
    *,
    group_id: str,
    target_id: str,
    target_name: str,
    attack_type: str,
    attack_param_name: str,
    attack_param_value: Any,
    is_benign: bool,
    pass_id: str,
    group_mode: str,
    segment_pattern: str,
    observation: base.ObservationSequence,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    specs: list[wrc.WindowSpec],
    cal: dict[int | str, dict[str, float]],
    threshold_type: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    evals = [evaluate_window(observation, f_geo_a, t_rel, spec, cal) for spec in specs]
    if threshold_type == "p99":
        adjusted: list[WindowEval] = []
        for ev in evals:
            if ev.fit.score_rmse_hz <= ev.threshold_p99 and not (ev.b_extreme or ev.k_extreme):
                local = "NORMAL_PASS" if (ev.b_normal and ev.k_normal) else "BORDERLINE_PASS"
            elif ev.b_extreme or ev.k_extreme:
                local = "EXTREME_ANOMALY"
            else:
                local = "FAIL"
            length = int(round(float(ev.spec.window_length_s)))
            evidence = EVIDENCE_NORMAL.get(length, 0.0) if local == "NORMAL_PASS" else EVIDENCE_BORDERLINE.get(length, 0.0) if local == "BORDERLINE_PASS" else 0.0
            adjusted.append(
                WindowEval(
                    spec=ev.spec,
                    fit=ev.fit,
                    threshold_p95=ev.threshold_p95,
                    threshold_p99=ev.threshold_p99,
                    local_decision=local,
                    evidence_score=float(evidence),
                    b_status=ev.b_status,
                    k_status=ev.k_status,
                    score_status="normal_p99" if local in {"NORMAL_PASS", "BORDERLINE_PASS"} else ev.score_status,
                    b_normal=ev.b_normal,
                    k_normal=ev.k_normal,
                    b_extreme=ev.b_extreme,
                    k_extreme=ev.k_extreme,
                    n_points=ev.n_points,
                )
            )
        evals = adjusted
    temporal_ok, min_overlap, max_overlap = temporal_stats(specs, args.max_overlap_ratio)
    joint = joint_fit(observation, f_geo_a, t_rel, specs, cal)
    decisions = decisions_from_windows(evals, joint, temporal_ok, args)
    effective = effective_duration(specs)
    evidence = float(sum(ev.evidence_score for ev in evals))
    extreme_count = int(sum(ev.local_decision == "EXTREME_ANOMALY" for ev in evals))
    has_extreme = bool(extreme_count > 0)
    common = {
        "group_id": group_id,
        "target_id": target_id,
        "target_name": target_name,
        "attack_type": attack_type,
        "attack_param_name": attack_param_name,
        "attack_param_value": attack_param_value,
        "is_benign": bool(is_benign),
        "is_attack": bool(not is_benign),
        "pass_id": pass_id,
        "group_mode": group_mode,
        "segment_pattern": segment_pattern,
        "num_windows": int(len(specs)),
        "window_lengths_s": serial([int(round(s.window_length_s)) for s in specs]),
        "window_positions": serial([f"{s.start_s:.1f}-{s.stop_s:.1f}" for s in specs]),
        "temporal_diversity_pass": bool(temporal_ok),
        "min_overlap_ratio": min_overlap,
        "max_overlap_ratio": max_overlap,
        "effective_total_duration_s": effective,
        "single_window_decisions": serial([ev.local_decision for ev in evals]),
        "single_window_scores": serial([ev.fit.score_rmse_hz for ev in evals], "float"),
        "single_window_b_hats": serial([ev.fit.b_hat_hz for ev in evals], "float"),
        "single_window_k_hats": serial([ev.fit.k_hat_hz_s for ev in evals], "float"),
        "single_window_evidence_scores": serial([ev.evidence_score for ev in evals], "float"),
        "evidence_score": evidence,
        **joint,
        "has_extreme_anomaly": has_extreme,
        "extreme_anomaly_count": extreme_count,
        "baseline_single_decision": decisions["single_window"][0],
        "baseline_naive_accum_decision": decisions["naive_accumulation"][0],
        "proposed_decision": decisions["proposed_accumulation"][0],
        "threshold_type": threshold_type,
        "observation_sequence_id": observation.sequence_id,
    }
    rows = []
    for strategy in args.strategies:
        decision, reason = decisions[strategy]
        rows.append(
            {
                **common,
                "strategy_type": strategy,
                "final_decision": decision,
                "decision_reason": reason,
            }
        )
    return rows


def aggregate_summary(dataset: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["group_mode", "segment_pattern", "attack_type", "attack_param_value", "strategy_type", "threshold_type"]
    rows: list[dict[str, Any]] = []
    for key, g in dataset.groupby(group_cols, dropna=False):
        benign = g[g["is_benign"]]
        attack = g[g["is_attack"]]
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "n": int(len(g)),
                "benign_accept_rate": float(benign["final_decision"].eq("ACCEPT").mean()) if len(benign) else np.nan,
                "benign_defer_rate": float(benign["final_decision"].eq("DEFER").mean()) if len(benign) else np.nan,
                "benign_reject_rate": float(benign["final_decision"].eq("REJECT").mean()) if len(benign) else np.nan,
                "attack_accept_rate": float(attack["final_decision"].eq("ACCEPT").mean()) if len(attack) else np.nan,
                "attack_defer_rate": float(attack["final_decision"].eq("DEFER").mean()) if len(attack) else np.nan,
                "attack_reject_rate": float(attack["final_decision"].eq("REJECT").mean()) if len(attack) else np.nan,
                "evidence_score_median": float(g["evidence_score"].median()),
                "evidence_score_p95": float(g["evidence_score"].quantile(0.95)),
                "joint_score_median": float(g["joint_score_rmse_hz"].median()),
                "joint_score_p95": float(g["joint_score_rmse_hz"].quantile(0.95)),
                "joint_normalized_score_median": float(g["joint_normalized_score"].median()),
                "joint_normalized_score_p95": float(g["joint_normalized_score"].quantile(0.95)),
                "joint_b_gate_pass_rate": float(g["joint_b_gate_pass"].mean()),
                "joint_k_gate_pass_rate": float(g["joint_k_gate_pass"].mean()),
                "temporal_diversity_pass_rate": float(g["temporal_diversity_pass"].mean()),
                "extreme_anomaly_rate": float(g["has_extreme_anomaly"].mean()),
            }
        )
    return pd.DataFrame(rows)


def strategy_comparison(summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    dims = ["group_mode", "segment_pattern", "attack_type", "attack_param_value", "threshold_type"]
    for key, g in summary.groupby(dims, dropna=False):
        single = g[g["strategy_type"] == "single_window"]
        single_attack = float(single["attack_accept_rate"].iloc[0]) if not single.empty else np.nan
        single_benign = float(single["benign_accept_rate"].iloc[0]) if not single.empty else np.nan
        for _, row in g.iterrows():
            rows.append(
                {
                    "strategy_type": row["strategy_type"],
                    **dict(zip(dims, key)),
                    "benign_accept_rate": row["benign_accept_rate"],
                    "attack_accept_rate": row["attack_accept_rate"],
                    "attack_defer_rate": row["attack_defer_rate"],
                    "attack_reject_rate": row["attack_reject_rate"],
                    "delta_attack_accept_vs_single": row["attack_accept_rate"] - single_attack if np.isfinite(single_attack) else np.nan,
                    "delta_benign_accept_vs_single": row["benign_accept_rate"] - single_benign if np.isfinite(single_benign) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_strategy_attack(summary: pd.DataFrame, out: Path) -> None:
    data = summary[(summary["threshold_type"] == "p95") & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))].copy()
    agg = data.groupby(["strategy_type", "attack_type"], as_index=False)["attack_accept_rate"].mean()
    piv = agg.pivot(index="attack_type", columns="strategy_type", values="attack_accept_rate").fillna(0.0)
    fig, ax = plt.subplots(figsize=(9, 5))
    piv.plot(kind="bar", ax=ax)
    ax.set_ylabel("attack accept rate")
    ax.set_title("Strategy Attack Accept Rate Comparison")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def plot_benign_states(dataset: pd.DataFrame, out: Path) -> None:
    benign = dataset[(dataset["threshold_type"] == "p95") & (dataset["is_benign"])].copy()
    rates = benign.groupby("strategy_type")["final_decision"].value_counts(normalize=True).unstack(fill_value=0.0)
    for col in ["ACCEPT", "DEFER", "REJECT"]:
        if col not in rates.columns:
            rates[col] = 0.0
    fig, ax = plt.subplots(figsize=(8.5, 5))
    rates[["ACCEPT", "DEFER", "REJECT"]].plot(kind="bar", stacked=True, ax=ax, color=["#4c78a8", "#f2be5c", "#c1665a"])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("benign fraction")
    ax.set_title("Benign ACCEPT / DEFER / REJECT by Strategy")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def plot_segment_pattern(summary: pd.DataFrame, out: Path) -> None:
    data = summary[(summary["threshold_type"] == "p95") & (summary["strategy_type"] == "proposed_accumulation") & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))].copy()
    agg = data.groupby(["group_mode", "attack_type"], as_index=False)["attack_accept_rate"].mean()
    piv = agg.pivot(index="group_mode", columns="attack_type", values="attack_accept_rate").fillna(0.0)
    fig, ax = plt.subplots(figsize=(9, 5))
    piv.plot(kind="bar", ax=ax)
    ax.set_ylabel("attack accept rate")
    ax.set_title("Accumulation by Segment Pattern")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def plot_attack_type(summary: pd.DataFrame, out: Path) -> None:
    data = summary[(summary["threshold_type"] == "p95") & (summary["strategy_type"] == "proposed_accumulation") & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))].copy()
    agg = data.groupby("attack_type", as_index=False).agg(attack_accept_rate=("attack_accept_rate", "mean"), attack_defer_rate=("attack_defer_rate", "mean"), attack_reject_rate=("attack_reject_rate", "mean"))
    fig, ax = plt.subplots(figsize=(8.5, 5))
    agg.set_index("attack_type")[["attack_accept_rate", "attack_defer_rate", "attack_reject_rate"]].plot(kind="bar", stacked=True, ax=ax, color=["#4c78a8", "#f2be5c", "#c1665a"])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("attack fraction")
    ax.set_title("Attack Type Under Proposed Accumulation")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def plot_evidence_distribution(dataset: pd.DataFrame, out: Path) -> None:
    data = dataset[(dataset["threshold_type"] == "p95") & (dataset["strategy_type"] == "proposed_accumulation")].copy()
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for label, group, color in [("benign", data[data["is_benign"]], "#4c78a8"), ("attack", data[data["is_attack"]], "#c1665a")]:
        vals = group["evidence_score"].dropna().to_numpy(float)
        if len(vals):
            ax.hist(vals, bins=np.linspace(0, max(6.0, float(np.nanmax(vals))), 30), alpha=0.45, density=True, label=label, color=color)
    ax.axvline(3.0, color="black", linestyle="--", label="accept evidence threshold")
    ax.set_xlabel("evidence_score")
    ax.set_ylabel("density")
    ax.set_title("Evidence Score Distribution")
    ax.legend()
    ax.grid(True, alpha=0.25)
    savefig(fig, out)


def plot_joint_effect(summary: pd.DataFrame, out: Path) -> None:
    data = summary[(summary["threshold_type"] == "p95") & (summary["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))].copy()
    agg = data[data["strategy_type"].isin(["naive_accumulation", "proposed_accumulation"])].groupby(["segment_pattern", "strategy_type"], as_index=False)["attack_accept_rate"].mean()
    piv = agg.pivot(index="segment_pattern", columns="strategy_type", values="attack_accept_rate").fillna(0.0)
    fig, ax = plt.subplots(figsize=(10, 5))
    piv.plot(kind="bar", ax=ax)
    ax.set_ylabel("attack accept rate")
    ax.set_title("Joint b/k Gate Effect: Naive vs Proposed")
    ax.grid(True, axis="y", alpha=0.25)
    savefig(fig, out)


def make_plots(dataset: pd.DataFrame, summary: pd.DataFrame, args: argparse.Namespace) -> list[Path]:
    paths = [
        args.figures_dir / "strategy_attack_accept_rate_comparison.png",
        args.figures_dir / "strategy_benign_accept_defer_comparison.png",
        args.figures_dir / "accumulation_by_segment_pattern.png",
        args.figures_dir / "attack_type_under_accumulation.png",
        args.figures_dir / "evidence_score_distribution.png",
        args.figures_dir / "joint_bk_gate_effect.png",
    ]
    plot_strategy_attack(summary, paths[0])
    plot_benign_states(dataset, paths[1])
    plot_segment_pattern(summary, paths[2])
    plot_attack_type(summary, paths[3])
    plot_evidence_distribution(dataset, paths[4])
    plot_joint_effect(summary, paths[5])
    return paths


def md_table(df: pd.DataFrame, columns: list[str], n: int = 20) -> str:
    if df.empty:
        return "无"
    part = df.loc[:, [c for c in columns if c in df.columns]].head(n).copy()
    for col in part.columns:
        if pd.api.types.is_float_dtype(part[col]):
            part[col] = part[col].map(lambda x: "" if pd.isna(x) else f"{x:.4f}")
    headers = list(part.columns)
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in part.to_numpy():
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def write_report(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, comparison: pd.DataFrame, figure_paths: list[Path], skip_count: int) -> None:
    p95 = summary[summary["threshold_type"] == "p95"].copy()
    proposed = p95[p95["strategy_type"] == "proposed_accumulation"]
    strategies = p95.groupby("strategy_type", as_index=False).agg(
        benign_accept_rate=("benign_accept_rate", "mean"),
        benign_defer_rate=("benign_defer_rate", "mean"),
        benign_reject_rate=("benign_reject_rate", "mean"),
        attack_accept_rate=("attack_accept_rate", "mean"),
        attack_defer_rate=("attack_defer_rate", "mean"),
        attack_reject_rate=("attack_reject_rate", "mean"),
    )
    attack_type = proposed[proposed["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"])].groupby("attack_type", as_index=False).agg(
        attack_accept_rate=("attack_accept_rate", "mean"),
        attack_defer_rate=("attack_defer_rate", "mean"),
        attack_reject_rate=("attack_reject_rate", "mean"),
    ).sort_values("attack_accept_rate", ascending=False)
    segment = proposed[proposed["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"])].groupby("group_mode", as_index=False).agg(
        attack_accept_rate=("attack_accept_rate", "mean"),
        attack_defer_rate=("attack_defer_rate", "mean"),
        attack_reject_rate=("attack_reject_rate", "mean"),
    )
    benign_states = dataset[(dataset["threshold_type"] == "p95") & (dataset["strategy_type"] == "proposed_accumulation") & (dataset["is_benign"])]["final_decision"].value_counts(normalize=True)
    proposed_attack = float(strategies.loc[strategies["strategy_type"].eq("proposed_accumulation"), "attack_accept_rate"].mean())
    single_attack = float(strategies.loc[strategies["strategy_type"].eq("single_window"), "attack_accept_rate"].mean())
    naive_attack = float(strategies.loc[strategies["strategy_type"].eq("naive_accumulation"), "attack_accept_rate"].mean())
    proposed_benign_accept = float(benign_states.get("ACCEPT", 0.0))
    proposed_benign_defer = float(benign_states.get("DEFER", 0.0))
    most_dangerous = str(attack_type.iloc[0]["attack_type"]) if not attack_type.empty else "样本不足"
    figures = "\n".join(f"- `{p.as_posix()}`" for p in figure_paths)
    text = f"""# Window-aware evidence accumulation verifier summary

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 实验目的

本轮实现并验证“窗口感知的三态累计验证器”：`ACCEPT / REJECT / DEFER`。目标是检验短窗口不单独 ACCEPT、而是作为时间分散的累计证据时，能否降低规则化轨道相似攻击的误接受，同时尽量把不确定样本转为 DEFER 而不是误 REJECT。

本轮仍然不评价主动频率补偿攻击，也不把结果写成真实世界安全边界。

## 2. 上一轮 calibration 发现

上一轮 window reliability calibration 显示：full-pass 平均 attack accept rate 约 `0.0083`，30s/60s 短窗口约 `0.0498`；best_attack window 明显比 middle window 更危险；30s/60s 对 b/k gate 的依赖更强。因此短窗口不应单独触发最终 ACCEPT。

## 3. 新验证器规则

- `full_pass` 和 `180s` 正常通过可直接 ACCEPT。
- `120s` 正常通过计 `2` 分，边界通过计 `1` 分。
- `60s` 正常通过计 `1` 分，边界通过计 `0.5` 分。
- `30s` 正常通过计 `0.5` 分，边界通过计 `0.25` 分。
- 累计分数达到 `{args.evidence_accept_threshold:g}` 后，还必须通过时间分散、joint score、joint b/k gate，且没有 extreme anomaly。
- 证据不足但无明显异常时输出 DEFER；明显异常时输出 REJECT。

## 4. b/k 设置方式

每个 target / window length 的 b/k 范围只由 benign_A 校准。使用 `median` 作为中心，用 `abs(value - center)` 的 p99 作为正常范围。短窗口按长度放宽：120s 为 1.2 倍，60s 为 1.5 倍，30s 的 b 为 2.0 倍、k 为 1.5 倍。k 是主要可疑指标。

## 5. 时间分散和 joint fitting

多窗口要求任意窗口 overlap ratio 小于 `{args.max_overlap_ratio:g}`，且中心间隔满足最小 gap。joint fitting 把同一次 pass 内多个窗口的采样点合并，统一拟合一组 `b_pass + k_pass(t-t0)`，用于检查多个片段能否由同一个整体频率平移和线性慢漂移解释。不同 pass 不共享 b/k，因为 effective residual 可能随过境、接收环境和时间变化。

## 6. 实验矩阵

- target 数：`{dataset["target_id"].nunique()}`
- benign sequence 数：`{dataset[dataset["is_benign"]]["observation_sequence_id"].nunique()}`
- attack sequence 数：`{dataset[dataset["is_attack"]]["observation_sequence_id"].nunique()}`
- group 行数：`{len(dataset)}`
- segment patterns：`{", ".join(split_cli_values(args.segment_patterns))}`
- strategies：`{", ".join(args.strategies)}`
- skip group 数：`{skip_count}`

## 7. 策略对比

{md_table(strategies, ["strategy_type", "benign_accept_rate", "benign_defer_rate", "benign_reject_rate", "attack_accept_rate", "attack_defer_rate", "attack_reject_rate"], 10)}

## 8. benign 三态结果

在 `p95 + proposed_accumulation` 下，benign ACCEPT 约 `{proposed_benign_accept:.4f}`，DEFER 约 `{proposed_benign_defer:.4f}`。DEFER 是本轮设计中可接受的不确定输出，后续可由更多窗口或多 pass 累计继续处理。

## 9. attack 三态结果

`p95` 平均 attack accept rate：single-window `{single_attack:.4f}`，naive accumulation `{naive_attack:.4f}`，proposed accumulation `{proposed_attack:.4f}`。如果 proposed 低于 naive，说明 joint b/k fitting 与异常门限对累计攻击样本有过滤作用。

## 10. 三类攻击对比

{md_table(attack_type, ["attack_type", "attack_accept_rate", "attack_defer_rate", "attack_reject_rate"], 10)}

当前 proposed accumulation 下最危险的攻击类型是：`{most_dangerous}`。

## 11. middle / spread / best_attack segments 对比

{md_table(segment, ["group_mode", "attack_accept_rate", "attack_defer_rate", "attack_reject_rate"], 10)}

best_attack_segments 是 diagnostic worst-case，不代表攻击源进行主动频率补偿或利用随机噪声挑窗口。

## 12. 阶段性回答

1. 新的 window-aware accumulation verifier 是否降低短窗口 attack accept rate：见第 7 节，proposed 相对 single-window / naive 的 attack accept rate 变化用于回答该问题。
2. 是否主要把短窗口样本从 ACCEPT 转为 DEFER，而不是误 REJECT：见 benign 和 attack 的 DEFER / REJECT 比例。
3. 多个分散短窗口是否比单个 best_attack window 更可靠：见第 11 节，spread_segments 与 best_attack_segments 的 attack accept rate 对比。
4. joint b/k fitting 是否降低攻击接受率：见 naive accumulation 与 proposed accumulation 的差异。
5. benign_A 可用性：见第 8 节，当前 ACCEPT 与 DEFER 比例是可用性指标。
6. altitude / inclination / phase 哪类仍最危险：当前为 `{most_dangerous}`。
7. 下一轮是否进入 partial-observation 下的 location-aware active compensation：建议先基于本轮 proposed 的 DEFER 样本和 best_attack_segments hard cases 做规则收紧；随后可以进入 partial-observation 下的 location-aware active compensation，但仍应明确它是下一轮压力测试，不属于本轮结果。

## 13. 生成文件

- `{args.dataset_output.as_posix()}`
- `{args.summary_output.as_posix()}`
- `{args.comparison_output.as_posix()}`
- `{args.report_output.as_posix()}`
{figures}
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_work_log(args: argparse.Namespace, dataset: pd.DataFrame, summary: pd.DataFrame, commands: list[str]) -> None:
    p95 = summary[summary["threshold_type"] == "p95"]
    proposed_attack = p95[(p95["strategy_type"] == "proposed_accumulation") & (p95["attack_type"].isin(["same_plane_altitude_offset", "same_plane_phase_offset", "inclination_offset"]))]["attack_accept_rate"].mean()
    proposed_benign = p95[(p95["strategy_type"] == "proposed_accumulation") & (p95["attack_type"] == "benign_A")]["benign_accept_rate"].mean()
    cmd_text = "\n\n".join(f"```bash\n{cmd}\n```" for cmd in commands)
    text = f"""

## {datetime.now().strftime("%Y-%m-%d %H:%M")} - window-aware evidence accumulation verifier

### A. 本轮目标

实现窗口感知的三态累计验证器，比较 single-window、naive accumulation 和 proposed accumulation 在 benign_A 与三类规则化轨道相似攻击下的 ACCEPT / DEFER / REJECT。

### B. 实际操作

- 新增 `scripts/run_window_aware_evidence_accumulation.py`。
- 复用上一轮窗口切片、攻击轨道生成、residual fitting、threshold calibration 和图表输出模式。
- 实现时间分散检查、同一 pass 内 joint b/k fitting、三态累计判决。
- 未加入主动频率补偿攻击。

### C. 新增/修改文件

- 新增：`scripts/run_window_aware_evidence_accumulation.py`
- 生成：`{args.dataset_output.as_posix()}`
- 生成：`{args.summary_output.as_posix()}`
- 生成：`{args.comparison_output.as_posix()}`
- 生成：`{args.report_output.as_posix()}`
- 生成：`{args.figures_dir.as_posix()}/strategy_attack_accept_rate_comparison.png` 等 6 张图
- 追加：`logs/work_log.md`

### D. 运行命令

{cmd_text}

### E. 结果摘要

- dataset rows：`{len(dataset)}`。
- summary rows：`{len(summary)}`。
- p95 proposed benign accept rate：`{proposed_benign:.4f}`。
- p95 proposed attack accept rate：`{proposed_attack:.4f}`。

### F. 问题与下一步

本轮仍是 controlled diagnostic，不是最终安全边界。下一步建议检查 proposed DEFER 与 best_attack_segments hard cases，再进入 partial-observation 下 location-aware active compensation 压力测试。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    args.segment_patterns = split_cli_values(args.segment_patterns)
    args.strategies = split_cli_values(args.strategies)
    args.threshold_types = split_cli_values(args.threshold_types)
    outputs = [
        args.dataset_output,
        args.summary_output,
        args.comparison_output,
        args.report_output,
        args.figures_dir / "strategy_attack_accept_rate_comparison.png",
        args.figures_dir / "strategy_benign_accept_defer_comparison.png",
        args.figures_dir / "accumulation_by_segment_pattern.png",
        args.figures_dir / "attack_type_under_accumulation.png",
        args.figures_dir / "evidence_score_distribution.png",
        args.figures_dir / "joint_bk_gate_effect.png",
    ]
    check_outputs(outputs, args.overwrite)
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=args.max_targets,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    if orbit_cfg.get("mode") != "controlled_starlink" or orbit_cfg.get("observation_id") is not None:
        fail("current experiment requires controlled_starlink mode and observation_id=null")
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    station = wrc.station_from_cfg(orbit_cfg)
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    rng = np.random.default_rng(args.seed)
    lengths = parse_window_lengths(args.window_lengths)
    n_benign = int(args.num_benign_sims or max(50, args.num_sims_per_attack * 10))
    specs_all = wrc.attack_specs(args)
    rows: list[dict[str, Any]] = []
    skip_count = 0
    attack_counter = 1

    for _, target in selection.head(args.max_targets).iterrows():
        target_id = str(target["target_norad_id"])
        target_name = str(target["target_name"])
        if target_id not in tle:
            fail(f"target NORAD not found in TLE: {target_id}")
        sat = tle[target_id]["sat"]
        geo = wrc.ensure_target_elevation(base.target_geo_from_library(library, target_id), sat, station, ts)
        f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
        t_rel = geo["t_rel_s"].to_numpy(float)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        pass_id = f"{target_id}_{str(geo['t_abs_utc'].iloc[0]).replace(':', '').replace('-', '')}"
        base_specs = base_middle_specs(t_rel, lengths)
        benign_obs: list[base.ObservationSequence] = []
        for sample_id in range(1, n_benign + 1):
            err = base.sample_error_params(ranges, rng)
            benign_obs.append(base.build_legitimate_observation(f"wae_benign_{target_id}_{sample_id:04d}", target_name, target_id, geo, err, rng, sample_id, args.seed))
        specs_by_key: dict[int | str, list[wrc.WindowSpec]] = {"full_pass": [s for s in base_specs if s.window_position == "full_pass"]}
        for length in lengths:
            specs_by_key[int(length)] = [s for s in base_specs if int(round(s.window_length_s)) == int(length)]
        cal = calibration_stats(benign_obs=benign_obs, geo=geo, f_geo_a=f_geo_a, specs_by_key=specs_by_key, threshold_types=args.threshold_types)

        observations: list[tuple[base.ObservationSequence, str, str, Any, bool, np.ndarray, str]] = []
        for obs in benign_obs:
            observations.append((obs, "benign_A", "none", "none", True, f_geo_a, "benign_A"))
        for spec in specs_all:
            f_geo_b = wrc.generate_attack_geo(spec, sat, station, ts, times, freq)
            source_key = f"{spec['attack_type']}:{spec['attack_param_name']}:{spec['attack_param_value']}"
            for sample_id in range(1, args.num_sims_per_attack + 1):
                err = base.sample_error_params(ranges, rng)
                seq_id = f"wae_attack_{attack_counter:07d}"
                attack_counter += 1
                obs = base.build_attack_observation(seq_id, target_name, target_id, geo, f_geo_b, spec, err, rng, sample_id, args.seed)
                observations.append((obs, str(spec["attack_type"]), str(spec["attack_param_name"]), float(spec["attack_param_value"]), False, f_geo_b, source_key))

        segment_cache: dict[tuple[str, str, str], list[wrc.WindowSpec]] = {}
        for obs, attack_type, param_name, param_value, is_benign, source_curve, source_key in observations:
            # Direct strong evidence groups.
            for direct_spec in base_specs:
                if direct_spec.window_position == "full_pass" or int(round(direct_spec.window_length_s)) == 180:
                    for th in args.threshold_types:
                        gid = f"{target_id}_{obs.sequence_id}_{direct_spec.window_type}_{th}"
                        rows.extend(
                            build_group_rows(
                                group_id=gid,
                                target_id=target_id,
                                target_name=target_name,
                                attack_type=attack_type,
                                attack_param_name=param_name,
                                attack_param_value=param_value,
                                is_benign=is_benign,
                                pass_id=pass_id,
                                group_mode=direct_spec.window_position,
                                segment_pattern=direct_spec.window_type,
                                observation=obs,
                                f_geo_a=f_geo_a,
                                t_rel=t_rel,
                                specs=[direct_spec],
                                cal=cal,
                                threshold_type=th,
                                args=args,
                            )
                        )
            for group_mode in args.segment_patterns:
                if group_mode == "best_attack_segments" and (not args.include_best_attack or is_benign):
                    continue
                for pattern in GROUP_PATTERNS:
                    cache_source = source_key if group_mode == "best_attack_segments" else "generic"
                    cache_key = (group_mode, pattern, cache_source)
                    if cache_key not in segment_cache:
                        specs = choose_group_specs(pattern, group_mode, t_rel, source_curve, f_geo_a, cal, args.max_overlap_ratio)
                        segment_cache[cache_key] = specs
                    specs = segment_cache[cache_key]
                    if len(specs) != len(GROUP_PATTERNS[pattern]):
                        skip_count += len(args.threshold_types)
                        continue
                    for th in args.threshold_types:
                        gid = f"{target_id}_{obs.sequence_id}_{group_mode}_{pattern}_{th}"
                        rows.extend(
                            build_group_rows(
                                group_id=gid,
                                target_id=target_id,
                                target_name=target_name,
                                attack_type=attack_type,
                                attack_param_name=param_name,
                                attack_param_value=param_value,
                                is_benign=is_benign,
                                pass_id=pass_id,
                                group_mode=group_mode,
                                segment_pattern=pattern,
                                observation=obs,
                                f_geo_a=f_geo_a,
                                t_rel=t_rel,
                                specs=specs,
                                cal=cal,
                                threshold_type=th,
                                args=args,
                            )
                        )

    dataset = pd.DataFrame(rows)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.dataset_output, index=False)
    summary = aggregate_summary(dataset)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)
    comparison = strategy_comparison(summary)
    args.comparison_output.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(args.comparison_output, index=False)
    figure_paths = make_plots(dataset, summary, args)
    write_report(args, dataset, summary, comparison, figure_paths, skip_count)
    commands = [
        "python -m py_compile scripts/run_window_aware_evidence_accumulation.py",
        "python scripts/run_window_aware_evidence_accumulation.py --max-targets 2 --max-passes-per-target 1 --num-sims-per-attack 2 --overwrite",
        "python scripts/run_window_aware_evidence_accumulation.py --overwrite",
    ]
    append_work_log(args, dataset, summary, commands)
    print(f"wrote {args.dataset_output} rows={len(dataset)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.comparison_output} rows={len(comparison)}")
    print(f"wrote {args.report_output}")
    for path in figure_paths:
        print(path)


if __name__ == "__main__":
    main()
