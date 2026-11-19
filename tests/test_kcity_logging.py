"""Logging intervals, including partial STOP windows and critic minibatches (no SUMO)."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcity.env.observation import OBS_DIM
from kcity.policy.bc import KCityBC
from kcity.policy.rlpd import DEFAULT_RLPD, KCityRLPD
from kcity.training.bc import run_bc
from kcity.training.experiment import load_experiment
from kcity.training.logging import IntervalMean
from kcity.training.rl import run_rl


def curve(root):
    return [json.loads(line) for line in (root / 'curve.jsonl').read_text().splitlines()]


class LoggingTests(unittest.TestCase):
    def test_mean_and_reset(self):
        interval = IntervalMean()
        self.assertIsNone(interval.mean())
        interval.add(dict(loss=1., signed=-4.))
        interval.add(dict(loss=7., signed=2.))
        self.assertEqual(interval.mean(), dict(loss=4., signed=-1.))
        self.assertEqual(interval.count, 2)
        interval.reset()
        self.assertIsNone(interval.mean())
        interval.add(dict(loss=9.))
        self.assertEqual(interval.mean(), dict(loss=9.))
        with self.assertRaises(ValueError):
            interval.add(dict(other=1.))

    def test_bc_partial_stop_resume_logs_disjoint_windows_and_preserves_weights(self):
        spec = load_experiment()
        spec['bc'].update(updates_per_seed=5, validate_every_updates=3, batch_size=2)
        spec['rlpd']['hidden_dims'] = [4, 4]
        data = dict(observation=np.zeros((4, OBS_DIM), np.float32),
                    action_target=np.ones((4, 2), np.float32) * .2)
        views = (dict(data_id='fixture', view_id='fixture'), dict(expert_train=data, expert_val=data))
        models = []

        def make_model(*args, **kwargs):
            model = KCityBC(*args, **kwargs)
            train = model.train_batch

            def batch(*args):
                train(*args)
                return dict(loss=float(model.updates ** 2))

            model.train_batch = batch
            models.append(model)
            return model

        with tempfile.TemporaryDirectory() as d, \
                patch('kcity.training.bc.read_views', return_value=views), \
                patch('kcity.training.bc.KCityBC', side_effect=make_model):
            full, resumed = Path(d) / 'full', Path(d) / 'resumed'
            run_bc(full, Path(d) / 'views', 11, spec, 'cpu')
            with patch('kcity.training.bc.stopped', side_effect=lambda root: models[-1].updates >= 2):
                run_bc(resumed, Path(d) / 'views', 11, spec, 'cpu')
            run_bc(resumed, Path(d) / 'views', 11, spec, 'cpu', resume=True)
            rows = curve(resumed)
            self.assertEqual([r['training_update_count'] for r in rows], [2, 1, 2])
            self.assertEqual([r['interval_start_updates'] for r in rows], [0, 2, 3])
            self.assertEqual([r['training']['loss'] for r in rows], [2.5, 9., 20.5])
            self.assertAlmostEqual(curve(full)[0]['training']['loss'], 14 / 3)
            for key, value in models[0].policy.state_dict().items():
                self.assertTrue(torch.equal(value, models[-1].policy.state_dict()[key]))

    def test_rl_warmup_is_not_counted_and_each_commit_resets_mean(self):
        spec = load_experiment()
        spec['budgets']['rl_transitions_per_method_seed'] = 7
        spec['rlpd']['start_training'] = 2
        spec['rl']['commit_interval'] = 3
        case = dict(namespace='train', scenario_id='A', case_index=0, demand_multiplier=1.)
        obs = np.zeros(OBS_DIM, np.float32)
        writer = SimpleNamespace(count=0, folders=[], shard_rows=3, pending=0,
                                 last_checkpoint=lambda: (None, None), close=lambda: None)
        env = SimpleNamespace(contract={}, case=case, _state={}, get_detected_vehicles=lambda: [],
                              reset=lambda **kwargs: (obs, {}), close=lambda: None,
                              step=lambda action: (obs, 0., False, False, {}))
        agent = SimpleNamespace(device=torch.device('cpu'), num_updates=0,
                                random_action=lambda: np.zeros(2), act=lambda obs: np.zeros(2),
                                sample_batch=lambda *args: None)

        def update(batch):
            agent.num_updates += 1
            return dict(critic_loss=float(agent.num_updates ** 2), actor_loss=-float(agent.num_updates))

        agent.update = update

        def add(**kwargs):
            writer.pending += 1

        def commit(*args):
            writer.count += writer.pending
            writer.pending = 0
            return root / 'transitions' / f'shard-{writer.count}'

        recorder = SimpleNamespace(recorder=SimpleNamespace(active=True), add=add, commit=commit)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'rl'
            with patch('kcity.training.rl.SumoKCityEnv', return_value=env), \
                    patch('kcity.training.rl.KCityRLPD', return_value=agent), \
                    patch('kcity.training.rl.GeneratedCasePlan.for_budget', return_value=[dict(case=case)]), \
                    patch('kcity.training.rl.dataset_config', return_value={}), \
                    patch('kcity.training.rl.ShardWriter', return_value=writer), \
                    patch('kcity.training.rl.OnlineRecorder', return_value=recorder), \
                    patch('kcity.training.rl.checkpoint_from_shard', side_effect=lambda path: path / 'bundle'), \
                    patch('kcity.training.rl.evaluate_dev', return_value=True):
                run_rl(root, 'B2', 11, spec, 'cpu')
                rows = curve(root)
                # A commit with no optimizer updates must not invent a zero loss.
                root = Path(d) / 'warmup'
                writer.count = writer.pending = agent.num_updates = 0
                spec['rlpd']['start_training'] = 7
                run_rl(root, 'B2', 11, spec, 'cpu')
                warmup_rows = curve(root)
            self.assertTrue(all(r['metrics'] is None and r['training_update_count'] == 0
                                for r in warmup_rows))
            self.assertEqual([r['training_update_count'] for r in rows], [1, 3, 1])
            self.assertEqual([r['interval_start_transitions'] for r in rows], [0, 3, 6])
            self.assertEqual([r['metrics']['critic_loss'] for r in rows], [1., 29 / 3, 25.])
            self.assertEqual([r['metrics']['actor_loss'] for r in rows], [-1., -3., -5.])

    def test_rlpd_critic_loss_is_mean_of_all_minibatches(self):
        hp = dict(DEFAULT_RLPD, hidden_dims=[4, 4], num_qs=2, num_min_qs=1,
                  batch_size=2, utd_ratio=3, offline_ratio=0.)
        agent = KCityRLPD(hp)
        rng = np.random.default_rng(5)
        batch = dict(observation=rng.normal(size=(6, OBS_DIM)).astype(np.float32),
                     action=np.zeros((6, 2), np.float32), reward=np.arange(6, dtype=np.float32),
                     next_observation=np.zeros((6, OBS_DIM), np.float32), mask=np.zeros(6, np.float32))
        losses = []
        backward = torch.Tensor.backward

        def record_backward(tensor, *args, **kwargs):
            losses.append(tensor.detach().item())
            return backward(tensor, *args, **kwargs)

        reference = KCityRLPD(hp)
        with patch.object(torch.Tensor, 'backward', record_backward):
            stats = agent.update(batch)
        reference.update(batch)
        self.assertAlmostEqual(stats['critic_loss'], sum(losses[:3]) / 3, places=5)
        self.assertNotAlmostEqual(stats['critic_loss'], losses[2], places=3)
        for key, value in agent.policy.state_dict().items():
            self.assertTrue(torch.equal(value, reference.policy.state_dict()[key]))


if __name__ == '__main__':
    unittest.main()
