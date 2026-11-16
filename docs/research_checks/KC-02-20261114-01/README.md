# KC-02 — 독립 K-CITY Gym 환경 구현·검증

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../research/RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../research/RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
상태: **KC-02 후보 구현과 작은 검사 완료**. 다음은 KC-03이다. `training_ready=false`, 학습 업데이트0, 전문가 dataset 전이0을 유지한다.

## 식별과 변경 범위

- 사전 등록: PROVENANCE.json. 시작 `2026-11-14T20:56:03.554322+09:00`, HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`, local branch `codex/kcity-kc01-20261114`. 시작부터 기존 미완료 변경이 있었으며 이를 보존했다. 이번 commit/push·외부 업로드는 없다.
- 구현 ID `KC-ENV-v1-kc02-candidate`. [환경](../../../env/env.py)·[경로 기하](../../../env/route.py)·[관측](../../../env/observation.py)·[검사 실행기](https://github.com/jaekimsung/JA_IN_JAE_project/blob/fac8482/tools/checks/check_env.py)·[회귀 검사](../../../tests/test_kcity_env.py)를 새로 추가했다.
- Python3.10.12, Gymnasium1.2.3, NumPy1.24.4, SUMO1.28.0. 기존 격리 venv를 사용했고 기존 고속도로·PPO/BC·맵·신호·모델·데이터와 KC-01 실행 source/config는 수정하지 않았다.
- 현재 사용법과 상세 계약: [KCITY_ENV.md](../../guides/KCITY_ENV.md). source hash는 [최종 통합 summary](integration_final/SUMMARY.json), 보호 파일 검증·종료 시각은 [FINAL_CHECKS.json](FINAL_CHECKS.json).

## 구현한 범위

1. A/B/C manifest·독립 seed/traffic 요청을 사용하는 reset. 연결별 TraCI handle·SUMO process·임시 파일을 소유한다. 오류와 insertion 실패는 명시적으로 드러낸다.
2. 73-D float32 관측·차선 mask·detected 목록·전체 절대 State를 분리한다. 내부 Lane과 매우 짧은 Edge의 진행을 route occurrence로 추적한다. 진행도 좌표와 실주행 거리는 별개다.
3. raw→clip→가속도/차선 요청을 기록한다. 정상 step은 0.1초×5회이며 사건/기한이 생기면 일찍 끝낸다. mode31/512·속도 상한8.33 m/s를 실제 조회로 확인했다.
4. 충돌·적색 진입·실제 LC·도착·teleport·제거·경로 이탈, 유한 과제 기한의 종료 처리. 외부 결정 횟수 제한은 별도 truncation wrapper다.
5. ego가 없거나 경로가 무효한 종료의 0 관측과 validity=false, 실제 before/after 상태·제어 결과·사건·보상 component를 제공한다.

## 검사 결과

| 검사 | 결과·근거 | 범위 |
|---|---|---|
| KC-01+KC-02 회귀 | **32개 통과**, 16.626초. 당시 검사 요약(원시 로그 삭제) | KC-01 16개 + KC-02 16개 |
| 표준 Gym API | **통과**, JSON·stdout·stderr | A,배경차 없음,warmup0,render 검사 제외 |
| 실제 reset 재현 | seed42 반복 초기 State SHA/관측 일치,43은 상이 | 배경 교통·60초 warmup·한 PC의 제한 seed 검사 |
| 연결 격리 | 두 환경 중 한쪽 step/close가 다른 쪽 시간을 바꾸지 않음 | 독립 connection·반복 close |
| 관측/제어 | 73-D·bounds·finite,raw/clip 구분,5 ticks,mask/cooldown | 일부 semantic 값 및 경로 경계 fixture 포함; 모든 상황 완전 검증 아님 |
| 고장 주입 | 강제 적색 진입·충돌·차량 제거·경로 이탈 검출 | 검사 안에서만 moveTo/신호/안전 mode를 바꿈. 연구 성능·기본 설정 결과에서 제외 |
| 시간 경계 | 과제0.7초에서 정확히7 ticks 종료, 외부2 decisions에서 truncation | 마지막 partial step·terminal observation 검사. learner GAE는 아직 수정하지 않음 |

초기 검사/개선 이력도 보존했다. `TESTS.attempt01/02/03.log`는 각각 당시11/14/32개 검사 결과다. 최초 표준 Gym 검사에서는 설정을 `self.spec`에 저장해 Gym의 예약 EnvSpec과 충돌했다. 실패 stderr를 보존하고 `self.contract`로 수정한 후 최종32개 검사·Gym·통합 실행을 다시 통과했다. 최종 회귀 검사에 예약 속성 보존도 포함했다.

## 최종 6회 통합 실행

최종 실행은 `2026-11-14T21:08:32.682728+09:00`~`21:08:48.220685+09:00`이다. [summary](integration_final/SUMMARY.json)·stdout/경고를 따른다. 모든 case에서 seed42를 사용했다. 배경 없음은 warmup0 검사 변형이고, 배경 있음은 후보 수요600 vph·warmup60초다.

| 과제 | 배경 차량 | AV decisions | 에피소드 실제 경과(s) | 초기 HV / 실행 중 최대 HV | 종료 |
|---|---|---:|---:|---:|---|
| A | 없음 | 68 | 33.8 | 0 / 0 | 도착 |
| B | 없음 | 49 | 24.4 | 0 / 0 | 도착 |
| C | 없음 | 181 | 90.2 | 0 / 0 | 도착 |
| A | 있음 | 52 | 25.7 | 13 / 14 | 도착 |
| B | 있음 | 49 | 24.4 | 5 / 9 | 도착 |
| C | 있음 | 224 | 111.9 | 13 / 29 | 도착 |

총623개의 engineering transition trace를 저장했다(8,897,061 bytes, 비압축). 경로 진행도 비감소·관측 bounds·substep 계약·통과 신호 매핑이 이 6회에서 확인됐다. 최종 통과 신호는 모두 G였다. 앞선 `integration_v1`, `integration_v2`의 실행도 각각 별도 보존했으며 최종 source 식별에는 `integration_final`만 사용한다. 18회의 반복을 독립 seed 성능 표본으로 세지 않는다.

이 제어는 일정 가속도와 사전 지정 차선 요청을 사용하는 디버그 스크립트이며 특권 route 정보를 참조한다. **B0 전문가·BC/PPO 정책·RQ1/RQ2 결과가 아니다.** trace는 schema 전체를 충족하는 제출용 수집 자료가 아니므로 10M 장부에 넣지 않는다.

## 남은 한계와 필요한 후속 작업

- **교통 충분성:** B의 초기 HV5대는 후보 기준10대 미달이다. 수요600 vph는 요청률이고 실측 밀도와 같지 않다. 이번에는 조건을 조정하지 않았다. KC-06에서 과제 주변 차량·상호작용까지 검토해 수요/warmup/경로와 기준을 확정해야 한다.
- **경고:** A 교통 case에서 HV `344e8c40733ed229-hv-000005`가 time72.10에 lane`-10_0`에서 decel8.0 m/s²의 emergency braking 경고를 남겼다. 최종 AV 사건 목록의 충돌/적색 진입0을 전체 교통 안전성 증거로 확대하지 않는다.
- **보상:** 진행·도착·충돌·적색·거부·실제 LC component만 후보 구현했다. `unjustified_wait=0`이다. 정당한 대기/양보를 분리하는 판정 없이 벌점을 넣지 않았다. 최종 보상 동결은 미완료다.
- **신호·규칙:** 진입 연결이 모호하면 classification_valid=false를 남긴다. 모든 multi-link/황색·동시 사건/정지·양보 준수 지표와 denominator는 KC-03에서 확장해야 한다. 현재 비신호 접근 관측은 정적 rule 표시이며 crossing 차량의 별도 actor 슬롯은 없다. B0/pilot에서 정보 충분성을 검토한다.
- **재현:** 제한 seed·한 PC에서의 결과다. 플랫폼별 SUMO/의존성·worker·정책 RNG·분리된 dev/final panel은 후속 실행기에 고정한다.
- **학습:** 기존 PPO truncation GAE 누출은 그대로이며 KC-03에서 수정한다. BC→PPO 공통 actor·정규화/분포 호환과 전체 resume는 KC-04, 전문가/writer는 KC-05다.
- **설정 상태:** KC-01의 JSON contract와 `observation.implemented=false` 당시 값은 보존했다. 이번 구현은 별도 implementation ID/source hash로 구분한다. `training.enabled=false`, `research_settings_frozen=false`를 유지한다.

다음 단계 **KC-03**에서는 bootstrap/trace 경계·terminal observation·평가 지표의 분자/분모와 사건 fixture를 검증한다. 그 뒤 KC-04/05/06을 거쳐 본 수집·학습 착수 여부를 판단한다.

## 이번에 사용한 명령

저장소 루트에서 실행했다. 기존 결과 경로 재사용은 금지한다.

당시 사용한 검사 실행기는 저장소에 남아 있다. 재검사는 현재 사용 안내의 새 output 명령을 따른다.
