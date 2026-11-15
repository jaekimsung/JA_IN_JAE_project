# KC-04 — 공통 정책·BC 이식·전체 재개 검증

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
상태: **KC-04 후보 구현과 제한 검증 완료. 다음은 KC-05 전문가·수집기다.** 본 비교 학습,전문가 dataset,final 평가는 실행하지 않았다. 검증용 실제 optimizer 작업은 아래에 별도로 기록한다. `training_ready=false`.

## 구현 범위와 식별

- 시작: `2026-11-14T22:14:35.693990+09:00`. HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`,local branch `codex/kcity-kc01-20261114`. 기존 미완료 변경을 보존했다. PROVENANCE.
- 신규: [공통 masked policy](../../../algorithms/kcity_policy.py), [BC/PPO·Runner·checkpoint](../../../algorithms/kcity_training.py), [후보 설정](../../../configs/kcity/v1/learning.json), [회귀 검사](../../../tests/test_kcity_policy.py), [검사 CLI](../../../scripts/kcity/check_policy.py).
- 수정: shared buffer의 sampling mask 저장,shared PPO의 주입 정책·동일 mask 재평가·update 카운터,K-CITY 환경의 현재 Episode 행동 이력과 replay 재개. 변경 전3개 source는 `before/`에 보존했다. 종전 고속도로 BC/network/map/data/model과 KC-01 protocol은 변경하지 않았다.
- 실제 사용 계약·호환성과 한계: [KCITY_POLICY_AND_RESUME.md](../../KCITY_POLICY_AND_RESUME.md). 최종 source/파일 보존·문서 검사는 [FINAL_CHECKS.json](FINAL_CHECKS.json).
- 환경 ID `KC-ENV-v3-kc04-candidate`,정책 ID `KC-HYBRID73-v1-candidate`. 현재 config는 미동결 후보이며 본학습 enabled=false다. 이번 commit/push·Drive/GitHub 업로드는 없다.

## 검증 결과

| 항목 | 실제 결과 | 해석 |
|---|---|---|
| 전체 회귀 검사 | **80개 통과**,36.496초 | 당시 검사 요약(원시 로그 삭제),기존61+KC-04 신규19 |
| 표준 Gym 검사 | 통과 | JSON·로그,A/no background/warmup0/render 제외 |
| 기본 후보 모델 | **73→256→256**,ReLU,총**86,022 parameters** | 실제 module 집계,이 크기로 본학습한 것은 아님 |
| BC trainable | **85,764 parameters**,value head257·std1 고정 | 공유 trunk/mean/lane만 업데이트 |
| BC→PPO 행동 | 최대 결정적 행동 차이**0.0** | 같은 mask·고정 전처리·actor 전체 key 복사 |
| BC 불변 조건 | value head·log_std 불변,B2/B3 초기 head/std 일치,새 PPO optimizer 비어 있음 | critic 출력은 공유 trunk 변화로 달라질 수 있음 |
| logprob | sampling vs 동일 mask 재평가 차이**0.0** | masked lane 선택/잘못된 label/mask/legacy actor도 검사 |
| BC resume | 다음 sampler 선택·loss·weight·Adam 상태 일치 | 합성 입력 [16,16] 모델,실제 dataset split 검증 아님 |
| PPO resume | 부분 rollout·행동·reward/event/전체 교통 trace·최종 obs·weight·Adam·RNG/counters 일치 | 아래18전이 비교,CPU 단일 learner |
| 예산/차단 | 실제 작은 fixture에서4+3=7전이,본 연구 요청은 reset 전에 거부 | protocol 미동결/enabled=false 유지 |
| 불일치 거부 | immutable path,파일 SHA,run/config/seed/source/runtime/data ID 검사 | metadata와 raw checkpoint를 함께 확인 |

## 전체 재개 통합 비교

실행: `2026-11-14T22:30:03.819947+09:00`~`22:30:07.164462+09:00`. [SUMMARY](validation_v1/SUMMARY.json)·실행 로그.

별도 통합 검사는 **[16,16] 작은 모델**과 합성 BC label을 사용했다. BC를2회 update한 뒤 checkpoint를 저장하고,연속/복원 양쪽에서 다음1회를 실행했다. sampler 선택·loss·모델·Adam 상태가 같았다. source가 된3-update fixture도 별도 checkpoint로 식별했다. 이4회의 실제 BC optimizer 작업은 학습 성능 결과가 아니다.

PPO는 BC actor로 초기화한 작은 B3 fixture를 사용했다. namespace는contract_check,case_index0,C만 사용하는 명시적 검사 변형이다. 연구의 기본3/3/4 schedule이나 dev/final 평가가 아니다.

1. 4전이를 수집하고1 rollout update를 수행했다.
2. 2전이를 추가 수집해 **T6/U1,부분 rollout2행**을 저장했다.
3. 연속 분기에서12전이를 더 수집하고 update했다.
4. 새 agent/새 SUMO process에 T6/U1을 복원한 뒤 같은12전이와 update를 수행했다.

두 분기의 최종은 각각 **T18/U2/optimizer steps5**다. 부분 buffer를 포함한 update 전 training state,실행 trace,update 통계,최종 전체 training state가 정확히 일치했다. 이 비교를 위해 실제 실행한 PPO optimizer 작업은 prefix1+연속 suffix4+복원 suffix4=**9회**다. 두 분기에 걸친 수집 호출은30전이이며,같은 기준 궤적의 재실행을 새 연구 전이나 데이터셋으로 합산하지 않는다. 환경 복원에 재실행한6결정도 learner 카운터에 더하지 않았다. 복원 wall은 약**1.12초**였다.

위 optimizer 수는 **별도 통합 검사**의 계측값이다. 80개 회귀 검사 안에서도 작은 gradient/optimizer fixture를 수행했으며,이를 본실험의 학습 진도로 합산하지 않는다. `[256,256]` 모델은 크기/설정만 확인했고 연구용1M 비교 학습을 시작하지 않았다.

## SUMO 저장 방식에서 발견한 한계와 수정

- 최초 직접 saveState/loadState probe에서 ego laneChangeMode가512→1621로 돌아갔다. PROBE.json.
- 제어 mode 보완 후에도 angle round-trip의 작은 차이와 일부 HV의 미래 속도/가속도 차이가 남았다. [초기 snapshot 차이](RESUME_PROBE_DIFF.json)·[미래 상태 차이](RESUME_FUTURE_DIFF.json).
- [공식 SUMO 문서](https://sumo.dlr.de/docs/Simulation/SaveAndLoad.html)에도 내부 거동 상태의 저장 제약이 있다. 실측 차이의 모든 원인을 특정 driver 변수 하나로 단정하지 않았다. 혼합 HV 모델을 제거하거나 물리를 바꾸지 않았다.
- 최종 구현은 XML loadState 대신 **동일 case/seed reset + 현재 Episode의 저장 행동 재실행**을 사용한다. raw snapshot·obs·mask·카운터·mode가 정확히 일치하지 않으면 재개를 거부한다. 최종 검사는 허용 오차를 늘려 통과시킨 것이 아니다.
- 이 재실행은 환경 내부 상태를 재구성하는 비용이며 정책 sampling·optimizer·학습 전이는 추가하지 않는다. 과제의 유한300초 이력까지만 필요하다. 직접 TraCI 개입·다른 source/runtime·다른 device·외부 wrapper는 검증 범위 밖이다.

실패 로그도 보존했다. `TESTS.attempt01.log`는 bool tensor의 isin 지원 문제를 발견한17개 검사(6 errors),`attempt02`는 직접 SUMO load 방식의 미래 상태 차이(1 failure),`attempt03`은 replay로 바꾼17개 통과,최종`attempt04`는 추가 gate/예산 검사를 포함한80개 통과다. 실패한 초기 probe checkpoint는 연구 초기값으로 재사용하지 않는다.

## 검증 산출물 위치

통과한 fixture checkpoint/trace는 저장소 밖 아래 경로에 있다.

`/home/heven/kcity_research_runs/KC-04-20261114-01/validation_v1/`

- `bc_step2/`, `bc_source_step3/`: 합성 BC update·resume 확인용.
- `ppo_partial_T6_U1/`: 정책·Adam·소유 RNG·부분 rollout·Episode/case cursor·환경 이력.
- `ppo_control_T18_U2/`, `ppo_resumed_T18_U2/`: 최종 연속/복원 비교.
- `control.jsonl`, `resumed.jsonl`, `sumo_control/`, `sumo_resumed/`: 비교 trace와 SUMO 입력/로그.

총553,935 bytes이며 각 checkpoint에 파일 목록/SHA256이 있다. **전부 검증 fixture**이고 실제 전문가·연구 정책이 아니다. source/runtime·run ID가 맞아야 로드할 수 있다. 이번에 Drive/GitHub에 올리지 않았다.

## 다음 단계와 남은 한계

다음은 **KC-05: 관측 정렬 규칙 전문가·작은 수집기/loader·schema/shard 품질 검사**다. 이후에 실제 BC train/validation 자료·best 선택·연구용 train/eval CLI·주기 checkpoint/STOP/백업을 연결한다.

GPU에서의 update 재현성·처리량,다중 worker,긴 Episode 전체 replay 비용,강제 장애,교통 충분성·부당 대기/정지/양보 판정과 최종 수요/보상 동결은 KC-06 등의 추가 검증 사항이다. 기존 `PPO.save/load`는 weights-only이며 새 Runner API와 혼동하지 않는다. 작은 검사를 통과한 것으로 학습 효율 가설의 지지나 실제 도로 성능을 주장하지 않는다.

## 재검사

저장소 루트,새 경로로 실행한다.

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B -m unittest discover -s tests -p 'test_kcity*.py' -v
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/check_policy.py --output /tmp/kcity-kc04-new-check --artifacts /tmp/kcity-kc04-new-fixtures
```
