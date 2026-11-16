# K-CITY SUMO map

K-CITY의 로컬 OpenDRIVE 원본을 변환한 **도로·교통 데모**다. JJ의 항공사진과 MORAI MGEO를 비교 자료로 사용한다. 학습한 AV 정책은 아직 연결하지 않았다.

## 바로 실행

프로젝트 루트에서 실행한다.

```bash
python view_kcity.py                 # 90도 회전, 차량 1배, 연속 주행 자동 시작
python view_kcity.py --aerial        # JJ 항공사진을 배경으로 표시
python view_kcity.py --netedit       # 도로·차선·Connection 편집기
python view_kcity.py --nogui --seconds 3600 # 화면 없이 1시간 검사
python view_kcity.py --baseline      # 기존 177대 유한 교통, ▶ 버튼으로 시작
```

빨간 `demo_ego`는 **SUMO IDM 차량**이다. PPO/BC 또는 HEVEN 주행 스택의 성능을 보여주는 차량이 아니다. 다른 차량은 Krauss / IDM / EIDM / ACC를 순환 배정한 합성 교통이다.

### 녹화용 연속 주행

기본 실행은 `tools/map/live_demo.py`의 TraCI 제어를 사용한다. 빨간 차량은 시작부터 1대만 투입하며, 기존 qualifier 경로 뒤에 실제 차선 연결을 따르는 귀환 경로를 붙인다. 경로 끝에 도달하기 전에 다음 순환 경로를 연장하므로 같은 차량 ID와 위치·속도를 유지한다. 신호나 앞차 때문에 정차할 수 있지만 목적지 도착으로 퇴장하지 않는다.

노란 차량은 기존 6초 간격 대신 **3초마다 최대 1대씩 계속 보충**한다. 주행 중인 차량과 투입 대기 차량을 합쳐 **60대**가 되면 추가 투입을 잠시 멈춘다. 차량 수는 출발·도착·혼잡에 따라 달라진다. GUI는 종료할 때까지 실행하며, `--seconds`를 지정하면 해당 시뮬레이션 시간에 종료한다. 차량 크기는 1배, 기본 화면 회전은 90도다. `/tmp`의 별도 설정 파일은 필요하지 않다.

```bash
python view_kcity.py --traffic-period 3 --max-traffic 60
python view_kcity.py --follow-ego     # 빨간 차량을 화면 중앙에서 추적
python view_kcity.py --follow-ego --zoom 300 # 추적하면서 더 넓게 보기
python view_kcity.py --angle 0         # 원래 방향
python view_kcity.py --delay 100       # 0.1초 스텝당 100ms 지연
python view_kcity.py --nogui --seconds 3600 --report /tmp/kcity-live.json
```

`sumo-gui -c maps/kcity/kcity.sumocfg`로 직접 실행하면 기존 유한 교통이 실행된다. **빨간 차량 연속 주행에는 `python view_kcity.py`를 사용**한다. `--baseline`과 `--reference`에서는 연속 주행 옵션을 적용하지 않는다. 아래의 177대 및 2,124대 검증 수치는 기존 유한 교통에 대한 결과다.

[연속 주행 검증](reports/live_demo_validation.json): seed 0/1/2에서 각각 시뮬레이션 1시간 동안 빨간 차량은 1회 생성, 도착·소실 0회, 약 18.0–18.4km 주행했다. 충돌·텔레포트는 0건, 빨간 차량의 최대 연속 대기는 32.1–41.5초였다. 초기 300초 이후 주변 차량은 평균 약 59대였다. 80대 상한을 시험했을 때는 일부 시드에서 충돌 또는 장시간 정체가 발생해 기본값을 60대로 낮췄다. 급제동 경고는 남아 있으며, 임의의 시드·무한 시간의 무정체를 보장하는 결과는 아니다.

`--follow-ego`는 빨간 차량이 투입되면 카메라 추적을 켠다. 기본 추적 줌은 500이며, `--zoom` 값이 클수록 더 확대된다. 차량 자체의 표시 배율은 1배로 유지한다. 실행 중에는 마우스 휠로 화면 확대율을 조정할 수 있다.

## 항공사진 없는 기본 화면

기본 실행에는 가상 건물 **30동**, 가로수·조경수 **808그루**, 녹지 **10곳**을 표시한다. 지붕·창·그림자, 녹지 산책로, 도로 가장자리 포장도 함께 배치했다. 실제 K-CITY 건물/수목 위치를 복원한 것은 아니다.

건물과 나무는 도로 가장자리에서 최소 3m, 신호 교차로 중심에서 13m 이상 이격했다. SUMO의 시각화용 polygon이므로 차량의 장애물·충돌 대상이 아니며, 도로·신호·차량 경로를 바꾸지 않는다. seed 0의 177대 주행 결과는 조경 표시 유무에 따라 모든 tripinfo 속성이 동일했다.

```bash
python view_kcity.py          # 건물·가로수·녹지 표시
python view_kcity.py --aerial # 항공사진 표시, 가상 조경 제외
python tools/map/scenery.py # 조경과 기본 화면 설정만 재생성
```

`build.py`에서도 조경을 자동 생성한다. 생성 의존성은 `shapely>=2,<3`이며 `tools/map/requirements.txt`에 포함했다. [배치 목록](reports/scenery.json), [비교 검증](reports/scenery_check/result.json), [SUMO polygon 문서](https://sumo.dlr.de/docs/Simulation/Shapes.html).

![항공사진 없는 도심 화면](reports/scenery_detail.png)

## 두 가지 맵

| 파일 | 용도 |
|---|---|
| `kcity.sumocfg` / `kcity.net.xml` | 검증한 데모: 감응식 신호 제어 교차로 14곳 + 전방향 정지 규칙 2곳 |
| `kcity.reference.sumocfg` / `kcity.reference.net.xml` | 원본을 SUMO로 변환한 비교용 맵. 신호·추가 정지 규칙 없음 |

`python view_kcity.py --reference`로 비교용 맵을 열 수 있다. 이 맵의 우선권도 SUMO의 추론 결과이며 실측 교통 규칙이 아니다. 데모의 통과 결과를 비교용 맵에 적용해서는 안 된다.

고립 도로 `69`는 사용자 요청으로 데모·비교용 맵 모두에서 제거했다. 현재 도로망은 하나의 연결 성분이다. `traffic_plan.json`으로 나머지 교통 경로·차량·투입 시각을 유지한다.

미사용 차선도 데모·비교용 맵에서 제거했다. 일반 차선 17개(최초 15개 + 재검사 2개), 미사용 회전 연결 53개가 대상이다. 내부 차선은 이후 신호화 재계산을 거쳐 346개이며, 현재 198개 일반 차선과 346개 내부 차선 모두 seed 0/1/2 중 적어도 한 번 통행했다. **현재 합성 교통 기준**이며 실제 K-CITY의 폐쇄·미사용 차선 판정이 아니다. [삭제 내역](reports/LANE_PRUNING.md)을 참고한다.

## 신호 운영

**14개 교차로에서 수요 감응식 신호**를 운영한다. 녹색 6–25초, 황색 3초, 전적색 3–7초이며 수요에 따라 다음 방향을 선택한다. 배치 12곳은 MGEO 신호/정지 노드 후보, 2곳은 복잡한 교차 흐름을 근거로 한 가정이다. 실제 K-CITY 현시표를 복원한 것은 아니다. [배치·운영·검증 보고서](reports/SIGNAL_DESIGN.md)를 참고한다.

![신호 배치](reports/signal_layout.png)

기본·2배·3배 투입과 별도 무작위 OD, 각 3개 시드에서 **2,124/2,124대 도착, 충돌·텔레포트 0**. 신호가 적었던 변경 전보다 기본 수요의 정지시간은 증가했다. 차량 총수가 유한한 시험이며 지속적 포화 수요를 보장하지 않는다.

## 구현 범위와 확인 결과

- 원본 OpenDRIVE: 일반 도로 84개 + 교차로 연결 도로 363개, 교차로 56개.
- SUMO: 일반 Edge 176개, 일반 Lane 198개. 원본 일반 도로 84개 중 고립 도로 `69`를 제외한 83개 포함.
- 북쪽 회전교차로의 SUMO roundabout 정의, 다차선 도로, 차선별 연결, 높이·곡선·도로 폭 정보.
- 모든 일반 Edge를 대상으로 하는 경로 176개 + CARLA qualifier 기반 데모 경로 1개.
- seed 0/1/2, 각 177대, 최대 1,800초의 종료 조건으로 검사: **531/531대 도착, 충돌·텔레포트 0**.
- 각 seed의 최대 동시 주행은 47 / 45 / 45대, 최대 연속 대기는 73.9 / 69.5 / 69.7초였다.
- 급제동 경고 7 / 9 / 6건은 남아 있다. 매끄러운 주행, 모든 부하에서의 안정성, 학습 AV의 Collision Rate를 검증한 결과는 아니다.

상세 한계·필요한 추가 자료는 [구현 보고서](reports/IMPLEMENTATION_REPORT.md)를 참고한다.

![도로망과 자료 비교](reports/overview.png)

## 재생성 및 검증

검증에 사용한 SUMO는 **1.28.0**이다. 실행만 할 때는 SUMO와 bundled Python tools가 있으면 되고, 재생성·분석은 아래 Python 의존성도 필요하다. Gymnasium이나 Torch는 이 맵 도구에서 사용하지 않는다.

```bash
# 필요할 때 별도 가상환경에 설치
python -m pip install -r tools/map/requirements.txt

python tools/map/build.py
python tools/map/audit_sources.py
python tools/map/render_signals.py
python tools/map/validate_signals.py
python tools/map/validate.py --seeds 0 1 2
python tools/map/lane_usage.py
```

`build.py`는 `source/manifest.json`의 SHA-256을 검사한 뒤 로컬 스냅샷을 입력으로 사용한다. 외부 ROS/CARLA/MORAI 프로세스를 시작하거나 원본 워크스페이스를 수정하지 않는다. 재생성하면 이 디렉터리의 생성된 맵·경로·설정·build 보고서를 갱신한다. 이전 검증 결과는 이전 네트워크 해시를 가리킬 수 있으므로 **재생성 후에는 검증도 다시 실행**한다.

## 파일

| 위치 | 내용 |
|---|---|
| `lane_pruning.json` | 차선·회전 연결 삭제 정책과 기준 해시 |
| `source/manifest.json` | 원본 위치·역할·해시, 제외한 JJ 기록의 사유 |
| `source/` | 변환 및 비교에 사용한 원본 스냅샷 |
| `kcity.rou.xml` | 177개 경로와 차량 투입 계획 |
| `kcity.junctions.nod.xml` | 초기 변환 정지 규칙. 최종 신호 적용 후 정지 규칙은 477/747 두 곳 |
| `signal_policy.json` / `kcity.signals.add.xml` | 신호 배치 정책 / 실제 로드할 감응식 운영 프로그램 |
| `kcity.add.xml` | CARLA의 시작·종료·정지·신호 위치 참고 POI; 정지선 강제 로직은 아님 |
| `kcity.aerial.gui.xml` | JJ 항공사진의 좌표 범위 기반 배경 |
| `reports/build.json` | 도로·연결·신호·경로 대응 및 빌드 명령 |
| `reports/source_audit.json` | 누락 연결 22개 분석, MGEO 비교, JJ GNSS 제외 근거 |
| `reports/validation_kcity.json` | 최종 3개 seed의 정량 검증 |
| `reports/kcity_seed*/` | 차량별 tripinfo, 경고, seed별 결과 |
| `reports/sumo_gui.png` | 실제 SUMO GUI 렌더링 확인 |
| `audit/` | 원본 내부 곡선 변환 경고, 초기 교통 시험과 수정 전 증거 |

## 출처와 사용 범위

OpenDRIVE 원본은 로컬 CARLA K-CITY 자료이며 도로 생성 방법은 [SUMO OpenDRIVE import](https://sumo.dlr.de/docs/Networks/Import/OpenDRIVE.html)를 따른다. 파일이 같다는 사실은 실제 도로의 최신 상태와 일치한다는 증거가 아니다.

JJ 항공사진 출처: **Esri, Vantor, Earthstar Geographics, and the GIS User Community** (`source/jj_kcity.json`). 항공사진은 위경도 범위를 투영한 참고 배경으로, 측량점에 맞춘 정밀 정합 결과가 아니다. MORAI MGEO에는 `license: MORAI`, `data_source: 웨이즈원`이 기록되어 있다. 이번 작업은 로컬 생성이며 외부 업로드·배포를 하지 않았다. 원본 및 파생 맵 공개 시에는 해당 자료의 사용·재배포 조건을 별도로 확인한다.
