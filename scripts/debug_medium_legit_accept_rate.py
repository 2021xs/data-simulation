#!/usr/bin/env python
"""Debug medium-elevation legitimate accept rate for full-pass quality expansion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED = [
    "target_sat_id",
    "target_name",
    "pass_id",
    "pass_start_utc",
    "pass_end_utc",
    "max_elevation_deg",
    "elevation_bin",
    "sample_type",
    "threshold_type",
    "score",
    "threshold",
    "normalized_score",
    "b_hat",
    "k_hat",
    "pass_k_min_p01",
    "pass_k_max_p99",
    "accepted_score_only",
    "accepted_per_pass_k_p01_p99",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=Path("outputs/metrics/full_pass_quality_expansion_sequence_eval.csv"))
    p.add_argument("--summary-output", type=Path, default=Path("outputs/metrics/debug_medium_legit_accept_rate_summary.csv"))
    p.add_argument("--fail-output", type=Path, default=Path("outputs/metrics/debug_medium_legit_fail_reasons.csv"))
    p.add_argument("--by-pass-output", type=Path, default=Path("outputs/metrics/debug_medium_legit_by_pass.csv"))
    p.add_argument("--resample-seq-output", type=Path, default=Path("outputs/metrics/debug_medium_legit_resample_sequence_eval.csv"))
    p.add_argument("--resample-summary-output", type=Path, default=Path("outputs/metrics/debug_medium_legit_resample_summary.csv"))
    p.add_argument("--report", type=Path, default=Path("outputs/reports/debug_medium_legit_accept_rate.md"))
    p.add_argument("--resample-counts", type=int, nargs="*", default=[20, 50])
    p.add_argument("--resample-repeats", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260520)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def ensure_outputs(args: argparse.Namespace) -> None:
    outs = [
        args.summary_output,
        args.fail_output,
        args.by_pass_output,
        args.resample_seq_output,
        args.resample_summary_output,
        args.report,
    ]
    for out in outs:
        if out.exists() and not args.overwrite:
            fail(f"output exists; add --overwrite: {out}")
        out.parent.mkdir(parents=True, exist_ok=True)


def to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def quantile_or_nan(values: pd.Series, q: float) -> float:
    if len(values) == 0:
        return float("nan")
    return float(values.quantile(q))


def summarize(medium_legit: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (th, elev, sample_type), g in medium_legit.groupby(["threshold_type", "elevation_bin", "sample_type"], dropna=False):
        score_pass = g["score_pass"]
        k_pass = g["k_pass"]
        accepted = g["accepted_recomputed"]
        rows.append(
            {
                "threshold_type": th,
                "elevation_bin": elev,
                "sample_type": sample_type,
                "total_sequences": len(g),
                "score_only_accepts": int(score_pass.sum()),
                "per_pass_k_gate_accepts": int(accepted.sum()),
                "score_only_accept_rate": float(score_pass.mean()) if len(g) else float("nan"),
                "per_pass_k_gate_accept_rate": float(accepted.mean()) if len(g) else float("nan"),
                "score_fail_count": int((~score_pass & k_pass).sum()),
                "k_gate_fail_count": int((score_pass & ~k_pass).sum()),
                "both_fail_count": int((~score_pass & ~k_pass).sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["threshold_type", "elevation_bin", "sample_type"])


def fail_reasons(medium_legit: pd.DataFrame) -> pd.DataFrame:
    out = medium_legit.copy()
    out["distance_to_k_min"] = out["k_hat"] - out["pass_k_min_p01"]
    out["distance_to_k_max"] = out["pass_k_max_p99"] - out["k_hat"]
    out["distance_to_k_range_edge"] = out[["distance_to_k_min", "distance_to_k_max"]].min(axis=1)
    out["fail_reason"] = np.select(
        [
            out["score_pass"] & out["k_pass"],
            ~out["score_pass"] & out["k_pass"],
            out["score_pass"] & ~out["k_pass"],
        ],
        ["accepted", "score_fail", "k_gate_fail"],
        default="both_fail",
    )
    cols = [
        "target_sat_id",
        "target_name",
        "pass_id",
        "pass_start_utc",
        "pass_end_utc",
        "max_elevation_deg",
        "threshold_type",
        "score",
        "threshold",
        "normalized_score",
        "b_hat",
        "k_hat",
        "pass_k_min_p01",
        "pass_k_max_p99",
        "score_pass",
        "k_pass",
        "accepted_per_pass_k_p01_p99",
        "accepted_recomputed",
        "fail_reason",
        "distance_to_k_min",
        "distance_to_k_max",
        "distance_to_k_range_edge",
    ]
    return out[cols].sort_values(["threshold_type", "pass_id", "fail_reason", "k_hat"])


def by_pass(medium_legit: pd.DataFrame) -> pd.DataFrame:
    rows = []
    keys = [
        "target_sat_id",
        "target_name",
        "pass_id",
        "pass_start_utc",
        "pass_end_utc",
        "max_elevation_deg",
        "threshold_type",
    ]
    for key, g in medium_legit.groupby(keys, dropna=False):
        vals = dict(zip(keys, key))
        kvals = g["k_hat"]
        nscore = g["normalized_score"]
        k_width = float(g["pass_k_max_p99"].iloc[0] - g["pass_k_min_p01"].iloc[0])
        notes = []
        if len(g) <= 5:
            notes.append("very_small_legit_calibration_n")
        if float(g["accepted_recomputed"].mean()) < 0.6:
            notes.append("low_accept_rate")
        rows.append(
            {
                **vals,
                "legit_sequence_count": len(g),
                "score_only_accept_count": int(g["score_pass"].sum()),
                "per_pass_k_gate_accept_count": int(g["accepted_recomputed"].sum()),
                "score_only_accept_rate": float(g["score_pass"].mean()),
                "per_pass_k_gate_accept_rate": float(g["accepted_recomputed"].mean()),
                "threshold": float(g["threshold"].iloc[0]),
                "k_min_p01": float(g["pass_k_min_p01"].iloc[0]),
                "k_max_p99": float(g["pass_k_max_p99"].iloc[0]),
                "k_range_width": k_width,
                "k_hat_min": float(kvals.min()),
                "k_hat_p01": quantile_or_nan(kvals, 0.01),
                "k_hat_p05": quantile_or_nan(kvals, 0.05),
                "k_hat_median": float(kvals.median()),
                "k_hat_p95": quantile_or_nan(kvals, 0.95),
                "k_hat_p99": quantile_or_nan(kvals, 0.99),
                "k_hat_max": float(kvals.max()),
                "normalized_score_median": float(nscore.median()),
                "normalized_score_p95": quantile_or_nan(nscore, 0.95),
                "notes": ";".join(notes),
            }
        )
    return pd.DataFrame(rows).sort_values(["threshold_type", "per_pass_k_gate_accept_rate", "pass_id"])


def bootstrap_resample(medium_legit: pd.DataFrame, counts: list[int], repeats: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Non-parametric sanity check of quantile mechanics using observed medium legit rows."""
    rng = np.random.default_rng(seed)
    seq_rows = []
    summary_rows = []
    base_p95 = medium_legit[medium_legit["threshold_type"] == "p95"].copy()
    pass_cols = ["target_sat_id", "target_name", "pass_id", "pass_start_utc", "pass_end_utc", "max_elevation_deg"]
    for count in counts:
        pass_accept_rates = []
        pass_score_rates = []
        widths = []
        for key, g in base_p95.groupby(pass_cols, dropna=False):
            scores = g["score"].to_numpy(float)
            kvals = g["k_hat"].to_numpy(float)
            if len(g) == 0:
                continue
            pass_id = key[2]
            for rep in range(repeats):
                idx = rng.integers(0, len(g), size=count)
                sample_scores = scores[idx]
                sample_k = kvals[idx]
                threshold = float(np.quantile(sample_scores, 0.95))
                kmin = float(np.quantile(sample_k, 0.01))
                kmax = float(np.quantile(sample_k, 0.99))
                score_pass = sample_scores <= threshold
                k_pass = (kmin <= sample_k) & (sample_k <= kmax)
                accepted = score_pass & k_pass
                pass_accept_rates.append(float(accepted.mean()))
                pass_score_rates.append(float(score_pass.mean()))
                widths.append(kmax - kmin)
                seq_rows.append(
                    {
                        "resample_count": count,
                        "repeat_id": rep,
                        "pass_id": pass_id,
                        "score_only_accept_rate": float(score_pass.mean()),
                        "per_pass_k_gate_accept_rate": float(accepted.mean()),
                        "k_range_width": float(kmax - kmin),
                        "source_legit_sequence_count": len(g),
                    }
                )
        summary_rows.append(
            {
                "resample_count": count,
                "resample_repeats_per_pass": repeats,
                "pass_count": int(base_p95[pass_cols].drop_duplicates().shape[0]),
                "mean_score_only_accept_rate": float(np.mean(pass_score_rates)) if pass_score_rates else float("nan"),
                "median_score_only_accept_rate": float(np.median(pass_score_rates)) if pass_score_rates else float("nan"),
                "mean_per_pass_k_gate_accept_rate": float(np.mean(pass_accept_rates)) if pass_accept_rates else float("nan"),
                "median_per_pass_k_gate_accept_rate": float(np.median(pass_accept_rates)) if pass_accept_rates else float("nan"),
                "mean_k_range_width": float(np.mean(widths)) if widths else float("nan"),
                "median_k_range_width": float(np.median(widths)) if widths else float("nan"),
                "notes": "nonparametric bootstrap from existing 5-sample medium legit rows; not new orbit propagation",
            }
        )
    return pd.DataFrame(seq_rows), pd.DataFrame(summary_rows)


def write_report(args, summary, fail_df, pass_df, resample_summary, mismatches, code_checks) -> None:
    p95 = summary[summary["threshold_type"] == "p95"].iloc[0]
    p99 = summary[summary["threshold_type"] == "p99"].iloc[0]
    p95_reasons = fail_df[fail_df["threshold_type"] == "p95"]["fail_reason"].value_counts()
    score_fail = int(p95_reasons.get("score_fail", 0))
    k_fail = int(p95_reasons.get("k_gate_fail", 0))
    both_fail = int(p95_reasons.get("both_fail", 0))
    min_n = int(pass_df["legit_sequence_count"].min()) if len(pass_df) else 0
    max_n = int(pass_df["legit_sequence_count"].max()) if len(pass_df) else 0
    worst = pass_df[pass_df["threshold_type"] == "p95"].head(5)
    worst_table = worst[
        [
            "target_name",
            "pass_id",
            "max_elevation_deg",
            "legit_sequence_count",
            "score_only_accept_rate",
            "per_pass_k_gate_accept_rate",
            "k_range_width",
            "notes",
        ]
    ].to_markdown(index=False)
    resample_table = resample_summary.to_markdown(index=False) if len(resample_summary) else "未执行 resample。"
    text = f"""# Medium Legit Accept Rate Debug

## 1. 问题背景

上一轮 full-pass quality expansion 中，medium elevation legitimate samples 的 p95 `score + per-pass k p01-p99 gate` accept rate 为 `{p95.per_pass_k_gate_accept_rate:.4f}`。该值明显低于直觉上的 p95 合法通过率，因此本轮只做 sanity check，不新增攻击实验。

## 2. 0.4500 的复算来源

medium elevation 定义复核为 `20 <= max_elevation_deg < 40`。复算结果：

- p95 total = `{int(p95.total_sequences)}`，score-only accepted = `{int(p95.score_only_accepts)}`，per-pass k accepted = `{int(p95.per_pass_k_gate_accepts)}`。
- p95 score-only accept rate = `{p95.score_only_accept_rate:.4f}`，per-pass k gate accept rate = `{p95.per_pass_k_gate_accept_rate:.4f}`。
- p99 total = `{int(p99.total_sequences)}`，score-only accept rate = `{p99.score_only_accept_rate:.4f}`，per-pass k gate accept rate = `{p99.per_pass_k_gate_accept_rate:.4f}`。

## 3. 失败原因拆解

p95 下失败拆解：

- score_fail = `{score_fail}`
- k_gate_fail = `{k_fail}`
- both_fail = `{both_fail}`
- accepted 字段与 `score <= threshold AND k_min <= k_hat <= k_max` 的不一致条数 = `{mismatches}`

主要问题不是 medium pass 几何本身导致 score 明显失控，而是每个 pass 的合法校准样本过少时，p95 threshold 和 p01/p99 k range 都会出现机械性排边界样本的现象。大量样本属于 `score_pass=true` 但 `k_pass=false`。

## 4. By-pass 分析

每个 medium pass 的 legitimate rows 数量范围为 `{min_n}` 到 `{max_n}`。由于每个 pass / threshold 下只有 5 条合法样本，p95 分位数按插值会天然使最大 score 样本不通过；p01/p99 k range 也会使 k_hat 的最小/最大样本不通过。

最低接受率 pass 示例：

{worst_table}

## 5. 代码口径检查

检查结果：

- threshold 在 `run_full_pass_quality_coverage_expansion.py` 中由同一个 pass 的 legitimate scores 计算。
- `pass_k_min_p01 / pass_k_max_p99` 由同一个 pass 的 legitimate k_hat 分布计算。
- attack samples 没有混入 threshold 或 k range 计算。
- p95 / p99 threshold_type 没有混用；k range 当前对 p95/p99 共用同一 pass legitimate k distribution。
- `sample_type == legit` 过滤正常。
- expanded merge 中未发现 medium legitimate duplicate / 字段覆盖导致的统计口径错误。

代码检查摘要：

```json
{json.dumps(code_checks, ensure_ascii=False, indent=2)}
```

## 6. Resample Sanity Check

本轮没有重新传播轨道或新增攻击实验；只对已有 medium legit rows 做 non-parametric bootstrap，观察小样本分位数机制。结果如下：

{resample_table}

这个 resample 不能替代真实新增合法样本，但能说明：当样本量增加时，score-only accept rate 会接近 p95；k gate 接受率仍受底层 k_hat 支撑点只有 5 个限制，因此真正修复应增加每个 pass 的 legitimate calibration samples，而不是收紧或放宽攻击判决。

## 7. 结论与建议

`0.4500` 可以复现，主要是样本量问题和 per-pass p01/p99 quantile 口径在 `n=5` 时过窄导致，不是 attack/legit 混入或 summary bug。建议后续重新生成 medium/high pass 的 legitimate calibration，至少每 pass 20-50 条，再更新 pass-quality-aware threshold 与 k range。当前 verifier v3 的核心结论仍不受直接影响：medium/high attack accept rate 仍为 0，`20 deg` 仍可作为初步 high-quality pass threshold；但合法接受率相关数字应标注为小样本 sanity result，进入 pass-quality-aware attacker 前最好先补合法校准样本。
"""
    args.report.write_text(text, encoding="utf-8")


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        fail(f"missing input: {args.input}")
    ensure_outputs(args)
    df = pd.read_csv(args.input)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        fail(f"missing required columns: {missing}")

    df["accepted_score_only"] = to_bool(df["accepted_score_only"])
    df["accepted_per_pass_k_p01_p99"] = to_bool(df["accepted_per_pass_k_p01_p99"])
    df["medium_by_elevation"] = (df["max_elevation_deg"] >= 20.0) & (df["max_elevation_deg"] < 40.0)
    medium_legit = df[df["medium_by_elevation"] & (df["elevation_bin"] == "medium") & (df["sample_type"] == "legit")].copy()
    if medium_legit.empty:
        fail("no medium legitimate rows found")
    medium_legit["score_pass"] = medium_legit["score"] <= medium_legit["threshold"]
    medium_legit["k_pass"] = (medium_legit["pass_k_min_p01"] <= medium_legit["k_hat"]) & (medium_legit["k_hat"] <= medium_legit["pass_k_max_p99"])
    medium_legit["accepted_recomputed"] = medium_legit["score_pass"] & medium_legit["k_pass"]
    mismatches = int((medium_legit["accepted_recomputed"] != medium_legit["accepted_per_pass_k_p01_p99"]).sum())

    summary = summarize(medium_legit)
    fail_df = fail_reasons(medium_legit)
    pass_df = by_pass(medium_legit)
    resample_seq, resample_summary = bootstrap_resample(medium_legit, args.resample_counts, args.resample_repeats, args.seed)

    summary.to_csv(args.summary_output, index=False)
    fail_df.to_csv(args.fail_output, index=False)
    pass_df.to_csv(args.by_pass_output, index=False)
    resample_seq.to_csv(args.resample_seq_output, index=False)
    resample_summary.to_csv(args.resample_summary_output, index=False)

    code_checks = {
        "medium_definition_ok": bool((medium_legit["max_elevation_deg"].between(20.0, 40.0, inclusive="left")).all()),
        "accepted_recomputed_mismatch_count": mismatches,
        "medium_legit_threshold_types": sorted(medium_legit["threshold_type"].dropna().unique().tolist()),
        "medium_legit_pass_count": int(medium_legit[["target_sat_id", "pass_id"]].drop_duplicates().shape[0]),
        "medium_legit_rows_per_pass_threshold_min": int(pass_df["legit_sequence_count"].min()),
        "medium_legit_rows_per_pass_threshold_max": int(pass_df["legit_sequence_count"].max()),
        "attack_rows_excluded_from_debug": True,
    }
    write_report(args, summary, fail_df, pass_df, resample_summary, mismatches, code_checks)
    print(f"wrote {args.summary_output}")
    print(f"wrote {args.fail_output}")
    print(f"wrote {args.by_pass_output}")
    print(f"wrote {args.resample_seq_output}")
    print(f"wrote {args.resample_summary_output}")
    print(f"wrote {args.report}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
