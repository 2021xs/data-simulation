#!/usr/bin/env python
"""Controlled segmented service-center compensation simulation.

This experiment is an offline controlled simulation.  It does not reproduce
Starlink beam scheduling, service cell binding, handover policy, or wireless
resource scheduling.  For each selected A/B/pass it recomputes F_A(t; S),
F_B(t; S), F_A(t; C), F_B(t; C), and the attack residual from local TLE
propagation.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
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

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_controlled_starlink_multitarget_dataset as orbit_builder  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_window_aware_evidence_accumulation as wae  # noqa: E402
import run_window_reliability_calibration as wrc  # noqa: E402


ATTACK_MODELS = ["M0", "M1", "M2_fast", "M2_block"]
RECEIVER_MODES = ["heatmap_mode", "sequence_mode"]
SMOKE_R_CELLS = [100.0, 500.0]
MAIN_R_CELLS = [50.0, 100.0, 200.0, 500.0]
T_SERVICE_VALUES = [30.0, 60.0, 120.0]
T_MIN_VALUES = [30.0, 60.0]
SMOKE_RHOS = [0.0, 0.5, 1.0]
MAIN_RHOS = [0.0, 0.25, 0.5, 0.75, 1.0]
SMOKE_PHIS = [0.0, 90.0, 180.0, 270.0]
MAIN_PHIS = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
SMOKE_BK_MODES = ["no_bk", "current_bk", "wide_bk", "bk_risk_defer"]
MAIN_BK_MODES = ["no_bk", "strict_bk", "current_bk", "wide_bk", "bk_risk_defer"]
SAMPLE_GROUPS = ["random_simulated", "ordinary_similar", "boundary_case"]
VERIFICATION_STRATEGIES = [
    "single-window",
    "window-aware accumulation",
    "multi-station all-accept",
    "multi-station + bk-risk-defer",
]
EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class CenterTrack:
    lat_deg: np.ndarray
    lon_deg: np.ndarray
    alt_m: np.ndarray
    segment_index: np.ndarray
    segment_starts: list[int]
    segment_ends: list[int]
    segment_rule: str


@dataclass(frozen=True)
class EvalDecision:
    decision: str
    reason: str
    residual_rmse_hz: float
    normalized_score: float
    b_hat_hz: float
    k_hat_hz_per_s: float
    raw_delta_rmse_hz: float
    score_gate_pass: bool
    b_gate_pass: bool
    k_gate_pass: bool
    coverage_gate_pass: bool


def fail(message: str) -> None:
    raise SystemExit(message)


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
    p = argparse.ArgumentParser(description="Run controlled segmented service-center compensation simulation.")
    p.add_argument("--preset", choices=["smoke", "main"], default="main")
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--hard-cases", type=Path, default=Path("outputs/metrics/window_aware_attack_accept_hard_cases.csv"))
    p.add_argument("--dataset-output", type=Path, default=Path("outputs/datasets/segmented_service_center_dwell_dataset.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/segmented_service_center_dwell_summary.csv"))
    p.add_argument("--segment-audit-output", type=Path, default=Path("outputs/metrics/segmented_service_center_segment_audit.csv"))
    p.add_argument("--heatmap-output", type=Path, default=Path("outputs/metrics/segmented_service_center_dwell_heatmap_input.csv"))
    p.add_argument("--geo-residual-output", type=Path, default=Path("outputs/metrics/segmented_service_center_geo_residual_audit.csv"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/segmented_service_center_dwell_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/segmented_service_center_dwell"))
    p.add_argument("--evaluation-scope", choices=["full_pass", "segment_local"], default="full_pass")
    p.add_argument("--doppler-reference-mode", choices=["moving_reference", "fixed_site_segment_center"], default="moving_reference")
    p.add_argument("--r-cell-km", nargs="+", default=None)
    p.add_argument("--alpha", nargs="+", default=None)
    p.add_argument("--rho", nargs="+", default=None)
    p.add_argument("--phi-deg", nargs="+", default=None)
    p.add_argument("--sample-groups", nargs="+", default=None)
    p.add_argument("--bk-modes", nargs="+", default=None)
    p.add_argument("--verification-strategies", nargs="+", default=None)
    p.add_argument("--receiver-modes", nargs="+", default=None)
    p.add_argument("--attack-models", nargs="+", default=None)
    p.add_argument("--t-service-s", nargs="+", default=None)
    p.add_argument("--t-min-s", nargs="+", default=None)
    p.add_argument("--max-targets", type=int, default=None)
    p.add_argument("--max-attackers-per-group", type=int, default=1)
    p.add_argument("--num-benign-sims", type=int, default=40)
    p.add_argument("--max-heatmap-segments", type=int, default=None)
    p.add_argument("--residual-mode", choices=["clean", "empirical"], default="empirical")
    p.add_argument("--seed", type=int, default=20260702)
    p.add_argument("--station-separation-km", type=float, default=100.0)
    p.add_argument("--station-bearing-deg", type=float, default=90.0)
    p.add_argument("--moving-reference-diff-step-s", type=float, default=0.5)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def check_outputs(args: argparse.Namespace) -> None:
    outputs = [
        args.dataset_output,
        args.summary_output,
        args.heatmap_output,
        args.segment_audit_output,
        args.geo_residual_output,
        args.report_output,
        args.figures_dir / "segment_duration_audit.png",
        args.figures_dir / "attack_model_dwell_comparison.png",
        args.figures_dir / "tservice_sensitivity.png",
        args.figures_dir / "rho_sensitivity_m2_block.png",
        args.figures_dir / "bk_ablation_m2_block.png",
        args.figures_dir / "window_aware_vs_single_m2_block.png",
    ]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not args.overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))


def require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{name} missing columns: {', '.join(missing)}")


def setup_grid(args: argparse.Namespace) -> None:
    smoke = args.preset == "smoke"
    args.r_cell_km = parse_float_csv(args.r_cell_km) if args.r_cell_km else (SMOKE_R_CELLS if smoke else MAIN_R_CELLS)
    args.alpha = parse_float_csv(args.alpha) if args.alpha else ([1.0] if smoke else [0.5, 1.0])
    args.rho = parse_float_csv(args.rho) if args.rho else (SMOKE_RHOS if smoke else MAIN_RHOS)
    args.phi_deg = parse_float_csv(args.phi_deg) if args.phi_deg else (SMOKE_PHIS if smoke else MAIN_PHIS)
    args.sample_groups = parse_csv(args.sample_groups) if args.sample_groups else SAMPLE_GROUPS
    args.bk_modes = parse_csv(args.bk_modes) if args.bk_modes else (SMOKE_BK_MODES if smoke else MAIN_BK_MODES)
    default_strategies = ["single-window", "window-aware accumulation"] if smoke else VERIFICATION_STRATEGIES
    args.verification_strategies = parse_csv(args.verification_strategies) if args.verification_strategies else default_strategies
    args.receiver_modes = parse_csv(args.receiver_modes) if args.receiver_modes else RECEIVER_MODES
    args.attack_models = parse_csv(args.attack_models) if args.attack_models else ATTACK_MODELS
    args.attack_models = ["M2_fast" if m == "M2" else m for m in args.attack_models]
    args.t_service_s = parse_float_csv(args.t_service_s) if args.t_service_s else T_SERVICE_VALUES
    args.t_min_s = parse_float_csv(args.t_min_s) if args.t_min_s else T_MIN_VALUES
    if args.max_targets is None:
        args.max_targets = 1 if smoke else 2
    if args.max_heatmap_segments is None:
        args.max_heatmap_segments = 3 if smoke else 5
    unsupported = set(args.bk_modes) - set(MAIN_BK_MODES)
    if unsupported:
        fail(f"unsupported bk modes: {', '.join(sorted(unsupported))}")
    unsupported_models = set(args.attack_models) - {"M0", "M1", "M2_fast", "M2_block", "M2_hybrid"}
    if unsupported_models:
        fail(f"unsupported attack models: {', '.join(sorted(unsupported_models))}")
    if args.evaluation_scope == "segment_local" and args.doppler_reference_mode != "fixed_site_segment_center":
        fail("evaluation_scope=segment_local requires doppler_reference_mode=fixed_site_segment_center")


def distance_km(lat1: float | np.ndarray, lon1: float | np.ndarray, lat2: float, lon2: float) -> np.ndarray:
    return active.haversine_distance_km(np.asarray(lat1, dtype=float), np.asarray(lon1, dtype=float), float(lat2), float(lon2))


def destination(lat_deg: float, lon_deg: float, distance_km_value: float, bearing_deg: float) -> tuple[float, float]:
    return active.destination_point(float(lat_deg), float(lon_deg), float(distance_km_value), float(bearing_deg))


def signed_offsets_km(rho: float, phi_deg: float, r_cell_km: float) -> tuple[float, float]:
    d = float(rho) * float(r_cell_km)
    theta = math.radians(float(phi_deg))
    return float(d * math.cos(theta)), float(d * math.sin(theta))


def load_inputs(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, list[float]]]:
    for path in [args.selection_table, args.candidate_library, args.tle_file, args.orbit_config, args.parameter_config]:
        if not path.exists():
            fail(f"missing input: {path}")
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=int(args.max_targets),
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    if orbit_cfg.get("mode") != "controlled_starlink":
        fail("current experiment must use controlled_starlink mode")
    if orbit_cfg.get("observation_id") is not None:
        fail("controlled_starlink mode requires observation_id=null")
    ts = load.timescale()
    tle = base.parse_tle(args.tle_file, ts)
    selection = selection.head(int(args.max_targets)).copy()
    library = library.copy()
    library["target_norad_id"] = library["target_norad_id"].astype(str)
    library["candidate_norad_id"] = library["candidate_norad_id"].astype(str)
    for tid in selection["target_norad_id"].astype(str):
        if tid not in tle:
            fail(f"target not found in TLE: {tid}")
    return selection, library, orbit_cfg, tle, ranges


def select_attack_samples(
    selection: pd.DataFrame,
    library: pd.DataFrame,
    tle: dict[str, dict[str, Any]],
    groups: list[str],
    max_attackers_per_group: int,
    hard_cases_path: Path,
) -> pd.DataFrame:
    hard = pd.read_csv(hard_cases_path) if hard_cases_path.exists() else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for target in selection.itertuples(index=False):
        target_id = str(target.target_norad_id)
        cand = library[(library["target_norad_id"].eq(target_id)) & (~library["candidate_norad_id"].eq(target_id))].copy()
        cand = cand[cand["candidate_norad_id"].isin(tle.keys())]
        cand = cand[["candidate_name", "candidate_norad_id", "candidate_rank_or_selection_order"]].drop_duplicates()
        cand = cand.sort_values(["candidate_rank_or_selection_order", "candidate_norad_id"]).reset_index(drop=True)
        if cand.empty:
            fail(f"no attacker candidate for target {target_id}")
        for group in groups:
            if group == "ordinary_similar":
                chosen = cand.head(max_attackers_per_group)
            elif group == "random_simulated":
                chosen = cand.tail(max_attackers_per_group)
            elif group == "boundary_case":
                chosen = cand.iloc[min(1, len(cand) - 1) : min(1, len(cand) - 1) + max_attackers_per_group]
                if not hard.empty and "target_id" in hard.columns and str(target_id) in set(hard["target_id"].astype(str)):
                    chosen = cand.head(max_attackers_per_group)
            else:
                continue
            for idx, row in chosen.reset_index(drop=True).iterrows():
                rows.append(
                    {
                        "target_sat_id": target_id,
                        "target_name": str(target.target_name),
                        "attack_sat_id": str(row["candidate_norad_id"]),
                        "attack_name": str(row["candidate_name"]),
                        "sample_group": group,
                        "sample_index": int(idx + 1),
                    }
                )
    samples = pd.DataFrame(rows).drop_duplicates()
    if samples.empty:
        fail("no attack samples selected")
    return samples.reset_index(drop=True)


def compute_subpoint_series(sat: Any, times: list[datetime], ts: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sky_times = ts.from_datetimes(times)
    subpoint = sat.at(sky_times).subpoint()
    return (
        np.asarray(subpoint.latitude.degrees, dtype=float),
        np.asarray(subpoint.longitude.degrees, dtype=float),
        np.zeros(len(times), dtype=float),
    )


def build_segment_indices(g_lat: np.ndarray, g_lon: np.ndarray, l_step_km: float) -> tuple[np.ndarray, list[int], list[int]]:
    seg = np.zeros(len(g_lat), dtype=int)
    starts = [0]
    current_lat = float(g_lat[0])
    current_lon = float(g_lon[0])
    current_seg = 0
    for i in range(1, len(g_lat)):
        d = float(distance_km(np.array([g_lat[i]]), np.array([g_lon[i]]), current_lat, current_lon)[0])
        if d >= float(l_step_km):
            current_seg += 1
            starts.append(i)
            current_lat = float(g_lat[i])
            current_lon = float(g_lon[i])
        seg[i] = current_seg
    ends = [s - 1 for s in starts[1:]] + [len(g_lat) - 1]
    return seg, starts, ends


def build_block_indices(t_rel: np.ndarray, t_service_s: float) -> tuple[np.ndarray, list[int], list[int]]:
    seg = np.zeros(len(t_rel), dtype=int)
    starts = [0]
    current_seg = 0
    current_start_t = float(t_rel[0])
    for i in range(1, len(t_rel)):
        if float(t_rel[i]) - current_start_t >= float(t_service_s):
            current_seg += 1
            starts.append(i)
            current_start_t = float(t_rel[i])
        seg[i] = current_seg
    ends = [s - 1 for s in starts[1:]] + [len(t_rel) - 1]
    return seg, starts, ends


def build_hybrid_indices(
    g_lat: np.ndarray,
    g_lon: np.ndarray,
    t_rel: np.ndarray,
    l_step_km: float,
    t_min_s: float,
) -> tuple[np.ndarray, list[int], list[int]]:
    seg = np.zeros(len(g_lat), dtype=int)
    starts = [0]
    current_lat = float(g_lat[0])
    current_lon = float(g_lon[0])
    current_start_t = float(t_rel[0])
    current_seg = 0
    for i in range(1, len(g_lat)):
        moved_km = float(distance_km(np.array([g_lat[i]]), np.array([g_lon[i]]), current_lat, current_lon)[0])
        dwell_s = float(t_rel[i]) - current_start_t
        if moved_km >= float(l_step_km) and dwell_s >= float(t_min_s):
            current_seg += 1
            starts.append(i)
            current_lat = float(g_lat[i])
            current_lon = float(g_lon[i])
            current_start_t = float(t_rel[i])
        seg[i] = current_seg
    ends = [s - 1 for s in starts[1:]] + [len(g_lat) - 1]
    return seg, starts, ends


def center_track(
    attack_model: str,
    g_lat: np.ndarray,
    g_lon: np.ndarray,
    g_alt: np.ndarray,
    t_rel: np.ndarray,
    r_cell_km: float,
    alpha: float,
    t_service_s: float = 0.0,
    t_min_s: float = 0.0,
) -> CenterTrack:
    n = len(g_lat)
    if attack_model == "M0":
        mid = n // 2
        return CenterTrack(
            np.full(n, float(g_lat[mid])),
            np.full(n, float(g_lon[mid])),
            np.zeros(n, dtype=float),
            np.zeros(n, dtype=int),
            [0],
            [n - 1],
            "fixed",
        )
    if attack_model == "M1":
        return CenterTrack(g_lat.copy(), g_lon.copy(), g_alt.copy(), np.arange(n, dtype=int), list(range(n)), list(range(n)), "continuous")
    if attack_model == "M2":
        attack_model = "M2_fast"
    if attack_model == "M2_fast":
        seg, starts, ends = build_segment_indices(g_lat, g_lon, float(alpha) * float(r_cell_km))
        rule = "spatial_step"
    elif attack_model == "M2_block":
        seg, starts, ends = build_block_indices(t_rel, float(t_service_s))
        rule = "dwell_block"
    elif attack_model == "M2_hybrid":
        seg, starts, ends = build_hybrid_indices(g_lat, g_lon, t_rel, float(alpha) * float(r_cell_km), float(t_min_s))
        rule = "hybrid_dwell"
    else:
        fail(f"unsupported attack model: {attack_model}")
    c_lat = np.zeros(n, dtype=float)
    c_lon = np.zeros(n, dtype=float)
    for _sidx, start in enumerate(starts):
        end = ends[_sidx]
        c_lat[start : end + 1] = float(g_lat[start])
        c_lon[start : end + 1] = float(g_lon[start])
    return CenterTrack(c_lat, c_lon, np.zeros(n, dtype=float), seg, starts, ends, rule)


def geo_curve_fixed(sat: Any, lat: float, lon: float, alt_m: float, times: list[datetime], ts: Any, freq_hz: float, step_s: float) -> tuple[np.ndarray, np.ndarray]:
    site = orbit_builder.wgs84.latlon(float(lat), float(lon), elevation_m=float(alt_m))
    geo = orbit_builder.geo_curve(sat, site, ts, times, float(freq_hz), float(step_s))
    return geo["f_geo_tle_hz"].to_numpy(float), geo["elevation_deg"].to_numpy(float)


def representative_indices(indices: list[int], max_count: int) -> list[int]:
    if max_count <= 0 or len(indices) <= max_count:
        return list(indices)
    positions = np.linspace(0, len(indices) - 1, int(max_count))
    chosen = sorted({int(round(p)) for p in positions})
    return [indices[i] for i in chosen]


def geo_curve_moving(
    sat: Any,
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    alt_m: np.ndarray,
    times: list[datetime],
    ts: Any,
    freq_hz: float,
    diff_step_s: float,
) -> np.ndarray:
    f_geo, _range_rate = active.geo_curve_moving_reference(sat, lat_deg, lon_deg, alt_m, times, ts, freq_hz, diff_step_s)
    return f_geo


def calibration_for_trel(t_rel: np.ndarray, ranges: dict[str, list[float]], seed: int, n: int) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    specs = [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)]
    for length in [60]:
        spec = wrc.build_middle_window(t_rel, length)
        if not spec.skip_reason:
            specs.append(spec)
    by_key: dict[str, list[wrc.WindowSpec]] = {"full_pass": [specs[0]]}
    by_key["60"] = [s for s in specs if int(round(s.window_length_s)) == 60]
    out: dict[str, dict[str, float]] = {}
    f_zero = np.zeros(len(t_rel), dtype=float)
    for key, key_specs in by_key.items():
        if not key_specs:
            continue
        scores: list[float] = []
        b_vals: list[float] = []
        k_vals: list[float] = []
        for _ in range(n):
            err = base.sample_error_params(ranges, rng)
            noise = rng.normal(0.0, err.sigma_hz, len(t_rel)) if err.sigma_hz > 0 else np.zeros(len(t_rel), dtype=float)
            y = err.b_hz + err.k_hz_s * (t_rel - float(np.mean(t_rel))) + noise
            for spec in key_specs:
                mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
                fit = wrc.fit_on_mask(y, f_zero, t_rel, mask)
                scores.append(float(fit.score_rmse_hz))
                b_vals.append(float(fit.b_hat_hz))
                k_vals.append(float(fit.k_hat_hz_s))
        b_arr = np.asarray(b_vals, dtype=float)
        k_arr = np.asarray(k_vals, dtype=float)
        b_center = float(np.median(b_arr))
        k_center = float(np.median(k_arr))
        out[key] = {
            "score_p95": float(np.quantile(scores, 0.95)),
            "score_p99": float(np.quantile(scores, 0.99)),
            "b_center": b_center,
            "k_center": k_center,
            "b_abs_p95": max(float(np.quantile(np.abs(b_arr - b_center), 0.95)), 1e-9),
            "k_abs_p95": max(float(np.quantile(np.abs(k_arr - k_center), 0.95)), 1e-9),
            "b_abs_p99": max(float(np.quantile(np.abs(b_arr - b_center), 0.99)), 1e-9),
            "k_abs_p99": max(float(np.quantile(np.abs(k_arr - k_center), 0.99)), 1e-9),
            "calibration_n": float(len(scores)),
        }
    return out


def threshold_for(cal: dict[str, dict[str, float]], key: str, bk_mode: str) -> dict[str, float]:
    c = cal[key]
    if bk_mode == "no_bk":
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": math.inf, "k_threshold": math.inf}
    if bk_mode == "strict_bk":
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": c["b_abs_p95"], "k_threshold": c["k_abs_p95"]}
    if bk_mode in {"current_bk", "bk_risk_defer"}:
        mult = wae.BK_MULTIPLIERS["full_pass" if key == "full_pass" else int(key)]
        return {"score_threshold": c["score_p95"], "b_center": c["b_center"], "k_center": c["k_center"], "b_threshold": c["b_abs_p99"] * float(mult[0]), "k_threshold": c["k_abs_p99"] * float(mult[1])}
    if bk_mode == "wide_bk":
        th = threshold_for(cal, key, "current_bk")
        th["b_threshold"] *= 2.0
        th["k_threshold"] *= 2.0
        return th
    fail(f"unsupported bk mode: {bk_mode}")


def fit_for_mask(y_obs: np.ndarray, f_geo_a: np.ndarray, t_rel: np.ndarray, mask: np.ndarray, bk_mode: str) -> tuple[float, float, float, float]:
    delta = y_obs[mask] - f_geo_a[mask]
    raw_rmse = float(np.sqrt(np.mean(delta**2))) if len(delta) else np.nan
    if bk_mode == "no_bk":
        return raw_rmse, 0.0, 0.0, raw_rmse
    fit = wrc.fit_on_mask(y_obs, f_geo_a, t_rel, mask)
    return float(fit.score_rmse_hz), float(fit.b_hat_hz), float(fit.k_hat_hz_s), raw_rmse


def spread_3x60_specs(t_rel: np.ndarray) -> list[wrc.WindowSpec]:
    if float(np.max(t_rel) - np.min(t_rel)) < 180.0:
        return [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)]
    return wae.choose_group_specs("3x60s", "spread_segments", t_rel, np.zeros(len(t_rel)), np.zeros(len(t_rel)), {60: {"score_p95": 1.0}}, 0.2)


def evaluate_single_station(
    *,
    y_obs: np.ndarray,
    f_geo_a: np.ndarray,
    t_rel: np.ndarray,
    coverage_mask: np.ndarray,
    cal: dict[str, dict[str, float]],
    bk_mode: str,
    verification_strategy: str,
    force_bk_risk_defer: bool = False,
) -> EvalDecision:
    if verification_strategy == "single-window":
        specs = [wrc.build_middle_window(t_rel, wrc.FULL_PASS_LENGTH_SENTINEL)]
    else:
        specs = spread_3x60_specs(t_rel)
    scores: list[float] = []
    b_vals: list[float] = []
    k_vals: list[float] = []
    raw_vals: list[float] = []
    score_passes: list[bool] = []
    b_passes: list[bool] = []
    k_passes: list[bool] = []
    coverage_passes: list[bool] = []
    evidence = 0.0
    for spec in specs:
        mask = wrc.slice_mask(t_rel, spec.start_s, spec.stop_s)
        if int(mask.sum()) < 3:
            continue
        covered = bool(np.all(coverage_mask[mask]))
        key = "full_pass" if spec.window_position == "full_pass" else str(int(round(spec.window_length_s)))
        if key not in cal:
            key = "full_pass"
        th = threshold_for(cal, key, bk_mode)
        score, b_hat, k_hat, raw_rmse = fit_for_mask(y_obs, f_geo_a, t_rel, mask, bk_mode)
        sp = bool(score <= th["score_threshold"])
        bp = True if bk_mode == "no_bk" else bool(abs(b_hat - th["b_center"]) <= th["b_threshold"])
        kp = True if bk_mode == "no_bk" else bool(abs(k_hat - th["k_center"]) <= th["k_threshold"])
        local = covered and sp and bp and kp
        if local:
            length = int(round(spec.window_length_s))
            evidence += float(wae.EVIDENCE_NORMAL.get(length, 0.0))
        scores.append(score)
        b_vals.append(b_hat)
        k_vals.append(k_hat)
        raw_vals.append(raw_rmse)
        score_passes.append(sp)
        b_passes.append(bp)
        k_passes.append(kp)
        coverage_passes.append(covered)
    if not scores:
        return EvalDecision("DEFER", "no_valid_window", np.nan, np.nan, np.nan, np.nan, np.nan, False, False, False, False)
    score = float(np.nanmedian(scores))
    b_hat = float(np.nanmedian(b_vals))
    k_hat = float(np.nanmedian(k_vals))
    raw_rmse = float(np.nanmedian(raw_vals))
    first_key = "full_pass" if verification_strategy == "single-window" else "60"
    if first_key not in cal:
        first_key = "full_pass"
    th0 = threshold_for(cal, first_key, bk_mode)
    normalized = float(score / th0["score_threshold"]) if th0["score_threshold"] > 0 else np.nan
    coverage_ok = bool(all(coverage_passes))
    score_ok = bool(all(score_passes)) if verification_strategy == "single-window" else bool(any(score_passes))
    bk_ok = bool(all(b_passes) and all(k_passes))
    if not coverage_ok:
        decision, reason = "DEFER", "coverage_not_available"
    elif verification_strategy == "single-window":
        decision = "ACCEPT" if score_ok and bk_ok else "REJECT"
        reason = "single_window_pass" if decision == "ACCEPT" else "single_window_gate_fail"
    else:
        temporal_ok, _min_ov, _max_ov = wae.temporal_stats(specs, 0.2)
        if evidence >= 3.0 and temporal_ok and bk_ok:
            decision, reason = "ACCEPT", "window_aware_evidence_temporal_bk_pass"
        elif not any(score_passes):
            decision, reason = "REJECT", "window_aware_all_score_fail"
        else:
            decision, reason = "DEFER", "window_aware_insufficient_or_unstable"
    use_risk_defer = bk_mode == "bk_risk_defer" or force_bk_risk_defer
    if decision == "ACCEPT" and use_risk_defer and bk_mode != "no_bk":
        b_use = abs(b_hat - th0["b_center"]) / max(th0["b_threshold"], 1e-9)
        k_use = abs(k_hat - th0["k_center"]) / max(th0["k_threshold"], 1e-9)
        absorption_ratio = raw_rmse / max(score, 1e-9)
        if b_use >= 0.8 or k_use >= 0.8 or absorption_ratio >= 2.0:
            decision, reason = "DEFER", f"bk_risk_defer_b={b_use:.3g}_k={k_use:.3g}_ratio={absorption_ratio:.3g}"
    return EvalDecision(decision, reason, score, normalized, b_hat, k_hat, raw_rmse, bool(score_ok), bool(all(b_passes)), bool(all(k_passes)), coverage_ok)


def sample_residual_terms(t_rel: np.ndarray, residual_mode: str, ranges: dict[str, list[float]], rng: np.random.Generator) -> tuple[np.ndarray, float, float, float, float]:
    t0 = float(np.mean(t_rel))
    if residual_mode == "clean":
        return np.zeros(len(t_rel), dtype=float), 0.0, 0.0, 0.0, t0
    err = base.sample_error_params(ranges, rng)
    noise = rng.normal(0.0, err.sigma_hz, len(t_rel)) if err.sigma_hz > 0 else np.zeros(len(t_rel), dtype=float)
    return noise, float(err.b_hz), float(err.k_hz_s), float(err.sigma_hz), t0


def row_from_decision(
    *,
    case_id: str,
    attack_model: str,
    segment_rule: str,
    t_service_s: float,
    t_min_s: float,
    receiver_mode: str,
    sample: dict[str, Any],
    pass_id: str,
    segment_index: int,
    window_id: str,
    r_cell_km: float,
    alpha: float,
    l_step_km: float,
    rho: float,
    phi_deg: float,
    c_lat: float,
    c_lon: float,
    s_lat: float,
    s_lon: float,
    distance_to_center_km: float,
    coverage_valid: bool,
    station_id: str,
    station_strategy: str,
    station_separation_km: float,
    bk_mode: str,
    verification_strategy: str,
    evaluation_scope: str,
    doppler_reference_mode: str,
    evaluation_start_s: float,
    evaluation_end_s: float,
    segment_start_s: float,
    segment_end_s: float,
    decision: EvalDecision,
    hard_case_flag: bool,
    boundary_case_flag: bool,
    segment_count: int,
    segment_duration_s: float,
    mean_segment_duration_s: float,
    median_segment_duration_s: float,
    min_segment_duration_s: float,
    max_segment_duration_s: float,
    mean_g_speed_km_per_s: float,
    coverage_valid_fraction: float,
    along_offset_km: float,
    cross_offset_km: float,
    mean_abs_r_geo_hz: float,
    rmse_r_geo_hz: float,
    max_abs_r_geo_hz: float,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "attack_model": attack_model,
        "segment_rule": segment_rule,
        "T_service_s": float(t_service_s),
        "T_min_s": float(t_min_s),
        "receiver_mode": receiver_mode,
        "sample_group": sample["sample_group"],
        "target_sat_id": sample["target_sat_id"],
        "target_name": sample["target_name"],
        "attack_sat_id": sample["attack_sat_id"],
        "attack_name": sample["attack_name"],
        "pass_id": pass_id,
        "segment_index": int(segment_index),
        "window_id": window_id,
        "R_cell_km": float(r_cell_km),
        "alpha": float(alpha),
        "L_step_km": float(l_step_km),
        "rho": float(rho),
        "phi_deg": float(phi_deg),
        "C_lat": float(c_lat),
        "C_lon": float(c_lon),
        "S_lat": float(s_lat),
        "S_lon": float(s_lon),
        "distance_to_center_km": float(distance_to_center_km),
        "coverage_valid": bool(coverage_valid),
        "station_id": station_id,
        "station_strategy": station_strategy,
        "station_separation_km": float(station_separation_km),
        "bk_mode": bk_mode,
        "verification_strategy": verification_strategy,
        "evaluation_scope": evaluation_scope,
        "doppler_reference_mode": doppler_reference_mode,
        "evaluation_start_s": float(evaluation_start_s),
        "evaluation_end_s": float(evaluation_end_s),
        "segment_start_s": float(segment_start_s),
        "segment_end_s": float(segment_end_s),
        "b_hat_hz": float(decision.b_hat_hz),
        "k_hat_hz_per_s": float(decision.k_hat_hz_per_s),
        "abs_b_hat_hz": abs(float(decision.b_hat_hz)),
        "abs_k_hat_hz_per_s": abs(float(decision.k_hat_hz_per_s)),
        "normalized_score": float(decision.normalized_score),
        "residual_rmse_hz": float(decision.residual_rmse_hz),
        "raw_delta_rmse_hz": float(decision.raw_delta_rmse_hz),
        "decision": decision.decision,
        "accept_flag": bool(decision.decision == "ACCEPT"),
        "defer_flag": bool(decision.decision == "DEFER"),
        "reject_flag": bool(decision.decision == "REJECT"),
        "decision_reason": decision.reason,
        "score_gate_pass": bool(decision.score_gate_pass),
        "b_gate_pass": bool(decision.b_gate_pass),
        "k_gate_pass": bool(decision.k_gate_pass),
        "coverage_gate_pass": bool(decision.coverage_gate_pass),
        "hard_case_flag": bool(hard_case_flag),
        "boundary_case_flag": bool(boundary_case_flag),
        "segment_count": int(segment_count),
        "segment_duration_s": float(segment_duration_s),
        "mean_segment_duration_s": float(mean_segment_duration_s),
        "median_segment_duration_s": float(median_segment_duration_s),
        "min_segment_duration_s": float(min_segment_duration_s),
        "max_segment_duration_s": float(max_segment_duration_s),
        "mean_G_speed_km_per_s": float(mean_g_speed_km_per_s),
        "coverage_valid_fraction": float(coverage_valid_fraction),
        "along_track_offset_km": float(along_offset_km),
        "cross_track_offset_km": float(cross_offset_km),
        "mean_abs_r_geo_hz": float(mean_abs_r_geo_hz),
        "rmse_r_geo_hz": float(rmse_r_geo_hz),
        "max_abs_r_geo_hz": float(max_abs_r_geo_hz),
    }


def summarize_rates(df: pd.DataFrame, group_cols: list[str], table_name: str, extra: dict[str, str] | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for key, g in df.groupby(group_cols, dropna=False, sort=False):
        counts = g["decision"].value_counts()
        n = len(g)
        row = {
            "summary_table": table_name,
            **dict(zip(group_cols, key)),
            "total_cases": int(n),
            "accept_rate": float(counts.get("ACCEPT", 0) / n) if n else np.nan,
            "defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
            "reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
        }
        if extra:
            for out_name, source_col in extra.items():
                row[out_name] = float(g[source_col].mean()) if source_col in g.columns and len(g) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    m2_block = df[df["attack_model"].eq("M2_block")]
    tables = [
        summarize_rates(
            df,
            ["attack_model", "T_service_s", "sample_group", "bk_mode", "verification_strategy"],
            "Q2_attack_model_dwell_comparison",
            {"mean_normalized_score": "normalized_score", "mean_abs_k_hat": "abs_k_hat_hz_per_s"},
        ),
        summarize_rates(
            df[df["attack_model"].eq("M2_fast")],
            ["R_cell_km", "alpha", "sample_group", "bk_mode", "verification_strategy"],
            "Q1_M2_fast_segment_speed_context",
            {
                "mean_segment_count": "segment_count",
                "mean_segment_duration_s": "mean_segment_duration_s",
                "median_segment_duration_s": "median_segment_duration_s",
                "min_segment_duration_s": "min_segment_duration_s",
                "max_segment_duration_s": "max_segment_duration_s",
                "mean_distance_to_center_km": "distance_to_center_km",
            },
        ),
        summarize_rates(
            m2_block,
            ["segment_index", "T_service_s", "sample_group", "bk_mode", "verification_strategy"],
            "Q3_M2_block_segment_level",
            {
                "segment_accept_rate": "accept_flag",
                "segment_mean_score": "normalized_score",
                "segment_mean_abs_k_hat": "abs_k_hat_hz_per_s",
                "mean_segment_duration_s": "segment_duration_s",
            },
        ),
        summarize_rates(
            m2_block,
            ["rho", "T_service_s", "sample_group", "bk_mode"],
            "Q4_M2_block_rho_sensitivity",
            {"mean_distance_to_center_km": "distance_to_center_km"},
        ),
        summarize_rates(
            m2_block,
            ["bk_mode", "sample_group", "verification_strategy"],
            "Q5_M2_block_bk_ablation",
            {"mean_abs_b_hat_hz": "abs_b_hat_hz", "mean_abs_k_hat_hz_per_s": "abs_k_hat_hz_per_s"},
        ),
        summarize_rates(
            m2_block,
            ["verification_strategy", "sample_group", "bk_mode", "T_service_s"],
            "Q6_M2_block_window_aware_vs_single",
            {"hard_case_accept_count": "accept_flag", "mean_normalized_score": "normalized_score"},
        ),
        summarize_rates(
            m2_block,
            ["station_strategy", "station_separation_km", "sample_group", "bk_mode", "T_service_s"],
            "Q7_M2_block_multistation",
        ),
    ]
    return pd.concat([t for t in tables if not t.empty], ignore_index=True)


def heatmap_input(df: pd.DataFrame) -> pd.DataFrame:
    heat = df[df["receiver_mode"].eq("heatmap_mode")].copy()
    if heat.empty:
        return pd.DataFrame()
    rows = []
    group_cols = ["attack_model", "T_service_s", "R_cell_km", "alpha", "rho", "phi_deg", "sample_group", "bk_mode"]
    for key, g in heat.groupby(group_cols, dropna=False, sort=False):
        counts = g["decision"].value_counts()
        n = len(g)
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "along_track_offset_km": float(g["along_track_offset_km"].median()),
                "cross_track_offset_km": float(g["cross_track_offset_km"].median()),
                "accept_rate": float(counts.get("ACCEPT", 0) / n) if n else np.nan,
                "defer_rate": float(counts.get("DEFER", 0) / n) if n else np.nan,
                "reject_rate": float(counts.get("REJECT", 0) / n) if n else np.nan,
                "mean_normalized_score": float(g["normalized_score"].mean()),
            }
        )
    return pd.DataFrame(rows)


def plot_figures(df: pd.DataFrame, heat: pd.DataFrame, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    figs: list[Path] = []
    attack = df[df["station_id"].eq("S0")].copy()
    if not attack.empty:
        d = attack.groupby("attack_model", as_index=False)["accept_flag"].mean()
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.bar(d["attack_model"], d["accept_flag"], color=["#4c78a8", "#f58518", "#54a24b"][: len(d)])
        ax.set_ylabel("非目标样本误接受率")
        ax.set_title("Attack Model Comparison")
        ax.set_ylim(0, max(0.05, float(d["accept_flag"].max()) * 1.25))
        fig.tight_layout()
        path = outdir / "attack_model_comparison.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)
    m2 = attack[attack["attack_model"].eq("M2")]
    if not m2.empty:
        d = m2.groupby("rho", as_index=False)["accept_flag"].mean().sort_values("rho")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(d["rho"], d["accept_flag"], marker="o", color="#4c78a8")
        ax.set_xlabel("rho")
        ax.set_ylabel("非目标样本误接受率")
        ax.set_title("M2 Rho Sensitivity")
        fig.tight_layout()
        path = outdir / "rho_sensitivity.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)
        d = m2.groupby(["R_cell_km", "alpha"], as_index=False)["accept_flag"].mean()
        fig, ax = plt.subplots(figsize=(7, 4))
        for alpha, g in d.groupby("alpha"):
            ax.plot(g["R_cell_km"], g["accept_flag"], marker="o", label=f"alpha={alpha:g}")
        ax.set_xlabel("R_cell_km")
        ax.set_ylabel("非目标样本误接受率")
        ax.set_title("M2 R_cell / Alpha Sensitivity")
        ax.legend()
        fig.tight_layout()
        path = outdir / "rcell_alpha_sensitivity.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)
        d = m2.groupby("bk_mode", as_index=False)["accept_flag"].mean()
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(d["bk_mode"], d["accept_flag"], color="#72b7b2")
        ax.set_ylabel("非目标样本误接受率")
        ax.set_title("M2 b/k Ablation")
        ax.tick_params(axis="x", rotation=25)
        fig.tight_layout()
        path = outdir / "bk_ablation_segmented_service_center.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)
    if not heat.empty:
        h = heat[(heat["attack_model"].eq("M2")) & (heat["bk_mode"].eq("current_bk"))].copy()
        if h.empty:
            h = heat.copy()
        piv = h.groupby(["rho", "phi_deg"], as_index=False)["accept_rate"].mean().pivot(index="rho", columns="phi_deg", values="accept_rate")
        fig, ax = plt.subplots(figsize=(8, 4.5))
        im = ax.imshow(piv.to_numpy(float), aspect="auto", origin="lower", cmap="viridis")
        ax.set_xticks(range(len(piv.columns)))
        ax.set_xticklabels([f"{c:g}" for c in piv.columns])
        ax.set_yticks(range(len(piv.index)))
        ax.set_yticklabels([f"{r:g}" for r in piv.index])
        ax.set_xlabel("phi_deg")
        ax.set_ylabel("rho")
        ax.set_title("Heatmap: 非目标样本误接受率")
        fig.colorbar(im, ax=ax, label="非目标样本误接受率")
        fig.tight_layout()
        path = outdir / "heatmap_accept_rate.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)
    return figs


def write_report(args: argparse.Namespace, df: pd.DataFrame, summary: pd.DataFrame, heat: pd.DataFrame, figures: list[Path]) -> None:
    valid = df[df["station_id"].eq("S0")]
    model_rates = valid.groupby("attack_model")["accept_flag"].mean().reset_index() if not valid.empty else pd.DataFrame()
    m2_rates = valid[valid["attack_model"].eq("M2")].groupby("bk_mode")["accept_flag"].mean().reset_index() if not valid.empty else pd.DataFrame()
    text = f"""# Service-Area-First Segmented Service-Center Compensation Report

## 1. 实验目标

本文实现的是 controlled segmented service-center compensation simulation，不是真实 Starlink 调度复现。实验在真实 Starlink TLE、controlled pass 时间网格和受控服务区域变化假设下，重新计算 `F_A(t;S)`、`F_B(t;S)`、`F_A(t;C)`、`F_B(t;C)`，评估攻击方只能按服务区中心做 Doppler pre-compensation 时，Doppler residual verifier、window-aware accumulation、b/k gate 和多站一致性的边界。

## 2. 模型定义

几何频率基线记为 `F_X(t;x)`。攻击补偿统一写为：

```text
u(t) = F_A(t; C(t)) - F_B(t; C(t))
```

真实接收点 `S` 处的攻击观测为：

```text
y_atk(t;S) = F_B(t;S) + u(t) + b_env + k_env*(t-t0) + epsilon(t)
```

验证器对 claimed target A 计算 `delta_A(t;S)=y_atk(t;S)-F_A(t;S)`。几何残差部分为：

```text
r_geo(t;S) = F_B(t;S) + F_A(t;C_i) - F_B(t;C_i) - F_A(t;S)
```

当 `S=C_i` 时，`r_geo=0`，说明服务区中心附近最危险；当 `S` 远离 `C_i` 时，剩下的是 cell 内 differential Doppler mismatch。

## 3. M0 / M1 / M2 区别

- `M0`: fixed-C baseline，默认 `C0=G(t_mid)`，且独立于 `S`。
- `M1`: continuous moving-reference baseline，`C(t)=G(t)=P_sub^A(t)`，只作为极端动态参考点对照。
- `M2`: service-area-first segmented service-center model，先用 `G(t)` 和 `L_step=alpha*R_cell` 生成 `C_i/I_i`，再在服务区中放置或扫描接收点。

## 4. heatmap_mode 和 sequence_mode

- `heatmap_mode`: 单段空间热力图。对服务区中心按 `rho/phi` 扫描接收点，用于观察同一服务区内位置对误接受的影响。
- `sequence_mode`: 跨段、window-aware、多站实验。`S` 由 `C_ref=G(t_mid)` 生成后，在整个 pass 内保持固定。

## 5. 跨段 S 固定规则

`sequence_mode` 中不会每段重新放置接收机。每段只计算固定 `S` 到当前 `C_i` 的地表大圆距离，并据此标记 `coverage_valid`；覆盖无效时该窗口或序列输出 `DEFER`。

## 6. 多站共用同一个 C_i(t) 和 u(t)

多站策略先为同一个 A/B/pass 生成全局 `C_i(t)` 和同一个 `u(t)`，然后 S0/S1/S2 分别接收并各自计算 residual。脚本没有为每个站生成不同的 `C_i` 或 `u_i(t)`。

## 7. smoke / main 参数

- 本次运行 preset: `{args.preset}`。
- `R_cell_km`: `{args.r_cell_km}`。
- `alpha`: `{args.alpha}`。
- `rho`: `{args.rho}`。
- `phi_deg`: `{args.phi_deg}`。
- `sample_group`: `{args.sample_groups}`。
- `bk_mode`: `{args.bk_modes}`。
- `verification_strategy`: `{args.verification_strategies}`。
- `max_targets`: `{args.max_targets}`，`max_attackers_per_group`: `{args.max_attackers_per_group}`。

## 8. 主要结果表

### 三模型总体对比

{model_rates.to_markdown(index=False) if not model_rates.empty else "无可用结果。"}

### M2 b/k 消融

{m2_rates.to_markdown(index=False) if not m2_rates.empty else "无可用结果。"}

完整汇总表见 `{args.summary_output.as_posix()}`，热力图输入表见 `{args.heatmap_output.as_posix()}`。

## 9. 风险点和表述边界

本文构造的是受控的服务区域变化假设。`G(t)=P_sub^A(t)` 只是 coverage-center trajectory 的简化生成规则，不表示真实 Starlink beam center 或真实服务区中心必然等于星下点。`M1` 是极端动态参考点对照，不是真实调度模型。非目标样本误接受率只表示受控仿真下非目标样本被误判为 `ACCEPT` 的比例，不等于真实世界攻击成功率。`b_env/k_env/noise` 来自经验误差模型，不是攻击者精确可控参数。`no_bk` 表示不允许 b/k 吸收 residual，是最严格基线，不是无门限。

## 10. 下一步建议

1. 放大 `max_targets` 和每组 attacker 数量，检查不同 pass 几何下的稳定性。
2. 对 M2 的 segment boundary 附近增加更细的 `rho/phi` 和时间窗口扫描。
3. 将本轮 `coverage_valid` diagnostic 升级为可配置前置 gate。
4. 后续再引入主动补偿攻击下的多接收端空间一致性约束。

## 11. 生成文件

- Dataset: `{args.dataset_output.as_posix()}`
- Summary: `{args.summary_output.as_posix()}`
- Heatmap input: `{args.heatmap_output.as_posix()}`
- Report: `{args.report_output.as_posix()}`
- Figures: `{", ".join(p.as_posix() for p in figures)}`
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def build_segment_audit(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["attack_model", "segment_rule", "R_cell_km", "alpha", "T_service_s", "T_min_s", "pass_id"]
    rows: list[dict[str, Any]] = []
    for key, g in df.groupby(group_cols, dropna=False, sort=False):
        rows.append(
            {
                **dict(zip(group_cols, key)),
                "segment_count": int(float(g["segment_count"].median())),
                "mean_segment_duration_s": float(g["mean_segment_duration_s"].median()),
                "median_segment_duration_s": float(g["median_segment_duration_s"].median()),
                "min_segment_duration_s": float(g["min_segment_duration_s"].median()),
                "max_segment_duration_s": float(g["max_segment_duration_s"].median()),
                "mean_L_step_km": float(g["L_step_km"].mean()),
                "mean_G_speed_km_per_s": float(g["mean_G_speed_km_per_s"].mean()),
            }
        )
    return pd.DataFrame(rows)


def model_label(row: pd.Series) -> str:
    if str(row.get("attack_model")) == "M2_block":
        return f"M2_block_{int(float(row.get('T_service_s', 0)))}s"
    if str(row.get("attack_model")) == "M2_hybrid":
        return f"M2_hybrid_{int(float(row.get('T_min_s', 0)))}s"
    return str(row.get("attack_model"))


def plot_figures(df: pd.DataFrame, heat: pd.DataFrame, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    figs: list[Path] = []
    audit = build_segment_audit(df)
    attack = df[df["station_id"].eq("S0")].copy()
    ylabel = "非目标样本误接受率"

    if not audit.empty:
        d = audit[audit["attack_model"].isin(["M2_fast", "M2_block"])].copy()
        if not d.empty:
            fig, ax = plt.subplots(figsize=(8, 4.5))
            for model, g in d.groupby("attack_model"):
                ax.scatter(g["R_cell_km"], g["mean_segment_duration_s"], label=model, alpha=0.8)
            ax.axhline(30.0, color="black", linestyle="--", linewidth=1.0, label="30s reference")
            ax.set_xlabel("R_cell_km")
            ax.set_ylabel("mean_segment_duration_s")
            ax.set_title("Segment Duration Audit")
            ax.legend()
            fig.tight_layout()
            path = outdir / "segment_duration_audit.png"
            fig.savefig(path, dpi=180)
            plt.close(fig)
            figs.append(path)

    if not attack.empty:
        d = attack.groupby(["attack_model", "T_service_s"], as_index=False)["accept_flag"].mean()
        d["label"] = d.apply(model_label, axis=1)
        d = d.drop_duplicates("label").sort_values(["attack_model", "T_service_s"])
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(d["label"], d["accept_flag"], color="#4c78a8")
        ax.set_ylabel(ylabel)
        ax.set_title("M0 / M1 / M2-fast / M2-block Comparison")
        ax.tick_params(axis="x", rotation=25)
        ax.set_ylim(0, max(0.05, float(d["accept_flag"].max()) * 1.25))
        fig.tight_layout()
        path = outdir / "attack_model_dwell_comparison.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)

    m2_block = attack[attack["attack_model"].eq("M2_block")]
    if not m2_block.empty:
        d = m2_block.groupby("T_service_s", as_index=False)["accept_flag"].mean().sort_values("T_service_s")
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(d["T_service_s"], d["accept_flag"], marker="o", color="#4c78a8")
        ax.set_xlabel("T_service_s")
        ax.set_ylabel(ylabel)
        ax.set_title("M2-block T_service Sensitivity")
        fig.tight_layout()
        path = outdir / "tservice_sensitivity.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)

        d = m2_block.groupby(["rho", "T_service_s"], as_index=False)["accept_flag"].mean()
        fig, ax = plt.subplots(figsize=(7, 4))
        for t_service, g in d.groupby("T_service_s"):
            ax.plot(g["rho"], g["accept_flag"], marker="o", label=f"T={t_service:g}s")
        ax.set_xlabel("rho")
        ax.set_ylabel(ylabel)
        ax.set_title("M2-block Rho Sensitivity")
        ax.legend()
        fig.tight_layout()
        path = outdir / "rho_sensitivity_m2_block.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)

        d = m2_block.groupby("bk_mode", as_index=False)["accept_flag"].mean()
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(d["bk_mode"], d["accept_flag"], color="#72b7b2")
        ax.set_ylabel(ylabel)
        ax.set_title("M2-block b/k Ablation")
        ax.tick_params(axis="x", rotation=25)
        fig.tight_layout()
        path = outdir / "bk_ablation_m2_block.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)

        d = m2_block[m2_block["verification_strategy"].isin(["single-window", "window-aware accumulation"])]
        d = d.groupby(["verification_strategy", "T_service_s"], as_index=False)["accept_flag"].mean()
        fig, ax = plt.subplots(figsize=(7, 4))
        for strategy, g in d.groupby("verification_strategy"):
            ax.plot(g["T_service_s"], g["accept_flag"], marker="o", label=strategy)
        ax.set_xlabel("T_service_s")
        ax.set_ylabel(ylabel)
        ax.set_title("M2-block Window-aware vs Single-window")
        ax.legend()
        fig.tight_layout()
        path = outdir / "window_aware_vs_single_m2_block.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        figs.append(path)

    return figs


def write_report(args: argparse.Namespace, df: pd.DataFrame, summary: pd.DataFrame, heat: pd.DataFrame, figures: list[Path]) -> None:
    valid = df[df["station_id"].eq("S0")].copy()
    audit = build_segment_audit(df)
    model_rates = valid.groupby(["attack_model", "T_service_s"], as_index=False)["accept_flag"].mean() if not valid.empty else pd.DataFrame()
    if not model_rates.empty:
        model_rates["model_label"] = model_rates.apply(model_label, axis=1)
        model_rates = model_rates[["model_label", "accept_flag"]].drop_duplicates("model_label")
    m2_fast_audit = audit[audit["attack_model"].eq("M2_fast")].copy()
    m2_block_rates = valid[valid["attack_model"].eq("M2_block")].groupby("T_service_s", as_index=False)["accept_flag"].mean() if not valid.empty else pd.DataFrame()
    m2_block_bk = valid[valid["attack_model"].eq("M2_block")].groupby("bk_mode", as_index=False)["accept_flag"].mean() if not valid.empty else pd.DataFrame()
    m2_block_window = valid[valid["attack_model"].eq("M2_block")].groupby("verification_strategy", as_index=False)["accept_flag"].mean() if not valid.empty else pd.DataFrame()

    fast_mean = float(m2_fast_audit["mean_segment_duration_s"].mean()) if not m2_fast_audit.empty else float("nan")
    fast_note = (
        "M2_fast 的平均段长低于 30s，上一轮 M2 更接近快速离散 moving-reference，不能直接代表多个较长 fixed-C 服务区块拼接。"
        if np.isfinite(fast_mean) and fast_mean < 30.0
        else "M2_fast 的平均段长未明显低于 30s，但仍应与 dwell-time-controlled M2_block 分开解释。"
    )

    text = f"""# Segmented Service-Center Dwell Experiment Report

## 1. 实验目标

本文仍是 controlled segmented service-center compensation simulation，不是真实 Starlink beam scheduling / service cell binding / handover policy / 无线资源调度复现。本轮目标是复核上一轮 M2 是否切换过快，并新增 dwell-time-controlled `M2_block`，评估较长服务区驻留时间下的分段服务中心补偿边界。

## 2. 模型定义

统一几何频率基线为 `F_X(t;x)`，补偿仍为：

```text
u(t) = F_A(t; C(t)) - F_B(t; C(t))
```

攻击观测为：

```text
y_atk(t;S) = F_B(t;S) + u(t) + b_env + k_env*(t-t0) + epsilon(t)
```

验证 residual 为 `delta_A(t;S)=y_atk(t;S)-F_A(t;S)`，几何残差为：

```text
r_geo(t;S) = F_B(t;S) + F_A(t;C(t)) - F_B(t;C(t)) - F_A(t;S)
```

当某段中 `S=C_i` 时，`r_geo=0`；当 `S` 偏离 `C_i` 时，体现 cell 内 differential Doppler mismatch。

## 3. M0 / M1 / M2-fast / M2-block

- `M0`: fixed-C baseline，`C(t)=C0`，整段固定。
- `M1`: continuous moving-reference baseline，`C(t)=G(t)=P_sub^A(t)`，只作为极端动态对照，不称为 upper bound。
- `M2_fast`: coverage-track-driven fast segmented service-center，即上一轮 M2，按 `L_step=alpha*R_cell` 快速分段更新。
- `M2_block`: dwell-time-controlled segmented service-center，每个 `C_i=G(t_i)` 固定持续 `T_service`，更接近“多个 fixed-C 服务区块按顺序拼接”的受控模型。
- `M2_hybrid`: 可选模型，空间步长和最小驻留时间同时满足才切换；本轮默认不跑。

`M2_block` 不是真实 Starlink 调度；`T_service` 只是服务区驻留时间敏感性参数，`R_cell` 只是服务区尺度参数，二者均不声称等同真实 Starlink cell radius 或 handover period。

## 4. M2-fast 段长审计

上一轮 M2_fast 采用空间步长 `L_step=alpha R_cell` 触发服务中心更新。如果生成的 `mean_segment_duration_s` 较短，则它更接近快速离散 moving-reference，而不是多个较长 fixed-C 服务区块。

本轮 M2_fast mean_segment_duration_s 平均值：`{fast_mean:.3f}` s。

{fast_note}

段长审计表输出到 `{args.segment_audit_output.as_posix()}`。

## 5. 接收点和多站约束

`heatmap_mode` 只用于单段空间热力图，可以围绕当前 `C_i` 放置接收点。`sequence_mode` 用于跨段 / window-aware / 多站实验，`S` 从 `C_ref=G(t_mid)` 生成后在整个 pass 内保持固定。多站实验对同一个 A/B/pass 先生成全局 `C(t)` 和同一个 `u(t)`，再让多个站分别接收；脚本没有为每站定制 `C_i(t)` 或 `u_i(t)`。

## 6. 本轮参数

- preset: `{args.preset}`
- attack_model: `{args.attack_models}`
- R_cell_km: `{args.r_cell_km}`
- alpha: `{args.alpha}`
- T_service_s: `{args.t_service_s}`
- rho: `{args.rho}`
- phi_deg: `{args.phi_deg}`
- sample_group: `{args.sample_groups}`
- bk_mode: `{args.bk_modes}`
- verification_strategy: `{args.verification_strategies}`
- max_targets: `{args.max_targets}`
- max_attackers_per_group: `{args.max_attackers_per_group}`
- max_heatmap_segments: `{args.max_heatmap_segments}`

## 7. 主要结果

### 模型误接受率对比

{model_rates.to_markdown(index=False) if not model_rates.empty else "无可用结果。"}

### M2_block T_service 趋势

{m2_block_rates.to_markdown(index=False) if not m2_block_rates.empty else "无可用结果。"}

### M2_block b/k 消融

{m2_block_bk.to_markdown(index=False) if not m2_block_bk.empty else "无可用结果。"}

### M2_block single-window vs window-aware / multi-station

{m2_block_window.to_markdown(index=False) if not m2_block_window.empty else "无可用结果。"}

完整 summary 输出到 `{args.summary_output.as_posix()}`；heatmap input 输出到 `{args.heatmap_output.as_posix()}`。

## 8. 风险点和表述边界

非目标样本误接受率只表示受控仿真下非目标样本被误判为 `ACCEPT` 的比例，不等于真实世界攻击成功率。`b_env/k_env/noise` 来自经验误差模型，不是攻击者精确可控参数。`no_bk` 表示不允许 b/k 吸收 residual，是最严格基线，不是无门限。不能写成真实 Starlink 每 30/60/120 秒切换服务区，也不能把 `T_service` 写成真实 handover 周期。

## 9. 下一步建议

1. 放大 `max_targets` 和每组 attacker 数量，复核 M2_block 在更多 pass 几何下的稳定性。
2. 对 segment boundary 附近的 `rho/phi` 做更密集扫描。
3. 将 `coverage_valid` 从 diagnostic 升级为可配置前置 gate。
4. 后续再进入主动补偿攻击下的多接收端空间一致性约束。

## 10. 生成文件

- Dataset: `{args.dataset_output.as_posix()}`
- Summary: `{args.summary_output.as_posix()}`
- Segment audit: `{args.segment_audit_output.as_posix()}`
- Heatmap input: `{args.heatmap_output.as_posix()}`
- Report: `{args.report_output.as_posix()}`
- Figures: `{", ".join(p.as_posix() for p in figures)}`
"""
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.write_text(text, encoding="utf-8")


def append_work_log(args: argparse.Namespace, df: pd.DataFrame, summary: pd.DataFrame, figures: list[Path]) -> None:
    path = Path("logs/work_log.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    model_accept = df[df["station_id"].eq("S0")].groupby("attack_model")["accept_flag"].mean().to_dict() if not df.empty else {}
    command = (
        "python scripts/run_segmented_service_center_compensation.py "
        f"--preset {args.preset} "
        f"--max-targets {args.max_targets} "
        f"--max-attackers-per-group {args.max_attackers_per_group} "
        f"--num-benign-sims {args.num_benign_sims} "
        f"--max-heatmap-segments {args.max_heatmap_segments} "
        "--overwrite"
    )
    text = f"""
## {now} - Service-Area-First Segmented Service-Center Compensation

### A. 本轮目标

实现 controlled segmented service-center compensation simulation，重新计算服务中心/接收点几何 Doppler 与攻击 residual，输出 dataset、summary、heatmap input、报告和图表。

### B. 实际操作

- 新增 `scripts/run_segmented_service_center_compensation.py`。
- 使用 controlled_starlink mode，`observation_id=null`。
- 复用现有 Starlink TLE、controlled pass candidate library、Skyfield Doppler 计算、b/k fitting 和 window-aware helper。
- 实现 M0 / M1 / M2，区分 `heatmap_mode` 与 `sequence_mode`，并保证多站共用同一个 `C_i(t)` 和 `u(t)`。

### C. 新增/修改文件

- `{args.dataset_output.as_posix()}`
- `{args.summary_output.as_posix()}`
- `{args.heatmap_output.as_posix()}`
- `{args.report_output.as_posix()}`
- `{args.figures_dir.as_posix()}/`

### D. 运行命令

```bash
{command}
```

### E. 结果摘要

- dataset rows: `{len(df)}`
- summary rows: `{len(summary)}`
- figures: `{len(figures)}`
- S0 model-level non-target false accept rates: `{model_accept}`

### F. 问题与下一步

- 当前是 controlled segmented service-center compensation simulation，不是真实 Starlink 调度复现。
- 默认运行规模受 `max_targets` 和 `max_attackers_per_group` 控制；后续可放大目标数与 attacker 数量。
- 下一步建议检查 segment boundary 附近样本，并把 coverage diagnostic 升级为可配置前置约束。
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def run(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[Path]]:
    setup_grid(args)
    check_outputs(args)
    selection, library, orbit_cfg, tle, ranges = load_inputs(args)
    samples = select_attack_samples(selection, library, tle, args.sample_groups, int(args.max_attackers_per_group), args.hard_cases)
    ts = load.timescale()
    rng = np.random.default_rng(args.seed)
    freq_hz = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    rows: list[dict[str, Any]] = []
    geo_rows: list[dict[str, Any]] = []
    fixed_geo_cache: dict[tuple[str, float, float], tuple[np.ndarray, np.ndarray]] = {}
    local_fixed_geo_cache: dict[tuple[str, str, float, float, int, int], tuple[np.ndarray, np.ndarray]] = {}
    local_cal_cache: dict[tuple[str, int, int], dict[str, dict[str, float]]] = {}

    for sample in samples.to_dict("records"):
        target_id = str(sample["target_sat_id"])
        attack_id = str(sample["attack_sat_id"])
        sat_a = tle[target_id]["sat"]
        sat_b = tle[attack_id]["sat"]
        target_geo = base.target_geo_from_library(library, target_id)
        require_columns(target_geo, ["t_abs_utc", "t_rel_s"], "target geometry")
        times = [base.parse_utc(v) for v in target_geo["t_abs_utc"].astype(str)]
        t_rel = target_geo["t_rel_s"].to_numpy(float)
        step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        pass_id = f"{target_id}_{str(target_geo['t_abs_utc'].iloc[0]).replace(':', '').replace('-', '')}"
        g_lat, g_lon, g_alt = compute_subpoint_series(sat_a, times, ts)
        mid = len(times) // 2
        g_step_dist = distance_km(g_lat[1:], g_lon[1:], 0.0, 0.0) if len(g_lat) < 2 else np.array(
            [
                float(distance_km(np.array([g_lat[i]]), np.array([g_lon[i]]), float(g_lat[i - 1]), float(g_lon[i - 1]))[0])
                for i in range(1, len(g_lat))
            ],
            dtype=float,
        )
        mean_g_speed = float(np.mean(g_step_dist) / max(step_s, 1e-9)) if len(g_step_dist) else 0.0
        cal = calibration_for_trel(t_rel, ranges, args.seed + int(target_id), int(args.num_benign_sims))
        terms = sample_residual_terms(t_rel, args.residual_mode, ranges, rng)
        noise, b_env, k_env, _sigma, t0 = terms

        for r_cell in args.r_cell_km:
            for alpha in args.alpha:
                l_step = float(alpha) * float(r_cell)
                for attack_model in args.attack_models:
                    model_t_services = args.t_service_s if attack_model == "M2_block" else [0.0]
                    model_t_mins = args.t_min_s if attack_model == "M2_hybrid" else [0.0]
                    for t_service_s in model_t_services:
                        for t_min_s in model_t_mins:
                            track = center_track(attack_model, g_lat, g_lon, g_alt, t_rel, float(r_cell), float(alpha), float(t_service_s), float(t_min_s))
                            f_a_c = geo_curve_moving(sat_a, track.lat_deg, track.lon_deg, track.alt_m, times, ts, freq_hz, args.moving_reference_diff_step_s)
                            f_b_c = geo_curve_moving(sat_b, track.lat_deg, track.lon_deg, track.alt_m, times, ts, freq_hz, args.moving_reference_diff_step_s)
                            u_t = f_a_c - f_b_c
                            segment_count = len(track.segment_starts)
                            durations = np.asarray([(track.segment_ends[i] - track.segment_starts[i] + 1) * step_s for i in range(segment_count)], dtype=float)
                            mean_segment_duration = float(np.mean(durations)) if len(durations) else float(np.max(t_rel) - np.min(t_rel))
                            median_segment_duration = float(np.median(durations)) if len(durations) else mean_segment_duration
                            min_segment_duration = float(np.min(durations)) if len(durations) else mean_segment_duration
                            max_segment_duration = float(np.max(durations)) if len(durations) else mean_segment_duration

                            for receiver_mode in args.receiver_modes:
                                for rho in args.rho:
                                    for phi in args.phi_deg:
                                        along_km, cross_km = signed_offsets_km(float(rho), float(phi), float(r_cell))
                                        if receiver_mode == "heatmap_mode":
                                            segmented = attack_model in {"M2_fast", "M2_block", "M2_hybrid"}
                                            raw_center_indices = track.segment_starts if segmented else [mid]
                                            center_indices = representative_indices(raw_center_indices, int(args.max_heatmap_segments))
                                            strategy_list = [s for s in args.verification_strategies if not s.startswith("multi-station")]
                                            if args.evaluation_scope == "segment_local":
                                                strategy_list = [s for s in strategy_list if s == "single-window"]
                                                if not strategy_list:
                                                    fail("heatmap segment_local requires verification_strategy=single-window")
                                        else:
                                            center_indices = [mid]
                                            strategy_list = list(args.verification_strategies)
                                        for center_i in center_indices:
                                            if receiver_mode == "heatmap_mode":
                                                center_seg_idx = int(track.segment_index[center_i])
                                                seg_start_i = int(track.segment_starts[center_seg_idx])
                                                seg_end_i = int(track.segment_ends[center_seg_idx])
                                            else:
                                                center_seg_idx = -1
                                                seg_start_i = 0
                                                seg_end_i = len(t_rel) - 1
                                            if receiver_mode == "sequence_mode":
                                                s0_lat, s0_lon = destination(float(g_lat[mid]), float(g_lon[mid]), float(rho) * float(r_cell), float(phi))
                                            else:
                                                s0_lat, s0_lon = destination(float(track.lat_deg[center_i]), float(track.lon_deg[center_i]), float(rho) * float(r_cell), float(phi))
                                            s1_lat, s1_lon = destination(s0_lat, s0_lon, float(args.station_separation_km), float(args.station_bearing_deg))
                                            s2_lat, s2_lon = destination(s0_lat, s0_lon, float(args.station_separation_km), (float(args.station_bearing_deg) + 90.0) % 360.0)
                                            needs_multi_station = any(s.startswith("multi-station") for s in strategy_list)
                                            station_defs = {"S0": (s0_lat, s0_lon)}
                                            if needs_multi_station:
                                                station_defs["S1"] = (s1_lat, s1_lon)
                                                station_defs["S2"] = (s2_lat, s2_lon)
                                            station_payload: dict[str, dict[str, Any]] = {}
                                            for sid, (s_lat, s_lon) in station_defs.items():
                                                use_segment_local = (
                                                    receiver_mode == "heatmap_mode"
                                                    and args.evaluation_scope == "segment_local"
                                                    and args.doppler_reference_mode == "fixed_site_segment_center"
                                                )
                                                if use_segment_local:
                                                    eval_slice = slice(seg_start_i, seg_end_i + 1)
                                                    eval_times = times[seg_start_i : seg_end_i + 1]
                                                    eval_t_rel = t_rel[eval_slice]
                                                    eval_noise = noise[eval_slice]
                                                    c_eval_lat = float(track.lat_deg[center_i])
                                                    c_eval_lon = float(track.lon_deg[center_i])
                                                    center_key_a = (target_id, "center", round(c_eval_lat, 7), round(c_eval_lon, 7), seg_start_i, seg_end_i)
                                                    center_key_b = (attack_id, "center", round(c_eval_lat, 7), round(c_eval_lon, 7), seg_start_i, seg_end_i)
                                                    site_key_a = (target_id, sid, round(float(s_lat), 7), round(float(s_lon), 7), seg_start_i, seg_end_i)
                                                    site_key_b = (attack_id, sid, round(float(s_lat), 7), round(float(s_lon), 7), seg_start_i, seg_end_i)
                                                    if center_key_a not in local_fixed_geo_cache:
                                                        local_fixed_geo_cache[center_key_a] = geo_curve_fixed(sat_a, c_eval_lat, c_eval_lon, 0.0, eval_times, ts, freq_hz, step_s)
                                                    if center_key_b not in local_fixed_geo_cache:
                                                        local_fixed_geo_cache[center_key_b] = geo_curve_fixed(sat_b, c_eval_lat, c_eval_lon, 0.0, eval_times, ts, freq_hz, step_s)
                                                    if site_key_a not in local_fixed_geo_cache:
                                                        local_fixed_geo_cache[site_key_a] = geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, eval_times, ts, freq_hz, step_s)
                                                    if site_key_b not in local_fixed_geo_cache:
                                                        local_fixed_geo_cache[site_key_b] = geo_curve_fixed(sat_b, s_lat, s_lon, 0.0, eval_times, ts, freq_hz, step_s)
                                                    f_a_c_eval, _elev_a_c = local_fixed_geo_cache[center_key_a]
                                                    f_b_c_eval, _elev_b_c = local_fixed_geo_cache[center_key_b]
                                                    f_a_s_eval, _elev_a_s = local_fixed_geo_cache[site_key_a]
                                                    f_b_s_eval, _elev_b_s = local_fixed_geo_cache[site_key_b]
                                                    u_eval = f_a_c_eval - f_b_c_eval
                                                    y_atk_eval = f_b_s_eval + u_eval + b_env + k_env * (eval_t_rel - t0) + eval_noise
                                                    dist_series = distance_km(
                                                        np.full(len(eval_t_rel), c_eval_lat, dtype=float),
                                                        np.full(len(eval_t_rel), c_eval_lon, dtype=float),
                                                        s_lat,
                                                        s_lon,
                                                    )
                                                    coverage_mask = dist_series <= float(r_cell) + 1e-9
                                                    r_geo_eval = f_b_s_eval + f_a_c_eval - f_b_c_eval - f_a_s_eval
                                                    local_cal_key = (target_id, seg_start_i, seg_end_i)
                                                    if local_cal_key not in local_cal_cache:
                                                        local_cal_cache[local_cal_key] = calibration_for_trel(
                                                            eval_t_rel,
                                                            ranges,
                                                            args.seed + int(target_id) + int(center_seg_idx),
                                                            int(args.num_benign_sims),
                                                        )
                                                    geo_rows.append(
                                                        {
                                                            "attack_model": attack_model,
                                                            "segment_rule": track.segment_rule,
                                                            "T_service_s": float(t_service_s),
                                                            "receiver_mode": receiver_mode,
                                                            "evaluation_scope": args.evaluation_scope,
                                                            "doppler_reference_mode": args.doppler_reference_mode,
                                                            "sample_group": sample["sample_group"],
                                                            "target_sat_id": target_id,
                                                            "attack_sat_id": attack_id,
                                                            "pass_id": pass_id,
                                                            "segment_index": center_seg_idx,
                                                            "R_cell_km": float(r_cell),
                                                            "alpha": float(alpha),
                                                            "rho": float(rho),
                                                            "phi_deg": float(phi),
                                                            "C_lat": c_eval_lat,
                                                            "C_lon": c_eval_lon,
                                                            "S_lat": float(s_lat),
                                                            "S_lon": float(s_lon),
                                                            "distance_to_center_km": float(dist_series[0]) if len(dist_series) else np.nan,
                                                            "evaluation_start_s": float(eval_t_rel[0]) if len(eval_t_rel) else np.nan,
                                                            "evaluation_end_s": float(eval_t_rel[-1]) if len(eval_t_rel) else np.nan,
                                                            "segment_start_s": float(t_rel[seg_start_i]),
                                                            "segment_end_s": float(t_rel[seg_end_i]),
                                                            "point_count": int(len(eval_t_rel)),
                                                            "coverage_valid_fraction": float(np.mean(coverage_mask)) if len(coverage_mask) else np.nan,
                                                            "mean_abs_r_geo_hz": float(np.mean(np.abs(r_geo_eval))) if len(r_geo_eval) else np.nan,
                                                            "rmse_r_geo_hz": float(np.sqrt(np.mean(r_geo_eval**2))) if len(r_geo_eval) else np.nan,
                                                            "max_abs_r_geo_hz": float(np.max(np.abs(r_geo_eval))) if len(r_geo_eval) else np.nan,
                                                        }
                                                    )
                                                    station_payload[sid] = {
                                                        "lat": s_lat,
                                                        "lon": s_lon,
                                                        "f_a_s": f_a_s_eval,
                                                        "y_atk": y_atk_eval,
                                                        "t_rel": eval_t_rel,
                                                        "coverage_mask": coverage_mask,
                                                        "cal": local_cal_cache[local_cal_key],
                                                        "distance_mean": float(np.mean(dist_series)),
                                                        "coverage_fraction": float(np.mean(coverage_mask)) if len(coverage_mask) else 0.0,
                                                        "evaluation_start_s": float(eval_t_rel[0]) if len(eval_t_rel) else np.nan,
                                                        "evaluation_end_s": float(eval_t_rel[-1]) if len(eval_t_rel) else np.nan,
                                                        "segment_start_s": float(t_rel[seg_start_i]),
                                                        "segment_end_s": float(t_rel[seg_end_i]),
                                                        "mean_abs_r_geo_hz": float(np.mean(np.abs(r_geo_eval))) if len(r_geo_eval) else np.nan,
                                                        "rmse_r_geo_hz": float(np.sqrt(np.mean(r_geo_eval**2))) if len(r_geo_eval) else np.nan,
                                                        "max_abs_r_geo_hz": float(np.max(np.abs(r_geo_eval))) if len(r_geo_eval) else np.nan,
                                                    }
                                                else:
                                                    key_a = (target_id, round(float(s_lat), 7), round(float(s_lon), 7))
                                                    key_b = (attack_id, round(float(s_lat), 7), round(float(s_lon), 7))
                                                    if key_a not in fixed_geo_cache:
                                                        fixed_geo_cache[key_a] = geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, times, ts, freq_hz, step_s)
                                                    if key_b not in fixed_geo_cache:
                                                        fixed_geo_cache[key_b] = geo_curve_fixed(sat_b, s_lat, s_lon, 0.0, times, ts, freq_hz, step_s)
                                                    f_a_s, _elev_a = fixed_geo_cache[key_a]
                                                    f_b_s, _elev_b = fixed_geo_cache[key_b]
                                                    y_atk = f_b_s + u_t + b_env + k_env * (t_rel - t0) + noise
                                                    dist_series = distance_km(np.asarray(track.lat_deg), np.asarray(track.lon_deg), s_lat, s_lon)
                                                    coverage_mask = dist_series <= float(r_cell) + 1e-9
                                                    r_geo_full = f_b_s + f_a_c - f_b_c - f_a_s
                                                    station_payload[sid] = {
                                                        "lat": s_lat,
                                                        "lon": s_lon,
                                                        "f_a_s": f_a_s,
                                                        "y_atk": y_atk,
                                                        "t_rel": t_rel,
                                                        "coverage_mask": coverage_mask,
                                                        "cal": cal,
                                                        "distance_mean": float(np.mean(dist_series)),
                                                        "coverage_fraction": float(np.mean(coverage_mask)),
                                                        "evaluation_start_s": float(t_rel[0]),
                                                        "evaluation_end_s": float(t_rel[-1]),
                                                        "segment_start_s": float(t_rel[seg_start_i]),
                                                        "segment_end_s": float(t_rel[seg_end_i]),
                                                        "mean_abs_r_geo_hz": float(np.mean(np.abs(r_geo_full))),
                                                        "rmse_r_geo_hz": float(np.sqrt(np.mean(r_geo_full**2))),
                                                        "max_abs_r_geo_hz": float(np.max(np.abs(r_geo_full))),
                                                    }
                                            for verification_strategy in strategy_list:
                                                is_multi = verification_strategy.startswith("multi-station")
                                                station_strategy = "multi-station" if is_multi else "single-station"
                                                for bk_mode in args.bk_modes:
                                                    if is_multi and receiver_mode == "heatmap_mode":
                                                        continue
                                                    station_decisions: dict[str, EvalDecision] = {}
                                                    station_ids = ["S0", "S1", "S2"] if is_multi else ["S0"]
                                                    for sid in station_ids:
                                                        payload = station_payload[sid]
                                                        local_strategy = "window-aware accumulation" if "window-aware" in verification_strategy else "single-window"
                                                        station_decisions[sid] = evaluate_single_station(
                                                            y_obs=payload["y_atk"],
                                                            f_geo_a=payload["f_a_s"],
                                                            t_rel=payload["t_rel"],
                                                            coverage_mask=payload["coverage_mask"],
                                                            cal=payload["cal"],
                                                            bk_mode=bk_mode,
                                                            verification_strategy=local_strategy,
                                                            force_bk_risk_defer=verification_strategy == "multi-station + bk-risk-defer",
                                                        )
                                                    if is_multi:
                                                        decisions = [station_decisions[sid].decision for sid in station_ids]
                                                        if verification_strategy == "multi-station all-accept":
                                                            final_decision = "ACCEPT" if all(d == "ACCEPT" for d in decisions) else "REJECT" if any(d == "REJECT" for d in decisions) else "DEFER"
                                                        else:
                                                            final_decision = "ACCEPT" if all(d == "ACCEPT" for d in decisions) else "DEFER" if any(d == "DEFER" for d in decisions) else "REJECT"
                                                        final_reason = f"{verification_strategy}:S0={decisions[0]}_S1={decisions[1]}_S2={decisions[2]}"
                                                        base_dec = station_decisions["S0"]
                                                        agg_dec = EvalDecision(
                                                            final_decision,
                                                            final_reason,
                                                            base_dec.residual_rmse_hz,
                                                            base_dec.normalized_score,
                                                            base_dec.b_hat_hz,
                                                            base_dec.k_hat_hz_per_s,
                                                            base_dec.raw_delta_rmse_hz,
                                                            all(d.score_gate_pass for d in station_decisions.values()),
                                                            all(d.b_gate_pass for d in station_decisions.values()),
                                                            all(d.k_gate_pass for d in station_decisions.values()),
                                                            all(d.coverage_gate_pass for d in station_decisions.values()),
                                                        )
                                                        output_station_ids = ["S0"]
                                                    else:
                                                        agg_dec = station_decisions["S0"]
                                                        output_station_ids = ["S0"]
                                                    for sid in output_station_ids:
                                                        payload = station_payload[sid]
                                                        case_id = "_".join(
                                                            [
                                                                attack_model,
                                                                f"T{float(t_service_s):g}",
                                                                receiver_mode,
                                                                str(target_id),
                                                                str(attack_id),
                                                                str(sample["sample_group"]),
                                                                f"R{float(r_cell):g}",
                                                                f"a{float(alpha):g}",
                                                                f"rho{float(rho):g}",
                                                                f"phi{float(phi):g}",
                                                                args.evaluation_scope,
                                                                verification_strategy.replace(" ", "-"),
                                                                bk_mode,
                                                            ]
                                                        )
                                                        if receiver_mode == "heatmap_mode":
                                                            seg_idx = int(track.segment_index[center_i])
                                                            c_lat = float(track.lat_deg[center_i])
                                                            c_lon = float(track.lon_deg[center_i])
                                                            dist = float(distance_km(np.array([payload["lat"]]), np.array([payload["lon"]]), c_lat, c_lon)[0])
                                                            cov = bool(dist <= float(r_cell) + 1e-9)
                                                            window_id = f"segment_{seg_idx}"
                                                            segment_duration = float(durations[seg_idx]) if 0 <= seg_idx < len(durations) else mean_segment_duration
                                                        else:
                                                            seg_idx = -1
                                                            c_lat = float(np.mean(track.lat_deg))
                                                            c_lon = float(np.mean(track.lon_deg))
                                                            dist = float(payload["distance_mean"])
                                                            cov = bool(payload["coverage_fraction"] >= 1.0)
                                                            window_id = "full_sequence"
                                                            segment_duration = mean_segment_duration
                                                        rows.append(
                                                            row_from_decision(
                                                                case_id=case_id,
                                                                attack_model=attack_model,
                                                                segment_rule=track.segment_rule,
                                                                t_service_s=float(t_service_s),
                                                                t_min_s=float(t_min_s),
                                                                receiver_mode=receiver_mode,
                                                                sample=sample,
                                                                pass_id=pass_id,
                                                                segment_index=seg_idx,
                                                                window_id=window_id,
                                                                r_cell_km=float(r_cell),
                                                                alpha=float(alpha),
                                                                l_step_km=float(l_step),
                                                                rho=float(rho),
                                                                phi_deg=float(phi),
                                                                c_lat=c_lat,
                                                                c_lon=c_lon,
                                                                s_lat=float(payload["lat"]),
                                                                s_lon=float(payload["lon"]),
                                                                distance_to_center_km=dist,
                                                                coverage_valid=cov,
                                                                station_id=sid,
                                                                station_strategy=station_strategy,
                                                                station_separation_km=0.0 if not is_multi else float(args.station_separation_km),
                                                                bk_mode=bk_mode,
                                                                verification_strategy=verification_strategy,
                                                                evaluation_scope=args.evaluation_scope if receiver_mode == "heatmap_mode" else "full_pass",
                                                                doppler_reference_mode=args.doppler_reference_mode
                                                                if receiver_mode == "heatmap_mode"
                                                                else "moving_reference",
                                                                evaluation_start_s=float(payload["evaluation_start_s"]),
                                                                evaluation_end_s=float(payload["evaluation_end_s"]),
                                                                segment_start_s=float(payload["segment_start_s"]),
                                                                segment_end_s=float(payload["segment_end_s"]),
                                                                decision=agg_dec,
                                                                hard_case_flag=bool(sample["sample_group"] == "boundary_case"),
                                                                boundary_case_flag=bool(sample["sample_group"] == "boundary_case"),
                                                                segment_count=segment_count,
                                                                segment_duration_s=segment_duration,
                                                                mean_segment_duration_s=mean_segment_duration,
                                                                median_segment_duration_s=median_segment_duration,
                                                                min_segment_duration_s=min_segment_duration,
                                                                max_segment_duration_s=max_segment_duration,
                                                                mean_g_speed_km_per_s=mean_g_speed,
                                                                coverage_valid_fraction=float(payload["coverage_fraction"]),
                                                                along_offset_km=along_km,
                                                                cross_offset_km=cross_km,
                                                                mean_abs_r_geo_hz=float(payload["mean_abs_r_geo_hz"]),
                                                                rmse_r_geo_hz=float(payload["rmse_r_geo_hz"]),
                                                                max_abs_r_geo_hz=float(payload["max_abs_r_geo_hz"]),
                                                            )
                                                        )
    df = pd.DataFrame(rows)
    if df.empty:
        fail("no dataset rows generated")
    summary = build_summary(df)
    heat = heatmap_input(df)
    segment_audit = build_segment_audit(df)
    geo_audit = pd.DataFrame(geo_rows)
    args.dataset_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.heatmap_output.parent.mkdir(parents=True, exist_ok=True)
    args.segment_audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.geo_residual_output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.dataset_output, index=False)
    summary.to_csv(args.summary_output, index=False)
    heat.to_csv(args.heatmap_output, index=False)
    segment_audit.to_csv(args.segment_audit_output, index=False)
    geo_audit.to_csv(args.geo_residual_output, index=False)
    figures = plot_figures(df, heat, args.figures_dir)
    write_report(args, df, summary, heat, figures)
    append_work_log(args, df, summary, figures)
    return df, summary, heat, figures


def main() -> None:
    args = parse_args()
    df, summary, heat, figures = run(args)
    print(f"wrote {args.dataset_output} rows={len(df)}")
    print(f"wrote {args.summary_output} rows={len(summary)}")
    print(f"wrote {args.heatmap_output} rows={len(heat)}")
    print(f"wrote {args.segment_audit_output}")
    print(f"wrote {args.geo_residual_output}")
    print(f"wrote {args.report_output}")
    print(f"wrote figures={len(figures)} to {args.figures_dir}")


if __name__ == "__main__":
    main()
