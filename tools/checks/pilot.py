"""KC06 isolated pilot orchestration: fresh data/BC and B2/B3, never main research.

Default budget50k/method. STOP file or SIGTERM saves at a completed control
boundary. Immutable model checkpoints live outside Git; source hashes are pinned.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from kcity.training import KCityBC,KCityPPO,KCityRunner,DEFAULT_PPO
from kcity.env.env import SumoKCityEnv
from kcity.env.config import digest,file_sha256,load_contract,make_case
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.data.collector import build_config,ExpertCollector
from kcity.data.dataset import ShardWriter,atomic_json,validate_dataset,iter_bc_batches
from kcity.evaluator import evaluate_cases

STOP=False
def stop_handler(*args):
    global STOP
    STOP=True
def now():return datetime.now().astimezone().isoformat()


def pilot_plan(contract):
    """Reserved high case indices; final namespace is never touched."""
    cases=[make_case(contract,'dev',s,1000000) for s in ['A','B','C']]
    return dict(cases=cases,panel_sha256=digest(cases),scope='pilot-dev3-not-main-dev100')


def check_config(config):
    if config['purpose']!='KC06_PILOT_ONLY' or not 1<=config['ppo_cap']<=50000:
        raise ValueError('Pilot purpose/cap invalid')
    if config['method_order']!=['B2','B3'] or config['train_case_start']!=1000000:
        raise ValueError('Pilot method/case contract invalid')
    if not 1<=config['expert_cap']<=10000 or not 1<=config['bc_updates']<=1000:
        raise ValueError('Pilot data/BC cap invalid')


class Pilot:
    def __init__(self,root,config,*,resume=False):
        check_config(config);self.root=Path(root).resolve();self.config=config;self.started=time.monotonic()
        if resume:
            if json.loads((self.root/'CONFIG.json').read_text())!=config:raise ValueError('Pilot config/source changed')
        else:
            self.root.mkdir(parents=True,exist_ok=False);atomic_json(self.root/'CONFIG.json',config)
            for name in config['source_sha256']:
                dst=self.root/'source'/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes((ROOT/name).read_bytes())
        self.status=dict(phase='PREPARING',pid=os.getpid(),started_at=now(),methods={},purpose=config['purpose'],
            main_research_training_started=False,training_ready=False)
        if (self.root/'STATUS.json').exists():self.status.update(json.loads((self.root/'STATUS.json').read_text()))
        self.status.update(pid=os.getpid(),updated_at=now())
        self.lock=self.root/'OWNER.json'
        if self.lock.exists():
            old=json.loads(self.lock.read_text())
            try:os.kill(old['pid'],0)
            except ProcessLookupError:pass
            else:raise RuntimeError('Pilot owner still alive')
        atomic_json(self.lock,dict(pid=os.getpid(),created_at=now()))
        self.write_status()

    def write_status(self,**changes):
        self.status.update(changes);self.status.update(updated_at=now(),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        atomic_json(self.root/'STATUS.json',self.status)
        (self.root/'HANDOFF.md').write_text(f"# KC06 pilot\n\nPhase: {self.status['phase']}\n\nLive progress: STATUS.json\nConfig: CONFIG.json\nStop: create STOP file; resume with same command plus --resume.\n\nMain RQ training remains disabled. Pilot weights/data must not initialize main experiments.\n")

    def stopped(self):return STOP or (self.root/'STOP').exists()

    def prepare_data(self):
        path=self.root/'expert'
        if (path/'QUALITY.json').exists():return json.loads((path/'QUALITY.json').read_text())
        self.write_status(phase='COLLECTING_PILOT_EXPERT')
        env=SumoKCityEnv(background=True);expert=KCityRuleExpert();writer=None
        try:
            plan=[dict(scenario_id=['A','B','C'][i%3],namespace='expert_val' if i%5==4 else 'expert_train',
                data_split='expert_val' if i%5==4 else 'expert_train',case_index=1000000+i) for i in range(180)]
            cfg=build_config(env,expert,'KC06-pilot-expert-'+self.root.name,plan)
            cfg['source_stage']='pilot';cfg['data_purpose']='KC06_pilot_not_main_pool'
            writer=ShardWriter(path,cfg,resume=(path/'RUN.json').exists(),shard_rows=256)
            collector=ExpertCollector(env,expert,writer)
            while writer.count<self.config['expert_cap']:
                collector.collect_until(min(self.config['expert_cap'],writer.count+1024))
                self.write_status(pilot_expert_transitions=writer.count)
                if self.stopped():return None
            report=validate_dataset(path);atomic_json(path/'QUALITY.json',report)
            return report
        finally:
            if writer is not None:writer.close()
            env.close()

    def bc(self,quality):
        model=KCityBC(seed=self.config['seed'],device=self.config['device']);folder=self.root/'bc';folder.mkdir(exist_ok=True)
        if (folder/'BEST.json').exists() and (folder/'COMPLETE').exists():
            model.load_checkpoint(folder/json.loads((folder/'BEST.json').read_text())['path'],expected_data_id=quality['data_id'])
            return model
        self.write_status(phase='BC_PILOT_TRAINING')
        data={}
        for split in ['expert_train','expert_val']:
            batches=list(iter_bc_batches(self.root/'expert',split,allow_debug=True))
            if not batches:raise RuntimeError('No successful whole expert Episodes in '+split)
            data[split]={key:np.concatenate([b[key] for b in batches]) for key in ['observation','action_target','action_mask']}
        def batch(d,idx):return [d[k][idx] for k in ['observation','action_target','action_mask']]
        best=json.loads((folder/'BEST.json').read_text())['validation_loss'] if (folder/'BEST.json').exists() else float('inf')
        checkpoints=sorted(folder.glob('update-*'))
        if checkpoints:model.load_checkpoint(checkpoints[-1],expected_data_id=quality['data_id'])
        for i in range(model.updates,self.config['bc_updates']):
            d=data['expert_train'];idx=model.sampler.integers(0,len(d['observation']),256)
            metrics=model.train_batch(*batch(d,idx))
            if (i+1)%100==0 or i+1==self.config['bc_updates']:
                with torch.no_grad():val,_=model.loss(*batch(data['expert_val'],slice(None)))
                score=float(val);name=f'update-{i+1:06d}'
                model.save_checkpoint(folder/name,dict(data_id=quality['data_id'],purpose='pilot',validation_loss=score))
                with (folder/'curve.jsonl').open('a') as f:f.write(json.dumps(dict(update=i+1,validation_loss=score,**metrics))+'\n')
                if score<best:best=score;atomic_json(folder/'BEST.json',dict(path=name,validation_loss=score))
                self.write_status(bc_updates=i+1,bc_validation_loss=score)
                if self.stopped():return None
        (folder/'COMPLETE').write_text(now())
        model.load_checkpoint(folder/json.loads((folder/'BEST.json').read_text())['path'],expected_data_id=quality['data_id'])
        return model

    def evaluate(self,agent,folder,transitions):
        path=folder/f'eval-{transitions:06d}.json'
        if path.exists():return
        env=SumoKCityEnv(background=True)
        try:
            records,summary=evaluate_cases(agent,env,pilot_plan(env.contract))
            atomic_json(path,dict(actual_transitions=transitions,records=records,aggregate=summary,purpose='pilot_dev3'))
        finally:env.close()

    def train(self,method,bc):
        folder=self.root/method;folder.mkdir(exist_ok=True)
        if (folder/'COMPLETE').exists():return True
        env=SumoKCityEnv(background=True)
        agent=KCityPPO(seed=self.config['seed'],device=self.config['device'])
        runner=KCityRunner(agent,env,run_id=self.root.name+'-'+method,namespace='train')
        runner.case_cursor=self.config['train_case_start']
        clock=time.monotonic();baseline=0
        try:
            if method=='B3':bc_source=json.loads((self.root/'bc/BEST.json').read_text());agent.initialize_bc(bc.policy,digest(bc_source))
            latest=folder/'LATEST.json'
            if latest.exists():runner.load_checkpoint(folder/json.loads(latest.read_text())['path'])
            baseline=agent.num_timesteps
            self.write_status(phase='PPO_PILOT_TRAINING',active_method=method)
            self.evaluate(agent,folder,agent.num_timesteps)
            while agent.num_timesteps<self.config['ppo_cap']:
                boundary=min(self.config['ppo_cap'],(agent.num_timesteps//10000+1)*10000)
                count=min(agent.n_steps-len(agent.buffer),boundary-agent.num_timesteps)
                for i in range(count):
                    runner.step()
                    if self.stopped():break
                # The last segment and STOP are explicit rollout cuts, not MDP terminations.
                stats=runner.update()
                elapsed=time.monotonic()-clock
                record=dict(transitions=agent.num_timesteps,updates=agent.num_updates,
                    optimizer_steps=agent.num_optimizer_steps,session_wall_s=elapsed,
                    session_transitions_per_s=(agent.num_timesteps-baseline)/elapsed,**stats)
                with (folder/'curve.jsonl').open('a') as f:f.write(json.dumps(record,allow_nan=False)+'\n')
                name=f'checkpoint-{agent.num_timesteps:06d}'
                runner.save_checkpoint(folder/name);atomic_json(latest,dict(path=name,**record))
                self.status['methods'][method]=dict(**record,latest_checkpoint=str(folder/name))
                self.write_status()
                if self.stopped():return False
                if agent.num_timesteps==boundary:self.evaluate(agent,folder,agent.num_timesteps)
            (folder/'COMPLETE').write_text(now());return True
        finally:env.close()

    def run(self):
        try:
            quality=self.prepare_data()
            if quality is None:self.write_status(phase='STOPPED');return
            bc=self.bc(quality)
            if bc is None:self.write_status(phase='STOPPED');return
            for method in self.config['method_order']:
                if not self.train(method,bc):self.write_status(phase='STOPPED');return
            self.write_status(phase='PILOT_TRAINING_COMPLETE',remaining='90-case feasibility,resource/backup review and scientific freeze remain')
        except BaseException as e:
            self.write_status(phase='FAILED',error=type(e).__name__+': '+str(e));raise
        finally:self.lock.unlink(missing_ok=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--device',choices=['cpu','cuda'],default='cuda');ap.add_argument('--resume',action='store_true')
    args=ap.parse_args();torch.set_num_threads(1)
    signal.signal(signal.SIGTERM,stop_handler);signal.signal(signal.SIGINT,stop_handler)
    if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
    sources={str(p.relative_to(ROOT)):file_sha256(p) for directory in ['kcity','rl','tools/map','tools/checks','legacy/highway/env','configs/kcity/v1']
        for p in (ROOT/directory).rglob('*') if p.is_file() and p.suffix in ['.py','.json']}
    config=dict(purpose='KC06_PILOT_ONLY',ppo_cap=50000,expert_cap=10000,bc_updates=1000,
        method_order=['B2','B3'],train_case_start=1000000,seed=11,device=args.device,
        source_sha256=sources,contract_sha256=digest(load_contract()),main_training_enabled=False)
    Pilot(args.output,config,resume=args.resume).run()


if __name__=='__main__':main()
