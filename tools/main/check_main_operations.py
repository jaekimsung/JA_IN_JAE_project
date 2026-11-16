"""Bounded GPU/data operational checks, never main collection or main training.

Artifacts stay on this computer. No Drive client or upload operation is used.
"""
import argparse
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
import torch
from kcity.training import KCityPPO,KCityBC,KCityRunner,runtime_contract,read_bundle
from kcity.env.config import digest,file_sha256
from kcity.env.env import SumoKCityEnv
from kcity.policy.rule_expert import KCityRuleExpert
from tools.checks.check_policy import serializable,fixture_batch,trace_rows
from kcity.data.dataset import atomic_json,validate_dataset,read_shard
from kcity.experiment import (load_scientific,case_plan,dataset_config,MainWriter,MainExpertCollector,
    RecordingRunner,OnlineRecorder,operational_sources,now,require)
from kcity.data.storage import NEXT_CODEC,CHECKPOINT_MODE


def fingerprint(agent):
    return digest(serializable(agent.training_state()))


def native_gpu_probe(root,spec,resume_child=False):
    root=Path(root)
    agent=KCityPPO(spec['policy'],hparams=spec['ppo'],seed=22,device='cuda')
    env=SumoKCityEnv(background=True)
    runner=KCityRunner(agent,env,run_id='OPS-GPU-RESUME',namespace='contract_check')
    runner.case_cursor=3000000
    if resume_child:
        try:
            runner.load_checkpoint(root/'boundary')
            replay=env.resume_replayed_control_steps
            initial=fingerprint(agent)
            trace=runner.collect(64)
            stats=runner.update()
            atomic_json(root/'resumed.json',dict(initial=initial,trace_sha=digest(trace_rows(trace)),
                final=fingerprint(agent),stats=stats,observation=runner.obs.tolist(),
                transitions=agent.num_timesteps,updates=agent.num_updates,optimizer_steps=agent.num_optimizer_steps,
                replay_steps=replay,replay_counted_as_learning=False))
        finally:env.close()
        return
    root.mkdir(parents=True,exist_ok=False)
    try:
        source=Path('/home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/replicates_v1/seed22/B2/checkpoint-050000')
        meta=json.loads((source/'metadata.json').read_text())
        payload=read_bundle(source,'ppo',meta['config'])
        agent.restore_training_state(payload['agent'])
        # Existing PILOT optimizer history is used only for restoration testing.
        # The explicit held-lane C prefix supplies a400-step environment history;
        # it is a scripted replay fixture, never counted as learner transitions.
        runner.obs,_=env.reset(options=dict(namespace='contract_check',scenario_id='C',case_index=3000000))
        runner.case_cursor=3000001
        prefix_reward=0.
        for _ in range(400):
            runner.obs,reward,term,trunc,_=env.step(np.zeros(2,np.float32))
            require(not term and not trunc,'Held-lane C replay fixture ended early')
            prefix_reward+=reward
        runner.ep_stats=[prefix_reward,400]
        runner.collect(7)
        runner.save_checkpoint(root/'boundary')
        initial=fingerprint(agent)
        boundary=dict(transitions=agent.num_timesteps,updates=agent.num_updates,
            optimizer_steps=agent.num_optimizer_steps,partial_buffer=len(agent.buffer),
            current_episode_history=len(env._action_history),
            pilot_source=str(source),pilot_source_manifest_sha256=file_sha256(source/'SHA256.json'),
            scripted_prefix_steps=400,scripted_prefix_counted_as_learning=False)
        trace=runner.collect(64)
        stats=runner.update()
        control=dict(initial=initial,trace_sha=digest(trace_rows(trace)),final=fingerprint(agent),stats=stats,
            observation=runner.obs.tolist(),transitions=agent.num_timesteps,updates=agent.num_updates,
            optimizer_steps=agent.num_optimizer_steps)
        atomic_json(root/'control.json',control)
    finally:env.close()
    envvars=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1')
    with (root/'child.log').open('w') as log:
        child=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--resume-child',
            '--output',str(root)],cwd=ROOT,env=envvars,stdout=log,stderr=subprocess.STDOUT)
    require(child.returncode==0,'Fresh-process GPU resume failed; inspect child.log')
    resumed=json.loads((root/'resumed.json').read_text())
    equal={k:control[k]==resumed[k] for k in control}
    require(all(equal.values()),'Continuous and resumed GPU branches differ')
    return dict(passed=True,boundary=boundary,exact_comparisons=equal,
        continuation_transitions_per_branch=64,final_transitions_per_branch=control['transitions'],
        final_updates_per_branch=control['updates'],final_optimizer_steps_per_branch=control['optimizer_steps'],
        resumed_in_fresh_process=True,replayed_steps=resumed['replay_steps'],
        replay_counted_as_learning=False,device=torch.cuda.get_device_name(0),hidden_sizes=spec['policy']['hidden_sizes'])


def bc_gpu_probe(root,spec):
    root.mkdir()
    model=KCityBC(spec['policy'],seed=22,device='cuda')
    data=fixture_batch(256)
    def step(agent):
        idx=agent.sampler.integers(0,256,256)
        return agent.train_batch(*[a[idx] for a in data])
    for _ in range(3):step(model)
    model.save_checkpoint(root/'T3',dict(data_id='OPS-SYNTHETIC-BC-NOT-MAIN'))
    expected=[step(model) for _ in range(3)]
    clone=KCityBC(spec['policy'],seed=22,device='cuda')
    clone.load_checkpoint(root/'T3',expected_data_id='OPS-SYNTHETIC-BC-NOT-MAIN')
    actual=[step(clone) for _ in range(3)]
    same=(expected==actual and digest(serializable(model.policy.state_dict()))==digest(serializable(clone.policy.state_dict()))
          and digest(serializable(model.optimizer.state_dict()))==digest(serializable(clone.optimizer.state_dict()))
          and model.sampler.bit_generator.state==clone.sampler.bit_generator.state)
    require(same,'GPU BC resume differs')
    return dict(passed=True,synthetic_labels=True,main_bc_updates=0,validation_optimizer_steps_across_branches=9,
                hidden_sizes=spec['policy']['hidden_sizes'])


def expert_probe(root):
    env=SumoKCityEnv(background=True)
    writer=None
    started=time.monotonic()
    try:
        plan=case_plan(env.contract,'expert',count=80,start=3000000)
        cfg=dataset_config(env,'OPS-EXPERT-NOT-MAIN',plan,'debug')
        writer=MainWriter(root,cfg,shard_rows=512)
        collector=MainExpertCollector(env,KCityRuleExpert(),writer)
        calls=[0]
        def stop():
            calls[0]+=1
            return calls[0]>17
        partial=collector.collect_main(2048,stop)
        require(partial['phase']=='STOPPED','Expert STOP did not pause')
        before=writer.count
        writer.close();writer=None;env.close()
        env=SumoKCityEnv(background=True)
        writer=MainWriter(root,cfg,resume=True,shard_rows=512)
        collector=MainExpertCollector(env,KCityRuleExpert(),writer)
        replay=getattr(env,'resume_replayed_control_steps',0)
        result=collector.collect_main(2048)
        quality=validate_dataset(root)
        require(result['phase']=='COMPLETE' and collector.metrics is None,'Expert target must finish its Episode')
        require(not json.loads((root/'RELEASE.json').read_text())['eligible_for_research_training'],'Probe leaked into main eligibility')
        return dict(passed=True,paused_at=before,replayed_steps=replay,collection=result,
            wall_s=time.monotonic()-started,data_id=quality['data_id'],quality_passed=quality['passed'],
            split_counts=quality['split_counts'],shard_rows=512,main_expert_transitions=0)
    finally:
        if writer is not None:writer.close()
        env.close()


def recorded_gpu_probe(root,spec):
    root.mkdir()
    plan=None;cfg=None
    def create(resume=False):
        nonlocal plan,cfg
        env=SumoKCityEnv(background=True)
        agent=KCityPPO(spec['policy'],hparams=spec['ppo'],seed=22,device='cuda')
        runner=RecordingRunner(agent,env,run_id='OPS-ATOMIC-PPO',namespace='contract_check')
        runner.case_cursor=3000000
        if cfg is None:
            plan=case_plan(env.contract,'probe',count=60,start=3000000)
            cfg=dataset_config(env,'OPS-ATOMIC-PPO-DATA',plan,'debug','B2',22)
        writer=MainWriter(root/'dataset',cfg,resume=resume,shard_rows=2048)
        recorder=OnlineRecorder(runner,writer,'B2',22)
        runner.recorder=recorder
        return env,agent,runner,writer,recorder
    env,agent,runner,writer,recorder=create()
    try:
        for _ in range(2055):
            runner.step()
            if len(agent.buffer)==2048:
                runner.update();recorder.commit()
        # This is exactly the CLI's safe STOP boundary: no partial-buffer update.
        recorder.commit()
        before=fingerprint(agent)
        boundary=dict(transitions=agent.num_timesteps,updates=agent.num_updates,partial_buffer=len(agent.buffer))
        expected=runner.collect(64)
        runner.update()
        expected_final=fingerprint(agent)
        expected_trace=digest(trace_rows(expected))
    finally:writer.close();env.close()
    env,agent,runner,writer,recorder=create(resume=True)
    try:
        require(before==fingerprint(agent),'Atomic data/learner resume mismatch')
        actual=runner.collect(64)
        runner.update();recorder.commit()
        require(expected_trace==digest(trace_rows(actual)) and expected_final==fingerprint(agent),
                'Recorded resumed continuation differs')
        report=validate_dataset(writer.root)
        require(report['unique_transitions']==agent.num_timesteps,'Data/learner transition count mismatch')
        return dict(passed=True,boundary=boundary,transitions=agent.num_timesteps,
            rollout_updates=agent.num_updates,optimizer_steps=agent.num_optimizer_steps,
            data_unique_transitions=report['unique_transitions'],quality_passed=report['passed'],
            completed_episodes=len(report['episodes']),atomic_checkpoint_within_shard=False,
            atomic_checkpoint_reference=True,retained_checkpoint_count=report['retained_learner_checkpoints'],
            storage_codec=NEXT_CODEC,checkpoint_mode=CHECKPOINT_MODE,
            partial_buffer_preserved=True,main_ppo_transitions=0)
    finally:writer.close();env.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--resume-child',action='store_true')
    args=parser.parse_args()
    torch.set_num_threads(1)
    require(torch.cuda.is_available(),'GPU operational validation requires CUDA')
    spec=load_scientific()
    if args.resume_child:
        native_gpu_probe(args.output,spec,True)
        return
    args.output.mkdir(parents=True,exist_ok=False)
    result=dict(started_at=now(),purpose='OPERATIONAL_VALIDATION_NOT_MAIN',remote_uploads_enabled=False,
        scientific_sha256=file_sha256(ROOT/'configs/kcity/main_v1/FROZEN_PROTOCOL.json'),
        operational_sources=operational_sources(),main_training_started=False,
        main_expert_transitions=0,main_ppo_transitions=0)
    for name,fn in [('bc_gpu',lambda:bc_gpu_probe(args.output/'bc_gpu',spec)),
                    ('gpu_resume',lambda:native_gpu_probe(args.output/'gpu_resume',spec)),
                    ('expert_writer',lambda:expert_probe(args.output/'expert_dataset')),
                    ('recorded_gpu',lambda:recorded_gpu_probe(args.output/'recorded_gpu',spec))]:
        atomic_json(args.output/'STATUS.json',dict(phase='RUNNING',active_check=name,updated_at=now(),remote_uploads_enabled=False))
        try:
            result[name]=fn()
        except BaseException as error:
            atomic_json(args.output/'STATUS.json',dict(phase='FAILED',active_check=name,updated_at=now(),
                error=type(error).__name__+': '+str(error),remote_uploads_enabled=False,main_training_started=False))
            raise
        atomic_json(args.output/'PARTIAL_RESULTS.json',result)
    result.update(passed=True,ended_at=now(),runtime=runtime_contract(),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    atomic_json(args.output/'SUMMARY.json',result)
    atomic_json(args.output/'STATUS.json',dict(phase='COMPLETE',passed=True,updated_at=now(),remote_uploads_enabled=False))
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
