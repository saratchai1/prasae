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

The source batch uses `reflectance = DN / 10000`, without subtracting 1000. The local reader requires DN encoding metadata and rechecks this empirically against matching committed acquisition sets, including a comparison to the alternative offset. A failed encoding or reference gate stops ingestion. The TIFFs themselves do not carry independent Sentinel product offset metadata; the report states this limit explicitly.

Scenes below 1% clear inside the plot do not contribute to composites. The canonical composite acceptance gate remains 5% valid registry pixels. **Acceptance is not portfolio comparability**: the separate existing full-plot QA gate requires at least 95% coverage plus secondary screening. A low-coverage observation may provide actual RGB/NDVI imagery while its chart/portfolio metrics remain excluded.

Assets are staged privately. The importer re-reads the exact slot and checks concurrent changes before publishing; usable observations and existing imagery are never overwritten. Each accepted observation stores its exact month, scene/time, registry identity/scope, processing version, ingest timestamp and per-band relative identifiers/SHA-256. Public reports omit machine paths. The compact scene manifest stores shared raster grids once, while full per-file statistics stay in SQLite.

## CI and review

`.github/workflows/local-satellite-manifest-check.yml` verifies committed manifests, observation/metadata consistency, source signatures, preservation of existing observations/imagery, derived image hashes and polygon clipping, plus isolated integrity/write-safety regression fixtures. It never downloads raw satellite sources. The existing portfolio browser workflow verifies the unified workspace, scope/FCD controls, filtering, charts, GIS/table, Before/After, real RGB/NDVI loading and missing-month behavior.

The five historical Drive inventory, TIFF QA, reconciliation, radiometry and ingestion workflows are retained as **manual `workflow_dispatch` audit tools**. They do not run on normal pushes. Manual legacy ingestion has read-only repository permission and exports a binary data patch for review instead of pushing `gh-pages`. Review such a patch against the current local-ingest provenance/scope policy before integration. The scripts and their diagnostic artifacts remain available.

Only application metadata/PNG assets and audit evidence are committed. `.local/`, `incoming/`, and the temporary duplicate QA output are ignored. The archived raw source is never needed by normal CI.
