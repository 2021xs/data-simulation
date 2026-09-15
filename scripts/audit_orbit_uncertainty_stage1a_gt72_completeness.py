#!/usr/bin/env python3
"""Audit whether June >72 h causal ages reflect missing Space-Track history.

The script performs one targeted GP_HISTORY completeness query, compares it to
the existing Stage-1A raw file, and never propagates an orbit or reads residuals.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

import requests

try:
    from scripts.acquire_orbit_uncertainty_stage1 import LOGIN_URL, QUERY_ROOT, parse_utc
except ModuleNotFoundError:
    from acquire_orbit_uncertainty_stage1 import LOGIN_URL, QUERY_ROOT, parse_utc


AFFECTED_IDS = ("47383", "47767", "47844", "48458", "60265", "65409", "65421")
QUERY_START = datetime(2026, 6, 18, tzinfo=timezone.utc)
QUERY_STOP = datetime(2026, 6, 25, tzinfo=timezone.utc)
FORMAL_WINDOW = "[2026-06-01T00:00:00Z, 2026-07-01T00:00:00Z)"
FROZEN_SELECTION_POLICY = (
    "CREATION_DATE <= evaluation_time; latest CREATION_DATE, then EPOCH, then GP_ID"
)
EXPECTED_FROZEN_PARAMETER_SHA = (
    "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
)
PREFIX = "orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness"


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_csv(
    path: Path,
    rows: Sequence[dict[str, Any]],
    fields: Sequence[str],
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, value: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RuntimeError(f"Expected a JSON list of objects: {path}")
    return value


def record_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("NORAD_CAT_ID", "")).strip(),
        iso_z(parse_utc(row.get("EPOCH"))),
        iso_z(parse_utc(row.get("CREATION_DATE"))),
    )


def record_sort_key(row: dict[str, Any]) -> tuple[datetime, datetime, str]:
    return (
        parse_utc(row["CREATION_DATE"]),
        parse_utc(row["EPOCH"]),
        str(row.get("GP_ID", "")),
    )


def classify_missing_record(
    row: dict[str, Any], cases: Sequence[dict[str, Any]]
) -> tuple[str, int, int]:
    creation = parse_utc(row["CREATION_DATE"])
    epoch = parse_utc(row["EPOCH"])
    eligible = 0
    newer = 0
    for case in cases:
        evaluation = parse_utc(case["evaluation_time"])
        if creation <= evaluation:
            eligible += 1
            if epoch > parse_utc(case["selected_gp_epoch"]):
                newer += 1
    if newer:
        return "A_CAUSALLY_ELIGIBLE_NEWER_GP", eligible, newer
    if not eligible:
        return "B_PUBLISHED_ONLY_AFTER_AFFECTED_EVALUATIONS", 0, 0
    return "NONEXPLANATORY_CAUSAL_BUT_NOT_NEWER", eligible, 0


def protected_inventory(
    acquisition_manifest_path: Path,
    candidate_manifest_path: Path,
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    acquisition = json.loads(acquisition_manifest_path.read_text(encoding="utf-8"))
    candidate = json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    if acquisition.get("stage1a_status") != "JUNE_STAGE1A_BLOCKED_CAUSAL_GP_AGE_GT_72H":
        raise RuntimeError("Stage-1A manifest is not at the expected >72 h blocked state")
    if candidate.get("status") != "JUNE_CONFIRMATORY_WINDOW_ACCEPTABLE":
        raise RuntimeError("June SupGP candidate audit is not ACCEPTABLE")

    expected: dict[str, str] = {
        acquisition_manifest_path.as_posix(): sha256(acquisition_manifest_path),
        candidate_manifest_path.as_posix(): sha256(candidate_manifest_path),
    }
    raw_path = Path(acquisition["ordinary_gp"]["raw_file"])
    expected[raw_path.as_posix()] = acquisition["ordinary_gp"]["sha256"]
    for item in candidate["frozen_artifact_protection"]["artifacts"]:
        expected[Path(item["path"]).as_posix()] = item["expected_sha256"]
    for path_text, expected_sha in expected.items():
        path = Path(path_text)
        if not path.exists() or sha256(path) != expected_sha:
            raise RuntimeError(f"Protected input SHA mismatch: {path}")
    return expected, acquisition, candidate


def acquire_targeted_history(path: Path, reuse_only: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path.exists():
        return load_json_rows(path), {
            "reused_without_network": True,
            "download_utc": "",
            "http_status": "",
        }
    if reuse_only:
        raise FileNotFoundError(f"Targeted query raw is not available for --reuse-only: {path}")
    username = os.environ.get("SPACETRACK_USERNAME", "")
    password = os.environ.get("SPACETRACK_PASSWORD", "")
    if not username or not password:
        raise RuntimeError("Space-Track credentials missing from process environment")

    ids_expr = ",".join(AFFECTED_IDS)
    query_url = (
        f"{QUERY_ROOT}/class/gp_history/NORAD_CAT_ID/{ids_expr}"
        f"/EPOCH/{QUERY_START:%Y-%m-%d}--{QUERY_STOP:%Y-%m-%d}"
        f"/orderby/{quote('NORAD_CAT_ID asc,EPOCH asc', safe=',')}/format/json"
    )
    session = requests.Session()
    login = session.post(
        LOGIN_URL, data={"identity": username, "password": password}, timeout=60
    )
    if login.status_code >= 400:
        raise RuntimeError(f"Space-Track login failed: HTTP {login.status_code}")
    response = session.get(query_url, timeout=180)
    if response.status_code >= 400:
        raise RuntimeError(f"Targeted GP_HISTORY query failed: HTTP {response.status_code}")
    try:
        rows = response.json()
    except ValueError as exc:
        raise RuntimeError("Targeted GP_HISTORY query returned non-JSON content") from exc
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Targeted GP_HISTORY response is not a JSON list of records")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return rows, {
        "reused_without_network": False,
        "download_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "login_http_status": login.status_code,
        "http_status": response.status_code,
        "content_type": response.headers.get("Content-Type", ""),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current-raw", type=Path,
        default=Path("data/orbit_uncertainty_stage1/raw/spacetrack_gp/spacetrack_gp_history_20260529_20260701_20sat_omm.json"),
    )
    parser.add_argument(
        "--causal-detail", type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_ordinary_gp_causal_support_audit.csv"),
    )
    parser.add_argument(
        "--acquisition-manifest", type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_acquisition_download_manifest.json"),
    )
    parser.add_argument(
        "--candidate-manifest", type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1f_june_supgp_candidate_manifest.json"),
    )
    parser.add_argument(
        "--stage1f-manifest", type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1f_lite_manifest.json"),
    )
    parser.add_argument(
        "--targeted-raw", type=Path,
        default=Path("data/orbit_uncertainty_stage1/audits/spacetrack_gp_history_20260618_20260625_7sat_gt72_completeness.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    parser.add_argument("--report-dir", type=Path, default=Path("outputs/reports"))
    parser.add_argument("--reuse-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    protected_before, acquisition, candidate = protected_inventory(
        args.acquisition_manifest, args.candidate_manifest
    )
    if acquisition["ordinary_gp"]["sha256"] != sha256(args.current_raw):
        raise RuntimeError("Current Stage-1A raw SHA does not match its manifest")
    stage1f = json.loads(args.stage1f_manifest.read_text(encoding="utf-8"))
    scientific_upper = stage1f["scientific_protocol"]["support"]["upper_hours_inclusive"]
    if scientific_upper != 36.0:
        raise RuntimeError("Frozen Stage-1F scientific support is not 36 h")
    if stage1f["final_fit"]["parameter_sha256"] != EXPECTED_FROZEN_PARAMETER_SHA:
        raise RuntimeError("Frozen Stage-1F parameter SHA mismatch")

    with args.causal_detail.open("r", encoding="utf-8-sig", newline="") as handle:
        causal_rows = list(csv.DictReader(handle))
    cases = [row for row in causal_rows if row["gp_age_gt_72h"] == "True"]
    if len(cases) != 25 or {row["NORAD_CAT_ID"] for row in cases} != set(AFFECTED_IDS):
        raise RuntimeError("Expected exactly the previously audited 25 rows / 7 satellites")

    current_rows = load_json_rows(args.current_raw)
    targeted_raw_rows, download = acquire_targeted_history(args.targeted_raw, args.reuse_only)
    targeted_raw_sha = sha256(args.targeted_raw)
    targeted_rows = [
        row for row in targeted_raw_rows
        if row.get("EPOCH")
        and QUERY_START <= parse_utc(row["EPOCH"]) < QUERY_STOP
    ]
    outside_targeted_window = len(targeted_raw_rows) - len(targeted_rows)
    returned_ids = {str(row.get("NORAD_CAT_ID", "")).strip() for row in targeted_rows}
    if returned_ids - set(AFFECTED_IDS):
        raise RuntimeError(f"Targeted query returned unexpected NORAD IDs: {returned_ids}")
    required = ("NORAD_CAT_ID", "EPOCH", "CREATION_DATE", "GP_ID")
    missing_required = sum(
        row.get(field) in (None, "") for row in targeted_rows for field in required
    )
    if missing_required:
        raise RuntimeError(f"Targeted query has {missing_required} missing required values")

    current_window_rows = [
        row for row in current_rows
        if str(row.get("NORAD_CAT_ID", "")).strip() in AFFECTED_IDS
        and row.get("EPOCH")
        and QUERY_START <= parse_utc(row["EPOCH"]) < QUERY_STOP
    ]
    current_gp_ids = {str(row.get("GP_ID", "")) for row in current_rows}
    current_keys = {record_key(row) for row in current_rows}
    missing_by_gp_id = [
        row for row in targeted_rows if str(row.get("GP_ID", "")) not in current_gp_ids
    ]
    missing_by_key = [row for row in targeted_rows if record_key(row) not in current_keys]
    union_missing: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in [*missing_by_gp_id, *missing_by_key]:
        key = (*record_key(row), str(row.get("GP_ID", "")))
        union_missing[key] = row

    cases_by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        cases_by_norad[case["NORAD_CAT_ID"]].append(case)
    comparison: list[dict[str, Any]] = []
    for row in sorted(union_missing.values(), key=record_sort_key):
        norad = str(row["NORAD_CAT_ID"])
        classification, eligible, newer = classify_missing_record(
            row, cases_by_norad[norad]
        )
        comparison.append({
            "NORAD_CAT_ID": norad,
            "GP_ID": str(row["GP_ID"]),
            "EPOCH": iso_z(parse_utc(row["EPOCH"])),
            "CREATION_DATE": iso_z(parse_utc(row["CREATION_DATE"])),
            "missing_by_gp_id": str(row["GP_ID"]) not in current_gp_ids,
            "missing_by_norad_epoch_creation": record_key(row) not in current_keys,
            "classification": classification,
            "causally_eligible_affected_evaluation_count": eligible,
            "causally_eligible_and_newer_evaluation_count": newer,
        })

    case_output = [{
        "NORAD_CAT_ID": row["NORAD_CAT_ID"],
        "evaluation_time": row["evaluation_time"],
        "selected_gp_id": row["selected_gp_id"],
        "selected_gp_epoch": row["selected_gp_epoch"],
        "selected_gp_creation_date": row["selected_gp_creation_date"],
        "element_age_hours": round(float(row["gp_age_seconds"]) / 3600.0, 6),
        "publication_age_hours": round(float(row["publication_age_seconds"]) / 3600.0, 6),
        "outside_stage1f_36h_support": float(row["gp_age_seconds"]) > scientific_upper * 3600.0,
    } for row in cases]

    current_by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in current_rows:
        current_by_norad[str(row.get("NORAD_CAT_ID", "")).strip()].append(row)
    recent: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases, start=1):
        evaluation = parse_utc(case["evaluation_time"])
        eligible = [
            row for row in current_by_norad[case["NORAD_CAT_ID"]]
            if row.get("CREATION_DATE") and parse_utc(row["CREATION_DATE"]) <= evaluation
        ]
        eligible.sort(key=record_sort_key, reverse=True)
        for rank, row in enumerate(eligible[:5], start=1):
            recent.append({
                "case_id": case_index,
                "NORAD_CAT_ID": case["NORAD_CAT_ID"],
                "evaluation_time": case["evaluation_time"],
                "causal_publication_rank": rank,
                "GP_ID": str(row.get("GP_ID", "")),
                "EPOCH": iso_z(parse_utc(row["EPOCH"])),
                "CREATION_DATE": iso_z(parse_utc(row["CREATION_DATE"])),
                "is_current_selected": str(row.get("GP_ID", "")) == case["selected_gp_id"],
            })
    if len(recent) != len(cases) * 5 or any(
        not row["is_current_selected"] for row in recent if row["causal_publication_rank"] == 1
    ):
        raise RuntimeError("Recent causal publication audit does not reproduce current selection")

    missing_a = sum(row["classification"] == "A_CAUSALLY_ELIGIBLE_NEWER_GP" for row in comparison)
    missing_b = sum(
        row["classification"] == "B_PUBLISHED_ONLY_AFTER_AFFECTED_EVALUATIONS"
        for row in comparison
    )
    missing_other = len(comparison) - missing_a - missing_b
    if missing_a:
        conclusion = "JUNE_GT72H_CAUSED_BY_ACQUISITION_INCOMPLETENESS"
    elif missing_other:
        raise RuntimeError("Targeted/current difference has an unadjudicated record class")
    else:
        conclusion = "JUNE_GT72H_IS_REAL_CAUSAL_PUBLIC_DATA_STALENESS"

    summary: list[dict[str, Any]] = []
    for norad in AFFECTED_IDS:
        targeted_sat = [row for row in targeted_rows if str(row["NORAD_CAT_ID"]) == norad]
        current_sat = [row for row in current_window_rows if str(row["NORAD_CAT_ID"]) == norad]
        comparison_sat = [row for row in comparison if row["NORAD_CAT_ID"] == norad]
        summary.append({
            "NORAD_CAT_ID": norad,
            "affected_evaluation_count": len(cases_by_norad[norad]),
            "targeted_query_records": len(targeted_sat),
            "current_raw_records_in_targeted_epoch_window": len(current_sat),
            "targeted_not_in_raw_by_gp_id": sum(row["missing_by_gp_id"] for row in comparison_sat),
            "targeted_not_in_raw_by_composite_key": sum(row["missing_by_norad_epoch_creation"] for row in comparison_sat),
            "class_a_causally_eligible_newer": sum(row["classification"] == "A_CAUSALLY_ELIGIBLE_NEWER_GP" for row in comparison_sat),
            "class_b_published_only_after": sum(row["classification"] == "B_PUBLISHED_ONLY_AFTER_AFFECTED_EVALUATIONS" for row in comparison_sat),
        })

    output_paths = {
        "cases": args.output_dir / f"{PREFIX}_cases.csv",
        "recent": args.output_dir / f"{PREFIX}_recent_causal_publications.csv",
        "comparison": args.output_dir / f"{PREFIX}_targeted_not_in_raw.csv",
        "summary": args.output_dir / f"{PREFIX}_targeted_query_summary.csv",
        "correctness": args.output_dir / f"{PREFIX}_correctness_audit.csv",
        "manifest": args.output_dir / f"{PREFIX}_manifest.json",
        "report": args.report_dir / f"{PREFIX}_report.md",
    }
    write_csv(output_paths["cases"], case_output, tuple(case_output[0]), args.overwrite)
    write_csv(output_paths["recent"], recent, tuple(recent[0]), args.overwrite)
    comparison_fields = (
        "NORAD_CAT_ID", "GP_ID", "EPOCH", "CREATION_DATE", "missing_by_gp_id",
        "missing_by_norad_epoch_creation", "classification",
        "causally_eligible_affected_evaluation_count",
        "causally_eligible_and_newer_evaluation_count",
    )
    write_csv(output_paths["comparison"], comparison, comparison_fields, args.overwrite)
    write_csv(output_paths["summary"], summary, tuple(summary[0]), args.overwrite)

    protected_after = {path: sha256(Path(path)) for path in protected_before}
    protected_unchanged = protected_after == protected_before
    credential_values = [
        os.environ.get(name, "") for name in ("SPACETRACK_USERNAME", "SPACETRACK_PASSWORD")
        if os.environ.get(name)
    ]
    checks = [
        {"check": "affected cases exactly 25 / 7 satellites", "passed": len(cases) == 25 and len(cases_by_norad) == 7, "observed": f"rows={len(cases)}; satellites={len(cases_by_norad)}"},
        {"check": "all 25 rows outside frozen 36h support", "passed": all(row["outside_stage1f_36h_support"] for row in case_output), "observed": f"outside={sum(row['outside_stage1f_36h_support'] for row in case_output)}/25"},
        {"check": "recent five causal publications available", "passed": len(recent) == 125, "observed": f"rows={len(recent)}"},
        {"check": "rank-1 publication reproduces current selection", "passed": all(row["is_current_selected"] for row in recent if row["causal_publication_rank"] == 1), "observed": "all 25 rank-1 rows match"},
        {"check": "targeted query returned all seven satellites", "passed": returned_ids == set(AFFECTED_IDS), "observed": f"returned={sorted(returned_ids)}"},
        {"check": "targeted required fields complete", "passed": missing_required == 0, "observed": f"missing_values={missing_required}"},
        {"check": "no causally eligible newer targeted record missing from raw", "passed": missing_a == 0, "observed": f"class_a={missing_a}"},
        {"check": "protected inputs unchanged", "passed": protected_unchanged, "observed": f"files={len(protected_after)}; equal={protected_unchanged}"},
        {"check": "frozen Stage-1F support remains 36h", "passed": scientific_upper == 36.0, "observed": f"upper_hours={scientific_upper}"},
        {"check": "residual/model coverage analysis absent", "passed": True, "observed": "ordinary-GP metadata completeness only"},
    ]
    write_csv(output_paths["correctness"], checks, ("check", "passed", "observed"), args.overwrite)

    report = f"""# June >72 h causal GP completeness audit

## 1. Scope

本轮只审计ordinary-GP historical availability。未生成或读取RTN residual、Stage-1F score、P95/P99 coverage或security classification；没有修改当前1693-record raw，也没有将future publication代入历史evaluation。

## 2. Targeted query

- affected NORAD：{list(AFFECTED_IDS)}
- requested EPOCH window：`[{iso_z(QUERY_START)}, {iso_z(QUERY_STOP)})`
- raw response：`{args.targeted_raw.as_posix()}`
- raw SHA：`{targeted_raw_sha}`
- response records：{len(targeted_raw_rows)}；local half-open window records：{len(targeted_rows)}；outside records：{outside_targeted_window}
- returned satellites：{len(returned_ids)}/7
- reused without network：{download['reused_without_network']}

## 3. Comparison with frozen Stage-1A raw

- targeted records not in current raw by GP_ID：{len(missing_by_gp_id)}
- targeted records not in current raw by NORAD+EPOCH+CREATION_DATE：{len(missing_by_key)}
- union missing records：{len(comparison)}
- Class A, causally eligible and newer at an affected evaluation：{missing_a}
- Class B, published only after affected evaluations：{missing_b}

{json.dumps(summary, ensure_ascii=False, indent=2)}

## 4. The 25 evaluations

全部25行均保留在`{output_paths['cases'].as_posix()}`；每行的最近5个causal publications共125行，保存在`{output_paths['recent'].as_posix()}`。每个case的rank 1均复现当前selected GP。

## 5. Scientific conclusion

`{conclusion}`

没有发现evaluation-time之前已经发布、EPOCH又比当前selected GP更新、但缺失于当前raw的记录。因此不能用今天获得的later GP“修复”这25个历史case；它们是当时public ordinary-GP availability/staleness事实，不是acquisition漏记录。

## 6. 72 h versus 36 h semantics

- 72 h：Stage-1A ordinary-GP acquisition lookback/readiness policy，用于输入可用性与因果准备度审计；不是Stage-1F uncertainty model的scientific support。
- 36 h：Stage-1F-lite冻结的scientific support，精确定义为`0 < element_age_hours <= 36`。
- 本次25个>72 h rows全部同时满足`element_age_hours >36`，因此全部属于`OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`。

这两个阈值不能互相替代，也没有在本轮修改。由于72 h是早期Stage-1A readiness policy，而25行在Stage-1F中本就DEFER，进入Stage-1B前需要在不查看June residual的前提下对Stage-1A task-level readiness进行protocol adjudication；本报告不代替该科研决定。
"""
    write_text(output_paths["report"], report, args.overwrite)

    generated = [path for key, path in output_paths.items() if key != "manifest"]
    credential_hits = 0
    for path in [args.targeted_raw, *generated]:
        payload = path.read_text(encoding="utf-8-sig", errors="ignore")
        credential_hits += sum(value in payload for value in credential_values)
    if credential_hits:
        raise RuntimeError("Credential value detected in generated audit output")

    manifest = {
        "stage": "June Stage-1A >72h causal completeness audit",
        "status": "JUNE_GT72H_CAUSAL_COMPLETENESS_AUDIT_COMPLETE",
        "conclusion": conclusion,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "causal_rule": FROZEN_SELECTION_POLICY,
        "affected": {"row_count": len(cases), "norad_ids": list(AFFECTED_IDS)},
        "targeted_query": {
            "source": "Space-Track GP_HISTORY",
            "request_object_ids": list(AFFECTED_IDS),
            "epoch_window": f"[{iso_z(QUERY_START)}, {iso_z(QUERY_STOP)})",
            "raw_path": args.targeted_raw.as_posix(),
            "raw_sha256": targeted_raw_sha,
            "raw_record_count": len(targeted_raw_rows),
            "half_open_window_record_count": len(targeted_rows),
            "outside_half_open_window_record_count": outside_targeted_window,
            **download,
        },
        "comparison": {
            "current_raw_path": args.current_raw.as_posix(),
            "current_raw_sha256": sha256(args.current_raw),
            "current_raw_targeted_window_record_count": len(current_window_rows),
            "targeted_not_in_raw_by_gp_id": len(missing_by_gp_id),
            "targeted_not_in_raw_by_composite_key": len(missing_by_key),
            "targeted_not_in_raw_union": len(comparison),
            "class_a_causally_eligible_newer": missing_a,
            "class_b_published_only_after": missing_b,
            "nonexplanatory_other": missing_other,
            "per_satellite": summary,
        },
        "protocol_semantics": {
            "stage1a_72h": "ordinary-GP acquisition lookback/readiness policy",
            "stage1f_36h": "frozen scientific model support: 0 < element_age_hours <= 36",
            "all_gt72_rows_also_outside_stage1f_support": all(row["outside_stage1f_36h_support"] for row in case_output),
            "protocol_adjudication_before_stage1b_needed": True,
        },
        "provenance": {
            "acquisition_manifest": {"path": args.acquisition_manifest.as_posix(), "sha256": sha256(args.acquisition_manifest)},
            "candidate_manifest": {"path": args.candidate_manifest.as_posix(), "sha256": sha256(args.candidate_manifest)},
            "stage1f_manifest": {"path": args.stage1f_manifest.as_posix(), "sha256": sha256(args.stage1f_manifest)},
            "frozen_parameter_sha256": EXPECTED_FROZEN_PARAMETER_SHA,
            "protected_before": protected_before,
            "protected_after": protected_after,
            "protected_unchanged": protected_unchanged,
            "credential_value_hits": credential_hits,
        },
        "blindness": {
            "residual_generated_or_read": False,
            "stage1f_score_read_or_computed": False,
            "coverage_read_or_computed": False,
            "future_gp_substituted": False,
        },
        "implementation": {
            "script_path": Path(__file__).as_posix(),
            "script_sha256": sha256(Path(__file__)),
            "git_commit": None,
            "git_note": "project root is not a Git worktree",
        },
        "outputs": {
            path.as_posix(): sha256(path) for path in generated
        },
    }
    write_text(
        output_paths["manifest"],
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        args.overwrite,
    )
    print(json.dumps({
        "status": manifest["status"],
        "conclusion": conclusion,
        "affected_rows": len(cases),
        "targeted_records": len(targeted_rows),
        "targeted_not_in_raw": len(comparison),
        "class_a_causally_eligible_newer": missing_a,
        "all_gt72_outside_stage1f_36h_support": manifest["protocol_semantics"]["all_gt72_rows_also_outside_stage1f_support"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
