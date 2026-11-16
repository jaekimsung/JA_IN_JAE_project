"""PPO training: rollout runners, the 1M-transition run loop (B2/B3) and its dev-panel curve."""
import json
from pathlib import Path
import time

import numpy as np

from kcity.training.experiment import experiment_sha256, run_metadata
from kcity.data.collector import case_plan, dataset_config
from kcity.data.dataset import ShardWriter, atomic_json
from kcity.data.online import OnlineRecorder
from kcity.data.storage import checkpoint_from_shard
from kcity.env.config import ROOT, digest, file_sha256
from kcity.env.env import SumoKCityEnv
from kcity.evaluation.evaluate import evaluate_cases
from kcity.evaluation.metrics import aggregate, policy_weights_sha256
from kcity.training.runs import Owner, now, read, require, stopped
from kcity.policy.bc import KCityBC
from kcity.training.experiment import training_config
from kcity.policy.checkpoint import read_bundle, write_bundle
from kcity.policy.ppo import KCityPPO


class KCityRunner:
    """Owns case cursor, partial rollout and episode counters across checkpoints."""
    PATTERN=('A','A','A','B','B','B','C','C','C','C')
    def __init__(self,agent,env,*,run_id,namespace='train',demand_multiplier=1.):
        if type(env).__name__!='SumoKCityEnv':raise ValueError('Exact resume currently supports native K-CITY env only')
        if namespace not in ['train','contract_check']:raise ValueError('Runner cannot consume dev/final/expert cases')
        self.agent,self.env,self.run_id,self.namespace,self.demand=agent,env,run_id,namespace,demand_multiplier
        self.case_cursor=0;self.episode_count=0;self.ep_stats=[0.,0];self.obs=None

    def config(self):
        return dict(run_id=self.run_id,namespace=self.namespace,demand_multiplier=self.demand,
            policy=self.agent.policy.config,hparams=self.agent.hparams,seed=self.agent.seed,
            device_type=self.agent.device.type,contract_sha256=digest(self.env.contract),
            environment=dict(background=self.env.background,debug_warmup_s=self.env.debug_warmup_s,
                debug_episode_limit_s=self.env.debug_episode_limit_s),case_pattern=list(self.PATTERN))

    def _reset_next(self):
        sid=self.PATTERN[self.case_cursor%len(self.PATTERN)]
        self.obs,_=self.env.reset(options=dict(namespace=self.namespace,scenario_id=sid,
            case_index=self.case_cursor,demand_multiplier=self.demand))
        self.case_cursor+=1

    def step(self):
        if self.obs is None:self._reset_next()
        mask=self.agent.policy.mask_from_obs(self.obs).cpu().tolist()
        if mask!=self.env.get_action_mask():raise ValueError('Policy and environment masks disagree')
        action,lp,value=self.agent.act(self.obs)
        nxt,reward,term,trunc,info=self.env.step(action)
        nv=0. if term else self.agent.get_value(nxt)
        self.agent.buffer.add(self.obs,action,lp,reward,value,terminated=term,truncated=trunc,
                              next_value=nv,action_mask=mask)
        self.agent.num_timesteps+=1;self.ep_stats[0]+=reward;self.ep_stats[1]+=1
        self.obs=nxt
        if term or trunc:
            self.episode_count+=1;self.ep_stats=[0.,0];self._reset_next()
        return action,lp,reward,term,trunc,info

    def collect(self,count):
        if isinstance(count,bool) or not isinstance(count,int) or count<1:raise ValueError('Positive count required')
        return [self.step() for _ in range(count)]

    def update(self):
        if self.obs is None:raise RuntimeError('Collect a rollout first')
        a,r=self.agent.buffer.compute_gae(self.agent.get_value(self.obs),self.agent.gamma,self.agent.gae_lambda)
        result=self.agent.update(a,r);self.agent.buffer.clear()
        return result

    def save_checkpoint(self,path):
        if self.obs is None:raise RuntimeError('Cannot checkpoint before reset/collection')
        payload=dict(agent=self.agent.training_state(),obs=self.obs.tolist(),ep_stats=self.ep_stats,
            case_cursor=self.case_cursor,episode_count=self.episode_count)
        write_bundle(path,'ppo',self.config(),payload,self.env)

    def load_checkpoint(self,path):
        payload=read_bundle(path,'ppo',self.config())
        self.env.load_resume_state(Path(path)/'environment')
        self.agent.restore_training_state(payload['agent'])
        self.obs=np.asarray(payload['obs'],dtype=np.float32)
        if not np.array_equal(self.obs,self.env._obs):raise RuntimeError('Runner/environment observation mismatch')
        self.ep_stats=payload['ep_stats'];self.case_cursor=payload['case_cursor'];self.episode_count=payload['episode_count']


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
                completed_cases=len(records),planned_cases=len(cases),updated_at=now()))
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
        require(bcfg['experiment_sha256']==experiment_sha256(spec),'BC source used different experiment settings')
        require(read(bc_root/'COMPLETE.json')['updates']==spec['bc']['updates_per_seed'],'BC is incomplete')
        bc_checkpoint = bc_root/read(bc_root/'BEST.json')['path']
    cfg = training_config(spec,'main_ppo',seed,method,device=device,
        bc_checkpoint=str(bc_checkpoint.resolve()) if bc_checkpoint else None,
        bc_manifest_sha256=file_sha256(bc_checkpoint/'SHA256.json') if bc_checkpoint else None)
    owner = Owner(root,cfg,resume)
    env = SumoKCityEnv(background=True)
    writer = None
    clock=time.monotonic()
    started_at = run_metadata()
    try:
        agent = KCityPPO(spec['policy'],hparams=spec['ppo'],seed=seed,device=device)
        if bc_checkpoint:
            bc = KCityBC(spec['policy'],seed=seed,lr=spec['bc']['learning_rate'],device=device)
            bc.load_checkpoint(bc_checkpoint)
            agent.initialize_bc(bc.policy,cfg['bc_manifest_sha256'])
        runner = RecordingRunner(agent,env,run_id=root.name,namespace='train')
        plan = case_plan(env.contract,'train')
        dcfg = dataset_config(env,root.name+'-online',plan,'ppo_train',method,seed,
                              experiment_sha256=cfg['experiment_sha256'])
        dcfg['learner_config'] = cfg
        writer = ShardWriter(root/'transitions',dcfg,resume=resume,shard_rows=spec['ppo']['n_steps'])
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
                session_new_transitions=agent.num_timesteps-session_start_transitions,run=started_at))
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
