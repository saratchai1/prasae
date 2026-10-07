#!/usr/bin/env python3
"""Enforce one registry identity and a contained optional scope for each PDD plot."""
import json
import re
from pathlib import Path
from collections import defaultdict
from shapely.geometry import shape

R = Path(__file__).resolve().parents[1]
catalog = json.loads((R / 'data/plots_catalog.json').read_text())
pdd = json.loads((R / 'data/pdd22/plots_catalog.json').read_text())
assert len(catalog) == 210 and len({int(p['id']) for p in catalog}) == 210
assert len(pdd) == 22 and len({p['code'] for p in pdd}) == 22
bycode = defaultdict(list)
for plot in catalog:
    m = re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])', plot.get('name', ''), re.I)
    if m:
        bycode[f'{int(m[1])}-{m[2].upper()}'].append(plot)
duplicates = {k: [p['id'] for p in xs] for k, xs in bycode.items() if len(xs) > 1}
assert not duplicates
rows = []
for plot in pdd:
    matches = bycode[plot['code']]
    assert len(matches) == 1, f'ambiguous PDD identity: {plot["code"]}'
    registry = matches[0]
    assert registry['province'] == plot['province']
    pg = shape(plot['geometry'])
    overlap = shape(registry['geometry']).intersection(pg).area / pg.area
    assert overlap >= .999, f'PDD exceeds registry boundary: {plot["code"]}'
    rows.append({'code': plot['code'], 'candidates': [{'id': registry['id'], 'area': registry['area_rai'],
                                                     'province': registry['province'], 'overlap_fraction': round(overlap, 5)}]})
print(json.dumps({'general_count': 210, 'pdd_count': 22, 'mapping': rows, 'duplicates': duplicates,
                  'registry_identities': 210, 'duplicate_registry_ids': 0,
                  'pdd_scope_not_extra_plots': 'PASS'}, ensure_ascii=False, indent=2))
