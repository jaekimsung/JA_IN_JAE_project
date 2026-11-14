# K-CITY Gym 환경 사용 안내 — KC-02

현재는 KC-04의 `KC-ENV-v3-kc04-candidate`로 현재 Episode 행동 이력과 replay 재개를 추가했다([재개 계약](KCITY_POLICY_AND_RESUME.md)). 최초 구현 ID: `KC-ENV-v1-kc02-candidate`. KC-03에서 `KC-ENV-v2-kc03-candidate`로 변경했으며 substep 측정·동시 사건 보존과 route_length를 추가했다. [변경/평가 계약](KCITY_EVALUATION.md). [검증 결과](research_checks/KC-02-20261114-01/README.md) · [연구 현황](RESEARCH_STATUS.md).

KC-05에서는 [B0·수집/검사 CLI](KCITY_DATA_PIPELINE.md)까지 작은 실제 자료로 확인했다. 연구 학습 실행기는 다음 단계다. 독립된 [SumoKCityEnv](../env/kcity_env.py)를 추가했다. A/B/C 유한 경로, 배경 교통, 73-D 관측, 가속도/차선 요청, 사건·종료 처리를 작은 실행에서 검사했다. **학습 실행기·전문가·데이터 수집기는 아직 연결하지 않았다.** 기존 고속도로 예제와 `view_kcity.py`는 그대로다.

## 실행 환경과 재검사

저장소 루트에서 SUMO **1.28.0**, Python 3.10+, NumPy, Gymnasium이 필요하다. 이번에는 기존 격리 환경의 Gymnasium 1.2.3을 사용했다. 전역 패키지는 변경하지 않았다. SUMO tools는 기존 `sumo_library()`가 찾는다.

```bash
# 이 PC에서 검증한 Python. 다른 PC에서는 해당 의존성을 갖춘 Python으로 바꾼다.
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B -m unittest discover -s tests -p 'test_kcity*.py' -v

# 출력 디렉터리는 존재하지 않는 새 경로를 지정한다.
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/check_env.py --output /tmp/kcity-kc02-new-check
```

두 번째 명령은 A/B/C × 배경 교통 유무, 총 6회만 수행한다. 경로상 필요한 차선 변경과 일정 가속을 요청하는 **공학용 스크립트**다. 특권 경로 정보를 이용하므로 연구의 B0 전문가나 학습 AV 성능 자료로 집계하지 않는다. 고정 seed42를 사용하며 학습 업데이트는 0이다.

## 최소 사용 예

```python
from env.kcity_env import SumoKCityEnv

env = SumoKCityEnv(scenario_id="A", background=True)
try:
    obs, info = env.reset(seed=42)
    for _ in range(10):
        obs, reward, terminated, truncated, info = env.step([0.0, 0.0])
        if terminated or truncated:
            break
finally:
    env.close()
```

`reset(options=...)`는 `scenario_id`, `namespace`, `case_index`, `demand_multiplier`만 허용한다. 기본 namespace는 `contract_check`다. 명시한 `case_index`가 seed보다 우선하며, 없으면 seed를 case index로 사용한다. seed도 없으면 Gym의 환경별 RNG에서 index를 뽑는다. 연구 패널에서는 명시적인 case manifest를 사용해야 한다. 서로 다른 method/worker 순서가 같은 case의 환경 seed를 바꾸지 않는다.

연결마다 고유 TraCI label을 사용하며 모든 조회/제어는 해당 connection으로 수행한다. `reset`은 이전 연결을 닫고 새 SUMO를 만든다. `close`는 반복 호출할 수 있다. `artifact_dir`을 주면 그 아래 고유 실행 디렉터리에 CASE·route XML·SUMO 로그를 남기고, 생략하면 임시 디렉터리를 종료 시 정리한다. `gui=True`로 SUMO GUI를 선택할 수 있지만 이번 검증은 headless였으며 GUI 렌더 검사는 생략했다.

`debug_warmup_s`, `debug_episode_limit_s`, `background=False`는 검사 변형이다. case의 `runtime_variant`와 UID에 반영되며 본 연구 기본 조건과 합산하지 않는다. warmup/기한은 0.1초 단위여야 한다.

## 관측·행동·기록 계약

- 관측: `float32[73]`, 범위 `[-1,1]`. [데이터 명세의 index표](DATA_COLLECTION_SPEC.md)와 [관측 구현](../env/kcity_observation.py)을 연결한다. 고정 거리·속도 척도와 clip을 사용한다. 아직 통계 기반 정규화나 센서 모델은 없다.
- 행동: `[정규화 가속도, 차선 요청]`. 유한 2-vector 원본을 기록한 후 `[-1,1]`로 clip한다. 양의 가속도는 최대 +2, 음은 -4.5 m/s²로 변환한다. 두 번째 값은 ≥0.5 왼쪽, ≤-0.5 오른쪽, 그 사이는 유지다. 최종 hybrid 정책의 categorical 출력 adapter는 KC-04에서 연결한다.
- 정상 step: `setAcceleration` 요청 후 0.1초 × 5회, 총 0.5초를 실행한다. 사건/기한 발생 시 1~5회에서 끝나며 실제 `control_dt_s`를 기록한다. speedMode31/laneChangeMode512, 속도 상한8.33 m/s를 사용한다.
- 차선 mask 순서: `[왼쪽, 유지, 오른쪽]`. 차선 부재·내부 교차로·cooldown은 요청을 거부하고 이유를 남긴다. API 발행 `lane_change_applied`와 실제 이동 `lane_change_executed`는 다르다. SUMO 안전 조정 때문에 요청 가속도와 실측 가속도도 다를 수 있다. 개입의 상세 원인은 `unknown`이며 추측해서 채우지 않는다.
- `info.state/next_state`: 전체 차량 절대 위치·속도·차선·경로, ego 정보, 모든 신호 상태, 교통 수량, route validity. `get_privileged_state()`와 별개로 actor는 73-D만 받는다. 특권 정보를 행동에 쓸지는 외부 controller의 책임이다.
- `get_detected_vehicles()`: 경로 corridor 내 차량 및 가까운 교차 접근 차량의 기록 후보. 가림·센서 오차를 모델링하지 않는다. 교차 접근 차량은 기록할 수 있으나 현재 actor의 별도 관측 슬롯은 없으므로 비신호 교차로 처리의 충분성을 pilot에서 검토해야 한다.
- 경로 진행도는 차선 길이 차이를 정규화한 고정 route 좌표다. 물리적 주행 거리 `ego_distance_m`와 구분한다. 내부 Lane과 짧은 Edge를 통과해도 route occurrence로 이어진다.

매 substep에서 ego 충돌·적색 진입·실제 차선 변경·도착·teleport·제거·경로 이탈을 추적한다. 신호 진입은 직전 신호와 route 연결 link index로 판정하며, 매핑이 모호하면 `classification_valid=false`로 남긴다. 이 검사를 최종 규칙 준수 평가기 전체로 간주하지 않는다.

## 종료와 보상 후보

도착·충돌·적색 진입·경로 이탈·teleport·제거·과제 기한은 `terminated=True`다. 과제 기한은 잔여시간이 관측에 포함된 유한 300초다. ego가 없거나 경로가 무효하면 0 관측을 반환하고 validity를 false로 기록한다. 따라서 0 관측을 실제 ego 측정치로 해석하면 안 된다.

외부 결정 횟수 제한이 필요하면 `KCityExternalTimeLimit(env, max_episode_steps=...)`를 사용한다. 과제 종료가 우선하며 그 외 외부 제한은 `truncated=True`, `end_reason=external_limit`과 유효한 현재 관측을 보존한다. 이를 학습에 연결하기 전에 **KC-03에서 bootstrap과 trace 경계를 각각 처리해야 한다**. KC-02 환경 추가만으로 해결되지는 않았으며, 후속 KC-03에서 shared buffer/PPO의 GAE 경계 수정을 검사했다.

현재 보상은 진행도/10 + 도착10 − 충돌20 − 적색 진입10 − 거부 요청0.02 − 실제 차선 변경0.01이다. `unjustified_wait=0`으로 비활성화했다. 신호 대기와 정당한 양보를 구분하는 검증된 판정기가 없기 때문이다. 이는 설계 보상의 부분 구현이며 pilot 전에 완성·동결해야 한다. 모든 출력의 `training_ready=false`는 유지한다.

73-D·배경 수요600 vph·보상·기한·제어값은 검사한 후보다. `configs/kcity/v1/protocol.json`의 KC-01 당시 `implemented=false`는 당시 계약 상태로 보존하며, 현재 구현 여부는 위 구현 ID와 결과 파일로 식별한다. 수집용 JSONL/NPZ writer와 연구 학습·평가 실행기는 후속 단계다. 공통 actor와 native Runner의 전체 checkpoint는 KC-04에서 후보 구현·작은 검사를 완료했다.
