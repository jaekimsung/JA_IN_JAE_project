# K-CITY 데이터 수집·저장·복구 사용 계약

[실제 결과](research_checks/KC-05-20261114-01/README.md) · [전체 데이터 명세](DATA_COLLECTION_SPEC.md) · [현재 상태](RESEARCH_STATUS.md).

갱신: 2026-11-16. B0·writer/validator·BC loader는 구현했고 3seed pilot과 본 collect/views/bc/ppo 운영 검증까지 완료했다. **본 데이터/학습 카운터는0**이다. 최초 KC-05의602debug전이는 본 pool/10M에서 제외한다. 다음 실제 작업은 [본 전문가pool](KCITY_MAIN_EXECUTION.md)이며 아래 소량 debug CLI와 구분한다.

## 1. 전문가 B0의 정보와 제어

[KCityRuleExpert](../experts/kcity_rule_expert.py)는 `predict(observation)`만 받는 결정적·메모리 없는 규칙 정책이다. 환경 handle,전체 State,detected 목록,미래 신호,현재 case ID를 받지 않는다. 설정 외에 과거 상태나 난수도 저장하지 않는다.

| OBS73 정보 | 실제 사용 |
|---|---|
| ego 속도·제한속도 | 순항7.5m/s,가감속+2/-4.5m/s² 범위 |
| 현재 corridor 앞 차량 gap/상대속도 | 시간간격1.5초·최소gap3m의 추종 규칙 |
| 현재/인접 Lane의 경로 연결성 | 현재 Lane으로 다음 경로를 못 갈 때 연결 가능한 인접 Lane 요청 |
| 인접 Lane의 전후 gap/상대속도 | 최소8m·시간gap1.5초 조건 확인 후 차선 요청 |
| 차선 존재·internal·cooldown | 공통 actor와 같은 기하학적 mask,유지는 항상 가능 |
| 현재 TLS의 red/yellow·거리 | 정지 여유2m와 후보 제동거리로 접근 속도를 제한 |

수치는 pilot 이후 본 설정에서 유지한 규칙 값이며 최적값/실측 교통 파라미터가 아니다. 실제 움직임에는 SUMO의31/512 안전 설정과 거동 모델도 참여한다. 전문가의 신호 제동을 정책 단독 안전 성능으로 해석하지 않는다.

A/B/C의 지정 경로에는 allway_stop이 없다. 구현에는 관측의 stop rule에 대한 메모리 없는 저속 접근 후보가 있지만,정지 유지시간·양보 규칙 전체를 인증하지 않았다. crossing 차량 슬롯이 없는73-D의 한계도 유지한다. 비신호 교차 차량의 gap을 전문가가 추가 특권 정보로 판단하지 않는다.

## 2. 실제 기록 구조

[Collector](../utils/kcity_collector.py)는 각0.5초 결정에 대해 다음을 저장한다. 사건/기한으로 일찍 끝난 전이는 실제1~5개의0.1초 tick을 기록한다.

- 수업 필수 `episode,t,observation,action_raw,action,reward,terminated,truncated,state,detected_vehicles,event,next_observation,next_state`와 중첩 행동/사건 필드.
- 모든 행의 실제 before/after 절대 State·전체 차량·신호,현재/다음 detected 목록. 사라진 ego는null·absorbing 관측·validity flag로 표시한다.
- 정책 원본/clip 후 입력/요청/실제 이동을 분리한다. `reward_env_raw`는 환경 원값,`reward`는 같은 값의float32 view다. GAE bootstrap 보상으로 바꾸지 않는다.
- run/case/episode/attempt/transition UID,교통 시드 그룹,source stage/split,teacher source/config hash,sim tick과실제dt,종료·segment 경계.
- 0.1초 사건과 substep 측정,원시 reward components. 부당 대기 판정은 여전히 미구현이다.

State의 interval별 HV departure/arrival와 최대60초 관측 window도 기록한다. window는 **reset 이후 수집한 결정 interval endpoint 집계**이며 warmup 전체나 임의의 정확한60초 실측으로 꾸미지 않는다. actor는 이 State를 받지 않는다.

파일 구조:

```text
<dataset>/
  RUN.json                  # 고정 case/seed/split/teacher/환경·코드 계약
  RELEASE.json              # 확정 shard 목록·고유 전이수·data ID
  sources/, assets/         # 실행 코드와 derived SUMO 입력의 SHA 검증 복사본
  COLLECTION_STATUS.json    # 실행/중단/실패/완료 운영 상태
  COLLECTION_SUMMARY.json   # 실제 수집 결과
  shards/shard-000000/
    transitions.jsonl.gz    # codec-aware reader로 전체 State/next 복원
    numeric.npz             # 같은 UID의 수치 view,object/pickle 없음
    events.jsonl.gz         # 전이에 join하는 사건 sidecar
    collector.json          # 정확한 수집 cursor·부분 Episode metrics
    environment/            # expert: 재개 상태, PPO: 외부 bundle 참조
    SHARD.json              # 파일 SHA·행 수·완료 Episode 집계
  checkpoints/              # 본 PPO의 외부 native bundle·보관 registry
  partial/                  # 아직 확정하지 않은 journal·파생 SQLite index
  quarantine/               # 복구 시 격리한 partial/오래된 lock
```

NPZ는 기본11개 key를 모두 보존하고 raw alias·bounded 입력·mask·UID·시간·validity·split을 추가한다. detected 좌표는float64와offsets로 표현한다. 절대 State는JSONL 기준 파일에 있으며 NPZ object dict로 넣지 않는다. 두 view를 두 배의 데이터로 세지 않는다.

현재 Episode 번호는 **해당 dataset 내 단조 증가 registry**다. 여러 run을 최종 release로 병합할 때는 전역 Episode ID 배정과 run/버전/시드 교차 검사가 추가로 필요하다.

## 3. Split과 BC loader

case의 namespace·시드 그룹·split을 **수집 전에** 정한다. 한 Episode 또는 같은 교통 시드 그룹이 두 split에 들어가면 거부한다. 이번 검증에서는 A/B/C 각1개를expert_train namespace와expert_val namespace에서 수집했다. 작은 파이프라인 점검을 위한3:3 구성이고,본 pool의80:20 설계를 대신하지 않는다.

[iter_bc_batches](../utils/kcity_data.py)는 완주·충돌 없음·정의된 적색 위반 없음·신호 unknown 없음이 확인된 **전체 B0 Episode**만 fitting view에 넣는다. 실패·불명·미완결 Episode의 원시 전이는 삭제하지 않는다. 종료 summary는 raw 사건/측정에서 다시 계산해 대조하므로,summary만 성공으로 바꿔 loader를 통과시킬 수 없다.

BC label은 `action.env_input`의 bounded 가감속과 Lane 명령이다. PPO logprob용 원본 action_raw는 그대로 보존한다. 기본 loader는 debug/pilot 자료로 연구 BC를 초기화하는 것을 거부한다. 이번 호환성 검사만 `allow_debug=True`를 명시했다.

```python
from utils.kcity_data import iter_bc_batches

for batch in iter_bc_batches(dataset_path, "expert_train", allow_debug=True):
    obs = batch["observation"]     # float32[N,73]
    target = batch["action_target"]  # float32[N,2]
    mask = batch["action_mask"]   # bool[N,3]
    # 이 예시는 검증용 자료 읽기다. 본 연구 학습 시작 명령이 아니다.
```

## 4. 확정·복구·품질 검사

한 writer만 lock을 소유한다. 전이는partial journal에 쓰고,shard 파일·수집 cursor·환경 이력을 만든 뒤 파일 fsync·manifest 확정·디렉터리 rename으로 commit한다. SQLite의unique 제약으로 UID와(episode,t) 중복을 막는다.

재개는 확정 shard를 다시 읽어 index와전역 count를 복원한다. 미확정partial은 격리하고 수량에 넣지 않는다. 디렉터리 commit 직후 RELEASE 갱신이 실패해도 다음 명시적resume이 확정 디렉터리로부터 index를 재구성한다. 살아 있는 writer의lock을 강제로 뺏지 않으며,죽은 PID의lock은resume에서 격리한다.

수집 cursor에는Episode/t·이전 interval/window·부분 지표를 저장한다. 환경은 KC-04의동일 case/seed+현재 Episode 행동 replay로 복원한다. replay는 새 수집 전이로 집계하지 않는다. code/teacher/config/shard 크기가 바뀌면 같은 run으로 이어 쓰지 않는다.

검사는 필수 State/finite·관측 범위/onehot/mask·tick/dt·raw→clip/명령·reward 합·Ego alias·detected와State 정렬·next/다음행연속·종료/absorbing·UID/split·NPZ dtype/값/offsets·사건 sidecar·archived code/map SHA를 대조한다. 배포/원격 백업 검증은 하지 않았으며 DQ-09의local coverage만 확인했다.

현재 writer/validator는 **한 shard를 메모리에 올리는 방식**이다. KC-05는64행, 본 expert 운영검사는512행, 본 PPO는rollout2048과평가경계 commit을 사용한다. 원래 일반 writer 기본값25,000행과10M 전체 운영의 peak RAM/I/O/재개를 전수 검증했다고 주장하지 않는다. 실패한 투입·통신 오류를 정상 완주로 바꾸지 않으며,미완결 수집은상태 파일과partial을 남긴다.

## 5. 지금 실행 가능한 명령

저장소 루트에서,새 output과안정적인run UID를 지정한다. 기존 격리 Python을 사용한다.

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python

# 구조·case/seed·teacher 점검만: SUMO 주행이나 데이터 쓰기 없음
PYTHONDONTWRITEBYTECODE=1 "$KCPY" -B scripts/kcity/collect_expert.py \
  --output /tmp/kcity-kc05-new-data --run-uid kc05-my-check --check-only

# A/B/C × 독립 train/val seed,총6개 Episode의 bounded debug 수집
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/collect_expert.py \
  --output /tmp/kcity-kc05-new-data --run-uid kc05-my-check --max-transitions 4000 --shard-rows 64

# 파일·학습 tensor 호환성만 검사. optimizer update 없음
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/validate_data.py \
  --dataset /tmp/kcity-kc05-new-data --output /tmp/kcity-kc05-new-report --check-bc-forward
```

중간 budget에서 멈춘 run은같은output/run UID/환경/shard 크기로 `--resume --max-transitions <더 큰 절대 목표>`를 준다. 한 번에10,000전이 이하의검증용 수집만 지원한다. 이미 확정된 전이는 다시 기록하지 않는다.

## 6. 현재 물리 형식과 PPO 기록

논리 계약은 KC-DATA-v1·KC-OBS73-v1이다. 물리 JSONL은 `KC-NEXT-REF-v1`로 다음 행과 같은 next_state/next_observation만 `next_reference` UID로 대체한다. Episode terminal과 shard 마지막 행은 명시 next다. `read_shard()`는 한 행 lookahead로 원래 전체 값을 복원한다. NPZ next와 수치 정밀도는 유지하고 과거 full-next도 읽는다. raw gzip 행을 그대로 논리 transition으로 사용하는 reader는 이 codec을 처리해야 한다.

본 PPO는 명시적인 online_policy provenance를 검사한다. B2/B3·seed·실제 행동정책 state_dict SHA·rollout/update/logprob/value를 검증하고 B0 자료로 위장하지 않는다. 본 data_split은 `ppo_train`, source_stage는 `ppo_train`이다. expert는 `expert_train/expert_val`, probe는 `ops_probe`로 분리한다.

PPO는 `transitions/checkpoints/`에 native learner bundle을 먼저 저장·fsync·SHA검증한 뒤 데이터 shard의 `environment/REFERENCE.json`에 경로·SHA·T를 기록한다. `checkpoint_from_shard()`로 실제 bundle을 해석한다. 데이터가 확정됐으면 최신 복원 모델도 이미 확정된 순서다. crash 잔여물은 명시적 재개에서 해당 run 내부만 정리한다.

최신·직전·50k 평가·초기 모델을 보관한다. 유지모델 검증 후 불필요한 새run bundle만 지우며 데이터 shard/SHA/UID는 immutable이다. 오래된 shard의 참조 bundle은 보관 대상이 아닐 수 있으므로 임의 과거 shard마다 재개 가능하다는 뜻은 아니다. CHECKPOINTS.json/CHECKPOINT_RETENTION.jsonl에 보관·정리 계보를 남긴다. BC도 최신·직전·필요best만 유지하며 loss/val 곡선은 보존한다.

[저장 최적화 실측](research_checks/KC-STORAGE-20261115-01/README.md): expert2,137/PPO2,119전이에서 논리 값 동등, JSONL gzip 각각9.47%/15.50% 감소. 이는 소표본 측정이며 전체10M 압축률 보장은 아니다.

## 7. 보관·제출의 남은 범위

사용자 요청으로 과거 rawdebug/probe·console로그·source복사본·로컬압축본을 삭제했다. 필요한 코드·설정·곡선·평가·모델11개·작은 검증 결과는 남겼다. 삭제된 과거 dataset을 현재 읽기/재개 입력으로 안내하지 않는다. **Drive 업로드 금지, 새 백업 없음.**

최종 release의 run간 전역Episode ID 매핑·다중run seed교차검사·≥10M UID union·공개 manifest/DatasetCard·Hub 전수 다운로드 복원은 후속이다. 로컬 validator 통과를 원격 제출 완료로 표시하지 않는다. [실행 프로토콜](EXECUTION_PROTOCOL.md)
