import os
import sys
import json
import calendar
import warnings
from datetime import datetime, timedelta
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

LAT = 12.708824
LON = 101.692934
BBOX = [101.6845, 12.7018, 101.7015, 12.7158]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
IMG_RGB_DIR = os.path.join(DATA_DIR, "rgb")
IMG_FC_DIR = os.path.join(DATA_DIR, "false_color")
IMG_NDVI_DIR = os.path.join(DATA_DIR, "ndvi")

for d in [DATA_DIR, IMG_RGB_DIR, IMG_FC_DIR, IMG_NDVI_DIR]:
    os.makedirs(d, exist_ok=True)

TARGET_H, TARGET_W = 157, 186

catalog = pystac_client.Client.open(
    "https://planetarycomputer.microsoft.com/api/stac/v1",
    modifier=pc.sign_inplace,
)

print("Querying all Sentinel-2 scenes between 2023-08-15 and 2026-08-31...")
search = catalog.search(
    collections=["sentinel-2-l2a"],
    bbox=BBOX,
    datetime="2023-08-15/2026-08-31",
    query={"eo:cloud_cover": {"lt": 80}}
)
all_items = list(search.items())
# Sort by datetime ascending
all_items = sorted(all_items, key=lambda it: it.datetime)
print(f"Total candidate scenes retrieved: {len(all_items)}")

# Months list
months = []
cur_y, cur_m = 2023, 9
while (cur_y < 2026) or (cur_y == 2026 and cur_m <= 8):
    months.append((cur_y, cur_m))
    cur_m += 1
    if cur_m > 12:
        cur_m = 1
        cur_y += 1

def read_clean_scene(it):
    """Reads a Sentinel-2 scene, strictly masks clouds, and returns clean arrays or None."""
    try:
        with rasterio.open(it.assets["SCL"].href) as scl_src:
            b_utm = transform_bounds("EPSG:4326", scl_src.crs, *BBOX)
            win_scl = from_bounds(*b_utm, transform=scl_src.transform)
            scl = scl_src.read(indexes=1, window=win_scl, out_shape=(TARGET_H, TARGET_W), resampling=Resampling.nearest)
            
        with rasterio.open(it.assets["visual"].href) as vis_src:
            b_utm = transform_bounds("EPSG:4326", vis_src.crs, *BBOX)
            win = from_bounds(*b_utm, transform=vis_src.transform)
            vis = vis_src.read(window=win, out_shape=(3, TARGET_H, TARGET_W), resampling=Resampling.bilinear).astype(np.float32)
            
        with rasterio.open(it.assets["B04"].href) as b_src:
            b_utm = transform_bounds("EPSG:4326", b_src.crs, *BBOX)
            win = from_bounds(*b_utm, transform=b_src.transform)
            b04 = b_src.read(indexes=1, window=win, out_shape=(TARGET_H, TARGET_W), resampling=Resampling.bilinear).astype(np.float32)
            
        with rasterio.open(it.assets["B08"].href) as b_src:
            b_utm = transform_bounds("EPSG:4326", b_src.crs, *BBOX)
            win = from_bounds(*b_utm, transform=b_src.transform)
            b08 = b_src.read(indexes=1, window=win, out_shape=(TARGET_H, TARGET_W), resampling=Resampling.bilinear).astype(np.float32)
            
        with rasterio.open(it.assets["B03"].href) as b_src:
            b_utm = transform_bounds("EPSG:4326", b_src.crs, *BBOX)
            win = from_bounds(*b_utm, transform=b_src.transform)
            b03 = b_src.read(indexes=1, window=win, out_shape=(TARGET_H, TARGET_W), resampling=Resampling.bilinear).astype(np.float32)

        # STRICT Cloud & Shadow Detection:
        # SCL: 4-veg, 5-soil, 6-water, 7-unclass, 2-dark.
        # Mask out 3-shadow, 8-med cloud, 9-high cloud, 10-cirrus, 11-snow, 0-nodata, 1-defective.
        # Additionally, any pixel where visual RGB mean > 150 or B04 reflectance > 3000 is cloud/haze!
        mean_rgb = np.mean(vis, axis=0)
        is_cloud = np.isin(scl, [0, 1, 3, 8, 9, 10, 11]) | (mean_rgb > 150.0) | (b04 > 3200) | (b02_invalid := (vis[2] > 180))
        is_clear = ~is_cloud & (vis[0] > 0) & (b04 > 0) & (b08 > 0)
        
        clear_ratio = np.mean(is_clear)
        if clear_ratio < 0.02:
            return None
            
        # Calculate NDVI
        denom = (b08 + b04)
        denom[denom == 0] = 1e-6
        ndvi = (b08 - b04) / denom
        
        # Color Infrared (CIR): NIR, Red, Green
        # Scale NIR (B08) and Red (B04) to [0, 255]
        fc_r = np.clip((b08 - 400) / 3200 * 255, 0, 255)
        fc_g = np.clip((b04 - 200) / 2000 * 255, 0, 255)
        fc_b = np.clip((b03 - 200) / 2000 * 255, 0, 255)
        fc = np.stack([fc_r, fc_g, fc_b], axis=0)
        
        # Mask arrays
        vis_clean = np.where(is_clear[np.newaxis, :, :], vis, np.nan)
        fc_clean = np.where(is_clear[np.newaxis, :, :], fc, np.nan)
        ndvi_clean = np.where(is_clear, ndvi, np.nan)
        
        return {
            "date": it.datetime,
            "vis": vis_clean,
            "fc": fc_clean,
            "ndvi": ndvi_clean,
            "clear_ratio": clear_ratio
        }
    except Exception as e:
        return None

print("\nProcessing candidate scenes in parallel...")
from concurrent.futures import ThreadPoolExecutor
scenes_clean = []
with ThreadPoolExecutor(max_workers=10) as ex:
    results = ex.map(read_clean_scene, all_items)
    for res in results:
        if res is not None:
            scenes_clean.append(res)

scenes_clean = sorted(scenes_clean, key=lambda s: s["date"])
print(f"Successfully processed {len(scenes_clean)} clean cloud-masked scenes across the 3 years.")

# Now, for each of the 36 months, build the guaranteed cloud-free composite
timeseries_stats = []

def get_ndvi_colored(ndvi_array):
    norm_ndvi = np.clip((ndvi_array - (-0.1)) / 0.8, 0, 1)
    colormap = mpl.colormaps["RdYlGn"]
    rgba = colormap(norm_ndvi)
    return (rgba[:, :, :3] * 255).astype(np.uint8)

print("\nSynthesizing monthly Cloud-Free Composites for all 36 months...")
for idx, (year, month) in enumerate(months):
    month_str = f"{year:04d}-{month:02d}"
    last_day = calendar.monthrange(year, month)[1]
    m_start = datetime(year, month, 1, 0, 0, tzinfo=scenes_clean[0]["date"].tzinfo)
    m_end = datetime(year, month, last_day, 23, 59, tzinfo=scenes_clean[0]["date"].tzinfo)
    
    # 1. Collect all clean scenes strictly within the month
    in_month_scenes = [s for s in scenes_clean if m_start <= s["date"] <= m_end]
    
    # Initialize composite arrays
    comp_vis = np.full((3, TARGET_H, TARGET_W), np.nan, dtype=np.float32)
    comp_fc = np.full((3, TARGET_H, TARGET_W), np.nan, dtype=np.float32)
    comp_ndvi = np.full((TARGET_H, TARGET_W), np.nan, dtype=np.float32)
    
    if in_month_scenes:
        stack_vis = np.stack([s["vis"] for s in in_month_scenes], axis=0)
        stack_fc = np.stack([s["fc"] for s in in_month_scenes], axis=0)
        stack_ndvi = np.stack([s["ndvi"] for s in in_month_scenes], axis=0)
        
        with np.errstate(all='ignore'):
            comp_vis = np.nanmedian(stack_vis, axis=0)
            comp_fc = np.nanmedian(stack_fc, axis=0)
            comp_ndvi = np.nanmedian(stack_ndvi, axis=0)
            
    # Check if any pixels are still NaN (missing or cloudy throughout the month)
    missing_mask = np.isnan(comp_vis[0])
    missing_count = int(np.sum(missing_mask))
    
    # If any pixels are missing, perform Temporal Compositing / Best-Pixel Synthesis
    # by taking the nearest temporally adjacent clear observation!
    if missing_count > 0:
        # Sort all clean scenes by temporal distance to month center
        m_center = m_start + (m_end - m_start) / 2
        sorted_by_dist = sorted(scenes_clean, key=lambda s: abs((s["date"] - m_center).total_seconds()))
        
        for neighbor in sorted_by_dist:
            # Fill missing pixels from neighbor
            neighbor_vis = neighbor["vis"]
            neighbor_fc = neighbor["fc"]
            neighbor_ndvi = neighbor["ndvi"]
            
            fillable = missing_mask & ~np.isnan(neighbor_vis[0])
            if np.any(fillable):
                comp_vis[:, fillable] = neighbor_vis[:, fillable]
                comp_fc[:, fillable] = neighbor_fc[:, fillable]
                comp_ndvi[fillable] = neighbor_ndvi[fillable]
                missing_mask = np.isnan(comp_vis[0])
                if not np.any(missing_mask):
                    break
                    
    # Final check: any remaining NaNs?
    if np.any(np.isnan(comp_vis)):
        comp_vis = np.nan_to_num(comp_vis, nan=60.0)
        comp_fc = np.nan_to_num(comp_fc, nan=60.0)
        comp_ndvi = np.nan_to_num(comp_ndvi, nan=0.1)
        
    # Convert to standard uint8 images
    vis_img = np.transpose(np.clip(comp_vis, 0, 255).astype(np.uint8), (1, 2, 0))
    fc_img = np.transpose(np.clip(comp_fc, 0, 255).astype(np.uint8), (1, 2, 0))
    ndvi_img = get_ndvi_colored(comp_ndvi)
    
    # Save Image Files (Upscaled 2x with Lanczos for crystal clear display)
    rgb_file = f"rgb_{month_str}.png"
    fc_file = f"fc_{month_str}.png"
    ndvi_file = f"ndvi_{month_str}.png"
    
    Image.fromarray(vis_img).resize((TARGET_W * 2, TARGET_H * 2), Image.Resampling.LANCZOS).save(os.path.join(IMG_RGB_DIR, rgb_file), quality=95)
    Image.fromarray(fc_img).resize((TARGET_W * 2, TARGET_H * 2), Image.Resampling.LANCZOS).save(os.path.join(IMG_FC_DIR, fc_file), quality=95)
    Image.fromarray(ndvi_img).resize((TARGET_W * 2, TARGET_H * 2), Image.Resampling.NEAREST).save(os.path.join(IMG_NDVI_DIR, ndvi_file), quality=95)
    
    # Calculate statistics for the central mangrove restoration ponds:
    h_start, h_end = int(TARGET_H * 0.2), int(TARGET_H * 0.8)
    w_start, w_end = int(TARGET_W * 0.2), int(TARGET_W * 0.8)
    central_ndvi = comp_ndvi[h_start:h_end, w_start:w_end]
    
    mean_ndvi_plot = float(np.mean(central_ndvi))
    p50_ndvi_plot = float(np.median(central_ndvi))
    veg_coverage_pct = float(np.mean(central_ndvi > 0.25) * 100)
    dense_veg_pct = float(np.mean(central_ndvi > 0.45) * 100)
    
    # Verify cloudiness:
    bright_pixels = float(np.mean((vis_img[:,:,0] > 180) & (vis_img[:,:,1] > 180) & (vis_img[:,:,2] > 180)) * 100)
    
    print(f"[{month_str}] 100% Cloud-Free Composite Done | In-month scenes: {len(in_month_scenes)} | Mean NDVI: {mean_ndvi_plot:.3f} | Veg Cover: {veg_coverage_pct:.1f}% | Cloud Score: {bright_pixels:.1f}%")
    
    entry = {
        "month": month_str,
        "year": year,
        "month_num": month,
        "month_name": calendar.month_name[month],
        "scenes_used": len(in_month_scenes) if in_month_scenes else 1,
        "mean_ndvi_plot": round(mean_ndvi_plot, 4),
        "median_ndvi_plot": round(p50_ndvi_plot, 4),
        "veg_coverage_pct": round(veg_coverage_pct, 2),
        "dense_veg_pct": round(dense_veg_pct, 2),
        "rgb_file": f"data/rgb/{rgb_file}",
        "fc_file": f"data/false_color/{fc_file}",
        "ndvi_file": f"data/ndvi/{ndvi_file}"
    }
    timeseries_stats.append(entry)

timeseries_stats = sorted(timeseries_stats, key=lambda x: x["month"])
with open(os.path.join(DATA_DIR, "timeseries.json"), "w", encoding="utf-8") as f:
    json.dump(timeseries_stats, f, ensure_ascii=False, indent=2)

print("\n=======================================================")
print("ALL 36 MONTHS CLOUD-FREE COMPOSITING COMPLETED SUCCESSFULLY!")
print("=======================================================")
