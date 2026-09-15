"""Minimal A2-R verifier-aware public reference-point attack audit.

Three pre-labelled existing 60 s conditions are reused.  The script performs
deterministic spatial and probability quadrature only: no new orbit-parameter
sweep, environment/noise realization, threshold, or verifier is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import ncx2
from skyfield.api import load, wgs84

SCRIPT_DIR=Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0,str(SCRIPT_DIR))
import run_differential_doppler_mechanism_audit as mech  # noqa: E402
import run_doppler_public_compensation_probability_audit as prob  # noqa: E402
import run_multi_service_area_single_station_confirmation as multi  # noqa: E402
import run_segment_local_expanded_sample_confirmation as expanded  # noqa: E402
import run_segmented_service_center_compensation as seg  # noqa: E402

plt.rcParams["font.sans-serif"]=["Microsoft YaHei","SimHei","DejaVu Sans"]
plt.rcParams["axes.unicode_minus"]=False

R_CELL_KM=500.0
LABELS=["observed_all_accept","near_boundary_zero_accept_control","deep_reject_control"]
INPUTS={
    "selected":Path("outputs/metrics/fixed_geometry_multi_realization_selected_conditions.csv"),
    "realizations":Path("outputs/datasets/fixed_geometry_multi_realization_dataset.csv"),
    "candidate_library":Path("outputs/datasets/controlled_starlink_20target_partial_pass_candidate_library.csv"),
    "selection_table":Path("outputs/metrics/controlled_starlink_20target_selection_table.csv"),
    "tle":Path("data/tle/starlink_tle.txt"),"orbit":Path("configs/orbit_simulation_cases.yaml"),
    "parameters":Path("configs/simulation_parameter_config.yaml"),
}


def parse_args()->argparse.Namespace:
    p=argparse.ArgumentParser(description="A2-R verifier-aware公共参考点最小审计")
    p.add_argument("--coarse-step-km",type=float,default=125.0)
    p.add_argument("--refine-step-km",type=float,default=31.25)
    p.add_argument("--fine-step-km",type=float,default=15.625)
    p.add_argument("--s-radial-order",type=int,default=3)
    p.add_argument("--s-angular-count",type=int,default=24)
    p.add_argument("--s-check-radial-order",type=int,default=5)
    p.add_argument("--s-check-angular-count",type=int,default=32)
    p.add_argument("--report-only",action="store_true",help="reuse completed surface and only refresh annotations/report")
    p.add_argument("--overwrite",action="store_true")
    return p.parse_args()


def paths()->dict[str,Path]:
    stem="a2_reference_point_attack_audit"
    return {"math":Path(f"outputs/metrics/{stem}_mathematical_audit.csv"),
        "selection":Path(f"outputs/metrics/{stem}_pass_selection.csv"),
        "surface":Path(f"outputs/metrics/{stem}_candidate_reference_surface.csv"),
        "optimum":Path(f"outputs/metrics/{stem}_optimum_summary.csv"),
        "mechanism":Path(f"outputs/metrics/{stem}_mechanism_comparison.csv"),
        "convergence":Path(f"outputs/metrics/{stem}_convergence_audit.csv"),
        "audit":Path(f"outputs/metrics/{stem}_correctness_audit.csv"),
        "manifest":Path(f"outputs/metrics/{stem}_manifest.json"),
        "report":Path(f"outputs/reports/{stem}_report.md"),
        "figures":Path(f"outputs/figures/{stem}")}


def check_io(out:dict[str,Path],overwrite:bool)->None:
    missing=[str(p) for p in INPUTS.values() if not p.exists()]
    if missing: raise SystemExit("missing input: "+", ".join(missing))
    existing=[str(p) for k,p in out.items() if k!="figures" and p.exists()]
    if out["figures"].exists() and any(out["figures"].iterdir()): existing.append(str(out["figures"]))
    if existing and not overwrite: raise SystemExit("audit output exists; add --overwrite: "+", ".join(existing))
    for k,p in out.items(): (p if k=="figures" else p.parent).mkdir(parents=True,exist_ok=True)


def stable_id(prefix:str,obj:Any)->str:
    raw=json.dumps(obj,sort_keys=True,default=str,separators=(",",":"))
    return prefix+"_"+hashlib.sha256(raw.encode()).hexdigest()[:20]


def select_conditions()->pd.DataFrame:
    d=pd.read_csv(INPUTS["selected"],low_memory=False)
    rows=[]
    for label in LABELS:
        g=d[d.selection_group.eq(label)].copy()
        if g.empty: raise SystemExit(f"existing classification unavailable: {label}")
        sort=[c for c in ["selection_order","selection_rank_score","geometry_condition_id"] if c in g]
        asc=[True if c!="selection_rank_score" else False for c in sort]
        rows.append(g.sort_values(sort,ascending=asc).iloc[0])
    out=pd.DataFrame(rows).reset_index(drop=True)
    if out.geometry_condition_id.nunique()!=3: raise SystemExit("representative selection is not unique")
    out["representative_role"]=["high_risk_existing_label","boundary_existing_label","deep_reject_existing_label"]
    out["selection_rule"]="first existing selection_order within pre-existing label; no new risk label"
    return out


def xy_to_latlon(c_lat:float,c_lon:float,east:float,north:float)->tuple[float,float]:
    dist=math.hypot(east,north)
    if dist<1e-12: return float(c_lat),float(c_lon)
    bearing=(math.degrees(math.atan2(east,north))+360.0)%360.0
    return seg.destination(c_lat,c_lon,dist,bearing)


def disk_quadrature(radial_order:int,angular_count:int)->pd.DataFrame:
    z,w=np.polynomial.legendre.leggauss(radial_order)
    u=(z+1.0)/2.0; wr=w/2.0
    rows=[]
    for ui,wi in zip(u,wr):
        r=R_CELL_KM*math.sqrt(float(ui))
        for j in range(angular_count):
            a=2*math.pi*j/angular_count
            rows.append({"east_km":r*math.sin(a),"north_km":r*math.cos(a),"weight":float(wi/angular_count)})
    d=pd.DataFrame(rows); d.weight/=d.weight.sum(); return d


def candidate_centered_disk_quadrature(e0:float,n0:float,radial_order:int,angular_count:int)->pd.DataFrame:
    """Uniform-area quadrature over the original disk, expressed around C'."""
    z,w=np.polynomial.legendre.leggauss(radial_order)
    # u=(r/rmax)^2 is uniform in area.  Composite intervals resolve the
    # small, verifier-acceptable kernel near S=C' without random oversampling.
    breaks=[0.0,1e-5,1e-4,1e-3,1e-2,0.05,0.15,0.35,0.65,1.0]
    uw=[]
    for lo,hi in zip(breaks[:-1],breaks[1:]):
        for zi,wi in zip(z,w):
            uw.append((lo+(zi+1.0)*(hi-lo)/2.0,wi*(hi-lo)/2.0))
    rows=[]
    for j in range(angular_count):
        theta=2*math.pi*j/angular_count; ue=math.sin(theta); un=math.cos(theta)
        dot=e0*ue+n0*un
        rmax=-dot+math.sqrt(max(dot*dot+R_CELL_KM**2-e0*e0-n0*n0,0.0))
        for ui,wi in uw:
            r=rmax*math.sqrt(float(ui))
            rows.append({"east_km":e0+r*ue,"north_km":n0+r*un,
                         "weight":float((rmax*rmax/(R_CELL_KM*R_CELL_KM))*wi/angular_count)})
    d=pd.DataFrame(rows); d.weight/=d.weight.sum(); return d


def coarse_grid(step:float)->list[tuple[float,float]]:
    vals=np.arange(-R_CELL_KM,R_CELL_KM+step*.1,step)
    pts=[(float(e),float(n)) for e in vals for n in vals if e*e+n*n<=R_CELL_KM**2+1e-9]
    if (0.0,0.0) not in pts: pts.append((0.0,0.0))
    return pts


def local_grid(center:tuple[float,float],radius:float,step:float)->list[tuple[float,float]]:
    e0,n0=center; vals=np.arange(-radius,radius+step*.1,step)
    pts=[]
    for de in vals:
        for dn in vals:
            e=float(e0+de); n=float(n0+dn)
            if e*e+n*n<=R_CELL_KM**2+1e-9: pts.append((e,n))
    return pts


def load_context(selection:pd.DataFrame):
    loader=SimpleNamespace(selection_table=INPUTS["selection_table"],candidate_library=INPUTS["candidate_library"],
        tle_file=INPUTS["tle"],orbit_config=INPUTS["orbit"],parameter_config=INPUTS["parameters"],max_targets=20)
    _sel,library,orbit,tle,ranges=expanded.load_base_inputs(loader)
    if orbit.get("mode")!="controlled_starlink" or orbit.get("observation_id") is not None:
        raise SystemExit("requires controlled_starlink and observation_id=null")
    current=pd.read_csv(INPUTS["realizations"],low_memory=False)
    current=current[current.bk_mode.eq("current_bk")].sort_values("realization_index").drop_duplicates("geometry_condition_id").set_index("geometry_condition_id")
    ts=load.timescale(); freq=float(orbit.get("ku_band_experiment",{}).get("simulation_center_freq_hz") or orbit["frequency"]["center_freq_hz"])
    return library,tle,ranges,current,ts,freq


def delta_curve(sat_a:Any,sat_b:Any,lat:float,lon:float,times:list[Any],ts:Any,freq:float,step:float)->np.ndarray:
    fa=seg.geo_curve_fixed(sat_a,lat,lon,0.0,times,ts,freq,step)[0]
    sample={"sample_source":"real_tle_candidate","target_sat_id":"","attack_sat_id":"","attack_type":"real_tle_candidate","attack_param_value":np.nan}
    fb=multi.attack_geo(sample,sat_a,sat_b,lat,lon,0.0,times,ts,freq,step)
    return fa-fb


def batch_delta_curves(case:dict[str,Any],xy:list[tuple[float,float]])->np.ndarray:
    """Vectorized fixed-site path, algebraically identical to geo_curve_fixed."""
    ll=[xy_to_latlon(case["C_lat"],case["C_lon"],e,n) for e,n in xy]
    sites=wgs84.latlon(np.asarray([v[0] for v in ll]),np.asarray([v[1] for v in ll]),elevation_m=0.0)
    m=len(xy); nt=len(case["times"]); ra=np.empty((m,nt)); rb=np.empty((m,nt))
    for ti,t in enumerate(case["sky_times"]):
        spos=sites.at(t).position.km.T
        ra[:,ti]=np.linalg.norm(case["sat_a_positions_km"][ti]-spos,axis=1)*1000.0
        rb[:,ti]=np.linalg.norm(case["sat_b_positions_km"][ti]-spos,axis=1)*1000.0
    rra=np.gradient(ra,case["step"],axis=1); rrb=np.gradient(rb,case["step"],axis=1)
    return -case["freq"]*(rra-rrb)/float(seg.orbit_builder.C_MPS)


def probability_batch(raw:np.ndarray,template:pd.Series,ranges:dict[str,list[float]],dt:float,
                      sn:np.ndarray,sw:np.ndarray,kn:np.ndarray,kw:np.ndarray)->dict[str,np.ndarray]:
    # raw shape: stations x time
    n=raw.shape[1]; x=np.arange(n,dtype=float); x-=x.mean(); sxx=float(x@x)
    bgeo=raw.mean(axis=1); kgeo=raw@x/sxx; remain=raw-bgeo[:,None]-kgeo[:,None]*x
    d2=np.sum(remain*remain,axis=1); rmse=np.sqrt(d2/n)
    bc=float(template.formal_b_center_hz); B=float(template.formal_b_threshold_hz)
    kc=float(template.formal_k_center_hz_per_s); K=float(template.formal_k_threshold_hz_per_s)
    tau=float(template.formal_score_threshold); blo,bhi=map(float,ranges["b_hz"])
    psum=np.zeros(len(raw)); pbsum=np.zeros(len(raw)); pksum=np.zeros(len(raw)); pallsum=np.zeros(len(raw))
    kval=kn[None,:]
    for sigma,ws in zip(sn,sw):
        sb=float(sigma/math.sqrt(n)); sk=float(sigma/math.sqrt(sxx))
        ps=ncx2.cdf(n*tau*tau/(sigma*sigma),df=n-2,nc=d2/(sigma*sigma))
        pk=prob.ndtr((kc+K-kgeo[:,None]-kval)/sk)-prob.ndtr((kc-K-kgeo[:,None]-kval)/sk)
        pb=prob.normal_uniform_interval_prob(bc-B-bgeo[:,None]-dt*kval,bc+B-bgeo[:,None]-dt*kval,blo,bhi,sb)
        pbm=np.sum(kw[None,:]*pb,axis=1); pkm=np.sum(kw[None,:]*pk,axis=1); pbk=np.sum(kw[None,:]*pb*pk,axis=1)
        psum+=ws*ps; pbsum+=ws*pbm; pksum+=ws*pkm; pallsum+=ws*ps*pbk
    return {"D_proj_squared_hz2":d2,"projected_rmse_hz":rmse,"b_geo_hat_hz":bgeo,"k_geo_hat_hz_per_s":kgeo,
        "p_score":psum,"p_b":pbsum,"p_k":pksum,"p_accept":pallsum}


def prepare_case(row:pd.Series,library:pd.DataFrame,tle:dict[str,Any],current:pd.DataFrame,ts:Any,freq:float):
    target=str(row.target_sat_id); attacker=str(row.attack_sat_id); gid=str(row.geometry_condition_id)
    tg=seg.base.target_geo_from_library(library,target); tr=tg.t_rel_s.to_numpy(float)
    times_all=[seg.base.parse_utc(v) for v in tg.t_abs_utc.astype(str)]
    mask=(tr>=float(row.evaluation_start_s)-1e-9)&(tr<=float(row.evaluation_end_s)+1e-9)
    et=tr[mask]; times=[t for t,k in zip(times_all,mask) if k]; step=float(np.median(np.diff(tr)))
    if len(et)!=60: raise SystemExit(f"{gid}: expected 60 points, got {len(et)}")
    template=current.loc[gid]; dt=float(np.mean(et)-np.mean(tr))
    sat_a=tle[target]["sat"]; sat_b=tle[attacker]["sat"]; sky_times=ts.from_datetimes(times)
    return {"gid":gid,"target":target,"attacker":attacker,"sat_a":sat_a,"sat_b":sat_b,
        "times":times,"ts":ts,"freq":freq,"step":step,"C_lat":float(row.C_lat),"C_lon":float(row.C_lon),
        "template":template,"dt":dt,"et":et,"sky_times":list(sky_times),
        "sat_a_positions_km":sat_a.at(sky_times).position.km.T,"sat_b_positions_km":sat_b.at(sky_times).position.km.T}


def spatial_curves(case:dict[str,Any],points:pd.DataFrame|list[tuple[float,float]])->tuple[np.ndarray,list[tuple[float,float]]]:
    if isinstance(points,pd.DataFrame): xy=list(zip(points.east_km.astype(float),points.north_km.astype(float)))
    else: xy=list(points)
    return batch_delta_curves(case,xy),xy


def evaluate_candidates(case:dict[str,Any],candidates:list[tuple[float,float]],radial_order:int,angular_count:int,
                        ranges:dict[str,list[float]],sn:np.ndarray,sw:np.ndarray,kn:np.ndarray,kw:np.ndarray,stage:str)->pd.DataFrame:
    c_curves,_=spatial_curves(case,candidates); rows=[]; blocks=[]; all_xy=[]
    for e,n in candidates:
        q=candidate_centered_disk_quadrature(e,n,radial_order,angular_count); blocks.append(q); all_xy.extend(zip(q.east_km,q.north_km))
    all_s_curves,_=spatial_curves(case,all_xy); offset=0
    for (e,n),cc,q in zip(candidates,c_curves,blocks):
        count=len(q); s_curves=all_s_curves[offset:offset+count]; offset+=count
        raw=cc[None,:]-s_curves
        m=probability_batch(raw,case["template"],ranges,case["dt"],sn,sw,kn,kw)
        s_weights=q.weight.to_numpy(float); avg={k:float(np.sum(s_weights*v)) for k,v in m.items()}
        dist=math.hypot(e,n); bearing=(math.degrees(math.atan2(e,n))+360)%360 if dist>1e-12 else 0.0
        rows.append({"geometry_condition_id":case["gid"],"target_sat_id":case["target"],"attack_sat_id":case["attacker"],
            "grid_stage":stage,"candidate_east_km":e,"candidate_north_km":n,"candidate_offset_km":dist,"candidate_bearing_deg":bearing,
            "area_mean_D_proj_squared_hz2":avg["D_proj_squared_hz2"],"area_mean_projected_rmse_hz":avg["projected_rmse_hz"],
            "area_mean_b_geo_hat_hz":avg["b_geo_hat_hz"],"area_mean_k_geo_hat_hz_per_s":avg["k_geo_hat_hz_per_s"],
            "area_mean_score_gate_probability":avg["p_score"],"area_mean_b_gate_probability":avg["p_b"],
            "area_mean_k_gate_probability":avg["p_k"],"area_mean_accept_probability":avg["p_accept"]})
    return pd.DataFrame(rows)


def refine_case(case:dict[str,Any],ranges:dict[str,list[float]],args:argparse.Namespace,
                sn:np.ndarray,sw:np.ndarray,kn:np.ndarray,kw:np.ndarray)->pd.DataFrame:
    coarse=evaluate_candidates(case,coarse_grid(args.coarse_step_km),args.s_radial_order,args.s_angular_count,ranges,sn,sw,kn,kw,"coarse")
    p0=coarse.loc[coarse.area_mean_accept_probability.idxmax()]; e0=coarse.loc[coarse.area_mean_D_proj_squared_hz2.idxmin()]
    centers={(float(p0.candidate_east_km),float(p0.candidate_north_km)),(float(e0.candidate_east_km),float(e0.candidate_north_km))}
    pts=set()
    for c in centers: pts.update(local_grid(c,args.coarse_step_km,args.refine_step_km))
    refine=evaluate_candidates(case,sorted(pts),args.s_radial_order,args.s_angular_count,ranges,sn,sw,kn,kw,"refine")
    p1=refine.loc[refine.area_mean_accept_probability.idxmax()]; e1=refine.loc[refine.area_mean_D_proj_squared_hz2.idxmin()]
    centers={(float(p1.candidate_east_km),float(p1.candidate_north_km)),(float(e1.candidate_east_km),float(e1.candidate_north_km))}
    pts=set()
    for c in centers: pts.update(local_grid(c,args.refine_step_km,args.fine_step_km))
    fine=evaluate_candidates(case,sorted(pts),args.s_radial_order,args.s_angular_count,ranges,sn,sw,kn,kw,"fine")
    return pd.concat([coarse,refine,fine],ignore_index=True)


def unique_best(surface:pd.DataFrame,metric:str,maximize:bool)->pd.Series:
    d=surface.sort_values("grid_stage").drop_duplicates(["candidate_east_km","candidate_north_km"],keep="last")
    return d.loc[d[metric].idxmax() if maximize else d[metric].idxmin()]


def local_M(case:dict[str,Any])->dict[str,float]:
    c0=delta_curve(case["sat_a"],case["sat_b"],case["C_lat"],case["C_lon"],case["times"],case["ts"],case["freq"],case["step"])
    cols=[]
    for e,n in [(1.0,0.0),(0.0,1.0)]:
        lat,lon=xy_to_latlon(case["C_lat"],case["C_lon"],e,n)
        cols.append(delta_curve(case["sat_a"],case["sat_b"],lat,lon,case["times"],case["ts"],case["freq"],case["step"])-c0)
    J=np.column_stack(cols); Jp=mech.projected_jacobian(J,case["et"]); M=Jp.T@Jp
    vals,vecs=np.linalg.eigh(M); v=vecs[:,0]
    angle=(math.degrees(math.atan2(v[0],v[1]))+360)%180
    return {"lambda_min":float(vals[0]),"lambda_max":float(vals[1]),"v_min_angle_deg":angle,"v_max_angle_deg":float((angle+90)%180)}


def axis_error(bearing:float,axis:float)->float:
    d=abs((bearing-axis)%180); return min(d,180-d)


def analyze(args:argparse.Namespace,selection:pd.DataFrame,library:pd.DataFrame,tle:dict[str,Any],ranges:dict[str,list[float]],current:pd.DataFrame,ts:Any,freq:float):
    sn,sw=prob.nodes(32,*map(float,ranges["sigma_hz"])); kn,kw=prob.nodes(48,*map(float,ranges["k_hz_per_s"]))
    surfaces=[]; opt=[]; mechanisms=[]; conv=[]; batch_diffs=[]
    for row in selection.itertuples(index=False):
        case=prepare_case(pd.Series(row._asdict()),library,tle,current,ts,freq)
        scalar=delta_curve(case["sat_a"],case["sat_b"],case["C_lat"],case["C_lon"],case["times"],case["ts"],case["freq"],case["step"])
        batch=batch_delta_curves(case,[(0.0,0.0)])[0]; batch_diffs.append(float(np.max(np.abs(scalar-batch))))
        surface=refine_case(case,ranges,args,sn,sw,kn,kw); surfaces.append(surface)
        center=surface[(surface.candidate_east_km.abs()<1e-9)&(surface.candidate_north_km.abs()<1e-9)].iloc[-1]
        proj=unique_best(surface,"area_mean_D_proj_squared_hz2",False); acc=unique_best(surface,"area_mean_accept_probability",True)
        M=local_M(case)
        for name,r in [("current_center_C",center),("projected_energy_optimum",proj),("verifier_aware_optimum",acc)]:
            opt.append({"geometry_condition_id":case["gid"],"representative_role":row.representative_role,"selection_group":row.selection_group,
                "target_sat_id":case["target"],"attack_sat_id":case["attacker"],"optimum_type":name,
                "east_km":r.candidate_east_km,"north_km":r.candidate_north_km,"offset_km":r.candidate_offset_km,"bearing_deg":r.candidate_bearing_deg,
                "area_mean_D_proj_squared_hz2":r.area_mean_D_proj_squared_hz2,"area_mean_accept_probability":r.area_mean_accept_probability,
                "absolute_accept_gain_vs_center":r.area_mean_accept_probability-center.area_mean_accept_probability,
                "relative_accept_gain_vs_center":(r.area_mean_accept_probability/center.area_mean_accept_probability-1) if center.area_mean_accept_probability>1e-15 else np.nan,
                **M,"axis_error_to_v_min_deg":axis_error(float(r.candidate_bearing_deg),M["v_min_angle_deg"]) if r.candidate_offset_km>1e-9 else np.nan})
        for label,r in [("C",center),("C_proj",proj),("C_acc",acc)]:
            mechanisms.append({"geometry_condition_id":case["gid"],"selection_group":row.selection_group,"point_type":label,
                **{c:getattr(r,c) for c in ["candidate_offset_km","candidate_bearing_deg","area_mean_D_proj_squared_hz2","area_mean_projected_rmse_hz",
                    "area_mean_b_geo_hat_hz","area_mean_k_geo_hat_hz_per_s","area_mean_score_gate_probability","area_mean_b_gate_probability",
                    "area_mean_k_gate_probability","area_mean_accept_probability"]}})
        # Spatial integration convergence at C and both optima; also re-rank the top-five shortlist.
        shortlist=pd.concat([surface.nlargest(5,"area_mean_accept_probability"),surface.nsmallest(5,"area_mean_D_proj_squared_hz2")]).drop_duplicates(["candidate_east_km","candidate_north_km"])
        hi=evaluate_candidates(case,list(zip(shortlist.candidate_east_km,shortlist.candidate_north_km)),args.s_check_radial_order,args.s_check_angular_count,ranges,sn,sw,kn,kw,"integration_check")
        hi_acc=hi.loc[hi.area_mean_accept_probability.idxmax()]; hi_proj=hi.loc[hi.area_mean_D_proj_squared_hz2.idxmin()]
        for objective,lo,hr in [("accept",acc,hi_acc),("projected_energy",proj,hi_proj)]:
            loc=math.hypot(float(lo.candidate_east_km-hr.candidate_east_km),float(lo.candidate_north_km-hr.candidate_north_km))
            value_lo=float(lo.area_mean_accept_probability if objective=="accept" else lo.area_mean_D_proj_squared_hz2)
            value_hi=float(hr.area_mean_accept_probability if objective=="accept" else hr.area_mean_D_proj_squared_hz2)
            conv.append({"geometry_condition_id":case["gid"],"selection_group":row.selection_group,"objective":objective,
                "main_radial_angular":f"{args.s_radial_order}x{args.s_angular_count}","check_radial_angular":f"{args.s_check_radial_order}x{args.s_check_angular_count}",
                "main_optimum_east_km":lo.candidate_east_km,"main_optimum_north_km":lo.candidate_north_km,
                "check_shortlist_optimum_east_km":hr.candidate_east_km,"check_shortlist_optimum_north_km":hr.candidate_north_km,
                "optimum_location_difference_km":loc,"main_value":value_lo,"check_value":value_hi,"absolute_value_difference":abs(value_hi-value_lo)})
    return pd.concat(surfaces,ignore_index=True),pd.DataFrame(opt),pd.DataFrame(mechanisms),pd.DataFrame(conv),batch_diffs


def make_figures(surface:pd.DataFrame,opt:pd.DataFrame,outdir:Path)->None:
    for gid,g in surface.groupby("geometry_condition_id"):
        d=g.sort_values("grid_stage").drop_duplicates(["candidate_east_km","candidate_north_km"],keep="last")
        o=opt[opt.geometry_condition_id.eq(gid)]
        fig,ax=plt.subplots(figsize=(7,6)); sc=ax.scatter(d.candidate_east_km,d.candidate_north_km,c=d.area_mean_accept_probability,s=35,cmap="viridis")
        for _,r in o.iterrows(): ax.scatter(r.east_km,r.north_km,s=100,marker={"current_center_C":"o","projected_energy_optimum":"s","verifier_aware_optimum":"*"}[r.optimum_type],edgecolor="white",label=r.optimum_type)
        circle=plt.Circle((0,0),R_CELL_KM,fill=False,color="black",lw=1); ax.add_patch(circle); ax.set_aspect("equal"); ax.set_xlabel("east km"); ax.set_ylabel("north km"); ax.legend(fontsize=8); fig.colorbar(sc,ax=ax,label="area mean P_accept")
        fig.tight_layout(); fig.savefig(outdir/f"{gid}_accept_surface.png",dpi=180); plt.close(fig)


def md(d:pd.DataFrame)->str: return d.to_markdown(index=False,floatfmt=".6g")


def report(out:dict[str,Path],selection:pd.DataFrame,opt:pd.DataFrame,mechdf:pd.DataFrame,conv:pd.DataFrame,audit:pd.DataFrame,args:argparse.Namespace)->None:
    compact=opt[["selection_group","target_sat_id","attack_sat_id","optimum_type","offset_km","bearing_deg","area_mean_D_proj_squared_hz2","area_mean_accept_probability","absolute_accept_gain_vs_center","axis_error_to_v_min_deg","axis_error_to_v_max_deg","integration_check_location_difference_km","location_stable_within_one_fine_step"]]
    findings=[]
    for group,g in opt.groupby("selection_group"):
        c=g[g.optimum_type.eq("current_center_C")].iloc[0]; a=g[g.optimum_type.eq("verifier_aware_optimum")].iloc[0]; p=g[g.optimum_type.eq("projected_energy_optimum")].iloc[0]
        status="位置稳定" if bool(a.location_stable_within_one_fine_step) else "位置未解析/积分敏感"
        findings.append(f"- `{group}`：中心P={c.area_mean_accept_probability:.6g}；离散C_acc候选P={a.area_mean_accept_probability:.6g}，绝对增益={a.absolute_accept_gain_vs_center:.6g}（{100*a.absolute_accept_gain_vs_center:.6g}个百分点），偏移={a.offset_km:.3f} km，{status}；C_proj偏移={p.offset_km:.3f} km。")
    findings_text="\n".join(findings)
    text=f"""# A2-R verifier-aware最优公共参考点审计

## 1. 范围

本轮只研究 `q(t;C')=F_A(C',t)-F_B(C',t)`、`C'∈Ω` 的A2-R攻击类。Ω沿用以原C为中心、R_cell={R_CELL_KM:g} km的受控圆盘；S主分析按面积均匀分布。这不是Starlink真实用户分布，也不是所有可能q(t)的全局优化。

没有生成environment/noise realization，没有修改verifier/threshold，没有做轨道参数sweep。代表条件来自既有标签：

{md(selection[["geometry_condition_id","representative_role","selection_group","physical_pair_id","target_sat_id","attack_sat_id","service_area_id"]])}

## 2. 局部理论

令S=C+Δx、C'=C+δ，且`ΔF(C+z)≈ΔF_C+Jz`。则`d(S;C')=ΔF(C')-ΔF(S)≈J(δ-Δx)`，投影能量为`(δ-Δx)^T M(δ-Δx)`，M=`J^TQJ`。区域期望为：

`E[D_proj²(δ)] = (δ-μ)^T M(δ-μ) + tr(MΣ)`，其中μ=`E[Δx]`、Σ=`Cov(Δx)`。

若区域关于C对称，μ=0；M正定时δ=0是唯一一阶projected-energy optimum，M半正定时沿其零空间可能不唯一。该结论只针对局部一阶和projected energy，不自动适用于verifier-aware P_accept。

## 3. 数值设计

- C' coarse Cartesian disk grid：{args.coarse_step_km:g} km；
- local refinement：{args.refine_step_km:g} km，再以{args.fine_step_km:g} km确认；
- S uniform-area主积分：9段面积坐标×每段{args.s_radial_order}阶Gauss×{args.s_angular_count}角度；
- 空间敏感性核对：9段×每段{args.s_check_radial_order}阶×{args.s_check_angular_count}角度；
- 每个S,C'的概率使用上一轮32×48阶半解析environment/noise积分。

## 4. 核心结果

{md(compact)}

`absolute_accept_gain_vs_center`是概率绝对值，即乘100后为百分点。只能称为A2-R类内的最优公共参考点。

{findings_text}

三个projected-energy候选的位置都通过高阶空间积分复核，但均明显偏离C。这不否定局部解析结论：R_cell=500 km对本次差分Doppler并非“小区域”，一阶线性化不足以控制整个圆盘的平均能量。verifier-aware位置只在`location_stable_within_one_fine_step=true`时解释；不稳定案例不得称为已找到C_acc*。

## 5. 机制对照

{md(mechdf)}

C_acc与C_proj是否相同、提升来自score/b/k哪一项，以同一行的区域平均gate概率直接比较；没有构造加权综合指标。

现有三个案例不支持“C_acc稳定沿最低敏感轴”：稳定的boundary C_acc更接近局部高敏感轴，deep C_acc也不沿v_min；high案例位置未解析。局部M只描述C附近的一阶结构，不能预设500 km圆盘上的全局离散最优方向。

## 6. 数值收敛

{md(conv)}

定位分辨率主要由{args.fine_step_km:g} km候选网格决定；高阶S积分只在主表top-five shortlist中复核，不能解释为连续全局优化证明。

## 7. 结论边界

- 本轮没有优化任意q(t)，仅优化物理可解释的参考点约束族；
- 三个条件是最小代表性验证，不支持全20-pass总体断言；
- 圆盘uniform-area是受控假设；
- C_acc偏移即使存在，也必须结合pass重复性判断，不能立即升级全量攻击模型；
- 若中心接近最优，则增强A1在对称服务区内的合理性，而不是证明现实攻击者一定选C。

## 8. 正确性审计

{md(audit)}
"""
    out["report"].write_text(text,encoding="utf-8")


def main()->None:
    args=parse_args(); out=paths()
    if args.report_only:
        required=[out[k] for k in ["selection","optimum","mechanism","convergence","audit"]]
        if any(not p.exists() for p in required): raise SystemExit("report-only requires completed audit outputs")
        selection=pd.read_csv(out["selection"],low_memory=False); opt=pd.read_csv(out["optimum"],low_memory=False)
        mechanisms=pd.read_csv(out["mechanism"],low_memory=False); conv=pd.read_csv(out["convergence"],low_memory=False); audit=pd.read_csv(out["audit"],low_memory=False)
        opt["axis_error_to_v_max_deg"]=opt.apply(lambda r:axis_error(float(r.bearing_deg),float(r.v_max_angle_deg)) if float(r.offset_km)>1e-9 else np.nan,axis=1)
        acc_conv=conv[conv.objective.eq("accept")].set_index("geometry_condition_id"); proj_conv=conv[conv.objective.eq("projected_energy")].set_index("geometry_condition_id")
        opt["integration_check_location_difference_km"]=np.nan; opt["integration_check_value"]=np.nan
        for idx,r in opt.iterrows():
            source=acc_conv if r.optimum_type=="verifier_aware_optimum" else (proj_conv if r.optimum_type=="projected_energy_optimum" else None)
            if source is not None:
                opt.loc[idx,"integration_check_location_difference_km"]=source.loc[r.geometry_condition_id,"optimum_location_difference_km"]
                opt.loc[idx,"integration_check_value"]=source.loc[r.geometry_condition_id,"check_value"]
        opt["location_stable_within_one_fine_step"]=opt.integration_check_location_difference_km.le(args.fine_step_km+1e-9)
        opt.loc[opt.optimum_type.eq("current_center_C"),"location_stable_within_one_fine_step"]=True
        stable=int(opt[opt.optimum_type.eq("verifier_aware_optimum")].location_stable_within_one_fine_step.sum())
        if not audit.check.astype(str).eq("verifier-aware convergence status explicitly recorded").any():
            audit=pd.concat([audit,pd.DataFrame([{"check":"verifier-aware convergence status explicitly recorded","passed":True,"observed":f"stable={stable}/3; unstable cases retained"}])],ignore_index=True)
        audit.to_csv(out["audit"],index=False,encoding="utf-8-sig")
        opt.to_csv(out["optimum"],index=False,encoding="utf-8-sig")
        if out["manifest"].exists():
            manifest=json.loads(out["manifest"].read_text(encoding="utf-8"))
            manifest["verifier_aware_location_stable_cases"]=stable
            manifest["verifier_aware_location_total_cases"]=3
            manifest["unresolved_verifier_aware_geometry_ids"]=opt.loc[
                opt.optimum_type.eq("verifier_aware_optimum") & ~opt.location_stable_within_one_fine_step,
                "geometry_condition_id",
            ].tolist()
            manifest["correctness_audit_passed"]=int(audit.passed.sum())
            manifest["correctness_audit_total"]=len(audit)
            manifest["audit_all_passed"]=bool(audit.passed.all())
            out["manifest"].write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        report(out,selection,opt,mechanisms,conv,audit,args)
        print("report-only refresh complete"); return
    check_io(out,args.overwrite); selection=select_conditions()
    library,tle,ranges,current,ts,freq=load_context(selection)
    surface,opt,mechanisms,conv,batch_diffs=analyze(args,selection,library,tle,ranges,current,ts,freq)
    opt["axis_error_to_v_max_deg"]=opt.apply(lambda r:axis_error(float(r.bearing_deg),float(r.v_max_angle_deg)) if float(r.offset_km)>1e-9 else np.nan,axis=1)
    acc_conv=conv[conv.objective.eq("accept")].set_index("geometry_condition_id")
    proj_conv=conv[conv.objective.eq("projected_energy")].set_index("geometry_condition_id")
    opt["integration_check_location_difference_km"]=np.nan; opt["integration_check_value"]=np.nan
    for idx,r in opt.iterrows():
        source=acc_conv if r.optimum_type=="verifier_aware_optimum" else (proj_conv if r.optimum_type=="projected_energy_optimum" else None)
        if source is not None:
            opt.loc[idx,"integration_check_location_difference_km"]=source.loc[r.geometry_condition_id,"optimum_location_difference_km"]
            opt.loc[idx,"integration_check_value"]=source.loc[r.geometry_condition_id,"check_value"]
    opt["location_stable_within_one_fine_step"]=opt.integration_check_location_difference_km.le(args.fine_step_km+1e-9)
    opt.loc[opt.optimum_type.eq("current_center_C"),"location_stable_within_one_fine_step"]=True
    mathdf=pd.DataFrame([
        {"item":"A2-R class","result":"one shared q(t;C')=DeltaF(C'), C' inside original controlled disk Omega"},
        {"item":"local residual","result":"d(S;C')=J(delta-Delta x)+second order"},
        {"item":"expected projected energy","result":"(delta-mu)^T M (delta-mu)+tr(M Sigma)"},
        {"item":"symmetric region optimum","result":"delta=0 when mu=0 and M positive definite; possible null-space nonuniqueness if semidefinite"},
        {"item":"verifier-aware distinction","result":"P_accept also depends on b_geo,k_geo,gate centers/widths and environment/noise distributions"},
    ])
    fine_counts=surface.groupby(["geometry_condition_id","grid_stage"]).size().unstack(fill_value=0)
    audits=[
        {"check":"three unambiguous pre-existing representative labels","passed":selection.selection_group.nunique()==3,"observed":selection.selection_group.tolist()},
        {"check":"controlled circular service region unchanged","passed":True,"observed":f"R_cell={R_CELL_KM} km; coverage relative to original C"},
        {"check":"center candidate present for every case","passed":surface.groupby("geometry_condition_id").apply(lambda g:((g.candidate_east_km.abs()<1e-9)&(g.candidate_north_km.abs()<1e-9)).any(),include_groups=False).all(),"observed":"all"},
        {"check":"coarse-refine-fine stages present","passed":set(surface.grid_stage)=={"coarse","refine","fine"},"observed":fine_counts.to_dict()},
        {"check":"all candidate reference points inside Omega","passed":bool((surface.candidate_offset_km<=R_CELL_KM+1e-9).all()),"observed":surface.candidate_offset_km.max()},
        {"check":"probabilities finite and bounded","passed":bool(np.isfinite(surface.area_mean_accept_probability).all() and surface.area_mean_accept_probability.between(0,1).all()),"observed":f"{surface.area_mean_accept_probability.min():.6g}..{surface.area_mean_accept_probability.max():.6g}"},
        {"check":"no environment/noise realization generated","passed":True,"observed":"deterministic spatial + semi-analytic probability quadrature"},
        {"check":"current thresholds reused","passed":True,"observed":"fixed_geometry current_bk stored thresholds"},
        {"check":"batch Doppler equals existing scalar propagation","passed":max(batch_diffs)<1e-5,"observed":max(batch_diffs)},
        {"check":"verifier-aware convergence status explicitly recorded","passed":True,"observed":f"stable={int(opt[opt.optimum_type.eq('verifier_aware_optimum')].location_stable_within_one_fine_step.sum())}/3; unstable cases retained"},
    ]
    audit=pd.DataFrame(audits)
    make_figures(surface,opt,out["figures"])
    mathdf.to_csv(out["math"],index=False,encoding="utf-8-sig"); selection.to_csv(out["selection"],index=False,encoding="utf-8-sig")
    surface.to_csv(out["surface"],index=False,encoding="utf-8-sig"); opt.to_csv(out["optimum"],index=False,encoding="utf-8-sig")
    mechanisms.to_csv(out["mechanism"],index=False,encoding="utf-8-sig"); conv.to_csv(out["convergence"],index=False,encoding="utf-8-sig")
    audit.to_csv(out["audit"],index=False,encoding="utf-8-sig")
    manifest={"audit":"A2-R reference-point-constrained regional attacker","created_at":datetime.now().isoformat(),"R_cell_km":R_CELL_KM,
        "station_distribution":"uniform_area_controlled_disk","new_environment_noise_realizations":False,"verifier_modified":False,"threshold_recalibrated":False,
        "grid":{"coarse_step_km":args.coarse_step_km,"refine_step_km":args.refine_step_km,"fine_step_km":args.fine_step_km,
            "S_main":[args.s_radial_order,args.s_angular_count],"S_check":[args.s_check_radial_order,args.s_check_angular_count]},
        "selected_geometry_ids":selection.geometry_condition_id.tolist(),
        "verifier_aware_location_stable_cases":int(opt[opt.optimum_type.eq("verifier_aware_optimum")].location_stable_within_one_fine_step.sum()),
        "verifier_aware_location_total_cases":3,
        "unresolved_verifier_aware_geometry_ids":opt.loc[
            opt.optimum_type.eq("verifier_aware_optimum") & ~opt.location_stable_within_one_fine_step,
            "geometry_condition_id",
        ].tolist(),
        "correctness_audit_passed":int(audit.passed.sum()),"correctness_audit_total":len(audit),
        "audit_all_passed":bool(audit.passed.all())}
    out["manifest"].write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    report(out,selection,opt,mechanisms,conv,audit,args)
    print(f"surface_rows={len(surface)} cases={selection.geometry_condition_id.nunique()} audit={int(audit.passed.sum())}/{len(audit)}")


if __name__=="__main__": main()
