# PDD22 satellite FCD screening

This branch isolates a 22-plot screening workflow for the Group 2 PDD. It does not overwrite the existing `data/plots_catalog.json` or the existing Prasae/portfolio metrics.

## PDD basis

The Group 2 PDD contains 22 participating VSD plots with a total participating area of **6,775.53 rai**. The PDD stratifies canopy density with Forest Canopy Density (FCD):

- High / green: FCD > 65%
- Medium / yellow: FCD 30-65%
- Low / red: FCD < 30%

The PDD workflow uses AVI, Bare Soil Index, Canopy Shadow Index, PCA-derived Vegetation Density, Scaled Shadow Index, and `FCD = sqrt(VD * SSI + 1) - 1`.

## Important boundary correction

`my-land/STC_VSD_EVR.kmz` contains multiple VSD representations for some plot codes. The generic `extract_kmz_plots.py` groups by plot code and can combine allocated and participating layers. That is not acceptable for the PDD22 calculation.

`extract_pdd22_plots.py` therefore selects the layer whose declared area matches the PDD participating area in Table 1-1 / Table 1-8, and writes a separate catalogue under `data/pdd22/`.

## Sentinel-2 adaptation

`process_pdd22_fcd.py` uses Sentinel-2 L2A surface reflectance but preserves the PDD FCD structure. Because the PDD formula was written for Landsat-8 DN values, the Sentinel implementation is explicitly labelled a **PDD-style FCD proxy**, not a byte-for-byte reproduction of the original FCD raster.

For temporal comparability, the PCA basis and linear 0-100 scaling anchors are fitted once from the **March 2023** reference across the 22 plots and then frozen. March 2024, March 2025 and March 2026 use exactly the same transform. This avoids independently rescaling every year to 0-100, which could conceal real change.

Open water is kept separate using `MNDWI > 0` with `NDVI <= 0.25`, so tidal water is not automatically counted as red/low canopy. Cloud/invalid pixels are kept as Unknown.

## Outputs

The workflow writes:

- `data/pdd22/plots_catalog.json` - exact 22 PDD participating plots
- `data/pdd22/selection_manifest.json` - provenance of selected KMZ layers
- `data/pdd22/fcd_calibration.json` - frozen March-2023 PCA/scaling transform
- `data/pdd22/fcd_metrics.json` / `.csv` - per-plot March 2023-2026 FCD areas
- `data/pdd22/portfolio_summary.csv` - all-22 aggregate green/yellow/red/water/unknown areas
- `data/pdd22/transitions.json` - pixel-class transition areas between consecutive years
- `data/pdd22/reference_vs_pdd_fcd.csv` - March-2023 Sentinel result versus PDD Table 3-1 province totals
- `data/pdd22/maps/<plot>/fcd_YYYY-03.png` - clipped class maps
- `data/pdd22/carbon_screening.json` - PDD nominal carbon scenario kept separate from satellite evidence

## Carbon boundary

The PDD gives total baseline tree carbon (**362,962.81 tCO2e**) and a planning increment (**9.40 tCO2e/rai/year**), but it does not provide High/Medium/Low FCD-specific carbon density in tCO2e/rai. The workflow therefore does **not** invent a direct FCD-to-carbon conversion.

The current satellite result answers the first defensible question: **Did green area increase and did red area increase/decrease across the same March observation window for all 22 plots?** A satellite-adjusted tCO2e estimate can be added once class-specific baseline carbon densities are supplied or an explicit experimental weighting model is approved.
