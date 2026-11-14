# KC-01 첫 단계 실행 기록

> 2026-11-15 게시 정리: 중간 산출물은 [로컬 압축 보관](../PUBLICATION_CLEANUP.md)으로 옮겼으며, 최종 원시 trace는 `.jsonl.gz`로 압축했습니다. 아래 수치/해시는 검사 당시의 기록입니다.

상태: **완료(이 단계의 계약·경로 검사 범위)**. 다음 단계 KC-02 및 전체 G1 readiness는 미완료다.

## 식별과 범위

시작 HEAD `5e7a46cabab1ee7adb6baa06279ff59351f4b802`, 작업 브랜치 `codex/kcity-kc01-20261114`. 기존 미커밋 문서를 보존한 dirty tree에서 작업했다. [사전 provenance](PROVENANCE.json)에 시작 시각·기존 상태와 보호 파일 SHA256을 저장했다. 새 코드의 정확한 hash와 실제 검증 시각은 [최종 summary](validation_v2/SUMMARY.json)에 있다.

변경은 신규 `env/kcity_config.py`, `scripts/kcity/scenarios.py`, scripts package 표식, `configs/kcity/v1/`, 회귀 검사 및 진행 문서다. 기존 맵·고속도로·BC/PPO·과거 모델/자료는 수정하지 않았다.

## 결과

- [16개 회귀 검사](TESTS.log): 모두 통과. 경로 단절, 목표 위치 범위, TLS/link index, 필수 Lane 조건 누락, hash drift, 잘못된 시간 단위/입력, namespace·독립 RNG·서로 다른 프로세스 재현성을 검사했다.
- [최종 보존·문서·source 검사](FINAL_CHECKS.json): 기존676개 보호 파일의 변경0, 최신 smoke의 source hash 일치, 로컬 링크/문법/diff 검사 통과를 기록했다.
- A/B/C passenger route와 배경 coverage176개 route의 연결을 확인했다.
- B/C는 `-3#4_0` 출발이며 다음 `-3#5` 연결은 `-3#4_1`에서만 가능하다. B에서0.2m/0.3m 일반 Edge와5개 internal via 연결을 제거 없이 보존했다.
- 같은 C case의 360s 투입 요청 목록은 같은 SHA로 재생성됐고, 다른 case_index의 목록은 달랐다. 예시 목록58건은 **요청 수**이며 실제 출발·학습 전이 수가 아니다.

| 경로 | 실제 출발·도착 위치 일치 | 목적지 도착 | 필수 Lane 이동 | 종료 sim time | scope |
|---|---|---|---|---:|---|
| A | 통과 | 통과 | 해당 없음 | 33.9s | 신호 route smoke |
| B | 통과 | 통과 | Lane0→1 확인 | 24.6s | 필수 Lane route smoke |
| C | 통과 | 통과 | Lane0→1 확인 | 90.3s | 복합 route smoke |

세 case 모두 관측된 mode31/512, active program `assumed_actuated_v1`, collision/teleport 차량 ID0건이다. 이는 **배경차 없는 IDM 종방향+스크립트 Lane 요청 검사**다. 학습 AV 안전성, 정책의 신호 이해, 전문가 B0 성능, 실제 제어 adapter·교통 수요 수행 가능성 결과가 아니다.

## 명령과 원시 증거

저장소 루트에서 수행했다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p test_kcity_scenarios.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/kcity/scenarios.py --output docs/research_checks/KC-01-20261114-01/validation_v2 --smoke
```

[첫 실행](validation/SUMMARY.json) 이후 출발 실제값·제어 mode 일치·필수 Lane 조건 누락 거부를 더 엄격하게 검증해 [validation_v2](validation_v2/SUMMARY.json)에 새 결과를 남겼다. 경로/수요/물리 조건을 변경한 것은 아니다. 첫 회귀 검사에서 다른 설치의 scripts package와 import가 충돌했으며, 명시적 package 표식으로 해결했다. [실패 로그](TESTS.attempt01.log), [이전 통과 로그 보관 위치](../PUBLICATION_CLEANUP.md)도 삭제하지 않았다.

최종 각 case의 `A.result.json/B.result.json/C.result.json`, `A/B/C/trace.jsonl`, `tripinfo.xml`, `warnings.log`는 `validation_v2/` 아래에 있다. `CASE_C.json`과 `TRAFFIC_REQUESTS_C.json`은 seed·요청 재현 근거다. 정확한 subprocess argv와 wall time은 case result에 있다. 검증 stderr의 정상 TraCI 연결 retry와 실제 SUMO 경고를 구분한다.

## 미완료와 다음 행동

Gym reset/step·73-D·실제 교통 reset 재현·학습/전문가 수집·GAE/BC 초기화 수정·수요 pilot은 이번에 하지 않았다. **learning updates=0, expert dataset transitions=0, training_ready=false**다. 최종 연구 설정 동결도 하지 않았다.

다음은 KC-02: 이 계약을 읽어 별도 K-CITY Gym 환경을 구현하고, 여러 환경 연결 격리·5substep 사건·다중 Edge 진행·유한 Episode·관측/행동 계약을 작은 검사로 검증한다. 단계별 진행 요청에 따라 이번에는 KC-01 결과까지 기록하고 멈춘다.
