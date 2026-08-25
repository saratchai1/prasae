"""Configuration for the 22-plot Group 2 PDD satellite screening workflow.

The areas below are the *participating project areas* from PDD Table 1-1 / 1-8,
not the larger allocated areas. These values are authoritative for reporting area in rai.
"""

from __future__ import annotations

PDD_TOTAL_PROJECT_AREA_RAI = 6775.53
PDD_BASELINE_TREE_CARBON_TCO2E = 362_962.81
PDD_INCREMENT_TCO2E_PER_RAI_YEAR = 9.40

FCD_LOW_MAX = 30.0
FCD_HIGH_MIN = 65.0

# Same-month observations reduce seasonal bias. 2566 is the user's satellite reference year.
OBSERVATION_MONTHS = [(2023, 3), (2024, 3), (2025, 3), (2026, 3)]

PDD22_PLOTS = [
    {"order": 1, "code": "18-VSD", "province": "ชุมพร", "coast": "อ่าวไทย", "allocated_area_rai": 2007.76, "project_area_rai": 1909.77},
    {"order": 2, "code": "19-VSD", "province": "ชุมพร", "coast": "อ่าวไทย", "allocated_area_rai": 324.13, "project_area_rai": 316.38},
    {"order": 3, "code": "40-VSD", "province": "พังงา", "coast": "อันดามัน", "allocated_area_rai": 289.11, "project_area_rai": 277.33},
    {"order": 4, "code": "41-VSD", "province": "พังงา", "coast": "อันดามัน", "allocated_area_rai": 181.50, "project_area_rai": 178.92},
    {"order": 5, "code": "42-VSD", "province": "พังงา", "coast": "อันดามัน", "allocated_area_rai": 228.88, "project_area_rai": 223.01},
    {"order": 6, "code": "43-VSD", "province": "พังงา", "coast": "อันดามัน", "allocated_area_rai": 123.91, "project_area_rai": 122.82},
    {"order": 7, "code": "44-VSD", "province": "พังงา", "coast": "อันดามัน", "allocated_area_rai": 223.49, "project_area_rai": 221.07},
    {"order": 8, "code": "66-VSD", "province": "ตรัง", "coast": "อันดามัน", "allocated_area_rai": 97.17, "project_area_rai": 97.17},
    {"order": 9, "code": "85-VSD", "province": "สตูล", "coast": "อันดามัน", "allocated_area_rai": 607.58, "project_area_rai": 599.58},
    {"order": 10, "code": "86-VSD", "province": "สตูล", "coast": "อันดามัน", "allocated_area_rai": 1162.47, "project_area_rai": 1141.96},
    {"order": 11, "code": "87-VSD", "province": "สมุทรสงคราม", "coast": "อ่าวไทย", "allocated_area_rai": 101.62, "project_area_rai": 92.92},
    {"order": 12, "code": "88-VSD", "province": "ปัตตานี", "coast": "อ่าวไทย", "allocated_area_rai": 307.41, "project_area_rai": 257.66},
    {"order": 13, "code": "89-VSD", "province": "ปัตตานี", "coast": "อ่าวไทย", "allocated_area_rai": 25.72, "project_area_rai": 25.72},
    {"order": 14, "code": "90-VSD", "province": "ปัตตานี", "coast": "อ่าวไทย", "allocated_area_rai": 60.65, "project_area_rai": 22.42},
    {"order": 15, "code": "93-VSD", "province": "ปัตตานี", "coast": "อ่าวไทย", "allocated_area_rai": 82.63, "project_area_rai": 82.63},
    {"order": 16, "code": "94-VSD", "province": "ปัตตานี", "coast": "อ่าวไทย", "allocated_area_rai": 140.87, "project_area_rai": 140.87},
    {"order": 17, "code": "95-VSD", "province": "ปัตตานี", "coast": "อ่าวไทย", "allocated_area_rai": 200.38, "project_area_rai": 200.38},
    {"order": 18, "code": "97-VSD", "province": "กระบี่", "coast": "อันดามัน", "allocated_area_rai": 185.58, "project_area_rai": 184.64},
    {"order": 19, "code": "98-VSD", "province": "กระบี่", "coast": "อันดามัน", "allocated_area_rai": 153.33, "project_area_rai": 150.95},
    {"order": 20, "code": "99-VSD", "province": "กระบี่", "coast": "อันดามัน", "allocated_area_rai": 205.78, "project_area_rai": 205.78},
    {"order": 21, "code": "100-VSD", "province": "กระบี่", "coast": "อันดามัน", "allocated_area_rai": 291.51, "project_area_rai": 291.51},
    {"order": 22, "code": "102-VSD", "province": "ภูเก็ต", "coast": "อันดามัน", "allocated_area_rai": 36.25, "project_area_rai": 32.04},
]

PDD_BASELINE_FCD_BY_PROVINCE = {
    "สมุทรสงคราม": {"total": 92.92, "high": 78.88, "medium": 11.52, "low": 1.86, "bare_error": 0.66},
    "ชุมพร": {"total": 2226.15, "high": 1280.30, "medium": 741.81, "low": 204.04, "bare_error": 0.00},
    "ปัตตานี": {"total": 729.68, "high": 462.46, "medium": 222.53, "low": 41.54, "bare_error": 3.15},
    "สตูล": {"total": 1741.54, "high": 1422.03, "medium": 283.72, "low": 26.41, "bare_error": 9.38},
    "พังงา": {"total": 1023.15, "high": 776.68, "medium": 234.01, "low": 9.32, "bare_error": 3.14},
    "ภูเก็ต": {"total": 32.04, "high": 16.50, "medium": 8.49, "low": 2.77, "bare_error": 4.28},
    "กระบี่": {"total": 832.88, "high": 513.21, "medium": 276.64, "low": 36.07, "bare_error": 6.96},
    "ตรัง": {"total": 97.17, "high": 5.42, "medium": 44.57, "low": 47.05, "bare_error": 0.13},
}


def validate_config() -> None:
    total = round(sum(p["project_area_rai"] for p in PDD22_PLOTS), 2)
    if total != PDD_TOTAL_PROJECT_AREA_RAI:
        raise ValueError(f"PDD22 project-area total mismatch: {total} != {PDD_TOTAL_PROJECT_AREA_RAI}")
    codes = [p["code"] for p in PDD22_PLOTS]
    if len(codes) != 22 or len(set(codes)) != 22:
        raise ValueError("PDD22 must contain exactly 22 unique plot codes")


validate_config()
