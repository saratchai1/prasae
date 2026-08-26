# PDD22 FCD V3 — cleaned Sentinel-2 scene screening

Uses the exact selected scenes from `data/pdd22_satellite` on the 22 PDD participating polygons.
Equivalent Green/Yellow/Red rai are emitted only when plot-month QA is GOOD (>=95% valid coverage).

## Portfolio good-coverage summary

| Month | GOOD plots | Matched area (rai) | Matched area % | Green | Yellow | Red |
|---|---:|---:|---:|---:|---:|---:|
| 2024-03 | 22 | 6775.53 | 100.00% | 4541.83 | 1810.89 | 395.11 |
| 2025-03 | 22 | 6775.53 | 100.00% | 4305.73 | 2162.91 | 279.19 |
| 2026-03 | 22 | 6775.53 | 100.00% | 4253.54 | 2124.20 | 370.09 |
| 2026-08 | 10 | 2449.40 | 36.15% | 1996.22 | 344.35 | 95.84 |

## Guardrail

Do not convert these class areas directly into tCO2e. Field verification remains required for suspected decline hotspots.