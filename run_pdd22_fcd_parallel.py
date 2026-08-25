#!/usr/bin/env python3
"""Parallel runner for process_pdd22_fcd.py.

Keeps one fixed March-2023 FCD calibration while parallelizing remote Sentinel-2
reads across plots. Output schema is identical to process_pdd22_fcd.py.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import process_pdd22_fcd as p
import process_verified_12_dates as base
from pdd22_config import OBSERVATION_MONTHS, PDD22_PLOTS, PDD_TOTAL_PROJECT_AREA_RAI

MAX_WORKERS = int(os.environ.get("PDD22_WORKERS", "6"))


def build_one_composite(plot, year, month):
    return p.build_composite(base.stac_client(), plot, year, month)


def process_one_plot(plot, reference_data, calibration, target_config):
    observations = []
    class_by_date = {}
    inside_ref = None
    ref_year, ref_month = OBSERVATION_MONTHS[0]
    runtime_catalog = base.stac_client()

    for year, month in OBSERVATION_MONTHS:
        key = p.month_key(year, month)
        data = reference_data if (year, month) == (ref_year, ref_month) else p.build_composite(runtime_catalog, plot, year, month)
        metrics, class_code = p.classify(plot, data, calibration)
        observations.append({"month": key, "year": year, "thai_year": year + 543, **metrics})
        class_by_date[key] = class_code
        if inside_ref is None:
            inside_ref = data["inside"]
        p.save_class_map(plot, key, class_code, data["inside"])

    date_keys = [p.month_key(y, m) for y, m in OBSERVATION_MONTHS]
    transitions = [
        p.transition_matrix(plot, from_key, to_key, class_by_date[from_key], class_by_date[to_key], inside_ref)
        for from_key, to_key in zip(date_keys[:-1], date_keys[1:])
    ]
    cfg = target_config[plot["code"]]
    plot_result = {
        "order": cfg["order"], "code": plot["code"], "province": plot["province"], "coast": plot["coast"],
        "area_rai": plot["area_rai"], "geometry_area_rai": plot.get("geometry_area_rai"), "observations": observations,
    }
    transition_result = {"code": plot["code"], "province": plot["province"], "transitions": transitions}
    return plot_result, transition_result


def main() -> int:
    p.DATA_DIR.mkdir(parents=True, exist_ok=True)
    p.MAP_DIR.mkdir(parents=True, exist_ok=True)
    plots = p.load_catalog()
    target_config = {item["code"]: item for item in PDD22_PLOTS}
    ref_year, ref_month = OBSERVATION_MONTHS[0]

    print(f"Parallel workers: {MAX_WORKERS}", flush=True)
    print("Building March-2023 reference composites...", flush=True)
    reference_composites = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(build_one_composite, plot, ref_year, ref_month): plot for plot in plots}
        for future in as_completed(futures):
            plot = futures[future]
            reference_composites[plot["code"]] = future.result()
            data = reference_composites[plot["code"]]
            print(
                f"  reference {plot['code']}: {data['status']} scenes={data['scenes_used']} clear={data['clear_pixel_pct']}%",
                flush=True,
            )

    calibration = p.fit_reference_calibration(reference_composites)
    p.CALIBRATION_PATH.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Reference calibration: PCA samples={calibration['reference_pca_sample_count']} "
        f"CSI samples={calibration['reference_csi_sample_count']}",
        flush=True,
    )

    plot_results = []
    transition_results = []
    print("Processing March-2024/2025/2026 across 22 plots...", flush=True)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_one_plot, plot, reference_composites[plot["code"]], calibration, target_config): plot
            for plot in plots
        }
        for future in as_completed(futures):
            plot = futures[future]
            plot_result, transition_result = future.result()
            plot_results.append(plot_result)
            transition_results.append(transition_result)
            latest = plot_result["observations"][-1]
            print(
                f"  done {plot['code']}: 2026 green={latest['high_green_rai']:.2f} "
                f"yellow={latest['medium_yellow_rai']:.2f} red={latest['low_red_rai']:.2f} "
                f"water={latest['water_rai']:.2f} unknown={latest['unknown_rai']:.2f} QA={latest['qa_label']}",
                flush=True,
            )

    plot_results.sort(key=lambda item: item["order"])
    transition_results.sort(key=lambda item: target_config[item["code"]]["order"])
    portfolio = p.aggregate_portfolio(plot_results)
    pdd_compare = p.compare_reference_to_pdd(plot_results)
    payload = {
        "schema_version": "1.0",
        "method": "PDD-style FCD proxy adapted to Sentinel-2 L2A",
        "screening_only": True,
        "project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
        "reference_year_assumption": "2566/2023 is a satellite reference requested by the user; it is not the PDD's official T-VER baseline survey date",
        "observation_months": [p.month_key(y, m) for y, m in OBSERVATION_MONTHS],
        "calibration": calibration,
        "portfolio": portfolio,
        "plots": plot_results,
    }
    p.METRICS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    p.TRANSITIONS_PATH.write_text(
        json.dumps({"unit": "rai", "class_labels": p.CLASS_LABELS, "plots": transition_results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    p.CARBON_PATH.write_text(json.dumps(p.carbon_screening_payload(portfolio), ensure_ascii=False, indent=2), encoding="utf-8")
    p.write_csvs(plot_results, portfolio, pdd_compare)

    print("\nPortfolio summary", flush=True)
    for row in portfolio:
        print(
            f"{row['thai_year']} ({row['month']}): green={row['high_green_rai']:,.2f} rai "
            f"yellow={row['medium_yellow_rai']:,.2f} red={row['low_red_rai']:,.2f} "
            f"water={row['water_rai']:,.2f} unknown={row['unknown_rai']:,.2f} "
            f"delta_green={row['delta_high_vs_2023_rai']:+,.2f} delta_red={row['delta_low_vs_2023_rai']:+,.2f}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
