"""On-policy rollout buffer and GAE(λ) for K-CITY PPO.

PPO는 현재 정책으로 모은 rollout만 쓰고, update가 끝나면 비운다. 종료(terminated)는
bootstrap과 trace를 모두 끊고, 잘림(truncated)은 bootstrap은 유지하되 trace만 끊는다.
"""
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
