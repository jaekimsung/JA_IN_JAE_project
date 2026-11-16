# 고속도로 예제 (수업 원본, 레거시)

「자율주행 인공지능 및 제어」 수업에서 제공한 고속도로 PPO·BC 예제입니다. K-CITY 연구와는 별개입니다. 여기의 `data/`와 `results/`는 **K-CITY 학습 성과가 아닙니다.**

| 파일 | 역할 |
|---|---|
| `env/road_config.py` | 도로·차량·교통류 설정 |
| `env/mdp_config.py` | 관측·행동·보상 정의 |
| `env/road_builder.py` | 설정 → SUMO 파일(`env/sumo/`) 생성 |
| `env/sumo_env.py` | Gymnasium 고속도로 환경 |
| `train.py` / `test.py` | PPO 학습 / 정책 평가 |
| `train_bc.py` / `collect_pomdp_data.py` | BC 학습 / 주행 데이터 수집 |
| `view_road.py` | 도로 시각화 |

학습 부품(PPO·BC·버퍼·신경망·평가·로깅)은 저장소 루트의 [`rl/`](../../rl/__init__.py)을 함께 사용합니다. 수업 자료([docs/course/](../../docs/course/0_Project_Introduction.md))의 `python train.py` 명령은 이 폴더에서 실행합니다.

```bash
cd legacy/highway
python train.py        # 결과: legacy/highway/results/<run>/
python test.py
```

`env/` 파일은 이동 전부터 동결 SHA 대상이었으므로 경로 재구성 후에도 [FROZEN_PROTOCOL.json](../../configs/kcity/main_v1/FROZEN_PROTOCOL.json)에 고정되어 있습니다. 수정하면 K-CITY 본 실행 guard가 막힙니다.
