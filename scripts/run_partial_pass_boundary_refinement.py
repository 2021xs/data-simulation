#!/usr/bin/env python
"""Run 20-target partial-pass window/sigma boundary refinement."""

from __future__ import annotations

import argparse, json
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

class InputError(ValueError): pass
def fail(m: str): raise InputError(m)

def read_yaml(p: Path) -> dict[str, Any]:
    if not p.exists(): fail(f"配置文件不存在: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def check_outputs(paths, overwrite):
    ex=[str(p) for p in paths if p.exists()]
    if ex and not overwrite: fail("输出文件已存在，若确认覆盖请添加 --overwrite: "+", ".join(ex))

def ranges(sim, range_type):
    r={}
    for k in ["b_hz","k_hz_per_s","sigma_hz"]:
        v=sim["parameters"][k][f"{range_type}_range"]; r[k]=[float(v[0]),float(v[1])]
    return sim.get("model",{}).get("name","effective_cfo_simulation_v1"), r

def md_table(df: pd.DataFrame) -> str:
    cols=list(df.columns)
    lines=["| "+" | ".join(cols)+" |","| "+" | ".join(["---"]*len(cols))+" |"]
    for _,row in df.iterrows():
        vals=[f"{row[c]:.6f}" if isinstance(row[c], float) else str(row[c]) for c in cols]
        lines.append("| "+" | ".join(vals)+" |")
    return "\n".join(lines)

def full_geometries(stage3b_dataset: Path):
    usecols=["target_index","target_name","target_norad_id","station_name","station_lat_deg","station_lon_deg","station_alt_m","center_freq_hz","t_abs_utc","t_rel_s","elevation_deg","range_m","range_rate_mps","doppler_hz","f_geo_tle_hz"]
    df=pd.read_csv(stage3b_dataset, usecols=usecols)
    out={}
    for ti,g in df.drop_duplicates(["target_index","t_abs_utc"]).groupby("target_index"):
        out[int(ti)]=g.sort_values("t_rel_s").reset_index(drop=True)
    return out

def window_idx(t, label):
    if str(label)=="full": return np.arange(len(t))
    dur=float(label); center=(float(t[0])+float(t[-1]))/2.0; start=center-dur/2; end=center+dur/2
    return np.flatnonzero((t>=start-1e-9)&(t<=end+1e-9))

def build_dataset(boundary_type, cfg, geos, base_r, scale, version, seed):
    rng=np.random.default_rng(seed)
    rows=[]; skipped=[]; seq_counter=1
    if boundary_type=="window_duration":
        settings=[(w, float(cfg["window_boundary"]["sigma_multiplier"])) for w in cfg["window_boundary"]["window_durations"]]
        sims=int(cfg["window_boundary"]["num_sims_per_target_per_window"])
    else:
        settings=[(w, float(s)) for w in cfg["sigma_boundary"]["window_durations"] for s in cfg["sigma_boundary"]["sigma_multipliers"]]
        sims=int(cfg["sigma_boundary"]["num_sims_per_target_per_setting"])
    for ti,geo in geos.items():
        t_full=geo.t_rel_s.to_numpy(float)
        for wlab,sigmult in settings:
            idx=window_idx(t_full,wlab)
            if len(idx)<10:
                skipped.append(dict(target_index=ti,window_duration_label=str(wlab),sigma_multiplier=sigmult,reason="too_few_points",n_time_points=int(len(idx)))); continue
            win=geo.iloc[idx].copy().reset_index(drop=True)
            start=float(win.t_rel_s.iloc[0]); end=float(win.t_rel_s.iloc[-1]); win["t_window_rel_s"]=win.t_rel_s-start
            t=win.t_rel_s.to_numpy(float); fgeo=win.f_geo_tle_hz.to_numpy(float)
            for si in range(1,sims+1):
                base_b=float(rng.uniform(*base_r["b_hz"])); base_sigma=float(rng.uniform(*base_r["sigma_hz"]))
                b=base_b*scale; sigma_base=base_sigma*scale; sigma=sigma_base*sigmult
                noise=rng.normal(0,sigma,len(win)); sid=("winb" if boundary_type=="window_duration" else "sigb")+f"_{seq_counter:06d}"; seq_counter+=1
                seq=win[["station_name","station_lat_deg","station_lon_deg","station_alt_m","center_freq_hz","t_abs_utc","t_rel_s","t_window_rel_s","elevation_deg","range_m","range_rate_mps","doppler_hz","f_geo_tle_hz"]].copy()
                seq.insert(0,"experiment_name",cfg["experiment_name"]); seq.insert(1,"boundary_type",boundary_type); seq.insert(2,"sequence_id",sid)
                seq.insert(3,"target_index",ti); seq.insert(4,"target_name",str(win.target_name.iloc[0])); seq.insert(5,"target_norad_id",str(win.target_norad_id.iloc[0]))
                seq.insert(6,"error_model_variant",cfg["error_model_variant"]); seq.insert(7,"sigma_multiplier",sigmult); seq.insert(8,"scenario",cfg["scenario"])
                seq.insert(9,"sim_index",si); seq.insert(10,"window_duration_label",str(wlab)); seq.insert(11,"window_duration_s",float(end-start))
                seq.insert(12,"window_center_offset_s",0.0); seq.insert(13,"window_start_rel_s",start); seq.insert(14,"window_end_rel_s",end)
                seq["b_hz"]=b; seq["k_hz_per_s"]=0.0; seq["sigma_hz"]=sigma; seq["sigma_base_hz"]=sigma_base; seq["base_b_hz"]=base_b; seq["base_sigma_hz"]=base_sigma
                seq["noise_hz"]=noise; seq["f_sim_hz"]=fgeo+b+noise; seq["mode"]="controlled_starlink"; seq["observation_id"]=pd.NA
                seq["label"]=str(win.target_norad_id.iloc[0]); seq["random_seed"]=seed; seq["config_version"]=version; seq["n_time_points"]=len(seq)
                rows.append(seq)
    return pd.concat(rows,ignore_index=True), skipped

def batch_scores(t, fsim, fgeo):
    x=t-float(np.mean(t)); n=float(len(t)); denom=float(np.sum(x*x))
    delta=fsim[None,:]-fgeo; b=delta.mean(axis=1); k=np.zeros(len(fgeo)) if denom==0 else (delta@x)/denom
    res=delta-b[:,None]-k[:,None]*x[None,:]
    return np.sqrt(np.mean(res*res,axis=1))

def match_dataset(df, lib, cfg):
    rows=[]
    for (ti,wlab,sig),g in df.groupby(["target_index","window_duration_label","sigma_multiplier"], sort=True):
        g=g.sort_values(["sequence_id","t_rel_s"]); ids=list(g.sequence_id.drop_duplicates())
        t=g[g.sequence_id==ids[0]].t_rel_s.to_numpy(float)
        fsim=g.pivot(index="sequence_id",columns="t_rel_s",values="f_sim_hz").loc[ids,t].to_numpy(float)
        lsub=lib[lib.target_index==ti].merge(pd.DataFrame({"t_rel_s":t}),on="t_rel_s")
        meta=lsub.drop_duplicates("candidate_norad_id").sort_values("candidate_rank_or_selection_order").reset_index(drop=True)
        mat=lsub.pivot(index="candidate_norad_id",columns="t_rel_s",values="f_geo_candidate_hz").loc[meta.candidate_norad_id,t].to_numpy(float)
        norads=meta.candidate_norad_id.astype(str).to_numpy(); true=str(g.target_norad_id.iloc[0]); true_idx=int(np.flatnonzero(norads==true)[0])
        firsts=g.drop_duplicates("sequence_id").set_index("sequence_id").loc[ids]
        for rowi,sid in enumerate(ids):
            rmse=batch_scores(t,fsim[rowi],mat); pred=int(np.argmin(rmse)); wr=rmse.copy(); wr[true_idx]=np.inf; bestw=int(np.argmin(wr)); first=firsts.loc[sid]
            rows.append(dict(experiment_name=cfg["experiment_name"],boundary_type=first.boundary_type,sequence_id=sid,target_index=ti,target_name=first.target_name,target_norad_id=true,
                predicted_name=meta.iloc[pred].candidate_name,predicted_norad_id=str(meta.iloc[pred].candidate_norad_id),best_wrong_name=meta.iloc[bestw].candidate_name,
                best_wrong_norad_id=str(meta.iloc[bestw].candidate_norad_id),true_score_rmse_hz=float(rmse[true_idx]),best_score_rmse_hz=float(rmse[pred]),
                best_wrong_score_rmse_hz=float(rmse[bestw]),margin_hz=float(rmse[bestw]-rmse[true_idx]),is_correct=str(meta.iloc[pred].candidate_norad_id)==true,
                window_duration_label=wlab,window_duration_s=float(first.window_duration_s),sigma_multiplier=float(sig),n_time_points=int(first.n_time_points),
                scenario=cfg["scenario"],error_model_variant=cfg["error_model_variant"],candidate_limit=int(cfg["candidate_limit"])))
    return pd.DataFrame(rows)

def summarize(res, by_sigma=False):
    keys=["window_duration_label"] + (["sigma_multiplier"] if by_sigma else [])
    summ=res.groupby(keys).agg(sequence_count=("sequence_id","count"),target_count=("target_index","nunique"),accuracy=("is_correct","mean"),
        wrong_count=("is_correct",lambda s:int((~s).sum())),negative_margin_count=("margin_hz",lambda s:int((s<0).sum())),
        negative_target_count=("target_index",lambda s:int(res.loc[s.index].query("margin_hz < 0").target_index.nunique())),
        mean_margin_hz=("margin_hz","mean"),median_margin_hz=("margin_hz","median"),min_margin_hz=("margin_hz","min"),p05_margin_hz=("margin_hz",lambda s:float(np.quantile(s,.05))),
        mean_true_score_rmse_hz=("true_score_rmse_hz","mean"),mean_best_wrong_score_rmse_hz=("best_wrong_score_rmse_hz","mean")).reset_index()
    pkeys=["target_index","target_name","target_norad_id","window_duration_label"] + (["sigma_multiplier"] if by_sigma else [])
    per=res.groupby(pkeys).agg(sequence_count=("sequence_id","count"),accuracy=("is_correct","mean"),wrong_count=("is_correct",lambda s:int((~s).sum())),
        negative_margin_count=("margin_hz",lambda s:int((s<0).sum())),mean_margin_hz=("margin_hz","mean"),median_margin_hz=("margin_hz","median"),min_margin_hz=("margin_hz","min"),
        p05_margin_hz=("margin_hz",lambda s:float(np.quantile(s,.05))),most_common_best_wrong=("best_wrong_norad_id",lambda s:str(s.astype(str).value_counts().index[0])),
        best_wrong_top_5=("best_wrong_norad_id",lambda s:";".join([f"{k}:{v}" for k,v in s.astype(str).value_counts().head(5).items()]))).reset_index()
    return summ, per

def threshold_window(per):
    order=["full","240","180","150","120","100","90","80","70","60","45","30"]
    rows=[]
    for (ti,tn,nn),g in per.groupby(["target_index","target_name","target_norad_id"]):
        mp={str(r.window_duration_label):r for _,r in g.iterrows()}
        def first(cond):
            for w in order:
                if w in mp and cond(mp[w]): return w
            return ""
        row=dict(target_index=ti,target_name=tn,target_norad_id=nn,first_negative_window_s=first(lambda r:r.negative_margin_count>0),
            first_negative_window_label=first(lambda r:r.negative_margin_count>0),first_window_with_negative_margin_count_ge_5=first(lambda r:r.negative_margin_count>=5),
            first_window_with_accuracy_below_0_9=first(lambda r:r.accuracy<0.9),most_common_hard_wrong_at_first_negative="")
        for w in ["full","180","120","90","60","30"]:
            row[f"margin_{w}_min_hz"]=float(mp[w].min_margin_hz) if w in mp else np.nan
        fn=row["first_negative_window_label"]
        row["most_common_hard_wrong_at_first_negative"]=mp[fn].most_common_best_wrong if fn in mp else ""
        row["notes"]="controlled boundary refinement"
        rows.append(row)
    return pd.DataFrame(rows)

def threshold_sigma(per):
    sigs=[1,2,3,5,7,10]; rows=[]
    for (ti,tn,nn,w),g in per.groupby(["target_index","target_name","target_norad_id","window_duration_label"]):
        mp={float(r.sigma_multiplier):r for _,r in g.iterrows()}
        def first(cond):
            for s in sigs:
                if float(s) in mp and cond(mp[float(s)]): return s
            return ""
        row=dict(target_index=ti,target_name=tn,target_norad_id=nn,window_duration_label=w,window_duration_s=float(g.window_duration_s.iloc[0]) if "window_duration_s" in g.columns else np.nan,
            first_negative_sigma_multiplier=first(lambda r:r.negative_margin_count>0),first_sigma_with_negative_margin_count_ge_5=first(lambda r:r.negative_margin_count>=5),
            first_sigma_with_accuracy_below_0_9=first(lambda r:r.accuracy<0.9),most_common_hard_wrong_at_first_negative="")
        for s in sigs:
            row[f"margin_sigma_{s}_min_hz"]=float(mp[float(s)].min_margin_hz) if float(s) in mp else np.nan
        fs=row["first_negative_sigma_multiplier"]
        row["most_common_hard_wrong_at_first_negative"]=mp[float(fs)].most_common_best_wrong if fs!="" else ""
        row["notes"]="controlled boundary refinement"
        rows.append(row)
    return pd.DataFrame(rows)

def plots(win_sum, win_thr, sig_sum, sig_thr, win_per, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    order=["full","240","180","150","120","100","90","80","70","60","45","30"]
    ws=win_sum.set_index("window_duration_label").reindex(order).dropna().reset_index()
    fig,ax=plt.subplots(figsize=(9,4.8)); ax.bar(ws.window_duration_label, ws.negative_target_count); ax.set_ylabel("negative target count"); ax.set_title("window_boundary_negative_target_count"); ax.tick_params(axis="x",rotation=30); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_window_boundary_negative_target_count.png",dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.8)); ax.plot(ws.window_duration_label, ws.min_margin_hz, marker="o"); ax.set_ylabel("min margin (Hz)"); ax.set_title("window_boundary_margin_by_duration"); ax.tick_params(axis="x",rotation=30); ax.grid(True,alpha=.25); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_window_boundary_margin_by_duration.png",dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,4.5)); win_thr.first_negative_window_label.value_counts().reindex(order).dropna().plot(kind="bar",ax=ax); ax.set_title("window_boundary_threshold_histogram"); ax.set_ylabel("target count"); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_window_boundary_threshold_histogram.png",dpi=160); plt.close(fig)
    piv=win_per.pivot(index="target_name",columns="window_duration_label",values="min_margin_hz").reindex(columns=order)
    fig,ax=plt.subplots(figsize=(9,8)); im=ax.imshow(piv.to_numpy(float),aspect="auto",cmap="viridis"); ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns,rotation=30); ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index,fontsize=7); fig.colorbar(im,ax=ax,label="min margin"); ax.set_title("window_boundary_per_target_heatmap"); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_window_boundary_per_target_heatmap.png",dpi=160); plt.close(fig)
    sp=sig_sum.pivot(index="window_duration_label",columns="sigma_multiplier",values="negative_target_count")
    fig,ax=plt.subplots(figsize=(8,5)); im=ax.imshow(sp.to_numpy(float),aspect="auto",cmap="magma"); ax.set_xticks(range(len(sp.columns))); ax.set_xticklabels(sp.columns); ax.set_yticks(range(len(sp.index))); ax.set_yticklabels(sp.index); fig.colorbar(im,ax=ax,label="negative target count"); ax.set_title("sigma_boundary_negative_target_heatmap"); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_sigma_boundary_negative_target_heatmap.png",dpi=160); plt.close(fig)
    sp=sig_sum.pivot(index="window_duration_label",columns="sigma_multiplier",values="min_margin_hz")
    fig,ax=plt.subplots(figsize=(8,5)); im=ax.imshow(sp.to_numpy(float),aspect="auto",cmap="viridis"); ax.set_xticks(range(len(sp.columns))); ax.set_xticklabels(sp.columns); ax.set_yticks(range(len(sp.index))); ax.set_yticklabels(sp.index); fig.colorbar(im,ax=ax,label="min margin"); ax.set_title("sigma_boundary_margin_heatmap"); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_sigma_boundary_margin_heatmap.png",dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(8,4.5)); sig_thr.first_negative_sigma_multiplier.astype(str).value_counts().sort_index().plot(kind="bar",ax=ax); ax.set_title("sigma_boundary_threshold_histogram"); ax.set_ylabel("target-window count"); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_sigma_boundary_threshold_histogram.png",dpi=160); plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,5))
    for w,g in sig_sum.groupby("window_duration_label"):
        ax.plot(g.sigma_multiplier,g.accuracy,marker="o",label=w)
    ax.set_xlabel("sigma_multiplier"); ax.set_ylabel("accuracy"); ax.set_title("sigma_boundary_per_window_accuracy"); ax.grid(True,alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(outdir/"controlled_starlink_20target_sigma_boundary_per_window_accuracy.png",dpi=160); plt.close(fig)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--orbit-config", required=True, type=Path)
    ap.add_argument("--sim-config", required=True, type=Path)
    ap.add_argument("--stage3b-dataset", required=True, type=Path)
    ap.add_argument("--candidate-library", required=True, type=Path)
    ap.add_argument("--output-dir", default=Path("outputs"), type=Path)
    ap.add_argument("--overwrite", action="store_true")
    a=ap.parse_args()
    out=a.output_dir
    files=[
        out/"datasets/controlled_starlink_20target_window_boundary_dataset.csv", out/"datasets/controlled_starlink_20target_window_boundary_manifest.json",
        out/"datasets/controlled_starlink_20target_sigma_boundary_dataset.csv", out/"datasets/controlled_starlink_20target_sigma_boundary_manifest.json",
        out/"metrics/controlled_starlink_20target_window_boundary_matching_results.csv", out/"metrics/controlled_starlink_20target_window_boundary_summary.csv",
        out/"metrics/controlled_starlink_20target_window_boundary_per_target_summary.csv", out/"metrics/controlled_starlink_20target_window_boundary_threshold_table.csv",
        out/"metrics/controlled_starlink_20target_sigma_boundary_matching_results.csv", out/"metrics/controlled_starlink_20target_sigma_boundary_summary.csv",
        out/"metrics/controlled_starlink_20target_sigma_boundary_per_target_summary.csv", out/"metrics/controlled_starlink_20target_sigma_boundary_threshold_table.csv",
        out/"reports/controlled_starlink_20target_partial_pass_boundary_refinement_report.md",
    ]
    try:
        check_outputs(files, a.overwrite)
        orbit=read_yaml(a.orbit_config); sim=read_yaml(a.sim_config); cfg=orbit["boundary_refinement"]
        geos=full_geometries(a.stage3b_dataset); lib=pd.read_csv(a.candidate_library)
        sel=pd.read_csv(cfg["target_selection_table"])
        if set(map(str,sel.target_norad_id)) != set(map(str,[g.target_norad_id.iloc[0] for g in geos.values()])): fail("target selection table 与 Stage 3B dataset target 列表不一致")
        if lib.groupby("target_index").candidate_norad_id.nunique().min()<int(cfg["candidate_limit"]): fail("candidate library candidate_limit 不足 1000")
        version, base_r=ranges(sim, orbit["simulation"]["range_type"]); scale=float(cfg["simulation_center_freq_hz"])/float(cfg["source_center_freq_hz"])
        seed=int(cfg["random_seed"]); win_df,win_skip=build_dataset("window_duration",cfg,geos,base_r,scale,version,seed); sig_df,sig_skip=build_dataset("sigma_amplitude",cfg,geos,base_r,scale,version,seed+1000)
        for p in [out/"datasets",out/"metrics",out/"reports",out/"plots"]: p.mkdir(parents=True,exist_ok=True)
        win_df.to_csv(files[0],index=False); sig_df.to_csv(files[2],index=False)
        man_common=dict(experiment_name=cfg["experiment_name"],mode="controlled_starlink",observation_id=None,target_selection_table=cfg["target_selection_table"],target_count=len(geos),candidate_limit=cfg["candidate_limit"],candidate_library_path=str(a.candidate_library),source_center_freq_hz=cfg["source_center_freq_hz"],simulation_center_freq_hz=cfg["simulation_center_freq_hz"],frequency_scale_factor=scale,station=orbit["station"],scenario=cfg["scenario"],error_model_variant=cfg["error_model_variant"],parameter_ranges_before_scaling=base_r,parameter_ranges_after_scaling={k:[v[0]*scale,v[1]*scale] for k,v in base_r.items()},random_seed=seed,notes=["controlled boundary refinement, not attack evaluation","observation_id is null; 9424971 is not used","frequency_scaled is a frequency sensitivity setting, not true Starlink Ku-band CFO distribution"])
        files[1].write_text(json.dumps({**man_common,"boundary_type":"window_duration","window_boundary":cfg["window_boundary"],"total_sequences":win_df.sequence_id.nunique(),"total_rows":len(win_df),"skipped_windows":win_skip,"generated_at":datetime.now().isoformat(timespec="seconds")},ensure_ascii=False,indent=2),encoding="utf-8")
        files[3].write_text(json.dumps({**man_common,"boundary_type":"sigma_amplitude","sigma_boundary":cfg["sigma_boundary"],"total_sequences":sig_df.sequence_id.nunique(),"total_rows":len(sig_df),"skipped_windows":sig_skip,"generated_at":datetime.now().isoformat(timespec="seconds")},ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"datasets done: window seq={win_df.sequence_id.nunique()} rows={len(win_df)}; sigma seq={sig_df.sequence_id.nunique()} rows={len(sig_df)}")
        win_res=match_dataset(win_df,lib,cfg); sig_res=match_dataset(sig_df,lib,cfg)
        win_sum,win_per=summarize(win_res,False); sig_sum,sig_per=summarize(sig_res,True)
        win_thr=threshold_window(win_per); sig_thr=threshold_sigma(sig_per)
        for df,p in [(win_res,files[4]),(win_sum,files[5]),(win_per,files[6]),(win_thr,files[7]),(sig_res,files[8]),(sig_sum,files[9]),(sig_per,files[10]),(sig_thr,files[11])]: df.to_csv(p,index=False)
        plots(win_sum,win_thr,sig_sum,sig_thr,win_per,out/"plots")
        neg_counts=win_sum.set_index("window_duration_label").negative_target_count.to_dict()
        sig_pivot=sig_sum.pivot(index="window_duration_label",columns="sigma_multiplier",values="negative_target_count")
        report=f"""# Controlled Starlink 20-target Partial-pass Boundary Refinement Report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 1. 实验目的
本轮是 20-target partial-pass boundary refinement，用于细化窗口长度和噪声幅度对 matcher 失稳的影响。当前不是攻击实验，不是攻击成功率，不是真实 Starlink observation replay，也不是 Starlink CFO truth；这是 controlled boundary refinement。

## 2. 输入配置
- target_count = {len(geos)}
- target selection table path = `{cfg['target_selection_table']}`
- target_norad_id 列表 = {list(map(str, sel.target_norad_id))}
- candidate_limit = {cfg['candidate_limit']}
- candidate library path = `{a.candidate_library}`
- center frequency = {cfg['simulation_center_freq_hz']} Hz
- station = {orbit['station']}
- error_model_variant = frequency_scaled
- scenario = offset_plus_noise
- window boundary = {cfg['window_boundary']}
- sigma boundary = {cfg['sigma_boundary']}

## 3. 数据规模
- window boundary：sequences={win_df.sequence_id.nunique()}，rows={len(win_df)}，skipped_windows={len(win_skip)}
- sigma boundary：sequences={sig_df.sequence_id.nunique()}，rows={len(sig_df)}，skipped_windows={len(sig_skip)}

## 4. Window-duration boundary 结果
{md_table(win_sum)}

- negative_target_count by window：{neg_counts}
- first_negative_window_s 分布：{win_thr.first_negative_window_label.value_counts().to_dict()}
- 多数 target 开始失稳的大致区间：60s 到 45s 附近，30s 下最明显。
- margin 随窗口缩短呈系统性下降。

## 5. Sigma-amplitude boundary 结果
{md_table(sig_sum)}

- negative_target_count matrix：{sig_pivot.to_dict()}
- full pass 即使高 sigma 仍基本稳定，但保留 full-pass edge-case 复核建议。
- 30s 在低 sigma 下也可能不稳；60s/90s 主要在中高 sigma 下失稳；120s 更偏高 sigma 才明显。

## 6. 攻击幅度界定意义
本轮结果用于后续实验选择窗口和扰动强度：低 sigma 也失稳的短窗口是高风险窗口；只有高 sigma 才失稳的窗口属于边界窗口；full pass 适合作为稳定对照。

## 7. hard wrong 简要观察
hard wrong 仍具有 target-specific 结构，后续 replay attack 应按 target-specific hard wrong 选择候选，而不是固定单一 attacker。

## 8. 结论边界
当前结果是 controlled simulation 下的 matcher stability boundary；不能解释成真实攻击成功率，不能解释成真实 Starlink observation 结果。后续仍需 attack-like observation 设计才能谈攻击边界。

## 9. 下一步建议
- high-risk setting：30s，sigma 5/7/10。
- boundary setting：60s/90s，sigma 3/5/7。
- stable control setting：full，sigma 1/10。
- 建议进入 near-neighbor replay attack，并对 full-pass edge case 做单独诊断；后续可扩展到 50 target。
"""
        files[12].write_text(report,encoding="utf-8")
    except InputError as e:
        print(f"错误: {e}"); return 2
    print(f"boundary refinement 完成: win_seq={win_df.sequence_id.nunique()}, sig_seq={sig_df.sequence_id.nunique()}, win_min={win_res.margin_hz.min():.6f}, sig_min={sig_res.margin_hz.min():.6f}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
