# 결과

v2.1 환경(`configs/kcity/v2_1`)에서 학습한 결과입니다. 방법별·seed별로 학습 그래프와 최종 모델만 둡니다.

```text
outputs/
├── BC/                         B1 행동 모방
├── SAC/                        B2 온라인 SAC (전문가 데이터 없음)
│   ├── training_losses_all_seeds.png   seed별 actor·critic loss, Q, entropy, temperature
│   ├── dev_evaluation_all_seeds.png    seed별 dev 충돌률·완주율·규칙 준수 완주율
│   └── seed11/, seed22/
│       ├── training_losses.png
│       ├── dev_evaluation.png
│       └── final_model/        300,000 전이 예산 종료 시점 모델
└── RLPD/                       B3 RLPD (전문가 데이터 50%)
```

- **최종 모델 읽기:** `kcity.policy.checkpoint.load_policy('outputs/SAC/seed11/final_model')`. `final_model/`의 파일은 `SHA256.json`으로 검증하므로 고치거나 일부만 옮기지 않습니다.
- **dev 결과:** 학습 중 평가(dev 패널 100사례)입니다. final 패널 결과가 아니며, 모델 선택에는 쓰지 않았습니다.
- **비어 있는 폴더:** BC·RLPD 결과와 SAC seed 33은 아직 들어오지 않았습니다.
