# K-CITY 수집·학습·평가 실행 안내

갱신: 2026-11-16. 실험 설정은 [experiment.json](../../configs/kcity/experiment.json) 하나다. 3seed pilot은 완료했고, **본 전문가 pool·본 BC·본 PPO는 아직 시작하지 않았다.**

2026-11-16 코드 정리로 동결 guard(FROZEN_PROTOCOL·호환 기록·launch-record·preflight)는 제거했다. 실행 폴더는 `CONFIG.json`(실험 설정 digest 포함)이 같을 때만 `--resume`으로 이어지고, 코드 버전(git commit)·Python/torch/플랫폼은 STATUS·bundle·dataset에 기록만 한다. 이전 방식은 commit [fac8482](https://github.com/jaekimsung/JA_IN_JAE_project/tree/fac8482)에 있다.

## 실행 순서

저장소 루트에서 실행한다. SUMO 1.28.0이 필요하다.

```bash
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1
RUNS=/home/heven/kcity_research_runs/KC-MAIN-v1

# 1. 전문가(B0) pool: 워커 N개가 사례를 나눠 최소 1M 전이를 채운다 (nproc으로 코어 확인 후 N 결정).
python -B runner/collect.py --output "$RUNS/expert" --workers 8

# 2. 공통 BC view 고정 → BC 3 seed (seed11 예시; 22/33은 output만 바꿔 반복)
python -B runner/train_bc.py views --pool "$RUNS/expert" --workers 8 --output "$RUNS/bc_views"
python -B runner/train_bc.py train --views "$RUNS/bc_views" --seed 11 --output "$RUNS/bc_seed11"

# 3. PPO: B2/B3 × seed마다 정확히 1M
python -B runner/train_ppo.py --method B2 --seed 11 --output "$RUNS/B2_seed11"
python -B runner/train_ppo.py --method B3 --seed 11 --bc-run "$RUNS/bc_seed11" --output "$RUNS/B3_seed11"

# 4. 최종 평가: 고정된 budget-end 정책(COMPLETE.json의 checkpoint)만 final 패널에서
python -B runner/evaluate.py --policy <COMPLETE.json의 checkpoint> --panel final --output "$RUNS/eval/B3_seed11"

# 5. 영상과 Hugging Face 폴더 (업로드는 직접)
python -B runner/record_video.py --policy <bundle 또는 expert> --scenario C --video --once --output "$RUNS/video/B3_C"
python -B runner/export_hf.py --dataset "$RUNS/expert" --dataset "$RUNS/B3_seed11/transitions" --output "$RUNS/hf_export"
```

작은 확인 실행은 `collect.py --target 2000`, `evaluate.py --limit 3`처럼 규모를 줄인다. `evaluate.py`의 `--policy`는 `expert` 또는 learner bundle 폴더(`metadata.json`·`training.pt`·`SHA256.json`)다.

학습 seed11/22/33은 정책 초기화·행동/미니배치 난수이며 환경 seed와 분리된다. 모든 방법의 훈련 사례 순서는 공통 A/A/A/B/B/B/C/C/C/C이다. 사례 길이에 따라 같은 전이에서 소비한 사례 수는 달라질 수 있다. main case index는 0부터이며 pilot의 1,000,000번대·운영 검증의 3,000,000번대 자료를 이월하지 않는다.

## 병렬 수집

`runner/collect.py --workers N`은 사례 계획을 **10개 사례 주기(A/A/A/B/B/B/C/C/C/C) 단위로 round robin** 분할해 워커 N개에 나눈다. 모든 워커가 같은 3:3:4 시나리오 구성을 갖고, 각 사례는 순차 계획과 같은 교통 seed·train/val split을 유지한다. 워커마다 자기 SUMO·`ShardWriter`·재개 상태를 `<pool>/part-XX/`에 두고 `ceil(target/N)` 전이를 채운 뒤 현재 Episode를 마친다(합계는 목표를 조금 넘는다). 각 워커는 끝날 때 자기 part를 검증해 `QUALITY.json`을 남기고, coordinator가 모든 part가 끝나면 사례·Episode가 겹치지 않는지 확인해 `POOL.json`(합계·`pool_id`)을 쓴다.

```bash
python -B runner/collect.py --output "$RUNS/expert" --workers 8            # 진행률은 30초마다, 로그는 <pool>/logs/
touch "$RUNS/expert/STOP"                                                  # 모든 워커가 저장 후 종료
rm "$RUNS/expert/STOP"; python -B runner/collect.py --output "$RUNS/expert" --workers 8 --resume
# 여러 서버: 서버마다 part 하나씩 실행 → part-XX/를 한 폴더에 모은 뒤
python -B runner/collect.py --output "$RUNS/expert" --part 3 --parts 8
python -B runner/collect.py --output "$RUNS/expert" --finalize
```

BC view·HF 내보내기는 pool 폴더를 그대로 받는다. part 순서와 shard 순서가 고정되어 있어 view 추출은 재현된다. 워커가 남긴 검증 보고서는 `RELEASE.json`의 data_id가 같을 때만 재사용하며, `--revalidate`로 전체를 다시 검증할 수 있다. 워커 수는 재개할 때 바꾸지 않는다(사례 분할이 달라진다). 워커 하나는 Python·SUMO 프로세스 하나씩, 대략 CPU 1~1.5코어를 쓴다.

## 중단과 재개

```bash
touch "$RUNS/B2_seed11/STOP"      # 정상 저장 후 종료 (SIGINT/SIGTERM도 같은 경로)
rm "$RUNS/B2_seed11/STOP"; python -B runner/train_ppo.py --method B2 --seed 11 --output "$RUNS/B2_seed11" --resume
```

부분 rollout에는 중단 때문에 추가 update를 넣지 않는다. STOP이 원래 rollout/평가 경계와 일치하면 연속 실행에서도 수행할 정상 update를 마친 뒤 저장한다. 살아 있는 owner의 lock은 빼앗지 않는다. 재개는 현재 Episode를 같은 행동으로 다시 실행해 SUMO 상태를 복원하므로, 같은 SUMO 버전과 같은 환경 코드에서만 정확하다(불일치하면 replay 검사에서 거부된다).

## 수집·BC view

원본은 성공/실패/unknown 모두 저장한다. 전문가 사례는 시나리오별 ordinal의 매 5번째를 val에 사전 배정한다. 한 Episode·교통 seed group은 split을 넘지 않는다. Episode 수 비율 80:20과 실제 전이 수 비율은 다를 수 있다.

정상 완주·지원 규칙 판정 통과·unknown 없음인 전체 Episode에서만 train 200k / val 50k unique-row view를 선택한다. seed 20261115로 비복원 추출한 동일 view를 3개 학습 seed에 공유한다. 충분한 성공 행이 없으면 중단한다. BC는 batch 256·10k updates, 500 updates마다 MSE+CE 검증, 최저 val loss를 선택한다(동률이면 먼저 나온 모델). B1과 같은 seed의 B3는 이 선택 actor를 공유하고, B3의 PPO optimizer·critic head·std는 새로 시작한다.

## PPO 데이터와 learner checkpoint

PPO 전이마다 전체 before/next State·detected·0.1초 사건·NPZ와 학습 값(log prob, value, next value, 행동 정책 hash)을 같은 shard 형식으로 기록한다. JSONL 물리 형식은 `KC-NEXT-REF-v1`이다. 다음 행과 완전히 같은 next State/observation만 UID 참조로 저장하고, Episode 종료와 shard 마지막 행에는 next를 명시한다. `read_shard()`는 모든 필드를 원래 값으로 복원한다.

가중치/optimizer/RNG/부분 buffer/환경 replay bundle을 먼저 `transitions/checkpoints/`에 검증·확정하고, 그 경로·SHA·전이 수를 `shard-*/environment/REFERENCE.json`에 기록한 뒤 데이터 shard를 atomic rename한다. 그래서 crash 후 고유 전이 수와 복원된 learner 카운터가 같다. 미확정 journal은 `quarantine/`으로 격리하며 중복 전이에 합산하지 않는다(재생성 가능한 SQLite index는 격리하지 않고 다시 만든다).

PPO는 최신·직전·50k 간격 평가 모델을 유지하고 나머지 bundle만 제거한다(`CHECKPOINTS.json`, `CHECKPOINT_RETENTION.jsonl`). BC는 최신·직전·best를 유지한다. 각 rollout 완료와 50k 평가 경계에서 데이터·모델 참조를 확정하며, 일반 rollout은 2048, 50k 경계의 마지막 rollout은 짧게 자른다. 1M을 초과해 수집하지 않는다. 주 최종 모델은 `COMPLETE.json`이 가리키는 budget-end bundle이다. `curve.jsonl`, `dev/T*/SUMMARY.json`, `SAMPLE_EFFICIENCY.json`에 학습·평가 곡선과 목표 도달 전이 수를 기록한다. final 패널은 학습 중에 쓰지 않는다.

## 처리량

결정 1회는 SUMO 0.1초 × 5 substep이다. 시간의 대부분은 TraCI 조회이며, 2026-11-16 정리에서 내부 substep은 필요한 필드만 읽고 마지막 substep에서 전체 State를 한 번 찍도록 바꿨다. 같은 사례 8개(약 2,800 결정)에서 출력이 원본과 완전히 같았고 TraCI 호출은 결정당 3.5~4.2배 줄었다. pilot 당시 측정치는 약 25 전이/s였으며, 개선 후 서버 처리량은 다시 측정해야 한다.

## 검증 자료의 범위

pilot·운영 검증 자료(source_stage=debug)는 본 pool·10M에서 제외하고 본 초기값으로 쓰지 않는다. 검사 통과는 검증한 구간의 재현성이며, 장시간의 모든 운용 장애나 실제 도로 안전을 보증하지 않는다.
