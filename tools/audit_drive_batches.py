#!/usr/bin/env python3
import csv, json, os, re, zipfile
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
# Environment overrides allow the audit to be exercised against small synthetic ZIPs in tests.
IN = Path(os.environ.get("DRIVE_BATCH_INPUT", str(ROOT / "incoming")))
OUT = Path(os.environ.get("DRIVE_BATCH_OUTPUT", str(ROOT / "audit-artifacts")))
OUT.mkdir(parents=True, exist_ok=True)

CODE_RE = re.compile(r"(?<!\\d)(\\d{1,3})\\s*[-_]\\s*(STC|VSD|EVR)(?![A-Za-z])", re.I)
PLOT_RE = re.compile(r"PLOT[_-]?(\\d{1,3})", re.I)
MONTH_RE = re.compile(r"(20\\d{2})[-_](0[1-9]|1[0-2])")
SCENE_RE = re.compile(r"(S2[ABC]_MSIL2A_[A-Z0-9_]+)", re.I)
BANDS = {"B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12", "SCL"}


def is_macos_metadata(name):
    """Recognize AppleDouble files and the __MACOSX mirror directory."""
    parts = name.replace("\\\\", "/").split("/")
    return "__MACOSX" in parts or any(part.startswith("._") for part in parts)


def parse_name(name):
    """Parse source TIFF paths only; AppleDouble sidecars are never imagery."""
    norm = name.replace("\\\\", "/")
    if is_macos_metadata(norm) or not norm.lower().endswith(".tif"):
        return None, None, None, None, None

    m = CODE_RE.search(norm)
    code = f"{int(m.group(1))}-{m.group(2).upper()}" if m else None
    p = PLOT_RE.search(norm)
    plot_id = int(p.group(1)) if p else None
    mm = MONTH_RE.search(norm)
    month = f"{mm.group(1)}-{mm.group(2)}" if mm else None
    stem = Path(norm).stem.upper()
    band = stem if stem in BANDS else None
    s = SCENE_RE.search(norm)
    scene = s.group(1) if s else None
    return code, plot_id, month, band, scene


zips = sorted(IN.rglob("*.zip"))
summary = []
entries = []
manifest_candidates = []
for zp in zips:
    row = {"zip": zp.name, "bytes": zp.stat().st_size}
    try:
        with zipfile.ZipFile(zp) as z:
            bad = z.testzip()
            infos = [i for i in z.infolist() if not i.is_dir()]
            row["integrity"] = "PASS" if bad is None else f"FAIL:{bad}"
            row["files"] = len(infos)
            row["metadata_files"] = sum(1 for i in infos if is_macos_metadata(i.filename))
            row["source_tiff_files"] = sum(
                1 for i in infos
                if not is_macos_metadata(i.filename) and i.filename.lower().endswith(".tif")
            )
            row["other_files"] = row["files"] - row["metadata_files"] - row["source_tiff_files"]
            row["uncompressed_bytes"] = sum(i.file_size for i in infos)
            ext = Counter(Path(i.filename).suffix.lower() or "[none]" for i in infos)
            row["extensions"] = dict(ext.most_common(20))
            row["top_level"] = dict(Counter(
                i.filename.replace("\\\\", "/").split("/")[0] for i in infos
            ).most_common(20))
            for i in infos:
                metadata = is_macos_metadata(i.filename)
                source_tiff = not metadata and i.filename.lower().endswith(".tif")
                if source_tiff:
                    code, pid, month, band, scene = parse_name(i.filename)
                else:
                    code, pid, month, band, scene = (None, None, None, None, None)
                rec = {
                    "zip": zp.name, "path": i.filename, "bytes": i.file_size,
                    "code": code, "plot_id": pid, "month": month, "band": band,
                    "scene_id": scene,
                    "entry_type": "macos_metadata" if metadata else "source_tiff" if source_tiff else "other",
                }
                entries.append(rec)
                low = i.filename.lower()
                if (not metadata and any(x in low for x in ["manifest", "metadata", "index", "inventory"])
                        and i.file_size <= 20_000_000):
                    try:
                        raw = z.read(i)
                        text = raw.decode("utf-8-sig", errors="replace")
                        manifest_candidates.append({
                            "zip": zp.name, "path": i.filename, "bytes": i.file_size,
                            "preview": text[:4000],
                        })
                    except Exception as exc:
                        manifest_candidates.append({
                            "zip": zp.name, "path": i.filename, "bytes": i.file_size,
                            "error": str(exc),
                        })
    except Exception as exc:
        row.update({"integrity": "ERROR", "error": str(exc), "files": 0,
                    "metadata_files": 0, "source_tiff_files": 0, "other_files": 0})
    summary.append(row)

source_tiffs = [e for e in entries if e["entry_type"] == "source_tiff"]
metadata_entries = [e for e in entries if e["entry_type"] == "macos_metadata"]
other_entries = [e for e in entries if e["entry_type"] == "other"]
by_band = Counter(e["band"] for e in source_tiffs if e["band"])
by_month = Counter(e["month"] for e in source_tiffs if e["month"])
by_code = Counter(e["code"] for e in source_tiffs if e["code"])
by_pid = Counter(e["plot_id"] for e in source_tiffs if e["plot_id"] is not None)
scene_ids = sorted({e["scene_id"] for e in source_tiffs if e["scene_id"]})
resolved = sum(
    1 for e in source_tiffs
    if e["month"] and (e["code"] or e["plot_id"] is not None) and e["band"] and e["scene_id"]
)
unresolved = len(source_tiffs) - resolved
report = {
    "zip_count": len(zips),
    "summary": summary,
    "total_files": len(entries),
    "archive_entries": len(entries),
    "source_tiff_files": len(source_tiffs),
    "metadata_files": len(metadata_entries),
    "other_files": len(other_entries),
    "resolved_plot_month_scene_band_paths": resolved,
    "unresolved_source_tiffs": unresolved,
    # Compatibility alias: now counts unresolved source TIFFs, not metadata sidecars.
    "unresolved_paths": unresolved,
    "unique_business_codes": len(by_code),
    "unique_plot_ids": len(by_pid),
    "unique_scene_ids": len(scene_ids),
    "bands": dict(sorted(by_band.items())),
    "months": dict(sorted(by_month.items())),
    "business_codes": dict(by_code.most_common()),
    "manifest_candidates": manifest_candidates,
    "sample_paths": source_tiffs[:50],
    "sample_metadata_paths": metadata_entries[:20],
}
(OUT / "drive_batch_inventory.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
with (OUT / "drive_batch_entries.csv").open("w", encoding="utf-8-sig", newline="") as f:
    fields = ["zip", "path", "bytes", "code", "plot_id", "month", "band", "scene_id", "entry_type"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(entries)

md = [
    "# Drive satellite batch inventory", "",
    f"- ZIPs: **{len(zips)}**",
    f"- Archive file entries (including metadata): **{len(entries):,}**",
    f"- Source TIFFs (excluding AppleDouble / __MACOSX): **{len(source_tiffs):,}**",
    f"- macOS metadata entries excluded from imagery counts: **{len(metadata_entries):,}**",
    f"- Other non-metadata files: **{len(other_entries):,}**",
    f"- Fully resolved plot+month+scene+band TIFF paths: **{resolved:,}**",
    f"- Unresolved source TIFF paths: **{unresolved:,}**",
    f"- Unique business codes in source TIFFs: **{len(by_code)}**",
    f"- Unique plot IDs in source TIFFs: **{len(by_pid)}**",
    f"- Unique scene IDs in source TIFFs: **{len(scene_ids)}**", "",
    "## ZIPs", "",
    "| ZIP | integrity | archive entries | source TIFFs | metadata | other | compressed MiB | uncompressed MiB |",
    "|---|---|---:|---:|---:|---:|---:|---:|",
]
for x in summary:
    md.append(
        f"| {x['zip']} | {x.get('integrity')} | {x.get('files', 0):,} | "
        f"{x.get('source_tiff_files', 0):,} | {x.get('metadata_files', 0):,} | "
        f"{x.get('other_files', 0):,} | {x.get('bytes', 0)/1048576:.1f} | "
        f"{x.get('uncompressed_bytes', 0)/1048576:.1f} |"
    )
md += ["", "## Source TIFF bands", "", json.dumps(dict(sorted(by_band.items()), ensure_ascii=False),
       ensure_ascii=False), "", "## Source TIFF months", "",
       json.dumps(dict(sorted(by_month.items()), ensure_ascii=False), ensure_ascii=False)]
(OUT / "drive_batch_inventory.md").write_text("\n".join(md), encoding="utf-8")
print(json.dumps({
    k: report[k] for k in [
        "zip_count", "total_files", "source_tiff_files", "metadata_files", "other_files",
        "resolved_plot_month_scene_band_paths", "unresolved_source_tiffs",
        "unique_business_codes", "unique_plot_ids", "unique_scene_ids", "bands", "months",
    ]
}, ensure_ascii=False, indent=2))
print("\n=== SOURCE TIFF SAMPLES ===")
for x in summary:
    print("\n##", x["zip"], "integrity", x.get("integrity"),
          "source TIFFs", x.get("source_tiff_files"), "metadata", x.get("metadata_files"))
    for e in [r for r in source_tiffs if r["zip"] == x["zip"]][:20]:
        print(e["path"])
print("\n=== NON-METADATA MANIFEST / INDEX CANDIDATES ===")
for m in manifest_candidates[:80]:
    print("\n---", m["zip"], m["path"], m.get("bytes"))
    print(m.get("preview") or m.get("error") or "")
