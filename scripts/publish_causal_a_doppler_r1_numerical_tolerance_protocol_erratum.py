#!/usr/bin/env python3
"""Publish the append-only R1 historical reproduction tolerance erratum."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_causal_a_doppler_reconstruction_reproduction_validation_rerun as r1  # noqa: E402

METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
DATASETS = ROOT / "outputs" / "datasets"
LOG = ROOT / "logs" / "work_log.md"

R0_PROTOCOL = METRICS / "doppler_semantic_reconstruction_protocol.json"
R0_MANIFEST = METRICS / "doppler_semantic_reconstruction_manifest.json"
POP_ERRATUM = METRICS / "doppler_semantic_reconstruction_r0_population_erratum_manifest.json"
R1_FAILURE = METRICS / "causal_a_doppler_r1_rerun_manifest.json"
R1_FAILURE_REPORT = REPORTS / "causal_a_doppler_reconstruction_reproduction_validation_rerun_report.md"
ROOT_CAUSE = METRICS / "causal_a_doppler_r1_numerical_divergence_manifest.json"
ROOT_CAUSE_REPORT = REPORTS / "causal_a_doppler_r1_level4_numerical_divergence_root_cause_audit.md"
HP = METRICS / "causal_a_doppler_r1_high_precision_reference.csv"
ULP = METRICS / "causal_a_doppler_r1_geometry_ulp_audit.csv"
PROP = METRICS / "causal_a_doppler_r1_error_propagation_audit.csv"
PATH_COMPARE = METRICS / "causal_a_doppler_r1_implementation_path_comparison.csv"
R1_FIT = METRICS / "causal_a_doppler_r1_rerun_fit_score_reproduction.csv"
INITIAL_SERIES = DATASETS / "doppler_verifier_orbit_similarity_attack_dataset.csv"
ACTIVE_SERIES = DATASETS / "active_compensation_first_pass_dataset.csv"
FROZEN_PARAMETER = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
BRIDGE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
CORRECTED_POPULATION = METRICS / "doppler_semantic_reconstruction_r1_corrected_population_binding.csv"

REPORT = REPORTS / "causal_a_doppler_r1_numerical_tolerance_protocol_erratum.md"
DERIVATION = METRICS / "causal_a_doppler_r1_numerical_tolerance_bound_derivation.csv"
ERRATUM = METRICS / "causal_a_doppler_r1_numerical_tolerance_erratum.csv"
MANIFEST = METRICS / "causal_a_doppler_r1_numerical_tolerance_erratum_manifest.json"
EFFECTIVE = METRICS / "causal_a_doppler_r1_effective_reproduction_tolerances.json"
OUTPUTS = [REPORT, DERIVATION, ERRATUM, EFFECTIVE, MANIFEST]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def decimal_digits(path: Path, columns: list[str]) -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(path, usecols=columns, dtype=str, keep_default_na=False)
    output: dict[str, dict[str, Any]] = {}
    for column in columns:
        digits = frame[column].str.partition(".")[2].str.len()
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(np.float64)
        output[column] = {
            "decimal_digits_min": int(digits.min()), "decimal_digits_median": float(digits.median()),
            "decimal_digits_max": int(digits.max()), "dtype_after_reload": str(values.dtype),
            "spacing_min": float(np.spacing(values).min()), "spacing_median": float(np.median(np.spacing(values))),
            "spacing_max": float(np.spacing(values).max()), "magnitude_min": float(values.min()),
            "magnitude_max": float(values.max()),
        }
    return output


def time_grid_gains() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for family, path, id_col, time_col in [
        ("score_only_verifier_and_synthetic_orbit_attacks", INITIAL_SERIES, "attack_sequence_id", "t_rel_s"),
        ("active_compensation_first_pass", ACTIVE_SERIES, "sequence_id", "t_rel_s"),
    ]:
        frame = pd.read_csv(path, usecols=[id_col, time_col])
        seen: set[tuple[int, bytes]] = set()
        for _, group in frame.groupby(id_col, sort=False):
            t = group[time_col].to_numpy(np.float64)
            signature = (len(t), t.tobytes())
            if signature in seen:
                continue
            seen.add(signature)
            x = t - float(np.mean(t))
            rows.append({
                "experiment_family": family, "point_count": len(t), "time_start_s": float(t.min()),
                "time_end_s": float(t.max()), "time_grid_dtype": str(t.dtype),
                "intercept_linf_operator_norm": float(np.sum(np.abs(np.ones_like(x) / len(x)))),
                "slope_linf_operator_norm_s_inverse": float(np.sum(np.abs(x)) / np.sum(x * x)),
            })
    return pd.DataFrame(rows)


def ceil_to(value: float, quantum: float) -> float:
    return float(math.ceil(value / quantum - 1e-15) * quantum)


def main() -> None:
    args = parse_args()
    required = [R0_PROTOCOL, R0_MANIFEST, POP_ERRATUM, CORRECTED_POPULATION, R1_FAILURE,
                R1_FAILURE_REPORT, ROOT_CAUSE, ROOT_CAUSE_REPORT, HP, ULP, PROP, PATH_COMPARE,
                R1_FIT, INITIAL_SERIES, ACTIVE_SERIES, FROZEN_PARAMETER, BRIDGE]
    missing = [rel(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative artifact: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not args.overwrite:
        raise SystemExit("Erratum output exists; refusing overwrite: " + ", ".join(existing))
    before = {rel(path): sha(path) for path in required}

    protocol = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    old = r1.numeric_tolerances(protocol)
    r1_failure = json.loads(R1_FAILURE.read_text(encoding="utf-8"))
    cause = json.loads(ROOT_CAUSE.read_text(encoding="utf-8"))
    if r1_failure.get("status") != "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED":
        raise SystemExit("R1 failure manifest status changed")
    if cause.get("status") != "R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC":
        raise SystemExit("Root-cause audit does not justify a tolerance decision")
    if cause.get("formula_audit", {}).get("root_cause_class") != "HISTORICAL_SERIALIZATION_QUANTIZATION":
        raise SystemExit("Root-cause classification is not frozen serialization quantization")
    if not cause.get("all_categorical_mismatches_zero"):
        raise SystemExit("Categorical exact-match prerequisite failed")

    serial_initial = decimal_digits(INITIAL_SERIES, ["f_geo_claimed_A_hz", "f_geo_attack_B_hz", "f_obs_attack_hz"])
    serial_active = decimal_digits(ACTIVE_SERIES, ["f_geo_A_S_hz", "f_geo_B_S_hz", "f_geo_A_C_hz", "f_geo_B_C_hz", "u_comp_hz", "delta_to_claimed_hz"])
    geometry_stats = [serial_initial[k] for k in ["f_geo_claimed_A_hz", "f_geo_attack_B_hz"]]
    geometry_stats += [serial_active[k] for k in ["f_geo_A_S_hz", "f_geo_B_S_hz", "f_geo_A_C_hz", "f_geo_B_C_hz"]]
    spacing_min = min(row["spacing_min"] for row in geometry_stats)
    spacing_median = float(np.median([row["spacing_median"] for row in geometry_stats]))
    spacing_max = max(row["spacing_max"] for row in geometry_stats)
    if not spacing_min == spacing_median == spacing_max:
        raise SystemExit("R1 geometry is not on one float64 ULP scale; fixed-bound decision invalid")

    # Independent bounds: no observed R1 difference participates in these expressions.
    # The historical value and reconstructed value each cross a float64
    # representation boundary, so use one ULP per side (two ULPs total).
    geometry_floor = 2.0 * spacing_max
    geometry_bound = geometry_floor
    geometry_proposed = ceil_to(geometry_bound, 1e-7)
    comp_spacing = serial_active["u_comp_hz"]["spacing_max"]
    compensation_bound = 2.0 * geometry_bound + 2.0 * comp_spacing
    compensation_proposed = ceil_to(compensation_bound, 1e-6)
    residual_local_spacing = serial_active["delta_to_claimed_hz"]["spacing_max"]
    residual_bound = 2.0 * geometry_bound + compensation_bound + 2.0 * residual_local_spacing
    residual_proposed = ceil_to(residual_bound, 1e-6)
    grids = time_grid_gains()
    b_bound = residual_proposed * float(grids.intercept_linf_operator_norm.max())
    b_proposed = ceil_to(b_bound, 1e-6)
    k_bound = residual_proposed * float(grids.slope_linf_operator_norm_s_inverse.max())
    # Fixed 1e-8 Hz/s quantum keeps this bound tight without using observed
    # R1 errors to choose a scale.
    k_proposed = ceil_to(k_bound, 1e-8)
    score_bound = residual_proposed
    score_proposed = ceil_to(score_bound, 1e-6)

    fit = pd.read_csv(R1_FIT)
    observed = {
        "geometry": float(r1_failure["maximum_errors"]["Doppler_hz"]),
        "compensation": float(r1_failure["maximum_errors"]["compensation_hz"]),
        "residual": float(r1_failure["maximum_errors"]["residual_hz"]),
        "b_hat": float(r1_failure["maximum_errors"]["b_hat_hz"]),
        "k_hat": float(r1_failure["maximum_errors"]["k_hat_hz_s"]),
        "score": float(r1_failure["maximum_errors"]["score_hz"]),
    }

    derivation_rows: list[dict[str, Any]] = []
    for family, artifact, data in [
        ("score_only_verifier_and_synthetic_orbit_attacks", INITIAL_SERIES, serial_initial),
        ("active_compensation_first_pass", ACTIVE_SERIES, serial_active),
    ]:
        for quantity, stats in data.items():
            derivation_rows.append({
                "record_type": "SERIALIZATION_AUDIT", "experiment_family": family,
                "quantity": quantity, "source_artifact": rel(artifact), "artifact_type": "CSV",
                "serialization_format": "pandas.to_csv default shortest round-trip decimal",
                "parser": "pandas.read_csv", **stats, "bound_construction_uses_observed_R1_max": False,
            })
    for row in grids.to_dict("records"):
        derivation_rows.append({"record_type": "OLS_TIME_GRID_OPERATOR", **row,
                                "bound_construction_uses_observed_R1_max": False})
    bound_specs = [
        ("geometry", geometry_bound, geometry_proposed, "2*full-frequency float64 ULPs: one representation boundary per compared value"),
        ("compensation", compensation_bound, compensation_proposed, "2*geometry_bound + 2*spacing(u_C magnitude)"),
        ("observation_and_residual", residual_bound, residual_proposed, "2*geometry_bound + compensation_bound + 2*spacing(residual magnitude)"),
        ("b_hat", b_bound, b_proposed, "residual_proposed * max centered-OLS intercept L_inf operator norm"),
        ("k_hat", k_bound, k_proposed, "residual_proposed * max centered-OLS slope L_inf operator norm"),
        ("score", score_bound, score_proposed, "RMSE 1-Lipschitz bound from residual_proposed"),
    ]
    for quantity, bound, proposed, rule in bound_specs:
        validation_key = "residual" if quantity == "observation_and_residual" else quantity
        derivation_rows.append({
            "record_type": "INDEPENDENT_BOUND", "quantity": quantity,
            "independent_numerical_floor": geometry_bound if quantity == "geometry" else math.nan,
            "derived_conservative_bound": bound, "proposed_reproduction_tolerance": proposed,
            "derivation_rule": rule, "observed_R1_max_validation_only": observed.get(validation_key, math.nan),
            "observed_within_proposed": observed.get(validation_key, 0.0) <= proposed,
            "bound_construction_uses_observed_R1_max": False,
        })
    derivation = pd.DataFrame(derivation_rows)

    effective = {
        "protocol_name": "CAUSAL_A_DOPPLER_R1_EFFECTIVE_HISTORICAL_REPRODUCTION_TOLERANCES_V2",
        "status": "R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED",
        "scope": "HISTORICAL_SERIALIZED_ARTIFACT_REPRODUCTION_ONLY",
        "authoritative_composition": [rel(R0_PROTOCOL), rel(POP_ERRATUM), rel(MANIFEST)],
        "scientific_method_changed": False, "verifier_behavior_changed": False,
        "population_changed": False, "categorical_match_requirement": "EXACT_ZERO_MISMATCH",
        "tolerances": {
            "evaluation_time_and_time_grid_s": old["time"],
            "A_position_km": old["A_position"], "A_velocity_km_s": old["A_velocity"],
            "B_position_km": old["B_position"], "B_velocity_km_s": old["B_velocity"],
            "Doppler_geometry_hz": geometry_proposed,
            "active_compensation_hz": compensation_proposed,
            "observation_and_raw_residual_hz": residual_proposed,
            "b_hat_hz": b_proposed, "k_hat_hz_per_s": k_proposed, "score_hz": score_proposed,
        },
        "dynamic_rule_rejected": "All bound R1 geometry values share one GHz-scale spacing; fixed bounds are simpler and auditable.",
        "observed_results_used_to_construct_bounds": False,
        "R2_authorized": False,
        "next_step": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN",
    }

    erratum_rows = [
        ("evaluation_time_and_time_grid", old["time"], old["time"], "KEEP", "exact time grid policy unchanged"),
        ("A_position", old["A_position"], old["A_position"], "KEEP", "state reconstruction already exact"),
        ("A_velocity", old["A_velocity"], old["A_velocity"], "KEEP", "state reconstruction already exact"),
        ("B_position", old["B_position"], old["B_position"], "KEEP", "state reconstruction already exact"),
        ("B_velocity", old["B_velocity"], old["B_velocity"], "KEEP", "state reconstruction already exact"),
        ("Doppler_geometry", old["geometry"], geometry_proposed, "ERRATUM_REQUIRED", "one GHz-scale float64 ULP exceeds old absolute tolerance"),
        ("active_compensation_curve", old["compensation"], compensation_proposed, "ERRATUM_REQUIRED", "two geometry terms plus subtraction rounding"),
        ("observation_and_raw_residual", old["residual"], residual_proposed, "ERRATUM_REQUIRED", "geometry and compensation propagation"),
        ("b_hat", old["b_score"], b_proposed, "ERRATUM_REQUIRED", "centered-OLS intercept operator bound"),
        ("k_hat", old["k"], k_proposed, "ERRATUM_REQUIRED", "centered-OLS slope operator bound"),
        ("score", old["b_score"], score_proposed, "ERRATUM_REQUIRED", "RMSE Lipschitz bound"),
        ("categorical_gates_and_final_decision", 0.0, 0.0, "KEEP", "exact zero-mismatch requirement"),
    ]
    erratum = pd.DataFrame(erratum_rows, columns=["quantity", "old_tolerance", "proposed_reproduction_tolerance", "decision", "derivation_summary"])
    erratum["scientific_effect"] = "NONE"
    erratum["scope"] = "HISTORICAL_REPRODUCTION_ONLY"
    erratum["bound_construction_uses_observed_R1_max"] = False

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    DERIVATION.parent.mkdir(parents=True, exist_ok=True)
    derivation.to_csv(DERIVATION, index=False, encoding="utf-8-sig")
    erratum.to_csv(ERRATUM, index=False, encoding="utf-8-sig")
    EFFECTIVE.write_text(json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = f"""# R1 historical reproduction numerical tolerance protocol erratum

## 正式决定

`R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED`

本 erratum 仅修正 historical serialized artifact reproduction comparison。Scientific/production thresholds、verifier、b/k gates、coverage、ACCEPT/REJECT 和 population 均不变。R1 尚未重新执行，R2 仍不授权。

## 1. Independent numerical floor

全部 direct R1 GHz geometry 的 float64 spacing：min={spacing_min:.16g} Hz，median={spacing_median:.16g} Hz，max={spacing_max:.16g} Hz。historical CSV 使用 pandas shortest round-trip decimal，reload dtype=float64。历史值与重建值各经历一个 float64 表示边界，因此比较界限采用两端各一 ULP 的保守 floor `{geometry_bound:.16g} Hz`，不是由 observed R1 maximum 构造。

## 2. Bound propagation

- Geometry bound `{geometry_bound:.16g}` Hz；固定 reproduction tolerance `{geometry_proposed:.16g}` Hz。
- Compensation bound `{compensation_bound:.16g}` Hz，来自两个 geometry bound 与 subtraction rounding；tolerance `{compensation_proposed:.16g}` Hz。
- Observation/residual bound `{residual_bound:.16g}` Hz；tolerance `{residual_proposed:.16g}` Hz。
- b_hat bound `{b_bound:.16g}` Hz；tolerance `{b_proposed:.16g}` Hz。
- k_hat bound `{k_bound:.16g}` Hz/s；tolerance `{k_proposed:.16g}` Hz/s。
- Score bound `{score_bound:.16g}` Hz；tolerance `{score_proposed:.16g}` Hz。

Observed R1 maxima 仅用于验证 proposed bounds 能覆盖已观察值，未参与任何公式。完整推导见 `{rel(DERIVATION)}`。

## 3. Fixed vs ULP-aware

A fixed absolute bound 最适合本 population：所有 geometry 值位于同一 GHz exponent bin，spacing 完全相同。Dynamic ULP rule 同样可行，但增加实现复杂度；hybrid 对当前 population 没有额外收益。因此采用可直接审计的 fixed per-quantity tolerances，不采用统一 tolerance。

## 4. Quantity decisions

{erratum.to_markdown(index=False)}

State/time tolerances 保持原值。Geometry、compensation、observation/residual、b_hat、k_hat 和 score 只在 historical reproduction equivalence 中采用 derived bounds。Categorical gate/decision 继续要求 exact zero mismatch。

## 5. Evidence boundary

High-precision evidence 仍只覆盖 30 个 direct-family failing samples，没有补造 10 个 passing samples。Tolerance decision 的主要依据是 serialization/ULP 与 deterministic operator-norm proof，而非 sample representativeness。

## 6. Formal status

`R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED`

SCIENTIFIC METHOD CHANGED: `NO`

VERIFIER BEHAVIOR CHANGED: `NO`

POPULATION CHANGED: `NO`

CATEGORICAL MATCH REQUIREMENT: `UNCHANGED / EXACT ZERO MISMATCH`

R2 AUTHORIZED: `NO`

NEXT STEP: `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN`
"""
    REPORT.write_text(report, encoding="utf-8")

    after = {rel(path): sha(path) for path in required}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        raise SystemExit("Protected artifact changed: " + ", ".join(changed))
    manifest = {
        "stage": "R1_NUMERICAL_TOLERANCE_PROTOCOL_ERRATUM_DECISION",
        "status": "R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED",
        "eligibility": {"same_scientific_formulas": True, "same_states_and_inputs": True,
                        "serialization_quantization_fully_explains_difference": True,
                        "bounds_independent_of_observed_max": True, "categorical_decisions_unchanged": True,
                        "reproduction_scope_only": True},
        "scientific_method_changed": False, "scientific_threshold_changed": False,
        "verifier_behavior_changed": False, "population_changed": False,
        "categorical_match_requirement": "UNCHANGED_EXACT_ZERO_MISMATCH",
        "R1_rerun_performed": False, "R2_authorized": False,
        "next_step": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN",
        "geometry_spacing_hz": {"min": spacing_min, "median": spacing_median, "max": spacing_max},
        "effective_tolerances": effective["tolerances"],
        "protected_artifact_changes": changed,
        "bound_sources": [{"path": rel(path), "sha256": before[rel(path)]} for path in required],
        "generator": {"path": rel(Path(__file__)), "sha256": sha(Path(__file__))},
        "outputs": [{"path": rel(path), "sha256": sha(path), "size_bytes": path.stat().st_size}
                    for path in [REPORT, DERIVATION, ERRATUM, EFFECTIVE]],
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n## {now} - R1 numerical tolerance protocol erratum decision\n\n### A. 本轮目标\n决定是否仅为 historical-artifact reproduction 发布 numerical tolerance erratum。\n\n### B. 实际操作\n审计 historical CSV serialization/dtype/spacing；从两端各一 ULP 的 geometry floor、compensation/residual arithmetic 和 centered-OLS operator norms 独立推导 bounds。Observed R1 maxima 仅用于验证，没有进入 bound 构造。\n\n### C. 新增/修改文件\n新增 `{rel(REPORT)}`、`{rel(DERIVATION)}`、`{rel(ERRATUM)}`、`{rel(EFFECTIVE)}`、`{rel(MANIFEST)}`；protected artifacts 未修改。\n\n### D. 结果摘要\n`R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED`；erratum eligibility=`NUMERICAL_TOLERANCE_ERRATUM_JUSTIFIED`。仅 reproduction tolerances 变更；scientific method/verifier behavior/population 不变；categorical exact-zero mismatch 不变；R2=NO。\n\n### E. 下一步\n`CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN`；本轮未自动执行。\n")
    print("R1_NUMERICAL_TOLERANCE_ERRATUM_PUBLISHED")
    print("SCIENTIFIC METHOD CHANGED: NO")
    print("VERIFIER BEHAVIOR CHANGED: NO")
    print("POPULATION CHANGED: NO")
    print("CATEGORICAL MATCH REQUIREMENT: UNCHANGED / EXACT ZERO MISMATCH")
    print("R2 AUTHORIZED: NO")
    print("NEXT STEP: CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_FINAL_RERUN")


if __name__ == "__main__":
    main()
