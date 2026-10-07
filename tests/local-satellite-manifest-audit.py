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
MULTI_PROVIDER_SCHEMA = 'native-multi-provider-v1'
XML_BAND_IDS = dict(zip(('B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12'),
                        (1, 2, 3, 4, 5, 6, 7, 8, 11, 12)))
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


def validate_metadata_profiles(radiometry, scenes, source_checksums, *, root=R):
    """Bind every full or partial scene to its exact provider-product profile."""
    if radiometry.get('provider_schema') == MULTI_PROVIDER_SCHEMA:
        return validate_multi_provider_profiles(radiometry, scenes, source_checksums, root=root)
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


def validate_product_xml_profile(profile, source_checksums):
    """Check the portable critical-node proof from the hashed exact-product XML."""
    source_id = profile['product_metadata_source_id']
    relative(source_id)
    assert source_id == f"provider-metadata/planetary-computer/{profile['scene_id']}.xml"
    checksum = profile['product_metadata_sha256']
    assert valid_sha(checksum) and source_checksums.get(source_id) == checksum, 'product XML is not in hashed source inventory'
    assert profile['product_metadata_filesize'] > 0
    url = profile['product_metadata_url']
    assert '?' not in url and url.startswith('https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/')
    assert '/' + profile['scene_id'] + '.SAFE/MTD_MSIL2A.xml' in url
    proof = profile['product_metadata_proof']
    assert proof['status'] == 'PASS'
    assert proof['product_uri'] == profile['product_uri']
    assert proof['processing_baseline'] == profile['processing_baseline']
    quantification = proof['boa_quantification_value']
    assert isinstance(quantification, (int, float)) and not isinstance(quantification, bool)
    assert math.isfinite(quantification) and quantification > 0
    offsets = proof['boa_offsets_by_band_id']
    assert {str(value) for value in XML_BAND_IDS.values()} <= offsets.keys()
    assert all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in offsets.values())
    assert proof['special_values']['NODATA'] == 0
    assert proof['critical_nodes'] == {'PRODUCT_URI': proof['product_uri'],
                                    'PROCESSING_BASELINE': proof['processing_baseline'],
                                    'BOA_QUANTIFICATION_VALUE': quantification,
                                    'BOA_ADD_OFFSET': offsets,
                                    'Special_Values': proof['special_values']}
    for band, asset in profile['assets'].items():
        assert asset['product_metadata_source_id'] == source_id and asset['product_metadata_sha256'] == checksum
        if band != 'SCL':
            band_id = XML_BAND_IDS[band]
            assert asset['band_id'] == band_id and asset['boa_add_offset'] == offsets[str(band_id)]
            assert asset['scale'] == 1 / quantification and asset['offset'] == offsets[str(band_id)] / quantification
            assert asset['nodata'] == proof['special_values']['NODATA']


def validate_reused_native_scene(scene, profile, prior_scene, prior_profile):
    """A reused canonical crop must exactly match the already validated batch."""
    namespace = 'reused/inputs-next/'
    prior = scene['prior_validated_batch']
    assert prior['id'] == profile['prior_batch_id'] == 'local-satellite-ingest-20261005'
    assert profile['metadata_format'] == 'earth-search-c1-flat-sidecar' and profile['source_namespace'] == namespace
    assert profile['provider'] == scene['provider'] == 'earth-search'
    assert prior['source_group'] == prior_scene['source_group']
    assert scene['source_group'] == namespace + prior_scene['source_group']
    assert prior['fingerprint'] == scene['fingerprint'] == prior_scene['fingerprint']
    assert scene['raster_grids'] == prior_scene['raster_grids'], 'reused raster grid differs from the validated prior crop'
    assert not scene['native_grid_proofs'], 'reused canonical grid must retain its prior validation'
    for key in ('scene_id', 'plot_id', 'month', 'acquisition_datetime', 'satellite', 'tile', 'scope'):
        assert scene[key] == prior_scene[key], 'reused scene identity differs from prior batch'
    assert scene['assets'].keys() == prior_scene['assets'].keys() == BANDS
    for band, asset in scene['assets'].items():
        previous = prior_scene['assets'][band]
        assert asset['source_id'] == namespace + asset_source_id(prior_scene, previous)
        assert all(asset[key] == previous[key] for key in ('filename', 'checksum', 'filesize', 'grid', 'integrity'))
    for key in ('scene_id', 'stac_item_id', 'collection', 'product_uri', 'sensing_datetime', 'processing_baseline', 'platform',
                'metadata_sha256', 'radiometry_sidecar_sha256'):
        assert profile[key] == prior_profile[key], 'reused provider metadata differs from prior validation'
    for key in ('metadata_source_id', 'radiometry_sidecar_source_id'):
        assert profile[key] == namespace + prior_profile[key]
    for band, previous in prior_profile['assets'].items():
        current = profile['assets'][band]
        for key, value in previous.items():
            assert current[key] == (namespace + value if key in ('metadata_source_id', 'radiometry_sidecar_source_id') else value), 'reused band metadata differs from prior validation'


def validate_multi_provider_profiles(radiometry, scenes, source_checksums, *, root=R):
    """Native providers keep distinct identities and independently bound metadata."""
    assert radiometry['status'] == radiometry['metadata_gate'] == 'PASS'
    assert radiometry['formula'] == 'DN * scale + offset'
    profiles = {(profile['provider'], profile['scene_id']): profile for profile in radiometry['profiles']}
    assert len(profiles) == len(radiometry['profiles']), 'duplicate or conflicting provider/product profile'
    assert radiometry['validated_product_count'] == len(profiles)
    scripts = radiometry['export_scripts']
    assert {script['source_id'] for script in scripts} == {'scripts/campaign_v2.py', 'scripts/campaign_pc.py', 'scripts/downloader.py'}
    assert len(scripts) == 3
    for script in scripts:
        relative(script['source_id'])
        assert valid_sha(script['checksum']) and source_checksums.get(script['source_id']) == script['checksum'], 'export script is not in hashed source inventory'
    unvalidated = {record['source_group']: record for record in radiometry['unvalidated_scene_records']}
    assert len(unvalidated) == len(radiometry['unvalidated_scene_records']), 'duplicate held metadata identity'
    seen_profiles, seen_unvalidated = set(), set()
    prior_reports = {}
    validated_scene_count = 0
    metadata_keys = ('metadata_source_id', 'metadata_sha256', 'radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')
    for scene in scenes:
        provider = scene['provider']
        assert provider in {'earth-search', 'planetary-computer'}
        key = provider, scene['scene_id']
        if key not in profiles:
            assert scene['source_group'] in unvalidated, 'scene has no product profile or explicit metadata hold'
            record = unvalidated[scene['source_group']]
            assert record['provider'] == provider and record['scene_id'] == scene['scene_id']
            assert record['reason'] == scene['metadata_status'] == 'HOLD_MISSING_PRODUCT_METADATA'
            assert not scene['complete'] and scene['missing_bands'], 'complete product cannot lack saved provider metadata'
            assert not scene['usable_source'], 'unvalidated provider metadata cannot be ingested'
            assert not any('radiometry' in asset for asset in scene['assets'].values())
            assert not scene.get('native_grid_proofs'), 'unvalidated source cannot claim a product-grid proof'
            seen_unvalidated.add(scene['source_group'])
            continue
        assert scene['source_group'] not in unvalidated, 'validated scene also claims an unvalidated hold'
        profile = profiles[key]
        assert scene['metadata_status'] == 'VALIDATED'
        seen_profiles.add(key)
        validated_scene_count += 1
        assert profile['profile_key'] == provider + '|' + scene['scene_id']
        assert profile['collection'] == ('sentinel-2-c1-l2a' if provider == 'earth-search' else 'sentinel-2-l2a')
        assert profile['product_uri'] == scene['scene_id'] + '.SAFE', 'profile refers to a different processing product'
        reused = profile.get('metadata_format') == 'earth-search-c1-flat-sidecar'
        namespace = profile.get('source_namespace', '') if reused else ''
        assert profile['metadata_source_id'] == namespace + f"source-items/{provider}/{scene['scene_id']}.json"
        expected_sidecar = f"metadata/{scene['scene_id']}/radiometry.json" if provider == 'earth-search' else f"metadata/{provider}/{scene['scene_id']}/radiometry.json"
        assert profile['radiometry_sidecar_source_id'] == namespace + expected_sidecar
        assert datetime.fromisoformat(profile['sensing_datetime']).strftime('%Y-%m') == scene['month']
        assert profile['platform'].lower().replace('-', '') == 'sentinel2' + scene['satellite'][2:].lower()
        assert f"_N{profile['processing_baseline'].replace('.', '')}_" in scene['scene_id']
        if provider == 'earth-search':
            stac_identity = re.fullmatch(r'(S2[ABC])_(T\d{2}[A-Z]{3})_(\d{8}T\d{6})_L2A', profile['stac_item_id'])
            assert stac_identity and stac_identity[1] == scene['satellite'] and stac_identity[2] == scene['tile']
            assert stac_identity[3][:8] == datetime.fromisoformat(scene['acquisition_datetime']).strftime('%Y%m%d')
        else:
            assert profile['stac_item_id'] == re.sub(r'_N\d{4}', '', scene['scene_id']), 'PC STAC identity must match the exact SAFE product'
        assert profile['assets'].keys() == BANDS
        if provider == 'planetary-computer':
            validate_product_xml_profile(profile, source_checksums)
        for band, proof in profile['assets'].items():
            assert proof['provider'] == provider
            common_proof = dict(proof)
            if provider == 'planetary-computer' and band != 'SCL':
                assert proof['formula'] == '(DN + BOA_ADD_OFFSET) / BOA_QUANTIFICATION_VALUE'
                common_proof['formula'] = 'DN * scale + offset'
            validate_metadata_radiometry(band, common_proof, source_checksums)
            assert proof['nodata'] == 0
            assert proof['native_dtype'] == ('uint8' if band == 'SCL' else 'uint16')
            assert proof['asset_key'] == (EARTH_SEARCH_ASSETS[band] if provider == 'earth-search' else band)
            assert all(proof[name] == profile[name] for name in metadata_keys)
            url = proof['native_asset_url']
            assert '?' not in url
            if provider == 'earth-search':
                assert url.startswith('https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/') and Path(url).name == band + '.tif'
            else:
                assert url.startswith('https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/') and '/' + scene['scene_id'] + '.SAFE/' in url
                assert re.search(r'_' + band + r'_\d+m\.tif$', url)
        for band, asset in scene['assets'].items():
            assert asset['radiometry'] == profile['assets'][band], 'scene/profile radiometry conflict'
            assert scene['raster_grids'][asset['grid']]['dtype'] == asset['radiometry']['native_dtype']
        if reused:
            prior_id = profile['prior_batch_id']
            assert prior_id == 'local-satellite-ingest-20261005'
            if prior_id not in prior_reports:
                path = root / 'audit-artifacts' / prior_id
                prior_reports[prior_id] = (read(path / 'scene_manifest.json'), read(path / 'radiometric_validation.json'))
            prior_scenes, prior_radiometry = prior_reports[prior_id]
            assert source_checksums.get(namespace + prior_radiometry['export_script_source_id']) == prior_radiometry['export_script_sha256'], 'reused encoder evidence differs from prior validation'
            matching_scenes = [record for record in prior_scenes if record['source_group'] == scene['prior_validated_batch']['source_group']]
            matching_profiles = [record for record in prior_radiometry['profiles'] if record['scene_id'] == scene['scene_id']]
            assert len(matching_scenes) == len(matching_profiles) == 1, 'reused crop lacks unique prior source evidence'
            validate_reused_native_scene(scene, profile, matching_scenes[0], matching_profiles[0])
        else:
            assert 'prior_validated_batch' not in scene, 'native crop cannot inherit canonical-grid validation'
            validate_native_grid_proofs(scene)
    assert seen_profiles == profiles.keys(), 'product profiles do not cover only audited scenes'
    assert seen_unvalidated == unvalidated.keys(), 'unvalidated metadata hold is not an audited scene'
    assert radiometry['validated_scene_count'] == validated_scene_count


def validate_native_grid_proofs(scene):
    """Reconstruct each native crop from its exact-product grid and integer window."""
    proofs = scene['native_grid_proofs']
    assert proofs.keys() == scene['assets'].keys(), 'every validated band requires its native product-grid proof'
    for band, asset in scene['assets'].items():
        proof = proofs[band]
        grid = scene['raster_grids'][asset['grid']]
        assert proof['crs'] == grid['crs'] and re.fullmatch(r'EPSG:\d+', proof['crs'])
        assert proof['pixel_encoding'] == 'raw native DN'
        assert isinstance(proof['metadata_transform_tags'], bool)
        if band == 'SCL':
            assert not proof['metadata_transform_tags'], 'SCL cannot carry spectral transform tags'
        transform, product_shape, window = proof['product_transform'], proof['product_shape'], proof['window']
        assert len(transform) == 6 and all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in transform)
        assert len(product_shape) == 2 and all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in product_shape)
        assert len(window) == 4 and all(isinstance(value, int) and not isinstance(value, bool) for value in window)
        col, row, width, height = window
        assert col >= 0 and row >= 0 and width > 0 and height > 0
        assert (width, height) == (grid['width'], grid['height'])
        assert col + width <= product_shape[1] and row + height <= product_shape[0], 'native crop outside original product grid'
        a, b, x, d, e, y = transform
        aa, bb, xx, dd, ee, yy = grid['transform']
        assert a == aa and e == ee and b == bb == d == dd == 0 and a > 0 and e < 0, 'native crop pixel spacing or rotation differs from product'
        assert math.isclose(xx, x + col * a, rel_tol=0, abs_tol=abs(a) * 1e-6) and math.isclose(yy, y + row * e, rel_tol=0, abs_tol=abs(e) * 1e-6), 'native crop origin differs from integer product window'
        assert grid['dtype'] == asset['radiometry']['native_dtype']
        assert grid['nodata'] is None or grid['nodata'] == asset['radiometry']['nodata']


def validate_acquisition_selection(scenes):
    """Retain reprocessing alternatives while contributing each acquisition once."""
    by_group = {scene['source_group']: scene for scene in scenes}
    assert len(by_group) == len(scenes), 'duplicate scene source group'
    key = lambda scene: (scene['plot_id'], scene['month'], scene['acquisition_key'])
    active = {}
    alternatives = {}
    for scene in scenes:
        if scene['usable_source']:
            acquisition = key(scene)
            assert acquisition not in active, 'one acquisition cannot contribute twice'
            active[acquisition] = scene
        if scene['dedup_action'] == 'HOLD_REPROCESSING_ALTERNATIVE':
            assert not scene['usable_source']
            chosen = by_group.get(scene['selected_source_group'])
            assert chosen and chosen['usable_source'] and key(chosen) == key(scene), 'held reprocessing must refer to an active matching acquisition'
            assert chosen['dedup_action'] == 'KEEP_REVIEWED_LATEST_PRODUCT'
            alternatives.setdefault(chosen['source_group'], []).append(scene)
    for scene in scenes:
        if scene['dedup_action'] != 'KEEP_REVIEWED_LATEST_PRODUCT':
            assert not scene.get('selection_alternatives'), 'only an explicit reviewed selection can hold alternatives'
            continue
        held = alternatives.get(scene['source_group'], [])
        listed = scene['selection_alternatives']
        assert scene['usable_source'] and held and len(listed) == len(set(listed))
        assert set(listed) == {record['source_group'] for record in held}, 'selection alternatives must retain every held source'
        rank = lambda record: (record['scene_id'].split('_')[3], record['scene_id'].split('_')[-1],
                               bool(record.get('native_grid_proofs')), record['source_group'])
        assert max([scene] + held, key=rank)['source_group'] == scene['source_group'], 'reviewed selection must use the latest validated processing product'


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
                expected_marker = ('NATIVE_MULTI_PROVIDER_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING'
                                   if batch['radiometric_validation'].get('provider_schema') == MULTI_PROVIDER_SCHEMA else
                                   'NATIVE_C1_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING')
                assert current_qa['radiometry_status'] == expected_marker
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


def validate_inventory_source_rows(inventory, summary, source_rows):
    """Count external encoder evidence separately from physical delivery files."""
    auxiliary = inventory.get('auxiliary_support_files', [])
    assert len(source_rows) == inventory['scientific_tifs'] + len(inventory.get('non_scientific_files', [])) + len(auxiliary)
    assert len({source['source_id'] for source in source_rows}) == len(source_rows), 'duplicate inventory identity'
    source_checksums = {source['source_id']: source['checksum'] for source in source_rows}
    for source in auxiliary:
        relative(source['source_id'])
        assert valid_sha(source['checksum']) and source['filesize'] > 0
        assert source['integrity_status'] == 'HASHED', 'external encoder evidence must be hashed'
        assert source_checksums.get(source['source_id']) == source['checksum']
    reused_count = inventory.get('reused_scientific_tifs', 0)
    if reused_count:
        assert isinstance(reused_count, int) and not isinstance(reused_count, bool) and reused_count > 0
        assert inventory['scientific_tifs'] == inventory['physical_scientific_tifs'] + reused_count
        reused_rows = [source for source in source_rows if source['source_id'].startswith('reused/')
                       and Path(source['source_id']).suffix.lower() in {'.tif', '.tiff'}]
        assert len(reused_rows) == reused_count, 'reused scientific count must match hashed reused TIFF identities'
    if auxiliary:
        physical_count = len(source_rows) - len(auxiliary) - reused_count
        assert inventory['local_files_scanned'] == summary['local_files_scanned'] == physical_count, 'external evidence is not a delivery file'
        assert inventory['source_evidence_files_scanned'] == summary['source_evidence_files_scanned'] == len(source_rows), 'incomplete source evidence count'
    assert sha(sorted(source_rows, key=lambda source: source['source_id'])) == inventory['source_manifest_sha256'] == summary['source_manifest_sha256']
    return source_checksums


def validate_held_scientific_source(source, *, multi_provider=False):
    relative(source['source_id'])
    assert valid_sha(source['checksum']) and source['filesize'] > 0
    assert source['integrity_status'] == 'VALID'
    if multi_provider and source['action'] == 'HOLD_UNASSIGNED_SOURCE':
        assert source['source_id'] == 'test_B04.tif', 'unassigned raster needs an explicit identity audit'
        assert not {'plot_id', 'month', 'scene_id'} & source.keys(), 'unassigned raster cannot claim an observation identity'
        assert isinstance(source['reason'], str) and source['reason']
    else:
        assert source['action'] == 'EXISTING_REGISTRY_OBSERVATION'


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
    multi_provider = radiometry.get('provider_schema') == MULTI_PROVIDER_SCHEMA
    if metadata_backed:
        assert radiometry['metadata_gate'] == 'PASS'
        expected_validated = len(scenes) - len(radiometry['unvalidated_scene_records']) if multi_provider else len(scenes)
        assert isinstance(radiometry['validated_scene_count'], int) and radiometry['validated_scene_count'] == expected_validated
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
        validate_held_scientific_source(source, multi_provider=multi_provider)
        source_rows.append({'source_id': source['source_id'], 'checksum': source['checksum']})
    source_rows.extend({'source_id': source['source_id'], 'checksum': source['checksum']}
                       for source in inventory.get('auxiliary_support_files', []))
    source_checksums = validate_inventory_source_rows(inventory, summary, source_rows)
    if metadata_backed:
        validate_metadata_profiles(radiometry, scenes, source_checksums, root=root)
    if multi_provider:
        validate_acquisition_selection(scenes)
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
            if multi_provider:
                providers = {scene['provider'] for scene in provenance['scenes']}
                expected_source = ('Planetary Computer / Sentinel-2 L2A' if providers == {'planetary-computer'} else
                                   'Earth Search / Sentinel-2 C1 L2A' if providers == {'earth-search'} else
                                   'Earth Search + Planetary Computer / Sentinel-2 L2A')
                assert providers <= {'earth-search', 'planetary-computer'} and providers
                assert observation['source'] == expected_source
            else:
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
                    common_radiometry = dict(asset['radiometry'])
                    if multi_provider and scene['provider'] == 'planetary-computer' and band != 'SCL':
                        assert common_radiometry['formula'] == '(DN + BOA_ADD_OFFSET) / BOA_QUANTIFICATION_VALUE'
                        common_radiometry['formula'] = 'DN * scale + offset'
                    validate_metadata_radiometry(band, common_radiometry, source_checksums)
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
