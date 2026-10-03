#!/usr/bin/env python3
import csv,json,re
from collections import Counter,defaultdict
from pathlib import Path
R=Path(__file__).resolve().parents[1]; A=R/"audit-artifacts"
REQ={"B02","B03","B04","B05","B06","B07","B08","B8A","B11","B12","SCL"}
rx=re.compile(r"(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)",re.I)
def code(x):
 m=rx.search(x or ""); return f"{int(m[1])}-{m[2].upper()}" if m else None
reg=json.loads((R/"data/plots_catalog.json").read_text())
pdd=json.loads((R/"data/pdd22/plots_catalog.json").read_text())
byid={int(x["id"]):x for x in reg}; bycode=defaultdict(list)
for x in reg:
 c=code(x.get("name")) or code(x.get("code"))
 if c: bycode[c].append(x)
pddby={x["code"]:x for x in pdd}
map22={c:int(bycode[c][0]["id"]) for c in pddby if len(bycode[c])==1}
g={}
with (A/"drive_batch_entries.csv").open(encoding="utf-8-sig") as f:
 for x in csv.DictReader(f):
  rid=int(x["plot_id"]) if x["plot_id"] else None
  if rid not in byid:
   cand=bycode.get(x["code"] or "",[]); rid=int(cand[0]["id"]) if len(cand)==1 else None
  m=x["month"]
  if rid is None or not m: continue
  z=g.setdefault((rid,m),{"bands":set(),"scenes":set(),"files":0})
  if x["band"]: z["bands"].add(x["band"])
  if x["scene_id"]: z["scenes"].add(x["scene_id"])
  z["files"]+=1
actions=Counter(); plan=[]
for (rid,m),z in sorted(g.items()):
 rp=byid[rid]; c=code(rp.get("name")); action="INGEST_REGISTRY"
 if c in pddby and map22.get(c)==rid:
  pp=pddby[c]; ar=float(rp.get("area_rai") or 0); ap=float(pp.get("area_rai") or 0)
  scope=abs(ar-ap)/max(ar,ap,1)<=.01 and all(abs(float(a)-float(b))<=1e-5 for a,b in zip(rp.get("bounds",[]),pp.get("bounds",[])))
  mp=R/"data/pdd22_satellite/plots"/c/"metadata.json"; sp=R/"data/pdd22_spectral/plots"/c/"spectral_manifest.json"
  md=json.loads(mp.read_text()) if mp.exists() else {}; sd=json.loads(sp.read_text()) if sp.exists() else {}
  obs=next((o for o in md.get("observations",[]) if o.get("month")==m),{})
  spec=next((o for o in sd.get("dates",[]) if o.get("month")==m),{})
  old=set(obs.get("selected_scene_ids") or []); oldbands=set((spec.get("files") or {}).keys())
  if scope and z["scenes"] and z["scenes"].issubset(old) and REQ.issubset(oldbands): action="DEDUP_REUSE_PDD22"
  elif not old or int(obs.get("valid_pixel_count") or 0)<=0: action="INGEST_FILL_PDD22_MISSING_MONTH"
  elif not scope: action="INGEST_REGISTRY_SCOPE"
  elif z["scenes"] and not z["scenes"].issubset(old): action="INGEST_ADDITIONAL_SCENE"
  else: action="INGEST_ASSET_GAP"
 actions[action]+=1
 plan.append({"plot_id":rid,"code":c,"month":m,"action":action,"bands":"|".join(sorted(z["bands"])),"scene_count":len(z["scenes"]),"files":z["files"]})
summary={"plot_month_groups":len(plan),"complete_11_band_groups":sum(REQ.issubset(set(x["bands"].split("|"))) for x in plan),"actions":dict(actions),"dedupe_policy":"scope+month+scene+assets; PDD subset never replaces registry"}
(A/"drive_batch_reconciliation.json").write_text(json.dumps({"summary":summary,"plan":plan},ensure_ascii=False,indent=2))
with (A/"drive_batch_reconciliation.csv").open("w",encoding="utf-8-sig",newline="") as f:
 w=csv.DictWriter(f,fieldnames=plan[0].keys() if plan else ["plot_id","code","month","action","bands","scene_count","files"]);w.writeheader();w.writerows(plan)
print(json.dumps(summary,ensure_ascii=False,indent=2))
