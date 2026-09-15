#!/usr/bin/env python
"""Multi-service-area single-station repeatability confirmation.

Each service area is evaluated as an independent segment-local fixed-C
experiment.  This is a controlled segmented service-center compensation
simulation, not a Starlink scheduling, handover, or multi-station experiment.
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

MAIN_DISTANCES = [0.0, 2.5, 5.0, 10.0, 50.0, 100.0, 200.0, 500.0]
SMOKE_DISTANCES = [0.0, 5.0, 50.0, 200.0]
MAIN_PHIS = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
SMOKE_PHIS = [0.0, 90.0, 180.0, 270.0]


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
    p = argparse.ArgumentParser(description="Run multi-service-area single-station repeatability confirmation.")
    p.add_argument("--preset", choices=["smoke", "main"], default="main")
    p.add_argument("--expanded-dataset", type=Path, default=Path("outputs/datasets/m2_segment_local_expanded_sample_dataset.csv"))
    p.add_argument("--legacy-dataset", type=Path, default=Path("outputs/datasets/original_vs_current_fixed_reference_dataset.csv"))
    p.add_argument("--legacy-case-list", type=Path, default=Path("outputs/metrics/fixed_c_legacy_replay_case_list.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/multi_service_area_single_station_dataset.csv"))
    p.add_argument("--row-summary-output", type=Path, default=Path("outputs/metrics/multi_service_area_single_station_row_summary.csv"))
    p.add_argument("--repeatability-output", type=Path, default=Path("outputs/metrics/multi_service_area_single_station_repeatability_summary.csv"))
    p.add_argument("--area-position-output", type=Path, default=Path("outputs/metrics/multi_service_area_single_station_area_position_summary.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/multi_service_area_single_station_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/multi_service_area_single_station"))
    p.add_argument("--distance-to-center-km", nargs="+", default=None)
    p.add_argument("--phi-deg", nargs="+", default=None)
    p.add_argument("--bk-modes", nargs="+", default=None)
    p.add_argument("--r-cell-km", type=float, default=500.0)
    p.add_argument("--t-service-s", type=float, default=60.0)
    p.add_argument("--alpha", type=float, default=1.0)
    p.add_argument("--max-service-areas-per-pass", type=int, default=None)
    p.add_argument("--min-segment-duration-s", type=float, default=45.0)
    p.add_argument("--num-benign-sims", type=int, default=30)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260706)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def setup_args(args: argparse.Namespace) -> None:
    smoke = args.preset == "smoke"
    args.distance_to_center_km = parse_float_csv(args.distance_to_center_km) if args.distance_to_center_km else (SMOKE_DISTANCES if smoke else MAIN_DISTANCES)
    args.phi_deg = parse_float_csv(args.phi_deg) if args.phi_deg else (SMOKE_PHIS if smoke else MAIN_PHIS)
    args.bk_modes = parse_csv(args.bk_modes) if args.bk_modes else (["current_bk", "wide_bk"] if smoke else ["no_bk", "current_bk", "wide_bk"])
    if args.max_service_areas_per_pass is None:
        args.max_service_areas_per_pass = 3 if smoke else 5
    if any(d > args.r_cell_km + 1e-9 for d in args.distance_to_center_km):
        fail("distance_to_center_km must be <= R_cell_km for this controlled run")


def check_outputs(args: argparse.Namespace) -> None:
    outputs = [
        args.dataset_output,
        args.row_summary_output,
        args.repeatability_output,
        args.area_position_output,
        args.report_output,
        args.figures_dir / "area_accept_fraction_vs_distance.png",
        args.figures_dir / "repeatability_class_vs_distance.png",
        args.figures_dir / "real_vs_synthetic_cross_area_repeatability.png",
        args.figures_dir / "service_area_index_accept_rate.png",
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
        max_targets=5,
    )
    return seg.load_inputs(loader_args)


def load_reused_samples(args: argparse.Namespace) -> pd.DataFrame:
    if not args.expanded_dataset.exists():
        fail(f"missing expanded dataset: {args.expanded_dataset}")
    cols = [
        "sample_source",
        "sample_group",
        "legacy_sample_group",
        "target_sat_id",
        "target_name",
        "attack_sat_id",
        "attack_name",
        "attacker_kind",
        "legacy_case_id",
        "legacy_decision",
        "legacy_R_km",
        "attack_type",
        "attack_param_name",
        "attack_param_value",
        "pair_id",
    ]
    df = pd.read_csv(args.expanded_dataset, usecols=cols, low_memory=False)
    samples = df.drop_duplicates().copy()
    legacy = samples["sample_source"].eq("legacy_synthetic")
    samples.loc[legacy, "sample_group"] = samples.loc[legacy, "legacy_sample_group"].fillna(samples.loc[legacy, "sample_group"])
    samples["target_sat_id"] = samples["target_sat_id"].astype(str)
    samples["attack_sat_id"] = samples["attack_sat_id"].astype(str)
    samples["sample_group"] = samples["sample_group"].astype(str)
    if args.preset == "smoke":
        parts = []
        for (_source, _group), g in samples.groupby(["sample_source", "sample_group"], sort=False):
            parts.append(g.head(2))
        samples = pd.concat(parts, ignore_index=True)
    return samples.reset_index(drop=True)


def load_legacy_env(args: argparse.Namespace) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not args.legacy_case_list.exists() or not args.legacy_dataset.exists():
        return out
    case_list = pd.read_csv(args.legacy_case_list)
    legacy = pd.read_csv(args.legacy_dataset)
    if "legacy_case_id" not in case_list.columns or "case_id" not in case_list.columns:
        return out
    for row in case_list.to_dict("records"):
        lid = str(row.get("legacy_case_id", ""))
        cid = str(row.get("case_id", ""))
        match = legacy[legacy["case_id"].astype(str).eq(cid)]
        if match.empty:
            continue
        m = match.iloc[0]
        out[lid] = {
            "b_env": float(m.get("b_injected", np.nan)),
            "k_env": float(m.get("k_injected", np.nan)),
            "sigma_hz": float(m.get("noise_std", np.nan)),
            "noise_seed": int(m.get("noise_seed", 0)),
        }
    return out


def representative_segments(track: seg.CenterTrack, t_rel: np.ndarray, max_count: int, min_duration_s: float) -> list[dict[str, Any]]:
    candidates = []
    for idx, start in enumerate(track.segment_starts):
        end = int(track.segment_ends[idx])
        duration = float(t_rel[end] - t_rel[start] + (np.median(np.diff(t_rel)) if len(t_rel) > 1 else 1.0))
        if duration + 1e-9 < min_duration_s:
            continue
        candidates.append({"segment_index": idx, "start_i": int(start), "end_i": end, "duration_s": duration})
    if not candidates:
        for idx, start in enumerate(track.segment_starts):
            end = int(track.segment_ends[idx])
            duration = float(t_rel[end] - t_rel[start] + (np.median(np.diff(t_rel)) if len(t_rel) > 1 else 1.0))
            candidates.append({"segment_index": idx, "start_i": int(start), "end_i": end, "duration_s": duration})
    if len(candidates) <= max_count:
        return candidates
    positions = np.linspace(0, len(candidates) - 1, max_count)
    selected = sorted({int(round(p)) for p in positions})
    return [candidates[i] for i in selected]


def area_phase(index: int, count: int) -> str:
    if count <= 1:
        return "middle"
    frac = index / max(count - 1, 1)
    if frac < 1.0 / 3.0:
        return "early"
    if frac > 2.0 / 3.0:
        return "late"
    return "middle"


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
    return seg.geo_curve_fixed(sat_b, lat, lon, alt_m, times, ts, freq_hz, step_s)[0]


def repeatability_class(value: float) -> str:
    if value <= 0:
        return "none"
    if value < 0.5:
        return "sporadic"
    if value < 1.0:
        return "recurrent"
    return "persistent"


def build_row_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["sample_source", "sample_group", "distance_to_center_km", "bk_mode", "service_area_index"]
    for key, g in df.groupby(group_cols, dropna=False):
        n = len(g)
        a = int(g["accept_flag"].sum())
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "total_rows": n,
                "accept_rows": a,
                "defer_rows": int(g["defer_flag"].sum()),
                "reject_rows": int(g["reject_flag"].sum()),
                "row_accept_rate": a / n if n else np.nan,
                "mean_normalized_score": float(g["normalized_score"].mean()),
            }
        )
    return pd.DataFrame(rows)


def build_repeatability(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    condition_cols = [
        "sample_source",
        "sample_group",
        "target_sat_id",
        "attack_sat_id",
        "pair_id",
        "distance_to_center_km",
        "phi_deg",
        "bk_mode",
    ]
    detail_rows = []
    for key, g in df.groupby(condition_cols, dropna=False):
        service_area_count = int(g["service_area_id"].nunique())
        accept_area_count = int(g.groupby("service_area_id")["accept_flag"].max().sum())
        defer_area_count = int(g.groupby("service_area_id")["defer_flag"].max().sum())
        reject_area_count = int(g.groupby("service_area_id")["reject_flag"].max().sum())
        frac = accept_area_count / service_area_count if service_area_count else np.nan
        detail_rows.append(
            {
                **dict(zip(condition_cols, key)),
                "service_area_count": service_area_count,
                "accept_area_count": accept_area_count,
                "defer_area_count": defer_area_count,
                "reject_area_count": reject_area_count,
                "area_accept_fraction": frac,
                "repeatability_class": repeatability_class(float(frac)),
            }
        )
    detail = pd.DataFrame(detail_rows)
    summary_cols = ["sample_source", "sample_group", "distance_to_center_km", "bk_mode"]
    rows = []
    for key, g in detail.groupby(summary_cols, dropna=False):
        n = len(g)
        any_accept = g["area_accept_fraction"] > 0
        recurrent = g["area_accept_fraction"] >= 0.5
        persistent = g["area_accept_fraction"] >= 1.0
        rows.append(
            {
                **dict(zip(summary_cols, key)),
                "pair_condition_count": n,
                "target_attacker_pair_count": int(g["pair_id"].nunique()),
                "mean_area_accept_fraction": float(g["area_accept_fraction"].mean()),
                "median_area_accept_fraction": float(g["area_accept_fraction"].median()),
                "pairs_with_any_accept": int(any_accept.sum()),
                "pairs_with_any_accept_rate": float(any_accept.mean()),
                "pairs_with_recurrent_accept": int(recurrent.sum()),
                "pairs_with_recurrent_accept_rate": float(recurrent.mean()),
                "pairs_with_persistent_accept": int(persistent.sum()),
                "pairs_with_persistent_accept_rate": float(persistent.mean()),
                "none_count": int((g["repeatability_class"] == "none").sum()),
                "sporadic_count": int((g["repeatability_class"] == "sporadic").sum()),
                "recurrent_count": int((g["repeatability_class"] == "recurrent").sum()),
                "persistent_count": int((g["repeatability_class"] == "persistent").sum()),
            }
        )
    return detail, pd.DataFrame(rows)


def build_area_position_summary(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["service_area_index", "service_area_phase", "sample_source", "sample_group", "distance_to_center_km", "bk_mode"]
    rows = []
    for key, g in df.groupby(group_cols, dropna=False):
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "total_rows": int(len(g)),
                "accept_rows": int(g["accept_flag"].sum()),
                "accept_rate": float(g["accept_flag"].mean()),
                "mean_normalized_score": float(g["normalized_score"].mean()),
            }
        )
    return pd.DataFrame(rows)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def make_figures(repeat: pd.DataFrame, detail: pd.DataFrame, area: pd.DataFrame, outdir: Path) -> list[Path]:
    paths: list[Path] = []
    d = repeat[repeat["bk_mode"].isin(["current_bk", "wide_bk"])]
    fig, ax = plt.subplots(figsize=(9, 5))
    for (source, group, bk), g in d.groupby(["sample_source", "sample_group", "bk_mode"]):
        g = g.sort_values("distance_to_center_km")
        ax.plot(g["distance_to_center_km"], g["mean_area_accept_fraction"], marker="o", label=f"{source}:{group}:{bk}")
    ax.set_xlabel("distance_to_center_km")
    ax.set_ylabel("跨服务区误接受重复率")
    ax.set_title("Area accept fraction vs distance")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=6)
    p = outdir / "area_accept_fraction_vs_distance.png"
    savefig(fig, p)
    paths.append(p)

    cls = detail.groupby(["sample_source", "sample_group", "distance_to_center_km", "bk_mode", "repeatability_class"], as_index=False).size()
    cls = cls[cls["bk_mode"].eq("current_bk")]
    fig, ax = plt.subplots(figsize=(9, 5))
    for klass, g in cls.groupby("repeatability_class"):
        gg = g.groupby("distance_to_center_km", as_index=False)["size"].sum().sort_values("distance_to_center_km")
        ax.plot(gg["distance_to_center_km"], gg["size"], marker="o", label=klass)
    ax.set_xlabel("distance_to_center_km")
    ax.set_ylabel("pair-direction count")
    ax.set_title("Repeatability class vs distance (current_bk)")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "repeatability_class_vs_distance.png"
    savefig(fig, p)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 5))
    d = repeat[repeat["bk_mode"].eq("current_bk")]
    for source, g in d.groupby("sample_source"):
        gg = g.groupby("distance_to_center_km", as_index=False)["pairs_with_recurrent_accept_rate"].mean().sort_values("distance_to_center_km")
        ax.plot(gg["distance_to_center_km"], gg["pairs_with_recurrent_accept_rate"], marker="o", label=source)
    ax.set_xlabel("distance_to_center_km")
    ax.set_ylabel("跨服务区误接受重复率")
    ax.set_title("Real vs synthetic cross-area repeatability")
    ax.grid(True, alpha=0.25)
    ax.legend()
    p = outdir / "real_vs_synthetic_cross_area_repeatability.png"
    savefig(fig, p)
    paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 5))
    d = area[(area["bk_mode"].eq("current_bk")) & (area["distance_to_center_km"].isin([0.0, 5.0, 50.0, 200.0]))]
    for (source, group), g in d.groupby(["sample_source", "sample_group"]):
        gg = g.groupby("service_area_index", as_index=False)["accept_rate"].mean().sort_values("service_area_index")
        ax.plot(gg["service_area_index"], gg["accept_rate"], marker="o", label=f"{source}:{group}")
    ax.set_xlabel("service_area_index")
    ax.set_ylabel("非目标样本误接受率")
    ax.set_title("Service area index accept rate")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7)
    p = outdir / "service_area_index_accept_rate.png"
    savefig(fig, p)
    paths.append(p)
    return paths


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[Path]]:
    setup_args(args)
    check_outputs(args)
    selection, library, orbit_cfg, tle, ranges = load_base_inputs(args)
    samples = load_reused_samples(args)
    legacy_env = load_legacy_env(args)
    ts = load.timescale()
    freq_hz = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    rng = np.random.default_rng(args.seed)
    rows: list[dict[str, Any]] = []
    geo_cache: dict[tuple[Any, ...], np.ndarray] = {}
    cal_cache: dict[tuple[str, int, int], dict[str, dict[str, float]]] = {}

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
        track = seg.center_track("M2_block", g_lat, g_lon, g_alt, t_rel, float(args.r_cell_km), float(args.alpha), float(args.t_service_s), 0.0)
        service_areas = representative_segments(track, t_rel, int(args.max_service_areas_per_pass), float(args.min_segment_duration_s))
        noise, b_env, k_env, sigma_hz, t0 = seg.sample_residual_terms(t_rel, args.residual_mode, ranges, rng)
        lid = str(sample.get("legacy_case_id", ""))
        if sample["sample_source"] == "legacy_synthetic" and lid in legacy_env:
            env = legacy_env[lid]
            if all(np.isfinite([env["b_env"], env["k_env"], env["sigma_hz"]])):
                b_env = env["b_env"]
                k_env = env["k_env"]
                sigma_hz = env["sigma_hz"]
                noise = np.random.default_rng(int(env["noise_seed"])).normal(0.0, sigma_hz, len(t_rel))
        for area_order, area in enumerate(service_areas):
            seg_idx = int(area["segment_index"])
            seg_start_i = int(area["start_i"])
            seg_end_i = int(area["end_i"])
            eval_times = times[seg_start_i : seg_end_i + 1]
            eval_t_rel = t_rel[seg_start_i : seg_end_i + 1]
            eval_noise = noise[seg_start_i : seg_end_i + 1]
            c_lat = float(track.lat_deg[seg_start_i])
            c_lon = float(track.lon_deg[seg_start_i])
            service_area_id = f"{pass_id}_area_{seg_idx}"
            cal_key = (target_id, seg_start_i, seg_end_i)
            if cal_key not in cal_cache:
                cal_cache[cal_key] = seg.calibration_for_trel(eval_t_rel, ranges, args.seed + int(target_id) + seg_idx, int(args.num_benign_sims))
            for distance_value in args.distance_to_center_km:
                phis = [0.0] if abs(float(distance_value)) < 1e-12 else list(args.phi_deg)
                for phi in phis:
                    s_lat, s_lon = seg.destination(c_lat, c_lon, float(distance_value), float(phi))
                    a_center_base = (target_id, round(c_lat, 7), round(c_lon, 7), seg_start_i, seg_end_i)
                    a_site_base = (target_id, round(s_lat, 7), round(s_lon, 7), seg_start_i, seg_end_i)
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
                        round(s_lat, 7),
                        round(s_lon, 7),
                        seg_start_i,
                        seg_end_i,
                    )
                    keys = {
                        "a_c": ("A_C", a_center_base),
                        "a_s": ("A_S", a_site_base),
                        "b_c": ("B_C", b_center_base),
                        "b_s": ("B_S", b_site_base),
                    }
                    if keys["a_c"] not in geo_cache:
                        geo_cache[keys["a_c"]] = seg.geo_curve_fixed(sat_a, c_lat, c_lon, 0.0, eval_times, ts, freq_hz, step_s)[0]
                    if keys["a_s"] not in geo_cache:
                        geo_cache[keys["a_s"]] = seg.geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, eval_times, ts, freq_hz, step_s)[0]
                    if keys["b_c"] not in geo_cache:
                        geo_cache[keys["b_c"]] = attack_geo(sample, sat_a, sat_b, c_lat, c_lon, 0.0, eval_times, ts, freq_hz, step_s)
                    if keys["b_s"] not in geo_cache:
                        geo_cache[keys["b_s"]] = attack_geo(sample, sat_a, sat_b, s_lat, s_lon, 0.0, eval_times, ts, freq_hz, step_s)
                    f_a_c = geo_cache[keys["a_c"]]
                    f_a_s = geo_cache[keys["a_s"]]
                    f_b_c = geo_cache[keys["b_c"]]
                    f_b_s = geo_cache[keys["b_s"]]
                    u = f_a_c - f_b_c
                    y_atk = f_b_s + u + b_env + k_env * (eval_t_rel - t0) + eval_noise
                    dist_series = seg.distance_km(np.full(len(eval_t_rel), c_lat), np.full(len(eval_t_rel), c_lon), s_lat, s_lon)
                    coverage = dist_series <= float(args.r_cell_km) + 1e-9
                    r_geo = f_b_s + f_a_c - f_b_c - f_a_s
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
                        rows.append(
                            {
                                "case_id": f"{sample['pair_id']}_area{seg_idx}_d{float(distance_value):g}_phi{float(phi):g}_{bk_mode}",
                                "sample_source": sample["sample_source"],
                                "sample_group": sample["sample_group"],
                                "legacy_case_id": sample.get("legacy_case_id", ""),
                                "legacy_decision": sample.get("legacy_decision", ""),
                                "legacy_R_km": sample.get("legacy_R_km", np.nan),
                                "attacker_kind": sample.get("attacker_kind", ""),
                                "attack_type": sample.get("attack_type", ""),
                                "attack_param_name": sample.get("attack_param_name", ""),
                                "attack_param_value": sample.get("attack_param_value", ""),
                                "attack_model": "M2_block",
                                "receiver_mode": "heatmap_mode",
                                "evaluation_scope": "segment_local",
                                "doppler_reference_mode": "fixed_site_segment_center",
                                "verification_strategy": "single-window",
                                "T_service_s": float(args.t_service_s),
                                "R_cell_km": float(args.r_cell_km),
                                "target_sat_id": target_id,
                                "target_name": sample["target_name"],
                                "attack_sat_id": sample["attack_sat_id"],
                                "attack_name": sample["attack_name"],
                                "pair_id": sample["pair_id"],
                                "pass_id": pass_id,
                                "service_area_id": service_area_id,
                                "service_area_index": int(area_order),
                                "service_area_segment_index": int(seg_idx),
                                "service_area_phase": area_phase(area_order, len(service_areas)),
                                "segment_start_s": float(t_rel[seg_start_i]),
                                "segment_end_s": float(t_rel[seg_end_i]),
                                "segment_duration_s": float(area["duration_s"]),
                                "evaluation_start_s": float(eval_t_rel[0]),
                                "evaluation_end_s": float(eval_t_rel[-1]),
                                "C_lat": c_lat,
                                "C_lon": c_lon,
                                "S_lat": float(s_lat),
                                "S_lon": float(s_lon),
                                "distance_to_center_km": float(distance_value),
                                "actual_distance_to_center_km": float(np.mean(dist_series)),
                                "distance_error_km": float(abs(np.mean(dist_series) - float(distance_value))),
                                "rho": float(distance_value) / float(args.r_cell_km),
                                "phi_deg": float(phi),
                                "bk_mode": bk_mode,
                                "b_env": float(b_env),
                                "k_env": float(k_env),
                                "sigma_hz": float(sigma_hz),
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
                                "random_seed": int(args.seed),
                                "sample_index_global": int(sidx),
                            }
                        )
    df = pd.DataFrame(rows)
    if df.empty:
        fail("no rows generated")
    row_summary = build_row_summary(df)
    repeat_detail, repeat_summary = build_repeatability(df)
    area_summary = build_area_position_summary(df)
    for path in [args.dataset_output, args.row_summary_output, args.repeatability_output, args.area_position_output, args.report_output]:
        path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.dataset_output, index=False)
    row_summary.to_csv(args.row_summary_output, index=False)
    repeat_summary.to_csv(args.repeatability_output, index=False)
    repeat_detail.to_csv(args.repeatability_output.with_name(args.repeatability_output.stem + "_detail.csv"), index=False)
    area_summary.to_csv(args.area_position_output, index=False)
    figures = make_figures(repeat_summary, repeat_detail, area_summary, args.figures_dir)
    write_report(args, df, row_summary, repeat_summary, repeat_detail, area_summary, figures)
    append_log(args, df, row_summary, repeat_summary, area_summary, figures)
    return df, row_summary, repeat_summary, area_summary, figures


def table_for(repeat: pd.DataFrame, source: str, group: str, bk: str = "current_bk") -> pd.DataFrame:
    return repeat[
        repeat["sample_source"].eq(source)
        & repeat["sample_group"].eq(group)
        & repeat["bk_mode"].eq(bk)
    ].sort_values("distance_to_center_km")


def write_report(
    args: argparse.Namespace,
    df: pd.DataFrame,
    row_summary: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    repeat_detail: pd.DataFrame,
    area_summary: pd.DataFrame,
    figures: list[Path],
) -> None:
    audit = {
        "evaluation_scope_ok": bool(df["evaluation_scope"].eq("segment_local").all()),
        "doppler_reference_ok": bool(df["doppler_reference_mode"].eq("fixed_site_segment_center").all()),
        "coverage_ok": bool(df["coverage_valid_fraction"].ge(1.0 - 1e-12).all() and df["coverage_gate_pass"].all()),
        "interval_equals_segment": bool(np.allclose(df["evaluation_start_s"], df["segment_start_s"]) and np.allclose(df["evaluation_end_s"], df["segment_end_s"])),
        "max_distance_error_km": float(df["distance_error_km"].max()),
        "rho0_rmse_r_geo_max_hz": float(df[df["distance_to_center_km"].eq(0.0)]["rmse_r_geo_hz"].max()),
    }
    scale = df.groupby(["sample_source", "sample_group"])["pair_id"].nunique().to_dict()
    service_counts = df.groupby(["sample_source", "sample_group"])["service_area_id"].nunique().to_dict()
    figs = "\n".join(f"- `{p.as_posix()}`" for p in figures)
    text = f"""# Multi-service-area single-station repeatability

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

本文仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。本轮也不是多站一致性实验；不同服务区中的 `S_i` 不是同时工作的多个接收站。

## 1. 实验目标

本轮只回答：同一种服务中心补偿风险，在多个不同服务区和各自固定验证站上，是偶发的局部几何现象，还是能够稳定重复出现。

## 2. 实验设置

- attack_model: `M2_block`
- receiver_mode: `heatmap_mode`
- evaluation_scope: `segment_local`
- doppler_reference_mode: `fixed_site_segment_center`
- verification_strategy: `single-window`
- T_service_s: `{args.t_service_s}`
- R_cell_km: `{args.r_cell_km}`，仅为受控尺度参数，不代表真实 Starlink 服务区半径。
- distance_to_center_km: `{args.distance_to_center_km}`
- d=0 只保留 `phi=0`；d>0 使用 `{args.phi_deg}`
- bk_mode: `{args.bk_modes}`
- max_service_areas_per_pass: `{args.max_service_areas_per_pass}`
- min_segment_duration_s: `{args.min_segment_duration_s}`

## 3. 样本规模

- dataset rows: `{len(df)}`
- row summary rows: `{len(row_summary)}`
- repeatability summary rows: `{len(repeat_summary)}`
- sample pair counts: `{scale}`
- service area counts: `{service_counts}`

## 4. 正确性审计

{pd.DataFrame([audit]).to_markdown(index=False)}

## 5. current_bk 跨服务区重复性

### real TLE ordinary_similar

{table_for(repeat_summary, 'real_tle_candidate', 'ordinary_similar').to_markdown(index=False)}

### real TLE boundary_case

{table_for(repeat_summary, 'real_tle_candidate', 'boundary_case').to_markdown(index=False)}

### legacy original_like

{table_for(repeat_summary, 'legacy_synthetic', 'original_like').to_markdown(index=False)}

### legacy hard_case_weighted

{table_for(repeat_summary, 'legacy_synthetic', 'hard_case_weighted').to_markdown(index=False)}

## 6. 服务区位置统计

{area_summary[area_summary['bk_mode'].eq('current_bk')].head(80).to_markdown(index=False)}

## 7. 图像

{figs}

## 8. 表述边界

跨服务区重复性分类只是描述性统计，不是新的 verifier 判决规则。不同服务区使用各自的局部补偿 `u_i(t)`，因此这些结果不能解释为多站 all-accept 或 majority 策略。
"""
    args.report_output.write_text(text, encoding="utf-8")


def append_log(
    args: argparse.Namespace,
    df: pd.DataFrame,
    row_summary: pd.DataFrame,
    repeat_summary: pd.DataFrame,
    area_summary: pd.DataFrame,
    figures: list[Path],
) -> None:
    path = Path("logs/work_log.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    audit_ok = bool(
        df["evaluation_scope"].eq("segment_local").all()
        and df["doppler_reference_mode"].eq("fixed_site_segment_center").all()
        and df["coverage_valid_fraction"].ge(1.0 - 1e-12).all()
        and df[df["distance_to_center_km"].eq(0.0)]["rmse_r_geo_hz"].max() < 1e-3
    )
    text = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} - multi-service-area single-station repeatability

### A. 本轮目标

在多个 M2_block 服务区中，为每个服务区放置各自固定验证站，检查同一种服务中心补偿风险是否跨服务区重复出现。

### B. 实际操作

- 新增 `scripts/run_multi_service_area_single_station_confirmation.py`。
- 复用上一轮 expanded run 的 target-attacker / synthetic spec 清单。
- 保持 `heatmap_mode + segment_local + fixed_site_segment_center + single-window`。
- 未新增攻击模型，未修改 sequence_mode，未做多站一致性。

### C. 新增/修改文件

- `{args.dataset_output.as_posix()}`
- `{args.row_summary_output.as_posix()}`
- `{args.repeatability_output.as_posix()}`
- `{args.area_position_output.as_posix()}`
- `{args.report_output.as_posix()}`
- `{args.figures_dir.as_posix()}/`

### D. 运行命令

preset=`{args.preset}`，max_service_areas_per_pass=`{args.max_service_areas_per_pass}`，R_cell_km=`{args.r_cell_km}`。

### E. 结果摘要

- dataset rows: `{len(df)}`
- row summary rows: `{len(row_summary)}`
- repeatability summary rows: `{len(repeat_summary)}`
- figures: `{len(figures)}`
- correctness audit passed: `{audit_ok}`

### F. 问题与下一步

- 本轮仍是 controlled segmented service-center compensation simulation，不是真实 Starlink 调度复现。
- 结果只用于跨服务区风险重复性，不用于多站一致性结论。
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    df, row_summary, repeat_summary, area_summary, figures = run(args)
    print(f"wrote {args.dataset_output} rows={len(df)}")
    print(f"wrote {args.row_summary_output} rows={len(row_summary)}")
    print(f"wrote {args.repeatability_output} rows={len(repeat_summary)}")
    print(f"wrote {args.area_position_output} rows={len(area_summary)}")
    print(f"wrote {args.report_output}")
    print(f"wrote figures={len(figures)} to {args.figures_dir}")


if __name__ == "__main__":
    main()
