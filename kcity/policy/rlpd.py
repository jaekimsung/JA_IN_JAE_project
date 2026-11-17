"""RLPD (Reinforcement Learning with Prior Data; Ball et al., 2023) learner, after github.com/ikostrikov/rlpd.

SAC with the three RLPD design choices:
  symmetric sampling   every batch is `offline_ratio` prior (expert) data and the rest online data
  LayerNorm critics    bounded Q extrapolation on actions the prior data never took
  large ensemble + UTD `num_qs` critics, a random subset of `num_min_qs` for the target, `utd_ratio` critic
                       updates per environment step, one actor/temperature update per step

    target = r + γ·mask·( min_{i∈subset} Q̄_i(s', a') − α·log π(a'|s') ),  a' ~ π(·|s')
    critic loss = mean_i (Q_i(s, a) − target)²           (all ensemble members)
    actor loss  = E[ α·log π(a|s) − mean_i Q_i(s, a) ],   a ~ π(·|s)
    α loss      = α·(H[π] − target_entropy),              target_entropy = −|A|/2

`mask` is 0 only on true termination. Method B2 is the same learner with offline_ratio 0 (no prior data).
The acting policy is `self.policy` (the actor): actions are [acceleration, lane command] in (−1, 1).
"""
from copy import deepcopy
import math

import numpy as np
import torch

from kcity.env.observation import OBS_DIM
from kcity.policy.networks import ACT_DIM, Actor, CriticEnsemble

DEFAULT_RLPD = dict(
    actor_lr=3e-4, critic_lr=3e-4, temp_lr=3e-4, hidden_dims=[256, 256], discount=.99, tau=.005,
    num_qs=10, num_min_qs=2, critic_layer_norm=True, init_temperature=1., backup_entropy=True,
    batch_size=256, utd_ratio=20, offline_ratio=.5, start_training=5000)


def seeded(build, seed):
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        return build()


class KCityRLPD:
    def __init__(self, hparams=None, *, seed=11, device='cpu'):
        self.hparams = deepcopy(DEFAULT_RLPD if hparams is None else hparams)
        if set(self.hparams) != set(DEFAULT_RLPD):
            raise ValueError('RLPD hyperparameter keys differ')
        h = self.hparams
        if not 0 <= h['offline_ratio'] < 1 or h['num_min_qs'] > h['num_qs'] or h['utd_ratio'] < 1:
            raise ValueError('Invalid RLPD hyperparameters')
        self.seed, self.device = seed, torch.device(device)
        dims = tuple(h['hidden_dims'])
        self.policy = seeded(lambda: Actor(OBS_DIM, dims), seed).to(self.device)
        self.critic = seeded(lambda: CriticEnsemble(OBS_DIM, dims, h['num_qs'], h['critic_layer_norm']), seed + 1).to(self.device)
        self.target_critic = deepcopy(self.critic).requires_grad_(False)
        self.log_temp = torch.tensor(math.log(h['init_temperature']), device=self.device, requires_grad=True)
        self.target_entropy = -ACT_DIM / 2
        self.actor_opt = torch.optim.Adam(self.policy.parameters(), lr=h['actor_lr'])
        self.critic_opt = torch.optim.Adam(self.critic.parameters(), lr=h['critic_lr'])
        self.temp_opt = torch.optim.Adam([self.log_temp], lr=h['temp_lr'])
        self.generator = torch.Generator(device=self.device).manual_seed(seed)
        self.batch_rng = np.random.default_rng(seed)  # exploration warm-up actions and batch indices
        self.num_updates = 0

    # ------------------------------------------------------------ acting

    def act(self, obs):
        """Stochastic training action."""
        return self.policy.predict(obs, deterministic=False, generator=self.generator)

    def random_action(self):
        return self.batch_rng.uniform(-1, 1, ACT_DIM).astype(np.float32)

    def predict(self, obs, deterministic=True):
        return self.policy.predict(obs, deterministic) if deterministic else self.act(obs)

    # ------------------------------------------------------------ update

    def sample_batch(self, online, prior=None):
        """Symmetric sampling: batch_size·utd_ratio rows, `offline_ratio` of each minibatch from the prior data."""
        h = self.hparams
        total = h['batch_size'] * h['utd_ratio']
        n_prior = int(total * h['offline_ratio']) if prior is not None else 0
        if h['offline_ratio'] > 0 and prior is None:
            raise ValueError('offline_ratio > 0 requires prior data')
        batch = online.sample(total - n_prior, self.batch_rng)
        if n_prior:
            first = prior.sample(n_prior, self.batch_rng)
            # Interleave so that every one of the utd_ratio minibatches keeps the same mixture.
            mixed = {}
            for key in batch:
                rows = np.empty((total,) + batch[key].shape[1:], batch[key].dtype)
                slots = np.zeros(total, bool)
                slots[np.linspace(0, total, n_prior, endpoint=False).astype(int)] = True
                rows[slots], rows[~slots] = first[key], batch[key]
                mixed[key] = rows
            batch = mixed
        return batch

    def update(self, batch):
        h = self.hparams
        tensors = {k: torch.as_tensor(v, dtype=torch.float32, device=self.device) for k, v in batch.items()}
        if len(tensors['reward']) != h['batch_size'] * h['utd_ratio'] or not all(torch.isfinite(v).all() for v in tensors.values()):
            raise ValueError('RLPD update requires a finite batch of batch_size*utd_ratio rows')
        stats = {}
        for mini in zip(*(v.chunk(h['utd_ratio']) for v in tensors.values())):
            obs, action, reward, next_obs, mask = mini
            temp = self.log_temp.exp().detach()
            with torch.no_grad():
                next_action, next_log_prob = self.policy.sample(next_obs, self.generator)
                subset = torch.randperm(h['num_qs'], generator=self.generator, device=self.device)[:h['num_min_qs']]
                next_q = self.target_critic(next_obs, next_action, subset).min(0).values
                if h['backup_entropy']:
                    next_q = next_q - temp * next_log_prob
                target = reward + h['discount'] * mask * next_q
            qs = self.critic(obs, action)
            critic_loss = ((qs - target) ** 2).mean()
            self.critic_opt.zero_grad()
            critic_loss.backward()
            self.critic_opt.step()
            with torch.no_grad():
                for param, slow in zip(self.critic.parameters(), self.target_critic.parameters()):
                    slow.mul_(1 - h['tau']).add_(param, alpha=h['tau'])
        # One actor and temperature update per environment step, on the last minibatch.
        new_action, log_prob = self.policy.sample(obs, self.generator)
        self.critic.requires_grad_(False)
        actor_loss = (temp * log_prob - self.critic(obs, new_action).mean(0)).mean()
        self.actor_opt.zero_grad()
        actor_loss.backward()
        self.actor_opt.step()
        self.critic.requires_grad_(True)
        entropy = -log_prob.detach().mean()
        temp_loss = self.log_temp.exp() * (entropy - self.target_entropy)
        self.temp_opt.zero_grad()
        temp_loss.backward()
        self.temp_opt.step()
        self.num_updates += 1
        stats.update(critic_loss=critic_loss.item(), q=qs.mean().item(), actor_loss=actor_loss.item(),
                     entropy=entropy.item(), temperature=temp.item())
        return stats

    # ------------------------------------------------------------ resume

    def training_state(self):
        return dict(
            actor=self.policy.state_dict(), critic=self.critic.state_dict(), target_critic=self.target_critic.state_dict(),
            log_temp=self.log_temp.detach().cpu(), actor_opt=self.actor_opt.state_dict(),
            critic_opt=self.critic_opt.state_dict(), temp_opt=self.temp_opt.state_dict(),
            generator=self.generator.get_state(), batch_rng=self.batch_rng.bit_generator.state,
            num_updates=self.num_updates, seed=self.seed, device_type=self.device.type)

    def restore_training_state(self, state):
        if state['seed'] != self.seed or state['device_type'] != self.device.type:
            raise ValueError('Resume seed/device mismatch')
        self.policy.load_state_dict(state['actor'])
        self.critic.load_state_dict(state['critic'])
        self.target_critic.load_state_dict(state['target_critic'])
        with torch.no_grad():
            self.log_temp.copy_(state['log_temp'])
        for name in ['actor_opt', 'critic_opt', 'temp_opt']:
            getattr(self, name).load_state_dict(state[name])
        self.generator.set_state(state['generator'].cpu())
        self.batch_rng.bit_generator.state = state['batch_rng']
        self.num_updates = state['num_updates']
