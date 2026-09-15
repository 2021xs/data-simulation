#!/usr/bin/env python
"""Audit full-pass elevation-bin coverage for hard-case targets/pairs."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--selected-pairs", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_selected_pairs.csv"))
    p.add_argument("--audit-output", type=Path, default=Path("outputs/metrics/full_pass_quality_coverage_audit.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/full_pass_quality_coverage_summary.csv"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def elevation_bin(v: float) -> str:
    if v < 20:
        return "low"
    if v < 40:
        return "medium"
    return "high"


def main() -> None:
    args = parse_args()
    if (args.audit_output.exists() or args.summary_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    for p in [args.sequence_eval, args.selected_pairs]:
        if not p.exists():
            fail(f"missing input: {p}")
    seq = pd.read_csv(args.sequence_eval)
    pairs = pd.read_csv(args.selected_pairs)
    passes = seq[["target_sat_id", "target_name", "pass_id", "max_elevation_deg"]].drop_duplicates().copy()
    passes["target_sat_id"] = passes["target_sat_id"].astype(str)
    passes["elevation_bin"] = passes["max_elevation_deg"].astype(float).map(elevation_bin)
    pair_rows = pairs[["target_sat_id", "target_name", "attack_source_sat_id", "attack_source_name", "delta_h_km"]].drop_duplicates().copy()
    pair_rows["target_sat_id"] = pair_rows["target_sat_id"].astype(str)
    rows = []
    for _, pair in pair_rows.iterrows():
        ppass = passes[passes["target_sat_id"] == str(pair["target_sat_id"])]
        counts = ppass["elevation_bin"].value_counts()
        notes = []
        if counts.get("medium", 0) == 0:
            notes.append("needs_medium_pass")
        if counts.get("high", 0) < 2:
            notes.append("needs_more_high_pass")
        rows.append(
            {
                "target_sat_id": pair["target_sat_id"],
                "target_name": pair["target_name"],
                "attack_source_sat_id": pair["attack_source_sat_id"],
                "attack_source_name": pair["attack_source_name"],
                "delta_h_km": float(pair["delta_h_km"]),
                "total_passes": int(len(ppass)),
                "low_pass_count": int(counts.get("low", 0)),
                "medium_pass_count": int(counts.get("medium", 0)),
                "high_pass_count": int(counts.get("high", 0)),
                "min_max_elevation_deg": float(ppass["max_elevation_deg"].min()) if len(ppass) else np.nan,
                "median_max_elevation_deg": float(ppass["max_elevation_deg"].median()) if len(ppass) else np.nan,
                "max_max_elevation_deg": float(ppass["max_elevation_deg"].max()) if len(ppass) else np.nan,
                "notes": ";".join(notes) if notes else "coverage_ok_for_current_bins",
            }
        )
    audit = pd.DataFrame(rows).sort_values(["target_sat_id", "delta_h_km"])
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(args.audit_output, index=False)

    summ_rows = []
    merged = pair_rows.merge(passes, on=["target_sat_id", "target_name"], how="left")
    for bin_name in ["low", "medium", "high"]:
        g = merged[merged["elevation_bin"] == bin_name]
        seq_g = seq[seq["max_elevation_deg"].astype(float).map(elevation_bin) == bin_name]
        summ_rows.append(
            {
                "elevation_bin": bin_name,
                "total_passes": int(passes[passes["elevation_bin"] == bin_name]["pass_id"].nunique()),
                "total_sequences": int(len(seq_g)),
                "target_count": int(g["target_sat_id"].nunique()),
                "attack_pair_count": int(g[["target_sat_id", "delta_h_km"]].drop_duplicates().shape[0]),
                "notes": "missing_medium_coverage" if bin_name == "medium" and g.empty else "",
            }
        )
    summary = pd.DataFrame(summ_rows)
    summary.to_csv(args.summary_output, index=False)
    print(f"wrote {args.audit_output} rows={len(audit)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(audit.to_string(index=False))
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
