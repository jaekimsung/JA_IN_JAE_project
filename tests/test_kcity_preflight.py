"""Budget-sized plans and main/pilot prior guards; no simulator required."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcity.data.collector import case_plan
from kcity.data.dataset import compact_plan, expand_plan
from kcity.data.plans import GeneratedCasePlan
from kcity.data.pool import partition
from kcity.data.replay import load_prior
from kcity.env.config import load_contract


class GeneratedPlanTests(unittest.TestCase):
    def test_identity_matches_explicit_plan_and_partitions(self):
        contract = load_contract()
        for kind in ('expert', 'train', 'archive', 'probe'):
            explicit = case_plan(contract, kind, count=120)
            for part in range(3):
                plan = GeneratedCasePlan(contract, kind, cycles=4, part=part, parts=3)
                self.assertEqual(list(plan), partition(explicit, part, 3))
                self.assertEqual(expand_plan(contract, compact_plan(plan))[:], plan[:])

    def test_four_million_budget_has_enough_cases_without_materializing(self):
        contract = load_contract()
        for part in range(8):
            plan = GeneratedCasePlan.for_budget(contract, 'expert', 4_000_000, part, 8)
            self.assertGreaterEqual(len(plan), 500_000)
            self.assertLess(len(json.dumps(compact_plan(plan))), 1000)
            self.assertNotEqual(plan[0]['case']['case_uid'], plan[-1]['case']['case_uid'])
            changed = compact_plan(plan)
            changed['contract_sha256'] = 'wrong'
            with self.assertRaisesRegex(ValueError, 'changed'):
                expand_plan(contract, changed)


class PriorGuardTests(unittest.TestCase):
    def test_prior_rejects_pilot_for_main_and_short_or_unvalidated_pool(self):
        with tempfile.TemporaryDirectory() as d:
            part = Path(d)
            config = dict(source_stage='pilot_expert_pool', eligible_for_research_training=False)
            (part / 'RUN.json').write_text(json.dumps(config))
            (part / 'RELEASE.json').write_text(json.dumps(dict(eligible_for_research_training=False)))
            with patch('kcity.data.replay.pool_reports', return_value=([part], [dict(unique_transitions=10)])):
                with self.assertRaisesRegex(ValueError, 'run purpose'):
                    load_prior(part, 5)
                with self.assertRaisesRegex(ValueError, 'budget'):
                    load_prior(part, 5, pilot=True, minimum_pool_rows=20)
                with patch('kcity.data.replay.shard_directories', return_value=[]):
                    with self.assertRaisesRegex(ValueError, 'Insufficient'):
                        load_prior(part, 5, pilot=True)
            with patch('kcity.data.replay.pool_reports', side_effect=ValueError('bad checksum')):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    load_prior(part, 5)


if __name__ == '__main__':
    unittest.main()
