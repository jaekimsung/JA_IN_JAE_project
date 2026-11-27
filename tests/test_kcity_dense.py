"""Contracts and decisions of the dense v2.1 scenarios."""
import unittest
from pathlib import Path

import numpy as np

from kcity.data.plans import GeneratedCasePlan
from kcity.env.config import ROOT, digest, load_contract, make_case
from kcity.env.observation import CONFLICT, LANE_LEFT, SPEED, VIA_LENGTH, YIELD_SIGN
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.training.experiment import load_experiment
from kcity.training.bc import decision_weights


class DenseTests(unittest.TestCase):
    def test_panels_and_pilot_seeds(self):
        import json
        pilot = load_experiment('configs/kcity/v2_1/pilot.json')
        spec = load_contract(ROOT / pilot['base_contract']['path'])
        for name, ref in pilot['case_panels'].items():
            panel = json.loads((ROOT / ref['path']).read_text())
            self.assertEqual(panel['cases_sha256'], digest(panel['cases']))
            for c in panel['cases']:
                self.assertEqual(c, make_case(spec, name, c['scenario_id'], c['case_index'], c['demand_multiplier']))
        plan = GeneratedCasePlan.for_budget(spec, 'expert', 20, case_offset=pilot['case_offset'])
        self.assertNotEqual(plan[0], GeneratedCasePlan.for_budget(spec, 'expert', 20)[0])
        self.assertEqual(plan[:], GeneratedCasePlan.from_descriptor(spec, plan.descriptor())[:])

    def test_main_panels_match_the_v2_1_contract(self):
        import json
        pilot = load_experiment('configs/kcity/v2_1/pilot.json')
        main = load_experiment('configs/kcity/v2_1/experiment.json')
        self.assertEqual(pilot['base_contract'], main['base_contract'])
        spec = load_contract(ROOT / pilot['base_contract']['path'])
        for name, ref in main['case_panels'].items():
            panel = json.loads((ROOT / ref['path']).read_text())
            self.assertEqual(digest(panel['cases']), panel['cases_sha256'])
            for case in panel['cases']:
                self.assertEqual(case, make_case(spec, name, case['scenario_id'], case['case_index'],
                                                 case['demand_multiplier']))

    def test_first_junction_requires_a_gap_in_the_stream(self):
        from runner.check_scenarios import audit
        row = audit((ROOT / 'configs/kcity/v2_1/protocol.json', 'C', 1004))
        first = row['entries'][0]
        self.assertEqual(first['edge'], '-77')
        self.assertGreaterEqual(row['initial_visible_moving_priority'], 2)
        self.assertGreaterEqual(first['priority_entered_before_ego'], 2)
        self.assertGreaterEqual(first['moving_priority'], 1)
        self.assertEqual(row['end_reason'], 'arrival')

    def test_expert_controls_first_approach_when_traffic_occludes_priority(self):
        from kcity.env.env import SumoKCityEnv
        env = SumoKCityEnv(protocol=ROOT / 'configs/kcity/v2_1/protocol.json')
        self.addCleanup(env.close)
        expert = KCityRuleExpert.from_protocol(env.contract['protocol'])
        for index in (2641, 4506):
            with self.subTest(case=index):
                obs, reset = env.reset(options=dict(namespace='expert_train', scenario_id='C', case_index=index))
                self.assertTrue(reset['priority_visibility_fallback'])
                self.assertEqual(reset['initial_visible_moving_priority'], 1)
                self.assertLess(env.conn.vehicle.getLanePosition(env.ego_id), 6.)
                while True:
                    obs, _, done, truncated, step = env.step(expert.predict(obs))
                    if done or truncated:
                        break
                self.assertEqual(step['end_reason'], 'arrival')
                self.assertFalse(env.ever_collision)

    def test_rolling_yield_uses_visible_motion(self):
        protocol = load_contract(ROOT / 'configs/kcity/v2_1/protocol.json')['protocol']
        expert = KCityRuleExpert.from_protocol(protocol)
        o = np.zeros(63, np.float32)
        o[1:21:4], o[3:21:4] = 1, -1
        o[[YIELD_SIGN, SPEED, LANE_LEFT, VIA_LENGTH]] = [1, .5, .09, .36]
        o[CONFLICT:CONFLICT+5] = [1, .19, .55, 0, .5]
        unsafe = expert.predict(o)[0]
        o[CONFLICT+1], o[CONFLICT+2] = .9, .3
        self.assertGreater(expert.predict(o)[0], unsafe)

    def test_demonstrated_merge_has_highest_sampling_weight(self):
        obs = np.zeros((3, 63))
        obs[1, -1] = 1
        actions = np.zeros((3, 2))
        actions[2, 1] = 1
        np.testing.assert_allclose(decision_weights(obs, actions, 9), [1, 3, 9])


if __name__ == '__main__':
    unittest.main()
