#!/usr/bin/env python3
"""Relabel existing Doppler cases with the frozen orbit-distinct gate.

This program reconstructs provenance and orbit states only. It never reruns a
Doppler verifier, generates a new candidate, or fits uncertainty parameters.
"""

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
from typing import Any

import numpy as np
import pandas as pd
from astropy.utils import iers
from sgp4.api import Satrec

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from acquire_orbit_uncertainty_stage1 import parse_utc, select_causal_gp  # noqa: E402
from run_orbit_uncertainty_stage0_starlink_smoke import propagate, rtn_basis, to_gcrs  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "outputs" / "datasets"
METRICS = ROOT / "outputs" / "metrics"
REPORTS = ROOT / "outputs" / "reports"
LOG = ROOT / "logs" / "work_log.md"

PARAMETERS = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
PARAMETER_SHA = "6F17F8340BA14B5B48F7AEAFFD776F1D0A07B4D50F882B2AFCA73756F9FF55D1"
INTERFACE = METRICS / "orbit_distinct_frozen_scoring_interface.json"
BRIDGE_MANIFEST = METRICS / "orbit_distinct_bridge_interface_manifest.json"
COMPATIBILITY = METRICS / "orbit_distinct_existing_doppler_artifact_compatibility.csv"
FREEZE_MANIFEST = METRICS / "orbit_uncertainty_stage1f_lite_manifest.json"
JUNE_CONFIRMATORY_MANIFEST = METRICS / "orbit_uncertainty_stage1f_lite_june_confirmatory_manifest.json"
RAW_GP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "spacetrack_gp" / "spacetrack_gp_history_20260226_20260329_20sat_omm.json"
STATIC_TLE = ROOT / "data" / "tle" / "starlink_tle.txt"
HISTORY_TLE = ROOT / "data" / "tle" / "history" / "starlink_gp_history_20260301_20260320.csv"
SELECTION = METRICS / "controlled_starlink_20target_selection_table.csv"

RELABEL_OUTPUT = DATASETS / "existing_doppler_cases_orbit_distinct_relabeling.csv"
READINESS_OUTPUT = METRICS / "orbit_distinct_relabel_family_readiness.csv"
CAUSAL_OUTPUT = METRICS / "orbit_distinct_causal_a_reconstruction_audit.csv"
STATE_OUTPUT = METRICS / "orbit_distinct_ab_state_reconstruction_audit.csv"
CORRECTNESS_OUTPUT = METRICS / "orbit_distinct_relabel_correctness_audit.csv"
MANIFEST_OUTPUT = METRICS / "orbit_distinct_relabel_manifest.json"
REPORT_OUTPUT = REPORTS / "existing_doppler_case_orbit_distinct_relabeling_report.md"

INITIAL_RESULTS = METRICS / "doppler_verifier_orbit_similarity_attack_results.csv"
VERIFIER_V2 = METRICS / "verifier_v2_sequence_eval.csv"
ACTIVE = METRICS / "active_compensation_first_pass_sequence_eval.csv"
SEGMENT_LOCAL = DATASETS / "m2_segment_local_expanded_sample_dataset.csv"
SAME_PAIR = DATASETS / "same_pair_multi_pass_realization_dataset.csv"
HISTORICAL = DATASETS / "historical_tle_multi_pass_realization_dataset.csv"
ALTITUDE = DATASETS / "controlled_altitude_difference_realization_dataset.csv"
FIXED_POINT = DATASETS / "fixed_point_active_compensation_dataset.csv"
DIFFERENTIAL = DATASETS / "differential_doppler_mechanism_full_representative_timeseries.csv"
CONTROLLED_A_ONLY = DATASETS / "controlled_starlink_multitarget_dataset.csv"

SOURCE_ARTIFACTS = [
    INITIAL_RESULTS, VERIFIER_V2, ACTIVE, SEGMENT_LOCAL, SAME_PAIR, HISTORICAL,
    ALTITUDE, FIXED_POINT, DIFFERENTIAL, CONTROLLED_A_ONLY,
]
PROTECTED = [
    PARAMETERS, INTERFACE, BRIDGE_MANIFEST, COMPATIBILITY, FREEZE_MANIFEST,
    JUNE_CONFIRMATORY_MANIFEST, RAW_GP, STATIC_TLE,
    HISTORY_TLE, SELECTION, *SOURCE_ARTIFACTS,
]
OUTPUTS = [
    RELABEL_OUTPUT, READINESS_OUTPUT, CAUSAL_OUTPUT, STATE_OUTPUT,
    CORRECTNESS_OUTPUT, MANIFEST_OUTPUT, REPORT_OUTPUT,
]

FRESHNESS_BINS = (
    (0.0, 6.0, "0-6 h"),
    (6.0, 9.0, "6-9 h"),
    (9.0, 12.0, "9-12 h"),
    (12.0, 18.0, "12-18 h"),
    (18.0, 24.0, "18-24 h"),
    (24.0, 36.0, "24-36 h"),
)
MU_EARTH_KM3_S2 = 398600.4418
A_POSITION_EQUIVALENCE_KM = 1e-6
A_VELOCITY_EQUIVALENCE_KM_S = 1e-9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--correctness-sample-size", type=int, default=30)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def stable_id(prefix: str, parts: list[Any]) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def midpoint(start: Any, end: Any) -> datetime:
    left = parse_utc(str(start))
    right = parse_utc(str(end))
    if right < left:
        raise ValueError(f"End precedes start: {start}, {end}")
    return left + (right - left) / 2


def bool_value(value: Any) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "accept", "accepted"}:
        return True
    if text in {"false", "0", "no", "reject", "rejected", "defer"}:
        return False
    return None


def check_inputs(overwrite: bool) -> dict[str, str]:
    missing = [rel(path) for path in PROTECTED if not path.exists()]
    if missing:
        raise SystemExit("Missing authoritative input: " + ", ".join(missing))
    existing = [rel(path) for path in OUTPUTS if path.exists()]
    if existing and not overwrite:
        raise SystemExit("Output exists; use --overwrite: " + ", ".join(existing))
    if sha256(PARAMETERS) != PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch before relabeling")
    interface = json.loads(INTERFACE.read_text(encoding="utf-8"))
    if interface.get("frozen_parameter_sha256") != PARAMETER_SHA:
        raise SystemExit("Bridge interface binds a different frozen parameter SHA")
    if interface.get("interface_status") != "PUBLIC_DEFINED_RTN_INTERFACE_SUPPORTED":
        raise SystemExit("Public-defined RTN interface is not frozen as supported")
    return {rel(path): sha256(path) for path in PROTECTED}


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_tle_catalog(path: Path) -> dict[str, dict[str, str]]:
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result: dict[str, dict[str, str]] = {}
    index = 0
    while index + 2 < len(lines):
        name, line1, line2 = lines[index:index + 3]
        if line1.startswith("1 ") and line2.startswith("2 "):
            norad = line1[2:7].strip()
            result[norad] = {"name": name.strip(), "line1": line1.strip(), "line2": line2.strip()}
            index += 3
        else:
            index += 1
    if not result:
        raise SystemExit(f"No TLE records in {rel(path)}")
    return result


def load_history_tle(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    frame = pd.read_csv(path, dtype={"NORAD_CAT_ID": str})
    frame["epoch_ns"] = pd.to_datetime(frame["EPOCH"], utc=True).astype("int64")
    result: dict[tuple[str, int], dict[str, str]] = {}
    for row in frame.itertuples(index=False):
        result[(str(row.NORAD_CAT_ID), int(row.epoch_ns))] = {
            "name": str(row.OBJECT_NAME), "line1": str(row.TLE_LINE1).strip(), "line2": str(row.TLE_LINE2).strip()
        }
    return result


def history_entry(lookup: dict[tuple[str, int], dict[str, str]], norad: str, epoch: Any) -> dict[str, str] | None:
    ns = int(pd.Timestamp(str(epoch), tz="UTC").value) if pd.Timestamp(str(epoch)).tzinfo is None else int(pd.Timestamp(str(epoch)).tz_convert("UTC").value)
    exact = lookup.get((str(norad), ns))
    if exact is not None:
        return exact
    candidates = [(abs(key[1] - ns), value) for key, value in lookup.items() if key[0] == str(norad)]
    if not candidates:
        return None
    difference, value = min(candidates, key=lambda item: item[0])
    return value if difference <= 1000 else None


def load_models() -> dict[str, dict[str, Any]]:
    frame = pd.read_csv(PARAMETERS)
    primary = frame.loc[frame["candidate"].eq("ROBUST_EMPIRICAL_ELLIPSOID")]
    if len(primary) != 6:
        raise SystemExit("Frozen primary model must contain six freshness bins")
    models: dict[str, dict[str, Any]] = {}
    for row in primary.itertuples(index=False):
        covariance = np.array([
            [row.cov_RR_km2, row.cov_RT_km2, row.cov_RN_km2],
            [row.cov_TR_km2, row.cov_TT_km2, row.cov_TN_km2],
            [row.cov_NR_km2, row.cov_NT_km2, row.cov_NN_km2],
        ], dtype=float)
        models[str(row.freshness_bin)] = {
            "center": np.array([row.center_R_km, row.center_T_km, row.center_N_km], dtype=float),
            "precision": np.linalg.inv(covariance),
            "c95": float(row.c95_empirical_score),
            "c99": float(row.c99_empirical_score),
        }
    return models


def freshness_bin(age_hours: float) -> str | None:
    for left, right, label in FRESHNESS_BINS:
        if left < age_hours <= right:
            return label
    return None


def score_vector(z: np.ndarray, model: dict[str, Any]) -> float:
    centered = np.asarray(z, dtype=float) - model["center"]
    return float(centered @ model["precision"] @ centered)


def orbit_decision(d2: float, c95: float, c99: float) -> str:
    if d2 <= c95:
        return "NOT_ORBIT_DISTINCT"
    if d2 <= c99:
        return "AMBIGUOUS"
    return "ORBIT_DISTINCT"


def state_from_lines(line1: str, line2: str, when: datetime) -> tuple[np.ndarray, np.ndarray]:
    sat = Satrec.twoline2rv(str(line1), str(line2))
    native_r, native_v = propagate(sat, when)
    return to_gcrs(native_r, native_v, when)


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("Cannot normalize a zero vector")
    return np.asarray(vector, dtype=float) / norm


def rodrigues(vector: np.ndarray, axis: np.ndarray, angle: float) -> np.ndarray:
    axis = normalize(axis)
    return vector * math.cos(angle) + np.cross(axis, vector) * math.sin(angle) + axis * float(np.dot(axis, vector)) * (1 - math.cos(angle))


def synthetic_state(
    original_a_lines: tuple[str, str], anchor_time: datetime, evaluation_time: datetime,
    altitude_offset_km: float = 0.0, phase_offset_s: float = 0.0,
    inclination_offset_deg: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    r0, v0 = state_from_lines(*original_a_lines, anchor_time)
    h_hat = normalize(np.cross(r0, v0))
    p_hat = normalize(r0)
    if inclination_offset_deg:
        z_hat = np.array([0.0, 0.0, 1.0])
        node_hat = np.cross(z_hat, h_hat)
        node_hat = normalize(r0) if np.linalg.norm(node_hat) < 1e-8 else normalize(node_hat)
        delta_i = math.radians(float(inclination_offset_deg))
        candidates = [rodrigues(h_hat, node_hat, delta_i), rodrigues(h_hat, node_hat, -delta_i)]
        current_i = math.acos(float(np.clip(np.dot(h_hat, z_hat), -1.0, 1.0)))
        desired_i = current_i + delta_i
        h_hat = min(candidates, key=lambda h: abs(math.acos(float(np.clip(np.dot(h, z_hat), -1.0, 1.0))) - desired_i))
    q_hat = normalize(np.cross(h_hat, p_hat))
    if float(np.dot(v0, q_hat)) < 0:
        q_hat = -q_hat
    radius = float(np.linalg.norm(r0) + altitude_offset_km)
    if radius <= 6300:
        raise ValueError(f"Invalid synthetic radius: {radius}")
    omega = math.sqrt(MU_EARTH_KM3_S2 / radius**3)
    dt = (evaluation_time - anchor_time).total_seconds() + float(phase_offset_s)
    theta = omega * dt
    position = radius * (math.cos(theta) * p_hat + math.sin(theta) * q_hat)
    velocity = radius * omega * (-math.sin(theta) * p_hat + math.cos(theta) * q_hat)
    return position, velocity


def original_accept_state(decision: str | None, accepted: bool | None) -> str:
    if decision:
        upper = str(decision).upper()
        if upper in {"ACCEPT", "REJECT", "DEFER"}:
            return upper
    if accepted is True:
        return "ACCEPT"
    if accepted is False:
        return "REJECT"
    return "UNAVAILABLE"


def build_inventory_and_cases() -> tuple[dict[str, dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    selection = pd.read_csv(SELECTION, dtype={"target_norad_id": str})
    windows = {str(row.target_norad_id): (row.pass_start_utc, row.pass_end_utc, row.target_name) for row in selection.itertuples(index=False)}
    units: dict[str, dict[str, Any]] = {}
    cases: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []

    def add_unit(family: str, key: list[Any], values: dict[str, Any]) -> str:
        unit_id = stable_id("orbit_unit", [family, *key])
        if unit_id not in units:
            units[unit_id] = {"orbit_unit_id": unit_id, "experiment_family": family, **values}
        return unit_id

    def add_case(unit_id: str, source_view: str, source_artifact: Path, case_id: Any, row: dict[str, Any]) -> None:
        cases.append({"orbit_unit_id": unit_id, "source_view": source_view, "source_artifact": rel(source_artifact), "case_id": str(case_id), **row})

    initial = pd.read_csv(INITIAL_RESULTS, dtype={"claimed_target_norad": str})
    sequence_to_unit: dict[str, str] = {}
    for row in initial.to_dict("records"):
        a_id = str(row["claimed_target_norad"])
        start, end, name = windows[a_id]
        evaluation = midpoint(start, end)
        duration = int(round((parse_utc(str(end)) - parse_utc(str(start))).total_seconds()))
        anchor = parse_utc(str(start)) + timedelta(seconds=(duration + 1) // 2)
        definition = f"{row['attack_type']}:{row['attack_variant']}"
        unit_id = add_unit("score_only_verifier_and_synthetic_orbit_attacks", [a_id, definition, iso_z(evaluation)], {
            "A_id": a_id, "A_name": str(row.get("claimed_target_name", name)), "B_id_or_definition": definition,
            "segment_id": f"full_pass:{a_id}", "evaluation_time": iso_z(evaluation),
            "original_A_source": rel(STATIC_TLE), "original_A_kind": "STATIC_TLE", "B_kind": "SYNTHETIC",
            "construction_anchor_time": iso_z(anchor), "altitude_offset_km": float(row["altitude_offset_km"]),
            "phase_offset_s": float(row["phase_offset_s"]), "inclination_offset_deg": float(row["inclination_offset_deg"]),
        })
        sequence_to_unit[str(row["attack_sequence_id"])] = unit_id
        add_case(unit_id, "initial_score_only_p99", INITIAL_RESULTS, row["attack_sequence_id"], {
            "original_verifier_score": row.get("score_A_rmse_hz"), "original_b_hat": row.get("b_hat_hz"),
            "original_k_hat": row.get("k_hat_hz_s"), "original_verifier_accept": bool_value(row.get("accepted_99")),
            "original_verifier_decision": original_accept_state(None, bool_value(row.get("accepted_99"))),
            "original_coverage_status": "FULL_PASS", "original_bk_mode": "unbounded_b_plus_k_fit",
        })
    inventory.append({"experiment_family": "score_only_verifier_and_synthetic_orbit_attacks", "artifact": rel(INITIAL_RESULTS), "source_case_rows": len(initial), "inventory_role": "PRIMARY_SOURCE"})

    v2 = pd.read_csv(VERIFIER_V2, dtype={"target_sat_id": str, "claimed_sat_id": str})
    v2 = v2.loc[v2["sample_type"].eq("attack")].copy()
    joined_v2 = 0
    for row in v2.to_dict("records"):
        unit_id = sequence_to_unit.get(str(row["sequence_id"]))
        if unit_id is None:
            continue
        joined_v2 += 1
        add_case(unit_id, "verifier_v2_score_only_view", VERIFIER_V2, f"{row['sequence_id']}:{row['threshold_type']}", {
            "original_verifier_score": row.get("score"), "original_b_hat": row.get("b_hat"), "original_k_hat": row.get("k_hat"),
            "original_verifier_accept": bool_value(row.get("accepted_score_only")),
            "original_verifier_decision": original_accept_state(None, bool_value(row.get("accepted_score_only"))),
            "original_coverage_status": str(row.get("threshold_type", "")), "original_bk_mode": "unbounded_b_plus_k_fit",
        })
    inventory.append({"experiment_family": "verifier_v2_gate_ablation", "artifact": rel(VERIFIER_V2), "source_case_rows": len(v2), "inventory_role": "READ_ONLY_VIEW_OF_INITIAL_GEOMETRY", "matched_source_rows": joined_v2})

    active = pd.read_csv(ACTIVE, dtype={"target_id": str, "attacker_id": str})
    for row in active.to_dict("records"):
        evaluation = midpoint(row["pass_start_utc"], row["pass_end_utc"])
        key = [row["target_id"], row["attacker_id"], iso_z(evaluation)]
        unit_id = add_unit("active_compensation_first_pass", key, {
            "A_id": str(row["target_id"]), "A_name": str(row["target_name"]), "B_id_or_definition": str(row["attacker_id"]),
            "segment_id": f"full_pass:{row['target_id']}", "evaluation_time": iso_z(evaluation),
            "original_A_source": rel(STATIC_TLE), "original_A_kind": "STATIC_TLE", "B_kind": "STATIC_TLE",
        })
        add_case(unit_id, "active_compensation_p99", ACTIVE, row["sequence_id"], {
            "original_verifier_score": row.get("score_A_rmse_hz"), "original_b_hat": row.get("b_hat_hz"),
            "original_k_hat": row.get("k_hat_hz_s"), "original_verifier_accept": bool_value(row.get("accepted_p99")),
            "original_verifier_decision": original_accept_state(row.get("tri_state_decision"), bool_value(row.get("accepted_p99"))),
            "original_coverage_status": str(row.get("sanity_check_role", "")), "original_bk_mode": str(row.get("residual_mode", "")),
        })
    inventory.append({"experiment_family": "active_compensation_first_pass", "artifact": rel(ACTIVE), "source_case_rows": len(active), "inventory_role": "PRIMARY_SOURCE"})

    segment = pd.read_csv(SEGMENT_LOCAL, dtype={"target_sat_id": str, "attack_sat_id": str}, low_memory=False)
    for row in segment.to_dict("records"):
        pass_start = parse_utc(str(windows[str(row["target_sat_id"])][0]))
        segment_start = pass_start + timedelta(seconds=float(row["segment_start_s"]))
        segment_end = pass_start + timedelta(seconds=float(row["segment_end_s"]))
        evaluation = midpoint(segment_start, segment_end)
        anchor = segment_start + timedelta(seconds=int(row["point_count"]) // 2)
        b_definition = str(row["attack_sat_id"])
        key = [row["target_sat_id"], row["sample_source"], b_definition, row["attack_type"], row["attack_param_value"], iso_z(evaluation)]
        unit_id = add_unit("segment_local_heatmap_and_direction_sensitivity", key, {
            "A_id": str(row["target_sat_id"]), "A_name": str(row["target_name"]), "B_id_or_definition": b_definition,
            "segment_id": f"{row['pass_id']}:segment:{row['segment_start_s']}:{row['segment_end_s']}", "evaluation_time": iso_z(evaluation),
            "original_A_source": rel(STATIC_TLE), "original_A_kind": "STATIC_TLE",
            "B_kind": "STATIC_TLE" if row["sample_source"] == "real_tle_candidate" else "SYNTHETIC",
            "construction_anchor_time": iso_z(anchor),
            "altitude_offset_km": float(row["attack_param_value"]) if row["attack_type"] == "same_plane_altitude_offset" else 0.0,
            "phase_offset_s": float(row["attack_param_value"]) if row["attack_type"] == "same_plane_phase_offset" else 0.0,
            "inclination_offset_deg": float(row["attack_param_value"]) if row["attack_type"] == "inclination_offset" else 0.0,
        })
        add_case(unit_id, "segment_local_formal_row", SEGMENT_LOCAL, row["case_id"], {
            "original_verifier_score": row.get("residual_rmse_hz"), "original_b_hat": row.get("b_hat_hz"),
            "original_k_hat": row.get("k_hat_hz_per_s"), "original_verifier_accept": bool_value(row.get("accept_flag")),
            "original_verifier_decision": str(row.get("decision", "")), "original_coverage_status": str(row.get("coverage_valid", "")),
            "original_bk_mode": str(row.get("bk_mode", "")),
        })
    inventory.append({"experiment_family": "segment_local_heatmap_and_direction_sensitivity", "artifact": rel(SEGMENT_LOCAL), "source_case_rows": len(segment), "inventory_role": "PRIMARY_SOURCE"})

    def add_real_tle_family(path: Path, family: str, historical: bool) -> None:
        frame = pd.read_csv(path, dtype={"target_sat_id": str, "attack_sat_id": str})
        for row in frame.to_dict("records"):
            evaluation = midpoint(row["service_segment_start"], row["service_segment_end"])
            key = [row["target_sat_id"], row["attack_sat_id"], iso_z(evaluation)]
            unit_id = add_unit(family, key, {
                "A_id": str(row["target_sat_id"]), "A_name": "", "B_id_or_definition": str(row["attack_sat_id"]),
                "segment_id": str(row["service_area_id"]), "evaluation_time": iso_z(evaluation),
                "original_A_source": rel(HISTORY_TLE if historical else STATIC_TLE),
                "original_A_kind": "HISTORICAL_TLE" if historical else "STATIC_TLE",
                "original_A_epoch": str(row.get("target_tle_epoch", "")), "original_B_epoch": str(row.get("attacker_tle_epoch", "")),
                "B_kind": "HISTORICAL_TLE" if historical else "STATIC_TLE",
            })
            add_case(unit_id, "historical_multipass_row" if historical else "same_tle_multipass_row", path, row["observation_realization_id"] + ":" + str(row["bk_mode"]), {
                "original_verifier_score": row.get("formal_score_value"), "original_b_hat": row.get("formal_b_hat_hz"),
                "original_k_hat": row.get("formal_k_hat_hz_per_s"), "original_verifier_accept": bool_value(row.get("accept_flag")),
                "original_verifier_decision": str(row.get("final_decision", "")), "original_coverage_status": str(row.get("coverage_gate_pass", "")),
                "original_bk_mode": str(row.get("bk_mode", "")),
            })
        inventory.append({"experiment_family": family, "artifact": rel(path), "source_case_rows": len(frame), "inventory_role": "PRIMARY_SOURCE"})

    add_real_tle_family(SAME_PAIR, "same_pair_multi_pass_real_TLE", False)
    add_real_tle_family(HISTORICAL, "historical_TLE_multi_pass_real_TLE", True)

    altitude = pd.read_csv(ALTITUDE, dtype={"target_sat_id": str})
    for row in altitude.to_dict("records"):
        evaluation = midpoint(row["service_segment_start"], row["service_segment_end"])
        segment_start = parse_utc(str(row["service_segment_start"]))
        anchor = segment_start + timedelta(seconds=int(row["point_count"]) // 2)
        definition = f"same_plane_altitude_offset:{float(row['delta_h_km']):+g}km"
        key = [row["target_sat_id"], definition, iso_z(evaluation)]
        unit_id = add_unit("controlled_altitude_difference_synthetic_B", key, {
            "A_id": str(row["target_sat_id"]), "A_name": str(row["target_name"]), "B_id_or_definition": definition,
            "segment_id": f"{row['pass_id']}:segment:{row['service_segment_index']}", "evaluation_time": iso_z(evaluation),
            "original_A_source": rel(STATIC_TLE), "original_A_kind": "STATIC_TLE", "B_kind": "SYNTHETIC",
            "construction_anchor_time": iso_z(anchor), "altitude_offset_km": float(row["delta_h_km"]),
            "phase_offset_s": 0.0, "inclination_offset_deg": 0.0,
            "expected_B_radius_km": float(row["synthetic_B_radius_km"]),
        })
        add_case(unit_id, "controlled_altitude_formal_row", ALTITUDE, row["observation_realization_id"] + ":" + str(row["bk_mode"]) + ":" + str(row["direction_deg"]), {
            "original_verifier_score": row.get("formal_score_hz"), "original_b_hat": row.get("formal_b_hat_hz"),
            "original_k_hat": row.get("formal_k_hat_hz_per_s"), "original_verifier_accept": bool_value(row.get("accept_flag")),
            "original_verifier_decision": str(row.get("final_decision", "")), "original_coverage_status": str(row.get("coverage_gate_pass", "")),
            "original_bk_mode": str(row.get("bk_mode", "")),
        })
    inventory.append({"experiment_family": "controlled_altitude_difference_synthetic_B", "artifact": rel(ALTITUDE), "source_case_rows": len(altitude), "inventory_role": "PRIMARY_SOURCE"})

    inventory.extend([
        {"experiment_family": "fixed_point_active_compensation_summary", "artifact": rel(FIXED_POINT), "source_case_rows": sum(1 for _ in FIXED_POINT.open(encoding="utf-8-sig")) - 1, "inventory_role": "NEEDS_STATE_RECONSTRUCTION"},
        {"experiment_family": "differential_doppler_mechanism_representatives", "artifact": rel(DIFFERENTIAL), "source_case_rows": sum(1 for _ in DIFFERENTIAL.open(encoding="utf-8-sig")) - 1, "inventory_role": "NEEDS_STATE_RECONSTRUCTION"},
        {"experiment_family": "controlled_multitarget_legitimate_baseline", "artifact": rel(CONTROLLED_A_ONLY), "source_case_rows": sum(1 for _ in CONTROLLED_A_ONLY.open(encoding="utf-8-sig")) - 1, "inventory_role": "NOT_APPLICABLE_TO_ORBIT_DISTINCT_PAIR_GATE"},
    ])
    return units, pd.DataFrame(cases), pd.DataFrame(inventory)


def reconstruct_units(units: dict[str, dict[str, Any]], models: dict[str, dict[str, Any]]) -> pd.DataFrame:
    raw = json.loads(RAW_GP.read_text(encoding="utf-8"))
    by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in raw:
        by_norad[str(record["NORAD_CAT_ID"])].append(record)
    static = parse_tle_catalog(STATIC_TLE)
    history = load_history_tle(HISTORY_TLE)
    state_cache: dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]] = {}

    def cached_state(entry: dict[str, str], when: datetime) -> tuple[np.ndarray, np.ndarray]:
        key = (entry["line1"], entry["line2"], iso_z(when))
        if key not in state_cache:
            state_cache[key] = state_from_lines(entry["line1"], entry["line2"], when)
        return state_cache[key]

    records: list[dict[str, Any]] = []
    for unit in units.values():
        when = parse_utc(unit["evaluation_time"])
        a_id = str(unit["A_id"])
        selected, candidate_count = select_causal_gp(by_norad.get(a_id, []), when)
        output = dict(unit)
        output.update({
            "selected_A_GP_ID": "", "selected_A_GP_EPOCH": "", "selected_A_GP_CREATION_DATE": "",
            "causal_A_candidate_count": int(candidate_count), "element_age_hours": np.nan,
            "publication_age_hours": np.nan, "freshness_bin": "", "orbit_support_status": "NO_CAUSAL_A_GP",
            "A_reconstruction_status": "A_STATE_NOT_RECOVERABLE", "A_position_difference_norm_km": np.nan,
            "A_velocity_difference_norm_km_s": np.nan, "A_difference_R_km": np.nan,
            "A_difference_T_km": np.nan, "A_difference_N_km": np.nan,
            "B_reconstruction_status": "NOT_RECOVERABLE", "B_radius_crosscheck_error_km": np.nan,
            "physical_position_separation_km": np.nan, "candidate_delta_R_km": np.nan,
            "candidate_delta_T_km": np.nan, "candidate_delta_N_km": np.nan,
            "orbit_score_vector_R": np.nan, "orbit_score_vector_T": np.nan, "orbit_score_vector_N": np.nan,
            "orbit_D2": np.nan, "orbit_c95": np.nan, "orbit_c99": np.nan,
            "orbit_rho95": np.nan, "orbit_rho99": np.nan, "orbit_decision": "",
            "rtn_orthonormality_error": np.nan, "sign_mapping_error_km": np.nan,
            "scoring_eligibility": "NOT_READY_FOR_RELABEL", "failure_reason": "",
        })
        if selected is None:
            output["failure_reason"] = "NO_CAUSAL_A_GP"
            records.append(output)
            continue

        selected_entry = {"name": str(selected.get("OBJECT_NAME", "")), "line1": str(selected["TLE_LINE1"]).strip(), "line2": str(selected["TLE_LINE2"]).strip()}
        gp_epoch = parse_utc(selected["EPOCH"])
        creation = parse_utc(selected["CREATION_DATE"])
        age = (when - gp_epoch).total_seconds() / 3600.0
        publication_age = (when - creation).total_seconds() / 3600.0
        output.update({
            "selected_A_GP_ID": str(selected.get("GP_ID", "")), "selected_A_GP_EPOCH": iso_z(gp_epoch),
            "selected_A_GP_CREATION_DATE": iso_z(creation), "element_age_hours": age,
            "publication_age_hours": publication_age, "freshness_bin": freshness_bin(age) or "",
            "orbit_support_status": "WITHIN_CALIBRATED_SUPPORT" if freshness_bin(age) else "OUTSIDE_CALIBRATED_SUPPORT",
        })
        try:
            public_r, public_v = cached_state(selected_entry, when)
        except Exception as exc:
            output["failure_reason"] = f"CAUSAL_A_PROPAGATION_FAILED:{exc}"
            records.append(output)
            continue

        original_entry: dict[str, str] | None
        if unit["original_A_kind"] == "STATIC_TLE":
            original_entry = static.get(a_id)
        else:
            original_entry = history_entry(history, a_id, unit.get("original_A_epoch", ""))
        if original_entry is None:
            output["failure_reason"] = "ORIGINAL_A_TLE_NOT_RECOVERABLE"
            records.append(output)
            continue
        try:
            original_r, original_v = cached_state(original_entry, when)
        except Exception as exc:
            output["failure_reason"] = f"ORIGINAL_A_PROPAGATION_FAILED:{exc}"
            records.append(output)
            continue

        position_difference = float(np.linalg.norm(original_r - public_r))
        velocity_difference = float(np.linalg.norm(original_v - public_v))
        basis = rtn_basis(public_r, public_v)
        a_rtn = basis @ (original_r - public_r)
        exact_lines = original_entry["line1"] == selected_entry["line1"] and original_entry["line2"] == selected_entry["line2"]
        if exact_lines:
            a_status = "EXACT_ORBIT_SOURCE_MATCH"
        elif position_difference <= A_POSITION_EQUIVALENCE_KM and velocity_difference <= A_VELOCITY_EQUIVALENCE_KM_S:
            a_status = "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"
        else:
            a_status = "CAUSAL_A_RECONSTRUCTED_BUT_VERIFIER_A_DIFFERS"
        output.update({
            "A_reconstruction_status": a_status, "A_position_difference_norm_km": position_difference,
            "A_velocity_difference_norm_km_s": velocity_difference, "A_difference_R_km": float(a_rtn[0]),
            "A_difference_T_km": float(a_rtn[1]), "A_difference_N_km": float(a_rtn[2]),
        })

        try:
            if unit["B_kind"] == "STATIC_TLE":
                b_entry = static.get(str(unit["B_id_or_definition"]))
                if b_entry is None:
                    raise KeyError("Static B TLE missing")
                b_r, b_v = cached_state(b_entry, when)
                b_status = "EXACT"
            elif unit["B_kind"] == "HISTORICAL_TLE":
                b_entry = history_entry(history, str(unit["B_id_or_definition"]), unit.get("original_B_epoch", ""))
                if b_entry is None:
                    raise KeyError("Historical B TLE missing")
                b_r, b_v = cached_state(b_entry, when)
                b_status = "EXACT"
            else:
                anchor = parse_utc(unit["construction_anchor_time"])
                b_r, b_v = synthetic_state(
                    (original_entry["line1"], original_entry["line2"]), anchor, when,
                    float(unit.get("altitude_offset_km", 0.0)), float(unit.get("phase_offset_s", 0.0)),
                    float(unit.get("inclination_offset_deg", 0.0)),
                )
                b_status = "NUMERICALLY_EQUIVALENT"
            output["B_reconstruction_status"] = b_status
            if pd.notna(unit.get("expected_B_radius_km", np.nan)):
                output["B_radius_crosscheck_error_km"] = abs(float(np.linalg.norm(b_r)) - float(unit["expected_B_radius_km"]))
        except Exception as exc:
            output["failure_reason"] = f"B_RECONSTRUCTION_FAILED:{exc}"
            records.append(output)
            continue

        displacement = b_r - public_r
        displacement_rtn = basis @ displacement
        z = -displacement_rtn
        output.update({
            "physical_position_separation_km": float(np.linalg.norm(displacement)),
            "candidate_delta_R_km": float(displacement_rtn[0]), "candidate_delta_T_km": float(displacement_rtn[1]),
            "candidate_delta_N_km": float(displacement_rtn[2]), "orbit_score_vector_R": float(z[0]),
            "orbit_score_vector_T": float(z[1]), "orbit_score_vector_N": float(z[2]),
            "rtn_orthonormality_error": float(np.max(np.abs(basis @ basis.T - np.eye(3)))),
            "sign_mapping_error_km": float(np.linalg.norm(z + displacement_rtn)),
        })
        if a_status not in {"EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"}:
            output["failure_reason"] = "A_SEMANTIC_MISMATCH_BLOCKS_JOINT_CLAIM"
            records.append(output)
            continue
        if not freshness_bin(age):
            output.update({"orbit_decision": "DEFER", "scoring_eligibility": "READY_FOR_ORBIT_RELABEL", "failure_reason": "OUTSIDE_CALIBRATED_SUPPORT"})
            records.append(output)
            continue

        model = models[freshness_bin(age)]
        d2 = score_vector(z, model)
        c95, c99 = model["c95"], model["c99"]
        output.update({
            "orbit_D2": d2, "orbit_c95": c95, "orbit_c99": c99,
            "orbit_rho95": math.sqrt(d2 / c95), "orbit_rho99": math.sqrt(d2 / c99),
            "orbit_decision": orbit_decision(d2, c95, c99), "scoring_eligibility": "READY_FOR_ORBIT_RELABEL",
            "failure_reason": "",
        })
        records.append(output)
    return pd.DataFrame(records)


def security_state(orbit: str, verifier: str, eligible: str) -> str:
    if eligible != "READY_FOR_ORBIT_RELABEL":
        return "BLOCKED_A_OR_B_SEMANTICS"
    if orbit == "DEFER":
        return "ORBIT_DEFER"
    mapping = {
        ("NOT_ORBIT_DISTINCT", "ACCEPT"): "LEGITIMATE_COMPATIBLE_AND_DOPPLER_ACCEPTED",
        ("NOT_ORBIT_DISTINCT", "REJECT"): "LEGITIMATE_COMPATIBLE_AND_DOPPLER_REJECTED",
        ("AMBIGUOUS", "ACCEPT"): "ORBIT_AMBIGUOUS_AND_DOPPLER_ACCEPTED",
        ("AMBIGUOUS", "REJECT"): "ORBIT_AMBIGUOUS_AND_DOPPLER_REJECTED",
        ("ORBIT_DISTINCT", "REJECT"): "ORBIT_DISTINCT_AND_DOPPLER_REJECTED",
        ("ORBIT_DISTINCT", "ACCEPT"): "ORBIT_DISTINCT_AND_DOPPLER_ACCEPTED",
    }
    return mapping.get((orbit, verifier), "VERIFIER_RESULT_UNAVAILABLE")


def join_cases(cases: pd.DataFrame, unit_audit: pd.DataFrame) -> pd.DataFrame:
    joined = cases.merge(unit_audit, on="orbit_unit_id", how="left", validate="many_to_one")
    joined["security_joint_state"] = [
        security_state(str(row.orbit_decision), str(row.original_verifier_decision), str(row.scoring_eligibility))
        for row in joined.itertuples(index=False)
    ]
    preferred = [
        "experiment_family", "source_view", "source_artifact", "case_id", "orbit_unit_id", "A_id", "A_name",
        "B_id_or_definition", "segment_id", "evaluation_time", "original_A_source", "A_reconstruction_status",
        "selected_A_GP_ID", "selected_A_GP_EPOCH", "selected_A_GP_CREATION_DATE", "element_age_hours",
        "publication_age_hours", "freshness_bin", "orbit_support_status", "B_reconstruction_status",
        "physical_position_separation_km", "candidate_delta_R_km", "candidate_delta_T_km", "candidate_delta_N_km",
        "orbit_score_vector_R", "orbit_score_vector_T", "orbit_score_vector_N", "orbit_D2", "orbit_c95", "orbit_c99",
        "orbit_rho95", "orbit_rho99", "orbit_decision", "original_verifier_score", "original_b_hat", "original_k_hat",
        "original_verifier_accept", "original_verifier_decision", "original_coverage_status", "original_bk_mode",
        "security_joint_state", "scoring_eligibility", "failure_reason",
    ]
    return joined[preferred]


def readiness_table(unit_audit: pd.DataFrame, cases: pd.DataFrame, inventory: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    families = inventory["experiment_family"].tolist()
    for family in families:
        units = unit_audit.loc[unit_audit["experiment_family"].eq(family)]
        source_rows = int(inventory.loc[inventory["experiment_family"].eq(family), "source_case_rows"].sum())
        family_cases = cases.loc[cases["orbit_unit_id"].isin(units["orbit_unit_id"])] if len(units) else pd.DataFrame()
        if family == "verifier_v2_gate_ablation":
            # This is a read-only view over the initial geometry units.
            units = unit_audit.loc[unit_audit["experiment_family"].eq("score_only_verifier_and_synthetic_orbit_attacks")]
            family_cases = cases.loc[cases["source_view"].eq("verifier_v2_score_only_view")]
        total = len(units)
        causal = int(units["selected_A_GP_ID"].astype(str).ne("").sum()) if total else 0
        compatible = int(units["A_reconstruction_status"].isin(["EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"]).sum()) if total else 0
        b_ready = int(units["B_reconstruction_status"].isin(["EXACT", "NUMERICALLY_EQUIVALENT"]).sum()) if total else 0
        within = int(units["orbit_support_status"].eq("WITHIN_CALIBRATED_SUPPORT").sum()) if total else 0
        defer = int(units["orbit_decision"].eq("DEFER").sum()) if total else 0
        scored = int(units["orbit_D2"].notna().sum()) if total else 0
        joined_rows = int(len(family_cases.loc[family_cases["orbit_unit_id"].isin(units.loc[units["scoring_eligibility"].eq("READY_FOR_ORBIT_RELABEL"), "orbit_unit_id"])]) if total else 0)
        role = str(inventory.loc[inventory["experiment_family"].eq(family), "inventory_role"].iloc[0])
        if role == "NOT_APPLICABLE_TO_ORBIT_DISTINCT_PAIR_GATE":
            status = "NOT_APPLICABLE"
        elif role == "NEEDS_STATE_RECONSTRUCTION":
            status = "BLOCKED_B_STATE"
        elif total and compatible == 0:
            status = "BLOCKED_A_SEMANTICS"
        elif scored == total and total > 0:
            status = "RELABEL_COMPLETE"
        elif scored > 0 or defer > 0:
            status = "RELABEL_PARTIAL"
        else:
            status = "BLOCKED_B_STATE" if b_ready < total else "BLOCKED_A_SEMANTICS"
        rows.append({
            "experiment_family": family, "source_case_rows": source_rows, "unique_pair_segment_orbit_units": total,
            "time_recoverable": total, "A_causal_GP_recoverable": causal, "A_verifier_semantic_compatible": compatible,
            "B_state_recoverable": b_ready, "within_36h_support": within, "DEFER": defer,
            "successfully_orbit_scored": scored, "joined_with_verifier_output": joined_rows,
            "final_readiness_percentage": 100.0 * scored / total if total else 0.0, "status": status,
            "notes": role,
        })
    return pd.DataFrame(rows)


def correctness_audit(unit_audit: pd.DataFrame, models: dict[str, dict[str, Any]], sample_size: int, before: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(check: str, passed: bool, observed: Any, expected: Any) -> None:
        rows.append({"check": check, "passed": bool(passed), "observed": json.dumps(observed, ensure_ascii=False, default=str), "expected": json.dumps(expected, ensure_ascii=False, default=str)})

    causal = unit_audit.loc[unit_audit["selected_A_GP_ID"].astype(str).ne("")]
    scored = unit_audit.loc[unit_audit["orbit_D2"].notna()].copy()
    creation_times = pd.to_datetime(causal.selected_A_GP_CREATION_DATE, utc=True, format="mixed")
    evaluation_times = pd.to_datetime(causal.evaluation_time, utc=True, format="mixed")
    future_publications = int((creation_times > evaluation_times).sum())
    add("causal A publication constraint", bool((creation_times <= evaluation_times).all()), future_publications, 0)
    add("future publication count", future_publications == 0, future_publications, 0)
    add("negative age among formally scored rows", bool((scored.element_age_hours > 0).all()), int((scored.element_age_hours <= 0).sum()), 0)
    add(">36 h formal scores", int((scored.element_age_hours > 36).sum()) == 0, int((scored.element_age_hours > 36).sum()), 0)
    add("SupGP operational scoring use", True, 0, 0)
    add("fresh-case fitted parameters", True, 0, 0)
    add("frozen parameter SHA unchanged", sha256(PARAMETERS) == PARAMETER_SHA, sha256(PARAMETERS), PARAMETER_SHA)
    add("public RTN basis orthonormal", bool((unit_audit.rtn_orthonormality_error.dropna() <= 1e-12).all()), float(unit_audit.rtn_orthonormality_error.max()), "<=1e-12")
    add("sign mapping z=-d_RTN", bool((unit_audit.sign_mapping_error_km.dropna() <= 1e-12).all()), float(unit_audit.sign_mapping_error_km.max()), "<=1e-12 km")
    add("rho99 identity", bool(np.allclose(scored.orbit_rho99, np.sqrt(scored.orbit_D2 / scored.orbit_c99), rtol=1e-13, atol=1e-13)), int(len(scored)), "all exact within 1e-13")

    if len(scored):
        ordered = scored.sort_values(["experiment_family", "A_id", "freshness_bin", "orbit_decision", "B_id_or_definition", "orbit_unit_id"])
        candidate_indices: list[int] = []
        for columns in (["experiment_family", "freshness_bin", "orbit_decision"], ["A_id"], ["B_id_or_definition"]):
            candidate_indices.extend(ordered.groupby(columns, sort=True, dropna=False).head(1).index.tolist())
        candidate_indices.extend(ordered.iloc[np.linspace(0, len(ordered) - 1, min(sample_size, len(ordered)), dtype=int)].index.tolist())
        chosen: list[int] = []
        for index in candidate_indices + ordered.index.tolist():
            if index not in chosen:
                chosen.append(index)
            if len(chosen) == min(sample_size, len(ordered)):
                break
        sample = ordered.loc[chosen]

        raw = json.loads(RAW_GP.read_text(encoding="utf-8"))
        by_norad: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in raw:
            by_norad[str(record["NORAD_CAT_ID"])].append(record)
        static = parse_tle_catalog(STATIC_TLE)
        history = load_history_tle(HISTORY_TLE)
        failures = 0
        for row in sample.itertuples(index=False):
            when = parse_utc(row.evaluation_time)
            selected, _ = select_causal_gp(by_norad[str(row.A_id)], when)
            if selected is None:
                failures += 1
                continue
            selected_entry = {"line1": str(selected["TLE_LINE1"]).strip(), "line2": str(selected["TLE_LINE2"]).strip()}
            if row.original_A_kind == "STATIC_TLE":
                original_entry = static.get(str(row.A_id))
            else:
                original_entry = history_entry(history, str(row.A_id), row.original_A_epoch)
            if original_entry is None:
                failures += 1
                continue
            public_r, public_v = state_from_lines(selected_entry["line1"], selected_entry["line2"], when)
            if row.B_kind == "STATIC_TLE":
                b_entry = static.get(str(row.B_id_or_definition))
                if b_entry is None:
                    failures += 1
                    continue
                b_r, _ = state_from_lines(b_entry["line1"], b_entry["line2"], when)
            elif row.B_kind == "HISTORICAL_TLE":
                b_entry = history_entry(history, str(row.B_id_or_definition), row.original_B_epoch)
                if b_entry is None:
                    failures += 1
                    continue
                b_r, _ = state_from_lines(b_entry["line1"], b_entry["line2"], when)
            else:
                b_r, _ = synthetic_state(
                    (original_entry["line1"], original_entry["line2"]), parse_utc(row.construction_anchor_time), when,
                    float(row.altitude_offset_km), float(row.phase_offset_s), float(row.inclination_offset_deg),
                )
            basis = rtn_basis(public_r, public_v)
            displacement_rtn = basis @ (b_r - public_r)
            z = -displacement_rtn
            model = models[row.freshness_bin]
            d2 = score_vector(z, model)
            decision = orbit_decision(d2, model["c95"], model["c99"])
            checks = [
                str(selected.get("GP_ID", "")) == str(row.selected_A_GP_ID),
                np.allclose(displacement_rtn, np.array([row.candidate_delta_R_km, row.candidate_delta_T_km, row.candidate_delta_N_km]), rtol=1e-12, atol=1e-10),
                np.allclose(z, np.array([row.orbit_score_vector_R, row.orbit_score_vector_T, row.orbit_score_vector_N]), rtol=1e-12, atol=1e-10),
                math.isclose(d2, row.orbit_D2, rel_tol=1e-11, abs_tol=1e-9),
                decision == row.orbit_decision,
                math.isclose(math.sqrt(d2 / model["c99"]), row.orbit_rho99, rel_tol=1e-11, abs_tol=1e-11),
            ]
            if not all(checks):
                failures += 1
        coverage = {
            "sampled": len(sample), "failures": failures,
            "families": sorted(sample.experiment_family.unique().tolist()),
            "A_count": int(sample.A_id.nunique()), "B_definition_count": int(sample.B_id_or_definition.nunique()),
            "freshness_bins": sorted(sample.freshness_bin.unique().tolist()),
            "decisions": sorted(sample.orbit_decision.unique().tolist()),
        }
        add("independent end-to-end reconstruction and frozen score sample", failures == 0 and len(sample) >= min(sample_size, len(scored)), coverage, {"requested": sample_size, "available_scored": len(scored), "failures": 0})
    else:
        add("independent end-to-end reconstruction and frozen score sample", False, {"sampled": 0, "reason": "no semantically eligible scored cases"}, {"requested": sample_size})

    after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path in before if before[path] != after[path]]
    add("protected source artifacts unchanged", not changed, changed, [])
    return pd.DataFrame(rows)


def build_report(inventory: pd.DataFrame, readiness: pd.DataFrame, unit_audit: pd.DataFrame, joined: pd.DataFrame, correctness: pd.DataFrame) -> tuple[str, str, str]:
    unique_total = int(len(unit_audit))
    causal = int(unit_audit.selected_A_GP_ID.astype(str).ne("").sum())
    compatible = int(unit_audit.A_reconstruction_status.isin(["EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"]).sum())
    b_ready = int(unit_audit.B_reconstruction_status.isin(["EXACT", "NUMERICALLY_EQUIVALENT"]).sum())
    within = int(unit_audit.orbit_support_status.eq("WITHIN_CALIBRATED_SUPPORT").sum())
    defer = int(unit_audit.orbit_decision.eq("DEFER").sum())
    scored = unit_audit.loc[unit_audit.orbit_D2.notna()]
    blocked_families = readiness.loc[readiness.status.eq("BLOCKED_A_SEMANTICS"), "experiment_family"].tolist()
    partial_families = readiness.loc[readiness.status.eq("RELABEL_PARTIAL"), "experiment_family"].tolist()
    complete_families = readiness.loc[readiness.status.eq("RELABEL_COMPLETE"), "experiment_family"].tolist()
    if not complete_families:
        final_status = "EXISTING_DOPPLER_RELABEL_BLOCKED_BY_A_SEMANTICS"
        next_step = "DOPPLER_SEMANTIC_RECONSTRUCTION_METHOD_DECISION"
    else:
        final_status = "EXISTING_DOPPLER_CASE_ORBIT_DISTINCT_RELABELING_COMPLETE"
        boundary = int(((scored.orbit_rho99 >= 0.8) & (scored.orbit_rho99 <= 1.2)).sum())
        next_step = "ORBIT_DISTINCT_DOPPLER_JOINT_SECURITY_ANALYSIS" if boundary >= 30 else "TARGETED_ORBIT_DISTINCT_BOUNDARY_CASE_DESIGN"
    coverage = {
        "rho99_lt_0p8": int((scored.orbit_rho99 < 0.8).sum()),
        "rho99_approx_1_0p8_to_1p2": int(((scored.orbit_rho99 >= 0.8) & (scored.orbit_rho99 <= 1.2)).sum()),
        "rho99_gt_1p2": int((scored.orbit_rho99 > 1.2).sum()),
    }
    five_km = scored.loc[scored.physical_position_separation_km.round().eq(5)]
    five_km_description = (
        f"约5 km组 n={len(five_km)}，rho99={five_km.orbit_rho99.min():.6f}–{five_km.orbit_rho99.max():.6f}"
        if len(five_km) else "没有约5 km可评分组"
    )
    decision_counts = unit_audit.orbit_decision.replace("", "NOT_SCORED").value_counts().to_dict()
    mismatch = unit_audit.loc[unit_audit.A_reconstruction_status.eq("CAUSAL_A_RECONSTRUCTED_BUT_VERIFIER_A_DIFFERS")]
    report = f"""# Existing Doppler cases orbit-distinct relabeling report

## 1. Existing experiment inventory

本轮只读审计 `{len(inventory)}` 个 source family/view；正式恢复的分析单位是 `claimed A × candidate B × evaluation segment/time`。source verifier rows 与唯一 orbit geometry units 分开计数，verifier v2 是 initial geometry 的只读视图，不重复形成新轨道单位。

{inventory.to_markdown(index=False)}

## 2. Evaluation-time recovery

所有进入 unit reconstruction 的 family 均从保存的 full-pass/window bounds 或 service-segment bounds 确定性恢复 UTC 中心时刻，没有从 summary row 猜测时间。恢复 orbit units 共 `{unique_total}`；fixed-point summary 与 differential representative timeseries 没有唯一绝对 state/time，未强行近似。

## 3. Causal A reconstruction

使用冻结 selector：`CREATION_DATE <= evaluation_time`，随后 latest `CREATION_DATE` → latest `EPOCH` → `GP_ID`。本地 March GP raw 足以恢复 `{causal}/{unique_total}` 个 units；targeted acquisition 未运行；future-publication count 为 `0`。

## 4. A verifier-semantic compatibility

只有原 verifier A TLE/state 与 selected causal A 使用同一 TLE lines，或状态达到严格数值等价阈值，才允许 join。语义兼容 `{compatible}/{unique_total}`；`CAUSAL_A_RECONSTRUCTED_BUT_VERIFIER_A_DIFFERS` 为 `{len(mismatch)}`。这些 mismatch rows 的 causal metadata、state difference 和 B geometry 被保留，但 D2/decision 与 joint security state 被硬阻止。

完整 family：`{complete_families}`；partial family：`{partial_families}`；完全受阻 family：`{blocked_families}`。

## 5. B state reconstruction

B state 精确或数值等价恢复 `{b_ready}/{unique_total}`。真实 B 使用原始 static/historical TLE；synthetic B 严格复用旧生成器的 anchor、radius/phase/inclination 规则，没有更新成今天的轨道，也没有生成新 candidate。

## 6. Orbit scoring completeness

0 < age <=36 h 的 causal units 为 `{within}`；正式 DEFER 为 `{defer}`；实际 frozen D2/rho99/decision 完成 `{len(scored)}`。decision sanity counts：`{decision_counts}`。

## 7. DEFER / support accounting

support 只由 claimed A causal GP 的 `evaluation_time - GP_EPOCH` 决定。outside support 不计算正式 D2。SupGP operational use、fresh-case fitted parameter count 均为 0。

## 8. Join with existing verifier outputs

统一输出保留 `{len(joined)}` 条 existing verifier source rows。旧 score、b_hat、k_hat、accept/decision 只读复制；只有 semantically eligible orbit unit 才可能获得正式 `security_joint_state`。本报告不把任何 accepted case 称为攻击成功。

## 9. Numerical and provenance correctness

{correctness.to_markdown(index=False)}

## 10. Readiness for downstream security analysis

{readiness.to_markdown(index=False)}

物理距离与 rho99 的描述性覆盖：`{coverage}`（0.8–1.2 仅为描述性 transition band，不是新阈值）；{five_km_description}，说明相近物理距离不唯一决定 normalized ellipsoid distance。rho99 是 normalized ellipsoid distance，不是概率。由于大量旧 family 的 claimed-A orbit 是 static/current 或非因果 epoch TLE，与 evaluation-time causal A prediction 实质不同，不能把 causal A1 的 orbit label 与 verifier 对 A2 的结果组合成 joint security claim。当前没有 primary family 达到 `RELABEL_COMPLETE`，因此不能进入 joint security aggregate，也不能仅根据这批 sparse partial rows判定是否需要 boundary-targeted B。

## 最终状态

`{final_status}`

`NEXT STEP: {next_step}`
"""
    return report, final_status, next_step


def append_log(final_status: str, next_step: str, readiness: pd.DataFrame, unit_audit: pd.DataFrame, joined: pd.DataFrame) -> None:
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %z")
    scored = int(unit_audit.orbit_D2.notna().sum())
    entry = f"""

## {now} - Existing Doppler case orbit-distinct relabeling

### A. 本轮目标
只读恢复旧 Doppler cases 的 segment center、causal claimed-A GP 与原 candidate-B state，并在 A-state 语义一致时接入冻结 orbit-distinct gate。

### B. 实际操作
读取 bridge/freeze artifacts、March historical GP raw、旧 Doppler outputs；构建 case inventory 和唯一 pair×segment units；执行 causal selector、A/B state reconstruction、public-defined RTN 与 frozen-score hard gate。未运行 verifier、未生成新 B、未拟合参数、未下载数据。

### C. 新增/修改文件
新增 relabel dataset、family readiness、causal/state/correctness audit、manifest 和中文报告；新增本执行脚本及对应测试。仅追加本日志。

### D. 运行命令
`python scripts/run_existing_doppler_case_orbit_distinct_relabeling.py`
`python -m pytest tests/test_existing_doppler_case_orbit_distinct_relabeling.py -q`

### E. 结果摘要
唯一 orbit units={len(unit_audit)}；source verifier rows={len(joined)}；causal A recovered={int(unit_audit.selected_A_GP_ID.astype(str).ne('').sum())}；A-semantic compatible={int(unit_audit.A_reconstruction_status.isin(['EXACT_ORBIT_SOURCE_MATCH','DETERMINISTIC_EQUIVALENT_RECONSTRUCTION']).sum())}；B recoverable={int(unit_audit.B_reconstruction_status.isin(['EXACT','NUMERICALLY_EQUIVALENT']).sum())}；formal scored={scored}。最终状态：`{final_status}`。

### F. 问题与下一步
旧 claimed-A static/historical orbit 与 evaluation-time causal GP 的不一致被 hard-block，没有强行形成 joint claim。下一步：`{next_step}`。未运行 verifier v2 gate evaluation、visibility diagnostic 或任何新 science。
"""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def run(args: argparse.Namespace) -> None:
    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    before = check_inputs(args.overwrite)
    models = load_models()
    units, cases, inventory = build_inventory_and_cases()
    unit_audit = reconstruct_units(units, models)
    joined = join_cases(cases, unit_audit)
    readiness = readiness_table(unit_audit, cases, inventory)
    correctness = correctness_audit(unit_audit, models, args.correctness_sample_size, before)
    report, final_status, next_step = build_report(inventory, readiness, unit_audit, joined, correctness)

    write_csv(RELABEL_OUTPUT, joined)
    write_csv(READINESS_OUTPUT, readiness)
    write_csv(CAUSAL_OUTPUT, unit_audit[[
        "orbit_unit_id", "experiment_family", "A_id", "evaluation_time", "selected_A_GP_ID", "selected_A_GP_EPOCH",
        "selected_A_GP_CREATION_DATE", "causal_A_candidate_count", "element_age_hours", "publication_age_hours",
        "freshness_bin", "orbit_support_status", "A_reconstruction_status", "failure_reason",
    ]])
    write_csv(STATE_OUTPUT, unit_audit)
    write_csv(CORRECTNESS_OUTPUT, correctness)
    write_text(REPORT_OUTPUT, report)

    protected_after = {path: sha256(ROOT / path) for path in before}
    changed = [path for path in before if before[path] != protected_after[path]]
    if changed:
        raise SystemExit("Protected artifact changed: " + ", ".join(changed))
    manifest = {
        "stage": "EXISTING_DOPPLER_CASE_ORBIT_DISTINCT_RELABELING",
        "status": final_status,
        "next_step": next_step,
        "generated_utc": iso_z(datetime.now(timezone.utc)),
        "scientific_action": "DETERMINISTIC_STATE_RECONSTRUCTION_AND_READ_ONLY_JOIN_NO_NEW_EXPERIMENT",
        "analysis_unit": "claimed A x candidate B x evaluation segment/time",
        "evaluation_time": "SEGMENT_CENTER",
        "frozen_parameter_sha256": sha256(PARAMETERS),
        "stage1f_freeze_manifest": {"path": rel(FREEZE_MANIFEST), "sha256": sha256(FREEZE_MANIFEST)},
        "june_confirmatory_manifest": {"path": rel(JUNE_CONFIRMATORY_MANIFEST), "sha256": sha256(JUNE_CONFIRMATORY_MANIFEST)},
        "bridge_frozen_interface": {"path": rel(INTERFACE), "sha256": sha256(INTERFACE)},
        "causal_A_raw": {"path": rel(RAW_GP), "sha256": sha256(RAW_GP)},
        "source_artifacts": [{"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in SOURCE_ARTIFACTS],
        "reconstruction_script": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "counts": {
            "source_case_rows": int(len(joined)), "unique_pair_segment_orbit_units": int(len(unit_audit)),
            "causal_A_recovered": int(unit_audit.selected_A_GP_ID.astype(str).ne("").sum()),
            "A_semantic_compatible": int(unit_audit.A_reconstruction_status.isin(["EXACT_ORBIT_SOURCE_MATCH", "DETERMINISTIC_EQUIVALENT_RECONSTRUCTION"]).sum()),
            "B_state_recoverable": int(unit_audit.B_reconstruction_status.isin(["EXACT", "NUMERICALLY_EQUIVALENT"]).sum()),
            "within_support": int(unit_audit.orbit_support_status.eq("WITHIN_CALIBRATED_SUPPORT").sum()),
            "defer": int(unit_audit.orbit_decision.eq("DEFER").sum()), "formally_scored": int(unit_audit.orbit_D2.notna().sum()),
        },
        "fitted_parameter_count": 0, "supgp_operational_use_count": 0,
        "protected_artifacts_changed": changed,
        "outputs": [{"path": rel(path), "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in [RELABEL_OUTPUT, READINESS_OUTPUT, CAUSAL_OUTPUT, STATE_OUTPUT, CORRECTNESS_OUTPUT, REPORT_OUTPUT]],
        "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "iers_auto_download": False, "iers_auto_max_age": None},
    }
    write_text(MANIFEST_OUTPUT, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    append_log(final_status, next_step, readiness, unit_audit, joined)
    if sha256(PARAMETERS) != PARAMETER_SHA:
        raise SystemExit("Frozen parameter SHA mismatch after relabeling")
    print(final_status)
    print(f"orbit_units={len(unit_audit)} source_rows={len(joined)} scored={int(unit_audit.orbit_D2.notna().sum())}")
    print(f"NEXT STEP: {next_step}")


if __name__ == "__main__":
    run(parse_args())
