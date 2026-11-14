"""KC-05 six-case small expert dataset; not a research pool or learning launch."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from env.kcity_env import SumoKCityEnv
from experts.kcity_rule_expert import KCityRuleExpert
from utils.kcity_collector import build_config,ExpertCollector
from utils.kcity_data import ShardWriter,atomic_json,validate_dataset


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',required=True,type=Path)
    ap.add_argument('--run-uid',required=True)
    ap.add_argument('--max-transitions',type=int,default=4000,help='Absolute committed-transition cap,up to10000')
    ap.add_argument('--shard-rows',type=int,default=64)
    ap.add_argument('--resume',action='store_true')
    ap.add_argument('--no-background',action='store_true',help='Explicit empty-road debug variant')
    ap.add_argument('--check-only',action='store_true')
    args=ap.parse_args()
    if not 1<=args.max_transitions<=10000:ap.error('KC-05 cap must be1..10000')
    env=SumoKCityEnv(background=not args.no_background,debug_warmup_s=0 if args.no_background else None)
    expert=KCityRuleExpert();config=build_config(env,expert,args.run_uid)
    if args.check_only:
        print(json.dumps(dict(planned_episodes=len(config['plan']),teacher=config['teacher'],source_stage='debug',
            schema_id=config['schema_id'],training_ready=False),indent=2));env.close();return
    started=datetime.now().astimezone().isoformat();clock=time.monotonic();writer=None
    try:
        writer=ShardWriter(args.output,config,resume=args.resume,shard_rows=args.shard_rows)
        atomic_json(args.output/'COLLECTION_STATUS.json',dict(phase='RUNNING',started_at=started,
            attempt_uid=writer.attempt_uid,target=args.max_transitions,committed_transitions=writer.count))
        collector=ExpertCollector(env,expert,writer);result=collector.collect_until(args.max_transitions)
        quality=validate_dataset(args.output)
        summary=dict(started_at=started,ended_at=datetime.now().astimezone().isoformat(),
            wall_s=time.monotonic()-clock,attempt_uid=writer.attempt_uid,collection=result,quality=quality,
            source_stage='debug',expert_pool_transitions_for_10M=0,learner_executed=False,optimizer_steps=0,
            research_training_started=False,training_ready=False)
        atomic_json(args.output/'COLLECTION_SUMMARY.json',summary)
        atomic_json(args.output/'COLLECTION_STATUS.json',dict(phase='COMPLETE' if result['completed_plan'] else 'BUDGET_PAUSED',
            ended_at=summary['ended_at'],attempt_uid=writer.attempt_uid,**result))
        print(json.dumps(dict(collection=result,quality_passed=quality['passed'],data_id=quality['data_id'],
            committed_shards=quality['committed_shards'],wall_s=summary['wall_s'],training_ready=False),indent=2))
    except BaseException as error:
        if writer is not None:
            atomic_json(args.output/'COLLECTION_STATUS.json',dict(phase='FAILED',attempt_uid=writer.attempt_uid,
                error_type=type(error).__name__,error=str(error),committed_transitions=writer.count,
                uncommitted_transitions=writer.pending,partial_counted=False,training_ready=False))
        raise
    finally:
        if writer is not None:writer.close()
        env.close()


if __name__=='__main__':main()
