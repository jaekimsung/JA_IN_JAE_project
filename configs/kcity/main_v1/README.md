# K-CITY 본 실험 설정과 운영 준비

갱신: 2026-11-16. [FROZEN_PROTOCOL.json](FROZEN_PROTOCOL.json)은 변경하지 않은 과학 설정이다. 동결 당시 training_enabled/launch_ready=false와 현재 운영 준비는 다른 상태다. 기존 KC01 loader에 그대로 넘기지 않는다.

본 collect/views/bc/ppo는 별도 운영 계층으로 연결했다. [현재 준비 기록](../../../docs/research_checks/KC-STORAGE-20261115-01/LAUNCH_READY.json) · [실행 안내](../../../docs/KCITY_MAIN_EXECUTION.md) · [현황](../../../docs/RESEARCH_STATUS.md). 본 수집/학습은0이다. final/archive/제출 통합은 후속이다.

cases_dev.json/cases_final.json은 동결 패널이며 final 실행 결과가 아니다. 환경·정책·학습 수식·73D·예산은 유지한다. JSONL 물리 next참조/모델보관과 문서개정의 호환 SHA는 [OPERATIONAL_COMPATIBILITY.json](OPERATIONAL_COMPATIBILITY.json)에 명시한다. 등록되지 않은 변경은 거부한다.

동결 당시 계약문서3개는 기존 Git commit ed12226에 보존돼 있다. 현재 문서는 새로운 SHA를 명시 등록했으며 새 백업 사본을 만들지 않았다. 준비 기록의 GPU 검증은 당시 source/time을 유지하고 이번 문서 guard 검증은 별도 기록한다. Drive 업로드 금지·로컬압축본 삭제 상태를 유지한다.
