#!/usr/bin/env python
"""Merge original and expanded full-pass quality samples, then summarize bins."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--base-eval", type=Path, default=Path("outputs/metrics/full_pass_adequacy_sequence_eval.csv"))
    p.add_argument("--expansion-eval", type=Path, default=Path("outputs/metrics/full_pass_quality_expansion_sequence_eval.csv"))
    p.add_argument("--sequence-output", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_bin_summary.csv"))
    p.add_argument("--sanity-output", type=Path, default=Path("outputs/metrics/full_pass_quality_expanded_legit_calibration_sanity.csv"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def elevation_bin(v: float) -> str:
    if v < 20:
        return "low"
    if v < 40:
        return "medium"
    return "high"


def normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    out = df.copy()
    if "attack_source_sat_id" not in out.columns:
        out["attack_source_sat_id"] = ""
    if "attack_source_name" not in out.columns:
        out["attack_source_name"] = ""
    optional_cols = [
        "pass_k_min_p01",
        "pass_k_max_p99",
        "pass_k_min_p05",
        "pass_k_max_p95",
        "k_range_width",
        "legit_calibration_count",
        "score_threshold_source",
        "k_range_source",
    ]
    for col in optional_cols:
        if col not in out.columns:
            warn(f"{source} input missing optional audit field {col}; filling with NA")
            out[col] = np.nan
    if out["k_range_width"].isna().all() and {"pass_k_min_p01", "pass_k_max_p99"}.issubset(out.columns):
        out["k_range_width"] = out["pass_k_max_p99"] - out["pass_k_min_p01"]
    out["elevation_bin"] = out["max_elevation_deg"].astype(float).map(elevation_bin)
    out["data_source"] = source
    cols = [
        "data_source",
        "target_sat_id",
        "target_name",
        "pass_id",
        "pass_start_utc",
        "pass_end_utc",
        "pass_duration_s",
        "max_elevation_deg",
        "elevation_bin",
        "sample_type",
        "attack_source_sat_id",
        "attack_source_name",
        "delta_h_km",
        "threshold_type",
        "score",
        "threshold",
        "normalized_score",
        "b_hat",
        "k_hat",
        "pass_k_min_p01",
        "pass_k_max_p99",
        "pass_k_min_p05",
        "pass_k_max_p95",
        "k_range_width",
        "legit_calibration_count",
        "score_threshold_source",
        "k_range_source",
        "accepted_score_only",
        "accepted_per_pass_k_p01_p99",
        "num_points",
    ]
    return out[cols]


def to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(["threshold_type", "elevation_bin", "sample_type"], dropna=False):
        th, bin_name, sample_type = key
        rows.append(
            {
                "threshold_type": th,
                "elevation_bin": bin_name,
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
                "notes": "expanded_full_pass_quality_coverage",
            }
        )
    order = {"low": 0, "medium": 1, "high": 2}
    out = pd.DataFrame(rows)
    out["_o"] = out["elevation_bin"].map(order)
    return out.sort_values(["threshold_type", "_o", "sample_type"]).drop(columns="_o")


def summarize_legit_sanity(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    d = df[df["sample_type"] == "legit"].copy()
    d["accepted_score_only"] = to_bool(d["accepted_score_only"])
    d["accepted_per_pass_k_p01_p99"] = to_bool(d["accepted_per_pass_k_p01_p99"])
    d["score_pass_recomputed"] = d["score"] <= d["threshold"]
    has_k = d["pass_k_min_p01"].notna() & d["pass_k_max_p99"].notna()
    d["k_pass_recomputed"] = np.where(has_k, (d["pass_k_min_p01"] <= d["k_hat"]) & (d["k_hat"] <= d["pass_k_max_p99"]), np.nan)
    d["accepted_recomputed"] = np.where(has_k, d["score_pass_recomputed"] & d["k_pass_recomputed"].astype(bool), d["accepted_per_pass_k_p01_p99"])
    for key, g in d.groupby(["elevation_bin", "threshold_type"], dropna=False):
        bin_name, th = key
        has_k_g = g["k_pass_recomputed"].notna()
        score_fail = (~g["score_pass_recomputed"] & (g["k_pass_recomputed"].fillna(True))).sum()
        k_fail = (g["score_pass_recomputed"] & (g["k_pass_recomputed"] == False)).sum()  # noqa: E712
        both_fail = (~g["score_pass_recomputed"] & (g["k_pass_recomputed"] == False)).sum()  # noqa: E712
        notes = []
        if not has_k_g.all():
            notes.append("some_rows_missing_k_range_audit_fields")
        rows.append(
            {
                "elevation_bin": bin_name,
                "threshold_type": th,
                "legit_calibration_count_per_pass_median": float(g["legit_calibration_count"].median()) if g["legit_calibration_count"].notna().any() else np.nan,
                "total_legit_sequences": int(len(g)),
                "score_only_accept_rate": float(g["accepted_score_only"].mean()),
                "per_pass_k_gate_accept_rate": float(g["accepted_per_pass_k_p01_p99"].mean()),
                "score_fail_count": int(score_fail),
                "k_gate_fail_count": int(k_fail),
                "both_fail_count": int(both_fail),
                "median_k_range_width": float(g["k_range_width"].median()) if g["k_range_width"].notna().any() else np.nan,
                "notes": ";".join(notes),
            }
        )
    order = {"low": 0, "medium": 1, "high": 2}
    out = pd.DataFrame(rows)
    out["_o"] = out["elevation_bin"].map(order)
    return out.sort_values(["threshold_type", "_o"]).drop(columns="_o")


def main() -> None:
    args = parse_args()
    if (args.sequence_output.exists() or args.summary_output.exists() or args.sanity_output.exists()) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    for p in [args.base_eval, args.expansion_eval]:
        if not p.exists():
            fail(f"missing input: {p}")
    base = normalize(pd.read_csv(args.base_eval), "base")
    exp = normalize(pd.read_csv(args.expansion_eval), "expansion")
    df = pd.concat([base, exp], ignore_index=True)
    args.sequence_output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.sequence_output, index=False)
    summary = summarize(df)
    summary.to_csv(args.summary_output, index=False)
    sanity = summarize_legit_sanity(df)
    sanity.to_csv(args.sanity_output, index=False)
    print(f"wrote {args.sequence_output} rows={len(df)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.sanity_output} rows={len(sanity)}")
    print(summary.to_string(index=False))
    print(sanity.to_string(index=False))


if __name__ == "__main__":
    main()
