#!/usr/bin/env python3
"""
Download real Sentinel-2 L2A cloud-free composite imagery for all 210 plots 
using Google Earth Engine (GEE).
Produces RGB + NDVI PNGs per plot per milestone month.
"""

import os
import json
import time
import requests
import calendar
import traceback
import ee
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── Configuration ───────────────────────────────────────────────────────────

GEE_PROJECT = 'hatyai-480206'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PLOTS_DIR = os.path.join(DATA_DIR, "plots")
CATALOG_PATH = os.path.join(DATA_DIR, "plots_catalog.json")

# 12 milestone months (quarterly + start/end)
MILESTONE_MONTHS = [
    (2023, 9), (2023, 12), (2024, 3), (2024, 6),
    (2024, 9), (2024, 12), (2025, 3), (2025, 6),
    (2025, 9), (2025, 12), (2026, 3), (2026, 8),
]

BUFFER_DEG = 0.003  # ~330m buffer around plot bounds
MAX_WORKERS = 5     # Avoid hitting GEE rate limits

# ─── GEE Initialization ──────────────────────────────────────────────────────

print(f"Initializing Earth Engine with project '{GEE_PROJECT}'...")
try:
    ee.Initialize(project=GEE_PROJECT)
except Exception as e:
    print(f"Failed to initialize Earth Engine: {e}")
    exit(1)

# ─── GEE Functions ───────────────────────────────────────────────────────────

def mask_s2_clouds(image):
    """Masks clouds in Sentinel-2 using the SCL band."""
    scl = image.select('SCL')
    # 3=shadow, 8=med cloud, 9=high cloud, 10=cirrus, 11=snow
    mask = (scl.neq(3)
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
            .And(scl.neq(11)))
    return image.updateMask(mask)

def download_image(url, filepath):
    """Downloads an image from a URL and saves it."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(filepath, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        return False

def process_single_plot(plot):
    """Generates GEE URLs and downloads them for a single plot."""
    plot_id = plot["id"]
    plot_dir = os.path.join(PLOTS_DIR, str(plot_id))
    os.makedirs(plot_dir, exist_ok=True)
    
    # Check if already complete
    existing = [f for f in os.listdir(plot_dir) if f.startswith("rgb_") and f.endswith(".png")]
    if len(existing) >= len(MILESTONE_MONTHS):
        print(f"  [PLOT_{plot_id:03d}] SKIP (already has {len(existing)} images)")
        return {"id": plot_id, "status": "skipped", "count": len(existing)}
    
    bounds = plot["bounds"]  # [min_lon, min_lat, max_lon, max_lat]
    roi = ee.Geometry.BBox(
        bounds[0] - BUFFER_DEG, bounds[1] - BUFFER_DEG,
        bounds[2] + BUFFER_DEG, bounds[3] + BUFFER_DEG
    )
    
    saved_count = 0
    
    # RdYlGn palette for NDVI
    ndvi_palette = ['#d73027', '#fc8d59', '#fee08b', '#d9ef8b', '#91cf60', '#1a9850']
    
    for year, month in MILESTONE_MONTHS:
        month_str = f"{year:04d}-{month:02d}"
        rgb_path = os.path.join(plot_dir, f"rgb_{month_str}.png")
        ndvi_path = os.path.join(plot_dir, f"ndvi_{month_str}.png")
        
        if os.path.exists(rgb_path) and os.path.exists(ndvi_path):
            saved_count += 1
            continue
            
        last_day = calendar.monthrange(year, month)[1]
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{last_day}"
        
        # Build GEE query
        collection = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                      .filterBounds(roi)
                      .filterDate(start_date, end_date)
                      .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 80))
                      .map(mask_s2_clouds))
                      
        # Create median composite
        median_img = collection.median()
        
        # We need to ensure we don't request empty images. 
        # But for thumbnail URLs, GEE handles empty pixels gracefully (transparent/black).
        
        # RGB Visual parameters
        rgb_vis = {
            'bands': ['B4', 'B3', 'B2'],
            'min': 0,
            'max': 3000,
        }
        
        # NDVI Calculation & Visual parameters
        ndvi = median_img.normalizedDifference(['B8', 'B4']).rename('NDVI')
        ndvi_vis = {
            'min': -0.1,
            'max': 0.8,
            'palette': ndvi_palette
        }
        
        try:
            # Generate URLs
            rgb_url = median_img.visualize(**rgb_vis).getThumbURL({
                'region': roi,
                'dimensions': 400,
                'format': 'png'
            })
            
            ndvi_url = ndvi.visualize(**ndvi_vis).getThumbURL({
                'region': roi,
                'dimensions': 400,
                'format': 'png'
            })
            
            # Download files
            if download_image(rgb_url, rgb_path) and download_image(ndvi_url, ndvi_path):
                saved_count += 1
        except ee.ee_exception.EEException as e:
            # Often means no imagery found for that period
            print(f"  [PLOT_{plot_id:03d}] {month_str} GEE Error (No image?): {e}")
            pass
        except Exception as e:
            print(f"  [PLOT_{plot_id:03d}] {month_str} Download Error: {e}")
            pass

    print(f"  [PLOT_{plot_id:03d}] {plot['name'][:35]} | {saved_count}/{len(MILESTONE_MONTHS)} images saved via GEE")
    return {"id": plot_id, "status": "done", "count": saved_count}


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        plots_catalog = json.load(f)
    
    print(f"=" * 70)
    print(f"Sentinel-2 GEE Downloader (Project: {GEE_PROJECT})")
    print(f"Plots: {len(plots_catalog)} | Months: {len(MILESTONE_MONTHS)} | Workers: {MAX_WORKERS}")
    print(f"=" * 70)
    
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    results = []
    # Using thread pool to download in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_plot, p): p for p in plots_catalog}
        for f in as_completed(futures):
            try:
                r = f.result()
                if r:
                    results.append(r)
            except Exception as e:
                plot = futures[f]
                print(f"  [PLOT_{plot['id']:03d}] ERROR: {e}")
                traceback.print_exc()
    
    done = [r for r in results if r["status"] == "done"]
    skipped = [r for r in results if r["status"] == "skipped"]
    
    print(f"\n{'=' * 70}")
    print(f"GEE DOWNLOAD COMPLETE!")
    print(f"  Processed: {len(done)} plots")
    print(f"  Skipped (already done): {len(skipped)} plots")
    print(f"  Output directory: {PLOTS_DIR}")
    print(f"{'=' * 70}")
