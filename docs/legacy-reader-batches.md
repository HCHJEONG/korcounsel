# 기존 corpus reader 배치 처리 계약

기존 89,130행 전수 확대는 `STAGE_LEGACY_READER_BATCH` 작업으로 나눠 실행한다. 한 작업은 1~100개의 명시적인 행 position을 처리한다. 판례 원문·기존 revision·기존 이미지 취득 기록을 덮어쓰지 않는다.

## 입력과 실행

`Queue.submit_legacy_reader_batch(request_key, manifest_artifact_id)`로 이미 보존한 JSON artifact를 등록한다. 필수 입력은 다음과 같다.

```json
{
  "version": "legacy-reader-batch-1",
  "parquet_sha256": "실제 Parquet 파일의 SHA-256",
  "snapshot_sha256": "Parquet legacy metadata의 원래 snapshot SHA-256",
  "positions": [0, 1, 2],
  "current_readers": {}
}
```

`current_readers`는 문자열 position을 현재 제공 본문 reader revision에 연결한다. 선택적인 `acquisition_revision`은 취득 상태 관측을 식별하는 SHA-256, `retry_generation`은 명시적인 재시도 세대인 0 이상의 정수다. 입력 artifact가 이 관측·재시도 구분을 보존한다. 동일 request key와 입력은 기존 작업을 반환하며 다른 입력은 충돌한다.

Worker는 설정된 `LEGACY_PARQUET_PATH`를 읽는다. 최초 실행 및 파일 변경 감지 시 전체 bytes의 SHA-256을 계산하고, 매 배치마다 snapshot metadata를 대조한다. 하나의 Worker 인스턴스를 계속 사용하면 검증한 파일의 device/inode/size/mtime/ctime과 SHA-256을 기억하여 불필요한 전체 해싱을 반복하지 않는다. 프로세스가 재시작되면 다시 전체를 해싱한다. 읽는 중 파일이 바뀌면 등록을 중단한다.

Migration 0011은 작업 종류·결과 manifest 종류·행별 ledger와 reader 조회 index를 추가한다. 원래 corpus import나 canonical registry를 변경하지 않는다.

## 행별 재개와 실패

`legacy_reader_batch_rows`는 job ID와 원래 position별로 `STAGED` 또는 `FAILED`, reader artifact, 집계와 오류 코드를 보존한다. 입력 HTML이 없는 행, 현재 본문과의 식별 불일치 등은 실패 행으로 남고 다음 행으로 진행한다. `STAGED`는 reader 보존 상태이며 전체 이미지 취득·조문 적용 버전 확인을 뜻하지 않는다.

각 행의 ledger 반영 시 유효한 worker lease를 확인한다. 중단·drain은 다음 checkpoint에서 멈추고 이미 보존한 행을 재사용한다. 재개한 완료 행에서도 reader·부모 HTML·연결된 이미지·조문 artifact의 무결성을 재확인한다. 실패 행을 다시 시도하려면 새 요청/입력 세대를 사용한다. 기존 실패 이력은 남는다.

`job.checkpoint.result_manifest`의 결과 artifact는 입력 manifest, snapshot/Parquet hash, 행별 결과, staged/failed 수와 download manifest를 담는다. 배치 작업이 SUCCEEDED여도 개별 실패 행이나 미취득 이미지가 있을 수 있다.

## 기존 보강의 유지

현재 본문 mapping이 없는 행은 같은 snapshot+position+본문 hash의 기존 reader revision을 재사용한다. mapping을 제공해 새 revision을 만들 때도 과거에 검증하여 연결한 이미지 bytes를 새 미확정/실패 상태로 지우지 않는다. 이전 위치와 연결 근거를 새 revision에 그대로 유지하고, 이전 revision 역시 불변으로 남긴다.

이미지 취득은 별도의 `ACQUIRE_IMAGE_BATCH` 작업이다. 대기 manifest는 원래 reader reference ID와 occurrence order/row position을 보존한다. 다운로드 ledger의 reference ID는 manifest hash에 따라 별도로 생성하므로 다른 배치나 재시도의 관찰을 기존 manifest로 잘못 귀속하지 않는다.

현재 scourt 본문과의 연결은 기존 `image-context-link-1` 규칙을 그대로 사용한다. 역사적 이미지 bytes의 동일성을 확정하지 않는다.

## 대량 저장과 검증

한 판례의 HTML·중복 제거한 조문 payload·reader manifest는 하나의 PostgreSQL transaction으로 저장한다. artifact ID를 일괄 조회하고 없는 항목만 삽입하며, 존재하는 artifact는 metadata·부모·hash와 실제 bytes를 확인한다. 이미 있는 CAS 파일은 검증 후 재사용하여 중복 temporary write/fsync를 피한다.

관련 actual PostgreSQL 회귀는 배치 행별 실패/재실행, hash 불일치·파일 변경, stop/drain 후 재개, lease 상실, 기존 이미지 연결 유지, 다운로드 참조 namespace와 occurrence 보존, artifact 일괄 저장의 원자성·손상 검출을 검증한다. 실제 public corpus의 실행 집계와 화면 결과는 별도 전수 실행 보고서에 기록한다.


reader handler는 배치 실행 기간에만 thread-local 연결 하나를 재사용한다. connect()별 transaction은 독립적으로 commit/rollback하고 중첩 connect()는 별도 연결을 사용한다. 다른 스레드의 API와 다른 worker handler의 연결 정책을 바꾸지 않는다. 큰 본문·표·조문 링크 점검과 집계 한계는 [독립 QA](legacy-reader-scale-qa.md)에 기록했다.


## 조문 이미지 포함 coverage verifier

scripts/verify_legacy_reader_coverage.py의 legacy-reader-coverage-2는 --statute-image-audit로 독립된 조문 이미지 전수 결과를 받는다. 감사 입력의 Parquet/snapshot hash·행수와 부모 조문 위치를 확인하고, reader의 payload를 다시 관측한 img 목록과 대조한다. 실제 전수 감사는 651행·4,698개 등장 위치이며 57·124행의 v3 참조가 각각 6곳으로 정확히 대응함을 DB 접근 없이 확인했다.

sidecar는 statute_image_occurrences, acquired_statute_images, unacquired_statute_images, missing_statute_image_references, statute_image_coverage_status를 추가한다. v2 manifest의 기본 등록 상태는 유지하면서 조문 이미지가 있는 행은 MISSING_REFERENCES로 구분한다. v3는 REFERENCES_VERIFIED 또는 NO_IMAGES를 기록하며 article_order·article_reference_id·payload hash·parent body hash·원래 태그/위치와 취득 status/hash/URL 및 metadata count를 확인한다.

--verify-blobs는 조문 이미지 파일의 실제 SHA-256과 decode도 검사한다. complete_reader_registration은 기존 기본 reader 보존 상태이고, complete_statute_image_reference_coverage는 조문 이미지 참조 연결 상태다. all_observed_images_acquired는 본문과 조문 이미지를 모두 계산한다. 참조 보존·bytes 취득·일반 검색 화면 검증은 별개다.

기존 coverage 회귀 4개와 조문 이미지 관련 회귀 7개를 통과했다. 원본 audit와 manifest의 위치 누락·교차 article/payload·손상 bytes·취득 hash 불일치를 검증했다. 실제 public DB 전수 verifier 실행은 이 코드 검증에 포함되지 않는다.


v3 재개 시에는 공유 manifest version 검사와 실제 부모 HTML에서의 조문/image 위치 재추출 대조도 수행한다. 취득된 조문 이미지는 status·URL·SHA-256 계약과 파일 bytes/decode를 함께 확인한다. 동일한 취득 증거가 여러 인용 위치에서 반복되면 검증 결과를 해당 호출 안에서 재사용한다. 기본 이미지 재처리도 기존 v3 statute_images를 계승한다. 실제 PostgreSQL 회귀 15개에서 양방향 보강 계승, checkpoint 후 조문 이미지 파일 손상으로 다음 행 진행 차단, 복구 후 재개 및 잘못된 article/취득 URL/버전 거절을 확인했다.
