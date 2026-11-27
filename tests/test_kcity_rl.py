"""RLPD learner, networks, BC, transition stores and the rule expert's decisions (no SUMO)."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kcity.data.replay import TransitionStore
from kcity.env.observation import (CONFLICT, CORRIDOR, EXISTS, LANE_ENDS, LANE_LEFT, OBS_DIM, SPEED, TLS_DIST, TLS_RED,
                                   TLS_YELLOW, VIA_LENGTH, YIELD_SIGN)
from kcity.evaluation.metrics import policy_weights_sha256
from kcity.policy.bc import KCityBC
from kcity.policy.checkpoint import load_policy, read_bundle
from kcity.policy.networks import Actor, CriticEnsemble
from kcity.policy.rlpd import DEFAULT_RLPD, KCityRLPD
from kcity.policy.rule_expert import KCityRuleExpert


def small(**changes):
    return {**DEFAULT_RLPD, **dict(hidden_dims=[16, 16], num_qs=4, batch_size=8, utd_ratio=3), **changes}


def store(n, seed, reward=0.0):
    rng = np.random.default_rng(seed)
    s = TransitionStore(n)
    for _ in range(n):
        s.add(rng.uniform(-1, 1, OBS_DIM), rng.uniform(-1.5, 1.5, 2), reward, rng.uniform(-1, 1, OBS_DIM), rng.random() < .1)
    return s


class NetworkTests(unittest.TestCase):
    def test_actor_samples_are_bounded_with_matching_log_probability(self):
        actor = Actor(OBS_DIM, (16, 16))
        obs = torch.rand(256, OBS_DIM)
        action, log_prob = actor.sample(obs, torch.Generator().manual_seed(1))
        self.assertTrue((action.abs() <= 1).all() and torch.isfinite(log_prob).all())
        mean, log_std = actor(obs)
        noise = torch.randn(mean.shape, generator=torch.Generator().manual_seed(1))
        u = mean + log_std.exp() * noise  # the same pre-tanh sample
        self.assertTrue(torch.allclose(action, torch.tanh(u)))
        expected = (torch.distributions.Normal(mean, log_std.exp()).log_prob(u)
                    - torch.log(1 - torch.tanh(u) ** 2)).sum(-1)
        inner = u.abs().max(-1).values < 3  # where float32 1 - tanh² is still accurate
        self.assertTrue(inner.any() and torch.allclose(log_prob[inner], expected[inner], atol=1e-3))
        self.assertTrue(np.allclose(actor.predict(obs[0].numpy()), torch.tanh(mean[0]).detach().numpy(), atol=1e-6))

    def test_critic_ensemble_members_are_independent_and_subsettable(self):
        critic = CriticEnsemble(OBS_DIM, (16, 16), num_qs=5)
        obs, action = torch.rand(7, OBS_DIM), torch.rand(7, 2)
        q = critic(obs, action)
        self.assertEqual(q.shape, (5, 7))
        self.assertFalse(torch.allclose(q[0], q[1]))
        subset = torch.tensor([3, 1])
        self.assertTrue(torch.allclose(critic(obs, action, subset), q[subset], atol=1e-6))


class LearnerTests(unittest.TestCase):
    def test_symmetric_sampling_keeps_the_prior_share_in_every_minibatch(self):
        agent = KCityRLPD(small(utd_ratio=4))
        batch = agent.sample_batch(store(50, 1, reward=0.0), store(50, 2, reward=1.0))
        self.assertEqual(len(batch['reward']), 32)
        for chunk in np.split(batch['reward'], 4):
            self.assertEqual(chunk.sum(), 4)  # half of each minibatch of 8 is prior data
        online_only = KCityRLPD(small(offline_ratio=0.0))
        self.assertEqual(online_only.sample_batch(store(50, 1), None)['reward'].sum(), 0)
        with self.assertRaises(ValueError):
            agent.sample_batch(store(50, 1), None)

    def test_update_changes_actor_critic_target_and_temperature(self):
        agent = KCityRLPD(small())
        online, prior = store(60, 1, 1.0), store(60, 2, 2.0)
        before = [policy_weights_sha256(m) for m in (agent.policy, agent.critic, agent.target_critic)]
        stats = agent.update(agent.sample_batch(online, prior))
        self.assertTrue(all(np.isfinite(v) for v in stats.values()))
        after = [policy_weights_sha256(m) for m in (agent.policy, agent.critic, agent.target_critic)]
        self.assertTrue(all(a != b for a, b in zip(before, after)))
        self.assertNotEqual(float(agent.log_temp), 0.0)
        self.assertEqual(agent.num_updates, 1)
        with self.assertRaises(ValueError):
            agent.update({k: v[:5] for k, v in agent.sample_batch(online, prior).items()})

    def test_terminal_transitions_do_not_bootstrap(self):
        agent = KCityRLPD(small(utd_ratio=1, batch_size=16, tau=0.0, critic_lr=0.05, offline_ratio=0.0))
        s = TransitionStore(16)
        for _ in range(16):
            s.add(np.zeros(OBS_DIM), [0.2, 0.0], 3.0, np.ones(OBS_DIM), True)
        with torch.no_grad():  # a huge target value must be ignored when mask is 0
            agent.target_critic.out.bias.fill_(1e6)
        for _ in range(300):
            agent.update(agent.sample_batch(s))
        q = agent.critic(torch.zeros(1, OBS_DIM), torch.tensor([[0.2, 0.0]])).mean().item()
        self.assertAlmostEqual(q, 3.0, delta=0.3)

    def test_training_state_resume_is_exact(self):
        online, prior = store(80, 1, 1.0), store(80, 2, 2.0)
        a = KCityRLPD(small())
        a.update(a.sample_batch(online, prior))
        b = KCityRLPD(small())
        b.restore_training_state(deepcopy(a.training_state()))
        obs = np.zeros(OBS_DIM, np.float32)
        for _ in range(2):
            self.assertTrue(np.array_equal(a.act(obs), b.act(obs)))
            self.assertTrue(np.array_equal(a.random_action(), b.random_action()))
            self.assertEqual(a.update(a.sample_batch(online, prior)), b.update(b.sample_batch(online, prior)))
        self.assertEqual(policy_weights_sha256(a), policy_weights_sha256(b))
        with self.assertRaises(ValueError):
            KCityRLPD(small(), seed=12).restore_training_state(a.training_state())

    def test_bc_fits_targets_and_bundle_loads_as_acting_policy(self):
        bc = KCityBC([32, 32], seed=3)
        obs = store(128, 5).data['observation']
        target = np.stack([np.tanh(obs[:, :8].sum(1)), np.sign(obs[:, 8])], 1).astype(np.float32)  # learnable rule
        first = bc.train_batch(obs, target)['loss']
        for _ in range(500):
            last = bc.train_batch(obs, target)['loss']
        self.assertLess(last, first * .5)
        with self.assertRaises(ValueError):
            bc.train_batch(obs, target * 3)
        with tempfile.TemporaryDirectory() as d:
            bc.save_checkpoint(Path(d) / 'b', dict(data_id='x'))
            policy, meta = load_policy(Path(d) / 'b')
            self.assertEqual((meta['kind'], meta['config']['method']), ('bc', 'B1'))
            self.assertTrue(np.array_equal(policy.predict(obs[0]), bc.predict(obs[0])))
            with self.assertRaises(ValueError):
                read_bundle(Path(d) / 'b', 'rl', meta['config'])

    def test_transition_store_clips_actions_and_masks_termination(self):
        s = TransitionStore(2)
        s.add(np.zeros(OBS_DIM), [3.0, -3.0], 1.0, np.zeros(OBS_DIM), True)
        s.add(np.zeros(OBS_DIM), [0.5, 1.0], 1.0, np.zeros(OBS_DIM), False)
        self.assertEqual(s.data['action'].tolist(), [[1.0, -1.0], [0.5, 1.0]])
        self.assertEqual(s.data['mask'].tolist(), [0.0, 1.0])
        with self.assertRaises(ValueError):
            s.add(np.zeros(OBS_DIM), [0, 0], 0, np.zeros(OBS_DIM), False)


class ExpertTests(unittest.TestCase):
    def obs(self, speed=5.0):
        o = np.zeros(OBS_DIM, np.float32)
        o[SPEED] = speed / 8.33
        for k in range(5):
            o[CORRIDOR + 4 * k:CORRIDOR + 4 * k + 4] = [1, 0, -1, 0]
        o[EXISTS + 2] = 1
        o[TLS_DIST] = 1
        o[LANE_LEFT] = 0.2  # 20 m to the junction entry
        return o

    def decide(self, o):
        action, detail = KCityRuleExpert().decision(o)
        return float(action[0]), detail['reasons']

    def test_red_stops_and_yellow_depends_on_distance(self):
        o = self.obs(7.0)
        o[TLS_DIST], o[TLS_RED] = 0.08, 1
        accel, reasons = self.decide(o)
        self.assertIn('signal_stop', reasons)
        self.assertLess(accel, 0)
        o = self.obs(8.0)
        o[TLS_DIST], o[TLS_YELLOW] = 0.2, 1
        self.assertIn('signal_stop', self.decide(o)[1])  # 20 m away at 8 m/s: stop
        o[TLS_DIST] = 0.05
        self.assertNotIn('signal_stop', self.decide(o)[1])  # 5 m away: cannot stop, clear the line during yellow

    def test_yields_to_arriving_or_inside_vehicles_not_to_waiting_ones(self):
        o = self.obs(7.0)
        o[YIELD_SIGN], o[VIA_LENGTH], o[LANE_LEFT] = 1, 0.3, 0.06
        self.assertNotIn('yield', self.decide(o)[1])
        o[CONFLICT:CONFLICT + 4] = [1, 0.4, 0.9, 0]  # 20 m away at 7.5 m/s
        accel, reasons = self.decide(o)
        self.assertIn('yield', reasons)
        self.assertLess(accel, 0)
        o[CONFLICT:CONFLICT + 4] = [1, 0.04, 0.0, 0]  # standing at its own stop line: it is waiting
        self.assertNotIn('yield', self.decide(o)[1])
        o[CONFLICT:CONFLICT + 4] = [1, 1.0, 0.5, 0]  # 50 m away at 4 m/s: the ego clears first
        self.assertNotIn('yield', self.decide(o)[1])
        o[CONFLICT:CONFLICT + 4] = [1, 0.0, 0.0, 1]  # inside the junction
        self.assertIn('yield', self.decide(o)[1])
        o[YIELD_SIGN] = 0  # on the major road the ego does not yield
        self.assertNotIn('yield', self.decide(o)[1])

    def test_waits_for_a_gap_before_the_required_lane_change(self):
        o = self.obs()
        o[EXISTS + 1], o[LANE_LEFT], o[LANE_ENDS] = 1, 0.4, 1  # the current lane ends; a left lane exists
        action, detail = KCityRuleExpert().decision(o)
        self.assertEqual(action[1], 1.0)
        o[CORRIDOR + 4 * 1] = 0.03  # a vehicle 3 m ahead in the target lane
        action, detail = KCityRuleExpert().decision(o)
        self.assertEqual(action[1], 0.0)
        self.assertIn('lane_end_wait', detail['reasons'])

    def test_keeps_a_safe_gap_without_sumo_assistance(self):
        o = self.obs(8.0)
        o[CORRIDOR + 4 * 2], o[CORRIDOR + 4 * 2 + 1] = 0.08, -1.0  # leader 8 m ahead, standing still
        accel, reasons = self.decide(o)
        self.assertEqual(accel, -1.0)
        self.assertIn('following', reasons)


if __name__ == '__main__':
    unittest.main()
