"""BC training: fixed train/val views from the expert pool and the resumable BC run loop (B1)."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

import numpy as np
import torch

from kcity.training.experiment import experiment_sha256, is_pilot, run_metadata, training_config
from kcity.data.dataset import atomic_json, shard_directories
from kcity.data.pool import pool_data_id, pool_reports
from kcity.data.storage import verify_bundle
from kcity.env.config import ROOT, digest, file_sha256, load_contract
from kcity.env.observation import (CONFLICT, INSIDE, LANE_ENDS, LANE_LEFT, SPEED, TLS_DIST,
                                   TLS_GREEN, TLS_RED, TLS_YELLOW, YIELD_SIGN)
from kcity.training.runs import Owner, now, read, require, stopped
from kcity.training.logging import IntervalMean
from kcity.policy.bc import KCityBC
from kcity.policy.checkpoint import read_bundle


def decision_weights(observation, action, weight):
    """Give demonstrated merges the highest weight and other local decision windows an intermediate weight."""
    lane_drop = observation[:, LANE_ENDS] > .5
    yield_traffic = ((observation[:, YIELD_SIGN] > .5) & (observation[:, CONFLICT] > .5)
                     & (observation[:, LANE_LEFT] < .4) & (observation[:, INSIDE] < .5))
    signal = ((observation[:, TLS_DIST] < .4) & ((observation[:, TLS_RED] > .5)
              | (observation[:, TLS_YELLOW] > .5)
              | ((observation[:, TLS_GREEN] > .5) & (observation[:, SPEED] < .25))))
    weights = np.where(lane_drop | yield_traffic | signal, np.sqrt(weight), 1.)
    return np.where(np.abs(action[:, 1]) >= .5, weight, weights)


def build_views(pool,output,spec,*,workers=1,revalidate=False):
    """Fixed BC train/val views from successful Episodes of an expert pool (one dataset or parallel parts)."""
    output = Path(output)
    require(not output.exists(),'New immutable BC view directory required')
    print(f'[BC views] Checking expert pool: {pool}', flush=True)
    parts,reports = pool_reports(pool,workers=workers,revalidate=revalidate)
    pilot = is_pilot(spec)
    contract = load_contract(ROOT / spec['base_contract']['path'])
    for part in parts:
        config = read(part/'RUN.json')
        require(config['source_stage']==('pilot_expert_pool' if pilot else 'expert_pool')
                and config['eligible_for_research_training'] is (not pilot), 'Not a new main expert pool or matching pilot pool: '+str(part))
        require(read(part/'RELEASE.json')['eligible_for_research_training'] is (not pilot),
                'Pool release not eligible for this run purpose: '+str(part))
        require(config['contract'] == contract, 'BC expert pool environment contract mismatch')
    report = dict(unique_transitions=sum(r['unique_transitions'] for r in reports),
                  episodes=[e for r in reports for e in r['episodes']])
    require(report['unique_transitions']>=spec['budgets']['expert_valid_transitions_min'],'Main pool budget not met')
    shards = [folder for part in parts for folder in shard_directories(part)]
    rng = np.random.default_rng(20261115)
    arrays = {}
    for split,size in [('expert_train',spec['bc']['train_view_rows']),('expert_val',spec['bc']['validation_view_rows'])]:
        episodes = [e for e in report['episodes'] if e['data_split']==split and
                    e['metrics']['compliant_completion'] is True and e['metrics']['primary_end_reason']=='arrival']
        total = sum(e['metrics']['decision_count'] for e in episodes)
        require(total>=size,'Insufficient successful rows for '+split)
        print(f'[BC views] {split}: selecting {size:,} of {total:,} eligible rows', flush=True)
        uids = [e['episode_uid'] for e in episodes]
        probabilities = None
        weight = spec['bc'].get('decision_sampling_weight', 1)
        if split == 'expert_train' and weight != 1:
            require(np.isfinite(weight) and weight >= 1, 'Invalid BC decision sampling weight')
            pieces = []
            for folder in shards:
                with np.load(folder/'numeric.npz', allow_pickle=False) as a:
                    eligible = (a['data_split'] == split) & np.isin(a['episode_uid'], uids)
                    pieces.append(decision_weights(a['observation'][eligible], a['action_raw'][eligible], weight))
            weights = np.concatenate(pieces)
            require(len(weights) == total, 'Weighted population differs from successful train rows')
            probabilities = weights / weights.sum()
        chosen = np.sort(rng.choice(total, size, replace=False, p=probabilities))
        chunks = {k:[] for k in ['observation','action_target','transition_uid']}
        cursor = 0
        for shard_index,folder in enumerate(shards,1):
            with np.load(folder/'numeric.npz',allow_pickle=False) as a:
                eligible = np.flatnonzero((a['data_split']==split)&np.isin(a['episode_uid'],uids))
                local = chosen[(chosen>=cursor)&(chosen<cursor+len(eligible))]-cursor
                indices = eligible[local]
                chunks['observation'].append(a['observation'][indices].copy())
                chunks['action_target'].append(np.clip(a['action_raw'][indices],-1,1))  # the executed action
                chunks['transition_uid'].append(a['transition_uid'][indices].copy())
                cursor += len(eligible)
            if shard_index % 500 == 0 or shard_index == len(shards):
                print(f'[BC views] {split}: shards={shard_index:,}/{len(shards):,}', flush=True)
        require(cursor==total,'Eligible count differs from completed Episode records')
        arrays[split] = {k:np.concatenate(v) for k,v in chunks.items()}
        require(len(set(arrays[split]['transition_uid']))==size,'Duplicate BC view rows')
    output.mkdir(parents=True)
    for split,data in arrays.items():
        np.savez_compressed(output/(split+'.npz'),**data)
    body = dict(schema='KC-BC-VIEWS-v2',pool=str(Path(pool).resolve()),data_id=pool_data_id(pool),
                run_purpose='pilot' if pilot else 'main', contract_sha256=digest(contract),
                parts=[str(part.resolve()) for part in parts],
                experiment_sha256=experiment_sha256(spec),rng_seed=20261115,
                files={p.name:file_sha256(p) for p in output.glob('*.npz')})
    atomic_json(output/'MANIFEST.json',dict(body,view_id=digest(body)))
    print(f'[BC views] COMPLETE output={output}', flush=True)
    return read(output/'MANIFEST.json')


def read_views(folder):
    folder = Path(folder)
    manifest = read(folder/'MANIFEST.json')
    require(manifest['view_id']==digest({k:v for k,v in manifest.items() if k!='view_id'}),'BC view identity mismatch')
    require(pool_data_id(manifest['pool'])==manifest['data_id'],'Pool changed after BC view selection')
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
            loss,parts = model.loss(data['observation'][i:end],data['action_target'][i:end])
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
    print(f'[BC seed={seed}] Loading views: {views}', flush=True)
    manifest,data = read_views(views)
    pilot = is_pilot(spec)
    require(manifest.get('run_purpose', 'main') == ('pilot' if pilot else 'main'), 'BC view run purpose mismatch')
    contract_hash = digest(load_contract(ROOT / spec['base_contract']['path']))
    view_contract = manifest.get('contract_sha256')
    require(view_contract == contract_hash, 'BC views environment contract mismatch')
    cfg = training_config(spec,'pilot_bc' if pilot else 'main_bc',seed,views=str(Path(views).resolve()),view_id=manifest['view_id'],device=device)
    owner = Owner(root,cfg,resume)
    model = KCityBC(spec['rlpd']['hidden_dims'],seed=seed,lr=spec['bc']['learning_rate'],device=device)
    best = dict(loss=None,path=None)
    clock=time.monotonic()
    try:
        if (root/'LATEST.json').exists():
            state = model.load_checkpoint(root/read(root/'LATEST.json')['path'],expected_data_id=manifest['data_id'])
            require(state['view_id']==manifest['view_id'],'BC resume views changed')
            best = state['best']
            if best['path']:atomic_json(root/'BEST.json',best)
        training_interval = IntervalMean()
        interval_start = model.updates
        session_start_updates = model.updates
        target = spec['bc']['updates_per_seed']
        print(f'[BC seed={seed}] {"RESUME" if resume else "START"} device={device} '
              f'updates={model.updates:,}/{target:,} train_rows={len(data["expert_train"]["observation"]):,} '
              f'val_rows={len(data["expert_val"]["observation"]):,} '
              f'log_every={spec["bc"]["validate_every_updates"]:,} updates output={root}', flush=True)
        for update in range(model.updates,spec['bc']['updates_per_seed']):
            train = data['expert_train']
            idx = model.sampler.integers(0,len(train['observation']),spec['bc']['batch_size'])
            training_metrics=model.train_batch(train['observation'][idx],train['action_target'][idx])
            training_interval.add(training_metrics)
            boundary = model.updates%spec['bc']['validate_every_updates']==0
            if boundary or stopped(root) or model.updates==spec['bc']['updates_per_seed']:
                path = f'update-{model.updates:06d}'
                val = validation_loss(model,data['expert_val']) if boundary else None
                if val is not None and (best['loss'] is None or val['loss']<best['loss']):
                    best = dict(loss=val['loss'],path=path)
                state = dict(data_id=manifest['data_id'],view_id=manifest['view_id'],best=best,validation=val)
                model.save_checkpoint(root/path,state)
                metrics = training_interval.mean()
                with (root/'curve.jsonl').open('a') as stream:
                    stream.write(json.dumps(dict(updates=model.updates,validation=val,training=metrics,
                        metric_aggregation='interval_mean', training_update_count=training_interval.count,
                        interval_start_updates=interval_start,
                        session_wall_s=time.monotonic()-clock))+'\n')
                training_interval.reset()
                interval_start = model.updates
                atomic_json(root/'LATEST.json',dict(path=path,updates=model.updates))
                if best['path']:
                    atomic_json(root/'BEST.json',best)
                retain_bc(root,best)
                atomic_json(root/'STATUS.json',dict(phase='STOPPED' if stopped(root) else ('BC_PILOT_TRAINING' if pilot else 'BC_MAIN_TRAINING'),
                    updated_at=now(),updates=model.updates,target=spec['bc']['updates_per_seed'],best=best,
                    session_wall_s=time.monotonic()-clock,run=run_metadata()))
                elapsed = time.monotonic()-clock
                rate = (model.updates-session_start_updates)/max(elapsed,1e-9)
                eta = (target-model.updates)/rate if rate > 0 else None
                fmt = lambda value: 'n/a' if value is None else f'{value:.6f}'
                print(f'[BC seed={seed}] updates={model.updates:,}/{target:,} '
                      f'({100*model.updates/target:.1f}%) '
                      f'train_loss={fmt(metrics.get("loss"))} '
                      f'train_accel_mse={fmt(metrics.get("accel_mse"))} '
                      f'train_lane_mse={fmt(metrics.get("lane_mse"))} '
                      f'val_loss={fmt(val["loss"] if val else None)} '
                      f'val_accel_mse={fmt(val.get("accel_mse") if val else None)} '
                      f'val_lane_mse={fmt(val.get("lane_mse") if val else None)} '
                      f'best_val_loss={fmt(best["loss"])} '
                      f'elapsed={elapsed:.1f}s updates/s={rate:.1f} '
                      f'eta={"n/a" if eta is None else f"{eta:.1f}s"} checkpoint={path}', flush=True)
            if stopped(root):
                print(f'[BC seed={seed}] STOPPED updates={model.updates:,}/{target:,} output={root}', flush=True)
                return
        atomic_json(root/'COMPLETE.json',dict(updates=model.updates,best=best,completed_at=now()))
        print(f'[BC seed={seed}] COMPLETE updates={model.updates:,}/{target:,} '
              f'best_checkpoint={best["path"]} best_val_loss={best["loss"]} output={root}', flush=True)
    finally:
        owner.close()
