#!/usr/bin/env python3
"""Calibrate the 13-STC Green Cover NDVI threshold against drone-derived tree-density extremes.

This is intentionally site-specific. It does not treat detector output as field ground truth.
Dense high-confidence tree cells are positive references; strong empty cells are negatives.
Training and holdout samples are split by 50 m spatial blocks to reduce spatial leakage.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from rasterio.transform import from_bounds, rowcol
from rasterio.warp import Resampling

import process_verified_12_dates as base

BASE_DIR = Path(__file__).resolve().parent
REFERENCE_PATH = BASE_DIR / "data" / "calibration" / "13stc_green_proxy_reference.json"
OUTPUT_PATH = BASE_DIR / "data" / "calibration" / "green_proxy_calibration.json"

CALIBRATION_SITE_ID = 76
DEFAULT_THRESHOLD = 0.25
SEARCH_MIN = 0.15
SEARCH_MAX = 0.40
SEARCH_STEP = 0.005
MIN_HOLDOUT_PRECISION = 0.80
MIN_HOLDOUT_BALANCED_ACCURACY = 0.65
MIN_VALID_TRAIN = 80
MIN_VALID_HOLDOUT = 50

WINDOW_START = os.environ.get("PRASAE_CALIBRATION_START", "2026-07-01")
WINDOW_END = os.environ.get("PRASAE_CALIBRATION_END", "2026-08-17")
MAX_SCENES = int(os.environ.get("PRASAE_CALIBRATION_MAX_SCENES", "8"))
MAX_CLOUD_COVER = float(os.environ.get("PRASAE_CALIBRATION_MAX_CLOUD", "85"))


def load_reference() -> dict[str, Any]:
    payload = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    raw_records = payload.get("records") or []
    if not raw_records:
        raise RuntimeError(f"No calibration records in {REFERENCE_PATH}")
    schema = payload.get("record_schema") or ["lon", "lat", "positive", "split"]
    records = []
    for raw in raw_records:
        row = dict(zip(schema, raw)) if isinstance(raw, list) else dict(raw)
        row["y"] = int(row.get("positive", row.get("y", 0)))
        row["label"] = "positive" if row["y"] else "negative"
        records.append(row)
    payload["records"] = records
    return payload


def grid_for_records(records: list[dict[str, Any]]) -> base.Grid:
    lons = np.asarray([float(r["lon"]) for r in records], dtype=float)
    lats = np.asarray([float(r["lat"]) for r in records], dtype=float)
    pad = 0.0010
    bbox = (
        float(lons.min() - pad),
        float(lats.min() - pad),
        float(lons.max() + pad),
        float(lats.max() + pad),
    )
    mid_lat = (bbox[1] + bbox[3]) / 2.0
    width_m = (bbox[2] - bbox[0]) * 111_000.0 * math.cos(math.radians(mid_lat))
    height_m = (bbox[3] - bbox[1]) * 111_000.0
    width = max(32, int(math.ceil(width_m / 10.0)))
    height = max(32, int(math.ceil(height_m / 10.0)))
    return base.Grid(
        bbox=bbox,
        width=width,
        height=height,
        transform=from_bounds(*bbox, width, height),
    )


def search_calibration_scenes(catalog, grid: base.Grid):
    search = catalog.search(
        collections=[base.COLLECTION],
        bbox=list(grid.bbox),
        datetime=f"{WINDOW_START}/{WINDOW_END}T23:59:59Z",
        query={"eo:cloud_cover": {"lt": MAX_CLOUD_COVER}},
    )
    items = list(search.items())
    items.sort(key=lambda item: item.properties.get("eo:cloud_cover", 100.0))
    return items[:MAX_SCENES]


def build_ndvi_composite(items, grid: base.Grid):
    layers = []
    metadata = []
    for item in items:
        try:
            scl = base.read_asset_to_grid(item, "SCL", grid, Resampling.nearest)
            b04 = base.read_asset_to_grid(item, "B04", grid, Resampling.bilinear)
            b08 = base.read_asset_to_grid(item, "B08", grid, Resampling.bilinear)
            clear = base.cloud_clear_mask(scl, b04, b08)
            ndvi = base.safe_normalized_difference(b08, b04)
            ndvi[~clear] = np.nan
            if np.isfinite(ndvi).sum() == 0:
                continue
            layers.append(ndvi)
            metadata.append({
                "id": item.id,
                "datetime": item.datetime.isoformat() if item.datetime else None,
                "catalog_cloud_cover_pct": item.properties.get("eo:cloud_cover"),
            })
        except Exception as exc:
            print(f"Calibration scene {item.id} skipped: {exc}")
    if not layers:
        raise RuntimeError("No usable Sentinel-2 calibration scenes")
    with np.errstate(all="ignore"):
        composite = np.nanmedian(np.stack(layers, axis=0), axis=0)
    return composite, metadata


def sample_records(records: list[dict[str, Any]], composite: np.ndarray, grid: base.Grid):
    sampled = []
    for source in records:
        r, c = rowcol(grid.transform, float(source["lon"]), float(source["lat"]))
        if not (0 <= r < grid.height and 0 <= c < grid.width):
            continue
        value = float(composite[r, c])
        if not math.isfinite(value):
            continue
        sampled.append({**source, "ndvi": value, "y": int(source["y"])})
    return sampled


def confusion(rows, threshold: float):
    tp = fp = tn = fn = 0
    for row in rows:
        pred = row["ndvi"] > threshold
        actual = bool(row["y"])
        if pred and actual:
            tp += 1
        elif pred and not actual:
            fp += 1
        elif not pred and not actual:
            tn += 1
        else:
            fn += 1
    return tp, fp, tn, fn


def metric_payload(rows, threshold: float):
    tp, fp, tn, fn = confusion(rows, threshold)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    specificity = tn / (tn + fp) if tn + fp else 0.0
    balanced_accuracy = (recall + specificity) / 2.0
    beta2 = 0.25
    f05 = (
        (1 + beta2) * precision * recall / (beta2 * precision + recall)
        if precision + recall else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": round(float(threshold), 3),
        "n": len(rows),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "specificity": round(specificity, 4),
        "balanced_accuracy": round(balanced_accuracy, 4),
        "f0_5": round(f05, 4),
        "f1": round(f1, 4),
    }


def choose_threshold(train_rows):
    thresholds = np.arange(SEARCH_MIN, SEARCH_MAX + SEARCH_STEP / 2, SEARCH_STEP)
    scored = [metric_payload(train_rows, float(t)) for t in thresholds]
    conservative = [m for m in scored if m["precision"] >= 0.90]
    pool = conservative if conservative else scored
    best = max(pool, key=lambda m: (m["f0_5"], m["balanced_accuracy"], m["threshold"]))
    return float(best["threshold"]), scored


def main() -> int:
    reference = load_reference()
    records = list(reference["records"])
    grid = grid_for_records(records)
    catalog = base.stac_client()
    items = search_calibration_scenes(catalog, grid)
    if not items:
        raise RuntimeError("No Sentinel-2 scenes found in calibration window")
    composite, scene_meta = build_ndvi_composite(items, grid)
    sampled = sample_records(records, composite, grid)
    train = [r for r in sampled if r["split"] == "train"]
    holdout = [r for r in sampled if r["split"] == "holdout"]

    candidate_threshold, score_table = choose_threshold(train)
    candidate_train = metric_payload(train, candidate_threshold)
    candidate_holdout = metric_payload(holdout, candidate_threshold)
    baseline_train = metric_payload(train, DEFAULT_THRESHOLD)
    baseline_holdout = metric_payload(holdout, DEFAULT_THRESHOLD)

    enough_data = len(train) >= MIN_VALID_TRAIN and len(holdout) >= MIN_VALID_HOLDOUT
    holdout_quality = (
        candidate_holdout["precision"] >= MIN_HOLDOUT_PRECISION
        and candidate_holdout["balanced_accuracy"] >= MIN_HOLDOUT_BALANCED_ACCURACY
    )
    no_material_regression = (
        candidate_holdout["f0_5"] >= baseline_holdout["f0_5"] - 0.01
        and candidate_holdout["balanced_accuracy"] >= baseline_holdout["balanced_accuracy"] - 0.02
    )
    promoted = bool(enough_data and holdout_quality and no_material_regression)
    selected_threshold = candidate_threshold if promoted else DEFAULT_THRESHOLD

    result = {
        "schema_version": "1.0",
        "site_id": CALIBRATION_SITE_ID,
        "site": reference.get("site"),
        "status": "PROMOTED_DRONE_CALIBRATED" if promoted else "FALLBACK_DEFAULT",
        "selected_threshold": round(float(selected_threshold), 3),
        "candidate_threshold": round(float(candidate_threshold), 3),
        "default_threshold": DEFAULT_THRESHOLD,
        "calibration_window": {"start": WINDOW_START, "end": WINDOW_END},
        "scenes": scene_meta,
        "sample_counts": {
            "reference_total": len(records),
            "sampled_total": len(sampled),
            "train": len(train),
            "holdout": len(holdout),
        },
        "candidate_metrics": {"train": candidate_train, "holdout": candidate_holdout},
        "baseline_0_25_metrics": {"train": baseline_train, "holdout": baseline_holdout},
        "promotion_gate": {
            "enough_data": enough_data,
            "holdout_precision_min": MIN_HOLDOUT_PRECISION,
            "holdout_balanced_accuracy_min": MIN_HOLDOUT_BALANCED_ACCURACY,
            "holdout_quality_pass": holdout_quality,
            "no_material_regression": no_material_regression,
        },
        "reference": {
            **reference.get("reference_source", {}),
            "reference_type": reference.get("reference_type"),
            "grid": reference.get("grid"),
            "sampling": reference.get("sampling"),
        },
        "method_note": (
            "Site-specific threshold calibration using dense high-confidence drone-tree cells "
            "versus strong empty cells. This is detector-derived calibration, not field ground truth; "
            "the calibrated threshold is applied only to PLOT_076."
        ),
        "score_table_train": score_table,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "selected_threshold": result["selected_threshold"],
        "candidate_holdout": candidate_holdout,
        "baseline_holdout": baseline_holdout,
        "scenes": len(scene_meta),
        "sample_counts": result["sample_counts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
