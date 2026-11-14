# KC-01 시나리오·시드 계약

이 디렉터리는 2026-11-14 첫 구현 단계의 **검사된 geometry/seed/control 계약**이다. 학습용 최종 설정이 아니다. `training.enabled=false`, `research_settings_frozen=false`를 유지한다.

- [protocol.json](protocol.json): SUMO1.28.0·맵/신호/경로 hash, 0.1/0.5 s 시간 단위, 후보 제어/수요, 독립 seed namespace.
- [scenarios.json](scenarios.json): A 신호 교차로, B 필수 차선 변경, C 복합 경로의 유한 출발/도착과 연결 조건.
- 구현: [설정 로더·요청 생성](../../../env/kcity_config.py), [구조/경로 검사기](../../../scripts/kcity/scenarios.py), [회귀 검사](../../../tests/test_kcity_scenarios.py).

위 구현 링크는 저장소 루트 기준 파일이다. 전체 진행은 [연구 현황](../../../docs/RESEARCH_STATUS.md)을 따른다.

## 실행

저장소 루트에서 실행한다. 원본 맵을 재생성하지 않으며, output은 **존재하지 않는 새 경로**여야 한다. SUMO tools는 기존 검색 함수를 사용하며 이 단계에 Gymnasium·Torch·CUDA는 필요하지 않다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p test_kcity_scenarios.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/kcity/scenarios.py --output /tmp/kcity-kc01-new-check
# 추가로 3개 유한 경로를 SUMO에서 검사할 때만:
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/kcity/scenarios.py --output /tmp/kcity-kc01-new-smoke --smoke
```

`SUMMARY.json`, case 설정, 투입 **요청** 목록을 출력한다. `--smoke`는 배경 교통 없이 IDM 종방향 제어와 초기에 한 번 발행하는 필수 Lane 명령으로 A/B/C를 검사한다. 신호·안전 mode 31/512와 실제 출발/도착 위치를 확인한다. 학습 정책·관측 정렬 전문가 B0·Gym lifecycle·73-D 관측·setAcceleration adapter를 구현하거나 평가한 실행은 아니다.

## 결정한 세부 사항

- A: `-68 → -13 → -71`, 출발 Lane0/5m/2m/s, 도착 `-71_0`의28.55m, 필수 신호647.
- B: `-3#4 → -3#5 → -3#6 → -3#7 → -3#8 → -68`, 출발 Lane0/5m/2m/s, 도착 `-68_0`의69m. 첫 Edge의 다음 연결은 Lane1만 허용된다.
- C: qualifier17개 Edge, 같은 Lane0 출발 조건, 도착 `3#4_0`의63.11m. B의 필수 Lane 확보와 신호647/268/764/169를 포함한다.
- 도착 위치는 각 마지막 Lane 길이에서5m를 뺀 값이다. 자동으로 잘못된 값을 clip하지 않고 벗어나면 validator가 거부한다.
- 0.2m·0.3m Edge와 internal via Lane을 정적 연결 목록에 보존한다. 0.1s 샘플 trace는 매우 짧은 Edge의 점유를 놓칠 수 있다. 이후 KC-02의 진행/이벤트 추적은 route index 변화까지 반영해야 한다.
- seed는 고정 정수 입력의 SHA256에서 component별31bit 정수로 파생한다. NumPy 의존 없이 전역 RNG·worker·policy 생성 순서와 분리하기 위한 선택이며, 앞서 예시로 든 SeedSequence와 값이 같은 알고리즘은 아니다. 알고리즘 ID를 명시했으며 source/Python 버전과 함께 고정한다.
- namespace는 expert_train/expert_val/train/dev/final/archive/contract_check로 분리한다. 같은 환경 case는 method/worker와 무관하다. paired 학습 seed별 case_index 할당은 KC-02 실행 manifest에서 정한다.
- Poisson arrivals·OD·vType을 서로 다른 RNG stream으로 생성한다. 수요 배수가 바뀌면 도착 요청 시간 간격을 조정하고 OD/type stream은 유지한다. 저장된 목록은 실제 SUMO departure/밀도/유효 학습 데이터가 아니다.

## 다음 단계

KC-02에서 연결별 실제 진행/정지선 사건, 독립 TraCI 환경, 같은 seed의 **실제 초기 교통 상태**, 관측·행동·종료를 구현한다. 현재 요청 목록의 결정성을 실제 환경 reset 결정성으로 확대하지 않는다. 기본 λ0=600·73-D·보상·제어 후보는 pilot 이후 최종 동결한다.
