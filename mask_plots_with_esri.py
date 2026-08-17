#!/usr/bin/env python3
"""
1. Downloads ESRI high-res satellite base image (esri_base.png) for all 210 plots.
2. Applies Polygon boundary alpha-mask to all Sentinel-2 RGB and NDVI images.
   - Pixels INSIDE the plot boundary remain full opacity.
   - Pixels OUTSIDE the plot boundary become 100% transparent.
"""

import os
import json
import requests
from PIL import Image, ImageDraw
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PLOTS_DIR = os.path.join(DATA_DIR, "plots")
CATALOG_PATH = os.path.join(DATA_DIR, "plots_catalog.json")

BUFFER_DEG = 0.003

with open(CATALOG_PATH, "r", encoding="utf-8") as f:
    plots_catalog = json.load(f)

def download_esri_base(plot):
    plot_id = plot["id"]
    plot_dir = os.path.join(PLOTS_DIR, str(plot_id))
    os.makedirs(plot_dir, exist_ok=True)
    
    esri_path = os.path.join(plot_dir, "esri_base.png")
    if os.path.exists(esri_path) and os.path.getsize(esri_path) > 1000:
        return plot_id, True
        
    bounds = plot["bounds"]
    min_lon = bounds[0] - BUFFER_DEG
    min_lat = bounds[1] - BUFFER_DEG
    max_lon = bounds[2] + BUFFER_DEG
    max_lat = bounds[3] + BUFFER_DEG
    
    # Calculate aspect ratio for dimensions
    w_deg = max_lon - min_lon
    h_deg = max_lat - min_lat
    if w_deg >= h_deg:
        W = 400
        H = int(round(400 * (h_deg / w_deg)))
    else:
        H = 400
        W = int(round(400 * (w_deg / h_deg)))
        
    esri_url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox={min_lon},{min_lat},{max_lon},{max_lat}&bboxSR=4326&imageSR=4326&size={W},{H}&format=png&f=image"
    
    try:
        r = requests.get(esri_url, timeout=15)
        if r.status_code == 200 and len(r.content) > 500:
            with open(esri_path, "wb") as f:
                f.write(r.content)
            return plot_id, True
    except Exception as e:
        print(f"Error downloading ESRI base for plot {plot_id}: {e}")
    return plot_id, False

print("=" * 70)
print(f"Step 1: Downloading ESRI base images for {len(plots_catalog)} plots...")
print("=" * 70)

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = {executor.submit(download_esri_base, p): p for p in plots_catalog}
    success = 0
    for f in as_completed(futures):
        pid, ok = f.result()
        if ok:
            success += 1

print(f"Downloaded ESRI base images for {success}/{len(plots_catalog)} plots.")

print("\n" + "=" * 70)
print("Step 2: Masking all Sentinel-2 RGB & NDVI images with Plot Boundaries...")
print("=" * 70)

def mask_plot_images(plot):
    plot_id = plot["id"]
    plot_dir = os.path.join(PLOTS_DIR, str(plot_id))
    if not os.path.exists(plot_dir):
        return plot_id, 0
        
    bounds = plot["bounds"]
    min_lon = bounds[0] - BUFFER_DEG
    min_lat = bounds[1] - BUFFER_DEG
    max_lon = bounds[2] + BUFFER_DEG
    max_lat = bounds[3] + BUFFER_DEG
    
    w_deg = max_lon - min_lon
    h_deg = max_lat - min_lat
    
    geom = plot["geometry"]
    coords = geom["coordinates"]
    if geom["type"] == "Polygon":
        coords = [coords]
        
    # Get all PNG images to mask (excluding esri_base.png)
    png_files = [f for f in os.listdir(plot_dir) if (f.startswith("rgb_") or f.startswith("ndvi_")) and f.endswith(".png")]
    
    masked_count = 0
    mask_cache = {}
    
    for fname in png_files:
        fpath = os.path.join(plot_dir, fname)
        try:
            im = Image.open(fpath).convert("RGBA")
            W, H = im.size
            
            # Generate or reuse mask for this (W, H)
            if (W, H) not in mask_cache:
                mask = Image.new("L", (W, H), 0)
                draw = ImageDraw.Draw(mask)
                for poly in coords:
                    for ring in poly:
                        pts = []
                        for lon, lat in ring:
                            px = ((lon - min_lon) / w_deg) * W
                            py = ((max_lat - lat) / h_deg) * H
                            pts.append((px, py))
                        draw.polygon(pts, fill=255)
                mask_cache[(W, H)] = mask
            else:
                mask = mask_cache[(W, H)]
                
            im.putalpha(mask)
            im.save(fpath, "PNG")
            masked_count += 1
        except Exception as e:
            print(f"Error masking {fpath}: {e}")
            
    return plot_id, masked_count

total_masked = 0
with ThreadPoolExecutor(max_workers=8) as executor:
    futures = {executor.submit(mask_plot_images, p): p for p in plots_catalog}
    for f in as_completed(futures):
        pid, count = f.result()
        total_masked += count

print(f"Successfully applied in-boundary alpha masks to {total_masked} images across all plots!")
print("=" * 70)
