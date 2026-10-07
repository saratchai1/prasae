# Local satellite ingest — 2026-10-04

One exact-month registry observation was accepted for **13-VSD / registry 82 / 2024-06**. Coverage is **5.05%**, above the canonical 5% ingestion threshold, and remains **INSUFFICIENT** for full-plot comparison. The 2,229 pre-existing usable observations and all 4,458 of their RGB/NDVI files are unchanged.

| Measure | Exact result |
| --- | ---: |
| Local files scanned | 29,083 |
| Scientific TIFFs decoded and SHA-256 indexed | 29,081 |
| Non-scientific files | 2 |
| ZIP count / valid / corrupt / duplicate source | 0 / 0 / 0 / 0 |
| Archive members | 0 |
| Resolved registry identities | 210 |
| Source plot-months | 2,520 |
| Total source scenes | 2,644 |
| Complete / partial scenes | 2,642 / 2 |
| Registry-contained scenes, including partials | 2,632 |
| Complete registry-contained scenes | 2,630 |
| PDD-only scenes | 12 |
| Unresolved plot / scope / corrupt raster | 0 / 0 / 0 |
| Registry scenes eligible after integrity, completeness and duplicate gates | 2,618 |
| Same-acquisition non-equivalent source products held | 12 scenes in 6 acquisitions |
| PDD duplicates dropped | 0 |
| All-zero source scenes / bands, retained and flagged | 79 / 869 |
| Missing registry slots before | 291 |
| Missing slots with eligible exact-month source | 290 |
| Newly accepted | 1 |
| NO_CLEAR_SCENE / LOW_COVERAGE / PDD_ONLY_FOOTPRINT | 277 / 12 / 1 |
| Registry slots still missing | 290 |
| Observations before / after | 2,229 / 2,230 |
| RGB added / NDVI added | 1 / 1 |
| Expected registry RGB + NDVI files after | 4,460 |

No ZIP exists under the local source root, so the original archive CRC cannot be rechecked here. Every available extracted TIFF was fully decoded; all 29,081 are readable. No raw satellite source was downloaded from Drive or committed.

The previous five partial scenes (53-STC, 54-STC, 55-STC, 19-VSD and 4-VSD, all 2023-09) are now complete for their original exact scenes. The two currently partial sources are **21-STC / 2024-06** (B11 missing) and **97-VSD / 2024-09** (B02 and B08 missing). No missing band was synthesized.

All previous 53 unresolved missing candidates were re-evaluated: **51 NO_CLEAR_SCENE + 2 LOW_COVERAGE** remain. The accepted observation is an additional gap outside that previous 53-candidate set. Registry 86 / 2025-09 has only a PDD footprint and remains missing in registry scope.

Radiometry used **295** matching reference observations across S2A/S2B/S2C. DN/10000 was closer for **295/295**; MAE was **0.0016776271186440676**, versus **0.26101694915254237** with subtraction of 1000. The source formula and the canonical v4 SCL/multi-index/calibration rules were retained.

QA totals remain **CLEAR=1759, ATMOSPHERE_REVIEW=29, TIDE_WATER_REVIEW=4, VISUAL_REVIEW=16, INSUFFICIENT=712**. Low coverage imagery is available for inspection; it does not become a comparable full-plot measurement.

Local validation passed: source audit, unified catalog audit, committed provenance/manifest audit, **10 ingestion regression tests**, **30 Node tests**, syntax checks, exact QA regeneration and **9 browser UAT checks**. A second audit reused SQLite and preserved all 2,230 observations, accepting zero additional observations. Details are in `test_results.json`.

The compact scientific scene manifest is **7,842,241 bytes**; the two new PNGs total **21,773 bytes**. Full raster statistics and absolute source paths stay in ignored `.local/satellite-source-index.sqlite`. Normal CI checks committed evidence/assets and behavior. The five legacy Drive workflows remain manual audit tools; manual ingestion exports a review patch and cannot push production.

Remaining data limitations are 277 cloud/no-clear slots, 12 slots below 5% composite coverage, one PDD-only registry gap, and two incomplete source scenes. The 12 conflicting source versions are retained for review; they do not block an additional missing slot in this run. No owner decision is required to complete the current ingest. Opening a PR does not merge production.
