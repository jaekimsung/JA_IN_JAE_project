"""KC06 fixed2Hz pilot replication, fresh seeds22/33 and shared fixed expert data.

No main experiment flags are changed. Seed11 results are never overwritten.
Each seed trains fresh BC1000 and B2/B3 each50k before dev100 evaluation.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import sys

import torch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.checks import pilot
from kcity.training import KCityPPO,read_bundle
from kcity.env.config import digest,file_sha256,load_contract,make_case
from kcity.env.env import SumoKCityEnv
from kcity.data.dataset import atomic_json,validate_dataset
from kcity.evaluator import evaluate_cases,aggregate


def replication_config(seed,device,data_root):
    if seed not in [22,33]:raise ValueError('This replication admits only new seeds22/33')
    source={str(p.relative_to(ROOT)):file_sha256(p) for directory in
        ['kcity','rl','tools/map','tools/checks','legacy/highway/env','configs/kcity/v1']
        for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ['.py','.json']}
    contract=load_contract()
    if contract['protocol']['timing']['control_step_s']!=.5 or contract['protocol']['timing']['sumo_step_s']!=.1:
        raise ValueError('Replication must retain original2Hz/0.1s physics')
    release=json.loads((data_root/'RELEASE.json').read_text())
    return dict(purpose='KC06_PILOT_ONLY',ppo_cap=50000,expert_cap=10000,bc_updates=1000,
        method_order=['B2','B3'],train_case_start=1000000,seed=seed,device=device,
        source_sha256=source,contract_sha256=digest(contract),main_training_enabled=False,
        replication='seed_only_22_33',shared_expert_root=str(data_root.resolve()),
        shared_expert_data_id=release['data_id'],environment_case_order='same as seed11,policy/init RNG vary')


class ReplicationPilot(pilot.Pilot):
    def prepare_data(self):
        source=Path(self.config['shared_expert_root']);report=validate_dataset(source)
        if report['data_id']!=self.config['shared_expert_data_id'] or report['unique_transitions']!=10000:
            raise ValueError('Shared expert data changed or has wrong count')
        if source.name!='expert' or json.loads((source/'RUN.json').read_text())['source_stage']!='pilot':
            raise ValueError('Expected the fixed pilot expert pool')
        link=self.root/'expert'
        if link.exists():
            if not link.is_symlink() or link.resolve()!=source.resolve():raise ValueError('Wrong expert symlink')
        else:link.symlink_to(source.resolve(),target_is_directory=True)
        atomic_json(self.root/'SHARED_DATA.json',dict(path=str(source.resolve()),data_id=report['data_id'],
            generation_cost_counted_once=True,read_only_reuse=True,main_pool_eligible=False))
        self.write_status(pilot_expert_transitions=10000,expert_generation_this_seed=0,
                          shared_expert_data_id=report['data_id'],seed=self.config['seed'])
        return report

    def stopped(self):
        return super().stopped() or (self.root.parent/'STOP').exists()


def expanded_evaluation(seed_root,seed,device,stop_file):
    contract=load_contract()
    cases=[make_case(contract,'dev',sid,2000000+i) for sid,n in [('A',30),('B',30),('C',40)] for i in range(n)]
    root=seed_root/'dev100';root.mkdir(exist_ok=True)
    atomic_json(root/'PANEL.json',dict(cases=cases,sha256=digest(cases),same_as_seed11_diagnosis=True))
    for method in ['BC','B2','B3']:
        output=root/method;output.mkdir(exist_ok=True)
        if (output/'SUMMARY.json').exists():continue
        if method=='BC':
            checkpoint=seed_root/'bc'/json.loads((seed_root/'bc/BEST.json').read_text())['path']
        else:checkpoint=seed_root/method/'checkpoint-050000'
        meta=json.loads((checkpoint/'metadata.json').read_text());payload=read_bundle(checkpoint,meta['kind'],meta['config'])
        agent=KCityPPO(meta['config']['policy'],seed=seed,device=device)
        agent.policy.load_state_dict(payload['policy'] if method=='BC' else payload['agent']['policy'],strict=True)
        records=json.loads((output/'EPISODES.json').read_text()) if (output/'EPISODES.json').exists() else []
        if [r['requested_case_uid'] for r in records]!=[c['case_uid'] for c in cases[:len(records)]]:
            raise ValueError('Existing dev records do not match fixed case order')
        env=SumoKCityEnv(background=True)
        try:
            for case in cases[len(records):]:
                if pilot.STOP or stop_file.exists():return False
                rows,_=evaluate_cases(agent,env,dict(cases=[case]));records.extend(rows)
                atomic_json(output/'EPISODES.json',records)
                atomic_json(root/'STATUS.json',dict(seed=seed,active_method=method,completed=len(records),planned=100))
            atomic_json(output/'SUMMARY.json',dict(seed=seed,method=method,aggregate=aggregate(records,100),
                checkpoint=str(checkpoint),manifest_sha256=file_sha256(checkpoint/'SHA256.json'),
                optimizer_steps_during_evaluation=0,final_cases_executed=0))
        finally:env.close()
    return True


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--shared-data',required=True,type=Path)
    ap.add_argument('--device',choices=['cpu','cuda'],default='cuda');ap.add_argument('--resume',action='store_true')
    args=ap.parse_args();torch.set_num_threads(1)
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
    signal.signal(signal.SIGTERM,pilot.stop_handler);signal.signal(signal.SIGINT,pilot.stop_handler)
    args.output.mkdir(parents=True,exist_ok=args.resume)
    owner=args.output/'OWNER.json'
    if owner.exists():
        old=json.loads(owner.read_text())
        try:os.kill(old['pid'],0)
        except ProcessLookupError:pass
        else:raise RuntimeError('Replication supervisor already running')
    atomic_json(owner,dict(pid=os.getpid(),started_at=pilot.now()))
    status=dict(phase='RUNNING',pid=os.getpid(),seed_order=[22,33],completed_seeds=[],
        policy_hz=2,physics_dt_s=.1,target_per_method=50000,main_training=False)
    atomic_json(args.output/'STATUS.json',status)
    (args.output/'HANDOFF.md').write_text('# Additional pilot seeds22/33\n\nEach seed: fresh BC1000 + B2/B3 each50k, then fixed dev100 per BC/B2/B3.\nUse child seed*/STATUS.json for live learner counters.\nSTOP in this directory or SIGTERM stops safely; remove STOP then rerun same command with --resume.\nShared expert data is read-only; do not delete original pilot.\n')
    try:
        for seed in [22,33]:
            if pilot.STOP or (args.output/'STOP').exists():status['phase']='STOPPED';break
            seed_root=args.output/f'seed{seed}';status.update(active_seed=seed,phase='TRAINING',
                learner_status=str(seed_root/'STATUS.json'));atomic_json(args.output/'STATUS.json',status)
            cfg=replication_config(seed,args.device,args.shared_data)
            runner=ReplicationPilot(seed_root,cfg,resume=args.resume and seed_root.exists())
            runner.run()
            child=json.loads((seed_root/'STATUS.json').read_text())
            if child['phase']!='PILOT_TRAINING_COMPLETE':status['phase']=child['phase'];break
            status['phase']='EVALUATING_DEV100';atomic_json(args.output/'STATUS.json',status)
            if not expanded_evaluation(seed_root,seed,args.device,args.output/'STOP'):
                status['phase']='STOPPED';break
            status['completed_seeds'].append(seed)
        else:status['phase']='COMPLETE'
        status['updated_at']=pilot.now();atomic_json(args.output/'STATUS.json',status)
    except BaseException as error:
        status.update(phase='FAILED',error=type(error).__name__+': '+str(error));atomic_json(args.output/'STATUS.json',status);raise
    finally:owner.unlink(missing_ok=True)


if __name__=='__main__':main()
