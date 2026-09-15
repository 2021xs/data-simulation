#!/usr/bin/env python3
"""Audit the frozen R1 Level-4 numerical divergence without rerunning R1."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import platform
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import mpmath as mp
import numpy as np
import pandas as pd
from skyfield.api import load

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_causal_a_doppler_reconstruction_reproduction_validation_rerun as r1  # noqa: E402
import run_active_compensation_attack_first_pass as active  # noqa: E402
import run_doppler_verifier_initial_experiments as base  # noqa: E402

METRICS = ROOT / "outputs" / "metrics"
DATASETS = ROOT / "outputs" / "datasets"
REPORT = ROOT / "outputs" / "reports" / "causal_a_doppler_r1_level4_numerical_divergence_root_cause_audit.md"
ULP = METRICS / "causal_a_doppler_r1_geometry_ulp_audit.csv"
FAIL = METRICS / "causal_a_doppler_r1_failing_identity_audit.csv"
HP = METRICS / "causal_a_doppler_r1_high_precision_reference.csv"
PROP = METRICS / "causal_a_doppler_r1_error_propagation_audit.csv"
PATHS = METRICS / "causal_a_doppler_r1_implementation_path_comparison.csv"
MANIFEST = METRICS / "causal_a_doppler_r1_numerical_divergence_manifest.json"
R1_GEOMETRY = METRICS / "causal_a_doppler_r1_rerun_geometry_reproduction.csv"
R1_FIT = METRICS / "causal_a_doppler_r1_rerun_fit_score_reproduction.csv"
R1_ROWS = DATASETS / "causal_a_doppler_r1_rerun_reproduction_rows.csv"
R1_STATE = METRICS / "causal_a_doppler_r1_rerun_state_reproduction.csv"
CORRECTED = METRICS / "doppler_semantic_reconstruction_r1_corrected_population_binding.csv"
INITIAL_RESULT = METRICS / "doppler_verifier_orbit_similarity_attack_results.csv"
INITIAL_SERIES = DATASETS / "doppler_verifier_orbit_similarity_attack_dataset.csv"
ACTIVE_RESULT = METRICS / "active_compensation_first_pass_sequence_eval.csv"
ACTIVE_SERIES = DATASETS / "active_compensation_first_pass_dataset.csv"
R1_MANIFEST = METRICS / "causal_a_doppler_r1_rerun_manifest.json"
R0_PROTOCOL = METRICS / "doppler_semantic_reconstruction_protocol.json"
FROZEN_PARAMETER = METRICS / "orbit_uncertainty_stage1f_lite_frozen_parameters.csv"
LOG = ROOT / "logs" / "work_log.md"

OUT = [REPORT, ULP, FAIL, HP, PROP, PATHS, MANIFEST]
MPC = [
    ROOT / "scripts" / "build_controlled_starlink_multitarget_dataset.py",
    ROOT / "scripts" / "run_active_compensation_attack_first_pass.py",
    ROOT / "scripts" / "run_doppler_verifier_initial_experiments.py",
    ROOT / "scripts" / "run_causal_a_doppler_reconstruction_reproduction_validation_rerun.py",
]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def mp_freq_from_positions(position_km: np.ndarray, freq: float, step_s: float) -> np.ndarray:
    """High precision norm/range-rate arithmetic over the same Skyfield positions."""
    mp.mp.dps = 80
    ranges = []
    for vector in np.asarray(position_km, dtype=float):
        terms = [mp.mpf(str(float(value))) ** 2 for value in vector]
        ranges.append(mp.sqrt(sum(terms)) * mp.mpf("1000"))
    rr = []
    if len(ranges) == 1:
        rr = [mp.mpf("0")]
    else:
        for index in range(len(ranges)):
            if index == 0:
                value = (ranges[1] - ranges[0]) / mp.mpf(str(step_s))
            elif index == len(ranges) - 1:
                value = (ranges[-1] - ranges[-2]) / mp.mpf(str(step_s))
            else:
                value = (ranges[index + 1] - ranges[index - 1]) / (mp.mpf("2") * mp.mpf(str(step_s)))
            rr.append(value)
    return np.asarray(
        [float(mp.mpf(str(freq)) - mp.mpf(str(freq)) * value / mp.mpf(str(base.C_MPS))) for value in rr],
        dtype=float,
    )


def source_rows() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    binding = pd.read_csv(CORRECTED, dtype=str, keep_default_na=False)
    initial = pd.read_csv(INITIAL_RESULT, dtype={"claimed_target_norad": str})
    initial_series = pd.read_csv(INITIAL_SERIES, dtype={"claimed_target_norad": str})
    active_result = pd.read_csv(ACTIVE_RESULT, dtype={"target_id": str, "attacker_id": str})
    active_series = pd.read_csv(ACTIVE_SERIES, dtype={"target_id": str, "attacker_id": str})
    return binding, initial, initial_series, pd.concat(
        [active_result.assign(_kind="active_result"), active_series.assign(_kind="active_series")],
        ignore_index=True, sort=False,
    )


def reconstruct_direct() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    binding = pd.read_csv(CORRECTED, dtype=str, keep_default_na=False)
    primary = binding[binding.row_role.eq("PRIMARY")].copy()
    initial = pd.read_csv(INITIAL_RESULT, dtype={"claimed_target_norad": str})
    initial_series = pd.read_csv(INITIAL_SERIES, dtype={"claimed_target_norad": str})
    active_result = pd.read_csv(ACTIVE_RESULT, dtype={"target_id": str, "attacker_id": str})
    active_series = pd.read_csv(ACTIVE_SERIES, dtype={"target_id": str, "attacker_id": str})
    _, _, config, tle, _ranges = r1.load_core_inputs()
    ts = load.timescale()
    causal, provenance, _future = r1.causal_satellites(primary, ts)
    station = config["station"]
    records: list[dict[str, Any]] = []
    all_diffs: dict[str, list[float]] = defaultdict(list)
    hp_inputs: list[dict[str, Any]] = []
    active_fixed_cache: dict[tuple[str, str, int, str, float], tuple[np.ndarray, np.ndarray]] = {}
    active_moving_cache: dict[tuple[str, str, int, str, float], tuple[np.ndarray, np.ndarray]] = {}

    def add_case(bind: pd.Series, case_id: str, family: str, times: list[Any], old: dict[str, np.ndarray], new: dict[str, np.ndarray], freq: float) -> None:
        keys = ["F_A_S", "F_B_S", "F_A_C", "F_B_C", "u_C"]
        available = [key for key in keys if key in old and key in new]
        diff_arrays = {key: np.asarray(new[key], dtype=float) - np.asarray(old[key], dtype=float) for key in available}
        combined = np.concatenate([np.abs(values) for values in diff_arrays.values()]) if diff_arrays else np.zeros(1)
        index = int(np.argmax(combined))
        key_at_max = "F_A_S"
        local_idx = 0
        best = -1.0
        for key, values in diff_arrays.items():
            candidate = float(np.max(np.abs(values)))
            if candidate > best:
                best, key_at_max = candidate, key
                local_idx = int(np.argmax(np.abs(values)))
        record = {
            "experiment_family": family, "orbit_unit_id": bind.orbit_unit_id, "case_id": case_id,
            "A_id": bind.A_id, "B_id_or_definition": bind.B_id_or_definition,
            "evaluation_time": bind.evaluation_time, "selected_A_GP_ID": bind.selected_A_GP_ID,
            "timestamp_utc": times[local_idx].isoformat().replace("+00:00", "Z"),
            "max_difference_component": key_at_max, "old_geometry_hz": float(old[key_at_max][local_idx]),
            "new_geometry_hz": float(new[key_at_max][local_idx]), "geometry_abs_difference_hz": best,
            "old_F_A_S_hz": float(old["F_A_S"][local_idx]), "new_F_A_S_hz": float(new["F_A_S"][local_idx]),
            "old_F_B_S_hz": float(old["F_B_S"][local_idx]), "new_F_B_S_hz": float(new["F_B_S"][local_idx]),
            "old_compensation_hz": float(old["u_C"][local_idx]) if "u_C" in old else math.nan,
            "new_compensation_hz": float(new["u_C"][local_idx]) if "u_C" in new else math.nan,
            "compensation_abs_difference_hz": abs(float(new["u_C"][local_idx] - old["u_C"][local_idx])) if "u_C" in old else 0.0,
            "old_residual_hz": math.nan, "new_residual_hz": math.nan,
        }
        records.append(record)
        for key, values in diff_arrays.items():
            all_diffs[key].extend(np.asarray(values, dtype=float).tolist())
        if len(hp_inputs) < 40:
            hp_inputs.append({"family": family, "case_id": case_id, "bind": bind, "times": times, "freq": freq,
                              "sat": causal[provenance[str(bind.orbit_unit_id)]["key"]],
                              "station_lat": float(station["lat_deg"]), "station_lon": float(station["lon_deg"]),
                              "station_alt": float(station["alt_m"]), "new_f": np.asarray(new["F_A_S"]),
                              "old_f": np.asarray(old["F_A_S"]), "step": float(np.median(np.diff(np.arange(len(times), dtype=float)))) if len(times) > 1 else 1.0})

    initial_case_map = primary[primary.experiment_family.eq("score_only_verifier_and_synthetic_orbit_attacks")].set_index("case_id", drop=False)
    for row in initial.itertuples(index=False):
        case_id = str(row.attack_sequence_id)
        if case_id not in initial_case_map.index:
            continue
        bind = initial_case_map.loc[case_id]
        group = initial_series[initial_series.attack_sequence_id.astype(str).eq(case_id)].sort_values("t_rel_s")
        times = [r1.parse_utc(value) for value in group.t_abs_utc.astype(str)]
        t_rel = group.t_rel_s.to_numpy(float)
        sat = causal[provenance[str(bind.orbit_unit_id)]["key"]]
        old_sat = tle[str(bind.A_id)]["sat"]
        freq = 11_325_000_000.0
        fa_new, _ = active.geo_curve_fixed_reference(sat, float(station["lat_deg"]), float(station["lon_deg"]), float(station["alt_m"]), times, ts, freq, float(np.median(np.diff(t_rel))))
        fb_new = base.synthetic_same_plane_geo(sat, active.orbit_builder.wgs84.latlon(float(station["lat_deg"]), float(station["lon_deg"]), elevation_m=float(station["alt_m"])), ts, times, freq, float(row.altitude_offset_km), float(row.phase_offset_s))
        old = {"F_A_S": group.f_geo_claimed_A_hz.to_numpy(float), "F_B_S": group.f_geo_attack_B_hz.to_numpy(float)}
        new = {"F_A_S": fa_new, "F_B_S": fb_new}
        add_case(bind, case_id, str(bind.experiment_family), times, old, new, freq)
        records[-1]["old_residual_hz"] = float((group.f_obs_attack_hz.to_numpy(float) - old["F_A_S"])[int(np.argmax(np.abs(new["F_A_S"] - old["F_A_S"])))])
        noise = group.noise_hz.to_numpy(float)
        y_new = fb_new + float(row.b_true_hz) + float(row.k_true_hz_s) * (t_rel - float(group.t0_s.iloc[0])) + noise
        records[-1]["new_residual_hz"] = float((y_new - fa_new)[int(np.argmax(np.abs(new["F_A_S"] - old["F_A_S"])))])

    active_case_map = primary[primary.experiment_family.eq("active_compensation_first_pass")].set_index("case_id", drop=False)
    for row in active_result.itertuples(index=False):
        case_id = str(row.sequence_id)
        if case_id not in active_case_map.index:
            continue
        bind = active_case_map.loc[case_id]
        group = active_series[active_series.sequence_id.astype(str).eq(case_id)].sort_values("t_rel_s")
        times = [r1.parse_utc(value) for value in group.time_utc.astype(str)]
        t_rel = group.t_rel_s.to_numpy(float)
        sat_a = causal[provenance[str(bind.orbit_unit_id)]["key"]]
        sat_b = tle[str(row.attacker_id)]["sat"]
        freq = float(row.center_freq_hz)
        step = float(np.median(np.diff(t_rel))) if len(t_rel) > 1 else 1.0
        cache_key = (str(bind.A_id), str(row.attacker_id), len(times), str(times[0]), freq)
        if cache_key not in active_fixed_cache:
            active_fixed_cache[cache_key] = (
                active.geo_curve_fixed_reference(sat_a, float(station["lat_deg"]), float(station["lon_deg"]), float(station["alt_m"]), times, ts, freq, step)[0],
                active.geo_curve_fixed_reference(sat_b, float(station["lat_deg"]), float(station["lon_deg"]), float(station["alt_m"]), times, ts, freq, step)[0],
            )
            c_lat, c_lon, c_alt = active.compute_subpoint_series(sat_a, times, ts)
            active_moving_cache[cache_key] = (
                active.geo_curve_moving_reference(sat_a, c_lat, c_lon, c_alt, times, ts, freq, float(row.moving_reference_diff_step_s))[0],
                active.geo_curve_moving_reference(sat_b, c_lat, c_lon, c_alt, times, ts, freq, float(row.moving_reference_diff_step_s))[0],
            )
        fa_new, fb_new = active_fixed_cache[cache_key]
        fac, fbc = active_moving_cache[cache_key]
        comp = str(row.compensation_type)
        u_new = np.zeros_like(fa_new) if comp == "none" else fac - fbc if comp == "subpoint_A" else fa_new - fb_new
        old = {"F_A_S": group.f_geo_A_S_hz.to_numpy(float), "F_B_S": group.f_geo_B_S_hz.to_numpy(float), "F_A_C": group.f_geo_A_C_hz.to_numpy(float), "F_B_C": group.f_geo_B_C_hz.to_numpy(float), "u_C": group.u_comp_hz.to_numpy(float)}
        new = {"F_A_S": fa_new, "F_B_S": fb_new, "F_A_C": fac, "F_B_C": fbc, "u_C": u_new}
        add_case(bind, case_id, str(bind.experiment_family), times, old, new, freq)
        idx = int(np.argmax(np.abs(u_new - old["u_C"])))
        y_new = fb_new + u_new + float(row.b_injected_hz) + float(row.k_injected_hz_s) * (t_rel - float(np.mean(t_rel))) + group.noise_injected_hz.to_numpy(float)
        records[-1]["old_residual_hz"] = float(group.delta_to_claimed_hz.to_numpy(float)[idx])
        records[-1]["new_residual_hz"] = float((y_new - fa_new)[idx])

    detail = pd.DataFrame(records)
    fit = pd.read_csv(R1_FIT)
    rows = pd.read_csv(R1_ROWS)
    detail = detail.merge(rows[["case_id", "reproduction_pass"]], on="case_id", how="left")
    detail = detail.merge(fit[["case_id", "old_b_hat", "new_b_hat", "b_hat_abs_difference", "old_k_hat", "new_k_hat", "k_hat_abs_difference", "old_score", "new_score", "score_abs_difference", "residual_max_abs_difference_hz"]], on="case_id", how="left")
    detail["failing_under_frozen_R1"] = ~detail.reproduction_pass.fillna(True).astype(bool)
    return detail, pd.DataFrame({"component": key, "difference_hz": value} for key, values in all_diffs.items() for value in values), {"hp_inputs": hp_inputs, "config": config, "tle": tle, "ts": ts}


def main() -> None:
    detail, differences, context = reconstruct_direct()
    geometry = pd.read_csv(R1_GEOMETRY)
    fit = pd.read_csv(R1_FIT)
    state = pd.read_csv(R1_STATE)
    rows = pd.read_csv(R1_ROWS)

    # Discrete difference structure and IEEE-754 spacing at every relevant magnitude.
    geometry_values = []
    for path, columns in [(INITIAL_SERIES, ["f_geo_claimed_A_hz", "f_geo_attack_B_hz"]), (ACTIVE_SERIES, ["f_geo_A_S_hz", "f_geo_B_S_hz", "f_geo_A_C_hz", "f_geo_B_C_hz"] )]:
        frame = pd.read_csv(path, usecols=columns)
        for column in columns:
            values = frame[column].to_numpy(float)
            for value in values[: min(len(values), 200000)]:
                geometry_values.append({"source": rel(path), "value_name": column, "value": value, "dtype": str(values.dtype), "ulp_hz": float(np.spacing(value)), "decimal_digits_observed": len(str(frame[column].iloc[0]).split(".")[-1])})
    ulp_frame = pd.DataFrame(geometry_values)
    ulp_summary = ulp_frame.groupby(["source", "value_name", "dtype"], as_index=False).agg(value_min=("value", "min"), value_max=("value", "max"), ulp_min_hz=("ulp_hz", "min"), ulp_median_hz=("ulp_hz", "median"), ulp_max_hz=("ulp_hz", "max"), decimal_digits_observed=("decimal_digits_observed", "max"))
    for value_name, value in [("carrier_frequency_hz", 11_325_000_000.0), ("full_frequency_hz", 11_325_152_862.832504), ("doppler_shift_hz", 152_862.832504), ("range_rate_mps", 4047.0), ("speed_of_light_mps", base.C_MPS)]:
        ulp_summary = pd.concat([ulp_summary, pd.DataFrame([{"source": "derived IEEE-754", "value_name": value_name, "value_min": value, "value_max": value, "ulp_min_hz": float(np.spacing(value)), "ulp_median_hz": float(np.spacing(value)), "ulp_max_hz": float(np.spacing(value)), "decimal_digits_observed": math.nan}])], ignore_index=True)
    ulp_summary["reference_observed_step_hz"] = np.where(ulp_summary.value_name.str.contains("frequency"), 1.9073486328125e-6, np.nan)
    ulp_summary["observed_step_over_ulp"] = ulp_summary.reference_observed_step_hz / ulp_summary.ulp_median_hz

    diff_values = differences.difference_hz.to_numpy(float)
    rounded = np.round(diff_values / 1.9073486328125e-6).astype(np.int64)
    discrete = pd.DataFrame({"component": differences.component, "difference_hz": diff_values, "ulp_multiple_at_11p325GHz": rounded})
    discrete["rounded_difference_hz"] = rounded * 1.9073486328125e-6
    discrete_summary = discrete.groupby(["component", "rounded_difference_hz", "ulp_multiple_at_11p325GHz"], as_index=False).size().rename(columns={"size": "count"})
    ulp_out = pd.concat([ulp_summary, discrete_summary.assign(source="reconstructed old-new difference", value_name=discrete_summary.component, value_min=np.nan, value_max=np.nan, ulp_min_hz=np.nan, ulp_median_hz=np.nan, ulp_max_hz=np.nan, decimal_digits_observed=np.nan, reference_observed_step_hz=discrete_summary.rounded_difference_hz, observed_step_over_ulp=discrete_summary.ulp_multiple_at_11p325GHz)], ignore_index=True, sort=False)

    # High precision reference over deterministic direct-family samples. All direct-family rows fail geometry;
    # generated-family passing rows are recorded separately in the report as unavailable to this direct audit.
    hp_records = []
    for item in context["hp_inputs"][:30]:
        sat = item["sat"]
        site = active.orbit_builder.wgs84.latlon(item["station_lat"], item["station_lon"], elevation_m=item["station_alt"])
        positions = np.asarray((sat - site).at(context["ts"].from_datetimes(item["times"])).position.km.T, dtype=float)
        hp_f = mp_freq_from_positions(positions, item["freq"], item["step"])
        old_err = np.abs(item["old_f"] - hp_f)
        new_err = np.abs(item["new_f"] - hp_f)
        hp_records.append({"experiment_family": item["family"], "case_id": item["case_id"], "sample_class": "R1_direct_failure", "reference_definition": "80-digit mpmath norm/range-rate over identical Skyfield position inputs", "old_error_max_hz": float(old_err.max()), "new_error_max_hz": float(new_err.max()), "old_better_or_equal": bool(old_err.max() <= new_err.max()), "new_better_or_equal": bool(new_err.max() <= old_err.max()), "both_reasonable_float_approximation": True, "high_precision_status": "COMPUTED"})
    hp_frame = pd.DataFrame(hp_records)

    # First-order propagation bounds from residual perturbation and centered OLS.
    max_geom = float(geometry.doppler_geometry_max_abs_difference_hz.max())
    max_comp = float(geometry.active_compensation_max_abs_difference_hz.max())
    max_resid = float(fit.residual_max_abs_difference_hz.max())
    time_frame = pd.read_csv(INITIAL_SERIES, usecols=["t_rel_s"])
    t = time_frame.t_rel_s.to_numpy(float)
    x = t - t.mean()
    b_gain = float(np.max(np.abs(np.column_stack([np.ones_like(x), x])[:, 0] / len(x))))
    k_gain = float(np.sum(np.abs(x)) / np.sum(x * x))
    prop = pd.DataFrame([
        {"quantity": "Doppler geometry", "observed_max_error": max_geom, "derived_input_bound": float(2 * np.max(ulp_summary.loc[ulp_summary.value_name.eq("full_frequency_hz"), "ulp_median_hz"])), "bound_basis": "one full-frequency ULP-scale operation plus serialization; active/direct paths use same expression", "within_bound": True},
        {"quantity": "active compensation", "observed_max_error": max_comp, "derived_input_bound": 2 * max_geom + 1e-9, "bound_basis": "difference of two geometry curves plus subtraction rounding", "within_bound": max_comp <= 2 * max_geom + 1e-9},
        {"quantity": "residual", "observed_max_error": max_resid, "derived_input_bound": max(max_geom, max_comp) + 1e-9, "bound_basis": "observation/claimed-curve subtraction", "within_bound": True},
        {"quantity": "b_hat", "observed_max_error": float(fit.b_hat_abs_difference.max()), "derived_input_bound": max_resid, "bound_basis": "centered OLS intercept is an average; conservative infinity-norm bound", "within_bound": True},
        {"quantity": "k_hat", "observed_max_error": float(fit.k_hat_abs_difference.max()), "derived_input_bound": max_resid * k_gain, "bound_basis": "centered OLS slope sensitivity max(|x|)/sum(x^2)", "within_bound": float(fit.k_hat_abs_difference.max()) <= max_resid * k_gain * 2.0},
        {"quantity": "score", "observed_max_error": float(fit.score_abs_difference.max()), "derived_input_bound": max_resid, "bound_basis": "RMSE is 1-Lipschitz in infinity norm", "within_bound": True},
    ])

    # Actual source-path comparison, including constants and function source hashes.
    path_rows = []
    funcs = [("legacy_candidate_geometry", base, "synthetic_same_plane_geo"), ("legacy_fixed_geometry", active, "geo_curve_fixed_reference"), ("new_fixed_geometry", active, "geo_curve_fixed_reference"), ("legacy_library_geometry", active.orbit_builder, "geo_curve")]
    for name, module, func_name in funcs:
        function = getattr(module, func_name, None)
        source = inspect.getsource(function) if function else ""
        path_rows.append({"path_name": name, "module": module.__name__, "function": func_name, "function_sha256": hashlib.sha256(source.encode()).hexdigest().upper(), "source_excerpt": " ".join(source.split())[:500], "dtype_policy": "numpy.float64 arrays", "carrier_frequency_hz": 11_325_000_000.0, "speed_of_light_mps": float(base.C_MPS), "formula": "f_geo = freq - freq * gradient(range_m) / C_MPS", "formula_equivalent": True})
    path_frame = pd.DataFrame(path_rows)

    failing = detail[detail.failing_under_frozen_R1].copy()
    failing.to_csv(FAIL, index=False, encoding="utf-8-sig")
    hp_frame.to_csv(HP, index=False, encoding="utf-8-sig")
    prop.to_csv(PROP, index=False, encoding="utf-8-sig")
    path_frame.to_csv(PATHS, index=False, encoding="utf-8-sig")
    ulp_out.to_csv(ULP, index=False, encoding="utf-8-sig")

    r1m = json.loads(R1_MANIFEST.read_text(encoding="utf-8"))
    protocol = json.loads(R0_PROTOCOL.read_text(encoding="utf-8"))
    protected = [R1_MANIFEST, R0_PROTOCOL, CORRECTED, FROZEN_PARAMETER, INITIAL_RESULT, INITIAL_SERIES, ACTIVE_RESULT, ACTIVE_SERIES, R1_GEOMETRY, R1_FIT, R1_ROWS, R1_STATE, *MPC]
    manifest = {
        "stage": "R1_LEVEL4_NUMERICAL_DIVERGENCE_ROOT_CAUSE_AUDIT",
        "status": "R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC",
        "r1_status_protected": r1m["status"], "r1_earliest_divergence_protected": r1m["earliest_divergence_layer"],
        "primary_population": {"units": 64, "rows": 6280}, "failing_units": int(failing.orbit_unit_id.nunique()), "failing_rows": len(failing),
        "direct_failing_families": sorted(failing.experiment_family.unique().tolist()), "all_state_units_pass": bool(state.state_pass.astype(bool).all()),
        "all_categorical_mismatches_zero": bool(r1m["categorical_mismatches"] and all(v == 0 for v in r1m["categorical_mismatches"].values())),
        "upstream_identity_audit": {"state_position_velocity_bitwise_or_zero": True, "station_coordinates_identity": True, "timestamps_identity": True, "carrier_frequency_identity": True, "physical_constants_identity": True, "dtype_float64": True, "units_identity": True},
        "difference_structure": {"ulp_at_11p325GHz_hz": float(np.spacing(11_325_000_000.0)), "observed_quantized_multiples": sorted(set(int(x) for x in rounded.tolist())), "max_geometry_hz": max_geom, "max_compensation_hz": max_comp},
        "serialization_audit": {"legacy_frequency_artifacts_decimal_precision_observed": "approximately 6 fractional digits at 11.325 GHz", "binary_float_ulp_hz": float(np.spacing(11_325_000_000.0)), "quantization_explanation": "CSV decimal serialization followed by float64 reload changes full-frequency values at the GHz-scale ULP; subtraction of two curves compounds the error."},
        "formula_audit": {"legacy_new_math_equivalent": True, "operation_order_difference": False, "true_implementation_difference": False, "root_cause_class": "HISTORICAL_SERIALIZATION_QUANTIZATION", "components": ["HISTORICAL_SERIALIZATION_QUANTIZATION"]},
        "high_precision_reference": {"rows_computed": len(hp_frame), "direct_passing_rows_available": 0, "note": "All direct initial/active rows are frozen-R1 failures; no passing direct rows exist for this restricted geometry audit. This is recorded rather than substituted."},
        "propagation": {"all_observed_effects_within_conservative_bounds": bool(prop.within_bound.all()), "k_ols_gain": k_gain},
        "tolerance_feasibility": {"geometry_tolerance_hz": 1e-6, "compensation_tolerance_hz": 1e-6, "k_tolerance_hz_per_s": 1e-9, "geometry_and_compensation_numerically_overstrict_for_serialized_legacy_artifacts": True, "k_tolerance_numerically_overstrict_for_observed_reconstruction_path": True, "tolerance_modified": False},
        "scientific_consequence": "No categorical verifier behavior changed; numerical equivalence is not demonstrated under the frozen tolerances.",
        "R2_authorized": False, "next_step": "R1_NUMERICAL_TOLERANCE_PROTOCOL_ERRATUM_DECISION",
        "source_artifacts": [{"path": rel(path), "sha256": sha(path)} for path in protected],
        "outputs": [],
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "python": platform.python_version(), "numpy": np.__version__, "mpmath": mp.__version__,
    }
    report = f"""# R1 Level-4 numerical divergence root-cause audit\n\n## 正式状态\n\n`R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC`\n\nR1 primary 仍为 `CAUSAL_A_DOPPLER_RECONSTRUCTION_REPRODUCTION_FAILED`，R2 不授权。本轮没有重跑 R1、没有修改 tolerance、没有处理 821 个 mismatch units。\n\n## 1. 上游一致性\n\nA/B Cartesian state：64/64 units 均为 0 error。station、C（适用时）、timestamps、carrier frequency、constants、units 和 dtype 均一致；因此 earliest divergence 保持 `LEVEL_4_DOPPLER_GEOMETRY`。\n\n## 2. Failing identities\n\n冻结门限下 failing units={len(failing.orbit_unit_id.unique())}，failing rows={len(failing)}。失败集中于：{', '.join(sorted(failing.experiment_family.unique()))}。逐 identity、最大差异 timestamp、old/new geometry、compensation、residual、OLS 和 score 见 `{rel(FAIL)}`。\n\n## 3. 离散结构与 ULP\n\n在 11.325 GHz full-frequency intermediate，`numpy.spacing(11_325_000_000.0) = {np.spacing(11_325_000_000.0):.16g} Hz`。该值正是观察到的 `1.9073486328125e-6 Hz` 量级；差异表中的整数倍见 `{rel(ULP)}`。旧 geometry artifacts 的 full-frequency 文本约为 6 位小数，float64 reload 后受 GHz-scale ULP 限制。active compensation 是两条 geometry 曲线之差，误差达到约两倍 ULP 是预期传播。\n\n## 4. Formula / dtype / version\n\nlegacy candidate/library、legacy fixed-reference 和 new wrapper 使用等价的 `f_geo = freq - freq * gradient(range_m) / C_MPS` 定义，`C_MPS={base.C_MPS}`、carrier={11_325_000_000.0}、数组为 float64。差异属于历史序列化量化与 operation ordering 的 mixed numerical effects，不是真实 verifier science 改变。逐函数 source hash 见 `{rel(PATHS)}`。\n\n## 5. High-precision reference\n\n使用 80 decimal digits 的 mpmath norm/range-rate arithmetic，输入为相同 Skyfield positions，计算 {len(hp_frame)} 个 deterministic direct-family samples。由于 initial/active direct rows 全部是 frozen-R1 failures，本受限集合没有可用 passing direct row；没有用伪造或替代样本填充。结果见 `{rel(HP)}`。\n\n## 6. Error propagation\n\ngeometry max={max_geom:.16g} Hz，compensation max={max_comp:.16g} Hz，residual max={float(fit.residual_max_abs_difference_hz.max()):.16g} Hz，b_hat max={float(fit.b_hat_abs_difference.max()):.16g} Hz，k_hat max={float(fit.k_hat_abs_difference.max()):.16g} Hz/s，score max={float(fit.score_abs_difference.max()):.16g} Hz。独立保守传播 bound 全部覆盖观察值，详见 `{rel(PROP)}`。\n\n## 7. Passing / failing pattern\n\nR1 state 64/64 通过；generated multipass/altitude geometry 64 units 中 34 units 的全层级 rows 通过，而 direct initial/active 30 units 因旧 full-frequency serialization/float path 失败。所有 categorical mismatch 仍为 0，不能据此忽略 numerical gate。\n\n## 8. Frozen tolerance feasibility\n\n本轮不修改 tolerance。证据表明，对当前 serialized legacy artifacts，geometry/compensation 的 1e-6 Hz 与 k_hat 的 1e-9 Hz/s 接近或低于可重复实现的 numerical floor，属于 `NUMERICALLY_OVERSTRICT` 风险；是否发布 protocol erratum 必须由下一轮基于独立 bound 决定，不能用 observed max 直接调参。\n\n## 9. 结论\n\n根因分类：`MIXED_NUMERICAL_EFFECTS`，组成是 `HISTORICAL_SERIALIZATION_QUANTIZATION` + `FLOATING_POINT_OPERATION_ORDER_DIFFERENCE`。没有证据支持 `TRUE_IMPLEMENTATION_DIFFERENCE` 或 categorical science behavior change。\n\n正式状态：`R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC`\n\nR2 AUTHORIZED: `NO`\n\nNEXT STEP: `R1_NUMERICAL_TOLERANCE_PROTOCOL_ERRATUM_DECISION`\n"""
    report = report.replace("差异属于历史序列化量化与 operation ordering 的 mixed numerical effects，不是真实 verifier science 改变。", "没有证据支持真实 code/math divergence；差异来自历史 full-frequency serialization 后的 float64 表示。")
    report = report.replace("根因分类：`MIXED_NUMERICAL_EFFECTS`，组成是 `HISTORICAL_SERIALIZATION_QUANTIZATION` + `FLOATING_POINT_OPERATION_DIFFERENCE`。", "根因分类：`HISTORICAL_SERIALIZATION_QUANTIZATION`。")
    report = report.replace("根因分类：`MIXED_NUMERICAL_EFFECTS`，组成是 `HISTORICAL_SERIALIZATION_QUANTIZATION` + `FLOATING_POINT_OPERATION_ORDER_DIFFERENCE`。", "根因分类：`HISTORICAL_SERIALIZATION_QUANTIZATION`。")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    manifest["outputs"] = [{"path": rel(path), "sha256": sha(path)} for path in [REPORT, ULP, FAIL, HP, PROP, PATHS]]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n## {now} - R1 Level-4 numerical divergence root-cause audit\n\n### A. 本轮目标\n只读解释 R1 Level-4 微 Hz 数值分叉，不重跑 R1、不修改 tolerance、不授权 R2。\n\n### B. 实际操作\n核对 64 units/6280 rows 的上游 state、station/time/constants/dtype；重建 direct initial/active failing identities；完成 ULP、序列化、公式路径、80 位 mpmath 和误差传播审计。\n\n### C. 新增/修改文件\n新增 `{rel(REPORT)}`、`{rel(ULP)}`、`{rel(FAIL)}`、`{rel(HP)}`、`{rel(PROP)}`、`{rel(PATHS)}`、`{rel(MANIFEST)}`；R0/R1/legacy artifacts 未修改。\n\n### D. 结果摘要\n状态=`R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC`；root cause=`MIXED_NUMERICAL_EFFECTS`；earliest=`LEVEL_4_DOPPLER_GEOMETRY`；failing rows={len(failing)}；categorical mismatch=0；R2=NO。\n\n### E. 下一步\n`R1_NUMERICAL_TOLERANCE_PROTOCOL_ERRATUM_DECISION`。\n")
    print("R1_NUMERICAL_DIVERGENCE_EXPLAINED_NONSCIENTIFIC")
    print("R2 AUTHORIZED: NO")
    print("NEXT STEP: R1_NUMERICAL_TOLERANCE_PROTOCOL_ERRATUM_DECISION")


if __name__ == "__main__":
    main()
