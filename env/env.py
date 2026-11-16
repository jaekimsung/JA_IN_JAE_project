"""K-CITY Gym environment: finite A/B/C routes with background traffic, isolated TraCI connections.

Each decision runs 5 SUMO ticks (0.1 s). No learner, expert or dataset writer is started here.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET

import gymnasium as gym
from gymnasium import spaces
import numpy as np

from env.config import (DEFAULT_PROTOCOL, ContractError, digest, load_contract,
    make_case, positive, repository_path, traffic_requests)
from env.route import RouteGeometry
from env.observation import build_observation
from env.scenarios import sumo_library, validate_contract

IMPLEMENTATION_ID='KC-ENV-v3-kc04-candidate'



class SumoKCityEnv(gym.Env):
    metadata={'render_modes':['human']}

    def __init__(self, protocol=DEFAULT_PROTOCOL, scenario_id='A', *, background=True,
                 gui=False, artifact_dir=None, debug_warmup_s=None, debug_episode_limit_s=None):
        super().__init__()
        self.contract=load_contract(protocol)
        self.structural,self.background_routes=validate_contract(self.contract)
        self.sumolib=sumo_library()
        import traci
        self.traci=traci
        self.net=self.sumolib.net.readNet(str(repository_path(self.contract['protocol']['assets']['network']['path'])),withInternal=True)
        self.scenario_id=scenario_id
        self.background=bool(background);self.gui=gui
        self.artifact_root=Path(artifact_dir) if artifact_dir is not None else None
        if self.artifact_root:self.artifact_root.mkdir(parents=True,exist_ok=True)
        for name,value in [('debug_warmup_s',debug_warmup_s),('debug_episode_limit_s',debug_episode_limit_s)]:
            if value is not None and (not math.isfinite(value) or value<0 or (name=='debug_episode_limit_s' and value==0)):
                raise ValueError(name+' must be finite and nonnegative (limit positive)')
        self.debug_warmup_s=debug_warmup_s;self.debug_episode_limit_s=debug_episode_limit_s
        self.action_space=spaces.Box(-1,1,shape=(2,),dtype=np.float32)
        self.observation_space=spaces.Box(-1,1,shape=(73,),dtype=np.float32)
        self.conn=None;self.label=None;self._temp=None;self._stdout=None
        self._done=True;self.ego_id='kcity_ego';self.case=None

    def _close_connection(self):
        if self.conn is not None:
            try:self.conn.close()
            finally:self.conn=None
        if self._stdout is not None:self._stdout.close();self._stdout=None
        if self._temp is not None:self._temp.cleanup();self._temp=None

    def close(self):
        self._close_connection();self._done=True

    def _routes_xml(self):
        source=ET.parse(repository_path(self.contract['protocol']['assets']['routes']['path'])).getroot()
        out=ET.Element('routes')
        for v in source.findall('vType'):
            if v.get('id') in self.contract['protocol']['traffic']['vehicle_types']:
                out.append(deepcopy(v))
        ctl=self.contract['protocol']['control']
        ET.SubElement(out,'vType',id='research_ego',vClass='passenger',carFollowModel='IDM',
            length='4.5',width='1.8',accel=str(ctl['max_accel_mps2']),decel=str(ctl['max_decel_mps2']),
            emergencyDecel='8',tau='1.5',maxSpeed=str(ctl['speed_cap_mps']),speedFactor='1',speedDev='0',color='1,0,0')
        for name,edges in sorted(self.background_routes.items()):
            ET.SubElement(out,'route',id=name,edges=' '.join(edges))
        ET.SubElement(out,'route',id='research_task',edges=' '.join(self.case['scenario']['route_edges']))
        for r in self.requests:
            ET.SubElement(out,'vehicle',id=r['request_id'],type=r['vehicle_type'],
                route=r['route_id'],depart=str(r['requested_depart_s']),
                departLane=r['depart_lane'],departSpeed=str(r['depart_speed_mps']))
        ET.indent(out)
        ET.ElementTree(out).write(self.run_dir/'traffic.rou.xml',encoding='utf-8',xml_declaration=True)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._close_connection();self._done=True
        options=options or {}
        unknown=set(options)-{'scenario_id','namespace','case_index','demand_multiplier'}
        if unknown:raise ValueError('Unknown reset option: '+str(sorted(unknown)))
        index=options.get('case_index',seed if seed is not None else int(self.np_random.integers(0,2**31-1)))
        self.case=make_case(self.contract,options.get('namespace','contract_check'),
            options.get('scenario_id',self.scenario_id),index,options.get('demand_multiplier',1.0))
        self.p=self.contract['protocol'];self.dt=self.p['timing']['sumo_step_s']
        self.warmup=self.p['timing']['warmup_s'] if self.debug_warmup_s is None else self.debug_warmup_s
        self.horizon=self.case['scenario']['episode_limit_s'] if self.debug_episode_limit_s is None else self.debug_episode_limit_s
        for value in [self.warmup,self.horizon]:
            if not math.isclose(value/self.dt,round(value/self.dt),abs_tol=1e-8):
                raise ValueError('warmup and deadline must align with SUMO ticks')
        self.case['runtime_variant']=dict(implementation=IMPLEMENTATION_ID,background=self.background,
            warmup_s=self.warmup,horizon_s=self.horizon,debug_override=self.debug_warmup_s is not None or self.debug_episode_limit_s is not None)
        self.case['case_uid']=digest({k:v for k,v in self.case.items() if k!='case_uid'})
        self.geometry=RouteGeometry(self.net,self.case['scenario'])
        self.requests=traffic_requests(self.contract,self.case,self.background_routes,
            duration_s=self.warmup+self.horizon+30) if self.background else []
        self.label='kcity_'+uuid.uuid4().hex
        if self.artifact_root:
            self.run_dir=Path(tempfile.mkdtemp(prefix=self.label+'_',dir=self.artifact_root))
        else:
            self._temp=tempfile.TemporaryDirectory(prefix=self.label+'_');self.run_dir=Path(self._temp.name)
        self._routes_xml()
        (self.run_dir/'CASE.json').write_text(json.dumps(self.case,indent=2)+'\n')
        binary=self.sumolib.checkBinary('sumo-gui' if self.gui else 'sumo')
        if subprocess.check_output([binary,'--version'],text=True).splitlines()[0].split()[-1]!=self.p['expected_sumo_version']:
            raise RuntimeError('SUMO version does not match protocol')
        assets=self.p['assets']
        cmd=[binary,'-n',str(repository_path(assets['network']['path'])),'-r',str(self.run_dir/'traffic.rou.xml'),
            '-a',str(repository_path(assets['signals']['path'])),'--seed',str(self.case['seeds']['sumo']),
            '--step-length',str(self.dt),'--time-to-teleport','-1','--collision.action','warn',
            '--collision.check-junctions','true','--no-step-log','true',
            '--error-log',str(self.run_dir/'sumo.warnings.log'),
            '--save-state.rng','true','--save-state.precision','17']
        if self.gui:cmd+=['--start','--quit-on-end']
        self._stdout=(self.run_dir/'sumo.stdout.log').open('w')
        try:
            self.traci.start(cmd,label=self.label,stdout=self._stdout)
            self.conn=self.traci.getConnection(self.label)
            for _ in range(round(self.warmup/self.dt)):self.conn.simulationStep()
            start=self.case['scenario']['start'];goal=self.case['scenario']['goal']
            self.conn.vehicle.add(self.ego_id,'research_task',typeID='research_ego',
                departLane=str(start['lane_index']),departPos=str(start['position_m']),
                departSpeed=str(start['speed_mps']),arrivalLane=str(goal['lane_index']),
                arrivalPos=str(goal['arrival_position_m']))
            self.conn.vehicle.setSpeedMode(self.ego_id,self.p['control']['speed_mode'])
            self.conn.vehicle.setLaneChangeMode(self.ego_id,self.p['control']['lane_change_mode'])
            insertion_wait=0
            while self.ego_id not in self.conn.vehicle.getIDList() and insertion_wait<300:
                self.conn.simulationStep();insertion_wait+=1
            if self.ego_id not in self.conn.vehicle.getIDList():
                raise RuntimeError('Ego insertion failed after 30s; no Episode was silently dropped')
            self.episode_start_tick=self._tick();self.deadline_tick=self.episode_start_tick+round(self.horizon/self.dt)
            self.cooldown_until=self.episode_start_tick;self.step_count=0;self._lane_request=None;self._action_history=[]
            self.ever_collision=False;self.ever_red=False;self._done=False
            self._state=self.get_privileged_state();self._obs,self._detected,self._mask=self._observe(self._state)
            self.last_progress=self._state['ego_route_progress_m'];self.initial_state_sha256=digest(self._state)
            self.elapsed_ticks=0
            return self._obs.copy(),dict(case=deepcopy(self.case),state=deepcopy(self._state),
                action_mask=list(self._mask),initial_state_sha256=self.initial_state_sha256,
                insertion_wait_s=insertion_wait*self.dt,implementation_id=IMPLEMENTATION_ID,
                training_ready=False,connection_label=self.label)
        except BaseException:
            self._close_connection();raise

    def _tick(self):
        return round(self.conn.simulation.getTime()/self.dt)

    def _vehicle(self, vid):
        v=self.conn.vehicle
        x,y,z=v.getPosition3D(vid)
        return dict(id=vid,x=x,y=y,z=z,speed=v.getSpeed(vid),accel_mps2=v.getAcceleration(vid),
            angle_deg=v.getAngle(vid),lane=v.getLaneIndex(vid),lane_id=v.getLaneID(vid),
            road_id=v.getRoadID(vid),lane_pos=v.getLanePosition(vid),
            route_index=v.getRouteIndex(vid),length_m=v.getLength(vid),type_id=v.getTypeID(vid),
            is_ego=vid==self.ego_id,allowed_speed_mps=v.getAllowedSpeed(vid))

    def get_privileged_state(self):
        if self.conn is None:raise RuntimeError('Environment must be reset first')
        vehicles=[self._vehicle(vid) for vid in sorted(self.conn.vehicle.getIDList())]
        ego=next((v for v in vehicles if v['is_ego']),None)
        pending=list(self.conn.simulation.getPendingVehicles())
        now=self.conn.simulation.getTime()  # one query per snapshot, not one per request
        state=dict(sim_tick=round(now/self.dt),sim_time_s=now,
            ego_alive=ego is not None,snapshot_valid=True,vehicles=vehicles,
            ego_x=None,ego_y=None,ego_z=None,ego_speed=None,ego_accel=None,ego_angle_deg=None,
            ego_lane=None,ego_lane_id=None,ego_road_id=None,ego_lane_pos=None,
            ego_route_index=None,ego_route_progress_m=None,ego_distance_m=None,
            ego_allowed_speed_mps=None,ego_waiting_s=None,ego_speedMode=None,ego_laneChangeMode=None,
            signals=[dict(id=t,program_id=self.conn.trafficlight.getProgram(t),
                phase_index=self.conn.trafficlight.getPhase(t),state=self.conn.trafficlight.getRedYellowGreenState(t))
                for t in sorted(self.conn.trafficlight.getIDList())],
            traffic=dict(running_hv=len(vehicles)-(ego is not None),pending_hv=sum(v!=self.ego_id for v in pending),
                active_request_count=sum(r['requested_depart_s']<=now for r in self.requests),
                requested_lambda_vph=self.case['requested_lambda_vph'] if self.background else 0),
            quality=dict(query_errors=[],missing_vehicle_ids=[]))
        if ego:
            mapping={'x':'ego_x','y':'ego_y','z':'ego_z','speed':'ego_speed','accel_mps2':'ego_accel',
                'angle_deg':'ego_angle_deg','lane':'ego_lane','lane_id':'ego_lane_id','road_id':'ego_road_id',
                'lane_pos':'ego_lane_pos','route_index':'ego_route_index','allowed_speed_mps':'ego_allowed_speed_mps'}
            state.update({out:ego[key] for key,out in mapping.items()})
            try:state['ego_route_progress_m']=self.geometry.locate(ego['road_id'],ego['lane_id'],ego['lane_pos'],ego['route_index'])
            except ContractError:state['ego_route_progress_m']=None
            state.update(ego_distance_m=self.conn.vehicle.getDistance(self.ego_id),
                ego_waiting_s=self.conn.vehicle.getWaitingTime(self.ego_id),
                ego_speedMode=self.conn.vehicle.getSpeedMode(self.ego_id),
                ego_laneChangeMode=self.conn.vehicle.getLaneChangeMode(self.ego_id))
        state['route_state']=dict(route_id=self.case['scenario']['id'],
            route_edges=list(self.geometry.edges),goal=deepcopy(self.case['scenario']['goal']),
            route_length_m=self.geometry.total,
            route_valid=ego is None or state['ego_route_progress_m'] is not None)
        return state

    def _substep_state(self):
        """Fields the substep loop reads: ego, HV counts, signal states, route validity.

        Values equal the same keys of get_privileged_state() at this tick (TraCI getters
        are side-effect free). The full snapshot is taken once after the loop.
        """
        ids=self.conn.vehicle.getIDList()
        ego=self._vehicle(self.ego_id) if self.ego_id in ids else None
        pending=self.conn.simulation.getPendingVehicles()
        progress=None
        if ego:
            try:progress=self.geometry.locate(ego['road_id'],ego['lane_id'],ego['lane_pos'],ego['route_index'])
            except ContractError:progress=None
        return dict(vehicles=[ego] if ego else [],ego_alive=ego is not None,
            signals=[dict(id=t,state=self.conn.trafficlight.getRedYellowGreenState(t))
                for t in sorted(self.conn.trafficlight.getIDList())],
            traffic=dict(running_hv=len(ids)-(ego is not None),pending_hv=sum(v!=self.ego_id for v in pending)),
            route_state=dict(route_valid=ego is None or progress is not None))

    def _observe(self,state):
        ego=next((v for v in state['vehicles'] if v['is_ego']),None)
        tls=list(self.conn.vehicle.getNextTLS(self.ego_id)) if ego else []
        if ego and state['ego_route_progress_m'] is None:
            return np.zeros(73,dtype=np.float32),[],[False,True,False]
        return build_observation(self.geometry,ego,state['vehicles'],tls,
            max(0,self.deadline_tick-self._tick())*self.dt,self.horizon,
            max(0,self.cooldown_until-self._tick())*self.dt,self.p['control']['speed_cap_mps'])

    def get_detected_vehicles(self):
        return deepcopy(self._detected)

    def get_action_mask(self):
        return list(self._mask)

    def _boundary_events(self,before,after,tick,tls_states):
        """Route occurrences crossed in one substep, including skipped short Edges."""
        events=[]
        if before is None or after is None:return events
        old=before['route_index'];new=after['route_index']
        for i in range(max(0,old),min(new+1,len(self.geometry.links))):
            opts=self.geometry.links[i]
            before_inside=any(before['lane_id'] in o['via'] for o in opts)
            after_inside=any(after['lane_id'] in o['via'] for o in opts)
            crossed=(not before_inside and after_inside) or (new>i and not before_inside)
            if not crossed:continue
            matches=[o for o in opts if o['from_lane']==before['lane_id'] or after['lane_id'] in o['via'] or o['to_lane']==after['lane_id']]
            chosen=matches[0] if len(matches)==1 else opts[0] if len(opts)==1 else None
            if chosen is not None and not chosen['tls']:continue
            state=None
            if chosen is not None:
                full=tls_states.get(chosen['tls'],'');idx=chosen['link_index']
                if 0<=idx<len(full):state=full[idx]
            events.append(dict(type='tls_crossing',sim_tick=tick,route_occurrence=i,
                tls_id=chosen['tls'] if chosen else None,link_index=chosen['link_index'] if chosen else None,
                signal_before=state,classification_valid=state in ['r','y','Y','G','g','o','O'],
                red_entry=state=='r',mapping_basis='route occurrence and before/after Lane'))
        return events

    def step(self,action):
        if self._done or self.conn is None:raise RuntimeError('Call reset before stepping or after Episode end')
        raw=np.asarray(action,dtype=np.float32)
        if raw.shape!=(2,) or not np.isfinite(raw).all():raise ValueError('Action must be a finite two-vector')
        bounded=np.clip(raw,-1,1);lane_cmd=1 if bounded[1]>=.5 else -1 if bounded[1]<=-.5 else 0
        category={1:0,0:1,-1:2}[lane_cmd]
        before=deepcopy(self._state);tick0=self._tick();mask=list(self._mask)
        reasons=[];issued=False;target=None;ctl=self.p['control']
        accel=float(bounded[0])*(ctl['max_accel_mps2'] if bounded[0]>=0 else ctl['max_decel_mps2'])
        alive_now=self.ego_id in self.conn.vehicle.getIDList()
        if alive_now:
            self.conn.vehicle.setAcceleration(self.ego_id,accel,self.p['timing']['control_step_s'])
        else:
            reasons.append('vehicle_absent')
        if not alive_now:
            pass
        elif lane_cmd and not mask[category]:
            reasons.append('internal_junction' if before['ego_road_id'].startswith(':') else
                'cooldown' if self.cooldown_until>tick0 else 'missing_lane')
        elif lane_cmd:
            target=before['ego_lane']+lane_cmd
            self.conn.vehicle.changeLane(self.ego_id,target,ctl['lane_command_duration_s'])
            self.cooldown_until=tick0+round(ctl['lane_cooldown_s']/self.dt);issued=True
            self._lane_request=dict(target=target,road_id=before['ego_road_id'],
                until_tick=tick0+round(ctl['lane_command_duration_s']/self.dt))
        events=[];reason=None;actual=[];samples=[];departed_hv=arrived_hv=0;executed=False
        current=before
        for _ in range(self.p['timing']['substeps']):
            old_ego=next((v for v in current['vehicles'] if v['is_ego']),None)
            tls={t['id']:t['state'] for t in current['signals']}
            self.conn.simulationStep();tick=self._tick()
            departures=list(self.conn.simulation.getDepartedIDList());arrivals=list(self.conn.simulation.getArrivedIDList())
            departed_hv+=sum(v!=self.ego_id for v in departures);arrived_hv+=sum(v!=self.ego_id for v in arrivals)
            current=self._substep_state();new_ego=next((v for v in current['vehicles'] if v['is_ego']),None)
            events.extend(self._boundary_events(old_ego,new_ego,tick,tls))
            for c in self.conn.simulation.getCollisions():
                if self.ego_id in [c.collider,c.victim]:
                    events.append(dict(type='collision',sim_tick=tick,collider=c.collider,victim=c.victim,collision_type=c.type))
            if self.ego_id in self.conn.simulation.getStartingTeleportIDList():events.append(dict(type='teleport',sim_tick=tick))
            if old_ego and new_ego and old_ego['road_id']==new_ego['road_id'] and not old_ego['road_id'].startswith(':') and old_ego['lane']!=new_ego['lane']:
                executed=True;events.append(dict(type='lane_change',sim_tick=tick,from_lane=old_ego['lane_id'],to_lane=new_ego['lane_id']))
            if new_ego:actual.append(new_ego['accel_mps2'])
            leader=self.conn.vehicle.getLeader(self.ego_id,100) if new_ego else None
            next_tls=list(self.conn.vehicle.getNextTLS(self.ego_id)) if new_ego else []
            samples.append(dict(sim_tick=tick,dt_s=self.dt,
                speed_mps=new_ego['speed'] if new_ego else None,
                running_hv=current['traffic']['running_hv'],pending_hv=current['traffic']['pending_hv'],
                leader_gap_m=float(leader[1]) if leader else None,
                next_tls_distance_m=float(next_tls[0][2]) if next_tls else None,
                next_tls_state=next_tls[0][3] if next_tls else None))
            # Preserve all simultaneous facts before choosing a primary reason.
            if current['ego_alive'] and not current['route_state']['route_valid']:
                events.append(dict(type='wrong_route',sim_tick=tick))
            if self.ego_id in arrivals:
                goal=self.case['scenario']['goal']
                correct=bool(old_ego and old_ego['road_id']==goal['edge'] and old_ego['lane']==goal['lane_index'])
                events.append(dict(type='arrival',sim_tick=tick,correct_goal=correct))
                if not correct:events.append(dict(type='wrong_route',sim_tick=tick))
            elif not current['ego_alive'] and not any(e['type']=='teleport' for e in events):
                events.append(dict(type='removal',sim_tick=tick,known_reason='unknown'))
            if tick>=self.deadline_tick:events.append(dict(type='deadline',sim_tick=tick))
            collision=any(e['type']=='collision' for e in events)
            red=any(e.get('red_entry',False) for e in events)
            self.ever_collision|=collision;self.ever_red|=red
            for candidate in ['collision','red_entry','wrong_route','teleport','removal','arrival','deadline']:
                if any(e['type']==candidate for e in events) or (candidate=='red_entry' and red):
                    reason=candidate;break
            if reason:break
        current=self.get_privileged_state()  # full snapshot once, at the last executed substep
        self.step_count+=1;self.elapsed_ticks=self._tick()-self.episode_start_tick
        self._state=current
        self._obs,self._detected,self._mask=self._observe(current)
        progress=current['ego_route_progress_m']
        if reason=='arrival':progress=self.geometry.total
        delta=0 if progress is None else max(0.,progress-self.last_progress)
        if progress is not None:self.last_progress=progress
        components=dict(progress=delta/10,arrival=10. if reason=='arrival' else 0.,
            collision=-20. if reason=='collision' else 0.,red_entry=-10. if reason=='red_entry' else 0.,
            invalid_request=-.02*bool(reasons),lane_change=-.01*executed,unjustified_wait=0.)
        # No unjustified-wait penalty is invented without a verified causal classifier.
        reward=float(sum(components.values()));self._done=reason is not None
        info=dict(case_uid=self.case['case_uid'],implementation_id=IMPLEMENTATION_ID,
            state=before,next_state=deepcopy(current),observation_valid=before['ego_alive'] and before['route_state']['route_valid'],
            next_observation_valid=current['ego_alive'] and current['route_state']['route_valid'],
            action_raw=raw.tolist(),policy_action_raw=raw.tolist(),
            action=dict(env_input=bounded.tolist(),accel_raw=float(bounded[0]),lane_change_raw=float(bounded[1]),
                lane_change=lane_cmd,lane_change_applied=issued,lane_change_executed=executed,
                accel_request_mps2=accel,accel_observed_mean_mps2=float(np.mean(actual)) if actual else None,
                lane_mask=mask,target_lane_index=target,known_rejection_reasons=reasons,sumo_override_reason='unknown'),
            action_mask=list(self._mask),events=events,substep_samples=samples,reward_components=components,
            end_reason=reason,executed_substeps=self._tick()-tick0,control_dt_s=(self._tick()-tick0)*self.dt,
            sim_tick_t=tick0,sim_tick_tp1=self._tick(),episode_time_s=self.elapsed_ticks*self.dt,
            event=dict(collided=any(e['type']=='collision' for e in events),
                arrived=any(e['type']=='arrival' for e in events),lane_before=before['ego_lane'],lane_after=current['ego_lane']),
            traffic_interval=dict(departed_hv=departed_hv,arrived_hv=arrived_hv),
            signal_classifier_complete=not any(e['type']=='tls_crossing' and not e['classification_valid'] for e in events),
            training_ready=False)
        self._action_history.append(raw.tolist())
        return self._obs.copy(),reward,self._done,False,info


    def save_resume_state(self, directory):
        """Native control-boundary checkpoint using deterministic current-Episode replay."""
        if self.conn is None or self._done:
            raise RuntimeError('Checkpoint requires a live environment at a control boundary')
        folder=Path(directory);folder.mkdir(parents=True,exist_ok=False)
        state=self.get_privileged_state()
        if state!=self._state:raise RuntimeError('Environment changed outside its step API')

        attrs=['episode_start_tick','deadline_tick','cooldown_until','step_count',
               'ever_collision','ever_red','last_progress','initial_state_sha256','elapsed_ticks','_lane_request']
        body=dict(schema='KC-ENV-RESUME-v2',strategy='replay_current_episode_v1',implementation_id=IMPLEMENTATION_ID,
            contract_sha256=digest(self.contract),case=self.case,
            constructor=dict(background=self.background,debug_warmup_s=self.debug_warmup_s,
                debug_episode_limit_s=self.debug_episode_limit_s,scenario_id=self.case['scenario_id']),
            attributes={k:getattr(self,k) for k in attrs},state=state,observation=self._obs.tolist(),
            detected=self._detected,mask=self._mask,action_history=self._action_history,numpy_rng=self.np_random.bit_generator.state,
            vehicle_modes={v['id']:[self.conn.vehicle.getSpeedMode(v['id']),
                self.conn.vehicle.getLaneChangeMode(v['id'])] for v in state['vehicles']})
        (folder/'environment.json').write_text(json.dumps(body,indent=2,allow_nan=False)+'\n')

    def load_resume_state(self, directory):
        folder=Path(directory);body=json.loads((folder/'environment.json').read_text())
        if (body['schema']!='KC-ENV-RESUME-v2' or body['strategy']!='replay_current_episode_v1' or
                body['implementation_id']!=IMPLEMENTATION_ID or body['contract_sha256']!=digest(self.contract)):
            raise ValueError('Environment checkpoint contract/source version mismatch')
        expected=dict(background=self.background,debug_warmup_s=self.debug_warmup_s,
            debug_episode_limit_s=self.debug_episode_limit_s,scenario_id=body['case']['scenario_id'])
        if expected!=body['constructor']:raise ValueError('Environment constructor mismatch')
        case=body['case']
        self.reset(options={k:case[k] for k in ['namespace','scenario_id','case_index','demand_multiplier']})
        if self.case!=case:raise ValueError('Regenerated case differs from saved case')
        if self.initial_state_sha256!=body['attributes']['initial_state_sha256']:
            raise RuntimeError('Initial case replay differs; exact resume refused')
        # SUMO save/load can lose hidden car-following/TraCI state. Re-execute
        # only this finite Episode from its deterministic reset. No policy,
        # optimizer or learner transition counters are advanced during replay.
        for action in body['action_history']:
            if self._done:raise RuntimeError('Checkpoint replay ended before saved boundary')
            self.step(action)
        for key,value in body['attributes'].items():
            if getattr(self,key)!=value:raise RuntimeError('Replayed environment counters differ: '+key)
        self.np_random.bit_generator.state=body['numpy_rng']
        modes={v['id']:[self.conn.vehicle.getSpeedMode(v['id']),
                self.conn.vehicle.getLaneChangeMode(v['id'])] for v in self._state['vehicles']}
        if (self._state!=body['state'] or self._obs.tolist()!=body['observation'] or
                self._detected!=body['detected'] or self._mask!=body['mask'] or modes!=body['vehicle_modes']):
            raise RuntimeError('Replayed SUMO/Python snapshot differs; exact resume refused')
        self.resume_replayed_control_steps=len(body['action_history'])
        return self._obs.copy()


class KCityExternalTimeLimit(gym.Wrapper):
    """Optional external decision budget; not the finite task's own deadline.

    Native task termination takes precedence. Terminal observation remains the
    current observation, and the downstream learner must bootstrap/truncate
    with an independent trace mask.
    """
    def __init__(self,env,max_episode_steps):
        super().__init__(env)
        if isinstance(max_episode_steps,bool) or not isinstance(max_episode_steps,int) or max_episode_steps<1:
            raise ValueError('External max_episode_steps must be a positive integer')
        self.max_episode_steps=max_episode_steps;self.elapsed=0;self.finished=True

    def reset(self,**kwargs):
        obs,info=self.env.reset(**kwargs);self.elapsed=0;self.finished=False
        return obs,info

    def step(self,action):
        if self.finished:raise RuntimeError('Reset after external time limit')
        obs,reward,terminated,truncated,info=self.env.step(action)
        self.elapsed+=1
        if not terminated and not truncated and self.elapsed>=self.max_episode_steps:
            truncated=True;info=dict(info,end_reason='external_limit')
        self.finished=terminated or truncated
        return obs,reward,terminated,truncated,info
