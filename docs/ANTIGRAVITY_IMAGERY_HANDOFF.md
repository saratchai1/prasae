# งานจัดหาข้อมูลดาวเทียมสำหรับ Prasae — ส่งให้ Antigravity

## เป้าหมายและขอบเขต
ขยายเว็บเดิมที่มีกราฟ แผนที่ GIS ภาพดาวเทียม ก่อน–หลัง Spectral Studio และ CSV ให้รองรับทะเบียน 210 แปลงใน workspace เดียวกัน ไม่สร้างหน้าแปลงทั่วไปแบบลดฟีเจอร์อีก งานเอกสารนี้เฉพาะการจัดหาข้อมูลต้นฉบับ/เตรียมอินพุต ไม่อนุญาตให้แก้ UI, merge, deploy หรือเปลี่ยนผลวิเคราะห์เดิม

Repo: `saratchai1/prasae`.
ข้อมูลต้นทางอ้างอิง commit `19ba56139325e977967164d7a459dadb4cbc47bd`.
ไฟล์ทะเบียน: `data/plots_catalog.json`; ผลเดิม: `data/timeseries_verified_12.json`.
ขอบเขต PDD: `data/pdd22/plots_catalog.json`; การเลือก scene: `data/pdd22_satellite/plots/<code>/metadata.json`.

**210 แปลงในทะเบียนมี 22 รหัส PDD อยู่ด้วย ไม่ใช่ 210+22 แปลงใหม่** ขอบเขตทะเบียนกับพื้นที่เข้าร่วม PDD อาจต่างกันมาก ให้ใช้ `scope` และ `geometry_id` ของแต่ละคำขอ ห้ามนำภาพที่ตัดตามขอบเขต PDD ไปแสดงเต็มขอบเขตทะเบียนหรือกลับกัน

## ไฟล์ที่ต้องอ่าน
- `inventory-summary.json`: จำนวนตามหลักฐานใน repository
- `plot-month-inventory.json`: ครบทุกแปลง–เดือน พร้อม scope, boundary reference, source status, coverage, known scene IDs และไฟล์ที่ขาด
- `unusable-periods.json`: ไม่มี observation ใช้งานได้ในชุดที่ commit; **ไม่ใช่หลักฐานว่า provider ไม่มี scene**
- `low-coverage.json`: มีภาพแต่ coverage ไม่ถึงเกณฑ์เดิม
- `review-candidates.json`: heuristic ขอให้ตรวจเมฆ/หมอก/น้ำหรือสภาพผิวพื้น ไม่ใช่ยืนยันว่าเป็นเมฆ
- `multiband-to-build.json`: ชุด browser 10 bands ยังไม่ครบ; อาจต้องดึง raw bands ของ scene ที่มีอยู่แล้ว ไม่จำเป็นต้องหา acquisition ใหม่
- `boundaries.geojson`: geometry อ้างอิงตาม scope
- `known-scene-ids.txt`: scene IDs รวมแบบไม่ซ้ำ เพื่อลดการดาวน์โหลด tile ซ้ำ

## ลำดับงาน
1. ตรวจ inventory แล้ว resolve `known_selected_scene_ids` จากแค็ตตาล็อกต้นทางก่อน จัดกลุ่ม scene/tile/date เพื่อใช้ข้อมูลเดียวกันกับหลายแปลงอย่างถูกขอบเขต ห้ามดาวน์โหลดข้อมูลชุดเดิมซ้ำทุกแปลง
2. จัดหาช่วง มี.ค. 2567, มี.ค. 2568, มี.ค. 2569 ก่อน ตามด้วย ส.ค. 2569 แล้วช่วงที่เหลือใน 12 เดือนที่ระบุ ใช้เดือนจริง ไม่ใช้ภาพล่าสุดแทน
3. ดึง Sentinel-2 L2A/BOA bands ต้นฉบับ: `B02 B03 B04 B05 B06 B07 B08 B8A B11 B12` และ `SCL`. เก็บ STAC item JSON, asset URL, acquisition datetime UTC, satellite, MGRS tile, processing baseline, projection/grid, nodata, scale/offset/quantification และ checksum ไว้ครบ
4. **ไม่ใช้ RGB screenshot, Google Earth screenshot, ภาพพื้นหลัง Esri หรือ PNG 8-bit เป็นอินพุตวิทยาศาสตร์** PNG ที่ repo ใช้เป็นภาพแสดงผล ค่าดัชนีต้องคำนวณจาก scientific reflectance ที่ถอด scale/offset ตาม metadata ต้นทางจริง
5. ถ้ามี scene ID เดิมที่ใช้ได้ ให้ดึง bands จาก scene เดิมก่อนเพื่อไม่ให้ RGB/NDVI/FCD/Spectral เป็นคนละ acquisition. ถ้า scene เดิมมีปัญหา ให้รายงาน candidate ใหม่ในเดือนเดียวกันพร้อมหลักฐาน แต่ห้ามแทนที่ source และตัวเลขเดิมเงียบ ๆ
6. ตรวจเมฆและเงาใน polygon จริง ใช้ SCL ร่วมกับดูภาพ/ข้อมูลเสริมตามที่มี แยกความสว่างจากน้ำ/ตะกอน/ดิน/แสงสะท้อนออกจากเมฆ ห้ามใช้ catalog cloud % ทั้ง tile ฟันธง cloud % ภายในแปลง และห้ามถือ heuristic เป็น ground truth
7. ทุกภาพก่อน–หลังต้องจัดลง CRS, extent, transform, width และ height เดียวกันใน scope เดียวกัน รักษาความละเอียดดั้งเดิม 10/20 เมตรและรายงานวิธี resample. mask ประเภทหมวดหมู่ใช้ nearest-neighbour. การขยายภาพไม่เพิ่ม spatial resolution จริง
8. ถ้าหาภาพใช้งานได้ในเดือนนั้นไม่ได้ ให้คืน `NO_USABLE_SCENE` พร้อม query, candidate IDs, เหตุผลคัดออก, coverage และข้อผิดพลาดเครือข่ายที่แยกจากไม่มี scene. ภาพเดือนอื่นส่งได้เป็นข้อเสนอทางเลือก แต่ห้ามใช้แทนเดือนที่ขอโดยไม่ได้อนุมัติ

## รูปแบบส่งกลับ
ส่งเป็น ZIP ที่มี `manifest.json`, `source-items/`, `inputs/` หรือ URL ต้นทางที่ดึงได้ และ `qa/`.
ต่อ scene ต้องมีต้นฉบับ GeoTIFF/COG/JP2 ที่มี georeference และ metadata หรือ URL เดิมที่อ้างอิงได้ถาวร; signed URLs ให้ระบุวันหมดอายุ ไม่ฝัง credentials ในไฟล์หรือ commit.
ต่อ request ให้คืน `request_id`, `geometry_id`, `scope`, สถานะ `EXISTING_SCENE_RESOLVED / NEW_CANDIDATE / NO_USABLE_SCENE / ACCESS_ERROR`, selected scene IDs, acquisition datetime, asset files/URLs, hashes, native resolution, grid, coverage และคำอธิบาย QA.
ถ้าทำ composite หลายวัน ให้เก็บรายชื่อ scene ทุกตัวและวิธี composite รวมถึง valid/contributor mask ห้ามเรียกว่าเป็นภาพถ่ายวันเดียว

## ข้อห้าม
- ไม่แก้ threshold หรือ calibration เพื่อให้ตัวเลขดูดี
- ไม่ตั้งชื่อ Green Cover Proxy ให้เป็น FCD
- ไม่สรุปว่ามีเมฆหรือน้ำท่วมจากค่า brightness เพียงอย่างเดียว
- ไม่ interpolate เดือนที่หาย ไม่สร้างภาพหรือผลแทน
- ไม่อ้างว่าดึงภาพไม่สำเร็จ = ไม่มีภาพดาวเทียม
- ไม่ merge/deploy หรือเขียนทับ production data

**การได้ raw bands ครบเป็นเพียงอินพุตสำหรับประมวลผล ไม่ได้ยืนยัน FCD ของทุกจังหวัดโดยอัตโนมัติ งานสอบเทียบและ validation ต้องทำแยกจากการหาภาพ**
