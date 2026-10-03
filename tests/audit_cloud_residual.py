#!/usr/bin/env python3
import csv,json,math
from pathlib import Path
from PIL import Image
import numpy as np
R=Path(__file__).resolve().parents[1]

def score(path):
    with Image.open(path) as im:
        a=np.asarray(im.convert('RGBA'),dtype=np.uint8)
    rgb=a[...,:3].astype(np.int16); valid=a[...,3]>0
    if not valid.any(): return {'valid':0,'cloud_like_pct':0,'haze_like_pct':0,'bright_pct':0}
    pix=rgb[valid]; mx=pix.max(axis=1); mn=pix.min(axis=1); mean=pix.mean(axis=1)
    neutral=(mx-mn)<=18
    cloud_like=neutral & (mean>=215)
    haze_like=((mx-mn)<=28) & (mean>=180)
    bright=mean>=215
    return {'valid':int(valid.sum()),'cloud_like_pct':round(float(cloud_like.mean()*100),3),'haze_like_pct':round(float(haze_like.mean()*100),3),'bright_pct':round(float(bright.mean()*100),3)}

# General plots: only QA-equivalent GOOD images (coverage >=95 and observed).
v=json.loads((R/'data/timeseries_verified_12.json').read_text(encoding='utf-8'))
general=[]
for p in v:
  for o in p['timeseries']:
    if o.get('status') not in {'observed_single_scene','observed_monthly_composite'}: continue
    cov=o.get('clear_pixel_pct')
    if not isinstance(cov,(int,float)) or cov<95: continue
    path=R/'data/plots'/str(p['id'])/f"rgb_{o['month']}.png"
    s=score(path);general.append({**s,'dataset':'general','id':p['id'],'code':p['code'],'name':p.get('name'),'province':p.get('province'),'month':o['month'],'coverage_pct':cov,'path':str(path.relative_to(R)),'mean_ndvi':o.get('mean_ndvi_inside')})
# PDD22 GOOD images
rows=list(csv.DictReader((R/'data/pdd22_satellite/coverage_report.csv').open(encoding='utf-8-sig')))
pdd=[]
for o in rows:
  if o['qa']!='GOOD': continue
  path=R/'data/pdd22_satellite/plots'/o['plot_code']/o['month']/'rgb.png'
  s=score(path);pdd.append({**s,'dataset':'pdd22','code':o['plot_code'],'province':o['province'],'month':o['month'],'coverage_pct':float(o['coverage_pct']),'path':str(path.relative_to(R)),'mean_ndvi':float(o['mean_ndvi']) if o.get('mean_ndvi') else None})
for arr in (general,pdd): arr.sort(key=lambda x:(x['cloud_like_pct'],x['haze_like_pct']),reverse=True)
out={
 'general_good_images':len(general),
 'pdd22_good_images':len(pdd),
 'general_cloud_like_gt_1pct':sum(x['cloud_like_pct']>1 for x in general),
 'general_cloud_like_gt_3pct':sum(x['cloud_like_pct']>3 for x in general),
 'pdd22_cloud_like_gt_1pct':sum(x['cloud_like_pct']>1 for x in pdd),
 'pdd22_cloud_like_gt_3pct':sum(x['cloud_like_pct']>3 for x in pdd),
 'general_top20':general[:20],
 'pdd22_top20':pdd[:20],
 'note':'Secondary RGB brightness/neutrality heuristic only; flags candidates for visual review and is not itself a cloud classifier.'
}
print(json.dumps(out,ensure_ascii=False,indent=2))
