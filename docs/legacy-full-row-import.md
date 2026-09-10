# 기존 DataFrame FULL_ROW 보존 importer

**전수 text 대조 후속:** 89,130행의 본문과 별도 파일 8,482개를 대조했다. 신규 미포함 판례로 확정한 자료는 없으며 ID 없는 기존 재결 6429행의 연결 검토가 필요하다. [상세 결과](legacy-text-coverage-audit.md).

2026-09-10. 기존 pickle에 저장된 DataFrame을 재사용하는 export 도구와 단일 worker importer를 구현하고 실제 표본을 검증했다.

## 저장 매체 결정: pickle, Parquet, PostgreSQL

Parquet은 행 단위 문서 형식이 아니라 **컬럼 지향(columnar) 이진 파일 형식**이다. 컬럼의 자료형과 schema를 기록하고, 컬럼별 압축·인코딩과 필요한 컬럼만 선택해 읽는 처리를 지원한다. 따라서 89,130행×60컬럼을 한 행당 JSON 파일 89,130개로 펼치는 것보다 파일 수와 파일시스템 부하를 줄이면서 전수 통계, 컬럼 검사, 재처리 입력으로 사용하기 쉽다. 파일 또는 partition의 SHA-256을 manifest에 고정하면 변경되지 않는 snapshot으로 전달·대조하기도 쉽다.

다만 Parquet은 Python 객체 저장소가 아니다. 문자열, 정수, 실수, bool, 날짜·시각, binary, list·struct처럼 schema로 표현 가능한 값은 Python·Java·Node.js 등에서 공유할 수 있지만 `dateutil.parser.parser` 같은 임의의 Python 객체 그래프를 그대로 복원하지는 못한다. 기존 corpus의 이런 값은 원래 pickle에 보존하고 Parquet에는 최소한 `OPAQUE`, Python type, snapshot hash, original position/index, field 이름을 기록해 원본 위치를 찾을 수 있게 한다. 빈 문자열, 정수 0, null, NaN, list/tuple 같은 역사적 구분도 변환 전에 명시적 표현 계약과 cell fingerprint로 검증해야 한다.

세 저장 매체의 책임은 다음과 같이 구분한다.

| 매체 | 기준 역할 | 장점 | 한계 |
| --- | --- | --- | --- |
| 원본 pickle | 역사적 Python object graph의 최종 보존본 | 당시 DataFrame과 Python 객체를 가장 충실하게 남김 | 신뢰한 Python 환경이 필요하고 언어 간 교환·부분 조회·안전한 일반 입력에 부적합 |
| Parquet | 전체 컬럼의 이식 가능한 표 형식 snapshot | 압축, 명시적 schema, 컬럼 선택 읽기, 분석·대조·재처리에 유리 | 임의 Python 객체를 표현하지 못하고 수정 시 파일 또는 partition을 다시 써야 함 |
| PostgreSQL | 서비스 운영 상태와 검색용 projection | transaction, 제약, 동시 변경, 검색, 관계, 작업·검토 이력에 적합 | 원본 object graph 보존 형식이 아니며 60컬럼의 성급한 schema·타입 강제는 역사적 구분을 잃을 수 있음 |

PostgreSQL은 89,130행을 담을 용량이 부족해서 제외하는 것이 아니다. 이 규모 자체는 PostgreSQL에 작다. 직접 적재만으로 끝내지 않는 이유는 원본 보존, 재현 가능한 입력 snapshot, 운영 데이터의 책임이 서로 다르기 때문이다. 대형 HTML과 모든 중간 표현을 운영 테이블에 넣으면 같은 EC2의 DB 크기·backup·vacuum 비용이 커지고, schema를 정하기 전에 값이 coercion될 수 있다. PostgreSQL에는 사용자·세션, job·ledger, canonical/link revision, 검토 이력, 검색에 필요한 판례 projection과 artifact hash/locator를 둔다. 원본과 전수 snapshot은 불변 파일로 유지한다. JSONB를 사용해도 JSON이 표현하지 못하는 Python 객체와 타입 구분 문제가 사라지지는 않는다.

따라서 현재 목표 구조는 **원본 pickle + 전체 Parquet snapshot + PostgreSQL projection/registry**다. 이미 구현한 행별 tagged JSON bundle은 SAMPLE 검증, 행 단위 격리, API 전달과 개별 원행 대조에 사용할 수 있지만, 89,130행 전수 보존의 유일한 주 형식으로 확정하지 않는다. Parquet 전환은 원본 pickle을 폐기하거나 현재 PostgreSQL importer의 보존 이력을 초기화하는 작업이 아니다.

### Node.js 사용 경계

Node.js에서도 Parquet을 읽고 쓸 수 있다. Arrow/Parquet 계열 라이브러리로 Parquet을 Arrow table로 읽거나, DuckDB의 Node client로 `read_parquet(...)`에 SQL을 실행하는 방식이 실용적이다. 다만 Node 생태계의 library별 지원 범위·유지보수 상태·logical type 호환성은 구현 시 고정 버전으로 실제 생성 파일을 대조해야 한다. Python 전용 OPAQUE 객체는 Node가 해석하지 않고 locator와 type metadata만 읽는다.

KorCounsel의 실행 책임은 다음과 같이 둔다.

- Python 분석/export 도구가 신뢰한 pickle을 읽어 Parquet과 manifest를 만들고 전수 타입·값·hash를 검증한다.
- Python worker가 검증된 snapshot을 읽어 PostgreSQL projection과 ledger를 작성한다.
- Node/TypeScript는 관리·점검 도구에서 제한적인 metadata/컬럼 조회에 사용할 수 있다.
- React 브라우저는 대형 Parquet snapshot을 직접 읽지 않고 FastAPI와 PostgreSQL 조회 경로를 사용한다. 실제 Parquet 크기는 변환 후 측정한다.

Parquet 구현 전에는 실제 60컬럼별 dtype과 혼합형 값을 분류하고, 원래 컬럼 순서·pandas dtype·row count·position/index·cell fingerprint를 manifest에 넣는 schema를 먼저 고정한다. 표본 변환에서 Python과 Node/DuckDB 읽기, 선택 컬럼 조회, null/sentinel/OPAQUE, 압축 후 크기와 round-trip을 검증한 뒤 전수 변환 여부를 결정한다. `pyarrow` 또는 Node library는 이 검증을 시작할 때만 의존성에 추가한다.

현재 Parquet exporter와 이를 읽는 worker 경로는 미구현이다. 위 내용은 후속 구현의 목표이며, 아래의 구현·검증 결과는 기존 tagged JSON bundle 경로에 해당한다.

## 입력은 기존 DataFrame

입력은 기존 최종 DataFrame pickle이다. text 파일로 DataFrame을 재구성하지 않는다. 본문·보강 HTML·metadata를 포함한 원래 60컬럼을 행별로 읽는다. text 파일은 별도 대조/보완 자료이며 이번 FULL_ROW 입력을 대신하지 않는다.

`scripts/export_legacy_rows.py`는 분석용 pandas 2.2.3·NumPy 1.26.4 환경에서 지정한 snapshot만 읽는다. 기존 allowlist unpickler를 재사용하고 레거시 코드를 import하지 않는다. 앱 runtime dependency에 pandas/NumPy를 추가하지 않았다. 대형 pickle은 표본만 선택하더라도 DataFrame 전체를 메모리에 읽어야 한다. 충분한 메모리가 있는 로컬 분석 환경에서 실행하며 bastion small worker에 올리지 않는다.

export는 입력 SHA-256을 먼저 대조하고 종료 시 크기·mtime·inode 변화를 검사한다. 원래 position과 index, 전체 컬럼 순서·이름·값·타입을 유지한다. 중복 index도 position으로 구분한다. 행 문자열을 과거 HTTP 응답 바이트로 표시하거나 과거 수집시각을 만들지 않는다.

## 값 보존과 archive 의존성

- 문자열·정수·null은 해당 타입/값을 그대로 보존한다.
- bool·float·date/datetime·list/tuple/dict는 타입을 명시한 JSON 트리로 보존한다. tuple과 list, 정수 키와 문자열 키를 구분한다. NaN/무한대는 JSON 비표준 숫자로 쓰지 않고 태그 값으로 남긴다.
- NumPy scalar는 원래 NumPy 타입명을 함께 보존하고 대응 scalar 값을 추출한다.
- 지원하지 않는 객체와 이를 포함한 container는 OPAQUE로 남긴다. 객체의 str/repr을 실행하지 않는다. 정확한 원래 객체는 snapshot hash + position + field 이름으로 원본 archive를 참조한다.
- **OPAQUE가 있는 bundle만으로 모든 Python 객체를 복구할 수 있다고 주장하지 않는다. 원본 pickle은 보존·백업 대상이다.** 이번 실제 표본의 900개 필드 중 OPAQUE 15개는 archive 참조이며 나머지 885개는 값을 보존했다.

본문과 보강 HTML은 원래 DataFrame 필드의 정확한 문자열로 유지한다. HTML을 정규화하거나 새로 보강하지 않는다. FULL_ROW는 전체 컬럼 보존 범위이며 원문의 법률적 완전성이나 구조화 완료 판정이 아니다.

## 불변 bundle과 worker

export는 DATA_DIR의 content-addressed blobs에 행 파일과 `legacy-full-row-bundle-1` manifest를 덮어쓰기 없이 저장한다. manifest는 snapshot hash/size/locator, 원래 전체 행 수, 컬럼 목록, SAMPLE/FULL 범위, 선택한 position별 파일 hash/size를 고정한다. FULL은 모든 position을 빠짐없이 포함해야 한다. 행·manifest 각각 64MiB의 입력 한도가 있다.

CLI는 manifest hash만 job에 등록한다. worker는 공유 DATA_DIR 안의 hash 경로를 읽으며 임의 외부 경로·pickle·URL을 job으로 받지 않는다. job handler는 `legacy-import-1`, mapper는 `legacy-staging-0.2.0`이다. 호환되지 않는 규칙 변경은 handler/version 및 고정 입력 정책을 함께 갱신해야 한다.

migration 0008은 IMPORT_LEGACY_BUNDLE job과 append-only `legacy_bundle_rows`를 추가한다. ledger는 job + 원래 position별 입력 artifact·보존 결과·PRESERVED/QUARANTINED·사유를 남긴다.

행 파일의 hash/size를 확인하고 원문 artifact를 보존한 뒤 schema·snapshot/position·FULL_ROW·전체 컬럼 일치를 검사한다. 잘못된 행은 원문을 보존한 채 격리하고 다음 행을 처리한다. 파일 누락·hash 손상·DB 저장 장애를 성공한 격리로 바꾸지 않는다. 판시사항·요지 결측, 미확정 identity, OPAQUE 자체는 행을 폐기하는 사유가 아니다.

완료 manifest는 selected = preserved + quarantined, pending=0을 검증한다. SAMPLE은 전체 corpus 완료로 표시하지 않는다. FULL 완료 플래그는 해당 archive의 보존 처리 범위이며 canonical 등록·법률 검수·gold 완료를 뜻하지 않는다.

## 재실행·중단과 연결 경계

같은 request key·manifest hash는 같은 job을 반환한다. 다른 request key로 같은 bundle을 처리하면 기존 보존 artifact를 재사용하고 실행별 ledger를 추가한다. 같은 snapshot 행에 서로 다른 content revision이 있으면 이전 것을 덮어쓰지 않는다.

worker는 drain/stop을 확인하고 lease를 갱신한다. 행 ledger commit 시 유효 lease를 다시 확인하므로 소유권을 잃은 worker가 완료 checkpoint를 기록할 수 없다. 파일/record 저장 뒤 ledger 저장 전에 중단돼도 재실행에서 동일 내용을 재사용한다. 완료한 행도 입력·저장 artifact 무결성을 확인한다. 재개는 ledger 기준이며 이전 입력을 다시 검증하는 비용이 있다.

보존 성공을 자동 canonical 등록으로 바꾸지 않는다. 실제 표본은 원행·본문 저장을 검증한 것이며 출처 간 연결이나 사람의 검토 승인을 확정하지 않았다. registry 등록은 재판결과 키·metadata 충돌을 검토한 별도 단계다.

## 실행

backend에서 분석용 export를 실행한다. 아래 경로는 운영자가 지정하며 앱에 hard-code하지 않는다.

```bash
uv run --with pandas==2.2.3 --with numpy==1.26.4 python ../scripts/export_legacy_rows.py \
  --snapshot /absolute/path/to/corpus.pickle \
  --expected-sha256 EXPECTED_SHA256 \
  --data-dir /absolute/path/to/staging \
  --positions 0,190,232,325,421,952 \
  --report /absolute/path/to/export-pointer.json
```

전체 export에는 --positions 대신 --all을 명시한다. 이번에는 15행 SAMPLE만 실제 실행했다. exporter 보고서의 manifest_hash를 사용한다. staging의 manifest와 참조 blobs를 API/worker의 공유 DATA_DIR에 무결성을 유지하며 전달한 뒤 등록한다. 호스트 DATA_DIR과 Compose named volume은 자동으로 같은 위치가 아니다.

```bash
klegal ops submit-legacy-import REQUEST_KEY MANIFEST_HASH
klegal ops legacy-import-status JOB_ID
klegal ops job JOB_ID
```

CLI·worker는 기존 명시적 DATABASE_URL/DATA_DIR 설정을 사용한다. 최종 result_manifest는 Records.read로 hash 검증 후 읽는다. 긴 import를 CLI 프로세스나 HTTP 요청에서 직접 실행하지 않는다.

실제 SAMPLE의 격리된 PostgreSQL 검증 도구:

```bash
uv run python scripts/verify_legacy_import_sample.py \
  --data-dir /absolute/path/to/staging \
  --manifest-hash MANIFEST_HASH \
  --report /absolute/path/to/report.json
```

이 명령은 KLEGAL_TEST_DATABASE_URL의 localhost:55432 개발/테스트 DB만 허용하며 생성한 UUID schema만 정리한다.

## 검증 결과

- 전체 Python 회귀 281건 통과, 실제 PostgreSQL integration 56건 포함. 기존 upstream warning 2건.
- 분석 전용 synthetic DataFrame export 회귀 1건 별도 통과. 중복 index, NumPy scalar, 원문·nested 값, 동일 export hash 및 잘못된 snapshot hash 거부를 확인했다.
- ruff check/format 및 mypy 42 source 파일 통과.
- 실제 기존 89,130행 DataFrame에서 15행·60컬럼을 추출했다. 900필드 중 15개 OPAQUE 참조, 본문 문자열 필드 30개. 두 번 import 후 보존 기록 15개·실행 ledger 30개·격리 0개이며 원행 JSON round-trip이 일치했다.
- 중단 후 재개, 저장 뒤 checkpoint 전 중단, 동일 입력 재사용, 잘못된 행의 원문 격리, 손상 파일 실패, drain, lease 상실, FULL/SAMPLE 범위와 컬럼 검증을 실제 PostgreSQL에서 확인했다.
- 로컬 Compose image 재빌드·migration 0008 적용·API/worker health를 확인했다. 실제 표본 job bfe60833-c410-4b62-9d03-65462f8b737d는 SUCCEEDED, PRESERVED 15개다. 이 표본 보존 기록은 로컬 개발 DB에 남긴다. 실제 canonical 등록은 하지 않았다.

[실제 표본 검증](legacy-full-row-sample-verification.json), [전체 검증 요약](legacy-import-verification.json).

## 다음 범위

89,130행 전체 export/import의 시간·메모리·디스크 측정과 전체 건수 reconciliation은 아직 실행하지 않았다. 다음은 표본의 재판 종류·병합 번호·기존 출처 연결 충돌을 검토해 등록 경로를 연결하고 전체 처리 규모를 확인하는 단계다. 과거/현재 번호 후보의 동일성 검토, 법률 본문 구조화, 보강 재취득, AWS 변경은 이번 범위에 포함하지 않았다.
