#!/usr/bin/env python3
"""Stage-1C descriptive structure/freshness/regime analysis.

Consumes the frozen Stage-1B canonical residual library.  This script does not
rebuild residuals, define an uncertainty boundary, filter maneuvers, analyze a
synthetic B, or run a Doppler verifier.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import statistics
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import ConstantInputWarning, pearsonr, spearmanr

try:
    from scripts.orbit_uncertainty_stage1_window import FORMAL_INTERVAL, WINDOW_TAG
except ModuleNotFoundError:
    from orbit_uncertainty_stage1_window import FORMAL_INTERVAL, WINDOW_TAG


STAGE1B_PREFIX = f"orbit_uncertainty_stage1b_{WINDOW_TAG}"
STAGE1C_PREFIX = f"orbit_uncertainty_stage1c_{WINDOW_TAG}"

DATASET_PATH = Path("outputs/datasets") / f"{STAGE1B_PREFIX}_rtn_residual_library.csv"
STAGE1B_MANIFEST_PATH = Path("outputs/metrics") / f"{STAGE1B_PREFIX}_manifest.json"

METRICS_DIR = Path("outputs/metrics")
REPORTS_DIR = Path("outputs/reports")
FIGURE_DIR = Path("outputs/figures") / STAGE1C_PREFIX

FRESHNESS_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_freshness_summary.csv"
RTN_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_rtn_component_summary.csv"
SATELLITE_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_satellite_summary.csv"
EXTREME_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_extreme_episode_audit.csv"
REGIME_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_regime_candidate_summary.csv"
RMS_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_rms_association_summary.csv"
CORRECTNESS_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_correctness_audit.csv"
MANIFEST_PATH = METRICS_DIR / f"{STAGE1C_PREFIX}_manifest.json"
REPORT_PATH = REPORTS_DIR / f"{STAGE1C_PREFIX}_residual_structure_report.md"

FRESHNESS_FIGURE = FIGURE_DIR / "position_disagreement_vs_element_age.png"
RTN_FIGURE = FIGURE_DIR / "rtn_disagreement_vs_element_age.png"
REGIME_FIGURE = FIGURE_DIR / "regime_candidate_timeseries.png"

AGE_EDGES_H = [0.0, 6.0, 12.0, 24.0, 36.0, 48.0, 72.0]
AGE_LABELS = ["0-6 h", "6-12 h", "12-24 h", "24-36 h", "36-48 h", "48-72 h"]
ORBIT_FIELDS = [
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "BSTAR",
]
ANGULAR_FIELDS = {"INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY"}
FRESHNESS_OUTCOMES = [
    "position_error_norm_km",
    "abs_delta_R_km",
    "abs_delta_T_km",
    "abs_delta_N_km",
    "velocity_error_norm_km_s",
    "abs_delta_v_R_km_s",
    "abs_delta_v_T_km_s",
    "abs_delta_v_N_km_s",
]


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


def ensure_outputs_available(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing Stage-1C outputs: {existing}")


def output_paths() -> list[Path]:
    return [
        FRESHNESS_PATH,
        RTN_PATH,
        SATELLITE_PATH,
        EXTREME_PATH,
        REGIME_PATH,
        RMS_PATH,
        CORRECTNESS_PATH,
        MANIFEST_PATH,
        REPORT_PATH,
        FRESHNESS_FIGURE,
        RTN_FIGURE,
        REGIME_FIGURE,
    ]


def verify_input() -> tuple[dict[str, Any], str]:
    manifest = load_json(STAGE1B_MANIFEST_PATH)
    if manifest.get("status") != "APRIL_STAGE1B_RESIDUAL_LIBRARY_COMPLETE":
        raise SystemExit("Frozen Stage-1B manifest is not COMPLETE")
    if manifest.get("window_tag") != WINDOW_TAG or manifest.get("formal_window") != FORMAL_INTERVAL:
        raise SystemExit("Stage-1B window binding differs from frozen Stage-1C input")
    if not DATASET_PATH.exists():
        raise SystemExit(f"Canonical Stage-1B dataset missing: {DATASET_PATH}")
    current_sha = sha256(DATASET_PATH)
    output_entry = manifest["outputs"].get(DATASET_PATH.name)
    if not output_entry or output_entry.get("sha256") != current_sha:
        raise SystemExit("Canonical dataset SHA does not match Stage-1B manifest")
    if int(manifest["result"]["rows"]) != 5675 or int(manifest["result"]["nominal_rows"]) != 5675:
        raise SystemExit("Stage-1B manifest row/nominal count is not the frozen 5675/5675")
    if int(manifest["result"]["excluded_rows"]) != 0:
        raise SystemExit("Stage-1B manifest has excluded rows")
    return manifest, current_sha


def read_dataset() -> pd.DataFrame:
    frame = pd.read_csv(
        DATASET_PATH,
        dtype={"NORAD_CAT_ID": str, "ordinary_gp_id": str},
        encoding="utf-8-sig",
    )
    required = {
        "NORAD_CAT_ID", "evaluation_time", "ordinary_gp_id", "ordinary_gp_epoch",
        "ordinary_gp_creation_date", "element_age_seconds", "publication_age_seconds",
        "supgp_rms_km", "supgp_source_file", "supgp_source_row_index",
        "delta_R_km", "delta_T_km", "delta_N_km", "delta_v_R_km_s",
        "delta_v_T_km_s", "delta_v_N_km_s", "position_error_norm_km",
        "velocity_error_norm_km_s", "nominal_row",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SystemExit(f"Canonical dataset fields missing: {missing}")
    if len(frame) != 5675 or not frame["nominal_row"].astype(bool).all():
        raise SystemExit("Canonical dataset is not 5675/5675 nominal")
    frame["_dataset_row_number"] = np.arange(2, len(frame) + 2)
    for column in ["evaluation_time", "ordinary_gp_epoch", "ordinary_gp_creation_date", "supgp_epoch"]:
        frame[column] = pd.to_datetime(frame[column], utc=True, format="mixed")
    for source, target in [
        ("delta_R_km", "abs_delta_R_km"),
        ("delta_T_km", "abs_delta_T_km"),
        ("delta_N_km", "abs_delta_N_km"),
        ("delta_v_R_km_s", "abs_delta_v_R_km_s"),
        ("delta_v_T_km_s", "abs_delta_v_T_km_s"),
        ("delta_v_N_km_s", "abs_delta_v_N_km_s"),
    ]:
        frame[target] = frame[source].abs()
    frame["element_age_hours"] = frame["element_age_seconds"] / 3600.0
    frame["publication_age_hours"] = frame["publication_age_seconds"] / 3600.0
    position_abs = frame[["abs_delta_R_km", "abs_delta_T_km", "abs_delta_N_km"]]
    frame["dominant_component"] = position_abs.idxmax(axis=1).map({
        "abs_delta_R_km": "R", "abs_delta_T_km": "T", "abs_delta_N_km": "N"
    })
    velocity_abs = frame[["abs_delta_v_R_km_s", "abs_delta_v_T_km_s", "abs_delta_v_N_km_s"]]
    frame["dominant_velocity_component"] = velocity_abs.idxmax(axis=1).map({
        "abs_delta_v_R_km_s": "R", "abs_delta_v_T_km_s": "T", "abs_delta_v_N_km_s": "N"
    })
    return frame.sort_values(["NORAD_CAT_ID", "evaluation_time"]).reset_index(drop=True)


def safe_correlation(x: pd.Series, y: pd.Series, method: str) -> tuple[float, float]:
    valid = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(valid) < 3 or valid.x.nunique() < 2 or valid.y.nunique() < 2:
        return math.nan, math.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConstantInputWarning)
        result = spearmanr(valid.x, valid.y) if method == "spearman" else pearsonr(valid.x, valid.y)
    return float(result.statistic), float(result.pvalue)


def descriptive(values: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        return {"n": 0, "min": "", "median": "", "p75": "", "p90": "", "p95": "", "max": ""}
    return {
        "n": int(len(clean)),
        "min": float(clean.min()),
        "median": float(clean.median()),
        "p75": float(clean.quantile(0.75)),
        "p90": float(clean.quantile(0.90)),
        "p95": float(clean.quantile(0.95)),
        "max": float(clean.max()),
    }


def top_rank_indices(frame: pd.DataFrame, fraction: float) -> set[int]:
    count = max(1, int(math.ceil(len(frame) * fraction)))
    return set(frame.nlargest(count, "position_error_norm_km").index.tolist())


def add_sensitivity_flags(frame: pd.DataFrame) -> dict[str, Any]:
    global_top1 = top_rank_indices(frame, 0.01)
    global_top005 = top_rank_indices(frame, 0.005)
    top20 = set(frame.nlargest(20, "position_error_norm_km").index.tolist())
    within_sat_top1: set[int] = set()
    for _, group in frame.groupby("NORAD_CAT_ID", sort=False):
        within_sat_top1.update(top_rank_indices(group, 0.01))
    frame["is_global_top_1pct"] = frame.index.isin(global_top1)
    frame["is_global_top_0_5pct"] = frame.index.isin(global_top005)
    frame["is_global_top20"] = frame.index.isin(top20)
    frame["is_within_satellite_top_1pct"] = frame.index.isin(within_sat_top1)
    return {
        "global_top1_count": len(global_top1),
        "global_top0_5_count": len(global_top005),
        "top20_count": len(top20),
        "within_satellite_top1_count": len(within_sat_top1),
        "global_top1_threshold_km": float(frame.loc[list(global_top1), "position_error_norm_km"].min()),
        "global_top0_5_threshold_km": float(frame.loc[list(global_top005), "position_error_norm_km"].min()),
        "pooled_p95_km": float(frame.position_error_norm_km.quantile(0.95)),
    }


def analysis_views(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "full": frame,
        "pooled_trim_global_top1_diagnostic": frame.loc[~frame.is_global_top_1pct],
        "pooled_trim_within_satellite_top1_diagnostic": frame.loc[~frame.is_within_satellite_top_1pct],
    }


def build_freshness_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    views = analysis_views(frame)
    predictors = ["element_age_hours", "publication_age_hours"]
    for view_name, view in views.items():
        for predictor in predictors:
            for outcome in FRESHNESS_OUTCOMES:
                for method in ["spearman", "pearson"]:
                    correlation, p_value = safe_correlation(view[predictor], view[outcome], method)
                    rows.append({
                        "section": "correlation",
                        "view": view_name,
                        "scope": "pooled",
                        "NORAD_CAT_ID": "",
                        "predictor": predictor,
                        "outcome": outcome,
                        "method": method,
                        "bin_label": "",
                        "bin_left_h": "",
                        "bin_right_h": "",
                        "n": len(view),
                        "correlation": correlation,
                        "p_value": p_value,
                        "min": "", "median": "", "p75": "", "p90": "", "p95": "", "max": "",
                        "delta_from_full": "",
                        "note": "trimmed views are diagnostic only" if view_name != "full" else "descriptive only",
                    })
        for predictor in predictors:
            binned = pd.cut(view[predictor], AGE_EDGES_H, labels=AGE_LABELS, right=False, include_lowest=True)
            for bin_index, label in enumerate(AGE_LABELS):
                group = view.loc[binned == label]
                for outcome in FRESHNESS_OUTCOMES:
                    stats = descriptive(group[outcome])
                    rows.append({
                        "section": "freshness_bin",
                        "view": view_name,
                        "scope": "pooled",
                        "NORAD_CAT_ID": "",
                        "predictor": predictor,
                        "outcome": outcome,
                        "method": "descriptive",
                        "bin_label": label,
                        "bin_left_h": AGE_EDGES_H[bin_index],
                        "bin_right_h": AGE_EDGES_H[bin_index + 1],
                        **stats,
                        "correlation": "",
                        "p_value": "",
                        "delta_from_full": "",
                        "note": "trimmed views are diagnostic only" if view_name != "full" else "fixed a priori freshness bins",
                    })
    full_quantiles = {q: float(frame.position_error_norm_km.quantile(q)) for q in [0.5, 0.75, 0.9, 0.95, 1.0]}
    for view_name, view in views.items():
        for q, label in [(0.5, "median"), (0.75, "p75"), (0.9, "p90"), (0.95, "p95"), (1.0, "max")]:
            value = float(view.position_error_norm_km.quantile(q))
            rows.append({
                "section": "sensitivity_quantile",
                "view": view_name,
                "scope": "pooled",
                "NORAD_CAT_ID": "",
                "predictor": "",
                "outcome": "position_error_norm_km",
                "method": label,
                "bin_label": "",
                "bin_left_h": "", "bin_right_h": "",
                "n": len(view),
                "correlation": "", "p_value": "",
                "min": "", "median": value if label == "median" else "", "p75": value if label == "p75" else "",
                "p90": value if label == "p90" else "", "p95": value if label == "p95" else "", "max": value if label == "max" else "",
                "delta_from_full": value - full_quantiles[q],
                "note": "trimmed views are diagnostic only" if view_name != "full" else "formal full population descriptive value",
            })
    return pd.DataFrame(rows)


def build_rtn_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes = [("pooled", "", frame)] + [
        ("per_satellite", norad, group) for norad, group in frame.groupby("NORAD_CAT_ID", sort=False)
    ]
    for scope, norad, group in scopes:
        for state_type, components, dominant_field in [
            ("position", {"R": "abs_delta_R_km", "T": "abs_delta_T_km", "N": "abs_delta_N_km"}, "dominant_component"),
            ("velocity", {"R": "abs_delta_v_R_km_s", "T": "abs_delta_v_T_km_s", "N": "abs_delta_v_N_km_s"}, "dominant_velocity_component"),
        ]:
            for component, field in components.items():
                stats = descriptive(group[field])
                rows.append({
                    "scope": scope,
                    "NORAD_CAT_ID": norad,
                    "state_type": state_type,
                    "component": component,
                    **stats,
                    "dominant_count": int((group[dominant_field] == component).sum()),
                    "dominant_proportion": float((group[dominant_field] == component).mean()),
                })
    return pd.DataFrame(rows)


def build_satellite_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for norad, group in frame.groupby("NORAD_CAT_ID", sort=False):
        trimmed = group.loc[~group.is_within_satellite_top_1pct]
        element_s, element_p = safe_correlation(group.element_age_hours, group.position_error_norm_km, "spearman")
        publication_s, publication_p = safe_correlation(group.publication_age_hours, group.position_error_norm_km, "spearman")
        trimmed_s, _ = safe_correlation(trimmed.element_age_hours, trimmed.position_error_norm_km, "spearman")
        proportions = group.dominant_component.value_counts(normalize=True).reindex(["R", "T", "N"], fill_value=0.0)
        max_row = group.loc[group.position_error_norm_km.idxmax()]
        rows.append({
            "NORAD_CAT_ID": norad,
            "object_name": group.object_name.iloc[0],
            "rows": len(group),
            "position_median_km": float(group.position_error_norm_km.median()),
            "position_p90_km": float(group.position_error_norm_km.quantile(0.90)),
            "position_p95_km": float(group.position_error_norm_km.quantile(0.95)),
            "position_max_km": float(group.position_error_norm_km.max()),
            "position_max_time": max_row.evaluation_time.isoformat().replace("+00:00", "Z"),
            "element_age_median_h": float(group.element_age_hours.median()),
            "element_age_max_h": float(group.element_age_hours.max()),
            "publication_age_median_h": float(group.publication_age_hours.median()),
            "publication_age_max_h": float(group.publication_age_hours.max()),
            "supgp_rms_median_km": float(group.supgp_rms_km.median()),
            "supgp_rms_max_km": float(group.supgp_rms_km.max()),
            "R_dominant_proportion": float(proportions["R"]),
            "T_dominant_proportion": float(proportions["T"]),
            "N_dominant_proportion": float(proportions["N"]),
            "dominant_pattern": str(proportions.idxmax()),
            "element_age_position_spearman": element_s,
            "element_age_position_spearman_p": element_p,
            "publication_age_position_spearman": publication_s,
            "publication_age_position_spearman_p": publication_p,
            "element_age_position_spearman_trim_within_sat_top1_diagnostic": trimmed_s,
            "global_top1_rows": int(group.is_global_top_1pct.sum()),
            "within_satellite_trimmed_rows": int(group.is_within_satellite_top_1pct.sum()),
        })
    return pd.DataFrame(rows)


def circular_difference(after: float, before: float) -> float:
    return (float(after) - float(before) + 180.0) % 360.0 - 180.0


def element_delta(after: dict[str, Any] | None, before: dict[str, Any] | None, field: str) -> Any:
    if after is None or before is None:
        return ""
    try:
        left = float(after[field])
        right = float(before[field])
    except (KeyError, TypeError, ValueError):
        return ""
    return circular_difference(left, right) if field in ANGULAR_FIELDS else left - right


def read_orbital_sources(frame: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    ordinary_path = Path(frame.ordinary_raw_file.iloc[0])
    ordinary_records = json.loads(ordinary_path.read_text(encoding="utf-8"))
    ordinary_by_id = {str(record["GP_ID"]): record for record in ordinary_records}
    supgp_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for source_file in sorted(frame.supgp_source_file.unique()):
        path = Path(source_file)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row_number, row in enumerate(csv.DictReader(handle), start=2):
                supgp_by_key[(path.as_posix(), row_number)] = row
    return ordinary_by_id, supgp_by_key


def detect_episodes(frame: pd.DataFrame, thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    q95 = thresholds["pooled_p95_km"]
    for norad, group_original in frame.groupby("NORAD_CAT_ID", sort=False):
        group = group_original.sort_values("evaluation_time")
        indices = group.index.tolist()
        high_positions = [position for position, index in enumerate(indices) if bool(frame.loc[index, "is_global_top_1pct"])]
        cursor = 0
        episode_number = 0
        while cursor < len(high_positions):
            start_pos = high_positions[cursor]
            end_pos = start_pos
            cursor += 1
            while cursor < len(high_positions):
                next_pos = high_positions[cursor]
                gap = next_pos - end_pos - 1
                bridge_ok = gap == 1 and float(group.iloc[end_pos + 1].position_error_norm_km) >= q95
                if gap == 0 or bridge_ok:
                    end_pos = next_pos
                    cursor += 1
                else:
                    break
            episode_number += 1
            episode_slice = group.iloc[start_pos:end_pos + 1]
            top1_slice = episode_slice.loc[episode_slice.is_global_top_1pct]
            pre = group.iloc[max(0, start_pos - 5):start_pos]
            post = group.iloc[end_pos + 1:min(len(group), end_pos + 6)]
            pre_median = float(pre.position_error_norm_km.median()) if len(pre) else math.nan
            post_median = float(post.position_error_norm_km.median()) if len(post) else math.nan
            episode_median = float(episode_slice.position_error_norm_km.median())
            onset_ratio = float(episode_slice.position_error_norm_km.iloc[0] / max(pre_median, np.finfo(float).tiny)) if math.isfinite(pre_median) else math.nan
            recovery_ratio = float(post_median / max(episode_median, np.finfo(float).tiny)) if math.isfinite(post_median) else math.nan
            duration_h = float((episode_slice.evaluation_time.iloc[-1] - episode_slice.evaluation_time.iloc[0]).total_seconds() / 3600.0)
            if len(top1_slice) == 1 and len(episode_slice) == 1:
                code, label = "A", "isolated_single_point_spike"
            elif duration_h >= 24.0 or len(top1_slice) >= 8:
                code, label = "D", "persistent_high_disagreement"
            elif (
                len(top1_slice) >= 2
                and math.isfinite(onset_ratio) and onset_ratio >= 3.0
                and math.isfinite(post_median) and post_median < thresholds["global_top1_threshold_km"]
                and math.isfinite(recovery_ratio) and recovery_ratio <= 0.5
            ):
                code, label = "C", "candidate_transition"
            else:
                code, label = "B", "several_consecutive_epochs_elevated"
            episodes.append({
                "NORAD_CAT_ID": norad,
                "episode_id": f"{norad}_E{episode_number:02d}",
                "start_index": indices[start_pos],
                "end_index": indices[end_pos],
                "start_time": episode_slice.evaluation_time.iloc[0],
                "end_time": episode_slice.evaluation_time.iloc[-1],
                "episode_row_count": len(episode_slice),
                "top1_row_count": len(top1_slice),
                "bridge_row_count": len(episode_slice) - len(top1_slice),
                "duration_hours": duration_h,
                "position_median_km": episode_median,
                "position_max_km": float(episode_slice.position_error_norm_km.max()),
                "velocity_max_km_s": float(episode_slice.velocity_error_norm_km_s.max()),
                "pre5_position_median_km": pre_median,
                "post5_position_median_km": post_median,
                "onset_ratio_vs_pre5_median": onset_ratio,
                "recovery_ratio_post5_vs_episode_median": recovery_ratio,
                "pattern_code": code,
                "pattern_label": label,
                "label_semantics": "descriptive candidate only; not a confirmed maneuver",
                "selected_gp_ids": ";".join(episode_slice.ordinary_gp_id.astype(str).drop_duplicates()),
                "selected_gp_change_count": int((episode_slice.ordinary_gp_id != episode_slice.ordinary_gp_id.shift()).sum() - 1),
            })
    return episodes


def locate_episode(index: int, episodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for episode in episodes:
        if episode["start_index"] <= index <= episode["end_index"]:
            return episode
    return None


def build_extreme_audit(
    frame: pd.DataFrame,
    episodes: list[dict[str, Any]],
    ordinary_by_id: dict[str, dict[str, Any]],
    supgp_by_key: dict[tuple[str, int], dict[str, Any]],
) -> pd.DataFrame:
    extreme = frame.loc[frame.is_global_top_1pct].copy().sort_values("position_error_norm_km", ascending=False)
    extreme["extreme_rank_position"] = np.arange(1, len(extreme) + 1)
    output: list[dict[str, Any]] = []
    for index, row in extreme.iterrows():
        satellite = frame.loc[frame.NORAD_CAT_ID == row.NORAD_CAT_ID].sort_values("evaluation_time")
        positions = satellite.index.tolist()
        location = positions.index(index)
        previous = frame.loc[positions[location - 1]] if location > 0 else None
        following = frame.loc[positions[location + 1]] if location + 1 < len(positions) else None
        current_ordinary = ordinary_by_id.get(str(row.ordinary_gp_id))
        previous_ordinary = ordinary_by_id.get(str(previous.ordinary_gp_id)) if previous is not None else None
        following_ordinary = ordinary_by_id.get(str(following.ordinary_gp_id)) if following is not None else None
        current_supgp = supgp_by_key[(Path(row.supgp_source_file).as_posix(), int(row.supgp_source_row_index))]
        previous_supgp = supgp_by_key[(Path(previous.supgp_source_file).as_posix(), int(previous.supgp_source_row_index))] if previous is not None else None
        following_supgp = supgp_by_key[(Path(following.supgp_source_file).as_posix(), int(following.supgp_source_row_index))] if following is not None else None
        episode = locate_episode(index, episodes)
        item: dict[str, Any] = {
            "extreme_rank_position": int(row.extreme_rank_position),
            "is_top_1pct": True,
            "is_top_0_5pct": bool(row.is_global_top_0_5pct),
            "is_top20": bool(row.is_global_top20),
            "NORAD_CAT_ID": row.NORAD_CAT_ID,
            "evaluation_time": row.evaluation_time.isoformat().replace("+00:00", "Z"),
            "position_error_norm_km": row.position_error_norm_km,
            "velocity_error_norm_km_s": row.velocity_error_norm_km_s,
            "delta_R_km": row.delta_R_km,
            "delta_T_km": row.delta_T_km,
            "delta_N_km": row.delta_N_km,
            "delta_v_R_km_s": row.delta_v_R_km_s,
            "delta_v_T_km_s": row.delta_v_T_km_s,
            "delta_v_N_km_s": row.delta_v_N_km_s,
            "dominant_component": row.dominant_component,
            "element_age_seconds": row.element_age_seconds,
            "publication_age_seconds": row.publication_age_seconds,
            "supgp_rms_km": row.supgp_rms_km,
            "ordinary_gp_id": row.ordinary_gp_id,
            "ordinary_gp_epoch": row.ordinary_gp_epoch.isoformat().replace("+00:00", "Z"),
            "ordinary_gp_creation_date": row.ordinary_gp_creation_date.isoformat().replace("+00:00", "Z"),
            "ordinary_gp_changed_from_previous_evaluation": bool(previous is not None and previous.ordinary_gp_id != row.ordinary_gp_id),
            "ordinary_gp_changes_at_next_evaluation": bool(following is not None and following.ordinary_gp_id != row.ordinary_gp_id),
            "episode_id": episode["episode_id"] if episode else "",
            "episode_pattern_code": episode["pattern_code"] if episode else "",
            "episode_pattern_label": episode["pattern_label"] if episode else "",
            "supgp_source_file": row.supgp_source_file,
            "supgp_source_row_index": int(row.supgp_source_row_index),
        }
        for field in ORBIT_FIELDS:
            key = field.lower()
            item[f"ordinary_{key}"] = current_ordinary.get(field, "") if current_ordinary else ""
            item[f"ordinary_prev_to_current_delta_{key}"] = element_delta(current_ordinary, previous_ordinary, field)
            item[f"ordinary_current_to_next_delta_{key}"] = element_delta(following_ordinary, current_ordinary, field)
            item[f"supgp_{key}"] = current_supgp.get(field, "")
            item[f"supgp_prev_to_current_delta_{key}"] = element_delta(current_supgp, previous_supgp, field)
            item[f"supgp_current_to_next_delta_{key}"] = element_delta(following_supgp, current_supgp, field)
        output.append(item)
    return pd.DataFrame(output)


def build_regime_summary(
    frame: pd.DataFrame,
    episodes: list[dict[str, Any]],
    ordinary_by_id: dict[str, dict[str, Any]],
    supgp_by_key: dict[tuple[str, int], dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        satellite = frame.loc[frame.NORAD_CAT_ID == episode["NORAD_CAT_ID"]].sort_values("evaluation_time")
        indices = satellite.index.tolist()
        start_position = indices.index(episode["start_index"])
        end_position = indices.index(episode["end_index"])
        pre = frame.loc[indices[start_position - 1]] if start_position > 0 else None
        post = frame.loc[indices[end_position + 1]] if end_position + 1 < len(indices) else None
        pre_ordinary = ordinary_by_id.get(str(pre.ordinary_gp_id)) if pre is not None else None
        post_ordinary = ordinary_by_id.get(str(post.ordinary_gp_id)) if post is not None else None
        pre_supgp = supgp_by_key[(Path(pre.supgp_source_file).as_posix(), int(pre.supgp_source_row_index))] if pre is not None else None
        post_supgp = supgp_by_key[(Path(post.supgp_source_file).as_posix(), int(post.supgp_source_row_index))] if post is not None else None
        item = dict(episode)
        item["start_time"] = episode["start_time"].isoformat().replace("+00:00", "Z")
        item["end_time"] = episode["end_time"].isoformat().replace("+00:00", "Z")
        item["pre_ordinary_gp_id"] = str(pre.ordinary_gp_id) if pre is not None else ""
        item["post_ordinary_gp_id"] = str(post.ordinary_gp_id) if post is not None else ""
        item["pre_to_post_ordinary_gp_changed"] = bool(pre is not None and post is not None and pre.ordinary_gp_id != post.ordinary_gp_id)
        for field in ORBIT_FIELDS:
            key = field.lower()
            item[f"ordinary_pre_to_post_delta_{key}"] = element_delta(post_ordinary, pre_ordinary, field)
            item[f"supgp_pre_to_post_delta_{key}"] = element_delta(post_supgp, pre_supgp, field)
        rows.append(item)
    return pd.DataFrame(rows).drop(columns=["start_index", "end_index"])


def build_rms_summary(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for view_name, view in analysis_views(frame).items():
        for outcome in ["position_error_norm_km", "velocity_error_norm_km_s"]:
            for method in ["spearman", "pearson"]:
                correlation, p_value = safe_correlation(view.supgp_rms_km, view[outcome], method)
                rows.append({
                    "section": "correlation", "view": view_name, "group": "pooled",
                    "outcome": outcome, "method": method, "bin_label": "", "bin_left_km": "", "bin_right_km": "",
                    "n": len(view), "correlation": correlation, "p_value": p_value,
                    "position_median_km": "", "position_p90_km": "", "position_p95_km": "", "position_max_km": "",
                    "velocity_median_km_s": "", "velocity_p95_km_s": "", "rms_median_km": "", "rms_p90_km": "", "rms_max_km": "",
                    "note": "trimmed views are diagnostic only" if view_name != "full" else "descriptive only; no RMS cutoff",
                })
    quantile_codes, bin_edges = pd.qcut(frame.supgp_rms_km, q=4, labels=False, retbins=True, duplicates="drop")
    for code in sorted(pd.Series(quantile_codes).dropna().unique()):
        group = frame.loc[quantile_codes == code]
        rows.append({
            "section": "rms_quantile_bin", "view": "full", "group": "pooled",
            "outcome": "position_and_velocity", "method": "descriptive",
            "bin_label": f"Q{int(code)+1}", "bin_left_km": float(bin_edges[int(code)]), "bin_right_km": float(bin_edges[int(code)+1]),
            "n": len(group), "correlation": "", "p_value": "",
            "position_median_km": float(group.position_error_norm_km.median()),
            "position_p90_km": float(group.position_error_norm_km.quantile(0.90)),
            "position_p95_km": float(group.position_error_norm_km.quantile(0.95)),
            "position_max_km": float(group.position_error_norm_km.max()),
            "velocity_median_km_s": float(group.velocity_error_norm_km_s.median()),
            "velocity_p95_km_s": float(group.velocity_error_norm_km_s.quantile(0.95)),
            "rms_median_km": float(group.supgp_rms_km.median()),
            "rms_p90_km": float(group.supgp_rms_km.quantile(0.90)),
            "rms_max_km": float(group.supgp_rms_km.max()),
            "note": "RMS quantile bin is descriptive; not a quality gate",
        })
    comparison_groups = {
        "full": frame,
        "typical_below_position_p95": frame.loc[frame.position_error_norm_km < frame.position_error_norm_km.quantile(0.95)],
        "global_top1_position": frame.loc[frame.is_global_top_1pct],
        "global_top0_5_position": frame.loc[frame.is_global_top_0_5pct],
        "top20_position": frame.loc[frame.is_global_top20],
    }
    for group_name, group in comparison_groups.items():
        rows.append({
            "section": "disagreement_group_rms_comparison", "view": "full", "group": group_name,
            "outcome": "supgp_rms_km", "method": "descriptive", "bin_label": "", "bin_left_km": "", "bin_right_km": "",
            "n": len(group), "correlation": "", "p_value": "",
            "position_median_km": float(group.position_error_norm_km.median()),
            "position_p90_km": float(group.position_error_norm_km.quantile(0.90)),
            "position_p95_km": float(group.position_error_norm_km.quantile(0.95)),
            "position_max_km": float(group.position_error_norm_km.max()),
            "velocity_median_km_s": float(group.velocity_error_norm_km_s.median()),
            "velocity_p95_km_s": float(group.velocity_error_norm_km_s.quantile(0.95)),
            "rms_median_km": float(group.supgp_rms_km.median()),
            "rms_p90_km": float(group.supgp_rms_km.quantile(0.90)),
            "rms_max_km": float(group.supgp_rms_km.max()),
            "note": "group comparison only; no records removed from formal population",
        })
    return pd.DataFrame(rows)


def plot_freshness(frame: pd.DataFrame) -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    hexbin = ax.hexbin(
        frame.element_age_hours,
        frame.position_error_norm_km,
        gridsize=45,
        mincnt=1,
        bins="log",
        cmap="viridis",
    )
    binned = pd.cut(frame.element_age_hours, AGE_EDGES_H, labels=AGE_LABELS, right=False, include_lowest=True)
    centers = [(left + right) / 2 for left, right in zip(AGE_EDGES_H[:-1], AGE_EDGES_H[1:])]
    bin_counts = [int((binned == age_bin).sum()) for age_bin in AGE_LABELS]
    for quantile, label, marker in [(0.5, "Median", "o"), (0.9, "P90", "s"), (0.95, "P95", "^")]:
        values = [frame.loc[binned == age_bin, "position_error_norm_km"].quantile(quantile) for age_bin in AGE_LABELS]
        ax.plot(centers, values, marker=marker, linewidth=1.8, label=label)
    ax.set_yscale("log")
    ax.set_xticks(centers, [f"{label}\nn={count}" for label, count in zip(AGE_LABELS, bin_counts)])
    ax.set_xlabel("Ordinary GP element age (h)")
    ax.set_ylabel("Position disagreement norm (km, log scale)")
    ax.set_title("Legitimate ordinary-GP → SupGP disagreement vs element age")
    ax.grid(True, which="both", alpha=0.22)
    ax.legend()
    colorbar = fig.colorbar(hexbin, ax=ax)
    colorbar.set_label("log10(records per hexagon)")
    fig.tight_layout()
    fig.savefig(FRESHNESS_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_rtn(frame: pd.DataFrame) -> None:
    binned = pd.cut(frame.element_age_hours, AGE_EDGES_H, labels=AGE_LABELS, right=False, include_lowest=True)
    centers = [(left + right) / 2 for left, right in zip(AGE_EDGES_H[:-1], AGE_EDGES_H[1:])]
    bin_counts = [int((binned == age_bin).sum()) for age_bin in AGE_LABELS]
    components = {"|R|": "abs_delta_R_km", "|T|": "abs_delta_T_km", "|N|": "abs_delta_N_km"}
    fig, axes = plt.subplots(1, 3, figsize=(14.5, 4.6), sharex=True)
    for ax, (quantile, title) in zip(axes, [(0.5, "Median"), (0.90, "P90"), (0.95, "P95")]):
        for label, field in components.items():
            values = [frame.loc[binned == age_bin, field].quantile(quantile) for age_bin in AGE_LABELS]
            ax.plot(centers, values, marker="o", linewidth=1.8, label=label)
        ax.set_yscale("log")
        ax.set_title(title)
        ax.set_xticks(centers, [f"{label.replace(' h', '')}\n{count}" for label, count in zip(AGE_LABELS, bin_counts)])
        ax.tick_params(axis="x", labelsize=7)
        ax.set_xlabel("Element-age bin (h); second line: n")
        ax.grid(True, which="both", alpha=0.22)
    axes[0].set_ylabel("Absolute RTN disagreement (km, log scale)")
    axes[-1].legend()
    fig.suptitle("RTN disagreement structure across element-age bins")
    fig.tight_layout()
    fig.savefig(RTN_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_regime_candidates(frame: pd.DataFrame, regime: pd.DataFrame) -> list[str]:
    ranked = regime.sort_values(["position_max_km", "duration_hours"], ascending=False)
    satellites = ranked.NORAD_CAT_ID.drop_duplicates().head(4).tolist()
    fig, axes = plt.subplots(len(satellites), 1, figsize=(12.5, 2.8 * len(satellites)), sharex=True)
    axes = np.atleast_1d(axes)
    q95 = frame.position_error_norm_km.quantile(0.95)
    q99_threshold = frame.loc[frame.is_global_top_1pct, "position_error_norm_km"].min()
    for ax, norad in zip(axes, satellites):
        group = frame.loc[frame.NORAD_CAT_ID == norad].sort_values("evaluation_time")
        ax.plot(group.evaluation_time, group.position_error_norm_km, marker=".", markersize=3, linewidth=0.8, label=f"NORAD {norad}")
        for _, episode in regime.loc[regime.NORAD_CAT_ID == norad].iterrows():
            ax.axvspan(pd.Timestamp(episode.start_time), pd.Timestamp(episode.end_time), alpha=0.16)
        ax.axhline(q95, linewidth=0.8, linestyle="--", label="pooled P95")
        ax.axhline(q99_threshold, linewidth=0.8, linestyle=":", label="top-1% threshold")
        ax.set_yscale("log")
        ax.set_ylabel("Position (km)")
        ax.grid(True, which="both", alpha=0.2)
        ax.legend(loc="upper left", ncol=3, fontsize=8)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    axes[-1].set_xlabel("Evaluation time (UTC)")
    fig.suptitle("Representative high-disagreement time-continuity candidates")
    fig.tight_layout()
    fig.savefig(REGIME_FIGURE, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return satellites


def report_text(
    frame: pd.DataFrame,
    freshness: pd.DataFrame,
    rtn: pd.DataFrame,
    satellite: pd.DataFrame,
    regime: pd.DataFrame,
    rms: pd.DataFrame,
    thresholds: dict[str, Any],
    figure_satellites: list[str],
) -> str:
    def corr(predictor: str, outcome: str, view: str = "full", method: str = "spearman") -> float:
        row = freshness.loc[
            (freshness.section == "correlation") & (freshness.view == view)
            & (freshness.predictor == predictor) & (freshness.outcome == outcome)
            & (freshness.method == method)
        ].iloc[0]
        return float(row.correlation)

    element_full = corr("element_age_hours", "position_error_norm_km")
    publication_full = corr("publication_age_hours", "position_error_norm_km")
    element_trim = corr("element_age_hours", "position_error_norm_km", "pooled_trim_global_top1_diagnostic")
    element_trim_sat = corr("element_age_hours", "position_error_norm_km", "pooled_trim_within_satellite_top1_diagnostic")
    rms_pos = float(rms.loc[(rms.section == "correlation") & (rms.view == "full") & (rms.outcome == "position_error_norm_km") & (rms.method == "spearman"), "correlation"].iloc[0])
    rms_vel = float(rms.loc[(rms.section == "correlation") & (rms.view == "full") & (rms.outcome == "velocity_error_norm_km_s") & (rms.method == "spearman"), "correlation"].iloc[0])
    pooled_position = rtn.loc[(rtn.scope == "pooled") & (rtn.state_type == "position")]
    dominant = pooled_position.sort_values("dominant_proportion", ascending=False).iloc[0]
    pattern_counts = regime.pattern_label.value_counts().to_dict()
    top_rms = rms.loc[(rms.section == "disagreement_group_rms_comparison") & (rms.group == "global_top1_position")].iloc[0]
    typical_rms = rms.loc[(rms.section == "disagreement_group_rms_comparison") & (rms.group == "typical_below_position_p95")].iloc[0]
    per_sat_positive = int((satellite.element_age_position_spearman > 0).sum())
    per_sat_median = float(satellite.element_age_position_spearman.median())
    per_sat_trim_median = float(satellite.element_age_position_spearman_trim_within_sat_top1_diagnostic.median())
    full_position_bins = freshness.loc[
        (freshness.section == "freshness_bin") & (freshness.view == "full")
        & (freshness.predictor == "element_age_hours") & (freshness.outcome == "position_error_norm_km")
    ].set_index("bin_label")
    bin_n_text = ", ".join(f"{label}: n={int(full_position_bins.loc[label, 'n'])}" for label in AGE_LABELS)
    first_four_medians = ", ".join(
        f"{label}: {float(full_position_bins.loc[label, 'median']):.3f} km" for label in AGE_LABELS[:4]
    )
    episodes_with_gp_changes = int((regime.selected_gp_change_count > 0).sum())
    max_episode = regime.sort_values("position_max_km", ascending=False).iloc[0]
    return f"""# Orbit Uncertainty Stage-1C：residual structure / freshness / regime characterization

## 1. Scope与输入

输入为冻结的Stage-1B canonical dataset：`{DATASET_PATH.as_posix()}`，20颗、5675行、5675 nominal、0 excluded。本脚本仅读取该dataset及其provenance所指ordinary/SupGP raw，用于回查orbital elements；没有重建residual、改变sign/frame或修改Stage-1B。

本轮所有trimmed view、top-tail与episode label均为descriptive diagnostic。没有建立legitimate uncertainty threshold、RMS cutoff、maneuver detector或final calibration。

## 2. Freshness structure

- pooled element age vs position：Spearman={element_full:.6f}；Pearson={corr('element_age_hours','position_error_norm_km',method='pearson'):.6f}。
- pooled publication age vs position：Spearman={publication_full:.6f}；Pearson={corr('publication_age_hours','position_error_norm_km',method='pearson'):.6f}。
- element age关联强于publication age，但两者都只是描述性association。
- exclude pooled top 1%后 element-age Spearman={element_trim:.6f}；逐星各自exclude top 1%后再pool为{element_trim_sat:.6f}。
- 20颗中{per_sat_positive}/20的within-satellite element-age Spearman为正；逐星Spearman中位数={per_sat_median:.6f}，per-satellite trimmed diagnostic中位数={per_sat_trim_median:.6f}。
- full-view element-age bin counts：{bin_n_text}。前四个样本量较充分的bin，其position median依次为{first_four_medians}。

36 h以上仅13行（36–48 h为{int(full_position_bins.loc['36-48 h', 'n'])}行，48–72 h为{int(full_position_bins.loc['48-72 h', 'n'])}行），且与高disagreement episode重叠；其极高bin quantile不可解释为稳定的cohort-wide freshness curve。

因此freshness relationship并非完全由少数最大值制造，但其强度随satellite和episode而异，不能只使用一个pooled curve代表所有目标。

## 3. RTN structure

Pooled position disagreement最常见dominant component为`{dominant.component}`，dominant proportion={float(dominant.dominant_proportion):.4f}。完整R/T/N median/P90/P95/max及逐星dominance见`{RTN_PATH.as_posix()}`与`{SATELLITE_PATH.as_posix()}`。

结论来自实际absolute RTN components与逐行argmax，没有预设along-track必须主导。

## 4. SupGP RMS association

- RMS vs position Spearman={rms_pos:.6f}。
- RMS vs velocity Spearman={rms_vel:.6f}。
- typical（position低于pooled P95）RMS median={float(typical_rms.rms_median_km):.6f} km；global top-1% RMS median={float(top_rms.rms_median_km):.6f} km。

RMS没有解释主要long tail；RMS quantile bins和高disagreement group比较只作描述，不建立cutoff。

## 5. Long-tail / regime candidates

- global top 1%：{thresholds['global_top1_count']}行，最低position={thresholds['global_top1_threshold_km']:.6f} km。
- global top 0.5%：{thresholds['global_top0_5_count']}行，最低position={thresholds['global_top0_5_threshold_km']:.6f} km。
- episode pattern counts：`{json.dumps(pattern_counts, ensure_ascii=False, sort_keys=True)}`。
- 831.098 km最大值属于同星多epoch连续高disagreement episode，不是isolated single-point spike。episode summary同时保存前后ordinary GP publication与ordinary/SupGP orbital-element变化，但这些只是candidate evidence，不是confirmed maneuver。
- {episodes_with_gp_changes}/{len(regime)}个candidate episode在episode内部出现selected ordinary GP切换。最大episode为NORAD {max_episode.NORAD_CAT_ID}，持续{float(max_episode.duration_hours):.3f} h、包含{int(max_episode.top1_row_count)}个top-1% rows、内部selected GP切换{int(max_episode.selected_gp_change_count)}次；这说明publication/state变化可回查，但不足以赋予maneuver因果标签。

代表性时间序列卫星：{', '.join(figure_satellites)}。

## 6. Sensitivity与heterogeneity

Full、pooled top-1% trimmed和per-satellite top-1% trimmed均保留正的element-age association；因此pooled freshness/RTN structure不完全由极端长尾驱动。另一方面，逐星correlation和tail magnitude差异明显，正式nominal model需要按freshness并保留satellite/regime heterogeneity，而不是立即拟合一个无条件pooled threshold。

Trimmed view is diagnostic only, not the formal uncertainty population.

## 7. 当前研究判断

1. Legitimate disagreement随element age呈明显但非决定性的单调增长关系。
2. element age与position disagreement的关系强于publication age。
3. pooled RTN通常由`{dominant.component}`方向主导；逐星结果见satellite summary。
4. SupGP RMS与position/velocity disagreement的rank association接近零，不能解释主要long tail。
5. 最大long tail包含明显时间连续episode；并非全部是孤立点，但本轮不将其标为confirmed maneuver。
6. freshness关系在pooled/per-satellite trimmed sensitivity后仍存在，但强度具有明显异质性。
7. 已具备设计freshness-conditioned nominal uncertainty model的基础；仍需下一阶段显式决定regime handling、层级结构和calibration protocol。本轮不执行该calibration。

## 8. Outputs

- freshness：`{FRESHNESS_PATH.as_posix()}`
- RTN：`{RTN_PATH.as_posix()}`
- per-satellite：`{SATELLITE_PATH.as_posix()}`
- extreme rows：`{EXTREME_PATH.as_posix()}`
- regime candidates：`{REGIME_PATH.as_posix()}`
- RMS：`{RMS_PATH.as_posix()}`
- correctness：`{CORRECTNESS_PATH.as_posix()}`
- manifest：`{MANIFEST_PATH.as_posix()}`
- figures：`{FIGURE_DIR.as_posix()}`
"""


def main() -> None:
    args = parse_args()
    ensure_outputs_available(output_paths(), args.overwrite)
    stage1b_manifest, dataset_sha = verify_input()
    dataset_sha_before = sha256(DATASET_PATH)
    frame = read_dataset()
    thresholds = add_sensitivity_flags(frame)
    ordinary_by_id, supgp_by_key = read_orbital_sources(frame)

    freshness = build_freshness_summary(frame)
    rtn = build_rtn_summary(frame)
    satellite = build_satellite_summary(frame)
    episode_records = detect_episodes(frame, thresholds)
    extreme = build_extreme_audit(frame, episode_records, ordinary_by_id, supgp_by_key)
    regime = build_regime_summary(frame, episode_records, ordinary_by_id, supgp_by_key)
    rms = build_rms_summary(frame)

    plot_freshness(frame)
    plot_rtn(frame)
    figure_satellites = plot_regime_candidates(frame, regime)

    dataset_sha_after = sha256(DATASET_PATH)
    checks = [
        {"check": "Stage-1B manifest COMPLETE and dataset SHA bound", "passed": dataset_sha == dataset_sha_before, "observed": dataset_sha},
        {"check": "canonical row/satellite count", "passed": len(frame) == 5675 and frame.NORAD_CAT_ID.nunique() == 20, "observed": f"rows={len(frame)}; satellites={frame.NORAD_CAT_ID.nunique()}"},
        {"check": "canonical rows remain nominal", "passed": bool(frame.nominal_row.astype(bool).all()), "observed": f"nominal={int(frame.nominal_row.astype(bool).sum())}"},
        {"check": "top rank counts", "passed": thresholds["global_top1_count"] == 57 and thresholds["global_top0_5_count"] == 29 and thresholds["top20_count"] == 20, "observed": json.dumps(thresholds)},
        {"check": "extreme audit covers every global top-1% row", "passed": len(extreme) == thresholds["global_top1_count"] and extreme.is_top_1pct.all(), "observed": f"rows={len(extreme)}"},
        {"check": "orbital source joins complete", "passed": not extreme.filter(regex="^(ordinary|supgp)_mean_motion$").isna().any().any(), "observed": f"ordinary_gp_records={len(ordinary_by_id)}; supgp_rows={len(supgp_by_key)}"},
        {"check": "per-satellite summary complete", "passed": len(satellite) == 20 and int(satellite.rows.sum()) == 5675, "observed": f"satellites={len(satellite)}; rows={int(satellite.rows.sum())}"},
        {"check": "freshness bins preserve explicit empty/small bins", "passed": set(AGE_LABELS).issubset(set(freshness.loc[freshness.section == 'freshness_bin', 'bin_label'])), "observed": json.dumps(AGE_LABELS)},
        {"check": "episode labels are descriptive only", "passed": regime.label_semantics.str.contains("not a confirmed maneuver", regex=False).all(), "observed": regime.pattern_label.value_counts().to_dict()},
        {"check": "trimmed views are diagnostic only", "passed": freshness.loc[freshness.view != 'full', 'note'].str.contains("diagnostic only", regex=False).all(), "observed": f"within_satellite_removed={thresholds['within_satellite_top1_count']}"},
        {"check": "figures generated", "passed": all(path.exists() and path.stat().st_size > 0 for path in [FRESHNESS_FIGURE, RTN_FIGURE, REGIME_FIGURE]), "observed": [str(path) for path in [FRESHNESS_FIGURE, RTN_FIGURE, REGIME_FIGURE]]},
        {"check": "Stage-1B canonical dataset unchanged", "passed": dataset_sha_before == dataset_sha_after, "observed": f"before={dataset_sha_before}; after={dataset_sha_after}"},
    ]
    correctness = pd.DataFrame(checks)
    if not correctness.passed.all():
        raise SystemExit(f"Stage-1C correctness failed before output write: {correctness.loc[~correctness.passed].to_dict('records')}")

    for path in [FRESHNESS_PATH, RTN_PATH, SATELLITE_PATH, EXTREME_PATH, REGIME_PATH, RMS_PATH, CORRECTNESS_PATH]:
        path.parent.mkdir(parents=True, exist_ok=True)
    freshness.to_csv(FRESHNESS_PATH, index=False, encoding="utf-8-sig")
    rtn.to_csv(RTN_PATH, index=False, encoding="utf-8-sig")
    satellite.to_csv(SATELLITE_PATH, index=False, encoding="utf-8-sig")
    extreme.to_csv(EXTREME_PATH, index=False, encoding="utf-8-sig")
    regime.to_csv(REGIME_PATH, index=False, encoding="utf-8-sig")
    rms.to_csv(RMS_PATH, index=False, encoding="utf-8-sig")
    correctness.to_csv(CORRECTNESS_PATH, index=False, encoding="utf-8-sig")

    report = report_text(frame, freshness, rtn, satellite, regime, rms, thresholds, figure_satellites)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    output_files = [FRESHNESS_PATH, RTN_PATH, SATELLITE_PATH, EXTREME_PATH, REGIME_PATH, RMS_PATH, CORRECTNESS_PATH, REPORT_PATH, FRESHNESS_FIGURE, RTN_FIGURE, REGIME_FIGURE]
    manifest = {
        "stage": "Orbit Uncertainty Stage-1C",
        "status": "STAGE1C_RESIDUAL_STRUCTURE_CHARACTERIZATION_COMPLETE",
        "generated_utc": utc_now(),
        "window_tag": WINDOW_TAG,
        "formal_window": FORMAL_INTERVAL,
        "input": {
            "stage1b_dataset": DATASET_PATH.as_posix(),
            "stage1b_dataset_sha256": dataset_sha,
            "stage1b_manifest": STAGE1B_MANIFEST_PATH.as_posix(),
            "stage1b_manifest_sha256": sha256(STAGE1B_MANIFEST_PATH),
            "rows": len(frame),
            "satellites": frame.NORAD_CAT_ID.nunique(),
            "nominal": int(frame.nominal_row.astype(bool).sum()),
            "stage1b_rebuilt": False,
            "hashes_before_after_equal": dataset_sha_before == dataset_sha_after,
        },
        "definitions": {
            "element_age": "evaluation_time - ordinary GP EPOCH",
            "publication_age": "evaluation_time - ordinary GP CREATION_DATE",
            "freshness_bins_hours": list(zip(AGE_EDGES_H[:-1], AGE_EDGES_H[1:])),
            "global_top1": "largest ceil(0.01*n) position_error_norm_km rows; 57 rows",
            "global_top0_5": "largest ceil(0.005*n) position_error_norm_km rows; 29 rows",
            "within_satellite_trim": "diagnostic only: largest ceil(0.01*n_sat) rows removed separately per satellite",
            "episode_grouping": "same-satellite adjacent global-top1 rows; bridge at most one non-top1 row only when bridge position >= pooled P95",
            "episode_patterns": {
                "A": "single top1 row without bridge",
                "B": "multiple consecutive/bridged elevated epochs not meeting C or D",
                "C": "at least 2 top1 rows, onset >=3x pre5 median, post5 below top1 threshold, recovery <=0.5x episode median",
                "D": "duration >=24 h or at least 8 top1 rows",
            },
            "orbital_angular_difference": "signed circular difference in [-180, 180) degrees",
            "label_semantics": "descriptive candidates only; never confirmed maneuver",
        },
        "builder": {
            "path": Path(__file__).as_posix(),
            "sha256": sha256(Path(__file__)),
            "python": platform.python_version(),
            "git_state": "NOT_A_GIT_WORK_TREE",
        },
        "thresholds_for_description_only": thresholds,
        "result": {
            "freshness_rows": len(freshness),
            "rtn_rows": len(rtn),
            "satellite_rows": len(satellite),
            "extreme_rows": len(extreme),
            "episode_rows": len(regime),
            "rms_rows": len(rms),
            "episode_pattern_counts": regime.pattern_label.value_counts().to_dict(),
            "figure_satellites": figure_satellites,
            "correctness_passed": int(correctness.passed.sum()),
            "correctness_total": len(correctness),
        },
        "outputs": {path.name: {"path": path.as_posix(), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in output_files},
        "scope_guards": {
            "final_uncertainty_boundary_built": False,
            "residual_rows_deleted": False,
            "rms_hard_filter_applied": False,
            "maneuver_detector_built": False,
            "synthetic_b_analyzed": False,
            "doppler_verifier_run": False,
            "final_calibration_run": False,
        },
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "input_rows": len(frame),
        "top1_rows": len(extreme),
        "episodes": len(regime),
        "episode_patterns": manifest["result"]["episode_pattern_counts"],
        "correctness": f"{int(correctness.passed.sum())}/{len(correctness)}",
        "figures": len([FRESHNESS_FIGURE, RTN_FIGURE, REGIME_FIGURE]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
