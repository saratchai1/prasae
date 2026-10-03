#!/usr/bin/env python3
import json,re,zipfile,math,os
from pathlib import Path
from collections import defaultdict,Counter
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from shapely.geometry import shape, box

R=Path(__file__).resolve().parents[1]
IN=R/'incoming'
TMP=R/'incoming_extracted'
TMP.mkdir(exist_ok=True)
BANDS=['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12','SCL']
months=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08']
code_re=re.compile(r'^(\d{1,3})-(STC|VSD|EVR)$',re.I)
plot_re=re.compile(r'^PLOT_(\d{1,3})$',re.I)
scene_re=re.compile(r'^S2[ABC]_MSIL2A_',re.I)
catalog=json.loads((R/'data/plots_catalog.json').read_text(encoding='utf-8'))
pdd=json.loads((R/'data/pdd22/plots_catalog.json').read_text(encoding='utf-8'))
by_id={int(p['id']):p for p in catalog}
def display_code(p):
    m=re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])',p.get('name',''),re.I)
    return f"{int(m.group(1))}-{m.group(2).upper()}" if m else p['code']
by_code=defaultdict(list)
for p in catalog:by_code[display_code(p)].append(p)
pdd_by={p['code']:p for p in pdd}

groups=defaultdict(lambda:defaultdict(dict))
archives=[]
for zp in sorted(IN.rglob('*.zip')):
  with zipfile.ZipFile(zp) as z:
    bad=z.testzip()
    if bad: raise RuntimeError(f'{zp.name}: corrupt {bad}')
    n=0
    for inf in z.infolist():
      name=inf.filename.replace('\\','/')
      if inf.is_dir() or name.startswith('__MACOSX/') or '/._' in name or name.startswith('._'): continue
      parts=[x for x in name.split('/') if x]
      if len(parts)<4 or not parts[-1].lower().endswith('.tif'): continue
      ident,month,scene,filename=parts[-4],parts[-3],parts[-2],parts[-1]
      if month not in months or not scene_re.match(scene): continue
      band=Path(filename).stem.upper()
      if band not in BANDS: continue
      pm=plot_re.match(ident);cm=code_re.match(ident)
      if pm: pid=int(pm.group(1));code=display_code(by_id[pid]) if pid in by_id else None
      elif cm:
        code=f"{int(cm.group(1))}-{cm.group(2).upper()}"; candidates=by_code.get(code,[])
        pid=int(candidates[0]['id']) if len(candidates)==1 else None
      else: continue
      if pid is None or pid not in by_id: continue
      out=TMP/f'{pid}/{month}/{scene}/{band}.tif';out.parent.mkdir(parents=True,exist_ok=True)
      if not out.exists():
        with z.open(inf) as src, out.open('wb') as dst:
          while True:
            chunk=src.read(1024*1024)
            if not chunk:break
            dst.write(chunk)
      groups[(pid,month)][scene][band]=out
      n+=1
    archives.append({'zip':zp.name,'science_tifs':n})

complete=[];partial=[]
for key,scenes in groups.items():
  for scene,b in scenes.items():
    miss=[x for x in BANDS if x not in b]
    row={'plot_id':key[0],'code':display_code(by_id[key[0]]),'month':key[1],'scene':scene,'present':sorted(b),'missing':miss}
    (complete if not miss else partial).append(row)

# inspect representative and all complete scene spatial metadata
samples=[];errors=[];scope_counts=Counter();value_stats=[]
for row in complete:
  pid=row['plot_id'];month=row['month'];scene=row['scene'];b=groups[(pid,month)][scene]
  metas=[]
  for band in BANDS:
    p=b[band]
    with rasterio.open(p) as ds:
      bounds=transform_bounds(ds.crs,'EPSG:4326',*ds.bounds,densify_pts=21) if ds.crs else None
      arr=ds.read(1,masked=True)
      finite=np.asarray(arr.compressed(),dtype=float)
      meta={'band':band,'shape':[ds.height,ds.width],'crs':str(ds.crs),'dtype':str(ds.dtypes[0]),'bounds4326':bounds,'nodata':ds.nodata,'scale':list(ds.scales),'offset':list(ds.offsets)}
      if finite.size:
        meta['min']=float(np.nanmin(finite));meta['p50']=float(np.nanmedian(finite));meta['max']=float(np.nanmax(finite))
      metas.append(meta)
  # infer footprint relation using B02
  bb=metas[0]['bounds4326']
  scope='UNKNOWN'
  if bb:
    footprint=box(*bb); rg=shape(by_id[pid]['geometry'])
    registry_cover=rg.intersection(footprint).area/max(rg.area,1e-20)
    pg=shape(pdd_by[row['code']]['geometry']) if row['code'] in pdd_by else None
    pdd_cover=pg.intersection(footprint).area/max(pg.area,1e-20) if pg else None
    # infer only whether raster contains each boundary; source may be padded/cropped rectangle
    if pg is not None and pdd_cover>0.999 and registry_cover<0.999:scope='PDD_ONLY_FOOTPRINT'
    elif registry_cover>0.999:scope='REGISTRY_CONTAINED'
    else:scope='PARTIAL_REGISTRY'
    scope_counts[scope]+=1
  if len(samples)<20 or row['code'] in {'18-VSD','87-VSD','97-VSD'}:
    samples.append({**row,'scope':scope,'metadata':metas})
  if len(value_stats)<40:value_stats.append({'plot_id':pid,'code':row['code'],'month':month,'scene':scene,'B02':metas[0],'B08':next(x for x in metas if x['band']=='B08'),'SCL':next(x for x in metas if x['band']=='SCL')})

plot_months=set(groups)
out={
 'archives':archives,
 'science_tifs':sum(x['science_tifs'] for x in archives),
 'resolved_plot_months':len(plot_months),
 'complete_scenes':len(complete),
 'partial_scenes':len(partial),
 'unique_plots':len({p for p,m in plot_months}),
 'months':dict(Counter(m for p,m in plot_months)),
 'scope_counts':dict(scope_counts),
 'partial_examples':partial[:100],
 'samples':samples[:80],
 'value_stats':value_stats,
}
(R/'audit-artifacts').mkdir(exist_ok=True)
(R/'audit-artifacts'/'drive_tif_qa.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:out[k] for k in ['archives','science_tifs','resolved_plot_months','complete_scenes','partial_scenes','unique_plots','months','scope_counts']},ensure_ascii=False,indent=2))
print('\n=== REPRESENTATIVE METADATA ===')
for s in samples[:12]:
  m=s['metadata']
  print(json.dumps({'plot_id':s['plot_id'],'code':s['code'],'month':s['month'],'scene':s['scene'],'scope':s['scope'],'B02':m[0],'B08':next(x for x in m if x['band']=='B08'),'SCL':next(x for x in m if x['band']=='SCL')},ensure_ascii=False))
