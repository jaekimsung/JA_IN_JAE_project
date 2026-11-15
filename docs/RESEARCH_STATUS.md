# K-CITY 연구 진행 현황

기준일: **2026-11-16** · 브랜치 `main` · 이번 개정은 작업 트리 기준이며 commit/push는 하지 않았다.

**3seed pilot과 본 실험 설정·운영 준비 검증을 완료했다. 본 전문가 수집·본 BC·본 PPO는 아직 시작하지 않았다.** 최신 현황은 이 문서, 날짜별 실적은 [연구 이력](RESEARCH_HISTORY.md), 과학 설정은 [FROZEN_PROTOCOL.json](../configs/kcity/main_v1/FROZEN_PROTOCOL.json)을 따른다.

## 주제와 유지한 조건

주제는 **K-CITY 복합 교통 환경에서 전문가 사전학습의 효과와 한계 분석**이다. 관측만 받는 규칙 전문가 B0, BC-only B1, fresh PPO-only B2, BC actor로 초기화한 PPO B3를 비교한다. 초기 성능·목표까지 필요한 PPO 전이·같은 예산의 끝 성능·전문가/BC 비용·수요 변화 성능을 구분한다.

기존 **73차원 관측을 유지**한다. 73은 observation 벡터의 길이이며 transition의 최상위 key 개수와 다르다. 필드 축소안은 적용하지 않았다. 판단2Hz·물리0.1초·공통[256,256]·86,022parameters·안전mode31/512를 유지한다. [데이터 명세](DATA_COLLECTION_SPEC.md) · [연구 계획](RESEARCH_PLAN.md)

## 단계별 상태

| 단계 | 실제 완료 범위 | 현재 상태 |
|---|---|---|
| KC-01~04 | 경로/seed·Gym73D·GAE·평가·공통actor·BC이식·재개 검사 | 완료 |
| KC-05 | 관측정렬B0·602debug전이·writer/loader·품질/복구 | 완료, 본 데이터 제외 |
| KC-06 | seed11/22/33, BC각1,000updates·B2/B3각50k·9정책dev100 | 완료 |
| KC-SETTINGS | 과학설정·dev/final패널·예산·모델선택 동결 | 완료 |
| KC-OPS/STORAGE | 본CLI·GPU부분rollout재개·데이터/모델commit·저장최적화 | 제한된 검증 완료, READY_LOCAL_ONLY |
| 본 전문가 | 새 유효전이 최소1M, 현재Episode완료까지 수집 | **0전이** |
| 본 BC | 공통train200k/val50k view, 3seed×10kupdates | **0updates** |
| 본 PPO | B2/B3×3seed×각 정확히1M | **0전이·0updates** |
| 최종 평가 | 고정정책·3수요·총3,000Episode | 미실행, 통합 실행 후속 |
| archive/제출 | 고정PPO6정책×500k·≥10M UID union·최종패키지 | 미실행, 실행기/병합·공개 검증 후속 |

## Pilot 결과와 해석

[3seed 원자료·실제 카운터](research_checks/KC-SETTINGS-20261115-01/SUMMARY.json) · [pilot 안내](KCITY_PILOT.md)

| seed | BC 평균완주(s) | PPO-only 평균(s) | BC→PPO 평균(s) |
|---|---:|---:|---:|
| 11 | 58.248 | 57.530 | 57.620 |
| 22 | 58.278 | 57.586 | 57.720 |
| 33 | 58.193 | 57.563 | 57.625 |

9정책 각각 동일dev100에서100/100완주, 관찰AV충돌/적색진입0이었다. 총pilot PPO300k·BC3,000updates, 공유expert10k는 한 번만 센다. BC는0전이 초기 이점이 있었지만 중간checkpoint에서 필수차선미확보 실패가 다시 나타났다. 끝 시점 PPO-only 평균은 BC→PPO보다 약0.095초 짧았다. 작은 차이로 방법의 일반적 우월성을 선언하지 않는다. [실패 진단](research_checks/KC-06-DIAG-20261115-01/README.md)

## 실행·용량·보관

- 현재 CLI는 collect/views/bc/ppo를 지원한다. [실행 방법](KCITY_MAIN_EXECUTION.md)의 check-only는 수집/학습/출력 생성을 하지 않는다.
- [준비 기록](research_checks/KC-STORAGE-20261115-01/LAUNCH_READY.json)은 본7M 준비 범위다. final/archive/제출 전체 완료를 뜻하지 않는다. GPU검증·126회귀검사 통과는 해당 시점 실적이며 이번 문서 개정에서 재학습한 결과가 아니다.
- 선택1·2 적용: 손실없이 next를 복원하는 KC-NEXT-REF-v1, PPO 최신·직전·50k평가 모델 보관. 전체State·NPZ·73D 유지.
- 필요량은 본7M 약45.91GiB·전체10M 약55.71GiB다. **headroom1.5·운영예비20GiB 포함** 추정치다. 2026-11-16 00:52 KST 읽기전용 확인 free약55.98GiB로 전체기준보다 약0.27GiB 높았다. 이전 저장검증 시점에는 부족했다. 외부 작업으로 변하므로 시작 직전 다시 확인한다.
- 11/16 사용자 요청으로 원시로그·debug자료·source복사본·로컬압축본 **2,014개, 할당량 약330MiB를 삭제**했다. 백업/이동 없음. 요약·곡선·Episode평가·필요모델11개·실행의존성은 유지한다.
- 모델root: `/home/heven/kcity_research_runs/KC-06-20261115-01/pilot_v1/`, 추가seed는 `/home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/replicates_v1/`. 모든 중간모델/rawpool이 남아 있지 않아 과거run의 완전 재개를 약속하지 않는다.
- **Drive 업로드 금지 유지. 원격백업·새 로컬압축본 없음.** Git/GitHub는 모델·원시데이터 백업이 아니다.

## 다음 순서와 남은 한계

1. 현재공간·source·owner·프로세스를 확인한 뒤 **새 본 전문가pool**부터 시작한다. 이번 문서 개정은 수집/학습 착수가 아니다.
2. 원본품질·완주whole-Episode·split을 검사하고 공통fitting view를 고정한다. 성공자료250k가 부족하면 중단한다.
3. 새 BC3seed → B2/B3각3seed 본1M 비교. pilot가중치/자료는 이월하지 않는다.
4. final3,000Episode·고정archive3M·전역ID병합·≥10M검증·Hub/영상/발표 패키지.

요청600/900/1200vph는 국소상호작용을 보장하지 않는다. 초기HV10 미달 사례를 제외하지 않고 노출분포를 보고한다. crossing관측슬롯·전체정지/양보 검증·부당대기 인과분류는 없다. compliant_completion은 지원하는 충돌/적색판정에 한정한다. SUMO안전기능을 포함한 시스템 비교이며 실차안전/현장신호현시 복원 결과가 아니다.
