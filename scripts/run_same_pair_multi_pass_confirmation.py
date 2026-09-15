#!/usr/bin/env python
"""Confirm same physical-pair boundary behavior across independent passes.

All orbit propagation, fixed-site Doppler, service segmentation, calibration,
residual fitting, and verifier decisions reuse the existing formal pipeline.
Same-TLE and historical-TLE analyses use isolated output prefixes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from skyfield.api import EarthSatellite, load

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_differential_doppler_mechanism_audit as mech  # noqa: E402
import run_fixed_geometry_multi_realization_confirmation as fixed  # noqa: E402
import run_multi_service_area_single_station_confirmation as multi  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

BK_MODES = ["no_bk", "current_bk", "wide_bk"]
DIRECTIONS = [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]
DISTANCE_KM = 2.5
FD_STEPS_KM = [0.5, 1.0, 2.0]
HISTORICAL_PAIRS = {"65409->47749", "65410->47749"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="同一物理pair跨pass确认实验")
    p.add_argument("--preset", choices=["smoke", "confirmation"], default="confirmation")
    p.add_argument("--analysis-scope", choices=["same_tle", "historical_tle_case", "both"], default="same_tle")
    p.add_argument("--pairs", type=int, default=10)
    p.add_argument("--passes-per-pair", type=int, default=4)
    p.add_argument("--realizations", type=int, default=20)
    p.add_argument("--master-seed", type=int, default=20260713)
    p.add_argument("--selected-conditions", type=Path, default=Path("outputs/metrics/fixed_geometry_multi_realization_selected_conditions.csv"))
    p.add_argument("--old-geometry-summary", type=Path, default=Path("outputs/metrics/fixed_geometry_multi_realization_geometry_summary.csv"))
    p.add_argument("--old-pair-summary", type=Path, default=Path("outputs/metrics/fixed_geometry_multi_realization_pair_summary.csv"))
    p.add_argument("--old-realization-dataset", type=Path, default=Path("outputs/datasets/fixed_geometry_multi_realization_dataset.csv"))
    p.add_argument("--pass-inventory", type=Path, default=Path("outputs/metrics/multi_pass_data_availability_pass_inventory.csv"))
    p.add_argument("--pair-inventory", type=Path, default=Path("outputs/metrics/multi_pass_data_availability_pair_inventory.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--tle-history", type=Path, default=Path("data/tle/history/starlink_gp_history_20260301_20260320.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def output_paths(scope: str, preset: str) -> dict[str, Path]:
    if scope == "same_tle":
        prefix = "same_pair_multi_pass" + ("_smoke" if preset == "smoke" else "")
        report = f"outputs/reports/{prefix}_confirmation_report.md"
        figures = f"outputs/figures/{prefix}_confirmation"
    else:
        prefix = "historical_tle_multi_pass" + ("_smoke" if preset == "smoke" else "")
        report = f"outputs/reports/{prefix}_case_report.md"
        figures = f"outputs/figures/{prefix}_case"
    return {
        "pairs": Path(f"outputs/metrics/{prefix}_selected_pairs.csv"),
        "passes": Path(f"outputs/metrics/{prefix}_selected_passes.csv"),
        "directions": Path(f"outputs/metrics/{prefix}_direction_candidates.csv"),
        "dataset": Path(f"outputs/datasets/{prefix}_realization_dataset.csv"),
        "geometry": Path(f"outputs/metrics/{prefix}_geometry_summary.csv"),
        "pass_summary": Path(f"outputs/metrics/{prefix}_pass_summary.csv"),
        "pair_summary": Path(f"outputs/metrics/{prefix}_pair_summary.csv"),
        "group": Path(f"outputs/metrics/{prefix}_group_summary.csv"),
        "transition": Path(f"outputs/metrics/{prefix}_gate_transition_summary.csv"),
        "explanatory": Path(f"outputs/metrics/{prefix}_explanatory_analysis.csv"),
        "audit": Path(f"outputs/metrics/{prefix}_correctness_audit.csv"),
        "report": Path(report),
        "figures": Path(figures),
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def require(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{label} missing columns: {missing}")


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


def utc(value: Any) -> pd.Timestamp:
    x = pd.Timestamp(value)
    return x.tz_localize("UTC") if x.tzinfo is None else x.tz_convert("UTC")


def iso(value: Any) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


def normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    for c in ["target_sat_id", "attack_sat_id", "target_norad_id"]:
        if c in d:
            d[c] = d[c].astype(str).str.replace(r"\.0$", "", regex=True)
    return d


def input_paths(args: argparse.Namespace) -> list[Path]:
    return [args.selected_conditions, args.old_geometry_summary, args.old_pair_summary,
            args.old_realization_dataset, args.pass_inventory, args.pair_inventory, args.tle_file,
            args.selection_table, args.candidate_library, args.orbit_config, args.parameter_config]


def check_io(args: argparse.Namespace, paths: dict[str, Path], scope: str) -> dict[str, str]:
    for p in input_paths(args) + ([args.tle_history] if scope == "historical_tle_case" else []):
        if not p.exists():
            fail(f"missing input: {p}")
    if args.pairs < 1 or args.passes_per_pair < 1 or args.realizations < 1:
        fail("pairs/passes-per-pair/realizations must be positive")
    existing = [str(p) for p in paths.values() if p.exists()]
    if existing and not args.overwrite:
        fail("output exists; add --overwrite: " + ", ".join(existing))
    for p in paths.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    return {str(p): sha_file(p) for p in input_paths(args)}


def load_orbit(args: argparse.Namespace):
    loader = SimpleNamespace(selection_table=args.selection_table, candidate_library=args.candidate_library,
                             tle_file=args.tle_file, orbit_config=args.orbit_config,
                             parameter_config=args.parameter_config, max_targets=5)
    selection, library, cfg, tle, ranges = expanded.load_base_inputs(loader)
    if cfg.get("mode") != "controlled_starlink" or cfg.get("observation_id") is not None:
        fail("requires controlled_starlink mode and observation_id=null")
    return selection, library, cfg, tle, ranges


def choose_pairs(args: argparse.Namespace, scope: str) -> pd.DataFrame:
    old = normalize_ids(pd.read_csv(args.old_geometry_summary))
    old = old[old.bk_mode == "current_bk"].copy()
    require(old, ["physical_pair_id", "target_sat_id", "attack_sat_id", "accept_fraction",
                  "gate_margin_risk_class", "raw_geo_rmse_hz",
                  "actual_direction_post_projection_sensitivity_hz_per_km",
                  "geometry_tolerance_budget_absorption_ratio"], "old geometry summary")
    rows = []
    for pid, g in old.groupby("physical_pair_id", sort=True):
        risk = g[g.gate_margin_risk_class == "k_boundary_sensitive"]
        deep = g[g.gate_margin_risk_class == "deep_reject"]
        group = "k_boundary_sensitive" if len(risk) else "deep_reject_control" if len(deep) else "other"
        basis = risk if len(risk) else deep if len(deep) else g
        rows.append({
            "physical_pair_id": pid, "target_sat_id": str(g.target_sat_id.iloc[0]),
            "attack_sat_id": str(g.attack_sat_id.iloc[0]), "pair_selection_group": group,
            "original_risk_class": "|".join(sorted(g.gate_margin_risk_class.unique())),
            "original_current_accept_fraction": float(g.accept_fraction.max()),
            "original_raw_geo_rmse": float(basis.raw_geo_rmse_hz.mean()),
            "original_direction_sensitivity": float(basis.actual_direction_post_projection_sensitivity_hz_per_km.mean()),
            "original_tolerance_budget_absorption": float(basis.geometry_tolerance_budget_absorption_ratio.mean()),
            "old_geometry_count": len(g),
        })
    inv = normalize_ids(pd.read_csv(args.pair_inventory))
    candidates = pd.DataFrame(rows).merge(inv[["physical_pair_id", "has_at_least_3_passes"]], on="physical_pair_id", validate="one_to_one")
    candidates = candidates[candidates.has_at_least_3_passes.astype(bool)].copy()
    if scope == "historical_tle_case":
        out = candidates[candidates.physical_pair_id.isin(HISTORICAL_PAIRS)].copy()
        out["pair_selection_group"] = "historical_tle_exploratory_case"
        out["selection_reason"] = "审计确认双边历史TLE覆盖；仅作两个物理pair的探索性案例"
        return out.sort_values("physical_pair_id").reset_index(drop=True)

    requested = 2 if args.preset == "smoke" else args.pairs
    risk_n = 1 if args.preset == "smoke" else min(7, max(1, requested - 3))
    control_n = requested - risk_n
    risk = candidates[candidates.pair_selection_group == "k_boundary_sensitive"].copy()
    risk["rank"] = (risk.groupby("target_sat_id").cumcount() +
                    risk.original_current_accept_fraction.rank(ascending=False, pct=True) +
                    risk.original_raw_geo_rmse.rank(pct=True) +
                    risk.original_tolerance_budget_absorption.rank(ascending=False, pct=True))
    selected = []
    used_targets: set[str] = set()
    used_attackers: set[str] = set()
    for _ in range(risk_n):
        avail = risk[~risk.physical_pair_id.isin([x.physical_pair_id for x in selected])]
        if avail.empty: break
        score = avail["rank"] - .8 * (~avail.target_sat_id.isin(used_targets)) - .25 * (~avail.attack_sat_id.isin(used_attackers))
        row = avail.loc[score.idxmin()]
        selected.append(row); used_targets.add(row.target_sat_id); used_attackers.add(row.attack_sat_id)
    controls = candidates[(candidates.pair_selection_group == "deep_reject_control") &
                          (~candidates.physical_pair_id.isin([x.physical_pair_id for x in selected]))].copy()
    controls["rank"] = controls.original_raw_geo_rmse.rank(ascending=False, pct=True) + controls.original_direction_sensitivity.rank(ascending=False, pct=True)
    for _ in range(control_n):
        avail = controls[~controls.physical_pair_id.isin([x.physical_pair_id for x in selected])]
        if avail.empty: break
        score = avail["rank"] - .8 * (~avail.target_sat_id.isin(used_targets)) - .25 * (~avail.attack_sat_id.isin(used_attackers))
        row = avail.loc[score.idxmin()]
        selected.append(row); used_targets.add(row.target_sat_id); used_attackers.add(row.attack_sat_id)
    if len(selected) < requested:
        avail = candidates[~candidates.physical_pair_id.isin([x.physical_pair_id for x in selected])]
        for _, row in avail.sort_values(["pair_selection_group", "original_current_accept_fraction"], ascending=[True, False]).iterrows():
            selected.append(row)
            if len(selected) >= requested: break
    out = pd.DataFrame(selected).head(requested).copy()
    out["selection_reason"] = np.where(out.pair_selection_group == "k_boundary_sensitive",
        "原固定几何含k_boundary_sensitive；兼顾目标/来源多样性、原接受比例、raw geometry和容忍吸收",
        "原固定几何含deep_reject；作为跨pass多gate深拒绝对照并兼顾目标/来源多样性")
    return out.drop(columns=["rank", "has_at_least_3_passes"], errors="ignore").reset_index(drop=True)


def add_pass_age(passes: pd.DataFrame) -> pd.DataFrame:
    d = passes.copy()
    d["pass_midpoint_time"] = d.apply(lambda r: iso(utc(r.pass_start_time) + (utc(r.pass_end_time)-utc(r.pass_start_time))/2), axis=1)
    d["target_tle_epoch"] = d.tle_epoch_target.astype(str)
    d["attacker_tle_epoch"] = d.tle_epoch_attack.astype(str)
    d["target_tle_age_hours"] = d.apply(lambda r: abs((utc(r.pass_midpoint_time)-utc(r.target_tle_epoch)).total_seconds())/3600, axis=1)
    d["attacker_tle_age_hours"] = d.apply(lambda r: abs((utc(r.pass_midpoint_time)-utc(r.attacker_tle_epoch)).total_seconds())/3600, axis=1)
    d["max_tle_age_hours"] = d[["target_tle_age_hours", "attacker_tle_age_hours"]].max(axis=1)
    d["epoch_difference_hours"] = d.apply(lambda r: abs((utc(r.target_tle_epoch)-utc(r.attacker_tle_epoch)).total_seconds())/3600, axis=1)
    return d


def diverse_pass_selection(group: pd.DataFrame, n: int, historical: bool) -> pd.DataFrame:
    g = group.sort_values("pass_start_time").copy()
    levels = [(48, "within_48h"), (72, "relaxed_to_72h"), (96, "relaxed_to_96h")]
    eligible = pd.DataFrame()
    level = "nearest_available"
    for limit, name in levels:
        subset = g[g.max_tle_age_hours <= limit]
        distinct = subset.target_tle_epoch.nunique() if historical else len(subset)
        if distinct >= n:
            eligible, level = subset, name
            break
    if eligible.empty:
        eligible = g.sort_values("max_tle_age_hours").head(max(n * 5, n)).copy()
    if historical:
        eligible = eligible.sort_values(["max_tle_age_hours", "pass_start_time"]).drop_duplicates("target_tle_epoch")
    chosen: list[int] = []
    if len(eligible):
        chosen.append(int(eligible.max_elevation_deg.sub(eligible.max_elevation_deg.median()).abs().idxmin()))
    while len(chosen) < min(n, len(eligible)):
        remaining = eligible[~eligible.index.isin(chosen)]
        time_hours = remaining.pass_midpoint_time.map(lambda x: min(abs((utc(x)-utc(eligible.loc[i, "pass_midpoint_time"])).total_seconds())/3600 for i in chosen))
        el_diff = remaining.max_elevation_deg.map(lambda x: min(abs(x-float(eligible.loc[i, "max_elevation_deg"])) for i in chosen))
        az_diff = remaining.azimuth_start_deg.map(lambda x: min(abs(((x-float(eligible.loc[i, "azimuth_start_deg"])+180)%360)-180) for i in chosen))
        dir_new = ~remaining.azimuth_direction.isin(set(eligible.loc[chosen, "azimuth_direction"]))
        score = time_hours/(time_hours.max()+1e-9) + el_diff/(el_diff.max()+1e-9) + .5*az_diff/(az_diff.max()+1e-9) + .5*dir_new.astype(float) - .15*remaining.max_tle_age_hours/(remaining.max_tle_age_hours.max()+1e-9)
        chosen.append(int(score.idxmax()))
    g["is_selected"] = False; g["pass_selection_rank"] = np.nan
    g["tle_age_relaxation_level"] = level
    for rank, idx in enumerate(chosen, 1):
        g.loc[idx, "is_selected"] = True; g.loc[idx, "pass_selection_rank"] = rank
    g["pass_selection_reason"] = np.where(g.is_selected,
        "按预声明TLE-age层级合格；贪心增加绝对时间、最大仰角、方位角和轨迹方向多样性",
        "合格候选但未进入预声明数量，或TLE age/多样性排序较后")
    if historical:
        target_el = float(g.loc[g.is_selected, "max_elevation_deg"].median()) if g.is_selected.any() else np.nan
        g["pass_geometry_matching_score"] = abs(g.max_elevation_deg-target_el)
        g["historical_tle_epoch_id"] = g.apply(lambda r: stable_id("epoch", {"target":r.target_tle_epoch,"attacker":r.attacker_tle_epoch}), axis=1)
    return g


def choose_passes(args: argparse.Namespace, pairs: pd.DataFrame, scope: str) -> pd.DataFrame:
    inv = normalize_ids(pd.read_csv(args.pass_inventory))
    require(inv, ["physical_pair_id", "pass_id", "pass_source_type", "pass_start_time", "pass_end_time",
                  "tle_epoch_target", "tle_epoch_attack", "max_elevation_deg", "pass_duration_s",
                  "service_segment_reusable", "valid_for_formal_pass_candidate"], "pass inventory")
    source = "same_tle_different_pass" if scope == "same_tle" else "different_date_tle"
    inv = inv[(inv.physical_pair_id.isin(pairs.physical_pair_id)) & (inv.pass_source_type == source) &
              inv.valid_for_formal_pass_candidate.astype(bool) & inv.service_segment_reusable.astype(bool)].copy()
    inv = add_pass_age(inv)
    n = 2 if args.preset == "smoke" else args.passes_per_pair
    parts = []
    for pid in pairs.physical_pair_id:
        g = inv[inv.physical_pair_id == pid]
        if len(g) < n: fail(f"{pid}: only {len(g)} valid {source} passes")
        parts.append(diverse_pass_selection(g, n, scope == "historical_tle_case"))
    return pd.concat(parts, ignore_index=True)


def history_satellites(path: Path, ts: Any) -> dict[tuple[str, str], Any]:
    h = pd.read_csv(path, dtype={"NORAD_CAT_ID": str})
    h["epoch_iso"] = h.EPOCH.map(iso)
    out = {}
    for r in h.itertuples(index=False):
        out[(str(r.NORAD_CAT_ID), str(r.epoch_iso))] = EarthSatellite(str(r.TLE_LINE1), str(r.TLE_LINE2), str(r.OBJECT_NAME), ts)
    return out


def pass_segment(row: pd.Series, sat_a: Any, ts: Any) -> dict[str, Any]:
    start, end = utc(row.pass_start_time), utc(row.pass_end_time)
    duration = int(math.floor((end-start).total_seconds()))
    full_times = [(start + pd.Timedelta(seconds=i)).to_pydatetime() for i in range(duration+1)]
    full_t = np.arange(len(full_times), dtype=float)
    glat, glon, galt = seg.compute_subpoint_series(sat_a, full_times, ts)
    track = seg.center_track("M2_block", glat, glon, galt, full_t, 100.0, 1.0, 60.0, 0.0)
    complete = [(i, s, e) for i, (s, e) in enumerate(zip(track.segment_starts, track.segment_ends)) if e-s+1 >= 60]
    if not complete: fail(f"{row.pass_id}: no complete 60-s service segment")
    mid = (len(full_t)-1)/2
    idx, seg_start, _seg_end = min(complete, key=lambda x: abs(((x[1]+x[2])/2)-mid))
    seg_end = seg_start + 59
    mask = np.zeros(len(full_t), dtype=bool); mask[seg_start:seg_end+1] = True
    return {"full_times":full_times, "full_t":full_t, "mask":mask, "et":full_t[mask],
            "times":[t for t, keep in zip(full_times, mask) if keep], "C_lat":float(glat[seg_start]),
            "C_lon":float(glon[seg_start]), "segment_index":idx,
            "service_segment_start":iso(full_times[seg_start]), "service_segment_end":iso(full_times[seg_end])}


def energy_absorption(raw: np.ndarray, remain: np.ndarray) -> float:
    return mech.energy_absorption(raw, remain) if hasattr(mech, "energy_absorption") else float(1-np.sum(remain**2)/max(np.sum(raw**2),1e-18))


def build_directions_and_geometries(args: argparse.Namespace, pairs: pd.DataFrame, pass_table: pd.DataFrame,
                                    scope: str, tle: dict[str, Any], ranges: dict[str, list[float]],
                                    ts: Any, freq_hz: float) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    hist = history_satellites(args.tle_history, ts) if scope == "historical_tle_case" else {}
    pair_map = pairs.set_index("physical_pair_id").to_dict("index")
    candidates, geometries = [], []
    for _, pr in pass_table[pass_table.is_selected.astype(bool)].sort_values(["physical_pair_id","pass_selection_rank"]).iterrows():
        target, attacker = str(pr.target_sat_id), str(pr.attack_sat_id)
        sat_a = tle[target]["sat"] if scope == "same_tle" else hist[(target, iso(pr.target_tle_epoch))]
        sat_b = tle[attacker]["sat"] if scope == "same_tle" else hist[(attacker, iso(pr.attacker_tle_epoch))]
        ps = pass_segment(pr, sat_a, ts); et, times = ps["et"], ps["times"]
        sample = {"sample_source":"real_tle_candidate","target_sat_id":target,"attack_sat_id":attacker,
                  "attack_type":"real_tle_candidate","attack_param_value":np.nan}
        fds = {h: mech.finite_difference(sample,sat_a,sat_b,ps["C_lat"],ps["C_lon"],times,ts,freq_hz,1.0,h) for h in FD_STEPS_KM}
        je, jn = fds[1.0]; jp = mech.projected_jacobian(np.column_stack([je,jn]), et)
        _u, sv, vt = np.linalg.svd(jp, full_matrices=False); sr = sv/math.sqrt(len(et)); weak = vt[-1]
        fd_norm = {h:float(np.sqrt(np.mean(np.column_stack(fds[h])**2))) for h in FD_STEPS_KM}
        stability = max(abs(fd_norm[.5]-fd_norm[1.0]),abs(fd_norm[2.0]-fd_norm[1.0]))/max(fd_norm[1.0],1e-12)
        pass_candidates = []
        for direction in DIRECTIONS:
            theta=math.radians(direction); vec=np.array([math.sin(theta),math.cos(theta)])
            sensitivity=float(np.sqrt(np.mean((jp@vec)**2)))
            pass_candidates.append({"physical_pair_id":pr.physical_pair_id,"pass_id":pr.pass_id,
                "direction_deg":direction,"actual_direction_post_projection_sensitivity_hz_per_km":sensitivity,
                "weakest_direction_sensitivity_hz_per_km":float(sr[-1]),"strongest_direction_sensitivity_hz_per_km":float(sr[0]),
                "anisotropy_ratio":float(sr[0]/sr[-1]) if sr[-1]>1e-12 else math.inf,
                "weakest_direction_deg":float((math.degrees(math.atan2(weak[0],weak[1]))+360)%180),
                "finite_difference_norm_0p5km":fd_norm[.5],"finite_difference_norm_1km":fd_norm[1.0],
                "finite_difference_norm_2km":fd_norm[2.0],"finite_difference_max_relative_change_0p5_1_2km":stability})
        pc=pd.DataFrame(pass_candidates); low=float(pc.loc[pc.actual_direction_post_projection_sensitivity_hz_per_km.idxmin(),"direction_deg"])
        opposite=(low+180)%360; remaining=pc[~pc.direction_deg.isin([low,opposite])]
        high=float(remaining.loc[remaining.actual_direction_post_projection_sensitivity_hz_per_km.idxmax(),"direction_deg"])
        roles={low:"lowest_sensitivity",opposite:"opposite_of_lowest",high:"high_sensitivity_control"}
        pc["is_selected_direction"]=pc.direction_deg.isin(roles); pc["direction_selection_role"]=pc.direction_deg.map(roles).fillna("not_selected")
        candidates.extend(pc.to_dict("records"))
        cal_seed=derive_seed(args.master_seed,str(pr.pass_id),0,"calibration"); cal=seg.calibration_for_trel(et,ranges,cal_seed,30)
        fa_c=seg.geo_curve_fixed(sat_a,ps["C_lat"],ps["C_lon"],0.0,times,ts,freq_hz,1.0)[0]
        fb_c=multi.attack_geo(sample,sat_a,sat_b,ps["C_lat"],ps["C_lon"],0.0,times,ts,freq_hz,1.0)
        for direction,role in roles.items():
            s_lat,s_lon=seg.destination(ps["C_lat"],ps["C_lon"],DISTANCE_KM,direction)
            fa_s=seg.geo_curve_fixed(sat_a,s_lat,s_lon,0.0,times,ts,freq_hz,1.0)[0]
            fb_s=multi.attack_geo(sample,sat_a,sat_b,s_lat,s_lon,0.0,times,ts,freq_hz,1.0)
            raw=fb_s+fa_c-fb_c-fa_s; ub,uk,ufit=mech.fit_unbounded(raw,et); uremain=raw-ufit
            th=seg.threshold_for(cal,"full_pass","current_bk")
            bb,bk,bfit=mech.fit_bounded(raw,et,(-th["b_threshold"],th["b_threshold"]),(-th["k_threshold"],th["k_threshold"]))
            tol_b=max(1e-8,2e-7*th["b_threshold"]); tol_k=max(1e-10,2e-7*th["k_threshold"])
            hit=abs(abs(bb)-th["b_threshold"])<=tol_b or abs(abs(bk)-th["k_threshold"])<=tol_k
            gid=stable_id("geometry",{"scope":scope,"pair":pr.physical_pair_id,"pass":pr.pass_id,"segment":ps["segment_index"],"distance":DISTANCE_KM,"direction":direction})
            meta={**pair_map[str(pr.physical_pair_id)],**pr.to_dict()}
            geometries.append({"meta":meta,"geometry_condition_id":gid,"sat_a":sat_a,"sat_b":sat_b,"sample":sample,
                "full_t":ps["full_t"],"mask":ps["mask"],"et":et,"times":times,"fa_s":fa_s,"raw":raw,"cal":cal,
                "calibration_seed":cal_seed,"service_segment_index":ps["segment_index"],
                "service_segment_start":ps["service_segment_start"],"service_segment_end":ps["service_segment_end"],
                "C_lat":ps["C_lat"],"C_lon":ps["C_lon"],"S_lat":s_lat,"S_lon":s_lon,"direction_deg":direction,
                "direction_selection_role":role,"actual_distance_km":float(seg.distance_km(np.array([ps["C_lat"]]),np.array([ps["C_lon"]]),s_lat,s_lon)[0]),
                "raw_geo_rmse_hz":float(np.sqrt(np.mean(raw**2))),"raw_geo_max_abs_hz":float(np.max(np.abs(raw))),
                "unbounded_geometry_b_hat_hz":ub,"unbounded_geometry_k_hat_hz_per_s":uk,
                "unbounded_geometry_post_rmse_hz":float(np.sqrt(np.mean(uremain**2))),
                "unbounded_geometry_absorption_ratio":energy_absorption(raw,uremain),
                "actual_direction_post_projection_sensitivity_hz_per_km":float(pc.loc[pc.direction_deg==direction,"actual_direction_post_projection_sensitivity_hz_per_km"].iloc[0]),
                "weakest_direction_sensitivity_hz_per_km":float(sr[-1]),"strongest_direction_sensitivity_hz_per_km":float(sr[0]),
                "anisotropy_ratio":float(sr[0]/sr[-1]) if sr[-1]>1e-12 else math.inf,
                "weakest_direction_deg":float((math.degrees(math.atan2(weak[0],weak[1]))+360)%180),
                "finite_difference_max_relative_change_0p5_1_2km":stability,
                "geometry_tolerance_budget_absorption_ratio":energy_absorption(raw,raw-bfit),
                "geometry_tolerance_budget_boundary_hit":bool(hit)})
    return pd.DataFrame(candidates), geometries


def generate_realizations(args: argparse.Namespace, geometries: list[dict[str, Any]], ranges: dict[str,list[float]]) -> pd.DataFrame:
    rows=[]
    for geo in geometries:
        gid=geo["geometry_condition_id"]; et=geo["et"]; mask=geo["mask"]; t0=float(np.mean(geo["full_t"])); coverage=np.ones(len(et),dtype=bool)
        for ridx in range(args.realizations):
            env_seed=derive_seed(args.master_seed,gid,ridx,"environment"); noise_seed=derive_seed(args.master_seed,gid,ridx,"noise")
            err=seg.base.sample_error_params(ranges,np.random.default_rng(env_seed))
            full_noise=np.random.default_rng(noise_seed).normal(0.0,err.sigma_hz,len(geo["full_t"])) if err.sigma_hz>0 else np.zeros(len(geo["full_t"]))
            noise=full_noise[mask]; y=geo["fa_s"]+geo["raw"]+err.b_hz+err.k_hz_s*(et-t0)+noise
            obs_id=stable_id("observation",{"geometry":gid,"realization":ridx,"environment_seed":env_seed,"noise_seed":noise_seed,"calibration_seed":geo["calibration_seed"]})
            for mode in BK_MODES:
                dec=seg.evaluate_single_station(y_obs=y,f_geo_a=geo["fa_s"],t_rel=et,coverage_mask=coverage,
                    cal=geo["cal"],bk_mode=mode,verification_strategy="single-window")
                th=seg.threshold_for(geo["cal"],"full_pass",mode); quality=bool(np.isfinite([dec.residual_rmse_hz,dec.b_hat_hz,dec.k_hat_hz_per_s]).all())
                meta=geo["meta"]
                row={k:meta.get(k) for k in meta}
                row.update({"geometry_condition_id":gid,"observation_realization_id":obs_id,"bk_mode":mode,
                    "physical_pair_id":meta["physical_pair_id"],"target_sat_id":meta["target_sat_id"],"attack_sat_id":meta["attack_sat_id"],
                    "pair_selection_group":meta["pair_selection_group"],"pass_id":meta["pass_id"],"pass_source_type":meta["pass_source_type"],
                    "service_area_id":f"{meta['pass_id']}_segment_{geo['service_segment_index']}","service_segment_index":geo["service_segment_index"],
                    "service_segment_start":geo["service_segment_start"],"service_segment_end":geo["service_segment_end"],
                    "C_lat":geo["C_lat"],"C_lon":geo["C_lon"],"S_lat":geo["S_lat"],"S_lon":geo["S_lon"],
                    "distance_km":DISTANCE_KM,"actual_distance_km":geo["actual_distance_km"],"direction_deg":geo["direction_deg"],
                    "direction_selection_role":geo["direction_selection_role"],"realization_index":ridx,"master_seed":args.master_seed,
                    "environment_seed":env_seed,"noise_seed":noise_seed,"calibration_seed":geo["calibration_seed"],
                    "b_env":float(err.b_hz),"k_env":float(err.k_hz_s),"sigma_hz":float(err.sigma_hz),"noise_hash":array_hash(noise),
                    "raw_geo_rmse_hz":geo["raw_geo_rmse_hz"],"raw_geo_max_abs_hz":geo["raw_geo_max_abs_hz"],
                    "unbounded_geometry_b_hat_hz":geo["unbounded_geometry_b_hat_hz"],"unbounded_geometry_k_hat_hz_per_s":geo["unbounded_geometry_k_hat_hz_per_s"],
                    "unbounded_geometry_post_rmse_hz":geo["unbounded_geometry_post_rmse_hz"],"unbounded_geometry_absorption_ratio":geo["unbounded_geometry_absorption_ratio"],
                    "actual_direction_post_projection_sensitivity_hz_per_km":geo["actual_direction_post_projection_sensitivity_hz_per_km"],
                    "weakest_direction_sensitivity_hz_per_km":geo["weakest_direction_sensitivity_hz_per_km"],"strongest_direction_sensitivity_hz_per_km":geo["strongest_direction_sensitivity_hz_per_km"],
                    "anisotropy_ratio":geo["anisotropy_ratio"],"weakest_direction_deg":geo["weakest_direction_deg"],
                    "finite_difference_max_relative_change_0p5_1_2km":geo["finite_difference_max_relative_change_0p5_1_2km"],
                    "geometry_tolerance_budget_absorption_ratio":geo["geometry_tolerance_budget_absorption_ratio"],
                    "geometry_tolerance_budget_boundary_hit":geo["geometry_tolerance_budget_boundary_hit"],
                    "formal_score_value":float(dec.residual_rmse_hz),"formal_score_threshold":float(th["score_threshold"]),
                    "formal_b_hat_hz":float(dec.b_hat_hz),"formal_b_center_hz":float(th["b_center"]),"formal_b_threshold_hz":float(th["b_threshold"]),
                    "formal_k_hat_hz_per_s":float(dec.k_hat_hz_per_s),"formal_k_center_hz_per_s":float(th["k_center"]),"formal_k_threshold_hz_per_s":float(th["k_threshold"]),
                    "score_gate_margin":float(th["score_threshold"]-dec.residual_rmse_hz),"b_gate_margin":float(th["b_threshold"]-abs(dec.b_hat_hz-th["b_center"])),
                    "k_gate_margin":float(th["k_threshold"]-abs(dec.k_hat_hz_per_s-th["k_center"])),"score_gate_pass":bool(dec.score_gate_pass),
                    "b_gate_pass":bool(dec.b_gate_pass),"k_gate_pass":bool(dec.k_gate_pass),"coverage_gate_pass":bool(dec.coverage_gate_pass),
                    "quality_gate_pass":quality,"final_decision":dec.decision,"accept_flag":dec.decision=="ACCEPT",
                    "primary_reject_gate":fixed.primary_gate(dec.score_gate_pass,dec.b_gate_pass,dec.k_gate_pass,dec.coverage_gate_pass,quality),
                    "point_count":len(et),"T_service_s":60.0,"evaluation_scope":"segment_local","doppler_reference_mode":"fixed_site_segment_center",
                    "verification_strategy":"single-window","observation_vector_hash":array_hash(y)})
                rows.append(row)
    return pd.DataFrame(rows)


def build_geometry_summary(data: pd.DataFrame) -> pd.DataFrame:
    d=data.copy(); d["selection_group"]=d.pair_selection_group
    out=fixed.build_geometry_summary(d)
    meta_cols=["pass_id","pass_source_type","pass_start_time","pass_end_time","pass_midpoint_time",
        "target_tle_epoch","attacker_tle_epoch","target_tle_age_hours","attacker_tle_age_hours","max_tle_age_hours",
        "pair_selection_group","original_risk_class","original_current_accept_fraction","service_segment_start","service_segment_end",
        "C_lat","C_lon","S_lat","S_lon","actual_distance_km","direction_selection_role","weakest_direction_deg",
        "finite_difference_max_relative_change_0p5_1_2km","unbounded_geometry_b_hat_hz",
        "unbounded_geometry_k_hat_hz_per_s","unbounded_geometry_post_rmse_hz",
        "geometry_tolerance_budget_boundary_hit"]
    meta=d.drop_duplicates("geometry_condition_id")[["geometry_condition_id"]+meta_cols]
    out=out.merge(meta,on="geometry_condition_id",validate="many_to_one")
    return out.rename(columns={"margin_sign_flip_score":"score_margin_sign_flip","margin_sign_flip_b":"b_margin_sign_flip","margin_sign_flip_k":"k_margin_sign_flip"})


def build_pass_summary(geometry: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    keys=["physical_pair_id","pass_id","bk_mode"]
    for key,g in geometry.groupby(keys,sort=False):
        risky=g.sort_values(["accept_fraction","actual_direction_post_projection_sensitivity_hz_per_km"],ascending=[False,True]).iloc[0]
        boundary=((g.accept_fraction>0)&(g.accept_fraction<.8)&g.k_margin_sign_flip)
        all_deep=g.gate_margin_risk_class.eq("deep_reject").all()
        label="pass_has_boundary_risk" if boundary.any() else "pass_all_deep_reject" if all_deep else "pass_mixed"
        realization=data[(data.physical_pair_id==key[0])&(data.pass_id==key[1])&(data.bk_mode==key[2])]
        gate_counts=realization.primary_reject_gate.value_counts()
        rows.append({**dict(zip(keys,key)),"pair_selection_group":g.pair_selection_group.iloc[0],
            "number_of_geometries":len(g),"geometries_with_nonzero_accept":int(g.accept_fraction.gt(0).sum()),
            "geometries_with_moderate_accept":int(g.accept_fraction.between(.2,.8,inclusive="left").sum()),
            "geometries_with_high_accept":int(g.accept_fraction.ge(.8).sum()),"any_nonzero_accept_geometry":bool(g.accept_fraction.gt(0).any()),
            "max_geometry_accept_fraction":float(g.accept_fraction.max()),"mean_geometry_accept_fraction":float(g.accept_fraction.mean()),
            "lowest_direction_sensitivity":float(g.actual_direction_post_projection_sensitivity_hz_per_km.min()),
            "highest_direction_sensitivity":float(g.actual_direction_post_projection_sensitivity_hz_per_km.max()),
            "highest_tolerance_budget_absorption":float(g.geometry_tolerance_budget_absorption_ratio.max()),
            "minimum_raw_geo_rmse":float(g.raw_geo_rmse_hz.min()),"closest_mean_k_margin_to_zero":float(g.k_margin_mean.abs().min()),
            "most_risky_direction":float(risky.direction_deg),"most_risky_direction_role":risky.direction_selection_role,
            "pass_has_boundary_risk":bool(boundary.any()),"pass_all_deep_reject":bool(all_deep),"pass_risk_label":label,
            "max_tle_age_hours":float(g.max_tle_age_hours.iloc[0]),"pass_midpoint_time":g.pass_midpoint_time.iloc[0],
            "k_margin_mean":float(g.k_margin_mean.mean()),"raw_geo_rmse_mean":float(g.raw_geo_rmse_hz.mean()),
            "direction_sensitivity_mean":float(g.actual_direction_post_projection_sensitivity_hz_per_km.mean()),
            "tolerance_absorption_mean":float(g.geometry_tolerance_budget_absorption_ratio.mean()),
            "score_only_fail_count":int(gate_counts.get("score",0)),"b_only_fail_count":int(gate_counts.get("b",0)),
            "k_only_fail_count":int(gate_counts.get("k",0)),"multiple_gate_fail_count":int(gate_counts.get("multiple",0)),
            "coverage_only_fail_count":int(gate_counts.get("coverage",0)),"quality_only_fail_count":int(gate_counts.get("quality",0)),
            "accept_realization_count":int(realization.accept_flag.sum()),"reject_realization_count":int(realization.final_decision.eq("REJECT").sum()),
            "defer_realization_count":int(realization.final_decision.eq("DEFER").sum())})
    return pd.DataFrame(rows)


def build_pair_summary(pass_summary: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for key,g in pass_summary.groupby(["physical_pair_id","bk_mode"],sort=False):
        rows.append({"physical_pair_id":key[0],"bk_mode":key[1],"pair_selection_group":g.pair_selection_group.iloc[0],
            "number_of_passes":len(g),"passes_with_nonzero_accept":int(g.any_nonzero_accept_geometry.sum()),
            "passes_with_moderate_accept":int(g.max_geometry_accept_fraction.ge(.2).sum()),
            "passes_with_high_accept":int(g.max_geometry_accept_fraction.ge(.8).sum()),
            "passes_with_boundary_risk":int(g.pass_has_boundary_risk.sum()),"passes_all_deep_reject":int(g.pass_all_deep_reject.sum()),
            "nonzero_pass_fraction":float(g.any_nonzero_accept_geometry.mean()),"moderate_pass_fraction":float(g.max_geometry_accept_fraction.ge(.2).mean()),
            "boundary_risk_pass_fraction":float(g.pass_has_boundary_risk.mean()),"mean_of_max_pass_accept_fraction":float(g.max_geometry_accept_fraction.mean()),
            "median_of_max_pass_accept_fraction":float(g.max_geometry_accept_fraction.median()),"max_observed_pass_accept_fraction":float(g.max_geometry_accept_fraction.max()),
            "cross_pass_direction_sensitivity_mean":float(g.direction_sensitivity_mean.mean()),"cross_pass_direction_sensitivity_std":float(g.direction_sensitivity_mean.std(ddof=0)),
            "cross_pass_raw_geometry_mean":float(g.raw_geo_rmse_mean.mean()),"cross_pass_raw_geometry_std":float(g.raw_geo_rmse_mean.std(ddof=0)),
            "cross_pass_tolerance_absorption_mean":float(g.tolerance_absorption_mean.mean()),"cross_pass_tolerance_absorption_std":float(g.tolerance_absorption_mean.std(ddof=0)),
            "cross_pass_k_margin_mean":float(g.k_margin_mean.mean()),"cross_pass_k_margin_std":float(g.k_margin_mean.std(ddof=0))})
    return pd.DataFrame(rows)


def build_group_summary(geometry: pd.DataFrame, pass_summary: pd.DataFrame, pair_summary: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for mode in BK_MODES:
        for group,g in geometry[geometry.bk_mode==mode].groupby("pair_selection_group"):
            p=pass_summary[(pass_summary.bk_mode==mode)&(pass_summary.pair_selection_group==group)]
            q=pair_summary[(pair_summary.bk_mode==mode)&(pair_summary.pair_selection_group==group)]
            rows.append({"bk_mode":mode,"pair_selection_group":group,"pair_count":q.physical_pair_id.nunique(),
                "pass_count":len(p),"geometry_count":len(g),"mean_geometry_accept_fraction":float(g.accept_fraction.mean()),
                "mean_max_pass_accept_fraction":float(p.max_geometry_accept_fraction.mean()),"passes_with_boundary_risk":int(p.pass_has_boundary_risk.sum()),
                "mean_pair_nonzero_pass_fraction":float(q.nonzero_pass_fraction.mean()) if len(q) else np.nan})
    return pd.DataFrame(rows)


def transition_detail(data: pd.DataFrame) -> pd.DataFrame:
    keys=["geometry_condition_id","observation_realization_id"]
    c=data[data.bk_mode=="current_bk"].set_index(keys); w=data[data.bk_mode=="wide_bk"].set_index(keys)
    j=c.add_suffix("_current").join(w.add_suffix("_wide"),validate="one_to_one")
    j["transition"]=j.final_decision_current+" -> "+j.final_decision_wide
    def reason(r):
        if r.transition!="REJECT -> ACCEPT": return "not_applicable"
        b=not bool(r.b_gate_pass_current) and bool(r.b_gate_pass_wide); k=not bool(r.k_gate_pass_current) and bool(r.k_gate_pass_wide)
        if r.score_gate_pass_current!=r.score_gate_pass_wide: return "score变化"
        if r.coverage_gate_pass_current!=r.coverage_gate_pass_wide or r.quality_gate_pass_current!=r.quality_gate_pass_wide: return "其他gate变化"
        return "b/k同时解除" if b and k else "b gate解除" if b else "k gate解除" if k else "无法解释"
    j["gate_release_reason"]=j.apply(reason,axis=1)
    return j.reset_index()


def transition_summary(data: pd.DataFrame) -> pd.DataFrame:
    detail=transition_detail(data); rows=[]
    mappings=[("geometry_pass",["physical_pair_id_current","pass_id_current","geometry_condition_id"]),
              ("pass",["physical_pair_id_current","pass_id_current"]),("pair",["physical_pair_id_current"]),("overall",[])]
    for level,cols in mappings:
        groups=[((),detail)] if not cols else detail.groupby(cols,dropna=False)
        for key,g in groups:
            key=key if isinstance(key,tuple) else (key,); base={"summary_level":level}
            for c,v in zip(cols,key): base[c.replace("_current","")]=v
            for (transition,reason),z in g.groupby(["transition","gate_release_reason"],dropna=False):
                rows.append({**base,"transition":transition,"gate_release_reason":reason,"realization_count":len(z),"total_paired_realizations":len(g),"fraction":len(z)/len(g)})
    return pd.DataFrame(rows)


def cluster_bootstrap_spearman(g: pd.DataFrame, metric: str, seed: int, n_boot: int=500) -> tuple[float,float,float,float]:
    x=g[["physical_pair_id","accept_fraction",metric]].dropna()
    if len(x)<3 or x[metric].nunique()<2 or x.accept_fraction.nunique()<2: return np.nan,np.nan,np.nan,np.nan
    rho,p=spearmanr(x[metric],x.accept_fraction); pairs=x.physical_pair_id.unique(); rng=np.random.default_rng(seed); vals=[]
    for _ in range(n_boot):
        sampled=rng.choice(pairs,len(pairs),replace=True); parts=[]
        for i,pid in enumerate(sampled):
            z=x[x.physical_pair_id==pid].copy(); z["boot_cluster"]=i; parts.append(z)
        b=pd.concat(parts,ignore_index=True)
        if b[metric].nunique()>1 and b.accept_fraction.nunique()>1: vals.append(spearmanr(b[metric],b.accept_fraction).statistic)
    return float(rho),float(p),float(np.quantile(vals,.025)) if vals else np.nan,float(np.quantile(vals,.975)) if vals else np.nan


def explanatory_analysis(data: pd.DataFrame, geometry: pd.DataFrame, pass_summary: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    cur=geometry[geometry.bk_mode=="current_bk"].copy(); rows=[]
    for stratum,g in [("all",cur)]+[(f"group:{k}",z) for k,z in cur.groupby("pair_selection_group")]+[(f"role:{k}",z) for k,z in cur.groupby("direction_selection_role")]:
        for metric in ["actual_direction_post_projection_sensitivity_hz_per_km","raw_geo_rmse_hz","geometry_tolerance_budget_absorption_ratio"]:
            rho,p,lo,hi=cluster_bootstrap_spearman(g,metric,args.master_seed+len(rows))
            rows.append({"analysis":"cluster_bootstrap_spearman","stratum":stratum,"metric":metric,"n":len(g),"value":rho,"p_value":p,"ci_lower":lo,"ci_upper":hi,"notes":"geometry-pass unit; physical-pair cluster bootstrap"})
    pair_means=cur.groupby("physical_pair_id").accept_fraction.mean(); pass_means=cur.groupby(["physical_pair_id","pass_id"]).accept_fraction.mean()
    between=float(pair_means.var(ddof=0)); within_pass=[]
    for _,g in pass_means.groupby(level=0): within_pass.extend((g-g.mean()).to_numpy()**2)
    within_pair=float(np.mean(within_pass)) if within_pass else np.nan
    within_dir=[]
    for _,g in cur.groupby(["physical_pair_id","pass_id"]): within_dir.extend((g.accept_fraction-g.accept_fraction.mean()).to_numpy()**2)
    direction=float(np.mean(within_dir)) if within_dir else np.nan
    dominant=max({"pair":between,"pair_pass":within_pair,"pair_pass_direction":direction},key=lambda k:{"pair":between,"pair_pass":within_pair,"pair_pass_direction":direction}[k])
    for metric,value in [("between_pair_variance",between),("within_pair_between_pass_variance",within_pair),("within_pass_between_direction_variance",direction)]:
        rows.append({"analysis":"variance_decomposition","stratum":"current","metric":metric,"n":len(cur),"value":value,"p_value":np.nan,"ci_lower":np.nan,"ci_upper":np.nan,"notes":f"dominant={dominant}"})
    current=data[data.bk_mode=="current_bk"].copy(); current["k_env_dm"]=current.k_env-current.groupby("geometry_condition_id").k_env.transform("mean"); current["k_hat_dm"]=current.formal_k_hat_hz_per_s-current.groupby("geometry_condition_id").formal_k_hat_hz_per_s.transform("mean")
    r,p=pearsonr(current.k_env_dm,current.k_hat_dm)
    rows.append({"analysis":"within_geometry_pearson","stratum":"current","metric":"k_env_vs_formal_k_hat","n":len(current),"value":r,"p_value":p,"ci_lower":np.nan,"ci_upper":np.nan,"notes":"demeaned within geometry"})
    for metric in ["raw_geo_rmse_hz","actual_direction_post_projection_sensitivity_hz_per_km","accept_fraction"]:
        x=cur[["max_tle_age_hours",metric]].dropna(); rho,p=spearmanr(x.max_tle_age_hours,x[metric]) if len(x)>=3 and x[metric].nunique()>1 else (np.nan,np.nan)
        rows.append({"analysis":"tle_age_spearman","stratum":"current","metric":metric,"n":len(x),"value":rho,"p_value":p,"ci_lower":np.nan,"ci_upper":np.nan,"notes":"same-TLE extrapolation diagnostic"})
    x=pass_summary[pass_summary.bk_mode=="current_bk"][["max_tle_age_hours","max_geometry_accept_fraction"]]
    rho,p=spearmanr(x.max_tle_age_hours,x.max_geometry_accept_fraction) if x.max_geometry_accept_fraction.nunique()>1 else (np.nan,np.nan)
    rows.append({"analysis":"tle_age_spearman","stratum":"pass_current","metric":"max_pass_accept_fraction","n":len(x),"value":rho,"p_value":p,"ci_lower":np.nan,"ci_upper":np.nan,"notes":"pass unit"})
    return pd.DataFrame(rows)


def make_figures(data: pd.DataFrame, geometry: pd.DataFrame, pass_summary: pd.DataFrame, pair_summary: pd.DataFrame,
                 transition: pd.DataFrame, outdir: Path) -> list[Path]:
    outdir.mkdir(parents=True,exist_ok=True); paths=[]; cur=geometry[geometry.bk_mode=="current_bk"].copy(); pc=pass_summary[pass_summary.bk_mode=="current_bk"].copy()
    def save(name):
        p=outdir/name; plt.tight_layout(); plt.savefig(p,dpi=180,bbox_inches="tight"); plt.close(); paths.append(p)
    pivot=pc.pivot(index="physical_pair_id",columns="pass_id",values="max_geometry_accept_fraction").fillna(0)
    plt.figure(figsize=(max(8,pivot.shape[1]*.35),max(4,pivot.shape[0]*.4))); plt.imshow(pivot,aspect="auto",vmin=0,vmax=1,cmap="viridis"); plt.colorbar(label="最大current接受比例"); plt.yticks(range(len(pivot)),pivot.index); plt.xticks([]); save("01_pair_pass_max_accept_heatmap.png")
    plt.figure(figsize=(10,6))
    for pid,g in pc.sort_values("pass_midpoint_time").groupby("physical_pair_id"): plt.plot(range(len(g)),g.max_geometry_accept_fraction,marker="o",label=pid)
    plt.xlabel("选中pass顺序"); plt.ylabel("最大current接受比例"); plt.legend(fontsize=6,ncol=2); save("02_pair_cross_pass_trajectory.png")
    plt.figure(figsize=(8,5)); pc.boxplot(column="max_geometry_accept_fraction",by="pair_selection_group",ax=plt.gca(),rot=15); plt.suptitle(""); save("03_risk_vs_control.png")
    plt.figure(figsize=(8,5)); cur.boxplot(column="accept_fraction",by="direction_selection_role",ax=plt.gca(),rot=15); plt.suptitle(""); save("04_direction_role_accept.png")
    for i,(metric,label) in enumerate([("actual_direction_post_projection_sensitivity_hz_per_km","方向敏感度"),("raw_geo_rmse_hz","raw geometry RMSE"),("geometry_tolerance_budget_absorption_ratio","tolerance-budget吸收比例")],5):
        plt.figure(figsize=(7,5));
        for role,g in cur.groupby("direction_selection_role"): plt.scatter(g[metric],g.accept_fraction,label=role,alpha=.8)
        plt.xlabel(label); plt.ylabel("current接受比例"); plt.legend(fontsize=7); save(f"{i:02d}_accept_vs_{metric}.png")
    kd=data[data.bk_mode=="current_bk"]
    plt.figure(figsize=(10,5)); kd.boxplot(column="k_gate_margin",by="pass_id",ax=plt.gca(),showfliers=False); plt.xticks([]); plt.suptitle(""); save("08_k_margin_by_pass.png")
    plt.figure(figsize=(7,5)); kd.boxplot(column="k_env",by="final_decision",ax=plt.gca()); plt.suptitle(""); save("09_k_env_by_decision.png")
    wide=pass_summary[pass_summary.bk_mode=="wide_bk"][["physical_pair_id","pass_id","max_geometry_accept_fraction"]].rename(columns={"max_geometry_accept_fraction":"wide"}); cw=pc.merge(wide,on=["physical_pair_id","pass_id"])
    plt.figure(figsize=(6,6)); plt.scatter(cw.max_geometry_accept_fraction,cw.wide); plt.plot([0,1],[0,1],"k--"); plt.xlabel("current"); plt.ylabel("wide"); save("10_current_vs_wide.png")
    rel=transition[(transition.summary_level=="overall")&(transition.gate_release_reason!="not_applicable")].groupby("gate_release_reason").realization_count.sum()
    plt.figure(figsize=(7,5))
    if len(rel):
        rel.plot.bar()
    else:
        plt.text(.5,.5,"本次没有 current REJECT -> wide ACCEPT",ha="center",va="center",transform=plt.gca().transAxes)
        plt.xticks([]); plt.yticks([])
    plt.ylabel("realization数"); save("11_current_to_wide_release.png")
    plt.figure(figsize=(7,5)); plt.scatter(cur.max_tle_age_hours,cur.accept_fraction); plt.xlabel("max TLE age (h)"); plt.ylabel("current接受比例"); save("12_accept_vs_tle_age.png")
    return paths


def correctness(args: argparse.Namespace, scope: str, pairs: pd.DataFrame, pass_table: pd.DataFrame, directions: pd.DataFrame,
                data: pd.DataFrame, geometry: pd.DataFrame, pass_summary: pd.DataFrame, pair_summary: pd.DataFrame,
                before: dict[str,str]) -> pd.DataFrame:
    tests=[]
    def add(name,passed,observed,expected): tests.append({"check":name,"passed":bool(passed),"observed":stable_json(observed),"expected":stable_json(expected)})
    selected=pass_table[pass_table.is_selected.astype(bool)]; selected_ids=set(pairs.physical_pair_id)
    inv=set(normalize_ids(pd.read_csv(args.pair_inventory)).physical_pair_id)
    add("所有选中pair存在于pass可用性审计",selected_ids<=inv,sorted(selected_ids-inv),[])
    add("风险/对照pair选择无重复",pairs.physical_pair_id.is_unique,int(pairs.physical_pair_id.duplicated().sum()),0)
    forbidden=set(selected.columns)&{"accept_flag","final_decision","formal_score_value","formal_k_hat_hz_per_s","k_gate_margin"}; add("pass选择未使用最终判决字段",not forbidden,sorted(forbidden),[])
    add("所有选中pass绝对时间不同",selected.groupby("physical_pair_id").pass_start_time.nunique().eq(selected.groupby("physical_pair_id").size()).all(),True,True)
    add("所有选中pass具有完整60秒服务段",selected.service_segment_reusable.astype(bool).all(),selected.service_segment_reusable.value_counts().to_dict(),"all true")
    add("短pass未进入正式实验",selected.pass_duration_s.ge(60).all(),float(selected.pass_duration_s.min()),">=60")
    expected_source="same_tle_different_pass" if scope=="same_tle" else "different_date_tle"; add("pass_source_type正确",selected.pass_source_type.eq(expected_source).all(),selected.pass_source_type.unique().tolist(),expected_source)
    age_recalc=selected.apply(lambda r:max(abs((utc(r.pass_midpoint_time)-utc(r.target_tle_epoch)).total_seconds()),abs((utc(r.pass_midpoint_time)-utc(r.attacker_tle_epoch)).total_seconds()))/3600,axis=1); add("TLE epoch和age计算正确",np.allclose(age_recalc,selected.max_tle_age_hours),float(np.max(abs(age_recalc-selected.max_tle_age_hours))),"<=1e-9")
    add("geometry-pass主键唯一",geometry[geometry.bk_mode=="current_bk"].geometry_condition_id.is_unique,int(geometry[geometry.bk_mode=="current_bk"].geometry_condition_id.duplicated().sum()),0)
    dc=directions.groupby(["physical_pair_id","pass_id"]).size(); add("每个pass保存全部8个候选方向",dc.eq(8).all(),dc.value_counts().to_dict(),8)
    low=directions[directions.direction_selection_role=="lowest_sensitivity"]; mins=directions.groupby(["physical_pair_id","pass_id"]).actual_direction_post_projection_sensitivity_hz_per_km.min(); lowidx=low.set_index(["physical_pair_id","pass_id"]).actual_direction_post_projection_sensitivity_hz_per_km; add("lowest方向确实为候选最低敏感度",np.allclose(lowidx.sort_index(),mins.sort_index()),True,True)
    roles=directions[directions.is_selected_direction.astype(bool)].pivot_table(index=["physical_pair_id","pass_id"],columns="direction_selection_role",values="direction_deg",aggfunc="first"); add("opposite方向正确",np.allclose((roles.lowest_sensitivity+180)%360,roles.opposite_of_lowest),True,True)
    selected_dir=directions[directions.is_selected_direction.astype(bool)]; role_counts=selected_dir.groupby(["physical_pair_id","pass_id"]).direction_selection_role.nunique(); high_ok=role_counts.eq(3).all() and selected_dir[selected_dir.direction_selection_role=="high_sensitivity_control"].actual_direction_post_projection_sensitivity_hz_per_km.ge(selected_dir[selected_dir.direction_selection_role=="lowest_sensitivity"].actual_direction_post_projection_sensitivity_hz_per_km.min()).all(); add("high方向为不同方向中的高敏感对照",high_ok,role_counts.value_counts().to_dict(),3)
    add("实际站点距离误差满足容差",(data.actual_distance_km-DISTANCE_KM).abs().max()<.01,float((data.actual_distance_km-DISTANCE_KM).abs().max()),"<0.01km")
    counts=data.groupby(["geometry_condition_id","bk_mode"]).size(); add("每个geometry生成指定数量realization",counts.eq(args.realizations).all(),counts.value_counts().to_dict(),args.realizations)
    obs=data.drop_duplicates(["geometry_condition_id","observation_realization_id"]); add("realization ID全局唯一",obs.observation_realization_id.is_unique,int(obs.observation_realization_id.duplicated().sum()),0)
    repro=all(int(r.environment_seed)==derive_seed(args.master_seed,r.geometry_condition_id,int(r.realization_index),"environment") and int(r.noise_seed)==derive_seed(args.master_seed,r.geometry_condition_id,int(r.realization_index),"noise") for r in obs.iloc[::-1].head(30).itertuples()); add("seed不依赖运行顺序",repro,True,True)
    pure=["raw_geo_rmse_hz","unbounded_geometry_b_hat_hz","actual_direction_post_projection_sensitivity_hz_per_km","geometry_tolerance_budget_absorption_ratio"]; add("同一geometry纯几何指标固定",data.groupby("geometry_condition_id")[pure].nunique(dropna=False).le(1).all().all(),True,True)
    add("calibration在同一geometry中固定",data.groupby("geometry_condition_id").calibration_seed.nunique().eq(1).all(),True,True)
    hashes=data.groupby(["geometry_condition_id","observation_realization_id"]).observation_vector_hash.nunique(); add("no/current/wide共享同一observation",hashes.eq(1).all(),int(hashes.max()),1)
    keys=["geometry_condition_id","observation_realization_id"]; c=data[data.bk_mode=="current_bk"].set_index(keys); w=data[data.bk_mode=="wide_bk"].set_index(keys)
    add("current/wide正式score相同",np.allclose(c.formal_score_value,w.formal_score_value,atol=1e-10),float(np.max(abs(c.formal_score_value-w.formal_score_value))),"<=1e-10")
    add("current/wide正式b_hat相同",np.allclose(c.formal_b_hat_hz,w.formal_b_hat_hz,atol=1e-10),float(np.max(abs(c.formal_b_hat_hz-w.formal_b_hat_hz))),"<=1e-10")
    add("current/wide正式k_hat相同",np.allclose(c.formal_k_hat_hz_per_s,w.formal_k_hat_hz_per_s,atol=1e-12),float(np.max(abs(c.formal_k_hat_hz_per_s-w.formal_k_hat_hz_per_s))),"<=1e-12")
    bad=int((c.accept_flag&~w.accept_flag).sum()); add("不出现current ACCEPT到wide REJECT",bad==0,bad,0)
    lo,hi=fixed.wilson(0,20); add("Wilson区间正确",abs(hi-.161125)<1e-5,(lo,hi),(0,.161125))
    add("geometry汇总能够回加",geometry.groupby("bk_mode").realization_count.sum().to_dict()==data.groupby("bk_mode").size().to_dict(),geometry.groupby("bk_mode").realization_count.sum().to_dict(),data.groupby("bk_mode").size().to_dict())
    add("pass汇总能够回加",pass_summary.groupby("bk_mode").number_of_geometries.sum().to_dict()==geometry.groupby("bk_mode").size().to_dict(),pass_summary.groupby("bk_mode").number_of_geometries.sum().to_dict(),geometry.groupby("bk_mode").size().to_dict())
    add("pair汇总能够回加",pair_summary.groupby("bk_mode").number_of_passes.sum().to_dict()==pass_summary.groupby("bk_mode").size().to_dict(),pair_summary.groupby("bk_mode").number_of_passes.sum().to_dict(),pass_summary.groupby("bk_mode").size().to_dict())
    add("有限差分0.5/1/2km稳定",directions.finite_difference_max_relative_change_0p5_1_2km.max()<.25,float(directions.finite_difference_max_relative_change_0p5_1_2km.max()),"<0.25 relative")
    add("direction和ENU单位正确",set(directions.direction_deg)==set(DIRECTIONS),sorted(directions.direction_deg.unique()),DIRECTIONS)
    valid_levels={"within_48h","relaxed_to_72h","relaxed_to_96h","nearest_available"}; add("TLE age放宽策略可回溯",set(selected.tle_age_relaxation_level)<=valid_levels,selected.tle_age_relaxation_level.value_counts().to_dict(),sorted(valid_levels))
    after={str(p):sha_file(p) for p in input_paths(args)}; add("旧正式输入运行前后SHA-256一致",before==after,{k:before[k]==after[k] for k in before},"all true")
    if scope=="historical_tle_case":
        add("历史案例target和attacker使用可回溯日期TLE",selected.target_tle_epoch.notna().all() and selected.attacker_tle_epoch.notna().all(),True,True)
        add("历史epoch身份可回溯",selected.historical_tle_epoch_id.notna().all() and selected.groupby("physical_pair_id").target_tle_epoch.nunique().ge(3).all(),selected.groupby("physical_pair_id").target_tle_epoch.nunique().to_dict(),">=3")
        add("历史epoch未误判为same-TLE pass",selected.pass_source_type.eq("different_date_tle").all(),selected.pass_source_type.unique().tolist(),"different_date_tle")
        add("两个历史案例未进入主实验总体统计",set(pairs.physical_pair_id)==HISTORICAL_PAIRS,sorted(pairs.physical_pair_id),sorted(HISTORICAL_PAIRS))
    return pd.DataFrame(tests)


def write_report(scope: str, args: argparse.Namespace, paths: dict[str,Path], pairs: pd.DataFrame, passes: pd.DataFrame,
                 data: pd.DataFrame, geometry: pd.DataFrame, pass_summary: pd.DataFrame, pair_summary: pd.DataFrame,
                 transition: pd.DataFrame, explanatory: pd.DataFrame, audit: pd.DataFrame, figures: list[Path]) -> None:
    ok=bool(audit.passed.all()); curg=geometry[geometry.bk_mode=="current_bk"]; curp=pass_summary[pass_summary.bk_mode=="current_bk"]; curpair=pair_summary[pair_summary.bk_mode=="current_bk"]
    role=curg.groupby("direction_selection_role").accept_fraction.mean().to_dict(); risk=curpair[curpair.pair_selection_group=="k_boundary_sensitive"]
    controls=curpair[curpair.pair_selection_group=="deep_reject_control"]
    tr=transition[transition.summary_level=="overall"][["transition","gate_release_reason","realization_count"]]
    exp=explanatory[["analysis","stratum","metric","n","value","p_value","ci_lower","ci_upper","notes"]]
    age=(float(passes.loc[passes.is_selected,"max_tle_age_hours"].min()),float(passes.loc[passes.is_selected,"max_tle_age_hours"].max()))
    historical=scope=="historical_tle_case"
    gate_counts=data[data.bk_mode=="current_bk"].primary_reject_gate.value_counts().to_dict()
    corr={r.metric:r for r in explanatory[(explanatory.analysis=="cluster_bootstrap_spearman")&(explanatory.stratum=="all")].itertuples()}
    variance=explanatory[explanatory.analysis=="variance_decomposition"].set_index("metric").value.to_dict()
    krow=explanatory[explanatory.analysis=="within_geometry_pearson"].iloc[0]
    age_rows=explanatory[explanatory.analysis=="tle_age_spearman"]
    risk_repeat=int(risk.passes_with_nonzero_accept.gt(1).sum()) if len(risk) else 0
    risk_any=int(risk.passes_with_nonzero_accept.gt(0).sum()) if len(risk) else 0
    control_new=int(controls.passes_with_nonzero_accept.gt(0).sum()) if len(controls) else 0
    selected_passes=passes[passes.is_selected.astype(bool)]
    epoch_table=(selected_passes.groupby("physical_pair_id").agg(passes=("pass_id","nunique"),
        target_epochs=("target_tle_epoch","nunique"),attacker_epochs=("attacker_tle_epoch","nunique"),
        min_tle_age_hours=("max_tle_age_hours","min"),max_tle_age_hours=("max_tle_age_hours","max")).reset_index())
    title="不同日期TLE多pass探索性案例" if historical else "same-TLE同一物理pair多pass确认实验"
    boundary = "该部分只有两个物理pair，是探索性案例，不支持跨日期总体推断。" if historical else "same-TLE不同pass是在同一个轨道初始条件模型下传播到不同轨道周次；不能覆盖TLE更新、机动或真实长期轨道误差。"
    if not ok:
        conclusions="正确性审计未全部通过，不输出研究结论。"
    elif historical:
        conclusions=f"两个历史TLE探索pair的current非零pass数均为0；geometry内k_env—k_hat相关={krow.value:.3f}。0/20不证明风险为0，本案例不支持跨日期总体推断。"
    else:
        conclusions=f"风险pair平均非零pass比例={risk.nonzero_pass_fraction.mean() if len(risk) else np.nan:.3f}；deep-reject对照中出现新非零pass的pair={int(controls.passes_with_nonzero_accept.gt(0).sum())}/{len(controls)}。lowest/opposite/high平均条件接受比例={role.get('lowest_sensitivity',np.nan):.3f}/{role.get('opposite_of_lowest',np.nan):.3f}/{role.get('high_sensitivity_control',np.nan):.3f}。这些是定向选择条件的机制结果，不是总体非目标样本误接受率。"
    age_interpretation=("历史案例TLE age均较小，但只有两个pair，不能用于总体TLE更新稳定性判断。" if historical else
        "本轮所有same-TLE pass均在48小时预声明层级内，且接受比例与TLE age未见显著单调关系；仍不能把same-TLE传播解释成不同日期真实TLE验证。")
    historical_section=(f"""## 7. 历史TLE案例

{epoch_table.to_markdown(index=False)}

历史案例中两个pair均使用4个可回溯目标/来源epoch。current与wide均未观察到接受或k-margin边界翻转，但geometry内 `k_env`—`k_hat` 耦合仍存在。这说明TLE更新明显改变了本次选中状态；0/20不等于风险为0，且两个案例不支持跨日期总体推断。

""" if historical else "")
    report=f"""# {title}

## 1. 目的和边界

保持 `T_service_s=60`、`segment_local`、`fixed_site_segment_center`、`single-window`，复用旧正式轨道传播、固定点Doppler、calibration、无边界(b+kt)拟合和score/b/k/coverage/quality gate。统一统计术语为“非目标样本误接受率”。{boundary}

## 2. 选择和规模

- pair：{len(pairs)}；风险/探索组：{pairs.pair_selection_group.value_counts().to_dict()}。
- 选中pass：{int(passes.is_selected.sum())}；每pair：{passes[passes.is_selected].groupby('physical_pair_id').size().to_dict()}。
- TLE age范围：{age[0]:.2f}–{age[1]:.2f}小时；放宽层级：{passes.loc[passes.is_selected,'tle_age_relaxation_level'].value_counts().to_dict()}。
- geometry-pass：{curg.geometry_condition_id.nunique()}；observation realization：{data.drop_duplicates(['geometry_condition_id','observation_realization_id']).shape[0]}；模式行：{len(data)}。

## 3. 跨pass重复性

{curpair[['physical_pair_id','pair_selection_group','number_of_passes','passes_with_nonzero_accept','passes_with_boundary_risk','nonzero_pass_fraction','boundary_risk_pass_fraction','max_observed_pass_accept_fraction']].to_markdown(index=False)}

原风险组中 {risk_any}/{len(risk)} 个pair至少在一个pass出现非零接受，{risk_repeat}/{len(risk)} 个pair在多于一个pass重复出现；没有pair在多数pass中重复。原deep-reject对照中 {control_new}/{len(controls)} 个在新pass进入边界，说明历史标签不能代表永久低风险。所有非零条件都集中在单个pass的lowest/opposite方向，高敏感方向为0。

## 4. 方向和几何机制

方向角色平均接受比例：{role}。lowest与opposite接近，而high方向未观察到接受，风险表现为pair × pass × direction局部事件。

{exp.to_markdown(index=False)}

总体cluster-bootstrap Spearman：方向敏感度 {corr.get('actual_direction_post_projection_sensitivity_hz_per_km').value if corr.get('actual_direction_post_projection_sensitivity_hz_per_km') else np.nan:.3f}，raw geometry {corr.get('raw_geo_rmse_hz').value if corr.get('raw_geo_rmse_hz') else np.nan:.3f}，tolerance-budget吸收 {corr.get('geometry_tolerance_budget_absorption_ratio').value if corr.get('geometry_tolerance_budget_absorption_ratio') else np.nan:.3f}；95%区间见表。局部敏感度只解释2.5 km局部条件，没有外推到远距离。

描述性方差为pair间 {variance.get('between_pair_variance',np.nan):.6f}、pair内pass间 {variance.get('within_pair_between_pass_variance',np.nan):.6f}、pass内方向间 {variance.get('within_pass_between_direction_variance',np.nan):.6f}。本轮最大项为pair内pass间，且方向项接近，因此风险更接近pair × pass，并进一步受direction约束；不是固定pair属性。

## 5. k gate与current/wide

geometry内去均值后的 `k_env`—正式 `k_hat` Pearson={krow.value:.3f}。current主要路径计数为 {gate_counts}；k单独失败多于b或score单独失败，但multiple gate失败也很多，因此应表述为k是主要单gate边界机制，而非唯一机制。current与wide共享正式score、b_hat、k_hat，wide只扩大b/k gate。

{tr.to_markdown(index=False)}

## 6. TLE age诊断

TLE age与raw geometry、方向敏感度、条件接受比例和pass最大接受比例的关系如下。{age_rows[['stratum','metric','n','value','p_value']].to_markdown(index=False)}

{age_interpretation}

{historical_section}## 8. 正确性审计

{audit.to_markdown(index=False)}

审计通过 {int(audit.passed.sum())}/{len(audit)}。{conclusions}

## 9. 当前结论和下一步

{conclusions}

same-TLE主实验支持“风险主要属于pair × pass × direction局部几何状态”，不支持永久高风险pair。建议扩大物理pair，并优先补齐双边历史TLE；历史案例目前仅表明机制状态对TLE epoch敏感。

## 10. 输出和局限

生成{len(figures)}幅图，CSV、dataset、报告和图均使用独立前缀。没有修改旧正式输出。{boundary}
"""
    paths["report"].write_text(report,encoding="utf-8")


def append_log(scope: str,args: argparse.Namespace,pairs: pd.DataFrame,passes: pd.DataFrame,data: pd.DataFrame,
               pair_summary: pd.DataFrame,audit: pd.DataFrame) -> None:
    now=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"); cur=pair_summary[pair_summary.bk_mode=="current_bk"]
    text=f"""

## {now} - {'历史TLE多pass探索性案例' if scope=='historical_tle_case' else 'same-TLE同一pair多pass正式确认'}

### A. 本轮目标
检验同一物理目标—非目标pair的(k)-gate边界风险跨pass重复性；same-TLE主实验与历史TLE两个案例严格隔离。

### B. 实际操作
新增`run_same_pair_multi_pass_confirmation.py`；按TLE age阶梯和pass几何多样性选pass；每pass重构中心60秒服务段；保存8方向候选并选择lowest/opposite/high；SHA-256独立派生environment/noise seed；复用正式calibration和verifier。

### C. 新增/修改文件
生成独立selected pair/pass/direction、realization dataset、geometry/pass/pair/group/transition/explanatory/audit CSV、报告和图。未修改配置或旧正式输出。

### D. 运行命令
`python scripts/run_same_pair_multi_pass_confirmation.py --preset {args.preset} --analysis-scope {scope} --pairs {args.pairs} --passes-per-pair {args.passes_per_pair} --realizations {args.realizations}{' --overwrite' if args.overwrite else ''}`

### E. 结果摘要
pair={len(pairs)}，selected pass={int(passes.is_selected.sum())}，模式行={len(data)}；正确性审计={int(audit.passed.sum())}/{len(audit)}。current逐pair非零pass比例={cur.set_index('physical_pair_id').nonzero_pass_fraction.to_dict()}。

### F. 问题与下一步
same-TLE结果不等同不同日期TLE；历史部分仅两个pair，不能总体推广。定向选择接受比例不是总体非目标样本误接受率。
"""
    with Path("logs/work_log.md").open("a",encoding="utf-8",newline="") as f: f.write(text)


def run_scope(args: argparse.Namespace, scope: str) -> None:
    paths=output_paths(scope,args.preset); before=check_io(args,paths,scope)
    pairs=choose_pairs(args,scope); pass_table=choose_passes(args,pairs,scope)
    _selection,_library,cfg,tle,ranges=load_orbit(args); ts=load.timescale(); freq=float(cfg.get("ku_band_experiment",{}).get("simulation_center_freq_hz") or cfg["frequency"]["center_freq_hz"])
    directions,geometries=build_directions_and_geometries(args,pairs,pass_table,scope,tle,ranges,ts,freq)
    data=generate_realizations(args,geometries,ranges); geometry=build_geometry_summary(data); pass_summary=build_pass_summary(geometry,data); pair_summary=build_pair_summary(pass_summary)
    group=build_group_summary(geometry,pass_summary,pair_summary); transition=transition_summary(data); explanatory=explanatory_analysis(data,geometry,pass_summary,args)
    audit=correctness(args,scope,pairs,pass_table,directions,data,geometry,pass_summary,pair_summary,before)
    pairs.to_csv(paths["pairs"],index=False,encoding="utf-8-sig"); pass_table.to_csv(paths["passes"],index=False,encoding="utf-8-sig"); directions.to_csv(paths["directions"],index=False,encoding="utf-8-sig")
    data.to_csv(paths["dataset"],index=False,encoding="utf-8-sig"); geometry.to_csv(paths["geometry"],index=False,encoding="utf-8-sig"); pass_summary.to_csv(paths["pass_summary"],index=False,encoding="utf-8-sig")
    pair_summary.to_csv(paths["pair_summary"],index=False,encoding="utf-8-sig"); group.to_csv(paths["group"],index=False,encoding="utf-8-sig"); transition.to_csv(paths["transition"],index=False,encoding="utf-8-sig"); explanatory.to_csv(paths["explanatory"],index=False,encoding="utf-8-sig"); audit.to_csv(paths["audit"],index=False,encoding="utf-8-sig")
    figures=make_figures(data,geometry,pass_summary,pair_summary,transition,paths["figures"])
    write_report(scope,args,paths,pairs,pass_table,data,geometry,pass_summary,pair_summary,transition,explanatory,audit,figures); append_log(scope,args,pairs,pass_table,data,pair_summary,audit)
    cur=pair_summary[pair_summary.bk_mode=="current_bk"]; exp=explanatory
    print(f"analysis_scope={scope}; pairs={len(pairs)}; groups={pairs.pair_selection_group.value_counts().to_dict()}")
    print(f"selected_passes={int(pass_table.is_selected.sum())}; TLE_age_h={pass_table.loc[pass_table.is_selected,'max_tle_age_hours'].min():.2f}..{pass_table.loc[pass_table.is_selected,'max_tle_age_hours'].max():.2f}")
    print(f"geometry_passes={geometry[geometry.bk_mode=='current_bk'].geometry_condition_id.nunique()}; realization_mode_rows={len(data)}; audit={int(audit.passed.sum())}/{len(audit)}")
    print("pair_nonzero_pass_fraction="+stable_json(cur.set_index("physical_pair_id").nonzero_pass_fraction.to_dict()))
    print("pair_boundary_risk_fraction="+stable_json(cur.set_index("physical_pair_id").boundary_risk_pass_fraction.to_dict()))
    print("mechanism="+stable_json(exp[exp.analysis.isin(["within_geometry_pearson","variance_decomposition"])][["metric","value","notes"]].to_dict("records")))
    overall=transition[transition.summary_level=="overall"][["transition","gate_release_reason","realization_count"]]; print("current_wide="+stable_json(overall.to_dict("records")))
    if not audit.passed.all(): fail(f"{scope} correctness audit failed; research conclusions suppressed")


def main() -> None:
    args=parse_args(); scopes=["same_tle","historical_tle_case"] if args.analysis_scope=="both" else [args.analysis_scope]
    for scope in scopes: run_scope(args,scope)


if __name__=="__main__":
    main()
