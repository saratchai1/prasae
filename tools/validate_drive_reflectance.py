#!/usr/bin/env python3
import json,re,zipfile,tempfile,shutil,math
from pathlib import Path
from collections import defaultdict
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import shape

R=Path(__file__).resolve().parents[1];IN=R/'incoming'
months=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08']
catalog=json.loads((R/'data/plots_catalog.json').read_text(encoding='utf-8'))
def dcode(p):
 m=re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])',p.get('name',''),re.I)
 return f"{int(m.group(1))}-{m.group(2).upper()}" if m else p['code']
byid={int(p['id']):p for p in catalog};bycode=defaultdict(list)
for p in catalog:bycode[dcode(p)].append(p)

members={}
for zp in sorted(IN.rglob('*.zip')):
 with zipfile.ZipFile(zp) as z:
  for inf in z.infolist():
   n=inf.filename.replace('\\','/')
   if inf.is_dir() or n.startswith('__MACOSX/') or '/._' in n or not n.lower().endswith('.tif'):continue
   ps=n.split('/')
   if len(ps)<4:continue
   ident,mo,scene,fn=ps[-4],ps[-3],ps[-2],ps[-1];band=Path(fn).stem.upper()
   if mo not in months or band not in {'B04','B08','SCL'}:continue
   if ident.upper().startswith('PLOT_'):
    try:pid=int(ident.split('_')[-1])
    except:continue
   else:
    m=re.match(r'^(\d{1,3})-(STC|VSD|EVR)$',ident,re.I)
    if not m:continue
    code=f"{int(m.group(1))}-{m.group(2).upper()}";cs=bycode.get(code,[])
    if len(cs)!=1:continue
    pid=int(cs[0]['id'])
   members[(pid,mo,scene,band)]=(zp,inf.filename)

def read(zp,name):
 with zipfile.ZipFile(zp) as z, z.open(name) as src, tempfile.NamedTemporaryFile(suffix='.tif') as tf:
  shutil.copyfileobj(src,tf);tf.flush()
  with rasterio.open(tf.name) as ds:return ds.read(1).astype(np.float32),ds.transform,ds.crs

def dilate(mask):
 p=np.pad(mask,1,constant_values=False);o=np.zeros_like(mask)
 for y in range(3):
  for x in range(3):o|=p[y:y+mask.shape[0],x:x+mask.shape[1]]
 return o

rows=[]
for pid,p in list(byid.items()):
 meta=json.loads((R/'data/plots'/str(pid)/'metadata.json').read_text(encoding='utf-8'))
 for o in meta.get('observations',[]):
  mo=o.get('month');target=o.get('stats',{}).get('mean_ndvi') if isinstance(o.get('stats'),dict) else o.get('mean_ndvi_inside')
  if target is None:target=o.get('mean_ndvi_inside')
  if target is None:continue
  selected=o.get('selected_scene_ids') or []
  available=[s for s in selected if all((pid,mo,s,b) in members for b in ['B04','B08','SCL'])]
  if not available:continue
  stacks0=[];stacks1=[];masks=[];transform=None
  for scene in available:
   b04,transform,crs=read(*members[(pid,mo,scene,'B04')]);b08,t2,c2=read(*members[(pid,mo,scene,'B08')]);scl,t3,c3=read(*members[(pid,mo,scene,'SCL')])
   if b04.shape!=b08.shape or b04.shape!=scl.shape:continue
   clear=np.isin(scl.astype(np.uint8),[4,5,6,7]) & ~dilate(np.isin(scl.astype(np.uint8),[1,2,3,8,9,10,11]))
   masks.append(clear)
   # model 0: DN/10000, model 1: (DN-1000)/10000
   for off,stack in [(0,stacks0),(-1000,stacks1)]:
    r=(b04+off)/10000.0;n=(b08+off)/10000.0
    nd=np.divide(n-r,n+r,out=np.full_like(n,np.nan),where=np.abs(n+r)>1e-6);nd[~clear]=np.nan;stack.append(nd)
  if not stacks0:continue
  inside=geometry_mask([p['geometry']],out_shape=stacks0[0].shape,transform=transform,invert=True,all_touched=False)
  vals=[]
  for stacks in [stacks0,stacks1]:
   with np.errstate(all='ignore'): comp=np.nanmedian(np.stack(stacks),axis=0)
   v=comp[inside & np.isfinite(comp)]
   vals.append(float(np.mean(v)) if v.size else None)
  if vals[0] is None or vals[1] is None:continue
  rows.append({'plot_id':pid,'code':dcode(p),'month':mo,'target':float(target),'selected_available':available,'ndvi_dn_div10000':round(vals[0],5),'ndvi_dn_minus1000':round(vals[1],5),'error_no_offset':round(abs(vals[0]-float(target)),5),'error_minus1000':round(abs(vals[1]-float(target)),5)})
  if len(rows)>=300:break
 if len(rows)>=300:break

def mae(k):
 a=[r[k] for r in rows];return sum(a)/len(a) if a else None
better0=sum(r['error_no_offset']<r['error_minus1000'] for r in rows);better1=sum(r['error_minus1000']<r['error_no_offset'] for r in rows)
out={'samples':len(rows),'mae_no_offset':mae('error_no_offset'),'mae_minus1000':mae('error_minus1000'),'better_no_offset':better0,'better_minus1000':better1,'rows':rows}
(R/'audit-artifacts').mkdir(exist_ok=True)
(R/'audit-artifacts'/'reflectance_offset_validation.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:out[k] for k in ['samples','mae_no_offset','mae_minus1000','better_no_offset','better_minus1000']},ensure_ascii=False,indent=2))
print('best examples',json.dumps(sorted(rows,key=lambda r:min(r['error_no_offset'],r['error_minus1000']))[:10],ensure_ascii=False))
print('worst examples',json.dumps(sorted(rows,key=lambda r:min(r['error_no_offset'],r['error_minus1000']),reverse=True)[:15],ensure_ascii=False))
