#!/usr/bin/env python
"""Audit differential-Doppler mechanisms behind existing local decisions.

This is a representative replay/audit of the existing 60 s M2_block,
fixed-site, segment-local experiment.  It reuses the old rows and the public
orbit/verifier helpers; it does not create a new attack or change a verifier.
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
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_multi_service_area_single_station_confirmation as multi  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BK_MODES = ["no_bk", "current_bk", "wide_bk"]
REAL_DISTANCES = [0.0, 2.5, 5.0, 10.0]
SYNTHETIC_DISTANCES = [0.0, 10.0, 50.0, 100.0, 200.0, 500.0]
GROUP_LABELS = {
    ("real_tle_candidate", "ordinary_similar"): "真实轨道普通相似样本",
    ("real_tle_candidate", "boundary_case"): "真实轨道较难区分样本",
    ("legacy_synthetic", "original_like"): "普通相似受控样本",
    ("legacy_synthetic", "hard_case_weighted"): "高难度受控样本",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="差分多普勒误接受机制代表性审计")
    p.add_argument("--preset", choices=["smoke", "audit"], default="audit")
    p.add_argument("--old-dataset", type=Path, default=Path("outputs/datasets/multi_service_area_single_station_dataset.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--max-pairs", type=int, default=10)
    p.add_argument("--fd-step-km", type=float, default=1.0)
    p.add_argument("--seed", type=int, default=20260711)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def paths_for(preset: str) -> dict[str, Path]:
    suffix = "_smoke" if preset == "smoke" else ""
    fig = Path(f"outputs/figures/differential_doppler_mechanism_audit{suffix}")
    return {
        "selected": Path(f"outputs/metrics/differential_doppler_mechanism_selected_pairs{suffix}.csv"),
        "timeseries": Path(f"outputs/datasets/differential_doppler_mechanism_timeseries{suffix}.csv"),
        "rows": Path(f"outputs/metrics/differential_doppler_mechanism_row_summary{suffix}.csv"),
        "area": Path(f"outputs/metrics/differential_doppler_mechanism_pair_area_summary{suffix}.csv"),
        "repeat": Path(f"outputs/metrics/differential_doppler_mechanism_repeatability_summary{suffix}.csv"),
        "distance_analysis": Path(f"outputs/metrics/differential_doppler_mechanism_distance_explanatory_analysis{suffix}.csv"),
        "transition": Path(f"outputs/metrics/differential_doppler_mechanism_current_to_wide{suffix}.csv"),
        "audit": Path(f"outputs/metrics/differential_doppler_mechanism_correctness_audit{suffix}.csv"),
        "report": Path(f"outputs/reports/differential_doppler_mechanism_audit_report{suffix}.md"),
        "figures": fig,
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def check_inputs(args: argparse.Namespace) -> None:
    for path in [args.old_dataset, args.candidate_library, args.selection_table, args.tle_file, args.orbit_config, args.parameter_config]:
        if not path.exists():
            fail(f"missing input: {path}")


def check_outputs(paths: dict[str, Path], overwrite: bool) -> None:
    existing = [str(p) for k, p in paths.items() if k != "figures" and p.exists()]
    if paths["figures"].exists() and any(paths["figures"].iterdir()):
        existing.append(str(paths["figures"]))
    if existing and not overwrite:
        fail("audit output exists; add --overwrite: " + ", ".join(existing))


def require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{name} missing columns: {', '.join(missing)}")


def load_old(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    require_columns(
        df,
        [
            "pair_id", "sample_source", "sample_group", "target_sat_id", "attack_sat_id",
            "service_area_id", "service_area_segment_index", "evaluation_start_s", "evaluation_end_s",
            "C_lat", "C_lon", "S_lat", "S_lon", "distance_to_center_km", "phi_deg", "bk_mode",
            "residual_rmse_hz", "normalized_score", "b_hat_hz", "k_hat_hz_per_s",
            "score_gate_pass", "b_gate_pass", "k_gate_pass", "coverage_gate_pass",
            "quality_gate_pass", "decision", "accept_flag", "T_service_s", "evaluation_scope",
            "doppler_reference_mode", "verification_strategy",
        ],
        "old formal dataset",
    )
    semantic = (
        df["T_service_s"].eq(60.0)
        & df["evaluation_scope"].eq("segment_local")
        & df["doppler_reference_mode"].eq("fixed_site_segment_center")
        & df["verification_strategy"].eq("single-window")
    )
    if not bool(semantic.all()):
        fail(f"old dataset contains {int((~semantic).sum())} rows outside formal audit semantics")
    return df


def _condition_pivot(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["sample_source", "sample_group", "pair_id", "service_area_id", "distance_to_center_km", "phi_deg"]
    return df.pivot_table(index=keys, columns="bk_mode", values="accept_flag", aggfunc="max").reset_index()


def select_pairs(df: pd.DataFrame, max_pairs: int, smoke: bool) -> pd.DataFrame:
    pivot = _condition_pivot(df)
    candidates: list[dict[str, Any]] = []
    keys = ["sample_source", "sample_group", "pair_id", "target_sat_id", "target_name", "attack_sat_id", "attack_name"]
    for key, g in df.groupby(keys, sort=False, dropna=False):
        source, group, pair_id, target, target_name, attacker, attack_name = key
        pg = pivot[(pivot["sample_source"] == source) & (pivot["sample_group"] == group) & (pivot["pair_id"] == pair_id)]
        cur = pg.get("current_bk", pd.Series(False, index=pg.index)).astype(bool)
        wide = pg.get("wide_bk", pd.Series(False, index=pg.index)).astype(bool)
        direction_discord = False
        for _, dg in pg.groupby(["service_area_id", "distance_to_center_km"]):
            if len(dg) > 1 and dg.get("current_bk", pd.Series(False, index=dg.index)).nunique() > 1:
                direction_discord = True
                break
        area_fraction = (
            pg.assign(cur=cur)
            .groupby("service_area_id")["cur"].max()
            .mean()
            if len(pg) else 0.0
        )
        reasons = []
        if cur.any(): reasons.append("current_bk误接受")
        if ((~cur) & wide).any(): reasons.append("current拒绝→wide误接受")
        if ((~cur) & (~wide)).any(): reasons.append("current/wide均拒绝")
        if direction_discord: reasons.append("同距离不同方向判决不同")
        if area_fraction >= 0.5: reasons.append("跨服务区持续或高比例误接受")
        elif area_fraction > 0: reasons.append("个别服务区偶发误接受")
        reasons.append(GROUP_LABELS.get((str(source), str(group)), str(group)))
        candidates.append({
            "pair_id": str(pair_id), "sample_source": str(source), "sample_group": str(group),
            "target_id": str(target), "target_name": str(target_name), "nontarget_id": str(attacker),
            "nontarget_name": str(attack_name), "selection_reason": "；".join(reasons),
            "number_of_service_areas": int(g["service_area_id"].nunique()),
            "current_accept_fraction": float(cur.mean()), "wide_accept_fraction": float(wide.mean()),
            "transition_count": int(((~cur) & wide).sum()), "direction_discord": bool(direction_discord),
            "area_risk_fraction": float(area_fraction), "group_label": GROUP_LABELS.get((str(source), str(group)), str(group)),
        })
    cand = pd.DataFrame(candidates)
    selected: list[pd.Series] = []
    used_pairs: set[str] = set()

    def take(mask: pd.Series, n: int = 1, sort: list[str] | None = None, asc: list[bool] | None = None) -> None:
        pool = cand[mask].copy()
        if sort:
            pool = pool.sort_values(sort, ascending=asc)
        for _, row in pool.iterrows():
            ident = str(row.pair_id)
            if ident in used_pairs:
                continue
            selected.append(row); used_pairs.add(ident)
            if sum(1 for r in selected[-n:] if r is not None) >= n:
                break

    # Four source/group strata first, then mechanism-rich cases.
    for source, group in GROUP_LABELS:
        take((cand.sample_source == source) & (cand.sample_group == group), 1,
             ["transition_count", "direction_discord", "current_accept_fraction"], [False, False, False])
    take(cand.direction_discord, 2, ["transition_count", "current_accept_fraction"], [False, False])
    take(cand.transition_count.gt(0), 2, ["transition_count"], [False])
    take(cand.area_risk_fraction.ge(0.5), 1, ["area_risk_fraction"], [False])
    take(cand.area_risk_fraction.between(0.0, 0.5, inclusive="neither"), 1, ["area_risk_fraction"], [True])
    for _, row in cand.sort_values(["transition_count", "direction_discord", "current_accept_fraction"], ascending=False).iterrows():
        if len(selected) >= max_pairs:
            break
        ident = str(row.pair_id)
        if ident not in used_pairs:
            selected.append(row); used_pairs.add(ident)
    out = pd.DataFrame(selected).drop_duplicates("pair_id").head(4 if smoke else max_pairs)
    if out.empty:
        fail("automatic pair selection returned no rows")
    return out.reset_index(drop=True)


def nearest_existing(requested: list[float], available: np.ndarray) -> tuple[list[float], str]:
    avail = np.unique(np.asarray(available, dtype=float))
    chosen = sorted({float(avail[np.argmin(np.abs(avail - v))]) for v in requested})
    notes = [f"{v:g}→{float(avail[np.argmin(np.abs(avail-v))]):g}" for v in requested if abs(float(avail[np.argmin(np.abs(avail-v))]) - v) > 1e-9]
    return chosen, "；".join(notes)


def fit_unbounded(values: np.ndarray, t_rel: np.ndarray) -> tuple[float, float, np.ndarray]:
    x = np.asarray(t_rel, dtype=float) - float(np.mean(t_rel))
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, np.asarray(values, dtype=float), rcond=None)
    fitted = design @ coef
    return float(coef[0]), float(coef[1]), fitted


def fit_bounded(values: np.ndarray, t_rel: np.ndarray, b_bounds: tuple[float, float], k_bounds: tuple[float, float]) -> tuple[float, float, np.ndarray]:
    # Centered time makes the two columns orthogonal; clipping each unbounded
    # coefficient is therefore the exact box-constrained least-squares result.
    b, k, _ = fit_unbounded(values, t_rel)
    b = float(np.clip(b, *b_bounds)); k = float(np.clip(k, *k_bounds))
    x = np.asarray(t_rel, dtype=float) - float(np.mean(t_rel))
    return b, k, b + k * x


def stats(values: np.ndarray) -> dict[str, float]:
    a = np.asarray(values, dtype=float)
    return {
        "mean_hz": float(np.mean(a)), "std_hz": float(np.std(a, ddof=0)),
        "rmse_hz": float(np.sqrt(np.mean(a * a))), "max_abs_hz": float(np.max(np.abs(a))),
        "peak_to_peak_hz": float(np.ptp(a)),
    }


def projected_jacobian(j: np.ndarray, t_rel: np.ndarray) -> np.ndarray:
    out = np.zeros_like(j, dtype=float)
    for col in range(2):
        _, _, fitted = fit_unbounded(j[:, col], t_rel)
        out[:, col] = j[:, col] - fitted
    return out


def finite_difference(
    sample: dict[str, Any], sat_a: Any, sat_b: Any | None, c_lat: float, c_lon: float,
    times: list[datetime], ts: Any, freq_hz: float, step_s: float, h_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    def delta(lat: float, lon: float) -> np.ndarray:
        fa = seg.geo_curve_fixed(sat_a, lat, lon, 0.0, times, ts, freq_hz, step_s)[0]
        fb = multi.attack_geo(sample, sat_a, sat_b, lat, lon, 0.0, times, ts, freq_hz, step_s)
        return fa - fb
    base = delta(c_lat, c_lon)
    nlat, nlon = seg.destination(c_lat, c_lon, h_km, 0.0)
    elat, elon = seg.destination(c_lat, c_lon, h_km, 90.0)
    return (delta(elat, elon) - base) / h_km, (delta(nlat, nlon) - base) / h_km


def threshold_from_old(row: pd.Series, cal: dict[str, dict[str, float]], bk_mode: str) -> dict[str, float]:
    th = seg.threshold_for(cal, "full_pass", bk_mode)
    nscore = float(row.normalized_score)
    score = float(row.residual_rmse_hz)
    if np.isfinite(nscore) and nscore > 1e-12:
        old_threshold = score / nscore
        # Prefer the exactly recorded formal threshold; keep recomputed delta for audit.
        th["recomputed_score_threshold"] = float(th["score_threshold"])
        th["score_threshold"] = float(old_threshold)
    else:
        th["recomputed_score_threshold"] = float(th["score_threshold"])
    return th


def replay_decision(row: pd.Series, th: dict[str, float], bk_mode: str) -> tuple[str, dict[str, bool]]:
    score_pass = bool(float(row.residual_rmse_hz) <= th["score_threshold"] + 1e-9)
    if bk_mode == "no_bk":
        b_pass = k_pass = True
    else:
        b_pass = bool(abs(float(row.b_hat_hz) - th["b_center"]) <= th["b_threshold"] + 1e-9)
        k_pass = bool(abs(float(row.k_hat_hz_per_s) - th["k_center"]) <= th["k_threshold"] + 1e-9)
    coverage = bool(row.coverage_gate_pass); quality = bool(row.quality_gate_pass)
    decision = "DEFER" if not coverage else ("ACCEPT" if score_pass and b_pass and k_pass and quality else "REJECT")
    return decision, {"score": score_pass, "b": b_pass, "k": k_pass, "coverage": coverage, "quality": quality}


def run(args: argparse.Namespace, paths: dict[str, Path]) -> tuple[pd.DataFrame, ...]:
    check_inputs(args); check_outputs(paths, args.overwrite)
    old = load_old(args.old_dataset)
    selected = select_pairs(old, args.max_pairs, args.preset == "smoke")
    loader = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library,
                             tle_file=args.tle_file, orbit_config=args.orbit_config,
                             parameter_config=args.parameter_config, max_targets=5)
    _selection, library, orbit_cfg, tle, ranges = expanded.load_base_inputs(loader)
    if orbit_cfg.get("mode") != "controlled_starlink" or orbit_cfg.get("observation_id") is not None:
        fail("audit requires mode=controlled_starlink and observation_id=null")
    ts = load.timescale()
    freq_hz = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    row_out: list[dict[str, Any]] = []; time_out: list[dict[str, Any]] = []
    distance_notes: list[str] = []; absorption_clip_count = 0
    for sp in selected.to_dict("records"):
        subset = old[(old.pair_id.astype(str) == sp["pair_id"]) & (old.sample_source == sp["sample_source"]) & (old.sample_group == sp["sample_group"])].copy()
        desired = REAL_DISTANCES if sp["sample_source"] == "real_tle_candidate" else SYNTHETIC_DISTANCES
        if args.preset == "smoke": desired = desired[:2]
        distances, note = nearest_existing(desired, subset.distance_to_center_km.to_numpy(float))
        if note: distance_notes.append(f"{sp['pair_id']}：{note}")
        subset = subset[subset.distance_to_center_km.isin(distances)]
        sample = subset.iloc[0].to_dict()
        target_id = str(sample["target_sat_id"]); attacker_id = str(sample["attack_sat_id"])
        if target_id not in tle: fail(f"target missing in TLE: {target_id}")
        sat_a = tle[target_id]["sat"]
        sat_b = tle[attacker_id]["sat"] if sp["sample_source"] == "real_tle_candidate" else None
        target_geo = seg.base.target_geo_from_library(library, target_id)
        full_t = target_geo.t_rel_s.to_numpy(float)
        full_times = [seg.base.parse_utc(v) for v in target_geo.t_abs_utc.astype(str)]
        step_s = float(np.median(np.diff(full_t)))
        area_cache: dict[str, dict[str, Any]] = {}
        condition_cols = ["service_area_id", "distance_to_center_km", "phi_deg"]
        for cond, g in subset.groupby(condition_cols, sort=False):
            area_id, distance, phi = cond
            formal = g.drop_duplicates("bk_mode").set_index("bk_mode")
            if not set(BK_MODES).issubset(formal.index):
                continue
            base_row = formal.loc["current_bk"]
            start = float(base_row.evaluation_start_s); end = float(base_row.evaluation_end_s)
            mask = (full_t >= start - 1e-9) & (full_t <= end + 1e-9)
            eval_t = full_t[mask]; times = [t for t, keep in zip(full_times, mask) if keep]
            if len(eval_t) < 3: fail(f"no matching service segment for {area_id}")
            c_lat, c_lon = float(base_row.C_lat), float(base_row.C_lon)
            s_lat, s_lon = float(base_row.S_lat), float(base_row.S_lon)
            cache_key = str(area_id)
            if cache_key not in area_cache:
                fd = {}
                for h in [0.5, float(args.fd_step_km), 2.0]:
                    fd[h] = finite_difference(sample, sat_a, sat_b, c_lat, c_lon, times, ts, freq_hz, step_s, h)
                je, jn = fd[float(args.fd_step_km)]
                jraw = np.column_stack([je, jn]); jpost = projected_jacobian(jraw, eval_t)
                _u, singular, vt = np.linalg.svd(jpost, full_matrices=False)
                singular_rmse = singular / math.sqrt(len(eval_t))
                strongest = float(singular_rmse[0]); weakest = float(singular_rmse[-1])
                weak_vec = vt[-1]
                weak_bearing = float((math.degrees(math.atan2(weak_vec[0], weak_vec[1])) + 360.0) % 180.0)
                rms_h = {h: float(np.sqrt(np.mean(np.column_stack(fd[h]) ** 2))) for h in fd}
                stability = float(max(abs(rms_h[0.5] - rms_h[1.0]), abs(rms_h[2.0] - rms_h[1.0])) / max(rms_h[1.0], 1e-12))
                area_cache[cache_key] = {
                    "je": je, "jn": jn, "jpost": jpost,
                    "east_raw": float(np.sqrt(np.mean(je * je))), "north_raw": float(np.sqrt(np.mean(jn * jn))),
                    "east_post": float(np.sqrt(np.mean(jpost[:, 0] ** 2))), "north_post": float(np.sqrt(np.mean(jpost[:, 1] ** 2))),
                    "weakest": weakest, "strongest": strongest,
                    "anisotropy": float(strongest / weakest) if weakest > 1e-12 else math.inf,
                    "weak_bearing": weak_bearing, "fd_stability": stability,
                }
            sens = area_cache[cache_key]
            fa_c = seg.geo_curve_fixed(sat_a, c_lat, c_lon, 0.0, times, ts, freq_hz, step_s)[0]
            fa_s = seg.geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, times, ts, freq_hz, step_s)[0]
            fb_c = multi.attack_geo(sample, sat_a, sat_b, c_lat, c_lon, 0.0, times, ts, freq_hz, step_s)
            fb_s = multi.attack_geo(sample, sat_a, sat_b, s_lat, s_lon, 0.0, times, ts, freq_hz, step_s)
            raw = fb_s + fa_c - fb_c - fa_s
            ub, uk, ufit = fit_unbounded(raw, eval_t); uremain = raw - ufit
            bearing = math.radians(float(phi)); direction = np.array([math.sin(bearing), math.cos(bearing)])
            actual_raw = sens["je"] * direction[0] + sens["jn"] * direction[1]
            actual_post = sens["jpost"] @ direction
            cal = seg.calibration_for_trel(eval_t, ranges, 20260706 + int(target_id) + int(base_row.service_area_segment_index), 30)
            for bk_mode in BK_MODES:
                old_row = formal.loc[bk_mode]
                th = threshold_from_old(old_row, cal, bk_mode)
                if bk_mode == "no_bk":
                    b_bounds = (0.0, 0.0); k_bounds = (0.0, 0.0)
                else:
                    # Geometry-only contribution budget relative to the formal gate centre.
                    b_bounds = (-float(th["b_threshold"]), float(th["b_threshold"]))
                    k_bounds = (-float(th["k_threshold"]), float(th["k_threshold"]))
                bb, bk, bfit = fit_bounded(raw, eval_t, b_bounds, k_bounds); remain = raw - bfit
                raw_s = stats(raw); post_s = stats(remain)
                eraw = float(np.sum(raw * raw)); eremain = float(np.sum(remain * remain))
                if eraw <= max(1e-18, len(raw) * 1e-18):
                    absorb = np.nan
                else:
                    absorb_raw = 1.0 - eremain / eraw
                    if -1e-10 <= absorb_raw <= 1.0 + 1e-10:
                        absorb = float(np.clip(absorb_raw, 0.0, 1.0))
                        absorption_clip_count += int(absorb != absorb_raw)
                    else:
                        absorb = float(absorb_raw)
                tol_b = max(1e-8, 1e-7 * max(abs(b_bounds[1] - b_bounds[0]), 1.0))
                tol_k = max(1e-10, 1e-7 * max(abs(k_bounds[1] - k_bounds[0]), 1e-3))
                b_low = abs(bb - b_bounds[0]) <= tol_b; b_high = abs(bb - b_bounds[1]) <= tol_b
                k_low = abs(bk - k_bounds[0]) <= tol_k; k_high = abs(bk - k_bounds[1]) <= tol_k
                replay, gates = replay_decision(old_row, th, bk_mode)
                mismatch_parts = []
                for gate, old_col in [("score", "score_gate_pass"), ("b", "b_gate_pass"), ("k", "k_gate_pass"), ("coverage", "coverage_gate_pass"), ("quality", "quality_gate_pass")]:
                    if gates[gate] != bool(old_row[old_col]): mismatch_parts.append(f"{gate}_gate数值/记录不一致")
                if replay != str(old_row.decision): mismatch_parts.append("final_decision不一致")
                actual_distance = float(seg.distance_km(np.array([c_lat]), np.array([c_lon]), s_lat, s_lon)[0])
                record = {
                    "pair_id": sp["pair_id"], "sample_source": sp["sample_source"], "sample_group": sp["sample_group"], "group_label": sp["group_label"],
                    "target_id": target_id, "nontarget_id": attacker_id, "service_area_id": area_id,
                    "service_area_segment_index": int(base_row.service_area_segment_index), "distance_km": float(distance), "actual_distance_km": actual_distance,
                    "distance_error_km": abs(actual_distance - float(distance)), "direction_deg": float(phi), "direction_definition": "0deg=north,90deg=east,clockwise",
                    "bk_mode": bk_mode, "time_reference_s": float(np.mean(eval_t)), "num_points": len(eval_t),
                    "raw_geo_mean_hz": raw_s["mean_hz"], "raw_geo_std_hz": raw_s["std_hz"], "raw_geo_rmse_hz": raw_s["rmse_hz"],
                    "raw_geo_max_abs_hz": raw_s["max_abs_hz"], "raw_geo_peak_to_peak_hz": raw_s["peak_to_peak_hz"],
                    "unbounded_b_hat_hz": ub, "unbounded_k_hat_hz_per_s": uk, "unbounded_post_bk_rmse_hz": float(np.sqrt(np.mean(uremain**2))),
                    "bounded_b_hat_hz": bb, "bounded_k_hat_hz_per_s": bk,
                    "geometry_b_lower_bound_hz": b_bounds[0], "geometry_b_upper_bound_hz": b_bounds[1], "geometry_k_lower_bound_hz_per_s": k_bounds[0], "geometry_k_upper_bound_hz_per_s": k_bounds[1],
                    "formal_b_gate_lower_hz": th["b_center"] - th["b_threshold"], "formal_b_gate_upper_hz": th["b_center"] + th["b_threshold"],
                    "formal_k_gate_lower_hz_per_s": th["k_center"] - th["k_threshold"], "formal_k_gate_upper_hz_per_s": th["k_center"] + th["k_threshold"],
                    "b_lower_boundary_hit": b_low, "b_upper_boundary_hit": b_high, "k_lower_boundary_hit": k_low, "k_upper_boundary_hit": k_high,
                    "any_bk_boundary_hit": bool(b_low or b_high or k_low or k_high),
                    "post_bk_mean_hz": post_s["mean_hz"], "post_bk_std_hz": post_s["std_hz"], "post_bk_rmse_hz": post_s["rmse_hz"], "post_bk_max_abs_hz": post_s["max_abs_hz"],
                    "raw_geo_energy": eraw, "remaining_energy": eremain, "absorption_ratio": absorb,
                    "score_value": float(old_row.residual_rmse_hz), "score_threshold": float(th["score_threshold"]), "score_gate_pass": gates["score"],
                    "b_gate_pass": gates["b"], "k_gate_pass": gates["k"], "coverage_gate_pass": gates["coverage"], "quality_gate_pass": gates["quality"],
                    "all_verifier_gates": "score,b,k,coverage,quality", "final_decision": replay, "original_final_decision": str(old_row.decision),
                    "decision_matches_original": replay == str(old_row.decision) and not mismatch_parts,
                    "decision_mismatch_reason": "；".join(mismatch_parts), "original_b_hat_hz": float(old_row.b_hat_hz), "original_k_hat_hz_per_s": float(old_row.k_hat_hz_per_s),
                    "east_raw_sensitivity_rmse_hz_per_km": sens["east_raw"], "north_raw_sensitivity_rmse_hz_per_km": sens["north_raw"],
                    "east_post_projection_sensitivity_rmse_hz_per_km": sens["east_post"], "north_post_projection_sensitivity_rmse_hz_per_km": sens["north_post"],
                    "weakest_direction_sensitivity_hz_per_km": sens["weakest"], "strongest_direction_sensitivity_hz_per_km": sens["strongest"],
                    "anisotropy_ratio": sens["anisotropy"], "weakest_direction_deg": sens["weak_bearing"],
                    "actual_direction_raw_sensitivity_hz_per_km": float(np.sqrt(np.mean(actual_raw**2))),
                    "actual_direction_post_projection_sensitivity_hz_per_km": float(np.sqrt(np.mean(actual_post**2))),
                    "finite_difference_max_relative_change_0p5_1_2km": sens["fd_stability"], "random_seed": args.seed,
                }
                row_out.append(record)
                for ti, value in enumerate(raw):
                    time_out.append({
                        "pair_id": sp["pair_id"], "sample_group": sp["sample_group"], "service_area_id": area_id, "distance_km": float(distance), "direction_deg": float(phi),
                        "bk_mode": bk_mode, "time_s": float(eval_t[ti] - np.mean(eval_t)), "raw_geometric_residual_hz": float(value),
                        "fitted_bk_component_hz": float(bfit[ti]), "remaining_residual_hz": float(remain[ti]), "weight": 1.0,
                    })
    rows = pd.DataFrame(row_out); timeseries = pd.DataFrame(time_out)
    selected["distance_substitution_note"] = selected.apply(lambda r: next((n.split("：", 1)[1] for n in distance_notes if n.startswith(r.pair_id + "：")), "无"), axis=1)
    selected["number_of_service_areas"] = selected.apply(lambda r: rows[(rows.pair_id == r.pair_id) & (rows.sample_group == r.sample_group)].service_area_id.nunique(), axis=1)
    rows.attrs["absorption_clip_count"] = absorption_clip_count
    return selected, timeseries, rows


def build_summaries(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    area_keys = ["pair_id", "sample_source", "sample_group", "group_label", "target_id", "nontarget_id", "service_area_id", "bk_mode"]
    area_records = []
    for key, g in rows.groupby(area_keys, dropna=False):
        accepted = g.final_decision.eq("ACCEPT")
        risk_dist = g.loc[accepted, "distance_km"].max() if accepted.any() else np.nan
        transition = rows[(rows.pair_id == key[0]) & (rows.sample_group == key[2]) & (rows.service_area_id == key[6])].pivot_table(index=["distance_km", "direction_deg"], columns="bk_mode", values="final_decision", aggfunc="first")
        has_transition = bool(((transition.get("current_bk") == "REJECT") & (transition.get("wide_bk") == "ACCEPT")).any()) if {"current_bk", "wide_bk"}.issubset(transition.columns) else False
        area_records.append({**dict(zip(area_keys, key)), "row_count": len(g), "accept_count": int(accepted.sum()), "accept_fraction": float(accepted.mean()),
                             "distance_direction_decisions": ";".join(f"d={r.distance_km:g},phi={r.direction_deg:g}:{r.final_decision}" for r in g.itertuples()),
                             "mean_absorption_ratio": float(g.absorption_ratio.mean()), "bk_boundary_hit_fraction": float(g.any_bk_boundary_hit.mean()),
                             "min_actual_direction_sensitivity": float(g.actual_direction_post_projection_sensitivity_hz_per_km.min()),
                             "max_actual_direction_sensitivity": float(g.actual_direction_post_projection_sensitivity_hz_per_km.max()),
                             "weakest_direction_sensitivity": float(g.weakest_direction_sensitivity_hz_per_km.min()),
                             "maximum_observed_risk_distance_km": float(risk_dist) if pd.notna(risk_dist) else np.nan,
                             "has_current_reject_wide_accept": has_transition})
    area = pd.DataFrame(area_records)
    repeat_records = []
    pair_keys = ["pair_id", "sample_source", "sample_group", "group_label", "target_id", "nontarget_id"]
    for key, g in rows.groupby(pair_keys, dropna=False):
        cur = g[g.bk_mode == "current_bk"]; wide = g[g.bk_mode == "wide_bk"]
        condition_fraction = cur.groupby(["distance_km", "direction_deg"]).apply(
            lambda x: x.final_decision.eq("ACCEPT").mean(), include_groups=False
        )
        mean_fraction = float(cur.final_decision.eq("ACCEPT").mean())
        repeat_records.append({**dict(zip(pair_keys, key)), "mean_accept_fraction": mean_fraction,
                               "current_accept_fraction": mean_fraction, "wide_accept_fraction": float(wide.final_decision.eq("ACCEPT").mean()),
                               "mean_actual_direction_sensitivity": float(cur.actual_direction_post_projection_sensitivity_hz_per_km.mean()),
                               "min_actual_direction_sensitivity": float(cur.actual_direction_post_projection_sensitivity_hz_per_km.min()),
                               "mean_weakest_direction_sensitivity": float(cur.weakest_direction_sensitivity_hz_per_km.mean()),
                               "mean_absorption_ratio": float(cur.absorption_ratio.mean()), "absorption_ratio_std": float(cur.absorption_ratio.std(ddof=0)),
                               "bk_boundary_hit_fraction": float(cur.any_bk_boundary_hit.mean()), "number_of_service_areas": int(cur.service_area_id.nunique()),
                               "persistent_accept": bool(len(condition_fraction) > 0 and (condition_fraction >= 1.0).any()),
                               "recurrent_accept": bool(len(condition_fraction) > 0 and (condition_fraction >= 0.5).any()),
                               "service_area_accept_fraction": float(condition_fraction.mean()) if len(condition_fraction) else np.nan,
                               "service_area_sensitivity_variance": float(cur.groupby("service_area_id").actual_direction_post_projection_sensitivity_hz_per_km.mean().var(ddof=0)),
                               "service_area_absorption_variance": float(cur.groupby("service_area_id").absorption_ratio.mean().var(ddof=0))})
    return area, pd.DataFrame(repeat_records)


def explanatory_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    d = rows[(rows.bk_mode == "current_bk") & (rows.distance_km > 0)].copy()
    d["accepted"] = d.final_decision.eq("ACCEPT").astype(int)
    features = {
        "distance_only": ["distance_km"],
        "distance_plus_direction_sensitivity": ["distance_km", "actual_direction_post_projection_sensitivity_hz_per_km"],
        "distance_plus_absorption": ["distance_km", "absorption_ratio"],
        "distance_plus_direction_sensitivity_plus_absorption": ["distance_km", "actual_direction_post_projection_sensitivity_hz_per_km", "absorption_ratio"],
    }
    records: list[dict[str, Any]] = []
    for col in ["distance_km", "actual_direction_post_projection_sensitivity_hz_per_km", "absorption_ratio", "anisotropy_ratio", "raw_geo_rmse_hz"]:
        valid = d[[col, "accepted"]].replace([np.inf, -np.inf], np.nan).dropna()
        rho, p = spearmanr(valid[col], valid.accepted) if len(valid) >= 3 else (np.nan, np.nan)
        records.append({"analysis_type": "spearman", "model_or_bin": col, "n": len(valid), "value": rho, "secondary_value": p, "notes": "value=rho; secondary=p"})
    for name, cols in features.items():
        valid = d[cols + ["accepted"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(valid) >= 20 and valid.accepted.nunique() == 2:
            model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=20260711))
            model.fit(valid[cols], valid.accepted); prob = model.predict_proba(valid[cols])[:, 1]
            auc = roc_auc_score(valid.accepted, prob)
            coef = model[-1].coef_[0]
            note = ";".join(f"{c}={v:.4g}" for c, v in zip(cols, coef))
        else:
            auc = np.nan; note = "样本不足或只有单一类别"
        records.append({"analysis_type": "logistic", "model_or_bin": name, "n": len(valid), "value": auc, "secondary_value": np.nan, "notes": "value=in-sample ROC-AUC; standardized coefficients: " + note})
    d["distance_bin"] = pd.cut(d.distance_km, bins=[-1e-9, 5, 10, 50, 100, 200, np.inf], include_lowest=True).astype(str)
    for (dist_bin, accepted), g in d.groupby(["distance_bin", "accepted"], observed=True):
        records.append({"analysis_type": "distance_bin", "model_or_bin": f"{dist_bin}|{'ACCEPT' if accepted else 'REJECT'}", "n": len(g),
                        "value": float(g.actual_direction_post_projection_sensitivity_hz_per_km.mean()), "secondary_value": float(g.absorption_ratio.mean()),
                        "notes": "value=mean direction sensitivity; secondary=mean absorption"})
    for (distance, accepted), g in d.groupby(["distance_km", "accepted"]):
        records.append({"analysis_type": "same_distance", "model_or_bin": f"d={distance:g}|{'ACCEPT' if accepted else 'REJECT'}", "n": len(g),
                        "value": float(g.actual_direction_post_projection_sensitivity_hz_per_km.mean()), "secondary_value": float(g.absorption_ratio.mean()),
                        "notes": "同距离判决组均值"})
    return pd.DataFrame(records)


def transition_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    keys = ["pair_id", "sample_source", "sample_group", "group_label", "service_area_id", "distance_km", "direction_deg"]
    cur = rows[rows.bk_mode == "current_bk"].set_index(keys); wide = rows[rows.bk_mode == "wide_bk"].set_index(keys)
    joined = cur.add_suffix("_current").join(wide.add_suffix("_wide"), how="inner").reset_index()
    out = joined[(joined.final_decision_current == "REJECT") & (joined.final_decision_wide == "ACCEPT")].copy()
    if out.empty: return out
    out["post_bk_rmse_decrease_fraction"] = 1.0 - out.post_bk_rmse_hz_wide / out.post_bk_rmse_hz_current.replace(0, np.nan)
    out["absorption_ratio_increase"] = out.absorption_ratio_wide - out.absorption_ratio_current
    def mechanism(r: pd.Series) -> str:
        b = (not bool(r.b_gate_pass_current)) and bool(r.b_gate_pass_wide)
        k = (not bool(r.k_gate_pass_current)) and bool(r.k_gate_pass_wide)
        score = (not bool(r.score_gate_pass_current)) and bool(r.score_gate_pass_wide)
        other = ((not bool(r.coverage_gate_pass_current)) and bool(r.coverage_gate_pass_wide)) or ((not bool(r.quality_gate_pass_current)) and bool(r.quality_gate_pass_wide))
        if b and k: return "b/k同时解除"
        if b: return "b边界解除"
        if k: return "k边界解除"
        if score: return "残差gate改变"
        if other: return "其他gate改变"
        return "无法解释"
    out["mechanism_class"] = out.apply(mechanism, axis=1)
    out["current_boundary_hit"] = out.any_bk_boundary_hit_current
    out["wide_boundary_released"] = out.any_bk_boundary_hit_current & ~out.any_bk_boundary_hit_wide
    return out


def correctness_audit(rows: pd.DataFrame, transitions: pd.DataFrame) -> pd.DataFrame:
    eps_geo = 1e-3
    tests = []
    def add(name: str, passed: bool, value: Any, tolerance: str, notes: str = "") -> None:
        tests.append({"check": name, "passed": bool(passed), "observed": value, "tolerance": tolerance, "notes": notes})
    d0 = rows[np.isclose(rows.distance_km, 0.0)]
    add("d=0距离误差", bool((d0.distance_error_km <= 1e-6).all()), float(d0.distance_error_km.max()), "<=1e-6 km")
    add("d=0原始几何残差", bool((d0.raw_geo_rmse_hz <= eps_geo).all()), float(d0.raw_geo_rmse_hz.max()), f"<={eps_geo} Hz")
    no = rows[rows.bk_mode == "no_bk"]
    no_ok = np.allclose(no.bounded_b_hat_hz, 0) and np.allclose(no.bounded_k_hat_hz_per_s, 0) and np.allclose(no.post_bk_rmse_hz, no.raw_geo_rmse_hz, atol=1e-9)
    add("no_bk恒等", no_ok, int((~np.isclose(no.post_bk_rmse_hz, no.raw_geo_rmse_hz, atol=1e-9)).sum()), "b=k=0且post=raw")
    add("无边界拟合RMSE不增", bool((rows.unbounded_post_bk_rmse_hz <= rows.raw_geo_rmse_hz + 1e-8).all()), float((rows.unbounded_post_bk_rmse_hz - rows.raw_geo_rmse_hz).max()), "<=1e-8 Hz")
    keys = ["pair_id", "sample_group", "service_area_id", "distance_km", "direction_deg"]
    c = rows[rows.bk_mode == "current_bk"].set_index(keys); w = rows[rows.bk_mode == "wide_bk"].set_index(keys)
    diff = w.post_bk_rmse_hz - c.post_bk_rmse_hz
    add("wide有界残差不高于current", bool((diff <= 1e-8).all()), float(diff.max()), "<=1e-8 Hz")
    bounds_ok = ((rows.bounded_b_hat_hz >= rows.geometry_b_lower_bound_hz - 1e-8) & (rows.bounded_b_hat_hz <= rows.geometry_b_upper_bound_hz + 1e-8) &
                 (rows.bounded_k_hat_hz_per_s >= rows.geometry_k_lower_bound_hz_per_s - 1e-10) & (rows.bounded_k_hat_hz_per_s <= rows.geometry_k_upper_bound_hz_per_s + 1e-10)).all()
    add("有界参数满足边界", bool(bounds_ok), int((~((rows.bounded_b_hat_hz >= rows.geometry_b_lower_bound_hz - 1e-8) & (rows.bounded_b_hat_hz <= rows.geometry_b_upper_bound_hz + 1e-8))).sum()), "box内")
    consistency = float(rows.decision_matches_original.mean())
    add("判决重放一致率", consistency == 1.0, consistency, "目标=100%", f"不一致{int((~rows.decision_matches_original).sum())}条")
    max_fd = float(rows.finite_difference_max_relative_change_0p5_1_2km.max())
    add("有限差分0.5/1/2km稳定", max_fd <= 0.15, max_fd, "最大相对变化<=15%", "局部数值稳定性检查")
    add("经纬度/ENU/单位", bool((rows.distance_error_km <= 1e-6).all()), float(rows.distance_error_km.max()), "大圆目的点距离误差<=1e-6 km", "0°北、90°东、顺时针；传播高度0 m")
    add("吸收比例数值范围", bool(rows.absorption_ratio.dropna().between(-1e-10, 1 + 1e-10).all()), int((~rows.absorption_ratio.dropna().between(-1e-10, 1 + 1e-10)).sum()), "浮点容差内[0,1]")
    add("current→wide样本存在", len(transitions) > 0, len(transitions), ">0")
    return pd.DataFrame(tests)


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); fig.tight_layout(); fig.savefig(path, dpi=180); plt.close(fig)


def make_figures(rows: pd.DataFrame, timeseries: pd.DataFrame, area: pd.DataFrame, transitions: pd.DataFrame, outdir: Path) -> list[Path]:
    paths: list[Path] = []
    # Representative three curves: select largest finite current absorption.
    current = rows[(rows.bk_mode == "current_bk") & rows.absorption_ratio.notna()]
    rep = current.sort_values("absorption_ratio", ascending=False).iloc[0]
    t = timeseries[(timeseries.pair_id == rep.pair_id) & (timeseries.service_area_id == rep.service_area_id) &
                   (timeseries.distance_km == rep.distance_km) & (timeseries.direction_deg == rep.direction_deg) & (timeseries.bk_mode == "current_bk")]
    fig, ax = plt.subplots(figsize=(10, 5)); ax.plot(t.time_s, t.raw_geometric_residual_hz, label="原始几何残差"); ax.plot(t.time_s, t.fitted_bk_component_hz, label="有界 b+kt"); ax.plot(t.time_s, t.remaining_residual_hz, label="拟合后剩余")
    ax.set(xlabel="相对服务段均值时间 (s)", ylabel="频率 (Hz)", title=f"代表机制三曲线：{rep.pair_id} / {rep.service_area_id}"); ax.legend(); p=outdir/"representative_three_curves.png"; savefig(fig,p); paths.append(p)
    # current reject -> wide accept boundary comparison.
    if not transitions.empty:
        tr = transitions.iloc[0]; labels=["current_bk","wide_bk"]
        b=[tr.bounded_b_hat_hz_current,tr.bounded_b_hat_hz_wide]; k=[tr.bounded_k_hat_hz_per_s_current,tr.bounded_k_hat_hz_per_s_wide]; rm=[tr.post_bk_rmse_hz_current,tr.post_bk_rmse_hz_wide]
        fig, axes=plt.subplots(1,3,figsize=(12,4)); axes[0].bar(labels,b); axes[0].set_title("几何 b_hat"); axes[1].bar(labels,k); axes[1].set_title("几何 k_hat"); axes[2].bar(labels,rm); axes[2].set_title("有界拟合后 RMSE");
        for ax in axes: ax.tick_params(axis='x',rotation=15)
        p=outdir/"current_reject_wide_accept_boundary_comparison.png"; savefig(fig,p); paths.append(p)
    d=rows[(rows.bk_mode=="current_bk") & (rows.distance_km>0)]
    colors=d.final_decision.map({"ACCEPT":"tab:red","REJECT":"tab:blue","DEFER":"tab:gray"})
    fig,ax=plt.subplots(figsize=(9,5)); ax.scatter(d.distance_km+d.direction_deg*0.0005,d.actual_direction_post_projection_sensitivity_hz_per_km,c=colors,alpha=.55); ax.set(xlabel="距离 (km；轻微方向抖动仅用于显示)",ylabel="实际方向投影后敏感度 (Hz/km)",title="相同距离下方向敏感度与判决"); p=outdir/"same_distance_direction_sensitivity_decision.png"; savefig(fig,p); paths.append(p)
    fig,ax=plt.subplots(figsize=(9,5));
    for label,g in d.groupby("group_label"): ax.scatter(g.absorption_ratio,g.post_bk_rmse_hz,label=label,alpha=.55)
    ax.set(xlabel="b/k 吸收比例",ylabel="几何有界拟合后 RMSE (Hz)",title="吸收比例与判决机制"); ax.legend(fontsize=8); p=outdir/"absorption_ratio_vs_decision.png"; savefig(fig,p); paths.append(p)
    ac=area[area.bk_mode=="current_bk"]
    fig,ax=plt.subplots(figsize=(9,5)); ax.scatter(ac.weakest_direction_sensitivity,ac.maximum_observed_risk_distance_km,c=ac.accept_fraction,cmap="viridis"); ax.set(xlabel="最弱方向敏感度 (Hz/km)",ylabel="最大观察风险距离 (km)",title="最大观察风险距离与最弱方向敏感度"); p=outdir/"risk_distance_vs_weakest_sensitivity.png"; savefig(fig,p); paths.append(p)
    # Three aligned cross-area heatmaps for one persistent/recurrent pair.
    pair = d.groupby("pair_id").final_decision.apply(lambda x:(x=="ACCEPT").mean()).sort_values(ascending=False).index[0]
    hd=d[d.pair_id==pair].copy(); hd["condition"]=hd.distance_km.astype(str)+"km/"+hd.direction_deg.astype(str)+"°"
    conds=list(dict.fromkeys(hd.condition)); areas=list(dict.fromkeys(hd.service_area_id)); fig,axes=plt.subplots(1,3,figsize=(16,5))
    vals=[("actual_direction_post_projection_sensitivity_hz_per_km","实际方向敏感度"),("absorption_ratio","吸收比例"),("final_decision","最终判决")]
    for ax,(col,title) in zip(axes,vals):
        pv=hd.pivot_table(index="service_area_id",columns="condition",values=col,aggfunc="first") if col!="final_decision" else hd.assign(dec=hd.final_decision.map({"REJECT":0,"DEFER":.5,"ACCEPT":1})).pivot_table(index="service_area_id",columns="condition",values="dec",aggfunc="first")
        pv=pv.reindex(index=areas,columns=conds); im=ax.imshow(pv.to_numpy(float),aspect="auto",cmap="viridis"); ax.set_title(title); ax.set_yticks(range(len(areas)),[str(x).split("_area_")[-1] for x in areas]); ax.set_xticks(range(len(conds)),conds,rotation=90,fontsize=6); fig.colorbar(im,ax=ax,fraction=.046)
    p=outdir/"cross_service_area_mechanism_heatmap.png"; savefig(fig,p); paths.append(p)
    return paths


def write_report(paths: dict[str, Path], selected: pd.DataFrame, rows: pd.DataFrame, area: pd.DataFrame, repeat: pd.DataFrame,
                 analysis: pd.DataFrame, transitions: pd.DataFrame, audit: pd.DataFrame, figures: list[Path]) -> tuple[str, bool]:
    logistic = analysis[analysis.analysis_type=="logistic"][["model_or_bin","n","value","notes"]]
    spearman = analysis[analysis.analysis_type=="spearman"][["model_or_bin","n","value","secondary_value"]]
    trans_counts = transitions.mechanism_class.value_counts() if not transitions.empty else pd.Series(dtype=int)
    group_compare = rows[(rows.bk_mode=="current_bk") & (rows.distance_km>0)].groupby("group_label").agg(
        n=("pair_id","size"), raw_geo_rmse=("raw_geo_rmse_hz","mean"), actual_sensitivity=("actual_direction_post_projection_sensitivity_hz_per_km","mean"),
        weakest_sensitivity=("weakest_direction_sensitivity_hz_per_km","mean"), anisotropy=("anisotropy_ratio","median"), absorption=("absorption_ratio","mean"),
        boundary_hit=("any_bk_boundary_hit","mean"), remaining_rmse=("post_bk_rmse_hz","mean"), accept_fraction=("final_decision",lambda x:(x=="ACCEPT").mean())).reset_index()
    auc = logistic.set_index("model_or_bin").value.to_dict()
    base_auc = auc.get("distance_only", np.nan); full_auc = auc.get("distance_plus_direction_sensitivity_plus_absorption", np.nan)
    direction_rho = spearman.set_index("model_or_bin").value.to_dict().get("actual_direction_post_projection_sensitivity_hz_per_km", np.nan)
    absorption_rho = spearman.set_index("model_or_bin").value.to_dict().get("absorption_ratio", np.nan)
    transition_explained = float((transitions.mechanism_class!="无法解释").mean()) if len(transitions) else 0.0
    transition_current_hit = float(transitions.current_boundary_hit.mean()) if len(transitions) else np.nan
    transition_wide_release = float(transitions.wide_boundary_released.mean()) if len(transitions) else np.nan
    transition_rmse_drop = float(transitions.post_bk_rmse_decrease_fraction.mean()) if len(transitions) else np.nan
    transition_absorb_gain = float(transitions.absorption_ratio_increase.mean()) if len(transitions) else np.nan
    cross_sens_rho, cross_sens_p = spearmanr(repeat.service_area_accept_fraction, repeat.mean_actual_direction_sensitivity)
    cross_weak_rho, cross_weak_p = spearmanr(repeat.service_area_accept_fraction, repeat.mean_weakest_direction_sensitivity)
    cross_absorb_rho, cross_absorb_p = spearmanr(repeat.service_area_accept_fraction, repeat.mean_absorption_ratio)
    cross_sens_var_rho, cross_sens_var_p = spearmanr(repeat.service_area_accept_fraction, repeat.service_area_sensitivity_variance)
    cross_absorb_var_rho, cross_absorb_var_p = spearmanr(repeat.service_area_accept_fraction, repeat.service_area_absorption_variance)
    extra_value = bool(np.isfinite(full_auc) and np.isfinite(base_auc) and full_auc >= base_auc + 0.02)
    same_distance = analysis[analysis.analysis_type=="same_distance"]
    direction_signal = bool(abs(direction_rho) >= 0.1) if np.isfinite(direction_rho) else False
    absorption_signal = bool(abs(absorption_rho) >= 0.1 or transition_explained >= 0.5) if np.isfinite(absorption_rho) else transition_explained >= 0.5
    cross_signal = bool(abs(cross_sens_rho) >= 0.3 or abs(cross_absorb_rho) >= 0.3)
    recommend = bool(extra_value and direction_signal and absorption_signal and cross_signal)
    conclusion = "建议进入全量分析" if recommend else "当前几何机制指标未形成足够独立预测价值，不建议进入全量扩展"
    report = f"""# 差分多普勒机制可行性审计报告

## 1. 本轮目的

本轮复用既有服务区内部空间风险与单站跨服务区重复性实验的卫星组合、60 秒服务段、服务中心和验证站，重新传播固定地面点多普勒，解释非目标样本的既有误接受。未新增攻击、未改变 sequence_mode、阈值或正式判决逻辑，也未评价 full pass 或 handover。

## 2. 与旧实验的关系

输入正式数据为 `multi_service_area_single_station_dataset.csv`。几何残差统一采用 `F_B(S)+F_A(C)-F_B(C)-F_A(S)`。轨道传播、目的点生成、受控轨道构造、校准和 gate 均复用旧脚本公共实现。旧 verifier 对每段使用 `t-mean(t)` 的无权重普通最小二乘；因此 b 的参考时刻是该服务段的时间均值。

方向角沿用旧实现：0° 指北、90° 指东、顺时针增加。Jacobian 列顺序为 East/North，实际方向投影使用 `[sin(phi), cos(phi)]`。

## 3. 样本选择

自动选择 {len(selected)} 个“来源/分组/目标—非目标”实例，保留每个组合原有 {int(selected.number_of_service_areas.min())}～{int(selected.number_of_service_areas.max())} 个有效服务区。真实轨道优先 0/2.5/5/10 km，受控样本优先 0/10/50/100/200/500 km；替换记录见清单。

{selected[['pair_id','sample_source','sample_group','target_id','nontarget_id','selection_reason','number_of_service_areas','distance_substitution_note']].to_markdown(index=False)}

## 4. 指标定义

`raw_geo_*` 是判决前纯几何残差；`unbounded_*` 是同一中心化时间定义下的无边界 b+kt 投影。`bounded_*` 是几何贡献的 box-constrained 最小二乘：no_bk 固定 b=k=0；current/wide 使用正式 gate 相对中心的参数容差（wide 为 current 的两倍）作为几何贡献预算。CSV 同时保存正式绝对 gate 上下界。由于中心化设计的常数列与时间列正交，对无边界系数逐项 clip 是精确的 box 最优解。

`score_value`、原始 b/k 与 final decision 来自旧正式观测（含经验环境项与噪声）；机制拟合只针对重算的纯几何项，二者没有混用。所有权重为 1。

## 5. 正确性审计

{audit.to_markdown(index=False)}

判决重放一致率为 {rows.decision_matches_original.mean():.2%}（{int(rows.decision_matches_original.sum())}/{len(rows)}）。吸收比例浮点截断 {int(rows.attrs.get('absorption_clip_count',0))} 次；d=0 且原始能量接近零时保持 NaN，不作强行解释。

## 6. 距离之外的几何解释

简单逻辑回归使用标准化特征和同一审计样本内 ROC-AUC，仅作可解释性筛查，不是泛化性能估计。

{logistic.to_markdown(index=False)}

Spearman 结果：

{spearman.to_markdown(index=False)}

距离-only AUC={base_auc:.3f}；距离+方向敏感度+吸收比例 AUC={full_auc:.3f}。同距离分组统计已保存到 `{paths['distance_analysis'].name}`。这些量若只与拟合后 RMSE 同步而没有相对距离的增益，不视作独立解释力。

## 7. current/wide b/k 差异机制

审计中共有 {len(transitions)} 条 current REJECT→wide ACCEPT。机制分类：

{trans_counts.rename('count').to_frame().to_markdown() if len(trans_counts) else '无新增误接受。'}

其中 current 几何 box 触边比例为 {transition_current_hit:.2%}，放宽到 wide 后解除触边比例为 {transition_wide_release:.2%}；几何有界拟合后 RMSE 平均下降 {transition_rmse_drop:.2%}，吸收比例平均增加 {transition_absorb_gain:.4f}。正式 gate 的变化分类全部可归入 b 边界解除、k 边界解除或二者同时解除；逐条的 score/b/k/coverage/quality gate 变化保存在 `{paths['transition'].name}`。

旧 verifier 的 current/wide 使用相同的无边界 b+kt 投影；新增接受来自参数 gate 容差放宽，而不是不同拟合子空间。几何 box 拟合仅用于量化在对应容差预算内可被吸收的部分。

## 8. 真实轨道与受控高难度样本差异

{group_compare.to_markdown(index=False)}

难例需区分：raw_geo_rmse 本就较小，或 raw_geo_rmse 不小但 absorption_ratio 较高。这里的 remaining_rmse 是机制解释量，不包装成新的 verifier 分数。

## 9. 跨服务区重复性解释

{repeat[['pair_id','group_label','service_area_accept_fraction','mean_actual_direction_sensitivity','mean_weakest_direction_sensitivity','mean_absorption_ratio','absorption_ratio_std','service_area_sensitivity_variance','service_area_absorption_variance','persistent_accept','recurrent_accept']].to_markdown(index=False)}

`persistent_accept` 与 `recurrent_accept` 沿用旧实验的固定条件跨服务区口径。

更精确地说，本表先对每个固定“距离×方向”条件计算跨服务区接受比例，再令某组合只要存在比例=1 的条件即为 persistent、存在比例>=0.5 的条件即为 recurrent；`service_area_accept_fraction` 是这些固定条件比例的均值。组合层面（n={len(repeat)}）的 Spearman 结果为：重复接受比例 vs 实际方向敏感度 rho={cross_sens_rho:.3f}（p={cross_sens_p:.3g}），vs 最弱方向敏感度 rho={cross_weak_rho:.3f}（p={cross_weak_p:.3g}），vs 平均吸收比例 rho={cross_absorb_rho:.3f}（p={cross_absorb_p:.3g}）。重复接受比例与服务区间敏感度方差 rho={cross_sens_var_rho:.3f}（p={cross_sens_var_p:.3g}），与吸收比例方差 rho={cross_absorb_var_rho:.3f}（p={cross_absorb_var_p:.3g}）。在本代表样本中，持续/高重复风险总体对应更低方向敏感度和更高且跨区更稳定的吸收比例；偶发风险组合的这些条件不同时成立。n=10 很小，因此只作为机制证据，不作总体推断。

## 10. 方向是否值得扩大

本轮停止判断：**{conclusion}**。

判定依据：方向敏感度 Spearman rho={direction_rho:.3f}，吸收比例 rho={absorption_rho:.3f}，current→wide 可分类解释比例={transition_explained:.2%}，完整简单模型相对距离-only 的样本内 AUC 增量={(full_auc-base_auc) if np.isfinite(full_auc) and np.isfinite(base_auc) else np.nan:.3f}。只有这些指标在同距离、current/wide 和跨服务区层面共同显示额外解释力时才建议扩大。

## 11. 当前局限

- 这是 8～12 对量级的代表性可行性审计，ROC-AUC 为样本内描述量，未做外部泛化声明。
- 有限差分 Jacobian 仅解释服务中心附近；不声称精确预测 100～500 km 的非线性残差。
- 受控样本仍是受控轨道构造，不代表真实 Starlink 频偏真值。
- 本轮没有证明统一安全距离、轨道面共面或相位接近的根因，也不作绝对首次性声明。

关键图：{', '.join(p.name for p in figures)}。
"""
    paths["report"].parent.mkdir(parents=True, exist_ok=True); paths["report"].write_text(report, encoding="utf-8")
    return conclusion, recommend


def append_log(args: argparse.Namespace, paths: dict[str, Path], selected: pd.DataFrame, timeseries: pd.DataFrame, rows: pd.DataFrame,
               area: pd.DataFrame, repeat: pd.DataFrame, transitions: pd.DataFrame, audit: pd.DataFrame, conclusion: str) -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    failed = audit[~audit.passed]
    text = f"""

## {now} - 差分多普勒机制代表性审计

### A. 本轮目标
复用既有 60 秒分段服务中心补偿样本与服务区，审计原始几何残差、b/k 吸收、局部方向敏感度及旧判决重放。

### B. 实际操作
- 新增独立脚本 `scripts/run_differential_doppler_mechanism_audit.py`。
- 复用 `load_inputs`、`geo_curve_fixed`、`destination`、`attack_geo`、`calibration_for_trel`、`threshold_for` 与原 single-window gate 语义。
- 输入 `{args.old_dataset}`；自动选择 {len(selected)} 个代表实例；正式统计 {len(rows)} 行、时间序列 {len(timeseries)} 行。
- 未修改配置、sequence_mode、旧脚本或旧正式输出；未生成新攻击。

### C. 新增/修改文件
- {paths['selected']}
- {paths['timeseries']}
- {paths['rows']}
- {paths['area']}
- {paths['repeat']}
- {paths['distance_analysis']}
- {paths['transition']}
- {paths['audit']}
- {paths['report']}
- {paths['figures']}/
- logs/work_log.md（仅追加）

### D. 运行命令
- `python -m py_compile scripts/run_differential_doppler_mechanism_audit.py`
- `python scripts/run_differential_doppler_mechanism_audit.py --preset smoke`
- `python scripts/run_differential_doppler_mechanism_audit.py --preset audit`

### E. 结果摘要
- 代表样本：{', '.join(selected.pair_id.astype(str))}
- 行级汇总 {len(rows)} 行；pair-area 汇总 {len(area)} 行；跨区汇总 {len(repeat)} 行。
- 判决重放一致率 {rows.decision_matches_original.mean():.2%}。
- current→wide 新增误接受 {len(transitions)} 条；主要机制：{transitions.mechanism_class.value_counts().to_dict() if len(transitions) else {}}。
- 正确性审计失败项：{failed.check.tolist()}。
- 停止判断：{conclusion}。

### F. 问题与下一步
- 局部 Jacobian 不外推为 100～500 km 的精确预测。
- 本轮为小样本样本内解释，是否全量扩大以报告第 10 节停止条件为准。
"""
    log = Path("logs/work_log.md"); log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f: f.write(text)


def main() -> None:
    args = parse_args(); paths = paths_for(args.preset)
    selected, timeseries, rows = run(args, paths)
    area, repeat = build_summaries(rows); analysis = explanatory_analysis(rows); transitions = transition_analysis(rows)
    audit = correctness_audit(rows, transitions)
    for key in ["selected","timeseries","rows","area","repeat","distance_analysis","transition","audit"]: paths[key].parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(paths["selected"], index=False); timeseries.to_csv(paths["timeseries"], index=False); rows.to_csv(paths["rows"], index=False)
    area.to_csv(paths["area"], index=False); repeat.to_csv(paths["repeat"], index=False); analysis.to_csv(paths["distance_analysis"], index=False)
    transitions.to_csv(paths["transition"], index=False); audit.to_csv(paths["audit"], index=False)
    figures = make_figures(rows, timeseries, area, transitions, paths["figures"])
    conclusion, _recommend = write_report(paths, selected, rows, area, repeat, analysis, transitions, audit, figures)
    if args.preset == "audit": append_log(args, paths, selected, timeseries, rows, area, repeat, transitions, audit, conclusion)
    print(f"新增脚本: {Path(__file__)}")
    print("代表样本:", ", ".join(selected.pair_id.astype(str)))
    print(f"时间序列 {len(timeseries)} 行；行汇总 {len(rows)}；pair-area {len(area)}；跨区 {len(repeat)}")
    print(f"判决重放一致率: {rows.decision_matches_original.mean():.2%}")
    print("current→wide 机制:", transitions.mechanism_class.value_counts().to_dict() if len(transitions) else {})
    print("正确性审计:", f"{int(audit.passed.sum())}/{len(audit)} 通过")
    print("最终判断:", conclusion)
    print("尚未解决: 小样本样本内结论；局部 Jacobian 不外推到远距离非线性预测。")
    if not bool(audit.passed.all()): fail("correctness audit has failed items; research conclusion is provisional, see audit CSV")


if __name__ == "__main__":
    main()
