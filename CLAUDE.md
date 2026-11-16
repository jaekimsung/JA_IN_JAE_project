# CLAUDE.md

K-CITY(SUMO) 자율주행 의사결정 연구입니다. 규칙 전문가 B0, BC-only B1, PPO-only B2, BC 초기화 PPO B3를 비교하고, 강의 최종 평가를 충족하는 것이 목표입니다. 평가 항목은 충돌률 < 5%, 완주, 충분한 HV, ≥10^7 데이터, 30초 이상 영상, 프로젝트 페이지입니다.

- 구조와 실행: [README.md](README.md)
- 설명 문서: [docs/README.md](docs/README.md)
- 평가 기준: [docs/course/6_Project_Evaluation.md](docs/course/6_Project_Evaluation.md)

## 수정 범위

- `maps/kcity/`(원자료·생성 맵·신호·보고서)와 `tools/map/`은 완성된 맵 구현입니다. 사용자 요청 없이 수정하지 않습니다.
- `configs/kcity/v1/protocol.json`·`scenarios.json`은 환경 계약입니다. 바꾸면 case_uid가 달라져 `configs/kcity/panels/`의 사례 패널이 무효가 됩니다. 바꿀 때는 패널을 다시 만들고 기존 결과와 섞지 않습니다.
- 데이터·checkpoint에 기록되는 식별자(`IMPLEMENTATION_ID`, `POLICY_ID`, `EXPERT_ID`, `SCHEMA_ID`, `METRIC_VERSION`)는 사례 ID와 데이터 호환에 쓰이므로 바꾸지 않습니다.
- 실험 설정은 [configs/kcity/experiment.json](configs/kcity/experiment.json) 하나입니다. 실행 폴더의 CONFIG.json에 이 설정의 digest가 들어가므로, 설정을 바꾸면 이전 run은 `--resume`으로 이어지지 않습니다(의도된 동작).
- 코드 버전은 run·bundle·dataset 메타데이터에 git commit으로 기록만 하고, 재개할 때 비교하지 않습니다.

## 실행

- **구성:** `env/`(실행환경) · `policy/`(정책·알고리즘) · `training/`(학습 루프·설정) · `data/`(수집·저장) · `evaluation/`(지표·평가) · `runner/`(실행).
- **import 방향:** env는 다른 패키지를 쓰지 않고, evaluation·policy → env, data → env·evaluation·policy, training → 나머지 전부입니다. data는 training을 import하지 않습니다.
- **진입점:** `runner/collect.py --workers N` → `runner/train_bc.py views|train` → `runner/train_ppo.py` → `runner/evaluate.py` → `runner/record_video.py` / `runner/export_hf.py`. 장기 실행은 `<output>/STOP` 후 `--resume`으로 이어갑니다.
- **회귀 검사:** `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 python -B -m unittest discover -s tests`. 검증 환경은 Linux·SUMO 1.28.0입니다.
- **처리량:** 본 수집·학습은 원격 Linux 서버에서 합니다. 처리량은 SUMO TraCI 조회가 지배합니다.

## 문서와 연구 규칙

- md 문서에는 프로젝트 설명(구조·환경·알고리즘·데이터·실험·실행 방법)만 둡니다. 작업·변경 이력은 쓰지 않고 git commit 메시지로 남깁니다.
- `docs/research_checks/`의 JSON은 예비 실험 원자료이므로 고치지 않습니다.
- debug·pilot 자료와 모델은 본 데이터나 본 초기값으로 이월하지 않습니다.
- 실패 사례를 빼거나 checkpoint를 다시 골라 결과를 좋게 만들지 않습니다. 작은 차이로 방법이 우월하다고 선언하지 않습니다.
- final 패널은 모델·설정 선택에 쓰지 않습니다.
- Drive 업로드와 원격 백업은 하지 않습니다. Hugging Face는 `runner/export_hf.py`로 폴더만 준비하고, 업로드는 사용자가 합니다.
