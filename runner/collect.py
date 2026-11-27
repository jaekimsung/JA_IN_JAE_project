"""Collect driving data into a pool with parallel workers: the B0 expert, or a fixed learned policy.

    python runner/collect.py --output runs/expert --workers 8            # 8 SUMO workers on this machine
    python runner/collect.py --output runs/expert --workers 8 --resume   # continue after STOP/crash
    python runner/collect.py --output runs/expert --target 5000          # small single-worker check

    # several machines: run one part per machine, copy part-XX/ into one folder, then finalize
    python runner/collect.py --output runs/expert --part 3 --parts 8
    python runner/collect.py --output runs/expert --finalize

    # fixed learned policy (BC/RL bundle) on the separate `archive` case namespace, deterministic actions
    python runner/collect.py --output runs/archive_B3_seed11 --workers 8         --policy runs/B3_seed11/transitions/checkpoints/T000300000-...

The case plan (A/A/A/B/B/B/C/C/C/C, every 5th case of a scenario is expert_val) is split into
whole 10-case cycles, round robin over parts, so each case keeps its traffic seeds and split.
Each part collects ceil(target / parts) transitions and finishes its current Episode. Default target:
expert 4M (expert_valid_transitions_min), learned policy 700k (archive_per_budget_end_policy).
`touch <output>/STOP` stops every worker cleanly; rerun the same command with --resume.
"""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from kcity.data.collector import PolicyCollector, dataset_config
from kcity.data.dataset import ShardWriter, atomic_json, validate_dataset
from kcity.data.pool import part_dir, write_pool
from kcity.data.plans import GeneratedCasePlan
from kcity.env.config import ROOT, file_sha256
from kcity.env.env import SumoKCityEnv
from kcity.evaluation.metrics import policy_weights_sha256
from kcity.policy.checkpoint import load_policy
from kcity.policy.rule_expert import KCityRuleExpert
from kcity.training.experiment import experiment_sha256, is_pilot, load_experiment, training_config
from kcity.training.runs import Owner, install_signals, now, read, stopped


def resolve_policy(args, protocol):
    """(actor, case-plan kind, source stage, fixed-policy identity or None)."""
    if args.policy == 'expert':
        return KCityRuleExpert.from_protocol(protocol), 'expert', 'expert_pool', None
    import torch
    torch.set_num_threads(1)
    bundle = Path(args.policy).resolve()
    policy, meta = load_policy(bundle)
    method = args.policy_method
    if method is None:
        method = meta['config']['method']  # B1 (BC), B2 (online SAC) or B3 (RLPD)
    identity = dict(method=method, seed=meta['config']['seed'], version='KC-ARCHIVE-v1',
                    policy_sha256=policy_weights_sha256(policy), bundle=str(bundle),
                    bundle_manifest_sha256=file_sha256(bundle / 'SHA256.json'))
    return policy, 'archive', 'archive', identity


def collect_part(args, spec, target):
    """One worker: its own SUMO, ShardWriter and resume state under <output>/part-XX."""
    root = part_dir(args.output, args.part)
    env = SumoKCityEnv(protocol=ROOT / spec['base_contract']['path'], background=True)
    actor, kind, stage, fixed = resolve_policy(args, env.contract['protocol'])
    if is_pilot(spec):
        stage = 'pilot_' + stage
    config = training_config(spec, stage + '_part', part=args.part, parts=args.parts, target=target,
                             shard_rows=args.shard_rows, policy=fixed)
    owner = Owner(root, config, args.resume)
    writer = None
    try:
        plan = GeneratedCasePlan.for_budget(env.contract, kind, args.target, args.part, args.parts, case_offset=spec.get('case_offset', 0))
        run_uid = f'{args.output.name}-part{args.part:02d}'
        data = dataset_config(env, run_uid, plan, stage, experiment_sha256=experiment_sha256(spec), fixed_policy=fixed)
        writer = ShardWriter(root / 'dataset', data, resume=args.resume, shard_rows=args.shard_rows)
        atomic_json(root / 'STATUS.json', dict(phase='COLLECTING', transitions=writer.count, target=target,
                                               part=args.part, parts=args.parts, updated_at=now()))
        stop = lambda: stopped(root) or stopped(args.output)
        result = PolicyCollector(env, actor, writer).collect(target, stop)
        quality = validate_dataset(writer.root)
        atomic_json(root / 'QUALITY.json', quality)
        atomic_json(root / 'STATUS.json', dict(result, part=args.part, parts=args.parts,
                                               updated_at=now(), data_id=quality['data_id']))
        return result
    finally:
        if writer is not None:
            writer.close()
        env.close()
        owner.close()


def progress(root, parts):
    rows = []
    for k in range(parts):
        status = part_dir(root, k) / 'STATUS.json'
        rows.append(read(status) if status.exists() else {})
    done = sum(r.get('transitions', 0) for r in rows)
    phases = ','.join(r.get('phase', '-')[:4] for r in rows)
    return done, phases


def run_workers(args, spec, target):
    """Coordinator: start one subprocess per part, report progress, write POOL.json when all finish."""
    root = args.output
    policy = 'expert' if args.policy == 'expert' else str(Path(args.policy).resolve())
    owner = Owner(root, training_config(spec, 'collection_pool', parts=args.workers, target=args.target,
                                        shard_rows=args.shard_rows, policy=policy,
                                        policy_method=args.policy_method), args.resume)
    logs = root / 'logs'
    logs.mkdir(exist_ok=True)
    env = dict(os.environ, OMP_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1')
    procs = []
    try:
        for k in range(args.workers):
            cmd = [sys.executable, '-B', str(Path(__file__).resolve()), '--output', str(root),
                   '--part', str(k), '--parts', str(args.workers), '--target', str(args.target),
                   '--shard-rows', str(args.shard_rows), '--policy', policy]
            cmd += ['--experiment', str(args.experiment.resolve())]
            cmd += (['--policy-method', args.policy_method] if args.policy_method else []) + (['--resume'] if args.resume else [])
            log = (logs / f'part-{k:02d}.log').open('a')
            procs.append((k, subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env), log))
        started, last_report = time.monotonic(), time.monotonic()
        baseline, _ = progress(root, args.workers)
        while any(p.poll() is None for _, p, _ in procs):
            time.sleep(1.)
            if stopped(root) and not (root / 'STOP').exists():
                # SIGINT/SIGTERM on the coordinator: ask every worker to save and exit.
                print('STOP requested; workers will save and exit', flush=True)
                (root / 'STOP').touch()
            if time.monotonic() - last_report >= args.report_every:
                last_report = time.monotonic()
                done, phases = progress(root, args.workers)
                rate = (done - baseline) / max(1., last_report - started)
                print(f'[{now()}] committed {done:,}/{args.target:,} transitions (session ~{rate:.0f}/s) parts {phases}',
                      flush=True)
        failed = [k for k, p, _ in procs if p.returncode != 0]
        if failed:
            raise SystemExit(f'Parts {failed} failed; see {logs}. Fix and rerun with --resume.')
        if stopped(root):
            print('Stopped. Remove STOP and rerun with --resume to continue.')
            return
        pool = write_pool(root, workers=args.workers)
        print(json.dumps({k: pool[k] for k in ['pool_id', 'unique_transitions', 'completed_episodes', 'split_counts']}, indent=2))
    finally:
        for _, p, log in procs:
            if p.poll() is None:
                p.terminate()
            log.close()
        owner.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', required=True, type=Path, help='pool directory')
    parser.add_argument('--experiment', type=Path, default=Path('configs/kcity/v2_1/experiment.json'),
                        help='experiment settings; a pilot file must set run_purpose=pilot')
    parser.add_argument('--policy', default='expert', help="'expert' (B0) or a BC/RL learner bundle directory")
    parser.add_argument('--policy-method', choices=['B1', 'B2', 'B3'], help='label for a bundle (default: inferred)')
    parser.add_argument('--target', type=int, help='total transition target (default: experiment budget)')
    parser.add_argument('--workers', type=int, default=1, help='parallel SUMO workers on this machine')
    parser.add_argument('--part', type=int, help='run one part only (worker mode)')
    parser.add_argument('--parts', type=int, help='total number of parts (with --part)')
    parser.add_argument('--finalize', action='store_true', help='only write POOL.json from finished parts')
    parser.add_argument('--shard-rows', type=int, default=512)
    parser.add_argument('--report-every', type=float, default=30., help='coordinator progress interval (s)')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    spec = load_experiment(args.experiment.resolve())
    budget = 'expert_valid_transitions_min' if args.policy == 'expert' else 'archive_per_budget_end_policy'
    args.target = args.target or spec['budgets'][budget]
    if args.finalize:
        print(json.dumps(write_pool(args.output, workers=max(1, args.workers)), indent=2)[:2000])
        return
    install_signals()
    if args.part is not None:
        if args.parts is None or not 0 <= args.part < args.parts:
            parser.error('--part k requires --parts N with 0 <= k < N')
        result = collect_part(args, spec, math.ceil(args.target / args.parts))
        print(json.dumps(dict(result, part=args.part), indent=2))
        return
    if args.workers < 1:
        parser.error('--workers must be >= 1')
    run_workers(args, spec, args.target)


if __name__ == '__main__':
    main()
