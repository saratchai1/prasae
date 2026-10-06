# Local Sentinel ingestion into the unified registry

`tools/ingest_local_satellite.py` audits local scientific crops and fills only missing registry observations. Registry scope remains the canonical set of 210 identities; the 22 PDD participating footprints remain optional scopes of matching identities.

The tool reads existing extracted TIFFs directly. It validates every ZIP that is present with `ZipFile.testzip()` and decodes every scientific TIFF block. Equivalent archive/extracted scene representations require matching registry identity, exact month, acquisition, all eleven band checksums, scope and raster grids. Extracted copies take precedence. Same-acquisition products with different fingerprints are held for review. Equal hashes in different plots or months are never used to fabricate or deduplicate observations.

## Run locally

Install `requirements-verified.txt` in a private virtual environment. Paths and the reusable source index are private and ignored by Git.

```sh
python tools/ingest_local_satellite.py --source-dir /path/to/inputs
```

This builds `.local/satellite-source-index.sqlite` and reports the current source inventory, every scene, missing candidate and processing result. It does not write application observations without `--apply`. The SQLite index stores absolute paths, archive members, SHA-256, file size/mtime, resolved identity, month/acquisition, spacecraft/tile/band, CRS, raster bounds/transform, dimensions/dtype/nodata, scope, decoding integrity and raster statistics.

After reviewing the audit, reuse the index without another recursive scan:

```sh
python tools/ingest_local_satellite.py --source-dir /path/to/inputs --reuse-index --apply
```

Rebuild without `--reuse-index` when source files are added, removed or modified. The importer also checks mtime and SHA-256 again for each selected input immediately before processing. Use a separate `--report-dir` for subsequent checks to preserve the historical before/after report of a completed ingest.

Optional prior **audit metadata** can be supplied to reproduce the partial-scene and previous-missing-candidate reconciliation:

```sh
python tools/ingest_local_satellite.py --source-dir /path/to/inputs --reuse-index \
  --previous-inventory /path/to/drive_batch_entries.csv \
  --previous-ingest /path/to/drive_missing_ingest.json \
  --report-dir .local/recheck
```

The 2026-10-04 recheck used the inventory artifact from workflow run `37135152658` (artifact `11278502009`) and the previous six-observation ingest report from run `37132197482` (artifact `11276514267`). Their checksums and original members are committed in `previous_batch_recheck.json`. These are metadata artifacts, not raw satellite downloads.

## Processing and acceptance

Every selected scene must be an exact acquisition month, readable, complete in B02/B03/B04/B05/B06/B07/B08/B8A/B11/B12/SCL, and registry-contained in **every band footprint**. The geometric containment gate is at least 99.9% registry overlap, matching the prior scope rule. CRS or footprint conflicts are held. Different dimensions are recorded; aligned footprints can use the canonical resampling reader. PDD-only and partial footprints never fill registry slots.

The canonical `process_verified_12_dates_v4.py` provides all metrics, grid, exact Polygon/MultiPolygon clipping with holes, SCL classes 4/5/6/7, contamination classes 1/2/3/8/9/10/11 and the existing one-pixel contamination buffer. It keeps the promoted 0.155 threshold for registry 76 and 0.25 elsewhere. No nearest-month, synthesized pixels or substituted assets are introduced.

The 2026-10-04 legacy source batch uses `reflectance = DN / 10000`, without subtracting 1000. Its local reader requires DN encoding metadata and rechecks this empirically against matching committed acquisition sets, including a comparison to the alternative offset. A failed encoding or reference gate stops ingestion. Those TIFFs do not carry independent Sentinel product offset metadata; the report states this limit explicitly.

Scenes below 1% clear inside the plot do not contribute to composites. The canonical composite acceptance gate remains 5% valid registry pixels. **Acceptance is not portfolio comparability**: the separate existing full-plot QA gate requires at least 95% coverage plus secondary screening. A low-coverage observation may provide actual RGB/NDVI imagery while its chart/portfolio metrics remain excluded.

Assets are staged privately. The importer re-reads the exact slot and checks concurrent changes before publishing; usable observations and existing imagery are never overwritten. Each accepted observation stores its exact month, scene/time, registry identity/scope, processing version, ingest timestamp and per-band relative identifiers/SHA-256. Public reports omit machine paths. The compact scene manifest stores shared raster grids once, while full per-file statistics stay in SQLite.

## CI and review

`.github/workflows/local-satellite-manifest-check.yml` verifies committed manifests, observation/metadata consistency, source signatures, preservation of existing observations/imagery, derived image hashes and polygon clipping, plus isolated integrity/write-safety regression fixtures. It never downloads raw satellite sources. The existing portfolio browser workflow verifies the unified workspace, scope/FCD controls, filtering, charts, GIS/table, Before/After, real RGB/NDVI loading and missing-month behavior.

The five historical Drive inventory, TIFF QA, reconciliation, radiometry and ingestion workflows are retained as **manual `workflow_dispatch` audit tools**. They do not run on normal pushes. Manual legacy ingestion has read-only repository permission and exports a binary data patch for review instead of pushing `gh-pages`. Review such a patch against the current local-ingest provenance/scope policy before integration. The scripts and their diagnostic artifacts remain available.

Only application metadata/PNG assets and audit evidence are committed. `.local/`, `incoming/`, and the temporary duplicate QA output are ignored. The archived raw source is never needed by normal CI.

## Native Earth Search C1 delivery, 2026-10-05

`tools/ingest_antigravity_satellite.py` reads a separate local delivery with `prepared/inputs`, saved `source-items/earth-search` STAC items, `metadata/<product>/radiometry.json`, and its reviewed export script. It reuses the private prepared-source SQLite index. Actual decoded files are authoritative: the supplied download/request manifests and append-only checksum list are incomplete.

```sh
python tools/ingest_antigravity_satellite.py --source-dir /path/to/inputs-next
python tools/ingest_antigravity_satellite.py --source-dir /path/to/inputs-next --reuse-index \
  --apply --report-dir audit-artifacts/local-satellite-ingest-YYYYMMDD
```

This exporter writes native DN and omits zero nodata and radiometry from TIFF headers. The adapter requires the exact product, provider, band identity, dtype, independent STAC/sidecar agreement and reviewed exporter hash. It masks STAC nodata before resampling and applies **each band's** `DN * scale + offset` once. SCL remains categorical. All 1,060 spectral asset metadata records in this delivery specify scale `0.0001` and offset `-0.1`; this is an explicit new-batch rule, not a reinterpretation of legacy observations. [Earth Search documents applying nonzero offset after scale](https://github.com/Element84/earth-search#gainoffset-in-items-after-jan-25-2022); [Copernicus describes native L2A encoding](https://sentiwiki.copernicus.eu/web/s2-products).

Metadata-valid native reflectance does **not** establish comparability with the legacy DN/10000 batch or its existing calibration. Newly filled full-coverage observations remain `RADIOMETRY_REVIEW` until cross-batch harmonization is verified. Their real RGB/NDVI imagery is available, while charts and portfolio deltas exclude them. New low-coverage observations remain `INSUFFICIENT`. Registry radiometry review does not propagate to an unrelated PDD analysis. No old observation, imagery, QA record or calibration is altered.

QA refresh publishes only newly accepted keys. The canonical QA builder also keeps water references within the same radiometric family, so adding native observations cannot change legacy water medians. CI recomputes QA deterministically and verifies all original records and assets across sequential ingest batches. Reports from earlier ingests remain historical evidence; the latest batch alone supplies current totals.

The 2026-10-05 delivery has 2,859 prepared TIFFs, 212 complete and 64 partial scenes, plus three readable repair TIFFs whose targets already have usable observations. It filled **32** missing slots across 29 plots, adding 64 images and preserving all 2,230 prior usable observations. The dataset now has **2,262 observed and 258 missing** registry slots. Ten new full-coverage slots retain radiometry review; 22 new slots remain coverage-insufficient. Detailed evidence is in `audit-artifacts/local-satellite-ingest-20261005/`.

## Completed second delivery audit, 2026-10-06

Run a new delivery with a separate index and report directory. The second reviewed exporter differs only in the `DELIVERY_ROOT` literal; the native encoder, grid and nodata handling are unchanged. The importer recognizes both exact reviewed script fingerprints and still rejects unknown encoders.

```sh
python tools/ingest_antigravity_satellite.py --source-dir /path/to/inputs-next-2 \
  --index .local/next2-source-index-20261006.sqlite \
  --report-dir .local/next2-dry-audit
python tools/ingest_antigravity_satellite.py --source-dir /path/to/inputs-next-2 \
  --index .local/next2-source-index-20261006.sqlite --reuse-index --apply \
  --report-dir audit-artifacts/local-satellite-ingest-20261006
```

This delivery contains 6,685 files, including 6,207 prepared TIFFs and one held repair. Its 615 source scene representations include 474 complete and 141 partial scenes across 154 plots and 351 plot-months. **All 351 slots already have usable observations; none supplies a missing slot.** Applying and repeating the ingestion both accept zero observations. All 5,001 application data files, including all 2,262 usable observations, 4,524 RGB/NDVI images and 2,520 QA records, remain unchanged.

The 761-entry request log contains historical claims. All 258 remaining slots have search timestamps dated 2026-10-04: 223 report no qualifying clear scene, while 35 refer to files in the previous delivery. Reprocessing those previous exact-month candidates reproduces 17 LOW_COVERAGE, eight NO_CLEAR_SCENE and ten NO_COMPLETE_SOURCE results. A completed downloader run therefore does not establish that the dataset's missing slots have usable scientific files.

The actual inventory remains authoritative. All 6,207 prepared TIFFs match listed checksums; the unlisted repair is independently decoded and hashed. The checksum file also contains 2,675 stale paths, and the download manifest omits 3,374 actual prepared files. Independent mapping, footprint, radiometry, duplicate and unchanged-source checks agree with the importer. The portable latest report and `remaining_candidates.json` in `audit-artifacts/local-satellite-ingest-20261006/` distinguish current physical sources from historical search claims. The three-batch CI audit verifies the full preservation chain without downloading raw satellite files.
