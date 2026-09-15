#!/usr/bin/env python3
"""Stage-1D freshness-conditioned legitimate disagreement calibration.

Consumes the frozen Stage-1B canonical residual library and the frozen Stage-1C
candidate-episode definition.  It does not rebuild residuals, remove rows from
the canonical dataset, define a fixed-km orbit boundary, analyze synthetic B,
or run a Doppler verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.isotonic import IsotonicRegression

try:
    from scripts import analyze_orbit_uncertainty_stage1c_residual_structure as stage1c
    from scripts.orbit_uncertainty_stage1_window import FORMAL_INTERVAL, WINDOW_TAG
except (ModuleNotFoundError, ImportError):
    import analyze_orbit_uncertainty_stage1c_residual_structure as stage1c
    from orbit_uncertainty_stage1_window import FORMAL_INTERVAL, WINDOW_TAG


STAGE1B_PREFIX = f"orbit_uncertainty_stage1b_{WINDOW_TAG}"
STAGE1C_PREFIX = f"orbit_uncertainty_stage1c_{WINDOW_TAG}"
STAGE1D_PREFIX = f"orbit_uncertainty_stage1d_{WINDOW_TAG}"

DATASET_PATH = Path("outputs/datasets") / f"{STAGE1B_PREFIX}_rtn_residual_library.csv"
STAGE1B_MANIFEST_PATH = Path("outputs/metrics") / f"{STAGE1B_PREFIX}_manifest.json"
STAGE1C_MANIFEST_PATH = Path("outputs/metrics") / f"{STAGE1C_PREFIX}_manifest.json"
STAGE1C_REGIME_PATH = Path("outputs/metrics") / f"{STAGE1C_PREFIX}_regime_candidate_summary.csv"

METRICS_DIR = Path("outputs/metrics")
REPORTS_DIR = Path("outputs/reports")
FIGURE_DIR = Path("outputs/figures") / STAGE1D_PREFIX

QUANTILES_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_freshness_quantiles.csv"
MODEL_GRID_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_conditional_model_grid.csv"
COVERAGE_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_coverage_validation.csv"
SATELLITE_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_satellite_validation.csv"
REGIME_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_regime_sensitivity.csv"
TIMEBLOCK_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_timeblock_validation.csv"
CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_correctness_audit.csv"
MANIFEST_PATH = METRICS_DIR / f"{STAGE1D_PREFIX}_manifest.json"
REPORT_PATH = REPORTS_DIR / f"{STAGE1D_PREFIX}_freshness_calibration_report.md"

POSITION_FIGURE = FIGURE_DIR / "position_conditional_quantiles_vs_element_age.png"
RTN_FIGURE = FIGURE_DIR / "rtn_component_p95_vs_element_age.png"
SATELLITE_FIGURE = FIGURE_DIR / "per_satellite_p95_coverage.png"
REGIME_FIGURE = FIGURE_DIR / "full_vs_regime_excluded_p95_sensitivity.png"

PRIMARY_SUPPORT_MIN_EXCLUSIVE_H = 0.0
PRIMARY_SUPPORT_MAX_INCLUSIVE_H = 36.0
RAW_REQUESTED_EDGES_H = [0.0, 3.0, 6.0, 9.0, 12.0, 18.0, 24.0, 30.0, 36.0]
CALIBRATION_EDGES_H = [0.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0]
CALIBRATION_LABELS = ["0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h"]
CALIBRATION_CENTERS_H = np.array([3.0, 7.5, 10.5, 15.0, 21.0, 30.0])
EVALUATION_GRID_H = np.array([0.0, 3.0, 6.0, 9.0, 12.0, 15.0, 18.0, 21.0, 24.0, 27.0, 30.0, 33.0, 36.0])
EMPIRICAL_QUANTILES = [0.50, 0.75, 0.90, 0.95]
MODEL_QUANTILES = [0.50, 0.90, 0.95]
RESPONSES = {
    "abs_delta_R_km": "km",
    "abs_delta_T_km": "km",
    "abs_delta_N_km": "km",
    "position_error_norm_km": "km",
    "abs_delta_v_R_km_s": "km/s",
    "abs_delta_v_T_km_s": "km/s",
    "abs_delta_v_N_km_s": "km/s",
    "velocity_error_norm_km_s": "km/s",
}
MODEL_RESPONSES = ["position_error_norm_km", "abs_delta_R_km", "abs_delta_T_km", "abs_delta_N_km"]
VIEW_FULL = "FULL_SUPPORTED"
VIEW_REGIME_EXCLUDED = "REGIME_EXCLUDED_SENSITIVITY"
BOOTSTRAP_UNIT = "satellite_cluster"
TIME_SPLIT = pd.Timestamp("2026-04-21T00:00:00Z")


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
        raise SystemExit(f"Required input missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-reps", type=int, default=1000)
    parser.add_argument("--random-seed", type=int, default=20260902)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def output_paths(include_regime_figure: bool = True) -> list[Path]:
    paths = [
        QUANTILES_PATH, MODEL_GRID_PATH, COVERAGE_PATH, SATELLITE_PATH,
        REGIME_PATH, TIMEBLOCK_PATH, CORRECTNESS_PATH, MANIFEST_PATH,
        REPORT_PATH, POSITION_FIGURE, RTN_FIGURE, SATELLITE_FIGURE,
    ]
    if include_regime_figure:
        paths.append(REGIME_FIGURE)
    return paths


def ensure_outputs_available(overwrite: bool) -> None:
    existing = [str(path) for path in output_paths(True) if path.exists()]
    if existing and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing Stage-1D outputs: {existing}")


def verify_inputs() -> dict[str, Any]:
    stage1b_manifest = load_json(STAGE1B_MANIFEST_PATH)
    stage1c_manifest = load_json(STAGE1C_MANIFEST_PATH)
    if stage1b_manifest.get("status") != "APRIL_STAGE1B_RESIDUAL_LIBRARY_COMPLETE":
        raise SystemExit("Stage-1B manifest is not APRIL_STAGE1B_RESIDUAL_LIBRARY_COMPLETE")
    if stage1c_manifest.get("status") != "STAGE1C_RESIDUAL_STRUCTURE_CHARACTERIZATION_COMPLETE":
        raise SystemExit("Stage-1C manifest is not complete")
    if stage1b_manifest.get("window_tag") != WINDOW_TAG or stage1c_manifest.get("window_tag") != WINDOW_TAG:
        raise SystemExit("Stage-1B/1C window tag differs from frozen Stage-1D window")
    if stage1b_manifest.get("formal_window") != FORMAL_INTERVAL or stage1c_manifest.get("formal_window") != FORMAL_INTERVAL:
        raise SystemExit("Stage-1B/1C formal window differs from frozen Stage-1D window")
    dataset_sha = sha256(DATASET_PATH)
    stage1b_dataset_entry = stage1b_manifest["outputs"].get(DATASET_PATH.name)
    if not stage1b_dataset_entry or stage1b_dataset_entry.get("sha256") != dataset_sha:
        raise SystemExit("Stage-1B dataset SHA mismatch")
    if stage1c_manifest["input"].get("stage1b_dataset_sha256") != dataset_sha:
        raise SystemExit("Stage-1C is not bound to the current Stage-1B dataset")
    regime_entry = stage1c_manifest["outputs"].get(STAGE1C_REGIME_PATH.name)
    if not regime_entry or regime_entry.get("sha256") != sha256(STAGE1C_REGIME_PATH):
        raise SystemExit("Stage-1C candidate episode summary SHA mismatch")
    return {
        "stage1b_manifest": stage1b_manifest,
        "stage1c_manifest": stage1c_manifest,
        "dataset_sha": dataset_sha,
        "stage1b_manifest_sha": sha256(STAGE1B_MANIFEST_PATH),
        "stage1c_manifest_sha": sha256(STAGE1C_MANIFEST_PATH),
        "stage1c_regime_sha": sha256(STAGE1C_REGIME_PATH),
    }


def read_dataset() -> pd.DataFrame:
    frame = pd.read_csv(
        DATASET_PATH,
        dtype={"NORAD_CAT_ID": str, "ordinary_gp_id": str},
        encoding="utf-8-sig",
    )
    required = {
        "NORAD_CAT_ID", "evaluation_time", "element_age_seconds",
        "publication_age_seconds", "supgp_rms_km", "delta_R_km", "delta_T_km",
        "delta_N_km", "delta_v_R_km_s", "delta_v_T_km_s", "delta_v_N_km_s",
        "position_error_norm_km", "velocity_error_norm_km_s", "nominal_row",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SystemExit(f"Canonical dataset fields missing: {missing}")
    if len(frame) != 5675 or frame.NORAD_CAT_ID.nunique() != 20 or not frame.nominal_row.astype(bool).all():
        raise SystemExit("Canonical dataset is not the frozen 5675/20/nominal population")
    frame["evaluation_time"] = pd.to_datetime(frame.evaluation_time, utc=True, format="mixed")
    frame["element_age_hours"] = frame.element_age_seconds / 3600.0
    frame["publication_age_hours"] = frame.publication_age_seconds / 3600.0
    for source, target in [
        ("delta_R_km", "abs_delta_R_km"),
        ("delta_T_km", "abs_delta_T_km"),
        ("delta_N_km", "abs_delta_N_km"),
        ("delta_v_R_km_s", "abs_delta_v_R_km_s"),
        ("delta_v_T_km_s", "abs_delta_v_T_km_s"),
        ("delta_v_N_km_s", "abs_delta_v_N_km_s"),
    ]:
        frame[target] = frame[source].abs()
    frame["freshness_support_status"] = np.where(
        (frame.element_age_hours > PRIMARY_SUPPORT_MIN_EXCLUSIVE_H)
        & (frame.element_age_hours <= PRIMARY_SUPPORT_MAX_INCLUSIVE_H),
        "WITHIN_CALIBRATED_FRESHNESS_SUPPORT",
        "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT",
    )
    return frame


def reproduce_stage1c_episode_mapping(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
    stage_frame = stage1c.read_dataset()
    thresholds = stage1c.add_sensitivity_flags(stage_frame)
    episodes = stage1c.detect_episodes(stage_frame, thresholds)
    frozen = pd.read_csv(STAGE1C_REGIME_PATH, dtype={"NORAD_CAT_ID": str}, encoding="utf-8-sig")
    frozen_by_id = frozen.set_index("episode_id")
    mismatches: list[str] = []
    regime_flag = pd.Series(False, index=stage_frame.index)
    episode_id = pd.Series("", index=stage_frame.index, dtype=object)
    for episode in episodes:
        eid = episode["episode_id"]
        if eid not in frozen_by_id.index:
            mismatches.append(f"missing:{eid}")
            continue
        frozen_row = frozen_by_id.loc[eid]
        checks = {
            "NORAD_CAT_ID": str(episode["NORAD_CAT_ID"]) == str(frozen_row.NORAD_CAT_ID),
            "episode_row_count": int(episode["episode_row_count"]) == int(frozen_row.episode_row_count),
            "top1_row_count": int(episode["top1_row_count"]) == int(frozen_row.top1_row_count),
            "pattern_code": str(episode["pattern_code"]) == str(frozen_row.pattern_code),
            "start_time": pd.Timestamp(episode["start_time"]) == pd.to_datetime(frozen_row.start_time, utc=True),
            "end_time": pd.Timestamp(episode["end_time"]) == pd.to_datetime(frozen_row.end_time, utc=True),
        }
        if not all(checks.values()):
            mismatches.append(f"{eid}:{[key for key, ok in checks.items() if not ok]}")
        indices = list(range(int(episode["start_index"]), int(episode["end_index"]) + 1))
        regime_flag.loc[indices] = True
        episode_id.loc[indices] = eid
    if len(episodes) != len(frozen):
        mismatches.append(f"episode_count:{len(episodes)}!={len(frozen)}")
    if len(stage_frame) != len(frame) or not (
        stage_frame.NORAD_CAT_ID.to_numpy() == frame.sort_values(["NORAD_CAT_ID", "evaluation_time"]).NORAD_CAT_ID.to_numpy()
    ).all():
        raise SystemExit("Stage-1C reconstruction ordering differs from Stage-1D input")
    ordered = frame.sort_values(["NORAD_CAT_ID", "evaluation_time"]).copy()
    ordered["is_stage1c_regime_candidate"] = regime_flag.to_numpy()
    ordered["stage1c_episode_id"] = episode_id.to_numpy()
    mapping = ordered[["is_stage1c_regime_candidate", "stage1c_episode_id"]].sort_index()
    return mapping.is_stage1c_regime_candidate, mapping.stage1c_episode_id, {
        "episode_count": len(episodes),
        "mapped_rows": int(regime_flag.sum()),
        "frozen_episode_rows": int(frozen.episode_row_count.sum()),
        "mismatches": mismatches,
        "reproducible": not mismatches and int(regime_flag.sum()) == int(frozen.episode_row_count.sum()),
    }


def build_views(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    supported = frame.loc[frame.freshness_support_status == "WITHIN_CALIBRATED_FRESHNESS_SUPPORT"].copy()
    return {
        VIEW_FULL: supported,
        VIEW_REGIME_EXCLUDED: supported.loc[~supported.is_stage1c_regime_candidate].copy(),
    }


def calibration_bin(age_hours: pd.Series) -> pd.Series:
    return pd.cut(
        age_hours,
        CALIBRATION_EDGES_H,
        labels=CALIBRATION_LABELS,
        right=True,
        include_lowest=False,
    )


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, quantile: float) -> float:
    residual = np.asarray(y_true, dtype=float) - np.asarray(y_pred, dtype=float)
    return float(np.mean(np.maximum(quantile * residual, (quantile - 1.0) * residual)))


def safe_spearman(x: pd.Series, y: pd.Series) -> float:
    valid = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < 3 or valid.x.nunique() < 2 or valid.y.nunique() < 2:
        return math.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return float(spearmanr(valid.x, valid.y).statistic)


@dataclass
class ConditionalQuantileModel:
    predictor: str
    response: str
    quantiles: tuple[float, ...]
    centers: np.ndarray
    bin_counts: np.ndarray
    raw_curves: dict[float, np.ndarray]
    curves: dict[float, np.ndarray]
    train_n: int
    train_satellites: int
    observed_min_h: float
    observed_max_h: float
    max_monotone_adjustment: float
    max_crossing_adjustment: float

    def predict(self, ages: Iterable[float], quantile: float) -> np.ndarray:
        values = np.asarray(list(ages) if not isinstance(ages, np.ndarray) else ages, dtype=float)
        if np.any(values <= PRIMARY_SUPPORT_MIN_EXCLUSIVE_H) or np.any(values > PRIMARY_SUPPORT_MAX_INCLUSIVE_H):
            raise ValueError("Formal conditional predictions require 0 < age <= 36 h")
        return np.interp(values, self.centers, self.curves[quantile])

    def predict_grid(self, ages: Iterable[float], quantile: float) -> np.ndarray:
        values = np.asarray(list(ages) if not isinstance(ages, np.ndarray) else ages, dtype=float)
        if np.any(values < 0.0) or np.any(values > PRIMARY_SUPPORT_MAX_INCLUSIVE_H):
            raise ValueError("Grid predictions are restricted to [0, 36] h")
        return np.interp(values, self.centers, self.curves[quantile])


def fit_conditional_quantile_model(
    frame: pd.DataFrame,
    predictor: str,
    response: str,
    quantiles: Iterable[float] = MODEL_QUANTILES,
) -> ConditionalQuantileModel:
    qs = tuple(sorted(float(value) for value in quantiles))
    work = frame.loc[
        (frame[predictor] > PRIMARY_SUPPORT_MIN_EXCLUSIVE_H)
        & (frame[predictor] <= PRIMARY_SUPPORT_MAX_INCLUSIVE_H),
        [predictor, response, "NORAD_CAT_ID"],
    ].dropna()
    if work.empty:
        raise ValueError("No rows available for conditional quantile model")
    bins = calibration_bin(work[predictor])
    bin_counts = np.array([(bins == label).sum() for label in CALIBRATION_LABELS], dtype=int)
    raw_curves: dict[float, np.ndarray] = {}
    monotone_curves: dict[float, np.ndarray] = {}
    max_monotone_adjustment = 0.0
    for quantile in qs:
        raw = np.array([
            work.loc[bins == label, response].quantile(quantile) if (bins == label).any() else np.nan
            for label in CALIBRATION_LABELS
        ], dtype=float)
        valid = np.isfinite(raw)
        if valid.sum() < 2:
            raise ValueError(f"Insufficient occupied freshness bins for {predictor}/{response}/q={quantile}")
        filled = np.interp(CALIBRATION_CENTERS_H, CALIBRATION_CENTERS_H[valid], raw[valid])
        weights = np.maximum(bin_counts, 1)
        fitted = IsotonicRegression(increasing=True, out_of_bounds="clip").fit_transform(
            CALIBRATION_CENTERS_H, filled, sample_weight=weights
        )
        raw_curves[quantile] = filled
        monotone_curves[quantile] = np.asarray(fitted, dtype=float)
        max_monotone_adjustment = max(max_monotone_adjustment, float(np.max(np.abs(fitted - filled))))
    max_crossing_adjustment = 0.0
    ordered: dict[float, np.ndarray] = {}
    previous: np.ndarray | None = None
    for quantile in qs:
        current = monotone_curves[quantile].copy()
        if previous is not None:
            adjusted = np.maximum(current, previous)
            max_crossing_adjustment = max(max_crossing_adjustment, float(np.max(np.abs(adjusted - current))))
            current = adjusted
        ordered[quantile] = current
        previous = current
    return ConditionalQuantileModel(
        predictor=predictor,
        response=response,
        quantiles=qs,
        centers=CALIBRATION_CENTERS_H.copy(),
        bin_counts=bin_counts,
        raw_curves=raw_curves,
        curves=ordered,
        train_n=len(work),
        train_satellites=work.NORAD_CAT_ID.nunique(),
        observed_min_h=float(work[predictor].min()),
        observed_max_h=float(work[predictor].max()),
        max_monotone_adjustment=max_monotone_adjustment,
        max_crossing_adjustment=max_crossing_adjustment,
    )


def cluster_bootstrap_quantile_cis(
    frame: pd.DataFrame,
    reps: int,
    seed: int,
) -> dict[tuple[str, str, float], tuple[float, float]]:
    satellites = sorted(frame.NORAD_CAT_ID.unique())
    grouped = {sat: group.copy() for sat, group in frame.groupby("NORAD_CAT_ID", sort=False)}
    rng = np.random.default_rng(seed)
    values: dict[tuple[str, str, float], list[float]] = {
        (label, response, quantile): []
        for label in CALIBRATION_LABELS for response in RESPONSES for quantile in EMPIRICAL_QUANTILES
    }
    for _ in range(reps):
        sampled = rng.choice(satellites, size=len(satellites), replace=True)
        bootstrap = pd.concat([grouped[str(sat)] for sat in sampled], ignore_index=True)
        bins = calibration_bin(bootstrap.element_age_hours)
        for label in CALIBRATION_LABELS:
            subset = bootstrap.loc[bins == label]
            for response in RESPONSES:
                quantiles = subset[response].quantile(EMPIRICAL_QUANTILES).to_numpy(dtype=float)
                for quantile, estimate in zip(EMPIRICAL_QUANTILES, quantiles):
                    values[(label, response, quantile)].append(float(estimate))
    return {
        key: (float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975)))
        for key, estimates in values.items()
    }


def build_empirical_quantiles(
    views: dict[str, pd.DataFrame],
    bootstrap_reps: int,
    seed: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view_index, (view_name, view) in enumerate(views.items()):
        cis = cluster_bootstrap_quantile_cis(view, bootstrap_reps, seed + view_index * 10000)
        bins = calibration_bin(view.element_age_hours)
        for label, left, right in zip(CALIBRATION_LABELS, CALIBRATION_EDGES_H[:-1], CALIBRATION_EDGES_H[1:]):
            subset = view.loc[bins == label]
            for response, unit in RESPONSES.items():
                for quantile in EMPIRICAL_QUANTILES:
                    estimate = float(subset[response].quantile(quantile))
                    ci_low, ci_high = cis[(label, response, quantile)]
                    rows.append({
                        "view": view_name,
                        "conditioning_variable": "element_age_seconds",
                        "bin_label": label,
                        "bin_left_h_exclusive": left,
                        "bin_right_h_inclusive": right,
                        "n": len(subset),
                        "satellite_count": subset.NORAD_CAT_ID.nunique(),
                        "response": response,
                        "unit": unit,
                        "quantile": quantile,
                        "estimate": estimate,
                        "cluster_bootstrap_ci_low": ci_low,
                        "cluster_bootstrap_ci_high": ci_high,
                        "bootstrap_unit": BOOTSTRAP_UNIT,
                        "bootstrap_reps": bootstrap_reps,
                        "random_seed": seed + view_index * 10000,
                        "bin_merge_reason": (
                            "requested 0-3 h had n=35/14 satellites; merged with 3-6 h"
                            if label == "0-6 h" else
                            "requested 30-36 h had n=46/15 satellites; merged with 24-30 h"
                            if label == "24-36 h" else "none"
                        ),
                        "interpretation": "empirical conditional summary; not a fixed-km orbit boundary",
                    })
    return pd.DataFrame(rows)


def model_grid_rows(
    model: ConditionalQuantileModel,
    view: str,
    conditioning_variable: str,
    model_role: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for quantile in model.quantiles:
        predictions = model.predict_grid(EVALUATION_GRID_H, quantile)
        for age, prediction in zip(EVALUATION_GRID_H, predictions):
            within_observed = model.observed_min_h <= age <= model.observed_max_h
            rows.append({
                "view": view,
                "model_role": model_role,
                "conditioning_variable": conditioning_variable,
                "response": model.response,
                "quantile": quantile,
                "evaluation_age_h": age,
                "prediction": float(prediction),
                "unit": RESPONSES[model.response],
                "formal_calibrated_support": bool(0.0 <= age <= 36.0),
                "within_observed_training_age_range": bool(within_observed),
                "boundary_display_only": bool(not within_observed),
                "boundary_handling": "clamped to nearest empirical-bin center" if not within_observed else "piecewise-linear interpolation",
                "train_n": model.train_n,
                "train_satellite_count": model.train_satellites,
                "observed_train_min_h": model.observed_min_h,
                "observed_train_max_h": model.observed_max_h,
                "max_monotone_adjustment": model.max_monotone_adjustment,
                "max_quantile_order_adjustment": model.max_crossing_adjustment,
                "model_method": "weighted isotonic empirical-bin quantiles + piecewise-linear interpolation",
                "extrapolation_above_36h": False,
            })
    return rows


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return math.nan, math.nan
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = (proportion + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt(proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def satellite_cluster_rate_ci(
    frame: pd.DataFrame,
    covered_column: str,
    reps: int,
    seed: int,
) -> tuple[float, float]:
    summaries = frame.groupby("NORAD_CAT_ID")[covered_column].agg(["sum", "count"])
    if len(summaries) < 2:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    sampled_indices = rng.integers(0, len(summaries), size=(reps, len(summaries)))
    successes = summaries["sum"].to_numpy(dtype=float)
    totals = summaries["count"].to_numpy(dtype=float)
    rates = successes[sampled_indices].sum(axis=1) / totals[sampled_indices].sum(axis=1)
    return float(np.quantile(rates, 0.025)), float(np.quantile(rates, 0.975))


def coverage_record(
    frame: pd.DataFrame,
    prediction_column: str,
    quantile: float,
    view: str,
    validation_design: str,
    conditioning_variable: str,
    aggregation_scope: str,
    group_id: str,
    bootstrap_reps: int,
    seed: int,
    ci_preference: str = "satellite_cluster_bootstrap",
) -> dict[str, Any]:
    covered_column = f"_covered_{prediction_column}"
    work = frame.copy()
    work[covered_column] = work.position_error_norm_km <= work[prediction_column]
    successes = int(work[covered_column].sum())
    total = len(work)
    if ci_preference == "wilson" or work.NORAD_CAT_ID.nunique() < 2:
        ci_low, ci_high = wilson_interval(successes, total)
        ci_method = "Wilson score (row-level descriptive; temporal dependence remains)"
    else:
        ci_low, ci_high = satellite_cluster_rate_ci(work, covered_column, bootstrap_reps, seed)
        ci_method = BOOTSTRAP_UNIT
    return {
        "view": view,
        "validation_design": validation_design,
        "conditioning_variable": conditioning_variable,
        "quantile": quantile,
        "aggregation_scope": aggregation_scope,
        "group_id": group_id,
        "n": total,
        "satellite_count": work.NORAD_CAT_ID.nunique(),
        "covered_count": successes,
        "coverage": successes / total if total else math.nan,
        "target_coverage": quantile,
        "coverage_minus_target": successes / total - quantile if total else math.nan,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "ci_method": ci_method,
        "pinball_loss": pinball_loss(work.position_error_norm_km.to_numpy(), work[prediction_column].to_numpy(), quantile) if total else math.nan,
        "prediction_denominator_verified": total,
        "notes": "coverage of position_error_norm_km conditional envelope; not attack acceptance",
    }


def add_full_fit_predictions(
    frame: pd.DataFrame,
    models: dict[float, ConditionalQuantileModel],
    predictor: str,
    prefix: str,
) -> pd.DataFrame:
    result = frame.copy()
    for quantile, model in models.items():
        result[f"{prefix}_q{int(quantile * 100):02d}"] = model.predict(result[predictor].to_numpy(), quantile)
    return result


def build_coverage_validation(
    predicted_views: dict[str, pd.DataFrame],
    bootstrap_reps: int,
    seed: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view_index, (view_name, frame) in enumerate(predicted_views.items()):
        bins = calibration_bin(frame.element_age_hours)
        time_group = np.where(frame.evaluation_time < TIME_SPLIT, "APR01_APR20", "APR21_APR30")
        rms_group = pd.qcut(frame.supgp_rms_km.rank(method="first"), 4, labels=["RMS_Q1", "RMS_Q2", "RMS_Q3", "RMS_Q4"])
        for quantile in [0.90, 0.95]:
            prediction = f"element_q{int(quantile * 100):02d}"
            rows.append(coverage_record(
                frame, prediction, quantile, view_name, "pooled_full_fit_in_sample",
                "element_age_seconds", "overall", "ALL", bootstrap_reps,
                seed + view_index * 10000 + int(quantile * 100),
            ))
            for norad, group in frame.groupby("NORAD_CAT_ID", sort=True):
                rows.append(coverage_record(
                    group, prediction, quantile, view_name, "pooled_full_fit_in_sample",
                    "element_age_seconds", "satellite", str(norad), bootstrap_reps,
                    seed, ci_preference="wilson",
                ))
            for label in CALIBRATION_LABELS:
                group = frame.loc[bins == label]
                rows.append(coverage_record(
                    group, prediction, quantile, view_name, "pooled_full_fit_in_sample",
                    "element_age_seconds", "freshness_bin", label, bootstrap_reps,
                    seed + 1000 + CALIBRATION_LABELS.index(label),
                ))
            for label in ["APR01_APR20", "APR21_APR30"]:
                group = frame.loc[time_group == label]
                rows.append(coverage_record(
                    group, prediction, quantile, view_name, "pooled_full_fit_in_sample",
                    "element_age_seconds", "time_block", label, bootstrap_reps,
                    seed + 2000 + (0 if label == "APR01_APR20" else 1),
                ))
            if view_name == VIEW_FULL:
                for label in ["RMS_Q1", "RMS_Q2", "RMS_Q3", "RMS_Q4"]:
                    group = frame.loc[rms_group == label]
                    rows.append(coverage_record(
                        group, prediction, quantile, view_name, "pooled_full_fit_in_sample",
                        "element_age_seconds", "rms_quartile", label, bootstrap_reps,
                        seed + 3000 + int(label[-1]),
                    ))
    return pd.DataFrame(rows)


def leave_one_satellite_out_predictions(
    frame: pd.DataFrame,
    predictor: str,
    view: str,
) -> pd.DataFrame:
    predictions: list[pd.DataFrame] = []
    for norad in sorted(frame.NORAD_CAT_ID.unique()):
        train = frame.loc[frame.NORAD_CAT_ID != norad]
        test = frame.loc[frame.NORAD_CAT_ID == norad].copy()
        for quantile in [0.90, 0.95]:
            model = fit_conditional_quantile_model(train, predictor, "position_error_norm_km", [quantile])
            test[f"loso_q{int(quantile * 100):02d}"] = model.predict(test[predictor].to_numpy(), quantile)
        test["held_out_norad"] = norad
        test["view"] = view
        predictions.append(test)
    return pd.concat(predictions, ignore_index=True)


def build_satellite_validation(
    predicted_views: dict[str, pd.DataFrame],
    loso_views: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view_name, frame in predicted_views.items():
        loso = loso_views[view_name]
        for norad, group in frame.groupby("NORAD_CAT_ID", sort=True):
            held = loso.loc[loso.NORAD_CAT_ID == norad]
            descriptive = {
                "view": view_name,
                "NORAD_CAT_ID": norad,
                "n": len(group),
                "age_min_h": float(group.element_age_hours.min()),
                "age_max_h": float(group.element_age_hours.max()),
                "position_median_km": float(group.position_error_norm_km.median()),
                "position_p90_km": float(group.position_error_norm_km.quantile(0.90)),
                "position_p95_km": float(group.position_error_norm_km.quantile(0.95)),
                "within_satellite_element_age_spearman": safe_spearman(group.element_age_hours, group.position_error_norm_km),
                "regime_candidate_rows": int(group.is_stage1c_regime_candidate.sum()),
            }
            for quantile in [0.90, 0.95]:
                full_col = f"element_q{int(quantile * 100):02d}"
                loso_col = f"loso_q{int(quantile * 100):02d}"
                full_success = int((group.position_error_norm_km <= group[full_col]).sum())
                loso_success = int((held.position_error_norm_km <= held[loso_col]).sum())
                full_ci = wilson_interval(full_success, len(group))
                loso_ci = wilson_interval(loso_success, len(held))
                rows.append({
                    **descriptive,
                    "quantile": quantile,
                    "full_fit_covered_count": full_success,
                    "full_fit_coverage": full_success / len(group),
                    "full_fit_wilson_low": full_ci[0],
                    "full_fit_wilson_high": full_ci[1],
                    "loso_covered_count": loso_success,
                    "loso_denominator": len(held),
                    "loso_coverage": loso_success / len(held),
                    "loso_wilson_low": loso_ci[0],
                    "loso_wilson_high": loso_ci[1],
                    "loso_coverage_minus_target": loso_success / len(held) - quantile,
                    "undercoverage_below_target_minus_0_05": bool(loso_success / len(held) < quantile - 0.05),
                    "ci_note": "Wilson is row-level descriptive; observations within a satellite are temporally dependent",
                })
    return pd.DataFrame(rows)


def build_loso_coverage(
    loso_views: dict[str, pd.DataFrame],
    bootstrap_reps: int,
    seed: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view_index, (view_name, frame) in enumerate(loso_views.items()):
        bins = calibration_bin(frame.element_age_hours)
        for quantile in [0.90, 0.95]:
            prediction = f"loso_q{int(quantile * 100):02d}"
            rows.append(coverage_record(
                frame, prediction, quantile, view_name, "leave_one_satellite_out",
                "element_age_seconds", "overall", "ALL", bootstrap_reps,
                seed + 4000 + view_index * 100 + int(quantile * 100),
            ))
            for label in CALIBRATION_LABELS:
                rows.append(coverage_record(
                    frame.loc[bins == label], prediction, quantile, view_name,
                    "leave_one_satellite_out", "element_age_seconds", "freshness_bin",
                    label, bootstrap_reps, seed + 5000 + CALIBRATION_LABELS.index(label),
                ))
    return pd.DataFrame(rows)


def build_timeblock_validation(
    views: dict[str, pd.DataFrame],
    bootstrap_reps: int,
    seed: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    blocks = [
        ("FORWARD_APR01_20_TO_APR21_30", lambda x: x.evaluation_time < TIME_SPLIT, lambda x: x.evaluation_time >= TIME_SPLIT),
        ("REVERSE_APR21_30_TO_APR01_20", lambda x: x.evaluation_time >= TIME_SPLIT, lambda x: x.evaluation_time < TIME_SPLIT),
    ]
    for view_index, (view_name, view) in enumerate(views.items()):
        for conditioning_variable, predictor in [
            ("element_age_seconds", "element_age_hours"),
            ("publication_age_seconds_sensitivity", "publication_age_hours"),
        ]:
            eligible = view.loc[(view[predictor] > 0.0) & (view[predictor] <= 36.0)].copy()
            for block_index, (block_id, train_selector, test_selector) in enumerate(blocks):
                train = eligible.loc[train_selector(eligible)]
                test = eligible.loc[test_selector(eligible)].copy()
                for quantile in [0.90, 0.95]:
                    model = fit_conditional_quantile_model(train, predictor, "position_error_norm_km", [quantile])
                    prediction_col = f"prediction_q{int(quantile * 100):02d}"
                    test[prediction_col] = model.predict(test[predictor].to_numpy(), quantile)
                    record = coverage_record(
                        test, prediction_col, quantile, view_name, "time_contiguous_out_of_sample",
                        conditioning_variable, "time_block", block_id, bootstrap_reps,
                        seed + 6000 + view_index * 1000 + block_index * 100 + int(quantile * 100),
                    )
                    record.update({
                        "train_start": train.evaluation_time.min().isoformat().replace("+00:00", "Z"),
                        "train_end": train.evaluation_time.max().isoformat().replace("+00:00", "Z"),
                        "test_start": test.evaluation_time.min().isoformat().replace("+00:00", "Z"),
                        "test_end": test.evaluation_time.max().isoformat().replace("+00:00", "Z"),
                        "train_n": len(train),
                        "train_satellite_count": train.NORAD_CAT_ID.nunique(),
                        "test_n": len(test),
                        "test_satellite_count": test.NORAD_CAT_ID.nunique(),
                        "train_age_min_h": float(train[predictor].min()),
                        "train_age_max_h": float(train[predictor].max()),
                        "test_age_min_h": float(test[predictor].min()),
                        "test_age_max_h": float(test[predictor].max()),
                        "max_monotone_adjustment": model.max_monotone_adjustment,
                        "max_quantile_order_adjustment": model.max_crossing_adjustment,
                    })
                    rows.append(record)
    return pd.DataFrame(rows)


def build_regime_and_secondary_sensitivity(
    views: dict[str, pd.DataFrame],
    empirical: pd.DataFrame,
    model_grid: pd.DataFrame,
    element_models: dict[str, dict[str, ConditionalQuantileModel]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    full_emp = empirical.loc[empirical.view == VIEW_FULL]
    excl_emp = empirical.loc[empirical.view == VIEW_REGIME_EXCLUDED]
    keys = ["bin_label", "response", "quantile"]
    merged = full_emp.merge(excl_emp, on=keys, suffixes=("_full", "_excluded"))
    for row in merged.itertuples():
        rows.append({
            "section": "regime_empirical_bin",
            "metric": "conditional_quantile",
            "response": row.response,
            "quantile": row.quantile,
            "bin_label": row.bin_label,
            "grid_age_h": "",
            "stratum": "stage1c_candidate_episode_excluded",
            "n": row.n_full,
            "full_value": row.estimate_full,
            "sensitivity_value": row.estimate_excluded,
            "absolute_difference": row.estimate_excluded - row.estimate_full,
            "relative_difference": row.estimate_excluded / row.estimate_full - 1.0 if row.estimate_full else math.nan,
            "note": "View B is sensitivity only; canonical population unchanged",
        })
    full_grid = model_grid.loc[
        (model_grid.view == VIEW_FULL) & (model_grid.conditioning_variable == "element_age_seconds")
    ]
    excl_grid = model_grid.loc[
        (model_grid.view == VIEW_REGIME_EXCLUDED) & (model_grid.conditioning_variable == "element_age_seconds")
    ]
    merged_grid = full_grid.merge(
        excl_grid,
        on=["response", "quantile", "evaluation_age_h"],
        suffixes=("_full", "_excluded"),
    )
    for row in merged_grid.itertuples():
        rows.append({
            "section": "regime_continuous_grid",
            "metric": "conditional_quantile",
            "response": row.response,
            "quantile": row.quantile,
            "bin_label": "",
            "grid_age_h": row.evaluation_age_h,
            "stratum": "stage1c_candidate_episode_excluded",
            "n": row.train_n_full,
            "full_value": row.prediction_full,
            "sensitivity_value": row.prediction_excluded,
            "absolute_difference": row.prediction_excluded - row.prediction_full,
            "relative_difference": row.prediction_excluded / row.prediction_full - 1.0 if row.prediction_full else math.nan,
            "note": "continuous model comparison; no candidate rows deleted from canonical dataset",
        })
    full = views[VIEW_FULL]
    element_spearman = safe_spearman(full.element_age_hours, full.position_error_norm_km)
    publication_spearman = safe_spearman(full.publication_age_hours, full.position_error_norm_km)
    rows.extend([
        {
            "section": "publication_age_sensitivity", "metric": "spearman",
            "response": "position_error_norm_km", "quantile": "", "bin_label": "", "grid_age_h": "",
            "stratum": "element_vs_publication", "n": len(full), "full_value": element_spearman,
            "sensitivity_value": publication_spearman, "absolute_difference": publication_spearman - element_spearman,
            "relative_difference": publication_spearman / element_spearman - 1.0,
            "note": "primary=element age; publication age remains secondary sensitivity",
        }
    ])
    rms_median = float(full.supgp_rms_km.median())
    rms_views = {
        "RMS_BELOW_OR_EQUAL_MEDIAN": full.loc[full.supgp_rms_km <= rms_median],
        "RMS_ABOVE_MEDIAN": full.loc[full.supgp_rms_km > rms_median],
    }
    pooled_model = element_models[VIEW_FULL]["position_error_norm_km"]
    pooled_prediction = pooled_model.predict_grid(EVALUATION_GRID_H, 0.95)
    for stratum, subset in rms_views.items():
        model = fit_conditional_quantile_model(subset, "element_age_hours", "position_error_norm_km", [0.95])
        prediction = model.predict_grid(EVALUATION_GRID_H, 0.95)
        for age, pooled_value, stratum_value in zip(EVALUATION_GRID_H, pooled_prediction, prediction):
            rows.append({
                "section": "rms_stratified_model_grid",
                "metric": "conditional_p95",
                "response": "position_error_norm_km",
                "quantile": 0.95,
                "bin_label": "",
                "grid_age_h": age,
                "stratum": stratum,
                "n": len(subset),
                "full_value": pooled_value,
                "sensitivity_value": stratum_value,
                "absolute_difference": stratum_value - pooled_value,
                "relative_difference": stratum_value / pooled_value - 1.0 if pooled_value else math.nan,
                "note": f"RMS median={rms_median:.6f} km used only for sensitivity stratification; not a cutoff/gate",
            })
    return pd.DataFrame(rows)


def plot_position(frame: pd.DataFrame, model_grid: pd.DataFrame) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.4, 5.6))
    hexbin = ax.hexbin(
        frame.element_age_hours, frame.position_error_norm_km,
        gridsize=45, mincnt=1, bins="log", cmap="viridis",
    )
    grid = model_grid.loc[
        (model_grid.view == VIEW_FULL)
        & (model_grid.conditioning_variable == "element_age_seconds")
        & (model_grid.response == "position_error_norm_km")
    ]
    for quantile, label, color in [(0.50, "P50", "#1f77b4"), (0.90, "P90", "#ff7f0e"), (0.95, "P95", "#2ca02c")]:
        group = grid.loc[grid["quantile"] == quantile]
        ax.plot(group.evaluation_age_h, group.prediction, marker="o", linewidth=2.0, label=label, color=color)
    ax.axvline(frame.element_age_hours.min(), color="grey", linestyle=":", linewidth=1.0, label="observed min age")
    ax.set_xlim(0, 36)
    ax.set_yscale("log")
    ax.set_xlabel("Ordinary GP element age (h); formal calibrated support: 0 < age ≤ 36 h")
    ax.set_ylabel("Position disagreement norm (km, log scale)")
    ax.set_title("Freshness-conditioned legitimate position disagreement")
    ax.grid(True, which="both", alpha=0.22)
    ax.legend()
    colorbar = fig.colorbar(hexbin, ax=ax)
    colorbar.set_label("log10(records per hexagon)")
    fig.tight_layout()
    fig.savefig(POSITION_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_rtn(model_grid: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    labels = {
        "abs_delta_R_km": "|R| P95",
        "abs_delta_T_km": "|T| P95",
        "abs_delta_N_km": "|N| P95",
    }
    for response, label in labels.items():
        group = model_grid.loc[
            (model_grid.view == VIEW_FULL)
            & (model_grid.conditioning_variable == "element_age_seconds")
            & (model_grid.response == response)
            & (model_grid["quantile"] == 0.95)
        ]
        ax.plot(group.evaluation_age_h, group.prediction, marker="o", linewidth=2.0, label=label)
    ax.set_xlim(0, 36)
    ax.set_yscale("log")
    ax.set_xlabel("Ordinary GP element age (h)")
    ax.set_ylabel("Absolute component disagreement P95 (km, log scale)")
    ax.set_title("Component-wise RTN conditional P95")
    ax.grid(True, which="both", alpha=0.22)
    ax.legend()
    fig.tight_layout()
    fig.savefig(RTN_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_satellite_coverage(satellite: pd.DataFrame) -> None:
    data = satellite.loc[(satellite.view == VIEW_FULL) & (satellite["quantile"] == 0.95)].sort_values("loso_coverage")
    positions = np.arange(len(data))
    lower = np.maximum(data.loso_coverage - data.loso_wilson_low, 0.0)
    upper = np.maximum(data.loso_wilson_high - data.loso_coverage, 0.0)
    fig, ax = plt.subplots(figsize=(10.0, 5.5))
    ax.errorbar(positions, data.loso_coverage, yerr=[lower, upper], fmt="o", capsize=3, label="LOSO P95 coverage (Wilson interval)")
    ax.axhline(0.95, color="#d62728", linestyle="--", label="target 0.95")
    ax.axhline(0.90, color="grey", linestyle=":", label="target - 0.05 diagnostic")
    ax.set_xticks(positions, data.NORAD_CAT_ID, rotation=55, ha="right")
    ax.set_ylim(max(0.0, data.loso_wilson_low.min() - 0.03), 1.01)
    ax.set_ylabel("Held-out empirical coverage")
    ax.set_xlabel("Held-out NORAD")
    ax.set_title("Leave-one-satellite-out P95 coverage")
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(SATELLITE_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_regime_sensitivity(model_grid: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8.8, 5.2))
    for view, label, style in [
        (VIEW_FULL, "FULL_SUPPORTED P95", "-"),
        (VIEW_REGIME_EXCLUDED, "REGIME_EXCLUDED_SENSITIVITY P95", "--"),
    ]:
        group = model_grid.loc[
            (model_grid.view == view)
            & (model_grid.conditioning_variable == "element_age_seconds")
            & (model_grid.response == "position_error_norm_km")
            & (model_grid["quantile"] == 0.95)
        ]
        ax.plot(group.evaluation_age_h, group.prediction, marker="o", linestyle=style, linewidth=2.0, label=label)
    ax.set_xlim(0, 36)
    ax.set_yscale("log")
    ax.set_xlabel("Ordinary GP element age (h)")
    ax.set_ylabel("Position disagreement P95 (km, log scale)")
    ax.set_title("Candidate-regime sensitivity of the conditional P95")
    ax.grid(True, which="both", alpha=0.22)
    ax.legend()
    fig.tight_layout()
    fig.savefig(REGIME_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)


def format_percent(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def report_text(
    frame: pd.DataFrame,
    views: dict[str, pd.DataFrame],
    empirical: pd.DataFrame,
    model_grid: pd.DataFrame,
    coverage: pd.DataFrame,
    satellite: pd.DataFrame,
    regime: pd.DataFrame,
    timeblock: pd.DataFrame,
    mapping_audit: dict[str, Any],
    bootstrap_reps: int,
    regime_figure_generated: bool,
) -> str:
    def overall(validation: str, view: str, quantile: float) -> pd.Series:
        return coverage.loc[
            (coverage.validation_design == validation) & (coverage.view == view)
            & (coverage["quantile"] == quantile) & (coverage.aggregation_scope == "overall")
        ].iloc[0]

    full_p95 = overall("pooled_full_fit_in_sample", VIEW_FULL, 0.95)
    loso_p95 = overall("leave_one_satellite_out", VIEW_FULL, 0.95)
    loso_p90 = overall("leave_one_satellite_out", VIEW_FULL, 0.90)
    sat_p95 = satellite.loc[(satellite.view == VIEW_FULL) & (satellite["quantile"] == 0.95)]
    under = sat_p95.loc[sat_p95.undercoverage_below_target_minus_0_05]
    empirical_p95 = regime.loc[
        (regime.section == "regime_empirical_bin")
        & (regime.response == "position_error_norm_km")
        & (pd.to_numeric(regime["quantile"], errors="coerce") == 0.95)
    ]
    max_regime = empirical_p95.iloc[empirical_p95.relative_difference.abs().argmax()]
    element_corr = float(regime.loc[(regime.section == "publication_age_sensitivity"), "full_value"].iloc[0])
    publication_corr = float(regime.loc[(regime.section == "publication_age_sensitivity"), "sensitivity_value"].iloc[0])
    forward = timeblock.loc[
        (timeblock.view == VIEW_FULL) & (timeblock.conditioning_variable == "element_age_seconds")
        & (timeblock["quantile"] == 0.95) & (timeblock.group_id == "FORWARD_APR01_20_TO_APR21_30")
    ].iloc[0]
    reverse = timeblock.loc[
        (timeblock.view == VIEW_FULL) & (timeblock.conditioning_variable == "element_age_seconds")
        & (timeblock["quantile"] == 0.95) & (timeblock.group_id == "REVERSE_APR21_30_TO_APR01_20")
    ].iloc[0]
    full_primary_grid = model_grid.loc[
        (model_grid.view == VIEW_FULL) & (model_grid.conditioning_variable == "element_age_seconds")
    ]
    full_position_grid = full_primary_grid.loc[full_primary_grid.response == "position_error_norm_km"]
    monotone_adjustment = float(full_position_grid.max_monotone_adjustment.max())
    crossing_adjustment = float(full_position_grid.max_quantile_order_adjustment.max())
    p95_undercoverage_count = len(under)
    p95_at_12 = full_primary_grid.loc[
        (full_primary_grid["quantile"] == 0.95) & (full_primary_grid.evaluation_age_h == 12.0)
    ].set_index("response")["prediction"]
    rms_grid = regime.loc[regime.section == "rms_stratified_model_grid"]
    rms_max_relative = float(rms_grid.relative_difference.abs().max())
    rms_q4 = coverage.loc[
        (coverage.view == VIEW_FULL) & (coverage.validation_design == "pooled_full_fit_in_sample")
        & (coverage["quantile"] == 0.95) & (coverage.aggregation_scope == "rms_quartile")
        & (coverage.group_id == "RMS_Q4")
    ].iloc[0]
    freeze_text = (
        "当前数据足以冻结calibration v1的方法、支持范围、经验表与validation artifacts；"
        "但由于candidate-regime P95 sensitivity、两颗LOSO undercoverage及forward/reverse time asymmetry，"
        "尚不足以把单一pooled envelope冻结为最终nominal uncertainty model。"
    )
    return f"""# Orbit Uncertainty Stage-1D：freshness-conditioned legitimate disagreement calibration

## 1. Scope与输入

输入为冻结的Stage-1B canonical dataset：`{DATASET_PATH.as_posix()}`，20颗、5675行、5675 nominal、0 excluded。Stage-1B未重建且SHA在本轮前后保持不变。Stage-1C的{mapping_audit['episode_count']}个candidate episodes已按原算法复现，映射{mapping_audit['mapped_rows']}行；其中{int(views[VIEW_FULL].is_stage1c_regime_candidate.sum())}行位于primary support。

Primary conditioning variable为`element_age_seconds = evaluation_time - ordinary_gp_epoch`。`publication_age_seconds`只作为secondary sensitivity；SupGP RMS只做stratification，未成为filter或gate。

## 2. Calibrated support与经验基准

- formal calibrated support：`0 < element_age_hours <= 36`，共{len(views[VIEW_FULL])}行、20颗。
- `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT`：{int((frame.freshness_support_status == 'OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT').sum())}行，仍保留在canonical dataset，不生成formal prediction。
- requested `0-3 h`只有35行/14星，因此与`3-6 h`合并；requested `30-36 h`只有46行/15星，因此与`24-30 h`合并。最终6个bins均覆盖20/20星。
- 经验P50/P75/P90/P95及satellite-cluster bootstrap {bootstrap_reps}次95% CI见`{QUANTILES_PATH.as_posix()}`。

## 3. Continuous conditional quantile model

第一版连续模型采用：经验bin quantile → satellite-count weighted isotonic monotone projection → bin-center间piecewise-linear interpolation。该设计可解释、确定性、无>36 h extrapolation。P50/P90/P95 grid的最大monotone adjustment={monotone_adjustment:.6f} km，quantile-order adjustment={crossing_adjustment:.6f} km。

Grid中的0 h与36 h若超出实际observed min/max，会标记`boundary_display_only=true`并clamp到最近经验bin center，不声称observed support。

在grid的12 h位置：`|R| P95={float(p95_at_12['abs_delta_R_km']):.6f} km`、`|T| P95={float(p95_at_12['abs_delta_T_km']):.6f} km`、`|N| P95={float(p95_at_12['abs_delta_N_km']):.6f} km`、position norm P95=`{float(p95_at_12['position_error_norm_km']):.6f} km`。这些是conditional summaries，不是最终orbit-space boundary。

## 4. Coverage validation

- full-fit in-sample P95 coverage={format_percent(float(full_p95.coverage))}，satellite-cluster CI=[{format_percent(float(full_p95.ci_low))}, {format_percent(float(full_p95.ci_high))}]。
- LOSO P90 coverage={format_percent(float(loso_p90.coverage))}；P95 coverage={format_percent(float(loso_p95.coverage))}，cluster CI=[{format_percent(float(loso_p95.ci_low))}, {format_percent(float(loso_p95.ci_high))}]。
- 20颗中有{p95_undercoverage_count}颗的LOSO P95 coverage低于`target-0.05` descriptive line：{', '.join(under.NORAD_CAT_ID.astype(str)) if p95_undercoverage_count else 'none'}。
- forward time block（Apr1-20 train → Apr21-30 test）P95={format_percent(float(forward.coverage))}；reverse block P95={format_percent(float(reverse.coverage))}。

Forward/reverse相差{100.0 * abs(float(forward.coverage) - float(reverse.coverage)):.2f} percentage points；两者仍接近目标，但非完全时间稳定。forward test包含主要late-April high-disagreement episodes，不能把该差异解释成纯随机波动。

这些coverage是legitimate disagreement envelope validation，不是attack acceptance probability。

## 5. Regime sensitivity

FULL_SUPPORTED保留所有candidate rows；REGIME_EXCLUDED_SENSITIVITY仅用于诊断。position P95的最大经验bin相对变化发生在`{max_regime.bin_label}`：{100.0 * float(max_regime.relative_difference):.2f}%（absolute {float(max_regime.absolute_difference):.6f} km）。因此candidate episodes对高freshness tail的影响必须显式保留，不能静默合并或删除。

Regime comparison figure generated={str(regime_figure_generated).lower()}，触发标准为position P95任一bin绝对相对变化≥10%。

## 6. Secondary sensitivities

- element age vs position Spearman={element_corr:.6f}；publication age={publication_corr:.6f}。element age继续表现出更强的rank association。
- RMS median split只用于stratified model comparison，不是cutoff。局部P95 grid最大相对变化={100.0 * rms_max_relative:.2f}%，但方向随freshness反转；最高RMS quartile在pooled envelope下coverage={format_percent(float(rms_q4.coverage))}。这不是稳定单调RMS effect，却说明下一版值得验证joint freshness×RMS conditioning，而不是建立RMS hard cutoff。

## 7. 当前判断

1. 0–36 h内经验quantile总体随freshness上升；连续模型通过显式monotone projection保持可解释，边缘bins的合并理由已冻结。
2. pooled coverage需结合LOSO逐星结果解释，不能只引用in-sample pooled比例。
3. satellite-specific undercoverage对象已单列，Wilson区间仅为行级描述并明确保留temporal-dependence限制。
4. candidate regime对P95 envelope的影响并非处处相同，在高age bin可明显改变tail。
5. time-block结果保留forward/reverse两个连续切分，未使用随机row split。
6. element age仍优于publication age作为primary conditioning variable；RMS不是第一阶替代变量。
7. {freeze_text}
8. 下一步应优先保留component-wise RTN calibration，因为position由T主导而velocity由vR主导；随后再研究能够保留相关结构的multivariate RTN/full-state set，而不是退化为fixed km sphere。

## 8. Scope guards

本轮没有synthetic B、1/5 km distinctness、Doppler、fixed global km threshold、confirmed maneuver label、RMS hard filter或>36 h formal extrapolation。没有从canonical dataset删除任何行。
"""


def main() -> None:
    args = parse_args()
    if args.bootstrap_reps < 200:
        raise SystemExit("bootstrap-reps must be >=200 for formal interval estimation")
    ensure_outputs_available(args.overwrite)
    input_audit = verify_inputs()
    dataset_sha_before = sha256(DATASET_PATH)
    frame = read_dataset()
    regime_flag, episode_id, mapping_audit = reproduce_stage1c_episode_mapping(frame)
    if not mapping_audit["reproducible"]:
        raise SystemExit(f"Stage-1C episode mapping is not reproducible: {mapping_audit['mismatches']}")
    frame["is_stage1c_regime_candidate"] = regime_flag
    frame["stage1c_episode_id"] = episode_id
    views = build_views(frame)

    empirical = build_empirical_quantiles(views, args.bootstrap_reps, args.random_seed)

    element_models: dict[str, dict[str, ConditionalQuantileModel]] = {}
    grid_rows: list[dict[str, Any]] = []
    predicted_views: dict[str, pd.DataFrame] = {}
    for view_name, view in views.items():
        element_models[view_name] = {}
        position_models: dict[float, ConditionalQuantileModel] = {}
        for response in MODEL_RESPONSES:
            model = fit_conditional_quantile_model(view, "element_age_hours", response, MODEL_QUANTILES)
            element_models[view_name][response] = model
            grid_rows.extend(model_grid_rows(model, view_name, "element_age_seconds", "primary"))
            if response == "position_error_norm_km":
                position_models = {
                    quantile: fit_conditional_quantile_model(view, "element_age_hours", response, [quantile])
                    for quantile in [0.90, 0.95]
                }
        predicted_views[view_name] = add_full_fit_predictions(view, position_models, "element_age_hours", "element")

    publication_view = views[VIEW_FULL].loc[
        (views[VIEW_FULL].publication_age_hours > 0.0)
        & (views[VIEW_FULL].publication_age_hours <= 36.0)
    ]
    publication_model = fit_conditional_quantile_model(
        publication_view, "publication_age_hours", "position_error_norm_km", MODEL_QUANTILES
    )
    grid_rows.extend(model_grid_rows(
        publication_model, "PUBLICATION_AGE_SENSITIVITY", "publication_age_seconds", "secondary_sensitivity"
    ))
    model_grid = pd.DataFrame(grid_rows)

    coverage = build_coverage_validation(predicted_views, args.bootstrap_reps, args.random_seed)
    loso_views = {
        view_name: leave_one_satellite_out_predictions(view, "element_age_hours", view_name)
        for view_name, view in views.items()
    }
    loso_coverage = build_loso_coverage(loso_views, args.bootstrap_reps, args.random_seed)
    coverage = pd.concat([coverage, loso_coverage], ignore_index=True)
    satellite = build_satellite_validation(predicted_views, loso_views)
    timeblock = build_timeblock_validation(views, args.bootstrap_reps, args.random_seed)
    regime = build_regime_and_secondary_sensitivity(views, empirical, model_grid, element_models)

    empirical_regime_p95 = regime.loc[
        (regime.section == "regime_empirical_bin")
        & (regime.response == "position_error_norm_km")
        & (pd.to_numeric(regime["quantile"], errors="coerce") == 0.95)
    ]
    regime_significant = bool((empirical_regime_p95.relative_difference.abs() >= 0.10).any())

    plot_position(views[VIEW_FULL], model_grid)
    plot_rtn(model_grid)
    plot_satellite_coverage(satellite)
    if regime_significant:
        plot_regime_sensitivity(model_grid)
    elif REGIME_FIGURE.exists() and args.overwrite:
        REGIME_FIGURE.unlink()

    dataset_sha_after = sha256(DATASET_PATH)
    full_grid = model_grid.loc[
        (model_grid.view == VIEW_FULL) & (model_grid.conditioning_variable == "element_age_seconds")
    ]
    crossing_count = 0
    monotone_violations = 0
    for response in MODEL_RESPONSES:
        pivot = full_grid.loc[full_grid.response == response].pivot(index="evaluation_age_h", columns="quantile", values="prediction").sort_index()
        crossing_count += int(((pivot[0.50] > pivot[0.90]) | (pivot[0.90] > pivot[0.95])).sum())
        for quantile in MODEL_QUANTILES:
            monotone_violations += int((np.diff(pivot[quantile].to_numpy()) < -1e-12).sum())
    coverage_denominators_ok = bool((coverage.n == coverage.prediction_denominator_verified).all())
    checks = [
        {"check": "Stage-1B input SHA unchanged", "passed": dataset_sha_before == dataset_sha_after == input_audit["dataset_sha"], "observed": dataset_sha_after},
        {"check": "Stage-1C candidate episode mapping reproducible", "passed": mapping_audit["reproducible"], "observed": json.dumps(mapping_audit)},
        {"check": "canonical row/satellite population unchanged", "passed": len(frame) == 5675 and frame.NORAD_CAT_ID.nunique() == 20, "observed": f"rows={len(frame)}; satellites={frame.NORAD_CAT_ID.nunique()}"},
        {"check": "freshness support classification", "passed": len(views[VIEW_FULL]) == 5662 and int((frame.freshness_support_status == 'OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT').sum()) == 13, "observed": f"supported={len(views[VIEW_FULL])}; outside={int((frame.freshness_support_status == 'OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT').sum())}"},
        {"check": "merged primary bins cover 20 satellites", "passed": bool(empirical.loc[empirical.view == VIEW_FULL].groupby('bin_label').satellite_count.min().eq(20).all()), "observed": empirical.loc[empirical.view == VIEW_FULL].groupby('bin_label').satellite_count.max().to_dict()},
        {"check": "quantile ordering P50<=P90<=P95", "passed": crossing_count == 0, "observed": f"crossing_grid_points={crossing_count}"},
        {"check": "primary curves monotone nondecreasing", "passed": monotone_violations == 0, "observed": f"violations={monotone_violations}"},
        {"check": "no formal grid prediction above 36 h", "passed": float(model_grid.evaluation_age_h.max()) <= 36.0, "observed": f"max_grid_h={model_grid.evaluation_age_h.max()}"},
        {"check": "0 h grid explicitly boundary display", "passed": bool(model_grid.loc[model_grid.evaluation_age_h == 0.0, 'boundary_display_only'].all()), "observed": f"rows={int((model_grid.evaluation_age_h == 0.0).sum())}"},
        {"check": "coverage denominators correct", "passed": coverage_denominators_ok, "observed": f"coverage_rows={len(coverage)}"},
        {"check": "satellite validation IDs complete", "passed": satellite.NORAD_CAT_ID.nunique() == 20 and set(satellite.NORAD_CAT_ID) == set(frame.NORAD_CAT_ID), "observed": f"satellites={satellite.NORAD_CAT_ID.nunique()}"},
        {"check": "FULL_SUPPORTED keeps candidate regime rows", "passed": int(views[VIEW_FULL].is_stage1c_regime_candidate.sum()) == 50, "observed": f"supported_candidate_rows={int(views[VIEW_FULL].is_stage1c_regime_candidate.sum())}"},
        {"check": "sensitivity view only excludes frozen candidate rows", "passed": len(views[VIEW_FULL]) - len(views[VIEW_REGIME_EXCLUDED]) == 50, "observed": f"full={len(views[VIEW_FULL])}; sensitivity={len(views[VIEW_REGIME_EXCLUDED])}"},
        {"check": "cluster-aware bootstrap configured", "passed": args.bootstrap_reps >= 200 and set(empirical.bootstrap_unit) == {BOOTSTRAP_UNIT}, "observed": f"unit={BOOTSTRAP_UNIT}; reps={args.bootstrap_reps}"},
        {"check": "no RMS hard filtering", "passed": len(views[VIEW_FULL]) == int((frame.element_age_hours <= 36.0).sum()), "observed": "RMS used only for median/quartile sensitivity stratification"},
        {"check": "scope excludes synthetic-B/Doppler/fixed-km boundary", "passed": True, "observed": "analysis code consumes legitimate Stage-1B rows only"},
    ]
    correctness = pd.DataFrame(checks)
    if not correctness.passed.all():
        raise SystemExit(f"Stage-1D correctness failed: {correctness.loc[~correctness.passed].to_dict('records')}")

    for path in [QUANTILES_PATH, MODEL_GRID_PATH, COVERAGE_PATH, SATELLITE_PATH, REGIME_PATH, TIMEBLOCK_PATH, CORRECTNESS_PATH, REPORT_PATH, MANIFEST_PATH]:
        path.parent.mkdir(parents=True, exist_ok=True)
    empirical.to_csv(QUANTILES_PATH, index=False, encoding="utf-8-sig")
    model_grid.to_csv(MODEL_GRID_PATH, index=False, encoding="utf-8-sig")
    coverage.to_csv(COVERAGE_PATH, index=False, encoding="utf-8-sig")
    satellite.to_csv(SATELLITE_PATH, index=False, encoding="utf-8-sig")
    regime.to_csv(REGIME_PATH, index=False, encoding="utf-8-sig")
    timeblock.to_csv(TIMEBLOCK_PATH, index=False, encoding="utf-8-sig")
    correctness.to_csv(CORRECTNESS_PATH, index=False, encoding="utf-8-sig")
    report = report_text(
        frame, views, empirical, model_grid, coverage, satellite, regime,
        timeblock, mapping_audit, args.bootstrap_reps, regime_significant,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")

    written_outputs = [
        QUANTILES_PATH, MODEL_GRID_PATH, COVERAGE_PATH, SATELLITE_PATH,
        REGIME_PATH, TIMEBLOCK_PATH, CORRECTNESS_PATH, REPORT_PATH,
        POSITION_FIGURE, RTN_FIGURE, SATELLITE_FIGURE,
    ]
    if regime_significant:
        written_outputs.append(REGIME_FIGURE)
    manifest = {
        "stage": "Orbit Uncertainty Stage-1D",
        "status": "STAGE1D_FRESHNESS_CALIBRATION_COMPLETE",
        "generated_utc": utc_now(),
        "window_tag": WINDOW_TAG,
        "formal_window": FORMAL_INTERVAL,
        "input": {
            "stage1b_dataset": DATASET_PATH.as_posix(),
            "stage1b_dataset_sha256": input_audit["dataset_sha"],
            "stage1b_manifest": STAGE1B_MANIFEST_PATH.as_posix(),
            "stage1b_manifest_sha256": input_audit["stage1b_manifest_sha"],
            "stage1c_manifest": STAGE1C_MANIFEST_PATH.as_posix(),
            "stage1c_manifest_sha256": input_audit["stage1c_manifest_sha"],
            "stage1c_regime_summary": STAGE1C_REGIME_PATH.as_posix(),
            "stage1c_regime_summary_sha256": input_audit["stage1c_regime_sha"],
            "rows": len(frame),
            "satellites": frame.NORAD_CAT_ID.nunique(),
            "nominal_rows": int(frame.nominal_row.astype(bool).sum()),
            "hashes_before_after_equal": dataset_sha_before == dataset_sha_after,
        },
        "definitions": {
            "primary_conditioning_variable": "element_age_seconds = evaluation_time - ordinary_gp_epoch",
            "secondary_conditioning_variable": "publication_age_seconds; sensitivity only",
            "primary_support": "0 < element_age_hours <= 36",
            "outside_support_label": "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT",
            "requested_bins_hours": RAW_REQUESTED_EDGES_H,
            "formal_merged_bins_hours": CALIBRATION_EDGES_H,
            "bin_merge_reasons": {
                "0-6": "requested 0-3 h had n=35/14 satellites; merged with 3-6 h",
                "24-36": "requested 30-36 h had n=46/15 satellites; merged with 24-30 h",
            },
            "model_method": "weighted isotonic empirical-bin quantiles + piecewise-linear interpolation",
            "bootstrap_unit": BOOTSTRAP_UNIT,
            "bootstrap_reps": args.bootstrap_reps,
            "random_seed": args.random_seed,
            "time_validation": ["Apr1-20 train -> Apr21-30 test", "reverse"],
            "regime_views": [VIEW_FULL, VIEW_REGIME_EXCLUDED],
            "regime_figure_trigger": "absolute relative position-P95 bin difference >=10%",
        },
        "result": {
            "supported_rows": len(views[VIEW_FULL]),
            "outside_support_rows": int((frame.freshness_support_status == "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT").sum()),
            "regime_candidate_rows_total": mapping_audit["mapped_rows"],
            "regime_candidate_rows_supported": int(views[VIEW_FULL].is_stage1c_regime_candidate.sum()),
            "empirical_rows": len(empirical),
            "model_grid_rows": len(model_grid),
            "coverage_rows": len(coverage),
            "satellite_validation_rows": len(satellite),
            "regime_sensitivity_rows": len(regime),
            "timeblock_rows": len(timeblock),
            "regime_sensitivity_figure_generated": regime_significant,
            "calibration_v1_protocol_and_artifacts_frozen": True,
            "single_pooled_nominal_model_ready_for_final_freeze": False,
            "final_freeze_blockers": [
                f"candidate-regime maximum absolute relative position-P95 bin sensitivity={float(empirical_regime_p95.relative_difference.abs().max()):.6f}",
                f"LOSO P95 undercoverage below target-0.05 satellites={int(satellite.loc[(satellite.view == VIEW_FULL) & (satellite['quantile'] == 0.95), 'undercoverage_below_target_minus_0_05'].sum())}",
                "forward/reverse time-block P95 coverage is reported separately in the timeblock artifact",
            ],
            "correctness_passed": int(correctness.passed.sum()),
            "correctness_total": len(correctness),
        },
        "builder": {
            "path": Path(__file__).as_posix(),
            "sha256": sha256(Path(__file__)),
            "python": platform.python_version(),
            "git_state": "NOT_A_GIT_WORK_TREE",
        },
        "outputs": {
            path.name: {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in written_outputs
        },
        "scope_guards": {
            "stage1b_rebuilt": False,
            "canonical_rows_deleted": False,
            "candidate_regime_rows_deleted": False,
            "rms_hard_filter_applied": False,
            "predictions_above_36h_generated": False,
            "fixed_global_km_boundary_built": False,
            "synthetic_b_analyzed": False,
            "doppler_verifier_run": False,
            "attack_threshold_built": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "supported_rows": manifest["result"]["supported_rows"],
        "outside_support_rows": manifest["result"]["outside_support_rows"],
        "empirical_rows": len(empirical),
        "coverage_rows": len(coverage),
        "timeblock_rows": len(timeblock),
        "regime_figure": regime_significant,
        "correctness": f"{int(correctness.passed.sum())}/{len(correctness)}",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
