#!/usr/bin/env python3
import json, math
from pathlib import Path
from statistics import median
from PIL import Image
import numpy as np

R=Path(__file__).resolve().parents[1]
plots=json.loads((R/'data/timeseries_verified_12.json').read_text(encoding='utf-8'))

def radiometry_family(o):
    provenance=o.get('source_provenance') or {}
    if provenance.get('version')=='native-multi-provider-local-v4-20261007':
        return 'NATIVE_MULTI_PROVIDER'
    return 'NATIVE_C1' if provenance.get('version')=='earth-search-c1-local-v4-20261005' else 'LEGACY'

def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

def rgb_screen(path):
    with Image.open(path) as im:
        a=np.asarray(im.convert('RGBA'),dtype=np.uint8)
    valid=a[...,3]>0
    if not valid.any():
        return {'valid_pixels':0,'cloud_like_pct':0.0,'haze_like_pct':0.0,'bright_pct':0.0}
    pix=a[...,:3][valid].astype(np.int16)
    mx=pix.max(axis=1);mn=pix.min(axis=1);mean=pix.mean(axis=1)
    cloud=((mx-mn)<=18)&(mean>=215)
    haze=((mx-mn)<=28)&(mean>=180)
    bright=mean>=215
    return {
      'valid_pixels':int(valid.sum()),
      'cloud_like_pct':round(float(cloud.mean()*100),3),
      'haze_like_pct':round(float(haze.mean()*100),3),
      'bright_pct':round(float(bright.mean()*100),3),
    }

def catalog_cloud(o):
    vals=[]
    for m in o.get('scene_metadata') or []:
        v=num(m.get('catalog_cloud_cover_pct'))
        if v is not None: vals.append(v)
    return max(vals) if vals else None

out={'version':'20261003-qa2','method':{
  'base_good':'observed status and clear_pixel_pct >= 95',
  'tide_water_review':'open_water_pct >= 60 and >=40 percentage points above median of other base-GOOD months for same plot',
  'atmosphere_review':'RGB residual cloud/haze heuristic plus scene catalog cloud context',
  'visual_review':'strong RGB residual heuristic without enough atmospheric context',
  'native_radiometry_review':'native C1 STAC scale/offset is validated, but cross-batch legacy harmonization is pending; real imagery remains available',
  'water_reference_scope':'same radiometric family only; native observations do not change legacy water references',
  'note':'Conservative screening gate. Review flags block portfolio delta; they are not proof of cloud or damage.'
},'observations':{},'summary':{}}
counts={}
for p in plots:
    pid=int(p['id']); series=p.get('timeseries') or []
    good_waters={family:[num(o.get('open_water_pct')) for o in series if radiometry_family(o)==family and o.get('status') in {'observed_single_scene','observed_monthly_composite'} and (num(o.get('clear_pixel_pct')) or 0)>=95 and num(o.get('open_water_pct')) is not None] for family in ('LEGACY','NATIVE_C1','NATIVE_MULTI_PROVIDER')}
    for o in series:
        month=o['month']; key=f'{pid}|{month}'
        coverage=num(o.get('clear_pixel_pct')) or 0
        observed=o.get('status') in {'observed_single_scene','observed_monthly_composite'}
        base_good=observed and coverage>=95
        rec={'status':'INSUFFICIENT','base_qa':'GOOD' if base_good else 'INSUFFICIENT','coverage_pct':coverage,'reason':'ข้อมูลไม่ผ่านเกณฑ์ coverage/observation สำหรับการเปรียบเทียบเต็มแปลง'}
        if base_good:
            path=R/'data/plots'/str(pid)/f'rgb_{month}.png'
            s=rgb_screen(path);water=num(o.get('open_water_pct'));cat=catalog_cloud(o)
            rec.update(s);rec['open_water_pct']=water;rec['catalog_cloud_cover_max_pct']=cat
            others=[x for x in good_waters[radiometry_family(o)] if water is None or x!=water]
            water_median=median(others) if others else None
            rec['other_good_month_water_median_pct']=None if water_median is None else round(float(water_median),2)
            tide=water is not None and water>=60 and water_median is not None and (water-water_median)>=40
            atmosphere=((s['cloud_like_pct']>=8 and s['haze_like_pct']>=12) or s['haze_like_pct']>=35) and (cat is not None and cat>=50)
            visual=(s['cloud_like_pct']>=8 or s['haze_like_pct']>=35)
            if tide:
                rec['status']='TIDE_WATER_REVIEW';rec['reason']='สัดส่วนน้ำสูงผิดปกติเมื่อเทียบกับเดือน GOOD อื่นของแปลงเดียวกัน ควรตรวจน้ำขึ้นลง/น้ำท่วมก่อนใช้ค่าเปลี่ยนแปลง'
            elif atmosphere:
                rec['status']='ATMOSPHERE_REVIEW';rec['reason']='ภาพมีสัญญาณ bright-neutral/haze เหลือหลัง SCL mask และ scene มี cloud context สูง ควรตรวจภาพก่อนใช้ค่าเปลี่ยนแปลง'
            elif visual:
                rec['status']='VISUAL_REVIEW';rec['reason']='ภาพมีสัญญาณสว่าง/เป็นกลางผิดปกติ ควรตรวจด้วยตาก่อนใช้ค่าเปลี่ยนแปลง'
            else:
                rec['status']='CLEAR';rec['reason']='ผ่าน coverage และ secondary visual screening สำหรับการคัดกรอง'
        if radiometry_family(o) in ('NATIVE_C1','NATIVE_MULTI_PROVIDER'):
            rec['radiometry_status']=radiometry_family(o)+'_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING'
            if rec['status']=='CLEAR':
                rec['visual_screening_status']='CLEAR'
                rec['status']='RADIOMETRY_REVIEW'
                rec['reason']='ภาพครบ แต่ยังไม่ยืนยันความสอดคล้องของค่าสะท้อนแสงระหว่างชุดข้อมูล จึงยังไม่สรุปการเปลี่ยนแปลง'
        out['observations'][key]=rec
        counts[rec['status']]=counts.get(rec['status'],0)+1
out['summary']=dict(sorted(counts.items()))
Path('audit-artifacts').mkdir(exist_ok=True)
(R/'audit-artifacts'/'all_plots_visual_qa.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'version':out['version'],'summary':out['summary'],'records':len(out['observations'])},ensure_ascii=False,indent=2))
