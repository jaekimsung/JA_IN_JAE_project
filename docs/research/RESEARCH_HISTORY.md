# K-CITY 연구 이력

갱신: 2026-11-16 · [현재 현황](RESEARCH_STATUS.md) · [실험 인덱스](EXPERIMENTS.md). 종료된 단계와 결정의 기록이다.

| 시점·ID | 당시 수행·결정 | 근거 |
|---|---|---|
| 11/01 맵·교통 | 일반차량 신호/데모검증, 학습AV성과 아님 | [신호집계](../../maps/kcity/reports/signals_validation/summary.json), [live집계](../../maps/kcity/reports/live_demo_validation.json) |
| 11/10 KC-AUDIT | seed43 finite177/177·live소실0, 기존BC이식/seed/GAE문제 확인 | [요약](../research_checks/KC-AUDIT-20261110-01/evidence/summary.json) |
| 11/14 KC-DESIGN | 수업6/7과 데이터·실험·결과설계 대조. 당시새수집/학습0 | [검사](../research_checks/KC-DESIGN-20261114-01/DESIGN_CHECKS.json) |
| 11/14 KC-01/02 | route/seed·독립TraCI·73D·State·제어/종료 | [KC-01](../research_checks/KC-01-20261114-01/README.md), [KC-02](../research_checks/KC-02-20261114-01/README.md) |
| 11/14 KC-03/04 | GAE경계·예산/평가·공통actor·BC이식·CPU재개 | [KC-03](../research_checks/KC-03-20261114-01/README.md), [KC-04](../research_checks/KC-04-20261114-01/README.md) |
| 11/14 KC-05 | B0·602debug전이·writer/loader·복구 | [KC-05](../research_checks/KC-05-20261114-01/README.md) |
| 11/15 KC-06/DIAG | seed11 BC1k·B2/B3각50k·중간LC실패진단·dev100 | [pilot](../research_checks/KC-06-20261115-01/README.md), [진단](../research_checks/KC-06-DIAG-20261115-01/README.md) |
| 11/15 KC-SEEDS/SETTINGS | seed22/33 추가fresh학습·9정책dev100·본설정동결 | [추가seed](../research_checks/KC-06-SEEDS-20261115-01/README.md), [확정](../research_checks/KC-SETTINGS-20261115-01/README.md) |
| 11/15~16 KC-OPS/STORAGE | 본CLI·GPU부분buffer/환경replay재개·commit·next참조/모델보관 | [운영](../research_checks/KC-OPS-20261115-01/README.md), [저장](../research_checks/KC-STORAGE-20261115-01/README.md) |
| 11/16 정리 | 사용자요청으로2,014파일·345,894,912bytes할당량 삭제. 백업/이동 없음 | [정리메타데이터](../research_checks/KC-STORAGE-20261115-01/LAUNCH_READY.json) |
| 11/16 문서개정 | 73D유지·현황/이력분리·실제CLI/저장형식/보관현황 정합화 | [운영호환기록](../../configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json) |
| 11/16 폴더재구성 | 코드 kcity/rl/tools/legacy, 문서 research/specs/guides로 이동. 과학설정 불변·경로SHA만 재고정(layout r2). 서버 LAUNCH_READY 재생성 필요 | [경로대응](../../configs/kcity/main_v1/LAYOUT_MIGRATION.json), [재구성 안내](../guides/KCITY_MAIN_EXECUTION.md#폴더-재구성layout-revision-2-2026-11-16) |

## 유지한 결정

- 주제는 전문가 사전학습의 초기효과·목표도달전이·끝성능·전체비용·수요변화 한계 비교다.
- 판단2Hz·물리0.1초는 공통통제이며 주기최적화 비교는 보류했다.
- expert최소1M+PPO6M+고정archive3M은 제출데이터 장부다. 학습에 필요한 최소량이라는 결론이 아니다.
- 부당대기분류 미지원/벌점0, crossing관측부재, 초기HV10미달은 숨기지 않는다.
- Drive업로드는 하지 않는다. 이전 로컬압축본도 후속삭제요청에 따라 제거했다.
- observation73D·기존전체필드 유지. 컬럼축소안은 적용하지 않았다.

## 계보와 보관

research_checks의 JSON은 해당시점 측정/해시영수증이다. 오래된상태/해시는 현재실행준비를 대신하지 않는다. 삭제된raw로그·임시스크립트·검증데이터는 현재 재개/다운로드자료로 안내하지 않는다. 필요한곡선·Episode평가·모델·요약만 남겼다.

동결당시 계약문서3개는 기존Git commit `ed12226e9b4f5ef54c69aabc35cc7ea40d5f6d65`에 있다. 새 사본/백업을 만들지 않고 현재문서SHA와 명시적호환기록으로 연결한다. 과학설정JSON·환경·정책·학습수식 동결은 유지한다.
