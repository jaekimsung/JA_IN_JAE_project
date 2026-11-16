# K-CITY 수집·학습·실험 실행 프로토콜

갱신: 2026-11-16 · [현황](../research/RESEARCH_STATUS.md) · [데이터](DATA_COLLECTION_SPEC.md) · [실행명령](../guides/KCITY_MAIN_EXECUTION.md) · [결과/제출](../research/RESULTS_AND_CONSULTING.md)

**READY_LOCAL_ONLY, 본 수집·BC/PPO 미시작.** 과학설정은[FROZEN_PROTOCOL.json](../../configs/kcity/main_v1/FROZEN_PROTOCOL.json), 운영준비는[LAUNCH_READY.json](../research_checks/KC-STORAGE-20261115-01/LAUNCH_READY.json)이다. frozen의training_enabled/launch_ready=false는동결당시기록으로보존하고별도운영계층이실행을검증한다.

## 1. Gate 현황

| Gate | 완료범위 | 남은사항 |
|---|---|---|
| G0설계/역할 | 데이터·실험·결과문서 | 실제담당/검토자·컨설팅배정확인 |
| G1환경 | A/B/C·seed·독립TraCI·73D·tick·종료검사 | 전체정지/양보·실차검증아님 |
| G2학습/재개 | GAE·mask/rawlogprob·BC이식·cap·CPU/GPU bounded재개 | 검증밖다중worker/장기장애보장없음 |
| G3teacher/writer | B0·State/next·JSONL/NPZ·UID/split·commit/복구 | 최종release병합·원격제출복원후속 |
| G4pilot | 3seed BC각1k·B2/B3각50k·9정책dev100·B0 90회 | 본1M성과로확대하지않음 |
| G5과학설정 | seed·예산·보상·교통·패널·모델선택동결 | 결과를보고방법별재튜닝금지 |
| G6운영준비 | 본CLI·source/owner/공간검사·저장최적화 | 실제착수0,시작직전재확인 |
| 제출준비 | ≥10M장부·평가/영상/제출설계 | final/archive통합·전역병합/포장·외부접근미완료 |

판단2Hz·물리0.1초·warmup60초·300초과제·73D·[256,256]·안전31/512·요청600/900/1200vph를유지한다. [전체설정](../research/RESEARCH_PLAN.md). GUI변형은제외한다.

## 2. 실행순서·통과조건

| 단계 | 수행·예산 | 다음조건 |
|---|---|---|
| S0확인 | source/science·owner·프로세스·현재공간·check-only | 실패시시작안함 |
| S1새expert | B0 baseline새case·최소1M후현재Episode완료 | 실패포함원본·전체DQ |
| S2views | 사전Episode/group분리·정상whole-Episode train200k/val50k | 충분량·고유UID·누출0·동일view |
| S3본BC | 3seed각10kupdates,batch256,val매500 | 최저MSE+CE·모델/Adam/RNG/곡선 |
| S4본PPO | B2fresh/B3same-seedBCactor·2×3×정확히1M | 매50k post-update dev100·끝모델/카운터 |
| S5final | B0 300+B1/B2/B3 2700=3000Episode | 고정case/모델·실패포함분모·3수요 |
| S6archive | 6개끝PPO정책×500k·고정추론·새case·Episode완료 | weights불변·학습재투입금지 |
| S7release | expert+PPO+archive≥10M 유효UID union | 전역ID·SHA·필수필드·HF/모델/영상/문서 |

S0의운영검증/pilot은완료했다. S1이후본카운터는0이다. S5/S6자동실행은아직제공하지않는다. 패널생성은평가완료가아니다. archive는성공정책만골라기록하지않는다.

PPO1M은run별정확한cap이며 마지막rollout은잔여예산·50k경계로자른다. expert/archive는최소량후Episode완료로초과할수있다. optimizer step·rollout update·환경전이는별도집계한다.

## 3. 분리·선택

expert는시나리오ordinal매5번째val,학습사례는A/A/A/B/B/B/C/C/C/C다. dev/final/향후archive는별도namespace다. 학습seed와환경seed를분리한다. 파일view/replay/재시도를새전이로세지않는다.

BC는지원규칙통과·unknown없는정상whole-Episode만fitting에쓴다. 실패raw는남긴다. label은bounded가감속/Lane, PPOlogprob는원본Gaussian기준이다. 주모델은budget-end,dev-best보조이며final로선택하지않는다. 목표dev결합완주≥.80연속2회·첫T/확인T분리·미달censored다.

## 4. 실제entrypoint

| 목적 | 코드 |
|---|---|
| 본collect/views/bc/ppo | [main_experiment.py](../../tools/main/main_experiment.py) |
| debug수집/검증 | [collect_expert.py](../../tools/checks/collect_expert.py), [validate_data.py](../../tools/checks/validate_data.py) |
| pilot | [pilot.py](../../tools/checks/pilot.py), [pilot_seeds.py](../../tools/checks/pilot_seeds.py) |
| 환경/학습/정책probe | [check_env.py](../../tools/checks/check_env.py), [check_learning.py](../../tools/checks/check_learning.py), [check_policy.py](../../tools/checks/check_policy.py) |
| 운영probe/preflight | [check_main_operations.py](../../tools/main/check_main_operations.py), [preflight_main.py](../../tools/main/preflight_main.py) |

본argv는[실행안내](../guides/KCITY_MAIN_EXECUTION.md)한곳에서유지한다. check-only는learner/output없지만입력pool/모델전체를검사하는dry-run은아니다. 실제stage에서필수입력을검사한다.

preflight_main.py는출력/로컬압축본을만들수있어문서점검목적으로무조건실행하지않는다. 삭제archive를재생성하지않았다. 과거설계placeholder collect.py/train_bc.py/train_ppo.py/evaluate.py/summarize.py/package_release.py는현재CLI가아니다.

본root예정은 `/home/heven/kcity_research_runs/KC-MAIN-v1/`. 새run은CONFIG/owner등록후STATUS/curve/checkpoint에실제진도를기록한다. 기존pilot을덮어쓰지않는다.

## 5. 저장·중단·재개

KC-NEXT-REF-v1은다음행과같은next만UID참조하고 terminal/shardtail은명시한다. reader가전체논리행을복원하며NPZnext도유지한다. PPO는검증된nativebundle을외부store에먼저확정하고데이터shard에SHA참조를남긴다.

PPO최신·직전·50k평가·초기모델,BC최신·직전·필요best를보관한다. 보관모델검증후해당새run의불필요모델만제거하며데이터UID/SHA는바꾸지않는다. STOP/SIGINT/SIGTERM은완결전이·부분rollout을보존하며중단때임의추가update를하지않는다.

재개는동일output/source/config/runtime·명시적--resume이필요하다. 현재Episode를같은seed+행동replay로복원하고snapshot/관측/mask일치시learner복원한다. replay는전이/update에합산안한다. 살아있는owner lock은빼앗지않는다. 삭제된과거pool로완전재개가능하다고하지않는다.

## 6. 공간·보관·실패

필요량추정은실측bytes/T·metadata·모델에headroom1.5+예비20GiB를적용한다. 본7M45.91GiB·전체10M55.71GiB추정,시점별free는[현황](../research/RESEARCH_STATUS.md)을따른다. 시작직전/장기운영중재확인한다. 필수State/정밀도/예비기준은줄이지않는다.

**Drive업로드금지.** 원격백업미실행,로컬압축본도삭제했다. rawdebug/log/source복사본삭제는후속사용자지시이며과거검증당시보관과구분한다.

필드누락/중복/GAE오류/NaN/source불일치/공간부족은중단·실패로기록한다. 정책충돌/LC실패를인프라무효로숨기지않는다. 과학조건변경은새설계/runID·비교가능성영향을명시한다.
