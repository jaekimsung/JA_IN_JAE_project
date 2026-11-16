"""BC learner: actor-only optimizer (trunk/mean/lane), MSE+CE loss, resumable checkpoint."""
from copy import deepcopy

import numpy as np
import torch

from policy.checkpoint import read_bundle, write_bundle
from policy.policy import bc_loss, bc_optimizer
from policy.ppo import new_policy


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
