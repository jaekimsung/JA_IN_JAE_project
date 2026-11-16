"""Expert pool = one or more dataset parts collected in parallel.

Layout (runner/collect.py):

    <pool>/POOL.json                 parts, totals and pool_id (written after all parts finish)
    <pool>/part-XX/dataset/          an ordinary KC-DATA-v1 dataset (own ShardWriter, SUMO, resume)
    <pool>/part-XX/QUALITY.json      validate_dataset() report written by that worker

A plain dataset directory (with RUN.json) is also accepted as a one-part pool.
"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from data.dataset import atomic_json, now, validate_dataset
from data.storage import require
from env.config import digest

CYCLE = 10  # one A/A/A/B/B/B/C/C/C/C scenario pattern


def partition(plan, part, parts):
    """Cases of one part: whole 10-case cycles, round robin. Every part keeps the 3:3:4 scenario mix
    and each case keeps the seeds/split it has in the sequential plan."""
    require(type(parts) is int and parts >= 1 and type(part) is int and 0 <= part < parts, 'Invalid part/parts')
    return [r for i, r in enumerate(plan) if (i // CYCLE) % parts == part]


def part_dir(root, part):
    return Path(root) / f'part-{part:02d}'


def pool_parts(root):
    """Dataset directories that make up a pool, in a fixed order."""
    root = Path(root)
    if (root / 'RUN.json').exists():
        return [root]
    if (root / 'dataset' / 'RUN.json').exists():
        return [root / 'dataset']
    parts = sorted(p / 'dataset' for p in root.glob('part-*') if (p / 'dataset' / 'RUN.json').exists())
    require(parts, f'No dataset or pool parts under {root}')
    return parts


def release_id(dataset):
    return json.loads((Path(dataset) / 'RELEASE.json').read_text())['data_id']


def pool_data_id(root):
    """Identity of the pool's committed contents (changes whenever any part commits more data)."""
    ids = [release_id(p) for p in pool_parts(root)]
    return ids[0] if len(ids) == 1 else digest(dict(schema='KC-POOL-v1', parts=ids))


def part_report(dataset, revalidate=False):
    """The worker's own validation report if it still matches the release; otherwise validate now."""
    quality = Path(dataset).parent / 'QUALITY.json'
    if not revalidate and quality.exists():
        report = json.loads(quality.read_text())
        if report.get('data_id') == release_id(dataset):
            return report
    return validate_dataset(dataset)


def pool_reports(root, *, workers=1, revalidate=False):
    parts = pool_parts(root)
    if workers > 1 and len(parts) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(parts))) as pool:
            reports = list(pool.map(part_report, parts, [revalidate] * len(parts)))
    else:
        reports = [part_report(p, revalidate) for p in parts]
    # Parts must be disjoint: distinct runs, cases and Episodes.
    runs = [json.loads((p / 'RUN.json').read_text())['run_uid'] for p in parts]
    require(len(set(runs)) == len(runs), 'Pool parts share a run UID')
    cases = [e['case_uid'] for r in reports for e in r['episodes']]
    require(len(set(cases)) == len(cases), 'A case was collected by more than one part')
    episodes = [e['episode_uid'] for r in reports for e in r['episodes']]
    require(len(set(episodes)) == len(episodes), 'Duplicate Episode UID across parts')
    return parts, reports


def write_pool(root, *, workers=1, revalidate=False):
    root = Path(root)
    parts, reports = pool_reports(root, workers=workers, revalidate=revalidate)
    splits, events = Counter(), Counter()
    for r in reports:
        splits.update(r['split_counts'])
        events.update(r['event_counts'])
    body = dict(schema='KC-POOL-v1', pool_id=pool_data_id(root), created_at=now(),
                unique_transitions=sum(r['unique_transitions'] for r in reports),
                completed_episodes=sum(len(r['episodes']) for r in reports),
                split_counts=dict(splits), event_counts=dict(events),
                parts=[dict(path=p.relative_to(root).as_posix() if p != root else '.', run_uid=json.loads((p / 'RUN.json').read_text())['run_uid'],
                            data_id=r['data_id'], unique_transitions=r['unique_transitions'],
                            completed_episodes=len(r['episodes']), split_counts=r['split_counts'])
                       for p, r in zip(parts, reports)])
    atomic_json(root / 'POOL.json', body)
    return body
