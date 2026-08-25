#!/usr/bin/env python3
"""PDD22 FCD screening v2: corrected VD direction + PDD-anchored March/August trends.

Screening only. Sentinel-2 is harmonized to the PDD Table 3-1 provincial FCD
shares in each 2023 same-month reference; those thresholds are then frozen
through 2026. This is not a verified T-VER carbon calculation.
"""
from __future__ import annotations

import csv, json, os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image

import process_pdd22_fcd as src
from pdd22_config import (
    PDD22_PLOTS, PDD_BASELINE_FCD_BY_PROVINCE, PDD_BASELINE_TREE_CARBON_TCO2E,
    PDD_INCREMENT_TCO2E_PER_RAI_YEAR, PDD_TOTAL_PROJECT_AREA_RAI,
)

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data/pdd22/plots_catalog.json"
OUT = ROOT / "data/pdd22_v2"
SERIES = {"march": [(2023,3),(2024,3),(2025,3),(2026,3)], "august": [(2023,8),(2024,8),(2025,8),(2026,8)]}
WORKERS = int(os.getenv("PDD22_V2_WORKERS", "6"))
SAMPLE = int(os.getenv("PDD22_REFERENCE_SAMPLE", "6000"))
PLOW, PHIGH = 2.0, 98.0
WATER_MNDWI, WATER_NDVI = 0.0, 0.25
COLORS = {1:(220,53,69), 2:(255,193,7), 3:(40,167,69), 4:(23,162,184)}


def mk(y,m): return f"{y:04d}-{m:02d}"
def ty(y): return y + 543

def load_plots():
    p = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert len(p) == 22 and round(sum(float(x["area_rai"]) for x in p),2) == 6775.53
    return p

def build_one(plot,y,m): return src.build_composite(src.base.stac_client(), plot, y, m)
def build_batch(plots,y,m):
    out = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fs = {ex.submit(build_one,p,y,m):p for p in plots}
        for f in as_completed(fs):
            p=fs[f]; out[p["code"]]=f.result(); d=out[p["code"]]
            print(p["code"], mk(y,m), d["status"], "clear", d.get("clear_pixel_pct"), flush=True)
    return out

def water(d): return d["valid"] & (d["mndwi"]>WATER_MNDWI) & (d["ndvi"]<=WATER_NDVI)
def sample_cols(arrs,mask,n=SAMPLE):
    ix=np.flatnonzero(mask.ravel())
    if not ix.size: return np.empty((0,len(arrs)))
    if ix.size>n: ix=ix[np.linspace(0,ix.size-1,n,dtype=np.int64)]
    x=np.column_stack([a.ravel()[ix] for a in arrs]).astype(float)
    return x[np.isfinite(x).all(axis=1)]

def fit(ref, refkey):
    xs=[]; cs=[]
    for d in ref.values():
        land=d["valid"] & ~water(d)
        s=sample_cols([d["avi"],d["bsi"],d["ndvi"]],land)
        c=sample_cols([d["csi"]],land)
        if len(s): xs.append(s)
        if len(c): cs.append(c[:,0])
    z=np.vstack(xs); x=z[:,:2]; ndvi=z[:,2]; mean=x.mean(0); ctr=x-mean
    vals,vecs=np.linalg.eigh(np.cov(ctr,rowvar=False)); v=vecs[:,np.argmax(vals)].astype(float); pc=ctr@v
    corr=float(np.corrcoef(pc,ndvi)[0,1])
    if np.isfinite(corr) and corr>0: v*=-1; pc*=-1; corr*=-1
    lo,hi=np.percentile(pc,[PLOW,PHIGH]); clo,chi=np.percentile(np.concatenate(cs),[PLOW,PHIGH])
    return {"reference":refkey,"mean":mean.tolist(),"pc1":v.tolist(),"pc1_ndvi_corr":corr,
            "vd_raw_low":float(lo),"vd_raw_high":float(hi),"csi_low":float(clo),"csi_high":float(chi),
            "vd_rule":"PDD p.109: maximum PCA -> VD 0%; minimum PCA -> VD 100%"}

def score(d,c):
    mean=np.array(c["mean"]); v=np.array(c["pc1"]); valid=d["valid"]
    pc=(d["avi"]-mean[0])*v[0]+(d["bsi"]-mean[1])*v[1]
    vd=np.clip((c["vd_raw_high"]-pc)/(c["vd_raw_high"]-c["vd_raw_low"])*100,0,100)
    ssi=np.clip((d["csi"]-c["csi_low"])/(c["csi_high"]-c["csi_low"])*100,0,100)
    f=np.sqrt(vd*ssi+1)-1; f[~valid]=np.nan
    w=water(d); return f,w,valid & ~w

def wq(v,w,q):
    o=np.argsort(v); v=v[o]; w=w[o]; cs=np.cumsum(w); return float(v[np.searchsorted(cs,q*cs[-1],side="left")])
def anchors(plots,ref,cal):
    vv=defaultdict(list); ww=defaultdict(list); by={p["code"]:p for p in plots}
    for code,d in ref.items():
        f,_,land=score(d,cal); x=f[land]; x=x[np.isfinite(x)]
        if len(x):
            p=by[code]; vv[p["province"]].append(x); ww[p["province"]].append(np.full(len(x),float(p["area_rai"])/max(1,int(d["inside"].sum()))))
    gv=np.concatenate([np.concatenate(x) for x in vv.values() if x]); gw=np.concatenate([np.concatenate(x) for x in ww.values() if x])
    out={}
    for prov,t in PDD_BASELINE_FCD_BY_PROVINCE.items():
        local=bool(vv.get(prov)); v=np.concatenate(vv[prov]) if local else gv; w=np.concatenate(ww[prov]) if local else gw
        ct=t["high"]+t["medium"]+t["low"]; q1=t["low"]/ct; q2=(t["low"]+t["medium"])/ct
        out[prov]={"low_cut":wq(v,w,q1),"high_cut":wq(v,w,q2),"class_frac":ct/t["total"],
                   "scope":"province_2023" if local else "global_2023_fallback",
                   "pdd":{"high":t["high"],"medium":t["medium"],"low":t["low"],"bare_error":t["bare_error"]}}
    return out

def qal(clear,wpct):
    if clear<30:return "LOW_QA"
    if wpct>40:return "TIDE_DOMINATED"
    if wpct>20:return "WATER_INFLUENCED"
    return "COMPARABLE"
def classify(p,d,cal,anc):
    a=anc[p["province"]]; f,w,land=score(d,cal); lo=land&(f<a["low_cut"]); med=land&(f>=a["low_cut"])&(f<a["high_cut"]); hi=land&(f>=a["high_cut"])
    cls=np.zeros(d["inside"].shape,np.uint8); cls[lo]=1; cls[med]=2; cls[hi]=3; cls[w]=4
    n=max(1,int(d["inside"].sum())); area=float(p["area_rai"]); unk=d["inside"]&(cls==0)
    obs={"high":hi.sum()/n*area,"medium":med.sum()/n*area,"low":lo.sum()/n*area,"water":w.sum()/n*area,"unknown":unk.sum()/n*area}
    cn=int(hi.sum()+med.sum()+lo.sum()); target=area*a["class_frac"]
    eq={k:(target*int(mask.sum())/cn if cn else None) for k,mask in [("high",hi),("medium",med),("low",lo)]}
    return {"status":d["status"],"qa":qal(float(d["clear_pixel_pct"]),obs["water"]/area*100),"clear_pct":float(d["clear_pixel_pct"]),
            "scenes":int(d["scenes_used"]),"scene_ids":[x["id"] for x in d["scene_metadata"]],
            "green_rai":None if eq["high"] is None else round(eq["high"],4),"yellow_rai":None if eq["medium"] is None else round(eq["medium"],4),
            "red_rai":None if eq["low"] is None else round(eq["low"],4),"bare_error_alloc_rai":round(area*(1-a["class_frac"]),4),
            "water_observed_rai":round(obs["water"],4),"unknown_observed_rai":round(obs["unknown"],4),
            "mean_fcd_score":round(float(np.nanmean(f[land])),4) if land.any() else None}, cls

def save_map(path,cls,inside):
    path.parent.mkdir(parents=True,exist_ok=True); im=np.zeros((*cls.shape,4),np.uint8)
    for k,c in COLORS.items(): im[cls==k,:3]=c; im[cls==k,3]=255
    u=inside&(cls==0); im[u,:3]=(140,140,140); im[u,3]=180; Image.fromarray(im,"RGBA").save(path,optimize=True)
def write_csv(path,rows):
    if not rows:return
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def run_series(name,dates,plots):
    batches={}; y0,m0=dates[0]; batches[(y0,m0)]=build_batch(plots,y0,m0); cal=fit(batches[(y0,m0)],mk(y0,m0)); anc=anchors(plots,batches[(y0,m0)],cal)
    obs={p["code"]:{} for p in plots}
    for y,m in dates:
        if (y,m) not in batches:batches[(y,m)]=build_batch(plots,y,m)
        for p in plots:
            r,cls=classify(p,batches[(y,m)][p["code"]],cal,anc); r.update(month=mk(y,m),thai_year=ty(y)); obs[p["code"]][mk(y,m)]=r
            save_map(OUT/"maps"/name/p["code"]/f"fcd_{mk(y,m)}.png",cls,batches[(y,m)][p["code"]]["inside"])
    portfolio=[]
    for y,m in dates:
        k=mk(y,m); oo=[obs[p["code"]][k] for p in plots]; tot=lambda f:round(sum(float(x[f]) for x in oo if x[f] is not None),2)
        portfolio.append({"month":k,"thai_year":ty(y),"green_rai":tot("green_rai"),"yellow_rai":tot("yellow_rai"),"red_rai":tot("red_rai"),
                          "bare_error_alloc_rai":tot("bare_error_alloc_rai"),"water_observed_rai":tot("water_observed_rai"),"unknown_observed_rai":tot("unknown_observed_rai"),
                          "low_qa_plots":sum(x["qa"]=="LOW_QA" for x in oo),"water_qa_plots":sum(x["qa"] in {"WATER_INFLUENCED","TIDE_DOMINATED"} for x in oo)})
    ref=portfolio[0]
    for r in portfolio:r["green_delta_vs_2023_rai"]=round(r["green_rai"]-ref["green_rai"],2); r["red_delta_vs_2023_rai"]=round(r["red_rai"]-ref["red_rai"],2)
    plots_out=[]
    for p in plots:
        rr=[obs[p["code"]][mk(y,m)] for y,m in dates]; a,b=rr[0],rr[-1]
        dg=None if a["green_rai"] is None or b["green_rai"] is None else round(b["green_rai"]-a["green_rai"],2)
        dr=None if a["red_rai"] is None or b["red_rai"] is None else round(b["red_rai"]-a["red_rai"],2)
        plots_out.append({"code":p["code"],"province":p["province"],"area_rai":p["area_rai"],"delta_green_rai":dg,"delta_red_rai":dr,"observations":rr})
    return {"series":name,"calibration":cal,"province_anchors":anc,"portfolio":portfolio,"plots":plots_out}

def consensus(results,plots):
    by={r["series"]:{x["code"]:x for x in r["plots"]} for r in results}; rows=[]
    for p in plots:
        ds=[]; row={"code":p["code"],"province":p["province"],"area_rai":p["area_rai"]}; qpen=0
        for s in ("march","august"):
            x=by[s][p["code"]]; row[s+"_green_delta_rai"]=x["delta_green_rai"]; row[s+"_red_delta_rai"]=x["delta_red_rai"]; qa=x["observations"][-1]["qa"]; row[s+"_2026_qa"]=qa
            if x["delta_green_rai"] is not None:ds.append((x["delta_green_rai"],x["delta_red_rai"]))
            qpen += 2 if qa=="LOW_QA" else 1 if qa in {"WATER_INFLUENCED","TIDE_DOMINATED"} else 0
        ag=round(float(np.mean([x[0] for x in ds])),2) if ds else None; ar=round(float(np.mean([x[1] for x in ds])),2) if ds else None
        row["avg_green_delta_rai"],row["avg_red_delta_rai"]=ag,ar; tol=max(1,float(p["area_rai"])*.01)
        dirs=["improve" if g>tol and r<-tol else "decline" if g<-tol and r>tol else "mixed" for g,r in ds]
        row["season_agreement"]="BOTH_SEASONS_"+dirs[0].upper() if len(dirs)==2 and dirs[0]==dirs[1] else "SEASON_SENSITIVE"
        concern=max(0,-ag if ag is not None else 0)+max(0,ar if ar is not None else 0)+qpen*tol; row["field_priority_score"]=round(concern,2)
        row["field_priority"]="HIGH" if "DECLINE" in row["season_agreement"] or concern>float(p["area_rai"])*.1 else "REVIEW" if row["season_agreement"]=="SEASON_SENSITIVE" or qpen else "ROUTINE"; rows.append(row)
    return sorted(rows,key=lambda x:x["field_priority_score"],reverse=True)

def main():
    OUT.mkdir(parents=True,exist_ok=True); plots=load_plots(); results=[]
    for name,dates in SERIES.items():
        r=run_series(name,dates,plots); results.append(r); (OUT/f"{name}_result.json").write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding="utf-8"); write_csv(OUT/f"{name}_portfolio.csv",r["portfolio"])
    rank=consensus(results,plots); write_csv(OUT/"plot_change_ranking.csv",rank)
    lines=["# PDD22 Satellite FCD Screening V2","","**Preliminary screening; not verified T-VER credit.**","","2023 is a satellite reference, not the official PDD baseline. PDD-equivalent 2023 class shares are anchored to PDD Table 3-1 by province, so the 2023 fit is calibration rather than independent validation.","","| Series | Year | Green | Yellow | Red | Water observed | Low QA |","|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        for x in r["portfolio"]: lines.append(f"| {r['series']} | {x['thai_year']} | {x['green_rai']:,.2f} | {x['yellow_rai']:,.2f} | {x['red_rai']:,.2f} | {x['water_observed_rai']:,.2f} | {x['low_qa_plots']} |")
    lines += ["","## 2023 → 2026",* [f"- {r['series']}: green {r['portfolio'][-1]['green_delta_vs_2023_rai']:+,.2f} rai; red {r['portfolio'][-1]['red_delta_vs_2023_rai']:+,.2f} rai" for r in results],"","## Highest field-check priority"]
    for i,x in enumerate(rank[:10],1): lines.append(f"{i}. {x['code']} — {x['field_priority']} — {x['season_agreement']} — green Δ {x['avg_green_delta_rai']} rai, red Δ {x['avg_red_delta_rai']} rai")
    lines += ["","## Carbon boundary",f"PDD baseline tree carbon = {PDD_BASELINE_TREE_CARBON_TCO2E:,.2f} tCO2e; planning increment = {PDD_INCREMENT_TCO2E_PER_RAI_YEAR:.2f} tCO2e/rai/year. No satellite-adjusted tCO2e is asserted because the PDD does not provide a validated FCD-class carbon-density conversion.","","August 2026 is a partial current-month observation using only scenes available when the workflow runs."]
    (OUT/"EXECUTIVE_SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    carbon={"screening_only":True,"pdd_baseline_tree_carbon_tco2e":PDD_BASELINE_TREE_CARBON_TCO2E,"pdd_increment_tco2e_per_rai_year":PDD_INCREMENT_TCO2E_PER_RAI_YEAR,"project_area_rai":PDD_TOTAL_PROJECT_AREA_RAI,"pdd_planning_benchmark":[{"thai_year":2567,"cumulative_increment_tco2e":0},{"thai_year":2568,"cumulative_increment_tco2e":round(PDD_TOTAL_PROJECT_AREA_RAI*PDD_INCREMENT_TCO2E_PER_RAI_YEAR,2)},{"thai_year":2569,"cumulative_increment_tco2e":round(PDD_TOTAL_PROJECT_AREA_RAI*PDD_INCREMENT_TCO2E_PER_RAI_YEAR*2,2)}],"satellite_adjusted_credit_tco2e":None}
    (OUT/"carbon_screening.json").write_text(json.dumps(carbon,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"manifest.json").write_text(json.dumps({"model_version":"pdd22_v2_pdd_anchored","plot_count":22,"project_area_rai":6775.53,"series":SERIES,"limits":["Sentinel-2 adaptation, not exact Landsat-8 PDD reproduction","2023 provincial anchoring is calibration, not validation","water/cloud reported as QA","August 2026 partial current month","no satellite carbon credit asserted"]},ensure_ascii=False,indent=2),encoding="utf-8")
    for r in results: print(r["series"],r["portfolio"][-1],flush=True)
    return 0
if __name__=="__main__": raise SystemExit(main())
