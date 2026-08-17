#!/usr/bin/env python3
"""Extract project plots from KMZ while preserving Polygon holes and MultiPolygons."""

from __future__ import annotations

import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup
from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
KMZ_PATH = BASE_DIR / "my-land" / "STC_VSD_EVR.kmz"
GEOD = Geod(ellps="WGS84")

PROVINCES_TH = [
    "กระบี่", "พังงา", "ระยอง", "จันทบุรี", "สตูล", "ปัตตานี",
    "สมุทรสงคราม", "ตราด", "ภูเก็ต", "ตรัง", "ชุมพร",
    "ประจวบคีรีขันธ์", "นครศรีธรรมราช", "ระนอง", "สุราษฎร์ธานี",
    "ฉะเชิงเทรา", "สมุทรปราการ", "สมุทรสาคร", "เพชรบุรี", "ชลบุรี", "สงขลา"
]


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


def infer_province(raw_name: str, centroid_lat: float, centroid_lon: float) -> str:
    match = re.search(r"จังหวัด\s*([^\s,]+)", raw_name)
    if match:
        return match.group(1)
    for province in PROVINCES_TH:
        if province in raw_name:
            return province

    if 12.4 <= centroid_lat <= 12.8 and 101.5 <= centroid_lon <= 101.9:
        return "ระยอง"
    if 12.2 <= centroid_lat <= 12.8 and 101.9 <= centroid_lon <= 102.6:
        return "จันทบุรี"
    if 7.8 <= centroid_lat <= 8.5 and 98.7 <= centroid_lon <= 99.2:
        return "กระบี่"
    if 8.2 <= centroid_lat <= 8.8 and 98.3 <= centroid_lon <= 98.7:
        return "พังงา"
    if 6.4 <= centroid_lat <= 7.0 and 99.8 <= centroid_lon <= 100.3:
        return "สตูล"
    if 6.7 <= centroid_lat <= 7.0 and 101.1 <= centroid_lon <= 101.6:
        return "ปัตตานี"
    if 13.2 <= centroid_lat <= 13.5 and 99.8 <= centroid_lon <= 100.2:
        return "สมุทรสงคราม"
    if 9.5 <= centroid_lat <= 10.5 and 98.4 <= centroid_lon <= 98.8:
        return "ระนอง"
    if 7.8 <= centroid_lat <= 8.2 and 98.2 <= centroid_lon <= 98.5:
        return "ภูเก็ต"
    if 11.5 <= centroid_lat <= 12.5 and 99.5 <= centroid_lon <= 100.1:
        return "ประจวบคีรีขันธ์"
    if 11.8 <= centroid_lat <= 12.5 and 102.4 <= centroid_lon <= 102.9:
        return "ตราด"
    return "ไม่ระบุ"


def geodesic_area_rai(geom) -> float:
    area_m2, _ = GEOD.geometry_area_perimeter(geom)
    return abs(area_m2) / 1600.0


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Reading KMZ: {KMZ_PATH}")
    with zipfile.ZipFile(KMZ_PATH, "r") as archive:
        kml_files = [name for name in archive.namelist() if name.lower().endswith(".kml")]
        if not kml_files:
            raise RuntimeError("KMZ contains no KML file")
        soup = BeautifulSoup(archive.read(kml_files[0]), "xml")

    raw_parcels = []
    for index, placemark in enumerate(soup.find_all("Placemark"), start=1):
        name_element = placemark.find("name")
        raw_name = name_element.text.strip() if name_element else f"Plot_{index}"
        polygons = [parse_polygon(element) for element in placemark.find_all("Polygon")]
        polygons = [polygon for polygon in polygons if polygon is not None]
        if not polygons:
            continue

        geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            continue

        province = infer_province(raw_name, geom.centroid.y, geom.centroid.x)
        area_match = re.search(r"เนื้อที่\s*([\d.]+)\s*ไร่", raw_name)
        declared_area = float(area_match.group(1)) if area_match else None

        plot_number = re.search(r"(แปลง\s*\d+)", raw_name)
        if plot_number:
            plot_key = f"{plot_number.group(1)}-{province}"
        else:
            plot_key = f"{re.sub(r'\(\d+\)', '', raw_name).strip()}-{province}"

        raw_parcels.append({
            "raw_name": raw_name,
            "plot_key": plot_key,
            "province": province,
            "declared_area_rai": declared_area,
            "geom": geom,
        })

    grouped = defaultdict(list)
    for parcel in raw_parcels:
        grouped[parcel["plot_key"]].append(parcel)

    catalog = []
    features = []
    for index, (_, items) in enumerate(grouped.items(), start=1):
        merged = unary_union([item["geom"] for item in items])
        if not merged.is_valid:
            merged = merged.buffer(0)
        if merged.is_empty:
            continue

        declared_parts = [item["declared_area_rai"] for item in items if item["declared_area_rai"] is not None]
        total_area = sum(declared_parts) if len(declared_parts) == len(items) else geodesic_area_rai(merged)
        province = items[0]["province"]
        display_title = re.sub(r"\(\d+\)", "", items[0]["raw_name"]).strip()
        if "เนื้อที่" in display_title:
            display_title = re.sub(r"เนื้อที่\s*[\d.]+\s*ไร่", f"เนื้อที่ {total_area:.2f} ไร่", display_title)

        bounds = [round(value, 8) for value in merged.bounds]
        centroid = [round(merged.centroid.y, 8), round(merged.centroid.x, 8)]
        plot = {
            "id": index,
            "code": f"PLOT_{index:03d}",
            "name": display_title,
            "province": province,
            "area_rai": round(total_area, 2),
            "parts_count": len(items),
            "centroid": centroid,
            "bounds": bounds,
            "geometry": mapping(merged),
        }
        catalog.append(plot)
        features.append({
            "type": "Feature",
            "id": index,
            "geometry": plot["geometry"],
            "properties": {key: value for key, value in plot.items() if key != "geometry"},
        })

    with (DATA_DIR / "plots_catalog.json").open("w", encoding="utf-8") as handle:
        json.dump(catalog, handle, ensure_ascii=False, indent=2)
    with (DATA_DIR / "plots.geojson").open("w", encoding="utf-8") as handle:
        json.dump({"type": "FeatureCollection", "features": features}, handle, ensure_ascii=False, indent=2)

    print(f"Generated {len(catalog)} primary plots")
    print(f"Total area: {sum(plot['area_rai'] for plot in catalog):,.2f} rai")


if __name__ == "__main__":
    main()
