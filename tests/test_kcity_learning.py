"""KC-03 GAE/update/metric fixtures; no optimizer steps or research learning."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy.buffer import RolloutBuffer
from env.env import SumoKCityEnv
from policy.ppo import KCityPPO
from env.config import load_contract
from evaluation.metrics import EpisodeMetrics, aggregate, make_panel
from evaluation.evaluate import evaluate_cases


class BufferTests(unittest.TestCase):
    def row(self, b, r=1, v=2, term=False, trunc=False, nv=4):
        b.add([0], [0, 0], 0, r, v, terminated=term, truncated=trunc, next_value=nv)

    def test_truncation_is_296_not_10196(self):
        b = RolloutBuffer(); self.row(b, trunc=True)
        self.row(b, r=100, v=100, term=True, nv=0)
        a, r = b.compute_gae(999, .99, .95)
        self.assertAlmostEqual(a[0], 2.96, places=5)
        self.assertAlmostEqual(r[0], 4.96, places=5)
        self.assertEqual(b.rewards, [1., 100.])
        self.assertEqual(b.bootstrap_masks, [1., 0.]); self.assertEqual(b.trace_masks, [0., 0.])

    def test_termination_never_bootstraps(self):
        b=RolloutBuffer(); self.row(b, term=True, nv=1e6)
        self.assertEqual(b.compute_gae(1e9,.99,.95)[0][0], -1)

    def test_both_flags_termination_takes_precedence(self):
        b=RolloutBuffer(); self.row(b, term=True, trunc=True, nv=None)
        self.assertEqual(b.compute_gae(100,.99,.95)[0][0], -1)

    def test_rollout_cut_bootstraps_once(self):
        b=RolloutBuffer(); self.row(b, nv=4)
        self.assertAlmostEqual(b.compute_gae(100,.99,.95)[0][0],2.96,places=5)

    def test_continuing_trace_matches_hand_calculation(self):
        b=RolloutBuffer(); self.row(b,r=1,v=2,nv=3); self.row(b,r=2,v=3,nv=5)
        a,_=b.compute_gae(5,.9,.8)
        np.testing.assert_allclose(a,[1+.9*3-2+.9*.8*(2+.9*5-3),2+.9*5-3])

    def test_truncation_without_terminal_value_rejected(self):
        with self.assertRaises(ValueError): self.row(RolloutBuffer(),trunc=True,nv=None)

    def test_legacy_add_signature_still_works(self):
        b=RolloutBuffer(); b.add([0],[0,0],0,1,2,False)
        self.assertAlmostEqual(b.compute_gae(4,.99,.95)[0][0],2.96,places=5)

    def test_empty_and_clear(self):
        b=RolloutBuffer(); self.assertEqual(len(b.compute_gae(0,.99,.95)[0]),0)
        self.row(b); b.clear(); self.assertEqual(b.next_values,[])


class FakeEnv:
    unwrapped = property(lambda self: self)
    def __init__(self, autoreset=False):
        self.resets=0; self.steps=0; self.autoreset=autoreset
    def reset(self):
        self.resets+=1; return np.array([100.],np.float32), {}
    def step(self, action):
        self.steps+=1
        # A terminal state worth 4, while the following reset is worth 100.
        return (np.array([100. if self.autoreset else 4.],np.float32),1.,False,True,
                {'final_observation':np.array([4.],np.float32)} if self.autoreset else {})


class UpdateTests(unittest.TestCase):
    def test_single_sample_final_rollout_is_finite_without_optimizer_step(self):
        p=KCityPPO(seed=11,device='cpu')
        p.buffer.add(np.zeros(73,np.float32),[.1,0],-1,1,0,terminated=True,next_value=0,
                     action_mask=[False,True,False])
        before={k:v.clone() for k,v in p.policy.state_dict().items()}
        with patch.object(p.optimizer,'step',return_value=None):
            stats=p.update(np.array([1.],np.float32),np.array([1.],np.float32))
        self.assertTrue(all(np.isfinite(v) for v in stats.values()))
        self.assertTrue(all(torch.equal(before[k],v) for k,v in p.policy.state_dict().items()))


class MetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.contract=load_contract()

    def record(self,events=(),failure=None,infra=None):
        case=make_panel(self.contract,'contract_check',{'A':1})['cases'][0]
        state=dict(sim_tick=0,route_state=dict(route_valid=True,route_length_m=10),
                   ego_route_progress_m=0,traffic=dict(running_hv=5,requested_lambda_vph=600))
        tracker=EpisodeMetrics(case,{'state':state})
        ns=deepcopy(state);ns['sim_tick']=2;ns['ego_route_progress_m']=2
        info=dict(sim_tick_t=0,sim_tick_tp1=2,executed_substeps=2,control_dt_s=.2,
            episode_time_s=.2,substep_samples=[dict(sim_tick=i,dt_s=.1,speed_mps=v,
            running_hv=hv,pending_hv=0,leader_gap_m=None) for i,v,hv in [(1,0,2),(2,4,4)]],
            events=list(events),next_state=ns,action=dict(lane_change=1,
            known_rejection_reasons=[],env_input=[1,1],sumo_override_reason='unknown'),
            action_raw=[2,1],traffic_interval=dict(departed_hv=1),end_reason='deadline')
        tracker.add(1,True,False,info)
        return tracker.finish(failure_reason=failure,infrastructure_error=infra)

    def test_time_weighted_metrics_and_no_fabricated_gap(self):
        r=self.record(); self.assertAlmostEqual(r['HV_time_weighted_mean'],3)
        self.assertAlmostEqual(r['mean_speed_mps'],2);self.assertAlmostEqual(r['standstill_s'],.1)
        self.assertIsNone(r['mean_gap_m']);self.assertIsNone(r['unjustified_wait_s'])
        self.assertEqual(r['executed_LC_count'],0);self.assertEqual(r['commands_left'],1)

    def test_simultaneous_flags_preserved_primary_collision(self):
        r=self.record([dict(type='arrival',correct_goal=True),dict(type='collision'),
            dict(type='tls_crossing',classification_valid=True,red_entry=True)])
        self.assertTrue(r['arrival_event']);self.assertTrue(r['completion']);self.assertTrue(r['ever_AV_collision'])
        self.assertEqual(r['primary_end_reason'],'collision');self.assertFalse(r['compliant_completion'])

    def test_unknown_signal_blocks_compliance_and_combined_score(self):
        r=self.record([dict(type='arrival',correct_goal=True),dict(type='tls_crossing',classification_valid=False,red_entry=False)])
        self.assertIsNone(r['compliant_completion']);a=aggregate([r],1)
        self.assertIsNone(a['signal_compliance']);self.assertIsNone(a['compliant_completion_rate'])

    def test_zero_signal_crossings_is_na(self):
        a=aggregate([self.record()],1);self.assertEqual(a['n_valid_tls_crossings'],0)
        self.assertIsNone(a['signal_compliance'])

    def test_policy_failure_kept_in_denominator_infra_not(self):
        a=self.record(failure='policy_invalid_action');b=self.record(infra='socket_disconnect')
        b['requested_case_uid']='other'
        r=aggregate([a,b],3);self.assertEqual(r['n_valid'],1)
        self.assertEqual(r['n_invalid_attempts'],1);self.assertEqual(r['n_missing_valid'],2)
        self.assertEqual(r['completion_rate'],0)

    def test_exact_collision_threshold(self):
        rows=[]
        for i in range(100):
            row=self.record([dict(type='collision')] if i<5 else [])
            row['requested_case_uid']=str(i);rows.append(row)
        self.assertFalse(aggregate(rows,100)['observed_collision_rate_below_5pct'])
        rows.pop(0);self.assertTrue(aggregate(rows,99)['observed_collision_rate_below_5pct'])

    def test_duplicates_rejected_and_empty_has_no_rate(self):
        r=self.record()
        with self.assertRaises(ValueError):aggregate([r,r],2)
        self.assertIsNone(aggregate([],100)['collision_rate'])

    def test_dev_final_disjoint_and_paired_demand_seeds(self):
        dev=make_panel(self.contract,'dev');final=make_panel(self.contract,'final')
        heavy=make_panel(self.contract,'final',demand_multiplier=2)
        self.assertEqual(len(dev['cases']),100)
        self.assertFalse({c['case_uid'] for c in dev['cases']} & {c['case_uid'] for c in final['cases']})
        self.assertEqual([c['seeds'] for c in final['cases']],[c['seeds'] for c in heavy['cases']])
        self.assertEqual(dev,make_panel(self.contract,'dev'))

    def test_reset_transport_failure_excluded_insertion_failure_included(self):
        panel=make_panel(self.contract,'contract_check',{'A':1})
        e=FakeEnv()
        for exc,valid in [(OSError('socket lost'),0),(RuntimeError('Ego insertion failed after 30s; fixture'),1)]:
            e.reset=lambda **kw: (_ for _ in ()).throw(exc)
            records,summary=evaluate_cases(None,e,panel)
            self.assertEqual(summary['n_valid'],valid)
            self.assertFalse(summary['evaluation_complete'] if not valid else summary['n_completed'])
            self.assertIsNone(records[0]['elapsed_s'])
            self.assertIsNone(summary['mean_elapsed_all'])

    def test_nan_policy_is_counted_as_failure_not_transport_error(self):
        env=SumoKCityEnv(background=False,debug_warmup_s=0);self.addCleanup(env.close)
        class InvalidPolicy:
            def predict(self,*a,**kw):return [float('nan'),0]
        rows,summary=evaluate_cases(InvalidPolicy(),env,make_panel(self.contract,'contract_check',{'A':1}))
        self.assertEqual(summary['n_valid'],1);self.assertEqual(summary['n_completed'],0)
        self.assertEqual(rows[0]['primary_end_reason'],'policy_invalid_action')

    def test_evaluation_rejects_policy_weight_mutation(self):
        env=SumoKCityEnv(background=False,debug_warmup_s=0);self.addCleanup(env.close)
        class MutatingFixture:
            def __init__(self):self.weight=0.
            def state_dict(self):return {'weight':torch.tensor([self.weight])}
            def predict(self,*a,**kw):self.weight+=1;return [float('nan'),0]
        with self.assertRaisesRegex(RuntimeError,'mutated policy weights'):
            evaluate_cases(MutatingFixture(),env,make_panel(self.contract,'contract_check',{'A':1}))

    def test_yellow_entry_and_unknown_signal_are_distinct(self):
        env=SumoKCityEnv(background=False,debug_warmup_s=0);self.addCleanup(env.close);env.reset(seed=1)
        opt=env.geometry.links[1][0]
        before=dict(route_index=1,lane_id=opt['from_lane']);after=dict(route_index=1,lane_id=opt['via'][0])
        yellow=env._boundary_events(before,after,10,{'647':'y'*20})[0]
        unknown=env._boundary_events(before,after,10,{})[0]
        self.assertTrue(yellow['classification_valid']);self.assertFalse(yellow['red_entry'])
        self.assertFalse(unknown['classification_valid'])

    def test_teleport_api_event_is_failure_even_with_live_snapshot(self):
        env=SumoKCityEnv(background=False,debug_warmup_s=0);self.addCleanup(env.close);env.reset(seed=2)
        with patch.object(env.conn.simulation,'getStartingTeleportIDList',return_value=[env.ego_id]):
            _,_,terminated,_,info=env.step([0,0])
        self.assertTrue(terminated);self.assertEqual(info['end_reason'],'teleport')
        self.assertTrue(info['next_state']['ego_alive'])


if __name__ == '__main__':unittest.main()
