#!/usr/bin/env python3
import json
from pathlib import Path
R=Path(__file__).resolve().parents[1];c=json.loads((R/'data/plots_catalog.json').read_text(encoding='utf-8'));v=json.loads((R/'data/timeseries_verified_12.json').read_text(encoding='utf-8'));assert len(c)==210 and len(v)==210;assert {int(x['id']) for x in c}=={int(x['id']) for x in v};months=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08'];missing=[];observed=0
for p in v:
 assert [x.get('month') for x in p.get('timeseries',[])]==months
 for o in p['timeseries']:
  if o.get('status') in {'observed_single_scene','observed_monthly_composite'}:
   observed+=1
   for layer in ['rgb','ndvi']:
    q=R/'data/plots'/str(p['id'])/f"{layer}_{o['month']}.png"
    if not q.is_file():missing.append(str(q))
assert not missing;provinces={}
for p in c:provinces[p.get('province') or 'ไม่ระบุ']=provinces.get(p.get('province') or 'ไม่ระบุ',0)+1
assert len(provinces)==17;print(json.dumps({'plots':210,'area_rai':round(sum(float(p['area_rai']) for p in c),2),'provinces':dict(sorted(provinces.items())),'observed_entries':observed,'images_checked':observed*2},ensure_ascii=False,indent=2))