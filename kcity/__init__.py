"""K-CITY 자율주행 의사결정 연구 패키지.

common      SUMO 도구 탐색·맵 경로·JSON/XML 쓰기 헬퍼
env/        계약(config)·Gym 환경·73D 관측·경로·시나리오 검증
policy/     공통 BC/PPO 정책과 관측 정렬 규칙 전문가(B0)
training    BC·PPO 학습기, checkpoint bundle, 재개
data/       전문가/온라인 전이 수집, shard 기록·검증, 저장 codec
evaluator   Episode 지표와 사례 패널 평가
experiment  동결 과학 설정 guard와 본 수집·학습 실행기

이 패키지를 import해도 시뮬레이터를 시작하지 않는다.
"""
