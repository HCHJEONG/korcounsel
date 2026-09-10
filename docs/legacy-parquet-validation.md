# Legacy Parquet 보존 검증 — 2026-09-10

## 결론과 범위

**Parquet을 전수 snapshot으로 사용하는 방향은 실제 표본에서 검증됐다. 다만 DataFrame을 자동 추론으로 바로 변환하면 실패하므로 명시적인 타입 보존 schema가 필요하다.** 이번 결과는 89,130행×60컬럼의 최상위 셀 타입 전수 조사와 146행의 Parquet 왕복 검증이다. 전체 corpus의 Parquet 변환·전체 값 대조·PostgreSQL 적재 완료를 뜻하지 않는다.

입력은 기존 pickle `df_glaw_corpus_fullest_gmeta_lmeta.pickle`, 6,525,441,901 bytes, SHA-256 `aa3d2c57d0f647b8c078df5784be5ef3e02e8b24cf40e543e9358b7b74dc7b69`다. 원본 해시 확인 후 기존 allowlist unpickler로 DataFrame을 읽고 종료 시 파일 크기·mtime·inode 불변을 확인했다. text 재구성, 원본 수정, source 재취득, canonical 변경은 수행하지 않았다.

## 전수 조사에서 확인한 사항

- **32컬럼은 모든 셀이 문자열**이다. 본문·HTML을 포함해 Parquet 문자열 컬럼으로 그대로 저장했다.
- 나머지 **28컬럼은 혼합형 또는 bool·float·dict·날짜·객체**다. 이번 보존 실험에서는 타입 태그를 가진 struct로 표현했다.
- 숫자 `0`과 문자열이 섞인 컬럼이 여러 개다. `case_unofficial_name`은 정수 87,984개·문자열 1,146개다. 같은 표본의 `Table.from_pandas` 자동 변환은 이 컬럼에서 `ArrowInvalid`로 실패했다.
- **`decision_date`의 89,129개는 날짜가 아닌 `dateutil.parser._parser.parser` 객체**이며, 원래 position 19,539의 1개만 `datetime.datetime`이다. 기존 조사에서 알려진 상태를 전수 재확인했다. 객체를 날짜로 간주하거나 다른 날짜 필드로 원행을 덮어쓰지 않는다.
- `lmeta_bubCode`는 NumPy float64이고 NaN이 456개다. NaN을 null이나 숫자 0으로 통합하지 않았다.
- `closing_argument`는 문자열 75,584개·date 13,546개, `party_info_dict`는 dict 89,126개·문자열 4개다.

컬럼별 dtype·타입별 수·sentinel 분포·최초 위치·최장 문자열 위치는 [전수 프로파일과 Python 검증 결과](legacy-parquet-verification.json)에 있다. 모든 dict 내부의 재귀 타입·키 schema를 전수 분류한 결과는 아니다. 중첩 값은 선택 표본에서 보존 검증했으며, 전수 변환에서는 행별 검증과 격리가 여전히 필요하다.

## 표본과 보존 표현

각 컬럼의 타입/sentinel별 최초 행, 최장 문자열 행, 약 100개의 일정 간격 행과 마지막 행의 합집합으로 **146행**을 선택했다. 확률 표본이나 압축률 추정용 무작위 표본이 아니다. 드문 datetime 1행도 포함한다.

원래 60컬럼의 이름과 순서를 유지하고 `__legacy_position`, 타입을 포함한 `__legacy_index`를 추가했다. 파일 metadata에는 원본 해시·경로·전체 행 수·선택 위치·컬럼별 pandas dtype·관찰 타입·표현 방식·index 정보를 담았다.

- 순수 문자열: native Parquet string으로 저장한다.
- 그 외: `original_type / encoding / text / integer` struct를 사용한다. 문자열과 정수는 별도 슬롯에 저장해 `0`, `"0"`, 빈 문자열을 구분한다.
- bool·float·date/datetime·dict/list/tuple은 기존 타입 명시 JSON 표현을 struct 내부에 보존한다. 따라서 이 실험은 모든 JSON 표현을 제거한 설계가 아니다. 일반 본문 컬럼은 직접 조회할 수 있지만 중첩 값은 별도 해석이 필요하다.
- int64 범위 밖 정수는 실험용 `BIG_INTEGER` 태그와 정확한 십진 문자열로 보존한다. 기존 worker의 LegacyField encoding을 변경한 것은 아니다.
- OPAQUE는 타입과 파일 metadata의 snapshot 해시, 행 position/index, 컬럼명으로 원본 pickle 위치를 찾는다. **객체 자체를 Parquet에서 복원했다고 주장하지 않는다.**
- manifest는 Parquet·대조 JSON의 SHA-256과 타입 포함 셀 표현의 누적 fingerprint를 기록한다. 누적 fingerprint는 OPAQUE 내부 객체 내용의 해시가 아니다.

이는 `legacy-parquet-experiment-1` 표본용 표현이다. 전수 exporter/worker의 확정 입력 계약, 부분 실패 복구·원자적 게시·partition/CAS 설계는 후속이다. bool/float·dict를 더 직접 조회하기 쉬운 native 타입으로 바꾸려면 같은 보존 검증을 다시 거쳐야 한다.

## 실제 검증 결과

| 항목 | 결과 |
| --- | --- |
| 실제 표본 | 146행×60컬럼 = 8,760셀 |
| 값 자체를 보존한 셀 | 8,615 |
| OPAQUE 원본 참조 | 145 |
| Python 대조 | 모든 표본 셀 표현·컬럼 순서·schema metadata 일치 |
| Node/DuckDB 대조 | 모든 표본 셀·행 위치·index 일치 |
| 선택 컬럼 읽기 | Python·Node 모두 일치 |
| Parquet Zstandard 파일 | 5,846,653 bytes |
| 같은 표본 Arrow 메모리 표현 | 26,675,865 bytes |
| 표본 쓰기 / 읽기·검증 | 약 0.075초 / 0.216초 |
| 원본 해시·로드·전수 프로파일·표본 작업 | 약 87.8초 |
| Python 프로세스 peak RSS | 8,603,024 KiB, 약 8.20GiB |
| Node 표본 조회·대조 | 약 0.209초, peak RSS 약 432MiB |

시간·메모리는 해당 로컬 실행의 관측값이며 캐시·장비 영향을 받는다. 표본 크기는 전체 Parquet 용량 예측치가 아니다. Node RSS에는 검증용 원문 대조 JSON 등을 메모리에 읽는 비용도 포함한다. small EC2에서 원본 pickle을 읽어도 된다는 근거로 사용하지 않는다.

[Node 실제 표본 결과](legacy-parquet-node-verification.json), [Node 합성 표본 결과](legacy-parquet-node-synthetic-verification.json).

합성 19행×3컬럼에서는 빈 문자열·0·"0"·None·NaN·무한대·음의 0·bool·list/tuple·정수/문자열 dict 키·NumPy scalar·2^53 초과/2^63 초과 정수·timezone datetime·OPAQUE·중복 index·한글/emoji/CRLF/NUL을 검증했다. Node의 BIGINT JSON 반환은 십진 문자열로 대조하며 JavaScript Number로 강제 변환하지 않았다.

Python 프로젝트 ruff check/format, mypy(42 source files) 통과. 기존 pytest는 **225 passed, 56 skipped**이며 skipped는 이번 실행에 개발 DB URL을 지정하지 않은 PostgreSQL integration이다. 분석 전용 신규 unittest 2개, 추가 Python 파일 ruff check/format, Node 문법 검사를 통과했다. 이번 작업은 DB 코드를 변경하지 않았다.

첫 내부 검증 시도는 비교 코드가 LegacyField의 schema_version을 누락해 실패했고 이를 보완했다. 성공 결과는 `-v2` 폴더의 artifact에 연결된다. 원본 데이터 손실을 수정한 작업이 아니다.

## 재현

분석용 버전은 Python 3.12, pandas 2.2.3, NumPy 1.26.4, PyArrow 25.0.0, Node v24.16.0, `@duckdb/node-api@1.5.5-r.4`다. 앱 pyproject/uv.lock·프런트 package/lock에는 의존성을 추가하지 않았다. Node 패키지는 data 아래 분석 전용 폴더에 설치했다. 실제 패키지 버전의 접미사까지 명시해야 한다.

backend에서 실행한다. OUTPUT은 아직 존재하지 않는 새 디렉터리여야 한다. DATA와 보고서 경로는 운영자가 명시하며, 스크립트에 레거시 경로를 고정하지 않는다.

```bash
uv run --with pandas==2.2.3 --with numpy==1.26.4 --with pyarrow==25.0.0 \
  python ../scripts/verify_legacy_parquet.py \
  --snapshot /absolute/path/to/corpus.pickle \
  --expected-sha256 aa3d2c57d0f647b8c078df5784be5ef3e02e8b24cf40e543e9358b7b74dc7b69 \
  --output /absolute/path/to/new-output \
  --report /absolute/path/to/report.json
```

루트에서 Node 검증을 실행한다.

```bash
npm install --prefix data/parquet-node-validation --save-exact @duckdb/node-api@1.5.5-r.4
node scripts/verify_legacy_parquet_node.mjs \
  data/parquet-validation-20260910-v2 data/parquet-node-validation \
  docs/legacy-parquet-node-verification.json
```

현재 실제 표본은 `data/parquet-validation-20260910-v2/`, 합성 표본은 `data/parquet-synthetic-20260910-v2/`에 있으며 Git에서 제외된다. 각 폴더의 sample.parquet·expected.json·manifest.json은 실험 산출물이며 운영 corpus release가 아니다.

형식·API 사용 근거: [Apache Arrow Parquet 문서](https://arrow.apache.org/docs/python/parquet.html), [DuckDB Node Neo API](https://duckdb.org/docs/current/clients/node_neo/overview).

## 다음 작업

보존 schema를 버전 있는 계약으로 고정하고, 분석용 전수 exporter에 제한된 batch/partition, hash manifest와 완료 표시를 구현한다. 원본 89,130행의 모든 셀에 대한 값/타입 대조·OPAQUE 집계·용량·실행시간·복구 검증을 통과한 후 worker의 Parquet 입력 경로와 PostgreSQL 적재를 연결한다. canonical 연결 확정은 별도 단계로 유지한다.
