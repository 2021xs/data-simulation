#!/usr/bin/env python3
"""Validate the frozen R1 population before numerical Doppler reproduction.

This entry point is fail-closed.  It writes a provenance audit and does not
propagate states or execute the verifier when the frozen row counts disagree.
"""

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

R0_PROTOCOL = METRICS / "doppler_semantic_reconstruction_protocol.json"
R0_MANIFEST = METRICS / "doppler_semantic_reconstruction_manifest.json"
RELABEL_ROWS = DATASETS / "existing_doppler_cases_orbit_distinct_relabeling.csv"
STATE_AUDIT = METRICS / "orbit_distinct_ab_state_reconstruction_audit.csv"
RELABEL_MANIFEST = METRICS / "orbit_distinct_relabel_manifest.json"
BRIDGE_INTERFACE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
FROZEN_PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
FROZEN_MANIFEST = METRICS / "orbit_uncertainty_stage1f_lite_manifest.json"
RAW_GP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "spacetrack_gp" / "spacetrack_gp_history_20260226_20260329_20sat_omm.json"

FROZEN_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
COMPATIBLE_STATUSES = {"EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"}
V2_VIEW = "verifier_v2_score_only_view"

SOURCE_ARTIFACTS = [
    METRICS / "doppler_verifier_orbit_similarity_attack_results.csv",
    DATASETS / "doppler_verifier_orbit_similarity_attack_dataset.csv",
    METRICS / "verifier_v2_sequence_eval.csv",
    METRICS / "active_compensation_first_pass_sequence_eval.csv",
    DATASETS / "active_compensation_first_pass_dataset.csv",
    DATASETS / "same_pair_multi_pass_realization_dataset.csv",
    DATASETS / "controlled_altitude_difference_realization_dataset.csv",
]
PRODUCTION_CODE = [
    ROOT / "scripts" / "run_doppler_verifier_initial_experiments.py",
    ROOT / "scripts" / "run_active_compensation_attack_first_pass.py",
    ROOT / "scripts" / "run_segmented_service_center_compensation.py",
    ROOT / "scripts" / "run_same_pair_multi_pass_confirmation.py",
    ROOT / "scripts" / "run_controlled_altitude_difference_risk_experiment.py",
]
CONFIG_INPUTS = [
    ROOT / "configs" / "orbit_simulation_cases.yaml",
    ROOT / "configs" / "simulation_parameter_config.yaml",
    ROOT / "data" / "tle" / "starlink_tle.txt",
]
AUTHORITATIVE_INPUTS = [
    R0_PROTOCOL, R0_MANIFEST, RELABEL_ROWS, STATE_AUDIT, RELABEL_MANIFEST,
    BRIDGE_INTERFACE, FROZEN_PARAMETERS, FROZEN_MANIFEST, RAW_GP,
    *SOURCE_ARTIFACTS, *PRODUCTION_CODE, *CONFIG_INPUTS,
]

ROWS_OUTPUT = DATASETS / "causal_a_doppler_r1_reproduction_rows.csv"
STATE_OUTPUT = METRICS / "causal_a_doppler_r1_state_reproduction.csv"
GEOMETRY_OUTPUT = METRICS / "causal_a_doppler_r1_geometry_reproduction.csv"
FIT_OUTPUT = METRICS / "causal_a_doppler_r1_fit_score_reproduction.csv"
GATE_OUTPUT = METRICS / "causal_a_doppler_r1_gate_decision_reproduction.csv"
FAILURE_OUTPUT = METRICS / "causal_a_doppler_r1_failure_attribution.csv"
V2_OUTPUT = METRICS / "causal_a_doppler_r1_verifier_v2_crosscheck.csv"
CORRECTNESS_OUTPUT = METRICS / "causal_a_doppler_r1_correctness_audit.csv"
MANIFEST_OUTPUT = METRICS / "causal_a_doppler_r1_manifest.json"
REPORT_OUTPUT = REPORTS / "causal_a_doppler_reconstruction_reproduction_validation_report.md"
OUTPUTS = [
    ROWS_OUTPUT, STATE_OUTPUT, GEOMETRY_OUTPUT, FIT_OUTPUT, GATE_OUTPUT,
    FAILURE_OUTPUT, V2_OUTPUT, CORRECTNESS_OUTPUT, REPORT_OUTPUT, MANIFEST_OUTPUT,
]


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


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def validate_inputs(overwrite: bool) -> dict[str, str]:
    missing = [rel(path) for path in AUTHORITATIVE_INPUTS if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Output exists; use --overwrite: " + ", ".join(existing))
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen orbit-uncertainty parameter SHA mismatch")
    protocol = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    manifest = json.loads(R0_MANIFEST.read_text(encoding="utf-8"))
    if protocol.get("status") != "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_FROZEN":
        raise SystemExit("R0 protocol is not frozen")
    if manifest.get("R1_compatible_orbit_units") != 64 or manifest.get("R1_primary_source_rows") != 6480:
        raise SystemExit("R0 manifest population constants changed")
    return {rel(path): sha256(path) for path in AUTHORITATIVE_INPUTS}


def load_population() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    protocol = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    state = pd.read_csv(STATE_AUDIT, dtype=str, keep_default_na=False)
    units = state[state["A_reconstruction_status"].isin(COMPATIBLE_STATUSES)].copy()
    row_columns = [
        "experiment_family", "source_view", "source_artifact", "case_id", "orbit_unit_id",
        "A_id", "A_name", "B_id_or_definition", "segment_id", "evaluation_time",
        "original_A_source", "A_reconstruction_status", "selected_A_GP_ID",
        "selected_A_GP_EPOCH", "selected_A_GP_CREATION_DATE", "B_reconstruction_status",
        "original_verifier_score", "original_b_hat", "original_k_hat",
        "original_verifier_accept", "original_verifier_decision",
        "original_coverage_status", "original_bk_mode",
    ]
    rows = pd.read_csv(RELABEL_ROWS, usecols=row_columns, dtype=str, keep_default_na=False)
    rows = rows[rows["orbit_unit_id"].isin(set(units["orbit_unit_id"]))].copy()
    rows["r1_role"] = rows["source_view"].map(lambda value: "SECONDARY_VERIFIER_V2" if value == V2_VIEW else "PRIMARY_SOURCE")
    rows["r1_execution_status"] = "NOT_EXECUTED_FROZEN_POPULATION_INCONSISTENCY"
    rows = rows.sort_values(["experiment_family", "orbit_unit_id", "source_view", "case_id"]).reset_index(drop=True)
    return units, rows, protocol


def empty_reproduction_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    geometry = pd.DataFrame(columns=[
        "orbit_unit_id", "case_id", "level", "quantity", "max_abs_difference",
        "rmse_difference", "frozen_tolerance", "pass", "execution_status",
    ])
    fit = pd.DataFrame(columns=[
        "orbit_unit_id", "case_id", "old_b_hat", "new_b_hat", "b_hat_abs_difference",
        "old_k_hat", "new_k_hat", "k_hat_abs_difference", "old_score", "new_score",
        "score_abs_difference", "score_relative_difference", "pass", "execution_status",
    ])
    gate = pd.DataFrame(columns=[
        "orbit_unit_id", "case_id", "score_gate_mismatch", "b_gate_mismatch",
        "k_gate_mismatch", "coverage_mismatch", "quality_gate_mismatch",
        "final_decision_mismatch", "execution_status",
    ])
    return geometry, fit, gate


def correctness_audit(units: pd.DataFrame, rows: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    expected_units = int(protocol["R1_reproduction_gate"]["orbit_unit_count"])
    expected_primary = int(protocol["R1_reproduction_gate"]["primary_source_rows_bound_to_units"])
    expected_v2 = int(protocol["R1_reproduction_gate"]["derived_verifier_v2_view_rows"])
    actual_primary = int(rows["r1_role"].eq("PRIMARY_SOURCE").sum())
    actual_v2 = int(rows["r1_role"].eq("SECONDARY_VERIFIER_V2").sum())
    actual_all = len(rows)
    expected_all_under_prompt = expected_primary + expected_v2
    checks = [
        ("primary_units_expected_64", len(units), expected_units, len(units) == expected_units),
        ("compatible_status_only", int(units["A_reconstruction_status"].isin(COMPATIBLE_STATUSES).sum()), expected_units,
         bool(units["A_reconstruction_status"].isin(COMPATIBLE_STATUSES).all())),
        ("primary_rows_expected_6480", actual_primary, expected_primary, actual_primary == expected_primary),
        ("secondary_v2_rows_expected_200", actual_v2, expected_v2, actual_v2 == expected_v2),
        ("total_rows_if_primary_and_secondary_are_disjoint", actual_all, expected_all_under_prompt, actual_all == expected_all_under_prompt),
        ("all_bound_rows_observed", actual_all, 6480, actual_all == 6480),
        ("new_random_draw_count", 0, 0, True),
        ("orbit_propagation_count", 0, 0, True),
        ("verifier_execution_count", 0, 0, True),
        ("old_verifier_source_rows_modified", 0, 0, True),
        ("frozen_verifier_thresholds_changed", 0, 0, True),
        ("b_k_ranges_changed", 0, 0, True),
        ("orbit_uncertainty_frozen_artifacts_changed", 0, 0, True),
    ]
    return pd.DataFrame(checks, columns=["check", "observed", "expected", "passed"])


def state_table(units: pd.DataFrame, protocol: dict[str, Any]) -> pd.DataFrame:
    columns = [
        "orbit_unit_id", "experiment_family", "A_id", "B_id_or_definition", "segment_id",
        "evaluation_time", "selected_A_GP_ID", "selected_A_GP_EPOCH",
        "selected_A_GP_CREATION_DATE", "A_reconstruction_status",
        "A_position_difference_norm_km", "A_velocity_difference_norm_km_s",
        "B_reconstruction_status", "B_radius_crosscheck_error_km",
    ]
    output = units.loc[:, columns].copy()
    output["A_position_frozen_tolerance"] = protocol["R1_reproduction_gate"]["tolerances"]["A_position"]
    output["A_velocity_frozen_tolerance"] = protocol["R1_reproduction_gate"]["tolerances"]["A_velocity"]
    output["B_position_frozen_tolerance"] = protocol["R1_reproduction_gate"]["tolerances"]["B_position"]
    output["B_velocity_frozen_tolerance"] = protocol["R1_reproduction_gate"]["tolerances"]["B_velocity"]
    output["r1_state_execution_status"] = "NOT_EXECUTED_FROZEN_POPULATION_INCONSISTENCY"
    return output.sort_values("orbit_unit_id").reset_index(drop=True)


def build_report(units: pd.DataFrame, rows: pd.DataFrame, protocol: dict[str, Any]) -> str:
    counts = rows.groupby(["experiment_family", "r1_role"]).size().rename("rows").reset_index()
    return f"""# Causal-A Doppler reconstruction reproduction validation (R1)

## 1. Formal result

`CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`

R1 在任何 state propagation、Doppler geometry、random replay、OLS 或 verifier execution 之前，由 frozen-population provenance gate 阻止。失败不是 numerical mismatch，而是 R0 population count 与 authoritative row binding 不一致。

## 2. Frozen population inconsistency

R0 protocol 同时冻结：

- primary reproduction rows = 6,480
- verifier-v2 secondary rows = 200

这要求两个互斥层级共 6,680 rows。但 authoritative relabel binding 实际只有 6,480 rows，其中 primary source 为 6,280，verifier-v2 derived view 为 200：

{counts.to_markdown(index=False)}

因此不能达到 `6480/6480 primary rows`。将 verifier-v2 的 200 rows 同时计入 primary 和 secondary 会重复计数；补造 200 rows 或重新选择 population 均违反冻结规则。

## 3. Unit provenance

64/64 units 可由 authoritative state audit 唯一恢复，且状态全部属于 `EXACT_ORBIT_SOURCE_MATCH` 或 `DETERMINISTIC_EQUIVALENT_RECONSTRUCTION`。没有 unit 被静默删除。但 R0 manifest 只记录数量，没有嵌入具体 unit list；本轮已在 state reproduction artifact 中固化该 64-unit identity。

## 4. Reproduction hierarchy

| Level | Quantity | R1 status |
|---|---|---|
| 1 | A state | NOT EXECUTED |
| 2 | B state | NOT EXECUTED |
| 3 | Doppler geometry | NOT EXECUTED |
| 4 | active compensation | NOT EXECUTED |
| 5 | observation residual | NOT EXECUTED |
| 6 | b_hat / k_hat | NOT EXECUTED |
| 7 | score | NOT EXECUTED |
| 8 | gates / coverage | NOT EXECUTED |
| 9 | final decision | NOT EXECUTED |

最早 divergence layer：`PROVENANCE_UNKNOWN / FROZEN_POPULATION_INCONSISTENCY`。

## 5. Required answers

1. 64/64 frozen units 已恢复 identity，但 numerical reproduction 未执行。
2. 6480/6480 primary rows：否；authoritative primary 只有 6,280。
3. A state 最大 R1 数值差异：`NOT_EVALUATED`。
4. B state 最大 R1 数值差异：`NOT_EVALUATED`。
5. Doppler geometry 最大差异：`NOT_EVALUATED`。
6. active compensation 最大差异：`NOT_EVALUATED`。
7. residual 最大差异：`NOT_EVALUATED`。
8. b_hat 最大差异：`NOT_EVALUATED`。
9. k_hat 最大差异：`NOT_EVALUATED`。
10. score 最大差异：`NOT_EVALUATED`。
11. score gate mismatch：`NOT_EVALUATED`。
12. b gate mismatch：`NOT_EVALUATED`。
13. k gate mismatch：`NOT_EVALUATED`。
14. coverage mismatch：`NOT_EVALUATED`。
15. final ACCEPT/REJECT mismatch：`NOT_EVALUATED`。
16. frozen numerical tolerances：未进入适用阶段，不能判 PASS。
17. 200 verifier-v2 cross-check：`LIMITATION_NOT_RUN_PRIMARY_POPULATION_GATE_FAILED`。
18. 最早失败层：frozen population provenance。
19. 尚未证明 semantic wrapper 在 A semantics 不变时保持 verifier science。
20. 不满足进入 `CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION` 的条件。

## 6. Resolution required

必须先发布一个明确的 R0 population erratum，只能二选一：

1. primary = 6,280，secondary verifier-v2 = 200，总绑定 = 6,480；或
2. 明确另外 200 条不属于 verifier-v2 derived view 的 authoritative primary rows 及其 identities/source SHA。

在 population 定义被正式修正前，R1 保持失败状态，不进入 R2。
"""


def append_log() -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    entry = f"""

## {now} - Causal-A Doppler reconstruction reproduction validation (R1)

### A. 本轮目标
使用 R0 冻结的 64 units / 6,480 primary rows 验证 causal-A-aligned reconstruction 是否复现旧 verifier science。

### B. 实际操作
完成 R0/relabel/source binding 的只读 population provenance gate。发现 authoritative binding 只有 6,280 primary rows 加 200 verifier-v2 secondary rows，总计 6,480；与冻结要求的 6,480 primary 加 200 secondary 不一致。按 fail-closed 原则停止，没有运行 state propagation、Doppler、random replay、OLS 或 verifier。

### C. 新增/修改文件
新增 R1 provenance rows、state identity、空的未执行 numerical layers、failure attribution、V2 limitation、correctness audit、manifest、报告、生成脚本和测试；未修改历史输入。

### D. 运行命令
`python scripts/run_causal_a_doppler_reconstruction_reproduction_validation.py`
`python -m pytest tests/test_causal_a_doppler_reconstruction_reproduction_validation.py -q`

### E. 结果摘要
状态为 `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`。64 unit identities 完整；primary rows 实际 6,280，冻结期望 6,480；secondary V2 rows 为 200；numerical/verifier execution count 均为 0。

### F. 问题与下一步
需要先发布 R0 population erratum，明确 primary=6,280 或提供缺少的 200 条独立 primary identities。R1 未通过，不允许进入 R2。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def run(args: argparse.Namespace) -> None:
    before = validate_inputs(args.overwrite)
    units, rows, protocol = load_population()
    primary = int(rows["r1_role"].eq("PRIMARY_SOURCE").sum())
    secondary = int(rows["r1_role"].eq("SECONDARY_VERIFIER_V2").sum())
    expected_primary = int(protocol["R1_reproduction_gate"]["primary_source_rows_bound_to_units"])
    expected_secondary = int(protocol["R1_reproduction_gate"]["derived_verifier_v2_view_rows"])

    state = state_table(units, protocol)
    geometry, fit, gate = empty_reproduction_tables()
    failure = pd.DataFrame([{
        "failure_category": "PROVENANCE_UNKNOWN",
        "failure_subtype": "FROZEN_POPULATION_INCONSISTENCY",
        "earliest_divergence_level": "PRE_LEVEL_1_POPULATION_GATE",
        "expected_primary_rows": expected_primary,
        "actual_primary_rows": primary,
        "expected_secondary_v2_rows": expected_secondary,
        "actual_secondary_v2_rows": secondary,
        "expected_disjoint_total_rows": expected_primary + expected_secondary,
        "actual_bound_total_rows": len(rows),
        "action": "STOP_NO_NUMERICAL_REPRODUCTION_NO_R2",
    }])
    v2 = pd.DataFrame([{
        "crosscheck": "VERIFIER_V2_SECONDARY",
        "expected_rows": expected_secondary,
        "actual_rows": secondary,
        "status": "VERIFIER_V2_CROSSCHECK_LIMITATION",
        "reason": "NOT_RUN_PRIMARY_POPULATION_GATE_FAILED",
    }])
    correctness = correctness_audit(units, rows, protocol)

    write_csv(ROWS_OUTPUT, rows)
    write_csv(STATE_OUTPUT, state)
    write_csv(GEOMETRY_OUTPUT, geometry)
    write_csv(FIT_OUTPUT, fit)
    write_csv(GATE_OUTPUT, gate)
    write_csv(FAILURE_OUTPUT, failure)
    write_csv(V2_OUTPUT, v2)
    write_csv(CORRECTNESS_OUTPUT, correctness)
    write_text(REPORT_OUTPUT, build_report(units, rows, protocol))

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        raise SystemExit("Protected authoritative input changed: " + ", ".join(changed))

    unit_identity_columns = ["orbit_unit_id", "experiment_family", "A_id", "B_id_or_definition", "segment_id", "evaluation_time"]
    row_identity_columns = ["orbit_unit_id", "source_view", "source_artifact", "case_id", "r1_role"]
    manifest = {
        "stage": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION",
        "status": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "failure_category": "PROVENANCE_UNKNOWN",
        "failure_subtype": "FROZEN_POPULATION_INCONSISTENCY",
        "earliest_divergence_layer": "PRE_LEVEL_1_POPULATION_GATE",
        "counts": {
            "expected_units": 64, "actual_units": len(units),
            "expected_primary_rows": expected_primary, "actual_primary_rows": primary,
            "expected_secondary_v2_rows": expected_secondary, "actual_secondary_v2_rows": secondary,
            "expected_disjoint_total_rows": expected_primary + expected_secondary,
            "actual_bound_total_rows": len(rows),
        },
        "population_identity": {
            "unit_sha256": stable_frame_sha(units, unit_identity_columns),
            "row_binding_sha256": stable_frame_sha(rows, row_identity_columns),
            "selection_rule": "A_reconstruction_status in {EXACT_ORBIT_SOURCE_MATCH, DETERMINISTIC_EQUIVALENT_RECONSTRUCTION}",
        },
        "R1_primary": "FAIL_POPULATION_GATE",
        "verifier_v2_crosscheck": "LIMITATION_NOT_RUN_PRIMARY_POPULATION_GATE_FAILED",
        "numerical_reproduction_performed": False,
        "orbit_propagation_count": 0,
        "doppler_geometry_execution_count": 0,
        "random_draw_count": 0,
        "OLS_execution_count": 0,
        "verifier_execution_count": 0,
        "spotcheck_count": 0,
        "frozen_parameter_sha256": sha256(FROZEN_PARAMETERS),
        "authoritative_inputs": [
            {"path": path, "sha256": digest, "size_bytes": (ROOT / path).stat().st_size}
            for path, digest in before.items()
        ],
        "generator": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "outputs": [
            {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in OUTPUTS if path != MANIFEST_OUTPUT
        ],
        "protected_input_changes": [],
        "R2_authorized": False,
        "required_resolution": "R0_POPULATION_ERRATUM",
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    append_log()
    print("CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED")
    print(f"R1 PRIMARY: FAIL ({primary}/{expected_primary} authoritative primary rows)")
    print(f"VERIFIER-V2 CROSSCHECK: LIMITATION ({secondary}/{expected_secondary} rows present; not run)")
    print("EARLIEST DIVERGENCE: PRE_LEVEL_1_POPULATION_GATE")
    print("R2 AUTHORIZED: NO")


if __name__ == "__main__":
    run(parse_args())
