#!/usr/bin/env python3
"""Ingest only genuinely missing registry observations from user-provided Drive Sentinel-2 L2A TIFF batches.

Safety:
- Never overwrite an existing usable registry observation.
- Never substitute another month.
- Never use PDD-only footprint TIFFs for registry scope.
- Reuse the canonical v4 Green Cover Proxy equations and thresholds.
- Scientific TIFF DN encoding is validated separately; these batches use DN / 10000 reflectance.
"""
from __future__ import annotations
import json, re, zipfile, warnings, sys
from pathlib import Path

R=Path(__file__).resolve().parents[1]
if str(R) not in sys.path:
    sys.path.insert(0,str(R))
from collections import defaultdict, Counter
from datetime import datetime, timezone
import numpy as np
from PIL import Image
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import reproject, Resampling, transform_bounds
from shapely.geometry import shape, box

import process_verified_12_dates as base
import process_verified_12_dates_v4 as v4

IN=R/'incoming'
CAT=R/'data/plots_catalog.json'
TS=R/'data/timeseries_verified_12.json'
OUT=R/'audit-artifacts'
OUT.mkdir(exist_ok=True)

MONTHS=[base.month_key(y,m) for y,m in base.MILESTONE_MONTHS]
BANDS=['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12','SCL']
REF_BANDS=[b for b in BANDS if b!='SCL']
catalog=json.loads(CAT.read_text(encoding='utf-8'))
series=json.loads(TS.read_text(encoding='utf-8'))
pdd=json.loads((R/'data/pdd22/plots_catalog.json').read_text(encoding='utf-8'))
byid={int(p['id']):p for p in catalog}
series_by={int(p['id']):p for p in series}
pdd_by={p['code']:p for p in pdd}

def dcode(p):
    m=re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])',p.get('name',''),re.I)
    return f"{int(m.group(1))}-{m.group(2).upper()}" if m else p['code']
bycode=defaultdict(list)
for p in catalog: bycode[dcode(p)].append(p)

def resolve_ident(ident):
    if ident.upper().startswith('PLOT_'):
        try: return int(ident.split('_')[-1])
        except: return None
    m=re.fullmatch(r'(\d{1,3})-(STC|VSD|EVR)',ident,re.I)
    if not m:return None
    c=f"{int(m.group(1))}-{m.group(2).upper()}";xs=bycode.get(c,[])
    return int(xs[0]['id']) if len(xs)==1 else None

members={}
scenes=defaultdict(lambda:defaultdict(set))
for zp in sorted(IN.rglob('*.zip')):
    with zipfile.ZipFile(zp) as z:
        bad=z.testzip()
        if bad: raise RuntimeError(f'{zp.name}: corrupt member {bad}')
        for inf in z.infolist():
            n=inf.filename.replace('\\','/')
            if inf.is_dir() or n.startswith('__MACOSX/') or '/._' in n or not n.lower().endswith('.tif'):continue
            ps=[x for x in n.split('/') if x]
            if len(ps)<4:continue
            ident,mo,scene,fn=ps[-4],ps[-3],ps[-2],ps[-1]
            band=Path(fn).stem.upper()
            if mo not in MONTHS or band not in BANDS or not scene.startswith(('S2A_','S2B_','S2C_')):continue
            pid=resolve_ident(ident)
            if pid not in byid:continue
            scenes[(pid,mo)][scene].add(band)
            members[(pid,mo,scene,band)]=(zp,inf.filename)

def existing_usable(pid,mo):
    p=series_by[pid]
    o=next((x for x in p.get('timeseries',[]) if x.get('month')==mo),None)
    if not o:return False,o
    return o.get('status') in {'observed_single_scene','observed_monthly_composite'} and float(o.get('clear_pixel_pct') or 0)>=5,o

def source_scope(pid,mo,scene):
    zp,name=members[(pid,mo,scene,'B02')]
    with zipfile.ZipFile(zp) as z:
        raw=z.read(name)
    with MemoryFile(raw) as mf, mf.open() as ds:
        bb=transform_bounds(ds.crs,'EPSG:4326',*ds.bounds,densify_pts=21)
    fp=box(*bb);reg=shape(byid[pid]['geometry']);rc=reg.intersection(fp).area/max(reg.area,1e-20)
    code=dcode(byid[pid]);pg=shape(pdd_by[code]['geometry']) if code in pdd_by else None
    pc=pg.intersection(fp).area/max(pg.area,1e-20) if pg else None
    if pg is not None and pc>0.999 and rc<0.999:return 'PDD_ONLY_FOOTPRINT'
    if rc>0.999:return 'REGISTRY_CONTAINED'
    return 'PARTIAL_REGISTRY'

def read_member_to_grid(pid,mo,scene,band,grid):
    zp,name=members[(pid,mo,scene,band)]
    with zipfile.ZipFile(zp) as z:
        raw=z.read(name)
    with MemoryFile(raw) as mf, mf.open() as ds:
        if band=='SCL':
            dst=np.zeros((grid.height,grid.width),dtype=np.float32)
            reproject(rasterio.band(ds,1),dst,src_transform=ds.transform,src_crs=ds.crs,src_nodata=ds.nodata,
                      dst_transform=grid.transform,dst_crs='EPSG:4326',dst_nodata=0,resampling=Resampling.nearest)
            return dst
        dst=np.full((grid.height,grid.width),np.nan,dtype=np.float32)
        reproject(rasterio.band(ds,1),dst,src_transform=ds.transform,src_crs=ds.crs,src_nodata=ds.nodata,
                  dst_transform=grid.transform,dst_crs='EPSG:4326',dst_nodata=np.nan,resampling=Resampling.bilinear)
        valid=np.isfinite(dst)
        # Validated against 300 committed observations: Drive source uses Sentinel reflectance DN / 10000 with no -1000 shift.
        dst[valid]=dst[valid]/10000.0
        return dst

def scene_meta(scene,clear):
    m=re.search(r'MSIL2A_(\d{8}T\d{6})',scene)
    dt=None
    if m:
        try:dt=datetime.strptime(m.group(1),'%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc).isoformat()
        except:pass
    b=re.search(r'_N(\d{4})_',scene)
    return {'id':scene,'datetime':dt,'catalog_cloud_cover_pct':None,'clear_inside_pct':round(clear*100,2),
            'processing_baseline':b.group(1) if b else None,'ingest_source':'user Drive Sentinel-2 L2A TIFF'}

def finite_median(values,digits=4):
    v=values[np.isfinite(values)]
    return round(float(np.median(v)),digits) if v.size else None

def process(pid,mo,complete_scenes):
    plot=byid[pid];geom=shape(plot['geometry']);grid=base.compute_grid(geom);inside=base.plot_mask(geom,grid)
    threshold,cal_status,cal_source=v4.threshold_info(plot)
    stack=[];metas=[]
    for scene in sorted(complete_scenes):
        arrays={b:read_member_to_grid(pid,mo,scene,b,grid) for b in BANDS}
        clear=base.cloud_clear_mask(arrays['SCL'],*[arrays[b] for b in REF_BANDS])
        ratio=float((clear&inside).sum()/max(1,int(inside.sum())))
        if ratio<.01:continue
        ndvi=base.safe_normalized_difference(arrays['B08'],arrays['B04'])
        ndre=base.safe_normalized_difference(arrays['B8A'],arrays['B05'])
        mndwi=base.safe_normalized_difference(arrays['B03'],arrays['B11'])
        evi=base.compute_evi(arrays['B02'],arrays['B04'],arrays['B08'])
        mfi=base.compute_mfi(arrays['B04'],arrays['B05'],arrays['B06'],arrays['B07'],arrays['B8A'],arrays['B12'])
        rgb=np.stack([arrays['B04'],arrays['B03'],arrays['B02']],axis=0)
        rgb[:,~clear]=np.nan
        for a in (ndvi,ndre,mndwi,evi,mfi):a[~clear]=np.nan
        stack.append({'rgb':rgb,'ndvi':ndvi,'ndre':ndre,'mndwi':mndwi,'evi':evi,'mfi':mfi})
        metas.append(scene_meta(scene,ratio))
    if not stack:return None,'NO_CLEAR_SCENE'
    def med(k):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',category=RuntimeWarning)
            return np.nanmedian(np.stack([x[k] for x in stack]),axis=0)
    rgb,ndvi,ndre,mndwi,evi,mfi=[med(k) for k in ['rgb','ndvi','ndre','mndwi','evi','mfi']]
    valid=inside&np.isfinite(ndvi)&np.isfinite(ndre)&np.isfinite(mndwi)&np.isfinite(mfi)
    valid_rgb=inside&np.isfinite(rgb).all(axis=0)
    cov=float(valid.sum()/max(1,int(inside.sum())))
    if cov<base.MIN_VALID_INSIDE_RATIO:return None,f'LOW_COVERAGE:{cov*100:.2f}'
    vegetation=valid&(ndvi>threshold)
    water=valid&(mndwi>base.OPEN_WATER_MNDWI_THRESHOLD)&~vegetation
    nonveg=valid&~vegetation&~water
    mfi_signal=valid&(mfi>base.SUBMERGED_MANGROVE_MFI_THRESHOLD)
    mfi_only=mfi_signal&~vegetation
    submerged=mfi_signal&water
    cnt=max(1,int(valid.sum()));pct=lambda m:float(m.sum()/cnt*100)
    ndv=ndvi[valid];mw=mndwi[valid]
    result={
      'month':mo,'year':int(mo[:4]),'month_num':int(mo[5:]),'status':'observed_single_scene' if len(stack)==1 else 'observed_monthly_composite',
      'source':base.SOURCE_LABEL,'proxy_version':v4.PROXY_VERSION,'green_proxy_threshold':round(float(threshold),3),
      'green_proxy_calibration_status':cal_status,'green_proxy_calibration_source':cal_source,'scenes_used':len(stack),
      'scene_ids':[m['id'] for m in metas],'scene_metadata':metas,'clear_pixel_pct':round(cov*100,2),
      'mean_ndvi_inside':round(float(np.mean(ndv)),4),'median_ndvi_inside':round(float(np.median(ndv)),4),
      'ndvi_p10_inside':round(float(np.percentile(ndv,10)),4),'ndvi_p90_inside':round(float(np.percentile(ndv,90)),4),
      'canopy_ndvi_median':finite_median(ndvi[vegetation]),'ndre_median':finite_median(ndre[vegetation]),
      'evi_median':finite_median(evi[vegetation]),'mfi_median':finite_median(mfi[mfi_signal],5),
      'mfi_positive_pct':round(pct(mfi_signal),1),'mfi_only_signal_pct':round(pct(mfi_only),1),
      'submerged_mangrove_signal_pct':round(pct(submerged),1),'mndwi_median':round(float(np.median(mw)),4),
      'vegetation_coverage_proxy_pct':round(pct(vegetation),1),'open_water_pct':round(pct(water),1),
      'open_nonvegetated_pct':round(pct(nonveg),1),'proxy_area_rai':round(float(plot['area_rai'])*pct(vegetation)/100,2),
      'open_water_area_rai':round(float(plot['area_rai'])*pct(water)/100,2),'ingest_provenance':'user Drive source TIFF; exact month; registry scope'
    }
    out=R/'data/plots'/str(pid);out.mkdir(parents=True,exist_ok=True)
    rgb8=np.moveaxis(np.nan_to_num(np.clip(rgb/base.RGB_REFLECTANCE_MAX*255,0,255),nan=0).astype(np.uint8),0,-1)
    base.save_rgba(out/f'rgb_{mo}.png',rgb8,valid_rgb)
    base.save_rgba(out/f'ndvi_{mo}.png',base.palette_ndvi(np.nan_to_num(ndvi,nan=-.1)),valid)
    return result,'ACCEPTED'

report=[];accepted=0
for (pid,mo),ss in sorted(scenes.items()):
    usable,old=existing_usable(pid,mo)
    if usable:continue
    complete={s for s,bs in ss.items() if set(BANDS)<=bs}
    if not complete:continue
    scope=source_scope(pid,mo,sorted(complete)[0])
    if scope!='REGISTRY_CONTAINED':
        report.append({'plot_id':pid,'code':dcode(byid[pid]),'month':mo,'scope':scope,'result':'SKIP_SCOPE','scenes':sorted(complete)});continue
    result,status=process(pid,mo,complete)
    rec={'plot_id':pid,'code':dcode(byid[pid]),'month':mo,'scope':scope,'result':status,'scenes':sorted(complete)}
    if result:
        target=series_by[pid]
        ts=target.get('timeseries',[])
        idx=next((i for i,x in enumerate(ts) if x.get('month')==mo),None)
        if idx is None: raise RuntimeError(f'missing timeseries slot {pid} {mo}')
        # fail closed: re-check immediately before writing.
        if ts[idx].get('status') in {'observed_single_scene','observed_monthly_composite'} and float(ts[idx].get('clear_pixel_pct') or 0)>=5:
            rec['result']='SKIP_BECAME_USABLE'
        else:
            ts[idx]=result;accepted+=1
            mp=R/'data/plots'/str(pid)/'metadata.json'
            md=json.loads(mp.read_text(encoding='utf-8'))
            dates=md.get('dates',[]);mi=next((i for i,x in enumerate(dates) if x.get('month')==mo),None)
            if mi is None:raise RuntimeError(f'missing metadata slot {pid} {mo}')
            dates[mi]=result
            md.setdefault('ingest_notes',[]).append({'month':mo,'source':'user Drive Sentinel-2 L2A TIFF','rule':'missing registry observation only; exact month; no substitution'})
            mp.write_text(json.dumps(md,ensure_ascii=False,indent=2),encoding='utf-8')
    report.append(rec)

TS.write_text(json.dumps(series,ensure_ascii=False,indent=2),encoding='utf-8')
counts=Counter(x['result'] for x in report)
out={'accepted':accepted,'counts':dict(counts),'records':report}
(OUT/'drive_missing_ingest.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'accepted':accepted,'counts':dict(counts)},ensure_ascii=False,indent=2))
if accepted==0:
    print('No new usable registry observations accepted.')
