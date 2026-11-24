# 첫 교차로 합류 시나리오 v2.1

C의 첫 교차로(759)에서 자차는 지선 `-77`의 5 m 지점에서 출발한다. 우선도로 `-21`에는 움직이는 선행 차량 두 대와 그 뒤를 따르는 차량을 배치한다. 선행 차량은 합류 지점까지의 거리와 차간 간격을 시드별로 다르게 뽑는다. 첫 관측을 반환할 때 정책의 교차로 관측 슬롯에 움직이는 우선차량이 두 대 이상 보이는지 검사한다.

1초 안에 관측 조건을 만족하면 기존과 같은 상태에서 시작한다. 일반 교통이 관측 슬롯을 차지해 조건을 만족하지 못하면 같은 시드와 배치를 재현하고, 배치 직후의 첫 관측부터 정책이 감속·정차·진입을 결정한다. reset 정보의 `priority_visibility_fallback`과 `initial_visible_moving_priority`로 이 경우와 실제 관측 대수를 확인할 수 있다.

선두 차군과 뒤차 사이에 첫 합류 기회가 생긴다. 그 뒤에는 작은 차군이 추가로 도착한다. 두 번째 교차로의 횡단 교통은 첫 합류 구간에 대기행렬이 곧바로 역류하는 일을 줄이도록 출발 시각을 조정했다. 감속·정차·합류는 각 정책이 결정한다. C에서는 우선차량이 교차로 안에 있거나 3초 이내로 접근하는 상황도 관측값으로 기록한다. 충돌 없이 합류하면 양보 위반 횟수와 감점은 0이며 주행을 계속한다.

## GUI로 사례 확인

저장소 루트에서 프로젝트 가상환경의 Python을 사용한다. 다음 명령은 검증용 사례 1004를 실시간 속도로 재생한다. 출력에는 새 경로를 지정한다.

```bash
python -B runner/record_video.py --protocol configs/kcity/v2_1/protocol.json \
  --namespace contract_check --scenario C --case-index 1004 --policy expert \
  --speed 1 --zoom 850 --once --output "$(mktemp -d)/C"
```

## 검증과 학습 입력

`runner/check_scenarios.py --scenarios C`의 결과 중 `entries`에서 `edge=-77`인 항목이 첫 교차로 진입이다. `priority_entered_before_ego`는 우선도로 접근과 교차로 내부에서 순서대로 관측된 고유 차량 수, `moving_priority`는 자차 진입 직전 50 m 안에서 접근 중인 우선차량 수다. `rolling_last_3s`는 직전 여섯 번의 정책 관측에서 자차 속도가 모두 0.5 m/s를 넘었는지 나타낸다.

파일럿은 `configs/kcity/v2_1/pilot.json`, 본 실험은 `configs/kcity/v2_1/experiment.json`을 사용한다. 파일럿 전문가 풀은 `runs/dense_v2_1_pilot/expert`, BC 입력은 `runs/dense_v2_1_pilot/bc_views`다. 환경 계약 해시에 맞춰 사례 패널과 학습 입력을 구분한다.
