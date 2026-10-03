#!/usr/bin/env python3
import json, re, os
from pathlib import Path
from collections import Counter, defaultdict

ROOT=Path(__file__).resolve().parents[1]
catalog=json.loads((ROOT/'data/plots_catalog.json').read_text(encoding='utf-8'))
verified=json.loads((ROOT/'data/timeseries_verified_12.json').read_text(encoding='utf-8'))
pdd=json.loads((ROOT/'data/pdd22/plots_catalog.json').read_text(encoding='utf-8'))
assert len(catalog)>=200
assert len(verified)>=200
assert len(pdd)==22

def business_code(name):
    m=re.search(r'(?<!\\d)(\\d{1,3})\\s*-\\s*(STC|VSD|EVR)(?![A-Za-z])', name or '', re.I)
    return f"{int(m.group(1))}-{m.group(2).upper()}" if m else None

cat_by_id={int(x['id']):x for x in catalog}
ver_by_id={int(x['id']):x for x in verified}
assert set(ver_by_id).issubset(set(cat_by_id))
months=['2023-09','2023-12','2024-03','2024-06','2024-09','2024-12','2025-03','2025-06','2025-09','2025-12','2026-03','2026-08']

province=Counter(x.get('province') or 'ไม่ระบุ' for x in catalog)
codes=defaultdict(list)
for x in catalog:
    bc=business_code(x.get('name'))
    if bc: codes[bc].append(x)

pdd_codes={x['code'] for x in pdd}
pdd_matches={c:codes.get(c,[]) for c in sorted(pdd_codes)}
missing_pdd=[c for c,v in pdd_matches.items() if not v]
duplicate_business={c:[x['id'] for x in v] for c,v in codes.items() if len(v)>1}

status=Counter()
image_missing=[]
month_counts=Counter()
complete_plots=0
observed_plots=0
for item in verified:
    ts=item.get('timeseries') or []
    assert [x.get('month') for x in ts]==months, item['id']
    observed=0
    all_assets=True
    for d in ts:
        s=d.get('status')
        status[s]+=1
        if s in {'observed_single_scene','observed_monthly_composite'}:
            observed+=1; month_counts[d['month']]+=1
            plot_dir=ROOT/'data/plots'/str(item['id'])
            for kind in ['rgb','ndvi']:
                p=plot_dir/f"{kind}_{d['month']}.png"
                if not p.exists():
                    image_missing.append(str(p.relative_to(ROOT)))
                    all_assets=False
    if observed: observed_plots+=1
    if observed==12 and all_assets: complete_plots+=1

area=sum(float(x.get('area_rai') or 0) for x in catalog)
out={
 'catalog_plots':len(catalog),
 'verified_plots':len(verified),
 'catalog_area_rai':round(area,2),
 'province_count':len(province),
 'provinces':dict(sorted(province.items())),
 'verified_observation_status':dict(status),
 'observed_plots':observed_plots,
 'complete_12_month_plots':complete_plots,
 'observed_plot_counts_by_month':dict(month_counts),
 'missing_expected_images':image_missing[:100],
 'missing_expected_image_count':len(image_missing),
 'pdd22_codes_in_generic_catalog':{c:[{'id':x['id'],'name':x.get('name'),'province':x.get('province'),'area_rai':x.get('area_rai')} for x in v] for c,v in pdd_matches.items()},
 'pdd22_missing_from_generic_catalog':missing_pdd,
 'duplicate_business_code_count':len(duplicate_business),
 'duplicate_business_codes':dict(list(sorted(duplicate_business.items()))[:100]),
}
print(json.dumps(out,ensure_ascii=False,indent=2))
