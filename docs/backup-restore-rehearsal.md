# DB·파일 백업 및 격리 복원 리허설

## 구현 범위

`backend/src/klegal_gold/storage/backup.py`는 PostgreSQL REPEATABLE READ/READ ONLY 트랜잭션에서 snapshot을 export하고 같은 snapshot의 `blobs` 목록과 실제 파일을 묶는다. 호출자는 동일 DB/schema에 `pg_dump --snapshot=<exported snapshot> -Fc`를 실행하는 adapter를 제공해야 한다. 기존 destination은 거절하며 원본 파일을 수정하지 않는다. 파일은 복사 전후 SHA-256·크기를 검증하고 dump도 hash를 기록한다. 복사/덤프 실패 시 partial 디렉터리는 남지만 완료 `manifest.json`은 발급하지 않는다. 완료 manifest는 fsync 후 atomic link로 발행한다.

`verify_backup()`은 dump와 등록 blob의 크기·hash, 파일 경로·symlink·중복 hash를 확인한다. checksum 검증은 실제 PostgreSQL 복원 성공 또는 위변조에 대한 서명 검증을 대체하지 않는다. dump 안에 사용자 password hash·세션·업무 데이터가 포함될 수 있으므로 결과 디렉터리를 비공개로 보관한다. 이 도구는 환경파일·외부 원본 archive·등록되지 않은 Parquet·DB role/password·서버 설정·TLS를 자동 복사하지 않는다. 전체 corpus 운영 백업 완료나 보관·암호화·원격 복제 정책 완료를 뜻하지 않는다.

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
