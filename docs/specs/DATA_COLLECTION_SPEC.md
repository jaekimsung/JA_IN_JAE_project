# K-CITY 데이터 컬럼·저장·검증 명세

갱신: 2026-11-16 · 논리 schema `KC-DATA-v1` / observation `KC-OBS73-v1`. **73차원 관측과 기존 전체 필드를 유지**한다. 3seed pilot·본 설정 동결·저장 최적화를 완료했으며 본 pool/BC/PPO는0이다. 현재 실행과 보관 상태는 [현황](../research/RESEARCH_STATUS.md)을 따른다.

73은 정책 입력 벡터 길이다. 현재 기본 transition 생성의 최상위 key는59개이며 중첩 State/행동/사건을 포함한다. 표의 항목 수·벡터 차원·flatten한 열 수를 혼용하지 않는다. `schema_status` 등 기존 candidate 문자열은 계보 식별값으로 보존하며 현재 준비 상태를 뜻하지 않는다.

[연구 계획](../research/RESEARCH_PLAN.md) · [실행 절차](EXECUTION_PROTOCOL.md) · [결과·컨설팅](../research/RESULTS_AND_CONSULTING.md) · [현재 상태](../research/RESEARCH_STATUS.md)

## 1. 수업 요구와 설계 결정

[6_Project_Evaluation.md](../course/6_Project_Evaluation.md)의 기본 transition 필드는 **전부 보존**한다. `state/next_state`의 절대 정보와 `detected_vehicles`도 필수다. 기존 고속도로 collector는 보존한다. 별도 K-CITY writer/loader와 본 실행기는 구현·검증했고, 최종 공개 release는 아직 없다.

| 요구·현재 차이 | 이번 결정 |
|---|---|
| 평가 자료의 `observation` 표기는 19-D, 실제 기본 코드는 31-D | 필드명은 유지, K-CITY 신규 버전은 **73-D**. `observation_schema_id`와 정확한 index표를 저장하고 컨설팅에서 차원 확장 인정 여부 확인. KC-02 구현·후속 pilot 검증·본 설정 동결 완료 |
| 기본 collector의 clipped `action_raw`와 PPO의 Gaussian 원본 표본이 다를 수 있음 | 수업 정의에 맞춰 `action_raw`는 **정책 원본 2-vector**, `action.env_input`은 실제 bounded 입력. `policy_action_raw`는 원본과 동일한 명시적 alias이며 PPO logprob는 원본 기준. 새 K-CITY loader는 bounded BC target과 PPO 원본 표본을 구분 |
| `lane_change_applied`가 API 성공만 나타낼 수 있음 | 기존 필드는 명령 발행 성공 의미로 유지하고 실제 이동은 `action.lane_change_executed`에 별도 기록 |
| JSONL의 중간 `next_*` 생략 | 논리 행에는 모든 next를 보존. 물리 JSONL은 `KC-NEXT-REF-v1`로 다음 행 UID 참조를 허용하고 terminal/shardtail은 명시. `read_shard()`가 원값을 복원 |
| 10^7개 데이터 | **정책 1개가 수행한 유효 AV 환경 전이 1개=1행**. HV별 상태·0.1 s substep·파일 복제·재시도 중복을 행 수에 더하지 않음 |
| 데이터 제출 | JSONL.gz를 완전한 기준 자료로, NPZ는 같은 행의 수치 학습 view로 제공. 두 파일의 행을 중복 집계하지 않음 |

## 2. 전이의 시간 계약

기본 SUMO tick 0.1 s, 정책 주기 0.5 s(5 tick)는 동결 조건이다. 기록 순서는 `snapshot s_t / o_t → policy a_t → 명령 발행 → 최대 5 substep·event 수집 → s_(t+1)/o_(t+1) → reward·종료 판정 → 한 행 확정`이다.

- `t=0`은 AV가 실제로 삽입된 뒤의 첫 정책 결정이다. warmup·삽입 대기는 별도 비용/traffic 로그이며 데이터 전이가 아니다.
- `sim_tick_t`, `sim_tick_tp1`은 정수 SUMO tick, `sim_time_s=sim_tick×0.1`이다. Episode 시간은 AV 출발 기준이다. 부동소수 오차로 step 정렬을 판단하지 않는다.
- substep 도중 충돌/도착/위반 종료이면 즉시 멈추고 `executed_substeps=1..5`, `control_dt_s`를 실제 경과로 저장한다. 이는 여러 전이가 아니라 하나의 짧아진 terminal 전이다. 정상 행은 5 tick이다.
- `state`와 `detected_vehicles`는 모두 **행동 적용 전 같은 tick**, `next_*`는 실제 종료 tick이다. 요청 행동에 관측되지 않은 다음 상태를 섞지 않는다.
- terminal 다음 행이 reset이라도 terminal `next_*`를 reset 관측으로 대체하지 않는다. budget/shard 경계는 종료가 아니므로 `terminated/truncated`를 억지로 true로 만들지 않는다.
- 중간에 프로세스가 죽어 `next_*`가 없는 마지막 전이는 `.partial`로 남겨 valid count에서 제외한다. 나중에 완성된 전이를 새 ID로 위장하지 않는다.

## 3. 공통 자료형·결측·식별 규칙

JSON은 UTF-8, IEEE 유한 숫자만 허용한다. NPZ는 object/pickle array 없이 읽혀야 한다. 관측/행동/reward는 float32, 절대 좌표·시각·route distance는 float64, 카운터는 int64, bool은 boolean이다. 원시 JSON은 API 값을 임의 소수4자리로 반올림하지 않는다. 정책에 입력한 float32 관측은 그대로 저장해 NPZ와 대조한다.

누락된 절대 좌표/차선/신호는 JSON `null`과 validity flag를 쓴다. **0으로 위치를 꾸미지 않는다**. NPZ 확장 수치의 null은 `value=0 + *_valid=false`로 내보내며 `NaN` sentinel은 쓰지 않는다. 존재하지 않는 신호/주변차의 관측 인코딩은 아래 mask 규약을 따른다.

`run_uid`는 실행 시작 때 발급해 재개 시 유지한다. `case_uid`는 scenario·수요·환경/traffic seed·고정 설정의 hash, `episode_uid`는 논리 Episode의 안정 ID다. 재실행은 `attempt_uid`로 구분한다. `transition_uid=SHA256(episode_uid + ':' + t)`이며 동일 Episode의 재시도는 같은 UID를 갖게 해 중복을 검출한다. runtime attempt는 별도 열이므로 실패 이력도 보존한다.

`episode_uid=SHA256(run_uid + ':' + logical_episode_index + ':' + case_uid)`로 구체화한다. 같은 case를 서로 다른 정책/학습 seed로 수행한 것은 서로 다른 run의 실제 경험이므로 중복이 아니다. 동일 run의 crash 재시도는 logical_episode_index와 episode_uid를 유지하고 attempt_uid만 바꾼다. run registry를 새로 발급해 같은 재시도를 고유 경험으로 위장하지 않는다.

현재 `episode`는 dataset/run 안의 단조 증가 int64이며 `t`는 Episode의 0-based index다. 최종 제출 병합 때 release 전체 고유 int64 재배정과 원본 run/episode 매핑이 필요하며 이 병합기는 후속이다. run별 `episode=0`을 그대로 병합하지 않는다. `(episode,t)`와 transition UID는 각각 unique해야 한다. 동일한 o/a라도 다른 유효 seed/시각의 정상 전이를 내용 hash만으로 중복 제거하지 않는다.

## 4. Transition 한 행의 필수 컬럼

표의 `state.*` 등은 중첩 JSON의 경로다. 모든 버전/manifest는 행의 `run_uid`로 찾아갈 수 있어야 하며 파일명을 통해 추측하지 않는다.

### 4.1 수업 기본 필드: 삭제 금지

| 컬럼 | 타입·형태 | 단위·시점 | 의미·검증 |
|---|---|---|---|
| `episode` | int64 | ID | 현재 dataset 내 번호. release 병합 시 전역 매핑 필요 |
| `t` | int64 | step | Episode 내부 정책 전이 index, 0부터 연속 |
| `observation` | float32[73] | 정규화·t | 정책이 실제 사용한 부분관측. index는 7절 |
| `action_raw` | float32[2] | 가감속 latent는 유한 실수·t | 정책 원본 `[accel_sample,lane_cmd]`; clip 전 원본을 보존 |
| `action.accel_raw` | float | [-1,1] | 환경에 전달한 `action.env_input[0]`. 원본 `action_raw[0]`와 다를 수 있음 |
| `action.lane_change_raw` | float | [-1,1] | 환경 입력의 Lane 값. hybrid 정책은 {-1,0,+1}이며 원본 Lane 명령과 같음 |
| `action.lane_change` | int8 | +1좌/0유지/-1우 | 실제 변환한 요청 명령 |
| `action.lane_change_applied` | bool | 해당 interval | TraCI 변경/유지 명령이 정상 발행됐는지. 실제 이동과 구분 |
| `reward` | float32 | interval 합 | 원시 환경 보상. GAE bootstrap 보정 reward로 덮어쓰지 않음 |
| `terminated` | bool | 종료 tick | 충돌·도착·과제기한 등 MDP 종료 |
| `truncated` | bool | 종료 tick | 외부 시간 제한 등 MDP 밖에서 잘림 |
| `state` | object | 절대 정보·t | 5절의 simulator-side privileged snapshot. policy 입력 아님 |
| `detected_vehicles` | list[object] | t | 정책의 관측 범위 안 차량 목록. 필드와 정렬은 6절 |
| `event.collided` | bool | interval OR | **AV 관련** SUMO 충돌 한 번 이상. HV끼리 충돌은 별도 |
| `event.arrived` | bool | interval OR | AV가 도착 목록에 있음. 지정 목적지 검사는 추가 필드 |
| `event.lane_before` | int/null | index·t | 행동 전 AV 차선. 내부 교차로는 lane_id도 함께 읽음 |
| `event.lane_after` | int/null | index·t+1 | interval 종료 차선. 사라진 차량은 null |
| `next_observation` | float32[73] | t+1 | 모든 논리 행에 존재. 물리 next참조는 reader로 복원. AV소실은 absorbing+valid=false |
| `next_state` | object | 절대 정보·t+1 | 모든 논리 행에 존재. 물리 next참조 허용. ego_alive=false라도 남은 HV/신호/시각 기록 |

### 4.2 식별·출처·시간·종료 확장

| 컬럼 | 타입 | 의미·허용 값 |
|---|---|---|
| `schema_id`, `observation_schema_id` | str | `KC-DATA-v1`, `KC-OBS73-v1`. 본 과학 설정에서 채택한 논리 계약 |
| `run_uid`, `case_uid`, `episode_uid`, `attempt_uid`, `transition_uid` | str | 위 식별 규칙. 재개/재시도 연결 |
| `source_stage` | enum | `expert_pool / ppo_train / dev_eval / final_eval / archive_rollout / pilot / debug` |
| `data_split` | enum | 현재 본 writer는 `expert_train / expert_val / ppo_train`, 운영 probe는 `ops_probe`. dev/final/archive/pilot/debug의 최종 release label은 후속 병합에서 명시 |
| `policy_id`, `policy_version`, `policy_checkpoint_sha256` | str | B0/B1/B2/B3, teacher hash 또는 실행중 frozen rollout policy hash. PPO는 `update_id`와 연결 |
| `train_seed`, `seed_manifest_id`, `scenario_id`, `route_id`, `demand_id` | int/null·str | 실제 값을 manifest와 대조. 학습 없는 정책의 train_seed는 null |
| `sim_tick_t`, `sim_tick_tp1`, `sim_time_s`, `next_sim_time_s` | int64/float64 | tick·s, 모든 state와 시간 정렬 |
| `episode_time_s`, `control_dt_s`, `executed_substeps` | float64/int8 | warmup 제외·실제 경과. 기본 control_dt=0.5 |
| `observation_valid`, `next_observation_valid` | bool | 실제 조회 가능 여부. terminal absorbing vector의 의미 표시 |
| `end_reason` | enum/null | `arrival/collision/red_entry/wrong_route/deadline/teleport/removal/external_limit` |
| `episode_complete`, `segment_end`, `segment_end_reason` | bool·enum/null | Episode 종료와 `budget/shard/checkpoint` 조각 경계 구분. segment만 끝나면 done=false |
| `row_valid`, `invalid_reasons` | bool/list[str] | 정렬·finite·출처·키 검사가 통과한 전이인가. 정상 정책 실패도 row_valid=true일 수 있음 |

### 4.3 행동 요청·명령·결과·학습 provenance

| 컬럼 | 타입·단위 | 기록 원칙 |
|---|---|---|
| `policy_action_raw` | float32[2] | `action_raw`와 동일한 명시적 alias. B0/BC는 결정적 원본 출력. alias가 다르면 오류 |
| `action.env_input` | float32[2] | 환경에 전달한 bounded [가감속,Lane]. 원본→clip 변환의 결과 |
| `action.accel_clipped`, `action.accel_request_mps2` | float | clip 결과, +2.0/-4.5 m/s² 변환. 원본과 혼동 금지 |
| `action.lane_category`, `action.lane_mask` | int8/bool[3] | category 0좌/1유지/2우. sampling 당시 mask를 저장 |
| `action.command_issue_tick`, `action.target_lane_id`, `action.lane_duration_s` | int64/str/null/float | 발행 시각·목표 Lane·유효시간. issued speed를 쓰면 그 값과 substep별 명령도 event log에 기록 |
| `action.accel_observed_mean_mps2`, `action.speed_after_mps` | float/null | substep의 실측 평균 가속도·최종 속도. 명령값 복사 금지 |
| `action.lane_change_executed` | bool | 같은 일반 Edge 내 lane index 변화로 확인. Edge/internal 전환을 차선 변경으로 세지 않음 |
| `action.known_rejection_reasons` | list[enum] | `missing_lane/internal_junction/cooldown/masked/invalid_input/traci_error` 등 **확인된** 사유 |
| `action.sumo_override_reason` | enum/null | 내부 사유를 API로 확정 못 하면 `unknown`/null. 속도 차이만으로 안전 개입 단정 금지 |
| `reward_components` | object{str:float} | progress/arrival/collision/red/invalid/lane_change/unjustified_wait. 합=reward |
| `learning.update_id`, `learning.rollout_id` | int64/null | 같은 rollout의 policy weights는 고정. BC/B0/고정 평가는 null |
| `learning.log_prob_raw`, `learning.value`, `learning.next_value` | float/null | 원본 정책 분포와 관측. 제출 필수 아님; PPO 재현용 내부 기록. B0에 가짜 logprob를 넣지 않음 |
| `learning.bootstrap_mask`, `learning.trace_mask` | bool/null | termination의 bootstrap와 Episode 경계의 trace 중단 분리 |

가감속은 interval 시작에 목표 가속도를 정하고 `setAcceleration` 명령으로 실제 실행 substep 동안 유지하는 설계로 우선 통일한다. 속도 clip/안전 조정은 SUMO mode에 따른다. `setSpeed(v+a·dt)`를 사용한다면 manifest의 `longitudinal_adapter`를 다른 버전으로 구분하고 혼용하지 않는다. **KC-02 후보 환경은 `setAcceleration`을 구현하고 요청/실측·substep 수를 기록한다.** 기존 고속도로 adapter는 변경하지 않았다. KC-05의별도writer/validator는필수State·next·행동/시간·JSONL/NPZ·복구를실제소량검사했다. 본 collect/views/bc/ppo 실행기와 과학 설정 동결도 완료했다. 본 학습 카운터는0이다.

## 5. 절대 State 명세: 반드시 포함

이 State는 분석을 위한 **관측 가능한 simulator snapshot**이며 SUMO 내부 RNG·모델 상태 전부를 담은 완전 Markov 상태/정확한 재개 파일이라고 주장하지 않는다. 재개에는 별도 checkpoint가 필요하다. `state`와 `next_state` 모두 아래 구조다.

| 경로 | 타입·단위 | 출처·규칙 |
|---|---|---|
| `sim_tick`, `sim_time_s`, `ego_alive`, `snapshot_valid` | int64/s/bool | snapshot 완료 여부, AV가 없어도 snapshot 유지 |
| `ego_x`, `ego_y`, `ego_z` | float64/null·m | SUMO network 좌표. 원본 도로/항공사진 좌표와 혼용 금지. network location/offset/projection은 manifest 보관 |
| `ego_speed`, `ego_accel`, `ego_angle_deg` | m/s, m/s², deg/null | TraCI 값. 각도는 SUMO 기준(북0°,시계방향)임을 표시 |
| `ego_lane`, `ego_lane_id`, `ego_road_id`, `ego_lane_pos` | index/str/m/null | 기존 state 키 보존. :internal lane 구분 |
| `ego_route_index`, `ego_route_progress_m`, `ego_distance_m` | int/m/null | route index·계획경로 누적 진행·실제 누적거리 구분 |
| `ego_allowed_speed_mps`, `ego_waiting_s`, `ego_speedMode`, `ego_laneChangeMode` | 단위별 숫자/null | 현재 제한/대기·실제 설정 읽기 |
| `vehicles` | list[vehicle] | 네트워크에서 실제 주행 중인 **모든 차량**, AV도 포함. vehicle ID 사전순. 미투입은 별도 pending 집계 |
| `vehicles[].id,x,y,speed,lane,lane_id,road_id,lane_pos` | 기존 필드 유지 | 모든 차량의 절대값. 추가 z/accel/angle/type_id/is_ego도 저장; 타입 파라미터는 manifest vType표로 연결 |
| `traffic.running_hv`, `traffic.pending_hv`, `traffic.departed_hv_interval`, `traffic.arrived_hv_interval` | int64 | HV에 AV를 포함하지 않음. 요청 투입은 별도 request log |
| `traffic.active_request_count`, `traffic.requested_lambda_vph`, `traffic.realized_departures_window` | int/veh/h/object | 요청량·실제 투입량 구분; window 시작/끝·표본수 명시 |
| `signals` | list[object] | 모든 TLS의 id/program_id/phase_index/state. **현재** 현시. 정밀 remaining duration 등은 privileged 영역만 허용 |
| `route_state` | object | scenario/route_id, goal_edge/arrival_pos, current connection occurrence index, route_valid |
| `quality.query_errors`, `quality.missing_vehicle_ids` | list | 조회 실패를 조용히 삭제하지 않음. critical snapshot 실패는 row_valid=false |

절대 좌표는 TraCI의 vehicle reference point를 그대로 저장하고 `position_reference='SUMO_front_bumper_center'`로 metadata에 적는다. rectangle 중심/센서 좌표가 필요한 분석에는 별도 변환을 둔다. [`getPosition`·speed·acceleration의 공식 정의](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html)를 사용하며 설치 1.28 bundled API와 후속 fixture로 대조한다.

AV가 소실되면 `ego_alive=false`, ego 필드는 null, 관측은 73개의 0과 `next_observation_valid=false`를 저장한다. 마지막으로 확인한 위치를 현재 위치라고 채우지 않는다. 직전 tick의 실제 위치가 필요하면 substep event trace에서 가져온다.

## 6. 감지 차량과 0.1 s 사건 로그

`detected_vehicles`의 각 원소는 기존 `id,x,y,rel_pos,speed,lane_offset`을 유지하고 `y`는 절대 m다. 추가 필드는 `edge_id,lane_id,accel_mps2,rel_speed_mps,relation,projection_valid,in_policy_slot`이다. `relation`은 `same_corridor / adjacent_corridor / crossing`이다.

주변차는 경로 corridor의 전100/후50 m와 교차로 주변100 m 범위에서 수집하는 **규칙**으로 구현했다. `rel_pos`는 같은/인접 corridor에만 경로방향 투영 부호 거리(앞+,뒤-), 교차 차량은 null+projection_valid=false다. `lane_offset`도 crossing에는 null이다. 가까운 순·ID 동률로 결정적 정렬한다. 정책73-D에는 lane별 nearest 전후10대까지만 들어가며, detected 목록에 더 많은 차가 있어도 모두 actor 입력인 것은 아니다.

73-D에는 crossing 차량의 속도/위치 슬롯이 없다. **교차 차량 gap 선택을 정책이 직접 학습했다는 주장을 하지 않는다.** A/B/C의 유신호 과제와 공통 SUMO 안전 설정으로 범위를 제한한다. 무신호·회전교차로 양보를 주과제로 확대하면 crossing 슬롯·교통 마스크를 추가한 새 관측 버전과 모든 방법의 재학습을 요구한다. B0도 추가 detected 정보를 몰래 쓰지 않는다.

별도 `events.jsonl.gz`는 `(episode_uid,t,sim_tick,event_uid)`로 전이에 join한다. events 수를 transition 수로 세지 않는다.

| 사건 컬럼 | 필수 내용 |
|---|---|
| `collision` | 발생 tick, collider/victim/type, AV 포함 여부. 같은 사건을 반복 tick에서 세지 않는 event_uid와 Episode-level ever flag |
| `tls_crossing` | route connection occurrence, TLS id/link_index, 진입 직전 state와 tick, 차체 기준, 위반 판정·유효성. 내부 Lane 진입 자체가 항상 위반은 아님 |
| `arrival/teleport/removal/wrong_route` | vehicle ID, tick, 실제 expected route/goal 비교, 제거 사유 known/unknown |
| `lane_change` | 원래 Edge의 이전/이후 lane_id, request t, executed tick. 연결 전환과 구분 |
| `traffic_request` | 예정 시각·OD/type/seed/request_id, 실제 departure, 지연·거부·상한 발동. AV 운전에 따라 달라지는 realized 값은 결과 |
| `episode_boundary` | 종료 이유·terminal snapshot valid, segment 종료인지 실제 Episode 종료인지 |

정지선 위반은 후속 fixture가 통과해야 유효 지표다. `getNextTLS` 거리와 connection/via Lane을 연결해 **차량 앞부분이 진입선을 통과하기 직전**의 해당 link state가 `r`이면 red_entry로 정의한다. 황색·소등·허용녹색은 별도 값으로 기록한다. 짧은 Edge를 0.5 s endpoint만 비교해서 건너뛰지 않도록 0.1 s trace와 crossed connection을 추적한다. state 불명확은 compliant로 채우지 않고 invalid 판정/검사 대상으로 남긴다.

## 7. 정책 관측 73-D index 계약

아래는 현재 `KC-OBS73-v1` 구현의 정확한 순서다. actor는 절대 State를 받지 않는다. 모든 연속 관측은 최종 [-1,1] clip, mask/one-hot은 {0,1}. `clip`은 입력 정규화이며 원시 state를 잘라 저장하지 않는다. 동적 평균/표준편차 대신 모든 방법에 같은 물리 정규화를 사용한다.

정규화 기준: `V=8.33m/s`, 전방100m·후방50m, `H=300s`, `Dmax=1000m`, max_accel=2.0/max_decel=4.5m/s², Lane index denominator는 전체 맵 max passenger lane count-1이다. 이 값은 동결됐으며 변경 시 schema/config 버전과 모든 비교 방법의 재학습 범위를 검토한다.

| index | 내용 | 정규화·결측 |
|---|---|---|
| 0 | ego_speed | v/V |
| 1+4k .. 4+4k, k=0..4 | offsets(+2,+1,0,-1,-2) 순 선행거리·선행상대속도·후행거리·후행상대속도 | front_gap/100,(v_other-v)/V,-rear_gap/50,(v_other-v)/V; 없으면 [1,0,-1,0], 31~40 mask로 구분 |
| 21..25 | Lane별 지정 다음 경로 연결성 | 존재하지 않음=-1; 존재하나 목표 연결 불가=0; 유효=1 |
| 26..30 | Lane별 전방 밀도 | 지정 corridor의 count/(유효관측길이/7.5m), [0,1] clip; 없는 Lane=0+존재mask0 |
| 31+2k,32+2k | 각 Lane의 front/rear 존재 | 0/1. 관측 밖과 미존재는 mask0 |
| 41..45 | offsets 순 Lane 존재 | 0/1 |
| 46 | ego_lane_index | index / max(1,map_max_lane_count-1); internal이면0 |
| 47 | route_progress | 경로 누적 / 계획 총길이, clip[0,1] |
| 48 | remaining_route_m | /Dmax; 도착 이후0 |
| 49 | current_edge_remaining_m | /100; internal은 현재 internal Lane 잔여 |
| 50 | ego_accel | 양수/2.0,음수/4.5 |
| 51 | inside_junction | 0/1 |
| 52 | lane_cooldown_remaining | /1s, clip[0,1] |
| 53 | episode_time_remaining | /H |
| 54,55 | next_TLS_present,distance | 100m 이내일 때1,d/100; 없으면0,0 |
| 56..59 | TLS red/yellow/green/off one-hot | 현재 경로 link, G/g→green,y/Y→yellow,r→red,o/O→off. 없음은 전부0; 그 외 state는 schema 오류 |
| 60,61 | stop_sign_present,distance | 경로100m 이내,없음0/0. 실제 stop line 좌표가 확정된 것만 사용 |
| 62 | unsignalized_conflict_ahead | 고정 맵 rule lookup·100m 범위0/1; crossing traffic의 전후 판단값 아님 |
| 63..66 | next_turn left/straight/right/U one-hot | 다음 경로 connection 회전; route 끝/없음 all0 |
| 67 | distance_to_next_turn | /100,없으면0 |
| 68..70 | 다음 route 연결의 left/current/right 가능 | 해당 인접 Lane으로 같은 route continuation 가능한지0/1 |
| 71 | next_route_connection_valid | connection 데이터 있으면1,route끝/없으면0 |
| 72 | current_speed_limit | 허용속도/V,clip[0,1] |

policy input validator는 길이73·float32·finite·범위·one-hot·mask 일관성, 양 Lane 부호, 내부 Lane, stop line sentinel을 검사한다. 옛 31-D를 0-padding해 새 정책 관측이라고 하지 않는다. 최종 수업 인정 차원이 달라지면 actor·dataset schema·모든 비교 방법을 함께 변경하고 컨설팅 결정으로 남긴다.

현재 `legacy/highway/train_bc.py::load_data`는 `abs(action_raw)<=1`을 요구하고 `legacy/highway/collect_pomdp_data.py`의 일부 정책은 수집 전에 clip한다. 새 데이터에서는 원본 가감속이 범위를 넘을 수 있으므로 이 검사·수집 경로를 그대로 쓰지 않는다. 새 BC loader는 `action.env_input`의 가감속과 `action.lane_category`를 학습 label로 선택하고 schema version으로 동작을 분기한다. PPO는 항상 원본 action_raw로 log probability를 계산한다. label 선택과 필드 의미를 모두 기록해 기존 자료와 조용히 섞지 않는다.

## 8. 파일·NPZ·분할·복원 계약

본 결과 root 예정은 저장소 밖 `/home/heven/kcity_research_runs/KC-MAIN-v1/`이며 아직 본 실행 출력은 없다. 현재 pilot/검증 root는 별도다. Git에는 문서/작은 설정/집계, 외부 저장소에는 모델·replay가 필요한 다른 알고리즘 자료·원시 데이터를 둔다. PPO는 보관 자료를 replay해 학습하지 않는다.

아래는 **후속 최종 제출 패키지 설계**이며 현재 writer 디렉터리와 다르다. 실제 RUN/RELEASE/shards/checkpoints 구조는 [파이프라인](KCITY_DATA_PIPELINE.md)을 따른다.

```text
release/
  DATASET_CARD.md, schema.json, RELEASE_MANIFEST.json, SHA256SUMS
  manifests/ runs.jsonl, episodes.jsonl, cases.jsonl, splits.json
  expert_train/<shard>.jsonl.gz, <shard>.npz, <shard>.MANIFEST.json
  expert_val/...
  ppo_train/...
  archive/...
  dev/..., final/...
  events/<run_uid>/*.jsonl.gz
```

`RELEASE_MANIFEST`에 dataset/protocol/code/env/obs/action/reward versions, 좌표 정의·단위·vTypes·map/TLS hashes, split별 유효고유수, invalid/duplicate/incomplete/attempt 수, 파일별 bytes/SHA256·행 수·first/last UID·종료/계속 segment 여부를 기록한다. JSONL/NPZ 동시 제공은 storage view 차이이지 별개의 samples가 아니다.

**기본 NPZ key 전부 유지**:

| key | shape/dtype |
|---|---|
| `observation`, `next_observation` | (N,73)/float32 |
| `action_raw` | (N,2)/float32 |
| `lane_change` | (N,)/int8 |
| `reward` | (N,)/float32 |
| `terminated`, `truncated` | (N,)/bool |
| `episode`, `t` | (N,)/int64 |
| `detected_xy` | (M,2)/float64 |
| `detected_offsets` | (N+1,)/int64, first0,lastM,단조 비감소 |

NPZ 확장: `policy_action_raw, action_env_input, action_mask, transition_uid`(고정 길이 ASCII), `sim_tick_t,sim_tick_tp1,control_dt_s,observation_valid,next_observation_valid,row_valid`. `detected_xy`의 순서는 같은 행 JSON detected 목록과 동일하다. **State/next_state는 JSONL의 복원된 논리 행에 반드시 존재**하며 NPZ에는 object dict로 넣지 않는다. JSONL+NPZ+manifest를 하나의 필수 shard 세트로 제출한다. 물리 JSONL은 반드시 codec-aware reader로 복원해 읽는다.

일반 writer 기본값은25,000행이지만 본 expert는 실측 운영 크기512행, 본 PPO는 rollout2048·50k경계에 맞춰 commit한다. 여러 Episode를 담을 수 있다. Episode가 file boundary를 넘으면 next를 명시하고 동일 episode_uid·t 연속성을 유지한다. split은 row가 아니라 **Episode·traffic seed group**으로 먼저 정한다. 한 Episode가 expert_train과 expert_val에 동시에 존재하면 전체 release reject다. 같은 case의 재시도는 같은 split이다.

쓰기 절차: `.partial` 스트리밍 → 마지막 명시 next 확인 → JSON/NPZ 완성 → fsync → schema·정렬·SHA 검사 → `.MANIFEST.json` 확정 → atomic rename → 전역 manifest에 append. crash 복구 시 manifest로 확정된 파일만 유효수에 넣고 partial은 별도 격리한다. 한 worker의 전체10M 배열을 메모리에 쌓지 않는다.

## 9. 품질 통과 기준과 10M 집계

| 검사 ID | 통과 기준 | 실패 처리 |
|---|---|---|
| DQ-01 필수 필드/타입 | 수업 필수 key 누락0; finite·shape 일치; State 절대 위치/차량 필드 presence | 누락 행 격리, 필수 필드 축소로 통과시키지 않음 |
| DQ-02 시간 정렬 | tick 차1..5, 정상5, state/obs 같은tick; nonterminal next=같은 Episode 다음 obs/state | boundary 포함 mismatch0; 시뮬레이터 이벤트 탓으로 넘어가지 않음 |
| DQ-03 종료 | terminal next 명시·사라진 AV null/valid flag, done이 Episode 경계와 일치 | terminal 누락·reset 혼입0 |
| DQ-04 행동 | policy raw→bounded→명령·reward 합 일치, mask keep 허용, raw logprob 재계산 일치 | clipped 행동으로 PPO ratio 재계산 금지 |
| DQ-05 ID·split | 전역(episode,t)/UID unique, Episode/traffic seed group train/val/dev/final 교집합0 | 동일 재시도·파일복사 중복 제외 및 기록 |
| DQ-06 NPZ/JSON 동등 | N·UID·73-D·action/reward/done 같음; offsets[-1]=M | 파일세트 전체 미확정 |
| DQ-07 출처 | code/config/map/signals/teacher/checkpoint hash 해결 가능 | 알 수 없는 policy 자료를 expert_train에 섞지 않음 |
| DQ-08 분포/상호작용 | speed<0.1m/s 정지비율·유형별수·mask 거부·근접차·적색대기·필수차선 case 수 보고 | 희소 유형/정지편중은 데이터 한계·추가 수집 판단; 성능 실패 행을 조용히 삭제하지 않음 |
| DQ-09 저장/복원(로컬 구현·외부 제출 후속) | local 전체 file SHA; 원격 목록/bytes/SHA·내려받기 검증; 무작위 shard가 아닌 필수 manifest 전체 파일 coverage 확인 | 원본 보존·재전송. 검증 전 정리 금지 |

품질 유효성과 정책 성공은 다르다. 충돌/위반/기한 초과가 정확히 기록된 자료는 분석용 유효 전이다. 다만 **BC fitting 대상은 baseline 수요에서 충돌·위반 없이 정상 완주한 B0 Episode**로 제한하며, 원본 실패 Episode도 expert_pool에 보존하고 필터 통과율을 보고한다.

수집량 장부는 [실행 절차](EXECUTION_PROTOCOL.md)의 `1M expert_pool + 6M PPO train + 3M fixed-policy archive`를 기본으로 한다. pilot/debug·평가자료는 별도 보관하되 목표10M의 기본 분자에서 제외한다. 확정된 유효 UID union이 **10,000,000 이상**이고 JSON/NPZ 양쪽 존재·복원이 가능해야 제출 완료다. 완주 Episode 경계 때문에 초과한 수량은 실제 값으로 보고한다. 부족한 유효 행은 추가 **새 case**로 채우며 실패 로그·필수 State를 잘라 저장량만 맞추지 않는다.

## 10. 저장 최적화·모델 참조

새 JSONL의 `storage_codec=KC-NEXT-REF-v1`은 같은 Episode의 다음 행과 정확히 같은 next_state/next_observation만 `next_reference`의 transition UID로 대체한다. terminal·shard 마지막 행에는 next를 직접 저장한다. 논리행·정밀도·전체State·NPZnext는 줄이지 않는다. 과거 full-next도 읽는다.

PPO는 `transitions/checkpoints/`에 native 모델/Adam/RNG/부분buffer/환경replay bundle을 검증·확정한 뒤 shard의 `environment/REFERENCE.json`에 경로/SHA/T를 기록한다. `checkpoint_from_shard()`로 해석한다. 최신·직전·50k평가 모델과 초기모델을 보관하며 데이터 shard/UID/SHA는 immutable이다. 예전 shard의 참조 모델은 보관 정책에 따라 제거될 수 있으므로 모든 shard에서 개별 재개가 가능하다고 주장하지 않는다. 최신 재개 및 평가 모델을 보장하는 정책이다. BC는 최신·직전·재개에 필요한best를 유지한다.

## 11. 개인정보·공개·참고 자료

수집 대상은 합성 차량이다. 토큰·로컬 계정·SSH 정보·원본 재배포 허용 여부가 불명확한 항공사진/MGEO를 dataset에 자동 포함하지 않는다. State의 SUMO 좌표와 네트워크 좌표계 설명은 필요하지만 원본 지도 재배포 허용을 뜻하지 않는다. 후속 실제 제출 때 사용하는 Hub/제출 목적지·모델·설정 manifest를 확인하고 공개 권한과 재배포 범위를 검토한다. 이번 작업에서는 업로드하지 않는다.

수업 필드 근거는 [평가 문서 기본 데이터 항목](../course/6_Project_Evaluation.md)이다. 기술 참고는 [SUMO 차량 상태](https://sumo.dlr.de/docs/TraCI/Vehicle_Value_Retrieval.html), [제어 명령](https://sumo.dlr.de/docs/TraCI/Change_Vehicle_State.html), [시간 제한 구분](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/), [Hugging Face dataset 공유](https://huggingface.co/docs/datasets/upload_dataset)이며 2026-11-14에 공식 문서를 확인했다. 현재 반환형/사건 판정은 설치1.28 기반 제한 fixture와 pilot에서 확인했다. 모든 정지/양보 규칙 검증은 아니다. Drive 업로드는 사용자 지시로 금지했고 이번 문서 개정에서도 수행하지 않았다.
