import os
import sys
import json
import zipfile
import re
from collections import defaultdict
from bs4 import BeautifulSoup
from shapely.geometry import Polygon, MultiPolygon, shape, mapping
from shapely.ops import unary_union

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
KMZ_PATH = os.path.join(BASE_DIR, "my-land", "STC_VSD_EVR.kmz")

os.makedirs(DATA_DIR, exist_ok=True)

print(f"Reading KMZ: {KMZ_PATH}...")
with zipfile.ZipFile(KMZ_PATH, "r") as z:
    kml_name = [n for n in z.namelist() if n.endswith(".kml")][0]
    kml_bytes = z.read(kml_name)

soup = BeautifulSoup(kml_bytes, "xml")
placemarks = soup.find_all("Placemark")
print(f"Total placemarks in KML: {len(placemarks)}")

# Known provinces in Thailand for inference if not in name string
PROVINCES_TH = [
    "กระบี่", "พังงา", "ระยอง", "จันทบุรี", "สตูล", "ปัตตานี", 
    "สมุทรสงคราม", "ตราด", "ภูเก็ต", "ตรัง", "ชุมพร", 
    "ประจวบคีรีขันธ์", "นครศรีธรรมราช", "ระนอง", "สุราษฎร์ธานี", "ฉะเชิงเทรา",
    "สมุทรปราการ", "สมุทรสาคร", "เพชรบุรี", "ชลบุรี", "สงขลา"
]

raw_parcels = []

for idx, p in enumerate(placemarks):
    name_el = p.find("name")
    raw_name = name_el.text.strip() if name_el else f"Plot_{idx+1}"
    
    poly_els = p.find_all("Polygon")
    if not poly_els:
        continue
        
    poly_geoms = []
    for poly_el in poly_els:
        outer = poly_el.find("outerBoundaryIs")
        if outer:
            coord_el = outer.find("coordinates")
            if coord_el:
                pts = []
                for pt in coord_el.text.strip().split():
                    parts = pt.split(",")
                    if len(parts) >= 2:
                        pts.append((float(parts[0]), float(parts[1])))
                if len(pts) >= 3:
                    try:
                        p_geom = Polygon(pts)
                        if p_geom.is_valid:
                            poly_geoms.append(p_geom)
                        else:
                            p_geom = p_geom.buffer(0)
                            if p_geom.is_valid:
                                poly_geoms.append(p_geom)
                    except:
                        pass
                        
    if not poly_geoms:
        continue
        
    geom = poly_geoms[0] if len(poly_geoms) == 1 else MultiPolygon(poly_geoms)
    
    # Extract Province
    prov = "ไม่ระบุ"
    m_prov = re.search(r"จังหวัด\s*([^\s,]+)", raw_name)
    if m_prov:
        prov = m_prov.group(1)
    else:
        for pr in PROVINCES_TH:
            if pr in raw_name:
                prov = pr
                break
        # Infer province from coordinates if still unspecified:
        if prov == "ไม่ระบุ":
            lat, lon = geom.centroid.y, geom.centroid.x
            if 12.4 <= lat <= 12.8 and 101.5 <= lon <= 101.9:
                prov = "ระยอง"
            elif 12.2 <= lat <= 12.8 and 101.9 <= lon <= 102.6:
                prov = "จันทบุรี"
            elif 7.8 <= lat <= 8.5 and 98.7 <= lon <= 99.2:
                prov = "กระบี่"
            elif 8.2 <= lat <= 8.8 and 98.3 <= lon <= 98.7:
                prov = "พังงา"
            elif 6.4 <= lat <= 7.0 and 99.8 <= lon <= 100.3:
                prov = "สตูล"
            elif 6.7 <= lat <= 7.0 and 101.1 <= lon <= 101.6:
                prov = "ปัตตานี"
            elif 13.2 <= lat <= 13.5 and 99.8 <= lon <= 100.2:
                prov = "สมุทรสงคราม"
            elif 9.5 <= lat <= 10.5 and 98.4 <= lon <= 98.8:
                prov = "ระนอง"
            elif 7.8 <= lat <= 8.2 and 98.2 <= lon <= 98.5:
                prov = "ภูเก็ต"
            elif 11.5 <= lat <= 12.5 and 99.5 <= lon <= 100.1:
                prov = "ประจวบคีรีขันธ์"
            elif 11.8 <= lat <= 12.5 and 102.4 <= lon <= 102.9:
                prov = "ตราด"

    # Extract Area in Rai
    m_area = re.search(r"เนื้อที่\s*([\d\.]+)\s*ไร่", raw_name)
    area_rai = float(m_area.group(1)) if m_area else round(geom.area * 111319.5 * 111319.5 / 1600.0, 2)
    
    # Base Plot Key for clustering sub-parcels (e.g. แปลง 60(1) & 60(2) -> แปลง 60-STC)
    m_plot_num = re.search(r"(แปลง\s*\d+)", raw_name)
    if m_plot_num:
        plot_key = f"{m_plot_num.group(1)}-{prov}"
    else:
        clean_name = re.sub(r"\(\d+\)", "", raw_name).strip()
        plot_key = f"{clean_name}-{prov}"
        
    raw_parcels.append({
        "raw_name": raw_name,
        "plot_key": plot_key,
        "province": prov,
        "area_rai": area_rai,
        "geom": geom
    })

print(f"Total valid polygon placemarks parsed: {len(raw_parcels)}")

# Group by plot_key into primary plots
grouped = defaultdict(list)
for p in raw_parcels:
    grouped[p["plot_key"]].append(p)

print(f"Total primary plot clusters: {len(grouped)}")

plots_catalog = []
features = []

for idx, (plot_key, items) in enumerate(grouped.items()):
    geoms = [it["geom"] for it in items]
    merged_geom = unary_union(geoms) if len(geoms) > 1 else geoms[0]
    
    # Calculate area and centroid
    total_area_rai = sum(it["area_rai"] for it in items)
    province = items[0]["province"]
    
    # Clean display name
    first_name = items[0]["raw_name"]
    display_title = re.sub(r"\(\d+\)", "", first_name).strip()
    if "เนื้อที่" in display_title:
        # Format cleanly: แปลง XX-STC (YY ไร่) จังหวัด ZZ
        display_title = re.sub(r"เนื้อที่\s*[\d\.]+\s*ไร่", f"เนื้อที่ {total_area_rai:.2f} ไร่", display_title)
        
    bounds = [round(b, 6) for b in merged_geom.bounds] # [min_lon, min_lat, max_lon, max_lat]
    centroid = [round(merged_geom.centroid.y, 6), round(merged_geom.centroid.x, 6)] # [lat, lon]
    
    plot_entry = {
        "id": idx + 1,
        "code": f"PLOT_{idx+1:03d}",
        "name": display_title,
        "province": province,
        "area_rai": round(total_area_rai, 2),
        "parts_count": len(items),
        "centroid": centroid,
        "bounds": bounds,
        "geometry": mapping(merged_geom)
    }
    plots_catalog.append(plot_entry)
    
    # GeoJSON feature
    feature = {
        "type": "Feature",
        "id": idx + 1,
        "geometry": mapping(merged_geom),
        "properties": {
            "id": idx + 1,
            "code": f"PLOT_{idx+1:03d}",
            "name": display_title,
            "province": province,
            "area_rai": round(total_area_rai, 2),
            "parts_count": len(items),
            "centroid": centroid,
            "bounds": bounds
        }
    }
    features.append(feature)

geojson_doc = {
    "type": "FeatureCollection",
    "features": features
}

# Save Catalog JSON
with open(os.path.join(DATA_DIR, "plots_catalog.json"), "w", encoding="utf-8") as f:
    json.dump(plots_catalog, f, ensure_ascii=False, indent=2)

# Save GeoJSON
with open(os.path.join(DATA_DIR, "plots.geojson"), "w", encoding="utf-8") as f:
    json.dump(geojson_doc, f, ensure_ascii=False, indent=2)

print(f"\n=======================================================")
print(f"Successfully generated {len(plots_catalog)} plots catalog!")
print(f"Data saved in:")
print(f"  - {DATA_DIR}/plots_catalog.json")
print(f"  - {DATA_DIR}/plots.geojson")
print(f"Total Area: {sum(p['area_rai'] for p in plots_catalog):,.2f} ไร่")
print("=======================================================")
