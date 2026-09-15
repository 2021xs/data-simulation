#!/usr/bin/env python
"""Plot a simplified Figure 2 for the subpoint compensation failure case.

The script only reads existing experiment outputs. It keeps the representative
sample selection and summary statistics in the notes file, while the figure
itself is reduced to one group-meeting-ready message.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SEQ_PATH = Path("outputs/metrics/active_compensation_first_pass_sequence_eval.csv")
DATASET_PATH = Path("outputs/datasets/active_compensation_first_pass_dataset.csv")
PAIRWISE_PATH = Path("outputs/metrics/active_compensation_first_pass_pairwise_compare.csv")
FIGURE_PATH = Path("outputs/charts/figure2_subpoint_failure_evidence.png")
NOTES_PATH = Path("outputs/charts/figure2_subpoint_failure_evidence_notes.md")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sequence-eval", type=Path, default=SEQ_PATH)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--pairwise", type=Path, default=PAIRWISE_PATH)
    parser.add_argument("--figure-output", type=Path, default=FIGURE_PATH)
    parser.add_argument("--notes-output", type=Path, default=NOTES_PATH)
    return parser.parse_args()


def setup_chinese_font() -> None:
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def read_csv_if_possible(path: Path, **kwargs: Any) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size <= 2:
        return None
    try:
        return pd.read_csv(path, **kwargs)
    except pd.errors.EmptyDataError:
        return None


def require_columns(df: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise SystemExit(f"{name} 缺少必要字段: {', '.join(missing)}")


def build_pairwise_from_sequence(seq: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    required = [
        "target_id",
        "target_name",
        "attacker_id",
        "attacker_name",
        "pass_start_utc",
        "pass_end_utc",
        "residual_mode",
        "reference_mode",
        "compensation_type",
        "score_A_rmse_hz",
        "attack_delta_rmse_hz",
        "accepted_p95",
        "tri_state_decision",
    ]
    require_columns(seq, required, "sequence_eval")

    sub = seq[
        (seq["reference_mode"].astype(str) == "subpoint_A")
        & (seq["compensation_type"].astype(str).isin(["none", "subpoint_A"]))
    ].copy()
    if sub.empty:
        return pd.DataFrame(), "sequence_eval 中没有可配对的 subpoint_A / none 样本"

    modes = set(sub["residual_mode"].astype(str))
    mode = "empirical" if "empirical" in modes else sorted(modes)[0]
    sub = sub[sub["residual_mode"].astype(str) == mode].copy()

    keys = [
        "target_id",
        "target_name",
        "attacker_id",
        "attacker_name",
        "pass_start_utc",
        "pass_end_utc",
        "residual_mode",
    ]
    none = sub[sub["compensation_type"].astype(str) == "none"]
    subpoint = sub[sub["compensation_type"].astype(str) == "subpoint_A"]
    merged = none.merge(subpoint, on=keys, suffixes=("_none", "_subpoint"))
    if merged.empty:
        return pd.DataFrame(), f"在 residual_mode={mode} 下无法配对 none 与 subpoint_A"

    out = pd.DataFrame(
        {
            "target_id": merged["target_id"],
            "target_name": merged["target_name"],
            "attacker_id": merged["attacker_id"],
            "attacker_name": merged["attacker_name"],
            "pass_start_utc": merged["pass_start_utc"],
            "pass_end_utc": merged["pass_end_utc"],
            "residual_mode": merged["residual_mode"],
            "none_score_hz": merged["score_A_rmse_hz_none"].astype(float),
            "subpoint_score_hz": merged["score_A_rmse_hz_subpoint"].astype(float),
            "none_attack_delta_rmse_hz": merged["attack_delta_rmse_hz_none"].astype(float),
            "subpoint_attack_delta_rmse_hz": merged["attack_delta_rmse_hz_subpoint"].astype(float),
            "subpoint_p95_accept": merged["accepted_p95_subpoint"],
            "subpoint_tri_state_decision": merged["tri_state_decision_subpoint"].astype(str),
            "subpoint_sequence_id": merged.get("sequence_id_subpoint", pd.Series([""] * len(merged))),
        }
    )
    out["score_improvement_ratio"] = (out["none_score_hz"] - out["subpoint_score_hz"]) / out[
        "none_score_hz"
    ]
    out["attack_delta_improvement_ratio"] = (
        out["none_attack_delta_rmse_hz"] - out["subpoint_attack_delta_rmse_hz"]
    ) / out["none_attack_delta_rmse_hz"]
    return out, f"pairwise 文件不可用，已从 sequence_eval 自动配对；residual_mode={mode}"


def load_pairwise(seq: pd.DataFrame, pairwise_path: Path) -> tuple[pd.DataFrame, str]:
    pairwise = read_csv_if_possible(pairwise_path)
    needed = [
        "residual_mode",
        "none_score_hz",
        "subpoint_score_hz",
        "none_attack_delta_rmse_hz",
        "subpoint_attack_delta_rmse_hz",
        "score_improvement_ratio",
        "attack_delta_improvement_ratio",
        "subpoint_p95_accept",
        "subpoint_tri_state_decision",
    ]
    if pairwise is not None and all(col in pairwise.columns for col in needed):
        modes = set(pairwise["residual_mode"].astype(str))
        mode = "empirical" if "empirical" in modes else sorted(modes)[0]
        return pairwise[pairwise["residual_mode"].astype(str) == mode].copy(), (
            f"使用 pairwise 文件 `{pairwise_path}`；residual_mode={mode}"
        )
    return build_pairwise_from_sequence(seq)


def choose_representative(pairwise: pd.DataFrame) -> pd.Series:
    candidates = pairwise[
        (pairwise["attack_delta_improvement_ratio"] > 0)
        & (pairwise["score_improvement_ratio"] <= 0)
        & (pairwise["subpoint_tri_state_decision"].astype(str) != "ACCEPT")
    ].copy()
    if candidates.empty:
        candidates = pairwise[
            (pairwise["attack_delta_improvement_ratio"] > 0)
            & (pairwise["subpoint_tri_state_decision"].astype(str) != "ACCEPT")
        ].copy()
    if candidates.empty:
        candidates = pairwise.copy()
    candidates["selection_score"] = candidates["attack_delta_improvement_ratio"].fillna(0) - candidates[
        "score_improvement_ratio"
    ].fillna(0)
    return candidates.sort_values("selection_score", ascending=False).iloc[0]


def locate_sequence_id(seq: pd.DataFrame, rep: pd.Series) -> str:
    if "subpoint_sequence_id" in rep and pd.notna(rep["subpoint_sequence_id"]):
        seq_id = str(rep["subpoint_sequence_id"])
        if seq_id and seq_id.lower() != "nan":
            return seq_id

    candidates = seq[
        (seq["target_id"].astype(str) == str(rep["target_id"]))
        & (seq["attacker_id"].astype(str) == str(rep["attacker_id"]))
        & (seq["pass_start_utc"].astype(str) == str(rep["pass_start_utc"]))
        & (seq["residual_mode"].astype(str) == str(rep["residual_mode"]))
        & (seq["reference_mode"].astype(str) == "subpoint_A")
        & (seq["compensation_type"].astype(str) == "subpoint_A")
    ]
    if candidates.empty:
        return ""
    return str(candidates.iloc[0]["sequence_id"])


def write_missing_outputs(args: argparse.Namespace, notes: list[str], message: str) -> None:
    setup_chinese_font()
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.axis("off")
    ax.text(0.5, 0.58, "星下点补偿导致时变空间失配", ha="center", fontsize=18, fontweight="bold")
    ax.text(0.5, 0.43, message, ha="center", fontsize=12.5, linespacing=1.6)
    args.figure_output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.figure_output, dpi=240, bbox_inches="tight")
    plt.close(fig)
    args.notes_output.parent.mkdir(parents=True, exist_ok=True)
    args.notes_output.write_text("\n".join(notes + ["", "## 未生成正式图", f"- {message}"]), encoding="utf-8")


def main() -> None:
    args = parse_args()
    setup_chinese_font()

    notes: list[str] = ["# 图2 星下点补偿失败证据图说明", "", "## 输入检查"]
    seq = read_csv_if_possible(args.sequence_eval)
    if seq is None:
        write_missing_outputs(args, notes, f"缺少 sequence_eval: {args.sequence_eval}")
        return
    notes.append(f"- sequence_eval: `{args.sequence_eval}`，行数 `{len(seq)}`。")
    notes.append(f"- sequence_eval 字段: `{', '.join(seq.columns)}`。")

    data_head = read_csv_if_possible(args.dataset, nrows=5)
    if data_head is None:
        write_missing_outputs(args, notes, f"缺少 dataset: {args.dataset}")
        return
    notes.append(f"- dataset: `{args.dataset}`。")
    notes.append(f"- dataset 字段: `{', '.join(data_head.columns)}`。")

    try:
        pairwise, pairwise_note = load_pairwise(seq, args.pairwise)
    except SystemExit as exc:
        write_missing_outputs(args, notes, str(exc))
        return
    notes.append(f"- {pairwise_note}。")
    if pairwise.empty:
        refs = sorted(seq["reference_mode"].dropna().astype(str).unique()) if "reference_mode" in seq.columns else []
        comps = (
            sorted(seq["compensation_type"].dropna().astype(str).unique())
            if "compensation_type" in seq.columns
            else []
        )
        write_missing_outputs(
            args,
            notes + [f"- 当前 reference_mode: `{refs}`。", f"- 当前 compensation_type: `{comps}`。"],
            "当前 CSV 中没有可配对的 subpoint_A / none 样本；未重跑主实验。",
        )
        return

    raw_imp = pairwise["attack_delta_improvement_ratio"] > 0
    score_imp = pairwise["score_improvement_ratio"] > 0
    raw_not_score = raw_imp & ~score_imp
    accept_count = int(pairwise["subpoint_p95_accept"].astype(bool).sum())
    defer_count = int((pairwise["subpoint_tri_state_decision"].astype(str) == "DEFER").sum())

    rep = choose_representative(pairwise)
    seq_id = locate_sequence_id(seq, rep)
    if not seq_id:
        write_missing_outputs(args, notes, "无法定位代表性样本 sequence_id。")
        return

    rep_seq = seq[seq["sequence_id"].astype(str) == seq_id]
    if rep_seq.empty:
        write_missing_outputs(args, notes, f"sequence_eval 中找不到代表性样本 `{seq_id}`。")
        return
    rep_seq_row = rep_seq.iloc[0]

    dataset_cols = [
        "sequence_id",
        "t_rel_s",
        "f_geo_A_S_hz",
        "f_attack_hz",
        "delta_to_claimed_hz",
        "C_S_distance_km",
    ]
    curve_data = pd.read_csv(args.dataset, usecols=lambda col: col in dataset_cols)
    curve = curve_data[curve_data["sequence_id"].astype(str) == seq_id].copy()
    if curve.empty:
        write_missing_outputs(args, notes, f"dataset 中找不到代表性样本 `{seq_id}`。")
        return
    require_columns(curve, ["t_rel_s", "C_S_distance_km"], "dataset representative curve")

    t = curve["t_rel_s"].to_numpy(float)
    if "delta_to_claimed_hz" in curve.columns:
        delta = curve["delta_to_claimed_hz"].to_numpy(float)
        delta_source = "delta_to_claimed_hz"
    else:
        require_columns(curve, ["f_attack_hz", "f_geo_A_S_hz"], "dataset representative curve")
        delta = curve["f_attack_hz"].to_numpy(float) - curve["f_geo_A_S_hz"].to_numpy(float)
        delta_source = "f_attack_hz - f_geo_A_S_hz"

    b_hat = float(rep_seq_row["b_hat_hz"])
    k_hat = float(rep_seq_row["k_hat_hz_s"])
    t0 = float(np.mean(t))
    residual = delta - (b_hat + k_hat * (t - t0))
    distance = curve["C_S_distance_km"].to_numpy(float)

    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    line_res = ax.plot(t, residual, color="#c53030", linewidth=2.0, label="扣除 b/k 后残差")
    ax.axhline(0, color="#666666", linewidth=0.9, alpha=0.65)
    ax.set_title("星下点补偿导致时变空间失配", fontsize=18, fontweight="bold", pad=14)
    ax.set_xlabel("相对过境时间 (s)", fontsize=12.5)
    ax.set_ylabel("扣除 b/k 后残差 (Hz)", fontsize=12.5)
    ax.grid(True, linestyle="--", alpha=0.26)

    ax_dist = ax.twinx()
    line_dist = ax_dist.plot(t, distance, color="#2f855a", linewidth=2.0, linestyle="-.", label="S 到 C(t) 距离")
    ax_dist.set_ylabel("S 到 C(t) 距离 (km)", fontsize=12.5)

    ax.text(
        0.04,
        0.93,
        "移动参考点 C(t) 先远后近再远，残差仍呈时变失配",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=12.3,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#d0d0d0", alpha=0.9),
    )
    lines = line_res + line_dist
    ax.legend(lines, [line.get_label() for line in lines], loc="lower right", frameon=True, fontsize=11)

    args.figure_output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(args.figure_output, dpi=260, bbox_inches="tight")
    plt.close(fig)

    notes.extend(
        [
            "",
            "## 使用字段",
            "- pairwise: `residual_mode`, `none_score_hz`, `subpoint_score_hz`, `score_improvement_ratio`, `none_attack_delta_rmse_hz`, `subpoint_attack_delta_rmse_hz`, `attack_delta_improvement_ratio`, `subpoint_p95_accept`, `subpoint_tri_state_decision`。",
            "- sequence_eval: `sequence_id`, `target_id`, `target_name`, `attacker_id`, `attacker_name`, `score_A_rmse_hz`, `attack_delta_rmse_hz`, `b_hat_hz`, `k_hat_hz_s`, `tri_state_decision`。",
            f"- dataset: `t_rel_s`, `{delta_source}`, `C_S_distance_km`。",
            "",
            "## 统计结果",
            f"- 原始几何差距改善比例: `{raw_imp.mean() * 100:.2f}%`。",
            f"- 验证器分数改善比例: `{score_imp.mean() * 100:.2f}%`。",
            f"- 原始改善但分数未改善比例: `{raw_not_score.mean() * 100:.2f}%`。",
            f"- ACCEPT 数: `{accept_count}`。",
            f"- DEFER 数: `{defer_count}`。",
            "",
            "## 代表性样本",
            f"- sequence_id: `{seq_id}`。",
            f"- target: `{rep_seq_row.get('target_name', rep.get('target_name', ''))}` / `{rep_seq_row.get('target_id', rep.get('target_id', ''))}`。",
            f"- attacker: `{rep_seq_row.get('attacker_name', rep.get('attacker_name', ''))}` / `{rep_seq_row.get('attacker_id', rep.get('attacker_id', ''))}`。",
            f"- score: `{float(rep_seq_row['score_A_rmse_hz']):.6f}` Hz。",
            f"- attack_delta_rmse: `{float(rep_seq_row['attack_delta_rmse_hz']):.6f}` Hz。",
            f"- tri_state: `{rep_seq_row['tri_state_decision']}`。",
            f"- d_min: `{float(np.nanmin(distance)):.3f}` km。",
            f"- 选择原因: 优先选择 subpoint_A 相比 none 原始几何差距有改善、验证器分数没有改善或更差、tri-state 不是 ACCEPT 的样本；该样本 selection_score 最高。",
        ]
    )
    args.notes_output.parent.mkdir(parents=True, exist_ok=True)
    args.notes_output.write_text("\n".join(notes), encoding="utf-8")
    print(f"Wrote {args.figure_output}")
    print(f"Wrote {args.notes_output}")


if __name__ == "__main__":
    main()
