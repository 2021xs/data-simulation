"""A2 public-compensation and geometry-conditioned acceptance audit.

Reads existing realization data and evaluates a semi-analytic probability
model.  It creates no orbit geometries, observations, thresholds, or verifier.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from scipy.special import ndtr
from scipy.stats import binom, ncx2, spearmanr


plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


INPUTS = {
    "fixed": Path("outputs/datasets/fixed_geometry_multi_realization_dataset.csv"),
    "multipass": Path("outputs/datasets/same_pair_multi_pass_realization_dataset.csv"),
    "altitude": Path("outputs/datasets/controlled_altitude_difference_realization_dataset.csv"),
    "candidate_library": Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"),
    "parameter_config": Path("configs/simulation_parameter_config.yaml"),
}


def output_paths() -> dict[str, Path]:
    stem = "doppler_public_compensation_probability_audit"
    return {
        "math": Path(f"outputs/metrics/{stem}_public_compensation_math_audit.csv"),
        "distribution": Path(f"outputs/metrics/{stem}_environment_distribution_audit.csv"),
        "predictions": Path(f"outputs/metrics/{stem}_geometry_probability_predictions.csv"),
        "validation": Path(f"outputs/metrics/{stem}_validation_summary.csv"),
        "calibration": Path(f"outputs/metrics/{stem}_calibration_bins.csv"),
        "groups": Path(f"outputs/metrics/{stem}_group_validation.csv"),
        "strata": Path(f"outputs/metrics/{stem}_stratified_validation.csv"),
        "audit": Path(f"outputs/metrics/{stem}_correctness_audit.csv"),
        "manifest": Path(f"outputs/metrics/{stem}_manifest.json"),
        "report": Path(f"outputs/reports/{stem}_report.md"),
        "figures": Path(f"outputs/figures/{stem}"),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="A2公共补偿与geometry-conditioned接受概率审计")
    p.add_argument("--quadrature-order-sigma", type=int, default=32)
    p.add_argument("--quadrature-order-k", type=int, default=48)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()


def check_io(out: dict[str, Path], overwrite: bool) -> None:
    missing = [str(p) for p in INPUTS.values() if not p.exists()]
    if missing:
        raise SystemExit("missing existing input: " + ", ".join(missing))
    old = [str(p) for k, p in out.items() if k != "figures" and p.exists()]
    if out["figures"].exists() and any(out["figures"].iterdir()):
        old.append(str(out["figures"]))
    if old and not overwrite:
        raise SystemExit("audit output exists; add --overwrite: " + ", ".join(old))
    for k, p in out.items():
        (p if k == "figures" else p.parent).mkdir(parents=True, exist_ok=True)


def bool_col(s: pd.Series) -> pd.Series:
    return s if s.dtype == bool else s.astype(str).str.lower().eq("true")


def load_ranges() -> dict[str, tuple[float, float]]:
    cfg = yaml.safe_load(INPUTS["parameter_config"].read_text(encoding="utf-8"))
    p = cfg["parameters"]
    return {"b": tuple(map(float, p["b_hz"]["main_range"])),
            "k": tuple(map(float, p["k_hz_per_s"]["main_range"])),
            "sigma": tuple(map(float, p["sigma_hz"]["main_range"]))}


def normalize(source: str, path: Path, library_means: dict[str, float]) -> pd.DataFrame:
    d = pd.read_csv(path, low_memory=False)
    d = d[d.bk_mode.eq("current_bk")].copy()
    d["dataset_group"] = source
    rename = {}
    if "formal_score_value" in d: rename["formal_score_value"] = "score_hz"
    if "formal_score_hz" in d: rename["formal_score_hz"] = "score_hz"
    if "formal_score_threshold" in d: rename["formal_score_threshold"] = "score_threshold_hz"
    if "formal_score_threshold_hz" in d: rename["formal_score_threshold_hz"] = "score_threshold_hz"
    if "b_env" in d: rename["b_env"] = "b_env_hz"
    if "k_env" in d: rename["k_env"] = "k_env_hz_per_s"
    if "sigma_hz" in d: rename["sigma_hz"] = "noise_sigma_hz"
    d = d.rename(columns=rename)
    if source == "fixed_geometry":
        mask_mean = (pd.to_numeric(d.evaluation_start_s) + pd.to_numeric(d.evaluation_end_s)) / 2.0
        d["environment_time_offset_s"] = mask_mean - d.target_sat_id.astype(str).map(library_means)
        d["pair_id_for_group"] = d.physical_pair_id.astype(str)
        d["pass_id_for_group"] = d.service_area_id.astype(str)
        d["height_km"] = np.nan
        d["direction_or_selection_role"] = d.selection_group.astype(str)
    else:
        start = pd.to_datetime(d.pass_start_time, utc=True)
        end = pd.to_datetime(d.pass_end_time, utc=True)
        seg_start = pd.to_datetime(d.service_segment_start, utc=True)
        seg_end = pd.to_datetime(d.service_segment_end, utc=True)
        full_mid = start + (end-start)/2
        segment_mid = seg_start + (seg_end-seg_start)/2
        d["environment_time_offset_s"] = (segment_mid-full_mid).dt.total_seconds()
        d["pair_id_for_group"] = (d.physical_pair_id.astype(str) if "physical_pair_id" in d
                                   else "synthetic_altitude:" + d.target_sat_id.astype(str))
        d["pass_id_for_group"] = d.pass_id.astype(str)
        d["height_km"] = d.delta_h_km if "delta_h_km" in d else np.nan
        role = "direction_role" if "direction_role" in d else "direction_selection_role"
        d["direction_or_selection_role"] = d[role].astype(str)
    needed = ["geometry_condition_id", "observation_realization_id", "b_env_hz", "k_env_hz_per_s",
              "noise_sigma_hz", "unbounded_geometry_b_hat_hz", "unbounded_geometry_k_hat_hz_per_s",
              "unbounded_geometry_post_rmse_hz", "formal_b_hat_hz", "formal_b_center_hz",
              "formal_b_threshold_hz", "formal_k_hat_hz_per_s", "formal_k_center_hz_per_s",
              "formal_k_threshold_hz_per_s", "score_hz", "score_threshold_hz", "accept_flag",
              "coverage_gate_pass", "point_count"]
    missing = [c for c in needed if c not in d]
    if missing:
        raise SystemExit(f"{source} missing fields: {missing}")
    return d


def normal_uniform_interval_prob(lower: np.ndarray, upper: np.ndarray, umin: float, umax: float,
                                 sd: float) -> np.ndarray:
    """P(lower <= U+Z <= upper), U uniform, Z normal(0,sd^2)."""
    if sd <= 0:
        overlap = np.maximum(0.0, np.minimum(umax, upper) - np.maximum(umin, lower))
        return overlap / (umax-umin)
    def H(z: np.ndarray) -> np.ndarray:
        return z*ndtr(z) + np.exp(-0.5*z*z)/math.sqrt(2.0*math.pi)
    def avg_cdf(c: np.ndarray) -> np.ndarray:
        return sd*(H((c-umin)/sd)-H((c-umax)/sd))/(umax-umin)
    return np.clip(avg_cdf(upper)-avg_cdf(lower), 0.0, 1.0)


def nodes(order: int, lo: float, hi: float) -> tuple[np.ndarray, np.ndarray]:
    z, w = np.polynomial.legendre.leggauss(order)
    return lo+(z+1.0)*(hi-lo)/2.0, w/2.0


def predict_geometry(row: pd.Series, ranges: dict[str, tuple[float,float]], sigma_nodes: np.ndarray,
                     sigma_weights: np.ndarray, k_nodes: np.ndarray, k_weights: np.ndarray) -> dict[str, float]:
    n = int(row.point_count)
    # All formal datasets use consecutive 1-second samples; retain the formula explicitly.
    sxx = n*(n*n-1.0)/12.0
    dproj2 = n*float(row.unbounded_geometry_post_rmse_hz)**2
    bgeo = float(row.unbounded_geometry_b_hat_hz); kgeo = float(row.unbounded_geometry_k_hat_hz_per_s)
    bc = float(row.formal_b_center_hz); B = float(row.formal_b_threshold_hz)
    kc = float(row.formal_k_center_hz_per_s); K = float(row.formal_k_threshold_hz_per_s)
    tau = float(row.score_threshold_hz); dt = float(row.environment_time_offset_s)
    blo, bhi = ranges["b"]
    p_score = p_b = p_k = p_bk = p_all = 0.0
    for sigma, ws in zip(sigma_nodes, sigma_weights):
        sb = sigma/math.sqrt(n); sk = sigma/math.sqrt(sxx)
        ps = float(ncx2.cdf(n*tau*tau/(sigma*sigma), df=n-2, nc=dproj2/(sigma*sigma)))
        kval = k_nodes
        pk_given = ndtr((kc+K-kgeo-kval)/sk)-ndtr((kc-K-kgeo-kval)/sk)
        pb_given = normal_uniform_interval_prob(
            bc-B-bgeo-dt*kval, bc+B-bgeo-dt*kval, blo, bhi, sb)
        pk_s = float(np.sum(k_weights*pk_given)); pb_s = float(np.sum(k_weights*pb_given))
        pbk_s = float(np.sum(k_weights*pk_given*pb_given))
        p_score += ws*ps; p_b += ws*pb_s; p_k += ws*pk_s; p_bk += ws*pbk_s; p_all += ws*ps*pbk_s
    coverage = bool(row.coverage_gate_pass)
    if not coverage:
        p_all = 0.0
    return {"predicted_score_gate_probability":p_score, "predicted_b_gate_probability":p_b,
            "predicted_k_gate_probability":p_k, "predicted_bk_joint_probability":p_bk,
            "predicted_accept_probability":p_all,
            "bk_dependence_ratio":p_bk/max(p_b*p_k,1e-15), "D_proj_hz_l2":math.sqrt(dproj2),
            "time_sxx_s2":sxx}


def distribution_audit(datasets: list[pd.DataFrame], ranges: dict[str, tuple[float,float]]) -> pd.DataFrame:
    rows=[]
    for d in datasets:
        source=d.dataset_group.iloc[0]
        unique=d.drop_duplicates("observation_realization_id")
        corr=unique[["b_env_hz","k_env_hz_per_s","noise_sigma_hz"]].corr(method="spearman")
        expected_k=d.unbounded_geometry_k_hat_hz_per_s+d.k_env_hz_per_s
        k_noise=d.formal_k_hat_hz_per_s-expected_k
        expected_b=d.unbounded_geometry_b_hat_hz+d.b_env_hz+d.environment_time_offset_s*d.k_env_hz_per_s
        b_noise=d.formal_b_hat_hz-expected_b
        n=d.point_count.astype(float); sxx=n*(n*n-1)/12
        rows.append({"dataset_group":source,"realization_count":len(unique),
            "b_min":unique.b_env_hz.min(),"b_max":unique.b_env_hz.max(),
            "k_min":unique.k_env_hz_per_s.min(),"k_max":unique.k_env_hz_per_s.max(),
            "sigma_min":unique.noise_sigma_hz.min(),"sigma_max":unique.noise_sigma_hz.max(),
            "max_abs_environment_spearman":float(np.max(np.abs(corr.to_numpy()[np.triu_indices(3,1)]))),
            "normalized_b_noise_variance_ratio":float(np.var(b_noise,ddof=0)/np.mean(d.noise_sigma_hz**2/n)),
            "normalized_k_noise_variance_ratio":float(np.var(k_noise,ddof=0)/np.mean(d.noise_sigma_hz**2/sxx)),
            "b_environment_time_offset_min_s":d.environment_time_offset_s.min(),
            "b_environment_time_offset_max_s":d.environment_time_offset_s.max(),
            "main_ranges":json.dumps(ranges)})
    return pd.DataFrame(rows)


def build_predictions(datasets: list[pd.DataFrame], ranges: dict[str, tuple[float,float]], so: int, ko: int) -> pd.DataFrame:
    sn,sw=nodes(so,*ranges["sigma"]); kn,kw=nodes(ko,*ranges["k"])
    rows=[]
    for d in datasets:
        keys=["geometry_condition_id"]
        for gid,g in d.groupby(keys,sort=False):
            first=g.iloc[0]
            pred=predict_geometry(first,ranges,sn,sw,kn,kw)
            accepted=bool_col(g.accept_flag)
            n=len(g); p=float(pred["predicted_accept_probability"])
            lo=int(binom.ppf(.025,n,p)); hi=int(binom.ppf(.975,n,p))
            rows.append({"dataset_group":first.dataset_group,"geometry_condition_id":gid,
                "pair_id":first.pair_id_for_group,"target_id":str(first.target_sat_id),
                "pass_id":first.pass_id_for_group,"height_km":first.height_km,
                "realization_count":n,"observed_accept_count":int(accepted.sum()),
                "observed_accept_fraction":float(accepted.mean()),"binomial_95_count_lower":lo,
                "binomial_95_count_upper":hi,"observed_count_inside_theory_binomial_95":bool(lo<=accepted.sum()<=hi),
                "observed_score_gate_fraction":float(bool_col(g.score_gate_pass).mean()),
                "observed_b_gate_fraction":float(bool_col(g.b_gate_pass).mean()),
                "observed_k_gate_fraction":float(bool_col(g.k_gate_pass).mean()),
                "direction_or_selection_role":first.direction_or_selection_role,
                "raw_geo_rmse_hz":float(first.raw_geo_rmse_hz),
                "projected_geo_rmse_hz":float(first.unbounded_geometry_post_rmse_hz),
                "b_geo_hat_hz":float(first.unbounded_geometry_b_hat_hz),
                "k_geo_hat_hz_per_s":float(first.unbounded_geometry_k_hat_hz_per_s),
                "environment_time_offset_s":float(first.environment_time_offset_s),**pred})
    return pd.DataFrame(rows)


def summaries(pred: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    val=[]; bins=[]; groups=[]
    for source,d0 in pred.groupby("dataset_group"):
        d=d0.copy()
        if source=="controlled_altitude": d=d[d.height_km.ne(0)]
        err=d.predicted_accept_probability-d.observed_accept_fraction
        r=spearmanr(d.predicted_accept_probability,d.observed_accept_fraction) if d.observed_accept_fraction.nunique()>1 else None
        val.append({"dataset_group":source,"geometry_count":len(d),"prediction_mae":float(np.mean(abs(err))),
            "prediction_rmse":float(np.sqrt(np.mean(err**2))),"mean_predicted_accept_probability":d.predicted_accept_probability.mean(),
            "mean_observed_accept_fraction":d.observed_accept_fraction.mean(),
            "score_gate_probability_mae":float(np.mean(abs(d.predicted_score_gate_probability-d.observed_score_gate_fraction))),
            "b_gate_probability_mae":float(np.mean(abs(d.predicted_b_gate_probability-d.observed_b_gate_fraction))),
            "k_gate_probability_mae":float(np.mean(abs(d.predicted_k_gate_probability-d.observed_k_gate_fraction))),
            "spearman_predicted_vs_observed":float(r.statistic) if r else np.nan,
            "spearman_p":float(r.pvalue) if r else np.nan,
            "fraction_observed_counts_inside_theory_binomial_95":d.observed_count_inside_theory_binomial_95.mean()})
        d["probability_bin"]=pd.cut(d.predicted_accept_probability,[-1e-12,.2,.4,.6,.8,1.0],labels=["0-0.2","0.2-0.4","0.4-0.6","0.6-0.8","0.8-1.0"])
        for b,g in d.groupby("probability_bin",observed=False):
            bins.append({"dataset_group":source,"probability_bin":str(b),"geometry_count":len(g),
                "predicted_probability_mean":g.predicted_accept_probability.mean(),
                "observed_accept_fraction_mean":g.observed_accept_fraction.mean()})
        groupcol="target_id" if source=="controlled_altitude" else "pair_id"
        for group,g in d.groupby(groupcol):
            if len(g)>=3 and g.observed_accept_fraction.nunique()>1:
                rr=spearmanr(g.predicted_accept_probability,g.observed_accept_fraction)
                rho=float(rr.statistic); pv=float(rr.pvalue)
            else: rho=pv=np.nan
            groups.append({"dataset_group":source,"group_type":groupcol,"group_id":group,"geometry_count":len(g),
                "predicted_mean":g.predicted_accept_probability.mean(),"observed_mean":g.observed_accept_fraction.mean(),
                "mae":np.mean(abs(g.predicted_accept_probability-g.observed_accept_fraction)),
                "within_group_spearman":rho,"within_group_spearman_p":pv})
    return pd.DataFrame(val),pd.DataFrame(bins),pd.DataFrame(groups)


def stratified_validation(pred: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    specs=[("controlled_altitude",["height_km"],"signed_height"),
           ("controlled_altitude",["direction_or_selection_role"],"direction_role"),
           ("fixed_geometry",["direction_or_selection_role"],"selection_group"),
           ("same_pair_multi_pass",["pair_id","pass_id"],"pair_pass")]
    for source,cols,label in specs:
        d=pred[pred.dataset_group.eq(source)].copy()
        if source=="controlled_altitude": d=d[d.height_km.ne(0)]
        for key,g in d.groupby(cols,dropna=False,sort=True):
            vals=key if isinstance(key,tuple) else (key,)
            rows.append({"dataset_group":source,"stratum_type":label,
                "stratum_id":"|".join(map(str,vals)),"geometry_count":len(g),
                "predicted_accept_probability_mean":g.predicted_accept_probability.mean(),
                "observed_accept_fraction_mean":g.observed_accept_fraction.mean(),
                "absolute_error":abs(g.predicted_accept_probability.mean()-g.observed_accept_fraction.mean()),
                "predicted_score_gate_probability_mean":g.predicted_score_gate_probability.mean(),
                "predicted_b_gate_probability_mean":g.predicted_b_gate_probability.mean(),
                "predicted_k_gate_probability_mean":g.predicted_k_gate_probability.mean()})
    return pd.DataFrame(rows)


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False,floatfmt=".6g")


def figures(pred: pd.DataFrame, cal: pd.DataFrame, outdir: Path) -> None:
    fig,axes=plt.subplots(1,3,figsize=(15,4.5))
    for ax,(source,g) in zip(axes,pred.groupby("dataset_group")):
        if source=="controlled_altitude": g=g[g.height_km.ne(0)]
        ax.scatter(g.predicted_accept_probability,g.observed_accept_fraction,s=14,alpha=.5)
        ax.plot([0,1],[0,1],"k--",lw=1); ax.set_title(source); ax.set_xlabel("theory P(ACCEPT)"); ax.set_ylabel("observed fraction")
    fig.tight_layout(); fig.savefig(outdir/"predicted_vs_observed_acceptance.png",dpi=180); plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4.8))
    for source,g in cal.groupby("dataset_group"):
        ax.plot(g.predicted_probability_mean,g.observed_accept_fraction_mean,marker="o",label=source)
    ax.plot([0,1],[0,1],"k--",lw=1); ax.set_xlabel("mean predicted probability"); ax.set_ylabel("mean observed fraction"); ax.legend()
    fig.tight_layout(); fig.savefig(outdir/"probability_calibration.png",dpi=180); plt.close(fig)
    a=pred[(pred.dataset_group.eq("controlled_altitude")) & pred.height_km.ne(0)].copy()
    if len(a):
        z=a.groupby(a.height_km.abs()).agg(predicted=("predicted_accept_probability","mean"),observed=("observed_accept_fraction","mean")).reset_index()
        fig,ax=plt.subplots(figsize=(8,4.8)); ax.plot(z.height_km,z.predicted,marker="o",label="theory"); ax.plot(z.height_km,z.observed,marker="s",label="observed")
        ax.set_xscale("log"); ax.set_xlabel("|delta_h| km"); ax.set_ylabel("accept probability"); ax.legend(); fig.tight_layout()
        fig.savefig(outdir/"altitude_probability_theory_vs_observed.png",dpi=180); plt.close(fig)


def write_report(out:dict[str,Path],ranges:dict[str,tuple[float,float]],dist:pd.DataFrame,pred:pd.DataFrame,
                 val:pd.DataFrame,cal:pd.DataFrame,groups:pd.DataFrame,strata:pd.DataFrame,audit:pd.DataFrame)->None:
    report=f"""# A2 公共补偿攻击与 geometry-conditioned acceptance probability 理论审计

## 1. 范围

本轮没有生成新轨道、新观测或新 threshold，也没有修改 verifier。概率验证只读取 fixed geometry、same-pair multi-pass 和 controlled altitude 的 current_bk realization。

## 2. A1→A2 公共补偿

令 `ΔF_S(t)=F_A(S,t)-F_B(S,t)`，公共补偿 q 在 S 的残差为 `r_S(q)=q-ΔF_S`。A2 至少有三个不同目标：

- 平均损失 `min_q E_S[D(S,q)]`：对应攻击者知道区域站点分布并优化平均效果；若 D 为平方 projected energy，无约束时间轨迹的最优解是区域 `ΔF_S` 的均值，模 nuisance 子空间不唯一。
- 最坏站点 `min_q max_S D(S,q)`：对应攻击者希望覆盖整个区域，解是 projected curve 集合的 Chebyshev center，一般不等于某个物理 C 的曲线。
- 接受概率 `max_q P_S(ACCEPT|q)`：最贴近认证风险，但包含 score 与 b/k slabs，通常非凸，也不等同于平均能量最小。

当前 A1 `q_C=ΔF_C` 是 A2 的可行特例，不一般地是全局最优解。令 `S=C+Δx`、`ΔF_S≈ΔF_C+JΔx`，则 C 补偿消掉零阶项并留下 `r≈-JΔx`。投影后 `||Qr||²≈Δx^T(J^TQJ)Δx=Δx^TMΔx`。若 Ω 小、分布关于 C 对称且平方 projected energy 是目标，则 `E[Δx]=0`，q_C 是一阶平均意义最优；期望剩余能量为 `tr(M Cov(Δx))`。当前 C 是服务段固定代表点，不保证等于真实站点分布的空间质心，因此这只是带条件的局部解释。

## 3. A1/A2/A3 层级

- A1：固定 C 和 `q_C`，位置知识最弱，残差由 S-C 空间差产生。
- A2：知道 `S∈Ω` 并优化一条公共 q；知识和控制更强，但一个 q 通常不能同时消除所有 S 的差异。
- A3：知道真实 S 且可逐时刻自由控制 q，取 `q*=ΔF_S` 后标量 Doppler residual 为零，形成模型内严格不可识别性。

A3 仍不代表现实攻击者具备完美站址/轨道/同步、无限控制带宽或任意协议能力。

## 4. 代码一致的随机模型

代码从 main ranges 独立均匀采样：`b_env∼U{ranges['b']}` Hz、`k_env∼U{ranges['k']}` Hz/s、`σ∼U{ranges['sigma']}` Hz；给定 σ 后逐点噪声 `n∼N(0,σ²I)`。这是一阶工程近似，不声称真实噪声严格 iid Gaussian。

在 mask-centered `x=t-mean(t)` 下：

`b_hat=b_geo+b_env+Δt·k_env+ζ_b`，`k_hat=k_geo+k_env+ζ_k`；条件于 σ，`ζ_b∼N(0,σ²/N)`、`ζ_k∼N(0,σ²/(x^Tx))`，且与 projected noise `Qn` 正交独立。Δt 是 environment t0 与 mask 均值之差，因此 b/k gate 通过共享 k_env 而相关。

score 条件分布满足：`N·score²/σ² ∼ χ'²_{{N-2}}(λ)`，其中 `λ=D_proj²/σ²`。本轮用确定性 Gauss–Legendre 对 σ 和 k_env 积分，并解析积分 b_env；没有生成 Monte Carlo realization。

## 5. 生成分布数值审计

{md(dist)}

noise coefficient 的归一化方差比应接近 1；偏差来自有限已有 realization，而不是另行拟合分布。

## 6. 概率验证

{md(val)}

`P_accept` 使用 score 与 b/k 联合 gate 的条件概率乘积再对 σ 积分；不是训练出来的预测器。有限的 20/30 realization 使 observed fraction 本身有明显二项抽样误差，因此同时报告观测计数是否落在理论二项 95% 区间。

## 7. 各组成量

- D_proj 决定 score 非中心参数；D_proj 越大，score gate 概率通常越低。
- b_geo 决定 b 分布相对 b slab 的位置，并受 Δt·k_env 平移。
- k_geo 决定 k 分布相对 k slab 的位置，是既有 k-boundary 翻转的直接几何项。
- environment uniform distribution 决定 coefficient 在 slabs 中的覆盖概率。
- σ 同时控制 score、bnoise、knoise，边际上三个 gate 并非完全独立；本轮在给定 σ 后联合，再对 σ 积分。
- coverage 不通过时理论接受概率置零。

分 gate MAE 已列入 validation summary。高度、方向、固定几何 selection group 以及 same-pair/pass 的预测—观测分层结果见 `doppler_public_compensation_probability_audit_stratified_validation.csv`；没有只依赖 pooled correlation。

## 8. 为什么同一 geometry 会翻转

geometry 固定只固定 D_proj、b_geo、k_geo。每次 realization 重新抽取 b_env、k_env、σ 和 n，使 score 与 coefficient margins 改变。尤其 k_geo 靠近 k slab 边界时，k_env 和 noise slope 会把 k_hat 推过边界；这不是 geometry 本身随机。

## 9. 理论价值与限制

现有结果支持形成 `geometry-conditioned probabilistic identity verification boundary`：geometry 给出非中心 score 和 coefficient 均值位置，environment/noise 给出接受概率。但这不是普适真实世界概率，因为 b/k/σ 分布来自工程 main_range baseline，threshold 也是有限校准样本的实现值。

其他限制：A2 尚未求解真实服务区优化；C 未证明是区域质心；没有建模相关/有色噪声、TLE 不确定性或攻击控制误差；没有训练分类器，也没有提出新防御。

## 10. 正确性审计

{md(audit)}
"""
    out["report"].write_text(report,encoding="utf-8")


def main()->None:
    args=parse_args(); out=output_paths(); check_io(out,args.overwrite); ranges=load_ranges()
    lib=pd.read_csv(INPUTS["candidate_library"],low_memory=False)
    means=(lib[lib.target_norad_id.astype(str).eq(lib.candidate_norad_id.astype(str))]
           .groupby(lib.target_norad_id.astype(str)).t_rel_s.mean().to_dict())
    datasets=[normalize("fixed_geometry",INPUTS["fixed"],means),normalize("same_pair_multi_pass",INPUTS["multipass"],means),
              normalize("controlled_altitude",INPUTS["altitude"],means)]
    dist=distribution_audit(datasets,ranges)
    pred=build_predictions(datasets,ranges,args.quadrature_order_sigma,args.quadrature_order_k)
    pred_hi=build_predictions(datasets,ranges,args.quadrature_order_sigma+8,args.quadrature_order_k+12)
    convergence_max=float(np.max(np.abs(pred.predicted_accept_probability-pred_hi.predicted_accept_probability)))
    val,cal,groups=summaries(pred); strata=stratified_validation(pred)
    math_rows=pd.DataFrame([
        {"item":"A2_mean_squared_projected","result":"q=E[DeltaF_S] modulo col(G); q_C first-order optimum only for small symmetric Omega centered at C"},
        {"item":"A2_minimax","result":"projected-curve Chebyshev center; not generally q_C"},
        {"item":"A2_accept_probability","result":"verifier-aware nonconvex objective involving projected score and centered b/k slabs"},
        {"item":"local_C_residual","result":"r(C+dx,q_C)=-J dx + O(||dx||^2); projected energy=dx^T M dx"},
        {"item":"A3_boundary","result":"q*=DeltaF_S makes scalar Doppler residual exactly zero inside the abstract model"},
    ])
    max_range_violation=0
    for d in datasets:
        max_range_violation+=int((~d.b_env_hz.between(*ranges["b"])).sum()+(~d.k_env_hz_per_s.between(*ranges["k"])).sum()+(~d.noise_sigma_hz.between(*ranges["sigma"])).sum())
    audit=pd.DataFrame([
        {"check":"no new geometry or realization generated","passed":True,"observed":"deterministic integration over existing geometry"},
        {"check":"all environment samples inside configured main ranges","passed":max_range_violation==0,"observed":max_range_violation},
        {"check":"probabilities finite and in [0,1]","passed":bool(np.isfinite(pred.predicted_accept_probability).all() and pred.predicted_accept_probability.between(0,1).all()),"observed":f"{pred.predicted_accept_probability.min():.6g}..{pred.predicted_accept_probability.max():.6g}"},
        {"check":"all three existing datasets represented","passed":pred.dataset_group.nunique()==3,"observed":pred.dataset_group.nunique()},
        {"check":"current_bk only and one prediction per geometry","passed":len(pred)==sum(d.geometry_condition_id.nunique() for d in datasets),"observed":len(pred)},
        {"check":"quadrature orders recorded","passed":args.quadrature_order_sigma>=12 and args.quadrature_order_k>=16,"observed":f"sigma={args.quadrature_order_sigma},k={args.quadrature_order_k}"},
        {"check":"probability quadrature converged under higher orders","passed":convergence_max<1e-8,"observed":convergence_max},
    ])
    figures(pred,cal,out["figures"])
    math_rows.to_csv(out["math"],index=False,encoding="utf-8-sig"); dist.to_csv(out["distribution"],index=False,encoding="utf-8-sig")
    pred.to_csv(out["predictions"],index=False,encoding="utf-8-sig"); val.to_csv(out["validation"],index=False,encoding="utf-8-sig")
    cal.to_csv(out["calibration"],index=False,encoding="utf-8-sig"); groups.to_csv(out["groups"],index=False,encoding="utf-8-sig")
    strata.to_csv(out["strata"],index=False,encoding="utf-8-sig")
    audit.to_csv(out["audit"],index=False,encoding="utf-8-sig")
    manifest={"audit":"doppler_public_compensation_probability","created_at":datetime.now().isoformat(),"new_geometry_generated":False,
              "new_realization_generated":False,"threshold_recalibrated":False,"verifier_modified":False,
              "quadrature":{"sigma_order":args.quadrature_order_sigma,"k_order":args.quadrature_order_k},
              "quadrature_convergence_max_abs_probability_difference":convergence_max,
              "ranges":ranges,"input_files":{k:str(v) for k,v in INPUTS.items()},"audit_all_passed":bool(audit.passed.all())}
    out["manifest"].write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    write_report(out,ranges,dist,pred,val,cal,groups,strata,audit)
    print(f"geometry_predictions={len(pred)} audit={int(audit.passed.sum())}/{len(audit)}")


if __name__=="__main__": main()
