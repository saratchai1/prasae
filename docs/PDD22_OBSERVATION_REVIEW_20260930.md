# PDD22 observation integrity and review landing page

## Delivery boundary

- Repository: `saratchai1/prasae`.
- Base: production `gh-pages@9da8818654dceeb628ecbbb9d7daf0ee01297a0f`.
- Proposed branch: `feat/pdd22-observation-review-20260930`.
- Draft PR targets `gh-pages`; no merge, deployment, workflow dispatch, data regeneration, storage mutation or scientific-method change is authorized by this delivery.
- Phase 1 covers the landing page, plot detail viewer, QA-gated chart, GIS status styling, Before/After, and filtered CSV.
- `app.js`, scientific pipelines, geometries, PNG assets and all `data/**` blobs are unchanged. The existing Spectral Studio remains available and unchanged; its internal renderer is **not** covered by the new atomic-frame guarantee. Do not claim that every legacy tab has been audited.

## Invariants

1. Observation selection is exact-month. NO_DATA and missing FCD months have no replacement image URL. No nearest-date fallback, synthetic observations or interpolation.
2. One shared display policy (`pdd22-observations.js`) controls numeric validity, effective QA, NDVI chart inclusion, FCD whole-plot eligibility, comparison and matched-set summaries.
3. A non-null number is not evidence that QA passed. For example, the existing coverage report contains 18-VSD / 2025-09 with mean NDVI 0.5345, coverage 0.81%, QA NO_DATA. That number must not become a whole-plot chart point or trend.
4. A GOOD declaration requires valid coverage >=95% (and <=100%). Missing/invalid QA is conservative. Partial FCD may be shown as **observed-only area**; it is never expanded into whole-plot area by this UI.
5. During replacement loading, the previous labelled frame and its own metadata may remain visible. A pending-state message names the requested observation. After decode, image and metadata commit together. A failed/missing replacement removes the old image; no stale image remains under a new date.
6. Last request wins across rapid month, plot and layer changes. Before/After commits both sides together; either side failing clears both.
7. Esri is explicitly labelled as a basemap unrelated to the selected month. It is not presented as the Sentinel acquisition of that month.
8. The FCD KPI shows the displayed observation, not a silent last-GOOD substitution. The latest GOOD month is separately disclosed as contextual metadata only.
9. Review summaries use a common set of plots with GOOD FCD at both endpoints, chronological order and the same calendar month. Same-month QA is only a screening guardrail: tides, pixel-level co-registration, uncertainty and field truth are not newly validated.
10. Negative green-class delta means “open for review”, not confirmed forest damage, a health score, carbon credit or a statistically significant change. Missing quality is a separate status.
11. CSV and the FCD table respect the province/search plot scope and include exact periods, both QA/coverage values, status, reason and method. Null values remain blank. The landing page's status filter is explicitly local to its review list.
12. The comparison script is loaded exactly once in HTML. The chart adapter no longer injects a second script or wraps plot selection.

## Interface changes

The initial tab is now “ภาพรวม / เลือกแปลงตรวจ”. A default pair is selected from actual FCD dates by maximum matched plot count, then newest end date and oldest matching start date; no observation is synthesized. Both selected months are visible and editable.

Cards show the filtered plot population, review signals, insufficient-data count and the explicitly dated latest FCD GOOD count. The common-set context gives matched count, participating area and delta, or an unavailable value rather than a false zero. Review rows open their exact Before/After pair.

Plot-specific KPIs sit inside the detail tab, not above the portfolio landing page. GIS colors represent review/data status, and selection changes border width instead of overwriting status colors. Mobile plot selection is a collapsible picker. The swipe divider supports pointer and keyboard control without capturing the entire page's vertical touch scroll.

## Verification performed

Environment: Node 22.16.0 and headless Chromium via Python Playwright.

- Syntax checks: all four changed/new JavaScript files PASS.
- `node --test tests/pdd22-observations.test.cjs`: **22/22 PASS**.
- `python tests/pdd22-dom.test.py`: **11 grouped checks PASS** at 1440x1000 and 390x844.

The Chromium tests are isolated integration tests with explicitly mocked Leaflet, Chart, image transport and test data. They execute the new production adapter, frame controller, chart adapter and comparison module against the real revised HTML. They are **not** live-site end-to-end tests, real Leaflet/CDN validation, full visual UAT or scientific validation. The local environment could not resolve GitHub/public asset hosts; repository access used the connected GitHub tool instead. No claim is made that all 22 plots or 264 real observations have been runtime-verified in this delivery.

## Required real-data UAT before promotion

From a full checkout of the PR branch (including its unchanged data assets):

```bash
node --test tests/pdd22-observations.test.cjs
python -m http.server 8000
```

Use the site on localhost:8000 in a browser with access to the existing CDN dependencies and basemap. Record actual tested commit SHA, browser, viewport and results.

1. Verify 22 participating plots, source total 6,775.53 rai. Default March 2024→March 2026 pair should be matched on 22 plots. The August 2026 GOOD summary in the existing source is 10 plots / 2,449.4 rai; verify per-plot calculations instead of using a hardcoded UI count.
2. 18-VSD / September 2025: no NDVI chart point despite the non-null source value; no Sentinel frame used as evidence. June 2024 NO_DATA behaves similarly.
3. Change months rapidly while throttled. Only the latest request may commit; retained frames must keep their original month labels. Change plot during load and inspect code, boundary, date and metric together.
4. Force an image HTTP failure in DevTools. Detail must clear stale imagery and show retry; Before/After must clear both frames if one fails. Retry the exact selected observation; do not switch dates as recovery.
5. Select FCD in a month without FCD. It must show unavailable, not silently jump to March. Both compare selectors retain their selected invalid month and explain availability rather than substituting another one.
6. Switch to Esri during a pending satellite load. The stale completion must not re-add Sentinel; the map must say that the basemap is not tied to the selected month.
7. Verify March and August last-GOOD cases. A March value must never be labelled August. The selected-period KPI and separately labelled latest-GOOD metadata must not be conflated.
8. Select a cross-season or reversed pair: images may remain inspectable, but no trend delta is reported. Change the QA set and verify both aggregate sides use precisely the same plot IDs.
9. Select several map polygons and return to overview: QA/review colors remain intact. Grey means insufficient data, not healthy forest.
10. Filter province/code, export CSV and verify the exact row scope, month columns, QA, nulls and UTF-8 Thai text. Test no matching plots.
11. Inspect desktop and actual iOS/Android: mobile picker, table horizontal scrolling, keyboard focus, divider drag/range, ability to scroll past the map, boundary toggles, and existing Spectral Studio navigation. Independently audit Spectral Studio's legacy render failures before extending the atomic guarantee to that tab.

## Stop conditions

Do not merge or deploy on any image/date/plot mismatch, stale frame after failed load, scientific data diff, invented observation, QA-to-success misclassification or mismatched comparison population. Do not regenerate imagery, process new satellite scenes, alter calibration thresholds, dispatch storage workflows or overwrite production in an attempt to make this UI test pass.
