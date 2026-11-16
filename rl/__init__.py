# rl 패키지: K-CITY 연구와 레거시 고속도로 예제가 함께 쓰는 학습 부품.
#
#   ppo.py       : PPO (연속 Gaussian / 하이브리드 가속+차선 행동)
#   bc.py        : 레거시 예제용 BC 정책
#   networks.py  : 신경망 빌더 (MLP, GaussianActorCritic, HybridActorCritic)
#   buffer.py    : 경험 버퍼 (RolloutBuffer / ReplayBuffer)
#   evaluator.py : 레거시 정책 평가 + 주행지표 집계 (ppo.py 기본 평가 함수)
#   logger.py    : 콘솔 / TensorBoard / CSV 로깅
#
# 새 알고리즘은 ppo.py와 같은 인터페이스(act, predict, train, save, load)로 추가한다.
