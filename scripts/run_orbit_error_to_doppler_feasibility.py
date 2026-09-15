"""Audit whether the frozen verifier population can support an orbit-error-to-Doppler replay.

This program is deliberately fail-closed.  It only executes the numerical Doppler
experiment when the frozen window population, historical SupGP reference records,
and orbit-only b/k gate semantics are all unambiguous.  The current repository does
not satisfy those prerequisites, so the current execution produces a coverage and
semantic-blocker audit without propagating or scoring any orbit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

R2_POPULATION = METRICS / "causal_a_doppler_r2_core_population.csv"
R3_ROWS = DATASETS / "causal_a_doppler_r3_observation_rows.csv"
R3_UNITS = DATASETS / "causal_a_doppler_r3_unit_summary.csv"
R3_MANIFEST = METRICS / "causal_a_doppler_r3_manifest.json"
JOINT_MANIFEST = METRICS / "joint_security_final_results_manifest.json"
SELECTION = METRICS / "controlled_starlink_20target_selection_table.csv"
ORBIT_CONFIG = ROOT / "configs" / "orbit_simulation_cases.yaml"

SEGMENT_SOURCE = DATASETS / "m2_segment_local_expanded_sample_dataset.csv"
ALTITUDE_SOURCE = DATASETS / "controlled_altitude_difference_realization_dataset.csv"
MULTIPASS_SOURCE = DATASETS / "same_pair_multi_pass_realization_dataset.csv"
ACTIVE_SOURCE = METRICS / "active_compensation_first_pass_sequence_eval.csv"
BASE_VERIFIER = ROOT / "scripts" / "run_doppler_verifier_initial_experiments.py"
SEGMENT_VERIFIER = ROOT / "scripts" / "run_segmented_service_center_compensation.py"

APRIL_SUPGP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "celestrak_supgp"
MAY_SUPGP = ROOT / "data" / "orbit_uncertainty_stage1" / "respecialdatarequest (4)"
JUNE_SUPGP = ROOT / "data" / "orbit_uncertainty_stage1" / "june"

SEGMENT_OUTPUT = DATASETS / "orbit_error_to_doppler_segment_dataset.csv"
FRESHNESS_OUTPUT = METRICS / "orbit_error_to_doppler_freshness_summary.csv"
GATE_OUTPUT = METRICS / "orbit_error_to_verifier_gate_summary.csv"
PROTOCOL_OUTPUT = METRICS / "orbit_error_to_doppler_feasibility_protocol.json"
MANIFEST_OUTPUT = METRICS / "orbit_error_to_doppler_feasibility_manifest.json"
REPORT_OUTPUT = REPORTS / "orbit_error_to_doppler_feasibility_report.md"

OUTPUTS = [
    SEGMENT_OUTPUT,
    FRESHNESS_OUTPUT,
    GATE_OUTPUT,
    PROTOCOL_OUTPUT,
    MANIFEST_OUTPUT,
    REPORT_OUTPUT,
]

FRESHNESS_BINS = ["0-6 h", "6-9 h", "9-12 h", "12-18 h", "18-24 h", "24-36 h"]
SIGN_CONVENTION = "delta_f_orbit_hz = F_ref_hz - F_public_hz"
STATUS = "SEMANTIC_BLOCKER_FOUND"
VERDICT = "INSUFFICIENT_COVERAGE_FOR_DECISION"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite only this experiment's independent outputs; never modifies frozen inputs.",
    )
    parser.add_argument("--skip-log", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def parse_utc(value: Any) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def bool_value(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def stable_id(parts: list[Any]) -> str:
    payload = "|".join(str(value) for value in parts)
    return "orbit_window_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def require_inputs() -> None:
    required = [
        R2_POPULATION,
        R3_ROWS,
        R3_UNITS,
        R3_MANIFEST,
        JOINT_MANIFEST,
        SELECTION,
        ORBIT_CONFIG,
        SEGMENT_SOURCE,
        ALTITUDE_SOURCE,
        MULTIPASS_SOURCE,
        ACTIVE_SOURCE,
    ]
    missing = [rel(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing required frozen inputs: " + ", ".join(missing))


def check_output_policy(overwrite: bool) -> None:
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not overwrite:
        raise SystemExit(
            "Independent outputs already exist; use --overwrite to replace only these outputs: "
            + ", ".join(existing)
        )


def verify_manifest_binding(manifest: dict[str, Any], path: Path) -> dict[str, Any]:
    expected = None
    records = (
        manifest.get("outputs", [])
        + manifest.get("source_inputs", [])
        + manifest.get("sources", [])
        + manifest.get("R2_bindings", [])
        + manifest.get("production_verifier_implementation", [])
    )
    for record in records:
        if str(record.get("path", "")).replace("\\", "/") == rel(path):
            expected = str(record.get("sha256", "")).upper()
            break
    actual = sha256(path)
    return {
        "path": rel(path),
        "expected_sha256": expected,
        "actual_sha256": actual,
        "binding_status": "PASS" if expected and expected == actual else "UNBOUND_OR_MISMATCH",
    }


def load_supgp_inventory() -> tuple[pd.DataFrame, dict[str, list[datetime]]]:
    rows: list[dict[str, Any]] = []
    epochs_by_sat: dict[str, list[datetime]] = {}
    for month, directory in [
        ("2026-04", APRIL_SUPGP),
        ("2026-05", MAY_SUPGP),
        ("2026-06", JUNE_SUPGP),
    ]:
        if not directory.exists():
            rows.append(
                {
                    "month": month,
                    "directory": rel(directory),
                    "file_count": 0,
                    "record_count": 0,
                    "min_epoch": "",
                    "max_epoch": "",
                    "status": "MISSING",
                }
            )
            continue
        month_epochs: list[datetime] = []
        files = sorted(directory.glob("sat*.csv"))
        for path in files:
            frame = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=["NORAD_CAT_ID", "EPOCH"])
            for record in frame.itertuples(index=False):
                epoch = parse_utc(record.EPOCH)
                sat_id = str(record.NORAD_CAT_ID)
                epochs_by_sat.setdefault(sat_id, []).append(epoch)
                month_epochs.append(epoch)
        rows.append(
            {
                "month": month,
                "directory": rel(directory),
                "file_count": len(files),
                "record_count": len(month_epochs),
                "min_epoch": iso_z(min(month_epochs)) if month_epochs else "",
                "max_epoch": iso_z(max(month_epochs)) if month_epochs else "",
                "status": "AVAILABLE" if month_epochs else "EMPTY",
            }
        )
    for values in epochs_by_sat.values():
        values.sort()
    return pd.DataFrame(rows), epochs_by_sat


def load_source_maps() -> dict[str, dict[str, pd.Series]]:
    segment = pd.read_csv(SEGMENT_SOURCE, dtype=str, keep_default_na=False, low_memory=False)
    altitude = pd.read_csv(ALTITUDE_SOURCE, dtype=str, keep_default_na=False, low_memory=False)
    multipass = pd.read_csv(MULTIPASS_SOURCE, dtype=str, keep_default_na=False, low_memory=False)
    active = pd.read_csv(ACTIVE_SOURCE, dtype=str, keep_default_na=False, low_memory=False)

    altitude["source_case_id"] = (
        altitude["observation_realization_id"]
        + ":"
        + altitude["bk_mode"]
        + ":"
        + pd.to_numeric(altitude["direction_deg"]).astype(str)
    )
    multipass["source_case_id"] = multipass["observation_realization_id"] + ":" + multipass["bk_mode"]

    mappings = {
        "segment_local_heatmap_and_direction_sensitivity": (segment, "case_id"),
        "controlled_altitude_difference_synthetic_B": (altitude, "source_case_id"),
        "same_pair_multi_pass_real_TLE": (multipass, "source_case_id"),
        "active_compensation_first_pass": (active, "sequence_id"),
    }
    result: dict[str, dict[str, pd.Series]] = {}
    for family, (frame, key) in mappings.items():
        if frame[key].duplicated().any():
            raise SystemExit(f"Duplicate source key in frozen source {family}")
        result[family] = {str(row[key]): row for _, row in frame.iterrows()}
    return result


def source_geometry(
    family: str,
    source: pd.Series,
    selection: dict[str, pd.Series],
    config: dict[str, Any],
) -> dict[str, Any]:
    carrier_hz = float(config.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or config["frequency"]["center_freq_hz"])
    if family == "segment_local_heatmap_and_direction_sensitivity":
        target_id = str(source["target_sat_id"])
        pass_start = parse_utc(selection[target_id]["pass_start_utc"])
        start = pass_start + timedelta(seconds=float(source["evaluation_start_s"]))
        end = pass_start + timedelta(seconds=float(source["evaluation_end_s"]))
        return {
            "window_start_utc": iso_z(start),
            "window_end_utc": iso_z(end),
            "point_count": int(float(source["point_count"])),
            "station_lat_deg": float(source["S_lat"]),
            "station_lon_deg": float(source["S_lon"]),
            "station_alt_m": 0.0,
            "carrier_freq_hz": carrier_hz,
            "coverage_rule": "distance(S,C)<=R_cell_km on every production sample",
        }
    if family in {
        "controlled_altitude_difference_synthetic_B",
        "same_pair_multi_pass_real_TLE",
    }:
        return {
            "window_start_utc": iso_z(parse_utc(source["service_segment_start"])),
            "window_end_utc": iso_z(parse_utc(source["service_segment_end"])),
            "point_count": int(float(source["point_count"])),
            "station_lat_deg": float(source["S_lat"]),
            "station_lon_deg": float(source["S_lon"]),
            "station_alt_m": 0.0,
            "carrier_freq_hz": carrier_hz,
            "coverage_rule": "frozen service segment; production coverage mask all true",
        }
    station = config["station"]
    return {
        "window_start_utc": iso_z(parse_utc(source["pass_start_utc"])),
        "window_end_utc": iso_z(parse_utc(source["pass_end_utc"])),
        "point_count": int(float(source["num_points"])),
        "station_lat_deg": float(station["lat_deg"]),
        "station_lon_deg": float(station["lon_deg"]),
        "station_alt_m": float(station["alt_m"]),
        "carrier_freq_hz": float(source["center_freq_hz"]),
        "coverage_rule": "max_elevation_deg>=existing min_elevation_deg",
    }


def build_window_audit(
    r3_rows: pd.DataFrame,
    r3_units: pd.DataFrame,
    source_maps: dict[str, dict[str, pd.Series]],
    epochs_by_sat: dict[str, list[datetime]],
    selection: dict[str, pd.Series],
    config: dict[str, Any],
) -> pd.DataFrame:
    unit_info = r3_units.drop_duplicates("orbit_unit_id").set_index("orbit_unit_id")
    source_rows = r3_rows.drop_duplicates(["experiment_family", "source_case_id", "orbit_unit_id"]).copy()
    records: list[dict[str, Any]] = []
    for row in source_rows.itertuples(index=False):
        family = str(row.experiment_family)
        source_id = str(row.source_case_id)
        source = source_maps[family].get(source_id)
        if source is None:
            raise SystemExit(f"Frozen source row not recoverable: {family}:{source_id}")
        geometry = source_geometry(family, source, selection, config)
        unit = unit_info.loc[str(row.orbit_unit_id)]
        evaluation_time = parse_utc(unit["evaluation_time"])
        start = parse_utc(geometry["window_start_utc"])
        end = parse_utc(geometry["window_end_utc"])
        ref_epochs = epochs_by_sat.get(str(unit["A_id"]), [])
        overlap = [epoch for epoch in ref_epochs if start <= epoch <= end]
        exact = any(abs((epoch - evaluation_time).total_seconds()) <= 1e-6 for epoch in ref_epochs)
        key = [
            unit["A_id"],
            geometry["window_start_utc"],
            geometry["window_end_utc"],
            f"{geometry['station_lat_deg']:.12f}",
            f"{geometry['station_lon_deg']:.12f}",
            f"{geometry['station_alt_m']:.6f}",
            f"{geometry['carrier_freq_hz']:.3f}",
        ]
        b_center = float(row.b_center_hz)
        b_threshold = float(row.b_threshold_hz)
        k_center = float(row.k_center_hz_per_s)
        k_threshold = float(row.k_threshold_hz_per_s)
        records.append(
            {
                "analysis_unit_id": stable_id(key),
                "A_id": str(unit["A_id"]),
                "A_name": str(unit["A_name"]),
                "window_provenance_group": {
                    "segment_local_heatmap_and_direction_sensitivity": "FROZEN_P1_SEGMENT_LOCAL",
                    "controlled_altitude_difference_synthetic_B": "FROZEN_P2_FIXED_SEGMENT",
                    "same_pair_multi_pass_real_TLE": "FROZEN_P3_MULTIPASS_SEGMENT",
                    "active_compensation_first_pass": "FROZEN_P4_FULL_PASS",
                }[family],
                "segment_or_pass_id": str(unit["segment_or_pass_id"]),
                "evaluation_time": iso_z(evaluation_time),
                **geometry,
                "A_GP_ID": str(unit["A_GP_ID"]),
                "A_GP_EPOCH": iso_z(parse_utc(unit["A_GP_EPOCH"])),
                "A_GP_CREATION_DATE": iso_z(parse_utc(unit["A_GP_CREATION_DATE"])),
                "element_age_hours": float(unit["element_age_hours"]),
                "publication_age_hours": float(unit["publication_age_hours"]),
                "freshness_bin": str(unit["freshness_bin"]),
                "orbit_support_status": str(unit["orbit_support_status"]),
                "score_threshold_hz": float(row.score_threshold_hz),
                "b_center_hz": b_center,
                "b_threshold_hz": b_threshold,
                "k_center_hz_per_s": k_center,
                "k_threshold_hz_per_s": k_threshold,
                "b_gate_enabled": math.isfinite(b_threshold),
                "reference_record_in_window": bool(overlap),
                "exact_reference_at_evaluation_time": exact,
                "reference_epoch_count_in_window": len(overlap),
                "reference_first_epoch_for_sat": iso_z(min(ref_epochs)) if ref_epochs else "",
                "reference_last_epoch_for_sat": iso_z(max(ref_epochs)) if ref_epochs else "",
                "delta_f_sign_convention": SIGN_CONVENTION,
                "raw_mean_hz": math.nan,
                "raw_rms_hz": math.nan,
                "raw_max_abs_hz": math.nan,
                "raw_p95_abs_hz": math.nan,
                "segment_start_end_difference_hz": math.nan,
                "b_hat_orbit_hz": math.nan,
                "k_hat_orbit_hz_per_s": math.nan,
                "score_orbit_hz": math.nan,
                "projection_residual_ratio": math.nan,
                "explained_fraction": math.nan,
                "score_gate_pass": "",
                "b_gate_pass": "",
                "k_gate_pass": "",
                "coverage_gate_pass": "",
                "quality_gate_pass": "",
                "final_verifier_decision": "NOT_EVALUATED",
                "execution_status": STATUS,
                "exclusion_reason": "NO_TEMPORAL_OVERLAP_WITH_SUPGP_REFERENCE;ORBIT_ONLY_BK_GATE_BASELINE_UNDEFINED",
            }
        )
    frame = pd.DataFrame(records)
    profile_columns = [
        "score_threshold_hz",
        "b_center_hz",
        "b_threshold_hz",
        "k_center_hz_per_s",
        "k_threshold_hz_per_s",
    ]
    collapsed: list[pd.Series] = []
    for _, group in frame.groupby("analysis_unit_id", sort=False):
        row = group.iloc[0].copy()
        profiles = group[profile_columns].drop_duplicates()
        row["threshold_profile_count"] = len(profiles)
        row["threshold_semantics_status"] = "UNIQUE" if len(profiles) == 1 else "AMBIGUOUS_MULTIPLE_FROZEN_PROFILES"
        for column in profile_columns:
            row[f"{column}_min"] = float(group[column].min())
            row[f"{column}_max"] = float(group[column].max())
            if group[column].nunique(dropna=False) > 1:
                row[column] = math.nan
        if len(profiles) > 1:
            row["exclusion_reason"] += ";ANALYSIS_UNIT_MULTIPLE_FROZEN_THRESHOLD_PROFILES"
        collapsed.append(row)
    result = pd.DataFrame(collapsed)
    return result.sort_values(
        ["evaluation_time", "A_id", "station_lat_deg", "station_lon_deg"]
    ).reset_index(drop=True)


def build_freshness_summary(windows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for freshness in FRESHNESS_BINS:
        group = windows[windows["freshness_bin"].eq(freshness)]
        rows.append(
            {
                "freshness_bin": freshness,
                "frozen_analysis_units": len(group),
                "unique_satellites": group["A_id"].nunique(),
                "units_with_reference_record_in_window": int(group["reference_record_in_window"].sum()),
                "units_with_exact_reference_at_evaluation_time": int(group["exact_reference_at_evaluation_time"].sum()),
                "raw_rms_median_hz": math.nan,
                "raw_rms_p90_hz": math.nan,
                "raw_rms_p95_hz": math.nan,
                "raw_rms_p99_hz": math.nan,
                "score_orbit_median_hz": math.nan,
                "explained_fraction_median": math.nan,
                "b_hat_orbit_median_hz": math.nan,
                "k_hat_orbit_median_hz_per_s": math.nan,
                "science_execution_status": "NOT_RUN",
                "notes": "No numerical Doppler aggregate: frozen windows and reference raw epochs do not overlap.",
            }
        )
    return pd.DataFrame(rows)


def build_gate_summary(windows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    gates = ["score", "b", "k", "score_plus_bk"]
    for gate in gates:
        rows.append(
            {
                "gate_name": gate,
                "total_frozen_analysis_units": len(windows),
                "evaluated_units": 0,
                "pass_count": 0,
                "rejection_count": 0,
                "defer_count": len(windows),
                "median_ratio": math.nan,
                "p90_ratio": math.nan,
                "p95_ratio": math.nan,
                "p99_ratio": math.nan,
                "max_ratio": math.nan,
                "status": STATUS,
                "notes": (
                    "Direct orbit-only b/k coefficients are additive perturbations, while the frozen gate "
                    "is defined on total fitted b/k around nonzero legitimate centers; nominal anchoring is not frozen."
                ),
            }
        )
    return pd.DataFrame(rows)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "（无记录）"
    return frame.to_markdown(index=False)


def build_report(
    windows: pd.DataFrame,
    freshness: pd.DataFrame,
    inventory: pd.DataFrame,
    manifest_bindings: list[dict[str, Any]],
) -> str:
    window_min = windows["window_start_utc"].min()
    window_max = windows["window_end_utc"].max()
    base_segments = windows[["A_id", "segment_or_pass_id", "evaluation_time"]].drop_duplicates()
    finite_b = windows[windows["b_gate_enabled"]]
    disabled_b = windows[~windows["b_gate_enabled"]]
    threshold_conflicts = int((windows["threshold_profile_count"] > 1).sum())
    return f"""# 公开轨道预测误差 → Doppler / Verifier 最小可行性审计

## 1. 结论先行

本轮状态：`{STATUS}`。

最终 verdict：`{VERDICT}`。

按照预先给定的停止条件，本轮没有执行轨道传播、Doppler 计算、OLS 拟合或 verifier 判决，也没有生成随机数。原因不是数值失败，而是 frozen population 与 reference 的时间覆盖不相交，并且纯 orbit-only `b_hat/k_hat` 如何进入当前总量 b/k gate 没有冻结语义。继续运行会要求新建科学 population 或自行定义 nominal b/k anchoring，二者均超出本轮授权。

## 2. 已冻结协议

- residual sign convention：`{SIGN_CONVENTION}`。
- freshness bins：`{' / '.join(FRESHNESS_BINS)}`；正式支持域为 `0 < age <= 36 h`。
- aggregation unit：合法 A × frozen segment/time × station；不同 source-provenance 条目或 observation realization 在恢复 station 后去重。
- production score：复用 centered-time OLS 后的 residual RMSE；没有定义新 score。
- thresholds / b/k gate：保持 frozen 值不变；本轮没有修改 verifier。
- reference 语义：SpaceX-E/SupGP higher-quality historical reference，不是 ground truth 或 exact state。

protocol/config hash 见 `outputs/metrics/orbit_error_to_doppler_feasibility_protocol.json` 与 manifest。

## 3. Frozen window coverage

- frozen Level-A units：407；恢复并去重后的 A×segment/time×station analysis units：{len(windows)}。
- 不考虑 station 的唯一 A×segment/time：{len(base_segments)}；卫星数：{windows['A_id'].nunique()}。
- frozen 时间范围：`{window_min}` 至 `{window_max}`。
- reference raw record 时间范围从 2026-04-01 开始；与上述 frozen March 窗口的 overlap units：{int(windows['reference_record_in_window'].sum())}/{len(windows)}。
- 在 frozen evaluation time 存在 exact SupGP reference epoch 的 units：{int(windows['exact_reference_at_evaluation_time'].sum())}/{len(windows)}。
- 同一 A×segment/time×station 映射到多个 frozen threshold profiles 的 units：{threshold_conflicts}/{len(windows)}；本审计没有任取其一。

### Reference inventory

{markdown_table(inventory)}

### Freshness coverage（仅 coverage，不含 Doppler 结果）

{markdown_table(freshness[['freshness_bin', 'frozen_analysis_units', 'unique_satellites', 'units_with_reference_record_in_window', 'units_with_exact_reference_at_evaluation_time']])}

当前 frozen windows 没有 `6-9 h` 和 `24-36 h` 覆盖，且主要集中在 `12-18 h`。即使 reference 时间问题被解决，这个分布也不足以稳定回答 6 个 freshness bins 的单调性或 P99 endpoint。

## 4. Semantic blocker：orbit-only b/k 与 production gate

production centered-time OLS 本身可无歧义复用，`score_orbit` 与 projection absorption diagnostic 也可定义。但 frozen final gate 对总 fitted parameters 判决：

- {len(finite_b)} 个 analysis units 启用有限 b gate，b center 为非零的 legitimate effective-bias calibration center；
- {len(disabled_b)} 个 full-pass provenance analysis units 的 b gate 被禁用；其 k gate 使用 per-target k quantile；
- 其余窗口使用 `current_bk`，b/k gate 作用于总 fitted b/k，而不是 orbit-induced additive delta。

本轮又明确禁止加入 `b_env`、`k_env`、noise。若把 `delta_f_orbit` 直接作为完整 residual，则非零 b center 的 gate failure 主要表示“没有 nominal effective bias”，不能解释为 ordinary-GP/reference disagreement 引起。若人为加上 b/k center，则需要新增一个未冻结的 deterministic anchoring rule，也违反“直接把 orbit-only residual 送入原 verifier”的字面语义。因此 final b/k pass/fail 和 combined decision 暂不可无歧义计算。

此外，{threshold_conflicts} 个去重后的 A×segment/time×station 单位映射到多个 frozen threshold profile；Level-A provenance 没有为本轮合法-A去重单位冻结唯一选择规则。审计仅保存各 profile 的 min/max 与冲突计数，没有任取阈值。

## 5. Q1–Q10 回答状态

1. Q1 raw Doppler 大小：未回答；frozen window 无 matching reference record。
2. Q2 freshness 关系：未回答；无 Doppler output，且两个 freshness bins 为空。
3. Q3 b+kt 吸收比例：未回答；不得凭 Stage-1 state residual 推断 observation-space projection。
4. Q4 score 对 freshness：未回答。
5. Q5 b/k gate 是否触发：未回答；orbit-only additive coefficient 与 total-parameter gate 的 anchoring 未冻结。
6. Q6 rejection attribution：未回答。
7. Q7 verifier 鲁棒性：证据不足，不能声称 robust 或 non-robust。
8. Q8 freshness-aware calibration：当前没有支持证据。
9. Q9 无需新 uncertainty layer：当前也没有支持证据。
10. Q10 geometry vs freshness：未回答；现有窗口 station/geometry 可恢复，但没有 reference-overlap outcome。

## 6. 需要解除的最小 blocker

后续若要重新授权数值实验，至少需要先冻结以下两点：

1. 合法-A evaluation population：在 April/May（exploratory）和 June（confirmatory）内预先选择 existing/frozen pass segments 与 stations，并在看 Doppler 结果前冻结 unit、timestamps、coverage rule 和 exclusions。不得把 SupGP epoch 直接事后当作 pass center。
2. gate perturbation semantics：明确 orbit-only `b_hat_orbit/k_hat_orbit` 是只做 margin diagnostic，还是叠加到哪个预先冻结的 nominal legitimate b/k anchor 后再执行 total b/k gate。两者不能混写。

在此之前，正确停止点是 coverage/semantic audit，而不是建立 freshness-aware threshold。

## 7. 产物与保护检查

- segment dataset 是 blocker/coverage audit；所有 science metric 均为空，`final_verifier_decision=NOT_EVALUATED`。
- 未生成诊断图，因为没有合法的 numeric Doppler output。
- manifest binding 检查：{sum(item['binding_status'] == 'PASS' for item in manifest_bindings)}/{len(manifest_bindings)} PASS。
- 未修改 407 Level-A、265-unit joint endpoint、orbit uncertainty 参数、R1/R2/R3/R4、threshold 或 final synthesis。
"""


def append_log(windows: pd.DataFrame, inventory: pd.DataFrame) -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    entry = f"""

## {now} - 公开轨道预测误差到 Doppler / Verifier 可行性审计

### A. 本轮目标

审计 frozen 合法-A 验证窗口能否支持 ordinary public GP relative to SpaceX-E/SupGP reference 的 orbit-only Doppler replay，并在可行时复用 production OLS / score / b/k gates。

### B. 实际操作

读取并核对 R2/R3/joint frozen provenance；从 frozen source artifacts 恢复 A×segment/time×station 单位；审计 April/May/June SupGP raw epoch overlap、freshness-bin coverage 与 production b/k gate 语义。触发 `SEMANTIC_BLOCKER_FOUND` 后按停止条件未执行轨道传播、Doppler、OLS 或 verifier。

### C. 新增/修改文件

- 新增 `scripts/run_orbit_error_to_doppler_feasibility.py`。
- 新增独立 coverage/blocker dataset、freshness summary、gate summary、protocol、manifest 和中文报告。
- 追加本日志。没有修改 frozen science、配置、threshold 或原始输入。

### D. 运行命令

`python scripts/run_orbit_error_to_doppler_feasibility.py`

### E. 结果摘要

恢复并去重的 analysis units={len(windows)}，reference-overlap units={int(windows['reference_record_in_window'].sum())}；reference inventory months={','.join(inventory['month'].astype(str))}。frozen windows 位于 March，而正式 SupGP reference raw records 从 April 开始。orbit-only additive b/k 与 production total-parameter b/k gate 之间缺少冻结 anchoring 语义。状态=`{STATUS}`；verdict=`{VERDICT}`。

### F. 问题与下一步

本轮 verifier v2 gate evaluation=未运行；visibility diagnostic=未运行；dataset/metrics/report=仅生成 coverage/blocker audit；figures=未生成。下一步只有在预先冻结 April/May/June 合法-A pass/station population 与 nominal b/k anchoring 后，才值得重新运行数值实验；当前不设计 freshness-aware threshold。
"""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def main() -> int:
    args = parse_args()
    require_inputs()
    check_output_policy(args.overwrite)

    config = yaml.safe_load(ORBIT_CONFIG.read_text(encoding="utf-8"))
    if config.get("mode") != "controlled_starlink" or config.get("observation_id") is not None:
        raise SystemExit("Experiment requires controlled_starlink mode with observation_id=null")

    r2 = pd.read_csv(R2_POPULATION, dtype=str, keep_default_na=False)
    included = r2[r2["include_in_R3"].map(bool_value)].copy()
    r3_units = pd.read_csv(R3_UNITS, dtype=str, keep_default_na=False, low_memory=False)
    r3_rows = pd.read_csv(R3_ROWS, dtype=str, keep_default_na=False, low_memory=False)
    if len(included) != 407 or len(r3_units) != 407 or len(r3_rows) != 26780:
        raise SystemExit(
            f"Frozen population mismatch: R2={len(included)}, R3_units={len(r3_units)}, R3_rows={len(r3_rows)}"
        )

    r3_manifest = json.loads(R3_MANIFEST.read_text(encoding="utf-8"))
    joint_manifest = json.loads(JOINT_MANIFEST.read_text(encoding="utf-8"))
    bindings = [
        verify_manifest_binding(r3_manifest, R3_ROWS),
        verify_manifest_binding(r3_manifest, R3_UNITS),
        verify_manifest_binding(joint_manifest, R3_MANIFEST),
        verify_manifest_binding(r3_manifest, R2_POPULATION),
        verify_manifest_binding(r3_manifest, SEGMENT_SOURCE),
        verify_manifest_binding(r3_manifest, ALTITUDE_SOURCE),
        verify_manifest_binding(r3_manifest, MULTIPASS_SOURCE),
        verify_manifest_binding(r3_manifest, ACTIVE_SOURCE),
        verify_manifest_binding(r3_manifest, ORBIT_CONFIG),
        verify_manifest_binding(r3_manifest, BASE_VERIFIER),
        verify_manifest_binding(r3_manifest, SEGMENT_VERIFIER),
    ]
    if any(item["binding_status"] != "PASS" for item in bindings):
        raise SystemExit("Frozen manifest binding mismatch; refusing to continue")

    selection_frame = pd.read_csv(SELECTION, dtype=str, keep_default_na=False)
    selection = {str(row["target_norad_id"]): row for _, row in selection_frame.iterrows()}
    source_maps = load_source_maps()
    inventory, epochs_by_sat = load_supgp_inventory()
    windows = build_window_audit(r3_rows, r3_units, source_maps, epochs_by_sat, selection, config)
    freshness = build_freshness_summary(windows)
    gates = build_gate_summary(windows)

    if windows["reference_record_in_window"].any():
        raise SystemExit("Unexpected reference overlap: numerical execution path is intentionally not implemented")

    protocol = {
        "protocol_name": "ORBIT_ERROR_TO_DOPPLER_FEASIBILITY_V1",
        "status": STATUS,
        "science_execution_performed": False,
        "protocol_frozen_before_new_doppler_results": True,
        "residual_sign_convention": SIGN_CONVENTION,
        "reference_semantics": "ordinary public GP relative to SpaceX-E/SupGP higher-quality historical reference; not ground truth",
        "aggregation_unit": "A x frozen segment/time x station",
        "freshness_bins": FRESHNESS_BINS,
        "support": "0 < element_age_hours <= 36; otherwise OUT_OF_SUPPORT/DEFER",
        "production_ols": "centered-time OLS; unchanged; not executed because prerequisites failed",
        "score": "production residual RMSE; unchanged; not executed",
        "thresholds": "frozen thresholds unchanged",
        "randomness": "no random number generation",
        "config_binding": {"path": rel(ORBIT_CONFIG), "sha256": sha256(ORBIT_CONFIG)},
        "frozen_R3_manifest_binding": {"path": rel(R3_MANIFEST), "sha256": sha256(R3_MANIFEST)},
        "exclusions": [
            "no SupGP reference raw epoch overlap with frozen March windows",
            "orbit-only additive b/k to production total-parameter b/k gate anchoring is not frozen",
            "some deduplicated A x segment/time x station units map to multiple frozen threshold profiles",
        ],
        "verdict": VERDICT,
    }
    write_json(PROTOCOL_OUTPUT, protocol)
    protocol_hash = sha256(PROTOCOL_OUTPUT)

    write_csv(SEGMENT_OUTPUT, windows)
    write_csv(FRESHNESS_OUTPUT, freshness)
    write_csv(GATE_OUTPUT, gates)
    report = build_report(windows, freshness, inventory, bindings)
    REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUTPUT.write_text(report, encoding="utf-8")

    manifest = {
        "stage": "ORBIT_ERROR_TO_DOPPLER_FEASIBILITY",
        "status": STATUS,
        "generated_utc": iso_z(datetime.now(timezone.utc)),
        "verdict": VERDICT,
        "science_execution_performed": False,
        "orbit_propagation_count": 0,
        "doppler_evaluation_count": 0,
        "ols_fit_count": 0,
        "verifier_execution_count": 0,
        "new_random_draw_count": 0,
        "frozen_level_a_units": len(r3_units),
        "frozen_observation_rows": len(r3_rows),
        "deduplicated_analysis_units": len(windows),
        "unique_A_segment_time_units": int(
            windows[["A_id", "segment_or_pass_id", "evaluation_time"]].drop_duplicates().shape[0]
        ),
        "unique_satellites": int(windows["A_id"].nunique()),
        "reference_overlap_units": int(windows["reference_record_in_window"].sum()),
        "ambiguous_threshold_profile_units": int((windows["threshold_profile_count"] > 1).sum()),
        "protocol": {"path": rel(PROTOCOL_OUTPUT), "sha256": protocol_hash},
        "frozen_bindings": bindings,
        "reference_inventory": inventory.to_dict(orient="records"),
        "protected_source_modifications": [],
        "generator": {
            "path": rel(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
            "size_bytes": Path(__file__).resolve().stat().st_size,
        },
        "outputs": [
            {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in [SEGMENT_OUTPUT, FRESHNESS_OUTPUT, GATE_OUTPUT, PROTOCOL_OUTPUT, REPORT_OUTPUT]
        ],
        "software": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
        },
    }
    write_json(MANIFEST_OUTPUT, manifest)
    if not args.skip_log:
        append_log(windows, inventory)
    print(json.dumps({
        "status": STATUS,
        "verdict": VERDICT,
        "analysis_units": len(windows),
        "reference_overlap_units": int(windows["reference_record_in_window"].sum()),
        "report": rel(REPORT_OUTPUT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
