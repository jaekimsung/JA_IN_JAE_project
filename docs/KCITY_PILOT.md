# KC-06 시험 학습 실행

현재 단계는 **pilot 실행 중**이다. 본 RQ1의 각1M×3seed 학습과 구분하며, pilot 가중치/자료를 본실험 초기값이나 pool에 재사용하지 않는다.

## 실행 계약

- 실행기: `scripts/kcity/pilot.py`. 73-D, [256,256] ReLU, 총86,022 parameters, seed11, 후보PPO 설정 유지.
- 새 expert10,000전이: 과거602전이 재사용 없음. expert_train/val namespace의case index1,000,000 이상, 약80:20의case 분리. source_stage=pilot. 실제 수량·완주 필터 통과수는QUALITY.json에서 확인.
- BC: 성공한 전체Episode의train만 사용해최대1,000업데이트, 매100업데이트val loss로best 선택. val은gradient에사용하지 않음. checkpoint·sampler/Adam 저장.
- B2/B3: 새PPO/새Adam에서각50,000전이. B3는같은BC best actor만복사하며B2/B3 value head 초기seed/std는같다. 기본PPO2048rollout·10epochs·64minibatch,매10k 경계에서정확히잘라같은전이수로비교.
- 학습 case는train namespace의1,000,000번부터시작. 동일3/3/4순서. pilot용dev는시나리오별1개씩총3개(별도고번index)이며0/10k/20k/30k/40k/50k에서결정적평가. 이는본dev100개/final100개성능을대신하지않는다. final은사용하지않음.
- 각rollout update 후모델/Adam/소유RNG/카운터/환경replay를immutablecheckpoint로저장. LATEST.json은최근확정지점을가리킴.
- `STATUS.json`은phase/방법별실제전이/update/optimizerstep/최근checkpoint/세션속도/peakRSS를기록. `curve.jsonl`은학습곡선원자료. `eval-*.json`은고정전이수의episode/분모기반평가.
- 후보KC01 protocol의본학습enabled=false와미동결flag는변경하지않음. 별도purpose=KC06_PILOT_ONLY로50k이하의pilot을실행한다. 본학습승인이나최종과학설정동결이아님.

## 현재 경로와 명령

실행root: `/home/heven/kcity_research_runs/KC-06-20261115-01/pilot_v1/`

```bash
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B scripts/kcity/pilot.py \
  --output /home/heven/kcity_research_runs/KC-06-20261115-01/pilot_v1 --device cuda
```

이미동일프로세스가실행중이면재실행하지않는다. OWNER.json의PID와실제process를대조한다.

중단하려면root아래`STOP`파일을만든다. 완료된제어경계에서현재rollout을update/저장하고STOPPED로끝난다. 수집중이면현재1024전이block의commit후멈춘다. 재개는STOP파일을치우고동일명령에`--resume`을추가한다. source/config/환경이바뀌면같은run재개를거부한다. checkpoint를바꾼코드로조용히복원하지않는다. 재개시마지막commit이후의학습작업은다시계산될수있고,이는새데이터로중복합산하지않는다.

SIGTERM/SIGINT도같은중단요청으로처리한다. BC는100update저장경계에서재개한다. 프로세스강제kill/정전검증은아직미실행이다.

## 병행 feasibility와남은범위

별도관측정렬B0로A/B/C×각10case×수요1/1.5/2배=90Episode를실행한다. contract_check namespace의2,000,000번대시드를사용한다. 실행기와결과는 `/home/heven/kcity_research_runs/KC-06-20261115-01/`의 `feasibility.py`, `FEASIBILITY_STATUS.json`, `feasibility-*.json`에있다. 학습속도측정과병행되어단독CPU성능벤치마크가아니다.

GPUsmoke는RTX3070에서4전이/1optimizerstep·finite loss·checkpoint복원을통과했다. 100개회귀검사도통과했다. CPU단일런의재현성검증을GPU전체장기재현성검증으로확대하지않는다.

완료후에만각50k결과·동일전이수의성공/충돌/위반/시간·BC초기이점과끝성능·벽시간/저장크기/peakRAM/GPU를정리한다. 교통충분성·기본보상의부당대기0·정지/양보관측한계·shard25k규모·원격백업/장기복구등미해결항목도확인한뒤본학습조건을동결한다. 이번에GitHub/Drive업로드는하지않았고모델은로컬runroot에있다.
