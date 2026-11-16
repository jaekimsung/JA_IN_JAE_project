# 환경 계약 (v1)

환경이 따르는 시나리오·seed·제어 계약입니다. 학습 설정(정책·PPO·BC·예산)은 [experiment.json](../experiment.json)에 있습니다. 이 파일들의 내용은 사례 ID(`case_uid`) 계산에 들어갑니다. 바꾸면 [평가 패널](../panels/)을 다시 만들어야 하고, 기존 결과와 섞을 수 없습니다.

| 파일 | 내용 |
|---|---|
| [protocol.json](protocol.json) | SUMO 버전(1.28.0), 맵·신호·경로 파일 SHA, 시간 단위(0.1초 tick, 0.5초 결정, warmup 60초), 제어(setAcceleration, +2/−4.5 m/s², 8.33 m/s, speedMode 31, laneChangeMode 512), 교통 수요, seed namespace |
| [scenarios.json](scenarios.json) | A/B/C 경로의 출발·도착, 필수 신호, 필수 차선 변경, 사례 구성 비율(A3·B3·C4) |

구현: [설정 로더·사례 생성](../../../kcity/env/config.py), [경로·seed 검사기](../../../kcity/env/scenarios.py), [회귀 검사](../../../tests/test_kcity_scenarios.py)

## 시나리오

- **A:** `-68 → -13 → -71`. Lane 0, 5m, 2m/s로 출발해 `-71_0`의 28.55m에 도착합니다. 필수 신호는 647입니다.
- **B:** `-3#4 → -3#5 → -3#6 → -3#7 → -3#8 → -68`. `-68_0`의 69m에 도착합니다. 첫 Edge에서 다음 경로로 이어지는 차선은 Lane 1뿐이라 필수 차선 변경이 있습니다.
- **C:** 17개 Edge로 `3#4_0`의 63.11m에 도착합니다. B의 필수 차선 변경과 신호 647·268·764·169를 포함합니다.
- **도착 위치:** 각 마지막 Lane 길이에서 5m를 뺀 값입니다. 0.2m·0.3m의 짧은 Edge와 교차로 내부 Lane도 경로 연결 목록에 포함합니다.

## seed와 교통 요청

- **seed 생성:** 고정 정수 입력의 SHA256에서 구성요소별로 31비트 seed를 만듭니다. 그래서 전역 난수, 워커, 정책 생성 순서와 무관하게 같은 사례는 같은 seed를 갖습니다.
- **namespace 분리:** expert_train / expert_val / train / dev / final / archive / contract_check로 나뉩니다.
- **교통 요청:** Poisson 도착, 출발·도착 지점(OD), 차량 종류를 서로 다른 난수 흐름으로 만듭니다. 수요 배수를 바꾸면 도착 간격만 달라지고 OD와 차량 종류는 유지됩니다.

## 검사

```bash
python -B -m unittest discover -s tests -p test_kcity_scenarios.py -v
python -B kcity/env/scenarios.py --output /tmp/kcity-scenarios-check            # 계약·경로 검사 (output은 새 경로)
python -B kcity/env/scenarios.py --output /tmp/kcity-scenarios-smoke --smoke    # 배경 교통 없이 A/B/C 주행 확인
```
