"""Document revisions must not silently bypass the frozen experiment guards."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import utils.kcity_main as main


class DocumentationContractTests(unittest.TestCase):
    def test_registered_revision_loads_without_changing_science(self):
        spec = main.load_scientific()
        self.assertFalse(spec['training_enabled'])
        self.assertTrue(spec['scientific_settings_frozen'])

    def reject_compat_edit(self, edit):
        original = main.read
        compatibility = deepcopy(original(main.ROOT / 'configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json'))
        edit(compatibility)

        def read(path):
            return compatibility if str(path).endswith('OPERATIONAL_COMPATIBILITY.json') else original(path)

        with patch.object(main, 'read', side_effect=read):
            with self.assertRaises(ValueError):
                main.load_scientific()

    def test_missing_registration_is_rejected(self):
        self.reject_compat_edit(lambda c: c.pop('documentation_revision'))

    def test_unregistered_document_content_is_rejected(self):
        self.reject_compat_edit(lambda c: c['documentation_revision']['contracts']['docs/DATA_COLLECTION_SPEC.md'].__setitem__('revised_sha256', '0' * 64))

    def test_wrong_original_contract_is_rejected(self):
        self.reject_compat_edit(lambda c: c['documentation_revision']['contracts']['docs/DATA_COLLECTION_SPEC.md'].__setitem__('frozen_sha256', '0' * 64))

    def test_wrong_baseline_commit_is_rejected(self):
        self.reject_compat_edit(lambda c: c['documentation_revision'].__setitem__('baseline_git_revision', '0' * 40))

    def test_wrong_scientific_fingerprint_is_rejected(self):
        self.reject_compat_edit(lambda c: c.__setitem__('scientific_sha256', '0' * 64))

    def test_nondocument_source_change_is_still_rejected(self):
        original = main.file_sha256
        with patch.object(main, 'file_sha256', side_effect=lambda p: '0' * 64 if str(p).endswith('env/kcity_env.py') else original(p)):
            with self.assertRaisesRegex(ValueError, 'Frozen source changed'):
                main.load_scientific()
