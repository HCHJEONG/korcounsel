# 날짜 전수 교정 검증과 이미지 보존 진행 — 2026-09-10

89,130행×60컬럼의 기존 DataFrame을 읽어 날짜 교정 후보와 이미지 inventory를 전수 생성했고, 그 overlay를 적용한 **전체 60컬럼 corrected Parquet**까지 만들었다. 원본 pickle·태그 있는 HTML은 수정하지 않았다. PostgreSQL 전수 적재, canonical 등록, 이미지 전수 취득 또는 GOLD 완료가 아니다.

## 날짜 결과

규칙 `legacy-date-repair-3`은 기존 로직의 목적을 계승하되 parser 생성자 오호출, 군사법원 이름의 사건번호 오인식, 날짜 공백·마지막 점, `변론종결일` heading을 보완한다. 기존 앱의 metadata 날짜 처리 함수를 재사용한다.

| 필드/상태 | 행 수 | 처리 |
| --- | ---: | --- |
| decision_date READY | 89,130 | 제목 날짜와 보존 HTML 대조, 존재하는 metadata와 일치 확인 |
| closing_argument READY | 13,518 | 단일 날짜·원문 구역 확인, 기존 유효 날짜와 대조 |
| closing_argument NOT_FOUND | 75,567 | 후보 없음; 기존값을 null로 덮어쓰지 않음 |
| closing_argument REVIEW_MULTIPLE | 45 | 여러 날짜와 당사자별 문맥 보존, 자동 적용 보류 |
| 행 격리 | 0 | 행 수와 산출물 건수 일치 |

선고일 중 408행은 양쪽 metadata 날짜가 없어 제목과 보존 HTML만으로 확인했다. READY는 결정론적 자료 대조 결과이며 사람이 법률적 정확성을 승인한 상태가 아니다. 원문 자체의 오기 가능성까지 배제하지 않는다. 기존 선고일은 parser 객체 89,129개와 오류 표식 datetime `2072-01-01` 1개였다. 군사법원 행(position 19539)은 제목의 `2002. 10. 24.`를 사용한다.

변론종결일 READY에는 기존 `no_info`에서 찾은 17행이 포함된다. 최종 규칙에서 기존 단일 날짜를 재현하지 못한 행은 0이다. 복수 날짜 45행은 정상적인 당사자별 종결일도 포함하므로 단순히 오류로 분류하거나 가장 늦은 날짜 하나로 확정하지 않는다. 후보를 못 찾은 NOT_FOUND도 실제 원문에 해당 정보가 없다는 전수 증명이 아니다. 상세 위치는 [후속 집계](legacy-repair-followup.json)에 있다.

## 변경분과 재현

출력: `data/repair-audit-20260910-v3/`. 원본 snapshot SHA-256은 `aa3d2c57d0f647b8c078df5784be5ef3e02e8b24cf40e543e9358b7b74dc7b69`이다.

- `dates.jsonl`: 89,130행, 원래 position/index, 원문·제목·가공 텍스트 hash, 이전값 또는 archive 위치, 후보·근거 위치·상태.
- `images.jsonl`: 89,130행, 원 src/name·등장 위치·매핑·해석 URL. v1/v2/v3의 이미지 inventory hash는 동일하다.
- `repair-overlay.parquet`: 89,130행×9컬럼, 3,746,031 bytes. 날짜는 date32, 적용 여부와 상태는 별도 컬럼이다. **apply=false의 null은 기존값 삭제 명령이 아니다.**
- overlay SHA-256: `60a57183eb3a9fe3d788216268364826b2c3d87965bd629b992831e09ce73df7`.
- 최종 60컬럼 export는 원본 snapshot·행 위치·HTML hash를 대조하여 변경분을 적용해야 한다. 원문 문자열과 수정 전 이력은 유지하며 미확정 값은 상태와 함께 보존한다.

[전수 실행 보고서](legacy-repair-full-audit.json), [Node 전체 셀 검증](repair-overlay-node-verification.json). PyArrow 자체 왕복과 DuckDB Node의 89,130행 전체 9컬럼 값 비교를 통과했다. Node v24.16.0, DuckDB Node API 1.5.5-r.4. 소요 약 273초, peak RSS 약 7.9 GiB이며 원본 시작 SHA 확인·종료 stat 불변을 검사했다.

## 전체 60컬럼 corrected Parquet

`scripts/export_corrected_legacy_parquet.py`로 기존 60컬럼 전체를 유지하고 `repair-overlay.parquet`의 apply=true 값만 반영한 전수 snapshot을 생성했다. `decision_date`는 89,130행 모두 교정 날짜로 바뀌었고, `closing_argument`는 기존 `no_info`였던 17행만 추가 교정했다. apply=false인 75,567행과 복수 후보 45행은 기존값을 삭제하거나 임의 확정하지 않았다.

- 출력: `data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet`
- 보고서: [Python 전수 export 보고서](corrected-legacy-parquet-full-export.json), [Node/DuckDB 검증](corrected-legacy-parquet-node-verification.json)
- Parquet SHA-256: `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`
- 크기: 1,215,542,924 bytes, row group 349개, row group size 256
- Python 검증: 전체 row group 재읽기·셀 표현 대조 통과, source stat 불변, OPAQUE 0셀
- Node 검증: 89,130행, 62컬럼(원 60컬럼 + locator 2컬럼), `decision_date` JSON 날짜 89,130행, `closing_argument` JSON 날짜 13,563행 확인
- 소요: 전체 약 342초, 쓰기 약 114초, 재읽기 검증 약 130초, peak RSS 약 15.0 GiB

이 Parquet은 교정된 snapshot이지 원본 pickle의 대체 폐기 근거가 아니다. manifest는 원본 snapshot hash와 overlay hash를 함께 고정한다.

재현은 backend 분석 환경에서 `scripts/export_corrected_legacy_parquet.py`에 `--snapshot`, `--expected-sha256`, `--overlay`, 새로운 `--output`, `--report`를 명시한다. pandas 2.2.3·NumPy 1.26.4·PyArrow 25.0.0은 분석용이며 앱 의존성으로 추가하지 않았다. allowlist unpickler를 사용하며 레거시 모듈의 최상위 코드를 실행하지 않는다.

## 이미지 전수 inventory

| 항목 | 수량 |
| --- | ---: |
| img가 있는 행 | 43,794 |
| 전체 img 등장 | 105,793 |
| alert_img 추정 UI 등장 | 90,345 |
| 나머지 등장 | 15,448 |
| 기존 imgDownload 경로 등장 | 10,860 |
| 해당 경로의 고유 URL / 출처 ID | 8,418 / 1,864 |
| flag 아이콘 등장 | 4,571 |
| src 없는 등장 | 17 |

아이콘 추정 항목도 원문에서 삭제하지 않는다. 8,418은 URL 개수이지 서로 다른 이미지 bytes 수나 현재 취득 가능 수가 아니다. 전체 해석 URL은 아이콘 포함 8,423개다. [집계](image-inventory-summary.json), 세부 원참조와 source ID별 대상은 `data/repair-audit-20260910/`에 보존했다.

**5행의 27개 이미지 참조에서 행 gmeta contId와 이미지 URL의 contId가 다르다.** 원래 이미지 참조를 행 ID로 자동 교체하면 안 된다. 정상 재사용인지 잘못된 보강인지 미확정이다. position은 3456, 8856, 28784, 39343, 41279다.

## 실제 파일 취득과 미해결 사례

현재 공식 제공자 매핑에 근거한 7개 문서 표본에서 총 38 URL의 이미지 bytes를 저장·검증했다. 문서별 저장량 합계는 372,121 bytes이며 전체 corpus 용량 추정치는 아니다. 현재 취득 파일을 과거 binary와 동일하다고 확정하지 않았다.

| source ID | 현재 URL / 성공 | 관찰 |
| --- | --- | --- |
| 2029039 | 33 / 33 | 34번 등장 연결; 3개 후 중단·재개, 최종 33개 재사용 시 신규 GET 0 |
| 1955834 | 1 / 1 | 2번 등장 연결 |
| 1956328 | 2 / 2 | 2번 등장 연결 |
| 1955787 | 2 / 0 | HTTP 200이나 0 bytes. 한 차례 재시도도 동일; EMPTY_IMAGE_BODY |
| 1970841 | 2 / 2 | 현재 6번 중 4번 연결. 기존 img3의 두 위치는 매핑 없어 미해결 |
| 1982647 | 0 / 0 | 현재도 14개 name만 있고 해석 주소 없음 |
| 2067140 | 0 / 0 | 기존 1개 이미지와 달리 현재 img 없음. 복구 성공 아님 |

**기존 name-only 17개는 이번 조사로 복구되지 않았다.** 다른 이미지의 취득 성공이나 현재 img 부재로 이를 성공 처리하지 않는다. 이미지 0개일 때 all_occurrences_linked를 false로 하는 회귀 검증도 추가했다. [확대 표본](image-expanded-sample.json), [이름만 있는 사례](image-name-only-sample.json), [빈 응답 재시도](image-empty-response-retry.json), [재사용 검증](image-sample-reuse.json).

`scripts/acquire_image_sample.py`는 분석용 단일 프로세스 도구다. 공식 HTTPS endpoint 제한·redirect 차단·15초 timeout/30초 deadline·16 MiB 상한·직렬 간격·429/503 중지·STOP/signal 중단·fsync ledger·SHA 기반 원자적 저장·재개 시 hash 재검증을 구현했다. Pillow 11.3.0의 verify와 첫 프레임 decode를 수행하며 OCR 또는 모든 애니메이션 프레임 해석은 하지 않는다. 응답 header나 HTTP 200만으로 성공 처리하지 않는다. 현재 매핑과 응답 artifact도 보존한다.

운영 worker의 claim/lease·다중 프로세스 제어·전체 대상 retry 정책·백업 복원 연결은 아직 구현하지 않았다. 저장된 mapping을 재사용하므로 새 source 관찰은 새 출력 디렉터리로 분리한다. 기존 source ID 변경·과거와 현재 본문 동일성은 별도 검토 대상이다.

## 검증과 다음 작업

- 새 분석 도구 회귀 19개 통과: 날짜 경계·복수 문맥·offset, 행 격리, hash 불일치, 이미지 오류·중단·재개·반복 위치·0개 이미지.
- 새 Python 파일 ruff 검사, Node syntax 검증. 기존 backend ruff/format/mypy 통과, pytest 225 passed / 56 skipped. 이번 corrected bundle 단계에서는 신규 bundle 변환 test와 PostgreSQL legacy import 통합 test를 통과했다.
- 원본 pickle과 레거시 코드·원문 HTML 수정, canonical 등록, AWS 변경은 없다. PostgreSQL 전수 적재는 로컬 개발 DB 보존 import 범위에서 완료했다.

corrected Parquet을 기존 full-row/DB import 경로에 연결하고 로컬 개발 PostgreSQL 보존 import까지 완료했다. 다음은 이미지별 영속 ledger와 worker 취득·재시도 연결, 8,418 URL 대상의 제한된 batch 확대, name-only/ID 불일치 예외 처리, 그리고 canonical 연결 후보 검토다. 복구 불가능한 이미지는 원참조와 실패 상태를 유지하고 완전 취득으로 표시하지 않는다.

## Parquet 직접 검색 UI — 2026-09-11

프론트 검증 검색은 PostgreSQL projection이 아니라 corrected Parquet snapshot을 직접 읽는다. FastAPI /api/cases/search는 LEGACY_PARQUET_PATH의 파일을 pyarrow batch scan으로 읽고, 각 행의 문자열화 가능한 컬럼 전체에서 단순 포함 검색을 수행한다. 실제 corrected Parquet에서 없는 검색어 0건과 대법원 3건 응답을 확인했다. 없는 검색어는 89,130행 전체를 끝까지 훑으므로 느릴 수 있다. DuckDB와 Polars는 아직 선택하지 않았다.

## Corrected bundle v2와 로컬 PostgreSQL import — 2026-09-11

보정된 Parquet data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet을 기존 legacy-full-row-bundle-1 CAS manifest로 변환했다. 최종 산출물은 data/corrected-legacy-bundle-20260911-v2이며 manifest hash는 c3e0ddeb7a23d0896a93c96c47aa1edd3664071a325be29287fa722c32be116b다. docs/corrected-legacy-bundle-export.json에 변환 보고서를 남겼다. v1 bundle은 locator original_index 문제를 고친 v2로 대체한다.

로컬 개발 PostgreSQL import job a2498da4-2321-480f-bbeb-fd3c278da1f6는 SUCCEEDED로 마감됐고, legacy_bundle_rows는 PRESERVED 89,130행, max(row_position)=89129다. legacy_records와 case_projection의 총수 89,145는 이전 15행 표본 import가 같은 개발 DB에 남아 있기 때문이다. 이 결과는 보존 import와 projection 생성 완료이며, canonical 등록·gold 확정·AWS 운영 DB 적재·이미지 binary 전수 취득 완료를 뜻하지 않는다.

초기 대량 import 시 60초 lease가 부족해 local dev 실패 job들이 생겼다. CLI service의 Queue lease를 300초로 늘렸고, 최종 성공 job은 heartbeat가 유지된 상태에서 전체 행을 보존했다. 실패 job들은 실험 이력으로 보되 최종 산출물 기준으로 사용하지 않는다.
