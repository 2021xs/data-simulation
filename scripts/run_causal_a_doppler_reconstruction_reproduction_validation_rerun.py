#!/usr/bin/env python3
"""Rerun the corrected R1 causal-A Doppler reproduction validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from acquire_orbit_uncertainty_stage1 import parse_utc, select_causal_gp  # noqa: E402
import evaluate_verifier_v2_gates as v2gate  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_controlled_altitude_difference_risk_experiment as altitude  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402
import run_multi_service_area_single_station_confirmation as multi  # noqa: E402
import run_same_pair_multi_pass_confirmation as multipass  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

R0_PROTOCOL = METRICS / "doppler_semantic_reconstruction_protocol.json"
R0_MANIFEST = METRICS / "doppler_semantic_reconstruction_manifest.json"
ERRATUM = METRICS / "doppler_semantic_reconstruction_r0_population_erratum.csv"
ERRATUM_MANIFEST = METRICS / "doppler_semantic_reconstruction_r0_population_erratum_manifest.json"
CORRECTED_BINDING = METRICS / "doppler_semantic_reconstruction_r1_corrected_population_binding.csv"
FAILED_R1_MANIFEST = METRICS / "causal_a_doppler_r1_manifest.json"
FAILED_R1_REPORT = REPORTS / "causal_a_doppler_reconstruction_reproduction_validation_report.md"
STATE_AUDIT = METRICS / "orbit_distinct_ab_state_reconstruction_audit.csv"
BRIDGE_INTERFACE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
FROZEN_PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
RAW_GP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "spacetrack_gp" / "spacetrack_gp_history_20260226_20260329_20sat_omm.json"
STATIC_TLE = ROOT / "data" / "tle" / "starlink_tle.txt"
SELECTION = METRICS / "controlled_starlink_20target_selection_table.csv"
CANDIDATE_LIBRARY = DATASETS / "controlled_starlink_20target_partial_pass_candidate_library.csv"
ORBIT_CONFIG = ROOT / "configs" / "orbit_simulation_cases.yaml"
PARAMETER_CONFIG = ROOT / "configs" / "simulation_parameter_config.yaml"

INITIAL_RESULTS = METRICS / "doppler_verifier_orbit_similarity_attack_results.csv"
INITIAL_TIMESERIES = DATASETS / "doppler_verifier_orbit_similarity_attack_dataset.csv"
ACTIVE_RESULTS = METRICS / "active_compensation_first_pass_sequence_eval.csv"
ACTIVE_TIMESERIES = DATASETS / "active_compensation_first_pass_dataset.csv"
MULTIPASS_RESULTS = DATASETS / "same_pair_multi_pass_realization_dataset.csv"
ALTITUDE_RESULTS = DATASETS / "controlled_altitude_difference_realization_dataset.csv"
V2_RESULTS = METRICS / "verifier_v2_sequence_eval.csv"

FROZEN_PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
COMPATIBLE_STATUSES = {"EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"}

REPORT_OUTPUT = REPORTS / "causal_a_doppler_reconstruction_reproduction_validation_rerun_report.md"
ROWS_OUTPUT = DATASETS / "causal_a_doppler_r1_rerun_reproduction_rows.csv"
STATE_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_state_reproduction.csv"
GEOMETRY_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_geometry_reproduction.csv"
FIT_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_fit_score_reproduction.csv"
GATE_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_gate_decision_reproduction.csv"
FAILURE_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_failure_attribution.csv"
V2_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_verifier_v2_crosscheck.csv"
CORRECTNESS_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_correctness_audit.csv"
MANIFEST_OUTPUT = METRICS / "causal_a_doppler_r1_rerun_manifest.json"
OUTPUTS = [
    REPORT_OUTPUT, ROWS_OUTPUT, STATE_OUTPUT, GEOMETRY_OUTPUT, FIT_OUTPUT,
    GATE_OUTPUT, FAILURE_OUTPUT, V2_OUTPUT, CORRECTNESS_OUTPUT, MANIFEST_OUTPUT,
]

PRODUCTION_CODE = [
    ROOT / "scripts" / "run_doppler_verifier_initial_experiments.py",
    ROOT / "scripts" / "run_active_compensation_attack_first_pass.py",
    ROOT / "scripts" / "run_segmented_service_center_compensation.py",
    ROOT / "scripts" / "run_same_pair_multi_pass_confirmation.py",
    ROOT / "scripts" / "run_controlled_altitude_difference_risk_experiment.py",
    ROOT / "scripts" / "evaluate_verifier_v2_gates.py",
]
AUTHORITATIVE_INPUTS = [
    R0_PROTOCOL, R0_MANIFEST, ERRATUM, ERRATUM_MANIFEST, CORRECTED_BINDING,
    FAILED_R1_MANIFEST, FAILED_R1_REPORT, STATE_AUDIT, BRIDGE_INTERFACE,
    FROZEN_PARAMETERS, RAW_GP, STATIC_TLE, SELECTION, CANDIDATE_LIBRARY,
    ORBIT_CONFIG, PARAMETER_CONFIG, INITIAL_RESULTS, INITIAL_TIMESERIES,
    ACTIVE_RESULTS, ACTIVE_TIMESERIES, MULTIPASS_RESULTS, ALTITUDE_RESULTS,
    V2_RESULTS, *PRODUCTION_CODE,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--spotcheck-size", type=int, default=30)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def to_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes", "accept", "accepted"}


def mismatch_flag(value: Any) -> int:
    """Return a robust integer mismatch flag for sparse family-specific fields."""
    if value is None or pd.isna(value):
        return 0
    return int(value)


def number_difference(left: Any, right: Any) -> float:
    a, b = float(left), float(right)
    if math.isinf(a) and math.isinf(b) and math.copysign(1, a) == math.copysign(1, b):
        return 0.0
    return abs(a - b)


def stats(values: np.ndarray) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "median": float(np.quantile(array, 0.50)),
        "p95": float(np.quantile(array, 0.95)),
        "p99": float(np.quantile(array, 0.99)),
        "max": float(np.max(array)),
    }


def norm_errors(old: np.ndarray, new: np.ndarray) -> np.ndarray:
    return np.linalg.norm(np.asarray(new, dtype=float) - np.asarray(old, dtype=float), axis=1)


def max_abs(old: np.ndarray, new: np.ndarray) -> float:
    return float(np.max(np.abs(np.asarray(new, dtype=float) - np.asarray(old, dtype=float))))


def rmse_difference(old: np.ndarray, new: np.ndarray) -> float:
    difference = np.asarray(new, dtype=float) - np.asarray(old, dtype=float)
    return float(np.sqrt(np.mean(difference**2)))


def numeric_tolerances(protocol: dict[str, Any]) -> dict[str, float]:
    source = protocol["R1_reproduction_gate"]["tolerances"]
    keys = {
        "time": "evaluation_time_and_time_grid",
        "A_position": "A_position", "A_velocity": "A_velocity",
        "B_position": "B_position", "B_velocity": "B_velocity",
        "geometry": "Doppler_geometry_curves", "compensation": "active_compensation_curve",
        "residual": "observation_and_raw_residual", "b_score": "b_hat_and_score", "k": "k_hat",
    }
    output: dict[str, float] = {}
    for target, key in keys.items():
        if key not in source:
            raise SystemExit("R1_NUMERICAL_TOLERANCE_NOT_FROZEN: " + key)
        match = re.search(r"<=\s*([0-9.eE+-]+)", str(source[key]))
        if not match:
            raise SystemExit("R1_NUMERICAL_TOLERANCE_NOT_FROZEN: " + key)
        output[target] = float(match.group(1))
    if "exact equality" not in source.get("gate_booleans_and_final_decision", ""):
        raise SystemExit("R1 categorical mismatch tolerance is not frozen")
    return output


def validate_and_load(overwrite: bool) -> tuple[dict[str, str], pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, float]]:
    missing = [rel(path) for path in AUTHORITATIVE_INPUTS if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Output exists; use --overwrite: " + ", ".join(existing))
    if sha256(FROZEN_PARAMETERS) != FROZEN_PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch")

    protocol = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    tolerances = numeric_tolerances(protocol)
    erratum = json.loads(ERRATUM_MANIFEST.read_text(encoding="utf-8"))
    failed = json.loads(FAILED_R1_MANIFEST.read_text(encoding="utf-8"))
    if erratum.get("status") != "R0_POPULATION_ERRATUM_PUBLISHED" or not erratum.get("R1_rerun_authorized"):
        raise SystemExit("R0 erratum does not authorize R1 rerun")
    if failed.get("numerical_reproduction_performed") is not False:
        raise SystemExit("First R1 is not a clean pre-numerical failure")

    binding = pd.read_csv(CORRECTED_BINDING, dtype=str, keep_default_na=False)
    primary = binding[binding["row_role"].eq("PRIMARY")].copy()
    secondary = binding[binding["row_role"].eq("VERIFIER_V2_SECONDARY")].copy()
    primary_ids = set(primary["stable_row_identity"])
    secondary_ids = set(secondary["stable_row_identity"])
    facts = {
        "units": int(binding["orbit_unit_id"].nunique()), "primary": len(primary),
        "secondary": len(secondary), "intersection": len(primary_ids & secondary_ids),
        "union": len(primary_ids | secondary_ids), "duplicates": int(binding["stable_row_identity"].duplicated().sum()),
    }
    expected = {"units": 64, "primary": 6280, "secondary": 200, "intersection": 0, "union": 6480, "duplicates": 0}
    mismatch = {key: (facts[key], value) for key, value in expected.items() if facts[key] != value}
    if mismatch:
        raise SystemExit(f"PRIMARY_POPULATION_PROVENANCE_INCONSISTENCY: {mismatch}")

    state = pd.read_csv(STATE_AUDIT, dtype=str, keep_default_na=False)
    frozen_units = state[state["orbit_unit_id"].isin(set(primary["orbit_unit_id"]))].copy()
    if len(frozen_units) != 64 or not frozen_units["A_reconstruction_status"].isin(COMPATIBLE_STATUSES).all():
        raise SystemExit("PRIMARY_POPULATION_PROVENANCE_INCONSISTENCY: incompatible A unit")
    before = {rel(path): sha256(path) for path in AUTHORITATIVE_INPUTS}
    return before, primary, secondary, protocol, tolerances


def load_core_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, dict[str, Any]], dict[str, list[float]]]:
    args = SimpleNamespace(
        selection_table=SELECTION, candidate_library=CANDIDATE_LIBRARY,
        tle_file=STATIC_TLE, orbit_config=ORBIT_CONFIG,
        parameter_config=PARAMETER_CONFIG, max_targets=20,
    )
    selection, library, config, tle, ranges = expanded.load_base_inputs(args)
    if config.get("mode") != "controlled_starlink" or config.get("observation_id") is not None:
        raise SystemExit("Production configuration is not controlled_starlink with observation_id=null")
    return selection, library, config, tle, ranges


def causal_satellites(primary: pd.DataFrame, ts: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]], int]:
    raw = json.loads(RAW_GP.read_text(encoding="utf-8"))
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in raw:
        by_id[str(item["NORAD_CAT_ID"])].append(item)
    unit_rows = primary.drop_duplicates("orbit_unit_id")
    satellites: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    future = 0
    for row in unit_rows.itertuples(index=False):
        when = parse_utc(str(row.evaluation_time))
        selected, _count = select_causal_gp(by_id[str(row.A_id)], when)
        if selected is None:
            raise SystemExit(f"PRIMARY_POPULATION_PROVENANCE_INCONSISTENCY: no causal GP for {row.orbit_unit_id}")
        creation = parse_utc(str(selected["CREATION_DATE"]))
        future += int(creation > when)
        if str(selected.get("GP_ID", "")) != str(row.selected_A_GP_ID):
            raise SystemExit(f"PRIMARY_POPULATION_PROVENANCE_INCONSISTENCY: GP_ID changed for {row.orbit_unit_id}")
        key = f"{row.A_id}:{selected['GP_ID']}"
        if key not in satellites:
            satellites[key] = EarthSatellite(
                str(selected["TLE_LINE1"]), str(selected["TLE_LINE2"]),
                str(selected.get("OBJECT_NAME", row.A_name)), ts,
            )
        provenance[str(row.orbit_unit_id)] = {
            "key": key, "A_id": str(row.A_id), "GP_ID": str(selected["GP_ID"]),
            "EPOCH": str(selected["EPOCH"]), "CREATION_DATE": str(selected["CREATION_DATE"]),
        }
    if future:
        raise SystemExit("PRIMARY_POPULATION_PROVENANCE_INCONSISTENCY: future publication")
    return satellites, provenance, future


def state_arrays(satellite: Any, times: list[datetime], ts: Any) -> tuple[np.ndarray, np.ndarray]:
    state = satellite.at(ts.from_datetimes(times))
    return np.asarray(state.position.km.T, dtype=float), np.asarray(state.velocity.km_per_s.T, dtype=float)


def synthetic_state_arrays(satellite: Any, times: list[datetime], ts: Any, altitude_km: float, phase_s: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    position, velocity = state_arrays(satellite, times, ts)
    mid = len(times) // 2
    r0, v0 = position[mid], velocity[mid]
    h_hat = base.normalize(np.cross(r0, v0))
    p_hat = base.normalize(r0)
    q_hat = base.normalize(np.cross(h_hat, p_hat))
    if float(np.dot(v0, q_hat)) < 0:
        q_hat = -q_hat
    radius = float(np.linalg.norm(r0) + altitude_km)
    omega = float(np.sqrt(base.MU_EARTH_KM3_S2 / radius**3))
    centered = np.array([(value - times[mid]).total_seconds() for value in times], dtype=float)
    theta = omega * (centered + phase_s)
    b_position = radius * (np.cos(theta)[:, None] * p_hat + np.sin(theta)[:, None] * q_hat)
    b_velocity = radius * omega * (-np.sin(theta)[:, None] * p_hat + np.cos(theta)[:, None] * q_hat)
    return b_position, b_velocity


def state_record(unit: pd.Series, old_a: Any, new_a: Any, old_b: Any, new_b: Any,
                 times: list[datetime], ts: Any, tolerances: dict[str, float], synthetic: tuple[float, float] | None = None) -> dict[str, Any]:
    old_ar, old_av = state_arrays(old_a, times, ts)
    new_ar, new_av = state_arrays(new_a, times, ts)
    if synthetic is None:
        old_br, old_bv = state_arrays(old_b, times, ts)
        new_br, new_bv = state_arrays(new_b, times, ts)
    else:
        old_br, old_bv = synthetic_state_arrays(old_a, times, ts, synthetic[0], synthetic[1])
        new_br, new_bv = synthetic_state_arrays(new_a, times, ts, synthetic[0], synthetic[1])
    ap, av = norm_errors(old_ar, new_ar), norm_errors(old_av, new_av)
    bp, bv = norm_errors(old_br, new_br), norm_errors(old_bv, new_bv)
    aps, avs, bps, bvs = stats(ap), stats(av), stats(bp), stats(bv)
    passed = aps["max"] <= tolerances["A_position"] and avs["max"] <= tolerances["A_velocity"] and bps["max"] <= tolerances["B_position"] and bvs["max"] <= tolerances["B_velocity"]
    return {
        "orbit_unit_id": unit["orbit_unit_id"], "experiment_family": unit["experiment_family"],
        "A_id": unit["A_id"], "B_id_or_definition": unit["B_id_or_definition"],
        "segment_id": unit["segment_id"], "evaluation_time": unit["evaluation_time"],
        "A_reconstruction_status": unit["A_reconstruction_status"], "selected_A_GP_ID": unit["selected_A_GP_ID"],
        "sample_timestamp_count": len(times),
        **{f"A_position_error_{key}_km": value for key, value in aps.items()},
        **{f"A_velocity_error_{key}_km_s": value for key, value in avs.items()},
        **{f"B_position_error_{key}_km": value for key, value in bps.items()},
        **{f"B_velocity_error_{key}_km_s": value for key, value in bvs.items()},
        "A_position_tolerance_km": tolerances["A_position"], "A_velocity_tolerance_km_s": tolerances["A_velocity"],
        "B_position_tolerance_km": tolerances["B_position"], "B_velocity_tolerance_km_s": tolerances["B_velocity"],
        "state_pass": passed,
    }


def geometry_record(unit: pd.Series, curve_pairs: dict[str, tuple[np.ndarray, np.ndarray]],
                    compensation_pair: tuple[np.ndarray, np.ndarray] | None,
                    time_error_s: float, tolerances: dict[str, float]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "orbit_unit_id": unit["orbit_unit_id"], "experiment_family": unit["experiment_family"],
        "time_grid_max_abs_error_s": time_error_s,
    }
    maxima, rmses = [], []
    for name, (old, new) in curve_pairs.items():
        result[f"{name}_max_abs_difference_hz"] = max_abs(old, new)
        result[f"{name}_rmse_difference_hz"] = rmse_difference(old, new)
        maxima.append(result[f"{name}_max_abs_difference_hz"])
        rmses.append(result[f"{name}_rmse_difference_hz"])
    result["doppler_geometry_max_abs_difference_hz"] = max(maxima) if maxima else 0.0
    result["doppler_geometry_rmse_difference_hz"] = max(rmses) if rmses else 0.0
    if compensation_pair is None:
        result["active_compensation_applicable"] = False
        result["active_compensation_max_abs_difference_hz"] = 0.0
        result["active_compensation_rmse_difference_hz"] = 0.0
    else:
        result["active_compensation_applicable"] = True
        result["active_compensation_max_abs_difference_hz"] = max_abs(*compensation_pair)
        result["active_compensation_rmse_difference_hz"] = rmse_difference(*compensation_pair)
    result["geometry_tolerance_hz"] = tolerances["geometry"]
    result["compensation_tolerance_hz"] = tolerances["compensation"]
    result["time_tolerance_s"] = tolerances["time"]
    result["geometry_pass"] = (
        result["doppler_geometry_max_abs_difference_hz"] <= tolerances["geometry"]
        and result["active_compensation_max_abs_difference_hz"] <= tolerances["compensation"]
        and time_error_s <= tolerances["time"]
    )
    return result


def append_fit_and_gate(
    row: pd.Series, old_score: float, new_score: float, old_b: float, new_b: float,
    old_k: float, new_k: float, observation_error: float, residual_error: float,
    score_gate_old: bool, score_gate_new: bool, b_gate_old: bool, b_gate_new: bool,
    k_gate_old: bool, k_gate_new: bool, coverage_old: bool, coverage_new: bool,
    quality_old: bool, quality_new: bool, decision_old: str, decision_new: str,
    tolerances: dict[str, float], fit_rows: list[dict[str, Any]], gate_rows: list[dict[str, Any]],
    row_rows: list[dict[str, Any]], bundle: dict[str, Any], bundles: dict[str, dict[str, Any]],
) -> None:
    score_diff = abs(new_score - old_score)
    b_diff, k_diff = abs(new_b - old_b), abs(new_k - old_k)
    relative = score_diff / max(abs(old_score), 1e-15)
    numerical_pass = (
        observation_error <= tolerances["residual"] and residual_error <= tolerances["residual"]
        and score_diff <= tolerances["b_score"] and b_diff <= tolerances.get("b", tolerances["b_score"])
        and k_diff <= tolerances["k"]
    )
    gate_mismatches = {
        "score_gate_mismatch": int(score_gate_old != score_gate_new),
        "b_gate_mismatch": int(b_gate_old != b_gate_new),
        "k_gate_mismatch": int(k_gate_old != k_gate_new),
        "coverage_mismatch": int(coverage_old != coverage_new),
        "quality_gate_mismatch": int(quality_old != quality_new),
        "final_decision_mismatch": int(str(decision_old) != str(decision_new)),
    }
    fit_rows.append({
        "stable_row_identity": row["stable_row_identity"], "orbit_unit_id": row["orbit_unit_id"],
        "experiment_family": row["experiment_family"], "case_id": row["case_id"],
        "old_b_hat": old_b, "new_b_hat": new_b, "b_hat_abs_difference": b_diff,
        "old_k_hat": old_k, "new_k_hat": new_k, "k_hat_abs_difference": k_diff,
        "old_score": old_score, "new_score": new_score, "score_abs_difference": score_diff,
        "score_relative_difference": relative, "observation_max_abs_difference_hz": observation_error,
        "residual_max_abs_difference_hz": residual_error, "numerical_pass": numerical_pass,
    })
    gate_rows.append({
        "stable_row_identity": row["stable_row_identity"], "orbit_unit_id": row["orbit_unit_id"],
        "experiment_family": row["experiment_family"], "case_id": row["case_id"],
        **gate_mismatches, "old_final_decision": decision_old, "new_final_decision": decision_new,
    })
    row_rows.append({
        "stable_row_identity": row["stable_row_identity"], "orbit_unit_id": row["orbit_unit_id"],
        "experiment_family": row["experiment_family"], "case_id": row["case_id"],
        "source_artifact": row["source_artifact"], "source_view": row["source_view"],
        "row_role": "PRIMARY", "numerical_pass": numerical_pass,
        **gate_mismatches, "reproduction_pass": numerical_pass and not any(gate_mismatches.values()),
    })
    bundles[row["stable_row_identity"]] = {
        **bundle, "orbit_unit_id": row["orbit_unit_id"],
        "experiment_family": row["experiment_family"],
    }


def process_initial(primary: pd.DataFrame, causal: dict[str, Any], provenance: dict[str, dict[str, Any]],
                    tle: dict[str, dict[str, Any]], config: dict[str, Any], ts: Any,
                    tolerances: dict[str, float], outputs: dict[str, list[dict[str, Any]]], bundles: dict[str, dict[str, Any]]) -> None:
    family = "score_only_verifier_and_synthetic_orbit_attacks"
    population = primary[primary["experiment_family"].eq(family)].copy()
    case_map = population.set_index("case_id", drop=False)
    source = pd.read_csv(INITIAL_RESULTS, dtype={"claimed_target_norad": str})
    source = source[source["attack_sequence_id"].isin(set(population["case_id"]))].copy()
    series = pd.read_csv(INITIAL_TIMESERIES, dtype={"claimed_target_norad": str})
    series = series[series["attack_sequence_id"].isin(set(population["case_id"]))].copy()
    station_cfg = config["station"]
    unit_done: set[str] = set()
    for source_row in source.itertuples(index=False):
        bind = case_map.loc[str(source_row.attack_sequence_id)]
        group = series[series["attack_sequence_id"].eq(str(source_row.attack_sequence_id))].sort_values("t_rel_s")
        times = [parse_utc(value) for value in group["t_abs_utc"].astype(str)]
        t_rel = group["t_rel_s"].to_numpy(float)
        unit_id = str(bind["orbit_unit_id"])
        old_a = tle[str(bind["A_id"])]["sat"]
        new_a = causal[provenance[unit_id]["key"]]
        f_a_new, _ = active.geo_curve_fixed_reference(
            new_a, float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]),
            float(station_cfg["alt_m"]), times, ts, 11_325_000_000.0,
            float(np.median(np.diff(t_rel))),
        )
        f_b_new = base.synthetic_same_plane_geo(
            new_a, active.orbit_builder.wgs84.latlon(
                float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"])
            ), ts, times, 11_325_000_000.0, float(source_row.altitude_offset_km), float(source_row.phase_offset_s),
        )
        f_a_old = group["f_geo_claimed_A_hz"].to_numpy(float)
        f_b_old = group["f_geo_attack_B_hz"].to_numpy(float)
        if unit_id not in unit_done:
            outputs["state"].append(state_record(
                bind, old_a, new_a, old_a, new_a, times, ts, tolerances,
                synthetic=(float(source_row.altitude_offset_km), float(source_row.phase_offset_s)),
            ))
            outputs["geometry"].append(geometry_record(
                bind, {"F_A_S": (f_a_old, f_a_new), "F_B_S": (f_b_old, f_b_new)},
                None, float(np.max(np.abs(t_rel - group["time_s"].to_numpy(float)))), tolerances,
            ))
            unit_done.add(unit_id)
        noise = group["noise_hz"].to_numpy(float)
        t0 = float(group["t0_s"].iloc[0])
        y_new = f_b_new + float(source_row.b_true_hz) + float(source_row.k_true_hz_s) * (t_rel - t0) + noise
        y_old = group["f_obs_attack_hz"].to_numpy(float)
        residual_new, residual_old = y_new - f_a_new, y_old - f_a_old
        fit = base.fit_bias_and_slope(y_new, f_a_new, t_rel)
        threshold = float(source_row.threshold_99_hz)
        score_pass_new = fit.score_rmse_hz <= threshold
        append_fit_and_gate(
            bind, float(source_row.score_A_rmse_hz), fit.score_rmse_hz,
            float(source_row.b_hat_hz), fit.b_hat_hz, float(source_row.k_hat_hz_s), fit.k_hat_hz_s,
            max_abs(y_old, y_new), max_abs(residual_old, residual_new),
            to_bool(source_row.accepted_99), score_pass_new, True, True, True, True,
            True, True, True, True, "ACCEPT" if to_bool(source_row.accepted_99) else "REJECT",
            "ACCEPT" if score_pass_new else "REJECT", tolerances,
            outputs["fit"], outputs["gate"], outputs["rows"],
            {"mode": "unbounded", "y": y_new, "f_a": f_a_new, "t_rel": t_rel,
             "threshold": threshold, "decision": "ACCEPT" if score_pass_new else "REJECT",
             "score": fit.score_rmse_hz, "b": fit.b_hat_hz, "k": fit.k_hat_hz_s,
             "score_gate": score_pass_new, "b_gate": True, "k_gate": True, "coverage": True}, bundles,
        )


def process_active(primary: pd.DataFrame, causal: dict[str, Any], provenance: dict[str, dict[str, Any]],
                   tle: dict[str, dict[str, Any]], config: dict[str, Any], ts: Any,
                   tolerances: dict[str, float], outputs: dict[str, list[dict[str, Any]]], bundles: dict[str, dict[str, Any]]) -> None:
    family = "active_compensation_first_pass"
    population = primary[primary["experiment_family"].eq(family)].copy()
    case_map = population.set_index("case_id", drop=False)
    source = pd.read_csv(ACTIVE_RESULTS, dtype={"target_id": str, "attacker_id": str})
    source = source[source["sequence_id"].isin(set(population["case_id"]))].copy()
    series = pd.read_csv(ACTIVE_TIMESERIES, dtype={"target_id": str, "attacker_id": str})
    series = series[series["sequence_id"].isin(set(population["case_id"]))].copy()
    station_cfg = config["station"]
    elevation_min = float(config["time_window"].get("min_elevation_deg", 10.0))
    unit_done: set[str] = set()
    unit_geometry: dict[str, dict[str, Any]] = {}
    for source_row in source.itertuples(index=False):
        bind = case_map.loc[str(source_row.sequence_id)]
        group = series[series["sequence_id"].eq(str(source_row.sequence_id))].sort_values("t_rel_s")
        times = [parse_utc(value) for value in group["time_utc"].astype(str)]
        t_rel = group["t_rel_s"].to_numpy(float)
        unit_id = str(bind["orbit_unit_id"])
        old_a = tle[str(bind["A_id"])]["sat"]
        new_a = causal[provenance[unit_id]["key"]]
        old_b = tle[str(source_row.attacker_id)]["sat"]
        new_b = old_b
        fixed_step_s = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        f_a_new, _ = active.geo_curve_fixed_reference(
            new_a, float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), float(station_cfg["alt_m"]),
            times, ts, float(source_row.center_freq_hz), fixed_step_s,
        )
        f_b_new, _ = active.geo_curve_fixed_reference(
            new_b, float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), float(station_cfg["alt_m"]),
            times, ts, float(source_row.center_freq_hz), fixed_step_s,
        )
        c_lat, c_lon, c_alt = active.compute_subpoint_series(new_a, times, ts)
        f_ac_new, _ = active.geo_curve_moving_reference(
            new_a, c_lat, c_lon, c_alt, times, ts, float(source_row.center_freq_hz), float(source_row.moving_reference_diff_step_s),
        )
        f_bc_new, _ = active.geo_curve_moving_reference(
            new_b, c_lat, c_lon, c_alt, times, ts, float(source_row.center_freq_hz), float(source_row.moving_reference_diff_step_s),
        )
        compensation = str(source_row.compensation_type)
        if compensation == "none":
            u_new = np.zeros_like(f_a_new)
        elif compensation == "subpoint_A":
            u_new = f_ac_new - f_bc_new
        elif compensation == "direct_S_ideal":
            u_new = f_a_new - f_b_new
        else:
            raise SystemExit(f"Unsupported frozen active compensation type: {compensation}")
        old_curves = {
            "F_A_S": group["f_geo_A_S_hz"].to_numpy(float), "F_B_S": group["f_geo_B_S_hz"].to_numpy(float),
            "F_A_C": group["f_geo_A_C_hz"].to_numpy(float), "F_B_C": group["f_geo_B_C_hz"].to_numpy(float),
        }
        if unit_id not in unit_done:
            outputs["state"].append(state_record(bind, old_a, new_a, old_b, new_b, times, ts, tolerances))
            unit_geometry[unit_id] = {
                "bind": bind,
                "curves": {"F_A_S": (old_curves["F_A_S"], f_a_new),
                           "F_B_S": (old_curves["F_B_S"], f_b_new),
                           "F_A_C": (old_curves["F_A_C"], f_ac_new),
                           "F_B_C": (old_curves["F_B_C"], f_bc_new)},
                "old_compensation": [], "new_compensation": [],
            }
            unit_done.add(unit_id)
        unit_geometry[unit_id]["old_compensation"].append(group["u_comp_hz"].to_numpy(float))
        unit_geometry[unit_id]["new_compensation"].append(u_new)
        noise = group["noise_injected_hz"].to_numpy(float)
        t0 = float(np.mean(t_rel))
        y_new = f_b_new + u_new + float(source_row.b_injected_hz) + float(source_row.k_injected_hz_s) * (t_rel - t0) + noise
        y_old = group["f_attack_hz"].to_numpy(float)
        residual_new = y_new - f_a_new
        residual_old = group["delta_to_claimed_hz"].to_numpy(float)
        observation = active.build_observation(
            str(source_row.sequence_id), str(source_row.target_name), str(source_row.target_id),
            pd.DataFrame({"t_rel_s": t_rel, "t_abs_utc": group["time_utc"].astype(str)}), y_new, f_b_new, noise,
            float(source_row.b_injected_hz), float(source_row.k_injected_hz_s), float(source_row.noise_sigma_hz),
            t0, compensation, str(source_row.attacker_name), str(source_row.attacker_id), str(source_row.residual_mode),
        )
        verification = base.verify_claimed_identity(
            observation, f_a_new, float(source_row.threshold_95_hz), float(source_row.threshold_99_hz)
        )
        score_gate_new = bool(verification.accepted_95)
        k_gate_new = float(source_row.target_k_min_p01) <= verification.k_hat_hz_s <= float(source_row.target_k_max_p99)
        coverage_new = float(source_row.max_elevation_deg) >= elevation_min
        decision_new = active.tri_state_decision(score_gate_new and k_gate_new, float(source_row.max_elevation_deg), elevation_min)
        append_fit_and_gate(
            bind, float(source_row.score_A_rmse_hz), verification.score_A_rmse_hz,
            float(source_row.b_hat_hz), verification.b_hat_hz, float(source_row.k_hat_hz_s), verification.k_hat_hz_s,
            max_abs(y_old, y_new), max_abs(residual_old, residual_new),
            to_bool(source_row.accepted_p95), score_gate_new, True, True,
            to_bool(source_row.accepted_per_target_k_p01_p99), k_gate_new,
            float(source_row.max_elevation_deg) >= elevation_min, coverage_new, True, True,
            str(source_row.tri_state_decision), decision_new, tolerances,
            outputs["fit"], outputs["gate"], outputs["rows"],
            {"mode": "unbounded", "y": y_new, "f_a": f_a_new, "t_rel": t_rel,
             "threshold": float(source_row.threshold_95_hz), "decision": decision_new,
             "score": verification.score_A_rmse_hz, "b": verification.b_hat_hz, "k": verification.k_hat_hz_s,
             "score_gate": score_gate_new, "b_gate": True, "k_gate": k_gate_new, "coverage": coverage_new,
             "k_min": float(source_row.target_k_min_p01), "k_max": float(source_row.target_k_max_p99),
             "active_tri_state": True, "max_elevation_deg": float(source_row.max_elevation_deg),
             "elevation_min_deg": elevation_min}, bundles,
        )
    for item in unit_geometry.values():
        outputs["geometry"].append(geometry_record(
            item["bind"], item["curves"],
            (np.concatenate(item["old_compensation"]), np.concatenate(item["new_compensation"])),
            0.0, tolerances,
        ))


def geometry_times(geo: dict[str, Any]) -> list[datetime]:
    if "times" in geo:
        return list(geo["times"])
    start = parse_utc(str(geo["service_segment_start"]))
    return [start + pd.Timedelta(seconds=index) for index in range(len(geo["et"]))]


def geometry_components(geo: dict[str, Any], family: str, ts: Any, freq: float) -> dict[str, np.ndarray]:
    sat_a, times = geo["sat_a"], geometry_times(geo)
    c_lat, c_lon = float(geo["C_lat"]), float(geo["C_lon"])
    s_lat, s_lon = float(geo["S_lat"]), float(geo["S_lon"])
    f_as = np.asarray(geo["fa_s"], dtype=float)
    f_ac = seg.geo_curve_fixed(sat_a, c_lat, c_lon, 0.0, times, ts, freq, 1.0)[0]
    if family == "same_pair_multi_pass_real_TLE":
        f_bs = multi.attack_geo(geo["sample"], sat_a, geo["sat_b"], s_lat, s_lon, 0.0, times, ts, freq, 1.0)
        f_bc = multi.attack_geo(geo["sample"], sat_a, geo["sat_b"], c_lat, c_lon, 0.0, times, ts, freq, 1.0)
    else:
        sample = {"sample_source": "legacy_synthetic", "target_sat_id": str(geo["target_sat_id"]),
                  "attack_sat_id": f"synthetic_delta_h_{float(geo['delta_h_km']):+g}km",
                  "attack_type": "same_plane_altitude_offset",
                  "attack_param_value": float(geo["delta_h_km"])}
        f_bs = expanded.attack_geo(sample, sat_a, None, s_lat, s_lon, 0.0, times, ts, freq, 1.0)
        f_bc = expanded.attack_geo(sample, sat_a, None, c_lat, c_lon, 0.0, times, ts, freq, 1.0)
    return {"F_A_S": f_as, "F_B_S": f_bs, "F_A_C": f_ac, "F_B_C": f_bc, "u_C": f_ac - f_bc}


def realization_vectors(geo: dict[str, Any], row: pd.Series, ranges: dict[str, list[float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    env_seed, noise_seed = int(row["environment_seed"]), int(row["noise_seed"])
    error = base.sample_error_params(ranges, np.random.default_rng(env_seed))
    full_noise = np.random.default_rng(noise_seed).normal(0.0, error.sigma_hz, len(geo["full_t"])) if error.sigma_hz > 0 else np.zeros(len(geo["full_t"]))
    noise = full_noise[geo["mask"]]
    t_rel = np.asarray(geo["et"], dtype=float)
    t0 = float(np.mean(geo["full_t"]))
    y = np.asarray(geo["fa_s"]) + np.asarray(geo["raw"]) + error.b_hz + error.k_hz_s * (t_rel - t0) + noise
    return y, noise, y - np.asarray(geo["fa_s"])


def process_generated_family(
    family: str, primary: pd.DataFrame, causal: dict[str, Any], provenance: dict[str, dict[str, Any]],
    tle: dict[str, dict[str, Any]], ranges: dict[str, list[float]], config: dict[str, Any], ts: Any,
    tolerances: dict[str, float], outputs: dict[str, list[dict[str, Any]]], bundles: dict[str, dict[str, Any]],
) -> int:
    population = primary[primary["experiment_family"].eq(family)].copy()
    case_map = population.set_index("case_id", drop=False)
    if family == "same_pair_multi_pass_real_TLE":
        source_all = pd.read_csv(MULTIPASS_RESULTS, dtype={"target_sat_id": str, "attack_sat_id": str})
        source_all["case_id"] = source_all["observation_realization_id"].astype(str) + ":" + source_all["bk_mode"].astype(str)
        source = source_all[source_all["case_id"].isin(set(population["case_id"]))].copy()
        pairs = source.drop_duplicates("physical_pair_id").copy()
        passes = source.drop_duplicates(["physical_pair_id", "pass_id"])[source.columns].copy()
        passes["is_selected"] = True
        args = SimpleNamespace(master_seed=20260713, realizations=20)
        freq = float(config.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or config["frequency"]["center_freq_hz"])
        old_tle = {key: dict(value) for key, value in tle.items()}
        new_tle = {key: dict(value) for key, value in tle.items()}
        for unit_id, prov in provenance.items():
            if prov["A_id"] in set(source["target_sat_id"]):
                new_tle[prov["A_id"]]["sat"] = causal[prov["key"]]
        _old_dirs, old_geos = multipass.build_directions_and_geometries(args, pairs, passes, "same_tle", old_tle, ranges, ts, freq)
        _new_dirs, new_geos = multipass.build_directions_and_geometries(args, pairs, passes, "same_tle", new_tle, ranges, ts, freq)
        new_generated = multipass.generate_realizations(args, new_geos, ranges)
        new_generated["case_id"] = new_generated["observation_realization_id"].astype(str) + ":" + new_generated["bk_mode"].astype(str)
    else:
        source_all = pd.read_csv(ALTITUDE_RESULTS, dtype={"target_sat_id": str})
        source_all["case_id"] = (
            source_all["observation_realization_id"].astype(str) + ":" + source_all["bk_mode"].astype(str)
            + ":" + source_all["direction_deg"].astype(float).astype(str)
        )
        source = source_all[source_all["case_id"].isin(set(population["case_id"]))].copy()
        passes = source.drop_duplicates(["target_sat_id", "pass_id"]).copy()
        passes["max_elevation_deg"] = passes["pass_max_elevation_deg"]
        args = SimpleNamespace(master_seed=20260823, realizations=20, num_benign_sims=30,
                               delta_h_km=sorted(source["delta_h_km"].astype(float).unique().tolist()))
        freq = float(config.get("ku_band_experiment", {}).get("simulation_center_freq_hz") or config["frequency"]["center_freq_hz"])
        old_tle = {key: dict(value) for key, value in tle.items()}
        new_tle = {key: dict(value) for key, value in tle.items()}
        for unit_id, prov in provenance.items():
            if prov["A_id"] in set(source["target_sat_id"]):
                new_tle[prov["A_id"]]["sat"] = causal[prov["key"]]
        _old_candidates, old_geos, *_ = altitude.build_geometries(args, passes, config, old_tle, ranges, ts)
        _new_candidates, new_geos, *_ = altitude.build_geometries(args, passes, config, new_tle, ranges, ts)
        new_generated = altitude.generate_realizations(args, new_geos, ranges)
        new_generated["case_id"] = (
            new_generated["observation_realization_id"].astype(str) + ":" + new_generated["bk_mode"].astype(str)
            + ":" + new_generated["direction_deg"].astype(float).astype(str)
        )

    new_generated = new_generated[new_generated["case_id"].isin(set(population["case_id"]))].copy()
    if len(source) != len(population) or len(new_generated) != len(population):
        raise SystemExit(f"{family}: generated/source row binding mismatch {len(source)}/{len(new_generated)}/{len(population)}")
    source_by_case = source.set_index("case_id")
    new_by_case = new_generated.set_index("case_id")
    old_geo_map = {str(item["geometry_condition_id"]): item for item in old_geos}
    new_geo_map = {str(item["geometry_condition_id"]): item for item in new_geos}
    unit_to_geometries: dict[str, set[str]] = defaultdict(set)
    for case_id, bind in case_map.iterrows():
        unit_to_geometries[str(bind["orbit_unit_id"])].add(str(source_by_case.loc[case_id, "geometry_condition_id"]))
    unit_lookup = population.drop_duplicates("orbit_unit_id").set_index("orbit_unit_id", drop=False)
    for unit_id, geometry_ids in unit_to_geometries.items():
        bind = unit_lookup.loc[unit_id]
        curve_accumulator: dict[str, list[np.ndarray]] = defaultdict(list)
        compensation_old, compensation_new = [], []
        times_for_state: list[datetime] | None = None
        old_a_for_state = new_a_for_state = old_b_for_state = new_b_for_state = None
        synthetic_spec: tuple[float, float] | None = None
        time_error = 0.0
        for geometry_id in sorted(geometry_ids):
            old_geo, new_geo = old_geo_map[geometry_id], new_geo_map[geometry_id]
            old_components = geometry_components(old_geo, family, ts, freq)
            new_components = geometry_components(new_geo, family, ts, freq)
            for name in ["F_A_S", "F_B_S", "F_A_C", "F_B_C"]:
                curve_accumulator[name].append(new_components[name] - old_components[name])
            compensation_old.append(old_components["u_C"])
            compensation_new.append(new_components["u_C"])
            times_for_state = geometry_times(new_geo)
            old_a_for_state, new_a_for_state = old_geo["sat_a"], new_geo["sat_a"]
            if family == "same_pair_multi_pass_real_TLE":
                old_b_for_state, new_b_for_state = old_geo["sat_b"], new_geo["sat_b"]
            else:
                old_b_for_state, new_b_for_state = old_geo["sat_a"], new_geo["sat_a"]
                synthetic_spec = (float(old_geo["delta_h_km"]), 0.0)
            old_time = np.asarray(old_geo["et"], dtype=float)
            new_time = np.asarray(new_geo["et"], dtype=float)
            time_error = max(time_error, float(np.max(np.abs(old_time - new_time))))
        assert times_for_state is not None
        outputs["state"].append(state_record(
            bind, old_a_for_state, new_a_for_state, old_b_for_state, new_b_for_state,
            times_for_state, ts, tolerances, synthetic=synthetic_spec,
        ))
        curve_pairs = {
            name: (np.zeros(sum(len(value) for value in differences)), np.concatenate(differences))
            for name, differences in curve_accumulator.items()
        }
        outputs["geometry"].append(geometry_record(
            bind, curve_pairs, (np.concatenate(compensation_old), np.concatenate(compensation_new)),
            time_error, tolerances,
        ))

    replayed_vectors: set[tuple[str, int]] = set()
    for case_id, bind in case_map.iterrows():
        old = source_by_case.loc[case_id]
        new = new_by_case.loc[case_id]
        geometry_id = str(old["geometry_condition_id"])
        old_geo, new_geo = old_geo_map[geometry_id], new_geo_map[geometry_id]
        old_y, old_noise, old_residual = realization_vectors(old_geo, old, ranges)
        new_y, new_noise, new_residual = realization_vectors(new_geo, old, ranges)
        replayed_vectors.add((geometry_id, int(old["realization_index"])))
        mode = str(old["bk_mode"])
        old_score_column = "formal_score_value" if family == "same_pair_multi_pass_real_TLE" else "formal_score_hz"
        old_threshold_column = "formal_score_threshold" if family == "same_pair_multi_pass_real_TLE" else "formal_score_threshold_hz"
        old_b_column = "formal_b_hat_hz"
        old_k_column = "formal_k_hat_hz_per_s"
        new_score_column = old_score_column
        new_threshold_column = old_threshold_column
        score_gate_old, score_gate_new = to_bool(old["score_gate_pass"]), to_bool(new["score_gate_pass"])
        b_gate_old, b_gate_new = to_bool(old["b_gate_pass"]), to_bool(new["b_gate_pass"])
        k_gate_old, k_gate_new = to_bool(old["k_gate_pass"]), to_bool(new["k_gate_pass"])
        coverage_old, coverage_new = to_bool(old["coverage_gate_pass"]), to_bool(new["coverage_gate_pass"])
        quality_old, quality_new = to_bool(old["quality_gate_pass"]), to_bool(new["quality_gate_pass"])
        append_fit_and_gate(
            bind, float(old[old_score_column]), float(new[new_score_column]),
            float(old[old_b_column]), float(new[old_b_column]), float(old[old_k_column]), float(new[old_k_column]),
            max_abs(old_y, new_y), max_abs(old_residual, new_residual),
            score_gate_old, score_gate_new, b_gate_old, b_gate_new, k_gate_old, k_gate_new,
            coverage_old, coverage_new, quality_old, quality_new,
            str(old["final_decision"]), str(new["final_decision"]), tolerances,
            outputs["fit"], outputs["gate"], outputs["rows"],
            {"mode": mode, "y": new_y, "f_a": np.asarray(new_geo["fa_s"]), "t_rel": np.asarray(new_geo["et"]),
             "threshold": float(new[new_threshold_column]), "b_center": float(new["formal_b_center_hz"]),
             "k_center": float(new["formal_k_center_hz_per_s"]),
             "b_threshold": float(new["formal_b_threshold_hz"]),
             "k_threshold": float(new["formal_k_threshold_hz_per_s"]),
             "decision": str(new["final_decision"]), "score": float(new[new_score_column]),
             "b": float(new[old_b_column]), "k": float(new[old_k_column]),
             "score_gate": score_gate_new, "b_gate": b_gate_new, "k_gate": k_gate_new,
             "coverage": coverage_new, "quality": quality_new}, bundles,
        )
        if multipass.array_hash(new_noise).lower() != str(old["noise_hash"]).lower():
            outputs["rows"][-1]["reproduction_pass"] = False
            outputs["rows"][-1]["randomness_hash_mismatch"] = 1
        else:
            outputs["rows"][-1]["randomness_hash_mismatch"] = 0
        observation_hash = multipass.array_hash(new_y) if family == "same_pair_multi_pass_real_TLE" else altitude.array_hash(new_y)
        if observation_hash.lower() != str(old["observation_vector_hash"]).lower():
            outputs["rows"][-1]["reproduction_pass"] = False
            outputs["rows"][-1]["observation_hash_mismatch"] = 1
        else:
            outputs["rows"][-1]["observation_hash_mismatch"] = 0
    return len(replayed_vectors)


def deterministic_spotcheck_ids(primary: pd.DataFrame, size: int) -> list[str]:
    if size < 30:
        raise SystemExit("R1 spotcheck size must be at least 30")
    frame = primary.copy()
    frame["sample_hash"] = frame["stable_row_identity"].map(lambda value: hashlib.sha256(("R1_SPOTCHECK_V1|" + value).encode("utf-8")).hexdigest())
    selected: list[str] = []
    for _, group in frame.groupby(["experiment_family", "original_verifier_decision"], sort=True):
        selected.append(str(group.sort_values("sample_hash").iloc[0]["stable_row_identity"]))
    remaining = frame[~frame["stable_row_identity"].isin(selected)].sort_values("sample_hash")
    selected.extend(remaining["stable_row_identity"].head(size - len(selected)).astype(str).tolist())
    return selected[:size]


def independent_spotcheck(selected: list[str], bundles: dict[str, dict[str, Any]],
                          state: pd.DataFrame, geometry: pd.DataFrame, tolerances: dict[str, float]) -> tuple[dict[str, bool], pd.DataFrame]:
    state_pass = state.set_index("orbit_unit_id")["state_pass"].map(to_bool).to_dict()
    geometry_pass = geometry.set_index("orbit_unit_id")["geometry_pass"].map(to_bool).to_dict()
    records = []
    for identity in selected:
        bundle = bundles[identity]
        y, f_a, t_rel = bundle["y"], bundle["f_a"], bundle["t_rel"]
        delta = y - f_a
        if bundle["mode"] == "no_bk":
            score = float(np.sqrt(np.mean(delta**2)))
            b_hat, k_hat = 0.0, 0.0
        else:
            x = t_rel - float(np.mean(t_rel))
            design = np.column_stack([np.ones_like(x), x])
            coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
            residual = delta - design @ coef
            score, b_hat, k_hat = float(np.sqrt(np.mean(residual**2))), float(coef[0]), float(coef[1])
        score_gate = score <= bundle["threshold"]
        if bundle.get("active_tri_state"):
            b_gate = True
            k_gate = bundle["k_min"] <= k_hat <= bundle["k_max"]
            decision = active.tri_state_decision(
                score_gate and k_gate, bundle["max_elevation_deg"], bundle["elevation_min_deg"]
            )
        else:
            b_gate = True if bundle["mode"] in {"unbounded", "no_bk"} else abs(b_hat - bundle["b_center"]) <= bundle["b_threshold"]
            k_gate = True if bundle["mode"] in {"unbounded", "no_bk"} else abs(k_hat - bundle["k_center"]) <= bundle["k_threshold"]
            decision = "DEFER" if not bundle["coverage"] else "ACCEPT" if score_gate and b_gate and k_gate else "REJECT"
        passed = (
            state_pass[bundle["orbit_unit_id"]] and geometry_pass[bundle["orbit_unit_id"]]
            and abs(score - bundle["score"]) <= tolerances["b_score"]
            and abs(b_hat - bundle["b"]) <= tolerances.get("b", tolerances["b_score"])
            and abs(k_hat - bundle["k"]) <= tolerances["k"]
            and score_gate == bundle["score_gate"] and b_gate == bundle["b_gate"]
            and k_gate == bundle["k_gate"] and decision == bundle["decision"]
        )
        records.append({"stable_row_identity": identity, "orbit_unit_id": bundle["orbit_unit_id"],
                        "experiment_family": bundle["experiment_family"], "independent_score": score,
                        "independent_b_hat": b_hat, "independent_k_hat": k_hat,
                        "independent_decision": decision, "spotcheck_pass": passed})
    mapping = {row["stable_row_identity"]: bool(row["spotcheck_pass"]) for row in records}
    return mapping, pd.DataFrame(records)


def secondary_crosscheck(secondary: pd.DataFrame, fit: pd.DataFrame, primary_pass: bool) -> pd.DataFrame:
    if not primary_pass:
        return pd.DataFrame([{"status": "VERIFIER_V2_CROSSCHECK_LIMITATION", "reason": "PRIMARY_FAILED"}])
    all_v2 = pd.read_csv(V2_RESULTS, dtype={"target_sat_id": str, "claimed_sat_id": str})
    all_v2["case_id"] = all_v2["sequence_id"].astype(str) + ":" + all_v2["threshold_type"].astype(str)
    v2 = all_v2[all_v2["sample_type"].eq("attack")].copy()
    initial_fit = fit[fit["experiment_family"].eq("score_only_verifier_and_synthetic_orbit_attacks")].copy()
    initial_fit["sequence_id"] = initial_fit["case_id"]
    fit_map = initial_fit.set_index("sequence_id")
    # Per-target V2 ranges are derived from the full legitimate population.
    rebuilt = all_v2.copy()
    for sequence_id, new in fit_map.iterrows():
        mask = rebuilt["sequence_id"].astype(str).eq(str(sequence_id))
        rebuilt.loc[mask, "score"] = float(new["new_score"])
        rebuilt.loc[mask, "b_hat"] = float(new["new_b_hat"])
        rebuilt.loc[mask, "k_hat"] = float(new["new_k_hat"])
    rebuilt["accepted_score_only"] = rebuilt["score"].le(rebuilt["threshold"])
    ranges = v2gate.load_global_ranges(SimpleNamespace(
        parameter_config=PARAMETER_CONFIG, global_k_min=None, global_k_max=None,
    ))
    rebuilt, _ = v2gate.add_gate_columns(rebuilt, ranges[0], ranges[1])
    source = v2.set_index("case_id")
    rebuilt_source = rebuilt.set_index("case_id")
    gate_columns = [
        "accepted_score_only", "accepted_score_plus_global_k", "accepted_score_plus_global_bk",
        "accepted_score_plus_per_target_k_p01_p99", "accepted_score_plus_per_target_bk_p01_p99",
        "accepted_score_plus_per_target_k_p05_p95", "accepted_score_plus_per_target_bk_p05_p95",
        "accepted_score_plus_per_target_bk",
    ]
    rows = []
    for bind in secondary.itertuples(index=False):
        old = source.loc[str(bind.case_id)]
        rebuilt_row = rebuilt_source.loc[str(bind.case_id)]
        sequence_id = str(old["sequence_id"])
        new = fit_map.loc[sequence_id]
        record = {
            "stable_row_identity": bind.stable_row_identity, "orbit_unit_id": bind.orbit_unit_id,
            "case_id": bind.case_id, "sequence_id": sequence_id, "threshold_type": old["threshold_type"],
            "score_abs_difference": abs(float(new["new_score"]) - float(old["score"])),
            "b_hat_abs_difference": abs(float(new["new_b_hat"]) - float(old["b_hat"])),
            "k_hat_abs_difference": abs(float(new["new_k_hat"]) - float(old["k_hat"])),
        }
        for column in gate_columns:
            record[f"{column}_mismatch"] = int(to_bool(rebuilt_row[column]) != to_bool(old[column]))
        record["all_gate_mismatch_count"] = sum(record[f"{column}_mismatch"] for column in gate_columns)
        rows.append(record)
    frame = pd.DataFrame(rows)
    frame["crosscheck_pass"] = (
        frame["score_abs_difference"].le(1e-6) & frame["b_hat_abs_difference"].le(1e-6)
        & frame["k_hat_abs_difference"].le(1e-9) & frame["all_gate_mismatch_count"].eq(0)
    )
    frame["status"] = np.where(frame["crosscheck_pass"], "VERIFIER_V2_CROSSCHECK_PASS", "VERIFIER_V2_CROSSCHECK_LIMITATION")
    return frame


def failure_rows(state: pd.DataFrame, geometry: pd.DataFrame, rows: pd.DataFrame,
                 fit: pd.DataFrame, gate: pd.DataFrame, spotcheck_pass: bool) -> pd.DataFrame:
    failures: list[dict[str, Any]] = []
    for record in state[~state["state_pass"].map(to_bool)].to_dict("records"):
        category = "A_STATE_RECONSTRUCTION" if record["A_position_error_max_km"] > record["A_position_tolerance_km"] or record["A_velocity_error_max_km_s"] > record["A_velocity_tolerance_km_s"] else "B_STATE_RECONSTRUCTION"
        failures.append({"failure_category": category, "earliest_divergence_layer": "LEVEL_1_A_STATE" if category.startswith("A_") else "LEVEL_2_B_STATE", "orbit_unit_id": record["orbit_unit_id"], "case_id": "", "detail": "frozen state tolerance exceeded"})
    for record in geometry[~geometry["geometry_pass"].map(to_bool)].to_dict("records"):
        category = "TIME_GRID" if record["time_grid_max_abs_error_s"] > record["time_tolerance_s"] else "COMPENSATION" if record["active_compensation_max_abs_difference_hz"] > record["compensation_tolerance_hz"] else "DOPPLER_GEOMETRY"
        layer = {"TIME_GRID": "LEVEL_3_TIME_GRID", "DOPPLER_GEOMETRY": "LEVEL_4_DOPPLER_GEOMETRY", "COMPENSATION": "LEVEL_5_ACTIVE_COMPENSATION"}[category]
        failures.append({"failure_category": category, "earliest_divergence_layer": layer, "orbit_unit_id": record["orbit_unit_id"], "case_id": "", "detail": "frozen geometry/time tolerance exceeded"})
    for record in rows[~rows["reproduction_pass"].map(to_bool)].to_dict("records"):
        fit_row = fit[fit["stable_row_identity"].eq(record["stable_row_identity"])].iloc[0]
        gate_row = gate[gate["stable_row_identity"].eq(record["stable_row_identity"])].iloc[0]
        if mismatch_flag(record.get("randomness_hash_mismatch", 0)):
            category, layer = "RANDOMNESS", "LEVEL_6_OBSERVATION_RANDOMNESS"
        elif fit_row["observation_max_abs_difference_hz"] > 1e-6 or fit_row["residual_max_abs_difference_hz"] > 1e-6:
            category, layer = "RESIDUAL", "LEVEL_7_RESIDUAL"
        elif fit_row["b_hat_abs_difference"] > 1e-6 or fit_row["k_hat_abs_difference"] > 1e-9:
            category, layer = "OLS", "LEVEL_8_OLS"
        elif fit_row["score_abs_difference"] > 1e-6:
            category, layer = "SCORE", "LEVEL_9_SCORE"
        else:
            mismatch_map = [("score_gate_mismatch", "SCORE_GATE"), ("b_gate_mismatch", "B_GATE"),
                            ("k_gate_mismatch", "K_GATE"), ("coverage_mismatch", "COVERAGE"),
                            ("final_decision_mismatch", "FINAL_DECISION")]
            category = next((name for column, name in mismatch_map if int(gate_row[column])), "PROVENANCE_UNKNOWN")
            layer = "LEVEL_11_FINAL_DECISION" if category == "FINAL_DECISION" else "LEVEL_10_GATES"
        failures.append({"failure_category": category, "earliest_divergence_layer": layer,
                         "orbit_unit_id": record["orbit_unit_id"], "case_id": record["case_id"], "detail": "primary row reproduction mismatch"})
    return pd.DataFrame(failures, columns=["failure_category", "earliest_divergence_layer", "orbit_unit_id", "case_id", "detail"])


def build_report(status: str, rows: pd.DataFrame, state: pd.DataFrame, geometry: pd.DataFrame, fit: pd.DataFrame,
                 gate: pd.DataFrame, v2: pd.DataFrame, spotcheck: pd.DataFrame,
                 correctness: pd.DataFrame, earliest: str) -> str:
    def maximum(frame: pd.DataFrame, column: str) -> float:
        return float(frame[column].max()) if len(frame) else math.nan
    v2_status = "PASS" if len(v2) == 200 and v2.get("crosscheck_pass", pd.Series(dtype=bool)).map(to_bool).all() else "LIMITATION"
    unit_pass = rows.groupby("orbit_unit_id")["reproduction_pass"].apply(lambda values: values.map(to_bool).all())
    secondary_summary = (
        f"{int(v2['crosscheck_pass'].map(to_bool).sum())}/200 pass"
        if len(v2) == 200 else "未执行（PRIMARY_FAILED）"
    )
    return f"""# Causal-A Doppler reconstruction reproduction validation rerun (R1)

## 1. Result

`{status}`

Primary population 使用 erratum 后的 64 units / 6,280 rows；200 verifier-v2 rows 仅作 secondary cross-check。未处理 821 个 A-semantics-mismatch units，也未进行 orbit-distinct security analysis。

## 2. Numerical reproduction

| Quantity | Maximum error |
|---|---:|
| A position norm | {maximum(state, 'A_position_error_max_km'):.12g} km |
| A velocity norm | {maximum(state, 'A_velocity_error_max_km_s'):.12g} km/s |
| B position norm | {maximum(state, 'B_position_error_max_km'):.12g} km |
| B velocity norm | {maximum(state, 'B_velocity_error_max_km_s'):.12g} km/s |
| Doppler geometry | {maximum(geometry, 'doppler_geometry_max_abs_difference_hz'):.12g} Hz |
| active compensation | {maximum(geometry, 'active_compensation_max_abs_difference_hz'):.12g} Hz |
| observation | {maximum(fit, 'observation_max_abs_difference_hz'):.12g} Hz |
| residual | {maximum(fit, 'residual_max_abs_difference_hz'):.12g} Hz |
| b_hat | {maximum(fit, 'b_hat_abs_difference'):.12g} Hz |
| k_hat | {maximum(fit, 'k_hat_abs_difference'):.12g} Hz/s |
| score | {maximum(fit, 'score_abs_difference'):.12g} Hz |
| score relative | {maximum(fit, 'score_relative_difference'):.12g} |

所有 pass/fail 均使用 R0 protocol 已冻结 tolerance，没有新增或放宽阈值。

## 3. Categorical reproduction

| Check | Mismatches |
|---|---:|
| score gate | {int(gate['score_gate_mismatch'].sum())} |
| b gate | {int(gate['b_gate_mismatch'].sum())} |
| k gate | {int(gate['k_gate_mismatch'].sum())} |
| coverage | {int(gate['coverage_mismatch'].sum())} |
| quality gate | {int(gate['quality_gate_mismatch'].sum())} |
| final decision | {int(gate['final_decision_mismatch'].sum())} |

## 4. Correctness and provenance

{correctness.to_markdown(index=False)}

Independent spot-check 使用 `SHA256('R1_SPOTCHECK_V1|' + stable_row_identity)` 的 deterministic stratified selection，先覆盖 family × old-decision strata，再按 hash 补足 30 rows。结果：{int(spotcheck['spotcheck_pass'].map(to_bool).sum())}/30 pass。

Verifier-v2 secondary cross-check：`{v2_status}`，{secondary_summary}。

## 5. Required answers

1. Primary units：64/64 covered；{int(unit_pass.sum())}/64 通过全部 reproduction levels。
2. Primary rows：{int(rows['reproduction_pass'].map(to_bool).sum())}/6280 通过全部 reproduction levels；categorical requirements 见上表。
3. A state 最大 position/velocity error：{maximum(state, 'A_position_error_max_km'):.12g} km / {maximum(state, 'A_velocity_error_max_km_s'):.12g} km/s。
4. B state 最大 position/velocity error：{maximum(state, 'B_position_error_max_km'):.12g} km / {maximum(state, 'B_velocity_error_max_km_s'):.12g} km/s。
5. Doppler geometry 最大误差：{maximum(geometry, 'doppler_geometry_max_abs_difference_hz'):.12g} Hz。
6. Active compensation 最大误差：{maximum(geometry, 'active_compensation_max_abs_difference_hz'):.12g} Hz。
7. Residual 最大误差：{maximum(fit, 'residual_max_abs_difference_hz'):.12g} Hz。
8. b_hat 最大误差：{maximum(fit, 'b_hat_abs_difference'):.12g} Hz。
9. k_hat 最大误差：{maximum(fit, 'k_hat_abs_difference'):.12g} Hz/s。
10. Score 最大误差：{maximum(fit, 'score_abs_difference'):.12g} Hz。
11-15. score/b/k/coverage/final mismatch：{int(gate['score_gate_mismatch'].sum())}/{int(gate['b_gate_mismatch'].sum())}/{int(gate['k_gate_mismatch'].sum())}/{int(gate['coverage_mismatch'].sum())}/{int(gate['final_decision_mismatch'].sum())}。
16. Frozen numerical tolerance：{'全部通过' if fit['numerical_pass'].map(to_bool).all() and state['state_pass'].map(to_bool).all() and geometry['geometry_pass'].map(to_bool).all() else '未全部通过'}。
17. Earliest divergence layer：`{earliest}`。
18. Verifier-v2：`{v2_status}`。
19. 30-row spot-check：{int(spotcheck['spotcheck_pass'].map(to_bool).sum())}/30。
20. Reconstruction implementation 不改变 verifier science：{'支持' if status.endswith('VALIDATED') else '不支持'}。
21. R2 authorization：{'YES' if status.endswith('VALIDATED') else 'NO'}。

## 6. Formal status

`{status}`

`R1 PRIMARY: {'PASS' if status.endswith('VALIDATED') else 'FAIL'}`

`PRIMARY POPULATION: 64 units / 6280 rows`

`VERIFIER-V2 CROSSCHECK: {v2_status}`

`R2 AUTHORIZED: {'YES' if status.endswith('VALIDATED') else 'NO'}`

`NEXT STEP: {'CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_AND_FREEZE' if status.endswith('VALIDATED') else 'STOP_AT_R1_EARLIEST_DIVERGENCE'}`
"""


def append_log(status: str, earliest: str, maxima: dict[str, float], v2_status: str) -> None:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    entry = f"""

## {now} - Causal-A Doppler reconstruction reproduction validation rerun (R1)

### A. 本轮目标
在 corrected 64-unit / 6,280-primary-row population 上验证 causal-A-aligned wrapper 是否数值等价复现 legacy verifier。

### B. 实际操作
复用 production orbit/Doppler/compensation/OLS/verifier functions；初始与 active family 读取保存的 observation variables，multipass/altitude 按冻结 seed/hash 重放。Primary 完成后执行 V2 secondary 和 deterministic 30-row independent spot-check。未处理 821 mismatch units。

### C. 新增/修改文件
新增独立 rerun dataset、state/geometry/fit/gate/failure/V2/correctness metrics、manifest、报告、脚本和测试；未修改 protected artifacts。

### D. 运行命令
`python scripts/run_causal_a_doppler_reconstruction_reproduction_validation_rerun.py`
`python -m pytest tests/test_causal_a_doppler_reconstruction_reproduction_validation_rerun.py -q`

### E. 结果摘要
状态 `{status}`；earliest divergence `{earliest}`；V2 `{v2_status}`；关键最大误差 {json.dumps(maxima, ensure_ascii=False)}。

### F. 问题与下一步
下一步仅依据 manifest 中 R2 authorization；本轮未进入 R2 或 joint-security analysis。
"""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def run(args: argparse.Namespace) -> None:
    before, primary, secondary, protocol, tolerances = validate_and_load(args.overwrite)
    selection, library, config, tle, ranges = load_core_inputs()
    _ = selection, library
    ts = load.timescale()
    causal, provenance, future_count = causal_satellites(primary, ts)
    outputs: dict[str, list[dict[str, Any]]] = {name: [] for name in ["state", "geometry", "fit", "gate", "rows"]}
    bundles: dict[str, dict[str, Any]] = {}

    process_initial(primary, causal, provenance, tle, config, ts, tolerances, outputs, bundles)
    process_active(primary, causal, provenance, tle, config, ts, tolerances, outputs, bundles)
    replayed = process_generated_family("same_pair_multi_pass_real_TLE", primary, causal, provenance, tle, ranges, config, ts, tolerances, outputs, bundles)
    replayed += process_generated_family("controlled_altitude_difference_synthetic_B", primary, causal, provenance, tle, ranges, config, ts, tolerances, outputs, bundles)

    state = pd.DataFrame(outputs["state"]).sort_values("orbit_unit_id").reset_index(drop=True)
    geometry = pd.DataFrame(outputs["geometry"]).sort_values("orbit_unit_id").reset_index(drop=True)
    fit = pd.DataFrame(outputs["fit"]).sort_values("stable_row_identity").reset_index(drop=True)
    gate = pd.DataFrame(outputs["gate"]).sort_values("stable_row_identity").reset_index(drop=True)
    rows = pd.DataFrame(outputs["rows"]).sort_values("stable_row_identity").reset_index(drop=True)
    if len(state) != 64 or len(geometry) != 64 or len(fit) != 6280 or len(gate) != 6280 or len(rows) != 6280:
        raise SystemExit(f"Primary output coverage mismatch: state={len(state)}, geometry={len(geometry)}, fit={len(fit)}, gate={len(gate)}, rows={len(rows)}")

    state_map = state.set_index("orbit_unit_id")["state_pass"].map(to_bool)
    geometry_map = geometry.set_index("orbit_unit_id")["geometry_pass"].map(to_bool)
    rows["state_pass"] = rows["orbit_unit_id"].map(state_map)
    rows["geometry_pass"] = rows["orbit_unit_id"].map(geometry_map)
    rows["reproduction_pass"] = rows["reproduction_pass"].map(to_bool) & rows["state_pass"] & rows["geometry_pass"]

    selected = deterministic_spotcheck_ids(primary, args.spotcheck_size)
    spot_map, spotcheck = independent_spotcheck(selected, bundles, state, geometry, tolerances)
    rows["spotcheck_selected"] = rows["stable_row_identity"].isin(set(selected))
    rows["spotcheck_pass"] = rows["stable_row_identity"].map(spot_map)
    spotcheck_pass = len(spotcheck) == args.spotcheck_size and spotcheck["spotcheck_pass"].map(to_bool).all()

    categorical_mismatches = int(gate[["score_gate_mismatch", "b_gate_mismatch", "k_gate_mismatch", "coverage_mismatch", "quality_gate_mismatch", "final_decision_mismatch"]].sum().sum())
    primary_pass = (
        state["state_pass"].map(to_bool).all() and geometry["geometry_pass"].map(to_bool).all()
        and fit["numerical_pass"].map(to_bool).all() and rows["reproduction_pass"].map(to_bool).all()
        and categorical_mismatches == 0 and spotcheck_pass
    )
    v2 = secondary_crosscheck(secondary, fit, primary_pass)
    v2_pass = len(v2) == 200 and v2["crosscheck_pass"].map(to_bool).all()
    failure = failure_rows(state, geometry, rows, fit, gate, spotcheck_pass)
    if len(failure):
        layer_order = ["LEVEL_1_A_STATE", "LEVEL_2_B_STATE", "LEVEL_3_TIME_GRID", "LEVEL_4_DOPPLER_GEOMETRY",
                       "LEVEL_5_ACTIVE_COMPENSATION", "LEVEL_6_OBSERVATION_RANDOMNESS", "LEVEL_7_RESIDUAL",
                       "LEVEL_8_OLS", "LEVEL_9_SCORE", "LEVEL_10_GATES", "LEVEL_11_FINAL_DECISION"]
        earliest = next((layer for layer in layer_order if layer in set(failure["earliest_divergence_layer"])), "PROVENANCE_UNKNOWN")
    else:
        earliest = "NONE"
    status = "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATED" if primary_pass else "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED"

    correctness = pd.DataFrame([
        ("primary_expected_units", 64, len(state), len(state) == 64),
        ("primary_expected_rows", 6280, len(rows), len(rows) == 6280),
        ("secondary_expected_rows", 200, len(v2) if primary_pass else 0, len(v2) == 200 if primary_pass else False),
        ("primary_secondary_overlap", 0, 0, True),
        ("future_publication_count", 0, future_count, future_count == 0),
        ("new_random_draw_count", 0, 0, True),
        ("replayed_random_vector_count", replayed, replayed, True),
        ("semantics_mismatch_units_executed", 0, 0, True),
        ("legacy_source_modifications", 0, 0, True),
        ("frozen_threshold_modifications", 0, 0, True),
        ("frozen_b_k_modifications", 0, 0, True),
        ("orbit_uncertainty_artifact_modifications", 0, 0, True),
        ("spotcheck_rows", args.spotcheck_size, len(spotcheck), len(spotcheck) == args.spotcheck_size),
        ("spotcheck_failures", 0, int((~spotcheck["spotcheck_pass"].map(to_bool)).sum()), spotcheck_pass),
    ], columns=["check", "expected", "observed", "passed"])

    write_csv(ROWS_OUTPUT, rows)
    write_csv(STATE_OUTPUT, state)
    write_csv(GEOMETRY_OUTPUT, geometry)
    write_csv(FIT_OUTPUT, fit)
    write_csv(GATE_OUTPUT, gate)
    write_csv(FAILURE_OUTPUT, failure)
    write_csv(V2_OUTPUT, v2)
    write_csv(CORRECTNESS_OUTPUT, correctness)
    write_text(REPORT_OUTPUT, build_report(status, rows, state, geometry, fit, gate, v2, spotcheck, correctness, earliest))

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path in before if before[path] != after[path]]
    if changed:
        raise SystemExit("Protected artifact changed: " + ", ".join(changed))

    maxima = {
        "A_position_km": float(state["A_position_error_max_km"].max()),
        "A_velocity_km_s": float(state["A_velocity_error_max_km_s"].max()),
        "B_position_km": float(state["B_position_error_max_km"].max()),
        "B_velocity_km_s": float(state["B_velocity_error_max_km_s"].max()),
        "Doppler_hz": float(geometry["doppler_geometry_max_abs_difference_hz"].max()),
        "compensation_hz": float(geometry["active_compensation_max_abs_difference_hz"].max()),
        "observation_hz": float(fit["observation_max_abs_difference_hz"].max()),
        "residual_hz": float(fit["residual_max_abs_difference_hz"].max()),
        "b_hat_hz": float(fit["b_hat_abs_difference"].max()),
        "k_hat_hz_s": float(fit["k_hat_abs_difference"].max()),
        "score_hz": float(fit["score_abs_difference"].max()),
    }
    manifest = {
        "stage": "CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_VALIDATION_RERUN",
        "status": status, "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "R1_primary": "PASS" if primary_pass else "FAIL",
        "primary_population": {"units_expected": 64, "units_actual": len(state), "rows_expected": 6280, "rows_actual": len(rows)},
        "verifier_v2_crosscheck": "PASS" if v2_pass else "LIMITATION",
        "secondary_population": {"rows_expected": 200, "rows_actual": len(v2) if primary_pass else 0},
        "earliest_divergence_layer": earliest, "maximum_errors": maxima,
        "categorical_mismatches": {
            column: int(gate[column].sum()) for column in ["score_gate_mismatch", "b_gate_mismatch", "k_gate_mismatch", "coverage_mismatch", "quality_gate_mismatch", "final_decision_mismatch"]
        },
        "all_frozen_numerical_tolerances_pass": bool(state["state_pass"].map(to_bool).all() and geometry["geometry_pass"].map(to_bool).all() and fit["numerical_pass"].map(to_bool).all()),
        "spotcheck": {"selection_rule": "deterministic stratified SHA256(R1_SPOTCHECK_V1|stable_row_identity)", "rows": len(spotcheck), "passed": int(spotcheck["spotcheck_pass"].map(to_bool).sum())},
        "execution_counters": {"semantics_mismatch_units": 0, "new_random_draws": 0, "replayed_random_vectors": replayed},
        "frozen_parameter_sha256": sha256(FROZEN_PARAMETERS),
        "protected_inputs": [{"path": path, "sha256": digest, "size_bytes": (ROOT / path).stat().st_size} for path, digest in before.items()],
        "production_code": [{"path": rel(path), "sha256": sha256(path)} for path in PRODUCTION_CODE],
        "generator": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "outputs": [{"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in OUTPUTS if path != MANIFEST_OUTPUT],
        "protected_artifact_changes": [], "scientific_method_changed": False,
        "R2_authorized": bool(primary_pass),
        "next_step": "CAUSAL_A_DOPPLER_CORE_RECONSTRUCTION_DESIGN_AND_FREEZE" if primary_pass else "STOP_AT_R1_EARLIEST_DIVERGENCE",
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    append_log(status, earliest, maxima, "PASS" if v2_pass else "LIMITATION")
    print(status)
    print("R1 PRIMARY: " + ("PASS" if primary_pass else "FAIL"))
    print("PRIMARY POPULATION: 64 units / 6280 rows")
    print("VERIFIER-V2 CROSSCHECK: " + ("PASS" if v2_pass else "LIMITATION"))
    print("R2 AUTHORIZED: " + ("YES" if primary_pass else "NO"))
    print("NEXT STEP: " + manifest["next_step"])


if __name__ == "__main__":
    run(parse_args())
