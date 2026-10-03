#!/usr/bin/env python3
import json, math
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image
from shapely.geometry import shape
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds

R=Path(__file__).resolve().parents[1]
catalog=json.loads((R/'data/plots_catalog.json').read_text(encoding='utf-8'))
geojson=json.loads((R/'data/plots.geojson').read_text(encoding='utf-8'))
verified=json.loads((R/'data/timeseries_verified_12.json').read_text(encoding='utf-8'))
cal=json.loads((R/'data/calibration/green_proxy_calibration.json').read_text(encoding='utf-8'))
assert len(catalog)==len(verified)==len(geojson['features'])==210
byid={int(p['id']):p for p in verified}
features={int(f['properties']['id']):f for f in geojson['features']}
months=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08']
spatial_errors=[];metric_errors=[];stale_assets=[];image_checks=0;observed=0;nonobserved=0
coverage_bins=Counter();thresholds=Counter();plot_pair_rows=[]

def close(a,b,tol=1e-7): return abs(float(a)-float(b))<=tol
def n(v): return float(v) if isinstance(v,(int,float)) and math.isfinite(float(v)) else None
for p in catalog:
    pid=int(p['id']); v=byid[pid]; f=features[pid]; geom=shape(p['geometry']); fg=shape(f['geometry'])
    if geom.is_empty or not geom.is_valid: spatial_errors.append([pid,'invalid_geometry'])
    if not geom.equals_exact(fg,1e-10): spatial_errors.append([pid,'geojson_geometry_diff'])
    gb=list(geom.bounds); cb=list(p['bounds'])
    if any(not close(a,b,1e-7) for a,b in zip(gb,cb)): spatial_errors.append([pid,'catalog_bounds_diff',gb,cb])
    meta_path=R/'data/plots'/str(pid)/'metadata.json'
    if not meta_path.is_file(): spatial_errors.append([pid,'metadata_missing']); continue
    meta=json.loads(meta_path.read_text(encoding='utf-8'))
    grid=meta['grid']; bbox=list(grid['bbox']); expected=[cb[0]-0.003,cb[1]-0.003,cb[2]+0.003,cb[3]+0.003]
    if any(not close(a,b,2e-7) for a,b in zip(bbox,expected)): spatial_errors.append([pid,'grid_bbox_vs_viewer_bounds',bbox,expected])
    w,h=int(grid['width']),int(grid['height'])
    if not(96<=w<=512 and 96<=h<=512): spatial_errors.append([pid,'grid_dimension_out_of_contract',w,h])
    transform=from_bounds(*bbox,w,h)
    inside=geometry_mask([p['geometry']],out_shape=(h,w),transform=transform,invert=True,all_touched=False)
    if not inside.any(): spatial_errors.append([pid,'zero_inside_pixels'])
    if meta.get('plot_id')!=pid: spatial_errors.append([pid,'metadata_plot_id_mismatch',meta.get('plot_id')])
    series=v.get('timeseries') or []
    if [o.get('month') for o in series]!=months: metric_errors.append([pid,'month_contract'])
    plot_threshold=n(v.get('green_proxy_threshold'))
    thresholds[plot_threshold]+=1
    expected_threshold=float(cal['selected_threshold']) if pid==76 and cal.get('status')=='PROMOTED_DRONE_CALIBRATED' else 0.25
    if plot_threshold is None or abs(plot_threshold-expected_threshold)>1e-9: metric_errors.append([pid,'plot_threshold',plot_threshold,expected_threshold])
    for o in series:
        month=o['month']; status=o.get('status'); coverage=n(o.get('clear_pixel_pct'))
        isobs=status in {'observed_single_scene','observed_monthly_composite'}
        rgb=R/'data/plots'/str(pid)/f'rgb_{month}.png'; ndvi=R/'data/plots'/str(pid)/f'ndvi_{month}.png'
        if isobs:
            observed+=1
            if coverage is None or coverage<5 or coverage>100: metric_errors.append([pid,month,'bad_observed_coverage',coverage])
            if coverage>=95: coverage_bins['GOOD>=95']+=1
            elif coverage>=50: coverage_bins['PARTIAL50-95']+=1
            else: coverage_bins['LOW5-50']+=1
            vals=[n(o.get('vegetation_coverage_proxy_pct')),n(o.get('open_water_pct')),n(o.get('open_nonvegetated_pct'))]
            if any(x is None or x<0 or x>100 for x in vals): metric_errors.append([pid,month,'bad_class_pct',vals])
            elif abs(sum(vals)-100)>0.31: metric_errors.append([pid,month,'class_sum',sum(vals),vals])
            nd=n(o.get('mean_ndvi_inside'))
            if nd is None or not -1<=nd<=1: metric_errors.append([pid,month,'ndvi_range',nd])
            th=n(o.get('green_proxy_threshold'))
            if th is None or abs(th-expected_threshold)>1e-9: metric_errors.append([pid,month,'obs_threshold',th,expected_threshold])
            green_area=n(o.get('proxy_area_rai')); exp_area=round(float(p['area_rai'])*vals[0]/100,2) if vals[0] is not None else None
            if green_area is None or abs(green_area-exp_area)>0.011: metric_errors.append([pid,month,'proxy_area_mismatch',green_area,exp_area])
            for path,kind in [(rgb,'rgb'),(ndvi,'ndvi')]:
                if not path.is_file(): spatial_errors.append([pid,month,kind,'missing']); continue
                with Image.open(path) as im:
                    image_checks+=1
                    if im.size!=(w,h): spatial_errors.append([pid,month,kind,'size',im.size,(w,h)])
                    if im.mode!='RGBA': spatial_errors.append([pid,month,kind,'mode',im.mode])
                    alpha=np.asarray(im.getchannel('A'))>0
                    if np.any(alpha & ~inside): spatial_errors.append([pid,month,kind,'alpha_outside_geometry',int((alpha&~inside).sum())])
                    if not alpha.any(): spatial_errors.append([pid,month,kind,'empty_alpha'])
                    if kind=='ndvi' and coverage is not None:
                        alpha_pct=alpha.sum()/inside.sum()*100
                        if abs(alpha_pct-coverage)>0.08: spatial_errors.append([pid,month,'ndvi_alpha_coverage_mismatch',round(alpha_pct,3),coverage])
        else:
            nonobserved+=1
            if rgb.exists() or ndvi.exists(): stale_assets.append([pid,month,status,rgb.exists(),ndvi.exists()])
            for key in ['mean_ndvi_inside','vegetation_coverage_proxy_pct','proxy_area_rai','open_water_pct','open_nonvegetated_pct']:
                if o.get(key) is not None: metric_errors.append([pid,month,'nonobserved_metric_not_null',key,o.get(key)])
    a=next(x for x in series if x['month']=='2024-03'); b=next(x for x in series if x['month']=='2026-03')
    if (n(a.get('clear_pixel_pct')) or 0)>=95 and (n(b.get('clear_pixel_pct')) or 0)>=95 and all(x.get('status') in {'observed_single_scene','observed_monthly_composite'} for x in (a,b)):
        ga=n(a.get('proxy_area_rai')); gb=n(b.get('proxy_area_rai')); na=n(a.get('mean_ndvi_inside')); nb=n(b.get('mean_ndvi_inside'))
        if ga is not None and gb is not None:
            plot_pair_rows.append({'id':pid,'code':p['code'],'name':p.get('name'),'province':p.get('province'),'area_rai':p['area_rai'],'delta_green_rai':round(gb-ga,2),'delta_green_pctpt':round(n(b.get('vegetation_coverage_proxy_pct'))-n(a.get('vegetation_coverage_proxy_pct')),1),'delta_ndvi':round(nb-na,4) if na is not None and nb is not None else None})

assert not spatial_errors, spatial_errors[:20]
assert not metric_errors, metric_errors[:20]
assert not stale_assets, stale_assets[:20]
plot_pair_rows.sort(key=lambda x:abs(x['delta_green_pctpt']),reverse=True)
out={'result':'PASS','plots':210,'observed_entries':observed,'nonobserved_entries':nonobserved,'image_files_spatially_checked':image_checks,'spatial_errors':0,'metric_errors':0,'stale_nonobserved_assets':0,'qa_coverage_bins':dict(coverage_bins),'threshold_counts':{str(k):v for k,v in thresholds.items()},'calibration_status':cal.get('status'),'calibrated_threshold':cal.get('selected_threshold'),'march_2024_to_2026_good_pairs':len(plot_pair_rows),'largest_abs_green_pct_changes':plot_pair_rows[:20]}
print(json.dumps(out,ensure_ascii=False,indent=2))
