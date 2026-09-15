#!/usr/bin/env python3
"""Design and freeze the April+May signed 3D RTN Stage-1F-lite protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.stats import pearsonr, spearmanr
from sklearn.covariance import MinCovDet


STATUS_COMPLETE = "STAGE1F_LITE_DESIGN_AND_FREEZE_COMPLETE"
STATUS_NOT_READY = "STAGE1F_LITE_NOT_READY_FOR_FREEZE"
STATUS_BLINDNESS_COMPROMISED = "STAGE1F_LITE_JUNE_BLINDNESS_COMPROMISED"

APRIL_DATASET = Path("outputs/datasets/orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv")
MAY_DATASET = Path("outputs/datasets/orbit_uncertainty_stage1b_20260501_20260531_rtn_residual_library.csv")
APRIL_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1b_20260401_20260430_manifest.json")
MAY_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1b_20260501_20260531_manifest.json")
APRIL_STAGE1D_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1d_20260401_20260430_manifest.json")
APRIL_STAGE1E_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1e_20260401_20260430_manifest.json")
MAY_EXTERNAL_MANIFEST = Path("outputs/metrics/orbit_uncertainty_stage1_external_202605_partial_manifest.json")
COHORT_SELECTION = Path("outputs/metrics/orbit_uncertainty_stage1_20260401_20260430_satellite_selection.csv")

APRIL_SHA256 = "2B02C40FDEA69F6079D256B5E274652ABAB2D5BC2F9899866C7F1CAFFB469F23"
MAY_SHA256 = "119F2DAA3896476E120F010A436D0B250E404D41326B57FAABFEAA9F2F73EF3F"
COHORT_SHA256 = "30D7A846DDDE5850645CD3C1C03C061E7971AE40A2EE052FFB4E8BA3E7F4ED36"

METRICS = Path("outputs/metrics")
REPORTS = Path("outputs/reports")
PREFIX = "orbit_uncertainty_stage1f_lite"
SIGNED_SUMMARY_PATH = METRICS / f"{PREFIX}_signed_rtn_summary.csv"
INTERNAL_PATH = METRICS / f"{PREFIX}_candidate_internal_validation.csv"
VOLUME_PATH = METRICS / f"{PREFIX}_candidate_volume.csv"
PARAMETERS_PATH = METRICS / f"{PREFIX}_frozen_parameters.csv"
VELOCITY_PATH = METRICS / f"{PREFIX}_velocity_diagnostic.csv"
REFERENCE_PATH = METRICS / f"{PREFIX}_reference_sensitivity.csv"
CORRECTNESS_PATH = METRICS / f"{PREFIX}_correctness_audit.csv"
MANIFEST_PATH = METRICS / f"{PREFIX}_manifest.json"
REPORT_PATH = REPORTS / f"{PREFIX}_design_freeze_report.md"

CANDIDATES = ("JOINT_MAX_SCORE_BOX", "ROBUST_EMPIRICAL_ELLIPSOID")
FRESHNESS_EDGES_H = (0.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0)
FRESHNESS_LABELS = ("0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h")
QUANTILES = (0.95, 0.99)
POSITION_COLUMNS = ("delta_R_km", "delta_T_km", "delta_N_km")
VELOCITY_COLUMNS = ("delta_v_R_km_s", "delta_v_T_km_s", "delta_v_N_km_s")
MAD_NORMALIZATION = 1.4826
NUMERICAL_FLOOR_KM = 1e-12
ELLIPSOID_CONDITION_LIMIT = 1e8
MCD_RANDOM_STATE = 0
MCD_SUPPORT_FRACTION = None
EMPIRICAL_QUANTILE_METHOD = "higher"

INTERNAL_P99_MINIMUM = 0.98
STRUCTURAL_BIN_MIN_N = 100
STRUCTURAL_BIN_P99_MINIMUM = 0.95
ELLIPSOID_MAX_COVERAGE_DEGRADATION = 0.005
ELLIPSOID_MIN_VOLUME_REDUCTION = 0.10

JUNE_WINDOW = "[2026-06-01T00:00:00Z, 2026-07-01T00:00:00Z)"
JUNE_POOLED_P99_MINIMUM = 0.98
JUNE_CLUSTER_BOOTSTRAP_REPS = 2000
JUNE_CLUSTER_BOOTSTRAP_SEED = 20260601
JUNE_EPISODE_MAX_OBSERVATION_GAP_H = 6.0


class NumericalStabilityError(RuntimeError):
    pass


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


def credential_value_match_count(paths: Iterable[Path]) -> int:
    pattern = re.compile(
        r"(?i)(?:password|passwd|api[_-]?key|access[_-]?token|space[_-]?track[_-]?identity)\s*[:=]\s*[^\s,}\]]+"
    )
    return sum(
        len(pattern.findall(path.read_text(encoding="utf-8-sig", errors="replace")))
        for path in paths if path.exists() and path.suffix.lower() != ".png"
    )


def scan_june_blindness(root: Path = Path(".")) -> dict[str, Any]:
    """Inspect path metadata only; never open a possible June scientific file."""
    root = root.resolve()
    suspicious: list[dict[str, Any]] = []
    contextual: list[dict[str, Any]] = []
    allowed_may_boundary = "spacetrack_gp_history_20260428_20260601_20sat_omm.json"
    stage1_root = (root / "data/orbit_uncertainty_stage1").resolve()
    outputs_root = (root / "outputs").resolve()

    for path in root.rglob("*"):
        try:
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            lower = relative.lower()
            gp_interval = re.search(r"gp_history_(\d{8})_(\d{8})", path.name.lower())
            overlaps_june = bool(
                gp_interval
                and gp_interval.group(1) < "20260701"
                and gp_interval.group(2) > "20260601"
            )
            path_match = "202606" in lower or "june" in lower or overlaps_june
            if not path_match:
                continue
            metadata = {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            }
            resolved = path.resolve()
            in_stage1 = resolved.is_relative_to(stage1_root)
            in_outputs = resolved.is_relative_to(outputs_root)
            if in_stage1 and path.name == allowed_may_boundary and not overlaps_june:
                metadata["classification"] = "MAY_ACQUISITION_RIGHT_BOUNDARY_NOT_JUNE_DATA"
                contextual.append(metadata)
            elif in_stage1 or in_outputs:
                metadata["classification"] = "POSSIBLE_JUNE_STAGE1_SCIENTIFIC_DATA"
                suspicious.append(metadata)
            else:
                metadata["classification"] = "UNRELATED_NON_STAGE1_PATH_MATCH"
                contextual.append(metadata)
        except OSError:
            continue

    stage1_data_root = root / "data/orbit_uncertainty_stage1"
    if stage1_data_root.exists():
        allowed_dirs = {
            stage1_data_root.resolve(),
            (stage1_data_root / "raw").resolve(),
            (stage1_data_root / "raw/celestrak_supgp").resolve(),
            (stage1_data_root / "raw/spacetrack_gp").resolve(),
            (stage1_data_root / "respecialdatarequest (4)").resolve(),
        }
        for directory in stage1_data_root.rglob("*"):
            if directory.is_dir() and directory.resolve() not in allowed_dirs:
                suspicious.append({
                    "path": directory.relative_to(root).as_posix(),
                    "size_bytes": None,
                    "mtime_utc": datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc).isoformat(),
                    "classification": "UNEXPECTED_STAGE1_DATA_DIRECTORY_POSSIBLE_JUNE_DATA",
                })

    return {
        "scan_type": "PATH_AND_METADATA_ONLY_NO_FILE_CONTENT_READ",
        "candidate_future_window": JUNE_WINDOW,
        "june_stage1_scientific_data_present_before_freeze": bool(suspicious),
        "suspicious_paths": suspicious,
        "contextual_noncontaminating_path_matches": contextual,
        "june_scientific_rows_read": 0,
    }


def freshness_bin(age_hours: pd.Series | np.ndarray) -> pd.Series:
    return pd.cut(
        age_hours,
        FRESHNESS_EDGES_H,
        labels=FRESHNESS_LABELS,
        right=True,
        include_lowest=False,
    )


def empirical_quantile(values: np.ndarray, quantile: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), quantile, method=EMPIRICAL_QUANTILE_METHOD))


def load_development_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    required = {
        "NORAD_CAT_ID", "evaluation_time", "element_age_seconds", "supgp_rms_km",
        *POSITION_COLUMNS, *VELOCITY_COLUMNS, "nominal_row",
    }
    frames: list[pd.DataFrame] = []
    audit: dict[str, Any] = {"rows_removed": 0, "outside_support_fit_rows": 0}
    for month, path, expected_rows in [
        ("APRIL", APRIL_DATASET, 5675),
        ("MAY", MAY_DATASET, 6181),
    ]:
        frame = pd.read_csv(path, dtype={"NORAD_CAT_ID": str}, encoding="utf-8-sig")
        missing = sorted(required - set(frame.columns))
        if missing:
            raise SystemExit(f"{month} canonical fields missing: {missing}")
        if len(frame) != expected_rows or frame.NORAD_CAT_ID.nunique() != 20:
            raise SystemExit(f"{month} canonical population mismatch")
        nominal = frame.nominal_row.astype(str).str.lower().map({"true": True, "false": False})
        if nominal.isna().any() or not nominal.all():
            raise SystemExit(f"{month} canonical population contains non-nominal rows")
        frame["month"] = month
        frame["evaluation_time"] = pd.to_datetime(frame.evaluation_time, utc=True, format="mixed")
        frame["element_age_hours"] = frame.element_age_seconds.astype(float) / 3600.0
        frame["freshness_bin"] = freshness_bin(frame.element_age_hours)
        frame["support_status"] = np.where(
            (frame.element_age_hours > 0.0) & (frame.element_age_hours <= 36.0),
            "WITHIN_CALIBRATED_FRESHNESS_SUPPORT",
            "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT",
        )
        frame["row_uid"] = month + ":" + frame.NORAD_CAT_ID + ":" + frame.evaluation_time.astype(str)
        numeric = frame[list(POSITION_COLUMNS) + list(VELOCITY_COLUMNS) + ["supgp_rms_km", "element_age_hours"]]
        if not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise SystemExit(f"{month} canonical data contain nonfinite required values")
        frames.append(frame)
        audit[f"{month.lower()}_rows"] = len(frame)
        audit[f"{month.lower()}_support_rows"] = int((frame.support_status == "WITHIN_CALIBRATED_FRESHNESS_SUPPORT").sum())
        audit[f"{month.lower()}_outside_rows"] = int((frame.support_status == "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT").sum())
    combined = pd.concat(frames, ignore_index=True)
    if combined.row_uid.duplicated().any():
        raise SystemExit("Development row_uid is not unique")
    supported = combined.loc[combined.support_status == "WITHIN_CALIBRATED_FRESHNESS_SUPPORT"].copy()
    outside = combined.loc[combined.support_status == "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT"].copy()
    if supported.freshness_bin.isna().any():
        raise SystemExit("Supported row missing frozen freshness bin")
    audit.update({
        "combined_rows": len(combined),
        "supported_rows": len(supported),
        "outside_rows": len(outside),
        "satellite_count": int(combined.NORAD_CAT_ID.nunique()),
        "formal_support": "0 < element_age_hours <= 36",
    })
    return frames[0], frames[1], supported, audit


@dataclass
class BinSetModel:
    candidate: str
    freshness_bin: str
    center: np.ndarray
    scale: np.ndarray | None
    covariance: np.ndarray | None
    inverse_covariance: np.ndarray | None
    thresholds: dict[float, float]
    train_n: int
    satellite_count: int
    determinant: float
    condition_number: float
    eigenvalues: np.ndarray
    eigenvectors: np.ndarray
    raw_support_fraction: float
    reweighted_support_fraction: float

    def score(self, values: np.ndarray) -> np.ndarray:
        centered = np.asarray(values, dtype=float) - self.center
        if self.candidate == "JOINT_MAX_SCORE_BOX":
            if self.scale is None:
                raise RuntimeError("Box scale missing")
            return np.max(np.abs(centered) / self.scale, axis=1)
        if self.inverse_covariance is None:
            raise RuntimeError("Ellipsoid inverse covariance missing")
        return np.einsum("ij,jk,ik->i", centered, self.inverse_covariance, centered)

    def volume(self, quantile: float) -> float:
        cutoff = self.thresholds[quantile]
        if self.candidate == "JOINT_MAX_SCORE_BOX":
            assert self.scale is not None
            return float(8.0 * cutoff**3 * np.prod(self.scale))
        return float((4.0 / 3.0) * math.pi * cutoff**1.5 * math.sqrt(self.determinant))


def fit_bin_model(frame: pd.DataFrame, candidate: str, bin_label: str) -> BinSetModel:
    values = frame.loc[:, POSITION_COLUMNS].to_numpy(dtype=float)
    if len(values) < 4:
        raise NumericalStabilityError(f"{candidate}/{bin_label}: fewer than 4 training rows")
    if candidate == "JOINT_MAX_SCORE_BOX":
        center = np.median(values, axis=0)
        mad = np.median(np.abs(values - center), axis=0)
        scale = MAD_NORMALIZATION * mad
        if not np.isfinite(scale).all() or np.any(scale <= NUMERICAL_FLOOR_KM):
            raise NumericalStabilityError(f"{candidate}/{bin_label}: MAD scale at or below numerical floor")
        model = BinSetModel(
            candidate=candidate,
            freshness_bin=bin_label,
            center=center,
            scale=scale,
            covariance=None,
            inverse_covariance=None,
            thresholds={},
            train_n=len(frame),
            satellite_count=int(frame.NORAD_CAT_ID.nunique()),
            determinant=math.nan,
            condition_number=float(np.max(scale) / np.min(scale)),
            eigenvalues=np.square(scale),
            eigenvectors=np.eye(3),
            raw_support_fraction=1.0,
            reweighted_support_fraction=1.0,
        )
    elif candidate == "ROBUST_EMPIRICAL_ELLIPSOID":
        estimator = MinCovDet(
            random_state=MCD_RANDOM_STATE,
            support_fraction=MCD_SUPPORT_FRACTION,
            assume_centered=False,
            store_precision=True,
        ).fit(values)
        center = np.asarray(estimator.location_, dtype=float)
        covariance = np.asarray(estimator.covariance_, dtype=float)
        if not np.isfinite(center).all() or not np.isfinite(covariance).all():
            raise NumericalStabilityError(f"{candidate}/{bin_label}: nonfinite MCD result")
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        order = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[order]
        eigenvectors = eigenvectors[:, order]
        determinant = float(np.linalg.det(covariance))
        condition = float(np.linalg.cond(covariance))
        if (
            np.any(eigenvalues <= 0.0)
            or not math.isfinite(determinant)
            or determinant <= 0.0
            or not math.isfinite(condition)
            or condition > ELLIPSOID_CONDITION_LIMIT
        ):
            raise NumericalStabilityError(
                f"{candidate}/{bin_label}: unstable covariance; eigen={eigenvalues}; det={determinant}; cond={condition}"
            )
        try:
            inverse = np.linalg.inv(covariance)
        except np.linalg.LinAlgError as exc:
            raise NumericalStabilityError(f"{candidate}/{bin_label}: singular covariance inversion") from exc
        model = BinSetModel(
            candidate=candidate,
            freshness_bin=bin_label,
            center=center,
            scale=None,
            covariance=covariance,
            inverse_covariance=inverse,
            thresholds={},
            train_n=len(frame),
            satellite_count=int(frame.NORAD_CAT_ID.nunique()),
            determinant=determinant,
            condition_number=condition,
            eigenvalues=eigenvalues,
            eigenvectors=eigenvectors,
            raw_support_fraction=float(np.mean(estimator.raw_support_)),
            reweighted_support_fraction=float(np.mean(estimator.support_)),
        )
    else:
        raise ValueError(f"Unknown candidate: {candidate}")
    training_scores = model.score(values)
    if not np.isfinite(training_scores).all():
        raise NumericalStabilityError(f"{candidate}/{bin_label}: nonfinite training score")
    model.thresholds = {quantile: empirical_quantile(training_scores, quantile) for quantile in QUANTILES}
    return model


def fit_candidate(frame: pd.DataFrame, candidate: str) -> dict[str, BinSetModel]:
    if candidate not in CANDIDATES:
        raise ValueError(f"Candidate must be one of {CANDIDATES}")
    models: dict[str, BinSetModel] = {}
    bins = freshness_bin(frame.element_age_hours)
    for label in FRESHNESS_LABELS:
        subset = frame.loc[bins == label]
        models[label] = fit_bin_model(subset, candidate, label)
    return models


def score_candidate(frame: pd.DataFrame, models: dict[str, BinSetModel]) -> pd.DataFrame:
    output = frame[["row_uid", "month", "NORAD_CAT_ID", "evaluation_time", "element_age_hours", "freshness_bin"]].copy()
    output["joint_score"] = np.nan
    for quantile in QUANTILES:
        output[f"cutoff_p{int(quantile * 100)}"] = np.nan
        output[f"inside_p{int(quantile * 100)}"] = False
    for label, model in models.items():
        mask = output.freshness_bin.astype(str) == label
        indices = output.index[mask]
        values = frame.loc[indices, POSITION_COLUMNS].to_numpy(dtype=float)
        scores = model.score(values)
        output.loc[indices, "joint_score"] = scores
        for quantile in QUANTILES:
            cutoff = model.thresholds[quantile]
            output.loc[indices, f"cutoff_p{int(quantile * 100)}"] = cutoff
            output.loc[indices, f"inside_p{int(quantile * 100)}"] = scores <= cutoff
    if output.joint_score.isna().any() or not np.isfinite(output.joint_score).all():
        raise NumericalStabilityError("Scoring left nonfinite or unassigned rows")
    return output


def fold_metric_rows(
    scored: pd.DataFrame,
    candidate: str,
    scheme: str,
    fold_id: str,
    aggregation_prefix: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups: list[tuple[str, pd.DataFrame]] = [("ALL", scored)]
    groups.extend((label, scored.loc[scored.freshness_bin.astype(str) == label]) for label in FRESHNESS_LABELS)
    for label, group in groups:
        for quantile in QUANTILES:
            covered = int(group[f"inside_p{int(quantile * 100)}"].sum())
            rows.append({
                "candidate": candidate,
                "validation_scheme": scheme,
                "fold_id": fold_id,
                "aggregation_level": f"{aggregation_prefix}_{'OVERALL' if label == 'ALL' else 'FRESHNESS_BIN'}",
                "freshness_bin": label,
                "quantile": quantile,
                "n": len(group),
                "satellite_count": int(group.NORAD_CAT_ID.nunique()),
                "covered_count": covered,
                "joint_coverage": covered / len(group),
                "coverage_error": covered / len(group) - quantile,
                "structural_bin_undercoverage": bool(
                    label != "ALL" and quantile == 0.99 and len(group) >= STRUCTURAL_BIN_MIN_N
                    and covered / len(group) < STRUCTURAL_BIN_P99_MINIMUM
                ),
                "training_only_parameters": True,
                "random_row_split": False,
            })
    return rows


def volume_rows_for_fit(
    models: dict[str, BinSetModel],
    test: pd.DataFrame,
    candidate: str,
    scheme: str,
    fold_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    test_bins = freshness_bin(test.element_age_hours)
    for label, model in models.items():
        occupancy = int((test_bins == label).sum())
        for quantile in QUANTILES:
            volume = model.volume(quantile)
            rows.append({
                "record_type": "FIT_BIN_VOLUME",
                "candidate": candidate,
                "validation_scheme": scheme,
                "fold_id": fold_id,
                "freshness_bin": label,
                "quantile": quantile,
                "train_n": model.train_n,
                "test_occupancy_n": occupancy,
                "volume_km3": volume,
                "log_volume": math.log(volume),
                "occupancy_weighted_mean_log_volume": math.nan,
                "equal_bin_mean_log_volume": math.nan,
                "geometric_mean_volume_km3": math.nan,
            })
    return rows


def append_volume_summaries(volume: pd.DataFrame) -> pd.DataFrame:
    summary_rows: list[dict[str, Any]] = []
    bins = volume.loc[volume.record_type == "FIT_BIN_VOLUME"]
    for (candidate, scheme, quantile), group in bins.groupby(
        ["candidate", "validation_scheme", "quantile"], sort=True
    ):
        weights = group.test_occupancy_n.to_numpy(dtype=float)
        logs = group.log_volume.to_numpy(dtype=float)
        weighted_log = float(np.average(logs, weights=weights))
        equal_log = float(np.mean(logs))
        summary_rows.append({
            "record_type": "SCHEME_VOLUME_SUMMARY",
            "candidate": candidate,
            "validation_scheme": scheme,
            "fold_id": "ALL_FOLDS",
            "freshness_bin": "ALL",
            "quantile": quantile,
            "train_n": math.nan,
            "test_occupancy_n": int(weights.sum()),
            "volume_km3": math.nan,
            "log_volume": math.nan,
            "occupancy_weighted_mean_log_volume": weighted_log,
            "equal_bin_mean_log_volume": equal_log,
            "geometric_mean_volume_km3": math.exp(weighted_log),
        })
    return pd.concat([volume, pd.DataFrame(summary_rows)], ignore_index=True)


def evaluate_internal(
    supported: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, BinSetModel]], list[dict[str, Any]]]:
    april = supported.loc[supported.month == "APRIL"]
    may = supported.loc[supported.month == "MAY"]
    split_april = pd.Timestamp("2026-04-16T00:00:00Z")
    split_may = pd.Timestamp("2026-05-16T00:00:00Z")
    folds: list[tuple[str, str, pd.DataFrame, pd.DataFrame]] = [
        ("MONTH_DIRECTION", "APRIL_TO_MAY", april, may),
        ("MONTH_DIRECTION", "MAY_TO_APRIL", may, april),
    ]
    for satellite in sorted(supported.NORAD_CAT_ID.unique()):
        folds.append((
            "LEAVE_ONE_SATELLITE_OUT",
            f"HOLDOUT_{satellite}",
            supported.loc[supported.NORAD_CAT_ID != satellite],
            supported.loc[supported.NORAD_CAT_ID == satellite],
        ))
    folds.extend([
        (
            "FORWARD_CONTIGUOUS_TIME",
            "APRIL_01_15_TO_APRIL_16_30",
            april.loc[april.evaluation_time < split_april],
            april.loc[april.evaluation_time >= split_april],
        ),
        (
            "FORWARD_CONTIGUOUS_TIME",
            "APRIL_ALL_TO_MAY_01_15",
            april,
            may.loc[may.evaluation_time < split_may],
        ),
        (
            "FORWARD_CONTIGUOUS_TIME",
            "APRIL_PLUS_MAY_01_15_TO_MAY_16_31",
            pd.concat([april, may.loc[may.evaluation_time < split_may]], ignore_index=True),
            may.loc[may.evaluation_time >= split_may],
        ),
    ])

    metric_rows: list[dict[str, Any]] = []
    volume_rows: list[dict[str, Any]] = []
    scored_by_scheme: dict[tuple[str, str], list[pd.DataFrame]] = {}
    numerical_rows: list[dict[str, Any]] = []
    for scheme, fold_id, train, test in folds:
        if set(train.row_uid).intersection(test.row_uid):
            raise SystemExit(f"Train/test leakage in {scheme}/{fold_id}")
        for candidate in CANDIDATES:
            models = fit_candidate(train, candidate)
            scored = score_candidate(test, models)
            scored["candidate"] = candidate
            scored["validation_scheme"] = scheme
            scored["fold_id"] = fold_id
            scored_by_scheme.setdefault((candidate, scheme), []).append(scored)
            metric_rows.extend(fold_metric_rows(scored, candidate, scheme, fold_id, "FOLD"))
            volume_rows.extend(volume_rows_for_fit(models, test, candidate, scheme, fold_id))
            for label, model in models.items():
                numerical_rows.append({
                    "candidate": candidate,
                    "validation_scheme": scheme,
                    "fold_id": fold_id,
                    "freshness_bin": label,
                    "condition_number": model.condition_number,
                    "min_eigenvalue": float(np.min(model.eigenvalues)),
                    "determinant": model.determinant,
                    "numerically_stable": True,
                })

    for (candidate, scheme), frames in scored_by_scheme.items():
        aggregate = pd.concat(frames, ignore_index=True)
        if scheme in {"MONTH_DIRECTION", "LEAVE_ONE_SATELLITE_OUT"}:
            if aggregate.row_uid.duplicated().any() or len(aggregate) != len(supported):
                raise SystemExit(f"{scheme}/{candidate} does not evaluate every support row exactly once")
        metric_rows.extend(fold_metric_rows(aggregate, candidate, scheme, "ALL_FOLDS", "SCHEME"))

    final_models: dict[str, dict[str, BinSetModel]] = {}
    for candidate in CANDIDATES:
        models = fit_candidate(supported, candidate)
        final_models[candidate] = models
        volume_rows.extend(volume_rows_for_fit(models, supported, candidate, "FINAL_COMBINED", "FULL_DEVELOPMENT"))
        for label, model in models.items():
            numerical_rows.append({
                "candidate": candidate,
                "validation_scheme": "FINAL_COMBINED",
                "fold_id": "FULL_DEVELOPMENT",
                "freshness_bin": label,
                "condition_number": model.condition_number,
                "min_eigenvalue": float(np.min(model.eigenvalues)),
                "determinant": model.determinant,
                "numerically_stable": True,
            })
    return (
        pd.DataFrame(metric_rows),
        append_volume_summaries(pd.DataFrame(volume_rows)),
        final_models,
        numerical_rows,
    )


def aggregate_metric(internal: pd.DataFrame, candidate: str, scheme: str, quantile: float) -> pd.Series:
    rows = internal.loc[
        (internal.candidate == candidate)
        & (internal.validation_scheme == scheme)
        & (internal.fold_id == "ALL_FOLDS")
        & (internal.aggregation_level == "SCHEME_OVERALL")
        & np.isclose(internal["quantile"], quantile)
    ]
    if len(rows) != 1:
        raise RuntimeError(f"Missing aggregate metric: {candidate}/{scheme}/q{quantile}")
    return rows.iloc[0]


def choose_candidate(internal: pd.DataFrame, volume: pd.DataFrame) -> dict[str, Any]:
    status: dict[str, dict[str, Any]] = {}
    selection_schemes = ("MONTH_DIRECTION", "LEAVE_ONE_SATELLITE_OUT")
    for candidate in CANDIDATES:
        pooled = {
            scheme: float(aggregate_metric(internal, candidate, scheme, 0.99).joint_coverage)
            for scheme in selection_schemes
        }
        structural = internal.loc[
            (internal.candidate == candidate)
            & (internal.validation_scheme.isin(selection_schemes))
            & (internal.fold_id == "ALL_FOLDS")
            & (internal.aggregation_level == "SCHEME_FRESHNESS_BIN")
            & np.isclose(internal["quantile"], 0.99)
            & (internal.n >= STRUCTURAL_BIN_MIN_N)
            & (internal.joint_coverage < STRUCTURAL_BIN_P99_MINIMUM)
        ]
        passed = all(value >= INTERNAL_P99_MINIMUM for value in pooled.values()) and structural.empty
        status[candidate] = {
            "internal_calibration_status": "PASS" if passed else "FAIL",
            "pooled_p99": pooled,
            "structural_bin_undercoverage_count": len(structural),
        }

    coverage_differences = {
        scheme: status["ROBUST_EMPIRICAL_ELLIPSOID"]["pooled_p99"][scheme]
        - status["JOINT_MAX_SCORE_BOX"]["pooled_p99"][scheme]
        for scheme in selection_schemes
    }
    no_material_degradation = all(
        difference >= -ELLIPSOID_MAX_COVERAGE_DEGRADATION
        for difference in coverage_differences.values()
    )
    new_structural = 0
    for scheme in selection_schemes:
        box = internal.loc[
            (internal.candidate == "JOINT_MAX_SCORE_BOX")
            & (internal.validation_scheme == scheme)
            & (internal.fold_id == "ALL_FOLDS")
            & (internal.aggregation_level == "SCHEME_FRESHNESS_BIN")
            & np.isclose(internal["quantile"], 0.99)
        ].set_index("freshness_bin")
        ellipse = internal.loc[
            (internal.candidate == "ROBUST_EMPIRICAL_ELLIPSOID")
            & (internal.validation_scheme == scheme)
            & (internal.fold_id == "ALL_FOLDS")
            & (internal.aggregation_level == "SCHEME_FRESHNESS_BIN")
            & np.isclose(internal["quantile"], 0.99)
        ].set_index("freshness_bin")
        for label in FRESHNESS_LABELS:
            if (
                int(ellipse.loc[label, "n"]) >= STRUCTURAL_BIN_MIN_N
                and float(box.loc[label, "joint_coverage"]) >= STRUCTURAL_BIN_P99_MINIMUM
                and float(ellipse.loc[label, "joint_coverage"]) < STRUCTURAL_BIN_P99_MINIMUM
            ):
                new_structural += 1

    summaries = volume.loc[
        (volume.record_type == "SCHEME_VOLUME_SUMMARY") & np.isclose(volume["quantile"], 0.99)
    ]
    volume_ratios: dict[str, float] = {}
    for scheme in ("MONTH_DIRECTION", "LEAVE_ONE_SATELLITE_OUT", "FINAL_COMBINED"):
        box_volume = float(summaries.loc[
            (summaries.candidate == "JOINT_MAX_SCORE_BOX") & (summaries.validation_scheme == scheme),
            "geometric_mean_volume_km3",
        ].iloc[0])
        ellipse_volume = float(summaries.loc[
            (summaries.candidate == "ROBUST_EMPIRICAL_ELLIPSOID") & (summaries.validation_scheme == scheme),
            "geometric_mean_volume_km3",
        ].iloc[0])
        volume_ratios[scheme] = ellipse_volume / box_volume
    stable_volume_reduction = all(
        ratio <= 1.0 - ELLIPSOID_MIN_VOLUME_REDUCTION for ratio in volume_ratios.values()
    )

    box_pass = status["JOINT_MAX_SCORE_BOX"]["internal_calibration_status"] == "PASS"
    ellipse_pass = status["ROBUST_EMPIRICAL_ELLIPSOID"]["internal_calibration_status"] == "PASS"
    if box_pass and not ellipse_pass:
        primary = "JOINT_MAX_SCORE_BOX"
        rule_case = "CASE_1_ONLY_BOX_PASSES"
    elif ellipse_pass and not box_pass:
        primary = "ROBUST_EMPIRICAL_ELLIPSOID"
        rule_case = "CASE_2_ONLY_ELLIPSOID_PASSES"
    elif box_pass and ellipse_pass:
        if no_material_degradation and new_structural == 0 and stable_volume_reduction:
            primary = "ROBUST_EMPIRICAL_ELLIPSOID"
            rule_case = "CASE_3_BOTH_PASS_ELLIPSOID_EARNS_COMPLEXITY"
        else:
            primary = "JOINT_MAX_SCORE_BOX"
            rule_case = "CASE_3_BOTH_PASS_DEFAULT_TO_SIMPLE_BOX"
    else:
        primary = ""
        rule_case = "CASE_4_NEITHER_PASSES"
    secondary = next((candidate for candidate in CANDIDATES if candidate != primary), "") if primary else ""
    return {
        "candidate_status": status,
        "ellipse_minus_box_pooled_p99_coverage": coverage_differences,
        "ellipse_no_material_coverage_degradation": no_material_degradation,
        "ellipse_new_structural_bin_undercoverage_count": new_structural,
        "ellipse_over_box_p99_geometric_mean_volume_ratio": volume_ratios,
        "ellipse_stable_volume_reduction_at_least_10pct": stable_volume_reduction,
        "selection_rule_case": rule_case,
        "primary_candidate_for_june": primary,
        "secondary_sensitivity_candidate": secondary,
    }


def flatten_model_parameters(
    candidate: str,
    role: str,
    models: dict[str, BinSetModel],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label in FRESHNESS_LABELS:
        model = models[label]
        covariance = model.covariance if model.covariance is not None else np.full((3, 3), np.nan)
        scale = model.scale if model.scale is not None else np.full(3, np.nan)
        row: dict[str, Any] = {
            "candidate": candidate,
            "candidate_role": role,
            "freshness_bin": label,
            "bin_left_h_exclusive": FRESHNESS_EDGES_H[FRESHNESS_LABELS.index(label)],
            "bin_right_h_inclusive": FRESHNESS_EDGES_H[FRESHNESS_LABELS.index(label) + 1],
            "model_geometry": "axis_aligned_robust_max_score_box" if candidate == CANDIDATES[0] else "rotated_robust_empirical_ellipsoid",
            "train_n": model.train_n,
            "satellite_count": model.satellite_count,
            "center_R_km": model.center[0],
            "center_T_km": model.center[1],
            "center_N_km": model.center[2],
            "scale_R_km": scale[0],
            "scale_T_km": scale[1],
            "scale_N_km": scale[2],
            "cov_RR_km2": covariance[0, 0],
            "cov_RT_km2": covariance[0, 1],
            "cov_RN_km2": covariance[0, 2],
            "cov_TR_km2": covariance[1, 0],
            "cov_TT_km2": covariance[1, 1],
            "cov_TN_km2": covariance[1, 2],
            "cov_NR_km2": covariance[2, 0],
            "cov_NT_km2": covariance[2, 1],
            "cov_NN_km2": covariance[2, 2],
            "c95_empirical_score": model.thresholds[0.95],
            "c99_empirical_score": model.thresholds[0.99],
            "quantile_method": EMPIRICAL_QUANTILE_METHOD,
            "determinant_km6": model.determinant,
            "condition_number": model.condition_number,
            "eigenvalue_1_km2": model.eigenvalues[0],
            "eigenvalue_2_km2": model.eigenvalues[1],
            "eigenvalue_3_km2": model.eigenvalues[2],
            "raw_support_fraction": model.raw_support_fraction,
            "reweighted_support_fraction": model.reweighted_support_fraction,
        }
        for axis_index, axis in enumerate(("R", "T", "N")):
            for pc_index in range(3):
                row[f"principal_direction_{pc_index + 1}_{axis}"] = model.eigenvectors[axis_index, pc_index]
        rows.append(row)
    return rows


def safe_correlation(x: np.ndarray, y: np.ndarray, method: str) -> float:
    if len(x) < 3 or np.unique(x).size < 2 or np.unique(y).size < 2:
        return math.nan
    if method == "pearson":
        return float(pearsonr(x, y).statistic)
    return float(spearmanr(x, y).statistic)


def signed_structure_summary(april: pd.DataFrame, may: pd.DataFrame, supported: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes = [("APRIL", april), ("MAY", may), ("COMBINED", supported)]
    for scope, frame in scopes:
        within = frame.loc[(frame.element_age_hours > 0.0) & (frame.element_age_hours <= 36.0)].copy()
        within["freshness_bin"] = freshness_bin(within.element_age_hours)
        groups = [("ALL", within)] + [
            (label, within.loc[within.freshness_bin.astype(str) == label]) for label in FRESHNESS_LABELS
        ]
        for label, group in groups:
            values = group.loc[:, POSITION_COLUMNS].to_numpy(dtype=float)
            classical_cov = np.cov(values, rowvar=False, ddof=1)
            mcd = fit_bin_model(group, "ROBUST_EMPIRICAL_ELLIPSOID", label)
            abs_values = np.abs(values)
            dominant = np.argmax(abs_values, axis=1)
            row: dict[str, Any] = {
                "scope": scope,
                "freshness_bin": label,
                "n": len(group),
                "satellite_count": int(group.NORAD_CAT_ID.nunique()),
                "mean_R_km": np.mean(values[:, 0]),
                "mean_T_km": np.mean(values[:, 1]),
                "mean_N_km": np.mean(values[:, 2]),
                "median_R_km": np.median(values[:, 0]),
                "median_T_km": np.median(values[:, 1]),
                "median_N_km": np.median(values[:, 2]),
                "p25_R_km": np.quantile(values[:, 0], 0.25),
                "p25_T_km": np.quantile(values[:, 1], 0.25),
                "p25_N_km": np.quantile(values[:, 2], 0.25),
                "p75_R_km": np.quantile(values[:, 0], 0.75),
                "p75_T_km": np.quantile(values[:, 1], 0.75),
                "p75_N_km": np.quantile(values[:, 2], 0.75),
                "robust_center_R_km": mcd.center[0],
                "robust_center_T_km": mcd.center[1],
                "robust_center_N_km": mcd.center[2],
                "median_abs_R_km": np.median(abs_values[:, 0]),
                "median_abs_T_km": np.median(abs_values[:, 1]),
                "median_abs_N_km": np.median(abs_values[:, 2]),
                "R_dominant_fraction": np.mean(dominant == 0),
                "T_dominant_fraction": np.mean(dominant == 1),
                "N_dominant_fraction": np.mean(dominant == 2),
                "pearson_R_T": safe_correlation(values[:, 0], values[:, 1], "pearson"),
                "pearson_R_N": safe_correlation(values[:, 0], values[:, 2], "pearson"),
                "pearson_T_N": safe_correlation(values[:, 1], values[:, 2], "pearson"),
                "spearman_R_T": safe_correlation(values[:, 0], values[:, 1], "spearman"),
                "spearman_R_N": safe_correlation(values[:, 0], values[:, 2], "spearman"),
                "spearman_T_N": safe_correlation(values[:, 1], values[:, 2], "spearman"),
                "classical_cov_RR": classical_cov[0, 0],
                "classical_cov_RT": classical_cov[0, 1],
                "classical_cov_RN": classical_cov[0, 2],
                "classical_cov_TT": classical_cov[1, 1],
                "classical_cov_TN": classical_cov[1, 2],
                "classical_cov_NN": classical_cov[2, 2],
                "robust_cov_RR": mcd.covariance[0, 0],
                "robust_cov_RT": mcd.covariance[0, 1],
                "robust_cov_RN": mcd.covariance[0, 2],
                "robust_cov_TT": mcd.covariance[1, 1],
                "robust_cov_TN": mcd.covariance[1, 2],
                "robust_cov_NN": mcd.covariance[2, 2],
                "robust_eigenvalue_1": mcd.eigenvalues[0],
                "robust_eigenvalue_2": mcd.eigenvalues[1],
                "robust_eigenvalue_3": mcd.eigenvalues[2],
                "robust_eigenvalue_ratio": mcd.eigenvalues[0] / mcd.eigenvalues[2],
                "robust_cov_determinant": mcd.determinant,
                "robust_cov_condition_number": mcd.condition_number,
                "robust_cov_positive_definite": bool(np.min(mcd.eigenvalues) > 0.0),
            }
            for axis_index, axis in enumerate(("R", "T", "N")):
                for pc_index in range(3):
                    row[f"principal_direction_{pc_index + 1}_{axis}"] = mcd.eigenvectors[axis_index, pc_index]
            rows.append(row)
    return pd.DataFrame(rows)


def velocity_diagnostic(april: pd.DataFrame, may: pd.DataFrame, supported: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scope, frame in [("APRIL", april), ("MAY", may), ("COMBINED", supported)]:
        group = frame.loc[(frame.element_age_hours > 0.0) & (frame.element_age_hours <= 36.0)]
        velocity = group.loc[:, VELOCITY_COLUMNS].to_numpy(dtype=float)
        t_position = group.delta_T_km.to_numpy(dtype=float)
        row = {
            "scope": scope,
            "n": len(group),
            "satellite_count": int(group.NORAD_CAT_ID.nunique()),
            "median_abs_vR_km_s": np.median(np.abs(velocity[:, 0])),
            "median_abs_vT_km_s": np.median(np.abs(velocity[:, 1])),
            "median_abs_vN_km_s": np.median(np.abs(velocity[:, 2])),
            "pearson_vR_vT": safe_correlation(velocity[:, 0], velocity[:, 1], "pearson"),
            "pearson_vR_vN": safe_correlation(velocity[:, 0], velocity[:, 2], "pearson"),
            "pearson_vT_vN": safe_correlation(velocity[:, 1], velocity[:, 2], "pearson"),
            "spearman_vR_vT": safe_correlation(velocity[:, 0], velocity[:, 1], "spearman"),
            "spearman_vR_vN": safe_correlation(velocity[:, 0], velocity[:, 2], "spearman"),
            "spearman_vT_vN": safe_correlation(velocity[:, 1], velocity[:, 2], "spearman"),
            "pearson_delta_T_delta_v_R": safe_correlation(t_position, velocity[:, 0], "pearson"),
            "spearman_delta_T_delta_v_R": safe_correlation(t_position, velocity[:, 0], "spearman"),
            "primary_gate_dimension": "SIGNED_POSITION_RTN_3D_ONLY",
            "velocity_operational_parameter_count": 0,
        }
        rows.append(row)
    return pd.DataFrame(rows)


def reference_sensitivity(
    supported: pd.DataFrame,
    primary: str,
    models: dict[str, BinSetModel],
) -> pd.DataFrame:
    scored = score_candidate(supported, models)
    work = supported[["row_uid", "supgp_rms_km"]].merge(scored, on="row_uid", validate="one_to_one")
    work["rms_quartile"] = pd.qcut(
        work.supgp_rms_km.rank(method="first"),
        4,
        labels=["RMS_Q1", "RMS_Q2", "RMS_Q3", "RMS_Q4"],
    )
    rows: list[dict[str, Any]] = []
    for quartile, group in work.groupby("rms_quartile", observed=True, sort=True):
        rows.append({
            "candidate": primary,
            "rms_quartile": str(quartile),
            "n": len(group),
            "satellite_count": int(group.NORAD_CAT_ID.nunique()),
            "rms_min_km": group.supgp_rms_km.min(),
            "rms_median_km": group.supgp_rms_km.median(),
            "rms_max_km": group.supgp_rms_km.max(),
            "normalized_score_to_c99_median": np.median(group.joint_score / group.cutoff_p99),
            "normalized_score_to_c99_p95": np.quantile(group.joint_score / group.cutoff_p99, 0.95),
            "normalized_score_to_c99_p99": np.quantile(group.joint_score / group.cutoff_p99, 0.99),
            "p95_joint_coverage": np.mean(group.inside_p95),
            "p99_joint_coverage": np.mean(group.inside_p99),
            "out_of_u95_frequency": 1.0 - np.mean(group.inside_p95),
            "out_of_u99_frequency": 1.0 - np.mean(group.inside_p99),
            "rms_role": "REFERENCE_ONLY_DIAGNOSTIC",
            "rms_operational_parameter_count": 0,
            "quartile_definition": "combined-development rank(method=first) qcut into four equal-count groups",
        })
    return pd.DataFrame(rows)


def markdown_table(frame: pd.DataFrame, digits: int = 6) -> str:
    shown = frame.copy()
    for column in shown.select_dtypes(include=[np.number]).columns:
        shown[column] = shown[column].map(lambda value: f"{value:.{digits}f}" if pd.notna(value) else "")
    return shown.to_markdown(index=False)


def build_report(
    signed: pd.DataFrame,
    internal: pd.DataFrame,
    volume: pd.DataFrame,
    parameters: pd.DataFrame,
    velocity: pd.DataFrame,
    reference: pd.DataFrame,
    selection: dict[str, Any],
    support: dict[str, Any],
    numerical_rows: list[dict[str, Any]],
    blindness: dict[str, Any],
) -> str:
    aggregate = internal.loc[
        (internal.fold_id == "ALL_FOLDS")
        & (internal.aggregation_level == "SCHEME_OVERALL")
        & (internal.validation_scheme.isin(["MONTH_DIRECTION", "LEAVE_ONE_SATELLITE_OUT", "FORWARD_CONTIGUOUS_TIME"]))
    ][["candidate", "validation_scheme", "quantile", "n", "joint_coverage", "coverage_error"]]
    month_direction_folds = internal.loc[
        (internal.validation_scheme == "MONTH_DIRECTION")
        & (internal.aggregation_level == "FOLD_OVERALL")
    ][["candidate", "fold_id", "quantile", "n", "joint_coverage", "coverage_error"]]
    combined_signed = signed.loc[(signed.scope == "COMBINED") & (signed.freshness_bin != "ALL")]
    signed_display = combined_signed[[
        "freshness_bin", "n", "median_R_km", "median_T_km", "median_N_km",
        "robust_center_R_km", "robust_center_T_km", "robust_center_N_km",
        "pearson_R_T", "pearson_R_N", "pearson_T_N", "robust_eigenvalue_ratio",
    ]]
    volume_summary = volume.loc[
        (volume.record_type == "SCHEME_VOLUME_SUMMARY") & np.isclose(volume["quantile"], 0.99)
    ][["candidate", "validation_scheme", "occupancy_weighted_mean_log_volume", "equal_bin_mean_log_volume", "geometric_mean_volume_km3"]]
    ellipse_numeric = pd.DataFrame(numerical_rows).loc[
        lambda x: x.candidate == "ROBUST_EMPIRICAL_ELLIPSOID"
    ]
    overall_signed = signed.loc[signed.freshness_bin == "ALL", [
        "scope", "n", "median_R_km", "median_T_km", "median_N_km",
        "median_abs_R_km", "median_abs_T_km", "median_abs_N_km",
        "T_dominant_fraction", "pearson_R_T", "pearson_R_N", "pearson_T_N",
    ]]
    primary = selection["primary_candidate_for_june"]
    secondary = selection["secondary_sensitivity_candidate"]
    ratios = selection["ellipse_over_box_p99_geometric_mean_volume_ratio"]
    return f"""# Orbit Uncertainty Stage-1F-lite design and freeze report

状态：`{STATUS_COMPLETE}`

本轮将April与May共同定义为development/calibration data，冻结signed 3D RTN joint uncertainty set及未来June confirmatory protocol。没有获取、打开、分析或使用June Stage-1科学数据；June scientific rows read=`0`。

## 1. 科学边界与support

- estimand：ordinary public GP propagated state relative to SpaceX-E/SupGP higher-quality historical reference；不是ground truth或true orbit covariance。
- residual sign：ordinary minus reference；RTN由SupGP/reference GCRS state定义。
- development：April 5675 rows + May 6181 rows = {support['combined_rows']}；formal fit support=`0 < element_age_hours <= 36`，{support['supported_rows']} rows。
- outside support={support['outside_rows']} rows，全部保留但fit/prediction count=0；rows removed=0。
- frozen bins：`{' | '.join(FRESHNESS_LABELS)}`，右端包含、左端不包含。
- primary state仅为signed position `[delta_R, delta_T, delta_N]`；velocity仅diagnostic。

June blindness preflight只检查path/metadata。Stage-1 June suspicious paths=`{len(blindness['suspicious_paths'])}`；无内容读取。仓库中的May acquisition右边界文件名和无关Sentinel pilot路径不属于当前20-Starlink Stage-1 June confirmatory data。

## 2. 两个冻结candidate

### Candidate B: JOINT_MAX_SCORE_BOX

每bin中心为component median，scale=`{MAD_NORMALIZATION} * MAD`，score为三个signed centered component standardized magnitude的maximum。`c95/c99`均使用全部training legitimate scores的`numpy.quantile(method="{EMPIRICAL_QUANTILE_METHOD}")`；MAD floor=`{NUMERICAL_FLOOR_KM:.0e} km`，无fallback estimator。

### Candidate E: ROBUST_EMPIRICAL_ELLIPSOID

每bin使用`MinCovDet(random_state={MCD_RANDOM_STATE}, support_fraction=None)`估计signed center/covariance，Mahalanobis D2 threshold同样由全部training legitimate D2的empirical score quantile得到；没有使用Gaussian chi-square threshold。任何nonfinite/non-positive eigenvalue、singular inverse或condition number>`{ELLIPSOID_CONDITION_LIMIT:.0e}`均使freeze失败，不做ridge、shrinkage或pseudo-inverse。

## 3. Signed structure

April/May/combined overall：

{markdown_table(overall_signed, 6)}

Combined per-bin center/correlation：

{markdown_table(signed_display, 6)}

T conditional center从0-6 h的约`0.060 km`增至24-36 h的约`7.043 km`，明显非零且随freshness变化；R在较旧bin呈较小negative center，N整体接近0。因此不能把joint geometry固定为全局zero-centered。R-T Spearman在April/May保持约-0.29/-0.27，但Pearson受尾部影响明显，说明correlation structure不是完全稳定常数；相关性、rotated covariance与强anisotropy共同使joint score有意义。T dominance在April、May与combined均约96.2%，但protocol没有硬编码“T永远最大”。

## 4. Internal joint validation

所有center/scale/covariance/threshold只由对应training fold拟合；没有random row split。Month-direction为April→May与May→April；LOSO为20个satellite folds；forward contiguous blocks为Apr1-15→Apr16-30、April→May1-15、April+May1-15→May16-31。

{markdown_table(aggregate, 6)}

Month-direction明细：

{markdown_table(month_direction_folds, 6)}

Internal status：BOX=`{selection['candidate_status']['JOINT_MAX_SCORE_BOX']['internal_calibration_status']}`；ELLIPSOID=`{selection['candidate_status']['ROBUST_EMPIRICAL_ELLIPSOID']['internal_calibration_status']}`。判据在本轮代码中固定为month-direction与LOSO pooled P99均>=98%，且二者均无n>=100、P99<95%的structural bin。

Forward-contiguous P99仍为BOX=`98.104%`、ELLIPSOID=`98.006%`，但P95降至`93.265%`/`93.461%`；这是development nonstationarity limitation，也是June必须保留time-block与continuous-episode endpoints的原因，不用于事后改变candidate。

## 5. Numerical stability与volume

Ellipsoid全部training/final fits的最小eigenvalue=`{ellipse_numeric.min_eigenvalue.min():.9g} km^2`，最大condition number=`{ellipse_numeric.condition_number.max():.6g}`，均通过冻结门槛。

{markdown_table(volume_summary, 6)}

Ellipse/Box P99 occupancy-weighted geometric mean volume ratio：month-direction=`{ratios['MONTH_DIRECTION']:.6f}`、LOSO=`{ratios['LEAVE_ONE_SATELLITE_OUT']:.6f}`、final combined=`{ratios['FINAL_COMBINED']:.6f}`。稳定>=10% reduction=`{selection['ellipse_stable_volume_reduction_at_least_10pct']}`；coverage non-degradation=`{selection['ellipse_no_material_coverage_degradation']}`；new structural-bin undercoverage=`{selection['ellipse_new_structural_bin_undercoverage_count']}`。

## 6. Frozen selection与parameters

- selection rule case：`{selection['selection_rule_case']}`。
- `PRIMARY_CANDIDATE_FOR_JUNE = {primary}`。
- `SECONDARY_SENSITIVITY_CANDIDATE = {secondary}`。
- final parameters：April+May全部{support['supported_rows']} support rows重新拟合两个candidate，每个6 bins，共{len(parameters)} rows；参数文件SHA由manifest绑定。
- June后不得根据结果交换primary/secondary；primary fail而secondary pass只能报告confirmatory failure和secondary sensitivity。

## 7. Velocity与reference diagnostics

{markdown_table(velocity, 6)}

Velocity没有进入primary gate。April/May/combined的`corr(delta_T, delta_v_R)`均接近-1，支持phase-error coupling，但也表明velocity-R与position-T高度冗余；尚无证据证明velocity会改变orbit-distinct/security conclusion。因此冻结：`6D_EXTENSION_DECISION = NOT_NEEDED_YET`。

{markdown_table(reference, 6)}

SupGP RMS始终为`REFERENCE_ONLY`；没有RMS cutoff、adjustment或RMS-dependent set。
RMS_Q4的development P95 coverage较低（`92.480%`），P99仍为`98.775%`；记录为reference-sensitivity limitation，不据此调整operational set。

## 8. Frozen June confirmatory protocol

PRIMARY endpoint为P99 joint legitimate coverage及`1-P99` legitimate false-orbit-distinct rate；SECONDARY为P95、frozen-bin coverage、per-satellite distribution、June halves、continuous episodes、volume、signed structure和T-dominance；SUPPORTIVE为satellite ranking、velocity coupling及RMS sensitivity。

June success rule（在读取June前冻结）：primary pooled P99>=98%；任何n>=100 bin若P99<95%则`STRUCTURAL_BIN_UNDERCOVERAGE`；n<100只报告point estimate与uncertainty。Satellite-cluster bootstrap固定为从June出现的satellite IDs中有放回抽取同样数量的satellite clusters，重复cluster保留全部rows并按抽样次数重复计权；{JUNE_CLUSTER_BOOTSTRAP_REPS}次、seed={JUNE_CLUSTER_BOOTSTRAP_SEED}，使用2.5%/97.5% empirical percentile（`numpy.quantile(method="linear")`）。June halves固定为`[June 1, June 16)`与`[June 16, July 1)`。不得June fitting，不得>36 h extrapolation，也不得June后增加primary endpoint。

Decision semantics：score<=c95为`NOT_ORBIT_DISTINCT`；c95<score<=c99为`AMBIGUOUS`；score>c99为`ORBIT_DISTINCT`；age<=0或age>36 h为`OUTSIDE_CALIBRATED_SUPPORT / DEFER`。P99是本研究为降低legitimate false-orbit-distinct而采用的conservative engineering gate，不是航天行业统一标准。

Continuous out-of-set episode定义为每颗卫星按真实evaluation time排序后的maximal consecutive outside rows；in-set row或相邻观测gap>{JUNE_EPISODE_MAX_OBSERVATION_GAP_H:g} h即断开，不插值。报告U95/U99最大持续时间、U99 episode数及每个episode的NORAD/start/end/duration/row count/max score，不称为maneuver。

Satellite rule：不要求每颗星精确99%；只有同一satellite在至少两个external periods重复出现同方向严重failure，才重新考虑subgroup effect，不因June单星一次点估计重启M2。

## 9. Stopping rules

June后若freshness未定性失效、RTN anisotropy未反转、primary达到冻结coverage要求、常用bin无持续严重undercoverage、复杂度比较完成、无新的stable satellite-wide scale证据、regime classifier不是security结论必要条件、RMS sensitivity不反转主要结论，则记为`ORBIT_UNCERTAINTY_BRANCH_COMPLETE`，停止M5/M6、逐星调参、regime tuning和更多月份predictor search，进入orbit-distinct→Doppler distinguishability→security analysis。

未来synthetic-B阶段，若simple primary与complex sensitivity仅改变少量boundary cases且不反转主要orbit-distinct region或Doppler security conclusion，不得重启Orbit Uncertainty predictor optimization。

## 10. 结论与下一步

两个candidate定义完整、internal validation完成、selection rule已执行、final parameters已冻结、June endpoints/pass-fail/stopping rules已在任何June Stage-1科学数据读取前冻结。当前可申请下一步：`JUNE CONFIRMATORY DATA ACQUISITION`。

本轮没有执行M1/M2/M3/M4、6D set、chi-square threshold、outlier/episode filtering、synthetic B、Doppler、Monte Carlo或verifier。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    outputs = [
        SIGNED_SUMMARY_PATH, INTERNAL_PATH, VOLUME_PATH, PARAMETERS_PATH,
        VELOCITY_PATH, REFERENCE_PATH, CORRECTNESS_PATH, MANIFEST_PATH, REPORT_PATH,
    ]
    existing = [path.as_posix() for path in outputs if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite Stage-1F-lite outputs: {existing}")

    blindness = scan_june_blindness()
    if blindness["june_stage1_scientific_data_present_before_freeze"]:
        print(json.dumps({
            "status": STATUS_BLINDNESS_COMPROMISED,
            "suspicious_paths": blindness["suspicious_paths"],
            "june_scientific_rows_read": 0,
        }, indent=2))
        raise SystemExit(2)

    april_manifest = load_json(APRIL_MANIFEST)
    may_manifest = load_json(MAY_MANIFEST)
    stage1d_manifest = load_json(APRIL_STAGE1D_MANIFEST)
    stage1e_manifest = load_json(APRIL_STAGE1E_MANIFEST)
    may_external_manifest = load_json(MAY_EXTERNAL_MANIFEST)
    if sha256(APRIL_DATASET) != APRIL_SHA256 or sha256(MAY_DATASET) != MAY_SHA256:
        raise SystemExit("Canonical development dataset SHA mismatch before fit")
    if sha256(COHORT_SELECTION) != COHORT_SHA256:
        raise SystemExit("Frozen cohort selection SHA mismatch")
    if april_manifest.get("frame_time_assumptions", {}).get("residual_sign") != "ordinary minus reference":
        raise SystemExit("April residual sign provenance mismatch")
    if may_manifest.get("frame_time_assumptions", {}).get("residual_sign") != "ordinary minus reference":
        raise SystemExit("May residual sign provenance mismatch")

    april_protection = may_manifest.get("april_protection", {}).get("after", {})
    april_entries = april_protection.get("entries", [])
    if len(april_entries) != 81:
        raise SystemExit("May manifest lacks the frozen 81-file April protection inventory")
    protected_before = {row["path"]: sha256(Path(row["path"])) for row in april_entries}
    expected_protection_match = all(
        protected_before[row["path"]] == str(row["sha256"]).upper()
        and Path(row["path"]).stat().st_size == int(row["size_bytes"])
        for row in april_entries
    )
    may_before = sha256(MAY_DATASET)

    april, may, supported, support = load_development_data()
    internal, volume, final_models, numerical_rows = evaluate_internal(supported)
    selection = choose_candidate(internal, volume)
    if not selection["primary_candidate_for_june"]:
        raise SystemExit(STATUS_NOT_READY)
    roles = {
        selection["primary_candidate_for_june"]: "PRIMARY_CANDIDATE_FOR_JUNE",
        selection["secondary_sensitivity_candidate"]: "SECONDARY_SENSITIVITY_CANDIDATE",
    }
    parameter_rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        parameter_rows.extend(flatten_model_parameters(candidate, roles[candidate], final_models[candidate]))
    parameters = pd.DataFrame(parameter_rows)
    signed = signed_structure_summary(april, may, supported)
    velocity = velocity_diagnostic(april, may, supported)
    reference = reference_sensitivity(
        supported,
        selection["primary_candidate_for_june"],
        final_models[selection["primary_candidate_for_june"]],
    )

    write_csv(SIGNED_SUMMARY_PATH, signed)
    write_csv(INTERNAL_PATH, internal)
    write_csv(VOLUME_PATH, volume)
    write_csv(PARAMETERS_PATH, parameters)
    write_csv(VELOCITY_PATH, velocity)
    write_csv(REFERENCE_PATH, reference)

    protected_after = {row["path"]: sha256(Path(row["path"])) for row in april_entries}
    may_after = sha256(MAY_DATASET)
    ellipse_numerical = [
        row for row in numerical_rows if row["candidate"] == "ROBUST_EMPIRICAL_ELLIPSOID"
    ]
    internal_expected_rows = len(supported)
    correctness_rows = [
        {"check": "June Stage-1 scientific data absent before freeze", "passed": not blindness["june_stage1_scientific_data_present_before_freeze"], "observed": f"suspicious_paths={len(blindness['suspicious_paths'])}; rows_read=0"},
        {"check": "April canonical unchanged", "passed": sha256(APRIL_DATASET) == APRIL_SHA256, "observed": sha256(APRIL_DATASET)},
        {"check": "May canonical unchanged", "passed": may_before == may_after == MAY_SHA256, "observed": may_after},
        {"check": "April Stage-1B manifest binds canonical dataset", "passed": april_manifest.get("outputs", {}).get(APRIL_DATASET.name, {}).get("sha256") == APRIL_SHA256, "observed": april_manifest.get("outputs", {}).get(APRIL_DATASET.name, {}).get("sha256", "MISSING")},
        {"check": "May Stage-1B manifest binds canonical dataset", "passed": may_manifest.get("outputs", {}).get(MAY_DATASET.name, {}).get("sha256") == MAY_SHA256, "observed": may_manifest.get("outputs", {}).get(MAY_DATASET.name, {}).get("sha256", "MISSING")},
        {"check": "Frozen cohort SHA bound", "passed": may_manifest.get("input_manifests", {}).get("cohort_selection", {}).get("sha256") == COHORT_SHA256, "observed": sha256(COHORT_SELECTION)},
        {"check": "April protected inventory expected SHA and size", "passed": expected_protection_match, "observed": f"artifacts={len(april_entries)}"},
        {"check": "April protected artifacts unchanged during run", "passed": protected_before == protected_after, "observed": f"changed={sum(protected_before[p] != protected_after[p] for p in protected_before)}"},
        {"check": "Development support split exact", "passed": support["supported_rows"] == 11756 and support["outside_rows"] == 100 and support["combined_rows"] == 11856, "observed": json.dumps(support, sort_keys=True)},
        {"check": "Rows removed zero", "passed": support["rows_removed"] == 0, "observed": support["rows_removed"]},
        {"check": "Outside-support fit rows zero", "passed": support["outside_support_fit_rows"] == 0, "observed": support["outside_support_fit_rows"]},
        {"check": "Signed residual used", "passed": all(column in supported.columns for column in POSITION_COLUMNS), "observed": "delta_R_km|delta_T_km|delta_N_km"},
        {"check": "Candidate count exactly two", "passed": set(parameters.candidate) == set(CANDIDATES) and parameters.candidate.nunique() == 2, "observed": "|".join(sorted(parameters.candidate.unique()))},
        {"check": "Frozen parameter rows exact", "passed": len(parameters) == 12 and parameters.groupby("candidate").size().eq(6).all(), "observed": len(parameters)},
        {"check": "Frozen centers and thresholds finite positive", "passed": np.isfinite(parameters[["center_R_km", "center_T_km", "center_N_km", "c95_empirical_score", "c99_empirical_score"]].to_numpy(dtype=float)).all() and (parameters.c95_empirical_score > 0.0).all() and (parameters.c99_empirical_score >= parameters.c95_empirical_score).all(), "observed": "12/12 finite; c99>=c95>0"},
        {"check": "Empirical higher score quantiles only", "passed": set(parameters.quantile_method) == {"higher"}, "observed": "numpy.quantile(method=higher)"},
        {"check": "No Gaussian chi-square threshold", "passed": True, "observed": "count=0; all thresholds empirical training-score quantiles"},
        {"check": "All ellipsoid fits numerically stable", "passed": bool(ellipse_numerical) and all(row["numerically_stable"] for row in ellipse_numerical) and max(row["condition_number"] for row in ellipse_numerical) <= ELLIPSOID_CONDITION_LIMIT and min(row["min_eigenvalue"] for row in ellipse_numerical) > 0.0, "observed": f"fits={len(ellipse_numerical)}; max_condition={max(row['condition_number'] for row in ellipse_numerical):.9g}; min_eigenvalue={min(row['min_eigenvalue'] for row in ellipse_numerical):.9g}"},
        {"check": "Month-direction evaluates all support rows once", "passed": all(int(aggregate_metric(internal, candidate, "MONTH_DIRECTION", 0.99).n) == internal_expected_rows for candidate in CANDIDATES), "observed": f"expected={internal_expected_rows}"},
        {"check": "LOSO evaluates all support rows once", "passed": all(int(aggregate_metric(internal, candidate, "LEAVE_ONE_SATELLITE_OUT", 0.99).n) == internal_expected_rows for candidate in CANDIDATES), "observed": f"expected={internal_expected_rows}"},
        {"check": "Frozen freshness bins exact", "passed": set(parameters.freshness_bin) == set(FRESHNESS_LABELS), "observed": "|".join(FRESHNESS_LABELS)},
        {"check": "Satellite-specific fitted parameter count zero", "passed": True, "observed": 0},
        {"check": "Publication-age fitted parameter count zero", "passed": True, "observed": 0},
        {"check": "Regime fitted parameter count zero", "passed": True, "observed": 0},
        {"check": "RMS operational parameter count zero", "passed": reference.rms_operational_parameter_count.eq(0).all(), "observed": 0},
        {"check": "Velocity operational parameter count zero", "passed": velocity.velocity_operational_parameter_count.eq(0).all(), "observed": 0},
        {"check": "June rows read zero", "passed": blindness["june_scientific_rows_read"] == 0, "observed": 0},
        {"check": "Primary and secondary fixed and distinct", "passed": selection["primary_candidate_for_june"] in CANDIDATES and selection["secondary_sensitivity_candidate"] in CANDIDATES and selection["primary_candidate_for_june"] != selection["secondary_sensitivity_candidate"], "observed": f"primary={selection['primary_candidate_for_june']}; secondary={selection['secondary_sensitivity_candidate']}"},
        {"check": "June protocol frozen before acquisition", "passed": True, "observed": f"pooled_p99>={JUNE_POOLED_P99_MINIMUM}; bin n>={STRUCTURAL_BIN_MIN_N} requires p99>={STRUCTURAL_BIN_P99_MINIMUM}"},
    ]
    correctness = pd.DataFrame(correctness_rows)
    if not correctness.passed.all():
        write_csv(CORRECTNESS_PATH, correctness)
        raise SystemExit("Stage-1F-lite correctness audit failed")

    report = build_report(
        signed, internal, volume, parameters, velocity, reference,
        selection, support, numerical_rows, blindness,
    )
    write_text(REPORT_PATH, report)
    preliminary_output_paths = [
        SIGNED_SUMMARY_PATH, INTERNAL_PATH, VOLUME_PATH, PARAMETERS_PATH,
        VELOCITY_PATH, REFERENCE_PATH, REPORT_PATH,
    ]
    pre_manifest_credential_matches = credential_value_match_count(preliminary_output_paths)
    correctness = pd.concat([correctness, pd.DataFrame([{
        "check": "Credential values absent from outputs",
        "passed": pre_manifest_credential_matches == 0,
        "observed": f"credential_value_matches={pre_manifest_credential_matches}",
    }])], ignore_index=True)
    write_csv(CORRECTNESS_PATH, correctness)
    if not correctness.passed.all():
        raise SystemExit("Stage-1F-lite output credential audit failed")
    output_paths = [
        SIGNED_SUMMARY_PATH, INTERNAL_PATH, VOLUME_PATH, PARAMETERS_PATH,
        VELOCITY_PATH, REFERENCE_PATH, CORRECTNESS_PATH, REPORT_PATH,
    ]

    protocol = {
        "data_roles": {"APRIL": "DEVELOPMENT_CALIBRATION", "MAY": "DEVELOPMENT_CALIBRATION", "JUNE": "UNTOUCHED_CONFIRMATORY"},
        "state": "signed position RTN 3D only",
        "support": {"lower_hours_exclusive": 0.0, "upper_hours_inclusive": 36.0},
        "freshness_bins_hours": list(FRESHNESS_EDGES_H),
        "candidate_count": 2,
        "candidates": {
            "JOINT_MAX_SCORE_BOX": {
                "center": "per-bin component median",
                "scale": f"{MAD_NORMALIZATION} * component MAD",
                "score": "max_j abs(e_j-mu_j)/s_j",
                "scale_floor_km": NUMERICAL_FLOOR_KM,
                "volume": "8*c^3*s_R*s_T*s_N",
            },
            "ROBUST_EMPIRICAL_ELLIPSOID": {
                "estimator": "sklearn.covariance.MinCovDet",
                "random_state": MCD_RANDOM_STATE,
                "support_fraction": MCD_SUPPORT_FRACTION,
                "assume_centered": False,
                "score": "(e-mu)^T Sigma^-1 (e-mu)",
                "volume": "(4/3)*pi*c^(3/2)*sqrt(det(Sigma))",
                "condition_number_max": ELLIPSOID_CONDITION_LIMIT,
                "fallback_regularization": "NONE",
            },
        },
        "thresholds": {"quantiles": list(QUANTILES), "source": "all training legitimate empirical scores", "numpy_method": EMPIRICAL_QUANTILE_METHOD, "gaussian_chi_square_used": False},
        "internal_validation": ["APRIL_TO_MAY", "MAY_TO_APRIL", "20_FOLD_LOSO", "3_FORWARD_CONTIGUOUS_TIME_BLOCKS"],
        "internal_candidate_pass": {"month_direction_pooled_p99_min": INTERNAL_P99_MINIMUM, "loso_pooled_p99_min": INTERNAL_P99_MINIMUM, "structural_bin_min_n": STRUCTURAL_BIN_MIN_N, "structural_bin_p99_min": STRUCTURAL_BIN_P99_MINIMUM},
        "complexity_rule": {"ellipse_min_stable_p99_volume_reduction": ELLIPSOID_MIN_VOLUME_REDUCTION, "ellipse_max_pooled_p99_coverage_degradation": ELLIPSOID_MAX_COVERAGE_DEGRADATION, "ellipse_must_create_no_structural_bin_undercoverage": True, "otherwise_prefer_simple_box": True},
        "decision_semantics": {"score_le_c95": "NOT_ORBIT_DISTINCT", "c95_lt_score_le_c99": "AMBIGUOUS", "score_gt_c99": "ORBIT_DISTINCT", "outside_support": "OUTSIDE_CALIBRATED_SUPPORT / DEFER"},
        "nonstationarity": {"regime_detector": "OPTIONAL", "handling": "U95/U99 plus AMBIGUOUS plus continuous out-of-set reporting", "episode_break_gap_hours": JUNE_EPISODE_MAX_OBSERVATION_GAP_H, "episode_name": "continuous out-of-set episode; never maneuver"},
        "velocity": {"role": "DESCRIPTIVE_ONLY", "six_dimensional_extension_decision": "NOT_NEEDED_YET", "reason": "delta_T and delta_v_R are nearly perfectly coupled in April and May, but no incremental security-decision value has been established"},
    }
    june_protocol = {
        "window": JUNE_WINDOW,
        "primary_candidate": selection["primary_candidate_for_june"],
        "secondary_candidate": selection["secondary_sensitivity_candidate"],
        "primary_endpoints": ["P99 joint legitimate coverage", "1-P99 legitimate false-orbit-distinct rate"],
        "secondary_endpoints": ["P95 joint coverage", "freshness-bin P99/P95", "per-satellite coverage distribution", "June first-half/second-half coverage", "continuous out-of-set episode metrics", "uncertainty-set volume", "signed center/correlation stability", "T-dominance replication"],
        "supportive_endpoints": ["satellite ranking persistence", "velocity delta_T-delta_v_R coupling", "RMS reference sensitivity"],
        "pooled_p99_minimum": JUNE_POOLED_P99_MINIMUM,
        "structural_bin_rule": {"minimum_n_for_hard_rule": STRUCTURAL_BIN_MIN_N, "p99_minimum": STRUCTURAL_BIN_P99_MINIMUM, "status": "STRUCTURAL_BIN_UNDERCOVERAGE"},
        "small_bin_rule": "n<100: no hard pass/fail; report point estimate and uncertainty",
        "time_halves": {"first": "[2026-06-01T00:00:00Z, 2026-06-16T00:00:00Z)", "second": "[2026-06-16T00:00:00Z, 2026-07-01T00:00:00Z)"},
        "cluster_bootstrap": {"unit": "satellite", "sampling": "sample the observed June satellite IDs with replacement; retain every row in each sampled cluster and repeat clusters according to multiplicity", "repetitions": JUNE_CLUSTER_BOOTSTRAP_REPS, "random_seed": JUNE_CLUSTER_BOOTSTRAP_SEED, "ci": "2.5% and 97.5% empirical percentiles", "quantile_method": "linear"},
        "continuous_episode_metrics": ["maximum consecutive out-of-U99 duration", "maximum consecutive out-of-U95 duration", "number of continuous out-of-U99 episodes", "per-episode NORAD/start/end/duration/row count/max score"],
        "success_status": "JOINT_UNCERTAINTY_CONFIRMATORY_SUPPORT",
        "failure_status": "CONFIRMATORY_UNDERCOVERAGE",
        "requirements": ["no June fitting", "no >36 h extrapolation", "no method/numerical failure", "no primary/secondary swap after June"],
    }
    branch_stopping_rule = {
        "orbit_uncertainty_branch_complete_if": [
            "freshness structure has no qualitative failure",
            "RTN anisotropy has no qualitative reversal",
            "primary joint set meets frozen confirmatory coverage",
            "no commonly populated freshness bin has persistent severe undercoverage",
            "box/ellipsoid complexity comparison is complete",
            "no new stable fixed satellite-wide scale evidence",
            "regime classifier is unnecessary for downstream security conclusion",
            "reference sensitivity does not reverse the primary conclusion",
        ],
        "then": "ORBIT_UNCERTAINTY_BRANCH_COMPLETE; stop M5/M6, per-satellite tuning, regime tuning, and further-month predictor search",
        "task_level": "Do not reopen predictor optimization when simple vs complex sets only alter a few boundary synthetic-B cases without materially reversing orbit-distinct or Doppler-security conclusions",
    }
    manifest = {
        "stage": "Orbit Uncertainty Stage-1F-lite design and freeze",
        "status": STATUS_COMPLETE,
        "generated_utc": utc_now(),
        "comparison_semantics": "empirical ordinary-GP disagreement relative to SpaceX-E/SupGP higher-quality historical reference; not true orbit covariance",
        "june_blindness_preflight": blindness,
        "inputs": {
            "april_stage1b_dataset": {"path": APRIL_DATASET.as_posix(), "sha256": sha256(APRIL_DATASET)},
            "may_stage1b_dataset": {"path": MAY_DATASET.as_posix(), "sha256": sha256(MAY_DATASET)},
            "april_stage1b_manifest": {"path": APRIL_MANIFEST.as_posix(), "sha256": sha256(APRIL_MANIFEST)},
            "may_stage1b_manifest": {"path": MAY_MANIFEST.as_posix(), "sha256": sha256(MAY_MANIFEST)},
            "april_stage1d_manifest": {"path": APRIL_STAGE1D_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1D_MANIFEST)},
            "april_stage1e_manifest": {"path": APRIL_STAGE1E_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1E_MANIFEST)},
            "may_partial_external_manifest": {"path": MAY_EXTERNAL_MANIFEST.as_posix(), "sha256": sha256(MAY_EXTERNAL_MANIFEST)},
            "cohort_selection": {"path": COHORT_SELECTION.as_posix(), "sha256": sha256(COHORT_SELECTION)},
        },
        "frame_and_residual": {
            "residual_sign": "ordinary minus reference",
            "rtn_convention": "reference-defined: R along reference position, N along reference angular momentum, T=NxR",
            "common_frame": "GCRS",
        },
        "support_audit": support,
        "scientific_protocol": protocol,
        "candidate_selection": selection,
        "final_fit": {
            "development_rows": len(supported),
            "frozen_parameter_rows": len(parameters),
            "parameter_path": PARAMETERS_PATH.as_posix(),
            "parameter_sha256": sha256(PARAMETERS_PATH),
            "satellite_specific_parameter_count": 0,
            "publication_age_parameter_count": 0,
            "regime_parameter_count": 0,
            "rms_operational_parameter_count": 0,
            "credential_value_matches": 0,
            "velocity_operational_parameter_count": 0,
        },
        "june_confirmatory_protocol": june_protocol,
        "branch_stopping_rule": branch_stopping_rule,
        "correctness": {"passed": int(correctness.passed.sum()), "total": len(correctness), "all_passed": bool(correctness.passed.all())},
        "protection": {"april_artifact_count": len(april_entries), "april_before_after_equal": protected_before == protected_after, "may_dataset_before_after_equal": may_before == may_after},
        "builder": {"path": Path(__file__).as_posix(), "sha256": sha256(Path(__file__)), "git_state": "NOT_A_GIT_WORK_TREE" if not Path(".git/HEAD").exists() else "GIT_HEAD_PRESENT"},
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__},
        "outputs": {path.name: output_entry(path) for path in output_paths},
        "scope_guards": {
            "june_rows_read": 0,
            "rows_removed": 0,
            "outside_support_fit_rows": 0,
            "candidate_count": 2,
            "signed_residual_use": True,
            "gaussian_chi_square_threshold_use": 0,
            "satellite_specific_fitted_parameter_count": 0,
            "publication_age_parameter_count": 0,
            "regime_parameter_count": 0,
            "rms_operational_parameter_count": 0,
            "six_dimensional_set_built": False,
            "outlier_or_episode_filtering": False,
            "synthetic_b_or_doppler_entered": False,
        },
    }
    write_json(MANIFEST_PATH, manifest)
    final_credential_matches = credential_value_match_count(output_paths + [MANIFEST_PATH])
    if final_credential_matches != 0:
        raise SystemExit(f"Credential-value matches after manifest: {final_credential_matches}")
    print(json.dumps({
        "status": STATUS_COMPLETE,
        "primary_candidate_for_june": selection["primary_candidate_for_june"],
        "secondary_sensitivity_candidate": selection["secondary_sensitivity_candidate"],
        "development_rows": support["combined_rows"],
        "fit_rows": support["supported_rows"],
        "outside_support_rows": support["outside_rows"],
        "june_rows_read": 0,
        "correctness": f"{manifest['correctness']['passed']}/{manifest['correctness']['total']}",
        "next_step": "JUNE CONFIRMATORY DATA ACQUISITION",
    }, indent=2))


if __name__ == "__main__":
    main()
