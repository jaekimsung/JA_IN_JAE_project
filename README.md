# K-CITY 자율주행 의사결정 프로젝트

**K-CITY를 도로 레퍼런스로 삼아, SUMO에서 교통 환경을 구축하고 자율주행 의사결정 모델을 학습·평가하는 프로젝트입니다.**

기존 「자율주행 인공지능 및 제어」 수업 예제 저장소를 **K-CITY 프로젝트 개발용 저장소로 재구성**했습니다. 앞으로 도로와 교통 시나리오, 자율주행 차량(AV) 환경, BC·PPO 학습, 주행 데이터 수집과 평가를 이 저장소에서 이어갑니다. 기존 예제 코드와 수업 자료는 개발 기반과 참고 자료로 유지합니다.

## 프로젝트 목표

K-CITY의 교차로·다차선 도로·회전교차로에서 일반 차량(HV)과 상호작용하며, 신호와 도로 연결을 따르고 목적지까지 주행하는 AV 의사결정 환경을 만드는 것이 목표입니다.

```text
K-CITY 도로 구축 → 교통 흐름 검증 → AV 환경 설계 → BC·PPO 학습 → 주행 평가·데이터 수집
```

자료에서 확인한 부분과 시뮬레이션을 위해 가정한 부분을 구분하고, 변경한 도로·신호·교통 조건에 맞춰 검증 결과를 남깁니다.

![K-CITY SUMO 도로와 가상 건물·가로수](maps/kcity/reports/scenery_detail.png)

*현재 SUMO 화면. 건물·나무·녹지는 시각화용 가상 배치이며 실제 시설 배치를 복원한 것은 아닙니다.*

## 현재 구현 상태

| 영역 | 상태 | 내용 |
|---|---|---|
| K-CITY 도로망 | 구현 | OpenDRIVE 기반 변환, 고립 도로 및 현재 합성 교통에서 미사용인 차선 제거 |
| 일반 차량 교통 | 구현 | 녹화용 지속 투입(3초 간격, 대기 포함 최대 60대) 및 기존 177대 검증 시나리오 |
| 교차로 운영 | 구현 | 수요 감응식 신호 14곳, 전방향 정지 규칙 2곳 |
| 주변 시각화 | 구현 | 가상 건물 30동, 나무 808그루, 녹지 10곳 및 선택형 항공사진 배경 |
| K-CITY용 AV 환경 | 예정 | 다중 도로 경로, 교차로·신호 관측, 행동·보상·종료 조건 설계 |
| K-CITY BC·PPO 학습 | 예정 | 기존 고속도로 예제를 K-CITY 환경에 연결하고 학습·비교 |
| AV 평가·데이터셋 | 예정 | 학습 정책의 완주·충돌·규칙 준수 평가 및 주행 데이터 수집 |

현재 도로망은 **일반 Edge 176개, 일반 차선 198개, 교차로 내부 차선 346개**입니다. 차선 제거는 시뮬레이션 통행 기록을 기준으로 했으며, 실제 K-CITY에서 사용하지 않는 차선을 판정한 결과는 아닙니다.

**빨간색 `demo_ego`는 SUMO IDM 차량입니다.** 아직 학습한 AV 정책을 연결하지 않았습니다. `train.py`, `test.py`, `collect_pomdp_data.py`는 기존 고속도로 환경을 사용하며, `data/`와 `results/`의 기존 예제 산출물도 K-CITY 학습 성과가 아닙니다.

## 바로 실행하기

프로젝트 루트에서 실행합니다. SUMO와 SUMO Python tools가 필요하며, 기존 검증에 사용한 SUMO 버전은 **1.28.0**입니다. 저장소에 생성된 맵이 포함되어 있어 화면을 확인할 때는 맵을 다시 만들 필요가 없습니다.

```bash
# SUMO 설치 확인
sumo --version

# 기본 화면: 90도 회전, 차량 1배, 빨간 차량 1대 순환 및 노란 차량 지속 투입
python view_kcity.py

# 항공사진을 배경으로 표시
python view_kcity.py --aerial

# GUI 없이 1시간 연속 주행 검사
python view_kcity.py --nogui --seconds 3600

# 기존 177대 유한 교통 검증 시나리오
python view_kcity.py --baseline

# 도로 편집기로 열기
python view_kcity.py --netedit
```

실행 옵션, 비교용 원본 맵, 세부 설정은 [K-CITY 맵 안내](maps/kcity/README.md)를 참고합니다.

기본 GUI는 자동으로 시작하며 창을 닫을 때까지 실행합니다. 빨간 차량은 귀환 경로를 포함한 순환 경로를 계속 연장해 도착으로 퇴장하지 않습니다. 신호와 주변 차량에 따른 정차는 유지합니다. 연속 주행은 위 Python 실행기를 사용해야 하며, `.sumocfg`를 SUMO에서 직접 열면 기존 유한 교통이 실행됩니다.

## 저장소 구성

```text
.
├── view_kcity.py           # K-CITY 도로·교통 데모 실행
├── maps/kcity/             # SUMO 맵, 경로, 신호, 조경, 원본 스냅샷, 검증 보고서
├── scripts/kcity/          # 맵 변환, 차선 정리, 신호·조경 생성, 검증 도구
├── env/                   # 기존 고속도로 환경 및 MDP 설정
├── algorithms/            # PPO·BC 알고리즘
├── utils/                 # 신경망, 버퍼, 평가·로깅 공통 코드
├── train.py               # 기존 고속도로 PPO 학습
├── train_bc.py            # 데이터셋 기반 BC 학습
├── test.py                # 기존 고속도로 정책 평가
├── collect_pomdp_data.py   # 기존 고속도로 주행 데이터 수집
├── view_road.py            # 기존 고속도로 예제 시각화
├── data/                  # 학습 데이터
├── results/               # 모델 및 실험 결과
└── project_materials/     # 수업 원자료와 프로젝트 요구사항
```

현재 K-CITY 맵 도구와 고속도로 학습 환경은 별도로 실행됩니다. 다음 개발 단계는 `env/`의 단일 도로 중심 구조를 K-CITY 경로·교차로 환경에 맞게 확장하는 것입니다.

## 앞으로 진행할 작업

1. **AV 주행 과제와 환경 구성** — 출발·도착 지점과 경로를 정의하고, 다중 Edge에서 차량 초기화·목적지 도착·경로 이탈을 처리합니다.
2. **관측·행동·보상 설계** — 주변 차량뿐 아니라 신호 상태, 정지선 거리, 교차로 진입 방향, 차선 연결을 관측에 반영합니다. 주행 진행도·충돌·교통 규칙·정체를 고려해 보상과 종료 조건을 정합니다.
3. **BC·PPO 학습과 비교** — K-CITY 전문가 주행 데이터를 수집하고 BC 기준 모델과 PPO 정책을 학습합니다. 학습 조건과 평가 시드·교통 조건을 기록합니다.
4. **평가와 산출물 정리** — 충돌률, 완주율, 신호 준수, 주행·대기시간을 평가하고 주행 영상과 데이터셋을 남깁니다. 수업의 기본 목표인 충돌률 5% 미만과 목적지 완주를 기준으로 구체적인 평가 시나리오를 확정합니다.

세부 요구사항은 [프로젝트 준비](project_materials/5_Project_Preparation.md)와 [최종 평가 기준](project_materials/6_Project_Evaluation.md)을 따릅니다.

## 맵 재생성과 검증

도로·신호·교통 조건을 수정할 때는 생성 파일과 검증 결과를 함께 갱신합니다. 아래 의존성 파일은 **K-CITY 맵 생성·분석 도구용**이며, 전체 학습 환경의 의존성을 설치하는 파일은 아닙니다.

```bash
python -m pip install -r scripts/kcity/requirements.txt
python scripts/kcity/build.py
python scripts/kcity/validate_signals.py
python scripts/kcity/validate.py --seeds 0 1 2
python scripts/kcity/lane_usage.py
```

재생성은 `maps/kcity/`의 생성된 맵·경로·설정을 갱신합니다. 원본 비교 분석과 그림 생성까지 포함한 전체 절차는 [맵 재생성 및 검증 안내](maps/kcity/README.md#재생성-및-검증)를 참고합니다.

저장된 신호 검증 결과에서는 기본·2배·3배 투입 및 별도 무작위 출발·도착 시나리오를 각각 3개 시드로 실행하여 **2,124/2,124대 도착, 충돌·텔레포트 0건**을 확인했습니다. 이는 유한한 합성 교통에 대한 결과입니다. 급제동 경고와 신호 대기는 남아 있으며, 지속적인 포화 수요나 학습 AV의 주행 성능을 검증한 결과는 아닙니다.

| 문서·결과 | 내용 |
|---|---|
| [K-CITY 맵 안내](maps/kcity/README.md) | 실행, 구조, 현재 구현 범위와 재생성 절차 |
| [신호 설계 보고서](maps/kcity/reports/SIGNAL_DESIGN.md) | 배치 근거, 가정, 운영 정책과 변경 전후 비교 |
| [신호 검증 결과](maps/kcity/reports/signals_validation/summary.json) | 교통 부하·시드별 검증 수치 |
| [기본 교통 검증 결과](maps/kcity/reports/validation_kcity.json) | 기본 시나리오의 도착·대기·경고 기록 |
| [차선 정리 기록](maps/kcity/reports/LANE_PRUNING.md) | 제거한 차선과 회전 연결의 선정 근거 |
| [초기 구현 보고서](maps/kcity/reports/IMPLEMENTATION_REPORT.md) | 최초 변환 범위, 원본 차이와 추가 자료 필요 사항 |

## 자료 출처와 가정

도로 형상과 연결의 기본 자료는 로컬 **CARLA K-CITY OpenDRIVE**입니다. **MORAI MGEO**는 도로 비교와 신호·정지 위치 후보 확인에, **JJ 항공사진**은 배경과 공간 비교에 사용했습니다. 원본 위치·역할·해시는 [소스 매니페스트](maps/kcity/source/manifest.json)에 기록되어 있습니다.

실제 K-CITY의 현시표와 실측 교통량을 확보한 상태는 아닙니다. 현재 신호 주기·제어 방식·차량 투입은 교통 흐름 검증을 위해 설계한 가정이며, 가상 건물과 나무는 차량의 충돌 대상이 아닌 시각화 요소입니다. 실제 교통 운영과의 일치도를 높이려면 현장 신호 운영 자료, 진입로별 교통량, 최신 차선 운영 정보가 추가로 필요합니다.

항공사진에는 **Esri, Vantor, Earthstar Geographics, and the GIS User Community** 출처가 기록되어 있으며, MGEO 메타데이터에는 `license: MORAI`, `data_source: 웨이즈원`이 명시되어 있습니다. 자료별 출처와 사용 범위는 [맵 문서](maps/kcity/README.md#출처와-사용-범위)에 정리되어 있습니다.

## 수업·개발 참고 자료

- [프로젝트 소개](project_materials/0_Project_Introduction.md)
- SUMO 설치: [Windows](project_materials/1_SUMO_Windows_Setup.md) · [macOS Apple Silicon](project_materials/1_SUMO_macOS_AppleSilicon_Setup.md)
- [도로 환경과 POMDP 구조](project_materials/2_Road_Environment_Construction.md)
- [BC 학습](project_materials/3_Model_Training_BC.md) · [강화학습](project_materials/4_Model_Training_RL.md)
- [프로젝트 준비](project_materials/5_Project_Preparation.md) · [평가 기준](project_materials/6_Project_Evaluation.md) · [컨설팅](project_materials/7_Project_Consulting.md)
