"""BC learner (B1): the RLPD actor trained to reproduce expert actions (MSE on the deterministic action)."""
from copy import deepcopy

import numpy as np
import torch
import torch.nn.functional as F

from kcity.env.observation import OBS_DIM
from kcity.policy.checkpoint import read_bundle, write_bundle
from kcity.policy.networks import Actor
from kcity.policy.rlpd import seeded


class KCityBC:
    def __init__(self, hidden_dims=(256, 256), *, seed=11, lr=3e-4, device='cpu'):
        self.seed, self.lr, self.device = seed, lr, torch.device(device)
        self.hidden_dims = list(hidden_dims)
        self.policy = seeded(lambda: Actor(OBS_DIM, tuple(hidden_dims)), seed).to(self.device)
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=lr)
        self.sampler = np.random.default_rng(seed)
        self.updates = 0

    def loss(self, obs, actions):
        """Acceleration and lane-command errors of the deterministic action tanh(mean)."""
        obs = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
        actions = torch.as_tensor(actions, dtype=torch.float32, device=self.device)
        if actions.shape != (obs.shape[0], 2) or not torch.isfinite(actions).all() or (actions.abs() > 1).any():
            raise ValueError('BC targets must be finite [acceleration, lane] pairs in [-1, 1]')
        predicted = self.policy.mean_action(obs)
        accel = F.mse_loss(predicted[:, 0], actions[:, 0])
        lane = F.mse_loss(predicted[:, 1], actions[:, 1])
        return accel + lane, dict(accel_mse=accel, lane_mse=lane)

    def train_batch(self, obs, actions):
        loss, parts = self.loss(obs, actions)
        if not torch.isfinite(loss):
            raise ValueError('BC loss is not finite')
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        self.updates += 1
        return dict(loss=float(loss.detach()), **{k: float(v.detach()) for k, v in parts.items()})

    def predict(self, obs, deterministic=True):
        return self.policy.predict(obs, deterministic)

    def config(self):
        return dict(method='B1', hidden_dims=self.hidden_dims, seed=self.seed, lr=self.lr, device_type=self.device.type)

    def save_checkpoint(self, path, run_state):
        write_bundle(path, 'bc', self.config(), dict(
            actor=self.policy.state_dict(), optimizer=self.optimizer.state_dict(), updates=self.updates,
            sampler=self.sampler.bit_generator.state, run_state=deepcopy(run_state)))

    def load_checkpoint(self, path, *, expected_data_id=None):
        payload = read_bundle(path, 'bc', self.config())
        if expected_data_id is not None and payload['run_state'].get('data_id') != expected_data_id:
            raise ValueError('BC dataset identity mismatch')
        self.policy.load_state_dict(payload['actor'], strict=True)
        self.optimizer.load_state_dict(payload['optimizer'])
        self.updates = payload['updates']
        self.sampler.bit_generator.state = payload['sampler']
        return deepcopy(payload['run_state'])
