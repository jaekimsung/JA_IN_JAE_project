"""BC training: fixed train/val views from the expert pool and the resumable BC run loop (B1)."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from training.experiment import experiment_sha256, run_metadata, training_config
from data.dataset import atomic_json, shard_directories, validate_dataset
from data.storage import verify_bundle
from env.config import digest, file_sha256
from training.runs import Owner, now, read, require, stopped
from policy.bc import KCityBC
from policy.checkpoint import read_bundle


def build_views(pool,output,spec):
    output = Path(output)
    require(not output.exists(),'New immutable BC view directory required')
    config = read(Path(pool)/'RUN.json')
    report = validate_dataset(pool)
    require(config['source_stage']=='expert_pool' and config['eligible_for_research_training'], 'Not a new main expert pool')
    require(report['unique_transitions']>=spec['budgets']['expert_valid_transitions_min'],'Main pool budget not met')
    require(read(Path(pool)/'RELEASE.json')['eligible_for_research_training'],'Pool release not eligible')
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
                experiment_sha256=experiment_sha256(spec),rng_seed=20261115,
                files={p.name:file_sha256(p) for p in output.glob('*.npz')})
    atomic_json(output/'MANIFEST.json',dict(body,view_id=digest(body)))
    return read(output/'MANIFEST.json')


def read_views(folder):
    folder = Path(folder)
    manifest = read(folder/'MANIFEST.json')
    require(manifest['view_id']==digest({k:v for k,v in manifest.items() if k!='view_id'}),'BC view identity mismatch')
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
    cfg = training_config(spec,'main_bc',seed,views=str(Path(views).resolve()),view_id=manifest['view_id'],device=device)
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
                state = dict(data_id=manifest['data_id'],view_id=manifest['view_id'],best=best,validation=val)
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
                    session_wall_s=time.monotonic()-clock,run=run_metadata()))
            if stopped(root):
                return
        atomic_json(root/'COMPLETE.json',dict(updates=model.updates,best=best,completed_at=now()))
    finally:
        owner.close()
