#!/usr/bin/env python3
import csv, io, json, re, zipfile
from pathlib import Path
from collections import Counter, defaultdict

ROOT=Path(__file__).resolve().parents[1]
IN=ROOT/"incoming"
OUT=ROOT/"audit-artifacts"
OUT.mkdir(exist_ok=True)

CODE_RE=re.compile(r"(?<!\d)(\d{1,3})\s*[-_]\s*(STC|VSD|EVR)(?![A-Za-z])", re.I)
PLOT_RE=re.compile(r"PLOT[_-]?(\d{1,3})", re.I)
MONTH_RE=re.compile(r"(20\d{2})[-_](0[1-9]|1[0-2])")
BAND_RE=re.compile(r"(?:^|[_./-])(B02|B03|B04|B05|B06|B07|B08|B8A|B11|B12|SCL)(?:[_./-]|$)", re.I)
SCENE_RE=re.compile(r"(S2[ABC]_MSIL2A_[A-Z0-9_]+)", re.I)

def parse_name(name):
    norm=name.replace("\\","/")
    m=CODE_RE.search(norm)
    code=f"{int(m.group(1))}-{m.group(2).upper()}" if m else None
    p=PLOT_RE.search(norm)
    plot_id=int(p.group(1)) if p else None
    mm=MONTH_RE.search(norm)
    month=f"{mm.group(1)}-{mm.group(2)}" if mm else None
    b=BAND_RE.search(norm)
    band=b.group(1).upper() if b else None
    s=SCENE_RE.search(norm)
    scene=s.group(1) if s else None
    return code,plot_id,month,band,scene

zips=sorted(IN.rglob("*.zip"))
summary=[]
entries=[]
manifest_candidates=[]
for zp in zips:
    row={"zip":zp.name,"bytes":zp.stat().st_size}
    try:
        with zipfile.ZipFile(zp) as z:
            bad=z.testzip()
            infos=[i for i in z.infolist() if not i.is_dir()]
            row["integrity"]="PASS" if bad is None else f"FAIL:{bad}"
            row["files"]=len(infos)
            row["uncompressed_bytes"]=sum(i.file_size for i in infos)
            ext=Counter(Path(i.filename).suffix.lower() or "[none]" for i in infos)
            row["extensions"]=dict(ext.most_common(20))
            row["top_level"]=dict(Counter(i.filename.replace("\\","/").split("/")[0] for i in infos).most_common(20))
            for i in infos:
                code,pid,month,band,scene=parse_name(i.filename)
                rec={"zip":zp.name,"path":i.filename,"bytes":i.file_size,"code":code,"plot_id":pid,"month":month,"band":band,"scene_id":scene}
                entries.append(rec)
                low=i.filename.lower()
                if any(x in low for x in ["manifest","metadata","index","inventory"]) and i.file_size <= 20_000_000:
                    try:
                        raw=z.read(i)
                        text=raw.decode("utf-8-sig",errors="replace")
                        manifest_candidates.append({"zip":zp.name,"path":i.filename,"bytes":i.file_size,"preview":text[:4000]})
                    except Exception as exc:
                        manifest_candidates.append({"zip":zp.name,"path":i.filename,"bytes":i.file_size,"error":str(exc)})
    except Exception as exc:
        row.update({"integrity":"ERROR","error":str(exc),"files":0})
    summary.append(row)

by_band=Counter(e["band"] for e in entries if e["band"])
by_month=Counter(e["month"] for e in entries if e["month"])
by_code=Counter(e["code"] for e in entries if e["code"])
by_pid=Counter(e["plot_id"] for e in entries if e["plot_id"] is not None)
scene_ids=sorted({e["scene_id"] for e in entries if e["scene_id"]})
resolved=sum(1 for e in entries if e["month"] and (e["code"] or e["plot_id"]) and e["band"])
report={
  "zip_count":len(zips),
  "summary":summary,
  "total_files":len(entries),
  "resolved_plot_month_band_paths":resolved,
  "unresolved_paths":len(entries)-resolved,
  "unique_business_codes":len(by_code),
  "unique_plot_ids":len(by_pid),
  "unique_scene_ids":len(scene_ids),
  "bands":dict(by_band),
  "months":dict(sorted(by_month.items())),
  "business_codes":dict(by_code.most_common()),
  "manifest_candidates":manifest_candidates,
  "sample_paths":entries[:500],
}
(OUT/"drive_batch_inventory.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
with (OUT/"drive_batch_entries.csv").open("w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["zip","path","bytes","code","plot_id","month","band","scene_id"])
    w.writeheader();w.writerows(entries)
md=[
 "# Drive satellite batch inventory","",
 f"- ZIP: **{len(zips)}**",
 f"- files: **{len(entries):,}**",
 f"- parsed plot+month+band paths: **{resolved:,}**",
 f"- unique business codes: **{len(by_code)}**",
 f"- unique plot IDs: **{len(by_pid)}**",
 f"- unique scene IDs embedded in paths: **{len(scene_ids)}**","",
 "## ZIPs","",
 "| ZIP | integrity | files | compressed MiB | uncompressed MiB |",
 "|---|---|---:|---:|---:|",
]
for x in summary:
    md.append(f"| {x['zip']} | {x.get('integrity')} | {x.get('files',0):,} | {x.get('bytes',0)/1048576:.1f} | {x.get('uncompressed_bytes',0)/1048576:.1f} |")
md += ["","## Bands","",json.dumps(dict(by_band),ensure_ascii=False),"","## Months","",json.dumps(dict(sorted(by_month.items())),ensure_ascii=False)]
(OUT/"drive_batch_inventory.md").write_text("\n".join(md),encoding="utf-8")
print(json.dumps({k:report[k] for k in ["zip_count","total_files","resolved_plot_month_band_paths","unresolved_paths","unique_business_codes","unique_plot_ids","unique_scene_ids","bands","months"]},ensure_ascii=False,indent=2))
