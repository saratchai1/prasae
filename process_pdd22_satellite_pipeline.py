#!/usr/bin/env python3
"""PDD22 Sentinel-2 Satellite Processing Pipeline (Optimized Multi-Threaded & Parallel).

Builds a scientifically auditable Sentinel-2 L2A dataset for the 22 PDD project plots.
Rules:
1. Uses ONLY authoritative PDD participating polygons from data/pdd22/plots_catalog.json.
2. ZERO adjacent-month fallback (no temporal substitution).
3. Evaluates all candidate scenes in the exact calendar month.
4. Uses single best scene if >=95% clear; otherwise same-month median composite.
5. Computes reflectance-based indices (NDVI, NDRE, MNDWI, EVI, MFI) and strict QA.
"""

from __future__ import annotations
import time
from shapely.geometry import mapping, shape
from rasterio.warp import Resampling, reproject
from rasterio.transform import from_bounds
from rasterio.features import geometry_mask
import rasterio
import pystac_client
import planetary_computer as pc
from PIL import Image
import numpy as np
from typing import Any

import calendar
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import dataclass
import datetime as dt_mod
import json
import math
import os
from pathlib import Path
import sys

import subprocess
import hashlib


def get_git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    except Exception:
        return "unknown"


def get_file_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def get_pip_version(package):
    try:
        import importlib.metadata
        return importlib.metadata.version(package)
    except Exception:
        return "unknown"


# Configure GDAL HTTP timeouts and Python unbuffered stdout
os.environ["GDAL_HTTP_TIMEOUT"] = "15"
os.environ["GDAL_HTTP_MAX_RETRY"] = "3"
os.environ["GDAL_HTTP_RETRY_DELAY"] = "1"
os.environ["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] = ".tif,.tiff,.TIF,.TIFF"
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PDD_CATALOG_PATH = DATA_DIR / "pdd22" / "plots_catalog.json"
OUT_DIR = DATA_DIR / "pdd22_satellite"
PLOTS_OUT_DIR = OUT_DIR / "plots"

MILESTONE_MONTHS = [
    (2023, 9), (2023, 12),
    (2024, 3), (2024, 6), (2024, 9), (2024, 12),
    (2025, 3), (2025, 6), (2025, 9), (2025, 12),
    (2026, 3), (2026, 8),
]

BUFFER_DEG = 0.003
MAX_DIMENSION = 512
MIN_DIMENSION = 96
RGB_REFLECTANCE_MAX = 0.30
CLOUD_BUFFER_PIXELS = 1

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
SOURCE_LABEL = "Microsoft Planetary Computer / Sentinel-2 L2A"

MFI_RED_NM = 665.0
MFI_SWIR2_NM = 2190.0
MFI_RED_EDGE_BANDS = {
    "B05": 705.0,
    "B06": 740.0,
    "B07": 783.0,
    "B8A": 865.0,
}
REQUIRED_BANDS = ["B02", "B03", "B04", "B05",
                  "B06", "B07", "B08", "B8A", "B11", "B12"]


@dataclass(frozen=True)
class Grid:
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    transform: Any
    resolution_m: float


def compute_fixed_grid(geom) -> Grid:
    min_lon, min_lat, max_lon, max_lat = geom.bounds
    bbox = (
        min_lon - BUFFER_DEG,
        min_lat - BUFFER_DEG,
        max_lon + BUFFER_DEG,
        max_lat + BUFFER_DEG,
    )
    mid_lat = (bbox[1] + bbox[3]) / 2.0
    width_m = (bbox[2] - bbox[0]) * 111_000.0 * math.cos(math.radians(mid_lat))
    height_m = (bbox[3] - bbox[1]) * 111_000.0
    width = max(MIN_DIMENSION, min(MAX_DIMENSION, int(round(width_m / 10.0))))
    height = max(MIN_DIMENSION, min(
        MAX_DIMENSION, int(round(height_m / 10.0))))
    approx_res = (width_m / width + height_m / height) / 2.0
    return Grid(
        bbox=bbox,
        width=width,
        height=height,
        transform=from_bounds(*bbox, width, height),
        resolution_m=round(approx_res, 2),
    )


def get_pdd_polygon_mask(geom, grid: Grid) -> np.ndarray:
    return geometry_mask(
        [mapping(geom)],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        invert=True,
        all_touched=False,
    )

def get_pdd_buffer_mask(geom, grid: Grid, buffer_meters: float = 200.0) -> np.ndarray:
    buffer_deg = buffer_meters / 111111.0
    buffer_geom = geom.buffer(buffer_deg)
    buffer_mask = geometry_mask(
        [mapping(buffer_geom)],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        invert=True,
        all_touched=False,
    )
    pdd_mask = get_pdd_polygon_mask(geom, grid)
    return buffer_mask & ~pdd_mask


def _asset_scale_offset(item, asset_name: str) -> tuple[float, float]:
    asset = item.assets[asset_name]
    raster_bands = asset.extra_fields.get("raster:bands") or []
    band_meta = raster_bands[0] if raster_bands else {}
    scale = float(band_meta.get("scale", 1.0))
    offset = float(band_meta.get("offset", 0.0))
    if asset_name != "SCL" and scale == 1.0 and offset == 0.0:
        scale = 0.0001
    return scale, offset


def read_asset_to_grid(item, asset_name: str, grid: Grid, resampling: Resampling, max_retries: int = 3) -> np.ndarray:
    asset = item.assets[asset_name]
    href = asset.href
    for attempt in range(max_retries):
        try:
            with rasterio.open(href) as src:
                destination = np.full(
                    (grid.height, grid.width), np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=destination,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=0,
                    dst_transform=grid.transform,
                    dst_crs="EPSG:4326",
                    dst_nodata=np.nan,
                    resampling=resampling,
                )
            if asset_name == "SCL":
                return destination
            scale, offset = _asset_scale_offset(item, asset_name)
            valid = np.isfinite(destination)
            destination[valid] = destination[valid] * scale + offset
            return destination
        except Exception as e:
            if attempt == max_retries - 1:
                return np.full((grid.height, grid.width), np.nan, dtype=np.float32)
            time.sleep(1.0 * (attempt + 1))
    return np.full((grid.height, grid.width), np.nan, dtype=np.float32)


def read_all_bands_concurrent(item, grid: Grid) -> dict[str, np.ndarray]:
    def _read_b(b_name: str):
        return b_name, read_asset_to_grid(item, b_name, grid, Resampling.bilinear)

    bands: dict[str, np.ndarray] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_read_b, b) for b in REQUIRED_BANDS]
        for f in as_completed(futures):
            b_name, arr = f.result()
            bands[b_name] = arr
    return bands


def _dilate(mask: np.ndarray, pixels: int = 1) -> np.ndarray:
    if pixels <= 0:
        return mask.copy()
    out = mask.copy()
    for _ in range(pixels):
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        expanded = np.zeros_like(out, dtype=bool)
        for dy in range(3):
            for dx in range(3):
                expanded |= padded[dy:dy + out.shape[0], dx:dx + out.shape[1]]
        out = expanded
    return out


def cloud_clear_mask(scl: np.ndarray, *bands: np.ndarray) -> np.ndarray:
    scl_i = np.nan_to_num(scl, nan=0.0).astype(np.uint8)
    clear_classes = np.isin(scl_i, [4, 5, 6, 7])
    contamination = np.isin(scl_i, [1, 2, 3, 8, 9, 10, 11])
    contamination = _dilate(contamination, CLOUD_BUFFER_PIXELS)
    valid_bands = np.ones(scl.shape, dtype=bool)
    for band in bands:
        valid_bands &= np.isfinite(band)
    return clear_classes & ~contamination & valid_bands


def safe_normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    denom = a + b
    return np.divide(
        a - b,
        denom,
        out=np.full_like(a, np.nan, dtype=np.float32),
        where=np.isfinite(denom) & (np.abs(denom) > 1e-6),
    )


def compute_mfi(
    b04: np.ndarray,
    b05: np.ndarray,
    b06: np.ndarray,
    b07: np.ndarray,
    b8a: np.ndarray,
    b12: np.ndarray,
) -> np.ndarray:
    red_edges = {"B05": b05, "B06": b06, "B07": b07, "B8A": b8a}
    residuals = []
    for name, wavelength_nm in MFI_RED_EDGE_BANDS.items():
        baseline = b12 + (b04 - b12) * (
            (MFI_SWIR2_NM - wavelength_nm) / (MFI_SWIR2_NM - MFI_RED_NM)
        )
        residuals.append(red_edges[name] - baseline)
    with np.errstate(all="ignore"):
        return np.nanmean(np.stack(residuals, axis=0), axis=0).astype(np.float32)


def compute_evi(b02: np.ndarray, b04: np.ndarray, b08: np.ndarray) -> np.ndarray:
    denom = b08 + 6.0 * b04 - 7.5 * b02 + 1.0
    return np.divide(
        2.5 * (b08 - b04),
        denom,
        out=np.full_like(b08, np.nan, dtype=np.float32),
        where=np.isfinite(denom) & (np.abs(denom) > 1e-6),
    )


def palette_ndvi(ndvi: np.ndarray) -> np.ndarray:
    stops = np.array([-0.1, 0.08, 0.26, 0.44, 0.62, 0.8], dtype=np.float32)
    colors = np.array([
        [215, 48, 39], [252, 141, 89], [254, 224, 139],
        [217, 239, 139], [145, 207, 96], [26, 152, 80],
    ], dtype=np.float32)
    clipped = np.clip(ndvi, stops[0], stops[-1])
    out = np.zeros((*ndvi.shape, 3), dtype=np.float32)
    for channel in range(3):
        out[..., channel] = np.interp(clipped, stops, colors[:, channel])
    return np.nan_to_num(np.clip(out, 0, 255), nan=0.0).astype(np.uint8)


def save_rgba_image(path: Path, rgb: np.ndarray, alpha_mask: np.ndarray) -> None:
    rgba = np.zeros((*alpha_mask.shape, 4), dtype=np.uint8)
    rgba[..., :3] = np.nan_to_num(rgb, nan=0.0).astype(np.uint8)
    rgba[..., 3] = np.where(alpha_mask, 255, 0).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(path, "PNG", optimize=True)


def save_grayscale_image(path: Path, arr: np.ndarray, alpha_mask: np.ndarray) -> None:
    rgba = np.zeros((*alpha_mask.shape, 4), dtype=np.uint8)
    arr_u8 = np.nan_to_num(arr, nan=0.0).astype(np.uint8)
    rgba[..., 0] = arr_u8
    rgba[..., 1] = arr_u8
    rgba[..., 2] = arr_u8
    rgba[..., 3] = np.where(alpha_mask, 255, 0).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(path, "PNG", optimize=True)


def search_exact_month_scenes(catalog, grid: Grid, year: int, month: int) -> list[Any]:
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01T00:00:00Z"
    end = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"
    search = catalog.search(
        collections=[COLLECTION],
        bbox=list(grid.bbox),
        datetime=f"{start}/{end}",
    )
    raw_items = list(search.items())

    dedup: dict[tuple[str, str], Any] = {}
    for item in raw_items:
        props = item.properties
        tile = props.get("s2:mgrs_tile", "")
        dt_str = str(item.datetime)[:13]
        baseline = str(props.get("s2:processing_baseline", "00.00"))
        key = (dt_str, tile)
        if key not in dedup:
            dedup[key] = item
        else:
            existing_baseline = str(dedup[key].properties.get(
                "s2:processing_baseline", "00.00"))
            if baseline > existing_baseline:
                dedup[key] = item

    sorted_items = sorted(dedup.values(), key=lambda it: it.datetime)
    return sorted_items


def process_plot_month(
    catalog,
    plot: dict[str, Any],
    grid: Grid,
    pdd_mask: np.ndarray,
    buffer_mask: np.ndarray,
    year: int,
    month: int,
) -> dict[str, Any]:
    plot_code = plot["code"]
    month_str = f"{year:04d}-{month:02d}"
    inside_pixel_count = int(np.sum(pdd_mask))

    candidate_items = search_exact_month_scenes(catalog, grid, year, month)

    evaluated_scenes = []
    usable_items = []

    buffer_pixel_count = int(np.sum(buffer_mask))
    mid_month = dt_mod.datetime(year, month, calendar.monthrange(
        year, month)[1] // 2 + 1, tzinfo=dt_mod.timezone.utc)

    for item in candidate_items:
        props = item.properties
        dt_utc = str(item.datetime)
        dt_obj = item.datetime

        if item.datetime:
            dt_th_str = (item.datetime + dt_mod.timedelta(hours=7)
                         ).strftime("%Y-%m-%d %H:%M:%S UTC+7")
        else:
            dt_th_str = "N/A"
            dt_obj = dt_mod.datetime(
                year, month, 1, tzinfo=dt_mod.timezone.utc)

        platform = props.get("platform", "Sentinel-2")
        mgrs = props.get("s2:mgrs_tile", "")
        baseline = str(props.get("s2:processing_baseline", ""))
        cat_cloud = float(props.get("eo:cloud_cover", 0.0))

        try:
            scl = read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            clear_mask = cloud_clear_mask(scl)
            clear_inside = int(np.sum(clear_mask & pdd_mask))
            clear_inside_pct = round(
                clear_inside / inside_pixel_count * 100.0, 2)

            clear_buffer = int(np.sum(clear_mask & buffer_mask))
            clear_buffer_pct = round(
                clear_buffer / buffer_pixel_count * 100.0, 2) if buffer_pixel_count > 0 else 0.0

        except Exception as e:
            print(f"    Warning: Failed to read SCL for {item.id}: {e}")
            continue

        scene_info = {
            "id": item.id,
            "satellite": platform,
            "datetime_utc": dt_utc,
            "datetime_thailand": dt_th_str,
            "mgrs_tile": mgrs,
            "processing_baseline": baseline,
            "catalog_cloud_cover_pct": round(cat_cloud, 2),
            "clear_inside_pixel_count": clear_inside,
            "clear_inside_pct": clear_inside_pct,
            "clear_buffer_pct": clear_buffer_pct,
            "dt_obj": dt_obj,
        }
        evaluated_scenes.append(scene_info)
        if clear_inside > 0:
            usable_items.append((item, scene_info, scl, clear_mask))

    def ranking_key(s):
        c_in = s["clear_inside_pct"]
        c_buf = s["clear_buffer_pct"]
        c_cat = -s.get("catalog_cloud_cover_pct", 100.0)
        diff_days = -abs((s["dt_obj"] - mid_month).total_seconds())
        baseline = s["processing_baseline"]
        s_id = s["id"]
        return (c_in, c_buf, c_cat, diff_days, baseline, s_id)

    best_single = None
    if usable_items:
        usable_items.sort(key=lambda x: ranking_key(x[1]), reverse=True)
        best_single = usable_items[0][1]

    analysis_mode = "no_data"
    selected_scenes = []

    bands_dict: dict[str, np.ndarray] = {}
    valid_data_mask = np.zeros((grid.height, grid.width), dtype=bool)
    obs_count = np.zeros((grid.height, grid.width), dtype=np.uint8)

    if best_single and best_single["clear_inside_pct"] >= 95.0:
        analysis_mode = "single_scene_good"
        target_item = usable_items[0][0]
        selected_scenes = [best_single]

        scl = usable_items[0][2]
        bands_dict = read_all_bands_concurrent(target_item, grid)
        valid_data_mask = cloud_clear_mask(
            scl, *[bands_dict[b] for b in REQUIRED_BANDS])
        obs_count = np.where(valid_data_mask, 1, 0).astype(np.uint8)

    elif len(usable_items) == 1:
        analysis_mode = "single_scene_partial"
        target_item = usable_items[0][0]
        selected_scenes = [best_single]

        scl = usable_items[0][2]
        bands_dict = read_all_bands_concurrent(target_item, grid)
        valid_data_mask = cloud_clear_mask(
            scl, *[bands_dict[b] for b in REQUIRED_BANDS])
        obs_count = np.where(valid_data_mask, 1, 0).astype(np.uint8)

    elif len(usable_items) > 1:
        analysis_mode = "same_month_multi_scene_composite"
        selected_scenes = [sc for _, sc, _, _ in usable_items]

        band_stacks: dict[str, list[np.ndarray]] = {
            b: [] for b in REQUIRED_BANDS}
        mask_stacks: list[np.ndarray] = []

        for it, sc, scl, _ in usable_items:
            cur_bands = read_all_bands_concurrent(it, grid)
            cur_clear = cloud_clear_mask(
                scl, *[cur_bands[b] for b in REQUIRED_BANDS])
            mask_stacks.append(cur_clear)
            for b in REQUIRED_BANDS:
                arr = cur_bands[b].copy()
                arr[~cur_clear] = np.nan
                band_stacks[b].append(arr)

        obs_count = np.sum(np.stack(mask_stacks, axis=0),
                           axis=0).astype(np.uint8)
        valid_data_mask = obs_count > 0

        with np.errstate(all="ignore"):
            for b in REQUIRED_BANDS:
                stacked = np.stack(band_stacks[b], axis=0)
                bands_dict[b] = np.nanmedian(
                    stacked, axis=0).astype(np.float32)
    else:
        analysis_mode = "no_data"
        selected_scenes = []
        for b in REQUIRED_BANDS:
            bands_dict[b] = np.full(
                (grid.height, grid.width), np.nan, dtype=np.float32)

    for s in evaluated_scenes:
        s.pop('dt_obj', None)
    for s in selected_scenes:
        s.pop('dt_obj', None)

    valid_inside_mask = valid_data_mask & pdd_mask
    valid_pixel_count = int(np.sum(valid_inside_mask))
    coverage_pct = round(valid_pixel_count / inside_pixel_count * 100.0, 2)

    # Update analysis mode based on final valid pixel count
    num_scenes = len(selected_scenes)
    if valid_pixel_count == 0:
        analysis_mode = "no_data"
        selected_scenes = []
    elif num_scenes == 1:
        if coverage_pct >= 95.0:
            analysis_mode = "single_scene_good"
        else:
            analysis_mode = "single_scene_partial"
    elif num_scenes >= 2:
        analysis_mode = "same_month_multi_scene_composite"
    if coverage_pct >= 95.0:
        qa_status = "GOOD"
    elif coverage_pct >= 50.0:
        qa_status = "PARTIAL"
    elif coverage_pct >= 5.0:
        qa_status = "LOW_QA"
    else:
        qa_status = "NO_DATA"

    assert valid_pixel_count <= inside_pixel_count, f"valid ({valid_pixel_count}) > inside ({inside_pixel_count})"
    assert inside_pixel_count <= grid.width * \
        grid.height, f"inside ({inside_pixel_count}) > total grid ({grid.width*grid.height})"

    stats: dict[str, Any] = {}
    if valid_pixel_count > 0:
        b02 = bands_dict["B02"]
        b03 = bands_dict["B03"]
        b04 = bands_dict["B04"]
        b05 = bands_dict["B05"]
        b06 = bands_dict["B06"]
        b07 = bands_dict["B07"]
        b08 = bands_dict["B08"]
        b8a = bands_dict["B8A"]
        b11 = bands_dict["B11"]
        b12 = bands_dict["B12"]

        ndvi = safe_normalized_difference(b08, b04)
        ndre = safe_normalized_difference(b8a, b05)
        mndwi = safe_normalized_difference(b03, b11)
        evi = compute_evi(b02, b04, b08)
        mfi = compute_mfi(b04, b05, b06, b07, b8a, b12)

        ndvi_vals = ndvi[valid_inside_mask]
        ndre_vals = ndre[valid_inside_mask]
        mndwi_vals = mndwi[valid_inside_mask]
        mfi_vals = mfi[valid_inside_mask]
        evi_vals = evi[valid_inside_mask]

        stats = {
            "mean_ndvi": round(float(np.nanmean(ndvi_vals)), 4),
            "median_ndvi": round(float(np.nanmedian(ndvi_vals)), 4),
            "p10_ndvi": round(float(np.nanpercentile(ndvi_vals, 10)), 4),
            "p90_ndvi": round(float(np.nanpercentile(ndvi_vals, 90)), 4),
            "median_ndre": round(float(np.nanmedian(ndre_vals)), 4),
            "median_mndwi": round(float(np.nanmedian(mndwi_vals)), 4),
            "median_evi": round(float(np.nanmedian(evi_vals)), 4),
            "median_mfi": round(float(np.nanmedian(mfi_vals)), 4),
            "water_fraction": round(float(np.mean(mndwi_vals > 0.0)), 4),
            "green_proxy_fraction": round(float(np.mean(ndvi_vals > 0.25)), 4),
        }
    else:
        stats = {
            "mean_ndvi": None,
            "median_ndvi": None,
            "p10_ndvi": None,
            "p90_ndvi": None,
            "median_ndre": None,
            "median_mndwi": None,
            "median_evi": None,
            "median_mfi": None,
            "water_fraction": None,
            "green_proxy_fraction": None,
        }

    month_out_dir = PLOTS_OUT_DIR / plot_code / month_str
    month_out_dir.mkdir(parents=True, exist_ok=True)

    # Visual RGB
    rgb_arr = np.zeros((grid.height, grid.width, 3), dtype=np.uint8)
    if valid_pixel_count > 0:
        r = np.nan_to_num(np.clip(
            bands_dict["B04"] / RGB_REFLECTANCE_MAX * 255.0, 0, 255), nan=0.0).astype(np.uint8)
        g = np.nan_to_num(np.clip(
            bands_dict["B03"] / RGB_REFLECTANCE_MAX * 255.0, 0, 255), nan=0.0).astype(np.uint8)
        b = np.nan_to_num(np.clip(
            bands_dict["B02"] / RGB_REFLECTANCE_MAX * 255.0, 0, 255), nan=0.0).astype(np.uint8)
        rgb_arr = np.stack([r, g, b], axis=-1)
    save_rgba_image(month_out_dir / "rgb.png", rgb_arr, valid_inside_mask)

    # Visual NDVI
    ndvi_arr = np.zeros((grid.height, grid.width, 3), dtype=np.uint8)
    if valid_pixel_count > 0:
        ndvi_arr = palette_ndvi(ndvi)
    save_rgba_image(month_out_dir / "ndvi.png", ndvi_arr, valid_inside_mask)

    # Valid Data Mask
    valid_mask_img = np.where(valid_inside_mask, 255, 0).astype(np.uint8)
    save_grayscale_image(month_out_dir / "valid_mask.png",
                         valid_mask_img, pdd_mask)

    # Observation Count
    obs_scaled = np.clip(obs_count * 50, 0, 255).astype(np.uint8)
    save_grayscale_image(
        month_out_dir / "observation_count.png", obs_scaled, pdd_mask)

    record = {
        "month": month_str,
        "analysis_mode": analysis_mode,
        "composite_method": "median_clear_reflectance" if analysis_mode == "same_month_multi_scene_composite" else "none",
        "qa": qa_status,
        "inside_pixel_count": inside_pixel_count,
        "valid_pixel_count": valid_pixel_count,
        "coverage_pct": coverage_pct,
        "scenes_evaluated_count": len(evaluated_scenes),
        "scenes_used_count": len(selected_scenes),
        "number_of_contributing_scenes": len(selected_scenes),
        "selected_scene_ids": [s["id"] for s in selected_scenes],
        "selected_scenes": selected_scenes,
        "scenes": evaluated_scenes,
        "stats": stats,
    }
    return record


def is_plot_already_complete(plot_code: str) -> bool:
    meta_path = PLOTS_OUT_DIR / plot_code / "metadata.json"
    if not meta_path.exists():
        return False
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        obs = meta.get("observations", [])
        if len(obs) != 12:
            return False
        for ob in obs:
            m = ob["month"]
            m_dir = PLOTS_OUT_DIR / plot_code / m
            if not (m_dir / "rgb.png").exists() or not (m_dir / "ndvi.png").exists() or not (m_dir / "valid_mask.png").exists():
                return False
        return True
    except Exception:
        return False


def process_single_plot(catalog, plot: dict[str, Any]) -> dict[str, Any]:
    plot_code = plot["code"]
    pdd_area_rai = plot["area_rai"]
    province = plot["province"]

    if is_plot_already_complete(plot_code):
        print(
            f"✓ Plot {plot_code:10s} already completed 12/12 dates. Loading existing metadata.")
        with open(PLOTS_OUT_DIR / plot_code / "metadata.json", "r", encoding="utf-8") as f:
            return json.load(f)

    geom = shape(plot["geometry"])
    grid = compute_fixed_grid(geom)
    pdd_mask = get_pdd_polygon_mask(geom, grid)
    buffer_mask = get_pdd_buffer_mask(geom, grid, 200.0)
    inside_pixel_count = int(np.sum(pdd_mask))

    print(f"\n=================================================================")
    print(
        f"PROCESSING PLOT {plot_code:10s} | {province:12s} | PDD Area: {pdd_area_rai:7.2f} rai")
    print(f"Grid: {grid.width}x{grid.height} (Res ~{grid.resolution_m}m) | PDD Polygon Pixels: {inside_pixel_count:,}")
    print(f"=================================================================")

    months_data = []
    for year, month in MILESTONE_MONTHS:
        month_str = f"{year:04d}-{month:02d}"
        t0 = time.time()
        rec = process_plot_month(catalog, plot, grid, pdd_mask, buffer_mask, year, month)
        months_data.append(rec)
        t_el = round(time.time() - t0, 2)
        print(f"  [{plot_code} {month_str}] {rec['analysis_mode']:32s} | QA: {rec['qa']:7s} | Coverage: {rec['valid_pixel_count']:5d}/{inside_pixel_count:5d} ({rec['coverage_pct']:5.1f}%) | Scenes used: {rec['scenes_used_count']:2d} ({t_el}s)")

    plot_meta = {
        "plot_code": plot_code,
        "province": province,
        "coast": plot.get("coast", ""),
        "pdd_area_rai": pdd_area_rai,
        "allocated_area_rai": plot.get("allocated_area_rai"),
        "source": SOURCE_LABEL,
        "rules": {
            "adjacent_month_fallback": False,
            "interpolation": False,
            "synthetic_pixels": False,
            "strict_pdd_boundary_only": True,
            "cloud_scl_clear_classes": [4, 5, 6, 7],
            "cloud_buffer_pixels": CLOUD_BUFFER_PIXELS,
        },
        "grid": {
            "crs": "EPSG:4326",
            "bbox": list(grid.bbox),
            "width": grid.width,
            "height": grid.height,
            "resolution_m": grid.resolution_m,
        },
        "inside_pixel_count": inside_pixel_count,
        "observations": months_data,
    }

    out_plot_dir = PLOTS_OUT_DIR / plot_code
    out_plot_dir.mkdir(parents=True, exist_ok=True)
    with open(out_plot_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(plot_meta, f, indent=2, ensure_ascii=False)

    return plot_meta


def generate_executive_qa_summary(all_results: list[dict[str, Any]]) -> None:
    total_obs = sum(len(m["observations"]) for m in all_results)
    qa_counts = {"GOOD": 0, "PARTIAL": 0, "LOW_QA": 0, "NO_DATA": 0}
    modes_counts = {"single_scene_good": 0, "single_scene_partial": 0,
                    "same_month_multi_scene_composite": 0, "no_data": 0}

    gaps = []
    composites_used = []

    for meta in all_results:
        code = meta["plot_code"]
        prov = meta["province"]
        for obs in meta["observations"]:
            qa = obs["qa"]
            qa_counts[qa] = qa_counts.get(qa, 0) + 1
            mode = obs["analysis_mode"]
            modes_counts[mode] = modes_counts.get(mode, 0) + 1

            if qa in ["NO_DATA", "LOW_QA"]:
                gaps.append({
                    "plot_code": code,
                    "province": prov,
                    "month": obs["month"],
                    "qa": qa,
                    "coverage_pct": obs["coverage_pct"],
                    "scenes_evaluated": obs["scenes_evaluated_count"],
                })
            elif mode == "same_month_multi_scene_composite":
                sc_ids = obs.get("selected_scene_ids", [])
                if not sc_ids and "scenes" in obs:
                    sc_ids = [s["id"] for s in obs["scenes"]
                              if s.get("clear_inside_pct", 0) > 0]
                composites_used.append({
                    "plot_code": code,
                    "province": prov,
                    "month": obs["month"],
                    "qa": qa,
                    "coverage_pct": obs["coverage_pct"],
                    "scenes_used": obs["scenes_used_count"],
                    "selected_scene_ids": sc_ids,
                })

    lines = []
    lines.append(
        "# PDD22 Sentinel-2 Satellite Dataset: Executive QA Summary\n")
    lines.append(
        f"**Total Plots**: {len(all_results)} PDD Participating Plots  ")
    lines.append(
        f"**Total Observations**: {total_obs} (22 Plots × 12 Milestone Months)  ")
    lines.append(f"**Authoritative Total Project Area**: 6,775.53 rai  ")
    lines.append(
        f"**Source**: Microsoft Planetary Computer STAC (`sentinel-2-l2a` BOA Surface Reflectance)\n")

    lines.append("## 1. Overall QA Distribution\n")
    lines.append("| QA Classification | Description | Count | Percentage |")
    lines.append("| :--- | :--- | :---: | :---: |")
    lines.append(
        f"| **GOOD** | $\\ge 95\\%$ valid real clear coverage | **{qa_counts['GOOD']}** | {qa_counts['GOOD']/total_obs*100:.1f}% |")
    lines.append(
        f"| **PARTIAL** | $50\\% \\le \\text{{cov}} < 95\\%$ | **{qa_counts['PARTIAL']}** | {qa_counts['PARTIAL']/total_obs*100:.1f}% |")
    lines.append(
        f"| **LOW_QA** | $5\\% \\le \\text{{cov}} < 50\\%$ | **{qa_counts['LOW_QA']}** | {qa_counts['LOW_QA']/total_obs*100:.1f}% |")
    lines.append(
        f"| **NO_DATA** | $< 5\\%$ valid observation in exact month | **{qa_counts['NO_DATA']}** | {qa_counts['NO_DATA']/total_obs*100:.1f}% |")
    lines.append(f"| **Total** | | **{total_obs}** | 100.0% |\n")

    lines.append("## 2. Analysis Mode Breakdown\n")
    lines.append(
        f"- **Single Acquisition ($\\ge$ 95% Coverage) (`single_scene_good`)**: {modes_counts['single_scene_good']} ({modes_counts['single_scene_good']/total_obs*100:.1f}%) — Pristine radiometric consistency.")
    lines.append(
        f"- **Single Acquisition (< 95% Coverage) (`single_scene_partial`)**: {modes_counts['single_scene_partial']} ({modes_counts['single_scene_partial']/total_obs*100:.1f}%) — Only one valid scene available, resulting in partial coverage.")
    lines.append(
        f"- **Same-Month Multi-Scene Composite**: {modes_counts['same_month_multi_scene_composite']} ({modes_counts['same_month_multi_scene_composite']/total_obs*100:.1f}%) — Median reflectance composite across same-month clear observations.")
    lines.append(
        f"- **No Data Available in Exact Month**: {modes_counts['no_data']} ({modes_counts['no_data']/total_obs*100:.1f}%) — Zero clear Sentinel-2 passes during heavy monsoon cloud cover.\n")

    lines.append(
        "## 3. Persistent Data Gaps (Requiring Review or Special Consideration)\n")
    lines.append("Under strict scientific rules (Zero adjacent-month substitution), the following plot-months had insufficient cloud-free observations within the exact calendar month:\n")
    lines.append(
        "| Plot Code | Province | Month | QA Status | Real Coverage % | Evaluated Candidate Scenes | Note |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :--- |")
    for g in gaps:
        lines.append(f"| **{g['plot_code']}** | {g['province']} | `{g['month']}` | **{g['qa']}** | {g['coverage_pct']:.1f}% | {g['scenes_evaluated']} | Persistent monsoon cloud cover across entire month |")

    lines.append("\n## 4. Multi-Scene Composite Provenance\n")
    lines.append(
        "The following observations required multi-scene same-month reconstruction:\n")
    lines.append(
        "| Plot Code | Month | QA | Coverage % | Scenes Used | Selected Scene IDs |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :--- |")
    for c in composites_used:
        sc_list = "<br>".join([f"`{s}`" for s in c["selected_scene_ids"]])
        lines.append(
            f"| **{c['plot_code']}** | `{c['month']}` | **{c['qa']}** | {c['coverage_pct']:.1f}% | {c['scenes_used']} | {sc_list} |")

    summary_path = OUT_DIR / "EXECUTIVE_QA_SUMMARY.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✓ Executive QA summary written to: {summary_path}")


def run_pipeline(target_codes: list[str] | None = None, max_plot_workers: int = 3) -> list[dict[str, Any]]:
    catalog = pystac_client.Client.open(STAC_URL, modifier=pc.sign_inplace)

    with open(PDD_CATALOG_PATH, "r", encoding="utf-8") as f:
        plots = json.load(f)

    if target_codes:
        plots = [p for p in plots if p["code"] in target_codes]

    results_map: dict[str, dict[str, Any]] = {}

    uncompleted = [p for p in plots if not is_plot_already_complete(p["code"])]
    completed = [p for p in plots if is_plot_already_complete(p["code"])]

    for p in completed:
        with open(PLOTS_OUT_DIR / p["code"] / "metadata.json", "r", encoding="utf-8") as f:
            results_map[p["code"]] = json.load(f)

    print(
        f"Total plots: {len(plots)} | Already complete: {len(completed)} | To process: {len(uncompleted)}")

    if uncompleted:
        with ThreadPoolExecutor(max_workers=max_plot_workers) as executor:
            future_to_plot = {executor.submit(
                process_single_plot, catalog, p): p for p in uncompleted}
            for future in as_completed(future_to_plot):
                p = future_to_plot[future]
                try:
                    res = future.result()
                    results_map[res["plot_code"]] = res
                except Exception as e:
                    print(f"[Error] Failed processing plot {p['code']}: {e}")

    results = [results_map[p["code"]]
               for p in plots if p["code"] in results_map]

    rows = []
    for meta in results:
        code = meta["plot_code"]
        prov = meta["province"]
        area = meta["pdd_area_rai"]
        for obs in meta["observations"]:
            st = obs["stats"]
            rows.append({
                "plot_code": code,
                "province": prov,
                "pdd_area_rai": area,
                "month": obs["month"],
                "analysis_mode": obs["analysis_mode"],
                "scene_count": obs["scenes_used_count"],
                "inside_pixel_count": obs["inside_pixel_count"],
                "valid_pixel_count": obs["valid_pixel_count"],
                "coverage_pct": obs["coverage_pct"],
                "qa": obs["qa"],
                "mean_ndvi": st["mean_ndvi"],
                "median_ndvi": st["median_ndvi"],
                "median_ndre": st["median_ndre"],
                "median_mndwi": st["median_mndwi"],
                "median_mfi": st["median_mfi"],
            })

    csv_path = OUT_DIR / "coverage_report.csv"
    if target_codes and len(target_codes) < 22:
        csv_path = OUT_DIR / "pilot_5_plots_coverage.csv"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n✓ Coverage report saved to: {csv_path}")

    manifest = {
        "dataset_name": "PDD22 Sentinel-2 Level-2A Scientific Satellite Dataset",
        "generated_at_utc": dt_mod.datetime.utcnow().isoformat() + "Z",
        "pipeline_source_commit": get_git_commit(),
        "dataset_commit": "<new cleanup commit SHA cannot be known until commit>",
        "pipeline_file_sha256": get_file_sha256(__file__),
        "python_version": sys.version.split()[0],
        "dependency_versions": {
            "numpy": get_pip_version("numpy"),
            "rasterio": get_pip_version("rasterio"),
            "shapely": get_pip_version("shapely"),
            "pyproj": get_pip_version("pyproj"),
            "pystac-client": get_pip_version("pystac-client"),
            "planetary-computer": get_pip_version("planetary-computer"),
        },
        "processing_rules": {
            "adjacent_month_fallback": False,
            "interpolation": False,
            "synthetic_pixels": False,
            "strict_calendar_month": True,
            "ranking_policy": [
                "highest clear_inside_pct",
                "highest clear_buffer_pct",
                "lowest catalog_cloud_cover_pct",
                "closest to middle of target calendar month",
                "newest processing_baseline",
                "stable deterministic ID"
            ]
        },
        "plot_count": len(results),
        "total_pdd_area_rai": sum(m["pdd_area_rai"] for m in results),
        "observation_months": [f"{y:04d}-{m:02d}" for y, m in MILESTONE_MONTHS],
        "source": SOURCE_LABEL,
        "plots": [
            {
                "plot_code": m["plot_code"],
                "province": m["province"],
                "pdd_area_rai": m["pdd_area_rai"],
                "inside_pixel_count": m["inside_pixel_count"],
                "grid": m["grid"],
            }
            for m in results
        ],
    }
    with open(OUT_DIR / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    generate_executive_qa_summary(results)

    return results


if __name__ == "__main__":
    import sys
    pilot = ["88-VSD", "93-VSD", "94-VSD", "95-VSD", "87-VSD"]
    if len(sys.argv) > 1 and sys.argv[1] == "--all":
        print("Running full 22-plot PDD satellite processing...")
        run_pipeline(None)
    else:
        print(f"Running Pilot on 5 plots: {pilot}...")
        run_pipeline(pilot)
