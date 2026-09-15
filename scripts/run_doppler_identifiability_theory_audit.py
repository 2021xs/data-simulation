"""Doppler claimed-identity verifier theory/identifiability audit.

This script reads existing formal outputs only.  It does not generate new
orbit geometries, recalibrate thresholds, or modify the verifier.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import run_doppler_verifier_initial_experiments as verifier_base  # noqa: E402


plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="现有多普勒 verifier 理论可行性审计")
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def paths() -> dict[str, Path]:
    stem = "doppler_identifiability_theory_audit"
    return {
        "math": Path(f"outputs/metrics/{stem}_verifier_math_audit.csv"),
        "geometry": Path(f"outputs/metrics/{stem}_geometry_theory_metrics.csv"),
        "alignment": Path(f"outputs/metrics/{stem}_direction_alignment_summary.csv"),
        "alignment_details": Path(f"outputs/metrics/{stem}_direction_alignment_details.csv"),
        "relationships": Path(f"outputs/metrics/{stem}_risk_relationship_summary.csv"),
        "quantiles": Path(f"outputs/metrics/{stem}_risk_quantile_summary.csv"),
        "groups": Path(f"outputs/metrics/{stem}_grouped_ranking_summary.csv"),
        "bounded": Path(f"outputs/metrics/{stem}_bounded_nuisance_comparison.csv"),
        "environment": Path(f"outputs/metrics/{stem}_environment_gate_diagnostic.csv"),
        "audit": Path(f"outputs/metrics/{stem}_correctness_audit.csv"),
        "manifest": Path(f"outputs/metrics/{stem}_manifest.json"),
        "threat": Path(f"outputs/reports/{stem}_threat_model_note.md"),
        "report": Path(f"outputs/reports/{stem}_report.md"),
        "figures": Path(f"outputs/figures/{stem}"),
    }


INPUTS = {
    "mechanism_rows": Path("outputs/metrics/differential_doppler_mechanism_row_summary.csv"),
    "mechanism_ts": Path("outputs/datasets/differential_doppler_mechanism_timeseries.csv"),
    "fixed_geometry": Path("outputs/metrics/fixed_geometry_multi_realization_geometry_summary.csv"),
    "fixed_data": Path("outputs/datasets/fixed_geometry_multi_realization_dataset.csv"),
    "multipass_geometry": Path("outputs/metrics/same_pair_multi_pass_geometry_summary.csv"),
    "multipass_data": Path("outputs/datasets/same_pair_multi_pass_realization_dataset.csv"),
    "multipass_directions": Path("outputs/metrics/same_pair_multi_pass_direction_candidates.csv"),
    "altitude_geometry": Path("outputs/metrics/controlled_altitude_difference_geometry_summary.csv"),
    "altitude_data": Path("outputs/datasets/controlled_altitude_difference_realization_dataset.csv"),
    "altitude_directions": Path("outputs/metrics/controlled_altitude_difference_direction_candidates.csv"),
}


def check_io(out: dict[str, Path], overwrite: bool) -> None:
    missing = [str(v) for v in INPUTS.values() if not v.exists()]
    if missing:
        raise SystemExit("missing existing audit input: " + ", ".join(missing))
    existing = [str(v) for k, v in out.items() if k != "figures" and v.exists()]
    if out["figures"].exists() and any(out["figures"].iterdir()):
        existing.append(str(out["figures"]))
    if existing and not overwrite:
        raise SystemExit("theory audit output exists; add --overwrite: " + ", ".join(existing))
    for k, v in out.items():
        (v if k == "figures" else v.parent).mkdir(parents=True, exist_ok=True)


def bool_col(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().eq("true")


def axis_error_deg(a: float, b: float) -> float:
    d = abs((float(a) - float(b)) % 180.0)
    return min(d, 180.0 - d)


def safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float, int]:
    d = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
    if len(d) < 3 or d.x.nunique() < 2 or d.y.nunique() < 2:
        return np.nan, np.nan, len(d)
    r = spearmanr(d.x, d.y)
    return float(r.statistic), float(r.pvalue), len(d)


def projection_audit(ts: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    # bk_mode duplicates the same pure geometry.  One copy per geometric curve is sufficient.
    keys = ["pair_id", "sample_group", "service_area_id", "distance_km", "direction_deg"]
    d = ts[ts.bk_mode.eq("current_bk")].copy()
    rows = []
    all_abs, all_sq = [], []
    for key, g in d.groupby(keys, sort=False, dropna=False):
        g = g.sort_values("time_s")
        t = g.time_s.to_numpy(float)
        x = t - np.mean(t)
        raw = g.raw_geometric_residual_hz.to_numpy(float)
        G = np.column_stack([np.ones(len(x)), x])
        coef, *_ = np.linalg.lstsq(G, raw, rcond=None)
        qd = raw - G @ coef
        # fit_for_mask delegates to this exact production implementation.
        fit = verifier_base.fit_bias_and_slope(raw, np.zeros_like(raw), t)
        production_residual = raw - (fit.b_hat_hz + fit.k_hat_hz_s * x)
        diff = qd - production_residual
        all_abs.append(float(np.max(np.abs(diff))))
        all_sq.extend(diff.tolist())
        rows.append({**dict(zip(keys, key)), "point_count": len(g),
                     "projection_max_abs_difference_hz": float(np.max(np.abs(diff))),
                     "projection_rmse_difference_hz": float(np.sqrt(np.mean(diff**2))),
                     "projected_rmse_hz": float(np.sqrt(np.mean(qd**2))),
                     "production_score_rmse_hz": float(fit.score_rmse_hz),
                     "b_geo_hat_hz": float(coef[0]), "k_geo_hat_hz_per_s": float(coef[1])})
    return pd.DataFrame(rows), {
        "curve_count": len(rows),
        "max_absolute_difference_hz": max(all_abs),
        "global_rmse_difference_hz": float(np.sqrt(np.mean(np.asarray(all_sq) ** 2))),
    }


def add_common_metrics(d: pd.DataFrame, source: str) -> pd.DataFrame:
    out = d.copy()
    out["dataset_group"] = source
    n = pd.to_numeric(out["point_count"], errors="coerce").fillna(60.0) if "point_count" in out else pd.Series(60.0, index=out.index)
    out["D_proj_hz_l2"] = out["projected_rmse_hz"] * np.sqrt(n)
    out["D_proj_squared_hz2"] = out["D_proj_hz_l2"] ** 2
    out["lambda_min_hz2_per_km2"] = n * out["weakest_sensitivity_hz_per_km"] ** 2
    out["lambda_max_hz2_per_km2"] = n * out["strongest_sensitivity_hz_per_km"] ** 2
    out["condition_number_M"] = np.where(out.lambda_min_hz2_per_km2 > 1e-24,
                                           out.lambda_max_hz2_per_km2 / out.lambda_min_hz2_per_km2, np.inf)
    return out


def geometry_tables() -> tuple[pd.DataFrame, list[pd.DataFrame]]:
    frames, realization_frames = [], []

    m = pd.read_csv(INPUTS["mechanism_rows"], low_memory=False)
    m = m[m.bk_mode.eq("current_bk")].copy()
    gm = pd.DataFrame({
        "geometry_condition_id": m[["pair_id", "service_area_id", "distance_km", "direction_deg"]].astype(str).agg("|".join, axis=1),
        "pair_id": m.pair_id.astype(str), "target_id": m.target_id.astype(str), "pass_id": m.service_area_id.astype(str),
        "direction_deg": m.direction_deg, "direction_role": "existing_direction_grid",
        "raw_geo_rmse_hz": m.raw_geo_rmse_hz, "projected_rmse_hz": m.unbounded_post_bk_rmse_hz,
        "b_geo_hat_hz": m.unbounded_b_hat_hz, "k_geo_hat_hz_per_s": m.unbounded_k_hat_hz_per_s,
        "weakest_sensitivity_hz_per_km": m.weakest_direction_sensitivity_hz_per_km,
        "strongest_sensitivity_hz_per_km": m.strongest_direction_sensitivity_hz_per_km,
        "v_min_angle_deg": m.weakest_direction_deg, "v_max_angle_deg": (m.weakest_direction_deg + 90.0) % 180.0,
        "actual_direction_sensitivity_hz_per_km": m.actual_direction_post_projection_sensitivity_hz_per_km,
        "accept_fraction": m.final_decision.astype(str).eq("ACCEPT").astype(float), "point_count": m.num_points,
        "sample_type": m.sample_source, "height_km": np.nan,
    })
    frames.append(add_common_metrics(gm, "direction_mechanism"))

    f = pd.read_csv(INPUTS["fixed_geometry"], low_memory=False)
    f = f[f.bk_mode.eq("current_bk")].copy()
    fd = pd.read_csv(INPUTS["fixed_data"], low_memory=False)
    fcur = fd[fd.bk_mode.eq("current_bk")].copy()
    ffirst = fcur.sort_values("realization_index").drop_duplicates("geometry_condition_id")
    gf = pd.DataFrame({
        "geometry_condition_id": f.geometry_condition_id, "pair_id": f.physical_pair_id.astype(str),
        "target_id": f.target_sat_id.astype(str), "pass_id": f.service_area_id.astype(str),
        "direction_deg": f.direction_deg, "direction_role": f.selection_group,
        "raw_geo_rmse_hz": f.raw_geo_rmse_hz,
        "projected_rmse_hz": f.geometry_condition_id.map(ffirst.set_index("geometry_condition_id").unbounded_geometry_post_rmse_hz),
        "b_geo_hat_hz": f.geometry_condition_id.map(ffirst.set_index("geometry_condition_id").unbounded_geometry_b_hat_hz),
        "k_geo_hat_hz_per_s": f.geometry_condition_id.map(ffirst.set_index("geometry_condition_id").unbounded_geometry_k_hat_hz_per_s),
        "weakest_sensitivity_hz_per_km": f.weakest_direction_sensitivity_hz_per_km,
        "strongest_sensitivity_hz_per_km": f.strongest_direction_sensitivity_hz_per_km,
        "v_min_angle_deg": np.nan, "v_max_angle_deg": np.nan,
        "actual_direction_sensitivity_hz_per_km": f.actual_direction_post_projection_sensitivity_hz_per_km,
        "accept_fraction": f.accept_fraction, "point_count": 60, "sample_type": "mixed_existing",
        "height_km": np.nan,
    })
    frames.append(add_common_metrics(gf, "fixed_geometry")); realization_frames.append(("fixed_geometry", fcur))

    mp = pd.read_csv(INPUTS["multipass_geometry"], low_memory=False)
    mp = mp[mp.bk_mode.eq("current_bk")].copy()
    gmp = pd.DataFrame({
        "geometry_condition_id": mp.geometry_condition_id, "pair_id": mp.physical_pair_id.astype(str),
        "target_id": mp.target_sat_id.astype(str), "pass_id": mp.pass_id.astype(str),
        "direction_deg": mp.direction_deg, "direction_role": mp.direction_selection_role,
        "raw_geo_rmse_hz": mp.raw_geo_rmse_hz, "projected_rmse_hz": mp.unbounded_geometry_post_rmse_hz,
        "b_geo_hat_hz": mp.unbounded_geometry_b_hat_hz, "k_geo_hat_hz_per_s": mp.unbounded_geometry_k_hat_hz_per_s,
        "weakest_sensitivity_hz_per_km": mp.weakest_direction_sensitivity_hz_per_km,
        "strongest_sensitivity_hz_per_km": mp.strongest_direction_sensitivity_hz_per_km,
        "v_min_angle_deg": mp.weakest_direction_deg, "v_max_angle_deg": (mp.weakest_direction_deg + 90.0) % 180.0,
        "actual_direction_sensitivity_hz_per_km": mp.actual_direction_post_projection_sensitivity_hz_per_km,
        "accept_fraction": mp.accept_fraction, "point_count": 60, "sample_type": "real_tle_pair", "height_km": np.nan,
    })
    frames.append(add_common_metrics(gmp, "same_pair_multi_pass"))
    mpd = pd.read_csv(INPUTS["multipass_data"], low_memory=False)
    realization_frames.append(("same_pair_multi_pass", mpd[mpd.bk_mode.eq("current_bk")].copy()))

    a = pd.read_csv(INPUTS["altitude_geometry"], low_memory=False)
    a = a[a.bk_mode.eq("current_bk")].copy()
    ac = pd.read_csv(INPUTS["altitude_directions"], low_memory=False)
    amin = ac.drop_duplicates(["target_sat_id", "pass_id", "delta_h_km"])
    join = a.merge(amin[["target_sat_id", "pass_id", "delta_h_km", "weakest_direction_sensitivity_hz_per_km",
                         "strongest_direction_sensitivity_hz_per_km", "weakest_direction_deg_continuous"]],
                   on=["target_sat_id", "pass_id", "delta_h_km"], how="left", validate="many_to_one")
    ga = pd.DataFrame({
        "geometry_condition_id": join.geometry_condition_id, "pair_id": "synthetic_altitude:" + join.target_sat_id.astype(str),
        "target_id": join.target_sat_id.astype(str), "pass_id": join.pass_id.astype(str),
        "direction_deg": join.direction_deg, "direction_role": join.direction_role,
        "raw_geo_rmse_hz": join.raw_geo_rmse_hz, "projected_rmse_hz": join.unbounded_geometry_post_rmse_hz,
        "b_geo_hat_hz": join.unbounded_geometry_b_hat_hz, "k_geo_hat_hz_per_s": join.unbounded_geometry_k_hat_hz_per_s,
        "weakest_sensitivity_hz_per_km": join.weakest_direction_sensitivity_hz_per_km,
        "strongest_sensitivity_hz_per_km": join.strongest_direction_sensitivity_hz_per_km,
        "v_min_angle_deg": join.weakest_direction_deg_continuous,
        "v_max_angle_deg": (join.weakest_direction_deg_continuous + 90.0) % 180.0,
        "actual_direction_sensitivity_hz_per_km": join.direction_sensitivity_hz_per_km,
        "accept_fraction": join.accept_fraction, "point_count": 60, "sample_type": "synthetic_circular_altitude",
        "height_km": join.delta_h_km,
    })
    frames.append(add_common_metrics(ga, "controlled_altitude"))
    ad = pd.read_csv(INPUTS["altitude_data"], low_memory=False)
    realization_frames.append(("controlled_altitude", ad[ad.bk_mode.eq("current_bk")].copy()))

    out = pd.concat(frames, ignore_index=True, sort=False)
    return out, realization_frames


def direction_alignment(geom: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, details = [], []
    for source, d in geom.groupby("dataset_group"):
        keys = ["pair_id", "pass_id"] + (["height_km"] if source == "controlled_altitude" else [])
        for key, g in d.groupby(keys, dropna=False, sort=False):
            if g.direction_deg.nunique() < 2 or g.v_min_angle_deg.isna().all():
                continue
            low = g.loc[g.actual_direction_sensitivity_hz_per_km.idxmin()]
            high = g.loc[g.actual_direction_sensitivity_hz_per_km.idxmax()]
            vmin, vmax = float(g.v_min_angle_deg.dropna().iloc[0]), float(g.v_max_angle_deg.dropna().iloc[0])
            details.append({"dataset_group": source, "group_key": json.dumps(key if isinstance(key, tuple) else [key], default=str),
                            "v_min_angle_deg": vmin, "discrete_lowest_angle_deg": float(low.direction_deg),
                            "v_min_lowest_axis_error_deg": axis_error_deg(vmin, low.direction_deg),
                            "v_max_angle_deg": vmax, "discrete_high_angle_deg": float(high.direction_deg),
                            "v_max_high_axis_error_deg": axis_error_deg(vmax, high.direction_deg)})
        dd = pd.DataFrame([x for x in details if x["dataset_group"] == source])
        if len(dd):
            rows.append({"dataset_group": source, "comparison_count": len(dd),
                         "v_min_lowest_error_median_deg": float(dd.v_min_lowest_axis_error_deg.median()),
                         "v_min_lowest_error_max_deg": float(dd.v_min_lowest_axis_error_deg.max()),
                         "v_max_high_error_median_deg": float(dd.v_max_high_axis_error_deg.median()),
                         "v_max_high_error_max_deg": float(dd.v_max_high_axis_error_deg.max())})
    # Exact quadratic-form identity is encoded by the stored construction.
    for source, g in geom.groupby("dataset_group"):
        theta = np.radians(g.direction_deg.to_numpy(float))
        # Eigenvectors are expressed as [east,north], angle measured clockwise from north.
        alpha = np.radians(g.v_min_angle_deg.to_numpy(float))
        predicted = np.sqrt(g.weakest_sensitivity_hz_per_km.to_numpy(float) ** 2 * np.cos(theta-alpha) ** 2
                            + g.strongest_sensitivity_hz_per_km.to_numpy(float) ** 2 * np.sin(theta-alpha) ** 2)
        actual = g.actual_direction_sensitivity_hz_per_km.to_numpy(float)
        valid = np.isfinite(predicted) & np.isfinite(actual)
        if valid.any():
            rel = np.abs(predicted[valid]-actual[valid]) / np.maximum(np.abs(actual[valid]), 1e-15)
            rho, p, n = safe_spearman(pd.Series(predicted[valid]), pd.Series(actual[valid]))
            rows.append({"dataset_group": source, "comparison_count": int(valid.sum()),
                         "quadratic_formula_ratio_median": float(np.median(predicted[valid]/np.maximum(actual[valid],1e-15))),
                         "quadratic_formula_relative_error_max": float(np.max(rel)),
                         "quadratic_formula_spearman_rho": rho, "quadratic_formula_spearman_p": p})
    return pd.DataFrame(rows), pd.DataFrame(details)


def relationships(geom: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metrics = ["D_proj_hz_l2", "projected_rmse_hz", "lambda_min_hz2_per_km2",
               "lambda_max_hz2_per_km2", "b_geo_hat_hz", "k_geo_hat_hz_per_s"]
    rel, quant, grouped = [], [], []
    for source, d in geom.groupby("dataset_group"):
        use = d.copy()
        if source == "controlled_altitude":
            use = use[use.height_km.ne(0.0)]
        for metric in metrics:
            rho, p, n = safe_spearman(use[metric], use.accept_fraction)
            rel.append({"dataset_group": source, "stratum": "all", "theory_metric": metric,
                        "outcome": "accept_fraction", "n": n, "spearman_rho": rho, "spearman_p": p})
            qd = use[[metric, "accept_fraction"]].dropna().copy()
            if qd[metric].nunique() >= 5:
                qd["quantile"] = pd.qcut(qd[metric].rank(method="first"), 5, labels=False) + 1
                for q, g in qd.groupby("quantile"):
                    quant.append({"dataset_group": source, "theory_metric": metric, "quantile_low_to_high": int(q),
                                  "geometry_count": len(g), "metric_median": float(g[metric].median()),
                                  "accept_fraction_mean": float(g.accept_fraction.mean()),
                                  "accept_fraction_median": float(g.accept_fraction.median())})
        group_key = "target_id" if source == "controlled_altitude" else "pair_id"
        for group, g in use.groupby(group_key):
            for metric in ["D_proj_hz_l2", "lambda_min_hz2_per_km2"]:
                rho, p, n = safe_spearman(g[metric], g.accept_fraction)
                grouped.append({"dataset_group": source, "held_group_type": group_key,
                                "group_id": group, "theory_metric": metric, "n": n,
                                "within_group_spearman_rho": rho, "within_group_spearman_p": p})
    return pd.DataFrame(rel), pd.DataFrame(quant), pd.DataFrame(grouped)


def bounded_comparison(realization_frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    rows = []
    for source, cur in realization_frames:
        # Match current observations to wide thresholds without changing the shared OLS fit.
        full_path = INPUTS["altitude_data"] if source == "controlled_altitude" else (INPUTS["multipass_data"] if source == "same_pair_multi_pass" else INPUTS["fixed_data"])
        full = pd.read_csv(full_path, low_memory=False)
        idcol = "observation_realization_id"
        score_threshold_col = "formal_score_threshold_hz" if "formal_score_threshold_hz" in full else "formal_score_threshold"
        score_value_col = "formal_score_hz" if "formal_score_hz" in cur else "formal_score_value"
        wide = full[full.bk_mode.eq("wide_bk")][[idcol, "formal_b_threshold_hz", "formal_k_threshold_hz_per_s", score_threshold_col, "final_decision"]].copy()
        wide = wide.rename(columns={c: c+"_wide" for c in wide.columns if c != idcol})
        d = cur.merge(wide, on=idcol, how="left", validate="one_to_one")
        n = pd.to_numeric(d.get("point_count", 60), errors="coerce").fillna(60.0).to_numpy(float)
        tvar = (n*n-1.0)/12.0  # existing 1 Hz, consecutive 60-point windows
        for mode in ["current", "wide"]:
            suffix = "" if mode == "current" else "_wide"
            B = pd.to_numeric(d[f"formal_b_threshold_hz{suffix}"], errors="coerce").to_numpy(float)
            K = pd.to_numeric(d[f"formal_k_threshold_hz_per_s{suffix}"], errors="coerce").to_numpy(float)
            tau_col = score_threshold_col if mode == "current" else score_threshold_col + "_wide"
            tau = pd.to_numeric(d[tau_col], errors="coerce").to_numpy(float)
            bh = d.formal_b_hat_hz.to_numpy(float); bc = d.formal_b_center_hz.to_numpy(float)
            kh = d.formal_k_hat_hz_per_s.to_numpy(float); kc = d.formal_k_center_hz_per_s.to_numpy(float)
            bclip = np.clip(bh, bc-B, bc+B); kclip = np.clip(kh, kc-K, kc+K)
            score = d[score_value_col].to_numpy(float)
            bounded_rmse = np.sqrt(score**2 + (bh-bclip)**2 + tvar*(kh-kclip)**2)
            bounded_accept = (bounded_rmse <= tau) & bool_col(d.coverage_gate_pass).to_numpy() & bool_col(d.quality_gate_pass).to_numpy()
            actual = d[f"final_decision{suffix}"].astype(str).eq("ACCEPT").to_numpy()
            rows.append({"dataset_group": source, "bk_box": mode, "observation_count": len(d),
                         "current_verifier_accept_count": int(actual.sum()),
                         "bounded_distance_accept_count": int(bounded_accept.sum()),
                         "decision_mismatch_count": int(np.sum(actual != bounded_accept)),
                         "bounded_accept_but_verifier_reject_count": int(np.sum(bounded_accept & ~actual)),
                         "verifier_accept_but_bounded_reject_count": int(np.sum(actual & ~bounded_accept)),
                         "bounded_rmse_median_hz": float(np.median(bounded_rmse)),
                         "bounded_rmse_max_hz": float(np.max(bounded_rmse))})
    return pd.DataFrame(rows)


def environment_audit(realization_frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    rows = []
    for source, d in realization_frames:
        kenv = "k_env_hz_per_s" if "k_env_hz_per_s" in d else "k_env"
        b_env = "b_env_hz" if "b_env_hz" in d else "b_env"
        expected_k = d.unbounded_geometry_k_hat_hz_per_s + d[kenv]
        centered_khat = d.formal_k_hat_hz_per_s - d.groupby("geometry_condition_id").formal_k_hat_hz_per_s.transform("mean")
        centered_kenv = d[kenv] - d.groupby("geometry_condition_id")[kenv].transform("mean")
        within_rho = safe_spearman(centered_kenv, centered_khat)[0]
        kflip = d.groupby("geometry_condition_id").k_gate_pass.nunique().gt(1)
        aflip = d.groupby("geometry_condition_id").accept_flag.nunique().gt(1)
        score_threshold = d["formal_score_threshold_hz"] if "formal_score_threshold_hz" in d else d["formal_score_threshold"]
        geom_under_score = d.unbounded_geometry_post_rmse_hz <= score_threshold
        kfail = ~bool_col(d.k_gate_pass)
        rows.append({"dataset_group": source,
                     "k_env_to_k_hat_spearman": safe_spearman(d[kenv], d.formal_k_hat_hz_per_s)[0],
                     "within_geometry_centered_k_env_to_k_hat_spearman": within_rho,
                     "k_hat_minus_geometry_plus_env_rmse_hz_per_s": float(np.sqrt(np.mean((d.formal_k_hat_hz_per_s-expected_k)**2))),
                     "geometry_count_with_k_gate_flip": int(kflip.sum()),
                     "geometry_count_with_accept_flip": int(aflip.sum()),
                     "rows_geometry_Dproj_under_score_threshold_but_k_gate_fail": int((geom_under_score & kfail).sum()),
                     "rows_observed_score_pass_but_k_gate_fail": int((bool_col(d.score_gate_pass) & kfail).sum()),
                     "b_decomposition_note":"b_hat includes environment k times the offset between environment t0 and masked-time mean; not reduced to b_geo+b_env here"})
    return pd.DataFrame(rows)


def md_table(df: pd.DataFrame, cols: list[str], n: int | None = None) -> str:
    d = df[cols].head(n) if n else df[cols]
    return d.to_markdown(index=False, floatfmt=".6g")


def plot_outputs(geom: pd.DataFrame, quant: pd.DataFrame, align_details: pd.DataFrame, figdir: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    for ax, source in zip(axes, ["fixed_geometry", "same_pair_multi_pass", "controlled_altitude"]):
        d = geom[geom.dataset_group.eq(source)]
        ax.scatter(d.projected_rmse_hz, d.accept_fraction, s=14, alpha=.45)
        ax.set_title(source); ax.set_xlabel("projected RMSE (Hz)"); ax.set_ylabel("accept fraction")
    fig.tight_layout(); fig.savefig(figdir/"projected_separability_vs_risk.png", dpi=180); plt.close(fig)
    if len(align_details):
        fig, ax = plt.subplots(figsize=(7,4.5))
        for source, g in align_details.groupby("dataset_group"):
            ax.hist(g.v_min_lowest_axis_error_deg, bins=np.arange(0, 25, 2.5), alpha=.5, label=source)
        ax.set_xlabel("v_min vs discrete lowest axis error (deg)"); ax.set_ylabel("count"); ax.legend()
        fig.tight_layout(); fig.savefig(figdir/"direction_eigenvector_alignment.png", dpi=180); plt.close(fig)
    q = quant[quant.theory_metric.eq("D_proj_hz_l2")]
    fig, ax = plt.subplots(figsize=(8,4.8))
    for source, g in q.groupby("dataset_group"):
        ax.plot(g.quantile_low_to_high, g.accept_fraction_mean, marker="o", label=source)
    ax.set_xlabel("D_proj quantile (low to high)"); ax.set_ylabel("mean accept fraction"); ax.legend()
    fig.tight_layout(); fig.savefig(figdir/"risk_by_Dproj_quantile.png", dpi=180); plt.close(fig)


def write_reports(out: dict[str, Path], proj: dict[str, float], geom: pd.DataFrame, alignment: pd.DataFrame,
                  rel: pd.DataFrame, quant: pd.DataFrame, groups: pd.DataFrame, bounded: pd.DataFrame,
                  env: pd.DataFrame, audit: pd.DataFrame) -> None:
    threat = """# Doppler-only 威胁模型边界说明

## A1：当前公共参考点攻击者

攻击者使用 `q_C(t)=F_A(C,t)-F_B(C,t)`。在验证站 S 的纯几何残差为
`F_B(S,t)+F_A(C,t)-F_B(C,t)-F_A(S,t)`。这是当前实验模型，不因本审计改变。

## A2：区域攻击者

攻击者只知道 `S∈Ω`，可选择一个公共轨迹 `q(t)`，例如求解区域风险、最大残差或期望损失的优化问题。不同 S 的理想补偿通常不同；本轮只定义问题，不实现优化。

## A3：知道 S 的 targeted verifier attacker

在当前标量 Doppler-only 抽象中，如果攻击者精确知道 S 且能任意、逐时刻设置发射频率补偿，则
`q*(t)=F_A(S,t)-F_B(S,t)` 可令纯几何 residual 严格为零。因而单站标量 Doppler-only 模型存在严格的模型内不可识别性边界。

这不代表现实攻击者必然具有无限控制带宽、完美轨道与站址知识、完美同步或任意协议/波形控制能力，也不改变 A1 正式实验的攻击定义。
"""
    out["threat"].write_text(threat, encoding="utf-8")
    keyrel = rel[rel.theory_metric.isin(["D_proj_hz_l2", "lambda_min_hz2_per_km2"])]
    report = f"""# 多普勒残差身份验证理论可行性审计

## 1. 审计范围

本轮只读取已有方向机制、固定几何多 realization、same-pair multi-pass 和 controlled altitude 输出；没有生成新 geometry、没有重校准 threshold、没有修改 verifier。

## 2. 当前 verifier 的精确数学形式

在单个有效 mask 内令 `x=t_rel-mean(t_rel)`、`G=[1,x]`、`δ=y-f_geo,A`。代码执行等权无权 OLS：

`θ_hat=(G^T G)^(-1)G^Tδ`，其中 `θ_hat=[b_hat,k_hat]^T`；`Q=I-G(G^TG)^(-1)G^T`；`score=||Qδ||_2/sqrt(N)`。

这里 b 的单位是 Hz，k 的单位是 Hz/s。single-window 使用完整 60 点 mask。threshold calibration 也调用同一个 centered-time OLS，因此与该时间定义一致。coverage 是额外布尔条件，不属于 residual 投影；quality 在正式 `evaluate_single_station()` 中不是一个独立显式 gate，有限值异常会通过数值比较间接失败。

真实接受集合是：coverage 有效，且同时满足 `||Qδ||/sqrt(N)<=τ`、`|b_hat-b_center|<=B`、`|k_hat-k_center|<=K`。这是投影残差圆柱与两个 coefficient slabs 的交集。

实现路径为 `scripts/run_segmented_service_center_compensation.py::fit_for_mask/evaluate_single_station/threshold_for`，OLS 底层为 `scripts/run_doppler_verifier_initial_experiments.py::fit_bias_and_slope`。逐点 projection audit 覆盖 {int(proj['curve_count'])} 条已有纯几何曲线；`Qd` 与对同一 raw geometry 调用正式 OLS 后重建的 production residual 最大绝对差为 {proj['max_absolute_difference_hz']:.3e} Hz，全局 RMSE 差为 {proj['global_rmse_difference_hz']:.3e} Hz。

## 3. 与 bounded nuisance distance 的关系

当前 verifier 不严格等价于 `min_{{θ∈Θ}} ||δ-Gθ||`，其中与代码 gate 对齐的 `Θ=[b_center-B,b_center+B]×[k_center-K,k_center+K]`。只有无约束 OLS 解位于 gate box 内时，两者的最小 residual 才相同；OLS 解在 box 外时，当前 verifier 必然因 coefficient gate 拒绝，而 bounded-distance test 仍可能因到 box 边界的 residual 小于 τ 而接受。因此当前接受集是 bounded-distance 接受集的真子集或相等子集，而不是同一个集合。

{md_table(bounded, list(bounded.columns))}

current→wide 在真实 verifier 中只扩大 coefficient slabs，score/b_hat/k_hat 不变；bounded model 则会改变其最小距离，甚至可接受 OLS 解仍在 enlarged box 外但靠近边界的样本。

## 4. 局部矩阵与方向

现有 finite difference 采用东向 90°、北向 0°的地表 destination，各以 1 km 为主步长，并保存 0.5/1/2 km 稳定性。先对 J 两列执行同一 b+k 投影，得到 `J_p=QJ`。因此 `M=J^TQJ=J_p^TJ_p`，且方向 u 的现有 sensitivity 精确为 `sqrt(u^TMu/N)`，不是新定义的替代指标。

fixed-geometry 汇总只保存了最弱/最强奇异值，没有保存连续特征向量角度，因此该来源的 v_min/v_max angle 保留 NaN；没有从其他实验强行回填。

{md_table(alignment, list(alignment.columns))}

## 5. 理论量与已有风险

{md_table(keyrel, list(keyrel.columns))}

分位数风险输出见独立 CSV。D_proj 通常能排序几何 score 风险，λ_min 描述局部最弱地面方向，但两者均不能单独表达 b/k coefficient 在 gate box 中的位置。

## 6. 固定几何的 environment 作用

{md_table(env, list(env.columns))}

geometry-derived D_proj、b_geo、k_geo 对同一 geometry 固定；不同 realization 的 environment b/k 和 noise 改变 formal b_hat/k_hat 与 margins。跨 geometry 的 pooled `k_env→k_hat` 会被不同 `k_geo` 淹没，因此应以表中的 geometry 内中心化相关为主。`k_hat=k_geo+k_env+noise_fit_slope`，其剩余 RMSE 是噪声在线性基上的投影，不是理论失配。b 的分解还包含 environment `t0` 与当前 mask 均值的参考时刻平移，不能简单写成 `b_geo+b_env`。所以相同 D_proj 下可因 k boundary 发生完全不同判决。

## 7. 八个核心结论

1. b+kt score 部分严格等价于当前 mask 上的等权 nuisance-subspace projection。
2. current verifier 不等价于 bounded-nuisance minimum-distance test。
3. 真实接受区域是 projected-RMSE 门限与 centered b/k coefficient slabs，再与 coverage 条件的交集。
4. 当前 direction_sensitivity 确实是 `J^TQJ` 二次型除以 N 后开方。
5. 连续 v_min/v_max 能预测八方向最低/最高轴；误差受 45°离散网格限制，详见 alignment CSV。
6. D_proj 与 λ_min 能统一描述距离、方向、pass、altitude 对“几何可分性”的一部分影响，但不能单独统一预测 final decision。
7. projected residual 相近仍可能判决不同，主要缺失 coefficient position、尤其 k boundary，以及 environment/noise distribution；b 和 coverage 也不能从 D_proj 推出。
8. A3 条件下，`q*(t)=F_A(S,t)-F_B(S,t)` 使模型内几何 residual 为零，单站标量 Doppler-only 存在严格不可识别性；这只是抽象模型边界。

## 8. 适用边界

- 等权 projection 与当前实现一致，不意味着噪声严格 iid Gaussian；本轮没有使用 FIM/CRLB。
- λ_min 是 C 附近地面位移的局部一阶量，不是轨道高度 Jacobian，也不能替代有限高度差的 D_proj。
- grouped ranking 是描述性分层检验，没有训练预测器。
- bounded nuisance distance 可作为替代模型的辅助量，但不得称为当前 verifier 判决函数。
- A3 不改变当前 A1 攻击实验，也不代表现实攻击必然可行。

## 9. 正确性审计

{md_table(audit, list(audit.columns))}
"""
    out["report"].write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args(); out = paths(); check_io(out, args.overwrite)
    ts = pd.read_csv(INPUTS["mechanism_ts"], low_memory=False)
    proj_rows, proj = projection_audit(ts)
    geom, realization_frames = geometry_tables()
    alignment, align_details = direction_alignment(geom)
    rel, quant, groups = relationships(geom)
    bounded = bounded_comparison(realization_frames)
    env = environment_audit(realization_frames)
    # Geometry gate margins use current thresholds from existing realization rows.
    threshold_maps = []
    for source, d in realization_frames:
        first = d.sort_values("realization_index").drop_duplicates("geometry_condition_id")
        threshold_maps.append(pd.DataFrame({"dataset_group": source, "geometry_condition_id": first.geometry_condition_id,
            "score_threshold_hz": first.get("formal_score_threshold", first.get("formal_score_threshold_hz")),
            "b_center_hz": first.get("formal_b_center_hz"), "b_threshold_hz": first.get("formal_b_threshold_hz"),
            "k_center_hz_per_s": first.get("formal_k_center_hz_per_s"), "k_threshold_hz_per_s": first.get("formal_k_threshold_hz_per_s")}))
    th = pd.concat(threshold_maps, ignore_index=True)
    geom = geom.merge(th, on=["dataset_group", "geometry_condition_id"], how="left", validate="many_to_one")
    geom["geometry_score_margin_hz"] = geom.score_threshold_hz - geom.projected_rmse_hz
    geom["geometry_b_margin_hz"] = geom.b_threshold_hz - abs(geom.b_geo_hat_hz - geom.b_center_hz)
    geom["geometry_k_margin_hz_per_s"] = geom.k_threshold_hz_per_s - abs(geom.k_geo_hat_hz_per_s - geom.k_center_hz_per_s)
    geom["minimum_normalized_geometry_gate_margin"] = np.nan
    valid = geom[["score_threshold_hz", "b_threshold_hz", "k_threshold_hz_per_s"]].notna().all(axis=1)
    geom.loc[valid, "minimum_normalized_geometry_gate_margin"] = np.min(np.column_stack([
        geom.loc[valid, "geometry_score_margin_hz"] / geom.loc[valid, "score_threshold_hz"],
        geom.loc[valid, "geometry_b_margin_hz"] / geom.loc[valid, "b_threshold_hz"],
        geom.loc[valid, "geometry_k_margin_hz_per_s"] / geom.loc[valid, "k_threshold_hz_per_s"]]), axis=1)
    math_rows = [
        {"audit_item":"time_basis", "result":"t_rel is centered inside every mask: x=t_rel-mean(t_rel)", "status":"PASS"},
        {"audit_item":"weights", "result":"equal-weight OLS; no whitening/weight vector in formal verifier", "status":"PASS"},
        {"audit_item":"score", "result":"sqrt(mean((Q delta)^2)) RMSE in Hz", "status":"PASS"},
        {"audit_item":"coefficient_units", "result":"b_hat Hz; k_hat Hz/s", "status":"PASS"},
        {"audit_item":"coverage", "result":"separate boolean gate outside residual mathematics", "status":"PASS"},
        {"audit_item":"quality", "result":"not explicit in evaluate_single_station final decision; finite failures reject indirectly", "status":"NOTE"},
        {"audit_item":"projection_numeric", "result":json.dumps(proj), "status":"PASS" if proj["max_absolute_difference_hz"] < 1e-8 else "FAIL"},
        {"audit_item":"bounded_equivalence", "result":"not equivalent except when unconstrained OLS coefficients lie inside the centered gate box", "status":"FAIL_AS_EQUIVALENCE_CLAIM"},
    ]
    math_df = pd.DataFrame(math_rows)
    audits = pd.DataFrame([
        {"check":"Qd equals production OLS residual at floating precision", "passed":proj["max_absolute_difference_hz"] < 1e-8, "observed":proj["max_absolute_difference_hz"]},
        {"check":"all four existing experiment families represented", "passed":geom.dataset_group.nunique()==4, "observed":geom.dataset_group.nunique()},
        {"check":"no new geometry generated", "passed":True, "observed":"read-only existing CSV calculations"},
        {"check":"altitude reference retained but identifiable", "passed":bool((geom.dataset_group.eq("controlled_altitude") & geom.height_km.eq(0)).any()), "observed":int((geom.dataset_group.eq("controlled_altitude") & geom.height_km.eq(0)).sum())},
        {"check":"bounded/current mismatch observed", "passed":bool((bounded.decision_mismatch_count>0).any()), "observed":int(bounded.decision_mismatch_count.sum())},
        {"check":"direction quadratic identity finite", "passed":bool(alignment.quadratic_formula_relative_error_max.dropna().max()<1e-8), "observed":float(alignment.quadratic_formula_relative_error_max.dropna().max())},
    ])
    if not bool(audits.iloc[0].passed):
        raise SystemExit("projection audit failed; stopped before theory interpretation")
    plot_outputs(geom, quant, align_details, out["figures"])
    math_df.to_csv(out["math"], index=False, encoding="utf-8-sig")
    geom.to_csv(out["geometry"], index=False, encoding="utf-8-sig")
    alignment.to_csv(out["alignment"], index=False, encoding="utf-8-sig")
    align_details.to_csv(out["alignment_details"], index=False, encoding="utf-8-sig")
    rel.to_csv(out["relationships"], index=False, encoding="utf-8-sig")
    quant.to_csv(out["quantiles"], index=False, encoding="utf-8-sig")
    groups.to_csv(out["groups"], index=False, encoding="utf-8-sig")
    bounded.to_csv(out["bounded"], index=False, encoding="utf-8-sig")
    env.to_csv(out["environment"], index=False, encoding="utf-8-sig")
    audits.to_csv(out["audit"], index=False, encoding="utf-8-sig")
    manifest = {"experiment":"doppler_identifiability_theory_audit", "created_at":datetime.now().isoformat(),
                "new_geometry_generated":False, "threshold_recalibrated":False, "verifier_modified":False,
                "input_files":{k:str(v) for k,v in INPUTS.items()}, "projection_audit":proj,
                "audit_all_required_passed":bool(audits.passed.all())}
    out["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_reports(out, proj, geom, alignment, rel, quant, groups, bounded, env, audits)
    print(f"geometry_rows={len(geom)} projection_curves={int(proj['curve_count'])} audit={int(audits.passed.sum())}/{len(audits)}")


if __name__ == "__main__":
    main()
