"""Behavior cloning (B1) from the expert pool.

    # 1) fix the shared train/val views (successful Episodes only, sampled once with seed 20261115)
    python runner/train_bc.py views --pool runs/expert --output runs/bc_views
    # 2) train one seed (10k updates, validation every 500, best val loss kept)
    python runner/train_bc.py train --views runs/bc_views --seed 11 --output runs/bc_seed11

STOP: touch <output>/STOP, then rerun the same command with --resume.
"""
import sys
from pathlib import Path

import argparse
import json

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.training.experiment import load_experiment
from kcity.training.runs import install_signals
from kcity.training.bc import build_views, run_bc


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    views = sub.add_parser('views', help='build fixed BC train/val views from an expert pool')
    views.add_argument('--pool', required=True, type=Path, help='expert pool (collect.py --output) or one dataset')
    views.add_argument('--workers', type=int, default=1, help='parallel validation of pool parts')
    views.add_argument('--revalidate', action='store_true', help='validate parts again even if worker reports match')
    views.add_argument('--output', required=True, type=Path)
    train = sub.add_parser('train', help='train one BC seed')
    train.add_argument('--views', required=True, type=Path)
    train.add_argument('--seed', required=True, type=int)
    train.add_argument('--output', required=True, type=Path)
    train.add_argument('--device', choices=['cpu', 'cuda'], default='cuda' if torch.cuda.is_available() else 'cpu')
    train.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    spec = load_experiment()
    if args.command == 'views':
        print(json.dumps(build_views(args.pool, args.output, spec, workers=args.workers, revalidate=args.revalidate), indent=2))
        return
    torch.set_num_threads(1)
    install_signals()
    run_bc(args.output, args.views, args.seed, spec, args.device, args.resume)


if __name__ == '__main__':
    main()
