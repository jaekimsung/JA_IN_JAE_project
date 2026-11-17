"""Networks shared by BC and RLPD: a tanh-Gaussian actor and a LayerNorm critic ensemble.

Actor   obs -> MLP -> (mean, log_std) -> a = tanh(u), u ~ Normal(mean, std);  action = [acceleration, lane command]
Critic  E independent Q(s, a) MLPs evaluated in one batched pass; LayerNorm after every hidden layer keeps
        Q-values bounded when updating many times per environment step on a mix of prior and online data.
"""
import math

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

LOG_STD_MIN, LOG_STD_MAX = -20.0, 2.0
ACT_DIM = 2


def xavier(layer):
    nn.init.xavier_uniform_(layer.weight)
    nn.init.zeros_(layer.bias)
    return layer


class Actor(nn.Module):
    def __init__(self, obs_dim, hidden_dims=(256, 256)):
        super().__init__()
        layers, last = [], obs_dim
        for width in hidden_dims:
            layers += [xavier(nn.Linear(last, width)), nn.ReLU()]
            last = width
        self.trunk = nn.Sequential(*layers)
        self.mean = xavier(nn.Linear(last, ACT_DIM))
        self.log_std = xavier(nn.Linear(last, ACT_DIM))

    def forward(self, obs):
        z = self.trunk(obs)
        return self.mean(z), self.log_std(z).clamp(LOG_STD_MIN, LOG_STD_MAX)

    def sample(self, obs, generator=None):
        """Reparameterized action in (-1, 1) and its log-probability."""
        mean, log_std = self(obs)
        noise = torch.randn(mean.shape, device=mean.device, generator=generator)
        u = mean + log_std.exp() * noise
        log_prob = (-0.5 * noise ** 2 - log_std - 0.5 * math.log(2 * math.pi)).sum(-1)
        log_prob = log_prob - (2 * (math.log(2) - u - F.softplus(-2 * u))).sum(-1)  # tanh change of variables
        return torch.tanh(u), log_prob

    def mean_action(self, obs):
        return torch.tanh(self(obs)[0])

    @torch.no_grad()
    def predict(self, obs, deterministic=True, generator=None):
        tensor = torch.as_tensor(obs, dtype=torch.float32, device=self.mean.weight.device).unsqueeze(0)
        action = self.mean_action(tensor) if deterministic else self.sample(tensor, generator)[0]
        return action[0].cpu().numpy().astype(np.float32)


class EnsembleLinear(nn.Module):
    def __init__(self, members, in_dim, out_dim):
        super().__init__()
        weight = torch.empty(members, out_dim, in_dim)
        for member in weight:
            nn.init.xavier_uniform_(member)
        self.weight = nn.Parameter(weight.transpose(1, 2).contiguous())
        self.bias = nn.Parameter(torch.zeros(members, 1, out_dim))

    def forward(self, x):  # (E, B, in) -> (E, B, out)
        return torch.baddbmm(self.bias, x, self.weight)


class CriticEnsemble(nn.Module):
    def __init__(self, obs_dim, hidden_dims=(256, 256), num_qs=10, layer_norm=True):
        super().__init__()
        self.num_qs, self.layer_norm = num_qs, layer_norm
        sizes = [obs_dim + ACT_DIM, *hidden_dims]
        self.hidden = nn.ModuleList(EnsembleLinear(num_qs, a, b) for a, b in zip(sizes, sizes[1:]))
        self.gain = nn.ParameterList(nn.Parameter(torch.ones(num_qs, 1, b)) for b in sizes[1:])
        self.shift = nn.ParameterList(nn.Parameter(torch.zeros(num_qs, 1, b)) for b in sizes[1:])
        self.out = EnsembleLinear(num_qs, sizes[-1], 1)

    def forward(self, obs, action, members=None):
        """Q-values (E, B); `members` selects a subset of the ensemble."""
        x = torch.cat([obs, action], -1)
        index = slice(None) if members is None else members
        x = x.unsqueeze(0).expand(self.num_qs if members is None else len(members), *x.shape)
        for layer, gain, shift in zip(self.hidden, self.gain, self.shift):
            x = torch.baddbmm(layer.bias[index], x, layer.weight[index])
            if self.layer_norm:
                x = F.layer_norm(x, x.shape[-1:]) * gain[index] + shift[index]
            x = F.relu(x)
        return torch.baddbmm(self.out.bias[index], x, self.out.weight[index]).squeeze(-1)
