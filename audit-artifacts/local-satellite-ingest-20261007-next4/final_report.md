# ผลนำเข้าข้อมูล inputs-next-4 — 7 ตุลาคม 2569

## 1. Source inventory
ตรวจไฟล์จริง 21,693 ไฟล์ / 1,965,605,661 bytes: TIFF 20,719 (prepared 20,718 และ test_B04.tif ที่ถือไว้ 1), support 974. ทุก TIFF อ่านผ่าน; prepared hash/size ตรง manifest ทั้งหมด. ไม่มี all-zero raster. ครอบคลุม 136 registry plots /246 แปลง–เดือนที่ยังขาด. Source inventory ของผู้ส่งเป็นสำเนา request log จึงใช้ผลตรวจไฟล์จริงแทน.

หลักฐาน composite เพิ่ม source เดิมที่ตรวจไว้แล้ว 11 TIFF จาก inputs-next และ metadata/exporter เดิม 3 ไฟล์; ดึงเฉพาะ XML metadata 475 products เพื่อตรวจ provider ใหม่ (26,254,799 bytes). รวมหลักฐาน 22,182 records โดยไม่นับ 489 reused/auxiliary records เป็นไฟล์ใน delivery ใหม่. ไม่ดาวน์โหลดภาพดาวเทียมเพิ่มและไม่ commit raw TIFF/XML.

## 2. Archive integrity
ZIP_COUNT=0; ZIP_VALID=0; ZIP_CORRUPT=0. TIFF ใหม่ 20,719 อ่านผ่านทั้งหมด. test_B04.tif ไม่มี registry/month/product mapping จึง HOLD_UNASSIGNED_SOURCE และไม่เป็น observation.

## 3. Scene completeness
Delivery ใหม่มี 1,887 representations: ครบ 11 bands 1,878 / partial 9. Planetary Computer 1,877; Earth Search 10. เมื่อรวม scene เดิมที่ใช้ประกอบ มี 1,888 representations: complete 1,879 / partial 9. Profiles 481 (PC475 / ESใหม่5 / ESเดิม1); ผูก metadata ได้ 1,883 scenes. ES partial 5 scenes ไม่มี saved STAC และถูกถือไว้.

## 4. Registry/PDD scope reconciliation
ยังมี registry 210 identities และ PDD22 เป็น optional scope. Scene manifests: REGISTRY_CONTAINED=1,789; UNKNOWN/held edge-or-partial footprint=99; PDD_ONLY=0. มี 1,667 complete sources ที่เลือกได้หลังตรวจ scope/product/dedup. ทุก band ที่ใช้ต้องครอบคลุม full registry อย่างน้อย99.9%. Native 10m/20m crop edges ต่างกันได้เฉพาะเมื่อ integer window ตรง original STAC grid/CRS/shape/dtype. Partial registry rasters ไม่ถูกนำเข้า.

## 5. Missing observation reconciliation
ก่อนรอบนี้ขาด249ช่อง. ผล: ACCEPTED=1; NO_CLEAR_SCENE=240; LOW_COVERAGE=5; NO_COMPLETE_SOURCE=3. ตอนนี้ขาด248ช่อง. Three source-absent requests คือ registry70/2023-09,106/2025-09,50/2026-08; downloader เกิด search timeout. ไม่มี saved query/page/rejection logs จึงไม่ยืนยันว่าค้นทุก provider ครบแล้ว. ไม่มี nearest-month substitution หรือ synthetic pixels.

## 6. Observations actually accepted
**99-VSD (registry131), กันยายน2566/2023-09: coverage7.52%**, observed_monthly_composite. ใช้ exact-month sources สอง acquisition:
- Earth Search C1 เดิม: S2A_MSIL2A_20230923T033541_N0509_R061_T47NMJ_20230923T075900, coverage4.07%.
- Planetary Computer ใหม่: S2B_MSIL2A_20230918T033539_N0510_R061_T47NNJ_20241013T024531, coverage3.46%.

รวม valid pixels248/3296=7.52427%; ทุก pixel ที่แสดงอยู่ใน registry polygon. ภาพใหม่เพียงชุดเดียวไม่ถึง5%; การรวมกับข้อมูลเดิมที่มี metadata-corrected native encoding ช่วยเติมช่องนี้จริง. Legacy DN/10000 ไม่ถูกนำมารวม. รายงานผู้ส่ง6.77%ไม่ถูกใช้เป็นค่าของแอป.

ตรวจ exact product XML475รายการ: BOA quantification10000, spectral additive offset−1000, nodata0. Per-band scalingทำครั้งเดียวหลังmasknodata; SCL categorical. PC/ES same-product82bandpairs มี raw DN และnodata masksเท่ากันทุกpixel รวม originalCOGที่มีscale/offsettags. [Microsoft อธิบาย native offset](https://github.com/microsoft/PlanetaryComputerExamples/blob/main/datasets/sentinel-2-l2a/baseline-change.ipynb); [Copernicus อธิบาย L2A encoding](https://sentiwiki.copernicus.eu/web/s2-products).

เลือกหนึ่ง verified product ต่อacquisitionด้วยhighest baseline/latest processing date/native grid โดยเก็บ111alternative representationsไว้เป็น HOLD_REPROCESSING_ALTERNATIVE และ4equivalent copiesไว้ในmanifest. ไม่อ้างว่า reprocessing pixels เท่ากันหรือใช้ acquisitionซ้ำ. For131, older18Sep N0509ให้0clear; N0510ให้3.46%. ทดสอบอีกห้า nonzero source slotsรวมข้อมูลnativeเดิมแล้วยังต่ำกว่า5%.

## 7. Files generated
เพิ่ม RGB1ภาพและNDVI1ภาพที่ data/plots/131/*_2023-09.png;173×177RGBA. Observations2,271→2,272; imagery4,542→4,544. Refreshเฉพาะ timeseries/metadataของช่อง131และQAช่องเดียว. จาก9,192ไฟล์เดิม มี9,189byte-identical; อีก3ไฟล์JSONแก้เท่าที่จำเป็น;เพิ่ม2PNG;ไม่มี deletion. ทุก2,271 usable observationsเดิมและ4,542ภาพเดิมคงเดิม. UI,slider,basemapและcalibrationเดิมคงเดิม.

## 8. QA summary
ช่องใหม่ยัง **INSUFFICIENT** เพราะcoverageต่ำกว่า95%; เก็บ NATIVE_MULTI_PROVIDER_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING. เปิดดูภาพได้แต่ไม่ใช้เป็นผลเปลี่ยนแปลงทั้งแปลง. QAอื่น2,519รายการคงเดิม. Summary: CLEAR1759 / INSUFFICIENT699 / RADIOMETRY_REVIEW13 / ATMOSPHERE_REVIEW29 / VISUAL_REVIEW16 / TIDE_WATER_REVIEW4. Newfamilyไม่เปลี่ยน legacy/C1 water references.

## 9. Tests
Python100 regressions, Node43 tests, Chromium16checks, source/catalog audits, five-batch manifest61,968sourceevidence records, QA byte-identical rebuild, JSsyntaxและgitdiff checksผ่าน. Browserตรวจภาพexact-monthทุก43accepted slotsของPR รวมช่องใหม่ และbefore/after drag/keyboard/left-right pixels/pan/zoom/basemap/boundary/mobile. ตรวจsourceซ้ำ21,693ไฟล์และXML475ไฟล์:ไม่มีการเปลี่ยนแปลง. รันซ้ำ --apply:เพิ่ม0observationsและ9,194ไฟล์ของแอปคงเดิมทุกbyte.

## 10. Branch / PR / SHA
Branch: feat/local-satellite-ingest-20261004. อัปเดต [PR13](https://github.com/saratchai1/prasae/pull/13) เข้า gh-pages;ไม่ merge. Application baselineก่อนรอบนี้007cbbd82c5f3935fdcdf15ec3975b68116abacd. FinalheadและGitHubCIอยู่ในPR. รวมPRเติม43observationsและ86RGB/NDVIimagesจากoriginalbaseline2229.

## 11. Remaining blockers
248ช่องยังไม่มี usable compositeจากข้อมูลที่ตรวจ:240no-clear,5ต่ำกว่า5%,3ไม่มีlocalsourceหลังsearchtimeout. ไม่มีหลักฐานexhaustive searchทุกprovider. Partial9scenesยังไม่ครบ;5ไม่มีSTAC. B08repairของ131/2025-09exact productยังไม่มา;86/2025-09มีcomplete native productsแต่gridต่างจากoldrepair specification จึงเป็นalternative productและcanonicalcoverage0 ไม่ใช่exact-gridrepair. Native/legacy harmonizationยังpending;ไม่ได้สรุป change metricเพิ่ม.
