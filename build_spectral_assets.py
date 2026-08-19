#!/usr/bin/env python3
"""Build lightweight Sentinel-2 band assets for the browser Spectral Studio.

Design goals
------------
- Exactly the same 12 declared months used by the monitoring dashboard.
- No nearest-month substitution, +/- day fallback, interpolation, or synthetic imagery.
- Sentinel-2 L2A bottom-of-atmosphere reflectance from Microsoft Planetary Computer.
- SCL cloud/shadow/snow masking and exact plot-polygon alpha masking.
- Fixed reflectance encoding (0.00..0.40 -> 0..255) so browser RGB mixing preserves
  relative band magnitudes across dates. These 8-bit files are for visualization only;
  analytical metrics continue to use the original float reflectance pipeline.
- Output only six bands needed for custom visualization: B02, B03, B04, B08, B11, B12.
- Full-portfolio builds can be split deterministically across GitHub Actions shards.

Environment variables
---------------------
PRASAE_PLOT_IDS: comma-separated plot ids, default "all" for the full portfolio.
PRASAE_SPECTRAL_MONTHS: comma-separated YYYY-MM values, default all 12 dates.
PRASAE_SPECTRAL_MAX_SCENES: max unique acquisitions per month, default 5.
PRASAE_WORKERS: plot-level workers, default 2.
PRASAE_SPECTRAL_OUTPUT_ROOT: output root, default data/plots.
PRASAE_SHARD_COUNT: total shard count, default 1.
PRASAE_SHARD_INDEX: zero-based shard index, default 0.
"""

from __future__ import annotations

import calendar
import json
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from rasterio.warp import Resampling
from shapely.geometry import shape

import process_verified_12_dates as base

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "data" / "plots_catalog.json"
PLOTS_DIR = Path(os.environ.get("PRASAE_SPECTRAL_OUTPUT_ROOT", str(BASE_DIR / "data" / "plots")))
BANDS = ("B02", "B03", "B04", "B08", "B11", "B12")
REFLECTANCE_MIN = 0.0
REFLECTANCE_MAX = 0.40
MIN_VALID_INSIDE_RATIO = 0.05
MAX_SCENES = int(os.environ.get("PRASAE_SPECTRAL_MAX_SCENES", "5"))
MAX_WORKERS = int(os.environ.get("PRASAE_WORKERS", "2"))
SHARD_COUNT = max(1, int(os.environ.get("PRASAE_SHARD_COUNT", "1")))
SHARD_INDEX = int(os.environ.get("PRASAE_SHARD_INDEX", "0"))


def selected_months() -> list[tuple[int, int]]:
    raw = os.environ.get("PRASAE_SPECTRAL_MONTHS", "").strip()
    allowed = {base.month_key(y, m): (y, m) for y, m in base.MILESTONE_MONTHS}
    if not raw:
        return list(base.MILESTONE_MONTHS)
    result = []
    for token in raw.split(","):
        token = token.strip()
        if token not in allowed:
            raise ValueError(f"Unsupported spectral month {token}; must be one of {sorted(allowed)}")
        result.append(allowed[token])
    return result


def selected_plots(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = os.environ.get("PRASAE_PLOT_IDS", "all").strip().lower()
    if raw == "all":
        selected = list(catalog)
    else:
        ids = {int(token.strip()) for token in raw.split(",") if token.strip()}
        selected = [plot for plot in catalog if int(plot["id"]) in ids]

    if not 0 <= SHARD_INDEX < SHARD_COUNT:
        raise ValueError(f"Invalid shard {SHARD_INDEX}/{SHARD_COUNT}")
    if SHARD_COUNT > 1:
        selected = [plot for position, plot in enumerate(selected) if position % SHARD_COUNT == SHARD_INDEX]
    return selected


def processing_baseline_number(item) -> float:
    raw = str(item.properties.get("s2:processing_baseline") or "0")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def unique_acquisitions(items) -> list:
    """Deduplicate reprocessed copies of the same acquisition."""
    chosen = {}
    for item in items:
        dt = item.datetime.isoformat() if item.datetime else item.id
        tile = (
            item.properties.get("s2:mgrs_tile")
            or item.properties.get("mgrs:tile")
            or item.properties.get("s2:granule_id")
            or "unknown"
        )
        key = (dt, tile)
        previous = chosen.get(key)
        if previous is None or processing_baseline_number(item) > processing_baseline_number(previous):
            chosen[key] = item
    result = list(chosen.values())
    result.sort(key=lambda item: (
        float(item.properties.get("eo:cloud_cover", 100.0)),
        item.datetime.isoformat() if item.datetime else item.id,
    ))
    return result[:MAX_SCENES]


def search_month_exact(catalog, grid: base.Grid, year: int, month: int):
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"
    search = catalog.search(
        collections=[base.COLLECTION],
        bbox=list(grid.bbox),
        datetime=f"{start}/{end}",
        query={"eo:cloud_cover": {"lt": base.MAX_CLOUD_COVER}},
    )
    return unique_acquisitions(list(search.items()))


def encode_band_luma(array: np.ndarray, valid: np.ndarray, path: Path) -> None:
    scaled = np.clip(
        (array - REFLECTANCE_MIN) / (REFLECTANCE_MAX - REFLECTANCE_MIN),
        0.0,
        1.0,
    )
    luma = np.nan_to_num(scaled * 255.0, nan=0.0).astype(np.uint8)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    la = np.stack([luma, alpha], axis=-1)
    Image.fromarray(la, mode="LA").save(path, "PNG", optimize=True)


def remove_month_assets(plot_dir: Path, month_key: str) -> None:
    for band in BANDS:
        base.remove_stale(plot_dir / f"band_{band}_{month_key}.png")


def build_month(catalog, plot: dict[str, Any], geom, grid: base.Grid, inside: np.ndarray, year: int, month: int):
    key = base.month_key(year, month)
    plot_dir = PLOTS_DIR / str(plot["id"])
    plot_dir.mkdir(parents=True, exist_ok=True)
    items = search_month_exact(catalog, grid, year, month)

    scene_bands: list[dict[str, np.ndarray]] = []
    scene_meta = []
    for item in items:
        try:
            scl = base.read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            bands = {
                band: base.read_asset_to_grid(item, band, grid, Resampling.bilinear)
                for band in BANDS
            }
            clear = base.cloud_clear_mask(scl, *(bands[band] for band in BANDS))
            valid_inside = clear & inside
            clear_inside_ratio = float(valid_inside.sum() / max(1, int(inside.sum())))
            if clear_inside_ratio < 0.01:
                continue
            for band in BANDS:
                bands[band][~clear] = np.nan
            scene_bands.append(bands)
            scene_meta.append({
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "catalog_cloud_cover_pct": item.properties.get("eo:cloud_cover"),
                "clear_inside_pct": round(clear_inside_ratio * 100.0, 2),
                "processing_baseline": item.properties.get("s2:processing_baseline"),
            })
        except Exception as exc:
            print(f"    {plot['code']} {key} scene {item.id}: {exc}")

    if not scene_bands:
        remove_month_assets(plot_dir, key)
        return {
            "month": key,
            "status": "no_data",
            "scenes_used": 0,
            "clear_pixel_pct": 0.0,
            "files": {},
            "scene_metadata": [],
        }

    composites = {}
    with np.errstate(all="ignore"):
        for band in BANDS:
            composites[band] = np.nanmedian(
                np.stack([scene[band] for scene in scene_bands], axis=0), axis=0
            ).astype(np.float32)

    valid = inside.copy()
    for band in BANDS:
        valid &= np.isfinite(composites[band])
    clear_ratio = float(valid.sum() / max(1, int(inside.sum())))
    if clear_ratio < MIN_VALID_INSIDE_RATIO:
        remove_month_assets(plot_dir, key)
        return {
            "month": key,
            "status": "insufficient_clear_pixels",
            "scenes_used": len(scene_bands),
            "clear_pixel_pct": round(clear_ratio * 100.0, 2),
            "files": {},
            "scene_metadata": scene_meta,
        }

    files = {}
    for band in BANDS:
        filename = f"band_{band}_{key}.png"
        encode_band_luma(composites[band], valid, plot_dir / filename)
        files[band] = filename

    return {
        "month": key,
        "status": "observed_single_scene" if len(scene_bands) == 1 else "observed_monthly_composite",
        "scenes_used": len(scene_bands),
        "clear_pixel_pct": round(clear_ratio * 100.0, 2),
        "files": files,
        "scene_metadata": scene_meta,
    }


def build_plot(plot: dict[str, Any], months: list[tuple[int, int]]) -> dict[str, Any]:
    geom = shape(plot["geometry"])
    grid = base.compute_grid(geom)
    inside = base.plot_mask(geom, grid)
    catalog = base.stac_client()
    print(f"[{plot['code']}] spectral assets {grid.width}x{grid.height}")
    dates = []
    for year, month in months:
        result = build_month(catalog, plot, geom, grid, inside, year, month)
        dates.append(result)
        print(
            f"  {result['month']}: {result['status']} scenes={result['scenes_used']} "
            f"clear={result['clear_pixel_pct']}%"
        )

    manifest = {
        "schema_version": "1.0",
        "asset_role": "browser_visualization_only",
        "source": base.SOURCE_LABEL,
        "plot_id": int(plot["id"]),
        "plot_code": plot["code"],
        "plot_name": plot["name"],
        "bbox": list(grid.bbox),
        "width": grid.width,
        "height": grid.height,
        "bands": list(BANDS),
        "encoding": {
            "format": "PNG LA (8-bit luminance + alpha)",
            "reflectance_min": REFLECTANCE_MIN,
            "reflectance_max": REFLECTANCE_MAX,
            "formula": "reflectance ~= luminance / 255 * 0.40",
            "warning": "Visualization asset only; do not use these quantized PNGs for scientific statistics.",
        },
        "rules": {
            "exact_declared_month_only": True,
            "nearest_month_fallback": False,
            "interpolation": False,
            "synthetic_imagery": False,
            "cloud_mask": "Sentinel-2 SCL + contamination buffer",
            "plot_mask": "exact Polygon/MultiPolygon including holes",
        },
        "dates": dates,
    }
    manifest_path = PLOTS_DIR / str(plot["id"]) / "spectral_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    plots = selected_plots(catalog)
    months = selected_months()
    if not plots:
        raise RuntimeError(f"No plots selected for shard {SHARD_INDEX}/{SHARD_COUNT}")
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    print(
        f"Building Spectral Studio assets for {len(plots)} plot(s), {len(months)} month(s), "
        f"shard={SHARD_INDEX}/{SHARD_COUNT}, output={PLOTS_DIR}"
    )

    manifests = []
    with ThreadPoolExecutor(max_workers=max(1, MAX_WORKERS)) as executor:
        futures = {executor.submit(build_plot, plot, months): plot for plot in plots}
        for future in as_completed(futures):
            plot = futures[future]
            try:
                manifests.append(future.result())
            except Exception:
                print(f"FAILED {plot['code']}")
                traceback.print_exc()
                raise

    observed = sum(
        1
        for manifest in manifests
        for item in manifest["dates"]
        if item["status"] in {"observed_single_scene", "observed_monthly_composite"}
    )
    print(f"Completed {len(manifests)} plot manifest(s); {observed} observed date(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
