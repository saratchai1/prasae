# Prasae Mangrove Monitoring

Live: https://saratchai1.github.io/prasae/

Current viewer contract:
- exactly 12 Sentinel-2 observation/composite dates
- Esri World Imagery as basemap
- Sentinel imagery clipped to plot polygons
- stable frame swapping without Esri flash between dates
- Before/After rendered as two synchronized side-by-side Leaflet maps
- selecting another plot refreshes detail and Before/After views immediately

Dates: 2023-09, 2023-12, 2024-03, 2024-06, 2024-09, 2024-12, 2025-03, 2025-06, 2025-09, 2025-12, 2026-03, 2026-08.

Verified statistics are generated separately by `process_verified_12_dates.py`; the UI does not fall back to interpolated or synthetic statistics.
