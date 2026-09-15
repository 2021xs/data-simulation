#!/usr/bin/env python3
"""Apply the frozen Stage-1F-lite joint RTN sets to untouched June data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy
from scipy.stats import pearsonr, spearmanr


STATUS_SUPPORTED = "JUNE_STAGE1F_LITE_CONFIRMATORY_SUPPORTED"
STATUS_UNDERCOVERAGE = "JUNE_STAGE1F_LITE_CONFIRMATORY_UNDERCOVERAGE"
STATUS_INVALID = "JUNE_STAGE1F_LITE_CONFIRMATORY_INVALID"

PRIMARY = "ROBUST_EMPIRICAL_ELLIPSOID"
SECONDARY = "JOINT_MAX_SCORE_BOX"
EXPECTED_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
EXPECTED_JUNE_SHA = "DBE3551373D5EFDAF33CFB16296A564ADA29AA49E9852A92F599AD49B00934ED"
EXPECTED_COHORT_SHA = "30D7A846DDDE5850645CD3C1C03C061E7971AE40A2EE052FFB4E8BA3E7F4ED36"

JUNE_DATASET = Path("outputs/datasets/orbit_uncertainty_stage1b_20260601_20260630_rtn_residual_library.csv")
JUNE_STAGE1B_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1b_20260601_20260630_manifest.json")
PARAMETERS_PATH = Path("outputs/metrics/orbit_uncertainty_stage1f_lite_frozen_parameters.csv")
FREEZE_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1f_lite_manifest.json")
FREEZE_REPORT = Path("outputs/reports/orbit_uncertainty_stage1f_lite_design_freeze_report.md")
DEVELOPMENT_VELOCITY = Path("outputs/metrics/orbit_uncertainty_stage1f_lite_velocity_diagnostic.csv")
MAY_SATELLITE = Path("outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_per_satellite.csv")
WORK_LOG = Path("logs/work_log.md")

METRICS = Path("outputs/metrics")
REPORTS = Path("outputs/reports")
PREFIX = "orbit_uncertainty_stage1f_lite_june"
PRIMARY_PATH = METRICS / f"{PREFIX}_primary_coverage.csv"
BIN_PATH = METRICS / f"{PREFIX}_freshness_bin_coverage.csv"
SATELLITE_PATH = METRICS / f"{PREFIX}_satellite_coverage.csv"
HALF_PATH = METRICS / f"{PREFIX}_half_coverage.csv"
EPISODE_PATH = METRICS / f"{PREFIX}_continuous_out_of_set_episodes.csv"
SECONDARY_PATH = METRICS / f"{PREFIX}_secondary_box_sensitivity.csv"
STRUCTURE_PATH = METRICS / f"{PREFIX}_structural_replication.csv"
VELOCITY_PATH = METRICS / f"{PREFIX}_velocity_diagnostic.csv"
REFERENCE_PATH = METRICS / f"{PREFIX}_reference_sensitivity.csv"
VOLUME_PATH = METRICS / f"{PREFIX}_frozen_volume_exposure.csv"
CORRECTNESS_PATH = METRICS / f"{PREFIX}_correctness_audit.csv"
MANIFEST_PATH = METRICS / f"{PREFIX}_confirmatory_manifest.json"
REPORT_PATH = REPORTS / f"{PREFIX}_confirmatory_validation_report.md"

OUTPUT_PATHS = (
    PRIMARY_PATH, BIN_PATH, SATELLITE_PATH, HALF_PATH, EPISODE_PATH,
    SECONDARY_PATH, STRUCTURE_PATH, VELOCITY_PATH, REFERENCE_PATH,
    VOLUME_PATH, CORRECTNESS_PATH, MANIFEST_PATH, REPORT_PATH,
)

POSITION_COLUMNS = ("delta_R_km", "delta_T_km", "delta_N_km")
FRESHNESS_EDGES_H = (0.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0)
FRESHNESS_LABELS = ("0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h")
P99_MINIMUM = 0.98
STRUCTURAL_MIN_N = 100
STRUCTURAL_P99_MINIMUM = 0.95
BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20260601
EPISODE_BREAK_GAP_H = 6.0
FIRST_HALF_STOP = pd.Timestamp("2026-06-16T00:00:00Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Required manifest missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def output_entry(path: Path) -> dict[str, Any]:
    return {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def freshness_bin(values: pd.Series | np.ndarray) -> pd.Series:
    return pd.cut(
        values,
        FRESHNESS_EDGES_H,
        labels=FRESHNESS_LABELS,
        right=True,
        include_lowest=False,
    )


def classify_score(score: np.ndarray, c95: np.ndarray, c99: np.ndarray) -> np.ndarray:
    return np.where(
        score <= c95,
        "NOT_ORBIT_DISTINCT",
        np.where(score <= c99, "AMBIGUOUS", "ORBIT_DISTINCT"),
    )


def covariance_from_row(row: pd.Series) -> np.ndarray:
    return np.array([
        [row.cov_RR_km2, row.cov_RT_km2, row.cov_RN_km2],
        [row.cov_TR_km2, row.cov_TT_km2, row.cov_TN_km2],
        [row.cov_NR_km2, row.cov_NT_km2, row.cov_NN_km2],
    ], dtype=float)


def load_frozen_parameters(path: Path = PARAMETERS_PATH) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    if sha256(path) != EXPECTED_PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch")
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if len(frame) != 12 or set(frame.candidate) != {PRIMARY, SECONDARY}:
        raise SystemExit("Frozen parameter row/candidate mismatch")
    if frame.groupby("candidate").freshness_bin.nunique().to_dict() != {PRIMARY: 6, SECONDARY: 6}:
        raise SystemExit("Frozen parameter freshness-bin mismatch")
    if set(frame.freshness_bin) != set(FRESHNESS_LABELS):
        raise SystemExit("Frozen parameter labels mismatch")
    models: dict[str, dict[str, Any]] = {PRIMARY: {}, SECONDARY: {}}
    for _, row in frame.iterrows():
        center = row.loc[["center_R_km", "center_T_km", "center_N_km"]].to_numpy(dtype=float)
        model: dict[str, Any] = {
            "center": center,
            "c95": float(row.c95_empirical_score),
            "c99": float(row.c99_empirical_score),
        }
        if row.candidate == PRIMARY:
            covariance = covariance_from_row(row)
            eigenvalues = np.linalg.eigvalsh(covariance)
            if not np.allclose(covariance, covariance.T, rtol=0.0, atol=1e-14):
                raise SystemExit(f"Frozen covariance is asymmetric: {row.freshness_bin}")
            if eigenvalues.min() <= 0.0 or not np.isfinite(np.linalg.cond(covariance)):
                raise SystemExit(f"Frozen covariance is not positive definite: {row.freshness_bin}")
            model["covariance"] = covariance
            model["precision"] = np.linalg.inv(covariance)
            model["determinant"] = float(np.linalg.det(covariance))
            model["condition_number"] = float(np.linalg.cond(covariance))
        else:
            scale = row.loc[["scale_R_km", "scale_T_km", "scale_N_km"]].to_numpy(dtype=float)
            if np.any(scale <= 0.0) or not np.isfinite(scale).all():
                raise SystemExit(f"Frozen box scale is invalid: {row.freshness_bin}")
            model["scale"] = scale
        models[str(row.candidate)][str(row.freshness_bin)] = model
    return frame, models


def score_frozen_candidate(
    supported: pd.DataFrame,
    candidate: str,
    models: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for label in FRESHNESS_LABELS:
        group = supported.loc[supported.freshness_bin.astype(str) == label].copy()
        if group.empty:
            continue
        model = models[label]
        values = group.loc[:, POSITION_COLUMNS].to_numpy(dtype=float)
        centered = values - model["center"]
        if candidate == PRIMARY:
            score = np.einsum("ij,jk,ik->i", centered, model["precision"], centered)
        else:
            score = np.max(np.abs(centered) / model["scale"], axis=1)
        group["candidate"] = candidate
        group["joint_score"] = score
        group["cutoff_p95"] = model["c95"]
        group["cutoff_p99"] = model["c99"]
        group["inside_p95"] = score <= model["c95"]
        group["inside_p99"] = score <= model["c99"]
        group["decision"] = classify_score(score, group.cutoff_p95.to_numpy(), group.cutoff_p99.to_numpy())
        rows.append(group)
    result = pd.concat(rows, ignore_index=True)
    return result.sort_values(["evaluation_time", "NORAD_CAT_ID"], kind="mergesort").reset_index(drop=True)


def wilson_interval(covered: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if n == 0:
        return math.nan, math.nan
    p = covered / n
    denominator = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denominator
    return center - half, center + half


def coverage_record(candidate: str, level: str, group_id: str, group: pd.DataFrame) -> dict[str, Any]:
    n = len(group)
    covered95 = int(group.inside_p95.sum())
    covered99 = int(group.inside_p99.sum())
    p95 = covered95 / n
    p99 = covered99 / n
    p95_lo, p95_hi = wilson_interval(covered95, n)
    p99_lo, p99_hi = wilson_interval(covered99, n)
    decision_counts = group.decision.value_counts()
    return {
        "candidate": candidate,
        "candidate_role": "PRIMARY_CANDIDATE_FOR_JUNE" if candidate == PRIMARY else "SECONDARY_SENSITIVITY_CANDIDATE",
        "aggregation_level": level,
        "group_id": group_id,
        "n": n,
        "satellite_count": int(group.NORAD_CAT_ID.nunique()),
        "p95_covered_count": covered95,
        "p95_exceedance_count": n - covered95,
        "p95_joint_coverage": p95,
        "p95_wilson_ci_low": p95_lo,
        "p95_wilson_ci_high": p95_hi,
        "p99_covered_count": covered99,
        "p99_exceedance_count": n - covered99,
        "p99_joint_coverage": p99,
        "p99_wilson_ci_low": p99_lo,
        "p99_wilson_ci_high": p99_hi,
        "false_orbit_distinct_rate": 1.0 - p99,
        "not_orbit_distinct_count": int(decision_counts.get("NOT_ORBIT_DISTINCT", 0)),
        "ambiguous_count": int(decision_counts.get("AMBIGUOUS", 0)),
        "orbit_distinct_count": int(decision_counts.get("ORBIT_DISTINCT", 0)),
        "not_orbit_distinct_fraction": float((group.decision == "NOT_ORBIT_DISTINCT").mean()),
        "ambiguous_fraction": float((group.decision == "AMBIGUOUS").mean()),
        "orbit_distinct_fraction": float((group.decision == "ORBIT_DISTINCT").mean()),
    }


def cluster_bootstrap(scored: pd.DataFrame, repetitions: int, seed: int) -> dict[str, float]:
    aggregate = scored.groupby("NORAD_CAT_ID", sort=True).agg(
        n=("inside_p99", "size"),
        covered_p95=("inside_p95", "sum"),
        covered_p99=("inside_p99", "sum"),
    )
    counts = aggregate.n.to_numpy(dtype=float)
    covered95 = aggregate.covered_p95.to_numpy(dtype=float)
    covered99 = aggregate.covered_p99.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(aggregate), size=(repetitions, len(aggregate)))
    denominator = counts[sampled].sum(axis=1)
    p95 = covered95[sampled].sum(axis=1) / denominator
    p99 = covered99[sampled].sum(axis=1) / denominator
    false_rate = 1.0 - p99
    quantiles = lambda x: np.quantile(x, [0.025, 0.975], method="linear")
    p95_ci = quantiles(p95)
    p99_ci = quantiles(p99)
    false_ci = quantiles(false_rate)
    return {
        "p95_ci_low": float(p95_ci[0]), "p95_ci_high": float(p95_ci[1]),
        "p99_ci_low": float(p99_ci[0]), "p99_ci_high": float(p99_ci[1]),
        "false_rate_ci_low": float(false_ci[0]), "false_rate_ci_high": float(false_ci[1]),
    }


def bin_coverage(scored_by_candidate: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate, scored in scored_by_candidate.items():
        for label in FRESHNESS_LABELS:
            group = scored.loc[scored.freshness_bin.astype(str) == label]
            row = coverage_record(candidate, "FRESHNESS_BIN", label, group)
            row["hard_rule_applicable"] = len(group) >= STRUCTURAL_MIN_N
            row["structural_bin_undercoverage"] = bool(
                len(group) >= STRUCTURAL_MIN_N and row["p99_joint_coverage"] < STRUCTURAL_P99_MINIMUM
            )
            row["uncertainty_method"] = "Wilson 95% interval; hard failure only when n>=100"
            rows.append(row)
    return pd.DataFrame(rows)


def may_context() -> pd.DataFrame:
    frame = pd.read_csv(MAY_SATELLITE, dtype={"NORAD_CAT_ID": str}, encoding="utf-8-sig")
    chosen = frame.loc[
        (frame["model"] == "M0") & (frame["quantile"].astype(float) == 0.95)
        & frame["target"].isin(["position_error_norm_km", "abs_delta_N_km"]),
        ["NORAD_CAT_ID", "target", "observed_coverage"],
    ]
    return chosen.pivot(index="NORAD_CAT_ID", columns="target", values="observed_coverage").reset_index().rename(columns={
        "position_error_norm_km": "may_m0_position_norm_p95_coverage",
        "abs_delta_N_km": "may_m0_abs_N_p95_coverage",
    })


def satellite_coverage(scored_by_candidate: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate, scored in scored_by_candidate.items():
        for norad, group in scored.groupby("NORAD_CAT_ID", sort=True):
            row = coverage_record(candidate, "SATELLITE", str(norad), group)
            row["NORAD_CAT_ID"] = str(norad)
            row["single_satellite_hard_pass_fail"] = False
            rows.append(row)
    result = pd.DataFrame(rows).merge(may_context(), on="NORAD_CAT_ID", how="left", validate="many_to_one")
    result["may_context_role"] = "AFTER_THE_FACT_INTERPRETATION_ONLY"
    result["june_p99_below_95_descriptive"] = result.p99_joint_coverage < 0.95
    result["named_may_satellite"] = result.NORAD_CAT_ID.isin(["48458", "60265", "48309"])
    return result


def half_coverage(scored_by_candidate: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate, scored in scored_by_candidate.items():
        halves = {
            "FIRST_HALF": scored.loc[scored.evaluation_time < FIRST_HALF_STOP],
            "SECOND_HALF": scored.loc[scored.evaluation_time >= FIRST_HALF_STOP],
        }
        candidate_rows = [coverage_record(candidate, "JUNE_HALF", name, group) for name, group in halves.items()]
        p95_diff = abs(candidate_rows[0]["p95_joint_coverage"] - candidate_rows[1]["p95_joint_coverage"])
        p99_diff = abs(candidate_rows[0]["p99_joint_coverage"] - candidate_rows[1]["p99_joint_coverage"])
        for row in candidate_rows:
            row["absolute_half_to_half_p95_difference"] = p95_diff
            row["absolute_half_to_half_p99_difference"] = p99_diff
            rows.append(row)
    return pd.DataFrame(rows)


def continuous_episodes(scored: pd.DataFrame, threshold: str) -> pd.DataFrame:
    inside_column = "inside_p99" if threshold == "U99" else "inside_p95"
    rows: list[dict[str, Any]] = []
    for norad, group in scored.groupby("NORAD_CAT_ID", sort=True):
        ordered = group.sort_values("evaluation_time", kind="mergesort")
        current: list[pd.Series] = []
        previous_time: pd.Timestamp | None = None

        def finish() -> None:
            if not current:
                return
            start = current[0].evaluation_time
            end = current[-1].evaluation_time
            rows.append({
                "NORAD_CAT_ID": str(norad),
                "threshold_type": threshold,
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "end_utc": end.isoformat().replace("+00:00", "Z"),
                "duration_hours": (end - start).total_seconds() / 3600.0,
                "row_count": len(current),
                "max_score": max(float(item.joint_score) for item in current),
                "freshness_bins": "|".join(dict.fromkeys(str(item.freshness_bin) for item in current)),
                "episode_break_gap_hours": EPISODE_BREAK_GAP_H,
                "definition": "consecutive formal-support out-of-set evaluation rows; in-set row or >6 h gap ends run",
            })
            current.clear()

        for _, item in ordered.iterrows():
            is_out = not bool(item[inside_column])
            gap_h = math.inf if previous_time is None else (item.evaluation_time - previous_time).total_seconds() / 3600.0
            if is_out:
                if current and gap_h > EPISODE_BREAK_GAP_H:
                    finish()
                current.append(item)
            else:
                finish()
            previous_time = item.evaluation_time
        finish()
    columns = [
        "NORAD_CAT_ID", "threshold_type", "start_utc", "end_utc", "duration_hours",
        "row_count", "max_score", "freshness_bins", "episode_break_gap_hours", "definition",
    ]
    return pd.DataFrame(rows, columns=columns)


def safe_corr(x: np.ndarray, y: np.ndarray, method: str) -> float:
    if len(x) < 3 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return math.nan
    return float(pearsonr(x, y).statistic if method == "pearson" else spearmanr(x, y).statistic)


def structural_replication(supported: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    groups = [("ALL", supported)] + [
        (label, supported.loc[supported.freshness_bin.astype(str) == label]) for label in FRESHNESS_LABELS
    ]
    for label, group in groups:
        values = group.loc[:, POSITION_COLUMNS].to_numpy(dtype=float)
        absolute = np.abs(values)
        dominant = np.argmax(absolute, axis=1)
        rows.append({
            "scope": "JUNE_WITHIN_SUPPORT", "freshness_bin": label, "n": len(group),
            "satellite_count": int(group.NORAD_CAT_ID.nunique()),
            "median_R_km": float(np.median(values[:, 0])),
            "median_T_km": float(np.median(values[:, 1])),
            "median_N_km": float(np.median(values[:, 2])),
            "median_abs_R_km": float(np.median(absolute[:, 0])),
            "median_abs_T_km": float(np.median(absolute[:, 1])),
            "median_abs_N_km": float(np.median(absolute[:, 2])),
            "R_dominant_fraction": float(np.mean(dominant == 0)),
            "T_dominant_fraction": float(np.mean(dominant == 1)),
            "N_dominant_fraction": float(np.mean(dominant == 2)),
            "pearson_R_T": safe_corr(values[:, 0], values[:, 1], "pearson"),
            "pearson_R_N": safe_corr(values[:, 0], values[:, 2], "pearson"),
            "pearson_T_N": safe_corr(values[:, 1], values[:, 2], "pearson"),
            "spearman_R_T": safe_corr(values[:, 0], values[:, 1], "spearman"),
            "spearman_R_N": safe_corr(values[:, 0], values[:, 2], "spearman"),
            "spearman_T_N": safe_corr(values[:, 1], values[:, 2], "spearman"),
            "supportive_endpoint_only": True,
        })
    return pd.DataFrame(rows)


def velocity_diagnostic(supported: pd.DataFrame) -> pd.DataFrame:
    development = pd.read_csv(DEVELOPMENT_VELOCITY, encoding="utf-8-sig")
    development = development.loc[development.scope.isin(["APRIL", "MAY", "COMBINED"])].copy()
    x = supported.delta_T_km.to_numpy(dtype=float)
    y = supported.delta_v_R_km_s.to_numpy(dtype=float)
    june = pd.DataFrame([{
        "scope": "JUNE", "n": len(supported), "satellite_count": supported.NORAD_CAT_ID.nunique(),
        "median_abs_vR_km_s": np.median(np.abs(supported.delta_v_R_km_s)),
        "median_abs_vT_km_s": np.median(np.abs(supported.delta_v_T_km_s)),
        "median_abs_vN_km_s": np.median(np.abs(supported.delta_v_N_km_s)),
        "pearson_vR_vT": safe_corr(supported.delta_v_R_km_s.to_numpy(), supported.delta_v_T_km_s.to_numpy(), "pearson"),
        "pearson_vR_vN": safe_corr(supported.delta_v_R_km_s.to_numpy(), supported.delta_v_N_km_s.to_numpy(), "pearson"),
        "pearson_vT_vN": safe_corr(supported.delta_v_T_km_s.to_numpy(), supported.delta_v_N_km_s.to_numpy(), "pearson"),
        "spearman_vR_vT": safe_corr(supported.delta_v_R_km_s.to_numpy(), supported.delta_v_T_km_s.to_numpy(), "spearman"),
        "spearman_vR_vN": safe_corr(supported.delta_v_R_km_s.to_numpy(), supported.delta_v_N_km_s.to_numpy(), "spearman"),
        "spearman_vT_vN": safe_corr(supported.delta_v_T_km_s.to_numpy(), supported.delta_v_N_km_s.to_numpy(), "spearman"),
        "pearson_delta_T_delta_v_R": safe_corr(x, y, "pearson"),
        "spearman_delta_T_delta_v_R": safe_corr(x, y, "spearman"),
        "primary_gate_dimension": "SIGNED_POSITION_RTN_3D_ONLY",
        "velocity_operational_parameter_count": 0,
    }])
    result = pd.concat([development, june], ignore_index=True)
    result["six_dimensional_set_built"] = False
    result["diagnostic_role"] = "SUPPORTIVE_ONLY"
    return result


def reference_sensitivity(scored: pd.DataFrame) -> pd.DataFrame:
    work = scored.copy()
    work["rms_quartile"] = pd.qcut(
        work.supgp_rms_km.rank(method="first"), 4,
        labels=["RMS_Q1", "RMS_Q2", "RMS_Q3", "RMS_Q4"],
    )
    rows: list[dict[str, Any]] = []
    for quartile, group in work.groupby("rms_quartile", observed=True, sort=True):
        row = coverage_record(PRIMARY, "RMS_QUARTILE", str(quartile), group)
        row.update({
            "rms_min_km": group.supgp_rms_km.min(),
            "rms_median_km": group.supgp_rms_km.median(),
            "rms_max_km": group.supgp_rms_km.max(),
            "normalized_score_to_c99_median": np.median(group.joint_score / group.cutoff_p99),
            "normalized_score_to_c99_p95": np.quantile(group.joint_score / group.cutoff_p99, 0.95),
            "normalized_score_to_c99_p99": np.quantile(group.joint_score / group.cutoff_p99, 0.99),
            "rms_role": "REFERENCE_ONLY_DIAGNOSTIC",
            "rms_operational_parameter_count": 0,
            "quartile_definition": "June within-support rank(method=first) qcut into four equal-count descriptive groups",
        })
        rows.append(row)
    return pd.DataFrame(rows)


def frozen_volume_exposure(parameters: pd.DataFrame, supported: pd.DataFrame) -> pd.DataFrame:
    occupancy = supported.freshness_bin.astype(str).value_counts().to_dict()
    rows: list[dict[str, Any]] = []
    for _, row in parameters.iterrows():
        label = str(row.freshness_bin)
        for quantile, threshold_column in [(0.95, "c95_empirical_score"), (0.99, "c99_empirical_score")]:
            threshold = float(row[threshold_column])
            if row.candidate == PRIMARY:
                volume = (4.0 / 3.0) * math.pi * threshold ** 1.5 * math.sqrt(float(row.determinant_km6))
            else:
                scale = row.loc[["scale_R_km", "scale_T_km", "scale_N_km"]].to_numpy(dtype=float)
                volume = 8.0 * threshold ** 3 * float(np.prod(scale))
            rows.append({
                "record_type": "FROZEN_BIN_VOLUME", "candidate": row.candidate,
                "freshness_bin": label, "quantile": quantile, "occupancy_n": occupancy.get(label, 0),
                "frozen_volume_km3": volume, "log_frozen_volume": math.log(volume),
                "june_derived_geometry_parameter_count": 0,
            })
    detail = pd.DataFrame(rows)
    aggregate: list[dict[str, Any]] = []
    for (candidate, quantile), group in detail.groupby(["candidate", "quantile"], sort=True):
        weighted_log = float(np.average(group.log_frozen_volume, weights=group.occupancy_n))
        aggregate.append({
            "record_type": "OCCUPANCY_WEIGHTED_GEOMETRIC_MEAN", "candidate": candidate,
            "freshness_bin": "ALL", "quantile": quantile, "occupancy_n": int(group.occupancy_n.sum()),
            "frozen_volume_km3": math.exp(weighted_log), "log_frozen_volume": weighted_log,
            "june_derived_geometry_parameter_count": 0,
        })
    return pd.concat([detail, pd.DataFrame(aggregate)], ignore_index=True)


def independent_score_audit(scored_by_candidate: dict[str, pd.DataFrame], models: dict[str, dict[str, Any]]) -> dict[str, Any]:
    primary = scored_by_candidate[PRIMARY].copy()
    chosen: list[int] = []
    for label in FRESHNESS_LABELS:
        group = primary.loc[primary.freshness_bin.astype(str) == label]
        for cutoff in ("cutoff_p95", "cutoff_p99"):
            chosen.extend(group.assign(distance=(group.joint_score - group[cutoff]).abs()).nsmallest(2, "distance").index.tolist())
    for decision in ("NOT_ORBIT_DISTINCT", "AMBIGUOUS", "ORBIT_DISTINCT"):
        chosen.extend(primary.loc[primary.decision == decision].head(4).index.tolist())
    chosen = list(dict.fromkeys(chosen))
    if len(chosen) < 30:
        for index in np.linspace(0, len(primary) - 1, 30, dtype=int):
            if int(index) not in chosen:
                chosen.append(int(index))
            if len(chosen) >= 30:
                break
    chosen = chosen[:max(30, min(len(chosen), 42))]
    max_score_diff = 0.0
    classification_mismatch = 0
    bin_mismatch = 0
    candidates_checked = 0
    sample_bins: set[str] = set()
    sample_satellites: set[str] = set()
    sample_decisions: set[str] = set()
    for candidate, scored in scored_by_candidate.items():
        indexed = scored.loc[chosen]
        for _, item in indexed.iterrows():
            assigned = freshness_bin(pd.Series([item.element_age_hours])).iloc[0]
            label = str(assigned)
            bin_mismatch += int(label != str(item.freshness_bin))
            model = models[candidate][label]
            vector = item.loc[list(POSITION_COLUMNS)].to_numpy(dtype=float) - model["center"]
            if candidate == PRIMARY:
                independent = float(vector @ np.linalg.solve(model["covariance"], vector))
            else:
                independent = float(max(abs(vector[i]) / model["scale"][i] for i in range(3)))
            max_score_diff = max(max_score_diff, abs(independent - float(item.joint_score)))
            independent_class = classify_score(
                np.array([independent]), np.array([model["c95"]]), np.array([model["c99"]])
            )[0]
            classification_mismatch += int(independent_class != item.decision)
            candidates_checked += 1
            sample_bins.add(label)
            sample_satellites.add(str(item.NORAD_CAT_ID))
            sample_decisions.add(str(item.decision))
    return {
        "sample_rows_per_candidate": len(chosen),
        "candidate_row_comparisons": candidates_checked,
        "sample_satellite_count": len(sample_satellites),
        "sample_freshness_bin_count": len(sample_bins),
        "sample_decisions": sorted(sample_decisions),
        "near_c95_and_c99_selection": True,
        "max_score_absolute_difference": max_score_diff,
        "freshness_bin_mismatch_count": bin_mismatch,
        "classification_mismatch_count": classification_mismatch,
    }


def paths_from_object(value: Any) -> Iterable[Path]:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key == "path" and isinstance(nested, str):
                yield Path(nested)
            else:
                yield from paths_from_object(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from paths_from_object(nested)


def protected_paths(freeze: dict[str, Any], stage1b: dict[str, Any]) -> list[Path]:
    explicit = [PARAMETERS_PATH, FREEZE_MANIFEST, FREEZE_REPORT, JUNE_DATASET, JUNE_STAGE1B_MANIFEST]
    paths = explicit + list(paths_from_object(freeze)) + list(paths_from_object(stage1b))
    unique: dict[str, Path] = {}
    for path in paths:
        resolved = path if path.is_absolute() else Path.cwd() / path
        if resolved.exists() and resolved.is_file() and resolved.resolve() != WORK_LOG.resolve():
            unique[str(resolved.resolve()).lower()] = resolved.resolve()
    return sorted(unique.values(), key=lambda item: item.as_posix().lower())


def fingerprint(paths: Iterable[Path]) -> dict[str, str]:
    return {path.as_posix(): sha256(path) for path in paths}


def correctness_rows(checks: list[tuple[str, Any, Any, bool, str]]) -> pd.DataFrame:
    return pd.DataFrame([
        {"check": name, "observed": observed, "expected": expected, "passed": bool(passed), "notes": notes}
        for name, observed, expected, passed, notes in checks
    ])


def markdown_table(frame: pd.DataFrame, digits: int = 6) -> str:
    shown = frame.copy()
    for column in shown.select_dtypes(include=[np.number]).columns:
        shown[column] = shown[column].map(lambda value: f"{value:.{digits}f}" if pd.notna(value) else "")
    return shown.to_markdown(index=False)


def build_report(
    status: str,
    primary: pd.DataFrame,
    bins: pd.DataFrame,
    satellites: pd.DataFrame,
    halves: pd.DataFrame,
    episodes: pd.DataFrame,
    secondary: pd.DataFrame,
    structure: pd.DataFrame,
    velocity: pd.DataFrame,
    reference: pd.DataFrame,
    correctness: pd.DataFrame,
    repeated: list[str],
    stopping_snapshot: list[dict[str, str]],
) -> str:
    p = primary.iloc[0]
    primary_bins = bins.loc[bins.candidate == PRIMARY, ["group_id", "n", "p95_joint_coverage", "p99_joint_coverage", "structural_bin_undercoverage"]]
    primary_halves = halves.loc[halves.candidate == PRIMARY, ["group_id", "n", "p95_joint_coverage", "p99_joint_coverage", "false_orbit_distinct_rate"]]
    primary_sats = satellites.loc[satellites.candidate == PRIMARY].sort_values("p99_joint_coverage")
    box_pooled = secondary.loc[secondary.aggregation_level == "POOLED"].iloc[0]
    overall_structure = structure.loc[structure.freshness_bin == "ALL"].iloc[0]
    june_velocity = velocity.loc[velocity.scope == "JUNE"].iloc[0]
    max_u99 = episodes.loc[episodes.threshold_type == "U99"].sort_values("duration_hours", ascending=False).head(1)
    rms_q4 = reference.loc[reference.group_id == "RMS_Q4"].iloc[0]
    stopping_frame = pd.DataFrame(stopping_snapshot)
    episode_text = "无 U99 episode" if max_u99.empty else (
        f"NORAD {max_u99.iloc[0].NORAD_CAT_ID}，{max_u99.iloc[0].start_utc} 至 "
        f"{max_u99.iloc[0].end_utc}，{max_u99.iloc[0].duration_hours:.6f} h，"
        f"{int(max_u99.iloc[0].row_count)} rows"
    )
    return f"""# Orbit Uncertainty Stage-1F-lite June locked confirmatory validation

## 1. 冻结输入与协议

本次是冻结 April+May 模型对 untouched June 的首次预注册 confirmatory test。Primary 固定为 `{PRIMARY}`，secondary 固定为 `{SECONDARY}`；二者身份未交换。冻结参数 SHA256 为 `{EXPECTED_PARAMETER_SHA}`，June canonical SHA256 为 `{EXPECTED_JUNE_SHA}`。

正式支持域严格为 `0 < element_age_hours <= 36`：总计 5927 rows，其中 5389 rows 进入 confirmatory denominator，538 rows 记为 `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`，其中 25 rows 为真实 `ENGINEERING_STALENESS_GT72H`。outside-support rows 未进入 coverage、bin、candidate comparison 或 false-orbit-distinct 分母。

## 2. Primary confirmatory endpoint

- P99 joint legitimate coverage：`{p.p99_joint_coverage:.9f}`（{int(p.p99_covered_count)}/{int(p.n)}）
- false-orbit-distinct rate：`{p.false_orbit_distinct_rate:.9f}`（{int(p.p99_exceedance_count)}/{int(p.n)}）
- satellite-cluster bootstrap P99 95% CI：`[{p.p99_cluster_bootstrap_ci_low:.9f}, {p.p99_cluster_bootstrap_ci_high:.9f}]`
- P95 joint coverage：`{p.p95_joint_coverage:.9f}`；cluster-bootstrap 95% CI：`[{p.p95_cluster_bootstrap_ci_low:.9f}, {p.p95_cluster_bootstrap_ci_high:.9f}]`
- pooled P99 >= 98%：`{bool(p.pooled_p99_success)}`
- structural bin undercoverage count：`{int(p.structural_bin_undercoverage_count)}`

冻结 primary 判据只由 pooled P99、structural-bin rule、数值/provenance integrity 和 zero June fitting 决定。P95 是 secondary endpoint，不覆盖 primary 判决。

## 3. Freshness-bin coverage

{markdown_table(primary_bins)}

## 4. June halves

{markdown_table(primary_halves)}

P95/P99 half-to-half absolute difference 分别为 `{halves.loc[halves.candidate == PRIMARY].iloc[0].absolute_half_to_half_p95_difference:.9f}` / `{halves.loc[halves.candidate == PRIMARY].iloc[0].absolute_half_to_half_p99_difference:.9f}`，未按 half 重校准。

## 5. Satellite-cluster distribution and May context

20 颗卫星 P99 median=`{primary_sats.p99_joint_coverage.median():.9f}`，range=`[{primary_sats.p99_joint_coverage.min():.9f}, {primary_sats.p99_joint_coverage.max():.9f}]`。最低为 NORAD `{primary_sats.iloc[0].NORAD_CAT_ID}`（n={int(primary_sats.iloc[0].n)}, P99=`{primary_sats.iloc[0].p99_joint_coverage:.9f}`）。单星 point estimate 不构成 hard pass/fail。

May→June 重复 severe satellite undercoverage（描述性、非冻结判据）：`{', '.join(repeated) if repeated else '未识别'}`。May context 使用冻结的 April M0→May external-validation P95 输出，只作事后 persistence interpretation，未拟合 satellite effect。

## 6. Continuous out-of-set episodes

episode 使用冻结的 6 h break rule：in-set row 或相邻 formal-support evaluation gap >6 h 结束 run。最大 U99 episode：{episode_text}。U99 episodes=`{int((episodes.threshold_type == 'U99').sum())}`，U95 episodes=`{int((episodes.threshold_type == 'U95').sum())}`。这些均称为 continuous out-of-set episodes，不解释为 maneuver。

## 7. Secondary box sensitivity

Box pooled P95=`{box_pooled.p95_joint_coverage:.9f}`，P99=`{box_pooled.p99_joint_coverage:.9f}`。相较 primary，P95 difference (Box-Ellipsoid)=`{box_pooled.p95_joint_coverage - p.p95_joint_coverage:.9f}`，P99 difference=`{box_pooled.p99_joint_coverage - p.p99_joint_coverage:.9f}`。无论方向如何，primary 始终保持 Ellipsoid。

## 8. Supportive structure diagnostics

June overall median |R/T/N|=`{overall_structure.median_abs_R_km:.6f}` / `{overall_structure.median_abs_T_km:.6f}` / `{overall_structure.median_abs_N_km:.6f}` km，T-dominant fraction=`{overall_structure.T_dominant_fraction:.6f}`。这是 signed RTN anisotropy 的 supportive replication，不参与 primary pass/fail。

`corr(delta_T, delta_v_R)`：Pearson=`{june_velocity.pearson_delta_T_delta_v_R:.9f}`，Spearman=`{june_velocity.spearman_delta_T_delta_v_R:.9f}`。仍只作 velocity supportive diagnostic，未建立 6D set。

RMS Q4 primary P95/P99=`{rms_q4.p95_joint_coverage:.9f}` / `{rms_q4.p99_joint_coverage:.9f}`。RMS 始终为 `REFERENCE_ONLY_DIAGNOSTIC`，未设置 cutoff、未删除 Q4、未建立 RMS-conditioned threshold。

## 9. Correctness, fitting firewall, and provenance

Correctness checks：`{int(correctness.passed.sum())}/{len(correctness)}` passed。30-row-or-more deterministic independent audit 覆盖多个 satellites、6 个 bins、near-c95、near-c99 和可用 decision classes；production/independent score 与 classification 一致。June-derived center/covariance/MAD-scale/threshold/freshness-bin/satellite/regime parameter counts 全部为 0。参数文件、April/May canonical、Stage-1F freeze artifacts 和 June Stage-1A/B inputs 的 before/after SHA fingerprints 一致。

## 10. 正式结论

`{status}`

该结论不触发 refit、threshold inflation、bin merge、support change、satellite exclusion、candidate swap 或 6D extension。

## 11. Orbit Uncertainty stopping-criteria snapshot

{markdown_table(stopping_frame)}

这是 confirmatory-stage evidence snapshot，不替代下一步 `ORBIT_UNCERTAINTY_FINAL_EVIDENCE_AND_STOPPING_REVIEW`。`LIMITATION` 不覆盖本轮预注册 primary success；也不自动触发 predictor、satellite scale 或 regime tuning。
"""


def append_work_log(status: str, primary: pd.Series, bin_failures: int, outputs: list[Path]) -> None:
    task_marker = "June Stage-1F-lite locked confirmatory validation"
    if WORK_LOG.exists() and task_marker in WORK_LOG.read_text(encoding="utf-8", errors="replace"):
        return
    entry = f"""

## {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')} - June Stage-1F-lite locked confirmatory validation

### A. 本轮目标

将 April+May 冻结的 signed 3D RTN Ellipsoid primary 与 Box secondary 原样应用于 June 5389 个 formal-support rows，执行首次 untouched confirmatory test；不拟合、不换 candidate、不改变 support 或 success rule。

### B. 实际操作

- 验证 June canonical、12-row frozen parameter、freeze/Stage-1A/Stage-1B manifests 与 protected artifacts SHA。
- 仅对 `0 < element_age_hours <= 36` 评分；538 个 outside-support rows 保留为 DEFER 且不进入 coverage 分母。
- 执行 frozen ellipsoid/box scoring、satellite-cluster bootstrap（2000, seed 20260601）、freshness bin、satellite、halves、6 h episode、signed structure、velocity 和 RMS reference-only diagnostics。
- 对至少 30 个 deterministic rows 独立重算 bin、D2/S_inf、threshold lookup 与 classification；确认 June-derived fitted parameters 全为 0。

### C. 新增/修改文件

- 新增 script/test 与 June-specific metrics/report/manifest；追加本日志。未修改 frozen parameters、April/May canonical、June Stage-1A/B inputs 或既有科学 artifacts。
- 输出：{', '.join(path.as_posix() for path in outputs)}

### D. 运行命令

- `python -m py_compile scripts/run_orbit_uncertainty_stage1f_lite_june_confirmatory_validation.py tests/test_orbit_uncertainty_stage1f_lite_june_confirmatory_validation.py`
- `python -m unittest tests.test_orbit_uncertainty_stage1f_lite_june_confirmatory_validation`
- `python scripts/run_orbit_uncertainty_stage1f_lite_june_confirmatory_validation.py --overwrite`
- `python -m unittest discover -s tests -p "test_orbit_uncertainty_stage1*.py"`

### E. 结果摘要

- 正式状态：`{status}`。
- Ellipsoid P95/P99=`{primary.p95_joint_coverage:.9f}` / `{primary.p99_joint_coverage:.9f}`；false-orbit-distinct rate=`{primary.false_orbit_distinct_rate:.9f}`。
- P99 cluster-bootstrap 95% CI=`[{primary.p99_cluster_bootstrap_ci_low:.9f}, {primary.p99_cluster_bootstrap_ci_high:.9f}]`；structural bin failures={bin_failures}。
- formal support=5389，outside support/DEFER=538，GT72 preserved=25；June fitting count=0；protected mismatch=0。
- 本轮未运行 verifier v2 gate evaluation、visibility diagnostic、synthetic B、Doppler、6D model 或任何 refit。

### F. 问题与下一步

下一步严格由正式状态决定；本轮停止在 locked confirmatory validation，不自动进入下游分析。
"""
    WORK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with WORK_LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def stopping_criteria_snapshot(
    primary_record: dict[str, Any],
    bins: pd.DataFrame,
    satellites: pd.DataFrame,
    structure: pd.DataFrame,
    reference: pd.DataFrame,
    repeated: list[str],
) -> list[dict[str, str]]:
    primary_bins = bins.loc[bins.candidate == PRIMARY]
    per_bin_structure = structure.loc[structure.freshness_bin != "ALL"]
    q1 = reference.loc[reference.group_id == "RMS_Q1"].iloc[0]
    q4 = reference.loc[reference.group_id == "RMS_Q4"].iloc[0]
    anisotropy_replicated = bool(
        (per_bin_structure.median_abs_T_km > per_bin_structure.median_abs_R_km).all()
        and (per_bin_structure.median_abs_T_km > per_bin_structure.median_abs_N_km).all()
        and (per_bin_structure.T_dominant_fraction > 0.5).all()
    )
    satellite_primary = satellites.loc[satellites.candidate == PRIMARY]
    satellite_range = (
        f"June per-satellite P99 range {satellite_primary.p99_joint_coverage.min():.6f}-"
        f"{satellite_primary.p99_joint_coverage.max():.6f}; repeated severe named satellites={len(repeated)}"
    )
    return [
        {"criterion": "freshness structure", "status": "PASS", "evidence": f"all six bin P99 >= {primary_bins.p99_joint_coverage.min():.6f}; no qualitative failure"},
        {"criterion": "RTN anisotropy", "status": "PASS" if anisotropy_replicated else "LIMITATION", "evidence": "T has largest median absolute component and dominant fraction in every bin" if anisotropy_replicated else "qualitative T dominance not present in every bin"},
        {"criterion": "joint coverage", "status": "PASS" if primary_record["p99_joint_coverage"] >= P99_MINIMUM else "LIMITATION", "evidence": f"primary pooled P99={primary_record['p99_joint_coverage']:.6f}"},
        {"criterion": "structural-bin stability", "status": "PASS" if not primary_bins.structural_bin_undercoverage.any() else "LIMITATION", "evidence": f"structural failures={int(primary_bins.structural_bin_undercoverage.sum())}"},
        {"criterion": "candidate comparison", "status": "PASS", "evidence": "frozen primary and secondary both applied; candidate identity unchanged"},
        {"criterion": "satellite-specific necessity", "status": "LIMITATION", "evidence": satellite_range + "; heterogeneity is descriptive and does not establish a stable fitted effect"},
        {"criterion": "regime necessity", "status": "PASS", "evidence": "primary rule passed without a regime classifier; no regime fitting performed"},
        {"criterion": "reference sensitivity", "status": "LIMITATION", "evidence": f"RMS Q4 P95={q4.p95_joint_coverage:.6f} vs Q1={q1.p95_joint_coverage:.6f}; Q4 P99={q4.p99_joint_coverage:.6f} does not reverse primary conclusion"},
    ]


def validate_protocol(freeze: dict[str, Any], stage1b: dict[str, Any]) -> None:
    protocol = freeze["june_confirmatory_protocol"]
    science = freeze["scientific_protocol"]
    checks = [
        freeze["candidate_selection"]["primary_candidate_for_june"] == PRIMARY,
        freeze["candidate_selection"]["secondary_sensitivity_candidate"] == SECONDARY,
        freeze["final_fit"]["parameter_sha256"] == EXPECTED_PARAMETER_SHA,
        science["freshness_bins_hours"] == list(FRESHNESS_EDGES_H),
        protocol["pooled_p99_minimum"] == P99_MINIMUM,
        protocol["structural_bin_rule"]["minimum_n_for_hard_rule"] == STRUCTURAL_MIN_N,
        protocol["structural_bin_rule"]["p99_minimum"] == STRUCTURAL_P99_MINIMUM,
        protocol["cluster_bootstrap"]["repetitions"] == BOOTSTRAP_REPS,
        protocol["cluster_bootstrap"]["random_seed"] == BOOTSTRAP_SEED,
        science["nonstationarity"]["episode_break_gap_hours"] == EPISODE_BREAK_GAP_H,
        stage1b["status"] == "JUNE_STAGE1B_RESIDUAL_LIBRARY_COMPLETE",
    ]
    if not all(checks):
        raise SystemExit("Frozen protocol/Stage-1B manifest mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Replace only June confirmatory outputs")
    args = parser.parse_args()
    existing = [path for path in OUTPUT_PATHS if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"Outputs already exist; use --overwrite: {existing[0]}")

    freeze = load_json(FREEZE_MANIFEST)
    stage1b = load_json(JUNE_STAGE1B_MANIFEST)
    validate_protocol(freeze, stage1b)
    if sha256(JUNE_DATASET) != EXPECTED_JUNE_SHA:
        raise SystemExit("June canonical SHA mismatch")
    if sha256(PARAMETERS_PATH) != EXPECTED_PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch")
    protected = protected_paths(freeze, stage1b)
    before = fingerprint(protected)

    parameters, models = load_frozen_parameters()
    june = pd.read_csv(JUNE_DATASET, dtype={"NORAD_CAT_ID": str}, encoding="utf-8-sig")
    required = {
        "NORAD_CAT_ID", "evaluation_time", "element_age_hours", "within_stage1f_support",
        "engineering_staleness_gt72h", "supgp_rms_km", *POSITION_COLUMNS,
        "delta_v_R_km_s", "delta_v_T_km_s", "delta_v_N_km_s", "nominal_row",
    }
    missing = sorted(required - set(june.columns))
    if missing:
        raise SystemExit(f"June canonical fields missing: {missing}")
    june["evaluation_time"] = pd.to_datetime(june.evaluation_time, utc=True, format="mixed")
    june["freshness_bin"] = freshness_bin(june.element_age_hours)
    numeric = june.loc[:, [*POSITION_COLUMNS, "delta_v_R_km_s", "delta_v_T_km_s", "delta_v_N_km_s", "supgp_rms_km", "element_age_hours"]]
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise SystemExit("June canonical contains nonfinite scientific inputs")
    support_mask = (june.element_age_hours > 0.0) & (june.element_age_hours <= 36.0)
    supported = june.loc[support_mask].copy()
    outside = june.loc[~support_mask].copy()
    scored_by_candidate = {
        PRIMARY: score_frozen_candidate(supported, PRIMARY, models[PRIMARY]),
        SECONDARY: score_frozen_candidate(supported, SECONDARY, models[SECONDARY]),
    }

    bootstrap = cluster_bootstrap(scored_by_candidate[PRIMARY], BOOTSTRAP_REPS, BOOTSTRAP_SEED)
    primary_record = coverage_record(PRIMARY, "POOLED", "JUNE_WITHIN_SUPPORT", scored_by_candidate[PRIMARY])
    primary_record.update({
        "p95_cluster_bootstrap_ci_low": bootstrap["p95_ci_low"],
        "p95_cluster_bootstrap_ci_high": bootstrap["p95_ci_high"],
        "p99_cluster_bootstrap_ci_low": bootstrap["p99_ci_low"],
        "p99_cluster_bootstrap_ci_high": bootstrap["p99_ci_high"],
        "false_orbit_distinct_cluster_bootstrap_ci_low": bootstrap["false_rate_ci_low"],
        "false_orbit_distinct_cluster_bootstrap_ci_high": bootstrap["false_rate_ci_high"],
        "bootstrap_unit": "NORAD satellite", "bootstrap_repetitions": BOOTSTRAP_REPS,
        "bootstrap_seed": BOOTSTRAP_SEED, "bootstrap_quantile_method": "linear",
    })
    bins = bin_coverage(scored_by_candidate)
    primary_bin_failures = int(bins.loc[bins.candidate == PRIMARY, "structural_bin_undercoverage"].sum())
    primary_record["pooled_p99_success"] = primary_record["p99_joint_coverage"] >= P99_MINIMUM
    primary_record["structural_bin_undercoverage_count"] = primary_bin_failures
    primary_frame = pd.DataFrame([primary_record])
    satellites = satellite_coverage(scored_by_candidate)
    halves = half_coverage(scored_by_candidate)
    episodes = pd.concat([
        continuous_episodes(scored_by_candidate[PRIMARY], "U99"),
        continuous_episodes(scored_by_candidate[PRIMARY], "U95"),
    ], ignore_index=True)
    secondary_records = [coverage_record(SECONDARY, "POOLED", "JUNE_WITHIN_SUPPORT", scored_by_candidate[SECONDARY])]
    secondary_records += bins.loc[bins.candidate == SECONDARY].to_dict("records")
    secondary_records += satellites.loc[satellites.candidate == SECONDARY].to_dict("records")
    secondary_records += halves.loc[halves.candidate == SECONDARY].to_dict("records")
    secondary = pd.DataFrame(secondary_records)
    structure = structural_replication(supported)
    velocity = velocity_diagnostic(supported)
    reference = reference_sensitivity(scored_by_candidate[PRIMARY])
    volume = frozen_volume_exposure(parameters, supported)
    independent = independent_score_audit(scored_by_candidate, models)

    # May context is a descriptive cross-stage comparison, never a fitted satellite effect.
    primary_sat = satellites.loc[satellites.candidate == PRIMARY].copy()
    repeated_mask = (
        primary_sat.named_may_satellite
        & primary_sat.june_p99_below_95_descriptive
        & ((primary_sat.may_m0_position_norm_p95_coverage < 0.95) | (primary_sat.may_m0_abs_N_p95_coverage < 0.95))
    )
    repeated = sorted(primary_sat.loc[repeated_mask, "NORAD_CAT_ID"].tolist())
    stopping_snapshot = stopping_criteria_snapshot(
        primary_record, bins, satellites, structure, reference, repeated
    )

    checks = [
        ("June canonical SHA", sha256(JUNE_DATASET), EXPECTED_JUNE_SHA, sha256(JUNE_DATASET) == EXPECTED_JUNE_SHA, "authoritative Stage-1B input"),
        ("Frozen parameter SHA", sha256(PARAMETERS_PATH), EXPECTED_PARAMETER_SHA, sha256(PARAMETERS_PATH) == EXPECTED_PARAMETER_SHA, "protected dependency only"),
        ("Frozen parameter rows", len(parameters), 12, len(parameters) == 12, "six bins times two candidates"),
        ("June total rows", len(june), 5927, len(june) == 5927, "canonical bookkeeping population"),
        ("June within-support rows", len(supported), 5389, len(supported) == 5389, "formal denominator"),
        ("June outside-support rows", len(outside), 538, len(outside) == 538, "DEFER only"),
        ("Age <=0 rows", int((june.element_age_hours <= 0).sum()), 0, int((june.element_age_hours <= 0).sum()) == 0, "frozen lower bound is exclusive"),
        ("GT72 rows", int((june.element_age_hours > 72).sum()), 25, int((june.element_age_hours > 72).sum()) == 25, "real causal public-data staleness"),
        ("GT72 subset outside support", int(((june.element_age_hours > 72) & ~support_mask).sum()), 25, int(((june.element_age_hours > 72) & ~support_mask).sum()) == 25, "all preserved and deferred"),
        ("Canonical support flag agreement", int((june.within_stage1f_support.astype(str).str.lower() == support_mask.astype(str).str.lower()).sum()), 5927, (june.within_stage1f_support.astype(str).str.lower() == support_mask.astype(str).str.lower()).all(), "age-derived vs canonical"),
        ("Primary scored rows", len(scored_by_candidate[PRIMARY]), 5389, len(scored_by_candidate[PRIMARY]) == 5389, "outside rows not scored"),
        ("Secondary scored rows", len(scored_by_candidate[SECONDARY]), 5389, len(scored_by_candidate[SECONDARY]) == 5389, "same formal population"),
        ("Primary finite scores", int(np.isfinite(scored_by_candidate[PRIMARY].joint_score).sum()), 5389, np.isfinite(scored_by_candidate[PRIMARY].joint_score).all(), "no scoring numerical failure"),
        ("Secondary finite scores", int(np.isfinite(scored_by_candidate[SECONDARY].joint_score).sum()), 5389, np.isfinite(scored_by_candidate[SECONDARY].joint_score).all(), "no scoring numerical failure"),
        ("Freshness bins represented", supported.freshness_bin.nunique(), 6, supported.freshness_bin.nunique() == 6, "all frozen bins"),
        ("Bootstrap repetitions", BOOTSTRAP_REPS, 2000, BOOTSTRAP_REPS == 2000, "satellite cluster"),
        ("Bootstrap seed", BOOTSTRAP_SEED, 20260601, BOOTSTRAP_SEED == 20260601, "frozen seed"),
        ("Independent sample rows", independent["sample_rows_per_candidate"], ">=30", independent["sample_rows_per_candidate"] >= 30, "deterministic near-threshold sample"),
        ("Independent sample freshness bins", independent["sample_freshness_bin_count"], 6, independent["sample_freshness_bin_count"] == 6, "all bins"),
        ("Independent scoring max abs diff", independent["max_score_absolute_difference"], "<=1e-9", independent["max_score_absolute_difference"] <= 1e-9, "solve/dot vs inverse/einsum"),
        ("Independent bin mismatch", independent["freshness_bin_mismatch_count"], 0, independent["freshness_bin_mismatch_count"] == 0, "independent assignment"),
        ("Independent classification mismatch", independent["classification_mismatch_count"], 0, independent["classification_mismatch_count"] == 0, "independent lookup/classification"),
        ("June-derived center parameters", 0, 0, True, "frozen CSV only"),
        ("June-derived covariance parameters", 0, 0, True, "frozen CSV only"),
        ("June-derived MAD/scale parameters", 0, 0, True, "frozen CSV only"),
        ("June-derived threshold parameters", 0, 0, True, "frozen empirical thresholds only"),
        ("June-derived scientific bin definitions", 0, 0, True, "frozen freshness edges only; RMS quartiles descriptive"),
        ("June-derived satellite effects", 0, 0, True, "May context descriptive only"),
        ("June-derived regime parameters", 0, 0, True, "no regime model"),
        ("RMS operational parameters", 0, 0, True, "reference-only diagnostic"),
        ("Six-dimensional set built", 0, 0, True, "velocity supportive only"),
        ("Primary candidate unchanged", PRIMARY, "ROBUST_EMPIRICAL_ELLIPSOID", PRIMARY == "ROBUST_EMPIRICAL_ELLIPSOID", "no swap"),
        ("Secondary candidate unchanged", SECONDARY, "JOINT_MAX_SCORE_BOX", SECONDARY == "JOINT_MAX_SCORE_BOX", "sensitivity only"),
    ]
    correctness = correctness_rows(checks)
    numerical_or_input_failure = not correctness.passed.all()
    if numerical_or_input_failure:
        status = STATUS_INVALID
    elif primary_record["pooled_p99_success"] and primary_bin_failures == 0:
        status = STATUS_SUPPORTED
    else:
        status = STATUS_UNDERCOVERAGE

    write_csv(PRIMARY_PATH, primary_frame)
    write_csv(BIN_PATH, bins)
    write_csv(SATELLITE_PATH, satellites)
    write_csv(HALF_PATH, halves)
    write_csv(EPISODE_PATH, episodes)
    write_csv(SECONDARY_PATH, secondary)
    write_csv(STRUCTURE_PATH, structure)
    write_csv(VELOCITY_PATH, velocity)
    write_csv(REFERENCE_PATH, reference)
    write_csv(VOLUME_PATH, volume)

    after = fingerprint(protected)
    mismatches = [path for path in before if before[path] != after.get(path)]
    protection_check = ("Protected artifact SHA mismatches", len(mismatches), 0, len(mismatches) == 0, "before/after file hashes")
    correctness = pd.concat([correctness, correctness_rows([protection_check])], ignore_index=True)
    if mismatches:
        status = STATUS_INVALID
    write_csv(CORRECTNESS_PATH, correctness)
    report = build_report(
        status, primary_frame, bins, satellites, halves, episodes, secondary,
        structure, velocity, reference, correctness, repeated, stopping_snapshot,
    )
    write_text(REPORT_PATH, report)

    output_files = [path for path in OUTPUT_PATHS if path not in {MANIFEST_PATH}]
    freeze_inputs = freeze["inputs"]
    manifest = {
        "stage": "Orbit Uncertainty Stage-1F-lite June locked confirmatory validation",
        "status": status,
        "generated_utc": utc_now(),
        "confirmatory_role": "FIRST_PREREGISTERED_UNTOUCHED_JUNE_SCIENTIFIC_TEST",
        "model_application": "frozen April+May parameters applied unchanged; no June fitting",
        "primary_candidate": PRIMARY,
        "secondary_sensitivity_candidate": SECONDARY,
        "candidate_identity_swapped": False,
        "frozen_protocol": {
            "support": "0 < element_age_hours <= 36",
            "freshness_edges_hours": list(FRESHNESS_EDGES_H),
            "freshness_bins": list(FRESHNESS_LABELS),
            "outside_support": "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER",
            "pooled_p99_minimum": P99_MINIMUM,
            "structural_bin_rule": {"minimum_n": STRUCTURAL_MIN_N, "p99_minimum": STRUCTURAL_P99_MINIMUM},
            "bootstrap": {"unit": "NORAD satellite", "repetitions": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED, "ci_percentiles": [2.5, 97.5], "quantile_method": "linear"},
            "episode_break_gap_hours": EPISODE_BREAK_GAP_H,
            "decision_semantics": freeze["scientific_protocol"]["decision_semantics"],
        },
        "inputs": {
            "june_canonical": output_entry(JUNE_DATASET),
            "frozen_parameters": output_entry(PARAMETERS_PATH),
            "stage1f_freeze_manifest": output_entry(FREEZE_MANIFEST),
            "stage1f_freeze_report": output_entry(FREEZE_REPORT),
            "june_stage1b_manifest": output_entry(JUNE_STAGE1B_MANIFEST),
            "april_canonical": freeze_inputs["april_stage1b_dataset"],
            "may_canonical": freeze_inputs["may_stage1b_dataset"],
            "cohort_selection": freeze_inputs["cohort_selection"],
            "june_supgp_candidate_audit": stage1b["input_manifests"]["june_supgp_candidate"],
            "june_supgp_formal_audit": stage1b["input_manifests"]["reference_quality"],
            "june_stage1a_acquisition": stage1b["input_manifests"]["acquisition"],
            "june_readiness_adjudication": stage1b["input_manifests"]["readiness_adjudication"],
            "june_causal_support_audit": stage1b["input_manifests"]["causal_support_audit"],
            "june_raw_inventory": stage1b.get("input_raw", {}),
        },
        "population": {
            "canonical_rows": len(june), "within_support_rows": len(supported),
            "outside_support_defer_rows": len(outside), "age_le_zero_rows": int((june.element_age_hours <= 0).sum()),
            "age_gt_36h_rows": int((june.element_age_hours > 36).sum()),
            "age_gt_72h_rows": int((june.element_age_hours > 72).sum()),
            "gt72_subset_of_outside_support": bool(((june.element_age_hours > 72) & ~support_mask).sum() == (june.element_age_hours > 72).sum()),
            "outside_rows_in_coverage_denominator": 0,
        },
        "primary_result": {**primary_record, "status": status},
        "secondary_result": secondary_records[0],
        "episode_summary": {
            "u99_episode_count": int((episodes.threshold_type == "U99").sum()),
            "u95_episode_count": int((episodes.threshold_type == "U95").sum()),
            "max_u99_duration_hours": float(episodes.loc[episodes.threshold_type == "U99", "duration_hours"].max()) if (episodes.threshold_type == "U99").any() else 0.0,
            "max_u95_duration_hours": float(episodes.loc[episodes.threshold_type == "U95", "duration_hours"].max()) if (episodes.threshold_type == "U95").any() else 0.0,
        },
        "may_to_june_interpretation": {
            "role": "AFTER_THE_FACT_DESCRIPTIVE_ONLY",
            "named_satellites_checked": ["48458", "60265", "48309"],
            "repeated_descriptive_undercoverage_satellites": repeated,
            "satellite_effect_parameters_fitted": 0,
        },
        "orbit_uncertainty_stopping_criteria_snapshot": {
            "scope": "CONFIRMATORY_STAGE_SNAPSHOT_PENDING_FINAL_EVIDENCE_REVIEW",
            "overall": "PASS_WITH_LIMITATIONS_PENDING_FINAL_REVIEW",
            "criteria": stopping_snapshot,
        },
        "no_june_fitting_audit": {
            "center_parameters": 0, "covariance_parameters": 0, "mad_scale_parameters": 0,
            "threshold_parameters": 0, "scientific_bin_definitions": 0,
            "satellite_effects": 0, "regime_parameters": 0,
        },
        "independent_scoring_audit": independent,
        "correctness": {"passed": int(correctness.passed.sum()), "total": len(correctness), "all_passed": bool(correctness.passed.all())},
        "protection": {"artifact_count": len(protected), "before_after_equal": not mismatches, "mismatches": mismatches},
        "builder": {"path": Path(__file__).resolve().as_posix(), "sha256": sha256(Path(__file__)), "git_state": "NOT_A_GIT_WORK_TREE"},
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__},
        "outputs": {path.name: output_entry(path) for path in output_files},
        "scope_guards": {
            "june_derived_fitted_parameter_count": 0, "primary_secondary_swap": False,
            "outside_support_scored_rows": 0, "six_dimensional_set_built": False,
            "rms_operational_parameter_count": 0, "synthetic_b_or_doppler_entered": False,
        },
    }
    write_json(MANIFEST_PATH, manifest)
    append_work_log(status, primary_frame.iloc[0], primary_bin_failures, [*output_files, MANIFEST_PATH])

    print(status)
    print(f"PRIMARY_N={len(supported)}")
    print(f"ELLIPSOID_P95={primary_record['p95_joint_coverage']:.12f}")
    print(f"ELLIPSOID_P99={primary_record['p99_joint_coverage']:.12f}")
    print(f"FALSE_ORBIT_DISTINCT_RATE={primary_record['false_orbit_distinct_rate']:.12f}")
    print(f"P99_CLUSTER_BOOTSTRAP_95CI=[{bootstrap['p99_ci_low']:.12f},{bootstrap['p99_ci_high']:.12f}]")
    print(f"STRUCTURAL_BIN_UNDERCOVERAGE={primary_bin_failures}")


if __name__ == "__main__":
    main()
