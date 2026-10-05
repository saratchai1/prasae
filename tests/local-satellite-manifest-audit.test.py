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
