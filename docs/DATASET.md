# 주행 데이터셋

POMDP 전이(transition) 단위로 저장합니다. 전이 하나에는 정책이 본 73차원 관측, 행동, 보상, 종료 여부, 그리고 **행동 전후의 SUMO 전체 State**가 함께 들어 있습니다. 형식은 `KC-DATA-v1`(관측 `KC-OBS73-v1`)이며, 코드는 [data/](../data/)에 있습니다.

## 데이터 원천

| 원천 | 규모 | 생성 |
|---|---|---|
| 전문가(B0) pool | 최소 1M 전이 | `runner/collect.py` (병렬 워커) |
| PPO 학습 전이 | B2·B3 × 3 seed × 1M = 6M | `runner/train_ppo.py`가 학습하면서 기록 |
| 최종 정책 주행 | 1M 시점 PPO 정책 6개 × 500k = 3M | `runner/collect.py --policy <bundle>` (병렬 워커, 결정적 행동) |

합계 목표는 10^7 전이 이상입니다. 성공, 실패, 판정 불가 Episode를 모두 저장하며, 걸러내는 작업은 BC view를 만들 때만 합니다.

## 전이 필드

수업 기본 수집 항목은 모두 포함되어 있습니다.

| 필드 | 형태 | 의미 |
|---|---|---|
| `episode`, `t` | int | Episode 번호, Episode 안의 결정 순서(0.5초 단위) |
| `observation`, `next_observation` | float32[73] | 정책 관측 o_t, o_{t+1} ([관측 표](ENVIRONMENT.md#관측-73차원--1-1)) |
| `action_raw` | float[2] | 정책 출력 [가속, 차선] (clip 전) |
| `action` | dict | `accel_raw`, `lane_change_raw`, `lane_change`(−1/0/+1), `lane_change_applied`, `lane_change_executed`, 요청 가속도(m/s²), 실측 평균 가속도, 차선 mask, 거부 사유 |
| `reward`, `reward_components` | float, dict | 보상과 항목별 값(진행·도착·충돌·적색·무효요청·차선변경) |
| `terminated`, `truncated`, `end_reason` | bool, str | 종료 여부와 종료 원인 |
| `state`, `next_state` | dict | s_t, s_{t+1}: 모든 차량의 위치(m)·속도(m/s)·가속·각도·차선·도로·종류, AV의 경로 진행도·목적지, 신호 14곳 상태, HV 수·대기 수·최근 60초 투입량 |
| `detected_vehicles` | list | 관측 시점에 AV 주변으로 감지된 차량(같은 차로·인접 차로·교차 관계, 상대 위치·속도) |
| `event` | dict | `collided`, `arrived`, `lane_before`, `lane_after` |
| `events`, `substep_samples` | list | 0.1초 단위 이벤트(차선변경·충돌·신호 통과·도착)와 속도·선행차 간격·HV 수 |
| 식별·출처 | str | `run_uid`, `case_uid`, `episode_uid`, `transition_uid`, `data_split`, `scenario_id`, `policy_id`(B0~B3), `train_seed`, 행동한 정책 가중치 hash |
| `learning` (PPO만) | dict | 행동 당시 log π, V(s), V(s'), update 번호 |

## 저장 구조

```text
<pool>/POOL.json                       part 목록·합계·pool_id
<pool>/part-XX/dataset/
  RUN.json                             수집 설정(환경 계약, 사례 계획, 전문가 설정, 맵 파일 SHA, git commit)
  RELEASE.json                         확정된 shard 목록, 고유 전이 수, data_id
  shards/shard-XXXXXX/
    transitions.jsonl.gz               전이 원본 (기준 데이터)
    numeric.npz                        같은 전이의 고정 크기 배열
    events.jsonl.gz                    0.1초 단위 이벤트
    SHARD.json                         파일별 SHA256, split별 행 수, 완료 Episode 요약
    collector.json, environment/       재개 정보 (공개 데이터에는 포함하지 않음)
```

- **NPZ 배열:** `observation`, `next_observation`, `action_raw`, `action_env_input`, `action_mask`, `lane_change`, `reward`, `terminated`, `truncated`, `episode`, `t`, `detected_xy`, `detected_offsets`, UID·split 등이 들어 있어 NumPy/PyTorch에서 바로 쓸 수 있습니다.
- **next 참조 압축:** JSONL은 `next_state`·`next_observation`이 바로 다음 행과 같으면 그 행의 UID(`next_reference`)만 저장합니다. 읽을 때 원래 값으로 복원되므로 정보 손실은 없습니다.
- **용량:** 전이당 약 2.0~2.3KB이며, 10M이면 약 21~23GB입니다.

## 수집 방식

1. **사례 계획:** 시나리오를 A/A/A/B/B/B/C/C/C/C로 반복합니다. 시나리오별 순번 5개 중 1개(`j % 5 == 4`)를 `expert_val`, 나머지를 `expert_train`으로 미리 정합니다. 같은 Episode와 교통 seed 묶음은 한 split에만 들어갑니다.
2. **최종 정책 수집:** 학습된 정책(BC·PPO bundle)으로 수집할 때는 학습·평가와 겹치지 않는 `archive` namespace 사례를 씁니다. 행동은 결정적이며, 행마다 정책 이름(B1~B3)·학습 seed·가중치 hash를 기록하고 검증합니다. 이 데이터는 BC view에 들어가지 않습니다.
3. **병렬 수집:** 사례 계획을 10개 사례 주기 단위로 워커 N개에 번갈아 나눕니다. 각 워커는 자기 SUMO와 기록기로 `ceil(목표/N)` 전이를 채우고 진행 중인 Episode까지 마칩니다. 모든 part가 같은 시나리오 구성을 갖고, 사례마다 교통 seed와 split이 고정되어 있습니다.
4. **기록:** 결정마다 전이를 검증해 journal에 쓰고, 512행마다(PPO는 rollout마다) shard로 확정합니다. 확정은 임시 폴더 rename이라 중단돼도 반쯤 쓴 shard는 데이터로 세지 않습니다.
5. **중단·재개:** `STOP` 파일이나 SIGINT/SIGTERM이 오면 저장 후 종료합니다. 재개하면 확정 지점부터 이어가고, 확정되지 않은 journal은 `quarantine/`으로 보관합니다.

## 품질 검사

- **행 단위(기록할 때마다):** 관측 범위와 이진 필드, raw → clip 변환, 차선 mask와 관측의 일치, 보상 합계, State의 시각 정렬, 감지 차량이 State에 실제로 있는지, 충돌·도착 이벤트의 일관성, substep 수, NaN 여부.
- **연속성:** 같은 Episode 안에서 이전 행의 `next_*`가 다음 행의 현재 값과 같아야 합니다. Episode는 종료 행 다음에만 바뀝니다.
- **전체:** JSONL과 NPZ의 일치, 이벤트 파일, 행 수, 원시 이벤트에서 다시 계산한 Episode 요약 일치, part 사이 사례·Episode 중복 여부.

## BC view와 공개

- **BC view:** `runner/train_bc.py views`는 pool 전체에서 성공 Episode만 골라 train 200k / val 50k를 고정 seed로 추출합니다([ALGORITHMS.md](ALGORITHMS.md#bc-b1)).
- **HF 공개:** `runner/export_hf.py`는 검증한 shard의 데이터 파일, dataset card(`README.md`), 독립 reader(`load_kcity.py`, numpy만 필요)를 Hugging Face용 폴더로 만듭니다. 업로드는 직접 합니다.
