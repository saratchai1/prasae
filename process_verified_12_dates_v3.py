#!/usr/bin/env python3
"""Conservative mangrove metrics v3 built on the canonical Sentinel-2 pipeline.

Key distinction:
- Vegetation Coverage Proxy is conservative: NDVI > 0.25 only.
- MFI is NOT merged into coverage. It is reported separately as a diagnostic
  for possible submerged mangrove signal, especially where MNDWI indicates water.
- NDRE/EVI describe vegetation condition only on pixels passing the conservative
  vegetation mask.
"""

from __future__ import annotations

import json
import numpy as np
from rasterio.warp import Resampling
import process_verified_12_dates as base

PROXY_VERSION = "v3_conservative_ndvi_mfi_diagnostic"
base.PROXY_VERSION = PROXY_VERSION


def empty_month(key, year, month, status, scenes=0, scene_meta=None):
    result = base._empty_month(key, year, month, status, scenes, scene_meta)
    result.update({
        "proxy_version": PROXY_VERSION,
        "submerged_mangrove_signal_pct": None,
        "mfi_only_signal_pct": None,
    })
    return result


def build_month_v3(catalog, plot, geom, grid, inside, year, month):
    key = base.month_key(year, month)
    plot_dir = base.PLOTS_DIR / str(plot["id"])
    plot_dir.mkdir(parents=True, exist_ok=True)
    rgb_path = plot_dir / f"rgb_{key}.png"
    ndvi_path = plot_dir / f"ndvi_{key}.png"

    items = base.search_month(catalog, grid, year, month)
    scenes = []
    scene_meta = []

    for item in items:
        try:
            scl = base.read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            b02 = base.read_asset_to_grid(item, "B02", grid, Resampling.bilinear)
            b03 = base.read_asset_to_grid(item, "B03", grid, Resampling.bilinear)
            b04 = base.read_asset_to_grid(item, "B04", grid, Resampling.bilinear)
            b05 = base.read_asset_to_grid(item, "B05", grid, Resampling.bilinear)
            b06 = base.read_asset_to_grid(item, "B06", grid, Resampling.bilinear)
            b07 = base.read_asset_to_grid(item, "B07", grid, Resampling.bilinear)
            b08 = base.read_asset_to_grid(item, "B08", grid, Resampling.bilinear)
            b8a = base.read_asset_to_grid(item, "B8A", grid, Resampling.bilinear)
            b11 = base.read_asset_to_grid(item, "B11", grid, Resampling.bilinear)
            b12 = base.read_asset_to_grid(item, "B12", grid, Resampling.bilinear)

            clear = base.cloud_clear_mask(
                scl, b02, b03, b04, b05, b06, b07, b08, b8a, b11, b12
            )
            valid_inside = clear & inside
            clear_inside_ratio = float(valid_inside.sum() / max(1, int(inside.sum())))
            if clear_inside_ratio < 0.01:
                continue

            ndvi = base.safe_normalized_difference(b08, b04)
            ndre = base.safe_normalized_difference(b8a, b05)
            mndwi = base.safe_normalized_difference(b03, b11)
            evi = base.compute_evi(b02, b04, b08)
            mfi = base.compute_mfi(b04, b05, b06, b07, b8a, b12)
            rgb = np.stack([b04, b03, b02], axis=0).astype(np.float32)
            rgb[:, ~clear] = np.nan
            for arr in (ndvi, ndre, mndwi, evi, mfi):
                arr[~clear] = np.nan

            scenes.append({"rgb": rgb, "ndvi": ndvi, "ndre": ndre,
                           "mndwi": mndwi, "evi": evi, "mfi": mfi})
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
        base.remove_stale(rgb_path); base.remove_stale(ndvi_path)
        return empty_month(key, year, month, "no_data")

    def med(name):
        with np.errstate(all="ignore"):
            return np.nanmedian(np.stack([scene[name] for scene in scenes], axis=0), axis=0)

    composite_rgb = med("rgb")
    composite_ndvi = med("ndvi")
    composite_ndre = med("ndre")
    composite_mndwi = med("mndwi")
    composite_evi = med("evi")
    composite_mfi = med("mfi")

    valid = (inside & np.isfinite(composite_ndvi) & np.isfinite(composite_ndre)
             & np.isfinite(composite_mndwi) & np.isfinite(composite_mfi))
    valid_rgb = inside & np.isfinite(composite_rgb).all(axis=0)
    clear_ratio = float(valid.sum() / max(1, int(inside.sum())))
    if clear_ratio < base.MIN_VALID_INSIDE_RATIO:
        base.remove_stale(rgb_path); base.remove_stale(ndvi_path)
        result = empty_month(key, year, month, "insufficient_clear_pixels", len(scenes), scene_meta)
        result["clear_pixel_pct"] = round(clear_ratio * 100.0, 2)
        return result

    rgb_uint8 = np.moveaxis(
        np.nan_to_num(np.clip(composite_rgb / base.RGB_REFLECTANCE_MAX * 255.0, 0, 255), nan=0.0).astype(np.uint8),
        0, -1,
    )
    ndvi_rgb = base.palette_ndvi(np.nan_to_num(composite_ndvi, nan=-0.1))
    base.save_rgba(rgb_path, rgb_uint8, valid_rgb)
    base.save_rgba(ndvi_path, ndvi_rgb, valid)

    ndvi_values = composite_ndvi[valid]
    mndwi_values = composite_mndwi[valid]

    vegetation = valid & (composite_ndvi > base.EMERGED_VEGETATION_NDVI_THRESHOLD)
    water = valid & (composite_mndwi > base.OPEN_WATER_MNDWI_THRESHOLD) & ~vegetation
    open_nonvegetated = valid & ~vegetation & ~water
    mfi_signal = valid & (composite_mfi > base.SUBMERGED_MANGROVE_MFI_THRESHOLD)
    mfi_only_signal = mfi_signal & ~vegetation
    submerged_mangrove_signal = mfi_signal & water

    valid_count = max(1, int(valid.sum()))
    pct = lambda mask: float(mask.sum() / valid_count * 100.0)
    vegetation_pct = pct(vegetation)
    water_pct = pct(water)
    open_nonveg_pct = pct(open_nonvegetated)

    def finite_median(values, digits=4):
        finite = values[np.isfinite(values)]
        return round(float(np.median(finite)), digits) if finite.size else None

    status = "observed_single_scene" if len(scenes) == 1 else "observed_monthly_composite"
    return {
        "month": key, "year": year, "month_num": month, "status": status,
        "source": base.SOURCE_LABEL, "proxy_version": PROXY_VERSION,
        "scenes_used": len(scenes), "scene_ids": [m["id"] for m in scene_meta],
        "scene_metadata": scene_meta, "clear_pixel_pct": round(clear_ratio * 100.0, 2),
        "mean_ndvi_inside": round(float(np.mean(ndvi_values)), 4),
        "median_ndvi_inside": round(float(np.median(ndvi_values)), 4),
        "ndvi_p10_inside": round(float(np.percentile(ndvi_values, 10)), 4),
        "ndvi_p90_inside": round(float(np.percentile(ndvi_values, 90)), 4),
        "canopy_ndvi_median": finite_median(composite_ndvi[vegetation], 4),
        "ndre_median": finite_median(composite_ndre[vegetation], 4),
        "evi_median": finite_median(composite_evi[vegetation], 4),
        "mfi_median": finite_median(composite_mfi[mfi_signal], 5),
        "mfi_positive_pct": round(pct(mfi_signal), 1),
        "mfi_only_signal_pct": round(pct(mfi_only_signal), 1),
        "submerged_mangrove_signal_pct": round(pct(submerged_mangrove_signal), 1),
        "mndwi_median": round(float(np.median(mndwi_values)), 4),
        "vegetation_coverage_proxy_pct": round(vegetation_pct, 1),
        "open_water_pct": round(water_pct, 1),
        "open_nonvegetated_pct": round(open_nonveg_pct, 1),
        "proxy_area_rai": round(float(plot["area_rai"]) * vegetation_pct / 100.0, 2),
        "open_water_area_rai": round(float(plot["area_rai"]) * water_pct / 100.0, 2),
    }


base.build_month = build_month_v3
_original_build_plot = base.build_plot


def build_plot_v3(plot):
    output = _original_build_plot(plot)
    output["data_quality"] = "observed_only_no_interpolation_multi_index_v3"
    output["proxy_version"] = PROXY_VERSION
    output["current_submerged_mangrove_signal_pct"] = output["timeseries"][-1].get("submerged_mangrove_signal_pct")

    metadata_path = base.PLOTS_DIR / str(plot["id"]) / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["proxy_version"] = PROXY_VERSION
        rules = metadata.setdefault("rules", {})
        rules["vegetation_proxy_version"] = PROXY_VERSION
        rules["vegetation_proxy_definition"] = f"NDVI > {base.EMERGED_VEGETATION_NDVI_THRESHOLD}; conservative green-cover proxy"
        rules["mfi_role"] = f"diagnostic only: MFI > {base.SUBMERGED_MANGROVE_MFI_THRESHOLD}; not merged into vegetation coverage"
        rules["submerged_mangrove_signal_definition"] = (
            f"MNDWI > {base.OPEN_WATER_MNDWI_THRESHOLD} AND MFI > {base.SUBMERGED_MANGROVE_MFI_THRESHOLD} AND NOT vegetation_proxy"
        )
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


base.build_plot = build_plot_v3

if __name__ == "__main__":
    raise SystemExit(base.main())
