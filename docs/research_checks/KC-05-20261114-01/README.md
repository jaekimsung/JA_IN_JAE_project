# KC-05 — 관측 정렬 전문가·실제 소량 수집·복구

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../research/RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../research/RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
**후보 구현과 소량 검증을 완료했다. 다음은 KC-06의50k 시험 학습이다.** 전문가 B0의 실제 주행602전이를 저장했다. 이 자료는debug 파이프라인 점검용이고,본학습 pool·목표10M·final 평가에 합산하지 않는다. 이번 데이터 검증에서 learner/optimizer는 실행하지 않았다.

## 식별과 산출물

- 사전 기록: local branch `codex/kcity-kc01-20261114`,HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`. 기존 미완료 변경을 보존했다.
- 신규 [B0](../../../policy/rule_expert.py),[data writer/validator/loader](../../../data/dataset.py),[collector/cursor](../../../data/collector.py),[수집 CLI](https://github.com/jaekimsung/JA_IN_JAE_project/blob/fac8482/tools/checks/collect_expert.py),[검사 CLI](https://github.com/jaekimsung/JA_IN_JAE_project/blob/fac8482/tools/checks/validate_data.py),[회귀 검사](../../../tests/test_kcity_data.py).
- 사용·컬럼·복구 계약은 [KCITY_DATA_PIPELINE.md](../../specs/KCITY_DATA_PIPELINE.md),설계와의 대응은 [데이터 명세](../../specs/DATA_COLLECTION_SPEC.md)를 따른다. 기존 env/PPO/BC/map/model/data와 KC-01 pin은 이번 단계에서 수정하지 않았다.
- 최종 source/원본 파일/문서 검사는 [FINAL_CHECKS.json](FINAL_CHECKS.json). Git commit/push·Drive/GitHub 업로드는 하지 않았다.

## 실제 전문가 정보 범위

`KC-B0-OBS73-v1-candidate`는73-D 관측만 받는 결정적·메모리 없는 규칙 정책이다. 전체 State·detected list·TraCI·case ID·미래 신호를 받지 않는다. 현재 속도/제한,현재 Lane 선행 gap/상대속도,경로 연결,인접 Lane 전후 gap,기하학적 mask,현재 red/yellow 접근을 사용한다.

순항7.5m/s·headway1.5s·최소gap3m·차선 전후gap8m·정지 여유2m는 후보 설정이다. SUMO mode31/512와 혼합HV 물리는 유지했다. 교차 접근 차량 gap·정지 유지시간·양보 규칙 전체를 판정하는 전문가가 아니며,정책 단독 안전성을 주장하지 않는다.

먼저 contract_check A/B/C×배경 유무의6회가 모두 도착했다(probe·로그). 본격 수집에는 이 probe 대신 아래 독립expert_train/expert_val case를 사용했다.

## 실제 수집 결과

실행 `2026-11-14T23:19:38.172679+09:00`~`23:19:57.224286+09:00`. Python3.10·NumPy·SUMO1.28.0의 실제 버전은 dataset RUN.json에 고정했다. 수집 wall19.05초는 회귀 검사와 동시 실행한 값이며 단독 처리량·학습 속도 추정에 사용하지 않는다.

| split/namespace | 과제 | 전이 | 실제 Episode 시간(s) | 초기HV | 시간가중HV 평균 | 실제LC | 종료 |
|---|---|---:|---:|---:|---:|---:|---|
| expert_train | A |56|27.7|14|16.47|0|도착|
| expert_train | B |52|25.7|10|12.41|1|도착|
| expert_train | C |195|97.3|8|11.20|1|도착|
| expert_val | A |52|25.9|8|12.39|0|도착|
| expert_val | B |52|25.6|10|12.08|1|도착|
| expert_val | C |195|97.3|9|12.90|1|도착|

- **602전이=303 train+299 validation**,6개의 고유 Episode,64행 후보 shard의 **10개 확정 shard**다. 작은 확인을 위해 과제별3:3 case를 배정했으며 본 pool80:20 분할의 결과가 아니다.
- 이6회에서 AV 충돌·적색 진입·teleport·제거·deadline·unknown TLS0,정상TLS 통과10,실제LC4를 기록했다. `성공6/6`은 제한된 전문가 검증 결과다.
- 행동 전 관측의 red 노출145결정,선행차 존재78결정,정지26결정,차선 요청4회·거부0회,detected 차량 기록293개다. 차선 label은 좌4/유지598/우0이다. 이는 과제 관련 상황이 자료에 들어갔다는 근거이며 충분한 분포/안전성 보장은 아니다. BC pilot에서는 유지 편중과 필수LC 수행을 별도로 확인해야 한다.
- C train·A val·C val의초기HV8/8/9는 후보 기준10대 미달이다. 수요600vph와 실제 상호작용 충분성은 KC-06에서 더 확인해야 한다.

원시 수집 로그는 COLLECTION.final.log,검사·지표 원문은 [SUMMARY](validation_v1/SUMMARY.json)와 VALIDATION.final.log에 있다. `learner_executed=false`,optimizer0이며 본 비교 학습은 시작하지 않았다.

## 파일과 BC 호환성

자료 위치:

`/home/heven/kcity_research_runs/KC-05-20261114-01/validation_v1/`

각 shard는 전체 State/next가 있는JSONL.gz,같은 UID의NPZ,events sidecar,수집 cursor/진행 중 환경 이력,파일별SHA를 묶는다. 원본 코드·generated SUMO 입력도source/asset snapshot으로 보관했다. source/run ID·시드·split·좌표 기준을 RUN.json에서 해결한다. JSONL과NPZ를 두 배로 세지 않는다.

측정한 전체 run 파일은 **2,797,148 bytes**(운영 파일/파생 index 포함),그중 JSONL.gz859,407·NPZ150,714·events3,593 bytes다. 작은64행 shard의 압축/메모리 특성을10M 수집량에 그대로 외삽하지 않는다.

BC loader는 정상 완주·충돌/정의된 적색 위반/신호unknown이 없는 Episode만 고르고,원시 실패/미완결 자료는 삭제하지 않는다. 종료 summary를 raw trace에서 다시 계산하므로 summary만 성공으로 고쳐 fitting 자료를 늘릴 수 없다.

실제303/299개를 [256,256] 공통 BC actor에 **forward만** 통과시켜 tensor/label/mask 호환을 확인했다. weight 불변·optimizer state 비어 있음·gradient updates0이다. SUMMARY의untrained_forward_loss는 무학습 모델의 입력 점검 수치이며 학습 성능이 아니다. default loader는debug자료의 연구 BC 초기화를 거부한다.

## 회귀·손상·복구 검사

- **100개 검사 통과**,44.452초(로그). 기존80+KC-05 신규20개다. 초기 신규18개 검사도 통과했고 이전 로그 보관 위치를 보존했다.
- 필수 State/finite·raw/clip·시간/next/absorbing·mask·detected 정렬·UID/동일 Episode·교통 시드 그룹 분할·NPZ dtype/offsets·파일SHA를 검사했다.
- 같은 shard 안과 shard 사이의 연속성을 확인했다. 중복,train/val 누출,잘못된next,State 누락/NaN,NPZ offset 손상,조작한 성공 summary·unknown 신호의BC fitting을 거부했다.
- 단일 writer lock·죽은 PID lock·미확정partial 격리·directory commit 후 RELEASE 갱신 실패 복구를 검사했다. 검증 중 주입한 고장은 실제 전문가 성능 실패로 세지 않는다.
- 현재 **dataset/run/contract 내부**의 품질 검사다. 여러run 병합의전역 Episode registry·버전 간 시드 교차 검사와원격 backup readback은 후속이다. local coverage만 검증했다.

100개 회귀 검사에는 기존 KC-04의 작은 optimizer fixture 재실행도 포함된다. 이와 **이번602전이 수집/BC forward의optimizer0**을 구분한다. 연구용 학습 전이·optimizer 진도에는 합산하지 않는다.

### 중단 후 실제 수집 재개

RESUME_CHECK.json·RESUME.final.log: 별도run을20전이에서 저장·종료한 뒤 같은run으로50전이까지 이어갔다. 최종50개의 고유 UID와2개 attempt를 확인했다. 관측·행동·reward·현재/다음 State·사건·substep 기록이 중단 없는 기준 실행의 첫50전이와 정확히 일치했다. replay20결정을 새로운 수집량으로 세지 않았다.

별도 복구 자료는 `/home/heven/kcity_research_runs/KC-05-20261114-01/resume_v2/`다. 앞선7→14 probe도 수집·재개 로그와별도폴더로 보존했다. 중복된 검증 궤적을 본 pool 수량에 합산하지 않는다.

## 다음: 실제 시험 학습

다음 KC-06에서는 pilot 실행 계약/학습 CLI·주기 dev 평가/저장/STOP을 연결하고 **PPO-only/BC→PPO 각50,000전이** 시험 학습을 진행한다. 실제90개 feasibility case·writer10k와RAM/I/O·GPU·장기 checkpoint/백업·보상/분포를 확인한 후 본 연구 설정을 동결한다. 현재 pool1M/BC10k/PPO각1M/final평가는 아직 실행하지 않았다.

재검사/수집 명령은 [사용 안내](../../specs/KCITY_DATA_PIPELINE.md)에 있다. 수집기는debug 최대10,000전이만 지원하며 본학습 승인 flag를 바꾸지 않는다.
