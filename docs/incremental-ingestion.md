# Source inventory와 증분 수집 계약

> **출처 ID 차집합 해석 — 2026-09-10:** 신규 contId/serialno는 새 출처 항목의 관찰이며 신규 판례 확정이 아니다. 기존 번호 미조회·다른 번호 후보가 확인됐으므로 문서 동일성 대조 후 출처 독립 canonical에 연결한다. 미조회만으로 삭제·철회로 확정하거나 기존 연결을 덮어쓰지 않는다. [identity 정책](case-identity.md) 참조.


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
