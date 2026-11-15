# K-CITY 결과 분석·컨설팅·최종 제출 계획

갱신: 2026-11-16. **3seed pilot 완료, 본1M 비교·final·제출10M는 미실행**이다. 본 결과표와 실제 pilot을 구분한다.

[데이터 명세](DATA_COLLECTION_SPEC.md) · [실행 프로토콜](EXECUTION_PROTOCOL.md) · [연구 현황](RESEARCH_STATUS.md) · [실험 인덱스](EXPERIMENTS.md)

## 1. 평가 요구를 결과물로 연결

아래 요구의 근거는 [6_Project_Evaluation.md](../project_materials/6_Project_Evaluation.md)다. ‘팀 설계’는 수업의 공식 수치 기준과 구분한다.

| 평가 요구 | 제출할 증거 | 연결할 데이터·파일 | 완료 판정 |
|---|---|---|---|
| 실제 도로 특징·선정 이유 | K-CITY 원본/변환 지도와 A/B/C 경로 그림 | source/manifest, route/config hashes | 출처·합성 신호/가정·생략 범위를 함께 설명 |
| 도로→interaction→의사결정 | 신호 대기/재출발, 필수 Lane 확보, 연속 교차로 사례 | detected/traffic exposure/events·route transition | HV와의 상호작용이 실제 trace/영상에서 확인됨 |
| Collision Rate <5% | AV 관련 충돌 Episode의 분자·분모·seed별 비율 | episode_summary.csv + collision events | 예:100 Episode면0~4 collision Episode가 관찰 기준 통과. 소수점 반올림으로5%를 <5%라 하지 않음 |
| 목적지 정상 완주 | 지정 goal/route·기한·정지/텔레포트/실패 집계 | end_reason,route_valid,goal_valid | 충돌0만 보고 성공이라고 하지 않음 |
| 충분한 일반차량 | 요청 수요·실제 HV 수·밀도·근접차·interaction 비율 | state.vehicles,traffic requests,episode exposure | 숫자가 미정인 수업 요건을 팀 pilot 기준/원시 분포와 함께 확인 |
| Dataset ≥10^7 | 유효 UID union,필수 State/transition,필드 설명·검증·복원 | RELEASE_MANIFEST·DQ report·HF 링크 | JSON/NPZ·HV snapshot 복제 중복 없이 ≥10M, 전체 파일 접근 가능 |
| 30초 이상 실제 주행 영상 | 실제 SUMO 정책 주행 화면,정책/시드/route/수요 표시 | video metadata·event trace·checkpoint hash | 실제 정책 실행 영상 ≥30초,생성 그림/IDM 데모를 학습 AV로 표시하지 않음 |
| 실행 가능한 코드/모델 | 환경·학습·평가·수집을 구분한 사용법·고정 모델 | code revision·dependency lock·model manifest | 별도 준비 환경에서 재현 명령/모델 load·짧은 replay 확인 |
| 프로젝트 페이지/발표/데이터 | GitHub,PDF 접근 링크,Hugging Face 연결 | release link registry | 외부 접근·버전·최종 iCampus 제출 파일 SHA 일치 |

수업 최종 발표는 문서상 **11/28(토) 13:00~19:00, 팀당13분 예정**이다. 이것을 iCampus 제출 마감 시각으로 대입하지 않는다. 마감/업로드 용량/최종 시간표는 공지에서 별도로 확인해야 한다. 문서상 마감 후 최신화는 인정되지 않으므로 최종 파일과 링크의 버전을 고정한다.

## 2. 분석의 최소 테이블

행 단위 전이를 그대로 그래프에만 그리지 말고 다음 단계를 재현 가능하게 만든다. `summarize.py`는 구현 예정이며 현재 존재하지 않는다.

### 2.1 episode_summary.csv: 유효 평가 Episode당 한 행

| 열 묶음 | 필수 컬럼·정의 |
|---|---|
| 식별 | experiment/run/case/episode/attempt UID,method,train_seed,eval_seed,scenario,route_id,demand_id,policy/checkpoint SHA |
| 분모 | expected_case,attempt_valid,infrastructure_invalid_reason,performance_failure_reason. 무효/재시도 원시 기록은 별도 attempt.csv |
| 종료·안전 | arrival_event,correct_goal,correct_route,ever_AV_collision,red_entry_count,tls_crossing_count,tls_crossing_unknown_count,teleport/removal/deadline,primary_end_reason |
| 성공 | completion,compliant_completion. 전자는 지정 경로·goal 도착, 후자는 기한 내 충돌·정의된 신호 위반 없이 완료 |
| 시간·거리 | elapsed_s,moving_s,standstill_s,unjustified_wait_s,route_progress_m,route_length_m,completion_fraction,route_efficiency(정의 가능한 case만) |
| 교통·interaction | requested/actual_departures,pending_max,HV_start/min/time_weighted_mean,neighbor_present_fraction,red_exposure,required_LC_exposure/achievement |
| 행동 | commands_left/right,command_accepted,executed_LC_count,known_rejection_counts,accel_clip_fraction,unknown_override_count |
| 품질 | valid_transition_count,missing/duplicate_rows,terminal_snapshot_valid,event_classifier_version,raw_data_manifest |

충돌·위반·경로 이탈이 동시에 발생할 수 있으므로 ever flags를 독립 보존한다. primary reason 우선순위는 `collision → red_entry → wrong_route → teleport → removal → arrival → deadline`로 사전 고정하고, 뒤 사건을 삭제하지 않는다. teleport/removal은 시스템 비정상 실패이며 발생한 실행을 성공으로 복구하지 않는다.

`attempt.csv`에는 무효·중단·실패를 포함한 모든 시도를 기록한다. 외부 소켓 장애처럼 사전 정의한 인프라 오류만 무효로 분류하고 같은 case를 재시행한다. 정책 NaN·AV 소실·긴 투입 지연을 유리하게 제외하지 않는다. 평가 종료까지 유효100개를 확보 못 하면 `유효n/계획100,무효m,중단k`를 함께 적는다.

### 2.2 condition_summary.csv: 방법·학습 seed·수요·과제별

주요 필드는 `n_planned,n_valid,n_invalid_attempts,n_completed,n_compliant_completed,n_collision,n_red_episode,n_teleport,n_removal,n_deadline,completion_rate,compliant_completion_rate,collision_rate,red_episode_rate,n_tls_crossings,n_red_crossings,signal_compliance,mean_elapsed_all,mean_elapsed_completed,penalized_time_all,mean_wait_all,HV_mean,interaction_fraction`이다. ratio만 저장하지 말고 원시 분자·분모도 둔다.

모든 유효 Episode의 실제 관측시간 평균과 **완주자만의** 시간 평균을 함께 표시한다. 충돌로1초 만에 끝난 정책이 빠르다고 보이지 않도록 `penalized_time_all=완주자는실제시간,실패자는과제기한300s`의 평균도 보조 지표로 제시한다. 이는 팀이 정의한 실패 비용이지 실제 주행 시간이나 관측된 생존시간 평균이 아니다. 가정 변경은 새 지표 버전으로 기록한다.

현재 평가기의 구현 출력과 후속 분석용 열의 차이는 manifest에서 명시한다. 위 snake_case CSV는 최종 분석기의 목표 계약이며 현재 EPISODES/SUMMARY JSON에 모두 그대로 구현된 열이라는 뜻은 아니다.

신호 준수율은 `1-red_crossings/valid_tls_crossings`, 교차 통과가0이면 **NA**다. unknown crossing은 조용히 분모에서 빼고100%로 쓰지 않으며 `n_unknown`과 지표 신뢰성 gate를 표시한다. signal fidelity가 확인되지 않으면 결합 성공률 역시 잠정치로 표시하고 final 산출을 차단한다.

### 2.3 learning_curve.csv와 cost_ledger.csv

- learning curve: method,seed,checkpoint_id,actual_PPO_transitions,optimizer_steps,rollout_updates,BC_updates,dev_case_manifest,scenario별 성능·위험·완주와 goal_reached status. x축은 epoch/파일 번호가 아니라 **실제 환경 전이**다.
- 비용 장부: stage/expert_generation/BC/PPO/dev/final/serialization/backup별 요청·유효 전이,optimizer steps,wall_s,CPU_s,GPU_s 또는 지원되는 계측값,peakRAM/GPU/bytes. GPU 시간 미계측을0으로 채우지 않는다.
- 목표 도달: validation 결합성공≥.80을 두 번 연속 만족한 두 checkpoint 중 첫 시점(두 번째는 확인점). `reached_at_T / not_reached_within_budget`와 평가 간격50k를 기록한다. 초기 성능과 예산 종료 성능을 별도 비교한다.
- 전문가 pool이3 seeds에 공유되면 총 생성 비용을 한 번 집계하고 모델별 배분 비용은 별도 열로 둔다. BC/PPO 비교의 효율 표에 전문가·BC 비용을 숨기지 않는다.

## 3. RQ별 표와 그림을 먼저 고정

| RQ | 필수 표/그림 | 읽는 방식·금지 해석 |
|---|---|---|
| RQ1 학습 효율 | B2/B3 seed별 dev성능-vs-T 곡선; 목표 도달T표; 동일1M endpoint표;전체 비용표 | BC 초기 우위와 최종 우위를 구분. 목표 미달성을 임의 수치로 치환하지 않음 |
| RQ2 수요 일반화 | 정책 고정,λ0/1.5λ0/2λ0별 결합성공·충돌·완주·위반·대기;실현밀도/queue도 함께 | λ와 밀도는 다름. 다른 안전설정·재학습·final 조건 사후변경 금지 |
| RQ3 추가구성 | 자연/균형 동일N·업데이트·schema·seed의상황 분포+BC/PPO곡선 | 주실험 이후 선택사항. 데이터수·teacher 실력 차이가 아닌 구성효과 |
| 과제/실패 | A/B/C별 개별 성능;실패taxonomy빈도;요청/실측/신호·차간거리 timeline;대표 영상 | 사건 발생만으로 원인 단정 금지. 실패 로그·기각 설정도 남김 |
| Dataset | split별고유수·필수 컬럼·단위·정지 비율·interaction·중복/누락·SHA coverage | 데이터많음만으로 정책품질 주장 금지 |

seed 3개를 3개의 독립 학습 반복으로 보고 원자료·평균·min/max를 함께 제시한다. 같은 final cases를 사용한 방법 간 차이는 학습 seed별 paired 차이로 보고한다. 수천 Episode를 독립 학습 seed처럼 취급하지 않는다. Episode-level rate의 Wilson 95% interval을 부가적으로 제시하되 seed 불확실성까지 해결한 것은 아니다. 3 seeds만으로 작은 차이의 통계적 우월/비열등성을 선언하지 않는다.

100 Episode에서 0충돌이 관찰돼도 ‘실제 충돌확률 0’이라고 쓰지 않는다. `관찰0/100`과 신뢰구간·동일 case 범위를 명시한다. 4/100은 관찰상 <5%이지만 그 분포의 충돌확률 <5%가 통계적으로 입증된 것과는 다르다.

본 실험 결과 표 틀(본 모델·final은 전부 미측정, pilot과 구분):

| 방법 | seed | PPO T | dev목표 도달 T | final수요 | 안전·규칙완주 n/N | 충돌 n/N | 일반완주 n/N | 신호 위반/통과 | 전체/완주자시간 | 전체 비용 |
|---|---|---:|---|---|---|---|---|---|---|---|
| B0 규칙전문가 | 없음 | 0 | 해당없음 | 측정전 | 측정전 | 측정전 | 측정전 | 측정전 | 측정전 | 측정전 |
| B1 BC-only |11/22/33개별|0|해당없음|측정전|측정전|측정전|측정전|측정전|측정전|측정전|
| B2 PPO-only |11/22/33개별|계획1M|측정전|측정전|측정전|측정전|측정전|측정전|측정전|측정전|
| B3 BC→PPO |11/22/33개별|계획1M|측정전|측정전|측정전|측정전|측정전|측정전|측정전|측정전|

## 4. 대표 trace·영상 선정

결과를 본 뒤 최고 성능 case만 고르는 것을 막기 위해 기본 영상 후보는 final 패널의 B3 seed11·λ0·C의 case_index0으로 미리 지정한다. 성공/실패와 상관없이 실제 결과를 그대로 표시한다. 대표성 설명을 위해 같은 case의 B0/B2도 나란히 재생하고 checkpoint·case·traffic hashes를 연결한다. 실패가 있으면 실패군에서 각 taxonomy의 가장 낮은 case_index를 추가한다.

별도 렌더 재실행은 같은 policy와 seed/settings로 수행하고 원래 headless 실행과 사건·도착·metric이 허용오차 내 일치하는지 확인한다. 다르면 원래 결과 영상이라고 하지 않고 새 render attempt로 등록해 불일치를 조사한다. 렌더 영상 수집을 final 추가 학습으로 쓰지 않는다.

영상에는 도로 구조·노란 HV·학습 AV·신호·interaction·목적지 주행이 보여야 한다. 표시 항목은 정책 B/seed/수요/과제/배속과 sim_time이다. 이를 실차 주행/실세계 검증 영상으로 소개하지 않는다. 녹화 파일은 30초 이상 실제 시뮬레이션 화면이어야 하며 짧은 영상 복제로 길이만 늘리지 않는다. 후보 Episode가 너무 짧으면 별도 C 전체 경로 데모를 1배속 또는 명시한 감속으로 녹화하고, 실제 30초 이상 주행하는 과제를 먼저 확인한다. 목적지 도착·실패를 편집으로 숨기지 않고 원본도 보존한다.

영상 metadata에는 `render_run_uid,source_eval_uid,checkpoint_SHA,case_SHA,net/signals_SHA,start/end_sim_time,wall_duration,sim_duration,fps,speed_factor,frame_count,SHA256`를 기록한다. 30초 이상인지 ffprobe 등으로 확인하고 PDF/페이지에서 실제 열리는지 점검한다.

## 5. 컨설팅 준비: 5분 설명 + 최대3분 질의

[7_Project_Consulting.md](../project_materials/7_Project_Consulting.md)는 **11/17 또는 11/24, 13:30~14:45, 배정된 날 1회, 5분+최대3분**이라고 명시한다. 팀별 날짜/순서는 문서에서 아직 미배정이다. 우리 팀 배정은 확인 전이며 두 날짜 모두 예약됐다고 간주하지 않는다. 아래는 내부 준비 일정이며 공식 공지의 변경을 확인해야 한다.

| 설명 시간 | 보여줄 것 | 현재 증거·정직한 표현 |
|---|---|---|
| 0:00~0:40 | K-CITY 지도·신호/필수 LC/연속 경로의 의미 | 실제 Edge 후보와 합성 신호/현장 자료의 한계 |
| 0:40~1:30 | 일반차량/AV 역할·A/B/C route | 기본 demo_ego는 IDM. 별도 학습정책 GUI는 pilot모델이며 본 결과와 구분. 177대는 교통 기반 결과 |
| 1:30~2:30 | 데이터 컬럼·절대 State·한 전이·10M 장부 | [데이터 명세](DATA_COLLECTION_SPEC.md) 4~8절의 축약표 |
| 2:30~3:40 | B0/B1/B2/B3·통제 변수·수요 평가 | 초기화 외 조건 동일,3seed pilot완료·본실험0. seed/GAE/BC/재개는 제한된검증 완료 |
| 3:40~5:00 | 막힌 지점·확인 질문 우선순위 | 전체 설명을 반복하지 말고 아래 1~3 질문부터 |

컨설팅에 가져갈 자료 묶음: 기존 중간발표 자료, 아래 역할표 1페이지, 현재 맵/교통 화면과 출처, 절대 State 포함 컬럼표 1페이지, 실험 matrix 1페이지, [과거 audit 결과](research_checks/KC-AUDIT-20261110-01/evidence/summary.json)와 GAE 재현값, 현재 미완료 final/archive/제출 gate 목록. 새 학습 결과가 없으면 있는 것처럼 발표하지 않는다.

| 우선 | 질문 | 팀 추천 답/왜 확인이 필요한가 | 답변에 따른 변경 |
|---|---|---|---|
| 1 | 관측 차원19 표기와 달리 기본코드는31-D이고 K-CITY는73-D로 구현·동결했는데, 기본 필드 유지+확장을 이 형태로 제출해도 되는가? 추가 컬럼 scope 제한이 확정됐는가? | 절대 State/기본 key 전부 유지, JSONL+NPZ. 문서상 확장 허용이지만 중간발표 후 scope 제한 예정 | 수업 인정 범위 확인. 변경 요구가 있으면 새 schema·전 방법 재학습 영향 검토 |
| 2 | 10^7의 단위는 AV 유효 transition으로 세고 expert/학습 log/fixed 정책 archive를 출처 분리해 합산해도 되는가? compression/shard/손실없는 next참조+loader 복원 형식을 인정하는가? | 1M+6M+3M 추천, 복제/HV/substep 미합산. 10M를 학습 예산으로 오해하지 않음 | 수집 장부·목표·HF 구조 |
| 3 | ‘충분한 HV/interaction’ 판정에 요구되는 최소 수/밀도나 대표 상황이 있는가? | 팀 내 HV≥10·노출 비율은 pilot 후보이며 교수 기준 아님 | traffic/case feasibility·영상/지표 |
| 4 | 합성 감응식 신호·SUMO 기본 안전 설정을 공통으로 쓴 시스템 비교 범위가 적절한가? | 실측 현시 복원/정책 단독 안전 주장 안함. 필수 LC와 경로/신호 행동을 trace로 설명 | 주장 범위·추가 진단·수업 기대 정렬 |
| 5 | 최종 iCampus 정확한 마감/업로드 제한·모델/원시 데이터 포함 범위와 팀 발표/컨설팅 배정은? | 발표11/28과 제출 마감은 다름. 문서에는 실제 마감/배정 없음 | 동결 일정·업로드/제출 형식 |

팀 역할 1페이지 템플릿: `팀이름(확인 전) / 팀원실명(미배정) / 환경·교통 / 데이터·B0 / BC·PPO / 평가·영상·페이지 / 각 인계물·검토자`. 임의 이름을 작성하지 않으며 실제 담당자 확정 후 갱신한다.

## 6. 현재 결과와 다음 준비

3seed pilot의 실제 성과는 [설정 확정 집계](research_checks/KC-SETTINGS-20261115-01/SUMMARY.json)와 [현황](RESEARCH_STATUS.md)을 따른다. BC/B2/B3 끝정책9개는 각각 dev100에서100/100완주·AV충돌/적색0이었다. BC초기우위와 중간필수LC실패가 함께 관찰됐다. 평균완주시간은 BC58.240초·B2 57.560초·B3 57.655초다. 이 작은 차이로 방법의 일반적 우월성을 주장하지 않는다.

| 다음 작업 | 필요한 증거 | 현재 |
|---|---|---|
| 컨설팅 | 연구질문·73D/기본필드·10M장부·pilot곡선/실패·교통노출·남은gate | 질문정리됨,실제팀배정/답변미확인 |
| 새expert→BC→PPO | 신규pool/views/3seedBC/6run1M,실제T/update·비용·재개 | 운영준비완료·본0 |
| 고정final/archive | 3수요3000Episode·6정책고정기록3M·weights/분모/UID | 미실행·통합CLI후속 |
| 최종제출 | ≥10M·전역병합·HF복원·모델/영상/PDF/페이지·링크/제출SHA | 미완료 |

시간/공간 부족 시 RQ3·회전교차로·긴급차량 확장을 먼저 보류한다. 필수State/10M/실패분모를 줄이거나 좋은seed만 고르지 않는다. 핵심예산·평가규모도 바꿔야 하면 사전설계변경과 불확실성을 기록한다. Drive 업로드는 하지 않는다.

## 7. 최종 결과 보고서와 발표 구성

결과 파일은 계획과 분리해 `report/FINAL_REPORT.md`에 작성할 예정이다. 지금은 만들어진 결과로 제시하지 않는다. 다음 순서를 고정한다.

1. **목적/도로/가정**: K-CITY 선정 이유·A/B/C·신호/교통 합성 범위·연구 질문.
2. **환경/MDP**: 실제 사용 obs/action/reward/종료·mode·지도/설정 버전과 seed.
3. **데이터**: 필수 컬럼·절대 State·정렬·split/출처·유효 고유 수·누락/중복/정지/interaction·비용.
4. **학습/실험**: B0/B1/B2/B3·동결 예산·초기화·checkpoint 선택·dev/final 분리·실패/중단 실행.
5. **결과**: 위 표·곡선·목표 도달 T·budget-end 성능·수요 이동·실패 trace·실제 영상.
6. **해석/한계**: 가설 지지/반대/불명확, 총비용, seed3개 한계, SUMO 안전 기능, 같은 맵 수요 변화 한정.
7. **재현/제출**: 코드/모델/데이터/PDF/영상/페이지 URL과 정확한 revision·SHA·실행 방법.

13분 발표 배분 추천은 목적/도로 2분, interaction·MDP 2분, 데이터 2분, 학습/비교 2분, 결과/영상 3분, 문제 해결·한계·결론 2분이다. 영상 30초 이상은 결과 시간에 포함한다. 실제 팀당 운영 시간이 바뀌면 최종 공지에 맞춘다.

## 8. 공개·제출 패키지와 최종 점검

| 위치 | 포함물 | 검증 |
|---|---|---|
| GitHub | 환경/학습/평가/수집코드,고정config·설치/재현법,작은집계·문서 | clean/frozen revision·필요하면 dirty patch·민감정보 제외·외부접근 |
| 모델보관/제출 | B1/B2/B3모델과policy/config/version·SHA·재개자료별도 | 모델load·짧은검사,weights-only와fullresume구분 |
| HuggingFace | ≥10M 유효고유transition,JSONL/NPZ/shardmanifest/schema/DatasetCard | 전체목록/SHA·원격coverage·실제loader/다운로드복원 |
| 발표자료 보관 위치(미정) | 최종발표PDF·영상/보고. 현재 Drive 업로드 금지 | 향후 허용된 제출 경로에서 PDF열림·영상재생·접근권한·release일치 확인 |
| 프로젝트페이지 | 무엇/도로/interaction/실행/결과/한계와위링크 | 다른브라우저/세션에서접근성·brokenlink확인 |
| iCampus | 공지된형식의코드·모델·데이터·발표자료와링크/manifest | 마감전업로드·다운로드재확인·제출 파일SHA·제출시각증거 |

Hub는 [공식 업로드 절차](https://huggingface.co/docs/datasets/upload_dataset)에 따라 dataset repo와 card를 준비한다. 실제 계정/저장소/라이선스/공개 범위는 정해지지 않았으며 이번 작업에서 repo를 만들거나 업로드하지 않았다. 현재 Drive 백업은 금지돼 수행하지 않았다. 최종 Hugging Face 제출은 별도 작업이다. 수업 문서의 동료 평가/예시 페이지는 보조 링크이며 이번 작업에서 그 내용을 검토한 것으로 주장하지 않는다.

최종 release는 `code_commit,protocol_hash,data_manifest_hash,model_manifest_hash,presentation_sha256,video_sha256,links_verified_at,submitted_at`를 고정한다. iCampus 제출 후 새 commit이 생겨도 어떤 파일이 평가 대상인지 명시한다.

## 9. 컨설팅 결정·수행 기록 양식

아래는 복사해서 실제 답변/실행 후 채울 템플릿이며 확인된 사실이 아니다.

```text
날짜/시각/시간대: 확인 전
컨설팅 배정/참석자: 확인 전
질문 ID/답변 원문 또는 요지: 확인 전
결정/적용할 protocol/schema version: 미정
기존안과 차이/이유/영향/무효 또는 참고 처리할 실행: 미정
수정 담당/검토자/다음 gate/완료 증거: 미배정
```

각 결정을 RESEARCH_STATUS의 결정 기록과 EXPERIMENTS의 해당 설계/실행 ID에 연결한다. 컨설팅 조언을 이미 받은 것처럼 선작성하지 않는다.
