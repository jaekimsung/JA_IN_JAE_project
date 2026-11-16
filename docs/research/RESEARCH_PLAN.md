# K-CITY 연구 계획

갱신: 2026-11-16 · [현재현황](RESEARCH_STATUS.md) · [이력](RESEARCH_HISTORY.md) · [실험설정](../../configs/kcity/experiment.json)

**주제: K-CITY 복합 교통 환경에서 전문가 사전학습의 효과와 한계 분석.** 3seed pilot과 본설정동결을 마쳤다. 본 수집/BC/PPO는0이다. 아래값은 현재적용할 통제설정이며 최적값이나 입증된성과가 아니다.

## 1. 질문·가설

| 질문 | 가설·비교 |
|---|---|
| RQ1 | BC초기화가 목표까지 필요한PPO경험을 줄이는가? B2/B3 동일T곡선·목표T·1M끝성능·총비용 비교 |
| RQ2 | 같은맵에서 수요증가시 이점이 유지되는가? 고정정책600/900/1200vph·과제별 실패/시간/노출 비교 |
| RQ3 선택 | 같은수량에서 전문가상황 구성이 영향을 주는가? 주실험뒤 자연/균형표본 비교, 현재상세미동결 |

결합자체를 새알고리즘으로 주장하지 않는다. 초기효과만존재·역효과·차이없음도 유효한답이다. 일반화범위는 같은K-CITY의수요변화이며 새도시/실차/센서검증으로 확대하지 않는다.

## 2. 방법·공통조건

| 방법 | 수행 |
|---|---|
| B0 | 73D만 받는 결정적규칙전문가. 전체State·미래신호·caseID 사용안함 |
| B1 | 새pool의seed별BC best actor,추가RL없음 |
| B2 | fresh PPO-only·새가중치/Adam/rollout |
| B3 | 같은seed B1의trunk/mu/lane만복사한PPO·fresh value head/std/Adam |

B3는BC/PPO loss혼합이 아니다. 공유trunk변화가critic표현에영향을주는것은 사전학습효과에포함한다. [정책계약](../specs/KCITY_POLICY_AND_RESUME.md)

| 항목 | 동결값 |
|---|---|
| 관측 | KC-OBS73-v1,float32[73],기존구성유지. State는분석용 |
| 모델 | shared[256,256]ReLU·Gaussian가감속/차선3범주/value,총86,022·BC85,764parameters |
| 시간 | 판단0.5초(2Hz),물리0.1초·5tick,warmup60초,유한과제300초 |
| 제어 | setAcceleration,+2/-4.5m/s²,속도상한8.33m/s,mode31/512 |
| 교통 | baseline600vph,평가900/1200,4종HV동일비율·동일OD/신호프로그램 |
| 과제 | A신호정지출발·B필수LC·C연속교차로,학습case순서A/A/A/B/B/B/C/C/C/C |
| PPO | lr1e-4,rollout2048,epochs10,minibatch64,γ.99,GAEλ.95,clip.2,value.5,lane entropy.01,gradnorm.5 |
| BC | train200k/val50k,batch256,lr3e-4,10kupdates,val매500,MSE+CE동일가중 |
| 학습seed | 11/22/33,환경case seed와분리 |

2Hz는공통비교조건이다. 주기비교는보류했고 최적/모든교통에서충분하다고하지않는다. GUI의0.02초·4배수요는연구결과에서제외한다.

## 3. 환경·보상과한계

A `-68 → -13 → -71`,B `-3#4 → -3#5 → -3#6 → -3#7 → -3#8 → -68`,C qualifier17edges를사용한다. 출발pos5m·speed2m/s와필수LC/goal을검사했다. 권위자료는[시나리오](../../configs/kcity/v1/scenarios.json)·[패널](../../configs/kcity/panels/cases_final.json)이다. 연구중맵재생성금지.

실제보상은max(0,Δroute_progress)/10+도착10−AV충돌20−적색진입10−무효요청0.02−실제LC0.01이다. unjustified_wait=0이며 정지원인인과분류는미구현이다. Gaussian원본표본/clip입력/요청/실측을분리한다. [환경계약](../guides/KCITY_ENV.md)

crossing차량은기록해도actor입력슬롯은없다. 가림/센서잡음도모델링하지않는다. SUMO안전기능을포함하는시스템비교이며 정책단독양보·완전정지/실차안전을인증하지않는다.

B0 feasibility90/90도착에도 초기HV10미달이baseline8/30·1.5배1/30,최소5대였다. 사례를제외하지않고 요청/실현수요·HV수·근접차노출을보고한다. 높은수요를국소상호작용보장으로해석하지않는다.

## 4. 데이터분리·예산

| 단계 | 계획·통제 | 현재 |
|---|---|---|
| 새expertpool | **최소1M 유효고유전이**,현재Episode완료까지초과허용·실패포함원본 | 0 |
| fitting view | 사전Episode/trafficgroup분리·정상whole-Episode train200k/val50k,seed20261115비복원 | 미생성 |
| 본BC | 동일view공유·3seed각10kupdates·최저val선택·동률은이른모델 | 0 |
| 본PPO | B2/B3×3seed×**정확히1M**=6M·매50k post-update dev100 | 0 |
| final | B0 300+B1/B2/B3 2700=3,000Episode·3수요 | 미실행 |
| archive | budget-end PPO6정책×500k=3M·새case·고정추론·Episode완료 | 미실행 |
| 제출합계 | expert+PPO+archive 유효UID union≥10M,pilot/dev/final제외 | 0 |

10M는수업데이터요건을위한 **계획장부**다. 학습에반드시7M/10M가필요하다는실험결론이아니다. BCview·NPZ복제·HVsnapshot·물리tick·replay·재시도를중복집계하지않는다. PPO는현재on-policy rollout을사용하며보관10M를replay학습하지않는다.

expert시나리오ordinal매5번째val을사전배정한다. Episode비율80:20과전이비율은다를수있다. 정상완료·지원규칙통과·unknown없는whole-Episode에서250k를확보못하면중단하고설계를검토한다. 실패원본은삭제하지않는다.

expert/train/dev/final/archive namespace를분리한다. B2/B3사례순서는같지만Episode길이에따라 같은T에서소비case수는달라질수있다. [데이터계약](../specs/DATA_COLLECTION_SPEC.md) · [실행프로토콜](../specs/EXECUTION_PROTOCOL.md)

## 5. 분석·모델선택

- dev100(A30/B30/C40),T=0·매50k에서평가. 결합완주≥.80 연속2회시첫T를목표도달점·두번째를확인점으로보고한다. 미달은censored,해상도50k다.
- 초기성능·같은T곡선·목표T·budget-end성능을구분한다. 전문가생성/BC/평가/I/O포함전체비용도별도비교한다.
- 주final은1M budget-end,dev-best는보조다. final성능으로재선택하지않으며archive는6개끝모델전부쓴다.
- 3학습seed 원값·평균·범위·paired차이를보고한다. 평가100Episode를학습100반복으로취급하지않는다.
- 완주/AV충돌/적색·unknown/기한/LC실패·전체/완주자시간·교통노출을함께본다. compliant_completion은지원하는충돌/적색판정에한정한다.
- 수업충돌<5%와연구목표완주≥90%·관찰신호준수100%의출처를구분한다. 유한표본0건은실제위험확률0의증명이아니다.

현재pilot은끝완주율이포화돼초기/중간곡선·수요이동·실패분석이필요하다. [결과/제출설계](RESULTS_AND_CONSULTING.md)

## 6. 실행·보관

[본실행기](../guides/KCITY_MAIN_EXECUTION.md)는collect/views/bc/ppo를지원한다. final/archive/전역release병합·포장은후속이다. 새output·source/config/runtime/owner/공간을검사한다. 재개에는모델/Adam/RNG/부분buffer/환경replay가필요하다.

논리State/next/73D를유지하고 물리next참조·checkpoint보관은[저장계약](../specs/KCITY_DATA_PIPELINE.md)을따른다. headroom1.5·예비20GiB 유지. **Drive업로드금지.** rawdebug/로컬압축본은사용자요청으로삭제했고필요모델/집계만남겼다. 이번개정에서는새수집/학습/업로드를하지않았다.
