# 현재 기준선·제한 품질 교정 — 2026-09-15

## 범위와 결과

사용자는 **현재 수치 확정 → 수정 가능한 품질 오류 처리·보류 근거 정리**와 기록 문서 정리를 요청했다. 이번 실행은 보유 자료의 읽기 전용 집계, 고정 433개 source ID의 품질 확인, 근거가 확인된 5건의 관리자 재처리까지다. 다음 기간 inventory/상세 수집, AWS 변경·전송, canonical 자동 병합, commit/push, 예약 실행은 수행하지 않았다.

- 비교 시작: 2026-09-15 16:03:20 KST, PostgreSQL REPEATABLE READ / READ ONLY.
- 교정 후 기준: 2026-09-15 16:07:37 KST, transaction snapshot `1688852:1688852:`.
- 코드 기준 HEAD: `ba04a50` (`new chat`, 앞선 `4c2f227` 이후 인수인계 문서 커밋);
  이번 교정·집계 도구·문서는 미커밋 변경이다. 이번 작업에서 commit/push하지 않았다.
- lawgo 규칙: `current-lawgo-3`. 필드 추출 규칙은 `case-fields-6`을 유지한다.
- lawgo 법원명 공백으로 발생한 충돌 4건을 EXACT로 교정하고 조문 8곳을 추가 보존했다.
- HTTP 200 서비스 오류 페이지 1곳을 구조 변경과 구분했다. 한 차례 재시도 후에도 동일 오류여서 보류했다.
- 새 reader 5개와 그에 대응하는 v6 필드 5개를 등록했다. 기존 원문·reader·필드 revision은 유지했다.

## 집계 단위와 현재 수치

`source_id`는 scourt namespace의 출처 문서 ID이며 고유 재판결과 수가 아니다. DB `documents`와 `active_source_links`는 각각 0행이다. 이는 판례가 없다는 뜻이 아니라 canonical 등록·연결의 전체 확정이 아직 없다는 뜻이다. 따라서 legacy 행 수와 고정 source cohort 수를 더해 고유 판례 총수로 보고하지 않는다.

| 구분 | 현재 수치 | 의미 |
|---|---:|---|
| corrected legacy Parquet | 89,130행 | 원래 60필드와 행 locator 보존 |
| legacy FULL_ROW DB | 89,130개 position / 89,145개 revision | 같은 행의 보존 이력 포함 |
| legacy reader | 89,130개 position / 94,322개 revision | 동일 위치의 여러 보강 이력 포함 |
| CURRENT_SOURCE reader | 2,260개 source ID / 2,751개 revision | 신규 판례 수로 해석하지 않음 |
| 위 source 중 legacy catalog 직접 대응 | 1,825개 | 출처 ID 기준 대응 |
| catalog 밖 source | 435개 | 고정 433개 + 과거 표본 2개 |
| 고정 증보·시험 cohort | 433개 source ID | 시험 23 + 2024-09~12 증보 410 |
| cohort scourt source version | 434개 | 433개 ID에 대한 원본 내용 버전 |
| cohort scourt 취득 관찰 | 456개 | replay·재관찰 포함 |
| cohort reader | 914개 revision | 최신 source별 433개와 구분 |
| 최신 cohort v6 필드 | 433개 | 과거 v6를 포함한 cohort v6 revision은 438개 |
| 전체 job 이력 | 5,481개 | 성공 5,403 / 실패 78 / 대기·실행 0 |

catalog 밖 표본 `2029039`, `3259074`는 기존 자료 대응 후보가 기록돼 있어 신규 cohort에 추가하지 않았다. 전체 CURRENT_SOURCE의 최신 reader 중 v6가 없는 1,827개는 별도 집계했다. 여기에는 legacy 보강·재관찰 표본과 과거 필드 버전이 포함될 수 있으며, 이를 신규 433건의 미처리로 합산하지 않는다. legacy 공통 60필드 조회는 원래 Parquet를 사용한다.

고정 cohort 선고월: 2024-09 57, 10월 116, 11월 111, 12월 126, 2025-09 1, 11월 1, 2026-06 12, 07월 9개다. 과거 기간의 미관찰 누락과 전체 canonical 중복 해소는 이번에 확정하지 않았다.

### 고정 433개 최신 단계

| 항목 | 결과 |
|---|---|
| 원문·metadata·최신 reader·v6 필드 연결 | 433/433 확인 |
| 필드 ERROR / NOT_PROCESSED | 0 / 0 |
| 필드 전체 상태 | REVIEW 433개; 폐기 역참조 감사 보류 포함 |
| 본문 이미지 / 조문 이미지 | 84 / 213곳 ACQUIRED; 고유 image blob 104개 hash·크기 확인 |
| lawgo 연결 | EXACT 329 / CONFLICT 35 / UNMATCHED 69 |
| 제공 조문 위치 | PRESERVED 5,927 / UNLINKED 2,206 / AMBIGUOUS 164 / FAILED 21 |
| 보존 조문 법령 버전 | 5,927곳 UNVERIFIED 유지 |
| cohort 후속 job | lawgo 성공 이력 440개, 필드 성공 이력 1,573개; 대기·실행 0 |

cohort 상세 취득 job의 실패 9개는 과거 복구 시도의 이력이다. 현재 원문·reader 누락 9건을 뜻하지 않는다. 성공 상세 job 456개와 신규 source ID 433개도 구분한다. 이미지가 없는 자료는 이미지 취득 job의 부재만으로 실패 또는 미처리로 판단하지 않는다.

## 교정 내용과 보류 근거

### 1. 법원 지원명 공백 충돌 4개 교정

보존 scourt metadata와 lawgo 목록·상세의 법원명, 전체 사건번호 집합, 재판 종류, 선고일을 대조했다. 아래 4개는 법원 이름의 공백만 달랐다.

| scourt source ID | 법원 | 사건번호 |
|---|---|---|
| 2026000029300 | 춘천지방법원 강릉지원 | 2023나31881 |
| 2025000013053 | 수원지방법원 여주지원 | 2024고단43 |
| 2026000035946 | 인천지방법원 부천지원 | 2023가단109994 |
| 2025000027193 | 춘천지방법원 강릉지원 | 2024노158 |

`court_comparison_key`는 공백만 비교에서 제외하고 지원·지부 등 모든 글자를 유지한다. 저장된 원래 법원명과 역사적 canonical key를 변경하지 않는다. 다른 지원, 지원이 없는 본원, 병합 번호 일부만 일치, 재판 종류·선고일 불일치는 계속 거절한다.

기존 관리자 `/api/admin/readers/{document_id}/lawgo` 명령으로 한 번씩 등록하고 완료 후 같은 경로의 `/fields` 명령으로 새 필드를 생성했다. 4개 모두 EXACT, 조문 보존은 5,919→5,927곳이다. 새 lawgo 목록·상세·frame·조문 응답도 원본으로 보존했다.

### 2. 남은 동일성 충돌 35개

- **34개:** lawgo 상세에 병합·본소/반소·부수 사건번호가 추가돼 scourt 대표 metadata와 전체 번호 집합이 다르다. 이 중 1개는 법원 지원명 공백 차이도 함께 있다.
- **1개:** `2026000041917`은 lawgo 사건번호의 `(울산)` 지역 표시를 포함한다. 이를 임의 제거하거나 법원 지부 정보를 추정하지 않는다.

충돌을 실체가 다른 판례라고 단정하지 않는다. 원문 사건번호 구획·병합 관계와 양쪽 제공자 정보를 대조할 후속 근거가 필요하다. 첫 번호 포함이나 fuzzy 점수만으로 EXACT로 바꾸지 않았다. 각 source의 원래 metadata, 후보 목록, lawgo 상세 원문 artifact는 보고서 `conflicts`에 연결돼 있다.

### 3. 조문 실패 21곳, 6개 source

- **20곳:** `lsLinkProc.do`가 조문 table 없이 hidden 법령 ID와 팝업 이동 스크립트만 제공한다. 조문 내용·당시 버전을 확인할 수 없어 `LAWGO_ARTICLE_STRUCTURE_CHANGED`를 유지한다. 법령 전체 페이지나 현행 내용을 인용 조문으로 대체하지 않는다.
- **1곳:** `2025000004903`의 제정 약사법 제42조 제2항 요청에 `div#error500`과 서비스 제공 불가 안내가 반환됐다. HTTP 상태는 200이었다. 알려진 오류 구조와 문구가 모두 있을 때 `LAWGO_SERVICE_UNAVAILABLE`로 분류하고 제한 재시도 가능 대상으로 구분한다. 이번 관리자 재처리에서도 동일 응답이어서 **1회 재시도 후 보류**한다. 추가 반복은 실행하지 않았다.

실패 위치별 원문 참조, 제공 연결, 요청 매개변수, 응답 artifact/hash와 분류는 보고서 `failures`에 있다. 과거 실패 기록을 삭제하거나 성공으로 바꾸지 않았다.

### 4. 기타 보류

- UNMATCHED 69개: 보존된 제공자 검색에서 확정 가능한 연결이 없다. 본문 인용을 해석해 임의 법령 API 요청을 만들지 않았다.
- 조문 UNLINKED 2,206곳, AMBIGUOUS 164곳: 실제 제공 연결 부재·복수 대응 상태를 위치별 유지한다.
- 폐기 역참조 433개: 공식 폐기/변경 관계의 전체 근거와 감사 계약이 필요하다. 단순 인용 또는 인용 부재로 미폐기 값을 만들지 않았다.
- 법령 버전 5,927곳: 제공 요청의 날짜 보존과 실체적인 적용 법령 버전 확정은 다르다. 이번에 의미 검증 완료로 바꾸지 않았다.
- legacy 역사적 사건기호와 전체 60필드 의미 감사: 이번 제한 교정의 대상 밖이며 기존 값을 일괄 재발행하지 않았다.

## 검증과 산출물

- 별도 `korcounsel_test` PostgreSQL을 사용한 전체 pytest **791 passed / 3 skipped**. 제외 3개는 별도 컨테이너 설정을 요구하는 dump/복원 시험이며 이번 교정 범위에서 재실행하지 않았다.
- ruff check/format, mypy 통과. 신규 단위 회귀는 공백 일치·다른 지원/병합 번호/재판 종류/날짜 불일치·빈 법원·HTTP 200 오류 분류를 검증한다.
- 고정 433개 원문 hash·reader/fields 연결, 개별 Parquet 타입/값과 60열 aggregate 왕복 대조. typed JSON dict의 키 순서는 의미적 값 차이와 구분했다.
- field evidence 2,679개 범위 검사 및 문자열 구획 값 대조. 이미지 297곳의 고유 blob 104개 hash·크기와 본문 이미지 태그 위치 확인. 법률적 의미 정확성이나 OCR 검증을 뜻하지 않는다.
- 관련 artifact 6,325개의 hash 확인. 교정 전 검증한 artifact 3,109개는 교정 후에도 동일 hash다. legacy Parquet SHA-256도 기존 `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`와 일치한다.
- 교정 5개 모두 인증된 일반 검색이 새 reader를 반환하고 본문·60필드 API는 200이다. 비인증 및 로그아웃 후 401을 확인했다.
- 실제 Chromium에서도 교정 5개 모두 로그인→일반 검색→새 본문→60필드 60개→새로고침 복원→로그아웃을 확인했다. 프런트 코드 변경은 없다.

### 고정 파일

- [교정 전 기준선·SQL](../data/quality-baseline-20260915/baseline-2d3f8d04fb5a546b76cd402b3a72c497a1b5b354711f565bc4155e8eeef092fc.json)
- [교정 후 기준선·SQL·원문 근거·보류 위치](../data/quality-baseline-20260915/baseline-980f34cfe2dcd48eb4596fee2a8f32dc6a30b5b70640d4b227914d163a6da818.json)
- [교정 후 433행×60열 Parquet](../data/quality-baseline-20260915/current-433-v6-quality-d9851f807dfeba93875b9eb0ecb15ac369f3114d0a11c3f2f3e15e91c1957bb0.parquet)
- [source→reader→fields 대응 manifest](../data/quality-baseline-20260915/current-433-v6-quality-d9851f807dfeba93875b9eb0ecb15ac369f3114d0a11c3f2f3e15e91c1957bb0.json)
- [전후 필드 차이·API 검증·과거 hash 불변](../data/quality-baseline-20260915/verification-85a431e0d7ae2ac84855c371e0d5f093c49070be732967ba5cd1e4aa33434b08.json)
- [교정 5개 실제 브라우저 검증](../data/quality-baseline-20260915/browser-verification.json)
- [전체 pytest 실행 로그](../data/quality-baseline-20260915/execution/pytest.log)

새 aggregate SHA-256은 `d9851f807dfeba93875b9eb0ecb15ac369f3114d0a11c3f2f3e15e91c1957bb0`이다. **aggregate는 로컬 불변 export이며 DB artifact로 별도 등록하지 않았다.** 개별 reader/fields revision 5개는 관리자 job을 통해 DB에 등록돼 실제 검색·열람에 사용된다. 기존 `fbe78170…` v6 snapshot도 이력으로 유지한다.

최초 조사 파일 `baseline-cb6e1173…`은 legacy reader origin과 취득 관찰 metadata 키를 잘못 조회해 두 부분집계가 0으로 표시됐다. 이를 판례 누락으로 해석하지 않았고, 실제 schema의 `LEGACY_CORPUS`와 `source_versions.artifact_id = artifacts.parent_id`로 교정한 `2d3f8d04…`가 실행 전 기준선이다. 최초 파일은 조사 이력으로만 보존한다.

### 재현

저장소 루트에서 실행한다. DB는 읽기 전용 transaction으로 조회하고 결과 파일만 추가한다. 접속 환경값은 출력하지 않는다.

```bash
KLEGAL_ENV_FILE="$PWD/.fordeploy/aws-backup/.env" \
backend/.venv/bin/python scripts/audit_current_baseline.py \
  --cohort data/window-run-20260915/current-433-v6-fbe7817002493585a3262aa904f713515321bd2f94b86170c291aed040e5dc34.json \
  --legacy data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet \
  --data data --output data/quality-baseline-20260915
```

SQL과 매개변수는 매 보고서 `queries`, 동일 transaction의 결과는 `sql_results`에 보존한다. 이후 새 job이 실행되면 새 기준 시각의 결과가 생기며 과거 파일은 변경하지 않는다. `action-*-request.json`과 `action-*-result.json`에는 이번 10개 관리자 요청의 UUID·대상 reader·job ID가 기록돼 있다.

이번에 사용한 제한 관리자 요청·snapshot/API 검증·브라우저 검증 스크립트도
`data/quality-baseline-20260915/execution/`에 보존했다. 이 스크립트는 이번 고정
대상과 요청 ID의 실행 근거이며 이후 기간 수집을 등록하는 도구가 아니다.

## 로컬 실행 환경 복구

시작 시 기존 postgres/API/web 컨테이너는 종료돼 있었고 worker는 재시작 중이었다. worker를 먼저 멈추고 기존 DB를 기동해 대기 작업 0개를 확인했다. 기존 볼륨을 유지한 채 누락된 개발 포트 `127.0.0.1:55432`를 복구하고, 로컬 API는 README처럼 `WEB_ORIGIN=http://127.0.0.1:8080`을 명시했다. `.env`는 수정하지 않았다. 교정된 backend 이미지를 로컬 API·단일 worker에 적용했다. AWS·DNS·migration 변경은 없다.

## 이 작업의 종료 기준과 다음 범위

이번에 확정한 숫자, 수정한 오류, 제한 재처리 결과, 해결하지 못한 항목의 근거를 모두 기록했다. 향후 증보는 별도 명시 명령으로 진행하며, 역사적 예규·폐기 관계 등 모든 의미 검토가 끝나야만 다음 inventory를 할 수 있다는 무기한 선행 조건을 만들지 않는다. 실제 이관·발행 시에는 그 범위의 미처리와 조사 후 보류를 구분해 검토한다.
