#!/usr/bin/env python
"""Evaluate full-pass ACCEPT / REJECT / DEFER rules."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/full_pass_tri_state_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/full_pass_tri_state_summary.csv"))
    p.add_argument("--elevation-min-deg", nargs="+", type=float, default=[15, 20, 25, 30])
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def decide(row: pd.Series, elevation_min_deg: float) -> str:
    passed = bool(row["accepted_per_pass_k_p01_p99"])
    if float(row["max_elevation_deg"]) < elevation_min_deg:
        return "DEFER" if passed else "REJECT"
    return "ACCEPT" if passed else "REJECT"


def main() -> None:
    args = parse_args()
    if (args.sequence_output.exists() or args.summary_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    if not args.sequence_eval.exists():
        fail(f"missing input: {args.sequence_eval}")
    df = pd.read_csv(args.sequence_eval)
    rows = []
    for elev in args.elevation_min_deg:
        tmp = df.copy()
        tmp["elevation_min_deg"] = float(elev)
        tmp["tri_state_decision"] = tmp.apply(lambda r: decide(r, float(elev)), axis=1)
        rows.append(tmp)
    out = pd.concat(rows, ignore_index=True)
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.sequence_output, index=False)

    summ = []
    for key, g in out.groupby(["threshold_type", "elevation_min_deg", "sample_type"], dropna=False):
        threshold_type, elev, sample_type = key
        total = len(g)
        counts = g["tri_state_decision"].value_counts()
        accept = int(counts.get("ACCEPT", 0))
        reject = int(counts.get("REJECT", 0))
        defer = int(counts.get("DEFER", 0))
        summ.append(
            {
                "threshold_type": threshold_type,
                "elevation_min_deg": elev,
                "sample_type": sample_type,
                "total_sequences": int(total),
                "accept_count": accept,
                "reject_count": reject,
                "defer_count": defer,
                "accept_rate": accept / total if total else 0.0,
                "reject_rate": reject / total if total else 0.0,
                "defer_rate": defer / total if total else 0.0,
            }
        )
    summary = pd.DataFrame(summ).sort_values(["threshold_type", "elevation_min_deg", "sample_type"])
    summary.to_csv(args.summary_output, index=False)
    print(f"wrote {args.sequence_output} rows={len(out)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
