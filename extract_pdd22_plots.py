#!/usr/bin/env python3
"""Extract exact participating boundaries for the 22 Group-2 PDD plots.

The source KMZ contains multiple VSD layers for some plot codes (for example an
allocated boundary and a smaller participating-project boundary). The generic
extractor groups by code and can union/sum those layers, so this script selects
geometry using the PDD Table 1-1 / 1-8 participating area as the authoritative
selector.
"""

from __future__ import annotations

import csv
import itertools
import json
import re
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

from pdd22_config import PDD22_PLOTS, PDD_TOTAL_PROJECT_AREA_RAI

BASE_DIR = Path(__file__).resolve().parent
KMZ_PATH = BASE_DIR / "my-land" / "STC_VSD_EVR.kmz"
OUT_DIR = BASE_DIR / "data" / "pdd22"
GEOD = Geod(ellps="WGS84")
AREA_MATCH_TOLERANCE_RAI = 0.10
GEOMETRY_WARN_RATIO = 0.10
GEOMETRY_FAIL_RATIO = 0.35


def parse_ring(boundary_element):
    if boundary_element is None:
        return []
    coordinates = boundary_element.find("coordinates")
    if coordinates is None:
        return []
    points = []
    for token in coordinates.text.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return points


def parse_polygon(poly_element):
    outer = parse_ring(poly_element.find("outerBoundaryIs"))
    if len(outer) < 3:
        return None
    holes = []
    for inner in poly_element.find_all("innerBoundaryIs"):
        ring = parse_ring(inner)
        if len(ring) >= 3:
            holes.append(ring)
    geom = Polygon(outer, holes=holes)
    if not geom.is_valid:
        geom = geom.buffer(0)
    if geom.is_empty or not geom.is_valid:
        return None
    return geom


def geodesic_area_rai(geom) -> float:
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 1600.0


def parse_area(text: str):
    patterns = [
        r"เนื้อที่\s*([\d,]+(?:\.\d+)?)\s*ไร่",
        r"พื้นที่\s*([\d,]+(?:\.\d+)?)\s*ไร่",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def parse_code(text: str):
    match = re.search(r"(?<!\d)(\d{1,3}\s*-\s*VSD)(?![A-Za-z])", text, re.IGNORECASE)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1)).upper()


def read_candidates():
    if not KMZ_PATH.exists():
        raise FileNotFoundError(f"Missing KMZ: {KMZ_PATH}")
    with zipfile.ZipFile(KMZ_PATH, "r") as archive:
        kml_files = [name for name in archive.namelist() if name.lower().endswith(".kml")]
        if not kml_files:
            raise RuntimeError("KMZ contains no KML file")
        soup = BeautifulSoup(archive.read(kml_files[0]), "xml")

    candidates = []
    for placemark_index, placemark in enumerate(soup.find_all("Placemark"), start=1):
        name_element = placemark.find("name")
        raw_name = name_element.text.strip() if name_element else f"Placemark_{placemark_index}"
        code = parse_code(raw_name)
        if not code:
            continue
        polygons = [parse_polygon(element) for element in placemark.find_all("Polygon")]
        polygons = [polygon for polygon in polygons if polygon is not None]
        if not polygons:
            continue
        geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            continue
        candidates.append({
            "placemark_index": placemark_index,
            "code": code,
            "raw_name": raw_name,
            "declared_area_rai": parse_area(raw_name),
            "geometry_area_rai": geodesic_area_rai(geom),
            "geometry": geom,
        })
    return candidates


def choose_candidates(code: str, target_area: float, all_candidates):
    candidates = [c for c in all_candidates if c["code"] == code]
    if not candidates:
        raise RuntimeError(f"{code}: no KMZ candidate found")

    exact = [
        c for c in candidates
        if c["declared_area_rai"] is not None
        and abs(c["declared_area_rai"] - target_area) <= AREA_MATCH_TOLERANCE_RAI
    ]
    if exact:
        return exact, "single/exact-declared-area"

    declared = [c for c in candidates if c["declared_area_rai"] is not None]
    best_combo = None
    best_error = float("inf")
    for r in range(1, min(len(declared), 8) + 1):
        for combo in itertools.combinations(declared, r):
            total = sum(c["declared_area_rai"] for c in combo)
            error = abs(total - target_area)
            if error < best_error - 1e-9 or (
                abs(error - best_error) <= 1e-9 and best_combo is not None and len(combo) < len(best_combo)
            ):
                best_error = error
                best_combo = combo
        if best_error <= AREA_MATCH_TOLERANCE_RAI:
            break
    if best_combo is not None and best_error <= AREA_MATCH_TOLERANCE_RAI:
        return list(best_combo), "subset/exact-declared-area-sum"

    by_geometry = sorted(candidates, key=lambda c: abs(c["geometry_area_rai"] - target_area))
    best = by_geometry[0]
    ratio = abs(best["geometry_area_rai"] - target_area) / max(target_area, 1e-9)
    if ratio > GEOMETRY_FAIL_RATIO:
        detail = [
            {
                "raw_name": c["raw_name"],
                "declared_area_rai": c["declared_area_rai"],
                "geometry_area_rai": round(c["geometry_area_rai"], 2),
            }
            for c in candidates
        ]
        raise RuntimeError(
            f"{code}: cannot identify participating layer for target {target_area:.2f} rai; "
            f"closest geometry differs by {ratio:.1%}. Candidates={detail}"
        )
    return [best], "fallback/geometry-area"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = read_candidates()
    target_codes = {item["code"] for item in PDD22_PLOTS}
    candidate_codes = {item["code"] for item in candidates}
    missing = sorted(target_codes - candidate_codes)
    if missing:
        raise RuntimeError(f"KMZ is missing target PDD codes: {missing}")

    catalog = []
    features = []
    manifest = []

    for target in PDD22_PLOTS:
        selected, selection_rule = choose_candidates(target["code"], float(target["project_area_rai"]), candidates)
        geom = unary_union([item["geometry"] for item in selected])
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty or not geom.is_valid:
            raise RuntimeError(f"{target['code']}: selected geometry is invalid")

        geometry_area = geodesic_area_rai(geom)
        area_ratio_error = abs(geometry_area - target["project_area_rai"]) / target["project_area_rai"]
        if area_ratio_error > GEOMETRY_FAIL_RATIO:
            raise RuntimeError(
                f"{target['code']}: geometry area {geometry_area:.2f} rai differs from PDD "
                f"{target['project_area_rai']:.2f} rai by {area_ratio_error:.1%}"
            )

        bounds = [round(value, 8) for value in geom.bounds]
        centroid = [round(geom.centroid.y, 8), round(geom.centroid.x, 8)]
        plot = {
            "id": int(target["order"]),
            "code": target["code"],
            "province": target["province"],
            "coast": target["coast"],
            "area_rai": float(target["project_area_rai"]),
            "allocated_area_rai": float(target["allocated_area_rai"]),
            "geometry_area_rai": round(geometry_area, 2),
            "parts_count": len(geom.geoms) if hasattr(geom, "geoms") else 1,
            "centroid": centroid,
            "bounds": bounds,
            "geometry": mapping(geom),
        }
        catalog.append(plot)
        features.append({
            "type": "Feature",
            "id": plot["id"],
            "geometry": plot["geometry"],
            "properties": {key: value for key, value in plot.items() if key != "geometry"},
        })
        manifest.append({
            "order": target["order"],
            "code": target["code"],
            "province": target["province"],
            "pdd_project_area_rai": target["project_area_rai"],
            "pdd_allocated_area_rai": target["allocated_area_rai"],
            "geometry_area_rai": round(geometry_area, 2),
            "geometry_area_difference_pct": round((geometry_area / target["project_area_rai"] - 1.0) * 100.0, 2),
            "geometry_area_warning": area_ratio_error > GEOMETRY_WARN_RATIO,
            "selection_rule": selection_rule,
            "selected_placemark_indices": [item["placemark_index"] for item in selected],
            "selected_declared_areas_rai": [item["declared_area_rai"] for item in selected],
            "selected_raw_names": [item["raw_name"] for item in selected],
        })

    pdd_total = round(sum(item["area_rai"] for item in catalog), 2)
    if pdd_total != PDD_TOTAL_PROJECT_AREA_RAI:
        raise RuntimeError(f"Output PDD total {pdd_total} != {PDD_TOTAL_PROJECT_AREA_RAI}")

    (OUT_DIR / "plots_catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "plots.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "selection_manifest.json").write_text(
        json.dumps({
            "source": str(KMZ_PATH.relative_to(BASE_DIR)),
            "method": "select PDD participating layer by Table 1-1/Table 1-8 project area",
            "pdd_total_project_area_rai": PDD_TOTAL_PROJECT_AREA_RAI,
            "plots": manifest,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (OUT_DIR / "plot_selection.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "order", "code", "province", "pdd_project_area_rai", "pdd_allocated_area_rai",
            "geometry_area_rai", "geometry_area_difference_pct", "geometry_area_warning", "selection_rule",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in manifest:
            writer.writerow({key: row[key] for key in fieldnames})

    print(f"Extracted {len(catalog)} PDD plots; authoritative area total={pdd_total:,.2f} rai")
    warnings = [m for m in manifest if m["geometry_area_warning"]]
    if warnings:
        print(f"Geometry-area warnings (> {GEOMETRY_WARN_RATIO:.0%}): {len(warnings)}")
        for item in warnings:
            print(f"  {item['code']}: {item['geometry_area_difference_pct']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
