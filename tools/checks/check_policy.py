"""KC-04 bounded synthetic BC/transfer + native SUMO partial-rollout resume checks."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from kcity.policy.policy import DEFAULT_POLICY,KCityPolicy
from kcity.training import DEFAULT_PPO,KCityBC,KCityPPO,KCityRunner,runtime_contract
from kcity.env.env import SumoKCityEnv
from kcity.env.config import digest,file_sha256


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


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--artifacts',required=True,type=Path,help='New external folder for fixture checkpoints/traces')
    args=ap.parse_args();out=args.output.resolve();artifacts=args.artifacts.resolve()
    if out.exists() or artifacts.exists():raise FileExistsError('Use new output and artifact paths')
    out.mkdir(parents=True);artifacts.mkdir(parents=True)
    (artifacts/'README.md').write_text('# KC-04 validation fixtures\n\nSynthetic-label/small-network validation only. Not research policies or expert data.\n')
    started=datetime.now().astimezone().isoformat()
    preset=json.loads((ROOT/'configs/kcity/v1/learning.json').read_text())
    assert preset['policy']==DEFAULT_POLICY and preset['ppo']==DEFAULT_PPO
    assert not preset['training_enabled'] and not preset['research_settings_frozen']
    production=KCityBC()
    parameter_counts=dict(total=sum(p.numel() for p in production.policy.parameters()),
        bc_trainable=sum(p.numel() for p in production.policy.parameters() if p.requires_grad))
    cfg=dict(DEFAULT_POLICY,hidden_sizes=[16,16]);hp=dict(DEFAULT_PPO,n_steps=4,n_epochs=1,minibatch_size=4)
    bc=KCityBC(cfg);batch=fixture_batch()
    fixed={k:v.clone() for k,v in bc.policy.state_dict().items() if k=='log_std' or k.startswith('v_head.')}
    bc_losses=[bc.train_batch(*batch) for _ in range(2)]
    bc.save_checkpoint(artifacts/'bc_step2',dict(data_id='SYNTHETIC-KC04-fixture',source_kind='synthetic',next_batch=2))
    clone=KCityBC(cfg);clone.load_checkpoint(artifacts/'bc_step2',expected_data_id='SYNTHETIC-KC04-fixture')
    ids=bc.sampler.integers(0,32,16);ids2=clone.sampler.integers(0,32,16)
    batch_next=tuple(x[ids] for x in batch)
    control_loss=bc.train_batch(*batch_next);resumed_loss=clone.train_batch(*batch_next)
    bc_resume_equal=(np.array_equal(ids,ids2) and control_loss==resumed_loss and
        digest(serializable(bc.policy.state_dict()))==digest(serializable(clone.policy.state_dict())) and
        digest(serializable(bc.optimizer.state_dict()))==digest(serializable(clone.optimizer.state_dict())))
    bc.save_checkpoint(artifacts/'bc_source_step3',dict(data_id='SYNTHETIC-KC04-fixture',source_kind='synthetic',next_batch=3))
    source_sha=file_sha256(artifacts/'bc_source_step3/SHA256.json')
    b2=KCityPPO(cfg,hparams=hp);b3=KCityPPO(cfg,hparams=hp);b3.initialize_bc(bc.policy,source_sha)
    transfer_error=max(float(np.max(np.abs(bc.policy.predict(o)-b3.predict(o)))) for o in batch[0])
    head_equal=all(torch.equal(v,b3.policy.state_dict()[k]) for k,v in b2.policy.state_dict().items()
                   if k=='log_std' or k.startswith('v_head.'))
    frozen_equal=all(torch.equal(v,bc.policy.state_dict()[k]) for k,v in fixed.items())
    obs=torch.tensor(batch[0]);masks=torch.tensor(batch[2]);sample,lp,_=b3.policy.sample(obs,masks,generator=b3.sampling_generator)
    lp2,_,_=b3.policy.evaluate_actions(obs,sample,masks);logprob_error=float((lp-lp2).abs().max())

    env=SumoKCityEnv(background=True,artifact_dir=artifacts/'sumo_control')
    replay_env=SumoKCityEnv(background=True,artifact_dir=artifacts/'sumo_resumed')
    runner=KCityRunner(b3,env,run_id='KC04-RESUME-SYNTHETIC-fixture',namespace='contract_check')
    runner.PATTERN=('C',)  # Explicit debug variant, never the research case schedule.
    resumed_agent=KCityPPO(cfg,hparams=hp)
    resumed=KCityRunner(resumed_agent,replay_env,run_id=runner.run_id,namespace='contract_check')
    resumed.PATTERN=('C',)
    try:
        runner.collect(4);runner.update();runner.collect(2)
        runner.save_checkpoint(artifacts/'ppo_partial_T6_U1')
        control=runner.collect(12)
        pre_update=digest(serializable(runner.agent.training_state()))
        control_stats=runner.update()
        then=time.monotonic();resumed.load_checkpoint(artifacts/'ppo_partial_T6_U1');restore_wall=time.monotonic()-then
        restored_pending_rows=len(resumed.agent.buffer)
        actual=resumed.collect(12)
        pending_equal=pre_update==digest(serializable(resumed.agent.training_state()))
        resumed_stats=resumed.update()
        full_equal=digest(serializable(runner.agent.training_state()))==digest(serializable(resumed.agent.training_state()))
        traces_equal=digest(trace_rows(control))==digest(trace_rows(actual))
        final_obs_equal=np.array_equal(runner.obs,resumed.obs)
        runner.save_checkpoint(artifacts/'ppo_control_T18_U2')
        resumed.save_checkpoint(artifacts/'ppo_resumed_T18_U2')
        for name,trace in [('control',control),('resumed',actual)]:
            with (artifacts/(name+'.jsonl')).open('w') as stream:
                for row in trace_rows(trace):stream.write(json.dumps(row,allow_nan=False)+'\n')
        continuation=dict(checkpoint_transitions=6,checkpoint_updates=1,restored_pending_rows=restored_pending_rows,
            suffix_decisions_per_branch=12,trace_equal=traces_equal,pending_training_state_equal=pending_equal,
            final_training_state_equal=full_equal,final_observation_equal=bool(final_obs_equal),
            update_metrics_equal=control_stats==resumed_stats,restored_control_steps=replay_env.resume_replayed_control_steps,
            restore_wall_s=restore_wall,final_transitions_per_branch=b3.num_timesteps,
            final_updates_per_branch=b3.num_updates,final_optimizer_steps_per_branch=b3.num_optimizer_steps)
    finally:env.close();replay_env.close()
    result=dict(started_at=started,ended_at=datetime.now().astimezone().isoformat(),runtime=runtime_contract(),
        source_SHA256={f:file_sha256(ROOT/f) for f in ['tools/checks/check_policy.py','tests/test_kcity_policy.py']},
        preset_sha256=file_sha256(ROOT/'configs/kcity/v1/learning.json'),production_hidden_sizes=[256,256],
        parameter_counts=parameter_counts,fixture_hidden_sizes=[16,16],fixture_ppo_hparams=hp,
        bc_probe=dict(initial_losses=bc_losses,continuation_loss=control_loss,resume_equal=bc_resume_equal,
            value_head_and_std_unchanged=frozen_equal,executed_optimizer_steps_across_branches=4),
        transfer=dict(max_deterministic_action_error=transfer_error,critic_head_and_std_match_b2=head_equal,
            sampled_vs_recomputed_logprob_error=logprob_error,bc_source_manifest_sha256=source_sha),
        continuation=continuation,artifacts=str(artifacts),
        validation_ppo_optimizer_steps_across_branches=9,validation_collected_transitions_across_branches=30,
        replay_transitions_counted_as_new_learning=False,research_training_started=False,research_training_transitions=0,
        expert_dataset_transitions=0,final_panel_cases_executed=0,gpu_validation_performed=False,training_ready=False)
    result['passed']=(parameter_counts==dict(total=86022,bc_trainable=85764) and bc_resume_equal and frozen_equal and
        transfer_error==0 and head_equal and logprob_error==0 and all(continuation[k] for k in
        ['trace_equal','pending_training_state_equal','final_training_state_equal','final_observation_equal','update_metrics_equal']))
    (out/'SUMMARY.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['runtime','source_SHA256','bc_probe']},indent=2))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
