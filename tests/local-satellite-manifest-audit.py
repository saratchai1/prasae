#!/usr/bin/env python3
"""Verify committed local ingest evidence and app assets; never fetch raw sources."""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from PIL import Image
import numpy as np
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from shapely.geometry import shape, Polygon
from shapely.ops import transform as transform_geometry
from pyproj import Transformer

R = Path(__file__).resolve().parents[1]
REPORT = R / 'audit-artifacts/local-satellite-ingest'
MONTHS = ['2023-09', '2023-12', '2024-03', '2024-06', '2024-09', '2024-12', '2025-03', '2025-06', '2025-09', '2025-12', '2026-03', '2026-08']
BANDS = {'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12', 'SCL'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(identifier):
    assert not identifier.startswith(('/', '\\')) and '..' not in identifier.replace('!', '/').split('/'), identifier
    assert not re.match(r'^[A-Za-z]:', identifier), identifier


catalog = read(R / 'data/plots_catalog.json')
series = read(R / 'data/timeseries_verified_12.json')
assert len(catalog) == len(series) == 210
byid = {int(p['id']): p for p in catalog}
byseries = {int(p['id']): p for p in series}
assert len(byid) == len(byseries) == 210 and byid.keys() == byseries.keys()
slots = {(int(p['id']), o['month']): o for p in series for o in p['timeseries']}
assert len(slots) == 2520
for p in series:
    assert [o['month'] for o in p['timeseries']] == MONTHS
    md = read(R / 'data/plots' / str(p['id']) / 'metadata.json')
    assert md['dates'] == p['timeseries'], p['id']

summary = read(REPORT / 'final_summary.json')
inventory = read(REPORT / 'source_inventory.json')
scenes = read(REPORT / 'scene_manifest.json')
results = read(REPORT / 'ingest_result.json')
baseline = read(REPORT / 'existing_observation_fingerprints.json')
assert len(scenes) == summary['complete_scenes'] + summary['partial_scenes']
assert sum(s['complete'] for s in scenes) == summary['complete_scenes']
assert dict(sorted(Counter(s['scope'] for s in scenes).items())) == summary['scope_counts']
assert dict(sorted(Counter(r['result'] for r in results['records']).items())) == results['counts'] == summary['result_counts']
assert len(results['records']) == summary['missing_candidates_before']
assert len({(r['plot_id'], r['month']) for r in results['records']}) == len(results['records'])
assert summary['observed_after'] - summary['observed_before'] == summary['newly_accepted']
assert sum(o['status'].startswith('observed_') for o in slots.values()) == summary['observed_after']
assert summary['still_missing'] == 2520 - summary['observed_after']
assert results['accepted'] == summary['newly_accepted']

source_rows = []
lookup = {}
for s in scenes:
    assert s['plot_id'] in byid and s['month'] in MONTHS
    relative(s['source_group'])
    assert datetime.fromisoformat(s['acquisition_datetime']).strftime('%Y-%m') == s['month']
    assert set(s['missing_bands']) == BANDS - s['assets'].keys()
    assert s['complete'] == (s['assets'].keys() == BANDS)
    signatures = {}
    for band, a in s['assets'].items():
        assert band in BANDS and re.fullmatch(r'[a-f0-9]{64}', a['checksum'])
        assert Path(a['filename']).stem.upper() == band
        grid = s['raster_grids'][a['grid']]
        signatures[band] = sha({'checksum': a['checksum'], **grid})
        source_id = s['source_group'] + '/' + a['filename']
        relative(source_id)
        source_rows.append({'source_id': source_id, 'checksum': a['checksum']})
        if s['usable_source']:
            assert s['scope'] == 'REGISTRY_CONTAINED' and s['complete'] and not s['errors'] and a['integrity'] == 'VALID'
            aa, bb, cc, dd, ee, ff = grid['transform']
            w, h = grid['width'], grid['height']
            footprint = Polygon([(aa*x + bb*y + cc, dd*x + ee*y + ff) for x, y in [(0, 0), (w, 0), (w, h), (0, h)]])
            if grid['crs'] != 'EPSG:4326':
                footprint = transform_geometry(Transformer.from_crs(grid['crs'], 'EPSG:4326', always_xy=True).transform, footprint)
            rg = shape(byid[s['plot_id']]['geometry'])
            assert rg.intersection(footprint).area / rg.area >= .999
    assert sha(signatures) == s['fingerprint'], s['source_group']
    for extra in s.get('additional_band_sources', []):
        source_rows.append({'source_id': extra['source_id'], 'checksum': extra['checksum']})
    key = (s['plot_id'], s['month'], s['scene_id'])
    lookup.setdefault(key, []).append(s)
source_rows += [{'source_id': r['source_id'], 'checksum': r['checksum']} for r in inventory['non_scientific_files']]
assert len(source_rows) == inventory['scientific_tifs'] + len(inventory['non_scientific_files'])
assert sha(sorted(source_rows, key=lambda r: r['source_id'])) == inventory['source_manifest_sha256']
assert inventory['source_manifest_sha256'] == summary['source_manifest_sha256']

assert len(baseline['observations']) == baseline['count'] == summary['observed_before']
for key, proof in baseline['observations'].items():
    pid, month = key.split('|')
    assert sha(slots[(int(pid), month)]) == proof['observation_sha256'], key
    for layer, checksum in proof['derived_assets'].items():
        assert file_sha(R / 'data/plots' / pid / f'{layer}_{month}.png') == checksum, key

for rec in results['records']:
    if rec['result'] != 'ACCEPTED':
        assert not slots[(rec['plot_id'], rec['month'])]['status'].startswith('observed_')
        continue
    o = slots[(rec['plot_id'], rec['month'])]
    provenance = o['source_provenance']
    assert provenance == rec['source_provenance']
    assert provenance['scope'] == 'REGISTRY' and provenance['scope_classification'] == 'REGISTRY_CONTAINED'
    assert provenance['registry_plot_id'] == rec['plot_id'] and provenance['exact_month'] == rec['month']
    assert provenance['processing_version'] == 'v4_site_calibrated_green_cover'
    assert provenance['reflectance_formula'] == 'DN / 10000'
    assert provenance['source_manifest_sha256'] == inventory['source_manifest_sha256']
    assert o['scene_ids'] == [s['scene_id'] for s in provenance['scenes']]
    for proof in provenance['scenes']:
        matches = [s for s in lookup[(rec['plot_id'], rec['month'], proof['scene_id'])]
                   if s['usable_source'] and s['fingerprint'] == proof['source_fingerprint']]
        assert len(matches) == 1
        s = matches[0]
        assert s['usable_source'] and proof['source_fingerprint'] == s['fingerprint']
        assert proof['acquisition_datetime'] == s['acquisition_datetime']
        assert proof['assets'].keys() == BANDS
        for band, a in proof['assets'].items():
            assert a['sha256'] == s['assets'][band]['checksum']
            assert a['source_id'] == s['source_group'] + '/' + s['assets'][band]['filename']
            relative(a['source_id'])
    for layer, a in rec['derived_assets'].items():
        relative(a['path'])
        path = R / a['path']
        assert file_sha(path) == a['sha256'] and path.stat().st_size <= 5 * 1024 * 1024
        with Image.open(path) as im:
            assert im.format == 'PNG' and im.mode == 'RGBA'
            pixels = np.asarray(im)
        md = read(R / 'data/plots' / str(rec['plot_id']) / 'metadata.json')
        grid = md['grid']
        assert pixels.shape[:2] == (grid['height'], grid['width'])
        inside = geometry_mask([byid[rec['plot_id']]['geometry']], out_shape=pixels.shape[:2],
                               transform=from_bounds(*grid['bbox'], grid['width'], grid['height']), invert=True)
        alpha = pixels[..., 3] > 0
        assert alpha.any() and not alpha[~inside].any(), 'exact polygon clipping, including holes'
        if layer == 'ndvi':
            assert abs(alpha.sum() / inside.sum() * 100 - o['clear_pixel_pct']) <= .01

radiometry = read(REPORT / 'radiometric_validation.json')
assert radiometry['status'] == 'PASS' and radiometry['samples'] >= 20
assert radiometry['tested_spacecraft'] == radiometry['source_spacecraft']
recheck = read(REPORT / 'previous_batch_recheck.json')
assert recheck['previous_partial_count'] == 5 and recheck['partial_results'] == {'UPGRADED_COMPLETE': 5}
assert recheck['previous_missing_count'] == 53 and recheck['missing_results'] == {'NO_CLEAR_SCENE': 51, 'LOW_COVERAGE': 2}
assert read(R / 'data/all_plots_visual_qa.json')['summary'] == summary['qa_summary']
print(json.dumps({'result': 'PASS', 'registry_identities': 210, 'source_files': len(source_rows),
                  'preserved_observations': baseline['count'], 'accepted': results['accepted'],
                  'no_nearest_month_substitution': 'PASS', 'no_synthetic_imagery': 'PASS',
                  'registry_pdd_scope_boundary': 'PASS', 'expected_derived_files': 'PASS'}, indent=2))
