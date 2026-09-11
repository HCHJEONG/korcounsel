# 현재 공식 원문 이미지 보존 감사

`scripts/audit_current_provider_images.py`는 완료된 scourt wave가 보존한 현재 원문 이미지의 취득 상태를 읽기 전용으로 점검한다. `CURRENT_SOURCE_ONLY, legacy link not approved` 계약이며, 현재 이미지 실물 보존과 과거 판례 본문 연결 승인은 별개다. 제목·문맥 불일치로 legacy 연결이 거절된 원문도 이미지 참조를 제외하지 않는다.

## 입력과 검증

- `--waves-dir` 아래 `wave-001` 등에서 `--start-wave`부터 `--end-wave`까지 연속 범위를 선택한다(1~19). 각 디렉터리의 `wave-<hash>.json`에 대응하는 등록 artifact를 조회하고 DB `created_at`, artifact ID 순 최신 receipt를 선택한다. 최신 receipt가 미완료면 과거 완료본으로 우회하지 않고 실패한다. 로컬에 없는 DB receipt를 탐색하지 않으므로 wave 실행에 사용한 원래 전체 디렉터리를 지정한다.
- 실제 불변 receipt bytes·SHA-256·metadata kind·로컬 내용·wave 번호·완료 상태·공통 inventory/targets hash를 대조한다. wave 사이 행 중복과 source 결과/current reader 연결 불일치를 거절한다.
- current reader는 ID별 한 번 검사하고 원래 wave/legacy 행 연결을 모두 남긴다. `ReaderStore`와 `Records`로 manifest와 원문 파일 hash·size를 검증한다. `image-reader-1`, `enriched-reader-2`, `enriched-reader-3`의 현재 원문을 지원하며 모두 같은 이미지 위치 검증을 통과해야 한다.
- 기존 `image_occurrences`로 원문을 다시 파싱해 전체 이미지 수·순서·부모 hash·원태그·src/name·문맥·제공자 매핑이 manifest와 정확히 일치하는지 확인한다. 같은 URL이 반복된 위치를 합치지 않는다.
- URL 후보는 기존 `valid_image_url`을 통과하고 scourt endpoint의 source ID 및 파일명이 현재 원문에서 관찰한 단일 provider mapping과 정확히 일치해야 한다. 추가 query, 중복 parameter, fragment 또는 모호한 매핑은 후보에서 제외하고 사유를 남긴다. URL을 추측·교정하지 않는다.
- 하나의 PostgreSQL `REPEATABLE READ, READ ONLY` transaction에서 receipt, reader, acquisition 및 attempt 상태를 읽는다. 기존 job·reader·DB·원본은 변경하지 않으며 source 요청과 다운로드도 하지 않는다.

## 분류와 출력

`NEVER_ATTEMPTED`는 URL에 acquisition 행과 attempt 행이 모두 없는 경우다. `ACQUIRED`, `FAILED`, `OTHER`를 따로 집계하며 acquisition 행 없이 attempt만 남은 경우와 `SKIPPED`도 OTHER다. 분류와 별도로 URL/제공자 매핑 적합성을 남긴다. 취득 실패를 원문 소실로 단정하지 않는다.

출력 디렉터리는 새 경로여야 한다. `references.jsonl`은 모든 등장 위치와 원참조·부모 reader/원문 artifact/hash·원 src/name/order/URL·매핑·취득 snapshot·legacy 연결 결과를 담는다. `parents.jsonl`은 제목·출처·provenance와 모든 원래 연결을 담는다. `summary.json`은 범위·receipt·분류별 건수·출력 hash/size·검증 범위를 기록한다. 검증 중 오류가 생기면 완료 보고서를 만들지 않으며 파일 출력 중 실패하면 `.partial-*` 디렉터리가 남을 수 있다. 기존 출력은 덮어쓰지 않는다.

`--verify-blobs`를 주면 ACQUIRED의 고유 blob마다 FileStore SHA/size 검증과 기존 `validate_image`의 실제 decode를 수행한다. 결과는 `verified-blobs.jsonl`에 남기며 하나라도 실패하면 감사가 실패한다. 옵션이 없으면 ACQUIRED는 ledger 상태 확인만 뜻한다.

`--write-manifests`는 **유효한 매핑의 NEVER_ATTEMPTED 참조만** URL당 최대 500개 단위의 `never-attempted-001.json` 등에 담는다. 반복 위치는 모두 보존한다. 기존 worker가 읽을 수 있는 `IMAGE_REFERENCE_MANIFEST` payload이나 artifact 등록·job 제출은 하지 않는다. `row_position`은 null이며 legacy 위치는 context에만 담는다. `legacy_link_approved=false`를 유지한다. 원위치 reference ID는 `original_reference_id`로 보존하고 실제 ledger reference ID는 기존 파서의 manifest hash 포함 생성에 맡겨 재감사 manifest의 이력을 구분한다.

후속 실행자는 후보 파일 hash를 summary와 대조하고 등록·bounded worker 실행을 별도로 수행한다. snapshot 이후 취득 상태가 바뀔 수 있으므로 이 파일 자체를 최신 상태나 재시도 승인으로 취급하지 않는다. FAILED는 never-attempted 후보에 자동 합류하지 않는다. 신규 취득을 legacy 연결 성공 건수로 계산하지 않는다.

## 로컬 실행 예시

backend에서 명시적 환경파일을 선택하고, 실제 로컬 blob 경로를 지정한다. 아래 환경파일 값은 출력하지 않는다. 출력 이름은 실행마다 새로 정한다.

```sh
cd backend
KLEGAL_ENV_FILE=../.fordeploy/aws-backup/.env \
UV_PROJECT_ENVIRONMENT=.venv-reader uv run --no-sync python \
  ../scripts/audit_current_provider_images.py \
  --waves-dir ../data/legacy-reader-scale-20260911-v1/scourt-image-waves \
  --start-wave 1 --end-wave 19 --data-dir ../data \
  --output-dir ../data/legacy-reader-scale-20260911-v1/current-images-audit-final \
  --verify-blobs --write-manifests
```

wave 19가 완료되지 않았으면 이 명령은 실패한다. `--data-dir` 생략 시 설정의 data_dir를 사용하므로 Compose용 경로와 호스트 경로를 혼동하지 않는다. 실제 실행 범위·검증 결과는 해당 summary를 따른다.

## 검증 기록 — 2026-09-11

단위 경계 회귀 21개와 기존 wave 회귀 15개, ruff check/format 및 mypy(55개 core 소스)가 통과했다. 실제 wave 1~9의 08:17:44 UTC snapshot에서 reader 893개·이미지 5,229위치·URL 4,048개를 검증했다. ACQUIRED 3,146 URL에 연결된 고유 파일 2,476개는 모두 hash·size·decode 검증을 통과했다. NEVER_ATTEMPTED 823 URL/926위치는 500 URL와 323 URL의 후보 파일로 나눴고 FAILED 79 URL/119위치, URL 미확정 16위치는 별도로 보존했다.

실제 결과는 `data/legacy-reader-scale-20260911-v1/current-provider-image-audit-tool-waves1-9/summary.json`과 연결된 JSONL·후보 manifest에 있다. 출력 파일 5개의 checksum도 summary와 일치했다. 이 실행은 실제 다운로드나 job 등록을 하지 않았으며 wave 10~19 검증 완료를 뜻하지 않는다.
