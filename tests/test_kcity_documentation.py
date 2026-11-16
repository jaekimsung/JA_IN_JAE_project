"""Document/layout revisions must not silently bypass the frozen experiment guards."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import kcity.experiment as main

CONTRACT = 'docs/specs/DATA_COLLECTION_SPEC.md'
SOURCE = 'kcity/env/env.py'


class DocumentationContractTests(unittest.TestCase):
    def setUp(self):
        self.original_read = main.read
        self.original_sha = main.file_sha256
        self.frozen_sha = self.original_sha(main.FROZEN)

    def run_with(self, compat_edit=None, frozen_edit=None, changed=None):
        """Load science with an edited compat/frozen record and/or one file reporting a new SHA."""
        compat = deepcopy(self.original_read(main.COMPAT))
        frozen = deepcopy(self.original_read(main.FROZEN))
        if compat_edit:
            compat_edit(compat)
        if frozen_edit:
            frozen_edit(frozen)

        def read(path):
            if str(path).endswith('OPERATIONAL_COMPATIBILITY.json'):
                return compat
            if str(path).endswith('FROZEN_PROTOCOL.json'):
                return frozen
            return self.original_read(path)

        def sha(path):
            if changed and str(path).replace('\\', '/').endswith(changed):
                return '1' * 64
            return self.original_sha(path)

        with patch.object(main, 'read', side_effect=read), patch.object(main, 'file_sha256', side_effect=sha):
            return main.load_scientific()

    def register_doc(self, frozen_sha=None, scientific=None):
        def edit(compat):
            frozen = self.original_read(main.FROZEN)['reference_contract_sha256'][CONTRACT]
            compat['scientific_sha256'] = scientific or self.frozen_sha
            compat['documentation_revision']['contracts'][CONTRACT] = dict(
                frozen_sha256=frozen_sha or frozen, revised_sha256='1' * 64)
        return edit

    def test_current_layout_loads_without_enabling_training(self):
        spec = main.load_scientific()
        self.assertFalse(spec['training_enabled'])
        self.assertTrue(spec['scientific_settings_frozen'])
        self.assertEqual(spec['layout_revision']['revision'], 2)

    def test_unregistered_contract_document_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'contract changed'):
            self.run_with(changed=CONTRACT)

    def test_registered_contract_document_revision_is_accepted(self):
        self.run_with(compat_edit=self.register_doc(), changed=CONTRACT)

    def test_registration_with_wrong_frozen_sha_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'contract changed'):
            self.run_with(compat_edit=self.register_doc(frozen_sha='0' * 64), changed=CONTRACT)

    def test_registration_for_another_science_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'contract changed'):
            self.run_with(compat_edit=self.register_doc(scientific='0' * 64), changed=CONTRACT)

    def test_unregistered_source_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Frozen source changed'):
            self.run_with(changed=SOURCE)

    def test_science_edit_after_layout_revision_is_rejected(self):
        def edit(frozen):
            frozen['budgets']['ppo_transitions_per_method_seed'] = 2000000
        with self.assertRaisesRegex(ValueError, 'Frozen science changed'):
            self.run_with(frozen_edit=edit)


class LayoutMigrationTests(unittest.TestCase):
    def setUp(self):
        self.frozen = main.read(main.FROZEN)
        self.migration = main.read(main.LAYOUT)

    def test_migration_record_is_pinned_by_frozen_protocol(self):
        record = self.frozen['layout_revision']['migration']
        self.assertEqual(main.file_sha256(main.ROOT / record['path']), record['sha256'])

    def test_every_pin_exists_and_maps_to_previous_path(self):
        pinned = self.migration['pinned_sources']
        self.assertEqual(sorted(pinned), sorted(self.frozen['source_sha256']))
        for name, entry in pinned.items():
            self.assertTrue((main.ROOT / name).is_file(), name)
            if entry['previous_path'] is None:
                self.assertTrue(name.endswith('__init__.py'), name)

    def test_old_layout_paths_are_gone(self):
        for old in self.migration['files']:
            if not old.startswith('docs/'):
                self.assertFalse((main.ROOT / old).exists(), old)

    def test_only_path_text_changed_in_science_fields(self):
        changed = self.migration['renamed_protocol_fields']
        self.assertEqual(sorted(changed), ['.case_generation.source'])
        self.assertEqual(json.dumps(self.frozen['case_generation']['source']),
                         json.dumps(changed['.case_generation.source']['after']))


if __name__ == '__main__':
    unittest.main()
