#!/usr/bin/env python
"""Expanded segment-local fixed-site confirmation run.

This script keeps the corrected heatmap semantics:
receiver_mode=heatmap_mode, evaluation_scope=segment_local, and
doppler_reference_mode=fixed_site_segment_center.  It compares real TLE
candidates with legacy synthetic hard cases under the same local fixed-site
Doppler path.  This is a controlled simulation, not a Starlink scheduling
reproduction.
"""

from __future__ import annotations

import argparse
import math
import sys
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

import run_fixed_reference_compensation_extended_sensitivity as ext  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


DISTANCES_MAIN = [0.0, 2.5, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0]
DISTANCES_SMOKE = [0.0, 5.0, 50.0, 200.0]
R_CELLS_MAIN = [50.0, 100.0, 200.0, 500.0]
R_CELLS_SMOKE = [200.0, 500.0]
PHIS_MAIN = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
BK_MAIN = ["no_bk", "current_bk", "wide_bk"]


def parse_csv(values: str | list[str]) -> list[str]:
    parts: list[str] = []
    if isinstance(values, list):
        for value in values:
            parts.extend(str(value).split(","))
    else:
        parts.extend(str(values).split(","))
    return [p.strip() for p in parts if p.strip()]


def parse_float_csv(values: str | list[str]) -> list[float]:
    return [float(v) for v in parse_csv(values)]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run expanded segment-local fixed-site confirmation experiment.")
    p.add_argument("--preset", choices=["smoke", "expanded"], default="expanded")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--legacy-dataset", type=Path, default=Path("outputs/datasets/original_vs_current_fixed_reference_dataset.csv"))
    p.add_argument("--legacy-replay-comparison", type=Path, default=Path("outputs/metrics/fixed_c_legacy_replay_comparison.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/m2_segment_local_expanded_sample_dataset.csv"))
    p.add_argument("--row-summary-output", type=Path, default=Path("outputs/metrics/m2_segment_local_expanded_row_summary.csv"))
    p.add_argument("--pair-summary-output", type=Path, default=Path("outputs/metrics/m2_segment_local_expanded_pair_summary.csv"))
    p.add_argument("--real-vs-synthetic-output", type=Path, default=Path("outputs/metrics/m2_segment_local_real_vs_synthetic_summary.csv"))
    p.add_argument("--risk-boundary-output", type=Path, default=Path("outputs/metrics/m2_segment_local_expanded_risk_boundary_summary.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/m2_segment_local_expanded_sample_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/m2_segment_local_expanded_sample"))
    p.add_argument("--r-cell-km", nargs="+", default=None)
    p.add_argument("--distance-to-center-km", nargs="+", default=None)
    p.add_argument("--phi-deg", nargs="+", default=None)
    p.add_argument("--bk-modes", nargs="+", default=None)
    p.add_argument("--attack-models", nargs="+", default="M0,M2_block")
    p.add_argument("--real-sample-groups", nargs="+", default="ordinary_similar,boundary_case")
    p.add_argument("--max-targets", type=int, default=None)
    p.add_argument("--max-attackers-per-group", type=int, default=None)
    p.add_argument("--max-heatmap-segments", type=int, default=None)
    p.add_argument("--t-service-s", type=float, default=60.0)
    p.add_argument("--alpha", type=float, default=1.0)
    p.add_argument("--num-benign-sims", type=int, default=30)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260706)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def setup_args(args: argparse.Namespace) -> None:
    smoke = args.preset == "smoke"
    args.r_cell_km = parse_float_csv(args.r_cell_km) if args.r_cell_km else (R_CELLS_SMOKE if smoke else R_CELLS_MAIN)
    args.distance_to_center_km = parse_float_csv(args.distance_to_center_km) if args.distance_to_center_km else (DISTANCES_SMOKE if smoke else DISTANCES_MAIN)
    args.phi_deg = parse_float_csv(args.phi_deg) if args.phi_deg else PHIS_MAIN
    args.bk_modes = parse_csv(args.bk_modes) if args.bk_modes else (["current_bk", "wide_bk"] if smoke else BK_MAIN)
    args.attack_models = parse_csv(args.attack_models)
    args.real_sample_groups = parse_csv(args.real_sample_groups)
    if args.max_targets is None:
        args.max_targets = 2 if smoke else 5
    if args.max_attackers_per_group is None:
        args.max_attackers_per_group = 2 if smoke else 5
    if args.max_heatmap_segments is None:
        args.max_heatmap_segments = 2 if smoke else 3
    unsupported = set(args.attack_models) - {"M0", "M2_block"}
    if unsupported:
        fail(f"unsupported attack model for this confirmation run: {', '.join(sorted(unsupported))}")
    unsupported_bk = set(args.bk_modes) - {"no_bk", "current_bk", "wide_bk"}
    if unsupported_bk:
        fail(f"unsupported bk modes: {', '.join(sorted(unsupported_bk))}")


def check_outputs(args: argparse.Namespace) -> None:
    outputs = [
        args.dataset_output,
        args.row_summary_output,
        args.pair_summary_output,
        args.real_vs_synthetic_output,
        args.risk_boundary_output,
        args.report_output,
        args.figures_dir / "accept_rate_vs_distance_real_tle.png",
        args.figures_dir / "accept_rate_vs_distance_legacy_synthetic.png",
        args.figures_dir / "real_vs_synthetic_comparison.png",
        args.figures_dir / "bk_mode_distance_comparison.png",
    ]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not args.overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def load_base_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, list[float]]]:
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        max_targets=args.max_targets,
    )
    return seg.load_inputs(loader_args)


def select_real_samples(
    selection: pd.DataFrame,
    library: pd.DataFrame,
    tle: dict[str, dict[str, Any]],
    groups: list[str],
    max_attackers_per_group: int,
    hard_cases: Path,
) -> pd.DataFrame:
    real = seg.select_attack_samples(selection, library, tle, groups, max_attackers_per_group, hard_cases).copy()
    real["sample_source"] = "real_tle_candidate"
    real["attacker_kind"] = "real_tle"
    real["legacy_case_id"] = ""
    real["legacy_decision"] = ""
    real["legacy_R_km"] = np.nan
    real["attack_type"] = "real_tle_candidate"
    real["attack_param_name"] = "candidate_norad_id"
    real["attack_param_value"] = real["attack_sat_id"].astype(str)
    return real


def load_legacy_synthetic_samples(args: argparse.Namespace, selection: pd.DataFrame) -> pd.DataFrame:
    if not args.legacy_dataset.exists():
        fail(f"missing legacy dataset: {args.legacy_dataset}")
    legacy = pd.read_csv(args.legacy_dataset)
    required = [
        "target_id",
        "target_name",
        "sample_group",
        "orbit_relation_type",
        "orbit_relation_param_name",
        "orbit_relation_param_value",
        "style_type",
        "compensation_mode",
        "bk_mode",
        "window_mode",
        "strategy_type",
        "requested_error_km",
        "final_decision",
    ]
    seg.require_columns(legacy, required, "legacy dataset")
    f = legacy[
        legacy["style_type"].eq("original_style")
        & legacy["compensation_mode"].eq("fixed_reference_compensation")
        & legacy["bk_mode"].eq("current_bk")
        & legacy["window_mode"].eq("full_pass")
        & legacy["strategy_type"].eq("original_strong_prior")
        & legacy["sample_group"].isin(["original_like", "hard_case_weighted"])
    ].copy()
    allowed_targets = set(selection["target_norad_id"].astype(str))
    f["target_id"] = f["target_id"].astype(str)
    f = f[f["target_id"].isin(allowed_targets)]
    replay = pd.read_csv(args.legacy_replay_comparison) if args.legacy_replay_comparison.exists() else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    keys = ["target_id", "target_name", "sample_group", "orbit_relation_type", "orbit_relation_param_name", "orbit_relation_param_value"]
    for key, g in f.groupby(keys, dropna=False, sort=False):
        target_id, target_name, sample_group, attack_type, param_name, param_value = key
        accept_g = g[g["final_decision"].eq("ACCEPT")]
        preferred = accept_g if not accept_g.empty else g
        legacy_case = str(preferred.iloc[0]["case_id"])
        legacy_decision = "ACCEPT" if not accept_g.empty else str(preferred.iloc[0]["final_decision"])
        legacy_r = float(preferred.iloc[0]["requested_error_km"])
        if not replay.empty and "legacy_decision" in replay.columns:
            rg = replay[
                replay["target_norad_id"].astype(str).eq(str(target_id))
                & replay["sample_group"].eq(sample_group)
                & replay["legacy_decision"].eq("ACCEPT")
                & replay.get("replay_decision", pd.Series(index=replay.index, dtype=str)).eq("ACCEPT")
            ]
            if not rg.empty:
                legacy_case = str(rg.iloc[0]["legacy_case_id"])
                legacy_decision = "ACCEPT_NEAR_REPLAY_ACCEPT"
                legacy_r = float(rg.iloc[0].get("R_label_km", legacy_r))
        mapped_group = "ordinary_similar" if sample_group == "original_like" else "boundary_case"
        attack_name = f"synthetic_{attack_type}_{float(param_value):g}"
        rows.append(
            {
                "target_sat_id": str(target_id),
                "target_name": str(target_name),
                "attack_sat_id": attack_name,
                "attack_name": attack_name,
                "sample_group": mapped_group,
                "legacy_sample_group": sample_group,
                "sample_index": len(rows) + 1,
                "sample_source": "legacy_synthetic",
                "attacker_kind": "synthetic",
                "legacy_case_id": legacy_case,
                "legacy_decision": legacy_decision,
                "legacy_R_km": legacy_r,
                "attack_type": str(attack_type),
                "attack_param_name": str(param_name),
                "attack_param_value": float(param_value),
            }
        )
    if not rows:
        fail("no legacy synthetic samples selected")
    return pd.DataFrame(rows)


def selected_segment_indices(track: seg.CenterTrack, attack_model: str, max_segments: int, mid: int) -> list[tuple[int, int, int, int]]:
    if attack_model == "M2_block":
        starts = seg.representative_indices(track.segment_starts, max_segments)
        out = []
        for start in starts:
            seg_idx = int(track.segment_index[start])
            out.append((seg_idx, int(start), int(track.segment_starts[seg_idx]), int(track.segment_ends[seg_idx])))
        return out
    block_seg, block_starts, block_ends = seg.build_block_indices(np.arange(len(track.lat_deg), dtype=float), 60.0)
    starts = seg.representative_indices(block_starts, max_segments)
    out = []
    for start in starts:
        idx = int(block_seg[start])
        out.append((idx, int(mid), int(block_starts[idx]), int(block_ends[idx])))
    return out


def attack_geo(
    sample: dict[str, Any],
    sat_a: Any,
    sat_b: Any | None,
    lat: float,
    lon: float,
    alt_m: float,
    times: list[datetime],
    ts: Any,
    freq_hz: float,
    step_s: float,
) -> np.ndarray:
    if sample["sample_source"] == "legacy_synthetic":
        spec = ext.synthetic_spec(str(sample["attack_type"]), float(sample["attack_param_value"]))
        return ext.generate_synthetic_geo(spec, sat_a, lat, lon, alt_m, times, ts, freq_hz)
    if sat_b is None:
        fail("real TLE sample missing attacker satellite")
    curve, _elev = seg.geo_curve_fixed(sat_b, lat, lon, alt_m, times, ts, freq_hz, step_s)
    return curve


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return np.nan, np.nan
    p = successes / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    half = z * math.sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total))) / denom
    return max(0.0, center - half), min(1.0, center + half)


def build_row_summary(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    work["distance_to_center_km"] = work["requested_distance_to_center_km"].astype(float)
    group_cols = ["sample_source", "sample_group", "attack_model", "distance_to_center_km", "R_cell_km", "bk_mode"]
    rows = []
    for key, g in work.groupby(group_cols, dropna=False):
        n = len(g)
        a = int(g["accept_flag"].sum())
        d = int(g["defer_flag"].sum())
        r = int(g["reject_flag"].sum())
        lo, hi = wilson_interval(a, n)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "total_rows": n,
                "accept_rows": a,
                "defer_rows": d,
                "reject_rows": r,
                "row_accept_rate": a / n if n else np.nan,
                "row_accept_rate_wilson_low": lo,
                "row_accept_rate_wilson_high": hi,
                "mean_normalized_score": float(g["normalized_score"].mean()),
                "median_normalized_score": float(g["normalized_score"].median()),
            }
        )
    return pd.DataFrame(rows)


def build_pair_summary(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.copy()
    df["distance_to_center_km"] = df["requested_distance_to_center_km"].astype(float)
    pair_cols = ["target_sat_id", "attack_sat_id", "sample_source", "sample_group", "attack_model", "distance_to_center_km", "bk_mode"]
    pair_rows = []
    for key, g in df.groupby(pair_cols, dropna=False):
        n = len(g)
        a = int(g["accept_flag"].sum())
        pair_rows.append(
            {
                **dict(zip(pair_cols, key)),
                "pair_total_rows": n,
                "pair_accept_rows": a,
                "pair_accept_fraction": a / n if n else np.nan,
                "pair_any_accept": bool(a > 0),
            }
        )
    pair_detail = pd.DataFrame(pair_rows)
    group_cols = ["sample_source", "sample_group", "attack_model", "distance_to_center_km", "bk_mode"]
    rows = []
    for key, g in pair_detail.groupby(group_cols, dropna=False):
        n = len(g)
        any_count = int(g["pair_any_accept"].sum())
        lo, hi = wilson_interval(any_count, n)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "pair_count": n,
                "mean_pair_accept_fraction": float(g["pair_accept_fraction"].mean()),
                "median_pair_accept_fraction": float(g["pair_accept_fraction"].median()),
                "pairs_with_any_accept": any_count,
                "pairs_with_any_accept_rate": any_count / n if n else np.nan,
                "pairs_with_any_accept_rate_wilson_low": lo,
                "pairs_with_any_accept_rate_wilson_high": hi,
            }
        )
    return pair_detail, pd.DataFrame(rows)


def build_real_vs_synthetic(pair_summary: pd.DataFrame) -> pd.DataFrame:
    cols = ["sample_source", "sample_group", "distance_to_center_km", "bk_mode"]
    rows = []
    for key, g in pair_summary.groupby(cols, dropna=False):
        rows.append(
            {
                **dict(zip(cols, key)),
                "pair_count": int(g["pair_count"].sum()),
                "mean_pair_accept_fraction": float(np.average(g["mean_pair_accept_fraction"], weights=g["pair_count"])),
                "pairs_with_any_accept_rate": float(np.average(g["pairs_with_any_accept_rate"], weights=g["pair_count"])),
                "wilson_upper_max": float(g["pairs_with_any_accept_rate_wilson_high"].max()),
            }
        )
    return pd.DataFrame(rows)


def build_risk_boundary(pair_summary: pd.DataFrame) -> pd.DataFrame:
    cols = ["sample_source", "sample_group", "attack_model", "bk_mode"]
    rows = []
    for key, g in pair_summary.groupby(cols, dropna=False):
        g = g.sort_values("distance_to_center_km")
        with_accept = g[g["pairs_with_any_accept"] > 0]
        zero = g[g["pairs_with_any_accept"] == 0]
        rows.append(
            {
                **dict(zip(cols, key)),
                "max_distance_km_with_accept": float(with_accept["distance_to_center_km"].max()) if not with_accept.empty else np.nan,
                "first_zero_accept_distance_km": float(zero["distance_to_center_km"].min()) if not zero.empty else np.nan,
                "peak_pairs_with_any_accept_rate": float(g["pairs_with_any_accept_rate"].max()),
                "distance_at_peak": float(g.loc[g["pairs_with_any_accept_rate"].idxmax(), "distance_to_center_km"]) if not g.empty else np.nan,
                "note": "observed risk transition; not a strict safety threshold",
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(pair_summary: pd.DataFrame, real_vs_syn: pd.DataFrame, outdir: Path) -> list[Path]:
    paths: list[Path] = []
    for source, name in [("real_tle_candidate", "accept_rate_vs_distance_real_tle.png"), ("legacy_synthetic", "accept_rate_vs_distance_legacy_synthetic.png")]:
        d = pair_summary[(pair_summary["sample_source"].eq(source)) & (pair_summary["attack_model"].eq("M2_block"))]
        fig, ax = plt.subplots(figsize=(9, 5))
        for (group, bk), g in d.groupby(["sample_group", "bk_mode"]):
            g = g.sort_values("distance_to_center_km")
            ax.plot(g["distance_to_center_km"], g["pairs_with_any_accept_rate"], marker="o", label=f"{group}:{bk}")
        ax.set_xlabel("distance_to_center_km")
        ax.set_ylabel("非目标样本误接受率")
        ax.set_title(f"{source}: M2_block segment-local")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=7)
        p = outdir / name
        savefig(fig, p)
        paths.append(p)

    d = real_vs_syn[real_vs_syn["bk_mode"].isin(["current_bk", "wide_bk"])].copy()
    fig, ax = plt.subplots(figsize=(9, 5))
    for (source, group, bk), g in d.groupby(["sample_source", "sample_group", "bk_mode"]):
        g = g.sort_values("distance_to_center_km")
        ax.plot(g["distance_to_center_km"], g["pairs_with_any_accept_rate"], marker="o", label=f"{source}:{group}:{bk}")
    ax.set_xlabel("distance_to_center_km")
    ax.set_ylabel("非目标样本误接受率")
    ax.set_title("real TLE vs legacy synthetic")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=6)
    p = outdir / "real_vs_synthetic_comparison.png"
    savefig(fig, p)
    paths.append(p)

    d = pair_summary[pair_summary["attack_model"].eq("M2_block")]
    fig, ax = plt.subplots(figsize=(9, 5))
    for bk, g in d.groupby("bk_mode"):
        g = g.groupby("distance_to_center_km", as_index=False)["pairs_with_any_accept_rate"].mean().sort_values("distance_to_center_km")
        ax.plot(g["distance_to_center_km"], g["pairs_with_any_accept_rate"], marker="o", label=bk)
    ax.set_xlabel("distance_to_center_km")
    ax.set_ylabel("非目标样本误接受率")
    ax.set_title("b/k mode distance comparison")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "bk_mode_distance_comparison.png"
    savefig(fig, p)
    paths.append(p)
    return paths


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[Path]]:
    setup_args(args)
    check_outputs(args)
    selection, library, orbit_cfg, tle, ranges = load_base_inputs(args)
    ts = load.timescale()
    freq_hz = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    real = select_real_samples(selection, library, tle, args.real_sample_groups, int(args.max_attackers_per_group), args.hard_cases)
    legacy = load_legacy_synthetic_samples(args, selection)
    samples = pd.concat([real, legacy], ignore_index=True, sort=False)
    rng = np.random.default_rng(args.seed)
    rows: list[dict[str, Any]] = []
    geo_cache: dict[tuple[Any, ...], np.ndarray] = {}
    cal_cache: dict[tuple[str, int, int], dict[str, dict[str, float]]] = {}
    legacy_source_rows = pd.read_csv(args.legacy_dataset) if args.legacy_dataset.exists() else pd.DataFrame()

    for sidx, sample in enumerate(samples.to_dict("records")):
        target_id = str(sample["target_sat_id"])
        sat_a = tle[target_id]["sat"]
        sat_b = tle[str(sample["attack_sat_id"])]["sat"] if sample["sample_source"] == "real_tle_candidate" else None
        target_geo = seg.base.target_geo_from_library(library, target_id)
        times = [seg.base.parse_utc(v) for v in target_geo["t_abs_utc"].astype(str)]
        t_rel = target_geo["t_rel_s"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        pass_id = f"{target_id}_{str(target_geo['t_abs_utc'].iloc[0]).replace(':', '').replace('-', '')}"
        g_lat, g_lon, g_alt = seg.compute_subpoint_series(sat_a, times, ts)
        mid = len(times) // 2
        noise, b_env, k_env, sigma_hz, t0 = seg.sample_residual_terms(t_rel, args.residual_mode, ranges, rng)
        if sample["sample_source"] == "legacy_synthetic" and pd.notna(sample.get("legacy_case_id", np.nan)):
            matched = legacy_source_rows[legacy_source_rows["case_id"].astype(str).eq(str(sample["legacy_case_id"]))]
            if not matched.empty:
                b_env = float(matched.iloc[0]["b_injected"])
                k_env = float(matched.iloc[0]["k_injected"])
                sigma_hz = float(matched.iloc[0]["noise_std"])
                seed = int(matched.iloc[0]["noise_seed"])
                noise = np.random.default_rng(seed).normal(0.0, sigma_hz, len(t_rel))
        for r_cell in args.r_cell_km:
            valid_distances = [d for d in args.distance_to_center_km if d <= r_cell + 1e-9]
            for attack_model in args.attack_models:
                track = seg.center_track(
                    attack_model,
                    g_lat,
                    g_lon,
                    g_alt,
                    t_rel,
                    float(r_cell),
                    float(args.alpha),
                    float(args.t_service_s),
                    0.0,
                )
                block_track = seg.center_track("M2_block", g_lat, g_lon, g_alt, t_rel, float(r_cell), float(args.alpha), float(args.t_service_s), 0.0)
                eval_segments = selected_segment_indices(block_track if attack_model == "M0" else track, attack_model, int(args.max_heatmap_segments), mid)
                segment_count = len(track.segment_starts)
                durations = np.asarray([(track.segment_ends[i] - track.segment_starts[i] + 1) * step_s for i in range(segment_count)], dtype=float)
                mean_seg = float(np.mean(durations)) if len(durations) else float(np.max(t_rel) - np.min(t_rel))
                median_seg = float(np.median(durations)) if len(durations) else mean_seg
                min_seg = float(np.min(durations)) if len(durations) else mean_seg
                max_seg = float(np.max(durations)) if len(durations) else mean_seg
                for seg_idx, center_i, seg_start_i, seg_end_i in eval_segments:
                    eval_slice = slice(seg_start_i, seg_end_i + 1)
                    eval_times = times[seg_start_i : seg_end_i + 1]
                    eval_t_rel = t_rel[eval_slice]
                    eval_noise = noise[eval_slice]
                    if attack_model == "M0":
                        c_lat = float(g_lat[mid])
                        c_lon = float(g_lon[mid])
                    else:
                        c_lat = float(track.lat_deg[center_i])
                        c_lon = float(track.lon_deg[center_i])
                    cal_key = (target_id, seg_start_i, seg_end_i)
                    if cal_key not in cal_cache:
                        cal_cache[cal_key] = seg.calibration_for_trel(eval_t_rel, ranges, args.seed + int(target_id) + int(seg_idx), int(args.num_benign_sims))
                    for distance_value in valid_distances:
                        rho = float(distance_value) / float(r_cell) if r_cell > 0 else np.nan
                        for phi in args.phi_deg:
                            s_lat, s_lon = seg.destination(c_lat, c_lon, float(distance_value), float(phi))
                            a_center_base = (
                                target_id,
                                round(c_lat, 7),
                                round(c_lon, 7),
                                seg_start_i,
                                seg_end_i,
                            )
                            a_site_base = (
                                target_id,
                                round(s_lat, 7),
                                round(s_lon, 7),
                                seg_start_i,
                                seg_end_i,
                            )
                            b_center_base = (
                                target_id,
                                sample["sample_source"],
                                sample["attack_sat_id"],
                                sample.get("attack_type", ""),
                                sample.get("attack_param_value", ""),
                                round(c_lat, 7),
                                round(c_lon, 7),
                                seg_start_i,
                                seg_end_i,
                            )
                            b_site_base = (
                                target_id,
                                sample["sample_source"],
                                sample["attack_sat_id"],
                                sample.get("attack_type", ""),
                                sample.get("attack_param_value", ""),
                                round(c_lat, 7),
                                round(c_lon, 7),
                                round(s_lat, 7),
                                round(s_lon, 7),
                                seg_start_i,
                                seg_end_i,
                            )
                            a_c_key = ("A_C", a_center_base)
                            a_s_key = ("A_S", a_site_base)
                            b_c_key = ("B_C", b_center_base)
                            b_s_key = ("B_S", b_site_base)
                            if a_c_key not in geo_cache:
                                geo_cache[a_c_key] = seg.geo_curve_fixed(sat_a, c_lat, c_lon, 0.0, eval_times, ts, freq_hz, step_s)[0]
                            if a_s_key not in geo_cache:
                                geo_cache[a_s_key] = seg.geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, eval_times, ts, freq_hz, step_s)[0]
                            if b_c_key not in geo_cache:
                                geo_cache[b_c_key] = attack_geo(sample, sat_a, sat_b, c_lat, c_lon, 0.0, eval_times, ts, freq_hz, step_s)
                            if b_s_key not in geo_cache:
                                geo_cache[b_s_key] = attack_geo(sample, sat_a, sat_b, s_lat, s_lon, 0.0, eval_times, ts, freq_hz, step_s)
                            f_a_c = geo_cache[a_c_key]
                            f_a_s = geo_cache[a_s_key]
                            f_b_c = geo_cache[b_c_key]
                            f_b_s = geo_cache[b_s_key]
                            u = f_a_c - f_b_c
                            y_atk = f_b_s + u + b_env + k_env * (eval_t_rel - t0) + eval_noise
                            dist_series = seg.distance_km(np.full(len(eval_t_rel), c_lat), np.full(len(eval_t_rel), c_lon), s_lat, s_lon)
                            coverage = dist_series <= float(r_cell) + 1e-9
                            r_geo = f_b_s + f_a_c - f_b_c - f_a_s
                            along_km, cross_km = seg.signed_offsets_km(rho, phi, r_cell)
                            for bk_mode in args.bk_modes:
                                dec = seg.evaluate_single_station(
                                    y_obs=y_atk,
                                    f_geo_a=f_a_s,
                                    t_rel=eval_t_rel,
                                    coverage_mask=coverage,
                                    cal=cal_cache[cal_key],
                                    bk_mode=bk_mode,
                                    verification_strategy="single-window",
                                )
                                case_id = "_".join(
                                    [
                                        str(sample["sample_source"]),
                                        attack_model,
                                        str(target_id),
                                        str(sample["attack_sat_id"]),
                                        str(sample["sample_group"]),
                                        f"R{r_cell:g}",
                                        f"d{distance_value:g}",
                                        f"phi{phi:g}",
                                        f"seg{seg_idx}",
                                        bk_mode,
                                    ]
                                )
                                rows.append(
                                    {
                                        "case_id": case_id,
                                        "sample_source": sample["sample_source"],
                                        "sample_group": sample["sample_group"],
                                        "legacy_sample_group": sample.get("legacy_sample_group", ""),
                                        "legacy_case_id": sample.get("legacy_case_id", ""),
                                        "legacy_decision": sample.get("legacy_decision", ""),
                                        "legacy_R_km": sample.get("legacy_R_km", np.nan),
                                        "attacker_kind": sample["attacker_kind"],
                                        "attack_type": sample.get("attack_type", ""),
                                        "attack_param_name": sample.get("attack_param_name", ""),
                                        "attack_param_value": sample.get("attack_param_value", ""),
                                        "attack_model": attack_model,
                                        "segment_rule": "fixed" if attack_model == "M0" else "dwell_block",
                                        "receiver_mode": "heatmap_mode",
                                        "evaluation_scope": "segment_local",
                                        "doppler_reference_mode": "fixed_site_segment_center",
                                        "verification_strategy": "single-window",
                                        "T_service_s": float(args.t_service_s),
                                        "target_sat_id": target_id,
                                        "target_name": sample["target_name"],
                                        "attack_sat_id": sample["attack_sat_id"],
                                        "attack_name": sample["attack_name"],
                                        "pair_id": f"{sample['sample_source']}:{target_id}:{sample['attack_sat_id']}",
                                        "pass_id": pass_id,
                                        "segment_index": int(seg_idx),
                                        "window_id": f"segment_{seg_idx}",
                                        "R_cell_km": float(r_cell),
                                        "alpha": float(args.alpha),
                                        "distance_to_center_km": float(distance_value),
                                        "actual_distance_to_center_km": float(np.mean(dist_series)),
                                        "requested_distance_to_center_km": float(distance_value),
                                        "distance_error_km": float(abs(np.mean(dist_series) - float(distance_value))),
                                        "rho": float(rho),
                                        "phi_deg": float(phi),
                                        "C_lat": c_lat,
                                        "C_lon": c_lon,
                                        "S_lat": float(s_lat),
                                        "S_lon": float(s_lon),
                                        "bk_mode": bk_mode,
                                        "b_env": float(b_env),
                                        "k_env": float(k_env),
                                        "sigma_hz": float(sigma_hz),
                                        "evaluation_start_s": float(eval_t_rel[0]),
                                        "evaluation_end_s": float(eval_t_rel[-1]),
                                        "segment_start_s": float(t_rel[seg_start_i]),
                                        "segment_end_s": float(t_rel[seg_end_i]),
                                        "point_count": int(len(eval_t_rel)),
                                        "coverage_valid": bool(np.all(coverage)),
                                        "coverage_valid_fraction": float(np.mean(coverage)),
                                        "coverage_gate_pass": bool(dec.coverage_gate_pass),
                                        "mean_abs_r_geo_hz": float(np.mean(np.abs(r_geo))),
                                        "rmse_r_geo_hz": float(np.sqrt(np.mean(r_geo**2))),
                                        "max_abs_r_geo_hz": float(np.max(np.abs(r_geo))),
                                        "b_hat_hz": float(dec.b_hat_hz),
                                        "k_hat_hz_per_s": float(dec.k_hat_hz_per_s),
                                        "abs_b_hat_hz": abs(float(dec.b_hat_hz)),
                                        "abs_k_hat_hz_per_s": abs(float(dec.k_hat_hz_per_s)),
                                        "normalized_score": float(dec.normalized_score),
                                        "residual_rmse_hz": float(dec.residual_rmse_hz),
                                        "raw_delta_rmse_hz": float(dec.raw_delta_rmse_hz),
                                        "score_gate_pass": bool(dec.score_gate_pass),
                                        "b_gate_pass": bool(dec.b_gate_pass),
                                        "k_gate_pass": bool(dec.k_gate_pass),
                                        "quality_gate_pass": True,
                                        "decision": dec.decision,
                                        "decision_reason": dec.reason,
                                        "accept_flag": bool(dec.decision == "ACCEPT"),
                                        "defer_flag": bool(dec.decision == "DEFER"),
                                        "reject_flag": bool(dec.decision == "REJECT"),
                                        "segment_count": int(segment_count),
                                        "segment_duration_s": float(eval_t_rel[-1] - eval_t_rel[0] + step_s),
                                        "mean_segment_duration_s": mean_seg,
                                        "median_segment_duration_s": median_seg,
                                        "min_segment_duration_s": min_seg,
                                        "max_segment_duration_s": max_seg,
                                        "along_track_offset_km": float(along_km),
                                        "cross_track_offset_km": float(cross_km),
                                        "random_seed": int(args.seed),
                                        "sample_index_global": int(sidx),
                                    }
                                )
    df = pd.DataFrame(rows)
    if df.empty:
        fail("no dataset rows generated")
    row_summary = build_row_summary(df)
    pair_detail, pair_summary = build_pair_summary(df)
    real_vs_syn = build_real_vs_synthetic(pair_summary)
    risk = build_risk_boundary(pair_summary)
    for path in [args.dataset_output, args.row_summary_output, args.pair_summary_output, args.real_vs_synthetic_output, args.risk_boundary_output, args.report_output]:
        path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.dataset_output, index=False)
    row_summary.to_csv(args.row_summary_output, index=False)
    pair_summary.to_csv(args.pair_summary_output, index=False)
    real_vs_syn.to_csv(args.real_vs_synthetic_output, index=False)
    risk.to_csv(args.risk_boundary_output, index=False)
    pair_detail.to_csv(args.pair_summary_output.with_name(args.pair_summary_output.stem + "_detail.csv"), index=False)
    figures = make_figures(pair_summary, real_vs_syn, args.figures_dir)
    write_report(args, df, row_summary, pair_summary, real_vs_syn, risk, figures)
    append_log(args, df, row_summary, pair_summary, real_vs_syn, risk, figures)
    return df, row_summary, pair_summary, real_vs_syn, risk, figures


def trend_table(pair_summary: pd.DataFrame, source: str, group: str, bk: str = "current_bk", model: str = "M2_block") -> pd.DataFrame:
    return pair_summary[
        pair_summary["sample_source"].eq(source)
        & pair_summary["sample_group"].eq(group)
        & pair_summary["bk_mode"].eq(bk)
        & pair_summary["attack_model"].eq(model)
    ].sort_values("distance_to_center_km")


def write_report(
    args: argparse.Namespace,
    df: pd.DataFrame,
    row_summary: pd.DataFrame,
    pair_summary: pd.DataFrame,
    real_vs_syn: pd.DataFrame,
    risk: pd.DataFrame,
    figures: list[Path],
) -> None:
    audit = {
        "evaluation_scope_ok": bool(df["evaluation_scope"].eq("segment_local").all()),
        "doppler_reference_ok": bool(df["doppler_reference_mode"].eq("fixed_site_segment_center").all()),
        "coverage_ok": bool(df["coverage_valid_fraction"].ge(1.0 - 1e-12).all() and df["coverage_gate_pass"].all()),
        "distance_error_max_km": float(df["distance_error_km"].max()),
        "rho0_rmse_r_geo_max_hz": float(df[df["requested_distance_to_center_km"].eq(0.0)]["rmse_r_geo_hz"].max()),
    }
    actual_targets = df.groupby("sample_source")["target_sat_id"].nunique().to_dict()
    actual_pairs = df.groupby(["sample_source", "sample_group"])["pair_id"].nunique().to_dict()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Expanded segment-local fixed-site confirmation

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

本文仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。

## 1. 实验目的

前一轮 fine sweep 的真实 TLE 样本规模较小；新旧 fixed-C 对账又显示 legacy synthetic hard cases 的旧高风险结果基本可 near replay。因此本轮把真实 TLE candidate 与 legacy synthetic hard cases 放入同一套 `segment_local + fixed_site_segment_center` 口径中，比较距离服务中心的风险曲线。

## 2. 实际参数

- preset: `{args.preset}`
- attack_model: `{args.attack_models}`
- receiver_mode: `heatmap_mode`
- evaluation_scope: `segment_local`
- doppler_reference_mode: `fixed_site_segment_center`
- verification_strategy: `single-window`
- T_service_s: `{args.t_service_s}`
- R_cell_km: `{args.r_cell_km}`
- distance_to_center_km: `{args.distance_to_center_km}`
- phi_deg: `{args.phi_deg}`
- bk_mode: `{args.bk_modes}`
- real max_targets: `{args.max_targets}`
- real max_attackers_per_group: `{args.max_attackers_per_group}`
- max_heatmap_segments: `{args.max_heatmap_segments}`

## 3. 样本规模

- dataset rows: `{len(df)}`
- row summary rows: `{len(row_summary)}`
- pair summary rows: `{len(pair_summary)}`
- actual targets by source: `{actual_targets}`
- actual pair counts by source/group: `{actual_pairs}`

## 4. 正确性审计

{pd.DataFrame([audit]).to_markdown(index=False)}

## 5. current_bk / M2_block 距离趋势

### real TLE ordinary_similar

{trend_table(pair_summary, 'real_tle_candidate', 'ordinary_similar').to_markdown(index=False)}

### real TLE boundary_case

{trend_table(pair_summary, 'real_tle_candidate', 'boundary_case').to_markdown(index=False)}

### legacy original_like

{trend_table(pair_summary, 'legacy_synthetic', 'ordinary_similar').to_markdown(index=False)}

### legacy hard_case_weighted

{trend_table(pair_summary, 'legacy_synthetic', 'boundary_case').to_markdown(index=False)}

## 6. 风险过渡摘要

{risk.to_markdown(index=False)}

## 7. 图像

{figs}

## 8. 表述边界

当前非目标样本误接受率是受控仿真中的比例，不是真实世界攻击成功率。`R_cell`、`T_service_s` 和距离扫描均为敏感性参数，不声称等同真实 Starlink cell radius、handover period 或 beam boundary。
"""
    args.report_output.write_text(text, encoding="utf-8")


def append_log(
    args: argparse.Namespace,
    df: pd.DataFrame,
    row_summary: pd.DataFrame,
    pair_summary: pd.DataFrame,
    real_vs_syn: pd.DataFrame,
    risk: pd.DataFrame,
    figures: list[Path],
) -> None:
    path = Path("logs/work_log.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    audit_ok = bool(
        df["evaluation_scope"].eq("segment_local").all()
        and df["doppler_reference_mode"].eq("fixed_site_segment_center").all()
        and df["coverage_valid_fraction"].ge(1.0 - 1e-12).all()
        and df[df["requested_distance_to_center_km"].eq(0.0)]["rmse_r_geo_hz"].max() < 1e-3
    )
    text = f"""
## {now} - segment-local expanded sample confirmation

### A. 本轮目标

扩大真实 TLE target / attacker 样本，并把 legacy synthetic hard cases 放入当前统一的 segment-local + fixed-site 口径，复核距离服务中心的非目标样本误接受风险曲线。

### B. 实际操作

- 新增 `scripts/run_segment_local_expanded_sample_confirmation.py`。
- 保持 `receiver_mode=heatmap_mode`、`evaluation_scope=segment_local`、`doppler_reference_mode=fixed_site_segment_center`、`verification_strategy=single-window`。
- 未新增攻击模型，未修改 sequence_mode，未恢复 full-pass heatmap。
- 输出 row-level 和 target-attacker pair-level summary，并加入 Wilson 95% CI。

### C. 新增/修改文件

- `{args.dataset_output.as_posix()}`
- `{args.row_summary_output.as_posix()}`
- `{args.pair_summary_output.as_posix()}`
- `{args.real_vs_synthetic_output.as_posix()}`
- `{args.risk_boundary_output.as_posix()}`
- `{args.report_output.as_posix()}`
- `{args.figures_dir.as_posix()}/`

### D. 运行命令

见本轮终端命令记录；preset=`{args.preset}`，max_targets=`{args.max_targets}`，max_attackers_per_group=`{args.max_attackers_per_group}`。

### E. 结果摘要

- dataset rows: `{len(df)}`
- row summary rows: `{len(row_summary)}`
- pair summary rows: `{len(pair_summary)}`
- figures: `{len(figures)}`
- correctness audit passed: `{audit_ok}`

### F. 问题与下一步

- 本轮仍是 controlled segmented service-center compensation simulation，不是真实 Starlink 调度复现。
- legacy synthetic 使用 near-replay 可复现 spec；旧数据缺逐点噪声向量，因此不标记为 exact replay。
- 下一步应基于 pair-level 结果决定是否形成阶段结论或继续统一 full-pass / segment-local 口径。
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    df, row_summary, pair_summary, real_vs_syn, risk, figures = run(args)
    print(f"wrote {args.dataset_output} rows={len(df)}")
    print(f"wrote {args.row_summary_output} rows={len(row_summary)}")
    print(f"wrote {args.pair_summary_output} rows={len(pair_summary)}")
    print(f"wrote {args.real_vs_synthetic_output} rows={len(real_vs_syn)}")
    print(f"wrote {args.risk_boundary_output} rows={len(risk)}")
    print(f"wrote {args.report_output}")
    print(f"wrote figures={len(figures)} to {args.figures_dir}")


if __name__ == "__main__":
    main()
