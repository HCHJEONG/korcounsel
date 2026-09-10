# PostgreSQL 저장·migration·worker — Step 2A

2026-09-10. Step 2A의 로컬 persistence와 실제 단일 worker를 구현했다. 전체 corpus import, source adapter, 로그인 HTTP 흐름, AWS 운영 변경은 별도다.

## 선택과 경계

- PostgreSQL 17 + 기존 lockfile의 Psycopg 3.3.5를 유지한다. ORM은 추가하지 않는다.
- `db/migrate.py`의 작은 번호순 SQL 실행기를 사용한다. SQL은 backend/migrations/에 둔다. migration 실행기 계약은 `numbered-sql-1`이며 별도 dependency는 없다.
- 파일명 순서·적용 checksum·연속성을 확인하고 transaction advisory lock으로 동시 실행을 직렬화한다. 한 호출의 미적용 migration은 하나의 트랜잭션으로 적용된다. 실패 시 그 호출 전체가 rollback된다.
- 적용 SQL은 수정하지 않는다. 후속 변경은 새 번호로 추가한다. 자동 downgrade/reset은 제공하지 않으며 기존 schema가 더 최신이거나 checksum이 달라지면 중단한다.
- API·worker 시작이 migration을 수행하지 않는다. 관리자가 명시적으로 migration을 실행한 뒤 서비스를 시작한다.
- Domain은 PostgreSQL/Psycopg를 import하지 않는다. `db/`는 SQL, `storage/`는 파일, `jobs/`는 처리, `operations.py`는 로컬 관리 명령이다.
- 연결은 작업 단위로 열고 트랜잭션 후 닫는다. 상시 대규모 pool은 없다. 연결 5초, statement 30초, lock 대기 5초 제한을 사용한다. 정상 worker는 하나이며 통합 테스트의 동시성은 격리된 schema에만 적용한다.

공식 근거: [PostgreSQL 잠금](https://www.postgresql.org/docs/17/explicit-locking.html), [SELECT와 SKIP LOCKED](https://www.postgresql.org/docs/17/sql-select.html), [Psycopg 트랜잭션](https://www.psycopg.org/psycopg3/docs/basic/transactions.html). 처음부터 복잡한 workflow engine이나 다수 worker를 도입하지 않는다.

## 저장 대상

| 테이블 묶음 | 저장 기준 |
| --- | --- |
| app_users / app_sessions | scrypt password hash와 session token SHA-256만 저장. 계정 자동 seed 없음 |
| blobs / artifacts | SHA-256·크기·상대 저장키·origin·부모·metadata. 파일은 DATA_DIR에 보존 |
| source_versions / source_receipts | HTTP 원본 내용 버전과 각 취득 관찰을 분리. source ID+raw hash가 버전키 |
| documents / document_revisions | 개별 결정 문서의 현재 연결 revision과 이전 전체 identity |
| case_keys / document_case_keys | 법원+전체 사건번호 업무키와 문서 revision의 관계. 하나의 사건에 여러 문서 허용 |
| active_source_links / identity_events | 활성 source key UNIQUE, 이전/이후 연결·사유·actor 이력 |
| legacy_records / legacy_import_attempts | snapshot+행 locator·coverage·content revision·artifact와 실행별 보존/격리 이력 |
| case_projection | artifact에서 재구성 가능한 조회 정보. 사용자/작업/식별 이력과 별도 |
| inventories / manifests | 완전성·범위와 versioned inventory/registry/dataset/asset/import 파일 참조 |
| jobs / job_attempts / job_events | 요청 identity, 실행 상태, 각 시도·소유권·checkpoint·오류 코드 |
| projection_rebuild_inputs | 재생성 요청 시점의 입력 artifact/revision 목록. 작업 도중 추가된 자료와 분리 |
| work_items / work_item_attempts | FETCH/ASSET/ENRICHMENT 항목·입력/규칙 버전·target별 관찰과 실패 이력 |
| runtime_control / worker_instances | 종료 준비와 실제 worker heartbeat |

history 테이블의 UPDATE/DELETE는 trigger로 거부한다. DB 관리자 권한으로 강제로 바꾸는 행위를 방지하는 별도 보안 체계라는 뜻은 아니다. 사용자·세션·현재 연결·작업의 진행 상태는 필요한 범위에서 변경 가능하고 이전 확정 자료와 완료 시도는 보존한다.

## Canonical registry와 legacy

Registry.apply는 IdentityLinkEvent를 받아 현재 revision과 previous payload를 대조한 뒤 트랜잭션으로 반영한다. 동일 event ID와 같은 내용은 재사용하며 다른 내용은 거부한다. 새로운 ID와 충돌하는 source 연결은 전체 이벤트를 rollback한다.

MERGE/SPLIT/RELINK 후에도 document_revisions와 events는 남는다. 은퇴한 대표값을 신규 문서에 재발급하지 않는다. registry snapshot은 DB 삽입 순서의 전체 이벤트를 보존하며 restore는 빈 registry 또는 동일 이벤트 prefix에서 재개할 수 있다. 관계없는 기존 history 위에 덮어 복원하지 않는다. snapshot은 Records.save_manifest로 별도 불변 파일로 저장할 수 있다.

LegacyCaseRecord 저장은 registry 확정과 별개다. 두 공식 ID가 함께 있다고 active_source_links에 자동 등록하지 않는다. 원행·숫자 0·empty·날짜 객체 표기·UNKNOWN provenance는 원모델 그대로 파일에 보존한다. 재실행 시 imported_at만 달라졌다면 최초 artifact를 재사용하고 새 run의 시도 이력만 추가한다.

PRESERVED는 보존 완료이며 법률적 승인이나 GOLD 승격이 아니다. QUARANTINED도 원행 artifact를 유지한다. 전체 FULL_ROW importer의 실패 분류·건수 reconciliation·배치 resume은 후속 import 작업에서 연결한다.

## 파일·DB 실패 복구

FileStore는 bytes hash로 `blobs/<앞 두 글자>/<SHA-256>` 키를 만든다. 같은 디렉터리에 임시 파일을 쓰고 fsync 후 hard link로 최종 이름을 설치한다. 이미 있는 최종 파일을 덮지 않고 hash·크기를 다시 확인한다. 디렉터리도 fsync한다. Linux/WSL의 동일 파일시스템을 대상으로 하며 Windows native 저장 adapter를 구현한 것은 아니다.

- 파일 저장 전 실패: DB 완료 참조를 만들지 않는다.
- 파일 설치 후 DB rollback: 파일은 orphan으로 남는다. 같은 입력 재실행 시 검증 후 재사용한다.
- DB 참조는 있지만 파일 누락/변조: 성공으로 재기록하지 않고 오류를 반환한다.
- 내용이 달라진 동일 artifact ID: 충돌로 거부하고 이전 artifact를 유지한다.
- 임시 파일이나 orphan을 자동 삭제하지 않는다. SIGKILL이 남긴 임시 파일의 운영 정리는 별도 점검 절차가 필요하다.

HTTP bytes는 RawLegalCase의 hash·크기·storage key와 실제 bytes를 대조한다. 동일 내용의 재취득은 원본 파일을 재사용하되 receipt의 실제 취득 시각/URL/provenance를 별도로 보존한다. legacy 문자열 hash를 HTTP hash로 넣지 않는다.

## 작업과 재시작

현재 실제 handler는 두 가지다.

1. VERIFY_ARTIFACT: 기존 artifact 파일의 hash·크기 검사.
2. REBUILD_PROJECTION: 등록 시 고정한 legacy artifact 목록에서 조회 데이터를 복원.

handler_version=persistence-1을 저장한다. job_id는 실행 요청 identity이며 dataset_version과 다르다. 수집·조문 보강 handler는 아직 없고 item ledger의 저장 계약만 준비됐다.

동일 request_key·같은 요청은 기존 job을 반환한다. 같은 key의 다른 kind/payload/재시도 설정은 거부한다. 완료된 작업을 의도적으로 다시 실행할 때는 새로운 request_key를 사용한다. 응답 유실 시에는 먼저 기존 job 조회 또는 같은 key 재요청으로 확인한다.

submit/claim/drain은 동일 runtime_control row lock으로 순서를 정한다. claim은 SKIP LOCKED를 사용하며 부분 UNIQUE 인덱스가 RUNNING 작업을 DB 전체에서 하나로 제한한다. worker마다 별도 프로세스 ID, 실행 시도마다 새 lease token을 발급한다.

기본 lease는 60초다. heartbeat·checkpoint·완료는 현재 token과 만료 여부를 검사한다. lease가 만료되면 다음 claim/status에서 이전 시도를 LEASE_EXPIRED로 종료하고 재시도 또는 최종 실패로 전환한다. 이전 worker가 늦게 복귀해도 새 소유자의 완료 상태를 바꿀 수 없다.

기본 최대 실패 횟수는 3회이며 1~10회 범위다. 일반 실패 후 지수 backoff는 최대 60초다. checkpoint를 저장한 정상 중단은 실패 budget을 소비하지 않는다. hash 검사는 digest 내부 상태를 복원하지 않고 다시 처음부터 검사한다. projection 재생성은 마지막으로 commit된 artifact 경계부터 이어간다. 부작용이 중복될 수 있으므로 projection upsert와 불변 파일 재사용으로 idempotency를 유지한다.

## 종료 준비·worker 생존

`ops drain`은 새 등록·claim을 막는다. 진행 작업은 다음 처리 경계에서 checkpoint 후 QUEUED로 돌아가거나 완료된다. 최대 유예는 120초로 정했다. 기존 lease와 이후 갱신 모두 이 deadline을 넘기지 못한다. 살아 있지만 응답하지 않는 worker도 lease 만료 후 소유권을 잃는다.

`ops status`의 ready_to_stop은 draining=true이고 유효 RUNNING 작업이 없다는 뜻이다. 대기 작업은 DB에 남아 다음 resume 후 처리된다. deadline 이후 기존 프로세스가 물리적으로 사라졌다는 의미는 아니다. 실제 EC2 StopInstances·Scheduler 연동은 후속이며 현재 handler 외 외부 부작용 작업에도 fencing/idempotency를 연결해야 한다.

SIGTERM/SIGINT는 stop 요청으로 처리하고 가능한 checkpoint 경계에서 종료한다. Compose의 stop_grace_period는 130초다. worker heartbeat는 별도 테이블에 기록하며 60초가 넘게 갱신되지 않거나 정상 종료 표시가 있으면 unavailable이다. API /api/health와 별도다.

drain 상태는 재시작 후 유지된다. worker 시작이 자동으로 resume하지 않는다. 운영자가 기동 조건을 확인한 뒤 `ops resume`을 실행한다. 평일 17시 자동 호출이나 AWS 예약 설정은 이번 단계에 없다.

## 실행 — 로컬 Compose

공개 개발 설정만 사용하며 실제 staging .env를 읽거나 덮어쓰지 않는다.

```bash
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml up -d --wait postgres
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml build api
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml run --rm migrate
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml up -d --wait api worker web
```

기존 schema에 migration을 먼저 적용한다. 초기화·downgrade·볼륨 삭제 명령은 일반 실행 절차에 없다. 확인은 worker 서비스에서 한다.

```bash
docker compose --env-file .fordeploy/compose.env.example exec worker klegal ops status
docker compose --env-file .fordeploy/compose.env.example exec worker klegal ops worker-health
docker compose --env-file .fordeploy/compose.env.example exec worker klegal ops rebuild-projection <request-key>
docker compose --env-file .fordeploy/compose.env.example exec worker klegal ops job <job-id>
docker compose --env-file .fordeploy/compose.env.example exec worker klegal ops drain
docker compose --env-file .fordeploy/compose.env.example exec worker klegal ops resume
```

호스트에서 실행하려면 backend에서 명시적으로 설정한 DATABASE_URL/DATA_DIR 또는 KLEGAL_ENV_FILE을 사용하고 `uv run klegal ops migrate`, `uv run klegal ops worker`를 실행한다. 같은 DB의 Compose worker와 호스트 worker를 기본으로 함께 실행하지 않는다.

## 검증과 한계

전체 Python suite에서 실제 PostgreSQL을 사용한다. 쓰기 테스트는 localhost:55432의 korcounsel_dev/korcounsel_test만 허용하며 테스트마다 생성한 klegal_test_<UUID> schema만 정리한다. public의 사용자/자료를 reset하지 않는다.

검증 대상: 빈 DB·기존 migration 업그레이드·checksum·동시 migration·DDL 실패 rollback, 원본 내용/취득 이력 분리, 파일 저장 후 DB 실패, 누락/변조 파일, 실제 metadata 15행 저장·JSON 복원·projection 재생성, 사건 다문서·활성 source unique·merge/split/relink·registry snapshot 재현, 비밀번호/세션 hash, item ledger, 동시 submit/claim, 만료된 소유자 차단, 실패 재시도, 실제 프로세스 종료/daemon SIGTERM, drain 경쟁·checkpoint·입력 고정.

[Compose 실측 보고서](step2a-compose-verification.json)는 로컬 개발 DB에 명확히 표시한 합성 artifact/job만 등록한 결과다. 이 합성 기록은 개발 DB에 남으며 corpus import 건수로 세지 않는다. 운영 DB import·full corpus 변환·실제 수집·Parquet export·전체 DB+artifact 재해복구·운영 권한 분리·AWS/TLS/예약은 미실행이다. 사용자/세션 repository는 준비했지만 HTTP 인증·CSRF·로그인 제한·화면 구현은 아직 없다. 비공개 작업 HTTP route를 새로 노출하지 않았다.

2026-09-10 최종 검증: uv locked sync·ruff check/format·mypy, pytest **140건**(실제 PostgreSQL integration **30건**) 통과. 기존 upstream warning 2건. wheel 설치본의 migration SQL 4개, Compose build/config·migration 적용/재실행·API/worker health·frontend/API HTTP 200·합성 작업 처리·drain 차단을 확인했다. [검증 기록](step2a-verification.json). 로컬 runtime은 resume 상태로 worker가 가동 중이며 AWS 변경·전체 corpus import는 하지 않았다.
