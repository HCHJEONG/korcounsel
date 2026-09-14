# Source inventory와 증분 수집 계약

> **출처 ID 차집합 해석 — 2026-09-10:** 신규 contId/serialno는 새 출처 항목의 관찰이며 신규 판례 확정이 아니다. 기존 번호 미조회·다른 번호 후보가 확인됐으므로 문서 동일성 대조 후 출처 독립 canonical에 연결한다. 미조회만으로 삭제·철회로 확정하거나 기존 연결을 덮어쓰지 않는다. [identity 정책](case-identity.md) 참조.



> **inventory delta 기반 구현 — 2026-09-11:** `ingestion.delta`가 동일 source·scope의 immutable inventory를 비교하여 `NEW`, `CHANGED`, `UNCHANGED`, `LEGACY_KNOWN`, `MISSING`, `ABSENCE_UNCONFIRMED`으로 기록한다. 두 snapshot이 모두 `COMPLETE`일 때만 `MISSING`을 허용하고, 그 외에는 부재를 확정하지 않는다. 새/변경 ID와 기존 ledger의 미완료 ID만 상세 취득 후보로 돌려준다. `LEGACY_KNOWN`은 corrected Parquet에서 계승할 기존 source ID 기준선에 이미 있다는 뜻일 뿐, canonical 연결이나 본문 최신성을 확정하지 않는다. 결과는 부모 inventory artifact hash를 검증한 뒤 파생 immutable artifact로 저장한다. corrected Parquet 실측은 89,130행 중 유효한 고유 contId 88,607개와 보류값 454개이며 bundle SHA-256은 `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`다. `klegal ops preserve-legacy-scourt-catalog <parquet-path>`가 이 기준선을 immutable artifact로 등록한다. `klegal ops plan-inventory-delta <current-snapshot-id> <legacy-catalog-artifact-id> [baseline-snapshot-id]`가 보존된 입력만 비교해 delta artifact와 건수를 출력한다. `klegal ops submit-delta-scourt-details <request-key-prefix> <delta-artifact-id> [max-details]`는 그 artifact의 `NEW`·`CHANGED`만 1~50건씩 idempotent detail job으로 등록한다. live 목록 실행과 worker의 실제 detail 취득은 다음 단계다.

관리자 실행 원칙(2026-09-11): 정기 실행을 두지 않는다. 인증된 관리자만 웹의 신규 판례 증보 시작으로 제한된 scourt inventory job을 명시적으로 등록한다. 작업이 성공하면 같은 화면에서 저장된 snapshot과 legacy catalog의 delta를 계산해 NEW·CHANGED 후보 수를 확인한다. 이 단계는 목록 관찰과 후보 계획만 수행하며, detail 수집은 같은 화면에서 1~50건의 제한된 batch로 명시 등록하며, lawgo 조문 보강·canonical 연결은 각각 별도 관리자 작업으로 남긴다.

2026-09-12 로컬 실증: 관리자 API 경로로 1페이지 20건 inventory를 실행해 20건 `NEW` delta를 보존했고, 그중 1건(`2026000043180`)의 상세 본문을 수집했다. worker는 source artifact·HTML 관찰 manifest와 함께 immutable `CURRENT_SOURCE` reader manifest를 만들고 job checkpoint에 reader document ID를 기록한다. 인증된 `/api/reader` 목록과 보존 HTML 응답을 확인했다. 이 표본은 이미지 참조가 0건이어서 image acquisition·lawgo 조문 보강은 발생하지 않았다. 이어 `/api/cases/search`와 화면 결과를 legacy Parquet와 `CURRENT_SOURCE` reader를 함께 표시하도록 연결했고, `2026두30340` 검색이 `CURRENT_SOURCE` 1건과 reader document ID를 반환하고 해당 HTML이 200으로 열림을 확인했다. 현재 증분 reader의 본문 검색은 보존 manifest를 순회하는 제한된 초기 구현이므로, 수집량이 커지기 전에 재구성 가능한 검색 projection을 별도 추가한다. 다음 단계는 lawgo 연결·조문 보강이다.

2026-09-09 추가 지시 반영. 구현 전 설계. 레거시 `_02`의 contId 집합 차이를 계승하며 선고일을 등록일로 해석하지 않는다.

## Snapshot

`data/manifests/`에 source별 immutable inventory를 저장한다. source, retrieved_at, total_count, 정렬·중복 제거된 source_ids, metadata_hash, collector_version이 필수다. 개별 ID의 metadata hash도 보존해야 CHANGED를 계산할 수 있다. snapshot 전체 hash만으로 어떤 ID가 바뀌었는지 추정하지 않는다.

추가로 snapshot_id, query/filter 범위, scope_hash, 시작/종료 시각, page/cursor·실패 page, observed_unique_count, completeness(COMPLETE/PARTIAL/UNKNOWN), hash 정규화 규칙을 기록한다. ID 목록이 커지면 hash가 고정된 별도 inventory artifact를 참조할 수 있다. 제한 100건 데모를 source 전체 snapshot으로 표시하지 않는다.

페이지 이동 중 자료 추가·삭제, 중복 page, total 변동은 탐지한다. 전체 count가 같다는 사실만으로 안정된 snapshot을 보장하지 않는다. 비교 가능한 동일 범위와 수집 완전성 검증이 있어야 disappearance를 추론할 수 있다. 그렇지 않으면 누락 판정을 보류한다.

## 비교와 실행

| delta | 의미 / 처리 |
| --- | --- |
| NEW | 비교 기준 inventory에 없는 source ID. 이미 저장된 source key는 재사용하고 신규 상세 취득을 등록 |
| UNCHANGED | ID 및 관찰 metadata가 동일. 본문이 바뀌지 않았다는 증거는 아님 |
| CHANGED | 같은 ID의 관찰 metadata hash가 다름. 상세 refresh 후보 |
| MISSING | 동일 범위의 충분히 완전한 snapshot에서 이전 ID가 보이지 않음. local raw 삭제 금지 |

inventory 비교와 fetch ledger를 함께 사용한다. 이전 snapshot에는 있었으나 상세 취득에 실패한 ID를 UNCHANGED라는 이유로 영원히 건너뛰지 않는다. 계획된 작업·성공 hash·실패·시도·checkpoint를 source key와 함께 보존한다. 중단 후 같은 입력/계획으로 재개하고 source ID별 중복 claim을 방지한다.

신규 수집 모드에서는 새 ID와 미완료 실패 작업만 fetch한다. 기존 ID 본문 변경 감지는 별도 refresh 정책(명시적 전체/표본/주기·metadata 변경 우선)을 통해 실제 재조회한다. 동일 source_id에서 raw hash가 바뀌면 SOURCE_UPDATED 이벤트와 새 source version을 기록한다. transport 차이에 의한 hash 변화와 법률 내용 수정 여부는 구분하며 자동으로 동일한 의미라고 단정하지 않는다.

availability는 ACTIVE/SOURCE_MISSING/WITHDRAWN/UNKNOWN으로 별도 관리한다. MISSING이나 HTTP 오류만으로 공식 철회 WITHDRAWN을 추론하지 않는다. 철회 근거·확인 시각을 남기고 과거 raw·release는 보존한다.

## 완료 기준

scourt metadata snapshot → 이전 snapshot 비교 → 신규 contId 및 실패 재시도 식별 → 신규 본문 취득 → law_go_kr 후보 매칭 → canonical 연결/미연결 출력 → 별도 refresh에서 hash 변경 검증까지 실제 증거를 남긴다. law_go_kr도 같은 inventory protocol을 사용한다. scourt live 수집 방식·조건이 미확인인 동안 fixture 기반 완료와 live 미완료를 구분한다.

회귀 검증에는 오래전에 선고했으나 새로 등록된 판례, duplicate IDs, 문자열/숫자 ID 입력 정규화, 부분 snapshot, 범위 변경, 같은 ID 본문 변경, 상세 실패 후 재개, source disappearance·복귀를 포함한다. 17시 종료 준비에서는 page 완료·fetch ledger를 checkpoint로 저장하고 부분 inventory를 COMPLETE로 승격하지 않는다.


## 기존 89,130행과 연결

최초 실행은 빈 DB에서 source 전체를 다시 수집하는 흐름이 아니다. 기존 snapshot의 공식 ID·원문/추출 필드·업무키·내용 버전을 import ledger에 등록하고, 이 기준으로 신규/미완료/refresh만 취득한다. 기존 metadata catalog는 2024년 보존 범위이며 현재 전체 목록이라고 가정하지 않는다. catalog에서 보이지 않는 기존 ID를 삭제하지 않는다. bootstrap import와 live inventory 수집의 완료 상태를 분리한다.

## 내용 보강도 증분으로 처리

[레거시 계승 전략](legacy-enrichment-and-incremental.md)에 따라 scourt 신규 본문, 미연결 lawgo 대조, 항목별 미완료 조문 보강을 각각 큐에 둔다. 기존 완료 본문·보강은 재사용한다. 본문·연결·조문/규칙 버전 변화 시 영향받는 보강만 재평가하고 이전 결과를 유지한다. 레거시에 구현된 신규 기준은 contId 차집합이며 serialno는 연결·보강 접근키였다. lawgo 변화 기반 재대조와 영속 ledger는 새 구현에서 보완한다.

## 선등록·후보강의 범위

2026-09-10 사용자 확정: scourt 본문을 기본 검증 후 먼저 등록하고 lawgo 대기/미연결 보강은 별도 작업으로 처리한다. 제공자가 연결한 조문 정보만 추가하며, 인용을 앱이 해석하여 법령 API로 직접 보강하지 않는다. 목록 변화·대기 기간에 따른 제한된 재시도로 미완료를 추적한다. 현행 사이트 구조 검증 전 과거 crawler를 대량 실행하지 않는다.

## 현재 본문 후속 job — 2026-09-14

상세 본문 보존 checkpoint 뒤 image acquisition → terminal 의존성 확인 reader refresh → lawgo 제공 연결 보강을 각각 별도 job으로 실행한다. 관리자의 명시 증보 요청에서 파생되는 후속 작업이며 정기 실행은 없다. 원문과 이전 reader는 불변이고, 이미지/lawgo 부분 실패는 본문 실패와 구분한다. 관리자 재보강 API·최신 revision 선택·실제 브라우저 검증 및 신규 이미지 실증 한계는 [현재 reader 보강 계약](current-reader-enrichment.md)을 따른다.


## 증보 강제 종료 경계 회귀 — 2026-09-14

기존 테스트에는 이미지 부분 실패·OSError 재시도, 103개 이미지의 50개 단위 checkpoint 재개, 의존 job 대기/최종 실패 후 reader 발급, 관리자 요청 중복 방지, 조문 실패/미연결 위치 유지, 오래된 root의 늦은 revision 검색 제외가 있다. 여기에 `test_current_reader_refresh.py::test_abrupt_exit_reclaims_lease_and_reuses_immutable_outputs`의 두 매개변수 시나리오를 추가했다.

- 이미지 첫 URL의 bytes·취득 ledger commit 이후 다음 URL에서 BaseException을 발생시켜 worker의 정상 실패 처리 없이 RUNNING 상태를 남긴다.
- 이미지 refresh가 immutable reader revision을 발급한 직후 PUBLISHED checkpoint 저장 전에 같은 방식으로 중단한다.

각 테스트는 `korcounsel_test`의 독립 임시 schema에서 해당 job의 lease만 만료시키고 새 Queue/Worker 객체로 재개한다. 이미지 성공 URL의 fetch가 총 1회임을 확인하고, reader 발급 후 중단한 경우 동일 revision을 재사용한다. 동일 요청 재전송은 같은 job ID를 반환하며 job은 2개만 존재한다. 반복 이미지 2곳은 동일 bytes를 반환하고 실패/대기 위치를 유지하며 검색에는 최신 reader 1개만 남는다. 기존 원문 manifest bytes·artifact 행·취득 시도 행은 불변이고 job 시도 이력은 LEASE_EXPIRED → SUCCEEDED다.

이는 합성 종료 주입과 실제 PostgreSQL 영속 상태를 결합한 회귀다. OS SIGKILL, 전원 장애, 실제 외부 제공자 연결 중단을 실행한 시험은 아니다. 운영 corpus·worker를 중단하거나 환경파일을 수정하지 않았다. 제품 코드·UI 수정 없이 기존 복구 계약을 검증하는 테스트만 추가했다.

검증 결과: 관련 reader refresh 통합 11개 통과 후 전체 Python/PostgreSQL **725개 통과**(66.71초, 기존 의존성/프로세스 경고 4개). ruff check·format --check, mypy(62 source files), pnpm lint·build, git diff --check를 통과했다. 프런트 동작 변경이 없어 이번 단계에서 브라우저 흐름을 재실행하지 않았다.
