# 실행 방법

저장소 루트에서 실행합니다. 필요 환경은 SUMO **1.28.0**(SUMO Python tools 포함), Python 3.10 이상, NumPy, PyTorch, Gymnasium입니다. 맵 생성 도구용 의존성은 [tools/map/requirements.txt](../tools/map/requirements.txt)에 따로 있습니다.

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
python -B runner/collect.py --output runs/expert --workers 8 # 최소 1M 전이 (experiment.json 예산)
python -B runner/collect.py --output runs/expert --target 5000   # 작은 확인 실행
```

여러 서버에 나눌 때는 서버마다 part 하나씩 실행하고, `part-XX/`를 한 폴더에 모은 뒤 마무리합니다.

```bash
python -B runner/collect.py --output runs/expert --part 3 --parts 8
python -B runner/collect.py --output runs/expert --finalize
```

## 3. BC

```bash
python -B runner/train_bc.py views --pool runs/expert --output runs/bc_views --workers 8
for s in 11 22 33; do python -B runner/train_bc.py train --views runs/bc_views --seed $s --output runs/bc_seed$s & done; wait
```

## 4. PPO

```bash
for s in 11 22 33; do
  python -B runner/train_ppo.py --method B2 --seed $s --output runs/B2_seed$s &
  python -B runner/train_ppo.py --method B3 --seed $s --bc-run runs/bc_seed$s --output runs/B3_seed$s &
done; wait
```

각 run은 정확히 1M 전이를 학습하고, 50k마다 dev 평가를 `dev/T*/SUMMARY.json`, 학습 곡선을 `curve.jsonl`, 목표 도달 전이 수를 `SAMPLE_EFFICIENCY.json`에 남깁니다. 최종 모델은 `COMPLETE.json`의 `checkpoint`(1M 시점 bundle)입니다. 모든 전이는 `<run>/transitions/`에 데이터셋 형식으로 저장됩니다.

## 5. 평가

```bash
python -B runner/evaluate.py --policy expert --panel dev --output runs/eval/expert_dev
python -B runner/evaluate.py --policy <COMPLETE.json의 checkpoint> --panel final --output runs/eval/B3_seed11
python -B runner/evaluate.py --policy <bundle> --panel dev --limit 3 --output runs/eval/smoke   # 작은 확인
```

`--policy`는 `expert` 또는 BC·PPO bundle 폴더입니다. 수요 배수별로 `EPISODES.json`(Episode별 지표)과 `SUMMARY.json`(충돌률·완주율과 Wilson 95% 구간)을 씁니다.

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
python -B runner/train_ppo.py --method B2 --seed 11 --output runs/B2_seed11 --resume
```

- **같은 명령으로 재개:** 재개는 같은 출력 폴더와 같은 설정에서만 가능합니다. `CONFIG.json`의 설정 digest를 비교하고, 수집은 워커 수도 같아야 합니다.
- **같은 SUMO 버전:** 현재 Episode를 같은 행동으로 다시 실행해 복원하므로, SUMO 버전과 환경 코드가 같아야 정확히 재개됩니다.
- **중단 시점의 처리:** 중단 때문에 추가 PPO update를 하지는 않습니다. rollout이 덜 찬 상태라면 buffer째 저장합니다.

## 회귀 검사

```bash
python -B -m unittest discover -s tests
```

SUMO를 실제로 띄우는 테스트는 환경 계약의 SUMO 버전(1.28.0)과 설치된 버전이 같아야 통과합니다.
