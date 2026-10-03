#!/usr/bin/env python3
"""Inventory committed inputs only. Missing in git does NOT mean absent from STAC.
No source imagery, source metrics or production files are modified.
"""
import calendar
import collections
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'satellite-handoff'
MONTHS = ['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08']
BANDS = ['B02','B03','B04','B05','B06','B07','B08','B8A','B11','B12']
OBSERVED = {'observed_single_scene','observed_monthly_composite'}
REVIEW = {'ATMOSPHERE_REVIEW','TIDE_WATER_REVIEW','VISUAL_REVIEW'}
BASE = '19ba56139325e977967164d7a459dadb4cbc47bd'

def read(path, default=None):
    file = ROOT / path
    return json.loads(file.read_text(encoding='utf-8-sig')) if file.is_file() else default

def business_code(p):
    match = re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])', p.get('name',''), re.I)
    return f'{int(match[1])}-{match[2].upper()}' if match else p.get('code') or p.get('name') or str(p['id'])

def scenes(o):
    ids = list(o.get('selected_scene_ids') or o.get('scene_ids') or [])
    for scene in (o.get('selected_scenes') or o.get('scene_metadata') or []):
        if isinstance(scene, dict) and (scene.get('id') or scene.get('scene_id')):
            ids.append(scene.get('id') or scene.get('scene_id'))
    return sorted(set(str(i) for i in ids if i))

def make_record(scope, p, o, meta, spec, qa):
    pid = int(p['id']) if scope == 'registry' else None
    code = business_code(p) if scope == 'registry' else p['code']
    month = o['month']
    image_root = f'data/plots/{pid}' if scope == 'registry' else f'data/pdd22_satellite/plots/{code}/{month}'
    preview = {key: f'{image_root}/{key}_{month}.png' if scope == 'registry' else f'{image_root}/{key}.png' for key in ['rgb','ndvi']}
    preview_present = {key: (ROOT / path).is_file() for key, path in preview.items()}
    dates = {r['month']: r for r in spec.get('dates', [])}
    date = dates.get(month, {})
    spectral_root = f'data/plots/{pid}' if scope == 'registry' else f'data/pdd22_spectral/plots/{code}'
    present = []
    for band in BANDS:
        filename = date.get('files', {}).get(band)
        if filename and (ROOT / spectral_root / filename).is_file():
            present.append(band)
    coverage = o.get('clear_pixel_pct') if scope == 'registry' else o.get('coverage_pct')
    observed = o.get('status') in OBSERVED if scope == 'registry' else isinstance(coverage, (int,float)) and coverage >= 5
    categories = []
    if observed and not all(preview_present.values()):
        categories.append('EXPECTED_PREVIEW_FILE_MISSING')
    if not observed:
        categories.append('NO_USABLE_OBSERVATION_IN_COMMITTED_DATA')
    elif not isinstance(coverage, (int,float)) or coverage < 95:
        categories.append('PARTIAL_OR_LOW_COVERAGE')
    if qa.get('status') in REVIEW:
        categories.append('HEURISTIC_REVIEW_NOT_CONFIRMED_CLOUD')
    missing = [band for band in BANDS if band not in present]
    if missing:
        categories.append('TEN_BAND_BROWSER_PACKAGE_NOT_BUILT')
    grid = meta.get('grid') or {}
    if scope == 'registry' and isinstance(grid.get('bbox'), list):
        grid = {'crs':grid.get('crs','EPSG:4326'), **grid}
    year, mon = map(int, month.split('-'))
    scene_ids = scenes(o)
    for row in (meta.get('observations') or meta.get('timeseries') or []):
        if row.get('month') == month:
            scene_ids = sorted(set(scene_ids + scenes(row)))
    return {
        'request_id':f'{scope}:{pid if pid is not None else code}:{month}',
        'scope':scope,'registry_id':pid,'plot_code':code,'original_plot_name':p.get('name',code),
        'province':p.get('province') or 'ไม่ระบุ','source_area_rai':p.get('area_rai'),
        'month':month,'utc_interval':[f'{month}-01T00:00:00Z',f'{month}-{calendar.monthrange(year,mon)[1]:02d}T23:59:59Z'],
        'priority':1 if month in {'2024-03','2025-03','2026-03'} else 2 if month == '2026-08' else 3,
        'observed_in_source':observed,'source_status':o.get('status') or o.get('qa'),
        'source_coverage_pct':coverage,'secondary_qa':qa.get('status','NOT_APPLICABLE_OR_NOT_AUDITED'),
        'secondary_qa_reason':qa.get('reason'),
        'preview_paths':preview,'preview_file_present':preview_present,
        'browser_bands_present':present,'browser_bands_missing':missing,
        'known_selected_scene_ids':scene_ids,'existing_grid':grid,
        'geometry_id':f'{scope}:{pid if pid is not None else code}',
        'categories':categories,
        'required_source_product':'Sentinel-2 L2A / BOA reflectance, not display PNG',
        'required_source_bands':BANDS+['SCL'],
        'provider_search_status':'NOT_SEARCHED_IN_THIS_INVENTORY',
        'action':'Resolve known selected scene IDs first. Verify access/metadata, then retrieve native scientific bands and SCL. Search other acquisitions within the exact month only for missing/unusable observations or reviewed imagery. Report alternatives separately; never silently replace observations.'
    }

catalog = read('data/plots_catalog.json')
verified = read('data/timeseries_verified_12.json')
pdd = read('data/pdd22/plots_catalog.json')
qa = read('data/all_plots_visual_qa.json', {}).get('observations', {})
assert isinstance(catalog,list) and len(catalog)==210
assert isinstance(verified,list) and len(verified)==210
assert isinstance(pdd,list) and len(pdd)==22
byid = {int(p['id']):p for p in verified}
rows = []; features = []
for p in catalog:
    pid = int(p['id'])
    meta = read(f'data/plots/{pid}/metadata.json', {})
    spec = read(f'data/plots/{pid}/spectral_manifest.json', {})
    series = {o['month']:o for o in byid[pid].get('timeseries',[])}
    for month in MONTHS:
        o = series.get(month, {'month':month,'status':'not_processed'})
        rows.append(make_record('registry',p,o,meta,spec,qa.get(f'{pid}|{month}',{})))
    features.append({'type':'Feature','id':f'registry:{pid}','properties':{'scope':'registry','registry_id':pid,'plot_code':business_code(p),'province':p.get('province'),'source_area_rai':p.get('area_rai')},'geometry':p['geometry']})
for p in pdd:
    code = p['code']; meta = read(f'data/pdd22_satellite/plots/{code}/metadata.json', {})
    spec = read(f'data/pdd22_spectral/plots/{code}/spectral_manifest.json', {})
    series = {o['month']:o for o in meta.get('observations', [])}
    for month in MONTHS:
        o = series.get(month, {'month':month,'qa':'NO_DATA','coverage_pct':None})
        rows.append(make_record('pdd',p,o,meta,spec,{}))
    features.append({'type':'Feature','id':f'pdd:{code}','properties':{'scope':'pdd','plot_code':code,'province':p.get('province'),'source_area_rai':p.get('area_rai')},'geometry':p['geometry']})
rows.sort(key=lambda r:(r['priority'],r['month'],r['scope'],r['plot_code']))
assert len(rows)==2784 and len({r['request_id'] for r in rows})==2784
assert all(r['geometry_id'] in {f['id'] for f in features} for r in rows)
summary={'basis_commit':BASE,'inventory_execution_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
         'scope_note':'210 registry records; 22 PDD participating scopes overlap those registry records. These are NOT 232 unique plots.',
         'provider_search_performed':False,'counts':{}}
for scope in ['registry','pdd']:
    rr = [r for r in rows if r['scope']==scope]
    summary['counts'][scope] = {
        'plot_count':len({r['geometry_id'] for r in rr}),'plot_months':len(rr),
        'observed_in_source':sum(r['observed_in_source'] for r in rr),
        'category_counts':dict(collections.Counter(c for r in rr for c in r['categories'])),
        'full_ten_band_browser_packages':sum(not r['browser_bands_missing'] for r in rr),
        'plot_months_with_any_browser_band':sum(bool(r['browser_bands_present']) for r in rr),
        'source_scene_ids_available':sum(bool(r['known_selected_scene_ids']) for r in rr)
    }
known_ids=sorted({s for r in rows for s in r['known_selected_scene_ids']})
summary['unique_known_scene_ids']=len(known_ids)
OUT.mkdir(exist_ok=True)
(OUT/'inventory-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'plot-month-inventory.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'boundaries.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},ensure_ascii=False),encoding='utf-8')
(OUT/'known-scene-ids.txt').write_text('\n'.join(known_ids)+'\n',encoding='utf-8')
# Focused queues; names describe repository state, not external satellite availability.
for name,category in [('unusable-periods','NO_USABLE_OBSERVATION_IN_COMMITTED_DATA'),('low-coverage','PARTIAL_OR_LOW_COVERAGE'),('review-candidates','HEURISTIC_REVIEW_NOT_CONFIRMED_CLOUD'),('multiband-to-build','TEN_BAND_BROWSER_PACKAGE_NOT_BUILT')]:
    selected=[r for r in rows if category in r['categories']]
    (OUT/f'{name}.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2),encoding='utf-8')
readme=(ROOT/'docs/ANTIGRAVITY_IMAGERY_HANDOFF.md').read_text(encoding='utf-8')
(OUT/'README.md').write_text(readme,encoding='utf-8')
md=['# ผลตรวจรายการภาพและข้อมูลที่ต้องจัดหา','',f'อ้างอิงข้อมูลที่ commit `{BASE}`','',
    '**นี่เป็นการตรวจไฟล์ใน repository ไม่ใช่ผลค้นหาแค็ตตาล็อกดาวเทียม การไม่มีไฟล์ใน repo ไม่ได้แปลว่าไม่มีภาพในผู้ให้บริการ**','',
    '| รายการ | ทะเบียน 210 แปลง | ขอบเขตเข้าร่วม PDD 22 แปลง |','|---|---:|---:|']
for label,key in [('ช่วงแปลง–เดือนทั้งหมด','plot_months'),('ช่วงที่ source ระบุว่ามี observation','observed_in_source'),('ชุด browser 10 bands ครบ','full_ten_band_browser_packages'),('ช่วงที่มี scene ID ให้ค้นหาต่อ','source_scene_ids_available')]:
    md.append(f"| {label} | {summary['counts']['registry'][key]} | {summary['counts']['pdd'][key]} |")
for label,key in [('ไม่มี observation ใช้งานได้ในข้อมูลที่ commit','NO_USABLE_OBSERVATION_IN_COMMITTED_DATA'),('coverage ต่ำกว่า 95%','PARTIAL_OR_LOW_COVERAGE'),('ควรตรวจภาพจาก heuristic (ไม่ใช่ยืนยันเมฆ)','HEURISTIC_REVIEW_NOT_CONFIRMED_CLOUD'),('ชุด browser 10 bands ยังไม่ครบ','TEN_BAND_BROWSER_PACKAGE_NOT_BUILT'),('source ระบุมีภาพแต่ไฟล์ preview หาย','EXPECTED_PREVIEW_FILE_MISSING')]:
    md.append(f"| {label} | {summary['counts']['registry']['category_counts'].get(key,0)} | {summary['counts']['pdd']['category_counts'].get(key,0)} |")
md += ['', 'หนึ่งช่วงอาจอยู่ได้หลายหมวด ห้ามบวกจำนวนหมวดเป็นจำนวนภาพรวม', '', '## ตัวอย่างสำหรับเริ่มงาน', '']
for code,month,scope in [('78-STC','2025-03','registry'),('18-VSD','2024-06','pdd'),('87-VSD','2025-09','registry'),('97-VSD','2025-06','registry')]:
    r=next((r for r in rows if r['plot_code']==code and r['month']==month and r['scope']==scope),None)
    if r:
        md += [f"### {code} · {r['province']} · {month} · {scope}", f"- source: {r['source_status']}; coverage: {r['source_coverage_pct']}%; secondary QA: {r['secondary_qa']}", f"- RGB/NDVI มีไฟล์: {r['preview_file_present']}", f"- browser bands ขาด: {', '.join(r['browser_bands_missing']) or 'ไม่ขาด'}", f"- scene IDs: {', '.join(r['known_selected_scene_ids']) or 'ไม่มีใน source'}", '']
(OUT/'SUMMARY_TH.md').write_text('\n'.join(md),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
print('\n'.join(md))
