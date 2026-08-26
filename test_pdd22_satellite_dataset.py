#!/usr/bin/env python3
"""Comprehensive Automated Validation Suite for PDD22 Sentinel-2 Dataset."""

import json
from pathlib import Path
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDD_CATALOG = DATA_DIR / "pdd22" / "plots_catalog.json"
SATELLITE_DIR = DATA_DIR / "pdd22_satellite"
PLOTS_DIR = SATELLITE_DIR / "plots"

EXPECTED_CODES = [
    "18-VSD", "19-VSD", "40-VSD", "41-VSD", "42-VSD", "43-VSD", "44-VSD",
    "66-VSD", "85-VSD", "86-VSD", "87-VSD", "88-VSD", "89-VSD", "90-VSD",
    "93-VSD", "94-VSD", "95-VSD", "97-VSD", "98-VSD", "99-VSD", "100-VSD", "102-VSD"
]

EXPECTED_MONTHS = [
    "2023-09", "2023-12",
    "2024-03", "2024-06", "2024-09", "2024-12",
    "2025-03", "2025-06", "2025-09", "2025-12",
    "2026-03", "2026-08",
]

SPECIFIC_AREAS = {
    "87-VSD": 92.92,
    "88-VSD": 257.66,
    "93-VSD": 82.63,
    "94-VSD": 140.87,
    "95-VSD": 200.38,
}


def test_catalog_integrity():
    print("Testing PDD Catalog Integrity...")
    with open(PDD_CATALOG, encoding="utf-8") as f:
        plots = json.load(f)
    assert len(plots) == 22, f"Expected 22 plots, got {len(plots)}"
    
    total_area = round(sum(p["area_rai"] for p in plots), 2)
    assert total_area == 6775.53, f"Expected total area 6775.53 rai, got {total_area}"
    
    codes = [p["code"] for p in plots]
    assert len(codes) == len(set(codes)) == 22, "Duplicate plot codes found"
    assert codes == EXPECTED_CODES, "Plot code sequence mismatch"
    
    for code, exp_area in SPECIFIC_AREAS.items():
        p = next(x for x in plots if x["code"] == code)
        assert p["area_rai"] == exp_area, f"{code} area {p['area_rai']} != {exp_area}"
    print("✓ Catalog assertions passed (22 plots, 6775.53 rai total).")


def test_satellite_dataset_integrity(available_codes: list[str] | None = None):
    print("\nTesting Satellite Dataset Integrity...")
    with open(PDD_CATALOG, encoding="utf-8") as f:
        pdd_cat = {p["code"]: p for p in json.load(f)}
        
    codes_to_test = available_codes or EXPECTED_CODES
    
    for code in codes_to_test:
        plot_dir = PLOTS_DIR / code
        assert plot_dir.exists(), f"Plot directory missing: {plot_dir}"
        
        meta_path = plot_dir / "metadata.json"
        assert meta_path.exists(), f"metadata.json missing for {code}"
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
            
        # Check metadata fields
        assert meta["plot_code"] == code
        assert meta["pdd_area_rai"] == pdd_cat[code]["area_rai"]
        grid = meta["grid"]
        assert "width" in grid and "height" in grid and "resolution_m" in grid
        w, h = grid["width"], grid["height"]
        
        inside_count = meta["inside_pixel_count"]
        assert inside_count <= w * h, f"{code}: inside_count ({inside_count}) > total grid ({w*h})"
        
        rules = meta.get("rules", {})
        assert rules.get("adjacent_month_fallback") is False, "adjacent_month_fallback must be False"
        assert rules.get("interpolation") is False, "interpolation must be False"
        assert rules.get("synthetic_pixels") is False, "synthetic_pixels must be False"
        
        obs_list = meta["observations"]
        assert len(obs_list) == 12, f"{code}: expected 12 observations, got {len(obs_list)}"
        obs_months = [obs["month"] for obs in obs_list]
        assert obs_months == EXPECTED_MONTHS, f"{code}: month mismatch {obs_months}"
        
        for obs in obs_list:
            m = obs["month"]
            m_dir = plot_dir / m
            assert m_dir.exists(), f"{code}/{m} folder missing"
            
            # Check image outputs
            rgb_p = m_dir / "rgb.png"
            ndvi_p = m_dir / "ndvi.png"
            mask_p = m_dir / "valid_mask.png"
            obs_p = m_dir / "observation_count.png"
            
            assert rgb_p.exists() and ndvi_p.exists() and mask_p.exists() and obs_p.exists(), f"Missing PNGs in {m_dir}"
            
            # Verify raster dimensions
            for img_p in [rgb_p, ndvi_p, mask_p, obs_p]:
                with Image.open(img_p) as im:
                    assert im.size == (w, h), f"{img_p} size mismatch {im.size} != {(w, h)}"
                
            # Verify math agreement
            valid_px = obs["valid_pixel_count"]
            inside_px = obs["inside_pixel_count"]
            cov_pct = obs["coverage_pct"]
            assert inside_px == inside_count
            assert valid_px <= inside_px, f"{code}/{m}: valid ({valid_px}) > inside ({inside_px})"
            calc_cov = round(valid_px / inside_px * 100.0, 2)
            assert abs(cov_pct - calc_cov) < 0.05, f"{code}/{m}: coverage_pct {cov_pct} != {calc_cov}"

            # Verify analysis mode semantics
            mode = obs["analysis_mode"]
            if mode == "single_scene_good":
                assert cov_pct >= 95.0
                assert len(obs["selected_scenes"]) == 1
                assert obs["number_of_contributing_scenes"] == 1
                assert obs["composite_method"] == "none"
            elif mode == "single_scene_partial":
                assert cov_pct < 95.0
                assert len(obs["selected_scenes"]) == 1
                assert obs["number_of_contributing_scenes"] == 1
                assert obs["composite_method"] == "none"
            elif mode == "same_month_multi_scene_composite":
                assert len(obs["selected_scenes"]) >= 2
                assert obs["number_of_contributing_scenes"] >= 2
                assert obs["composite_method"] == "median_clear_reflectance"
            elif mode == "no_data":
                assert valid_px == 0
                assert len(obs["selected_scenes"]) == 0
                assert obs["number_of_contributing_scenes"] == 0
                assert obs["composite_method"] == "none"
            else:
                assert False, f"Unknown analysis mode: {mode}"
            
            # Verify QA Status Semantics independently
            qa = obs["qa"]
            if qa == "GOOD":
                assert cov_pct >= 95.0
            elif qa == "PARTIAL":
                assert 50.0 <= cov_pct < 95.0
            elif qa == "LOW_QA":
                assert 5.0 <= cov_pct < 50.0
            elif qa == "NO_DATA":
                assert cov_pct < 5.0
            else:
                assert False, f"Unknown qa status: {qa}"
            # Verify exact test requirements
            for sc in obs.get("selected_scenes", []):
                assert "processing_baseline" in sc
                assert "dt_obj" not in sc

            
            # Verify scene datetimes are strictly within the declared month
            for sc in obs.get("scenes", []):
                dt_utc = sc.get("datetime_utc", "")
                if dt_utc and dt_utc != "N/A":
                    assert dt_utc.startswith(m), f"Scene {sc['id']} datetime {dt_utc} outside month {m}!"

    print(f"✓ All dataset integrity assertions passed for {len(codes_to_test)} plots!")



def test_global_artifacts():
    print("\nTesting Global Artifacts...")
    manifest_path = SATELLITE_DIR / "manifest.json"
    assert manifest_path.exists(), "manifest.json missing"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    assert manifest["plot_count"] == 22
    assert manifest["total_pdd_area_rai"] == 6775.53
    assert "pipeline_source_commit" in manifest
    assert "dataset_commit" in manifest
    assert "pipeline_file_sha256" in manifest
    assert "python_version" in manifest
    assert "dependency_versions" in manifest
    assert "processing_rules" in manifest
    
    report_path = SATELLITE_DIR / "coverage_report.csv"
    assert report_path.exists(), "coverage_report.csv missing"
    
    with open(report_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    assert len(lines) == 265, f"Expected 264 data rows + 1 header, got {len(lines)}"
    
    header = lines[0].strip().split(",")
    assert "plot_code" in header
    assert "month" in header
    
    from collections import Counter
    plot_idx = header.index("plot_code")
    month_idx = header.index("month")
    
    plot_counts = Counter()
    months_seen = set()
    
    for row in lines[1:]:
        cols = row.strip().split(",")
        plot_code = cols[plot_idx]
        month = cols[month_idx]
        
        assert plot_code in EXPECTED_CODES, f"Unexpected plot: {plot_code}"
        assert month in EXPECTED_MONTHS, f"Unexpected month: {month}"
        
        plot_counts[plot_code] += 1
        months_seen.add(month)
        
    assert len(plot_counts) == 22, f"Expected 22 unique plots, got {len(plot_counts)}"
    assert len(months_seen) == 12, f"Expected 12 unique months, got {len(months_seen)}"
    for p, c in plot_counts.items():
        assert c == 12, f"Expected exactly 12 rows for {p}, got {c}"
    
    print("✓ Global artifacts passed.")

if __name__ == "__main__":
    test_global_artifacts()
    test_catalog_integrity()
    # Check which plots exist
    existing = [d.name for d in PLOTS_DIR.iterdir() if d.is_dir() and d.name in EXPECTED_CODES]
    assert len(existing) == 22, f"Expected exactly 22 plot directories, found {len(existing)}"
    assert set(existing) == set(EXPECTED_CODES)
    test_satellite_dataset_integrity(existing)
