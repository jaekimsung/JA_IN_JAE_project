# K-CITY 설정 확정 후속 작업

사용자 승인 범위: 추가seed pilot완료 → 결과집계 → 본실험 과학설정확정 → 기록/commit/push. 본 수집/학습은 시작하지 않는다.

요청 및 결정: REQUEST.json. 현재 상태: STATUS.json. 실행기: scripts/research/finalize_kcity_settings.py --wait --publish.

실행중 pilot의코드/config는수정하지않는다. 감독프로세스COMPLETE, seed22/33, 9개dev100정책의동일패널/데이터품질 및 checkpoint SHA를검사한다. 정책실패는분모에유지한다.

원래HEAD/입력파일변경·다른사용자수정·학습중단/오류·검사실패 시 REVIEW_REQUIRED로멈추고자동commit하지않는다. force push하지않는다.

완료뒤원격commit검증영수증: /home/heven/kcity_research_runs/KC-06-SEEDS-20261115-01/SETTINGS_PUBLICATION.json
