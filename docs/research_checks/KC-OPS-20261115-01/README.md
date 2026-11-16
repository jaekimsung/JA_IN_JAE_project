# KC-OPS: 본 실험 운영 준비 검증

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../research/RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../research/RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
상태: **READY_LOCAL_ONLY**. 전문가1M·BC·PPO6M을 실행할 운영 준비를 검증했다. **본 전문가0전이·본 BC0updates·본 PPO0전이**이며 이번에 실제 실행한 optimizer 작업은 아래 검증용뿐이다.

사용자 지시로 **Drive 업로드는 하지 않았다**. 원격 백업은 미검증·미실행이며 요구사항을 로컬 보관으로 변경한 사유를 [진도](STATUS.json)와 출처에 남겼다.

## 구현

- [본 실행기](../../../runner/train_ppo.py): collect / views / bc / ppo. 4개 check-only가 실제 output 없이 통과했고, launch record 없는 본 실행은 거부됐다.
- [운영 계층](../../../training/ppo.py): 고정 설정/해시/owner/디스크 검사, 새 전문가 pool·성공 whole-Episode BC view, same-seed BC actor 이식, 정확한1M cap·post-update50k dev100.
- PPO의 전체 State/NPZ/사건과 learner bundle을 같은 shard에 atomic commit한다. 부분 rollout STOP, 정상 rollout 경계, 평가 경계, 예산 끝의 STOP을 연속 실행과 비교했다.
- 기존 B0 전용 validator에 명시적인 online PPO provenance 분기만 추가했다. [호환 SHA](https://github.com/jaekimsung/JA_IN_JAE_project/blob/fac8482/configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json)로 원래 frozen 자료와 연결한다. 환경/보상/actor/PPO 수식과 과학 설정 JSON은 보존했다.

## 실제 검증 결과

| 검사 | 실행·결과 |
|---|---|
| 회귀 검사 | 118개 통과,66.245초. 로그 |
| GPU BC | 생산[256,256], synthetic label, save/resume 후 weights/Adam/sampler/손실 일치. 검증 optimizer 총9회 |
| 긴 GPU 재개 | 실제 pilot50k·7,850 optimizer 이력을 검증용으로 복원. T50,007·부분 buffer7·현재 Episode replay407결정에서 저장하고 별도 프로세스로 재개. 다음64전이 및 업데이트 후 weights/Adam/RNG/trace/counters 완전 일치 |
| 전문가 기록·재개 | 17전이에서 STOP,17결정 replay,최종2,137전이·19완료 Episode. 목표2,048을 넘겨 현재 Episode를 정상 종료. 전체 DQ 통과,본 pool eligibility=false |
| fresh GPU 기록·재개 | T2,055·부분 buffer7을 저장. 재개 후 T2,119·rollout2·optimizer340,같은 연속 실행과 정확히 일치. 기록된 고유 전이2,119개와 learner 카운터 일치,전체 DQ 통과 |
| 메모리 | 검증 부모 프로세스 peak RSS 약1.86GiB. 10M 전체를 RAM에 적재하는 검사가 아님 |
| 로컬 보관 | 압축 파일의 모든 구성 파일을 다시 읽고 SHA 일치 확인. 검증 영수증. 원본 삭제/원격 업로드 없음 |

native GPU probe의407결정 중400결정은 긴 환경 replay를 확보하는 명시적인 차선 유지 fixture다. 이 prefix를 learner 전이로 세지 않았다. 기존 pilot 모델을 본 초기값으로 사용하지 않는다.
작은 범위의 연속/재개 동등성 검증이며,1M 본 실행 완료나 모든 장기 장애를 검증한 것은 아니다.

[상세 결과](SUMMARY.json) · CLI 검사 · 운영 인계

## 공간 산정과 범위

- 측정 당시 free **53.79GiB**, main7M 준비 기준 필요 **53.54GiB**: 통과. 여기에는 실측 데이터·SQLite·joint checkpoint,1.5배 여유·20GiB 운영 예비 공간·고정2GiB·추가 STOP100회 bundle을 포함한다.
- STOP fixture는2,119전이에 checkpoint3개를 만든다. 이를 그대로1M에 비례시키지 않고 실제 본 설정의 **1M당500번 commit**으로 bundle 비용을 분리했다. 원래 과대 추정 결과(preflight_v1)는 당시 보존했으나 후속 정리에서 삭제했다.
- 전체10M 제출 기록까지 보수적으로 보관할 예상 필요량은 **67.07GiB**로, 현 공간보다 **13.29GiB** 더 필요하다. 따라서 이번 READY의 범위는 expert1M·BC·PPO6M이다. archive3M 이전에 공간 확보·재검증이 필요하다.
- 여유가 기준과 가까우므로 실행기에서 각 단계 시작 전 디스크를 다시 검사한다. 학습 중에도 실제 사용량을 기록해야 한다. 기존 연구 파일 삭제나 Drive 이동은 하지 않았다.

[용량 원자료와 계산식](CAPACITY.json) · 실행 준비 증거

## 다음 단계

별도 지시 후 **새 전문가1M pool 수집 → 품질/고정 fitting view → 본 BC3seed → 본 PPO6run** 순서로 진행한다.
[실행 명령과 STOP/resume 설명](../../guides/KCITY_MAIN_EXECUTION.md)을 따른다. 현재 본 수집·본 학습 프로세스는 실행하지 않았다.

실제 artifact: `/home/heven/kcity_research_runs/KC-OPS-20261115-01`. 작은 보고서·해시만 저장소에 두고 모델·실제 State 자료·로컬 archive는 외부 실행 폴더에 보관했다. 이번 단계의 commit/push는 수행하지 않았다.
