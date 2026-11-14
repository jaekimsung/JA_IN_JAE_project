# KC-04: 공통 BC/PPO 정책·초기화·재개 계약

2026-11-14 후보 구현. [검사 결과](research_checks/KC-04-20261114-01/README.md) · [연구 현황](RESEARCH_STATUS.md).

**공통 정책과 전체 재개의 작은 검사를 완료했다. 본 비교 학습·전문가 데이터 수집은 아직 시작하지 않았다.** 검증용 모델·입력·optimizer 실행은 본 실험과 구분한다. `training_ready=false`, 연구 설정은 pilot 뒤 동결한다.

## 1. 공통 정책과 실제 파라미터 수

[KCityPolicy](../algorithms/kcity_policy.py)는 기존 HybridActorCritic을 바탕으로 만든 별도 K-CITY 정책이다. 종전 고속도로 신경망과 BCPolicy는 보존했다. 후보 설정은 [learning.json](../configs/kcity/v1/learning.json)과 코드 기본값이 일치하는지 검사한다. 이 파일은 KC-01의 pinned protocol을 수정하는 파일이 아니다.

```text
환경의 고정 스케일 73-D 관측 → 공유 trunk [256,256] ReLU
                                  ├ 가감속 평균 head + tanh
                                  ├ 차선 logits head(좌/유지/우)
                                  └ value head
별도 학습 파라미터 log_std: 초기 -0.5
```

| 항목 | 실제 개수/설정 |
|---|---|
| 전체 PPO 파라미터 | **86,022** |
| BC에서 업데이트하는 trunk+mean+lane 파라미터 | **85,764** |
| BC에서 고정하는 value head | 257 |
| BC에서 고정하는 log_std | 1 |
| 관측 전처리 | 환경이 출력한73-D를 그대로 입력. BC 전용 mean/std 재추정 없음 |

가감속은 Normal 원본을 sample하고 logprob를 계산한다. 원본은 범위를 넘을 수 있고, 환경이 별도로 clip한다. 차선은 categorical이며 index0/1/2가 명령+1/0/-1에 대응한다. BC의 전문가 가감속 label은 `[-1,1]`이어야 하며 범위 밖을 조용히 clip해 다른 정답으로 바꾸지 않는다.

## 2. 같은 차선 mask를 모든 경로에 사용

기하학적 mask는73-D의 차선 존재42/44,교차로 내부51,cooldown52에서 복원한다. 유지 명령은 항상 허용한다. 실제 환경 mask와 같음을 Runner가 매 step 확인한다. 추가 특권 교통 정보를 mask에 넣지 않는다.

- BC: 같은 mask의 categorical CE를 사용한다. masked 차선을 정답으로 준 label은 오류다.
- PPO sampling: masked logits를 제외한다. 원본 행동과 당시 mask를 rollout에 저장한다.
- PPO update: **저장 당시 mask**로 logprob를 다시 계산한다. 관측에서 복원한 mask와 다르면 거부한다. masked entropy·차선 변경 확률을 진단에 쓴다.
- 결정적 평가: 같은 masked categorical argmax를 쓴다. 존재하지 않는 차선이 logits 최댓값이어도 선택하지 않는다.

기존 buffer의6번째 positional done API는 유지한다. 새 K-CITY 수집에서는 `action_mask`를 반드시 저장한다. 이식·샘플링·재평가 검사에서 행동/logprob 차이가0임을 확인했다.

## 3. BC→PPO 초기화

[KCityBC / KCityPPO](../algorithms/kcity_training.py)가 같은 KCityPolicy를 사용한다.

BC loss는 `가감속 MSE + 차선 CE`이며 가중치는1:1 후보다. BC optimizer는 trunk/mean/lane만 포함하고 value head·log_std는 고정한다. 현재 검증에는 **합성 입력·합성 label과 [16,16] 모델**을 사용했다. 이를 전문가 데이터나 학습된 연구 B1로 부르지 않는다.

B3는 fresh PPO를 만든 뒤 BC의 trunk/mean/lane 전체 key만 엄격하게 복사한다. source/target의 policy config·shape·finite·고정 std를 검사한다. 기존 BCPolicy와 config가 다른 모델은 거부하며 `strict=False`를 사용하지 않는다.

B2/B3는 같은 PPO seed의 초기 value head 파라미터·log_std와 새 Adam 상태를 유지한다. BC optimizer를 B3로 넘기지 않는다. **공유 trunk가 바뀌므로 critic 출력까지 같아야 하는 것은 아니다.** 이 차이는 계획에서 정한 공유 표현 사전학습 효과에 포함한다. B1/B3의 같은 관측에 대한 결정적 행동은 동일해야 한다.

BC 학습 checkpoint는 optimizer·update 수·sampler RNG·호출자가 제공한 data/split/cursor 식별자를 함께 저장한다. `load_checkpoint(..., expected_data_id=...)`로 dataset identity를 대조할 수 있다. KC-05에서실제소량dataset reader·split/shard/BCforward 검사를연결했다([자료계약](KCITY_DATA_PIPELINE.md)). 검증loss기반best선택과연구학습CLI는후속이다. 이 단계에서 실제 전문가 checkpoint는 생성하지 않았다.

## 4. 전체 재개 방식

기존 `PPO.save/load`는 계속 weights-only다. 전체 재개는 **KCityRunner.save_checkpoint/load_checkpoint**를 사용한다. 네이티브 SumoKCityEnv 한 개와 전용 Runner의 제어 경계에서만 지원한다. generic PPO.learn의 로컬 상태나 외부 wrapper/vector env를 이 API로 복원한다고 주장하지 않는다.

체크포인트에는 다음이 포함된다.

- 정책·critic·Adam 상태,환경 전이/update/optimizer step 카운터,BC 초기화 출처.
- 소유권이 분리된 Torch 행동 sampler RNG·NumPy minibatch RNG. BC는 자신의 sampler RNG를 저장한다. 현재 구조에는 Dropout/RNN이 없고 Python 전역 RNG를 학습 난수로 사용하지 않는다.
- 부분 rollout의 obs/raw action/logprob/raw reward/value/next value/termination/truncation/당시 mask.
- 현재 observation·Episode return/길이·완료 Episode 수·다음 case cursor·고정3/3/4 case 순서.
- 현재 case/시드/제어 설정,현재 에피소드의 행동 이력,전체 교통 snapshot·신호·cooldown·lane 요청·종료/진행 속성,환경 RNG.
- run ID·policy/hyperparameter·protocol hash·실제 source SHA·Python/NumPy/Torch/platform/thread 설정,파일 목록/SHA256.

### SUMO XML 상태만으로 재개하지 않는 이유

이번 실제 비교에서 saveState/loadState 후 laneChangeMode가512→1621로 달라졌고,보완 후에도 일부 HV의 미래 속도·가속도가 달라졌다. [공식 SaveAndLoad 문서](https://sumo.dlr.de/docs/Simulation/SaveAndLoad.html)도 내부 거동 상태의 저장 한계를 안내한다. [TraCI loadState 문서](https://sumo.dlr.de/docs/TraCI/Change_Simulation_State.html)는 미리 읽지 않은 교통 입력 누락에도 주의를 요구한다. 이번에 본 차이의 모든 원인을 하나의 항목으로 단정하지 않는다.

따라서 현재 구현은 **`replay_current_episode_v1`**이다. 같은 case/시드로 reset·warmup한 후 저장한 현재 Episode 행동만 환경 API로 재실행한다. 이 과정에서 정책 sampling·optimizer·learner 전이 카운터를 증가시키지 않는다. 내부 거동·신호·TraCI 명령 상태를 재구성한 다음,저장 snapshot/관측/mask/카운터/제어 mode와 **정확히 일치할 때만** learner 상태를 복원한다. 값이 다르면 재개를 거부한다. 새 Episode로 실패를 지우거나 물리 조건을 바꾸지 않는다.

환경 기한300초와0.5초 결정 간격으로 현재 Episode 이력은 정상적으로 최대600개 결정이다. 더 짧게 끝난 Episode는 Runner가 다음 case로 옮긴 뒤 그 초기 상태/이력만 저장한다. 재개 비용은 현재 Episode 재실행+warmup이며 장기 학습 전체를 재실행하지 않는다. 실제로 저장된6개 결정을 재실행한 작은 비교에서 복원 약1.12초를 측정했다. 이 숫자를300초 Episode 전체나 다른 CPU/GPU의 비용으로 확대하지 않는다.

### 저장·불일치·적용 범위

새 경로에만 immutable checkpoint를 만든다. 임시 디렉터리에 기록·파일 fsync·SHA 목록 생성 후 rename하며,지원 OS에서는 디렉터리도 fsync한다. 기존 checkpoint를 덮어쓰지 않는다. 파일 추가/누락/변조,다른 run/config/seed/device/source/runtime이면 로드하지 않는다.

CPU·Linux·고정 버전·단일 learner에서 검사했다. GPU update의 재현성·성능,다중 worker checkpoint,강제 전원 장애,수백 초 전체 이력 재실행은 아직 검증 전이다. 외부에서 직접 TraCI로 상태를 바꾼 실행은 복원 범위 밖이다. 연구 작업에서는 Runner의 환경 API로만 제어한다. 동시에 여러 Python thread에서 optimizer update를 실행하는 구성도 검증하지 않았다.

## 5. 현재 실행할 수 있는 검사

저장소 루트에서 실행한다. 기존 검증용 격리 환경이며 전역 패키지는 변경하지 않았다. output/artifacts는 존재하지 않는 새 경로여야 한다.

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B -m unittest discover -s tests -p 'test_kcity*.py' -v
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/check_policy.py \
  --output /tmp/kcity-kc04-new-check \
  --artifacts /tmp/kcity-kc04-new-fixtures
```

두 번째 명령은 합성 BC 업데이트와 작은 SUMO/PPO 재개 비교를 수행한다. 작은 모델의 실제 optimizer 작업이 있으며 본 연구 학습은 아니다. fixture checkpoint를 BC source나 본학습 초기값으로 재사용하지 않는다.

현재 검증용 checkpoint/trace 위치는 [실행 결과](research_checks/KC-04-20261114-01/README.md)에 있다. Git에는 코드/설정/작은 근거만 정리하며 이번에 Drive/GitHub 업로드는 하지 않았다.

## 6. 이후 연결

KCityRunner는 전이를 수집하고 부분 rollout을 update한 후 저장할 수 있다. `run_until(target)`은 절대 전이 예산을 넘기지 않으며,현재 protocol의 `training.enabled=false`와 미동결 상태에서는 본 연구 실행을 거부한다. `fixture=True`는 contract_check namespace의 최대32전이 검증만 허용한다. 재개 시 이미 모은 전이를 다시 수량에 넣지 않는다.

다음 KC-05에서 관측 정렬 전문가·writer/loader·data/split ID를 연결한다. KC-06에서 실제 교통 상호작용·보상·GPU/처리량·저장비용·장기 checkpoint/STOP·정기 dev 평가를 pilot하고 최종 설정을 동결한다. 지금은 연구용 학습 CLI·best 선택·주기 checkpoint/backup·완전한 launch preflight가 준비됐다고 표시하지 않는다.
