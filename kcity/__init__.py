"""K-CITY 자율주행 연구 코드.

env/        실행환경: Gym 환경·73D 관측·경로·시나리오·환경 계약·SUMO 헬퍼
policy/     정책·알고리즘: 정책망·PPO·BC 학습기·버퍼/GAE·규칙 전문가 B0·checkpoint
training/   학습 코드: BC run·PPO run·dev 평가 곡선·실험 설정·실행 폴더/STOP 관리
data/       데이터: 수집·사례 계획·병렬 pool·shard 저장/검증·PPO 전이 기록
evaluation/ 평가: Episode 지표·사례 패널 평가

import만으로 SUMO를 시작하지 않는다.
"""
