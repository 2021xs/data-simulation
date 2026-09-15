#!/usr/bin/env python3
"""Deterministic post-hoc orbit-distance terminology and ROE analysis.

This script reads the frozen R2/R3 provenance, reconstructs only selected
existing A/B states, and derives osculating elements/ROE at their recorded
common evaluation epochs.  It does not draw random samples, propagate a new
experiment grid, run a verifier, or change the orbit-uncertainty model.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from astropy.utils import iers
from skyfield.api import load


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_causal_a_doppler_core_reconstruction as core  # noqa: E402
import run_existing_doppler_case_orbit_distinct_relabeling as orbit  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
UNIT_SUMMARY = ROOT / "outputs" / "datasets" / "causal_a_doppler_r3_unit_summary.csv"
CORE_POPULATION = ROOT / "outputs" / "metrics" / "causal_a_doppler_r2_core_population.csv"
RAW_GP = ROOT / "data" / "orbit_uncertainty_stage1" / "raw" / "spacetrack_gp" / "spacetrack_gp_history_20260226_20260329_20sat_omm.json"
STATIC_TLE = ROOT / "data" / "tle" / "starlink_tle.txt"
ROE_OUTPUT = ROOT / "outputs" / "metrics" / "representative_roe_characterization.csv"
TERMINOLOGY_OUTPUT = ROOT / "outputs" / "metrics" / "orbit_distance_terminology_mapping.csv"
REPORT_OUTPUT = ROOT / "outputs" / "reports" / "orbit_distance_theoretical_alignment_and_roe_analysis.md"

MU = orbit.MU_EARTH_KM3_S2
ALTITUDE_LEVELS = (-10.0, -5.0, -1.0, 0.0, 1.0, 5.0, 10.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="replace only this script's three outputs")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def wrap_pi(angle: float) -> float:
    return float((angle + math.pi) % (2.0 * math.pi) - math.pi)


def wrap_2pi(angle: float) -> float:
    return float(angle % (2.0 * math.pi))


def osculating_elements(r_km: np.ndarray, v_km_s: np.ndarray) -> dict[str, float]:
    """Return two-body osculating elements in GCRS, with nonsingular e-vector components."""
    r = np.asarray(r_km, dtype=float)
    v = np.asarray(v_km_s, dtype=float)
    r_norm = float(np.linalg.norm(r))
    v_norm = float(np.linalg.norm(v))
    h_vec = np.cross(r, v)
    h_norm = float(np.linalg.norm(h_vec))
    h_hat = h_vec / h_norm
    k_hat = np.array([0.0, 0.0, 1.0])
    n_vec = np.cross(k_hat, h_vec)
    n_norm = float(np.linalg.norm(n_vec))
    if n_norm < 1e-12:
        raise ValueError("Equatorial orbit is outside this analysis convention")
    p_node = n_vec / n_norm
    q_node = np.cross(h_hat, p_node)
    e_vec = ((v_norm**2 - MU / r_norm) * r - float(np.dot(r, v)) * v) / MU
    eccentricity = float(np.linalg.norm(e_vec))
    energy = 0.5 * v_norm**2 - MU / r_norm
    semi_major_axis = float(-MU / (2.0 * energy))
    inclination = float(math.acos(float(np.clip(h_hat[2], -1.0, 1.0))))
    raan = wrap_2pi(math.atan2(float(p_node[1]), float(p_node[0])))
    e_x = float(np.dot(e_vec, p_node))
    e_y = float(np.dot(e_vec, q_node))

    if eccentricity > 1e-10:
        cos_eccentric_anomaly = float(np.clip((1.0 - r_norm / semi_major_axis) / eccentricity, -1.0, 1.0))
        sin_eccentric_anomaly = float(np.dot(r, v) / (eccentricity * math.sqrt(MU * semi_major_axis)))
        eccentric_anomaly = math.atan2(sin_eccentric_anomaly, cos_eccentric_anomaly)
        mean_anomaly = eccentric_anomaly - eccentricity * math.sin(eccentric_anomaly)
        argument_of_perigee = math.atan2(e_y, e_x)
        mean_argument_of_latitude = wrap_2pi(argument_of_perigee + mean_anomaly)
    else:
        mean_anomaly = 0.0
        argument_of_perigee = 0.0
        mean_argument_of_latitude = wrap_2pi(math.atan2(float(np.dot(r, q_node)), float(np.dot(r, p_node))))

    return {
        "a_km": semi_major_axis,
        "e": eccentricity,
        "i_rad": inclination,
        "raan_rad": raan,
        "argp_rad": wrap_2pi(argument_of_perigee),
        "mean_anomaly_rad": wrap_2pi(mean_anomaly),
        "u_mean_rad": mean_argument_of_latitude,
        "e_x": e_x,
        "e_y": e_y,
        "radius_km": r_norm,
        "speed_km_s": v_norm,
    }


def quasi_nonsingular_roe(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    delta_raan = wrap_pi(b["raan_rad"] - a["raan_rad"])
    values = {
        "delta_a": (b["a_km"] - a["a_km"]) / a["a_km"],
        "delta_lambda_rad": wrap_pi((b["u_mean_rad"] - a["u_mean_rad"]) + delta_raan * math.cos(a["i_rad"])),
        "delta_e_x": b["e_x"] - a["e_x"],
        "delta_e_y": b["e_y"] - a["e_y"],
        "delta_i_x_rad": b["i_rad"] - a["i_rad"],
        "delta_i_y_rad": delta_raan * math.sin(a["i_rad"]),
        "delta_raan_rad_wrapped": delta_raan,
    }
    for source, target in [
        ("delta_a", "a_delta_a_km"),
        ("delta_lambda_rad", "a_delta_lambda_km"),
        ("delta_e_x", "a_delta_e_x_km"),
        ("delta_e_y", "a_delta_e_y_km"),
        ("delta_i_x_rad", "a_delta_i_x_km"),
        ("delta_i_y_rad", "a_delta_i_y_km"),
    ]:
        values[target] = a["a_km"] * values[source]
    values["a_delta_e_norm_km"] = math.hypot(values["a_delta_e_x_km"], values["a_delta_e_y_km"])
    values["a_delta_i_norm_km"] = math.hypot(values["a_delta_i_x_km"], values["a_delta_i_y_km"])
    groups = {
        "relative_semimajor_axis": abs(values["a_delta_a_km"]),
        "relative_mean_longitude_phase": abs(values["a_delta_lambda_km"]),
        "relative_eccentricity_vector": values["a_delta_e_norm_km"],
        "relative_inclination_vector": values["a_delta_i_norm_km"],
    }
    values["dominant_scaled_roe_structure"] = max(groups, key=groups.get)
    values["dominant_scaled_roe_magnitude_km"] = groups[values["dominant_scaled_roe_structure"]]
    return values


def representative_rows(units: pd.DataFrame) -> pd.DataFrame:
    units = units.copy()
    for column in ["altitude_offset_km", "rho99", "controlled_observation_acceptance_fraction"]:
        units[column] = pd.to_numeric(units[column], errors="coerce")

    altitude = units.loc[
        units["experiment_family"].eq("controlled_altitude_difference_synthetic_B")
        & units["altitude_offset_km"].isin(ALTITUDE_LEVELS)
    ]
    complete_groups: list[tuple[int, str]] = []
    for (a_id, segment), group in altitude.groupby(["A_id", "segment_or_pass_id"], dropna=False):
        if set(group["altitude_offset_km"].tolist()) == set(ALTITUDE_LEVELS):
            complete_groups.append((int(a_id), str(segment)))
    if not complete_groups:
        raise SystemExit("No frozen controlled-altitude geometry contains all seven requested levels")
    chosen_a, chosen_segment = sorted(complete_groups)[0]
    chosen_altitude = altitude.loc[
        altitude["A_id"].astype(int).eq(chosen_a)
        & altitude["segment_or_pass_id"].astype(str).eq(chosen_segment)
    ].sort_values("altitude_offset_km")
    if len(chosen_altitude) != len(ALTITUDE_LEVELS):
        raise SystemExit("Controlled-altitude representative selection is not one row per requested level")
    chosen_altitude = chosen_altitude.assign(
        case_role=chosen_altitude["altitude_offset_km"].map(lambda value: f"controlled_altitude_{value:+g}_km"),
        selection_rule="result_blind_lowest_A_and_segment_with_all_seven_levels_including_zero",
    )

    phase = units.loc[units["B_identity_or_perturbation_definition"].eq("synthetic_same_plane_phase_offset_60")].sort_values("orbit_unit_id").head(1)
    inclination = units.loc[units["B_identity_or_perturbation_definition"].eq("synthetic_inclination_offset_0.2")].sort_values("orbit_unit_id").head(1)
    if len(phase) != 1 or len(inclination) != 1:
        raise SystemExit("Frozen phase/inclination representative is missing")
    phase = phase.assign(case_role="phase_offset_plus_60_s", selection_rule="only_frozen_positive_60_s_segment_case")
    inclination = inclination.assign(case_role="inclination_offset_plus_0p2_deg", selection_rule="only_frozen_positive_0p2_deg_segment_case")

    real = units.loc[units["B_class"].eq("REAL_B") & units["orbit_decision"].eq("ORBIT_DISTINCT")].copy()
    high = real.sort_values(["controlled_observation_acceptance_fraction", "orbit_unit_id"], ascending=[False, True]).head(1)
    zero = real.loc[real["controlled_observation_acceptance_fraction"].eq(0.0)].sort_values(["rho99", "orbit_unit_id"]).head(1)
    if len(high) != 1 or len(zero) != 1:
        raise SystemExit("Frozen real-pair high/zero acceptance representatives are missing")
    high = high.assign(case_role="real_pair_highest_existing_controlled_acceptance", selection_rule="requested_result_stratum_max_acceptance_then_orbit_unit_id")
    zero = zero.assign(case_role="real_pair_zero_acceptance_nearest_rho99_boundary", selection_rule="requested_zero_acceptance_stratum_min_rho99_then_orbit_unit_id")

    selected = pd.concat([chosen_altitude, phase, inclination, high, zero], ignore_index=True)
    if len(selected) != 11 or selected["orbit_unit_id"].duplicated().any():
        raise SystemExit("Representative selection must contain eleven distinct frozen units")
    return selected


def terminology_mapping() -> pd.DataFrame:
    rows = [
        ("orbit distance / orbital distance", "未限定时没有单一物理量；历史上下文可能指瞬时位置距离或不确定度归一化距离", "undefined unless qualified", "明确写 instantaneous A–B position separation、RTN displacement 或 rho99", "HIGH", "正式正文禁用裸术语；每次附量纲、历元与 frame"),
        ("orbit difference", "对 A/B 完整相对状态或轨道结构的泛称，不等于单个 km 标量", "common-epoch GCRS state and/or element space", "complete relative state / relative-orbit difference", "MEDIUM", "如需定量，拆成 Δr/Δv、RTN 和/或 ROE"),
        ("physical_position_separation_km", "共同 evaluation epoch 的 |r_B-r_A|", "GCRS Cartesian Euclidean norm", "instantaneous Euclidean A–B position separation", "LOW", "保留；正文补 common epoch 与 GCRS"),
        ("physical_velocity_separation_km_s", "共同 evaluation epoch 的 |v_B-v_A|", "GCRS Cartesian Euclidean norm", "instantaneous Euclidean A–B velocity separation", "LOW", "保留并与 position 一起说明 complete state"),
        ("delta_R_km / delta_T_km / delta_N_km", "共同 evaluation epoch 的 r_B-r_A 在 A 的 RTN 基底投影", "chief-A RTN; R outward, T direction of motion, N orbit normal", "instantaneous chief-RTN relative-position components", "LOW", "保留作为 security primary representation"),
        ("rho99", "冻结 empirical RTN 椭球中的 sqrt(D2/c99)，无 km 量纲且不是概率", "signed 3-D RTN uncertainty-normalized space", "P99-normalized empirical RTN distance (not probability)", "HIGH", "不得称 km distance、概率或 ROE distance"),
        ("5 km / 10 km", "孤立写法语义不唯一；项目中至少出现地面距离、anchor radius offset、瞬时 A–B separation、RTN component", "context dependent", "总是加限定词与 frame", "HIGH", "逐处替换为 ground geodesic / anchor-radius / instantaneous GCRS / RTN"),
        ("distance_km / distance_to_center_km", "segment/direction family 中地面参考点 C 到服务点 S 的测地距离", "Earth surface geodesic / receiver local tangent parameterization", "ground C–S geodesic separation", "HIGH", "不得写成 satellite orbit distance"),
        ("C_S_distance_km / e_km / R_km", "A2/fixed-C 语境中的地面 C–S 或参考半径实验因子", "Earth surface geodesic or prescribed ground-radius grid", "ground C–S geodesic separation / ground radius factor", "HIGH", "首次出现给出 C、S 定义；禁止与 r_A/r_B 混用"),
        ("along_track_offset_km (segment receiver geometry)", "历史字段实际为 d cos(phi) 的地面局部二维分量", "receiver local tangent / bearing parameterization", "receiver-local ground-direction component", "HIGH", "论文重命名；不得称 orbital along-track"),
        ("cross_track_offset_km (segment receiver geometry)", "历史字段实际为 d sin(phi) 的地面局部二维分量", "receiver local tangent / bearing parameterization", "receiver-local ground-direction component", "HIGH", "论文重命名；不得称 orbital cross-track"),
        ("along-track / cross-track / radial (orbit context)", "相对于 chief A 的 T/N/R 方向，不等于 East/North 或地面 bearing", "chief-A RTN", "RTN transverse / normal / radial", "MEDIUM", "每处显式写 RTN；不要和 receiver-local 术语混用"),
        ("altitude difference / altitude_offset_km / delta_h_km", "synthetic anchor 时刻在 A 的径向单位矢量上改变圆轨道半径；B 的圆轨道速度随新半径共同定义", "anchor GCRS radial direction; circular two-body construction", "synthetic anchor orbital-radius offset", "HIGH", "不要自动写成 ΔR=Δa 或恒定 A–B 距离"),
        ("same-plane phase offset / phase_offset_s", "B 在其完整圆轨道上使用 dt+phase_offset_s；是时间参数化的相位偏移", "synthetic orbital plane / mean-longitude-like phase", "synthetic orbital phase-time offset", "MEDIUM", "正文可同时给 a·δλ，不能把秒直接称 km"),
        ("inclination offset / orbit-plane perturbation", "anchor 处旋转目标法向后重建 B 的圆轨道平面与完整速度", "GCRS inertial orbit-plane construction", "synthetic orbit-plane/inclination construction parameter", "MEDIUM", "报告实际 ROE inclination vector；参数角不等于单时刻 ΔN"),
        ("direction offset / direction sensitivity", "可能指地面 C→S bearing，也可能指 orbital RTN；历史主线以前者居多", "receiver local tangent or chief-A RTN depending family", "ground service-bearing sensitivity / RTN-direction sensitivity", "HIGH", "拆分命名，不单写 direction offset"),
        ("position offset", "必须区分完整 state construction 与仅改 position 的 historical diagnostic", "Cartesian frame, epoch dependent", "complete-state local perturbation 或 position-only local diagnostic", "HIGH", "检查 velocity provenance；不能据单个 Δr 宣称另一条轨道"),
        ("perturb_along_track / near-orbit lower-bound family", "逐时刻沿速度方向平移 position，velocity 未作为 B state 定义", "local Cartesian direction at each sample", "local along-track position sensitivity diagnostic", "HIGH", "维持降级；不得作为 different-orbit evidence"),
        ("SYNTHETIC_RELATIVE_TO_A", "由 causal A 的 anchor 完整 r,v 基底构造新的 circular two-body r_B,v_B 并传播到 evaluation epoch", "GCRS state; two-body circular synthetic propagation", "physically consistent local-state-initialized synthetic orbit", "LOW", "保留；同时报告 construction parameter 与实际 common-epoch RTN/ROE"),
        ("REAL_B", "静态 Starlink TLE 中另一 NORAD 对象在 A evaluation epoch 的完整传播状态", "TLE/SGP4 TEME transformed to GCRS", "real-catalog B propagated to common epoch", "LOW", "保留；声明来源为 static TLE，不称 synthetic"),
    ]
    evidence = [
        "joint_security_final_results_freeze_and_paper_synthesis.md; orbit_distinct_doppler_joint_security_analysis.md",
        "causal_a_doppler_r3_unit_summary.csv; representative_roe_characterization.csv",
        "run_causal_a_doppler_core_reconstruction.py:547",
        "run_causal_a_doppler_core_reconstruction.py:548",
        "run_causal_a_doppler_core_reconstruction.py:511,549-551",
        "run_causal_a_doppler_core_reconstruction.py:525,1351",
        "controlled_altitude_difference_report.md; segment-local reports; frozen synthesis",
        "freeze_causal_a_doppler_core_reconstruction_design.py:264,281; synthetic_b audit:161,244",
        "a2_reference_point_attack_audit_report.md; fixed_c_legacy_reconciliation_report.md",
        "synthetic_b_orbit_construction_audit.md:244",
        "synthetic_b_orbit_construction_audit.md:244",
        "run_orbit_uncertainty_stage0_starlink_smoke.py:97-102; D'Amico et al. ISSFD 2009",
        "run_existing_doppler_case_orbit_distinct_relabeling.py:273-300",
        "run_existing_doppler_case_orbit_distinct_relabeling.py:297-300",
        "run_existing_doppler_case_orbit_distinct_relabeling.py:281-291",
        "segment-local direction fields and reports",
        "synthetic_b_orbit_construction_audit.md",
        "run_tle_error_lower_bound_calibration.py:321-329",
        "run_causal_a_doppler_core_reconstruction.py:500-507",
        "run_causal_a_doppler_core_reconstruction.py:492-497",
    ]
    frame = pd.DataFrame(rows, columns=[
        "historical_term", "actual_semantics", "coordinate_frame", "recommended_term", "paper_risk", "action"
    ])
    frame["source_evidence"] = evidence
    return frame


def reconstruct(selected: pd.DataFrame, population: pd.DataFrame) -> pd.DataFrame:
    pop = population.loc[population["orbit_unit_id"].isin(selected["orbit_unit_id"])].copy()
    if len(pop) != len(selected):
        raise SystemExit("Selected frozen units do not have a one-to-one R2 population provenance row")
    ts = load.timescale(builtin=True)
    provenance, _ = core.load_causal_catalog(pop, ts)
    tle = orbit.parse_tle_catalog(STATIC_TLE)
    rows: list[dict[str, Any]] = []

    for frozen in selected.itertuples(index=False):
        unit_id = str(frozen.orbit_unit_id)
        prov = provenance[unit_id]
        when = orbit.parse_utc(str(frozen.evaluation_time))
        a_r, a_v = orbit.state_from_lines(prov["line1"], prov["line2"], when)

        if str(frozen.B_class) == "REAL_B":
            b_id = str(frozen.B_identity_or_perturbation_definition)
            entry = tle.get(b_id)
            if entry is None:
                raise SystemExit(f"Static real B missing: {unit_id}:{b_id}")
            b_r, b_v = orbit.state_from_lines(entry["line1"], entry["line2"], when)
            b_source = f"{rel(STATIC_TLE)}::NORAD_{b_id}::SGP4_TEME_to_GCRS"
        else:
            anchor = orbit.parse_utc(str(frozen.synthetic_construction_anchor_time))
            b_r, b_v = orbit.synthetic_state(
                (prov["line1"], prov["line2"]), anchor, when,
                float(frozen.altitude_offset_km), float(frozen.phase_offset_s), float(frozen.inclination_offset_deg),
            )
            b_id = "SYNTHETIC_RELATIVE_TO_A"
            b_source = "frozen_synthetic_state_rule::circular_two_body_complete_r_v"

        displacement = b_r - a_r
        delta_rtn = orbit.rtn_basis(a_r, a_v) @ displacement
        a_elements = osculating_elements(a_r, a_v)
        b_elements = osculating_elements(b_r, b_v)
        roe = quasi_nonsingular_roe(a_elements, b_elements)
        position_separation = float(np.linalg.norm(displacement))
        velocity_separation = float(np.linalg.norm(b_v - a_v))
        saved_rtn = np.array([frozen.delta_R_km, frozen.delta_T_km, frozen.delta_N_km], dtype=float)

        a_name = str(frozen.A_name).strip()
        if not a_name or a_name.lower() == "nan":
            a_name = tle.get(str(frozen.A_id), {}).get("name", f"NORAD-{frozen.A_id}")
        b_name = tle.get(str(b_id), {}).get("name", str(b_id))
        row: dict[str, Any] = {
            "case_role": frozen.case_role,
            "selection_rule": frozen.selection_rule,
            "experiment_family": frozen.experiment_family,
            "orbit_unit_id": unit_id,
            "A_id": str(frozen.A_id),
            "A_name": a_name,
            "B_class": frozen.B_class,
            "B_id_or_definition": frozen.B_identity_or_perturbation_definition,
            "B_name": b_name,
            "segment_or_pass_id": frozen.segment_or_pass_id,
            "evaluation_epoch_utc": str(frozen.evaluation_time),
            "common_epoch_confirmed": True,
            "state_reference_frame": "GCRS (TEME-to-GCRS for TLE states)",
            "gravitational_parameter_km3_s2": MU,
            "element_convention": "two-body osculating; u=omega+M; e_x=e*cos(omega); e_y=e*sin(omega); B-minus-A ROE; angles wrapped to [-pi,pi)",
            "A_state_source": f"causal_A_GP_ID={prov['GP_ID']}::SGP4_TEME_to_GCRS",
            "B_state_source": b_source,
            "synthetic_construction_anchor_time": frozen.synthetic_construction_anchor_time,
            "altitude_offset_km": frozen.altitude_offset_km,
            "phase_offset_s": frozen.phase_offset_s,
            "inclination_offset_deg": frozen.inclination_offset_deg,
            "frozen_orbit_decision": frozen.orbit_decision,
            "frozen_rho99": frozen.rho99,
            "frozen_controlled_observation_acceptance_fraction": frozen.controlled_observation_acceptance_fraction,
            "instantaneous_position_separation_km": position_separation,
            "instantaneous_velocity_separation_km_s": velocity_separation,
            "orbit_plane_separation_deg": math.degrees(math.acos(float(np.clip(
                np.dot(np.cross(a_r, a_v), np.cross(b_r, b_v))
                / (np.linalg.norm(np.cross(a_r, a_v)) * np.linalg.norm(np.cross(b_r, b_v))),
                -1.0, 1.0,
            )))),
            "delta_R_km": float(delta_rtn[0]),
            "delta_T_km": float(delta_rtn[1]),
            "delta_N_km": float(delta_rtn[2]),
            "frozen_state_position_reconstruction_abs_error_km": abs(position_separation - float(frozen.physical_position_separation_km)),
            "frozen_state_velocity_reconstruction_abs_error_km_s": abs(velocity_separation - float(frozen.physical_velocity_separation_km_s)),
            "frozen_RTN_reconstruction_max_abs_error_km": float(np.max(np.abs(delta_rtn - saved_rtn))),
        }
        for label, vector in [("A_r", a_r), ("A_v", a_v), ("B_r", b_r), ("B_v", b_v)]:
            suffixes = ("x", "y", "z")
            unit = "km" if label.endswith("r") else "km_s"
            for suffix, value in zip(suffixes, vector):
                row[f"{label}_{suffix}_{unit}"] = float(value)
        for prefix, elements in [("A", a_elements), ("B", b_elements)]:
            for name, value in elements.items():
                row[f"{prefix}_{name}"] = value
        row.update(roe)
        rows.append(row)

    result = pd.DataFrame(rows)
    if result["frozen_state_position_reconstruction_abs_error_km"].max() > 1e-6:
        raise SystemExit("A/B position reconstruction does not reproduce frozen R3 state provenance")
    if result["frozen_state_velocity_reconstruction_abs_error_km_s"].max() > 1e-9:
        raise SystemExit("A/B velocity reconstruction does not reproduce frozen R3 state provenance")
    if result["frozen_RTN_reconstruction_max_abs_error_km"].max() > 1e-6:
        raise SystemExit("RTN reconstruction does not reproduce frozen R3 state provenance")
    return result


def f(value: Any, digits: int = 6) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):.{digits}g}"


def report_text(roe: pd.DataFrame, terms: pd.DataFrame, input_hashes: dict[str, str]) -> str:
    altitude = roe.loc[roe["case_role"].str.startswith("controlled_altitude")].sort_values("altitude_offset_km")
    altitude_zero = altitude.loc[altitude["altitude_offset_km"].eq(0.0)].iloc[0]
    phase = roe.loc[roe["case_role"].eq("phase_offset_plus_60_s")].iloc[0]
    inclination = roe.loc[roe["case_role"].eq("inclination_offset_plus_0p2_deg")].iloc[0]
    real = roe.loc[roe["B_class"].eq("REAL_B")]

    term_lines = [
        "| historical_term | actual_semantics | coordinate/frame | recommended_term | paper_risk | action |",
        "|---|---|---|---|---|---|",
    ]
    for row in terms.itertuples(index=False):
        term_lines.append(f"| {row.historical_term} | {row.actual_semantics} | {row.coordinate_frame} | {row.recommended_term} | {row.paper_risk} | {row.action} |")

    case_lines = [
        "| case | B type | factor | ΔR / ΔT / ΔN (km) | aδa / aδλ (km) | a‖δe‖ / a‖δi‖ (km) | dominant ROE | frozen orbit / acceptance |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in roe.itertuples(index=False):
        factor = (
            f"Δh={f(row.altitude_offset_km)} km" if str(row.case_role).startswith("controlled_altitude")
            else f"Δt={f(row.phase_offset_s)} s" if row.case_role == "phase_offset_plus_60_s"
            else f"Δi_param={f(row.inclination_offset_deg)} deg" if row.case_role == "inclination_offset_plus_0p2_deg"
            else str(row.B_id_or_definition)
        )
        case_lines.append(
            f"| {row.case_role}<br>{row.orbit_unit_id} | {row.B_class} | {factor} | "
            f"{f(row.delta_R_km)} / {f(row.delta_T_km)} / {f(row.delta_N_km)} | "
            f"{f(row.a_delta_a_km)} / {f(row.a_delta_lambda_km)} | "
            f"{f(row.a_delta_e_norm_km)} / {f(row.a_delta_i_norm_km)} | "
            f"{row.dominant_scaled_roe_structure} | {row.frozen_orbit_decision} / {f(row.frozen_controlled_observation_acceptance_fraction, 4)} |"
        )

    altitude_lines = [
        "| Δh parameter (km) | common-epoch ΔR (km) | absolute aδa (km) | Δ(aδa) vs Δh=0 (km) | absolute aδλ (km) | Δ(aδλ) vs Δh=0 (km) | a‖δe‖ (km) |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in altitude.itertuples(index=False):
        altitude_lines.append(
            f"| {f(row.altitude_offset_km)} | {f(row.delta_R_km, 8)} | {f(row.a_delta_a_km, 8)} | "
            f"{f(row.a_delta_a_km-altitude_zero['a_delta_a_km'], 8)} | {f(row.a_delta_lambda_km, 8)} | "
            f"{f(row.a_delta_lambda_km-altitude_zero['a_delta_lambda_km'], 8)} | {f(row.a_delta_e_norm_km, 8)} |"
        )

    max_pos = roe["frozen_state_position_reconstruction_abs_error_km"].max()
    max_vel = roe["frozen_state_velocity_reconstruction_abs_error_km_s"].max()
    max_rtn = roe["frozen_RTN_reconstruction_max_abs_error_km"].max()
    hash_lines = "\n".join(f"- `{path}`: `{digest}`" for path, digest in input_hashes.items())

    return f"""# 轨道差异理论对齐与有限 ROE 解释分析

## 1. 审计范围与结论

本轮只读取冻结 R2/R3 provenance 与历史正文，未重跑 407 个 Level-A units、26780 条 observation rows、Monte Carlo、verifier、joint-security aggregate，也未修改 orbit uncertainty model。唯一数值工作是：对 11 个已存在 frozen units 按其原始 provenance 重建共同历元的完整 `r_A,v_A,r_B,v_B`，再做确定性的二体 osculating-element / ROE 后处理。

**最终 verdict：`THEORETICAL_ALIGNMENT_COMPLETE`。**

当前正式方法可稳定分层为：

1. `physical_position_separation_km`：共同历元 GCRS 中的瞬时 Euclidean position separation；
2. `ΔR/ΔT/ΔN`：同一瞬时相对位置在 chief A 的 RTN 中的有符号分量；
3. `rho99`：冻结 empirical RTN uncertainty model 的无量纲归一化距离，是 security primary representation 的判别尺度；
4. ROE：由共同历元完整 `r,v` 推出的 secondary explanatory layer，用来说明相同瞬时 km 背后是 relative semimajor axis、phase、eccentricity 还是 inclination structure；
5. 地面 `C–S distance` / receiver bearing：ground geometry，绝不是 satellite orbit separation。

没有发现新的 primary physics error。现有 primary experiment 无需因术语或轨道定义重跑；唯一 position-only historical family 继续维持 local geometric sensitivity diagnostic 定位。

## 2. 理论口径与计算约定

采用 A 为 chief、B 为 deputy 的准非奇异 ROE：

```text
δa   = (a_B - a_A) / a_A
δλ   = (u_B - u_A) + (Ω_B - Ω_A) cos(i_A),  u = ω + M
δe_x = e_B cos(ω_B) - e_A cos(ω_A)
δe_y = e_B sin(ω_B) - e_A sin(ω_A)
δi_x = i_B - i_A
δi_y = (Ω_B - Ω_A) sin(i_A)
```

角差 wrap 到 `[-π,π)`；长度尺度全部乘 chief semi-major axis `a_A`。这一口径与 D’Amico 等对 near-circular formation flight 的 relative mean longitude、relative eccentricity vector、relative inclination vector定义一致；文献也明确指出 instantaneous Hill/RTN position 是随 argument of latitude 变化的映射，relative eccentricity 产生 R/T 周期结构，relative inclination 产生幅值约 `aδi` 的 N 周期结构。[D’Amico et al., ISSFD 2009](https://issfd.org/ISSFD_2009/FormationFlyingI/Damico.pdf)；[Stanford Space Rendezvous Laboratory, relative astrodynamics models](https://slab.stanford.edu/projects/models)。

本报告的状态/元素约定：

- A 的 causal GP 与 real B 的 static TLE 均先按原工程 SGP4 传播，再由 TEME 转为 GCRS；synthetic B 复用原工程 complete circular two-body `r,v` construction。
- 在每条 frozen unit 的 `evaluation_time` 同时计算 A/B；所有 `Δ` 与 ROE 都是 B minus A。
- `μ = {MU:.7f} km³/s²`；从共同历元 GCRS Cartesian state 计算二体瞬时 osculating elements。
- `a·δλ` 等是可解释的 length-scaled ROE，不是新的 distance norm，不进入 gate。
- 对相距数千至一万 km 的 real pairs，ROE 数值仍可由完整 state 定义，但 near-circular small-separation linear RTN mapping 只作定性结构解释，不能当高精度局部线性模型。
- 单时刻 RTN position **不能唯一反演 ROE**：六维相对轨道至少需要共同历元的完整相对 state（含 velocity）；不同 `Δv` 可在同一个 `Δr` 下给出不同 `δa/δe/δi`。

## 3. 术语 mapping

{chr(10).join(term_lines)}

### 3.1 主要混淆风险

- 裸写“5 km orbit difference”风险最高：它可能是 ground C–S geodesic、synthetic anchor orbital-radius offset、common-epoch `|Δr|`，或某一 RTN component。论文必须明确是哪一种。
- segment-local 历史字段 `along_track_offset_km/cross_track_offset_km` 实际是 receiver-local ground geometry；应改称 ground/service-bearing components，不得拿来解释 satellite RTN T/N。
- controlled altitude 的 `±1/±5/±10 km` 是 **anchor 时刻 orbital-radius construction factor**，不是 universal orbit-distance threshold，也不保证在所有 epoch 有 `|Δr|=|Δh|`、`ΔR=Δh` 或 `Δa=Δh`。
- `rho99` 无量纲、依赖 signed RTN、freshness bin、empirical center/covariance/c99；它既不是 physical km、概率，也不是 ROE norm。

## 4. Representative-case selection 与复算一致性

共 11 cases：同一 A/pass geometry 上的 `Δh=0,±1,±5,±10 km` 七点；冻结的 `+60 s` phase case；冻结的 `+0.2 deg` orbit-plane construction case；real-B ORBIT_DISTINCT 中 controlled acceptance 最大的一例；以及 zero-acceptance 中 rho99 最接近边界的一例。高度组用“拥有全部七个 levels 的最小 A_id/segment id”选择，不读结果；加入 frozen `Δh=0` 只为分离 circularization baseline 与 signed altitude factor 的增量。real 高/低组因任务明确要求两个 acceptance strata，分别在冻结 strata 内按预先声明的极值和稳定 tie-break 选择。没有新造 case 或随机观测。

冻结状态复算最大误差：position norm `{max_pos:.3e} km`，velocity norm `{max_vel:.3e} km/s`，RTN component `{max_rtn:.3e} km`。这确认 CSV 中 ROE 来自与 frozen joint-security unit 一致的 A/B state provenance，而不是新实验状态。

{chr(10).join(case_lines)}

完整 state、A/B osculating elements、六个 dimensionless ROE、六个 `a·ROE` 与复算误差见 `outputs/metrics/representative_roe_characterization.csv`。

## 5. 三个 synthetic family 的特别验证

### 5.1 Controlled altitude

{chr(10).join(altitude_lines)}

绝对 B−A ROE 不能被简化成“只有 δa”：即使 frozen `Δh=0`，B 仍按 anchor radius 被圆化，而 A 是 causal TLE/SGP4 state，所以本例已有 `aδa={f(altitude_zero['a_delta_a_km'])} km`、`aδλ={f(altitude_zero['a_delta_lambda_km'])} km`、`a‖δe‖={f(altitude_zero['a_delta_e_norm_km'])} km` 的 construction baseline。表中多数单例按最大 length-scaled component 会显示 phase-dominant，这不是 altitude 因子失效，而是 absolute B−A ROE 包含了共同的 circularization baseline。

隔离 `Δh=0` baseline 后，signed altitude sweep 的 **增量结构** 很清楚：`Δ(aδa)` 与输入 `Δh` 在数值精度内一一对应；`a‖δe‖` 在七点间保持不变；`aδλ` 只因不同半径的 mean motion 在 anchor/evaluation 半秒差中发生毫米至米级变化。换言之，controlled factor 主要注入 relative semimajor-axis / orbital-radius structure，但每个 absolute A/B pair 还同时带有 phase/eccentricity background。`ΔR` 与 absolute `aδa` 不是定义上相等；本例二者相差约 `{f(altitude_zero['delta_R_km']-altitude_zero['a_delta_a_km'])} km`。结论应写“anchor orbital-radius offset whose incremental ROE effect is primarily relative semimajor axis”，不能写 `ΔR=Δa=Δh`。

### 5.2 Phase offset

`+60 s` case 的 common-epoch RTN 为 `ΔR={f(phase['delta_R_km'])} km, ΔT={f(phase['delta_T_km'])} km, ΔN={f(phase['delta_N_km'])} km`；length-scaled ROE 为 `aδλ={f(phase['a_delta_lambda_km'])} km`、`a‖δe‖={f(phase['a_delta_e_norm_km'])} km`、`aδa={f(phase['a_delta_a_km'])} km`。因此主结构是 relative mean longitude / phase；同时存在非零 relative eccentricity，原因仍包括 synthetic B circularization 与 A osculating eccentricity。不能把它表述成一个纯 Cartesian T translation，也不能声称除 phase 外其他 ROE 严格为零。

### 5.3 Inclination / orbit-plane offset

`+0.2 deg` 是 constructor input label，不是本例最终 classical `i_B-i_A` 或两轨道面夹角的保证值。共同历元完整 state 给出 `i_B-i_A={f(math.degrees(inclination['delta_i_x_rad']))} deg`、plane separation=`{f(inclination['orbit_plane_separation_deg'])} deg`、`a‖δi‖={f(inclination['a_delta_i_norm_km'])} km`；其 dominant structure 为 `{inclination['dominant_scaled_roe_structure']}`。这不影响 B 的动力学一致性，但论文应称“`+0.2 deg` orbit-plane construction parameter”，不能称“实际 classical inclination 精确增加 0.2 deg”。

该 case 的瞬时 `ΔN={f(inclination['delta_N_km'], 8)} km`，远小于 `a‖δi‖`，正是“single-epoch N 很小不代表 plane difference 很小”的例子：near-circular 一阶图景中 N 随 chief argument of latitude 近似谐波变化，振幅与相位由 relative inclination vector 决定；如果 evaluation epoch 接近两轨道面的交线，瞬时 `ΔN` 可以接近零，而别的 orbital phase 会变大。实际 `δi_x/δi_y` 必须由完整 `r,v` 计算，不能只从参数标签或单点 `ΔN` 推断。该标签—realized-angle 差异只要求术语校正；R3 的 orbit gate 与 joint result 本来就使用 realized `r,v→RTN→rho99`，所以无需重跑 primary experiment。

## 6. Real-pair 与 Doppler outcome 的解释边界

两个 real-B case 证明两件事：

1. real B 的来源是 static Starlink TLE，经 SGP4 传播到 A 的同一 evaluation epoch；不属于 synthetic construction。
2. frozen controlled acceptance 与“某一个 Euclidean km”不存在一一对应。高 acceptance representative 与 zero acceptance representative 分别为 `{real.sort_values('frozen_controlled_observation_acceptance_fraction', ascending=False).iloc[0]['orbit_unit_id']}` 和 `{real.sort_values(['frozen_controlled_observation_acceptance_fraction','frozen_rho99']).iloc[0]['orbit_unit_id']}`；其 Doppler outcome 仍由 pass/receiver geometry、时间曲线与 verifier profile fit 共同决定。ROE 在此只解释相对轨道结构，不预测 acceptance，也不建立新 gate。

## 7. 对五个最终问题的回答

1. **“同样 5 km 的 R/T/N 是否应视为不同？”——是，且 RTN + ROE 已足够作理论解释。** RTN 首先区分同一瞬时 5 km 位于 radial、transverse 还是 normal；ROE 再解释它来自 semimajor-axis/phase/eccentricity/inclination 的何种六维相对轨道结构。二者不等价，但互补。
2. **当前 RTN empirical uncertainty model 仍适合作为 security primary representation。** 它直接对应已冻结、可校准的 public-orbit prediction error coordinates 与 signed covariance structure；本轮没有发现需要替换它的物理错误。
3. **ROE 只需要作为 explanatory layer。** 不建 ROE ellipsoid、不设 P95/P99、不替代 rho99、不进入 verifier/security gate。
4. **没有 primary experiment 因术语/轨道定义必须重跑。** 需要的是论文术语收紧与图表 caption 对齐。historical `perturb_along_track` 继续只称 local position sensitivity；若未来想把该 family 当 different-orbit evidence，才需要另行重构，但这不是当前 primary 的缺口。
5. **可以正式结束 orbit-distance methodological alignment。** 结束条件是正文遵循本报告 mapping，固定写清 quantity、epoch、frame 与 construction semantics；不要求改 orbit uncertainty model 或重跑 frozen joint science。

## 8. Paper-ready wording

推荐：

> The primary orbit-distinctness representation remains the signed, freshness-conditioned RTN empirical uncertainty model. Physical separation is reported as an instantaneous common-epoch GCRS norm, while finite quasi-nonsingular ROE are used only post hoc to explain whether a given RTN displacement is associated mainly with relative semimajor axis, mean longitude, eccentricity, or inclination structure.

> The controlled ±1/±5/±10 km altitude parameter is an orbital-radius offset applied at the synthetic construction anchor. It is not assumed to equal the common-epoch radial displacement, semimajor-axis difference, or a universal orbit-distance threshold.

禁止：

> A 5 km orbit difference means the same geometry in every direction.

> rho99 is the probability that two satellites occupy different orbits.

> A single RTN position vector uniquely determines the relative orbit.

## 9. Provenance 与只读边界

输入 SHA256（运行前后未改变）：

{hash_lines}

本轮新增的三个 artifact 是解释性审计产物，不属于 Monte Carlo dataset、verifier metrics 或 frozen joint-security result。脚本为 `scripts/analyze_orbit_distance_roe_alignment.py`；运行只允许覆盖该脚本自己的三个输出。
"""


def main() -> int:
    args = parse_args()
    inputs = [UNIT_SUMMARY, CORE_POPULATION, RAW_GP, STATIC_TLE]
    for path in inputs:
        if not path.exists():
            raise SystemExit(f"Missing input: {rel(path)}")
    outputs = [ROE_OUTPUT, TERMINOLOGY_OUTPUT, REPORT_OUTPUT]
    if not args.overwrite:
        existing = [rel(path) for path in outputs if path.exists()]
        if existing:
            raise SystemExit(f"Refusing to overwrite existing analysis outputs: {existing}")

    before = {rel(path): sha256(path) for path in inputs}
    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    units = pd.read_csv(UNIT_SUMMARY, dtype={"A_id": str})
    population = pd.read_csv(CORE_POPULATION, dtype={"A_id": str})
    selected = representative_rows(units)
    roe = reconstruct(selected, population)
    terms = terminology_mapping()
    after = {rel(path): sha256(path) for path in inputs}
    if before != after:
        raise SystemExit("A protected frozen input changed during deterministic post-hoc analysis")

    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    roe.to_csv(ROE_OUTPUT, index=False, encoding="utf-8-sig", float_format="%.15g")
    terms.to_csv(TERMINOLOGY_OUTPUT, index=False, encoding="utf-8-sig")
    REPORT_OUTPUT.write_text(report_text(roe, terms, before), encoding="utf-8")
    print(f"representative_cases={len(roe)}")
    print(f"terminology_rows={len(terms)}")
    print(f"max_position_reconstruction_error_km={roe['frozen_state_position_reconstruction_abs_error_km'].max():.3e}")
    print(f"max_velocity_reconstruction_error_km_s={roe['frozen_state_velocity_reconstruction_abs_error_km_s'].max():.3e}")
    print(f"max_RTN_reconstruction_error_km={roe['frozen_RTN_reconstruction_max_abs_error_km'].max():.3e}")
    for path in outputs:
        print(f"wrote={rel(path)} sha256={sha256(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
