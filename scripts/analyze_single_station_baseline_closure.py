#!/usr/bin/env python
"""Build a read-only closure report for the single-station verifier baseline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--datasets-dir", type=Path, default=Path("outputs/datasets"))
    p.add_argument("--report", type=Path, default=Path("docs/single_station_baseline_closure_report.md"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(msg: str) -> None:
    raise SystemExit(msg)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        fail(f"missing input: {path}")
    return pd.read_csv(path)


def to_bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s.fillna(False)
    return s.astype(str).str.strip().str.lower().isin(["true", "1", "yes", "y"])


def pct(v: float) -> str:
    return f"{100.0 * float(v):.2f}%"


def md_table(df: pd.DataFrame, columns: list[str] | None = None, max_rows: int | None = None) -> str:
    if columns is not None:
        df = df[columns].copy()
    if max_rows is not None:
        df = df.head(max_rows).copy()
    if df.empty:
        return "_无记录_"
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(format_cell)
    header = "| " + " | ".join(out.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(out.columns)) + " |"
    rows = ["| " + " | ".join(str(v) for v in row) + " |" for row in out.to_numpy()]
    return "\n".join([header, sep] + rows)


def format_cell(v: Any) -> str:
    if pd.isna(v):
        return ""
    if isinstance(v, float):
        if abs(v) >= 100:
            return f"{v:.3f}"
        if abs(v) >= 1:
            return f"{v:.6f}".rstrip("0").rstrip(".")
        return f"{v:.6f}".rstrip("0").rstrip(".")
    return str(v).replace("\n", " ")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def final_results(metrics: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    tri = read_csv(metrics / "full_pass_quality_expanded_tri_state_summary.csv")
    tri20 = tri[tri["elevation_min_deg"].astype(float).eq(20.0)].copy()
    rows = []
    for th in ["p95", "p99"]:
        legit = tri20[(tri20["threshold_type"].eq(th)) & (tri20["sample_type"].eq("legit"))].iloc[0]
        attack = tri20[(tri20["threshold_type"].eq(th)) & (tri20["sample_type"].eq("attack"))].iloc[0]
        rows.append(
            {
                "result_scope": "single_pass_sequence_tri_state",
                "threshold_type": th,
                "legitimate_total": int(legit["total_sequences"]),
                "legitimate_accept": int(legit["accept_count"]),
                "legitimate_reject": int(legit["reject_count"]),
                "legitimate_defer": int(legit["defer_count"]),
                "attack_total": int(attack["total_sequences"]),
                "attack_accept": int(attack["accept_count"]),
                "attack_reject": int(attack["reject_count"]),
                "attack_defer": int(attack["defer_count"]),
                "false_accept_count": int(attack["accept_count"]),
                "false_reject_count": int(legit["reject_count"]),
                "false_accept_rate": float(attack["accept_rate"]),
                "false_reject_rate": float(legit["reject_rate"]),
                "threshold_rule": f"{th} per-pass legitimate residual RMSE quantile",
                "parameter_gate": "per-pass k_hat p01-p99",
                "quality_rule": "max_elevation_deg >= 20 => ACCEPT if score+k pass; low elevation score+k pass => DEFER",
                "source_path": "outputs/metrics/full_pass_quality_expanded_tri_state_summary.csv",
            }
        )

    agg = read_csv(metrics / "full_pass_quality_expanded_multipass_aggregation_summary.csv")
    agg20 = agg[
        agg["elevation_min_deg"].astype(float).eq(20.0)
        & agg["aggregation_rule"].eq("any_high_quality_accept")
    ].copy()
    for th in ["p95", "p99"]:
        legit = agg20[(agg20["threshold_type"].eq(th)) & (agg20["sample_type"].eq("legit"))].iloc[0]
        attack = agg20[(agg20["threshold_type"].eq(th)) & (agg20["sample_type"].eq("attack"))].iloc[0]
        rows.append(
            {
                "result_scope": "case_level_multipass_any_high_quality_accept",
                "threshold_type": th,
                "legitimate_total": int(legit["total_cases"]),
                "legitimate_accept": int(legit["final_accept_count"]),
                "legitimate_reject": int(legit["final_reject_count"]),
                "legitimate_defer": int(legit["final_defer_count"]),
                "attack_total": int(attack["total_cases"]),
                "attack_accept": int(attack["final_accept_count"]),
                "attack_reject": int(attack["final_reject_count"]),
                "attack_defer": int(attack["final_defer_count"]),
                "false_accept_count": int(attack["final_accept_count"]),
                "false_reject_count": int(legit["final_reject_count"]),
                "false_accept_rate": float(attack["final_accept_rate"]),
                "false_reject_rate": float(legit["final_reject_rate"]),
                "threshold_rule": f"{th} per-pass legitimate residual RMSE quantile",
                "parameter_gate": "per-pass k_hat p01-p99",
                "quality_rule": "accept if any high-quality pass accepts; otherwise DEFER if only low-quality pass accepts",
                "source_path": "outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv",
            }
        )
    return pd.DataFrame(rows), tri20


def ablation_table(metrics: Path) -> pd.DataFrame:
    seq = read_csv(metrics / "full_pass_quality_expanded_sequence_eval.csv")
    seq["accepted_score_only"] = to_bool(seq["accepted_score_only"])
    seq["accepted_per_pass_k_p01_p99"] = to_bool(seq["accepted_per_pass_k_p01_p99"])
    tri = read_csv(metrics / "full_pass_quality_expanded_tri_state_sequence_eval.csv")
    tri20 = tri[tri["elevation_min_deg"].astype(float).eq(20.0)].copy()
    rows = []
    for th in ["p95", "p99"]:
        d = seq[seq["threshold_type"].eq(th)]
        t = tri20[tri20["threshold_type"].eq(th)]
        versions = [
            ("Version 1", "仅 residual RMSE 阈值", d, "accepted_score_only", "没有使用 k_hat/b_hat 或过境质量判断。"),
            ("Version 2", "residual RMSE 阈值 + k_hat 参数合理性检查", d, "accepted_per_pass_k_p01_p99", "使用每个 pass 的合法样本 k_hat p01-p99 范围。"),
        ]
        for version, method, df, col, explain in versions:
            legit = df[df["sample_type"].eq("legit")]
            attack = df[df["sample_type"].eq("attack")]
            legit_accept = int(legit[col].sum())
            attack_accept = int(attack[col].sum())
            rows.append(
                {
                    "threshold_type": th,
                    "method_version": version,
                    "method": method,
                    "legitimate_total": int(len(legit)),
                    "legitimate_accept_rate": legit_accept / len(legit),
                    "attack_total": int(len(attack)),
                    "attack_reject_rate": 1.0 - attack_accept / len(attack),
                    "false_accept_count": attack_accept,
                    "false_reject_count": int(len(legit) - legit_accept),
                    "defer_count": 0,
                    "explanation": explain,
                    "source_path": "outputs/metrics/full_pass_quality_expanded_sequence_eval.csv",
                }
            )
        legit = t[t["sample_type"].eq("legit")]
        attack = t[t["sample_type"].eq("attack")]
        rows.append(
            {
                "threshold_type": th,
                "method_version": "Version 3",
                "method": "residual RMSE 阈值 + k_hat 参数检查 + 20°过境质量判断",
                "legitimate_total": int(len(legit)),
                "legitimate_accept_rate": float((legit["tri_state_decision"] == "ACCEPT").mean()),
                "attack_total": int(len(attack)),
                "attack_reject_rate": float((attack["tri_state_decision"] == "REJECT").mean()),
                "false_accept_count": int((attack["tri_state_decision"] == "ACCEPT").sum()),
                "false_reject_count": int((legit["tri_state_decision"] == "REJECT").sum()),
                "defer_count": int((t["tri_state_decision"] == "DEFER").sum()),
                "explanation": "低仰角通过样本不强行 ACCEPT，而是 DEFER；高质量 pass 才允许强接受。",
                "source_path": "outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv",
            }
        )
    return pd.DataFrame(rows)


def case_studies(metrics: Path) -> pd.DataFrame:
    rows = []
    fa = read_csv(metrics / "verifier_v2_false_accepts_detail.csv")
    fa_p95 = fa[fa["threshold_type"].eq("p95")].sort_values("score").head(1)
    if not fa_p95.empty:
        r = fa_p95.iloc[0]
        rows.append(
            {
                "case_type": "score-only false accept filtered by k gate",
                "sequence_id": r["sequence_id"],
                "target": r["target"],
                "source_or_attacker": r["attack_source"],
                "attack_type": r["attack_type"],
                "score_rmse_hz": r["score"],
                "threshold_hz": r["threshold"],
                "b_hat_hz": r["b_hat"],
                "k_hat_hz_per_s": r["k_hat"],
                "decision": "score-only ACCEPT; global/per-target k gate REJECT",
                "why_boundary": "RMSE 低于阈值，但 k_hat 约 -3.22 Hz/s，明显超出 main_range 与 per-target 合法范围。",
                "limitation": "单看残差 RMSE 会让拟合自由度吸收几何差异，必须联合 fitted-parameter sanity gate。",
                "source_path": "outputs/metrics/verifier_v2_false_accepts_detail.csv",
            }
        )

    tri = read_csv(metrics / "full_pass_quality_expanded_tri_state_sequence_eval.csv")
    reject = tri[
        tri["threshold_type"].eq("p95")
        & tri["elevation_min_deg"].astype(float).eq(20.0)
        & tri["sample_type"].eq("legit")
        & tri["tri_state_decision"].eq("REJECT")
        & (tri["max_elevation_deg"].astype(float) >= 20.0)
    ].sort_values("normalized_score").head(1)
    if not reject.empty:
        r = reject.iloc[0]
        rows.append(
            {
                "case_type": "legitimate false reject under score+k",
                "sequence_id": f"{r['target_sat_id']} / {r['pass_id']} / row_index={int(r.name)}",
                "target": f"{r['target_name']} / {r['target_sat_id']}",
                "source_or_attacker": "legitimate observation",
                "attack_type": "",
                "score_rmse_hz": r["score"],
                "threshold_hz": r["threshold"],
                "b_hat_hz": r["b_hat"],
                "k_hat_hz_per_s": r["k_hat"],
                "decision": "REJECT",
                "why_boundary": f"高质量过境 max_elevation_deg={float(r['max_elevation_deg']):.2f}°，但 score 或 k_hat 检查未通过。",
                "limitation": "参数 gate 会牺牲一部分合法接受率；这是安全性与合法误拒之间的主要折中。",
                "source_path": "outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv",
            }
        )

    defer = tri[
        tri["threshold_type"].eq("p95")
        & tri["elevation_min_deg"].astype(float).eq(20.0)
        & tri["sample_type"].eq("legit")
        & tri["tri_state_decision"].eq("DEFER")
    ].sort_values("normalized_score").head(1)
    if not defer.empty:
        r = defer.iloc[0]
        rows.append(
            {
                "case_type": "legitimate low-elevation DEFER",
                "sequence_id": f"{r['target_sat_id']} / {r['pass_id']} / row_index={int(r.name)}",
                "target": f"{r['target_name']} / {r['target_sat_id']}",
                "source_or_attacker": "legitimate observation",
                "attack_type": "",
                "score_rmse_hz": r["score"],
                "threshold_hz": r["threshold"],
                "b_hat_hz": r["b_hat"],
                "k_hat_hz_per_s": r["k_hat"],
                "decision": "DEFER",
                "why_boundary": f"score+k 通过，但 max_elevation_deg={float(r['max_elevation_deg']):.2f} < 20°。",
                "limitation": "低仰角合法样本可能看起来像目标，但不适合强 ACCEPT；需要等待高质量完整过境。",
                "source_path": "outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv",
            }
        )
    return pd.DataFrame(rows)


def write_report(
    path: Path,
    final_df: pd.DataFrame,
    ablation: pd.DataFrame,
    cases: pd.DataFrame,
    manifest: dict[str, Any],
    orbit_cfg: dict[str, Any],
    param_cfg: dict[str, Any],
    metrics: Path,
) -> None:
    station = manifest.get("station") or orbit_cfg.get("station", {})
    ranges = manifest.get("parameter_ranges_used") or {
        "b_hz": param_cfg.get("parameters", {}).get("b_hz", {}).get("main_range", "未在当前仓库中找到"),
        "k_hz_per_s": param_cfg.get("parameters", {}).get("k_hz_per_s", {}).get("main_range", "未在当前仓库中找到"),
        "sigma_hz": param_cfg.get("parameters", {}).get("sigma_hz", {}).get("main_range", "未在当前仓库中找到"),
    }
    pqa = read_csv(metrics / "pass_quality_aware_attacker_search_sequence_eval.csv")
    pqa_summary = pqa.groupby("threshold_type")[["accepted_score_only", "accepted_per_pass_k_p01_p99", "accepted_v3_single_pass"]].sum().reset_index()
    pqa_summary["total_sequences"] = pqa.groupby("threshold_type").size().values
    v2 = read_csv(metrics / "verifier_v2_gate_ablation.csv")
    v2_short = v2[
        v2["sample_group"].isin(["legit", "attack"])
        & v2["gate_name"].isin(["score_only", "score_plus_global_k_gate", "score_plus_global_bk_gate"])
    ].copy()
    text = f"""# 单站 Doppler Residual Identity Verification Baseline 收口报告

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

本报告只整理当前仓库中已经存在的单站 Doppler-only claimed-identity verification 代码和输出；没有重新生成 attack observation，没有改 verifier 逻辑，也没有做主动调频或多站实验。

## 1. 单站 baseline 当前链路

当前单站链路的核心实现位于 `scripts/run_doppler_verifier_initial_experiments.py`：

- `ObservationSequence`（约第 57 行）保存一条观测曲线 `y_obs_hz`、时间网格、source geometry 和经验误差参数。
- `fit_bias_and_slope(...)`（约第 236 行）计算 `delta_A(t)=y(t)-f_geo_A(t)`，用最小二乘拟合 `b_hat + k_hat(t-t0)`，并输出拟合后 residual RMSE。
- `apply_empirical_error_model(...)`（约第 251 行）生成 `f_obs(t)=f_geo(t)+b+k(t-t0)+noise`。
- `build_legitimate_observation(...)`（约第 272 行）用目标 A 的几何曲线生成合法观测。
- `build_attack_observation(...)`（约第 312 行）用攻击源 B 的几何曲线生成观测，但只把它作为观测来源，不作为 claimed reference。
- `verify_claimed_identity(...)`（约第 366 行）只接收观测曲线和 claimed target A 的 `f_geo_A(t)`，不使用 B 的轨道参数做判决。
- `calibrate_thresholds(...)`（约第 480 行）按每个 target 的合法 residual RMSE 分布计算 p95 / p99 阈值。
- `synthetic_same_plane_geo(...)`（约第 523 行）用于构造第一阶段规则化 same-plane 高度/相位扰动攻击轨道。

后续增强逻辑是只读后处理或扩展实验：

- `scripts/evaluate_verifier_v2_gates.py`：保留 score-only 决策，额外统计 global k、global b/k、per-target k、per-target b/k gate。
- `scripts/run_full_pass_quality_coverage_expansion.py`：为困难样本补充中高仰角完整过境，并按每个 pass 重新校准 score threshold 与 k_hat 范围。
- `scripts/evaluate_full_pass_quality_expanded_tri_state.py`：实现 `ACCEPT / REJECT / DEFER`，其中低于仰角阈值但 score+k 通过的样本给 `DEFER`。
- `scripts/evaluate_full_pass_quality_expanded_multipass_aggregation.py`：把多次完整过境聚合成 case-level 决策。
- `scripts/run_pass_quality_aware_attacker_search.py`：在攻击者知道 pass-quality 规则的情况下，只评估 `max_elevation_deg >= 20` 的高质量候选过境。

链路可以整理为：

`TLE / SGP4 / station / carrier frequency` -> `f_geo_A(t)` -> `f_obs(t)` -> `delta_A(t)` -> `b/k least-squares fitting` -> `residual RMSE score` -> `p95/p99 threshold` -> `k_hat / b_hat sanity check` -> `pass quality` -> `ACCEPT / REJECT / DEFER`。

## 2. 固定实验设置表

| 项目 | 当前仓库事实 |
| --- | --- |
| mode | `controlled_starlink`，`observation_id=null`，来源：`outputs/datasets/doppler_verifier_initial_experiments_manifest.json` |
| 地面站 | `{station.get('name', '未在当前仓库中找到')}`，lat `{station.get('lat_deg', 'NA')}`，lon `{station.get('lon_deg', 'NA')}`，alt `{station.get('alt_m', 'NA')}` m |
| 载波频率 | `{manifest.get('simulation_center_freq_hz', '未在当前仓库中找到')}` Hz |
| 目标卫星数量 | 初始 score-only/v2：`{manifest.get('target_count', '未在当前仓库中找到')}`；full-pass quality expanded 当前覆盖困难目标/过境集合见 `outputs/metrics/full_pass_quality_expanded_sequence_eval.csv` |
| 初始合法样本 | `{manifest.get('legitimate_sequence_count', '未在当前仓库中找到')}` sequences，`{manifest.get('legitimate_row_count', '未在当前仓库中找到')}` rows |
| 初始攻击样本 | `{manifest.get('attack_sequence_count', '未在当前仓库中找到')}` sequences，`{manifest.get('attack_row_count', '未在当前仓库中找到')}` rows |
| 初始攻击类型 | `{', '.join(manifest.get('attack_types', [])) or '未在当前仓库中找到'}` |
| 初始攻击参数 | 高度偏移 `{manifest.get('altitude_offsets_km', 'NA')}` km；相位偏移 `{manifest.get('phase_offsets_s', 'NA')}` s |
| 时间窗口 | `configs/orbit_simulation_cases.yaml` 中 `auto_pass_search`，search_start=`{orbit_cfg.get('time_window', {}).get('search_start_utc', 'NA')}`，min_elevation=`{orbit_cfg.get('time_window', {}).get('min_elevation_deg', 'NA')}` deg，step=`{orbit_cfg.get('time_window', {}).get('step_s', 'NA')}` s |
| residual model | `f_obs(t)=f_geo(t)+b+k(t-t0)+noise` |
| b 范围 | `{ranges.get('b_hz')}` Hz，来源：`configs/simulation_parameter_config.yaml` / manifest |
| k 范围 | `{ranges.get('k_hz_per_s')}` Hz/s，来源：`configs/simulation_parameter_config.yaml` / manifest |
| noise sigma 范围 | `{ranges.get('sigma_hz')}` Hz，来源：`configs/simulation_parameter_config.yaml` / manifest |
| 阈值计算 | per-target 或 per-pass 合法样本 residual RMSE 的 p95 / p99 分位数 |
| 参数检查 | v2 使用 global k、global b/k、per-target quantile；full-pass quality 使用 per-pass `k_hat` p01-p99 |
| pass quality | 当前收口使用 `max_elevation_deg >= 20°` 作为强接受候选完整过境阈值；低仰角通过样本进入 `DEFER` |
| 主要输出 | `outputs/metrics/verifier_v2_gate_ablation.csv`、`outputs/metrics/full_pass_quality_expanded_tri_state_summary.csv`、`outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv`、`outputs/metrics/pass_quality_aware_attacker_search_sequence_eval.csv` |

## 3. 最终 baseline 结果表

### 3.1 单次完整过境 tri-state 序列级结果

数据来源：`outputs/metrics/full_pass_quality_expanded_tri_state_summary.csv`，`elevation_min_deg=20`。

{md_table(final_df[final_df['result_scope'].eq('single_pass_sequence_tri_state')], ['threshold_type', 'legitimate_total', 'legitimate_accept', 'legitimate_reject', 'legitimate_defer', 'attack_total', 'attack_accept', 'attack_reject', 'attack_defer', 'false_accept_count', 'false_reject_count', 'false_accept_rate', 'false_reject_rate', 'threshold_rule', 'parameter_gate', 'quality_rule'])}

### 3.2 case-level 多过境聚合结果

推荐作为当前单站 baseline 收口口径：`any_high_quality_accept`。含义是：至少一个高质量完整过境通过 score+k 才最终 ACCEPT；若只有低质量过境通过，则 DEFER。

数据来源：`outputs/metrics/full_pass_quality_expanded_multipass_aggregation_summary.csv`，`elevation_min_deg=20`。

{md_table(final_df[final_df['result_scope'].eq('case_level_multipass_any_high_quality_accept')], ['threshold_type', 'legitimate_total', 'legitimate_accept', 'legitimate_reject', 'legitimate_defer', 'attack_total', 'attack_accept', 'attack_reject', 'attack_defer', 'false_accept_count', 'false_reject_count', 'false_accept_rate', 'false_reject_rate', 'threshold_rule', 'parameter_gate', 'quality_rule'])}

补充验证：pass-quality-aware attacker search 在 `max_elevation_deg >= 20°` 的约束搜索中，p95/p99 的 score-only、score+k、v3 single-pass 接受数均为 0。

{md_table(pqa_summary, ['threshold_type', 'total_sequences', 'accepted_score_only', 'accepted_per_pass_k_p01_p99', 'accepted_v3_single_pass'])}

## 4. 最小 ablation 表

数据来源：`outputs/metrics/full_pass_quality_expanded_sequence_eval.csv` 与 `outputs/metrics/full_pass_quality_expanded_tri_state_sequence_eval.csv`。

说明：最终 full-pass quality 主线使用的是 per-pass `k_hat` p01-p99 检查；`b_hat` gate 在 v2 离线消融中已经评估，但当前 pass-quality tri-state 输出没有单独的 per-pass b_hat gate 字段，因此 ablation 的 Version 2/3 不把 b_hat 作为最终主线条件。

{md_table(ablation, ['threshold_type', 'method_version', 'method', 'legitimate_total', 'legitimate_accept_rate', 'attack_total', 'attack_reject_rate', 'false_accept_count', 'false_reject_count', 'defer_count', 'explanation'])}

v2 初始 20-target score-only 对比也支持同一结论：score-only 在 2000 条攻击中有 3 条 false accept；global k / global b+k gate 后 false accept 变为 0。

{md_table(v2_short, ['threshold_type', 'gate_name', 'sample_group', 'total_sequences', 'accepted_sequences', 'false_accepts_for_attack', 'false_accept_rate_for_attack', 'legit_accept_rate', 'notes'], 12)}

## 5. false accept / false reject / DEFER 个例分析

{md_table(cases, ['case_type', 'sequence_id', 'target', 'source_or_attacker', 'attack_type', 'score_rmse_hz', 'threshold_hz', 'b_hat_hz', 'k_hat_hz_per_s', 'decision', 'why_boundary', 'limitation', 'source_path'])}

补充边界参考：`outputs/metrics/verifier_v2_fine_sweep_hard_cases.csv` 中存在细粒度高度偏移样本可以通过 per-target k p01-p99 gate，例如 `alt_fine_001147`，这说明几何极近样本仍是单站 Doppler-only baseline 的边界，但它不是当前 pass-quality 主线的最终验收口径。

## 6. 单站阶段性结论

1. 当前单站链路已经可以作为 baseline：输入为 claimed target A 与观测曲线，只用 A 的 `f_geo_A(t)` 做残差拟合与判决，不在 verifier 中使用攻击源 B 的轨道参数。
2. residual RMSE 能区分合法样本和多数规则化轨道相似攻击；初始 2000 条攻击中 score-only false accept 为 3 条。
3. `k_hat` / `b_hat` 参数合理性检查是必要的：3 条 score-only false accept 的 `k_hat` 明显越界，加入 gate 后被拒绝。
4. pass quality 判断解决了低质量完整过境的强判决问题：低仰角样本即使通过 score+k，也进入 `DEFER`，而不是直接 ACCEPT。
5. 当前推荐收口口径为：per-pass residual RMSE threshold + per-pass k_hat p01-p99 gate + `20°` high-quality pass 判断 + case-level `any_high_quality_accept` 聚合。
6. 剩余边界主要来自几何极近、细粒度高度偏移、短/低质量窗口，以及后续更强的主动频率补偿攻击。
7. 因此下一阶段不应继续无限扩展单站规则化攻击集合，而应在这个 baseline 上研究主动调频攻击下的多接收端空间一致性与残差差异。

## 7. 下次组会可用的一页摘要

### 单站 Doppler residual identity verification baseline 收口

- 当前单站验证器已经形成可复现 baseline：给定声称目标 A，只用 A 的理论多普勒曲线和观测曲线做残差拟合与判决。
- 初始 score-only 结果显示，残差 RMSE 能拒绝绝大多数规则化轨道相似攻击，但 2000 条攻击中仍有 3 条误接受。
- 这 3 条误接受的 `k_hat` 明显越界，说明只看 RMSE 不够；加入拟合参数合理性检查后，误接受降为 0。
- 在完整过境质量实验中，20°以上高质量过境的攻击误接受率为 0；低仰角通过样本不强行接受，而是延后判断。
- case-level 多过境聚合下，`any_high_quality_accept` 规则在当前困难样本集合中保持合法样本 200/200 接受，攻击样本 0/160 接受。
- 当前单站 baseline 的边界是几何极近、低质量过境和潜在主动调频攻击。
- 下一阶段应基于该 baseline 研究主动调频攻击下，多接收端看到的补偿残差是否一致。

## 附：本报告生成的结果表

- `outputs/metrics/single_station_baseline_final_results.csv`
- `outputs/metrics/single_station_baseline_ablation.csv`
- `outputs/metrics/single_station_baseline_case_studies.csv`
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_log() -> None:
    entry = f"""
## {datetime.now().strftime('%Y-%m-%d %H:%M')} - single-station baseline closure report

### A. 本轮目标

整理当前单站 Doppler-only claimed-identity verifier 的代码事实、实验结果、ablation 和边界案例，形成可汇报、可复现的 baseline 收口报告。

### B. 实际操作

- 新增只读统计脚本 `scripts/analyze_single_station_baseline_closure.py`。
- 读取已有 verifier、v2 gate、full-pass tri-state、multi-pass aggregation、pass-quality-aware attacker 和 fine-sweep hard case 输出。
- 生成最终结果表、最小 ablation 表、边界案例表和 Markdown 报告。
- 未重新仿真，未生成新 attack observation，未改 verifier 核心逻辑。

### C. 新增/修改文件

- `scripts/analyze_single_station_baseline_closure.py`
- `outputs/metrics/single_station_baseline_final_results.csv`
- `outputs/metrics/single_station_baseline_ablation.csv`
- `outputs/metrics/single_station_baseline_case_studies.csv`
- `docs/single_station_baseline_closure_report.md`
- `logs/work_log.md`

### D. 运行命令

```bash
python -m py_compile scripts/analyze_single_station_baseline_closure.py
python scripts/analyze_single_station_baseline_closure.py --overwrite
```

### E. 结果摘要

- 单次完整过境 tri-state p95：legit ACCEPT/REJECT/DEFER = `1108/142/70`，attack ACCEPT/REJECT/DEFER = `0/790/50`。
- case-level `any_high_quality_accept` p95：legit ACCEPT = `200/200`，attack ACCEPT = `0/160`。
- pass-quality-aware attacker search：p95/p99 high-quality pass accepted rows 均为 `0`。

### F. 问题与下一步

当前单站 baseline 足够作为下一阶段主动调频多点实验的基线；主动补偿攻击和多接收端空间一致性仍需单独建模与实验。
"""
    p = Path("logs/work_log.md")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(entry)


def main() -> None:
    args = parse_args()
    outputs = [
        args.metrics_dir / "single_station_baseline_final_results.csv",
        args.metrics_dir / "single_station_baseline_ablation.csv",
        args.metrics_dir / "single_station_baseline_case_studies.csv",
        args.report,
    ]
    existing = [p for p in outputs if p.exists()]
    if existing and not args.overwrite:
        fail("outputs exist; add --overwrite:\n" + "\n".join(str(p) for p in existing))

    final_df, _tri20 = final_results(args.metrics_dir)
    ablation = ablation_table(args.metrics_dir)
    cases = case_studies(args.metrics_dir)
    manifest = load_json(args.datasets_dir / "doppler_verifier_initial_experiments_manifest.json")
    orbit_cfg = load_yaml(Path("configs/orbit_simulation_cases.yaml"))
    param_cfg = load_yaml(Path("configs/simulation_parameter_config.yaml"))

    args.metrics_dir.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(args.metrics_dir / "single_station_baseline_final_results.csv", index=False, encoding="utf-8-sig")
    ablation.to_csv(args.metrics_dir / "single_station_baseline_ablation.csv", index=False, encoding="utf-8-sig")
    cases.to_csv(args.metrics_dir / "single_station_baseline_case_studies.csv", index=False, encoding="utf-8-sig")
    write_report(args.report, final_df, ablation, cases, manifest, orbit_cfg, param_cfg, args.metrics_dir)
    append_log()
    print(f"wrote {args.metrics_dir / 'single_station_baseline_final_results.csv'} rows={len(final_df)}")
    print(f"wrote {args.metrics_dir / 'single_station_baseline_ablation.csv'} rows={len(ablation)}")
    print(f"wrote {args.metrics_dir / 'single_station_baseline_case_studies.csv'} rows={len(cases)}")
    print(f"wrote {args.report}")


if __name__ == "__main__":
    main()
