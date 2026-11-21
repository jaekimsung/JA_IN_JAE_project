"""Online RL training: B2 (online-only SAC) or B3 (RLPD: SAC + expert prior data).

    python runner/train_rl.py --method B2 --seed 11 --output runs/B2_seed11
    python runner/train_rl.py --method B3 --seed 11 --prior runs/expert --output runs/B3_seed11

Trains the experiment budget, evaluates the dev panel at fixed intervals, and records every transition in the
dataset format under <output>/transitions. STOP: touch <output>/STOP, then rerun the same command with --resume.
"""
import sys
from pathlib import Path

import argparse
import math

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.training.experiment import load_experiment
from kcity.training.rl import run_rl
from kcity.training.runs import install_signals


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--method', choices=['B2', 'B3'], required=True)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--prior', type=Path, help='expert pool used as prior data (B3 only)')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cuda' if torch.cuda.is_available() else 'cpu')
    parser.add_argument('--threads', type=int, default=1, help='torch CPU threads')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--report-every', type=float, default=30., metavar='SECONDS',
                        help='terminal progress interval in seconds (default: 30; does not change file/checkpoint cadence)')
    parser.add_argument('--experiment', type=Path, default=Path('configs/kcity/experiment.json'))
    args = parser.parse_args()
    if not math.isfinite(args.report_every) or args.report_every <= 0:
        parser.error('--report-every must be positive and finite')
    if (args.method == 'B3') != (args.prior is not None):
        parser.error('--prior is required for B3 and not allowed for B2')
    torch.set_num_threads(args.threads)
    install_signals()
    run_rl(args.output, args.method, args.seed, load_experiment(args.experiment.resolve()), args.device,
           args.prior, args.resume, report_every=args.report_every)


if __name__ == '__main__':
    main()
