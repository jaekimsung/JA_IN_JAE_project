"""Shared synthetic fixtures for tests (no simulator, no learning)."""
import numpy as np
import torch

from kcity.policy.policy import KCityPolicy


def serializable(value):
    if isinstance(value,torch.Tensor):
        return dict(dtype=str(value.dtype),shape=list(value.shape),values=value.detach().cpu().tolist())
    if isinstance(value,dict):return {k:serializable(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [serializable(v) for v in value]
    return value


def fixture_batch(n=32):
    obs=np.zeros((n,73),np.float32);obs[:,0]=np.linspace(0,1,n);obs[:,41:46]=1
    obs[::3,42]=0;obs[1::3,44]=0;obs[::7,51]=1;obs[::5,52]=.5
    masks=KCityPolicy.mask_from_obs(obs).numpy();actions=np.zeros((n,2),np.float32)
    actions[:,0]=np.sin(np.arange(n))*.5
    for i in range(n):actions[i,1]=[1,0,-1][np.flatnonzero(masks[i])[i%int(masks[i].sum())]]
    return obs,actions,masks


def trace_rows(transitions):
    return [dict(action=t[0].tolist(),log_prob=t[1],reward=t[2],terminated=t[3],truncated=t[4],info=t[5]) for t in transitions]
