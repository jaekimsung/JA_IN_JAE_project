"""Transition stores for RLPD: the prior (expert) data and the online replay buffer.

Both are read from dataset shards (`numeric.npz`), so the online replay buffer of a resumed run is rebuilt
from the transitions the run already committed instead of being checkpointed separately.
"""
from pathlib import Path

import numpy as np

from kcity.data.dataset import shard_directories
from kcity.data.pool import pool_parts
from kcity.env.observation import OBS_DIM

KEYS = ('observation', 'action', 'reward', 'next_observation', 'mask')


class TransitionStore:
    """Fixed-capacity arrays of (s, a, r, s', mask); mask = 0 only when the Episode truly terminated."""

    def __init__(self, capacity):
        self.capacity, self.size = capacity, 0
        self.data = dict(
            observation=np.zeros((capacity, OBS_DIM), np.float32), action=np.zeros((capacity, 2), np.float32),
            reward=np.zeros(capacity, np.float32), next_observation=np.zeros((capacity, OBS_DIM), np.float32),
            mask=np.zeros(capacity, np.float32))

    def __len__(self):
        return self.size

    def add(self, observation, action, reward, next_observation, terminated):
        if self.size >= self.capacity:
            raise ValueError('Transition store is full')
        row = (observation, np.clip(action, -1, 1), reward, next_observation, 0.0 if terminated else 1.0)
        for key, value in zip(KEYS, row):
            self.data[key][self.size] = value
        self.size += 1

    def extend(self, arrays):
        n = len(arrays['reward'])
        if self.size + n > self.capacity:
            raise ValueError('Transition store is full')
        for key in KEYS:
            self.data[key][self.size:self.size + n] = arrays[key]
        self.size += n

    def sample(self, n, rng):
        if not self.size:
            raise ValueError('Cannot sample an empty transition store')
        index = rng.integers(0, self.size, n)
        return {key: self.data[key][index] for key in KEYS}


def shard_arrays(folder, split=None):
    """RL view of one shard. Actions are the clipped values the environment executed."""
    with np.load(Path(folder) / 'numeric.npz', allow_pickle=False) as a:
        keep = np.ones(len(a['reward']), bool) if split is None else a['data_split'] == split
        return dict(observation=a['observation'][keep], action=np.clip(a['action_raw'][keep], -1, 1), reward=a['reward'][keep],
                    next_observation=a['next_observation'][keep], mask=1.0 - a['terminated'][keep].astype(np.float32))


def load_store(folders, capacity, split=None):
    store = TransitionStore(capacity)
    for folder in folders:
        arrays = shard_arrays(folder, split)
        room = capacity - len(store)
        if room <= 0:
            break
        store.extend({k: v[:room] for k, v in arrays.items()})
    return store


def load_prior(pool, limit):
    """First `limit` expert_train transitions of an expert pool (all Episodes, including failures)."""
    folders = [folder for part in pool_parts(pool) for folder in shard_directories(part)]
    store = load_store(folders, limit, 'expert_train')
    if not len(store):
        raise ValueError('Expert pool has no expert_train transitions')
    return store
