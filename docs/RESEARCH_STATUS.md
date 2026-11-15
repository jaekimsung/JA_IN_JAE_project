# K-CITY 연구 현황

<!-- KC-SETTINGS-20261115-01 -->

2026-11-15 이후 최신 완료 기록: **추가3seed pilot 집계 및 본 실험 과학 설정 확정 완료**. [확정 설정·실제 결과](research_checks/KC-SETTINGS-20261115-01/README.md). 아래 과거 미실행·후속동결 문구는 당시 단계의 이력이다. **본 데이터 수집/본 BC·PPO 미시작, launch_ready=false**. 본 실행기·GPU 장기재개·저장/원격백업 검증은 다음 운영 단계로 남긴다.

- **요청된 후속 범위(2026-11-15):** 현재 seed22/33 pilot 학습·dev100 평가 완료 후, 3seed 결과 집계 → 본 실험 과학 설정 확정 → 진행 기록 → main commit·GitHub push까지 수행한다. 본 수집/본 학습은 시작하지 않는다. [후속 진도](research_checks/KC-SETTINGS-20261115-01/README.md). 아직 설정 확정·push 완료를 뜻하지 않는다.

마지막 갱신: **2026-11-14T23:30:40.325570+09:00**

## 1. 먼저 읽을 요약

- **추가 seed 실행 중(2026-11-15):** 2Hz/물리0.1초 고정,seed22/33의fresh BC1000·B2/B3각50k와같은dev100평가를순차실행한다. 동일pilot expert10k를공유하고기존seed11모델을이어받지않는다. [실행/진도 안내](research_checks/KC-06-SEEDS-20261115-01/README.md). 새추가실험의104개검사와사전점검은통과했다. 아직추가seed학습완료를뜻하지않는다.


- **2026-11-15 연구 범위 결정:** BC/PPO/BC→PPO 비교의 공통 정책 주기를2Hz로 유지하고 주기 비교 실험은 보류한다. 학습/평가 물리 tick0.1초, 기존 안전/관측/보상 계약 유지. 2Hz 최적성이나 정책 단독 안전성을 주장하지 않는다. 다음은 추가 seed의 재현성 확인·교통/백업 등 잔여조건 확정이며, 총비용/학습곡선과 수요 변화도 함께 비교한다.


- **후속 진단 완료:** B2-40k/B3-30k의 B/C 실패4건은초기필수차선변경미선택으로재현됐고,별도진단개입4건은모두도착했다. 최종BC/B2/B3의같은독립dev100개씩평가는각100/100완주·충돌/적색0이다. [최종 보고서](research_checks/KC-06-DIAG-20261115-01/README.md). 학습seed1개·중간불안정은남아있고본실험조건동결/1M학습은아직아니다. 아래실행중기록은당시이력이다.


- **KC-06 후속 진단 진행 중:** 각50k pilot 학습은 완료했다. B2 40k/B3 30k 실패 재현·차선 요청 개입(성능집계 제외),그리고 BC/B2/B3의독립dev100개씩평가를실행한다. 학습/설정수정은이번진단에서하지않고final자료를사용하지않는다. 실제진도는 `/home/heven/kcity_research_runs/KC-06-20261115-01/diagnosis_v1/STATUS.json`이다.


- **2026-11-15 실제 학습 시작:** fresh pilot expert10k·BC1000updates 완료. B2 2048전이/rollout1/optimizer320의 체크포인트를 확인했고 GPU에서 계속 실행 중이다. B3는 B2 50k 뒤 자동 진행한다. [진도 스냅샷](research_checks/KC-06-20261115-01/LIVE_VERIFICATION.json). 본1M 비교·final·과학 설정 동결은 아직 아니다.


- **KC-06 진행 중(2026-11-15):** 별도 pilot 실행기·fresh writer10k/BC·각50k PPO·저장/dev 평가를 준비해 실행한다. 본 RQ 실험은 미착수, 최종 동결은 아직 아니다.

- **현재 단계: KC-05 완료, 다음 KC-06(각 50k 시험 학습·feasibility/비용 pilot).** [수집/복구 계약](KCITY_DATA_PIPELINE.md) · [실제 결과](research_checks/KC-05-20261114-01/README.md).
- 73-D만 사용하는 결정적·메모리 없는 B0와 수집기·JSONL/NPZ/event shard·BC loader를 구현했다. 필수 State/next, 원본 행동, mask, 시드/UID를 보존한다. 기존 env/PPO/BC/map/model은 이번 단계에서 수정하지 않았다.
- **100개 회귀 검사 통과.** 실제 6개 Episode에서 **602전이(train303/val299), 10개 확정 shard**를 수집했고 모두 도착했다. AV 충돌/적색/unknown0, TLS통과10, 실제LC4다. 동일 contract 내의 품질·분할·복구를 검증한 소량 debug 자료다.
- red 관측145결정·선행차78결정·정지26결정을 기록했다. 실제 자료303/299개가 BC tensor/loss를 통과했고 weight·optimizer는 변하지 않았다. 본학습 자료로 승격하거나 10M에 합산하지 않는다.
- 수집20→50전이 재개에서 중복 없이50개를 확보했고, 중단 없는 실행과 관측·행동·현재/다음 State·사건이 정확히 같았다. partial·손상·조작 summary·split 누출·동시 writer도 검사했다.
- **본 비교 학습·전문가 pool·final 평가는0**이다. 이번 수집/BC forward의 optimizer는0이며, 회귀 검사의 기존 소형 gradient fixture는 구분한다. 다음 KC-06에서 학습 CLI/주기 저장·dev 평가를 연결하고 첫50k 시험 학습을 진행한다.
- 남은 것은 교통 충분성(일부 초기HV8/9<10)·보상/정지/양보·GPU/장기/메모리·10k writer·90case feasibility·원격 백업·전역 release 병합·최종 동결이다. `training_ready=false`, commit/push/외부 업로드는 없다.

설계 문서는 [연구 계획](RESEARCH_PLAN.md) → [데이터 명세](DATA_COLLECTION_SPEC.md) → [실행 프로토콜](EXECUTION_PROTOCOL.md) → [결과·컨설팅](RESULTS_AND_CONSULTING.md), 실제 결과 인덱스는 [EXPERIMENTS.md](EXPERIMENTS.md)다. 11/10 audit·11/14 설계 점검과 이번 실행 결과를 구분한다.

## 2. 단계별 상태

상태 어휘: `미착수 / 진행 중 / 검증 대기 / 완료 / 차단 / 보류`. 코드만 작성한 상태를 검증 완료로 표시하지 않는다.

| 작업 ID | 작업 | 상태 | 확인 근거·산출물 | 관련 파트 | 다음 행동 |
|---|---|---|---|---|---|
| KC-DOC-02 | 데이터·수집·학습·평가·제출 실행 설계 | 완료 | 세 상세 명세·KC-DESIGN-20261114-01·[최종 검사](research_checks/KC-DESIGN-20261114-01/DESIGN_CHECKS.json) | 전체 | KC-01/G1 구현과 검증부터 이어감 |
| KC-DOC-01 | 현재 구현 조사·연구 설계·문서 체계 | 완료 | 세 문서·README 안내·KC-AUDIT-20261110-01 | 전체 | 아래 우선 작업으로 이어감 |
| KC-01 | 경로/seed/제어 계약 고정(1단계) | 완료 | [설정](../configs/kcity/v1/README.md)·[실행 결과](research_checks/KC-01-20261114-01/README.md)·16개 회귀 검사 | 환경·교통 | 최종 수요/학습 설정은 pilot 뒤 동결; KC-02 완료로 연결 |
| KC-02 | K-CITY Gym 환경 | 완료 | [환경 안내](KCITY_ENV.md)·[결과](research_checks/KC-02-20261114-01/README.md)·32 tests·Gym·6 bounded cases | 환경 | 후보 구현 완료; 다음 KC-03, 최종 수요/보상은 KC-06 |
| KC-03 | GAE/종료/평가 신뢰성 | 완료 | [61 tests·GAE2.96·6cases·Gym](research_checks/KC-03-20261114-01/README.md) | PPO·평가 | 후보 지표 완료; 다음 KC-04, 최종 규칙/수요는 추가 검증 |
| KC-04 | 공통 actor의 BC→PPO | 완료 | [공통 정책·80 tests·전체 재개](research_checks/KC-04-20261114-01/README.md) | 학습 | 후보 API 검증 완료; 실제 expert/data 연결은 KC-05 |
| KC-05 | 관측 정렬 전문가·수집기 | 완료 | [100 tests·602전이·6도착·복구/loader](research_checks/KC-05-20261114-01/README.md) | 전문가·데이터 | 후보/소량 완료; 다음 KC-06 실제50k 시험 학습 |
| KC-06 | 수요/보상/규모 pilot | 진행 중 | B0/데이터/학습 API의 작은 검사 완료,실제학습 CLI·pilot은미실행 | 실험 운영 | CLI/dev/주기저장 연결→각50k 시험학습·feasibility/비용 측정 |
| KC-07 | RQ1 본 비교 | 차단 | 실제 expert/data·통합 실행·pilot/동결 미완료 | 학습·분석 | KC-01~06 완료 후 새 실험 ID로 시작 |
| KC-08 | RQ2 고정 정책 수요 평가 | 차단 | 평가할 K-CITY 학습 정책 없음 | 평가 | KC-07 정책과 독립 final case 준비 |
| KC-09 | RQ3 데이터 구성 비교 | 보류 | 필수 RQ1/2 우선 | 데이터·학습 | 같은 λ0 풀·N·업데이트 통제 설계 유지 |
| KC-10 | 10M 데이터셋·최종 재현성 | 미착수 | debug602전이 생성;본10M 목표분자0 | 데이터·보고 | 전문가/학습/평가/추가 기록을 목적별 집계 |

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
| seed 재현성 | 부분 구현 | 새 K-CITY는 seed42 반복 reset 초기 상태/관측 일치,43 상이. 기존 고속도로는159/161 불일치 이력 유지 | K-CITY의 제한 seed·단일 PC 검증. 기존 고속도로 RNG는 수정하지 않음 |
| K-CITY Gym 연결 | 부분 구현 | 독립 `SumoKCityEnv`·73-D·제어/종료를 검사. 기존 train/test/collector는 고속도로 유지 | KC-02 후보 완료; 학습/수집 실행기·최종 보상/평가는 후속 |
| BC 개별 학습 기반 | 부분 구현 | 기존31-D MSE 예제 보존. 신규73-D common hybrid BC loss·mask·optimizer/resume 후보 검사 | KC-05 debug303/299전이 forward 호환 확인. 실제 pool·BC선택정책은 아직 없음 |
| PPO 기반·저장 | 부분 구현 | train 설정은 [256,256] ReLU hybrid. sampling/logprob 재계산 일치. 기존 model.pt도 현재 31-D hybrid에 CPU 로드 가능 | KC-03에서 GAE/예산/독립 평가 계약과 case panel 수정·검사. 기존 `save()`는 weights-only. 새 KCityRunner는 optimizer/RNG/부분 rollout/환경 replay까지 재개 검사. 로드 가능성이 K-CITY 재사용 가능성을 뜻하지 않음 |
| BC 초기화 PPO | 부분 구현 | 신규73-D 공통 masked policy86,022 parameters,actor 이식·fresh head/std/optimizer 확인 | 실제 전문가 데이터의 BC와 연구 B3 초기화는 후속. 기존31-D BC/PPO 이식 불가 이력 유지 |
| 행동·제어 기록 | 부분 구현 | 고속도로는 raw→clip→속도 명령, LC quantize/자체 간격 gate. `speedMode=0/laneChangeMode=0` 실측 | ‘모든 안전 기능 off’라는 주석은 부정확. SUMO 1.28 mode 0은 일부 검사를 유지함 |
| AV 평가/수집 | 부분 구현 | 신규 B0·필수 State/next·UID/시드·JSONL/NPZ/event shard·복구·loader 검증 | 실제pool·PPO train logger·최종release/원격backup은후속 |
| K-CITY 10M 목표 | 미구현 | 현재 `data/dataset.npz`는 **4,941전이·10 Episode·31-D의 고속도로 자료** | 전문가/학습/평가별 K-CITY 고유 전이는 측정 전 |
| 현실 일반화·신호 실측 일치 | 확인 불가 | 실측 교통량/현시표·현장 주행 자료 없음 | 수요 변화 실험도 아직 미실행. 실제 도로 성능으로 해석 금지 |

### 제어 분담에서 특히 주의할 점

데모의 mode는 실제 **31/1621**이고, 고속도로는 **0/0**이다. 고속도로는 자체 차선 안전 gate도 켜져 있으므로 설정 숫자만으로 개입이 없다고 주장할 수 없다. SUMO의 mode 0은 ‘대부분의 검사 off’이며 bit 5/6의 반대 의미 때문에 ‘전부 off’와 다르다. [버전 1.28 공식 정의](https://github.com/eclipse-sumo/sumo/blob/v1_28_0/docs/web/docs/TraCI/Change_Vehicle_State.md)를 기준으로 해석한다.

새 K-CITY 후보 환경에 31/512를 적용하고 실제 조회로 확인했다. 기존 데모/고속도로는 변경하지 않았다. 모든 방법에서 같은 설정으로 수행하고 제어 보정을 완전히 분리할 수 없으면 시스템 수준 결과로 보고한다. `lane_change_applied=True`는 기존 코드에서 명령 API가 성공했다는 뜻이며 물리적 차선 변경 완료를 보장하지 않는다.

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
| A/B/C B0 소량도착 확인 | 독립train/val6case도착;충분한수요/분포·학습정책은미검증 | KC-06 90case feasibility·각50k 학습 |
| 신호·정지선·내부 Lane 이벤트 | 0.1초 추적·강제 적색 진입 fixture 확인; 모호한 매핑/정지·양보 준수는 미완료 | KC-03에서 평가 taxonomy·분모·경계 검증 확장 |
| BC/PPO 공통 계약 검증 완료 | 새 KCityPolicy의 actor·고정 전처리·mask·head/std/optimizer 비교 확인 | KC-05 실제 데이터/BC 선택·학습 실행기에 같은 계약 연결 |
| truncation GAE 수정 완료 | 기존101.96→2.96,원래 reward·경계 분리 검사 | 이후 KC-04/학습 실행기에서도 새 buffer API와 실제 next value 계약 유지 |
| 연구 실행 seed 할당 | K-CITY 환경별 seed·초기 hash 구현; 학습/평가 panel과 policy RNG는 미연결 | KC-03/04에서 독립 panel·정책/학습 seed 연결 |
| λ0·배수·포화 수요 | finite 2/3배와 연속 수요 일반화가 다름 | B0로 기준/증가 수요 feasibility 확인 후 600/900/1200 후보 확정 또는 수정 |
| 73-D·보상·기한·목표 후보 | 미검증 값을 최적값으로 쓸 위험 | KC-06 전에 후보로 표시, pilot 후 config/결정 기록 동결 |
| 실제 작업 자원 | 현재 측정은 배경 교통뿐; AV/PPO/수집 비용 불명 | 50k pilot 및 새 schema shard 측정. 학습 시간·용량은 측정 전 |
| 실행 의존성 | 기본 Python에는 Gymnasium/TensorBoard 없음 | audit에만 별도 cache venv+Gymnasium 1.2.3 사용. BC 학습용 환경은 후속 준비 |
| 학습 재개/모델 선택 | 새 Runner의 전체 재개는 작은 CPU 검사 통과; 실제 best 선택·주기 저장은 미연결 | 실제 validation/data ID·GPU/장기/STOP pilot·최종 모델 선택 연결 |
| 수업 충돌률 경계 | 준비 ≤5%, 최종 평가 <5% | 우선 <5% 사용·담당 확인. 결합 완주 지표 목표는 별도 동결 |
| 현장 자료 | 현재 신호·차선·수요를 실측 운영이라고 주장할 수 없음 | 필요하면 현시표·실측량·최신 차선 운영 확보; 주실험은 합성 조건으로 명시 |

## 6. 바로 다음 작업 5개

1. **KC-01은 완료했다.** [결과](research_checks/KC-01-20261114-01/README.md)를 확인하고 이후 구현에서 해당 계약·회귀 검사를 유지한다. 최종 연구 조건 동결과 전체 G1 통과는 아직 아니다.
2. **KC-02도 완료했다.** [검사 결과](research_checks/KC-02-20261114-01/README.md)의 범위·후보 보상·교통 한계를 유지한다. KC-03도 후보 검사를 완료했으며 본 학습은 시작하지 않는다.
3. **KC-04도 후보 검증을 완료했다.** 공통 masked actor·BC 초기화·optimizer/RNG/부분 rollout/환경 재개의 [실제 범위](research_checks/KC-04-20261114-01/README.md)를 유지하고 실제 데이터 연결로 이어간다.
4. **KC-05도 후보 구현·소량 검증을 완료했다.** 실제602전이·100개검사·복구/BC입력의 [범위](research_checks/KC-05-20261114-01/README.md)를 유지한다. 본pool/10M로집계하지 않는다.
5. **P0 / 다음 KC-06 — 실제50k 시험학습·제한 pilot와 사전 동결.** 선행: 위 기반. 완료: λ0/증가 수요 수행 가능성·50k pilot·I/O 비용을 측정하고 3 seed/예산/목표/final 패널을 동결. 이후에만 RQ1→RQ2→선택 RQ3를 실행.

## 7. 결정 기록

2026-11-14에는 기존 RQ·모델 비교 방향을 유지하면서 실행 계약을 구체화했다. 실제 적용은 G1~G5 이후다.

| 날짜 | 결정 | 이유 | 다른 대안 | 영향 | 관련 실험 |
|---|---|---|---|---|---|
| 2026-11-15 | 판단2Hz를세방식의공통통제조건으로유지,주기실험보류 | 연구질문은주기최적화가아닌학습방식비교;단일seed pilot 수행가능성확인 | 2/5/10Hz factorial 확장 | 결론을2Hz/SUMO안전/정의된과제에한정,추가seed·비용·수요검증은유지 | KC-06 후속·본RQ 설계 |
| 2026-11-14 | KC-02 후보 환경만 구현·검증, 학습은 후속 | 단계별 요청, 비교 기반 신뢰성 우선 | 곧바로 PPO/대량 수집 | KC-03 다음, updates0/readiness false | KC-02-20261114-01 |
| 2026-11-14 | 부당 대기 보상은0으로 보류 | 정당 신호 대기/양보를 검증 없이 벌점화할 수 없음 | 속도0이면 무조건 벌점 | 보상 부분 구현, KC-03/06 판정·pilot 필요 | KC-02-20261114-01 |
| 2026-11-14 | KC-01만 구현·검증하고 다음 단계로 보고 | 사용자의 단계별 진행 요청 | 한 번에 환경/학습까지 시작 | G1 부분 충족; KC-02는 미착수 유지 | KC-01-20261114-01 |
| 2026-11-14 | SHA256 component seed와 독립 Poisson/OD/type stream | 가벼운 표준 라이브러리·전역 RNG/worker/정책과 분리 | 예시 SeedSequence 그대로 의존 | 알고리즘 ID/버전 명시. 요청 결정성만 검증, 실제 reset은 다음 단계 | KC-01-20261114-01 |
| 2026-11-14 | 필수 State/기본 transition/NPZ key 보존, JSONL의 모든 next 명시 | 평가6번 문서의 필수 항목과 경계 검증 우선 | 중간 next 생략·기존19/31-D 표기 고정 | full State의 비용을 pilot에서 측정; 73-D 확장은 컨설팅 확인 | KC-DESIGN-20261114-01 |
| 2026-11-14 | action_raw는 정책 원본, bounded env_input과 실측을 분리 | 수업의 ‘정책 원본’ 정의와 PPO logprob 일관성 | 현재 collector처럼 사전 clip 후 원본으로 명명 | 새 loader/collector schema 분기 필요; 옛 고속도로 코드는 보존 | KC-DESIGN-20261114-01 |
| 2026-11-14 | 10M=expert pool1M+PPO6M+fixed archive3M | 학습 예산과 제출 데이터 수량을 분리 | 평가/복제/HV/substep을 합산 | 별도 archive split; final/pilot은 기본10M 분자에서 제외 | KC-DESIGN-20261114-01 |
| 2026-11-14 | 주 final은 budget-end, B0~B3 총3000 Episode 후보 | 같은 예산의 비교·사후 선택 방지 | final 최고 정책만 선택 | dev-best는 별도 보조 실행·비용; 3 seed 불확실성 보고 | KC-DESIGN-20261114-01 |
| 2026-11-14 | 설계 완료와 실행 readiness를 분리 | 전용 환경/실행기 미존재 확인 | 문서의 가상 CLI를 실행 가능 명령으로 표시 | G1~G5 증거 후 LAUNCH_READY, 이번에는 만들지 않음 | KC-DESIGN-20261114-01 |
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

### 2026-11-14

- KC-DOC-02 시작. 평가 문서의 필수 State/transition·10^7 데이터·30초 이상 주행 영상·Hugging Face/프로젝트 페이지·최종 제출 요건과 컨설팅 운영을 확인했다.
- 현재 HEAD `5e7a46c`, 작업 시작 시 clean tree. 기존 연구 설계와 실패 기록을 유지하면서 실행 전 상세 명세를 작성한다.
- 새 `DATA_COLLECTION_SPEC.md`, `EXECUTION_PROTOCOL.md`, `RESULTS_AND_CONSULTING.md`에 필수 필드·절대 State·73-D index·action/next 계약·10M 장부·BC/PPO 비교·독립평가·영상·컨설팅·제출까지 상세화했다.
- 기본 연구 방향과 과거 audit/실패 이력을 보존했다. 현재 없는 CLI/config는 구현할 계약으로 명시했고 실제 수집/학습 명령으로 실행하지 않았다.
- 이번 결과의 실험 ID는 KC-DESIGN-20261114-01이다. 새 source/map/runtime 수정과 학습/수집/외부 업로드는 없었다.
- 필수 transition19개·기본 NPZ11개 key, 73-D 블록 합계, 10M 수집/3000 Episode 평가 장부, Markdown 링크와 기존 source 불변을 검증했다. runtime readiness는 false로 유지하며 새 수집/학습은 시작하지 않았다.

### 2026-11-14 — KC-01 첫 구현

- local branch `codex/kcity-kc01-20261114`에서 기존 미완료 문서 변경을 보존하며 신규 설정/로더/검사기/회귀 검사를 작성했다.
- A/B/C·176개 배경 route·신호 link index·내부 Lane·짧은 Edge·목표 위치를 검사했다. Poisson 요청의 재현·다른 case/namespace/수요 배수와 OD/type stream 분리를 검증했다.
- 16개 회귀 검사가 통과했다. 첫 import 충돌과 이전 검사 로그를 보존했고 명시적인 scripts package로 해결했다.
- 두 차례의 A/B/C smoke를 별도 출력으로 보존했다. 최종 v2에서 출발/도착·31/512 mode·필수 LC를 모두 확인했다. 배경 교통과 학습 정책은 사용하지 않았다.
- 학습/전문가 수집0, 새 Gym/73-D/GAE/BC/writer는 미구현. 다음 KC-02로 인계하며 이번 단계에서 멈춘다.

### 2026-11-14 — KC-02 환경 구현

- 독립 TraCI connection·73-D·setAcceleration·차선 mask·전체 State/관측 분리·route occurrence 진행·0.1초 사건 추적·종료/wrapper를 구현했다. [사용 안내](KCITY_ENV.md).
- KC-01 포함32개 검사와 표준 Gym 검사(render 제외)가 통과했다. 강제 적색/충돌/제거/이탈 fixture는 성능 평가에서 제외했다. 초기 Gym 검사에서 `spec` 예약 속성 충돌이 발견되어 `contract`로 수정했으며 실패 로그도 보존했다.
- 최종 source로 A/B/C×배경 교통 유무6회 모두 도착했다. 앞선 두 통합 실행도 별도 보존했다. HV 급제동 경고1건과 B 교통 reset HV5대를 기록했다. 수요 feasibility나 안전성 전체 통과로 확대하지 않는다.
- 보상 중 부당 대기 판정은0이며 전체 보상·수요·schema는 최종 동결 전이다. JSONL은 engineering trace이고 전문가 dataset이 아니다.
- 학습/전문가 수집/외부 업로드0. 기존 source/map/data/model을 보존하고 다음 KC-03으로 인계한다. 실제 검사·해시는 [최종 점검](research_checks/KC-02-20261114-01/FINAL_CHECKS.json)에 남긴다.

### 2026-11-14 — KC-03 종료·GAE·평가

- buffer의 bootstrap/trace 경계·terminal V를 분리하고 PPO의 truncation reward 수정을 제거했다. 과거 source를 보존해101.96→2.96을 재현했다. 마지막 rollout을 남은 예산에 맞추며1행 정규화도 finite로 확인했다.
- 평가 환경은 독립 인스턴스를 요구한다. 학습 reset을 추가하지 않으며 평가 중Python/NumPy/Torch RNG를 보존한다. global TraCI를 사용하는 기존 highway launcher는 기본 정기 평가 상태에서 실행 전 안내 오류를 낸다. [호환성 안내](KCITY_EVALUATION.md).
- K-CITY 환경의0.1초 측정·동시 사건 보존과 별도 metric/case evaluator를 추가했다. 61개 검사·Gym·6회 scripted 주행이 통과했다. 원시 분모·unknown/무효 처리·weights 불변을 검사했다.
- dev/final 총400개 panel은 생성만 하고 실행하지 않았다. C초기HV4대·정지/양보/부당 대기 판정 등 남은 한계를 유지했다. 본 학습/optimizer steps/전문가 dataset0. 다음 KC-04이며 [최종 검증](research_checks/KC-03-20261114-01/FINAL_CHECKS.json)에 근거를 남긴다.

### 2026-11-14 — KC-04 공통 정책·초기화·재개

- 종전 BC/network와31-D 데이터를 보존하고 신규 KCityPolicy·BC/PPO/Runner·learning 후보 설정·검사기를 추가했다. 실제 actor/mask/고정 전처리와 strict 초기화·head/std/새 optimizer 조건을 검사했다.
- SUMO 직접 save/load는 lane mode·미래 HV가 달라져 채택하지 않았다. 공식 저장 제약과 probe를 기록하고 현재 Episode의 결정적 행동 replay+exact snapshot gate로 재개를 구현했다. 물리/HV mix를 바꾸지 않았다.
- 첫 bool mask 검사 문제와 save/load 실패 로그를 보존했다. 최종80개 검사·Gym·별도 BC/PPO 연속/복원 비교가 통과했다. 기본 모델86022 parameters,검증용모델[16,16].
- 별도 통합검사의 BC4/PPO9 optimizer 작업과30개 수집 호출은 검증 비용이다. 본 비교 학습 전이·전문가 dataset·final 평가0. `/home/heven/kcity_research_runs/KC-04-20261114-01/validation_v1/`에 fixture를 보관했으며 외부 업로드는 없다.
- GPU/장기 replay·학습 CLI·실제 validation best 선택·주기 checkpoint/백업과 전체 readiness는 미완료다. 다음 KC-05이며 [최종 검사](research_checks/KC-04-20261114-01/FINAL_CHECKS.json)에 source/문서/파일 보존 근거를 남긴다.

### 2026-11-14 — KC-05 실제 전문가·소량 수집

- OBS73-only memoryless B0·full State/next 기록·immutable JSONL/NPZ/event shard·SQLite UID/split index·복구/BC loader를 구현했다. 기존runtime source는변경하지 않았다.
- 최초6개empty/traffic probe 모두도착. 독립expert_train/val각A/B/C의6개Episode에서도모두도착해602전이·10shard를확정했다. red145/선행차78/정지26결정·실제LC4를기록했다.
- 100개회귀검사·602행전수JSON/NPZ/사건/출처검사·BCforward만수행한호환검사가통과했다. 조작summary와unknown을BC에넣지않고실패/미완결raw를보존했다.
- 별도run20→50resume에서중단없는물리trace와일치했다. 원격검증·실제pool/학습은미실행. 이전KC-04의소형gradient fixture재실행과이번수집/forward optimizer0을구분했다.
- 자료는 `/home/heven/kcity_research_runs/KC-05-20261114-01/validation_v1/`에있고debug/10M집계제외다. 다음KC-06에서첫50k시험학습을진행한다. [최종검사](research_checks/KC-05-20261114-01/FINAL_CHECKS.json)에보존/출처/검사결과를남긴다.
