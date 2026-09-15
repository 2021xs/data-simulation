#!/usr/bin/env python
"""Analyze full-pass adequacy by pass elevation quality."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--multipass-seq", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/full_pass_adequacy_elevation_bin_summary.csv"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def elevation_bin(x: float) -> str:
    if x < 20:
        return "low"
    if x < 40:
        return "medium"
    return "high"


def main() -> None:
    args = parse_args()
    if (args.sequence_output.exists() or args.summary_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    if not args.multipass_seq.exists():
        fail(f"missing input: {args.multipass_seq}")
    df = pd.read_csv(args.multipass_seq)
    required = [
        "target_sat_id",
        "target_name",
        "pass_id",
        "pass_start_utc",
        "pass_end_utc",
        "pass_duration_s",
        "max_elevation_deg",
        "num_points",
        "threshold_type",
        "sample_type",
        "delta_h_km",
        "score",
        "threshold",
        "normalized_score",
        "b_hat",
        "k_hat",
        "accepted_score_only",
        "accepted_per_pass_k_p01_p99",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        fail("missing columns: " + ", ".join(missing))
    out = df[required].copy()
    out["elevation_bin"] = out["max_elevation_deg"].astype(float).map(elevation_bin)
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.sequence_output, index=False)

    rows = []
    for key, g in out.groupby(["threshold_type", "elevation_bin", "sample_type"], dropna=False):
        threshold_type, elev_bin, sample_type = key
        rows.append(
            {
                "threshold_type": threshold_type,
                "elevation_bin": elev_bin,
                "sample_type": sample_type,
                "total_sequences": int(len(g)),
                "score_only_accepts": int(g["accepted_score_only"].sum()),
                "per_pass_k_gate_accepts": int(g["accepted_per_pass_k_p01_p99"].sum()),
                "score_only_accept_rate": float(g["accepted_score_only"].mean()),
                "per_pass_k_gate_accept_rate": float(g["accepted_per_pass_k_p01_p99"].mean()),
                "median_normalized_score": float(g["normalized_score"].median()),
                "p05_normalized_score": float(g["normalized_score"].quantile(0.05)),
                "p95_normalized_score": float(g["normalized_score"].quantile(0.95)),
                "median_k_hat": float(g["k_hat"].median()),
                "p05_k_hat": float(g["k_hat"].quantile(0.05)),
                "p95_k_hat": float(g["k_hat"].quantile(0.95)),
                "median_max_elevation_deg": float(g["max_elevation_deg"].median()),
                "median_pass_duration_s": float(g["pass_duration_s"].median()),
            }
        )
    summary = pd.DataFrame(rows)
    order = {"low": 0, "medium": 1, "high": 2}
    summary["_order"] = summary["elevation_bin"].map(order)
    summary = summary.sort_values(["threshold_type", "_order", "sample_type"]).drop(columns="_order")
    summary.to_csv(args.summary_output, index=False)
    print(f"wrote {args.sequence_output} rows={len(out)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
