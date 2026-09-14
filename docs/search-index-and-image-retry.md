# 검색 색인과 이미지 재취득 — 2026-09-14

## 관리자 실행

로그인한 관리자는 ‘신규 판례 증보’의 ‘검색 색인 관리’를 펼쳐 현재 기존 corpus 전체의 검색 색인을 구축한다. UUID request ID를 유지하며, 새로고침 후 같은 작업의 진행 행 수를 복구한다. 판례를 열거나 닫아도 색인 작업의 URL 식별자는 유지한다. 준비되지 않은 색인은 검색에서 사용하지 않는다. 이 명령은 신규 판례를 외부에서 수집하지 않으며 정기 실행을 만들지 않는다.

현재 수집 본문의 ‘이미지 재취득’은 그 revision에 보존된 제공자 주소로 미취득 파일을 다시 요청한다. 성공 파일은 재사용하고, 주소가 없는 위치는 미확보로 남긴다. 원래 위치를 임의로 바꾸거나 이미지 주소를 추측하지 않는다. 기존 조문 보강과 이미지 위치를 새 immutable reader에 계승한다. 성공 표시가 모든 이미지 확보를 뜻하지 않으므로 각 위치의 상태를 확인한다.

- `POST /api/admin/search-index`: `{request_id: UUID}`. 운영 설정의 `LEGACY_PARQUET_PATH`만 사용하며 임의 파일 경로를 받지 않는다.
- `POST /api/admin/readers/{document_id}/images`: `{request_id: UUID}`. CURRENT_SOURCE와 이미지 참조 존재를 확인한다.
- 두 endpoint 모두 인증된 관리자와 같은 Origin을 요구하고 queue의 종료 준비 정책을 따른다. 응답 유실은 같은 request ID로 확인한다.

## 검색 계약과 복구

migration 0014는 기존 `pg_trgm`을 이용하는 별도 projection과 두 job 종류를 추가한다. raw artifact·Parquet·기존 reader manifest는 변경하지 않는다. 색인 테이블은 재생성 가능한 파생 데이터이며 원본을 대체하지 않는다.

모든 원래 컬럼의 `_text` 규칙과 Python Unicode casefold를 적용한다. 컬럼별 위치 범위를 함께 저장해 컬럼 사이를 가로지르는 문자열 일치는 후보에서 제외한다. 원래 행 순서, 결과 한도, matched_columns 순서, 원행 locator, 본문 SHA-256을 기존 스캔과 동일하게 반환한다. SQL LIKE의 `%`, `_`, 역슬래시는 literal로 처리한다.

원본 경로·inode/device·크기·mtime/ctime ns·규칙 버전으로 snapshot key를 만든다. 구축 완료 전 전체 원본 SHA-256과 행 수를 확인하고 ready로 전환한다. 요청 시 파일 signature가 다르면 기존 색인을 쓰지 않는다. 파일 변경 감지는 운영 중 원본을 임의 변경하지 않는 계약에 더한 안전장치다. 원본을 정비한 경우 명시적으로 다시 구축한다.

row group 단위 transaction에 행과 다음 group을 함께 저장한다. 중단된 group은 rollback되고 완료 group부터 재개한다. 전체 ready 전에는 기존 Parquet scan이 계속 동작한다. 완료 후 일반 검색은 준비된 projection을 먼저 사용하고, 없거나 다른 파일이면 기존 scan으로 돌아간다. 기존 64개 결과 캐시도 fallback에 유지한다. CURRENT_SOURCE 최신 revision 선택은 기존 정책을 따른다.

이미지 명령은 `RETRY_CURRENT_IMAGES` coordinator가 immutable 참조 manifest, `ACQUIRE_IMAGE_BATCH`, `REFRESH_CURRENT_READER_IMAGES`를 idempotent하게 등록한다. coordinator 재실행은 같은 child job을 반환한다. UI는 coordinator의 `follow_up_job_id`를 따라 실제 reader 발급 완료까지 확인한다. 이미지 job의 terminal 상태를 확인하는 기존 queue 의존성 계약을 그대로 사용한다.

## 검증

실제 PostgreSQL 회귀는 검색 결과 동등성, Unicode·literal 특수문자, 컬럼 경계, 파일 교체, 부분 색인 미노출, 중단·재개·중복 방지, 이미지 실패 후 새 명령에서의 재취득을 포함한다. 전체 712개 회귀와 ruff·mypy·pnpm lint/build를 통과했다.

실제 이미지 표본은 `2009다47340`의 보강 reader에서 실행했다. coordinator `0801bca3-7e4a-4c25-976f-4fffdaaa6c25`, image job `f7905fe7-3d6a-4fad-87f2-4c0198de84cf`, refresh job `c41db502-4130-4fa7-9d5d-81c094eb075b`가 완료됐다. 새 reader `04751594fc5a4382ca0f9af3a15f36b096a8ec8d84a103da1e2897ed4db603d7`에서 이미지 4곳 실제 로딩과 주소 미확보 2곳 표시를 브라우저로 확인했다. 이 표본은 기존 성공 bytes 재사용이며, 실제 새 bytes 취득은 앞선 2024도8174 검증과 구분한다.

검색 전수 구축 job은 `e56a0e99-bedc-4555-9076-94b23d252d02`이며 실행 증거는 `data/search-index-audit-20260914/`에 보존한다. 89,130행 구축을 완료했고 모든 행의 본문 SHA-256·원래 행 위치를 원본과 전수 대조했다. 원본 파일 SHA-256은 `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`로 기존 manifest와 일치한다. projection 테이블과 색인은 합계 3,296,854,016바이트다. 구축 중 임시 GIN pending-list 설정은 기본값으로 복구했고 VACUUM ANALYZE를 완료했다.

최종 코드의 로컬 직접 조회 실측은 아래와 같다. 각 표본은 기존 스캔과 결과·순서·matched_columns·본문 hash가 모두 일치했다. 흔한 검색어는 처음 256행을 먼저 확인해 결과 한도를 채우며, 부족하면 나머지 행을 검색한다.

| 검색어 | 기존 스캔 | 색인 조회 | legacy 결과 수 |
| --- | ---: | ---: | ---: |
| 2024도8174 | 19.063초 | 0.019초 | 0 |
| 2009다47340 | 18.419초 | 0.019초 | 2 |
| 소유권 | 1.728초 | 0.041초 | 30 |

CURRENT_SOURCE까지 합친 일반 검색 API의 사건번호 표본은 앞선 실측에서 각각 0.091초/0.096초였다. 이는 로컬 표본 측정이며 모든 검색어의 응답 시간을 보장하지 않는다. 최종 배포 후 브라우저 일반 검색→최신 reader에서 저장 이미지 4곳 로딩·미확보 2곳·조문 4곳 계승을 재확인했다. 미인증 401·편집자 403도 검증했다. 증거 파일은 `full-row-check.json`, `verified.json`, `prefix-verified.json`, `image-retry.json`이다.

## 범위와 한계

검색 색인은 추가 DB 공간을 사용한다. 이전 snapshot은 자동 삭제하지 않는다. 아주 짧거나 흔한 검색어는 trigram 선택도가 낮을 수 있다. CURRENT_SOURCE 본문 색인과 50개 초과 URL 처리는 아래 후속 구현으로 확장했다. 기존 단일 배치 job의 한도 계약은 유지한다. 이미지 재취득은 저장된 주소 기준이며 현재 제공자 mapping을 다시 관찰하는 작업이나 legacy reader 재보강을 대신하지 않는다. 조문 내부 추가 이미지 취득은 [후속 구현](current-statute-images.md)에 연결했다. 다른 lawgo popup 형식은 후속 범위다.


## CURRENT_SOURCE 본문 색인·이미지 분할 — 2026-09-14 후속

migration 0015는 current_reader_search 파생 projection을 추가한다. 새 CURRENT_SOURCE reader를 불변 artifact로 저장한 뒤 제목·원문 HTML의 casefold 검색 문자열을 등록한다. 기존 reader와 artifact 등록 직후 중단된 누락분은 관리자 ‘검색 색인 구축’ job에서 채운다. 누락 행 자체가 재개 기준이며 원본·기존 manifest를 수정하지 않는다. 최신 source/root/revision을 먼저 선택한 뒤 제목 우선, 제목 일치가 없으면 본문 일치라는 기존 검색 계약을 적용한다. 최신 reader의 색인이 하나라도 없으면 기존 파일 검색으로 돌아간다. 색인이 준비되면 결과가 아닌 HTML 파일은 읽지 않는다. 보강 조문의 별도 payload까지 검색 범위를 확장하지는 않는다.

신규 수집과 새 관리자 이미지 재취득 명령은 all_urls 모드로 URL을 50개씩 처리한다. 각 URL 처리 후 image_next_url과 누적 성공·실패·bytes를 영속 checkpoint에 저장한다. 50개 배치가 끝나면 CHECKPOINTED로 큐에 돌아가며 worker 재시작 후 다음 URL부터 계속한다. 배치마다 bytes 상한을 새로 적용한다. 전체 URL 범위의 처리가 끝나거나 job이 최종 실패해야 후속 reader refresh가 실행된다. 개별 이미지 실패는 위치별로 남고 다른 URL 처리를 막지 않는다. 이미 등록된 단일 배치 job의 payload는 변경하지 않으므로 과거 한도 job에는 새 관리자 재취득 명령을 사용한다.

실제 PostgreSQL의 합성 103 URL 시험에서 50→100→103 재개, worker 교체, 후속 refresh 대기, 102개 성공·1개 실패, 원문 hash 불변을 확인했다. 이는 실제 제공자에게 103개를 다운로드한 실증과 구분한다. 검색 회귀는 최신 revision, Unicode casefold·literal 특수문자, 누락 색인 fallback·재구축, 검색 시 HTML 파일 미접근을 포함한다. 전체 Python/PostgreSQL 회귀 714건 통과.


로컬 관리자 웹에서 구축 job `f4c3c748-c61c-41f7-9f6f-582cd32b72ff`가 성공했고 CURRENT_SOURCE의 보존 revision 1,836개 모두 색인을 등록했다. 전수 HTML SHA-256과 title/html casefold 문자열 일치를 확인했다. `닭 날개` 본문 검색은 현재 판례 3건, 직접 색인 조회 0.0354초였으며 `2024도8174` 제목 검색은 1건·0.0197초였다. 없는 검색어는 0건·0.2568초였다. 이는 로컬 표본으로 일반 API 전체 응답 시간과 구분한다. 증거는 `data/search-index-audit-20260914/current-verified.json`에 보존했다.

일반 웹의 본문 문자열 검색→2009다47340 최신 reader에서 이미지 4곳 정상 로딩·미확보 2곳·조문 4곳을 확인했다. 미인증 검색·본문·색인 명령은 401이다. ruff format/check·mypy·전체 pytest 714건·pnpm lint/build·git diff --check 통과. 로컬 migration 0015와 API/worker/web 반영을 완료했으며 환경파일 변경·자동 schedule·commit/push는 하지 않았다.
