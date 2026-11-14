# K-CITY 실험 인덱스

[연구 계획](RESEARCH_PLAN.md) · [현재 현황](RESEARCH_STATUS.md)

계획은 결과가 아니다. 일반차량 교통 검증, 고속도로 예제, K-CITY 학습 AV를 분리한다. 실행 상태는 `계획 / 실행 중 / 완료 / 실패 / 중단 / 무효`를 사용한다. 실패·중단·무효 실행도 삭제하지 않는다. 같은 설계라도 조건을 바꿔 다시 실행하면 새 ID를 붙이고 이전 ID와 연결한다.

## 1. 요약 인덱스

| 실험 ID | 연결된 RQ·가설 | 정책·비교 조건 | 상태 | 주요 결과 | 설정·로그·결과 링크 | 해석·제한 |
|---|---|---|---|---|---|---|
| KC-05-20261114-01 | RQ1 expert/data 기반 | 73-D-only B0·소량 수집·shard/loader/품질/복구 | 완료 | 100 tests·602전이·6도착·20→50resume일치 | [결과](research_checks/KC-05-20261114-01/README.md)·[summary](research_checks/KC-05-20261114-01/validation_v1/SUMMARY.json) | debug 자료,BCforward만,연구학습/10M분자0 |
| KC-04-20261114-01 | RQ1 초기화·재개 기반 | 공통 masked actor·BC 이식·전체 resume fixtures | 완료 | 80 tests·Gym·행동/logprob차이0·전체 재개 일치 | [결과](research_checks/KC-04-20261114-01/README.md)·[summary](research_checks/KC-04-20261114-01/validation_v1/SUMMARY.json) | [16,16] 검증용 optimizer 작업만,연구 학습/전문가0 |
| KC-03-20261114-01 | RQ1/2 평가 기반 | GAE·종료·예산·독립평가·사건 지표 fixture | 완료 | 61 tests·Gym·GAE101.96→2.96·6회도착 | [결과](research_checks/KC-03-20261114-01/README.md)·[summary](research_checks/KC-03-20261114-01/integration_final/SUMMARY.json) | optimizer0; 지정 행동 검사,final미실행 |
| KC-02-20261114-01 | RQ1/2 실행 기반 | 독립 K-CITY Gym·73-D·제어/종료·작은 검사 | 완료 | 32 tests·Gym 통과,6 scripted cases 도착 | [결과](research_checks/KC-02-20261114-01/README.md)·[summary](research_checks/KC-02-20261114-01/integration_final/SUMMARY.json) | B0/학습 아님; updates0,보상/수요 후보 |
| KC-01-20261114-01 | RQ1/2 실행 기반 | A/B/C·seed·제어 계약·route 연결/위치·짧은 SUMO route smoke | 완료 | 16개 회귀 검사·A/B/C 도착/위치·B/C LC 확인 | [실행 기록](research_checks/KC-01-20261114-01/README.md)·[summary](research_checks/KC-01-20261114-01/validation_v2/SUMMARY.json) | 배경차 없음·IDM+지정 Lane 명령; 학습/B0/Gym 아님, learning updates0 |
| KC-DESIGN-20261114-01 | RQ1~3의 실행 설계 | 수업 평가·컨설팅 요구 대조,필수 컬럼·10M 장부·gate·결과 명세 | 완료 | 시행 전 설계·읽기 전용 검사. 새 수집/학습/시뮬레이션0 | [데이터 명세](DATA_COLLECTION_SPEC.md), [프로토콜](EXECUTION_PROTOCOL.md), [결과·컨설팅](RESULTS_AND_CONSULTING.md), [검사](research_checks/KC-DESIGN-20261114-01/READ_ONLY_CHECK.json) | 코드/실험 준비 완료를 의미하지 않음. G1~G5 미통과 |
| KC-AUDIT-20261110-01 | RQ1~3의 구현 기반 | 구조·과거 hash·새 seed43 finite/live·고속도로·정책/GAE fixture | 완료 | 177/177 도착, live 소실0; BC 이식 불가·seed 불일치·GAE 누출 확인 | [summary](research_checks/KC-AUDIT-20261110-01/evidence/summary.json), [provenance](research_checks/KC-AUDIT-20261110-01/evidence/provenance.json), 아래 상세 | audit 완료이며 학습 기반에 결함이 없다는 뜻은 아님 |
| KC-HIST-SIGNALS-20261101 | 환경 기반(학습 가설 검증 아님) | before/after × finite 수요1/2/3/random_OD ×seed0/1/2 | 완료 | after12회 2,124/2,124 도착·충돌기록0; before12회 중4회 판정 실패·충돌기록5 | [저장 summary](../maps/kcity/reports/signals_validation/summary.json), [설계 보고](../maps/kcity/reports/SIGNAL_DESIGN.md) | 이번에 다시 실행한 결과 아님. 전체24회를 무충돌이라고 쓰지 않음 |
| KC-HIST-LIVE60 | 환경 기반 | IDM 순환,3 s 요청·60대 상한,seed0/1/2 각3,600 s | 완료 | 저장된 3 runs 충돌/텔레포트0·빨간 차량 소실0 | [저장 결과](../maps/kcity/reports/live_demo_validation.json)의 `runs` | vehicle-step collision counter, 유한 시간 데모 |
| KC-HIST-LIVE80 | 환경 기반 | 같은 파일의 80대 상한 시험 | 실패 | 일부 trial에 충돌 차량-스텝 집계가 남아 80대 기본값 기각 | [기각 trial](../maps/kcity/reports/live_demo_validation.json)의 `rejected_cap80_trials` | 개별 trial의 실제 결과를 원문에서 확인; 고유 충돌 사건 수로 바꾸지 않음 |
| HW-LEGACY-20260907 | 고속도로 참고 | 기존 PPO 학습·평가 로그 | 완료 | 마지막 저장 평가194,560전이, success0·timeout1.0 | [eval CSV](../results/run_20260907_202220/eval_log.csv), [train CSV](../results/run_20260907_202220/training_log.csv) | 마지막 평가점이지 최종 학습 예산 완주를 증명하는 값은 아님. K-CITY 비교에서 제외 |
| KC-PILOT-v1 | RQ1/2의 수행 가능성·비용 | B0 A/B/C 및 λ 후보, 제한 PPO/직렬화 pilot | 계획 | **미실행·측정 전** | [계획 7·10절](RESEARCH_PLAN.md#7-데이터-분리-수요-예산) | 구현·정확한 config·실제 실행 ID를 먼저 확정 |
| KC-RQ1-v1 | RQ1/H1, 실험 A | B0/B1/B2/B3,3 seeds,동일 λ0/PPO 예산 | 계획 | **미실행** | [방법·예산](RESEARCH_PLAN.md#6-전문가bcppo의-통제-설계) | 목표 도달·종료 성능·총비용 분리 |
| KC-RQ2-v1 | RQ2/H2, 실험 B | 고정 정책,λ0/증가1/증가2,새 evaluation cases | 계획 | **미실행** | [수요·평가](RESEARCH_PLAN.md#71-시드와-수요) | 추가 학습/새 도시 일반화 없음 |
| KC-RQ3-v1 | RQ3/H3, 추가 실험 C | 같은 λ0 풀·N·BC/PPO 예산,자연/균형 구성 | 계획 | **미실행·주실험 뒤 검토** | [구성 실험](RESEARCH_PLAN.md#74-선택-실험-c) | 전문가 실력·고수요 노출 효과와 분리 |

`-v1`은 연구 설계의 계획 ID다. 실제 실행은 예를 들어 `KC-RQ1-v1-B3-seed11-<시각>`처럼 독립 ID를 만들고 config/시작 시각을 먼저 등록한다. 계획 표에 기대 성능을 채우지 않는다.

### KC-DESIGN-20261114-01: 시행 전 상세 설계 기록

- 목적/기준: 6·7번 수업 자료의 필수 컬럼·절대 State·10M·평가·영상·제출·컨설팅 요구가 데이터 계약과 실행 순서에 빠짐없이 연결되는지 확인한다.
- 코드 식별: HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`, 시작 시 clean tree, 이후 Markdown/읽기 전용 검사 파일만 추가·갱신. 기존 runtime·학습·맵 코드는 수정하지 않는다.
- 시작 근거: [READ_ONLY_CHECK](research_checks/KC-DESIGN-20261114-01/READ_ONLY_CHECK.json)의 `time`, source SHA·SUMO1.28·disk/entrypoints. 이 시각은 실제 code 변경 없이 점검한 시각이며 11/10 audit를 재실행한 시각이 아니다.
- 실행: 수업/연구 문서 읽기, 필수 key 대조·index/수량 계산·로컬 문서 링크·source hash 검증만 수행. 새 SUMO runs=0, 전문가 생성=0, PPO 전이/업데이트=0, BC 업데이트=0. seed·policy·평가 Episode 수는 해당 없음.
- 결과: 데이터 컬럼·73-D 순서·10M 장부·S0~S7·G0~G6·결과/컨설팅/제출 명세. 실제 모델·raw driving dataset·영상은 생성하지 않았다.
- 한계/해석: K-CITY 환경·전용 실행기·preflight는 아직 없다. 설계 검사를 통과해도 실행 readiness gate 통과는 아니다. H1/H2/H3 지지 여부는 미판단이다.
- 문서/코드 무변경 최종 검증: [DESIGN_CHECKS.json](research_checks/KC-DESIGN-20261114-01/DESIGN_CHECKS.json)에 종료 시각과 결과를 남긴다. 데이터 크기/학습시간은 pilot 측정 전이며 root free만으로 시행 가능하다고 쓰지 않는다.

## 2. KC-AUDIT-20261110-01 상세

### 사전 계획과 실제 범위

- 목적: 문서의 구현 주장과 실제 코드·설정·로그 대조, 연구의 첫 구현 작업 정의.
- 변경 변수: 새 finite/live 교통의 SUMO seed43; 고속도로 reset seed 고정 반복; 학습 없는 BC/PPO·GAE fixture.
- 고정 조건: 기존 K-CITY net/routes/signals/scenery·차량 모델·기본 안전 설정. audit 전후 검사 파일 SHA 불변. 고속도로는 별도 출력 폴더에 생성했다.
- 성공 기준: 조사 결과·재현 명령·결함·제한을 보존하는 것. AV 성능 성공 판정이 아니다.
- 최초 계획은 이 문서에 실행 전 등록했고, 종료 후 실제 값으로 보완했다.

### 식별·버전·자료

- HEAD `d81a9a962a29898fbd768d0168eaacd6862a6d8e`, branch main. 실행 시 연구 문서/audit script와 기존 사용자 파일이 미추적이므로 **clean commit 실행이 아니다**. 초기 작업 트리와 검사 source SHA는 [provenance.json](research_checks/KC-AUDIT-20261110-01/evidence/provenance.json)에 있다.
- SUMO 1.28.0, TraCI API22·동일 bundled tools. Python3.10.12; Gymnasium1.2.3은 audit 전용 cache venv에 설치했다. NumPy/Torch 및 실제 import 경로는 [versions.json](research_checks/KC-AUDIT-20261110-01/evidence/versions.json), 설치 기록은 [dependency_install.log](research_checks/KC-AUDIT-20261110-01/dependency_install.log)에 있다.
- 정책 fixture는 CPU에서 모델을 만들고 sampling/value 계산만 수행했다. BC/PPO gradient updates=0, 전문가 생성=0, PPO 학습 전이=0. SUMO 교통 스텝과 고속도로 20개 검사 전이를 학습·전문가 데이터 수에 더하지 않는다.
- 사용 자료: 현재 맵/유한 routes, qualifier 기반 live route, 기존 고속도로 설정·NPZ·CSV. 평가/학습 분리형 K-CITY 데이터 버전은 아직 없다.
- 네트워크 SHA: `cfc9be136736b5f5e7874fce34992e90f9ac7d8d76422a7f67a27e2deb3e4894`.
- 신호 SHA: `0643c2047f47f032ad0f88fc2fea1dda5f9c49e93f4d3e24cc438ba1a2616489`.
- 기본 routes SHA: `dfb35f886fa2b5b669109122e50666e1a784d47e938cdbf0fd817e429756a2db`.
- 원본 스냅샷 9개 확인은 [source_snapshot_checks.json](research_checks/KC-AUDIT-20261110-01/evidence/source_snapshot_checks.json)에 별도 기록했다.

### 실행 명령과 시각

프로젝트 루트에서 사용한 실행:

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  /home/heven/.cache/kcity-research-audit-20261110/venv/bin/python -B \
  docs/research_checks/KC-AUDIT-20261110-01/run_audit.py \
  --output docs/research_checks/KC-AUDIT-20261110-01/evidence
```

실제 시작 시각은 provenance의 `started_at`, 종료는 summary의 `ended_at=2026-11-10T23:10:45.591986+09:00`다. 각 SUMO subprocess의 argv·returncode·wall time은 [finite command](research_checks/KC-AUDIT-20261110-01/evidence/finite_HV_seed43.command.json), [live command](research_checks/KC-AUDIT-20261110-01/evidence/live_IDM_seed43.command.json)에 있다.

다른 PC에서 다시 검사하려면 별도 Python 환경에 `gymnasium==1.2.3`과 적절한 NumPy/Torch, SUMO1.28 bundled tools를 준비하고 `--output`에 **존재하지 않는 새 경로**를 준다. 스크립트는 기존 결과 디렉터리를 덮어쓰지 않는다. 환경 준비 예:

```bash
python3 -m venv --system-site-packages /tmp/kcity-audit-venv
/tmp/kcity-audit-venv/bin/python -m pip install 'gymnasium==1.2.3'
# 이 venv에서 torch/numpy import와 sumo --version을 먼저 확인
PYTHONDONTWRITEBYTECODE=1 /tmp/kcity-audit-venv/bin/python -B \
  docs/research_checks/KC-AUDIT-20261110-01/run_audit.py \
  --output docs/research_checks/KC-AUDIT-20261110-01/recheck-new-id
```

CPU·설치·시스템 부하에 따른 wall time 차이는 예상되며, 새 결과는 별도 실행 ID와 함께 등록한다. 기존 `build.py/validate.py` 기본 출력은 원본/과거 결과를 갱신하므로 이번 audit 재현 대신 무조건 실행하지 않는다.

### 실제 관찰

| 검사 | 실제 결과 | 근거와 제한 |
|---|---|---|
| 맵·신호 구조 | 176 Edge,198 일반/346 내부 Lane,14 TLS,2 all-way stop; topology·signal structural errors0 | 정적 검사 + 실제 API probe. 최신 현장 지도 일치도 검사 아님 |
| 과거 after12 cases의 계보 | 12개 모두 net/signals/generated route hash 일치 | 과거 결과의 파일 연결을 확인한 것. 12회 재실행 아님 |
| 새 finite seed43 | 177/177 도착,미완료0,충돌기록0,teleport0 | 1,800 s·wall0.723 s·1회. [통계 XML](research_checks/KC-AUDIT-20261110-01/evidence/finite.statistics.xml) |
| 새 live seed43 | 600 s·wall3.455 s,빨간 차량1회 생성·경로연장4·소실/도착0,충돌/teleport0 | 3 s 요청,60대 pending 포함 상한. [live JSON](research_checks/KC-AUDIT-20261110-01/evidence/live_IDM.json) |
| 고속도로 실행 | 각 reset 뒤10 step=5 s,31-D·finite 관측,mode0/0 | [고속도로 stdout](research_checks/KC-AUDIT-20261110-01/evidence/legacy_env.stdout.log), 생성 맵은 evidence/isolated_highway 아래 |
| seed 반복 | 같은 Gym seed와 전역 NumPy seed에서도 초기 차량159/161·SHA 상이 | `_prefill_traffic` 무시드 RNG 영향. 두 번의 재현 실패로 현재 방식의 결정성 보장이 깨짐을 확인 |
| BC→PPO 이식 | 직접 load 실패,BC74,498 / PPO75,270 parameters | 기존 31-D·[256,256]의 실측. 73-D 후보의 parameter count가 아님 |
| hybrid logprob | 128개 표본의 sample/evaluate max 차이0; 가감속 latent 중14개가 Box 범위 밖 | PPO buffer의 raw와 적용 clip을 분리해야 함. 이 결과 자체가 PPO clipping 버그라는 뜻은 아님 |
| truncation GAE | 의도한 isolated advantage2.96 대신101.959999 | 다음 Episode reset value100이 누출되는 두 전이 fixture. 실제 정책 성능 영향량을 측정한 것은 아님 |
| 데이터·기존 학습 로그 | 고속도로4,941전이·10 Episode·31-D. 마지막 legacy eval194,560전이 success0/timeout1.0 | K-CITY 전문가/학습 자료로 재분류하지 않음 |
| 파일 보존 | 선택한 원본 코드·맵·자료의 실행 전후 SHA 변화0 | 이후 README 연구 안내 추가는 명시적 문서 변경. 과거 결과는 덮어쓰지 않음 |

관찰 사실: 교통 기반은 실행되고 학습 연결/호환성/재현성 결함이 남아 있다. 해석: 본학습 전에 계약·평가·GAE/seed·초기화를 완성해야 한다. 제한: 일반차량과 offline fixture만 수행했고 GUI/학습 AV/교통 수요 일반화를 검증하지 않았다. **H1/H2/H3 지지 여부는 아직 판단할 수 없다.**

### 결과·로그 위치

- [원시 집계 summary](research_checks/KC-AUDIT-20261110-01/evidence/summary.json), [실행 source](research_checks/KC-AUDIT-20261110-01/run_audit.py).
- [finite tripinfo](research_checks/KC-AUDIT-20261110-01/evidence/finite.trips.xml), [collision XML](research_checks/KC-AUDIT-20261110-01/evidence/finite.collisions.xml), [statistics XML](research_checks/KC-AUDIT-20261110-01/evidence/finite.statistics.xml).
- [finite stdout](research_checks/KC-AUDIT-20261110-01/evidence/finite_HV_seed43.stdout.log)·[stderr](research_checks/KC-AUDIT-20261110-01/evidence/finite_HV_seed43.stderr.log), [live stdout](research_checks/KC-AUDIT-20261110-01/evidence/live_IDM_seed43.stdout.log)·[stderr](research_checks/KC-AUDIT-20261110-01/evidence/live_IDM_seed43.stderr.log).
- [audit stdout](research_checks/KC-AUDIT-20261110-01/run.stdout.log)·[stderr](research_checks/KC-AUDIT-20261110-01/run.stderr.log). stderr에는 gradient 계산용 tensor를 scalar로 읽는 경고가 1회 있으나 optimizer/update는 수행하지 않았다.
- checkpoint/학습 데이터/영상: **생성하지 않음**. 짧은 고속도로 검사 전이는 dataset으로 저장하지 않았다.

## 3. 과거 기록의 해석과 보존

### KC-HIST-SIGNALS-20261101

저장된 실행 source는 [validate_signals.py](../scripts/kcity/validate_signals.py)이며 [결과 디렉터리](../maps/kcity/reports/signals_validation)에 각 case의 traffic.rou.xml/statistics.xml/trips.xml/collisions.xml/stdout.log/result.json이 있다. `before/after`, 수요 `1/2/3/random_od`, seed `0/1/2`의 24 runs다. BC/PPO 예산은 0이며 모두 SUMO 차량 모델이다.

after는 12회 모두 passed, 총2,124대 도착·충돌기록0·teleport0·급제동 경고126이다. before도 총2,124대가 도착했지만 4회가 collision 조건 때문에 passed=False이고 collision records 합계5다. 도착만으로 안전 성공이라고 판단하지 않는다.

고정177대의 출발 시각을 나눈 2/3배 시험이며 연속 정상상태의 λ 증가와 다르다. 원본 실행 commit·시작/종료 wall 시각·전체 runtime 버전이 각 result에 완전히 기록되지 않아 **확인 불가**로 남긴다. 현재 net/signals/생성 routes 해시는 이번 audit와 연결된다. 날짜 ID는 기존 맵 작업 식별용이며 정확한 실행 시각을 새로 만들어 넣지 않았다.

### KC-HIST-LIVE60 / KC-HIST-LIVE80

[live_demo_validation.json](../maps/kcity/reports/live_demo_validation.json)의 `runs` 3개와 `rejected_cap80_trials`를 별도 실험군으로 취급한다. 60대는 seed0/1/2,각3,600 s의 유한 검증이다. 80대 일부 실패를 숨기지 않으며 collision counter는 고유 사건 수가 아닌 colliding vehicle-step 집계다. 코드 commit/정확한 시작 시각은 파일에 없는 범위에서 확인 불가다. 실제 configuration과 limitation 필드를 원문과 함께 보존한다.

### HW-LEGACY-20260907

[고속도로 결과 폴더](../results/run_20260907_202220)에 model.pt,train.py,road_config.py,mdp_config.py,training/eval CSV,TensorBoard events가 있다. 마지막 eval step194,560,success0,timeout1.0,collision0은 파일 관찰치다. 원 실행 commit·SUMO/runtime·최종 정확한 학습 예산 완주는 이 값만으로 확정하지 않는다. 이번에 모델을 학습/재평가하지 않았다. 기존 정책은 K-CITY baseline으로 사용하지 않고 삭제도 하지 않는다.

2026-11-10T23:25:48.249679+09:00에 별도 CPU 가중치 검사도 수행했다. `torch.load(weights_only=True, map_location='cpu')`로 tensor shape를 확인하고 현재 31-D [256,256] hybrid에 `load_state_dict`를 적용해 성공했다. 이는 위 BC→PPO 호환성 실패와 별개의 확인이며, K-CITY 73-D 후보에 바로 연결할 수 있다는 뜻은 아니다. [가중치 SHA·shape·검사 결과](research_checks/KC-AUDIT-20261110-01/evidence/legacy_checkpoint_inspection.json)를 보존한다. 이 보충 검사는 SUMO/PPO 실행 없이 끝났고, 앞서 기록한 main audit의 시작·종료 시각은 변경하지 않는다.

## 4. 앞으로 실행할 실험의 등록 계약

2026-11-14 상세 계약은 [실행 프로토콜](EXECUTION_PROTOCOL.md)에 있다. 학습/수집/최종평가 실행기는 아직 미구현이며 문서의 예시 argv는 실행할 수 있는 완성 명령이 아니다. KC-01/02 검사 명령만 각 사용 안내에서 실행할 수 있다. 각 단계가 G1~G5를 통과하면 신규 실행 ID로 등록한다. `KC-DESIGN-20261114-01`은 시행 전 명세 검사 ID로서 실험 성능 자료에 합산하지 않는다.

계획된 KC-PILOT/RQ1/RQ2/RQ3의 공통 설계는 [RESEARCH_PLAN.md](RESEARCH_PLAN.md)에 있다. 아래 항목을 **실제 실행 ID별로 먼저 채운 뒤** `실행 중`으로 바꾸고, 종료 후 `완료/실패/중단/무효`와 실제 결과를 남긴다.

| 항목 | 실행 전에 기록할 내용 | 현재 계획 상태 |
|---|---|---|
| 목적·RQ·가설 | 비교 변수,고정 조건,성공/실패 기준 | 계획 문서에 제안됨 |
| 식별·버전 | commit/dirty diff,source/config/map/signals/schema/dataset 해시,런타임 버전 | 실제 구현/실행 전 동결 필요 |
| 재현 조건 | train/eval seeds,case manifest,경로/수요 요청 및 발생 방식,차량 모델·신호·제어 모드 | 후보만 있음 |
| 모델·초기화 | policy 구조·분포·mask·정규화,BC source checkpoint,optimizer 신규/재개 여부 | 미구현 |
| 학습·비용 | BC sample/update budget,PPO actual/requested transitions·updates,평가 전이,전문가/학습/평가 wall·CPU/GPU | 측정 전 |
| 실행 | 명령,시작/종료 ISO8601,현재 상태,중복 방지 owner/run ID,정상 중단·재개 방법 | 미실행 |
| 평가 | 예정/유효/무효/실패 Episode 수,지표 분자·분모·단위,seed별 변동·paired differences | 측정 전 |
| 실패·원시 산출물 | event taxonomy,representative trace/video,logs/checkpoints/data/aggregate의 상대 경로 | 미생성 |
| 해석 | 관찰/가정/해석 분리,가설 지지·불리·불명확·예산 내 미달성 | 판단 전 |

KC-RQ1은 같은 예산의 학습곡선과 목표 도달 전이·총비용을, KC-RQ2는 **고정된** 정책의 세 수요 평가를 기록한다. KC-RQ3는 같은 전문가 풀과 수량·업데이트를 확인한 뒤 별도 실행한다. 정책/안전 설정/버그 수정으로 비교 가능성이 깨지면 기존 실행은 이력으로 보존하고 참고용 또는 무효 사유를 명시한다. final case를 보고 조건을 바꾸면 새 설계/실행 ID를 사용한다.
