# KC-06 pilot 실행 현황

갱신: 2026-11-16. **아래는 해당 단계 실행 당시의 이력**이다. 현재 현황은 [RESEARCH_STATUS](../../research/RESEARCH_STATUS.md), 후속 단계는 [RESEARCH_HISTORY](../../research/RESEARCH_HISTORY.md)를 따른다. 당시 미완료/후속 문구는 현재 미구현을 뜻하지 않는다. 사용자 요청으로 원시 로그·debug 데이터·fixture·source 복사본·로컬 압축본은 삭제했다. 본문에 나온 과거 파일명/경로/SHA는 계보이며 현재 보관 또는 완전 재개를 보장하지 않는다. 필요한 요약·곡선·평가 및 모델11개만 유지하고 새 백업/이동은 하지 않았다.
상태: **완료**(seed11 pilot). 당시 착수 내용: [실행 계약/명령/STOP/재개](../../guides/KCITY_PILOT.md)를 따른다. 시작 기록·PID/경로·GPU 검사를 보존했다.

- 100개 회귀 검사 통과(46.468초): TESTS.log.
- RTX3070에서 실제4전이/1optimizer step와 재개 smoke 통과. 이4전이는50k pilot 예산과 별도다.
- pilot은새 expert10k→BC1000updates→B2/B3각50k 순서다. 별도 B0 90case feasibility도 실행한다.
- 실행root: `/home/heven/kcity_research_runs/KC-06-20261115-01/pilot_v1/`. 실시간 상태는 STATUS.json,재개 안내는 HANDOFF.md,방법별곡선과checkpoint는B2/B3하위다.
- source/config는 CONFIG.json에고정했다. 현재본실험protocol동결/학습enabled flag를바꾸지않고별도pilot budget만실행한다.
- 최종완료보고/과학설정동결은두방법의50k와미해결항목을확인한후다. 이전데이터602전이·기존학습모델을pilot입력으로재사용하지않는다. final case와본1M비교는미실행이다.

## 실측 진도 스냅샷

Pilot expert10,000전이(전체95개완료Episode+마지막부분Episode), BC1,000updates완료. B2의첫checkpoint는2,048전이/rollout update1/Adam320steps다. SHA와전체checkpoint읽기를검사했다. 실제learner가실행됐고모델/optimizer카운터가증가했다. B3는B2 50k완료후순차실행예정이다. 최신카운터는live STATUS.json이우선이다.

첫세션속도약13.84전이/초는학습전0전이평가시간을포함한초기값이다. 안정상태/순수rollout속도나장기예상완료시간으로확대하지않는다. GPU RTX3070의해당PID에CUDA메모리할당도확인했다.

진도확인시점은 LIVE_VERIFICATION.json에있다. 두방법의50k완료및과학설정동결은아직완료하지않았다. 당시 프로세스는 후속 완료했다. 현재 남은 결과와 모델은 최신 현황을 따른다.
