# 문서 색인

처음 읽는다면 [연구 현황](research/RESEARCH_STATUS.md) → [연구 계획](research/RESEARCH_PLAN.md) → [본 실행 방법](guides/KCITY_MAIN_EXECUTION.md) 순서를 권장합니다.

## research/ — 연구 진행

| 문서 | 내용 |
|---|---|
| [RESEARCH_STATUS](research/RESEARCH_STATUS.md) | 최신 현황, 단계별 상태, 다음 순서 |
| [RESEARCH_HISTORY](research/RESEARCH_HISTORY.md) | 날짜별 실적 |
| [RESEARCH_PLAN](research/RESEARCH_PLAN.md) | 연구 질문·가설·비교 설계 |
| [EXPERIMENTS](research/EXPERIMENTS.md) | 실험·검사 인덱스 |
| [RESULTS_AND_CONSULTING](research/RESULTS_AND_CONSULTING.md) | 지표·그림·영상·컨설팅·제출 계획 |

## specs/ — 계약과 명세

실험 설정은 [experiment.json](../configs/kcity/experiment.json)에 있습니다. 아래 명세 안의 "동결·launch-record·preflight" 서술은 2026-11-16 코드 정리 전의 설계 기록이며, 현재 코드에는 그 장치가 없습니다.

| 문서 | 내용 |
|---|---|
| [DATA_COLLECTION_SPEC](specs/DATA_COLLECTION_SPEC.md) | 데이터 컬럼·73D 관측·JSONL/NPZ·품질 검사 |
| [KCITY_DATA_PIPELINE](specs/KCITY_DATA_PIPELINE.md) | 수집·저장·복구 사용 계약 |
| [KCITY_EVALUATION](specs/KCITY_EVALUATION.md) | 종료·GAE·평가 지표 계약 |
| [KCITY_POLICY_AND_RESUME](specs/KCITY_POLICY_AND_RESUME.md) | 공통 BC/PPO 정책·초기화·재개 계약 |
| [EXECUTION_PROTOCOL](specs/EXECUTION_PROTOCOL.md) | 수집·학습·평가 순서와 착수 gate |

## guides/ — 사용 안내

| 문서 | 내용 |
|---|---|
| [KCITY_ENV](guides/KCITY_ENV.md) | K-CITY Gym 환경 사용법 |
| [KCITY_MAIN_EXECUTION](guides/KCITY_MAIN_EXECUTION.md) | 수집·BC·PPO·평가·영상·HF 내보내기 실행법, STOP/재개 |
| [KCITY_PILOT](guides/KCITY_PILOT.md) | KC-06 pilot 결과 |

## 기타

- [research_checks/](research_checks/) — 단계별 검증 기록. `KC-<단계>-<YYYYMMDD>-<NN>/`에 README·FINAL_CHECKS.json·SUMMARY.json을 둡니다. 안의 JSON에 남은 옛 경로·동결 기록은 계보이므로 고치지 않습니다. 당시 파일은 commit [fac8482](https://github.com/jaekimsung/JA_IN_JAE_project/tree/fac8482)에 있습니다.
- [course/](course/0_Project_Introduction.md) — 수업 원자료와 발표·평가 기준.
- [prompts/](prompts/KCity_Codex_Research_Prompt.md) — 연구 진행용 에이전트 프롬프트.
