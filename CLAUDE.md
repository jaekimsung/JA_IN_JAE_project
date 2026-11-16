# CLAUDE.md

K-CITY(SUMO) 자율주행 의사결정 연구: 규칙 전문가 B0, BC-only B1, PPO-only B2, BC 초기화 PPO B3를 비교하고 강의 최종 평가(충돌률 < 5%, 완주, 충분한 HV, ≥10^7 데이터, 30초 이상 영상, 프로젝트 페이지)를 충족한다. 구조와 실행 순서는 [README.md](README.md), 문서 색인은 [docs/README.md](docs/README.md), 최신 상태는 [docs/research/RESEARCH_STATUS.md](docs/research/RESEARCH_STATUS.md), 평가 기준은 [docs/course/6_Project_Evaluation.md](docs/course/6_Project_Evaluation.md)에 있다.

## 수정 범위

- `maps/kcity/`(원자료·생성 맵·신호·보고서)와 `tools/map/`은 완성된 맵 구현이다. 사용자 요청 없이 수정하지 않는다.
- `configs/kcity/v1/protocol.json`·`scenarios.json`은 환경 계약이다. 바꾸면 case_uid가 달라져 `configs/kcity/panels/`의 사례 패널이 무효가 되므로, 바꿀 때는 패널을 다시 만들고 기존 결과와 섞지 않는다.
- 실험 설정은 [configs/kcity/experiment.json](configs/kcity/experiment.json) 하나다. 실행 폴더의 CONFIG.json에 이 설정의 digest가 들어가므로, 설정을 바꾸면 이전 run은 `--resume`으로 이어지지 않는다(의도된 동작).
- 코드 버전은 run·bundle·dataset 메타데이터에 git commit으로 기록만 하고, 재개할 때 비교하지 않는다.

## 실행

- 구성: `env/`(실행환경) · `policy/`(정책·알고리즘) · `training/`(학습 루프·설정) · `data/`(수집·저장) · `evaluation/`(지표·평가) · `runner/`(실행). 의존 방향은 env ← policy ← training, data → evaluation이며 data는 training을 import하지 않는다.
- 진입점: `runner/collect.py --workers N`(사례 주기 단위 병렬 수집, `<pool>/part-XX`) → `runner/train_bc.py views|train` → `runner/train_ppo.py` → `runner/evaluate.py` → `runner/record_video.py` / `runner/export_hf.py`. 장기 실행은 `<output>/STOP` 후 `--resume`.
- 회귀 검사: `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 python -B -m unittest discover -s tests`. 검증 환경은 Linux·SUMO 1.28.0이며, 다른 SUMO 버전에서는 SUMO를 띄우는 테스트가 버전 검사로 실패한다.
- 본 수집·학습은 원격 Linux 서버에서 한다. 처리량은 SUMO TraCI 조회가 지배한다(PPO/BC 연산은 1% 미만).
- 맵 데모는 `python runner/view_kcity.py`.

## 연구 기록 규칙

- 단계별 검증은 `docs/research_checks/KC-<단계>-<YYYYMMDD>-<NN>/`에 README·SUMMARY.json으로 남기고, 현황(STATUS)과 이력(HISTORY)을 함께 갱신한다.
- research_checks의 JSON과 서버 기록에 남은 옛 경로·동결 기록은 계보이므로 고치지 않는다. 당시 파일은 commit `fac8482`에 있다.
- debug·pilot 자료와 모델은 본 데이터나 본 초기값으로 이월하지 않는다. 실패 사례를 빼거나 checkpoint를 다시 골라 결과를 좋게 만들지 않는다. 작은 차이로 방법이 우월하다고 선언하지 않는다. final 패널은 모델·설정 선택에 쓰지 않는다.
- Drive 업로드와 원격 백업은 하지 않는다. Hugging Face는 `runner/export_hf.py`로 폴더만 준비하고 업로드는 사용자가 한다.
