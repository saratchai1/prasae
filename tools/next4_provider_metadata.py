"""Product-bound radiometry for the reviewed native crops in inputs-next-4.

This module reads saved metadata only. It never downloads a scene, signs a URL,
or changes source files. Planetary Computer's TIFF crops omit scale/offset tags,
so its exact-product ESA XML supplies quantification and per-band offsets. Earth
Search supplies explicit raster:bands metadata. The delivery's nested sidecars
must agree with the independent provider metadata in both cases.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

BANDS = ('B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12', 'SCL')
ASSET_KEYS = dict(zip(BANDS, ('blue', 'green', 'red', 'rededge1', 'rededge2',
                           'rededge3', 'nir', 'nir08', 'swir16', 'swir22', 'scl')))
XML_BAND_IDS = dict(zip(BANDS[:-1], (1, 2, 3, 4, 5, 6, 7, 8, 11, 12)))
SCENE_RE = re.compile(r'S2([ABC])_MSIL2A_(\d{8})T\d{6}_N(\d{4})_R\d{3}_T\d{2}[A-Z]{3}_\d{8}T\d{6}')
REVIEWED_EXPORTERS = {
    'scripts/campaign_pc.py': 'fb6ace7ae29e2910dbe3b964acbc8d5a314f5240b59cf4f9a74a9c11197b627c',
    'scripts/campaign_v2.py': '7c70c399885f8a0ea2640f58b08660206c610a9c864352ed025659efc3566025',
    'scripts/downloader.py': 'cc65aacbf6e85b67d74222eedf98672cc6d1c0d4cb2d768af9e1025606c70a38',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def finite(value, name, *, positive=False):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), f'{name}: finite numeric value required')
    require(not positive or value > 0, f'{name}: positive value required')
    return float(value)


def audit_exporters(root):
    """Fail closed if the reviewed copy/crop implementation changes."""
    root = Path(root)
    scripts = []
    for source_id, expected in REVIEWED_EXPORTERS.items():
        path = root / source_id
        require(path.is_file(), f'reviewed exporter missing: {source_id}')
        actual = file_hash(path)
        require(actual == expected, f'exporter encoding needs a new audit: {source_id}')
        scripts.append({'source_id': source_id, 'checksum': actual})
    return {'status': 'PASS', 'scripts': scripts,
            'encoding': 'uint16 native DN crop/copy; no pixel scale or offset applied',
            'tiff_tag_rule': 'default tags or tags exactly matching provider metadata; raw DN is decoded once'}


def parse_product_metadata(xml_bytes, scene_id, processing_baseline):
    """Validate critical ESA L2A XML nodes and derive native band radiometry."""
    match = SCENE_RE.fullmatch(scene_id)
    require(match is not None, 'invalid exact product identifier')
    try:
        tree = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError('invalid product metadata XML') from exc
    local_name = lambda element: element.tag.rsplit('}', 1)[-1]

    def unique_text(name):
        values = {element.text.strip() for element in tree.iter()
                  if local_name(element) == name and element.text and element.text.strip()}
        require(len(values) == 1, f'XML {name}: one explicit value required')
        return next(iter(values))

    product = unique_text('PRODUCT_URI')
    baseline = unique_text('PROCESSING_BASELINE')
    require(product == scene_id + '.SAFE', 'XML product URI mismatch')
    require(baseline == processing_baseline, 'XML/STAC processing baseline mismatch')
    require(baseline.replace('.', '') == match[3], 'XML product identifier baseline mismatch')
    try:
        quantification = finite(float(unique_text('BOA_QUANTIFICATION_VALUE')),
                                'BOA quantification', positive=True)
        offsets = {}
        for element in tree.iter():
            if local_name(element) == 'BOA_ADD_OFFSET':
                require('band_id' in element.attrib and element.text, 'XML band offset identity missing')
                band_id = int(element.attrib['band_id'])
                require(band_id not in offsets, 'duplicate XML band offset')
                offsets[band_id] = finite(float(element.text), f'XML band {band_id} offset')
        special_values = {}
        for element in tree.iter():
            if local_name(element) == 'Special_Values':
                parts = {local_name(child): child.text.strip() for child in element if child.text}
                name = parts.get('SPECIAL_VALUE_TEXT')
                index = parts.get('SPECIAL_VALUE_INDEX')
                require(name is not None and index is not None, 'XML special value incomplete')
                require(name not in special_values, 'duplicate XML special value')
                special_values[name] = finite(float(index), f'XML special value {name}')
    except (TypeError, KeyError, OverflowError) as exc:
        raise ValueError('invalid numeric product metadata') from exc
    require(all(band_id in offsets for band_id in XML_BAND_IDS.values()), 'XML per-band BOA offset missing')
    require(special_values.get('NODATA') == 0, 'XML native nodata 0 required')
    assets = {band: {'scale': 1.0 / quantification,
                     'offset': offsets[band_id] / quantification,
                     'nodata': special_values['NODATA'], 'band_id': band_id,
                     'boa_add_offset': offsets[band_id], 'native_dtype': 'uint16',
                     'formula': '(DN + BOA_ADD_OFFSET) / BOA_QUANTIFICATION_VALUE'}
              for band, band_id in XML_BAND_IDS.items()}
    assets['SCL'] = {'scale': 1, 'offset': 0, 'nodata': special_values['NODATA'],
                     'native_dtype': 'uint8', 'formula': 'SCL categorical'}
    return {'status': 'PASS', 'product_uri': product, 'processing_baseline': baseline,
            'boa_quantification_value': quantification,
            'boa_offsets_by_band_id': {str(key): value for key, value in sorted(offsets.items())},
            'special_values': special_values, 'assets': assets,
            'critical_nodes': {'PRODUCT_URI': product, 'PROCESSING_BASELINE': baseline,
                               'BOA_QUANTIFICATION_VALUE': quantification,
                               'BOA_ADD_OFFSET': {str(key): value for key, value in sorted(offsets.items())},
                               'Special_Values': special_values}}


def metadata_profile(root, provider, scene_id, metadata_dir):
    """Return a portable profile for one provider/product; XML stays auxiliary.

    ``metadata_dir`` contains provider-metadata/planetary-computer/<scene>.xml.
    The returned XML source identity is relative to that auxiliary evidence root.
    All delivery metadata identities are relative to ``root``. Provider/product
    keys remain separate even when both providers serve the same exact product.
    """
    root, metadata_dir = Path(root), Path(metadata_dir)
    require(provider in ('earth-search', 'planetary-computer'), 'unsupported provider')
    match = SCENE_RE.fullmatch(scene_id)
    require(match is not None, 'invalid exact product identifier')
    stac_path = root / 'source-items' / provider / (scene_id + '.json')
    sidecar_path = (root / 'metadata' / scene_id / 'radiometry.json' if provider == 'earth-search'
                    else root / 'metadata' / provider / scene_id / 'radiometry.json')
    item = json.loads(stac_path.read_text(encoding='utf-8'))
    sidecar = json.loads(sidecar_path.read_text(encoding='utf-8'))
    properties = item['properties']
    collection = 'sentinel-2-c1-l2a' if provider == 'earth-search' else 'sentinel-2-l2a'
    require(item['collection'] == collection, 'provider collection mismatch')
    require(properties['s2:product_uri'] == scene_id + '.SAFE', 'STAC product URI mismatch')
    require(properties['datetime'][:7] == match[2][:4] + '-' + match[2][4:6], 'STAC sensing month mismatch')
    baseline = properties['s2:processing_baseline']
    require(baseline.replace('.', '') == match[3], 'STAC identifier baseline mismatch')
    require(properties['platform'].lower().replace('-', '') == 'sentinel2' + match[1].lower(),
            'STAC spacecraft mismatch')
    for flag in ('earthsearch:boa_offset_applied', 'earthsearch:reflectance_offset_applied'):
        require(not properties.get(flag), 'already harmonized source needs an independent encoding audit')
    proof = {'profile_key': provider + '|' + scene_id, 'provider': provider, 'scene_id': scene_id,
             'stac_item_id': item['id'], 'collection': collection,
             'product_uri': properties['s2:product_uri'], 'sensing_datetime': properties['datetime'],
             'processing_baseline': baseline, 'platform': properties['platform'],
             'catalog_cloud_cover_pct': properties.get('eo:cloud_cover'),
             'metadata_source_id': stac_path.relative_to(root).as_posix(),
             'metadata_sha256': file_hash(stac_path),
             'radiometry_sidecar_source_id': sidecar_path.relative_to(root).as_posix(),
             'radiometry_sidecar_sha256': file_hash(sidecar_path), 'assets': {}}
    xml = None
    if provider == 'planetary-computer':
        source_id = 'provider-metadata/planetary-computer/' + scene_id + '.xml'
        path = metadata_dir / source_id
        xml_bytes = path.read_bytes()
        xml = parse_product_metadata(xml_bytes, scene_id, baseline)
        url = item['assets']['product-metadata']['href']
        require('?' not in url and url.startswith('https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/')
                and '/' + scene_id + '.SAFE/MTD_MSIL2A.xml' in url, 'product XML asset identity mismatch')
        proof.update(product_metadata_source_id=source_id,
                     product_metadata_sha256=hashlib.sha256(xml_bytes).hexdigest(),
                     product_metadata_filesize=len(xml_bytes), product_metadata_url=url,
                     product_metadata_proof={key: value for key, value in xml.items() if key != 'assets'})
    for band in BANDS:
        key = ASSET_KEYS[band] if provider == 'earth-search' else band
        asset = item['assets'][key]
        href = asset['href']
        require('?' not in href, f'{band}: signed asset URL cannot enter provenance')
        if provider == 'earth-search':
            require(href.startswith('https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/')
                    and Path(href).name == band + '.tif', f'{band}: native Earth Search asset identity mismatch')
        else:
            require(href.startswith('https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/')
                    and '/' + scene_id + '.SAFE/' in href
                    and re.search(r'_' + band + r'_\d+m\.tif$', href), f'{band}: native PC asset identity mismatch')
        if band != 'SCL':
            require([entry['name'] for entry in asset['eo:bands']] == [band], f'{band}: eo:bands mismatch')
        side = sidecar['assets'][band]
        raster_bands = asset.get('raster:bands')
        if provider == 'earth-search':
            require(raster_bands is not None and len(raster_bands) == 1, f'{band}: explicit raster metadata required')
            rb = raster_bands[0]
            require('nodata' in rb, f'{band}: nodata metadata missing')
            scale = rb.get('scale', 1) if band == 'SCL' else rb['scale']
            offset = rb.get('offset', 0) if band == 'SCL' else rb['offset']
            info = {'scale': scale, 'offset': offset, 'nodata': rb['nodata'],
                    'native_dtype': rb['data_type'], 'formula': 'SCL categorical' if band == 'SCL' else 'DN * scale + offset'}
        else:
            info = dict(xml['assets'][band])
            if raster_bands is not None:
                require(len(raster_bands) == 1, f'{band}: expected one raster band')
                require(all(key not in raster_bands[0] or raster_bands[0][key] == info[key]
                            for key in ('scale', 'offset', 'nodata')), f'{band}: STAC/XML radiometry conflict')
        finite(info['scale'], f'{band} scale', positive=True)
        finite(info['offset'], f'{band} offset')
        finite(info['nodata'], f'{band} nodata')
        require(info['nodata'] == 0, f'{band}: native nodata 0 required')
        require(info['native_dtype'] == ('uint8' if band == 'SCL' else 'uint16'), f'{band}: native datatype mismatch')
        require(all(side.get(key) == info[key] for key in ('scale', 'offset', 'nodata', 'native_dtype')),
                f'{band}: sidecar conflicts with independent provider metadata')
        if band == 'SCL':
            require(info['scale'] == 1 and info['offset'] == 0, 'SCL must remain categorical')
        proof['assets'][band] = {**info, 'asset_key': key, 'provider': provider, 'native_asset_url': href,
                                **{key: proof[key] for key in ('metadata_source_id', 'metadata_sha256',
                                     'radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')}}
        if xml:
            proof['assets'][band].update(product_metadata_source_id=proof['product_metadata_source_id'],
                                        product_metadata_sha256=proof['product_metadata_sha256'])
    return proof
