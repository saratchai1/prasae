#!/usr/bin/env python3
"""Build the canonical 12-date Sentinel-2 mangrove monitoring dataset.

Metric design
-------------
* Exactly 12 declared observation/composite months.
* No nearest-month substitution, interpolation, or synthetic fallback.
* Exact Polygon/MultiPolygon clipping with polygon holes preserved.
* Sentinel-2 Level-2A bottom-of-atmosphere reflectance.
* Cloud/shadow/snow masking from SCL, with a small contamination buffer.
* Plot-wide NDVI plus a tide-resilient Mangrove Vegetation Proxy.
* Mangrove Forest Index (MFI) is used to retain periodically submerged mangrove
  signal that can be missed by NDVI alone.
* NDRE is recorded as a red-edge canopy-condition diagnostic.
* MNDWI-derived open-water fraction is reported separately rather than folded
  into vegetation condition.
* Every date records scene IDs, QA, native-resolution provenance and metric rules.

Data source: Sentinel-2 L2A from Microsoft Planetary Computer STAC.
"""

from __future__ import annotations

import calendar
import json
import math
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import planetary_computer as pc
import pystac_client
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject
from shapely.geometry import mapping, shape

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLOTS_DIR = DATA_DIR / "plots"
CATALOG_PATH = DATA_DIR / "plots_catalog.json"
OUTPUT_PATH = DATA_DIR / "timeseries_verified_12.json"

MILESTONE_MONTHS = [
    (2023, 9), (2023, 12), (2024, 3), (2024, 6),
    (2024, 9), (2024, 12), (2025, 3), (2025, 6),
    (2025, 9), (2025, 12), (2026, 3), (2026, 8),
]

BUFFER_DEG = 0.003
MAX_DIMENSION = 512
MIN_DIMENSION = 96
MAX_SCENES_PER_MONTH = int(os.environ.get("PRASAE_MAX_SCENES", "6"))
MAX_WORKERS = int(os.environ.get("PRASAE_WORKERS", "4"))
MAX_CLOUD_COVER = 90
MIN_VALID_INSIDE_RATIO = 0.05

# Screening rules; these are deliberately called proxies, not field canopy cover.
EMERGED_VEGETATION_NDVI_THRESHOLD = 0.25
SUBMERGED_MANGROVE_MFI_THRESHOLD = 0.0
OPEN_WATER_MNDWI_THRESHOLD = 0.0
PROXY_VERSION = "v2_ndvi_or_mfi"

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


@dataclass(frozen=True)
class Grid:
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    transform: Any


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def compute_grid(geom) -> Grid:
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
    height = max(MIN_DIMENSION, min(MAX_DIMENSION, int(round(height_m / 10.0))))
    return Grid(bbox=bbox, width=width, height=height, transform=from_bounds(*bbox, width, height))


def _asset_scale_offset(item, asset_name: str) -> tuple[float, float]:
    asset = item.assets[asset_name]
    raster_bands = asset.extra_fields.get("raster:bands") or []
    band_meta = raster_bands[0] if raster_bands else {}
    scale = float(band_meta.get("scale", 1.0))
    offset = float(band_meta.get("offset", 0.0))
    if asset_name != "SCL" and scale == 1.0 and offset == 0.0:
        scale = 0.0001
    return scale, offset


def read_asset_to_grid(item, asset_name: str, grid: Grid, resampling: Resampling) -> np.ndarray:
    asset = item.assets[asset_name]
    with rasterio.open(asset.href) as src:
        destination = np.full((grid.height, grid.width), np.nan, dtype=np.float32)
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


def plot_mask(geom, grid: Grid) -> np.ndarray:
    return geometry_mask(
        [mapping(geom)],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        invert=True,
        all_touched=False,
    )


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
    return np.clip(out, 0, 255).astype(np.uint8)


def save_rgba(path: Path, rgb: np.ndarray, alpha_mask: np.ndarray) -> None:
    rgba = np.zeros((*alpha_mask.shape, 4), dtype=np.uint8)
    rgba[..., :3] = rgb
    rgba[..., 3] = np.where(alpha_mask, 255, 0).astype(np.uint8)
    Image.fromarray(rgba, mode="RGBA").save(path, "PNG", optimize=True)


def remove_stale(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def stac_client():
    return pystac_client.Client.open(STAC_URL, modifier=pc.sign_inplace)


def search_month(catalog, grid: Grid, year: int, month: int):
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"
    search = catalog.search(
        collections=[COLLECTION],
        bbox=list(grid.bbox),
        datetime=f"{start}/{end}",
        query={"eo:cloud_cover": {"lt": MAX_CLOUD_COVER}},
    )
    items = list(search.items())
    items.sort(key=lambda item: item.properties.get("eo:cloud_cover", 100.0))
    return items[:MAX_SCENES_PER_MONTH]


def _empty_month(key: str, year: int, month: int, status: str, scenes=0, scene_meta=None):
    return {
        "month": key, "year": year, "month_num": month, "status": status,
        "source": SOURCE_LABEL, "proxy_version": PROXY_VERSION,
        "scenes_used": scenes,
        "scene_ids": [meta["id"] for meta in (scene_meta or [])],
        "scene_metadata": scene_meta or [], "clear_pixel_pct": 0.0,
        "mean_ndvi_inside": None, "median_ndvi_inside": None,
        "ndvi_p10_inside": None, "ndvi_p90_inside": None,
        "canopy_ndvi_median": None, "ndre_median": None,
        "evi_median": None, "mfi_median": None, "mfi_positive_pct": None,
        "mndwi_median": None, "vegetation_coverage_proxy_pct": None,
        "open_water_pct": None, "open_nonvegetated_pct": None,
        "proxy_area_rai": None, "open_water_area_rai": None,
    }


def build_month(catalog, plot: dict[str, Any], geom, grid: Grid, inside: np.ndarray, year: int, month: int):
    key = month_key(year, month)
    plot_dir = PLOTS_DIR / str(plot["id"])
    plot_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = plot_dir / f"rgb_{key}.png"
    ndvi_path = plot_dir / f"ndvi_{key}.png"

    items = search_month(catalog, grid, year, month)
    scenes = []
    scene_meta = []

    for item in items:
        try:
            scl = read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            b02 = read_asset_to_grid(item, "B02", grid, Resampling.bilinear)
            b03 = read_asset_to_grid(item, "B03", grid, Resampling.bilinear)
            b04 = read_asset_to_grid(item, "B04", grid, Resampling.bilinear)
            b05 = read_asset_to_grid(item, "B05", grid, Resampling.bilinear)
            b06 = read_asset_to_grid(item, "B06", grid, Resampling.bilinear)
            b07 = read_asset_to_grid(item, "B07", grid, Resampling.bilinear)
            b08 = read_asset_to_grid(item, "B08", grid, Resampling.bilinear)
            b8a = read_asset_to_grid(item, "B8A", grid, Resampling.bilinear)
            b11 = read_asset_to_grid(item, "B11", grid, Resampling.bilinear)
            b12 = read_asset_to_grid(item, "B12", grid, Resampling.bilinear)

            clear = cloud_clear_mask(scl, b02, b03, b04, b05, b06, b07, b08, b8a, b11, b12)
            valid_inside = clear & inside
            clear_inside_ratio = float(valid_inside.sum() / max(1, int(inside.sum())))
            if clear_inside_ratio < 0.01:
                continue

            ndvi = safe_normalized_difference(b08, b04)
            ndre = safe_normalized_difference(b8a, b05)
            mndwi = safe_normalized_difference(b03, b11)
            evi = compute_evi(b02, b04, b08)
            mfi = compute_mfi(b04, b05, b06, b07, b8a, b12)

            rgb = np.stack([b04, b03, b02], axis=0).astype(np.float32)
            rgb[:, ~clear] = np.nan
            for index_array in (ndvi, ndre, mndwi, evi, mfi):
                index_array[~clear] = np.nan

            scenes.append({"rgb": rgb, "ndvi": ndvi, "ndre": ndre, "mndwi": mndwi, "evi": evi, "mfi": mfi})
            scene_meta.append({
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "catalog_cloud_cover_pct": item.properties.get("eo:cloud_cover"),
                "clear_inside_pct": round(clear_inside_ratio * 100.0, 2),
                "processing_baseline": item.properties.get("s2:processing_baseline"),
            })
        except Exception as exc:
            print(f"    {plot['code']} {key} scene {item.id}: {exc}")

    if not scenes:
        remove_stale(rgb_path); remove_stale(ndvi_path)
        return _empty_month(key, year, month, "no_data")

    def med(name):
        with np.errstate(all="ignore"):
            return np.nanmedian(np.stack([scene[name] for scene in scenes], axis=0), axis=0)

    composite_rgb = med("rgb")
    composite_ndvi = med("ndvi")
    composite_ndre = med("ndre")
    composite_mndwi = med("mndwi")
    composite_evi = med("evi")
    composite_mfi = med("mfi")

    valid_common_inside = (
        inside & np.isfinite(composite_ndvi) & np.isfinite(composite_ndre)
        & np.isfinite(composite_mndwi) & np.isfinite(composite_mfi)
    )
    valid_rgb = inside & np.isfinite(composite_rgb).all(axis=0)
    clear_ratio = float(valid_common_inside.sum() / max(1, int(inside.sum())))

    if clear_ratio < MIN_VALID_INSIDE_RATIO:
        remove_stale(rgb_path); remove_stale(ndvi_path)
        result = _empty_month(key, year, month, "insufficient_clear_pixels", len(scenes), scene_meta)
        result["clear_pixel_pct"] = round(clear_ratio * 100.0, 2)
        return result

    rgb_uint8 = np.moveaxis(np.clip(composite_rgb / RGB_REFLECTANCE_MAX * 255.0, 0, 255).astype(np.uint8), 0, -1)
    ndvi_rgb = palette_ndvi(np.nan_to_num(composite_ndvi, nan=-0.1))
    save_rgba(rgb_path, rgb_uint8, valid_rgb)
    save_rgba(ndvi_path, ndvi_rgb, valid_common_inside)

    ndvi_values = composite_ndvi[valid_common_inside]
    mndwi_values = composite_mndwi[valid_common_inside]

    emerged_vegetation = composite_ndvi > EMERGED_VEGETATION_NDVI_THRESHOLD
    submerged_mangrove_signal = composite_mfi > SUBMERGED_MANGROVE_MFI_THRESHOLD
    mangrove_proxy = valid_common_inside & (emerged_vegetation | submerged_mangrove_signal)

    open_water = valid_common_inside & (composite_mndwi > OPEN_WATER_MNDWI_THRESHOLD) & ~mangrove_proxy
    open_nonvegetated = valid_common_inside & ~mangrove_proxy & ~open_water

    valid_count = max(1, int(valid_common_inside.sum()))
    vegetation_proxy = float(mangrove_proxy.sum() / valid_count * 100.0)
    open_water_pct = float(open_water.sum() / valid_count * 100.0)
    open_nonveg_pct = float(open_nonvegetated.sum() / valid_count * 100.0)
    mfi_positive_pct = float((valid_common_inside & submerged_mangrove_signal).sum() / valid_count * 100.0)

    def finite_median(values: np.ndarray, digits: int = 4):
        finite = values[np.isfinite(values)]
        return round(float(np.median(finite)), digits) if finite.size else None

    status = "observed_single_scene" if len(scenes) == 1 else "observed_monthly_composite"
    return {
        "month": key, "year": year, "month_num": month, "status": status,
        "source": SOURCE_LABEL, "proxy_version": PROXY_VERSION,
        "scenes_used": len(scenes), "scene_ids": [meta["id"] for meta in scene_meta],
        "scene_metadata": scene_meta, "clear_pixel_pct": round(clear_ratio * 100.0, 2),
        "mean_ndvi_inside": round(float(np.mean(ndvi_values)), 4),
        "median_ndvi_inside": round(float(np.median(ndvi_values)), 4),
        "ndvi_p10_inside": round(float(np.percentile(ndvi_values, 10)), 4),
        "ndvi_p90_inside": round(float(np.percentile(ndvi_values, 90)), 4),
        "canopy_ndvi_median": finite_median(composite_ndvi[mangrove_proxy], 4),
        "ndre_median": finite_median(composite_ndre[mangrove_proxy], 4),
        "evi_median": finite_median(composite_evi[mangrove_proxy], 4),
        "mfi_median": finite_median(composite_mfi[mangrove_proxy], 5),
        "mfi_positive_pct": round(mfi_positive_pct, 1),
        "mndwi_median": round(float(np.median(mndwi_values)), 4),
        "vegetation_coverage_proxy_pct": round(vegetation_proxy, 1),
        "open_water_pct": round(open_water_pct, 1),
        "open_nonvegetated_pct": round(open_nonveg_pct, 1),
        "proxy_area_rai": round(float(plot["area_rai"]) * vegetation_proxy / 100.0, 2),
        "open_water_area_rai": round(float(plot["area_rai"]) * open_water_pct / 100.0, 2),
    }


def build_plot(plot: dict[str, Any]) -> dict[str, Any]:
    geom = shape(plot["geometry"])
    if geom.is_empty:
        raise ValueError("empty plot geometry")
    if not geom.is_valid:
        repaired = geom.buffer(0)
        if repaired.is_empty or not repaired.is_valid:
            raise ValueError("invalid plot geometry")
        geom = repaired

    grid = compute_grid(geom)
    inside = plot_mask(geom, grid)
    if not inside.any():
        raise ValueError("plot geometry covers zero target pixels")

    catalog = stac_client()
    timeseries = []
    print(f"[{plot['code']}] {plot['name']} ({grid.width}x{grid.height})")
    for year, month in MILESTONE_MONTHS:
        result = build_month(catalog, plot, geom, grid, inside, year, month)
        timeseries.append(result)
        print(f"  {result['month']}: {result['status']} scenes={result['scenes_used']} clear={result.get('clear_pixel_pct')}% proxy={result.get('vegetation_coverage_proxy_pct')}")

    # Endpoint semantics remain exact: no neighboring-date substitution.
    first = timeseries[0]
    last = timeseries[-1]
    initial = first.get("mean_ndvi_inside")
    current = last.get("mean_ndvi_inside")
    gain = round(current - initial, 4) if initial is not None and current is not None else None
    growth = round((gain / abs(initial)) * 100.0, 1) if gain is not None and abs(initial) >= 0.05 else None

    output = {
        "id": plot["id"], "code": plot["code"], "name": plot["name"],
        "province": plot["province"], "area_rai": plot["area_rai"],
        "parts_count": plot["parts_count"], "centroid": plot["centroid"],
        "bounds": plot["bounds"], "geometry": mapping(geom),
        "data_quality": "observed_only_no_interpolation_multi_index_v2",
        "source": SOURCE_LABEL, "proxy_version": PROXY_VERSION,
        "initial_ndvi": initial, "current_ndvi": current, "gain_ndvi": gain, "growth_pct": growth,
        "current_vegetation_proxy_pct": last.get("vegetation_coverage_proxy_pct"),
        "current_canopy_ndvi_median": last.get("canopy_ndvi_median"),
        "current_ndre_median": last.get("ndre_median"),
        "current_open_water_pct": last.get("open_water_pct"),
        "timeseries": timeseries,
    }

    plot_dir = PLOTS_DIR / str(plot["id"])
    metadata = {
        "plot_id": plot["id"], "plot_code": plot["code"], "source": SOURCE_LABEL,
        "collection": COLLECTION,
        "milestone_months": [month_key(y, m) for y, m in MILESTONE_MONTHS],
        "rules": {
            "interpolation": False, "synthetic_fallback": False,
            "clip_to_exact_geometry": True, "preserve_polygon_holes": True,
            "reflectance_scale_offset_from_stac": True,
            "cloud_scl_clear_classes": [4, 5, 6, 7],
            "cloud_buffer_pixels_on_10m_grid": CLOUD_BUFFER_PIXELS,
            "vegetation_proxy_version": PROXY_VERSION,
            "vegetation_proxy_definition": f"(NDVI > {EMERGED_VEGETATION_NDVI_THRESHOLD}) OR (MFI > {SUBMERGED_MANGROVE_MFI_THRESHOLD})",
            "open_water_definition": f"MNDWI > {OPEN_WATER_MNDWI_THRESHOLD} AND NOT vegetation_proxy",
            "ndre_definition": "(B8A - B05) / (B8A + B05)",
            "mndwi_definition": "(B03 - B11) / (B03 + B11)",
            "mfi_definition": "Jia et al. 2019 Sentinel-2 Mangrove Forest Index",
        },
        "native_resolution_m": {"ndvi": 10, "rgb": 10, "ndre": 20, "mndwi": 20, "mfi": 20},
        "grid": {"crs": "EPSG:4326", "target_resolution_approx_m": 10,
                 "bbox": list(grid.bbox), "width": grid.width, "height": grid.height},
        "dates": timeseries,
    }
    with (plot_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    return output


def main() -> int:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        plots = json.load(handle)

    plot_ids = os.environ.get("PRASAE_PLOT_IDS", "").strip()
    if plot_ids:
        wanted = {int(value.strip()) for value in plot_ids.split(",") if value.strip()}
        plots = [plot for plot in plots if int(plot["id"]) in wanted]

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(build_plot, plot): plot for plot in plots}
        for future in as_completed(futures):
            plot = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                failures.append({"id": plot["id"], "code": plot["code"], "error": str(exc)})
                print(f"[{plot['code']}] FAILED: {exc}")
                traceback.print_exc()

    results.sort(key=lambda item: item["id"])
    with OUTPUT_PATH.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    print(f"\nWrote {len(results)} plot records to {OUTPUT_PATH}")
    if failures:
        print(f"Failures: {len(failures)}")
        for failure in failures:
            print(f"  {failure}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
