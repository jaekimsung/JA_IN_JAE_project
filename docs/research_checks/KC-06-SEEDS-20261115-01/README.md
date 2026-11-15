# KC-06 추가 학습 seed22/33 pilot

상태: **실행 중**. 기존 seed11의결과는보존하고,정책 초기값/학습 난수만바꾸는두개의추가pilot을시작했다. 본1M비교나final평가가아니다.

## 고정 조건

- 정책판단2Hz(0.5초),SUMO물리tick0.1초(10Hz),결정당5substep. 기존보상/관측/mask/안전/모델/hyperparameter를유지한다. GUI시연의0.02초·4배수요는적용하지않는다.
- 새seed22/33. 각seed마다fresh BC1,000updates와PPO-only/BC→PPO각50,000전이. BC가중치를seed11에서이어받지않는다. PPO/B3 optimizer는각각신규다.
- 이미검증된같은pilot expert10k를읽기전용으로공유한다. 데이터를매seed새로생성해data효과와초기화효과를섞지않는다. 생성비용은한번만집계한다. 새로운본학습pool로승격하지않는다.
- 환경case는원래seed11과같은trainnamespace의1,000,000번대·3/3/4순서다. 여기서바꾸는seed는모델초기화·행동sampling·minibatch/BCsampling의난수다. B2/B3의pairedcase계약을유지한다.
- 원래pilot처럼0/10k간격의동일dev3개를측정한다. 각seed학습후BC/B2/B3를기존진단과같은dev100개(A30/B30/C40,index2,000,000번대)에서평가한다. finalnamespace는사용하지않는다.

## 실행·재개

실행기: [pilot_seeds.py](../../../scripts/kcity/pilot_seeds.py). 기존 [pilot.py](../../../scripts/kcity/pilot.py)의BC/PPO 생성부만config의seed를읽도록일반화했다. seed11을줄경우설정/학습로직은기존과같다. 기존script원본은 `pilot.before.py`에보존했다.

104개회귀검사가통과했다(44.538초). source계약·shareddata전수검사·두config의차이가seed뿐임을확인했다. [사전점검](PREFLIGHT.json)·[실행PID/명령](LAUNCH.json).

실행root: `/home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/replicates_v1/`

- root STATUS.json은현재seed/학습/평가단계를보여준다.
- 각seed22/seed33의STATUS.json은실제transitions/rollout/optimizer카운터와최근checkpoint를보여준다.
- BC는100업데이트, PPO는각rollout update후checkpoint를저장한다. root내STOP파일을만들거나SIGTERM/SIGINT로정상중단을요청할수있다.
- 재개는STOP을치운후동일명령에--resume을추가한다. 파일/source/config검사를통과해야한다. 살아있는OWNER PID가있으면중복실행을거부한다.
- dev100평가도완료한case부터이어간다. 평가도중optimizer업데이트는없다.

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/pilot_seeds.py \
 --output /home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/replicates_v1 \
 --shared-data /home/heven/kcity_research_runs/KC-06-20261115-01/pilot_v1/expert --device cuda
```

최종3seed결과가나오기전PPO-only/BC→PPO우열이나재현성확보완료를주장하지않는다. 현재수요·관측·SUMO안전의범위안에서해석하고원격백업/최종과학설정동결은별도미완료로유지한다.


## 후속 완료 기록

seed22/33의 학습·평가 완료. [3seed 집계와 설정 확정](../KC-SETTINGS-20261115-01/README.md)을 따른다. 위 실행 중 문구는 착수 당시 기록이다.
