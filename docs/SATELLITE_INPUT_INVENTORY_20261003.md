# ผลตรวจไฟล์ดาวเทียมเพื่อส่งต่องานจัดหา

## ขอบเขตหลักฐาน
ข้อมูลอ้างอิง: `19ba56139325e977967164d7a459dadb4cbc47bd`.
ตรวจด้วย `tools/build_satellite_handoff.py` ที่ commit `5ffeb87bd0b3e6fcc0c99e40daa510f51ef22ed6`.
GitHub Actions run `37115952829`, inventory job `111182698584`: SUCCESS.
Artifact `11271940206`: `prasae-antigravity-satellite-handoff`, ZIP 848,001 bytes; SHA-256 `637c2f4a340dd9d4a402ab1075d8ec7a4bf014f3bcd6bde45e4388bb86ba4784`.

**ตรวจไฟล์และ metadata ที่ commit ใน repository เท่านั้น ยังไม่ได้ค้นหา provider/STAC ใหม่ในรอบนี้ จึงไม่ใช่รายการที่ยืนยันว่าไม่มีภาพดาวเทียมให้หา**

## จำนวนในขอบเขตทะเบียน 210 แปลง
หนึ่งรายการหมายถึงหนึ่งแปลงในหนึ่งเดือน ไม่ใช่หนึ่ง scene หรือหนึ่งไฟล์

| รายการ | จำนวน |
|---|---:|
| แปลง–เดือนทั้งหมด (210 × 12) | 2,520 |
| มี observation ตามสถานะใน source | 2,223 |
| ไม่มี observation ใช้งานได้ในชุดที่ commit | 297 |
| มี observation แต่ coverage ต่ำกว่า 95% | 417 |
| ถูก heuristic เดิมระบุให้ตรวจภาพเพิ่มเติม | 49 |
| source ระบุมี observation แต่ RGB/NDVI preview ที่คาดไว้หาย | 0 |
| ชุดแสดงผล 10 bands ครบในขอบเขตทะเบียน | 0 |
| มี browser band บางส่วน | 9 |
| มี scene IDs จาก source ให้ค้นหาต่อ | 2,254 |

หมวดมี overlap เช่น ชุด 10 bands ยังไม่ครบอาจเป็นช่วงที่มี RGB/NDVI อยู่แล้ว ห้ามรวมจำนวนหมวดเป็นจำนวนภาพที่ขาดใหม่
49 รายการเป็นคำขอให้ตรวจจาก heuristic ไม่ใช่เมฆที่ยืนยันแล้ว

## ชุด PDD 22 แปลง
มี 264 แปลง–เดือน, ผ่านเกณฑ์ observation coverage >=5% จำนวน 254, ไม่มี observation ใช้งานได้ 10 และมี browser 10-band packages อยู่ 257 ชุด (สามชุดมีข้อมูล pixel บางส่วนแต่ไม่ถึงเกณฑ์ observation ใช้งานได้). การมีไฟล์จึงไม่เท่ากับผ่าน QA

**22 รหัส PDD อยู่ในทะเบียน 210 แปลงแล้ว ไม่ใช่ 232 แปลงต่างกัน** แต่ขอบเขตพื้นที่เข้าร่วม PDD กับขอบเขตทะเบียนต้องเก็บแยก ไม่เอา raster คนละขอบเขตไปแทนกัน

## ตัวอย่างที่เกี่ยวข้อง
- `78-STC ภูเก็ต / 2025-03 / registry`: source ระบุ observed_monthly_composite, coverage 100%; มีทั้ง RGB และ NDVI. ปัญหาหน้าแสดงภาพไม่ใช่ผู้ใช้ยังไม่ได้ดาวน์โหลดภาพ. ยังไม่มีชุด browser 10 bands สำหรับขอบเขตทะเบียนนี้
- `18-VSD ชุมพร / 2024-06 / pdd`: source ระบุ NO_DATA, coverage 0%; ไฟล์ PNG มีอยู่แต่ไม่ใช่หลักฐานว่ามี observation ใช้งานได้; ไม่มี selected scene IDs ใน source สำหรับช่วงนี้
- `87-VSD สมุทรสงคราม / 2025-09 / registry`: มีภาพ, coverage 100%, heuristic ระบุ TIDE_WATER_REVIEW; ต้องตรวจเหตุ ไม่ใช่เหมาว่าไฟล์หายหรือเป็นเมฆแน่นอน
- `97-VSD กระบี่ / 2025-06 / registry`: มีภาพ, coverage 98.04%, heuristic ระบุ ATMOSPHERE_REVIEW; ต้องตรวจภาพต้นฉบับและ mask ต่อ

## ส่งต่อให้ Antigravity
ใน ZIP มี README ภาษาไทย, summary, inventory รายแปลง–เดือน, คิวไม่มี observation, คิว coverage ต่ำ, คิวภาพที่ต้องตรวจ, คิว 10-band packages ที่ยังไม่ครบ, GeoJSON ขอบเขตตาม scope และ selected scene IDs ไม่ซ้ำรวม 791 IDs

ให้ resolve selected scene IDs เดิมก่อน ดึง scientific Sentinel-2 L2A/BOA `B02 B03 B04 B05 B06 B07 B08 B8A B11 B12 + SCL` พร้อม metadata, scale/offset, projection/grid และ checksum. ไม่เอา PNG 8-bit หรือภาพหน้าจอเป็นอินพุตคำนวณ. ใช้ acquisition ใหม่เฉพาะเมื่อเดิมไม่มี/ไม่ผ่านการตรวจ และรายงานการเปลี่ยนแยกชัดเจน. ไม่แทนเดือนอื่นเอง

การจัดชุดรายการนี้ไม่ได้แก้หรือ deploy เว็บ production และไม่ได้ประมวลผล FCD ใหม่ การขยาย workspace เดียวเป็นงานบน branch `feat/unified-210-workspace-20261003` แยกจากงานจัดหาภาพนี้
