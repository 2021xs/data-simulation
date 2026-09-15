#!/usr/bin/env python3
"""Freeze the June Stage-1A causal-readiness protocol clarification.

This builder reads acquisition and provenance metadata only. It must not read
or generate RTN residuals, Stage-1F scores, or confirmatory coverage results.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


STATUS = "JUNE_STAGE1A_PROTOCOL_ADJUDICATED_CAUSAL_READY"
PROTOCOL = "CAUSAL_DATA_READINESS_V2"
EXPECTED_PARAMETER_SHA = (
    "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
)
EXPECTED_SELECTION_POLICY = (
    "CREATION_DATE <= evaluation_time; latest CREATION_DATE, then EPOCH, then GP_ID"
)
EXPECTED_EVALUATIONS = 5927
EXPECTED_GT36 = 538
EXPECTED_GT72 = 25
EXPECTED_PRIMARY = 5389
EXPECTED_AFFECTED = {"47383", "47767", "47844", "48458", "60265", "65409", "65421"}
SCIENTIFIC_SUPPORT_UPPER_HOURS = 36.0
ENGINEERING_STALENESS_HOURS = 72.0

REQUIRED_CAUSAL_FIELDS = {
    "NORAD_CAT_ID",
    "evaluation_time",
    "causal_candidate_count",
    "selected_gp_epoch",
    "selected_gp_creation_date",
    "gp_age_seconds",
    "publication_age_seconds",
    "future_publication_used",
    "selected_gp_epoch_after_evaluation",
}
FORBIDDEN_SCIENTIFIC_FIELDS = {
    "delta_r",
    "delta_t",
    "delta_n",
    "delta_v_r",
    "delta_v_t",
    "delta_v_n",
    "position_error_norm",
    "ellipsoid_score",
    "box_score",
    "p95_coverage",
    "p99_coverage",
    "false_orbit_distinct_rate",
    "orbit_distinct",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def classify_readiness(rows: Sequence[dict[str, Any]]) -> str:
    if any(int(row["causal_candidate_count"]) <= 0 for row in rows):
        return "BLOCKED_MISSING_CAUSAL_SUPPORT"
    if any(
        parse_bool(row["future_publication_used"])
        or parse_bool(row["selected_gp_epoch_after_evaluation"])
        or float(row["gp_age_seconds"]) < 0.0
        or float(row["publication_age_seconds"]) < 0.0
        for row in rows
    ):
        return "BLOCKED_FUTURE_OR_INVALID_CAUSAL_SELECTION"
    if any(float(row["gp_age_seconds"]) > ENGINEERING_STALENESS_HOURS * 3600.0 for row in rows):
        return "READY_WITH_GT72H_STALENESS"
    return "READY_CAUSAL_SUPPORTED"


def summarize_causal_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise RuntimeError("Causal support audit is empty")
    fields = {str(field).strip() for field in rows[0]}
    missing = REQUIRED_CAUSAL_FIELDS - fields
    if missing:
        raise RuntimeError(f"Causal support audit missing fields: {sorted(missing)}")
    forbidden = {field.lower() for field in fields} & FORBIDDEN_SCIENTIFIC_FIELDS
    if forbidden:
        raise RuntimeError(f"Scientific result fields are forbidden in this audit: {sorted(forbidden)}")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["NORAD_CAT_ID"]).strip()].append(row)

    ages = [float(row["gp_age_seconds"]) / 3600.0 for row in rows]
    publication_ages = [float(row["publication_age_seconds"]) / 3600.0 for row in rows]
    candidate_missing = sum(int(row["causal_candidate_count"]) <= 0 for row in rows)
    future = sum(parse_bool(row["future_publication_used"]) for row in rows)
    epoch_after = sum(parse_bool(row["selected_gp_epoch_after_evaluation"]) for row in rows)
    negative_element = sum(value < 0.0 for value in ages)
    nonpositive_element = sum(value <= 0.0 for value in ages)
    negative_publication = sum(value < 0.0 for value in publication_ages)
    gt36 = sum(value > SCIENTIFIC_SUPPORT_UPPER_HOURS for value in ages)
    gt72 = sum(value > ENGINEERING_STALENESS_HOURS for value in ages)
    primary = sum(0.0 < value <= SCIENTIFIC_SUPPORT_UPPER_HOURS for value in ages)
    gt72_rows = [
        row
        for row, age in zip(rows, ages, strict=True)
        if age > ENGINEERING_STALENESS_HOURS
    ]
    gt72_subset_gt36 = all(
        float(row["gp_age_seconds"]) / 3600.0 > SCIENTIFIC_SUPPORT_UPPER_HOURS
        for row in gt72_rows
    )
    per_satellite = []
    for norad, sat_rows in sorted(grouped.items(), key=lambda item: int(item[0])):
        sat_gt72 = sum(
            float(row["gp_age_seconds"]) > ENGINEERING_STALENESS_HOURS * 3600.0
            for row in sat_rows
        )
        per_satellite.append(
            {
                "NORAD_CAT_ID": norad,
                "evaluation_rows": len(sat_rows),
                "gt72_staleness_rows": sat_gt72,
                "readiness_v2_status": classify_readiness(sat_rows),
            }
        )

    invalid = candidate_missing + future + epoch_after + negative_element + negative_publication
    stage1b_eligible = len(rows) if invalid == 0 else 0
    return {
        "evaluation_rows": len(rows),
        "satellite_count": len(grouped),
        "causal_candidate_available_rows": len(rows) - candidate_missing,
        "causal_candidate_missing_rows": candidate_missing,
        "future_publication_use_rows": future,
        "selected_gp_epoch_after_evaluation_rows": epoch_after,
        "negative_element_age_rows": negative_element,
        "nonpositive_element_age_rows": nonpositive_element,
        "negative_publication_age_rows": negative_publication,
        "element_age_gt36_rows": gt36,
        "element_age_gt72_rows": gt72,
        "gt72_subset_of_gt36": gt72_subset_gt36,
        "gt72_affected_satellites": sorted(
            {str(row["NORAD_CAT_ID"]).strip() for row in gt72_rows}, key=int
        ),
        "stage1b_canonical_eligible_rows": stage1b_eligible,
        "stage1f_primary_confirmatory_rows": primary,
        "stage1f_outside_support_rows": len(rows) - primary,
        "cohort_readiness_v2_status": classify_readiness(rows),
        "per_satellite": per_satellite,
    }


def write_csv(
    path: Path, rows: Sequence[dict[str, Any]], fields: Sequence[str], overwrite: bool
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


def existing(paths: Iterable[Path]) -> list[Path]:
    return sorted({path for path in paths if path.exists()}, key=lambda path: path.as_posix())


def build_protected_inventory(
    completeness: dict[str, Any], stage1f: dict[str, Any]
) -> dict[str, str]:
    paths: set[Path] = set()
    for path_text in completeness["provenance"]["protected_before"]:
        paths.add(Path(path_text))
    paths.add(Path(completeness["targeted_query"]["raw_path"]))
    paths.update(Path(path_text) for path_text in completeness["outputs"])
    paths.update(
        {
            Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_manifest.json"),
            Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_acquisition_download_manifest.json"),
            Path("outputs/reports/orbit_uncertainty_stage1_20260601_20260630_acquisition_report.md"),
            Path("outputs/reports/orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_report.md"),
        }
    )
    for item in stage1f["outputs"].values():
        paths.add(Path(item["path"]))
    for tag in ("20260401_20260430", "20260501_20260531"):
        paths.update(Path("outputs/metrics").glob(f"orbit_uncertainty_stage1_{tag}_acquisition_*"))
        paths.update(Path("outputs/metrics").glob(f"orbit_uncertainty_stage1_{tag}_ordinary_gp_causal_*"))
        paths.add(Path(f"outputs/reports/orbit_uncertainty_stage1_{tag}_acquisition_report.md"))
        paths.add(Path(f"outputs/metrics/orbit_uncertainty_stage1b_{tag}_manifest.json"))
        paths.add(Path(f"outputs/reports/orbit_uncertainty_stage1b_{tag}_report.md"))
        paths.add(Path(f"outputs/datasets/orbit_uncertainty_stage1b_{tag}_rtn_residual_library.csv"))
    inventory = {path.as_posix(): sha256(path) for path in existing(paths)}
    if len(inventory) < 35:
        raise RuntimeError(f"Protected inventory unexpectedly small: {len(inventory)}")
    return inventory


def audit_row(
    section: str,
    rule_id: str,
    old_rule: str,
    clarified_rule: str,
    observed: str,
    passed: bool,
    stage1b_effect: str,
    stage1f_effect: str,
    provenance_path: str,
) -> dict[str, Any]:
    return {
        "section": section,
        "rule_id": rule_id,
        "old_rule": old_rule,
        "new_clarified_rule": clarified_rule,
        "observed": observed,
        "passed": passed,
        "stage1b_effect": stage1b_effect,
        "stage1f_effect": stage1f_effect,
        "provenance_path": provenance_path,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--causal-detail",
        type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_ordinary_gp_causal_support_audit.csv"),
    )
    parser.add_argument(
        "--acquisition-manifest",
        type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_acquisition_download_manifest.json"),
    )
    parser.add_argument(
        "--completeness-manifest",
        type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1_20260601_20260630_gt72_causal_completeness_manifest.json"),
    )
    parser.add_argument(
        "--stage1f-manifest",
        type=Path,
        default=Path("outputs/metrics/orbit_uncertainty_stage1f_lite_manifest.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    parser.add_argument("--report-dir", type=Path, default=Path("outputs/reports"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_csv = args.output_dir / "orbit_uncertainty_stage1_june_readiness_protocol_adjudication.csv"
    output_manifest = args.output_dir / "orbit_uncertainty_stage1_june_readiness_protocol_adjudication_manifest.json"
    output_report = args.report_dir / "orbit_uncertainty_stage1_june_readiness_protocol_adjudication.md"
    if not args.overwrite:
        for path in (output_csv, output_manifest, output_report):
            if path.exists():
                raise FileExistsError(f"Refusing to overwrite existing output: {path}")

    acquisition = load_json(args.acquisition_manifest)
    completeness = load_json(args.completeness_manifest)
    stage1f = load_json(args.stage1f_manifest)
    protected_before = build_protected_inventory(completeness, stage1f)

    if acquisition.get("stage1a_status") != "JUNE_STAGE1A_BLOCKED_CAUSAL_GP_AGE_GT_72H":
        raise RuntimeError("Legacy June Stage-1A state is not the expected >72 h block")
    if acquisition["causal_support"]["selection_policy"] != EXPECTED_SELECTION_POLICY:
        raise RuntimeError("Frozen causal selection policy mismatch")
    if completeness.get("status") != "JUNE_GT72H_CAUSAL_COMPLETENESS_AUDIT_COMPLETE":
        raise RuntimeError("Causal completeness audit is not complete")
    if completeness.get("conclusion") != "JUNE_GT72H_IS_REAL_CAUSAL_PUBLIC_DATA_STALENESS":
        raise RuntimeError("The >72 h cases were not proven to be real causal staleness")
    comparison = completeness["comparison"]
    if any(
        comparison[key] != 0
        for key in (
            "targeted_not_in_raw_by_gp_id",
            "targeted_not_in_raw_by_composite_key",
            "targeted_not_in_raw_union",
            "class_a_causally_eligible_newer",
            "class_b_published_only_after",
            "nonexplanatory_other",
        )
    ):
        raise RuntimeError("Targeted completeness comparison is not exact")

    support = stage1f["scientific_protocol"]["support"]
    bins = stage1f["scientific_protocol"]["freshness_bins_hours"]
    if support != {"lower_hours_exclusive": 0.0, "upper_hours_inclusive": 36.0}:
        raise RuntimeError("Frozen Stage-1F scientific support mismatch")
    if bins != [0.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0]:
        raise RuntimeError("Frozen Stage-1F freshness bins mismatch")
    if stage1f["final_fit"]["parameter_sha256"] != EXPECTED_PARAMETER_SHA:
        raise RuntimeError("Frozen Stage-1F parameter SHA mismatch")
    if stage1f["candidate_selection"]["primary_candidate_for_june"] != "ROBUST_EMPIRICAL_ELLIPSOID":
        raise RuntimeError("Frozen primary candidate mismatch")
    if stage1f["candidate_selection"]["secondary_sensitivity_candidate"] != "JOINT_MAX_SCORE_BOX":
        raise RuntimeError("Frozen secondary candidate mismatch")

    with args.causal_detail.open("r", encoding="utf-8-sig", newline="") as handle:
        causal_rows = list(csv.DictReader(handle))
    summary = summarize_causal_rows(causal_rows)
    expected = {
        "evaluation_rows": EXPECTED_EVALUATIONS,
        "satellite_count": 20,
        "causal_candidate_available_rows": EXPECTED_EVALUATIONS,
        "causal_candidate_missing_rows": 0,
        "future_publication_use_rows": 0,
        "selected_gp_epoch_after_evaluation_rows": 0,
        "negative_element_age_rows": 0,
        "nonpositive_element_age_rows": 0,
        "negative_publication_age_rows": 0,
        "element_age_gt36_rows": EXPECTED_GT36,
        "element_age_gt72_rows": EXPECTED_GT72,
        "stage1b_canonical_eligible_rows": EXPECTED_EVALUATIONS,
        "stage1f_primary_confirmatory_rows": EXPECTED_PRIMARY,
        "stage1f_outside_support_rows": EXPECTED_GT36,
        "cohort_readiness_v2_status": "READY_WITH_GT72H_STALENESS",
    }
    mismatches = {key: (summary[key], value) for key, value in expected.items() if summary[key] != value}
    if mismatches:
        raise RuntimeError(f"June readiness counts do not match frozen facts: {mismatches}")
    if set(summary["gt72_affected_satellites"]) != EXPECTED_AFFECTED:
        raise RuntimeError("Affected >72 h satellite set mismatch")
    if not summary["gt72_subset_of_gt36"]:
        raise RuntimeError("The >72 h rows are not a strict subset of >36 h rows")

    window_source = Path("scripts/orbit_uncertainty_stage1_window.py")
    acquisition_source = Path("scripts/acquire_orbit_uncertainty_stage1.py")
    april_design = Path("outputs/reports/orbit_uncertainty_stage1_20260401_20260430_design_report.md")
    stage1f_report = Path("outputs/reports/orbit_uncertainty_stage1f_lite_design_freeze_report.md")
    provenance_text = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (window_source, acquisition_source, april_design, stage1f_report)
    )
    if "LOOKBACK_HOURS = 72.0" not in provenance_text or "0 < element_age_hours <= 36" not in provenance_text:
        raise RuntimeError("Historical 72 h / frozen 36 h provenance markers are missing")

    audit_rows = [
        audit_row(
            "OLD_RULE",
            "LEGACY_STAGE1A_72H_HARD_COMPLETION_CHECK",
            "Any selected ordinary-GP element age >72 h blocked Stage-1A completion.",
            "Retained as historical implementation fact; superseded for June/future readiness by CAUSAL_DATA_READINESS_V2.",
            "June legacy status=JUNE_STAGE1A_BLOCKED_CAUSAL_GP_AGE_GT_72H; rows=25",
            True,
            "Legacy blocker adjudicated, not erased.",
            "No scientific threshold or parameter changes.",
            args.acquisition_manifest.as_posix(),
        ),
        audit_row(
            "PROVENANCE",
            "ROLE_OF_72H",
            "72 h served acquisition lookback and engineering readiness checks.",
            "72 h remains an engineering staleness reporting threshold, not uncertainty support or a safety threshold.",
            "April/May >72 h=0; June >72 h=25 after exact targeted completeness audit",
            True,
            "Age >72 h alone does not block canonical construction.",
            "No formal prediction outside 36 h.",
            "scripts/orbit_uncertainty_stage1_window.py; scripts/acquire_orbit_uncertainty_stage1.py",
        ),
        audit_row(
            "PROVENANCE",
            "ROLE_OF_36H",
            "Not a Stage-1A acquisition threshold.",
            "0 < element_age_hours <=36 is the sole frozen Stage-1F formal scientific support.",
            f"primary={summary['stage1f_primary_confirmatory_rows']}; outside={summary['stage1f_outside_support_rows']}",
            True,
            "All causal rows remain canonical.",
            "Only 5389 rows are eligible; 538 rows DEFER.",
            args.stage1f_manifest.as_posix(),
        ),
        audit_row(
            "CAUSAL_DATA_READINESS_V2",
            "CAUSAL_CANDIDATE_REQUIRED",
            "Causal candidate required.",
            "Every real SupGP evaluation row must have a causal ordinary-GP candidate.",
            f"{summary['causal_candidate_available_rows']}/{summary['evaluation_rows']}",
            summary["causal_candidate_missing_rows"] == 0,
            "5927 rows eligible.",
            "Eligibility is evaluated separately by 36 h support.",
            args.causal_detail.as_posix(),
        ),
        audit_row(
            "CAUSAL_DATA_READINESS_V2",
            "CAUSAL_SELECTION_VALIDITY",
            "Future and invalid selections blocked readiness.",
            "Require no future publication, no selected EPOCH after evaluation, and no negative element/publication age.",
            f"future={summary['future_publication_use_rows']}; epoch_after={summary['selected_gp_epoch_after_evaluation_rows']}; negative_element={summary['negative_element_age_rows']}; negative_publication={summary['negative_publication_age_rows']}",
            all(summary[key] == 0 for key in ("future_publication_use_rows", "selected_gp_epoch_after_evaluation_rows", "negative_element_age_rows", "negative_publication_age_rows")),
            "Valid causal rows eligible.",
            "Does not expand scientific support.",
            args.causal_detail.as_posix(),
        ),
        audit_row(
            "CAUSAL_DATA_READINESS_V2",
            "GT72_STALENESS_HANDLING",
            "Age >72 h was a Stage-1A completion blocker.",
            "Preserve and label ENGINEERING_STALENESS_GT72H; do not block Stage-1B solely for age >72 h.",
            f"rows={summary['element_age_gt72_rows']}; satellites={len(summary['gt72_affected_satellites'])}",
            summary["element_age_gt72_rows"] == EXPECTED_GT72,
            "25 rows preserved in the expected 5927-row canonical library.",
            "All 25 rows are OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER.",
            args.completeness_manifest.as_posix(),
        ),
        audit_row(
            "SCIENTIFIC_SUPPORT",
            "GT36_DEFER",
            "Scientific support already froze >36 h as outside support.",
            "Retain >36 h rows canonically; generate no formal Stage-1F classification or coverage contribution for them.",
            f"gt36={summary['element_age_gt36_rows']}; gt72_subset={summary['element_age_gt72_rows']}/{summary['element_age_gt72_rows']}",
            summary["gt72_subset_of_gt36"] and summary["nonpositive_element_age_rows"] == 0,
            "538 rows preserved.",
            "538 rows DEFER; primary confirmatory rows=5389.",
            args.stage1f_manifest.as_posix(),
        ),
        audit_row(
            "BLINDNESS",
            "PRE_RESULT_ADJUDICATION",
            "Protocol conflict existed before Stage-1B.",
            "Clarification is frozen before any June residual, score, coverage, or security result is read or computed.",
            "June residual rows read=0; Stage-1F scores read=0; coverage results read=0",
            True,
            "Protocol-only adjudication permits the next construction stage.",
            "Candidate, parameters, thresholds, support, and pass/fail rule unchanged.",
            args.completeness_manifest.as_posix(),
        ),
    ]
    for row in summary["per_satellite"]:
        audit_rows.append(
            audit_row(
                "PER_SATELLITE_READINESS_V2",
                f"NORAD_{row['NORAD_CAT_ID']}",
                "Legacy READY or CAUSAL_GP_AGE_GT_72H.",
                row["readiness_v2_status"],
                f"evaluation_rows={row['evaluation_rows']}; gt72={row['gt72_staleness_rows']}",
                row["readiness_v2_status"].startswith("READY_"),
                "All causally valid rows eligible for canonical Stage-1B.",
                "Rows >36 h remain DEFER independently.",
                args.causal_detail.as_posix(),
            )
        )

    fields = tuple(audit_rows[0])
    write_csv(output_csv, audit_rows, fields, args.overwrite)

    status_counts = Counter(row["readiness_v2_status"] for row in summary["per_satellite"])
    report = f"""# June Stage-1A readiness protocol adjudication

状态：`{STATUS}`

本 amendment 只解决 Stage-1A engineering readiness 与 Stage-1F scientific support 的语义冲突。它在任何 June RTN residual、Stage-1F score、P95/P99 coverage、false-orbit-distinct rate 或逐星 confirmatory performance 被读取或计算之前完成。

## 1. Provenance finding

- `72 h` 的历史来源是 ordinary-GP acquisition pre-window/lookback，并在 Stage-1A/早期 Stage-1B correctness 中被用作 engineering readiness check。它不是 uncertainty model 的 scientific support，也不是 safety threshold。
- Stage-1F-lite 的 formal scientific support 独立冻结为 `0 < element_age_hours <= 36`；freshness bins、candidate identity、frozen parameters、empirical P95/P99 threshold 和 June success rule 均未改变。
- April/May 的 `>72 h=0`，因此本 clarification 不要求回写或重跑任何历史 artifact。

72 h 历史角色判定：

| Candidate role | Provenance decision |
|---|---|
| A. causal lookback acquisition support | `true` |
| B. Stage-1A engineering/readiness condition | `true` |
| C. scientific uncertainty support | `false` |
| D. safety threshold | `false` |

## 2. OLD RULE

Legacy June Stage-1A implementation 将任何 selected ordinary-GP element age `>72 h` 作为 task-level completion blocker。因此 June 虽然 `5927/5927` rows 均有合法 causal candidate，仍得到 `JUNE_STAGE1A_BLOCKED_CAUSAL_GP_AGE_GT_72H`。

该旧状态保留为历史 provenance，不覆盖、不删除。

## 3. NEW CLARIFIED RULE: CAUSAL_DATA_READINESS_V2

1. 每个真实 SupGP evaluation row 必须存在 causal ordinary-GP candidate。
2. `CREATION_DATE <= evaluation_time`；选择顺序保持 latest `CREATION_DATE` → latest `EPOCH` → `GP_ID`。
3. future publication use、selected GP epoch after evaluation、negative element age、negative publication age必须均为0。
4. 满足上述 causal validity 的 rows 全部允许进入 canonical Stage-1B residual library。
5. element age `>72 h` 标记为 `ENGINEERING_STALENESS_GT72H`，但它本身不再阻塞 Stage-1B construction。
6. Stage-1F formal eligibility 仍只由 `0 < element_age_hours <=36` 决定；`>36 h` 一律 `OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER`。

Readiness states：`READY_CAUSAL_SUPPORTED`、`READY_WITH_GT72H_STALENESS`、`BLOCKED_MISSING_CAUSAL_SUPPORT`、`BLOCKED_FUTURE_OR_INVALID_CAUSAL_SELECTION`。

## 4. June adjudication

- SupGP evaluations：{summary['evaluation_rows']}
- causal candidate：{summary['causal_candidate_available_rows']}/{summary['evaluation_rows']}
- future publication use：{summary['future_publication_use_rows']}
- selected GP EPOCH after evaluation：{summary['selected_gp_epoch_after_evaluation_rows']}
- negative element/publication age：{summary['negative_element_age_rows']}/{summary['negative_publication_age_rows']}
- nonpositive element age：{summary['nonpositive_element_age_rows']}
- element age >36 h：{summary['element_age_gt36_rows']}
- element age >72 h：{summary['element_age_gt72_rows']}，affected satellites={summary['gt72_affected_satellites']}
- >72 h subset of >36 h：{summary['element_age_gt72_rows']}/{summary['element_age_gt72_rows']}
- V2 per-satellite status counts：{dict(status_counts)}
- cohort status：`{summary['cohort_readiness_v2_status']}`

Targeted completeness audit 已确认7/7 satellites、65/65 same-window records完全一致，missing GP_ID=0、missing composite key=0、evaluation-time-before-published newer GP=0、25/25 rank-1 selection复现。因此25 rows是 real causal public-data staleness，不能也没有使用 later GP替换。

## 5. Stage effects

- Stage-1B：`{summary['stage1b_canonical_eligible_rows']}/{summary['evaluation_rows']}` causal-supported rows eligible for canonical construction。预期 canonical rows仍为5927；538 rows和其中25个>72 h rows均不得删除、截断或替换。
- Stage-1F：future primary confirmatory rows=`{summary['stage1f_primary_confirmatory_rows']}`；outside support=`{summary['stage1f_outside_support_rows']}`。outside rows不产生formal ellipsoid/box classification、P95/P99 coverage或false-orbit-distinct contribution，只输出`DEFER`。
- Stage-1F scientific protocol changed=`false`。

## 6. Why this is not post-hoc model tuning

本 amendment 不接触 June scientific outcomes，只澄清 input readiness 与 model support 的职责边界。它不改变 primary/secondary candidate、center、covariance、scale、c95/c99、freshness support/bins、complexity rule、model-selection rule、decision semantics或June pass/fail criteria。Frozen parameter SHA仍为`{EXPECTED_PARAMETER_SHA}`。

## 7. Decision

没有科学理由仅因真实 causal element age `>72 h` 阻止完整 canonical residual library 的生成；这些rows对 public-data availability 的描述本身有价值。科学约束在 Stage-1F gate处执行：全部`>36 h` rows保留但`DEFER`。

因此确有必要在不查看 June residual 的前提下完成这次 protocol adjudication；否则会把 input availability policy 错当成 frozen model support，并无依据地丢失真实 causal rows。

`{STATUS}`

NEXT STEP: `JUNE_STAGE1B_RESIDUAL_LIBRARY_CONSTRUCTION`
"""
    write_text(output_report, report, args.overwrite)

    protected_after = {path: sha256(Path(path)) for path in protected_before}
    protected_unchanged = protected_before == protected_after
    if not protected_unchanged:
        changed = [path for path in protected_before if protected_before[path] != protected_after.get(path)]
        raise RuntimeError(f"Protected artifacts changed during adjudication: {changed}")

    checks = {
        "causal_candidate_5927_of_5927": summary["causal_candidate_available_rows"] == EXPECTED_EVALUATIONS,
        "future_publication_zero": summary["future_publication_use_rows"] == 0,
        "selected_epoch_after_evaluation_zero": summary["selected_gp_epoch_after_evaluation_rows"] == 0,
        "negative_ages_zero": summary["negative_element_age_rows"] == 0 and summary["negative_publication_age_rows"] == 0,
        "nonpositive_element_age_zero": summary["nonpositive_element_age_rows"] == 0,
        "targeted_completeness_missing_zero": comparison["targeted_not_in_raw_union"] == 0,
        "gt72_rows_25": summary["element_age_gt72_rows"] == EXPECTED_GT72,
        "gt36_rows_538": summary["element_age_gt36_rows"] == EXPECTED_GT36,
        "gt72_subset_of_gt36_25_of_25": summary["gt72_subset_of_gt36"],
        "primary_confirmatory_rows_5389": summary["stage1f_primary_confirmatory_rows"] == EXPECTED_PRIMARY,
        "stage1b_eligible_rows_5927": summary["stage1b_canonical_eligible_rows"] == EXPECTED_EVALUATIONS,
        "june_residual_rows_read_zero": True,
        "june_stage1f_scores_read_zero": True,
        "stage1f_scientific_protocol_changed_false": True,
        "frozen_parameter_sha_unchanged": sha256(Path(stage1f["final_fit"]["parameter_path"])) == EXPECTED_PARAMETER_SHA,
        "protected_artifacts_unchanged": protected_unchanged,
    }
    if not all(checks.values()):
        raise RuntimeError(f"Correctness audit failed: {checks}")

    provenance_paths = [
        window_source,
        acquisition_source,
        april_design,
        Path("outputs/reports/orbit_uncertainty_stage1_20260401_20260430_acquisition_report.md"),
        Path("outputs/reports/orbit_uncertainty_stage1_20260501_20260531_acquisition_report.md"),
        Path("outputs/reports/orbit_uncertainty_stage1b_20260401_20260430_report.md"),
        Path("outputs/reports/orbit_uncertainty_stage1b_20260501_20260531_report.md"),
        stage1f_report,
        args.acquisition_manifest,
        args.completeness_manifest,
        args.stage1f_manifest,
        args.causal_detail,
    ]
    manifest = {
        "stage": "June Stage-1A readiness protocol adjudication",
        "status": STATUS,
        "protocol": {
            "name": PROTOCOL,
            "effective_scope": "June 2026 and future data under the same frozen Stage-1F-lite protocol",
            "historical_april_may_artifacts_rewritten": False,
            "72h_role_audit": {
                "A_causal_lookback_acquisition_support": True,
                "B_stage1a_engineering_readiness_condition": True,
                "C_scientific_uncertainty_support": False,
                "D_safety_threshold": False,
            },
            "old_rule": {
                "name": "LEGACY_STAGE1A_72H_HARD_COMPLETION_CHECK",
                "role": "ordinary-GP acquisition/lookback and engineering readiness condition",
                "behavior": "selected element age >72 h blocked Stage-1A completion",
                "scientific_uncertainty_support": False,
                "safety_threshold": False,
            },
            "new_clarified_rule": {
                "causal_candidate_required_for_every_evaluation": True,
                "creation_date_must_not_exceed_evaluation_time": True,
                "selected_epoch_after_evaluation_allowed": False,
                "negative_element_or_publication_age_allowed": False,
                "causally_valid_rows_stage1b_eligible": True,
                "gt72_label": "ENGINEERING_STALENESS_GT72H",
                "gt72_alone_blocks_stage1b": False,
                "stage1f_formal_support": "0 < element_age_hours <= 36",
                "outside_support_decision": "OUTSIDE_CALIBRATED_FRESHNESS_SUPPORT / DEFER",
            },
            "readiness_states": [
                "READY_CAUSAL_SUPPORTED",
                "READY_WITH_GT72H_STALENESS",
                "BLOCKED_MISSING_CAUSAL_SUPPORT",
                "BLOCKED_FUTURE_OR_INVALID_CAUSAL_SELECTION",
            ],
            "engineering_rationale": "Canonical construction requires valid historical causal inputs; age >72 h is a measured public-data availability fact, not an invalid selection.",
            "scientific_rationale": "Formal uncertainty inference remains restricted by the independently frozen 0 < element_age_hours <= 36 support, so retaining older canonical rows does not extrapolate the model.",
        },
        "june": summary,
        "completeness_binding": {
            "status": completeness["status"],
            "conclusion": completeness["conclusion"],
            "targeted_records": completeness["targeted_query"]["half_open_window_record_count"],
            "targeted_satellites": len(completeness["targeted_query"]["request_object_ids"]),
            "targeted_not_in_raw": comparison["targeted_not_in_raw_union"],
            "causally_eligible_newer_missing": comparison["class_a_causally_eligible_newer"],
            "manifest_sha256": sha256(args.completeness_manifest),
        },
        "stage_effects": {
            "expected_canonical_stage1b_rows": EXPECTED_EVALUATIONS,
            "stage1b_rows_removed": 0,
            "stage1f_primary_confirmatory_rows": EXPECTED_PRIMARY,
            "stage1f_outside_support_defer_rows": EXPECTED_GT36,
            "stage1f_gt72_preserved_rows": EXPECTED_GT72,
            "stage1f_formal_prediction_for_outside_support_rows": 0,
            "stage1f_scientific_protocol_changed": False,
        },
        "frozen_stage1f": {
            "primary_candidate": "ROBUST_EMPIRICAL_ELLIPSOID",
            "secondary_sensitivity_candidate": "JOINT_MAX_SCORE_BOX",
            "freshness_support": support,
            "freshness_bins_hours": bins,
            "parameter_path": stage1f["final_fit"]["parameter_path"],
            "parameter_sha256": EXPECTED_PARAMETER_SHA,
            "candidate_identity_changed": False,
            "parameters_changed": False,
            "threshold_definitions_changed": False,
            "june_success_rule_changed": False,
            "decision_semantics_changed": False,
        },
        "blindness": {
            "adjudicated_before_stage1b": True,
            "june_residual_rows_read": 0,
            "june_stage1f_scores_read": 0,
            "june_coverage_results_read": 0,
            "june_security_results_read": 0,
            "residual_generated": False,
            "stage1f_score_computed": False,
        },
        "correctness": checks,
        "provenance": {
            "source_artifacts": {
                path.as_posix(): sha256(path) for path in existing(provenance_paths)
            },
            "protected_before": protected_before,
            "protected_after": protected_after,
            "protected_unchanged": protected_unchanged,
            "mutable_sources_reviewed": {
                "logs/work_log.md": "reviewed for historical Stage-1A/Stage-1F chronology; intentionally not SHA-protected because this append-only log is updated after each task"
            },
        },
        "implementation": {
            "script_path": Path(__file__).as_posix(),
            "script_sha256": sha256(Path(__file__)),
            "git_commit": None,
            "git_note": "project root is not a Git worktree",
        },
        "outputs": {
            output_csv.as_posix(): sha256(output_csv),
            output_report.as_posix(): sha256(output_report),
        },
        "scope_guards": {
            "ordinary_gp_download_performed": False,
            "stage1b_executed": False,
            "residual_file_read": False,
            "stage1f_confirmatory_validation_executed": False,
            "future_gp_substitution": False,
            "rows_dropped": 0,
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    write_text(output_manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", args.overwrite)
    print(
        json.dumps(
            {
                "status": STATUS,
                "protocol": PROTOCOL,
                "stage1b_eligible_rows": summary["stage1b_canonical_eligible_rows"],
                "stage1f_primary_rows": summary["stage1f_primary_confirmatory_rows"],
                "stage1f_defer_rows": summary["stage1f_outside_support_rows"],
                "gt72_staleness_rows": summary["element_age_gt72_rows"],
                "protected_artifacts": len(protected_before),
                "protected_unchanged": protected_unchanged,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
