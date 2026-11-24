# K-CITY 밀집 교통 실험

첫 교차로에서 우선차량 두 대를 먼저 보내고 합류하는 실험의 설정과 재생 방법은 [v2.1 안내](../v2_1/README.md)에 있다.

`pilot.json`은 seed 11 파일럿, `experiment.json`은 본 실험 설정이다. 수집·학습·평가 명령에서 `--experiment`로 파일을 지정한다. 두 설정은 같은 도로 환경과 dev 패널을 사용한다. 파일럿 데이터의 사례 인덱스는 10,000,000부터 시작한다.

| 과제 | 초기 조건과 교통 흐름 |
|---|---|
| A 연속 신호 | 배경 교통이 들어오기 전에 경로상 네 감응식 신호의 시작 녹색 현시를 시드별로 정한다. 60초 워밍업 후 네 교차 접근로에 교통을 공급한다. 황색·전적색 시간은 맵의 신호 프로그램을 따른다. |
| B 필수 차선 변경 | 자차는 합류 구간의 30 m 지점에서 출발한다. 이 구간의 통과 교통은 배치 차량 세 대와 후속 차군이 담당한다. SUMO에서 목표 차로의 움직이는 앞·뒤 차량을 확인한 시점을 첫 관측으로 삼는다. |
| C 비신호 양보 | 첫 합류로의 우선차량은 이미 이동 중이다. 후속 차량은 작은 차군과 긴 간격을 번갈아 형성한다. B0는 관측한 차량 속도와 교차로까지의 거리로 통과 시간을 추정해 접근 속도를 조절한다. |

관측 `KC-OBS63-v2`는 63차원이다. 교차로 차량 세 칸에는 교차로 내부 차량을 먼저 넣고, 이어서 접근 중인 차량을 예상 도착 시간순으로 넣는다. 같은 접근로에서 출발해 교차로 안에서 갈라진 차량도 보인다. 양보 위반 판정에는 기존의 3초 기준을 사용한다.

## 파일럿 입력 준비

저장소 루트에서 SUMO 1.28.0과 프로젝트 Python 환경을 사용한다.

```bash
python -B runner/check_scenarios.py --protocol configs/kcity/v2/protocol.json \
  --start-index 1000 --cases-per-scenario 30 --workers 8 --output outputs/dense_v2_preflight/independent_audit.json

python -B runner/collect.py --experiment configs/kcity/v2/pilot.json \
  --output runs/dense_v2_pilot/expert --workers 6 --report-every 10

python -B runner/train_bc.py views --experiment configs/kcity/v2/pilot.json \
  --pool runs/dense_v2_pilot/expert --output runs/dense_v2_pilot/bc_views
```

BC 학습 표본은 완주한 에피소드에서 비복원 추출한다. 기본 가중치는 1, 차로 끝·양보·신호 대응 구간은 √6, 실제 전문가 차선변경 명령은 6이다. 검증 표본은 완주한 검증 에피소드에서 균일하게 추출한다. RLPD prior는 파일럿 풀의 expert_train 분할에서 8,000개 전이를 읽는다.

## 준비된 입력으로 파일럿 학습

```bash
python -B runner/train_bc.py train --experiment configs/kcity/v2/pilot.json --seed 11 \
  --views runs/dense_v2_pilot/bc_views --output runs/dense_v2_pilot/B1_seed11

python -B runner/train_rl.py --experiment configs/kcity/v2/pilot.json --method B2 --seed 11 \
  --output runs/dense_v2_pilot/B2_seed11 --report-every 10

python -B runner/train_rl.py --experiment configs/kcity/v2/pilot.json --method B3 --seed 11 \
  --prior runs/dense_v2_pilot/expert --output runs/dense_v2_pilot/B3_seed11 --report-every 10
```

파일럿은 BC 2,000 업데이트, SAC·RLPD 각각 환경 전이 30,000개다. 본 실험을 진행할 때는 v2의 `experiment.json`과 새 출력 디렉터리를 사용해 전문가 데이터를 수집한다.
