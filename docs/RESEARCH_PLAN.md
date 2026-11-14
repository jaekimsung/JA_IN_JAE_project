# K-CITY 후속 연구 계획

[현재 현황](RESEARCH_STATUS.md) · [실험 인덱스](EXPERIMENTS.md) · [작업 요청](../prompts/KCity_Codex_Research_Prompt.md)

2026-11-14 실행 전 상세화: [데이터 컬럼·저장 계약](DATA_COLLECTION_SPEC.md), [수집·학습·평가 프로토콜](EXECUTION_PROTOCOL.md), [결과·컨설팅·제출](RESULTS_AND_CONSULTING.md)을 함께 읽는다. 아래 안정적인 RQ·가설·통제 설계를 유지하고, 필드/명령/예산 장부의 상세 정의는 이 세 문서로 연결한다. 실제 구현·동결 전까지 수치 후보를 실행 완료로 표시하지 않는다.

단계별 실행 승인 후 **KC-01/02 후보 구현·검증을 완료**했다. [설정](../configs/kcity/v1/README.md)·[KC-01](research_checks/KC-01-20261114-01/README.md)·[KC-02 실제 결과](research_checks/KC-02-20261114-01/README.md)·[Gym 사용 안내](KCITY_ENV.md)를 따른다. 73-D·제어·종료는 작은 실행에서 동작했지만 전문가·학습 준비 완료는 아니다. 이어 [KC-03](research_checks/KC-03-20261114-01/README.md)의 GAE·종료·예산·평가 후보 검사를 완료했다. 이어 [KC-04](research_checks/KC-04-20261114-01/README.md)에서 공통 masked actor·초기화·부분 rollout/환경 replay 재개 후보 검사를 완료했다. 이어 [KC-05](research_checks/KC-05-20261114-01/README.md)에서 B0/수집기/loader와602개debug전이·복구를검증했다. 다음은 KC-06의각50k시험학습이며 연구 설정은pilot뒤동결한다.

이 문서는 안정적인 연구 설계다. 실제 진행과 설계 변경 이유는 현황 문서, 실행별 설정과 결과는 실험 인덱스에 남긴다. **아래 환경·학습 수치는 추천 후보이며 아직 구현·최적화·확정된 조건이 아니다.** 현재 확인된 구현과 수치는 현황 문서에서 구분한다.

## 1. 목적과 기여

개발 목표는 K-CITY 복합 교통 환경에서 주변 차량·신호·목적지 경로를 고려해 안전하고 효율적으로 주행하는 의사결정 정책을 검증하는 것이다. 연구 주제는 **K-CITY 복합 교통 환경에서 전문가 사전학습의 효과와 한계 분석**이다.

BC 초기화 PPO와 PPO-only를 통제된 조건에서 비교한다. BC와 강화학습의 결합 자체를 새 알고리즘 기여로 주장하지 않는다. 초기 이점만 있거나, 일부 조건에서 불리하거나, 차이를 확인하지 못한 결과도 유효한 답이다. 일반화 주장은 **같은 K-CITY 도로망에서 교통 수요가 변할 때**로 한정한다. 새 도시·실차·정밀 센서 인지 성능으로 확대하지 않는다.

이번 작업은 조사·짧은 검증·설계·Markdown 기록까지다. 본격적인 환경 변경, BC/PPO 학습, 1,000만 전이 수집은 후속 요청에서 시작한다.

2026-11-14 추가 요청은 평가·컨설팅 자료를 반영한 시행 전 상세 설계다. 절대 State를 포함한 수업 필수 필드를 유지하고, 정책 원본 `action_raw`와 환경 bounded 입력을 분리하며, JSONL에는 모든 행의 next를 명시한다. 10M 장부는 전문가 pool1M+PPO6M+고정 정책 archive3M으로 구체화했다. 이 변경은 데이터 기록 계약이며 학습 예산을 늘리는 결정이 아니다. 이번에는 새 시뮬레이션·수집·학습을 하지 않았다.

## 2. 질문, 가설, 실험 연결

| 질문 | 가설(확정 결과가 아님) | 대응 실험 | 독립 변수 | 주요 관측 |
|---|---|---|---|---|
| RQ1: 전문가 사전학습이 목표 성능에 필요한 PPO 경험을 줄이는가? | H1: 기본 주행 초기화로 초기 실패와 PPO 상호작용이 줄 수 있다 | 실험 A, KC-RQ1 | 초기화: 무작위 / BC | 같은 전이 수 성능, 목표 도달 전이, 예산 종료 성능, 초기 실패, 시드 편차, 전체 비용 |
| RQ2: 수요가 높아져도 이점이 유지되는가? | H2: BC-only의 일부 한계를 PPO가 보완할 수 있으나 분포 이동 시 이점이 감소할 수 있다 | 실험 B, KC-RQ2 | 고정 정책의 평가 수요 | 안전·규칙 준수 완주, 충돌·위반·실패, 대기·주행 시간 |
| RQ3: 같은 데이터 수에서도 상황 구성이 영향을 주는가? | H3: 중요한 상호작용의 구성에 따라 초기화·후속 PPO 성능이 달라질 수 있다 | 추가 실험 C, KC-RQ3 | 자연 / 상호작용 균형 표본 | 초기 BC 성능, 같은 PPO 예산 학습곡선, 실패 유형 |

RQ1·RQ2가 필수다. RQ3는 기반과 주실험이 완료된 뒤 진행하며 전문가 실력 차이와 데이터 구성 효과를 혼동하지 않는다.

## 3. 현재 기반과 재사용 범위

맵·신호·일반차량 데모는 존재하지만 K-CITY 학습 환경은 없다. [조사 근거](research_checks/KC-AUDIT-20261110-01/evidence/summary.json)를 기준으로 다음을 재사용한다.

| 기존 코드 | 재사용할 부분 | 후속 작업에서 바꿀 부분 |
|---|---|---|
| `scripts/kcity/build.py::{main,qualifier_route,coverage_routes}`, `signals.py::apply_signals`, `prune_lanes.py::prune_network` | 생성 계보·경로 연결 검사·신호 정책 | 연구 도중 재생성하지 않고 맵/신호/경로 해시를 동결. 수정 시 새 환경 버전·재검증 |
| `scripts/kcity/common.py`, `validate.py::topology_check`, `validate_signals.py::structural` | SUMO tools 검색, 구조 검사 | 연구 설정의 독립 출력 경로에서 재사용 |
| `scripts/kcity/live_demo.py::run` | TraCI 연결·차량 투입 API 사용 예 | 무한 경로 연장·60대 상한은 데모용. Episode/수요 실험 환경으로 그대로 사용하지 않음 |
| `env/sumo_env.py::SumoHighwayEnv` | Gym 인터페이스, 주변 차량 질의, 행동 적용 아이디어 | `r0`·단일 도로·전역 TraCI 연결 의존을 새 `SumoKCityEnv`로 분리 |
| `utils/networks.py::HybridActorCritic` | 연속 가감속 + 3범주 차선 정책 | 같은 actor로 BC를 학습하고 PPO에 명시적 초기화; 마스크와 전처리 통일 |
| `algorithms/ppo.py::{collect_rollout,update,learn,save,load}`, `utils/buffer.py::RolloutBuffer` | PPO 업데이트 골격 | 종료/시간 초과 GAE, 독립 평가 환경, 정확한 전이 예산, 전체 재개 상태 |
| `train_bc.py::{load_data,split_episodes,run_epoch}`, `algorithms/bc.py::BCPolicy` | 입력 검사·Episode 분리 로직 | 현재 MSE 2출력 BC를 그대로 이식할 수 없음. 공통 hybrid actor의 가감속 MSE + 차선 CE로 연결 |
| `collect_pomdp_data.py::{collect,iter_transitions,merge_parts}` | 전이와 종료 관측의 정렬, 압축 저장 아이디어 | 시드/경로/버전/행동 보정 사유, 분할 스트리밍 저장. 전체 데이터를 메모리에 쌓는 방식은 대량 수집에 사용하지 않음 |
| `utils/evaluator.py::evaluate_policy`, `utils/logger.py::RunLogger` | 평가 루프·CSV 기록 | 신호·경로·텔레포트·분모·시간·실패 분류·평가 시드 패널 추가 |

기존 고속도로 예제와 그 자료는 보존한다. `train.py`, `test.py`, `collect_pomdp_data.py`를 현재대로 실행하면 `env/sumo/`를 재생성하므로 K-CITY 실행 명령으로 소개하지 않는다.

## 4. 필수 과제와 실제 경로 후보

다음은 현재 passenger 연결을 검사한 **개발용 경로 후보**다. 생성된 [경로와 차선 연결 목록](research_checks/KC-AUDIT-20261110-01/evidence/scenario_candidates.json)에 전체 Edge ID가 있다. 후속 KC-01/02에서 지정 위치 출발·도착과 scripted 주행을 확인했다. 전문가 수행 가능성과 본 수요 검증은 아직 남아 있다.

| 과제 | 구체적 후보와 목적 | 완료 판정의 핵심 |
|---|---|---|
| A: 신호 정지·출발 | `-68 → -13 → -71`, 신호 `647`, 일반 Edge 길이 합 약 133.92 m | 적색 접근 시 정지하고 허용 신호에서 통과한 뒤 지정 목적지 도착. 녹색만 만난 Episode를 적색 대기 성공으로 세지 않음 |
| B: 경로상 필수 차선 변경 | `-3#4 → -3#5 → -3#6 → -3#7 → -3#8 → -68`, 약 155.83 m | 첫 68.59 m의 2차선 Edge에서 차선 0 출발 후보. 다음 Edge 연결은 차선 1만 가능하므로 적시에 왼쪽으로 이동 |
| C: 복합 경로 | 기존 `qualifier`의 17개 Edge, 일반 Edge 길이 합 약 406.96 m | 첫 필수 차선 확보와 신호 `647/268/764/169`를 연속 통과하고 유한 목적지 도착 |

위 길이는 내부 교차로 Lane을 제외한 합계이며 실제 주행거리·시간이 아니다. 출발 위치 5 m, 초기 속도 2 m/s를 우선 검토하되 B의 차선 변경 여유와 투입 간섭을 B0로 확인한 뒤 동결한다. 첫 차선 길이의 정확한 값은 JSON의 측정값을 따른다.

개발은 A→B→C 순서로 검사하되, **비교 학습에서는 모든 방법에 A/B/C = 30/30/40%의 동일 과제 분포**를 제공하는 방식을 우선 추천한다. 특정 방법만 쉬운 과제부터 학습시키지 않는다. 회전교차로는 우선 확장, 긴급차량 양보는 추가 확장으로 주실험 뒤에 둔다. 전체 맵 임의 주행으로 이 과제를 대신하지 않는다.

## 5. K-CITY 환경 명세 추천안

### 5.1 Episode와 경로

- 새 `env/kcity_config.py`, `env/kcity_env.py::SumoKCityEnv`를 둔다. 기존 고속도로는 유지한다.
- 각 환경은 고유 TraCI label과 자기 connection을 사용한다. reset/close가 다른 학습·평가 인스턴스를 닫지 않아야 한다.
- `reset(seed, options)`에서 시나리오·SUMO·교통 투입·초기 배치를 하나의 seed tree로 결정하고 실제 사용 시드를 반환한다. 전역 `np.random`과 인자 없는 `default_rng()`에 기대지 않는다.
- warmup 60 s 후보 후 AV를 지정 출발 Edge·차선·위치에 투입한다. warmup은 Episode 시간·PPO 전이 수에서 제외하되 비용에 포함한다. 투입 지연·실패를 별도로 기록한다.
- 목적지 Edge·arrivalPos·허용 경로를 고정한다. 데모의 경로 순환 연장과 자동 재경로는 사용하지 않는다.
- 경로 진행도는 route index와 내부 Lane을 포함한 경로 거리로 계산한다. `getLanePosition`을 전체 진행도로 쓰지 않는다. 반복 Edge·내부 교차로·차선 변경에 대한 fixture가 필요하다.
- 동일 시나리오 내 최장 도착 시간 300 s를 **과제의 유한 지평 후보**로 둔다. 잔여 시간을 관측에 넣으며, 기한 초과는 실패 `terminated=True, reason=deadline`로 취급한다. 외부 실행 중단과 과제 실패를 구분한다.

### 5.2 Observation: 단일 시점 73-D 후보

기존 31-D의 국소 교통 표현을 확장한 후보이며 KC-02에서 해당 관측을 구현·실행 검사했다. [구현 안내](KCITY_ENV.md)를 따른다. 학습 데이터와 최종 동결 schema는 아직 없다.

| 블록 | 차원 | 내용·처리 |
|---|---:|---|
| 국소 교통 | 31 | 속도 1 + 좌2/좌1/현재/우1/우2의 전후 거리·상대속도 20 + 연결성 5 + 밀도 5. 연결성과 다음 Lane 밀도는 **지정 경로 기준**으로 수정 |
| 이웃 존재 마스크 | 10 | 차선별 선행·후행 존재. 없는 차량과 멀리 있는 차량 구분 |
| 차선 존재 마스크 | 5 | 같은 5개 오프셋의 도로 차선 존재 여부 |
| 자차·Episode | 8 | 차선 인덱스, 경로 진행률, 잔여 경로거리, 현재 Edge 잔여거리, 가속도, 내부 교차로 여부, 차선 변경 cooldown, 잔여 시간 |
| 신호·정지 규칙 | 9 | 신호 존재/거리, 적·황·녹·소등 one-hot 4, 정지 표지 존재/거리, 무신호 상충 교차로 여부 |
| 다음 경로 | 10 | 좌/직진/우/U 회전 one-hot 4, 다음 회전 거리, 좌/현재/우 차선의 다음 경로 연결 3, 다음 연결 유효 여부, 현재 제한속도 |
| 합계 | **73** | 순서·단위·결측 규칙을 schema version으로 동결 |

초기 관측 범위는 경로 전방 100 m·후방 50 m 후보로 둔다. 각 Lane의 가장 가까운 전·후 차량 1대만 정책 입력에 넣는다. 거리는 경로 방향 m, 속도는 m/s이며 상대속도는 `다른 차량 - 자차`, Lane index 증가가 왼쪽이다. 인접 Lane을 스캔할 때 차량 ID로 동률 정렬하고 접속 Lane을 경로 기준으로 이어 본다.

구체적인 0~72 index와 sentinel/mask 규칙은 [데이터 명세 7절](DATA_COLLECTION_SPEC.md#7-정책-관측-73-d-index-계약)을 따른다. 이 73-D에는 crossing 차량 슬롯이 없다. detected/privileged 자료에 crossing 차량을 기록해도 actor가 그 정보를 받는 것은 아니므로, 무신호 교차로 gap 선택을 정책 단독으로 학습했다는 주장은 하지 않는다. 확장 과제로 필요하면 새 관측 버전과 모든 비교 방법의 재학습을 요구한다.

거리/관측 범위, 속도/8.33 m/s, 가속도/해당 가감속 한계로 고정 물리 정규화를 적용하고 제한 범위를 명시한다. 학습된 평균·표준편차를 BC에만 적용하지 않는다. 결측은 0 등 고정값과 마스크를 함께 쓰고 `NaN/Inf`는 거부한다. route/TLS 없음은 독립 마스크로 구분한다.

전체 상태의 시야 밖 차량·주변 운전자 내부 파라미터·다음 행동·미래 신호 현시는 숨긴다. 정확한 위치·속도·현재 신호와 경로를 SUMO에서 읽는 이상적인 인지 가정이며 실제 센서 검증이 아니다. 우선 단일 시점 MLP를 사용한다. 잔여 속도/의도 추정 문제가 확인되면 동일한 4시점 누적을 모든 방법에 적용하는 별도 버전으로 비교한다. 주실험 도중 일부 방법에만 과거 정보를 추가하지 않는다.

### 5.3 행동, 분포, SUMO 제어 분담

- 기존 `HybridActorCritic`의 **Gaussian 가감속 1 + Categorical 차선 3**을 우선 재사용한다. 차선 범주는 왼쪽 `+1`, 유지 `0`, 오른쪽 `-1`이며 `LANE_CMDS=(1,0,-1)` 순서를 유지한다.
- 정책 제어 주기 0.5 s, SUMO 기본 스텝 0.1 s로 5 substep을 수행하는 후보를 추천한다. 한 정책 전이 안의 충돌·신호 통과·도착 이벤트는 매 substep에서 수집한다.
- 가감속 latent Gaussian 표본은 PPO buffer에 **원본 그대로** 저장한다. 환경은 이를 `[-1,1]`로 제한하고 양수는 최대 +2.0 m/s², 음수는 최대 -4.5 m/s²로 변환하는 후보를 사용한다. 최고 속도는 도로 제한과 8.33 m/s 중 작은 값이다.
- 원본 표본의 log probability로 PPO 비율을 계산한다. clip한 실제 행동을 원본 Gaussian의 표본처럼 다시 저장하지 않는다. clip 변환은 환경의 결정적 변환으로 명시하며, 실제 가속도와 요청 가속도가 같다고 주장하지 않는다. tanh-squashed 분포로 바꾸면 Jacobian을 포함한 별도 검증·환경 버전이 필요하다.
- 차선 명령은 1 s 유효·최소 1 s cooldown 후보다. 존재하지 않는 차선, 내부 교차로, cooldown은 **샘플링 전** 기하학적 mask로 제외하고 유지 명령을 항상 허용한다. 같은 mask를 BC CE, PPO sampling과 재평가에 사용한다. buffer에 당시 mask를 저장한다.
- 교통 간격으로 거부되는 요청과 실제 Lane 이동은 별도 기록한다. `changeLane` 호출 성공은 물리적 차선 변경 완료와 다르다. 잦은 재요청으로 cooldown을 우회하지 못하게 한다.
- 주실험은 모든 방법에 `speedMode=31`, `laneChangeMode=512`를 우선 추천한다. 현재 고속도로의 `0/0`, 데모의 `31/1621`과 다르므로 새 설정으로 B0부터 검증해야 한다. 512는 자동 차선 선택을 끄면서 간격 검사를 유지하는 설정이다. 설정 의미는 [SUMO 1.28 문서](https://github.com/eclipse-sumo/sumo/blob/v1_28_0/docs/web/docs/TraCI/Change_Vehicle_State.md)를 따른다.
- 맵과 같은 `collision.action=warn`, `collision.check-junctions=true`, `time-to-teleport=-1`을 공통 후보로 둔다. AV 충돌을 검출하면 환경이 실패 종료하고 terminal 관측을 보관한다. 현재 고속도로의 `collision.action=remove`와 구분한다. collision min-gap 설정과 SUMO 충돌 type도 기록하며, SUMO의 충돌 판정을 실측 차체 접촉으로 확대 해석하지 않는다.
- SUMO의 우선권·추종·신호 제동을 포함한 **시스템 수준 비교**가 기본 해석이다. 요청/허용/적용/실측 차이를 모두 안전 개입으로 세지 않는다. 클리핑·경계·교차로·cooldown 등 명시적으로 아는 사유와 SUMO 내부 사유 미확인을 구분한다.

mode 31에서 신호 위반이 0이라는 것만으로 정책이 신호에 맞춰 제동을 학습했다고 결론 내리지 않는다. 신호 접근 시 요청 가감속·실측 속도 trace를 함께 조사하고, 내부 보정의 원인을 분리할 수 없으면 정책 단독 신호 준수 성능이라고 쓰지 않는다.

### 5.4 보상과 종료

보상 후보는 `Δ경로거리/10m + 10·정상도착 - 20·AV충돌 - 10·적색진입 - 0.02·무효요청 - 0.01·차선변경 - 0.01·근거없는정지`다. 최적 계수가 아니며 B0·간단한 고정 정책으로 보상 편법을 확인한 뒤 동결한다. 속도만 높여 보상받거나, 경로를 반복해서 보상을 누적하거나, 안전 설정에 기대 계속 위험 명령을 요청하는 경우를 검사한다.

적색·정지 표지·선행차 대기 중에는 정지 페널티를 주지 않는다. ‘근거없는 정지’는 경로 진행 가능·앞 공간 확보·허용 신호·위협 없음이 확인된 경우에만 판정하며, 판정 불가를 임의 대기로 분류하지 않는다. 느린 정상 대기를 교착으로 조기 종료하지 않는다. 60 s 무진행은 우선 진단 로그로 두고, 교착 판정이 검증되기 전에는 과제 기한으로 실패를 판정한다.

| 사건 | 추천 반환·해석 |
|---|---|
| 지정 경로·목적지 정상 도착 | `terminated=True`, 도착. 과거 위반이 있으면 안전·규칙 준수 성공은 아님 |
| AV 관련 충돌, 적색 진입, 경로 이탈, 텔레포트, 설명 없는 제거 | `terminated=True`, 개별 실패 사유. 일반 도착과 구분 |
| 과제 기한 초과 | 유한 지평의 실패 `terminated=True`, 관측에 잔여 시간 포함 |
| 외부 TimeLimit/실행 중단 | 과제 기한과 별도 `truncated=True`. 유효 terminal observation을 보관하고 필요 시 bootstrap |
| SUMO 프로세스 장애·소켓 단절 | 인프라 오류로 전체 기록 보존. 아래 재실행 규칙 적용; 도착으로 처리하지 않음 |

기존 PPO의 truncation 뒤 reset value 혼입은 KC-03에서 수정했고 과거101.96→정답2.96을 확인했다. [실제 계약](KCITY_EVALUATION.md)을 유지하며 이후 실행기에서도 **bootstrap 가능 여부(termination)와 trace 단절(termination 또는 truncation)**을 따로 보관하고 terminal observation으로만 bootstrap해야 한다. [Gymnasium 시간 제한 문서](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/)와 맞춰 fixture를 통과하기 전에는 비교 학습을 시작하지 않는다.

## 6. 전문가·BC·PPO의 통제 설계

### 6.1 네 기준 정책

| ID | 정책 | 학습·초기화 |
|---|---|---|
| B0 | 관측 정렬 규칙 기반 전문가 | 동일73-D의신호/차간거리/경로연결로제어. KC-05 후보구현·6case도착 확인;교차gap/양보전체판정은아님 |
| B1 | BC-only | 공통 hybrid actor를 가감속 MSE + 차선 CE로 학습하고 고정 |
| B2 | PPO-only | 같은 네트워크·전처리·초기 분산·seed의 무작위 초기화 |
| B3 | BC 초기화 PPO | B1과 같은 선택 checkpoint의 actor 표현을 복사한 뒤 같은 PPO 예산 |

빨간 IDM 데모는 자동 차선 선택과 SUMO 내부 모델 정보를 사용하므로 그 행동을 그대로 ‘관측만 사용하는 전문가’라고 부르지 않는다. SUMO autopilot을 추가 기준으로 쓰면 별도 B0-SUMO로 기록하고 제어·특권 정보 차이를 공개한다.

B0는 미리 정한 신호/차간거리/경로 규칙을 쓰며 전체 차량 상태·미래 현시·미래 궤적을 보지 않는 방식을 우선 추천한다. 이것이 수행 불가능하면 정보 추가 이유와 관측만으로 모방 가능한지 먼저 검토한다. B0의 실패율·요청 거부·불필요 정지를 측정한 후 그 데이터가 전문가 자료로 적절한지 판단한다.

### 6.2 네트워크·업데이트

기존 `train.py`와 연결하기 위해 은닉층 `[256,256]`, ReLU hybrid 구조를 우선 추천한다. 73-D 입력을 같은 구조에 적용한다. 현재 BC의 `fc1/fc2/fc3`, 관측 평균·표준편차와 PPO의 `trunk/mu_head/lane_head/v_head/log_std`는 호환되지 않는다. `load_state_dict(strict=False)`로 일부만 무시하고 초기화 성공을 주장하지 않는다.

B1/B3는 같은 trunk·가감속 head·차선 head를 사용한다. BC 중 `log_std=-0.5`는 고정하고 value head를 BC loss로 학습하지 않는다. B2/B3의 value head 초기 난수와 optimizer 신규 상태를 맞춘다. 공유 trunk를 BC로 바꾸면 critic 입력 표현도 달라지므로 이를 **공유 표현의 사전학습 효과**에 포함한다고 명시한다. PPO optimizer는 B2/B3 모두 새로 만든다.

PPO 후보는 현재 예제의 `lr=1e-4, n_steps=2048, epochs=10, minibatch=64, gamma=.99, GAE λ=.95, clip=.2, value_coef=.5, entropy=0, lane_entropy=.01, grad_norm=.5`다. BC 후보는 batch 256·10,000 gradient updates·500 updates마다 검증이며 두 loss 가중치 1:1에서 시작한다. 업데이트 수와 실제 표본 재사용량을 기록한다. 후보 조정은 pilot에서만 하고 주실험 전 manifest를 고정한다.

BC 최저 검증 모방 loss로 B1/B3에 쓸 동일 checkpoint를 선택한다. B2와 B3의 PPO hyperparameter·정규화·seed·평가 주기·안전 설정·과제/교통 분포를 맞춘다. 주실험 중 특정 방법만 재튜닝하지 않는다. final 평가 성능으로 BC epoch·PPO checkpoint를 고르지 않는다.

## 7. 데이터 분리, 수요, 예산

### 7.1 시드와 수요

학습 seed 후보는 `11,22,33`이며 B1/B2/B3에서 짝지어 사용한다. 환경 seed namespace 후보는 전문가 `10000–19999`, PPO 학습 `20000–29999`, 개발 평가 `30000–30999`, final `40000–40999`다. 이는 범위 이름이며 실제 배정은 중복 없는 case manifest로 동결한다. 하나의 seed가 같아도 시나리오·수요·generator version이 다르면 같은 case가 아니다.

BC train/validation은 Episode와 생성 seed를 묶어 분리한다. row를 임의 분리하지 않는다. PPO 개발 평가와 final case는 별도 파일·별도 환경 인스턴스로 유지한다. BC 통계·모델 선택·목표 성능 판정에 final 데이터가 들어가면 해당 비교는 무효다.

`λ0=600대/시간`을 **초기 보정 후보**로 추천한다. 근거는 기존 유한 시나리오의 약 6 s 투입 간격뿐이며, 연속 수요의 수행 가능성을 입증한 값이 아니다. 배경 OD 비율·차량 모델 구성·신호 프로그램은 동일하게 유지한다. 평가 후보는 `λ0/1.5λ0/2λ0`; B0로 도착 가능성·포화 여부를 확인한 뒤 실제 값을 잠근다.

기존 연속 데모의 3 s·60대 상한을 이 수요 설정으로 대체하지 않는다. 상한에 걸리면 요청 투입률 자체가 변한다. 연구에서는 투입 요청 수/시각, 실제 출발 수/지연, pending, 실제 차량 수/도로 길이, Lane별 밀도·대기열을 기록한다. 상한이 필요하면 모두에게 같은 값으로 고정하고 제한 발동도 보고한다. 감응식 신호의 **프로그램/파라미터**는 동일하게 유지하지만 차량 행동이 검지기에 영향을 주므로 실제 현시 시퀀스까지 같다고 가정하지 않는다.

### 7.2 실험 A와 B의 권장 초기 규모

- B2/B3: 방법당 3개 학습 seed × **1,000,000 PPO 환경 전이/seed 후보**. 1전이는 0.5 s 정책 상호작용이며 SUMO 5 substep·평가 전이·warmup과 구분한다. 마지막 rollout을 남은 예산에 맞춰 줄이고 실제 전이 수를 기록한다.
- B1/B3용 전문가 풀: 우선 기준 수요에서 최대 1,000,000전이 후보. 같은 Episode 분리 후 BC 학습 200,000전이·검증 50,000전이를 우선 검토한다. 실제 수량·품질을 확인하지 않고 확보됐다고 쓰지 않는다.
- 개발 평가: 약 50,000 학습 전이마다 독립된 100 cases(A/B/C=30/30/40), 마지막에는 정확한 post-update checkpoint로 평가. rollout 경계 때문에 달라지는 실제 평가 전이를 기록한다.
- final: 학습된 정책·seed·수요당 100 Episode, A/B/C=30/30/40. B1/B2/B3 각각 3 seed × 3수요 ×100 = **2,700 Episode**, 단일 고정 B0는 3수요 ×100 = **300 Episode**로 총 3,000 Episode 후보다. 동일 case를 방법 간 짝지어 사용한다.
- B0 feasibility/pilot과 개발 평가에 쓴 cases는 final에 재사용하지 않는다. 학습 seed 3개로 불확실성이 충분히 해소됐다고 주장하지 않는다.

현재 짧은 측정은 일반차량 1,800 s를 wall 0.723 s, TraCI IDM 데모 600 s를 wall 3.455 s에 실행한 것이다. **AV 환경·정책 추론·PPO backward·데이터 직렬화 benchmark가 아니므로 학습 시간·1,000만 전이 비용으로 환산하지 않는다.** KC-06에서 B0의 A/B/C별 10 Episode와 단일 seed 50k PPO pilot(후속 요청 시)을 측정한 뒤 위 규모·저장 용량·병렬도를 확정한다.

### 7.3 목표 도달과 전체 비용

검증 집합의 안전·규칙 준수 완주율 **0.80 이상을 두 번 연속** 만족한 첫 checkpoint를 목표 도달 후보로 추천한다. 수업의 일반 완주율 90%를 결합 지표에 자동 적용한 값이 아니다. B0 pilot에서 목표가 의미 있는지 확인한 뒤 주실험 전에 고정한다. 충돌 <5%, 정상 완주 ≥90%, 관측된 신호 준수 100%는 별도 요구/목표로 보고한다.

같은 전이 수의 곡선, 예산 종료 checkpoint, validation으로 선택한 checkpoint의 final 결과를 나누어 기록한다. 미달성은 `예산 내 미달성`이며 임의로 목표 도달 전이를 채우지 않는다. 개발 평가 간격만큼 도달 시점 해상도가 제한됨을 밝힌다.

비용은 전문가 생성의 요청/유효 전이·wall/CPU/GPU 시간, BC 업데이트·학습 시간, PPO 상호작용·업데이트·시간, 개발/final 평가 전이·시간, 저장/검증 I/O로 나눈다. 전문가 풀을 여러 seed에 공유한 실제 총비용과 모델별 분배 비용을 함께 제시한다. PPO 전이 절감이 전문가 생성까지 포함한 총비용 절감이라는 뜻은 아니다.

### 7.4 선택 실험 C

같은 λ0 전문가 풀에서 자연 분포와 상호작용 균형 표본을 뽑는다. 우선 유형은 `필수 차선 확보 / 신호 접근·정지 / 신호 후 재출발 / 선행차 추종 / 기타 순항`이며 중복 상황은 이 순서로 주 유형을 정하고 보조 label도 보존한다. 신호 거리·속도·정지/재출발 기준은 추출 전에 schema로 고정한다.

16개 연속 전이 블록을 추출 단위로 하는 후보를 추천한다. 같은 수량 N=200,000 후보를 목표로 하되 희소 유형이 부족하면 **두 표본을 같은 N으로 줄이고 이유를 기록**한다. 중복 복제로 유효 데이터 수를 늘리지 않는다. Episode·seed 분리를 유지하고, 과거 관측을 추가하는 경우 같은 Episode의 burn-in 문맥을 보존한다. 전문가·데이터 생성 조건·모델·BC 업데이트·이후 PPO 예산은 동일하다. 증가 수요 평가 데이터는 이 풀에 넣지 않는다.

## 8. 평가·실패·해석 규칙

`안전·규칙 준수 완주율 = 기한 내 AV 관련 충돌·정의된 신호 위반 없이 지정 목적지에 정상 도착한 Episode 수 / 유효 평가 Episode 수`

| 지표 | 분자·분모와 단위 |
|---|---|
| 정상 완주율 | 지정 목적지 정상 도착 Episode / 전체 유효 Episode. 과거 위반이 있어도 일반 완주는 별도 집계 |
| AV 충돌률 | AV가 collider 또는 victim인 충돌이 한 번 이상 난 Episode / 전체 유효 Episode. 차량-스텝 수나 전체 HV 충돌 수와 구분 |
| 신호 준수율 | `1 - 위반 신호 통과 / 유효 신호 통과`와 `위반 Episode / 전체 Episode`를 함께 보고. 통과 0회는 NA. 적색 진입을 위반으로 정의하고 황색 진입은 별도 진단으로 기록 |
| 시간 초과·경로 이탈·제거·텔레포트 | 각 실패 Episode / 전체 유효 Episode. 텔레포트 후 도착을 정상 완주로 복구하지 않음 |
| 주행·대기 시간 | 전체 Episode의 제한 시간까지 비용과, 완주한 경우만의 조건부 평균을 함께 보고. 미완주에 짧은 주행 시간이 나왔다고 효율 우위로 해석하지 않음 |
| 요청·보정·실제 차선 변경 | 원본 정책 행동, clip/기하학적 거부, SUMO 명령, 실측 결과를 나눔. 실제 차선 변경 횟수와 명령 횟수 구분 |
| 불확실성 | seed별 원자료·평균·범위, case를 짝지은 차이와 seed 변동. Episode를 학습 seed의 독립 복제처럼 취급하지 않음 |

최종 평가 문서는 충돌 `<5%`, 준비 문서는 `≤5%`라 경계가 다르다. 연구는 더 엄격한 `<5%`를 우선 적용하고 수업 담당 확인 항목으로 남긴다. 완주 ≥90%·신호 준수 100%는 요청 프롬프트의 목표이며, 평가 기준 문서에서 동일 수치를 모두 확인한 것으로 쓰지 않는다. 유한 표본의 위반 0건은 실제 위반 확률 0의 증명이 아니다.

실패 taxonomy는 AV 추돌/접촉, 적색 진입, 위험/거부된 차선 변경, 필수 차선 미확보·경로 이탈, 과도한 대기·기한 초과, 텔레포트·제거, 인프라/수치 오류로 둔다. 첫 사건과 복수 사건을 모두 보관하고 대표 trace·영상으로 원인을 조사한다. 이벤트 label만으로 정책·신호·교통 수요 중 무엇이 원인인지 단정하지 않는다.

예정된 case와 시도 수를 모두 기록한다. 소켓 장애·외부 프로세스 종료처럼 사전 정의한 인프라 실패는 무효 시도로 남기고 방법 간 같은 case를 재실행해 필요한 유효 Episode를 채운다. 정책의 NaN·충돌·차량 제거·투입 지연은 성능 실패를 인프라 오류로 숨기는 데 사용하지 않는다. 실행이 끝나지 않으면 계획 수와 실제 유효 분모를 모두 표시한다.

## 9. 데이터셋·체크포인트·재현성

1,000만 **고유하고 유효한** 전이의 수집 목표는 유지한다. 이는 방법별 PPO 학습 예산이 아니다. 전문가/학습 rollout/개발 평가/final 평가/추가 기록을 목적별로 나누고 동일 전이의 중복 파일은 한 번만 센다. 위 초기 후보는 전문가 1M + B2/B3 6 runs ×1M =7M이며 평가 전이 수는 실제 Episode 길이로 결정된다. 부족분은 별도 수집 계획으로 결정하고 주실험 학습 예산을 조용히 늘리지 않는다.

2026-11-14 상세 결정: 부족한 기본3M은 6개 budget-end B2/B3 정책을 각각500k씩 고정 추론하는 별도 archive split으로 수집한다. 평가·pilot 자료는 기본10M 집계에서 제외하고 raw UID union과 필수 shard 세트로 최종 수량을 확인한다. 성공한 자료만 제출 수량으로 세는 것과, BC 학습 자료를 정상 전문가 Episode로 제한하는 것은 구분한다. 구체적인 필터·초과/부족 처리·split 계약은 [실행 프로토콜](EXECUTION_PROTOCOL.md)에 있다.

필수 schema는 `observation, policy_action_raw, action_mask, requested_acceleration, requested_lane, issued_command, observed_speed/acceleration/lane_change, known_rejection_reason, reward/components, next_observation, terminated, truncated, end_reason, episode/case/attempt/step/sim_time, route/scenario/seed_tree, policy/env/config/data_version, collision/arrival/violation/teleport/removal`이다. 정책 밖의 전체 상태는 `privileged_*`로 분리하며 BC 입력으로 혼입하지 않는다.

기본 저장 단위는 25k 전이 shard 후보다. 쓰기 중 `.partial`, 완료 후 SHA256·행 수·Episode 범위를 manifest에 확정한다. Episode 끝의 terminal observation과 다음 Episode 첫 관측을 섞지 않는다. 자료량·직렬화 시간은 새 73-D pilot에서 측정한다. 현재 고속도로 NPZ 4,941개는 새 데이터 용량 추정의 확정 근거가 아니다.

정지 상태 비율, 상황별 수량, 중복 `(case,attempt,step)`, 시간 간격, 누락값, 충돌/종료 관측, 행동 label과 실제 Lane 이동의 시차를 검증한다. 표준 PPO는 현 정책의 on-policy rollout으로 업데이트하며 저장한 1,000만 전이를 임의 replay로 다시 PPO 학습하지 않는다.

실험마다 code commit + dirty diff, SUMO/TraCI/Python/Torch/Gym 버전, 맵·신호·scenario·전처리 해시, 요청/적용 수요와 제어 설정을 보관한다. 재개 checkpoint에는 정책·가치·optimizer·난수·카운터·정규화·필요한 rollout/환경 상태가 있어야 한다. 가중치만 저장하는 기존 `PPO.save()`는 정확한 재개 checkpoint가 아니다. 모델·원시 데이터는 별도 결과 디렉터리와 검증된 백업에 두고 Markdown에는 링크와 집계만 남긴다. KC-04의 새 KCityRunner는 이 전체 상태와 현재 Episode replay를 저장·검사한다([실제 계약](KCITY_POLICY_AND_RESUME.md)). 작은 CPU 검증이며 기존 save/load의 의미를 바꾼 것은 아니다.

## 10. 단계별 구현 계획과 완료 기준

작업량은 코드 변경 범위에 대한 계획 추정이며 일정 보장이 아니다. 구현 요청을 받기 전 아래 작업을 착수하지 않는다.

| 작업 ID | 목적 | 선행 조건 | 실제 수정 대상 파일·함수 | 검증 방법 | 완료 기준 | 산출물 | 우선순위 | 예상 작업량 |
|---|---|---|---|---|---|---|---|---|
| KC-DOC-01 | 조사·설계·기록 체계 | 요청·기존 코드 | 이 세 문서·README·조사 스크립트 | 구조·해시·짧은 실행·링크 검사 | 구현/미구현·결과/제안 분리 | 계획·현황·실험 인덱스 | P0 | 중: 조사와 1개 통합 audit |
| KC-01 | A/B/C와 seed·제어 명세 고정 | 조사 완료 | 새 `env/kcity_config.py`, `scripts/kcity/scenarios.py`, `tests/test_kcity_scenarios.py` | 연결·신호·필수 차선·출발/도착·해시·시드 fixture | 아래 첫 구현 완료 기준 모두 통과 | versioned scenario/protocol manifest | P0 | 소~중: 설정·검사 3파일 |
| KC-02 | K-CITY Gym 최소 환경 | KC-01 | 새 `env/kcity_env.py::{reset,step,_get_obs,close}`; 기존 `_neighbor/_lane_density` 아이디어 | 73-D bounds, multi-Edge·내부 Lane 진행, A/B/C 유한 Episode, 인스턴스 격리 | seed 재현·목적지/충돌/제거/기한 처리 증거 | 환경·짧은 trace | P0 | 대: lifecycle·관측·행동 통합 |
| KC-03 | 종료·GAE·평가 신뢰성 | KC-02, buffer fixture | `utils/buffer.py::{add,compute_gae}`, `algorithms/ppo.py::{collect_rollout,learn}`, `utils/evaluator.py`; 새 평가 config | termination/truncation/rollout 경계, 적색 통과·충돌 fixture | cross-Episode 누출 0, 분모·독립 seed panel·정확한 예산 | 회귀 검사·지표 schema | P0 | 중~대: buffer·평가 3파트 |
| KC-04 | 공통 actor의 BC→PPO | KC-02/03 | 실제 구현: `algorithms/kcity_policy.py`, `algorithms/kcity_training.py`, shared PPO/buffer; 기존 BC/network 보존 | BC 전후 deterministic action, logprob/mask, optimizer/RNG 재개 검사 | 입력/분포/전처리 호환, B2/B3 조건 diff는 초기화뿐 | 공통 정책·초기화·재개 검사 | P0 | 중: 네트워크·학습 연결 |
| KC-05 | 전문가와 데이터 품질 | KC-02/03 | 실제 구현: `experts/kcity_rule_expert.py`, `utils/kcity_data.py/kcity_collector.py`, 별도 collect/validate CLI | B0 A/B/C, seed/Episode 분리, shard/시간/중복/label 검사 | 관측만으로 모방 가능·실력/한계·비용 기록 | 전문가·고정 λ0 풀·manifest | P0 | 대: teacher·기록·검사 |
| KC-06 | 규모·수요·보상 보정과 동결 | KC-04/05 | 새 `experiments/kcity/pilot` 설정·보고 | B0 경로별 10 Episode, 50k PPO pilot, I/O benchmark | λ0·배수·목표·예산·자원 측정 후 고정 | pilot 결과·동결 manifest | P0 | 중: 제한된 pilot 실행 |
| KC-07 | RQ1 통제 비교 | KC-06 | K-CITY BC/PPO 실행 config·`utils/logger.py` | 3 seed·동일 예산·학습곡선·비용 | B0/B1/B2/B3 결과·미달성·seed별 변동 보존 | KC-RQ1 runs | P1 | 대: BC 및 6개 PPO 본학습 |
| KC-08 | RQ2 고정 정책 수요 이동 | KC-07 | 새 평가 manifest·`utils/evaluator.py` | 3수요·짝지은 cases·정책 가중치 해시 불변 | 3,000 Episode 후보의 실제 분모·실패·시간 보고 | KC-RQ2 runs | P1 | 대: 평가·대표 실패 trace |
| KC-09 | RQ3 상황 구성 | KC-07/08 | 새 표본 추출기·BC/PPO configs | 같은 풀/N/업데이트/seed·누출 검사 | 구성 외 차이 없는 비교 | KC-RQ3 runs | P2 | 대: 별도 BC/PPO 반복 |
| KC-10 | 10M 데이터·최종 재현성 | 각 수집/실험 결과 | shard manifest·dataset validator·문서 | 고유 전이 합계·복원·해시·누락 검사 | 실제 수량과 미달성 분리·재현 명령 확인 | dataset card·최종 보고 | P1 | 중~대: 집계·저장·재현 |

**첫 구현 KC-01의 완료 기준**: (1) A/B/C의 Edge·시작/도착 위치·차선·허용 차량·시간 예산을 manifest로 명시, (2) 모든 route 연결과 TLS index 검증, (3) B의 출발 Lane 0은 다음 Edge로 직결되지 않고 Lane 1만 연결됨을 자동 검사, (4) map/signals/seed tree·제어·schema 해시 기록, (5) 동일 seed의 교통 요청 목록 동일 및 다른 seed 변화, (6) 0.2 m 수준의 짧은 Edge·내부 Lane을 놓치지 않는 검사, (7) 기존 맵·고속도로·과거 결과 해시 불변. 이 단계에서는 본학습을 시작하지 않는다.

## 11. 미확정 사항과 결정 원칙

우선 동결할 것은 A/B/C 출발·도착, λ0의 연속 수요 수행 가능성, 73-D 결측/마스크 명세, 정지선 통과 판정, 공통 안전 설정, B0 품질, validation 목표·비용·저장 용량이다. 추천 후보를 실제 검사로 확정하고 변경 이유·영향·관련 실험 ID를 현황 문서에 남긴다. 여러 수요·차량 모델·신호·관측을 동시에 바꾸지 않는다.

실제 현시표·최신 차선 운영·교통량이 없어 현재 맵을 실측 K-CITY 운영의 복원으로 주장할 수 없다. 원본 MGEO·항공사진 사용 범위와 라이선스는 별도 확인 사항이며, 이번 조사에서는 외부 업로드·원본 워크스페이스 수정이 없다.

## 12. 근거와 참고 문헌

외부 자료는 2026-11-10에 원문 페이지를 확인했다. 우리 실험의 성능을 보증하는 근거가 아니다.

- [Ross, Gordon & Bagnell (2011), DAgger](https://proceedings.mlr.press/v15/ross11a.html): 행동이 이후 관측 분포를 바꾸는 모방학습의 분포 이동 문제. 이 문제의식 때문에 closed-loop 실패도 평가한다. 이번 연구에 DAgger를 추가한다는 뜻은 아니다.
- [Liang et al. (2018), CIRL](https://arxiv.org/abs/1807.03776): 시각 기반 CARLA에서 모방과 RL을 결합한 선행 연구. DDPG 기반으로 본 연구의 PPO·벡터 관측·SUMO와 다르다. 결합 자체의 신규성 근거로 쓰지 않는다.
- [Rietsch et al. (2022), Driver Dojo](https://arxiv.org/abs/2207.11432): 시나리오·관측·행동 설계와 일반화 평가의 중요성. 우리 연구 범위는 동일 도로망의 수요 변화로 더 좁다.
- [SUMO 1.28 제어 문서](https://github.com/eclipse-sumo/sumo/blob/v1_28_0/docs/web/docs/TraCI/Change_Vehicle_State.md), [차량 상태 조회](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html), [충돌 출력](https://sumo.dlr.de/docs/Simulation/Output/Collisions.html): 설치 버전 1.28.0과 실제 bundled TraCI probe를 대조했다. 신규 위반 검출기의 정확도는 별도 fixture가 필요하다.
- [Gymnasium 시간 제한](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/): termination과 truncation의 bootstrap 구분. 실제 코드의 trace 단절 문제는 저장소 fixture로 별도 확인했다.
- 수업 원자료: [준비](../project_materials/5_Project_Preparation.md), [평가](../project_materials/6_Project_Evaluation.md). 실제 수정 후보·과거 수치의 근거는 [현황](RESEARCH_STATUS.md)과 [실험](EXPERIMENTS.md)에 연결한다.
