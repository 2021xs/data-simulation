#!/usr/bin/env python
"""Run controlled Starlink 20-target partial-pass validation."""

from __future__ import annotations

import argparse, json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from skyfield.api import EarthSatellite, load, wgs84

C_MPS = 299_792_458.0

class InputError(ValueError): pass
def fail(m: str): raise InputError(m)

def read_yaml(p: Path) -> dict[str, Any]:
    if not p.exists(): fail(f"配置文件不存在: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))

def parse_utc(s: str):
    if s.endswith("Z"): s=s[:-1]+"+00:00"
    d=datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def parse_tle(path: Path, ts):
    lines=[l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out=[]; i=0
    while i+2 < len(lines):
        n,l1,l2=lines[i].strip(),lines[i+1].strip(),lines[i+2].strip()
        if l1.startswith("1 ") and l2.startswith("2 ") and n.upper().startswith("STARLINK"):
            try:
                sat=EarthSatellite(l1,l2,n,ts)
                out.append(dict(name=n,norad=l1[2:7].strip(),epoch=sat.epoch.utc_iso(),
                                inclination=float(l2[8:16]),mean_motion=float(l2[52:63]),sat=sat))
            except Exception:
                pass
            i+=3
        else:
            i+=1
    if not out: fail("未解析到 Starlink TLE")
    return out

def find_pass(sat, station, ts, tw):
    step=float(tw.get("step_s",1)); start=parse_utc(tw["search_start_utc"])
    dur_h=float(tw.get("search_duration_h",24)); min_el=float(tw["min_elevation_deg"])
    max_s=float(tw["max_pass_duration_s"])
    times=[start+timedelta(seconds=i*step) for i in range(int(dur_h*3600//step)+1)]
    sf=ts.from_datetimes(times); elev=(sat-station).at(sf).altaz()[0].degrees
    idx=np.flatnonzero(elev>=min_el)
    if len(idx)==0: return None
    segs=[]; s=p=int(idx[0])
    for raw in idx[1:]:
        x=int(raw)
        if x==p+1: p=x
        else: segs.append((s,p)); s=p=x
    segs.append((s,p)); s,e=segs[0]
    max_pts=int(max_s//step)+1
    if e-s+1>max_pts: e=s+max_pts-1
    sel=times[s:e+1]; el=elev[s:e+1]
    return sel, dict(pass_start_utc=sel[0].isoformat().replace("+00:00","Z"), pass_end_utc=sel[-1].isoformat().replace("+00:00","Z"),
                     pass_duration_s=float((sel[-1]-sel[0]).total_seconds()), step_s=step, time_points_full=len(sel),
                     max_elevation_deg=float(np.max(el)), min_elevation_deg=float(np.min(el)))

def geo_curve(sat, station, ts, times, freq, step):
    sf=ts.from_datetimes(times); topo=(sat-station).at(sf)
    elev=topo.altaz()[0].degrees; rng=topo.distance().m; rr=np.gradient(rng, step)
    dop=-freq*rr/C_MPS; start=times[0]
    return pd.DataFrame(dict(t_abs_utc=[t.isoformat().replace("+00:00","Z") for t in times],
                             t_rel_s=[(t-start).total_seconds() for t in times],
                             elevation_deg=elev, range_m=rng, range_rate_mps=rr, doppler_hz=dop,
                             f_geo_tle_hz=freq+dop))

def select_candidates(entries, target, limit):
    for e in entries:
        e["score"]=abs(e["inclination"]-target["inclination"])+10*abs(e["mean_motion"]-target["mean_motion"])
    sel=sorted(entries, key=lambda e:(e["score"], e["name"]))[:limit]
    if target["norad"] not in {e["norad"] for e in sel}: sel=[target]+sel[:limit-1]
    sel=sorted(sel, key=lambda e:(0 if e["norad"]==target["norad"] else 1, e["score"], e["name"]))[:limit]
    for i,e in enumerate(sel,1): e["rank"]=i; e["is_true"]=e["norad"]==target["norad"]
    return sel

def ranges(sim, range_type):
    r={}
    for k in ["b_hz","k_hz_per_s","sigma_hz"]:
        v=sim["parameters"][k][f"{range_type}_range"]; r[k]=[float(v[0]),float(v[1])]
    return sim.get("model",{}).get("name","effective_cfo_simulation_v1"), r

def window_idx(t, label):
    if label=="full": return np.arange(len(t))
    dur=float(label.replace("center_","").replace("s",""))
    center=(float(t[0])+float(t[-1]))/2.0; start=center-dur/2; end=center+dur/2
    return np.flatnonzero((t>=start-1e-9)&(t<=end+1e-9))

def batch_scores(t, fsim, fgeo):
    x=t-float(np.mean(t)); n=float(len(t)); denom=float(np.sum(x*x))
    delta=fsim[None,:]-fgeo
    b=delta.mean(axis=1); k=np.zeros(len(fgeo)) if denom==0 else (delta@x)/denom
    res=delta-b[:,None]-k[:,None]*x[None,:]
    return np.sqrt(np.mean(res*res,axis=1))

def check_outputs(paths, overwrite):
    ex=[str(p) for p in paths if p.exists()]
    if ex and not overwrite: fail("输出文件已存在，若确认覆盖请添加 --overwrite: "+", ".join(ex))

def md_table(df: pd.DataFrame) -> str:
    cols=list(df.columns)
    lines=["| "+" | ".join(cols)+" |", "| "+" | ".join(["---"]*len(cols))+" |"]
    for _,row in df.iterrows():
        vals=[]
        for c in cols:
            v=row[c]
            vals.append(f"{v:.6f}" if isinstance(v, float) else str(v))
        lines.append("| "+" | ".join(vals)+" |")
    return "\n".join(lines)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--tle-file", required=True, type=Path)
    ap.add_argument("--orbit-config", required=True, type=Path)
    ap.add_argument("--sim-config", required=True, type=Path)
    ap.add_argument("--output-dir", default=Path("outputs"), type=Path)
    ap.add_argument("--overwrite", action="store_true")
    a=ap.parse_args()
    out=a.output_dir
    paths={
      "selection_csv": out/"metrics/controlled_starlink_20target_selection_table.csv",
      "selection_md": out/"reports/controlled_starlink_20target_selection_table.md",
      "dataset": out/"datasets/controlled_starlink_20target_partial_pass_dataset.csv",
      "manifest": out/"datasets/controlled_starlink_20target_partial_pass_manifest.json",
      "library": out/"datasets/controlled_starlink_20target_partial_pass_candidate_library.csv",
      "results": out/"metrics/controlled_starlink_20target_partial_pass_matching_results.csv",
      "summary": out/"metrics/controlled_starlink_20target_partial_pass_summary.csv",
      "per_target": out/"metrics/controlled_starlink_20target_partial_pass_per_target_summary.csv",
      "hard_wrong": out/"metrics/controlled_starlink_20target_partial_pass_hard_wrong_table.csv",
      "report": out/"reports/controlled_starlink_20target_partial_pass_validation_report.md",
    }
    plot_paths=[out/"plots/controlled_starlink_20target_partial_pass_margin_by_window.png",
                out/"plots/controlled_starlink_20target_partial_pass_accuracy_by_window.png",
                out/"plots/controlled_starlink_20target_partial_pass_per_target_min_margin_heatmap.png",
                out/"plots/controlled_starlink_20target_partial_pass_negative_margin_heatmap.png",
                out/"plots/controlled_starlink_20target_partial_pass_hard_wrong_distribution.png",
                out/"plots/controlled_starlink_20target_partial_pass_full_vs_30s_margin.png"]
    try:
        check_outputs(list(paths.values())+plot_paths, a.overwrite)
        orbit=read_yaml(a.orbit_config); sim=read_yaml(a.sim_config); cfg=orbit["multi_target_partial_pass_validation"]
        if orbit.get("mode")!="controlled_starlink" or cfg.get("observation_id") is not None: fail("必须保持 controlled_starlink 且 observation_id=null")
        ts=load.timescale(); entries=parse_tle(a.tle_file, ts)
        st=orbit["station"]; station=wgs84.latlon(float(st["lat_deg"]),float(st["lon_deg"]),elevation_m=float(st["alt_m"]))
        freq=float(cfg["simulation_center_freq_hz"]); scale=freq/float(cfg["source_center_freq_hz"])
        version, base_r=ranges(sim, orbit["simulation"]["range_type"]); scaled_r={k:[v[0]*scale,v[1]*scale] for k,v in base_r.items()}
        rng=np.random.default_rng(int(cfg["random_seed"]))
        target_ref=next((e for e in entries if e["norad"]=="44714"), None)
        if not target_ref: fail("STARLINK-1008 / 44714 不在 TLE 中")
        for e in entries:
            e["sel_score"]=abs(e["inclination"]-target_ref["inclination"])+10*abs(e["mean_motion"]-target_ref["mean_motion"])
        candidates_targets=[target_ref]+[e for e in sorted(entries,key=lambda x:(x["sel_score"],x["name"])) if e["norad"]!="44714"]
        selected=[]; skipped=[]; selection_rows=[]; geos={}
        for e in candidates_targets:
            if len(selected)>=int(cfg["target_count"]): break
            res=find_pass(e["sat"], station, ts, orbit["time_window"])
            if res is None:
                skipped.append(dict(target_name=e["name"], target_norad_id=e["norad"], reason="no_visible_pass")); continue
            times,pinfo=res
            if pinfo["pass_duration_s"] < 180:
                skipped.append(dict(target_name=e["name"], target_norad_id=e["norad"], reason="pass_shorter_than_180s")); continue
            geo=geo_curve(e["sat"], station, ts, times, freq, pinfo["step_s"])
            cand_count=len(select_candidates(entries, e, int(cfg["candidate_limit"])))
            if cand_count<int(cfg["candidate_limit"]):
                skipped.append(dict(target_name=e["name"], target_norad_id=e["norad"], reason="candidate_count_insufficient")); continue
            idx=len(selected)+1; selected.append(e); geos[e["norad"]]=geo
            selection_rows.append(dict(target_index=idx,target_name=e["name"],target_norad_id=e["norad"],tle_epoch=e["epoch"],
                **pinfo,doppler_min_hz=float(geo.doppler_hz.min()),doppler_max_hz=float(geo.doppler_hz.max()),
                doppler_span_hz=float(geo.doppler_hz.max()-geo.doppler_hz.min()),candidate_limit=int(cfg["candidate_limit"]),
                candidate_count_actual=cand_count,contains_true_target=True,
                selected_reason="已深挖 reference case" if e["norad"]=="44714" else "有效 pass 时长充足；Doppler span 合理；candidate library 可生成；用于扩展 target 多样性",
                notes="controlled_starlink; observation_id=null"))
        sel_df=pd.DataFrame(selection_rows)
        for p in [paths["selection_csv"].parent, paths["selection_md"].parent]: p.mkdir(parents=True, exist_ok=True)
        sel_df.to_csv(paths["selection_csv"], index=False)
        paths["selection_md"].write_text("# 20 target selection table\n\n"+md_table(sel_df), encoding="utf-8")
        print(f"selection done: {len(selected)} targets")

        rows=[]; libs=[]; seq_counter=1; skipped_windows=[]
        for trow,e in zip(selection_rows, selected):
            target_index=trow["target_index"]; geo=geos[e["norad"]]; full_t=geo.t_rel_s.to_numpy(float)
            # candidate library per target full pass
            cand=select_candidates(entries,e,int(cfg["candidate_limit"]))
            times=ts.from_datetimes([parse_utc(x) for x in geo.t_abs_utc]); step=float(np.median(np.diff(full_t)))
            for c in cand:
                topo=(c["sat"]-station).at(times); rngm=topo.distance().m; rr=np.gradient(rngm, step); dop=-freq*rr/C_MPS
                libs.append(pd.DataFrame(dict(target_index=target_index,target_name=e["name"],target_norad_id=e["norad"],
                    candidate_name=c["name"],candidate_norad_id=c["norad"],candidate_rank_or_selection_order=c["rank"],
                    t_abs_utc=geo.t_abs_utc,t_rel_s=geo.t_rel_s,center_freq_hz=freq,f_geo_candidate_hz=freq+dop,
                    is_true_target=c["is_true"],candidate_selection_reason="similar_inclination_mean_motion")))
            for wlab in cfg["window_durations"]:
                idx=window_idx(full_t,wlab)
                if len(idx)<10:
                    skipped_windows.append(dict(target_name=e["name"],target_norad_id=e["norad"],window_duration_label=wlab,reason="too_few_points")); continue
                win=geo.iloc[idx].copy().reset_index(drop=True)
                start=float(win.t_rel_s.iloc[0]); end=float(win.t_rel_s.iloc[-1]); win["t_window_rel_s"]=win.t_rel_s-start
                t=win.t_rel_s.to_numpy(float); fgeo=win.f_geo_tle_hz.to_numpy(float); t0=float(np.mean(t))
                for si in range(1,int(cfg["num_sims_per_target_per_window"])+1):
                    base_b=float(rng.uniform(*base_r["b_hz"])); base_sigma=float(rng.uniform(*base_r["sigma_hz"]))
                    b=base_b*scale; sigma_base=base_sigma*scale; sigma=sigma_base*float(cfg["sigma_multiplier"])
                    noise=rng.normal(0,sigma,len(win)); seq_id=f"mtpp_{seq_counter:06d}"; seq_counter+=1
                    seq=win.copy()
                    seq.insert(0,"experiment_name",cfg["experiment_name"]); seq.insert(1,"sequence_id",seq_id)
                    seq.insert(2,"target_index",target_index); seq.insert(3,"target_name",e["name"]); seq.insert(4,"target_norad_id",e["norad"])
                    seq.insert(5,"error_model_variant",cfg["error_model_variant"]); seq.insert(6,"sigma_multiplier",float(cfg["sigma_multiplier"]))
                    seq.insert(7,"scenario",cfg["scenario"]); seq.insert(8,"sim_index",si); seq.insert(9,"window_duration_label",wlab)
                    seq.insert(10,"window_duration_s", float(end-start)); seq.insert(11,"window_start_rel_s",start); seq.insert(12,"window_end_rel_s",end)
                    seq["station_name"]=st["name"]; seq["station_lat_deg"]=float(st["lat_deg"]); seq["station_lon_deg"]=float(st["lon_deg"]); seq["station_alt_m"]=float(st["alt_m"])
                    seq["center_freq_hz"]=freq; seq["b_hz"]=b; seq["k_hz_per_s"]=0.0; seq["sigma_hz"]=sigma; seq["sigma_base_hz"]=sigma_base
                    seq["base_b_hz"]=base_b; seq["base_sigma_hz"]=base_sigma; seq["noise_hz"]=noise; seq["f_sim_hz"]=fgeo+b+noise
                    seq["mode"]="controlled_starlink"; seq["observation_id"]=pd.NA; seq["label"]=e["norad"]; seq["random_seed"]=int(cfg["random_seed"]); seq["config_version"]=version
                    seq["n_time_points"]=len(seq)
                    rows.append(seq)
        df=pd.concat(rows, ignore_index=True); lib=pd.concat(libs, ignore_index=True)
        for p in [paths["dataset"].parent, paths["library"].parent, paths["manifest"].parent]: p.mkdir(parents=True, exist_ok=True)
        df.to_csv(paths["dataset"], index=False); lib.to_csv(paths["library"], index=False)
        manifest=dict(generated_at=datetime.now().isoformat(timespec="seconds"), experiment_name=cfg["experiment_name"], mode="controlled_starlink",
            observation_id=None,target_count=len(selected),target_selection_table_path=str(paths["selection_csv"]),source_center_freq_hz=cfg["source_center_freq_hz"],
            simulation_center_freq_hz=freq,frequency_scale_factor=scale,station=st,tle_source_path=str(a.tle_file),error_model_variant=cfg["error_model_variant"],
            sigma_multiplier=cfg["sigma_multiplier"],scenario=cfg["scenario"],candidate_limit=cfg["candidate_limit"],window_durations=cfg["window_durations"],
            num_sims_per_target_per_window=cfg["num_sims_per_target_per_window"],total_rows=len(df),total_sequences=df.sequence_id.nunique(),
            skipped_targets=skipped,skipped_windows=skipped_windows,parameter_ranges_before_scaling=base_r,parameter_ranges_after_scaling=scaled_r,
            random_seed=cfg["random_seed"],notes=["controlled multi-target partial-pass validation, not attack evaluation","observation_id is null; 9424971 is not used","frequency_scaled is a frequency sensitivity setting, not true Starlink Ku-band CFO distribution"])
        paths["manifest"].write_text(json.dumps(manifest,ensure_ascii=False,indent=2), encoding="utf-8")
        print(f"dataset/lib done: seq={df.sequence_id.nunique()}, rows={len(df)}, lib_rows={len(lib)}")

        # matcher batch by target/window
        res_rows=[]
        for (target_index,wlab), g in df.groupby(["target_index","window_duration_label"], sort=True):
            g=g.sort_values(["sequence_id","t_rel_s"]); ids=list(g.sequence_id.drop_duplicates())
            t=g[g.sequence_id==ids[0]].t_rel_s.to_numpy(float)
            fsim=g.pivot(index="sequence_id",columns="t_rel_s",values="f_sim_hz").loc[ids,t].to_numpy(float)
            lsub=lib[lib.target_index==target_index].merge(pd.DataFrame({"t_rel_s":t}), on="t_rel_s")
            meta=lsub.drop_duplicates("candidate_norad_id").sort_values("candidate_rank_or_selection_order").reset_index(drop=True)
            mat=lsub.pivot(index="candidate_norad_id",columns="t_rel_s",values="f_geo_candidate_hz").loc[meta.candidate_norad_id,t].to_numpy(float)
            norads=meta.candidate_norad_id.astype(str).to_numpy(); true=str(g.target_norad_id.iloc[0]); true_idx=int(np.flatnonzero(norads==true)[0])
            firsts=g.drop_duplicates("sequence_id").set_index("sequence_id").loc[ids]
            for rowi,sid in enumerate(ids):
                rmse=batch_scores(t,fsim[rowi],mat); pred=int(np.argmin(rmse)); wr=rmse.copy(); wr[true_idx]=np.inf; bestw=int(np.argmin(wr)); first=firsts.loc[sid]
                res_rows.append(dict(experiment_name=cfg["experiment_name"],sequence_id=sid,target_index=target_index,target_name=first.target_name,target_norad_id=true,
                    predicted_name=meta.iloc[pred].candidate_name,predicted_norad_id=str(meta.iloc[pred].candidate_norad_id),
                    best_wrong_name=meta.iloc[bestw].candidate_name,best_wrong_norad_id=str(meta.iloc[bestw].candidate_norad_id),
                    true_score_rmse_hz=float(rmse[true_idx]),best_score_rmse_hz=float(rmse[pred]),best_wrong_score_rmse_hz=float(rmse[bestw]),
                    margin_hz=float(rmse[bestw]-rmse[true_idx]),is_correct=str(meta.iloc[pred].candidate_norad_id)==true,
                    window_duration_label=wlab,window_duration_s=float(first.window_duration_s),n_time_points=int(first.n_time_points),
                    scenario=cfg["scenario"],error_model_variant=cfg["error_model_variant"],sigma_multiplier=float(cfg["sigma_multiplier"]),candidate_limit=int(cfg["candidate_limit"])))
        res=pd.DataFrame(res_rows)
        summary=res.groupby("window_duration_label").agg(sequence_count=("sequence_id","count"),target_count=("target_index","nunique"),accuracy=("is_correct","mean"),wrong_count=("is_correct",lambda s:int((~s).sum())),negative_margin_count=("margin_hz",lambda s:int((s<0).sum())),mean_margin_hz=("margin_hz","mean"),median_margin_hz=("margin_hz","median"),min_margin_hz=("margin_hz","min"),p05_margin_hz=("margin_hz",lambda s:float(np.quantile(s,.05))),mean_true_score_rmse_hz=("true_score_rmse_hz","mean"),mean_best_wrong_score_rmse_hz=("best_wrong_score_rmse_hz","mean")).reset_index()
        per=res.groupby(["target_index","target_name","target_norad_id","window_duration_label"]).agg(
            sequence_count=("sequence_id","count"),
            accuracy=("is_correct","mean"),
            wrong_count=("is_correct",lambda s:int((~s).sum())),
            negative_margin_count=("margin_hz",lambda s:int((s<0).sum())),
            mean_margin_hz=("margin_hz","mean"),
            median_margin_hz=("margin_hz","median"),
            min_margin_hz=("margin_hz","min"),
            p05_margin_hz=("margin_hz",lambda s:float(np.quantile(s,.05))),
            most_common_best_wrong=("best_wrong_norad_id",lambda s:str(s.value_counts().index[0])),
            best_wrong_top_5=("best_wrong_norad_id",lambda s:";".join([f"{k}:{v}" for k,v in s.astype(str).value_counts().head(5).items()]))
        ).reset_index()
        hard=[]
        name_map=res.drop_duplicates("best_wrong_norad_id").set_index("best_wrong_norad_id")["best_wrong_name"].to_dict()
        for _,grp in per.groupby(["target_index","target_name","target_norad_id","window_duration_label"]):
            # use res subset for hardest row
            rsub=res[(res.target_index==grp.target_index.iloc[0])&(res.window_duration_label==grp.window_duration_label.iloc[0])]
            hr=rsub.sort_values("margin_hz").iloc[0]; vc=rsub.best_wrong_norad_id.astype(str).value_counts(); common=str(vc.index[0])
            hard.append(dict(target_index=hr.target_index,target_name=hr.target_name,target_norad_id=hr.target_norad_id,window_duration_label=hr.window_duration_label,
                hardest_wrong_name=hr.best_wrong_name,hardest_wrong_norad_id=hr.best_wrong_norad_id,min_margin_hz=hr.margin_hz,
                most_common_best_wrong_name=name_map.get(common,""),most_common_best_wrong_norad_id=common,most_common_best_wrong_count=int(vc.iloc[0]),
                negative_margin_count=int((rsub.margin_hz<0).sum()),notes="controlled validation"))
        hard_df=pd.DataFrame(hard)
        for p in [paths["results"].parent, paths["summary"].parent]: p.mkdir(parents=True, exist_ok=True)
        res.to_csv(paths["results"], index=False); summary.to_csv(paths["summary"], index=False); per.to_csv(paths["per_target"], index=False); hard_df.to_csv(paths["hard_wrong"], index=False)

        # plots
        (out/"plots").mkdir(parents=True, exist_ok=True)
        order=["full","center_180s","center_120s","center_60s","center_30s"]
        fig,ax=plt.subplots(figsize=(9,5)); data=[res[res.window_duration_label==w].margin_hz for w in order if w in set(res.window_duration_label)]; ax.boxplot(data, labels=[w for w in order if w in set(res.window_duration_label)], showfliers=False); ax.set_ylabel("margin_hz"); ax.set_title("20target margin by window"); ax.grid(True,axis="y",alpha=.25); fig.tight_layout(); fig.savefig(plot_paths[0],dpi=160); plt.close(fig)
        fig,ax=plt.subplots(figsize=(8,4.5)); sm=summary.set_index("window_duration_label").reindex(order).dropna(); ax.bar(sm.index,sm.accuracy); ax.set_ylim(0,1.05); ax.set_ylabel("accuracy"); ax.set_title("20target accuracy by window"); ax.tick_params(axis="x",rotation=25); fig.tight_layout(); fig.savefig(plot_paths[1],dpi=160); plt.close(fig)
        piv=per.pivot(index="target_name",columns="window_duration_label",values="min_margin_hz").reindex(columns=order)
        fig,ax=plt.subplots(figsize=(8,8)); im=ax.imshow(piv.to_numpy(float),aspect="auto",cmap="viridis"); ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns,rotation=30); ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index,fontsize=7); fig.colorbar(im,ax=ax,label="min margin"); ax.set_title("per-target min margin"); fig.tight_layout(); fig.savefig(plot_paths[2],dpi=160); plt.close(fig)
        piv=per.pivot(index="target_name",columns="window_duration_label",values="negative_margin_count").reindex(columns=order)
        fig,ax=plt.subplots(figsize=(8,8)); im=ax.imshow(piv.to_numpy(float),aspect="auto",cmap="magma"); ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns,rotation=30); ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index,fontsize=7); fig.colorbar(im,ax=ax,label="negative count"); ax.set_title("negative margin count"); fig.tight_layout(); fig.savefig(plot_paths[3],dpi=160); plt.close(fig)
        vc=res.best_wrong_norad_id.astype(str).value_counts().head(15); fig,ax=plt.subplots(figsize=(9,4.8)); ax.bar(vc.index,vc.values); ax.tick_params(axis="x",rotation=35); ax.set_title("hard wrong distribution"); ax.set_ylabel("count"); fig.tight_layout(); fig.savefig(plot_paths[4],dpi=160); plt.close(fig)
        f=per[per.window_duration_label=="full"][["target_name","min_margin_hz"]].rename(columns={"min_margin_hz":"full"}); c=per[per.window_duration_label=="center_30s"][["target_name","min_margin_hz"]].rename(columns={"min_margin_hz":"center_30s"}); sc=f.merge(c,on="target_name"); fig,ax=plt.subplots(figsize=(6,5)); ax.scatter(sc.full,sc.center_30s); ax.axhline(0,color="red",ls="--"); ax.set_xlabel("full min margin"); ax.set_ylabel("30s min margin"); ax.set_title("full vs 30s min margin"); ax.grid(True,alpha=.25); fig.tight_layout(); fig.savefig(plot_paths[5],dpi=160); plt.close(fig)

        full=summary[summary.window_duration_label=="full"].iloc[0]; s60=per[per.window_duration_label=="center_60s"].groupby("target_norad_id").negative_margin_count.max(); s30=per[per.window_duration_label=="center_30s"].groupby("target_norad_id").negative_margin_count.max()
        fragile=per.sort_values("min_margin_hz").iloc[0]
        report=f"""# Controlled Starlink 20-target Partial-pass Validation Report

生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

## 实验目的
本轮是 20-target multi-target partial-pass validation，用于验证 44714 的 partial-pass failure 是否不是孤例。当前不是攻击实验，不是攻击成功率，不是真实 Starlink observation replay，也不是 Starlink CFO truth。

## 20 target 样本表
- CSV：`{paths['selection_csv']}`
- Markdown：`{paths['selection_md']}`
- 有效 target 数：{len(selected)}
- skipped target 数：{len(skipped)}
- pass duration 范围：{sel_df.pass_duration_s.min():.1f} - {sel_df.pass_duration_s.max():.1f} s
- Doppler span 范围：{sel_df.doppler_span_hz.min():.3f} - {sel_df.doppler_span_hz.max():.3f} Hz

## 输入配置
- target_count = {len(selected)}
- candidate_limit = {cfg['candidate_limit']}
- center frequency = {freq:.0f} Hz
- station = {st['name']} / lat={st['lat_deg']} / lon={st['lon_deg']} / alt_m={st['alt_m']}
- error_model_variant = frequency_scaled
- sigma_multiplier = 10
- scenario = offset_plus_noise
- window_durations = {cfg['window_durations']}
- num_sims_per_target_per_window = {cfg['num_sims_per_target_per_window']}
- mode = controlled_starlink
- observation_id = null

## 数据集规模
- total_sequences：{df.sequence_id.nunique()}
- total_rows：{len(df)}
- candidate library rows：{len(lib)}
- skipped windows：{len(skipped_windows)}

## 总体结果
{md_table(summary)}

说明：overall / window accuracy 是 stress grid 平均值，不是真实场景准确率。

## full pass 是否稳定
- full accuracy：{full.accuracy:.6f}
- full negative_margin_count：{int(full.negative_margin_count)}
- full min_margin_hz：{full.min_margin_hz:.6f}

## 短窗口影响
- 60s 出现 negative margin 的 target 数：{int((s60>0).sum())}
- 30s 出现 negative margin 的 target 数：{int((s30>0).sum())}
- 30s min_margin_hz：{summary[summary.window_duration_label=='center_30s'].min_margin_hz.iloc[0]:.6f}
- 60s min_margin_hz：{summary[summary.window_duration_label=='center_60s'].min_margin_hz.iloc[0]:.6f}
- 44714 是多个 failure case 之一，不是唯一目标。

## per-target 差异与 hard wrong
- 最脆弱 target：{fragile.target_name} / {fragile.target_norad_id}，window={fragile.window_duration_label}，min_margin={fragile.min_margin_hz:.6f}
- hard wrong 分布 top 10：{res.best_wrong_norad_id.astype(str).value_counts().head(10).to_dict()}
- 每个 target 的 hard wrong 见 `{paths['hard_wrong']}`。

## 结论边界
当前证明的是 controlled partial-pass validation。如果多个 target 短窗口失稳，只能说 controlled setting 下存在系统性 partial-pass confusion risk；不能解释为真实攻击成功率，不能解释为真实 Starlink observation 结果。

## 下一步建议
如果多数 target 在 30s/60s 失稳，进入 multi-target near-neighbor replay attack 设计；也可先挑最脆弱 target 做 case study。若需要统计版，可扩展到 50 target。
"""
        paths["report"].parent.mkdir(parents=True,exist_ok=True); paths["report"].write_text(report,encoding="utf-8")
    except InputError as e:
        print(f"错误: {e}"); return 2
    print(f"Stage 3B 完成: targets={len(selected)}, seq={df.sequence_id.nunique()}, rows={len(df)}, acc={res.is_correct.mean():.6f}, min_margin={res.margin_hz.min():.6f}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
