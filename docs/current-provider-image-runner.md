# 현재 원문 이미지 후보 실행

`scripts/run_current_provider_images.py`는 [현재 원문 이미지 감사](current-provider-image-audit.md)의 **NEVER_ATTEMPTED 후보만** 기존 `IMAGE_REFERENCE_MANIFEST` → `Queue.submit_image_batch` → `Worker` 경로로 순차 실행한다. `CURRENT_SOURCE_ONLY, legacy link not approved` 계약을 유지하며 source 조회·metadata 교정·legacy 연결·reader 재등록을 하지 않는다. 19개 기본 wave의 감사 출력이 입력 범위다. 별도 source-ID 후보 검증에는 자동 확대 적용하지 않는다.

## 입력 고정과 선행 확인

- `--summary-sha256`로 `summary.json`의 정확한 bytes를 고정한다. summary가 가리키는 모든 JSONL·후보 파일의 hash/size를 대조하고 후보 전체가 감사의 적격 미시도 위치와 정확히 일치하는지 검증한다. 일부 후보 누락·중복·500 URL 초과·다른 scope·FAILED 혼입·legacy 행 지정은 거절한다.
- 원래 현재 reader/원문과 완료 wave receipt도 `Records`와 기존 감사 검사로 다시 읽어 검증한다. 실제 실행용 source ID·URL·원 src/name/order 및 부모 hash를 원문 재파싱 결과와 대조한다.
- 실제 실행 전 URL별 `image_acquisitions`와 `image_acquisition_attempts`를 같은 읽기 전용 snapshot에서 재확인한다. 두 표에 모두 이력이 없는 URL만 실행 manifest에 담는다. 이미 취득·실패·SKIPPED 상태 또는 attempt만 있는 URL은 사유와 함께 제외한다.
- 원 감사 summary와 원 후보 bytes/hash를 별도 artifact로 그대로 등록하고, 필터한 실행 manifest는 원 후보를 parent로 연결한다. 반복 위치·원본 참조·제목/문맥 미확인 내역은 유지한다. 실행 선택은 `selection-NNN.json`과 동일한 불변 DB artifact로 남긴다.

## 실행·재개

각 실행은 최대 500 URL이며 `--max-batches` 기본값은 1이다. 이전에 완료된 job은 같은 ID/결과를 재사용하고 새 실행 한도를 소비하지 않는다. 동일 감사 SHA와 동일 출력 디렉터리로 재실행한다. 로컬 상태 파일만으로 완료를 인정하지 않으며 불변 artifact bytes와 실제 job 상태를 확인한다. 상태 파일은 임시 파일에서 no-overwrite 방식으로 설치한다.

job 제출 응답이 유실돼도 실행 manifest로 만든 같은 request key를 조회해 기존 job을 재사용한다. 부분 취득 후 중단됐으면 ACQUIRED는 worker의 기존 skip 경로를 사용하며 재다운로드하지 않는다. 매 worker 시도 직전에 ledger를 다시 확인한다. 중단된 job에 **FAILED·SKIPPED·기타 기존 시도** URL이 남아 있으면 `CURRENT_ONLY_PRIOR_ATTEMPT_REQUIRES_REVIEW`로 정지한다. 기존 downloader의 자동 job 재시도가 그 URL을 다시 요청하는 것을 막는 경계다. 이 경우 기존 job을 그대로 일반 worker로 재실행하지 말고 원인과 미처리 URL을 검토해야 한다. helper는 job 취소·payload 변경·실패 이력 삭제를 하지 않는다.

첫 URL의 decode FAILED가 이미 저장된 뒤, 뒤쪽 URL에서 OSError 등 worker 수준 예외가 발생하면 일반 Queue는 job을 재시도 대기(QUEUED)로 돌릴 수 있다. 이 helper는 다음 claim 전에 PAUSED로 멈추며 QUEUED job을 남긴다. 이를 전체 취득 성공이나 처리 완료로 표시하지 않는다. **이 상태에서 일반 worker를 재가동하면 helper의 guard를 우회한다.** 일반 worker를 중지한 상태 또는 runtime draining 상태로 유지하고, 기존 job/manifest/attempt·실패 응답을 보존한 운영 검토가 필요하다. 현재 Queue/CLI에는 job 취소나 일부 URL 제거 기능이 없으므로 자동 진행 절차는 제공하지 않는다. 기존 활성 job을 이력을 보존하며 종료하는 별도 운영자 queue 정리 결정을 먼저 해야 한다. 정리 후 새 감사에서 이력이 없는 URL만 새 manifest/job으로 처리할 수 있으며, 기존 FAILED의 재취득은 별도 검토 대상이다. 이 helper는 그 정리나 승인 결정을 대신 수행하지 않는다.

정상 SUCCEEDED job 안에서 발생한 개별 이미지 실패는 완료된 취득 시도의 결과로 보존하고 다음 배치로 진행한다. 터미널 FAILED job은 `CURRENT_ONLY_TERMINAL_JOB_FAILED`로 정지하며 새 job을 만들지 않는다. 다른 QUEUED/RUNNING job, 실행 중인 소유 lease, runtime draining을 확인하고 해당 경우 새 취득을 시작하지 않는다. 기존 단일 worker 운영 계약을 따르며 동시 별도 downloader 실행은 지원하지 않는다.

`run-<hash>.json` 및 `CURRENT_SOURCE_IMAGE_RUN` artifact에 batch 선택 수·사전 제외 수·job ID/상태·마지막 실행 checkpoint·현재 URL ledger 상태를 기록한다. checkpoint의 이번 시도 취득 수와 누적 URL 취득 수를 혼동하지 않는다. [재시도 지표](image-job-retry-metrics.md) 참조. 모든 source-only 취득 수는 legacy 이미지 연결 성공 수와 별도로 집계한다.

## 명령

아래는 준비된 실행 예시이며 구현 검증 중 실제 corpus 취득은 실행하지 않았다. 먼저 운영자가 검증한 감사 summary SHA를 고정한다.

```sh
cd backend
# 이 모드는 파일만 읽고 DB 설정을 로드하거나 출력 폴더를 만들지 않는다.
UV_PROJECT_ENVIRONMENT=.venv-reader uv run --no-sync python \
  ../scripts/run_current_provider_images.py \
  --audit-dir ../data/legacy-reader-scale-20260911-v1/current-images-audit-final \
  --summary-sha256 <검증한_summary_SHA256> --verify-input-only

# wave 종료 후 실제 실행. 재개도 같은 감사 SHA와 같은 출력 디렉터리를 사용한다.
KLEGAL_ENV_FILE=../.fordeploy/aws-backup/.env \
UV_PROJECT_ENVIRONMENT=.venv-reader uv run --no-sync python \
  ../scripts/run_current_provider_images.py \
  --audit-dir ../data/legacy-reader-scale-20260911-v1/current-images-audit-final \
  --summary-sha256 <검증한_summary_SHA256> \
  --data-dir ../data \
  --output-dir ../data/legacy-reader-scale-20260911-v1/current-images-acquisition \
  --max-batches 1
```

취득 후 새 출력 디렉터리로 감사를 다시 실행하고 `--verify-blobs`로 실물 hash/size/decode를 검증한다. 재감사 snapshot의 FAILED를 미시도 후보로 바꾸거나 source-only 취득을 legacy 연결 승인으로 올리지 않는다.

## 검증 기록 — 2026-09-11

새 helper 단위 회귀 17개와 PostgreSQL 통합 회귀 1개를 추가했다. 감사/wave 및 기존 부분 취득 재개 회귀를 합친 55개 테스트가 통과했고, ruff check/format와 mypy(core 55개 파일)도 통과했다. 통합 검증은 `korcounsel_test`의 임시 schema와 합성 fetcher에서 실제 Queue/Worker를 사용했다. 첫 URL decode 실패 응답/attempt를 보존한 뒤 둘째 URL의 합성 OSError로 job이 QUEUED에 남고, guard가 두 번째 claim 전에 PAUSED로 정지하는 것을 검증했다. 같은 helper를 재실행해도 job attempt 수 1·실패 응답·ledger·job 상태가 유지되고 추가 fetch가 없었다. 셋째 URL은 미요청이다.

실제 wave 1~9 감사 출력은 `--verify-input-only`로 2개 후보 manifest의 파일·scope·위치를 검증했다. 이 모드는 DB를 열거나 출력 폴더를 만들지 않았다. 구현 검증 중 실제 corpus DB 쓰기·외부 취득은 실행하지 않았다.
