"""Integrity gates for deferred settings publication; never train or publish."""
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/freeze/finalize_kcity_settings.py'
spec = importlib.util.spec_from_file_location('kcity_settings_handoff', SCRIPT)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class SettingsHandoffTests(unittest.TestCase):
    def records(self):
        return [dict(requested_case_uid=str(i), namespace='dev', attempt_valid=True,
                     data_quality_valid=True, completion=False) for i in range(100)]

    def test_policy_failure_remains_in_evaluation(self):
        self.assertEqual(len(handoff.validate_records(self.records())), 100)

    def test_partial_duplicate_and_wrong_split_are_rejected(self):
        with self.assertRaises(ValueError):
            handoff.validate_records(self.records()[:-1])
        rows = self.records()
        rows[-1]['requested_case_uid'] = rows[0]['requested_case_uid']
        with self.assertRaises(ValueError):
            handoff.validate_records(rows)
        rows = self.records()
        rows[0]['namespace'] = 'final'
        with self.assertRaises(ValueError):
            handoff.validate_records(rows)

    def test_infrastructure_or_bad_data_is_not_scored_as_policy_failure(self):
        for field in ['attempt_valid', 'data_quality_valid']:
            rows = self.records()
            rows[0][field] = False
            with self.assertRaises(ValueError):
                handoff.validate_records(rows)

    def test_unfinished_supervisor_cannot_freeze(self):
        with patch.object(handoff, 'read', return_value=dict(phase='TRAINING', completed_seeds=[])):
            with self.assertRaisesRegex(ValueError, 'Both replication'):
                handoff.collect_results()

    def test_checkpoint_checksum_and_escape_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'training.pt').write_bytes(b'test-fixture-not-a-model')
            handoff.write(root/'SHA256.json', {'training.pt': handoff.sha(root/'training.pt')})
            self.assertTrue(handoff.verify_checkpoint(root)['verified'])
            (root/'training.pt').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'Changed checkpoint'):
                handoff.verify_checkpoint(root)
            handoff.write(root/'SHA256.json', {'../outside': 'bad'})
            with self.assertRaisesRegex(ValueError, 'Unsafe checkpoint'):
                handoff.verify_checkpoint(root)

    def test_unrelated_worktree_changes_cancel_publication(self):
        def command(*args):
            return {('git','rev-parse','HEAD'): 'head',
                    ('git','branch','--show-current'): 'main',
                    ('git','remote','get-url','origin'): handoff.REMOTE,
                    ('git','diff','--cached','--name-only'): '',
                    ('git','ls-files','--modified','--others','--exclude-standard'): 'unrelated.txt'}[args]
        request = dict(expected_head='head', input_sha256={}, allowed_paths=['authorized.md'])
        with patch.object(handoff,'command',side_effect=command):
            with self.assertRaisesRegex(ValueError,'Unrelated changes'):
                handoff.check_worktree(request)

    def test_scientific_freeze_does_not_enable_training_and_panels_are_disjoint(self):
        original = handoff.ROOT
        request = handoff.read(original/'docs/research_checks/KC-SETTINGS-20261115-01/REQUEST.json')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(original/'configs/kcity/v1', root/'configs/kcity/v1')
            for name in ['DATA_COLLECTION_SPEC.md','KCITY_EVALUATION.md','KCITY_DATA_PIPELINE.md']:
                (root/'docs/specs').mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original/'docs/specs'/name, root/'docs/specs'/name)
            check = root/'checks'
            handoff.write(check/'SUMMARY.json', {'synthetic_test_only': True})
            with patch.object(handoff,'ROOT',root), patch.object(handoff,'CHECK',check):
                protocol = handoff.build_protocol(request,{})
            self.assertTrue(protocol['scientific_settings_frozen'])
            self.assertFalse(protocol['training_enabled'])
            self.assertFalse(protocol['launch_ready'])
            self.assertEqual(protocol['budgets']['ppo_total_transitions'],6000000)
            self.assertEqual(protocol['parameters'],dict(total=86022,bc_trainable=85764))
            dev = handoff.read(root/'configs/kcity/main_v1/cases_dev.json')['cases']
            final = handoff.read(root/'configs/kcity/main_v1/cases_final.json')['cases']
            self.assertEqual(len(dev),100)
            self.assertEqual(len(final),300)
            self.assertTrue(set(c['case_uid'] for c in dev).isdisjoint(c['case_uid'] for c in final))
            self.assertTrue(all(not c.get('executed',False) for c in final))


if __name__ == '__main__':
    unittest.main()
