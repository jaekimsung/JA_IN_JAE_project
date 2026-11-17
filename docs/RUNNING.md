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

학습된 정책으로 수집할 때(최종 정책 3M)는 bundle을 `--policy`로 넘깁니다. 방법 이름(B1·B2·B3)은 bundle에서 자동으로 판별하며, 기본 목표는 정책당 500k입니다.

```bash
python -B runner/collect.py --output runs/archive_B3_seed11 --workers 8 --policy <B3_seed11의 COMPLETE.json checkpoint>
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

## 4. 강화학습 (B2 온라인 SAC, B3 RLPD)

```bash
for s in 11 22 33; do
  python -B runner/train_rl.py --method B2 --seed $s --output runs/B2_seed$s &
  python -B runner/train_rl.py --method B3 --seed $s --prior runs/expert --output runs/B3_seed$s &
done; wait
```

각 run은 300,000 전이를 학습하고, 25,000마다 dev 평가를 `dev/T*/SUMMARY.json`, 학습 곡선을 `curve.jsonl`, 목표 도달 전이 수를 `SAMPLE_EFFICIENCY.json`에 남깁니다. B3는 `--prior`로 준 전문가 pool에서 100만 전이를 사전 데이터로 읽습니다. 환경 1 step마다 critic을 20회 update하므로 GPU 사용을 권장합니다.

## 5. 평가

```bash
python -B runner/evaluate.py --policy expert --panel dev --output runs/eval/expert_dev
python -B runner/evaluate.py --policy <COMPLETE.json의 checkpoint> --panel final --output runs/eval/B3_seed11
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
