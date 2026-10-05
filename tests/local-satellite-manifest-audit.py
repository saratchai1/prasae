#!/usr/bin/env python3
"""Verify sequential committed ingest evidence and app assets, without raw sources."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
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
MONTHS = ['2023-09', '2023-12', '2024-03', '2024-06', '2024-09', '2024-12', '2025-03', '2025-06', '2025-09', '2025-12', '2026-03', '2026-08']
BANDS = {'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12', 'SCL'}
EARTH_SEARCH_ASSETS = {'B02': 'blue', 'B03': 'green', 'B04': 'red', 'B05': 'rededge1',
                       'B06': 'rededge2', 'B07': 'rededge3', 'B08': 'nir', 'B8A': 'nir08',
                       'B11': 'swir16', 'B12': 'swir22', 'SCL': 'scl'}
REPORT_FILES = ('final_summary', 'source_inventory', 'scene_manifest', 'ingest_result',
                'existing_observation_fingerprints', 'radiometric_validation')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(identifier):
    assert isinstance(identifier, str) and identifier, identifier
    assert not identifier.startswith(('/', '\\')) and '..' not in identifier.replace('!', '/').split('/'), identifier
    assert not re.match(r'^[A-Za-z]:', identifier), identifier


def valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value)


def asset_source_id(scene, asset):
    return asset.get('source_id', scene['source_group'] + '/' + asset['filename'])


def slot_key(record):
    return int(record['plot_id']), record['month']


def baseline_keys(batch):
    return {(int(pid), month) for pid, month in
            (key.split('|') for key in batch['existing_observation_fingerprints']['observations'])}


def discover_batches(root):
    reports = sorted((root / 'audit-artifacts').glob('local-satellite-ingest*/final_summary.json'))
    assert reports, 'no committed local-satellite ingest evidence'
    batches = []
    for summary_path in reports:
        report = summary_path.parent
        batch = {'path': report}
        for name in REPORT_FILES:
            path = report / f'{name}.json'
            assert path.is_file(), f'incomplete report: {path}'
            batch[name] = read(path)
        qa_baseline_path = report / 'existing_qa_fingerprints.json'
        if qa_baseline_path.is_file():
            batch['existing_qa_fingerprints'] = read(qa_baseline_path)
        batches.append(batch)
    # A batch snapshots all usable observations before it runs. Count and then
    # directory date place historic reports before later missing-slot fills.
    return sorted(batches, key=lambda b: (b['final_summary']['observed_before'], b['path'].name))


def validate_batch_chain(batches, slots):
    """No previously usable slot may be accepted again, including across batches."""
    accepted = {}
    preserved = baseline_keys(batches[0])
    for index, batch in enumerate(batches):
        summary = batch['final_summary']
        baseline = batch['existing_observation_fingerprints']
        results = batch['ingest_result']
        before = baseline_keys(batch)
        assert before == preserved, f"non-continuous preservation baseline: {batch['path']}"
        assert len(before) == len(baseline['observations']) == baseline['count'] == summary['observed_before']
        assert before <= slots.keys()
        records = results['records']
        record_keys = {slot_key(record) for record in records}
        assert len(record_keys) == len(records) == summary['missing_candidates_before']
        assert record_keys == slots.keys() - before, 'batch must account for every missing exact-month slot'
        counts = dict(sorted(Counter(record['result'] for record in records).items()))
        assert counts == results['counts'] == summary['result_counts']
        new = [record for record in records if record['result'] == 'ACCEPTED']
        assert len(new) == results['accepted'] == summary['newly_accepted']
        assert summary['observed_after'] - summary['observed_before'] == len(new)
        assert summary['still_missing'] == len(slots) - summary['observed_after']
        for record in new:
            key = slot_key(record)
            assert key not in preserved and key not in accepted, 'existing usable observation overwritten'
            accepted[key] = (index, batch, record)
        preserved |= {slot_key(record) for record in new}
        assert len(preserved) == summary['observed_after']
    observed = {key for key, observation in slots.items() if observation['status'].startswith('observed_')}
    assert observed == preserved, 'current app observations lack an accepted or preserved source'
    assert len(observed) == batches[-1]['final_summary']['observed_after']
    for index, batch in enumerate(batches):
        for record in batch['ingest_result']['records']:
            key = slot_key(record)
            if record['result'] != 'ACCEPTED' and key in observed:
                assert key in accepted and accepted[key][0] > index, 'historical unresolved slot has no later accepted proof'
                later = accepted[key][1]
                assert slots[key]['source_provenance']['source_manifest_sha256'] == later['source_inventory']['source_manifest_sha256']
    return accepted


def validate_metadata_radiometry(band, radiometry, source_checksums):
    assert isinstance(radiometry, dict), f'{band}: missing per-asset radiometry'
    assert isinstance(radiometry['scale'], (int, float)) and math.isfinite(radiometry['scale']) and radiometry['scale'] > 0
    assert isinstance(radiometry['offset'], (int, float)) and math.isfinite(radiometry['offset'])
    assert 'nodata' in radiometry
    assert radiometry['nodata'] is None or (isinstance(radiometry['nodata'], (int, float)) and math.isfinite(radiometry['nodata']))
    if band == 'SCL':
        assert radiometry['scale'] == 1 and radiometry['offset'] == 0, 'categorical SCL must not be reflectance-scaled'
        assert radiometry['formula'] == 'SCL categorical'
    else:
        assert radiometry['formula'] == 'DN * scale + offset'
    metadata_id = radiometry['metadata_source_id']
    relative(metadata_id)
    assert valid_sha(radiometry['metadata_sha256'])
    assert source_checksums.get(metadata_id) == radiometry['metadata_sha256'], 'radiometry metadata is not in hashed source inventory'
    sidecar_id = radiometry['radiometry_sidecar_source_id']
    relative(sidecar_id)
    assert valid_sha(radiometry['radiometry_sidecar_sha256'])
    assert source_checksums.get(sidecar_id) == radiometry['radiometry_sidecar_sha256'], 'radiometry sidecar is not in hashed source inventory'
    assert isinstance(radiometry['asset_key'], str) and radiometry['asset_key']


def validate_metadata_profiles(radiometry, scenes, source_checksums):
    """Bind every full or partial scene to its exact provider-product profile."""
    assert radiometry['status'] == radiometry['metadata_gate'] == 'PASS'
    assert radiometry['formula'] == 'DN * scale + offset'
    assert radiometry['validated_scene_count'] == len(scenes)
    products = {scene['scene_id'] for scene in scenes}
    profiles = {profile['scene_id']: profile for profile in radiometry['profiles']}
    assert len(profiles) == len(radiometry['profiles']), 'duplicate or conflicting product profile'
    assert profiles.keys() == products, 'product profiles do not cover every scene'
    assert radiometry['validated_product_count'] == len(products)
    export_script = radiometry['export_script_source_id']
    relative(export_script)
    assert valid_sha(radiometry['export_script_sha256'])
    assert source_checksums.get(export_script) == radiometry['export_script_sha256'], 'export script is not in hashed source inventory'
    metadata_keys = ('metadata_source_id', 'metadata_sha256',
                     'radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')
    for scene in scenes:
        profile = profiles[scene['scene_id']]
        assert profile['collection'] == 'sentinel-2-c1-l2a'
        assert profile['product_uri'] == scene['scene_id'] + '.SAFE', 'profile refers to a different processing product'
        assert profile['metadata_source_id'].endswith('/' + scene['scene_id'] + '.json')
        assert profile['radiometry_sidecar_source_id'].endswith('/' + scene['scene_id'] + '/radiometry.json')
        assert datetime.fromisoformat(profile['sensing_datetime']).strftime('%Y-%m') == scene['month']
        assert profile['platform'] == {'S2A': 'sentinel-2a', 'S2B': 'sentinel-2b', 'S2C': 'sentinel-2c'}[scene['satellite']]
        assert f"_N{profile['processing_baseline'].replace('.', '')}_" in scene['scene_id']
        stac_identity = re.fullmatch(r'(S2[ABC])_(T\d{2}[A-Z]{3})_(\d{8}T\d{6})_L2A', profile['stac_item_id'])
        assert stac_identity
        assert stac_identity[1] == scene['satellite'] and stac_identity[2] == scene['tile']
        assert stac_identity[3][:8] == datetime.fromisoformat(scene['acquisition_datetime']).strftime('%Y%m%d')
        assert profile['assets'].keys() == BANDS
        for band, proof in profile['assets'].items():
            validate_metadata_radiometry(band, proof, source_checksums)
            assert proof['asset_key'] == EARTH_SEARCH_ASSETS[band], 'wrong provider asset mapped to scientific band'
            assert all(proof[key] == profile[key] for key in metadata_keys), 'profile asset metadata identity mismatch'
        for band, asset in scene['assets'].items():
            assert asset['radiometry'] == profile['assets'][band], 'scene/profile radiometry conflict'
            assert scene['raster_grids'][asset['grid']]['dtype'] == asset['radiometry']['native_dtype']


def validate_qa_preservation(batches, qa, slots):
    """Preserve unrelated QA, and block native/legacy trend comparisons."""
    observations = qa['observations']
    expected_keys = {f'{pid}|{month}' for pid, month in slots}
    assert observations.keys() == expected_keys
    assert dict(sorted(Counter(record['status'] for record in observations.values()).items())) == qa['summary']
    preserved_count = None
    for index, batch in enumerate(batches):
        native = 'metadata_gate' in batch['radiometric_validation']
        baseline = batch.get('existing_qa_fingerprints')
        assert not native or baseline is not None, 'native batch lacks QA preservation evidence'
        if baseline is None:
            continue
        assert re.fullmatch(r'[a-f0-9]{40}', baseline['base_sha'])
        assert len(baseline['observations']) == baseline['count'] == len(slots)
        assert baseline['observations'].keys() == expected_keys
        assert all(valid_sha(value) for value in baseline['observations'].values())
        accepted = [record for record in batch['ingest_result']['records'] if record['result'] == 'ACCEPTED']
        allowed = {f"{record['plot_id']}|{record['month']}" for record in accepted}
        assert len(baseline['allowed_changed_keys']) == len(set(baseline['allowed_changed_keys']))
        assert set(baseline['allowed_changed_keys']) == allowed, 'QA permission must equal this batch accepted slots'
        later_allowed = {f"{record['plot_id']}|{record['month']}" for later in batches[index + 1:]
                         for record in later['ingest_result']['records'] if record['result'] == 'ACCEPTED'}
        unchanged = expected_keys - allowed - later_allowed
        for key in unchanged:
            assert sha(observations[key]) == baseline['observations'][key], f'unrelated QA record changed: {key}'
        preserved_count = len(unchanged)
        if native:
            for record in accepted:
                key = f"{record['plot_id']}|{record['month']}"
                observation = slots[slot_key(record)]
                current_qa = observations[key]
                assert current_qa['radiometry_status'] == 'NATIVE_C1_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING'
                assert abs(current_qa['coverage_pct'] - observation['clear_pixel_pct']) <= .01
                if observation['clear_pixel_pct'] < 95:
                    assert current_qa['status'] == 'INSUFFICIENT', 'low coverage must remain insufficient'
                else:
                    visual_status = current_qa.get('visual_screening_status')
                    if visual_status in {'ATMOSPHERE_REVIEW', 'VISUAL_REVIEW', 'TIDE_WATER_REVIEW'}:
                        assert current_qa['status'] == visual_status, 'retain any other visual review gate'
                    else:
                        assert current_qa['status'] == 'RADIOMETRY_REVIEW', 'native/legacy comparison requires radiometry review'
    return preserved_count


def audit_batch(batch, root, byid, slots):
    report = batch['path']
    summary = batch['final_summary']
    inventory = batch['source_inventory']
    scenes = batch['scene_manifest']
    baseline = batch['existing_observation_fingerprints']
    radiometry = batch['radiometric_validation']
    assert len(scenes) == summary['complete_scenes'] + summary['partial_scenes']
    assert sum(scene['complete'] for scene in scenes) == summary['complete_scenes']
    assert dict(sorted(Counter(scene['scope'] for scene in scenes).items())) == summary['scope_counts']
    assert radiometry['status'] == 'PASS'
    metadata_backed = 'metadata_gate' in radiometry
    if metadata_backed:
        assert radiometry['metadata_gate'] == 'PASS'
        assert isinstance(radiometry['validated_scene_count'], int) and radiometry['validated_scene_count'] == len(scenes)
    else:
        # Historic DN encoding was validated on matching acquisitions.
        assert radiometry['samples'] >= 20
        assert radiometry['tested_spacecraft'] == radiometry['source_spacecraft']
        assert radiometry['mae_no_offset'] < radiometry['mae_minus1000']
        assert radiometry['better_no_offset'] == radiometry['samples']
    source_rows = []
    lookup = {}
    for scene in scenes:
        assert scene['plot_id'] in byid and scene['month'] in MONTHS
        relative(scene['source_group'])
        acquisition = datetime.fromisoformat(scene['acquisition_datetime'])
        assert acquisition.strftime('%Y-%m') == scene['month']
        assert acquisition.strftime('%Y%m%dT%H%M%S') in scene['scene_id'], 'source identity/acquisition mismatch'
        assert set(scene['missing_bands']) == BANDS - scene['assets'].keys()
        assert scene['complete'] == (scene['assets'].keys() == BANDS)
        signatures = {}
        checked_grids = set()
        for band, asset in scene['assets'].items():
            assert band in BANDS and valid_sha(asset['checksum'])
            assert Path(asset['filename']).stem.upper() == band
            grid = scene['raster_grids'][asset['grid']]
            signatures[band] = sha({'checksum': asset['checksum'], **grid})
            source_id = asset_source_id(scene, asset)
            relative(source_id)
            source_rows.append({'source_id': source_id, 'checksum': asset['checksum']})
            assert asset['filesize'] > 0
            if scene['usable_source']:
                assert scene['scope'] == 'REGISTRY_CONTAINED' and scene['complete'] and not scene['errors'] and asset['integrity'] == 'VALID'
                if asset['grid'] not in checked_grids:
                    aa, bb, cc, dd, ee, ff = grid['transform']
                    w, h = grid['width'], grid['height']
                    footprint = Polygon([(aa*x + bb*y + cc, dd*x + ee*y + ff) for x, y in [(0, 0), (w, 0), (w, h), (0, h)]])
                    if grid['crs'] != 'EPSG:4326':
                        footprint = transform_geometry(Transformer.from_crs(grid['crs'], 'EPSG:4326', always_xy=True).transform, footprint)
                    registry = shape(byid[scene['plot_id']]['geometry'])
                    assert registry.intersection(footprint).area / registry.area >= .999
                    checked_grids.add(asset['grid'])
        assert sha(signatures) == scene['fingerprint'], scene['source_group']
        for extra in scene.get('additional_band_sources', []):
            relative(extra['source_id'])
            assert valid_sha(extra['checksum'])
            source_rows.append({'source_id': extra['source_id'], 'checksum': extra['checksum']})
        lookup.setdefault((scene['plot_id'], scene['month'], scene['scene_id']), []).append(scene)
    for source in inventory.get('non_scientific_files', []):
        relative(source['source_id'])
        assert valid_sha(source['checksum'])
        source_rows.append({'source_id': source['source_id'], 'checksum': source['checksum']})
    for source in inventory.get('held_scientific_files', []):
        relative(source['source_id'])
        assert valid_sha(source['checksum']) and source['filesize'] > 0
        assert source['integrity_status'] == 'VALID'
        assert source['action'] == 'EXISTING_REGISTRY_OBSERVATION'
        source_rows.append({'source_id': source['source_id'], 'checksum': source['checksum']})
    assert len(source_rows) == inventory['scientific_tifs'] + len(inventory.get('non_scientific_files', []))
    assert len({source['source_id'] for source in source_rows}) == len(source_rows), 'duplicate inventory identity'
    assert sha(sorted(source_rows, key=lambda source: source['source_id'])) == inventory['source_manifest_sha256'] == summary['source_manifest_sha256']
    source_checksums = {source['source_id']: source['checksum'] for source in source_rows}
    if metadata_backed:
        validate_metadata_profiles(radiometry, scenes, source_checksums)
    # Every historical baseline remains byte-identical in the current app.
    for key, proof in baseline['observations'].items():
        pid, month = key.split('|')
        assert sha(slots[(int(pid), month)]) == proof['observation_sha256'], key
        assert proof['derived_assets'].keys() == {'rgb', 'ndvi'}
        for layer, checksum in proof['derived_assets'].items():
            assert file_sha(root / 'data/plots' / pid / f'{layer}_{month}.png') == checksum, key
    for record in batch['ingest_result']['records']:
        if record['result'] != 'ACCEPTED':
            continue
        observation = slots[slot_key(record)]
        provenance = observation['source_provenance']
        assert provenance == record['source_provenance']
        assert provenance['scope'] == 'REGISTRY' and provenance['scope_classification'] == 'REGISTRY_CONTAINED'
        assert provenance['registry_plot_id'] == record['plot_id'] and provenance['exact_month'] == record['month']
        assert provenance['processing_version'] == 'v4_site_calibrated_green_cover'
        assert provenance['reflectance_formula'] == ('DN * scale + offset' if metadata_backed else 'DN / 10000')
        if metadata_backed:
            assert observation['source'] == 'Earth Search / Sentinel-2 C1 L2A'
        assert provenance['source_manifest_sha256'] == inventory['source_manifest_sha256']
        assert observation['scene_ids'] == [scene['scene_id'] for scene in provenance['scenes']]
        assert provenance['scenes']
        for proof in provenance['scenes']:
            matches = [scene for scene in lookup[(record['plot_id'], record['month'], proof['scene_id'])]
                       if scene['usable_source'] and scene['fingerprint'] == proof['source_fingerprint']]
            assert len(matches) == 1
            scene = matches[0]
            assert proof['acquisition_datetime'] == scene['acquisition_datetime']
            assert proof['assets'].keys() == BANDS
            for band, asset in proof['assets'].items():
                source_asset = scene['assets'][band]
                grid = scene['raster_grids'][source_asset['grid']]
                assert asset['sha256'] == source_asset['checksum']
                assert asset['source_id'] == asset_source_id(scene, source_asset)
                assert asset['filesize'] == source_asset['filesize']
                assert asset['raster_signature'] == sha({'checksum': source_asset['checksum'], **grid})
                relative(asset['source_id'])
                if metadata_backed:
                    assert asset['radiometry'] == source_asset['radiometry']
                    validate_metadata_radiometry(band, asset['radiometry'], source_checksums)
        assert record['derived_assets'].keys() == {'rgb', 'ndvi'}
        for layer, asset in record['derived_assets'].items():
            relative(asset['path'])
            assert asset['path'] == f"data/plots/{record['plot_id']}/{layer}_{record['month']}.png"
            path = root / asset['path']
            assert file_sha(path) == asset['sha256'] and path.stat().st_size <= 5 * 1024 * 1024
            with Image.open(path) as image:
                assert image.format == 'PNG' and image.mode == 'RGBA'
                pixels = np.asarray(image)
            grid = read(root / 'data/plots' / str(record['plot_id']) / 'metadata.json')['grid']
            assert pixels.shape[:2] == (grid['height'], grid['width'])
            inside = geometry_mask([byid[record['plot_id']]['geometry']], out_shape=pixels.shape[:2],
                                   transform=from_bounds(*grid['bbox'], grid['width'], grid['height']), invert=True)
            alpha = pixels[..., 3] > 0
            assert alpha.any() and not alpha[~inside].any(), 'exact polygon clipping, including holes'
            if layer == 'ndvi':
                assert abs(alpha.sum() / inside.sum() * 100 - observation['clear_pixel_pct']) <= .01
    if report.name == 'local-satellite-ingest':
        recheck = read(report / 'previous_batch_recheck.json')
        assert recheck['previous_partial_count'] == 5 and recheck['partial_results'] == {'UPGRADED_COMPLETE': 5}
        assert recheck['previous_missing_count'] == 53 and recheck['missing_results'] == {'NO_CLEAR_SCENE': 51, 'LOW_COVERAGE': 2}
    return len(source_rows)


def main(root=R):
    catalog = read(root / 'data/plots_catalog.json')
    series = read(root / 'data/timeseries_verified_12.json')
    assert len(catalog) == len(series) == 210
    byid = {int(plot['id']): plot for plot in catalog}
    byseries = {int(plot['id']): plot for plot in series}
    assert len(byid) == len(byseries) == 210 and byid.keys() == byseries.keys()
    slots = {(int(plot['id']), observation['month']): observation for plot in series for observation in plot['timeseries']}
    assert len(slots) == 2520
    for plot in series:
        assert [observation['month'] for observation in plot['timeseries']] == MONTHS
        metadata = read(root / 'data/plots' / str(plot['id']) / 'metadata.json')
        assert metadata['dates'] == plot['timeseries'], plot['id']
    batches = discover_batches(root)
    accepted = validate_batch_chain(batches, slots)
    source_count = sum(audit_batch(batch, root, byid, slots) for batch in batches)
    qa = read(root / 'data/all_plots_visual_qa.json')
    preserved_qa = validate_qa_preservation(batches, qa, slots)
    assert qa['summary'] == batches[-1]['final_summary']['qa_summary']
    print(json.dumps({'result': 'PASS', 'registry_identities': 210, 'batches': len(batches),
                      'source_files': source_count, 'preserved_observations': batches[0]['existing_observation_fingerprints']['count'],
                      'accepted': len(accepted), 'observed_after': batches[-1]['final_summary']['observed_after'],
                      'preserved_qa_records': preserved_qa,
                      'no_nearest_month_substitution': 'PASS', 'no_synthetic_imagery': 'PASS',
                      'registry_pdd_scope_boundary': 'PASS', 'expected_derived_files': 'PASS'}, indent=2))


if __name__ == '__main__':
    main()
