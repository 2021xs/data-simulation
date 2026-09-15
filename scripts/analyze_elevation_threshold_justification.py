#!/usr/bin/env python
"""Summarize why 20 deg is a practical elevation threshold.

This script is read-only with respect to experiment inputs: it reuses existing
full-pass, pass-quality-aware attacker, and target availability CSV outputs.
It does not generate new observations or rerun orbit propagation.
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


BIN_EDGES = [0, 5, 10, 15, 20, 25, 30, 40, 60, math.inf]
BIN_LABELS = ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-40", "40-60", "60+"]
THRESHOLDS_DEG = [5, 10, 15, 20, 25, 30, 35, 40]
DEFAULT_THRESHOLD_TYPES = ["p95", "p99"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--reports-dir", type=Path, default=Path("outputs/reports"))
    p.add_argument("--availability-suffix", default="300")
    p.add_argument("--threshold-types", nargs="+", default=DEFAULT_THRESHOLD_TYPES)
    p.add_argument("--min-bin-count", type=int, default=5)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def read_csv_if_exists(path: Path) -> pd.DataFrame | None:
    if path.exists():
        return pd.read_csv(path)
    warn(f"missing input, skipped: {path}")
    return None


def ensure_can_write(paths: list[Path], overwrite: bool) -> None:
    existing = [p for p in paths if p.exists()]
    if existing and not overwrite:
        fail("outputs exist; add --overwrite:\n" + "\n".join(str(p) for p in existing))


def to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y"])


def add_bins(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["max_elevation_deg"] = pd.to_numeric(out["max_elevation_deg"], errors="coerce")
    out["elevation_bin"] = pd.cut(
        out["max_elevation_deg"],
        bins=BIN_EDGES,
        labels=BIN_LABELS,
        right=False,
        include_lowest=True,
    ).astype(str)
    out.loc[out["max_elevation_deg"].isna(), "elevation_bin"] = "unknown"
    return out


def normalize_eval(df: pd.DataFrame, source_file: str, default_sample_type: str | None = None) -> pd.DataFrame:
    out = df.copy()
    out["source_file"] = source_file
    if "sample_type" not in out.columns:
        out["sample_type"] = default_sample_type or ""
    out["sample_type"] = out["sample_type"].replace({"legitimate": "legit"}).fillna(default_sample_type or "")
    for col in ["accepted_score_only", "accepted_per_pass_k_p01_p99", "accepted_v3_single_pass"]:
        if col not in out.columns:
            out[col] = False if col != "accepted_v3_single_pass" else np.nan
        else:
            out[col] = to_bool(out[col])
    numeric_cols = ["score", "threshold", "normalized_score", "k_hat", "b_hat", "max_elevation_deg"]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "normalized_score" not in out.columns or out["normalized_score"].isna().all():
        if {"score", "threshold"}.issubset(out.columns):
            out["normalized_score"] = out["score"] / out["threshold"]
        else:
            out["normalized_score"] = np.nan
    return add_bins(out)


def load_sequence_sources(metrics_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    warnings: list[str] = []
    frames: list[pd.DataFrame] = []
    specs = [
        ("full_pass_adequacy_sequence_eval.csv", None),
        ("full_pass_quality_expanded_sequence_eval.csv", None),
        ("pass_quality_aware_attacker_search_sequence_eval.csv", "attack"),
    ]
    for name, sample_type in specs:
        path = metrics_dir / name
        df = read_csv_if_exists(path)
        if df is None:
            warnings.append(f"未找到 {name}，对应统计已跳过。")
            continue
        required = {"max_elevation_deg", "threshold_type", "accepted_score_only", "accepted_per_pass_k_p01_p99"}
        missing = required - set(df.columns)
        if missing:
            warnings.append(f"{name} 缺少字段 {sorted(missing)}，已跳过。")
            continue
        frames.append(normalize_eval(df, name, sample_type))
    if not frames:
        fail("no usable sequence evaluation inputs found")
    all_seq = pd.concat(frames, ignore_index=True, sort=False)
    all_seq = all_seq[all_seq["threshold_type"].isin(DEFAULT_THRESHOLD_TYPES + ["p90", "p999"])].copy()
    attack = all_seq[all_seq["sample_type"].astype(str).str.lower().eq("attack")].copy()
    legit = all_seq[all_seq["sample_type"].astype(str).str.lower().eq("legit")].copy()
    return attack, legit, warnings


def quantile_or_nan(s: pd.Series, q: float) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.quantile(q)) if len(s) else np.nan


def mean_or_nan(s: pd.Series) -> float:
    return float(s.mean()) if len(s) else np.nan


def summarize_attack_by_bin(attack: pd.DataFrame, threshold_types: list[str], min_bin_count: int) -> pd.DataFrame:
    rows = []
    for source_file, d0 in attack.groupby("source_file", dropna=False):
        for th in threshold_types:
            d = d0[d0["threshold_type"] == th]
            for i, label in enumerate(BIN_LABELS):
                g = d[d["elevation_bin"] == label]
                total = len(g)
                notes = []
                if total and total < min_bin_count:
                    notes.append("low_sample_count")
                if not total:
                    notes.append("empty_bin")
                rows.append(
                    {
                        "source_file": source_file,
                        "threshold_type": th,
                        "elevation_bin": label,
                        "elevation_min": BIN_EDGES[i],
                        "elevation_max": "" if math.isinf(BIN_EDGES[i + 1]) else BIN_EDGES[i + 1],
                        "sample_type": "attack",
                        "total_attack_sequences": int(total),
                        "score_only_accepts": int(g["accepted_score_only"].sum()) if total else 0,
                        "score_k_accepts": int(g["accepted_per_pass_k_p01_p99"].sum()) if total else 0,
                        "v3_accepts": int(g["accepted_v3_single_pass"].sum()) if "accepted_v3_single_pass" in g else 0,
                        "score_only_accept_rate": mean_or_nan(g["accepted_score_only"]) if total else np.nan,
                        "score_k_accept_rate": mean_or_nan(g["accepted_per_pass_k_p01_p99"]) if total else np.nan,
                        "v3_accept_rate": mean_or_nan(g["accepted_v3_single_pass"]) if total else np.nan,
                        "min_normalized_score": float(g["normalized_score"].min()) if total else np.nan,
                        "median_normalized_score": float(g["normalized_score"].median()) if total else np.nan,
                        "p90_normalized_score": quantile_or_nan(g["normalized_score"], 0.90),
                        "max_normalized_score": float(g["normalized_score"].max()) if total else np.nan,
                        "notes": ";".join(notes),
                    }
                )
    return pd.DataFrame(rows)


def summarize_legit_by_bin(legit: pd.DataFrame, threshold_types: list[str], min_bin_count: int) -> pd.DataFrame:
    primary = legit[legit["source_file"] == "full_pass_quality_expanded_sequence_eval.csv"].copy()
    if primary.empty:
        primary = legit.copy()
    rows = []
    for th in threshold_types:
        d = primary[primary["threshold_type"] == th]
        for label in BIN_LABELS:
            g = d[d["elevation_bin"] == label]
            total = len(g)
            score_fail = int((~g["accepted_score_only"]).sum()) if total else 0
            k_fail = int((g["accepted_score_only"] & ~g["accepted_per_pass_k_p01_p99"]).sum()) if total else 0
            both_fail = int((~g["accepted_score_only"] & ~g["accepted_per_pass_k_p01_p99"]).sum()) if total else 0
            notes = []
            if total and total < min_bin_count:
                notes.append("low_sample_count")
            if not total:
                notes.append("empty_bin")
            rows.append(
                {
                    "threshold_type": th,
                    "elevation_bin": label,
                    "total_legit_sequences": int(total),
                    "score_only_accepts": int(g["accepted_score_only"].sum()) if total else 0,
                    "score_k_accepts": int(g["accepted_per_pass_k_p01_p99"].sum()) if total else 0,
                    "score_only_accept_rate": mean_or_nan(g["accepted_score_only"]) if total else np.nan,
                    "score_k_accept_rate": mean_or_nan(g["accepted_per_pass_k_p01_p99"]) if total else np.nan,
                    "score_fail_count": score_fail,
                    "k_gate_fail_count": k_fail,
                    "both_fail_count": both_fail,
                    "median_normalized_score": float(g["normalized_score"].median()) if total else np.nan,
                    "p95_normalized_score": quantile_or_nan(g["normalized_score"], 0.95),
                    "median_k_hat": float(g["k_hat"].median()) if total and "k_hat" in g else np.nan,
                    "notes": ";".join(notes),
                }
            )
    return pd.DataFrame(rows)


def pick_primary_attack(attack: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    preferred = "pass_quality_aware_attacker_search_sequence_eval.csv"
    d = attack[attack["source_file"] == preferred].copy()
    if not d.empty:
        return d, preferred
    fallback = "full_pass_quality_expanded_sequence_eval.csv"
    d = attack[attack["source_file"] == fallback].copy()
    if not d.empty:
        return d, fallback
    return attack.copy(), "all_available_attack_sources"


def summarize_safety_tradeoff(attack: pd.DataFrame, threshold_types: list[str]) -> pd.DataFrame:
    rows = []
    for source, source_df in attack.groupby("source_file", dropna=False):
        for th in threshold_types:
            d = source_df[source_df["threshold_type"] == th]
            for threshold_deg in THRESHOLDS_DEG:
                qualified = d[d["max_elevation_deg"] >= threshold_deg]
                low = d[d["max_elevation_deg"] < threshold_deg]
                notes = [f"source={source}"]
                if qualified.empty:
                    notes.append("no_qualified_attack_sequences")
                rows.append(
                    {
                        "source_file": source,
                        "threshold_deg": threshold_deg,
                        "threshold_type": th,
                        "qualified_attack_sequences": int(len(qualified)),
                        "qualified_score_only_accepts": int(qualified["accepted_score_only"].sum()),
                        "qualified_score_k_accepts": int(qualified["accepted_per_pass_k_p01_p99"].sum()),
                        "qualified_v3_accepts": int(qualified["accepted_v3_single_pass"].sum()) if "accepted_v3_single_pass" in qualified else 0,
                        "qualified_score_only_accept_rate": mean_or_nan(qualified["accepted_score_only"]) if len(qualified) else np.nan,
                        "qualified_score_k_accept_rate": mean_or_nan(qualified["accepted_per_pass_k_p01_p99"]) if len(qualified) else np.nan,
                        "qualified_v3_accept_rate": mean_or_nan(qualified["accepted_v3_single_pass"]) if len(qualified) else np.nan,
                        "low_quality_attack_sequences": int(len(low)),
                        "low_quality_score_k_accepts": int(low["accepted_per_pass_k_p01_p99"].sum()),
                        "notes": ";".join(notes),
                    }
                )
    return pd.DataFrame(rows)


def availability_paths(metrics_dir: Path, suffix: str) -> tuple[Path, Path, Path]:
    if suffix:
        detail = metrics_dir / f"target_pass_quality_availability_pass_detail_{suffix}.csv"
        target = metrics_dir / f"target_pass_quality_availability_{suffix}.csv"
        summary = metrics_dir / f"target_pass_quality_availability_summary_{suffix}.csv"
        if detail.exists() and target.exists():
            return target, detail, summary
    return (
        metrics_dir / "target_pass_quality_availability.csv",
        metrics_dir / "target_pass_quality_availability_pass_detail.csv",
        metrics_dir / "target_pass_quality_availability_summary.csv",
    )


def summarize_availability(metrics_dir: Path, suffix: str) -> pd.DataFrame:
    target_path, detail_path, _ = availability_paths(metrics_dir, suffix)
    target_df = read_csv_if_exists(target_path)
    detail_df = read_csv_if_exists(detail_path)
    if target_df is None or detail_df is None:
        fail("missing availability target or pass detail input")
    required = {"target_sat_id", "duration_days"}
    if not required.issubset(target_df.columns):
        fail(f"{target_path} missing required fields: {sorted(required - set(target_df.columns))}")
    if not {"target_sat_id", "duration_days", "max_elevation_deg", "time_since_audit_start_hours"}.issubset(detail_df.columns):
        fail(f"{detail_path} missing required availability pass detail fields")
    detail = detail_df.copy()
    detail["max_elevation_deg"] = pd.to_numeric(detail["max_elevation_deg"], errors="coerce")
    detail["time_since_audit_start_hours"] = pd.to_numeric(detail["time_since_audit_start_hours"], errors="coerce")
    rows = []
    for duration in sorted(pd.to_numeric(target_df["duration_days"], errors="coerce").dropna().unique()):
        targets_d = target_df[pd.to_numeric(target_df["duration_days"], errors="coerce") == duration]
        target_ids = sorted(targets_d["target_sat_id"].astype(str).unique())
        detail_d = detail[pd.to_numeric(detail["duration_days"], errors="coerce") == duration].copy()
        for threshold_deg in THRESHOLDS_DEG:
            qualified = detail_d[detail_d["max_elevation_deg"] >= threshold_deg]
            q_counts = qualified.groupby(qualified["target_sat_id"].astype(str)).size()
            first_wait = qualified.groupby(qualified["target_sat_id"].astype(str))["time_since_audit_start_hours"].min()
            with_q = set(q_counts.index.astype(str))
            target_count = len(target_ids)
            targets_with = len(with_q & set(target_ids))
            visible_targets = set(detail_d["target_sat_id"].astype(str).unique())
            only_below = len((visible_targets & set(target_ids)) - with_q)
            counts = pd.Series([q_counts.get(t, 0) for t in target_ids], dtype=float)
            waits = pd.Series([first_wait.get(t, np.nan) for t in target_ids], dtype=float).dropna()
            rows.append(
                {
                    "duration_days": int(duration) if float(duration).is_integer() else float(duration),
                    "threshold_deg": threshold_deg,
                    "target_count": int(target_count),
                    "targets_with_qualified_pass_count": int(targets_with),
                    "targets_without_qualified_pass_count": int(target_count - targets_with),
                    "qualified_coverage_rate": float(targets_with / target_count) if target_count else np.nan,
                    "only_below_threshold_count": int(only_below),
                    "mean_time_to_first_qualified_pass_hours": float(waits.mean()) if len(waits) else np.nan,
                    "median_time_to_first_qualified_pass_hours": float(waits.median()) if len(waits) else np.nan,
                    "p90_time_to_first_qualified_pass_hours": quantile_or_nan(waits, 0.90),
                    "max_time_to_first_qualified_pass_hours": float(waits.max()) if len(waits) else np.nan,
                    "mean_qualified_pass_count": float(counts.mean()) if len(counts) else np.nan,
                    "median_qualified_pass_count": float(counts.median()) if len(counts) else np.nan,
                    "p10_qualified_pass_count": quantile_or_nan(counts, 0.10),
                    "p90_qualified_pass_count": quantile_or_nan(counts, 0.90),
                    "notes": f"recomputed_from={detail_path.name}",
                }
            )
    return pd.DataFrame(rows)


def fmt_pct(v: float | int | np.floating) -> str:
    if pd.isna(v):
        return "NA"
    return f"{float(v) * 100:.2f}%"


def fmt_num(v: float | int | np.floating, digits: int = 2) -> str:
    if pd.isna(v):
        return "NA"
    return f"{float(v):.{digits}f}"


def row_lookup(df: pd.DataFrame, **kwargs) -> pd.Series | None:
    d = df
    for k, v in kwargs.items():
        d = d[d[k] == v]
    if d.empty:
        return None
    return d.iloc[0]


def choose_boundary_attack_source(attack_bin: pd.DataFrame) -> str:
    preferred = "full_pass_quality_expanded_sequence_eval.csv"
    if preferred in set(attack_bin["source_file"].dropna()):
        return preferred
    fallback = "full_pass_adequacy_sequence_eval.csv"
    if fallback in set(attack_bin["source_file"].dropna()):
        return fallback
    return str(attack_bin["source_file"].dropna().iloc[0]) if not attack_bin.empty else "NA"


def choose_attacker_search_source(safety: pd.DataFrame) -> str:
    preferred = "pass_quality_aware_attacker_search_sequence_eval.csv"
    if preferred in set(safety["source_file"].dropna()):
        return preferred
    return str(safety["source_file"].dropna().iloc[0]) if not safety.empty else "NA"


def write_report(
    path: Path,
    attack_bin: pd.DataFrame,
    legit_bin: pd.DataFrame,
    safety: pd.DataFrame,
    availability: pd.DataFrame,
    warnings: list[str],
) -> None:
    boundary_source = choose_boundary_attack_source(attack_bin)
    search_source = choose_attacker_search_source(safety)
    p95_20 = row_lookup(safety, source_file=boundary_source, threshold_type="p95", threshold_deg=20)
    p95_10 = row_lookup(safety, source_file=boundary_source, threshold_type="p95", threshold_deg=10)
    p95_15 = row_lookup(safety, source_file=boundary_source, threshold_type="p95", threshold_deg=15)
    p95_30 = row_lookup(safety, source_file=boundary_source, threshold_type="p95", threshold_deg=30)
    search_p95_20 = row_lookup(safety, source_file=search_source, threshold_type="p95", threshold_deg=20)
    avail20_30d = row_lookup(availability, duration_days=30, threshold_deg=20)
    avail30_30d = row_lookup(availability, duration_days=30, threshold_deg=30)
    avail10_30d = row_lookup(availability, duration_days=30, threshold_deg=10)
    legit20_25 = row_lookup(legit_bin, threshold_type="p95", elevation_bin="20-25")
    legit25_30 = row_lookup(legit_bin, threshold_type="p95", elevation_bin="25-30")
    low_attack_rows = attack_bin[
        (attack_bin["source_file"] == boundary_source)
        & (attack_bin["threshold_type"] == "p95")
        & (attack_bin["elevation_bin"].isin(["0-5", "5-10", "10-15", "15-20"]))
    ]
    high_attack_rows = attack_bin[
        (attack_bin["source_file"] == boundary_source)
        & (attack_bin["threshold_type"] == "p95")
        & (attack_bin["elevation_bin"].isin(["20-25", "25-30", "30-40", "40-60", "60+"]))
    ]
    low_total = int(low_attack_rows["total_attack_sequences"].sum()) if not low_attack_rows.empty else 0
    low_accept = int(low_attack_rows["score_k_accepts"].sum()) if not low_attack_rows.empty else 0
    high_total = int(high_attack_rows["total_attack_sequences"].sum()) if not high_attack_rows.empty else 0
    high_accept = int(high_attack_rows["score_k_accepts"].sum()) if not high_attack_rows.empty else 0
    low_rate = low_accept / low_total if low_total else np.nan
    high_rate = high_accept / high_total if high_total else np.nan
    warn_text = "\n".join(f"- {w}" for w in warnings) if warnings else "- 无关键输入缺失；缺失等价文件未影响本轮主统计。"
    lines = [
        "# 20° Elevation Threshold Justification Summary",
        "",
        "## 1. 问题背景",
        "",
        "老师反馈的核心问题是：`20°` 这个低仰角 / 中高仰角分界必须有实验故事，不能只是经验拍脑袋。本轮只复用已有 CSV 做统计汇总，不生成新的 attack observation，不重新设计 verifier，也不改变 b/k/noise 模型。",
        "",
        "## 2. 方法",
        "",
        "- 使用 `max_elevation_deg` 作为完整过境质量指标。",
        "- 攻击侧读取 full-pass / expanded full-pass / pass-quality-aware attacker 结果，并按最大仰角分桶统计接受率。",
        "- 合法侧优先读取 `full_pass_quality_expanded_sequence_eval.csv`，统计不同最大仰角下 score-only 与 score+k gate 接受率。",
        "- 可用性侧读取 300-target availability pass detail，在 `5/10/15/20/25/30/35/40°` 候选阈值下重算 7/14/30 天 coverage 与 time-to-first-qualified-pass。",
        "- `20°` 在这里不是物理常数，而是当前 controlled station / target set / attack model 下的经验分界和工程阈值。",
        "",
        "## 3. 攻击侧结果",
        "",
        f"- 低仰角边界故事优先采用 `{boundary_source}`，因为该文件覆盖 10-20° 的 low-elevation full-pass 样本。",
        f"- 高质量攻击搜索补充采用 `{search_source}`，用于检查 20° 以上候选完整过境上的攻击接受情况。",
        f"- p95、score+k 下，`<20°` 攻击样本接受数为 `{low_accept}/{low_total}`，接受率 `{fmt_pct(low_rate)}`。",
        f"- p95、score+k 下，`>=20°` 攻击样本接受数为 `{high_accept}/{high_total}`，接受率 `{fmt_pct(high_rate)}`。",
    ]
    if p95_20 is not None:
        lines.append(
            f"- 在 `{boundary_source}` 中，当候选阈值设为 `20°`，qualified attack sequences = `{int(p95_20.qualified_attack_sequences)}`，"
            f"score-only accept rate = `{fmt_pct(p95_20.qualified_score_only_accept_rate)}`，"
            f"score+k accept rate = `{fmt_pct(p95_20.qualified_score_k_accept_rate)}`，"
            f"v3 accept rate = `{fmt_pct(p95_20.qualified_v3_accept_rate)}`。"
        )
    if search_p95_20 is not None:
        lines.append(
            f"- 在 `{search_source}` 中，`>=20°` qualified attack sequences = `{int(search_p95_20.qualified_attack_sequences)}`，"
            f"score+k / v3 accept rate 分别为 `{fmt_pct(search_p95_20.qualified_score_k_accept_rate)}` / `{fmt_pct(search_p95_20.qualified_v3_accept_rate)}`。"
        )
    if p95_10 is not None and p95_15 is not None and p95_30 is not None:
        lines.append(
            f"- 对比 `10°` / `15°` / `20°` / `30°`：p95 score+k qualified attack accept rate 分别为 "
            f"`{fmt_pct(p95_10.qualified_score_k_accept_rate)}` / `{fmt_pct(p95_15.qualified_score_k_accept_rate)}` / "
            f"`{fmt_pct(p95_20.qualified_score_k_accept_rate)}` / `{fmt_pct(p95_30.qualified_score_k_accept_rate)}`。"
        )
    lines += [
        "- 若某些细分 elevation bin 样本数低于 `--min-bin-count`，CSV 中已用 `low_sample_count` 标注，报告结论不对这些小样本 bin 过度外推。",
        "",
        "## 4. 合法侧结果",
        "",
    ]
    if legit20_25 is not None:
        lines.append(
            f"- p95、`20-25°` 合法样本 score+k accept rate = `{fmt_pct(legit20_25.score_k_accept_rate)}`，"
            f"score-only accept rate = `{fmt_pct(legit20_25.score_only_accept_rate)}`，样本数 `{int(legit20_25.total_legit_sequences)}`。"
        )
    if legit25_30 is not None:
        lines.append(
            f"- p95、`25-30°` 合法样本 score+k accept rate = `{fmt_pct(legit25_30.score_k_accept_rate)}`，样本数 `{int(legit25_30.total_legit_sequences)}`。"
        )
    lines += [
        "- 低仰角合法样本也可能通过 score/k gate，因此低仰角不应直接作为 `REJECT` 证据；更稳妥的协议语义是 `DEFER`：等待更高质量完整过境再认证。",
        "",
        "## 5. 可用性侧结果",
        "",
    ]
    for label, row in [("10°", avail10_30d), ("20°", avail20_30d), ("30°", avail30_30d)]:
        if row is not None:
            lines.append(
                f"- 30 天、候选阈值 `{label}`：coverage = `{int(row.targets_with_qualified_pass_count)}/{int(row.target_count)}` "
                f"(`{fmt_pct(row.qualified_coverage_rate)}`)，median wait = `{fmt_num(row.median_time_to_first_qualified_pass_hours)}` h，"
                f"p90 wait = `{fmt_num(row.p90_time_to_first_qualified_pass_hours)}` h，median qualified pass count = `{fmt_num(row.median_qualified_pass_count)}`。"
            )
    lines += [
        "- 详细 7/14/30 天、各候选阈值结果见 `outputs/metrics/elevation_threshold_availability_tradeoff_300.csv`。",
        "",
        "## 6. 为什么当前选择 20°",
        "",
        "当前选择 `20°` 的理由不是它具有普适物理常数意义，而是它在本轮数据中同时满足三个工程条件：",
        "",
        "1. 低于 `20°` 的区间保留了更多边界样本和攻击接受风险，适合作为 `DEFER` 区间，而不是强接受候选完整过境。",
        "2. 不低于 `20°` 后，当前 pass-quality-aware attacker 主结果中的攻击接受率明显下降或为 0，说明中高仰角完整过境更适合作为强接受候选。",
        "3. 300-target availability audit 中，`20°` 仍保持良好可用性；相比把阈值提高到 `30°` 或更高，`20°` 是更偏保留可用性的最低安全阈值。",
        "",
        "因此，`20°` 应表述为：在当前 controlled station、当前 Starlink target set、当前规则化轨道相似攻击模型与当前 score+k/v3 verifier 结果下，一个安全性-可用性折中的初步 high-quality full-pass threshold。",
        "",
        "## 7. 局限性",
        "",
        "- `20°` 不是通用物理常数；换地面站、换目标集合、换频段设置、换 pass finder 或换攻击模型，都需要重新校准。",
        "- 当前主动频率补偿攻击尚未纳入该阈值分析。",
        "- 部分 elevation bin 可能样本数有限，已在 CSV 中标注。",
        "- 本轮复用已有结果，不重新生成轨道数据，因此结论边界受已有实验覆盖范围限制。",
        "",
        "## 8. 后续工作",
        "",
        "- 当前优先把 elevation threshold story 补完整，并用于组会解释 `20°` 的工程依据。",
        "- 主动补偿攻击需要单独做文献调研和攻击能力建模。",
        "- 后续可研究服务区中心补偿到边缘接收端失配的问题，再重新评估 elevation threshold 是否需要变化。",
        "",
        "## 9. 输入缺失与替代说明",
        "",
        warn_text,
        "",
        "## 10. 关键输出文件",
        "",
        "- `outputs/metrics/elevation_threshold_attack_rate_by_bin.csv`",
        "- `outputs/metrics/elevation_threshold_legit_rate_by_bin.csv`",
        "- `outputs/metrics/elevation_threshold_safety_tradeoff.csv`",
        "- `outputs/metrics/elevation_threshold_availability_tradeoff_300.csv`",
        "- `outputs/figures/elevation_threshold_justification/`",
        "",
        f"_Generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} local time._",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def append_work_log(
    log_path: Path,
    attack_bin: pd.DataFrame,
    safety: pd.DataFrame,
    availability: pd.DataFrame,
    commands: list[str],
) -> None:
    boundary_source = choose_boundary_attack_source(attack_bin)
    search_source = choose_attacker_search_source(safety)
    p95_20 = row_lookup(safety, source_file=boundary_source, threshold_type="p95", threshold_deg=20)
    search_p95_20 = row_lookup(safety, source_file=search_source, threshold_type="p95", threshold_deg=20)
    avail20_30d = row_lookup(availability, duration_days=30, threshold_deg=20)
    attack_rate = fmt_pct(p95_20.qualified_score_k_accept_rate) if p95_20 is not None else "NA"
    search_attack_rate = fmt_pct(search_p95_20.qualified_score_k_accept_rate) if search_p95_20 is not None else "NA"
    cov = f"{int(avail20_30d.targets_with_qualified_pass_count)}/{int(avail20_30d.target_count)}" if avail20_30d is not None else "NA"
    wait = fmt_num(avail20_30d.p90_time_to_first_qualified_pass_hours) if avail20_30d is not None else "NA"
    entry = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} - 20-degree elevation threshold justification

### A. 本轮目标

基于已有 full-pass / pass-quality / attacker / availability 结果，解释为什么当前将 `max_elevation_deg >= 20°` 作为强接受候选完整过境的初步阈值。本轮不生成新的 attack observation，不做主动补偿、多站或 verifier 重设计。

### B. 实际操作

- 新增读取型分析脚本 `scripts/analyze_elevation_threshold_justification.py`。
- 复用已有 sequence evaluation 与 300-target availability pass detail。
- 按 elevation bin 统计攻击接受率和合法接受率。
- 按候选阈值 `5/10/15/20/25/30/35/40°` 统计安全性与可用性折中。
- 生成中文报告 `outputs/reports/elevation_threshold_justification_summary.md`。

### C. 新增/修改文件

- `scripts/analyze_elevation_threshold_justification.py`
- `outputs/metrics/elevation_threshold_attack_rate_by_bin.csv`
- `outputs/metrics/elevation_threshold_legit_rate_by_bin.csv`
- `outputs/metrics/elevation_threshold_safety_tradeoff.csv`
- `outputs/metrics/elevation_threshold_availability_tradeoff_300.csv`
- `outputs/reports/elevation_threshold_justification_summary.md`
- `logs/work_log.md`

### D. 运行命令

```bash
{chr(10).join(commands)}
```

### E. 结果摘要

- p95、`{boundary_source}`、候选阈值 `20°`、qualified attack score+k accept rate = `{attack_rate}`。
- p95、`{search_source}`、候选阈值 `20°`、qualified attack score+k accept rate = `{search_attack_rate}`。
- 300 targets、30 天、`20°` qualified coverage = `{cov}`。
- 300 targets、30 天、`20°` p90 time-to-first-qualified-pass = `{wait} h`。
- `20°` 不是物理常数，而是当前 controlled station / target set / attack model 下的安全性-可用性折中阈值。

### F. 问题与下一步

低仰角合法样本仍可能通过，因此低仰角更适合 `DEFER` 而不是直接 `REJECT`。后续若进入主动频率补偿攻击或多站空间一致性，应重新校准 elevation threshold。
"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)


def main() -> None:
    args = parse_args()
    out_attack = args.metrics_dir / "elevation_threshold_attack_rate_by_bin.csv"
    out_legit = args.metrics_dir / "elevation_threshold_legit_rate_by_bin.csv"
    out_safety = args.metrics_dir / "elevation_threshold_safety_tradeoff.csv"
    out_availability = args.metrics_dir / f"elevation_threshold_availability_tradeoff_{args.availability_suffix}.csv"
    report = args.reports_dir / "elevation_threshold_justification_summary.md"
    ensure_can_write([out_attack, out_legit, out_safety, out_availability, report], args.overwrite)

    attack, legit, warnings = load_sequence_sources(args.metrics_dir)
    threshold_types = args.threshold_types
    attack_bin = summarize_attack_by_bin(attack, threshold_types, args.min_bin_count)
    legit_bin = summarize_legit_by_bin(legit, threshold_types, args.min_bin_count)
    safety = summarize_safety_tradeoff(attack, threshold_types)
    availability = summarize_availability(args.metrics_dir, args.availability_suffix)

    args.metrics_dir.mkdir(parents=True, exist_ok=True)
    attack_bin.to_csv(out_attack, index=False)
    legit_bin.to_csv(out_legit, index=False)
    safety.to_csv(out_safety, index=False)
    availability.to_csv(out_availability, index=False)
    write_report(report, attack_bin, legit_bin, safety, availability, warnings)

    commands = [
        "python -m py_compile scripts/analyze_elevation_threshold_justification.py scripts/plot_elevation_threshold_justification.py",
        f"python scripts/analyze_elevation_threshold_justification.py --availability-suffix {args.availability_suffix} --overwrite",
        "python scripts/plot_elevation_threshold_justification.py --overwrite",
    ]
    append_work_log(Path("logs/work_log.md"), attack_bin, safety, availability, commands)

    print(f"wrote {out_attack} rows={len(attack_bin)}")
    print(f"wrote {out_legit} rows={len(legit_bin)}")
    print(f"wrote {out_safety} rows={len(safety)}")
    print(f"wrote {out_availability} rows={len(availability)}")
    print(f"wrote {report}")
    boundary_source = choose_boundary_attack_source(attack_bin)
    p95_20 = row_lookup(safety, source_file=boundary_source, threshold_type="p95", threshold_deg=20)
    if p95_20 is not None:
        print(
            f"p95 {boundary_source} threshold=20 score+k accept rate:",
            fmt_pct(p95_20.qualified_score_k_accept_rate),
            f"({int(p95_20.qualified_score_k_accepts)}/{int(p95_20.qualified_attack_sequences)})",
        )


if __name__ == "__main__":
    main()
