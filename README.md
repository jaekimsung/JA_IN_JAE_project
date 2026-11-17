# K-CITY 자율주행 의사결정 프로젝트

**자율주행 실험도시 K-CITY를 SUMO로 구현하고, 일반 차량·교통신호와 상호작용하며 목적지까지 주행하는 자율주행 차량(AV) 의사결정 정책을 학습·평가하는 프로젝트입니다.**

연구 주제는 **K-CITY 복합 교통 환경에서 전문가 사전학습의 효과와 한계 분석**입니다. 같은 환경에서 다음 네 가지를 비교합니다.
- 규칙 전문가(B0)
- 행동 모방(BC, B1)
- 사전 데이터 없이 학습한 온라인 SAC(B2)
- 전문가 데이터를 사전 데이터로 쓰는 RLPD(B3)

![K-CITY SUMO 도로와 가상 건물·가로수](maps/kcity/reports/scenery_detail.png)

*SUMO 화면. 건물·나무·녹지는 시각화용 가상 배치입니다.*

## 개요

```text
K-CITY 도로·신호 구현 → 일반 차량 교통 → AV 환경(관측·행동·보상) → 전문가 데이터 → BC·RLPD 학습 → 평가·영상·데이터셋
```

| 구성 | 내용 | 문서 |
|---|---|---|
| 도로·교통 | OpenDRIVE 기반 K-CITY 도로망(Edge 176, 차선 198), 수요 감응 신호 14곳, 정지 규칙 2곳, HV 4종(Krauss·IDM·EIDM·ACC) 600대/h | [ENVIRONMENT](docs/ENVIRONMENT.md), [맵](maps/kcity/README.md) |
| 주행 과제 | A 신호 정지·재출발, B 필수 차선 변경, C 복합(차선 변경 + 연속 신호 4곳), 제한 300초 | [ENVIRONMENT](docs/ENVIRONMENT.md#주행-과제) |
| AV 의사결정 | 0.5초마다 73차원 관측 → [가속, 차선 변경], 진행·도착·충돌·적색 진입 보상 | [ENVIRONMENT](docs/ENVIRONMENT.md#관측-73차원--1-1) |
| 학습 | tanh-Gaussian actor(256×256) + LayerNorm critic 10개, RLPD(B3)·온라인 SAC(B2) 3 seed × 300k 전이, BC(B1) 20k update | [ALGORITHMS](docs/ALGORITHMS.md) |
| 데이터 | POMDP 전이 + SUMO 전체 State, JSONL·NPZ shard, 병렬 수집, 목표 10^7 전이 이상 | [DATASET](docs/DATASET.md) |
| 평가 | dev/final 고정 사례 패널, 수요 1.0·1.5·2.0배, 충돌률·완주율·규칙 준수 완주·교통 노출 | [EXPERIMENT](docs/EXPERIMENT.md) |

## 저장소 구성

```text
.
├── kcity/            # 코드
│   ├── env/          #   실행환경: Gym 환경·73D 관측·경로·시나리오·환경 계약·SUMO 헬퍼
│   ├── policy/       #   정책·알고리즘: actor·critic ensemble·RLPD·BC 학습기·규칙 전문가 B0·checkpoint
│   ├── training/     #   학습 코드: BC run·RL run·dev 평가 곡선·실험 설정·실행 폴더/STOP 관리
│   ├── data/         #   데이터: 전문가·정책 수집, 사례 계획, 병렬 pool, shard 저장/검증, RL 전이 기록, 사전 데이터·replay buffer
│   └── evaluation/   #   평가: Episode 지표·HV 노출·사례 패널 평가
├── runner/           # 실행: collect · train_bc · train_rl · evaluate · record_video · export_hf · view_kcity
├── configs/kcity/    # experiment.json(실험 설정), v1/(환경 계약), panels/(dev·final 평가 사례)
├── maps/             # 맵: kcity/(SUMO 맵·경로·신호·조경, 원본 자료, 검증 보고서), tools/(맵 생성·검증 도구)
├── tests/            # 회귀 검사
└── docs/             # 설명 문서 (docs/README.md)
```

`kcity/` 안의 패키지는 한 방향으로만 import합니다.
- `env`는 다른 패키지를 쓰지 않습니다.
- `evaluation`·`policy`는 `env`를 씁니다.
- `data`는 `env`·`evaluation`·`policy`(규칙 전문가)를 씁니다.
- `training`은 `env`·`policy`·`data`·`evaluation`을 씁니다.
- `runner/`는 전부를 씁니다.

모듈을 import하는 것만으로는 SUMO가 실행되지 않으며, SUMO는 `SumoKCityEnv.reset()`을 호출할 때 시작됩니다.

## 실행

SUMO **1.28.0**, Python 3.10 이상, NumPy, PyTorch, Gymnasium이 필요합니다. 자세한 옵션은 [RUNNING](docs/RUNNING.md)에 있습니다.

```bash
python runner/view_kcity.py                                              # 맵·교통 데모 (GUI)
python runner/collect.py --output runs/expert --workers 8                # 전문가 데이터 (병렬)
python runner/train_bc.py views --pool runs/expert --output runs/bc_views
python runner/train_bc.py train --views runs/bc_views --seed 11 --output runs/bc_seed11
python runner/train_rl.py --method B2 --seed 11 --output runs/B2_seed11
python runner/train_rl.py --method B3 --seed 11 --prior runs/expert --output runs/B3_seed11
python runner/collect.py --output runs/archive_B3_seed11 --workers 8 --policy <bundle>   # 최종 정책 데이터
python runner/evaluate.py --policy <bundle 또는 expert> --panel final --output runs/eval/B3_seed11
python runner/record_video.py --policy <bundle 또는 expert> --scenario C --video --once --output runs/video/C
python runner/export_hf.py --dataset runs/expert --dataset runs/B3_seed11/transitions --output runs/hf_export
python -m unittest discover -s tests                                     # 회귀 검사
```

장기 실행은 `<output>/STOP` 파일로 안전하게 멈추고, 같은 명령에 `--resume`을 붙여 이어갑니다.

## 맵 데모와 재생성

`python runner/view_kcity.py`는 빨간 데모 차량(SUMO IDM, 학습 정책 아님)이 순환 경로를 돌고 일반 차량이 계속 투입되는 화면을 띄웁니다. 주요 옵션은 다음과 같습니다.
- `--aerial`: 항공사진 배경
- `--nogui --seconds 3600`: 화면 없이 연속 주행 검사
- `--baseline`: 177대 유한 교통 시나리오
- `--netedit`: 도로 편집기로 열기

```bash
python -m pip install -r maps/tools/requirements.txt
python maps/tools/build.py
python maps/tools/validate_signals.py
python maps/tools/validate.py --seeds 0 1 2
python maps/tools/lane_usage.py
```

신호 검증(기본·2배·3배 투입과 무작위 출발·도착, 각 3 seed)에서 **2,124/2,124대가 도착했고 충돌·텔레포트는 0건**이었습니다.

| 문서 | 내용 |
|---|---|
| [K-CITY 맵 안내](maps/kcity/README.md) | 실행, 구조, 구현 범위와 재생성 절차 |
| [신호 설계 보고서](maps/kcity/reports/SIGNAL_DESIGN.md) | 신호 배치 근거, 가정, 운영 정책 |
| [차선 정리 기록](maps/kcity/reports/LANE_PRUNING.md) | 제거한 차선과 회전 연결의 선정 근거 |
| [초기 구현 보고서](maps/kcity/reports/IMPLEMENTATION_REPORT.md) | 변환 범위, 원본과의 차이 |

## 자료 출처와 가정

- **도로 형상과 연결:** **CARLA K-CITY OpenDRIVE**를 기본 자료로 썼습니다.
- **도로 비교와 신호·정지 위치 후보:** **MORAI MGEO**를 썼습니다.
- **배경과 공간 비교:** **JJ 항공사진**을 썼습니다.

원본 위치·역할·해시는 [소스 매니페스트](maps/kcity/source/manifest.json)에 있습니다.

실제 K-CITY의 신호 현시표와 실측 교통량은 확보하지 못했습니다. 그래서 신호 주기·제어 방식·차량 투입은 교통 흐름 검증을 위해 설계한 가정입니다. 가상 건물과 나무는 충돌 대상이 아닌 시각화 요소입니다.

항공사진의 출처는 **Esri, Vantor, Earthstar Geographics, and the GIS User Community**이고, MGEO 메타데이터에는 `license: MORAI`, `data_source: 웨이즈원`이 명시되어 있습니다. 자료별 사용 범위는 [맵 문서](maps/kcity/README.md#출처와-사용-범위)에 있습니다.

## 수업 자료

- [프로젝트 소개](docs/course/0_Project_Introduction.md)
- SUMO 설치: [Windows](docs/course/1_SUMO_Windows_Setup.md) · [macOS Apple Silicon](docs/course/1_SUMO_macOS_AppleSilicon_Setup.md)
- [도로 환경과 POMDP 구조](docs/course/2_Road_Environment_Construction.md)
- [BC 학습](docs/course/3_Model_Training_BC.md) · [강화학습](docs/course/4_Model_Training_RL.md)
- [프로젝트 준비](docs/course/5_Project_Preparation.md) · [평가 기준](docs/course/6_Project_Evaluation.md) · [컨설팅](docs/course/7_Project_Consulting.md)
