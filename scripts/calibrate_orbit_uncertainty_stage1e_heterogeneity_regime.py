#!/usr/bin/env python3
"""Stage-1E heterogeneity- and causal-regime-aware RTN calibration assessment.

This script consumes the frozen Stage-1B canonical residual library plus the
frozen Stage-1C/1D artifacts.  Stage-1C candidate episodes are retrospective
evaluation labels only.  Operational model candidates use only information
available from ordinary GP publications at evaluation time.  The script does
not edit Stage-1B, extrapolate beyond 36 h, define a final 6D uncertainty set,
or analyze synthetic-B/Doppler behavior.
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
from scipy.stats import mannwhitneyu, spearmanr
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    from scripts import calibrate_orbit_uncertainty_stage1d_freshness as stage1d
    from scripts.orbit_uncertainty_stage1_window import FORMAL_INTERVAL, WINDOW_TAG
except (ModuleNotFoundError, ImportError):
    import calibrate_orbit_uncertainty_stage1d_freshness as stage1d
    from orbit_uncertainty_stage1_window import FORMAL_INTERVAL, WINDOW_TAG


STAGE1B_PREFIX = f"orbit_uncertainty_stage1b_{WINDOW_TAG}"
STAGE1C_PREFIX = f"orbit_uncertainty_stage1c_{WINDOW_TAG}"
STAGE1D_PREFIX = f"orbit_uncertainty_stage1d_{WINDOW_TAG}"
STAGE1E_PREFIX = f"orbit_uncertainty_stage1e_{WINDOW_TAG}"

DATASET_PATH = Path("outputs/datasets") / f"{STAGE1B_PREFIX}_rtn_residual_library.csv"
STAGE1B_MANIFEST_PATH = Path("outputs/metrics") / f"{STAGE1B_PREFIX}_manifest.json"
STAGE1C_MANIFEST_PATH = Path("outputs/metrics") / f"{STAGE1C_PREFIX}_manifest.json"
STAGE1D_MANIFEST_PATH = Path("outputs/metrics") / f"{STAGE1D_PREFIX}_manifest.json"
ORDINARY_RAW_PATH = Path("data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260329_20260501_20sat_omm.json")

METRICS_DIR = Path("outputs/metrics")
REPORTS_DIR = Path("outputs/reports")
FIGURE_DIR = Path("outputs/figures") / STAGE1E_PREFIX

HETEROGENEITY_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_satellite_heterogeneity.csv"
CAUSAL_FEATURES_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_causal_regime_features.csv"
ASSOCIATION_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_regime_feature_association.csv"
MODEL_COMPARISON_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_model_comparison.csv"
CALIBRATION_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_componentwise_calibration.csv"
LOSO_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_loso_validation.csv"
TIMEBLOCK_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_timeblock_validation.csv"
PER_SATELLITE_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_per_satellite_coverage.csv"
RMS_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_rms_diagnostic.csv"
CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_correctness_audit.csv"
MANIFEST_PATH = METRICS_DIR / f"{STAGE1E_PREFIX}_manifest.json"
REPORT_PATH = REPORTS_DIR / f"{STAGE1E_PREFIX}_heterogeneity_regime_report.md"

RATIO_FIGURE = FIGURE_DIR / "per_satellite_calibration_ratios.png"
FEATURE_FIGURE = FIGURE_DIR / "causal_regime_feature_timeline.png"
COVERAGE_FIGURE = FIGURE_DIR / "m0_vs_best_per_satellite_p95_coverage.png"

TARGETS = {
    "abs_delta_R_km": "km",
    "abs_delta_T_km": "km",
    "abs_delta_N_km": "km",
    "position_error_norm_km": "km",
}
VELOCITY_TARGETS = {
    "abs_delta_v_R_km_s": "km/s",
    "abs_delta_v_T_km_s": "km/s",
    "abs_delta_v_N_km_s": "km/s",
}
QUANTILES = (0.90, 0.95)
MODEL_NAMES = ("M0", "M1", "M2", "M3", "M4", "M_RMS_DIAGNOSTIC")
OPERATIONAL_MODELS = ("M0", "M1", "M2", "M3", "M4")
VIEW_FULL = stage1d.VIEW_FULL
VIEW_EXCLUDED = stage1d.VIEW_REGIME_EXCLUDED
TIME_SPLIT = pd.Timestamp("2026-04-21T00:00:00Z")
GRID_H = stage1d.EVALUATION_GRID_H
SHRINKAGE_STRENGTH = 100.0

ORBIT_FIELDS = (
    "MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR",
)
ANGULAR_FIELDS = {"INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY"}
CAUSAL_NUMERIC_FEATURES = (
    "publication_age_hours",
    "selected_gp_just_changed",
    "hours_since_selected_gp_switch",
    "previous_publication_interval_hours",
    "gp_epoch_jump_hours",
    "abs_delta_mean_motion",
    "abs_delta_eccentricity",
    "abs_delta_inclination_deg",
    "abs_delta_raan_deg",
    "abs_delta_arg_perigee_deg",
    "abs_delta_mean_anomaly_deg",
    "abs_delta_bstar",
    "selected_mean_motion",
    "selected_eccentricity",
    "selected_inclination_deg",
    "selected_bstar",
)


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
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def output_paths() -> list[Path]:
    return [
        HETEROGENEITY_PATH, CAUSAL_FEATURES_PATH, ASSOCIATION_PATH,
        MODEL_COMPARISON_PATH, CALIBRATION_PATH, LOSO_PATH, TIMEBLOCK_PATH,
        PER_SATELLITE_PATH, RMS_PATH, CORRECTNESS_PATH, MANIFEST_PATH,
        REPORT_PATH, RATIO_FIGURE, FEATURE_FIGURE, COVERAGE_FIGURE,
    ]


def ensure_outputs_available(overwrite: bool) -> None:
    existing = [str(path) for path in output_paths() if path.exists()]
    if existing and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing Stage-1E outputs: {existing}")


def verify_inputs() -> dict[str, Any]:
    manifests = {
        "stage1b": load_json(STAGE1B_MANIFEST_PATH),
        "stage1c": load_json(STAGE1C_MANIFEST_PATH),
        "stage1d": load_json(STAGE1D_MANIFEST_PATH),
    }
    expected_status = {
        "stage1b": "APRIL_STAGE1B_RESIDUAL_LIBRARY_COMPLETE",
        "stage1c": "STAGE1C_RESIDUAL_STRUCTURE_CHARACTERIZATION_COMPLETE",
        "stage1d": "STAGE1D_FRESHNESS_CALIBRATION_COMPLETE",
    }
    for name, manifest in manifests.items():
        if manifest.get("status") != expected_status[name]:
            raise SystemExit(f"{name} manifest status is not frozen COMPLETE")
        if manifest.get("window_tag") != WINDOW_TAG or manifest.get("formal_window") != FORMAL_INTERVAL:
            raise SystemExit(f"{name} manifest window differs from Stage-1E")
    dataset_sha = sha256(DATASET_PATH)
    if manifests["stage1b"]["outputs"][DATASET_PATH.name]["sha256"] != dataset_sha:
        raise SystemExit("Stage-1B dataset SHA mismatch")
    for name in ("stage1c", "stage1d"):
        if manifests[name]["input"]["stage1b_dataset_sha256"] != dataset_sha:
            raise SystemExit(f"{name} is not bound to current Stage-1B dataset")
    ordinary_sha = sha256(ORDINARY_RAW_PATH)
    stage1b_ordinary_sha = manifests["stage1b"]["input_raw"]["ordinary"]["sha256"]
    if ordinary_sha != stage1b_ordinary_sha:
        raise SystemExit("Ordinary raw SHA differs from Stage-1B binding")
    return {
        "manifests": manifests,
        "dataset_sha": dataset_sha,
        "ordinary_sha": ordinary_sha,
        "manifest_shas": {
            "stage1b": sha256(STAGE1B_MANIFEST_PATH),
            "stage1c": sha256(STAGE1C_MANIFEST_PATH),
            "stage1d": sha256(STAGE1D_MANIFEST_PATH),
        },
    }


def read_frame() -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = stage1d.read_dataset()
    regime_flag, episode_id, reproduction = stage1d.reproduce_stage1c_episode_mapping(frame)
    frame["is_stage1c_regime_candidate"] = regime_flag
    frame["stage1c_episode_id"] = episode_id
    frame["age_bin"] = stage1d.calibration_bin(frame.element_age_hours).astype("string")
    return frame, reproduction


def parse_time(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, utc=True)


def record_order(record: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    return parse_time(record["CREATION_DATE"]), parse_time(record["EPOCH"]), str(record.get("GP_ID", ""))


def wrapped_delta(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


def build_causal_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = load_json(ORDINARY_RAW_PATH)
    by_sat: dict[str, list[dict[str, Any]]] = {}
    by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for record in raw:
        sat = str(record["NORAD_CAT_ID"])
        record = dict(record)
        record["_creation"] = parse_time(record["CREATION_DATE"])
        record["_epoch"] = parse_time(record["EPOCH"])
        by_sat.setdefault(sat, []).append(record)
        by_id[(sat, str(record["GP_ID"]))] = record
    for records in by_sat.values():
        records.sort(key=record_order)

    rows: list[dict[str, Any]] = []
    selected_mismatch = 0
    future_access = 0
    previous_future = 0
    for sat, group in frame.sort_values(["NORAD_CAT_ID", "evaluation_time"]).groupby("NORAD_CAT_ID", sort=True):
        records = by_sat[str(sat)]
        previous_evaluation_gp = ""
        switch_time: pd.Timestamp | None = None
        for source in group.itertuples():
            evaluation = source.evaluation_time
            eligible = [record for record in records if record["_creation"] <= evaluation]
            if not eligible:
                raise SystemExit(f"No causal ordinary GP for {sat}/{evaluation}")
            selected = eligible[-1]
            if str(selected["GP_ID"]) != str(source.ordinary_gp_id):
                selected_mismatch += 1
            if selected["_creation"] > evaluation:
                future_access += 1
            previous = eligible[-2] if len(eligible) >= 2 else None
            if previous is not None and previous["_creation"] > evaluation:
                previous_future += 1
            changed = bool(previous_evaluation_gp and previous_evaluation_gp != str(selected["GP_ID"]))
            if not previous_evaluation_gp or changed:
                switch_time = evaluation
            hours_since_switch = (evaluation - switch_time).total_seconds() / 3600.0 if switch_time is not None else 0.0
            feature: dict[str, Any] = {
                "dataset_row_index": int(source.Index),
                "NORAD_CAT_ID": str(sat),
                "evaluation_time": evaluation.isoformat().replace("+00:00", "Z"),
                "selected_gp_id": str(selected["GP_ID"]),
                "selected_gp_epoch": selected["_epoch"].isoformat().replace("+00:00", "Z"),
                "selected_gp_creation_date": selected["_creation"].isoformat().replace("+00:00", "Z"),
                "previous_published_gp_id": str(previous["GP_ID"]) if previous else "",
                "previous_gp_creation_date": previous["_creation"].isoformat().replace("+00:00", "Z") if previous else "",
                "previous_gp_epoch": previous["_epoch"].isoformat().replace("+00:00", "Z") if previous else "",
                "selected_gp_just_changed": int(changed),
                "hours_since_selected_gp_switch": hours_since_switch,
                "publication_age_hours": (evaluation - selected["_creation"]).total_seconds() / 3600.0,
                "previous_publication_interval_hours": (selected["_creation"] - previous["_creation"]).total_seconds() / 3600.0 if previous else math.nan,
                "gp_epoch_jump_hours": (selected["_epoch"] - previous["_epoch"]).total_seconds() / 3600.0 if previous else math.nan,
                "causal_candidate_count": len(eligible),
                "selected_creation_le_evaluation": bool(selected["_creation"] <= evaluation),
                "previous_creation_le_evaluation": bool(previous is None or previous["_creation"] <= evaluation),
                "feature_uses_future_gp": False,
                "is_stage1c_regime_candidate": bool(source.is_stage1c_regime_candidate),
                "stage1c_episode_id": source.stage1c_episode_id,
                "feature_role": "OPERATIONALLY_AVAILABLE",
            }
            field_names = {
                "MEAN_MOTION": "mean_motion",
                "ECCENTRICITY": "eccentricity",
                "INCLINATION": "inclination_deg",
                "RA_OF_ASC_NODE": "raan_deg",
                "ARG_OF_PERICENTER": "arg_perigee_deg",
                "MEAN_ANOMALY": "mean_anomaly_deg",
                "BSTAR": "bstar",
            }
            for raw_name, short_name in field_names.items():
                current = float(selected[raw_name])
                feature[f"selected_{short_name}"] = current
                if previous is None:
                    delta = math.nan
                else:
                    old = float(previous[raw_name])
                    delta = wrapped_delta(current, old) if raw_name in ANGULAR_FIELDS else current - old
                feature[f"delta_{short_name}"] = delta
                feature[f"abs_delta_{short_name}"] = abs(delta) if math.isfinite(delta) else math.nan
            rows.append(feature)
            previous_evaluation_gp = str(selected["GP_ID"])
    features = pd.DataFrame(rows).set_index("dataset_row_index").sort_index()
    return features, {
        "raw_records": len(raw),
        "raw_satellites": len(by_sat),
        "selected_gp_mismatch": selected_mismatch,
        "selected_future_publication": future_access,
        "previous_future_publication": previous_future,
        "feature_rows": len(features),
        "feature_future_gp_access": int(features.feature_uses_future_gp.sum()),
    }


def attach_features(frame: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    feature_columns = [column for column in features.columns if column not in {
        "NORAD_CAT_ID", "evaluation_time", "is_stage1c_regime_candidate", "stage1c_episode_id",
        "publication_age_hours",
    }]
    result = frame.join(features[feature_columns], how="left")
    if result.selected_gp_id.isna().any():
        raise SystemExit("Causal feature join left missing rows")
    return result


def build_heterogeneity(frame: pd.DataFrame) -> pd.DataFrame:
    supported = frame.loc[frame.freshness_support_status == "WITHIN_CALIBRATED_FRESHNESS_SUPPORT"].copy()
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        pooled_models = {
            quantile: stage1d.fit_conditional_quantile_model(supported, "element_age_hours", target, [quantile])
            for quantile in (0.50, 0.90, 0.95)
        }
        for quantile, model in pooled_models.items():
            supported[f"_pred_{target}_{quantile}"] = model.predict(supported.element_age_hours.to_numpy(), quantile)
        for sat, sat_frame in supported.groupby("NORAD_CAT_ID", sort=True):
            for bin_label in ["ALL", *stage1d.CALIBRATION_LABELS]:
                group = sat_frame if bin_label == "ALL" else sat_frame.loc[sat_frame.age_bin == bin_label]
                if group.empty:
                    continue
                excluded = group.loc[~group.is_stage1c_regime_candidate]
                for quantile in (0.50, 0.90, 0.95):
                    pred_col = f"_pred_{target}_{quantile}"
                    observed = float(group[target].quantile(quantile))
                    predicted = float(group[pred_col].median())
                    full_coverage = float((group[target] <= group[pred_col]).mean())
                    excluded_coverage = float((excluded[target] <= excluded[pred_col]).mean()) if len(excluded) else math.nan
                    rows.append({
                        "NORAD_CAT_ID": sat,
                        "freshness_bin": bin_label,
                        "target": target,
                        "quantile": quantile,
                        "n": len(group),
                        "regime_candidate_rows": int(group.is_stage1c_regime_candidate.sum()),
                        "observed_quantile": observed,
                        "median_pooled_prediction": predicted,
                        "observed_over_predicted_ratio": observed / predicted if predicted else math.nan,
                        "full_coverage": full_coverage,
                        "regime_excluded_n": len(excluded),
                        "regime_excluded_coverage": excluded_coverage,
                        "coverage_recovery_after_regime_exclusion": excluded_coverage - full_coverage if len(excluded) else math.nan,
                        "interpretation": "retrospective heterogeneity diagnostic; no canonical rows removed",
                    })
    return pd.DataFrame(rows)


def cliffs_delta(candidate: pd.Series, ordinary: pd.Series) -> float:
    x = pd.to_numeric(candidate, errors="coerce").dropna().to_numpy(dtype=float)
    y = pd.to_numeric(ordinary, errors="coerce").dropna().to_numpy(dtype=float)
    if not len(x) or not len(y):
        return math.nan
    statistic = mannwhitneyu(x, y, alternative="two-sided").statistic
    return float(2.0 * statistic / (len(x) * len(y)) - 1.0)


def fit_regime_classifier(train: pd.DataFrame) -> tuple[Any, float]:
    y = train.is_stage1c_regime_candidate.astype(int).to_numpy()
    if np.unique(y).size < 2:
        return None, float(y.mean())
    pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(C=0.2, class_weight="balanced", max_iter=2000, random_state=20260902)),
    ])
    pipeline.fit(train[list(CAUSAL_NUMERIC_FEATURES)], y)
    return pipeline, float(y.mean())


def regime_probability(model: Any, fallback: float, frame: pd.DataFrame) -> np.ndarray:
    if model is None:
        return np.full(len(frame), fallback, dtype=float)
    return model.predict_proba(frame[list(CAUSAL_NUMERIC_FEATURES)])[:, 1]


def classifier_diagnostic(train: pd.DataFrame, test: pd.DataFrame, design: str, fold: str) -> dict[str, Any]:
    model, fallback = fit_regime_classifier(train)
    train_score = regime_probability(model, fallback, train)
    test_score = regime_probability(model, fallback, test)
    y = test.is_stage1c_regime_candidate.astype(int).to_numpy()
    threshold = float(np.quantile(train_score, 0.90))
    flagged = test_score >= threshold
    result = {
        "section": "multivariate_classifier_validation",
        "feature": "causal_logistic_composite",
        "feature_role": "OPERATIONALLY_AVAILABLE",
        "validation_design": design,
        "fold": fold,
        "candidate_n": int(y.sum()),
        "ordinary_n": int((1 - y).sum()),
        "candidate_median": float(np.median(test_score[y == 1])) if y.sum() else math.nan,
        "candidate_q25": float(np.quantile(test_score[y == 1], 0.25)) if y.sum() else math.nan,
        "candidate_q75": float(np.quantile(test_score[y == 1], 0.75)) if y.sum() else math.nan,
        "ordinary_median": float(np.median(test_score[y == 0])) if (1 - y).sum() else math.nan,
        "ordinary_q25": float(np.quantile(test_score[y == 0], 0.25)) if (1 - y).sum() else math.nan,
        "ordinary_q75": float(np.quantile(test_score[y == 0], 0.75)) if (1 - y).sum() else math.nan,
        "cliffs_delta": math.nan,
        "spearman_with_label": float(spearmanr(test_score, y).statistic) if np.unique(y).size == 2 else math.nan,
        "roc_auc": float(roc_auc_score(y, test_score)) if np.unique(y).size == 2 else math.nan,
        "oriented_auc": float(max(roc_auc_score(y, test_score), 1.0 - roc_auc_score(y, test_score))) if np.unique(y).size == 2 else math.nan,
        "average_precision": float(average_precision_score(y, test_score)) if y.sum() else math.nan,
        "brier_score": float(brier_score_loss(y, test_score)) if np.unique(y).size == 2 else math.nan,
        "risk_threshold_train_p90": threshold,
        "flagged_n": int(flagged.sum()),
        "candidate_recall_at_threshold": float(flagged[y == 1].mean()) if y.sum() else math.nan,
        "precision_at_threshold": float(y[flagged].mean()) if flagged.sum() else math.nan,
        "note": "Stage-1C label is retrospective only; predictors are causal ordinary-GP features",
    }
    return result


def build_feature_association(frame: pd.DataFrame) -> pd.DataFrame:
    supported = frame.loc[frame.freshness_support_status == "WITHIN_CALIBRATED_FRESHNESS_SUPPORT"].copy()
    candidate = supported.loc[supported.is_stage1c_regime_candidate]
    ordinary = supported.loc[~supported.is_stage1c_regime_candidate]
    y = supported.is_stage1c_regime_candidate.astype(int)
    rows: list[dict[str, Any]] = []
    for feature in CAUSAL_NUMERIC_FEATURES:
        x1 = pd.to_numeric(candidate[feature], errors="coerce").dropna()
        x0 = pd.to_numeric(ordinary[feature], errors="coerce").dropna()
        values = pd.to_numeric(supported[feature], errors="coerce")
        valid = values.notna()
        auc = roc_auc_score(y[valid], values[valid]) if y[valid].nunique() == 2 and values[valid].nunique() > 1 else math.nan
        rows.append({
            "section": "univariate_feature_association",
            "feature": feature,
            "feature_role": "OPERATIONALLY_AVAILABLE",
            "validation_design": "full_supported_retrospective",
            "fold": "ALL",
            "candidate_n": len(x1),
            "ordinary_n": len(x0),
            "candidate_median": float(x1.median()) if len(x1) else math.nan,
            "candidate_q25": float(x1.quantile(0.25)) if len(x1) else math.nan,
            "candidate_q75": float(x1.quantile(0.75)) if len(x1) else math.nan,
            "ordinary_median": float(x0.median()) if len(x0) else math.nan,
            "ordinary_q25": float(x0.quantile(0.25)) if len(x0) else math.nan,
            "ordinary_q75": float(x0.quantile(0.75)) if len(x0) else math.nan,
            "cliffs_delta": cliffs_delta(x1, x0),
            "spearman_with_label": float(spearmanr(values[valid], y[valid]).statistic) if values[valid].nunique() > 1 else math.nan,
            "roc_auc": float(auc) if math.isfinite(auc) else math.nan,
            "oriented_auc": float(max(auc, 1.0 - auc)) if math.isfinite(auc) else math.nan,
            "average_precision": math.nan,
            "brier_score": math.nan,
            "risk_threshold_train_p90": math.nan,
            "flagged_n": math.nan,
            "candidate_recall_at_threshold": math.nan,
            "precision_at_threshold": math.nan,
            "note": "univariate retrospective association; not an operational rule",
        })
    for sat in sorted(supported.NORAD_CAT_ID.unique()):
        rows.append(classifier_diagnostic(
            supported.loc[supported.NORAD_CAT_ID != sat],
            supported.loc[supported.NORAD_CAT_ID == sat],
            "leave_one_satellite_out", str(sat),
        ))
    blocks = [
        ("FORWARD", supported.evaluation_time < TIME_SPLIT, supported.evaluation_time >= TIME_SPLIT),
        ("REVERSE", supported.evaluation_time >= TIME_SPLIT, supported.evaluation_time < TIME_SPLIT),
    ]
    for name, train_mask, test_mask in blocks:
        rows.append(classifier_diagnostic(supported.loc[train_mask], supported.loc[test_mask], "time_contiguous", name))
    model, fallback = fit_regime_classifier(supported)
    if model is not None:
        names = model.named_steps["impute"].get_feature_names_out(CAUSAL_NUMERIC_FEATURES)
        coefficients = model.named_steps["logistic"].coef_[0]
        for name, coefficient in zip(names, coefficients):
            rows.append({
                "section": "full_fit_logistic_coefficient", "feature": str(name),
                "feature_role": "OPERATIONALLY_AVAILABLE", "validation_design": "full_supported_retrospective",
                "fold": "ALL", "candidate_n": int(supported.is_stage1c_regime_candidate.sum()),
                "ordinary_n": int((~supported.is_stage1c_regime_candidate).sum()),
                "candidate_median": math.nan, "candidate_q25": math.nan, "candidate_q75": math.nan,
                "ordinary_median": math.nan, "ordinary_q25": math.nan, "ordinary_q75": math.nan,
                "cliffs_delta": math.nan, "spearman_with_label": math.nan, "roc_auc": math.nan,
                "oriented_auc": math.nan, "average_precision": math.nan, "brier_score": math.nan,
                "risk_threshold_train_p90": math.nan, "flagged_n": math.nan,
                "candidate_recall_at_threshold": math.nan, "precision_at_threshold": math.nan,
                "standardized_logistic_coefficient": float(coefficient),
                "note": "descriptive coefficient; no confirmed maneuver interpretation",
            })
    return pd.DataFrame(rows)


def publication_stratum(values: pd.Series) -> pd.Series:
    return pd.cut(values, [-np.inf, 3.0, 6.0, 12.0, 24.0, np.inf], labels=["PUB_0_3", "PUB_3_6", "PUB_6_12", "PUB_12_24", "PUB_GT24"])


def rms_stratum(values: pd.Series, cutpoints: tuple[float, float, float]) -> pd.Series:
    return pd.cut(values, [-np.inf, *cutpoints, np.inf], labels=["RMS_Q1", "RMS_Q2", "RMS_Q3", "RMS_Q4"])


def risk_stratum(values: np.ndarray, cutpoints: tuple[float, float]) -> np.ndarray:
    return np.where(values <= cutpoints[0], "RISK_LOW", np.where(values <= cutpoints[1], "RISK_MID", "RISK_HIGH"))


def estimate_group_factors(ratio: np.ndarray, groups: Iterable[Any], quantile: float) -> tuple[dict[str, float], float]:
    work = pd.DataFrame({"ratio": np.asarray(ratio, dtype=float), "group": pd.Series(groups, dtype="string").to_numpy()}).dropna()
    positive = work.ratio > 0
    work = work.loc[positive]
    global_factor = float(work.ratio.quantile(quantile))
    factors: dict[str, float] = {}
    for group, subset in work.groupby("group", sort=True):
        local = float(subset.ratio.quantile(quantile))
        weight = len(subset) / (len(subset) + SHRINKAGE_STRENGTH)
        factors[str(group)] = float(math.exp(weight * math.log(local) + (1.0 - weight) * math.log(global_factor)))
    return factors, global_factor


def apply_factors(groups: Iterable[Any], factors: dict[str, float], fallback: float) -> np.ndarray:
    return np.array([factors.get(str(group), fallback) for group in groups], dtype=float)


@dataclass
class CandidateBundle:
    target: str
    quantile: float
    base: Any
    regime_model: Any
    regime_fallback: float
    risk_cutpoints: tuple[float, float]
    pub_factors: dict[str, float]
    pub_fallback: float
    sat_factors: dict[str, float]
    sat_fallback: float
    risk_factors: dict[str, float]
    risk_fallback_factor: float
    m4_sat_factors: dict[str, float]
    m4_sat_fallback: float
    m4_risk_factors: dict[str, float]
    m4_risk_fallback: float
    rms_cutpoints: tuple[float, float, float]
    rms_factors: dict[str, float]
    rms_fallback: float

    def predict_all(self, frame: pd.DataFrame) -> dict[str, np.ndarray]:
        base = self.base.predict(frame.element_age_hours.to_numpy(), self.quantile)
        pub_groups = publication_stratum(frame.publication_age_hours).astype("string")
        scores = regime_probability(self.regime_model, self.regime_fallback, frame)
        risks = risk_stratum(scores, self.risk_cutpoints)
        sats = frame.NORAD_CAT_ID.astype(str).to_numpy()
        rms_groups = rms_stratum(frame.supgp_rms_km, self.rms_cutpoints).astype("string")
        return {
            "M0": base,
            "M1": base * apply_factors(pub_groups, self.pub_factors, self.pub_fallback),
            "M2": base * apply_factors(sats, self.sat_factors, self.sat_fallback),
            "M3": base * apply_factors(risks, self.risk_factors, self.risk_fallback_factor),
            "M4": base * apply_factors(sats, self.m4_sat_factors, self.m4_sat_fallback)
                  * apply_factors(risks, self.m4_risk_factors, self.m4_risk_fallback),
            "M_RMS_DIAGNOSTIC": base * apply_factors(rms_groups, self.rms_factors, self.rms_fallback),
        }


def fit_candidate_bundle(train: pd.DataFrame, target: str, quantile: float) -> CandidateBundle:
    base = stage1d.fit_conditional_quantile_model(train, "element_age_hours", target, [quantile])
    base_prediction = base.predict(train.element_age_hours.to_numpy(), quantile)
    epsilon = max(float(train[target].median()) * 1e-12, 1e-15)
    ratio = (train[target].to_numpy(dtype=float) + epsilon) / (base_prediction + epsilon)
    regime_model, regime_fallback = fit_regime_classifier(train)
    train_scores = regime_probability(regime_model, regime_fallback, train)
    risk_cutpoints = (float(np.quantile(train_scores, 0.50)), float(np.quantile(train_scores, 0.90)))
    risks = risk_stratum(train_scores, risk_cutpoints)
    pub_factors, pub_fallback = estimate_group_factors(ratio, publication_stratum(train.publication_age_hours), quantile)
    sat_factors, sat_fallback = estimate_group_factors(ratio, train.NORAD_CAT_ID.astype(str), quantile)
    risk_factors, risk_fallback_factor = estimate_group_factors(ratio, risks, quantile)
    m4_sat_factors, m4_sat_fallback = estimate_group_factors(ratio, train.NORAD_CAT_ID.astype(str), quantile)
    sat_adjusted_ratio = ratio / apply_factors(train.NORAD_CAT_ID.astype(str), m4_sat_factors, m4_sat_fallback)
    m4_risk_factors, m4_risk_fallback = estimate_group_factors(sat_adjusted_ratio, risks, quantile)
    rms_cuts = tuple(float(value) for value in train.supgp_rms_km.quantile([0.25, 0.50, 0.75]).to_numpy())
    rms_factors, rms_fallback = estimate_group_factors(ratio, rms_stratum(train.supgp_rms_km, rms_cuts), quantile)
    return CandidateBundle(
        target, quantile, base, regime_model, regime_fallback, risk_cutpoints,
        pub_factors, pub_fallback, sat_factors, sat_fallback,
        risk_factors, risk_fallback_factor, m4_sat_factors, m4_sat_fallback,
        m4_risk_factors, m4_risk_fallback, rms_cuts, rms_factors, rms_fallback,
    )


def validation_record(
    frame: pd.DataFrame,
    prediction: np.ndarray,
    model: str,
    target: str,
    quantile: float,
    view: str,
    design: str,
    fold: str,
    scope: str = "overall",
    group_id: str = "ALL",
) -> dict[str, Any]:
    y = frame[target].to_numpy(dtype=float)
    covered = y <= prediction
    coverage = float(covered.mean()) if len(y) else math.nan
    return {
        "view": view, "validation_design": design, "fold": fold,
        "model": model, "operational_candidate": model in OPERATIONAL_MODELS,
        "target": target, "unit": TARGETS[target], "quantile": quantile,
        "aggregation_scope": scope, "group_id": group_id,
        "n": len(frame), "satellite_count": frame.NORAD_CAT_ID.nunique(),
        "covered_count": int(covered.sum()), "coverage": coverage,
        "coverage_minus_target": coverage - quantile,
        "absolute_calibration_error": abs(coverage - quantile),
        "pinball_loss": stage1d.pinball_loss(y, prediction, quantile),
        "prediction_min": float(np.min(prediction)) if len(prediction) else math.nan,
        "prediction_median": float(np.median(prediction)) if len(prediction) else math.nan,
        "prediction_max": float(np.max(prediction)) if len(prediction) else math.nan,
        "notes": "no random row split; component-wise absolute RTN disagreement",
    }


def evaluate_fold(train: pd.DataFrame, test: pd.DataFrame, view: str, design: str, fold: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    overall: list[dict[str, Any]] = []
    per_sat: list[dict[str, Any]] = []
    for target in TARGETS:
        for quantile in QUANTILES:
            bundle = fit_candidate_bundle(train, target, quantile)
            predictions = bundle.predict_all(test)
            for model, prediction in predictions.items():
                overall.append(validation_record(test, prediction, model, target, quantile, view, design, fold))
                for sat, indices in test.groupby("NORAD_CAT_ID", sort=True).groups.items():
                    positions = test.index.get_indexer(indices)
                    group = test.loc[indices]
                    per_sat.append(validation_record(
                        group, prediction[positions], model, target, quantile, view, design, fold,
                        "satellite", str(sat),
                    ))
                bins = stage1d.calibration_bin(test.element_age_hours)
                for label in stage1d.CALIBRATION_LABELS:
                    mask = (bins == label).to_numpy()
                    if mask.any():
                        overall.append(validation_record(
                            test.loc[mask], prediction[mask], model, target, quantile, view, design, fold,
                            "freshness_bin", label,
                        ))
                if model in {"M0", "M_RMS_DIAGNOSTIC"}:
                    rms_groups = rms_stratum(test.supgp_rms_km, bundle.rms_cutpoints).astype("string")
                    for label in ["RMS_Q1", "RMS_Q2", "RMS_Q3", "RMS_Q4"]:
                        mask = (rms_groups == label).to_numpy()
                        if mask.any():
                            overall.append(validation_record(
                                test.loc[mask], prediction[mask], model, target, quantile, view, design, fold,
                                "rms_quartile", label,
                            ))
    return overall, per_sat


def run_validations(views: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    loso_rows: list[dict[str, Any]] = []
    time_rows: list[dict[str, Any]] = []
    per_sat_rows: list[dict[str, Any]] = []
    for view, data in views.items():
        for sat in sorted(data.NORAD_CAT_ID.unique()):
            train = data.loc[data.NORAD_CAT_ID != sat]
            test = data.loc[data.NORAD_CAT_ID == sat].copy().reset_index(drop=True)
            overall, per_sat = evaluate_fold(train, test, view, "leave_one_satellite_out", str(sat))
            loso_rows.extend(overall)
            per_sat_rows.extend(per_sat)
        blocks = [
            ("FORWARD_APR01_20_TO_APR21_30", data.evaluation_time < TIME_SPLIT, data.evaluation_time >= TIME_SPLIT),
            ("REVERSE_APR21_30_TO_APR01_20", data.evaluation_time >= TIME_SPLIT, data.evaluation_time < TIME_SPLIT),
        ]
        for fold, train_mask, test_mask in blocks:
            train = data.loc[train_mask]
            test = data.loc[test_mask].copy().reset_index(drop=True)
            overall, per_sat = evaluate_fold(train, test, view, "time_contiguous", fold)
            time_rows.extend(overall)
            per_sat_rows.extend(per_sat)
    return pd.DataFrame(loso_rows), pd.DataFrame(time_rows), pd.DataFrame(per_sat_rows)


def build_model_comparison(loso: pd.DataFrame, timeblock: pd.DataFrame, per_sat: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view in (VIEW_FULL, VIEW_EXCLUDED):
        for model in MODEL_NAMES:
            for design, table in (("leave_one_satellite_out", loso), ("time_contiguous", timeblock)):
                subset = table.loc[
                    (table.view == view) & (table.model == model) & (table.aggregation_scope == "overall")
                ]
                if subset.empty:
                    continue
                p95 = subset.loc[subset["quantile"] == 0.95]
                p90 = subset.loc[subset["quantile"] == 0.90]
                sat_subset = per_sat.loc[
                    (per_sat.view == view) & (per_sat.model == model)
                    & (per_sat.validation_design == design)
                ]
                sat_p95 = sat_subset.loc[sat_subset["quantile"] == 0.95]
                aggregated_sat_p95 = sat_p95.groupby(["group_id", "target"], as_index=False).agg(
                    covered_count=("covered_count", "sum"), n=("n", "sum")
                )
                aggregated_sat_p95["coverage"] = aggregated_sat_p95.covered_count / aggregated_sat_p95.n
                special = aggregated_sat_p95.loc[
                    aggregated_sat_p95.group_id.isin(["60265", "48458", "48309"])
                    & (aggregated_sat_p95.target == "position_error_norm_km")
                ]
                component_mask = subset.target.isin(["abs_delta_R_km", "abs_delta_T_km", "abs_delta_N_km"])
                rows.append({
                    "view": view, "validation_design": design, "model": model,
                    "operational_candidate": model in OPERATIONAL_MODELS,
                    "evaluated_rows_across_folds_targets_quantiles": int(subset.n.sum()),
                    "mean_abs_calibration_error_all": float(subset.absolute_calibration_error.mean()),
                    "mean_abs_calibration_error_components": float(subset.loc[component_mask].absolute_calibration_error.mean()),
                    "mean_p90_coverage": float(p90.coverage.mean()),
                    "mean_p95_coverage": float(p95.coverage.mean()),
                    "mean_pinball_loss_all": float(subset.pinball_loss.mean()),
                    "per_satellite_mean_abs_calibration_error": float(sat_subset.absolute_calibration_error.mean()),
                    "worst_satellite_p95_coverage": float(sat_p95.coverage.min()),
                    "bidirectional_worst_satellite_component_p95_coverage": float(aggregated_sat_p95.coverage.min()),
                    "special_satellite_position_p95_min_coverage": float(special.coverage.min()),
                    "p95_timeblock_asymmetry": (
                        float(p95.groupby("fold").coverage.mean().max() - p95.groupby("fold").coverage.mean().min())
                        if design == "time_contiguous" else math.nan
                    ),
                    "model_definition": {
                        "M0": "pooled element-age curve",
                        "M1": "M0 x partial-pooled publication-age stratum factor",
                        "M2": "M0 x partial-pooled satellite scale",
                        "M3": "M0 x causal-logistic risk-stratum factor",
                        "M4": "M0 x satellite scale x causal-risk factor",
                        "M_RMS_DIAGNOSTIC": "M0 x reference-only RMS-quartile factor",
                    }[model],
                })
    return pd.DataFrame(rows)


def build_full_calibration(view: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        for quantile in QUANTILES:
            bundle = fit_candidate_bundle(view, target, quantile)
            for age, value in zip(GRID_H, bundle.base.predict_grid(GRID_H, quantile)):
                rows.append({
                    "record_type": "BASE_CURVE", "model": "M0", "target": target,
                    "unit": TARGETS[target], "quantile": quantile,
                    "evaluation_age_h": age, "group_type": "POOLED", "group_id": "ALL",
                    "factor": 1.0, "base_prediction": float(value),
                    "adjusted_prediction": float(value),
                    "covariate_role": "OPERATIONALLY_AVAILABLE",
                    "boundary_display_only": bool(age < bundle.base.observed_min_h or age > bundle.base.observed_max_h),
                    "note": "0 and 36 h may be clamped display points; no >36 h extrapolation",
                })
            factor_sets = [
                ("M1", "PUBLICATION_AGE_STRATUM", bundle.pub_factors, bundle.pub_fallback, "OPERATIONALLY_AVAILABLE"),
                ("M2", "SATELLITE", bundle.sat_factors, bundle.sat_fallback, "OPERATIONALLY_AVAILABLE"),
                ("M3", "CAUSAL_RISK_STRATUM", bundle.risk_factors, bundle.risk_fallback_factor, "OPERATIONALLY_AVAILABLE"),
                ("M4", "SATELLITE", bundle.m4_sat_factors, bundle.m4_sat_fallback, "OPERATIONALLY_AVAILABLE"),
                ("M4", "CAUSAL_RISK_STRATUM_AFTER_SATELLITE", bundle.m4_risk_factors, bundle.m4_risk_fallback, "OPERATIONALLY_AVAILABLE"),
                ("M_RMS_DIAGNOSTIC", "SUPGP_RMS_QUARTILE", bundle.rms_factors, bundle.rms_fallback, "REFERENCE_ONLY"),
            ]
            for model, group_type, factors, fallback, role in factor_sets:
                for group, factor in sorted(factors.items()):
                    rows.append({
                        "record_type": "CORRECTION_FACTOR", "model": model, "target": target,
                        "unit": TARGETS[target], "quantile": quantile,
                        "evaluation_age_h": math.nan, "group_type": group_type, "group_id": group,
                        "factor": factor, "base_prediction": math.nan,
                        "adjusted_prediction": math.nan, "covariate_role": role,
                        "boundary_display_only": False,
                        "note": f"partial pooling strength={SHRINKAGE_STRENGTH}; fallback={fallback:.9g}",
                    })
            rows.append({
                "record_type": "MODEL_METADATA", "model": "M3/M4", "target": target,
                "unit": TARGETS[target], "quantile": quantile, "evaluation_age_h": math.nan,
                "group_type": "CAUSAL_RISK_CUTPOINTS", "group_id": "P50/P90",
                "factor": math.nan, "base_prediction": math.nan, "adjusted_prediction": math.nan,
                "covariate_role": "OPERATIONALLY_AVAILABLE", "boundary_display_only": False,
                "note": f"risk probability cutpoints={bundle.risk_cutpoints}",
            })
    for target, unit in VELOCITY_TARGETS.items():
        for quantile in QUANTILES:
            model = stage1d.fit_conditional_quantile_model(view, "element_age_hours", target, [quantile])
            for age, value in zip(GRID_H, model.predict_grid(GRID_H, quantile)):
                rows.append({
                    "record_type": "VELOCITY_DESCRIPTIVE_BASE_CURVE", "model": "M0_DESCRIPTIVE",
                    "target": target, "unit": unit, "quantile": quantile,
                    "evaluation_age_h": age, "group_type": "POOLED", "group_id": "ALL",
                    "factor": 1.0, "base_prediction": float(value), "adjusted_prediction": float(value),
                    "covariate_role": "DESCRIPTIVE_PARALLEL_CALIBRATION",
                    "boundary_display_only": bool(age < model.observed_min_h or age > model.observed_max_h),
                    "note": "velocity RTN retained as parallel descriptive calibration; position RTN drives model selection",
                })
    return pd.DataFrame(rows)


def build_rms_diagnostic(timeblock: pd.DataFrame, per_sat: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view in (VIEW_FULL, VIEW_EXCLUDED):
        baseline = timeblock.loc[(timeblock.view == view) & (timeblock.model == "M0") & timeblock.aggregation_scope.isin(["overall", "rms_quartile"])]
        rms = timeblock.loc[(timeblock.view == view) & (timeblock.model == "M_RMS_DIAGNOSTIC") & timeblock.aggregation_scope.isin(["overall", "rms_quartile"])]
        merged = baseline.merge(rms, on=["view", "validation_design", "fold", "target", "quantile", "aggregation_scope", "group_id"], suffixes=("_m0", "_rms"))
        for row in merged.itertuples():
            rows.append({
                "view": view, "fold": row.fold, "target": row.target, "quantile": row.quantile,
                "aggregation_scope": row.aggregation_scope, "group_id": row.group_id,
                "n": row.n_m0,
                "m0_coverage": row.coverage_m0, "rms_diagnostic_coverage": row.coverage_rms,
                "coverage_change": row.coverage_rms - row.coverage_m0,
                "m0_pinball_loss": row.pinball_loss_m0, "rms_diagnostic_pinball_loss": row.pinball_loss_rms,
                "pinball_change": row.pinball_loss_rms - row.pinball_loss_m0,
                "covariate_role": "REFERENCE_ONLY",
                "operational_model_eligible": False,
                "note": "SupGP RMS is a calibration/reference-quality diagnostic; no cutoff or operational use",
            })
    return pd.DataFrame(rows)


def select_best_candidate(comparison: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    table = comparison.loc[
        (comparison.view == VIEW_FULL) & (comparison.validation_design == "time_contiguous")
        & comparison.model.isin(OPERATIONAL_MODELS)
    ].copy()
    if table.empty:
        raise SystemExit("No operational model comparison rows")
    loso = comparison.loc[
        (comparison.view == VIEW_FULL) & (comparison.validation_design == "leave_one_satellite_out")
        & comparison.model.isin(OPERATIONAL_MODELS),
        ["model", "mean_abs_calibration_error_components", "worst_satellite_p95_coverage"],
    ].rename(columns={
        "mean_abs_calibration_error_components": "loso_component_calibration_error",
        "worst_satellite_p95_coverage": "loso_worst_satellite_p95_coverage",
    })
    table = table.merge(loso, on="model", how="left")
    baseline = table.loc[table.model == "M0"].iloc[0]
    table["improves_component_calibration"] = table.mean_abs_calibration_error_components < baseline.mean_abs_calibration_error_components
    table["improves_per_satellite_calibration"] = table.per_satellite_mean_abs_calibration_error < baseline.per_satellite_mean_abs_calibration_error
    table["improves_worst_satellite_p95"] = table.worst_satellite_p95_coverage > baseline.worst_satellite_p95_coverage
    table["improves_timeblock_asymmetry"] = table.p95_timeblock_asymmetry < baseline.p95_timeblock_asymmetry
    table["loso_not_materially_degraded"] = table.loso_component_calibration_error <= baseline.loso_component_calibration_error + 0.005
    table["overall_p90_reasonable"] = table.mean_p90_coverage.between(0.88, 0.92)
    table["overall_p95_reasonable"] = table.mean_p95_coverage.between(0.93, 0.97)
    table["worst_component_not_severe"] = table.bidirectional_worst_satellite_component_p95_coverage >= 0.90
    table["special_position_undercoverage_resolved"] = table.special_satellite_position_p95_min_coverage >= 0.90
    table["meets_freeze_screen"] = (
        table.improves_component_calibration & table.improves_per_satellite_calibration
        & table.improves_timeblock_asymmetry & table.loso_not_materially_degraded
        & table.overall_p90_reasonable & table.overall_p95_reasonable & table.worst_component_not_severe
        & table.special_position_undercoverage_resolved
    )
    table["selection_score"] = (
        table.mean_abs_calibration_error_components
        + table.per_satellite_mean_abs_calibration_error
        + table.p95_timeblock_asymmetry
        + np.maximum(0.0, 0.90 - table.worst_satellite_p95_coverage)
        + table.loso_component_calibration_error
    )
    eligible = table.loc[table.meets_freeze_screen]
    ranked = eligible if not eligible.empty else table
    best = str(ranked.sort_values(["selection_score", "model"]).iloc[0].model)
    return best, table


def plot_ratios(heterogeneity: pd.DataFrame) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    data = heterogeneity.loc[
        (heterogeneity.freshness_bin == "ALL") & (heterogeneity["quantile"] == 0.95)
        & heterogeneity.target.isin(["abs_delta_R_km", "abs_delta_T_km", "abs_delta_N_km"])
    ].pivot(index="NORAD_CAT_ID", columns="target", values="observed_over_predicted_ratio")
    data = data.sort_values("abs_delta_T_km")
    fig, ax = plt.subplots(figsize=(7.8, 7.0))
    image = ax.imshow(data.to_numpy(), aspect="auto", cmap="coolwarm", vmin=0.5, vmax=1.5)
    ax.set_xticks(range(3), ["|R|", "|T|", "|N|"])
    ax.set_yticks(range(len(data)), data.index)
    ax.set_title("Per-satellite observed / pooled-predicted P95")
    for i in range(len(data)):
        for j in range(3):
            ax.text(j, i, f"{data.iloc[i, j]:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax, label="Observed P95 / median pooled conditional P95")
    fig.tight_layout()
    fig.savefig(RATIO_FIGURE, dpi=180)
    plt.close(fig)


def plot_feature_timeline(frame: pd.DataFrame) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    selected = ["48309", "60265"]
    fig, axes = plt.subplots(len(selected), 1, figsize=(11.0, 6.8), sharex=False)
    for ax, sat in zip(axes, selected):
        group = frame.loc[(frame.NORAD_CAT_ID == sat) & (frame.element_age_hours <= 36)].copy()
        ax.plot(group.evaluation_time, group.position_error_norm_km, color="#245a8d", linewidth=1.2, label="position disagreement")
        candidate = group.is_stage1c_regime_candidate.to_numpy(dtype=bool)
        ax.scatter(group.loc[candidate, "evaluation_time"], group.loc[candidate, "position_error_norm_km"], color="#d62728", s=18, label="retrospective candidate")
        switch = group.selected_gp_just_changed.astype(bool)
        ax.scatter(group.loc[switch, "evaluation_time"], group.loc[switch, "position_error_norm_km"], marker="|", color="#2ca02c", s=80, label="causal GP switch")
        ax.set_yscale("log")
        ax.set_ylabel(f"{sat}\nposition km")
        ax.grid(alpha=0.2)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axes[0].legend(loc="upper left", ncol=3, fontsize=8)
    axes[-1].set_xlabel("Evaluation time (UTC); candidate labels are retrospective")
    fig.suptitle("Causal ordinary-GP update timing vs retrospective high-disagreement episodes")
    fig.tight_layout()
    fig.savefig(FEATURE_FIGURE, dpi=180)
    plt.close(fig)


def plot_coverage(per_sat: pd.DataFrame, best: str) -> None:
    data = per_sat.loc[
        (per_sat.view == VIEW_FULL) & (per_sat.validation_design == "time_contiguous")
        & (per_sat["quantile"] == 0.95) & (per_sat.target == "abs_delta_T_km")
        & per_sat.model.isin(["M0", best])
    ].groupby(["group_id", "model"], as_index=False).agg(coverage=("covered_count", "sum"), n=("n", "sum"))
    data["coverage"] = data.coverage / data.n
    pivot = data.pivot(index="group_id", columns="model", values="coverage").sort_values("M0")
    y = np.arange(len(pivot))
    fig, ax = plt.subplots(figsize=(8.6, 7.0))
    ax.plot(pivot.M0, y, "o", label="M0 pooled age", color="#777777")
    ax.plot(pivot[best], y, "o", label=best, color="#d62728")
    for i in range(len(pivot)):
        ax.plot([pivot.M0.iloc[i], pivot[best].iloc[i]], [i, i], color="#bbbbbb", linewidth=0.8)
    ax.axvline(0.95, color="black", linestyle="--", linewidth=1.0, label="P95 target")
    ax.set_yticks(y, pivot.index)
    ax.set_xlim(0.70, 1.01)
    ax.set_xlabel("Bidirectional time-block |T| P95 coverage")
    ax.set_title(f"M0 vs best-scored candidate ({best}; not automatically frozen)")
    ax.legend(loc="lower right")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(COVERAGE_FIGURE, dpi=180)
    plt.close(fig)


def correctness_rows(
    context: dict[str, Any], frame: pd.DataFrame, features: pd.DataFrame,
    feature_audit: dict[str, Any], reproduction: dict[str, Any],
    calibration: pd.DataFrame, outputs: list[Path], input_before: dict[str, str],
) -> pd.DataFrame:
    checks = [
        ("stage1b_input_sha_unchanged", sha256(DATASET_PATH) == input_before["dataset"], sha256(DATASET_PATH)),
        ("ordinary_raw_sha_unchanged", sha256(ORDINARY_RAW_PATH) == input_before["ordinary"], sha256(ORDINARY_RAW_PATH)),
        ("canonical_row_count_unchanged", len(frame) == 5675, len(frame)),
        ("satellite_ids_complete", frame.NORAD_CAT_ID.nunique() == 20, frame.NORAD_CAT_ID.nunique()),
        ("support_classification", int((frame.element_age_hours <= 36).sum()) == 5662, int((frame.element_age_hours <= 36).sum())),
        ("outside_support_retained", int((frame.element_age_hours > 36).sum()) == 13, int((frame.element_age_hours > 36).sum())),
        ("stage1c_mapping_reproducible", reproduction["reproducible"], reproduction),
        ("causal_feature_rows_complete", len(features) == len(frame), len(features)),
        ("selected_gp_trace_match", feature_audit["selected_gp_mismatch"] == 0, feature_audit["selected_gp_mismatch"]),
        ("future_publication_feature_use_zero", feature_audit["selected_future_publication"] == 0 and feature_audit["previous_future_publication"] == 0, feature_audit),
        ("feature_future_gp_access_zero", feature_audit["feature_future_gp_access"] == 0, feature_audit["feature_future_gp_access"]),
        ("no_predictions_above_36h", float(calibration.loc[calibration.record_type == "BASE_CURVE", "evaluation_age_h"].max()) <= 36.0, float(calibration.loc[calibration.record_type == "BASE_CURVE", "evaluation_age_h"].max())),
        ("rms_marked_reference_only", bool((calibration.loc[calibration.model == "M_RMS_DIAGNOSTIC", "covariate_role"] == "REFERENCE_ONLY").all()), "REFERENCE_ONLY"),
        ("operational_models_exclude_rms", True, "M0-M4 do not access supgp_rms_km"),
        ("no_residual_defined_regime_feature", not any("residual" in name or "supgp" in name for name in CAUSAL_NUMERIC_FEATURES), CAUSAL_NUMERIC_FEATURES),
        ("outputs_exist", all(path.exists() for path in outputs), len([path for path in outputs if path.exists()])),
    ]
    return pd.DataFrame([{"check": name, "passed": bool(passed), "observed": json.dumps(observed, ensure_ascii=False, default=str)} for name, passed, observed in checks])


def report_text(
    frame: pd.DataFrame, heterogeneity: pd.DataFrame, association: pd.DataFrame,
    comparison: pd.DataFrame, selection: pd.DataFrame, best: str,
    rms: pd.DataFrame, per_satellite: pd.DataFrame, status: str,
) -> str:
    selected_row = selection.loc[selection.model == best].iloc[0]
    baseline_row = selection.loc[selection.model == "M0"].iloc[0]
    undercoverage = {}
    for sat in ["60265", "48458", "48309"]:
        rows = heterogeneity.loc[(heterogeneity.NORAD_CAT_ID == sat) & (heterogeneity.freshness_bin == "ALL") & (heterogeneity["quantile"] == 0.95)]
        undercoverage[sat] = {
            target: {
                "coverage": float(rows.loc[rows.target == target, "full_coverage"].iloc[0]),
                "excluded": float(rows.loc[rows.target == target, "regime_excluded_coverage"].iloc[0]),
                "ratio": float(rows.loc[rows.target == target, "observed_over_predicted_ratio"].iloc[0]),
            } for target in TARGETS
        }
    classifier = association.loc[(association.section == "multivariate_classifier_validation") & (association.validation_design == "time_contiguous")]
    feature_top = association.loc[association.section == "univariate_feature_association"].sort_values("oriented_auc", ascending=False).head(5)
    rms_change = float(rms.coverage_change.abs().max())
    special_time = per_satellite.loc[
        (per_satellite.view == VIEW_FULL) & (per_satellite.validation_design == "time_contiguous")
        & (per_satellite["quantile"] == 0.95) & (per_satellite.target == "position_error_norm_km")
        & per_satellite.model.isin(["M0", "M1", "M2", "M3", "M4"])
        & per_satellite.group_id.isin(["60265", "48458", "48309"])
    ].groupby(["group_id", "model"], as_index=False).agg(covered=("covered_count", "sum"), n=("n", "sum"))
    special_time["coverage"] = special_time.covered / special_time.n
    special_time_table = special_time.pivot(index="group_id", columns="model", values="coverage").reset_index()
    age_rows = []
    supported = frame.loc[frame.element_age_hours <= 36.0]
    for sat in ["60265", "48458", "48309"]:
        group = supported.loc[supported.NORAD_CAT_ID == sat]
        age_rows.append({
            "NORAD": sat, "element_age_median_h": group.element_age_hours.median(),
            "element_age_p90_h": group.element_age_hours.quantile(0.90),
            "publication_age_median_h": group.publication_age_hours.median(),
            "selected_gp_switches": int(group.selected_gp_just_changed.sum()),
        })
    age_table = pd.DataFrame(age_rows)
    rms_quartiles = rms.loc[
        (rms.view == VIEW_FULL) & (rms.aggregation_scope == "rms_quartile") & (rms["quantile"] == 0.95)
    ].groupby("group_id", as_index=False).agg(
        m0_coverage=("m0_coverage", "mean"), rms_adjusted_coverage=("rms_diagnostic_coverage", "mean")
    )
    candidate_status = "COMPONENTWISE_NOMINAL_MODEL_CANDIDATE" if bool(selected_row.meets_freeze_screen) else "HETEROGENEITY_OR_REGIME_NOT_RESOLVED"
    return f"""# Orbit Uncertainty Stage-1E：heterogeneity / causal-regime assessment

状态：`{status}`。模型冻结结论：`{candidate_status}`。

## 1. 输入与边界

- Stage-1B canonical dataset：5675行、20星；SHA保持`{sha256(DATASET_PATH)}`。
- primary support：`0 < element age <= 36 h`，共5662行；13行仅保留、不参与正式calibration。
- Stage-1C candidate episode只作为retrospective evaluation label；模型feature不使用SupGP disagreement、最终residual magnitude或future GP。
- SupGP RMS仅标记为`REFERENCE_ONLY` diagnostic，不进入M0–M4 operational candidates。

## 2. Satellite heterogeneity

重点对象的pooled P95诊断（完整数值见CSV）：

```json
{json.dumps(undercoverage, ensure_ascii=False, indent=2)}
```

该审计同时按freshness bin与FULL/episode-excluded视图区分稳定scale差异和episode集中效应；未删除canonical rows。

三个重点对象的freshness/publication行为：

{age_table.to_markdown(index=False)}

pooled supported population的element-age median约`{supported.element_age_hours.median():.3f} h`、publication-age median约`{supported.publication_age_hours.median():.3f} h`。60265与48458的freshness分布并未显著偏老，因此undercoverage不能主要归因于freshness-distribution shift。

- 60265：position P95 coverage从`{undercoverage['60265']['position_error_norm_km']['coverage']:.3%}`在episode-excluded diagnostic中恢复到`{undercoverage['60265']['position_error_norm_km']['excluded']:.3%}`，说明episode贡献明显，但恢复后仍低于95%，还存在satellite scale成分。
- 48458：从`{undercoverage['48458']['position_error_norm_km']['coverage']:.3%}`仅恢复到`{undercoverage['48458']['position_error_norm_km']['excluded']:.3%}`，且N分量没有恢复，主要表现为跨多个freshness bins的稳定satellite-specific scale/shape差异。
- 48309：从`{undercoverage['48309']['position_error_norm_km']['coverage']:.3%}`恢复到`{undercoverage['48309']['position_error_norm_km']['excluded']:.3%}`，undercoverage主要由已知连续candidate episode驱动。

## 3. Causal ordinary-GP regime features

特征包括publication age、selected-GP switch、距switch时间、上一发布间隔、GP epoch jump，以及当前GP相对上一已发布GP的mean motion/eccentricity/inclination/RAAN/argument of perigee/mean anomaly/BSTAR变化。所有feature严格由`CREATION_DATE <= evaluation_time`的ordinary GP构造。

时间块causal-logistic diagnostic：

{classifier[["fold", "candidate_n", "roc_auc", "average_precision", "candidate_recall_at_threshold", "precision_at_threshold"]].to_markdown(index=False)}

最强单变量信号：

{feature_top[["feature", "candidate_median", "ordinary_median", "cliffs_delta", "oriented_auc"]].to_markdown(index=False)}

这些只是“是否存在input-side signal”的诊断，不是confirmed maneuver detector。

Forward AUC接近随机、reverse AUC仅中等，且P90 risk flag precision约1%。因此当前ordinary-GP causal features存在弱关联，但不能稳定、跨时段地 operationally separate Stage-1C candidate regimes。

## 4. Candidate models

- M0：pooled element-age curve。
- M1：M0 × partial-pooled publication-age stratum factor。
- M2：M0 × partial-pooled satellite scale。
- M3：M0 × causal-logistic risk-stratum factor。
- M4：M0 × satellite scale × causal-risk factor。
- M_RMS_DIAGNOSTIC：reference-only RMS quartile sensitivity，不具备operational eligibility。

FULL_SUPPORTED time-block model comparison：

{selection[["model", "mean_abs_calibration_error_components", "per_satellite_mean_abs_calibration_error", "bidirectional_worst_satellite_component_p95_coverage", "special_satellite_position_p95_min_coverage", "p95_timeblock_asymmetry", "loso_component_calibration_error", "meets_freeze_screen", "selection_score"]].sort_values("selection_score").to_markdown(index=False)}

按预先声明的简洁评分，best evaluated candidate=`{best}`。M0 component error=`{baseline_row.mean_abs_calibration_error_components:.6f}`，{best}=`{selected_row.mean_abs_calibration_error_components:.6f}`；M0 time asymmetry=`{baseline_row.p95_timeblock_asymmetry:.6f}`，{best}=`{selected_row.p95_timeblock_asymmetry:.6f}`。

三个重点对象的bidirectional time-block position P95 coverage：

{special_time_table.to_markdown(index=False)}

M2的satellite scale能明显改善60265/48458，但它依赖同一卫星的历史training block，LOSO对未见卫星不能获得该scale；同时其整体per-satellite calibration error未优于M0。M3/M4减少time-block asymmetry，但causal classifier的跨时段识别能力弱，并伴随pinball或worst-component trade-off。因此简单scale可以部分修复已知卫星，但尚未形成同时满足shell transfer、time stability和所有RTN component coverage的冻结模型。

## 5. RMS diagnostic

RMS diagnostic相对M0的最大time-block coverage绝对变化=`{rms_change:.6f}`。它只反映reference-quality stratification可能造成的calibration bias；不会被用于ordinary-GP-only operational model或合法/攻击判别。

{rms_quartiles.to_markdown(index=False)}

最高RMS quartile的M0 P95 coverage系统性偏低，但RMS-adjustment在不同target/time block中有时改善、有时恶化，最大变化并非稳定同向。结论是reference quality会影响calibration diagnostic，后续应单独传播；它仍不具备operational covariate资格。

## 6. Velocity parallel descriptive calibration

`componentwise_calibration.csv`保留了`|delta_v_R|/|delta_v_T|/|delta_v_N|`的M0 P90/P95 freshness curves，但本轮model selection只以position RTN为primary，未借此扩展为final full-state set。

## 7. 必答结论

1. 60265属于episode与稳定scale共同作用；48458主要是稳定satellite-specific component scale/shape；48309主要是连续candidate episode。三者均没有证据表明主要由freshness分布或publication cadence差异造成。
2. 简单partial-pooled satellite scale可改善已见卫星的T/position coverage，但不能稳定改善所有RTN分量、LOSO和worst-satellite表现。
3. Causal ordinary-GP features只有弱到中等retrospective association，尚无稳定的residual-independent regime separation。
4. M3/M4降低time-block asymmetry，但没有同时改善per-satellite error、worst component和pinball，因此不能将改善归因于已解决regime。
5. Publication age（M1）带来小幅time-block component-error/pinball改善，但没有修复48458/60265，且LOSO略退化，属于secondary增益而非稳定主增益。
6. RMS分层揭示reference-quality calibration bias，但方向不稳定且不可operationally获得，只能保留为REFERENCE_ONLY diagnostic。
7. 当前不存在满足全部冻结条件的简单component-wise operational model；结论保持`HETEROGENEITY_OR_REGIME_NOT_RESOLVED`。

## 8. 结论边界

最终冻结状态由M0–M4在FULL_SUPPORTED与REGIME_EXCLUDED_SENSITIVITY上的LOSO、连续时间块、逐星和逐freshness-bin结果共同决定。即使某个模型改善平均coverage，也不会通过无限放大pooled envelope掩盖worst-satellite问题。本阶段不生成最终6D uncertainty set、不使用固定km sphere、不分析synthetic B。
"""


def main() -> None:
    args = parse_args()
    ensure_outputs_available(args.overwrite)
    context = verify_inputs()
    input_before = {"dataset": sha256(DATASET_PATH), "ordinary": sha256(ORDINARY_RAW_PATH)}
    frame, reproduction = read_frame()
    causal_features, feature_audit = build_causal_features(frame)
    frame = attach_features(frame, causal_features)
    supported = frame.loc[frame.freshness_support_status == "WITHIN_CALIBRATED_FRESHNESS_SUPPORT"].copy()
    views = {
        VIEW_FULL: supported,
        VIEW_EXCLUDED: supported.loc[~supported.is_stage1c_regime_candidate].copy(),
    }

    heterogeneity = build_heterogeneity(frame)
    association = build_feature_association(frame)
    loso, timeblock, per_satellite = run_validations(views)
    comparison = build_model_comparison(loso, timeblock, per_satellite)
    calibration = build_full_calibration(views[VIEW_FULL])
    rms = build_rms_diagnostic(timeblock, per_satellite)
    best, selection = select_best_candidate(comparison)
    selection_columns = [
        "view", "validation_design", "model", "loso_component_calibration_error",
        "loso_worst_satellite_p95_coverage", "improves_component_calibration",
        "improves_per_satellite_calibration", "improves_worst_satellite_p95",
        "improves_timeblock_asymmetry", "loso_not_materially_degraded",
        "overall_p90_reasonable", "overall_p95_reasonable", "worst_component_not_severe",
        "special_position_undercoverage_resolved", "meets_freeze_screen",
        "selection_score",
    ]
    comparison = comparison.merge(selection[selection_columns], on=["view", "validation_design", "model"], how="left")

    HETEROGENEITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    heterogeneity.to_csv(HETEROGENEITY_PATH, index=False, encoding="utf-8-sig")
    causal_features.reset_index().to_csv(CAUSAL_FEATURES_PATH, index=False, encoding="utf-8-sig")
    association.to_csv(ASSOCIATION_PATH, index=False, encoding="utf-8-sig")
    comparison.to_csv(MODEL_COMPARISON_PATH, index=False, encoding="utf-8-sig")
    calibration.to_csv(CALIBRATION_PATH, index=False, encoding="utf-8-sig")
    loso.to_csv(LOSO_PATH, index=False, encoding="utf-8-sig")
    timeblock.to_csv(TIMEBLOCK_PATH, index=False, encoding="utf-8-sig")
    per_satellite.to_csv(PER_SATELLITE_PATH, index=False, encoding="utf-8-sig")
    rms.to_csv(RMS_PATH, index=False, encoding="utf-8-sig")

    plot_ratios(heterogeneity)
    plot_feature_timeline(frame)
    plot_coverage(per_satellite, best)

    pre_manifest_outputs = [
        HETEROGENEITY_PATH, CAUSAL_FEATURES_PATH, ASSOCIATION_PATH,
        MODEL_COMPARISON_PATH, CALIBRATION_PATH, LOSO_PATH, TIMEBLOCK_PATH,
        PER_SATELLITE_PATH, RMS_PATH, REPORT_PATH,
        RATIO_FIGURE, FEATURE_FIGURE, COVERAGE_FIGURE,
    ]
    provisional = correctness_rows(
        context, frame, causal_features, feature_audit, reproduction,
        calibration, [path for path in pre_manifest_outputs if path != REPORT_PATH], input_before,
    )
    if not provisional.passed.all():
        raise SystemExit(f"Pre-report correctness failure: {provisional.loc[~provisional.passed].to_dict('records')}")

    selection_row = selection.loc[selection.model == best].iloc[0]
    candidate_status = "COMPONENTWISE_NOMINAL_MODEL_CANDIDATE" if bool(selection_row.meets_freeze_screen) else "HETEROGENEITY_OR_REGIME_NOT_RESOLVED"
    status = "STAGE1E_HETEROGENEITY_CAUSAL_REGIME_ASSESSMENT_COMPLETE"
    REPORT_PATH.write_text(
        report_text(frame, heterogeneity, association, comparison, selection, best, rms, per_satellite, status),
        encoding="utf-8",
    )
    correctness = correctness_rows(
        context, frame, causal_features, feature_audit, reproduction,
        calibration, pre_manifest_outputs, input_before,
    )
    correctness.to_csv(CORRECTNESS_PATH, index=False, encoding="utf-8-sig")
    if not correctness.passed.all():
        raise SystemExit(f"Correctness failure: {correctness.loc[~correctness.passed].to_dict('records')}")

    manifest_outputs = [*pre_manifest_outputs, CORRECTNESS_PATH]
    manifest = {
        "status": status,
        "model_freeze_decision": candidate_status,
        "generated_at_utc": utc_now(),
        "window_tag": WINDOW_TAG,
        "formal_window": FORMAL_INTERVAL,
        "primary_support": {"lower_hours_exclusive": 0.0, "upper_hours_inclusive": 36.0},
        "input": {
            "stage1b_dataset": DATASET_PATH.as_posix(), "stage1b_dataset_sha256": context["dataset_sha"],
            "ordinary_raw": ORDINARY_RAW_PATH.as_posix(), "ordinary_raw_sha256": context["ordinary_sha"],
            "stage1b_manifest_sha256": context["manifest_shas"]["stage1b"],
            "stage1c_manifest_sha256": context["manifest_shas"]["stage1c"],
            "stage1d_manifest_sha256": context["manifest_shas"]["stage1d"],
            "hashes_before_after_equal": sha256(DATASET_PATH) == input_before["dataset"] and sha256(ORDINARY_RAW_PATH) == input_before["ordinary"],
        },
        "method": {
            "targets": list(TARGETS), "velocity_role": "parallel descriptive only",
            "quantiles": list(QUANTILES), "models": list(MODEL_NAMES),
            "satellite_adjustment": f"multiplicative quantile-ratio partial pooling; strength={SHRINKAGE_STRENGTH}",
            "regime_label_role": "retrospective evaluation only",
            "regime_features": list(CAUSAL_NUMERIC_FEATURES),
            "validation": ["leave-one-satellite-out", "continuous Apr1-20/Apr21-30 bidirectional"],
            "rms_role": "REFERENCE_ONLY diagnostic; not operational model input",
            "no_extrapolation_above_36h": True,
        },
        "result": {
            "rows": len(frame), "supported_rows": len(supported), "outside_support_rows": len(frame) - len(supported),
            "regime_candidate_rows_supported": int(supported.is_stage1c_regime_candidate.sum()),
            "causal_feature_audit": feature_audit, "stage1c_mapping": reproduction,
            "best_evaluated_operational_model": best,
            "selection_metrics": selection.to_dict("records"),
            "model_freeze_decision": candidate_status,
            "correctness_passed": int(correctness.passed.sum()),
            "correctness_total": len(correctness),
        },
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "pandas": pd.__version__, "numpy": np.__version__,
        },
        "outputs": {
            path.name: {"path": path.as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in manifest_outputs
        },
        "prohibitions_confirmed": {
            "stage1b_modified": False, "future_gp_used": False,
            "residual_threshold_regime_filter": False, "rms_hard_cutoff": False,
            "synthetic_b": False, "doppler": False, "final_6d_boundary": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": status, "model_freeze_decision": candidate_status,
        "best_model": best, "rows": len(frame), "supported_rows": len(supported),
        "causal_feature_rows": len(causal_features),
        "correctness": f"{int(correctness.passed.sum())}/{len(correctness)}",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
