#!/usr/bin/env python3
"""Publish the append-only R0 reproduction-population accounting erratum."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

R0_REPORT = REPORTS / "doppler_semantic_reconstruction_method_decision.md"
R0_FAMILY = METRICS / "doppler_semantic_reconstruction_family_matrix.csv"
R0_DEPENDENCY = METRICS / "doppler_semantic_reconstruction_dependency_audit.csv"
R0_PROTOCOL = METRICS / "doppler_semantic_reconstruction_protocol.json"
R0_MANIFEST = METRICS / "doppler_semantic_reconstruction_manifest.json"

R1_REPORT = REPORTS / "causal_a_doppler_reconstruction_reproduction_validation_report.md"
R1_MANIFEST = METRICS / "causal_a_doppler_r1_manifest.json"
R1_BINDING = DATASETS / "causal_a_doppler_r1_reproduction_rows.csv"
R1_NUMERICAL_OUTPUTS = [
    METRICS / "causal_a_doppler_r1_geometry_reproduction.csv",
    METRICS / "causal_a_doppler_r1_fit_score_reproduction.csv",
    METRICS / "causal_a_doppler_r1_gate_decision_reproduction.csv",
]

RELABEL_ROWS = DATASETS / "existing_doppler_cases_orbit_distinct_relabeling.csv"
STATE_AUDIT = METRICS / "orbit_distinct_ab_state_reconstruction_audit.csv"
RELABEL_MANIFEST = METRICS / "orbit_distinct_relabel_manifest.json"
FROZEN_PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
FROZEN_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"

SOURCE_VERIFIER_ARTIFACTS = [
    METRICS / "doppler_verifier_orbit_similarity_attack_results.csv",
    METRICS / "verifier_v2_sequence_eval.csv",
    METRICS / "active_compensation_first_pass_sequence_eval.csv",
    DATASETS / "same_pair_multi_pass_realization_dataset.csv",
    DATASETS / "controlled_altitude_difference_realization_dataset.csv",
]

FAILED_R1_ARTIFACTS = [
    R1_REPORT, R1_MANIFEST, R1_BINDING,
    METRICS / "causal_a_doppler_r1_state_reproduction.csv",
    *R1_NUMERICAL_OUTPUTS,
    METRICS / "causal_a_doppler_r1_failure_attribution.csv",
    METRICS / "causal_a_doppler_r1_verifier_v2_crosscheck.csv",
    METRICS / "causal_a_doppler_r1_correctness_audit.csv",
]

AUTHORITATIVE_INPUTS = [
    R0_REPORT, R0_FAMILY, R0_DEPENDENCY, R0_PROTOCOL, R0_MANIFEST,
    RELABEL_ROWS, STATE_AUDIT, RELABEL_MANIFEST,
    *FAILED_R1_ARTIFACTS, *SOURCE_VERIFIER_ARTIFACTS, FROZEN_PARAMETERS,
]

REPORT_OUTPUT = REPORTS / "doppler_semantic_reconstruction_r0_population_erratum.md"
ERRATUM_OUTPUT = METRICS / "doppler_semantic_reconstruction_r0_population_erratum.csv"
IDENTITY_OUTPUT = METRICS / "doppler_semantic_reconstruction_r0_population_identity_audit.csv"
BINDING_OUTPUT = METRICS / "doppler_semantic_reconstruction_r1_corrected_population_binding.csv"
MANIFEST_OUTPUT = METRICS / "doppler_semantic_reconstruction_r0_population_erratum_manifest.json"
OUTPUTS = [REPORT_OUTPUT, ERRATUM_OUTPUT, IDENTITY_OUTPUT, BINDING_OUTPUT, MANIFEST_OUTPUT]

COMPATIBLE_STATUSES = {"EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"}
V2_VIEW = "verifier_v2_score_only_view"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def stable_frame_sha(frame: pd.DataFrame, columns: list[str]) -> str:
    ordered = frame.loc[:, columns].fillna("").astype(str).sort_values(columns).reset_index(drop=True)
    payload = ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def stable_row_identity(row: pd.Series) -> str:
    payload = "\x1f".join(str(row[column]) for column in ["source_artifact", "source_view", "case_id", "orbit_unit_id"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def validate_inputs(overwrite: bool) -> dict[str, str]:
    missing = [rel(path) for path in AUTHORITATIVE_INPUTS if not path.exists()]
    if missing:
        raise SystemExit("Missing protected input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Output exists; use --overwrite: " + ", ".join(existing))
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen orbit-uncertainty parameter SHA mismatch")

    r0 = json.loads(R0_MANIFEST.read_text(encoding="utf-8"))
    protocol = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    if r0.get("R1_compatible_orbit_units") != 64 or r0.get("R1_primary_source_rows") != 6480:
        raise SystemExit("Original R0 accounting fields no longer match the preserved error")
    if protocol["R1_reproduction_gate"].get("derived_verifier_v2_view_rows") != 200:
        raise SystemExit("Original R0 V2 count changed")

    r1 = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    zero_fields = [
        "orbit_propagation_count", "doppler_geometry_execution_count", "random_draw_count",
        "OLS_execution_count", "verifier_execution_count", "spotcheck_count",
    ]
    if r1.get("status") != "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED":
        raise SystemExit("Failed R1 status is not preserved")
    if any(int(r1.get(field, -1)) != 0 for field in zero_fields):
        raise SystemExit("A numerical R1 execution counter is nonzero; accounting-only erratum is invalid")
    for path in R1_NUMERICAL_OUTPUTS:
        if len(pd.read_csv(path)) != 0:
            raise SystemExit(f"Numerical R1 output is nonempty: {rel(path)}")
    return {rel(path): sha256(path) for path in AUTHORITATIVE_INPUTS}


def construct_population() -> tuple[pd.DataFrame, pd.DataFrame]:
    state = pd.read_csv(STATE_AUDIT, dtype=str, keep_default_na=False)
    units = state[state["A_reconstruction_status"].isin(COMPATIBLE_STATUSES)].copy()
    unit_ids = set(units["orbit_unit_id"])
    columns = [
        "experiment_family", "source_view", "source_artifact", "case_id", "orbit_unit_id",
        "A_id", "A_name", "B_id_or_definition", "segment_id", "evaluation_time",
        "original_A_source", "A_reconstruction_status", "selected_A_GP_ID",
        "selected_A_GP_EPOCH", "selected_A_GP_CREATION_DATE", "B_reconstruction_status",
        "original_verifier_score", "original_b_hat", "original_k_hat",
        "original_verifier_accept", "original_verifier_decision",
        "original_coverage_status", "original_bk_mode",
    ]
    binding = pd.read_csv(RELABEL_ROWS, usecols=columns, dtype=str, keep_default_na=False)
    binding = binding[binding["orbit_unit_id"].isin(unit_ids)].copy()
    binding["row_role"] = binding["source_view"].map(
        lambda value: "VERIFIER_V2_SECONDARY" if value == V2_VIEW else "PRIMARY"
    )
    binding["stable_row_identity"] = binding.apply(stable_row_identity, axis=1)
    binding = binding.sort_values(["row_role", "experiment_family", "orbit_unit_id", "source_view", "case_id"]).reset_index(drop=True)

    counts = binding.groupby(["orbit_unit_id", "row_role"]).size().unstack(fill_value=0)
    for column in ["PRIMARY", "VERIFIER_V2_SECONDARY"]:
        if column not in counts:
            counts[column] = 0
    unit_columns = [
        "orbit_unit_id", "experiment_family", "A_id", "A_name", "B_id_or_definition",
        "segment_id", "evaluation_time", "A_reconstruction_status", "selected_A_GP_ID",
        "B_reconstruction_status",
    ]
    identity = units[unit_columns].drop_duplicates("orbit_unit_id").set_index("orbit_unit_id")
    identity = identity.join(counts[["PRIMARY", "VERIFIER_V2_SECONDARY"]], how="left").fillna(0).reset_index()
    identity = identity.rename(columns={"PRIMARY": "primary_row_count", "VERIFIER_V2_SECONDARY": "secondary_row_count"})
    identity["primary_row_count"] = identity["primary_row_count"].astype(int)
    identity["secondary_row_count"] = identity["secondary_row_count"].astype(int)
    identity["total_row_count"] = identity["primary_row_count"] + identity["secondary_row_count"]
    identity["compatible_unit"] = True
    identity = identity.sort_values("orbit_unit_id").reset_index(drop=True)
    return binding, identity


def verify_population(binding: pd.DataFrame, identity: pd.DataFrame) -> dict[str, Any]:
    primary = binding[binding["row_role"].eq("PRIMARY")]
    secondary = binding[binding["row_role"].eq("VERIFIER_V2_SECONDARY")]
    primary_ids = set(primary["stable_row_identity"])
    secondary_ids = set(secondary["stable_row_identity"])
    union_ids = primary_ids | secondary_ids
    source_missing = [path for path in binding["source_artifact"].unique() if not (ROOT / path).exists()]
    facts = {
        "compatible_units": int(identity["orbit_unit_id"].nunique()),
        "primary_rows": len(primary),
        "secondary_rows": len(secondary),
        "intersection_rows": len(primary_ids & secondary_ids),
        "union_rows": len(union_ids),
        "duplicate_stable_identities": int(binding["stable_row_identity"].duplicated().sum()),
        "missing_identity_fields": int((binding[["source_artifact", "source_view", "case_id", "orbit_unit_id"]] == "").any(axis=1).sum()),
        "missing_source_artifacts": len(source_missing),
        "orphan_rows": int((~binding["orbit_unit_id"].isin(set(identity["orbit_unit_id"]))).sum()),
        "units_without_rows": int((identity["total_row_count"] == 0).sum()),
        "additional_primary_identities_found": 0,
    }
    expected = {
        "compatible_units": 64, "primary_rows": 6280, "secondary_rows": 200,
        "intersection_rows": 0, "union_rows": 6480, "duplicate_stable_identities": 0,
        "missing_identity_fields": 0, "missing_source_artifacts": 0, "orphan_rows": 0,
        "units_without_rows": 0, "additional_primary_identities_found": 0,
    }
    mismatch = {key: (facts[key], value) for key, value in expected.items() if facts[key] != value}
    if mismatch:
        raise SystemExit(f"Corrected population audit failed: {mismatch}")
    facts["primary_set_sha256"] = stable_frame_sha(primary, ["stable_row_identity"])
    facts["secondary_set_sha256"] = stable_frame_sha(secondary, ["stable_row_identity"])
    facts["total_bound_set_sha256"] = stable_frame_sha(binding, ["stable_row_identity"])
    facts["compatible_unit_identity_sha256"] = stable_frame_sha(
        identity, ["orbit_unit_id", "experiment_family", "A_id", "B_id_or_definition", "segment_id", "evaluation_time"]
    )
    return facts


def erratum_table(facts: dict[str, Any]) -> pd.DataFrame:
    records = [
        ("compatible_units", "64", "64", "UNCHANGED"),
        ("primary_source_rows", "6480", "6280", "ACCOUNTING_CORRECTION"),
        ("verifier_v2_secondary_rows", "200", "200", "UNCHANGED"),
        ("total_bound_rows", "6680_IMPLIED", "6480", "ACCOUNTING_CORRECTION"),
        ("primary_secondary_intersection", "NOT_EXPLICIT", "0", "CLARIFIED"),
        ("additional_primary_identities", "IMPLIED_200", "0", "ACCOUNTING_CORRECTION"),
        ("scientific_method_changed", "false", "false", "UNCHANGED"),
        ("population_identity_changed", "false", "false", "UNCHANGED"),
        ("post_hoc_scientific_tuning", "false", "false", "UNCHANGED"),
        ("result_driven_population_change", "false", "false", "UNCHANGED"),
        ("accounting_correction_only", "not_recorded", "true", "CLARIFIED"),
        ("R1_primary_pass_denominator_rows", "6480", "6280", "ACCOUNTING_CORRECTION"),
        ("R1_secondary_pass_denominator_rows", "200", "200", "UNCHANGED"),
    ]
    frame = pd.DataFrame(records, columns=["field", "old_value", "corrected_value", "change_class"])
    frame["evidence_union_rows"] = facts["union_rows"]
    frame["evidence_intersection_rows"] = facts["intersection_rows"]
    return frame


def build_report(facts: dict[str, Any], identity: pd.DataFrame) -> str:
    family = identity.groupby("experiment_family").agg(
        compatible_units=("orbit_unit_id", "nunique"),
        primary_rows=("primary_row_count", "sum"),
        secondary_rows=("secondary_row_count", "sum"),
        total_rows=("total_row_count", "sum"),
    ).reset_index()
    return f"""# Doppler semantic reconstruction R0 population erratum

## 1. Erratum decision

本 erratum 仅修正 R0 reproduction population 的 row-count accounting：

| Population | Original R0 | Corrected |
|---|---:|---:|
| compatible units | 64 | 64 |
| primary source rows | 6,480 | 6,280 |
| verifier-v2 secondary rows | 200 | 200 |
| total bound rows | implied 6,680 | 6,480 |

原 R0 中“6,480 primary”确认是 accounting error：该数值实际等于 primary 与 V2 secondary 的 union。authoritative binding 中不存在额外 200 条独立 primary identities。

## 2. Identity-set audit

- `|PRIMARY_SET| = {facts['primary_rows']}`
- `|VERIFIER_V2_SECONDARY_SET| = {facts['secondary_rows']}`
- `intersection = {facts['intersection_rows']}`
- `union = {facts['union_rows']}`
- compatible units = {facts['compatible_units']}
- duplicate stable identities = {facts['duplicate_stable_identities']}
- missing identity fields = {facts['missing_identity_fields']}
- orphan rows = {facts['orphan_rows']}

Stable row identity schema：`SHA256(source_artifact + source_view + case_id + orbit_unit_id)`。

| Set | SHA-256 |
|---|---|
| PRIMARY_SET | `{facts['primary_set_sha256']}` |
| VERIFIER_V2_SECONDARY_SET | `{facts['secondary_set_sha256']}` |
| TOTAL_BOUND_SET | `{facts['total_bound_set_sha256']}` |
| compatible unit identity | `{facts['compatible_unit_identity_sha256']}` |

## 3. Unit-level accounting

{family.to_markdown(index=False)}

完整 64-unit 逐项计数见 machine-readable identity audit；各 unit 的 row count 没有被假设为相同。

## 4. Scientific scope

`R0 scientific method changed = false`。

以下全部不变：64-unit identities、family membership、A compatibility rule、B semantics、causal-A reconstruction、Doppler production chain、active-compensation formula、draws/seeds、OLS、score、thresholds、b/k gates、coverage、ACCEPT/REJECT logic、numerical tolerances、R1 hierarchy、zero categorical mismatch requirement 和 R2 authorization rule。

- `POST_HOC_SCIENTIFIC_TUNING = false`
- `RESULT_DRIVEN_POPULATION_CHANGE = false`
- `POPULATION_IDENTITY_CHANGE = false`
- `ACCOUNTING_CORRECTION_ONLY = true`

第一次 R1 在 `PRE_LEVEL_1_POPULATION_GATE` 停止。A/B state、Doppler、compensation、residual、OLS、fit、score、gates、decision 和 spot-check 均为 `NOT_EVALUATED`，所有 numerical execution counters 为 0。因此本 erratum 发生在任何数值结果生成或查看之前。

## 5. Corrected R1 expectation

R1 primary pass/fail 重新冻结为：64/64 units 与 6,280/6,280 primary rows，全部原 numerical tolerances 通过且所有 categorical/final-decision mismatch 为 0。只有 primary PASS 后，才对 200/200 verifier-v2 secondary rows 做 cross-check。

## 6. Formal answers

1. Compatible units：64，未改变。
2. Primary identities：精确 6,280。
3. V2 secondary identities：精确 200。
4. Primary/secondary intersection：0。
5. Union：精确 6,480。
6. “6,480 primary”只是 accounting error：是。
7. 缺失的额外 200 primary identities：不存在。
8. Erratum 前生成/查看 numerical R1 result：否。
9. Scientific protocol 修改：否。
10. Corrected machine-readable binding：已生成。
11. R1 可以按 corrected denominator 重新执行，但本轮未执行。

## 7. Formal status

`R0_POPULATION_ERRATUM_PUBLISHED`

`CORRECTED R1 PRIMARY: 64 units / 6280 rows`

`R1 SECONDARY: 200 verifier-v2 rows`

`TOTAL BOUND: 6480 rows`

`SCIENTIFIC METHOD CHANGED: NO`

`NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_RERUN`
"""


def append_log() -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    entry = f"""

## {now} - R0 population erratum

### A. 本轮目标
以 append-only erratum 修正 R0 reproduction population 的 row-count accounting，不改变 scientific method 或 population identity。

### B. 实际操作
从 authoritative relabel binding 和 state audit 重建 PRIMARY、VERIFIER_V2_SECONDARY 与 TOTAL sets；验证 64 units、6,280 primary、200 secondary、0 intersection、6,480 union。确认第一次 R1 numerical/verifier execution counters 均为 0。

### C. 新增/修改文件
新增 erratum report、accounting table、64-unit identity audit、corrected population binding、manifest、生成脚本和测试。原 R0、第一次 R1、Orbit-Uncertainty、bridge 和 Doppler outputs 均未修改。

### D. 运行命令
`python scripts/publish_doppler_semantic_reconstruction_r0_population_erratum.py`
`python -m pytest tests/test_doppler_semantic_reconstruction_r0_population_erratum.py -q`

### E. 结果摘要
`R0_POPULATION_ERRATUM_PUBLISHED`。Corrected R1 primary=64 units/6,280 rows，secondary=200，total=6,480，intersection=0；scientific method changed=false。

### F. 问题与下一步
下一步为 `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_RERUN`；本轮没有执行 R1 numerical reproduction。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def run(args: argparse.Namespace) -> None:
    before = validate_inputs(args.overwrite)
    binding, identity = construct_population()
    facts = verify_population(binding, identity)
    erratum = erratum_table(facts)

    write_csv(ERRATUM_OUTPUT, erratum)
    write_csv(IDENTITY_OUTPUT, identity)
    write_csv(BINDING_OUTPUT, binding)
    write_text(REPORT_OUTPUT, build_report(facts, identity))

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        raise SystemExit("Protected artifact changed: " + ", ".join(changed))

    manifest = {
        "stage": "R0_POPULATION_ERRATUM",
        "status": "R0_POPULATION_ERRATUM_PUBLISHED",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "supersedes_fields_only": {
            "artifact": rel(R0_PROTOCOL),
            "fields": ["R1_reproduction_gate.primary_source_rows_bound_to_units", "R1_reproduction_gate.primary_source_row_breakdown.initial_score_only"],
            "old_values": [6480, 300],
            "corrected_values": [6280, 100],
        },
        "corrected_population": facts,
        "scientific_method_changed": False,
        "post_hoc_scientific_tuning": False,
        "result_driven_population_change": False,
        "population_identity_change": False,
        "accounting_correction_only": True,
        "pre_erratum_R1_numerical_results_generated_or_inspected": False,
        "corrected_R1_primary": {"units": 64, "rows": 6280},
        "R1_secondary": {"role": "VERIFIER_V2_SECONDARY", "rows": 200, "run_only_after_primary_pass": True},
        "total_bound_rows": 6480,
        "R1_numerical_reproduction_executed_this_round": False,
        "execution_counters": {
            "orbit_propagation": 0, "doppler_geometry": 0, "random_draw": 0,
            "OLS": 0, "verifier": 0, "spotcheck": 0,
        },
        "frozen_parameter_sha256": sha256(FROZEN_PARAMETERS),
        "protected_inputs": [
            {"path": path, "sha256": digest, "size_bytes": (ROOT / path).stat().st_size}
            for path, digest in before.items()
        ],
        "source_verifier_artifacts": [
            {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in SOURCE_VERIFIER_ARTIFACTS
        ],
        "generator": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "outputs": [
            {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in OUTPUTS if path != MANIFEST_OUTPUT
        ],
        "protected_artifact_changes": [],
        "R1_rerun_authorized": True,
        "R2_authorized": False,
        "next_step": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_RERUN",
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    append_log()
    print("R0_POPULATION_ERRATUM_PUBLISHED")
    print("CORRECTED R1 PRIMARY: 64 units / 6280 rows")
    print("R1 SECONDARY: 200 verifier-v2 rows")
    print("TOTAL BOUND: 6480 rows")
    print("SCIENTIFIC METHOD CHANGED: NO")
    print("NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_RERUN")


if __name__ == "__main__":
    run(parse_args())
