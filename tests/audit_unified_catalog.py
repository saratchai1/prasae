import json,re
from pathlib import Path
from collections import defaultdict
from shapely.geometry import shape
R=Path(__file__).resolve().parents[1]
c=json.loads((R/'data/plots_catalog.json').read_text())
p=json.loads((R/'data/pdd22/plots_catalog.json').read_text())
b=defaultdict(list)
for x in c:
 m=re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])',x.get('name',''),re.I)
 if m:b[str(int(m[1]))+'-'+m[2].upper()].append(x)
rows=[]
for x in p:
 candidates=b[x['code']]
 rows.append({'code':x['code'],'candidates':[{'id':v['id'],'area':v['area_rai'],'province':v.get('province'),'overlap_fraction':round(shape(v['geometry']).intersection(shape(x['geometry'])).area/shape(x['geometry']).area,5)} for v in candidates]})
print(json.dumps({'general_count':len(c),'pdd_count':len(p),'mapping':rows,'duplicates':{k:[x['id'] for x in v] for k,v in b.items() if len(v)>1}},ensure_ascii=False,indent=2))
