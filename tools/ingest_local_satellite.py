#!/usr/bin/env python3
"""Inventory local Sentinel crops, then fill only usable missing registry slots.

No network source reads. The private SQLite cache retains absolute paths; public
reports and observations retain relative source identifiers and SHA-256 hashes.
Use --reuse-index after the first audit and --apply to publish staged observations.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import warnings
import zipfile
import zlib

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.warp import reproject, Resampling, transform_bounds
from shapely.geometry import box, shape, Polygon
from shapely.ops import transform as transform_geometry
from pyproj import Transformer

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
import process_verified_12_dates as base
import process_verified_12_dates_v4 as v4

VERSION = 'local-registry-v4-20261004'
BANDS = ('B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12', 'SCL')
MONTHS = tuple(base.month_key(y, m) for y, m in base.MILESTONE_MONTHS)
OBSERVED = {'observed_single_scene', 'observed_monthly_composite'}
SCENE_RE = re.compile(r'^(S2[ABC])_MSIL2A_(\d{8}T\d{6})_(?:N\d{4}_)?(R\d{3})_(T\d{2}[A-Z]{3})_(\d{8}T\d{6})$')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def display_code(plot):
    match = re.search(r'(?<!\d)(\d{1,3})\s*-\s*(STC|VSD|EVR)(?![A-Za-z])', plot.get('name', ''), re.I)
    return f'{int(match[1])}-{match[2].upper()}' if match else plot['code']


def usable(o):
    return bool(o and o.get('status') in OBSERVED and float(o.get('clear_pixel_pct') or 0) >= 5)


def acquisition_key(scene):
    m = SCENE_RE.fullmatch(scene)
    return '_'.join(m.group(i) for i in (1, 2, 3, 4)) if m else None


def resolve_identifier(ident, catalog):
    if re.fullmatch(r'PLOT_\d+', ident, re.I):
        pid = int(ident.split('_')[-1])
        return pid if pid in catalog else None
    match = re.fullmatch(r'(\d{1,3})-(STC|VSD|EVR)', ident, re.I)
    if not match:
        return None
    code = f'{int(match[1])}-{match[2].upper()}'
    ids = [pid for pid, plot in catalog.items() if display_code(plot) == code]
    return ids[0] if len(ids) == 1 else None


def parse_source(identifier, catalog):
    parts = identifier.replace('\\', '/').split('/')
    rec = {'plot_identifier': None, 'registry_plot_id': None, 'registry_code': None,
           'month': None, 'scene_id': None, 'acquisition_datetime': None,
           'satellite': None, 'tile': None, 'band': None, 'mapping_status': 'INVALID_MAPPING'}
    if len(parts) < 4:
        return rec
    ident, month, scene, filename = parts[-4:]
    rec.update(plot_identifier=ident, month=month, scene_id=scene, band=Path(filename).stem.upper())
    pid = resolve_identifier(ident, catalog)
    rec['registry_plot_id'] = pid
    rec['registry_code'] = display_code(catalog[pid]) if pid is not None else None
    m = SCENE_RE.fullmatch(scene)
    if m:
        try:
            dt = datetime.strptime(m[2], '%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc)
            rec.update(acquisition_datetime=dt.isoformat(), satellite=m[1], tile=m[4])
        except ValueError:
            m = None
    if pid is None:
        rec['mapping_status'] = 'UNRESOLVED_PLOT'
    elif m and month in MONTHS and dt.strftime('%Y-%m') == month and rec['band'] in BANDS:
        rec['mapping_status'] = 'RESOLVED'
    return rec


@contextmanager
def open_raster(record):
    if record.get('archive_path'):
        with zipfile.ZipFile(record['archive_path']) as archive:
            raw = archive.read(record['member_path'])
        with MemoryFile(raw) as memory, memory.open() as ds:
            yield ds
    else:
        with rasterio.open(record['source_path']) as ds:
            yield ds


def classify_footprint(footprint, registry_geom, pdd_geom=None):
    rc = registry_geom.intersection(footprint).area / max(registry_geom.area, 1e-20)
    pc = pdd_geom.intersection(footprint).area / max(pdd_geom.area, 1e-20) if pdd_geom is not None else None
    if rc >= 0.999:
        return 'REGISTRY_CONTAINED', rc, pc
    if pc is not None and pc >= 0.999:
        return 'PDD_ONLY_FOOTPRINT', rc, pc
    return 'HOLD_PARTIAL_SCOPE_FOR_REVIEW', rc, pc


def inspect_record(record, catalog, pdd):
    rec = dict(record)
    if rec.get('member_path'):
        with zipfile.ZipFile(rec['archive_path']) as z:
            raw = z.read(rec['member_path'])
        rec['checksum'] = hashlib.sha256(raw).hexdigest()
        rec['crc32'] = f'{zlib.crc32(raw):08x}'
    else:
        rec['checksum'] = file_hash(rec['source_path'])
    rec.update(parse_source(rec['member_path'] or rec['relative_id'], catalog))
    try:
        with open_raster(rec) as ds:
            values = ds.read()  # Decode every raster block, not just its header.
            if ds.count != 1 or ds.crs is None or ds.width < 1 or ds.height < 1:
                raise ValueError('expected one georeferenced scientific band')
            finite = values[np.isfinite(values)]
            if not finite.size:
                raise ValueError('no finite raster values')
            corners = [ds.transform * xy for xy in [(0, 0), (ds.width, 0), (ds.width, ds.height), (0, ds.height)]]
            footprint = Polygon(corners)
            if ds.crs != rasterio.crs.CRS.from_epsg(4326):
                footprint = transform_geometry(Transformer.from_crs(ds.crs, 'EPSG:4326', always_xy=True).transform, footprint)
            if not footprint.is_valid or footprint.area <= 0:
                raise ValueError('invalid raster footprint')
            rec.update(crs=str(ds.crs), bounds=list(ds.bounds), width=ds.width, height=ds.height,
                       dtype=ds.dtypes[0], nodata=ds.nodata, transform=list(ds.transform)[:6],
                       footprint=list(footprint.exterior.coords),
                       scales=list(ds.scales), offsets=list(ds.offsets), tags=ds.tags(),
                       minimum=float(finite.min()), maximum=float(finite.max()),
                       zero_pixel_pct=round(float((values == 0).mean() * 100), 6),
                       all_zero=bool((values == 0).all()), integrity_status='VALID')
            if rec['band'] == 'SCL':
                rec['scl_classes'] = [int(x) for x in np.unique(values)]
                if any(x < 0 or x > 11 for x in rec['scl_classes']):
                    raise ValueError('invalid Sentinel SCL class')
            pid = rec['registry_plot_id']
            if pid is not None:
                pg = pdd.get(display_code(catalog[pid]))
                scope, rc, pc = classify_footprint(footprint, shape(catalog[pid]['geometry']), shape(pg['geometry']) if pg else None)
                rec.update(source_scope=scope, registry_footprint_coverage=round(rc, 8),
                           pdd_footprint_coverage=None if pc is None else round(pc, 8))
            else:
                rec['source_scope'] = 'UNRESOLVED_PLOT'
    except Exception as exc:
        rec.update(integrity_status='INVALID_RASTER', source_scope='UNKNOWN', error=f'{type(exc).__name__}: {exc}')
    return rec


def build_index(root, index_path, catalog, pdd, reuse=False, workers=4):
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path)
    columns = ['source_id', 'source_path', 'archive_path', 'member_path', 'filesize', 'mtime_ns',
               'checksum', 'plot_identifier', 'registry_plot_id', 'registry_code', 'month', 'scene_id',
               'acquisition_datetime', 'satellite', 'tile', 'band', 'crs', 'bounds', 'width', 'height',
               'dtype', 'nodata', 'source_scope', 'integrity_status']
    conn.execute('CREATE TABLE IF NOT EXISTS sources (' + ','.join(f'{c} TEXT' for c in columns) + ', record_json TEXT, PRIMARY KEY(source_id))')
    conn.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
    key = digest({'version': VERSION, 'root': str(root), 'registry': catalog, 'pdd': pdd})
    oldmeta = dict(conn.execute('SELECT key,value FROM metadata'))
    if reuse:
        if oldmeta.get('index_key') != key:
            raise RuntimeError('index root/catalog/version differs; rebuild without --reuse-index')
        rows = [json.loads(r[0]) for r in conn.execute('SELECT record_json FROM sources ORDER BY source_id')]
        inventory = json.loads(oldmeta['inventory'])
        conn.close()
        return rows, inventory
    cached = {json.loads(row[0])['source_id']: json.loads(row[0]) for row in conn.execute('SELECT record_json FROM sources')}
    physical = sorted(p for p in root.rglob('*') if p.is_file())
    jobs, records, archives = [], [], []
    for path in physical:
        stat = path.stat()
        rel = path.relative_to(root).as_posix()
        entry = {'source_id': rel, 'relative_id': rel, 'source_path': str(path), 'archive_path': None,
                 'member_path': None, 'filesize': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        if path.suffix.lower() == '.zip':
            summary = {'source_id': rel, 'filesize': stat.st_size, 'checksum': file_hash(path),
                       'status': 'INVALID_ARCHIVE', 'total_members': 0, 'scientific_tifs': 0}
            try:
                with zipfile.ZipFile(path) as z:
                    bad = z.testzip()
                    summary['total_members'] = len(z.infolist())
                    if bad:
                        raise ValueError(f'CRC failure: {bad}')
                    summary['status'] = 'VALID'
                    for inf in z.infolist():
                        if inf.is_dir() or not inf.filename.lower().endswith(('.tif', '.tiff')) or inf.filename.startswith('__MACOSX/') or '/._' in inf.filename:
                            continue
                        summary['scientific_tifs'] += 1
                        jobs.append({**entry, 'source_id': f'{rel}!{inf.filename}', 'relative_id': f'{rel}!{inf.filename}',
                                     'archive_path': str(path), 'member_path': inf.filename, 'filesize': inf.file_size,
                                     'archive_checksum': summary['checksum']})
            except Exception as exc:
                summary['status'] = 'INVALID_ARCHIVE'
                summary['error'] = f'{type(exc).__name__}: {exc}'
            archives.append(summary)
            records.append({**entry, 'checksum': summary['checksum'], 'integrity_status': summary['status'], 'source_scope': 'UNKNOWN'})
        elif path.suffix.lower() in {'.tif', '.tiff'}:
            jobs.append(entry)
        else:
            records.append({**entry, 'checksum': file_hash(path), 'integrity_status': 'NON_SCIENTIFIC', 'source_scope': 'UNKNOWN'})
    pending = []
    for job in jobs:
        old = cached.get(job['source_id'])
        if oldmeta.get('index_key') == key and old and all(old.get(k) == job.get(k) for k in ('filesize', 'mtime_ns', 'archive_checksum')):
            records.append(old)
        else:
            pending.append(job)
    print(f'Index: {len(physical)} physical files; {len(jobs)} TIFF representations; validating {len(pending)}', flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for n, row in enumerate(pool.map(lambda j: inspect_record(j, catalog, pdd), pending), 1):
            records.append(row)
            if n % 2000 == 0:
                print(f'Raster integrity: {n}/{len(pending)} decoded', flush=True)
    records.sort(key=lambda x: x['source_id'])
    duplicate_archives = Counter(a['checksum'] for a in archives if a['status'] == 'VALID')
    inventory = {'local_files_scanned': len(physical), 'local_bytes': sum(p.stat().st_size for p in physical),
                 'scientific_tifs': len(jobs), 'archives': archives,
                 'zip_count': len(archives), 'zip_valid': sum(a['status'] == 'VALID' for a in archives),
                 'zip_corrupt': sum(a['status'] != 'VALID' for a in archives),
                 'zip_duplicate_source': sum(n - 1 for n in duplicate_archives.values()),
                 'total_members': sum(a['total_members'] for a in archives),
                 'archive_scientific_tifs': sum(a['scientific_tifs'] for a in archives)}
    conn.execute('DELETE FROM sources')
    for rec in records:
        vals = [json.dumps(rec[c], ensure_ascii=False) if isinstance(rec.get(c), (list, dict)) else rec.get(c) for c in columns]
        conn.execute('INSERT INTO sources VALUES (' + ','.join('?' for _ in range(len(columns) + 1)) + ')', vals + [json.dumps(rec, ensure_ascii=False, allow_nan=False)])
    for k, value in {'index_key': key, 'inventory': json.dumps(inventory), 'indexed_at': datetime.now(timezone.utc).isoformat()}.items():
        conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (k, value))
    conn.commit()
    conn.close()
    return records, inventory


def raster_signature(rec):
    return digest({k: rec.get(k) for k in ('checksum', 'crs', 'bounds', 'width', 'height', 'dtype', 'nodata', 'transform')})


def reconcile_scenes(records):
    grouped = defaultdict(list)
    unresolved = []
    for rec in records:
        if rec.get('band') not in BANDS:
            if rec.get('mapping_status'):
                unresolved.append(public_source(rec))
            continue
        if rec['mapping_status'] != 'RESOLVED':
            unresolved.append(public_source(rec))
            continue
        parent = rec['relative_id'].rsplit('/', 1)[0]
        grouped[(rec['registry_plot_id'], rec['month'], rec['scene_id'], parent)].append(rec)
    scenes = []
    for (pid, month, sid, parent), assets in sorted(grouped.items()):
        byband = defaultdict(list)
        for rec in assets:
            byband[rec['band']].append(rec)
        selected = {b: sorted(xs, key=lambda r: (bool(r['archive_path']), r['source_id']))[0] for b, xs in byband.items()}
        errors = []
        for b, xs in byband.items():
            if len({raster_signature(x) for x in xs}) > 1:
                errors.append(f'DUPLICATE_BAND_CONFLICT:{b}')
        missing = sorted(set(BANDS) - set(selected))
        if any(r['integrity_status'] != 'VALID' for r in assets):
            errors.append('INVALID_RASTER')
        if len({r.get('crs') for r in assets}) > 1:
            errors.append('MISMATCHED_CRS')
        footprints = [Polygon(r['footprint']) for r in assets if r.get('footprint')]
        if footprints:
            common = footprints[0]
            for fp in footprints[1:]:
                if common.symmetric_difference(fp).area / max(common.union(fp).area, 1e-20) > 0.001:
                    errors.append('MISMATCHED_FOOTPRINT')
                    break
        scopes = {r.get('source_scope') for r in assets}
        scope = next(iter(scopes)) if len(scopes) == 1 else 'HOLD_PARTIAL_SCOPE_FOR_REVIEW'
        if errors:
            scope = 'UNKNOWN'
        scene = {'plot_id': pid, 'code': assets[0]['registry_code'], 'month': month, 'scene_id': sid,
                 'acquisition_key': acquisition_key(sid), 'acquisition_datetime': assets[0]['acquisition_datetime'],
                 'satellite': assets[0]['satellite'], 'tile': assets[0]['tile'],
                 'source_group': parent, 'scope': scope, 'complete': not missing,
                 'usable_source': not missing and not errors and scope == 'REGISTRY_CONTAINED',
                 'missing_bands': missing, 'duplicate_bands': sorted(b for b, xs in byband.items() if len(xs) > 1),
                 'dimensions': sorted({(r.get('width'), r.get('height')) for r in assets}, key=str),
                 'dimension_mismatch': len({(r.get('width'), r.get('height')) for r in assets}) > 1,
                 'errors': sorted(set(errors)), 'all_zero_bands': sorted(r['band'] for r in assets if r.get('all_zero')),
                 'registry_footprint_coverage_min': min((r.get('registry_footprint_coverage', 0) for r in assets)),
                 'pdd_footprint_coverage_min': min((r['pdd_footprint_coverage'] for r in assets if r.get('pdd_footprint_coverage') is not None), default=None),
                 'assets': selected, 'dedup_action': 'KEEP', 'equivalent_sources': []}
        extra_bands = [public_source(r) for band, xs in byband.items() for r in xs if r is not selected[band]]
        if extra_bands:
            scene['additional_band_sources'] = extra_bands
        scene['fingerprint'] = digest({b: raster_signature(r) for b, r in sorted(selected.items())})
        scenes.append(scene)
    # Only drop duplicate source representations with all required bands, scope,
    # acquisition and raster signatures equivalent. Prefer extracted TIFFs.
    equivalence = defaultdict(list)
    for scene in scenes:
        equivalence[(scene['plot_id'], scene['month'], scene['acquisition_key'], scene['scope'], scene['fingerprint'])].append(scene)
    for xs in equivalence.values():
        xs.sort(key=lambda s: (any(r['archive_path'] for r in s['assets'].values()), s['source_group']))
        for duplicate in xs[1:]:
            if xs[0]['complete'] and duplicate['complete'] and not xs[0]['errors'] and not duplicate['errors']:
                duplicate.update(dedup_action='SKIP_EQUIVALENT_SOURCE', usable_source=False)
                xs[0]['equivalent_sources'].append(duplicate['source_group'])
    # Same acquisition with non-equivalent products is held, rather than silently
    # selecting a reprocessing version or weighting the same acquisition twice.
    acquisitions = defaultdict(list)
    for s in scenes:
        if s['usable_source']:
            acquisitions[(s['plot_id'], s['month'], s['acquisition_key'])].append(s)
    for xs in acquisitions.values():
        if len(xs) > 1:
            for s in xs:
                s.update(usable_source=False, dedup_action='HOLD_ACQUISITION_CONFLICT')
    return scenes, unresolved


def public_source(rec):
    result = {k: v for k, v in rec.items() if k not in {'source_path', 'archive_path', 'mtime_ns'}}
    if result.get('error'):
        for key in ('source_path', 'archive_path'):
            if rec.get(key):
                result['error'] = result['error'].replace(rec[key], rec['source_id'])
    return result


def public_scene(scene):
    # Store each shared grid once. Full per-file raster statistics and machine
    # paths remain in SQLite; this manifest is sufficient to reconstruct every
    # relative identifier and verify the per-band and scene fingerprints.
    grid_keys = ('crs', 'bounds', 'width', 'height', 'dtype', 'nodata', 'transform')
    grids, assets = [], {}
    for band, rec in sorted(scene['assets'].items()):
        grid = {k: rec.get(k) for k in grid_keys}
        if grid not in grids:
            grids.append(grid)
        assets[band] = {'filename': Path(rec['member_path'] or rec['source_id']).name,
                        'filesize': rec['filesize'], 'checksum': rec['checksum'],
                        'grid': grids.index(grid), 'integrity': rec['integrity_status']}
    return {**{k: v for k, v in scene.items() if k != 'assets'}, 'raster_grids': grids, 'assets': assets}


def write_scene_manifest(path, scenes):
    # One deterministic line per scene keeps the complete scientific manifest
    # reviewable without repeating eleven identical grid descriptions.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[\n' + ',\n'.join(json.dumps(public_scene(s), ensure_ascii=False, separators=(',', ':'), allow_nan=False)
                                      for s in scenes) + '\n]\n', encoding='utf-8')


def local_item(scene):
    b = re.search(r'_N(\d{4})_', scene['scene_id'])
    return SimpleNamespace(id=scene['scene_id'], datetime=datetime.fromisoformat(scene['acquisition_datetime']),
                           properties={'eo:cloud_cover': None, 's2:processing_baseline': b[1] if b else None},
                           assets=scene['assets'])


def read_local_asset(item, band, grid, resampling, offset=0):
    record = item.assets[band]
    with open_raster(record) as ds:
        dst = np.full((grid.height, grid.width), np.nan, dtype=np.float32)
        reproject(rasterio.band(ds, 1), dst, src_transform=ds.transform, src_crs=ds.crs,
                  src_nodata=ds.nodata if ds.nodata is not None else 0,
                  dst_transform=grid.transform, dst_crs='EPSG:4326', dst_nodata=np.nan, resampling=resampling)
    if band != 'SCL':
        valid = np.isfinite(dst)
        dst[valid] = (dst[valid] + offset) / 10000.0
    return dst


def process_local(plot, scenes, *, output_dir=None, write_assets=False, offset=0):
    geom = shape(plot['geometry'])
    grid = base.compute_grid(geom)
    inside = base.plot_mask(geom, grid)
    month = scenes[0]['month']
    if any(s['month'] != month or s['plot_id'] != int(plot['id']) or s['scope'] != 'REGISTRY_CONTAINED' or not s['usable_source'] for s in scenes):
        raise ValueError('processing requires usable exact-month registry-contained scenes')
    errors = []
    def checked_reader(item, band, grid, resampling):
        try:
            return read_local_asset(item, band, grid, resampling, offset)
        except Exception as exc:
            errors.append(f'{item.id}/{band}: {type(exc).__name__}: {exc}')
            raise
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        result = v4.build_month_v4(None, plot, geom, grid, inside, int(month[:4]), int(month[5:]),
                                  items=[local_item(s) for s in scenes], read_asset=checked_reader,
                                  output_dir=output_dir, write_assets=write_assets)
    if errors:
        raise RuntimeError('local source read failed; never classify this as cloud: ' + '; '.join(errors))
    return result


def validate_radiometry(scenes, catalog, series):
    byslot = defaultdict(list)
    for scene in scenes:
        if scene['usable_source']:
            byslot[(scene['plot_id'], scene['month'])].append(scene)
    candidates = []
    for pid, plot_series in series.items():
        for obs in plot_series['timeseries']:
            local = byslot.get((pid, obs['month']), [])
            selected_keys = {acquisition_key(s) for s in obs.get('scene_ids', [])}
            available = {s['acquisition_key']: s for s in local}
            # Exact acquisition-set comparisons only; no alternate scene proxies.
            if usable(obs) and (obs.get('clear_pixel_pct') or 0) >= 50 and selected_keys and None not in selected_keys and selected_keys <= available.keys():
                chosen = [available[k] for k in sorted(selected_keys)]
                candidates.append((pid, obs, chosen))
    # Distribute reference samples across month, spacecraft and plot identity.
    candidates.sort(key=lambda x: (x[1]['month'], x[2][0]['satellite'], x[0]))
    strata = defaultdict(list)
    for c in candidates:
        strata[(c[1]['month'], c[2][0]['satellite'])].append(c)
    selected = []
    for n in range(max((len(x) for x in strata.values()), default=0)):
        for key in sorted(strata):
            if n < len(strata[key]):
                selected.append(strata[key][n])
        if len(selected) >= 300:
            break
    rows = []
    for pid, obs, chosen in selected[:300]:
        a = process_local(catalog[pid], chosen)
        b = process_local(catalog[pid], chosen, offset=-1000)
        if a.get('mean_ndvi_inside') is None or b.get('mean_ndvi_inside') is None:
            continue
        target = float(obs['mean_ndvi_inside'])
        rows.append({'plot_id': pid, 'month': obs['month'], 'satellite': chosen[0]['satellite'],
                     'scene_ids': [s['scene_id'] for s in chosen], 'target_ndvi': target,
                     'ndvi_dn_div10000': a['mean_ndvi_inside'], 'ndvi_dn_minus1000': b['mean_ndvi_inside'],
                     'error_no_offset': round(abs(a['mean_ndvi_inside'] - target), 6),
                     'error_minus1000': round(abs(b['mean_ndvi_inside'] - target), 6)})
    mae0 = float(np.mean([r['error_no_offset'] for r in rows])) if rows else None
    mae1 = float(np.mean([r['error_minus1000'] for r in rows])) if rows else None
    wins = sum(r['error_no_offset'] < r['error_minus1000'] for r in rows)
    # Every representation is inspected for DN encoding metadata. Unknown encoding
    # does not inherit the validated formula merely because the filename is S2.
    bad_encoding = sorted({r['source_id'] for s in scenes for b, r in s['assets'].items()
                           if b != 'SCL' and (r.get('dtype') not in {'uint16', 'int16'} or r.get('scales') != [1.0] or r.get('offsets') != [0.0])})
    spacecraft = sorted({s['satellite'] for s in scenes if s['usable_source']})
    tested = sorted({r['satellite'] for r in rows})
    passed = len(rows) >= 20 and wins >= len(rows) * .75 and mae0 < .05 and mae0 < mae1 * .7 and not bad_encoding and tested == spacecraft
    return {'status': 'PASS' if passed else 'HOLD_FOR_REVIEW', 'formula': 'reflectance = DN / 10000; no subtraction of 1000',
            'method': 'canonical v4 reconstruction of matching committed acquisition sets; alternate offset compared on the same pixels',
            'interpretation': 'empirical consistency with committed reference observations; TIFFs do not carry independent product offset metadata',
            'samples': len(rows), 'mae_no_offset': mae0, 'mae_minus1000': mae1, 'better_no_offset': wins,
            'source_spacecraft': spacecraft, 'tested_spacecraft': tested, 'invalid_encoding_sources': bad_encoding, 'rows': rows}


def verify_source_unchanged(record):
    p = Path(record['archive_path'] or record['source_path'])
    stat = p.stat()
    if stat.st_mtime_ns != record['mtime_ns']:
        raise RuntimeError(f'source changed since index: {record["source_id"]}')
    if record['archive_path']:
        with zipfile.ZipFile(p) as z:
            checksum = hashlib.sha256(z.read(record['member_path'])).hexdigest()
    else:
        checksum = file_hash(p)
    if checksum != record['checksum']:
        raise RuntimeError(f'source checksum changed: {record["source_id"]}')


def ingest_slot(pid, month, result, stage, initial_series_bytes, initial_metadata_bytes):
    """Fail closed on concurrent edits before copying either imagery or metadata."""
    ts_path = R / 'data/timeseries_verified_12.json'
    if ts_path.read_bytes() != initial_series_bytes:
        raise RuntimeError('timeseries changed concurrently; rerun audit')
    current = read_json(ts_path)
    target = next(p for p in current if int(p['id']) == pid)
    i = next(i for i, o in enumerate(target['timeseries']) if o['month'] == month)
    if usable(target['timeseries'][i]):
        return None
    md_path = R / 'data/plots' / str(pid) / 'metadata.json'
    if md_path.read_bytes() != initial_metadata_bytes:
        raise RuntimeError(f'plot {pid} metadata changed concurrently; rerun audit')
    md = read_json(md_path)
    mi = next(i for i, o in enumerate(md['dates']) if o['month'] == month)
    if usable(md['dates'][mi]):
        raise RuntimeError('usable plot metadata conflicts with missing timeseries')
    for layer in ('rgb', 'ndvi'):
        src = stage / f'{layer}_{month}.png'
        if src.stat().st_size > 5 * 1024 * 1024:
            raise RuntimeError('derived PNG exceeds 5 MiB review limit')
        dst = md_path.parent / src.name
        if dst.exists():
            raise RuntimeError(f'hold existing derived asset in missing slot: {dst.relative_to(R)}')
    for layer in ('rgb', 'ndvi'):
        shutil.copy2(stage / f'{layer}_{month}.png', md_path.parent / f'{layer}_{month}.png')
    target['timeseries'][i] = result
    md['dates'][mi] = result
    md.setdefault('ingest_notes', []).append({'month': month, 'source': 'local Sentinel-2 L2A scientific TIFF',
                                            'rule': 'missing registry observation only; exact month; no substitution', 'version': VERSION})
    write_json(md_path, md)
    write_json(ts_path, current)
    return ts_path.read_bytes()


def previous_batch_recheck(inventory_csv, previous_ingest, catalog, scenes, results):
    old_bands = defaultdict(set)
    members = defaultdict(list)
    with inventory_csv.open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            path = row['path']
            if not path.lower().endswith('.tif') or path.startswith('__MACOSX/') or '/._' in path:
                continue
            parsed = parse_source(path, catalog)
            if parsed['mapping_status'] != 'RESOLVED':
                continue
            key = (parsed['registry_plot_id'], parsed['month'], parsed['scene_id'])
            old_bands[key].add(parsed['band'])
            members[key].append({'archive': row['zip'], 'member': path})
    current = defaultdict(list)
    for scene in scenes:
        current[(scene['plot_id'], scene['month'], scene['scene_id'])].append(scene)
    partials = []
    for key, bands in sorted(old_bands.items()):
        if set(BANDS) <= bands:
            continue
        xs = current[key]
        now = set().union(*(set(s['assets']) for s in xs)) if xs else set()
        partials.append({'plot_id': key[0], 'code': display_code(catalog[key[0]]), 'month': key[1], 'scene_id': key[2],
                         'previous_missing_bands': sorted(set(BANDS) - bands), 'local_missing_bands': sorted(set(BANDS) - now),
                         'result': 'UPGRADED_COMPLETE' if any(s['complete'] for s in xs) else ('STILL_PARTIAL' if xs else 'NOT_FOUND_LOCALLY'),
                         'local_source_groups': [s['source_group'] for s in xs], 'previous_source_members': members[key]})
    new_by = {(r['plot_id'], r['month']): r for r in results}
    previous = []
    for old in read_json(previous_ingest)['records']:
        if old['result'] == 'ACCEPTED':
            continue
        key = (old['plot_id'], old['month'])
        now = new_by.get(key)
        if now is None:
            previous.append({'plot_id': key[0], 'code': old['code'], 'month': key[1], 'previous_result': old['result'],
                             'result': 'EXISTING_REGISTRY_OBSERVATION'})
            continue
        previous.append({'plot_id': key[0], 'code': old['code'], 'month': key[1], 'previous_result': old['result'],
                         'previous_scene_ids': old['scenes'], 'local_scene_ids': now['source_scene_ids'],
                         'result': now['result'], 'coverage_pct': now.get('coverage_pct'),
                         'new_scene_ids': sorted(set(now['source_scene_ids']) - set(old['scenes']))})
    return {'evidence': {'inventory_csv_sha256': file_hash(inventory_csv), 'ingest_report_sha256': file_hash(previous_ingest)},
            'previous_partial_count': len(partials), 'partial_results': dict(sorted(Counter(r['result'] for r in partials).items())),
            'partial_scenes': partials, 'previous_missing_count': len(previous),
            'missing_results': dict(sorted(Counter(r['result'] for r in previous).items())), 'missing_records': previous}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--index', type=Path, default=R / '.local/satellite-source-index.sqlite')
    parser.add_argument('--report-dir', type=Path, default=R / 'audit-artifacts/local-satellite-ingest')
    parser.add_argument('--reuse-index', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--previous-inventory', type=Path, help='prior audit CSV, not raw source')
    parser.add_argument('--previous-ingest', type=Path, help='prior missing-ingest JSON report')
    args = parser.parse_args()
    root = args.source_dir.resolve()
    if not root.is_dir():
        raise RuntimeError('source directory does not exist')
    catalog_list = read_json(R / 'data/plots_catalog.json')
    catalog = {int(p['id']): p for p in catalog_list}
    if len(catalog_list) != 210 or len(catalog) != 210:
        raise RuntimeError('expected exactly 210 unique registry identities')
    series_list = read_json(R / 'data/timeseries_verified_12.json')
    series = {int(p['id']): p for p in series_list}
    if series.keys() != catalog.keys() or any(tuple(o['month'] for o in p['timeseries']) != MONTHS for p in series.values()):
        raise RuntimeError('registry/series identities or declared months differ')
    pdd = {p['code']: p for p in read_json(R / 'data/pdd22/plots_catalog.json')}
    records, inventory = build_index(root, args.index, catalog, pdd, args.reuse_index, args.workers)
    scenes, unresolved = reconcile_scenes(records)
    byslot = defaultdict(list)
    for s in scenes:
        byslot[(s['plot_id'], s['month'])].append(s)
    report = args.report_dir
    raster_rows = [r for r in records if r.get('band') in BANDS]
    source_inventory = {**{k: v for k, v in inventory.items() if k != 'archives'},
                        'processing_version': VERSION, 'integrity_counts': dict(sorted(Counter(r['integrity_status'] for r in records).items())),
                        'resolved_plots': len({r['registry_plot_id'] for r in raster_rows if r['mapping_status'] == 'RESOLVED'}),
                        'unique_scientific_checksums': len({r['checksum'] for r in raster_rows}),
                        'non_scientific_files': [{k: r[k] for k in ('source_id', 'filesize', 'checksum', 'integrity_status')}
                                                 for r in records if not r.get('band')],
                        'source_manifest_sha256': digest([{'source_id': r['source_id'], 'checksum': r['checksum']} for r in records])}
    write_json(report / 'source_inventory.json', source_inventory)
    write_json(report / 'archive_integrity.json', {**{k: inventory[k] for k in ('zip_count', 'zip_valid', 'zip_corrupt', 'zip_duplicate_source', 'total_members', 'archive_scientific_tifs')},
                                                 'archives': inventory['archives'], 'note': 'No ZIP under source root means archive integrity is not available; extracted raster decoding and SHA-256 are audited separately.'})
    write_scene_manifest(report / 'scene_manifest.json', scenes)
    write_json(report / 'unresolved_sources.json', unresolved)
    write_json(report / 'partial_scenes.json', [public_scene(s) for s in scenes if not s['complete']])
    scope_counts = dict(sorted(Counter(s['scope'] for s in scenes).items()))
    write_json(report / 'scope_reconciliation.json', {'counts': scope_counts, 'unit': 'source scene representation',
                                                     'rule': 'all required-band footprints must contain at least 99.9% of registry geometry; partial scope held',
                                                     'records': [{k: s[k] for k in ('plot_id', 'code', 'month', 'scene_id', 'scope', 'registry_footprint_coverage_min', 'pdd_footprint_coverage_min', 'usable_source', 'dedup_action')} for s in scenes]})
    pdd_rows = []
    for s in scenes:
        if s['code'] in pdd:
            path = R / 'data/pdd22_satellite/plots' / s['code'] / 'metadata.json'
            pm = read_json(path) if path.exists() else {}
            po = next((o for o in pm.get('observations', []) if o.get('month') == s['month']), {})
            pkeys = [acquisition_key(x) for x in po.get('selected_scene_ids', [])]
            pdd_rows.append({'plot_id': s['plot_id'], 'code': s['code'], 'month': s['month'], 'scene_id': s['scene_id'],
                             'scope': s['scope'], 'same_acquisition_in_pdd': s['acquisition_key'] in pkeys,
                             'action': 'KEEP_REGISTRY_SOURCE' if s['scope'] == 'REGISTRY_CONTAINED' else 'HOLD_FOR_REVIEW',
                             'reason': 'PDD required scientific-band and output-footprint equivalence is not proven; no PDD imagery substitution or deduplication'})
    write_json(report / 'pdd_dedup_report.json', {'skipped_pdd_duplicates': 0, 'records': pdd_rows})
    manifest, candidates = [], []
    for pid in sorted(catalog):
        for obs in series[pid]['timeseries']:
            month = obs['month']
            sources = byslot.get((pid, month), [])
            eligible = [s for s in sources if s['usable_source']]
            category = 'EXISTING_REGISTRY_OBSERVATION' if usable(obs) else (
                'MISSING_OBSERVATION_HAS_CANDIDATE' if eligible else (
                    'PDD_ONLY_FOOTPRINT' if sources and all(s['scope'] == 'PDD_ONLY_FOOTPRINT' for s in sources) else 'NO_COMPLETE_SOURCE'))
            row = {'plot_id': pid, 'code': display_code(catalog[pid]), 'month': month,
                   'repo_status_before': obs['status'], 'repo_coverage_before': obs.get('clear_pixel_pct'),
                   'existing_scene_ids': obs.get('scene_ids', []), 'category': category,
                   'source_scene_ids': sorted({s['scene_id'] for s in sources}), 'eligible_scene_ids': [s['scene_id'] for s in eligible],
                   'source_scopes': sorted({s['scope'] for s in sources})}
            manifest.append(row)
            if not usable(obs):
                candidates.append(row)
    write_json(report / 'plot_month_manifest.json', manifest)
    write_json(report / 'missing_candidates.json', candidates)
    print(f'Reconciliation: {len(byslot)} source plot-months; {len(candidates)} missing registry slots; {sum(bool(r["eligible_scene_ids"]) for r in candidates)} with eligible exact-month source', flush=True)
    radiometry = validate_radiometry(scenes, catalog, series)
    write_json(report / 'radiometric_validation.json', radiometry)
    print('Radiometry:', json.dumps({k: v for k, v in radiometry.items() if k != 'rows'}), flush=True)
    if radiometry['status'] != 'PASS':
        raise RuntimeError('radiometric validation failed; reports preserved, observations untouched')
    before = sum(o['status'] in OBSERVED for p in series.values() for o in p['timeseries'])
    stage_root = R / '.local/local-satellite-staging'
    stage_root.mkdir(parents=True, exist_ok=True)
    initial_bytes = (R / 'data/timeseries_verified_12.json').read_bytes()
    preserved = {f'{pid}|{o["month"]}': digest(o) for pid, p in series.items() for o in p['timeseries'] if usable(o)}
    old_assets = {key: {'observation_sha256': checksum,
                       'derived_assets': {layer: file_hash(R / 'data/plots' / key.split('|')[0] / f'{layer}_{key.split("|")[1]}.png')
                                          for layer in ('rgb', 'ndvi')}} for key, checksum in preserved.items()}
    write_json(report / 'existing_observation_fingerprints.json', {
        'base_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=R, text=True).strip(),
        'count': len(preserved), 'observations': old_assets})
    results = []
    accepted = 0
    timestamp = datetime.now(timezone.utc).isoformat()
    for row in candidates:
        pid, month = row['plot_id'], row['month']
        chosen = [s for s in byslot.get((pid, month), []) if s['usable_source']]
        rec = {**row, 'result': row['category'] if row['category'] != 'MISSING_OBSERVATION_HAS_CANDIDATE' else 'NO_COMPLETE_SOURCE'}
        if chosen:
            for s in chosen:
                for record in s['assets'].values():
                    verify_source_unchanged(record)
            stage = stage_root / str(pid)
            result = process_local(catalog[pid], chosen, output_dir=stage, write_assets=args.apply)
            coverage = result.get('clear_pixel_pct', 0)
            rec['coverage_pct'] = coverage
            rec['scenes_used'] = result['scene_ids']
            rec['result'] = 'NO_CLEAR_SCENE' if result['status'] == 'no_data' else ('LOW_COVERAGE' if not usable(result) else 'ACCEPTED')
            if usable(result):
                used = [s for s in chosen if s['scene_id'] in result['scene_ids']]
                provenance = {'version': VERSION, 'processing_version': v4.PROXY_VERSION, 'ingested_at': timestamp,
                              'registry_plot_id': pid, 'registry_code': display_code(catalog[pid]), 'exact_month': month,
                              'scope': 'REGISTRY', 'scope_classification': 'REGISTRY_CONTAINED',
                              'reflectance_formula': 'DN / 10000', 'source_manifest_sha256': source_inventory['source_manifest_sha256'],
                              'scenes': [{'scene_id': s['scene_id'], 'acquisition_datetime': s['acquisition_datetime'], 'source_fingerprint': s['fingerprint'],
                                          'assets': {b: {'source_id': r['source_id'], 'original_filename': Path(r['member_path'] or r['source_id']).name,
                                                         'member_path': r['member_path'], 'sha256': r['checksum'], 'filesize': r['filesize'],
                                                         'raster_signature': raster_signature(r)} for b, r in sorted(s['assets'].items())}} for s in used]}
                result['ingest_provenance'] = 'local scientific TIFF; exact month; registry scope'
                result['source_provenance'] = provenance
                rec['source_provenance'] = provenance
                if args.apply:
                    md_path = R / 'data/plots' / str(pid) / 'metadata.json'
                    next_bytes = ingest_slot(pid, month, result, stage, initial_bytes, md_path.read_bytes())
                    if next_bytes is None:
                        rec['result'] = 'EXISTING_REGISTRY_OBSERVATION'
                    else:
                        initial_bytes = next_bytes
                        accepted += 1
                        rec['derived_assets'] = {layer: {'path': f'data/plots/{pid}/{layer}_{month}.png',
                                                       'sha256': file_hash(R / 'data/plots' / str(pid) / f'{layer}_{month}.png')}
                                                 for layer in ('rgb', 'ndvi')}
                else:
                    rec['result'] = 'USABLE_DRY_RUN'
        results.append(rec)
        print(f'{pid} {month}: {rec["result"]} {rec.get("coverage_pct", "")}', flush=True)
    final_series = {int(p['id']): p for p in read_json(R / 'data/timeseries_verified_12.json')}
    for key, old_digest in preserved.items():
        pid, month = key.split('|')
        obs = next(o for o in final_series[int(pid)]['timeseries'] if o['month'] == month)
        if digest(obs) != old_digest:
            raise RuntimeError(f'existing usable observation altered: {key}')
    if accepted:
        subprocess.run([sys.executable, str(R / 'tests/build_all_plots_visual_qa.py')], cwd=R, check=True)
        shutil.copy2(R / 'audit-artifacts/all_plots_visual_qa.json', R / 'data/all_plots_visual_qa.json')
    counts = dict(sorted(Counter(r['result'] for r in results).items()))
    after = sum(o['status'] in OBSERVED for p in final_series.values() for o in p['timeseries'])
    summary = {**source_inventory, 'plot_months': len(byslot), 'complete_scenes': sum(s['complete'] for s in scenes),
               'partial_scenes': sum(not s['complete'] for s in scenes), 'scope_counts': scope_counts,
               'complete_scope_counts': dict(sorted(Counter(s['scope'] for s in scenes if s['complete']).items())),
               'unresolved_scope': sum(s['scope'] not in {'REGISTRY_CONTAINED', 'PDD_ONLY_FOOTPRINT'} for s in scenes),
               'source_dedup_actions': dict(sorted(Counter(s['dedup_action'] for s in scenes).items())),
               'all_zero_scene_count': sum(bool(s['all_zero_bands']) for s in scenes),
               'all_zero_band_count': sum(len(s['all_zero_bands']) for s in scenes),
               'eligible_registry_scenes': sum(s['usable_source'] for s in scenes),
               'unresolved_sources': len(unresolved), 'missing_candidates_before': len(candidates),
               'missing_with_eligible_source': sum(bool(r['eligible_scene_ids']) for r in candidates),
               'newly_accepted': accepted, 'result_counts': counts, 'still_missing': sum(not usable(o) for p in final_series.values() for o in p['timeseries']),
               'observed_before': before, 'observed_after': after, 'derived_rgb_added': accepted, 'derived_ndvi_added': accepted,
               'existing_usable_observations_preserved': len(preserved), 'mode': 'apply' if args.apply else 'audit',
               'qa_summary': read_json(R / 'data/all_plots_visual_qa.json')['summary']}
    write_json(report / 'ingest_result.json', {'counts': counts, 'accepted': accepted, 'records': results})
    write_json(report / 'final_summary.json', summary)
    if args.previous_inventory and args.previous_ingest:
        write_json(report / 'previous_batch_recheck.json', previous_batch_recheck(args.previous_inventory, args.previous_ingest, catalog, scenes, results))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
