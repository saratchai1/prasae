#!/usr/bin/env python3
import json,re,zipfile,tempfile,shutil
from pathlib import Path
from collections import defaultdict,Counter
import rasterio
from rasterio.warp import transform_bounds
from shapely.geometry import shape,box

R=Path(__file__).resolve().parents[1];IN=R/'incoming'
months=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08']
bands={'B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12','SCL'}
catalog=json.loads((R/'data/plots_catalog.json').read_text(encoding='utf-8'))
def dcode(p):
 m=re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])',p.get('name',''),re.I)
 return f"{int(m.group(1))}-{m.group(2).upper()}" if m else p['code']
def scene_key(scene):
 ps=scene.split('_')
 if len(ps)<6 or not ps[0].startswith('S2') or ps[1]!='MSIL2A': return scene
 orbit=next((x for x in ps[3:] if re.fullmatch(r'R\d{3}',x)),None)
 tile=next((x for x in ps[3:] if re.fullmatch(r'T\d{2}[A-Z]{3}',x)),None)
 return f'{ps[0]}_{ps[2]}_{orbit or "?"}_{tile or "?"}'
byid={int(p['id']):p for p in catalog};bycode=defaultdict(list)
for p in catalog:bycode[dcode(p)].append(p)
pdd={p['code']:p for p in json.loads((R/'data/pdd22/plots_catalog.json').read_text(encoding='utf-8'))}

archive=defaultdict(lambda:defaultdict(set));members={}
for zp in sorted(IN.rglob('*.zip')):
 with zipfile.ZipFile(zp) as z:
  bad=z.testzip()
  if bad: raise RuntimeError(f'{zp.name}: corrupt {bad}')
  for inf in z.infolist():
   n=inf.filename.replace('\\','/')
   if inf.is_dir() or n.startswith('__MACOSX/') or '/._' in n:continue
   ps=n.split('/')
   if len(ps)<4 or not ps[-1].lower().endswith('.tif'):continue
   ident,mo,scene,fn=ps[-4],ps[-3],ps[-2],ps[-1];band=Path(fn).stem.upper()
   if mo not in months or band not in bands or not scene.startswith(('S2A_','S2B_','S2C_')):continue
   if ident.upper().startswith('PLOT_'):
    try: pid=int(ident.split('_')[-1])
    except: continue
   else:
    m=re.match(r'^(\d{1,3})-(STC|VSD|EVR)$',ident,re.I)
    if not m:continue
    code=f"{int(m.group(1))}-{m.group(2).upper()}";cs=bycode.get(code,[])
    if len(cs)!=1:continue
    pid=int(cs[0]['id'])
   archive[(pid,mo)][scene].add(band)
   members[(pid,mo,scene,band)]=(zp,inf.filename)

rows=[];counts=Counter();actions=Counter();scope_counts=Counter();scope_exceptions=[]
for (pid,mo),scenes in sorted(archive.items()):
 complete={s for s,bs in scenes.items() if bands<=bs}
 meta=json.loads((R/'data/plots'/str(pid)/'metadata.json').read_text(encoding='utf-8'))
 o=next((x for x in meta.get('dates',[]) if x.get('month')==mo),{})
 selected=set(o.get('scene_ids') or [])
 selected_keys={scene_key(s) for s in selected}
 complete_by_key=defaultdict(list)
 for s in complete: complete_by_key[scene_key(s)].append(s)
 complete_keys=set(complete_by_key)
 usable=o.get('status') in {'observed_single_scene','observed_monthly_composite'} and float(o.get('clear_pixel_pct') or 0)>=5
 canonical_overlap=selected_keys & complete_keys
 canonical_exact=bool(selected_keys) and selected_keys<=complete_keys
 if usable and canonical_exact:cat='EXISTING_ACQUISITIONS_AVAILABLE'
 elif usable and canonical_overlap:cat='PARTIAL_EXISTING_ACQUISITIONS_AVAILABLE'
 elif usable and complete:cat='ALTERNATE_SCENE_ONLY'
 elif not usable and complete:cat='MISSING_OBSERVATION_HAS_CANDIDATE'
 else:cat='NO_COMPLETE_SOURCE'
 counts[cat]+=1
 row={'plot_id':pid,'code':dcode(byid[pid]),'month':mo,'repo_status':o.get('status'),'repo_coverage_pct':o.get('clear_pixel_pct'),'repo_selected':sorted(selected),'repo_selected_acquisitions':sorted(selected_keys),'archive_complete_scenes':sorted(complete),'archive_complete_acquisitions':sorted(complete_keys),'archive_scene_count':len(scenes),'category':cat}
 source_scope='UNKNOWN'
 if complete:
  scene=sorted(complete)[0];zp,name=members[(pid,mo,scene,'B02')]
  with zipfile.ZipFile(zp) as z, z.open(name) as src, tempfile.NamedTemporaryFile(suffix='.tif') as tf:
   shutil.copyfileobj(src,tf);tf.flush()
   with rasterio.open(tf.name) as ds: bb=transform_bounds(ds.crs,'EPSG:4326',*ds.bounds,densify_pts=21)
  footprint=box(*bb);rg=shape(byid[pid]['geometry']);rc=rg.intersection(footprint).area/max(rg.area,1e-20)
  pc=dcode(byid[pid]);pg=shape(pdd[pc]['geometry']) if pc in pdd else None;pcov=pg.intersection(footprint).area/max(pg.area,1e-20) if pg else None
  row['registry_coverage_by_source_bbox']=round(rc,6);row['pdd_coverage_by_source_bbox']=None if pcov is None else round(pcov,6);row['source_bbox']=bb
  if pg is not None and pcov>0.999 and rc<0.999: source_scope='PDD_ONLY_FOOTPRINT'
  elif rc>0.999: source_scope='REGISTRY_CONTAINED'
  else: source_scope='PARTIAL_REGISTRY'
 row['source_scope']=source_scope;scope_counts[source_scope]+=1
 if source_scope=='PDD_ONLY_FOOTPRINT':
  pmeta_path=R/'data/pdd22_satellite/plots'/row['code']/'metadata.json';po={}
  if pmeta_path.exists():
   pm=json.loads(pmeta_path.read_text(encoding='utf-8'));po=next((x for x in pm.get('observations',[]) if x.get('month')==mo),{})
  pselected=set(po.get('selected_scene_ids') or []);pkeys={scene_key(s) for s in pselected}
  row['pdd_repo_qa']=po.get('qa');row['pdd_repo_coverage_pct']=po.get('coverage_pct');row['pdd_repo_acquisitions']=sorted(pkeys)
  if pkeys and complete_keys<=pkeys: action='SKIP_PDD_DUPLICATE'
  elif po.get('qa')=='NO_DATA' or not pkeys: action='KEEP_PDD_GAP_FILL_CANDIDATE'
  else: action='KEEP_PDD_ALTERNATE_CANDIDATE'
  scope_exceptions.append(row)
 elif source_scope=='REGISTRY_CONTAINED':
  action='KEEP_REGISTRY_SOURCE'
 else:
  action='HOLD_PARTIAL_SCOPE_FOR_REVIEW'
 row['ingest_action']=action;actions[action]+=1
 rows.append(row)

out={'counts':dict(counts),'ingest_actions':dict(actions),'scope_counts':dict(scope_counts),'plot_months':len(rows),'scope_exception_count':len(scope_exceptions),'scope_exceptions':scope_exceptions,'rows':rows}
(R/'audit-artifacts').mkdir(exist_ok=True)
(R/'audit-artifacts'/'drive_scene_reconcile.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:out[k] for k in ['plot_months','counts','ingest_actions','scope_counts','scope_exception_count']},ensure_ascii=False,indent=2))
print('\n=== SCOPE EXCEPTIONS ===')
for r in scope_exceptions: print(json.dumps({k:r.get(k) for k in ['plot_id','code','month','category','source_scope','pdd_repo_qa','pdd_repo_coverage_pct','ingest_action']},ensure_ascii=False))
