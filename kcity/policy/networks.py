"""K-CITY 정책망 부품: 범용 MLP 빌더와 하이브리드 actor-critic 몸체.

`kcity.policy.policy.KCityPolicy`가 HybridActorCritic을 상속해 관측 mask,
샘플링, 로그확률·엔트로피 계산을 정의한다. 파라미터 생성 순서(trunk → mu_head →
lane_head → v_head → log_std)는 seed별 초기 가중치를 결정하므로 바꾸지 않는다.
"""
import numpy as np
import torch
import torch.nn as nn


def build_mlp(in_dim: int, hidden_sizes, out_dim: int = None,
              activation: str = "tanh") -> nn.Sequential:
    """[in_dim] → hidden_sizes → (out_dim) 형태의 MLP를 만든다.

    Args:
        in_dim:        입력 차원
        hidden_sizes:  은닉층 크기 리스트. 예: [64, 64]
        out_dim:       출력 차원. None이면 마지막 은닉층까지만 만든다
                       (= 여러 head가 공유하는 "몸통/트렁크"로 쓸 때)
        activation:    "tanh" | "relu" | "elu"
                       tanh는 소규모 RL에서 관례적으로 안정적이고,
                       relu는 층이 깊거나 큰 문제에서 유리한 경향.

    Returns:
        nn.Sequential. 마지막 층은 활성함수 없음 (out_dim을 준 경우).
    """
    act_layer = {"tanh": nn.Tanh, "relu": nn.ReLU, "elu": nn.ELU}[activation]

    layers, last = [], in_dim
    for h in hidden_sizes:
        layers += [nn.Linear(last, h), act_layer()]
        last = h
    if out_dim is not None:
        layers.append(nn.Linear(last, out_dim))   # 출력층엔 활성함수 X
    return nn.Sequential(*layers)


def orthogonal_init(module: nn.Module, gain: float = 1.0):
    """직교 초기화 — PPO 논문 계열 구현에서 표준으로 쓰이는 초기화.

    policy head는 작은 gain(0.01)으로 초기화해서 학습 초기에
    모든 행동이 거의 균등하게 나오도록 만드는 것이 관례다
    (특정 행동으로 성급하게 쏠리는 것을 방지).
    """
    if isinstance(module, nn.Linear):
        nn.init.orthogonal_(module.weight, gain=gain)
        nn.init.constant_(module.bias, 0.0)
    return module


# ======================================================================
# 하이브리드 Actor-Critic: 연속 가감속(Normal) + 이산 차선변경(Categorical 좌/유지/우)
#   action = [가감속 실수, 차선명령(+1/0/-1)],  log π = log N(가감속) + log Cat(차선)
# ======================================================================
class HybridActorCritic(nn.Module):
    # 차선 인덱스 ↔ 명령 매핑: 0=왼쪽(+1), 1=유지(0), 2=오른쪽(-1)
    LANE_CMDS = (1.0, 0.0, -1.0)

    def __init__(self, obs_dim: int, hidden_sizes=(64, 64),
                 activation: str = "tanh", init_log_std=-0.5,
                 lane_keep_bias: float = 1.0):
        """
        Args:
            init_log_std: "가감속" 축의 초기 탐험 폭 σ = exp(·).
                (시퀀스가 오면 첫 원소를 사용 — Gaussian 정책과의 호환용)
            lane_keep_bias: 차선 head의 "유지" 로짓 초기 편향.
                1.0 → 초기 확률 약 (좌 16%, 유지 68%, 우 16%)
                    = 스텝당 ~32%가 변경 시도 (탐험 충분 + 과폭주 방지)
                0.0 → 균등 1/3씩 (~67% 시도), 2.0 → ~14% 시도
        """
        super().__init__()
        self.trunk = build_mlp(obs_dim, hidden_sizes, None, activation)
        last = hidden_sizes[-1]
        self.mu_head = orthogonal_init(nn.Linear(last, 1), gain=0.01)
        self.lane_head = orthogonal_init(nn.Linear(last, 3), gain=0.01)
        self.v_head = orthogonal_init(nn.Linear(last, 1), gain=1.0)
        with torch.no_grad():
            self.lane_head.bias[1] = lane_keep_bias   # "유지"를 기본값으로

        if not np.isscalar(init_log_std):
            init_log_std = float(init_log_std[0])
        self.log_std = nn.Parameter(torch.ones(1) * float(init_log_std))

    def forward(self, obs):
        z = self.trunk(obs)
        mu = torch.tanh(self.mu_head(z))          # 가감속 평균 ∈ [-1,1]
        std = torch.exp(self.log_std)
        lane_logits = self.lane_head(z)
        return mu, std, lane_logits, self.v_head(z).squeeze(-1)
