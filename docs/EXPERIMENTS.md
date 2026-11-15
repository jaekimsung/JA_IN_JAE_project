# K-CITY 실험 인덱스

갱신: 2026-11-16 · [현황](RESEARCH_STATUS.md) · [설계](RESEARCH_PLAN.md) · [이력](RESEARCH_HISTORY.md)

검사/pilot와본연구결과를구분한다. 완료는해당범위의완료이며본1M/final/≥10M완료를뜻하지않는다. 삭제raw로그/임시audit script는현재명령으로제공하지않는다.

## 완료기록

| ID | 실제수행 | 근거·제한 |
|---|---|---|
| KC-AUDIT-20261110-01 | seed43 finite177/177·live소실0,BC이식/seed/GAE문제 | [요약](research_checks/KC-AUDIT-20261110-01/evidence/summary.json),학습0 |
| KC-DESIGN-20261114-01 | 수업6/7·데이터/gate/결과대조 | [검사](research_checks/KC-DESIGN-20261114-01/DESIGN_CHECKS.json),당시새실행0 |
| KC-01 | route/seed·출발도착·필수LC,16tests | [기록](research_checks/KC-01-20261114-01/README.md),지정행동 |
| KC-02 | 독립Gym73D/State/제어종료,32tests·6scripted도착 | [기록](research_checks/KC-02-20261114-01/README.md),연구정책아님 |
| KC-03 | GAE/예산/독립평가·사건지표,61tests | [기록](research_checks/KC-03-20261114-01/README.md),optimizer0 |
| KC-04 | 공통actor/BC이식·부분buffer/환경재개,80tests | [기록](research_checks/KC-04-20261114-01/README.md),합성fixture포함 |
| KC-05 | B0/writer/QC/loader·602debug전이,100tests | [기록](research_checks/KC-05-20261114-01/README.md),본pool제외 |
| KC-06 | expert10k·BC1k·B2/B3각50k,seed11 | [기록](research_checks/KC-06-20261115-01/README.md),pilot |
| KC-06-DIAG | 중간LC실패4건·개입진단·seed11 dev100 | [기록](research_checks/KC-06-DIAG-20261115-01/README.md),개입은성과제외 |
| KC-06-SEEDS | seed22/33 freshBC각1k·B2/B3각50k·dev100 | [기록](research_checks/KC-06-SEEDS-20261115-01/README.md),완료 |
| KC-SETTINGS | 3seed/9정책집계·본설정/패널동결 | [요약](research_checks/KC-SETTINGS-20261115-01/SUMMARY.json),본학습0 |
| KC-OPS | 본CLI·GPU재개/STOP/기록,118tests | [기록](research_checks/KC-OPS-20261115-01/README.md),bounded |
| KC-STORAGE | next손실없는참조·모델보관,126tests+BC보관7검사 | [기록](research_checks/KC-STORAGE-20261115-01/README.md),본0 |

test수는단계별누적이며합산하지않는다. GPU probe400결정scriptedprefix/환경replay는학습전이에더하지않는다.

## Pilot비교

총PPO300k·BC3,000updates,공유expert10k한번집계. 9정책각각동일dev100에서100/100완주·AV충돌/적색0. 시간/해석은[현황](RESEARCH_STATUS.md)참조. 끝성과로중간실패를지우지않는다.

0/10/20/30/40/50k의동일pilot dev3개완주수:

| seed | B2 PPO-only | B3 BC→PPO |
|---|---|---|
| 11 | 0,2,3,3,1,3 | 3,3,1,1,1,3 |
| 22 | 0,1,3,2,1,3 | 3,1,1,1,1,3 |
| 33 | 0,2,1,1,3,3 | 3,3,3,3,3,3 |

3case곡선은개발진단이며본dev100/final/통계적우월성을대신하지않는다. expert label 유지9936/좌64/우0은편중가설근거이며인과검증결과는아니다.

## 본연구등록

| ID | 설계 | 실제 |
|---|---|---|
| KC-RQ1-v1 | 새expert≥1M·BC3seed각10k·B2/B3각3seed×1M | 수집0·BC0·PPO0 |
| KC-RQ2-v1 | 고정끝정책·600/900/1200vph·총3000Episode | 미실행 |
| KC-ARCHIVE-v1 | 6끝정책×500k·새case·고정추론 | 미실행·통합CLI후속 |
| KC-RQ3-v1 | 자연/균형구성동일예산 | 선택·미실행·주실험뒤 |

실행전runUID·시각·commit/dirtysourceSHA·환경/패널/데이터·초기화·요청예산·명령/owner를등록한다. 이후실제T/rollout/optimizer·중단/실패/완료·분모·비용·출력SHA를기록한다. final로조건/모델을바꾸면새실험이다.

## 기존자료경계

- [신호before/after](../maps/kcity/reports/signals_validation/summary.json): after12회2124/2124도착·충돌기록0,before12회4회판정실패·충돌기록5. 전체24회를무충돌로쓰지않는다.
- [Live60/80](../maps/kcity/reports/live_demo_validation.json): 60대상한seed0/1/2각3600초와기각80대trial분리. 충돌카운터는차량-step집계다.
- [고속도로legacy](../results/run_20260907_202220/eval_log.csv): 마지막평가194560전이success0·timeout1.0은K-CITY결과가아니며최종예산완료증거도아니다.

현재필요모델/곡선/집계는남겼고 rawaudit/probe로그·불필요중간모델·압축본은11/16삭제했다. 과거hash는계보이며현재파일존재증명이아니다.
