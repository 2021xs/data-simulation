#!/usr/bin/env python
"""Summarize verifier v2 fine sweep gate robustness and hard cases."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--altitude-eval", type=Path, default=Path("outputs/metrics/verifier_v2_altitude_fine_sweep_sequence_eval.csv"))
    parser.add_argument("--phase-eval", type=Path, default=Path("outputs/metrics/verifier_v2_phase_fine_sweep_sequence_eval.csv"))
    parser.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv"))
    parser.add_argument("--hard-cases-output", type=Path, default=Path("outputs/metrics/verifier_v2_fine_sweep_hard_cases.csv"))
    parser.add_argument("--threshold-type", choices=["p95", "p99", "all"], default="all")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def load_eval(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"input not found: {path}")
    df = pd.read_csv(path)
    required = [
        "sequence_id",
        "target_sat_id",
        "target_name",
        "attack_source_name",
        "attack_type",
        "attack_param_name",
        "attack_param_value",
        "threshold_type",
        "score",
        "threshold",
        "normalized_score",
        "b_hat",
        "k_hat",
        "target_k_min_p01",
        "target_k_max_p99",
        "accepted_score_only",
        "accepted_per_target_k_p01_p99",
        "accepted_per_target_k_p05_p95",
        "rejection_reason",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        fail(f"{path} missing columns: " + ", ".join(missing))
    return df


def threshold_filter(df: pd.DataFrame, threshold_type: str) -> pd.DataFrame:
    if threshold_type == "all":
        return df.copy()
    return df[df["threshold_type"] == threshold_type].copy()


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_cols = ["threshold_type", "attack_type", "attack_param_name", "attack_param_value"]
    for key, group in df.groupby(group_cols, sort=True):
        threshold_type, attack_type, param_name, param_value = key
        total = len(group)
        score_accepts = int(group["accepted_score_only"].sum())
        global_accepts = int(group["accepted_global_k_gate"].sum())
        p01_accepts = int(group["accepted_per_target_k_p01_p99"].sum())
        p05_accepts = int(group["accepted_per_target_k_p05_p95"].sum())
        rows.append(
            {
                "threshold_type": threshold_type,
                "attack_type": attack_type,
                "attack_param_name": param_name,
                "attack_param_value": param_value,
                "total_sequences": int(total),
                "score_only_accepts": score_accepts,
                "global_k_gate_accepts": global_accepts,
                "per_target_k_p01_p99_accepts": p01_accepts,
                "per_target_k_p05_p95_accepts": p05_accepts,
                "score_only_false_accept_rate": score_accepts / total if total else np.nan,
                "global_k_false_accept_rate": global_accepts / total if total else np.nan,
                "per_target_k_p01_p99_false_accept_rate": p01_accepts / total if total else np.nan,
                "per_target_k_p05_p95_false_accept_rate": p05_accepts / total if total else np.nan,
                "median_normalized_score": float(group["normalized_score"].median()),
                "p05_normalized_score": float(group["normalized_score"].quantile(0.05)),
                "p95_normalized_score": float(group["normalized_score"].quantile(0.95)),
                "median_k_hat": float(group["k_hat"].median()),
                "p05_k_hat": float(group["k_hat"].quantile(0.05)),
                "p95_k_hat": float(group["k_hat"].quantile(0.95)),
            }
        )
    return pd.DataFrame(rows)


def hard_case_rows(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    p95 = df[df["threshold_type"] == "p95"].copy()
    if p95.empty:
        p95 = df.copy()
    lowest = p95.sort_values("normalized_score", ascending=True).head(30).copy()
    lowest["hard_case_type"] = "lowest_normalized_score_top30"
    rows.append(lowest)

    closest = p95.assign(distance_to_threshold=(p95["normalized_score"] - 1.0).abs()).sort_values("distance_to_threshold").head(30).copy()
    closest["hard_case_type"] = "normalized_score_closest_to_1_top30"
    rows.append(closest)

    score_only_k_rejected = p95[(p95["accepted_score_only"]) & (~p95["accepted_per_target_k_p01_p99"])].copy()
    score_only_k_rejected["hard_case_type"] = "score_only_accepted_but_k_gate_rejected"
    rows.append(score_only_k_rejected)

    k_accepted = p95[p95["accepted_per_target_k_p01_p99"]].copy()
    k_accepted["hard_case_type"] = "score_plus_per_target_k_p01_p99_accepted"
    rows.append(k_accepted)

    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if out.empty:
        return out
    out["target"] = out["target_name"].astype(str) + " / " + out["target_sat_id"].astype(str)
    out["attack_source"] = out["attack_source_name"].astype(str)
    out["attack_param"] = out["attack_param_name"].astype(str) + "=" + out["attack_param_value"].astype(str)
    cols = [
        "hard_case_type",
        "sequence_id",
        "target",
        "attack_source",
        "attack_type",
        "attack_param",
        "score",
        "threshold",
        "normalized_score",
        "b_hat",
        "k_hat",
        "target_k_min_p01",
        "target_k_max_p99",
        "accepted_score_only",
        "accepted_per_target_k_p01_p99",
        "rejection_reason",
    ]
    return out[cols].drop_duplicates(["hard_case_type", "sequence_id", "attack_param", "threshold"])


def main() -> None:
    args = parse_args()
    outputs = [args.summary_output, args.hard_cases_output]
    if any(path.exists() for path in outputs) and not args.overwrite:
        fail("output exists; add --overwrite")
    altitude = load_eval(args.altitude_eval)
    phase = load_eval(args.phase_eval)
    df = threshold_filter(pd.concat([altitude, phase], ignore_index=True), args.threshold_type)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(df)
    hard = hard_case_rows(df)
    summary.to_csv(args.summary_output, index=False)
    hard.to_csv(args.hard_cases_output, index=False)
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.hard_cases_output} rows={len(hard)}")
    for attack_type in sorted(df["attack_type"].unique()):
        for th in sorted(df["threshold_type"].unique()):
            sub = df[(df["attack_type"] == attack_type) & (df["threshold_type"] == th)]
            print(
                f"{attack_type} {th}: total={len(sub)} "
                f"score_only={int(sub['accepted_score_only'].sum())} "
                f"per_target_k_p01_p99={int(sub['accepted_per_target_k_p01_p99'].sum())}"
            )


if __name__ == "__main__":
    main()
