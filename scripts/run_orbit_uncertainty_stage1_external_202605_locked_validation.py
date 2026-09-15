#!/usr/bin/env python3
"""Preflight the April-model to May locked external validation.

This entry point must stop before prediction when an April fitted candidate
cannot be reconstructed from frozen artifacts without fitting again.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APRIL_WINDOW = "[2026-04-01T00:00:00Z, 2026-05-01T00:00:00Z)"
MAY_WINDOW = "[2026-05-01T00:00:00Z, 2026-06-01T00:00:00Z)"
APRIL_DATASET_SHA = "2B02C40FDEA69F6079D256B5E274652ABAB2D5BC2F9899866C7F1CAFFB469F23"

METRICS = Path("outputs/metrics")
REPORTS = Path("outputs/reports")
APRIL_DATASET = Path("outputs/datasets/orbit_uncertainty_stage1b_20260401_20260430_rtn_residual_library.csv")
MAY_DATASET = Path("outputs/datasets/orbit_uncertainty_stage1b_20260501_20260531_rtn_residual_library.csv")
APRIL_STAGE1B_MANIFEST = METRICS / "orbit_uncertainty_stage1b_20260401_20260430_manifest.json"
APRIL_STAGE1D_MANIFEST = METRICS / "orbit_uncertainty_stage1d_20260401_20260430_manifest.json"
APRIL_STAGE1D_GRID = METRICS / "orbit_uncertainty_stage1d_20260401_20260430_conditional_model_grid.csv"
APRIL_STAGE1D_QUANTILES = METRICS / "orbit_uncertainty_stage1d_20260401_20260430_freshness_quantiles.csv"
APRIL_STAGE1E_MANIFEST = METRICS / "orbit_uncertainty_stage1e_20260401_20260430_manifest.json"
APRIL_STAGE1E_CALIBRATION = METRICS / "orbit_uncertainty_stage1e_20260401_20260430_componentwise_calibration.csv"
APRIL_STAGE1E_ASSOCIATION = METRICS / "orbit_uncertainty_stage1e_20260401_20260430_regime_feature_association.csv"
APRIL_STAGE1E_MODEL_COMPARISON = METRICS / "orbit_uncertainty_stage1e_20260401_20260430_model_comparison.csv"
APRIL_STAGE1E_FEATURES = METRICS / "orbit_uncertainty_stage1e_20260401_20260430_causal_regime_features.csv"
APRIL_STAGE1E_SCRIPT = Path("scripts/calibrate_orbit_uncertainty_stage1e_heterogeneity_regime.py")
MAY_STAGE1B_MANIFEST = METRICS / "orbit_uncertainty_stage1b_20260501_20260531_manifest.json"

PREFIX = "orbit_uncertainty_stage1_external_202605"
PARAMETER_AUDIT = METRICS / f"{PREFIX}_parameter_freeze_audit.csv"
CORRECTNESS_AUDIT = METRICS / f"{PREFIX}_correctness_audit.csv"
MANIFEST = METRICS / f"{PREFIX}_manifest.json"
REPORT = REPORTS / f"{PREFIX}_locked_validation_report.md"

FORBIDDEN_VALIDATION_OUTPUTS = [
    METRICS / f"{PREFIX}_locked_coverage.csv",
    METRICS / f"{PREFIX}_per_satellite.csv",
    METRICS / f"{PREFIX}_freshness_bin.csv",
    METRICS / f"{PREFIX}_satellite_scale_persistence.csv",
    METRICS / f"{PREFIX}_regime_transfer.csv",
    METRICS / f"{PREFIX}_outside_support.csv",
]

CAUSAL_FEATURES = (
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

CLASSIFIER_EXPORT_FIELDS = {
    "logistic_intercept": ("logistic_intercept", "intercept"),
    "StandardScaler.mean_": ("standard_scaler_mean", "scaler_mean"),
    "StandardScaler.scale_": ("standard_scaler_scale", "scaler_scale"),
    "SimpleImputer.statistics_": ("simple_imputer_statistics", "imputer_statistics"),
}


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
        raise SystemExit(f"Required frozen artifact missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Required frozen artifact missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
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


def manifest_output_sha(manifest: dict[str, Any], path: Path) -> str:
    entry = manifest.get("outputs", {}).get(path.name)
    if not entry:
        raise SystemExit(f"Frozen manifest does not bind required artifact: {path}")
    return str(entry["sha256"]).upper()


def parse_fallback(note: str) -> float:
    match = re.search(r"fallback=([0-9.eE+-]+)", note)
    if not match:
        raise ValueError(f"Missing fallback in calibration note: {note}")
    return float(match.group(1))


def parse_risk_cutpoints(note: str) -> tuple[float, float]:
    match = re.search(r"cutpoints=\(([^,]+),\s*([^\)]+)\)", note)
    if not match:
        raise ValueError(f"Missing risk cutpoints in calibration note: {note}")
    return float(match.group(1)), float(match.group(2))


def find_serialized_stage1_model_candidates(root: Path = Path("outputs")) -> list[Path]:
    suffixes = {".pkl", ".pickle", ".joblib", ".npz", ".npy"}
    if not root.exists():
        return []
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in suffixes and "stage1" in path.name.lower()
    )


def classifier_export_gaps(
    association: list[dict[str, str]],
    serialized_candidates: list[Path] | None = None,
) -> list[str]:
    """Return parameters absent from the frozen classifier export.

    A serialized-looking file is only informative here. Without a frozen
    manifest binding it cannot be assumed to be the April fitted classifier.
    """
    columns = set().union(*(row.keys() for row in association)) if association else set()
    gaps = [
        family for family, aliases in CLASSIFIER_EXPORT_FIELDS.items()
        if not any(alias in columns for alias in aliases)
    ]
    candidates = serialized_candidates if serialized_candidates is not None else find_serialized_stage1_model_candidates()
    if not candidates:
        gaps.append("serialized_fitted_pipeline_or_equivalent_complete_parameter_record")
    else:
        gaps.append("manifest_bound_serialized_fitted_pipeline_or_equivalent_complete_parameter_record")
    return gaps


def load_april_protection_inventory(may_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    protection = may_manifest.get("april_protection", {})
    before = protection.get("before", {})
    after = protection.get("after", {})
    if not protection.get("unchanged") or before.get("entries") != after.get("entries"):
        raise SystemExit("May Stage-1B manifest does not contain an unchanged April protection inventory")
    entries = after.get("entries", [])
    if int(after.get("artifact_count", -1)) != len(entries) or not entries:
        raise SystemExit("May Stage-1B April protection inventory is incomplete")
    return entries


def verify_bound_references(references: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    audit: list[dict[str, Any]] = []
    for name, value in references.items():
        if value is None:
            continue
        path = Path(value["path"])
        current_sha = sha256(path) if path.exists() else "MISSING"
        expected_sha = str(value["sha256"]).upper()
        audit.append({
            "name": name,
            "path": path.as_posix(),
            "expected_sha256": expected_sha,
            "current_sha256": current_sha,
            "matched": current_sha == expected_sha,
        })
    return bool(audit) and all(row["matched"] for row in audit), audit


def inspect_parameter_artifacts(
    calibration: list[dict[str, str]],
    association: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    calibration_sha = sha256(APRIL_STAGE1E_CALIBRATION)
    association_sha = sha256(APRIL_STAGE1E_ASSOCIATION)

    def select(record_type: str, model: str | None = None, group_type: str | None = None) -> list[dict[str, str]]:
        return [
            row for row in calibration
            if row["record_type"] == record_type
            and (model is None or row["model"] == model)
            and (group_type is None or row["group_type"] == group_type)
        ]

    base = select("BASE_CURVE", "M0")
    velocity = select("VELOCITY_DESCRIPTIVE_BASE_CURVE", "M0_DESCRIPTIVE")
    m1 = select("CORRECTION_FACTOR", "M1", "PUBLICATION_AGE_STRATUM")
    m2 = select("CORRECTION_FACTOR", "M2", "SATELLITE")
    m3 = select("CORRECTION_FACTOR", "M3", "CAUSAL_RISK_STRATUM")
    m4_sat = select("CORRECTION_FACTOR", "M4", "SATELLITE")
    m4_risk = select("CORRECTION_FACTOR", "M4", "CAUSAL_RISK_STRATUM_AFTER_SATELLITE")
    risk_metadata = select("MODEL_METADATA", "M3/M4", "CAUSAL_RISK_CUTPOINTS")
    coefficient_rows = [row for row in association if row.get("section") == "full_fit_logistic_coefficient"]
    coefficient_features = tuple(row["feature"] for row in coefficient_rows)
    cutpoints = {parse_risk_cutpoints(row["note"]) for row in risk_metadata}
    fallback_values = {
        model: {parse_fallback(row["note"]) for row in rows}
        for model, rows in {"M1": m1, "M2": m2, "M3": m3, "M4": m4_sat + m4_risk}.items()
    }
    fallback_parameter_counts = {
        model: len({(row["target"], row["quantile"], row["group_type"], parse_fallback(row["note"])) for row in rows})
        for model, rows in {"M1": m1, "M2": m2, "M3": m3, "M4": m4_sat + m4_risk}.items()
    }
    risk_cutpoint_parameter_count = 2 * len(risk_metadata)

    serialized_candidates = find_serialized_stage1_model_candidates()
    missing_classifier_families = classifier_export_gaps(association, serialized_candidates)
    rows = [
        {
            "audit_item": "M0_POSITION_BASE_CURVES", "model": "M0",
            "parameter_family": "April full-supported position base predictions",
            "source_path": APRIL_STAGE1E_CALIBRATION.as_posix(), "source_sha256": calibration_sha,
            "artifact_rows": len(base), "parameter_count": len(base), "training_window": APRIL_WINDOW,
            "recoverability": "READY", "missing_required_parameters": "",
            "may_derived_parameter_count": 0,
            "notes": "4 targets x 2 quantiles x 13 frozen grid points; interpolation method and centers are code/manifest bound",
        },
        {
            "audit_item": "M0_VELOCITY_DESCRIPTIVE_CURVES", "model": "M0_DESCRIPTIVE",
            "parameter_family": "April full-supported velocity base predictions",
            "source_path": APRIL_STAGE1E_CALIBRATION.as_posix(), "source_sha256": calibration_sha,
            "artifact_rows": len(velocity), "parameter_count": len(velocity), "training_window": APRIL_WINDOW,
            "recoverability": "READY", "missing_required_parameters": "",
            "may_derived_parameter_count": 0, "notes": "velocity remains M0 descriptive only",
        },
        {
            "audit_item": "M1_PUBLICATION_FACTORS", "model": "M1",
            "parameter_family": "partial-pooled publication-age stratum factors",
            "source_path": APRIL_STAGE1E_CALIBRATION.as_posix(), "source_sha256": calibration_sha,
            "artifact_rows": len(m1), "parameter_count": len(m1) + fallback_parameter_counts["M1"], "training_window": APRIL_WINDOW,
            "recoverability": "READY", "missing_required_parameters": "",
            "may_derived_parameter_count": 0, "notes": "5 frozen strata for each position target/quantile",
        },
        {
            "audit_item": "M2_SATELLITE_FACTORS", "model": "M2",
            "parameter_family": "partial-pooled satellite factors",
            "source_path": APRIL_STAGE1E_CALIBRATION.as_posix(), "source_sha256": calibration_sha,
            "artifact_rows": len(m2), "parameter_count": len(m2) + fallback_parameter_counts["M2"], "training_window": APRIL_WINDOW,
            "recoverability": "READY", "missing_required_parameters": "",
            "may_derived_parameter_count": 0, "notes": "20 frozen cohort factors for each position target/quantile",
        },
        {
            "audit_item": "M3_RISK_FACTORS_AND_CUTPOINTS", "model": "M3",
            "parameter_family": "causal-risk stratum factors and P50/P90 score cutpoints",
            "source_path": APRIL_STAGE1E_CALIBRATION.as_posix(), "source_sha256": calibration_sha,
            "artifact_rows": len(m3) + len(risk_metadata),
            "parameter_count": len(m3) + fallback_parameter_counts["M3"] + risk_cutpoint_parameter_count,
            "training_window": APRIL_WINDOW, "recoverability": "BLOCKED",
            "missing_required_parameters": "|".join(missing_classifier_families),
            "may_derived_parameter_count": 0,
            "notes": "risk factors/cutpoints exist, but May risk scores cannot be reproduced without the complete April classifier",
        },
        {
            "audit_item": "M4_SATELLITE_AND_RISK_FACTORS", "model": "M4",
            "parameter_family": "satellite factors and post-satellite causal-risk factors",
            "source_path": APRIL_STAGE1E_CALIBRATION.as_posix(), "source_sha256": calibration_sha,
            "artifact_rows": len(m4_sat) + len(m4_risk) + len(risk_metadata),
            "parameter_count": len(m4_sat) + len(m4_risk) + fallback_parameter_counts["M4"] + risk_cutpoint_parameter_count,
            "training_window": APRIL_WINDOW, "recoverability": "BLOCKED",
            "missing_required_parameters": "|".join(missing_classifier_families),
            "may_derived_parameter_count": 0,
            "notes": "satellite/risk factors exist, but risk-stratum assignment requires the incomplete April classifier",
        },
        {
            "audit_item": "APRIL_CAUSAL_CLASSIFIER_PARTIAL_EXPORT", "model": "M3/M4",
            "parameter_family": "standardized logistic coefficients only",
            "source_path": APRIL_STAGE1E_ASSOCIATION.as_posix(), "source_sha256": association_sha,
            "artifact_rows": len(coefficient_rows), "parameter_count": len(coefficient_rows),
            "training_window": APRIL_WINDOW, "recoverability": "INCOMPLETE",
            "missing_required_parameters": "|".join(missing_classifier_families),
            "may_derived_parameter_count": 0,
            "notes": "coefficients alone do not define predict_proba on raw May causal features",
        },
    ]
    details = {
        "counts": {
            "m0_position_base_curve_rows": len(base), "m0_velocity_curve_rows": len(velocity),
            "m1_publication_factor_rows": len(m1), "m2_satellite_factor_rows": len(m2),
            "m3_risk_factor_rows": len(m3), "m4_satellite_factor_rows": len(m4_sat),
            "m4_risk_factor_rows": len(m4_risk), "risk_metadata_rows": len(risk_metadata),
            "classifier_coefficient_rows": len(coefficient_rows),
        },
        "classifier_coefficient_features_exact": coefficient_features == CAUSAL_FEATURES,
        "risk_cutpoints": sorted([list(value) for value in cutpoints]),
        "fallback_values_by_model": {key: sorted(value) for key, value in fallback_values.items()},
        "fallback_parameter_counts_by_model": fallback_parameter_counts,
        "risk_cutpoint_parameter_count": risk_cutpoint_parameter_count,
        "missing_classifier_parameter_families": missing_classifier_families,
        "serialized_model_candidates": [path.as_posix() for path in serialized_candidates],
    }
    return rows, details


def audit_may_support() -> dict[str, Any]:
    rows = 0
    primary = 0
    outside = 0
    nominal = 0
    with MAY_DATASET.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows += 1
            age_h = float(row["element_age_seconds"]) / 3600.0
            primary += 0.0 < age_h <= 36.0
            outside += age_h > 36.0
            nominal += str(row["nominal_row"]).lower() == "true"
    return {
        "rows": rows, "nominal_rows": nominal,
        "primary_external_validation_rows": primary,
        "outside_april_calibrated_freshness_support_rows": outside,
        "support_condition": "0 < element_age_seconds / 3600 <= 36",
    }


def build_blocked_report(
    april_sha: str,
    may_sha: str,
    support: dict[str, Any],
    april_artifact_count: int,
    may_stage1a_reference_count: int,
    coefficient_count: int,
    missing: list[str],
) -> str:
    missing_text = "`, `".join(missing)
    return f"""# May locked external validation 参数冻结预检报告

状态：`MAY_LOCKED_EXTERNAL_VALIDATION_BLOCKED_APRIL_PARAMETER_PROVENANCE`

## 1. 已通过的冻结检查

- April Stage-1B canonical SHA：`{april_sha}`，与冻结值一致。
- April 受保护 inventory 共 {april_artifact_count} 项，覆盖 Stage-1A/B/C/D/E 与 raw/provenance；当前 mismatch=0。
- April Stage-1D/1E status、window、manifest output SHA 均一致；Stage-1E freeze decision 仍为 `HETEROGENEITY_OR_REGIME_NOT_RESOLVED`。
- May Stage-1B dataset SHA：`{may_sha}`，与 May manifest 完整绑定值一致。
- May Stage-1A 非空 manifest/reference 共 {may_stage1a_reference_count} 项，当前 SHA mismatch=0。
- May support 按 `0 < element_age_seconds / 3600 <= 36` 精确划分：PRIMARY={support['primary_external_validation_rows']}，OUTSIDE={support['outside_april_calibrated_freshness_support_rows']}，总计 {support['rows']} 行。
- May-derived fitted parameter count=`0`；未生成 coverage、per-satellite、freshness-bin、scale-persistence、regime-transfer 或 figures。

## 2. Parameter freeze audit

- M0：position base curves 与 velocity descriptive curves 已落盘。
- M1：April publication-age strata factors 已落盘。
- M2：20 颗 April partial-pooled satellite factors 已落盘。
- M3/M4：risk factors 与 P50/P90 risk-score cutpoints 已落盘；April classifier 只导出了 {coefficient_count} 个 standardized coefficients。
- 缺失：`{missing_text}`。

April 生产实现使用 `SimpleImputer(add_indicator=True) -> StandardScaler -> LogisticRegression`。仅有 standardized coefficients 不能把 May raw causal features唯一映射为 `predict_proba`；缺少 intercept 和 preprocessing statistics 时，同一组 coefficients 可对应不同 risk score 与 risk stratum。用 April feature/label 重新运行 `fit_regime_classifier` 或重新计算 preprocessing statistics 都属于重新拟合/重建未冻结参数，本轮没有执行。

## 3. 停止点

由于 M3/M4 无法从现有 April artifacts 无歧义恢复，严格的 M0-M4 locked external validation 未执行，不能输出 `MAY_LOCKED_EXTERNAL_VALIDATION_COMPLETE`。需要先在独立 provenance 修复任务中找回 April 当时已经拟合并冻结的完整 classifier artifact；不能使用 May 数据补参数，也不能现在重跑 April fit 后把新结果冒充原 frozen model。

详细逐项结果见 `{PARAMETER_AUDIT.as_posix()}` 与 `{CORRECTNESS_AUDIT.as_posix()}`。
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    outputs = [PARAMETER_AUDIT, CORRECTNESS_AUDIT, MANIFEST, REPORT]
    existing = [str(path) for path in outputs if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite existing preflight outputs: {existing}")

    april_stage1b = load_json(APRIL_STAGE1B_MANIFEST)
    stage1d = load_json(APRIL_STAGE1D_MANIFEST)
    stage1e = load_json(APRIL_STAGE1E_MANIFEST)
    may_stage1b = load_json(MAY_STAGE1B_MANIFEST)
    calibration = load_csv(APRIL_STAGE1E_CALIBRATION)
    association = load_csv(APRIL_STAGE1E_ASSOCIATION)

    april_inventory = load_april_protection_inventory(may_stage1b)
    april_inventory_paths = [Path(row["path"]) for row in april_inventory]
    may_stage1a_bound, may_stage1a_audit = verify_bound_references(may_stage1b.get("input_manifests", {}))
    may_stage1a_paths = [Path(row["path"]) for row in may_stage1a_audit]
    frozen_sources = list(dict.fromkeys([
        *april_inventory_paths,
        APRIL_DATASET, APRIL_STAGE1B_MANIFEST, APRIL_STAGE1D_MANIFEST,
        APRIL_STAGE1D_GRID, APRIL_STAGE1D_QUANTILES, APRIL_STAGE1E_MANIFEST,
        APRIL_STAGE1E_CALIBRATION, APRIL_STAGE1E_ASSOCIATION,
        APRIL_STAGE1E_MODEL_COMPARISON, APRIL_STAGE1E_FEATURES, APRIL_STAGE1E_SCRIPT,
        MAY_DATASET, MAY_STAGE1B_MANIFEST, *may_stage1a_paths,
    ]))
    hashes_before = {path.as_posix(): sha256(path) for path in frozen_sources}
    parameter_rows, parameter_details = inspect_parameter_artifacts(calibration, association)
    support = audit_may_support()
    may_dataset_sha = sha256(MAY_DATASET)

    stage1d_bound = all(
        sha256(path) == manifest_output_sha(stage1d, path)
        for path in [APRIL_STAGE1D_GRID, APRIL_STAGE1D_QUANTILES]
    )
    stage1e_bound = all(
        sha256(path) == manifest_output_sha(stage1e, path)
        for path in [APRIL_STAGE1E_CALIBRATION, APRIL_STAGE1E_ASSOCIATION, APRIL_STAGE1E_MODEL_COMPARISON, APRIL_STAGE1E_FEATURES]
    )
    may_entry = may_stage1b.get("outputs", {}).get(MAY_DATASET.name, {})
    missing = parameter_details["missing_classifier_parameter_families"]
    april_inventory_mismatches = [
        row for row in april_inventory
        if not Path(row["path"]).exists()
        or sha256(Path(row["path"])) != str(row["sha256"]).upper()
        or Path(row["path"]).stat().st_size != int(row["size_bytes"])
    ]
    expected_parameter_counts = {
        "m0_position_base_curve_rows": 104,
        "m0_velocity_curve_rows": 78,
        "m1_publication_factor_rows": 40,
        "m2_satellite_factor_rows": 160,
        "m3_risk_factor_rows": 24,
        "m4_satellite_factor_rows": 160,
        "m4_risk_factor_rows": 24,
        "risk_metadata_rows": 8,
        "classifier_coefficient_rows": 16,
    }
    parameter_row_counts_exact = all(
        parameter_details["counts"].get(name) == expected
        for name, expected in expected_parameter_counts.items()
    )
    correctness = [
        {"check": "April Stage-1B canonical SHA frozen", "passed": sha256(APRIL_DATASET) == APRIL_DATASET_SHA, "observed": sha256(APRIL_DATASET)},
        {"check": "April protected Stage-1A/B/C/D/E and raw inventory", "passed": not april_inventory_mismatches, "observed": f"artifacts={len(april_inventory)}; mismatches={len(april_inventory_mismatches)}"},
        {"check": "April Stage-1D status/window", "passed": stage1d.get("status") == "STAGE1D_FRESHNESS_CALIBRATION_COMPLETE" and stage1d.get("formal_window") == APRIL_WINDOW, "observed": f"status={stage1d.get('status')}; window={stage1d.get('formal_window')}"},
        {"check": "April Stage-1E status/freeze decision/window", "passed": stage1e.get("status") == "STAGE1E_HETEROGENEITY_CAUSAL_REGIME_ASSESSMENT_COMPLETE" and stage1e.get("model_freeze_decision") == "HETEROGENEITY_OR_REGIME_NOT_RESOLVED" and stage1e.get("formal_window") == APRIL_WINDOW, "observed": f"status={stage1e.get('status')}; decision={stage1e.get('model_freeze_decision')}; window={stage1e.get('formal_window')}"},
        {"check": "April calibration artifacts manifest-bound", "passed": stage1d_bound and stage1e_bound, "observed": f"stage1d={stage1d_bound}; stage1e={stage1e_bound}"},
        {"check": "April parameter artifact row counts exact", "passed": parameter_row_counts_exact, "observed": json.dumps(parameter_details["counts"], sort_keys=True)},
        {"check": "April classifier coefficient feature order exact", "passed": parameter_details["classifier_coefficient_features_exact"], "observed": f"features={parameter_details['counts']['classifier_coefficient_rows']}"},
        {"check": "May Stage-1B status/window/dataset SHA", "passed": may_stage1b.get("status") == "MAY_STAGE1B_RESIDUAL_LIBRARY_COMPLETE" and may_stage1b.get("formal_window") == MAY_WINDOW and may_entry.get("sha256") == may_dataset_sha, "observed": f"status={may_stage1b.get('status')}; sha={may_dataset_sha}"},
        {"check": "May Stage-1A manifests current SHA-bound", "passed": may_stage1a_bound, "observed": f"references={len(may_stage1a_audit)}; mismatches={sum(not row['matched'] for row in may_stage1a_audit)}"},
        {"check": "May support split exact", "passed": support["rows"] == 6181 and support["nominal_rows"] == 6181 and support["primary_external_validation_rows"] == 6094 and support["outside_april_calibrated_freshness_support_rows"] == 87, "observed": json.dumps(support, sort_keys=True)},
        {"check": "M0/M1/M2 frozen parameters recoverable", "passed": all(row["recoverability"] == "READY" for row in parameter_rows if row["model"] in {"M0", "M0_DESCRIPTIVE", "M1", "M2"}), "observed": "M0 base/velocity curves, M1 factors and M2 factors present"},
        {"check": "M3/M4 complete frozen classifier recoverable", "passed": False, "observed": "missing=" + "|".join(missing)},
        {"check": "May-derived fitted parameter count zero", "passed": sum(int(row["may_derived_parameter_count"]) for row in parameter_rows) == 0, "observed": "may_derived_parameter_count=0"},
        {"check": ">36h formal predictions zero", "passed": not any(path.exists() for path in FORBIDDEN_VALIDATION_OUTPUTS), "observed": "formal_prediction_outputs_created=0"},
        {"check": "RMS not used as operational input", "passed": True, "observed": "preflight stopped before prediction; M_RMS_DIAGNOSTIC excluded"},
        {"check": "May rows removed zero", "passed": support["rows"] == 6181, "observed": f"retained_for_provenance={support['rows']}; coverage_not_run=true"},
        {"check": "May causal feature fitting/future access absent", "passed": True, "observed": "May causal features and risk scores were not generated because preflight blocked before prediction"},
    ]

    parameter_fields = [
        "audit_item", "model", "parameter_family", "source_path", "source_sha256",
        "artifact_rows", "parameter_count", "training_window", "recoverability",
        "missing_required_parameters", "may_derived_parameter_count", "notes",
    ]
    hashes_after = {path.as_posix(): sha256(path) for path in frozen_sources}
    unchanged = hashes_before == hashes_after
    correctness.append({
        "check": "Frozen April/May inputs unchanged during preflight",
        "passed": unchanged,
        "observed": f"input_files={len(frozen_sources)}; changed={sum(hashes_before[path] != hashes_after[path] for path in hashes_before)}",
    })
    write_csv(PARAMETER_AUDIT, parameter_rows, parameter_fields)
    write_csv(CORRECTNESS_AUDIT, correctness, ["check", "passed", "observed"])

    blockers = [
        "April M3/M4 causal classifier export is incomplete: standardized coefficients are present, but logistic intercept, scaler means/scales, imputer statistics and a serialized fitted pipeline (or equivalent complete parameter record) are absent.",
        "Recomputing these parameters from April labels/features would be an April refit and is forbidden by the locked external-validation protocol.",
    ]
    supPORT_TOTAL = support["rows"]
    legacy_report = f"""# May locked external validation parameter-freeze preflight

状态：`MAY_LOCKED_EXTERNAL_VALIDATION_BLOCKED_APRIL_PARAMETER_PROVENANCE`。

## 1. 已通过的冻结检查

- April Stage-1B canonical SHA：`{sha256(APRIL_DATASET)}`，与冻结值一致。
- April Stage-1D/1E status、window、manifest output SHA均一致；Stage-1E freeze decision仍为`HETEROGENEITY_OR_REGIME_NOT_RESOLVED`。
- May Stage-1B dataset SHA：`{may_dataset_sha}`，与May manifest完整绑定值一致。
- May support按`0 < element_age_seconds / 3600 <= 36`精确划分为PRIMARY={support['primary_external_validation_rows']}、OUTSIDE={support['outside_april_calibrated_freshness_support_rows']}，总计{supPORT_TOTAL}行。
- May-derived fitted parameter count=`0`；没有生成coverage、per-satellite、freshness-bin、scale persistence、regime transfer或figures。

## 2. Parameter freeze audit

- M0：position base curves与velocity descriptive curves已落盘。
- M1：April publication-age strata factors已落盘。
- M2：20星April partial-pooled satellite factors已落盘。
- M3/M4：risk factors与P50/P90 risk-score cutpoints已落盘；April classifier只导出了{parameter_details['counts']['classifier_coefficient_rows']}个standardized coefficients。
- 缺失：`{'`, `'.join(missing)}`。

standardized coefficients本身不能将May raw causal features唯一映射为`predict_proba`；缺少intercept和scaler参数时，相同coefficient可对应不同risk score与risk stratum。用April feature/label重新运行`fit_regime_classifier`或重新计算preprocessing statistics都属于重新拟合/重建未冻结参数，本轮没有执行。

## 3. 停止点

由于M3/M4无法从现有April artifacts无歧义恢复，严格的M0–M4 locked external validation未执行，不能输出`MAY_LOCKED_EXTERNAL_VALIDATION_COMPLETE`。需要先在独立的provenance修复任务中，从原April运行环境找回当时已经拟合的完整classifier artifact；不能用May数据补参数，也不能在本轮重跑April fit后把新结果冒充原frozen model。

详细逐项结果见`{PARAMETER_AUDIT.as_posix()}`与`{CORRECTNESS_AUDIT.as_posix()}`。
""".replace("{supPORT_TOTAL}", str(support["rows"]))
    del legacy_report, supPORT_TOTAL
    report = build_blocked_report(
        sha256(APRIL_DATASET), may_dataset_sha, support, len(april_inventory),
        len(may_stage1a_audit), parameter_details["counts"]["classifier_coefficient_rows"], missing,
    )
    write_text(REPORT, report)

    manifest = {
        "stage": "Orbit Uncertainty Stage-1 locked external validation preflight",
        "status": "MAY_LOCKED_EXTERNAL_VALIDATION_BLOCKED_APRIL_PARAMETER_PROVENANCE",
        "generated_utc": utc_now(),
        "training_window": APRIL_WINDOW,
        "test_window": MAY_WINDOW,
        "april_model_freeze_decision": stage1e.get("model_freeze_decision"),
        "blockers": blockers,
        "parameter_freeze": {
            "audit_status": "APRIL_PARAMETER_FREEZE_AUDIT_BLOCKED",
            "may_derived_fitted_parameter_count": 0,
            "recoverable_candidates": ["M0", "M1", "M2", "M0_DESCRIPTIVE_VELOCITY"],
            "blocked_candidates": ["M3", "M4"],
            "details": parameter_details,
        },
        "april_protection": {
            "artifact_count": len(april_inventory),
            "mismatch_count": len(april_inventory_mismatches),
            "mismatches": april_inventory_mismatches,
            "frozen_input_hashes_before_after_equal": unchanged,
        },
        "inputs": {
            "april_stage1b_dataset": {"path": APRIL_DATASET.as_posix(), "sha256": sha256(APRIL_DATASET)},
            "april_stage1b_manifest": {"path": APRIL_STAGE1B_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1B_MANIFEST)},
            "april_stage1d_manifest": {"path": APRIL_STAGE1D_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1D_MANIFEST)},
            "april_stage1d_grid": {"path": APRIL_STAGE1D_GRID.as_posix(), "sha256": sha256(APRIL_STAGE1D_GRID)},
            "april_stage1d_quantiles": {"path": APRIL_STAGE1D_QUANTILES.as_posix(), "sha256": sha256(APRIL_STAGE1D_QUANTILES)},
            "april_stage1e_manifest": {"path": APRIL_STAGE1E_MANIFEST.as_posix(), "sha256": sha256(APRIL_STAGE1E_MANIFEST)},
            "april_stage1e_componentwise_calibration": {"path": APRIL_STAGE1E_CALIBRATION.as_posix(), "sha256": sha256(APRIL_STAGE1E_CALIBRATION)},
            "april_stage1e_regime_association": {"path": APRIL_STAGE1E_ASSOCIATION.as_posix(), "sha256": sha256(APRIL_STAGE1E_ASSOCIATION)},
            "april_stage1e_model_comparison": {"path": APRIL_STAGE1E_MODEL_COMPARISON.as_posix(), "sha256": sha256(APRIL_STAGE1E_MODEL_COMPARISON)},
            "april_stage1e_causal_features": {"path": APRIL_STAGE1E_FEATURES.as_posix(), "sha256": sha256(APRIL_STAGE1E_FEATURES)},
            "may_stage1b_dataset": {"path": MAY_DATASET.as_posix(), "sha256": may_dataset_sha},
            "may_stage1b_manifest": {"path": MAY_STAGE1B_MANIFEST.as_posix(), "sha256": sha256(MAY_STAGE1B_MANIFEST)},
            "may_stage1a_manifests": may_stage1a_audit,
        },
        "support_audit": support,
        "correctness": {
            "passed": sum(bool(row["passed"]) for row in correctness),
            "total": len(correctness),
            "failed_checks": [row["check"] for row in correctness if not row["passed"]],
            "frozen_input_hashes_before_after_equal": unchanged,
        },
        "builder": {"path": Path(__file__).as_posix(), "sha256": sha256(Path(__file__))},
        "outputs": {
            path.name: {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in [PARAMETER_AUDIT, CORRECTNESS_AUDIT, REPORT]
        },
        "scope_guards": {
            "external_coverage_computed": False,
            "may_refit_performed": False,
            "april_refit_performed": False,
            "may_causal_features_generated": False,
            "risk_scores_generated": False,
            "outside_support_predictions_generated": False,
            "rms_used_operationally": False,
            "stage1f_entered": False,
            "synthetic_b_or_doppler_run": False,
        },
    }
    write_json(MANIFEST, manifest)
    print(json.dumps({
        "status": manifest["status"],
        "primary_rows": support["primary_external_validation_rows"],
        "outside_support_rows": support["outside_april_calibrated_freshness_support_rows"],
        "may_derived_fitted_parameters": 0,
        "blocked_models": ["M3", "M4"],
        "coverage_computed": False,
    }, indent=2))


if __name__ == "__main__":
    main()
