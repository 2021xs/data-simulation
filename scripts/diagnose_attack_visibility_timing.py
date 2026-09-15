#!/usr/bin/env python
"""Visibility and timing diagnostics for verifier attack sequences.

The attack source in the current verifier experiment is a controlled synthetic
same-plane orbit, not a real TLE object.  This script reuses the same
same-plane circular-orbit construction used by the verifier builder and reports
visibility as a diagnostic, not as an accept/reject gate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from skyfield.api import EarthSatellite, load, wgs84
from skyfield.positionlib import Geocentric

C_MPS = 299_792_458.0
MU_EARTH_KM3_S2 = 398_600.4418


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    parser.add_argument("--attack-dataset", type=Path, default=None)
    parser.add_argument("--sequence-eval", type=Path, default=Path("outputs/metrics/verifier_v2_sequence_eval.csv"))
    parser.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    parser.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    parser.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
    parser.add_argument("--visible-elevation-deg", type=float, default=None)
    parser.add_argument("--search-padding-s", type=float, default=900.0)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def parse_utc(value: str) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso_z(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def parse_tle(path: Path, ts: Any) -> dict[str, dict[str, Any]]:
    if not path.exists():
        fail(f"TLE file not found: {path}")
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    entries: dict[str, dict[str, Any]] = {}
    i = 0
    while i + 2 < len(lines):
        name, line1, line2 = lines[i].strip(), lines[i + 1].strip(), lines[i + 2].strip()
        if line1.startswith("1 ") and line2.startswith("2 "):
            norad = line1[2:7].strip()
            entries[norad] = {"name": name, "sat": EarthSatellite(line1, line2, name, ts)}
            i += 3
        else:
            i += 1
    return entries


def normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        fail("zero-length orbital vector in synthetic same-plane construction")
    return vector / norm


def synthetic_same_plane_positions_km(
    sat: EarthSatellite,
    ts: Any,
    times: list[datetime],
    altitude_offset_km: float,
    phase_offset_s: float,
    reference_times: list[datetime],
) -> np.ndarray:
    reference_sf = ts.from_datetimes(reference_times)
    ref_geo = sat.at(reference_sf)
    pos_km = ref_geo.position.km.T
    vel_km_s = ref_geo.velocity.km_per_s.T
    mid = len(reference_times) // 2
    r0 = pos_km[mid]
    v0 = vel_km_s[mid]
    h_hat = normalize(np.cross(r0, v0))
    p_hat = normalize(r0)
    q_hat = normalize(np.cross(h_hat, p_hat))
    if float(np.dot(v0, q_hat)) < 0:
        q_hat = -q_hat
    radius_km = float(np.linalg.norm(r0) + altitude_offset_km)
    if radius_km <= 6300.0:
        fail(f"synthetic orbit radius is abnormal: {radius_km:.3f} km")
    angular_rate_rad_s = float(np.sqrt(MU_EARTH_KM3_S2 / radius_km**3))
    center_time = reference_times[mid]
    t_centered = np.array([(dt - center_time).total_seconds() for dt in times], dtype=float)
    theta = angular_rate_rad_s * (t_centered + phase_offset_s)
    return radius_km * (np.cos(theta)[:, None] * p_hat + np.sin(theta)[:, None] * q_hat)


def synthetic_elevation_deg(
    sat: EarthSatellite,
    station: Any,
    ts: Any,
    times: list[datetime],
    altitude_offset_km: float,
    phase_offset_s: float,
    reference_times: list[datetime],
) -> np.ndarray:
    pos_km = synthetic_same_plane_positions_km(sat, ts, times, altitude_offset_km, phase_offset_s, reference_times)
    sf_times = ts.from_datetimes(times)
    synthetic_geo = Geocentric(pos_km.T, t=sf_times, center=399, target=-900001)
    topocentric = synthetic_geo - station.at(sf_times)
    return np.asarray(topocentric.altaz()[0].degrees, dtype=float)


def numeric_param(group: pd.DataFrame, column: str, default: float = 0.0) -> float:
    if column not in group.columns:
        return default
    value = pd.to_numeric(group[column], errors="coerce").dropna()
    return float(value.iloc[0]) if not value.empty else default


def contiguous_visible_window(times: list[datetime], visible: np.ndarray) -> tuple[datetime | None, datetime | None]:
    idx = np.flatnonzero(visible)
    if len(idx) == 0:
        return None, None
    return times[int(idx[0])], times[int(idx[-1])]


def main() -> None:
    args = parse_args()
    attack_dataset_path = args.attack_dataset or args.input_dir / "datasets/doppler_verifier_module_boundary_regression_attack_dataset.csv"
    outputs = [
        args.output_dir / "attack_visibility_timing_diagnostic.csv",
        args.output_dir / "attack_visibility_timing_summary.csv",
    ]
    if any(path.exists() for path in outputs) and not args.overwrite:
        fail("output exists; add --overwrite to replace visibility timing diagnostics")
    if not attack_dataset_path.exists():
        fail(f"attack dataset not found: {attack_dataset_path}")
    if not args.sequence_eval.exists():
        fail(f"sequence eval not found: {args.sequence_eval}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    orbit_cfg = read_yaml(args.orbit_config)
    if orbit_cfg.get("mode") != "controlled_starlink":
        fail("current verifier diagnostic expects controlled_starlink mode")
    station_cfg = orbit_cfg["station"]
    visible_mask = float(args.visible_elevation_deg if args.visible_elevation_deg is not None else orbit_cfg.get("time_window", {}).get("min_elevation_deg", 0.0))
    ts = load.timescale()
    tle_entries = parse_tle(args.tle_file, ts)
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))

    attack = pd.read_csv(attack_dataset_path)
    sequence_eval = pd.read_csv(args.sequence_eval)
    score = sequence_eval[(sequence_eval["sample_type"] == "attack") & (sequence_eval["threshold_type"] == args.threshold_type)].copy()
    score_map = score.set_index("sequence_id")["accepted_score_only"].astype(bool).to_dict()
    best_gate_candidates = [
        "accepted_score_plus_global_k",
        "accepted_score_plus_per_target_k_p05_p95",
        "accepted_score_plus_per_target_k_p01_p99",
        "accepted_score_plus_global_bk",
    ]
    best_gate_col = next((c for c in best_gate_candidates if c in score.columns), "accepted_score_only")
    best_gate_map = score.set_index("sequence_id")[best_gate_col].astype(bool).to_dict()

    required = ["attack_sequence_id", "claimed_target_norad", "claimed_target_name", "attack_type", "attack_variant", "t_abs_utc"]
    missing = [c for c in required if c not in attack.columns]
    if missing:
        fail("attack dataset missing required columns: " + ", ".join(missing))

    rows: list[dict[str, Any]] = []
    for sequence_id, group in attack.groupby("attack_sequence_id", sort=True):
        group = group.sort_values("t_abs_utc")
        target_norad = str(group["claimed_target_norad"].iloc[0])
        if target_norad not in tle_entries:
            fail(f"target NORAD not found in TLE: {target_norad}")
        times = [parse_utc(v) for v in group["t_abs_utc"].astype(str)]
        a_start, a_end = times[0], times[-1]
        pad = float(args.search_padding_s)
        step = 1.0
        search_start = a_start - timedelta(seconds=pad)
        search_end = a_end + timedelta(seconds=pad)
        n_search = int((search_end - search_start).total_seconds() // step) + 1
        search_times = [search_start + timedelta(seconds=i * step) for i in range(n_search)]
        altitude_offset_km = numeric_param(group, "altitude_offset_km", 0.0)
        phase_offset_s = numeric_param(group, "phase_offset_s", 0.0)
        sat = tle_entries[target_norad]["sat"]
        elev_a = synthetic_elevation_deg(sat, station, ts, times, altitude_offset_km, phase_offset_s, times)
        elev_search = synthetic_elevation_deg(sat, station, ts, search_times, altitude_offset_km, phase_offset_s, times)
        visible_a = elev_a >= visible_mask
        visible_search = elev_search >= visible_mask
        b_first, b_last = contiguous_visible_window(search_times, visible_search)
        visible_fraction = float(np.mean(visible_a)) if len(visible_a) else np.nan
        overlap_fraction = visible_fraction
        rows.append(
            {
                "sequence_id": sequence_id,
                "target_sat_id": target_norad,
                "target_name": group["claimed_target_name"].iloc[0],
                "attack_type": group["attack_type"].iloc[0],
                "attack_param": group["attack_variant"].iloc[0],
                "A_window_start_utc": iso_z(a_start),
                "A_window_end_utc": iso_z(a_end),
                "B_visible_fraction_in_A_window": visible_fraction,
                "A_B_visibility_overlap_fraction": overlap_fraction,
                "B_first_visible_utc": iso_z(b_first),
                "B_last_visible_utc": iso_z(b_last),
                "pass_start_offset_s": (b_first - a_start).total_seconds() if b_first else np.nan,
                "pass_end_offset_s": (b_last - a_end).total_seconds() if b_last else np.nan,
                "B_min_elevation_deg_in_A_window": float(np.min(elev_a)),
                "B_max_elevation_deg_in_A_window": float(np.max(elev_a)),
                "B_mean_elevation_deg_in_A_window": float(np.mean(elev_a)),
                "visible_elevation_mask_deg": visible_mask,
                "accepted_score_only": bool(score_map.get(sequence_id, False)),
                "accepted_after_best_gate": bool(best_gate_map.get(sequence_id, False)),
                "best_gate_name": best_gate_col,
                "diagnostic_note": "synthetic B elevation uses same same-plane circular-orbit construction as verifier attack builder",
            }
        )
    diagnostic = pd.DataFrame(rows)
    summary_rows = []
    for (attack_type, attack_param), group in diagnostic.groupby(["attack_type", "attack_param"], dropna=False):
        summary_rows.append(
            {
                "attack_type": attack_type,
                "attack_param": attack_param,
                "total_sequences": int(len(group)),
                "mean_visible_fraction": float(group["B_visible_fraction_in_A_window"].mean()),
                "median_visible_fraction": float(group["B_visible_fraction_in_A_window"].median()),
                "mean_overlap_fraction": float(group["A_B_visibility_overlap_fraction"].mean()),
                "median_overlap_fraction": float(group["A_B_visibility_overlap_fraction"].median()),
                "mean_pass_start_offset_s": float(group["pass_start_offset_s"].mean()),
                "mean_pass_end_offset_s": float(group["pass_end_offset_s"].mean()),
                "min_B_max_elevation_deg": float(group["B_max_elevation_deg_in_A_window"].min()),
                "median_B_max_elevation_deg": float(group["B_max_elevation_deg_in_A_window"].median()),
                "max_B_max_elevation_deg": float(group["B_max_elevation_deg_in_A_window"].max()),
                "false_accept_count_score_only": int(group["accepted_score_only"].sum()),
                "false_accept_count_after_best_gate": int(group["accepted_after_best_gate"].sum()),
            }
        )
    summary = pd.DataFrame(summary_rows)
    diagnostic.to_csv(outputs[0], index=False)
    summary.to_csv(outputs[1], index=False)
    print(f"wrote {outputs[0]}")
    print(f"wrote {outputs[1]}")
    print(f"visibility mask: elevation >= {visible_mask} deg; best gate column: {best_gate_col}")


if __name__ == "__main__":
    main()
