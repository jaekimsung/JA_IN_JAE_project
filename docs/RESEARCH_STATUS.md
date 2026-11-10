# K-CITY 연구 현황

마지막 갱신: **2026-11-10T23:26:17+09:00**

## 1. 먼저 읽을 요약

- **현재 단계: 현황 조사·짧은 실행 검증 완료, K-CITY 학습 AV 환경 구현 전.** 연구 방향은 [전문가 사전학습의 효과·한계 분석](RESEARCH_PLAN.md)이다.
- 이번에 완료한 일: 코드/설정/과거 로그 대조, 독립 출력 경로의 SUMO·고속도로·정책/GAE 검사, A/B/C 경로 후보 연결 검사, 연구 계획·현황·실험 인덱스 작성.
- 중요한 확인: 맵은 176 Edge / 198 일반 Lane / 346 내부 Lane, 신호 14곳이다. 새 seed 43의 유한 합성 교통은 177/177대 도착·충돌/텔레포트 0. 이는 **학습 AV 성능이 아니다**.
- 학습 전 해결 사항: K-CITY Gym/신호·경로 평가 미구현, BC→PPO 구조/정규화 불일치, 같은 reset seed의 초기 교통 불일치, truncation 뒤 GAE의 에피소드 간 value 혼입.
- 바로 다음 작업: KC-01에서 유한 A/B/C 경로·출발/도착·seed·제어 명세를 고정하고 자동 검사를 만든다. 완료 기준은 [계획 10절](RESEARCH_PLAN.md#10-단계별-구현-계획과-완료-기준)에 있다.
- **환경 코드 변경·BC/PPO 학습·1,000만 전이 수집은 이번에 하지 않았다.** 기존 맵/고속도로/과거 결과 및 다른 작업 프로세스를 변경하지 않았다.

팀원은 이 문서 → [RESEARCH_PLAN.md](RESEARCH_PLAN.md) → [EXPERIMENTS.md](EXPERIMENTS.md) 순서로 읽으면 된다. 수치는 실행/파일 근거, 추천 조건은 미구현 설계로 구분한다.

## 2. 단계별 상태

상태 어휘: `미착수 / 진행 중 / 검증 대기 / 완료 / 차단 / 보류`. 코드만 작성한 상태를 검증 완료로 표시하지 않는다.

| 작업 ID | 작업 | 상태 | 확인 근거·산출물 | 관련 파트 | 다음 행동 |
|---|---|---|---|---|---|
| KC-DOC-01 | 현재 구현 조사·연구 설계·문서 체계 | 완료 | 세 문서·README 안내·KC-AUDIT-20261110-01 | 전체 | 아래 우선 작업으로 이어감 |
| KC-01 | 경로/seed/제어 명세 동결 | 미착수 | [검사된 경로 후보](research_checks/KC-AUDIT-20261110-01/evidence/scenario_candidates.json)만 존재 | 환경·교통 | 후보를 versioned scenario로 만들고 출발/도착 검사 |
| KC-02 | K-CITY Gym 환경 | 미착수 | 기존 `SumoHighwayEnv`와 맵 데모만 있음 | 환경 | 다중 Edge lifecycle·73-D 후보·substep 이벤트 구현 |
| KC-03 | GAE/종료/평가 신뢰성 | 미착수 | [GAE 재현](research_checks/KC-AUDIT-20261110-01/evidence/summary.json)의 `truncation_fixture` | PPO·평가 | trace 단절과 bootstrap 분리, 위반/실패 fixture |
| KC-04 | 공통 actor의 BC→PPO | 미착수 | `policy_fixture`에서 직접 state_dict 이식 실패 확인 | 학습 | 공통 hybrid BC와 초기화/재개 검사 |
| KC-05 | 관측 정렬 전문가·수집기 | 미착수 | 현재 collector는 고속도로 random/keep-lane/PPO/BC만 지원 | 전문가·데이터 | B0 구현·모방 가능성·seed/shard 검증 |
| KC-06 | 수요/보상/규모 pilot | 미착수 | 배경 교통 실행 시간만 측정됨 | 실험 운영 | B0와 AV/PPO pilot 후 λ0·예산·목표 동결 |
| KC-07 | RQ1 본 비교 | 차단 | 환경/초기화/종료 처리 미완료 | 학습·분석 | KC-01~06 완료 후 새 실험 ID로 시작 |
| KC-08 | RQ2 고정 정책 수요 평가 | 차단 | 평가할 K-CITY 학습 정책 없음 | 평가 | KC-07 정책과 독립 final case 준비 |
| KC-09 | RQ3 데이터 구성 비교 | 보류 | 필수 RQ1/2 우선 | 데이터·학습 | 같은 λ0 풀·N·업데이트 통제 설계 유지 |
| KC-10 | 10M 데이터셋·최종 재현성 | 미착수 | K-CITY 고유 전이는 수집되지 않음 | 데이터·보고 | 전문가/학습/평가/추가 기록을 목적별 집계 |

## 3. 현재 구현 진단과 근거

아래는 단계별 상태와 별개의 **구현 진단**이다. 요청의 어휘 `완료 / 부분 구현 / 미구현 / 문서와 불일치 / 확인 불가`를 사용한다.

| 영역 | 진단 | 확인한 사실과 근거 | 한계·다음 조치 |
|---|---|---|---|
| 맵·소스 계보 | 완료 | `kcity.net.xml` 직접 집계 176/198/346, 소스 스냅샷 9개와 manifest SHA 대조. `build.py`가 OpenDRIVE 변환·prune·signals·scenery 수행 | 실제 최신 K-CITY 차선/현시 복원 아님. [소스](../maps/kcity/source/manifest.json) |
| 경로·일반차량 | 완료 | 유한 177개 route/177대, 새 seed 43에서 전부 도착. `validate.topology_check` 오류 0 | 빨간 IDM 1대를 포함한 총 177대. 177대 HV + 학습 AV 1대가 아님 |
| 신호 운영 | 완료 | 신호 프로그램 정의 14개, 구조 충돌/커버리지 검사 통과, 실제 TraCI TLS 14개/type 3, 과거 기록은 `assumed_actuated_v1` | 현시·수요·배치는 가정. 사전 정의와 신호 trajectory가 동일하다는 뜻은 아님 |
| 거동 모델·시간 간격 | 완료 | Krauss/IDM/EIDM/ACC, vType 최고속도 8.33 m/s, SUMO 1.28.0, K-CITY Δt=0.1 s | 모델별 실측 보정·현실 교통량 확인은 없음 |
| 연속 빨간 차량 | 완료 | 600 s 새 seed 43에서 1회 생성·경로 4회 연장·소실/도착 0, 3,362.73 m 주행 | `live_demo.py`의 IDM 순환. 목적지 도착 과제나 학습 정책이 아님 |
| 고속도로 reset/step | 완료(그 범위) | 독립 복사본에서 2 reset ×10 step, 유한 31-D 관측, step=0.5 s 확인 | 다중 Edge·신호/위반·K-CITY 학습 검증은 아님 |
| 고속도로 관측 설명 | 문서와 불일치 | `SumoHighwayEnv.__init__`의 일부 주석은 19-D, 실제 식·mdp_config·실행은 **31-D** | 정책/데이터 schema는 실행 31-D를 기준으로 해석 |
| seed 재현성 | 부분 구현 | Gym seed 인자는 있으나 같은 요청 seed + 같은 전역 NumPy seed에서도 초기 차량 수 159/161, 상태 SHA 상이 | `_start_sumo`의 전역 RNG와 `_prefill_traffic`의 무시드 RNG를 통합해야 함 |
| K-CITY Gym 연결 | 미구현 | `train.py/test.py/collect_pomdp_data.py`가 `road_builder.build()`와 `SumoHighwayEnv` 사용; `r0` 고정 | 기존 cfg 경로만 K-CITY로 바꾸는 방식으로 해결되지 않음 |
| BC 개별 학습 기반 | 부분 구현 | 31→256→256→2 MSE 정책, train-set obs mean/std, Episode 분리 로직 존재 | K-CITY 데이터·BC 학습 로그/정책 없음. audit는 학습하지 않음 |
| PPO 기반·저장 | 부분 구현 | train 설정은 [256,256] ReLU hybrid. sampling/logprob 재계산 일치. 기존 model.pt도 현재 31-D hybrid에 CPU 로드 가능 | GAE 오류·단일 환경 평가·seed 패널 부재. `save()`는 policy weights만 저장. 로드 가능성이 K-CITY 재사용 가능성을 뜻하지 않음 |
| BC 초기화 PPO | 미구현 | BC 74,498 / 현재 31-D PPO 75,270 parameters, state_dict 직접 이식 실패 | 입력 정규화·head·분포 통일과 초기화 API 필요. 단순 strict=False 금지 |
| 행동·제어 기록 | 부분 구현 | 고속도로는 raw→clip→속도 명령, LC quantize/자체 간격 gate. `speedMode=0/laneChangeMode=0` 실측 | ‘모든 안전 기능 off’라는 주석은 부정확. SUMO 1.28 mode 0은 일부 검사를 유지함 |
| AV 평가/수집 | 부분 구현 | 고속도로 충돌·도착·시간 초과와 NPZ/JSONL collector 존재 | 신호·경로·텔레포트 실패·개입 사유·명시 seed/version 부족 |
| K-CITY 10M 목표 | 미구현 | 현재 `data/dataset.npz`는 **4,941전이·10 Episode·31-D의 고속도로 자료** | 전문가/학습/평가별 K-CITY 고유 전이는 측정 전 |
| 현실 일반화·신호 실측 일치 | 확인 불가 | 실측 교통량/현시표·현장 주행 자료 없음 | 수요 변화 실험도 아직 미실행. 실제 도로 성능으로 해석 금지 |

### 제어 분담에서 특히 주의할 점

데모의 mode는 실제 **31/1621**이고, 고속도로는 **0/0**이다. 고속도로는 자체 차선 안전 gate도 켜져 있으므로 설정 숫자만으로 개입이 없다고 주장할 수 없다. SUMO의 mode 0은 ‘대부분의 검사 off’이며 bit 5/6의 반대 의미 때문에 ‘전부 off’와 다르다. [버전 1.28 공식 정의](https://github.com/eclipse-sumo/sumo/blob/v1_28_0/docs/web/docs/TraCI/Change_Vehicle_State.md)를 기준으로 해석한다.

새 주실험의 추천 31/512는 아직 적용하지 않았다. 모든 방법에서 같은 설정으로 수행하고 제어 보정을 완전히 분리할 수 없으면 시스템 수준 결과로 보고한다. `lane_change_applied=True`는 기존 코드에서 명령 API가 성공했다는 뜻이며 물리적 차선 변경 완료를 보장하지 않는다.

## 4. 확인된 결과: 서로 다른 범위를 분리

| 실험 ID | 결과 | 근거 | 해석·한계 |
|---|---|---|---|
| KC-HIST-SIGNALS-20261101 | 저장된 after 12 cases에서 2,124/2,124 도착, collision records 0, teleport 0, 급제동 경고 126 | [과거 summary](../maps/kcity/reports/signals_validation/summary.json), 이번 hash checks | 이번에 12 cases를 재실행한 것은 아님. 1/2/3배는 177대 출발 시간 압축이며 지속 수요 검증 아님 |
| KC-AUDIT-20261110-01 / finite | 새 seed 43, 1,800 s, 177/177 도착, 충돌/텔레포트 0; subprocess wall 0.723 s | [새 summary](research_checks/KC-AUDIT-20261110-01/evidence/summary.json), [tripinfo](research_checks/KC-AUDIT-20261110-01/evidence/finite.trips.xml), [충돌](research_checks/KC-AUDIT-20261110-01/evidence/finite.collisions.xml) | 일반차량 단일 finite case, 학습 AV 평가 아님 |
| KC-AUDIT-20261110-01 / live | 새 seed 43, 600 s, 빨간 IDM 소실 0·경로 연장 4, 충돌/텔레포트 0; wall 3.455 s | [live JSON](research_checks/KC-AUDIT-20261110-01/evidence/live_IDM.json) | 3 s 요청·60대 상한; 300 s 이후 평균 약 58.90대. 독립 수요 단계나 무한 안정성 증거 아님 |
| HW-LEGACY-20260907 | 마지막 저장 평가 194,560전이: collision 0, success 0, timeout 1.0 | [기존 CSV](../results/run_20260907_202220/eval_log.csv) | 고속도로 과거 로그. 현 K-CITY/새 코드 성능으로 재사용하지 않음 |
| KC-AUDIT-20261110-01 / policy·GAE | BC 이식 실패, hybrid logprob 차이 0, truncation fixture가 101.96을 산출(의도한 값 2.96) | [policy_fixture·truncation_fixture](research_checks/KC-AUDIT-20261110-01/evidence/summary.json) | CPU offline 검사, 학습 업데이트 0. 버그 영향의 실차/학습 성능 정량치는 아님 |

과거 12 cases의 network/signals/각 generated route 해시가 현재 해당 파일과 일치함을 확인했다. seed 1/2에서 쓴 생성 route는 기본 `kcity.rou.xml` 자체와 byte가 같아야 하는 것이 아니므로 각 case 파일과 대조했다. 맵·환경 source는 짧은 실행 전후 불변이고, README 안내 변경과 새 문서/검사 파일만 이번 변경 범위다.

## 5. 문제·미확정 사항·의존관계

| 항목 | 영향 | 해결할 다음 행동 |
|---|---|---|
| A/B/C 후보만 연결 검사 완료 | AV 투입·도착·B0 수행 가능성은 아직 없음 | KC-01 manifest 후 KC-02/05에서 bounded Episode 검사 |
| 신호·정지선·내부 Lane 이벤트 | 신호 준수/경로 진행 지표를 현재 평가기로 만들 수 없음 | 매 0.1 s 이벤트 검출 fixture. API 반환·위반 기준 분리 |
| BC/PPO 불일치 | 초기화 효과와 architecture/normalization 차이가 섞임 | 같은 HybridActorCritic, 같은 고정 전처리, actor copy·mask·분산 검사 |
| truncation GAE 누출 | 학습곡선을 신뢰할 수 있는 비교가 차단됨 | 별도 trace 경계와 terminal observation bootstrap; 기존/수정 fixture 비교 |
| seed 소유권 불명확 | 같은 case를 방법 간 짝지을 수 없음 | SUMO/traffic/episode/policy seed tree, request manifest와 초기 상태 hash 재현 |
| λ0·배수·포화 수요 | finite 2/3배와 연속 수요 일반화가 다름 | B0로 기준/증가 수요 feasibility 확인 후 600/900/1200 후보 확정 또는 수정 |
| 73-D·보상·기한·목표 후보 | 미검증 값을 최적값으로 쓸 위험 | KC-06 전에 후보로 표시, pilot 후 config/결정 기록 동결 |
| 실제 작업 자원 | 현재 측정은 배경 교통뿐; AV/PPO/수집 비용 불명 | 50k pilot 및 새 schema shard 측정. 학습 시간·용량은 측정 전 |
| 실행 의존성 | 기본 Python에는 Gymnasium/TensorBoard 없음 | audit에만 별도 cache venv+Gymnasium 1.2.3 사용. BC 학습용 환경은 후속 준비 |
| 학습 재개/모델 선택 | 기존 save는 가중치만; final로 선택할 위험 | 전체 optimizer/RNG/카운터 checkpoint와 독립 validation/final manifests |
| 수업 충돌률 경계 | 준비 ≤5%, 최종 평가 <5% | 우선 <5% 사용·담당 확인. 결합 완주 지표 목표는 별도 동결 |
| 현장 자료 | 현재 신호·차선·수요를 실측 운영이라고 주장할 수 없음 | 필요하면 현시표·실측량·최신 차선 운영 확보; 주실험은 합성 조건으로 명시 |

## 6. 바로 다음 작업 5개

1. **P0 / KC-01 — 유한 시나리오 고정.** 선행: 이번 조사. 완료: A/B/C의 출발·도착·필수 차선·TLS·seed·해시 자동 검사와 기존 파일 불변. [구체적 첫 완료 기준](RESEARCH_PLAN.md#10-단계별-구현-계획과-완료-기준).
2. **P0 / KC-02 — K-CITY 환경 lifecycle·관측·이벤트.** 선행: KC-01. 완료: 같은 seed 초기 상태 재현, 고유 TraCI 연결, 73-D 계약 검사, 내부 Lane 진행·도착·충돌·제거·기한 판정 trace.
3. **P0 / KC-03·04 — PPO 신뢰성과 BC 초기화.** 선행: 관측/행동 계약. 완료: GAE 경계 fixture, 동일 mask의 logprob 검사, BC→PPO deterministic action 일치, 전체 재개 검증.
4. **P0 / KC-05 — 전문가와 작은 데이터 검증.** 선행: 환경/평가. 완료: B0가 A/B/C를 실제 수행하고 사용 정보·실패를 기록; Episode/seed 분리·shard·누락/중복 검사 통과.
5. **P0 / KC-06 — 제한 pilot와 사전 동결.** 선행: 위 기반. 완료: λ0/증가 수요 수행 가능성·50k pilot·I/O 비용을 측정하고 3 seed/예산/목표/final 패널을 동결. 이후에만 RQ1→RQ2→선택 RQ3를 실행.

## 7. 결정 기록

| 날짜 | 결정 | 이유 | 다른 대안 | 영향 | 관련 실험 |
|---|---|---|---|---|---|
| 2026-11-10 | 조사·짧은 검증·문서만 수행 | 이번 요청의 명시적 범위 | 곧바로 환경 수정/학습 | 기존 코드/맵을 보존하고 구현은 다음 요청으로 남김 | KC-AUDIT-20261110-01 |
| 2026-11-10 | 연구 기여를 통제 비교로 정의 | BC+RL 자체는 선행 연구가 있음 | 새 알고리즘으로 포장 | BC 초기화의 무효/불리한 결과도 보고 | KC-RQ1/2/3 계획 |
| 2026-11-10 | 실제 Edge에서 A/B/C 후보 선택 | 기존 qualifier에 TLS와 필수 차선 연결이 확인됨 | 전체 맵 임의 주행 | 수행 가능성은 B0/AV 검사 전까지 미확정 | KC-AUDIT-20261110-01 |
| 2026-11-10 | 새 K-CITY 환경을 분리하고 shared hybrid actor 추천 | r0 의존·분포/정규화 불일치 | 기존 cfg만 교체 또는 state_dict 일부 무시 | 고속도로 보존, 비교 조건을 명시적으로 통일 | KC-01~04 계획 |
| 2026-11-10 | GAE·seed를 본학습 전 gate로 지정 | offline value 누출과 reset 불일치 재현 | 기존 코드 그대로 비교 | 수정 후 새 실행만 주비교; 과거 로그는 참고용 유지 | KC-AUDIT-20261110-01 |
| 2026-11-10 | 31/512·73-D·300 s·λ0=600·1M budget은 후보 | 현재 맵/기존 네트워크에 맞춘 최소 범위 추천 | 고속도로 0/0·데모 31/1621 그대로 이식 | 구현/pilot 뒤 확정해야 하며 이번에 적용하지 않음 | KC-06 계획 |
| 2026-11-10 | 충돌률 <5%, 결합 목표 0.80 후보를 분리 | 최종 평가 경계와 요청의 결합 지표 구분 | 결합 지표에 90% 자동 적용 | 최종 비교 전 기준 확인·동결 필요 | KC-RQ1/2 계획 |

## 8. 날짜별 작업 기록

### 2026-11-10

- 요청·적용 지침·README·수업 준비/평가 문서·Git 상태 확인. 조사 시작 HEAD는 `d81a9a962a29898fbd768d0168eaacd6862a6d8e`, branch `main`. 기존 미추적 `prompts/`, `MUJOCO_LOG.TXT`를 보존했다.
- `docs/`에 같은 역할의 기존 문서가 없어 세 파일을 만들고 KC-DOC-01을 진행 중으로 표시한 뒤 조사했다.
- 환경·BC/PPO·정책·buffer·평가·수집·맵 생성/검증 코드를 읽고, 저장된 일반차량 결과와 파일 해시를 대조했다.
- audit 전용 cache venv에 Gymnasium 1.2.3을 설치했다. 전역 Python/기존 학습 환경은 바꾸지 않았다. CPU 검사만 수행했고 별도 결과 경로 외의 맵을 재생성하지 않았다.
- audit 실행 시각은 [provenance](research_checks/KC-AUDIT-20261110-01/evidence/provenance.json)와 summary 종료 시각에 남겼다. 새 finite/live/고속도로/정책·GAE 결과를 위에 반영했다.
- 후속 CPU 가중치 검사에서 기존 고속도로 model.pt는 현재 31-D hybrid 구조에 로드됨을 확인했다. [shape·SHA·호환성 기록](research_checks/KC-AUDIT-20261110-01/evidence/legacy_checkpoint_inspection.json)을 추가했으며 정책 재평가는 하지 않았다.
- RQ1/2 필수·RQ3 선택, 과제 후보, 정책/환경/지표/비용/누출 통제와 후속 작업 완료 기준을 작성했다. 실제 정책 학습·전문가 생성·10M 수집은 0이다.
- README에 현황→계획→실험 인덱스 안내를 추가했다. 결과 파일과 Markdown 링크를 검증하고 KC-DOC-01을 완료로 갱신했다. 다음은 KC-01이며 아직 착수하지 않았다.
- [문서 최종 검사](research_checks/KC-AUDIT-20261110-01/DOCUMENT_CHECKS.json)에 링크/절 anchor·원본 해시·diff 검사 결과를 남겼다.

## 이후 기록 규칙

매 작업 전에 계획/현황을 읽고 해당 ID를 진행 중으로 갱신한다. 장시간 실행은 먼저 실험 ID·설정·시작 상태를 등록한다. 종료 후 실제 조건·검증·결과·다음 행동을 기록한다. 기존 결정/사람 메모/실패·중단·무효 실행을 지우지 않는다. 중요한 설계·안전 설정 변경은 비교 가능성과 이전 결과 처리까지 기록한다. 기대 성능을 완료 결과로 쓰지 않는다.
