#!/usr/bin/env python3
"""Build browser-only Sentinel-2 spectral assets for the authoritative PDD22 dataset.

The browser package follows the frozen scene selections in data/pdd22_satellite,
uses only the 22 PDD participating polygons, and writes 8-bit visualization PNGs.
The scientific NDVI/FCD pipeline continues to use float BOA reflectance; these PNGs
must never be used for carbon accounting or scientific statistics.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.warp import Resampling
from shapely.geometry import shape

import process_pdd22_satellite_pipeline as sat

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data/pdd22/plots_catalog.json"
CLEAN = ROOT / "data/pdd22_satellite/plots"
OUT = ROOT / "data/pdd22_spectral/plots"

BANDS = (
    "B02", "B03", "B04",
    "B05", "B06", "B07",
    "B08", "B8A", "B11", "B12",
)
NATIVE_RESOLUTION_M = {
    "B02": 10, "B03": 10, "B04": 10, "B08": 10,
    "B05": 20, "B06": 20, "B07": 20, "B8A": 20,
    "B11": 20, "B12": 20,
}
REFLECTANCE_MIN = 0.0
REFLECTANCE_MAX = 0.40
WORKERS = max(1, int(os.environ.get("PDD22_SPECTRAL_WORKERS", "2")))
RETRIES = 6
SHARD_COUNT = max(1, int(os.environ.get("PDD22_SPECTRAL_SHARD_COUNT", "1")))
SHARD_INDEX = int(os.environ.get("PDD22_SPECTRAL_SHARD_INDEX", "0"))


def load_plots():
    plots = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert len(plots) == 22
    assert round(sum(float(p["area_rai"]) for p in plots), 2) == 6775.53
    if not 0 <= SHARD_INDEX < SHARD_COUNT:
        raise ValueError(f"invalid shard {SHARD_INDEX}/{SHARD_COUNT}")
    return [plot for i, plot in enumerate(plots) if i % SHARD_COUNT == SHARD_INDEX]


def load_clean(code):
    return json.loads((CLEAN / code / "metadata.json").read_text(encoding="utf-8"))


def get_item_retry(client, scene_id):
    """Use the same STAC lookup form that already works in FCD V3."""
    last = None
    for attempt in range(RETRIES):
        try:
            item = client.get_item(scene_id, collection_id=sat.COLLECTION)
            if item is None:
                found = list(
                    client.search(
                        collections=[sat.COLLECTION],
                        ids=[scene_id],
                        max_items=1,
                    ).items()
                )
                item = found[0] if found else None
            if item is None:
                raise RuntimeError(f"STAC item not found: {scene_id}")
            sat.pc.sign_inplace(item)
            return item
        except Exception as exc:
            last = exc
            if attempt == RETRIES - 1:
                break
            delay = min(20, 2 ** attempt)
            print(
                f"STAC retry {attempt + 1}/{RETRIES} {scene_id}: {exc}; {delay}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"Failed STAC item {scene_id}: {last}")


def encode_band(arr, valid, path):
    scaled = np.clip(
        (arr - REFLECTANCE_MIN) / (REFLECTANCE_MAX - REFLECTANCE_MIN),
        0.0,
        1.0,
    )
    luma = np.nan_to_num(scaled * 255.0, nan=0.0).astype(np.uint8)
    alpha = np.where(valid, 255, 0).astype(np.uint8)
    Image.fromarray(np.stack([luma, alpha], axis=-1), mode="LA").save(
        path, "PNG", optimize=True
    )


def build_plot(client, plot):
    code = plot["code"]
    clean = load_clean(code)
    geom = shape(plot["geometry"])
    grid = sat.compute_fixed_grid(geom)
    inside = sat.get_pdd_polygon_mask(geom, grid)
    out_dir = OUT / code
    out_dir.mkdir(parents=True, exist_ok=True)
    dates = []

    print(f"[{code}] {grid.width}x{grid.height}", flush=True)
    for obs in clean["observations"]:
        month = obs["month"]
        scene_ids = list(obs.get("selected_scene_ids") or [])
        if int(obs.get("valid_pixel_count", 0)) == 0 or not scene_ids:
            dates.append(
                {
                    "month": month,
                    "status": "no_data",
                    "qa": obs.get("qa", "NO_DATA"),
                    "analysis_mode": obs.get("analysis_mode", "no_data"),
                    "coverage_pct": float(obs.get("coverage_pct", 0.0)),
                    "files": {},
                    "scene_ids": [],
                }
            )
            continue

        scenes = []
        for scene_id in scene_ids:
            item = get_item_retry(client, scene_id)
            scl = sat.read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            all_bands = sat.read_all_bands_concurrent(item, grid)
            clear = sat.cloud_clear_mask(
                scl, *[all_bands[b] for b in sat.REQUIRED_BANDS]
            )
            masked = {}
            for band in BANDS:
                arr = all_bands[band].copy()
                arr[~clear] = np.nan
                masked[band] = arr
            scenes.append(masked)

        composite = {}
        with np.errstate(all="ignore"):
            for band in BANDS:
                composite[band] = np.nanmedian(
                    np.stack([scene[band] for scene in scenes], axis=0), axis=0
                ).astype(np.float32)

        valid = inside.copy()
        for band in BANDS:
            valid &= np.isfinite(composite[band])

        coverage = float(valid.sum() / max(1, int(inside.sum())) * 100.0)
        expected = float(obs.get("coverage_pct", 0.0))
        if abs(coverage - expected) > 0.35:
            raise RuntimeError(
                f"{code} {month} coverage mismatch "
                f"spectral={coverage:.2f} clean={expected:.2f}"
            )

        files = {}
        for band in BANDS:
            filename = f"band_{band}_{month}.png"
            encode_band(composite[band], valid, out_dir / filename)
            files[band] = filename

        dates.append(
            {
                "month": month,
                "status": "available",
                "qa": obs.get("qa"),
                "analysis_mode": obs.get("analysis_mode"),
                "coverage_pct": round(coverage, 2),
                "files": files,
                "scene_ids": scene_ids,
            }
        )
        print(
            f"  {month} {obs.get('qa')} {coverage:.2f}% scenes={len(scene_ids)}",
            flush=True,
        )

    manifest = {
        "schema_version": "3.0-pdd22-10band",
        "asset_role": "browser_visualization_only",
        "plot_code": code,
        "pdd_area_rai": float(plot["area_rai"]),
        "bounds": plot["bounds"],
        "width": grid.width,
        "height": grid.height,
        "display_grid_resolution_m": grid.resolution_m,
        "bands": list(BANDS),
        "native_resolution_m": NATIVE_RESOLUTION_M,
        "encoding": {
            "format": "PNG LA (8-bit luminance + alpha)",
            "reflectance_min": REFLECTANCE_MIN,
            "reflectance_max": REFLECTANCE_MAX,
            "formula": "reflectance ~= luminance / 255 * 0.40",
            "warning": (
                "Visualization only; analytical metrics use original float "
                "reflectance. B05/B06/B07/B8A/B11/B12 are native 20 m even "
                "when aligned to the common browser grid."
            ),
        },
        "rules": {
            "pdd_participating_boundary_only": True,
            "frozen_clean_scene_selection": True,
            "adjacent_month_fallback": False,
            "interpolation": False,
            "synthetic_imagery": False,
        },
        "dates": dates,
    }
    (out_dir / "spectral_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return code, dates


def main():
    plots = load_plots()
    OUT.mkdir(parents=True, exist_ok=True)
    client = sat.pystac_client.Client.open(
        sat.STAC_URL, modifier=sat.pc.sign_inplace
    )
    results = []
    print(f"Shard {SHARD_INDEX}/{SHARD_COUNT}: {len(plots)} plots", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(build_plot, client, plot): plot for plot in plots}
        for future in as_completed(futures):
            plot = futures[future]
            code, dates = future.result()
            results.append((code, dates))
            print(f"DONE {code}", flush=True)

    available = sum(
        1 for _, dates in results for d in dates if d["status"] == "available"
    )
    summary = {
        "shard_index": SHARD_INDEX,
        "shard_count": SHARD_COUNT,
        "plot_count": len(results),
        "plot_codes": sorted(code for code, _ in results),
        "available_plot_months": available,
        "bands": list(BANDS),
    }
    (OUT.parent / f"shard_{SHARD_INDEX}.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(
        f"Completed shard {SHARD_INDEX}: {len(results)} plots; "
        f"{available} available plot-months",
        flush=True,
    )


if __name__ == "__main__":
    main()
