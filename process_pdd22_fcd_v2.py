#!/usr/bin/env python3
"""PDD22 FCD screening v2: corrected VD direction + PDD-anchored March/August trends.

Screening only. Sentinel-2 is harmonized to the PDD Table 3-1 provincial FCD
shares in each 2023 same-month reference; those thresholds are then frozen
through 2026. This is not a verified T-VER carbon calculation.
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image

import process_pdd22_fcd as src
from pdd22_config import (
    PDD22_PLOTS,
    PDD_BASELINE_FCD_BY_PROVINCE,
    PDD_BASELINE_TREE_CARBON_TCO2E,
    PDD_INCREMENT_TCO2E_PER_RAI_YEAR,
    PDD_TOTAL_PROJECT_AREA_RAI,
)

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "data/pdd22/plots_catalog.json"
OUT = ROOT / "data/pdd22_v2"
SERIES = {
    "march": [(2023, 3), (2024, 3), (2025, 3), (2026, 3)],
    "august": [(2023, 8), (2024, 8), (2025, 8), (2026, 8)],
}
WORKERS = int(os.getenv("PDD22_V2_WORKERS", "6"))
SAMPLE = int(os.getenv("PDD22_REFERENCE_SAMPLE", "6000"))
PLOW, PHIGH = 2.0, 98.0
WATER_MNDWI, WATER_NDVI = 0.0, 0.25
MIN_PORTFOLIO_COVERAGE_FOR_DELTA = 0.95
COLORS = {1: (220, 53, 69), 2: (255, 193, 7), 3: (40, 167, 69), 4: (23, 162, 184)}


def mk(year, month):
    return f"{year:04d}-{month:02d}"


def ty(year):
    return year + 543


def load_plots():
    plots = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert len(plots) == 22
    assert round(sum(float(x["area_rai"]) for x in plots), 2) == PDD_TOTAL_PROJECT_AREA_RAI
    return plots


def build_one(plot, year, month):
    return src.build_composite(src.base.stac_client(), plot, year, month)


def build_batch(plots, year, month):
    out = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(build_one, plot, year, month): plot for plot in plots}
        for future in as_completed(futures):
            plot = futures[future]
            out[plot["code"]] = future.result()
            data = out[plot["code"]]
            print(
                plot["code"], mk(year, month), data["status"],
                "clear", data.get("clear_pixel_pct"), flush=True,
            )
    return out


def water(data):
    if "mndwi" not in data or "ndvi" not in data:
        return np.zeros_like(data["inside"], dtype=bool)
    return data["valid"] & (data["mndwi"] > WATER_MNDWI) & (data["ndvi"] <= WATER_NDVI)


def sample_cols(arrays, mask, n=SAMPLE):
    indices = np.flatnonzero(mask.ravel())
    if not indices.size:
        return np.empty((0, len(arrays)))
    if indices.size > n:
        indices = indices[np.linspace(0, indices.size - 1, n, dtype=np.int64)]
    matrix = np.column_stack([array.ravel()[indices] for array in arrays]).astype(float)
    return matrix[np.isfinite(matrix).all(axis=1)]


def fit(reference, reference_key):
    pca_samples = []
    csi_samples = []
    for data in reference.values():
        if data.get("status") == "no_data" or "avi" not in data:
            continue
        land = data["valid"] & ~water(data)
        sample = sample_cols([data["avi"], data["bsi"], data["ndvi"]], land)
        csi = sample_cols([data["csi"]], land)
        if len(sample):
            pca_samples.append(sample)
        if len(csi):
            csi_samples.append(csi[:, 0])
    if not pca_samples or not csi_samples:
        raise RuntimeError(f"No usable {reference_key} pixels for PDD22 V2 calibration")

    matrix = np.vstack(pca_samples)
    x = matrix[:, :2]
    ndvi = matrix[:, 2]
    mean = x.mean(axis=0)
    centered = x - mean
    eigenvalues, eigenvectors = np.linalg.eigh(np.cov(centered, rowvar=False))
    vector = eigenvectors[:, np.argmax(eigenvalues)].astype(float)
    pc1 = centered @ vector
    correlation = float(np.corrcoef(pc1, ndvi)[0, 1])

    # PDD page 109 states maximum PCA -> VD 0%, minimum PCA -> VD 100%.
    # Orient PC1 so vegetation-rich (higher NDVI) tends toward the low PCA end.
    if np.isfinite(correlation) and correlation > 0:
        vector *= -1
        pc1 *= -1
        correlation *= -1

    raw_low, raw_high = np.percentile(pc1, [PLOW, PHIGH])
    csi_low, csi_high = np.percentile(np.concatenate(csi_samples), [PLOW, PHIGH])
    if not raw_high > raw_low or not csi_high > csi_low:
        raise RuntimeError("PDD22 V2 reference scaling anchors collapsed")

    return {
        "reference": reference_key,
        "mean": mean.tolist(),
        "pc1": vector.tolist(),
        "pc1_ndvi_corr": correlation,
        "vd_raw_low": float(raw_low),
        "vd_raw_high": float(raw_high),
        "csi_low": float(csi_low),
        "csi_high": float(csi_high),
        "vd_rule": "PDD p.109: maximum PCA -> VD 0%; minimum PCA -> VD 100%",
        "scaling_percentiles": [PLOW, PHIGH],
    }


def score(data, calibration):
    if data.get("status") == "no_data" or "avi" not in data:
        shape = data["inside"].shape
        return (
            np.full(shape, np.nan, dtype=np.float32),
            np.zeros(shape, dtype=bool),
            np.zeros(shape, dtype=bool),
        )
    mean = np.array(calibration["mean"])
    vector = np.array(calibration["pc1"])
    valid = data["valid"]
    pc1 = (data["avi"] - mean[0]) * vector[0] + (data["bsi"] - mean[1]) * vector[1]
    vd = np.clip(
        (calibration["vd_raw_high"] - pc1)
        / (calibration["vd_raw_high"] - calibration["vd_raw_low"])
        * 100.0,
        0,
        100,
    )
    ssi = np.clip(
        (data["csi"] - calibration["csi_low"])
        / (calibration["csi_high"] - calibration["csi_low"])
        * 100.0,
        0,
        100,
    )
    fcd = np.sqrt(vd * ssi + 1.0) - 1.0
    fcd[~valid] = np.nan
    water_mask = water(data)
    return fcd, water_mask, valid & ~water_mask


def weighted_quantile(values, weights, quantile):
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights)
    if not len(cumulative) or cumulative[-1] <= 0:
        raise RuntimeError("Weighted quantile has zero total weight")
    index = np.searchsorted(cumulative, quantile * cumulative[-1], side="left")
    return float(values[min(index, len(values) - 1)])


def anchors(plots, reference, calibration):
    values_by_province = defaultdict(list)
    weights_by_province = defaultdict(list)
    by_code = {plot["code"]: plot for plot in plots}

    for code, data in reference.items():
        if data.get("status") == "no_data" or "avi" not in data:
            continue
        fcd, _, land = score(data, calibration)
        values = fcd[land]
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        plot = by_code[code]
        pixel_weight = float(plot["area_rai"]) / max(1, int(data["inside"].sum()))
        values_by_province[plot["province"]].append(values)
        weights_by_province[plot["province"]].append(np.full(len(values), pixel_weight))

    all_value_parts = [np.concatenate(parts) for parts in values_by_province.values() if parts]
    all_weight_parts = [np.concatenate(parts) for parts in weights_by_province.values() if parts]
    if not all_value_parts:
        raise RuntimeError("No 2023 FCD values available for provincial anchoring")
    global_values = np.concatenate(all_value_parts)
    global_weights = np.concatenate(all_weight_parts)

    output = {}
    for province, target in PDD_BASELINE_FCD_BY_PROVINCE.items():
        local = bool(values_by_province.get(province))
        values = np.concatenate(values_by_province[province]) if local else global_values
        weights = np.concatenate(weights_by_province[province]) if local else global_weights
        classified_target = target["high"] + target["medium"] + target["low"]
        q_low = target["low"] / classified_target
        q_high = (target["low"] + target["medium"]) / classified_target
        output[province] = {
            "low_cut": weighted_quantile(values, weights, q_low),
            "high_cut": weighted_quantile(values, weights, q_high),
            "class_frac": classified_target / target["total"],
            "scope": "province_2023" if local else "global_2023_fallback",
            "pdd": {
                "high": target["high"],
                "medium": target["medium"],
                "low": target["low"],
                "bare_error": target["bare_error"],
            },
        }
    return output


def qa_label(clear_pct, water_pct):
    if clear_pct < 30:
        return "LOW_QA"
    if water_pct > 40:
        return "TIDE_DOMINATED"
    if water_pct > 20:
        return "WATER_INFLUENCED"
    return "COMPARABLE"


def classify(plot, data, calibration, province_anchors):
    anchor = province_anchors[plot["province"]]
    area = float(plot["area_rai"])
    bare_error = round(area * (1.0 - anchor["class_frac"]), 4)
    inside = data["inside"]

    if data.get("status") == "no_data" or "avi" not in data:
        return {
            "status": data.get("status", "no_data"),
            "qa": "LOW_QA",
            "clear_pct": float(data.get("clear_pixel_pct", 0.0)),
            "scenes": int(data.get("scenes_used", 0)),
            "scene_ids": [item.get("id") for item in data.get("scene_metadata", [])],
            "green_rai": None,
            "yellow_rai": None,
            "red_rai": None,
            "bare_error_alloc_rai": bare_error,
            "water_observed_rai": 0.0,
            "unknown_observed_rai": round(area, 4),
            "mean_fcd_score": None,
        }, np.zeros(inside.shape, dtype=np.uint8)

    fcd, water_mask, land = score(data, calibration)
    low = land & (fcd < anchor["low_cut"])
    medium = land & (fcd >= anchor["low_cut"]) & (fcd < anchor["high_cut"])
    high = land & (fcd >= anchor["high_cut"])

    class_code = np.zeros(inside.shape, dtype=np.uint8)
    class_code[low] = 1
    class_code[medium] = 2
    class_code[high] = 3
    class_code[water_mask] = 4

    inside_count = max(1, int(inside.sum()))
    unknown = inside & (class_code == 0)
    observed_water_rai = float(water_mask.sum()) / inside_count * area
    observed_unknown_rai = float(unknown.sum()) / inside_count * area

    classified_count = int(high.sum() + medium.sum() + low.sum())
    target_classified_area = area * anchor["class_frac"]
    equivalent = {
        key: target_classified_area * int(mask.sum()) / classified_count if classified_count else None
        for key, mask in (("high", high), ("medium", medium), ("low", low))
    }
    clear_pct = float(data.get("clear_pixel_pct", 0.0))
    water_pct = observed_water_rai / area * 100.0 if area else 0.0

    return {
        "status": data["status"],
        "qa": qa_label(clear_pct, water_pct),
        "clear_pct": clear_pct,
        "scenes": int(data.get("scenes_used", 0)),
        "scene_ids": [item.get("id") for item in data.get("scene_metadata", [])],
        "green_rai": None if equivalent["high"] is None else round(equivalent["high"], 4),
        "yellow_rai": None if equivalent["medium"] is None else round(equivalent["medium"], 4),
        "red_rai": None if equivalent["low"] is None else round(equivalent["low"], 4),
        "bare_error_alloc_rai": bare_error,
        "water_observed_rai": round(observed_water_rai, 4),
        "unknown_observed_rai": round(observed_unknown_rai, 4),
        "mean_fcd_score": round(float(np.nanmean(fcd[land])), 4) if land.any() else None,
    }, class_code


def save_map(path, class_code, inside):
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((*class_code.shape, 4), dtype=np.uint8)
    for code, color in COLORS.items():
        image[class_code == code, :3] = color
        image[class_code == code, 3] = 255
    unknown = inside & (class_code == 0)
    image[unknown, :3] = (140, 140, 140)
    image[unknown, 3] = 180
    Image.fromarray(image, "RGBA").save(path, optimize=True)


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_series(name, dates, plots):
    batches = {}
    reference_year, reference_month = dates[0]
    batches[(reference_year, reference_month)] = build_batch(plots, reference_year, reference_month)
    calibration = fit(batches[(reference_year, reference_month)], mk(reference_year, reference_month))
    province_anchors = anchors(plots, batches[(reference_year, reference_month)], calibration)
    observations = {plot["code"]: {} for plot in plots}

    for year, month in dates:
        if (year, month) not in batches:
            batches[(year, month)] = build_batch(plots, year, month)
        for plot in plots:
            data = batches[(year, month)][plot["code"]]
            result, class_code = classify(plot, data, calibration, province_anchors)
            result.update(month=mk(year, month), thai_year=ty(year))
            observations[plot["code"]][mk(year, month)] = result
            save_map(OUT / "maps" / name / plot["code"] / f"fcd_{mk(year, month)}.png", class_code, data["inside"])

    portfolio = []
    for year, month in dates:
        key = mk(year, month)
        rows = [observations[plot["code"]][key] for plot in plots]
        by_code = {plot["code"]: plot for plot in plots}
        available_codes = [plot["code"] for plot in plots if observations[plot["code"]][key]["green_rai"] is not None]
        coverage = round(sum(float(by_code[code]["area_rai"]) for code in available_codes), 2)

        def total(field):
            return round(sum(float(row[field]) for row in rows if row[field] is not None), 2)

        portfolio.append({
            "month": key,
            "thai_year": ty(year),
            "green_rai": total("green_rai"),
            "yellow_rai": total("yellow_rai"),
            "red_rai": total("red_rai"),
            "bare_error_alloc_rai": total("bare_error_alloc_rai"),
            "water_observed_rai": total("water_observed_rai"),
            "unknown_observed_rai": total("unknown_observed_rai"),
            "equivalent_coverage_area_rai": coverage,
            "equivalent_coverage_pct": round(coverage / PDD_TOTAL_PROJECT_AREA_RAI * 100.0, 2),
            "missing_equivalent_area_rai": round(PDD_TOTAL_PROJECT_AREA_RAI - coverage, 2),
            "low_qa_plots": sum(row["qa"] == "LOW_QA" for row in rows),
            "water_qa_plots": sum(row["qa"] in {"WATER_INFLUENCED", "TIDE_DOMINATED"} for row in rows),
        })

    reference = portfolio[0]
    minimum_coverage = PDD_TOTAL_PROJECT_AREA_RAI * MIN_PORTFOLIO_COVERAGE_FOR_DELTA
    for row in portfolio:
        comparable = (
            row["equivalent_coverage_area_rai"] >= minimum_coverage
            and reference["equivalent_coverage_area_rai"] >= minimum_coverage
        )
        row["green_delta_vs_2023_rai"] = (
            round(row["green_rai"] - reference["green_rai"], 2) if comparable else None
        )
        row["red_delta_vs_2023_rai"] = (
            round(row["red_rai"] - reference["red_rai"], 2) if comparable else None
        )

    plot_results = []
    for plot in plots:
        rows = [observations[plot["code"]][mk(year, month)] for year, month in dates]
        first, last = rows[0], rows[-1]
        delta_green = (
            None if first["green_rai"] is None or last["green_rai"] is None
            else round(last["green_rai"] - first["green_rai"], 2)
        )
        delta_red = (
            None if first["red_rai"] is None or last["red_rai"] is None
            else round(last["red_rai"] - first["red_rai"], 2)
        )
        plot_results.append({
            "code": plot["code"],
            "province": plot["province"],
            "area_rai": plot["area_rai"],
            "delta_green_rai": delta_green,
            "delta_red_rai": delta_red,
            "observations": rows,
        })

    return {
        "series": name,
        "calibration": calibration,
        "province_anchors": province_anchors,
        "portfolio": portfolio,
        "plots": plot_results,
    }


def consensus(results, plots):
    by_series = {
        result["series"]: {plot["code"]: plot for plot in result["plots"]}
        for result in results
    }
    rows = []
    for plot in plots:
        deltas = []
        row = {"code": plot["code"], "province": plot["province"], "area_rai": plot["area_rai"]}
        qa_penalty = 0
        for series_name in ("march", "august"):
            result = by_series[series_name][plot["code"]]
            row[f"{series_name}_green_delta_rai"] = result["delta_green_rai"]
            row[f"{series_name}_red_delta_rai"] = result["delta_red_rai"]
            qa = result["observations"][-1]["qa"]
            row[f"{series_name}_2026_qa"] = qa
            if result["delta_green_rai"] is not None and result["delta_red_rai"] is not None:
                deltas.append((result["delta_green_rai"], result["delta_red_rai"]))
            qa_penalty += 2 if qa == "LOW_QA" else 1 if qa in {"WATER_INFLUENCED", "TIDE_DOMINATED"} else 0

        avg_green = round(float(np.mean([item[0] for item in deltas])), 2) if deltas else None
        avg_red = round(float(np.mean([item[1] for item in deltas])), 2) if deltas else None
        row["avg_green_delta_rai"] = avg_green
        row["avg_red_delta_rai"] = avg_red
        tolerance = max(1.0, float(plot["area_rai"]) * 0.01)
        directions = [
            "improve" if green > tolerance and red < -tolerance
            else "decline" if green < -tolerance and red > tolerance
            else "mixed"
            for green, red in deltas
        ]
        if len(directions) == 2 and directions[0] == directions[1]:
            row["season_agreement"] = "BOTH_SEASONS_" + directions[0].upper()
        elif len(directions) < 2:
            row["season_agreement"] = "ONE_SEASON_ONLY"
        else:
            row["season_agreement"] = "SEASON_SENSITIVE"

        concern = (
            max(0.0, -avg_green if avg_green is not None else 0.0)
            + max(0.0, avg_red if avg_red is not None else 0.0)
            + qa_penalty * tolerance
        )
        row["field_priority_score"] = round(concern, 2)
        row["field_priority"] = (
            "HIGH"
            if "DECLINE" in row["season_agreement"] or concern > float(plot["area_rai"]) * 0.10
            else "REVIEW"
            if row["season_agreement"] in {"SEASON_SENSITIVE", "ONE_SEASON_ONLY"} or qa_penalty
            else "ROUTINE"
        )
        rows.append(row)
    return sorted(rows, key=lambda item: item["field_priority_score"], reverse=True)


def fmt_delta(value):
    return "N/A" if value is None else f"{value:+,.2f}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plots = load_plots()
    results = []
    for name, dates in SERIES.items():
        result = run_series(name, dates, plots)
        results.append(result)
        (OUT / f"{name}_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_csv(OUT / f"{name}_portfolio.csv", result["portfolio"])

    ranking = consensus(results, plots)
    write_csv(OUT / "plot_change_ranking.csv", ranking)

    lines = [
        "# PDD22 Satellite FCD Screening V2",
        "",
        "**Preliminary screening; not verified T-VER credit.**",
        "",
        "2023 is a satellite reference, not the official PDD baseline. PDD-equivalent 2023 class shares are anchored to PDD Table 3-1 by province, so the 2023 fit is calibration rather than independent validation.",
        "",
        "| Series | Year | Green | Yellow | Red | Coverage | Water observed | Low QA |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        for row in result["portfolio"]:
            lines.append(
                f"| {result['series']} | {row['thai_year']} | {row['green_rai']:,.2f} | "
                f"{row['yellow_rai']:,.2f} | {row['red_rai']:,.2f} | "
                f"{row['equivalent_coverage_pct']:.1f}% | {row['water_observed_rai']:,.2f} | "
                f"{row['low_qa_plots']} |"
            )

    lines += ["", "## 2023 → 2026"]
    for result in results:
        last = result["portfolio"][-1]
        lines.append(
            f"- {result['series']}: green {fmt_delta(last['green_delta_vs_2023_rai'])} rai; "
            f"red {fmt_delta(last['red_delta_vs_2023_rai'])} rai; "
            f"2026 coverage {last['equivalent_coverage_pct']:.1f}%"
        )

    lines += ["", "## Highest field-check priority"]
    for index, item in enumerate(ranking[:10], 1):
        lines.append(
            f"{index}. {item['code']} — {item['field_priority']} — {item['season_agreement']} — "
            f"green Δ {item['avg_green_delta_rai']} rai, red Δ {item['avg_red_delta_rai']} rai"
        )

    lines += [
        "",
        "## Carbon boundary",
        f"PDD baseline tree carbon = {PDD_BASELINE_TREE_CARBON_TCO2E:,.2f} tCO2e; "
        f"planning increment = {PDD_INCREMENT_TCO2E_PER_RAI_YEAR:.2f} tCO2e/rai/year. "
        "No satellite-adjusted tCO2e is asserted because the PDD does not provide a validated FCD-class carbon-density conversion.",
        "",
        "August is retained as a seasonal/tidal sensitivity check. Missing or low-clear months are explicitly flagged and portfolio deltas are suppressed when equivalent coverage is below 95% of project area.",
        "",
        "August 2026 is a partial current-month observation using only scenes available when the workflow runs.",
    ]
    (OUT / "EXECUTIVE_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    carbon = {
        "screening_only": True,
        "pdd_baseline_tree_carbon_tco2e": PDD_BASELINE_TREE_CARBON_TCO2E,
        "pdd_increment_tco2e_per_rai_year": PDD_INCREMENT_TCO2E_PER_RAI_YEAR,
        "project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
        "pdd_planning_benchmark": [
            {"thai_year": 2567, "cumulative_increment_tco2e": 0.0},
            {
                "thai_year": 2568,
                "cumulative_increment_tco2e": round(
                    PDD_TOTAL_PROJECT_AREA_RAI * PDD_INCREMENT_TCO2E_PER_RAI_YEAR, 2
                ),
            },
            {
                "thai_year": 2569,
                "cumulative_increment_tco2e": round(
                    PDD_TOTAL_PROJECT_AREA_RAI * PDD_INCREMENT_TCO2E_PER_RAI_YEAR * 2, 2
                ),
            },
        ],
        "satellite_adjusted_credit_tco2e": None,
    }
    (OUT / "carbon_screening.json").write_text(
        json.dumps(carbon, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "manifest.json").write_text(
        json.dumps(
            {
                "model_version": "pdd22_v2_pdd_anchored",
                "plot_count": 22,
                "project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
                "series": SERIES,
                "portfolio_delta_minimum_coverage_pct": MIN_PORTFOLIO_COVERAGE_FOR_DELTA * 100,
                "limits": [
                    "Sentinel-2 adaptation, not exact Landsat-8 PDD reproduction",
                    "2023 provincial anchoring is calibration, not independent validation",
                    "water/cloud reported as QA rather than interpreted as forest loss",
                    "missing satellite months do not receive fabricated FCD classes",
                    "August 2026 is a partial current-month observation",
                    "no satellite carbon credit asserted",
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    for result in results:
        print(result["series"], result["portfolio"][-1], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
