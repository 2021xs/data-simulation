#!/usr/bin/env python
"""Select and diagnose verifier v2 fine-sweep hard cases."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from skyfield.api import load, wgs84

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_doppler_verifier_initial_experiments as base  # noqa: E402

ALTITUDE_DELTAS_KM = [-10, -7.5, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 7.5, 10]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--fine-sweep-eval", type=Path, default=Path("outputs/metrics/verifier_v2_altitude_fine_sweep_sequence_eval.csv"))
    p.add_argument("--selection-output", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_selected_pairs.csv"))
    p.add_argument("--forensic-summary", type=Path, default=Path("outputs/metrics/verifier_v2_hard_case_forensic_summary.csv"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures/verifier_v2_hard_case_forensics"))
    p.add_argument("--selection-table", type=Path, default=Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"))
    p.add_argument("--candidate-library", type=Path, default=Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"))
    p.add_argument("--tle-file", type=Path, default=Path("data/tle/starlink_tle.txt"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--seed", type=int, default=20260519)
    p.add_argument("--num-sims-per-case", type=int, default=5)
    p.add_argument("--threshold-type", choices=["p95", "p99"], default="p95")
    p.add_argument("--top-n", type=int, default=10)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def select_hard_cases(path: Path, threshold_type: str) -> pd.DataFrame:
    if not path.exists():
        fail(f"fine sweep eval not found: {path}")
    df = pd.read_csv(path)
    sel = df[
        (df["threshold_type"] == threshold_type)
        & (df["attack_type"] == "same_plane_altitude_offset_fine")
        & (df["attack_param_value"].isin([-1.0, -2.0]))
        & (df["accepted_per_target_k_p01_p99"].astype(bool))
    ].copy()
    if sel.empty:
        fail("no selected hard cases found")
    sel["delta_h_km"] = sel["attack_param_value"].astype(float)
    sel["distance_to_k_range_edge"] = np.minimum(
        (sel["k_hat"] - sel["target_k_min_p01"]).abs(),
        (sel["target_k_max_p99"] - sel["k_hat"]).abs(),
    )
    cols = [
        "sequence_id",
        "target_sat_id",
        "target_name",
        "attack_source_sat_id",
        "attack_source_name",
        "delta_h_km",
        "threshold_type",
        "score",
        "threshold",
        "normalized_score",
        "b_hat",
        "k_hat",
        "target_k_min_p01",
        "target_k_max_p99",
        "distance_to_k_range_edge",
        "num_points",
        "window_start_utc",
        "window_end_utc",
    ]
    return sel[cols].sort_values("normalized_score").reset_index(drop=True)


def load_inputs(args: argparse.Namespace):
    loader_args = SimpleNamespace(
        selection_table=args.selection_table,
        candidate_library=args.candidate_library,
        tle_file=args.tle_file,
        orbit_config=args.orbit_config,
        parameter_config=args.parameter_config,
        target_count=20,
    )
    selection, library, orbit_cfg, ranges = base.load_inputs(loader_args)
    ts = load.timescale()
    tle_entries = base.parse_tle(args.tle_file, ts)
    return selection, library, orbit_cfg, ranges, tle_entries


def target_index(selection: pd.DataFrame, target_norad: str) -> int:
    ids = [str(v) for v in selection["target_norad_id"]]
    return ids.index(str(target_norad))


def regenerate_case(args: argparse.Namespace, selected_row: pd.Series, selection, library, orbit_cfg, ranges, tle_entries):
    target_norad = str(selected_row["target_sat_id"])
    seq_id = str(selected_row["sequence_id"])
    match = re.search(r"(\d+)$", seq_id)
    seq_num = int(match.group(1)) if match else None
    ts = load.timescale()
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    rng = np.random.default_rng(args.seed)
    counter = 1
    for _, target in selection.iterrows():
        tn = str(target["target_norad_id"])
        geo = base.target_geo_from_library(library, tn)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
        sat = tle_entries[tn]["sat"]
        for dh in ALTITUDE_DELTAS_KM:
            f_geo_b = base.synthetic_same_plane_geo(sat, station, ts, times, freq, altitude_offset_km=float(dh), phase_offset_s=0.0)
            for sample_id in range(1, args.num_sims_per_case + 1):
                err = base.sample_error_params(ranges, rng)
                current_id = f"alt_fine_{counter:06d}"
                counter += 1
                spec = {
                    "attack_type": "same_plane_altitude_offset_fine",
                    "attack_variant": f"delta_h_{dh:+g}km",
                    "altitude_offset_km": float(dh),
                    "phase_offset_s": 0.0,
                    "inclination_offset_deg": 0.0,
                    "raan_offset_deg": 0.0,
                }
                obs = base.build_attack_observation(current_id, str(target["target_name"]), tn, geo, f_geo_b, spec, err, rng, sample_id, args.seed)
                if current_id == seq_id:
                    return geo, obs, f_geo_a, f_geo_b
    fail(f"failed to regenerate {seq_id}")


def regenerate_cases(args: argparse.Namespace, selected_ids: set[str], selection, library, orbit_cfg, ranges, tle_entries):
    ts = load.timescale()
    station_cfg = orbit_cfg["station"]
    station = wgs84.latlon(float(station_cfg["lat_deg"]), float(station_cfg["lon_deg"]), elevation_m=float(station_cfg["alt_m"]))
    freq = float(library["center_freq_hz"].iloc[0]) if "center_freq_hz" in library.columns else float(orbit_cfg.get("ku_band_experiment", {}).get("simulation_center_freq_hz", 11_325_000_000))
    rng = np.random.default_rng(args.seed)
    counter = 1
    out = {}
    for _, target in selection.iterrows():
        tn = str(target["target_norad_id"])
        geo = base.target_geo_from_library(library, tn)
        times = [base.parse_utc(v) for v in geo["t_abs_utc"].astype(str)]
        f_geo_a = geo["f_geo_candidate_hz"].to_numpy(float)
        sat = tle_entries[tn]["sat"]
        for dh in ALTITUDE_DELTAS_KM:
            f_geo_b = base.synthetic_same_plane_geo(sat, station, ts, times, freq, altitude_offset_km=float(dh), phase_offset_s=0.0)
            for sample_id in range(1, args.num_sims_per_case + 1):
                err = base.sample_error_params(ranges, rng)
                current_id = f"alt_fine_{counter:06d}"
                counter += 1
                spec = {
                    "attack_type": "same_plane_altitude_offset_fine",
                    "attack_variant": f"delta_h_{dh:+g}km",
                    "altitude_offset_km": float(dh),
                    "phase_offset_s": 0.0,
                    "inclination_offset_deg": 0.0,
                    "raan_offset_deg": 0.0,
                }
                obs = base.build_attack_observation(current_id, str(target["target_name"]), tn, geo, f_geo_b, spec, err, rng, sample_id, args.seed)
                if current_id in selected_ids:
                    out[current_id] = (geo, obs, f_geo_a, f_geo_b)
                    if len(out) == len(selected_ids):
                        return out
    return out


def plot_case(row: pd.Series, geo: pd.DataFrame, obs, f_geo_a: np.ndarray, f_geo_b: np.ndarray, out: Path) -> dict[str, float]:
    t = obs.t_rel_s.astype(float)
    x = t - float(np.mean(t))
    y = obs.y_obs_hz
    delta = y - f_geo_a
    design = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    fitted = design @ coef
    residual = delta - fitted
    rmse = float(np.sqrt(np.mean(residual * residual)))
    trend = float(np.polyfit(x, residual, 1)[0]) if len(x) > 1 else 0.0
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    axes[0].plot(t, f_geo_a, label="f_geo_A claimed", linewidth=1.6)
    axes[0].plot(t, f_geo_b, label="f_geo_B attack", linewidth=1.4)
    axes[0].plot(t, y, label="y_B observation", linewidth=1.1, alpha=0.85)
    axes[0].set_ylabel("frequency (Hz)")
    axes[0].legend()
    axes[0].grid(True, alpha=0.25)
    axes[1].plot(t, delta, label="delta = y_B - f_geo_A")
    axes[1].plot(t, fitted, "--", label=f"fit b+k, k={coef[1]:.4f}")
    axes[1].set_ylabel("delta / fit (Hz)")
    axes[1].legend()
    axes[1].grid(True, alpha=0.25)
    axes[2].plot(t, residual, label=f"residual, RMSE={rmse:.3f} Hz")
    axes[2].axhline(0, color="black", linewidth=1)
    axes[2].set_xlabel("t_rel_s")
    axes[2].set_ylabel("residual (Hz)")
    axes[2].legend()
    axes[2].grid(True, alpha=0.25)
    fig.suptitle(f"{row['target_name']} {row['sequence_id']} delta_h={row['delta_h_km']} km norm={row['normalized_score']:.3f}")
    fig.tight_layout()
    fig.savefig(out, dpi=170)
    plt.close(fig)
    return {
        "residual_mean": float(np.mean(residual)),
        "residual_std": float(np.std(residual, ddof=0)),
        "residual_max_abs": float(np.max(np.abs(residual))),
        "residual_trend_after_fit": trend,
    }


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


def main() -> None:
    args = parse_args()
    outs = [args.selection_output, args.forensic_summary]
    if any(p.exists() for p in outs) and not args.overwrite:
        fail("outputs exist; add --overwrite")
    args.selection_output.parent.mkdir(parents=True, exist_ok=True)
    args.figures_dir.mkdir(parents=True, exist_ok=True)
    selected = select_hard_cases(args.fine_sweep_eval, args.threshold_type)
    selected.to_csv(args.selection_output, index=False)
    selection, library, orbit_cfg, ranges, tle_entries = load_inputs(args)
    diag_ids = pd.concat(
        [
            selected.sort_values("normalized_score").head(args.top_n),
            selected.assign(dist=(selected["normalized_score"] - 1).abs()).sort_values("dist").head(args.top_n),
        ]
    ).drop_duplicates("sequence_id")
    rows = []
    regenerated = regenerate_cases(args, set(diag_ids["sequence_id"].astype(str)), selection, library, orbit_cfg, ranges, tle_entries)
    for _, row in diag_ids.iterrows():
        geo, obs, f_geo_a, f_geo_b = regenerated[str(row["sequence_id"])]
        fname = safe_name(f"{row['target_name']}_{row['attack_source_name']}_dh{row['delta_h_km']}_{row['sequence_id']}.png")
        stats = plot_case(row, geo, obs, f_geo_a, f_geo_b, args.figures_dir / fname)
        rows.append(
            {
                "sequence_id": row["sequence_id"],
                "target": f"{row['target_name']} / {row['target_sat_id']}",
                "attack_source": row["attack_source_name"],
                "delta_h_km": row["delta_h_km"],
                "normalized_score": row["normalized_score"],
                "b_hat": row["b_hat"],
                "k_hat": row["k_hat"],
                **stats,
                "notes": "low score after b+k fit; inspect residual trend and k range edge distance",
            }
        )
    pd.DataFrame(rows).to_csv(args.forensic_summary, index=False)
    print(f"wrote {args.selection_output} rows={len(selected)}")
    print(f"wrote {args.forensic_summary} rows={len(rows)}")


if __name__ == "__main__":
    main()
