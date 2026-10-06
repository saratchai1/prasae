# ผลนำเข้า Sentinel-2 delivery `inputs-next-3` — 2026-10-06

นำเข้าเสร็จเท่าที่ scientific source จริงรองรับ: **เพิ่ม 9 แปลง–เดือนใน 9 แปลง และภาพ RGB/NDVI 18 ภาพ** ปัจจุบันมี **2,271 observed / 249 missing** ใน 210 registry identities ข้อมูลและภาพเดิมคงเดิม

รายงานดาวน์โหลดที่ระบุ usable=0 ใช้อ้างอิงไม่ได้: ทั้ง 52 downloaded requests เกิด error อ่าน `valid_pct` ซึ่งไม่มีใน canonical schema และ audit ของผู้ดาวน์โหลดยังใช้ raw DN/grid/threshold ต่างจากระบบ ผลนี้ใช้ canonical v4 กับ native metadata ที่ตรวจแล้ว และมีการคำนวณอิสระสองทางให้ผลตรงกัน

## 1. Source inventory

LOCAL_FILES_SCANNED=931 · LOCAL_BYTES=79170683 · SCIENTIFIC_TIFS=810 · SUPPORT_FILES=121 · RESOLVED_PLOTS=45 · PLOT_MONTHS=52 · RAW_CACHE_FILES=0

แยกหลักฐาน exporter ที่อยู่นอก delivery อีก 1 ไฟล์เป็น auxiliary evidence: SOURCE_EVIDENCE_FILES_SCANNED=932 ไม่เพิ่มเข้า physical file count ของ delivery ใช้ reusable SQLite index ส่วนตัว ไม่ commit raw TIFF, exporter source หรือ absolute machine paths

## 2. Archive/file integrity

ZIP_COUNT=0 · ZIP_VALID=0 · ZIP_CORRUPT=0 · ZIP_DUPLICATE_SOURCE=0 · TOTAL_MEMBERS=0 · TIFF_VALID=810 · INVALID_TIFF=0 · ALL_ZERO_TIFF=0

ทั้ง 810 TIFF decode ผ่านและ hash/size ตรง download manifest ทั้งหมด Checksum list 1,785 บรรทัดครอบคลุม TIFF จริงครบ ไม่มี hash conflict/unlisted scientific file ตรวจซ้ำ source 931 ไฟล์ไม่พบ hash/size/mtime เปลี่ยน หลักฐาน exporter ก็ถูก hash ผูกใน inventory และตรวจ unchanged ก่อนเขียนแอป

## 3. Scene completeness / repairs

TOTAL_SCENES=74 · COMPLETE_SCENES=70 · PARTIAL_SCENES=4 · UNIQUE_PRODUCTS=57

Repair packet เดิม 15 scenes ได้ครบ 11 bands แล้วทั้ง 15: 55 requested missing bands และ 110 retained bands โดย retained bytes ตรง delivery เดิมและ packet hashes ทั้ง 165 band grids ตรง specification และ saved STAC product/URI ตรง exact product ไม่แทน acquisition

ยังมี partial 4 scenes: 48-STC/2024-03 ขาด B04; 19-VSD/2025-09 ขาด B08; PLOT_097/2024-12 ขาด B08; 99-VSD/2025-09 ขาด B08 PLOT_097/2024-12 มีแต่ incomplete source ส่วนอีกสามช่องมี complete acquisition อื่นให้ประมวลผลได้ ไม่สร้าง missing band เอง

## 4. Registry/PDD scope และการซ้ำ

REGISTRY_IDENTITIES=210 · DUPLICATE_REGISTRY_IDS=0 · REGISTRY_CONTAINED=74 · PDD_ONLY=0 · UNRESOLVED_SCOPE=0 · UNRESOLVED_PLOT=0

ทุก band footprint ผ่าน full-registry containment≥99.9% ไม่มี PDD crop มาแทน registry และ PDD22 ยังคงเป็น optional participating scope ภายใต้ identity เดิม

TIFF 455 ไฟล์มี hash ตรง delivery `inputs-next` และ 355 ไฟล์มี byte hash ใหม่เมื่อเทียบสอง delivery ก่อน ไม่มีไฟล์ตรง `inputs-next-2` การซ้ำระดับไฟล์ไม่ได้ใช้แทนการตรวจ identity/month/product/scope และไม่ใช่เหตุให้แก้ existing usable observations

## 5. Missing observation reconciliation

MISSING_CANDIDATES_BEFORE=258 · MISSING_WITH_PHYSICAL_SOURCE=52 · MISSING_WITH_ELIGIBLE_SOURCE=51 · NEWLY_ACCEPTED=9 · STILL_MISSING=249

ผล canonical ทุกช่อง: ACCEPTED=9 · LOW_COVERAGE=24 · NO_CLEAR_SCENE=18 · NO_COMPLETE_SOURCE=207

NO_COMPLETE_SOURCE 207 ประกอบด้วย 206 ช่องที่ไม่มี scientific file ใน delivery และ PLOT_097/2024-12 ที่มี incomplete scene ผู้ดาวน์โหลดรายงาน 206 ช่องแรกว่าไม่พบ clear scene แต่ยังไม่ได้พิสูจน์โดยอิสระว่าค้นครบทุก provider ผล local-file audit จึงแสดงว่าไม่มี complete source แทนการอ้างว่าดาวน์โหลดสำเร็จหรือค้นทั่วโลกแล้ว

## 6. Observations accepted

OBSERVED_BEFORE=2262 · OBSERVED_AFTER=2271 · EXISTING_OBSERVATIONS_PRESERVED=2262 · EXISTING_IMAGES_PRESERVED=4524

| Registry ID | รหัส | เดือน | Clear coverage | QA |
|---|---|---|---|---|
| 25 | 48-STC | 2024-03 | 100.00% | RADIOMETRY_REVIEW |
| 63 | 15-STC | 2024-09 | 20.78% | INSUFFICIENT |
| 76 | 13-STC | 2025-06 | 48.40% | INSUFFICIENT |
| 87 | 101-VSD | 2025-09 | 20.05% | INSUFFICIENT |
| 131 | 99-VSD | 2025-06 | 84.50% | INSUFFICIENT |
| 142 | 36-VSD | 2023-09 | 100.00% | RADIOMETRY_REVIEW |
| 151 | 96-VSD | 2026-08 | 65.60% | INSUFFICIENT |
| 153 | 69-VSD | 2024-09 | 59.28% | INSUFFICIENT |
| 186 | PLOT_186 | 2024-09 | 100.00% | RADIOMETRY_REVIEW |

ภาพใหม่ทั้ง 9 ช่องเป็น exact-month จาก complete native source ที่ผ่าน canonical composite gate≥5% สามช่อง coverage 100% แต่ยังต้อง radiometric harmonization ก่อนสรุป delta เทียบ legacy อีกหกช่องยังไม่ผ่าน full-plot coverage≥95% จึงมีภาพให้ดูแต่ไม่เติม chart/portfolio metrics

## 7. Files generated / preservation

DERIVED_RGB_ADDED=9 · DERIVED_NDVI_ADDED=9 · EXPECTED_DERIVED_FILES=4542 · UPDATED_PLOT_METADATA=9 · MODIFIED_EXISTING_DATA_FILES=11 · NEW_IMAGE_FILES=18

ไฟล์เดิมใต้ data/ ทั้งหมด 9,174 ไฟล์ (รวม optional PDD assets) เปลี่ยนเฉพาะ metadata 9 แปลง และ timeseries/QA รวม 11 ไฟล์ อีก 9,163 ไฟล์เหมือนเดิมทุก byte มีภาพเพิ่ม 18 ภาพ ตรวจ fingerprints ยืนยัน observation เดิม 2,262 ช่อง ภาพเดิม 4,524 ภาพ และ QA ที่ไม่เกี่ยวข้อง 2,511 records คงเดิม

นำเข้าซ้ำ accepted=0 และ data/ ทุก 9,192 ไฟล์ byte-identical ภาพก่อน–หลัง/slider/basemap เดิมผ่าน browser checks โดยไม่มี frontend code changes ในรอบนี้

## 8. Radiometry และ QA

METADATA_PRODUCTS_VALIDATED=57 · SPECTRAL_ASSETS_VALIDATED=570 · METADATA_CONFLICTS=0

TIFF headers เป็น native DN: spectral uint16 736 ไฟล์และ categorical SCL uint8 74 ไฟล์ ไม่มี nodata/scale/offset tags Exporter `run_pipeline.py` checksum อยู่ใน reviewed allowlist หลังตรวจว่า download_band AST เหมือน encoder รอบก่อน การเปลี่ยน script อยู่ใน acquisition/state/repair handling

ใช้ per-band STAC **DN × 0.0001 − 0.1** ครั้งเดียวและ mask nodata=0 ก่อน resampling; SCL categorical ไม่ scale สูตร legacy DN/10000, canonical grid/equations/cloud buffer และ threshold 0.155 ของ registry76 / 0.25 ของแปลงอื่นคงเดิม External exporter evidence ผูก hash ใน public inventory ด้วย portable ID และตรวจ changed-source ก่อน apply

QA ปัจจุบัน: CLEAR=1759 · INSUFFICIENT=699 · RADIOMETRY_REVIEW=13 · ATMOSPHERE_REVIEW=29 · VISUAL_REVIEW=16 · TIDE_WATER_REVIEW=4

สาม observation ใหม่ที่ coverage100% ผ่าน secondary visual screen แต่คง RADIOMETRY_REVIEW ไม่มี full native month เดิมในสามแปลงนี้ให้เทียบกัน จึงไม่มีการผ่อน comparison gate หรือเปลี่ยน water reference ของข้อมูลเดิม canonical QA rebuild ตรง byte-for-byte

## 9. Tests

SOURCE_AUDIT=PASS · UNIFIED_CATALOG_AUDIT=PASS · MANIFEST_PROVENANCE_AUDIT=PASS (4 batches / 39,786 source evidence records) · PYTHON_REGRESSIONS=56 PASS · NODE_TESTS=43 PASS · BROWSER_UAT=16 PASS · JAVASCRIPT_SYNTAX=PASS · QA_REBUILD_BYTE_MATCH=PASS · REAPPLY_IDEMPOTENCE=PASS

Browser ตรวจ imagery ของ accepted ทั้ง 42 ช่องจากทุก batch (รวม 9 ช่องใหม่) โหลด RGB/NDVI ตรงเดือนจริง พร้อม 210 identities/search/province/GIS/table/registry-PDD-FCD/chart exclusions และ Before/After split pixels, drag, keyboard, zoom/pan, boundary, first-month selection, missing/failure/retry/mobile No nearest-month substitution / no synthetic imagery / registry-PDD boundary / expected derived assets ผ่านทั้งหมด รายละเอียดอยู่ใน test_results.json

## 10. Branch / PR / SHA

BRANCH=feat/local-satellite-ingest-20261004 · PR=https://github.com/saratchai1/prasae/pull/13 · AUDIT_BASE_SHA=7e6dae1be1c479173ad2791cae4460f53ba892e2

Commit SHA ที่เผยแพร่และ FILES_CHANGED ระบุใน PR body/ข้อความส่งงาน อัปเดต PR เดิมเข้า gh-pages โดยไม่ merge รายงานเดิมทั้งสาม batch ยังคงเป็น historical evidence

## 11. Remaining blockers

เหลือ **249 exact plot-months**: 24 coverage<5%, 18 ไม่มี clear scene ที่รอด canonical masks, และ 207 ไม่มี complete source ตามคำอธิบายข้างต้น `remaining_candidates.json` แจกแจงทั้งหมดเพื่อไม่สั่ง download ซ้ำช่องที่รับแล้ว

ต้องการ exact-month/full-registry source ที่ครบ 11 bands และเพิ่ม clear pixels จริง; incomplete PLOT_097/2024-12 ต้อง B08 ของ exact product หรือ complete acquisition อื่นในเดือนเดียวกัน การมีข้อมูลใหม่ 9 ช่องช่วยให้ดูภาพได้มากขึ้น แต่ยังไม่ทำให้ native/legacy vegetation delta ผ่าน QA จนกว่าจะมี harmonization ที่ตรวจสอบได้ ไม่มีการสังเคราะห์ pixels, ใช้เดือนข้างเคียง หรือแก้ข้อมูลที่ดีอยู่แล้ว
