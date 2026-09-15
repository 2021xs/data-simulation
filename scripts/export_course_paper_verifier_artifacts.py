#!/usr/bin/env python
"""Export course-paper artifacts for Section 6.

This script only reads existing metrics/reports and formats paper-ready
tables, figures, facts, and a short draft. It does not rerun simulations.
"""

from __future__ import annotations

import argparse
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import yaml


CORE_METRICS = [
    "verifier_v2_sequence_eval.csv",
    "verifier_v2_gate_ablation.csv",
    "verifier_v2_false_accepts_detail.csv",
    "verifier_v2_altitude_fine_sweep_sequence_eval.csv",
    "verifier_v2_phase_fine_sweep_sequence_eval.csv",
    "verifier_v2_fine_sweep_gate_summary.csv",
    "verifier_v2_fine_sweep_hard_cases.csv",
    "verifier_v2_hard_case_forensic_summary.csv",
    "verifier_v2_hard_case_multipass_sequence_eval.csv",
    "verifier_v2_hard_case_multipass_summary.csv",
    "verifier_v2_hard_case_multiwindow_sequence_eval.csv",
    "verifier_v2_hard_case_multiwindow_summary.csv",
    "controlled_starlink_20target_selection_table.csv",
]

CORE_REPORTS = [
    "verifier_v2_summary.md",
    "verifier_v2_fine_sweep_summary.md",
    "verifier_v2_hard_case_temporal_summary.md",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--metrics-dir", type=Path, default=Path("outputs/metrics"))
    p.add_argument("--reports-dir", type=Path, default=Path("outputs/reports"))
    p.add_argument("--figures-dir", type=Path, default=Path("outputs/figures"))
    p.add_argument("--output-dir", type=Path, default=Path("outputs/course_paper"))
    p.add_argument("--parameter-config", type=Path, default=Path("configs/simulation_parameter_config.yaml"))
    p.add_argument("--orbit-config", type=Path, default=Path("configs/orbit_simulation_cases.yaml"))
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def read_csv(path: Path, audit: list[dict[str, Any]]) -> pd.DataFrame | None:
    if not path.exists():
        audit.append({"path": str(path), "status": "missing", "rows": 0, "columns": []})
        return None
    df = pd.read_csv(path)
    audit.append({"path": str(path), "status": "ok", "rows": len(df), "columns": list(df.columns)})
    return df


def read_text(path: Path, audit: list[dict[str, Any]]) -> str:
    if not path.exists():
        audit.append({"path": str(path), "status": "missing", "rows": 0, "columns": []})
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    audit.append({"path": str(path), "status": "ok", "rows": len(text.splitlines()), "columns": ["markdown"]})
    return text


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def ensure_outputs(paths: list[Path], overwrite: bool) -> None:
    existing = [str(path) for path in paths if path.exists()]
    if existing and not overwrite:
        fail("输出文件已存在；若确认覆盖请添加 --overwrite: " + ", ".join(existing))
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)


def as_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().isin(["true", "1", "yes"])


def fmt_num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "NA"
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(x):
        return "NA"
    if x.is_integer():
        return str(int(x))
    return f"{x:.{digits}f}".rstrip("0").rstrip(".")


def latex_escape(text: Any) -> str:
    value = str(text)
    for src, dst in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ]:
        value = value.replace(src, dst)
    return value


def latex_table(headers: list[str], rows: list[list[Any]], caption: str, label: str) -> str:
    colspec = "p{0.33\\linewidth}p{0.58\\linewidth}" if len(headers) == 2 else "l" * len(headers)
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        rf"\caption{{{latex_escape(caption)}}}",
        rf"\label{{{latex_escape(label)}}}",
        rf"\begin{{tabular}}{{{colspec}}}",
        r"\hline",
        " & ".join(latex_escape(h) for h in headers) + r" \\",
        r"\hline",
    ]
    for row in rows:
        lines.append(" & ".join(latex_escape(x) for x in row) + r" \\")
    lines.extend([r"\hline", r"\end{tabular}", r"\end{table}", ""])
    return "\n".join(lines)


def gate_row(gate: pd.DataFrame, threshold: str, gate_name: str, group: str, quantile: str | None = None) -> pd.Series | None:
    if gate is None:
        return None
    sub = gate[
        (gate["threshold_type"].astype(str) == threshold)
        & (gate["gate_name"].astype(str) == gate_name)
        & (gate["sample_group"].astype(str) == group)
    ]
    if quantile is not None and "quantile_setting" in sub.columns:
        sub = sub[sub["quantile_setting"].fillna("").astype(str) == quantile]
    return None if sub.empty else sub.iloc[0]


def compute_results(data: dict[str, pd.DataFrame | None]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    gate = data.get("verifier_v2_gate_ablation.csv")
    row = gate_row(gate, "p95", "score_only", "attack")
    result["coarse_score_only_false_accepts"] = int(row["false_accepts_for_attack"]) if row is not None else None
    result["coarse_score_only_total"] = int(row["total_sequences"]) if row is not None else None
    row = gate_row(gate, "p95", "score_plus_per_target_k_quantile_gate", "attack", "p01-p99")
    result["coarse_per_target_k_false_accepts"] = int(row["false_accepts_for_attack"]) if row is not None else None
    result["coarse_per_target_k_total"] = int(row["total_sequences"]) if row is not None else None

    fine = data.get("verifier_v2_fine_sweep_gate_summary.csv")
    if fine is not None:
        p95_alt = fine[
            (fine["threshold_type"].astype(str) == "p95")
            & (fine["attack_type"].astype(str) == "same_plane_altitude_offset_fine")
        ]
        p95_phase = fine[
            (fine["threshold_type"].astype(str) == "p95")
            & (fine["attack_type"].astype(str) == "same_plane_phase_offset_fine")
        ]
        result["altitude_fine_total"] = int(p95_alt["total_sequences"].sum())
        result["altitude_fine_score_only_false_accepts"] = int(p95_alt["score_only_accepts"].sum())
        result["altitude_fine_per_target_k_false_accepts"] = int(p95_alt["per_target_k_p01_p99_accepts"].sum())
        result["phase_fine_total"] = int(p95_phase["total_sequences"].sum())
        result["phase_fine_score_only_false_accepts"] = int(p95_phase["score_only_accepts"].sum())
        result["phase_fine_per_target_k_false_accepts"] = int(p95_phase["per_target_k_p01_p99_accepts"].sum())
        danger = p95_alt[p95_alt["attack_param_value"].isin([-2.0, -1.0])]
        result["altitude_danger_rows"] = danger.sort_values("attack_param_value").copy()

    mp = data.get("verifier_v2_hard_case_multipass_sequence_eval.csv")
    if mp is not None:
        attack = mp[(mp["sample_type"].astype(str) == "attack") & (mp["threshold_type"].astype(str) == "p95")]
        result["multipass_total"] = int(len(attack))
        result["multipass_score_only_accepts"] = int(as_bool(attack["accepted_score_only"]).sum())
        result["multipass_per_pass_k_accepts"] = int(as_bool(attack["accepted_per_pass_k_p01_p99"]).sum())
        if len(attack):
            result["multipass_score_only_rate"] = result["multipass_score_only_accepts"] / len(attack)
            result["multipass_per_pass_k_rate"] = result["multipass_per_pass_k_accepts"] / len(attack)
            pass_summary = attack.groupby("pass_id", dropna=False).agg(
                max_elevation_deg=("max_elevation_deg", "first"),
                total=("score", "size"),
                score_only_accepts=("accepted_score_only", lambda s: int(as_bool(s).sum())),
                per_pass_k_accepts=("accepted_per_pass_k_p01_p99", lambda s: int(as_bool(s).sum())),
            ).reset_index()
            result["multipass_pass_summary"] = pass_summary

    mw = data.get("verifier_v2_hard_case_multiwindow_summary.csv")
    if mw is not None:
        rows = []
        for length in sorted(mw["window_length_s"].dropna().unique()):
            sub = mw[
                (mw["threshold_type"].astype(str) == "p95")
                & (mw["aggregation_rule"].astype(str) == "all_windows_accept")
                & (mw["window_length_s"] == length)
            ]
            # Keep this aggregation consistent with the existing temporal
            # summary report: average the per-hard-case rows rather than
            # weighting by attack_total.
            legit_rate = float(sub["legit_accept_rate"].dropna().mean())
            attack_rate = float(sub["attack_accept_rate"].dropna().mean())
            rows.append({"window_length_s": int(length), "legit_accept_rate": legit_rate, "attack_accept_rate": attack_rate})
        result["multiwindow_all_windows"] = pd.DataFrame(rows)

    forensic = data.get("verifier_v2_hard_case_forensic_summary.csv")
    if forensic is not None:
        result["hard_case_count"] = int(len(forensic))
        result["hard_case_min_normalized_score"] = float(forensic["normalized_score"].min()) if len(forensic) else None

    selection = data.get("controlled_starlink_20target_selection_table.csv")
    if selection is not None:
        result["target_count"] = int(len(selection))
        result["candidate_limit"] = int(selection["candidate_limit"].max()) if "candidate_limit" in selection else None

    return result


def extract_report_numbers(reports: dict[str, str]) -> dict[str, str]:
    extracted: dict[str, str] = {}
    text = "\n".join(reports.values())
    patterns = {
        "README/report coarse": r"score-only false accepts[：:]\s*`?(\d+)`?",
        "README/report selected hard cases": r"selected hard cases(?: 数量)?[：:]\s*`?(\d+)`?",
    }
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        if m:
            extracted[key] = m.group(1)
    return extracted


def write_settings_table(path: Path, cfg: dict[str, Any], param_cfg: dict[str, Any], result: dict[str, Any]) -> None:
    station = cfg.get("station", {})
    ku = cfg.get("ku_band_experiment", {})
    params = param_cfg.get("parameters", {})
    b_range = params.get("b_hz", {}).get("main_range", [3179.0, 3728.0])
    k_range = params.get("k_hz_per_s", {}).get("main_range", [-1.110156, -0.197808])
    sigma_range = params.get("sigma_hz", {}).get("main_range", [23.215, 32.89])
    rows = [
        ["Station", f"lat={station.get('lat_deg', 52.2100):.4f}, lon={station.get('lon_deg', 5.1600):.4f}, alt={station.get('alt_m', 14)} m"],
        ["Center frequency", f"{ku.get('simulation_center_freq_hz', 11325000000) / 1e9:.3f} GHz (controlled simulation baseline)"],
        ["Residual model", f"b in [{b_range[0]}, {b_range[1]}] Hz; k in [{k_range[0]}, {k_range[1]}] Hz/s; sigma in [{sigma_range[0]}, {sigma_range[1]}] Hz"],
        ["Targets", f"{result.get('target_count', 20)}-target controlled Starlink baseline"],
        ["Attack/stress tests", "altitude fine sweep, phase fine sweep, hard-case temporal retest"],
        ["Verifier score", "detrended residual RMSE after fitting b + k(t-t0)"],
        ["Gate", "per-target/per-pass fitted k_hat p01-p99 sanity gate"],
    ]
    path.write_text(
        latex_table(
            ["Item", "Setting"],
            rows,
            "第6节受控仿真实验设置。该表对应 controlled simulation baseline，不是真实 Starlink observation replay。",
            "tab:section6_experiment_settings",
        ),
        encoding="utf-8",
    )


def write_results_table(path: Path, result: dict[str, Any]) -> None:
    mw = result.get("multiwindow_all_windows")
    mw_text = "NA"
    if isinstance(mw, pd.DataFrame) and not mw.empty:
        parts = [
            f"{int(r.window_length_s)}s: legit {r.legit_accept_rate:.4f}, attack {r.attack_accept_rate:.4f}"
            for r in mw.itertuples(index=False)
        ]
        mw_text = "; ".join(parts)
    rows = [
        [
            "coarse verifier v2 score-only attack eval",
            f"{result.get('coarse_score_only_false_accepts')} / {result.get('coarse_score_only_total')} false accepts",
            "outputs/metrics/verifier_v2_gate_ablation.csv",
        ],
        [
            "coarse verifier v2 score + per-target k gate",
            f"{result.get('coarse_per_target_k_false_accepts')} / {result.get('coarse_per_target_k_total')} false accepts",
            "outputs/metrics/verifier_v2_gate_ablation.csv",
        ],
        [
            "altitude fine sweep p95 score-only",
            f"{result.get('altitude_fine_score_only_false_accepts')} / {result.get('altitude_fine_total')} false accepts",
            "outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv",
        ],
        [
            "altitude fine sweep p95 score + per-target k p01-p99",
            f"{result.get('altitude_fine_per_target_k_false_accepts')} / {result.get('altitude_fine_total')} false accepts",
            "outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv",
        ],
        [
            "phase fine sweep p95 score-only",
            f"{result.get('phase_fine_score_only_false_accepts')} / {result.get('phase_fine_total')} false accepts",
            "outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv",
        ],
        [
            "hard-case multipass p95 score-only",
            f"{result.get('multipass_score_only_accepts')} / {result.get('multipass_total')} = {fmt_num(result.get('multipass_score_only_rate'), 6)}",
            "outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv",
        ],
        [
            "hard-case multipass p95 per-pass k gate",
            f"{result.get('multipass_per_pass_k_accepts')} / {result.get('multipass_total')} = {fmt_num(result.get('multipass_per_pass_k_rate'), 6)}",
            "outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv",
        ],
        [
            "multiwindow 30s/60s/120s all-windows",
            mw_text,
            "outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv",
        ],
    ]
    path.write_text(
        latex_table(
            ["Experiment", "Controlled accept/reject result", "Source"],
            rows,
            "第6节 verifier 初步验证关键结果。这里的 accept/reject behavior 仅表示受控仿真设置下的判决结果。",
            "tab:section6_verifier_results",
        ),
        encoding="utf-8",
    )


def plot_altitude(path_png: Path, path_pdf: Path, fine: pd.DataFrame | None) -> bool:
    if fine is None:
        return False
    sub = fine[
        (fine["threshold_type"].astype(str) == "p95")
        & (fine["attack_type"].astype(str) == "same_plane_altitude_offset_fine")
    ].sort_values("attack_param_value")
    if sub.empty:
        return False
    plt.figure(figsize=(7.4, 4.4))
    plt.plot(sub["attack_param_value"], sub["score_only_accepts"], marker="o", label="score-only")
    plt.plot(sub["attack_param_value"], sub["per_target_k_p01_p99_accepts"], marker="s", label="score + per-target k p01-p99")
    plt.axvline(-2, color="#999999", linestyle="--", linewidth=1)
    plt.axvline(-1, color="#999999", linestyle="--", linewidth=1)
    plt.xlabel("Altitude perturbation delta_h_km")
    plt.ylabel("False accept count (p95, per 100 cases)")
    plt.title("Fine altitude sweep accept behavior")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path_png, dpi=180)
    plt.savefig(path_pdf)
    plt.close()
    return True


def plot_multiwindow(path_png: Path, path_pdf: Path, mw: pd.DataFrame | None) -> bool:
    if mw is None or mw.empty:
        return False
    x = list(range(len(mw)))
    width = 0.36
    plt.figure(figsize=(7.2, 4.4))
    plt.bar([i - width / 2 for i in x], mw["legit_accept_rate"], width=width, label="legit accept rate")
    plt.bar([i + width / 2 for i in x], mw["attack_accept_rate"], width=width, label="attack accept rate")
    plt.xticks(x, [f"{int(v)}s" for v in mw["window_length_s"]])
    plt.ylim(0, 1.0)
    plt.xlabel("Subwindow length")
    plt.ylabel("Accept rate (p95 all-windows)")
    plt.title("Hard-case temporal multiwindow summary")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path_png, dpi=180)
    plt.savefig(path_pdf)
    plt.close()
    return True


def source_label(path: str) -> str:
    return path.replace("\\", "/")


def write_facts(
    path: Path,
    audit: list[dict[str, Any]],
    result: dict[str, Any],
    extracted: dict[str, str],
    generated_figures: dict[str, bool],
) -> None:
    missing = [source_label(a["path"]) for a in audit if a["status"] == "missing"]
    audit_lines = []
    for item in audit:
        cols = item["columns"]
        support = "可支撑表格/图表" if item["status"] == "ok" else "missing"
        if item["status"] == "ok" and "fine_sweep_gate_summary" in item["path"]:
            support = "可支撑 fine altitude sweep 图与结果表"
        elif item["status"] == "ok" and "multiwindow_summary" in item["path"]:
            support = "可支撑 hard-case temporal 图与结果表"
        elif item["status"] == "ok" and "gate_ablation" in item["path"]:
            support = "可支撑 coarse verifier v2 消融表"
        elif item["status"] == "ok" and "forensic" in item["path"]:
            support = "可支撑 hard cases 机理说明"
        audit_lines.append(
            f"- `{source_label(item['path'])}`: {item['status']}, rows={item['rows']}, "
            f"fields={', '.join(cols[:12])}{'...' if len(cols) > 12 else ''}; {support}"
        )

    danger_text = ""
    danger = result.get("altitude_danger_rows")
    if isinstance(danger, pd.DataFrame) and not danger.empty:
        parts = []
        for row in danger.itertuples(index=False):
            parts.append(
                f"delta_h={row.attack_param_value:g} km: score-only {int(row.score_only_accepts)}/{int(row.total_sequences)}, "
                f"score+k {int(row.per_target_k_p01_p99_accepts)}/{int(row.total_sequences)}"
            )
        danger_text = "; ".join(parts)

    mw = result.get("multiwindow_all_windows")
    mw_text = ""
    if isinstance(mw, pd.DataFrame) and not mw.empty:
        mw_text = "; ".join(
            f"{int(row.window_length_s)}s legit={row.legit_accept_rate:.4f}, attack={row.attack_accept_rate:.4f}"
            for row in mw.itertuples(index=False)
        )

    text = f"""# 课程论文第 6 节实验事实整理

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 1. 实验目标

本节材料用于支撑《低轨卫星通信中的多普勒残差身份认证方法综述与研究方案》第 6 节“简单实现与初步验证”。目标是说明 claimed-identity Doppler residual verifier 已有一个可运行的 controlled Starlink TLE / station / Ku-band frequency baseline，并展示 score-only、score + fitted k_hat sanity gate、fine sweep 与 hard-case temporal stress test 下的 accept/reject behavior。

## 2. 受控仿真设置

- 场景：controlled Starlink TLE / station / frequency baseline，不是真实 Starlink SatNOGS observation replay。
- Station：lat=52.2100, lon=5.1600, alt=14 m。
- Simulation frequency：11.325 GHz。
- Residual terms：engineering effective residual model，使用 b、k、sigma main_range；frequency-scaled 或 residual terms 不解释为真实 Starlink Ku-band CFO 分布。
- Target set：{result.get('target_count', 20)}-target controlled Starlink baseline。

## 3. Verifier 定义

对 claimed target A，verifier 使用 claimed geometry `f_geo_A(t)`，计算 `delta_A(t)=f_obs(t)-f_geo_A(t)`；随后拟合 `b_hat+k_hat(t-t0)`，用 detrended residual RMSE 作为 score。score-only 判决为 `score <= threshold_A`，verifier v2 进一步加入 fitted `k_hat` 的 per-target/per-pass p01-p99 sanity gate。

## 4. 已核查 metrics / reports

{chr(10).join(audit_lines)}

Missing files：{', '.join(missing) if missing else '无'}。

## 5. 核心结果事实

- Coarse verifier v2 p95 score-only：{result.get('coarse_score_only_false_accepts')} / {result.get('coarse_score_only_total')} false accepts，来源 `outputs/metrics/verifier_v2_gate_ablation.csv`。
- Coarse verifier v2 p95 score + per-target k p01-p99 gate：{result.get('coarse_per_target_k_false_accepts')} / {result.get('coarse_per_target_k_total')} false accepts，来源 `outputs/metrics/verifier_v2_gate_ablation.csv`。
- Altitude fine sweep p95 score-only：{result.get('altitude_fine_score_only_false_accepts')} / {result.get('altitude_fine_total')} false accepts；score + per-target k p01-p99：{result.get('altitude_fine_per_target_k_false_accepts')} / {result.get('altitude_fine_total')} false accepts，来源 `outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv`。
- Fine altitude sweep 危险区域：{danger_text or 'NA'}。
- Phase fine sweep p95 score-only：{result.get('phase_fine_score_only_false_accepts')} / {result.get('phase_fine_total')} false accepts，来源 `outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv`。
- Hard-case forensic selected cases：{result.get('hard_case_count')}；最低 normalized score 约 {fmt_num(result.get('hard_case_min_normalized_score'), 4)}，来源 `outputs/metrics/verifier_v2_hard_case_forensic_summary.csv`。
- Hard-case multipass p95：score-only {result.get('multipass_score_only_accepts')} / {result.get('multipass_total')} = {fmt_num(result.get('multipass_score_only_rate'), 6)}；per-pass k gate {result.get('multipass_per_pass_k_accepts')} / {result.get('multipass_total')} = {fmt_num(result.get('multipass_per_pass_k_rate'), 6)}，来源 `outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv`。
- Multiwindow p95 all-windows：{mw_text or 'NA'}，来源 `outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv`。

## 6. 可直接写入论文第 6 节的要点

1. claimed-identity Doppler residual verifier 的基本流程已在受控仿真中实现：claimed target A -> `f_obs-f_geo_A` -> b+k 剖面拟合 -> residual RMSE score -> threshold accept/reject。
2. Coarse sweep 中 score-only 表现看似较好，但 fine altitude sweep 暴露出 delta_h=-1/-2 km 边界风险。
3. fitted `k_hat` sanity gate 能减少 false accept，但 fine sweep 和 hard-case temporal retest 表明它不是充分防线。
4. hard cases 更可能来自低仰角 pass、轨道几何曲线天然接近、b+k profile 吸收主要差异，而不是简单的 k_hat 贴边。
5. multi-pass / pass-quality-aware verifier 是更合理的后续增强方向；random short window 需要同时报告 legit accept rate 与 attack accept rate，不能单独宣称为强防御。

## 7. 禁止表述提醒

- 不要写成真实 Starlink observation replay。
- 不要写成真实攻击成功率。
- 不要把 frequency_scaled 或 effective residual terms 写成真实 Starlink Ku-band CFO 分布。
- 不要写 “accuracy=1 证明攻击无效”。
- 推荐使用：controlled setting 下的 accept/reject behavior、engineering effective residual model、claimed-identity Doppler verifier、score + fitted k_hat sanity gate、fine sweep / hard-case temporal stress test。

## 8. 自动计算与报告整理来源

- 自动计算：coarse gate ablation、altitude/phase fine sweep、hard-case multipass、multiwindow aggregate、hard-case forensic count。
- 从 README/reports 交叉核对：{extracted if extracted else '未依赖报告数字；reports 仅作为文字边界和结论核对'}。
- 图表生成：altitude fine sweep={generated_figures.get('altitude')}; hard-case temporal={generated_figures.get('temporal')}。
"""
    path.write_text(text, encoding="utf-8")


def write_appendix(path: Path) -> None:
    code = r'''\begin{lstlisting}[language=Python,caption={claimed-identity Doppler residual verifier 核心流程简化代码},label={lst:claimed_identity_verifier}]
import numpy as np

def fit_bias_slope_and_score(f_obs_hz, f_geo_A_hz, t_rel_s):
    """Paper appendix version, not the full engineering script."""
    t_centered = t_rel_s - np.mean(t_rel_s)
    delta_A = f_obs_hz - f_geo_A_hz

    design = np.column_stack([np.ones_like(t_centered), t_centered])
    coef, *_ = np.linalg.lstsq(design, delta_A, rcond=None)
    b_hat, k_hat = float(coef[0]), float(coef[1])

    fitted_profile = design @ coef
    residual = delta_A - fitted_profile
    score_rmse_hz = float(np.sqrt(np.mean(residual ** 2)))
    return score_rmse_hz, b_hat, k_hat, residual

def verify_claimed_identity(
    f_obs_hz,
    f_geo_A_hz,
    t_rel_s,
    score_threshold_hz,
    k_min_hz_s=None,
    k_max_hz_s=None,
):
    score, b_hat, k_hat, residual = fit_bias_slope_and_score(
        f_obs_hz, f_geo_A_hz, t_rel_s
    )
    score_ok = score <= score_threshold_hz

    if k_min_hz_s is None or k_max_hz_s is None:
        k_gate_ok = True
    else:
        k_gate_ok = (k_min_hz_s <= k_hat <= k_max_hz_s)

    accepted = bool(score_ok and k_gate_ok)
    return {
        "accepted": accepted,
        "score_rmse_hz": score,
        "b_hat_hz": b_hat,
        "k_hat_hz_s": k_hat,
        "score_ok": bool(score_ok),
        "k_gate_ok": bool(k_gate_ok),
    }

def sweep_thresholds(legit_scores, attack_scores, thresholds):
    rows = []
    for th in thresholds:
        legit_accept = np.asarray(legit_scores) <= th
        attack_accept = np.asarray(attack_scores) <= th
        rows.append({
            "threshold_hz": float(th),
            "false_reject_rate": float(1.0 - legit_accept.mean()),
            "false_accept_rate": float(attack_accept.mean()),
        })
    return rows
\end{lstlisting}
'''
    path.write_text(code, encoding="utf-8")


def write_section_draft(path: Path, result: dict[str, Any]) -> None:
    mw = result.get("multiwindow_all_windows")
    mw_text = "未读取到 multiwindow 汇总。"
    if isinstance(mw, pd.DataFrame) and not mw.empty:
        mw_text = "；".join(
            f"{int(r.window_length_s)} s all-windows 下 legit accept rate={r.legit_accept_rate:.4f}, attack accept rate={r.attack_accept_rate:.4f}"
            for r in mw.itertuples(index=False)
        )

    text = f"""## 6 简单实现与初步验证

### 6.1 实验设置

为验证本文提出的 claimed-identity Doppler residual verifier 至少具备一个可运行的实现，本节使用已有的 controlled Starlink TLE / station / Ku-band frequency baseline 进行整理。实验采用真实 Starlink TLE、受控地面站（lat=52.2100, lon=5.1600, alt=14 m）和 11.325 GHz simulation frequency，目标集合为 {result.get('target_count', 20)} 个 controlled Starlink target。观测曲线中的 b、k 与 sigma 来自 engineering effective residual model 的 main range，用于构造受控仿真中的 observation/model residual terms。该设置不是真实 Starlink SatNOGS observation replay，也不表示真实 Ku-band CFO 分布。

攻击或压力测试材料包括 coarse verifier v2 eval、same-plane altitude fine sweep、same-plane phase fine sweep，以及针对 fine sweep hard cases 的 temporal retest。相关输入主要来自 `outputs/metrics/verifier_v2_gate_ablation.csv`、`outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv`、`outputs/metrics/verifier_v2_hard_case_forensic_summary.csv`、`outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv` 和 `outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv`。

### 6.2 Verifier 实现

Verifier 的输入为 claimed target A、观测频率序列 `f_obs(t)` 和由 A 的 TLE / station / frequency 计算得到的几何基线 `f_geo_A(t)`。实现中先计算 `delta_A(t)=f_obs(t)-f_geo_A(t)`，再对 `delta_A(t)` 拟合 `b_hat+k_hat(t-t0)`，其中 `t0` 为当前时间窗的均值。扣除该线性 profile 后得到 residual，并以 residual RMSE 作为 verifier score。score-only 判决使用 per-target threshold：当 `score_A <= threshold_A` 时 accept，否则 reject。

Verifier v2 在 score 判决之后加入 fitted `k_hat` sanity gate。该 gate 使用合法受控样本估计每个 target 或每个 pass 的 `k_hat` p01-p99 区间；只有 score 通过且 `k_hat` 落在相应区间内时才 accept。这个 gate 的意义是约束 b+k profile 对异常慢变趋势的过度吸收，但它只是 sanity check，不是完整防线。

### 6.3 结果分析

首先，coarse verifier v2 构成了最小闭环。在 p95 threshold 下，score-only attack eval 出现 {result.get('coarse_score_only_false_accepts')} / {result.get('coarse_score_only_total')} false accepts；加入 score + per-target k p01-p99 gate 后为 {result.get('coarse_per_target_k_false_accepts')} / {result.get('coarse_per_target_k_total')} false accepts。该结果来自 `outputs/metrics/verifier_v2_gate_ablation.csv`。它说明基本流程可以运行，且 fitted k gate 能过滤 coarse sweep 中的一类异常样本，但不能据此宣称系统已安全。

其次，fine sweep 暴露出 score-only verifier 的边界风险。在 altitude fine sweep 的 p95 结果中，score-only false accepts 为 {result.get('altitude_fine_score_only_false_accepts')} / {result.get('altitude_fine_total')}；加入 score + per-target k p01-p99 gate 后仍有 {result.get('altitude_fine_per_target_k_false_accepts')} / {result.get('altitude_fine_total')}。其中 delta_h=-2 km 与 delta_h=-1 km 是较危险区域。相对地，phase fine sweep 在当前粒度下 score-only false accepts 为 {result.get('phase_fine_score_only_false_accepts')} / {result.get('phase_fine_total')}。这些数字来自 `outputs/metrics/verifier_v2_fine_sweep_gate_summary.csv`。因此，coarse sweep 中较好的表现不能替代 fine sweep 边界检查。

最后，hard-case temporal retest 显示这些边界样本不是简单的 k_hat 贴边问题。`outputs/metrics/verifier_v2_hard_case_forensic_summary.csv` 中 selected hard cases 为 {result.get('hard_case_count')} 个，最低 normalized score 约为 {fmt_num(result.get('hard_case_min_normalized_score'), 4)}；这些样本的风险主要来自特定 pass geometry 下 `f_geo_B(t)` 与 claimed `f_geo_A(t)` 天然接近，并且 b+k profile 能吸收主要差异。multi-pass p95 retest 中，score-only accepted 为 {result.get('multipass_score_only_accepts')} / {result.get('multipass_total')} = {fmt_num(result.get('multipass_score_only_rate'), 6)}，per-pass k gate accepted 为 {result.get('multipass_per_pass_k_accepts')} / {result.get('multipass_total')} = {fmt_num(result.get('multipass_per_pass_k_rate'), 6)}，来源 `outputs/metrics/verifier_v2_hard_case_multipass_sequence_eval.csv`。multiwindow 聚合结果为：{mw_text}，来源 `outputs/metrics/verifier_v2_hard_case_multiwindow_summary.csv`。这说明 temporal consistency 有潜力，但必须同时报告合法接受率与攻击接受率，不能把 random short window 单独表述为强防御。

### 6.4 小结

本节结果表明，claimed-identity Doppler residual verifier 在 controlled setting 下可以实现，并能完成从 `f_obs-f_geo_A`、b+k profile 拟合、residual RMSE scoring 到 threshold accept/reject 的基本闭环。与此同时，score-only verifier 并不充分；fitted `k_hat` sanity gate 能减少 false accept，但 fine altitude sweep 和 hard-case temporal retest 表明它不是充分防线。后续更合理的方向是 multi-pass verifier、pass-quality-aware verifier，以及在必要时引入 multi-station consistency。当前所有结果均为 controlled simulation baseline 下的 accept/reject behavior，不能解释为真实 Starlink observation replay 或真实攻击成功率。
"""
    path.write_text(text, encoding="utf-8")


def append_work_log(path: Path, outputs: list[Path], result: dict[str, Any], missing: list[str], commands: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    text = f"""
## {now} - 课程论文第6节 verifier artifacts 导出

### A. 本轮目标

基于已有 README、scripts、outputs/metrics、outputs/reports、outputs/figures，整理课程论文第 6 节“简单实现与初步验证”可直接引用的实验事实、LaTeX 表格、图表、附录代码片段和正文草稿。

### B. 实际操作

- 新增独立整理脚本 `scripts/export_course_paper_verifier_artifacts.py`。
- 只读取已有 metrics/reports，不重新运行 heavy simulation，不修改 outputs/metrics 原始结果。
- 自动汇总 coarse verifier v2、fine altitude/phase sweep、hard-case multipass 与 multiwindow 结果。
- 生成 `outputs/course_paper/` 下论文材料。

### C. 新增/修改文件

{chr(10).join(f'- `{source_label(str(p))}`' for p in outputs)}

### D. 运行命令

```bash
{chr(10).join(commands)}
```

### E. 结果摘要

- coarse p95 score-only false accepts = `{result.get('coarse_score_only_false_accepts')} / {result.get('coarse_score_only_total')}`。
- coarse p95 score + per-target k gate false accepts = `{result.get('coarse_per_target_k_false_accepts')} / {result.get('coarse_per_target_k_total')}`。
- altitude fine sweep p95 score-only false accepts = `{result.get('altitude_fine_score_only_false_accepts')} / {result.get('altitude_fine_total')}`；score + per-target k gate = `{result.get('altitude_fine_per_target_k_false_accepts')} / {result.get('altitude_fine_total')}`。
- phase fine sweep p95 score-only false accepts = `{result.get('phase_fine_score_only_false_accepts')} / {result.get('phase_fine_total')}`。
- hard-case multipass p95 score-only accepted = `{result.get('multipass_score_only_accepts')} / {result.get('multipass_total')}`；per-pass k gate accepted = `{result.get('multipass_per_pass_k_accepts')} / {result.get('multipass_total')}`。
- missing files = `{', '.join(missing) if missing else '无'}`。

### F. 问题与下一步

本轮未重新生成 dataset/candidate library，也未运行 matcher 或仿真。论文中建议引用 `table_experiment_settings.tex`、`table_verifier_results.tex`、`fig_altitude_fine_sweep_accepts.*` 与 `fig_hard_case_temporal_summary.*`，并明确这些结果是 controlled simulation baseline 下的 accept/reject behavior，不是真实 Starlink observation replay 或真实攻击成功率。
"""
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    args = parse_args()
    outputs = [
        args.output_dir / "course_paper_section6_facts.md",
        args.output_dir / "table_experiment_settings.tex",
        args.output_dir / "table_verifier_results.tex",
        args.output_dir / "fig_altitude_fine_sweep_accepts.png",
        args.output_dir / "fig_altitude_fine_sweep_accepts.pdf",
        args.output_dir / "fig_hard_case_temporal_summary.png",
        args.output_dir / "fig_hard_case_temporal_summary.pdf",
        args.output_dir / "appendix_c_code_snippet.tex",
        args.output_dir / "section6_draft.md",
    ]
    ensure_outputs(outputs, args.overwrite)

    audit: list[dict[str, Any]] = []
    data = {name: read_csv(args.metrics_dir / name, audit) for name in CORE_METRICS}
    reports = {name: read_text(args.reports_dir / name, audit) for name in CORE_REPORTS}
    read_text(Path("README.md"), audit)

    result = compute_results(data)
    extracted = extract_report_numbers(reports)
    cfg = load_yaml(args.orbit_config)
    param_cfg = load_yaml(args.parameter_config)

    write_settings_table(outputs[1], cfg, param_cfg, result)
    write_results_table(outputs[2], result)
    altitude_ok = plot_altitude(outputs[3], outputs[4], data.get("verifier_v2_fine_sweep_gate_summary.csv"))
    temporal_ok = plot_multiwindow(outputs[5], outputs[6], result.get("multiwindow_all_windows"))
    write_appendix(outputs[7])
    write_section_draft(outputs[8], result)
    write_facts(outputs[0], audit, result, extracted, {"altitude": altitude_ok, "temporal": temporal_ok})

    missing = [source_label(a["path"]) for a in audit if a["status"] == "missing"]
    append_work_log(
        Path("logs/work_log.md"),
        [Path("scripts/export_course_paper_verifier_artifacts.py"), *outputs],
        result,
        missing,
        ["python scripts/export_course_paper_verifier_artifacts.py --overwrite"],
    )

    print("wrote course paper artifacts:")
    for path in outputs:
        print(f"- {path}")
    print(f"altitude figure generated: {altitude_ok}")
    print(f"temporal figure generated: {temporal_ok}")
    print(f"missing files: {', '.join(missing) if missing else 'none'}")


if __name__ == "__main__":
    main()
