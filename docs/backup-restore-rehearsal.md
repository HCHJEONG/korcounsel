# DB·파일 백업 및 격리 복원 리허설

## 구현 범위

`backend/src/klegal_gold/storage/backup.py`는 PostgreSQL REPEATABLE READ/READ ONLY 트랜잭션에서 snapshot을 export하고 같은 snapshot의 `blobs` 목록과 실제 파일을 묶는다. 호출자는 동일 DB/schema에 `pg_dump --snapshot=<exported snapshot> -Fc`를 실행하는 adapter를 제공해야 한다. 기존 destination은 거절하며 원본 파일을 수정하지 않는다. 파일은 복사 전후 SHA-256·크기를 검증하고 dump도 hash를 기록한다. 복사/덤프 실패 시 partial 디렉터리는 남지만 완료 `manifest.json`은 발급하지 않는다. 완료 manifest는 fsync 후 atomic link로 발행한다.

`verify_backup()`은 dump와 등록 blob의 크기·hash, 파일 경로·symlink·중복 hash를 확인한다. checksum 검증은 실제 PostgreSQL 복원 성공 또는 위변조에 대한 서명 검증을 대체하지 않는다. dump 안에 사용자 password hash·세션·업무 데이터가 포함될 수 있으므로 결과 디렉터리를 비공개로 보관한다. 이 도구는 환경파일·외부 원본 archive·설정되지 않은 외부 Parquet·DB role/password·서버 설정·TLS를 자동 복사하지 않는다. 전체 corpus 운영 백업 완료나 보관·암호화·원격 복제 정책 완료를 뜻하지 않는다.

## 재실행 가능한 로컬 리허설

실행 위치는 `backend/`다. Python/pytest는 uv 환경, PostgreSQL 도구는 명시한 기존 로컬 PostgreSQL 컨테이너의 pg_dump/pg_restore를 사용한다. 같은 cluster인지 system_identifier를 먼저 대조한다. `korcounsel_test`가 미리 존재해야 하며 환경파일의 DB명과 무관하게 테스트는 이 별도 DB로 고정한다. 실제 연결값은 출력하지 않는다.

```bash
uv run python ../scripts/rehearse_backup_restore.py \
  --env-file /home/hchjeong/IntelliJProjects/korcounsel/.fordeploy/aws-backup/.env \
  --postgres-container korcounsel-postgres-1 \
  --output /home/hchjeong/IntelliJProjects/korcounsel/data/restore-drill-20260914
```

재실행은 새로운 output 경로를 지정한다. 결과는 `report.json`, `results.xml`, `pytest/`의 합성 fixture backup이다. output이 이미 있으면 거절하므로 pytest가 기존 corpus 경로를 정리하지 않는다. 중단된 리허설을 자동으로 정리하거나 기존 output 위에 재실행하지 않는다.

테스트는 `korcounsel_test`의 임시 schema에 합성 원문·반복 이미지·실패/대기 위치·조문·미연결 위치·사용자/세션·작업을 생성한다. snapshot 발급 후 별도 트랜잭션에서 등록한 자료가 DB dump와 파일 목록 모두에 섞이지 않는지 확인한다. 복원 대상은 이번 실행이 새로 생성한 `korcounsel_restore_<uuid>` DB뿐이다. pg_trgm 확장을 준비하고 `pg_restore --exit-on-error --no-owner --no-privileges`로 같은 schema를 복원한다. 모든 테이블의 행을 비교하고 이미지 bytes·본문·검색·계정/세션·작업 재개를 확인한 뒤 생성한 복원 DB만 삭제한다. 외부 종료나 시스템 장애로 cleanup이 실행되지 않으면 잔여 테스트 DB를 조사해야 하며 임의로 다른 DB를 삭제하지 않는다.

## 검증 범위와 한계

- 실제 pg_dump/pg_restore 및 파일 복사; DB 전체 테이블 행의 동일성 확인.
- snapshot 이후 등록 자료 제외, 완료된 immutable reader와 이미지·조문 재사용.
- 복원 계정 인증, 일반 검색→reader HTML→반복 이미지 API, 실패 이미지 404, 로그아웃 후 401.
- 대기 작업 재개와 동일 요청 중복 방지; 원래 DB의 대기 작업은 미실행 유지.
- 누락·손상 source blob 및 dump 실패 시 완료 manifest 미발행.
- 백업 dump/blob 변조·symlink 거부; 복원 복사본 손상이 원본/backup에 전파되지 않음.

합성 데이터의 격리 복원 검증이다. 기존 89,130행 전체의 대용량 복원 시간·용량, 실제 운영 corpus dump, AWS 복원, 브라우저 육안 검증을 이번 리허설로 대신하지 않는다. 로컬 운영 서비스 중단·환경파일 변경·schedule 생성은 하지 않는다.

## 2026-09-14 실제 실행

문서의 명령으로 리허설 7개가 4.29초에 통과했다. 실제 restore용 합성 bundle은 등록 blob 6개·16,156바이트와 PostgreSQL dump 113,040바이트다. 결과는 로컬 `data/restore-drill-20260914/report.json`, `results.xml`, `pytest/`에 보존했다. 운영 데이터 백업/복원 여부는 보고서에 모두 false로 명시했다.

최종 회귀: 실제 restore 테스트를 활성화한 전체 Python/PostgreSQL **732개 통과**(73.49초, 의존성·프로세스 경고 4개). backend 전체와 리허설 스크립트의 ruff check/format, mypy(63 source files), pnpm lint/build 및 git diff --check를 통과했다.


## 관리자 웹 백업 — 2026-09-14

로그인 후 관리자 영역의 **백업 관리**를 펼쳐 **지금 백업 실행**을 누른다. 현재 DB의 public schema(계정·세션·작업 및 수집 이력 포함), 같은 snapshot에 등록된 원문·이미지·reader blob, 설정된 `LEGACY_PARQUET_PATH` 파일을 보존한다. 화면은 최근 20건의 대기/실행/성공/실패, 시도 횟수, 파일 처리 건수, 저장 용량과 Parquet 포함 여부를 표시한다. 화면 새로고침 후 DB 이력을 다시 읽고 숨겨진 탭의 polling은 멈춘다.

- `GET/POST /api/admin/backups`는 서버에서 관리자 권한을 확인하며 POST에는 동일 Origin이 필요하다. 비로그인 401, 편집자 403이다.
- 등록 결과가 불확실하면 URL에 유지한 요청 ID로 **같은 요청 확인**을 누른다. 동일 요청은 같은 job을 반환하고 다른 요청의 동시 백업은 거절한다. 종료 준비 중에는 신규 접수를 막는다.
- `CREATE_BACKUP`은 기존 단일 worker의 영속 queue·lease·checkpoint를 사용한다. 브라우저를 닫아도 실행된다. 정기 실행은 만들지 않는다.
- 백업마다 job ID와 lease ID를 조합한 새 디렉터리를 만든다. 중단된 snapshot은 파일 개수부터 이어 복사하지 않고 새 snapshot·디렉터리에서 다시 시작한다. 이전 partial 파일은 삭제하지 않는다. 완료 manifest가 발행된 뒤 job 완료 기록만 유실되면 기존 bundle을 검증해 재사용한다.
- 실패한 복사/덤프에는 완료 `manifest.json`을 발급하지 않는다. DB 덤프와 Parquet에도 크기·SHA-256을 기록한다. 원본·기존 manifest는 수정하지 않는다.
- 외부 동결 pickle archive, 환경파일, DB role/password 설정, TLS/서버 설정은 포함하지 않는다. **백업 성공과 전체 복원 검증 성공은 별개**이며 화면에도 복원 검증이 별도 절차임을 표시한다. 웹에서 운영 DB를 덮어쓰는 복원 기능은 제공하지 않는다.

### 저장 위치와 실행 조건

Compose는 worker에 `BACKUP_DIR=/backups`와 `${LOCAL_BACKUP_DIR:-./backups}:/backups`를 연결한다. 기본 호스트 위치는 저장소의 `backups/`이며 Git 및 frontend Docker build context에서 제외한다. 호스트 디렉터리를 실행 사용자 소유·비공개 권한(예: 0700)으로 준비한다. 별도 위치는 Compose 실행 환경의 `LOCAL_BACKUP_DIR`로 지정하며 기존 환경파일을 수정할 필요가 없다. 일반 Python 실행은 절대 경로 `BACKUP_DIR`를 설정해야 웹 백업을 활성화한다. 백업 경로는 원본 data store 밖이어야 한다.

사전 검사는 등록 blob 크기 + 현재 DB 크기 + Parquet 크기 + 1GiB 여유를 확인한다. 실제 파일시스템에서 쓰기가 실패하면 partial 상태로 남는다. WSL 내부 여유량만으로 Windows 호스트 볼륨 공간까지 보장하지 않는다. 가상 디스크가 놓인 Windows 볼륨의 여유량과 기존 partial 백업 용량도 함께 확인해야 한다.

backend 이미지에 PostgreSQL 17 `pg_dump`를 포함한다. Docker socket은 worker에 연결하지 않는다. Psycopg의 `ConnectionInfo.dsn`은 비밀번호를 제거하므로, 인증된 libpq 연결의 password를 덤프 자식 프로세스 환경에만 전달한다. credential을 argv·job payload·로그에 기록하지 않는다.

### 재개 작업에서 확인한 사항

기존 웹 실행의 job `20093a1c-16b6-43d3-a1f7-143765684841`은 서비스 중단 당시 완료 manifest 없이 부분 파일만 남았다. PostgreSQL/API/web/worker를 기존 볼륨으로 재기동하자 lease 만료를 감지하고 같은 job의 새 시도로 복구됐다. 첫 시도 부분 파일은 보존했다. 별도의 신규 백업 요청은 등록하지 않았다.

실제 컨테이너의 작은 테스트 DB snapshot으로 덤프 adapter를 검증하면서 비밀번호 전달 누락을 발견해 수정했다. `KLEGAL_TEST_BACKUP_WORKER_CONTAINER=korcounsel-worker-1`을 지정하면 이 회귀를 실행한다. `KLEGAL_TEST_PG_CONTAINER`가 활성화하는 기존 실제 pg_restore 리허설과 함께 검사한다. 현재 운영 corpus 전체의 백업·복원 완료 결과는 이 항목으로 대신하지 않는다.


## 전수 로컬 백업·격리 복원 실증 완료 — 2026-09-14

관리자 웹에서 등록한 기존 job `20093a1c-16b6-43d3-a1f7-143765684841`의 세 번째 시도가 SUCCEEDED로 끝났다. 성공한 시도는 18:32:13~18:55:25 KST, 약 **23분 13초**였다. 첫 시도는 서비스 중단 뒤 lease 만료, 두 번째 시도는 코드 갱신을 위한 정상 checkpoint 종료였으며 부분 디렉터리는 모두 보존했다. 신규 백업 요청을 중복 등록하지 않았다.

완료 bundle: `backups/20093a1c-16b6-43d3-a1f7-143765684841-ebff18cb-64b2-4a6b-87eb-1c7c2944b671/`.

| 항목 | 실측 |
| --- | ---: |
| 등록 blob | 529,886개 / 28,868,586,160 bytes |
| PostgreSQL dump | 1,322,933,621 bytes |
| corrected Parquet | 1,215,542,924 bytes / 주 검색 corpus 89,130행 |
| 완료 manifest | 116,984,928 bytes |
| 별도 동결 archive 보충본 | 6,525,441,901 bytes |

동결 pickle은 `backups/archive-supplements/20093a1c-16b6-43d3-a1f7-143765684841/`에 별도 복사하고, 기존 확정 SHA-256 `aa3d2c57d0f647b8c078df5784be5ef3e02e8b24cf40e543e9358b7b74dc7b69`과 원본·복사본 일치를 확인했다. corrected Parquet의 provenance manifest도 함께 보존했다. pickle은 역직렬화하지 않았다. 이는 이번 수동 보충본이며 웹 백업의 자동 포함 범위를 바꾸거나 기존 완료 manifest를 수정한 것이 아니다.

### 실제 복원과 데이터 대조

완료 bundle의 dump·Parquet·529,886개 blob을 다시 검증한 뒤, 별도 `data/full-restore-4b54dc4eef06/files/`로 복사해 전수 SHA-256을 대조했다. 복원 DB는 **`korcounsel_restore_1ec6dccf325347ec9b97e974b26f0271`**이며 원래 DB를 덮어쓰지 않았다. 복원 DB에는 worker를 실행하지 않았다.

처음에는 `public` schema 재생성 충돌로 새 복원 DB에서 pg_restore가 실패했다. 이미 존재하는 schema를 사용하도록 **`pg_restore --schema=public --exit-on-error --no-owner --no-privileges`**를 적용했다. pg_trgm은 새 DB의 public schema에 먼저 준비한다. SQL 출력에서 schema 중복 생성이 빠지고 35개 테이블 정의는 유지됨을 확인했고, 기존 schema를 대상으로 하는 실제 dump/restore 회귀를 추가했다. 첫 실패 DB `korcounsel_restore_53248621a49c47a7a2113808ec9469e3`도 임의 삭제하지 않았다.

35개 테이블의 비교 대상 행 수와 내용 해시를 기록했다. 계속 변하는 `app_sessions`·`worker_instances`는 원본과 동일성 판단에서 제외하고 복원본의 행 수·해시를 기록했다. 다른 테이블은 원본과 일치했다. `jobs`·`job_attempts`·`job_events`의 현재 백업 job은 실행 중 snapshot과 완료 후 상태가 다르므로 따로 대조했다. snapshot의 이벤트 6건이 현재 7건의 이력에 그대로 남아 있고, 이전 시도·진행 중 시도의 식별 정보·요청 내용이 동일함을 확인했다.

주요 대조: legacy 검색 89,130행, 전체 legacy 보존 레코드 89,145건, artifact 531,292건, blob 529,886건, current reader 검색 revision 1,841건, 이미지 취득 8,411건 및 취득 시도 8,755건, 현재 백업 외 작업 2,953건. 기존 미완료·실패·중복 보존 이력도 삭제하지 않았다. DB 재복원·테이블 대조는 약 **15분 9초**였으며, 앞선 백업 재검증·파일 복사 시간과 실패 시도 시간은 이 수치에 포함하지 않는다.

### 복원본의 실제 브라우저 검증

임시 localhost 앱을 복원 DB·복원 파일만 사용하도록 실행했다.

- `2010두9976`: legacy Parquet 검색→보존 본문, current 최신 결과 1건→조문 26곳, 조문 미연결·적용 버전 미확인 위치 표시.
- `2010구합13975`: 저장 조문 이미지 2곳이 내부 `/api/reader/...` 주소에서 실제로 디코딩·표시됨.
- 새로고침 후 같은 reader 복원, 로그아웃 시 본문 제거, 미인증 검색/본문 401, 외부 요청 0건.
- 원래 관리자 화면에서도 동일 job의 백업 완료·529,886개 처리·Parquet 포함과 새로고침 복구를 확인했다. 화면은 수동 복원 결과를 자동 추적하지 않으므로 ‘복원 검증은 별도 절차’로 표시한다.

검증용 API·프런트 서버는 종료했다. 복원 DB·파일 및 `data/full-restore-4b54dc4eef06/report.json`, `browser-report.json`, `backup-completed.png`, `restored-statute-image.png`는 로컬에 보존했다. 이 백업은 같은 WSL 디스크 내 별도 경로에 있으므로 디스크 자체 장애에 대비한 외부 보관·AWS 복원 완료를 뜻하지 않는다. 환경파일 변경, 원본 덮어쓰기, schedule 생성, commit/push는 하지 않았다.

최종 검증: **739개 통과**, ruff check/format·mypy(64 source files), pnpm lint/build, git diff --check 통과. 의존성·프로세스 경고 4개는 기존 항목이다.
