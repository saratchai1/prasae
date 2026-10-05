#!/usr/bin/env python3
"""Offline regressions for metadata identity, nodata and native DN radiometry."""
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import ingest_antigravity_satellite as ingest

SID = 'S2C_MSIL2A_20250902T033551_N0511_R061_T47PRQ_20250902T085021'


class NativeRadiometry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        assets, self.sidecar = {}, {'s2_product_uri': SID + '.SAFE', 'processing_baseline': '05.11', 'platform': 'sentinel-2c'}
        for band, key in ingest.ASSET_KEYS.items():
            rb = {'nodata': 0, 'data_type': 'uint8' if band == 'SCL' else 'uint16'}
            if band != 'SCL':
                rb.update(scale=.0001, offset=-.1)
            assets[key] = {'href': 'https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/test/' + band + '.tif',
                           'raster:bands': [rb], 'eo:bands': [{'name': band}]}
            for suffix in ('scale', 'offset', 'nodata'):
                self.sidecar[f'{band}_{suffix}'] = rb.get(suffix)
        self.item = {'id': 'S2C_T47PRQ_20250902T034917_L2A', 'collection': 'sentinel-2-c1-l2a', 'assets': assets,
                     'properties': {'s2:product_uri': SID + '.SAFE', 's2:processing_baseline': '05.11',
                                    'platform': 'sentinel-2c', 'datetime': '2025-09-02T03:54:52Z'}}
        self.save()

    def save(self):
        for path, obj in ((self.root / f'source-items/earth-search/{SID}.json', self.item),
                          (self.root / f'metadata/{SID}/radiometry.json', self.sidecar)):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(obj))

    def test_offset_is_applied_after_scale_and_nodata_stays_missing(self):
        path = self.root / 'B04.tif'
        transform = from_origin(100, 13, .0001, .0001)
        with rasterio.open(path, 'w', driver='GTiff', height=2, width=2, count=1, dtype='uint16', crs='EPSG:4326', transform=transform) as ds:
            ds.write(np.array([[0, 1000], [2000, 500]], dtype='uint16'), 1)
        record = {'source_path': str(path), 'archive_path': None,
                  'radiometry': ingest.metadata_profile(self.root, SID)['assets']['B04']}
        grid = SimpleNamespace(height=2, width=2, transform=transform)
        actual = ingest.read_native_asset(SimpleNamespace(assets={'B04': record}), 'B04', grid, Resampling.bilinear)
        self.assertTrue(np.isnan(actual[0, 0]))
        np.testing.assert_allclose(actual.flat[1:], [0, .1, -.05], atol=1e-7)

    def test_scl_is_categorical_without_offset(self):
        path = self.root / 'SCL.tif'
        transform = from_origin(100, 13, .0001, .0001)
        with rasterio.open(path, 'w', driver='GTiff', height=2, width=2, count=1, dtype='uint8', crs='EPSG:4326', transform=transform) as ds:
            ds.write(np.array([[0, 4], [6, 9]], dtype='uint8'), 1)
        rec = {'source_path': str(path), 'archive_path': None,
               'radiometry': ingest.metadata_profile(self.root, SID)['assets']['SCL']}
        actual = ingest.read_native_asset(SimpleNamespace(assets={'SCL': rec}), 'SCL', SimpleNamespace(height=2, width=2, transform=transform), Resampling.nearest)
        self.assertTrue(np.isnan(actual[0, 0]))
        np.testing.assert_array_equal(actual.flat[1:], [4, 6, 9])

    def test_missing_offset_cannot_inherit_default(self):
        del self.item['assets']['red']['raster:bands'][0]['offset']
        self.save()
        with self.assertRaises(KeyError):
            ingest.metadata_profile(self.root, SID)

    def test_conflicting_sidecar_stops_before_processing(self):
        self.sidecar['B04_offset'] = 0
        self.save()
        with self.assertRaisesRegex(ValueError, 'conflicting radiometry'):
            ingest.metadata_profile(self.root, SID)

    def test_wrong_product_or_month_is_held(self):
        self.item['properties']['s2:product_uri'] = SID.replace('20250902', '20250912') + '.SAFE'
        self.save()
        with self.assertRaisesRegex(ValueError, 'product URI'):
            ingest.metadata_profile(self.root, SID)
        self.item['properties']['s2:product_uri'] = SID + '.SAFE'
        self.item['properties']['datetime'] = '2025-08-02T03:54:52Z'
        self.save()
        with self.assertRaisesRegex(ValueError, 'sensing month'):
            ingest.metadata_profile(self.root, SID)

    def test_harmonized_flag_prevents_double_offset(self):
        self.item['properties']['earthsearch:boa_offset_applied'] = True
        self.save()
        with self.assertRaisesRegex(ValueError, 'already harmonized'):
            ingest.metadata_profile(self.root, SID)

    def test_transformed_export_is_not_treated_as_native_dn(self):
        profiles = {SID: ingest.metadata_profile(self.root, SID)}
        rec = {'source_id': 'prepared/inputs/B04.tif', 'dtype': 'uint16', 'scales': [.0001], 'offsets': [-.1], 'nodata': None}
        with self.assertRaisesRegex(ValueError, 'already carries'):
            ingest.bind_radiometry([{'scene_id': SID, 'assets': {'B04': rec}}], profiles)


    def test_changed_exporter_needs_a_fresh_encoding_audit(self):
        path = self.root / 'scripts/sentinel_pipeline.py'
        path.parent.mkdir()
        path.write_text('# unknown encoder')
        with patch.object(sys, 'argv', ['ingest', '--source-dir', str(self.root)]):
            with self.assertRaisesRegex(ValueError, 'new encoding audit'):
                ingest.main()

    def test_new_qa_does_not_change_old_water_reference_or_admit_mixed_radiometry(self):
        previous = {'version': 'old', 'observations': {
            '1|2023-09': {'status': 'CLEAR', 'other_good_month_water_median_pct': 10},
            '1|2024-09': {'status': 'INSUFFICIENT'},
            '2|2024-09': {'status': 'INSUFFICIENT'}}, 'summary': {}}
        computed = {'observations': {
            '1|2023-09': {'status': 'TIDE_WATER_REVIEW', 'other_good_month_water_median_pct': 80},
            '1|2024-09': {'status': 'CLEAR', 'coverage_pct': 100},
            '2|2024-09': {'status': 'INSUFFICIENT', 'coverage_pct': 12}}}
        with patch.object(ingest, 'R', self.root), patch.object(ingest.subprocess, 'run'), \
             patch.object(ingest.local, 'read_json', return_value=computed), patch.object(ingest.local, 'write_json') as writer:
            ingest.refresh_accepted_qa(['1|2024-09', '2|2024-09'], previous)
        output = writer.call_args.args[1]
        self.assertEqual(output['observations']['1|2023-09'], {'status': 'CLEAR', 'other_good_month_water_median_pct': 10})
        self.assertEqual(output['observations']['1|2024-09']['status'], 'RADIOMETRY_REVIEW')
        self.assertEqual(output['observations']['1|2024-09']['visual_screening_status'], 'CLEAR')
        self.assertEqual(output['observations']['2|2024-09']['status'], 'INSUFFICIENT')
        self.assertEqual(output['summary'], {'CLEAR': 1, 'INSUFFICIENT': 1, 'RADIOMETRY_REVIEW': 1})


if __name__ == '__main__':
    unittest.main()
