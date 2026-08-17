# Mangrove Monitoring Metrics

This dashboard intentionally separates **vegetation amount**, **vegetation condition**, **water/tide context**, and **observation quality**. It does not collapse them into a single uncalibrated health score.

## 1. Whole-plot NDVI

`NDVI = (B08 - B04) / (B08 + B04)`

- Sentinel-2 native bands: B08/B04 at 10 m.
- Reported as mean/median plus P10/P90 inside the exact plot polygon.
- Useful as plot-wide greenness context.
- Water and exposed substrate can strongly move the plot mean, so whole-plot NDVI change must be interpreted with Open Water and QA.

## 2. Conservative Green Cover Proxy

Current rule:

`NDVI > 0.25`

This is the percentage of valid in-boundary pixels passing the rule.

Important:

- It is a **proxy**, not field canopy cover, survival rate, tree count, or carbon stock.
- MFI is deliberately **not** merged into this percentage.
- The 0.25 threshold is a screening threshold and should be recalibrated when plot-aligned drone/field labels are available.

## 3. Vegetation-only NDVI

Median NDVI calculated only over pixels passing the Green Cover Proxy.

This separates two questions:

- **How much visible green vegetation is present?** -> Green Cover Proxy
- **How green is the detected vegetation?** -> Vegetation-only NDVI

## 4. NDRE red-edge diagnostic

`NDRE = (B8A - B05) / (B8A + B05)`

Calculated over Green Cover pixels. B8A/B05 are 20 m Sentinel-2 bands and are resampled to the common target grid for aligned plot statistics.

NDRE is retained as a vegetation-condition diagnostic; it is not converted into biomass or carbon without field calibration.

## 5. Open Water

Current screening rule:

`MNDWI = (B03 - B11) / (B03 + B11)`

`Open Water = MNDWI > 0 AND NOT Green Cover`

Open Water is shown alongside Green Cover because tidal/water conditions can alter apparent vegetation metrics in mangrove restoration areas.

## 6. MFI signal in water

The Sentinel-2 Mangrove Forest Index (MFI; Jia et al., 2019) is calculated from red, red-edge and SWIR2 reflectance.

The dashboard reports:

`MFI signal in water = MFI > 0 AND Open Water`

This is a **diagnostic of possible submerged mangrove spectral signal**. It is not added to Green Cover and must not be described as measured canopy area.

## 7. Observation QA and comparability

Every date records:

- clear-pixel percentage inside the plot
- number of Sentinel-2 scenes used
- source scene IDs and timestamps
- processing status
- Open Water percentage

Dashboard context labels:

- `LOW QA`: clear pixels < 30%
- `TIDE-DOMINATED`: Open Water > 40%
- `WATER-INFLUENCED`: Open Water > 20%
- `COMPARABLE`: otherwise

These labels are screening aids, not statistical confidence intervals.

## 8. No fabricated time series

The system has exactly 12 declared observation/composite months. It does not:

- interpolate missing months
- substitute the nearest available image while displaying another date
- generate synthetic NDVI values

Missing or poor observations remain `no_data` / `insufficient_clear_pixels`.

## 9. Recommended next calibration step

The strongest next improvement is to create plot-aligned reference labels from UAV/field data for representative classes such as:

- visible mangrove canopy / seedlings
- open water
- mud / exposed substrate
- grass or other non-mangrove vegetation

Then evaluate thresholds and/or a supervised Sentinel-2 classifier against those labels. Until that calibration exists, all area percentages remain explicitly labeled as proxies.
