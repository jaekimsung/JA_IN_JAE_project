"""Operational adapters for the immutable K-CITY scientific specification.

The environment, policy, reward and legacy KC01 contracts remain untouched.
Native full-State shards and learner checkpoints share the SAME atomic commit
for online PPO, so a crash cannot leave data ahead of the restored learner.
No Google Drive or other upload operation is performed by this module.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import shutil
import time

import numpy as np
import torch

from kcity.policy.policy import DEFAULT_POLICY
from kcity.training import KCityBC, KCityPPO, KCityRunner, DEFAULT_PPO,read_bundle
from kcity.env.config import ROOT, digest, file_sha256, load_contract, make_case
from kcity.env.env import SumoKCityEnv, IMPLEMENTATION_ID
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.data.collector import build_config, ExpertCollector
from kcity.data.dataset import ShardWriter, atomic_json, make_transition, shard_directories, validate_dataset
from kcity.evaluator import EpisodeMetrics, evaluate_cases, aggregate, policy_weights_sha256
from kcity.data.storage import (NEXT_CODEC,CHECKPOINT_MODE,checkpoint_from_shard,
    save_external,sync_retention,verify_bundle)

FROZEN = ROOT/'configs/kcity/main_v1/FROZEN_PROTOCOL.json'
COMPAT = ROOT/'configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json'
LAYOUT = ROOT/'configs/kcity/main_v1/LAYOUT_MIGRATION.json'
# 경로 재배치로만 바뀌는 필드. 나머지(과학 설정)는 layout_revision.science_digest로 고정한다.
LAYOUT_FIELDS = ('source_sha256', 'reference_contract_sha256', 'layout_revision')
PATTERN = ('A','A','A','B','B','B','C','C','C','C')
NEW_SOURCES = ['kcity/experiment.py', 'tools/main/main_experiment.py','kcity/data/dataset.py',
               'kcity/data/storage.py','configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json']
STOP = False


def now():
    return datetime.now().astimezone().isoformat()


def read(path):
    return json.loads(Path(path).read_text())


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def stop_handler(*args):
    global STOP
    STOP = True


def install_signals():
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)


def stopped(root):
    return STOP or (Path(root)/'STOP').exists()


def science_digest(protocol):
    return digest({k: v for k, v in protocol.items() if k not in LAYOUT_FIELDS})


def load_scientific(path=FROZEN):
    p = read(path)
    require(p['schema_id']=='KC-SCIENTIFIC-FREEZE-v1' and p['scientific_settings_frozen'], 'Unfrozen science')
    require(p['policy']==DEFAULT_POLICY and p['ppo']==DEFAULT_PPO, 'Frozen policy/PPO mismatch')
    layout = p.get('layout_revision')
    if layout is not None:
        require(science_digest(p)==layout['science_digest'], 'Frozen science changed after layout revision')
    # 동결 후 변경은 OPERATIONAL_COMPATIBILITY.json에 frozen/현재 SHA를 함께 등록한 경우만 허용한다.
    # 등록 파일 자체가 운영 소스(NEW_SOURCES)라서 launch record 검사도 다시 거친다.
    for name, checksum in p['source_sha256'].items():
        actual=file_sha256(ROOT/name)
        if actual!=checksum:
            compat=read(COMPAT)
            entry=compat.get('extensions', {}).get(name, {})
            require(compat.get('scientific_sha256')==file_sha256(path) and
                    entry.get('frozen_sha256')==checksum and
                    entry.get('operational_sha256')==actual,
                    'Frozen source changed: '+name)
    for name, checksum in p['reference_contract_sha256'].items():
        actual = file_sha256(ROOT/name)
        if actual != checksum:
            compat = read(COMPAT)
            entry = compat.get('documentation_revision', {}).get('contracts', {}).get(name, {})
            require(compat.get('scientific_sha256') == file_sha256(path) and
                    entry.get('frozen_sha256') == checksum and
                    entry.get('revised_sha256') == actual,
                    'Frozen data/metric contract changed: '+name)
    for panel in p['case_panels'].values():
        require(file_sha256(ROOT/panel['path'])==panel['sha256'], 'Frozen case panel changed')
    contract = load_contract(ROOT/p['base_contract']['path'])
    require(digest(contract)==p['base_contract']['loaded_contract_sha256'], 'Base contract mismatch')
    require(p['timing']==contract['protocol']['timing'] and p['control']==contract['protocol']['control'],
            'Science and environment timing/control differ')
    return p


def operational_sources():
    return {name:file_sha256(ROOT/name) for name in NEW_SOURCES}


def require_launch(record,stage=None,output=None):
    require(record is not None, 'Main work requires a verified --launch-record; use --check-only for preparation')
    ready = read(record)
    require(ready['phase'] in ['READY','READY_LOCAL_ONLY'] and ready['launch_ready'], 'Launch record is not ready')
    require(ready['scientific_sha256']==file_sha256(FROZEN), 'Launch science fingerprint changed')
    require(ready['operational_sources']==operational_sources(), 'Operational code changed since preflight')
    require(ready['remote_uploads_enabled'] is False, 'Drive uploads are disabled by user instruction')
    load_scientific()
    if stage is not None:
        location=Path(output).resolve()
        while not location.exists():location=location.parent
        capacity=ready['capacity']
        extra=2*1024**3
        if stage=='collect':extra+=int(1.5*1000000*capacity['expert_measurement']['bytes_per_transition'])
        if stage=='ppo':extra+=int(1.5*1000000*capacity['ppo_measurement']['bytes_per_transition'])
        require(shutil.disk_usage(location).free>=capacity['reserve_bytes']+extra,
                'Insufficient current disk space for this stage plus operating reserve')
    return ready


class Owner:
    def __init__(self, root, config, resume=False):
        self.root = Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.path = self.root/'OWNER.json'
        if self.path.exists():
            pid = read(self.path)['pid']
            try:
                os.kill(pid,0)
            except ProcessLookupError:
                require(resume,'Stale owner requires explicit --resume')
                self.path.unlink()
            else:
                raise RuntimeError('Another process owns this run')
        manifest = self.root/'CONFIG.json'
        if manifest.exists():
            require(resume and read(manifest)==config, 'Explicit resume with identical configuration required')
        else:
            require(not resume and not any(self.root.iterdir()), 'New run requires a new empty output')
            atomic_json(manifest,config)
        with self.path.open('x') as stream:
            json.dump(dict(pid=os.getpid(),started_at=now()),stream)

    def close(self):
        self.path.unlink(missing_ok=True)


def resolved_case(contract, namespace, sid, index):
    case = make_case(contract,namespace,sid,index)
    case['runtime_variant'] = dict(implementation=IMPLEMENTATION_ID,background=True,
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
            index = cursor+start
            namespace = 'contract_check' if kind=='probe' else 'train'
            split = 'ops_probe' if kind=='probe' else 'ppo_train'
        result.append(dict(case=resolved_case(contract,namespace,sid,index),data_split=split))
    require(len({r['case']['case_uid'] for r in result})==len(result),'Repeated case in plan')
    return result


def dataset_config(env, run_uid, plan, stage, method='B0', seed=None):
    cfg = build_config(env,KCityRuleExpert(),run_uid)
    cfg.update(plan=plan,source_stage=stage,data_purpose='main_'+stage if stage!='debug' else 'operational_probe_not_main',
        eligible_for_research_training=stage=='expert_pool',training_ready=False,
        scientific_sha256=file_sha256(FROZEN),remote_uploads_enabled=False,storage_codec=NEXT_CODEC)
    cfg['source_sha256'].update(operational_sources())
    cfg['asset_snapshots']['scientific_protocol']=dict(path=str(FROZEN.relative_to(ROOT)),sha256=file_sha256(FROZEN))
    if method!='B0':
        cfg['checkpoint_policy']=dict(mode=CHECKPOINT_MODE,keep_recent=2,evaluation_interval_transitions=50000)
        cfg['online_policy']=dict(method=method,seed=seed,version='KC-MAIN-ONLINE-v1')
        cfg['teacher'] = dict(id=method+'-online',config=dict(seed=seed),
                              fingerprint=digest(dict(method=method,seed=seed)),source_sha256=file_sha256(ROOT/NEW_SOURCES[0]))
    return cfg


class MainWriter(ShardWriter):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        try:
            if self.config.get('checkpoint_policy',{}).get('mode')==CHECKPOINT_MODE:
                sync_retention(self.root,self.folders,self.config['checkpoint_policy'])
        except BaseException:
            self.close()
            raise

    def commit(self,checkpoint,completed_episodes,save_environment=None):
        external=self.config.get('checkpoint_policy',{}).get('mode')==CHECKPOINT_MODE
        if external:
            require(save_environment is not None,'Online shard requires a learner checkpoint')
            callback=lambda stub:save_external(self.root,stub,save_environment,self.count+self.pending)
        else:callback=save_environment
        folder=super().commit(checkpoint,completed_episodes,callback)
        if folder is not None and external:
            sync_retention(self.root,self.folders,self.config['checkpoint_policy'])
        return folder

    def refresh_release(self):
        super().refresh_release()
        release = read(self.root/'RELEASE.json')
        release.pop('data_id')
        release['eligible_for_research_training'] = bool(self.config['source_stage']=='expert_pool'
                                                       and self.config['eligible_for_research_training'])
        atomic_json(self.root/'RELEASE.json',dict(release,data_id=digest(release)))


class MainExpertCollector(ExpertCollector):
    def collect_main(self, target, stop=lambda:False):
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
                    transitions=self.writer.count,target=target,completed_episodes=self.index,
                    main_training_started=False,remote_uploads_enabled=False))
        if self.writer.pending:
            self._commit()
        complete = self.writer.count>=target and self.metrics is None
        require(complete or stop(), 'Case plan exhausted before target; preserve partial run for review')
        return dict(phase='COMPLETE' if complete else 'STOPPED',transitions=self.writer.count,
                    target=target,completed_episodes=self.index,finish_episode=True)


class RecordingRunner(KCityRunner):
    """Native runner mechanics with a recorder hook BEFORE terminal reset."""
    def step(self):
        if self.obs is None:
            self._reset_next()
        before = self.obs.copy()
        detected = self.env.get_detected_vehicles()
        mask = self.agent.policy.mask_from_obs(before).cpu().tolist()
        require(mask==self.env.get_action_mask(),'Policy and environment masks disagree')
        action,lp,value = self.agent.act(before)
        nxt,reward,term,trunc,info = self.env.step(action)
        nv = 0. if term else self.agent.get_value(nxt)
        self.agent.buffer.add(before,action,lp,reward,value,terminated=term,truncated=trunc,
                              next_value=nv,action_mask=mask)
        self.agent.num_timesteps += 1
        self.ep_stats[0] += reward
        self.ep_stats[1] += 1
        self.obs = nxt
        self.recorder.add(before,detected,nxt,self.env.get_detected_vehicles(),reward,term,trunc,info,lp,value,nv)
        if term or trunc:
            self.episode_count += 1
            self.ep_stats = [0.,0]
            self._reset_next()
        return action,lp,reward,term,trunc,info


class OnlineRecorder:
    def __init__(self,runner,writer,method,seed):
        self.runner,self.writer,self.method,self.seed = runner,writer,method,seed
        self.metrics = None
        self.completed = []
        self.t = 0
        self.previous = dict(departed_hv=0,arrived_hv=0)
        self.history = []
        self.behavior_sha = policy_weights_sha256(runner.agent)
        saved,folder = writer.last_checkpoint()
        if saved is not None:
            runner.load_checkpoint(checkpoint_from_shard(folder))
            require(writer.count==runner.agent.num_timesteps,'Atomic learner/data counts differ')
            self.t,self.previous,self.history = saved['t'],saved['previous'],saved['history']
            if saved['metrics'] is not None:
                self.metrics = EpisodeMetrics.__new__(EpisodeMetrics)
                self.metrics.__dict__.update(saved['metrics'])
                self.metrics.commands = Counter({int(k):v for k,v in self.metrics.commands.items()})
                self.metrics.rejections = Counter(self.metrics.rejections)
            self.behavior_sha = saved['behavior_sha']

    def add(self,before,detected,nxt,next_detected,reward,term,trunc,info,lp,value,nv):
        r = self.runner
        case = self.writer.config['plan'][r.episode_count]['case']
        require(case==r.env.case,'Online case differs from declared plan')
        if self.metrics is None:
            self.metrics = EpisodeMetrics(case,{'state':info['state']})
            self.t = 0
            self.previous = dict(departed_hv=0,arrived_hv=0)
            self.history = []
        row = make_transition(config=self.writer.config,case=case,episode_index=r.episode_count,t=self.t,
            attempt_uid=self.writer.attempt_uid,observation=before,detected=detected,next_observation=nxt,
            next_detected=next_detected,reward=reward,terminated=term,truncated=trunc,info=info,
            start_tick=r.env.episode_start_tick,previous_interval=self.previous,departure_history=self.history,
            segment_reason='checkpoint' if term or trunc else None,
            policy_context=dict(behavior_sha=self.behavior_sha,update_id=r.agent.num_updates,
                rollout_id=r.agent.num_updates,log_prob_raw=lp,value=value,next_value=nv))
        self.writer.append(row)
        self.metrics.add(row['reward_env_raw'],term,trunc,row)
        self.t += 1
        self.previous = deepcopy(info['traffic_interval'])
        self.history.append([info['sim_tick_tp1'],info['traffic_interval']['departed_hv']])
        if term or trunc:
            self.completed.append(dict(episode_uid=row['episode_uid'],episode=r.episode_count,
                case_uid=case['case_uid'],data_split=self.writer.config['plan'][r.episode_count]['data_split'],
                metrics=self.metrics.finish()))
            self.metrics = None
            self.t = 0

    def commit(self):
        self.behavior_sha = policy_weights_sha256(self.runner.agent)
        state = dict(t=self.t,previous=self.previous,history=self.history,
                     behavior_sha=self.behavior_sha,metrics=deepcopy(self.metrics.__dict__) if self.metrics else None)
        folder = self.writer.commit(state,self.completed,self.runner.save_checkpoint)
        self.completed = []
        return folder


def training_config(kind,seed=None,method=None,**extra):
    return dict(kind=kind,seed=seed,method=method,scientific_sha256=file_sha256(FROZEN),
                operational_sources=operational_sources(),remote_uploads_enabled=False,**extra)


def build_views(pool,output,spec):
    output = Path(output)
    require(not output.exists(),'New immutable BC view directory required')
    config = read(Path(pool)/'RUN.json')
    report = validate_dataset(pool)
    require(config['source_stage']=='expert_pool' and config['eligible_for_research_training'], 'Not a new main expert pool')
    require(report['unique_transitions']>=spec['budgets']['expert_valid_transitions_min'],'Main pool budget not met')
    require(read(Path(pool)/'RELEASE.json')['eligible_for_research_training'],'Pool release not eligible')
    require(config['scientific_sha256']==file_sha256(FROZEN),'Pool belongs to another science protocol')
    rng = np.random.default_rng(20261115)
    arrays = {}
    for split,size in [('expert_train',spec['bc']['train_view_rows']),('expert_val',spec['bc']['validation_view_rows'])]:
        episodes = [e for e in report['episodes'] if e['data_split']==split and
                    e['metrics']['compliant_completion'] is True and e['metrics']['primary_end_reason']=='arrival']
        total = sum(e['metrics']['decision_count'] for e in episodes)
        require(total>=size,'Insufficient successful rows for '+split)
        chosen = np.sort(rng.choice(total,size,replace=False))
        uids = [e['episode_uid'] for e in episodes]
        chunks = {k:[] for k in ['observation','action_target','action_mask','transition_uid']}
        cursor = 0
        for folder in shard_directories(pool):
            with np.load(folder/'numeric.npz',allow_pickle=False) as a:
                eligible = np.flatnonzero((a['data_split']==split)&np.isin(a['episode_uid'],uids))
                local = chosen[(chosen>=cursor)&(chosen<cursor+len(eligible))]-cursor
                indices = eligible[local]
                for key,source in [('observation','observation'),('action_target','action_env_input'),
                                   ('action_mask','action_mask'),('transition_uid','transition_uid')]:
                    chunks[key].append(a[source][indices].copy())
                cursor += len(eligible)
        require(cursor==total,'Eligible count differs from completed Episode records')
        arrays[split] = {k:np.concatenate(v) for k,v in chunks.items()}
        require(len(set(arrays[split]['transition_uid']))==size,'Duplicate BC view rows')
    output.mkdir(parents=True)
    for split,data in arrays.items():
        np.savez_compressed(output/(split+'.npz'),**data)
    body = dict(schema='KC-MAIN-BC-VIEWS-v1',pool=str(Path(pool).resolve()),data_id=report['data_id'],
                scientific_sha256=file_sha256(FROZEN),rng_seed=20261115,
                files={p.name:file_sha256(p) for p in output.glob('*.npz')})
    atomic_json(output/'MANIFEST.json',dict(body,view_id=digest(body)))
    return read(output/'MANIFEST.json')


def read_views(folder):
    folder = Path(folder)
    manifest = read(folder/'MANIFEST.json')
    require(manifest['view_id']==digest({k:v for k,v in manifest.items() if k!='view_id'}),'BC view identity mismatch')
    require(manifest['scientific_sha256']==file_sha256(FROZEN),'BC views use different protocol')
    require(read(Path(manifest['pool'])/'RELEASE.json')['data_id']==manifest['data_id'],'Pool changed after BC view selection')
    data = {}
    for name,checksum in manifest['files'].items():
        require(file_sha256(folder/name)==checksum,'BC view checksum mismatch')
        with np.load(folder/name,allow_pickle=False) as a:
            data[Path(name).stem] = {k:a[k].copy() for k in a.files}
    return manifest,data


def validation_loss(model,data):
    totals = Counter()
    count = len(data['observation'])
    with torch.no_grad():
        for i in range(0,count,2048):
            end = min(count,i+2048)
            loss,parts = model.loss(*[data[k][i:end] for k in ['observation','action_target','action_mask']])
            for key,value in dict(loss=loss,**parts).items():
                totals[key] += float(value)*(end-i)/count
    return dict(totals)


def retain_bc(root,best):
    """Keep latest/previous and the best needed by either resume state."""
    folders=sorted(Path(root).glob('update-*'))
    recent=folders[-2:]
    keep={p.name for p in recent}
    if best['path']:keep.add(best['path'])
    for path in recent:
        meta=read(path/'metadata.json')
        state=read_bundle(path,'bc',meta['config'])['run_state']['best']
        if state['path']:keep.add(state['path'])
    for name in keep:verify_bundle(Path(root)/name)
    removed=[]
    for path in folders:
        if path.name in keep:continue
        require(path.is_dir() and not path.is_symlink() and path.parent==Path(root),'Unexpected BC checkpoint object')
        removed.append(path.name)
        shutil.rmtree(path)
    atomic_json(Path(root)/'CHECKPOINT_RETENTION.json',dict(retained=sorted(keep),removed_this_pass=removed,
        policy='latest_previous_and_best_needed_for_resume'))


def run_bc(root,views,seed,spec,device,resume=False):
    root = Path(root)
    manifest,data = read_views(views)
    cfg = training_config('main_bc',seed,views=str(Path(views).resolve()),view_id=manifest['view_id'],device=device)
    owner = Owner(root,cfg,resume)
    model = KCityBC(spec['policy'],seed=seed,lr=spec['bc']['learning_rate'],device=device)
    best = dict(loss=None,path=None)
    clock=time.monotonic()
    try:
        if (root/'LATEST.json').exists():
            state = model.load_checkpoint(root/read(root/'LATEST.json')['path'],expected_data_id=manifest['data_id'])
            require(state['view_id']==manifest['view_id'],'BC resume views changed')
            best = state['best']
            if best['path']:atomic_json(root/'BEST.json',best)
        for update in range(model.updates,spec['bc']['updates_per_seed']):
            train = data['expert_train']
            idx = model.sampler.integers(0,len(train['observation']),spec['bc']['batch_size'])
            training_metrics=model.train_batch(*[train[k][idx] for k in ['observation','action_target','action_mask']])
            boundary = model.updates%spec['bc']['validate_every_updates']==0
            if boundary or stopped(root) or model.updates==spec['bc']['updates_per_seed']:
                path = f'update-{model.updates:06d}'
                val = validation_loss(model,data['expert_val']) if boundary else None
                if val is not None and (best['loss'] is None or val['loss']<best['loss']):
                    best = dict(loss=val['loss'],path=path)
                state = dict(data_id=manifest['data_id'],view_id=manifest['view_id'],best=best,
                             validation=val,scientific_sha256=file_sha256(FROZEN))
                model.save_checkpoint(root/path,state)
                with (root/'curve.jsonl').open('a') as stream:
                    stream.write(json.dumps(dict(updates=model.updates,validation=val,training=training_metrics,
                        session_wall_s=time.monotonic()-clock))+'\n')
                atomic_json(root/'LATEST.json',dict(path=path,updates=model.updates))
                if best['path']:
                    atomic_json(root/'BEST.json',best)
                retain_bc(root,best)
                atomic_json(root/'STATUS.json',dict(phase='STOPPED' if stopped(root) else 'BC_MAIN_TRAINING',
                    updated_at=now(),updates=model.updates,target=spec['bc']['updates_per_seed'],best=best,
                    session_wall_s=time.monotonic()-clock,main_training_started=True,remote_uploads_enabled=False))
            if stopped(root):
                return
        atomic_json(root/'COMPLETE.json',dict(updates=model.updates,best=best,completed_at=now()))
    finally:
        owner.close()


def evaluate_dev(agent,root,point,spec,stop=lambda:False):
    folder = Path(root)/'dev'/f'T{point:07d}'
    folder.mkdir(parents=True,exist_ok=True)
    policy_sha=policy_weights_sha256(agent)
    if (folder/'POLICY.json').exists():
        require(read(folder/'POLICY.json')['acting_state_dict_sha256']==policy_sha,'Dev policy changed at fixed transition')
    else:
        atomic_json(folder/'POLICY.json',dict(acting_state_dict_sha256=policy_sha,actual_transitions=point))
    if (folder/'SUMMARY.json').exists():
        return True
    cases = read(ROOT/spec['case_panels']['dev']['path'])['cases']
    records = read(folder/'EPISODES.json') if (folder/'EPISODES.json').exists() else []
    require([r['requested_case_uid'] for r in records]==[c['case_uid'] for c in cases[:len(records)]], 'Dev resume panel mismatch')
    env = SumoKCityEnv(background=True)
    try:
        for case in cases[len(records):]:
            if stop():
                return False
            rows,_ = evaluate_cases(agent,env,dict(cases=[case]))
            records.extend(rows)
            atomic_json(folder/'EPISODES.json',records)
            atomic_json(Path(root)/'STATUS.json',dict(phase='EVALUATING_DEV',transitions=point,
                completed_cases=len(records),planned_cases=len(cases),updated_at=now(),main_training_started=True))
        summary=aggregate(records,len(cases))
        atomic_json(folder/'SUMMARY.json',dict(actual_transitions=point,aggregate=summary,acting_state_dict_sha256=policy_sha))
        curve=[]
        for path in sorted((Path(root)/'dev').glob('T*/SUMMARY.json')):
            curve.append(read(path))
        threshold=spec['metrics']['target_rate']
        target=confirmation=None
        for first,second in zip(curve,curve[1:]):
            valid=lambda row:(row['aggregate']['n_valid']==100 and row['aggregate']['data_quality_valid'] and
                row['aggregate']['compliant_completion_rate'] is not None and
                row['aggregate']['compliant_completion_rate']>=threshold)
            if (valid(first) and valid(second) and
                    second['actual_transitions']-first['actual_transitions']==spec['metrics']['dev_interval_transitions']):
                target,confirmation=first['actual_transitions'],second['actual_transitions']
                break
        atomic_json(Path(root)/'SAMPLE_EFFICIENCY.json',dict(target_transition=target,
            confirmation_transition=confirmation,right_censored=confirmation is None,
            observed_through_transition=point,curve=curve,
            bc_expert_costs_reported_separately=True))
        return True
    finally:
        env.close()


def run_ppo(root,method,seed,spec,device,bc_root=None,resume=False):
    root = Path(root)
    bc_checkpoint = None
    if method=='B3':
        require(bc_root is not None,'B3 requires the same-seed completed MAIN BC run')
        bc_root = Path(bc_root)
        bcfg = read(bc_root/'CONFIG.json')
        require(bcfg['kind']=='main_bc' and bcfg['seed']==seed,'Wrong BC source kind/seed')
        require(bcfg['scientific_sha256']==file_sha256(FROZEN) and bcfg['operational_sources']==operational_sources(),
                'BC source belongs to a different scientific/operational version')
        require(read(bc_root/'COMPLETE.json')['updates']==spec['bc']['updates_per_seed'],'BC is incomplete')
        bc_checkpoint = bc_root/read(bc_root/'BEST.json')['path']
    cfg = training_config('main_ppo',seed,method,device=device,
        bc_checkpoint=str(bc_checkpoint.resolve()) if bc_checkpoint else None,
        bc_manifest_sha256=file_sha256(bc_checkpoint/'SHA256.json') if bc_checkpoint else None)
    owner = Owner(root,cfg,resume)
    env = SumoKCityEnv(background=True)
    writer = None
    clock=time.monotonic()
    try:
        agent = KCityPPO(spec['policy'],hparams=spec['ppo'],seed=seed,device=device)
        if bc_checkpoint:
            bc = KCityBC(spec['policy'],seed=seed,lr=spec['bc']['learning_rate'],device=device)
            bc.load_checkpoint(bc_checkpoint)
            agent.initialize_bc(bc.policy,cfg['bc_manifest_sha256'])
        runner = RecordingRunner(agent,env,run_id=root.name,namespace='train')
        plan = case_plan(env.contract,'train')
        dcfg = dataset_config(env,root.name+'-online',plan,'ppo_train',method,seed)
        dcfg['learner_config'] = cfg
        writer = MainWriter(root/'transitions',dcfg,resume=resume,shard_rows=spec['ppo']['n_steps'])
        recorder = OnlineRecorder(runner,writer,method,seed)
        runner.recorder = recorder
        if runner.obs is None:
            if (root/'initial_policy').exists():
                runner.load_checkpoint(root/'initial_policy')
            else:
                runner._reset_next()
                runner.save_checkpoint(root/'initial_policy')
        session_start_transitions=agent.num_timesteps
        cap = spec['budgets']['ppo_transitions_per_method_seed']
        interval = spec['metrics']['dev_interval_transitions']
        while agent.num_timesteps<=cap:
            if agent.num_timesteps%interval==0:
                if not evaluate_dev(agent,root,agent.num_timesteps,spec,lambda:stopped(root)):
                    return
            if agent.num_timesteps==cap or stopped(root):
                break
            boundary = min(cap,(agent.num_timesteps//interval+1)*interval)
            count = min(agent.n_steps-len(agent.buffer),boundary-agent.num_timesteps)
            for _ in range(count):
                runner.step()
                if stopped(root):
                    break
            # STOP preserves the partial buffer instead of introducing an extra update.
            stats=None
            if not stopped(root) or len(agent.buffer)==agent.n_steps or agent.num_timesteps==boundary:
                stats=runner.update()
            folder = recorder.commit()
            bundle=checkpoint_from_shard(folder)
            atomic_json(root/'LATEST.json',dict(path=str(folder.relative_to(root)),transitions=agent.num_timesteps))
            atomic_json(root/'STATUS.json',dict(phase='STOPPED' if stopped(root) else 'PPO_MAIN_TRAINING',
                updated_at=now(),method=method,seed=seed,transitions=agent.num_timesteps,target=cap,
                rollout_updates=agent.num_updates,optimizer_steps=agent.num_optimizer_steps,
                committed_data_transitions=writer.count,checkpoint=str(bundle),
                session_wall_s=time.monotonic()-clock,
                session_new_transitions=agent.num_timesteps-session_start_transitions,
                main_training_started=True,remote_uploads_enabled=False))
            with (root/'curve.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(attempt_uid=writer.attempt_uid,transitions=agent.num_timesteps,
                    rollout_updates=agent.num_updates,optimizer_steps=agent.num_optimizer_steps,metrics=stats,
                    session_wall_s=time.monotonic()-clock,checkpoint=str(bundle)))+'\n')
            if stopped(root):
                return
        if agent.num_timesteps==cap:
            atomic_json(root/'COMPLETE.json',dict(transitions=cap,rollout_updates=agent.num_updates,
                optimizer_steps=agent.num_optimizer_steps,completed_at=now(),policy_selection='budget_end',
                checkpoint=str(checkpoint_from_shard(root/read(root/'LATEST.json')['path']))))
    finally:
        if writer is not None:
            writer.close()
        env.close()
        owner.close()
