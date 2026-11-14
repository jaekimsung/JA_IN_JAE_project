"""KC-04 BC/PPO initialization and resumable control-boundary training state.

APIs for later runners, not a research launch command. No background job starts
on import. Tests may execute a few explicitly labelled synthetic updates.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import random
import shutil
import tempfile

import numpy as np
import torch

from algorithms.ppo import PPO
from algorithms.kcity_policy import KCityPolicy,bc_optimizer,bc_loss,initialize_from_bc
from env.kcity_config import digest,file_sha256,ROOT
from utils.buffer import RolloutBuffer

DEFAULT_PPO=dict(lr=1e-4,n_steps=2048,n_epochs=10,minibatch_size=64,gamma=.99,
    gae_lambda=.95,clip_eps=.2,value_coef=.5,entropy_coef=0.,lane_entropy_coef=.01,
    max_grad_norm=.5,normalize_advantage=True)
SOURCES=['algorithms/kcity_policy.py','algorithms/kcity_training.py','algorithms/ppo.py',
         'utils/networks.py','utils/buffer.py','env/kcity_env.py','env/kcity_config.py',
         'env/kcity_observation.py','env/kcity_route.py','scripts/kcity/scenarios.py',
         'configs/kcity/v1/learning.json']


def pack_numpy(state):return [state[0],state[1].tolist(),int(state[2]),int(state[3]),float(state[4])]
def unpack_numpy(state):return (state[0],np.asarray(state[1],dtype=np.uint32),state[2],state[3],state[4])


def runtime_contract():
    return dict(python=platform.python_version(),numpy=np.__version__,torch=str(torch.__version__),
                platform=platform.platform(),machine=platform.machine(),torch_threads=torch.get_num_threads(),
                source_sha256={f:file_sha256(ROOT/f) for f in SOURCES})


def new_policy(config, seed):
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        return KCityPolicy(config)


class KCityPPO(PPO):
    def __init__(self, policy_config=None, *, seed=11, device='cpu', hparams=None):
        self.hparams=deepcopy(DEFAULT_PPO if hparams is None else hparams)
        if set(self.hparams)!=set(DEFAULT_PPO):raise ValueError('PPO hyperparameter keys differ')
        model=new_policy(policy_config,seed)
        np_state=np.random.get_state()
        try:
            with torch.random.fork_rng(devices=[]):
                super().__init__(73,2,policy=model,seed=seed,device=device,**self.hparams)
        finally:np.random.set_state(np_state)
        self.seed=seed
        self.sampling_generator=torch.Generator(device=self.device).manual_seed(seed)
        self.update_rng=np.random.RandomState(seed)
        self.initialization=dict(method='B2',bc_source=None)

    @torch.no_grad()
    def act(self,obs):
        tensor=torch.as_tensor(obs,dtype=torch.float32,device=self.device).unsqueeze(0)
        action,lp,value=self.policy.sample(tensor,generator=self.sampling_generator)
        return action[0].cpu().numpy().astype(np.float32),float(lp.item()),float(value.item())

    @torch.no_grad()
    def predict(self,obs,deterministic=True):
        if not deterministic:return self.act(obs)[0]
        return self.policy.predict(obs,True)

    def initialize_bc(self,source,source_id):
        if self.num_timesteps or self.num_updates or self.optimizer.state or len(self.buffer):
            raise ValueError('BC initialization is only allowed on a fresh PPO run')
        initialize_from_bc(self.policy,source)
        self.initialization=dict(method='B3',bc_source=source_id)

    def update(self,advantages,returns):
        if len(self.buffer)==0 or not np.isfinite(advantages).all() or not np.isfinite(returns).all():
            raise ValueError('PPO update requires a finite nonempty rollout')
        if len(advantages)!=len(self.buffer) or len(returns)!=len(self.buffer):
            raise ValueError('Advantage/return length mismatch')
        outer=np.random.get_state()
        try:
            np.random.set_state(self.update_rng.get_state())
            return super().update(advantages,returns)
        finally:
            self.update_rng.set_state(np.random.get_state());np.random.set_state(outer)

    def training_state(self):
        return dict(policy=self.policy.state_dict(),optimizer=self.optimizer.state_dict(),
            seed=self.seed,device_type=self.device.type,initialization=self.initialization,
            num_timesteps=self.num_timesteps,num_updates=self.num_updates,
            num_optimizer_steps=self.num_optimizer_steps,sampling_rng=self.sampling_generator.get_state(),
            update_rng=pack_numpy(self.update_rng.get_state()),buffer=buffer_state(self.buffer))

    def restore_training_state(self,state):
        if state['seed']!=self.seed or state['device_type']!=self.device.type:
            raise ValueError('Resume seed/device mismatch')
        self.policy.load_state_dict(state['policy'],strict=True)
        self.optimizer.load_state_dict(state['optimizer'])
        self.initialization=state['initialization']
        for k in ['num_timesteps','num_updates','num_optimizer_steps']:setattr(self,k,state[k])
        self.sampling_generator.set_state(state['sampling_rng'].cpu())
        self.update_rng.set_state(unpack_numpy(state['update_rng']))
        restore_buffer(self.buffer,state['buffer'])


class KCityBC:
    def __init__(self,policy_config=None,*,seed=11,lr=3e-4,device='cpu'):
        self.seed,self.lr,self.device=seed,lr,torch.device(device)
        self.policy=new_policy(policy_config,seed).to(self.device)
        self.optimizer=bc_optimizer(self.policy,lr)
        self.sampler=np.random.default_rng(seed)
        self.updates=0

    def loss(self,obs,actions,masks):
        obs=torch.as_tensor(obs,dtype=torch.float32,device=self.device)
        actions=torch.as_tensor(actions,dtype=torch.float32,device=self.device)
        if not np.isin(np.asarray(masks),[0,1]).all():raise ValueError('Invalid BC mask values')
        masks=torch.as_tensor(masks,dtype=torch.bool,device=self.device)
        return bc_loss(self.policy,obs,actions,masks)

    def train_batch(self,obs,actions,masks):
        loss,parts=self.loss(obs,actions,masks)
        if not torch.isfinite(loss):raise ValueError('BC loss is not finite')
        self.optimizer.zero_grad();loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in self.policy.parameters()):
            raise ValueError('BC gradients are not finite')
        self.optimizer.step();self.updates+=1
        return dict(loss=float(loss.detach()),**{k:float(v.detach()) for k,v in parts.items()})

    def config(self):return dict(policy=self.policy.config,seed=self.seed,lr=self.lr,device_type=self.device.type)

    def save_checkpoint(self,path,run_state):
        write_bundle(path,'bc',self.config(),dict(policy=self.policy.state_dict(),
            optimizer=self.optimizer.state_dict(),updates=self.updates,
            sampler=self.sampler.bit_generator.state,run_state=deepcopy(run_state)))

    def load_checkpoint(self,path,*,expected_data_id=None):
        payload=read_bundle(path,'bc',self.config())
        if expected_data_id is not None and payload['run_state'].get('data_id')!=expected_data_id:
            raise ValueError('BC dataset identity mismatch')
        self.policy.load_state_dict(payload['policy'],strict=True)
        self.optimizer.load_state_dict(payload['optimizer']);self.updates=payload['updates']
        self.sampler.bit_generator.state=payload['sampler']
        return deepcopy(payload['run_state'])


def buffer_state(buffer):
    return [dict(obs=o.tolist(),action=a.tolist(),log_prob=lp,reward=r,value=v,
            terminated=bool(term),truncated=trunc,next_value=nv,action_mask=mask)
        for o,a,lp,r,v,term,trunc,nv,mask in zip(buffer.obs,buffer.actions,buffer.log_probs,
            buffer.rewards,buffer.values,buffer.dones,buffer.truncated,buffer.next_values,buffer.action_masks)]


def restore_buffer(buffer,rows):
    buffer.clear()
    for row in rows:buffer.add(**row)


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

    def run_until(self,target,*,fixture=False):
        """Absolute transition cap. Research calls require a frozen enabled protocol.

        Bounded contract_check fixtures may exercise real optimizer mechanics;
        they are never research training runs or expert dataset records.
        """
        if isinstance(target,bool) or not isinstance(target,int) or target<self.agent.num_timesteps:
            raise ValueError('Absolute nondecreasing transition target required')
        p=self.env.contract['protocol']
        if fixture:
            if self.namespace!='contract_check' or target>32:
                raise ValueError('Unfrozen fixture budget is limited to 32 contract-check transitions')
        elif not p['research_settings_frozen'] or not p['training']['enabled']:
            raise RuntimeError('Research training is disabled until KC-05/06 gates and freeze')
        history=[]
        while self.agent.num_timesteps<target or len(self.agent.buffer):
            room=self.agent.n_steps-len(self.agent.buffer)
            count=min(max(0,room),target-self.agent.num_timesteps)
            if count:self.collect(count)
            if len(self.agent.buffer):
                stats=self.update()
                history.append(dict(transitions=self.agent.num_timesteps,
                    updates=self.agent.num_updates,optimizer_steps=self.agent.num_optimizer_steps,**stats))
        return history

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


def write_bundle(path,kind,config,payload,env=None):
    path=Path(path).resolve()
    if path.exists():raise FileExistsError('Checkpoint must use a new immutable path')
    path.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix=path.name+'.partial-',dir=path.parent))
    try:
        if env is not None:env.save_resume_state(staging/'environment')
        torch.save(payload,staging/'training.pt')
        meta=dict(schema='KC-TRAINING-RESUME-v1',kind=kind,config=config,runtime=runtime_contract(),
                  training_ready=False)
        (staging/'metadata.json').write_text(json.dumps(meta,indent=2,allow_nan=False)+'\n')
        manifest={str(p.relative_to(staging)):file_sha256(p) for p in sorted(staging.rglob('*')) if p.is_file()}
        (staging/'SHA256.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for p in staging.rglob('*'):
            if p.is_file():
                with p.open('rb') as f:os.fsync(f.fileno())
        if hasattr(os,'O_DIRECTORY'):
            fd=os.open(staging,os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        staging.rename(path)
        if hasattr(os,'O_DIRECTORY'):
            fd=os.open(path.parent,os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
    except BaseException:
        shutil.rmtree(staging);raise


def read_bundle(path,kind,config):
    path=Path(path).resolve();manifest=json.loads((path/'SHA256.json').read_text())
    actual={str(p.relative_to(path)):file_sha256(p) for p in path.rglob('*') if p.is_file() and p.name!='SHA256.json'}
    if actual!=manifest:raise ValueError('Checkpoint file set/SHA256 mismatch')
    meta=json.loads((path/'metadata.json').read_text())
    if meta['schema']!='KC-TRAINING-RESUME-v1' or meta['kind']!=kind or meta['config']!=config:
        raise ValueError('Checkpoint kind/run/config mismatch')
    if meta['runtime']!=runtime_contract():raise ValueError('Checkpoint source/runtime mismatch')
    return torch.load(path/'training.pt',map_location='cpu',weights_only=True)
