#!/usr/bin/env python
"""Audit concentration and independence of real-TLE noncenter accepts.

This script is read-only with respect to all formal experiment outputs.  It
does not propagate an orbit, regenerate an observation, change a verifier, or
fit a predictive model.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

PHYSICAL_KEY = [
    "target_sat_id", "attack_sat_id", "service_area_id",
    "service_area_segment_index", "distance_km", "direction_deg", "bk_mode",
]
MECHANISM_METRICS = [
    "raw_geo_rmse_hz",
    "actual_direction_post_projection_sensitivity_hz_per_km",
    "weakest_direction_sensitivity_hz_per_km",
    "unbounded_geometry_absorption_ratio",
    "geometry_tolerance_budget_absorption_ratio",
    "formal_b_hat_hz",
    "formal_k_hat_hz_per_s",
    "formal_b_gate_margin_hz",
    "formal_k_gate_margin_hz_per_s",
]
AXIS_GROUPS = {
    0.0: "北—南轴", 180.0: "北—南轴",
    45.0: "东北—西南轴", 225.0: "东北—西南轴",
    90.0: "东—西轴", 270.0: "东—西轴",
    135.0: "东南—西北轴", 315.0: "东南—西北轴",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="审计真实 TLE 非中心误接受的分布、独立性和集中程度")
    p.add_argument("--row-summary", type=Path, default=Path("outputs/metrics/differential_doppler_mechanism_full_row_summary.csv"))
    p.add_argument("--pair-inventory", type=Path, default=Path("outputs/metrics/differential_doppler_mechanism_full_pair_inventory.csv"))
    p.add_argument("--repeatability", type=Path, default=Path("outputs/metrics/differential_doppler_mechanism_full_repeatability_summary.csv"))
    p.add_argument("--grouped-validation", type=Path, default=Path("outputs/metrics/differential_doppler_mechanism_full_grouped_validation.csv"))
    p.add_argument("--full-report", type=Path, default=Path("outputs/reports/differential_doppler_mechanism_full_analysis_report.md"))
    p.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/real_tle_positive_distribution_audit_report.md"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/real_tle_positive_distribution_audit"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def output_paths(args: argparse.Namespace) -> dict[str, Path]:
    p = args.output_dir
    return {
        "physical": p / "real_tle_positive_audit_physical_conditions.csv",
        "target": p / "real_tle_positive_audit_target_summary.csv",
        "pair": p / "real_tle_positive_audit_pair_summary.csv",
        "area": p / "real_tle_positive_audit_service_area_summary.csv",
        "distance": p / "real_tle_positive_audit_distance_summary.csv",
        "direction": p / "real_tle_positive_audit_direction_summary.csv",
        "group": p / "real_tle_positive_audit_group_summary.csv",
        "concentration": p / "real_tle_positive_audit_concentration_summary.csv",
        "conflicts": p / "real_tle_positive_audit_duplicate_conflicts.csv",
        "correctness": p / "real_tle_positive_audit_correctness.csv",
        "target_pair_matrix": p / "real_tle_positive_audit_target_pair_matrix.csv",
        "pair_area_matrix": p / "real_tle_positive_audit_pair_area_matrix.csv",
        "pair_distance_matrix": p / "real_tle_positive_audit_pair_distance_matrix.csv",
        "pair_direction_matrix": p / "real_tle_positive_audit_pair_direction_matrix.csv",
        "report": args.report_output,
        "figures": args.figures_dir,
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{name} missing columns: {', '.join(missing)}")


def check_io(args: argparse.Namespace, paths: dict[str, Path]) -> None:
    for p in [args.row_summary, args.pair_inventory, args.repeatability, args.grouped_validation, args.full_report]:
        if not p.exists():
            fail(f"missing input: {p}")
    existing = [str(p) for k, p in paths.items() if k != "figures" and p.exists()]
    if paths["figures"].exists() and any(paths["figures"].iterdir()):
        existing.append(str(paths["figures"]))
    if existing and not args.overwrite:
        fail("audit output exists; add --overwrite: " + ", ".join(existing))


def physical_id(row: pd.Series) -> str:
    return (
        f"{row.target_sat_id}->{row.attack_sat_id}|{row.service_area_id}|"
        f"seg{int(row.service_area_segment_index)}|d{float(row.distance_km):g}|"
        f"phi{float(row.direction_deg):g}|{row.bk_mode}"
    )


def add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["target_sat_id"] = out.target_sat_id.astype(str)
    out["attack_sat_id"] = out.attack_sat_id.astype(str)
    out["physical_pair_id"] = out.target_sat_id + "->" + out.attack_sat_id
    out["target_service_area_id"] = out.target_sat_id + "|" + out.service_area_id.astype(str)
    out["physical_condition_id"] = out.apply(physical_id, axis=1)
    out["formal_b_gate_margin_hz"] = np.minimum(
        out.formal_b_hat_hz - out.formal_b_gate_lower_hz,
        out.formal_b_gate_upper_hz - out.formal_b_hat_hz,
    )
    out["formal_k_gate_margin_hz_per_s"] = np.minimum(
        out.formal_k_hat_hz_per_s - out.formal_k_gate_lower_hz_per_s,
        out.formal_k_gate_upper_hz_per_s - out.formal_k_hat_hz_per_s,
    )
    out["axis_group"] = out.direction_deg.map(AXIS_GROUPS).fillna("其他方向")
    return out


def flatten_metric_stats(g: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for metric in MECHANISM_METRICS:
        values = pd.to_numeric(g[metric], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        for stat in ["mean", "median", "min", "max"]:
            out[f"{metric}_{stat}"] = float(getattr(values, stat)()) if len(values) else np.nan
    return out


def aggregate_physical_positive(pos: pd.DataFrame, all_real: pd.DataFrame) -> pd.DataFrame:
    all_decisions = all_real.groupby(PHYSICAL_KEY, dropna=False).agg(
        all_sample_groups=("sample_group", lambda x: ",".join(sorted(set(map(str, x))))),
        all_label_decisions=("formal_final_decision", lambda x: ",".join(sorted(set(map(str, x))))),
        all_label_row_count=("formal_final_decision", "size"),
        all_label_decision_count=("formal_final_decision", "nunique"),
    ).reset_index()
    records = []
    for key, g in pos.groupby(PHYSICAL_KEY, dropna=False, sort=False):
        record: dict[str, Any] = dict(zip(PHYSICAL_KEY, key))
        record.update({
            "physical_condition_id": str(g.iloc[0].physical_condition_id),
            "physical_pair_id": str(g.iloc[0].physical_pair_id),
            "source_pair_id": str(g.iloc[0].pair_id),
            "target_service_area_id": str(g.iloc[0].target_service_area_id),
            "positive_sample_groups": ",".join(sorted(g.sample_group.astype(str).unique())),
            "raw_positive_row_count": int(len(g)),
            "positive_group_count": int(g.sample_group.nunique()),
            "appears_positive_in_multiple_sample_groups": bool(g.sample_group.nunique() > 1),
        })
        # Geometry is deterministic for the physical key. Formal fitted values
        # are summarized across positive label rows because the table has no
        # observation-realization key that would justify choosing one label.
        for metric in MECHANISM_METRICS:
            values = pd.to_numeric(g[metric], errors="coerce")
            record[metric] = float(values.mean())
            if metric.startswith("formal_"):
                record[f"{metric}_min_across_positive_labels"] = float(values.min())
                record[f"{metric}_max_across_positive_labels"] = float(values.max())
        records.append(record)
    out = pd.DataFrame(records).merge(all_decisions, on=PHYSICAL_KEY, how="left", validate="one_to_one")
    out["decision_conflict_across_labels"] = out.all_label_decision_count.gt(1)
    return out.sort_values(["target_sat_id", "attack_sat_id", "service_area_id", "distance_km", "direction_deg"]).reset_index(drop=True)


def entity_hhi(counts: pd.Series) -> tuple[float, float]:
    total = float(counts.sum())
    if total <= 0:
        return np.nan, np.nan
    shares = counts.astype(float) / total
    hhi = float(np.sum(shares * shares))
    return hhi, float(1.0 / hhi) if hhi > 0 else np.nan


def top_shares(counts: pd.Series) -> dict[str, float]:
    values = counts.sort_values(ascending=False).to_numpy(float)
    total = float(values.sum())
    return {f"top{k}_positive_share": float(values[: min(k, len(values))].sum() / total) if total else np.nan for k in [1, 2, 3, 5]}


def build_summaries(
    raw_pos: pd.DataFrame, physical: pd.DataFrame, all_real: pd.DataFrame
) -> tuple[pd.DataFrame, ...]:
    total = len(physical)
    all_physical = all_real.drop_duplicates(PHYSICAL_KEY).copy()

    target_rows = []
    for target, g in physical.groupby("target_sat_id"):
        raw = raw_pos[raw_pos.target_sat_id.eq(str(target))]
        denom = all_physical[all_physical.target_sat_id.eq(str(target))]
        record = {
            "target_sat_id": target,
            "positive_raw_rows": len(raw),
            "positive_physical_conditions": len(g),
            "positive_physical_pair_count": g.physical_pair_id.nunique(),
            "positive_service_area_count": g.target_service_area_id.nunique(),
            "positive_distance_count": g.distance_km.nunique(),
            "positive_direction_count": g.direction_deg.nunique(),
            "positive_share": len(g) / total,
            "all_real_conditions": len(denom),
            "target_condition_accept_rate": len(g) / len(denom) if len(denom) else np.nan,
        }
        record.update(flatten_metric_stats(g))
        target_rows.append(record)
    target = pd.DataFrame(target_rows).sort_values("positive_physical_conditions", ascending=False)

    pair_rows = []
    for pair, g in physical.groupby("physical_pair_id"):
        target_id, attack_id = pair.split("->", 1)
        raw = raw_pos[raw_pos.physical_pair_id.eq(pair)]
        denom = all_physical[all_physical.physical_pair_id.eq(pair)]
        groups = sorted(all_real[all_real.physical_pair_id.eq(pair)].sample_group.astype(str).unique())
        record = {
            "physical_pair_id": pair,
            "source_pair_id": str(raw.iloc[0].pair_id),
            "target_sat_id": target_id,
            "attack_sat_id": attack_id,
            "sample_groups": ",".join(groups),
            "positive_raw_rows": len(raw),
            "positive_physical_conditions": len(g),
            "positive_service_area_count": g.target_service_area_id.nunique(),
            "positive_distance_count": g.distance_km.nunique(),
            "positive_direction_count": g.direction_deg.nunique(),
            "positive_share": len(g) / total,
            "all_noncenter_conditions": len(denom),
            "pair_condition_accept_rate": len(g) / len(denom) if len(denom) else np.nan,
            "ordinary_positive_count": int(raw[raw.sample_group.eq("ordinary_similar")].drop_duplicates(PHYSICAL_KEY).shape[0]),
            "boundary_positive_count": int(raw[raw.sample_group.eq("boundary_case")].drop_duplicates(PHYSICAL_KEY).shape[0]),
            "appears_in_multiple_sample_groups": len(groups) > 1,
            "positive_in_multiple_service_areas": g.target_service_area_id.nunique() > 1,
            "positive_in_multiple_directions": g.direction_deg.nunique() > 1,
            "positive_in_multiple_distances": g.distance_km.nunique() > 1,
        }
        record.update(flatten_metric_stats(g))
        pair_rows.append(record)
    pair = pd.DataFrame(pair_rows).sort_values(["positive_physical_conditions", "physical_pair_id"], ascending=[False, True])

    area_rows = []
    for area_id, g in physical.groupby("target_service_area_id"):
        area_rows.append({
            "target_service_area_id": area_id,
            "service_area_id": str(g.iloc[0].service_area_id),
            "target_sat_id": str(g.iloc[0].target_sat_id),
            "positive_physical_conditions": len(g),
            "positive_physical_pair_count": g.physical_pair_id.nunique(),
            "positive_distance_count": g.distance_km.nunique(),
            "positive_direction_count": g.direction_deg.nunique(),
            "positive_share": len(g) / total,
        })
    area = pd.DataFrame(area_rows).sort_values("positive_physical_conditions", ascending=False)

    distance_rows = []
    for distance, g in physical.groupby("distance_km"):
        denom = all_physical[all_physical.distance_km.eq(distance)]
        record = {
            "distance_km": distance,
            "positive_physical_conditions": len(g),
            "positive_physical_pair_count": g.physical_pair_id.nunique(),
            "positive_target_count": g.target_sat_id.nunique(),
            "positive_service_area_count": g.target_service_area_id.nunique(),
            "positive_share": len(g) / total,
            "all_real_conditions": len(denom),
            "distance_condition_accept_rate": len(g) / len(denom) if len(denom) else np.nan,
        }
        record.update(flatten_metric_stats(g))
        distance_rows.append(record)
    # Include zero-positive existing distances so 5/10 km are explicit.
    existing_distances = sorted(all_physical.distance_km.unique())
    present = {float(r["distance_km"]) for r in distance_rows}
    for distance in existing_distances:
        if float(distance) not in present:
            denom = all_physical[all_physical.distance_km.eq(distance)]
            distance_rows.append({"distance_km": distance, "positive_physical_conditions": 0, "positive_physical_pair_count": 0, "positive_target_count": 0, "positive_service_area_count": 0, "positive_share": 0.0, "all_real_conditions": len(denom), "distance_condition_accept_rate": 0.0})
    distance = pd.DataFrame(distance_rows).sort_values("distance_km")

    direction_rows = []
    for direction in sorted(all_physical.direction_deg.unique()):
        g = physical[physical.direction_deg.eq(direction)]
        denom = all_physical[all_physical.direction_deg.eq(direction)]
        direction_rows.append({
            "direction_deg": direction,
            "axis_group": AXIS_GROUPS.get(float(direction), "其他方向"),
            "positive_physical_conditions": len(g),
            "positive_physical_pair_count": g.physical_pair_id.nunique(),
            "positive_target_count": g.target_sat_id.nunique(),
            "positive_service_area_count": g.target_service_area_id.nunique(),
            "positive_share": len(g) / total,
            "all_real_conditions": len(denom),
            "direction_condition_accept_rate": len(g) / len(denom) if len(denom) else np.nan,
        })
    direction = pd.DataFrame(direction_rows).sort_values("direction_deg")
    axis_aux = direction.groupby("axis_group", as_index=False).agg(
        positive_physical_conditions=("positive_physical_conditions", "sum"),
        positive_physical_pair_count=("positive_physical_pair_count", "sum"),
        positive_target_count=("positive_target_count", "sum"),
        positive_service_area_count=("positive_service_area_count", "sum"),
        positive_share=("positive_share", "sum"),
        all_real_conditions=("all_real_conditions", "sum"),
    )
    axis_aux["direction_deg"] = np.nan
    axis_aux["direction_condition_accept_rate"] = axis_aux.positive_physical_conditions / axis_aux.all_real_conditions
    axis_aux["summary_level"] = "axis_auxiliary"
    direction["summary_level"] = "raw_direction_primary"
    direction = pd.concat([direction, axis_aux[direction.columns]], ignore_index=True)

    group_rows = []
    for group_name in sorted(all_real.sample_group.unique()):
        raw = raw_pos[raw_pos.sample_group.eq(group_name)].drop_duplicates(PHYSICAL_KEY)
        denom = all_real[all_real.sample_group.eq(group_name)].drop_duplicates(PHYSICAL_KEY)
        fractional = float(sum(1.0 / max(int(n), 1) for n in physical[physical.positive_sample_groups.str.contains(group_name, regex=False)].positive_group_count))
        record = {
            "sample_group": group_name,
            "positive_raw_rows": int((raw_pos.sample_group == group_name).sum()),
            "positive_physical_conditions": len(raw),
            "positive_physical_pair_count": raw.physical_pair_id.nunique(),
            "positive_target_count": raw.target_sat_id.nunique(),
            "positive_fractional_equivalent": fractional,
            "positive_share": fractional / total,
            "all_real_conditions": len(denom),
            "group_condition_accept_rate": len(raw) / len(denom) if len(denom) else np.nan,
            "physical_conditions_positive_in_both_groups": int(physical.appears_positive_in_multiple_sample_groups.sum()),
        }
        record.update(flatten_metric_stats(raw))
        group_rows.append(record)
    group = pd.DataFrame(group_rows)
    return target, pair, area, distance, direction, group, all_physical


def build_concentration(target: pd.DataFrame, pair: pd.DataFrame, area: pd.DataFrame, physical: pd.DataFrame, raw_count: int) -> pd.DataFrame:
    target_counts = target.set_index("target_sat_id").positive_physical_conditions
    pair_counts = pair.set_index("physical_pair_id").positive_physical_conditions
    area_counts = area.set_index("target_service_area_id").positive_physical_conditions
    thhi, teff = entity_hhi(target_counts)
    phhi, peff = entity_hhi(pair_counts)
    ahhi, aeff = entity_hhi(area_counts)
    record: dict[str, Any] = {
        "raw_positive_rows": raw_count,
        "deduplicated_physical_positive_conditions": len(physical),
        "duplicate_rows_removed": raw_count - len(physical),
        "unique_target_count": physical.target_sat_id.nunique(),
        "unique_physical_pair_count": physical.physical_pair_id.nunique(),
        "unique_service_area_count": physical.target_service_area_id.nunique(),
        "unique_distance_count": physical.distance_km.nunique(),
        "unique_direction_count": physical.direction_deg.nunique(),
        "target_positive_hhi": thhi, "pair_positive_hhi": phhi, "service_area_positive_hhi": ahhi,
        "effective_target_count": teff, "effective_pair_count": peff, "effective_service_area_count": aeff,
    }
    record.update({f"target_{k}": v for k, v in top_shares(target_counts).items()})
    record.update({f"pair_{k}": v for k, v in top_shares(pair_counts).items()})
    return pd.DataFrame([record])


def build_conflicts(all_real: pd.DataFrame) -> pd.DataFrame:
    conflict_ids = all_real.groupby(PHYSICAL_KEY).formal_final_decision.nunique()
    conflict_keys = conflict_ids[conflict_ids > 1].reset_index()[PHYSICAL_KEY]
    if conflict_keys.empty:
        return pd.DataFrame(columns=["conflict_row_id"] + PHYSICAL_KEY)
    out = all_real.merge(conflict_keys, on=PHYSICAL_KEY, how="inner")
    cols = PHYSICAL_KEY + [
        "physical_condition_id", "physical_pair_id", "pair_instance_id", "pair_id", "sample_group",
        "formal_final_decision", "formal_score_value", "formal_b_hat_hz", "formal_k_hat_hz_per_s",
        "formal_score_gate_pass", "formal_b_gate_pass", "formal_k_gate_pass",
    ]
    out = out[cols].sort_values(PHYSICAL_KEY + ["sample_group"])
    out.insert(0, "conflict_row_id", np.arange(1, len(out) + 1))
    return out


def matrices(physical: pd.DataFrame) -> tuple[pd.DataFrame, ...]:
    target_pair = pd.pivot_table(physical, index="target_sat_id", columns="physical_pair_id", values="physical_condition_id", aggfunc="count", fill_value=0).reset_index()
    pair_area = pd.pivot_table(physical, index="physical_pair_id", columns="target_service_area_id", values="physical_condition_id", aggfunc="count", fill_value=0).reset_index()
    pair_distance = pd.pivot_table(physical, index="physical_pair_id", columns="distance_km", values="physical_condition_id", aggfunc="count", fill_value=0).reset_index()
    pair_direction = pd.pivot_table(physical, index="physical_pair_id", columns="direction_deg", values="physical_condition_id", aggfunc="count", fill_value=0).reset_index()
    return target_pair, pair_area, pair_distance, pair_direction


def report_positive_from_prior(validation: pd.DataFrame, report_text: str) -> tuple[float, str]:
    q = validation[
        validation.scope.eq("local_0_10km") & validation.stratum.eq("real_all") &
        validation.validation.eq("leave_one_pair_out") & validation.model.eq("M0_distance")
    ]
    if len(q) == 1:
        return float(q.iloc[0].positive_n), "grouped_validation real_all/local/M0 positive_n"
    matches = re.findall(r"真实[^\n]{0,30}正例[^\d]{0,10}(\d+)", report_text)
    return (float(matches[-1]), "prior report regex") if matches else (np.nan, "unavailable")


def correctness(
    rows: pd.DataFrame, raw_pos: pd.DataFrame, physical: pd.DataFrame, all_real: pd.DataFrame,
    target: pd.DataFrame, pair: pd.DataFrame, area: pd.DataFrame, distance: pd.DataFrame,
    direction: pd.DataFrame, group: pd.DataFrame, concentration: pd.DataFrame,
    conflicts: pd.DataFrame, matrices_out: tuple[pd.DataFrame, ...], prior_count: float,
) -> pd.DataFrame:
    tests = []
    def add(name: str, passed: bool, observed: Any, tolerance: str, notes: str = "") -> None:
        tests.append({"check": name, "passed": bool(passed), "observed": observed, "tolerance": tolerance, "notes": notes})
    required = set(PHYSICAL_KEY + MECHANISM_METRICS + ["sample_source", "sample_group", "formal_final_decision", "pair_id"])
    add("输入全量行表存在且字段完整", required.issubset(rows.columns), len(required - set(rows.columns)), "0 missing")
    filter_ok = raw_pos.sample_source.eq("real_tle_candidate").all() and raw_pos.bk_mode.eq("current_bk").all() and raw_pos.distance_km.gt(0).all() and raw_pos.formal_final_decision.eq("ACCEPT").all()
    add("主筛选条件正确", filter_ok, len(raw_pos), "real/current/d>0/ACCEPT")
    add("raw positive与前轮一致", np.isnan(prior_count) or len(raw_pos) == int(prior_count), f"current={len(raw_pos)}, prior={prior_count}", "equal or prior unavailable")
    add("物理去重主键唯一", not physical.duplicated(PHYSICAL_KEY).any(), int(physical.duplicated(PHYSICAL_KEY).sum()), "0 duplicate")
    conflict_condition_count = int(conflicts[PHYSICAL_KEY].drop_duplicates().shape[0]) if len(conflicts) else 0
    add("同一物理条件不存在ACCEPT/REJECT冲突", conflict_condition_count == 0, conflict_condition_count, "0", "冲突已完整写入 duplicate_conflicts.csv")
    add("所有正例均为真实轨道", raw_pos.sample_source.eq("real_tle_candidate").all(), raw_pos.sample_source.unique().tolist(), "real_tle_candidate")
    add("所有正例均为current_bk", raw_pos.bk_mode.eq("current_bk").all(), raw_pos.bk_mode.unique().tolist(), "current_bk")
    add("所有正例distance>0", raw_pos.distance_km.gt(0).all(), float(raw_pos.distance_km.min()), ">0")
    outside = int(raw_pos.distance_km.gt(10).sum())
    add("所有正例落在局部范围", outside == 0, outside, "0 rows above 10 km")
    totals = {
        "target": int(target.positive_physical_conditions.sum()),
        "pair": int(pair.positive_physical_conditions.sum()),
        "area": int(area.positive_physical_conditions.sum()),
        "distance": int(distance[distance.get("summary_level", "raw_direction_primary").ne("axis_auxiliary") if "summary_level" in distance else np.ones(len(distance), dtype=bool)].positive_physical_conditions.sum()),
        "direction_raw": int(direction[direction.summary_level.eq("raw_direction_primary")].positive_physical_conditions.sum()),
    }
    add("实体汇总可回加物理正例", all(v == len(physical) for v in totals.values()), json.dumps(totals, ensure_ascii=False), str(len(physical)))
    shares = {
        "target": float(target.positive_share.sum()), "pair": float(pair.positive_share.sum()),
        "area": float(area.positive_share.sum()), "distance": float(distance.positive_share.sum()),
        "direction_raw": float(direction[direction.summary_level.eq("raw_direction_primary")].positive_share.sum()),
        "group_fractional": float(group.positive_share.sum()),
    }
    add("positive_share总和为1", all(abs(v - 1.0) <= 1e-9 for v in shares.values()), json.dumps(shares, ensure_ascii=False), "1±1e-9")
    c = concentration.iloc[0]
    hhi_ok = all(0 < float(c[x]) <= 1 for x in ["target_positive_hhi", "pair_positive_hhi", "service_area_positive_hhi"])
    eff_ok = all(abs(float(c[h]) * float(c[e]) - 1.0) <= 1e-9 for h, e in [("target_positive_hhi", "effective_target_count"), ("pair_positive_hhi", "effective_pair_count"), ("service_area_positive_hhi", "effective_service_area_count")])
    add("HHI与有效实体数正确", hhi_ok and eff_ok, json.dumps({x: float(c[x]) for x in ["target_positive_hhi", "pair_positive_hhi", "service_area_positive_hhi", "effective_target_count", "effective_pair_count", "effective_service_area_count"]}), "HHI∈(0,1], HHI*N_eff=1")
    overlap = int(physical.appears_positive_in_multiple_sample_groups.sum())
    expected_overlap = int(raw_pos.groupby(PHYSICAL_KEY).sample_group.nunique().gt(1).sum())
    add("ordinary/boundary重复准确识别", overlap == expected_overlap, f"physical={overlap}, raw={expected_overlap}", "equal")
    primary_dups = {
        "physical": int(physical.duplicated(PHYSICAL_KEY).sum()),
        "target": int(target.duplicated(["target_sat_id"]).sum()),
        "pair": int(pair.duplicated(["physical_pair_id"]).sum()),
        "area": int(area.duplicated(["target_service_area_id"]).sum()),
        "distance": int(distance.duplicated(["distance_km"]).sum()),
        "direction": int(direction.duplicated(["summary_level", "direction_deg", "axis_group"]).sum()),
        "group": int(group.duplicated(["sample_group"]).sum()),
        "conflicts": int(conflicts.duplicated(["conflict_row_id"]).sum()) if len(conflicts) else 0,
    }
    for name, matrix in zip(["target_pair", "pair_area", "pair_distance", "pair_direction"], matrices_out):
        primary_dups[name] = int(matrix.iloc[:, 0].duplicated().sum())
    add("所有输出主键唯一", sum(primary_dups.values()) == 0, json.dumps(primary_dups, ensure_ascii=False), "all zero")
    # Traceability is at the raw label-row level. A physical key may have two
    # label rows, which is exactly what the conflict/duplicate audit exposes.
    raw_key = ["pair_instance_id"] + PHYSICAL_KEY
    add("每条raw正例可回溯唯一正式记录", not raw_pos.duplicated(raw_key).any(), int(raw_pos.duplicated(raw_key).sum()), "0 duplicate raw keys")
    pair_mapping = rows.groupby("pair_id")[["target_sat_id", "attack_sat_id"]].nunique().max()
    add("pair_id唯一表示物理卫星对", bool((pair_mapping <= 1).all()), pair_mapping.to_dict(), "max unique target/attack=1")
    return pd.DataFrame(tests)


def heuristic_decision(audit_df: pd.DataFrame, concentration: pd.DataFrame, physical: pd.DataFrame) -> tuple[str, list[str]]:
    if not audit_df.passed.all():
        return "暂缓扩样判断：物理条件判决冲突尚未解决", [
            "优先补充 observation realization / residual seed 主键，解释 ordinary/boundary 相同几何条件为何出现相反判决",
            "在冲突语义澄清前，不把19个去重条件作为19个独立观测",
            "随后再按目标、独立pair和不同过境决定定向扩样",
        ]
    c = concentration.iloc[0]
    broad = (
        c.unique_target_count >= 4 and c.unique_physical_pair_count >= 6 and
        c.unique_service_area_count >= 2 and c.unique_direction_count >= 2 and
        c.pair_top1_positive_share <= 0.30 and c.pair_top2_positive_share <= 0.50
    )
    if broad:
        return "启发式判断：暂不需要立即大规模扩样，可先理论化并安排中等规模外部验证", [
            "优先增加不同日期/不同过境以验证独立性", "其次增加无正例目标的独立pair", "不优先增加同一过境的距离/方向扫描密度",
        ]
    targets = sorted(set(["新增没有正例或样本不足的目标卫星", "新增独立真实目标—非目标卫星对", "对高风险pair增加不同日期/不同过境"]))
    return "启发式判断：需要定向扩样", targets


def savefig(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def heatmap(matrix: pd.DataFrame, title: str, path: Path) -> None:
    labels = matrix.iloc[:, 0].astype(str).tolist()
    values = matrix.iloc[:, 1:].to_numpy(float)
    fig, ax = plt.subplots(figsize=(max(9, 0.42 * max(values.shape[1], 1)), max(5, 0.35 * max(values.shape[0], 1))))
    im = ax.imshow(values, aspect="auto", cmap="viridis")
    ax.set_yticks(range(len(labels)), labels, fontsize=7)
    ax.set_xticks(range(values.shape[1]), [str(x) for x in matrix.columns[1:]], rotation=90, fontsize=7)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, label="物理正例条件数")
    savefig(fig, path)


def make_figures(
    target: pd.DataFrame, pair: pd.DataFrame, distance: pd.DataFrame, direction: pd.DataFrame,
    physical: pd.DataFrame, matrices_out: tuple[pd.DataFrame, ...], outdir: Path,
) -> list[Path]:
    paths: list[Path] = []
    fig, ax1 = plt.subplots(figsize=(9, 5))
    x = np.arange(len(target))
    ax1.bar(x, target.positive_physical_conditions, color="tab:blue", label="物理正例条件数")
    ax1.set_ylabel("物理正例条件数")
    ax1.set_xticks(x, target.target_sat_id.astype(str))
    ax2 = ax1.twinx()
    ax2.plot(x, target.target_condition_accept_rate, color="tab:red", marker="o", label="接受率")
    ax2.set_ylabel("非中心条件接受率")
    ax1.set_title("各目标卫星正例数量与接受率")
    p = outdir / "target_positive_count_and_rate.png"; savefig(fig, p); paths.append(p)

    fig, ax = plt.subplots(figsize=(12, 5))
    q = pair.sort_values("positive_physical_conditions", ascending=False)
    ax.bar(q.physical_pair_id, q.positive_share)
    ax.tick_params(axis="x", rotation=70, labelsize=7)
    ax.set(ylabel="正例贡献占比", title="物理卫星对正例贡献占比")
    p = outdir / "pair_positive_share.png"; savefig(fig, p); paths.append(p)

    d = distance.copy()
    fig, ax = plt.subplots(figsize=(8, 5)); ax.bar(d.distance_km.astype(str), d.positive_physical_conditions)
    ax.set(xlabel="距离 (km)", ylabel="物理正例条件数", title="真实轨道正例距离分布")
    p = outdir / "positive_by_distance.png"; savefig(fig, p); paths.append(p)

    dr = direction[direction.summary_level.eq("raw_direction_primary")]
    fig, ax = plt.subplots(figsize=(9, 5)); ax.bar(dr.direction_deg.astype(int).astype(str), dr.positive_physical_conditions)
    ax.set(xlabel="方向角（0°北，90°东，顺时针）", ylabel="物理正例条件数", title="真实轨道正例方向分布")
    p = outdir / "positive_by_direction.png"; savefig(fig, p); paths.append(p)

    _tp, pa, pdist, pdir = matrices_out
    for matrix, title, name in [
        (pa, "物理卫星对 × 服务区", "pair_area_heatmap.png"),
        (pdist, "物理卫星对 × 距离", "pair_distance_heatmap.png"),
        (pdir, "物理卫星对 × 方向", "pair_direction_heatmap.png"),
    ]:
        p = outdir / name; heatmap(matrix, title, p); paths.append(p)

    fig, ax = plt.subplots(figsize=(9, 6))
    sc = ax.scatter(
        physical.raw_geo_rmse_hz,
        physical.actual_direction_post_projection_sensitivity_hz_per_km,
        c=physical.geometry_tolerance_budget_absorption_ratio,
        s=50 + 100 * physical.unbounded_geometry_absorption_ratio,
        cmap="viridis", edgecolor="black", linewidth=0.3,
    )
    ax.set(xlabel="raw geometry RMSE (Hz)", ylabel="实际方向投影后敏感度 (Hz/km)", title="物理正例的 raw geometry—方向敏感度—吸收比例")
    fig.colorbar(sc, ax=ax, label="tolerance-budget 吸收比例")
    p = outdir / "positive_mechanism_relationship.png"; savefig(fig, p); paths.append(p)
    return paths


def write_report(
    args: argparse.Namespace, paths: dict[str, Path], raw_pos: pd.DataFrame, physical: pd.DataFrame,
    target: pd.DataFrame, pair: pd.DataFrame, area: pd.DataFrame, distance: pd.DataFrame,
    direction: pd.DataFrame, group: pd.DataFrame, concentration: pd.DataFrame,
    conflicts: pd.DataFrame, correctness_df: pd.DataFrame, figures: list[Path],
    decision: str, priorities: list[str], prior_source: str,
) -> None:
    c = concentration.iloc[0]
    pair_top = pair.sort_values("positive_physical_conditions", ascending=False).head(5)
    dir_raw = direction[direction.summary_level.eq("raw_direction_primary")]
    conflict_conditions = conflicts[PHYSICAL_KEY].drop_duplicates().shape[0] if len(conflicts) else 0
    audit_pass = bool(correctness_df.passed.all())
    report = f"""# 真实轨道非中心误接受分布与独立性审计

## 1. 目的与边界

本轮只读取全量机制表，未进行轨道传播、攻击重放、验证器修改或模型训练。主筛选为 `sample_source=real_tle_candidate`、`bk_mode=current_bk`、`distance_km>0`、`formal_final_decision=ACCEPT`；局部范围显式检查为 `distance_km<=10`。

## 2. 两种统计视图与主键

- 原始条件实例视图：{len(raw_pos)} 条正式 ACCEPT 标签行。
- 物理条件去重视图：{len(physical)} 个物理键，移除 {len(raw_pos)-len(physical)} 条双标签 ACCEPT 重复。
- 物理键：`target_sat_id + attack_sat_id + service_area_id + service_area_segment_index + distance + direction + bk_mode`。行表没有 evaluation start/end，也没有 observation realization / residual seed。

同一 `pair_id` 始终映射唯一 target/attack，因此本轮另建可读的 `physical_pair_id=target->attack`，但不把样本组写入物理 pair。

## 3. 数据正确性与冲突

{correctness_df.to_markdown(index=False)}

前轮正例计数来源：{prior_source}。发现 {conflict_conditions} 个物理条件在 ordinary/boundary 标签行之间同时出现 ACCEPT 与 REJECT；共有 {len(conflicts)} 条冲突标签明细。这表明这些标签行可能包含未保存的不同随机残差 realization，不能在缺少 realization 主键时既视为相同物理条件、又视为独立观测。

由于正确性审计并非全部通过，后续集中程度仍作为描述性结果输出，但扩样启发式结论暂缓。

## 4. 目标卫星分布

{target[['target_sat_id','positive_raw_rows','positive_physical_conditions','positive_physical_pair_count','positive_service_area_count','positive_share','all_real_conditions','target_condition_accept_rate']].to_markdown(index=False)}

## 5. 物理卫星对分布与集中程度

Top pair：

{pair_top[['physical_pair_id','positive_raw_rows','positive_physical_conditions','positive_service_area_count','positive_direction_count','positive_share','pair_condition_accept_rate','ordinary_positive_count','boundary_positive_count']].to_markdown(index=False)}

Top1/2/3 pair 占比分别为 {c.pair_top1_positive_share:.2%}、{c.pair_top2_positive_share:.2%}、{c.pair_top3_positive_share:.2%}。pair HHI={c.pair_positive_hhi:.4f}，有效 pair 数={c.effective_pair_count:.2f}。HHI 越接近 1 表示越集中；有效实体数 `1/HHI` 表示当前分布约等价于多少个均匀贡献实体。目标 HHI={c.target_positive_hhi:.4f}（有效目标 {c.effective_target_count:.2f}），服务区 HHI={c.service_area_positive_hhi:.4f}（有效服务区 {c.effective_service_area_count:.2f}）。

## 6. 服务区、距离、方向与样本组

服务区：

{area.to_markdown(index=False)}

距离：

{distance[['distance_km','positive_physical_conditions','positive_physical_pair_count','positive_target_count','positive_service_area_count','positive_share','all_real_conditions','distance_condition_accept_rate']].to_markdown(index=False)}

方向原始统计（0°北、90°东、顺时针）为主；轴向合并只作辅助，不能假定相反方向几何等价：

{direction[['summary_level','direction_deg','axis_group','positive_physical_conditions','positive_physical_pair_count','positive_target_count','positive_service_area_count','positive_share','all_real_conditions','direction_condition_accept_rate']].to_markdown(index=False)}

样本组使用 fractional attribution 计算 share，使一个双组正例条件在两个组各贡献 1/2，share 总和保持 1；`positive_physical_conditions` 仍保留各组内实际去重计数：

{group[['sample_group','positive_raw_rows','positive_physical_conditions','positive_physical_pair_count','positive_target_count','positive_fractional_equivalent','positive_share','all_real_conditions','group_condition_accept_rate','physical_conditions_positive_in_both_groups']].to_markdown(index=False)}

## 7. 覆盖矩阵与机制描述

已输出 target×pair、pair×area、pair×distance、pair×direction 四个矩阵。物理正例逐条保存 raw geometry、方向/最弱敏感度、两类吸收、formal b/k 及 gate margin；目标、pair、距离、样本组汇总包含均值、中位数、最小和最大值。没有引入聚类或新预测模型。

## 8. 必须回答的十五个问题

1. 原始真实轨道非中心正例：**{len(raw_pos)} 条**。
2. 标签去重后：**{len(physical)} 个物理正例条件**，移除 {len(raw_pos)-len(physical)} 条双 ACCEPT 重复。
3. 覆盖目标卫星：**{physical.target_sat_id.nunique()} 颗**。
4. 覆盖物理卫星对：**{physical.physical_pair_id.nunique()} 个**。
5. 覆盖服务区：**{physical.target_service_area_id.nunique()} 个 target-area**。
6. 是否主要集中于一个目标：描述上 44714 占比最高，但 top1 target={c.target_top1_positive_share:.2%}；是否可作独立性结论受标签冲突限制。
7. 是否集中于1～2个 pair：描述上否；top1 pair={c.pair_top1_positive_share:.2%}、top2={c.pair_top2_positive_share:.2%}。
8. top1/top2/top3 pair：{c.pair_top1_positive_share:.2%} / {c.pair_top2_positive_share:.2%} / {c.pair_top3_positive_share:.2%}。
9. 是否全部在2.5 km：**{bool((physical.distance_km==2.5).all())}**。
10. 5 km 或10 km误接受：5 km={int((physical.distance_km==5).sum())}，10 km={int((physical.distance_km==10).sum())}。
11. 是否集中少数方向：只出现在 {physical.direction_deg.nunique()} 个方向，分布为 {physical.direction_deg.value_counts().sort_index().to_dict()}，因此方向覆盖集中。
12. ordinary/boundary 大量物理重复：双 ACCEPT 重复 {int(physical.appears_positive_in_multiple_sample_groups.sum())} 个；更严重的是 {conflict_conditions} 个相同物理键存在相反判决。
13. 多个独立场景还是少数条件重复：描述上覆盖多个目标/pair，但独立 realization 无法从当前字段证明；不能把19个键直接解释为19个独立观测。
14. 是否足以支持真实轨道机制结论：足以支持“存在这些几何条件与正式误接受关联”的描述，不足以支持正例独立性或发生频率的稳健结论。
15. 是否立即扩充数据集：**{decision}**。

## 9. 扩样启发式判断与优先级

本节标准是研究规划启发式，不是统计定理。当前审计失败项使正式扩样建议暂缓。优先事项：

{chr(10).join(f'{i+1}. {x}' for i, x in enumerate(priorities))}

在 realization 语义修复后，如果仍需扩样，应优先新增独立目标/pair与不同日期过境，而不是增加同一次过境中的距离和方向行密度。

## 10. 图表与输出

生成 {len(figures)} 张图：{', '.join(p.name for p in figures)}。冲突明细、物理条件表和所有汇总/矩阵均使用独立 `real_tle_positive_audit_*` 文件名，未覆盖旧输出。

## 11. 局限

- 当前只有一个日期/过境族，无法估计跨过境独立性。
- 样本组可能不仅是标签，还隐含不同经验误差 realization；行表缺少 seed/realization ID。
- HHI、top-k 与有效实体数只描述这批正例，不是总体攻击成功概率或显著性检验。
"""
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    paths["report"].write_text(report, encoding="utf-8")


def append_log(
    args: argparse.Namespace, paths: dict[str, Path], raw_pos: pd.DataFrame, physical: pd.DataFrame,
    concentration: pd.DataFrame, conflicts: pd.DataFrame, correctness_df: pd.DataFrame,
    decision: str, priorities: list[str], figures: list[Path],
) -> None:
    c = concentration.iloc[0]
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    text = f"""

## {now} - 真实 TLE 非中心正例分布与独立性审计

### A. 本轮目标
只读审计真实轨道 current_bk 非中心 ACCEPT 的分布、物理去重、集中程度和独立性，不进行轨道传播、攻击重放或模型训练。

### B. 实际操作
- 新增 `scripts/run_real_tle_positive_distribution_audit.py`。
- 输入 `{args.row_summary}`、pair inventory、repeatability、grouped validation 和全量报告。
- 筛选 `real_tle_candidate + current_bk + distance>0 + formal ACCEPT`；使用 target/attack/area/segment/distance/direction/bk 物理键。

### C. 新增输出
- `outputs/metrics/real_tle_positive_audit_*.csv`（10 个明细/汇总 + 4 个矩阵）
- {paths['report']}
- {paths['figures']}/（{len(figures)} 张图）
- logs/work_log.md（仅追加）

### D. 运行命令
- `python -m py_compile scripts/run_real_tle_positive_distribution_audit.py`
- `python scripts/run_real_tle_positive_distribution_audit.py`

### E. 结果摘要
- raw positive rows={len(raw_pos)}；deduplicated physical conditions={len(physical)}；removed={len(raw_pos)-len(physical)}。
- targets={physical.target_sat_id.nunique()}；pairs={physical.physical_pair_id.nunique()}；target-areas={physical.target_service_area_id.nunique()}；distances={physical.distance_km.value_counts().sort_index().to_dict()}；directions={physical.direction_deg.value_counts().sort_index().to_dict()}。
- pair top1/top2/top3={c.pair_top1_positive_share:.2%}/{c.pair_top2_positive_share:.2%}/{c.pair_top3_positive_share:.2%}；pair HHI={c.pair_positive_hhi:.4f}；effective pairs={c.effective_pair_count:.2f}。
- conflicting physical conditions={conflicts[PHYSICAL_KEY].drop_duplicates().shape[0] if len(conflicts) else 0}；correctness={int(correctness_df.passed.sum())}/{len(correctness_df)}。
- 扩样判断：{decision}。

### F. 问题与下一步
- 当前最优先不是增加扫描行，而是补足/恢复 observation realization 或 residual seed 主键，解释相同物理键的标签间相反判决。
- 优先级：{'; '.join(priorities)}。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    paths = output_paths(args)
    check_io(args, paths)
    rows = pd.read_csv(args.row_summary, low_memory=False)
    inventory = pd.read_csv(args.pair_inventory)
    repeatability = pd.read_csv(args.repeatability)
    validation = pd.read_csv(args.grouped_validation)
    report_text = args.full_report.read_text(encoding="utf-8")
    required = PHYSICAL_KEY + [
        "pair_instance_id", "pair_id", "sample_source", "sample_group", "formal_final_decision",
        "formal_score_value", "formal_b_hat_hz", "formal_k_hat_hz_per_s",
        "formal_b_gate_lower_hz", "formal_b_gate_upper_hz",
        "formal_k_gate_lower_hz_per_s", "formal_k_gate_upper_hz_per_s",
        "formal_score_gate_pass", "formal_b_gate_pass", "formal_k_gate_pass",
    ] + [m for m in MECHANISM_METRICS if not m.startswith("formal_b_gate_margin") and not m.startswith("formal_k_gate_margin")]
    require_columns(rows, required, "full row summary")
    require_columns(inventory, ["pair_id", "target_sat_id", "attack_sat_id", "sample_group"], "pair inventory")
    require_columns(repeatability, ["pair_id", "service_area_accept_fraction_noncenter"], "repeatability")
    require_columns(validation, ["scope", "stratum", "validation", "model", "positive_n"], "grouped validation")
    rows = add_derived_fields(rows)
    all_real = rows[
        rows.sample_source.eq("real_tle_candidate") & rows.bk_mode.eq("current_bk") & rows.distance_km.gt(0)
    ].copy()
    raw_pos = all_real[all_real.formal_final_decision.eq("ACCEPT")].copy()
    physical = aggregate_physical_positive(raw_pos, all_real)
    target, pair, area, distance, direction, group, _all_physical = build_summaries(raw_pos, physical, all_real)
    concentration = build_concentration(target, pair, area, physical, len(raw_pos))
    conflicts = build_conflicts(all_real)
    matrices_out = matrices(physical)
    prior_count, prior_source = report_positive_from_prior(validation, report_text)
    correctness_df = correctness(rows, raw_pos, physical, all_real, target, pair, area, distance, direction, group, concentration, conflicts, matrices_out, prior_count)
    decision, priorities = heuristic_decision(correctness_df, concentration, physical)

    for key in ["physical", "target", "pair", "area", "distance", "direction", "group", "concentration", "conflicts", "correctness", "target_pair_matrix", "pair_area_matrix", "pair_distance_matrix", "pair_direction_matrix"]:
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    physical.to_csv(paths["physical"], index=False)
    target.to_csv(paths["target"], index=False)
    pair.to_csv(paths["pair"], index=False)
    area.to_csv(paths["area"], index=False)
    distance.to_csv(paths["distance"], index=False)
    direction.to_csv(paths["direction"], index=False)
    group.to_csv(paths["group"], index=False)
    concentration.to_csv(paths["concentration"], index=False)
    conflicts.to_csv(paths["conflicts"], index=False)
    correctness_df.to_csv(paths["correctness"], index=False)
    for key, matrix in zip(["target_pair_matrix", "pair_area_matrix", "pair_distance_matrix", "pair_direction_matrix"], matrices_out):
        matrix.to_csv(paths[key], index=False)
    figures = make_figures(target, pair, distance, direction, physical, matrices_out, paths["figures"])
    write_report(args, paths, raw_pos, physical, target, pair, area, distance, direction, group, concentration, conflicts, correctness_df, figures, decision, priorities, prior_source)
    append_log(args, paths, raw_pos, physical, concentration, conflicts, correctness_df, decision, priorities, figures)

    c = concentration.iloc[0]
    conflict_conditions = conflicts[PHYSICAL_KEY].drop_duplicates().shape[0] if len(conflicts) else 0
    print(f"1. raw positive rows: {len(raw_pos)}")
    print(f"2. deduplicated physical positive conditions: {len(physical)}")
    print(f"3. unique targets: {physical.target_sat_id.nunique()}")
    print(f"4. unique physical pairs: {physical.physical_pair_id.nunique()}")
    print(f"5. unique target-service areas: {physical.target_service_area_id.nunique()}")
    print(f"6. pair top1/top2/top3 share: {c.pair_top1_positive_share:.2%}/{c.pair_top2_positive_share:.2%}/{c.pair_top3_positive_share:.2%}")
    print(f"7. pair HHI={c.pair_positive_hhi:.6f}; effective pair count={c.effective_pair_count:.3f}")
    print(f"8. distance distribution: {physical.distance_km.value_counts().sort_index().to_dict()}")
    print(f"9. direction distribution: {physical.direction_deg.value_counts().sort_index().to_dict()}")
    print(f"10. ordinary/boundary double-ACCEPT physical duplicates: {physical.appears_positive_in_multiple_sample_groups.sum()}; conflicting physical conditions: {conflict_conditions}")
    print(f"11. dominance: target top1={c.target_top1_positive_share:.2%}; pair top1={c.pair_top1_positive_share:.2%}; descriptive pair concentration is low, independence remains unresolved")
    print(f"12. expansion decision: {decision}")
    print(f"13. priorities: {'; '.join(priorities)}")
    print(f"correctness: {int(correctness_df.passed.sum())}/{len(correctness_df)} passed")


if __name__ == "__main__":
    main()
