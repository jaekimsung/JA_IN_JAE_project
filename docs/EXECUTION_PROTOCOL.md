# K-CITY 수집·학습·실험 시행 전 프로토콜

ID `KC-PROTOCOL-v1-draft-20261114` · **설계 준비 완료를 목표로 한 runbook; 현재 실행 가능 승인은 아님**.

[데이터 계약](DATA_COLLECTION_SPEC.md) · [결과·컨설팅](RESULTS_AND_CONSULTING.md) · [연구 계획](RESEARCH_PLAN.md) · [실험 인덱스](EXPERIMENTS.md)

실행 현황 갱신(2026-11-14): KC-01/02 후보 구현·작은 검사를 완료했다. [설정](../configs/kcity/v1/README.md)·[Gym 안내](KCITY_ENV.md)·[KC-02 결과](research_checks/KC-02-20261114-01/README.md)를 따른다. G1의 작은 환경 검사는 통과했지만 통합 preflight는 아직 없으며, 최종 신호/규칙 지표·보상·수요 충분성은 KC-03/06에서 추가 검증한다. KC-03의 GAE/예산/독립평가·사건 지표 후보 검사도 완료했다. [실제 계약](KCITY_EVALUATION.md)을 따른다. KC-04의 공통 actor·BC 이식·전체 resume 후보 검사도 완료했다([계약](KCITY_POLICY_AND_RESUME.md)). KC-05의 B0·수집/검사 CLI·shard/loader·복구도작은실제자료로확인했다([계약](KCITY_DATA_PIPELINE.md)). 연구학습/최종평가 CLI와G2~G5 전체는미완료다.

## 1. 현재 준비 수준과 이번 작업의 끝

현재 저장소 HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`, SUMO1.28.0을 읽기 전용으로 확인했다. 상세 [READ_ONLY_CHECK.json](research_checks/KC-DESIGN-20261114-01/READ_ONLY_CHECK.json)에 코드/수업자료/맵 해시·공간·실행기 존재 여부가 있다. 새 시뮬레이션·수집·BC/PPO 업데이트는 **0**이다.

설계 점검 시에는 전용 환경도 없었다. 현재 KC-01/02로 `env/kcity_config.py`, `env/kcity_env.py`와 작은 검사기는 추가했다. KC-05에서 `experts/kcity_rule_expert.py`와 작은 `collect_expert.py/validate_data.py`도 추가했다. 남은 것은 연구용 통합 K-CITY preflight/train/evaluate/summarize와 대량 pool 운영 실행기다. 기존 `train.py`, `test.py`, `collect_pomdp_data.py`는 고속도로용이다. 이 문서는 **무엇을 어떤 순서·설정·산출물로 시행할지**를 정하며, 빠진 구현을 문서만으로 실행 가능하다고 표시하지 않는다. 후속 구현과 gate 검증이 끝나야 ‘명령 한 번으로 시행 직전’ 상태가 된다.

이번에 고정하는 것은 필수 컬럼 보존, 데이터/학습 예산 구분, 분리·버전·지표·결과 기록 계약이다. 관측73-D/λ/보상/학습 hyperparameter는 다음 표의 pilot 후보이며 최적값이나 확정 성능이 아니다.

## 2. 운영 역할과 경로

팀원 이름은 임의로 채우지 않는다. 컨설팅 전에 실제 담당자·검토자 이름을 배정한다. 한 사람이 여러 역할을 맡을 수 있지만 산출물 검토자를 따로 둔다.

| 역할 | 중심 책임 | 인계할 산출물 |
|---|---|---|
| 환경 담당 | A/B/C route·seed·신호·SUMO 제어·종료 | protocol/scenario·환경 fixtures·preflight 결과 |
| 데이터 담당 | B0·record schema·shard·QC·10M 집계 | teacher hash·dataset manifests·품질 보고·복원 증거 |
| 학습 담당 | 공통 actor BC→PPO·예산·재개 | frozen configs·checkpoints·curves·비용 장부 |
| 평가·발표 담당 | 독립 case 평가·실패 trace·표/그림·영상·Hub/페이지/제출 | final manifest·결과보고·링크·제출 SHA |

논리 디렉터리 계약(아직 만들지 않은 실행 구조):

```text
repo/
  configs/kcity/v1/ protocol.json, scenarios.json, cases_*.jsonl, schema.json
  env/kcity_env.py, experts/kcity_rule_expert.py
  scripts/kcity/ preflight.py collect.py train_bc.py train_ppo.py evaluate.py
                  validate_dataset.py summarize.py record_video.py package_release.py
  tests/kcity/ ...
/home/heven/kcity_research_runs/<protocol_id>/
  preflight/<id>/..., pilot/<id>/..., expert_pool/<id>/...
  bc/seed11|22|33/...
  ppo/B2|B3/seed11|22|33/...
  evaluations/dev|final/..., archive/..., release/...
```

실제 구현 때 이 경로의 script/CLI를 맞추거나 문서를 함께 갱신한다. 현재 존재하지 않는 결과 경로를 완료 링크로 제공하지 않는다. root 내 output 덮어쓰기 금지, 단일 run owner lock, 정상 중단/재개는 manifest의 run_uid 유지가 기본이다.

## 3. 고정 후보표

| 항목 | v1 추천 | 동결 조건 |
|---|---|---|
| 과제 A/B/C | 기존 검사 후보와 A/B/C=30/30/40% | route 연결·실제 출발/도착·필수 차선/신호 판정 통과 |
| 경로 | A `-68 -13 -71`; B `-3#4 -3#5 -3#6 -3#7 -3#8 -68`; C 현재 qualifier17 edges | [기존 route 후보](research_checks/KC-AUDIT-20261110-01/evidence/scenario_candidates.json)의 ID·hash 사용 |
| 출발/도착 | 출발 pos5m,speed2m/s; B lane0→필수lane1; 도착 마지막 Lane 끝5m 전 | 끝 Edge가 짧으면 임의 clip하지 않고 geometry validator로 새 위치 선정·기록 |
| 시간 | tick0.1s,decision0.5s,5 substep,warmup60s,Episode300s | 조기 terminal/정지대기·진행·tick fixtures |
| 관측·행동 | 73-D draft,Gaussian 가감속+3범주 Lane,mask | [컬럼/인덱스 계약](DATA_COLLECTION_SPEC.md)·same-mask logprob 검사 |
| 제어 | speedMode31,laneChangeMode512,+2.0/-4.5m/s²,limit≤8.33m/s | B0/충돌/신호 trace 검사. 모든 학습법 동일 |
| 교통 | requested λ0=600vph,900/1200은 증가 평가 후보; 4종 차량 비율25%씩 | 지속 λ feasibility·충분한 HV·request/realized량 검사 |
| OD·신호 | 기존coverage route pool의 동결 OD 가중치·동일vTypes·actuated program | request generator ID/hash·signal policy hash. 평가 때 수요 외 변수 고정 |
| 보상 | 기존 계획의 progress/arrival/collision/red/invalid/lane/wait 항 | 제동·계속 정지·경로반복·불필요 LC 악용 검사 후 계수 고정 |
| 정책 | shared trunk[256,256] ReLU,mu/lane/value heads,log_std=-0.5 | BC/PPO 동일 객체/전처리. 실제 parameter수 저장 |
| PPO | lr1e-4,n_steps2048,epochs10,minibatch64,γ.99,GAEλ.95,clip.2,value.5,lane_entropy.01,gradnorm.5 | pilot 뒤 양 방법 같은 설정으로 잠금 |
| BC | 200k train·50k val,10k updates,batch256,lr3e-4,val매500 | 선택 자료·완주 품질·독립 Episode/seed 확보, 같은 budget |
| 학습 seed | 11,22,33 | B1/B2/B3 paired; 환경 seeds는 별도 |
| 목표 | dev 안전·규칙 준수 완주≥.80 두 연속 checkpoint | B0 기준으로 달성 가능·의미 확인 후 사전 동결 |

보상 항은 interval당 합으로 정의한다. progress는 실제 Δ거리, 도착/충돌/적색 penalty는 사건당1회, 시간 기반 대기는 실제 `control_dt_s/0.5` 비례, LC는 명령 재발행이 아니라 실제 수행당을 우선 추천한다. 무효 요청 penalty의 적용 사유도 기록한다. 조기 terminal이라고 전체5 substep 대기 페널티를 더하지 않는다.

λ0가 수행 불가능하면 pilot에서 **예정 순서600→450→300vph**로 내려가며 동일 기준을 적용한다. 통과한 첫 값을 기준 후보로 고정하고 1.5/2배를 다시 검사한다. seed를 골라 통과시키지 않는다. 모두 불가능하면 정책 성능 비교 전에 route·제어·traffic 운영을 해결한다. 최고 수요만 실패하면 고부하 실패 조건으로 남길지 낮은 배수로 설계를 바꿀지 컨설팅/동결 기록에서 결정하며 결과 확인 후 final을 몰래 바꾸지 않는다.

### 일반차량과 interaction을 실제로 보장하는 방법

평가 자료의 ‘일정 수 이상’에는 수치가 없다. 다음은 **팀 내부 pilot 품질 기준 후보**다: reset 시 active HV≥10, Episode 시간가중 평균HV≥10, case 패널에서 A 적색 접근·정지 사례≥30%, B 필수 LC 구간에 인접차/선후행차 존재 사례≥50%, C 감지차가 존재하는 시간비율 중앙값≥30%. 개별 임계값은 수업 공식 기준이라고 쓰지 않는다.

단순 수요만 높여 상호작용 있다고 하지 않는다. A의 적색 노출·B의 원래 Lane으로 목적지 연결 불가·선행gap/인접차·대기·LC 성공을 별도 집계한다. λ0에서 이 조건을 만족하지 못하면 **정책과 무관한 case 생성 단계**에서 OD/배경 배치/warmup을 조정한다. 고정 final cases를 정책 성능을 본 뒤 재샘플링하지 않는다. 주실험 후 낮은 HV가 관찰되면 case를 삭제하지 않고 전체 성능+traffic exposure와 범위 제한을 함께 보고한다.

## 4. 시행 전 gate와 첫 구현 순서

체크박스는 실제 증거가 있기 전 `[ ]`로 유지한다. 문서 작성 완료를 코드/학습 준비 완료와 섞지 않는다.

| gate | 필요한 작업·검사 | 통과 증거 | 현재 |
|---|---|---|---|
| G0 설계/역할 | 데이터/지표/일정/담당·컨설팅 질문 명세 | 이 세 문서,실제 담당 배정 | 문서 완료·담당 미배정 |
| G1 환경 | KC-01/02:route/spawn/goal,독립TraCI,seed 재현,73-D·5substep,충돌/위반/제거 | preflight.json+source hashes+각case traces | **부분 통과: KC-01/02 작은 검사 완료**; 통합 preflight·최종 지표/수요는 후속 |
| G2 PPO·초기화 | KC-03/04:GAE 경계·terminal next,mask/raw logprob,BC→PPO 행동일치,예산 cap | tests결과+정상 resume fingerprints | **부분 통과: KC-03/04 작은 후보 검사 완료**; 통합 실행기·GPU/장기·최종 preflight 미완료 |
| G3 teacher·writer | KC-05:관측만 사용하는 B0,필수 State·columns·NPZ,shard·crash 복구 | B0 짧은 A/B/C traces,DQ-01..09 | **작은 후보검사 완료:602행·100tests·복구/loader**;원격DQ09·최종release병합미완료 |
| G4 pilot·비용 | B0 feasibility,10k writer pilot,50k PPO pilot,1/2worker 측정 | pilot.csv·throughput·실측bytes/T·peakRAM·GPU·buffer | **미실행** |
| G5 과학 설정 동결 | λ0·schema·reward·seed manifest·목표·예산 최종화 | FROZEN_PROTOCOL.json+각 hash+상태READY | G1~4 필요 |
| G6 본 수집·학습 착수 | 공간/백업/중복 job/버전 확인,experiment 사전 등록 | LAUNCH_READY.json+owner lock+실제RUNNING counters | **착수 금지: 이번 범위 밖** |

첫 구현은 **KC-01**이다. `configs/kcity/v1/scenarios.json`과 `env/kcity_config.py`, route validator를 만들고 A/B/C, B lane0→1 필수 연결, 실제 arrivalPos 범위, map/TLS hashes, seed tree·request manifest를 자동 검사한다. output에서 최소 A/B/C 유한 Episode를 검증할 때까지 본 수집·학습은 시작하지 않는다. 기존 `build.py`로 맵을 덮어써서 route 오류를 우회하지 않는다.

KC-02~05 구현 변경 대상과 후속 CLI 계약:

| 대상 | 새로 구현/수정할 함수 | gate에 필요한 검증 |
|---|---|---|
| `env/kcity_env.py`(신규) | reset,step,get_policy_observation,get_privileged_state,collect_substep_events,close | 연결 격리·절대 State·끝관측·진행·5tick·사건 |
| `experts/kcity_rule_expert.py`(신규) | predict(obs,mask),teacher_version | actor와 같은 정보만 사용·참조 데이터 없음 |
| `utils/buffer.py`, `algorithms/ppo.py` | add/compute_gae/collect_rollout/learn/save/load | bootstrap와trace mask 분리,eval 환경 분리,cap·full resume |
| `utils/networks.py`, 새 K-CITY BC 실행기 | 공통 hybrid actor·CE+MSE·mask·actor 초기화 | BC/B3 deterministic outputs 동일; B2/B3 critic head 초기화·std·새optimizer 맞춤 |
| K-CITY 수집기/validator(신규) | snapshot_transition,write_shard,validate_shard,resume_writer | DQ·partial·ID·동시writer·소실 처리 |
| 평가/집계/영상/패키징 실행기(신규) | evaluate_cases,summarize,record_video,package_release | 분모·failed attempt·weights 불변·영상-실험연결 |

## 5. Case·seed·split을 먼저 동결

기존 seed namespace(전문가10000대,학습20000대,dev30000대,final40000대)는 **master namespace label**로만 쓴다. 각 Episode의 SUMO/traffic/goal/init RNG는 `SeedSequence([master_namespace, scenario_code, case_index, seed_component])` 같은 명시적인 정수 입력으로 생성한다. Python built-in hash나 실행 순서·worker ID에 따라 바뀌는 전역 RNG를 사용하지 않는다.

- `cases_expert`: baseline λ0만 생성. traffic seed group 전체를 train80%/val20%로 먼저 배정한다.
- `cases_train`: B2/B3의 paired seed별 같은 명세 목록, A/B/C 3/3/4 묶음 순서를 동일하게 한다. Episode 길이가 달라 소비 case 수는 달라질 수 있으므로 같은 transition에서 실현 교통이 완전히 같다고 주장하지 않는다.
- `cases_dev`: λ0의100개 독립case(A30/B30/C40). 학습·BC 선택에 사용 가능한 개발 panel이다.
- `cases_final`: 각 수요100개(A30/B30/C40), 모든 방법·seed에 같은case를 적용. 수요 배수 간 OD/개체 기본seed를 짝지을 수 있지만 요청 timestamp는 배수에 따라 다르다.
- `cases_archive`: 별도namespace50000대. 학습/개발/final과 겹치지 않는 고정 정책 기록용. baseline 수요만 사용.

manifest에는 scenario/route/goal/start/traffic 요청·SUMO seeds·max_time·λ·vTypes/safety 설정·hash를 포함한다. policy checkpoint를 case seed에 섞지 않는다. final 접근과 rerun은 attempt 장부로 추적하고 development 결과를 final로 이름만 바꾸지 않는다.

## 6. 수집·학습·평가의 순서와 수량

아래 수량은 **계획 예산**이다. 실제 카운터는 측정 전이다.

| 단계 | 입력 → 수행 | 실행 수·예산 | 출력·다음 진행 조건 |
|---|---|---|---|
| S0 구현/단위검사 | G1~G3 구현 | fixture·A/B/C 소규모 | 환경/GAE/seed/초기화/필드 통과. 학습성과 아님 |
| S1 feasibility·비용 pilot | B0 + 제한PPO +writer | B0 A/B/C×10cases×3수요=90 Episode; writer10k전이; PPO50k×B2/B3 각1 seed | 비용·수요·reward·공통config를 결정. pilot 가중치/자료는 본학습 초기값·expert_train에 재사용 안함 |
| S2 전문가 pool | 동결B0·baseline 수요·별도case | 최소1,000,000유효전이,Episode 경계까지 마쳐 초과 허용 | raw 성공/실패 모두보존·BC filter·DQ·remote 검증 |
| S3 BC | pool의train/val만 | 3 seed; train200k/val50k;10k updates씩 | B1 seed별정책과 B3용 동일actor;최저 val loss checkpoint |
| S4 PPO 비교 | B2fresh,B3BC actor 초기화 | 2방법×3seed×1,000,000전이=6,000,000 | post-update50k평가/저장; 실제transition/update counters·최종checkpoints |
| S5 고정 정책 평가 | B0/B1/B2/B3의budget-end 정책 | 3수요;B1~3 각3seed×100cases=2700+B0×100×3=300,총3000 Episode | 실패포함episode.csv·조건별raw counts·CI·videos; no learning |
| S6 제출용추가기록 | S5 전 고정한budget-end B2/B3 정책6개 | 각500,000유효전이=3,000,000,완전Episode로 마쳐 초과허용 | archive split,새case,weights 불변;수집용이고 PPO budget 아님 |
| S7 검증·공개·제출 | S2+S4+S6의UID union | **10M 이상**,dev/final/pilot 별도 | DQ/원격 복원·HF/코드/모델/PDF/영상/페이지·iCampus최종파일 |

S5의 final 결과를 보고 S6 정책을 좋은 것만 고르지 않는다. S6는 원래 정한 B2/B3의 **모든6개 budget-end 정책**을 쓰며 성능이 나빠도 그대로 기록한다. archive는 분리된 평가 밖 자료이고 어떤 학습에도 다시 넣지 않는다. S5/S6 순서를 바꿔도 정책·case/seed·비율을 이미 동결한 경우에만 가능하다.

10M는 전문가1M+PPO6M+archive3M라는 보수적인 **계획 장부**다. 전문가 BC train/val view를 풀에서 뽑아도 원본과 중복 계산하지 않는다. expert filter에서 정상완주 자료250k가 확보되지 않으면 B0 품질을 먼저 해결하거나 실제 지원 가능한 sample budget으로 설계를 변경해 모든 방법/seed에 적용한다. teacher 실패를 은폐하거나 다른 controller의 자료를 섞어 수만 맞추지 않는다.

PPO의 정확한 1M 전이/seed를 맞추려면 남은 예산과 다음 50k 평가 경계에 맞춰 마지막 rollout을 짧게 수집한다. 2048 step을 무조건 반복해 cap을 넘기지 않는다. `learner_updates`는 실제 optimizer gradient step 수, `rollout_updates`는 PPO update 호출 수를 따로 기록한다. 같은 rollout을 10 epoch 반복한 횟수를 환경 전이 수에 더하지 않는다.

### 학습·checkpoint 선택·재개

- BC는 train 자료만 gradient에, val loss만 best 선택에 사용한다. 가감속 MSE와 차선 CE를 따로 보고 합으로 선택한다. value head는 BC에서 학습하지 않고 log_std=-0.5로 고정한다.
- B1과 B3는 각 seed별 같은 BC checkpoint에서 출발한다. B2/B3의 네트워크·입력·value head 초기 난수·PPO optimizer 신규 상태·초기 std를 맞춘다. 공유 trunk의 변화가 critic 표현에도 영향을 주는 것은 사전학습 효과에 포함해 기록한다.
- PPO는 0전이와 매 50k의 curve를 남긴다. dev 목표 .80을 두 번 연속 만족한 첫 번째 checkpoint의 전이를 기록한다. 실제 도달은 평가 사이에 있을 수 있어 해상도는 50k다. 예산 내 미달성은 right-censored로 표시하며 임의로 0/1M에 도달했다고 대입하지 않는다.
- 주 final은 **budget-end checkpoint**로 고정한다. dev-best는 보조 결과로만 선택·보고한다. 추가 final 평가를 하면 정책별 100 cases를 추가한 새 실험 ID와 비용으로 구분한다. 좋은 final이 나올 때까지 checkpoint를 바꾸지 않는다.
- 매 50k post-update와 정상 중단 시 모델·optimizer·RNG·전처리·counters·rollout 상태를 저장한다. 환경 상태까지 정확히 복원 가능한지는 SUMO saveState/TraCI 설정의 검증을 거친다. 미검증이면 update/Episode 경계에서 재개해 새 Episode로 기록하고 bitwise 연속이라고 쓰지 않는다. KC-04에서는 직접 XML load의 차이를 발견해 현재 Episode 행동 replay를 채택했다. 작은 CPU 검사에서 전체 상태/후속 실행이 정확히 같았으며 source/runtime와 snapshot 불일치 시 재개를 거부한다. GPU/긴 이력은 pilot 검증 전이다.
- 현재/직전 재개 checkpoint는 디스크에 유지하고 실행 중 config를 바꾸지 않는다. stale owner를 확인한 후에만 재개한다. Drive 백업은 파일 목록/bytes/SHA·원격 readback 통과 후 보관 완료로 표시한다. 이번 작업은 기존 백업·다른 연구 서비스를 조작하지 않는다.

## 7. 측정해야 할 비용·공간·병렬도

이번 읽기 전용 점검 당시 root free는 약 74 GiB다. 이는 새 dataset을 저장하기에 충분하다는 판정이 아니다. 73-D obs/next_obs만 float32로 2×73×4=**584 bytes/T**, 10M에서 5.84 GB(decimal)의 무압축 하한이다. 모든 State/HV·next_state·events·NPZ·checkpoint·백업 여유를 포함하지 않는다. 압축률·총파일 크기는 아직 측정하지 않았다.

S1의 writer 10k가 필수 State를 모두 기록하도록 하여 `jsonl_bytes/T, npz_bytes/T, event_bytes/T, write/read_Tps, peak_RSS, checksum/encode/decode시간`을 측정한다. 밀도별 평균/최대·95th-percentile shard 크기를 함께 남긴다. `needed=(목표잔여T×해당밀도실측bytes/T + checkpoint예상 + upload staging)`의 1.5배와 20 GiB 운영 여유를 가용 공간과 대조하는 팀 기준을 추천한다. 부족하면 저장 볼륨/원격 확정 shard 보관을 준비하며 필수 State를 제거해 맞추지 않는다.

환경/teacher·학습/평가·직렬화 각각의 T/s와 wall/CPU/GPU 비용을 나눠 측정한다. 일반차량 SUMO의 과거 RTF를 학습속도처럼 제시하지 않는다. 우선 learner 1개+평가환경 1개를 기준으로 실측하고, 1/2 worker의 같은 budget benchmark 후 병렬도를 선택한다. GPU 사용만으로 속도를 보장하지 않고 다른 작업의 GPU/RAM 상태를 실행 직전에 읽어 확인한다.

## 8. 명령과 착수 전 확인

### 지금 실행 가능한 읽기 전용 점검

아래는 설치/코드/해시 상태 확인만 한다. 실제 데이터 수집/학습 명령이 아니다.

```bash
cd /home/heven/Artificial-Intelligence-and-Control-for-Autonomous-Driving
git status --short
git rev-parse HEAD
sumo --version
df -h .
sha256sum maps/kcity/kcity.net.xml maps/kcity/kcity.signals.add.xml
```

### 후속 구현에서 제공할 CLI 계약: 현재는 실행 금지

다음 명령은 **구현할 인터페이스의 명세**이며 현재 파일이 없다. config도 이번에 실행 파일로 생성하지 않았다. `--help`/fixture/gate 결과까지 확인한 후 문서와 실제 argv를 대조해야 한다. 기존 고속도로 명령으로 대신 실행하지 않는다.

```text
# <ROOT>는 설계용 placeholder. 실제 실행 config에서 절대경로 확정
python scripts/kcity/preflight.py --protocol configs/kcity/v1/protocol.json --out <ROOT>/preflight --no-training
python scripts/kcity/collect.py --stage expert_pool --protocol <frozen.json> --target-valid-transitions 1000000 --finish-episode --out <ROOT>/expert_pool
python scripts/kcity/validate_dataset.py --manifest <pool_manifest.json> --all-shards
python scripts/kcity/train_bc.py --protocol <frozen.json> --seed 11 --out <ROOT>/bc/seed11
python scripts/kcity/train_ppo.py --protocol <frozen.json> --method B2 --seed 11 --cap 1000000 --out <ROOT>/ppo/B2/seed11
python scripts/kcity/train_ppo.py --protocol <frozen.json> --method B3 --seed 11 --bc-checkpoint <bc11.pt> --cap 1000000 --out <ROOT>/ppo/B3/seed11
# BC/PPO를 seed22,33에서도 별도 run으로 수행
python scripts/kcity/evaluate.py --protocol <frozen.json> --split final --case-manifest <cases_final.jsonl> --policy-manifest <budget_end_policies.json> --out <ROOT>/evaluations/final
python scripts/kcity/collect.py --stage archive_rollout --protocol <frozen.json> --policy-manifest <six_frozen_policies.json> --valid-transitions-per-policy 500000 --finish-episode --out <ROOT>/archive
python scripts/kcity/summarize.py --experiment-manifest <experiment_manifest.json> --out <ROOT>/report
python scripts/kcity/package_release.py --release-manifest <release.json> --check-only
```

`--resume`는 정확한 run_uid/config/checkpoint 해시를 검사해야 한다. 새 가중치로 재시작하는 명령과 재개 명령을 혼동하지 않는다. STOP은 마지막 완결 전이/업데이트 후 저장하고 종료하며 중단 이력은 삭제하지 않는다.

### 시작 직전 리뷰할 출력

`LAUNCH_READY.json`의 필수값은 `phase=READY`, protocol/config/source hashes, gate별 검증 file/hash, time/host, 선택 실행 목록, seeds, 요청 예산, free_disk/예상 용량, 예상 실행 비용, 출력/백업 목적지, owner lock, credential 제외 여부다. **빈 결과·가짜 pass를 넣지 않으며 지금은 파일을 만들지 않는다.**

모든 값을 검토 가능하게 준비한 뒤 수집·학습 착수 여부를 판단한다. 이번 요청은 시행 전 설계까지이므로 다음 실제 구현/실험 작업은 G1부터 이어간다.

## 9. 중단·실패·설계 변경

환경 오류/필수 필드 누락/UID 중복/GAE 불일치/NaN이면 해당 실행을 실패 또는 중단으로 기록하고 원본과 실패 trace를 보존한다. 예산 미달은 실제 전이와 업데이트를 보고한다. 정책 충돌은 성능 실패로 데이터에 남기며 인프라 오류라고 고쳐 쓰지 않는다.

환경/보상/안전 mode/관측 버전이 달라지면 새 protocol·run ID를 부여하고 이전 비교의 참고/무효 여부와 이유를 명시한다. 이번 세부 계약은 이전 73-D 구성·1M 비교 방향을 유지하면서, 10M 추가 기록을 고정 정책 자료로 구체화했다. teacher/filter·원본 행동 구분·전체 next 명시·수요 feasibility·교통 노출 기준은 2026-11-14 결정으로 현황 문서에 연결한다.
