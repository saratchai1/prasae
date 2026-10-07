#!/usr/bin/env python3
"""Offline regressions for product XML, provider identity and native crop grids."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import audit_next4_satellite as audit
import next4_provider_metadata as metadata

SID = 'S2C_MSIL2A_20250902T033551_N0511_R061_T47PRQ_20250902T085021'


def xml_fixture():
    offsets = ''.join(f'<BOA_ADD_OFFSET band_id="{index}">-1000</BOA_ADD_OFFSET>'
                      for index in range(13))
    return (f'<Product><PRODUCT_URI>{SID}.SAFE</PRODUCT_URI>'
            '<PROCESSING_BASELINE>05.11</PROCESSING_BASELINE>'
            '<BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE>'
            f'<BOA_ADD_OFFSET_VALUES_LIST>{offsets}</BOA_ADD_OFFSET_VALUES_LIST>'
            '<Special_Values><SPECIAL_VALUE_TEXT>NODATA</SPECIAL_VALUE_TEXT>'
            '<SPECIAL_VALUE_INDEX>0</SPECIAL_VALUE_INDEX></Special_Values>'
            '</Product>').encode()


class ProviderMetadata(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.auxiliary = self.root / 'auxiliary'
        self.items = {}
        for provider in ('planetary-computer', 'earth-search'):
            assets, sidecar = {}, {'assets': {}}
            for band in metadata.BANDS:
                scl = band == 'SCL'
                key = band if provider == 'planetary-computer' else metadata.ASSET_KEYS[band]
                dtype = 'uint8' if scl else 'uint16'
                scale, offset = (1, 0) if scl else (.0001, -.1)
                href = ('https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/test/' + SID +
                        f'.SAFE/IMG_DATA/T47PRQ_20250902T033551_{band}_{20 if scl else 10}m.tif'
                        if provider == 'planetary-computer' else
                        'https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/'
                        'sentinel-2-c1-l2a/test/' + band + '.tif')
                assets[key] = {'href': href, 'eo:bands': [{'name': band}]}
                if provider == 'earth-search':
                    assets[key]['raster:bands'] = [{'scale': scale, 'offset': offset,
                                                  'nodata': 0, 'data_type': dtype}]
                sidecar['assets'][band] = {'scale': scale, 'offset': offset, 'nodata': 0,
                                          'native_dtype': dtype}
            if provider == 'planetary-computer':
                assets['product-metadata'] = {'href':
                    'https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/test/' +
                    SID + '.SAFE/MTD_MSIL2A.xml'}
            item = {'id': provider + '-item', 'collection': 'sentinel-2-l2a' if
                    provider == 'planetary-computer' else 'sentinel-2-c1-l2a',
                    'properties': {'s2:product_uri': SID + '.SAFE',
                                   's2:processing_baseline': '05.11',
                                   'platform': 'Sentinel-2C', 'datetime': '2025-09-02T03:35:51Z'},
                    'assets': assets}
            self.items[provider] = item
            path = self.root / f'source-items/{provider}/{SID}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(item))
            sidepath = (self.root / f'metadata/planetary-computer/{SID}/radiometry.json'
                        if provider == 'planetary-computer' else
                        self.root / f'metadata/{SID}/radiometry.json')
            sidepath.parent.mkdir(parents=True, exist_ok=True)
            sidepath.write_text(json.dumps(sidecar))
        self.xml_path = self.auxiliary / f'provider-metadata/planetary-computer/{SID}.xml'
        self.xml_path.parent.mkdir(parents=True)
        self.xml_path.write_bytes(xml_fixture())

    def test_xml_derives_each_band_offset_and_nodata_without_defaults(self):
        parsed = metadata.parse_product_metadata(xml_fixture(), SID, '05.11')
        self.assertEqual(parsed['boa_quantification_value'], 10000)
        self.assertEqual(parsed['assets']['B8A']['band_id'], 8)
        self.assertEqual(parsed['assets']['B12']['band_id'], 12)
        self.assertEqual(parsed['assets']['B04']['offset'], -.1)
        self.assertEqual(parsed['assets']['B04']['scale'], .0001)
        self.assertEqual(parsed['assets']['B04']['nodata'], 0)
        self.assertEqual(parsed['assets']['SCL']['offset'], 0)

    def test_wrong_xml_product_is_rejected_before_processing(self):
        body = xml_fixture().replace((SID + '.SAFE').encode(), b'other-product.SAFE')
        with self.assertRaisesRegex(ValueError, 'product URI'):
            metadata.parse_product_metadata(body, SID, '05.11')

    def test_wrong_xml_baseline_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'baseline'):
            metadata.parse_product_metadata(xml_fixture(), SID, '05.10')

    def test_missing_per_band_offset_cannot_inherit_another_band(self):
        body = xml_fixture().replace(b'<BOA_ADD_OFFSET band_id="8">-1000</BOA_ADD_OFFSET>', b'')
        with self.assertRaisesRegex(ValueError, 'per-band BOA offset missing'):
            metadata.parse_product_metadata(body, SID, '05.11')

    def test_missing_or_conflicting_nodata_is_rejected(self):
        for replacement in (b'<SPECIAL_VALUE_INDEX>1</SPECIAL_VALUE_INDEX>',
                            b'<SPECIAL_VALUE_INDEX>nan</SPECIAL_VALUE_INDEX>'):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                metadata.parse_product_metadata(xml_fixture().replace(
                    b'<SPECIAL_VALUE_INDEX>0</SPECIAL_VALUE_INDEX>', replacement), SID, '05.11')
        body = xml_fixture().replace(b'<SPECIAL_VALUE_TEXT>NODATA</SPECIAL_VALUE_TEXT>',
                                    b'<SPECIAL_VALUE_TEXT>UNKNOWN</SPECIAL_VALUE_TEXT>')
        with self.assertRaisesRegex(ValueError, 'nodata'):
            metadata.parse_product_metadata(body, SID, '05.11')

    def test_quantification_must_be_explicit_positive_and_finite(self):
        for value in (b'0', b'nan', b'-10000'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metadata.parse_product_metadata(xml_fixture().replace(b'>10000<', b'>' + value + b'<'),
                                                SID, '05.11')

    def test_same_product_in_two_providers_has_independent_bound_profiles(self):
        records = [{'source_id': f'prepared/{prefix}/1-STC/2025-09/{SID}/B04.tif',
                    'scene_id': SID, 'band': 'B04'} for prefix in
                   ('alternative-providers/planetary-computer', 'inputs')]
        profiles, held = audit.load_profiles(self.root, records, self.auxiliary)
        self.assertFalse(held)
        self.assertEqual(set(profiles), {('planetary-computer', SID), ('earth-search', SID)})
        pc, es = profiles[('planetary-computer', SID)], profiles[('earth-search', SID)]
        self.assertNotEqual(pc['profile_key'], es['profile_key'])
        self.assertEqual(pc['product_metadata_sha256'], hashlib.sha256(xml_fixture()).hexdigest())
        self.assertNotIn('product_metadata_sha256', es)
        self.assertEqual(pc['assets']['B04']['asset_key'], 'B04')
        self.assertEqual(es['assets']['B04']['asset_key'], 'red')

    def test_sidecar_cannot_override_independent_xml(self):
        path = self.root / f'metadata/planetary-computer/{SID}/radiometry.json'
        sidecar = json.loads(path.read_text())
        sidecar['assets']['B04']['offset'] = 0
        path.write_text(json.dumps(sidecar))
        with self.assertRaisesRegex(ValueError, 'sidecar conflicts'):
            metadata.metadata_profile(self.root, 'planetary-computer', SID, self.auxiliary)


class NativeCropGrid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.radiometry = {'native_dtype': 'uint16', 'scale': .0001, 'offset': -.1,
                           'nodata': 0, 'asset_key': 'B04'}
        self.asset = {'proj:transform': [10, 0, 500000, 0, -10, 1000000],
                      'proj:shape': [1000, 1000]}
        self.item = {'properties': {'proj:code': 'EPSG:32647'}, 'assets': {'B04': self.asset}}
        self.record = {'crs': 'EPSG:32647', 'transform': [10, 0, 500200, 0, -10, 999800],
                       'width': 60, 'height': 60, 'dtype': 'uint16', 'scales': [1.0],
                       'offsets': [0.0], 'nodata': None}

    def test_shifted_native_origin_is_not_a_valid_crop(self):
        bad = copy.deepcopy(self.record)
        bad['transform'][2] += 5
        with self.assertRaisesRegex(ValueError, 'off original pixel grid'):
            audit.native_grid_proof(bad, self.asset, self.item, self.radiometry)

    def test_resampled_native_resolution_and_outside_windows_are_rejected(self):
        bad = copy.deepcopy(self.record)
        bad['transform'][0] = 9
        with self.assertRaisesRegex(ValueError, 'resampled'):
            audit.native_grid_proof(bad, self.asset, self.item, self.radiometry)
        bad = copy.deepcopy(self.record)
        bad['width'] = 1000
        with self.assertRaisesRegex(ValueError, 'outside original product'):
            audit.native_grid_proof(bad, self.asset, self.item, self.radiometry)

    def test_matching_tiff_transform_tags_describe_raw_dn_and_are_read_once(self):
        transform = from_origin(100, 13, .0001, .0001)
        path = self.root / 'tagged_B04.tif'
        with rasterio.open(path, 'w', driver='GTiff', height=2, width=2, count=1,
                           dtype='uint16', crs='EPSG:4326', transform=transform, nodata=0) as dst:
            dst.write(np.array([[0, 1000], [2000, 500]], dtype='uint16'), 1)
            dst.scales, dst.offsets = (.0001,), (-.1,)
        record = {'crs': 'EPSG:4326', 'transform': list(transform)[:6], 'width': 2, 'height': 2,
                  'dtype': 'uint16', 'nodata': 0, 'scales': [.0001], 'offsets': [-.1],
                  'source_path': str(path), 'archive_path': None, 'radiometry': self.radiometry}
        asset = {'proj:transform': list(transform)[:6], 'proj:shape': [2, 2]}
        proof = audit.native_grid_proof(record, asset, {'properties': {'proj:code': 'EPSG:4326'}},
                                        self.radiometry)
        self.assertTrue(proof['metadata_transform_tags'])
        actual = audit.native.read_native_asset(SimpleNamespace(assets={'B04': record}), 'B04',
                    SimpleNamespace(height=2, width=2, transform=transform), Resampling.bilinear)
        self.assertTrue(np.isnan(actual[0, 0]))
        np.testing.assert_allclose(actual.flat[1:], [0, .1, -.05], atol=1e-7)

    def test_conflicting_tiff_transform_tags_are_rejected(self):
        bad = copy.deepcopy(self.record)
        bad['scales'], bad['offsets'] = [.0001], [0]
        with self.assertRaisesRegex(ValueError, 'transform tags conflict'):
            audit.native_grid_proof(bad, self.asset, self.item, self.radiometry)

    def native_window_fixture(self, *, partial=False):
        records, assets, profiles = [], {}, {}
        transformer = Transformer.from_crs('EPSG:32647', 'EPSG:4326', always_xy=True)
        group = f'prepared/alternative-providers/planetary-computer/1-STC/2025-09/{SID}'
        for band in metadata.BANDS:
            twenty = band not in ('B02', 'B03', 'B04', 'B08')
            resolution, origin, size = (20, (500180, 999820), 32) if twenty else (10, (500200, 999800), 60)
            transform = [resolution, 0, origin[0], 0, -resolution, origin[1]]
            native_asset = {'proj:transform': [resolution, 0, 500000, 0, -resolution, 1000000],
                            'proj:shape': [10000 // resolution, 10000 // resolution]}
            assets[band] = native_asset
            dtype = 'uint8' if band == 'SCL' else 'uint16'
            rad = {'scale': 1 if band == 'SCL' else .0001, 'offset': 0 if band == 'SCL' else -.1,
                   'native_dtype': dtype, 'nodata': 0, 'asset_key': band}
            profiles[band] = rad
            corners = [(origin[0], origin[1]), (origin[0] + size * resolution, origin[1]),
                       (origin[0] + size * resolution, origin[1] - size * resolution),
                       (origin[0], origin[1] - size * resolution), (origin[0], origin[1])]
            footprint = [list(transformer.transform(x, y)) for x, y in corners]
            records.append({'source_id': group + '/' + band + '.tif',
                'relative_id': group + '/' + band + '.tif', 'source_path': str(self.root / (band + '.tif')),
                'archive_path': None, 'member_path': None, 'mapping_status': 'RESOLVED',
                'registry_plot_id': 1, 'registry_code': '1-STC', 'month': '2025-09', 'scene_id': SID,
                'band': band, 'acquisition_datetime': '2025-09-02T03:35:51+00:00', 'satellite': 'S2C',
                'tile': 'T47PRQ', 'checksum': hashlib.sha256(band.encode()).hexdigest(),
                'integrity_status': 'VALID', 'source_scope': 'HOLD_PARTIAL_SCOPE_FOR_REVIEW' if
                partial and band == 'SCL' else 'REGISTRY_CONTAINED',
                'registry_footprint_coverage': .5 if partial and band == 'SCL' else 1.0,
                'pdd_footprint_coverage': None, 'footprint': footprint, 'width': size, 'height': size,
                'crs': 'EPSG:32647', 'transform': transform, 'bounds':
                [origin[0], origin[1] - size * resolution, origin[0] + size * resolution, origin[1]],
                'dtype': dtype, 'scales': [1.0], 'offsets': [0.0], 'nodata': None, 'all_zero': False})
        item = {'properties': {'proj:code': 'EPSG:32647'}, 'assets': assets}
        path = self.root / f'source-items/planetary-computer/{SID}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item))
        profile = {'metadata_source_id': path.relative_to(self.root).as_posix(), 'assets': profiles}
        return records, {('planetary-computer', SID): profile}

    def test_native_10m_20m_crop_edges_are_allowed_after_independent_grid_checks(self):
        records, profiles = self.native_window_fixture()
        scenes, unresolved = audit.reconcile_native_windows(self.root, records, profiles)
        self.assertFalse(unresolved)
        self.assertEqual(len(scenes), 1)
        self.assertTrue(scenes[0]['usable_source'])
        self.assertFalse(scenes[0]['errors'])
        self.assertNotEqual(scenes[0]['assets']['B04']['footprint'], scenes[0]['assets']['SCL']['footprint'])
        self.assertEqual(scenes[0]['native_grid_proofs']['B04']['window'], [20, 20, 60, 60])
        self.assertEqual(scenes[0]['native_grid_proofs']['SCL']['window'], [9, 9, 32, 32])

    def test_native_crop_relaxation_does_not_admit_partial_registry_scope(self):
        records, profiles = self.native_window_fixture(partial=True)
        scenes, unresolved = audit.reconcile_native_windows(self.root, records, profiles)
        self.assertFalse(unresolved)
        self.assertFalse(scenes[0]['usable_source'])
        self.assertNotEqual(scenes[0]['scope'], 'REGISTRY_CONTAINED')


if __name__ == '__main__':
    unittest.main()
