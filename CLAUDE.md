# CLAUDE.md

K-CITY(SUMO) 자율주행 의사결정 연구: 규칙 전문가 B0, BC-only B1, PPO-only B2, BC 초기화 PPO B3를 비교한다. 구조와 문서 색인은 [README.md](README.md), [docs/README.md](docs/README.md)를 본다. 최신 상태는 [docs/research/RESEARCH_STATUS.md](docs/research/RESEARCH_STATUS.md)에 있다.

## 동결 guard (가장 중요)

- [configs/kcity/main_v1/FROZEN_PROTOCOL.json](configs/kcity/main_v1/FROZEN_PROTOCOL.json)은 `kcity/`·`rl/`·`tools/map`·`tools/checks`·`legacy/highway/env`의 주요 파일, `configs/kcity/v1/*.json`, `docs/specs/`의 ★계약 문서 3개를 **경로와 SHA로 고정**한다. `kcity.experiment.load_scientific()`이 이를 검사한다.
- 핀 파일을 수정하면 본 실행이 막힌다. 수정이 필요하면 [OPERATIONAL_COMPATIBILITY.json](configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json)에 등록한다(소스는 `extensions`, 계약 문서는 `documentation_revision.contracts`에 frozen/현재 SHA를 기록). 파일을 옮기는 경우에는 [tools/freeze/refreeze_layout.py](tools/freeze/refreeze_layout.py)로 재동결한다. 과학 필드(수치·보상·예산·패널)는 바꾸지 않는다.
- 운영 소스(`kcity/experiment.py`, `tools/main/main_experiment.py`, `kcity/data/{dataset,storage}.py`, 호환 기록)를 바꾸면 서버의 LAUNCH_READY가 무효가 된다. 이 경우 서버에서 `tools/main/preflight_main.py`를 다시 실행해야 한다.
- SHA는 LF 기준이다. `.gitattributes`가 LF 체크아웃을 강제하므로 CRLF로 저장하지 않는다.

## 실행

- 회귀 검사: `PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 python -B -m unittest discover -s tests`. 본 검증 환경은 Linux·SUMO 1.28.0이다. Windows에서는 SUMO 버전, `os.O_DIRECTORY`·`resource`, numpy↔torch 호환 문제로 일부 테스트가 원래 실패한다.
- 본 수집·학습은 원격 Linux 서버(`/home/heven/...`)에서 한다. 명령은 [docs/guides/KCITY_MAIN_EXECUTION.md](docs/guides/KCITY_MAIN_EXECUTION.md)에 있다. `--check-only`만 출력 없이 안전하게 실행된다.
- 맵 데모는 `python view_kcity.py`, 맵 재생성은 `tools/map/`을 쓴다.

## 연구 기록 규칙

- 단계별 검증은 `docs/research_checks/KC-<단계>-<YYYYMMDD>-<NN>/`에 README·FINAL_CHECKS.json·SUMMARY.json으로 남긴다. 현황(STATUS)과 이력(HISTORY)도 함께 갱신한다.
- research_checks의 JSON과 서버 기록에 있는 옛 경로는 계보이므로 고치지 않는다. 대응은 [LAYOUT_MIGRATION.json](configs/kcity/main_v1/LAYOUT_MIGRATION.json)에서 찾는다.
- debug·pilot 자료와 모델은 본 데이터나 본 초기값으로 이월하지 않는다. 실패 사례를 빼거나 checkpoint를 다시 골라 결과를 좋게 만들지 않는다. 작은 차이로 방법이 우월하다고 선언하지 않는다.
- Drive 업로드와 원격 백업은 하지 않는다(사용자 금지). Git은 모델·원시 데이터 백업이 아니다.
- `legacy/highway/`는 수업 고속도로 예제다. 그 결과를 K-CITY 성과로 표기하지 않는다.
