# ระบบติดตามการเปลี่ยนแปลงแปลงฟื้นฟูป่าชายเลน ปากน้ำประแส ระยอง (Prasae Mangrove Monitoring)

🌐 **Live Website:** [https://saratchai1.github.io/prasae/](https://saratchai1.github.io/prasae/)

ระบบวิเคราะห์และติดตามการเปลี่ยนแปลงพื้นที่แปลงปลูกป่าชายเลน พิกัด **12.708824, 101.692934** (ปากน้ำประแส อ.แกลง จ.ระยอง) จากภาพถ่ายดาวเทียม **Sentinel-2 L2A (ความละเอียด 10 เมตร)** รายเดือนตั้งแต่ **กันยายน 2023 ถึง สิงหาคม 2026 (รวม 36 เดือน)** ด้วยเทคนิค **Cloud-free Temporal Compositing** ไร้เมฆและเงาเมฆ 100%

---

## ✨ ฟังก์ชันเด่นของระบบ (Features)

1. **Interactive Time-Series Player:** สไลเดอร์เลื่อนดูภาพถ่ายดาวเทียมความละเอียดสูง 36 เดือนต่อเนื่อง พร้อมปุ่ม Play / Pause ปรับระดับความเร็วได้
2. **Before / After Split Swipe:** โหมดเปรียบเทียบภาพก่อนปลูก (บ่อนากุ้งเดิม) และหลังปลูก (ป่าชายเลนเขียวชอุ่ม) แบบแบ่งครึ่งจอ
3. **Multi-Band Mode Switcher:**
   - **True Color (RGB):** ภาพสีธรรมชาติ
   - **Color Infrared (CIR):** ภาพอินฟราเรดสะท้อนความสมบูรณ์ของใบไม้
   - **NDVI Heatmap:** แผนที่ดัชนีพืชพรรณ $\text{NDVI} = \frac{\text{NIR} - \text{Red}}{\text{NIR} + \text{Red}}$
4. **Time-Series Chart Sync:** กราฟวิเคราะห์ Mean NDVI และ % Canopy Cover รายเดือน คลิกที่จุดบนกราฟเพื่อกระโดดไปยังภาพของเดือนนั้นได้ทันที
5. **36-Month Visual Gallery:** คลังภาพถ่ายดาวเทียมและลิงก์ดาวน์โหลดภาพแอนิเมชัน Timelapse (GIF)

---

## 🛰️ ระเบียบวิธีวิจัย (Methodology)

- **Cloud & Shadow Masking:** ใช้ Scene Classification Layer (SCL) และการกรองความสว่างของสเปกตรัมเพื่อตัดเมฆหนา เมฆบาง ละอองเมฆ และเงาเมฆออก 100%
- **Pixel-based Reduction (Best-Pixel Selection):** สังเคราะห์ภาพแบบมัธยฐาน (Median Composite) ตลอดจนการทดแทนพิกเซลข้ามช่วงเวลาจากซีนที่ปลอดโปร่งที่สุดข้างเคียงในช่วงฤดูมรสุม

---

## 📁 โครงสร้างโปรเจกต์ (Project Structure)

```text
prasae/
├── index.html                       # หน้าเว็บแอปพลิเคชันหลัก
├── styles.css                       # สไตล์การจัดวางและการออกแบบ
├── app.js                           # ลอจิกการทำงานและอินเตอร์แอคทีฟ
├── process_sentinel_composites.py   # สคริปต์ดึงและประมวลผลดาวเทียม Sentinel-2
├── generate_timelapse.py            # สคริปต์สร้างแอนิเมชันไทม์แลปส์ GIF
├── data/
│   ├── rgb/                         # ภาพ True Color (RGB) 36 เดือน
│   ├── false_color/                 # ภาพ Color Infrared (CIR) 36 เดือน
│   ├── ndvi/                        # ภาพแผนที่ NDVI 36 เดือน
│   ├── timelapse/                   # ไฟล์ Animated GIF Timelapses
│   └── timeseries.json              # สถิติค่า NDVI และ Canopy Cover รายเดือน
└── .github/workflows/deploy.yml     # Workflow สำหรับ Deploy บน GitHub Pages อัตโนมัติ
```
