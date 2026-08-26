#!/usr/bin/env python3
"""PDD22 FCD screening V3 using the frozen cleaned Sentinel-2 scene selections.

Purpose
-------
Recompute Green / Yellow / Red FCD screening on the authoritative 22 PDD
participating polygons using the exact selected Sentinel-2 scenes recorded in
``data/pdd22_satellite``.  The PDD-style AVI/BSI/CSI structure, corrected VD
direction, and 2023 provincial PDD anchors are retained from V2.

This is a screening product only.  It is not an exact reproduction of the PDD
Landsat-8 workflow and is not a verified carbon-credit calculation.
"""
from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image
from rasterio.warp import Resampling
from shapely.geometry import shape

import process_pdd22_fcd as fcdsrc
import process_pdd22_fcd_v2 as v2
import process_pdd22_satellite_pipeline as sat
from pdd22_config import PDD_TOTAL_PROJECT_AREA_RAI

ROOT = Path(__file__).resolve().parent
PDD_CATALOG = ROOT / "data/pdd22/plots_catalog.json"
SAT_ROOT = ROOT / "data/pdd22_satellite/plots"
OUT = ROOT / "data/pdd22_v3"
MAPS = OUT / "maps"
REFERENCE = (2023, 3)
TARGET_MONTHS = [(2024, 3), (2025, 3), (2026, 3), (2026, 8)]
WORKERS = 4
COLORS = {1: (220, 53, 69), 2: (255, 193, 7), 3: (40, 167, 69), 4: (23, 162, 184)}


def mk(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def load_plots():
    plots = json.loads(PDD_CATALOG.read_text(encoding="utf-8"))
    assert len(plots) == 22
    assert round(sum(float(p["area_rai"]) for p in plots), 2) == PDD_TOTAL_PROJECT_AREA_RAI
    return plots


def load_clean_metadata(code: str):
    path = SAT_ROOT / code / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


def find_clean_observation(code: str, year: int, month: int):
    key = mk(year, month)
    meta = load_clean_metadata(code)
    for obs in meta["observations"]:
        if obs["month"] == key:
            return obs
    raise KeyError(f"{code}: missing cleaned observation {key}")


def empty_result(plot, clean_obs=None):
    geom = shape(plot["geometry"])
    grid = sat.compute_fixed_grid(geom)
    inside = sat.get_pdd_polygon_mask(geom, grid)
    return {
        "status": "no_data",
        "grid": grid,
        "inside": inside,
        "valid": np.zeros_like(inside, dtype=bool),
        "scene_metadata": [],
        "scenes_used": 0,
        "clear_pixel_pct": 0.0,
        "qa": (clean_obs or {}).get("qa", "NO_DATA"),
        "analysis_mode": (clean_obs or {}).get("analysis_mode", "no_data"),
    }


def build_from_clean_selection(catalog, plot, year: int, month: int):
    clean = find_clean_observation(plot["code"], year, month)
    scene_ids = list(clean.get("selected_scene_ids") or [])
    if clean.get("valid_pixel_count", 0) == 0 or not scene_ids:
        return empty_result(plot, clean)

    geom = shape(plot["geometry"])
    grid = sat.compute_fixed_grid(geom)
    inside = sat.get_pdd_polygon_mask(geom, grid)
    found = list(catalog.search(collections=[sat.COLLECTION], ids=scene_ids).items())
    by_id = {item.id: item for item in found}
    missing = [scene_id for scene_id in scene_ids if scene_id not in by_id]
    if missing:
        raise RuntimeError(f"{plot['code']} {mk(year, month)} missing STAC IDs: {missing}")

    scenes = []
    for scene_id in scene_ids:
        item = by_id[scene_id]
        scl = sat.read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
        bands = sat.read_all_bands_concurrent(item, grid)
        clear = sat.cloud_clear_mask(scl, *[bands[b] for b in sat.REQUIRED_BANDS])
        masked = {}
        for band_name, arr in bands.items():
            arr = arr.copy()
            arr[~clear] = np.nan
            masked[band_name] = arr
        scenes.append(masked)

    composite = {}
    with np.errstate(all="ignore"):
        for band_name in sat.REQUIRED_BANDS:
            composite[band_name] = np.nanmedian(
                np.stack([scene[band_name] for scene in scenes], axis=0), axis=0
            ).astype(np.float32)

    valid = inside.copy()
    for band_name in sat.REQUIRED_BANDS:
        valid &= np.isfinite(composite[band_name])
    clear_pct = float(valid.sum() / max(1, int(inside.sum())) * 100.0)
    if abs(clear_pct - float(clean["coverage_pct"])) > 0.25:
        raise RuntimeError(
            f"{plot['code']} {mk(year, month)} coverage mismatch: "
            f"rebuilt={clear_pct:.2f}% cleaned={clean['coverage_pct']}%"
        )

    b02 = composite["B02"]
    b03 = composite["B03"]
    b04 = composite["B04"]
    b08 = composite["B08"]
    b11 = composite["B11"]
    ndvi = fcdsrc.base.safe_normalized_difference(b08, b04)
    mndwi = fcdsrc.base.safe_normalized_difference(b03, b11)
    avi, bsi, csi = fcdsrc.pdd_indices(b02, b03, b04, b08)
    for arr in (ndvi, mndwi, avi, bsi, csi):
        arr[~valid] = np.nan

    return {
        "status": "observed" if valid.any() else "no_data",
        "grid": grid,
        "inside": inside,
        "valid": valid,
        "b02": b02,
        "b03": b03,
        "b04": b04,
        "b08": b08,
        "b11": b11,
        "ndvi": ndvi,
        "mndwi": mndwi,
        "avi": avi,
        "bsi": bsi,
        "csi": csi,
        "scene_metadata": clean.get("selected_scenes", []),
        "scenes_used": len(scene_ids),
        "clear_pixel_pct": round(clear_pct, 2),
        "qa": clean["qa"],
        "analysis_mode": clean["analysis_mode"],
    }


def build_target_batch(catalog, plots, year: int, month: int):
    output = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(build_from_clean_selection, catalog, plot, year, month): plot
            for plot in plots
        }
        for future in as_completed(futures):
            plot = futures[future]
            output[plot["code"]] = future.result()
            d = output[plot["code"]]
            print(plot["code"], mk(year, month), d["analysis_mode"], d["qa"], d["clear_pixel_pct"], flush=True)
    return output


def classify_v3(plot, data, calibration, province_anchors):
    anchor = province_anchors[plot["province"]]
    area = float(plot["area_rai"])
    inside = data["inside"]
    inside_count = max(1, int(inside.sum()))
    class_code = np.zeros(inside.shape, dtype=np.uint8)

    if data.get("status") == "no_data" or "avi" not in data:
        return {
            "month": None,
            "qa": data.get("qa", "NO_DATA"),
            "analysis_mode": data.get("analysis_mode", "no_data"),
            "coverage_pct": float(data.get("clear_pixel_pct", 0.0)),
            "scenes_used": 0,
            "scene_ids": [],
            "green_observed_rai": 0.0,
            "yellow_observed_rai": 0.0,
            "red_observed_rai": 0.0,
            "water_observed_rai": 0.0,
            "unknown_observed_rai": area,
            "green_rai": None,
            "yellow_rai": None,
            "red_rai": None,
            "mean_fcd_score": None,
        }, class_code

    fcd, water_mask, land = v2.score(data, calibration)
    low = land & (fcd < anchor["low_cut"])
    medium = land & (fcd >= anchor["low_cut"]) & (fcd < anchor["high_cut"])
    high = land & (fcd >= anchor["high_cut"])
    class_code[low] = 1
    class_code[medium] = 2
    class_code[high] = 3
    class_code[water_mask] = 4
    unknown = inside & (class_code == 0)

    def rai(mask):
        return float(mask.sum()) / inside_count * area

    classified_count = int(low.sum() + medium.sum() + high.sum())
    equivalent = {"green": None, "yellow": None, "red": None}
    if data.get("qa") == "GOOD" and classified_count > 0:
        target_classified_area = area * anchor["class_frac"]
        equivalent = {
            "green": target_classified_area * int(high.sum()) / classified_count,
            "yellow": target_classified_area * int(medium.sum()) / classified_count,
            "red": target_classified_area * int(low.sum()) / classified_count,
        }

    scene_ids = [item.get("id") for item in data.get("scene_metadata", [])]
    return {
        "month": None,
        "qa": data.get("qa"),
        "analysis_mode": data.get("analysis_mode"),
        "coverage_pct": float(data.get("clear_pixel_pct", 0.0)),
        "scenes_used": int(data.get("scenes_used", 0)),
        "scene_ids": scene_ids,
        "green_observed_rai": round(rai(high), 4),
        "yellow_observed_rai": round(rai(medium), 4),
        "red_observed_rai": round(rai(low), 4),
        "water_observed_rai": round(rai(water_mask), 4),
        "unknown_observed_rai": round(rai(unknown), 4),
        "green_rai": None if equivalent["green"] is None else round(equivalent["green"], 4),
        "yellow_rai": None if equivalent["yellow"] is None else round(equivalent["yellow"], 4),
        "red_rai": None if equivalent["red"] is None else round(equivalent["red"], 4),
        "mean_fcd_score": round(float(np.nanmean(fcd[land])), 4) if land.any() else None,
    }, class_code


def save_map(path: Path, class_code, inside):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((*class_code.shape, 4), dtype=np.uint8)
    for code, color in COLORS.items():
        image[class_code == code, :3] = color
        image[class_code == code, 3] = 255
    unknown = inside & (class_code == 0)
    image[unknown, :3] = (140, 140, 140)
    image[unknown, 3] = 150
    Image.fromarray(image, "RGBA").save(path, optimize=True)


def write_csv(path: Path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    plots = load_plots()
    catalog = sat.pystac_client.Client.open(sat.STAC_URL, modifier=sat.pc.sign_inplace)

    print("Building March-2023 PDD anchor reference", flush=True)
    reference = v2.build_batch(plots, *REFERENCE)
    calibration = v2.fit(reference, mk(*REFERENCE))
    province_anchors = v2.anchors(plots, reference, calibration)

    batches = {}
    for year, month in TARGET_MONTHS:
        batches[(year, month)] = build_target_batch(catalog, plots, year, month)

    plot_results = []
    flat_rows = []
    for plot in plots:
        observations = []
        for year, month in TARGET_MONTHS:
            key = mk(year, month)
            data = batches[(year, month)][plot["code"]]
            result, class_code = classify_v3(plot, data, calibration, province_anchors)
            result["month"] = key
            observations.append(result)
            save_map(MAPS / plot["code"] / f"fcd_{key}.png", class_code, data["inside"])
            flat_rows.append({
                "plot_code": plot["code"],
                "province": plot["province"],
                "area_rai": plot["area_rai"],
                **result,
            })
        plot_results.append({
            "code": plot["code"],
            "province": plot["province"],
            "area_rai": plot["area_rai"],
            "geometry": plot["geometry"],
            "bounds": plot["bounds"],
            "centroid": plot["centroid"],
            "observations": observations,
        })

    portfolio = []
    for year, month in TARGET_MONTHS:
        key = mk(year, month)
        rows = [r for r in flat_rows if r["month"] == key and r["qa"] == "GOOD" and r["green_rai"] is not None]
        matched_area = sum(float(r["area_rai"]) for r in rows)
        portfolio.append({
            "month": key,
            "good_plot_count": len(rows),
            "matched_good_area_rai": round(matched_area, 2),
            "matched_good_area_pct": round(matched_area / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2),
            "green_rai": round(sum(float(r["green_rai"]) for r in rows), 2),
            "yellow_rai": round(sum(float(r["yellow_rai"]) for r in rows), 2),
            "red_rai": round(sum(float(r["red_rai"]) for r in rows), 2),
        })

    ranking = []
    for item in plot_results:
        by_month = {o["month"]: o for o in item["observations"]}
        start = by_month["2024-03"]
        end = by_month["2026-03"]
        comparable = start["qa"] == "GOOD" and end["qa"] == "GOOD"
        dg = None if not comparable else round(float(end["green_rai"]) - float(start["green_rai"]), 2)
        dr = None if not comparable else round(float(end["red_rai"]) - float(start["red_rai"]), 2)
        ranking.append({
            "plot_code": item["code"],
            "province": item["province"],
            "area_rai": item["area_rai"],
            "march_2024_2026_comparable": comparable,
            "delta_green_rai": dg,
            "delta_red_rai": dr,
            "current_2026_08_qa": by_month["2026-08"]["qa"],
            "current_2026_08_green_rai": by_month["2026-08"]["green_rai"],
            "current_2026_08_yellow_rai": by_month["2026-08"]["yellow_rai"],
            "current_2026_08_red_rai": by_month["2026-08"]["red_rai"],
        })
    ranking.sort(key=lambda r: (r["delta_green_rai"] is not None, -(r["delta_green_rai"] or 0), r["delta_red_rai"] or 0), reverse=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "plots_result.json").write_text(json.dumps(plot_results, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "calibration.json").write_text(json.dumps({"calibration": calibration, "province_anchors": province_anchors}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps({
        "model_version": "pdd22_v3_cleaned_scene_fcd",
        "plot_count": 22,
        "project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
        "reference_month": "2023-03",
        "target_months": [mk(*x) for x in TARGET_MONTHS],
        "scene_source": "data/pdd22_satellite selected_scene_ids",
        "pdd_fcd_classes": {"green": ">65 equivalent", "yellow": "30-65 equivalent", "red": "<30 equivalent"},
        "good_only_equivalent_area": True,
        "warning": "PDD-equivalent Sentinel-2 screening only; not exact Landsat PDD reproduction and not verified carbon accounting.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(OUT / "plot_month_results.csv", flat_rows)
    write_csv(OUT / "portfolio_summary.csv", portfolio)
    write_csv(OUT / "plot_change_ranking.csv", ranking)

    lines = [
        "# PDD22 FCD V3 — cleaned Sentinel-2 scene screening",
        "",
        "Uses the exact selected scenes from `data/pdd22_satellite` on the 22 PDD participating polygons.",
        "Equivalent Green/Yellow/Red rai are emitted only when plot-month QA is GOOD (>=95% valid coverage).",
        "",
        "## Portfolio good-coverage summary",
        "",
        "| Month | GOOD plots | Matched area (rai) | Matched area % | Green | Yellow | Red |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in portfolio:
        lines.append(f"| {r['month']} | {r['good_plot_count']} | {r['matched_good_area_rai']:.2f} | {r['matched_good_area_pct']:.2f}% | {r['green_rai']:.2f} | {r['yellow_rai']:.2f} | {r['red_rai']:.2f} |")
    lines += ["", "## Guardrail", "", "Do not convert these class areas directly into tCO2e. Field verification remains required for suspected decline hotspots."]
    (OUT / "EXECUTIVE_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")

    print((OUT / "EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8"), flush=True)


if __name__ == "__main__":
    main()
