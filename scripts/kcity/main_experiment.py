"""Frozen K-CITY main collector / BC / PPO CLI. No training on import.

--check-only is safe before a launch record exists. Actual main work requires
--launch-record. This tool intentionally has no upload or Drive integration.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import torch
from utils.kcity_main import (FROZEN, Owner, MainWriter, MainExpertCollector, case_plan,
    dataset_config, load_scientific, require_launch, operational_sources, install_signals,
    stopped, training_config, run_bc, run_ppo, build_views, now)
from env.kcity_env import SumoKCityEnv
from experts.kcity_rule_expert import KCityRuleExpert
from utils.kcity_data import atomic_json, validate_dataset


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['collect','views','bc','ppo'])
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--launch-record',type=Path)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--seed',choices=[11,22,33],type=int,default=11)
    parser.add_argument('--method',choices=['B2','B3'],default='B2')
    parser.add_argument('--pool',type=Path)
    parser.add_argument('--views',type=Path)
    parser.add_argument('--bc-run',type=Path)
    parser.add_argument('--device',choices=['cpu','cuda'],default='cuda')
    parser.add_argument('--shard-rows',type=int,default=512)
    args=parser.parse_args()
    torch.set_num_threads(1)
    install_signals()
    spec=load_scientific()
    if args.check_only:
        print(json.dumps(dict(stage=args.stage,scientific_protocol=spec['protocol_id'],
            operational_sources=operational_sources(),output=str(args.output.resolve()),
            intended_seed=args.seed,intended_method=args.method,budgets=spec['budgets'],
            learner_executed=False,new_transitions=0,remote_uploads_enabled=False),indent=2))
        return
    require_launch(args.launch_record,args.stage,args.output)
    if args.device=='cuda' and args.stage in ['bc','ppo'] and not torch.cuda.is_available():
        parser.error('CUDA is unavailable')
    if args.stage=='collect':
        if args.shard_rows!=512:
            parser.error('Use the measured operational expert shard size512')
        cfg=training_config('main_expert_pool',shard_rows=args.shard_rows)
        owner=Owner(args.output,cfg,args.resume)
        env=SumoKCityEnv(background=True)
        writer=None
        try:
            plan=case_plan(env.contract,'expert')
            data=dataset_config(env,args.output.name,plan,'expert_pool')
            writer=MainWriter(args.output/'dataset',data,resume=args.resume,shard_rows=args.shard_rows)
            collector=MainExpertCollector(env,KCityRuleExpert(),writer)
            result=collector.collect_main(spec['budgets']['expert_valid_transitions_min'],lambda:stopped(args.output))
            quality=validate_dataset(writer.root)
            atomic_json(args.output/'QUALITY.json',quality)
            atomic_json(args.output/'STATUS.json',dict(result,updated_at=now(),data_id=quality['data_id'],
                main_training_started=False,remote_uploads_enabled=False))
        finally:
            if writer is not None:writer.close()
            env.close()
            owner.close()
    elif args.stage=='views':
        if not args.pool:parser.error('--pool is required')
        print(json.dumps(build_views(args.pool,args.output,spec),indent=2))
    elif args.stage=='bc':
        if not args.views:parser.error('--views is required')
        run_bc(args.output,args.views,args.seed,spec,args.device,args.resume)
    else:
        run_ppo(args.output,args.method,args.seed,spec,args.device,args.bc_run,args.resume)


if __name__=='__main__':
    main()
