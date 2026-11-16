# 정책과 학습 알고리즘

네 가지 방법을 같은 환경·관측·정책 구조에서 비교합니다. 알고리즘은 [policy/](../kcity/policy), 학습 루프는 [training/](../kcity/training), 설정값은 [experiment.json](../configs/kcity/experiment.json)에 있습니다.

| 방법 | 내용 |
|---|---|
| **B0** 규칙 전문가 | 73차원 관측만 보는 결정적 규칙. 앞차 추종(IDM 형태), 적·황 신호 정지, 경로상 필요한 차선 변경(앞뒤 간격 확인), 정지 규칙 접근 ([rule_expert.py](../kcity/policy/rule_expert.py)) |
| **B1** BC | B0 데이터를 지도학습한 정책. 검증 손실이 가장 낮은 checkpoint 선택 |
| **B2** PPO | 무작위 초기화에서 PPO로 학습 |
| **B3** BC → PPO | 같은 seed의 B1 actor로 초기화한 뒤 PPO로 학습 |

B3는 BC와 PPO 손실을 섞는 방식이 아닙니다. 초기 가중치만 BC에서 가져옵니다.

## 정책망

[networks.py](../kcity/policy/networks.py), [policy.py](../kcity/policy/policy.py)

```text
관측 73 → [256, ReLU] → [256, ReLU] (공유 trunk) ─┬─ 가속 head: tanh(μ)       → Normal(μ, σ)
                                                ├─ 차선 head: 3 logits + mask → Categorical(좌/유지/우)
                                                └─ 가치 head: V(s)
σ = exp(log_std), 초기 log_std = −0.5 (σ ≈ 0.61), 차선 "유지" 초기 편향 0.5
파라미터 86,022개 (BC 학습 대상 85,764개)
```

- 로그확률과 엔트로피는 가속(Normal)과 차선(Categorical)의 값을 더합니다.
- 차선 mask는 관측에서 계산하며, 행동을 저장할 때의 mask와 같은지 매번 검사합니다.
- 평가에서는 결정적으로 행동합니다. 가속은 μ, 차선은 argmax입니다.

## PPO (B2, B3)

[policy/ppo.py](../kcity/policy/ppo.py), [policy/buffer.py](../kcity/policy/buffer.py), [training/ppo.py](../kcity/training/ppo.py)

| 항목 | 값 |
|---|---|
| rollout | 2,048 전이 (50k 평가 경계에서는 짧게 자름) |
| 업데이트 | 10 epoch × minibatch 64, Adam lr 1e-4(고정), gradient clip 0.5 |
| 목적함수 | clipped surrogate(ε 0.2) + 0.5·value MSE − 0.01·차선 head 엔트로피 |
| advantage | GAE(γ 0.99, λ 0.95), rollout 단위 정규화 |
| 예산 | 방법·seed마다 정확히 1,000,000 전이, seed 11·22·33 |
| 평가 | 50k 전이마다 dev 패널 100 사례(결정적) |
| 최종 모델 | 1M 시점 모델(budget-end). dev 최고 모델은 보조 기록 |

GAE는 종료(`terminated`)와 잘림(`truncated`)을 구분합니다. 종료는 bootstrap을 0으로 두고, 잘림은 다음 상태 가치로 bootstrap하되 trace는 끊습니다. 각 전이에는 수집 시점 정책의 V(다음 관측)을 함께 저장합니다.

**B3 초기화:** BC actor의 trunk, 가속 head, 차선 head를 복사합니다. 가치 head, σ, optimizer는 새로 시작합니다. 공유 trunk가 이후 PPO에서 바뀌는 것도 사전학습 효과에 포함해서 해석합니다.

**재현성:** 정책 초기화, 행동 샘플링(`torch.Generator`), minibatch 셔플(`RandomState`)이 각각 학습 seed에서 분리되어 있습니다. 평가는 이 난수들을 소비하지 않습니다. 교통 seed는 사례마다 정해져 있어 B2와 B3가 같은 사례 순서로 학습합니다.

## BC (B1)

[policy/bc.py](../kcity/policy/bc.py), [training/bc.py](../kcity/training/bc.py)

- **데이터:** B0 pool에서 정상 완주하고, 규칙 판정을 통과하고, 신호 판정 불가가 없는 Episode만 사용합니다. train 200k / val 50k 행을 seed 20261115로 한 번 비복원 추출해 고정하고, 세 seed가 같은 view를 씁니다.
- **손실:** 가속 MSE(μ와 전문가 가속) + 차선 Cross-Entropy입니다. 가중치는 1:1이며, 가치 head와 σ는 학습하지 않습니다.
- **학습:** batch 256, 10,000 update, Adam lr 3e-4입니다. 500 update마다 val 손실을 계산해 가장 낮은 checkpoint를 선택합니다(동률이면 먼저 나온 것).

## 학습 상태 저장과 재개

[policy/checkpoint.py](../kcity/policy/checkpoint.py)

- **bundle 구성:** 가중치, optimizer, 난수 상태, 진행 중인 rollout buffer, 환경 재개 정보를 하나의 폴더(bundle)에 SHA256 목록과 함께 저장합니다. bundle은 임시 폴더에 쓴 뒤 rename으로 확정합니다.
- **데이터와 함께 확정:** PPO는 rollout을 마칠 때마다 learner bundle을 먼저 확정하고, 그 다음에 같은 전이의 데이터 shard를 확정합니다. 그래서 중단 후 재개해도 데이터 수와 학습 카운터가 일치합니다.
- **환경 재개:** 현재 Episode를 같은 행동으로 다시 실행해 SUMO 상태를 복원하고, 저장된 State와 정확히 같은지 확인합니다.
- **보관 정책:** PPO는 최신·직전·50k 경계 bundle만 남깁니다. BC는 최신·직전·best를 남깁니다.

## 알려진 위험

- **필수 차선 변경 실패:** 전문가 데이터에서 차선 변경 비율이 매우 낮습니다(유지가 대부분). 그래서 BC가 "유지"로 쏠리기 쉽고, 결정적 평가(argmax)에서 필수 차선 변경을 놓칠 수 있습니다.
- **B3의 trunk 교란:** critic이 새로 시작하므로 초기 value 손실의 gradient가 BC로 학습된 공유 trunk를 바꿀 수 있습니다.
- **보상 스케일:** 매 결정의 진행 보상(약 0.01~0.1)이 종료 보상(±10~20)보다 훨씬 작고, return은 정규화하지 않습니다.
