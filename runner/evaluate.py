"""Deterministic evaluation on the fixed dev/final case panels.

    python evaluate.py --policy expert --panel dev --output runs/eval/expert_dev
    python evaluate.py --policy runs/B3_seed11/transitions/checkpoints/T001000000-... --panel final \
        --demand 1.0 1.5 2.0 --output runs/eval/B3_seed11_final

--policy is `expert` or a BC/PPO learner bundle directory (contains metadata.json/training.pt).
Writes EPISODES.json and SUMMARY.json per demand and prints collision/completion rates.
The final panel is for the fixed main policies only; never use it to choose models or settings.
"""
import sys
from pathlib import Path

import argparse
import json
import math

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from training.experiment import load_experiment
from data.dataset import atomic_json
from env.config import ROOT
from env.env import SumoKCityEnv
from evaluation.evaluate import evaluate_cases
from policy.rule_expert import KCityRuleExpert
from training.runs import now
from policy.checkpoint import load_policy


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [max(0., centre - half), min(1., centre + half)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--policy', required=True, help="'expert' or a learner bundle directory")
    parser.add_argument('--panel', choices=['dev', 'final'], default='dev')
    parser.add_argument('--demand', type=float, nargs='+', help='demand multipliers to keep (default: all in panel)')
    parser.add_argument('--limit', type=int, help='evaluate only the first N cases per demand (smoke test)')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    args = parser.parse_args()
    torch.set_num_threads(1)
    spec = load_experiment()
    if args.policy == 'expert':
        policy, source = KCityRuleExpert(), dict(kind='expert')
    else:
        policy, meta = load_policy(args.policy, args.device)
        source = dict(kind=meta['kind'], bundle=str(Path(args.policy).resolve()), config=meta['config'])
    cases = json.loads((ROOT / spec['case_panels'][args.panel]['path']).read_text())['cases']
    demands = sorted({c['demand_multiplier'] for c in cases}) if args.demand is None else args.demand
    args.output.mkdir(parents=True, exist_ok=True)
    env = SumoKCityEnv(background=True)
    rows = []
    try:
        for demand in demands:
            panel = [c for c in cases if math.isclose(c['demand_multiplier'], demand)][:args.limit]
            if not panel:
                parser.error(f'No {args.panel} cases at demand {demand}')
            records, summary = evaluate_cases(policy, env, dict(cases=panel))
            folder = args.output / f'demand_{demand:g}'
            folder.mkdir(exist_ok=True)
            atomic_json(folder / 'EPISODES.json', records)
            summary.update(collision_rate_wilson95=wilson(summary['n_collision'], summary['n_valid']),
                           completion_rate_wilson95=wilson(summary['n_completed'], summary['n_valid']))
            atomic_json(folder / 'SUMMARY.json', dict(panel=args.panel, demand_multiplier=demand, policy=source,
                                                      evaluated_at=now(), aggregate=summary))
            rows.append((demand, summary))
    finally:
        env.close()
    print(f"{'demand':>6} {'n':>4} {'collision':>10} {'completion':>11} {'compliant':>10} {'mean_s(done)':>13}")
    for demand, s in rows:
        rate = lambda v: '-' if v is None else f'{100 * v:.1f}%'
        mean = s['mean_elapsed_completed']
        print(f"{demand:>6g} {s['n_valid']:>4} {rate(s['collision_rate']):>10} {rate(s['completion_rate']):>11} "
              f"{rate(s['compliant_completion_rate']):>10} {'-' if mean is None else f'{mean:.1f}':>13}")


if __name__ == '__main__':
    main()
