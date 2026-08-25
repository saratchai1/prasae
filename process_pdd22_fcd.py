#!/usr/bin/env python3
"""PDD-style FCD screening for the 22 Group-2 mangrove plots.

This is a screening adaptation of the PDD's Landsat-8 Forest Canopy Density
workflow to Sentinel-2 L2A reflectance. It preserves the PDD index structure:
AVI + BSI -> PCA -> Vegetation Density (VD), CSI -> Scaled Shadow Index (SSI),
then FCD = sqrt(VD * SSI + 1) - 1, with PDD classes >65 / 30-65 / <30.

The PCA basis and linear scaling anchors are fitted once from the March-2023
reference across all 22 PDD plots, then held fixed for March-2024/2025/2026.
This script does NOT convert FCD directly into verified T-VER carbon credit.
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from rasterio.warp import Resampling
from shapely.geometry import shape

import process_verified_12_dates as base
from pdd22_config import (
    FCD_HIGH_MIN,
    FCD_LOW_MAX,
    OBSERVATION_MONTHS,
    PDD22_PLOTS,
    PDD_BASELINE_FCD_BY_PROVINCE,
    PDD_BASELINE_TREE_CARBON_TCO2E,
    PDD_INCREMENT_TCO2E_PER_RAI_YEAR,
    PDD_TOTAL_PROJECT_AREA_RAI,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "pdd22"
CATALOG_PATH = DATA_DIR / "plots_catalog.json"
MAP_DIR = DATA_DIR / "maps"
METRICS_PATH = DATA_DIR / "fcd_metrics.json"
METRICS_CSV_PATH = DATA_DIR / "fcd_metrics.csv"
SUMMARY_CSV_PATH = DATA_DIR / "portfolio_summary.csv"
TRANSITIONS_PATH = DATA_DIR / "transitions.json"
CALIBRATION_PATH = DATA_DIR / "fcd_calibration.json"
PDD_COMPARE_CSV_PATH = DATA_DIR / "reference_vs_pdd_fcd.csv"
CARBON_PATH = DATA_DIR / "carbon_screening.json"

MAX_SAMPLE_PER_PLOT = int(os.environ.get("PDD22_REFERENCE_SAMPLE", "6000"))
MIN_OBSERVED_RATIO = float(os.environ.get("PDD22_MIN_OBSERVED_RATIO", "0.05"))
WATER_MNDWI_THRESHOLD = float(os.environ.get("PDD22_WATER_MNDWI", "0.0"))
WATER_NDVI_CEILING = float(os.environ.get("PDD22_WATER_NDVI_CEILING", "0.25"))
SCALE_LOWER_PERCENTILE = float(os.environ.get("PDD22_SCALE_LOW_PCT", "2"))
SCALE_UPPER_PERCENTILE = float(os.environ.get("PDD22_SCALE_HIGH_PCT", "98"))

CLASS_LABELS = {0: "unknown", 1: "low_red", 2: "medium_yellow", 3: "high_green", 4: "water"}
CLASS_RGB = {1: (220, 53, 69), 2: (255, 193, 7), 3: (40, 167, 69), 4: (23, 162, 184)}


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def load_catalog():
    if not CATALOG_PATH.exists():
        raise FileNotFoundError(f"Missing {CATALOG_PATH}; run extract_pdd22_plots.py first")
    plots = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if len(plots) != 22:
        raise RuntimeError(f"Expected 22 PDD plots, found {len(plots)}")
    if round(sum(float(p["area_rai"]) for p in plots), 2) != PDD_TOTAL_PROJECT_AREA_RAI:
        raise RuntimeError("PDD22 catalog area total does not equal 6,775.53 rai")
    return plots


def pdd_indices(b02, b03, b04, b08):
    """AVI, BSI and CSI using the PDD equations on Sentinel-2 0-1 reflectance."""
    dnmax = 1.0
    with np.errstate(all="ignore"):
        avi = np.cbrt((b08 + 1.0) * (dnmax - b04) * (b08 - b04)).astype(np.float32)
        bsi_den = b08 + b03 + b04
        bsi = np.divide(
            (b08 - b03) - b04,
            bsi_den,
            out=np.full_like(b08, np.nan, dtype=np.float32),
            where=np.isfinite(bsi_den) & (np.abs(bsi_den) > 1e-6),
        )
        csi = np.cbrt((dnmax - b03) * (dnmax - b02) * (dnmax - b04)).astype(np.float32)
    return avi, bsi, csi


def build_composite(catalog, plot: dict[str, Any], year: int, month: int):
    geom = shape(plot["geometry"])
    grid = base.compute_grid(geom)
    inside = base.plot_mask(geom, grid)
    if not inside.any():
        raise ValueError(f"{plot['code']}: plot covers zero target pixels")

    items = base.search_month(catalog, grid, year, month)
    scenes = []
    scene_meta = []
    for item in items:
        try:
            scl = base.read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            b02 = base.read_asset_to_grid(item, "B02", grid, Resampling.bilinear)
            b03 = base.read_asset_to_grid(item, "B03", grid, Resampling.bilinear)
            b04 = base.read_asset_to_grid(item, "B04", grid, Resampling.bilinear)
            b08 = base.read_asset_to_grid(item, "B08", grid, Resampling.bilinear)
            b11 = base.read_asset_to_grid(item, "B11", grid, Resampling.bilinear)
            clear = base.cloud_clear_mask(scl, b02, b03, b04, b08, b11)
            clear_inside = clear & inside
            ratio = float(clear_inside.sum() / max(1, int(inside.sum())))
            if ratio < 0.01:
                continue
            arrays = [b02, b03, b04, b08, b11]
            for arr in arrays:
                arr[~clear] = np.nan
            scenes.append(arrays)
            scene_meta.append({
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "catalog_cloud_cover_pct": item.properties.get("eo:cloud_cover"),
                "clear_inside_pct": round(ratio * 100.0, 2),
                "processing_baseline": item.properties.get("s2:processing_baseline"),
            })
        except Exception as exc:
            print(f"  {plot['code']} {month_key(year, month)} scene {item.id}: {exc}")

    if not scenes:
        return {
            "status": "no_data", "grid": grid, "inside": inside,
            "valid": np.zeros_like(inside, dtype=bool), "scene_metadata": [],
            "scenes_used": 0, "clear_pixel_pct": 0.0,
        }

    stack = np.asarray(scenes, dtype=np.float32)
    with np.errstate(all="ignore"):
        composite = np.nanmedian(stack, axis=0)
    b02, b03, b04, b08, b11 = composite
    valid = inside.copy()
    for arr in (b02, b03, b04, b08, b11):
        valid &= np.isfinite(arr)
    clear_ratio = float(valid.sum() / max(1, int(inside.sum())))
    status = "observed" if clear_ratio >= MIN_OBSERVED_RATIO else "insufficient_clear_pixels"
    ndvi = base.safe_normalized_difference(b08, b04)
    mndwi = base.safe_normalized_difference(b03, b11)
    avi, bsi, csi = pdd_indices(b02, b03, b04, b08)
    for arr in (ndvi, mndwi, avi, bsi, csi):
        arr[~valid] = np.nan
    return {
        "status": status, "grid": grid, "inside": inside, "valid": valid,
        "b02": b02, "b03": b03, "b04": b04, "b08": b08, "b11": b11,
        "ndvi": ndvi, "mndwi": mndwi, "avi": avi, "bsi": bsi, "csi": csi,
        "scene_metadata": scene_meta, "scenes_used": len(scenes),
        "clear_pixel_pct": round(clear_ratio * 100.0, 2),
    }


def deterministic_sample(arrays, mask, limit):
    indices = np.flatnonzero(mask.ravel())
    if indices.size == 0:
        return np.empty((0, len(arrays)), dtype=np.float32)
    if indices.size > limit:
        positions = np.linspace(0, indices.size - 1, num=limit, dtype=np.int64)
        indices = indices[positions]
    cols = [arr.ravel()[indices] for arr in arrays]
    matrix = np.column_stack(cols).astype(np.float32)
    return matrix[np.isfinite(matrix).all(axis=1)]


def fit_reference_calibration(reference_composites):
    pca_samples = []
    csi_samples = []
    for data in reference_composites.values():
        if data["status"] == "no_data":
            continue
        valid = data["valid"]
        water = valid & (data["mndwi"] > WATER_MNDWI_THRESHOLD) & (data["ndvi"] <= WATER_NDVI_CEILING)
        land = valid & ~water
        if int(land.sum()) < 100:
            land = valid
        pca_sample = deterministic_sample([data["avi"], data["bsi"]], land, MAX_SAMPLE_PER_PLOT)
        shadow_sample = deterministic_sample([data["csi"]], land, MAX_SAMPLE_PER_PLOT)
        if pca_sample.size:
            pca_samples.append(pca_sample)
        if shadow_sample.size:
            csi_samples.append(shadow_sample[:, 0])

    if not pca_samples or not csi_samples:
        raise RuntimeError("Reference calibration has no usable pixels")
    x = np.vstack(pca_samples).astype(np.float64)
    csi_all = np.concatenate(csi_samples).astype(np.float64)
    mean = np.mean(x, axis=0)
    centered = x - mean
    covariance = np.cov(centered, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(covariance)
    order = np.argsort(eigvals)[::-1]
    vector = eigvecs[:, order[0]].astype(np.float64)
    if (vector[0] - vector[1]) < 0:
        vector *= -1.0
    pc1 = centered @ vector
    vd_low, vd_high = np.percentile(pc1, [SCALE_LOWER_PERCENTILE, SCALE_UPPER_PERCENTILE])
    csi_low, csi_high = np.percentile(csi_all, [SCALE_LOWER_PERCENTILE, SCALE_UPPER_PERCENTILE])
    if not vd_high > vd_low or not csi_high > csi_low:
        raise RuntimeError("Reference scaling anchors collapsed")
    return {
        "reference_month": month_key(*OBSERVATION_MONTHS[0]),
        "sensor": "Sentinel-2 L2A",
        "pdd_adaptation": "AVI + BSI -> PCA -> fixed VD; CSI -> fixed SSI; FCD=sqrt(VD*SSI+1)-1",
        "reflectance_dnmax": 1.0,
        "pca_mean": [float(v) for v in mean],
        "pca_pc1_vector": [float(v) for v in vector],
        "pca_eigenvalues": [float(eigvals[i]) for i in order],
        "vd_scale_percentiles": [SCALE_LOWER_PERCENTILE, SCALE_UPPER_PERCENTILE],
        "vd_raw_low": float(vd_low), "vd_raw_high": float(vd_high),
        "ssi_scale_percentiles": [SCALE_LOWER_PERCENTILE, SCALE_UPPER_PERCENTILE],
        "csi_raw_low": float(csi_low), "csi_raw_high": float(csi_high),
        "reference_pca_sample_count": int(x.shape[0]),
        "reference_csi_sample_count": int(csi_all.size),
        "fcd_classes": {
            "high_green": f"> {FCD_HIGH_MIN}%",
            "medium_yellow": f"{FCD_LOW_MAX}-{FCD_HIGH_MIN}%",
            "low_red": f"< {FCD_LOW_MAX}%",
        },
        "water_rule": f"MNDWI > {WATER_MNDWI_THRESHOLD} AND NDVI <= {WATER_NDVI_CEILING}",
        "temporal_rule": "PCA/scaling fitted once on March-2023 and frozen for later March observations",
        "warning": "Screening adaptation; not a verified remote-sensing carbon model and not identical to the PDD Landsat-8 implementation.",
    }


def linear_scale(values, low, high):
    scaled = (values - low) / (high - low) * 100.0
    return np.clip(scaled, 0.0, 100.0).astype(np.float32)


def classify(plot, data, calibration):
    inside = data["inside"]
    inside_count = max(1, int(inside.sum()))
    class_code = np.zeros_like(inside, dtype=np.uint8)
    if data["status"] == "no_data":
        metrics = {
            "status": "no_data", "scenes_used": 0, "scene_ids": [], "scene_metadata": [],
            "clear_pixel_pct": 0.0, "qa_label": "LOW_QA",
            "high_green_pct": 0.0, "medium_yellow_pct": 0.0, "low_red_pct": 0.0,
            "water_pct": 0.0, "unknown_pct": 100.0,
            "high_green_rai": 0.0, "medium_yellow_rai": 0.0, "low_red_rai": 0.0,
            "water_rai": 0.0, "unknown_rai": float(plot["area_rai"]),
            "mean_fcd_valid_land": None, "median_fcd_valid_land": None,
            "mean_ndvi_valid": None, "median_mndwi_valid": None,
        }
        return metrics, class_code

    mean = np.asarray(calibration["pca_mean"], dtype=np.float32)
    vector = np.asarray(calibration["pca_pc1_vector"], dtype=np.float32)
    valid = data["valid"] & np.isfinite(data["avi"]) & np.isfinite(data["bsi"]) & np.isfinite(data["csi"])
    pc1 = (data["avi"] - mean[0]) * vector[0] + (data["bsi"] - mean[1]) * vector[1]
    vd = linear_scale(pc1, calibration["vd_raw_low"], calibration["vd_raw_high"])
    ssi = linear_scale(data["csi"], calibration["csi_raw_low"], calibration["csi_raw_high"])
    with np.errstate(all="ignore"):
        fcd = np.sqrt(vd * ssi + 1.0) - 1.0
    fcd[~valid] = np.nan

    water = valid & (data["mndwi"] > WATER_MNDWI_THRESHOLD) & (data["ndvi"] <= WATER_NDVI_CEILING)
    land = valid & ~water
    low = land & (fcd < FCD_LOW_MAX)
    medium = land & (fcd >= FCD_LOW_MAX) & (fcd <= FCD_HIGH_MIN)
    high = land & (fcd > FCD_HIGH_MIN)
    class_code[low] = 1
    class_code[medium] = 2
    class_code[high] = 3
    class_code[water] = 4

    area = float(plot["area_rai"])
    def pct(mask): return float(mask.sum() / inside_count * 100.0)
    def rai(mask): return float(mask.sum() / inside_count * area)

    unknown = inside & (class_code == 0)
    high_pct, medium_pct, low_pct, water_pct, unknown_pct = [pct(m) for m in (high, medium, low, water, unknown)]
    if data["clear_pixel_pct"] < 30.0:
        qa = "LOW_QA"
    elif water_pct > 40.0:
        qa = "TIDE_DOMINATED"
    elif water_pct > 20.0:
        qa = "WATER_INFLUENCED"
    else:
        qa = "COMPARABLE"
    finite_land = fcd[land]
    finite_land = finite_land[np.isfinite(finite_land)]
    metrics = {
        "status": data["status"], "scenes_used": data["scenes_used"],
        "scene_ids": [m["id"] for m in data["scene_metadata"]], "scene_metadata": data["scene_metadata"],
        "clear_pixel_pct": data["clear_pixel_pct"], "qa_label": qa,
        "high_green_pct": round(high_pct, 2), "medium_yellow_pct": round(medium_pct, 2),
        "low_red_pct": round(low_pct, 2), "water_pct": round(water_pct, 2), "unknown_pct": round(unknown_pct, 2),
        "high_green_rai": round(rai(high), 2), "medium_yellow_rai": round(rai(medium), 2),
        "low_red_rai": round(rai(low), 2), "water_rai": round(rai(water), 2), "unknown_rai": round(rai(unknown), 2),
        "mean_fcd_valid_land": round(float(np.mean(finite_land)), 2) if finite_land.size else None,
        "median_fcd_valid_land": round(float(np.median(finite_land)), 2) if finite_land.size else None,
        "mean_ndvi_valid": round(float(np.nanmean(data["ndvi"][valid])), 4) if valid.any() else None,
        "median_mndwi_valid": round(float(np.nanmedian(data["mndwi"][valid])), 4) if valid.any() else None,
    }
    return metrics, class_code


def save_class_map(plot, date_key, class_code, inside):
    out_dir = MAP_DIR / plot["code"]
    out_dir.mkdir(parents=True, exist_ok=True)
    rgba = np.zeros((*class_code.shape, 4), dtype=np.uint8)
    for code, rgb in CLASS_RGB.items():
        mask = class_code == code
        rgba[mask, :3] = rgb
        rgba[mask, 3] = 235
    unknown = inside & (class_code == 0)
    rgba[unknown, :3] = (128, 128, 128)
    rgba[unknown, 3] = 120
    Image.fromarray(rgba, mode="RGBA").save(out_dir / f"fcd_{date_key}.png", optimize=True)


def transition_matrix(plot, from_key, to_key, from_classes, to_classes, inside):
    inside_count = max(1, int(inside.sum()))
    pixel_area = float(plot["area_rai"]) / inside_count
    matrix = {CLASS_LABELS[a]: {CLASS_LABELS[b]: 0.0 for b in CLASS_LABELS} for a in CLASS_LABELS}
    for a in CLASS_LABELS:
        for b in CLASS_LABELS:
            count = int((inside & (from_classes == a) & (to_classes == b)).sum())
            matrix[CLASS_LABELS[a]][CLASS_LABELS[b]] = round(count * pixel_area, 2)
    return {"from": from_key, "to": to_key, "unit": "rai", "matrix": matrix}


def aggregate_portfolio(plot_results):
    by_date = defaultdict(lambda: defaultdict(float))
    qa_counts = defaultdict(lambda: defaultdict(int))
    for plot in plot_results:
        for obs in plot["observations"]:
            key = obs["month"]
            for field in ["high_green_rai", "medium_yellow_rai", "low_red_rai", "water_rai", "unknown_rai"]:
                by_date[key][field] += float(obs[field])
            qa_counts[key][obs["qa_label"]] += 1
    reference_key = month_key(*OBSERVATION_MONTHS[0])
    reference = by_date[reference_key]
    output = []
    for year, month in OBSERVATION_MONTHS:
        key = month_key(year, month)
        row = {"month": key, "year": year, "thai_year": year + 543}
        for field in ["high_green_rai", "medium_yellow_rai", "low_red_rai", "water_rai", "unknown_rai"]:
            row[field] = round(by_date[key][field], 2)
        row["high_green_pct"] = round(row["high_green_rai"] / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2)
        row["medium_yellow_pct"] = round(row["medium_yellow_rai"] / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2)
        row["low_red_pct"] = round(row["low_red_rai"] / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2)
        row["water_pct"] = round(row["water_rai"] / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2)
        row["unknown_pct"] = round(row["unknown_rai"] / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2)
        row["delta_high_vs_2023_rai"] = round(row["high_green_rai"] - reference["high_green_rai"], 2)
        row["delta_low_vs_2023_rai"] = round(row["low_red_rai"] - reference["low_red_rai"], 2)
        row["qa_counts"] = dict(qa_counts[key])
        output.append(row)
    return output


def compare_reference_to_pdd(plot_results):
    reference_key = month_key(*OBSERVATION_MONTHS[0])
    sentinel = defaultdict(lambda: defaultdict(float))
    for plot in plot_results:
        obs = next(item for item in plot["observations"] if item["month"] == reference_key)
        province = plot["province"]
        sentinel[province]["high"] += obs["high_green_rai"]
        sentinel[province]["medium"] += obs["medium_yellow_rai"]
        sentinel[province]["low"] += obs["low_red_rai"]
        sentinel[province]["water_unknown"] += obs["water_rai"] + obs["unknown_rai"]
    rows = []
    for province, pdd in PDD_BASELINE_FCD_BY_PROVINCE.items():
        s = sentinel[province]
        rows.append({
            "province": province, "pdd_total_rai": pdd["total"],
            "pdd_high_rai": pdd["high"], "sentinel_2023_high_rai": round(s["high"], 2),
            "delta_high_rai": round(s["high"] - pdd["high"], 2),
            "pdd_medium_rai": pdd["medium"], "sentinel_2023_medium_rai": round(s["medium"], 2),
            "delta_medium_rai": round(s["medium"] - pdd["medium"], 2),
            "pdd_low_rai": pdd["low"], "sentinel_2023_low_rai": round(s["low"], 2),
            "delta_low_rai": round(s["low"] - pdd["low"], 2),
            "pdd_bare_error_rai": pdd["bare_error"],
            "sentinel_2023_water_unknown_rai": round(s["water_unknown"], 2),
        })
    return rows


def write_csvs(plot_results, portfolio, pdd_compare):
    fields = [
        "order", "code", "province", "coast", "area_rai", "month", "year", "thai_year",
        "status", "qa_label", "scenes_used", "clear_pixel_pct", "high_green_rai", "medium_yellow_rai",
        "low_red_rai", "water_rai", "unknown_rai", "high_green_pct", "medium_yellow_pct", "low_red_pct",
        "water_pct", "unknown_pct", "mean_fcd_valid_land", "median_fcd_valid_land", "mean_ndvi_valid", "median_mndwi_valid",
    ]
    with METRICS_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for plot in plot_results:
            for obs in plot["observations"]:
                row = {k: plot[k] for k in ["order", "code", "province", "coast", "area_rai"]}
                row.update({k: obs.get(k) for k in fields if k not in row})
                writer.writerow(row)

    portfolio_fields = [
        "month", "year", "thai_year", "high_green_rai", "medium_yellow_rai", "low_red_rai", "water_rai", "unknown_rai",
        "high_green_pct", "medium_yellow_pct", "low_red_pct", "water_pct", "unknown_pct",
        "delta_high_vs_2023_rai", "delta_low_vs_2023_rai",
    ]
    with SUMMARY_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=portfolio_fields)
        writer.writeheader()
        for row in portfolio:
            writer.writerow({key: row.get(key) for key in portfolio_fields})

    with PDD_COMPARE_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pdd_compare[0].keys()))
        writer.writeheader()
        writer.writerows(pdd_compare)


def carbon_screening_payload(portfolio):
    nominal_annual = PDD_TOTAL_PROJECT_AREA_RAI * PDD_INCREMENT_TCO2E_PER_RAI_YEAR
    nominal_by_year = []
    for year in [2024, 2025, 2026]:
        years_elapsed = max(0, year - 2024)
        nominal_by_year.append({
            "year": year, "thai_year": year + 543, "years_elapsed_from_2567": years_elapsed,
            "nominal_cumulative_increment_tco2e": round(nominal_annual * years_elapsed, 2),
            "nominal_total_tree_carbon_tco2e": round(PDD_BASELINE_TREE_CARBON_TCO2E + nominal_annual * years_elapsed, 2),
        })
    return {
        "purpose": "preliminary screening only",
        "pdd_baseline_tree_carbon_tco2e": PDD_BASELINE_TREE_CARBON_TCO2E,
        "pdd_project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
        "pdd_increment_tco2e_per_rai_year": PDD_INCREMENT_TCO2E_PER_RAI_YEAR,
        "pdd_nominal_annual_increment_tco2e": round(nominal_annual, 2),
        "pdd_nominal_by_year": nominal_by_year,
        "satellite_adjusted_credit_tco2e": None,
        "satellite_adjusted_credit_status": "not calculated: PDD does not provide carbon density by FCD High/Medium/Low stratum; FCD area change is reported separately to avoid inventing a carbon conversion",
        "satellite_portfolio_fcd": portfolio,
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MAP_DIR.mkdir(parents=True, exist_ok=True)
    plots = load_catalog()
    target_config = {item["code"]: item for item in PDD22_PLOTS}

    print("Building March-2023 reference composites for fixed FCD calibration...")
    reference_composites = {}
    reference_catalog = base.stac_client()
    ref_year, ref_month = OBSERVATION_MONTHS[0]
    for index, plot in enumerate(plots, start=1):
        print(f"[{index:02d}/22] {plot['code']} {plot['province']} reference")
        reference_composites[plot["code"]] = build_composite(reference_catalog, plot, ref_year, ref_month)
    calibration = fit_reference_calibration(reference_composites)
    CALIBRATION_PATH.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")

    plot_results = []
    transition_results = []
    runtime_catalog = base.stac_client()
    for index, plot in enumerate(plots, start=1):
        print(f"\n[{index:02d}/22] Processing {plot['code']} {plot['province']} area={plot['area_rai']} rai")
        observations = []
        class_by_date = {}
        inside_ref = None
        for year, month in OBSERVATION_MONTHS:
            key = month_key(year, month)
            if (year, month) == (ref_year, ref_month):
                data = reference_composites[plot["code"]]
            else:
                data = build_composite(runtime_catalog, plot, year, month)
            metrics, class_code = classify(plot, data, calibration)
            obs = {"month": key, "year": year, "thai_year": year + 543, **metrics}
            observations.append(obs)
            class_by_date[key] = class_code
            if inside_ref is None:
                inside_ref = data["inside"]
            save_class_map(plot, key, class_code, data["inside"])
            print(f"  {key} {metrics['qa_label']} clear={metrics['clear_pixel_pct']}% green={metrics['high_green_rai']:.2f} yellow={metrics['medium_yellow_rai']:.2f} red={metrics['low_red_rai']:.2f} water={metrics['water_rai']:.2f} unknown={metrics['unknown_rai']:.2f}")

        transitions = []
        date_keys = [month_key(y, m) for y, m in OBSERVATION_MONTHS]
        for from_key, to_key in zip(date_keys[:-1], date_keys[1:]):
            transitions.append(transition_matrix(plot, from_key, to_key, class_by_date[from_key], class_by_date[to_key], inside_ref))
        cfg = target_config[plot["code"]]
        plot_results.append({
            "order": cfg["order"], "code": plot["code"], "province": plot["province"], "coast": plot["coast"],
            "area_rai": plot["area_rai"], "geometry_area_rai": plot.get("geometry_area_rai"), "observations": observations,
        })
        transition_results.append({"code": plot["code"], "province": plot["province"], "transitions": transitions})

    portfolio = aggregate_portfolio(plot_results)
    pdd_compare = compare_reference_to_pdd(plot_results)
    payload = {
        "schema_version": "1.0", "method": "PDD-style FCD proxy adapted to Sentinel-2 L2A", "screening_only": True,
        "project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
        "reference_year_assumption": "2566/2023 is a satellite reference requested by the user; it is not the PDD's official T-VER baseline survey date",
        "observation_months": [month_key(y, m) for y, m in OBSERVATION_MONTHS],
        "calibration": calibration, "portfolio": portfolio, "plots": plot_results,
    }
    METRICS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    TRANSITIONS_PATH.write_text(json.dumps({"unit": "rai", "class_labels": CLASS_LABELS, "plots": transition_results}, ensure_ascii=False, indent=2), encoding="utf-8")
    CARBON_PATH.write_text(json.dumps(carbon_screening_payload(portfolio), ensure_ascii=False, indent=2), encoding="utf-8")
    write_csvs(plot_results, portfolio, pdd_compare)

    print("\nPortfolio summary")
    for row in portfolio:
        print(f"{row['thai_year']} ({row['month']}): green={row['high_green_rai']:,.2f} rai yellow={row['medium_yellow_rai']:,.2f} red={row['low_red_rai']:,.2f} water={row['water_rai']:,.2f} unknown={row['unknown_rai']:,.2f} Δgreen={row['delta_high_vs_2023_rai']:+,.2f} Δred={row['delta_low_vs_2023_rai']:+,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
