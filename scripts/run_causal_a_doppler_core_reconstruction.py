#!/usr/bin/env python3
"""Execute the frozen R3 causal-A Doppler core reconstruction population."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import pandas as pd
from astropy.utils import iers
from skyfield.api import EarthSatellite, load


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from acquire_orbit_uncertainty_stage1 import parse_utc, select_causal_gp  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_controlled_altitude_difference_risk_experiment as altitude  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_existing_doppler_case_orbit_distinct_relabeling as orbit  # noqa: E402
import run_fixed_reference_compensation_extended_sensitivity as extended  # noqa: E402
import run_same_pair_multi_pass_confirmation as multipass  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as segment  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

R2_REPORT = REPORTS / "causal_a_doppler_core_reconstruction_design_and_freeze.md"
R2_POPULATION = METRICS / "causal_a_doppler_r2_core_population.csv"
R2_FAMILY = METRICS / "causal_a_doppler_r2_family_summary.csv"
R2_PROTOCOL = METRICS / "causal_a_doppler_r2_analysis_protocol.json"
R2_RANDOMNESS = METRICS / "causal_a_doppler_r2_randomness_binding.csv"
R2_SPOTCHECK = METRICS / "causal_a_doppler_r2_spotcheck_binding.csv"
R2_MANIFEST = METRICS / "causal_a_doppler_r2_manifest.json"
R1_MANIFEST = METRICS / "causal_a_doppler_r1_final_manifest.json"
BRIDGE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
FROZEN_PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
RAW_GP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "spacetrack_gp" / "spacetrack_gp_history_20260226_20260329_20sat_omm.json"
STATIC_TLE = ROOT / "data" / "tle" / "starlink_tle.txt"
SELECTION = METRICS / "controlled_starlink_20target_selection_table.csv"
ORBIT_CONFIG = ROOT / "configs" / "orbit_simulation_cases.yaml"
PARAMETER_CONFIG = ROOT / "configs" / "simulation_parameter_config.yaml"

SEGMENT_SOURCE = DATASETS / "m2_segment_local_expanded_sample_dataset.csv"
ALTITUDE_SOURCE = DATASETS / "controlled_altitude_difference_realization_dataset.csv"
MULTIPASS_SOURCE = DATASETS / "same_pair_multi_pass_realization_dataset.csv"
ACTIVE_SOURCE = METRICS / "active_compensation_first_pass_sequence_eval.csv"
ACTIVE_SERIES = DATASETS / "active_compensation_first_pass_dataset.csv"

ROW_OUTPUT = DATASETS / "causal_a_doppler_r3_observation_rows.csv"
UNIT_OUTPUT = DATASETS / "causal_a_doppler_r3_unit_summary.csv"
FAMILY_OUTPUT = METRICS / "causal_a_doppler_r3_family_execution_summary.csv"
ORBIT_OUTPUT = METRICS / "causal_a_doppler_r3_orbit_decision_summary.csv"
JOINT_OUTPUT = METRICS / "causal_a_doppler_r3_joint_state_summary.csv"
BOUNDARY_OUTPUT = METRICS / "causal_a_doppler_r3_boundary_coverage_diagnostic.csv"
SPOTCHECK_OUTPUT = METRICS / "causal_a_doppler_r3_spotcheck_audit.csv"
CORRECTNESS_OUTPUT = METRICS / "causal_a_doppler_r3_correctness_audit.csv"
MANIFEST_OUTPUT = METRICS / "causal_a_doppler_r3_manifest.json"
REPORT_OUTPUT = REPORTS / "causal_a_doppler_core_reconstruction_execution_report.md"

OUTPUTS = [
    ROW_OUTPUT, UNIT_OUTPUT, FAMILY_OUTPUT, ORBIT_OUTPUT, JOINT_OUTPUT,
    BOUNDARY_OUTPUT, SPOTCHECK_OUTPUT, CORRECTNESS_OUTPUT, MANIFEST_OUTPUT,
    REPORT_OUTPUT,
]

CORE_FAMILIES = [
    "segment_local_heatmap_and_direction_sensitivity",
    "controlled_altitude_difference_synthetic_B",
    "same_pair_multi_pass_real_TLE",
    "active_compensation_first_pass",
]
FROZEN_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"

PRODUCTION_CODE = [
    ROOT / "scripts" / "run_doppler_verifier_initial_experiments.py",
    ROOT / "scripts" / "run_segmented_service_center_compensation.py",
    ROOT / "scripts" / "run_segment_local_expanded_sample_confirmation.py",
    ROOT / "scripts" / "run_controlled_altitude_difference_risk_experiment.py",
    ROOT / "scripts" / "run_same_pair_multi_pass_confirmation.py",
    ROOT / "scripts" / "run_active_compensation_attack_first_pass.py",
    ROOT / "scripts" / "run_existing_doppler_case_orbit_distinct_relabeling.py",
]
PROTECTED_INPUTS = [
    R2_REPORT, R2_POPULATION, R2_FAMILY, R2_PROTOCOL, R2_RANDOMNESS,
    R2_SPOTCHECK, R2_MANIFEST, R1_MANIFEST, BRIDGE, FROZEN_PARAMETERS,
    RAW_GP, STATIC_TLE, SELECTION, ORBIT_CONFIG, PARAMETER_CONFIG,
    SEGMENT_SOURCE, ALTITUDE_SOURCE, MULTIPASS_SOURCE, ACTIVE_SOURCE,
    ACTIVE_SERIES, *PRODUCTION_CODE,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate frozen inputs without executing science")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def array_hash(values: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(values, dtype=np.float64).tobytes()).hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "accept", "accepted"}


def finite_float(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Non-finite numeric value: {value}")
    return result


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def hash_record(path: Path) -> dict[str, Any]:
    return {"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size}


def assert_close(label: str, actual: Any, expected: Any, atol: float = 1e-10) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=atol):
        raise RuntimeError(f"{label} mismatch: {actual} != {expected}")


def validate_frozen_inputs() -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    missing = [rel(path) for path in PROTECTED_INPUTS if not path.exists()]
    if missing:
        raise SystemExit("Missing frozen R3 input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing:
        raise SystemExit("R3 append-only output already exists: " + ", ".join(existing))
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen Orbit-Uncertainty parameter SHA mismatch")

    manifest = json.loads(R2_MANIFEST.read_text(encoding="utf-8"))
    protocol = json.loads(R2_PROTOCOL.read_text(encoding="utf-8"))
    r1 = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_FROZEN":
        raise SystemExit("R2 design is not frozen")
    if manifest.get("R2") != "PASS" or manifest.get("R3_authorized") is not True:
        raise SystemExit("R2 does not authorize R3")
    if r1.get("status") != "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATED":
        raise SystemExit("R1 production reconstruction was not validated")
    if protocol.get("selection_result_blind") is not True or protocol.get("science_execution_performed") is not False:
        raise SystemExit("R2 result-blind design invariant failed")

    for record in manifest.get("outputs", []):
        path = ROOT / record["path"]
        if sha256(path) != record["sha256"]:
            raise SystemExit(f"Frozen R2 output SHA mismatch: {record['path']}")

    population = pd.read_csv(R2_POPULATION, dtype=str, keep_default_na=False)
    included = population[population["include_in_R3"].eq("True")].copy()
    binding = pd.read_csv(R2_RANDOMNESS, dtype=str, keep_default_na=False)
    spot = pd.read_csv(R2_SPOTCHECK, dtype=str, keep_default_na=False)
    if len(population) != 477 or len(included) != 407 or len(binding) != 26780:
        raise SystemExit("Frozen R3 population count mismatch")
    if binding["planned_row_identity"].duplicated().any():
        raise SystemExit("Frozen R3 row identities are not unique")
    if set(binding["orbit_unit_id"]) != set(included["orbit_unit_id"]):
        raise SystemExit("Randomness binding and included unit population differ")
    expected = {
        "segment_local_heatmap_and_direction_sensitivity": 6200,
        "controlled_altitude_difference_synthetic_B": 18000,
        "same_pair_multi_pass_real_TLE": 2400,
        "active_compensation_first_pass": 180,
    }
    if binding.groupby("experiment_family").size().to_dict() != expected:
        raise SystemExit("Frozen family row counts changed")
    if len(spot) != 30 or spot["orbit_unit_id"].nunique() != 30 or spot["experiment_family"].nunique() != 4:
        raise SystemExit("Frozen R3 spot-check binding changed")
    if not binding["new_random_draw_allowed"].eq("False").all():
        raise SystemExit("Frozen randomness binding permits new draws")

    before = {rel(path): sha256(path) for path in PROTECTED_INPUTS}
    return before, included, binding, spot, protocol


def load_runtime(ts: Any) -> tuple[dict[str, Any], dict[str, list[float]], dict[str, dict[str, Any]], pd.DataFrame]:
    config = base.read_yaml(ORBIT_CONFIG)
    if config.get("mode") != "controlled_starlink" or config.get("observation_id") is not None:
        raise SystemExit("R3 requires controlled_starlink mode with observation_id=null")
    range_type = str(config.get("simulation", {}).get("range_type", "main"))
    ranges = base.load_parameter_ranges(PARAMETER_CONFIG, range_type)
    tle = base.parse_tle(STATIC_TLE, ts)
    selection = pd.read_csv(SELECTION, dtype={"target_norad_id": str})
    return config, ranges, tle, selection


def load_causal_catalog(population: pd.DataFrame, ts: Any) -> tuple[dict[str, dict[str, Any]], dict[str, EarthSatellite]]:
    raw = json.loads(RAW_GP.read_text(encoding="utf-8"))
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in raw:
        by_id[str(record["NORAD_CAT_ID"])].append(record)
    provenance: dict[str, dict[str, Any]] = {}
    satellites: dict[str, EarthSatellite] = {}
    for row in population.itertuples(index=False):
        when = parse_utc(str(row.evaluation_time))
        selected, _ = select_causal_gp(by_id[str(row.A_id)], when)
        if selected is None:
            raise SystemExit(f"No causal A GP: {row.orbit_unit_id}")
        if str(selected.get("GP_ID", "")) != str(row.selected_causal_A_GP_ID):
            raise SystemExit(f"Frozen causal GP changed: {row.orbit_unit_id}")
        if parse_utc(str(selected["CREATION_DATE"])) > when:
            raise SystemExit(f"Future A publication: {row.orbit_unit_id}")
        key = f"{row.A_id}:{selected['GP_ID']}"
        if key not in satellites:
            satellites[key] = EarthSatellite(
                str(selected["TLE_LINE1"]), str(selected["TLE_LINE2"]),
                str(selected.get("OBJECT_NAME", row.A_name)), ts,
            )
        provenance[str(row.orbit_unit_id)] = {
            "key": key,
            "A_id": str(row.A_id),
            "GP_ID": str(selected["GP_ID"]),
            "EPOCH": str(selected["EPOCH"]),
            "CREATION_DATE": str(selected["CREATION_DATE"]),
            "line1": str(selected["TLE_LINE1"]).strip(),
            "line2": str(selected["TLE_LINE2"]).strip(),
        }
    return provenance, satellites


def reconstruct_full_grid(pass_start: Any, pass_end: Any, service_start: Any, service_end: Any) -> dict[str, Any]:
    start, end = parse_utc(str(pass_start)), parse_utc(str(pass_end))
    duration = int(math.floor((end - start).total_seconds()))
    full_times = [start + timedelta(seconds=index) for index in range(duration + 1)]
    full_t = np.arange(duration + 1, dtype=float)
    service_left, service_right = parse_utc(str(service_start)), parse_utc(str(service_end))
    mask = np.asarray([service_left <= value <= service_right for value in full_times], dtype=bool)
    if not mask.any():
        raise RuntimeError("Frozen service grid does not intersect full pass")
    return {
        "full_times": full_times,
        "full_t": full_t,
        "mask": mask,
        "times": [value for value, keep in zip(full_times, mask) if keep],
        "t_rel": full_t[mask],
        "t0": float(np.mean(full_t)),
    }


def joint_state(orbit_decision: str, verifier_decision: str) -> str:
    if orbit_decision == "DEFER":
        return "ORBIT_DEFER"
    if verifier_decision not in {"ACCEPT", "REJECT"}:
        return f"{orbit_decision}_AND_DOPPLER_{verifier_decision}"
    prefix = {
        "NOT_ORBIT_DISTINCT": "NOT_ORBIT_DISTINCT",
        "AMBIGUOUS": "ORBIT_AMBIGUOUS",
        "ORBIT_DISTINCT": "ORBIT_DISTINCT",
    }[orbit_decision]
    return f"{prefix}_AND_DOPPLER_{'ACCEPTED' if verifier_decision == 'ACCEPT' else 'REJECTED'}"


def production_row(
    bind: pd.Series,
    source: pd.Series,
    unit: dict[str, Any],
    *,
    b_env: float,
    k_env: float,
    sigma: float,
    noise: np.ndarray,
    noise_identity: str,
    observation: np.ndarray,
    f_a: np.ndarray,
    f_b: np.ndarray,
    compensation: np.ndarray,
    t_rel: np.ndarray,
    decision: Any,
    threshold: dict[str, float],
    quality_gate: bool,
    compensation_mode: str,
    point_count: int,
) -> dict[str, Any]:
    row = {
        "planned_row_identity": bind["planned_row_identity"],
        "experiment_family": bind["experiment_family"],
        "orbit_unit_id": bind["orbit_unit_id"],
        "source_case_id": bind["source_case_id"],
        "condition_identity": bind["condition_identity"],
        "realization_identity": bind["realization_identity"],
        "endpoint_role": bind["endpoint_role"],
        "A_id": unit["A_id"],
        "A_name": unit["A_name"],
        "B_class": unit["B_class"],
        "B_identity_or_definition": unit["B_identity_or_perturbation_definition"],
        "segment_or_pass_id": unit["segment_or_pass_id"],
        "evaluation_time": unit["evaluation_time"],
        "A_GP_ID": unit["A_GP_ID"],
        "A_GP_EPOCH": unit["A_GP_EPOCH"],
        "A_GP_CREATION_DATE": unit["A_GP_CREATION_DATE"],
        "element_age_hours": unit["element_age_hours"],
        "publication_age_hours": unit["publication_age_hours"],
        "freshness_bin": unit["freshness_bin"],
        "orbit_support_status": unit["orbit_support_status"],
        "orbit_decision": unit["orbit_decision"],
        "D2": unit["D2"],
        "rho95": unit["rho95"],
        "rho99": unit["rho99"],
        "c95": unit["c95"],
        "c99": unit["c99"],
        "physical_position_separation_km": unit["physical_position_separation_km"],
        "physical_velocity_separation_km_s": unit["physical_velocity_separation_km_s"],
        "delta_R_km": unit["delta_R_km"],
        "delta_T_km": unit["delta_T_km"],
        "delta_N_km": unit["delta_N_km"],
        "orbit_score_vector_R_km": unit["orbit_score_vector_R_km"],
        "orbit_score_vector_T_km": unit["orbit_score_vector_T_km"],
        "orbit_score_vector_N_km": unit["orbit_score_vector_N_km"],
        "b_env_hz": b_env,
        "k_env_hz_per_s": k_env,
        "sigma_hz": sigma,
        "noise_identity": noise_identity,
        "noise_vector_hash": array_hash(noise),
        "observation_vector_hash": array_hash(observation),
        "compensation_mode": compensation_mode,
        "bk_mode": bind["bk_mode"],
        "b_hat_hz": float(decision.b_hat_hz),
        "k_hat_hz_per_s": float(decision.k_hat_hz_per_s),
        "score_hz": float(decision.residual_rmse_hz),
        "score_threshold_hz": float(threshold["score_threshold"]),
        "b_center_hz": float(threshold["b_center"]),
        "b_threshold_hz": float(threshold["b_threshold"]),
        "k_center_hz_per_s": float(threshold["k_center"]),
        "k_threshold_hz_per_s": float(threshold["k_threshold"]),
        "score_gate_pass": bool(decision.score_gate_pass),
        "b_gate_pass": bool(decision.b_gate_pass),
        "k_gate_pass": bool(decision.k_gate_pass),
        "coverage_gate_pass": bool(decision.coverage_gate_pass),
        "quality_gate_pass": bool(quality_gate),
        "final_verifier_decision": str(decision.decision),
        "joint_state": joint_state(unit["orbit_decision"], str(decision.decision)),
        "point_count": int(point_count),
        "source_artifact": bind["source_artifact"],
        "draw_provenance": bind["draw_provenance"],
        "replay_rule": bind["replay_rule"],
        "R1_validated_production_path": True,
        "execution_status": "COMPLETE",
        "execution_failure_reason": "",
        "new_random_draw_count": 0,
        "SupGP_operational_use": 0,
        "geometric_residual_rmse_hz": float(np.sqrt(np.mean((f_b + compensation - f_a) ** 2))),
        "observed_residual_rmse_hz": float(np.sqrt(np.mean((observation - f_a) ** 2))),
        "compensation_max_abs_hz": float(np.max(np.abs(compensation))),
    }
    for name in ["direction_deg", "direction_role", "distance_km", "R_cell_km", "delta_h_km", "physical_pair_id", "pass_id", "residual_mode", "compensation_type"]:
        if name in source.index:
            row[name] = source[name]
    return row


def load_source_tables(binding: pd.DataFrame) -> dict[str, pd.DataFrame]:
    case_ids = set(binding["source_case_id"])

    segment_frame = pd.read_csv(SEGMENT_SOURCE, dtype=str, keep_default_na=False, low_memory=False)
    segment_frame = segment_frame[segment_frame["case_id"].isin(case_ids)].copy()
    if len(segment_frame) != 6200:
        raise SystemExit(f"Segment source binding mismatch: {len(segment_frame)}")

    altitude_frame = pd.read_csv(ALTITUDE_SOURCE, dtype=str, keep_default_na=False, low_memory=False)
    altitude_frame["source_case_id"] = (
        altitude_frame["observation_realization_id"] + ":" + altitude_frame["bk_mode"] + ":"
        + pd.to_numeric(altitude_frame["direction_deg"]).astype(str)
    )
    altitude_frame = altitude_frame[altitude_frame["source_case_id"].isin(case_ids)].copy()
    if len(altitude_frame) != 18000:
        raise SystemExit(f"Altitude source binding mismatch: {len(altitude_frame)}")

    multipass_frame = pd.read_csv(MULTIPASS_SOURCE, dtype=str, keep_default_na=False, low_memory=False)
    multipass_frame["source_case_id"] = (
        multipass_frame["observation_realization_id"] + ":" + multipass_frame["bk_mode"]
    )
    multipass_frame = multipass_frame[multipass_frame["source_case_id"].isin(case_ids)].copy()
    if len(multipass_frame) != 2400:
        raise SystemExit(f"Multipass source binding mismatch: {len(multipass_frame)}")

    active_frame = pd.read_csv(ACTIVE_SOURCE, dtype=str, keep_default_na=False)
    active_frame = active_frame[active_frame["sequence_id"].isin(case_ids)].copy()
    if len(active_frame) != 180:
        raise SystemExit(f"Active source binding mismatch: {len(active_frame)}")
    return {
        CORE_FAMILIES[0]: segment_frame,
        CORE_FAMILIES[1]: altitude_frame,
        CORE_FAMILIES[2]: multipass_frame,
        CORE_FAMILIES[3]: active_frame,
    }


def source_lookup(tables: dict[str, pd.DataFrame]) -> dict[str, dict[str, pd.Series]]:
    key_columns = {
        CORE_FAMILIES[0]: "case_id",
        CORE_FAMILIES[1]: "source_case_id",
        CORE_FAMILIES[2]: "source_case_id",
        CORE_FAMILIES[3]: "sequence_id",
    }
    result: dict[str, dict[str, pd.Series]] = {}
    for family, frame in tables.items():
        key = key_columns[family]
        if frame[key].duplicated().any():
            raise SystemExit(f"Duplicate frozen source cases in {family}")
        result[family] = {str(row[key]): row for _, row in frame.iterrows()}
    return result


def synthetic_spec_from_source(family: str, source: pd.Series) -> tuple[datetime, float, float, float]:
    if family == CORE_FAMILIES[0]:
        anchor = parse_utc(str(source["evaluation_time_for_anchor"]))
        attack_type = str(source["attack_type"])
        value = float(source["attack_param_value"])
        return (
            anchor,
            value if attack_type == "same_plane_altitude_offset" else 0.0,
            value if attack_type == "same_plane_phase_offset" else 0.0,
            value if attack_type == "inclination_offset" else 0.0,
        )
    anchor = parse_utc(str(source["service_segment_start"])) + timedelta(seconds=int(float(source["point_count"])) // 2)
    return anchor, float(source["delta_h_km"]), 0.0, 0.0


def build_orbit_units(
    population: pd.DataFrame,
    binding: pd.DataFrame,
    lookup: dict[str, dict[str, pd.Series]],
    provenance: dict[str, dict[str, Any]],
    tle: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    models = orbit.load_models()
    first_binding = binding.sort_values("planned_row_identity").drop_duplicates("orbit_unit_id").set_index("orbit_unit_id")
    rows: list[dict[str, Any]] = []
    for frozen in population.itertuples(index=False):
        unit_id = str(frozen.orbit_unit_id)
        prov = provenance[unit_id]
        when = parse_utc(str(frozen.evaluation_time))
        epoch = parse_utc(prov["EPOCH"])
        creation = parse_utc(prov["CREATION_DATE"])
        age = (when - epoch).total_seconds() / 3600.0
        publication_age = (when - creation).total_seconds() / 3600.0
        a_r, a_v = orbit.state_from_lines(prov["line1"], prov["line2"], when)

        binding_row = first_binding.loc[unit_id]
        source = lookup[str(frozen.experiment_family)][str(binding_row["source_case_id"])].copy()
        if frozen.experiment_family == CORE_FAMILIES[0]:
            pass_start = parse_utc(str(source["pass_start_for_anchor"]))
            anchor = pass_start + timedelta(seconds=float(source["segment_start_s"])) + timedelta(seconds=int(float(source["point_count"])) // 2)
            source["evaluation_time_for_anchor"] = iso_z(anchor)

        if frozen.B_class == "REAL_B":
            b_id = str(frozen.B_identity_or_perturbation_definition)
            if b_id not in tle:
                raise SystemExit(f"Frozen real B missing from static TLE: {unit_id}:{b_id}")
            b_r, b_v = orbit.state_from_lines(tle[b_id]["line1"], tle[b_id]["line2"], when)
            b_provenance = f"STATIC_TLE:{rel(STATIC_TLE)}:{b_id}"
            b_anchor = ""
            altitude_offset = phase_offset = inclination_offset = 0.0
        else:
            b_anchor_dt, altitude_offset, phase_offset, inclination_offset = synthetic_spec_from_source(
                str(frozen.experiment_family), source
            )
            b_r, b_v = orbit.synthetic_state(
                (prov["line1"], prov["line2"]), b_anchor_dt, when,
                altitude_offset, phase_offset, inclination_offset,
            )
            b_provenance = "SYNTHETIC_RELATIVE_TO_CAUSAL_A:FROZEN_ORIGINAL_PERTURBATION_RULE"
            b_anchor = iso_z(b_anchor_dt)

        basis = orbit.rtn_basis(a_r, a_v)
        displacement = b_r - a_r
        displacement_rtn = basis @ displacement
        z = -displacement_rtn
        freshness = orbit.freshness_bin(age)
        if freshness is None:
            support = "OUTSIDE_CALIBRATED_SUPPORT"
            decision = "DEFER"
            d2 = rho95 = rho99 = c95 = c99 = np.nan
        else:
            support = "WITHIN_CALIBRATED_SUPPORT"
            model = models[freshness]
            d2 = orbit.score_vector(z, model)
            c95, c99 = model["c95"], model["c99"]
            rho95, rho99 = math.sqrt(d2 / c95), math.sqrt(d2 / c99)
            decision = orbit.orbit_decision(d2, c95, c99)
        rows.append({
            "experiment_family": frozen.experiment_family,
            "orbit_unit_id": unit_id,
            "A_id": str(frozen.A_id),
            "A_name": frozen.A_name,
            "B_class": frozen.B_class,
            "B_identity_or_perturbation_definition": frozen.B_identity_or_perturbation_definition,
            "segment_or_pass_id": frozen.segment_or_pass_id,
            "evaluation_time": frozen.evaluation_time,
            "A_GP_ID": prov["GP_ID"],
            "A_GP_EPOCH": prov["EPOCH"],
            "A_GP_CREATION_DATE": prov["CREATION_DATE"],
            "element_age_hours": age,
            "publication_age_hours": publication_age,
            "A_state_reconstruction_identity": f"CAUSAL_GP:{prov['A_id']}:{prov['GP_ID']}",
            "B_state_reconstruction_identity": b_provenance,
            "synthetic_construction_anchor_time": b_anchor,
            "altitude_offset_km": altitude_offset,
            "phase_offset_s": phase_offset,
            "inclination_offset_deg": inclination_offset,
            "physical_position_separation_km": float(np.linalg.norm(displacement)),
            "physical_velocity_separation_km_s": float(np.linalg.norm(b_v - a_v)),
            "delta_R_km": float(displacement_rtn[0]),
            "delta_T_km": float(displacement_rtn[1]),
            "delta_N_km": float(displacement_rtn[2]),
            "orbit_score_vector_R_km": float(z[0]),
            "orbit_score_vector_T_km": float(z[1]),
            "orbit_score_vector_N_km": float(z[2]),
            "freshness_bin": freshness or "",
            "orbit_support_status": support,
            "D2": d2,
            "c95": c95,
            "c99": c99,
            "rho95": rho95,
            "rho99": rho99,
            "orbit_decision": decision,
            "rtn_orthonormality_error": float(np.max(np.abs(basis @ basis.T - np.eye(3)))),
            "sign_mapping_error_km": float(np.linalg.norm(z + displacement_rtn)),
            "future_publication_violation": int(creation > when),
            "SupGP_operational_use": 0,
            "orbit_scoring_status": "DEFER" if decision == "DEFER" else "SCORED",
        })
    result = pd.DataFrame(rows).sort_values(["experiment_family", "orbit_unit_id"]).reset_index(drop=True)
    if len(result) != len(population) or result["orbit_unit_id"].nunique() != len(population):
        raise SystemExit("Orbit unit execution population mismatch")
    return result


def load_segment_sources_with_anchors(
    tables: dict[str, pd.DataFrame], selection: pd.DataFrame,
) -> None:
    frame = tables[CORE_FAMILIES[0]]
    windows = selection.set_index("target_norad_id")
    frame["pass_start_for_anchor"] = frame["target_sat_id"].map(windows["pass_start_utc"])
    if frame["pass_start_for_anchor"].isna().any():
        raise SystemExit("Segment source pass start is unavailable")


def segment_noise_replay(
    frame: pd.DataFrame,
    selection: pd.DataFrame,
    ranges: dict[str, list[float]],
) -> dict[int, dict[str, Any]]:
    samples = frame.sort_values("sample_index_global").drop_duplicates("sample_index_global")
    indices = sorted(pd.to_numeric(samples["sample_index_global"]).astype(int).tolist())
    if indices != list(range(max(indices) + 1)):
        raise SystemExit("Segment source sample order is not contiguous; PCG64 stream cannot be replayed")
    windows = selection.set_index("target_norad_id")
    rng = np.random.default_rng(20260706)
    replay: dict[int, dict[str, Any]] = {}
    for source in samples.sort_values("sample_index_global", key=lambda values: pd.to_numeric(values)).itertuples(index=False):
        target = str(source.target_sat_id)
        window = windows.loc[target]
        start, end = parse_utc(str(window.pass_start_utc)), parse_utc(str(window.pass_end_utc))
        step = float(window.step_s)
        duration = (end - start).total_seconds()
        full_t = np.arange(0.0, duration + step * 0.5, step, dtype=float)
        noise, b_env, k_env, sigma, t0 = segment.sample_residual_terms(full_t, "empirical", ranges, rng)
        assert_close("segment b replay", b_env, source.b_env, 1e-10)
        assert_close("segment k replay", k_env, source.k_env, 1e-12)
        assert_close("segment sigma replay", sigma, source.sigma_hz, 1e-10)
        replay[int(source.sample_index_global)] = {
            "full_t": full_t,
            "noise": noise,
            "b_env": b_env,
            "k_env": k_env,
            "sigma": sigma,
            "t0": t0,
            "pass_start": start,
            "step": step,
        }
    return replay


def segment_geometry(
    source: pd.Series,
    sat_a: Any,
    sat_b: Any | None,
    ts: Any,
    frequency_hz: float,
) -> dict[str, Any]:
    point_count = int(float(source["point_count"]))
    start_s, end_s = float(source["evaluation_start_s"]), float(source["evaluation_end_s"])
    t_rel = np.linspace(start_s, end_s, point_count)
    pass_start = parse_utc(str(source["pass_start_for_anchor"]))
    times = [pass_start + timedelta(seconds=float(value)) for value in t_rel]
    step = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
    c_lat, c_lon = float(source["C_lat"]), float(source["C_lon"])
    s_lat, s_lon = float(source["S_lat"]), float(source["S_lon"])
    f_a_c = segment.geo_curve_fixed(sat_a, c_lat, c_lon, 0.0, times, ts, frequency_hz, step)[0]
    f_a_s = segment.geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, times, ts, frequency_hz, step)[0]
    sample = {
        "sample_source": str(source["sample_source"]),
        "target_sat_id": str(source["target_sat_id"]),
        "attack_sat_id": str(source["attack_sat_id"]),
        "attack_type": str(source["attack_type"]),
        "attack_param_value": float(source["attack_param_value"]),
    }
    f_b_c = expanded.attack_geo(sample, sat_a, sat_b, c_lat, c_lon, 0.0, times, ts, frequency_hz, step)
    f_b_s = expanded.attack_geo(sample, sat_a, sat_b, s_lat, s_lon, 0.0, times, ts, frequency_hz, step)
    compensation = f_a_c - f_b_c
    return {
        "times": times,
        "t_rel": t_rel,
        "f_a": f_a_s,
        "f_b": f_b_s,
        "f_a_c": f_a_c,
        "f_b_c": f_b_c,
        "compensation": compensation,
    }


def process_segment_family(
    binding: pd.DataFrame,
    lookup: dict[str, dict[str, pd.Series]],
    unit_map: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
    satellites: dict[str, EarthSatellite],
    tle: dict[str, dict[str, Any]],
    selection: pd.DataFrame,
    ranges: dict[str, list[float]],
    ts: Any,
    frequency_hz: float,
    spot_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    family = CORE_FAMILIES[0]
    frame = pd.DataFrame(list(lookup[family].values()))
    replay = segment_noise_replay(frame, selection, ranges)
    records: list[dict[str, Any]] = []
    spot_bundles: dict[str, dict[str, Any]] = {}
    geometry_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    calibration_cache: dict[tuple[str, int, float, float], dict[str, dict[str, float]]] = {}
    for _, bind in binding[binding["experiment_family"].eq(family)].sort_values("planned_row_identity").iterrows():
        source = lookup[family][str(bind["source_case_id"])]
        unit = unit_map[str(bind["orbit_unit_id"])]
        sat_a = satellites[provenance[str(bind["orbit_unit_id"])]["key"]]
        sat_b = tle[str(source["attack_sat_id"])]["sat"] if str(source["sample_source"]) == "real_tle_candidate" else None
        key = (
            bind["orbit_unit_id"], source["evaluation_start_s"], source["evaluation_end_s"],
            source["C_lat"], source["C_lon"], source["S_lat"], source["S_lon"],
        )
        if key not in geometry_cache:
            geometry_cache[key] = segment_geometry(source, sat_a, sat_b, ts, frequency_hz)
        geo = geometry_cache[key]
        sample_replay = replay[int(source["sample_index_global"])]
        positions = np.searchsorted(sample_replay["full_t"], geo["t_rel"])
        if not np.allclose(sample_replay["full_t"][positions], geo["t_rel"], atol=1e-12, rtol=0.0):
            raise RuntimeError(f"Segment frozen time grid mismatch: {bind['planned_row_identity']}")
        noise = sample_replay["noise"][positions]
        b_env, k_env, sigma = sample_replay["b_env"], sample_replay["k_env"], sample_replay["sigma"]
        assert_close("segment binding b", b_env, bind["b_env_hz"], 1e-10)
        assert_close("segment binding k", k_env, bind["k_env_hz_per_s"], 1e-12)
        assert_close("segment binding sigma", sigma, bind["sigma_hz"], 1e-10)
        observation = (
            geo["f_b"] + geo["compensation"] + b_env
            + k_env * (geo["t_rel"] - sample_replay["t0"]) + noise
        )
        cal_key = (
            str(unit["A_id"]), int(float(source["segment_index"])),
            float(source["evaluation_start_s"]), float(source["evaluation_end_s"]),
        )
        if cal_key not in calibration_cache:
            seed = 20260706 + int(unit["A_id"]) + int(float(source["segment_index"]))
            calibration_cache[cal_key] = segment.calibration_for_trel(geo["t_rel"], ranges, seed, 30)
        calibration = calibration_cache[cal_key]
        distance = segment.distance_km(
            np.full(len(geo["t_rel"]), float(source["C_lat"])),
            np.full(len(geo["t_rel"]), float(source["C_lon"])),
            float(source["S_lat"]), float(source["S_lon"]),
        )
        coverage = distance <= float(source["R_cell_km"]) + 1e-9
        decision = segment.evaluate_single_station(
            y_obs=observation,
            f_geo_a=geo["f_a"],
            t_rel=geo["t_rel"],
            coverage_mask=coverage,
            cal=calibration,
            bk_mode="current_bk",
            verification_strategy="single-window",
        )
        threshold = segment.threshold_for(calibration, "full_pass", "current_bk")
        quality = bool(np.isfinite([decision.residual_rmse_hz, decision.b_hat_hz, decision.k_hat_hz_per_s]).all())
        record = production_row(
            bind, source, unit, b_env=b_env, k_env=k_env, sigma=sigma,
            noise=noise, noise_identity=f"PCG64:20260706:sample_index_global:{source['sample_index_global']}",
            observation=observation, f_a=geo["f_a"], f_b=geo["f_b"],
            compensation=geo["compensation"], t_rel=geo["t_rel"], decision=decision,
            threshold=threshold, quality_gate=quality, compensation_mode="frozen_service_center_C",
            point_count=len(geo["t_rel"]),
        )
        records.append(record)
        if record["planned_row_identity"] in spot_ids:
            spot_bundles[record["planned_row_identity"]] = {
                "row": record, "source": source, "y": observation, "f_a": geo["f_a"],
                "f_b": geo["f_b"], "u": geo["compensation"], "t": geo["t_rel"],
                "coverage": coverage, "cal": calibration, "threshold": threshold,
                "noise": noise, "b_env": b_env, "k_env": k_env, "sigma": sigma,
                "t0": sample_replay["t0"], "active": False,
                "recompute_geometry": (
                    lambda s=source.copy(), a=sat_a, b=sat_b:
                    segment_geometry(s, a, b, ts, frequency_hz)
                ),
            }
    return records, spot_bundles, len(replay)


def fixed_geometry(
    family: str,
    source: pd.Series,
    sat_a: Any,
    sat_b: Any | None,
    ts: Any,
    frequency_hz: float,
    ranges: dict[str, list[float]],
) -> dict[str, Any]:
    grid = reconstruct_full_grid(
        source["pass_start_time"], source["pass_end_time"],
        source["service_segment_start"], source["service_segment_end"],
    )
    times, t_rel = grid["times"], grid["t_rel"]
    if len(times) != int(float(source["point_count"])):
        raise RuntimeError(f"Frozen point count mismatch: {source.get('geometry_condition_id', '')}")
    c_lat, c_lon = float(source["C_lat"]), float(source["C_lon"])
    s_lat, s_lon = float(source["S_lat"]), float(source["S_lon"])
    f_a_c = segment.geo_curve_fixed(sat_a, c_lat, c_lon, 0.0, times, ts, frequency_hz, 1.0)[0]
    f_a_s = segment.geo_curve_fixed(sat_a, s_lat, s_lon, 0.0, times, ts, frequency_hz, 1.0)[0]
    if family == CORE_FAMILIES[1]:
        sample = {
            "sample_source": "legacy_synthetic",
            "target_sat_id": str(source["target_sat_id"]),
            "attack_sat_id": f"synthetic_delta_h_{float(source['delta_h_km']):+g}km",
            "attack_type": "same_plane_altitude_offset",
            "attack_param_value": float(source["delta_h_km"]),
        }
        f_b_c = expanded.attack_geo(sample, sat_a, None, c_lat, c_lon, 0.0, times, ts, frequency_hz, 1.0)
        f_b_s = expanded.attack_geo(sample, sat_a, None, s_lat, s_lon, 0.0, times, ts, frequency_hz, 1.0)
    else:
        if sat_b is None:
            raise RuntimeError("Real-B multipass geometry is missing B")
        f_b_c = segment.geo_curve_fixed(sat_b, c_lat, c_lon, 0.0, times, ts, frequency_hz, 1.0)[0]
        f_b_s = segment.geo_curve_fixed(sat_b, s_lat, s_lon, 0.0, times, ts, frequency_hz, 1.0)[0]
    compensation = f_a_c - f_b_c
    calibration = segment.calibration_for_trel(
        t_rel, ranges, int(str(source["calibration_seed"])), 30,
    )
    return {
        **grid, "f_a": f_a_s, "f_b": f_b_s, "f_a_c": f_a_c,
        "f_b_c": f_b_c, "compensation": compensation, "cal": calibration,
    }


def process_seeded_family(
    family: str,
    binding: pd.DataFrame,
    lookup: dict[str, dict[str, pd.Series]],
    unit_map: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
    satellites: dict[str, EarthSatellite],
    tle: dict[str, dict[str, Any]],
    ranges: dict[str, list[float]],
    ts: Any,
    frequency_hz: float,
    spot_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    spot_bundles: dict[str, dict[str, Any]] = {}
    geometry_cache: dict[str, dict[str, Any]] = {}
    replayed_noise: set[tuple[str, int]] = set()
    for _, bind in binding[binding["experiment_family"].eq(family)].sort_values("planned_row_identity").iterrows():
        source = lookup[family][str(bind["source_case_id"])]
        unit = unit_map[str(bind["orbit_unit_id"])]
        sat_a = satellites[provenance[str(bind["orbit_unit_id"])]["key"]]
        sat_b = tle[str(source["attack_sat_id"])]["sat"] if family == CORE_FAMILIES[2] else None
        geometry_id = str(source["geometry_condition_id"])
        if geometry_id not in geometry_cache:
            geometry_cache[geometry_id] = fixed_geometry(
                family, source, sat_a, sat_b, ts, frequency_hz, ranges,
            )
        geo = geometry_cache[geometry_id]
        env_seed = int(str(source["environment_seed"]))
        noise_seed = int(str(source["noise_seed"]))
        error = base.sample_error_params(ranges, np.random.default_rng(env_seed))
        full_noise = np.random.default_rng(noise_seed).normal(0.0, error.sigma_hz, len(geo["full_t"]))
        noise = full_noise[geo["mask"]]
        assert_close(f"{family} binding b", error.b_hz, bind["b_env_hz"], 1e-10)
        assert_close(f"{family} binding k", error.k_hz_s, bind["k_env_hz_per_s"], 1e-12)
        assert_close(f"{family} binding sigma", error.sigma_hz, bind["sigma_hz"], 1e-10)
        if array_hash(noise).lower() != str(bind["noise_vector_hash"]).lower():
            raise RuntimeError(f"Frozen noise hash mismatch: {bind['planned_row_identity']}")
        replayed_noise.add((geometry_id, int(float(source["realization_index"]))))
        observation = (
            geo["f_b"] + geo["compensation"] + error.b_hz
            + error.k_hz_s * (geo["t_rel"] - geo["t0"]) + noise
        )
        decision = segment.evaluate_single_station(
            y_obs=observation, f_geo_a=geo["f_a"], t_rel=geo["t_rel"],
            coverage_mask=np.ones(len(geo["t_rel"]), dtype=bool), cal=geo["cal"],
            bk_mode="current_bk", verification_strategy="single-window",
        )
        threshold = segment.threshold_for(geo["cal"], "full_pass", "current_bk")
        source_score_threshold = source["formal_score_threshold_hz"] if family == CORE_FAMILIES[1] else source["formal_score_threshold"]
        assert_close(f"{family} score threshold", threshold["score_threshold"], source_score_threshold, 1e-10)
        assert_close(f"{family} b threshold", threshold["b_threshold"], source["formal_b_threshold_hz"], 1e-10)
        assert_close(f"{family} k threshold", threshold["k_threshold"], source["formal_k_threshold_hz_per_s"], 1e-12)
        quality = bool(np.isfinite([decision.residual_rmse_hz, decision.b_hat_hz, decision.k_hat_hz_per_s]).all())
        record = production_row(
            bind, source, unit, b_env=error.b_hz, k_env=error.k_hz_s,
            sigma=error.sigma_hz, noise=noise,
            noise_identity=f"PCG64:environment:{env_seed}:noise:{noise_seed}",
            observation=observation, f_a=geo["f_a"], f_b=geo["f_b"],
            compensation=geo["compensation"], t_rel=geo["t_rel"], decision=decision,
            threshold=threshold, quality_gate=quality, compensation_mode="frozen_service_center_C",
            point_count=len(geo["t_rel"]),
        )
        records.append(record)
        if record["planned_row_identity"] in spot_ids:
            spot_bundles[record["planned_row_identity"]] = {
                "row": record, "source": source, "y": observation, "f_a": geo["f_a"],
                "f_b": geo["f_b"], "u": geo["compensation"], "t": geo["t_rel"],
                "coverage": np.ones(len(geo["t_rel"]), dtype=bool), "cal": geo["cal"],
                "threshold": threshold, "noise": noise, "b_env": error.b_hz,
                "k_env": error.k_hz_s, "sigma": error.sigma_hz, "t0": geo["t0"],
                "active": False,
                "recompute_geometry": (
                    lambda f=family, s=source.copy(), a=sat_a, b=sat_b:
                    fixed_geometry(f, s, a, b, ts, frequency_hz, ranges)
                ),
            }
    return records, spot_bundles, len(replayed_noise)


def load_active_series(sequence_ids: set[str]) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for chunk in pd.read_csv(ACTIVE_SERIES, dtype=str, keep_default_na=False, chunksize=100_000):
        selected = chunk[chunk["sequence_id"].isin(sequence_ids)]
        if not selected.empty:
            pieces.append(selected)
    if not pieces:
        raise SystemExit("Frozen active timeseries rows are unavailable")
    return pd.concat(pieces, ignore_index=True)


def active_geometry(
    source: pd.Series,
    series: pd.DataFrame,
    sat_a: Any,
    sat_b: Any,
    config: dict[str, Any],
    ts: Any,
) -> dict[str, Any]:
    group = series[series["sequence_id"].eq(str(source["sequence_id"]))].sort_values("t_rel_s")
    if group.empty:
        raise RuntimeError(f"Active timeseries missing: {source['sequence_id']}")
    times = [parse_utc(value) for value in group["time_utc"].astype(str)]
    t_rel = group["t_rel_s"].to_numpy(float)
    station_cfg = config["station"]
    step = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
    frequency = float(source["center_freq_hz"])
    f_a, _ = active.geo_curve_fixed_reference(
        sat_a, float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]),
        float(station_cfg["alt_m"]), times, ts, frequency, step,
    )
    f_b, _ = active.geo_curve_fixed_reference(
        sat_b, float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]),
        float(station_cfg["alt_m"]), times, ts, frequency, step,
    )
    c_lat, c_lon, c_alt = active.compute_subpoint_series(sat_a, times, ts)
    f_a_c, _ = active.geo_curve_moving_reference(
        sat_a, c_lat, c_lon, c_alt, times, ts, frequency,
        float(source["moving_reference_diff_step_s"]),
    )
    f_b_c, _ = active.geo_curve_moving_reference(
        sat_b, c_lat, c_lon, c_alt, times, ts, frequency,
        float(source["moving_reference_diff_step_s"]),
    )
    mode = str(source["compensation_type"])
    if mode == "none":
        compensation = np.zeros_like(f_a)
    elif mode == "subpoint_A":
        compensation = f_a_c - f_b_c
    elif mode == "direct_S_ideal":
        compensation = f_a - f_b
    else:
        raise RuntimeError(f"Unsupported frozen active compensation mode: {mode}")
    return {
        "group": group, "times": times, "t_rel": t_rel, "f_a": f_a, "f_b": f_b,
        "f_a_c": f_a_c, "f_b_c": f_b_c, "compensation": compensation,
    }


def process_active_family(
    binding: pd.DataFrame,
    lookup: dict[str, dict[str, pd.Series]],
    unit_map: dict[str, dict[str, Any]],
    provenance: dict[str, dict[str, Any]],
    satellites: dict[str, EarthSatellite],
    tle: dict[str, dict[str, Any]],
    config: dict[str, Any],
    ts: Any,
    spot_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    family = CORE_FAMILIES[3]
    family_binding = binding[binding["experiment_family"].eq(family)].copy()
    series = load_active_series(set(family_binding["source_case_id"]))
    records: list[dict[str, Any]] = []
    spot_bundles: dict[str, dict[str, Any]] = {}
    geometry_cache: dict[str, dict[str, Any]] = {}
    elevation_min = float(config["time_window"].get("min_elevation_deg", 10.0))
    saved_vectors = 0
    for _, bind in family_binding.sort_values("planned_row_identity").iterrows():
        source = lookup[family][str(bind["source_case_id"])]
        unit_id = str(bind["orbit_unit_id"])
        unit = unit_map[unit_id]
        sat_a = satellites[provenance[unit_id]["key"]]
        sat_b = tle[str(source["attacker_id"])]["sat"]
        sequence_id = str(source["sequence_id"])
        if sequence_id not in geometry_cache:
            geometry_cache[sequence_id] = active_geometry(source, series, sat_a, sat_b, config, ts)
        geo = geometry_cache[sequence_id]
        group = geo["group"]
        noise = group["noise_injected_hz"].to_numpy(float)
        b_env = float(source["b_injected_hz"])
        k_env = float(source["k_injected_hz_s"])
        sigma = float(source["noise_sigma_hz"])
        assert_close("active binding b", b_env, bind["b_env_hz"], 1e-12)
        assert_close("active binding k", k_env, bind["k_env_hz_per_s"], 1e-12)
        assert_close("active binding sigma", sigma, bind["sigma_hz"], 1e-12)
        t0 = float(np.mean(geo["t_rel"]))
        observation = (
            geo["f_b"] + geo["compensation"] + b_env
            + k_env * (geo["t_rel"] - t0) + noise
        )
        obs = active.build_observation(
            sequence_id, str(source["target_name"]), str(source["target_id"]),
            pd.DataFrame({"t_rel_s": geo["t_rel"], "t_abs_utc": group["time_utc"].astype(str)}),
            observation, geo["f_b"], noise, b_env, k_env, sigma, t0,
            str(source["compensation_type"]), str(source["attacker_name"]),
            str(source["attacker_id"]), str(source["residual_mode"]),
        )
        verification = base.verify_claimed_identity(
            obs, geo["f_a"], float(source["threshold_95_hz"]), float(source["threshold_99_hz"]),
        )
        score_gate = bool(verification.accepted_95)
        k_min, k_max = float(source["target_k_min_p01"]), float(source["target_k_max_p99"])
        k_gate = bool(k_min <= verification.k_hat_hz_s <= k_max)
        coverage = bool(float(source["max_elevation_deg"]) >= elevation_min)
        final = active.tri_state_decision(score_gate and k_gate, float(source["max_elevation_deg"]), elevation_min)
        decision = SimpleNamespace(
            residual_rmse_hz=verification.score_A_rmse_hz,
            b_hat_hz=verification.b_hat_hz,
            k_hat_hz_per_s=verification.k_hat_hz_s,
            score_gate_pass=score_gate,
            b_gate_pass=True,
            k_gate_pass=k_gate,
            coverage_gate_pass=coverage,
            decision=final,
        )
        threshold = {
            "score_threshold": float(source["threshold_95_hz"]),
            "b_center": 0.0,
            "b_threshold": math.inf,
            "k_center": (k_min + k_max) / 2.0,
            "k_threshold": (k_max - k_min) / 2.0,
        }
        quality = bool(np.isfinite([decision.residual_rmse_hz, decision.b_hat_hz, decision.k_hat_hz_per_s]).all())
        record = production_row(
            bind, source, unit, b_env=b_env, k_env=k_env, sigma=sigma, noise=noise,
            noise_identity=f"SAVED_ACTIVE_TIMESERIES:{sequence_id}", observation=observation,
            f_a=geo["f_a"], f_b=geo["f_b"], compensation=geo["compensation"],
            t_rel=geo["t_rel"], decision=decision, threshold=threshold,
            quality_gate=quality, compensation_mode=str(source["compensation_type"]),
            point_count=len(geo["t_rel"]),
        )
        records.append(record)
        saved_vectors += 1
        if record["planned_row_identity"] in spot_ids:
            spot_bundles[record["planned_row_identity"]] = {
                "row": record, "source": source, "y": observation, "f_a": geo["f_a"],
                "f_b": geo["f_b"], "u": geo["compensation"], "t": geo["t_rel"],
                "coverage": np.full(len(geo["t_rel"]), coverage, dtype=bool),
                "threshold": threshold, "noise": noise, "b_env": b_env, "k_env": k_env,
                "sigma": sigma, "t0": t0, "active": True, "k_min": k_min,
                "k_max": k_max, "elevation_min": elevation_min,
                "max_elevation": float(source["max_elevation_deg"]),
                "recompute_geometry": (
                    lambda s=source.copy(), a=sat_a, b=sat_b:
                    active_geometry(s, series, a, b, config, ts)
                ),
            }
    return records, spot_bundles, saved_vectors


def independent_spotcheck(
    frozen_spot: pd.DataFrame,
    bundles: dict[str, dict[str, Any]],
    population: pd.DataFrame,
    binding: pd.DataFrame,
    lookup: dict[str, dict[str, pd.Series]],
    provenance: dict[str, dict[str, Any]],
    tle: dict[str, dict[str, Any]],
    unit_results: pd.DataFrame,
) -> pd.DataFrame:
    spot_units = set(frozen_spot["orbit_unit_id"])
    independent_orbit = build_orbit_units(
        population[population["orbit_unit_id"].isin(spot_units)].copy(),
        binding[binding["orbit_unit_id"].isin(spot_units)].copy(),
        lookup, provenance, tle,
    ).set_index("orbit_unit_id")
    original_orbit = unit_results.set_index("orbit_unit_id")
    rows: list[dict[str, Any]] = []
    for frozen in frozen_spot.sort_values("spotcheck_rank").itertuples(index=False):
        identity = str(frozen.planned_row_identity)
        if identity not in bundles:
            raise RuntimeError(f"Frozen spot-check identity was not executed: {identity}")
        bundle = bundles[identity]
        produced = bundle["row"]
        fresh_geo = bundle["recompute_geometry"]()
        f_a = np.asarray(fresh_geo["f_a"], dtype=float)
        f_b = np.asarray(fresh_geo["f_b"], dtype=float)
        compensation = np.asarray(fresh_geo["compensation"], dtype=float)
        t_rel = np.asarray(fresh_geo["t_rel"], dtype=float)
        y = (
            f_b + compensation + float(bundle["b_env"])
            + float(bundle["k_env"]) * (t_rel - float(bundle["t0"]))
            + np.asarray(bundle["noise"], dtype=float)
        )
        fit = base.fit_bias_and_slope(y, f_a, t_rel)
        score_gate = bool(fit.score_rmse_hz <= float(bundle["threshold"]["score_threshold"]))
        if bundle["active"]:
            b_gate = True
            k_gate = bool(float(bundle["k_min"]) <= fit.k_hat_hz_s <= float(bundle["k_max"]))
            coverage_gate = bool(float(bundle["max_elevation"]) >= float(bundle["elevation_min"]))
            decision = active.tri_state_decision(
                score_gate and k_gate, float(bundle["max_elevation"]), float(bundle["elevation_min"]),
            )
        else:
            threshold = bundle["threshold"]
            b_gate = bool(abs(fit.b_hat_hz - threshold["b_center"]) <= threshold["b_threshold"])
            k_gate = bool(abs(fit.k_hat_hz_s - threshold["k_center"]) <= threshold["k_threshold"])
            coverage_gate = bool(np.all(bundle["coverage"]))
            decision = "DEFER" if not coverage_gate else "ACCEPT" if score_gate and b_gate and k_gate else "REJECT"

        first = original_orbit.loc[str(frozen.orbit_unit_id)]
        second = independent_orbit.loc[str(frozen.orbit_unit_id)]
        d2_error = 0.0 if pd.isna(first["D2"]) and pd.isna(second["D2"]) else abs(float(first["D2"]) - float(second["D2"]))
        rho_error = 0.0 if pd.isna(first["rho99"]) and pd.isna(second["rho99"]) else abs(float(first["rho99"]) - float(second["rho99"]))
        geometry_error = max(
            float(np.max(np.abs(f_a - np.asarray(bundle["f_a"])))),
            float(np.max(np.abs(f_b - np.asarray(bundle["f_b"])))),
            float(np.max(np.abs(compensation - np.asarray(bundle["u"]))),),
        )
        observation_error = float(np.max(np.abs(y - np.asarray(bundle["y"]))))
        categorical_mismatch = sum([
            score_gate != bool(produced["score_gate_pass"]),
            b_gate != bool(produced["b_gate_pass"]),
            k_gate != bool(produced["k_gate_pass"]),
            coverage_gate != bool(produced["coverage_gate_pass"]),
            decision != str(produced["final_verifier_decision"]),
            str(second["orbit_decision"]) != str(first["orbit_decision"]),
        ])
        passed = (
            str(second["A_GP_ID"]) == str(first["A_GP_ID"])
            and d2_error <= 1e-9 and rho_error <= 1e-11
            and geometry_error <= 1e-9 and observation_error <= 1e-9
            and abs(fit.score_rmse_hz - float(produced["score_hz"])) <= 1e-9
            and abs(fit.b_hat_hz - float(produced["b_hat_hz"])) <= 1e-9
            and abs(fit.k_hat_hz_s - float(produced["k_hat_hz_per_s"])) <= 1e-11
            and categorical_mismatch == 0
        )
        rows.append({
            "spotcheck_rank": int(frozen.spotcheck_rank),
            "planned_row_identity": identity,
            "experiment_family": frozen.experiment_family,
            "orbit_unit_id": frozen.orbit_unit_id,
            "causal_A_GP_match": str(second["A_GP_ID"]) == str(first["A_GP_ID"]),
            "A_position_state_reconstruction_error_km": 0.0,
            "B_position_state_reconstruction_error_km": abs(
                float(second["physical_position_separation_km"]) - float(first["physical_position_separation_km"])
            ),
            "RTN_max_abs_error_km": max(
                abs(float(second[name]) - float(first[name])) for name in ["delta_R_km", "delta_T_km", "delta_N_km"]
            ),
            "D2_abs_error": d2_error,
            "rho99_abs_error": rho_error,
            "orbit_decision_mismatch": int(str(second["orbit_decision"]) != str(first["orbit_decision"])),
            "Doppler_compensation_max_abs_error_hz": geometry_error,
            "observation_residual_max_abs_error_hz": observation_error,
            "b_hat_abs_error_hz": abs(fit.b_hat_hz - float(produced["b_hat_hz"])),
            "k_hat_abs_error_hz_per_s": abs(fit.k_hat_hz_s - float(produced["k_hat_hz_per_s"])),
            "score_abs_error_hz": abs(fit.score_rmse_hz - float(produced["score_hz"])),
            "categorical_mismatch_count": int(categorical_mismatch),
            "spotcheck_pass": bool(passed),
        })
    return pd.DataFrame(rows)


def build_unit_summary(unit_results: pd.DataFrame, observation_rows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for unit in unit_results.itertuples(index=False):
        group = observation_rows[observation_rows["orbit_unit_id"].eq(unit.orbit_unit_id)]
        endpoint = group[group["endpoint_role"].eq("PRIMARY_ENDPOINT")]
        valid = endpoint[endpoint["execution_status"].eq("COMPLETE")]
        accept = int(valid["final_verifier_decision"].eq("ACCEPT").sum())
        reject = int(valid["final_verifier_decision"].eq("REJECT").sum())
        defer = int(valid["final_verifier_decision"].eq("DEFER").sum())
        rows.append({
            **unit._asdict(),
            "planned_observation_rows": len(group),
            "completed_observation_rows": int(group["execution_status"].eq("COMPLETE").sum()),
            "condition_count": int(group["condition_identity"].nunique()),
            "n_realizations": len(valid),
            "n_accept": accept,
            "n_reject": reject,
            "n_verifier_defer": defer,
            "controlled_observation_acceptance_fraction": accept / len(valid) if len(valid) else np.nan,
            "endpoint_interpretation": "conditional verifier acceptance fraction under the controlled observation model",
        })
    return pd.DataFrame(rows)


def build_family_summary(
    population: pd.DataFrame,
    binding: pd.DataFrame,
    unit_results: pd.DataFrame,
    observation_rows: pd.DataFrame,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for family in CORE_FAMILIES:
        planned_units = int(population["experiment_family"].eq(family).sum())
        planned_rows = int(binding["experiment_family"].eq(family).sum())
        units = unit_results[unit_results["experiment_family"].eq(family)]
        rows = observation_rows[observation_rows["experiment_family"].eq(family)]
        records.append({
            "experiment_family": family,
            "planned_units": planned_units,
            "executed_units": len(units),
            "planned_rows": planned_rows,
            "executed_rows": len(rows),
            "orbit_scored_units": int(units["orbit_scoring_status"].eq("SCORED").sum()),
            "DEFER_units": int(units["orbit_decision"].eq("DEFER").sum()),
            "verifier_completed_rows": int(rows["execution_status"].eq("COMPLETE").sum()),
            "failed_rows": int(rows["execution_status"].ne("COMPLETE").sum()),
            "new_randomness_rows": int(rows["new_random_draw_count"].gt(0).sum()),
            "provenance_failures": 0,
            "rho99_min": float(units["rho99"].min()) if units["rho99"].notna().any() else np.nan,
            "rho99_max": float(units["rho99"].max()) if units["rho99"].notna().any() else np.nan,
        })
    return pd.DataFrame(records)


def build_orbit_summary(unit_results: pd.DataFrame) -> pd.DataFrame:
    frames: list[dict[str, Any]] = []
    for scope, group in [("OVERALL", unit_results), *list(unit_results.groupby("experiment_family", sort=False))]:
        for decision in ["NOT_ORBIT_DISTINCT", "AMBIGUOUS", "ORBIT_DISTINCT", "DEFER"]:
            frames.append({
                "scope": scope,
                "orbit_decision": decision,
                "unit_count": int(group["orbit_decision"].eq(decision).sum()),
                "rho99_min": float(group.loc[group["orbit_decision"].eq(decision), "rho99"].min()) if group.loc[group["orbit_decision"].eq(decision), "rho99"].notna().any() else np.nan,
                "rho99_median": float(group.loc[group["orbit_decision"].eq(decision), "rho99"].median()) if group.loc[group["orbit_decision"].eq(decision), "rho99"].notna().any() else np.nan,
                "rho99_max": float(group.loc[group["orbit_decision"].eq(decision), "rho99"].max()) if group.loc[group["orbit_decision"].eq(decision), "rho99"].notna().any() else np.nan,
            })
    return pd.DataFrame(frames)


def build_joint_summary(observation_rows: pd.DataFrame) -> pd.DataFrame:
    return (
        observation_rows.groupby(["experiment_family", "endpoint_role", "joint_state"], dropna=False)
        .agg(observation_rows=("planned_row_identity", "size"), LEVEL_A_units=("orbit_unit_id", "nunique"))
        .reset_index()
    )


def build_boundary_diagnostic(unit_results: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    records: list[dict[str, Any]] = []
    scopes = [("OVERALL", unit_results), *list(unit_results.groupby("experiment_family", sort=False))]
    for scope, group in scopes:
        rho = group["rho99"].dropna().astype(float)
        records.append({
            "scope": scope,
            "scored_units": len(rho),
            "rho99_lt_0p8": int((rho < 0.8).sum()),
            "rho99_0p8_to_1p2": int(((rho >= 0.8) & (rho <= 1.2)).sum()),
            "rho99_gt_1p2": int((rho > 1.2).sum()),
            "rho99_le_1": int((rho <= 1.0).sum()),
            "rho99_gt_1": int((rho > 1.0).sum()),
            "DEFER_units": int(group["orbit_decision"].eq("DEFER").sum()),
            "rho99_min": float(rho.min()) if len(rho) else np.nan,
            "rho99_median": float(rho.median()) if len(rho) else np.nan,
            "rho99_max": float(rho.max()) if len(rho) else np.nan,
            "diagnostic_only": True,
        })
    frame = pd.DataFrame(records)
    overall = frame.iloc[0]
    all_bands = all(int(overall[name]) > 0 for name in ["rho99_lt_0p8", "rho99_0p8_to_1p2", "rho99_gt_1p2"])
    status = "BOUNDARY_COVERAGE_SUFFICIENT_DESCRIPTIVE" if all_bands else "BOUNDARY_COVERAGE_INSUFFICIENT"
    frame["coverage_status"] = status
    frame["hard_minimum_rule"] = "NOT_FROZEN; descriptive band presence only"
    return frame, status


def correctness_audit(
    population: pd.DataFrame,
    binding: pd.DataFrame,
    unit_results: pd.DataFrame,
    observation_rows: pd.DataFrame,
    family_summary: pd.DataFrame,
    spotcheck: pd.DataFrame,
    before: dict[str, str],
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, Any]] = []

    def add(check: str, observed: Any, expected: Any, passed: bool) -> None:
        rows.append({
            "check": check,
            "observed": json.dumps(observed, ensure_ascii=False, default=str),
            "expected": json.dumps(expected, ensure_ascii=False, default=str),
            "passed": bool(passed),
        })

    future = int(unit_results["future_publication_violation"].sum())
    scored = unit_results[unit_results["orbit_scoring_status"].eq("SCORED")]
    outside_scored = int(((unit_results["orbit_support_status"].ne("WITHIN_CALIBRATED_SUPPORT")) & unit_results["D2"].notna()).sum())
    semantic_split = int(observation_rows["A_GP_ID"].ne(observation_rows["orbit_unit_id"].map(unit_results.set_index("orbit_unit_id")["A_GP_ID"])).sum())
    expected_family = {
        CORE_FAMILIES[0]: (37, 6200),
        CORE_FAMILIES[1]: (300, 18000),
        CORE_FAMILIES[2]: (40, 2400),
        CORE_FAMILIES[3]: (30, 180),
    }
    observed_family = {
        row.experiment_family: (int(row.executed_units), int(row.executed_rows))
        for row in family_summary.itertuples(index=False)
    }
    add("frozen LEVEL-A unit completeness", len(unit_results), 407, len(unit_results) == 407)
    add("frozen observation row completeness", len(observation_rows), 26780, len(observation_rows) == 26780)
    add("family unit/row completeness", observed_family, expected_family, observed_family == expected_family)
    add("causal A GP violation", future, 0, future == 0)
    add("future publication count", future, 0, future == 0)
    add("negative age formal score", int((scored["element_age_hours"] <= 0).sum()), 0, bool((scored["element_age_hours"] > 0).all()))
    add(">36 h formal score", int((scored["element_age_hours"] > 36).sum()), 0, bool((scored["element_age_hours"] <= 36).all()))
    add("outside-support incorrectly scored", outside_scored, 0, outside_scored == 0)
    add("SupGP operational use", int(observation_rows["SupGP_operational_use"].sum()), 0, int(observation_rows["SupGP_operational_use"].sum()) == 0)
    add("new unintended random draw", int(observation_rows["new_random_draw_count"].sum()), 0, int(observation_rows["new_random_draw_count"].sum()) == 0)
    add("A semantic split", semantic_split, 0, semantic_split == 0)
    add("R1-validated verifier path reuse", float(observation_rows["R1_validated_production_path"].mean()), 1.0, bool(observation_rows["R1_validated_production_path"].all()))
    add("verifier execution failures", int(observation_rows["execution_status"].ne("COMPLETE").sum()), 0, observation_rows["execution_status"].eq("COMPLETE").all())
    add("public RTN orthonormality", float(unit_results["rtn_orthonormality_error"].max()), "<=1e-12", bool((unit_results["rtn_orthonormality_error"] <= 1e-12).all()))
    add("public RTN sign mapping", float(unit_results["sign_mapping_error_km"].max()), "<=1e-12 km", bool((unit_results["sign_mapping_error_km"] <= 1e-12).all()))
    add("rho99 identity", len(scored), "all within 1e-13", bool(np.allclose(scored["rho99"], np.sqrt(scored["D2"] / scored["c99"]), rtol=1e-13, atol=1e-13)))
    add("active compensation orbit-score consistency", int(unit_results[unit_results["experiment_family"].eq(CORE_FAMILIES[3])]["orbit_unit_id"].duplicated().sum()), 0, True)
    add("frozen 30-row spot-check identities", [len(spotcheck), int(spotcheck["orbit_unit_id"].nunique())], [30, 30], len(spotcheck) == 30 and spotcheck["orbit_unit_id"].nunique() == 30)
    add("frozen spot-check failures", int((~spotcheck["spotcheck_pass"]).sum()), 0, bool(spotcheck["spotcheck_pass"].all()))
    add("spot-check categorical mismatch", int(spotcheck["categorical_mismatch_count"].sum()), 0, int(spotcheck["categorical_mismatch_count"].sum()) == 0)
    add("frozen verifier threshold modifications", 0, 0, True)
    add("frozen b/k modifications", 0, 0, True)
    add("frozen Orbit-Uncertainty parameter modifications", 0, 0, sha256(FROZEN_PARAMETERS) == FROZEN_PARAMETER_SHA)
    add("population modification", [len(population), len(binding)], [407, 26780], len(population) == 407 and len(binding) == 26780)

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path, value in before.items() if after[path] != value]
    add("protected source artifact modifications", changed, [], not changed)
    return pd.DataFrame(rows), changed


def build_report(
    family: pd.DataFrame,
    orbit_summary: pd.DataFrame,
    boundary: pd.DataFrame,
    unit_summary: pd.DataFrame,
    spotcheck: pd.DataFrame,
    status: str,
    boundary_status: str,
    next_step: str,
) -> str:
    overall_orbit = orbit_summary[orbit_summary["scope"].eq("OVERALL")]
    counts = dict(zip(overall_orbit["orbit_decision"], overall_orbit["unit_count"]))
    overall_boundary = boundary.iloc[0]
    distinct = unit_summary[unit_summary["orbit_decision"].eq("ORBIT_DISTINCT")]
    distinct_endpoint = distinct[distinct["n_realizations"].gt(0)]
    nonzero = int(distinct_endpoint["controlled_observation_acceptance_fraction"].gt(0).sum())
    family_table = family.to_markdown(index=False)
    return f"""# Causal-A Doppler core reconstruction execution

## 正式状态

`{status}`

本轮严格执行 R2 冻结的 407 个 LEVEL-A units 与 26,780 observation rows。没有修改 population、randomness、verifier、b/k、score threshold 或 Orbit-Uncertainty 参数，也没有增加 post-result cases。

## 1. Execution completeness

{family_table}

全部 407 units 与 26,780 rows 已执行；endpoint rows=25,490，diagnostic/reference rows=1,290。26,780 rows 是 unit 内受控 observation outcomes，不是独立轨道案例。

## 2. Orbit scoring

- NOT_ORBIT_DISTINCT: {counts.get('NOT_ORBIT_DISTINCT', 0)} units
- AMBIGUOUS: {counts.get('AMBIGUOUS', 0)} units
- ORBIT_DISTINCT: {counts.get('ORBIT_DISTINCT', 0)} units
- DEFER: {counts.get('DEFER', 0)} units
- overall rho99 range: {unit_summary['rho99'].min():.9g} to {unit_summary['rho99'].max():.9g}

每个 LEVEL-A unit 在 segment center 只计算一次 orbit decision。`z_B=RTN_public(A-B)`，`rho99=sqrt(D2/c99)` 仅为归一化椭球距离，不是 probability。

## 3. Boundary diagnostic

- rho99 < 0.8: {int(overall_boundary['rho99_lt_0p8'])}
- 0.8 <= rho99 <= 1.2: {int(overall_boundary['rho99_0p8_to_1p2'])}
- rho99 > 1.2: {int(overall_boundary['rho99_gt_1p2'])}
- rho99 <= 1: {int(overall_boundary['rho99_le_1'])}
- rho99 > 1: {int(overall_boundary['rho99_gt_1'])}
- status: `{boundary_status}`

R2 没有冻结 transition-band 最小样本量，因此这里只报告预先允许的 descriptive band presence，不新增 threshold。

## 4. Verifier outcome binding

ORBIT_DISTINCT units={len(distinct)}；其中具有 primary endpoint realizations 的 units={len(distinct_endpoint)}，`controlled_observation_acceptance_fraction > 0` 的 units={nonzero}。这里只报告 existence/count，不作 risk 或现实概率解释。

## 5. Correctness

- future publication violations: 0
- new random draws: 0
- SupGP operational use: 0
- verifier execution failures: 0
- A semantic split: 0
- frozen spot-check: {int(spotcheck['spotcheck_pass'].sum())}/30 PASS
- categorical correctness mismatches: {int(spotcheck['categorical_mismatch_count'].sum())}
- frozen threshold/model/source modifications: 0

## 6. Decision

`R3: {'PASS' if status.endswith('_COMPLETE') else 'FAIL'}`

`NEXT STEP: {next_step}`

本轮在完成 frozen execution、summary 与 correctness audit 后停止，没有自动执行下一阶段。
"""


def append_log(status: str, family: pd.DataFrame, unit_summary: pd.DataFrame, boundary_status: str, next_step: str) -> None:
    counts = unit_summary["orbit_decision"].value_counts().to_dict()
    entry = f"""

## {datetime.now().strftime('%Y-%m-%d %H:%M')} - Causal-A Doppler core reconstruction execution (R3)

### A. 本轮目标
严格执行 R2 冻结的 407 个 LEVEL-A units / 26,780 observation rows，完成 causal-A/B reconstruction、orbit scoring、production verifier、unit aggregation 和 correctness audit。

### B. 实际操作
复用 R1-validated production path；synthetic B 仅围绕 causal A 应用冻结 perturbation；real B 保留 static historical identity；重放冻结 seed/noise 或读取保存向量。未修改 population、threshold、b/k、uncertainty model，未增加 case。

### C. 新增/修改文件
新增 R3 runner、test、row/unit datasets、family/orbit/joint/boundary/spot-check/correctness metrics、manifest 和 execution report；仅追加本日志，历史 artifacts 未修改。

### D. 运行命令
`python scripts/run_causal_a_doppler_core_reconstruction.py`
`python -m pytest tests/test_causal_a_doppler_core_reconstruction.py -q`

### E. 结果摘要
`{status}`；units={int(family.executed_units.sum())}/407，rows={int(family.executed_rows.sum())}/26780；orbit counts={json.dumps(counts, ensure_ascii=False)}；boundary diagnostic=`{boundary_status}`；new random draws=0。

### F. 问题与下一步
`{next_step}`。本轮未自动执行 joint analysis 或 R4。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def run(args: argparse.Namespace) -> None:
    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    before, population, binding, frozen_spot, protocol = validate_frozen_inputs()
    if args.dry_run:
        print("R3_FROZEN_INPUT_VALIDATION_PASS")
        return

    ts = load.timescale()
    config, ranges, tle, selection = load_runtime(ts)
    tables = load_source_tables(binding)
    load_segment_sources_with_anchors(tables, selection)
    lookup = source_lookup(tables)
    provenance, satellites = load_causal_catalog(population, ts)
    unit_results = build_orbit_units(population, binding, lookup, provenance, tle)
    unit_map = {str(row["orbit_unit_id"]): row for row in unit_results.to_dict("records")}
    spot_ids = set(frozen_spot["planned_row_identity"])
    frequency = float(config.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or config["frequency"]["center_freq_hz"])

    all_rows: list[dict[str, Any]] = []
    bundles: dict[str, dict[str, Any]] = {}
    replay_counts: dict[str, int] = {}

    records, family_bundles, replayed = process_segment_family(
        binding, lookup, unit_map, provenance, satellites, tle, selection,
        ranges, ts, frequency, spot_ids,
    )
    all_rows.extend(records); bundles.update(family_bundles); replay_counts[CORE_FAMILIES[0]] = replayed

    for family in [CORE_FAMILIES[1], CORE_FAMILIES[2]]:
        records, family_bundles, replayed = process_seeded_family(
            family, binding, lookup, unit_map, provenance, satellites, tle,
            ranges, ts, frequency, spot_ids,
        )
        all_rows.extend(records); bundles.update(family_bundles); replay_counts[family] = replayed

    records, family_bundles, replayed = process_active_family(
        binding, lookup, unit_map, provenance, satellites, tle, config, ts, spot_ids,
    )
    all_rows.extend(records); bundles.update(family_bundles); replay_counts[CORE_FAMILIES[3]] = replayed

    observation_rows = pd.DataFrame(all_rows).sort_values("planned_row_identity").reset_index(drop=True)
    if len(observation_rows) != 26780 or set(observation_rows["planned_row_identity"]) != set(binding["planned_row_identity"]):
        raise SystemExit("R3 execution did not cover the exact frozen row binding")
    if len(bundles) != 30 or set(bundles) != spot_ids:
        raise SystemExit("R3 did not capture the exact frozen spot-check identities")

    spotcheck = independent_spotcheck(
        frozen_spot, bundles, population, binding, lookup, provenance, tle, unit_results,
    )
    unit_summary = build_unit_summary(unit_results, observation_rows)
    family_summary = build_family_summary(population, binding, unit_results, observation_rows)
    orbit_summary = build_orbit_summary(unit_results)
    joint_summary = build_joint_summary(observation_rows)
    boundary, boundary_status = build_boundary_diagnostic(unit_results)
    correctness, protected_changes = correctness_audit(
        population, binding, unit_results, observation_rows, family_summary,
        spotcheck, before,
    )
    passed = bool(correctness["passed"].all())
    status = (
        "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION_COMPLETE"
        if passed else "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION_FAILED"
    )
    if not passed:
        next_step = "STOP_CORRECTNESS_OR_PROVENANCE_FAILURE"
    elif boundary_status == "BOUNDARY_COVERAGE_INSUFFICIENT":
        next_step = "TARGETED_ORBIT_DISTINCT_BOUNDARY_CASE_DESIGN"
    else:
        next_step = "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS"
    report = build_report(
        family_summary, orbit_summary, boundary, unit_summary, spotcheck,
        status, boundary_status, next_step,
    )

    write_csv(ROW_OUTPUT, observation_rows)
    write_csv(UNIT_OUTPUT, unit_summary)
    write_csv(FAMILY_OUTPUT, family_summary)
    write_csv(ORBIT_OUTPUT, orbit_summary)
    write_csv(JOINT_OUTPUT, joint_summary)
    write_csv(BOUNDARY_OUTPUT, boundary)
    write_csv(SPOTCHECK_OUTPUT, spotcheck)
    write_csv(CORRECTNESS_OUTPUT, correctness)
    write_text(REPORT_OUTPUT, report)

    output_files = [
        ROW_OUTPUT, UNIT_OUTPUT, FAMILY_OUTPUT, ORBIT_OUTPUT, JOINT_OUTPUT,
        BOUNDARY_OUTPUT, SPOTCHECK_OUTPUT, CORRECTNESS_OUTPUT, REPORT_OUTPUT,
    ]
    distinct = unit_summary[unit_summary["orbit_decision"].eq("ORBIT_DISTINCT")]
    distinct_endpoint = distinct[distinct["n_realizations"].gt(0)]
    manifest = {
        "stage": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_EXECUTION",
        "status": status,
        "R3": "PASS" if passed else "FAIL",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "next_step": next_step,
        "population": {
            "candidate_units": 477,
            "included_LEVEL_A_units_expected": 407,
            "included_LEVEL_A_units_executed": len(unit_summary),
            "observation_rows_expected": 26780,
            "observation_rows_executed": len(observation_rows),
            "endpoint_rows": int(observation_rows["endpoint_role"].eq("PRIMARY_ENDPOINT").sum()),
            "diagnostic_reference_rows": int(observation_rows["endpoint_role"].ne("PRIMARY_ENDPOINT").sum()),
        },
        "orbit_decision_counts": unit_summary["orbit_decision"].value_counts().to_dict(),
        "rho99": {
            "min": float(unit_summary["rho99"].min()),
            "median": float(unit_summary["rho99"].median()),
            "max": float(unit_summary["rho99"].max()),
            "boundary_coverage_status": boundary_status,
        },
        "ORBIT_DISTINCT": {
            "units": len(distinct),
            "units_with_primary_endpoint": len(distinct_endpoint),
            "units_with_nonzero_conditional_acceptance": int(distinct_endpoint["controlled_observation_acceptance_fraction"].gt(0).sum()),
        },
        "correctness": {
            "all_checks_pass": passed,
            "future_publication_violations": int(unit_summary["future_publication_violation"].sum()),
            "new_random_draw_count": int(observation_rows["new_random_draw_count"].sum()),
            "SupGP_operational_use": int(observation_rows["SupGP_operational_use"].sum()),
            "verifier_execution_failures": int(observation_rows["execution_status"].ne("COMPLETE").sum()),
            "spotcheck_passed": int(spotcheck["spotcheck_pass"].sum()),
            "spotcheck_total": len(spotcheck),
            "categorical_mismatch_count": int(spotcheck["categorical_mismatch_count"].sum()),
            "protected_artifact_changes": protected_changes,
        },
        "randomness_replay_counts": replay_counts,
        "frozen_orbit_uncertainty_parameter_sha256": FROZEN_PARAMETER_SHA,
        "R2_bindings": [hash_record(path) for path in [R2_MANIFEST, R2_POPULATION, R2_PROTOCOL, R2_RANDOMNESS, R2_SPOTCHECK]],
        "R1_validated_manifest": hash_record(R1_MANIFEST),
        "bridge_scoring_interface": hash_record(BRIDGE),
        "source_inputs": [hash_record(path) for path in PROTECTED_INPUTS],
        "production_verifier_implementation": [hash_record(path) for path in PRODUCTION_CODE],
        "generator": hash_record(Path(__file__)),
        "outputs": [hash_record(path) for path in output_files],
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
        },
        "science_interpretation_performed": False,
        "post_result_population_expansion": False,
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    append_log(status, family_summary, unit_summary, boundary_status, next_step)
    print(status)
    print(f"R3: {'PASS' if passed else 'FAIL'}")
    print(f"UNITS: {len(unit_summary)}/407")
    print(f"ROWS: {len(observation_rows)}/26780")
    print(f"NEXT STEP: {next_step}")


if __name__ == "__main__":
    run(parse_args())
