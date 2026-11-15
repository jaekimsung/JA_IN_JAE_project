# KC-03: 종료·GAE·평가 지표 사용 계약

갱신: 2026-11-16. GAE·정확한 전이 예산·독립 평가·사건 기반 지표를 구현하고 pilot/본 운영 계층에 연결했다. **3seed pilot 완료, 본1M 비교·final은 미실행**이다. [현황](RESEARCH_STATUS.md) · [정책/재개](KCITY_POLICY_AND_RESUME.md) · [단계별 검사](research_checks/KC-03-20261114-01/README.md)

## 1. GAE에서 두 경계를 구분

[RolloutBuffer](../utils/buffer.py)는 원래 reward, `terminated`, `truncated`, 실제 next 관측의 value를 저장한다.

```text
bootstrap_mask = 1 - terminated
trace_mask = 1 - (terminated or truncated)
delta[t] = reward[t] + gamma * bootstrap_mask[t] * V(actual_next[t]) - V(obs[t])
A[t] = delta[t] + gamma * lambda * trace_mask[t] * A[t+1]
```

| 경계 | bootstrap | trace | next value |
|---|---:|---:|---|
| 정상 전이 | 1 | 1 | 실제 next 관측 |
| 과제 종료·유한300초 기한 | 0 | 0 | 사용하지 않음 |
| 외부 TimeLimit | 1 | 0 | reset 전 terminal 관측 |
| rollout 끝·전이 예산 끝 | 1 | 수집 조각 밖으로 이어가지 않음 | 현재 과제의 next 관측 |
| terminated+truncated 동시 | 0 | 0 | 종료 우선 |

`add(obs, action, log_prob, reward, value, terminated=..., truncated=..., next_value=...)`를 사용한다. 종전6번째 positional `done`도 termination 의미로 지원하지만, truncation은 명시적으로 지정해야 한다. truncation에 next_value가 없으면 오류다. reward에 bootstrap 값을 더하는 옛 방식과 혼용하지 않는다.

[PPO.collect_rollout](../algorithms/ppo.py)는 reset 전 next value를 계산한다. `final_observation/terminal_observation/final_obs`를 제공하는 same-step autoreset도 처리한다. vector 환경·다른 autoreset mode는 지원을 검증하지 않았다. next 관측이 유효하지 않은 truncation은 오류로 중단하며 가짜 value로 복구하지 않는다.

검사 사례: r=1,V=2,terminal V=4,gamma=.99에서 정답 A=2.96이다. 다음 reset의 V=100이 섞였던 기존 코드는101.96이었다. 수정 후2.96을 확인했다. 기존 성능 로그/모델은 다시 학습한 결과로 바꾸지 않는다.

## 2. 예산·독립 평가·호환성

`collect_rollout(..., max_steps=remaining)`와 `learn(total_timesteps=absolute_target)`가 마지막 rollout을 줄인다. 예산7,n_steps4의 제어 흐름은4+3전이다. 이미 목표에 도달했으면 환경 reset도 하지 않는다. 예산은0.1초 substep 수가 아니라 AV 결정 전이 수다. 마지막 rollout이1행이어도 advantage 정규화가 NaN이 되지 않도록 모집단 표준편차를 사용한다.

정기 평가를 켜려면 `PPO.learn(..., eval_env=independent_env, eval_fn=...)`를 제공한다. 같은 unwrapped 환경이면 시작 전에 거부한다. 평가 후 학습 환경을 reset하지 않으며 Python/NumPy/Torch 정책 RNG를 복원한다. 환경의 독립 connection·seed는 호출자가 보장해야 한다. K-CITY의 인스턴스별 connection은 KC-02에서 검사했다. 공통 masked actor·Runner와 주기 dev 평가는 pilot/본 실행기에 연결했다.

**기존 고속도로 실행기의 호환성 변화:** `train.py`는 global TraCI를 쓰고 기본 `EVAL_INTERVAL=5`다. 이 상태로는 맵 생성/학습 전에 명시적 오류로 중단한다. 기존 고속도로 예제를 사용할 때는 `EVAL_INTERVAL=0`으로 주기 평가를 끄고 저장 정책을 `test.py`로 별도 평가하거나, 연결부터 독립시킨 실행기가 필요하다. 단순히 고속도로 환경 인스턴스를 두 개 만드는 것은 해결책이 아니다. 이번에는 고속도로 주행/재학습을 하지 않았다.

정기 평가 기본 callback은 종전 고속도로 evaluator다. K-CITY에서는 이를 사용하지 말고 아래 case 평가기를 연결해야 한다. 본 CLI는 전용 evaluate_cases와 native Runner를 사용한다. 전체 재개는 native Runner API로 검증했다. 기존 `save/load`는 계속 weights-only다.

## 3. 고정 case panel

[utils/kcity_evaluator.py](../utils/kcity_evaluator.py)의 `make_panel(contract, namespace, counts=None, demand_multiplier=1.0)`은 정책과 독립적으로 case를 생성한다. 기본 A30/B30/C40이며 dev/final namespace를 분리한다. final의1/1.5/2배 수요는 OD/type 기본 seed를 짝짓고 도착 요청 간격을 바꾼다. case UID와 panel SHA를 보관한다.

본 dev100·final수요별100패널은 [main_v1](../configs/kcity/main_v1/README.md)에 동결했다. pilot dev100은 별도의 개발진단 index를 사용했으며 본 final은 아직 실행하지 않았다. KC-03 당시의 contract_check 6회는 공학 검사다. 최종평가 통합 실행·attempt 장부는 후속이다.

## 4. 평가 지표와 불명 값

`evaluate_cases(policy, env, panel, on_transition=...)`는 deterministic `predict(obs,deterministic=True)` 인터페이스를 사용한다. 자동 재시도나 optimizer 호출은 없다. policy에 state_dict가 있으면 전후 hash를 비교하고 변경되면 오류다. 호출자가 소유한 **별도 평가 환경**으로 실행한다. transition callback은 raw trace를 보관할 수 있지만 제출용 shard writer는 아니다.

`EpisodeMetrics`는 info의 사건과0.1초 `substep_samples`를 모아 다음을 기록한다.

- 충돌·도착·적색 진입·이탈·teleport·제거·기한 사실을 독립 보존한다. 대표 종료 순서는 collision→red_entry→wrong_route→teleport→removal→arrival→deadline이다. arrival와collision이 같은 tick이면 도착 사실도 남지만 결합 성공은 false다.
- `completion`: 지정 경로/goal·기한을 충족한 도착. `compliant_completion`: 여기에 충돌·정의된 적색 진입이 없는 경우다. 현재 지원 규칙은 **적색 진입**이며 모든 정지/양보 규칙의 준수를 의미하지 않는다.
- 요청 차선 변경과 실제 lane_change 사건 수를 구분한다. 물리적 진행도는 canonical route 좌표이고 실제 주행거리와 다르다.
- 속도·HV 수·차간거리는 substep dt로 가중한다. 속도를 읽을 수 없는 terminal tick은 누락 시간으로 기록한다. 선행차가 없으면 mean/min gap은 null이며 가시거리 값으로 채우지 않는다. HV departures는 reset 이후 구간만 센다.
- standstill은 speed<0.1 m/s 기준이다. `unjustified_wait_s=null`이며 정당 대기/양보의 인과적 분류는 구현하지 않았다. 보상의 부당 대기 벌점도 계속0이다.
- tick/substep 중복·누락·총시간 정렬을 품질 오류로 표시한다. unknown crossing이 있으면 signal compliance와 결합 성공률을 null로 막는다. 신호 통과0건의 준수율도 null이다.

`aggregate(records,n_planned)`는 원시 분자/분모와 계획/유효/인프라 무효/미확보 수를 함께 출력한다. NaN/잘못된 정책 출력·ego 투입30초 실패·step guard는 성능 실패이며 유효 분모에 남는다. 명시된 소켓/프로세스 통신 오류만 인프라 무효다. 미정의 예외는 전파해 원인을 확인한다. 재시도는 자동으로 하지 않는다.

투입 실패처럼 reset 관측이 없으면 elapsed는 null이며, 관측시간 평균의 별도 분모에서 제외한다. 이는 해당 시도를 성공/유효 분모에서 제외하는 뜻이 아니다. 실패 비용의 보조 지표는 과제 기한300초로 유지한다. 이는 실제 측정 시간이 아니다. duplicate case로 평가 분모를 늘리는 것은 거부한다.

5/100은5%로서 **<5% 조건을 통과하지 않는다**. 낮은 관찰 충돌률만으로 실제 충돌확률의 상한을 입증하지 않는다. Wilson interval·학습 seed별 paired 분석·최종 제출 집계는 후속 분석기에서 추가한다.

## 5. 검사 명령

저장소 루트에서, 출력은 새 디렉터리를 지정한다. 기존 격리 환경을 사용하며 전역 패키지는 변경하지 않았다.

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B -m unittest discover -s tests -p 'test_kcity*.py' -v
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/check_learning.py --output /tmp/kcity-kc03-new-check
```

검사 실행기는 학습 없이 A/B/C×2와 GAE fixture·panel 생성만 수행한다. 산출물은 SUMMARY, PANEL, EPISODES JSON/CSV, AGGREGATE, transition trace, SUMO 경고 로그다. 이 probe는 특권 route 정보를 사용하는 공학 검사이며 연구 B0나 BC/PPO 정책이 아니다. 수집10M 장부에도 합산하지 않는다.

본 설정/목표 동결과 제한된 GPU 운영 preflight는 후속 완료했다. 전체 정지/양보 지표·교통 상호작용 보장·최종 제출 집계는 남아 있다. 과거 작은 검사·pilot을 본1M 성과나 실차 안전 검증으로 확대하지 않는다.
