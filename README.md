# Prasae Mangrove Monitoring

Dashboard สำหรับติดตามแปลงฟื้นฟูป่าชายเลนด้วย **Sentinel-2 L2A จำนวน 12 observation/composite dates** และขอบเขตแปลงจาก KMZ/GeoJSON

## หลักการข้อมูลปัจจุบัน

- ใช้ 12 ช่วงเวลาเท่านั้น: `2023-09`, `2023-12`, `2024-03`, `2024-06`, `2024-09`, `2024-12`, `2025-03`, `2025-06`, `2025-09`, `2025-12`, `2026-03`, `2026-08`
- ไม่มีการสร้างภาพของเดือนที่ไม่มีจริงด้วย nearest-date substitution
- ไม่มี linear interpolation เพื่อทำให้ดูเหมือนมีข้อมูลรายเดือน 36 เดือน
- ไม่มี synthetic/fallback NDVI
- ถ้าไม่มีข้อมูลที่ผ่าน QA จะบันทึก `no_data` หรือ `insufficient_clear_pixels`
- ค่าที่เคยเรียกว่า Canopy Cover เปลี่ยนเป็น **Vegetation Coverage Proxy** ซึ่งนิยามเป็นสัดส่วนพิกเซลในขอบเขตแปลงที่ `NDVI > 0.25`

## การแสดงแผนที่

Layer stack ของ viewer คือ:

1. **Esri World Imagery** เป็น basemap ถาวร
2. **Sentinel-2 RGB หรือ NDVI** เป็น PNG โปร่งใสที่มีข้อมูลเฉพาะภายใน polygon ของแปลง
3. **Plot boundary** เป็นเส้น outline เท่านั้น ไม่มีสี fill ทับภาพ

เมื่อเปลี่ยน observation date ภาพ Sentinel-2 จะ crossfade ขณะที่ Esri basemap อยู่คงเดิม

Compare view ใช้ Leaflet map เดียวกันและ geographic bounds เดียวกันสำหรับ Before/After ไม่ใช้ `<img>` + SVG ที่มีความเสี่ยงเรื่อง aspect-ratio alignment

## Canonical processing pipeline

ใช้ไฟล์เดียวเป็น source of truth:

```bash
python extract_kmz_plots.py
python process_verified_12_dates.py
```

Dependencies:

```bash
pip install -r requirements-verified.txt
```

Pipeline ใช้ Sentinel-2 L2A จาก Microsoft Planetary Computer STAC, reproject ทุก scene ลง explicit WGS84 raster grid เดียวกัน, cloud-mask ด้วย SCL, ทำ monthly median composite เฉพาะเดือนที่ประกาศ และ clip ด้วย exact Polygon/MultiPolygon geometry รวมถึง polygon holes

Outputs:

```text
data/
├── plots_catalog.json
├── plots.geojson
├── timeseries_verified_12.json
└── plots/<plot_id>/
    ├── rgb_YYYY-MM.png
    ├── ndvi_YYYY-MM.png
    └── metadata.json
```

`metadata.json` เก็บ scene IDs, acquisition timestamps, catalog cloud cover, clear-pixel QA, source และกฎการประมวลผลเพื่อ audit ได้

## Data integrity behavior

หน้าเว็บอ่าน `data/timeseries_verified_12.json` เท่านั้นสำหรับ KPI/กราฟ/ตาราง ถ้าไฟล์นี้ยังไม่มีข้อมูล verified หน้าเว็บยังเปิดดูภาพ 12 dates ที่มีอยู่ได้ แต่จะแสดงค่าทางสถิติเป็น `—` แทนการ fallback ไปใช้ชุดข้อมูล interpolated เดิม

## GitHub Pages

Repository ใช้ GitHub Pages แบบ branch/legacy deployment ที่ตั้งไว้ใน repository settings จึงไม่เก็บ workflow deploy ซ้ำที่พยายาม deploy `main` เข้า protected `github-pages` environment

สำหรับ rebuild ชุดข้อมูล 12 dates มี workflow manual: `.github/workflows/rebuild-verified-data.yml`
