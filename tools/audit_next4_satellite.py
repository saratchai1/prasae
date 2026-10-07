#!/usr/bin/env python3
"""Audit native Earth Search and Planetary Computer local crops without redownloading imagery.

Existing observations are preserved. Exact product metadata and reviewed unscaled
exporters are required. Differing 10/20m crop edges are safe only when each native
window is on its authoritative product grid and contains the full registry.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import rasterio
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest_local_satellite as local
import ingest_antigravity_satellite as native
import next4_provider_metadata as provider
R = local.R
VERSION = 'native-multi-provider-local-v4-20261007'
require = native.require


def profile_key(scene):
    return (scene['provider'], scene['scene_id'])


def provider_name(source_id):
    return 'planetary-computer' if '/alternative-providers/planetary-computer/' in source_id else 'earth-search'


def load_profiles(root, records, metadata_dir):
    grouped = defaultdict(list)
    for r in records:
        grouped[(provider_name(r['source_id']), r['scene_id'])].append(r)
    profiles, held = {}, []
    for (name, sid), rows in sorted(grouped.items()):
        path = root / 'source-items' / name / (sid + '.json')
        if not path.exists():
            # An incomplete failed download is evidence, never a processable scene.
            groups = defaultdict(set)
            for r in rows:
                groups[r['source_id'].rsplit('/', 1)[0]].add(r['band'])
            require(all(set(local.BANDS) - bands for bands in groups.values()), 'complete product lacks metadata')
            held.extend({'provider': name, 'scene_id': sid, 'source_group': group,
                         'reason': 'HOLD_MISSING_PRODUCT_METADATA'} for group in groups)
            continue
        profiles[(name, sid)] = provider.metadata_profile(root, name, sid, metadata_dir)
    return profiles, held


def native_grid_proof(record, asset, item, radiometry):
    expected_crs = asset.get('proj:code') or item['properties'].get('proj:code')
    epsg = asset.get('proj:epsg') or item['properties'].get('proj:epsg')
    if epsg is not None:
        expected_crs = f'EPSG:{epsg}'
    require(expected_crs == record['crs'], 'native crop CRS differs from exact STAC product')
    transform = asset['proj:transform'][:6]
    original_shape = asset['proj:shape']
    a, b, x, d, e, y = record['transform']
    aa, bb, xx, dd, ee, yy = transform
    require(a == aa and b == bb == 0 and d == dd == 0 and e == ee and a > 0 and e < 0,
            'native crop resampled or rotated relative to product grid')
    col, row = (x - xx) / aa, (y - yy) / ee
    require(abs(col-round(col)) < 1e-6 and abs(row-round(row)) < 1e-6, 'native crop off original pixel grid')
    require(col >= 0 and row >= 0 and col + record['width'] <= original_shape[1] and
            row + record['height'] <= original_shape[0], 'native window outside original product')
    require(record['dtype'] == radiometry['native_dtype'], 'native dtype mismatch')
    tags = (record['scales'], record['offsets'])
    require(tags == ([1.0], [0.0]) or tags == ([radiometry['scale']], [radiometry['offset']]),
            'TIFF transform tags conflict with verified product metadata')
    require(record['nodata'] is None or record['nodata'] == radiometry['nodata'], 'native nodata mismatch')
    return {'crs': expected_crs, 'product_transform': transform, 'product_shape': original_shape,
            'window': [int(round(col)), int(round(row)), record['width'], record['height']],
            'metadata_transform_tags': tags != ([1.0], [0.0]), 'pixel_encoding': 'raw native DN'}


def reconcile_native_windows(root, records, profiles):
    items = {}
    for key, profile in profiles.items():
        items[key] = local.read_json(root / profile['metadata_source_id'])
    for r in records:
        key = (provider_name(r['source_id']), r['scene_id'])
        if key not in profiles:
            continue
        p, item = profiles[key], items[key]
        radiometry = p['assets'][r['band']]
        r['native_grid_proof'] = native_grid_proof(r, item['assets'][radiometry['asset_key']], item, radiometry)
        r['radiometry'] = radiometry
    scenes, unresolved = local.reconcile_scenes(records)
    for s in scenes:
        s['provider'] = provider_name(s['source_group'])
        verified = profile_key(s) in profiles
        s['metadata_status'] = 'VALIDATED' if verified else 'HOLD_MISSING_PRODUCT_METADATA'
        # Crop windows at native 10m/20m resolution round differently. Preserve
        # actual grid footprints; permit those edges only after product-grid and
        # full-registry checks on every available band.
        if verified and s['errors'] == ['MISMATCHED_FOOTPRINT'] and all(
                r.get('native_grid_proof') and r['source_scope'] == 'REGISTRY_CONTAINED' and
                r['registry_footprint_coverage'] >= .999 for r in s['assets'].values()):
            s.update(errors=[], scope='REGISTRY_CONTAINED')
        s['native_grid_proofs'] = {b: r['native_grid_proof'] for b, r in s['assets'].items() if r.get('native_grid_proof')}
        s['usable_source'] = verified and s['complete'] and not s['errors'] and s['scope'] == 'REGISTRY_CONTAINED'
        s['dedup_action'] = 'KEEP'
        s['equivalent_sources'] = []
    equivalence = defaultdict(list)
    for s in scenes:
        if s['usable_source']:
            equivalence[(s['plot_id'], s['month'], s['acquisition_key'], s['scope'], s['fingerprint'])].append(s)
    for xs in equivalence.values():
        xs.sort(key=lambda s: s['source_group'])
        for duplicate in xs[1:]:
            duplicate.update(usable_source=False, dedup_action='SKIP_EQUIVALENT_SOURCE')
            xs[0]['equivalent_sources'].append(duplicate['source_group'])
    select_reviewed_products(scenes)
    return scenes, unresolved


def select_reviewed_products(scenes):
    """Select one authoritative product per acquisition, retaining alternatives.

    This is explicit reprocessing selection, not a claim of raster equivalence.
    Product metadata, grids, scope and encoding are independently validated
    first. The highest processing baseline, then latest processing timestamp,
    is preferred. An exact product on its verified native grid takes priority
    over a previous warped representation. No acquisition is weighted twice.
    """
    acquisitions = defaultdict(list)
    for s in scenes:
        if s['usable_source']:
            acquisitions[(s['plot_id'], s['month'], s['acquisition_key'])].append(s)
    for xs in acquisitions.values():
        if len(xs) < 2:
            continue
        chosen = max(xs, key=lambda s: (s['scene_id'].split('_')[3], s['scene_id'].split('_')[-1],
                                      bool(s.get('native_grid_proofs')), s['source_group']))
        chosen['dedup_action'] = 'KEEP_REVIEWED_LATEST_PRODUCT'
        chosen['selection_alternatives'] = [s['source_group'] for s in xs if s is not chosen]
        for s in xs:
            if s is not chosen:
                s.update(usable_source=False, dedup_action='HOLD_REPROCESSING_ALTERNATIVE',
                         selected_source_group=chosen['source_group'])


def reused_native_source(root, index):
    """Reuse one proven complementary C1 source; all earlier bytes stay intact."""
    sid = 'S2A_MSIL2A_20230923T033541_N0509_R061_T47NMJ_20230923T075900'
    prefix = 'reused/inputs-next/'
    with sqlite3.connect(index.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        rows = [json.loads(row[0]) for row in conn.execute('SELECT record_json FROM sources WHERE registry_plot_id=131 AND month=? AND scene_id=?', ('2023-09', sid))]
    scenes, unresolved = local.reconcile_scenes(rows)
    require(not unresolved and len(scenes) == 1 and scenes[0]['usable_source'], 'previous native source is not complete full-registry')
    old = scenes[0]
    previous = local.read_json(R / 'audit-artifacts/local-satellite-ingest-20261005/scene_manifest.json')
    proof = next(s for s in previous if s['plot_id'] == 131 and s['month'] == '2023-09' and s['scene_id'] == sid)
    require(old['fingerprint'] == proof['fingerprint'], 'prior native source changed')
    native.exporter_evidence(root)
    p = native.metadata_profile(root, sid)
    item = local.read_json(root / p['metadata_source_id'])
    support, private = [], []
    for source_id in (p['metadata_source_id'], p['radiometry_sidecar_source_id'], 'scripts/sentinel_pipeline.py'):
        path = root / source_id
        st = path.stat()
        rec = {'source_id': prefix + source_id, 'filesize': st.st_size, 'checksum': local.file_hash(path), 'integrity_status': 'HASHED'}
        support.append(rec)
        private.append({**rec, 'source_path': str(path), 'archive_path': None, 'member_path': None, 'mtime_ns': st.st_mtime_ns})
    p.update(provider='earth-search', profile_key='earth-search|' + sid, metadata_format='earth-search-c1-flat-sidecar',
             source_namespace=prefix, prior_batch_id='local-satellite-ingest-20261005')
    for key in ('metadata_source_id', 'radiometry_sidecar_source_id'):
        p[key] = prefix + p[key]
    for b, info in p['assets'].items():
        info.update(provider='earth-search', native_asset_url=item['assets'][info['asset_key']]['href'],
                    metadata_source_id=p['metadata_source_id'], radiometry_sidecar_source_id=p['radiometry_sidecar_source_id'])
    for rec in rows:
        local.verify_source_unchanged(rec)
        rec['source_id'] = rec['relative_id'] = prefix + 'prepared/inputs/' + rec['source_id']
        rec['radiometry'] = p['assets'][rec['band']]
    old.update(source_group=prefix + 'prepared/inputs/' + old['source_group'], provider='earth-search', metadata_status='VALIDATED',
               catalog_cloud_cover_pct=p['catalog_cloud_cover_pct'], native_grid_proofs={},
               prior_validated_batch={'id': 'local-satellite-ingest-20261005', 'fingerprint': proof['fingerprint'],
                                      'source_group': proof['source_group']})
    return rows, old, p, support, private


def compact_scene(scene):
    result = local.public_scene(scene)
    for band, rec in scene['assets'].items():
        result['assets'][band]['source_id'] = rec['source_id']
        if 'radiometry' in rec:
            result['assets'][band]['radiometry'] = rec['radiometry']
    return result


def snapshot_support(root, prepared_paths, series):
    support, held, private = [], [], []
    for path in sorted(p for p in root.rglob('*') if p.is_file() and p not in prepared_paths):
        st = path.stat()
        rec = {'source_id': path.relative_to(root).as_posix(), 'filesize': st.st_size,
               'checksum': local.file_hash(path), 'integrity_status': 'HASHED'}
        private.append({**rec, 'source_path': str(path), 'archive_path': None, 'member_path': None, 'mtime_ns': st.st_mtime_ns})
        if path.suffix.lower() in ('.tif', '.tiff'):
            require(rec['source_id'] == 'test_B04.tif', 'unexpected unassigned scientific file; audit its identity')
            with rasterio.open(path) as ds:
                for _, window in ds.block_windows(1):
                    ds.read(1, window=window)
                require(ds.count == 1 and ds.crs, 'invalid held test raster')
            rec.update(integrity_status='VALID', action='HOLD_UNASSIGNED_SOURCE',
                       reason='standalone download test lacks registry/month/product mapping; no ingestion')
            held.append(rec)
        else:
            require(path.suffix.lower() != '.zip', 'unexpected archive requires integrity audit')
            support.append(rec)
    return support, held, private


def metadata_auxiliary(metadata_dir, profiles):
    public, private = [], []
    for key, profile in profiles.items():
        if key[0] != 'planetary-computer':
            continue
        path = metadata_dir / profile['product_metadata_source_id']
        st = path.stat()
        rec = {'source_id': profile['product_metadata_source_id'], 'filesize': st.st_size,
               'checksum': local.file_hash(path), 'integrity_status': 'HASHED'}
        require(rec['checksum'] == profile['product_metadata_sha256'], 'product XML changed')
        public.append(rec)
        private.append({**rec, 'source_path': str(path), 'archive_path': None, 'member_path': None, 'mtime_ns': st.st_mtime_ns})
    return public, private


def verify_profile(root, metadata_dir, p):
    if p.get('source_namespace'):
        root = root.parent
        # The namespace is portable; the configured original delivery is read-only.
        for idkey, hashkey in [('metadata_source_id', 'metadata_sha256'), ('radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')]:
            require(local.file_hash(root / p[idkey].removeprefix('reused/')) == p[hashkey], 'reused metadata changed')
        return
    for idkey, hashkey in [('metadata_source_id', 'metadata_sha256'), ('radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')]:
        require(local.file_hash(root / p[idkey]) == p[hashkey], 'product metadata changed during processing')
    if p['provider'] == 'planetary-computer':
        require(local.file_hash(metadata_dir / p['product_metadata_source_id']) == p['product_metadata_sha256'], 'product XML changed')


def process_native(plot, scenes, **kwargs):
    result = native.process_native(plot, scenes, **kwargs)
    providers = sorted({s['provider'] for s in scenes})
    result['source'] = 'Planetary Computer / Sentinel-2 L2A' if providers == ['planetary-computer'] else (
        'Earth Search / Sentinel-2 C1 L2A' if providers == ['earth-search'] else 'Earth Search + Planetary Computer / Sentinel-2 L2A')
    return result


def provenance(pid, month, scenes, manifest_hash, timestamp):
    result = native.provenance(pid, month, scenes, manifest_hash, timestamp)
    result.update(version=VERSION, radiometry_interpretation='exact provider STAC/product XML; raw native DN scaled once; legacy results preserved')
    for proof, scene in zip(result['scenes'], scenes):
        proof['provider'] = scene['provider']
    return result


def refresh_accepted_qa(accepted_keys, previous_qa):
    subprocess.run([sys.executable, str(R / 'tests/build_all_plots_visual_qa.py')], cwd=R, check=True)
    computed = local.read_json(R / 'audit-artifacts/all_plots_visual_qa.json')
    for key in accepted_keys:
        require(computed['observations'][key]['radiometry_status'] == 'NATIVE_MULTI_PROVIDER_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING', 'new QA family is not integrated')
        previous_qa['observations'][key] = computed['observations'][key]
    previous_qa['summary'] = dict(sorted(Counter(r['status'] for r in previous_qa['observations'].values()).items()))
    local.write_json(R / 'data/all_plots_visual_qa.json', previous_qa)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--index', type=Path, default=R / '.local/next4-source-index-20261007.sqlite')
    parser.add_argument('--report-dir', type=Path, default=R / '.local/next-ingest-audit')
    parser.add_argument('--provider-metadata-dir', type=Path, required=True)
    parser.add_argument('--reuse-index', action='store_true')
    parser.add_argument('--reuse-native-source-dir', type=Path, required=True)
    parser.add_argument('--reuse-native-index', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.source_dir.resolve()
    exports = provider.audit_exporters(root)['scripts']
    catalog = {int(p['id']): p for p in local.read_json(R / 'data/plots_catalog.json')}
    series = {int(p['id']): p for p in local.read_json(R / 'data/timeseries_verified_12.json')}
    require(len(catalog) == len(series) == 210 and catalog.keys() == series.keys(), 'registry identities differ')
    require(all(tuple(o['month'] for o in p['timeseries']) == local.MONTHS for p in series.values()), 'declared months differ')
    pdd = {p['code']: p for p in local.read_json(R / 'data/pdd22/plots_catalog.json')}
    records, inventory = local.build_index(root / 'prepared', args.index, catalog, pdd, args.reuse_index)
    require(all(r['integrity_status'] == 'VALID' for r in records), 'invalid prepared raster; audit before ingest')
    for r in records:
        stat = Path(r['source_path']).stat()
        require(stat.st_size == r['filesize'] and stat.st_mtime_ns == r['mtime_ns'], 'source changed since cached inventory; rebuild index')
        r['source_id'] = r['relative_id'] = 'prepared/' + r['source_id']
    profiles, held_metadata = load_profiles(root, records, args.provider_metadata_dir)
    scenes, unresolved = reconcile_native_windows(root, records, profiles)
    require(not unresolved, 'unresolved source identity; audit before ingest')
    support, held, support_private = snapshot_support(root, {Path(r['source_path']) for r in records}, series)
    reused, old_scene, old_profile, old_support, old_private = reused_native_source(args.reuse_native_source_dir.resolve(), args.reuse_native_index)
    require(profile_key(old_scene) not in profiles, 'reused metadata profile identity collision')
    profiles[profile_key(old_scene)] = old_profile
    scenes.append(old_scene)
    records.extend(reused)
    # Reconcile source choices again with the proven complementary old scene.
    select_reviewed_products(scenes)
    for s in scenes:
        profile = profiles.get(profile_key(s))
        if profile:
            s['catalog_cloud_cover_pct'] = profile['catalog_cloud_cover_pct']
        else:
            s.update(usable_source=False, metadata_status='HOLD_MISSING_PRODUCT_METADATA')
    byslot = defaultdict(list)
    for scene in scenes:
        byslot[(scene['plot_id'], scene['month'])].append(scene)
    auxiliary, auxiliary_private = metadata_auxiliary(args.provider_metadata_dir, profiles)
    auxiliary.extend(old_support)
    auxiliary_private.extend(old_private)
    source_rows = sorted([{'source_id': r['source_id'], 'checksum': r['checksum']}
                          for r in records + support + held + auxiliary], key=lambda r: r['source_id'])
    require(len({r['source_id'] for r in source_rows}) == len(source_rows),
            'duplicate source evidence identity; disambiguate exporter from delivery files')
    source_inventory = {**{k: v for k, v in inventory.items() if k != 'archives'},
                        'local_files_scanned': len(records) - len(reused) + len(support) + len(held),
                        'source_evidence_files_scanned': len(source_rows),
                        'auxiliary_files_scanned': len(auxiliary),
                        'auxiliary_support_files': auxiliary,
                        'local_bytes': sum(r['filesize'] for r in records[:-len(reused)] + support + held),
                        'scientific_tifs': len(records) + len(held), 'prepared_scientific_tifs': len(records) - len(reused),
                        'physical_scientific_tifs': len(records) - len(reused) + len(held), 'reused_scientific_tifs': len(reused),
                        'repair_scientific_tifs': 0, 'unassigned_scientific_tifs': len(held), 'held_scientific_files': held,
                        'processing_version': VERSION, 'source_manifest_sha256': local.digest(source_rows),
                        'integrity_counts': dict(sorted(Counter(r['integrity_status'] for r in records + held).items())),
                        'resolved_plots': len({s['plot_id'] for s in scenes}),
                        'unique_scientific_checksums': len({r['checksum'] for r in records + held}),
                        'non_scientific_files': support,
                        'download_manifest_records': len(local.read_json(root / 'download_manifest.json')),
                        'request_result_records': len(local.read_json(root / 'request_results.json')),
                        'inventory_basis': 'actual decoded files and independently hashed support; copied source_inventory is not authoritative'}
    report = args.report_dir
    local.write_json(report / 'source_inventory.json', source_inventory)
    local.write_json(report / 'archive_integrity.json', {**{k: inventory[k] for k in ('zip_count', 'zip_valid', 'zip_corrupt', 'zip_duplicate_source', 'total_members')},
                                                     'archives': [], 'note': 'No ZIP found. Every prepared and held test TIFF is decoded and hashed; reused native source matches prior committed evidence.'})
    report.mkdir(parents=True, exist_ok=True)
    import json
    (report / 'scene_manifest.json').write_text('[\n' + ',\n'.join(json.dumps(compact_scene(s), ensure_ascii=False, separators=(',', ':'), allow_nan=False) for s in scenes) + '\n]\n', encoding='utf-8')
    local.write_json(report / 'unresolved_sources.json', unresolved)
    local.write_json(report / 'partial_scenes.json', [compact_scene(s) for s in scenes if not s['complete']])
    scope_counts = dict(sorted(Counter(s['scope'] for s in scenes).items()))
    local.write_json(report / 'scope_reconciliation.json', {'counts': scope_counts, 'unit': 'prepared source scene',
                     'rule': 'all band footprints contain at least 99.9% of full registry; no PDD substitution',
                     'records': [{k: s[k] for k in ('plot_id', 'code', 'month', 'scene_id', 'scope', 'registry_footprint_coverage_min', 'usable_source')} for s in scenes]})
    local.write_json(report / 'pdd_dedup_report.json', {'skipped_pdd_duplicates': 0,
                    'rule': 'PDD scope is distinct; no equivalence proven and no PDD pixels used',
                    'records': [{'plot_id': s['plot_id'], 'month': s['month'], 'scene_id': s['scene_id'], 'action': 'KEEP_REGISTRY_SOURCE'} for s in scenes if s['code'] in pdd]})
    radiometry = {'status': 'PASS', 'metadata_gate': 'PASS', 'formula': 'DN * scale + offset',
                 'provider_schema': 'native-multi-provider-v1',
                 'method': 'reviewed raw native crop encoder + exact STAC and product XML metadata; nodata before one transform',
                 'validated_scene_count': sum(profile_key(s) in profiles for s in scenes),
                 'validated_product_count': len(profiles), 'unvalidated_scene_records': held_metadata,
                 'interpretation': 'Provider encoding validated independently; legacy observations unchanged; cross-batch harmonization remains pending.',
                 'profiles': list(profiles.values()), 'export_scripts': exports}
    local.write_json(report / 'radiometric_validation.json', radiometry)
    manifest, candidates = [], []
    for pid in sorted(catalog):
        for obs in series[pid]['timeseries']:
            sources = byslot.get((pid, obs['month']), [])
            eligible = [s for s in sources if s['usable_source']]
            category = 'EXISTING_REGISTRY_OBSERVATION' if local.usable(obs) else (
                'MISSING_OBSERVATION_HAS_CANDIDATE' if eligible else 'NO_COMPLETE_SOURCE')
            row = {'plot_id': pid, 'code': local.display_code(catalog[pid]), 'month': obs['month'],
                   'repo_status_before': obs['status'], 'repo_coverage_before': obs.get('clear_pixel_pct'),
                   'category': category, 'source_scene_ids': [s['scene_id'] for s in sources],
                   'eligible_scene_ids': [s['scene_id'] for s in eligible]}
            manifest.append(row)
            if not local.usable(obs):
                candidates.append(row)
    local.write_json(report / 'plot_month_manifest.json', manifest)
    local.write_json(report / 'missing_candidates.json', candidates)
    baseline = {f'{pid}|{o["month"]}': {'observation_sha256': local.digest(o),
                    'derived_assets': {layer: local.file_hash(R / 'data/plots' / str(pid) / f'{layer}_{o["month"]}.png') for layer in ('rgb', 'ndvi')}}
                for pid, p in series.items() for o in p['timeseries'] if local.usable(o)}
    local.write_json(report / 'existing_observation_fingerprints.json', {
        'base_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip(),
        'count': len(baseline), 'observations': baseline})
    # Check all supporting metadata again before the first application write.
    for record in support_private:
        local.verify_source_unchanged(record)
    for record in auxiliary_private:
        local.verify_source_unchanged(record)
    initial_bytes = (R / 'data/timeseries_verified_12.json').read_bytes()
    metadata_bytes = {pid: (R / 'data/plots' / str(pid) / 'metadata.json').read_bytes() for pid in catalog}
    results, accepted, accepted_keys = [], 0, []
    previous_qa = local.read_json(R / 'data/all_plots_visual_qa.json')
    qa_fingerprints = {k: local.digest(v) for k, v in previous_qa['observations'].items()}
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in candidates:
        pid, month = row['plot_id'], row['month']
        selected = [s for s in byslot.get((pid, month), []) if s['usable_source']]
        rec = {**row, 'result': 'NO_COMPLETE_SOURCE'}
        if selected:
            for s in selected:
                for r in s['assets'].values():
                    local.verify_source_unchanged(r)
                verify_profile(root, args.provider_metadata_dir, profiles[profile_key(s)])
            stage = R / '.local/next-satellite-staging' / str(pid)
            result = process_native(catalog[pid], selected, output_dir=stage, write_assets=args.apply)
            rec.update(coverage_pct=result.get('clear_pixel_pct', 0), scenes_used=result['scene_ids'])
            rec['result'] = 'NO_CLEAR_SCENE' if result['status'] == 'no_data' else ('LOW_COVERAGE' if not local.usable(result) else 'USABLE_DRY_RUN')
            if local.usable(result):
                used = [s for s in selected if s['scene_id'] in result['scene_ids']]
                result['ingest_provenance'] = 'local native Sentinel-2 TIFF; exact month; registry scope; explicit provider metadata'
                result['source_provenance'] = provenance(pid, month, used, source_inventory['source_manifest_sha256'], timestamp)
                rec['source_provenance'] = result['source_provenance']
                if args.apply:
                    next_bytes = local.ingest_slot(pid, month, result, stage, initial_bytes, metadata_bytes[pid], version=VERSION)
                    require(next_bytes is not None, 'slot changed before apply; re-audit required')
                    initial_bytes = next_bytes
                    metadata_bytes[pid] = (R / 'data/plots' / str(pid) / 'metadata.json').read_bytes()
                    rec['result'] = 'ACCEPTED'
                    accepted += 1
                    accepted_keys.append(f'{pid}|{month}')
                    rec['derived_assets'] = {layer: {'path': f'data/plots/{pid}/{layer}_{month}.png',
                        'sha256': local.file_hash(R / 'data/plots' / str(pid) / f'{layer}_{month}.png')} for layer in ('rgb', 'ndvi')}
        results.append(rec)
        if selected:
            print(f'{pid} {month}: {rec["result"]} {rec.get("coverage_pct", "")}', flush=True)
    final_series = {int(p['id']): p for p in local.read_json(R / 'data/timeseries_verified_12.json')}
    for key, proof in baseline.items():
        pid, month = key.split('|')
        require(local.digest(next(o for o in final_series[int(pid)]['timeseries'] if o['month'] == month)) == proof['observation_sha256'], 'existing observation changed')
        for layer, checksum in proof['derived_assets'].items():
            require(local.file_hash(R / 'data/plots' / pid / f'{layer}_{month}.png') == checksum, 'existing imagery changed')
    if accepted:
        refresh_accepted_qa(accepted_keys, previous_qa)
    local.write_json(report / 'existing_qa_fingerprints.json', {
        'base_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip(),
        'count': len(qa_fingerprints), 'observations': qa_fingerprints, 'allowed_changed_keys': sorted(accepted_keys)})
    counts = dict(sorted(Counter(r['result'] for r in results).items()))
    summary = {**source_inventory, 'plot_months': len(byslot), 'complete_scenes': sum(s['complete'] for s in scenes),
               'partial_scenes': sum(not s['complete'] for s in scenes), 'scope_counts': scope_counts,
               'complete_scope_counts': dict(sorted(Counter(s['scope'] for s in scenes if s['complete']).items())),
               'unresolved_scope': sum(s['scope'] == 'UNKNOWN' for s in scenes), 'unresolved_sources': len(unresolved),
               'eligible_registry_scenes': sum(s['usable_source'] for s in scenes),
               'source_dedup_actions': dict(sorted(Counter(s['dedup_action'] for s in scenes).items())),
               'missing_candidates_before': len(candidates), 'missing_with_eligible_source': sum(bool(r['eligible_scene_ids']) for r in candidates),
               'existing_observed_slots_in_delivery_skipped': sum(r['category'] == 'EXISTING_REGISTRY_OBSERVATION' and bool(r['source_scene_ids']) for r in manifest),
               'newly_accepted': accepted, 'observed_before': len(baseline),
               'observed_after': sum(local.usable(o) for p in final_series.values() for o in p['timeseries']),
               'still_missing': sum(not local.usable(o) for p in final_series.values() for o in p['timeseries']),
               'result_counts': counts, 'derived_rgb_added': accepted, 'derived_ndvi_added': accepted,
               'existing_usable_observations_preserved': len(baseline), 'mode': 'apply' if args.apply else 'audit',
               'qa_summary': local.read_json(R / 'data/all_plots_visual_qa.json')['summary']}
    local.write_json(report / 'ingest_result.json', {'counts': counts, 'accepted': accepted, 'records': results})
    local.write_json(report / 'final_summary.json', summary)
    print(json.dumps({k: summary[k] for k in ('scientific_tifs', 'complete_scenes', 'partial_scenes', 'result_counts', 'observed_before', 'observed_after', 'still_missing')}, indent=2), flush=True)


if __name__ == '__main__':
    main()
