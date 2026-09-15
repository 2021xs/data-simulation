#!/usr/bin/env python3
"""Prepare the Stage-1A Starlink cohort and acquisition design without downloading data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.orbit_uncertainty_stage1_window import (
        FORMAL_DURATION_DAYS,
        FORMAL_INTERVAL,
        FORMAL_START,
        FORMAL_STOP_EXCLUSIVE,
        GP_ACQUISITION_START,
        GP_ACQUISITION_STOP_EXCLUSIVE,
        LOOKBACK_HOURS,
        START_DATE,
        STOP_DATE,
        WINDOW_TAG,
    )
except ModuleNotFoundError:
    from orbit_uncertainty_stage1_window import (
        FORMAL_DURATION_DAYS,
        FORMAL_INTERVAL,
        FORMAL_START,
        FORMAL_STOP_EXCLUSIVE,
        GP_ACQUISITION_START,
        GP_ACQUISITION_STOP_EXCLUSIVE,
        LOOKBACK_HOURS,
        START_DATE,
        STOP_DATE,
        WINDOW_TAG,
    )


MU_EARTH_KM3_S2 = 398600.4418
EARTH_EQUATORIAL_RADIUS_KM = 6378.137

SELECTION_INPUT = Path("outputs/metrics/controlled_starlink_20target_selection_table.csv")
TLE_INPUT = Path("data/tle/starlink_tle.txt")
GP_CACHE_INPUT = Path("data/tle/history/starlink_gp_history_20260301_20260320.json")
STAGE0_REGIME_INPUT = Path("outputs/metrics/orbit_uncertainty_stage0_starlink_regime_audit.csv")
STAGE0_SUPGP_INPUT = Path("outputs/metrics/orbit_uncertainty_stage0_supgp_reference_quality.csv")
CURRENT_SUPGP_DIR = Path("data/orbit_uncertainty_stage1/raw/celestrak_supgp")

METRICS_DIR = Path("outputs/metrics")
REPORTS_DIR = Path("outputs/reports")
OUTPUT_PREFIX = f"orbit_uncertainty_stage1_{WINDOW_TAG}"
CANDIDATE_OUTPUT = METRICS_DIR / f"{OUTPUT_PREFIX}_candidate_audit.csv"
SELECTION_OUTPUT = METRICS_DIR / f"{OUTPUT_PREFIX}_satellite_selection.csv"
SPACE_TRACK_OUTPUT = METRICS_DIR / f"{OUTPUT_PREFIX}_spacetrack_acquisition_plan.csv"
MANIFEST_OUTPUT = METRICS_DIR / f"{OUTPUT_PREFIX}_design_manifest.json"
REQUEST_OUTPUT = REPORTS_DIR / f"{OUTPUT_PREFIX}_celestrak_request.txt"
REPORT_OUTPUT = REPORTS_DIR / f"{OUTPUT_PREFIX}_design_report.md"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite {path}; pass --overwrite explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite {path}; pass --overwrite explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_tle(path: Path) -> dict[str, dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) % 3:
        raise ValueError(f"Expected 3LE records in {path}, found {len(lines)} lines")
    records: dict[str, dict] = {}
    for index in range(0, len(lines), 3):
        name, line1, line2 = (line.strip() for line in lines[index:index + 3])
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            raise ValueError(f"Invalid 3LE record at line {index + 1}")
        norad = line1[2:7].strip()
        parts = line2.split()
        inclination_deg = float(parts[2])
        eccentricity = float(f"0.{parts[4]}")
        mean_motion_rev_day = float(parts[7])
        angular_rate_rad_s = mean_motion_rev_day * 2.0 * math.pi / 86400.0
        semi_major_axis_proxy_km = (MU_EARTH_KM3_S2 / angular_rate_rad_s**2) ** (1.0 / 3.0)
        records[norad] = {
            "tle_object_name": name,
            "inclination_deg": inclination_deg,
            "eccentricity": eccentricity,
            "mean_motion_rev_day": mean_motion_rev_day,
            "semi_major_axis_proxy_km": semi_major_axis_proxy_km,
            "mean_altitude_proxy_km": semi_major_axis_proxy_km - EARTH_EQUATORIAL_RADIUS_KM,
        }
    return records


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.rstrip("Z") + "+00:00").astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def audit_gp_cache(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["NORAD_CAT_ID"]), []).append(row)
    result: dict[str, dict] = {}
    for norad, records in grouped.items():
        epochs = sorted(parse_utc(row["EPOCH"]) for row in records)
        creations = sorted(parse_utc(row["CREATION_DATE"]) for row in records)
        span_days = max((epochs[-1] - epochs[0]).total_seconds() / 86400.0, 1.0)
        result[norad] = {
            "ordinary_gp_cached_record_count": len(records),
            "ordinary_gp_cached_epoch_min": epochs[0].isoformat().replace("+00:00", "Z"),
            "ordinary_gp_cached_epoch_max": epochs[-1].isoformat().replace("+00:00", "Z"),
            "ordinary_gp_cached_creation_min": creations[0].isoformat().replace("+00:00", "Z"),
            "ordinary_gp_cached_creation_max": creations[-1].isoformat().replace("+00:00", "Z"),
            "ordinary_gp_cached_updates_per_day": len(records) / span_days,
        }
    return result


def audit_current_supgp(path: Path) -> tuple[dict[str, dict], dict]:
    files = sorted(path.glob("*.csv"))
    by_norad: dict[str, dict] = {}
    provenance_files = []
    total_records = 0
    all_epochs: list[datetime] = []
    all_sources: Counter[str] = Counter()
    for raw_path in files:
        rows = read_csv(raw_path)
        epochs = [parse_utc(row["EPOCH"]) for row in rows]
        ids = {str(row.get("NORAD_CAT_ID", "")).strip() for row in rows}
        if len(ids) != 1:
            raise ValueError(f"Expected one NORAD per SupGP file, found {sorted(ids)} in {raw_path}")
        norad = next(iter(ids))
        sources = Counter(str(row.get("DATA_SOURCE", "")).strip() for row in rows)
        all_sources.update(sources)
        all_epochs.extend(epochs)
        total_records += len(rows)
        file_info = {
            "path": raw_path.as_posix(),
            "sha256": sha256(raw_path),
            "record_count": len(rows),
            "norad_id": norad,
            "epoch_min": min(epochs).isoformat().replace("+00:00", "Z"),
            "epoch_max": max(epochs).isoformat().replace("+00:00", "Z"),
            "data_sources": dict(sources),
        }
        provenance_files.append(file_info)
        by_norad[norad] = file_info
    formal_start = parse_utc(FORMAL_START)
    formal_stop = parse_utc(FORMAL_STOP_EXCLUSIVE)
    outside = sum(not (formal_start <= epoch < formal_stop) for epoch in all_epochs)
    summary = {
        "directory": path.as_posix(),
        "file_count": len(files),
        "record_count": total_records,
        "satellite_count": len(by_norad),
        "epoch_min": min(all_epochs).isoformat().replace("+00:00", "Z") if all_epochs else "",
        "epoch_max": max(all_epochs).isoformat().replace("+00:00", "Z") if all_epochs else "",
        "records_outside_formal_window": outside,
        "data_sources": dict(all_sources),
        "files": provenance_files,
    }
    return by_norad, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace Stage-1A outputs")
    args = parser.parse_args()

    selection = read_csv(SELECTION_INPUT)
    if len(selection) != 20:
        raise ValueError(f"Expected exactly 20 project-used targets, found {len(selection)}")
    ids = [str(row["target_norad_id"]).strip() for row in selection]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate target NORAD IDs in project selection")

    tle = parse_tle(TLE_INPUT)
    missing_tle = sorted(set(ids) - set(tle))
    if missing_tle:
        raise ValueError(f"Targets missing from TLE: {missing_tle}")

    gp_cache = audit_gp_cache(GP_CACHE_INPUT)
    regime = {row["norad_cat_id"]: row for row in read_csv(STAGE0_REGIME_INPUT)}
    supgp = {row["norad_cat_id"]: row for row in read_csv(STAGE0_SUPGP_INPUT)}
    current_supgp, current_supgp_provenance = audit_current_supgp(CURRENT_SUPGP_DIR)
    if set(current_supgp) != set(ids):
        raise ValueError(
            "Current April SupGP does not match the frozen cohort: "
            f"missing={sorted(set(ids) - set(current_supgp))}, "
            f"extra={sorted(set(current_supgp) - set(ids))}"
        )
    if current_supgp_provenance["records_outside_formal_window"]:
        raise ValueError("Current SupGP contains records outside the approved April formal window")

    audit_rows: list[dict] = []
    for row in selection:
        norad = str(row["target_norad_id"]).strip()
        name = row["target_name"].strip()
        t = tle[norad]
        cached = gp_cache.get(norad, {})
        if norad == "65409":
            expected_role = "nominal_anchor"
            expected_regime = "nominal-looking"
        elif norad == "65410":
            expected_role = "uncertain_control"
            expected_regime = "uncertain"
        elif norad == "65411":
            expected_role = "regime_change_control"
            expected_regime = "possible_regime_change"
        else:
            expected_role = "nominal_candidate_pending_stage1b_audit"
            expected_regime = "unclassified_pending_stage1b"

        cached_count = int(cached.get("ordinary_gp_cached_record_count", 0))
        s0 = supgp.get(norad)
        r0 = regime.get(norad)
        april_ref = current_supgp[norad]
        usage = f"controlled_starlink_20target target_index={row['target_index']}"
        if norad == "44714":
            usage += "; established reference case"
        audit_rows.append({
            "NORAD_CAT_ID": norad,
            "OBJECT_NAME": name,
            "project_existing_use": usage,
            "inclination_deg": f"{t['inclination_deg']:.4f}",
            "eccentricity": f"{t['eccentricity']:.7f}",
            "mean_motion_rev_day": f"{t['mean_motion_rev_day']:.8f}",
            "semi_major_axis_proxy_km": f"{t['semi_major_axis_proxy_km']:.3f}",
            "mean_altitude_proxy_km": f"{t['mean_altitude_proxy_km']:.3f}",
            "orbital_shell_audit": "project 53.16-deg / ~473-km shell",
            "ordinary_gp_local_cache_status": "cached_partial_window" if cached_count else "not_cached_stage1a",
            "ordinary_gp_cached_record_count": cached_count,
            "ordinary_gp_cached_epoch_min": cached.get("ordinary_gp_cached_epoch_min", ""),
            "ordinary_gp_cached_epoch_max": cached.get("ordinary_gp_cached_epoch_max", ""),
            "ordinary_gp_cached_creation_min": cached.get("ordinary_gp_cached_creation_min", ""),
            "ordinary_gp_cached_creation_max": cached.get("ordinary_gp_cached_creation_max", ""),
            "ordinary_gp_cached_updates_per_day": (
                f"{cached['ordinary_gp_cached_updates_per_day']:.3f}" if cached_count else ""
            ),
            "ordinary_gp_formal_window_coverage": "pending_space_track_acquisition_audit",
            "current_or_known_supgp_availability": "current_april_historical_SpaceX-E_available",
            "current_april_supgp_record_count": april_ref["record_count"],
            "current_april_supgp_epoch_min": april_ref["epoch_min"],
            "current_april_supgp_epoch_max": april_ref["epoch_max"],
            "current_april_supgp_sha256": april_ref["sha256"],
            "existing_historical_supgp": "yes_stage0_2026-03-08_to_2026-03-14" if s0 else "no_local_file",
            "existing_supgp_record_count": int(s0["record_count"]) if s0 else 0,
            "existing_regime_evidence": r0["classification"] if r0 else "not_found",
            "expected_cohort_role": expected_role,
            "expected_regime_label": expected_regime,
            "selection_status": "selected_april_reference_available_formal_gate_pending",
            "selection_basis": "already used project target; same formal shell; no unrelated object added",
        })

    audit_fields = list(audit_rows[0])
    write_csv(CANDIDATE_OUTPUT, audit_rows, audit_fields, args.overwrite)

    selection_rows = [
        {
            "NORAD_CAT_ID": row["target_norad_id"],
            "OBJECT_NAME": row["target_name"],
            "START_DATE": START_DATE,
            "STOP_DATE": STOP_DATE,
        }
        for row in selection
    ]
    write_csv(SELECTION_OUTPUT, selection_rows, list(selection_rows[0]), args.overwrite)

    norad_lines = "\n".join(ids)
    request_text = (
        f"NORAD:\n{norad_lines}\n\n"
        f"START_DATE:\n{START_DATE}\n\n"
        f"STOP_DATE:\n{STOP_DATE}\n\n"
        "FORMAT:\nCSV\n"
    )
    write_text(REQUEST_OUTPUT, request_text, args.overwrite)

    space_track_rows = [{
        "NORAD_CAT_ID": row["target_norad_id"],
        "OBJECT_NAME": row["target_name"],
        "requested_class": "gp_history",
        "preferred_format": "OMM JSON",
        "acquisition_start_utc": GP_ACQUISITION_START,
        "formal_start_utc": f"{START_DATE}T00:00:00Z",
        "formal_stop_exclusive_utc": GP_ACQUISITION_STOP_EXCLUSIVE,
        "causal_lookback_hours": LOOKBACK_HOURS,
        "local_cache_records_stage1a": int(gp_cache.get(row["target_norad_id"], {}).get("ordinary_gp_cached_record_count", 0)),
        "action": "acquire_april_formal_gp_history_with_72h_lookback",
    } for row in selection]
    write_csv(SPACE_TRACK_OUTPUT, space_track_rows, list(space_track_rows[0]), args.overwrite)

    manifest = {
        "stage": "orbit_uncertainty_stage1a_acquisition_design",
        "status": "APRIL_DESIGN_FROZEN",
        "window_tag": WINDOW_TAG,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_provenance": [
            {"path": str(path), "sha256": sha256(path)}
            for path in (
                SELECTION_INPUT, TLE_INPUT, GP_CACHE_INPUT,
                STAGE0_REGIME_INPUT, STAGE0_SUPGP_INPUT,
            )
        ],
        "cohort": {
            "size": len(selection),
            "norad_cat_ids": ids,
            "source": str(SELECTION_INPUT),
            "selection_sha256": sha256(SELECTION_OUTPUT),
            "selection_gate": "April historical SupGP availability/integrity must pass the formal Stage-1A reference-quality gate",
            "orbital_scope": "single narrow project shell: inclination about 53.16 deg; mean-altitude proxy 472.5-474.6 km",
        },
        "window": {
            "start_date": START_DATE,
            "stop_date_inclusive_for_manual_request": STOP_DATE,
            "formal_half_open_interval": FORMAL_INTERVAL,
            "duration_days": FORMAL_DURATION_DAYS,
            "ordinary_gp_acquisition_interval": f"[{GP_ACQUISITION_START}, {GP_ACQUISITION_STOP_EXCLUSIVE})",
            "window_tag": WINDOW_TAG,
            "rationale": [
                "April candidate availability audit found 20/20 satellites and 30/30 UTC days with reference",
                "read-only simulation under the existing gate produced READY=20, PARTIAL=0, NO_REFERENCE=0",
                "window selection used reference availability/integrity only, not RMS magnitude or residual results",
                "March pilot was abandoned after a repeated request returned no new epochs inside its archive-wide gap",
            ],
        },
        "current_april_supgp": current_supgp_provenance,
        "celestrak": {
            "manual_captcha_required": True,
            "format": "CSV",
            "single_request_feasible": True,
            "official_limits": {"satellites_per_request": 100, "records_per_request": 20000},
            "current_april_record_count": current_supgp_provenance["record_count"],
            "current_april_file_count": current_supgp_provenance["file_count"],
            "current_april_satellite_count": current_supgp_provenance["satellite_count"],
            "request_text": str(REQUEST_OUTPUT),
        },
        "space_track": {
            "data_class": "GP_HISTORY",
            "preferred_format": "OMM JSON",
            "acquisition_interval": f"[{GP_ACQUISITION_START}, {GP_ACQUISITION_STOP_EXCLUSIVE})",
            "causal_lookback_hours": LOOKBACK_HOURS,
            "lookback_basis": "Stage-0 max selected gp_age was 27.03 h; 72 h is >2.6x that value and spans several typical update cycles",
            "causal_policy": {
                "evaluation_time": "supgp_epoch",
                "eligible": "ordinary_gp_creation_date <= evaluation_time",
                "selection_order": ["creation_date descending", "epoch descending", "gp_id descending"],
                "no_candidate_action": "mark causal_missing; never select a future release",
            },
        },
        "reference_sampling_policy": {
            "evaluation_time": "each native SupGP epoch",
            "interpolation": "no dense minute-level pseudo-independent samples",
            "ordinary_gp": "propagate selected causal record to evaluation_time",
            "supgp": "use at native epoch; if propagated, record supgp_propagation_age_seconds explicitly",
            "reference_semantics": "operator-derived higher-quality SGP4-compatible reference, not precise truth",
        },
        "residual_schema": [
            "satellite_id", "evaluation_time", "ordinary_gp_epoch", "ordinary_gp_creation_date",
            "ordinary_gp_age_seconds", "supgp_epoch", "supgp_source", "supgp_fit_rms",
            "delta_R", "delta_T", "delta_N", "delta_v_R", "delta_v_T", "delta_v_N",
            "position_error_norm", "velocity_error_norm", "ordinary_orbital_elements",
            "supgp_orbital_elements", "regime_features", "reference_quality_features",
        ],
        "regime_design": {
            "allowed_labels": ["nominal-looking", "possible_regime_change", "uncertain"],
            "features": [
                "supgp_fit_rms", "mean_motion_change", "semi_major_axis_proxy_change", "bstar_change",
                "element_discontinuity", "gp_supgp_disagreement_jump", "reference_gap",
            ],
            "framework": {
                "nominal-looking": "no aligned multi-indicator discontinuity; adequate reference continuity",
                "possible_regime_change": "at least two independent feature families show temporally aligned change",
                "uncertain": "isolated/conflicting evidence or insufficient reference quality/coverage",
                "constraint": "BSTAR jump alone never establishes a maneuver",
            },
            "execution": "deferred to Stage-1B; no formal labels trained or thresholded in Stage-1A",
        },
        "freshness": {
            "canonical_variable": "gp_age_seconds",
            "continuous": True,
            "descriptive_bins_hours": ["0-6", "6-12", "12-24", "24-48", ">48"],
            "bins_are_model_definition": False,
        },
        "statistical_split_design": {
            "primary_nominal_outer_split": "12 train/development satellites, 3 calibration satellites, 3 held-out test satellites",
            "controls": "65411 possible-regime and 65410 uncertain remain evaluation-only controls; do not train nominal boundary with them",
            "assignment": "after coverage audit, deterministic and stratified by cached/reference coverage and orbital proxy; freeze in manifest",
            "inner_group_key": ["satellite_id", "ordinary_gp_record_id_or_propagation_arc", "utc_day"],
            "temporal_rule": "keep complete propagation arcs and adjacent same-day SupGP epochs in one partition",
            "forbidden": "random row split",
        },
        "direct_spacex_ephemeris": {
            "status": "optional_nonblocking_forward_archive",
            "policy": "from pilot start, archive raw operator files and provenance for a small selected subset",
            "historical_claim_forbidden": True,
        },
        "prohibited_in_stage1a": [
            "historical SupGP automated download", "uncertainty thresholds", "synthetic B",
            "Doppler propagation", "formal calibration", "attack-uncertainty boundary",
        ],
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", args.overwrite)

    inclination_values = [float(row["inclination_deg"]) for row in audit_rows]
    altitude_values = [float(row["mean_altitude_proxy_km"]) for row in audit_rows]
    cached_ids = [row["NORAD_CAT_ID"] for row in audit_rows if row["ordinary_gp_cached_record_count"]]
    role_counts = Counter(row["expected_cohort_role"] for row in audit_rows)
    report = f"""# Orbit uncertainty Stage-1A：cohort 与 acquisition design

## 1. 状态与边界

状态：`APRIL_DESIGN_FROZEN`。本轮冻结项目既有20颗Starlink的30天 April formal window与72 h causal lookback。当前 April SupGP 已到位并绑定provenance；本脚本不下载SupGP/GP，不计算residual或任何uncertainty threshold。

## 2. 最终cohort

最终对象为项目`controlled_starlink_20target`正式selection中的全部20颗，不加入项目外对象。角色设计为：{dict(role_counts)}。其中65409沿用Stage-0的`nominal-looking`锚点，65410为`uncertain`控制，65411为`possible_regime_change`控制；其余17颗只是`nominal_candidate_pending_stage1b_audit`，不能在取得历史reference之前声称已稳定。

轨道代理范围：倾角{min(inclination_values):.4f}–{max(inclination_values):.4f}°，TLE mean-motion推导的平均高度代理{min(altitude_values):.3f}–{max(altitude_values):.3f} km。对象确实集中在项目原有约53.16°、约473 km的单一窄shell；这是selection bias，也是当前论文对象边界，不为“多样性”强加其他shell。

旧本地ordinary GP cache只覆盖{len(cached_ids)}/20颗（{', '.join(cached_ids)}）且仅为March部分区间，不作为 April formal acquisition。April ordinary GP必须按新窗口另行获取并审核。

## 3. 共同30天窗口

CelesTrak人工请求日期为`{START_DATE}`至`{STOP_DATE}`，正式分析采用半开区间`{FORMAL_INTERVAL}`，恰为{FORMAL_DURATION_DAYS}天。窗口迁移仅依据reference availability/integrity：当前20颗均覆盖30/30 UTC日，且read-only gate simulation为20/20 READY。未使用RMS大小、residual或uncertainty结果挑选月份。

## 4. Acquisition policy

- CelesTrak：April CSV已到位，当前{current_supgp_provenance['file_count']} files / {current_supgp_provenance['record_count']} records / {current_supgp_provenance['satellite_count']}/20 satellites；逐文件SHA保存于design manifest。
- Space-Track：优先GP_HISTORY OMM JSON；采集`{GP_ACQUISITION_START}`至`{GP_ACQUISITION_STOP_EXCLUSIVE}`，其中窗口前72小时为causal lookback。Stage-0 smoke的最大selected `gp_age`为27.03小时，72小时覆盖其2.6倍以上及多个典型更新周期。若仍无causal GP，则标记`causal_missing`，不使用未来记录。
- evaluation time固定为SupGP epoch；eligible ordinary GP满足`CREATION_DATE <= evaluation_time`，再按creation date、epoch、GP_ID降序确定性选择。
- 以每条原生SupGP epoch作为reference observation，不插值成分钟级伪独立样本。如必须传播SupGP，显式保存`supgp_propagation_age_seconds`。

## 5. Regime、freshness与统计独立性

regime只设计三标签框架，不执行正式标注。`possible_regime_change`要求至少两类独立特征在时间上对齐；BSTAR单独跳变不构成maneuver证据。`gp_age_seconds`保持连续，0–6、6–12、12–24、24–48、>48小时只用于描述图表。

nominal主分析计划在coverage gate后分为12颗development/train、3颗calibration、3颗held-out satellite test；65410和65411作为evaluation-only控制。内层以`(satellite_id, ordinary_gp_record/propagation_arc, UTC day)`分组，整条传播arc不跨partition，禁止random row split。

## 6. 进入Stage-1B的条件

April SupGP availability已读取绑定；进入Stage-1B前仍必须完成 April ordinary GP acquisition、全SupGP epoch causal support audit和正式SupGP reference-quality gate。任一环节不足时停在Stage-1A，不用later GP、插值或其他reference补齐。

CelesTrak官方人工请求入口：`https://celestrak.org/NORAD/archives/sup-request.php?FORMAT=csv`；官方SupGP查询/字段说明：`https://celestrak.org/NORAD/documentation/sup-gp-queries.php`。

## 7. 关键文件

- `{CANDIDATE_OUTPUT.as_posix()}`
- `{SELECTION_OUTPUT.as_posix()}`
- `{REQUEST_OUTPUT.as_posix()}`
- `{SPACE_TRACK_OUTPUT.as_posix()}`
- `{MANIFEST_OUTPUT.as_posix()}`
"""
    write_text(REPORT_OUTPUT, report, args.overwrite)

    print(json.dumps({
        "status": manifest["status"],
        "cohort_size": len(selection),
        "window": FORMAL_INTERVAL,
        "cached_ordinary_gp_satellites": len(cached_ids),
        "current_april_supgp_records": current_supgp_provenance["record_count"],
        "outputs": [str(path) for path in (
            CANDIDATE_OUTPUT, SELECTION_OUTPUT, REQUEST_OUTPUT,
            SPACE_TRACK_OUTPUT, MANIFEST_OUTPUT, REPORT_OUTPUT,
        )],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
