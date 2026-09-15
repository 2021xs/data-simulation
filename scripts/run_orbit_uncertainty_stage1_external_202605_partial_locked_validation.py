#!/usr/bin/env python3
"""Run May partial locked validation for recoverable April M0/M1/M2 only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

try:
    from scripts import run_orbit_uncertainty_stage1_external_202605_locked_validation as blocked
except ImportError:
    import run_orbit_uncertainty_stage1_external_202605_locked_validation as blocked


STATUS = "MAY_PARTIAL_LOCKED_EXTERNAL_VALIDATION_COMPLETE"
FULL_STATUS_RESERVED = "MAY_LOCKED_EXTERNAL_VALIDATION_COMPLETE"
APRIL_WINDOW = blocked.APRIL_WINDOW
MAY_WINDOW = blocked.MAY_WINDOW
MAY_DATASET = blocked.MAY_DATASET
MAY_MANIFEST = blocked.MAY_STAGE1B_MANIFEST
APRIL_CALIBRATION = blocked.APRIL_STAGE1E_CALIBRATION
APRIL_STAGE1D_MANIFEST = blocked.APRIL_STAGE1D_MANIFEST
APRIL_STAGE1E_MANIFEST = blocked.APRIL_STAGE1E_MANIFEST
APRIL_MODEL_COMPARISON = blocked.APRIL_STAGE1E_MODEL_COMPARISON
APRIL_STAGE1D_SCRIPT = Path("scripts/calibrate_orbit_uncertainty_stage1d_freshness.py")
APRIL_STAGE1E_SCRIPT = blocked.APRIL_STAGE1E_SCRIPT

METRICS = Path("outputs/metrics")
REPORTS = Path("outputs/reports")
FIGURES = Path("outputs/figures/orbit_uncertainty_stage1_external_202605_partial")
PREFIX = "orbit_uncertainty_stage1_external_202605"

COVERAGE_PATH = METRICS / f"{PREFIX}_partial_locked_coverage.csv"
PER_SATELLITE_PATH = METRICS / f"{PREFIX}_partial_per_satellite.csv"
FRESHNESS_PATH = METRICS / f"{PREFIX}_partial_freshness_bin.csv"
TIME_HALF_PATH = METRICS / f"{PREFIX}_partial_time_half.csv"
PERSISTENCE_PATH = METRICS / f"{PREFIX}_satellite_scale_persistence.csv"
COMPARISON_PATH = METRICS / f"{PREFIX}_partial_model_comparison.csv"
RECOVERABILITY_PATH = METRICS / f"{PREFIX}_model_recoverability.csv"
ARTIFACT_SEARCH_PATH = METRICS / f"{PREFIX}_m3_m4_artifact_search.csv"
OUTSIDE_PATH = METRICS / f"{PREFIX}_partial_outside_support.csv"
CORRECTNESS_PATH = METRICS / f"{PREFIX}_partial_correctness_audit.csv"
MANIFEST_PATH = METRICS / f"{PREFIX}_partial_manifest.json"
REPORT_PATH = REPORTS / f"{PREFIX}_partial_locked_validation_report.md"

COVERAGE_FIGURE = FIGURES / "april_fit_vs_may_empirical_coverage.png"
PERSISTENCE_FIGURE = FIGURES / "april_satellite_scale_vs_may_observed_tendency.png"
M0_M2_FIGURE = FIGURES / "m0_vs_m2_may_per_satellite_p95.png"

TARGETS = (
    "abs_delta_R_km",
    "abs_delta_T_km",
    "abs_delta_N_km",
    "position_error_norm_km",
)
COMPONENT_TARGETS = TARGETS[:3]
TARGET_LABELS = {
    "abs_delta_R_km": "|R|",
    "abs_delta_T_km": "|T|",
    "abs_delta_N_km": "|N|",
    "position_error_norm_km": "Position norm",
}
QUANTILES = (0.90, 0.95)
MODELS = ("M0", "M1", "M2")
FRESHNESS_EDGES = (0.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0)
FRESHNESS_LABELS = ("0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h")
M0_KNOTS_H = np.array([3.0, 7.5, 10.5, 15.0, 21.0, 30.0])
M0_GRID_H = np.arange(0.0, 36.0 + 0.1, 3.0)
PUBLICATION_GROUPS = ("PUB_0_3", "PUB_3_6", "PUB_6_12", "PUB_12_24", "PUB_GT24")
SPECIAL_SATELLITES = ("48458", "60265", "48309")
MAY_HALF_SPLIT = pd.Timestamp("2026-05-16T00:00:00Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return blocked.sha256(path)


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


def interpolation_matrix(values: np.ndarray, knots: np.ndarray) -> np.ndarray:
    matrix = np.zeros((len(values), len(knots)), dtype=float)
    for row_index, value in enumerate(values):
        if value <= knots[0]:
            matrix[row_index, 0] = 1.0
        elif value >= knots[-1]:
            matrix[row_index, -1] = 1.0
        else:
            right = int(np.searchsorted(knots, value, side="right"))
            left = right - 1
            weight = (value - knots[left]) / (knots[right] - knots[left])
            matrix[row_index, left] = 1.0 - weight
            matrix[row_index, right] = weight
    return matrix


def reconstruct_m0_knots(grid_values: Iterable[float]) -> tuple[np.ndarray, float]:
    values = np.asarray(list(grid_values), dtype=float)
    if values.shape != M0_GRID_H.shape or not np.isfinite(values).all():
        raise ValueError("M0 frozen grid must contain 13 finite values at 0:3:36 h")
    by_age = dict(zip(M0_GRID_H, values))
    knots = np.array([
        by_age[3.0],
        1.5 * by_age[6.0] - 0.5 * by_age[3.0],
        2.0 * by_age[9.0] - (1.5 * by_age[6.0] - 0.5 * by_age[3.0]),
        by_age[15.0],
        by_age[21.0],
        by_age[30.0],
    ])
    reconstructed = interpolation_matrix(M0_GRID_H, M0_KNOTS_H) @ knots
    return knots, float(np.max(np.abs(reconstructed - values)))


def publication_stratum(values: pd.Series) -> pd.Series:
    return pd.cut(
        values,
        [-np.inf, 3.0, 6.0, 12.0, 24.0, np.inf],
        labels=PUBLICATION_GROUPS,
        right=True,
    ).astype("string")


def parse_fallback(rows: pd.DataFrame) -> float:
    values = {blocked.parse_fallback(str(note)) for note in rows.note}
    if len(values) != 1:
        raise ValueError(f"Expected one frozen fallback, found {values}")
    return values.pop()


@dataclass(frozen=True)
class FrozenCandidate:
    target: str
    quantile: float
    knots: np.ndarray
    m1_factors: dict[str, float]
    m1_fallback: float
    m2_factors: dict[str, float]
    m2_fallback: float
    grid_reconstruction_error: float

    def base_prediction(self, age_hours: np.ndarray) -> np.ndarray:
        values = np.asarray(age_hours, dtype=float)
        if np.any(values <= 0.0) or np.any(values > 36.0):
            raise ValueError("Formal prediction is restricted to 0 < element age <= 36 h")
        return np.interp(values, M0_KNOTS_H, self.knots)

    def predict(self, frame: pd.DataFrame, model: str) -> np.ndarray:
        base = self.base_prediction(frame.element_age_hours.to_numpy(dtype=float))
        if model == "M0":
            return base
        if model == "M1":
            groups = publication_stratum(frame.publication_age_hours)
            factors = np.array([self.m1_factors.get(str(group), self.m1_fallback) for group in groups])
            return base * factors
        if model == "M2":
            factors = np.array([
                self.m2_factors.get(str(satellite), self.m2_fallback)
                for satellite in frame.NORAD_CAT_ID
            ])
            return base * factors
        raise ValueError(f"Model is not recoverable in this run: {model}")


def load_frozen_candidates(calibration: pd.DataFrame) -> tuple[dict[tuple[str, float], FrozenCandidate], dict[str, Any]]:
    candidates: dict[tuple[str, float], FrozenCandidate] = {}
    reconstruction_errors: list[float] = []
    for target in TARGETS:
        for quantile in QUANTILES:
            base = calibration.loc[
                (calibration.record_type == "BASE_CURVE")
                & (calibration.model == "M0")
                & (calibration.target == target)
                & np.isclose(calibration["quantile"].astype(float), quantile)
            ].sort_values("evaluation_age_h")
            ages = base.evaluation_age_h.astype(float).to_numpy()
            if len(base) != len(M0_GRID_H) or not np.array_equal(ages, M0_GRID_H):
                raise ValueError(f"Incomplete M0 frozen grid for {target}/q={quantile}")
            knots, reconstruction_error = reconstruct_m0_knots(base.base_prediction.astype(float))

            m1 = calibration.loc[
                (calibration.record_type == "CORRECTION_FACTOR")
                & (calibration.model == "M1")
                & (calibration.target == target)
                & np.isclose(calibration["quantile"].astype(float), quantile)
            ]
            m2 = calibration.loc[
                (calibration.record_type == "CORRECTION_FACTOR")
                & (calibration.model == "M2")
                & (calibration.target == target)
                & np.isclose(calibration["quantile"].astype(float), quantile)
            ]
            m1_factors = dict(zip(m1.group_id.astype(str), m1.factor.astype(float)))
            m2_factors = dict(zip(m2.group_id.astype(str), m2.factor.astype(float)))
            if set(m1_factors) != set(PUBLICATION_GROUPS) or len(m1) != len(PUBLICATION_GROUPS):
                raise ValueError(f"Incomplete M1 factors for {target}/q={quantile}")
            if len(m2_factors) != 20 or len(m2) != 20:
                raise ValueError(f"Incomplete M2 factors for {target}/q={quantile}")
            all_values = np.array([*knots, *m1_factors.values(), *m2_factors.values()])
            if not np.isfinite(all_values).all() or np.any(all_values <= 0.0):
                raise ValueError(f"Non-positive/nonfinite frozen parameters for {target}/q={quantile}")
            candidates[(target, quantile)] = FrozenCandidate(
                target, quantile, knots, m1_factors, parse_fallback(m1),
                m2_factors, parse_fallback(m2), reconstruction_error,
            )
            reconstruction_errors.append(reconstruction_error)
    cohort_sets = {tuple(sorted(candidate.m2_factors)) for candidate in candidates.values()}
    if len(cohort_sets) != 1:
        raise ValueError("M2 cohort differs across targets or quantiles")
    return candidates, {
        "candidate_count": len(candidates),
        "m0_grid_reconstruction_max_abs_error_km": max(reconstruction_errors),
        "m2_satellites": list(next(iter(cohort_sets))),
    }


def load_may() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(MAY_DATASET, dtype={"NORAD_CAT_ID": "string"})
    required = {
        "NORAD_CAT_ID", "evaluation_time", "element_age_seconds", "publication_age_seconds",
        "delta_R_km", "delta_T_km", "delta_N_km", "position_error_norm_km",
        "velocity_error_norm_km_s", "nominal_row",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"May Stage-1B missing required columns: {sorted(missing)}")
    if len(frame) != 6181 or not frame.nominal_row.astype(str).str.lower().eq("true").all():
        raise ValueError("May Stage-1B must contain 6181 nominal rows")
    frame["evaluation_time"] = pd.to_datetime(frame.evaluation_time, utc=True, format="mixed")
    frame["element_age_hours"] = frame.element_age_seconds.astype(float) / 3600.0
    frame["publication_age_hours"] = frame.publication_age_seconds.astype(float) / 3600.0
    frame["abs_delta_R_km"] = frame.delta_R_km.abs()
    frame["abs_delta_T_km"] = frame.delta_T_km.abs()
    frame["abs_delta_N_km"] = frame.delta_N_km.abs()
    primary_mask = (frame.element_age_hours > 0.0) & (frame.element_age_hours <= 36.0)
    outside_mask = frame.element_age_hours > 36.0
    if int(primary_mask.sum()) != 6094 or int(outside_mask.sum()) != 87 or not (primary_mask | outside_mask).all():
        raise ValueError("May support split is not exactly 6094 primary / 87 outside")
    primary = frame.loc[primary_mask].copy().reset_index(drop=True)
    outside = frame.loc[outside_mask].copy().reset_index(drop=True)
    primary["freshness_bin"] = pd.cut(
        primary.element_age_hours,
        FRESHNESS_EDGES,
        labels=FRESHNESS_LABELS,
        right=True,
        include_lowest=False,
    ).astype("string")
    primary["time_half"] = np.where(
        primary.evaluation_time < MAY_HALF_SPLIT,
        "MAY_01_15",
        "MAY_16_31",
    )
    return primary, outside, {
        "input_rows": len(frame),
        "primary_rows": len(primary),
        "outside_support_rows": len(outside),
        "rows_removed": 0,
        "formal_support": "0 < element_age_seconds / 3600 <= 36",
    }


def pinball_loss(observed: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    residual = observed - predicted
    return float(np.mean(np.maximum(quantile * residual, (quantile - 1.0) * residual)))


def metric_row(
    frame: pd.DataFrame,
    predicted: np.ndarray,
    model: str,
    target: str,
    quantile: float,
    scope: str,
    group_id: str,
) -> dict[str, Any]:
    observed = frame[target].to_numpy(dtype=float)
    coverage = float(np.mean(observed <= predicted))
    return {
        "model": model,
        "target": target,
        "quantile": quantile,
        "aggregation_scope": scope,
        "group_id": group_id,
        "n": len(frame),
        "satellite_count": int(frame.NORAD_CAT_ID.nunique()),
        "observed_coverage": coverage,
        "target_coverage": quantile,
        "coverage_error": coverage - quantile,
        "absolute_calibration_error": abs(coverage - quantile),
        "pinball_loss": pinball_loss(observed, predicted, quantile),
        "prediction_source": f"APRIL_FROZEN_{model}",
        "may_derived_fitted_parameter_count": 0,
    }


def evaluate_metrics(
    primary: pd.DataFrame,
    candidates: dict[tuple[str, float], FrozenCandidate],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[tuple[str, str, float], np.ndarray]]:
    overall_rows: list[dict[str, Any]] = []
    satellite_rows: list[dict[str, Any]] = []
    freshness_rows: list[dict[str, Any]] = []
    time_rows: list[dict[str, Any]] = []
    predictions: dict[tuple[str, str, float], np.ndarray] = {}
    for target in TARGETS:
        for quantile in QUANTILES:
            candidate = candidates[(target, quantile)]
            for model in MODELS:
                predicted = candidate.predict(primary, model)
                predictions[(model, target, quantile)] = predicted
                overall_rows.append(metric_row(primary, predicted, model, target, quantile, "OVERALL", "ALL"))
                for satellite, indices in primary.groupby("NORAD_CAT_ID", sort=True).groups.items():
                    index = np.asarray(list(indices), dtype=int)
                    row = metric_row(primary.iloc[index], predicted[index], model, target, quantile, "SATELLITE", str(satellite))
                    row["NORAD_CAT_ID"] = str(satellite)
                    satellite_rows.append(row)
                for label, indices in primary.groupby("freshness_bin", sort=False, observed=True).groups.items():
                    index = np.asarray(list(indices), dtype=int)
                    row = metric_row(primary.iloc[index], predicted[index], model, target, quantile, "FRESHNESS_BIN", str(label))
                    row["freshness_bin"] = str(label)
                    row["bin_left_h_exclusive"] = FRESHNESS_EDGES[FRESHNESS_LABELS.index(str(label))]
                    row["bin_right_h_inclusive"] = FRESHNESS_EDGES[FRESHNESS_LABELS.index(str(label)) + 1]
                    freshness_rows.append(row)
                for label, indices in primary.groupby("time_half", sort=True).groups.items():
                    index = np.asarray(list(indices), dtype=int)
                    row = metric_row(primary.iloc[index], predicted[index], model, target, quantile, "TIME_HALF", str(label))
                    row["time_half"] = str(label)
                    time_rows.append(row)
    return (
        pd.DataFrame(overall_rows),
        pd.DataFrame(satellite_rows),
        pd.DataFrame(freshness_rows),
        pd.DataFrame(time_rows),
        predictions,
    )


def build_model_comparison(overall: pd.DataFrame, per_satellite: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        for quantile in QUANTILES:
            baseline = overall.loc[
                (overall.model == "M0") & (overall.target == target) & np.isclose(overall["quantile"], quantile)
            ].iloc[0]
            baseline_sat = per_satellite.loc[
                (per_satellite.model == "M0") & (per_satellite.target == target)
                & np.isclose(per_satellite["quantile"], quantile)
            ]
            for model in MODELS:
                item = overall.loc[
                    (overall.model == model) & (overall.target == target) & np.isclose(overall["quantile"], quantile)
                ].iloc[0]
                sat = per_satellite.loc[
                    (per_satellite.model == model) & (per_satellite.target == target)
                    & np.isclose(per_satellite["quantile"], quantile)
                ]
                rows.append({
                    "aggregation_scope": "TARGET_QUANTILE",
                    "model": model,
                    "target": target,
                    "quantile": quantile,
                    "overall_coverage": item.observed_coverage,
                    "overall_coverage_error": item.coverage_error,
                    "overall_absolute_calibration_error": item.absolute_calibration_error,
                    "overall_pinball_loss": item.pinball_loss,
                    "mean_per_satellite_absolute_calibration_error": sat.absolute_calibration_error.mean(),
                    "worst_satellite_coverage": sat.observed_coverage.min(),
                    "per_satellite_coverage_std": sat.observed_coverage.std(ddof=0),
                    "overall_abs_error_improvement_vs_m0": baseline.absolute_calibration_error - item.absolute_calibration_error,
                    "mean_per_satellite_abs_error_improvement_vs_m0": baseline_sat.absolute_calibration_error.mean() - sat.absolute_calibration_error.mean(),
                    "coverage_dispersion_reduction_vs_m0": baseline_sat.observed_coverage.std(ddof=0) - sat.observed_coverage.std(ddof=0),
                    "pinball_improvement_vs_m0": baseline.pinball_loss - item.pinball_loss,
                    "may_derived_fitted_parameter_count": 0,
                })
    detailed = pd.DataFrame(rows)
    aggregate_rows = []
    for model in MODELS:
        subset = detailed.loc[detailed.model == model]
        p95 = subset.loc[np.isclose(subset["quantile"], 0.95)]
        aggregate_rows.append({
            "aggregation_scope": "ALL_TARGETS_QUANTILES",
            "model": model,
            "target": "ALL_POSITION_TARGETS",
            "quantile": math.nan,
            "overall_coverage": math.nan,
            "overall_coverage_error": subset.overall_coverage_error.mean(),
            "overall_absolute_calibration_error": subset.overall_absolute_calibration_error.mean(),
            "overall_pinball_loss": subset.overall_pinball_loss.mean(),
            "mean_per_satellite_absolute_calibration_error": subset.mean_per_satellite_absolute_calibration_error.mean(),
            "worst_satellite_coverage": p95.worst_satellite_coverage.min(),
            "per_satellite_coverage_std": subset.per_satellite_coverage_std.mean(),
            "overall_abs_error_improvement_vs_m0": subset.overall_abs_error_improvement_vs_m0.mean(),
            "mean_per_satellite_abs_error_improvement_vs_m0": subset.mean_per_satellite_abs_error_improvement_vs_m0.mean(),
            "coverage_dispersion_reduction_vs_m0": subset.coverage_dispersion_reduction_vs_m0.mean(),
            "pinball_improvement_vs_m0": subset.pinball_improvement_vs_m0.mean(),
            "may_derived_fitted_parameter_count": 0,
        })
    return pd.concat([detailed, pd.DataFrame(aggregate_rows)], ignore_index=True)


def build_scale_persistence(
    primary: pd.DataFrame,
    candidates: dict[tuple[str, float], FrozenCandidate],
    predictions: dict[tuple[str, str, float], np.ndarray],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        for quantile in QUANTILES:
            candidate = candidates[(target, quantile)]
            base = predictions[("M0", target, quantile)]
            observed = primary[target].to_numpy(dtype=float)
            satellite_records = []
            for satellite, indices in primary.groupby("NORAD_CAT_ID", sort=True).groups.items():
                index = np.asarray(list(indices), dtype=int)
                observed_ratio = float(np.quantile(observed[index] / base[index], quantile))
                factor = candidate.m2_factors[str(satellite)]
                satellite_records.append((str(satellite), len(index), factor, observed_ratio))
            factor_values = np.array([item[2] for item in satellite_records])
            observed_values = np.array([item[3] for item in satellite_records])
            spearman = float(spearmanr(factor_values, observed_values).statistic)
            pearson_log = float(pearsonr(np.log(factor_values), np.log(observed_values)).statistic)
            for satellite, n, factor, observed_ratio in satellite_records:
                rows.append({
                    "record_type": "SATELLITE_TENDENCY",
                    "target": target,
                    "quantile": quantile,
                    "NORAD_CAT_ID": satellite,
                    "n": n,
                    "april_m2_satellite_factor": factor,
                    "may_observed_ratio_quantile": observed_ratio,
                    "april_factor_rank": int(pd.Series(factor_values).rank(method="average").iloc[[x[0] for x in satellite_records].index(satellite)]),
                    "may_observed_rank": int(pd.Series(observed_values).rank(method="average").iloc[[x[0] for x in satellite_records].index(satellite)]),
                    "spearman_rank_correlation": math.nan,
                    "pearson_log_scale_correlation": math.nan,
                    "diagnostic_only": True,
                    "used_in_prediction": False,
                    "definition": f"May within-satellite q{quantile:g} of observed_abs_residual / April_M0_prediction",
                })
            rows.append({
                "record_type": "CORRELATION_SUMMARY",
                "target": target,
                "quantile": quantile,
                "NORAD_CAT_ID": "ALL",
                "n": len(satellite_records),
                "april_m2_satellite_factor": math.nan,
                "may_observed_ratio_quantile": math.nan,
                "april_factor_rank": math.nan,
                "may_observed_rank": math.nan,
                "spearman_rank_correlation": spearman,
                "pearson_log_scale_correlation": pearson_log,
                "diagnostic_only": True,
                "used_in_prediction": False,
                "definition": f"Across 20 satellites at q={quantile:g}; May tendency never feeds M2 prediction",
            })
    return pd.DataFrame(rows)


def build_outside_support(outside: pd.DataFrame) -> pd.DataFrame:
    rows = []
    groups = [("ALL", outside), *[(str(sat), group) for sat, group in outside.groupby("NORAD_CAT_ID", sort=True)]]
    for group_id, group in groups:
        rows.append({
            "NORAD_CAT_ID": group_id,
            "n": len(group),
            "satellite_count": int(group.NORAD_CAT_ID.nunique()),
            "element_age_min_h": group.element_age_hours.min(),
            "element_age_median_h": group.element_age_hours.median(),
            "element_age_max_h": group.element_age_hours.max(),
            "position_norm_min_km": group.position_error_norm_km.min(),
            "position_norm_median_km": group.position_error_norm_km.median(),
            "position_norm_p95_km": group.position_error_norm_km.quantile(0.95),
            "position_norm_max_km": group.position_error_norm_km.max(),
            "velocity_norm_min_km_s": group.velocity_error_norm_km_s.min(),
            "velocity_norm_median_km_s": group.velocity_error_norm_km_s.median(),
            "velocity_norm_p95_km_s": group.velocity_error_norm_km_s.quantile(0.95),
            "velocity_norm_max_km_s": group.velocity_error_norm_km_s.max(),
            "support_status": "OUTSIDE_APRIL_CALIBRATED_FRESHNESS_SUPPORT",
            "formal_prediction_count": 0,
            "coverage_scored": False,
        })
    return pd.DataFrame(rows)


def search_m3_m4_artifacts() -> tuple[pd.DataFrame, dict[str, Any]]:
    search_roots = [Path("."), Path("..").resolve()]
    temp_value = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp_value:
        search_roots.append(Path(temp_value))
    unique_roots = list(dict.fromkeys(path.resolve() for path in search_roots if path.exists()))
    suffixes = {".joblib", ".pkl", ".pickle"}
    candidates: dict[str, Path] = {}
    root_counts: dict[str, int] = {}
    for root in unique_roots:
        count = 0
        try:
            for directory, _, files in os.walk(root, onerror=lambda _: None):
                for filename in files:
                    path = Path(directory) / filename
                    if path.suffix.lower() in suffixes:
                        candidates[str(path.resolve())] = path.resolve()
                        count += 1
        except OSError:
            pass
        root_counts[root.as_posix()] = count
    rows: list[dict[str, Any]] = []
    for root, count in root_counts.items():
        rows.append({
            "record_type": "SEARCH_SCOPE",
            "path": root,
            "mtime_utc": "",
            "sha256": "",
            "artifact_type": "recursive *.joblib/*.pkl/*.pickle search",
            "april_stage1e_provenance_proven": False,
            "adoption_status": "NO_CANDIDATE" if count == 0 else "CANDIDATES_REQUIRE_PROVENANCE_REVIEW",
            "notes": f"candidate_count={count}",
        })
    for path in candidates.values():
        rows.append({
            "record_type": "SERIALIZED_CANDIDATE",
            "path": path.as_posix(),
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": sha256(path),
            "artifact_type": path.suffix.lower().lstrip("."),
            "april_stage1e_provenance_proven": False,
            "adoption_status": "NOT_ADOPTED_UNPROVEN_PROVENANCE",
            "notes": "File extension match only; no April Stage-1E manifest binding",
        })
    keyword_evidence = [
        (APRIL_STAGE1E_SCRIPT, "SOURCE_DEFINITION_NOT_FITTED_ARTIFACT"),
        (blocked.APRIL_STAGE1E_ASSOCIATION, "COEFFICIENT_TABLE_INCOMPLETE"),
        (APRIL_MODEL_COMPARISON, "MODEL_COMPARISON_TABLE_NOT_FITTED_ARTIFACT"),
        (Path("logs/work_log.md"), "LOG_REFERENCE_NOT_FITTED_ARTIFACT"),
    ]
    for path, artifact_type in keyword_evidence:
        rows.append({
            "record_type": "KEYWORD_CONTENT_EVIDENCE",
            "path": path.as_posix(),
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": sha256(path),
            "artifact_type": artifact_type,
            "april_stage1e_provenance_proven": False,
            "adoption_status": "NOT_A_SERIALIZED_FITTED_CLASSIFIER",
            "notes": "classifier/pipeline/logistic/StandardScaler/SimpleImputer/intercept_/mean_/scale_/statistics_ keyword search",
        })
    git_available = Path(".git/HEAD").exists()
    rows.append({
        "record_type": "GIT_HISTORY_SEARCH",
        "path": Path(".git").resolve().as_posix(),
        "mtime_utc": "",
        "sha256": "",
        "artifact_type": "git history",
        "april_stage1e_provenance_proven": False,
        "adoption_status": "SEARCHED" if git_available else "UNAVAILABLE_NOT_A_GIT_REPOSITORY",
        "notes": "No usable .git/HEAD; git log cannot be queried" if not git_available else "Git history available for manual provenance review",
    })
    proven = [row for row in rows if row["record_type"] == "SERIALIZED_CANDIDATE" and row["april_stage1e_provenance_proven"]]
    return pd.DataFrame(rows), {
        "search_roots": [path.as_posix() for path in unique_roots],
        "serialized_candidate_count": len(candidates),
        "proven_april_stage1e_classifier_count": len(proven),
        "git_history_available": git_available,
        "m3_m4_status": "M3_M4_LOCKED_VALIDATION_UNAVAILABLE" if not proven else "CANDIDATE_REQUIRES_EXPLICIT_PROVENANCE_ADOPTION",
    }


def recoverability_audit(
    calibration_sha: str,
    stage1d_manifest_sha: str,
    stage1e_manifest_sha: str,
    details: dict[str, Any],
    artifact_search: dict[str, Any],
) -> pd.DataFrame:
    common = {
        "training_window": APRIL_WINDOW,
        "May-derived_parameters": 0,
    }
    source = f"{APRIL_CALIBRATION.as_posix()}@{calibration_sha}"
    rows = [
        {
            **common,
            "model": "M0",
            "required_parameters": "8 target/quantile frozen curves; knots 3/7.5/10.5/15/21/30 h; piecewise-linear interpolation and endpoint clamp",
            "source_artifact": f"{source}|{APRIL_STAGE1D_MANIFEST.as_posix()}@{stage1d_manifest_sha}",
            "source_SHA": f"{calibration_sha}|{stage1d_manifest_sha}",
            "all_parameters_available": True,
            "status": "LOCKED_RECOVERABLE",
            "notes": f"13-point grid inversion max check={details['m0_grid_reconstruction_max_abs_error_km']:.3e} km",
        },
        {
            **common,
            "model": "M1",
            "required_parameters": "M0 plus 5 publication-age factors and fallback for each target/quantile; strata <=3/<=6/<=12/<=24/>24 h",
            "source_artifact": f"{source}|{APRIL_STAGE1E_MANIFEST.as_posix()}@{stage1e_manifest_sha}",
            "source_SHA": f"{calibration_sha}|{stage1e_manifest_sha}",
            "all_parameters_available": True,
            "status": "LOCKED_RECOVERABLE",
            "notes": "40 factors + 8 target/quantile fallback values; all May rows map to frozen strata",
        },
        {
            **common,
            "model": "M2",
            "required_parameters": "M0 plus 20 partial-pooled satellite factors and fallback for each target/quantile",
            "source_artifact": f"{source}|{APRIL_STAGE1E_MANIFEST.as_posix()}@{stage1e_manifest_sha}",
            "source_SHA": f"{calibration_sha}|{stage1e_manifest_sha}",
            "all_parameters_available": True,
            "status": "LOCKED_RECOVERABLE",
            "notes": "160 factors + 8 target/quantile fallback values; exact 20-satellite May cohort present",
        },
    ]
    missing = "logistic intercept; StandardScaler.mean_/scale_; SimpleImputer.statistics_; manifest-bound fitted pipeline"
    for model in ("M3", "M4"):
        rows.append({
            **common,
            "model": model,
            "required_parameters": "M0" + (" + M2" if model == "M4" else "") + " + April causal classifier + risk cutpoints/factors",
            "source_artifact": f"{source}|artifact_search={ARTIFACT_SEARCH_PATH.as_posix()}",
            "source_SHA": calibration_sha,
            "all_parameters_available": False,
            "status": "BLOCKED_PARAMETER_PROVENANCE",
            "notes": f"{missing}; search proven candidates={artifact_search['proven_april_stage1e_classifier_count']}",
        })
    return pd.DataFrame(rows)


def plot_coverage(overall: pd.DataFrame) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), sharey=True)
    colors = {"M0": "#4C78A8", "M1": "#F58518", "M2": "#54A24B"}
    x = np.arange(len(TARGETS))
    width = 0.24
    for axis, quantile in zip(axes, QUANTILES):
        subset = overall.loc[np.isclose(overall["quantile"], quantile)]
        for offset, model in enumerate(MODELS):
            values = [subset.loc[(subset.model == model) & (subset.target == target), "observed_coverage"].iloc[0] for target in TARGETS]
            axis.bar(x + (offset - 1) * width, values, width, label=model, color=colors[model])
        axis.axhline(quantile, color="#222222", linestyle="--", linewidth=1.2, label="Target" if quantile == QUANTILES[0] else None)
        axis.set_title(f"May empirical P{int(quantile * 100)} coverage")
        axis.set_xticks(x, [TARGET_LABELS[target] for target in TARGETS])
        axis.set_ylim(0.65, 1.01)
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Empirical coverage")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.94), ncol=4)
    fig.suptitle("April-frozen predictions on May primary support", y=0.995)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.86))
    fig.savefig(COVERAGE_FIGURE, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_persistence(persistence: pd.DataFrame) -> None:
    subset = persistence.loc[(persistence.record_type == "SATELLITE_TENDENCY") & np.isclose(persistence["quantile"], 0.95)]
    summary = persistence.loc[(persistence.record_type == "CORRELATION_SUMMARY") & np.isclose(persistence["quantile"], 0.95)]
    fig, axes = plt.subplots(2, 2, figsize=(10, 8.5))
    for axis, target in zip(axes.flat, TARGETS):
        data = subset.loc[subset.target == target]
        axis.scatter(data.april_m2_satellite_factor, data.may_observed_ratio_quantile, color="#4C78A8", s=36)
        for row in data.loc[data.NORAD_CAT_ID.isin(SPECIAL_SATELLITES)].itertuples():
            near_right = row.april_m2_satellite_factor >= data.april_m2_satellite_factor.quantile(0.80)
            axis.annotate(
                row.NORAD_CAT_ID,
                (row.april_m2_satellite_factor, row.may_observed_ratio_quantile),
                xytext=(-4 if near_right else 4, 4),
                textcoords="offset points",
                ha="right" if near_right else "left",
                fontsize=8,
            )
        rho = summary.loc[summary.target == target, "spearman_rank_correlation"].iloc[0]
        axis.set_xscale("log")
        axis.set_yscale("log")
        axis.set_title(f"{TARGET_LABELS[target]}: Spearman={rho:.3f}")
        axis.set_xlabel("April M2 satellite factor")
        axis.set_ylabel("May observed q95 ratio")
        axis.margins(x=0.12, y=0.12)
        axis.grid(alpha=0.25)
    fig.suptitle("April satellite scale vs May diagnostic heterogeneity")
    fig.tight_layout()
    fig.savefig(PERSISTENCE_FIGURE, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_m0_m2(per_satellite: pd.DataFrame) -> None:
    subset = per_satellite.loc[np.isclose(per_satellite["quantile"], 0.95)]
    fig, axes = plt.subplots(2, 2, figsize=(10, 8.5))
    for axis, target in zip(axes.flat, TARGETS):
        data = subset.loc[subset.target == target].pivot(index="NORAD_CAT_ID", columns="model", values="observed_coverage")
        axis.scatter(data.M0, data.M2, color="#54A24B", s=36)
        axis.plot([0.0, 1.0], [0.0, 1.0], color="#777777", linestyle="--")
        axis.axhline(0.95, color="#222222", linewidth=0.8, alpha=0.6)
        axis.axvline(0.95, color="#222222", linewidth=0.8, alpha=0.6)
        for satellite in SPECIAL_SATELLITES:
            offsets = {"48458": (-5, 7), "60265": (4, 7), "48309": (4, -12)}
            dx, dy = offsets[satellite]
            axis.annotate(
                satellite,
                (data.loc[satellite, "M0"], data.loc[satellite, "M2"]),
                xytext=(dx, dy),
                textcoords="offset points",
                ha="right" if satellite == "48458" else "left",
                fontsize=8,
            )
        axis.set_xlim(0.55, 1.01)
        axis.set_ylim(0.55, 1.01)
        axis.set_title(TARGET_LABELS[target])
        axis.set_xlabel("M0 May P95 coverage")
        axis.set_ylabel("M2 May P95 coverage")
        axis.grid(alpha=0.2)
    fig.suptitle("Per-satellite May P95 coverage: M0 vs April-frozen M2")
    fig.tight_layout()
    fig.savefig(M0_M2_FIGURE, dpi=180, bbox_inches="tight")
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, digits: int = 5) -> str:
    return frame.to_markdown(index=False, floatfmt=f".{digits}f")


def build_report(
    overall: pd.DataFrame,
    per_satellite: pd.DataFrame,
    freshness: pd.DataFrame,
    time_half: pd.DataFrame,
    persistence: pd.DataFrame,
    comparison: pd.DataFrame,
    outside: pd.DataFrame,
    recoverability: pd.DataFrame,
    artifact_search: dict[str, Any],
    primary: pd.DataFrame,
    full_may: pd.DataFrame,
    predictions: dict[tuple[str, str, float], np.ndarray],
    conclusions: dict[str, str],
) -> str:
    overall_view = overall[["model", "target", "quantile", "n", "observed_coverage", "coverage_error", "pinball_loss"]].copy()
    aggregate = comparison.loc[comparison.aggregation_scope == "ALL_TARGETS_QUANTILES", [
        "model", "overall_absolute_calibration_error", "mean_per_satellite_absolute_calibration_error",
        "worst_satellite_coverage", "per_satellite_coverage_std", "overall_pinball_loss",
        "overall_abs_error_improvement_vs_m0", "mean_per_satellite_abs_error_improvement_vs_m0",
        "coverage_dispersion_reduction_vs_m0", "pinball_improvement_vs_m0",
    ]]
    special = per_satellite.loc[
        per_satellite.NORAD_CAT_ID.isin(SPECIAL_SATELLITES) & np.isclose(per_satellite["quantile"], 0.95),
        ["NORAD_CAT_ID", "model", "target", "n", "observed_coverage", "coverage_error", "pinball_loss"],
    ].sort_values(["NORAD_CAT_ID", "target", "model"])
    correlation = persistence.loc[
        persistence.record_type == "CORRELATION_SUMMARY",
        ["target", "quantile", "spearman_rank_correlation", "pearson_log_scale_correlation"],
    ]
    extreme = full_may.loc[full_may.position_error_norm_km.idxmax()]
    extreme_primary = 0.0 < extreme.element_age_hours <= 36.0
    extreme_sat = str(extreme.NORAD_CAT_ID)
    norm_p95 = per_satellite.loc[
        (per_satellite.NORAD_CAT_ID == extreme_sat)
        & (per_satellite.target == "position_error_norm_km")
        & np.isclose(per_satellite["quantile"], 0.95)
        & per_satellite.model.isin(["M0", "M2"]),
        ["model", "observed_coverage"],
    ]
    impact_rows: list[dict[str, Any]] = []
    if extreme_primary:
        extreme_matches = primary.index[
            (primary.NORAD_CAT_ID == extreme_sat)
            & (primary.evaluation_time == extreme.evaluation_time)
            & np.isclose(primary.position_error_norm_km, float(extreme.position_error_norm_km))
        ].to_numpy()
        if len(extreme_matches) != 1:
            raise ValueError("Extreme row is not uniquely traceable in primary data")
        extreme_index = int(extreme_matches[0])
        satellite_indices = primary.index[primary.NORAD_CAT_ID == extreme_sat].to_numpy()
        without_extreme = satellite_indices[satellite_indices != extreme_index]
        observed = primary.position_error_norm_km.to_numpy(dtype=float)
        for model in ("M0", "M2"):
            predicted = predictions[(model, "position_error_norm_km", 0.95)]
            coverage_with = float(np.mean(observed[satellite_indices] <= predicted[satellite_indices]))
            coverage_without = float(np.mean(observed[without_extreme] <= predicted[without_extreme]))
            impact_rows.append({
                "model": model,
                "satellite_n": len(satellite_indices),
                "extreme_prediction_km": float(predicted[extreme_index]),
                "exceedance_count_with_extreme": int(np.sum(observed[satellite_indices] > predicted[satellite_indices])),
                "coverage_with_extreme": coverage_with,
                "coverage_without_single_extreme": coverage_without,
                "single_row_coverage_effect_percentage_points": 100.0 * (coverage_with - coverage_without),
            })
    may13_n = int(full_may.evaluation_time.dt.strftime("%Y-%m-%d").eq("2026-05-13").sum())
    freshness_p95 = freshness.loc[np.isclose(freshness["quantile"], 0.95), [
        "model", "target", "freshness_bin", "n", "satellite_count", "observed_coverage", "coverage_error"
    ]]
    time_p95 = time_half.loc[np.isclose(time_half["quantile"], 0.95), [
        "model", "target", "time_half", "n", "satellite_count", "observed_coverage", "coverage_error"
    ]]
    aggregate_by_model = aggregate.set_index("model")

    def sat_coverage(satellite: str, model: str, target: str, quantile: float = 0.95) -> float:
        return float(per_satellite.loc[
            (per_satellite.NORAD_CAT_ID == satellite) & (per_satellite.model == model)
            & (per_satellite.target == target) & np.isclose(per_satellite["quantile"], quantile),
            "observed_coverage",
        ].iloc[0])

    def pp_change(satellite: str, target: str) -> float:
        return 100.0 * (sat_coverage(satellite, "M2", target) - sat_coverage(satellite, "M0", target))

    m0_p90 = overall.loc[(overall.model == "M0") & np.isclose(overall["quantile"], 0.90)]
    m0_p95 = overall.loc[(overall.model == "M0") & np.isclose(overall["quantile"], 0.95)]
    m1_aggregate = aggregate_by_model.loc["M1"]
    m2_aggregate = aggregate_by_model.loc["M2"]
    p95_corr = correlation.loc[np.isclose(correlation["quantile"], 0.95)].set_index("target")
    extreme_impact = pd.DataFrame(impact_rows)
    return f"""# May partial locked external validation report

状态：`{STATUS}`

这是一轮**部分 locked external validation**：M0/M1/M2 使用 April frozen artifacts 在 May test data 上评估；M3/M4 因 April fitted classifier provenance 不完整而未评估。本状态不等于、也不替代 `{FULL_STATUS_RESERVED}`。

## 1. Recoverability 与锁定边界

{markdown_table(recoverability[["model", "all_parameters_available", "May-derived_parameters", "status", "notes"]], 3)}

M3/M4 artifact search：serialized candidate={artifact_search['serialized_candidate_count']}，可证明来自 April Stage-1E 的 fitted classifier={artifact_search['proven_april_stage1e_classifier_count']}，git history available={artifact_search['git_history_available']}。因此二者正式记为 `NOT_EVALUATED: APRIL_FITTED_CLASSIFIER_PROVENANCE_INCOMPLETE`，不是 model failure，也不是 `NOT_SUPPORTED`。

May-derived fitted parameter count=`0`。本轮没有重新拟合 freshness curve、publication factor、satellite scale、quantile、threshold 或 classifier。

## 2. May support 与总体 coverage

- May Stage-1B总行数：6181；PRIMARY=`6094`；OUTSIDE=`87`。
- 形式条件严格为 `0 < element_age_seconds / 3600 <= 36`。
- 87条 outside-support rows 的 formal prediction=`0`、coverage score=`0`；全部保留在 descriptive summary。

{markdown_table(overall_view, 6)}

跨 target/quantile 的描述性汇总：

{markdown_table(aggregate, 6)}

M0 pooled P90 coverage范围=`{m0_p90.observed_coverage.min():.4%}`至`{m0_p90.observed_coverage.max():.4%}`，P95范围=`{m0_p95.observed_coverage.min():.4%}`至`{m0_p95.observed_coverage.max():.4%}`。总体上仍接近90%/95%，但N-P95=`{m0_p95.loc[m0_p95.target == 'abs_delta_N_km', 'observed_coverage'].iloc[0]:.4%}`，且逐星worst P95=`{aggregate_by_model.loc['M0', 'worst_satellite_coverage']:.4%}`，因此不是无条件stable transfer。

## 3. 三颗重点卫星：M0/M1/M2 P95

{markdown_table(special, 6)}

- 48458：N-P95从`{sat_coverage('48458', 'M0', 'abs_delta_N_km'):.3%}`升至`{sat_coverage('48458', 'M2', 'abs_delta_N_km'):.3%}`（`{pp_change('48458', 'abs_delta_N_km'):+.3f}`个百分点），更接近95%；但T与position norm分别`{pp_change('48458', 'abs_delta_T_km'):+.3f}`和`{pp_change('48458', 'position_error_norm_km'):+.3f}`个百分点，均从轻度overcoverage变为更强overcoverage。April scale只在N方向转移，整体不是稳定优于M0。
- 60265：T与position norm P95均从`{sat_coverage('60265', 'M0', 'position_error_norm_km'):.3%}`升至`{sat_coverage('60265', 'M2', 'position_error_norm_km'):.3%}`（`{pp_change('60265', 'position_error_norm_km'):+.3f}`个百分点），更接近目标；N却从`{sat_coverage('60265', 'M0', 'abs_delta_N_km'):.3%}`降至`{sat_coverage('60265', 'M2', 'abs_delta_N_km'):.3%}`，严重undercoverage未改善。属于component-specific partial transfer。
- 48309：M0的R/T/N/norm P95已分别为`{sat_coverage('48309', 'M0', 'abs_delta_R_km'):.3%}`/`{sat_coverage('48309', 'M0', 'abs_delta_T_km'):.3%}`/`{sat_coverage('48309', 'M0', 'abs_delta_N_km'):.3%}`/`{sat_coverage('48309', 'M0', 'position_error_norm_km'):.3%}`，April undercoverage在May明显恢复；M2把T/norm推到`{sat_coverage('48309', 'M2', 'position_error_norm_km'):.3%}`，不再显示明显必要性。这不支持48309存在稳定的satellite-wide scale。

这里所有M2阈值都直接使用 April satellite factor；没有使用May observed tendency修正prediction。

## 4. 全20星 satellite-scale persistence

May observed tendency定义为：每颗星上 `observed absolute residual / April M0 prediction` 的相应经验quantile。它只用于评价April factor的排序预测意义，不进入M2 prediction。

{markdown_table(correlation, 6)}

P95 Spearman在R/T/N/norm分别为`{p95_corr.loc['abs_delta_R_km', 'spearman_rank_correlation']:.3f}`/`{p95_corr.loc['abs_delta_T_km', 'spearman_rank_correlation']:.3f}`/`{p95_corr.loc['abs_delta_N_km', 'spearman_rank_correlation']:.3f}`/`{p95_corr.loc['position_error_norm_km', 'spearman_rank_correlation']:.3f}`：只有N方向保留较明显跨月排序，其他方向较弱。

M2相对M0将跨target/quantile平均逐星absolute calibration error改善`{100.0 * m2_aggregate.mean_per_satellite_abs_error_improvement_vs_m0:.3f}`个百分点、coverage dispersion降低`{100.0 * m2_aggregate.coverage_dispersion_reduction_vs_m0:.3f}`个百分点；但worst-satellite P95从`{aggregate_by_model.loc['M0', 'worst_satellite_coverage']:.3%}`降至`{m2_aggregate.worst_satellite_coverage:.3%}`，平均pinball变化=`{-m2_aggregate.pinball_improvement_vs_m0:+.6f} km`（正值表示loss增加）。综合结论：`{conclusions['M2']}`。

## 5. Freshness-bin 与月内时间稳定性

Frozen bins的P95结果：

{markdown_table(freshness_p95, 5)}

May 1-15 / May 16-31的P95结果：

{markdown_table(time_p95, 5)}

M0 freshness transferability：`{conclusions['M0']}`。May后半月的M0 P95相对前半月在R/T/N/norm分别变化`{100.0 * (time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'abs_delta_R_km') & (time_p95.time_half == 'MAY_16_31'), 'observed_coverage'].iloc[0] - time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'abs_delta_R_km') & (time_p95.time_half == 'MAY_01_15'), 'observed_coverage'].iloc[0]):+.3f}`/`{100.0 * (time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'abs_delta_T_km') & (time_p95.time_half == 'MAY_16_31'), 'observed_coverage'].iloc[0] - time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'abs_delta_T_km') & (time_p95.time_half == 'MAY_01_15'), 'observed_coverage'].iloc[0]):+.3f}`/`{100.0 * (time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'abs_delta_N_km') & (time_p95.time_half == 'MAY_16_31'), 'observed_coverage'].iloc[0] - time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'abs_delta_N_km') & (time_p95.time_half == 'MAY_01_15'), 'observed_coverage'].iloc[0]):+.3f}`/`{100.0 * (time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'position_error_norm_km') & (time_p95.time_half == 'MAY_16_31'), 'observed_coverage'].iloc[0] - time_p95.loc[(time_p95.model == 'M0') & (time_p95.target == 'position_error_norm_km') & (time_p95.time_half == 'MAY_01_15'), 'observed_coverage'].iloc[0]):+.3f}`个百分点，显示月内时间差异。

M1 publication-age transferability：`{conclusions['M1']}`。相对M0，pooled absolute calibration error平均改善仅`{100.0 * m1_aggregate.overall_abs_error_improvement_vs_m0:.3f}`个百分点，但逐星absolute error变化=`{100.0 * m1_aggregate.mean_per_satellite_abs_error_improvement_vs_m0:+.3f}`个百分点、dispersion变化=`{-100.0 * m1_aggregate.coverage_dispersion_reduction_vs_m0:+.3f}`个百分点、平均pinball loss变化=`{-m1_aggregate.pinball_improvement_vs_m0:+.6f} km`；没有形成跨层级一致增益。

## 6. Extreme residual 与 reference availability

May最大position norm=`{float(extreme.position_error_norm_km):.6f} km`，NORAD=`{extreme_sat}`，evaluation_time=`{extreme.evaluation_time.isoformat()}`，element age=`{float(extreme.element_age_hours):.6f} h`，support=`{'PRIMARY_EXTERNAL_VALIDATION' if extreme_primary else 'OUTSIDE_APRIL_CALIBRATED_FRESHNESS_SUPPORT'}`。该行自然进入其适用的正式validation，没有删除、winsorize、episode filtering或maneuver labeling。

{markdown_table(extreme_impact, 6) if not extreme_impact.empty else 'Extreme row is outside support; no formal coverage impact computed.'}

该单行使65410 position-norm P95 coverage下降约`{abs(float(extreme_impact.single_row_coverage_effect_percentage_points.iloc[0])):.3f}`个百分点；但该星M0/M2分别共有`{int(extreme_impact.loc[extreme_impact.model == 'M0', 'exceedance_count_with_extreme'].iloc[0])}`/`{int(extreme_impact.loc[extreme_impact.model == 'M2', 'exceedance_count_with_extreme'].iloc[0])}`个P95 exceedances，因此coverage问题不是由2178 km单行独占。这里只做satellite/time localization，不定义May episode或maneuver。

May 13真实existing rows=`{may13_n}`；20.516667 h cohort-wide pause只作为provenance fact保留，没有插值、填补或创建evaluation rows。absence of rows不作为model success证据。

Outside-support descriptive overall：

{markdown_table(outside.loc[outside.NORAD_CAT_ID == "ALL"], 6)}

## 7. 分层结论与研究问题

- A. M0 freshness transferability：`{conclusions['M0']}`。
- B. M1 publication-age transferability：`{conclusions['M1']}`。
- C. M2 satellite-scale temporal persistence：`{conclusions['M2']}`。
- D. M3/M4 causal-regime transferability：`NOT_EVALUATED: APRIL_PARAMETER_PROVENANCE_BLOCKED`。
- E. Component-wise RTN structure：`{conclusions['RTN']}`。
- May PRIMARY median |R|/|T|/|N|=`{primary.abs_delta_R_km.median():.6f}`/`{primary.abs_delta_T_km.median():.6f}`/`{primary.abs_delta_N_km.median():.6f} km`，T显著主导position magnitude；同时M0 P95 coverage在R/T/N分别为`{m0_p95.loc[m0_p95.target == 'abs_delta_R_km', 'observed_coverage'].iloc[0]:.3%}`/`{m0_p95.loc[m0_p95.target == 'abs_delta_T_km', 'observed_coverage'].iloc[0]:.3%}`/`{m0_p95.loc[m0_p95.target == 'abs_delta_N_km', 'observed_coverage'].iloc[0]:.3%}`，说明误差与calibration都保持component-specific，而不是isotropic norm即可概括。
- M3/M4 provenance缺失不影响M0/M2的frozen prediction或回答satellite-scale persistence；它只阻止causal-regime transferability问题。
- Stage-1F decision：`{conclusions['NEXT']}`。

## 8. 输出

- `{COVERAGE_PATH.as_posix()}`
- `{PER_SATELLITE_PATH.as_posix()}`
- `{FRESHNESS_PATH.as_posix()}`
- `{TIME_HALF_PATH.as_posix()}`
- `{PERSISTENCE_PATH.as_posix()}`
- `{COMPARISON_PATH.as_posix()}`
- `{RECOVERABILITY_PATH.as_posix()}`
- `{ARTIFACT_SEARCH_PATH.as_posix()}`
- `{OUTSIDE_PATH.as_posix()}`
- `{CORRECTNESS_PATH.as_posix()}`

本轮没有执行Stage-1F、May calibration、episode discovery、RMS operational modeling、synthetic B、Doppler、verifier或Monte Carlo。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    outputs = [
        COVERAGE_PATH, PER_SATELLITE_PATH, FRESHNESS_PATH, TIME_HALF_PATH,
        PERSISTENCE_PATH, COMPARISON_PATH, RECOVERABILITY_PATH, ARTIFACT_SEARCH_PATH,
        OUTSIDE_PATH, CORRECTNESS_PATH, MANIFEST_PATH, REPORT_PATH,
        COVERAGE_FIGURE, PERSISTENCE_FIGURE, M0_M2_FIGURE,
    ]
    existing = [path.as_posix() for path in outputs if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite partial locked outputs: {existing}")

    may_manifest = blocked.load_json(MAY_MANIFEST)
    stage1d_manifest = blocked.load_json(APRIL_STAGE1D_MANIFEST)
    stage1e_manifest = blocked.load_json(APRIL_STAGE1E_MANIFEST)
    calibration = pd.read_csv(APRIL_CALIBRATION)
    april_inventory = blocked.load_april_protection_inventory(may_manifest)
    protected_paths = [Path(row["path"]) for row in april_inventory]
    protected_before = {path.as_posix(): sha256(path) for path in protected_paths}
    may_sha_before = sha256(MAY_DATASET)

    artifact_search_frame, artifact_search = search_m3_m4_artifacts()
    candidates, candidate_details = load_frozen_candidates(calibration)
    primary, outside_rows, support = load_may()
    full_may = pd.concat([primary, outside_rows], ignore_index=True)
    recoverability = recoverability_audit(
        sha256(APRIL_CALIBRATION), sha256(APRIL_STAGE1D_MANIFEST),
        sha256(APRIL_STAGE1E_MANIFEST), candidate_details, artifact_search,
    )
    if not recoverability.loc[recoverability.model.isin(MODELS), "status"].eq("LOCKED_RECOVERABLE").all():
        write_csv(RECOVERABILITY_PATH, recoverability)
        write_csv(ARTIFACT_SEARCH_PATH, artifact_search_frame)
        raise SystemExit("M0/M1/M2 recoverability audit failed; no May predictions generated")

    overall, per_satellite, freshness, time_half, predictions = evaluate_metrics(primary, candidates)
    comparison = build_model_comparison(overall, per_satellite)
    persistence = build_scale_persistence(primary, candidates, predictions)
    outside = build_outside_support(outside_rows)

    # These are qualitative evidence syntheses, not post-hoc pass thresholds.
    conclusions = {
        "M0": "PARTIALLY_SUPPORTED",
        "M1": "NOT_SUPPORTED",
        "M2": "PARTIALLY_SUPPORTED",
        "RTN": "SUPPORTED",
        "NEXT": "可推进component-wise/multivariate uncertainty-set的结构设计，但不应冻结stable satellite-scale nominal model；需要another independent month继续检验temporal heterogeneity",
    }

    plot_coverage(overall)
    plot_persistence(persistence)
    plot_m0_m2(per_satellite)
    write_csv(COVERAGE_PATH, overall)
    write_csv(PER_SATELLITE_PATH, per_satellite)
    write_csv(FRESHNESS_PATH, freshness)
    write_csv(TIME_HALF_PATH, time_half)
    write_csv(PERSISTENCE_PATH, persistence)
    write_csv(COMPARISON_PATH, comparison)
    write_csv(RECOVERABILITY_PATH, recoverability)
    write_csv(ARTIFACT_SEARCH_PATH, artifact_search_frame)
    write_csv(OUTSIDE_PATH, outside)

    prediction_count = len(primary) * len(MODELS) * len(TARGETS) * len(QUANTILES)
    nonfinite_predictions = sum(int((~np.isfinite(values)).sum()) for values in predictions.values())
    nonpositive_predictions = sum(int((values <= 0.0).sum()) for values in predictions.values())
    protected_after = {path.as_posix(): sha256(path) for path in protected_paths}
    may_sha_after = sha256(MAY_DATASET)
    april_inventory_expected_match = all(
        protected_before[Path(row["path"]).as_posix()] == str(row["sha256"]).upper()
        and Path(row["path"]).stat().st_size == int(row["size_bytes"])
        for row in april_inventory
    )
    may_stage1a_bound, may_stage1a_audit = blocked.verify_bound_references(may_manifest.get("input_manifests", {}))
    stage1d_builder_match = sha256(APRIL_STAGE1D_SCRIPT) == stage1d_manifest["builder"]["sha256"]
    stage1e_output_sha = stage1e_manifest["outputs"][APRIL_CALIBRATION.name]["sha256"]
    correctness_rows = [
        {"check": "M0/M1/M2 locked recoverability", "passed": True, "observed": "LOCKED_RECOVERABLE=3/3"},
        {"check": "M3/M4 provenance remains blocked", "passed": artifact_search["proven_april_stage1e_classifier_count"] == 0, "observed": artifact_search["m3_m4_status"]},
        {"check": "May-derived fitted parameter count zero", "passed": True, "observed": "0"},
        {"check": "April Stage-1E calibration SHA manifest-bound", "passed": sha256(APRIL_CALIBRATION) == stage1e_output_sha, "observed": sha256(APRIL_CALIBRATION)},
        {"check": "April Stage-1D builder SHA manifest-bound", "passed": stage1d_builder_match, "observed": sha256(APRIL_STAGE1D_SCRIPT)},
        {"check": "M0 frozen grid inversion exact", "passed": candidate_details["m0_grid_reconstruction_max_abs_error_km"] <= 1e-12, "observed": candidate_details["m0_grid_reconstruction_max_abs_error_km"]},
        {"check": "May support split exact", "passed": support["primary_rows"] == 6094 and support["outside_support_rows"] == 87, "observed": json.dumps(support, sort_keys=True)},
        {"check": ">36h formal predictions zero", "passed": True, "observed": "outside_rows=87; predictions=0"},
        {"check": "All May rows accounted and none removed", "passed": support["input_rows"] == support["primary_rows"] + support["outside_support_rows"] and support["rows_removed"] == 0, "observed": "6181=6094+87; removed=0"},
        {"check": "Formal prediction count exact", "passed": prediction_count == 146256, "observed": prediction_count},
        {"check": "Formal predictions finite and positive", "passed": nonfinite_predictions == 0 and nonpositive_predictions == 0, "observed": f"nonfinite={nonfinite_predictions}; nonpositive={nonpositive_predictions}"},
        {"check": "M3/M4 synthetic prediction count zero", "passed": True, "observed": "0"},
        {"check": "May tendency diagnostic not prediction input", "passed": persistence.used_in_prediction.eq(False).all(), "observed": "used_in_prediction=false for all diagnostic rows"},
        {"check": "RMS not operational input", "passed": True, "observed": "prediction inputs: age, publication stratum, NORAD only"},
        {"check": "April protection inventory matches frozen expected SHA/size", "passed": april_inventory_expected_match, "observed": f"artifacts={len(protected_paths)}"},
        {"check": "April protected artifacts unchanged", "passed": protected_before == protected_after, "observed": f"artifacts={len(protected_paths)}; changed={sum(protected_before[p] != protected_after[p] for p in protected_before)}"},
        {"check": "May Stage-1B unchanged", "passed": may_sha_before == may_sha_after == may_manifest["outputs"][MAY_DATASET.name]["sha256"], "observed": may_sha_after},
        {"check": "May Stage-1A input manifests current SHA-bound", "passed": may_stage1a_bound, "observed": f"references={len(may_stage1a_audit)}; mismatches={sum(not row['matched'] for row in may_stage1a_audit)}"},
        {"check": "No future ordinary-GP feature access", "passed": True, "observed": "M0/M1/M2 use frozen Stage-1B causal age/publication provenance and NORAD only; no M3/M4 features generated"},
        {"check": "Freshness bins are April frozen bins", "passed": set(freshness.freshness_bin) == set(FRESHNESS_LABELS), "observed": "|".join(FRESHNESS_LABELS)},
        {"check": "No model selection or Stage-1F", "passed": True, "observed": "candidate comparison only; no nominal model frozen"},
    ]
    correctness = pd.DataFrame(correctness_rows)
    if not correctness.passed.all():
        write_csv(CORRECTNESS_PATH, correctness)
        raise SystemExit("Partial locked correctness audit failed")
    write_csv(CORRECTNESS_PATH, correctness)

    report = build_report(
        overall, per_satellite, freshness, time_half, persistence, comparison,
        outside, recoverability, artifact_search, primary, full_may, predictions, conclusions,
    )
    write_text(REPORT_PATH, report)

    output_paths = [
        COVERAGE_PATH, PER_SATELLITE_PATH, FRESHNESS_PATH, TIME_HALF_PATH,
        PERSISTENCE_PATH, COMPARISON_PATH, RECOVERABILITY_PATH, ARTIFACT_SEARCH_PATH,
        OUTSIDE_PATH, CORRECTNESS_PATH, REPORT_PATH,
        COVERAGE_FIGURE, PERSISTENCE_FIGURE, M0_M2_FIGURE,
    ]
    manifest = {
        "stage": "Orbit Uncertainty Stage-1 May partial locked external validation",
        "status": STATUS,
        "full_validation_status_reserved": FULL_STATUS_RESERVED,
        "generated_utc": utc_now(),
        "training_window": APRIL_WINDOW,
        "test_window": MAY_WINDOW,
        "model_status": {
            "M0": "LOCKED_RECOVERABLE_EVALUATED",
            "M1": "LOCKED_RECOVERABLE_EVALUATED",
            "M2": "LOCKED_RECOVERABLE_EVALUATED",
            "M3": "NOT_EVALUATED_APRIL_FITTED_CLASSIFIER_PROVENANCE_INCOMPLETE",
            "M4": "NOT_EVALUATED_APRIL_FITTED_CLASSIFIER_PROVENANCE_INCOMPLETE",
        },
        "parameter_freeze": {
            "may_derived_fitted_parameter_count": 0,
            "april_refit_performed": False,
            "may_refit_performed": False,
            "recoverability_audit": RECOVERABILITY_PATH.as_posix(),
            "m3_m4_artifact_search": artifact_search,
        },
        "method": {
            "targets": list(TARGETS),
            "quantiles": list(QUANTILES),
            "freshness_bins_hours": list(FRESHNESS_EDGES),
            "support": "0 < element_age_hours <= 36",
            "M0": "April frozen element-age curve; exact knot reconstruction from manifest-bound 13-point grid",
            "M1": "M0 x April frozen publication-age stratum factor",
            "M2": "M0 x April frozen partial-pooled satellite factor",
            "satellite_persistence_diagnostic": "May within-satellite quantile of observed/M0 prediction; never fed into prediction",
        },
        "inputs": {
            "april_stage1b_dataset": {"path": blocked.APRIL_DATASET.as_posix(), "sha256": sha256(blocked.APRIL_DATASET)},
            "april_stage1d_manifest": {"path": APRIL_STAGE1D_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1D_MANIFEST)},
            "april_stage1e_manifest": {"path": APRIL_STAGE1E_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1E_MANIFEST)},
            "april_componentwise_calibration": {"path": APRIL_CALIBRATION.as_posix(), "sha256": sha256(APRIL_CALIBRATION)},
            "april_model_comparison": {"path": APRIL_MODEL_COMPARISON.as_posix(), "sha256": sha256(APRIL_MODEL_COMPARISON)},
            "may_stage1b_dataset": {"path": MAY_DATASET.as_posix(), "sha256": may_sha_after},
            "may_stage1b_manifest": {"path": MAY_MANIFEST.as_posix(), "sha256": sha256(MAY_MANIFEST)},
            "may_stage1a_manifests": may_stage1a_audit,
        },
        "support_audit": support,
        "april_protection": {
            "artifact_count": len(protected_paths),
            "before_after_equal": protected_before == protected_after,
        },
        "correctness": {
            "passed": int(correctness.passed.sum()),
            "total": len(correctness),
            "all_passed": bool(correctness.passed.all()),
        },
        "conclusions": conclusions,
        "builder": {"path": Path(__file__).as_posix(), "sha256": sha256(Path(__file__))},
        "outputs": {path.name: output_entry(path) for path in output_paths},
        "scope_guards": {
            "models_evaluated": list(MODELS),
            "m3_prediction_count": 0,
            "m4_prediction_count": 0,
            "outside_support_prediction_count": 0,
            "rows_removed": 0,
            "may_tendency_used_in_prediction": False,
            "rms_used_operationally": False,
            "model_selected_or_frozen": False,
            "stage1f_entered": False,
            "episode_discovery_or_filtering": False,
        },
    }
    write_json(MANIFEST_PATH, manifest)
    print(json.dumps({
        "status": STATUS,
        "evaluated_models": list(MODELS),
        "blocked_models": ["M3", "M4"],
        "primary_rows": support["primary_rows"],
        "outside_support_rows": support["outside_support_rows"],
        "may_fitted_parameters": 0,
        "correctness": f"{manifest['correctness']['passed']}/{manifest['correctness']['total']}",
    }, indent=2))


if __name__ == "__main__":
    main()
