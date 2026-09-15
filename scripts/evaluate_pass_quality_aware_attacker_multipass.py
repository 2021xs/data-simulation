#!/usr/bin/env python
"""Evaluate whether one perturbation passes multiple high-quality full passes."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_search_sequence_eval.csv"))
    p.add_argument("--output", type=Path, default=Path("outputs/metrics/pass_quality_aware_attacker_multipass_summary.csv"))
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
    if args.output.exists() and not args.overwrite:
        fail("output exists; add --overwrite")
    if not args.input.exists():
        fail(f"missing input: {args.input}")
    df = pd.read_csv(args.input)
    df["accepted_v3_single_pass"] = to_bool(df["accepted_v3_single_pass"])
    rows = []
    group_cols = ["target_name", "attack_source_sat_id", "delta_h_km", "phase_offset_s", "threshold_type"]
    for key, g in df.groupby(group_cols, dropna=False):
        target, source, dh, phase, th = key
        pass_summary = g.groupby("pass_id").agg(
            pass_accepted=("accepted_v3_single_pass", "any"),
            min_normalized_score=("normalized_score", "min"),
            median_normalized_score=("normalized_score", "median"),
            max_normalized_score=("normalized_score", "max"),
            median_k_hat=("k_hat", "median"),
        ).reset_index()
        accepted_pass_count = int(pass_summary["pass_accepted"].sum())
        num_passes = int(len(pass_summary))
        rows.append(
            {
                "target": target,
                "attack_source": source,
                "delta_h_km": dh,
                "phase_offset": phase,
                "threshold_type": th,
                "num_high_quality_passes": num_passes,
                "accepted_pass_count": accepted_pass_count,
                "accepted_pass_rate": accepted_pass_count / num_passes if num_passes else 0.0,
                "any_high_quality_accept": bool(accepted_pass_count >= 1),
                "two_high_quality_accept": bool(accepted_pass_count >= 2),
                "all_high_quality_accept": bool(num_passes > 0 and accepted_pass_count == num_passes),
                "min_normalized_score": float(g["normalized_score"].min()),
                "median_normalized_score": float(g["normalized_score"].median()),
                "max_normalized_score": float(g["normalized_score"].max()),
                "median_k_hat": float(g["k_hat"].median()),
            }
        )
    out = pd.DataFrame(rows).sort_values(["threshold_type", "accepted_pass_count", "min_normalized_score"], ascending=[True, False, True])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"wrote {args.output} rows={len(out)}")
    if not out.empty:
        print(out.groupby("threshold_type")[["any_high_quality_accept", "two_high_quality_accept", "all_high_quality_accept"]].sum().to_string())


if __name__ == "__main__":
    main()
