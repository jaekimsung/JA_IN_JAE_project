"""PPO training: B2 (fresh) or B3 (initialized from the same-seed BC best actor).

    python runner/train_ppo.py --method B2 --seed 11 --output runs/B2_seed11
    python runner/train_ppo.py --method B3 --seed 11 --bc-run runs/bc_seed11 --output runs/B3_seed11

Trains exactly the experiment budget (1M transitions), evaluates the dev panel every 50k,
and records every transition in the dataset format under <output>/transitions.
STOP: touch <output>/STOP, then rerun the same command with --resume.
"""
import sys
from pathlib import Path

import argparse

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.training.experiment import load_experiment
from kcity.training.runs import install_signals
from kcity.training.ppo import run_ppo


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--method', choices=['B2', 'B3'], required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--bc-run', type=Path, help='completed BC run of the same seed (B3 only)')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cuda' if torch.cuda.is_available() else 'cpu')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.method == 'B3' and args.bc_run is None:
        parser.error('B3 requires --bc-run')
    torch.set_num_threads(1)
    install_signals()
    run_ppo(args.output, args.method, args.seed, load_experiment(), args.device, args.bc_run, args.resume)


if __name__ == '__main__':
    main()
