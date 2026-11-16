# K-CITY 저장 용량 최적화: 선택1·2 적용

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../research/RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../research/RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
완료: **손실 없는 next 필드 복원 + 최신·직전·평가용 learner checkpoint 보관**. 사용자 승인한 두 항목만 적용했다.
본 데이터 수집/본 BC/PPO는0이며, 기존 pilot·이전 운영 검증 artifact를 삭제하거나 Drive에 업로드하지 않았다.

## 1. 중복 next 저장 축소

새 JSONL 물리 형식은 `KC-NEXT-REF-v1`이다. 같은 Episode 내 다음 행의 State/observation과 완전히 같은 값에만 그 행의 transition UID를 기록한다.
Episode 종료와 shard 마지막 행에는 next를 직접 저장한다. [read_shard](../../../data/dataset.py)가 한 행 lookahead로 **원래 모든 필드와 값**을 복원한다.
NPZ의 next_observation 등 필수 배열,전체 State,차량,정밀도,사건,timing은 그대로다. 과거 full-next 형식도 읽는다.

검증 자료의 실제 비교(구/신 실행별 attempt UUID만 제외):

| 자료 | 완전히 일치한 논리 전이 | JSONL gzip 기존 | 최적화 | 감소 |
|---|---:|---:|---:|---:|
| 전문가 | 2,137 | 3,670,963bytes | 3,323,201bytes | 9.47% |
| PPO | 2,119 | 4,720,308bytes | 3,988,573bytes | 15.50% |

이는 위 샘플의 JSONL 감소율이며,전체10M 파일에 동일 비율을 보장하지 않는다. [실측 비교](FORMAT_COMPARISON.json).

## 2. learner 보관 정책

PPO는 매 rollout에서 learner bundle을 먼저 별도 `transitions/checkpoints/`에 안전하게 저장·SHA 검증한다.
그 경로·SHA·누적 전이 수를 데이터 shard의 `environment/REFERENCE.json`에 기록한 뒤 shard를 atomic rename한다.
데이터가 확정됐으면 해당 latest learner도 이미 존재한다. 데이터 확정 전 crash의 고아 모델은 다음 명시적 writer 재개에서 이 출력 내부만 정리한다.

- 유지: 최신·직전 bundle 및50k 간격 평가 bundle. 초기 정책도 별도 보존한다.
- 최신/직전/평가 bundle을 검증한 뒤 불필요한 새 bundle만 제거한다. 손상된 최신본이 있으면 정리부터 하지 않는다.
- 데이터 shard·행·UID·기존 SHA는 수정하지 않는다. 보관 registry와 제거 기록은 외부 `CHECKPOINTS.json` / `CHECKPOINT_RETENTION.jsonl`에 남긴다.
- BC는 최신·직전 및 그 재개 상태가 필요로 하는 best를 유지한다. loss/val 곡선과 모델 SHA는 남긴다.
- 과거 pilot·검증 자료에 소급 적용하거나 기존 공개 결과를 덮어쓰지 않았다.

실제 GPU 기록 검증에서는 data2,119전이를 모두 유지하고 learner bundle3개 중 최신2개를 보관했다. T2,048의 새 검사용 모델1,081,482bytes만 정리했다.
이 실제 작은 정리량과 아래 **미래 전체 수집 용량 추정 감소**는 구분한다.

## 검증

- **126개 회귀 검사 통과**(74.051초). 원시 로그는 삭제했다. 추가 BC 보관 정책 검증7개도 통과했다(원시 로그 삭제).
- 실제 GPU long-history/부분 rollout save·fresh-process resume/후속 업데이트 일치. metadata/RNG/optimizer/trace/counters가 연속 실행과 같다.
- fresh GPU 기록은 T2,055·부분 buffer7에서 재개해 T2,119·rollout2·optimizer340,전체 데이터 DQ와 고유 전이 카운터 일치.
- codec 오류·Episode 경계·shard 경계·prune 이후 원본 읽기·최신 손상 시 정리 거부·모델만 확정된 crash·데이터 확정 후 manifest 갱신 전 crash를 검사했다.
- 이전 운영 검증의 전문가2,137/PPO2,119전이 full-next 데이터도 현재 reader에서 원래 data ID로 검증됐다.
- 검사용 learner/model은 본 학습으로 이월하지 않는다. 400결정 scripted replay prefix는 새 학습 전이로 세지 않는다.

[상세 GPU 결과](SUMMARY.json) · [진도](STATUS.json) · 실행/복구 인계.

## 용량 재산정

| 준비 범위 | 기존 필요량 | 최적화 후 필요량 |
|---|---:|---:|
| 전문가1M·PPO6M 및 BC | 53.54GiB | 45.91GiB |
| 제출용 전체10M 기록까지 | 67.07GiB | 55.71GiB |

필요량은 물리 파일 예상량에1.5배 headroom과20GiB 운영 예비 공간을 포함한 기준이다. 두 기준은 **변경하지 않았다**.
측정 당시 실제 free는 **54.38GiB**로,본7M 단계는 통과하지만 전체10M 기준에는 아직 **1.33GiB** 부족하다.
따라서 선택1·2는 적용 완료지만,전체10M 보관이 충분하다고 표시하지 않는다. 추가 공간 확보나 예비 기준 조정은 이번에 하지 않았다.
예상 필요량은 작은 실측 자료의 추정치이므로 실행 단계별 실제 사용량을 다시 확인한다.

[계산식·원자료](CAPACITY.json) · [새 실행 준비 기록](LAUNCH_READY.json).
[이전 운영 준비](../KC-OPS-20261115-01/README.md)의 숫자와 ready source는 역사 기록이며 새 명령에는 현재 ready 기록을 사용한다.

원시 검증 artifact·로컬 압축본은 후속 사용자 요청으로 삭제했다. 현재 요약·설정·준비 기록만 남아 있다.
이번 작업은 본 학습 착수나 Git commit/push까지 포함하지 않는다.
