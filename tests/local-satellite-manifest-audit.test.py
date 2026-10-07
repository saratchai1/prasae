#!/usr/bin/env python3
"""Regression cases for multi-batch preservation and metadata-backed radiometry."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('manifest_audit', Path(__file__).with_name('local-satellite-manifest-audit.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def batch(name, before, accepted, unresolved, manifest):
    records = [{'plot_id': pid, 'month': month, 'result': 'ACCEPTED'} for pid, month in accepted]
    records += [{'plot_id': pid, 'month': month, 'result': 'NO_CLEAR_SCENE'} for pid, month in unresolved]
    counts = {'ACCEPTED': len(accepted), 'NO_CLEAR_SCENE': len(unresolved)}
    counts = {key: value for key, value in counts.items() if value}
    return {'path': Path(name), 'existing_observation_fingerprints': {
        'count': len(before), 'observations': {f'{pid}|{month}': {} for pid, month in before}},
        'ingest_result': {'accepted': len(accepted), 'counts': counts, 'records': records},
        'source_inventory': {'source_manifest_sha256': manifest},
        'final_summary': {'observed_before': len(before), 'observed_after': len(before) + len(accepted),
                          'newly_accepted': len(accepted), 'still_missing': len(unresolved),
                          'missing_candidates_before': len(records), 'result_counts': counts}}


class SequentialBatchTests(unittest.TestCase):
    def setUp(self):
        month = '2024-09'
        self.keys = [(pid, month) for pid in range(1, 5)]
        first, second, third, fourth = self.keys
        self.slots = {key: {'status': 'observed_clear' if key != fourth else 'no_data',
                            'source_provenance': {'source_manifest_sha256': 'new' if key == third else 'old'}}
                      for key in self.keys}
        self.batches = [batch('old', [first], [second], [third, fourth], 'old'),
                        batch('new', [first, second], [third], [fourth], 'new')]

    def test_later_fill_preserves_historical_accepted_slot(self):
        accepted = audit.validate_batch_chain(self.batches, self.slots)
        self.assertEqual(set(accepted), set(self.keys[1:3]))

    def test_existing_observation_cannot_be_reaccepted(self):
        self.batches[1]['ingest_result']['records'][0]['plot_id'] = 2
        with self.assertRaises(AssertionError):
            audit.validate_batch_chain(self.batches, self.slots)

    def test_later_baseline_cannot_drop_prior_accepted_observation(self):
        del self.batches[1]['existing_observation_fingerprints']['observations']['2|2024-09']
        with self.assertRaises(AssertionError):
            audit.validate_batch_chain(self.batches, self.slots)

    def test_historical_unresolved_slot_needs_later_manifest_identity(self):
        self.slots[self.keys[2]]['source_provenance']['source_manifest_sha256'] = 'old'
        with self.assertRaises(AssertionError):
            audit.validate_batch_chain(self.batches, self.slots)

    def test_unreported_current_observation_rejected(self):
        self.slots[self.keys[3]]['status'] = 'observed_clear'
        with self.assertRaises(AssertionError):
            audit.validate_batch_chain(self.batches, self.slots)

    def test_inconsistent_accepted_count_rejected(self):
        self.batches[1]['ingest_result']['accepted'] = 0
        with self.assertRaises(AssertionError):
            audit.validate_batch_chain(self.batches, self.slots)


class MetadataRadiometryTests(unittest.TestCase):
    def setUp(self):
        self.proof = {'scale': .0001, 'offset': -.1, 'nodata': 0, 'formula': 'DN * scale + offset',
                      'metadata_source_id': 'source-items/scene.json', 'metadata_sha256': 'a' * 64,
                      'radiometry_sidecar_source_id': 'metadata/scene.json', 'radiometry_sidecar_sha256': 'b' * 64,
                      'asset_key': 'red'}
        self.checksums = {'source-items/scene.json': 'a' * 64, 'metadata/scene.json': 'b' * 64}

    def test_negative_and_preapplied_offsets_are_distinct_valid_profiles(self):
        audit.validate_metadata_radiometry('B04', self.proof, self.checksums)
        preapplied = deepcopy(self.proof)
        preapplied['offset'] = 0
        audit.validate_metadata_radiometry('B04', preapplied, self.checksums)

    def test_unhashed_provider_metadata_rejected(self):
        self.checksums['source-items/scene.json'] = 'c' * 64
        with self.assertRaises(AssertionError):
            audit.validate_metadata_radiometry('B04', self.proof, self.checksums)

    def test_unhashed_export_sidecar_rejected(self):
        del self.checksums['metadata/scene.json']
        with self.assertRaises(AssertionError):
            audit.validate_metadata_radiometry('B04', self.proof, self.checksums)

    def test_categorical_scl_cannot_use_spectral_scaling(self):
        with self.assertRaises(AssertionError):
            audit.validate_metadata_radiometry('SCL', self.proof, self.checksums)
        self.proof.update(scale=1, offset=0, formula='SCL categorical', asset_key='scl')
        audit.validate_metadata_radiometry('SCL', self.proof, self.checksums)

    def test_nonfinite_scale_rejected(self):
        self.proof['scale'] = float('nan')
        with self.assertRaises(AssertionError):
            audit.validate_metadata_radiometry('B04', self.proof, self.checksums)


class AuxiliarySourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        auxiliary = {'source_id': 'export-scripts/run_pipeline.py', 'checksum': 'c' * 64,
                     'filesize': 50000, 'integrity_status': 'HASHED'}
        self.rows = [{'source_id': 'prepared/inputs/scene/B04.tif', 'checksum': 'a' * 64},
                     {'source_id': 'source-items/scene.json', 'checksum': 'b' * 64},
                     {'source_id': auxiliary['source_id'], 'checksum': auxiliary['checksum']}]
        self.inventory = {'scientific_tifs': 1, 'non_scientific_files': [self.rows[1]],
                          'auxiliary_support_files': [auxiliary], 'local_files_scanned': 2,
                          'source_evidence_files_scanned': 3,
                          'source_manifest_sha256': audit.sha(sorted(self.rows, key=lambda row: row['source_id']))}
        self.summary = {key: self.inventory[key] for key in
                        ('local_files_scanned', 'source_evidence_files_scanned', 'source_manifest_sha256')}

    def validate(self):
        return audit.validate_inventory_source_rows(self.inventory, self.summary, self.rows)

    def test_external_encoder_is_evidence_but_not_a_physical_delivery_file(self):
        checksums = self.validate()
        self.assertEqual(checksums['export-scripts/run_pipeline.py'], 'c' * 64)

    def test_historical_delivery_without_auxiliary_keeps_original_digest(self):
        self.rows.pop()
        self.inventory.pop('auxiliary_support_files')
        self.inventory.pop('source_evidence_files_scanned')
        self.summary.pop('source_evidence_files_scanned')
        self.inventory['source_manifest_sha256'] = self.summary['source_manifest_sha256'] = audit.sha(sorted(self.rows, key=lambda row: row['source_id']))
        self.assertEqual(len(self.validate()), 2)

    def test_auxiliary_file_cannot_inflate_physical_delivery_count(self):
        self.inventory['local_files_scanned'] = self.summary['local_files_scanned'] = 3
        with self.assertRaisesRegex(AssertionError, 'not a delivery file'):
            self.validate()

    def test_source_evidence_count_must_include_external_encoder(self):
        self.inventory['source_evidence_files_scanned'] = self.summary['source_evidence_files_scanned'] = 2
        with self.assertRaisesRegex(AssertionError, 'source evidence count'):
            self.validate()

    def test_external_encoder_must_have_a_matching_hashed_row(self):
        self.inventory['auxiliary_support_files'][0]['checksum'] = 'd' * 64
        with self.assertRaises(AssertionError):
            self.validate()

    def test_external_encoder_cannot_be_unhashed(self):
        self.inventory['auxiliary_support_files'][0]['integrity_status'] = 'UNKNOWN'
        with self.assertRaisesRegex(AssertionError, 'must be hashed'):
            self.validate()

    def test_external_encoder_source_id_must_be_portable(self):
        self.inventory['auxiliary_support_files'][0]['source_id'] = '/private/run_pipeline.py'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_duplicate_auxiliary_identity_cannot_hide_another_source(self):
        self.rows[-1] = deepcopy(self.rows[0])
        with self.assertRaisesRegex(AssertionError, 'duplicate inventory identity'):
            self.validate()

    def test_manifest_digest_binds_external_encoder_evidence(self):
        self.rows[-1]['checksum'] = self.inventory['auxiliary_support_files'][0]['checksum'] = 'd' * 64
        with self.assertRaises(AssertionError):
            self.validate()

    def include_reused_source(self):
        self.rows.append({'source_id': 'reused/inputs-next/prepared/inputs/scene/B04.tif', 'checksum': 'd' * 64})
        self.inventory.update(scientific_tifs=2, physical_scientific_tifs=1, reused_scientific_tifs=1,
                              source_evidence_files_scanned=4,
                              source_manifest_sha256=audit.sha(sorted(self.rows, key=lambda row: row['source_id'])))
        self.summary.update(source_evidence_files_scanned=4, source_manifest_sha256=self.inventory['source_manifest_sha256'])

    def test_reused_scientific_evidence_does_not_inflate_physical_delivery_count(self):
        self.include_reused_source()
        self.assertEqual(len(self.validate()), 4)

    def test_reused_scientific_count_must_match_portable_tiff_identities(self):
        self.include_reused_source()
        self.rows[-1]['source_id'] = 'prepared/inputs/extra/B04.tif'
        with self.assertRaisesRegex(AssertionError, 'reused scientific count'):
            self.validate()

    def test_physical_and_reused_scientific_totals_must_reconcile(self):
        self.include_reused_source()
        self.inventory['physical_scientific_tifs'] = 2
        with self.assertRaises(AssertionError):
            self.validate()


class MetadataProfileTests(unittest.TestCase):
    def setUp(self):
        product = 'S2A_MSIL2A_20230913T033541_N0509_R061_T47NNH_20230913T090759'
        metadata_id = f'source-items/earth-search/{product}.json'
        sidecar_id = f'metadata/{product}/radiometry.json'
        self.checksums = {metadata_id: 'a' * 64, sidecar_id: 'b' * 64, 'scripts/export.py': 'c' * 64}
        profile = {'scene_id': product, 'stac_item_id': 'S2A_T47NNH_20230913T034947_L2A',
                   'collection': 'sentinel-2-c1-l2a', 'product_uri': product + '.SAFE',
                   'sensing_datetime': '2023-09-13T03:56:30Z', 'processing_baseline': '05.09',
                   'platform': 'sentinel-2a', 'metadata_source_id': metadata_id, 'metadata_sha256': 'a' * 64,
                   'radiometry_sidecar_source_id': sidecar_id, 'radiometry_sidecar_sha256': 'b' * 64, 'assets': {}}
        for band, asset_key in audit.EARTH_SEARCH_ASSETS.items():
            profile['assets'][band] = {'scale': 1 if band == 'SCL' else .0001,
                                       'offset': 0 if band == 'SCL' else -.1, 'nodata': 0,
                                       'formula': 'SCL categorical' if band == 'SCL' else 'DN * scale + offset',
                                       'asset_key': asset_key, 'native_dtype': 'uint8' if band == 'SCL' else 'uint16',
                                       **{key: profile[key] for key in ('metadata_source_id', 'metadata_sha256',
                                                                      'radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')}}
        self.report = {'status': 'PASS', 'metadata_gate': 'PASS', 'formula': 'DN * scale + offset',
                       'validated_scene_count': 1, 'validated_product_count': 1, 'profiles': [profile],
                       'export_script_source_id': 'scripts/export.py', 'export_script_sha256': 'c' * 64}
        self.scenes = [{'scene_id': product, 'month': '2023-09', 'acquisition_datetime': '2023-09-13T03:35:41+00:00',
                        'satellite': 'S2A', 'tile': 'T47NNH', 'raster_grids': [{'dtype': 'uint16'}, {'dtype': 'uint8'}],
                        'assets': {'B04': {'grid': 0, 'radiometry': deepcopy(profile['assets']['B04'])},
                                   'SCL': {'grid': 1, 'radiometry': deepcopy(profile['assets']['SCL'])}}}]

    def validate(self):
        audit.validate_metadata_profiles(self.report, self.scenes, self.checksums)

    def test_partial_scene_requires_complete_matching_product_profile(self):
        self.validate()

    def test_missing_product_profile_rejected(self):
        self.report['profiles'] = []
        with self.assertRaises(AssertionError):
            self.validate()

    def test_duplicate_conflicting_product_profile_rejected(self):
        conflict = deepcopy(self.report['profiles'][0])
        conflict['assets']['B04']['offset'] = 0
        self.report['profiles'].append(conflict)
        with self.assertRaises(AssertionError):
            self.validate()

    def test_scene_and_profile_radiometry_conflict_rejected(self):
        self.scenes[0]['assets']['B04']['radiometry']['offset'] = 0
        with self.assertRaises(AssertionError):
            self.validate()

    def test_profile_cannot_claim_unvalidated_scene_count(self):
        self.report['validated_scene_count'] = 0
        with self.assertRaises(AssertionError):
            self.validate()

    def test_different_reprocessing_product_uri_rejected(self):
        self.report['profiles'][0]['product_uri'] = 'different-product.SAFE'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_different_sensing_month_rejected(self):
        self.report['profiles'][0]['sensing_datetime'] = '2023-10-13T03:56:30Z'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_unhashed_export_script_rejected(self):
        self.checksums['scripts/export.py'] = 'd' * 64
        with self.assertRaises(AssertionError):
            self.validate()


class MultiProviderProfileTests(unittest.TestCase):
    def setUp(self):
        original = MetadataProfileTests()
        original.setUp()
        self.product = original.scenes[0]['scene_id']
        self.checksums = deepcopy(original.checksums)
        self.profiles, self.scenes = [], []
        scripts = [{'source_id': name, 'checksum': str(index) * 64} for index, name in enumerate(
            ('scripts/campaign_v2.py', 'scripts/campaign_pc.py', 'scripts/downloader.py'), start=1)]
        self.checksums.update({record['source_id']: record['checksum'] for record in scripts})
        for provider in ('earth-search', 'planetary-computer'):
            profile = deepcopy(original.report['profiles'][0])
            profile.update(provider=provider, profile_key=provider + '|' + self.product)
            if provider == 'planetary-computer':
                profile.update(collection='sentinel-2-l2a', platform='Sentinel-2A',
                               stac_item_id=self.product.replace('_N0509', ''),
                               metadata_source_id=f'source-items/{provider}/{self.product}.json', metadata_sha256='d' * 64,
                               radiometry_sidecar_source_id=f'metadata/{provider}/{self.product}/radiometry.json',
                               radiometry_sidecar_sha256='e' * 64,
                               product_metadata_source_id=f'provider-metadata/{provider}/{self.product}.xml',
                               product_metadata_sha256='f' * 64, product_metadata_filesize=2000,
                               product_metadata_url=f'https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/test/{self.product}.SAFE/MTD_MSIL2A.xml')
                offsets = {str(band_id): -1000 for band_id in audit.XML_BAND_IDS.values()}
                proof = {'status': 'PASS', 'product_uri': profile['product_uri'], 'processing_baseline': '05.09',
                         'boa_quantification_value': 10000, 'boa_offsets_by_band_id': offsets,
                         'special_values': {'NODATA': 0, 'SATURATED': 65535}}
                proof['critical_nodes'] = {'PRODUCT_URI': proof['product_uri'], 'PROCESSING_BASELINE': proof['processing_baseline'],
                                          'BOA_QUANTIFICATION_VALUE': 10000, 'BOA_ADD_OFFSET': offsets,
                                          'Special_Values': proof['special_values']}
                profile['product_metadata_proof'] = proof
                self.checksums.update({profile['metadata_source_id']: profile['metadata_sha256'],
                                       profile['radiometry_sidecar_source_id']: profile['radiometry_sidecar_sha256'],
                                       profile['product_metadata_source_id']: profile['product_metadata_sha256']})
            for band, asset in profile['assets'].items():
                asset.update(provider=provider, **{key: profile[key] for key in
                             ('metadata_source_id', 'metadata_sha256', 'radiometry_sidecar_source_id', 'radiometry_sidecar_sha256')})
                if provider == 'earth-search':
                    asset['native_asset_url'] = 'https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/sentinel-2-c1-l2a/test/' + band + '.tif'
                else:
                    asset.update(asset_key=band,
                                 native_asset_url=f'https://sentinel2l2a01.blob.core.windows.net/sentinel2-l2/test/{self.product}.SAFE/T47NNH_{band}_10m.tif',
                                 product_metadata_source_id=profile['product_metadata_source_id'],
                                 product_metadata_sha256=profile['product_metadata_sha256'])
                    if band != 'SCL':
                        asset.update(band_id=audit.XML_BAND_IDS[band], boa_add_offset=-1000,
                                     formula='(DN + BOA_ADD_OFFSET) / BOA_QUANTIFICATION_VALUE')
            grids = [{'crs': 'EPSG:32647', 'dtype': dtype, 'nodata': 0, 'width': 2, 'height': 2,
                      'transform': [resolution, 0, 500000 + resolution, 0, -resolution, 1000000 - 2 * resolution]}
                     for dtype, resolution in (('uint16', 10), ('uint8', 20))]
            assets, grid_proofs = {}, {}
            for band, asset in profile['assets'].items():
                grid_index = 1 if band == 'SCL' else 0
                resolution = 20 if band == 'SCL' else 10
                assets[band] = {'grid': grid_index, 'radiometry': deepcopy(asset)}
                grid_proofs[band] = {'crs': 'EPSG:32647', 'product_transform': [resolution, 0, 500000, 0, -resolution, 1000000],
                                     'product_shape': [10980, 10980], 'window': [1, 2, 2, 2],
                                     'metadata_transform_tags': False, 'pixel_encoding': 'raw native DN'}
            scene = {**deepcopy(original.scenes[0]), 'provider': provider, 'source_group': 'prepared/' + provider + '/scene',
                     'metadata_status': 'VALIDATED', 'usable_source': True, 'complete': True, 'missing_bands': [],
                     'raster_grids': grids, 'assets': assets, 'native_grid_proofs': grid_proofs}
            self.profiles.append(profile)
            self.scenes.append(scene)
        self.report = {'status': 'PASS', 'metadata_gate': 'PASS', 'formula': 'DN * scale + offset',
                       'provider_schema': audit.MULTI_PROVIDER_SCHEMA, 'profiles': self.profiles,
                       'validated_scene_count': 2, 'validated_product_count': 2,
                       'export_scripts': scripts, 'unvalidated_scene_records': []}

    def validate(self):
        audit.validate_metadata_profiles(self.report, self.scenes, self.checksums)

    def test_same_product_from_two_providers_keeps_distinct_valid_profiles(self):
        self.validate()

    def test_duplicate_provider_product_profile_rejected(self):
        self.report['profiles'].append(deepcopy(self.profiles[0]))
        with self.assertRaisesRegex(AssertionError, 'duplicate or conflicting'):
            self.validate()

    def test_unhashed_product_xml_rejected(self):
        del self.checksums[self.profiles[1]['product_metadata_source_id']]
        with self.assertRaisesRegex(AssertionError, 'product XML'):
            self.validate()

    def test_xml_quantification_cannot_disagree_with_band_transform(self):
        proof = self.profiles[1]['product_metadata_proof']
        proof['boa_quantification_value'] = proof['critical_nodes']['BOA_QUANTIFICATION_VALUE'] = 20000
        with self.assertRaises(AssertionError):
            self.validate()

    def test_xml_offsets_cannot_be_swapped_between_band_ids(self):
        self.profiles[1]['assets']['B04']['band_id'] = audit.XML_BAND_IDS['B03']
        with self.assertRaises(AssertionError):
            self.validate()

    def test_pc_collection_and_item_identity_cannot_inherit_earth_search_rules(self):
        self.profiles[1]['stac_item_id'] = self.profiles[0]['stac_item_id']
        with self.assertRaisesRegex(AssertionError, 'PC STAC identity'):
            self.validate()

    def test_provider_asset_mapping_cannot_cross_between_providers(self):
        self.profiles[1]['assets']['B04']['asset_key'] = 'red'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_signed_native_asset_url_rejected(self):
        self.profiles[1]['assets']['B04']['native_asset_url'] += '?sig=private'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_changed_exporter_checksum_rejected(self):
        self.report['export_scripts'][0]['checksum'] = '9' * 64
        with self.assertRaisesRegex(AssertionError, 'export script'):
            self.validate()

    def test_missing_metadata_is_held_only_for_explicit_incomplete_scene(self):
        scene = deepcopy(self.scenes[0])
        scene.update(scene_id=self.product.replace('20230913', '20230923'),
                     source_group='prepared/held/scene', metadata_status='HOLD_MISSING_PRODUCT_METADATA',
                     complete=False, missing_bands=list(audit.BANDS - {'SCL'}), usable_source=False,
                     assets={'SCL': {'grid': 1}}, native_grid_proofs={})
        self.scenes.append(scene)
        self.report['unvalidated_scene_records'].append({'provider': 'earth-search', 'scene_id': scene['scene_id'],
                                                        'source_group': scene['source_group'], 'reason': 'HOLD_MISSING_PRODUCT_METADATA'})
        self.validate()
        scene['usable_source'] = True
        with self.assertRaisesRegex(AssertionError, 'cannot be ingested'):
            self.validate()

    def test_unreported_missing_metadata_rejected(self):
        self.scenes[0]['scene_id'] = self.product.replace('20230913', '20230923')
        with self.assertRaisesRegex(AssertionError, 'no product profile'):
            self.validate()

    def test_off_grid_crop_origin_rejected(self):
        self.scenes[1]['raster_grids'][0]['transform'][2] += 1
        with self.assertRaisesRegex(AssertionError, 'origin differs'):
            self.validate()

    def test_outside_product_window_rejected(self):
        self.scenes[1]['native_grid_proofs']['B04']['window'][0] = 10979
        with self.assertRaisesRegex(AssertionError, 'outside original'):
            self.validate()

    def test_resampled_native_grid_rejected(self):
        self.scenes[1]['raster_grids'][0]['transform'][0] = 5
        with self.assertRaisesRegex(AssertionError, 'pixel spacing'):
            self.validate()

    def test_every_bound_band_requires_its_grid_proof(self):
        del self.scenes[1]['native_grid_proofs']['B04']
        with self.assertRaisesRegex(AssertionError, 'every validated band'):
            self.validate()

    def test_categorical_scl_cannot_carry_transform_tags(self):
        self.scenes[1]['native_grid_proofs']['SCL']['metadata_transform_tags'] = True
        with self.assertRaisesRegex(AssertionError, 'SCL cannot'):
            self.validate()


class HeldScientificSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = {'source_id': 'test_B04.tif', 'checksum': 'a' * 64, 'filesize': 100,
                       'integrity_status': 'VALID', 'action': 'HOLD_UNASSIGNED_SOURCE',
                       'reason': 'standalone test raster lacks registry/month/product identity'}

    def test_unassigned_test_raster_is_valid_held_evidence_only(self):
        audit.validate_held_scientific_source(self.source, multi_provider=True)

    def test_historical_batches_cannot_inherit_new_hold_rule(self):
        with self.assertRaises(AssertionError):
            audit.validate_held_scientific_source(self.source)

    def test_unassigned_raster_cannot_claim_plot_month_identity(self):
        self.source.update(plot_id=1, month='2023-09')
        with self.assertRaisesRegex(AssertionError, 'observation identity'):
            audit.validate_held_scientific_source(self.source, multi_provider=True)


class ReusedNativeSourceTests(unittest.TestCase):
    def setUp(self):
        original = MultiProviderProfileTests()
        original.setUp()
        namespace = 'reused/inputs-next/'
        self.prior_scene = deepcopy(original.scenes[0])
        self.prior_scene.update(plot_id=131, fingerprint='a' * 64, scope='REGISTRY_CONTAINED')
        self.prior_profile = deepcopy(original.profiles[0])
        for band, asset in self.prior_scene['assets'].items():
            asset.update(source_id=self.prior_scene['source_group'] + '/' + band + '.tif',
                         filename=band + '.tif', checksum='b' * 64, filesize=100, integrity='VALID')
        self.scene = deepcopy(self.prior_scene)
        self.scene.update(source_group=namespace + self.prior_scene['source_group'], native_grid_proofs={},
                          prior_validated_batch={'id': 'local-satellite-ingest-20261005',
                                                 'fingerprint': self.prior_scene['fingerprint'],
                                                 'source_group': self.prior_scene['source_group']})
        self.profile = deepcopy(self.prior_profile)
        self.profile.update(metadata_format='earth-search-c1-flat-sidecar', source_namespace=namespace,
                            prior_batch_id='local-satellite-ingest-20261005')
        for key in ('metadata_source_id', 'radiometry_sidecar_source_id'):
            self.profile[key] = namespace + self.profile[key]
        for band, asset in self.scene['assets'].items():
            asset['source_id'] = namespace + asset['source_id']
            for key in ('metadata_source_id', 'radiometry_sidecar_source_id'):
                self.profile['assets'][band][key] = namespace + self.profile['assets'][band][key]
            asset['radiometry'] = deepcopy(self.profile['assets'][band])

    def validate(self):
        audit.validate_reused_native_scene(self.scene, self.profile, self.prior_scene, self.prior_profile)

    def test_reused_canonical_crop_requires_exact_prior_grid_and_metadata(self):
        self.validate()

    def test_reused_crop_cannot_change_grid(self):
        self.scene['raster_grids'][0]['transform'][2] += 1
        with self.assertRaisesRegex(AssertionError, 'raster grid differs'):
            self.validate()

    def test_reused_band_cannot_inherit_another_checksum(self):
        self.scene['assets']['B04']['checksum'] = 'c' * 64
        with self.assertRaises(AssertionError):
            self.validate()

    def test_reused_profile_cannot_reinterpret_radiometry(self):
        self.profile['assets']['B04']['offset'] = 0
        with self.assertRaisesRegex(AssertionError, 'band metadata differs'):
            self.validate()


class AcquisitionSelectionTests(unittest.TestCase):
    def setUp(self):
        latest = 'S2A_MSIL2A_20230913T033541_N0510_R061_T47NNH_20241106T073433'
        prior = latest.replace('_N0510', '_N0509').replace('20241106T073433', '20230913T090759')
        self.scenes = [{'plot_id': 1, 'month': '2023-09', 'acquisition_key': 'same-acquisition',
                        'scene_id': latest, 'source_group': 'prepared/latest', 'usable_source': True,
                        'dedup_action': 'KEEP_REVIEWED_LATEST_PRODUCT', 'selection_alternatives': ['prepared/prior'],
                        'native_grid_proofs': {'B04': {}}},
                       {'plot_id': 1, 'month': '2023-09', 'acquisition_key': 'same-acquisition',
                        'scene_id': prior, 'source_group': 'prepared/prior', 'usable_source': False,
                        'dedup_action': 'HOLD_REPROCESSING_ALTERNATIVE', 'selected_source_group': 'prepared/latest',
                        'native_grid_proofs': {'B04': {}}}]

    def test_latest_product_retains_alternative_without_double_counting(self):
        audit.validate_acquisition_selection(self.scenes)

    def test_same_acquisition_cannot_contribute_twice(self):
        self.scenes[1]['usable_source'] = True
        self.scenes[1]['dedup_action'] = 'KEEP'
        with self.assertRaisesRegex(AssertionError, 'contribute twice'):
            audit.validate_acquisition_selection(self.scenes)

    def test_older_reprocessing_cannot_claim_latest_selection(self):
        self.scenes[0]['scene_id'], self.scenes[1]['scene_id'] = self.scenes[1]['scene_id'], self.scenes[0]['scene_id']
        with self.assertRaisesRegex(AssertionError, 'latest validated processing'):
            audit.validate_acquisition_selection(self.scenes)


class QaPreservationTests(unittest.TestCase):
    def setUp(self):
        month = '2024-09'
        self.keys = [(pid, month) for pid in range(1, 4)]
        self.text_keys = [f'{pid}|{month}' for pid, month in self.keys]
        self.before = {self.text_keys[0]: {'status': 'CLEAR', 'coverage_pct': 100, 'other_good_month_water_median_pct': 10},
                       self.text_keys[1]: {'status': 'INSUFFICIENT', 'coverage_pct': 0},
                       self.text_keys[2]: {'status': 'INSUFFICIENT', 'coverage_pct': 0}}
        self.qa = {'observations': deepcopy(self.before)}
        pending = 'NATIVE_C1_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING'
        self.qa['observations'][self.text_keys[1]].update(status='RADIOMETRY_REVIEW', coverage_pct=95.8, radiometry_status=pending)
        self.qa['observations'][self.text_keys[2]].update(coverage_pct=55, radiometry_status=pending)
        self.slots = {self.keys[0]: {'clear_pixel_pct': 100}, self.keys[1]: {'clear_pixel_pct': 95.8}, self.keys[2]: {'clear_pixel_pct': 55}}
        self.batches = [batch('native', [self.keys[0]], self.keys[1:], [], 'native-manifest')]
        self.batches[0]['radiometric_validation'] = {'metadata_gate': 'PASS'}
        self.batches[0]['existing_qa_fingerprints'] = {
            'base_sha': 'a' * 40, 'count': 3, 'observations': {key: audit.sha(value) for key, value in self.before.items()},
            'allowed_changed_keys': self.text_keys[1:]}

    def validate(self):
        self.qa['summary'] = dict(sorted(audit.Counter(value['status'] for value in self.qa['observations'].values()).items()))
        return audit.validate_qa_preservation(self.batches, self.qa, self.slots)

    def test_unrelated_qa_preserved_and_native_images_remain_reviewable(self):
        self.assertEqual(self.validate(), 1)

    def test_old_water_context_change_rejected(self):
        self.qa['observations'][self.text_keys[0]]['other_good_month_water_median_pct'] = 20
        with self.assertRaises(AssertionError):
            self.validate()

    def test_qa_changes_cannot_expand_beyond_accepted_slots(self):
        self.batches[0]['existing_qa_fingerprints']['allowed_changed_keys'] = self.text_keys
        with self.assertRaises(AssertionError):
            self.validate()

    def test_native_full_coverage_cannot_be_marked_comparable_clear(self):
        self.qa['observations'][self.text_keys[1]]['status'] = 'CLEAR'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_native_radiometry_marker_required(self):
        del self.qa['observations'][self.text_keys[1]]['radiometry_status']
        with self.assertRaises((AssertionError, KeyError)):
            self.validate()

    def test_native_low_coverage_remains_insufficient(self):
        self.qa['observations'][self.text_keys[2]]['status'] = 'RADIOMETRY_REVIEW'
        with self.assertRaises(AssertionError):
            self.validate()

    def test_multi_provider_low_coverage_uses_distinct_metadata_gate(self):
        self.batches[0]['radiometric_validation']['provider_schema'] = audit.MULTI_PROVIDER_SCHEMA
        pending = 'NATIVE_MULTI_PROVIDER_METADATA_VALIDATED_LEGACY_HARMONIZATION_PENDING'
        for key in self.text_keys[1:]:
            self.qa['observations'][key]['radiometry_status'] = pending
        self.assertEqual(self.validate(), 1)

    def test_existing_visual_review_gate_retained(self):
        self.qa['observations'][self.text_keys[1]].update(status='ATMOSPHERE_REVIEW', visual_screening_status='ATMOSPHERE_REVIEW')
        self.assertEqual(self.validate(), 1)

    def test_later_accepted_slot_can_change_prior_unresolved_qa(self):
        first, second, third = self.keys
        older = batch('older', [first], [second], [third], 'older-manifest')
        older['radiometric_validation'] = {'metadata_gate': 'PASS'}
        older['existing_qa_fingerprints'] = deepcopy(self.batches[0]['existing_qa_fingerprints'])
        older['existing_qa_fingerprints']['allowed_changed_keys'] = [self.text_keys[1]]
        later_before = deepcopy(self.before)
        later_before[self.text_keys[1]] = deepcopy(self.qa['observations'][self.text_keys[1]])
        later = batch('later', [first, second], [third], [], 'later-manifest')
        later['radiometric_validation'] = {'metadata_gate': 'PASS'}
        later['existing_qa_fingerprints'] = {
            'base_sha': 'b' * 40, 'count': 3, 'observations': {key: audit.sha(value) for key, value in later_before.items()},
            'allowed_changed_keys': [self.text_keys[2]]}
        self.batches = [older, later]
        self.assertEqual(self.validate(), 2)


if __name__ == '__main__':
    unittest.main()
