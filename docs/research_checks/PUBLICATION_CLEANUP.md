# 2026-11-15 main 게시 전 산출물 정리

KC-01~05 작업은 로컬 `codex/kcity-kc01-20261114`의 `ef9b9e0`을 원본으로 보존하고, main에는 squash하여 통합한다. 코드·설정·테스트의 내용은 바꾸지 않았다.

- VS Code 편집기 상태/검색 DB는 Git에서 제외했다. 원래 작업 폴더의 DB는 C++ 도구가 사용 중이므로 로컬에서 유지한다. 1.59GB 파일이 원격 커밋에 들어가지 않는다.
- 중복 integration_v1/v2, early_probe, 실패한 임시 resume checkpoint, 중간 통과 로그를 저장소 밖 압축 보관으로 옮겼다.
- 최종 SUMMARY/RESULT·출처/최종 검사·핵심 실패 로그·재현에 쓰는 before source는 남겼다. 기존 최종 transitions.jsonl은 내용 SHA를 대조한 후 gzip으로 보관했다.
- 원본 docs/research_checks 전체344개 파일을 먼저 압축하고 각 파일 SHA256을 검증했다. 보관 위치는 `/home/heven/kcity_research_runs/publication_cleanup_20261115_01/`의 `research_checks_before_cleanup.tar.gz`, `MANIFEST.json`, `CLEANUP_PLAN.json`이다. 이 로컬 아카이브는 GitHub에 올리지 않는다.
- 이전 단계 README와 FINAL_CHECKS의 날짜/해시/파일 크기는 당시 원시 산출물 기준의 역사 기록이다. 삭제가 아니라 외부 보관으로 옮긴 중간 산출물은 위 아카이브에서 찾는다. 최종 trace는 같은 디렉터리의 `.jsonl.gz`를 사용한다.
- 실제602전이 dataset과 KC-04 검증 모델은 기존 `/home/heven/kcity_research_runs/` 경로에 유지한다. 본학습과 외부 데이터 업로드는 실행하지 않았다.

게시 전 검사: 실행 코드/설정/테스트는 원본 작업 커밋과 동일하며, 정리된 main 체크아웃에서100개 회귀 검사(45.561초)가 통과했다. 로컬 문서 링크303개와gzip 내용 SHA를 확인했다. 편집기 캐시를 제외한 게시 tree에는100MiB 초과 파일이 없다.
