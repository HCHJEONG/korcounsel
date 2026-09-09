# Source inventory와 증분 수집 계약

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
