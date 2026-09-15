#!/usr/bin/env python
"""Evaluate verifier v2 score and fitted-parameter gates.

This is a post-processing script.  It keeps the original score-only verifier
decision intact, then adds fitted b/k sanity gates for ablation.
"""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/metrics"))
    parser.add_argument("--legit-results", type=Path, default=None)
    parser.add_argument("--attack-results", type=Path, default=None)
    parser.add_argument("--legit-dataset", type=Path, default=None)
    parser.add_argument("--attack-dataset", type=Path, default=None)
    parser.add_argument("--thresholds", type=Path, default=None)
    parser.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    parser.add_argument("--threshold-type", choices=["p95", "p99", "both"], default="both")
    parser.add_argument("--global-k-min", type=float, default=None)
    parser.add_argument("--global-k-max", type=float, default=None)
    parser.add_argument("--per-target-quantile", nargs=2, type=float, default=[0.01, 0.99])
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        fail(f"{name} missing required columns: {', '.join(missing)}")


def default_path(args: argparse.Namespace, kind: str) -> Path:
    defaults = {
        "legit_results": args.input_dir / "metrics/doppler_verifier_module_boundary_regression_legitimate_score_results.csv",
        "attack_results": args.input_dir / "metrics/doppler_verifier_module_boundary_regression_attack_results.csv",
        "legit_dataset": args.input_dir / "datasets/doppler_verifier_module_boundary_regression_legitimate_dataset.csv",
        "attack_dataset": args.input_dir / "datasets/doppler_verifier_module_boundary_regression_attack_dataset.csv",
        "thresholds": args.input_dir / "metrics/doppler_verifier_module_boundary_regression_thresholds.csv",
    }
    return defaults[kind]


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        warnings.warn(f"parameter config not found: {path}")
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_global_ranges(args: argparse.Namespace) -> tuple[tuple[float, float] | None, tuple[float, float] | None, str]:
    cfg = read_yaml(args.parameter_config)
    params = cfg.get("parameters", {})
    source = str(args.parameter_config)
    k_range = None
    b_range = None
    if "k_hz_per_s" in params and "main_range" in params["k_hz_per_s"]:
        k_range = tuple(float(x) for x in params["k_hz_per_s"]["main_range"])
    if "b_hz" in params and "main_range" in params["b_hz"]:
        b_range = tuple(float(x) for x in params["b_hz"]["main_range"])
    if args.global_k_min is not None and args.global_k_max is not None:
        k_range = (float(args.global_k_min), float(args.global_k_max))
        source = "CLI --global-k-min/--global-k-max"
    return k_range, b_range, source


def bool_series(values: pd.Series) -> pd.Series:
    return values.astype(str).str.lower().isin(["true", "1", "yes"])


def sequence_windows(dataset: pd.DataFrame, id_col: str) -> pd.DataFrame:
    require_columns(dataset, [id_col, "t_abs_utc"], f"{id_col} dataset")
    grouped = dataset.groupby(id_col)
    out = grouped.agg(
        num_points=("t_abs_utc", "size"),
        window_start_utc=("t_abs_utc", "min"),
        window_end_utc=("t_abs_utc", "max"),
    ).reset_index()
    return out


def build_sequence_eval(
    legit: pd.DataFrame,
    attack: pd.DataFrame,
    legit_dataset: pd.DataFrame,
    attack_dataset: pd.DataFrame,
    thresholds: pd.DataFrame,
    threshold_types: list[str],
) -> pd.DataFrame:
    require_columns(legit, ["sequence_id", "target_name", "target_norad", "score_rmse_hz", "b_hat_hz", "k_hat_hz_s"], "legit results")
    require_columns(
        attack,
        [
            "attack_sequence_id",
            "claimed_target_name",
            "claimed_target_norad",
            "attack_type",
            "attack_variant",
            "score_A_rmse_hz",
            "threshold_95_hz",
            "threshold_99_hz",
            "accepted_95",
            "accepted_99",
            "b_hat_hz",
            "k_hat_hz_s",
        ],
        "attack results",
    )
    require_columns(thresholds, ["target_norad", "threshold_95_hz", "threshold_99_hz"], "thresholds")

    legit_windows = sequence_windows(legit_dataset, "sequence_id")
    attack_windows = sequence_windows(attack_dataset, "attack_sequence_id")
    th = thresholds[["target_norad", "threshold_95_hz", "threshold_99_hz"]].copy()
    th["target_norad"] = th["target_norad"].astype(str)

    rows: list[pd.DataFrame] = []
    legit = legit.copy()
    legit["target_norad"] = legit["target_norad"].astype(str)
    attack = attack.copy()
    attack["claimed_target_norad"] = attack["claimed_target_norad"].astype(str)
    legit_base = legit.merge(legit_windows, on="sequence_id", how="left").merge(th, on="target_norad", how="left")
    for threshold_type in threshold_types:
        threshold_col = "threshold_95_hz" if threshold_type == "p95" else "threshold_99_hz"
        part = pd.DataFrame(
            {
                "sequence_id": legit_base["sequence_id"],
                "target_sat_id": legit_base["target_norad"].astype(str),
                "target_name": legit_base["target_name"],
                "claimed_sat_id": legit_base["target_norad"].astype(str),
                "claimed_name": legit_base["target_name"],
                "attack_source_sat_id": "",
                "attack_source_name": "",
                "sample_type": "legit",
                "attack_type": "",
                "attack_param": "",
                "threshold_type": threshold_type,
                "score": legit_base["score_rmse_hz"].astype(float),
                "threshold": legit_base[threshold_col].astype(float),
                "accepted_score_only": legit_base["score_rmse_hz"].astype(float) <= legit_base[threshold_col].astype(float),
                "b_hat": legit_base["b_hat_hz"].astype(float),
                "k_hat": legit_base["k_hat_hz_s"].astype(float),
                "num_points": legit_base["num_points"],
                "window_start_utc": legit_base["window_start_utc"],
                "window_end_utc": legit_base["window_end_utc"],
            }
        )
        rows.append(part)

    attack_base = attack.merge(attack_windows, on="attack_sequence_id", how="left")
    for threshold_type in threshold_types:
        threshold_col = "threshold_95_hz" if threshold_type == "p95" else "threshold_99_hz"
        accepted_col = "accepted_95" if threshold_type == "p95" else "accepted_99"
        part = pd.DataFrame(
            {
                "sequence_id": attack_base["attack_sequence_id"],
                "target_sat_id": attack_base["claimed_target_norad"].astype(str),
                "target_name": attack_base["claimed_target_name"],
                "claimed_sat_id": attack_base["claimed_target_norad"].astype(str),
                "claimed_name": attack_base["claimed_target_name"],
                "attack_source_sat_id": "synthetic_same_plane_orbit",
                "attack_source_name": attack_base["attack_type"].astype(str) + "/" + attack_base["attack_variant"].astype(str),
                "sample_type": "attack",
                "attack_type": attack_base["attack_type"],
                "attack_param": attack_base["attack_variant"],
                "threshold_type": threshold_type,
                "score": attack_base["score_A_rmse_hz"].astype(float),
                "threshold": attack_base[threshold_col].astype(float),
                "accepted_score_only": bool_series(attack_base[accepted_col]),
                "b_hat": attack_base["b_hat_hz"].astype(float),
                "k_hat": attack_base["k_hat_hz_s"].astype(float),
                "num_points": attack_base["num_points"],
                "window_start_utc": attack_base["window_start_utc"],
                "window_end_utc": attack_base["window_end_utc"],
            }
        )
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def add_gate_columns(seq: pd.DataFrame, global_k_range: tuple[float, float] | None, global_b_range: tuple[float, float] | None) -> tuple[pd.DataFrame, dict[str, str]]:
    out = seq.copy()
    notes: dict[str, str] = {}
    out["accepted_score_plus_global_k"] = False
    if global_k_range is None:
        notes["score_plus_global_k_gate"] = "unavailable: no global_k_range"
    else:
        lo, hi = global_k_range
        out["accepted_score_plus_global_k"] = out["accepted_score_only"] & out["k_hat"].between(lo, hi, inclusive="both")
        notes["score_plus_global_k_gate"] = f"global_k_range=[{lo}, {hi}]"

    if global_b_range is None or global_k_range is None:
        out["accepted_score_plus_global_bk"] = False
        notes["score_plus_global_bk_gate"] = "unavailable: no trusted global b/k range"
    else:
        blo, bhi = global_b_range
        klo, khi = global_k_range
        out["accepted_score_plus_global_bk"] = (
            out["accepted_score_only"]
            & out["b_hat"].between(blo, bhi, inclusive="both")
            & out["k_hat"].between(klo, khi, inclusive="both")
        )
        notes["score_plus_global_bk_gate"] = f"global_b_range=[{blo}, {bhi}], global_k_range=[{klo}, {khi}]"

    for qlo, qhi, suffix in [(0.01, 0.99, "p01_p99"), (0.05, 0.95, "p05_p95")]:
        col_k = f"accepted_score_plus_per_target_k_{suffix}"
        col_bk = f"accepted_score_plus_per_target_bk_{suffix}"
        out[col_k] = False
        out[col_bk] = False
        legit = out[out["sample_type"] == "legit"]
        ranges = legit.groupby("target_sat_id").agg(
            k_lo=("k_hat", lambda s: float(s.quantile(qlo))),
            k_hi=("k_hat", lambda s: float(s.quantile(qhi))),
            b_lo=("b_hat", lambda s: float(s.quantile(qlo))),
            b_hi=("b_hat", lambda s: float(s.quantile(qhi))),
        )
        joined = out.join(ranges, on="target_sat_id")
        out[col_k] = out["accepted_score_only"] & joined["k_hat"].between(joined["k_lo"], joined["k_hi"], inclusive="both")
        out[col_bk] = (
            out["accepted_score_only"]
            & joined["k_hat"].between(joined["k_lo"], joined["k_hi"], inclusive="both")
            & joined["b_hat"].between(joined["b_lo"], joined["b_hi"], inclusive="both")
        )
        notes[f"score_plus_per_target_k_quantile_gate_{suffix}"] = f"per-target k_hat quantile [{qlo}, {qhi}] from legit samples"
        notes[f"score_plus_per_target_bk_quantile_gate_{suffix}"] = f"per-target b_hat/k_hat quantile [{qlo}, {qhi}] from legit samples"
    out["accepted_score_plus_per_target_bk"] = out["accepted_score_plus_per_target_bk_p01_p99"]
    return out, notes


def ablation_rows(seq: pd.DataFrame, gate_cols: dict[str, tuple[str, str]], notes: dict[str, str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    groups: list[tuple[str, pd.DataFrame]] = [("legit", seq[seq["sample_type"] == "legit"]), ("attack", seq[seq["sample_type"] == "attack"])]
    for attack_type, group in seq[seq["sample_type"] == "attack"].groupby("attack_type"):
        groups.append((f"attack_type:{attack_type}", group))
    for (threshold_type, th_df) in seq.groupby("threshold_type"):
        for gate_name, (col, quantile_setting) in gate_cols.items():
            for sample_group, group_all_th in groups:
                group = group_all_th[group_all_th["threshold_type"] == threshold_type]
                if group.empty:
                    continue
                accepted = int(group[col].sum())
                is_attack_group = sample_group.startswith("attack")
                rows.append(
                    {
                        "threshold_type": threshold_type,
                        "gate_name": gate_name,
                        "quantile_setting": quantile_setting,
                        "sample_group": sample_group,
                        "total_sequences": int(len(group)),
                        "accepted_sequences": accepted,
                        "rejected_sequences": int(len(group) - accepted),
                        "false_accepts_for_attack": accepted if is_attack_group else 0,
                        "false_accept_rate_for_attack": (accepted / len(group)) if is_attack_group else np.nan,
                        "legit_accept_rate": (accepted / len(group)) if sample_group == "legit" else np.nan,
                        "notes": notes.get(gate_name, ""),
                    }
                )
    return pd.DataFrame(rows)


def rejection_reason(row: pd.Series, col: str) -> str:
    if bool(row[col]):
        return "accepted"
    reasons = []
    if not bool(row["accepted_score_only"]):
        reasons.append("score_above_threshold")
    if "global_k" in col and not bool(row.get("accepted_score_plus_global_k", False)):
        reasons.append("k_hat_out_of_global_range")
    if "global_bk" in col and not bool(row.get("accepted_score_plus_global_bk", False)):
        reasons.append("b_hat_or_k_hat_out_of_global_range")
    if "per_target_k" in col:
        reasons.append("k_hat_out_of_per_target_quantile_range")
    if "per_target_bk" in col:
        reasons.append("b_hat_or_k_hat_out_of_per_target_quantile_range")
    return ";".join(dict.fromkeys(reasons)) or "rejected"


def false_accept_details(seq: pd.DataFrame) -> pd.DataFrame:
    fa = seq[(seq["sample_type"] == "attack") & (seq["accepted_score_only"])].copy()
    rows = []
    for _, row in fa.iterrows():
        reasons = {
            "global_k": rejection_reason(row, "accepted_score_plus_global_k"),
            "per_target_k_p01_p99": rejection_reason(row, "accepted_score_plus_per_target_k_p01_p99"),
            "per_target_k_p05_p95": rejection_reason(row, "accepted_score_plus_per_target_k_p05_p95"),
            "global_bk": rejection_reason(row, "accepted_score_plus_global_bk"),
            "per_target_bk": rejection_reason(row, "accepted_score_plus_per_target_bk"),
        }
        rows.append(
            {
                "threshold_type": row["threshold_type"],
                "sequence_id": row["sequence_id"],
                "target": f"{row['target_name']} / {row['target_sat_id']}",
                "attack_source": row["attack_source_name"],
                "attack_type": row["attack_type"],
                "attack_param": row["attack_param"],
                "score": row["score"],
                "threshold": row["threshold"],
                "b_hat": row["b_hat"],
                "k_hat": row["k_hat"],
                "accepted_score_only": row["accepted_score_only"],
                "accepted_score_plus_global_k": row["accepted_score_plus_global_k"],
                "accepted_score_plus_per_target_k_p01_p99": row["accepted_score_plus_per_target_k_p01_p99"],
                "accepted_score_plus_per_target_k_p05_p95": row["accepted_score_plus_per_target_k_p05_p95"],
                "accepted_score_plus_global_bk": row["accepted_score_plus_global_bk"],
                "accepted_score_plus_per_target_bk": row["accepted_score_plus_per_target_bk"],
                "rejection_reason_for_each_gate": json.dumps(reasons, ensure_ascii=False),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "legit_results": args.legit_results or default_path(args, "legit_results"),
        "attack_results": args.attack_results or default_path(args, "attack_results"),
        "legit_dataset": args.legit_dataset or default_path(args, "legit_dataset"),
        "attack_dataset": args.attack_dataset or default_path(args, "attack_dataset"),
        "thresholds": args.thresholds or default_path(args, "thresholds"),
    }
    for path in paths.values():
        if not path.exists():
            fail(f"input not found: {path}")
    outputs = [
        output_dir / "verifier_v2_sequence_eval.csv",
        output_dir / "verifier_v2_gate_ablation.csv",
        output_dir / "verifier_v2_false_accepts_detail.csv",
    ]
    if any(p.exists() for p in outputs) and not args.overwrite:
        fail("output exists; add --overwrite to replace verifier v2 post-processing outputs")

    threshold_types = ["p95", "p99"] if args.threshold_type == "both" else [args.threshold_type]
    legit = pd.read_csv(paths["legit_results"])
    attack = pd.read_csv(paths["attack_results"])
    legit_dataset = pd.read_csv(paths["legit_dataset"])
    attack_dataset = pd.read_csv(paths["attack_dataset"])
    thresholds = pd.read_csv(paths["thresholds"])
    seq = build_sequence_eval(legit, attack, legit_dataset, attack_dataset, thresholds, threshold_types)
    global_k_range, global_b_range, range_source = load_global_ranges(args)
    seq, notes = add_gate_columns(seq, global_k_range, global_b_range)
    notes["score_only"] = "score <= per-target threshold"
    notes["score_plus_global_k_gate"] = notes.get("score_plus_global_k_gate", "") + f"; range_source={range_source}"
    notes["score_plus_global_bk_gate"] = notes.get("score_plus_global_bk_gate", "") + f"; range_source={range_source}"

    gate_cols = {
        "score_only": ("accepted_score_only", ""),
        "score_plus_global_k_gate": ("accepted_score_plus_global_k", ""),
        "score_plus_per_target_k_quantile_gate": ("accepted_score_plus_per_target_k_p01_p99", "p01-p99"),
        "score_plus_per_target_k_quantile_gate_p05_p95": ("accepted_score_plus_per_target_k_p05_p95", "p05-p95"),
        "score_plus_global_bk_gate": ("accepted_score_plus_global_bk", ""),
        "score_plus_per_target_bk_quantile_gate": ("accepted_score_plus_per_target_bk", "p01-p99"),
    }
    ablation = ablation_rows(seq, gate_cols, notes)
    fa = false_accept_details(seq)

    seq.to_csv(outputs[0], index=False)
    ablation.to_csv(outputs[1], index=False)
    fa.to_csv(outputs[2], index=False)
    print(f"wrote {outputs[0]}")
    print(f"wrote {outputs[1]}")
    print(f"wrote {outputs[2]}")
    print(f"attack sequences: {seq[(seq.sample_type == 'attack') & (seq.threshold_type == threshold_types[0])]['sequence_id'].nunique()}")
    for th in threshold_types:
        score_only_fa = seq[(seq["sample_type"] == "attack") & (seq["threshold_type"] == th) & (seq["accepted_score_only"])]
        global_k_fa = seq[(seq["sample_type"] == "attack") & (seq["threshold_type"] == th) & (seq["accepted_score_plus_global_k"])]
        print(f"{th}: score-only false accepts={len(score_only_fa)}, after global k={len(global_k_fa)}")


if __name__ == "__main__":
    main()
