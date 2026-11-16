"""Bounded environment fixtures and real SUMO integration, no learning updates."""
from pathlib import Path
from copy import deepcopy
import unittest
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kcity.env.env import SumoKCityEnv
from kcity.env.route import RouteGeometry
from kcity.env.config import load_contract, ContractError
from kcity.env.scenarios import sumo_library


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=load_contract();lib=sumo_library()
        cls.net=lib.net.readNet(str(ROOT/cls.spec['protocol']['assets']['network']['path']),withInternal=True)
        cls.scenario=cls.spec['scenario_manifest']['scenarios'][1]
        cls.g=RouteGeometry(cls.net,cls.scenario)

    def test_progress_is_continuous_through_short_and_internal_lanes(self):
        g=self.g
        for i in range(len(g.links)):
            regular=g.net.getEdge(g.edges[i]).getLane(0)
            # Use the route-permitted lane, including Lane1 at B's first exit.
            option=g.links[i][0];regular=g.net.getLane(option['from_lane'])
            begin=g.locate(g.edges[i],regular.getID(),regular.getLength(),i)
            nominal=min(o['length'] for o in g.links[i])
            seq=option['via'];last=begin
            for lane_id in seq:
                lane=g.net.getLane(lane_id)
                p0=g.locate(lane.getEdge().getID(),lane_id,0.,i)
                p1=g.locate(lane.getEdge().getID(),lane_id,lane.getLength(),i)
                self.assertAlmostEqual(p0,last,places=6);self.assertGreaterEqual(p1,p0);last=p1
            nxt=g.net.getLane(option['to_lane'])
            self.assertAlmostEqual(last,g.locate(g.edges[i+1],nxt.getID(),0.,i+1),places=6)

    def test_goal_progress_and_wrong_route(self):
        g=self.g;goal=self.scenario['goal'];lane=g.net.getEdge(goal['edge']).getLane(goal['lane_index'])
        self.assertAlmostEqual(g.locate(goal['edge'],lane.getID(),goal['arrival_position_m'],len(g.edges)-1),g.total)
        with self.assertRaises(ContractError):g.locate('3#4','3#4_0',5,0)

    def test_corridor_crosses_internal_and_short_edges(self):
        seg=self.g.corridor('-3#4_1',60,0,front_range=100)
        ids={s[0] for s in seg}
        self.assertIn('-3#5_0',ids);self.assertIn('-3#7_0',ids)
        self.assertTrue(any(l.startswith(':') for l in ids))
        self.assertIsNone(self.g._next('-3#4_0',0))

    def test_neighbor_uses_route_distance_across_edge_boundary(self):
        ego=dict(id='ego',lane_id='-3#4_1',lane=1,lane_pos=65,road_id='-3#4',
                 route_index=0,length_m=4.5)
        other=dict(id='ahead',lane_id='-3#6_0',lane_pos=1,speed=2,length_m=4.5)
        block=self.g.lane_features(ego,[other],0)
        self.assertEqual(block['front']['id'],'ahead');self.assertGreaterEqual(block['front']['gap'],0)


class GymIntegrationTests(unittest.TestCase):
    def create(self,**kwargs):
        e=SumoKCityEnv(background=False,debug_warmup_s=0,**kwargs)
        self.addCleanup(e.close);return e

    def test_reset_seed_reproduces_actual_traffic_not_only_requests(self):
        e=SumoKCityEnv(background=True)
        self.addCleanup(e.close)
        a,ia=e.reset(seed=42);b,ib=e.reset(seed=42)
        self.assertEqual(ia['initial_state_sha256'],ib['initial_state_sha256'])
        self.assertTrue(np.array_equal(a,b))
        _,ic=e.reset(seed=43)
        self.assertNotEqual(ia['initial_state_sha256'],ic['initial_state_sha256'])
        self.assertGreater(ia['state']['traffic']['running_hv'],0)

    def test_connections_are_isolated_and_close_is_idempotent(self):
        a,b=self.create(),self.create()
        a.reset(seed=0);b.reset(seed=1)
        self.assertNotEqual(a.label,b.label)
        time_b=b.conn.simulation.getTime();a.step([0,0])
        self.assertEqual(time_b,b.conn.simulation.getTime())
        a.close();a.close();obs,*_=b.step([0,0])
        self.assertTrue(b.observation_space.contains(obs))

    def test_real_step_raw_clipped_state_and_substeps(self):
        e=self.create();obs,reset=e.reset(seed=0)
        self.assertIsNone(e.spec)  # Reserved Gym EnvSpec is not our config dict.
        self.assertEqual(obs.shape,(73,));self.assertEqual(obs.dtype,np.float32)
        state=reset['state'];_,reward,term,trunc,i=e.step([2.,0])
        self.assertEqual(i['state'],state)
        self.assertEqual(i['executed_substeps'],5);self.assertAlmostEqual(i['control_dt_s'],.5)
        self.assertEqual(i['action_raw'],[2.,0]);self.assertEqual(i['action']['env_input'],[1.,0])
        self.assertAlmostEqual(i['action']['accel_request_mps2'],2.)
        self.assertAlmostEqual(reward,sum(i['reward_components'].values()))
        self.assertFalse(term or trunc)
        self.assertEqual(i['next_state']['ego_speedMode'],31)
        self.assertEqual(i['next_state']['ego_laneChangeMode'],512)
        tick=e._tick()
        for bad in [[float('nan'),0],[0],[0,0,0]]:
            with self.assertRaises(ValueError):e.step(bad)
        self.assertEqual(tick,e._tick())

    def test_substep_state_matches_full_snapshot_fields(self):
        """step() reads _substep_state() on inner substeps; each field must equal the full snapshot."""
        e=SumoKCityEnv(background=True);self.addCleanup(e.close);e.reset(seed=3)
        for action in [[1.,0],[.3,1.],[-.5,0],[0,-1.]]*3:
            light,full=e._substep_state(),e.get_privileged_state()
            self.assertEqual(light['vehicles'],[v for v in full['vehicles'] if v['is_ego']])
            self.assertEqual(light['ego_alive'],full['ego_alive'])
            self.assertEqual(light['signals'],[dict(id=s['id'],state=s['state']) for s in full['signals']])
            self.assertEqual(light['traffic'],{k:full['traffic'][k] for k in ['running_hv','pending_hv']})
            self.assertEqual(light['route_state']['route_valid'],full['route_state']['route_valid'])
            *_,term,trunc,_=e.step(action)
            if term or trunc:break

    def test_lane_mask_missing_lane_and_cooldown(self):
        e=self.create(scenario_id='B');_,i=e.reset(seed=0)
        self.assertEqual(i['action_mask'],[True,True,False])
        _,_,_,_,bad=e.step([0,-1])
        self.assertEqual(bad['action']['known_rejection_reasons'],['missing_lane'])
        _,_,_,_,changed=e.step([0,1])
        self.assertTrue(changed['action']['lane_change_applied'])
        self.assertTrue(changed['action']['lane_change_executed'])
        self.assertEqual(e.get_action_mask(),[False,True,False])
        _,_,_,_,cool=e.step([0,-1])
        self.assertEqual(cool['action']['known_rejection_reasons'],['cooldown'])

    def test_finite_deadline_is_termination_and_exact_tick(self):
        e=self.create(debug_episode_limit_s=.7);e.reset(seed=0)
        self.assertFalse(e.step([0,0])[2])
        obs,_,term,trunc,i=e.step([0,0])
        self.assertTrue(term);self.assertFalse(trunc)
        self.assertEqual(i['executed_substeps'],2);self.assertEqual(i['end_reason'],'deadline')
        self.assertAlmostEqual(i['episode_time_s'],.7)
        with self.assertRaises(RuntimeError):e.step([0,0])

    def test_removed_vehicle_has_terminal_absorbing_observation(self):
        e=self.create();e.reset(seed=0)
        e.conn.vehicle.remove(e.ego_id)
        obs,_,term,trunc,i=e.step([0,0])
        self.assertTrue(term);self.assertFalse(trunc);self.assertEqual(i['end_reason'],'removal')
        self.assertFalse(i['next_state']['ego_alive']);self.assertIsNone(i['next_state']['ego_x'])
        self.assertFalse(i['next_observation_valid']);self.assertTrue(np.array_equal(obs,np.zeros(73)))

    def test_boundary_fixture_tracks_red_and_skipped_occurrences(self):
        e=self.create();e.reset(seed=0)
        opt=e.geometry.links[1][0]
        before=dict(route_index=1,lane_id=opt['from_lane'])
        after=dict(route_index=1,lane_id=opt['via'][0])
        states={'647':'r'*20}
        events=e._boundary_events(before,after,10,states)
        self.assertEqual(len(events),1);self.assertTrue(events[0]['red_entry'])
        self.assertEqual(events[0]['link_index'],2)
        self.assertEqual(e._boundary_events(after,dict(route_index=2,lane_id=opt['to_lane']),11,states),[])

    def test_actual_red_entry_fixture_terminates(self):
        e=self.create();e.reset(seed=0)
        # Fault injection intentionally overrides common safety for this fixture
        # only. It is never a performance/evaluation episode.
        e.conn.trafficlight.setRedYellowGreenState('647','r'*len(e.conn.trafficlight.getRedYellowGreenState('647')))
        e.conn.vehicle.moveTo(e.ego_id,'-13_0',26.36)
        e.conn.vehicle.setSpeedMode(e.ego_id,0)
        e.conn.vehicle.setSpeed(e.ego_id,7.)
        e._state=e.get_privileged_state();e._obs,e._detected,e._mask=e._observe(e._state)
        _,_,term,trunc,i=e.step([1,0])
        self.assertTrue(term);self.assertFalse(trunc)
        self.assertEqual(i['end_reason'],'red_entry')
        self.assertTrue(any(x.get('red_entry') for x in i['events']))
        self.assertLess(i['executed_substeps'],5)

    def test_actual_collision_fixture_terminates(self):
        e=self.create();e.reset(seed=0)
        e.conn.vehicle.add('fixture_blocker','research_task',typeID='hv_IDM',
                           departLane='0',departPos='30',departSpeed='0')
        e.conn.simulationStep()
        self.assertIn('fixture_blocker',e.conn.vehicle.getIDList())
        e.conn.vehicle.moveTo(e.ego_id,'-68_0',30.)
        e.conn.vehicle.setSpeedMode(e.ego_id,0)
        e._state=e.get_privileged_state();e._obs,e._detected,e._mask=e._observe(e._state)
        _,_,term,trunc,i=e.step([1,0])
        self.assertTrue(term);self.assertFalse(trunc)
        self.assertEqual(i['end_reason'],'collision');self.assertTrue(i['event']['collided'])

    def test_inside_junction_mask_keeps_only_stay(self):
        e=self.create(scenario_id='B');e.reset(seed=0)
        via=e.geometry.links[0][0]['via'][0]
        e.conn.vehicle.moveTo(e.ego_id,via,.1)
        e._state=e.get_privileged_state();obs,_,mask=e._observe(e._state)
        self.assertEqual(mask,[False,True,False]);self.assertEqual(obs[51],1.)

    def test_actual_off_route_fixture_terminates(self):
        e=self.create();e.reset(seed=0)
        x,y=e.net.getLane('3#4_0').getShape()[1]
        e.conn.vehicle.moveToXY(e.ego_id,'3#4',0,x,y,keepRoute=0,matchThreshold=5)
        e._state=e.get_privileged_state();e._obs,e._detected,e._mask=e._observe(e._state)
        obs,_,term,trunc,i=e.step([0,0])
        self.assertTrue(term);self.assertFalse(trunc)
        self.assertEqual(i['end_reason'],'wrong_route');self.assertFalse(i['next_observation_valid'])


if __name__=='__main__':unittest.main()
