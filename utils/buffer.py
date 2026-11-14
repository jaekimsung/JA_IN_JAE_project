"""경험 버퍼 모음.

강화학습 알고리즘은 크게 두 부류이고, 쓰는 버퍼도 다르다:

  · on-policy  (PPO, A2C, ...)  → RolloutBuffer
      "지금 정책"으로 모은 경험만 쓸 수 있다.
      업데이트가 끝나면 데이터를 전부 버리고 새로 모은다.

  · off-policy (DQN, SAC, ...)  → ReplayBuffer
      과거 정책이 모은 경험도 재사용할 수 있다.
      큰 순환 버퍼에 계속 쌓아두고 무작위로 뽑아 학습한다.

버퍼를 utils/로 분리한 이유: 버퍼는 알고리즘의 "부품"이지 본체가 아니다.
train.py(메인)에서 버퍼를 만들어 에이전트에 주입(dependency injection)하면,
- 어떤 버퍼를 쓰는지가 메인에서 한눈에 보이고
- 나중에 버퍼를 바꾸거나(예: 우선순위 리플레이) 다른 알고리즘을 붙일 때
  알고리즘 코드를 열지 않아도 된다.
"""
import random
from collections import deque

import numpy as np
import torch


# ======================================================================
# On-policy용: RolloutBuffer  (PPO가 사용)
# ======================================================================
class RolloutBuffer:
    """한 번의 rollout(n_steps) 동안의 경험을 담아두는 버퍼.

    PPO는 on-policy 알고리즘이라, 업데이트 후에는 이 데이터를 버리고
    새 정책으로 다시 수집한다 (ReplayBuffer처럼 오래 쌓아두지 않는다).

    저장하는 것: obs/action/log_prob/raw reward/value/terminated/truncated/next_value
        log_prob : 그 행동을 뽑을 당시의 log π_old(a|s).
                   PPO의 확률비 r(θ) 계산에 필요해서 함께 저장한다.
        value    : 그 상태의 V(s) 추정치. GAE 계산에 필요.
    """

    def __init__(self):
        self.clear()

    def clear(self):
        self.obs, self.actions, self.log_probs = [], [], []
        self.rewards, self.values, self.dones = [], [], []
        self.truncated, self.next_values = [], []
        self.action_masks = []
        self.bootstrap_masks, self.trace_masks = [], []

    def add(self, obs, action, log_prob, reward, value, done=None, *,
            terminated=None, truncated=False, next_value=None, action_mask=None):
        """Store the raw reward and separate bootstrap/trace boundaries.

        The old positional ``done`` means termination only. New collectors must
        supply both flags and V(actual next observation), before reset. A
        truncation without that next value is rejected rather than guessed.
        """
        if terminated is None:
            if done is None:
                raise ValueError("Supply terminated (or legacy done)")
            terminated = bool(done)
        elif done is not None and bool(done) != bool(terminated):
            raise ValueError("done and terminated disagree")
        if truncated and not terminated and next_value is None:
            raise ValueError("Truncation requires terminal-observation next_value")
        for scalar in [log_prob, reward, value] + ([] if next_value is None else [next_value]):
            if not np.isfinite(scalar):
                raise ValueError("Rollout scalars must be finite")
        if action_mask is not None:
            mask = np.asarray(action_mask)
            if mask.shape != (3,) or not np.isin(mask, [0,1]).all() or not mask[1]:
                raise ValueError("Lane mask must be a boolean three-vector allowing keep")
            action_mask = mask.astype(bool).tolist()
        self.action_masks.append(action_mask)
        self.obs.append(np.array(obs, dtype=np.float32, copy=True))
        self.actions.append(np.array(action, dtype=np.float32, copy=True))
        self.log_probs.append(float(log_prob))
        self.rewards.append(float(reward))
        self.values.append(float(value))
        self.dones.append(float(bool(terminated)))
        self.truncated.append(bool(truncated))
        self.next_values.append(None if next_value is None else float(next_value))
        self.bootstrap_masks.append(float(not terminated))
        self.trace_masks.append(float(not (terminated or truncated)))

    def __len__(self):
        return len(self.rewards)

    def compute_gae(self, last_value: float, gamma: float, gae_lambda: float):
        """delta=r+gamma*bootstrap*V(next)-V; A=delta+gamma*lambda*trace*A(next).

        Termination: bootstrap=0, trace=0. Truncation: bootstrap=1, trace=0.
        A rollout cut bootstraps but does not cross into an uncollected segment.
        Legacy non-truncated transitions may infer next V from the next row or
        last_value. Explicit next_values always take precedence.
        """
        if not all(np.isfinite(x) and 0 <= x <= 1 for x in [gamma, gae_lambda]):
            raise ValueError("gamma and gae_lambda must be in [0,1]")
        if not np.isfinite(last_value):
            raise ValueError("last_value must be finite")
        values = np.asarray(self.values, dtype=np.float64)
        advantages = np.zeros(len(self), dtype=np.float64)
        gae = 0.0
        for t in reversed(range(len(self))):
            next_value = self.next_values[t]
            if next_value is None:
                next_value = last_value if t == len(self)-1 else values[t+1]
            delta = self.rewards[t] + gamma*self.bootstrap_masks[t]*next_value - values[t]
            gae = delta + gamma*gae_lambda*self.trace_masks[t]*gae
            advantages[t] = gae
        return advantages.astype(np.float32), (advantages+values).astype(np.float32)

    def to_tensors(self, device):
        """(obs, actions, old_log_probs)를 학습용 텐서로 변환."""
        return (
            torch.as_tensor(np.asarray(self.obs, dtype=np.float32), device=device),
            torch.as_tensor(np.asarray(self.actions, dtype=np.float32), device=device),
            torch.as_tensor(np.asarray(self.log_probs, dtype=np.float32), device=device),
        )


# ======================================================================
# Off-policy용: ReplayBuffer  (DQN, SAC 등을 추가할 때 사용)
#
# 현재 PPO는 이 버퍼를 쓰지 않지만, 새 알고리즘을 붙일 때
# 그대로 가져다 쓸 수 있도록 표준형을 만들어둔다.
# ======================================================================
class ReplayBuffer:
    """고정 크기 순환(circular) 경험 버퍼.

    (s, a, r, s', done) 전이를 capacity까지 쌓고, 가득 차면
    가장 오래된 것부터 밀어낸다. sample()로 무작위 미니배치를 뽑는다.
    무작위 샘플링은 연속된 전이 사이의 상관관계를 깨서 학습을 안정화한다.
    """

    def __init__(self, capacity: int = 100_000, seed: int = 0):
        self.buffer = deque(maxlen=capacity)
        self.rng = random.Random(seed)

    def add(self, obs, action, reward, next_obs, done):
        self.buffer.append((obs, action, reward, next_obs, float(done)))

    def __len__(self):
        return len(self.buffer)

    def sample(self, batch_size: int, device=None):
        """무작위 미니배치를 텐서로 반환: (obs, act, rew, next_obs, done)"""
        batch = self.rng.sample(self.buffer, batch_size)
        obs, act, rew, next_obs, done = map(np.asarray, zip(*batch))
        to = lambda x, dt=np.float32: torch.as_tensor(
            np.asarray(x, dtype=dt), device=device)
        return to(obs), to(act), to(rew), to(next_obs), to(done)
