#!/usr/bin/env python
"""Evaluate multi-pass aggregation on expanded full-pass quality coverage."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_sequence_eval.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_multipass_aggregation_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv"))
    p.add_argument("--elevation-min-deg", nargs="+", type=float, default=[15, 20, 25, 30, 35, 40])
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


RULES = [
    "single_pass_v2_baseline",
    "defer_if_only_low_quality",
    "any_high_quality_accept",
    "two_high_quality_accept",
    "all_high_quality_accept",
]


def fail(msg: str) -> None:
    raise SystemExit(msg)


def add_case_id(df: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, g in df.groupby(["threshold_type", "sample_type", "target_sat_id", "delta_h_km", "pass_id"], dropna=False, sort=False):
        tmp = g.copy()
        tmp["case_index"] = np.arange(1, len(tmp) + 1)
        parts.append(tmp)
    return pd.concat(parts, ignore_index=True)


def final_decision(g: pd.DataFrame, rule: str, elev: float) -> str:
    high = g[g["max_elevation_deg"] >= elev]
    low = g[g["max_elevation_deg"] < elev]
    high_accept = int(high["accepted_per_pass_k_p01_p99"].sum())
    high_total = len(high)
    low_accept = int(low["accepted_per_pass_k_p01_p99"].sum())
    first = g.sort_values("pass_start_utc").iloc[0]
    if rule == "single_pass_v2_baseline":
        return "ACCEPT" if bool(first["accepted_per_pass_k_p01_p99"]) else "REJECT"
    if rule in {"defer_if_only_low_quality", "any_high_quality_accept"}:
        if high_accept >= 1:
            return "ACCEPT"
        return "DEFER" if low_accept > 0 else "REJECT"
    if rule == "two_high_quality_accept":
        if high_accept >= 2:
            return "ACCEPT"
        return "DEFER" if (high_accept == 1 or low_accept > 0) else "REJECT"
    if rule == "all_high_quality_accept":
        if high_total > 0 and high_accept == high_total:
            return "ACCEPT"
        return "DEFER" if (high_accept > 0 or low_accept > 0) else "REJECT"
    raise ValueError(rule)


def main() -> None:
    args = parse_args()
    if (args.sequence_output.exists() or args.summary_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    if not args.sequence_eval.exists():
        fail(f"missing input: {args.sequence_eval}")
    df = add_case_id(pd.read_csv(args.sequence_eval))
    rows = []
    case_cols = ["threshold_type", "sample_type", "target_sat_id", "target_name", "delta_h_km", "case_index"]
    for elev in args.elevation_min_deg:
        for key, g in df.groupby(case_cols, dropna=False):
            th, sample_type, tid, name, dh, case_idx = key
            for rule in RULES:
                rows.append(
                    {
                        "threshold_type": th,
                        "elevation_min_deg": float(elev),
                        "aggregation_rule": rule,
                        "sample_type": sample_type,
                        "target_sat_id": tid,
                        "target_name": name,
                        "delta_h_km": dh,
                        "case_index": case_idx,
                        "num_passes": int(g["pass_id"].nunique()),
                        "high_quality_passes": int((g["max_elevation_deg"] >= elev).sum()),
                        "low_quality_passes": int((g["max_elevation_deg"] < elev).sum()),
                        "accepted_passes": int(g["accepted_per_pass_k_p01_p99"].sum()),
                        "final_decision": final_decision(g, rule, float(elev)),
                    }
                )
    out = pd.DataFrame(rows)
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.sequence_output, index=False)
    summ = []
    for key, g in out.groupby(["threshold_type", "elevation_min_deg", "aggregation_rule", "sample_type"], dropna=False):
        th, elev, rule, sample_type = key
        total = len(g)
        counts = g["final_decision"].value_counts()
        accept = int(counts.get("ACCEPT", 0))
        reject = int(counts.get("REJECT", 0))
        defer = int(counts.get("DEFER", 0))
        summ.append(
            {
                "threshold_type": th,
                "elevation_min_deg": elev,
                "aggregation_rule": rule,
                "sample_type": sample_type,
                "total_cases": int(total),
                "final_accept_count": accept,
                "final_reject_count": reject,
                "final_defer_count": defer,
                "final_accept_rate": accept / total if total else 0.0,
                "final_reject_rate": reject / total if total else 0.0,
                "final_defer_rate": defer / total if total else 0.0,
                "notes": "expanded full-pass aggregation only; no multi-window",
            }
        )
    summary = pd.DataFrame(summ).sort_values(["threshold_type", "elevation_min_deg", "aggregation_rule", "sample_type"])
    summary.to_csv(args.summary_output, index=False)
    print(f"wrote {args.sequence_output} rows={len(out)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
