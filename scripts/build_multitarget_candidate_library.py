#!/usr/bin/env python
"""Build candidate geometry library for controlled Starlink multi-target passes."""

from __future__ import annotations
import argparse, sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
import numpy as np
import pandas as pd
from skyfield.api import EarthSatellite, load, wgs84

C_MPS=299_792_458.0
class InputError(ValueError): pass
def fail(m): raise InputError(m)

def parse_args():
    p=argparse.ArgumentParser()
    p.add_argument("--tle-file", required=True, type=Path)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--candidate-limit", type=int, default=200)
    p.add_argument("--overwrite", action="store_true")
    return p.parse_args()

def parse_utc_series(vals):
    out=[]
    for v in vals:
        s=str(v)
        if s.endswith("Z"): s=s[:-1]+"+00:00"
        d=datetime.fromisoformat(s)
        out.append((d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc))
    return out

def parse_tle(path, ts):
    lines=[l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out=[]; i=0
    while i+2<len(lines):
        n,l1,l2=lines[i].strip(),lines[i+1].strip(),lines[i+2].strip()
        if l1.startswith("1 ") and l2.startswith("2 ") and n.upper().startswith("STARLINK"):
            try:
                sat=EarthSatellite(l1,l2,n,ts)
                out.append(dict(name=n,norad=l1[2:7].strip(),line1=l1,line2=l2,epoch=sat.epoch.utc_iso(),
                                inclination=float(l2[8:16]),mean_motion=float(l2[52:63]),sat=sat))
            except Exception: pass
            i+=3
        else: i+=1
    return out

def select(entries, target_norad, limit):
    target=next((e for e in entries if e["norad"]==str(target_norad)), None)
    if not target: fail(f"true target {target_norad} 不在 TLE 文件中")
    for e in entries:
        e["score"]=abs(e["inclination"]-target["inclination"])+10*abs(e["mean_motion"]-target["mean_motion"])
    sel=sorted(entries,key=lambda e:(e["score"],e["name"]))[:limit]
    if target["norad"] not in {e["norad"] for e in sel}: sel=[target]+sel[:limit-1]
    sel=sorted(sel,key=lambda e:(0 if e["norad"]==target["norad"] else 1,e["score"],e["name"]))
    for rank,e in enumerate(sel,1): e["rank"]=rank; e["is_true"]=e["norad"]==target["norad"]
    return sel

def main():
    a=parse_args()
    try:
        if a.output.exists() and not a.overwrite: fail(f"输出文件已存在，若确认覆盖请添加 --overwrite: {a.output}")
        if not a.dataset.exists(): fail(f"dataset 不存在: {a.dataset}")
        if not a.tle_file.exists(): fail(f"TLE 文件不存在: {a.tle_file}")
        df=pd.read_csv(a.dataset)
        req=["pass_id","target_name","target_norad_id","station_name","station_lat_deg","station_lon_deg","station_alt_m","center_freq_hz","t_abs_utc","t_rel_s"]
        miss=[c for c in req if c not in df.columns]
        if miss: fail("dataset 缺少字段: "+", ".join(miss))
        ts=load.timescale(); entries=parse_tle(a.tle_file, ts)
        rows=[]
        for pass_id,base in df.drop_duplicates(["pass_id","t_abs_utc"]).groupby("pass_id", sort=True):
            base=base.sort_values("t_rel_s").reset_index(drop=True)
            target_norad=str(base.target_norad_id.iloc[0]); target_name=str(base.target_name.iloc[0])
            candidates=select(entries,target_norad,a.candidate_limit)
            site=wgs84.latlon(float(base.station_lat_deg.iloc[0]),float(base.station_lon_deg.iloc[0]),elevation_m=float(base.station_alt_m.iloc[0]))
            times=ts.from_datetimes(parse_utc_series(base.t_abs_utc)); step=float(np.median(np.diff(base.t_rel_s))) if len(base)>1 else 1.0
            freq=float(base.center_freq_hz.iloc[0])
            for c in candidates:
                topo=(c["sat"]-site).at(times); elev=topo.altaz()[0].degrees; rng=topo.distance().m
                rr=np.gradient(rng, step); dop=-freq*rr/C_MPS
                rows.append(pd.DataFrame(dict(pass_id=pass_id,target_name=target_name,target_norad_id=target_norad,
                    candidate_name=c["name"],candidate_norad_id=c["norad"],candidate_rank=c["rank"],is_true_target=c["is_true"],
                    station_name=base.station_name.iloc[0],center_freq_hz=freq,t_abs_utc=base.t_abs_utc,t_rel_s=base.t_rel_s,
                    elevation_deg=elev,range_m=rng,range_rate_mps=rr,doppler_hz=dop,f_geo_candidate_hz=freq+dop,
                    tle_epoch=c["epoch"],inclination_deg=c["inclination"],mean_motion_rev_per_day=c["mean_motion"])))
        lib=pd.concat(rows,ignore_index=True)
        a.output.parent.mkdir(parents=True, exist_ok=True); lib.to_csv(a.output,index=False)
    except InputError as e:
        print(f"错误: {e}", file=sys.stderr); return 2
    print(f"多 target candidate library 生成完成: {a.output}")
    print(f"pass 数: {lib.pass_id.nunique()}, 每 pass 候选数: {lib.groupby('pass_id').candidate_norad_id.nunique().min()}-{lib.groupby('pass_id').candidate_norad_id.nunique().max()}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
