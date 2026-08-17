#!/usr/bin/env python3
"""Build the canonical 12-date Sentinel-2 dataset for the Prasae dashboard.

Design rules
------------
* Exactly 12 declared observation/composite months. No nearest-month substitution.
* No interpolation between observations.
* No synthetic/fallback NDVI values.
* Polygon/MultiPolygon clipping happens on the raster grid and preserves holes.
* Pixels outside the plot geometry are transparent so Esri can remain the basemap.
* Every output date records source scene IDs and QA metadata.

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
MAX_SCENES_PER_MONTH = 8
MAX_WORKERS = int(os.environ.get("PRASAE_WORKERS", "4"))
MAX_CLOUD_COVER = 90
MIN_VALID_INSIDE_RATIO = 0.05
VEGETATION_NDVI_THRESHOLD = 0.25
RGB_REFLECTANCE_MAX = 3000.0

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
SOURCE_LABEL = "Microsoft Planetary Computer / Sentinel-2 L2A"


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


def read_asset_to_grid(item, asset_name: str, grid: Grid, resampling: Resampling) -> np.ndarray:
    """Reproject one asset band into the explicit WGS84 target grid."""
    href = item.assets[asset_name].href
    with rasterio.open(href) as src:
        destination = np.zeros((grid.height, grid.width), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=grid.transform,
            dst_crs="EPSG:4326",
            resampling=resampling,
            dst_nodata=0,
        )
    return destination


def plot_mask(geom, grid: Grid) -> np.ndarray:
    """True only inside the exact geometry, including correct hole semantics."""
    return geometry_mask(
        [mapping(geom)],
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        invert=True,
        all_touched=False,
    )


def cloud_clear_mask(scl: np.ndarray, b04: np.ndarray, b08: np.ndarray) -> np.ndarray:
    # Sentinel-2 SCL classes kept: 2 dark pixels, 4 vegetation, 5 bare soil,
    # 6 water, 7 unclassified. Excluded: nodata/saturated/shadow/cloud/cirrus/snow.
    clear_classes = np.isin(scl.astype(np.uint8), [2, 4, 5, 6, 7])
    return clear_classes & (b04 > 0) & (b08 > 0)


def palette_ndvi(ndvi: np.ndarray) -> np.ndarray:
    """Render NDVI with a fixed six-stop RdYlGn-like palette without matplotlib."""
    stops = np.array([-0.1, 0.08, 0.26, 0.44, 0.62, 0.8], dtype=np.float32)
    colors = np.array([
        [215, 48, 39],
        [252, 141, 89],
        [254, 224, 139],
        [217, 239, 139],
        [145, 207, 96],
        [26, 152, 80],
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
            b08 = read_asset_to_grid(item, "B08", grid, Resampling.bilinear)
            clear = cloud_clear_mask(scl, b04, b08)
            valid_inside = clear & inside
            inside_count = int(inside.sum())
            clear_inside_ratio = float(valid_inside.sum() / max(1, inside_count))
            if clear_inside_ratio < 0.01:
                continue

            denominator = b08 + b04
            ndvi = np.divide(
                b08 - b04,
                denominator,
                out=np.full_like(b08, np.nan, dtype=np.float32),
                where=denominator != 0,
            )
            rgb = np.stack([b04, b03, b02], axis=0).astype(np.float32)
            rgb[:, ~clear] = np.nan
            ndvi[~clear] = np.nan
            scenes.append((rgb, ndvi))
            scene_meta.append({
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "catalog_cloud_cover_pct": item.properties.get("eo:cloud_cover"),
                "clear_inside_pct": round(clear_inside_ratio * 100.0, 2),
            })
        except Exception as exc:
            print(f"    {plot['code']} {key} scene {item.id}: {exc}")

    if not scenes:
        remove_stale(rgb_path)
        remove_stale(ndvi_path)
        return {
            "month": key,
            "year": year,
            "month_num": month,
            "status": "no_data",
            "source": SOURCE_LABEL,
            "scenes_used": 0,
            "scene_ids": [],
            "clear_pixel_pct": 0.0,
            "mean_ndvi_inside": None,
            "median_ndvi_inside": None,
            "vegetation_coverage_proxy_pct": None,
        }

    rgb_stack = np.stack([scene[0] for scene in scenes], axis=0)
    ndvi_stack = np.stack([scene[1] for scene in scenes], axis=0)
    with np.errstate(all="ignore"):
        composite_rgb = np.nanmedian(rgb_stack, axis=0)
        composite_ndvi = np.nanmedian(ndvi_stack, axis=0)

    valid_ndvi_inside = inside & np.isfinite(composite_ndvi)
    valid_rgb = inside & np.isfinite(composite_rgb).all(axis=0)
    clear_ratio = float(valid_ndvi_inside.sum() / max(1, int(inside.sum())))

    if clear_ratio < MIN_VALID_INSIDE_RATIO:
        remove_stale(rgb_path)
        remove_stale(ndvi_path)
        return {
            "month": key,
            "year": year,
            "month_num": month,
            "status": "insufficient_clear_pixels",
            "source": SOURCE_LABEL,
            "scenes_used": len(scenes),
            "scene_ids": [meta["id"] for meta in scene_meta],
            "scene_metadata": scene_meta,
            "clear_pixel_pct": round(clear_ratio * 100.0, 2),
            "mean_ndvi_inside": None,
            "median_ndvi_inside": None,
            "vegetation_coverage_proxy_pct": None,
        }

    rgb_uint8 = np.moveaxis(np.clip(composite_rgb / RGB_REFLECTANCE_MAX * 255.0, 0, 255).astype(np.uint8), 0, -1)
    ndvi_rgb = palette_ndvi(np.nan_to_num(composite_ndvi, nan=-0.1))
    save_rgba(rgb_path, rgb_uint8, valid_rgb)
    save_rgba(ndvi_path, ndvi_rgb, valid_ndvi_inside)

    values = composite_ndvi[valid_ndvi_inside]
    vegetation_proxy = float(np.mean(values > VEGETATION_NDVI_THRESHOLD) * 100.0)
    status = "observed_single_scene" if len(scenes) == 1 else "observed_monthly_composite"
    return {
        "month": key,
        "year": year,
        "month_num": month,
        "status": status,
        "source": SOURCE_LABEL,
        "scenes_used": len(scenes),
        "scene_ids": [meta["id"] for meta in scene_meta],
        "scene_metadata": scene_meta,
        "clear_pixel_pct": round(clear_ratio * 100.0, 2),
        "mean_ndvi_inside": round(float(np.mean(values)), 4),
        "median_ndvi_inside": round(float(np.median(values)), 4),
        "vegetation_coverage_proxy_pct": round(vegetation_proxy, 1),
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
        print(f"  {result['month']}: {result['status']} scenes={result['scenes_used']} clear={result.get('clear_pixel_pct')}%")

    first = timeseries[0]
    last = timeseries[-1]
    initial = first["mean_ndvi_inside"]
    current = last["mean_ndvi_inside"]
    gain = round(current - initial, 4) if initial is not None and current is not None else None
    growth = round((gain / abs(initial)) * 100.0, 1) if gain is not None and abs(initial) >= 0.05 else None
    current_proxy = last["vegetation_coverage_proxy_pct"]

    output = {
        "id": plot["id"],
        "code": plot["code"],
        "name": plot["name"],
        "province": plot["province"],
        "area_rai": plot["area_rai"],
        "parts_count": plot["parts_count"],
        "centroid": plot["centroid"],
        "bounds": plot["bounds"],
        "geometry": mapping(geom),
        "data_quality": "observed_only_no_interpolation",
        "source": SOURCE_LABEL,
        "initial_ndvi": initial,
        "current_ndvi": current,
        "gain_ndvi": gain,
        "growth_pct": growth,
        "current_vegetation_proxy_pct": current_proxy,
        "timeseries": timeseries,
    }

    plot_dir = PLOTS_DIR / str(plot["id"])
    metadata = {
        "plot_id": plot["id"],
        "plot_code": plot["code"],
        "source": SOURCE_LABEL,
        "collection": COLLECTION,
        "milestone_months": [month_key(y, m) for y, m in MILESTONE_MONTHS],
        "rules": {
            "interpolation": False,
            "synthetic_fallback": False,
            "clip_to_exact_geometry": True,
            "preserve_polygon_holes": True,
            "vegetation_proxy_definition": f"NDVI > {VEGETATION_NDVI_THRESHOLD}",
        },
        "grid": {
            "crs": "EPSG:4326",
            "bbox": list(grid.bbox),
            "width": grid.width,
            "height": grid.height,
        },
        "dates": timeseries,
    }
    with (plot_dir / "metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    return output


def main() -> int:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        plots = json.load(handle)
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
