"""Situation and metric fixtures."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcity.env.env import SumoKCityEnv
from kcity.env.config import load_contract
from kcity.evaluation.metrics import EpisodeMetrics, aggregate
from kcity.env.config import ROOT, make_case
from kcity.training.experiment import load_experiment
from kcity.evaluation.evaluate import evaluate_cases


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


def make_panel(contract, namespace, counts):
    return dict(cases=[make_case(contract, namespace, sid, i) for sid, n in sorted(counts.items()) for i in range(n)])


class SituationTests(unittest.TestCase):
    def test_locations_match_network_and_routes(self):
        import xml.etree.ElementTree as ET
        from kcity.evaluation.situations import SITUATIONS, situation_of
        root=ET.parse(ROOT/'maps/kcity/kcity.net.xml').getroot()
        kinds={j.get('id'):j.get('type') for j in root.findall('junction')}
        ends={e.get('id'):e.get('to') for e in root.findall('edge') if e.get('function')!='internal'}
        lanes={e.get('id'):len(e.findall('lane')) for e in root.findall('edge')}
        signal,drop,plain=(SITUATIONS[k] for k in ['signal_chain','lane_drop','unsignalized'])
        self.assertTrue(all(kinds[j]=='traffic_light' for j in signal['junctions']))
        self.assertEqual([ends[e] for e in signal['approach_edges']],list(signal['junctions']))
        self.assertTrue(all(kinds[j]=='priority' for j in plain['junctions']))
        self.assertEqual({ends[e] for e in plain['approach_edges']},set(plain['junctions']))
        self.assertEqual((lanes['-3#4'],lanes['-3#5']),(2,1))
        scenarios={sid:make_case(load_contract(),'contract_check',sid,0)['scenario'] for sid in 'ABC'}
        self.assertEqual(sorted(scenarios['A']['required_tls_ids']),sorted(signal['junctions']))
        self.assertEqual(scenarios['B']['required_lane_change']['edge'],drop['approach_edges'][0])
        self.assertEqual(tuple(scenarios['C']['route_edges'][:2]),plain['approach_edges'])
        self.assertEqual(situation_of(':464_3'),'unsignalized');self.assertEqual(situation_of('-13'),'signal_chain')
        self.assertEqual(situation_of(':647_0'),'signal_chain');self.assertIsNone(situation_of('3#4'))

    def test_failure_is_attributed_to_the_situation_where_the_episode_ended(self):
        from kcity.evaluation import situations
        case=dict(scenario=dict(required_lane_change=dict(edge='-3#4',required_exit_lanes=[1])))
        def step(road,next_road,lane=0,events=(),speed=0.,cmd=0):
            ego=dict(id='ego',is_ego=True,road_id=next_road,lane=lane,x=0,y=0)
            other=dict(id='hv',is_ego=False,road_id=':464_1',lane=0,x=3,y=4)
            return dict(control_dt_s=.5,events=list(events),substep_samples=[],
                state=dict(ego_road_id=road,ego_lane_pos=20.,vehicles=[]),
                next_state=dict(ego_road_id=next_road,ego_lane=lane,ego_speed=speed,vehicles=[ego,other]),
                action=dict(lane_change=cmd,known_rejection_reasons=['cooldown'] if cmd else []))
        s=situations.new_state()
        situations.update(s,case,step('-3#4','-3#4',cmd=1))
        situations.update(s,case,step('-3#4','-3#4',lane=1,speed=3.,
            events=[dict(type='lane_change',from_lane='-3#4_0',to_lane='-3#4_1')]))
        situations.update(s,case,step('-3#8',':464_3',speed=3.))
        situations.update(s,case,step(':464_3',':464_3',speed=3.,events=[dict(type='collision')]))
        r=situations.finish(s,case,False)
        self.assertEqual(r['failure_situation'],'unsignalized');self.assertEqual(r['visited'],['lane_drop','unsignalized'])
        lane=r['lane_drop']
        self.assertEqual((lane['done'],lane['position_m'],lane['requests'],lane['rejected'],lane['wait_s']),(True,20.,1,1,.5))
        self.assertEqual(r['unsignalized'],dict(passes=1,passes_with_cross_traffic=1,min_distance_m=5.,collisions=1,yield_violations=0))
        self.assertIsNone(situations.finish(situations.new_state(),case,True)['failure_situation'])


class MetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.contract=load_contract()

    def record(self,events=(),failure=None,infra=None,vehicles=None):
        case=make_panel(self.contract,'contract_check',{'A':1})['cases'][0]
        state=dict(sim_tick=0,route_state=dict(route_valid=True,route_length_m=10),
                   ego_route_progress_m=0,traffic=dict(running_hv=5,requested_lambda_vph=600))
        if vehicles is not None:state['vehicles']=vehicles
        tracker=EpisodeMetrics(case,{'state':state})
        ns=deepcopy(state);ns['sim_tick']=2;ns['ego_route_progress_m']=2
        info=dict(sim_tick_t=0,sim_tick_tp1=2,control_dt_s=.2,
            episode_time_s=.2,substep_samples=[dict(sim_tick=i,dt_s=.1,speed_mps=v,
            running_hv=hv,pending_hv=0,leader_gap_m=None) for i,v,hv in [(1,0,2),(2,4,4)]],
            events=list(events),next_state=ns,action=dict(lane_change=1,
            known_rejection_reasons=[],accel_raw=1,lane_change_raw=1),
            action_raw=[2,1],traffic_interval=dict(departed_hv=1),end_reason='deadline')
        tracker.add(1,True,False,info)
        return tracker.finish(failure_reason=failure,infrastructure_error=infra)

    def test_near_hv_exposure_counts_vehicles_within_50m(self):
        ego=dict(id='kcity_ego',x=0.,y=0.,is_ego=True)
        hv=lambda i,x:dict(id=f'hv{i}',x=x,y=0.,is_ego=False)
        r=self.record(vehicles=[ego,hv(1,30.),hv(2,-49.),hv(3,80.)])
        self.assertEqual(r['near_HV_50m_mean'],2);self.assertEqual(r['near_HV_50m_max'],2)
        self.assertEqual(r['near_HV_50m_presence_fraction'],1)
        alone=self.record(vehicles=[ego,hv(3,80.)])
        self.assertEqual(alone['near_HV_50m_mean'],0);self.assertEqual(alone['near_HV_50m_presence_fraction'],0)
        unknown=self.record()  # no vehicle snapshot: exposure is unknown, not zero
        self.assertIsNone(unknown['near_HV_50m_mean']);self.assertIsNone(unknown['near_HV_50m_max'])

    def test_aggregate_reports_exposure_and_stops_for_every_valid_case(self):
        ego=dict(id='kcity_ego',x=0.,y=0.,is_ego=True)
        a=self.record(vehicles=[ego,dict(id='hv',x=10.,y=0.,is_ego=False)]);a['requested_case_uid']='a'
        b=self.record(vehicles=[ego]);b['requested_case_uid']='b'
        s=aggregate([a,b],2)
        self.assertEqual(s['exposure']['n_episodes'],2)
        self.assertEqual(s['exposure']['HV_start_mean'],5);self.assertEqual(s['exposure']['n_HV_start_below_10'],2)
        self.assertEqual(s['exposure']['near_HV_50m_mean'],.5);self.assertEqual(s['exposure']['near_HV_50m_presence_mean'],.5)
        self.assertEqual(s['stops']['n_deadline'],0);self.assertEqual(s['stops']['standstill_s_max'],.1)
        empty=aggregate([],1)
        self.assertIsNone(empty['exposure']['HV_start_mean']);self.assertEqual(empty['stops']['n_deadline'],0)

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

    def test_dev_final_panels_disjoint_and_paired_demand_seeds(self):
        spec=load_experiment()
        read=lambda name:__import__('json').loads((ROOT/spec['case_panels'][name]['path']).read_text())['cases']
        dev,final=read('dev'),read('final')
        self.assertEqual(len(dev),100);self.assertEqual(len(final),300)
        self.assertFalse({c['case_uid'] for c in dev}&{c['case_uid'] for c in final})
        by_demand={}
        for c in final:by_demand.setdefault(c['demand_multiplier'],[]).append(c['seeds'])
        self.assertEqual(sorted(by_demand),[1.0,1.5,2.0])
        self.assertTrue(by_demand[1.0]==by_demand[1.5]==by_demand[2.0])
        self.assertEqual(dev[0],make_case(self.contract,'dev',dev[0]['scenario_id'],dev[0]['case_index']))

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
