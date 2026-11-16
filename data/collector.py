"""Expert (B0) collection, case plans and dataset run configs; no learner is created."""
from collections import Counter
from copy import deepcopy
import json
import platform
import numpy as np
import subprocess
import xml.etree.ElementTree as ET

from env.config import ROOT,DEFAULT_PROTOCOL,digest,file_sha256,git_info,make_case,repository_path
from env.env import IMPLEMENTATION_ID as _IMPLEMENTATION_ID
from policy.rule_expert import EXPERT_ID,KCityRuleExpert
from data.dataset import atomic_json,make_transition,now
from data.storage import CHECKPOINT_MODE,NEXT_CODEC,require
from evaluation.metrics import EpisodeMetrics

PATTERN=('A','A','A','B','B','B','C','C','C','C')


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
        case['runtime_variant']=dict(implementation=_IMPLEMENTATION_ID,background=env.background,
            warmup_s=env.contract['protocol']['timing']['warmup_s'] if env.debug_warmup_s is None else env.debug_warmup_s,
            horizon_s=case['scenario']['episode_limit_s'] if env.debug_episode_limit_s is None else env.debug_episode_limit_s,
            debug_override=env.debug_warmup_s is not None or env.debug_episode_limit_s is not None)
        case['case_uid']=digest({k:v for k,v in case.items() if k!='case_uid'})
        resolved.append(dict(case=case,data_split=entry['data_split']))
    if len({r['case']['case_uid'] for r in resolved})!=len(resolved):raise ValueError('Duplicate planned case')
    if json.loads(DEFAULT_PROTOCOL.read_text())!=env.contract['protocol']:
        raise ValueError('Collector requires the default environment contract (configs/kcity/v1/protocol.json)')
    teacher=dict(id=EXPERT_ID,config=deepcopy(expert.config))
    teacher['fingerprint']=digest(teacher)
    assets=deepcopy(env.contract['protocol']['assets'])
    assets['scenarios']=deepcopy(env.contract['protocol']['scenario_manifest'])
    assets['protocol']=dict(path=str(DEFAULT_PROTOCOL.relative_to(ROOT)),sha256=file_sha256(DEFAULT_PROTOCOL))
    location=ET.parse(repository_path(assets['network']['path'])).getroot().find('location')
    return dict(schema_id='KC-COLLECTION-v1-candidate',run_uid=run_uid,
        data_purpose='KC05_pipeline_validation_NOT_RESEARCH_POOL',source_stage='debug',
        eligible_for_research_training=False,training_ready=False,contract=env.contract,
        teacher=teacher,code=git_info(),asset_snapshots=assets,plan=resolved,
        environment=dict(background=env.background,debug_warmup_s=env.debug_warmup_s,
            debug_episode_limit_s=env.debug_episode_limit_s),
        coordinate_frame=dict(position_reference='SUMO_front_bumper_center',
            location=dict(location.attrib) if location is not None else None),
        episode_id_scheme='dataset_local_monotonic_registry; allocate/check release-global IDs before merging runs',
        runtime=dict(python=platform.python_version(),platform=platform.platform(),numpy=np.__version__,
            sumo_version=subprocess.check_output([env.sumolib.checkBinary('sumo'),'--version'],text=True).splitlines()[0]),
    )


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

    def collect(self, target, stop=lambda:False):
        """Collect until an absolute transition target, then finish the current Episode."""
        require(type(target) is int and target>0 and target>=self.writer.count,'Invalid absolute collection target')
        while self.index<len(self.config['plan']):
            current = self.writer.count+self.writer.pending
            if stop() or (current>=target and self.metrics is None):
                break
            if self.metrics is None:
                self._start()
            entry = self.config['plan'][self.index]
            case = entry['case']
            before,detected = self.obs.copy(),deepcopy(self.detected)
            nxt,reward,term,trunc,info = self.env.step(self.expert.predict(before))
            next_detected = self.env.get_detected_vehicles()
            reason = 'checkpoint' if term or trunc else 'shard' if self.writer.pending+1>=self.writer.shard_rows else None
            row = make_transition(config=self.config,case=case,episode_index=self.index,t=self.t,
                attempt_uid=self.writer.attempt_uid,observation=before,detected=detected,
                next_observation=nxt,next_detected=next_detected,reward=reward,terminated=term,truncated=trunc,
                info=info,start_tick=self.start_tick,previous_interval=self.previous_interval,
                departure_history=self.departure_history,segment_reason=reason)
            self.writer.append(row)
            self.metrics.add(row['reward_env_raw'],term,trunc,row)
            self.t += 1
            self.obs,self.detected = nxt,next_detected
            self.previous_interval = deepcopy(info['traffic_interval'])
            self.departure_history.append([info['sim_tick_tp1'],info['traffic_interval']['departed_hv']])
            if term or trunc:
                self.completed_pending.append(dict(episode_uid=row['episode_uid'],episode=self.index,
                    case_uid=case['case_uid'],data_split=entry['data_split'],metrics=self.metrics.finish()))
                self.index += 1
                self.t = 0
                self.metrics = None
            if self.writer.pending>=self.writer.shard_rows or ((term or trunc) and self.writer.count+self.writer.pending>=target):
                self._commit()
                atomic_json(self.writer.root.parent/'STATUS.json',dict(phase='COLLECTING',updated_at=now(),
                    transitions=self.writer.count,target=target,completed_episodes=self.index))
        if self.writer.pending:
            self._commit()
        complete = self.writer.count>=target and self.metrics is None
        require(complete or stop(), 'Case plan exhausted before target; preserve partial run for review')
        return dict(phase='COMPLETE' if complete else 'STOPPED',transitions=self.writer.count,
                    target=target,completed_episodes=self.index,finish_episode=True)


def resolved_case(contract, namespace, sid, index):
    case = make_case(contract,namespace,sid,index)
    case['runtime_variant'] = dict(implementation=_IMPLEMENTATION_ID,background=True,
        warmup_s=contract['protocol']['timing']['warmup_s'],horizon_s=case['scenario']['episode_limit_s'],debug_override=False)
    case['case_uid'] = digest({k:v for k,v in case.items() if k!='case_uid'})
    return case


def case_plan(contract, kind, count=20000, start=0):
    require(type(count) is int and count>0,'Positive case count required')
    seen = Counter()
    result = []
    for cursor in range(count):
        sid = PATTERN[cursor%10]
        if kind=='expert':
            index = seen[sid]+start
            seen[sid] += 1
            namespace = 'expert_val' if index%5==4 else 'expert_train'
            split = namespace
        else:
            require(kind in ('probe','train','archive'),'Unknown case plan kind: '+str(kind))
            index = cursor+start
            namespace,split = dict(probe=('contract_check','ops_probe'),train=('train','ppo_train'),
                                   archive=('archive','archive'))[kind]
        result.append(dict(case=resolved_case(contract,namespace,sid,index),data_split=split))
    require(len({r['case']['case_uid'] for r in result})==len(result),'Repeated case in plan')
    return result


def dataset_config(env, run_uid, plan, stage, method='B0', seed=None, *, experiment_sha256=None, fixed_policy=None):
    """Writer config. method B2/B3 = online PPO rows; fixed_policy = rows driven by a frozen learned policy."""
    cfg = build_config(env,KCityRuleExpert(),run_uid)
    cfg.update(plan=plan,source_stage=stage,data_purpose='main_'+stage if stage!='debug' else 'operational_probe_not_main',
        eligible_for_research_training=stage=='expert_pool',training_ready=False,
        experiment_sha256=experiment_sha256,storage_codec=NEXT_CODEC)
    if method!='B0':
        cfg['checkpoint_policy']=dict(mode=CHECKPOINT_MODE,keep_recent=2,evaluation_interval_transitions=50000)
        cfg['online_policy']=dict(method=method,seed=seed,version='KC-MAIN-ONLINE-v1')
        cfg['teacher'] = dict(id=method+'-online',config=dict(seed=seed),
                              fingerprint=digest(dict(method=method,seed=seed)))
    if fixed_policy is not None:
        require(method=='B0','fixed_policy and online PPO are exclusive')
        require({'method','seed','version','policy_sha256'}<=set(fixed_policy),'Incomplete fixed policy identity')
        cfg['fixed_policy']=dict(fixed_policy)
        cfg['teacher']=dict(id=fixed_policy['method']+'-fixed',config=dict(seed=fixed_policy['seed']),
                            fingerprint=fixed_policy['policy_sha256'])
    return cfg
