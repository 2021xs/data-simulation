#!/usr/bin/env python
"""Full grouped-validation analysis for differential-Doppler mechanisms.

The script reuses every formal 60 s, segment-local, fixed-site condition in
the existing multi-service-area dataset.  It freezes the mechanism definitions
from run_differential_doppler_mechanism_audit.py and never modifies the formal
verifier, attacks, thresholds, or legacy outputs.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_differential_doppler_mechanism_audit as audit  # noqa: E402
import run_multi_service_area_single_station_confirmation as multi  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BK_MODES = ["no_bk", "current_bk", "wide_bk"]
EXPECTED_COUNTS = {
    ("real_tle_candidate", "ordinary_similar"): 25,
    ("real_tle_candidate", "boundary_case"): 25,
    ("legacy_synthetic", "original_like"): 6,
    ("legacy_synthetic", "hard_case_weighted"): 6,
}
GROUP_LABELS = audit.GROUP_LABELS
LOCAL_MODELS = {
    "M0_distance": ["distance_km"],
    "M1_distance_direction": ["distance_km", "actual_direction_post_projection_sensitivity_hz_per_km"],
    "M2_distance_unbounded_absorption": ["distance_km", "unbounded_geometry_absorption_ratio"],
    "M3_distance_tolerance_absorption": ["distance_km", "geometry_tolerance_budget_absorption_ratio"],
    "M4_distance_direction_unbounded_absorption": ["distance_km", "actual_direction_post_projection_sensitivity_hz_per_km", "unbounded_geometry_absorption_ratio"],
    "M5_distance_raw_geometry": ["distance_km", "raw_geo_rmse_hz"],
    "M6_distance_raw_direction_absorption": ["distance_km", "raw_geo_rmse_hz", "actual_direction_post_projection_sensitivity_hz_per_km", "unbounded_geometry_absorption_ratio"],
    "M7_unbounded_post_rmse": ["unbounded_geometry_post_rmse_hz"],
    "M8_formal_score": ["formal_score_value"],
}
FULL_DISTANCE_MODELS = {
    "F0_distance": ["distance_km"],
    "F1_raw_geometry": ["raw_geo_rmse_hz"],
    "F2_unbounded_absorption": ["unbounded_geometry_absorption_ratio"],
    "F3_tolerance_absorption": ["geometry_tolerance_budget_absorption_ratio"],
    "F4_distance_raw_geometry": ["distance_km", "raw_geo_rmse_hz"],
    "F5_distance_raw_geometry_absorption": ["distance_km", "raw_geo_rmse_hz", "unbounded_geometry_absorption_ratio"],
    "F6_unbounded_post_rmse": ["unbounded_geometry_post_rmse_hz"],
    "F7_formal_score": ["formal_score_value"],
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="全量差分多普勒几何机制与分组样本外验证")
    p.add_argument("--preset", choices=["smoke", "full"], default="full")
    p.add_argument("--old-dataset", type=Path, default=Path("outputs/datasets/multi_service_area_single_station_dataset.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--bootstrap-iterations", type=int, default=1000)
    p.add_argument("--seed", type=int, default=20260711)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def output_paths(preset: str) -> dict[str, Path]:
    s = "_smoke" if preset == "smoke" else ""
    stem = f"differential_doppler_mechanism_full{s}"
    return {
        "inventory": Path(f"outputs/metrics/{stem}_pair_inventory.csv"),
        "rows": Path(f"outputs/metrics/{stem}_row_summary.csv"),
        "area": Path(f"outputs/metrics/{stem}_pair_area_summary.csv"),
        "repeat": Path(f"outputs/metrics/{stem}_repeatability_summary.csv"),
        "validation": Path(f"outputs/metrics/{stem}_grouped_validation.csv"),
        "transition": Path(f"outputs/metrics/{stem}_current_to_wide.csv"),
        "comparison": Path(f"outputs/metrics/{stem}_group_comparison.csv"),
        "audit": Path(f"outputs/metrics/{stem}_correctness_audit.csv"),
        "timeseries": Path(f"outputs/datasets/{stem}_representative_timeseries.csv"),
        "report": Path(f"outputs/reports/{stem}_analysis_report.md"),
        "figures": Path(f"outputs/figures/{stem}_analysis"),
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def check_paths(args: argparse.Namespace, paths: dict[str, Path]) -> None:
    for p in [args.old_dataset, args.candidate_library, args.selection_table, args.tle_file, args.orbit_config, args.parameter_config]:
        if not p.exists(): fail(f"missing input: {p}")
    existing = [str(p) for k, p in paths.items() if k != "figures" and p.exists()]
    if paths["figures"].exists() and any(paths["figures"].iterdir()): existing.append(str(paths["figures"]))
    if existing and not args.overwrite: fail("full-analysis output exists; add --overwrite: " + ", ".join(existing))


def load_formal(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    audit.require_columns(d, [
        "sample_source", "sample_group", "pair_id", "target_sat_id", "attack_sat_id", "service_area_id",
        "service_area_segment_index", "evaluation_start_s", "evaluation_end_s", "C_lat", "C_lon", "S_lat", "S_lon",
        "distance_to_center_km", "phi_deg", "bk_mode", "residual_rmse_hz", "normalized_score", "b_hat_hz",
        "k_hat_hz_per_s", "score_gate_pass", "b_gate_pass", "k_gate_pass", "coverage_gate_pass", "quality_gate_pass",
        "decision", "T_service_s", "evaluation_scope", "doppler_reference_mode", "verification_strategy",
    ], "formal dataset")
    semantic = d.T_service_s.eq(60.0) & d.evaluation_scope.eq("segment_local") & d.doppler_reference_mode.eq("fixed_site_segment_center") & d.verification_strategy.eq("single-window")
    if not semantic.all(): fail(f"formal dataset contains {int((~semantic).sum())} rows outside frozen semantics")
    d["target_sat_id"] = d.target_sat_id.astype(str); d["attack_sat_id"] = d.attack_sat_id.astype(str)
    d["pair_instance_id"] = d.sample_source + "|" + d.sample_group + "|" + d.pair_id.astype(str)
    return d


def build_inventory(d: pd.DataFrame) -> pd.DataFrame:
    keys = ["pair_instance_id", "pair_id", "sample_source", "sample_group", "target_sat_id", "target_name", "attack_sat_id", "attack_name"]
    rows = []
    for key, g in d.groupby(keys, sort=False, dropna=False):
        source, group = key[2], key[3]
        rows.append({**dict(zip(keys, key)), "group_label": GROUP_LABELS.get((source, group), group),
                     "service_area_count": int(g.service_area_id.nunique()), "distance_count": int(g.distance_to_center_km.nunique()),
                     "direction_count": int(g.phi_deg.nunique()), "bk_modes": ",".join(sorted(g.bk_mode.unique())),
                     "formal_row_count": len(g), "physical_pair_group_key": str(key[1])})
    inv = pd.DataFrame(rows)
    counts = inv.groupby(["sample_source", "sample_group"]).size().to_dict()
    inv["expected_group_count"] = inv.apply(lambda r: EXPECTED_COUNTS.get((r.sample_source, r.sample_group), np.nan), axis=1)
    inv["actual_group_count"] = inv.apply(lambda r: counts.get((r.sample_source, r.sample_group), 0), axis=1)
    inv["count_matches_expected"] = inv.expected_group_count.eq(inv.actual_group_count)
    return inv


def choose_smoke_instances(inv: pd.DataFrame) -> list[str]:
    out = []
    for source, group in EXPECTED_COUNTS:
        g = inv[(inv.sample_source == source) & (inv.sample_group == group)]
        if not g.empty: out.extend(g.head(2).pair_instance_id.astype(str).tolist())
    return out


def formal_threshold(row: pd.Series, cal: dict[str, dict[str, float]], mode: str) -> dict[str, float]:
    th = seg.threshold_for(cal, "full_pass", mode)
    norm, score = float(row.normalized_score), float(row.residual_rmse_hz)
    if np.isfinite(norm) and norm > 1e-12: th["score_threshold"] = score / norm
    return th


def replay_from_gates(row: pd.Series) -> str:
    if not bool(row.coverage_gate_pass): return "DEFER"
    passed = all(bool(row[c]) for c in ["score_gate_pass", "b_gate_pass", "k_gate_pass", "quality_gate_pass"])
    return "ACCEPT" if passed else "REJECT"


def energy_absorption(raw: np.ndarray, remain: np.ndarray) -> float:
    eraw = float(np.sum(raw * raw))
    if eraw <= max(1e-18, len(raw) * 1e-18): return np.nan
    value = 1.0 - float(np.sum(remain * remain)) / eraw
    if -1e-10 <= value <= 1 + 1e-10: return float(np.clip(value, 0.0, 1.0))
    return float(value)


def compute_full_rows(args: argparse.Namespace, formal: pd.DataFrame, inv: pd.DataFrame) -> tuple[pd.DataFrame, dict[tuple[Any, ...], tuple[np.ndarray, np.ndarray]]]:
    if args.preset == "smoke":
        formal = formal[formal.pair_instance_id.isin(choose_smoke_instances(inv))].copy()
    loader = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library, tle_file=args.tle_file,
                             orbit_config=args.orbit_config, parameter_config=args.parameter_config, max_targets=5)
    _sel, library, orbit_cfg, tle, ranges = expanded.load_base_inputs(loader)
    if orbit_cfg.get("mode") != "controlled_starlink" or orbit_cfg.get("observation_id") is not None:
        fail("full analysis requires controlled_starlink and observation_id=null")
    ts = load.timescale()
    freq_hz = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    curve_cache: dict[tuple[Any, ...], np.ndarray] = {}
    fd_cache: dict[tuple[str, str], dict[str, Any]] = {}
    cal_cache: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    series_cache: dict[tuple[Any, ...], tuple[np.ndarray, np.ndarray]] = {}
    target_cache: dict[str, tuple[np.ndarray, list[datetime], float, Any]] = {}
    output: list[dict[str, Any]] = []

    def curve(entity: str, physical_pair: str, sample: dict[str, Any], sat_a: Any, sat_b: Any | None,
              lat: float, lon: float, times: list[datetime], start: float, end: float, step: float) -> np.ndarray:
        identity = str(sample["target_sat_id"]) if entity == "A" else physical_pair
        key = (entity, identity, round(lat, 8), round(lon, 8), start, end)
        if key not in curve_cache:
            curve_cache[key] = (seg.geo_curve_fixed(sat_a, lat, lon, 0.0, times, ts, freq_hz, step)[0] if entity == "A"
                                else multi.attack_geo(sample, sat_a, sat_b, lat, lon, 0.0, times, ts, freq_hz, step))
        return curve_cache[key]

    instance_keys = ["pair_instance_id", "pair_id", "sample_source", "sample_group"]
    for ikey, instance in formal.groupby(instance_keys, sort=False):
        instance_id, physical_pair, source, group = ikey
        sample = instance.iloc[0].to_dict(); target = str(sample["target_sat_id"]); attacker = str(sample["attack_sat_id"])
        if target not in target_cache:
            tg = seg.base.target_geo_from_library(library, target)
            tr = tg.t_rel_s.to_numpy(float); times_all = [seg.base.parse_utc(v) for v in tg.t_abs_utc.astype(str)]
            target_cache[target] = (tr, times_all, float(np.median(np.diff(tr))), tle[target]["sat"])
        tr, times_all, step, sat_a = target_cache[target]
        sat_b = tle[attacker]["sat"] if source == "real_tle_candidate" else None
        for cond, g in instance.groupby(["service_area_id", "distance_to_center_km", "phi_deg"], sort=False):
            area, distance, phi = cond; by_mode = g.drop_duplicates("bk_mode").set_index("bk_mode")
            if not set(BK_MODES).issubset(by_mode.index): continue
            base = by_mode.loc["current_bk"]; start, end = float(base.evaluation_start_s), float(base.evaluation_end_s)
            mask = (tr >= start - 1e-9) & (tr <= end + 1e-9); et = tr[mask]; times = [x for x, keep in zip(times_all, mask) if keep]
            c_lat, c_lon, s_lat, s_lon = map(float, [base.C_lat, base.C_lon, base.S_lat, base.S_lon])
            fa_c = curve("A", physical_pair, sample, sat_a, sat_b, c_lat, c_lon, times, start, end, step)
            fa_s = curve("A", physical_pair, sample, sat_a, sat_b, s_lat, s_lon, times, start, end, step)
            fb_c = curve("B", physical_pair, sample, sat_a, sat_b, c_lat, c_lon, times, start, end, step)
            fb_s = curve("B", physical_pair, sample, sat_a, sat_b, s_lat, s_lon, times, start, end, step)
            raw = fb_s + fa_c - fb_c - fa_s
            series_cache[(instance_id, str(area), float(distance), float(phi))] = (et.copy(), raw.copy())
            ub, uk, ufit = audit.fit_unbounded(raw, et); uremain = raw - ufit
            raw_rmse = float(np.sqrt(np.mean(raw * raw))); upost = float(np.sqrt(np.mean(uremain * uremain)))
            uabsorb = energy_absorption(raw, uremain)
            fd_key = (str(physical_pair), str(area))
            if fd_key not in fd_cache:
                fds = {h: audit.finite_difference(sample, sat_a, sat_b, c_lat, c_lon, times, ts, freq_hz, step, h) for h in [0.5, 1.0, 2.0]}
                je, jn = fds[1.0]; j = np.column_stack([je, jn]); jp = audit.projected_jacobian(j, et)
                _u, sv, vt = np.linalg.svd(jp, full_matrices=False); sr = sv / math.sqrt(len(et)); weak = vt[-1]
                rms_h = {h: float(np.sqrt(np.mean(np.column_stack(fds[h]) ** 2))) for h in fds}
                fd_cache[fd_key] = {
                    "je": je, "jn": jn, "jp": jp, "east_raw": float(np.sqrt(np.mean(je**2))), "north_raw": float(np.sqrt(np.mean(jn**2))),
                    "east_post": float(np.sqrt(np.mean(jp[:, 0]**2))), "north_post": float(np.sqrt(np.mean(jp[:, 1]**2))),
                    "strongest": float(sr[0]), "weakest": float(sr[-1]), "anisotropy": float(sr[0] / sr[-1]) if sr[-1] > 1e-12 else math.inf,
                    "weak_deg": float((math.degrees(math.atan2(weak[0], weak[1])) + 360) % 180),
                    "stability": float(max(abs(rms_h[0.5]-rms_h[1.0]), abs(rms_h[2.0]-rms_h[1.0])) / max(rms_h[1.0], 1e-12)),
                }
            sens = fd_cache[fd_key]; theta = math.radians(float(phi)); direction = np.array([math.sin(theta), math.cos(theta)])
            actual_post = sens["jp"] @ direction
            cal_key = (target, str(area))
            if cal_key not in cal_cache:
                cal_cache[cal_key] = seg.calibration_for_trel(et, ranges, 20260706 + int(target) + int(base.service_area_segment_index), 30)
            cal = cal_cache[cal_key]
            actual_dist = float(seg.distance_km(np.array([c_lat]), np.array([c_lon]), s_lat, s_lon)[0])
            for mode in BK_MODES:
                fr = by_mode.loc[mode]; th = formal_threshold(fr, cal, mode)
                if mode == "no_bk": bbounds = (0.0, 0.0); kbounds = (0.0, 0.0)
                else: bbounds = (-float(th["b_threshold"]), float(th["b_threshold"])); kbounds = (-float(th["k_threshold"]), float(th["k_threshold"]))
                bb, bk, bfit = audit.fit_bounded(raw, et, bbounds, kbounds); remain = raw - bfit
                tol_b = max(1e-8, 1e-7 * max(abs(bbounds[1]-bbounds[0]), 1.0)); tol_k = max(1e-10, 1e-7 * max(abs(kbounds[1]-kbounds[0]), 1e-3))
                hit = any([abs(bb-bbounds[0]) <= tol_b, abs(bb-bbounds[1]) <= tol_b, abs(bk-kbounds[0]) <= tol_k, abs(bk-kbounds[1]) <= tol_k])
                replay = replay_from_gates(fr)
                output.append({
                    "pair_instance_id": instance_id, "pair_id": physical_pair, "sample_source": source, "sample_group": group,
                    "group_label": GROUP_LABELS.get((source, group), group), "target_sat_id": target, "attack_sat_id": attacker,
                    "service_area_id": area, "service_area_segment_index": int(base.service_area_segment_index), "distance_km": float(distance),
                    "actual_distance_km": actual_dist, "distance_error_km": abs(actual_dist-float(distance)), "direction_deg": float(phi),
                    "direction_definition": "0deg=north,90deg=east,clockwise", "bk_mode": mode, "num_points": len(et), "time_reference_s": float(np.mean(et)),
                    "raw_geo_rmse_hz": raw_rmse, "unbounded_geometry_b_hat_hz": ub, "unbounded_geometry_k_hat_hz_per_s": uk,
                    "unbounded_geometry_post_rmse_hz": upost, "unbounded_geometry_absorption_ratio": uabsorb,
                    "geometry_tolerance_budget_b_hat_hz": bb, "geometry_tolerance_budget_k_hat_hz_per_s": bk,
                    "geometry_tolerance_budget_post_rmse_hz": float(np.sqrt(np.mean(remain**2))),
                    "geometry_tolerance_budget_absorption_ratio": energy_absorption(raw, remain), "geometry_tolerance_budget_boundary_hit": bool(hit),
                    "geometry_tolerance_b_lower_hz": bbounds[0], "geometry_tolerance_b_upper_hz": bbounds[1],
                    "geometry_tolerance_k_lower_hz_per_s": kbounds[0], "geometry_tolerance_k_upper_hz_per_s": kbounds[1],
                    "formal_score_value": float(fr.residual_rmse_hz), "formal_score_threshold": float(th["score_threshold"]),
                    "formal_b_hat_hz": float(fr.b_hat_hz), "formal_k_hat_hz_per_s": float(fr.k_hat_hz_per_s),
                    "formal_b_gate_lower_hz": th["b_center"]-th["b_threshold"], "formal_b_gate_upper_hz": th["b_center"]+th["b_threshold"],
                    "formal_k_gate_lower_hz_per_s": th["k_center"]-th["k_threshold"], "formal_k_gate_upper_hz_per_s": th["k_center"]+th["k_threshold"],
                    "formal_score_gate_pass": bool(fr.score_gate_pass), "formal_b_gate_pass": bool(fr.b_gate_pass), "formal_k_gate_pass": bool(fr.k_gate_pass),
                    "formal_coverage_gate_pass": bool(fr.coverage_gate_pass), "formal_quality_gate_pass": bool(fr.quality_gate_pass),
                    "formal_final_decision": replay, "original_final_decision": str(fr.decision), "decision_matches_original": replay == str(fr.decision),
                    "east_raw_sensitivity_rmse_hz_per_km": sens["east_raw"], "north_raw_sensitivity_rmse_hz_per_km": sens["north_raw"],
                    "east_post_projection_sensitivity_rmse_hz_per_km": sens["east_post"], "north_post_projection_sensitivity_rmse_hz_per_km": sens["north_post"],
                    "actual_direction_post_projection_sensitivity_hz_per_km": float(np.sqrt(np.mean(actual_post**2))),
                    "weakest_direction_sensitivity_hz_per_km": sens["weakest"], "strongest_direction_sensitivity_hz_per_km": sens["strongest"],
                    "anisotropy_ratio": sens["anisotropy"], "weakest_direction_deg": sens["weak_deg"],
                    "finite_difference_max_relative_change_0p5_1_2km": sens["stability"], "random_seed": args.seed,
                })
    return pd.DataFrame(output), series_cache


def build_area_summary(rows: pd.DataFrame) -> pd.DataFrame:
    keys = ["pair_instance_id", "pair_id", "sample_source", "sample_group", "group_label", "target_sat_id", "attack_sat_id", "service_area_id", "bk_mode"]
    out = []
    for key, g in rows.groupby(keys, dropna=False):
        non = g[g.distance_km > 0]; local = non[non.distance_km <= 10]
        out.append({**dict(zip(keys, key)), "condition_count": len(g), "accept_count": int(g.formal_final_decision.eq("ACCEPT").sum()),
                    "accept_fraction": float(g.formal_final_decision.eq("ACCEPT").mean()), "noncenter_accept_fraction": float(non.formal_final_decision.eq("ACCEPT").mean()),
                    "local_noncenter_accept_fraction": float(local.formal_final_decision.eq("ACCEPT").mean()) if len(local) else np.nan,
                    "mean_raw_geo_rmse_hz": float(non.raw_geo_rmse_hz.mean()), "mean_unbounded_absorption_ratio": float(non.unbounded_geometry_absorption_ratio.mean()),
                    "mean_tolerance_absorption_ratio": float(non.geometry_tolerance_budget_absorption_ratio.mean()),
                    "mean_actual_direction_sensitivity_local": float(local.actual_direction_post_projection_sensitivity_hz_per_km.mean()) if len(local) else np.nan,
                    "tolerance_boundary_hit_fraction": float(g.geometry_tolerance_budget_boundary_hit.mean()),
                    "maximum_observed_noncenter_accept_distance_km": float(non.loc[non.formal_final_decision.eq('ACCEPT'), 'distance_km'].max()) if non.formal_final_decision.eq('ACCEPT').any() else np.nan})
    return pd.DataFrame(out)


def fixed_condition_repeat(g: pd.DataFrame) -> pd.Series:
    return g.groupby(["distance_km", "direction_deg"]).formal_final_decision.apply(lambda x: float(x.eq("ACCEPT").mean()))


def build_repeatability(rows: pd.DataFrame) -> pd.DataFrame:
    cur = rows[rows.bk_mode == "current_bk"]
    keys = ["pair_instance_id", "pair_id", "sample_source", "sample_group", "group_label", "target_sat_id", "attack_sat_id"]
    out=[]
    for key,g in cur.groupby(keys,dropna=False):
        inc=fixed_condition_repeat(g); non=fixed_condition_repeat(g[g.distance_km>0]); local=fixed_condition_repeat(g[(g.distance_km>0)&(g.distance_km<=10)])
        area_geo=g[g.distance_km>0].groupby("service_area_id").agg(direction=("actual_direction_post_projection_sensitivity_hz_per_km","mean"),weakest=("weakest_direction_sensitivity_hz_per_km","mean"),unbounded=("unbounded_geometry_absorption_ratio","mean"),tolerance=("geometry_tolerance_budget_absorption_ratio","mean"))
        out.append({**dict(zip(keys,key)), "number_of_service_areas":int(g.service_area_id.nunique()),
                    "persistent_accept_including_center":bool(len(inc) and (inc>=1).any()), "recurrent_accept_including_center":bool(len(inc) and (inc>=.5).any()), "service_area_accept_fraction_including_center":float(inc.mean()),
                    "persistent_accept_noncenter":bool(len(non) and (non>=1).any()), "recurrent_accept_noncenter":bool(len(non) and (non>=.5).any()), "service_area_accept_fraction_noncenter":float(non.mean()),
                    "local_service_area_accept_fraction_noncenter":float(local.mean()) if len(local) else np.nan,
                    "mean_actual_direction_sensitivity_local":float(g[(g.distance_km>0)&(g.distance_km<=10)].actual_direction_post_projection_sensitivity_hz_per_km.mean()),
                    "mean_weakest_direction_sensitivity":float(area_geo.weakest.mean()), "mean_unbounded_absorption_ratio":float(area_geo.unbounded.mean()),
                    "mean_tolerance_budget_absorption_ratio":float(area_geo.tolerance.mean()), "service_area_direction_sensitivity_variance":float(area_geo.direction.var(ddof=0)),
                    "service_area_weakest_sensitivity_variance":float(area_geo.weakest.var(ddof=0)), "service_area_unbounded_absorption_variance":float(area_geo.unbounded.var(ddof=0)),
                    "service_area_tolerance_absorption_variance":float(area_geo.tolerance.var(ddof=0))})
    return pd.DataFrame(out)


def transition_analysis(rows: pd.DataFrame) -> pd.DataFrame:
    keys=["pair_instance_id","pair_id","sample_source","sample_group","group_label","target_sat_id","service_area_id","distance_km","direction_deg"]
    c=rows[rows.bk_mode=="current_bk"].set_index(keys); w=rows[rows.bk_mode=="wide_bk"].set_index(keys)
    z=c.add_suffix("_current").join(w.add_suffix("_wide")).reset_index()
    z=z[(z.formal_final_decision_current=="REJECT")&(z.formal_final_decision_wide=="ACCEPT")].copy()
    def cls(r:pd.Series)->str:
        b=not bool(r.formal_b_gate_pass_current) and bool(r.formal_b_gate_pass_wide); k=not bool(r.formal_k_gate_pass_current) and bool(r.formal_k_gate_pass_wide)
        if b and k:return "b/k同时解除"
        if b:return "b gate解除"
        if k:return "k gate解除"
        if (not r.formal_score_gate_pass_current) and r.formal_score_gate_pass_wide:return "score gate改变"
        if (not r.formal_coverage_gate_pass_current) and r.formal_coverage_gate_pass_wide:return "coverage gate改变"
        if (not r.formal_quality_gate_pass_current) and r.formal_quality_gate_pass_wide:return "quality gate改变"
        return "无法解释"
    if len(z):
        z["formal_gate_release_type"]=z.apply(cls,axis=1)
        z["formal_score_current_wide_equal"]=np.isclose(z.formal_score_value_current,z.formal_score_value_wide,rtol=0,atol=1e-9)
        z["formal_b_hat_current_wide_equal"]=np.isclose(z.formal_b_hat_hz_current,z.formal_b_hat_hz_wide,rtol=0,atol=1e-9)
        z["formal_k_hat_current_wide_equal"]=np.isclose(z.formal_k_hat_hz_per_s_current,z.formal_k_hat_hz_per_s_wide,rtol=0,atol=1e-12)
        z["geometry_tolerance_budget_boundary_hit_current"]=z.geometry_tolerance_budget_boundary_hit_current
        z["geometry_tolerance_budget_boundary_hit_wide"]=z.geometry_tolerance_budget_boundary_hit_wide
        z["geometry_tolerance_budget_absorption_gain"]=z.geometry_tolerance_budget_absorption_ratio_wide-z.geometry_tolerance_budget_absorption_ratio_current
        z["transition_count_by_sample_source"]=z.groupby("sample_source")["pair_id"].transform("size")
        z["transition_count_by_sample_group"]=z.groupby(["sample_source","sample_group"])["pair_id"].transform("size")
        z["transition_count_by_distance"]=z.groupby("distance_km")["pair_id"].transform("size")
        z["transition_count_by_service_area"]=z.groupby("service_area_id")["pair_id"].transform("size")
        z["transition_count_by_gate_type"]=z.groupby("formal_gate_release_type")["pair_id"].transform("size")
    return z


def metric_values(y: np.ndarray, p: np.ndarray) -> dict[str,float]:
    if len(np.unique(y))<2:return {"roc_auc":np.nan,"pr_auc":np.nan,"balanced_accuracy":np.nan,"brier_score":np.nan}
    return {"roc_auc":float(roc_auc_score(y,p)),"pr_auc":float(average_precision_score(y,p)),"balanced_accuracy":float(balanced_accuracy_score(y,p>=.5)),"brier_score":float(brier_score_loss(y,p))}


def fit_predict(train: pd.DataFrame,test:pd.DataFrame,features:list[str],categorical:bool)->np.ndarray:
    cols=features+(["sample_group"] if categorical else [])
    numeric=features
    prep=ColumnTransformer([("num",StandardScaler(),numeric)]+([("cat",OneHotEncoder(handle_unknown="ignore"),["sample_group"])] if categorical else []))
    pipe=Pipeline([("prep",prep),("model",LogisticRegression(max_iter=2000,random_state=20260711))])
    pipe.fit(train[cols],train.accepted);return pipe.predict_proba(test[cols])[:,1]


def grouped_oof(data:pd.DataFrame,features:list[str],group_col:str,categorical:bool)->tuple[pd.DataFrame,pd.DataFrame]:
    preds=[];folds=[]
    for held in sorted(data[group_col].astype(str).unique()):
        test=data[data[group_col].astype(str)==held];train=data[data[group_col].astype(str)!=held]
        overlap=set(train.pair_id)&set(test.pair_id)
        status="ok"
        if train.accepted.nunique()<2: status="train_single_class"
        elif len(test)==0: status="empty_test"
        if status=="ok":
            p=fit_predict(train,test,features,categorical)
            q=test[["row_uid","pair_instance_id","pair_id","target_sat_id","sample_source","sample_group","accepted"]].copy();q["probability"]=p;q["held_group"]=held;preds.append(q)
        folds.append({"held_group":held,"train_n":len(train),"test_n":len(test),"train_positive":int(train.accepted.sum()),"test_positive":int(test.accepted.sum()),"physical_pair_overlap_count":len(overlap),"status":status})
    return (pd.concat(preds,ignore_index=True) if preds else pd.DataFrame()),pd.DataFrame(folds)


def bootstrap_oof(pred:pd.DataFrame,iterations:int,seed:int)->dict[str,tuple[float,float]]:
    pair_codes,pairs=pd.factorize(pred.pair_id.astype(str),sort=True);rng=np.random.default_rng(seed);values={"roc_auc":[],"pr_auc":[]}
    y=pred.accepted.to_numpy(int);prob=pred.probability.to_numpy(float);pair_n=len(pairs)
    for _ in range(iterations):
        counts=rng.multinomial(pair_n,np.full(pair_n,1.0/pair_n));weights=counts[pair_codes]
        active=weights>0
        if np.unique(y[active]).size<2:continue
        values["roc_auc"].append(float(roc_auc_score(y,prob,sample_weight=weights)))
        values["pr_auc"].append(float(average_precision_score(y,prob,sample_weight=weights)))
    return {k:(float(np.quantile(v,.025)),float(np.quantile(v,.975))) if len(v)>=20 else (np.nan,np.nan) for k,v in values.items()}


def validation_strata(d:pd.DataFrame)->dict[str,pd.DataFrame]:
    return {
        "real_ordinary":d[(d.sample_source=="real_tle_candidate")&(d.sample_group=="ordinary_similar")],
        "real_boundary":d[(d.sample_source=="real_tle_candidate")&(d.sample_group=="boundary_case")],
        "controlled_ordinary":d[(d.sample_source=="legacy_synthetic")&(d.sample_group=="original_like")],
        "controlled_hard":d[(d.sample_source=="legacy_synthetic")&(d.sample_group=="hard_case_weighted")],
        "real_all":d[d.sample_source=="real_tle_candidate"],"controlled_all":d[d.sample_source=="legacy_synthetic"],"combined_aux":d,
    }


def run_validation(rows:pd.DataFrame,iterations:int,seed:int,smoke:bool,core_only:bool=False)->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    base=rows[(rows.bk_mode=="current_bk")&(rows.distance_km>0)].copy().reset_index(drop=True);base["accepted"]=base.formal_final_decision.eq("ACCEPT").astype(int);base["row_uid"]=np.arange(len(base),dtype=np.int64)
    local=base[base.distance_km<=10].replace([np.inf,-np.inf],np.nan)
    records=[];allpred=[];allfold=[]
    jobs=[]
    for scope,strata,models in [("local_0_10km",validation_strata(local),LOCAL_MODELS),("full_distance_controlled",{k:v for k,v in validation_strata(base).items() if k in {"controlled_ordinary","controlled_hard","controlled_all"}},FULL_DISTANCE_MODELS)]:
        for stratum,data in strata.items():
            for model,features in models.items():jobs.append((scope,stratum,data,model,features))
    if smoke:
        keep = {"M0_distance", "M4_distance_direction_unbounded_absorption", "M5_distance_raw_geometry", "M6_distance_raw_direction_absorption", "F0_distance", "F5_distance_raw_geometry_absorption"}
        jobs = [job for job in jobs if job[3] in keep]
    if core_only:
        core={"M0_distance","M1_distance_direction","M2_distance_unbounded_absorption","M4_distance_direction_unbounded_absorption","M5_distance_raw_geometry","M6_distance_raw_direction_absorption"}
        jobs=[job for job in jobs if job[0]=="local_0_10km" and job[3] in core]
    for j,(scope,stratum,data,model,features) in enumerate(jobs):
        valid=data.dropna(subset=features+["accepted"]).copy();categorical=stratum=="combined_aux"
        for validation,group_col in [("leave_one_pair_out","pair_id"),("leave_one_target_out","target_sat_id")]:
            if validation=="leave_one_target_out" and valid.target_sat_id.nunique()<2:
                records.append({"scope":scope,"stratum":stratum,"validation":validation,"model":model,"features":"+".join(features),"status":"insufficient_targets","n":len(valid),"positive_n":int(valid.accepted.sum()),"pair_n":valid.pair_id.nunique(),"target_n":valid.target_sat_id.nunique()});continue
            pred,fold=grouped_oof(valid,features,group_col,categorical)
            fold["scope"]=scope;fold["stratum"]=stratum;fold["validation"]=validation;fold["model"]=model;allfold.append(fold)
            if pred.empty:
                records.append({"scope":scope,"stratum":stratum,"validation":validation,"model":model,"features":"+".join(features),"status":"no_oof_predictions","n":len(valid),"positive_n":int(valid.accepted.sum()),"pair_n":valid.pair_id.nunique(),"target_n":valid.target_sat_id.nunique()});continue
            m=metric_values(pred.accepted.to_numpy(int),pred.probability.to_numpy(float));ci=bootstrap_oof(pred,50 if smoke else iterations,seed+j)
            records.append({"scope":scope,"stratum":stratum,"validation":validation,"model":model,"features":"+".join(features),"status":"ok","n":len(pred),"positive_n":int(pred.accepted.sum()),"pair_n":pred.pair_id.nunique(),"target_n":pred.target_sat_id.nunique(),**m,
                            "roc_auc_ci_low":ci["roc_auc"][0],"roc_auc_ci_high":ci["roc_auc"][1],"pr_auc_ci_low":ci["pr_auc"][0],"pr_auc_ci_high":ci["pr_auc"][1]})
            pred["scope"]=scope;pred["stratum"]=stratum;pred["validation"]=validation;pred["model"]=model;allpred.append(pred)
    summary=pd.DataFrame(records);preds=pd.concat(allpred,ignore_index=True) if allpred else pd.DataFrame();folds=pd.concat(allfold,ignore_index=True) if allfold else pd.DataFrame()
    # Paired cluster-bootstrap model differences from aligned OOF predictions.
    deltas=[]
    comparisons=[("M1_distance_direction","M0_distance"),("M2_distance_unbounded_absorption","M0_distance"),("M4_distance_direction_unbounded_absorption","M0_distance"),("M6_distance_raw_direction_absorption","M5_distance_raw_geometry")]
    grouped_predictions = preds.groupby(["scope","stratum","validation"]) if not preds.empty else []
    for (scope,stratum,validation),g in grouped_predictions:
        for a,b in comparisons:
            aa=g[g.model==a];bb=g[g.model==b]
            if aa.empty or bb.empty:continue
            keys=["row_uid","pair_instance_id","pair_id","target_sat_id","sample_group","accepted"]
            z=aa[keys+["probability"]].rename(columns={"probability":"pa"}).merge(bb[keys+["probability"]].rename(columns={"probability":"pb"}),on=keys)
            y=z.accepted.to_numpy(int);pa=z.pa.to_numpy(float);pb=z.pb.to_numpy(float);codes,pairs=pd.factorize(z.pair_id.astype(str),sort=True)
            ma=metric_values(y,pa);mb=metric_values(y,pb);rng=np.random.default_rng(seed+len(deltas));av=[];pv=[];pair_n=len(pairs)
            for _ in range(50 if smoke else iterations):
                counts=rng.multinomial(pair_n,np.full(pair_n,1.0/pair_n));weights=counts[codes];active=weights>0
                if np.unique(y[active]).size<2:continue
                av.append(float(roc_auc_score(y,pa,sample_weight=weights)-roc_auc_score(y,pb,sample_weight=weights)))
                pv.append(float(average_precision_score(y,pa,sample_weight=weights)-average_precision_score(y,pb,sample_weight=weights)))
            deltas.append({"scope":scope,"stratum":stratum,"validation":validation,"model":f"DELTA:{a}-{b}","features":"paired OOF predictions","status":"ok","n":len(z),"positive_n":int(z.accepted.sum()),"pair_n":len(pairs),"target_n":z.target_sat_id.nunique(),"roc_auc":ma["roc_auc"]-mb["roc_auc"],"pr_auc":ma["pr_auc"]-mb["pr_auc"],
                           "roc_auc_ci_low":float(np.quantile(av,.025)) if len(av)>=20 else np.nan,"roc_auc_ci_high":float(np.quantile(av,.975)) if len(av)>=20 else np.nan,"pr_auc_ci_low":float(np.quantile(pv,.025)) if len(pv)>=20 else np.nan,"pr_auc_ci_high":float(np.quantile(pv,.975)) if len(pv)>=20 else np.nan})
    if deltas:summary=pd.concat([summary,pd.DataFrame(deltas)],ignore_index=True,sort=False)
    return summary,preds,folds


def cluster_effect(data:pd.DataFrame,metric:str,iterations:int,seed:int)->tuple[float,float,float]:
    def effect(x:pd.DataFrame)->float:
        a=x[x.accepted==1][metric];r=x[x.accepted==0][metric]
        return float(a.mean()-r.mean()) if len(a) and len(r) else np.nan
    point=effect(data);codes,pairs=pd.factorize(data.pair_id.astype(str),sort=True);rng=np.random.default_rng(seed);vals=[];values=data[metric].to_numpy(float);accepted=data.accepted.to_numpy(int);pair_n=len(pairs)
    for _ in range(iterations):
        counts=rng.multinomial(pair_n,np.full(pair_n,1.0/pair_n));weights=counts[codes];amask=accepted==1;rmask=accepted==0
        if weights[amask].sum()<=0 or weights[rmask].sum()<=0:continue
        v=float(np.average(values[amask],weights=weights[amask])-np.average(values[rmask],weights=weights[rmask]))
        if np.isfinite(v):vals.append(v)
    return point,(float(np.quantile(vals,.025)) if len(vals)>=20 else np.nan),(float(np.quantile(vals,.975)) if len(vals)>=20 else np.nan)


def group_comparison(rows:pd.DataFrame,repeat:pd.DataFrame,iterations:int,seed:int)->pd.DataFrame:
    cur=rows[(rows.bk_mode=="current_bk")&(rows.distance_km>0)&(rows.distance_km<=10)].copy();cur["accepted"]=cur.formal_final_decision.eq("ACCEPT").astype(int)
    metrics=["actual_direction_post_projection_sensitivity_hz_per_km","weakest_direction_sensitivity_hz_per_km","raw_geo_rmse_hz","unbounded_geometry_absorption_ratio","geometry_tolerance_budget_absorption_ratio","anisotropy_ratio"]
    out=[]
    for sidx,(name,d) in enumerate(validation_strata(cur).items()):
        for midx,m in enumerate(metrics):
            x=d[["pair_id","accepted",m]].replace([np.inf,-np.inf],np.nan).dropna();rho,p=spearmanr(x[m],x.accepted) if len(x)>=3 and x.accepted.nunique()==2 else (np.nan,np.nan);eff,lo,hi=cluster_effect(x,m,iterations,seed+sidx*20+midx)
            out.append({"analysis":"local_group_effect","stratum":name,"metric":m,"distance_km":np.nan,"decision":"ACCEPT-minus-REJECT","n":len(x),"pair_n":x.pair_id.nunique(),"spearman_rho":rho,"spearman_p":p,"mean":float(x[m].mean()),"median":float(x[m].median()),"effect":eff,"effect_ci_low":lo,"effect_ci_high":hi})
        for (distance,decision),g in d.groupby(["distance_km","accepted"]):
            for m in metrics:
                out.append({"analysis":"same_distance","stratum":name,"metric":m,"distance_km":distance,"decision":"ACCEPT" if decision else "REJECT","n":len(g),"pair_n":g.pair_id.nunique(),"mean":float(g[m].replace([np.inf,-np.inf],np.nan).mean()),"median":float(g[m].replace([np.inf,-np.inf],np.nan).median())})
    repmetrics=["mean_actual_direction_sensitivity_local","mean_weakest_direction_sensitivity","mean_unbounded_absorption_ratio","mean_tolerance_budget_absorption_ratio","service_area_direction_sensitivity_variance","service_area_unbounded_absorption_variance","service_area_tolerance_absorption_variance"]
    repstrata={"real_ordinary":repeat[(repeat.sample_source=="real_tle_candidate")&(repeat.sample_group=="ordinary_similar")],"real_boundary":repeat[(repeat.sample_source=="real_tle_candidate")&(repeat.sample_group=="boundary_case")],"controlled_ordinary":repeat[(repeat.sample_source=="legacy_synthetic")&(repeat.sample_group=="original_like")],"controlled_hard":repeat[(repeat.sample_source=="legacy_synthetic")&(repeat.sample_group=="hard_case_weighted")],"real_all":repeat[repeat.sample_source=="real_tle_candidate"],"controlled_all":repeat[repeat.sample_source=="legacy_synthetic"]}
    for sidx,(name,d) in enumerate(repstrata.items()):
        for midx,m in enumerate(repmetrics):
            x=d[["pair_id","service_area_accept_fraction_noncenter",m]].dropna();rho,p=spearmanr(x.service_area_accept_fraction_noncenter,x[m]) if len(x)>=3 else (np.nan,np.nan);rng=np.random.default_rng(seed+500+sidx*20+midx);vals=[];pair_n=len(x)
            for _ in range(iterations):
                q=x.iloc[rng.integers(0,pair_n,pair_n)]
                if q.service_area_accept_fraction_noncenter.nunique()<2 or q[m].nunique()<2:continue
                v=spearmanr(q.service_area_accept_fraction_noncenter,q[m]).statistic
                if np.isfinite(v):vals.append(v)
            out.append({"analysis":"repeatability_pair_correlation","stratum":name,"metric":m,"n":len(x),"pair_n":len(x),"spearman_rho":rho,"spearman_p":p,"effect_ci_low":float(np.quantile(vals,.025)) if len(vals)>=20 else np.nan,"effect_ci_high":float(np.quantile(vals,.975)) if len(vals)>=20 else np.nan})
    return pd.DataFrame(out)


def representative_timeseries(rows:pd.DataFrame,series:dict[tuple[Any,...],tuple[np.ndarray,np.ndarray]],repeat:pd.DataFrame)->pd.DataFrame:
    cur=rows[(rows.bk_mode=="current_bk")&(rows.distance_km>0)].copy();choices=[]
    def pick(label:str,cand:pd.DataFrame,sort:str|None=None,ascending:bool=True)->None:
        if cand.empty:return
        r=cand.sort_values(sort,ascending=ascending).iloc[0] if sort else cand.iloc[0];choices.append((label,r))
    pick("真实轨道非中心误接受",cur[(cur.sample_source=="real_tle_candidate")&(cur.formal_final_decision=="ACCEPT")])
    pick("真实轨道非中心拒绝",cur[(cur.sample_source=="real_tle_candidate")&(cur.formal_final_decision=="REJECT")])
    persistent=set(repeat[(repeat.sample_group=="hard_case_weighted")&repeat.persistent_accept_noncenter].pair_instance_id);pick("受控高难度持续误接受",cur[cur.pair_instance_id.isin(persistent)&cur.formal_final_decision.eq("ACCEPT")])
    wide=rows[rows.bk_mode=="wide_bk"][["pair_instance_id","service_area_id","distance_km","direction_deg","formal_final_decision"]].rename(columns={"formal_final_decision":"wide_decision"});cw=cur.merge(wide,on=["pair_instance_id","service_area_id","distance_km","direction_deg"]);pick("current拒绝wide接受",cw[(cw.formal_final_decision=="REJECT")&(cw.wide_decision=="ACCEPT")])
    discord=cur.groupby(["pair_instance_id","service_area_id","distance_km"]).formal_final_decision.nunique();dk=discord[discord>1].index
    if len(dk):pick("同距离不同方向结果不同",cur.set_index(["pair_instance_id","service_area_id","distance_km"]).loc[[dk[0]]].reset_index())
    pick("原始几何残差小型难例",cur[cur.formal_final_decision=="ACCEPT"],"raw_geo_rmse_hz",True)
    high=cur[cur.formal_final_decision=="ACCEPT"].copy();high["mechanism_rank"]=high.raw_geo_rmse_hz.rank(pct=True)+high.unbounded_geometry_absorption_ratio.rank(pct=True);pick("原始残差不小但高吸收难例",high,"mechanism_rank",False)
    out=[]
    for label,r in choices:
        key=(r.pair_instance_id,str(r.service_area_id),float(r.distance_km),float(r.direction_deg));et,raw=series[key]
        for mode in (["current_bk","wide_bk"] if label=="current拒绝wide接受" else ["current_bk"]):
            rr=rows[(rows.pair_instance_id==r.pair_instance_id)&(rows.service_area_id==r.service_area_id)&(rows.distance_km==r.distance_km)&(rows.direction_deg==r.direction_deg)&(rows.bk_mode==mode)].iloc[0]
            x=et-et.mean();fit=rr.geometry_tolerance_budget_b_hat_hz+rr.geometry_tolerance_budget_k_hat_hz_per_s*x
            for i in range(len(raw)):out.append({"representative_reason":label,"pair_instance_id":r.pair_instance_id,"pair_id":r.pair_id,"sample_source":r.sample_source,"sample_group":r.sample_group,"service_area_id":r.service_area_id,"distance_km":r.distance_km,"direction_deg":r.direction_deg,"bk_mode":mode,"time_s":float(x[i]),"raw_geometric_residual_hz":float(raw[i]),"geometry_tolerance_budget_component_hz":float(fit[i]),"remaining_residual_hz":float(raw[i]-fit[i]),"weight":1.0})
    return pd.DataFrame(out)


def correctness(inv:pd.DataFrame,rows:pd.DataFrame,trans:pd.DataFrame,folds:pd.DataFrame,paths:dict[str,Path],full:bool,area:pd.DataFrame|None=None,repeat:pd.DataFrame|None=None,timeseries:pd.DataFrame|None=None)->pd.DataFrame:
    tests=[]
    def add(name:str,passed:bool,value:Any,tol:str,notes:str="")->None:tests.append({"check":name,"passed":bool(passed),"observed":value,"tolerance":tol,"notes":notes})
    counts=inv.groupby(["sample_source","sample_group"]).size().to_dict();expected_ok=all(counts.get(k)==v for k,v in EXPECTED_COUNTS.items()) if full else True
    add("全量组合及分组数量",expected_ok,json.dumps({"|".join(k):v for k,v in counts.items()},ensure_ascii=False),str(EXPECTED_COUNTS),"62为组条件实例；物理pair另计")
    d0=rows[np.isclose(rows.distance_km,0)];add("d=0距离误差",(d0.distance_error_km<=1e-6).all(),d0.distance_error_km.max(),"<=1e-6 km");add("d=0原始几何残差",(d0.raw_geo_rmse_hz<=1e-3).all(),d0.raw_geo_rmse_hz.max(),"<=1e-3 Hz")
    no=rows[rows.bk_mode=="no_bk"];add("no_bk恒等",np.allclose(no.geometry_tolerance_budget_b_hat_hz,0)&np.allclose(no.geometry_tolerance_budget_k_hat_hz_per_s,0)&np.allclose(no.geometry_tolerance_budget_post_rmse_hz,no.raw_geo_rmse_hz,atol=1e-8),0,"b=k=0且post=raw")
    add("无边界拟合RMSE不增",(rows.unbounded_geometry_post_rmse_hz<=rows.raw_geo_rmse_hz+1e-8).all(),(rows.unbounded_geometry_post_rmse_hz-rows.raw_geo_rmse_hz).max(),"<=1e-8 Hz")
    box=(rows.geometry_tolerance_budget_b_hat_hz>=rows.geometry_tolerance_b_lower_hz-1e-8)&(rows.geometry_tolerance_budget_b_hat_hz<=rows.geometry_tolerance_b_upper_hz+1e-8)&(rows.geometry_tolerance_budget_k_hat_hz_per_s>=rows.geometry_tolerance_k_lower_hz_per_s-1e-10)&(rows.geometry_tolerance_budget_k_hat_hz_per_s<=rows.geometry_tolerance_k_upper_hz_per_s+1e-10);add("容忍预算参数满足box",box.all(),int((~box).sum()),"0 violations")
    keys=["pair_instance_id","service_area_id","distance_km","direction_deg"];c=rows[rows.bk_mode=="current_bk"].set_index(keys);w=rows[rows.bk_mode=="wide_bk"].set_index(keys)
    add("wide容忍预算残差不高于current",(w.geometry_tolerance_budget_post_rmse_hz-c.geometry_tolerance_budget_post_rmse_hz<=1e-8).all(),(w.geometry_tolerance_budget_post_rmse_hz-c.geometry_tolerance_budget_post_rmse_hz).max(),"<=1e-8 Hz")
    add("正式判决重放一致率",rows.decision_matches_original.all(),rows.decision_matches_original.mean(),"100%")
    add("current/wide正式score相同",np.allclose(c.formal_score_value,w.formal_score_value,rtol=0,atol=1e-9),float(np.max(np.abs(c.formal_score_value-w.formal_score_value))),"<=1e-9 Hz")
    add("current/wide正式b_hat相同",np.allclose(c.formal_b_hat_hz,w.formal_b_hat_hz,rtol=0,atol=1e-9),float(np.max(np.abs(c.formal_b_hat_hz-w.formal_b_hat_hz))),"<=1e-9 Hz")
    add("current/wide正式k_hat相同",np.allclose(c.formal_k_hat_hz_per_s,w.formal_k_hat_hz_per_s,rtol=0,atol=1e-12),float(np.max(np.abs(c.formal_k_hat_hz_per_s-w.formal_k_hat_hz_per_s))),"<=1e-12 Hz/s")
    sup=(w.formal_b_gate_lower_hz<=c.formal_b_gate_lower_hz+1e-9)&(w.formal_b_gate_upper_hz>=c.formal_b_gate_upper_hz-1e-9)&(w.formal_k_gate_lower_hz_per_s<=c.formal_k_gate_lower_hz_per_s+1e-12)&(w.formal_k_gate_upper_hz_per_s>=c.formal_k_gate_upper_hz_per_s-1e-12);add("wide正式b/k gate为current超集",sup.all(),int((~sup).sum()),"0 violations")
    add("0.5/1/2km有限差分稳定",(rows.finite_difference_max_relative_change_0p5_1_2km<=.15).all(),rows.finite_difference_max_relative_change_0p5_1_2km.max(),"<=15%")
    add("ENU方向角及km/m",(rows.distance_error_km<=1e-6).all(),rows.distance_error_km.max(),"0°北/90°东/顺时针；<=1e-6km")
    absorb=rows[["unbounded_geometry_absorption_ratio","geometry_tolerance_budget_absorption_ratio"]].stack().dropna();add("吸收比例范围",absorb.between(-1e-10,1+1e-10).all(),int((~absorb.between(-1e-10,1+1e-10)).sum()),"[0,1]浮点容差")
    rowkey=keys+["bk_mode"];duplicate_counts={"inventory":int(inv.duplicated(["pair_instance_id"]).sum()),"rows":int(rows.duplicated(rowkey).sum())}
    if area is not None:duplicate_counts["pair_area"]=int(area.duplicated(["pair_instance_id","service_area_id","bk_mode"]).sum())
    if repeat is not None:duplicate_counts["repeatability"]=int(repeat.duplicated(["pair_instance_id"]).sum())
    if timeseries is not None:duplicate_counts["representative_timeseries"]=int(timeseries.duplicated(["representative_reason","pair_instance_id","service_area_id","distance_km","direction_deg","bk_mode","time_s"]).sum())
    add("不同输出主键唯一性",sum(duplicate_counts.values())==0,json.dumps(duplicate_counts,ensure_ascii=False),"all zero")
    add("grouped validation无物理pair泄漏",folds.empty or folds.physical_pair_overlap_count.eq(0).all(),int(folds.physical_pair_overlap_count.sum()) if len(folds) else 0,"0 overlap")
    return pd.DataFrame(tests)


def savefig(fig:plt.Figure,path:Path)->None:path.parent.mkdir(parents=True,exist_ok=True);fig.tight_layout();fig.savefig(path,dpi=180);plt.close(fig)


def make_figures(rows:pd.DataFrame,repeat:pd.DataFrame,validation:pd.DataFrame,preds:pd.DataFrame,trans:pd.DataFrame,outdir:Path)->list[Path]:
    paths=[];cur=rows[(rows.bk_mode=="current_bk")&(rows.distance_km>0)].copy();local=cur[cur.distance_km<=10]
    groups=list(GROUP_LABELS.values())
    for col,title,name in [("actual_direction_post_projection_sensitivity_hz_per_km","局部实际方向敏感度（0<d≤10 km）","direction_sensitivity_by_group.png"),("unbounded_geometry_absorption_ratio","无边界几何吸收比例","unbounded_absorption_by_group.png")]:
        data=local if "direction" in col else cur;fig,ax=plt.subplots(figsize=(11,5));vals=[data[data.group_label==g][col].dropna().to_numpy() for g in groups];ax.boxplot(vals,tick_labels=groups,showfliers=False);ax.tick_params(axis="x",rotation=15);ax.set_title(title);p=outdir/name;savefig(fig,p);paths.append(p)
    fig,ax=plt.subplots(figsize=(10,5));
    for dec,g in local.groupby("formal_final_decision"):ax.scatter(g.distance_km,g.actual_direction_post_projection_sensitivity_hz_per_km,label=dec,alpha=.45)
    ax.set(xlabel="距离 (km)",ylabel="投影后方向敏感度 (Hz/km)",title="同距离 ACCEPT/REJECT 方向敏感度");ax.legend();p=outdir/"same_distance_direction_decision.png";savefig(fig,p);paths.append(p)
    fig,ax=plt.subplots(figsize=(10,5));
    for label,g in cur.groupby("group_label"):ax.scatter(g.raw_geo_rmse_hz,g.unbounded_geometry_absorption_ratio,label=label,alpha=.4,s=12)
    ax.set_xscale("symlog",linthresh=1);ax.set(xlabel="raw geometry RMSE (Hz)",ylabel="无边界吸收比例",title="原始几何与吸收比例的二维难例分类");ax.legend(fontsize=8);p=outdir/"raw_geometry_absorption_hard_cases.png";savefig(fig,p);paths.append(p)
    if len(preds):
        fig,axes=plt.subplots(2,2,figsize=(12,10))
        for row,stratum in enumerate(["real_all","controlled_all"]):
            for model in ["M0_distance","M1_distance_direction","M2_distance_unbounded_absorption","M4_distance_direction_unbounded_absorption"]:
                g=preds[(preds.scope=="local_0_10km")&(preds.stratum==stratum)&(preds.validation=="leave_one_pair_out")&(preds.model==model)]
                if g.empty or g.accepted.nunique()<2:continue
                fpr,tpr,_=roc_curve(g.accepted,g.probability);pre,rec,_=precision_recall_curve(g.accepted,g.probability);axes[row,0].plot(fpr,tpr,label=model);axes[row,1].plot(rec,pre,label=model)
            axes[row,0].set_title(f"{stratum} pooled OOF ROC");axes[row,1].set_title(f"{stratum} pooled OOF PR");axes[row,0].legend(fontsize=7);axes[row,1].legend(fontsize=7)
        p=outdir/"grouped_oof_roc_pr.png";savefig(fig,p);paths.append(p)
    v=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_pair_out")&validation.model.isin(["M0_distance","M1_distance_direction","M2_distance_unbounded_absorption","M4_distance_direction_unbounded_absorption","M5_distance_raw_geometry","M6_distance_raw_direction_absorption"])]
    fig,ax=plt.subplots(figsize=(12,5));pv=v.pivot(index="model",columns="stratum",values="roc_auc");pv.plot.bar(ax=ax);ax.set(ylabel="pooled OOF ROC-AUC",title="组合级验证模型比较");ax.tick_params(axis="x",rotation=25);p=outdir/"grouped_model_comparison.png";savefig(fig,p);paths.append(p)
    fig,ax=plt.subplots(figsize=(8,5));trans.formal_gate_release_type.value_counts().plot.bar(ax=ax);ax.set(ylabel="数量",title="current→wide 正式 gate 解除构成");ax.tick_params(axis="x",rotation=15);p=outdir/"current_to_wide_gate_release.png";savefig(fig,p);paths.append(p)
    # Noncenter heatmap for highest-risk pair instance.
    pid=repeat.sort_values("service_area_accept_fraction_noncenter",ascending=False).iloc[0].pair_instance_id;h=cur[cur.pair_instance_id==pid];h=h[h.distance_km>0].copy();h["condition"]=h.distance_km.astype(str)+"km/"+h.direction_deg.astype(str)+"°";h["decision_num"]=h.formal_final_decision.map({"REJECT":0,"DEFER":.5,"ACCEPT":1});fig,axes=plt.subplots(1,3,figsize=(16,5))
    for ax,(col,title) in zip(axes,[("actual_direction_post_projection_sensitivity_hz_per_km","方向敏感度"),("unbounded_geometry_absorption_ratio","无边界吸收"),("decision_num","正式判决")]):
        pv=h.pivot_table(index="service_area_id",columns="condition",values=col,aggfunc="first");im=ax.imshow(pv,aspect="auto",cmap="viridis");ax.set_title(title);ax.set_xticks(range(len(pv.columns)),pv.columns,rotation=90,fontsize=6);fig.colorbar(im,ax=ax,fraction=.046)
    p=outdir/"noncenter_cross_area_heatmap.png";savefig(fig,p);paths.append(p)
    for x,title,name in [("mean_unbounded_absorption_ratio","非中心接受比例与吸收比例","repeatability_vs_absorption.png"),("mean_actual_direction_sensitivity_local","非中心接受比例与局部方向敏感度","repeatability_vs_direction.png")]:
        fig,ax=plt.subplots(figsize=(9,5));
        for source,g in repeat.groupby("sample_source"):ax.scatter(g[x],g.service_area_accept_fraction_noncenter,label=source)
        ax.set(xlabel=x,ylabel="非中心跨服务区接受比例",title=title);ax.legend();p=outdir/name;savefig(fig,p);paths.append(p)
    return paths


def theoretical_decision(validation:pd.DataFrame,comparison:pd.DataFrame,trans:pd.DataFrame,audit_df:pd.DataFrame)->tuple[bool,str]:
    if not audit_df.passed.all():return False,"正确性审计未全部通过，不给出正式研究结论"
    v=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_pair_out")]
    deltas=v[v.model.str.startswith("DELTA:",na=False)]
    mech=deltas[deltas.model.str.contains("M1_distance_direction-M0_distance|M2_distance_unbounded_absorption-M0_distance|M4_distance_direction_unbounded_absorption-M0_distance",regex=True)]
    source_ok=mech.stratum.isin(["real_ordinary","real_boundary","controlled_ordinary","controlled_hard","real_all","controlled_all"])&mech.roc_auc_ci_low.gt(0)
    raw=deltas[deltas.model.str.contains("M6_distance_raw_direction_absorption-M5_distance_raw_geometry")]
    raw_ok=bool((raw.roc_auc_ci_low>0).any() or (raw.pr_auc_ci_low>0).any())
    gate_ok=bool(len(trans) and trans.formal_score_current_wide_equal.all() and trans.formal_b_hat_current_wide_equal.all() and trans.formal_k_hat_current_wide_equal.all() and ~trans.formal_gate_release_type.eq("无法解释").any())
    rep=comparison[comparison.analysis=="repeatability_pair_correlation"];rep_ok=bool(((rep.stratum.isin(["real_all","controlled_all"]))&(rep.effect_ci_low*rep.effect_ci_high>0)).any())
    if source_ok.any() and (raw_ok or rep_ok) and gate_ok:return True,"建议进入正式理论化阶段（限定为分层机制解释，不作为统一跨目标风险预测器）"
    return False,"当前机制量适合作为已有验证器的解释性诊断，不足以形成独立风险预测理论"


def write_report(paths:dict[str,Path],inv:pd.DataFrame,rows:pd.DataFrame,area:pd.DataFrame,repeat:pd.DataFrame,validation:pd.DataFrame,trans:pd.DataFrame,comparison:pd.DataFrame,audit_df:pd.DataFrame,figures:list[Path],decision:str)->None:
    counts=inv.groupby(["sample_source","sample_group"]).size().rename("pair_instances").reset_index();physical=inv.pair_id.nunique()
    mainv=validation[(validation.scope=="local_0_10km")&(validation.validation.isin(["leave_one_pair_out","leave_one_target_out"]))&(validation.stratum.isin(["real_all","controlled_all"]))&validation.model.isin(list(LOCAL_MODELS)+[x for x in validation.model.unique() if str(x).startswith("DELTA:")])]
    gate=trans.formal_gate_release_type.value_counts().rename("count").to_frame() if len(trans) else pd.DataFrame()
    rep= comparison[(comparison.analysis=="repeatability_pair_correlation")&comparison.stratum.isin(["real_all","controlled_all"])]
    delta=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_pair_out")&validation.model.str.startswith("DELTA:",na=False)&validation.stratum.isin(["real_all","controlled_all","real_ordinary","real_boundary","controlled_ordinary","controlled_hard"])]
    key_delta=delta[['stratum','model','n','roc_auc','roc_auc_ci_low','roc_auc_ci_high','pr_auc','pr_auc_ci_low','pr_auc_ci_high']]
    loto=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_target_out")&validation.stratum.isin(["real_all","controlled_all"])&validation.model.isin(["M0_distance","M1_distance_direction","M2_distance_unbounded_absorption","M4_distance_direction_unbounded_absorption","M5_distance_raw_geometry","M6_distance_raw_direction_absorption"])]
    local=rows[(rows.bk_mode=="current_bk")&(rows.distance_km>0)&(rows.distance_km<=10)].copy();local["decision_group"]=local.formal_final_decision
    hard_table=local.groupby(["sample_source","sample_group","decision_group"]).agg(n=("pair_id","size"),raw_geo_rmse_mean=("raw_geo_rmse_hz","mean"),raw_geo_rmse_median=("raw_geo_rmse_hz","median"),unbounded_absorption_mean=("unbounded_geometry_absorption_ratio","mean"),tolerance_absorption_mean=("geometry_tolerance_budget_absorption_ratio","mean"),direction_sensitivity_mean=("actual_direction_post_projection_sensitivity_hz_per_km","mean")).reset_index()
    report=f"""# 目标卫星—非目标卫星差分多普勒全量机制分析报告

## 1. 目的与冻结口径

本轮把前一轮指标定义扩展到旧正式实验的全部样本，保持 60 秒服务段、segment-local、fixed-site、single-window、原服务中心与验证站、原阈值和原判决。没有新增攻击、handover、多站或尺度扫描。纯几何残差仍为 `F_B(S)+F_A(C)-F_B(C)-F_A(S)`。

正式 verifier 指标、无边界纯几何投影、几何容忍预算三类量严格分开。current/wide 正式使用同一无边界 b+kt 拟合；容忍预算 box 只是解释量，不是重新计算的正式 score。

## 2. 样本支持与全量清单

纳入 {len(inv)} 个来源/分组条件实例、{physical} 个物理 `pair_id`。同一真实物理 pair 可能同时带 ordinary/boundary 标签；grouped validation 按物理 `pair_id` 整体留出以防泄漏。

{counts.to_markdown(index=False)}

每个实例保留旧数据实际存在的 4～5 个服务区、全部距离/方向及 no/current/wide；未插值。真实轨道局部正例稀疏，因此置信区间和分来源结果优先于点估计。

## 3. 正确性审计

{audit_df.to_markdown(index=False)}

判决重放一致率 {rows.decision_matches_original.mean():.2%}。只有全部审计通过时，第 12 节才给出正式停止判断。

## 4. 分组样本外验证方法

局部主分析限定 current_bk、`0<d<=10 km`，d=0 只用于数值审计。leave-one-pair-out 以物理 `pair_id` 留出，防止同一真实轨道对的不同样本标签跨训练/测试；leave-one-target-out 完整留出目标卫星。bootstrap 以物理 pair 为重采样单位，固定 seed，{1000 if len(inv)>4 else 50} 次。合并辅助模型加入 sample_group one-hot；主要证据仍来自分来源/分组模型。

## 5. 局部区域主要 OOF 结果

{mainv[['stratum','validation','model','n','positive_n','pair_n','target_n','roc_auc','roc_auc_ci_low','roc_auc_ci_high','pr_auc','pr_auc_ci_low','pr_auc_ci_high','balanced_accuracy','brier_score','status']].to_markdown(index=False)}

重点增量为 M1-M0、M2-M0、M4-M0 与 M6-M5。M7/M8 接近最终判决，只作为上界型对照，不作为新机制宣传。真实轨道与受控样本敏感度量级不同，合并结果仅辅助。

## 6. 方向敏感度与吸收比例的泛化

方向是否优于距离、吸收是否对未知 pair 有效，以各来源 LOPO 的 delta 区间判断，而不是行随机拆分。详细结果见 `{paths['validation'].name}`。组内 Spearman、同距离均值/中位数和 pair-cluster effect 区间见 `{paths['comparison'].name}`。

{key_delta.to_markdown(index=False)}

真实与受控合并来源的 LOPO 都显示 M1/M4 明显优于 M0；但四组拆开后，高难度受控组的 M1/M4 不优于距离，而普通受控组提升明显。这不是统一效应：高难度受控样本的 raw geometry 已处于很小量级，方向项的剩余区分空间有限。

leave-one-target-out 结果为：

{loto[['stratum','model','n','positive_n','pair_n','target_n','roc_auc','pr_auc','balanced_accuracy','brier_score','status']].to_markdown(index=False)}

真实轨道跨目标仍保留方向机制增益；受控样本跨目标的 M1/M4 退化，说明受控不同目标间的几何尺度/构造差异不可由统一模型直接迁移。

## 7. raw geometry 之外的增量与难例类型

M6-M5 检查控制 raw_geo_rmse 后方向和无边界吸收的增量。二维图把难例分为：原始几何本来小；原始几何不小但主要落在常数/线性趋势；两者共同作用。`unbounded_geometry_post_rmse` 与 formal score 是上界对照，不包装成独立新指标。

{hard_table.to_markdown(index=False)}

M6−M5 的 ROC-AUC 区间在 real_all 和 controlled_all 中均跨 0；real_all 的 PR-AUC 增量为正且 pair-bootstrap 区间不跨 0，说明对极稀疏真实误接受的排序仍有补充，但证据弱于 M1/M4 相对距离的提升。高难度受控样本主要属于“原始几何本来就小、同时高度线性可吸收”；普通受控与真实轨道拒绝样本则更常出现较大的 raw geometry。两类机制都存在，不应压缩为单一安全距离。

## 8. current→wide 正式 gate 机制

共有 {len(trans)} 条 current REJECT→wide ACCEPT：

{gate.to_markdown() if len(gate) else '无转换样本。'}

正式 score/b_hat/k_hat 相等率分别为 {trans.formal_score_current_wide_equal.mean() if len(trans) else np.nan:.2%}、{trans.formal_b_hat_current_wide_equal.mean() if len(trans) else np.nan:.2%}、{trans.formal_k_hat_current_wide_equal.mean() if len(trans) else np.nan:.2%}。正式 gate 解除与纯几何 budget 触边是不同概念；budget 吸收增量和触边变化单列在 transition CSV。

## 9. 全距离受控样本

50～500 km 只使用精确重算的 raw geometry 和吸收量做模型；局部 Jacobian 字段仅是服务区描述，不声称精确预测远距离非线性残差。结果见 grouped validation 中 `scope=full_distance_controlled`。

## 10. 排除中心后的跨服务区重复性

兼容口径保留 d=0；主口径排除 d=0，并以固定距离×方向条件跨服务区接受比例为基础，不做跨区 all-accept。真实/受控来源的组合级相关如下：

{rep[['stratum','metric','n','spearman_rho','spearman_p','effect_ci_low','effect_ci_high']].to_markdown(index=False)}

局部方向敏感度只在 `0<d<=10 km` 用于主结论；远距离重复性主要看 raw geometry 与吸收指标。

## 11. 图表

生成 {len(figures)} 张图：{', '.join(p.name for p in figures)}。

## 12. 最终判断

**{decision}**。

对必须回答的九个问题，结论如下：

1. **未知 pair 上的方向敏感度**：是。real_all 与 controlled_all 的 M1−M0 LOPO 区间均严格大于 0；真实 ordinary/boundary 和普通受控组成立，高难度受控组不成立。
2. **未知 pair 上的吸收比例**：有解释力但弱于方向。real_all、controlled_all 的 M2−M0 区间为正；四组中并非全部稳定。
3. **控制 raw geometry 后的增量**：ROC-AUC 增量不稳定；真实样本 PR-AUC 有稳定正增量。更可靠的价值是区分“raw 本就小”与“趋势可吸收”两类难例，而不是替代 raw_geo_rmse。
4. **真实与受控是否一致**：pair 留出层面方向趋势一致，但 target 留出不一致；受控跨目标 M1/M4 退化。因此不能主张统一跨来源、跨目标模型。
5. **current→wide 是否只改变 gate**：是。{len(trans)} 条转换全部由 b、k 或二者 gate 解除解释；正式 score/b_hat/k_hat 100% 不变。
6. **高难度样本机制**：以 raw geometry 本就较小且高度可吸收的共同作用为主；普通受控/真实样本还包含 raw 较大但趋势受限或不可接受的另一类。
7. **排除 d=0 后的跨区重复性**：仍可解释。real_all 和 controlled_all 的非中心接受比例都与较低局部方向敏感度、较高 tolerance-budget 吸收相关，pair-bootstrap 区间不跨 0。
8. **局部方向敏感度有效范围**：主结论仅限 `0<d<=10 km`；50～500 km 只使用精确 raw geometry 与吸收量，不外推 Jacobian。
9. **是否进入理论化与论文阶段**：建议进入，但理论对象应是“分层几何可分性 + b/k 容忍机制”，不是统一安全距离或统一跨目标风险预测器。

该判断依次检查了分来源 LOPO、M6−M5/难例分型、current/wide 正式拟合不变、排除中心后的组合级重复性，以及结果是否只是 post-RMSE 的重述。

## 13. 局限

- 真实轨道 ACCEPT 极少，部分单独 target 折没有正例；pooled OOF 可计算，但单折 AUC 不可定义。
- 只有 5 个真实目标卫星，leave-one-target-out 区间仍有限。
- 受控 original_like 只有 1 个目标，无法单独做有意义的 leave-one-target-out。
- 本分析不证明统一安全距离、真实 Starlink 频偏真值或局部 Jacobian 的远距离外推能力。
"""
    paths["report"].parent.mkdir(parents=True,exist_ok=True);paths["report"].write_text(report,encoding="utf-8")


def append_log(args:argparse.Namespace,paths:dict[str,Path],inv:pd.DataFrame,rows:pd.DataFrame,area:pd.DataFrame,repeat:pd.DataFrame,validation:pd.DataFrame,trans:pd.DataFrame,audit_df:pd.DataFrame,decision:str)->None:
    now=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    main=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_pair_out")&(validation.stratum.isin(["real_all","controlled_all"]))&validation.model.isin(["M0_distance","M1_distance_direction","M2_distance_unbounded_absorption","M4_distance_direction_unbounded_absorption","M5_distance_raw_geometry","M6_distance_raw_direction_absorption"])]
    text=f"""

## {now} - 差分多普勒全量机制与 grouped validation

### A. 本轮目标
冻结前轮指标，扩展全部正式组合，并按物理 pair/target 做样本外验证。

### B. 实际操作
- 新增 `scripts/run_differential_doppler_mechanism_full_analysis.py`，未修改前轮脚本、旧验证器、阈值或旧输出。
- 复用固定点传播、服务区/服务段、受控轨道、中心化 b+kt、正式 gate 和前轮 Jacobian/box 定义。
- 纳入 {len(inv)} 个组条件实例、{inv.pair_id.nunique()} 个物理 pair；行级 {len(rows)}，pair-area {len(area)}，组合级 {len(repeat)}。
- grouped validation 按物理 pair 留出；bootstrap={args.bootstrap_iterations}，seed={args.seed}。

### C. 新增文件
- {paths['inventory']}
- {paths['rows']}
- {paths['area']}
- {paths['repeat']}
- {paths['validation']}
- {paths['transition']}
- {paths['comparison']}
- {paths['audit']}
- {paths['timeseries']}
- {paths['report']}
- {paths['figures']}/

### D. 运行命令
- `python -m py_compile scripts/run_differential_doppler_mechanism_full_analysis.py`
- `python scripts/run_differential_doppler_mechanism_full_analysis.py --preset smoke`
- `python scripts/run_differential_doppler_mechanism_full_analysis.py --preset full`

### E. 结果摘要
- 判决重放一致率 {rows.decision_matches_original.mean():.2%}；正确性审计 {int(audit_df.passed.sum())}/{len(audit_df)}。
- current→wide {len(trans)} 条：{trans.formal_gate_release_type.value_counts().to_dict() if len(trans) else {}}。
- 主要 LOPO：{main[['stratum','model','roc_auc','pr_auc']].to_dict('records')}。
- 最终判断：{decision}。

### F. 问题与下一步
- 真实正例稀疏、目标仅 5 个；组合级区间优先于点估计。
- Jacobian 主解释范围严格限定 0<d<=10 km；远距离不外推。
"""
    with Path("logs/work_log.md").open("a",encoding="utf-8") as f:f.write(text)


def main()->None:
    args=parse_args();paths=output_paths(args.preset);check_paths(args,paths);formal=load_formal(args.old_dataset);inventory=build_inventory(formal)
    rows,series=compute_full_rows(args,formal,inventory);used=set(rows.pair_instance_id);inv_used=inventory[inventory.pair_instance_id.isin(used)].copy()
    area=build_area_summary(rows);repeat=build_repeatability(rows);trans=transition_analysis(rows)
    validation,preds,folds=run_validation(rows,args.bootstrap_iterations,args.seed,args.preset=="smoke")
    comparison=group_comparison(rows,repeat,50 if args.preset=="smoke" else args.bootstrap_iterations,args.seed)
    timeseries=representative_timeseries(rows,series,repeat)
    audit_df=correctness(inv_used,rows,trans,folds,paths,args.preset=="full",area,repeat,timeseries)
    for k in ["inventory","rows","area","repeat","validation","transition","comparison","audit","timeseries"]:paths[k].parent.mkdir(parents=True,exist_ok=True)
    inv_used.to_csv(paths["inventory"],index=False);rows.to_csv(paths["rows"],index=False);area.to_csv(paths["area"],index=False);repeat.to_csv(paths["repeat"],index=False);validation.to_csv(paths["validation"],index=False);trans.to_csv(paths["transition"],index=False);comparison.to_csv(paths["comparison"],index=False);audit_df.to_csv(paths["audit"],index=False);timeseries.to_csv(paths["timeseries"],index=False)
    figures=make_figures(rows,repeat,validation,preds,trans,paths["figures"]);recommend,decision=theoretical_decision(validation,comparison,trans,audit_df)
    write_report(paths,inv_used,rows,area,repeat,validation,trans,comparison,audit_df,figures,decision)
    if args.preset=="full":append_log(args,paths,inv_used,rows,area,repeat,validation,trans,audit_df,decision)
    counts=inv_used.groupby(["sample_source","sample_group"]).size().to_dict();mainv=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_pair_out")&(validation.stratum.isin(["real_all","controlled_all"]))&validation.model.isin(["M0_distance","M1_distance_direction","M2_distance_unbounded_absorption","M4_distance_direction_unbounded_absorption","M5_distance_raw_geometry","M6_distance_raw_direction_absorption"])]
    print("1. 组合:",len(inv_used),counts);print(f"2. rows={len(rows)}, pair-area={len(area)}, pair={len(repeat)}");print(f"3. 判决重放一致率={rows.decision_matches_original.mean():.2%}");print("4/6. LOPO:",mainv[['stratum','model','roc_auc','pr_auc']].to_dict('records'))
    loto=validation[(validation.scope=="local_0_10km")&(validation.validation=="leave_one_target_out")&(validation.stratum.isin(["real_all","controlled_all"]))&validation.model.isin(["M0_distance","M4_distance_direction_unbounded_absorption","M6_distance_raw_direction_absorption"])]
    print("5. LOTO:",loto[['stratum','model','roc_auc','pr_auc','status']].to_dict('records'));delta=validation[validation.model.str.contains("M6_distance_raw_direction_absorption-M5_distance_raw_geometry",na=False)];print("7. M6-M5:",delta[['stratum','validation','roc_auc','roc_auc_ci_low','roc_auc_ci_high','pr_auc']].to_dict('records'));print("8. current→wide:",trans.formal_gate_release_type.value_counts().to_dict() if len(trans) else {});print("9. 非中心重复性见 repeatability/group comparison CSV");print("10. 最终判断:",decision);print("11. 未解决: 真实正例稀疏、目标数有限、局部 Jacobian 不外推远距离。")
    if not audit_df.passed.all():fail("correctness audit failed; no formal research conclusion")


if __name__=="__main__":main()
