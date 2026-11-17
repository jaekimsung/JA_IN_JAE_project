"""Parallel expert pools: case partition, part discovery, POOL.json and multi-part BC views (no SUMO)."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcity.data.collector import case_plan
from kcity.data.pool import partition, pool_data_id, pool_parts, write_pool
from kcity.env.config import load_contract
from kcity.training.bc import build_views, read_views
from kcity.training.experiment import load_experiment


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fake_part(root, k, *, rows=6, eligible=True, stale=False):
    """A minimal committed dataset part: RUN/RELEASE/QUALITY and one shard with numeric.npz."""
    dataset = root / f'part-{k:02d}' / 'dataset'
    run_uid, data_id = f'pool-part{k:02d}', f'data-{k}'
    write(dataset / 'RUN.json', dict(run_uid=run_uid, source_stage='expert_pool', eligible_for_research_training=eligible))
    write(dataset / 'RELEASE.json', dict(data_id=data_id, eligible_for_research_training=eligible))
    splits = ['expert_train'] * (rows - 2) + ['expert_val'] * 2
    episodes = [dict(episode_uid=f'ep{k}-{s}', case_uid=f'case{k}-{s}', data_split=s,
                     metrics=dict(compliant_completion=True, primary_end_reason='arrival',
                                  decision_count=splits.count(s)))
                for s in ['expert_train', 'expert_val']]
    write(root / f'part-{k:02d}' / 'QUALITY.json', dict(
        data_id='old' if stale else data_id, unique_transitions=rows, committed_shards=1,
        split_counts=dict(Counter(splits)), event_counts={}, episodes=episodes))
    shard = dataset / 'shards' / 'shard-000000'
    write(shard / 'SHARD.json', {})
    obs = np.zeros((rows, 63), np.float32)
    obs[:, 0] = np.arange(rows) / 10 + k
    np.savez(shard / 'numeric.npz', observation=obs, action_env_input=np.zeros((rows, 2), np.float32),
             action_mask=np.tile([False, True, False], (rows, 1)),
             transition_uid=np.asarray([f't{k}-{i}' for i in range(rows)], dtype='U64'),
             data_split=np.asarray(splits, dtype='U32'),
             episode_uid=np.asarray([f'ep{k}-{s}' for s in splits], dtype='U64'))
    return dataset


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.plan = case_plan(load_contract(), 'expert', count=200)

    def test_parts_are_disjoint_complete_and_keep_case_identity(self):
        parts = [partition(self.plan, k, 3) for k in range(3)]
        uids = [r['case']['case_uid'] for p in parts for r in p]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertEqual(sorted(uids), sorted(r['case']['case_uid'] for r in self.plan))
        original = {r['case']['case_uid']: r for r in self.plan}
        for p in parts:
            self.assertTrue(all(original[r['case']['case_uid']] == r for r in p))

    def test_every_part_keeps_the_scenario_mix(self):
        for k in range(4):
            part = partition(self.plan, k, 4)
            self.assertEqual(len(part) % 10, 0)
            counts = Counter(r['case']['scenario_id'] for r in part)
            self.assertEqual(counts['A'] * 10, len(part) * 3)
            self.assertEqual(counts['C'] * 10, len(part) * 4)

    def test_single_part_is_the_sequential_plan_and_bad_args_fail(self):
        self.assertEqual(partition(self.plan, 0, 1), self.plan)
        for part, parts in [(2, 2), (-1, 2), (0, 0)]:
            with self.assertRaises(ValueError):
                partition(self.plan, part, parts)


class PoolTests(unittest.TestCase):
    def test_part_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                pool_parts(root / 'missing')
            single = fake_part(root / 'single', 0)
            self.assertEqual(pool_parts(single), [single])
            pool = root / 'pool'
            parts = [fake_part(pool, k) for k in [1, 0]]
            self.assertEqual(pool_parts(pool), sorted(parts))

    def test_pool_totals_identity_and_disjointness(self):
        with tempfile.TemporaryDirectory() as d:
            pool = Path(d)
            for k in range(2):
                fake_part(pool, k)
            summary = write_pool(pool)
            self.assertEqual(summary['unique_transitions'], 12)
            self.assertEqual(summary['split_counts'], {'expert_train': 8, 'expert_val': 4})
            self.assertEqual(summary['pool_id'], pool_data_id(pool))
            self.assertEqual(json.loads((pool / 'POOL.json').read_text())['completed_episodes'], 4)
            quality = pool / 'part-01' / 'QUALITY.json'
            report = json.loads(quality.read_text())
            report['episodes'][0]['case_uid'] = 'case0-expert_train'
            quality.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'more than one part'):
                write_pool(pool)

    def test_stale_worker_report_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            fake_part(Path(d), 0, stale=True)
            with self.assertRaises(Exception):  # falls back to full validation of an incomplete fixture
                write_pool(Path(d))

    def test_bc_views_span_parts_deterministically_and_detect_pool_change(self):
        spec = deepcopy(load_experiment())
        spec['budgets']['expert_valid_transitions_min'] = 12
        spec['bc'].update(train_view_rows=6, validation_view_rows=3)
        with tempfile.TemporaryDirectory() as d:
            pool = Path(d) / 'pool'
            for k in range(2):
                fake_part(pool, k)
            first = build_views(pool, Path(d) / 'v1', spec)
            second = build_views(pool, Path(d) / 'v2', spec)
            self.assertEqual(first['files'], second['files'])
            _, data = read_views(Path(d) / 'v1')
            self.assertEqual(len(data['expert_train']['observation']), 6)
            self.assertEqual(len(data['expert_val']['observation']), 3)
            sources = {uid.split('-')[0] for uid in data['expert_train']['transition_uid']}
            self.assertEqual(sources, {'t0', 't1'})
            self.assertTrue(set(data['expert_val']['transition_uid']).isdisjoint(data['expert_train']['transition_uid']))
            write(pool / 'part-01' / 'dataset' / 'RELEASE.json', dict(data_id='more-data', eligible_for_research_training=True))
            with self.assertRaisesRegex(ValueError, 'Pool changed'):
                read_views(Path(d) / 'v1')

    def test_debug_part_cannot_enter_bc_views(self):
        spec = deepcopy(load_experiment())
        with tempfile.TemporaryDirectory() as d:
            pool = Path(d)
            fake_part(pool, 0)
            fake_part(pool, 1, eligible=False)
            with self.assertRaisesRegex(ValueError, 'Not a new main expert pool'):
                build_views(pool, pool / 'views', spec)


if __name__ == '__main__':
    unittest.main()
