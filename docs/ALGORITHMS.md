# 정책과 학습 알고리즘

같은 환경·관측·행동에서 네 가지를 비교합니다. 알고리즘은 [policy/](../kcity/policy), 학습 루프는 [training/](../kcity/training), 설정값은 [experiment.json](../configs/kcity/experiment.json)에 있습니다.

| 방법 | 내용 |
|---|---|
| **B0** 규칙 전문가 | 사전 데이터를 만드는 결정적 규칙 정책 ([rule_expert.py](../kcity/policy/rule_expert.py)). 주행 중인 AV를 돕는 데는 쓰지 않음 |
| **B1** BC | B0 데이터를 지도학습한 정책. 검증 손실이 가장 낮은 checkpoint 선택 |
| **B2** 온라인 SAC | 사전 데이터 없이 환경 경험만으로 학습 (B3와 같은 학습기, 사전 데이터 비율 0) |
| **B3** RLPD | 매 batch의 절반을 전문가 사전 데이터로 채워 학습 |

B1은 전문가 데이터만 쓰고, B2는 환경 경험만 쓰고, B3는 둘 다 씁니다. B1과 B3의 차이가 "BC의 한계를 강화학습이 메우는가"에 대한 답이고, B2와 B3의 차이가 "사전 데이터가 표본 효율을 높이는가"에 대한 답입니다.

## 규칙 전문가 (B0)

B0는 사전 데이터(BC 학습 데이터와 RLPD의 prior data)를 만드는 정책이며, B1~B3가 주행할 때는 어떤 형태로도 개입하지 않습니다. 학습 정책과 똑같이 63차원 관측만 보며, SUMO 내부 정보·전체 State·경로 차선 정보는 쓰지 않습니다.

| 규칙 | 내용 |
|---|---|
| 추종 | 현재 차로 앞차에 대한 IDM 형태의 간격 유지. 최대 감속으로 앞차 뒤에 설 수 있는 속도를 넘지 않음 (SUMO가 간격을 지켜 주지 않음) |
| 신호 | 적색이면 정지선 2m 앞에 정지. 황색이면 최대 감속으로도 정지선 전에 설 수 없을 때만 통과 |
| 출구 막힘 | 앞차가 교차로 바로 너머에 서 있으면 교차로에 들어가지 않음 |
| 차로 감소 | 현재 차로가 끝나면(관측 62) 옆 차로의 앞·뒤 간격이 충분할 때 차선 변경을 요청하고, 아니면 차로 끝에서 대기 |
| 양보 | 양보 표지가 있으면, 다른 진입로의 차량이 교차로 안에 있거나 AV가 지나가기 전에 도착할 것 같을 때 진입 전 정지. 자기 정지선에 서 있는 차량은 기다리는 중으로 보고 무시 |

## 정책망

[networks.py](../kcity/policy/networks.py)

```text
Actor    관측 63 → [256, ReLU] → [256, ReLU] → 평균 μ(2), log σ(2) → a = tanh(u), u ~ Normal(μ, σ)
Critic   (관측 63, 행동 2) → [256, LayerNorm, ReLU] × 2 → Q   × 10개 (서로 독립인 ensemble)
```

- 행동은 `[가속, 차선 명령]` 연속값입니다. 평가에서는 `tanh(μ)`로 결정적으로 행동합니다.
- BC와 RLPD가 같은 Actor 구조를 씁니다.

## BC (B1)

[policy/bc.py](../kcity/policy/bc.py), [training/bc.py](../kcity/training/bc.py)

- **데이터:** 전문가 pool에서 규칙 준수 완주 Episode의 전이만 골라 학습 20만·검증 5만 행을 고정합니다. 사례 단위로 학습·검증을 나눕니다.
- **손실:** 결정적 행동 `tanh(μ)`와 전문가 행동의 MSE(가속 + 차선 명령).
- **학습:** Adam lr 3e-4, batch 256, 20,000 update, 1,000 update마다 검증.

## RLPD (B2, B3)

[policy/rlpd.py](../kcity/policy/rlpd.py), [data/replay.py](../kcity/data/replay.py), [training/rl.py](../kcity/training/rl.py)

RLPD(Reinforcement Learning with Prior Data, Ball et al. 2023)는 SAC에 세 가지를 더해 사전 데이터를 온라인 학습에 그대로 쓰는 방법입니다. [공개 구현](https://github.com/ikostrikov/rlpd)의 구조와 기본값을 따랐습니다.

| 요소 | 내용 | 값 |
|---|---|---|
| 대칭 표본 추출 | 매 batch를 사전 데이터와 온라인 데이터로 나눠 채움 | 사전 50% (B2는 0%) |
| LayerNorm critic | 사전 데이터에 없는 행동에서 Q값이 과대 외삽되는 것을 억제 | 사용 |
| 큰 ensemble + 높은 UTD | critic 10개, target은 임의의 2개 중 최솟값, 환경 1 step마다 critic 20회 update | 10 / 2 / 20 |

```text
target = r + γ·mask·( min_{i∈임의 2개} Q̄_i(s', a') − α·log π(a'|s') ),   a' ~ π(·|s')
critic 손실 = 평균_i (Q_i(s, a) − target)²
actor 손실  = E[ α·log π(a|s) − 평균_i Q_i(s, a) ]        (step마다 1회)
α 손실      = α·(H[π] − 목표 엔트로피),   목표 엔트로피 = −|A|/2 = −1
```

| 항목 | 값 |
|---|---|
| 학습률 | actor·critic·α 모두 3e-4 (Adam) |
| γ, τ | 0.99, 0.005 |
| batch | 256 × UTD 20 |
| 초기 α | 1.0 |
| 초기 탐색 | 처음 5,000 step은 균등 무작위 행동, update 없음 |
| `mask` | 종료(`terminated`)에서만 0. 기한 초과도 종료이며 남은 시간이 관측에 있음 |
| 예산 | 방법·seed마다 300,000 전이, seed 11·22·33 |
| 평가 | 25,000 전이마다 dev 패널 100 사례(결정적) |

**이 프로젝트에 맞춘 부분**

- **사전 데이터:** 전문가 pool의 `expert_train` 전이 100만 개(실패 Episode 포함). 행동은 환경이 실제로 실행한 clip된 값을 씁니다.
- **replay buffer = 기록된 데이터:** 온라인 전이는 모두 데이터셋 형식으로 저장되고, 재개할 때 replay buffer는 확정된 shard에서 다시 만듭니다. buffer를 따로 checkpoint하지 않습니다.
- **재현성:** 초기화, 행동 샘플링, batch 추출이 학습 seed에서 정해지고, 학습 상태와 함께 저장됩니다.

## checkpoint와 재개

[policy/checkpoint.py](../kcity/policy/checkpoint.py), [data/storage.py](../kcity/data/storage.py)

- **bundle:** 학습 상태(`training.pt`), 설정(`metadata.json`), 환경 재개 정보(`environment/`), 파일별 SHA256(`SHA256.json`)을 한 폴더로 원자적으로 씁니다.
- **데이터와 함께 확정:** 5,000 전이마다 learner bundle을 먼저 확정하고, 그 다음에 같은 전이의 데이터 shard를 확정합니다. 그래서 재개해도 데이터 수와 학습 카운터가 일치합니다.
- **환경 재개:** 진행 중인 Episode는 같은 사례를 처음부터 저장된 행동으로 다시 실행해 복원합니다.
- **보관 정책:** RL은 최신·직전·평가 경계 bundle만 남깁니다. BC는 최신·직전·best를 남깁니다.
