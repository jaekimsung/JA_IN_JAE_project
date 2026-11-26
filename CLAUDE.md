# CLAUDE.md

K-CITY(SUMO) 자율주행 의사결정 연구입니다. 세 가지 주행 과제(연속 신호, 필수 차선 변경, 비신호 교차로 양보)에서 규칙 전문가 B0, BC B1, 온라인 SAC B2, RLPD B3를 비교하고, 강의 최종 평가를 충족하는 것이 목표입니다. 평가 항목은 충돌률 < 5%, 완주, 충분한 HV, ≥10^7 데이터, 30초 이상 영상, 프로젝트 페이지입니다.

- 구조와 실행: [README.md](README.md)
- 설명 문서: [docs/README.md](docs/README.md)
- 평가 기준: [docs/course/6_Project_Evaluation.md](docs/course/6_Project_Evaluation.md)

## 수정 범위

- `maps/kcity/`(원자료·생성 맵·신호·보고서)와 `maps/tools/`는 완성된 맵 구현입니다. 사용자 요청 없이 수정하지 않습니다.
- 최종 제출 기준은 v2.1입니다. `configs/kcity/v2_1/protocol.json`·`scenarios.json`은 환경 계약입니다. 바꾸면 case_uid가 달라져 같은 폴더의 사례 패널(`cases_dev.json`·`cases_final.json`)이 무효가 됩니다. 바꿀 때는 패널을 다시 만들고 기존 결과와 섞지 않습니다.
- 데이터·checkpoint에 기록되는 식별자(`IMPLEMENTATION_ID`, `OBSERVATION_ID`, `EXPERT_ID`, `SCHEMA_ID`, `METRIC_VERSION`)는 사례 ID와 데이터 호환에 쓰이므로 바꾸지 않습니다.
- 실험 설정은 [configs/kcity/v2_1/experiment.json](configs/kcity/v2_1/experiment.json)(파일럿은 `pilot.json`)입니다. 실행 폴더의 CONFIG.json에 이 설정의 digest가 들어가므로, 설정을 바꾸면 이전 run은 `--resume`으로 이어지지 않습니다(의도된 동작).
- 코드 버전은 run·bundle·dataset 메타데이터에 git commit으로 기록만 하고, 재개할 때 비교하지 않습니다.

## 과제 제약 (강의 FAQ)

- AV에 보조 규칙이나 도움 요소를 붙이지 않습니다. SUMO 안전 보정은 끄고(speedMode 6, laneChangeMode 0), 규칙·별도 모델로 시나리오를 고르거나 행동을 고치지 않습니다. 규칙 전문가 B0는 데이터 생성에만 쓰며, 학습 정책과 같은 관측만 봅니다(특권 정보 없음).
- 경로는 큰 틀(다음 회전 방향, 남은 거리)만 관측에 넣고, 어느 차선으로 가야 하는지 같은 차선 단위 안내는 넣지 않습니다.
- 보상 항은 꼭 필요한 것만 둡니다. 관측은 겹치거나 상수인 칸을 두지 않습니다.
- 데이터 열은 가능한 한 숫자로, 신호는 상태별로 차원을 나눠 저장합니다.

## 실행

- **구성:** 코드는 `kcity/` 아래 `env/`(실행환경) · `policy/`(정책·알고리즘) · `training/`(학습 루프·설정) · `data/`(수집·저장) · `evaluation/`(지표·평가)이고, 실행 진입점은 `runner/`입니다. 루트는 kcity·runner·configs·maps·tests·docs·outputs 7개이고, 결과(평가·학습 곡선·최종 모델·예비 실험 원자료)는 모두 `outputs/`에 둡니다. 로컬 대시보드는 `runner/dashboard/`입니다.
- **import 방향:** env는 다른 패키지를 쓰지 않고, evaluation·policy → env, data → env·evaluation·policy, training → 나머지 전부입니다. data는 training을 import하지 않습니다.
- **진입점:** `runner/collect.py --workers N` → `runner/train_bc.py views|train` → `runner/train_rl.py` → `runner/evaluate.py` → `runner/record_video.py` / `runner/export_hf.py`. 장기 실행은 `<output>/STOP` 후 `--resume`으로 이어갑니다.
- **회귀 검사:** `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 python -B -m unittest discover -s tests`. 검증 환경은 Linux·SUMO 1.28.0입니다.
- **처리량:** 본 수집·학습은 원격 Linux 서버에서 합니다. 처리량은 SUMO TraCI 조회가 지배합니다.

## 문서와 연구 규칙

- md 문서에는 프로젝트 설명(구조·환경·알고리즘·데이터·실험·실행 방법)만 둡니다. 작업·변경 이력은 쓰지 않고 git commit 메시지로 남깁니다.
- `outputs/`에는 방법(BC·SAC·RLPD)별·seed별 학습 결과 그래프와 최종 모델(`final_model/`)만 둡니다. `final_model/`은 SHA256으로 검증되므로 안의 파일을 고치지 않습니다.
- debug·pilot 자료와 모델은 본 데이터나 본 초기값으로 이월하지 않습니다.
- 실패 사례를 빼거나 checkpoint를 다시 골라 결과를 좋게 만들지 않습니다. 작은 차이로 방법이 우월하다고 선언하지 않습니다.
- final 패널은 모델·설정 선택에 쓰지 않습니다.
- Drive 업로드와 원격 백업은 하지 않습니다. Hugging Face는 `runner/export_hf.py`로 폴더만 준비하고, 업로드는 사용자가 합니다.
