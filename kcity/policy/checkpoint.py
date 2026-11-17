"""Learner bundles (atomic directory + SHA256 manifest) and policy loading."""
import json
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
import torch

import platform

from kcity.env.config import file_sha256, git_info



def run_metadata():
    """Recorded with every bundle/run for provenance; never compared on resume."""
    return dict(git=git_info(), python=platform.python_version(), numpy=np.__version__,
                torch=str(torch.__version__), platform=platform.platform())


def write_bundle(path,kind,config,payload,env=None):
    path=Path(path).resolve()
    if path.exists():raise FileExistsError('Checkpoint must use a new immutable path')
    path.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix=path.name+'.partial-',dir=path.parent))
    try:
        if env is not None:env.save_resume_state(staging/'environment')
        torch.save(payload,staging/'training.pt')
        meta=dict(schema='KC-TRAINING-RESUME-v1',kind=kind,config=config,runtime=run_metadata())
        (staging/'metadata.json').write_text(json.dumps(meta,indent=2,allow_nan=False)+'\n')
        manifest={str(p.relative_to(staging)):file_sha256(p) for p in sorted(staging.rglob('*')) if p.is_file()}
        (staging/'SHA256.json').write_text(json.dumps(manifest,indent=2)+'\n')
        for p in staging.rglob('*'):
            if p.is_file():
                with p.open('rb') as f:os.fsync(f.fileno())
        fd=os.open(staging,os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        staging.rename(path)
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
    return torch.load(path/'training.pt',map_location='cpu',weights_only=True)


def load_policy(path, device='cpu'):
    """Load the acting policy (actor) from a BC or RL bundle (inference only)."""
    from kcity.env.observation import OBS_DIM
    from kcity.policy.networks import Actor
    path = Path(path)
    meta = json.loads((path / 'metadata.json').read_text())
    payload = read_bundle(path, meta['kind'], meta['config'])
    state = payload['actor'] if meta['kind'] == 'bc' else payload['agent']['actor']
    policy = Actor(OBS_DIM, tuple(meta['config']['hidden_dims'])).to(device)
    policy.load_state_dict(state, strict=True)
    policy.eval()
    return policy, meta
