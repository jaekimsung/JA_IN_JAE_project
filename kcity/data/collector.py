"""KC-05 bounded, restartable expert collection; no learner is created."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import platform
import numpy as np
import subprocess
import xml.etree.ElementTree as ET

from kcity.env.config import ROOT,DEFAULT_PROTOCOL,digest,file_sha256,make_case,repository_path
from kcity.env.env import IMPLEMENTATION_ID
from kcity.policy.rule_expert import EXPERT_ID
from kcity.data.dataset import ShardWriter,episode_uid,make_transition
from kcity.evaluator import EpisodeMetrics

SOURCES=['kcity/policy/__init__.py','kcity/policy/rule_expert.py','kcity/data/collector.py',
    'kcity/data/dataset.py','kcity/evaluator.py','kcity/env/env.py','kcity/env/config.py',
    'kcity/env/observation.py','kcity/env/route.py','kcity/env/scenarios.py','tools/checks/collect_expert.py']


def build_config(env,expert,run_uid,plan=None):
    if not isinstance(run_uid,str) or not run_uid:raise ValueError('Stable run UID required')
    if plan is None:
        plan=[dict(scenario_id=sid,namespace=namespace,case_index=0,data_split=namespace)
              for namespace in ['expert_train','expert_val'] for sid in ['A','B','C']]
    resolved=[]
    for entry in plan:
        if entry['data_split'] not in ['expert_train','expert_val'] or entry['namespace']!=entry['data_split']:
            raise ValueError('Expert train/val seed namespaces and splits must match')
        case=make_case(env.contract,entry['namespace'],entry['scenario_id'],entry['case_index'],entry.get('demand_multiplier',1.))
        case['runtime_variant']=dict(implementation=IMPLEMENTATION_ID,background=env.background,
            warmup_s=env.contract['protocol']['timing']['warmup_s'] if env.debug_warmup_s is None else env.debug_warmup_s,
            horizon_s=case['scenario']['episode_limit_s'] if env.debug_episode_limit_s is None else env.debug_episode_limit_s,
            debug_override=env.debug_warmup_s is not None or env.debug_episode_limit_s is not None)
        case['case_uid']=digest({k:v for k,v in case.items() if k!='case_uid'})
        resolved.append(dict(case=case,data_split=entry['data_split']))
    if len({r['case']['case_uid'] for r in resolved})!=len(resolved):raise ValueError('Duplicate planned case')
    if json.loads(DEFAULT_PROTOCOL.read_text())!=env.contract['protocol']:
        raise ValueError('KC-05 collector is pinned to the current default candidate protocol')
    source={f:file_sha256(ROOT/f) for f in SOURCES}
    teacher=dict(id=EXPERT_ID,config=deepcopy(expert.config),source_sha256=source['kcity/policy/rule_expert.py'])
    teacher['fingerprint']=digest(teacher)
    assets=deepcopy(env.contract['protocol']['assets'])
    assets['scenarios']=deepcopy(env.contract['protocol']['scenario_manifest'])
    assets['protocol']=dict(path=str(DEFAULT_PROTOCOL.relative_to(ROOT)),sha256=file_sha256(DEFAULT_PROTOCOL))
    location=ET.parse(repository_path(assets['network']['path'])).getroot().find('location')
    return dict(schema_id='KC-COLLECTION-v1-candidate',run_uid=run_uid,
        data_purpose='KC05_pipeline_validation_NOT_RESEARCH_POOL',source_stage='debug',
        eligible_for_research_training=False,training_ready=False,contract=env.contract,
        teacher=teacher,source_sha256=source,asset_snapshots=assets,plan=resolved,
        environment=dict(background=env.background,debug_warmup_s=env.debug_warmup_s,
            debug_episode_limit_s=env.debug_episode_limit_s),
        coordinate_frame=dict(position_reference='SUMO_front_bumper_center',
            location=dict(location.attrib) if location is not None else None),
        episode_id_scheme='dataset_local_monotonic_registry; allocate/check release-global IDs before merging runs',
        runtime=dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,
            sumo_version=subprocess.check_output([env.sumolib.checkBinary('sumo'),'--version'],text=True).splitlines()[0]),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())


class ExpertCollector:
    def __init__(self,env,expert,writer):
        self.env,self.expert,self.writer=env,expert,writer
        self.config=writer.config;self.index=0;self.t=0;self.start_tick=None
        self.previous_interval=dict(departed_hv=0,arrived_hv=0);self.departure_history=[]
        self.metrics=None;self.completed_pending=[];self.obs=None;self.detected=[]
        saved,folder=writer.last_checkpoint()
        if saved is not None:
            if saved['committed_transitions']!=writer.count:raise ValueError('Collector/writer counter mismatch')
            self.index=saved['episode_index'];self.t=saved['t'];self.start_tick=saved['episode_start_tick']
            self.previous_interval=saved['previous_interval'];self.departure_history=saved['departure_history']
            if saved['active']:
                self.env.load_resume_state(folder/'environment')
                self.obs=self.env._obs.copy();self.detected=self.env.get_detected_vehicles()
                self.metrics=EpisodeMetrics.__new__(EpisodeMetrics)
                self.metrics.__dict__.update(saved['metrics'])
                self.metrics.commands=Counter({int(k):v for k,v in self.metrics.commands.items()})
                self.metrics.rejections=Counter(self.metrics.rejections)
                case=self.config['plan'][self.index]['case']
                if self.env.case!=case:raise ValueError('Restored case differs from data plan')

    def _start(self):
        case=self.config['plan'][self.index]['case']
        self.obs,reset=self.env.reset(options={k:case[k] for k in ['namespace','scenario_id','case_index','demand_multiplier']})
        if reset['case']!=case:raise ValueError('Runtime case differs from declared source/seed manifest')
        self.detected=self.env.get_detected_vehicles();self.t=0;self.start_tick=reset['state']['sim_tick']
        self.previous_interval=dict(departed_hv=0,arrived_hv=0);self.departure_history=[]
        self.metrics=EpisodeMetrics(case,reset)

    def checkpoint(self):
        return dict(schema='KC-COLLECTOR-RESUME-v1',episode_index=self.index,t=self.t,
            episode_start_tick=self.start_tick,previous_interval=self.previous_interval,
            departure_history=self.departure_history,active=self.metrics is not None,
            committed_transitions=self.writer.count+self.writer.pending,
            metrics=deepcopy(self.metrics.__dict__) if self.metrics is not None else None)

    def _commit(self):
        result=self.writer.commit(self.checkpoint(),self.completed_pending,
            self.env.save_resume_state if self.metrics is not None else None)
        if result is not None:self.completed_pending=[]

    def collect_until(self,absolute_cap):
        if isinstance(absolute_cap,bool) or not isinstance(absolute_cap,int) or not 1<=absolute_cap<=10000:
            raise ValueError('KC-05 validation collection is bounded to 1..10000 transitions')
        if absolute_cap<self.writer.count:raise ValueError('Absolute collection cap is behind committed progress')
        while self.index<len(self.config['plan']) and self.writer.count+self.writer.pending<absolute_cap:
            if self.metrics is None:self._start()
            entry=self.config['plan'][self.index];case=entry['case']
            before=self.obs.copy();detected=deepcopy(self.detected)
            action=self.expert.predict(before)
            nxt,reward,term,trunc,info=self.env.step(action)
            next_detected=self.env.get_detected_vehicles()
            last_case=term and self.index+1==len(self.config['plan'])
            reason=('budget' if self.writer.count+self.writer.pending+1==absolute_cap else
                    'shard' if self.writer.pending+1==self.writer.shard_rows else 'checkpoint' if last_case else None)
            row=make_transition(config=self.config,case=case,episode_index=self.index,t=self.t,
                attempt_uid=self.writer.attempt_uid,observation=before,detected=detected,
                next_observation=nxt,next_detected=next_detected,reward=reward,terminated=term,truncated=trunc,
                info=info,start_tick=self.start_tick,previous_interval=self.previous_interval,
                departure_history=self.departure_history,segment_reason=reason)
            self.writer.append(row)
            # Feed the stored full State into the metric accumulator as well;
            # an offline reader reconstructs exactly these summaries.
            self.metrics.add(row['reward_env_raw'],term,trunc,row)
            self.t+=1;self.obs=nxt;self.detected=next_detected
            self.previous_interval=deepcopy(info['traffic_interval'])
            self.departure_history.append([info['sim_tick_tp1'],info['traffic_interval']['departed_hv']])
            if term or trunc:
                self.completed_pending.append(dict(episode_uid=row['episode_uid'],episode=self.index,
                    case_uid=case['case_uid'],data_split=entry['data_split'],metrics=self.metrics.finish()))
                self.index+=1;self.t=0;self.metrics=None
                if self.index<len(self.config['plan']):self._start()
            if reason is not None:self._commit()
        if self.writer.pending:self._commit()
        return dict(committed_transitions=self.writer.count,completed_plan=self.index==len(self.config['plan']),
            planned_episodes=len(self.config['plan']),episode_index=self.index,
            source_stage='debug',expert_pool_transitions_for_10M=0,research_training_started=False,training_ready=False)
