"""Shared BC/PPO actor-critic for the 73-D observation: lane masks from the observation, sampling, BC loss and BC->PPO transfer."""
from copy import deepcopy
import numpy as np
import torch
from torch.distributions import Categorical, Normal
import torch.nn.functional as F

from policy.networks import HybridActorCritic

POLICY_ID = 'KC-HYBRID73-v1-candidate'
DEFAULT_POLICY = dict(policy_id=POLICY_ID, obs_dim=73, hidden_sizes=[256,256],
                      activation='relu', init_log_std=-.5, lane_keep_bias=.5,
                      preprocessing='env_fixed_obs73_identity_v1')


class KCityPolicy(HybridActorCritic):
    def __init__(self, config=None):
        self.config=deepcopy(DEFAULT_POLICY if config is None else config)
        if set(self.config)!=set(DEFAULT_POLICY) or any(self.config[k]!=DEFAULT_POLICY[k]
                for k in ['policy_id','obs_dim','preprocessing']):
            raise ValueError('Unsupported K-CITY policy/preprocessing contract')
        sizes=self.config['hidden_sizes']
        if not sizes or any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in sizes):
            raise ValueError('Hidden sizes must be positive integers')
        super().__init__(73,hidden_sizes=sizes,activation=self.config['activation'],
                         init_log_std=self.config['init_log_std'],lane_keep_bias=self.config['lane_keep_bias'])

    @staticmethod
    def mask_from_obs(obs):
        obs=torch.as_tensor(obs)
        if obs.shape[-1]!=73 or not torch.isfinite(obs).all() or (obs.abs()>1).any():
            raise ValueError('Expected finite bounded OBS73')
        available=(obs[...,51]<.5)&(obs[...,52]<=1e-9)
        return torch.stack([available&(obs[...,42]>.5),torch.ones_like(available),
                            available&(obs[...,44]>.5)],dim=-1)

    def distributions(self, obs, lane_mask=None):
        expected=self.mask_from_obs(obs)
        if lane_mask is not None:
            raw_mask=torch.as_tensor(lane_mask)
            if not ((raw_mask==0)|(raw_mask==1)).all():
                raise ValueError('Lane masks must contain only boolean values')
        mask=expected if lane_mask is None else torch.as_tensor(lane_mask,device=obs.device,dtype=torch.bool)
        if mask.shape!=expected.shape or not torch.equal(mask,expected):
            raise ValueError('Stored lane mask does not match observation geometry/cooldown')
        mu,std,logits,value=self(obs)
        logits=logits.masked_fill(~mask,-torch.inf)
        return Normal(mu,std),Categorical(logits=logits),value

    def sample(self, obs, lane_mask=None, generator=None):
        nd,cd,value=self.distributions(obs,lane_mask)
        accel=nd.loc+nd.scale*torch.randn(nd.loc.shape,device=obs.device,generator=generator)
        idx=torch.multinomial(cd.probs,1,generator=generator).squeeze(-1)
        cmds=torch.as_tensor(self.LANE_CMDS,device=obs.device)[idx]
        action=torch.cat([accel,cmds.unsqueeze(-1)],dim=-1)
        return action,nd.log_prob(accel).sum(-1)+cd.log_prob(idx),value

    def det_action(self, obs, lane_mask=None):
        nd,cd,_=self.distributions(obs,lane_mask)
        idx=cd.logits.argmax(-1)
        return torch.cat([nd.loc,torch.as_tensor(self.LANE_CMDS,device=obs.device)[idx].unsqueeze(-1)],dim=-1)

    def evaluate_actions(self, obs, actions, lane_mask=None):
        nd,cd,value=self.distributions(obs,lane_mask)
        if actions.shape!=obs.shape[:-1]+(2,):raise ValueError('Hybrid action batch shape mismatch')
        cmds=actions[...,1]
        if not torch.isfinite(actions).all() or not ((cmds==1)|(cmds==0)|(cmds==-1)).all():
            raise ValueError('Raw hybrid actions require exact lane commands +1/0/-1')
        idx=(1-cmds).long()
        mask=self.mask_from_obs(obs)
        if not mask.gather(-1,idx.unsqueeze(-1)).all():
            raise ValueError('Stored action selected a masked lane')
        return nd.log_prob(actions[...,:1]).sum(-1)+cd.log_prob(idx),nd.entropy().sum(-1)+cd.entropy(),value

    def lane_entropy(self, obs):return self.distributions(obs)[1].entropy()
    def lane_change_prob(self, obs):return 1-self.distributions(obs)[1].probs[...,1]

    def actor_state(self):
        return {k:v.detach().cpu().clone() for k,v in self.state_dict().items()
                if k.startswith(('trunk.','mu_head.','lane_head.'))}

    @torch.no_grad()
    def predict(self, obs, deterministic=True):
        tensor=torch.as_tensor(obs,dtype=torch.float32,device=self.log_std.device).unsqueeze(0)
        action=self.det_action(tensor) if deterministic else self.sample(tensor)[0]
        return action[0].cpu().numpy().astype(np.float32)


def bc_optimizer(policy, lr=3e-4):
    """BC trains trunk/mean/lane only; critic head and exploration std stay fixed."""
    if not torch.equal(policy.log_std.detach(),torch.full_like(policy.log_std,policy.config['init_log_std'])):
        raise ValueError('BC log_std must remain at its fixed configured value')
    for name,param in policy.named_parameters():
        param.requires_grad_(not name.startswith('v_head.') and name!='log_std')
    return torch.optim.Adam([p for p in policy.parameters() if p.requires_grad],lr=lr)


def bc_loss(policy, observations, action_raw, lane_masks):
    """MSE on bounded expert acceleration + CE on the requested lane category.

    Gaussian PPO samples remain unbounded; expert labels outside [-1,1] are
    rejected here, not silently clipped into a different supervised target.
    """
    if action_raw.shape!=(observations.shape[0],2) or not torch.isfinite(action_raw).all():
        raise ValueError('Invalid BC action labels')
    if (action_raw[:,0].abs()>1).any():raise ValueError('BC expert acceleration must be bounded')
    # Also validates categorical labels and the same sampling-time mask.
    policy.evaluate_actions(observations,action_raw,lane_masks)
    nd,cd,_=policy.distributions(observations,lane_masks)
    mse=F.mse_loss(nd.loc.squeeze(-1),action_raw[:,0])
    ce=F.cross_entropy(cd.logits,(1-action_raw[:,1]).long())
    return mse+ce,dict(accel_mse=mse,lane_ce=ce)


def initialize_from_bc(target, source):
    """Copy all actor representation keys strictly; keep fresh critic/std/optimizer."""
    if not isinstance(source,KCityPolicy) or not isinstance(target,KCityPolicy):
        raise ValueError('Only the common K-CITY actor can be transferred')
    if target.config!=source.config:raise ValueError('BC/PPO policy configs differ')
    if not torch.equal(source.log_std.detach(),torch.full_like(source.log_std,source.config['init_log_std'])):
        raise ValueError('BC exploration std changed')
    full=target.state_dict();actor=source.actor_state()
    if set(actor)!=set(target.actor_state()):raise ValueError('Actor state keys differ')
    for key,value in actor.items():
        if value.shape!=full[key].shape:raise ValueError('Actor shape mismatch: '+key)
        if not torch.isfinite(value).all():raise ValueError('BC actor contains nonfinite weights')
        full[key]=value.to(full[key].device)
    target.load_state_dict(full,strict=True)
    for param in target.parameters():param.requires_grad_(True)
