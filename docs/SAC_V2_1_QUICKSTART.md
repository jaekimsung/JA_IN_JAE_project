# v2.1 SAC 학습 시작하기 · seed 11

이 실행의 목적은 K-CITY v2.1에서 RLPD seed 11과 비교할 **SAC(B2) seed 11** 모델을 만드는 것입니다. SAC는 SUMO에서 직접 주행하며 학습 데이터를 모읍니다. 기존 `runs/` 폴더나 전문가 데이터를 따로 받을 필요가 없습니다.

아래 명령은 **Linux, Bash, NVIDIA GPU** 기준입니다.

## 1. 학습 브랜치 받기

터미널에서 다음 두 줄을 실행하세요. v2.1 학습에 사용할 브랜치는 `JAEKIMSUNG`입니다.

```bash
git clone --depth 1 --branch JAEKIMSUNG https://github.com/jaekimsung/JA_IN_JAE_project.git
cd JA_IN_JAE_project
```

이후 명령은 모두 이 폴더에서 실행합니다.

## 2. 내 PC의 학습 환경 확인하기

SUMO **1.28.0**과 Python **3.10 이상**이 필요합니다. NumPy, Gymnasium, CUDA용 PyTorch가 설치된 Python 환경을 활성화한 뒤 실행하세요.

```bash
python --version
sumo --version
python -c "import numpy, gymnasium, torch; from kcity.env.common import sumo_tools; sumo_tools(); import traci; print('CUDA:', torch.cuda.is_available())"
```

- `sumo --version`의 첫 줄에 `1.28.0`이 표시되고 마지막 명령이 `CUDA: True`를 출력하면 다음 단계로 진행하세요.
- `sumo: command not found`가 나오면 SUMO 설치와 실행 경로(`PATH`)를 확인하세요. `traci` 또는 `sumolib`를 찾지 못하면 SUMO 설치 폴더의 `tools/`와 `SUMO_HOME` 경로를 확인하세요.
- `CUDA: False`가 나오면 `nvidia-smi`로 GPU가 인식되는지 확인하고, 현재 Python 환경에 CUDA용 PyTorch가 설치되어 있는지 확인하세요.

## 3. 본 학습 시작하기

아래 블록을 한 번 실행하세요. `mkdir`는 빈 저장소에 로그를 기록할 폴더를 만듭니다.

```bash
mkdir -p runs/dense_v2_1_main
set -o pipefail
python -Bu runner/train_rl.py \
  --experiment configs/kcity/v2_1/experiment.json \
  --method B2 --seed 11 --device cuda \
  --output runs/dense_v2_1_main/B2_seed11 \
  2>&1 | tee -a runs/dense_v2_1_main/B2_seed11.log
```

학습은 **온라인 전이 30만 개**까지 진행합니다. 처음 5,000개는 학습에 사용할 경험을 쌓는 구간입니다. 시작 시점과 이후 25,000개마다 고정 dev 사례 100건을 주행 평가합니다. 로그에 `[DEV B2_seed11]`이 표시되는 동안에는 평가 사례 수가 올라가고, 해당 평가가 끝나면 학습이 이어집니다. 실행 중에는 학습 터미널을 열어 두세요.

## 4. 진행 확인과 결과 전달

| 파일 | 확인할 내용 |
|---|---|
| `runs/dense_v2_1_main/B2_seed11/COMPLETE.json` | 종료 전이 수 300,000과 종료 모델의 체크포인트 경로 |
| `runs/dense_v2_1_main/B2_seed11/dev/T0300000/SUMMARY.json` | 종료 모델의 dev 규칙 준수 완주율과 충돌률 |

결과를 전달할 때는 **`runs/dense_v2_1_main/B2_seed11/` 폴더와 그 옆의 `B2_seed11.log`**를 함께 공유하세요. 이 폴더에는 평가 결과, 학습 곡선, 모델 체크포인트가 있습니다. `runs/`는 Git에서 제외되어 있어 결과는 학습한 PC에 저장됩니다.
