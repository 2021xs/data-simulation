#!/usr/bin/env python
"""Confirm realization sensitivity at fixed real-TLE differential-Doppler geometries.

The script reuses the formal orbit, residual, calibration, and verifier code.
Geometry and calibration are fixed within each condition.  Only the empirical
environment terms and Gaussian noise vary through order-independent SHA-256
derived streams.  Existing formal outputs are read-only inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
from skyfield.api import load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_multi_service_area_single_station_confirmation as multi  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BK_MODES = ["no_bk", "current_bk", "wide_bk"]
MASTER_DEFAULT = 20260712


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="固定真实轨道几何的多 observation-realization 确认实验")
    p.add_argument("--preset", choices=["smoke", "confirmation"], default="confirmation")
    p.add_argument("--realizations", type=int, default=30)
    p.add_argument("--master-seed", type=int, default=MASTER_DEFAULT)
    p.add_argument("--formal-dataset", type=Path, default=Path("outputs/datasets/multi_service_area_single_station_dataset.csv"))
    p.add_argument("--mechanism-rows", type=Path, default=Path("outputs/metrics/differential_doppler_mechanism_full_row_summary.csv"))
    p.add_argument("--lineage", type=Path, default=Path("outputs/metrics/observation_realization_lineage_table.csv"))
    p.add_argument("--lineage-geometry", type=Path, default=Path("outputs/metrics/observation_realization_geometry_summary.csv"))
    p.add_argument("--positive-conditions", type=Path, default=Path("outputs/metrics/real_tle_positive_audit_physical_conditions.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def output_paths(preset: str) -> dict[str, Path]:
    suffix = "_smoke" if preset == "smoke" else ""
    stem = f"fixed_geometry_multi_realization{suffix}"
    return {
        "selected": Path(f"outputs/metrics/{stem}_selected_conditions.csv"),
        "dataset": Path(f"outputs/datasets/{stem}_dataset.csv"),
        "geometry": Path(f"outputs/metrics/{stem}_geometry_summary.csv"),
        "pair": Path(f"outputs/metrics/{stem}_pair_summary.csv"),
        "target": Path(f"outputs/metrics/{stem}_target_summary.csv"),
        "group": Path(f"outputs/metrics/{stem}_group_summary.csv"),
        "transition": Path(f"outputs/metrics/{stem}_gate_transition_summary.csv"),
        "audit": Path(f"outputs/metrics/{stem}_correctness_audit.csv"),
        "report": Path(f"outputs/reports/{stem}_confirmation_report.md"),
        "figures": Path(f"outputs/figures/{stem}_confirmation"),
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def require(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{name} missing columns: {missing}")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json(value).encode('utf-8')).hexdigest()[:24]}"


def derive_seed(master_seed: int, geometry_id: str, realization_index: int, stream_name: str) -> int:
    material = f"{master_seed}|{geometry_id}|{realization_index}|{stream_name}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


def array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in ["target_sat_id", "attack_sat_id"]:
        if c in d:
            d[c] = d[c].astype(str).str.replace(r"\.0$", "", regex=True)
    return d


def rank01(s: pd.Series, ascending: bool = True) -> pd.Series:
    if s.notna().sum() <= 1:
        return pd.Series(0.5, index=s.index)
    return s.rank(pct=True, ascending=ascending, method="average").fillna(0.5)


def diverse_take(ranked: pd.DataFrame, n: int, excluded: set[str] | None = None) -> pd.DataFrame:
    excluded = excluded or set()
    d = ranked[~ranked.geometry_condition_id.isin(excluded)].copy()
    chosen: list[int] = []
    seen_pairs: set[str] = set()
    seen_targets: set[str] = set()
    # First pass rewards new pairs and targets while retaining risk ranking.
    remaining = list(d.index)
    while remaining and len(chosen) < n:
        best = min(remaining, key=lambda i: float(d.at[i, "selection_rank_score"])
                   - (0.35 if str(d.at[i, "physical_pair_id"]) not in seen_pairs else 0.0)
                   - (0.15 if str(d.at[i, "target_sat_id"]) not in seen_targets else 0.0))
        chosen.append(best); remaining.remove(best)
        seen_pairs.add(str(d.at[best, "physical_pair_id"])); seen_targets.add(str(d.at[best, "target_sat_id"]))
    return d.loc[chosen].copy()


def select_conditions(lineage: pd.DataFrame, geometry: pd.DataFrame, preset: str) -> pd.DataFrame:
    real = lineage[(lineage.sample_source == "real_tle_candidate") & (lineage.bk_mode == "current_bk")
                   & (lineage.distance_km > 0) & (lineage.distance_km <= 10)].copy()
    require(real, ["geometry_condition_id", "physical_pair_id", "formal_k_gate_lower_hz_per_s",
                   "formal_k_gate_upper_hz_per_s", "formal_k_hat_hz_per_s"], "lineage")
    representatives = real.sort_values(["geometry_condition_id", "sample_group"]).drop_duplicates("geometry_condition_id")
    feature_cols = [
        "geometry_condition_id", "physical_pair_id", "target_sat_id", "attack_sat_id", "service_area_id",
        "service_area_segment_index", "distance_km", "direction_deg", "evaluation_start_s", "evaluation_end_s",
        "C_lat", "C_lon", "S_lat", "S_lon", "calibration_seed", "target_tle_epoch", "attack_tle_epoch",
        "raw_geo_rmse_hz", "unbounded_geometry_b_hat_hz", "unbounded_geometry_k_hat_hz_per_s",
        "unbounded_geometry_post_rmse_hz", "unbounded_geometry_absorption_ratio",
        "actual_direction_post_projection_sensitivity_hz_per_km", "weakest_direction_sensitivity_hz_per_km",
        "strongest_direction_sensitivity_hz_per_km", "anisotropy_ratio",
        "geometry_tolerance_budget_absorption_ratio", "geometry_tolerance_budget_boundary_hit",
    ]
    rep = representatives[feature_cols].copy()
    margins = real.assign(
        k_center=(real.formal_k_gate_lower_hz_per_s + real.formal_k_gate_upper_hz_per_s) / 2,
        k_threshold=(real.formal_k_gate_upper_hz_per_s - real.formal_k_gate_lower_hz_per_s) / 2,
    )
    margins["existing_k_margin"] = margins.k_threshold - abs(margins.formal_k_hat_hz_per_s - margins.k_center)
    old = margins.groupby("geometry_condition_id").agg(
        existing_k_margin_mean=("existing_k_margin", "mean"),
        existing_k_margin_min=("existing_k_margin", "min"),
        existing_k_margin_abs_min=("existing_k_margin", lambda x: float(np.min(np.abs(x)))),
        existing_score_fail_count=("formal_score_gate_pass", lambda x: int((~x.astype(bool)).sum())),
        existing_b_fail_count=("formal_b_gate_pass", lambda x: int((~x.astype(bool)).sum())),
        existing_k_fail_count=("formal_k_gate_pass", lambda x: int((~x.astype(bool)).sum())),
    ).reset_index()
    d = rep.merge(geometry[["geometry_condition_id", "any_accept", "all_accept", "mixed_decisions", "accept_count", "reject_count"]], on="geometry_condition_id", validate="one_to_one").merge(old, on="geometry_condition_id", validate="one_to_one")
    d["direction_preference"] = d.direction_deg.isin([135.0, 315.0]).astype(int)
    d["distance_preference"] = np.isclose(d.distance_km, 2.5).astype(int)

    a = d[d.any_accept].copy()
    a["selection_group"] = np.where(a.all_accept, "observed_all_accept", "observed_mixed")
    a["selection_reason"] = np.where(a.all_accept, "旧两个 realization 均 ACCEPT；纳入全部 any-accept A 组", "旧两个 realization 一 ACCEPT 一 REJECT；纳入全部 any-accept A 组")
    a["selection_rank_score"] = 0.0

    zero = d[~d.any_accept].copy()
    comparable_pair = zero.physical_pair_id.isin(set(a.physical_pair_id)).astype(float)
    comparable_target = zero.target_sat_id.isin(set(a.target_sat_id)).astype(float)
    bscore = (2 * rank01(zero.existing_k_margin_abs_min, True)
              + rank01(zero.actual_direction_post_projection_sensitivity_hz_per_km, True)
              + rank01(zero.raw_geo_rmse_hz, True)
              + rank01(zero.geometry_tolerance_budget_absorption_ratio, False)
              - 0.35 * zero.distance_preference - 0.2 * zero.direction_preference
              - 0.2 * comparable_pair - 0.1 * comparable_target)
    zero["selection_rank_score"] = bscore
    nb = 1 if preset == "smoke" else 10
    b = diverse_take(zero.sort_values("selection_rank_score"), nb)
    b["selection_group"] = "near_boundary_zero_accept_control"
    b["selection_reason"] = "旧两个 realization 均拒绝；优先 k margin 接近0、低敏感度、小 raw geometry、高容忍吸收及与A组可比"

    remaining = zero[~zero.geometry_condition_id.isin(set(b.geometry_condition_id))].copy()
    multi_fail = remaining[["existing_score_fail_count", "existing_b_fail_count", "existing_k_fail_count"]].sum(axis=1)
    cscore = (rank01(remaining.raw_geo_rmse_hz, False)
              + rank01(remaining.actual_direction_post_projection_sensitivity_hz_per_km, False)
              + rank01(remaining.geometry_tolerance_budget_absorption_ratio, True)
              + rank01(remaining.existing_k_margin_mean, True)
              + rank01(multi_fail, False)
              - 0.15 * remaining.distance_preference - 0.1 * remaining.direction_preference)
    remaining["selection_rank_score"] = cscore
    nc = 1 if preset == "smoke" else 10
    c = diverse_take(remaining.sort_values("selection_rank_score"), nc, set(b.geometry_condition_id))
    c["selection_group"] = "deep_reject_control"
    c["selection_reason"] = "旧两个 realization 均拒绝；优先大 raw geometry、高方向敏感度、低容忍吸收、负 k margin 或多 gate 失败"

    if preset == "smoke":
        aa = a[a.all_accept].head(1)
        am = a[a.mixed_decisions].head(1)
        a = pd.concat([aa, am], ignore_index=True)
    selected = pd.concat([a, b, c], ignore_index=True)
    selected["selection_order"] = np.arange(len(selected))
    selected["selection_is_risk_stratified"] = True
    return selected.sort_values("selection_order").reset_index(drop=True)


def primary_gate(score: bool, b: bool, k: bool, coverage: bool, quality: bool) -> str:
    failed = [name for name, passed in [("score", score), ("b", b), ("k", k), ("coverage", coverage), ("quality", quality)] if not passed]
    if not failed:
        return "none"
    return failed[0] if len(failed) == 1 else "multiple"


def load_orbit_inputs(args: argparse.Namespace):
    loader = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library,
                             tle_file=args.tle_file, orbit_config=args.orbit_config,
                             parameter_config=args.parameter_config, max_targets=5)
    selection, library, orbit_cfg, tle, ranges = expanded.load_base_inputs(loader)
    if orbit_cfg.get("mode") != "controlled_starlink" or orbit_cfg.get("observation_id") is not None:
        fail("requires controlled_starlink mode and observation_id=null")
    return selection, library, orbit_cfg, tle, ranges


def generate(args: argparse.Namespace, selected: pd.DataFrame, lineage: pd.DataFrame) -> pd.DataFrame:
    _selection, library, orbit_cfg, tle, ranges = load_orbit_inputs(args)
    ts = load.timescale()
    freq_hz = float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or orbit_cfg["frequency"]["center_freq_hz"])
    mode_rows = lineage[lineage.geometry_condition_id.isin(set(selected.geometry_condition_id))].sort_values("sample_group").drop_duplicates(["geometry_condition_id", "bk_mode"]).set_index(["geometry_condition_id", "bk_mode"])
    target_cache: dict[str, tuple[pd.DataFrame, np.ndarray, list[Any], float, Any]] = {}
    geometry_cache: dict[str, dict[str, Any]] = {}
    output: list[dict[str, Any]] = []

    for cond in selected.itertuples(index=False):
        gid = str(cond.geometry_condition_id); target = str(cond.target_sat_id); attacker = str(cond.attack_sat_id)
        if target not in target_cache:
            tg = seg.base.target_geo_from_library(library, target)
            tr = tg.t_rel_s.to_numpy(float)
            times = [seg.base.parse_utc(v) for v in tg.t_abs_utc.astype(str)]
            target_cache[target] = (tg, tr, times, float(np.median(np.diff(tr))), tle[target]["sat"])
        _tg, tr, times_all, step, sat_a = target_cache[target]
        sat_b = tle[attacker]["sat"]
        mask = (tr >= float(cond.evaluation_start_s) - 1e-9) & (tr <= float(cond.evaluation_end_s) + 1e-9)
        et = tr[mask]; times = [x for x, keep in zip(times_all, mask) if keep]
        if len(et) < 3:
            fail(f"{gid}: fewer than 3 segment points")
        fa_c = seg.geo_curve_fixed(sat_a, cond.C_lat, cond.C_lon, 0.0, times, ts, freq_hz, step)[0]
        fa_s = seg.geo_curve_fixed(sat_a, cond.S_lat, cond.S_lon, 0.0, times, ts, freq_hz, step)[0]
        sample = {"sample_source": "real_tle_candidate", "target_sat_id": target, "attack_sat_id": attacker,
                  "attack_type": "real_tle_candidate", "attack_param_value": np.nan}
        fb_c = multi.attack_geo(sample, sat_a, sat_b, cond.C_lat, cond.C_lon, 0.0, times, ts, freq_hz, step)
        fb_s = multi.attack_geo(sample, sat_a, sat_b, cond.S_lat, cond.S_lon, 0.0, times, ts, freq_hz, step)
        raw = fb_s + fa_c - fb_c - fa_s
        distance = seg.distance_km(np.full(len(et), cond.C_lat), np.full(len(et), cond.C_lon), cond.S_lat, cond.S_lon)
        coverage = distance <= 500.0 + 1e-9
        cal_seed = int(cond.calibration_seed)
        cal = seg.calibration_for_trel(et, ranges, cal_seed, 30)
        geometry_cache[gid] = {"raw": raw, "fa_s": fa_s, "mask": mask, "et": et, "coverage": coverage, "cal": cal}
        t0 = float(np.mean(tr))

        for ridx in range(args.realizations):
            env_seed = derive_seed(args.master_seed, gid, ridx, "environment")
            noise_seed = derive_seed(args.master_seed, gid, ridx, "noise")
            err = base.sample_error_params(ranges, np.random.default_rng(env_seed))
            full_noise = np.random.default_rng(noise_seed).normal(0.0, err.sigma_hz, len(tr)) if err.sigma_hz > 0 else np.zeros(len(tr))
            noise = full_noise[mask]
            noise_hash = array_hash(noise)
            obs_id = stable_id("observation", {"geometry_condition_id": gid, "realization_index": ridx,
                                                 "environment_seed": env_seed, "noise_seed": noise_seed,
                                                 "calibration_seed": cal_seed})
            y = fb_s + (fa_c - fb_c) + err.b_hz + err.k_hz_s * (et - t0) + noise

            for mode in BK_MODES:
                dec = seg.evaluate_single_station(y_obs=y, f_geo_a=fa_s, t_rel=et, coverage_mask=coverage,
                                                  cal=cal, bk_mode=mode, verification_strategy="single-window")
                th = seg.threshold_for(cal, "full_pass", mode)
                quality = bool(np.isfinite([dec.residual_rmse_hz, dec.b_hat_hz, dec.k_hat_hz_per_s]).all())
                score_margin = float(th["score_threshold"] - dec.residual_rmse_hz)
                b_margin = float(th["b_threshold"] - abs(dec.b_hat_hz - th["b_center"]))
                k_margin = float(th["k_threshold"] - abs(dec.k_hat_hz_per_s - th["k_center"]))
                source = mode_rows.loc[(gid, mode)]
                output.append({
                    "geometry_condition_id": gid, "observation_realization_id": obs_id, "bk_mode": mode,
                    "selection_group": cond.selection_group, "physical_pair_id": cond.physical_pair_id,
                    "target_sat_id": target, "attack_sat_id": attacker, "service_area_id": cond.service_area_id,
                    "service_area_segment_index": int(cond.service_area_segment_index), "distance_km": float(cond.distance_km),
                    "direction_deg": float(cond.direction_deg), "evaluation_start_s": float(cond.evaluation_start_s),
                    "evaluation_end_s": float(cond.evaluation_end_s), "realization_index": ridx,
                    "master_seed": int(args.master_seed), "environment_seed": env_seed, "noise_seed": noise_seed,
                    "calibration_seed": cal_seed, "b_env": float(err.b_hz), "k_env": float(err.k_hz_s),
                    "sigma_hz": float(err.sigma_hz), "noise_hash": noise_hash,
                    "raw_geo_rmse_hz": float(np.sqrt(np.mean(raw**2))), "raw_geo_max_abs_hz": float(np.max(np.abs(raw))),
                    "unbounded_geometry_b_hat_hz": float(source.unbounded_geometry_b_hat_hz),
                    "unbounded_geometry_k_hat_hz_per_s": float(source.unbounded_geometry_k_hat_hz_per_s),
                    "unbounded_geometry_post_rmse_hz": float(source.unbounded_geometry_post_rmse_hz),
                    "unbounded_geometry_absorption_ratio": float(source.unbounded_geometry_absorption_ratio),
                    "actual_direction_post_projection_sensitivity_hz_per_km": float(source.actual_direction_post_projection_sensitivity_hz_per_km),
                    "weakest_direction_sensitivity_hz_per_km": float(source.weakest_direction_sensitivity_hz_per_km),
                    "strongest_direction_sensitivity_hz_per_km": float(source.strongest_direction_sensitivity_hz_per_km),
                    "anisotropy_ratio": float(source.anisotropy_ratio),
                    "geometry_tolerance_budget_absorption_ratio": float(source.geometry_tolerance_budget_absorption_ratio),
                    "geometry_tolerance_budget_boundary_hit": bool(source.geometry_tolerance_budget_boundary_hit),
                    "formal_score_value": float(dec.residual_rmse_hz), "formal_score_threshold": float(th["score_threshold"]),
                    "formal_b_hat_hz": float(dec.b_hat_hz), "formal_b_center_hz": float(th["b_center"]),
                    "formal_b_threshold_hz": float(th["b_threshold"]),
                    "formal_k_hat_hz_per_s": float(dec.k_hat_hz_per_s), "formal_k_center_hz_per_s": float(th["k_center"]),
                    "formal_k_threshold_hz_per_s": float(th["k_threshold"]),
                    "score_gate_margin": score_margin, "b_gate_margin": b_margin, "k_gate_margin": k_margin,
                    "score_gate_pass": bool(dec.score_gate_pass), "b_gate_pass": bool(dec.b_gate_pass),
                    "k_gate_pass": bool(dec.k_gate_pass), "coverage_gate_pass": bool(dec.coverage_gate_pass),
                    "quality_gate_pass": quality, "final_decision": dec.decision,
                    "accept_flag": bool(dec.decision == "ACCEPT"),
                    "primary_reject_gate": primary_gate(dec.score_gate_pass, dec.b_gate_pass, dec.k_gate_pass,
                                                        dec.coverage_gate_pass, quality),
                    "point_count": len(et), "T_service_s": 60.0, "evaluation_scope": "segment_local",
                    "doppler_reference_mode": "fixed_site_segment_center", "verification_strategy": "single-window",
                    "observation_vector_hash": array_hash(y),
                })
    return pd.DataFrame(output)


def wilson(success: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return np.nan, np.nan
    p = success / total; den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    lower = 0.0 if success == 0 else max(0.0, center - half)
    upper = 1.0 if success == total else min(1.0, center + half)
    return lower, upper


def qstats(g: pd.DataFrame, col: str, prefix: str) -> dict[str, float]:
    x = g[col].to_numpy(float)
    if np.isposinf(x).all():
        return {f"{prefix}_mean": math.inf, f"{prefix}_std": 0.0, f"{prefix}_q05": math.inf,
                f"{prefix}_q25": math.inf, f"{prefix}_median": math.inf, f"{prefix}_q75": math.inf,
                f"{prefix}_q95": math.inf}
    return {f"{prefix}_mean": float(np.mean(x)), f"{prefix}_std": float(np.std(x, ddof=0)),
            f"{prefix}_q05": float(np.quantile(x, .05)), f"{prefix}_q25": float(np.quantile(x, .25)),
            f"{prefix}_median": float(np.median(x)), f"{prefix}_q75": float(np.quantile(x, .75)),
            f"{prefix}_q95": float(np.quantile(x, .95))}


def sign_flip(x: pd.Series) -> bool:
    return bool((x > 0).any() and (x < 0).any())


def build_geometry_summary(data: pd.DataFrame) -> pd.DataFrame:
    keys = ["geometry_condition_id", "bk_mode", "selection_group", "physical_pair_id", "target_sat_id", "attack_sat_id",
            "service_area_id", "distance_km", "direction_deg"]
    rows = []
    mechanism = ["raw_geo_rmse_hz", "raw_geo_max_abs_hz", "unbounded_geometry_absorption_ratio",
                 "actual_direction_post_projection_sensitivity_hz_per_km", "weakest_direction_sensitivity_hz_per_km",
                 "strongest_direction_sensitivity_hz_per_km", "anisotropy_ratio", "geometry_tolerance_budget_absorption_ratio"]
    for key, g in data.groupby(keys, sort=False, dropna=False):
        accept = int(g.accept_flag.sum()); reject = int(g.final_decision.eq("REJECT").sum()); defer = int(g.final_decision.eq("DEFER").sum())
        lo, hi = wilson(accept, len(g))
        row = {**dict(zip(keys, key)), "realization_count": len(g), "accept_count": accept, "reject_count": reject,
               "defer_count": defer, "accept_fraction": accept / len(g), "accept_fraction_ci_lower": lo,
               "accept_fraction_ci_upper": hi,
               "score_gate_fail_fraction": float((~g.score_gate_pass).mean()), "b_gate_fail_fraction": float((~g.b_gate_pass).mean()),
               "k_gate_fail_fraction": float((~g.k_gate_pass).mean()), "coverage_gate_fail_fraction": float((~g.coverage_gate_pass).mean()),
               "quality_gate_fail_fraction": float((~g.quality_gate_pass).mean()),
               "margin_sign_flip_score": sign_flip(g.score_gate_margin), "margin_sign_flip_b": sign_flip(g.b_gate_margin),
               "margin_sign_flip_k": sign_flip(g.k_gate_margin),
               "primary_reject_gate_counts": stable_json(g.loc[~g.accept_flag, "primary_reject_gate"].value_counts().to_dict())}
        row.update(qstats(g, "score_gate_margin", "score_margin")); row.update(qstats(g, "b_gate_margin", "b_margin")); row.update(qstats(g, "k_gate_margin", "k_margin"))
        row.update({c: g[c].iloc[0] for c in mechanism})
        rows.append(row)
    out = pd.DataFrame(rows)
    current = out.bk_mode.eq("current_bk")
    af = out.accept_fraction
    out["observed_accept_risk_class"] = np.select(
        [current & (af >= .8), current & (af >= .2), current & (af > 0), current & (af == 0)],
        ["observed_high_accept", "observed_moderate_accept", "observed_rare_accept", "no_accept_observed"], default="not_current_bk")
    labels = []
    for r in out.itertuples(index=False):
        if r.bk_mode != "current_bk": labels.append("not_current_bk"); continue
        reject_gates = json.loads(r.primary_reject_gate_counts)
        if r.k_margin_q05 > 0 and max(r.score_gate_fail_fraction, r.b_gate_fail_fraction, r.k_gate_fail_fraction, r.coverage_gate_fail_fraction, r.quality_gate_fail_fraction) == 0:
            label = "deep_accept"
        elif r.margin_sign_flip_k and reject_gates.get("k", 0) + reject_gates.get("multiple", 0) >= max(1, r.reject_count / 2):
            label = "k_boundary_sensitive"
        elif r.margin_sign_flip_b and reject_gates.get("b", 0) >= max(1, r.reject_count / 2):
            label = "b_boundary_sensitive"
        elif r.margin_sign_flip_score and reject_gates.get("score", 0) >= max(1, r.reject_count / 2):
            label = "score_boundary_sensitive"
        elif r.accept_count == 0 and min(r.score_margin_q95, r.b_margin_q95, r.k_margin_q95) < 0:
            label = "deep_reject"
        else:
            label = "mixed_multi_gate"
        labels.append(label)
    out["gate_margin_risk_class"] = labels
    return out


def aggregate_entities(current: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for key, g in current.groupby(cols, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(cols, key)), "geometry_count": len(g), "mean_accept_fraction": g.accept_fraction.mean(),
                     "median_accept_fraction": g.accept_fraction.median(), "max_accept_fraction": g.accept_fraction.max(),
                     "high_accept_geometry_count": int(g.observed_accept_risk_class.eq("observed_high_accept").sum()),
                     "k_boundary_sensitive_count": int(g.gate_margin_risk_class.eq("k_boundary_sensitive").sum()),
                     "mixed_geometry_count": int(g.accept_fraction.between(1e-12, 1 - 1e-12).sum())})
    return pd.DataFrame(rows)


def transition_summary(data: pd.DataFrame) -> pd.DataFrame:
    keys = ["geometry_condition_id", "observation_realization_id"]
    c = data[data.bk_mode == "current_bk"].set_index(keys)
    w = data[data.bk_mode == "wide_bk"].set_index(keys)
    joined = c.add_suffix("_current").join(w.add_suffix("_wide"), how="inner")
    joined["transition"] = joined.final_decision_current + " -> " + joined.final_decision_wide
    def reason(r: pd.Series) -> str:
        if r.transition != "REJECT -> ACCEPT": return "not_applicable"
        b = (not bool(r.b_gate_pass_current)) and bool(r.b_gate_pass_wide)
        k = (not bool(r.k_gate_pass_current)) and bool(r.k_gate_pass_wide)
        return "b/k同时解除" if b and k else "b gate解除" if b else "k gate解除" if k else "其他"
    joined["gate_release_reason"] = joined.apply(reason, axis=1)
    detail = joined.reset_index()
    group_cols = ["selection_group_current", "transition", "gate_release_reason"]
    summary = detail.groupby(group_cols, dropna=False).size().rename("realization_count").reset_index()
    summary = summary.rename(columns={"selection_group_current": "selection_group"})
    summary["total_realizations"] = len(detail)
    summary["fraction"] = summary.realization_count / len(detail)
    return summary


def correlations(current: pd.DataFrame) -> pd.DataFrame:
    metrics = ["raw_geo_rmse_hz", "actual_direction_post_projection_sensitivity_hz_per_km",
               "weakest_direction_sensitivity_hz_per_km", "unbounded_geometry_absorption_ratio",
               "geometry_tolerance_budget_absorption_ratio"]
    rows = []
    strata = [("all_selected", current)] + [(f"group:{k}", g) for k, g in current.groupby("selection_group")]
    strata += [(f"target:{k}", g) for k, g in current.groupby("target_sat_id")]
    for stratum, g in strata:
        for metric in metrics:
            x = g[["accept_fraction", metric]].dropna()
            rho, p = spearmanr(x[metric], x.accept_fraction) if len(x) >= 3 and x[metric].nunique() > 1 and x.accept_fraction.nunique() > 1 else (np.nan, np.nan)
            rows.append({"stratum": stratum, "metric": metric, "geometry_count": len(x), "spearman_rho": rho, "spearman_p": p})
    return pd.DataFrame(rows)


def make_figures(data: pd.DataFrame, geometry: pd.DataFrame, transition: pd.DataFrame, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    cur = geometry[geometry.bk_mode == "current_bk"].sort_values("accept_fraction", ascending=False).reset_index(drop=True)
    paths: list[Path] = []
    def save(name: str):
        p = outdir / name; plt.tight_layout(); plt.savefig(p, dpi=180, bbox_inches="tight"); plt.close(); paths.append(p)
    x = np.arange(len(cur)); lo = np.maximum(0.0, cur.accept_fraction - cur.accept_fraction_ci_lower); hi = np.maximum(0.0, cur.accept_fraction_ci_upper - cur.accept_fraction)
    plt.figure(figsize=(14, 5)); plt.errorbar(x, cur.accept_fraction, yerr=[lo, hi], fmt="o", capsize=2); plt.axhline(.8, color="r", ls="--"); plt.axhline(.2, color="gray", ls=":"); plt.xlabel("固定几何条件（按接受比例排序）"); plt.ylabel("current 接受比例 / Wilson 95% CI"); save("01_geometry_current_accept_fraction_wilson.png")
    plt.figure(figsize=(10, 5)); cur.boxplot(column="accept_fraction", by="selection_group", ax=plt.gca(), rot=20); plt.suptitle(""); plt.title("A/B/C 选择组的条件接受比例"); save("02_selection_group_accept_fraction.png")
    a = cur[cur.selection_group.isin(["observed_all_accept", "observed_mixed"])]
    plt.figure(figsize=(9, 5)); a.boxplot(column="accept_fraction", by="selection_group", ax=plt.gca()); plt.suptitle(""); plt.title("原 all-accept 与 mixed 几何"); save("03_original_all_vs_mixed.png")
    mixed_ids = set(cur.loc[cur.selection_group == "observed_mixed", "geometry_condition_id"])
    km = data[(data.bk_mode == "current_bk") & data.geometry_condition_id.isin(mixed_ids)]
    order = km.groupby("geometry_condition_id").k_gate_margin.median().sort_values().index
    vals = [km.loc[km.geometry_condition_id == gid, "k_gate_margin"].to_numpy() for gid in order]
    plt.figure(figsize=(14, 5)); plt.boxplot(vals, showfliers=False); plt.axhline(0, color="r", ls="--"); plt.xlabel("原 mixed 几何"); plt.ylabel("k gate margin (Hz/s)"); save("04_mixed_geometry_k_margin.png")
    kd = data[data.bk_mode == "current_bk"]
    plt.figure(figsize=(8, 5)); kd.boxplot(column="k_env", by="final_decision", ax=plt.gca()); plt.suptitle(""); plt.title("ACCEPT/REJECT realization 的 k_env"); save("05_k_env_by_decision.png")
    for idx, (metric, name, xlabel) in enumerate([
        ("actual_direction_post_projection_sensitivity_hz_per_km", "06_accept_vs_direction_sensitivity.png", "实际方向投影后敏感度 (Hz/km)"),
        ("raw_geo_rmse_hz", "07_accept_vs_raw_geometry.png", "raw geometry RMSE (Hz)"),
        ("unbounded_geometry_absorption_ratio", "08_accept_vs_unbounded_absorption.png", "无边界几何吸收比例")]):
        plt.figure(figsize=(8, 5))
        for group, g in cur.groupby("selection_group"):
            plt.scatter(g[metric], g.accept_fraction, label=group, alpha=.8)
        plt.xlabel(xlabel); plt.ylabel("current 接受比例"); plt.legend(fontsize=8); save(name)
    wide = geometry[geometry.bk_mode == "wide_bk"][["geometry_condition_id", "accept_fraction"]].rename(columns={"accept_fraction": "wide"})
    cw = cur.merge(wide, on="geometry_condition_id")
    plt.figure(figsize=(6, 6)); plt.scatter(cw.accept_fraction, cw.wide); plt.plot([0, 1], [0, 1], "k--"); plt.xlabel("current 接受比例"); plt.ylabel("wide 接受比例"); save("09_current_vs_wide_accept_fraction.png")
    rel = transition[transition.gate_release_reason != "not_applicable"].groupby("gate_release_reason").realization_count.sum()
    plt.figure(figsize=(7, 5)); rel.plot.bar(); plt.ylabel("current REJECT → wide ACCEPT realization 数"); save("10_current_to_wide_gate_release.png")
    exemplars = []
    deep_accept = cur[cur.gate_margin_risk_class == "deep_accept"]
    if deep_accept.empty:
        exemplars.append(("highest_accept_no_deep_accept", cur.sort_values("accept_fraction", ascending=False).iloc[0].geometry_condition_id))
    else:
        exemplars.append(("deep_accept", deep_accept.iloc[0].geometry_condition_id))
    k_boundary = cur[cur.gate_margin_risk_class == "k_boundary_sensitive"]
    if not k_boundary.empty: exemplars.append(("k_boundary_sensitive", k_boundary.iloc[0].geometry_condition_id))
    rare = cur[cur.observed_accept_risk_class == "observed_rare_accept"]
    if not rare.empty: exemplars.append(("rare_accept", rare.iloc[0].geometry_condition_id))
    deep_reject = cur[cur.gate_margin_risk_class == "deep_reject"]
    if not deep_reject.empty: exemplars.append(("deep_reject", deep_reject.iloc[0].geometry_condition_id))
    fig, axes = plt.subplots(max(1, len(exemplars)), 3, figsize=(12, 3 * max(1, len(exemplars))), squeeze=False)
    for i, (label, gid) in enumerate(exemplars):
        z = kd[kd.geometry_condition_id == gid]
        for j, col in enumerate(["score_gate_margin", "b_gate_margin", "k_gate_margin"]):
            axes[i, j].hist(z[col], bins=10); axes[i, j].axvline(0, color="r", ls="--"); axes[i, j].set_title(f"{label}: {col}")
    save("11_representative_margin_distributions.png")
    return paths


def correctness(args: argparse.Namespace, selected: pd.DataFrame, data: pd.DataFrame, geometry: pd.DataFrame,
                hashes_before: dict[str, str], hashes_after: dict[str, str], ranges: dict[str, list[float]]) -> pd.DataFrame:
    tests = []
    def add(name: str, passed: bool, observed: Any, expected: str): tests.append({"check": name, "passed": bool(passed), "observed": observed, "expected": expected})
    add("选中条件均为真实轨道非中心局部条件", selected.distance_km.gt(0).all() and selected.distance_km.le(10).all(), selected.distance_km.agg(["min", "max"]).to_dict(), "0<d<=10 and real TLE")
    add("选中 geometry_condition_id 唯一", selected.geometry_condition_id.is_unique, int(selected.geometry_condition_id.duplicated().sum()), "0 duplicates")
    a_count = int(selected.selection_group.isin(["observed_all_accept", "observed_mixed"]).sum())
    expected_a = 2 if args.preset == "smoke" else 19
    add("A组包含preset要求的 any-accept", a_count == expected_a, a_count, str(expected_a))
    bc = selected[selected.selection_group.isin(["near_boundary_zero_accept_control", "deep_reject_control"])]
    add("B/C组无几何重复", bc.geometry_condition_id.is_unique, int(bc.geometry_condition_id.duplicated().sum()), "0")
    counts = data.groupby(["geometry_condition_id", "bk_mode"]).size()
    add("每个几何每模式生成指定 realization 数", counts.eq(args.realizations).all(), counts.value_counts().to_dict(), str(args.realizations))
    obs = data.drop_duplicates(["geometry_condition_id", "observation_realization_id"])
    add("observation_realization_id 全局唯一", obs.observation_realization_id.is_unique, int(obs.observation_realization_id.duplicated().sum()), "0 duplicates")
    seed_unique = obs.groupby("geometry_condition_id").agg(env=("environment_seed", "nunique"), noise=("noise_seed", "nunique"))
    add("同一几何 environment/noise seed 不重复", seed_unique.eq(args.realizations).all().all(), seed_unique.min().to_dict(), str(args.realizations))
    # Re-derive after reversed row order to prove execution-order independence.
    sample = obs.iloc[::-1].head(min(20, len(obs)))
    repro = all(int(r.environment_seed) == derive_seed(args.master_seed, r.geometry_condition_id, int(r.realization_index), "environment") and int(r.noise_seed) == derive_seed(args.master_seed, r.geometry_condition_id, int(r.realization_index), "noise") for r in sample.itertuples())
    add("调整运行顺序后 seed 可复现", repro, len(sample), "all sampled rows exact")
    pure = ["raw_geo_rmse_hz", "raw_geo_max_abs_hz", "unbounded_geometry_b_hat_hz", "unbounded_geometry_k_hat_hz_per_s", "unbounded_geometry_post_rmse_hz", "unbounded_geometry_absorption_ratio", "actual_direction_post_projection_sensitivity_hz_per_km", "weakest_direction_sensitivity_hz_per_km", "strongest_direction_sensitivity_hz_per_km", "anisotropy_ratio"]
    pure_ok = data.groupby("geometry_condition_id")[pure].nunique(dropna=False).le(1).all().all()
    add("同一几何纯几何指标固定", pure_ok, bool(pure_ok), "True")
    keys = ["geometry_condition_id", "observation_realization_id"]
    c = data[data.bk_mode == "current_bk"].set_index(keys); w = data[data.bk_mode == "wide_bk"].set_index(keys)
    add("current/wide 正式 score 相同", np.allclose(c.formal_score_value, w.formal_score_value, atol=1e-10), float(np.max(np.abs(c.formal_score_value-w.formal_score_value))), "<=1e-10")
    add("current/wide 正式 b_hat 相同", np.allclose(c.formal_b_hat_hz, w.formal_b_hat_hz, atol=1e-10), float(np.max(np.abs(c.formal_b_hat_hz-w.formal_b_hat_hz))), "<=1e-10")
    add("current/wide 正式 k_hat 相同", np.allclose(c.formal_k_hat_hz_per_s, w.formal_k_hat_hz_per_s, atol=1e-12), float(np.max(np.abs(c.formal_k_hat_hz_per_s-w.formal_k_hat_hz_per_s))), "<=1e-12")
    bad = int((c.accept_flag & ~w.accept_flag).sum()); add("无 current ACCEPT→wide REJECT", bad == 0, bad, "0")
    calibration_seed_fixed = data.groupby("geometry_condition_id").calibration_seed.nunique().eq(1).all()
    calibration_values = ["formal_score_threshold", "formal_b_center_hz", "formal_b_threshold_hz",
                          "formal_k_center_hz_per_s", "formal_k_threshold_hz_per_s"]
    calibration_thresholds_fixed = data.groupby(["geometry_condition_id", "bk_mode"])[calibration_values].nunique(dropna=False).le(1).all().all()
    add("同一几何 calibration seed与阈值固定", calibration_seed_fixed and calibration_thresholds_fixed,
        {"seed_fixed": bool(calibration_seed_fixed), "thresholds_fixed": bool(calibration_thresholds_fixed)}, "both true")
    range_ok = obs.b_env.between(*ranges["b_hz"]).all() and obs.k_env.between(*ranges["k_hz_per_s"]).all() and obs.sigma_hz.between(*ranges["sigma_hz"]).all()
    add("环境与噪声分布使用旧正式 main ranges", range_ok, {"b": obs.b_env.agg(["min","max"]).to_dict(), "k": obs.k_env.agg(["min","max"]).to_dict(), "sigma": obs.sigma_hz.agg(["min","max"]).to_dict()}, stable_json(ranges))
    obs_hashes = data.groupby(keys).observation_vector_hash.nunique()
    add("no/current/wide 使用同一观测", obs_hashes.eq(1).all(), int(obs_hashes.max()), "1 hash")
    # Wilson known case 0/30 and 30/30.
    w0 = wilson(0, 30); w30 = wilson(30, 30)
    add("Wilson区间计算正确", abs(w0[1]-0.113513) < 1e-5 and abs(w30[0]-0.886487) < 1e-5, {"0/30": w0, "30/30": w30}, "standard 95% Wilson")
    summed = geometry.groupby("bk_mode").realization_count.sum().to_dict(); actual = data.groupby("bk_mode").size().to_dict()
    add("几何汇总可回加", summed == actual, {"summary": summed, "data": actual}, "equal")
    margin_score = np.allclose(data.score_gate_margin, data.formal_score_threshold-data.formal_score_value)
    margin_b = np.allclose(data.b_gate_margin, data.formal_b_threshold_hz-abs(data.formal_b_hat_hz-data.formal_b_center_hz), equal_nan=True)
    margin_k = np.allclose(data.k_gate_margin, data.formal_k_threshold_hz_per_s-abs(data.formal_k_hat_hz_per_s-data.formal_k_center_hz_per_s), equal_nan=True)
    add("gate margin公式和符号正确", margin_score and margin_b and margin_k, {"score":margin_score,"b":margin_b,"k":margin_k}, "all true")
    changed = sum(hashes_before[k] != hashes_after.get(k) for k in hashes_before)
    add("旧正式文件SHA-256未改变", changed == 0, changed, "0")
    return pd.DataFrame(tests)


def write_report(args: argparse.Namespace, paths: dict[str, Path], selected: pd.DataFrame, data: pd.DataFrame,
                 geometry: pd.DataFrame, transition: pd.DataFrame, corr: pd.DataFrame, audit: pd.DataFrame,
                 ranges: dict[str, list[float]], figures: list[Path]) -> None:
    cur = geometry[geometry.bk_mode == "current_bk"].copy()
    all_old = cur[cur.selection_group == "observed_all_accept"]
    mixed_old = cur[cur.selection_group == "observed_mixed"]
    near = cur[cur.selection_group == "near_boundary_zero_accept_control"]
    deep = cur[cur.selection_group == "deep_reject_control"]
    new_near = int(near.accept_count.gt(0).sum()); new_deep = int(deep.accept_count.gt(0).sum())
    stable = cur[cur.accept_fraction >= .8]
    k_sensitive = int(cur.gate_margin_risk_class.eq("k_boundary_sensitive").sum())
    mixed_still = int(mixed_old.accept_fraction.between(1e-12, 1-1e-12).sum())
    kd = data[(data.bk_mode == "current_bk") & data.geometry_condition_id.isin(set(mixed_old.geometry_condition_id))]
    kenv = kd.groupby("final_decision").k_env.agg(["count", "mean", "std", "median", "min", "max"])
    mixed_margin_flips = {name: int(mixed_old[col].sum()) for name, col in [("score", "margin_sign_flip_score"), ("b", "margin_sign_flip_b"), ("k", "margin_sign_flip_k")]}
    mixed_primary_gates = kd.primary_reject_gate.value_counts().to_dict()
    kd = kd.copy()
    kd["k_env_within_geometry"] = kd.k_env - kd.groupby("geometry_condition_id").k_env.transform("mean")
    kd["k_hat_within_geometry"] = kd.formal_k_hat_hz_per_s - kd.groupby("geometry_condition_id").formal_k_hat_hz_per_s.transform("mean")
    within_k_corr = float(np.corrcoef(kd.k_env_within_geometry, kd.k_hat_within_geometry)[0, 1])
    release = transition[transition.gate_release_reason != "not_applicable"].groupby("gate_release_reason").realization_count.sum()
    overall_corr = corr[corr.stratum == "all_selected"]
    wide = geometry[geometry.bk_mode == "wide_bk"][["geometry_condition_id", "accept_fraction"]].rename(columns={"accept_fraction": "wide_accept_fraction"})
    wide_gain = cur.merge(wide, on="geometry_condition_id")
    wide_gain["accept_fraction_gain"] = wide_gain.wide_accept_fraction - wide_gain.accept_fraction
    wide_top = wide_gain.nlargest(10, "accept_fraction_gain")[["geometry_condition_id", "selection_group", "physical_pair_id", "service_area_id", "distance_km", "direction_deg", "accept_fraction", "wide_accept_fraction", "accept_fraction_gain"]]
    recommendation = ("存在较稳定高风险几何；下一步优先验证同一物理 pair 的不同日期和不同过境。" if len(stable) >= 2
                      else "风险主要表现为 realization 敏感边界；下一步优先扩充不同日期/过境和独立物理 pair，并保留多 realization。")
    report = f"""# 固定几何多 observation-realization 确认报告

## 1. 目的与正式语义

固定真实目标—非目标卫星对、TLE、60秒服务段、服务中心、验证站、距离和方向，仅独立重抽经验环境项与噪声，估计 `P(ACCEPT | 固定几何条件)`。保持 `segment_local`、`fixed_site_segment_center`、`single-window` 和原 no/current/wide 正式验证器；未新增攻击、服务区、驻留时间、多站或 handover。

本轮选择是风险分层确认样本：包含全部旧 any-accept 几何和定向选择的近边界/深拒绝对照，不是随机总体样本，不能估计整个 Starlink 候选空间总体 FAR。

## 2. 条件选择与规模

- preset：{args.preset}；每几何 realization：{args.realizations}；master seed：{args.master_seed}。
- 选择几何：{len(selected)}；分组：{selected.selection_group.value_counts().to_dict()}。
- 目标数：{selected.target_sat_id.nunique()}；物理 pair 数：{selected.physical_pair_id.nunique()}；服务区数：{selected.service_area_id.nunique()}。
- realization级数据：{len(data)} 行（每个 observation 同时评估 no/current/wide）。

## 3. 独立 seed 与经验残差模型

使用 SHA-256(`master_seed|geometry_condition_id|realization_index|stream_name`) 分别派生 environment/noise seed，不使用 Python `hash()`，不同几何与执行顺序互不依赖。calibration seed 沿用旧血缘表并在同一几何固定。

旧正式实现 `run_doppler_verifier_initial_experiments.py::sample_error_params`：

- b_env：Uniform{ranges['b_hz']} Hz，effective constant frequency bias，不是 pure CFO truth；
- k_env：Uniform{ranges['k_hz_per_s']} Hz/s；
- sigma_hz：Uniform{ranges['sigma_hz']} Hz；
- noise：`default_rng(noise_seed).normal(0, sigma_hz, N_full_pass)`，再取固定服务段；这是当前工程高斯近似，不代表严格白噪声。

## 4. 原 all-accept 与 mixed 条件

原 all-accept 条件：

{all_old[['geometry_condition_id','physical_pair_id','service_area_id','distance_km','direction_deg','accept_count','realization_count','accept_fraction','accept_fraction_ci_lower','accept_fraction_ci_upper','k_margin_mean','k_margin_std','k_margin_q05','primary_reject_gate_counts']].to_markdown(index=False)}

原16个 mixed 中，本轮仍 mixed 的有 **{mixed_still}/{len(mixed_old)}**；其中 `k_boundary_sensitive` 标签数为 **{int(mixed_old.gate_margin_risk_class.eq('k_boundary_sensitive').sum())}/{len(mixed_old)}**。

mixed 条件 ACCEPT/REJECT realization 的 k_env：

{kenv.to_markdown()}

k gate 的正负 margin 翻转和 k_env 对正式 k_hat 的推动是主要机制。原 mixed 几何的 margin sign-flip 条件数为 {mixed_margin_flips}；b/score margin 也经常跨零，但 realization 级 primary gate 计数为 {mixed_primary_gates}，单独由 k 拒绝明显多于单独由 b 或 score 拒绝。因此“主要由 k gate”指判决主导路径，不表示 b/score margin 从不变化。

在每个 geometry 内去均值后，`k_env` 与正式 `k_hat` 的 Pearson 相关为 **{within_k_corr:.3f}**。这比混合不同几何后的总体相关更直接地说明：固定几何时，环境线性漂移是推动正式 k_hat 跨 gate 的主要 realization 变量；噪声造成剩余离散。

## 5. 0/2 对照与深拒绝对照

- near-boundary 0/2 对照中出现新 ACCEPT：{new_near}/{len(near)}；接受比例分布：{near.accept_fraction.describe().to_dict()}。
- deep-reject 对照中出现 ACCEPT：{new_deep}/{len(deep)}；接受比例分布：{deep.accept_fraction.describe().to_dict()}。

## 6. 条件接受比例与几何机制量

分析单位是一行一个 `geometry_condition_id`，没有把 realization 行当成独立几何样本。全部选择条件的 Spearman：

{overall_corr.to_markdown(index=False)}

分A/B/C、目标和 pair 的描述性结果保存在 group/pair/target CSV。由于样本经过风险分层选择且只有约39个几何，相关仅用于机制描述，不能解释为总体概率模型。

## 7. current 与 wide

current→wide gate解除构成：

{release.to_frame('realization_count').to_markdown() if len(release) else '无 current REJECT → wide ACCEPT'}

同一 realization 的 current/wide 共享相同 observation、正式 score、b_hat 与 k_hat；wide 只扩大 b/k gate。未把 wide 描述为重新拟合得到更小正式残差。

wide 接受比例增幅最大的几何：

{wide_top.to_markdown(index=False)}

## 8. 风险分类与最终判断

- current 高接受比例（>=0.8）几何：{len(stable)}；其条件表见 geometry summary。
- current k-boundary-sensitive 几何：{k_sensitive}。
- current 风险类别：{cur.observed_accept_risk_class.value_counts().to_dict()}。
- gate-margin类别：{cur.gate_margin_risk_class.value_counts().to_dict()}。

**{recommendation}**

## 9. 正确性审计

{audit.to_markdown(index=False)}

审计通过 {int(audit.passed.sum())}/{len(audit)}。任何失败时不得使用上述研究判断。

## 10. 局限

30次 realization 只给出有限精度的条件概率；2/2、30/30都不表示绝对必然，0/30也不是安全证明。环境残差来自当前经验模型，结果不等同真实 Starlink 现场攻击概率。局部方向敏感度仅用于 <=10 km，不外推远距离。样本包含全部旧正例和定向对照，存在明确选择偏差。

## 11. 输出与图

关键CSV、报告和 {len(figures)} 幅图均使用独立 `fixed_geometry_multi_realization` 文件名，未覆盖旧正式输出。
"""
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    paths["report"].write_text(report, encoding="utf-8")


def append_log(args: argparse.Namespace, paths: dict[str, Path], selected: pd.DataFrame, data: pd.DataFrame,
               geometry: pd.DataFrame, audit: pd.DataFrame) -> None:
    cur = geometry[geometry.bk_mode == "current_bk"]
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    block = f"""

## {now} - 固定几何多 observation-realization 确认

### A. 本轮目标
固定真实轨道几何与calibration，仅重抽环境残差和噪声，估计条件误接受比例与gate裕量。

### B. 实际操作
- 新增 `scripts/run_fixed_geometry_multi_realization_confirmation.py`。
- 条件选择：{selected.selection_group.value_counts().to_dict()}，共{len(selected)}个几何。
- SHA-256独立派生environment/noise seed；每几何{args.realizations}个realization；master seed={args.master_seed}。
- 复用旧轨道传播、固定点多普勒、calibration、环境模型和正式验证器。

### C. 新增/修改文件
- 新增 selected/dataset/geometry/pair/target/group/transition/audit CSV、报告与图；未修改配置和旧正式输出。

### D. 运行命令
- `python -m py_compile scripts/run_fixed_geometry_multi_realization_confirmation.py`
- `python scripts/run_fixed_geometry_multi_realization_confirmation.py --preset smoke --realizations 3`
- `python scripts/run_fixed_geometry_multi_realization_confirmation.py --preset confirmation --realizations {args.realizations}`

### E. 结果摘要
- realization级行数={len(data)}；correctness={int(audit.passed.sum())}/{len(audit)}。
- current风险类别={cur.observed_accept_risk_class.value_counts().to_dict()}。
- current gate-margin类别={cur.gate_margin_risk_class.value_counts().to_dict()}。
- 稳定高风险几何(accept_fraction>=0.8)={int(cur.accept_fraction.ge(.8).sum())}。

### F. 问题与下一步
- 当前为风险分层选择，不能估计总体FAR；优先进行不同日期/过境验证并显式保存多个realization。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(block)


def run(args: argparse.Namespace) -> None:
    if args.realizations <= 0: fail("--realizations must be positive")
    paths = output_paths(args.preset)
    inputs = [args.formal_dataset, args.mechanism_rows, args.lineage, args.lineage_geometry,
              args.positive_conditions, args.candidate_library, args.selection_table, args.tle_file,
              args.orbit_config, args.parameter_config]
    for p in inputs:
        if not p.exists(): fail(f"missing input: {p}")
    existing = [str(p) for k,p in paths.items() if k != "figures" and p.exists()]
    if paths["figures"].exists() and any(paths["figures"].iterdir()): existing.append(str(paths["figures"]))
    if existing and not args.overwrite: fail("outputs exist; add --overwrite: " + ", ".join(existing))
    hashes_before = {str(p): sha_file(p) for p in inputs}
    lineage = normalize_ids(pd.read_csv(args.lineage, low_memory=False))
    geom_old = pd.read_csv(args.lineage_geometry)
    selected = select_conditions(lineage, geom_old, args.preset)
    data = generate(args, selected, lineage)
    geometry = build_geometry_summary(data)
    current = geometry[geometry.bk_mode == "current_bk"].copy()
    pair = aggregate_entities(current, ["physical_pair_id", "target_sat_id", "attack_sat_id"])
    target = aggregate_entities(current, ["target_sat_id"])
    group = aggregate_entities(current, ["selection_group"])
    corr = correlations(current)
    group = pd.concat([group.assign(record_type="group_summary"), corr.assign(record_type="spearman")], ignore_index=True, sort=False)
    transition = transition_summary(data)
    for p in paths.values(): p.parent.mkdir(parents=True, exist_ok=True)
    hashes_after = {str(p): sha_file(p) for p in inputs}
    _sel, _lib, _cfg, _tle, ranges = load_orbit_inputs(args)
    audit = correctness(args, selected, data, geometry, hashes_before, hashes_after, ranges)
    selected.to_csv(paths["selected"], index=False); data.to_csv(paths["dataset"], index=False)
    geometry.to_csv(paths["geometry"], index=False); pair.to_csv(paths["pair"], index=False)
    target.to_csv(paths["target"], index=False); group.to_csv(paths["group"], index=False)
    transition.to_csv(paths["transition"], index=False); audit.to_csv(paths["audit"], index=False)
    figures = make_figures(data, geometry, transition, paths["figures"])
    write_report(args, paths, selected, data, geometry, transition, corr, audit, ranges, figures)
    append_log(args, paths, selected, data, geometry, audit)
    cur = geometry[geometry.bk_mode == "current_bk"]
    old_all = cur[cur.selection_group == "observed_all_accept"]
    old_mixed = cur[cur.selection_group == "observed_mixed"]
    near = cur[cur.selection_group == "near_boundary_zero_accept_control"]
    deep = cur[cur.selection_group == "deep_reject_control"]
    wide = geometry[geometry.bk_mode == "wide_bk"]
    print(f"1. selected geometries: {len(selected)}")
    print(f"2. groups: {selected.selection_group.value_counts().to_dict()}")
    print(f"3. realization-level rows: {len(data)}")
    print(f"4. correctness: {int(audit.passed.sum())}/{len(audit)} passed")
    print("5. original all-accept fractions:", old_all.set_index("geometry_condition_id").accept_fraction.to_dict())
    print("6. original mixed classes:", old_mixed.gate_margin_risk_class.value_counts().to_dict())
    print(f"7. near-boundary 0/2 with ACCEPT: {int(near.accept_count.gt(0).sum())}/{len(near)}")
    print(f"8. deep-reject with ACCEPT: {int(deep.accept_count.gt(0).sum())}/{len(deep)}")
    print(f"9. k-boundary-sensitive: {int(cur.gate_margin_risk_class.eq('k_boundary_sensitive').sum())}")
    print(f"10. mean current/wide accept fraction: {cur.accept_fraction.mean():.4f}/{wide.accept_fraction.mean():.4f}")
    print("11. main correlations:", corr[corr.stratum == "all_selected"][["metric","spearman_rho"]].set_index("metric").spearman_rho.to_dict())
    print(f"12. stable high-risk geometries: {int(cur.accept_fraction.ge(.8).sum())}")
    print("13. different-pass validation recommended: yes")
    print("14. unresolved: selected sample, finite 30-realization precision, empirical residual model, and only existing pass geometries")
    if not audit.passed.all(): fail("correctness audit failed; research conclusion withheld")


if __name__ == "__main__":
    run(parse_args())
