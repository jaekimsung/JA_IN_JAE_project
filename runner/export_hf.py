"""Prepare validated K-CITY datasets as a Hugging Face dataset folder (no upload).

    python export_hf.py --dataset runs/expert/dataset --dataset runs/B2_seed11/transitions ... \
        --output runs/hf_export --name kcity-driving

Each dataset is validated, then its shards' data files (transitions.jsonl.gz, numeric.npz,
events.jsonl.gz) are hard-linked (or copied with --copy) under <output>/data/<dataset-name>/.
Resume/learner state (collector.json, environment/) is not exported. Upload yourself, e.g.
    huggingface-cli upload <user>/<repo> <output> --repo-type dataset
"""
import sys
from pathlib import Path

import argparse
from collections import Counter
import json
import os
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 저장소 루트
from training.experiment import git_info
from data.dataset import OBSERVATION_ID, SCHEMA_ID, shard_directories, validate_dataset

DATA_FILES = ('transitions.jsonl.gz', 'numeric.npz', 'events.jsonl.gz')

READER = '''"""Standalone reader for the K-CITY driving dataset (needs only numpy).

JSONL rows may store `next_reference` instead of next_state/next_observation: the
values equal the following row's state/observation (same Episode, t+1). This reader
restores them so every yielded row has the full transition.
"""
import gzip
import json
from pathlib import Path

import numpy as np


def rows(shard):
    with gzip.open(Path(shard) / 'transitions.jsonl.gz', 'rt') as stream:
        items = iter(json.loads(line) for line in stream)
        current = next(items, None)
        while current is not None:
            following = next(items, None)
            if 'next_reference' in current:
                assert following is not None and current.pop('next_reference') == following['transition_uid']
                current['next_state'], current['next_observation'] = following['state'], following['observation']
            yield current
            current = following


def numeric(shard):
    with np.load(Path(shard) / 'numeric.npz', allow_pickle=False) as arrays:
        return {key: arrays[key] for key in arrays.files}


def shards(root):
    return sorted(p for p in Path(root).glob('data/*/shard-*') if p.is_dir())


if __name__ == '__main__':
    import sys
    first = shards(sys.argv[1] if len(sys.argv) > 1 else '.')[0]
    row = next(rows(first))
    print(first, sorted(row)[:12], numeric(first)['observation'].shape)
'''

COLUMNS = [
    ('episode', 'int', '-', 'Episode number within the dataset (dataset-local)'),
    ('t', 'int', 'decision', 'Decision index within the Episode (2 Hz policy, 0.5 s per step)'),
    ('observation', 'float32[73]', 'normalized [-1,1]', 'Partial observation o_t given to the AV policy (KC-OBS73-v1)'),
    ('action_raw', 'float32[2]', '-', 'Policy output [acceleration, lane change] before clipping'),
    ('action.accel_raw', 'float', 'normalized [-1,1]', 'Acceleration command passed to SUMO (x2.0 m/s² up, x4.5 m/s² down)'),
    ('action.lane_change_raw', 'float', '-', 'Raw lane command passed to the environment'),
    ('action.lane_change', 'int', '{-1,0,+1}', 'Quantized lane command (+1 left, -1 right)'),
    ('action.lane_change_applied', 'bool', '-', 'Whether the lane command was issued to SUMO (mask/cooldown allowed it)'),
    ('reward', 'float32', '-', 'Reward r_t (progress/10, +10 arrival, -20 collision, -10 red entry, small LC/invalid penalties)'),
    ('terminated', 'bool', '-', 'Task end: arrival, collision, red entry, wrong route, deadline (time is in the observation)'),
    ('truncated', 'bool', '-', 'External time limit (not used by the native task)'),
    ('state', 'dict', 'm, m/s, deg', 'Privileged SUMO state s_t: all vehicles, ego pose/lane/route progress, signals, traffic counts'),
    ('detected_vehicles', 'list', 'm, m/s', 'Vehicles near the AV at observation time (same/adjacent corridor, crossing)'),
    ('event.collided', 'bool', '-', 'AV collision during this step'),
    ('event.arrived', 'bool', '-', 'AV reached the goal during this step'),
    ('event.lane_before / lane_after', 'int', 'lane index', 'AV lane before and after the action'),
    ('next_observation', 'float32[73]', 'normalized', 'o_{t+1}; in JSONL restored from the next row when `next_reference` is used'),
    ('next_state', 'dict', '-', 's_{t+1}; in JSONL restored from the next row when `next_reference` is used'),
]


def link(source, target, copy):
    target.parent.mkdir(parents=True, exist_ok=True)
    if copy:
        shutil.copy2(source, target)
    else:
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)


def card(name, reports):
    total = sum(r['unique_transitions'] for r in reports.values())
    splits = Counter()
    for r in reports.values():
        splits.update(r['split_counts'])
    lines = ['---', f'pretty_name: {name}', 'license: other', 'task_categories:', '- reinforcement-learning',
             'tags:', '- autonomous-driving', '- sumo', '- k-city', '---', '',
             f'# {name}', '',
             'POMDP transitions of an autonomous vehicle (AV) driving the K-CITY road network in SUMO among '
             'human-driven vehicles (HV), with traffic signals and route goals. Each transition stores the '
             'policy observation, action, reward, termination flags, the privileged simulator state before and '
             'after the step, detected vehicles and events.', '',
             f'- Transitions: **{total:,}** (schema `{SCHEMA_ID}`, observation `{OBSERVATION_ID}`)',
             '- Splits: ' + ', '.join(f'{k} {v:,}' for k, v in sorted(splits.items())),
             f'- Code: git `{git_info()["commit"]}`', '', '## Parts', '',
             '| part | source stage | transitions | Episodes | data_id |', '|---|---|---:|---:|---|']
    for part, r in reports.items():
        lines.append(f"| `{part}` | {r['source_stage']} | {r['unique_transitions']:,} | {len(r['episodes']):,} | `{r['data_id'][:16]}` |")
    lines += ['', '## Columns (JSONL, one transition per line)', '', '| field | type | unit | meaning |', '|---|---|---|---|']
    lines += [f'| `{a}` | {b} | {c} | {d} |' for a, b, c, d in COLUMNS]
    lines += ['', 'Additional fields: run/case/episode/transition UIDs, data_split, policy identity, reward_components, '
              'substep_samples (0.1 s), traffic_interval, end_reason, and learner values for online PPO rows.', '',
              '## Files', '', '```text', 'data/<part>/shard-XXXXXX/',
              '  transitions.jsonl.gz   full transitions (authoritative)',
              '  numeric.npz            observation, next_observation, action_raw, action_env_input, action_mask, reward,',
              '                         terminated, truncated, episode, t, lane_change, detected_xy, detected_offsets, ...',
              '  events.jsonl.gz        per-tick events (lane change, collision, signal crossing, arrival)',
              'load_kcity.py            standalone reader (numpy only)', '```', '',
              '`numeric.npz` holds the same transitions as fixed-size arrays for direct use in NumPy/PyTorch.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dataset', action='append', required=True, type=Path, help='dataset root (repeatable)')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--name', default='K-CITY Autonomous Driving Transitions')
    parser.add_argument('--copy', action='store_true', help='copy files instead of hard-linking')
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output must be a new or empty directory')
    reports = {}
    for root in args.dataset:
        part = root.parent.name if root.name in ('dataset', 'transitions') else root.name
        if part in reports:
            parser.error(f'Duplicate part name {part}; pass distinct run directories')
        report = validate_dataset(root)
        report['source_stage'] = json.loads((root / 'RUN.json').read_text())['source_stage']
        for shard in shard_directories(root):
            for name in DATA_FILES:
                link(shard / name, args.output / 'data' / part / shard.name / name, args.copy)
        reports[part] = report
        print(f"{part}: {report['unique_transitions']:,} transitions, {report['committed_shards']} shards")
    (args.output / 'README.md').write_text(card(args.name, reports), encoding='utf-8')
    (args.output / 'load_kcity.py').write_text(READER, encoding='utf-8')
    summary = {part: {k: r[k] for k in ['data_id', 'unique_transitions', 'committed_shards', 'split_counts',
                                       'event_counts', 'source_stage']} for part, r in reports.items()}
    (args.output / 'SUMMARY.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(f"total {sum(r['unique_transitions'] for r in reports.values()):,} transitions -> {args.output}")


if __name__ == '__main__':
    main()
