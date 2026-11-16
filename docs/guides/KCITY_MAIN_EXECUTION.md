# K-CITY 본 수집·학습 실행기

과학 설정은 [FROZEN_PROTOCOL.json](../../configs/kcity/main_v1/FROZEN_PROTOCOL.json)이다.
갱신: 2026-11-16. **운영 준비 검증 완료, 본 전문가 pool·본 BC·본 PPO 미시작**이다. 3seed pilot은 완료했다.
[최신 저장 최적화·준비 결과](../research_checks/KC-STORAGE-20261115-01/README.md)를 먼저 확인한다.

## 실행 범위와 보호 장치

- `main_experiment.py --check-only`: 설정·코드·예산 확인만 하고 output을 만들지 않는다.
- 실제 실행은 검증된 `--launch-record`가 있어야 한다. source/science SHA, owner lock, 현재 단계의 디스크 여유를 검사한다. 문서 개정은 명시적 호환 SHA에 등록하며 미등록 변경은 거부한다.
- 기존 KC01 환경 계약의 training flag는 비활성 상태로 보존한다. 별도 실행 계층이 frozen 명세와 운영 검증을 연결한다. 환경·보상·정책·PPO 수식은 바꾸지 않았다.
- Drive 업로드는 **사용자가 금지했다**. 원격 백업은 하지 않으며 완료로 표시하지 않는다. 과거 로컬 압축/readback은 수행했으나 압축본·raw probe는 후속 삭제 요청으로 제거했다. 현재 archive는 없고 새 백업도 만들지 않는다. 현재 준비 범위는 expert1M·BC·PPO6M이다. 최종평가/추가 archive3M은 후속 단계다.

## 이후 사용할 명령

다음 명령은 본 작업을 실행하므로 이번 준비 단계에서는 실행하지 않았다.
먼저 현재 공간을 확인하고, `LAUNCH_READY.json`의 실제 경로·source SHA·단계별 준비 상태를 확인한다.

```bash
cd /home/heven/Artificial-Intelligence-and-Control-for-Autonomous-Driving
KCPY=/home/heven/.cache/kcity-research-audit-20261110/venv/bin/python
KCRUN=/home/heven/kcity_research_runs/KC-MAIN-v1
KCREADY=/home/heven/kcity_research_runs/KC-STORAGE-20261115-01/preflight_final_v2/LAUNCH_READY.json

# 읽기 전용 확인: 수집/학습 없음
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B tools/main/main_experiment.py collect \
  --output "$KCRUN/expert" --check-only

# 1. 새 전문가 pool. 최소1M 전이를 채운 뒤 현재 Episode를 끝낸다.
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B tools/main/main_experiment.py collect \
  --output "$KCRUN/expert" --launch-record "$KCREADY"

# 2. raw 품질 검사 후 공통 BC fitting view를 고정한다.
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B tools/main/main_experiment.py views \
  --pool "$KCRUN/expert/dataset" --output "$KCRUN/bc_views" --launch-record "$KCREADY"

# 3. 본 BC: seed11 예시. 같은 명령을 별도 output·seed22/33으로 실행한다.
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B tools/main/main_experiment.py bc \
  --views "$KCRUN/bc_views" --seed 11 --device cuda --output "$KCRUN/bc_seed11" \
  --launch-record "$KCREADY"

# 4. 본 PPO: seed11 예시. B2/B3·각 seed를 새 output에서 각각1M까지 학습한다.
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B tools/main/main_experiment.py ppo \
  --method B2 --seed 11 --device cuda --output "$KCRUN/B2_seed11" --launch-record "$KCREADY"
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 "$KCPY" -B tools/main/main_experiment.py ppo \
  --method B3 --seed 11 --device cuda --bc-run "$KCRUN/bc_seed11" \
  --output "$KCRUN/B3_seed11" --launch-record "$KCREADY"
```

학습 seed11/22/33은 정책 초기화·행동/미니배치 난수이며 환경 seed와 분리된다.
모든 방법의 훈련 사례 순서는 공통 A/A/A/B/B/B/C/C/C/C이다. 사례 길이에 따라 같은 전이에서 소비한 사례 수는 달라질 수 있다.
새 main case index는0부터이며 pilot의1,000,000번대·운영 검증의3,000,000번대 자료를 이월하지 않는다.

## 수집·BC fitting view

원본은 성공/실패/unknown 모두 저장한다. 전문가 사례는 시나리오별 ordinal의 매5번째를 val에 사전 배정한다.
한 Episode·교통 seed group은 split을 넘지 않는다. Episode 수 비율80:20과 실제 전이 수 비율은 다를 수 있다.
정상 완주·지원 규칙 판정 통과·unknown 없음인 전체 Episode에서만 train200k/val50k unique-row view를 선택한다.
seed20261115로 비복원 추출한 동일 view를3개 학습 seed에 공유한다. 충분한 성공 행이 없으면 중단한다.
BC는 batch256·10k updates,500updates마다 MSE+CE 검증, 최저 val loss를 선택한다. 동률이면 먼저 나온 모델을 유지한다.
B1과 같은 seed의 B3는 이 선택 actor를 공유한다. B3의 PPO optimizer·critic head·std는 새로 시작한다.

## PPO 데이터·재개 일관성

기존 데이터 검사는 B0 source만 허용했다. `online_policy`가 명시된 경우에 한해 B2/B3·seed·행동 정책 hash·raw logprob·value를 추가 검증하도록 확장했다.
기존 B0 경로는 그대로다. 원래 frozen SHA와 확장 SHA의 관계는 [운영 호환 기록](../../configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json)에 남겼다.

PPO 전이마다 전체 before/next State·detected·0.1초 사건·NPZ와 학습 값을 논리적으로 보존한다.
새 JSONL 물리 형식은 `KC-NEXT-REF-v1`이다. 다음 행과 완전히 같은 next State/observation만 UID 참조로 저장한다.
Episode 종료 및 shard 마지막 행에는 next를 명시한다. `read_shard()`는 모든 필드를 원래 값으로 복원한다.
NPZ의 next_observation 등 필수 배열은 그대로 유지한다. 과거 full-next JSONL도 읽을 수 있다.

가중치/optimizer/RNG/부분 buffer/환경 replay bundle을 먼저 `transitions/checkpoints/`에 검증·확정한다.
그 경로·SHA·전이 수를 `transitions/shards/shard-*/environment/REFERENCE.json`에 기록한 뒤 데이터 shard를 atomic rename한다.
`checkpoint_from_shard()`로 실제 bundle 경로를 얻는다. 데이터와 모델의 확정 순서가 보장되어 crash 후 고유 전이 수와 복원 learner 카운터가 같다.
미확정 journal은 격리하며 중복 전이에 합산하지 않는다. 확정 전 남은 고아 모델·native partial은 다음 명시적 재개 시 이 실행 폴더 안에서만 정리한다.

PPO는 최신·직전·50k 간격 평가 모델을 유지한다. 최신/직전/평가 bundle SHA를 확인한 뒤 보관 대상이 아닌 새 모델만 제거한다.
데이터 shard와 그 SHA·UID는 수정하지 않는다. `CHECKPOINTS.json`과 `CHECKPOINT_RETENTION.jsonl`에 보관·정리 기록을 남긴다.
BC는 최신·직전·선택된 best(직전 재개 상태에 필요한 best 포함)를 유지하며 전체 loss 곡선은 보존한다.
기존 pilot/운영 검증 폴더에는 이 정책을 소급 적용하지 않았다.

과거 shard마다 참조된 bundle은 보관 정책에 따라 제거될 수 있다. latest/previous 및 평가용 bundle을 유지하며 모든 과거 shard에서 재개 가능하다고 주장하지 않는다.

각 rollout 완료와50k 평가 경계에서 데이터·모델 참조를 확정한다. 일반 rollout2048,50k 경계의 마지막 rollout은 짧게 자른다.
1M을 초과해 수집하지 않는다. 주최종 모델은 `COMPLETE.json`이 가리키는 budget-end bundle이다.
`curve.jsonl`, dev/T*/SUMMARY.json, SAMPLE_EFFICIENCY.json에 업데이트·평가 곡선·목표 전이 수를 기록한다.
최종평가 패널은 이 실행기에서 사용하지 않는다.

```bash
# 실행 output 안에 STOP을 생성하면 정상 저장 후 종료한다.
touch "$KCRUN/B2_seed11/STOP"

# STOP을 지운 뒤 원래 명령에 --resume을 추가한다.
rm "$KCRUN/B2_seed11/STOP"
```

SIGINT/SIGTERM도 같은 중단 경로를 사용한다. 부분 rollout에는 중단 때문에 추가 update를 넣지 않는다.
다만 STOP이 원래 rollout/평가 경계와 일치하면 연속 실행에서도 수행할 정상 update를 마친 뒤 저장한다.
살아 있는 owner의 lock을 빼앗거나 실행 중 source를 변경하지 않는다. 재개에는 같은 output/config/source/runtime가 필요하다.

## 검증 자료의 범위

GPU 재개 검사는 실제 pilot50k의 optimizer 이력을 **운영 검증에만** 읽었다. 본 초기값으로 사용하지 않는다.
400결정의 차선 유지 fixture로 긴 환경 replay 이력을 만들었고, 이 prefix는 learner 전이로 세지 않았다.
별도 fresh GPU 기록 검사는 실제 State와 학습/저장을 함께 실행했다. 이 자료도 source_stage=debug이며 본 pool·10M에서 제외한다.
검사 통과는 검증한 구간의 재현성이다. 장시간의 모든 운용 장애나 실제 도로 안전을 보증하지 않는다.

## 문서 개정과 검증의 계보

2026-11-16 개정은 과학 설정·73D·환경·정책·학습 수식/예산을 유지한다. 동결 당시 계약 문서3개는 기존 Git commit `ed12226`에 있으며 [호환 기록](../../configs/kcity/main_v1/OPERATIONAL_COMPATIBILITY.json)에 frozen/current SHA와 기준 commit을 명시했다. 해시 검사는 등록된 문서 버전만 허용한다.

준비 기록의 GPU 결과는 원래 source fingerprint와 검증 시각을 보존한다. 이번 문서 개정에서는 문서 호환 guard·check-only·학습 함수 불변을 다시 확인하고 그 범위만 별도 기록한다. 이번에 GPU 재학습을 수행한 것으로 표시하지 않는다. 최종평가/고정archive 실행기와 제출패키지는 후속이다.

## 폴더 재구성(layout revision 2, 2026-11-16)

코드를 기능별 패키지(`kcity/`, `rl/`, `tools/`, `legacy/highway/`)로 옮기고 FROZEN_PROTOCOL.json의 **경로·SHA만 다시 고정**했다. 수치·보상·예산·사례 패널·환경 계약은 그대로이며, guard는 `layout_revision.science_digest`로 과학 필드가 바뀌지 않았는지 매번 확인한다. 핀 파일 내용의 변경은 import·경로 줄뿐이다. 옛 경로와 새 경로의 대응, 파일별 이전/현재 SHA는 [LAYOUT_MIGRATION.json](../../configs/kcity/main_v1/LAYOUT_MIGRATION.json)에 기록했다. 재현 도구는 [refreeze_layout.py](../../tools/freeze/refreeze_layout.py)이다. 이전 운영 확장과 문서 개정 등록은 새 SHA에 포함됐고, 그 내용은 호환 기록의 `history`에 남겼다.

**위 `KCREADY`(KC-STORAGE preflight_final_v2)는 옛 경로의 운영 소스 SHA를 기록하고 있어 더 이상 통과하지 않는다.** 서버에서 새 commit을 받은 뒤 `tools/main/preflight_main.py`로 LAUNCH_READY를 다시 만들고, 그 경로를 `KCREADY`로 쓴다. 과거 pilot·운영 검증 bundle에 기록된 source 경로도 옛 경로이므로, 그 자료로 재개하지 않는다는 기존 원칙을 유지한다.
