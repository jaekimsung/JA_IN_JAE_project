# KC-03 — 종료·GAE·평가 신뢰성 후보 구현 결과

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../research/RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../research/RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
**KC-03의 제한된 완료 기준을 통과했다. 다음은 KC-04 공통 actor·BC→PPO 초기화/재개다.** 본 학습·전문가 수집·final 평가는 실행하지 않았다. optimizer steps0, `training_ready=false`다.

## 코드와 실행 식별

- 사전 기록: HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`, branch `codex/kcity-kc01-20261114`, 시작부터 있던 미완료 변경을 보존했다. 이번 commit/push/외부 업로드는 없다.
- 변경: [buffer](../../../rl/buffer.py)·[PPO](../../../rl/ppo.py)의 경계/예산/평가 처리, [K-CITY 환경](../../../kcity/env/env.py)의 substep 측정·동시 사건 보존, [기존 highway launcher](../../../legacy/highway/train.py)의 공유 연결 평가 사전 차단. 변경 전4개 source는 `before/`에 보존했다.
- 신규: [case/metric evaluator](../../../kcity/evaluator.py)·[검사 실행기](../../../tools/checks/check_learning.py)·[회귀 검사](../../../tests/test_kcity_learning.py)·[사용 계약](../../specs/KCITY_EVALUATION.md).
- 환경 ID는 `KC-ENV-v2-kc03-candidate`, 지표 ID는 `KC-METRICS-v1-candidate`다. KC-01 protocol/map/TLS pin은 변경하지 않았다. KC-02 결과는 이전 source의 이력으로 그대로 보존했다.
- 최종 source SHA·실행 시각은 [통합 SUMMARY](integration_final/SUMMARY.json), 전체 보호 파일·문서·소스 검증은 [FINAL_CHECKS](FINAL_CHECKS.json).

## 검증 결과

| 항목 | 실제 결과 | 근거/제한 |
|---|---|---|
| 회귀 검사 | **61개 통과**,23.893초 | 당시 검사 요약(원시 로그 삭제); 기존32+KC-03 신규29 |
| 표준 Gym 검사 | 통과 | JSON·로그; A,no background,warmup0,render 제외 |
| 기존 GAE 재현→수정 | 101.959999→**2.960000** | `before/utils/buffer.py`를 별도 import해 과거 수식 재현; 정답2.96 |
| 종료/절단 | termination bootstrap0, truncation terminal V만 사용·trace0 | 동시 flags·autoreset·잘못된 terminal obs·rollout cut 검사 |
| 정확한 예산 | n_steps4,목표7에서4+3,목표 재호출은no-op | update를 mock한 제어 흐름 검사. 실제 학습 성능이 아님 |
| 마지막1행 rollout | NaN 없이 finite loss/통계 | optimizer.step을 mock, 실제 가중치 변경0 |
| 독립 평가 | 공유 env 사전 거부,학습 reset 추가 없음,RNG 복원 | fake env 제어 흐름 검사; 실제 connection 격리는 KC-02 검사도 유지 |
| 실제 PPO rollout | fresh73-D 소형 정책으로3전이 수집,외부2-step 경계 확인 | weight 전후 동일,optimizer state 비어 있음; update하지 않음 |
| 실패 분모 | NaN 정책·투입 실패는유효 실패,소켓 오류는인프라 무효 | helper/실제 reset fixture; 의도적 주입과 정상 결과를 구분 |
| 신호·사건 | 실제 적색/충돌/이탈/제거,황색·unknown·teleport API fixture | 황색을 적색으로 세지 않음. 모든 도로 규칙 판정기는 아님 |
| 분모/지표 | 0신호 통과→NA,unknown→준수/결합률 차단,5/100은<5%실패 | 중복 case 거부,동시 collision/arrival/red flags 보존 |
| 고정 정책 평가 | state_dict 전후 hash 비교,변경 감지시 오류 | 의도적으로 변하는 synthetic fixture도 거부 |

앞선 `TESTS.attempt01.log`(23개), `TESTS.attempt02.log`(55개), `integration_v1`도 보존했다. 최종 source 확인은 `integration_final`을 따른다. `learn/update`는 수학·제어 흐름 fixture에서 mock과 함께 호출했으며 **실제 optimizer step과 본 학습은0**이다.

## 실제 SUMO 통합 평가

최종 실행: `2026-11-14T21:40:23.328177+09:00`~`21:40:37.605723+09:00`. Python3.10.12·Gymnasium1.2.3·SUMO1.28.0,기존 격리 venv를 사용했다. 실행 로그·empty Episode JSON·traffic Episode JSON, 같은 폴더의CSV/AGGREGATE/trace가 원시 근거다.

| 과제 | 배경 교통 | decisions | 실제 시간(s) | 초기HV | 시간가중평균HV | 실제LC | TLS통과 |
|---|---|---:|---:|---:|---:|---:|---:|
| A | 없음 |68|33.8|0|0|0|1|
| B | 없음 |49|24.4|0|0|1|0|
| C | 없음 |181|90.2|0|0|1|4|
| A | 있음 |52|25.7|12|12.92|0|1|
| B | 있음 |49|24.4|14|15.25|1|0|
| C | 있음 |228|113.6|4|11.62|1|4|

6회 모두 지정 goal에 도착했다. 총627개 engineering transitions,AV 충돌/적색 진입/신호 unknown0,각 배경 조건의TLS통과5건을 기록했다. 최종 통합 stdout에는 SUMO Warning/Error가 없었다. 이를 통계적 안전성이나 정책 단독 신호 학습의 증거로 해석하지 않는다.

이번 case는 namespace `contract_check`, scenario별case_index0이다. KC-02의seed42/case_index42와 다르며 동일 case 재현 결과로 비교하지 않는다. 고정 가속·특권 route 정보에 따른 차선 요청 probe다. **B0/학습 AV가 아니며 데이터셋10M에 합산하지 않는다.** C의초기HV4대는 후보10대 기준 미달이므로 교통 충분성은 계속 pilot 사항이다.

## 평가 패널과 남은 작업

- 생성한 패널: dev100,final100×수요1/1.5/2배. namespace/seed 분리·재생성 일치·수요별 기본 seed pairing을 검사했다. 이400개 case는 생성만 했고 **실행하지 않았다**. 원래 고정 namespace 계약은 유지했다.
- 모든 유효 실패는 분모에 남는다. 인프라 무효/미확보를 별도 표시하고 자동 재시도는 하지 않는다. 재시도 장부·분석용Wilson interval/seed paired 분석·최종 제출 집계·통합 preflight는 후속이다.
- 현재 결합 지표는 충돌/적색/경로/goal/기한에 한정한다. 정지·양보 규칙 전체,비신호 crossing 정보의 충분성,모호한 multi-link 진입,경고/정체 원인분석은 더 검증해야 한다. unknown은100%준수로 바꾸지 않는다.
- 부당대기 보상0·시간null,수요/보상/목표/최종 schema 미동결. C초기HV4대와 KC-02의B초기HV5대 사례를 함께 보존했다.
- 기존 `train.py`는 정기평가를 켠 기본 설정이면 **실행 전 오류**로 안내한다. global TraCI를 쓰는 옛 highway 두 인스턴스를 독립 환경으로 오인하지 않기 위한 변경이다. highway 사용자는 `EVAL_INTERVAL=0`+별도`test.py` 또는 연결 독립 실행기가 필요하다. 이번에는 highway 실행/학습을 하지 않았다.
- `save/load`는weights-only이며 전체 학습 재개·공통 masked actor·BC 초기화는 KC-04에서 구현한다. 모델/데이터/맵은 변경하지 않았고 외부 백업·업로드도 하지 않았다.

## 재검사 명령

저장소 루트에서 새 output 경로로 실행한다.

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B -m unittest discover -s tests -p 'test_kcity*.py' -v
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/check_learning.py --output /tmp/kcity-kc03-new-check
```

삭제된 old-buffer 사본을 재현 입력으로 사용하지 않는다.
