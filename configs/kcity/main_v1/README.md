# K-CITY 본 실험 과학 설정

FROZEN_PROTOCOL.json은 본 실험 설계 확정본이다. scientific_settings_frozen=true와 training_enabled=false / launch_ready=false는 서로 다른 상태다. 기존 KC01 loader에 바로 넘기지 않는다. 운영 실행기 연결은 다음 단계다.

cases_dev.json / cases_final.json은 생성만 한 고정 패널이며, final 실행 결과가 아니다. 관측/보상 코드와 맵은 SHA로 참조하고 기존 v1 파일은 변경하지 않았다.
