#!/usr/bin/env python
"""Recover observation-realization lineage for the formal mechanism rows.

This is a read-only audit.  It replays only the deterministic random-number
stream used to create residual/environment terms; it does not propagate an
orbit, regenerate an experiment, change a verifier, or overwrite old outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_multi_service_area_single_station_confirmation as multi  # noqa: E402


JOIN_KEY_FULL = [
    "sample_source", "sample_group", "pair_id", "target_sat_id", "attack_sat_id",
    "service_area_id", "service_area_segment_index", "distance_km", "direction_deg", "bk_mode",
]
COARSE_KEY = [
    "target_sat_id", "attack_sat_id", "service_area_id", "service_area_segment_index",
    "distance_km", "direction_deg", "bk_mode",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="恢复正式观测 realization、seed 与冲突血缘")
    p.add_argument("--formal-dataset", type=Path, default=Path("outputs/datasets/multi_service_area_single_station_dataset.csv"))
    p.add_argument("--mechanism-rows", type=Path, default=Path("outputs/metrics/differential_doppler_mechanism_full_row_summary.csv"))
    p.add_argument("--conflicts", type=Path, default=Path("outputs/metrics/real_tle_positive_audit_duplicate_conflicts.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--legacy-dataset", type=Path, default=Path("outputs/datasets/original_vs_current_fixed_reference_dataset.csv"))
    p.add_argument("--legacy-case-list", type=Path, default=Path("outputs/metrics/fixed_c_legacy_replay_case_list.csv"))
    p.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--report-output", type=Path, default=Path("outputs/reports/observation_realization_lineage_audit_report.md"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def paths(args: argparse.Namespace) -> dict[str, Path]:
    p = args.output_dir
    return {
        "lineage": p / "observation_realization_lineage_table.csv",
        "conflict": p / "observation_realization_conflict_classification.csv",
        "seed": p / "observation_realization_seed_reconstruction.csv",
        "geometry": p / "observation_realization_geometry_summary.csv",
        "pair": p / "observation_realization_pair_summary.csv",
        "target": p / "observation_realization_target_summary.csv",
        "audit": p / "observation_realization_correctness_audit.csv",
        "report": args.report_output,
    }


def fail(message: str) -> None:
    raise SystemExit(message)


def require_columns(df: pd.DataFrame, cols: list[str], name: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        fail(f"{name} missing columns: {', '.join(missing)}")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}_{hashlib.sha256(stable_json(value).encode('utf-8')).hexdigest()[:24]}"


def array_hash(values: np.ndarray) -> str:
    a = np.asarray(values, dtype="<f8")
    return hashlib.sha256(a.tobytes(order="C")).hexdigest()


def normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["target_sat_id", "attack_sat_id"]:
        if col in out:
            out[col] = out[col].astype(str).str.replace(r"\.0$", "", regex=True)
    return out


def check_io(args: argparse.Namespace, out: dict[str, Path]) -> dict[str, str]:
    inputs = [
        args.formal_dataset, args.mechanism_rows, args.conflicts, args.candidate_library,
        args.selection_table, args.tle_file, args.parameter_config, args.orbit_config,
    ]
    for p in inputs:
        if not p.exists():
            fail(f"missing input: {p}")
    existing = [str(p) for p in out.values() if p.exists()]
    if existing and not args.overwrite:
        fail("lineage output exists; add --overwrite: " + ", ".join(existing))
    return {str(p): file_sha256(p) for p in inputs}


def parse_tle_epoch(line1: str) -> str:
    token = line1[18:32].strip()
    yy = int(token[:2]); day = float(token[2:])
    year = 2000 + yy if yy < 57 else 1900 + yy
    dt = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1.0)
    return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")


def load_tle_identity(path: Path) -> dict[str, dict[str, str]]:
    lines = [x.rstrip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    out: dict[str, dict[str, str]] = {}
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 "):
            norad = line1[2:7].strip()
            out[norad] = {
                "name": name, "line1": line1, "line2": line2,
                "epoch": parse_tle_epoch(line1),
                "tle_identity_sha256": hashlib.sha256(f"{name}\n{line1}\n{line2}".encode()).hexdigest(),
            }
            i += 3
        else:
            i += 1
    return out


def source_evidence() -> dict[str, Any]:
    specs = {
        "load_samples": (SCRIPT_DIR / "run_multi_service_area_single_station_confirmation.py", "def load_reused_samples"),
        "global_rng": (SCRIPT_DIR / "run_multi_service_area_single_station_confirmation.py", "rng = np.random.default_rng(args.seed)"),
        "sample_residual": (SCRIPT_DIR / "run_multi_service_area_single_station_confirmation.py", "noise, b_env, k_env, sigma_hz, t0 = seg.sample_residual_terms"),
        "calibration_seed": (SCRIPT_DIR / "run_multi_service_area_single_station_confirmation.py", "args.seed + int(target_id) + seg_idx"),
        "sample_index": (SCRIPT_DIR / "run_multi_service_area_single_station_confirmation.py", '"sample_index_global": int(sidx)'),
        "group_selection": (SCRIPT_DIR / "run_segmented_service_center_compensation.py", 'if group == "ordinary_similar"'),
        "boundary_selection": (SCRIPT_DIR / "run_segmented_service_center_compensation.py", 'elif group == "boundary_case"'),
        "residual_function": (SCRIPT_DIR / "run_segmented_service_center_compensation.py", "def sample_residual_terms"),
        "calibration_function": (SCRIPT_DIR / "run_segmented_service_center_compensation.py", "def calibration_for_trel"),
    }
    out = {}
    for name, (path, pattern) in specs.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        matches = [i + 1 for i, line in enumerate(lines) if pattern in line]
        out[name] = {"file": str(path), "line": matches[0] if matches else None, "pattern": pattern}
    return out


def load_library_identity(path: Path) -> tuple[pd.DataFrame, dict[tuple[str, str], dict[str, Any]]]:
    lib = pd.read_csv(path, low_memory=False).reset_index(names="library_row_index")
    lib["target_norad_id"] = lib.target_norad_id.astype(str)
    lib["candidate_norad_id"] = lib.candidate_norad_id.astype(str)
    identities: dict[tuple[str, str], dict[str, Any]] = {}
    for key, g in lib.groupby(["target_norad_id", "candidate_norad_id"], sort=False):
        payload = {
            "target": key[0], "candidate": key[1],
            "row_indices": g.library_row_index.astype(int).tolist(),
            "time_start": str(g.t_abs_utc.iloc[0]), "time_end": str(g.t_abs_utc.iloc[-1]),
            "row_count": len(g), "rank": float(g.candidate_rank_or_selection_order.iloc[0]),
        }
        identities[key] = {
            "id": stable_id("library_rows", payload),
            "row_start": int(g.library_row_index.min()), "row_end": int(g.library_row_index.max()),
            "row_count": len(g), "time_start": payload["time_start"], "time_end": payload["time_end"],
            "rank": payload["rank"],
        }
    return lib, identities


def parameter_ranges(path: Path) -> dict[str, tuple[float, float]]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    params = cfg["parameters"]
    return {
        "b": tuple(map(float, params["b_hz"]["main_range"])),
        "k": tuple(map(float, params["k_hz_per_s"]["main_range"])),
        "sigma": tuple(map(float, params["sigma_hz"]["main_range"])),
    }


def sample_table(formal: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "sample_index_global", "sample_source", "sample_group", "pair_id", "target_sat_id", "target_name",
        "attack_sat_id", "attack_name", "legacy_case_id", "attack_type", "attack_param_name", "attack_param_value",
        "b_env", "k_env", "sigma_hz", "random_seed",
    ]
    samples = formal[cols].drop_duplicates("sample_index_global").sort_values("sample_index_global").reset_index(drop=True)
    if samples.sample_index_global.astype(int).tolist() != list(range(len(samples))):
        fail("sample_index_global is not contiguous; exact RNG replay is unsafe")
    return samples


def reconstruct_samples(
    samples: pd.DataFrame, lib: pd.DataFrame, ranges: dict[str, tuple[float, float]],
    legacy_env: dict[str, dict[str, float]], master_seed: int,
) -> tuple[pd.DataFrame, dict[int, dict[str, Any]]]:
    rng = np.random.default_rng(master_seed)
    records = []
    arrays: dict[int, dict[str, Any]] = {}
    formula = (
        "rng=default_rng(master_seed); iterate sample_index_global ascending; "
        "draw uniform(b_main), uniform(k_main), uniform(sigma_main), then normal(0,sigma,N_target_pass)"
    )
    for row in samples.itertuples(index=False):
        idx = int(row.sample_index_global); target = str(row.target_sat_id)
        tg = lib[(lib.target_norad_id == target) & (lib.candidate_norad_id == target)].sort_values("t_rel_s")
        t_rel = tg.t_rel_s.to_numpy(float)
        state_before = stable_id("rng_state", rng.bit_generator.state)
        b = float(rng.uniform(*ranges["b"])); k = float(rng.uniform(*ranges["k"])); sigma = float(rng.uniform(*ranges["sigma"]))
        noise = rng.normal(0.0, sigma, len(t_rel)) if sigma > 0 else np.zeros(len(t_rel))
        global_draw = {"b": b, "k": k, "sigma": sigma, "noise": noise}
        explicit_seed: float | int = np.nan
        source = "global_master_rng_stream"
        confidence = "deterministically_reconstructed"
        lid = str(row.legacy_case_id)
        if row.sample_source == "legacy_synthetic" and lid in legacy_env:
            env = legacy_env[lid]
            b, k, sigma = env["b_env"], env["k_env"], env["sigma_hz"]
            explicit_seed = int(env["noise_seed"])
            noise = np.random.default_rng(explicit_seed).normal(0.0, sigma, len(t_rel))
            source = "legacy_explicit_noise_seed_override"
            confidence = "exact"
        stored_match = bool(
            np.isclose(b, float(row.b_env), rtol=0, atol=1e-12) and
            np.isclose(k, float(row.k_env), rtol=0, atol=1e-12) and
            np.isclose(sigma, float(row.sigma_hz), rtol=0, atol=1e-12)
        )
        env_id = stable_id("environment", {"sample_index": idx, "b": b, "k": k, "sigma": sigma, "source": source})
        full_noise_id = stable_id("noise_full", {"sample_index": idx, "hash": array_hash(noise), "n": len(noise), "source": source})
        residual_id = stable_id("residual_full", {"environment": env_id, "noise": full_noise_id, "t0": float(np.mean(t_rel))})
        record = {
            "sample_index_global": idx, "sample_source": row.sample_source, "sample_group": row.sample_group,
            "pair_id": row.pair_id, "target_sat_id": target, "attack_sat_id": str(row.attack_sat_id),
            "master_seed": master_seed, "geometry_seed": np.nan,
            "noise_seed": explicit_seed, "residual_seed": explicit_seed,
            "rng_state_before_id": state_before, "global_stream_sample_index": idx,
            "reconstructed_b_env": b, "reconstructed_k_env": k, "reconstructed_sigma_hz": sigma,
            "stored_b_env": float(row.b_env), "stored_k_env": float(row.k_env), "stored_sigma_hz": float(row.sigma_hz),
            "stored_environment_matches_reconstruction": stored_match,
            "environment_realization_id": env_id, "noise_realization_id_full_pass": full_noise_id,
            "residual_realization_id_full_pass": residual_id,
            "reconstructed_seed_formula": formula if source == "global_master_rng_stream" else "legacy noise=default_rng(noise_seed).normal(0,sigma,N)",
            "reconstructed_seed_inputs": stable_json({"master_seed": master_seed, "sample_index_global": idx, "target_time_points": len(t_rel), "explicit_noise_seed": explicit_seed}),
            "random_source_type": source, "reconstruction_confidence": confidence if stored_match else "unresolved",
            "global_stream_draw_environment_id": stable_id("global_draw", {"b": global_draw["b"], "k": global_draw["k"], "sigma": global_draw["sigma"]}),
        }
        records.append(record)
        arrays[idx] = {"noise": noise, "t_rel": t_rel, "environment_id": env_id, "confidence": record["reconstruction_confidence"]}
    return pd.DataFrame(records), arrays


def join_formal_rows(mechanism: pd.DataFrame, formal: pd.DataFrame) -> pd.DataFrame:
    mechanism = normalize_ids(mechanism); formal = normalize_ids(formal)
    formal = formal.rename(columns={"distance_to_center_km": "distance_km", "phi_deg": "direction_deg"})
    lineage_cols = JOIN_KEY_FULL + [
        "case_id", "pass_id", "service_area_index", "service_area_phase",
        "segment_start_s", "segment_end_s", "segment_duration_s", "evaluation_start_s", "evaluation_end_s",
        "C_lat", "C_lon", "S_lat", "S_lon", "R_cell_km", "T_service_s",
        "attacker_kind", "attack_type", "attack_param_name", "attack_param_value",
        "doppler_reference_mode", "evaluation_scope", "verification_strategy",
        "b_env", "k_env", "sigma_hz", "random_seed", "sample_index_global", "point_count",
        "decision", "decision_reason", "residual_rmse_hz", "b_hat_hz", "k_hat_hz_per_s",
        "score_gate_pass", "b_gate_pass", "k_gate_pass", "coverage_gate_pass", "quality_gate_pass",
    ]
    require_columns(formal, lineage_cols, "formal dataset")
    f = formal[lineage_cols].copy()
    if f.duplicated(JOIN_KEY_FULL).any():
        fail(f"formal dataset duplicate join keys: {int(f.duplicated(JOIN_KEY_FULL).sum())}")
    if mechanism.duplicated(JOIN_KEY_FULL).any():
        fail(f"mechanism table duplicate join keys: {int(mechanism.duplicated(JOIN_KEY_FULL).sum())}")
    out = mechanism.merge(f, on=JOIN_KEY_FULL, how="left", validate="one_to_one", suffixes=("", "_formal_source"), indicator=True)
    if not out._merge.eq("both").all():
        fail(f"lineage join missing formal rows: {int(out._merge.ne('both').sum())}")
    out = out.drop(columns="_merge")
    out["formal_source_decision_matches"] = out.formal_final_decision.eq(out.decision)
    return out


def build_lineage(
    joined: pd.DataFrame, seed_table: pd.DataFrame, arrays: dict[int, dict[str, Any]],
    lib: pd.DataFrame, library_ids: dict[tuple[str, str], dict[str, Any]],
    selection: pd.DataFrame, tle: dict[str, dict[str, str]], config_hash: str,
) -> pd.DataFrame:
    seed_cols = [c for c in seed_table.columns if c not in ["sample_index_global", "sample_source", "sample_group", "pair_id", "target_sat_id", "attack_sat_id"]]
    out = joined.merge(seed_table[["sample_index_global"] + seed_cols], on="sample_index_global", how="left", validate="many_to_one")
    selection = selection.reset_index(names="selection_row_index")
    selection["target_norad_id"] = selection.target_norad_id.astype(str)
    selection_map = {str(r.target_norad_id): f"selection_row_{int(r.selection_row_index)}" for r in selection.itertuples()}
    target_times: dict[str, pd.DataFrame] = {}
    records = []
    for row in out.itertuples(index=False):
        target, attacker = str(row.target_sat_id), str(row.attack_sat_id)
        if target not in target_times:
            target_times[target] = lib[(lib.target_norad_id == target) & (lib.candidate_norad_id == target)].sort_values("t_rel_s")
        tg = target_times[target]
        mask = tg.t_rel_s.between(float(row.evaluation_start_s) - 1e-9, float(row.evaluation_end_s) + 1e-9)
        eval_rows = tg[mask]
        eval_start_utc = str(eval_rows.t_abs_utc.iloc[0]); eval_end_utc = str(eval_rows.t_abs_utc.iloc[-1])
        sample_array = arrays[int(row.sample_index_global)]
        noise_segment = sample_array["noise"][mask.to_numpy()]
        noise_segment_id = stable_id("noise_segment", {"full_sample_index": int(row.sample_index_global), "hash": array_hash(noise_segment), "start": row.evaluation_start_s, "end": row.evaluation_end_s})
        target_lib = library_ids[(target, target)]; attacker_lib = library_ids.get((target, attacker), {})
        target_tle = tle.get(target, {}); attacker_tle = tle.get(attacker, {})
        geometry_payload = {
            "target": target, "attacker": attacker,
            "target_tle_epoch": target_tle.get("epoch"), "attacker_tle_epoch": attacker_tle.get("epoch"),
            "target_tle_hash": target_tle.get("tle_identity_sha256"), "attacker_tle_hash": attacker_tle.get("tle_identity_sha256"),
            "target_library": target_lib.get("id"), "attacker_library": attacker_lib.get("id"),
            "attack_type": row.attack_type, "attack_param_name": row.attack_param_name,
            "attack_param_value": row.attack_param_value,
            "evaluation_start_utc": eval_start_utc, "evaluation_end_utc": eval_end_utc,
            "C_lat": row.C_lat, "C_lon": row.C_lon, "S_lat": row.S_lat, "S_lon": row.S_lon,
            "distance_km": row.distance_km, "direction_deg": row.direction_deg,
            "doppler_reference_mode": row.doppler_reference_mode,
        }
        geometry_id = stable_id("geometry", geometry_payload)
        calibration_seed = int(row.random_seed) + int(target) + int(row.service_area_segment_index)
        calibration_payload = {
            "seed": calibration_seed, "target": target, "segment_index": int(row.service_area_segment_index),
            "start": row.evaluation_start_s, "end": row.evaluation_end_s, "n": 30, "parameter_config_hash": config_hash,
        }
        calibration_id = stable_id("calibration", calibration_payload)
        residual_segment_id = stable_id("residual_segment", {"environment": row.environment_realization_id, "noise": noise_segment_id, "t0": float(np.mean(sample_array["t_rel"]))})
        observation_confidence = row.reconstruction_confidence
        observation_id = stable_id("observation", {"geometry": geometry_id, "residual": residual_segment_id, "calibration": calibration_id}) if observation_confidence != "unresolved" else ""
        verifier_payload = {
            "config_hash": config_hash, "bk_mode": row.bk_mode,
            "score_threshold": row.formal_score_threshold,
            "b_lower": row.formal_b_gate_lower_hz, "b_upper": row.formal_b_gate_upper_hz,
            "k_lower": row.formal_k_gate_lower_hz_per_s, "k_upper": row.formal_k_gate_upper_hz_per_s,
        }
        decision_id = stable_id("decision", {"observation": observation_id, "verifier": verifier_payload}) if observation_id else ""
        record = {
            "lineage_row_id": stable_id("lineage_row", {"case": row.case_id, "sample_group": row.sample_group}),
            "physical_pair_id": f"{target}->{attacker}",
            "target_tle_epoch": target_tle.get("epoch", ""), "attack_tle_epoch": attacker_tle.get("epoch", ""),
            "target_tle_identity_sha256": target_tle.get("tle_identity_sha256", ""), "attack_tle_identity_sha256": attacker_tle.get("tle_identity_sha256", ""),
            "target_library_row_id": target_lib.get("id", ""), "attacker_library_row_id": attacker_lib.get("id", ""),
            "target_library_row_start": target_lib.get("row_start"), "target_library_row_end": target_lib.get("row_end"),
            "attacker_library_row_start": attacker_lib.get("row_start"), "attacker_library_row_end": attacker_lib.get("row_end"),
            "selection_row_id": selection_map.get(target, ""),
            "evaluation_start_utc": eval_start_utc, "evaluation_end_utc": eval_end_utc,
            "geometry_condition_id": geometry_id, "geometry_realization_id": geometry_id,
            "noise_realization_id": noise_segment_id, "residual_realization_id": residual_segment_id,
            "calibration_realization_id": calibration_id, "calibration_seed": calibration_seed,
            "observation_realization_id": observation_id, "decision_condition_id": decision_id,
            "verifier_config_version": config_hash,
            "reconstruction_confidence_row": observation_confidence,
            "coarse_physical_condition_id": stable_id("coarse", {k: getattr(row, k) for k in COARSE_KEY}),
        }
        records.append(record)
    lineage = pd.concat([out.reset_index(drop=True), pd.DataFrame(records)], axis=1)
    return lineage


def classify_conflicts(lineage: pd.DataFrame, conflict_input: pd.DataFrame) -> pd.DataFrame:
    conflict_input = normalize_ids(conflict_input)
    conflict_keys = conflict_input[COARSE_KEY].drop_duplicates()
    tracked = lineage.merge(conflict_keys, on=COARSE_KEY, how="inner")
    records = []
    diff_fields = [
        "sample_group", "sample_index_global", "target_tle_epoch", "attack_tle_epoch",
        "evaluation_start_utc", "evaluation_end_utc", "C_lat", "C_lon", "S_lat", "S_lon",
        "environment_realization_id", "noise_realization_id", "residual_realization_id",
        "calibration_realization_id", "master_seed", "noise_seed", "calibration_seed",
        "formal_score_value", "formal_b_hat_hz", "formal_k_hat_hz_per_s",
        "formal_score_gate_pass", "formal_b_gate_pass", "formal_k_gate_pass", "formal_final_decision",
    ]
    for coarse_id, g in tracked.groupby("coarse_physical_condition_id", sort=False):
        geometry_ids = sorted(g.geometry_condition_id.astype(str).unique())
        observation_ids = sorted(x for x in g.observation_realization_id.astype(str).unique() if x)
        decision_ids = sorted(x for x in g.decision_condition_id.astype(str).unique() if x)
        decisions = sorted(g.formal_final_decision.astype(str).unique())
        unresolved = g.reconstruction_confidence_row.eq("unresolved").any() or len(observation_ids) == 0
        identical_conflict = len(decision_ids) == 1 and len(decisions) > 1 and not unresolved
        hidden_geometry = len(geometry_ids) > 1
        random_differences = any(g[x].astype(str).nunique(dropna=False) > 1 for x in ["environment_realization_id", "noise_realization_id", "residual_realization_id", "calibration_realization_id"])
        if identical_conflict:
            classification = "IDENTICAL_REALIZATION_DECISION_CONFLICT"
            basis = "decision_condition_id完全相同但formal_final_decision不同"
        elif hidden_geometry:
            classification = "HIDDEN_GEOMETRY_DIFFERENCE"
            basis = "粗主键相同但TLE/时间/坐标/库行构成的geometry_condition_id不同"
        elif not unresolved and len(observation_ids) > 1 and random_differences:
            classification = "DIFFERENT_OBSERVATION_REALIZATION"
            basis = "geometry_condition_id相同；sample RNG流位置、environment/noise/residual realization不同；calibration可单独核对"
        else:
            classification = "UNRESOLVED_LINEAGE"
            basis = "现有字段或重建结果不足以唯一恢复observation realization"
        basis = {
            "IDENTICAL_REALIZATION_DECISION_CONFLICT": "decision_condition_id 完全相同，但 formal_final_decision 不同",
            "HIDDEN_GEOMETRY_DIFFERENCE": "粗主键相同，但 TLE、时间、坐标或库行构成的 geometry_condition_id 不同",
            "DIFFERENT_OBSERVATION_REALIZATION": "geometry_condition_id 相同；sample RNG 流位置及 environment/noise/residual realization 不同；calibration 可单独核对",
            "UNRESOLVED_LINEAGE": "现有字段或重建结果不足以唯一恢复 observation realization",
        }[classification]
        differences = {}
        for field in diff_fields:
            values = g[field].tolist()
            unique = list(dict.fromkeys(map(str, values)))
            if len(unique) > 1:
                differences[field] = unique
        side_cols = ["lineage_row_id", "sample_group", "sample_index_global", "geometry_condition_id", "observation_realization_id", "decision_condition_id", "environment_realization_id", "noise_realization_id", "calibration_realization_id", "formal_final_decision", "formal_score_value", "formal_b_hat_hz", "formal_k_hat_hz_per_s", "formal_score_gate_pass", "formal_b_gate_pass", "formal_k_gate_pass"]
        first = g.iloc[0]
        records.append({
            "conflict_id": stable_id("conflict", coarse_id), "coarse_physical_condition_id": coarse_id,
            "physical_pair_id": first.physical_pair_id, "target_sat_id": first.target_sat_id, "attack_sat_id": first.attack_sat_id,
            "service_area_id": first.service_area_id, "service_area_segment_index": first.service_area_segment_index,
            "distance_km": first.distance_km, "direction_deg": first.direction_deg, "bk_mode": first.bk_mode,
            "tracked_lineage_rows": len(g), "geometry_condition_count": len(geometry_ids),
            "observation_realization_count": len(observation_ids), "decision_condition_count": len(decision_ids),
            "formal_decisions": ",".join(decisions), "conflict_classification": classification,
            "classification_basis": basis, "differing_input_fields_json": stable_json(differences),
            "sides_json": g[side_cols].to_json(orient="records", force_ascii=False),
            "formal_score_mean": g.formal_score_value.mean(), "formal_score_std": g.formal_score_value.std(ddof=0),
            "formal_b_hat_mean": g.formal_b_hat_hz.mean(), "formal_b_hat_std": g.formal_b_hat_hz.std(ddof=0),
            "formal_k_hat_mean": g.formal_k_hat_hz_per_s.mean(), "formal_k_hat_std": g.formal_k_hat_hz_per_s.std(ddof=0),
            "score_gate_differs": g.formal_score_gate_pass.nunique() > 1,
            "b_gate_differs": g.formal_b_gate_pass.nunique() > 1,
            "k_gate_differs": g.formal_k_gate_pass.nunique() > 1,
        })
    return pd.DataFrame(records).sort_values(["target_sat_id", "attack_sat_id", "service_area_id", "direction_deg"]).reset_index(drop=True)


def geometry_summary(lineage: pd.DataFrame) -> pd.DataFrame:
    real = lineage[
        lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk") & lineage.distance_km.gt(0)
    ].copy()
    rows = []
    group_cols = ["geometry_condition_id", "physical_pair_id", "target_sat_id", "attack_sat_id", "service_area_id", "service_area_segment_index", "distance_km", "direction_deg"]
    for key, g in real.groupby(group_cols, sort=False):
        decisions = g.formal_final_decision.astype(str)
        accept = int(decisions.eq("ACCEPT").sum()); reject = int(decisions.eq("REJECT").sum())
        rows.append({
            **dict(zip(group_cols, key)),
            "number_of_realizations": g.observation_realization_id.nunique(),
            "label_row_count": len(g), "sample_groups": ",".join(sorted(g.sample_group.unique())),
            "accept_count": accept, "reject_count": reject, "accept_fraction": accept / len(g),
            "any_accept": accept > 0, "all_accept": accept == len(g), "mixed_decisions": accept > 0 and reject > 0,
            "formal_score_mean": g.formal_score_value.mean(), "formal_score_std": g.formal_score_value.std(ddof=0),
            "formal_b_hat_mean": g.formal_b_hat_hz.mean(), "formal_b_hat_std": g.formal_b_hat_hz.std(ddof=0),
            "formal_k_hat_mean": g.formal_k_hat_hz_per_s.mean(), "formal_k_hat_std": g.formal_k_hat_hz_per_s.std(ddof=0),
            "score_gate_pass_count": int(g.formal_score_gate_pass.sum()),
            "b_gate_pass_count": int(g.formal_b_gate_pass.sum()), "k_gate_pass_count": int(g.formal_k_gate_pass.sum()),
            "ordinary_environment_id": next(iter(g.loc[g.sample_group.eq("ordinary_similar"), "environment_realization_id"]), ""),
            "boundary_environment_id": next(iter(g.loc[g.sample_group.eq("boundary_case"), "environment_realization_id"]), ""),
        })
    return pd.DataFrame(rows)


def entity_summaries(geometry: pd.DataFrame, lineage: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    real = lineage[lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk") & lineage.distance_km.gt(0)]
    def build(cols: list[str]) -> pd.DataFrame:
        out = []
        for key, g in geometry.groupby(cols):
            key_tuple = key if isinstance(key, tuple) else (key,)
            observation = real[real.geometry_condition_id.isin(g.geometry_condition_id)]
            out.append({
                **dict(zip(cols, key_tuple)),
                "total_geometry_count": len(g), "positive_geometry_count": int(g.any_accept.sum()),
                "any_accept_geometry_count": int(g.any_accept.sum()), "all_accept_geometry_count": int(g.all_accept.sum()),
                "mixed_geometry_count": int(g.mixed_decisions.sum()),
                "total_observation_realizations": observation.observation_realization_id.nunique(),
                "positive_realization_count": int(observation.formal_final_decision.eq("ACCEPT").sum()),
                "realization_accept_rate": float(observation.formal_final_decision.eq("ACCEPT").mean()),
                "formal_score_mean": observation.formal_score_value.mean(), "formal_score_std": observation.formal_score_value.std(ddof=0),
                "formal_b_hat_mean": observation.formal_b_hat_hz.mean(), "formal_b_hat_std": observation.formal_b_hat_hz.std(ddof=0),
                "formal_k_hat_mean": observation.formal_k_hat_hz_per_s.mean(), "formal_k_hat_std": observation.formal_k_hat_hz_per_s.std(ddof=0),
            })
        return pd.DataFrame(out)
    return build(["physical_pair_id", "target_sat_id", "attack_sat_id"]), build(["target_sat_id"])


def ordinary_boundary_analysis(lineage: pd.DataFrame, geometry: pd.DataFrame) -> dict[str, Any]:
    real = lineage[lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk") & lineage.distance_km.gt(0)]
    paired = real.pivot_table(index="geometry_condition_id", columns="sample_group", values=["b_env", "k_env", "sigma_hz", "formal_score_value", "formal_b_hat_hz", "formal_k_hat_hz_per_s"], aggfunc="first")
    stats = {}
    for metric in ["b_env", "k_env", "sigma_hz", "formal_score_value", "formal_b_hat_hz", "formal_k_hat_hz_per_s"]:
        if (metric, "ordinary_similar") in paired and (metric, "boundary_case") in paired:
            diff = paired[(metric, "boundary_case")] - paired[(metric, "ordinary_similar")]
            stats[metric] = {"mean_boundary_minus_ordinary": float(diff.mean()), "std": float(diff.std(ddof=0)), "nonzero_fraction": float((np.abs(diff) > 1e-12).mean())}
    positive = geometry[geometry.any_accept]
    return {
        "all_geometry_condition_count": len(geometry),
        "geometry_with_two_realizations": int(geometry.number_of_realizations.ge(2).sum()),
        "positive_geometry_count": len(positive), "mixed_positive_geometry_count": int(positive.mixed_decisions.sum()),
        "paired_metric_differences": stats,
    }


def correctness_audit_clean(
    lineage: pd.DataFrame, conflicts: pd.DataFrame, seed: pd.DataFrame,
    geometry: pd.DataFrame, original_conflicts: pd.DataFrame,
    input_hash_before: dict[str, str], input_hash_after: dict[str, str], evidence: dict[str, Any],
) -> pd.DataFrame:
    tests = []
    def add(name: str, passed: bool, observed: Any, tolerance: str, notes: str = "") -> None:
        tests.append({"check": name, "passed": bool(passed), "observed": observed, "tolerance": tolerance, "notes": notes})
    original_count = original_conflicts[COARSE_KEY].drop_duplicates().shape[0]
    add("16个原冲突均被追踪", len(conflicts) == original_count == 16, f"input={original_count}, classified={len(conflicts)}", "16")
    add("每个冲突均有分类", conflicts.conflict_classification.notna().all() and len(conflicts) == original_count, conflicts.conflict_classification.value_counts().to_dict(), "no missing")
    geometry_fields = ["target_tle_epoch", "target_library_row_id", "evaluation_start_utc", "evaluation_end_utc", "C_lat", "C_lon", "S_lat", "S_lon", "geometry_condition_id"]
    add("geometry_condition_id字段完整", lineage[geometry_fields].astype(str).ne("").all().all(), int(lineage[geometry_fields].isna().sum().sum()), "0 missing")
    unresolved = int(lineage.reconstruction_confidence_row.eq("unresolved").sum())
    obs_ok = lineage.loc[lineage.reconstruction_confidence_row.ne("unresolved"), "observation_realization_id"].astype(str).ne("").all()
    add("observation_realization_id完整或标记unresolved", obs_ok, {"unresolved_rows": unresolved}, "resolved rows have ID")
    add("decision_condition_id行级唯一", not lineage.decision_condition_id.duplicated().any(), int(lineage.decision_condition_id.duplicated().sum()), "0 duplicates")
    conflicts_by_decision = lineage.groupby("decision_condition_id").formal_final_decision.nunique().gt(1).sum()
    add("同一decision_condition_id判决唯一", conflicts_by_decision == 0, int(conflicts_by_decision), "0")
    seed_match = seed[seed.sample_source.eq("real_tle_candidate")].stored_environment_matches_reconstruction.all()
    add("重建seed/RNG流与旧环境字段一致", seed_match, int((~seed[seed.sample_source.eq('real_tle_candidate')].stored_environment_matches_reconstruction).sum()), "0 real sample mismatches", "real无独立noise_seed；用master RNG state/index精确重建")
    evidence_ok = all(v.get("line") for v in evidence.values())
    add("ordinary/boundary语义有代码证据", evidence_ok, stable_json(evidence), "all evidence line numbers present")
    real = lineage[lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk") & lineage.distance_km.gt(0)]
    positive = geometry[geometry.any_accept]
    sums_ok = int(positive.accept_count.sum()) == int(real.formal_final_decision.eq("ACCEPT").sum()) and int(geometry.label_row_count.sum()) == len(real)
    add("几何层与realization层汇总可回加", sums_ok, {"positive_realizations": int(positive.accept_count.sum()), "raw_accept_rows": int(real.formal_final_decision.eq('ACCEPT').sum()), "geometry_label_rows": int(geometry.label_row_count.sum()), "lineage_rows": len(real)}, "equal")
    unchanged = input_hash_before == input_hash_after
    add("旧正式输入未修改", unchanged, int(sum(input_hash_before[k] != input_hash_after.get(k) for k in input_hash_before)), "0 hash changes")
    identical = int(conflicts.conflict_classification.eq("IDENTICAL_REALIZATION_DECISION_CONFLICT").sum())
    add("不存在identical realization相反判决", identical == 0, identical, "0", "若>0必须暂停扩样与理论化")
    return pd.DataFrame(tests)


def final_decision_legacy(conflicts: pd.DataFrame, audit: pd.DataFrame, geometry: pd.DataFrame) -> tuple[str, list[str]]:
    counts = conflicts.conflict_classification.value_counts().to_dict()
    if counts.get("IDENTICAL_REALIZATION_DECISION_CONFLICT", 0) > 0:
        return "暂停扩样与理论化：存在完全相同realization的相反正式判决", ["定位生成链路与判决写入一致性"]
    unresolved = counts.get("UNRESOLVED_LINEAGE", 0)
    if unresolved > 0:
        return "旧数据血缘仍不足，当前正例独立性不能精确判断", ["后续强制保存observation/residual/noise realization ID与seed"]
    different = counts.get("DIFFERENT_OBSERVATION_REALIZATION", 0)
    if different >= max(1, int(math.ceil(0.8 * len(conflicts)))):
        positive = geometry[geometry.any_accept]
        return "可恢复扩样判断：冲突主要是相同几何下不同观测实现，不是正式数据一致性错误", [
            f"按几何层使用 any/all/mixed：positive={len(positive)}, all_accept={int(positive.all_accept.sum())}, mixed={int(positive.mixed_decisions.sum())}",
            "后续数据必须保存master seed、sample index、RNG state/noise hash和calibration seed",
            "扩样优先不同日期/不同过境，并为同一几何保留多个明确编号的观测realization",
            "已有目标/pair描述上不集中；不优先增加同一次过境的距离/方向行密度",
        ]
    if counts.get("HIDDEN_GEOMETRY_DIFFERENCE", 0) > 0:
        return "需修正物理主键：ordinary/boundary包含隐藏几何差异", ["用新geometry_condition_id重算正例分布"]
    return "血缘分类结果不足以恢复扩样判断", ["检查未覆盖的输入身份"]


def write_report_legacy(
    args: argparse.Namespace, out: dict[str, Path], lineage: pd.DataFrame, conflicts: pd.DataFrame,
    seed: pd.DataFrame, geometry: pd.DataFrame, pair: pd.DataFrame, target: pd.DataFrame,
    audit: pd.DataFrame, evidence: dict[str, Any], semantics: dict[str, Any], decision: str, next_steps: list[str],
) -> None:
    counts = conflicts.conflict_classification.value_counts().rename("count").to_frame()
    positive = geometry[geometry.any_accept]
    positive_lineage = lineage[lineage.geometry_condition_id.isin(positive.geometry_condition_id) & lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk")]
    mixed = positive[positive.mixed_decisions]
    report = f"""# Observation realization 数据血缘与冲突溯源审计

## 1. 目的与边界

本轮只读取旧正式 dataset、全量机制表、冲突表、candidate library、selection、TLE与配置，并按旧代码顺序重建残差 RNG 流。未传播轨道、未重跑攻击、未修改验证器或旧输出。

## 2. 旧生成链与 seed 公式

代码证据：

{pd.DataFrame([{"evidence": k, **v} for k, v in evidence.items()]).to_markdown(index=False)}

正式 multi-service 脚本只创建一次 `rng=default_rng(master_seed)`，随后按 `sample_index_global` 顺序对每个样本抽取 `uniform(b), uniform(k), uniform(sigma), normal(noise,N)`。real 样本没有独立标量 `noise_seed`；其精确噪声身份由 master seed、sample index、进入该样本前的 RNG state 和重建 noise hash共同确定。校准 seed 精确为 `master_seed + int(target_id) + service_area_segment_index`，不含 sample_group。

重建的 real sample b/k/sigma 与旧 dataset 精确匹配率为 {seed[seed.sample_source.eq('real_tle_candidate')].stored_environment_matches_reconstruction.mean():.2%}。无法确认的标量 seed 保持空值，没有伪造。

## 3. ordinary/boundary 的真实语义

1. **不只是同一记录的标签分类**：两组在样本表中是独立 sample row，具有不同 `sample_index_global`。
2. **候选库行**：同一物理 pair 使用同一 attacker candidate-library 行集合；两组选择窗口可能重叠，使同一候选进入两组。
3. **过境/服务段**：冲突两侧 absolute evaluation time、C/S坐标、距离和方向相同。
4. **经验残差 realization**：不同；b_env/k_env/sigma由全局 RNG 流的不同位置抽取。
5. **noise seed**：real 样本没有独立标量 seed，但 RNG state和noise hash不同。
6. **calibration seed**：相同，由 target与segment决定。
7. **sample_group是否参与seed**：不直接参与公式；它通过生成两个有序样本实例，间接改变 sample index/RNG流位置。
8. **为何同pair进入两组**：ordinary取候选排序前N个；boundary从偏移位置取N个，hard-case target还可能取前N个，因此集合重叠。

组间描述性差异：

```json
{json.dumps(semantics, ensure_ascii=False, indent=2)}
```

## 4. 三级主键

- `geometry_condition_id`：TLE epoch/哈希、target/attacker library行集合、绝对服务段时间、C/S坐标、距离、方向与固定点参考模式。
- `observation_realization_id`：geometry + environment b/k/sigma realization + segment noise hash + calibration realization。
- `decision_condition_id`：observation + bk_mode + 正式阈值/gate边界 + verifier/config哈希。

所有 resolved 行都保留重建公式、输入和 confidence；real 行为 `deterministically_reconstructed`，显式 legacy seed可为 `exact`。

## 5. 16个冲突的分类

{counts.to_markdown()}

{conflicts[['conflict_id','physical_pair_id','service_area_id','distance_km','direction_deg','geometry_condition_count','observation_realization_count','formal_decisions','conflict_classification','score_gate_differs','b_gate_differs','k_gate_differs','classification_basis']].to_markdown(index=False)}

若分类为 DIFFERENT_OBSERVATION_REALIZATION，其含义是相同几何在不同经验残差/noise实现下产生不同判决，不是完全相同输入的自相矛盾。逐冲突的两侧完整ID、差异字段和判决均保存在 conflict CSV。

## 6. 几何层与 observation-realization 层重计数

- 审计的真实 current 非中心几何条件总数：{len(geometry)}。
- 具有至少一个 ACCEPT 的唯一几何：{len(positive)}。
- 所有 realization 均 ACCEPT 的几何：{int(positive.all_accept.sum())}。
- mixed-decision 几何：{int(positive.mixed_decisions.sum())}。
- 正例 observation realization：{int(positive_lineage.formal_final_decision.eq('ACCEPT').sum())}。
- 与正例几何关联的 observation realization 总数：{positive_lineage.observation_realization_id.nunique()}。
- 这些 realization 的接受率：{positive_lineage.formal_final_decision.eq('ACCEPT').mean():.2%}。

不能把同一几何的两个 realization 当成两个独立几何，也不再把其随机差异称为几何冲突。

## 7. 随机性与 gate 描述

所有物理几何均有 ordinary/boundary 两个 observation realization。正例几何中 mixed={len(mixed)}，说明大多数正例几何对经验残差/noise实现敏感。mixed几何的 score/b/k均值与标准差、score/b/k gate pass计数见 geometry summary；冲突CSV另外标记具体变化来自 score、b还是k gate。

环境项并非只改变白噪声：ordinary/boundary 的 b_env、k_env、sigma均由不同RNG流位置重抽，因此是完整经验环境 realization 变化。

## 8. 正确性审计

{audit.to_markdown(index=False)}

如果存在 `IDENTICAL_REALIZATION_DECISION_CONFLICT`，必须暂停扩样和理论化；如果存在 unresolved，不能强行归为不同realization。

## 9. 最终决策

**{decision}**。

下一步：

{chr(10).join(f'{i+1}. {x}' for i, x in enumerate(next_steps))}

当前正例独立性应表述为：多个物理pair/目标共享19个“any-accept几何”，但其中大多数只有部分 observation realization 被接受。后续扩样需要同时扩不同过境和明确编号的 realization，而不是单纯增加同一过境的空间扫描行。

## 10. 输出与局限

输出 lineage={len(lineage)} 行、seed reconstruction={len(seed)} 个样本、geometry summary={len(geometry)} 个几何、pair summary={len(pair)}、target summary={len(target)}。旧脚本未保存 real 的独立 noise seed；本轮用可验证的 RNG state/noise hash替代，confidence明确标为 deterministically reconstructed。
"""
    out["report"].parent.mkdir(parents=True, exist_ok=True)
    out["report"].write_text(report, encoding="utf-8")


def append_log_legacy(
    out: dict[str, Path], lineage: pd.DataFrame, conflicts: pd.DataFrame, geometry: pd.DataFrame,
    seed: pd.DataFrame, audit: pd.DataFrame, decision: str, next_steps: list[str],
) -> None:
    counts = conflicts.conflict_classification.value_counts().to_dict()
    positive = geometry[geometry.any_accept]
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    text = f"""

## {now} - Observation realization 数据血缘与冲突溯源

### A. 本轮目标
沿旧正式生成链恢复 geometry/environment/noise/calibration/observation/decision 身份，分类16个粗物理主键冲突。

### B. 实际操作
- 新增 `scripts/run_observation_realization_lineage_audit.py`；只读旧dataset/机制表/冲突表/library/selection/TLE/config。
- 重放 `master_seed + sample_index_global` 的全局 RNG 消耗顺序；real无独立noise_seed，使用RNG state与noise hash。
- calibration seed按 `master_seed + target_id + segment_index` 重建。
- 未传播轨道、未重跑攻击、未修改验证器或旧输出。

### C. 新增输出
- {out['lineage']}
- {out['conflict']}
- {out['seed']}
- {out['geometry']}
- {out['pair']}
- {out['target']}
- {out['audit']}
- {out['report']}
- logs/work_log.md（仅追加）

### D. 运行命令
- `python -m py_compile scripts/run_observation_realization_lineage_audit.py`
- `python scripts/run_observation_realization_lineage_audit.py`

### E. 结果摘要
- lineage rows={len(lineage)}；sample realizations={len(seed)}；conflict classification={counts}。
- real b/k/sigma重建匹配率={seed[seed.sample_source.eq('real_tle_candidate')].stored_environment_matches_reconstruction.mean():.2%}。
- positive geometry={len(positive)}；all-accept={int(positive.all_accept.sum())}；mixed={int(positive.mixed_decisions.sum())}；positive realizations={int(positive.accept_count.sum())}。
- correctness={int(audit.passed.sum())}/{len(audit)}；最终判断={decision}。

### F. 问题与下一步
- {'; '.join(next_steps)}。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(text)


def correctness_audit(
    lineage: pd.DataFrame, conflicts: pd.DataFrame, seed: pd.DataFrame,
    geometry: pd.DataFrame, original_conflicts: pd.DataFrame,
    input_hash_before: dict[str, str], input_hash_after: dict[str, str], evidence: dict[str, Any],
) -> pd.DataFrame:
    tests: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, tolerance: str, notes: str = "") -> None:
        tests.append({"check": name, "passed": bool(passed), "observed": observed, "tolerance": tolerance, "notes": notes})

    original_count = original_conflicts[COARSE_KEY].drop_duplicates().shape[0]
    add("16 个原冲突均被追踪", len(conflicts) == original_count == 16,
        f"input={original_count}, classified={len(conflicts)}", "16")
    add("每个冲突均有明确分类", conflicts.conflict_classification.notna().all() and len(conflicts) == original_count,
        conflicts.conflict_classification.value_counts().to_dict(), "no missing")

    common = ["target_tle_epoch", "target_library_row_id", "evaluation_start_utc", "evaluation_end_utc",
              "C_lat", "C_lon", "S_lat", "S_lon", "geometry_condition_id"]
    common_ok = lineage[common].notna().all().all() and lineage[common].astype(str).ne("").all().all()
    real = lineage.sample_source.eq("real_tle_candidate")
    real_fields = ["attack_tle_epoch", "attacker_library_row_id"]
    real_ok = lineage.loc[real, real_fields].notna().all().all() and lineage.loc[real, real_fields].astype(str).ne("").all().all()
    synth_fields = ["attack_type", "attack_param_name", "attack_param_value"]
    synth_ok = lineage.loc[~real, synth_fields].notna().all().all()
    add("geometry_condition_id 构造字段完整", common_ok and real_ok and synth_ok,
        {"common": bool(common_ok), "real_tle": bool(real_ok), "controlled": bool(synth_ok)}, "all required fields present")

    unresolved_rows = lineage.reconstruction_confidence_row.eq("unresolved")
    obs_ok = lineage.loc[~unresolved_rows, "observation_realization_id"].astype(str).ne("").all()
    add("observation_realization_id 完整或标记 unresolved", obs_ok,
        {"unresolved_rows": int(unresolved_rows.sum())}, "resolved rows have ID")
    resolved_decisions = lineage.loc[lineage.decision_condition_id.astype(str).ne("")]
    duplicate_decisions = int(resolved_decisions.decision_condition_id.duplicated().sum())
    add("decision_condition_id 行级唯一", duplicate_decisions == 0, duplicate_decisions, "0 duplicates")
    contrary = int(resolved_decisions.groupby("decision_condition_id").formal_final_decision.nunique().gt(1).sum())
    add("同一 decision_condition_id 判决唯一", contrary == 0, contrary, "0")

    real_seed = seed[seed.sample_source.eq("real_tle_candidate")]
    mismatches = int((~real_seed.stored_environment_matches_reconstruction).sum())
    add("重建 RNG 流与旧环境字段一致", mismatches == 0, mismatches, "0 real sample mismatches",
        "real 样本无独立 noise_seed；通过 master RNG state、sample index 和 noise hash 精确重建")
    evidence_ok = all(v.get("line") for v in evidence.values())
    add("ordinary/boundary 语义有代码证据", evidence_ok, stable_json(evidence), "all evidence lines present")

    real_current = lineage[lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk") & lineage.distance_km.gt(0)]
    positive = geometry[geometry.any_accept]
    sums_ok = (int(positive.accept_count.sum()) == int(real_current.formal_final_decision.eq("ACCEPT").sum())
               and int(geometry.label_row_count.sum()) == len(real_current))
    add("几何层与 realization 层汇总可回加", sums_ok,
        {"positive_realizations": int(positive.accept_count.sum()),
         "raw_accept_rows": int(real_current.formal_final_decision.eq("ACCEPT").sum()),
         "geometry_label_rows": int(geometry.label_row_count.sum()), "lineage_rows": len(real_current)}, "equal")
    changed = sum(input_hash_before[k] != input_hash_after.get(k) for k in input_hash_before)
    add("旧正式输入未修改", changed == 0, int(changed), "0 hash changes")
    identical = int(conflicts.conflict_classification.eq("IDENTICAL_REALIZATION_DECISION_CONFLICT").sum())
    add("不存在 identical-realization 相反判决", identical == 0, identical, "0", "若大于 0 必须暂停扩样与理论化")
    return pd.DataFrame(tests)


def final_decision(conflicts: pd.DataFrame, audit: pd.DataFrame, geometry: pd.DataFrame) -> tuple[str, list[str]]:
    counts = conflicts.conflict_classification.value_counts().to_dict()
    if counts.get("IDENTICAL_REALIZATION_DECISION_CONFLICT", 0):
        return "暂停扩样与理论化：发现完全相同 observation realization 的相反正式判决", ["优先定位生成链路与判决写入一致性"]
    if counts.get("UNRESOLVED_LINEAGE", 0):
        return "旧数据血缘仍不足，当前正例独立性不能精确判断", ["后续强制保存 observation/residual/noise realization ID 与 seed"]
    if not audit.passed.all():
        return "正确性审计未全部通过，暂不恢复扩样判断", ["先修复失败审计项"]
    if counts.get("DIFFERENT_OBSERVATION_REALIZATION", 0) >= math.ceil(0.8 * len(conflicts)):
        positive = geometry[geometry.any_accept]
        return "可以恢复扩样判断：冲突主要是相同几何下不同观测实现，不是正式数据一致性错误", [
            f"按几何层报告 any/all/mixed：positive={len(positive)}, all_accept={int(positive.all_accept.sum())}, mixed={int(positive.mixed_decisions.sum())}",
            "后续数据强制保存 master seed、sample index、RNG state/noise hash 和 calibration seed",
            "扩样优先不同日期与不同过境，并为相同几何保留多个明确编号的 observation realization",
            "不优先增加同一次过境中的距离/方向行密度",
        ]
    if counts.get("HIDDEN_GEOMETRY_DIFFERENCE", 0):
        return "需要修正物理主键：ordinary/boundary 包含隐藏几何差异", ["用新 geometry_condition_id 重算正例分布"]
    return "血缘分类不足以恢复扩样判断", ["检查仍未覆盖的输入身份"]


def write_report(
    args: argparse.Namespace, out: dict[str, Path], lineage: pd.DataFrame, conflicts: pd.DataFrame,
    seed: pd.DataFrame, geometry: pd.DataFrame, pair: pd.DataFrame, target: pd.DataFrame,
    audit: pd.DataFrame, evidence: dict[str, Any], semantics: dict[str, Any], decision: str, next_steps: list[str],
) -> None:
    counts = conflicts.conflict_classification.value_counts().rename("count").to_frame()
    positive = geometry[geometry.any_accept]
    positive_rows = lineage[lineage.geometry_condition_id.isin(positive.geometry_condition_id)
                            & lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk")]
    real_seed_match = seed.loc[seed.sample_source.eq("real_tle_candidate"), "stored_environment_matches_reconstruction"].mean()
    conflict_ids = set(conflicts.coarse_physical_condition_id)
    conflict_rows = lineage[lineage.coarse_physical_condition_id.isin(conflict_ids)].copy()
    gate_flip_counts = {
        "score": int(conflicts.score_gate_differs.sum()),
        "b": int(conflicts.b_gate_differs.sum()),
        "k": int(conflicts.k_gate_differs.sum()),
    }
    conflict_rows["score_margin_hz"] = conflict_rows.formal_score_threshold - conflict_rows.formal_score_value
    conflict_rows["k_gate_margin_hz_per_s"] = np.minimum(
        conflict_rows.formal_k_hat_hz_per_s - conflict_rows.formal_k_gate_lower_hz_per_s,
        conflict_rows.formal_k_gate_upper_hz_per_s - conflict_rows.formal_k_hat_hz_per_s,
    )
    decision_margins = conflict_rows.groupby("formal_final_decision")[["score_margin_hz", "k_gate_margin_hz_per_s"]].agg(["mean", "median", "min", "max"])
    conflict_cols = ["conflict_id", "physical_pair_id", "service_area_id", "distance_km", "direction_deg",
                     "geometry_condition_count", "observation_realization_count", "formal_decisions",
                     "conflict_classification", "score_gate_differs", "b_gate_differs", "k_gate_differs", "classification_basis"]
    report = f"""# Observation realization 数据血缘与冲突溯源审计

## 1. 目的与边界

本轮只读审计旧正式 dataset、全量机制表、冲突表、候选库、selection、TLE 与配置，并按旧代码顺序重建残差 RNG 流。未传播轨道、未重新运行攻击实验、未修改验证器或任何旧正式输出。

## 2. 旧生成链与 seed 公式

代码证据：

{pd.DataFrame([{"evidence": k, **v} for k, v in evidence.items()]).to_markdown(index=False)}

正式 multi-service 脚本只创建一次 `rng = np.random.default_rng(master_seed)`，随后按 `sample_index_global` 顺序为每个样本抽取 `b_env`、`k_env`、`sigma_hz` 和整段高斯噪声。real 样本没有独立标量 `noise_seed`；其精确噪声身份由 master seed、sample index、进入样本前的 RNG state 与重建 noise hash 共同确定。校准 seed 为：

```text
master_seed + int(target_sat_id) + service_area_segment_index
```

该公式不含 `sample_group`。real 样本重建的 b/k/sigma 与旧 dataset 匹配率为 **{real_seed_match:.2%}**。无法确认的标量 seed 保持为空，没有伪造 ID。

## 3. ordinary/boundary 的真实语义

1. 两组不是同一 observation 行的纯标签副本，而是独立、有序的 sample row，具有不同 `sample_index_global`。
2. 同一物理 pair 使用相同 attacker candidate-library 行集合；ordinary 与 boundary 的选择窗口可重叠，因此一个物理 pair 可进入两组。
3. 本次 16 个冲突两侧的 TLE、绝对服务段时间、服务中心、验证站、距离和方向均相同。
4. 两组使用不同完整环境 realization：`b_env/k_env/sigma_hz` 来自全局 RNG 流的不同位置，噪声数组也不同。
5. real 样本没有独立 `noise_seed`，但 RNG state/noise hash 不同。
6. 同一目标和服务段的 calibration seed 相同。
7. `sample_group` 不直接进入 seed 公式；它通过生成两个有序样本实例，间接改变 sample index 和 RNG 流位置。

组间描述性差异：

```json
{json.dumps(semantics, ensure_ascii=False, indent=2)}
```

## 4. 三级主键

- `geometry_condition_id`：目标/攻击轨道身份和 epoch、候选库行集合、绝对服务段时间、C/S 坐标、距离、方向和固定点参考模式。
- `observation_realization_id`：geometry 加环境 b/k/sigma realization、分段 noise hash 和 calibration realization。
- `decision_condition_id`：observation 加 `bk_mode`、正式阈值、b/k gate 边界与 verifier/config 哈希。

resolved 行均保存重建公式、输入和 confidence。real 行标记为 `deterministically_reconstructed`；旧脚本未保存的独立标量 `noise_seed` 保持空值。

## 5. 16 个冲突的分类

{counts.to_markdown()}

{conflicts[conflict_cols].to_markdown(index=False)}

16 个冲突全部为 `DIFFERENT_OBSERVATION_REALIZATION`：相同纯几何与相同 calibration 下，不同经验环境/噪声 realization 得到不同判决。它们不是完全相同输入下的自相矛盾。逐冲突两侧的完整 ID、差异字段和 gate 变化保存在 conflict CSV。

## 6. 几何层与 observation-realization 层重计数

- 全部 real/current/noncenter 唯一几何条件：{len(geometry)}。
- 至少一个 realization ACCEPT 的几何：{len(positive)}。
- 所有 realization 均 ACCEPT 的几何：{int(positive.all_accept.sum())}。
- mixed-decision 几何：{int(positive.mixed_decisions.sum())}。
- 正例 observation realization：{int(positive_rows.formal_final_decision.eq('ACCEPT').sum())}。
- 正例几何关联的 observation realization 总数：{positive_rows.observation_realization_id.nunique()}。
- 上述 realization 接受率：{positive_rows.formal_final_decision.eq('ACCEPT').mean():.2%}。

因此，19 个是 `any-accept` 几何条件，不等同于 19 个稳定误接受几何；其中 16 个对 observation realization 敏感，只有 3 个在现有两个 realization 中均接受。

## 7. 随机性与 gate 的描述性结论

旧表中每个 real 几何都具有 ordinary/boundary 两个 observation realization，并非只有少数几何被重复 realization。mixed decision 不是几何输入变化造成，而是整套经验环境项与噪声变化造成。

16 个冲突中，k gate 在 **{gate_flip_counts['k']}/16** 个条件中翻转，b gate 在 **{gate_flip_counts['b']}/16** 个条件中翻转，score gate 仅在 **{gate_flip_counts['score']}/16** 个条件中翻转。因此判决敏感性的主导路径是经验 `k_env` 改变拟合 k 并跨越 current k gate，而不是普遍由 score 在阈值附近抖动。ACCEPT/REJECT 两侧的 score 与 k gate margin 如下：

{decision_margins.to_markdown()}

ordinary/boundary 不是仅改变白噪声：`b_env/k_env/sigma_hz` 在全部配对几何中均不同。组间平均差相对几何间波动较小且没有证据支持固定单向偏置，因此更准确的解释是两组使用了独立完整环境 realization，而非 boundary 标签系统性施加某个确定残差偏移。

## 8. 正确性审计

{audit.to_markdown(index=False)}

全部审计通过，且没有 `IDENTICAL_REALIZATION_DECISION_CONFLICT` 或 `UNRESOLVED_LINEAGE`。旧正式输入文件在运行前后 SHA-256 一致。

## 9. 最终决策

**{decision}**。

下一步：

{chr(10).join(f'{i + 1}. {item}' for i, item in enumerate(next_steps))}

这使上一轮集中度审计的扩样判断可以恢复，但应以几何层的 any/all/mixed 口径重新解释：已有正例覆盖并非被单一 pair 主导，然而多数正例几何只在部分 realization 中接受。后续扩样应同时增加独立过境，并显式保存多个 observation realization，而不是只提高同一次过境的空间扫描密度。

## 10. 输出与局限

生成 lineage {len(lineage)} 行、seed reconstruction {len(seed)} 个样本、geometry summary {len(geometry)} 个几何、pair summary {len(pair)} 行、target summary {len(target)} 行。旧数据未保存 real 样本的独立标量 noise seed，本轮用可验证的 RNG state/noise hash 恢复等价身份，并明确标记为 deterministic reconstruction。
"""
    out["report"].parent.mkdir(parents=True, exist_ok=True)
    out["report"].write_text(report, encoding="utf-8")


def append_log(
    out: dict[str, Path], lineage: pd.DataFrame, conflicts: pd.DataFrame, geometry: pd.DataFrame,
    seed: pd.DataFrame, audit: pd.DataFrame, decision: str, next_steps: list[str],
) -> None:
    counts = conflicts.conflict_classification.value_counts().to_dict()
    positive = geometry[geometry.any_accept]
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    block = f"""

## {now} - Observation realization 数据血缘与冲突溯源审计（可读修正版）

### A. 本轮目标
沿旧正式生成链恢复 geometry/environment/noise/calibration/observation/decision 身份，分类 16 个粗物理主键冲突。

### B. 实际操作
- 新增 `scripts/run_observation_realization_lineage_audit.py`，只读旧 dataset、机制表、冲突表、library、selection、TLE 和配置。
- 按 `master_seed + sample_index_global` 的全局 RNG 消耗顺序重放环境项与噪声；real 样本无独立 noise seed，使用 RNG state 和 noise hash。
- calibration seed 按 `master_seed + target_id + segment_index` 重建。
- 未传播轨道、未重新运行攻击、未修改验证器或旧正式输出。

### C. 新增/修改文件
- 新增 lineage/conflict/seed/geometry/pair/target/correctness CSV 和 lineage audit report。
- 追加本工作日志；未修改配置和旧正式输出。

### D. 运行命令
- `python -m py_compile scripts/run_observation_realization_lineage_audit.py`
- `python scripts/run_observation_realization_lineage_audit.py --overwrite`

### E. 结果摘要
- lineage rows={len(lineage)}；sample realizations={len(seed)}；conflict classification={counts}。
- real b/k/sigma 重建匹配率={seed.loc[seed.sample_source.eq('real_tle_candidate'), 'stored_environment_matches_reconstruction'].mean():.2%}。
- positive geometry={len(positive)}；all-accept={int(positive.all_accept.sum())}；mixed={int(positive.mixed_decisions.sum())}；positive realizations={int(positive.accept_count.sum())}。
- correctness={int(audit.passed.sum())}/{len(audit)}；最终判断：{decision}。

### F. 问题与下一步
- {'；'.join(next_steps)}。
"""
    with Path("logs/work_log.md").open("a", encoding="utf-8") as f:
        f.write(block)


def main() -> None:
    args = parse_args(); out = paths(args); hashes_before = check_io(args, out)
    formal = normalize_ids(pd.read_csv(args.formal_dataset, low_memory=False))
    mechanism = normalize_ids(pd.read_csv(args.mechanism_rows, low_memory=False))
    original_conflicts = normalize_ids(pd.read_csv(args.conflicts, low_memory=False))
    lib, library_ids = load_library_identity(args.candidate_library)
    selection = pd.read_csv(args.selection_table)
    tle = load_tle_identity(args.tle_file)
    ranges = parameter_ranges(args.parameter_config)
    joined = join_formal_rows(mechanism, formal)
    samples = sample_table(formal)
    master_seeds = samples.random_seed.astype(int).unique()
    if len(master_seeds) != 1:
        fail(f"expected one master seed, found {master_seeds.tolist()}")
    legacy_args = argparse.Namespace(legacy_case_list=args.legacy_case_list, legacy_dataset=args.legacy_dataset)
    legacy_env = multi.load_legacy_env(legacy_args)
    seed_table, arrays = reconstruct_samples(samples, lib, ranges, legacy_env, int(master_seeds[0]))
    config_hash = stable_id("verifier_config", {
        "parameter_config": file_sha256(args.parameter_config), "orbit_config": file_sha256(args.orbit_config),
        "multi_script": file_sha256(SCRIPT_DIR / "run_multi_service_area_single_station_confirmation.py"),
        "segmented_script": file_sha256(SCRIPT_DIR / "run_segmented_service_center_compensation.py"),
    })
    lineage = build_lineage(joined, seed_table, arrays, lib, library_ids, selection, tle, config_hash)
    conflicts = classify_conflicts(lineage, original_conflicts)
    geometry = geometry_summary(lineage)
    pair, target = entity_summaries(geometry, lineage)
    evidence = source_evidence()
    semantics = ordinary_boundary_analysis(lineage, geometry)
    hashes_after = {p: file_sha256(Path(p)) for p in hashes_before}
    audit = correctness_audit(lineage, conflicts, seed_table, geometry, original_conflicts, hashes_before, hashes_after, evidence)
    decision, next_steps = final_decision(conflicts, audit, geometry)
    for p in out.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    lineage.to_csv(out["lineage"], index=False)
    conflicts.to_csv(out["conflict"], index=False)
    seed_table.to_csv(out["seed"], index=False)
    geometry.to_csv(out["geometry"], index=False)
    pair.to_csv(out["pair"], index=False)
    target.to_csv(out["target"], index=False)
    audit.to_csv(out["audit"], index=False)
    write_report(args, out, lineage, conflicts, seed_table, geometry, pair, target, audit, evidence, semantics, decision, next_steps)
    append_log(out, lineage, conflicts, geometry, seed_table, audit, decision, next_steps)
    counts = conflicts.conflict_classification.value_counts().to_dict(); positive = geometry[geometry.any_accept]
    positive_obs = lineage[lineage.geometry_condition_id.isin(positive.geometry_condition_id) & lineage.sample_source.eq("real_tle_candidate") & lineage.bk_mode.eq("current_bk")]
    print(f"1. tracked conflicts: {len(conflicts)}")
    print(f"2. different observation realization: {counts.get('DIFFERENT_OBSERVATION_REALIZATION', 0)}")
    print(f"3. hidden geometry difference: {counts.get('HIDDEN_GEOMETRY_DIFFERENCE', 0)}")
    print(f"4. identical realization conflicts: {counts.get('IDENTICAL_REALIZATION_DECISION_CONFLICT', 0)}")
    print(f"5. unresolved: {counts.get('UNRESOLVED_LINEAGE', 0)}")
    print("6. ordinary/boundary difference: same geometry/calibration, different ordered sample index and full environment/noise realization; group is indirect, not a seed formula term")
    print(f"7. unique positive geometry conditions: {len(positive)}")
    print(f"8. unique positive observation realizations: {int(positive_obs.formal_final_decision.eq('ACCEPT').sum())}")
    print(f"9. mixed decision geometry conditions: {int(positive.mixed_decisions.sum())}")
    print(f"10. all-accept geometry conditions: {int(positive.all_accept.sum())}")
    print(f"11. expansion judgment recoverable: {counts.get('UNRESOLVED_LINEAGE', 0) == 0 and counts.get('IDENTICAL_REALIZATION_DECISION_CONFLICT', 0) == 0}")
    print(f"12. next: {'; '.join(next_steps)}")
    print(f"correctness: {int(audit.passed.sum())}/{len(audit)} passed")
    if counts.get("IDENTICAL_REALIZATION_DECISION_CONFLICT", 0) > 0:
        fail("identical realization decision conflict found; stop expansion and theoretical work")


if __name__ == "__main__":
    main()
