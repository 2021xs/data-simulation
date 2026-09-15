#!/usr/bin/env python
"""Plot figures for the 20 deg elevation-threshold justification."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


BIN_LABELS = ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-40", "40-60", "60+"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/elevation_threshold_justification"))
    p.add_argument("--availability-suffix", default="300")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def save(fig: plt.Figure, path: Path, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        fail(f"output exists; add --overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def read_required(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"missing input: {path}")
    return pd.read_csv(path)


def primary_attack_source(df: pd.DataFrame) -> str:
    preferred = "pass_quality_aware_attacker_search_sequence_eval.csv"
    if preferred in set(df["source_file"].dropna()):
        return preferred
    return str(df["source_file"].dropna().iloc[0])


def boundary_safety_source(df: pd.DataFrame) -> str:
    preferred = "full_pass_quality_expanded_sequence_eval.csv"
    if preferred in set(df["source_file"].dropna()):
        return preferred
    fallback = "full_pass_adequacy_sequence_eval.csv"
    if fallback in set(df["source_file"].dropna()):
        return fallback
    return str(df["source_file"].dropna().iloc[0])


def ordered_bins(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["elevation_bin"] = pd.Categorical(out["elevation_bin"], BIN_LABELS, ordered=True)
    return out.sort_values("elevation_bin")


def plot_attack_accept_rate(attack: pd.DataFrame, out: Path, overwrite: bool) -> None:
    source = primary_attack_source(attack)
    d = ordered_bins(attack[attack["source_file"] == source])
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, th in zip(axes, ["p95", "p99"]):
        g = d[d["threshold_type"] == th]
        x = np.arange(len(BIN_LABELS))
        ax.plot(x, g.set_index("elevation_bin").reindex(BIN_LABELS)["score_only_accept_rate"], marker="o", label="score-only")
        ax.plot(x, g.set_index("elevation_bin").reindex(BIN_LABELS)["score_k_accept_rate"], marker="s", label="score+k")
        if "v3_accept_rate" in g.columns:
            ax.plot(x, g.set_index("elevation_bin").reindex(BIN_LABELS)["v3_accept_rate"], marker="^", label="v3")
        ax.axvline(3.5, color="#444444", linestyle=":", linewidth=1.5, label="20 deg")
        ax.set_xticks(x, BIN_LABELS, rotation=35, ha="right")
        ax.set_ylim(bottom=0)
        ax.set_title(f"Attack accept rate by elevation bin ({th})")
        ax.set_xlabel("max elevation bin (deg)")
        ax.grid(True, axis="y", alpha=0.25)
    axes[0].set_ylabel("accept rate")
    axes[0].legend()
    save(fig, out, overwrite)


def plot_legit_accept_rate(legit: pd.DataFrame, out: Path, overwrite: bool) -> None:
    d = ordered_bins(legit)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
    for ax, th in zip(axes, ["p95", "p99"]):
        g = d[d["threshold_type"] == th]
        x = np.arange(len(BIN_LABELS))
        ax.plot(x, g.set_index("elevation_bin").reindex(BIN_LABELS)["score_only_accept_rate"], marker="o", label="score-only")
        ax.plot(x, g.set_index("elevation_bin").reindex(BIN_LABELS)["score_k_accept_rate"], marker="s", label="score+k")
        ax.axvline(3.5, color="#444444", linestyle=":", linewidth=1.5, label="20 deg")
        ax.set_xticks(x, BIN_LABELS, rotation=35, ha="right")
        ax.set_ylim(0, 1.05)
        ax.set_title(f"Legit accept rate by elevation bin ({th})")
        ax.set_xlabel("max elevation bin (deg)")
        ax.grid(True, axis="y", alpha=0.25)
    axes[0].set_ylabel("accept rate")
    axes[0].legend()
    save(fig, out, overwrite)


def plot_safety_tradeoff(safety: pd.DataFrame, out: Path, overwrite: bool) -> None:
    source = boundary_safety_source(safety)
    safety = safety[safety["source_file"] == source].copy()
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for th, marker in [("p95", "o"), ("p99", "s")]:
        g = safety[safety["threshold_type"] == th].sort_values("threshold_deg")
        ax.plot(g["threshold_deg"], g["qualified_score_k_accept_rate"], marker=marker, label=f"{th} score+k")
        if "qualified_v3_accept_rate" in g.columns and g["qualified_v3_accept_rate"].notna().any():
            ax.plot(g["threshold_deg"], g["qualified_v3_accept_rate"], marker=marker, linestyle="--", label=f"{th} v3")
    ax.axvline(20, color="#444444", linestyle=":", linewidth=1.5, label="20 deg")
    ax.set_xlabel("candidate elevation threshold (deg)")
    ax.set_ylabel("qualified attack accept rate")
    ax.set_title("Safety tradeoff by elevation threshold")
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    save(fig, out, overwrite)


def plot_availability_tradeoff(avail: pd.DataFrame, out: Path, overwrite: bool) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.8))
    for duration, marker in [(7, "o"), (14, "s"), (30, "^")]:
        g = avail[avail["duration_days"] == duration].sort_values("threshold_deg")
        ax.plot(g["threshold_deg"], g["qualified_coverage_rate"], marker=marker, label=f"{duration} days")
    ax.axvline(20, color="#444444", linestyle=":", linewidth=1.5, label="20 deg")
    ax.set_xlabel("candidate elevation threshold (deg)")
    ax.set_ylabel("target coverage rate")
    ax.set_title("300-target availability by elevation threshold")
    ax.set_ylim(0, 1.05)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    save(fig, out, overwrite)


def plot_wait_tradeoff(avail: pd.DataFrame, out: Path, overwrite: bool) -> None:
    d = avail[avail["duration_days"] == 30].sort_values("threshold_deg")
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.plot(d["threshold_deg"], d["median_time_to_first_qualified_pass_hours"], marker="o", label="median wait")
    ax.plot(d["threshold_deg"], d["p90_time_to_first_qualified_pass_hours"], marker="s", label="p90 wait")
    ax.axvline(20, color="#444444", linestyle=":", linewidth=1.5, label="20 deg")
    ax.set_xlabel("candidate elevation threshold (deg)")
    ax.set_ylabel("time to first qualified pass (hours)")
    ax.set_title("300-target waiting time by elevation threshold (30 days)")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    save(fig, out, overwrite)


def plot_threshold_choice_summary(safety: pd.DataFrame, avail: pd.DataFrame, out: Path, overwrite: bool) -> None:
    source = boundary_safety_source(safety)
    s = safety[(safety["threshold_type"] == "p95") & (safety["source_file"] == source)].sort_values("threshold_deg")
    a = avail[avail["duration_days"] == 30].sort_values("threshold_deg")
    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.plot(s["threshold_deg"], s["qualified_score_k_accept_rate"], marker="o", color="#b34f3f", label="attack accept rate (p95 score+k)")
    ax1.set_xlabel("candidate elevation threshold (deg)")
    ax1.set_ylabel("attack accept rate", color="#b34f3f")
    ax1.tick_params(axis="y", labelcolor="#b34f3f")
    ax1.set_ylim(bottom=0)
    ax2 = ax1.twinx()
    ax2.plot(a["threshold_deg"], a["qualified_coverage_rate"], marker="s", color="#2f6f9f", label="30-day coverage")
    ax2.plot(a["threshold_deg"], a["p90_time_to_first_qualified_pass_hours"], marker="^", color="#4f8f62", label="p90 wait hours")
    ax2.set_ylabel("coverage rate / p90 wait hours")
    ax1.axvline(20, color="#444444", linestyle=":", linewidth=1.5)
    ax1.set_title("20 deg as a safety-availability tradeoff")
    ax1.grid(True, axis="y", alpha=0.25)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best")
    save(fig, out, overwrite)


def main() -> None:
    args = parse_args()
    attack = read_required(args.metrics_dir / "elevation_threshold_attack_rate_by_bin.csv")
    legit = read_required(args.metrics_dir / "elevation_threshold_legit_rate_by_bin.csv")
    safety = read_required(args.metrics_dir / "elevation_threshold_safety_tradeoff.csv")
    avail = read_required(args.metrics_dir / f"elevation_threshold_availability_tradeoff_{args.availability_suffix}.csv")
    args.figures_dir.mkdir(parents=True, exist_ok=True)

    plot_attack_accept_rate(attack, args.figures_dir / "attack_accept_rate_vs_elevation_bin.png", args.overwrite)
    plot_legit_accept_rate(legit, args.figures_dir / "legit_accept_rate_vs_elevation_bin.png", args.overwrite)
    plot_safety_tradeoff(safety, args.figures_dir / "safety_tradeoff_by_threshold.png", args.overwrite)
    plot_availability_tradeoff(avail, args.figures_dir / "availability_tradeoff_by_threshold_300.png", args.overwrite)
    plot_wait_tradeoff(avail, args.figures_dir / "time_to_first_qualified_pass_by_threshold_300.png", args.overwrite)
    plot_threshold_choice_summary(safety, avail, args.figures_dir / "threshold_choice_summary.png", args.overwrite)
    print(f"wrote figures to {args.figures_dir}")


if __name__ == "__main__":
    main()
