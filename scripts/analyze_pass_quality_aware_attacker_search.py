#!/usr/bin/env python
"""Analyze pass-quality-aware attacker search outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_search_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_search_summary.csv"))
    p.add_argument("--hard-cases-output", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_hard_cases.csv"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def main() -> None:
    args = parse_args()
    if (args.summary_output.exists() or args.hard_cases_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    if not args.input.exists():
        fail(f"missing input: {args.input}")
    df = pd.read_csv(args.input)
    for col in ["accepted_score_only", "accepted_per_pass_k_p01_p99", "accepted_v3_single_pass"]:
        df[col] = to_bool(df[col])
    df["k_distance_to_min"] = df["k_hat"] - df["pass_k_min_p01"]
    df["k_distance_to_max"] = df["pass_k_max_p99"] - df["k_hat"]
    df["abs_k_distance_to_range_edge"] = df[["k_distance_to_min", "k_distance_to_max"]].abs().min(axis=1)
    rows = []
    group_cols = ["threshold_type", "target_name", "pass_id", "delta_h_km", "phase_offset_s"]
    for key, g in df.groupby(group_cols, dropna=False):
        th, target, pass_id, dh, phase = key
        rows.append(
            {
                "threshold_type": th,
                "target": target,
                "pass_id": pass_id,
                "delta_h_km": dh,
                "phase_offset": phase,
                "total_sequences": int(len(g)),
                "score_only_accepts": int(g["accepted_score_only"].sum()),
                "per_pass_k_gate_accepts": int(g["accepted_per_pass_k_p01_p99"].sum()),
                "v3_single_pass_accepts": int(g["accepted_v3_single_pass"].sum()),
                "min_normalized_score": float(g["normalized_score"].min()),
                "median_normalized_score": float(g["normalized_score"].median()),
                "min_abs_k_distance_to_range_edge": float(g["abs_k_distance_to_range_edge"].min()),
                "accepted_count": int(g["accepted_v3_single_pass"].sum()),
            }
        )
    summary = pd.DataFrame(rows).sort_values(["threshold_type", "accepted_count", "min_normalized_score"], ascending=[True, False, True])
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary_output, index=False)

    parts = []
    top_low = df.nsmallest(50, "normalized_score").copy()
    top_low["hard_case_type"] = "lowest_normalized_score_top50"
    parts.append(top_low)
    near = df.assign(distance_to_threshold=(df["normalized_score"] - 1.0).abs()).nsmallest(50, "distance_to_threshold").copy()
    near["hard_case_type"] = "closest_to_threshold_top50"
    parts.append(near)
    score_pass_k_reject = df[df["accepted_score_only"] & ~df["accepted_per_pass_k_p01_p99"]].copy()
    score_pass_k_reject = score_pass_k_reject.sort_values("normalized_score").head(200)
    score_pass_k_reject["hard_case_type"] = "score_pass_k_gate_rejected"
    parts.append(score_pass_k_reject)
    score_k_accept = df[df["accepted_per_pass_k_p01_p99"]].copy()
    score_k_accept = score_k_accept.sort_values("normalized_score").head(200)
    score_k_accept["hard_case_type"] = "score_plus_k_gate_accepted"
    parts.append(score_k_accept)
    v3_accept = df[df["accepted_v3_single_pass"]].copy()
    v3_accept = v3_accept.sort_values("normalized_score").head(200)
    v3_accept["hard_case_type"] = "v3_single_pass_accepted"
    parts.append(v3_accept)
    hard = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    cols = ["hard_case_type"] + [c for c in hard.columns if c != "hard_case_type"]
    hard = hard[cols] if not hard.empty else hard
    hard.to_csv(args.hard_cases_output, index=False)
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.hard_cases_output} rows={len(hard)}")
    if not df.empty:
        print(df.groupby("threshold_type")[["accepted_score_only", "accepted_per_pass_k_p01_p99", "accepted_v3_single_pass"]].sum().to_string())


if __name__ == "__main__":
    main()
