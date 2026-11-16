"""Collect expert (B0) driving data into a K-CITY dataset (KC-DATA-v1 shards).

    python collect.py --output runs/expert                 # experiment budget (1M), finishes the last Episode
    python collect.py --output runs/expert --target 5000   # small check run
    touch runs/expert/STOP; python collect.py --output runs/expert --resume

Cases follow the A/A/A/B/B/B/C/C/C/C pattern; every 5th case of a scenario is expert_val.
"""
import sys
from pathlib import Path

import argparse
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from training.experiment import experiment_sha256, load_experiment, training_config
from data.collector import ExpertCollector, case_plan, dataset_config
from data.dataset import ShardWriter, atomic_json, validate_dataset
from env.env import SumoKCityEnv
from policy.rule_expert import KCityRuleExpert
from training.runs import Owner, install_signals, now, stopped


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', required=True, type=Path, help='run directory (dataset goes to <output>/dataset)')
    parser.add_argument('--target', type=int, help='absolute transition target (default: experiment budget)')
    parser.add_argument('--shard-rows', type=int, default=512)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    spec = load_experiment()
    target = args.target or spec['budgets']['expert_valid_transitions_min']
    install_signals()
    owner = Owner(args.output, training_config(spec, 'main_expert_pool', shard_rows=args.shard_rows), args.resume)
    env = SumoKCityEnv(background=True)
    writer = None
    try:
        plan = case_plan(env.contract, 'expert')
        data = dataset_config(env, args.output.name, plan, 'expert_pool', experiment_sha256=experiment_sha256(spec))
        writer = ShardWriter(args.output / 'dataset', data, resume=args.resume, shard_rows=args.shard_rows)
        result = ExpertCollector(env, KCityRuleExpert(), writer).collect(target, lambda: stopped(args.output))
        quality = validate_dataset(writer.root)
        atomic_json(args.output / 'QUALITY.json', quality)
        atomic_json(args.output / 'STATUS.json', dict(result, updated_at=now(), data_id=quality['data_id']))
        print(json.dumps(dict(result, data_id=quality['data_id'], split_counts=quality['split_counts']), indent=2))
    finally:
        if writer is not None:
            writer.close()
        env.close()
        owner.close()


if __name__ == '__main__':
    main()
