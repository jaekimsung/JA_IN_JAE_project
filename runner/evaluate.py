"""Deterministic evaluation on the fixed dev/final case panels.

    python runner/evaluate.py --policy expert --panel dev --output runs/eval/expert_dev
    python runner/evaluate.py --policy runs/B3_seed11/transitions/checkpoints/T000300000-... --panel final \
        --demand 1.0 1.5 2.0 --output runs/eval/B3_seed11_final

--policy is `expert` or a BC/RL learner bundle directory (contains metadata.json/training.pt).
Writes EPISODES.json and SUMMARY.json per demand and prints collision/completion rates, HV exposure
(HV on the map, HV within 50 m of the AV, leader presence), stopping indicators and the outcome of each
problem situation (signal chain, lane drop, unsignalized junctions; kcity/evaluation/situations.py).
The final panel is for the fixed main policies only; never use it to choose models or settings.
"""
import sys
from pathlib import Path

import argparse
import json
import math

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.training.experiment import load_experiment
from kcity.data.dataset import atomic_json
from kcity.env.config import ROOT
from kcity.env.env import SumoKCityEnv
from kcity.evaluation.evaluate import evaluate_cases
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.training.runs import now
from kcity.policy.checkpoint import load_policy


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
    parser.add_argument('--experiment', type=Path, default=Path('configs/kcity/experiment.json'))
    args = parser.parse_args()
    torch.set_num_threads(1)
    spec = load_experiment(args.experiment)
    env = SumoKCityEnv(protocol=ROOT / spec['base_contract']['path'], background=True)
    if args.policy == 'expert':
        policy, source = KCityRuleExpert.from_protocol(env.contract['protocol']), dict(kind='expert')
    else:
        policy, meta = load_policy(args.policy, args.device)
        source = dict(kind=meta['kind'], bundle=str(Path(args.policy).resolve()), config=meta['config'])
    cases = json.loads((ROOT / spec['case_panels'][args.panel]['path']).read_text())['cases']
    demands = sorted({c['demand_multiplier'] for c in cases}) if args.demand is None else args.demand
    args.output.mkdir(parents=True, exist_ok=True)
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
    rate = lambda v: '-' if v is None else f'{100 * v:.1f}%'
    num = lambda v, f='.1f': '-' if v is None else format(v, f)
    print(f"{'demand':>6} {'n':>4} {'collision':>10} {'completion':>11} {'compliant':>10} {'mean_s(done)':>13}")
    for demand, s in rows:
        print(f"{demand:>6g} {s['n_valid']:>4} {rate(s['collision_rate']):>10} {rate(s['completion_rate']):>11} "
              f"{rate(s['compliant_completion_rate']):>10} {num(s['mean_elapsed_completed']):>13}")
    print()
    print(f"{'demand':>6} {'HV@start':>9} {'HV(avg)':>8} {'start<10':>9} {'near50m':>8} {'near>0':>7} "
          f"{'leader':>7} {'stop_s':>7} {'stop_max':>9} {'deadline':>9}")
    for demand, s in rows:
        e, st = s['exposure'], s['stops']
        print(f"{demand:>6g} {num(e['HV_start_mean']):>9} {num(e['HV_time_weighted_mean']):>8} "
              f"{e['n_HV_start_below_10']:>9} {num(e['near_HV_50m_mean'], '.2f'):>8} {rate(e['near_HV_50m_presence_mean']):>7} "
              f"{rate(e['leader_present_fraction_mean']):>7} {num(st['standstill_s_mean']):>7} {num(st['standstill_s_max']):>9} "
              f"{st['n_deadline']:>9}")
    print()
    print(f"{'demand':>6} {'situation':<14} {'exposed':>8} {'failed':>7} {'fail%':>7}  detail")
    for demand, s in rows:
        for name, item in s['situations'].items():
            if name == 'other':
                detail = ''
            elif name == 'signal_chain':
                detail = (f"crossings {item['crossings']}, red {item['red_entries']}, yellow {rate(item['yellow_entry_fraction'])}, "
                          f"wait {num(item['wait_s_mean'])}s, box stop {num(item['box_stop_s_mean'])}s")
            elif name == 'lane_drop':
                detail = (f"done {rate(item['done_rate'])} at {num(item['position_m_mean'])}m, requests {num(item['requests_mean'])}, "
                          f"rejected {num(item['rejected_mean'])}, target-lane HV {num(item['target_lane_hv_mean'], '.2f')}")
            else:
                detail = (f"passes {item['passes']}, cross traffic {rate(item['cross_traffic_fraction'])}, "
                          f"min distance {num(item['min_distance_m'])}m, collisions {item['collisions']}, "
                          f"yield violations {item['yield_violations']}")
            print(f"{demand:>6g} {name:<14} {item.get('n_exposed', '-'):>8} {item['n_failed_here']:>7} "
                  f"{rate(item.get('failure_rate')):>7}  {detail}")


if __name__ == '__main__':
    main()
