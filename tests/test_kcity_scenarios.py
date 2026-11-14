"""KC-01 contract regression checks; no learner or simulator process is started."""
from copy import deepcopy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from env.kcity_config import (ContractError, DEFAULT_PROTOCOL, canonical_bytes,
    case_seeds, load_contract, make_case, repository_path, traffic_requests,
    validate_settings)
from scripts.kcity.scenarios import validate_contract


class KCityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_contract()
        cls.report, cls.routes = validate_contract(cls.spec)

    def test_all_scenarios_and_background_connections(self):
        self.assertEqual(set(self.report['scenarios']), {'A', 'B', 'C'})
        self.assertEqual(self.report['background_routes_checked'], 176)
        self.assertEqual(self.report['errors'], [])

    def test_signal_and_link_indices_are_grounded(self):
        a = self.report['scenarios']['A']
        self.assertEqual(a['TLS_ids'], ['647'])
        signal = a['connections'][1]['options'][0]
        self.assertEqual(signal['tls_id'], '647')
        self.assertEqual(signal['link_index'], 2)
        self.assertEqual(self.report['scenarios']['C']['TLS_ids'], ['169','268','647','764'])

    def test_required_lane_change_is_real(self):
        for sid in ['B', 'C']:
            row = self.report['scenarios'][sid]
            self.assertEqual(row['start']['lane_id'], '-3#4_0')
            self.assertEqual({c['from_lane'] for c in row['connections'][0]['options']}, {'-3#4_1'})
            self.assertTrue(row['required_lane_change_geometry_valid'])

    def test_short_and_internal_lanes_are_retained(self):
        b = self.report['scenarios']['B']
        self.assertEqual({e['id'] for e in b['short_normal_edges']}, {'-3#5', '-3#7'})
        self.assertTrue(all(c['options'][0]['via_lanes'] for c in b['connections']))
        self.assertEqual(len(b['connections']), 5)

    def test_goal_outside_lane_is_rejected(self):
        bad = deepcopy(self.spec)
        bad['scenario_manifest']['scenarios'][0]['goal']['arrival_position_m'] = 1e6
        with self.assertRaisesRegex(ContractError, 'goal outside'):
            validate_contract(bad)

    def test_disconnected_route_is_rejected(self):
        bad = deepcopy(self.spec)
        bad['scenario_manifest']['scenarios'][0]['route_edges'][1] = '3#4'
        with self.assertRaisesRegex(ContractError, 'No passenger connection'):
            validate_contract(bad)

    def test_missing_tls_is_rejected(self):
        bad = deepcopy(self.spec)
        bad['scenario_manifest']['scenarios'][0]['required_tls_ids'] = []
        with self.assertRaisesRegex(ContractError, 'required TLS'):
            validate_contract(bad)

    def test_start_in_correct_lane_does_not_fake_required_change(self):
        bad = deepcopy(self.spec)
        row = bad['scenario_manifest']['scenarios'][1]
        row['start']['lane_index'] = 1
        row['required_lane_change']['depart_lane'] = 1
        with self.assertRaisesRegex(ContractError, 'does not require a change'):
            validate_contract(bad)

    def test_required_lane_task_cannot_be_silently_removed(self):
        bad = deepcopy(self.spec)
        bad['scenario_manifest']['scenarios'][1]['required_lane_change'] = None
        with self.assertRaisesRegex(ContractError, 'cannot be omitted'):
            validate_contract(bad)

    def test_asset_drift_is_rejected(self):
        p = deepcopy(self.spec['protocol'])
        p['assets']['network']['sha256'] = '0' * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'protocol.json'
            path.write_text(json.dumps(p))
            with self.assertRaisesRegex(ContractError, 'changed: network'):
                load_contract(path)

    def test_timing_and_training_authorization_cannot_drift(self):
        for mutate in ['timing', 'training']:
            bad = deepcopy(self.spec)
            if mutate == 'timing':
                bad['protocol']['timing']['control_step_s'] = .4
            else:
                bad['protocol']['training']['enabled'] = True
            with self.assertRaises(ContractError):
                validate_settings(bad)

    def test_external_asset_and_unsafe_numeric_input_rejected(self):
        for path in ['/tmp/secret', '../secret']:
            with self.assertRaises(ContractError):
                repository_path(path)
        for val in [-1, float('nan'), float('inf'), True]:
            with self.assertRaises(ContractError):
                make_case(self.spec, 'dev', 'C', 0, val)
        with self.assertRaises(ContractError):
            case_seeds(self.spec, 'dev', 'C', True)

    def test_request_reproducibility_independent_of_global_rng(self):
        case = make_case(self.spec, 'dev', 'C', 42)
        first = traffic_requests(self.spec, case, self.routes)
        random.seed(93842)
        for _ in range(10):
            random.random()
        second = traffic_requests(self.spec, make_case(self.spec, 'dev', 'C', 42), reversed(list(self.routes)))
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertTrue(all(0 <= r['requested_depart_s'] < 360 for r in first))
        self.assertEqual(len({r['request_id'] for r in first}), len(first))

    def test_separate_process_seed_equality(self):
        code = "from env.kcity_config import *; print(digest(make_case(load_contract(), 'dev', 'C', 42)))"
        a = subprocess.check_output([sys.executable,'-B','-c',code],cwd=ROOT,text=True)
        b = subprocess.check_output([sys.executable,'-B','-c',code],cwd=ROOT,text=True)
        self.assertEqual(a,b)

    def test_split_case_and_component_seed_separation(self):
        a = case_seeds(self.spec, 'expert_train', 'A', 0)
        b = case_seeds(self.spec, 'expert_val', 'A', 0)
        c = case_seeds(self.spec, 'expert_train', 'A', 1)
        self.assertEqual(len(set(a.values())), len(a))
        self.assertFalse(set(a.values()) & set(b.values()))
        self.assertNotEqual(a, c)

    def test_demand_scales_arrivals_without_changing_od_stream(self):
        a = make_case(self.spec, 'final', 'C', 0, 1)
        b = make_case(self.spec, 'final', 'C', 0, 2)
        self.assertNotEqual(a['case_uid'],b['case_uid'])
        self.assertEqual(a['seeds'],b['seeds'])
        low, high = [traffic_requests(self.spec, case, self.routes) for case in [a,b]]
        self.assertGreater(len(high),len(low))
        for x,y in zip(low,high):
            self.assertAlmostEqual(x['requested_depart_s']/2,y['requested_depart_s'],places=7)
            self.assertEqual((x['route_id'],x['vehicle_type']),(y['route_id'],y['vehicle_type']))


if __name__ == '__main__':
    unittest.main()
