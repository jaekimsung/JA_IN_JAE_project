# KC-06 pilot 완료 결과

갱신: 2026-11-16 · **pilot완료,본학습미시작**. [3seed집계](../research_checks/KC-SETTINGS-20261115-01/README.md) · [실패진단](../research_checks/KC-06-DIAG-20261115-01/README.md) · [현황](../research/RESEARCH_STATUS.md)

## 실제수행

- seed11/22/33각freshBC1,000updates,B2/B3각50k전이. 총BC3,000updates·PPO300k.
- 동일새pilotexpert10k공유,기존602debug재사용없음. traincase1,000,000번대·별도dev진단2,000,000번대.
- 73D·[256,256]·86,022parameters·판단2Hz/물리0.1초·안전31/512. BC는100updates마다valbest,PPO는10k마다dev3개평가.
- 끝모델9개를동일dev100(A30/B30/C40)에서결정적평가,모두100/100완주·AV충돌/적색0. final미사용.
- BC초기이점과중간필수LC실패를함께관찰했다. 최종작은시간차로일반적우열을판단하지않았다. [곡선/실험인덱스](../research/EXPERIMENTS.md)

pilot자료/모델은본pool·초기값·제출10M에이월하지않는다. 본설정동결과운영검증은후속완료했다.

## 현재보관

seed11: `/home/heven/kcity_research_runs/KC-06-20261115-01/pilot_v1/`
추가seed: `/home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/replicates_v1/seed22/` 및 `seed33/`

BCbest3개·PPO끝6개·seed11실패진단2개,총11모델을남겼다. seed22BCbest는update900,seed11/33은1000이다. 곡선·devEpisode결과·요약은보존했다. rawexpertpool·console로그·불필요중간모델·fixture/archive는사용자요청으로삭제했다. **기존출력을덮어쓰거나완전재개가능하다고간주하지않는다.**

## 실행범위

[기본pilot](https://github.com/jaekimsung/JA_IN_JAE_project/blob/fac8482/tools/checks/pilot.py)·[추가seed](https://github.com/jaekimsung/JA_IN_JAE_project/blob/fac8482/tools/checks/pilot_seeds.py)는pilot전용이다. 본실행은[main안내](KCITY_MAIN_EXECUTION.md)를따른다. pilot재현은새output/ID에서새10k수집부터해야한다. 추가seedCLI는유효shared-data가필요하므로삭제된과거pool을입력으로안내하지않는다.

당시STATUS/curve는당시실적이다. STOP/--resume도동일source/config/runtime·모든필수입력이남아있는run에한정된다. 완료pilot을실행중으로표시하지않는다. 이번개정에서는재학습/시뮬레이션/업로드를하지않았다.

> 2026-11-16 코드 정리로 KC 단계 검증 스크립트(`tools/checks/`, `check_policy.py`, 운영 probe·preflight)는 삭제됐다. 위 검증 명령을 재현하려면 [commit fac8482](https://github.com/jaekimsung/JA_IN_JAE_project/tree/fac8482)를 checkout한다. 현재 실행 방법은 [실행 안내](KCITY_MAIN_EXECUTION.md)를 따른다.
