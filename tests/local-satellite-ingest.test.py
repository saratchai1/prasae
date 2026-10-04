#!/usr/bin/env python3
"""Regression gates for local source identity, scope, integrity and write safety."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import ingest_local_satellite as local

SCENE = 'S2A_MSIL2A_20240616T032521_N0510_R018_T47PRP_20240616T091952'


class LocalIngestTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        self.catalog = {1: {'id': 1, 'code': 'PLOT_001', 'name': '1-STC', 'area_rai': 10,
                            'geometry': mapping(box(.002, .002, .008, .008))}}
        self.pdd = {'1-STC': {'geometry': mapping(box(.003, .003, .006, .006))}}

    def tearDown(self):
        self.temp.cleanup()

    def band(self, name, scene=SCENE, bounds=(0, 0, .01, .01)):
        p = self.inputs / '1-STC' / '2024-06' / scene / f'{name}.tif'
        p.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(p, 'w', driver='GTiff', width=16, height=16, count=1, dtype='uint16',
                           crs='EPSG:4326', transform=from_bounds(*bounds, 16, 16), nodata=0) as ds:
            ds.write(np.full((16, 16), 4 if name == 'SCL' else 2000, dtype=np.uint16), 1)
        return p

    def index(self, reuse=False):
        return local.build_index(self.inputs, self.root / 'index.sqlite', self.catalog, self.pdd, reuse=reuse, workers=1)

    def test_month_and_registry_identity_are_exact(self):
        good = local.parse_source(f'1-STC/2024-06/{SCENE}/B02.tif', self.catalog)
        self.assertEqual(good['registry_plot_id'], 1)
        self.assertEqual(good['mapping_status'], 'RESOLVED')
        for identifier in [f'1-STC/2024-03/{SCENE}/B02.tif', f'PLOT_999/2024-06/{SCENE}/B02.tif']:
            self.assertNotEqual(local.parse_source(identifier, self.catalog)['mapping_status'], 'RESOLVED')

    def test_partial_pdd_raster_cannot_replace_registry(self):
        scope, rc, pc = local.classify_footprint(box(.003, .003, .006, .006),
                                               box(.002, .002, .008, .008), box(.003, .003, .006, .006))
        self.assertEqual(scope, 'PDD_ONLY_FOOTPRINT')
        self.assertLess(rc, 1)
        self.assertEqual(pc, 1)
        for b in local.BANDS:
            self.band(b, bounds=(.003, .003, .006, .006))
        rows, _ = self.index()
        scenes, _ = local.reconcile_scenes(rows)
        self.assertTrue(scenes[0]['complete'])
        self.assertFalse(scenes[0]['usable_source'])
        with self.assertRaises(ValueError):
            local.process_local(self.catalog[1], scenes)

    def test_archive_and_extracted_equivalence_prefers_extracted(self):
        paths = [self.band(b) for b in local.BANDS]
        with zipfile.ZipFile(self.inputs / 'same-source.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for p in paths:
                z.write(p, p.relative_to(self.inputs))
        rows, inventory = self.index()
        self.assertEqual(inventory['zip_valid'], 1)
        self.assertEqual(inventory['scientific_tifs'], 22)
        scenes, _ = local.reconcile_scenes(rows)
        self.assertEqual(sum(s['usable_source'] for s in scenes), 1)
        chosen = next(s for s in scenes if s['usable_source'])
        self.assertTrue(all(not r['archive_path'] for r in chosen['assets'].values()))
        self.assertEqual(sum(s['dedup_action'] == 'SKIP_EQUIVALENT_SOURCE' for s in scenes), 1)
        public = local.public_scene(chosen)
        for b, a in public['assets'].items():
            grid = public['raster_grids'][a['grid']]
            self.assertEqual(local.raster_signature({**grid, 'checksum': a['checksum']}), local.raster_signature(chosen['assets'][b]))
        self.assertEqual(self.index(reuse=True)[1], inventory)

    def test_corrupt_zip_is_recorded_without_ingestion(self):
        self.inputs.mkdir()
        p = self.inputs / 'broken.zip'
        with zipfile.ZipFile(p, 'w', zipfile.ZIP_STORED) as z:
            z.writestr('payload.txt', b'known uncompressed payload')
        raw = p.read_bytes().replace(b'known uncompressed payload', b'wrong uncompressed payload')
        p.write_bytes(raw)
        _, inventory = self.index()
        self.assertEqual(inventory['zip_corrupt'], 1)
        self.assertEqual(inventory['zip_valid'], 0)

    def test_corrupt_band_and_partial_scene_remain_unusable(self):
        for b in local.BANDS[:-1]:
            self.band(b)
        corrupt = self.band('B02')
        corrupt.write_bytes(b'not a TIFF')
        rows, _ = self.index()
        scenes, _ = local.reconcile_scenes(rows)
        self.assertEqual(scenes[0]['missing_bands'], ['SCL'])
        self.assertIn('INVALID_RASTER', scenes[0]['errors'])
        self.assertFalse(scenes[0]['usable_source'])

    def test_acquisition_conflict_is_held(self):
        variant = SCENE.replace('_N0510_', '_')
        for b in local.BANDS:
            self.band(b)
            p = self.band(b, scene=variant)
            if b == 'B04':
                with rasterio.open(p, 'r+') as ds:
                    ds.write(np.full((16, 16), 2500, dtype=np.uint16), 1)
        rows, _ = self.index()
        scenes, _ = local.reconcile_scenes(rows)
        self.assertEqual(len(scenes), 2)
        self.assertTrue(all(s['dedup_action'] == 'HOLD_ACQUISITION_CONFLICT' for s in scenes))
        self.assertFalse(any(s['usable_source'] for s in scenes))

    def test_validation_never_deletes_existing_assets(self):
        plot = self.catalog[1]
        geom = box(.002, .002, .008, .008)
        grid = local.base.compute_grid(geom)
        for layer in ('rgb', 'ndvi'):
            (self.root / f'{layer}_2024-06.png').write_bytes(b'preserved')
        result = local.v4.build_month_v4(None, plot, geom, grid, local.base.plot_mask(geom, grid), 2024, 6,
                                        items=[], output_dir=self.root, write_assets=False)
        self.assertEqual(result['status'], 'no_data')
        self.assertEqual((self.root / 'rgb_2024-06.png').read_bytes(), b'preserved')
        self.assertEqual((self.root / 'ndvi_2024-06.png').read_bytes(), b'preserved')

    def test_existing_slot_rechecked_before_any_copy(self):
        ts = self.root / 'data/timeseries_verified_12.json'
        local.write_json(ts, [{'id': 1, 'timeseries': [{'month': '2024-06', 'status': 'observed_single_scene', 'clear_pixel_pct': 100}]}])
        with patch.object(local, 'R', self.root):
            self.assertIsNone(local.ingest_slot(1, '2024-06', {}, self.root / 'nonexistent-stage', ts.read_bytes(), b''))
            with self.assertRaisesRegex(RuntimeError, 'concurrently'):
                local.ingest_slot(1, '2024-06', {}, self.root, b'stale dataset', b'')

    def test_source_mutation_requires_reindex(self):
        p = self.band('B02')
        rows, _ = self.index()
        p.write_bytes(b'changed')
        with self.assertRaises(RuntimeError):
            local.verify_source_unchanged(rows[0])

    def test_calibration_stays_plot_specific(self):
        threshold, status, _ = local.v4.threshold_info({'id': 76})
        self.assertEqual(status, 'PROMOTED_DRONE_CALIBRATED')
        self.assertAlmostEqual(threshold, .155)
        self.assertEqual(local.v4.threshold_info({'id': 1})[0], .25)


if __name__ == '__main__':
    unittest.main()
