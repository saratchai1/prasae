# ผลตรวจ Sentinel-2 delivery `inputs-next-2` — 2026-10-06

ตรวจและดำเนินการครบเท่าที่ข้อมูลจริงรองรับแล้ว **เพิ่ม observation ได้ 0 ช่อง** เพราะ source ทั้ง 351 แปลง–เดือนในชุดนี้อยู่ในช่องที่มีข้อมูลใช้ได้แล้วทั้งหมด ไม่เขียนทับ observation, ภาพ, metadata หรือ QA เดิม ระบบยังมี **2,262 observed / 258 missing** ใน 210 registry identities

## 1. Source inventory

LOCAL_FILES_SCANNED=6685 · LOCAL_BYTES=505132094 · SCIENTIFIC_TIFS=6208 · PREPARED_TIFS=6207 · HELD_REPAIR_TIFS=1 · SUPPORT_FILES=477 · RAW_NATIVE_FILES=0 · RESOLVED_PLOTS=154 · PLOT_MONTHS=351

อ่านและ decode prepared TIFF ทั้งหมดใน reusable SQLite index ส่วนตัว มี manifest/hash ของทุกไฟล์ใน portable reports ไม่ commit raw satellite หรือ absolute machine paths

## 2. Archive/file integrity

ZIP_COUNT=0 · ZIP_VALID=0 · ZIP_CORRUPT=0 · TIFF_VALID=6208 · INVALID_TIFF=0 · ALL_ZERO_TIFF=0

`checksums.sha256` มี 50,958 บรรทัด / 8,882 paths: prepared จริง 6,207 ไฟล์ hash ตรงทั้งหมด อีก 1 repair ไม่อยู่ใน checksum list แต่ decode/hash โดยอิสระแล้ว มี 2,675 stale paths ที่ไม่มีใน delivery นี้ ไม่มี checksum conflict

`download_manifest.json` มี 2,833 รายการที่ path/hash/registry mapping ตรงจริงทั้งหมด แต่ prepared TIFF อีก 3,374 ไฟล์ไม่ได้อยู่ใน manifest จึงใช้ actual files เป็น inventory authoritative การตรวจ snapshot ทุก 6,685 ไฟล์ซ้ำไม่พบไฟล์เพิ่ม ลบ เปลี่ยน hash/size/mtime

## 3. Scene completeness

TOTAL_SCENES=615 · COMPLETE_SCENES=474 · PARTIAL_SCENES=141 · UNIQUE_PRODUCTS=233

Complete หมายถึงมีทั้ง 11 bands: B02/B03/B04/B05/B06/B07/B08/B8A/B11/B12/SCL ไม่สร้าง band ที่ขาดเอง ไม่มี partial union ข้าม delivery ที่กลายเป็น complete เพิ่ม

## 4. Registry/PDD scope และการซ้ำ

REGISTRY_IDENTITIES=210 · DUPLICATE_REGISTRY_IDS=0 · REGISTRY_CONTAINED=615 · PDD_ONLY=0 · UNRESOLVED_SCOPE=0 · EXISTING_OBSERVED_SLOTS_IN_DELIVERY_SKIPPED=351

ตรวจรหัสธุรกิจจากชื่อ registry → canonical ID → request ID → source path และ full geometry/footprint โดย agent อีกตัว ผลตรงทั้งหมด ทุก band footprint ผ่าน containment≥99.9% ไม่มี PDD pixels มาแทน registry

Prepared bands 95 ไฟล์จาก 16 scene overlaps มี exact product/grid/SHA/pixels ตรงกับ delivery ก่อนหน้า และ repair75/2024-06 B11 ซ้ำอีก 1 ไฟล์ รวม 96 physical duplicates; conflicts=0 การมี source ต่าง acquisition ในช่องที่ observed แล้วก็ไม่ใช่เหตุให้เขียนทับตามข้อกำหนดของผู้ใช้

## 5. Missing observation reconciliation

MISSING_CANDIDATES_BEFORE=258 · MISSING_WITH_ANY_NEW_SOURCE=0 · MISSING_WITH_ELIGIBLE_NEW_SOURCE=0 · NEWLY_ACCEPTED=0 · STILL_MISSING=258

ผล current physical delivery: NO_COMPLETE_SOURCE_IN_THIS_DELIVERY=258 ไม่มีไฟล์ใน `inputs-next-2` ที่ตรงกับช่อง missing ใด

Request log 761 รายการปะปนประวัติเดิม ทุก 258 ช่อง missing มี search timestamp UTC วันที่ **2026-10-04** ไม่ใช่การค้นหาใหม่ในรอบ Oct 5/6:

- 223 รายงาน `NO_CLEAR_SCENE_AFTER_EXHAUSTIVE_SEARCH`: 197 มี max SCL clear=0 และ 26 มี max<5%; นี่เป็นคำรายงานของผู้ดาวน์โหลดจากการค้นหาเดิม ไม่ใช่ข้อพิสูจน์ว่าค้นทุก provider ใหม่แล้ว
- 35 รายงาน `REQUIRES_RADIOMETRIC_ADAPTER` แต่อ้าง 49 scenes ใน **inputs-next ชุดก่อน**: 467 band claims มีไฟล์เก่าจริง อีก 72 band claims เป็น DOWNLOAD_ERROR ไม่มี band claim ที่เป็นไฟล์ใหม่สำหรับ missing slots

ประมวลผล source เก่าซ้ำด้วย canonical pipeline และ metadata/radiometry เดิม ได้ผลตรงรายงานก่อนหน้าทุกช่อง: **LOW_COVERAGE=17 · NO_CLEAR_SCENE=8 · NO_COMPLETE_SOURCE=233** โดย 233 ประกอบด้วย 223 ที่ไม่มี source เก็บไว้ และ 10 incomplete old targets ในกลุ่ม stale adapter claims

## 6. Observations accepted

OBSERVED_BEFORE=2262 · OBSERVED_AFTER=2262 · ACTUALLY_ACCEPTED=0 · EXISTING_OBSERVATIONS_PRESERVED=2262 · EXISTING_IMAGES_PRESERVED=4524

ไม่ substitute เดือนใกล้เคียง ไม่สังเคราะห์ภาพ/พิกเซล ไม่ขยาย PDD scope ไม่แก้ข้อมูลเก่าที่ใช้งานได้ ไม่มี observation ใหม่ที่อ้างจากข้อความ download-success โดยไม่มี scientific files

## 7. Files generated

DERIVED_RGB_ADDED=0 · DERIVED_NDVI_ADDED=0 · UPDATED_PLOT_METADATA=0 · APPLICATION_DATA_FILES_CHANGED=0 · APPLICATION_DATA_FILES_PRESERVED=5001

เพิ่ม portable audit/provenance/reconciliation reports และรับ exact exporter fingerprint ที่เปลี่ยนเฉพาะ destination directory ไม่มี app UI/slider/basemap changes การใช้ `--apply` ซ้ำ accepted=0 และ app data files ทุก byte คงเดิม ขนาด scene manifest 5.6 MiB อยู่ต่ำกว่า manifest จาก audit แรก

## 8. Radiometry และ QA

METADATA_PRODUCTS_VALIDATED=233 · SPECTRAL_ASSETS_VALIDATED=2330 · METADATA_CONFLICTS=0

สูตร native DN เดิม: DN × per-band STAC scale + offset โดย spectral scale=0.0001, offset=−0.1, nodata=0; mask nodata ก่อน resampling และ SCL categorical unchanged สคริปต์ exporter ต่างจากรอบก่อนเฉพาะ DELIVERY_ROOT literal ตรวจทั้ง diff/AST และ encoder operations แล้ว ไม่เปลี่ยนสูตร legacy DN/10000 หรือ calibration

QA เดิมทั้งหมด 2,520 รายการคงเดิม: CLEAR=1759 · INSUFFICIENT=702 · RADIOMETRY_REVIEW=10 · ATMOSPHERE_REVIEW=29 · VISUAL_REVIEW=16 · TIDE_WATER_REVIEW=4

สิบ observation ของ native รอบก่อนยังต้องตรวจ harmonization ก่อนสรุป delta เทียบ legacy; งานนี้ไม่แก้ review gates เพราะไม่มี accepted observations ใหม่

## 9. Tests

SOURCE_AUDIT=PASS · UNIFIED_CATALOG_AUDIT=PASS · MANIFEST_PROVENANCE_AUDIT=PASS (3 batches / 38,854 source file representations) · PYTHON_REGRESSIONS=46 PASS · NODE_TESTS=43 PASS · BROWSER_UAT=16 PASS · JAVASCRIPT_SYNTAX=PASS · QA_REBUILD_BYTE_MATCH=PASS · REAPPLY_IDEMPOTENCE=PASS

ตรวจ RGB/NDVI ของ accepted เดิมทั้ง 33 ช่องจากสอง delivery ก่อนหน้า โหลดตรงเดือนจริง พร้อม checks search/province/210identities, registry/PDD/FCD, GIS/table, missing/QA chart, slider split pixels/drag/keyboard/zoom/pan/firstmonth/missing/retry/mobile โปรแกรม data และ QA ไม่ถูกเปลี่ยนจากการทดสอบ

## 10. Branch / PR / SHA

BRANCH=feat/local-satellite-ingest-20261004 · PR=https://github.com/saratchai1/prasae/pull/13 · AUDIT_BASE_SHA=6850bc0b565d3caac480c70cfcb29de21619d260

Commit SHA ที่เผยแพร่และ FILES_CHANGED จะระบุใน PR body/ข้อความส่งงาน อัปเดต PR เดิมโดยไม่ merge gh-pages

## 11. Remaining blockers

ยังมี 258 แปลง–เดือนขาดจริง การดาวน์โหลดรอบนี้เสร็จไม่ได้ทำให้มี source ใช้งานได้เพิ่มสำหรับช่องเหล่านั้น ต้องค้น exact-month/full-registry source ที่ครบ 11 bands และมี clear coverage ตาม canonical gate≥5%; full-plot comparisons ยังต้อง coverage≥95% และ QA ผ่าน

`remaining_candidates.json` และ `remaining_request_reconciliation.json` แจกแจงทุกช่องพร้อมวันค้นหาเดิม สถานะผู้ดาวน์โหลด จำนวน candidate/ไฟล์ที่อ้าง และผล canonical เดิม เพื่อไม่ส่งงานซ้ำกับ 351 ช่องที่ observed แล้ว 10 incomplete targets ต้อง retry band ของ exact product ที่ขาดหรือ acquisition ใหม่ในเดือนเดียวกัน; 17 low-coverage และ 8 no-clear ต้อง source ที่ให้ clear pixels เพิ่มจริง ห้ามผ่อนเกณฑ์หรือเติมภาพเดา
