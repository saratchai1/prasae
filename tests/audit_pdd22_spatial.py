#!/usr/bin/env python3
import csv,json,math
from pathlib import Path
import numpy as np
from PIL import Image
from shapely.geometry import shape
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds

R=Path(__file__).resolve().parents[1]
catalog=json.loads((R/'data/pdd22/plots_catalog.json').read_text(encoding='utf-8'))
manifest=json.loads((R/'data/pdd22_satellite/manifest.json').read_text(encoding='utf-8'))
rows=list(csv.DictReader((R/'data/pdd22_satellite/coverage_report.csv').open(encoding='utf-8-sig')))
fcd=json.loads((R/'data/pdd22_v3/plots_result.json').read_text(encoding='utf-8'))
assert len(catalog)==22 and len(manifest['plots'])==22 and len(rows)==264 and len(fcd)==22
cat={p['code']:p for p in catalog};man={p['plot_code']:p for p in manifest['plots']};fcdm={p['code']:p for p in fcd}
errors=[];image_checks=0;fcd_checks=0

for code,p in cat.items():
  m=man[code]; geom=shape(p['geometry']); bbox=m['grid']['bbox']; w=m['grid']['width'];h=m['grid']['height']
  expected=[p['bounds'][0]-0.003,p['bounds'][1]-0.003,p['bounds'][2]+0.003,p['bounds'][3]+0.003]
  if any(abs(float(a)-float(b))>2e-7 for a,b in zip(bbox,expected)):errors.append([code,'manifest_bbox',bbox,expected])
  if abs(float(m['grid']['resolution_m'])-10)>0.5:errors.append([code,'resolution',m['grid']['resolution_m']])
  inside=geometry_mask([p['geometry']],out_shape=(h,w),transform=from_bounds(*bbox,w,h),invert=True,all_touched=False)
  if int(inside.sum())!=int(m['inside_pixel_count']):errors.append([code,'inside_count',int(inside.sum()),m['inside_pixel_count']])
  prows=[r for r in rows if r['plot_code']==code]
  assert len(prows)==12
  for r in prows:
    mo=r['month'];rgb=R/'data/pdd22_satellite/plots'/code/mo/'rgb.png';ndvi=R/'data/pdd22_satellite/plots'/code/mo/'ndvi.png';vm=R/'data/pdd22_satellite/plots'/code/mo/'valid_mask.png'
    imgs={}
    for kind,path in [('rgb',rgb),('ndvi',ndvi),('valid_mask',vm)]:
      with Image.open(path) as im:
        if im.size!=(w,h):errors.append([code,mo,kind,'size',im.size,(w,h)])
        a=np.asarray(im.convert('RGBA'))
        imgs[kind]=a;image_checks+=1
        alpha=a[...,3]>0
        if np.any(alpha & ~inside):errors.append([code,mo,kind,'alpha_outside',int((alpha&~inside).sum())])
    rgb_alpha=imgs['rgb'][...,3]>0;ndvi_alpha=imgs['ndvi'][...,3]>0
    if not np.array_equal(rgb_alpha,ndvi_alpha):errors.append([code,mo,'rgb_ndvi_alpha_diff',int(np.count_nonzero(rgb_alpha^ndvi_alpha))])
    valid_value=imgs['valid_mask'][...,0]>0
    if not np.array_equal(rgb_alpha,valid_value):errors.append([code,mo,'image_valid_mask_diff',int(np.count_nonzero(rgb_alpha^valid_value))])
    coverage=round(float(rgb_alpha.sum())/max(1,int(inside.sum()))*100,2)
    if abs(coverage-float(r['coverage_pct']))>0.011:errors.append([code,mo,'coverage',coverage,r['coverage_pct']])
    if r['qa']=='NO_DATA' and rgb_alpha.sum() and coverage>=5:errors.append([code,mo,'no_data_has_valid_pixels',coverage])
  fp=fcdm[code]
  if shape(fp['geometry']).equals_exact(geom,1e-10) is False:errors.append([code,'fcd_geometry_diff'])
  if abs(float(fp['area_rai'])-float(p['area_rai']))>0.01:errors.append([code,'fcd_area',fp['area_rai'],p['area_rai']])
  for o in fp.get('observations',[]):
    mo=o['month'];path=R/'data/pdd22_v3/maps'/code/f'fcd_{mo}.png'
    with Image.open(path) as im:
      if im.size!=(w,h):errors.append([code,mo,'fcd_size',im.size,(w,h)])
      a=np.asarray(im.convert('RGBA'));fcd_checks+=1
      alpha=a[...,3]>0
      if np.any(alpha & ~inside):errors.append([code,mo,'fcd_alpha_outside',int((alpha&~inside).sum())])
      if not np.array_equal(alpha,inside):errors.append([code,mo,'fcd_inside_coverage_diff',int(np.count_nonzero(alpha^inside))])
    vals=[float(o.get(k,0) or 0) for k in ['green_rai','yellow_rai','red_rai','water_rai','unknown_rai']]
    if abs(sum(vals)-float(p['area_rai']))>0.08:errors.append([code,mo,'fcd_area_sum',sum(vals),p['area_rai'],vals])

# Static compare contract: both sides must use the same georeferenced bounds.
src=(R/'pdd22-compare-swipe.js').read_text(encoding='utf-8')
if 'beforeUrl:a.url' not in src or 'afterUrl:b.url' not in src or 'bounds:imageBoundsForPlot(activePlot)' not in src:errors.append(['compare','snapshot_contract_missing'])
if 'M.loadLeafletFrame(L,map,{url:s.beforeUrl,bounds:s.bounds}' not in src or 'M.loadLeafletFrame(L,map,{url:s.afterUrl,bounds:s.bounds}' not in src:errors.append(['compare','same_bounds_not_used'])

assert not errors,errors[:30]
print(json.dumps({'result':'PASS','plots':22,'satellite_observations':264,'satellite_images_checked':image_checks,'fcd_maps_checked':fcd_checks,'spatial_errors':0,'compare_same_bounds':True,'total_pdd_area_rai':round(sum(float(p['area_rai']) for p in catalog),2)},ensure_ascii=False,indent=2))
