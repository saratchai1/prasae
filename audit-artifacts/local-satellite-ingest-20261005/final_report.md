# ผลนำข้อมูล Sentinel-2 รอบ 2026-10-05 เข้าระบบ

เพิ่มข้อมูลจริง **32 แปลง–เดือน** ใน 29 แปลง จาก local delivery โดยคงข้อมูลเดิมทั้งหมด ภาพ RGB/NDVI ใหม่พร้อมดูใน unified workspace 210 แปลง

## 1. Source inventory

LOCAL_FILES_SCANNED=3086 · SCIENTIFIC_TIFS=2862 (prepared 2859 + repair 3) · RESOLVED_PLOTS=124 · PLOT_MONTHS=178

ตรวจ decode และ SHA-256 ทุก TIFF ใช้ index ส่วนตัว ไม่มี raw TIFF เข้า Git; manifests ของผู้ดาวน์โหลดไม่ครบ: download_manifest 712 รายการ เทียบกับ prepared TIFF จริง 2859; request_results 390 จากเป้าหมายก่อนหน้า 761 รายการ ไฟล์ raw-native ไม่มีข้อมูล

## 2. Archive/file integrity

ZIP_COUNT=0 · ZIP_VALID=0 · ZIP_CORRUPT=0 · TIFF_VALID=2862 · UNRESOLVED_SOURCES=0

checksums.sha256 มี 13,593 บรรทัดซ้ำจากหลายรอบ ครอบคลุม 2,675 ไฟล์ปัจจุบันและไม่มี hash ขัดแย้ง อีก 187 ไฟล์ไม่ได้อยู่ในรายการ แต่ตรวจ decode/compute SHA และ snapshot ซ้ำโดยอิสระครบแล้ว รายการนี้จึงไม่ใช่ inventory authoritative

## 3. Scene completeness

COMPLETE_SCENES=212 · PARTIAL_SCENES=64 · TOTAL_SCENES=276 · UNIQUE_PRODUCTS=106

## 4. Registry/PDD scope และรายการซ้ำ

REGISTRY_CONTAINED=276 scene representations · PDD_ONLY=0 · UNRESOLVED_SCOPE=0 · REGISTRY_IDENTITIES=210 · DUPLICATE_REGISTRY_IDS=0

ข้าม 111 แปลง–เดือนที่มี observation ใช้ได้อยู่แล้ว; ไม่แก้ repair ของ75/2024-06 และ121/2024-09 เพราะทั้งสองช่องมีข้อมูลใช้ได้แล้ว พบ910ไฟล์ SHA ซ้ำกับชุดก่อน และ976band pairs ที่พิกเซลตรงกับ exact product/grid เดิม ไม่มี conflict ไม่มี PDD subset แทน registry

Partial ที่ซ่อมได้ด้วย old exact product มี21scene:20อยู่ในช่อง observed จึงข้าม อีก1คือ203/2025-09 ตรงกับ scene เดิมซึ่งเคย coverage3.03% จึงไม่สร้าง observation ใหม่จากข้อมูลที่เคยต่ำกว่าเกณฑ์

## 5. Missing observation reconciliation

MISSING_CANDIDATES_BEFORE=290 · MISSING_WITH_ELIGIBLE_SOURCE=57 · NEWLY_ACCEPTED=32 · NO_CLEAR_SCENE=8 · LOW_COVERAGE=17 · NO_COMPLETE_SOURCE_IN_THIS_DELIVERY=233 · STILL_MISSING=258

เฉพาะเดือนจริงและ full registry bands ครบ11เท่านั้น ไม่มี nearest-month, synthetic pixels หรือ copy ภาพข้ามเดือน รายการหลังนำเข้าคือ remaining_candidates.json; missing_candidates.json เป็น snapshot ก่อนนำเข้า

## 6. Observations accepted

OBSERVED_BEFORE=2230 · OBSERVED_AFTER=2262 · EXISTING_OBSERVATIONS_PRESERVED=2230 · EXISTING_IMAGES_PRESERVED=4460

| Registry ID | รหัส | เดือนจริง | Coverage % |
|---:|---|---|---:|
| 3 | 7-STC | 2024-06 | 5.04 |
| 3 | 7-STC | 2024-09 | 95.80 |
| 9 | 22-STC | 2024-09 | 5.52 |
| 14 | 6-STC | 2025-06 | 100.00 |
| 14 | 6-STC | 2026-08 | 23.91 |
| 21 | 65-STC | 2025-09 | 14.82 |
| 27 | 42-STC | 2026-08 | 44.25 |
| 28 | 43-STC | 2024-06 | 78.51 |
| 28 | 43-STC | 2026-08 | 28.30 |
| 47 | 62-STC | 2025-09 | 48.38 |
| 48 | 64-STC | 2026-08 | 100.00 |
| 50 | 29-STC | 2023-09 | 26.00 |
| 54 | 59-STC | 2025-06 | 95.75 |
| 75 | 21-STC | 2024-09 | 29.21 |
| 81 | 17-STC | 2024-09 | 22.82 |
| 85 | 64-VSD | 2023-09 | 21.26 |
| 91 | PLOT_091 | 2026-08 | 83.33 |
| 99 | PLOT_099 | 2023-09 | 100.00 |
| 125 | 100-VSD | 2026-08 | 32.48 |
| 137 | 27-VSD | 2025-09 | 14.50 |
| 163 | 18-VSD | 2025-06 | 8.96 |
| 170 | 92-VSD | 2026-08 | 89.70 |
| 171 | PLOT_171 | 2023-12 | 100.00 |
| 172 | PLOT_172 | 2023-09 | 86.67 |
| 173 | PLOT_173 | 2023-12 | 100.00 |
| 180 | PLOT_180 | 2026-08 | 100.00 |
| 181 | PLOT_181 | 2025-06 | 8.33 |
| 189 | PLOT_189 | 2025-09 | 100.00 |
| 192 | PLOT_192 | 2025-06 | 10.34 |
| 197 | PLOT_197 | 2025-06 | 80.56 |
| 209 | PLOT_209 | 2024-12 | 20.00 |
| 210 | PLOT_210 | 2024-12 | 96.26 |

## 7. Files generated

DERIVED_RGB_ADDED=32 · DERIVED_NDVI_ADDED=32 · TOTAL_EXPECTED_IMAGES=4524 · UPDATED_PLOT_METADATA=29

แก้ observation/metadata เฉพาะ32ช่องที่ขาด และ QA เฉพาะ32ช่องนั้น QA อีก2488รายการคงเดิม ตรวจ reapply ได้0acceptedและ appfiles5001ไฟล์ไม่เปลี่ยน byte ใด

## 8. Radiometry และ QA

QA: CLEAR=1759 · INSUFFICIENT=702 · RADIOMETRY_REVIEW=10 · ATMOSPHERE_REVIEW=29 · VISUAL_REVIEW=16 · TIDE_WATER_REVIEW=4

ชุดใหม่เก็บ native DN แต่ไม่มี scale/offset และ zero-nodata ใน TIFF header ต้องใช้ per-band STAC ที่ตรงกับ product และ sidecar โดย mask nodata ก่อน resampling แล้วใช้ DN × scale + offset;1060 spectral metadata assets ยืนยัน scale0.0001 และoffset−0.1 ส่วนSCLไม่เปลี่ยนค่า สูตรเดิม DN/10000 ไม่ถูกแก้ย้อนหลัง หลักฐานเป็น metadata-valid native BOA ไม่ใช่การยืนยัน harmonization กับ legacy

ภาพจริง32ช่องดูได้ แต่22ช่อง coverage<95 จึง INSUFFICIENT และ10ช่อง coverage≥95 แม้ผ่าน visual screening ยัง RADIOMETRY_REVIEW เพื่อป้องกัน NDVI/พื้นที่พืชเปลี่ยนลวงจากสูตรต่างกัน ยังไม่แก้ calibration เดิม ไม่มีคู่ native-vs-native เดือนเดียวกันต่างปีที่ถูกตัดออกใน dataset นี้

อ้างอิงเจ้าของข้อมูล: [Earth Search gain/offset](https://github.com/Element84/earth-search#gainoffset-in-items-after-jan-25-2022), [Copernicus L2A encoding](https://sentiwiki.copernicus.eu/web/s2-products)

## 9. Tests

SOURCE_AUDIT=PASS · UNIFIED_CATALOG_AUDIT=PASS · BROWSER_UAT=PASS (16 checks และโหลด RGB/NDVI ของ accepted ทั้ง33ช่องจากสองbatch) · MANIFEST_AUDIT=PASS · PYTHON_REGRESSIONS=46 PASS · NODE_TESTS=43 PASS · SYNTAX=PASS · QA_REBUILD=PASS · IDEMPOTENCE=PASS

Browser ยืนยัน sliderลาก/keyboard/splitpixels/zoom/pan/เดือนแรก/missing/retry/PDDscope/mobile และ basemapเดิมคงอยู่ ตรวจ hash observations และ PNG ข้ามสอง batch โดย CI ไม่ต้องดาวน์โหลด raw satellite

## 10. Branch / PR / SHA

BRANCH=feat/local-satellite-ingest-20261004 · PR=https://github.com/saratchai1/prasae/pull/13 · AUDIT_BASE_SHA=e24d2b71f15e5df710bab862401312841524e3de

Commitที่เผยแพร่และFILES_CHANGEDแสดงใน PR body และข้อความส่งงาน ไม่ merge gh-pages ระหว่างงานนี้

## 11. Remaining blockers

ยังขาด258แปลง–เดือน:233ไม่มี complete source ที่ใช้ได้ใน deliveryนี้,17coverage<5%,8ไม่มีclear scene. มี64partialsceneในsourceรวม ซึ่งหลายรายการอยู่ในช่องเดิมที่มีข้อมูลแล้ว การเติมต่อจำเป็นต้องได้ทุกbandของexact product/fullregistryหรือsceneอื่นในเดือนเดียวกันที่มีclear coverageมากพอ

การนำค่าชุดใหม่ไปสรุปการเปลี่ยนแปลงเทียบlegacyยังต้องยืนยันradiometric harmonizationและความเหมาะสมของthreshold/calibration โดยไม่เปลี่ยนผลเดิมเงียบ ๆ
