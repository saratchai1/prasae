#!/usr/bin/env python3
"""
Download real Sentinel-2 L2A cloud-free composite imagery for all 210 plots.
Uses Microsoft Planetary Computer STAC API.
Produces RGB + NDVI PNGs per plot per milestone month.
"""

import os
import sys
import json
import warnings
import calendar
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
import pystac_client
import planetary_computer as pc
from PIL import Image
import matplotlib as mpl

# ─── Configuration ───────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PLOTS_DIR = os.path.join(DATA_DIR, "plots")
CATALOG_PATH = os.path.join(DATA_DIR, "plots_catalog.json")

# 12 milestone months (quarterly + start/end)
MILESTONE_MONTHS = [
    (2023, 9),   # Baseline (before planting)
    (2023, 12),  # 3 months
    (2024, 3),   # 6 months
    (2024, 6),   # 9 months
    (2024, 9),   # 1 year
    (2024, 12),  # 1.3 years
    (2025, 3),   # 1.5 years
    (2025, 6),   # 1.8 years
    (2025, 9),   # 2 years
    (2025, 12),  # 2.3 years
    (2026, 3),   # 2.5 years
    (2026, 8),   # Current (latest)
]

MAX_IMG_SIZE = 400  # Max pixel dimension per side
MIN_IMG_SIZE = 96   # Min pixel dimension per side
BUFFER_DEG = 0.003  # ~330m buffer around plot bounds
MAX_WORKERS = 8     # Parallel download threads

# ─── Helpers ─────────────────────────────────────────────────────────────────

def get_ndvi_colored(ndvi_array):
    """Convert NDVI float array to RGB colormap image."""
    norm = np.clip((ndvi_array - (-0.1)) / 0.8, 0, 1)
    cmap = mpl.colormaps["RdYlGn"]
    rgba = cmap(norm)
    rgb = (rgba[:, :, :3] * 255).astype(np.uint8)
    # Set NaN pixels to dark background
    nan_mask = np.isnan(ndvi_array)
    rgb[nan_mask] = [15, 23, 42]
    return rgb


def compute_image_size(bounds, min_size=MIN_IMG_SIZE, max_size=MAX_IMG_SIZE):
    """Compute appropriate pixel size based on geographic extent."""
    import math
    lon_range = bounds[2] - bounds[0]
    lat_range = bounds[3] - bounds[1]
    mid_lat = (bounds[1] + bounds[3]) / 2.0
    
    # meters per degree
    m_per_deg_lon = 111000 * math.cos(math.radians(mid_lat))
    m_per_deg_lat = 111000
    
    w_m = lon_range * m_per_deg_lon
    h_m = lat_range * m_per_deg_lat
    
    # Sentinel-2 is 10m resolution
    w_px = int(w_m / 10)
    h_px = int(h_m / 10)
    
    # Clamp to min/max
    w_px = max(min_size, min(max_size, w_px))
    h_px = max(min_size, min(max_size, h_px))
    
    return h_px, w_px


def read_and_composite_month(stac_catalog, bbox, target_shape, year, month):
    """
    Download and composite Sentinel-2 scenes for a given month.
    Returns dict with 'vis' (3,H,W), 'ndvi' (H,W), 'clear_ratio' or None.
    """
    last_day = calendar.monthrange(year, month)[1]
    
    # Search window: target month ± 15 days for temporal compositing
    if month == 1:
        search_start = f"{year-1}-12-15"
    else:
        search_start = f"{year}-{month-1:02d}-15"
    
    if month == 12:
        search_end = f"{year+1}-01-15"
    else:
        search_end = f"{year}-{month+1:02d}-15"
    
    search = stac_catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=bbox,
        datetime=f"{search_start}/{search_end}",
        query={"eo:cloud_cover": {"lt": 70}},
    )
    items = sorted(list(search.items()), 
                   key=lambda it: it.properties.get("eo:cloud_cover", 100))
    
    if not items:
        # Wider search: ± 45 days
        if month <= 2:
            ws = f"{year-1}-{max(1,month+10):02d}-01"
        else:
            ws = f"{year}-{month-2:02d}-01"
        if month >= 11:
            we = f"{year+1}-{min(12,month-10):02d}-28"
        else:
            we = f"{year}-{month+2:02d}-28"
            
        search = stac_catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime=f"{ws}/{we}",
            query={"eo:cloud_cover": {"lt": 80}},
        )
        items = sorted(list(search.items()),
                       key=lambda it: it.properties.get("eo:cloud_cover", 100))
    
    if not items:
        return None
    
    H, W = target_shape
    
    # Process up to 6 best (lowest cloud) scenes for compositing
    clean_scenes = []
    for it in items[:6]:
        try:
            with rasterio.open(it.assets["SCL"].href) as scl_src:
                b_utm = transform_bounds("EPSG:4326", scl_src.crs, *bbox)
                win = from_bounds(*b_utm, transform=scl_src.transform)
                scl = scl_src.read(indexes=1, window=win,
                                   out_shape=(H, W),
                                   resampling=Resampling.nearest)
            
            with rasterio.open(it.assets["visual"].href) as vis_src:
                b_utm2 = transform_bounds("EPSG:4326", vis_src.crs, *bbox)
                win2 = from_bounds(*b_utm2, transform=vis_src.transform)
                vis = vis_src.read(window=win2,
                                  out_shape=(3, H, W),
                                  resampling=Resampling.bilinear).astype(np.float32)
            
            with rasterio.open(it.assets["B04"].href) as b_src:
                b04 = b_src.read(indexes=1, window=win,
                                 out_shape=(H, W),
                                 resampling=Resampling.bilinear).astype(np.float32)
            
            with rasterio.open(it.assets["B08"].href) as b_src:
                b08 = b_src.read(indexes=1, window=win,
                                 out_shape=(H, W),
                                 resampling=Resampling.bilinear).astype(np.float32)
            
            # Cloud mask: SCL classes 0,1,3,8,9,10,11 = cloud/shadow/invalid
            mean_rgb = np.mean(vis, axis=0)
            is_cloud = (np.isin(scl, [0, 1, 3, 8, 9, 10, 11]) | 
                       (mean_rgb > 150.0) | 
                       (b04 > 3200) |
                       (vis[2] > 180))
            is_clear = (~is_cloud & (vis[0] > 0) & (b04 > 0) & (b08 > 0))
            
            clear_ratio = float(np.mean(is_clear))
            if clear_ratio < 0.05:
                continue
            
            # NDVI
            denom = b08 + b04
            denom[denom == 0] = 1e-6
            ndvi = (b08 - b04) / denom
            
            # Apply cloud mask
            vis_clean = np.where(is_clear[np.newaxis, :, :], vis, np.nan)
            ndvi_clean = np.where(is_clear, ndvi, np.nan)
            
            clean_scenes.append({
                "vis": vis_clean,
                "ndvi": ndvi_clean,
                "clear_ratio": clear_ratio,
            })
        except Exception:
            continue
    
    if not clean_scenes:
        return None
    
    # Temporal Compositing: median of all clean scenes
    stack_vis = np.stack([s["vis"] for s in clean_scenes], axis=0)
    stack_ndvi = np.stack([s["ndvi"] for s in clean_scenes], axis=0)
    
    with np.errstate(all="ignore"):
        comp_vis = np.nanmedian(stack_vis, axis=0)
        comp_ndvi = np.nanmedian(stack_ndvi, axis=0)
    
    # Fill any remaining NaN with nearest scene
    missing_mask = np.isnan(comp_vis[0])
    if np.any(missing_mask):
        for s in clean_scenes:
            fill_available = ~np.isnan(s["vis"][0]) & missing_mask
            if np.any(fill_available):
                for c in range(3):
                    comp_vis[c][fill_available] = s["vis"][c][fill_available]
                comp_ndvi[fill_available] = s["ndvi"][fill_available]
                missing_mask = np.isnan(comp_vis[0])
                if not np.any(missing_mask):
                    break
    
    # Replace any final NaN with 0
    comp_vis = np.nan_to_num(comp_vis, nan=0.0)
    comp_ndvi = np.nan_to_num(comp_ndvi, nan=0.0)
    
    total_clear = float(1.0 - np.mean(np.isnan(stack_vis[0, 0])))
    
    return {
        "vis": comp_vis,
        "ndvi": comp_ndvi,
        "clear_ratio": total_clear,
    }


def process_single_plot(plot):
    """Download and save all milestone images for a single plot."""
    plot_id = plot["id"]
    plot_dir = os.path.join(PLOTS_DIR, str(plot_id))
    os.makedirs(plot_dir, exist_ok=True)
    
    # Check if already complete
    existing = [f for f in os.listdir(plot_dir) if f.startswith("rgb_") and f.endswith(".png")]
    if len(existing) >= len(MILESTONE_MONTHS):
        print(f"  [PLOT_{plot_id:03d}] SKIP (already has {len(existing)} images)")
        return {"id": plot_id, "status": "skipped", "count": len(existing)}
    
    bounds = plot["bounds"]  # [min_lon, min_lat, max_lon, max_lat]
    bbox = [
        bounds[0] - BUFFER_DEG,
        bounds[1] - BUFFER_DEG,
        bounds[2] + BUFFER_DEG,
        bounds[3] + BUFFER_DEG,
    ]
    
    target_shape = compute_image_size(bbox)
    
    stac_catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace,
    )
    
    saved_count = 0
    
    for year, month in MILESTONE_MONTHS:
        month_str = f"{year:04d}-{month:02d}"
        rgb_path = os.path.join(plot_dir, f"rgb_{month_str}.png")
        ndvi_path = os.path.join(plot_dir, f"ndvi_{month_str}.png")
        
        # Skip if already exists
        if os.path.exists(rgb_path) and os.path.exists(ndvi_path):
            saved_count += 1
            continue
        
        result = read_and_composite_month(stac_catalog, bbox, target_shape, year, month)
        
        if result is None:
            # Create a placeholder dark image
            dark = np.zeros((target_shape[0], target_shape[1], 3), dtype=np.uint8)
            dark[:] = [15, 23, 42]  # Dark background
            Image.fromarray(dark).save(rgb_path, optimize=True)
            Image.fromarray(dark).save(ndvi_path, optimize=True)
            saved_count += 1
            continue
        
        # Save RGB
        vis = result["vis"]
        rgb_arr = np.clip(vis, 0, 255).astype(np.uint8)
        rgb_img = np.transpose(rgb_arr, (1, 2, 0))  # (H,W,3)
        Image.fromarray(rgb_img).save(rgb_path, optimize=True)
        
        # Save NDVI colormap
        ndvi_colored = get_ndvi_colored(result["ndvi"])
        Image.fromarray(ndvi_colored).save(ndvi_path, optimize=True)
        
        saved_count += 1
    
    print(f"  [PLOT_{plot_id:03d}] {plot['name'][:35]} | {plot['province']} | {saved_count}/{len(MILESTONE_MONTHS)} images saved")
    return {"id": plot_id, "status": "done", "count": saved_count}


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        plots_catalog = json.load(f)
    
    print(f"=" * 70)
    print(f"Sentinel-2 L2A Cloud-Free Imagery Downloader")
    print(f"Plots: {len(plots_catalog)} | Months: {len(MILESTONE_MONTHS)} | Workers: {MAX_WORKERS}")
    print(f"Total images to generate: {len(plots_catalog) * len(MILESTONE_MONTHS) * 2} (RGB + NDVI)")
    print(f"Output: {PLOTS_DIR}/{{plot_id}}/rgb_YYYY-MM.png & ndvi_YYYY-MM.png")
    print(f"=" * 70)
    
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    results = []
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
    print(f"COMPLETE!")
    print(f"  Processed: {len(done)} plots")
    print(f"  Skipped (already done): {len(skipped)} plots")
    print(f"  Total images: {sum(r['count'] for r in results) * 2} (RGB + NDVI)")
    print(f"  Output directory: {PLOTS_DIR}")
    print(f"{'=' * 70}")
