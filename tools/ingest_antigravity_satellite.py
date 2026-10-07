#!/usr/bin/env python3
"""Fill missing slots from a local Earth Search C1 export with explicit radiometry.

Raw download work stays outside this tool. Historical legacy results are never
reinterpreted. Native DN is decoded using each band's saved STAC scale/offset,
after masking its nodata. All inventory and evidence paths are root-relative.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import subprocess
import sys
import warnings

import numpy as np
import rasterio
from rasterio.warp import reproject
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest_local_satellite as local

R = local.R
VERSION = 'earth-search-c1-local-v4-20261005'
# This reviewed downloader exports unscaled uint16 native DN. A changed export
# implementation needs a fresh encoding audit rather than inheriting this gate.
NATIVE_EXPORT_SCRIPT_SHA256 = 'c1391c1a29013f28061cb47e29edd2e1acf8c0e85e307841adfd78ccdb9696e2'
# The second delivery changes only DELIVERY_ROOT; its encoding is byte-identical.
REVIEWED_NATIVE_EXPORT_SHA256 = frozenset((
    NATIVE_EXPORT_SCRIPT_SHA256,
    '967d2ed3185b7d8ada415fbc9ea0255089f082db423e80e8036e6e8d3a20a7db',
    # Next3 changes acquisition/state/repair handling; download_band is unchanged.
    'c8fea583ba320248dcbdd8198367ef1dbb50479790b10cd92a981698d94c1873',
))
ASSET_KEYS = dict(zip(local.BANDS, ('blue', 'green', 'red', 'rededge1', 'rededge2',
                                  'rededge3', 'nir', 'nir08', 'swir16', 'swir22', 'scl')))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exporter_evidence(root, export_script=None):
    path = (export_script or root / 'scripts/sentinel_pipeline.py').resolve()
    stat = path.stat()
    checksum = local.file_hash(path)
    require(checksum in REVIEWED_NATIVE_EXPORT_SHA256,
            'export script differs from reviewed native DN encoder; a new encoding audit is required')
    external = not path.is_relative_to(root)
    source_id = ('export-scripts/' + path.name if external else path.relative_to(root).as_posix())
    public = {'source_id': source_id, 'filesize': stat.st_size,
              'checksum': checksum, 'integrity_status': 'HASHED'}
    private = {**public, 'source_path': str(path), 'archive_path': None,
               'member_path': None, 'mtime_ns': stat.st_mtime_ns}
    return public, private, external


def metadata_profile(root, scene_id):
    """Bind product, per-band STAC metadata and export sidecar before reading DN."""
    stac_path = root / 'source-items/earth-search' / f'{scene_id}.json'
    sidecar_path = root / 'metadata' / scene_id / 'radiometry.json'
    item, sidecar = local.read_json(stac_path), local.read_json(sidecar_path)
    properties = item['properties']
    product = properties['s2:product_uri'].removesuffix('.SAFE')
    require(item['collection'] == 'sentinel-2-c1-l2a', 'unsupported source collection')
    require(product == scene_id, 'STAC product URI does not match exported product')
    require(sidecar['s2_product_uri'].removesuffix('.SAFE') == product, 'sidecar product mismatch')
    require(properties['s2:processing_baseline'] == sidecar['processing_baseline'], 'baseline mismatch')
    require(properties['platform'] == sidecar['platform'], 'spacecraft mismatch')
    require(properties['datetime'][:7] == local.SCENE_RE.fullmatch(scene_id)[2][:4] + '-' +
            local.SCENE_RE.fullmatch(scene_id)[2][4:6], 'STAC sensing month mismatch')
    for flag in ('earthsearch:boa_offset_applied', 'earthsearch:reflectance_offset_applied'):
        require(not properties.get(flag), 'already harmonized source cannot inherit native DN offset')
    proof = {'scene_id': scene_id, 'stac_item_id': item['id'], 'collection': item['collection'],
             'product_uri': properties['s2:product_uri'], 'sensing_datetime': properties['datetime'],
             'processing_baseline': properties['s2:processing_baseline'], 'platform': properties['platform'],
             'catalog_cloud_cover_pct': properties.get('eo:cloud_cover'),
             'metadata_source_id': stac_path.relative_to(root).as_posix(),
             'metadata_sha256': local.file_hash(stac_path),
             'radiometry_sidecar_source_id': sidecar_path.relative_to(root).as_posix(),
             'radiometry_sidecar_sha256': local.file_hash(sidecar_path), 'assets': {}}
    for band, key in ASSET_KEYS.items():
        asset = item['assets'][key]
        require(Path(asset['href']).name == band + '.tif', f'{band}: STAC band filename mismatch')
        require(asset['href'].startswith('https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/'),
                f'{band}: unsupported native asset origin')
        raster_bands = asset['raster:bands']
        require(len(raster_bands) == 1, f'{band}: expected one raster band')
        rb = raster_bands[0]
        require('nodata' in rb, f'{band}: nodata metadata missing')
        nodata = rb['nodata']
        require(nodata is None or isinstance(nodata, (int, float)) and math.isfinite(nodata), f'{band}: invalid nodata')
        require(nodata == sidecar[band + '_nodata'], f'{band}: conflicting nodata metadata')
        if band == 'SCL':
            require(rb.get('scale', 1) == 1 and rb.get('offset', 0) == 0, 'SCL must remain categorical')
            require(sidecar.get('SCL_scale') in (None, 1) and sidecar.get('SCL_offset') in (None, 0), 'SCL sidecar conflict')
            scale, offset, formula = 1, 0, 'SCL categorical'
        else:
            require([e['name'] for e in asset['eo:bands']] == [band], f'{band}: eo:bands mismatch')
            scale, offset, formula = rb['scale'], rb['offset'], 'DN * scale + offset'
            require(isinstance(scale, (int, float)) and math.isfinite(scale) and scale > 0, f'{band}: invalid scale')
            require(isinstance(offset, (int, float)) and math.isfinite(offset), f'{band}: invalid offset')
            require(scale == sidecar[band + '_scale'] and offset == sidecar[band + '_offset'], f'{band}: conflicting radiometry')
        proof['assets'][band] = {'scale': scale, 'offset': offset, 'nodata': nodata, 'formula': formula,
                                'asset_key': key, 'native_dtype': rb['data_type'],
                                **{k: proof[k] for k in ('metadata_source_id', 'metadata_sha256',
                                                       'radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')}}
    return proof


def bind_radiometry(scenes, profiles):
    for scene in scenes:
        profile = profiles[scene['scene_id']]
        for band, rec in scene['assets'].items():
            radiometry = profile['assets'][band]
            require(rec['dtype'] == radiometry['native_dtype'], f'{rec["source_id"]}: exported dtype differs from STAC')
            require(rec['scales'] == [1.0] and rec['offsets'] == [0.0], 'export already carries a transform')
            require(rec['nodata'] is None or rec['nodata'] == radiometry['nodata'], 'export nodata conflicts with STAC')
            rec['radiometry'] = radiometry


def read_native_asset(item, band, grid, resampling):
    record = item.assets[band]
    info = record['radiometry']
    with local.open_raster(record) as ds:
        dst = np.full((grid.height, grid.width), np.nan, dtype=np.float32)
        # The downloader left zero nodata out of TIFF headers. The STAC value
        # must therefore be used before scaling, especially before bilinear reads.
        reproject(rasterio.band(ds, 1), dst, src_transform=ds.transform, src_crs=ds.crs,
                  src_nodata=info['nodata'], dst_transform=grid.transform, dst_crs='EPSG:4326',
                  dst_nodata=np.nan, resampling=resampling)
    if band != 'SCL':
        valid = np.isfinite(dst)
        dst[valid] = dst[valid] * info['scale'] + info['offset']
    return dst


def process_native(plot, scenes, *, output_dir=None, write_assets=False):
    require(bool(scenes), 'no scenes to process')
    month = scenes[0]['month']
    require(all(s['plot_id'] == int(plot['id']) and s['month'] == month and s['usable_source'] and
                s['scope'] == 'REGISTRY_CONTAINED' for s in scenes), 'requires complete exact-month registry scenes')
    geom = shape(plot['geometry'])
    grid = local.base.compute_grid(geom)
    inside = local.base.plot_mask(geom, grid)
    errors = []
    items = [local.local_item(s) for s in scenes]
    for item, scene in zip(items, scenes):
        item.properties['eo:cloud_cover'] = scene.get('catalog_cloud_cover_pct')
    def reader(item, band, grid, resampling):
        try:
            return read_native_asset(item, band, grid, resampling)
        except Exception as exc:
            errors.append(f'{item.id}/{band}: {type(exc).__name__}: {exc}')
            raise
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        result = local.v4.build_month_v4(None, plot, geom, grid, inside, int(month[:4]), int(month[5:]),
                                      items=items, read_asset=reader,
                                      output_dir=output_dir, write_assets=write_assets)
    if errors:
        raise RuntimeError('source read failure cannot be labeled cloud: ' + '; '.join(errors))
    result['source'] = 'Earth Search / Sentinel-2 C1 L2A'
    return result


def compact_scene(scene):
    result = local.public_scene(scene)
    for band, rec in scene['assets'].items():
        result['assets'][band].update(source_id=rec['source_id'], radiometry=rec['radiometry'])
    return result


def snapshot_support(root, prepared_paths, series):
    support, held, private = [], [], []
    for path in sorted(p for p in root.rglob('*') if p.is_file() and p not in prepared_paths):
        stat = path.stat()
        record = {'source_id': path.relative_to(root).as_posix(), 'filesize': stat.st_size,
                  'checksum': local.file_hash(path), 'integrity_status': 'HASHED'}
        private.append({**record, 'source_path': str(path), 'archive_path': None,
                        'member_path': None, 'mtime_ns': stat.st_mtime_ns})
        if path.suffix.lower() in ('.tif', '.tiff'):
            match = re.fullmatch(r'repairs/repair_registry_(\d+)_(\d{4}-\d{2})/([A-Z0-9]+)\.tif', record['source_id'])
            require(match is not None, 'unindexed scientific source; rebuild or audit its mapping before ingestion')
            pid, month = int(match[1]), match[2]
            require(pid in series and any(o['month'] == month and local.usable(o) for o in series[pid]['timeseries']),
                    'repair target lacks a usable observation; requires exact-product reconciliation before processing')
            with rasterio.open(path) as ds:
                ds.read()  # Independently decode repair files, even though their slots are preserved.
                require(ds.count == 1 and ds.crs is not None, 'invalid held repair raster')
            record.update(integrity_status='VALID', action='EXISTING_REGISTRY_OBSERVATION', plot_id=pid, month=month, band=match[3],
                          reason='repair target already has a usable registry observation; no replacement')
            held.append(record)
        else:
            require(path.suffix.lower() != '.zip', 'unexpected archive requires archive integrity/mapping audit')
            support.append(record)
    return support, held, private


def provenance(pid, month, scenes, manifest_hash, timestamp):
    return {'version': VERSION, 'processing_version': local.v4.PROXY_VERSION, 'ingested_at': timestamp,
            'registry_plot_id': pid, 'registry_code': scenes[0]['code'], 'exact_month': month,
            'scope': 'REGISTRY', 'scope_classification': 'REGISTRY_CONTAINED',
            'reflectance_formula': 'DN * scale + offset', 'source_manifest_sha256': manifest_hash,
            'radiometry_interpretation': 'native Earth Search C1 per-band STAC metadata; legacy observations preserved without reinterpretation',
            'scenes': [{'scene_id': s['scene_id'], 'acquisition_datetime': s['acquisition_datetime'],
                        'source_fingerprint': s['fingerprint'],
                        'assets': {b: {'source_id': r['source_id'], 'original_filename': Path(r['source_id']).name,
                                       'member_path': None, 'sha256': r['checksum'], 'filesize': r['filesize'],
                                       'raster_signature': local.raster_signature(r), 'radiometry': r['radiometry']}
                                   for b, r in sorted(s['assets'].items())}} for s in scenes]}


def refresh_accepted_qa(accepted_keys, previous_qa):
    """Refresh new slots while preserving all earlier QA evidence verbatim."""
    subprocess.run([sys.executable, str(R / 'tests/build_all_plots_visual_qa.py')], cwd=R, check=True)
    computed = local.read_json(R / 'audit-artifacts/all_plots_visual_qa.json')
    output = previous_qa
    if 'method' in computed:
        output['method'] = computed['method']
    for key in accepted_keys:
        rec = computed['observations'][key]
        rec['radiometry_status'] = 'NATIVE_C1_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING'
        if rec['status'] == 'CLEAR':
            rec['visual_screening_status'] = 'CLEAR'
            rec['status'] = 'RADIOMETRY_REVIEW'
            rec['reason'] = 'ภาพครบ แต่ยังไม่ยืนยันความสอดคล้องของค่าสะท้อนแสงระหว่างชุดข้อมูล จึงยังไม่สรุปการเปลี่ยนแปลง'
        output['observations'][key] = rec
    output['summary'] = dict(sorted(Counter(r['status'] for r in output['observations'].values()).items()))
    local.write_json(R / 'data/all_plots_visual_qa.json', output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--index', type=Path, default=R / '.local/next-source-index-20261005.sqlite')
    parser.add_argument('--report-dir', type=Path, default=R / '.local/next-ingest-audit')
    parser.add_argument('--export-script', type=Path,
                        help='Reviewed exporter evidence when supplied outside the scientific delivery')
    parser.add_argument('--reuse-index', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.source_dir.resolve()
    export_public, export_private, export_external = exporter_evidence(root, args.export_script)
    catalog = {int(p['id']): p for p in local.read_json(R / 'data/plots_catalog.json')}
    series = {int(p['id']): p for p in local.read_json(R / 'data/timeseries_verified_12.json')}
    require(len(catalog) == len(series) == 210 and catalog.keys() == series.keys(), 'registry identities differ')
    require(all(tuple(o['month'] for o in p['timeseries']) == local.MONTHS for p in series.values()), 'declared months differ')
    pdd = {p['code']: p for p in local.read_json(R / 'data/pdd22/plots_catalog.json')}
    records, inventory = local.build_index(root / 'prepared/inputs', args.index, catalog, pdd, args.reuse_index)
    require(all(r['integrity_status'] == 'VALID' for r in records), 'invalid prepared raster; audit before ingest')
    for r in records:
        stat = Path(r['source_path']).stat()
        require(stat.st_size == r['filesize'] and stat.st_mtime_ns == r['mtime_ns'], 'source changed since cached inventory; rebuild index')
        r['source_id'] = r['relative_id'] = 'prepared/inputs/' + r['source_id']
    scenes, unresolved = local.reconcile_scenes(records)
    require(not unresolved, 'unresolved source identity; audit before ingest')
    support, held, support_private = snapshot_support(root, {Path(r['source_path']) for r in records}, series)
    profiles = {s: metadata_profile(root, s) for s in sorted({s['scene_id'] for s in scenes})}
    bind_radiometry(scenes, profiles)
    for s in scenes:
        s['catalog_cloud_cover_pct'] = profiles[s['scene_id']]['catalog_cloud_cover_pct']
    byslot = defaultdict(list)
    for scene in scenes:
        byslot[(scene['plot_id'], scene['month'])].append(scene)
    auxiliary = [export_public] if export_external else []
    source_rows = sorted([{'source_id': r['source_id'], 'checksum': r['checksum']}
                          for r in records + support + held + auxiliary], key=lambda r: r['source_id'])
    require(len({r['source_id'] for r in source_rows}) == len(source_rows),
            'duplicate source evidence identity; disambiguate exporter from delivery files')
    source_inventory = {**{k: v for k, v in inventory.items() if k != 'archives'},
                        'local_files_scanned': len(records) + len(support) + len(held),
                        'source_evidence_files_scanned': len(source_rows),
                        'auxiliary_files_scanned': len(auxiliary),
                        'auxiliary_support_files': auxiliary,
                        'local_bytes': sum(r['filesize'] for r in records + support + held),
                        'scientific_tifs': len(records) + len(held), 'prepared_scientific_tifs': len(records),
                        'repair_scientific_tifs': len(held), 'held_scientific_files': held,
                        'processing_version': VERSION, 'source_manifest_sha256': local.digest(source_rows),
                        'integrity_counts': dict(sorted(Counter(r['integrity_status'] for r in records + held).items())),
                        'resolved_plots': len({s['plot_id'] for s in scenes}),
                        'unique_scientific_checksums': len({r['checksum'] for r in records + held}),
                        'non_scientific_files': support,
                        'download_manifest_records': len(local.read_json(root / 'download_manifest.json')),
                        'request_result_records': len(local.read_json(root / 'request_results.json')),
                        'inventory_basis': 'actual decoded files; delivery manifests are incomplete and are not authoritative'}
    report = args.report_dir
    local.write_json(report / 'source_inventory.json', source_inventory)
    local.write_json(report / 'archive_integrity.json', {**{k: inventory[k] for k in ('zip_count', 'zip_valid', 'zip_corrupt', 'zip_duplicate_source', 'total_members')},
                                                     'archives': [], 'note': 'No ZIP found. Every prepared and held repair TIFF is decoded and hashed.'})
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
                 'method': 'exact-product native DN export + independent matching per-band STAC and sidecar metadata',
                 'validated_scene_count': len(scenes), 'validated_product_count': len(profiles),
                 'interpretation': 'Native Earth Search C1 metadata requires offset after scale. Legacy DN/10000 observations remain unchanged; this does not establish cross-batch radiometric harmonization.',
                 'profiles': list(profiles.values()), 'export_script_source_id': export_public['source_id'],
                 'export_script_sha256': export_public['checksum']}
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
    local.verify_source_unchanged(export_private)
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
                for pathkey in ('metadata_source_id', 'radiometry_sidecar_source_id'):
                    path = root / profiles[s['scene_id']][pathkey]
                    hashkey = 'metadata_sha256' if pathkey == 'metadata_source_id' else 'radiometry_sidecar_sha256'
                    require(local.file_hash(path) == profiles[s['scene_id']][hashkey], 'radiometry metadata changed during processing')
            stage = R / '.local/next-satellite-staging' / str(pid)
            result = process_native(catalog[pid], selected, output_dir=stage, write_assets=args.apply)
            rec.update(coverage_pct=result.get('clear_pixel_pct', 0), scenes_used=result['scene_ids'])
            rec['result'] = 'NO_CLEAR_SCENE' if result['status'] == 'no_data' else ('LOW_COVERAGE' if not local.usable(result) else 'USABLE_DRY_RUN')
            if local.usable(result):
                used = [s for s in selected if s['scene_id'] in result['scene_ids']]
                result['ingest_provenance'] = 'local native Earth Search C1 TIFF; exact month; registry scope; explicit radiometry'
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
               'unresolved_scope': 0, 'unresolved_sources': len(unresolved),
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
