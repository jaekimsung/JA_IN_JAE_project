# 실행 방법

저장소 루트에서 실행합니다. 필요 환경은 SUMO **1.28.0**(SUMO Python tools 포함), Python 3.10 이상, NumPy, PyTorch, Gymnasium입니다. 맵 생성 도구용 의존성은 [maps/tools/requirements.txt](../maps/tools/requirements.txt)에 따로 있습니다.

```bash
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1
```

## 1. 맵 확인

```bash
python runner/view_kcity.py                 # GUI: 빨간 데모 차량 + 지속 투입되는 일반 차량
python runner/view_kcity.py --aerial        # 항공사진 배경
python runner/view_kcity.py --nogui --seconds 3600
```

## 2. 전문가 데이터 수집

```bash
nproc                                                        # 코어 수 확인 → 워커 수 결정 (워커당 약 1~1.5코어)
python -B runner/collect.py --output runs/expert --workers 8 # 최소 4M 전이 (experiment.json 예산)
python -B runner/collect.py --output runs/expert --target 5000   # 작은 확인 실행
```

학습된 정책으로 수집할 때(최종 정책 4.2M)는 bundle을 `--policy`로 넘깁니다. 방법 이름(B1·B2·B3)은 bundle에서 자동으로 판별하며, 기본 목표는 정책당 700k입니다.

```bash
python -B runner/collect.py --output runs/archive_B3_seed11 --workers 8 --policy <B3_seed11의 COMPLETE.json checkpoint>
```

여러 서버에 나눌 때는 서버마다 part 하나씩 실행하고, `part-XX/`를 한 폴더에 모은 뒤 마무리합니다.

```bash
python -B runner/collect.py --output runs/expert --part 3 --parts 8
python -B runner/collect.py --output runs/expert --finalize
```

사례 계획은 목표 전이당 최소 한 사례를 확보하는 결정적 생성 규칙으로 저장합니다.
필요한 사례만 메모리에 생성하므로, 짧은 Episode가 많아도 고정 20,000개 계획이 먼저
소진되는 문제가 없습니다. 워커별 10개 사례 주기 분할과 기존 사례의 seed·split은 유지됩니다.

작은 예산으로 점검할 때는 본 설정을 복사한 별도 JSON에 `run_purpose: "pilot"`을 지정하고
각 명령에 `--experiment <pilot.json>`을 전달합니다. 수집·BC view·학습에 동일한 설정을 사용합니다.
Pilot 전문가 데이터는 학습 사용 가능 표시가 꺼진 `pilot_expert_pool`로 기록되며,
본 BC·B3 학습에서 거부됩니다. Pilot BC view와 본 학습도 서로 섞을 수 없습니다.
Pilot 데이터·모델은 본 데이터 수와 본 초기값에 이월하지 않습니다.

## 3. BC

```bash
python -B runner/train_bc.py views --pool runs/expert --output runs/bc_views --workers 8
for s in 11 22 33; do python -B runner/train_bc.py train --views runs/bc_views --seed $s --output runs/bc_seed$s & done; wait
```

BC view 생성은 pool 검사·split별 선택 행 수·500 shard마다 처리 현황을 터미널에 출력합니다.
BC 학습은 시작·재개 시 설정을, 기본 1,000 update마다 진행률·구간 평균 학습 손실·검증 손실·
가속도/차선 명령 MSE·최적 검증 손실·경과 시간·처리 속도·예상 남은 시간·체크포인트 경로를 출력합니다.
예상 남은 시간은 현재 실행 세션의 평균 속도로 계산합니다. 중단·완료도 별도 표시하며,
출력은 즉시 flush하므로 `| tee bc.log`로 화면과 파일에 함께 기록할 수 있습니다.
기존 `curve.jsonl`, `STATUS.json`, `BEST.json`, `COMPLETE.json`도 계속 저장됩니다.

### 학습 로그 그래프

Matplotlib이 설치된 데스크톱 터미널에서 실행합니다. 기본 명령은 `runs/` 아래의 모든
`curve.jsonl`을 찾아 BC·RL 학습 지표와 RL 평가 비율을 각각 그래프 창으로 엽니다.
Pilot 로그도 해당 폴더 아래에 있으면 포함되므로 본 학습만 비교할 때는 `--run`을 지정합니다.

```bash
python -B runner/plot_training.py
python -B runner/plot_training.py --root runs/another_experiment
python -B runner/plot_training.py \
  --run BC11=runs/bc_main_seed11 \
  --run BC22=runs/bc_main_seed22 \
  --run BC33=runs/bc_main_seed33
```

이미지는 자동 저장하지 않습니다. 그래프 창 도구 모음의 저장 버튼으로 원하는 그림의
파일명·형식을 선택합니다. 창에서 확대·이동도 할 수 있습니다. BC는 같은 실행의 학습 곡선을
실선, 검증 곡선을 점선으로 그리고, loss 그래프의 별은 `BEST.json`의 선택 지점입니다.
로그에 존재하는 숫자 지표를 자동으로 찾아 그리며, 누락된 값과 RL 무작위 탐색 구간은
0으로 채우지 않습니다. 기존 구간 평균과 과거 마지막 update 값은 원래 기록대로 표시하며,
추가 평활화나 seed 평균은 적용하지 않습니다.
학습 중에도 실행할 수 있지만 실행 시점의 스냅샷이므로 갱신하려면 창을 닫고 다시 실행합니다.
GUI backend 오류가 나면 Tk가 설치된 환경에서 `MPLBACKEND=TkAgg python -B runner/plot_training.py`로 실행합니다.

## 4. 강화학습 (B2 온라인 SAC, B3 RLPD)

```bash
for s in 11 22 33; do
  python -B runner/train_rl.py --method B2 --seed $s --output runs/B2_seed$s &
  python -B runner/train_rl.py --method B3 --seed $s --prior runs/expert --output runs/B3_seed$s &
done; wait
```

각 run은 300,000 전이를 학습하고, 25,000마다 평가 결과를 `dev/T*/SUMMARY.json`, 학습 곡선을 `curve.jsonl`, 목표 도달 전이 수를 `SAMPLE_EFFICIENCY.json`에 남깁니다. B3는 `--prior`로 준 전문가 pool에서 100만 전이를 사전 데이터로 읽습니다.

B3는 시작할 때 전문가 pool 전체의 파일·전이 일치와 part 중복을 다시 검증합니다.
환경 계약·본/Pilot 구분·전체 pool 예산이 맞고, `expert_train` 전이가 설정된 사전 데이터
수 이상일 때만 학습을 진행합니다.

### RL 터미널 모니터링

RL은 초기화·시작·재개·무작위 탐색 종료·체크포인트 저장·중단·완료를 즉시 출력합니다.
기본 30초마다 전이 수·진행률·learner update 수·에피소드 수·구간 평균 critic/actor loss·Q·
entropy·temperature·경과 시간·처리 속도·대략적인 남은 시간을 표시합니다.
`--report-every 10`으로 터미널 출력 간격만 바꿀 수 있으며 학습 설정·저장 주기는 바뀌지 않습니다.
`PROGRESS_UNCOMMITTED`는 마지막 저장 이후의 아직 확정되지 않은 진행 상태입니다.
손실은 마지막 저장 이후의 누적 구간 평균이고 학습 update가 없으면 `n/a`입니다.
처리 속도·예상 시간은 초기화와 평가 시간을 포함한 현재 실행 세션 기준의 추정치입니다.

시작 시 T=0에서도 평가 사례 100개를 평가하며 이때는 학습하지 않습니다. 평가 시작·10개 사례마다의
진행·종료·규칙 준수 완주율·충돌률을 출력합니다. 이후에도 25,000 전이마다 같은 평가를 합니다.
파일 로그 `curve.jsonl`·`STATUS.json`과 평가 결과는 기존 주기로 계속 저장됩니다.

```bash
set -o pipefail
python -B runner/train_rl.py --method B2 --seed 11 --device cuda \
  --output runs/B2_seed11 --report-every 30 2>&1 | tee runs/B2_seed11.log
```

### 학습 손실 로그

`curve.jsonl`의 BC `training`과 RL `metrics`는 직전 로그 이후 수행한 학습 update의
구간 평균입니다(`metric_aggregation: "interval_mean"`). BC는 기본 1,000 update마다,
RL은 기본 5,000 전이마다 기록하며, STOP이나 예산 종료 시 짧은 구간도 기록합니다.
`training_update_count`는 평균에 포함된 learner update 수입니다.
구간은 BC의 `interval_start_updates` 또는 RL의 `interval_start_transitions` 초과부터
현재 `updates` 또는 `transitions` 이하까지이며, 재개 후에는 복원 시점부터 새 구간을 시작합니다.

RL `critic_loss`와 `q`는 learner update 안의 모든 critic minibatch를 먼저 평균한 값입니다.
따라서 critic loss의 실제 minibatch 수는 `training_update_count × utd_ratio`입니다.
actor loss·entropy·temperature는 learner update별 값을 평균합니다.
초기 무작위 탐색 중 실제 학습 update가 없는 구간은 `metrics: null`,
`training_update_count: 0`으로 남깁니다. BC `validation`은 검증 데이터 전체의 평균이며,
구간 평균 여부 표시가 없는 기존 로그는 마지막 update 값입니다.

## 5. 평가

```bash
python -B runner/evaluate.py --policy expert --panel dev --output runs/eval/expert_dev
python -B runner/evaluate.py --policy <COMPLETE.json의 checkpoint> --panel dev --output runs/eval/B3_seed11
python -B runner/evaluate.py --policy <bundle> --panel dev --limit 3 --output runs/eval/smoke   # 작은 확인
```

`--policy`는 `expert` 또는 BC·RL bundle 폴더입니다. 수요 배수별로 `EPISODES.json`(Episode별 지표)과 `SUMMARY.json`을 씁니다. `SUMMARY.json`에는 충돌률·완주율과 Wilson 95% 구간, 교통 노출(`exposure`), 정지 지표(`stops`), 문제 상황별 지표(`situations`)가 들어 있습니다. 화면에는 세 개의 표가 출력됩니다.

여러 방법의 평가 결과와 RL 학습 곡선을 가설별로 나란히 보려면 `report.py`를 씁니다.

```bash
python -B runner/report.py --eval B0=runs/eval/expert --eval B1=runs/eval/B1_seed11 \
    --eval B2=runs/eval/B2_seed11 --eval B3=runs/eval/B3_seed11 \
    --run B2=runs/B2_seed11 --run B3=runs/B3_seed11 --output runs/report.json
```
- **성능 표:** 충돌률·완주율·규칙 준수 완주율·평균 완주 시간
- **노출·정지 표:** 출발 시 HV, 시간가중 HV, 출발 HV 10대 미만 사례 수, AV 50m 안 HV 수와 존재 비율, 선행차 존재 비율, 정지 시간 평균·최대, 기한 초과 수

### 평가 결과 그래프

```bash
python -B runner/plot_evaluation.py --root runs/eval/<평가_폴더>
python -B runner/plot_evaluation.py --eval BC11=<평가_폴더1> --eval BC22=<평가_폴더2>
```

`SUMMARY.json`과 `EPISODES.json`에서 전체 완주율·규칙 준수 완주율·충돌률, 종료 원인,
시나리오별 규칙 준수 완주율, 필수 차선 변경 위치와 변경 전 정지 시간을 그래프 창으로 엽니다.
상위 run에 전체 요약이 있으면 하위 demand 복사본은 중복으로 표시하지 않습니다.
원인이 겹치지 않도록 종료 원인 그래프는 Episode당 최종 원인 하나를 셉니다.
차선 변경이 없는 사례의 위치는 0으로 대체하지 않으며, 범례에 변경 건수/대상 건수를 표시합니다.
차선 끝 1m 기준선은 평가에 해당 진단값이 기록돼 있을 때만 표시합니다.
이미지는 자동 저장하지 않고 창 도구 모음의 저장 버튼으로 선택 저장합니다.
동일한 사례 패널인지 확인하고 비교하며, 각 seed는 별도로 표시합니다.

## 6. 주행 영상과 데이터 공개

```bash
python -B runner/record_video.py --policy <bundle 또는 expert> --scenario C --video --once --output runs/video/C
python -B runner/export_hf.py --dataset runs/expert --dataset runs/B3_seed11/transitions --output runs/hf_export
```

- **영상:** GUI 화면을 tick마다 저장해 `drive.mp4`로 만듭니다(ffmpeg 필요). AV는 빨간색, HV는 노란색입니다. `--demo-step 0.02`를 주면 화면이 부드러워지며, 이 값은 시연용이고 평가 조건과는 별개입니다.
- **HF 폴더:** 데이터 파일, dataset card, 독립 reader를 만듭니다. Hugging Face 업로드는 `huggingface-cli upload <user>/<repo> runs/hf_export --repo-type dataset`으로 직접 합니다.

## 중단과 재개

```bash
touch runs/B2_seed11/STOP          # 저장 후 종료 (SIGINT/SIGTERM도 같음). 수집 pool은 runs/expert/STOP
rm runs/B2_seed11/STOP
python -B runner/train_rl.py --method B2 --seed 11 --output runs/B2_seed11 --resume
```

- **같은 명령으로 재개:** 재개는 같은 출력 폴더와 같은 설정에서만 가능합니다. `CONFIG.json`의 설정 digest를 비교하고, 수집은 워커 수도 같아야 합니다.
- **같은 SUMO 버전:** 현재 Episode를 같은 행동으로 다시 실행해 복원하므로, SUMO 버전과 환경 코드가 같아야 정확히 재개됩니다.
- **중단 시점의 처리:** 중단 시점까지의 전이와 learner 상태를 함께 확정합니다. 재개하면 replay buffer를 확정된 전이에서 다시 만들고 이어서 학습합니다.

## 회귀 검사

```bash
python -B -m unittest discover -s tests
```

SUMO를 실제로 띄우는 테스트는 환경 계약의 SUMO 버전(1.28.0)과 설치된 버전이 같아야 통과합니다.
