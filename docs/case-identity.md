# Canonical 판례 identity 계약

2026-09-09 추가 지시 반영. 구현 전 설계이며 클래스·DB·resolver는 아직 없다. [레거시 조사](legacy-case-identity-and-assets.md), [schema](dataset-schema.md)를 함께 따른다.

## 네 종류의 식별자

| 대상 | 키 / 의미 |
| --- | --- |
| SourceCaseIdentifier | `(source, source_id)`. scourt contId와 law_go_kr serialno는 서로 다른 namespace이며 opaque string |
| SourceCaseVersion | source 식별자 + raw_content_hash. 동일 ID의 수정된 원문은 새 버전 |
| CanonicalCaseIdentity | 한 법적 판례를 묶는 독립 canonical_id. source ID·사건번호·본문 hash 자체로 대체하지 않음 |
| LegalIssueUnit revision | 실제 사용한 source version·필드/위치·규칙 버전으로 식별. canonical 연결 변경과 내용 revision은 구분 |

CanonicalCaseIdentity에는 court, decision_date, case_numbers 전체, source_identifiers 및 연결 결정 revision을 둔다. 법원 지원·지부, 판결/결정/명령 등 disposition 차이를 후보 비교에 유지한다. 같은 사건번호라도 다른 날짜·결정이면 자동 병합하지 않는다. source별 원 metadata와 정규화값은 모두 보존한다.

canonical ID 생성 알고리즘은 Step 2의 설계 결정 대상으로 남긴다. 검토 기준은 source 추가·metadata 정정에도 안정성, 재실행/동시 생성 시 멱등성, 영속 registry snapshot 기반 재현성, merge/split 이력과 과거 링크 보존이다. mutable metadata hash 또는 첫 수집 source ID를 그대로 쓰는 방식은 채택하지 않는다. 하나의 source만 있는 정상 판례도 독립 canonical identity를 가질 수 있고 cross-source 상태는 UNMATCHED일 수 있다.

## Resolver와 상태

`CaseIdentityResolver.resolve(left: SourceCaseMetadata, candidates: Iterable[SourceCaseMetadata]) -> IdentityResolution`을 독립 subsystem으로 둔다. 후보 생성과 확정 판단을 분리하고 입력 순서를 바꿔도 결과가 같아야 한다.

| 상태 | 판정 계약 |
| --- | --- |
| EXACT | 완전한 사건번호 집합·검증된 법원·날짜 및 필요한 disposition의 강한 신호가 유일하게 일치하고 충돌 없음 |
| HIGH_CONFIDENCE | 병합 번호 부분 겹침 등 완전 equality는 아니나 명시적 강한 규칙을 만족한 유일 후보. 자동 연결 허용 규칙을 별도로 버전 관리 |
| AMBIGUOUS | 복수 타당 후보, 부족한 신호 또는 약한 유사도만 있음. 자동 확정하지 않음 |
| UNMATCHED | 충분한 후보 없음. source record를 보존하고 이후 재매칭 가능 |
| CONFLICT | 기존 확정 연결 또는 핵심 metadata 사이 명시적 모순. 자동 덮어쓰기 금지 |

결과에는 candidate IDs/versions, status, score, field별 MATCH/MISMATCH/MISSING 신호, reason codes, rule/resolver version, 실행 참조를 기록한다. 점수는 결정론적 규칙 점수이며 확률 97%처럼 표현하지 않는다. 숫자 가중치·threshold는 fixture 검증을 거쳐 Step 5A에서 고정한다. 점수가 높아도 충돌·복수 후보·불충분한 필수 신호를 덮어쓰지 못한다. 제목 fuzzy similarity만으로 확정하지 않는다.

첫 사건번호는 후보 검색의 단서로만 사용한다. 전체 병합 번호, 정확한 토큰 경계, 법원 계층과 날짜를 확인한다. 약칭 alias는 근거 있는 명시적 표로 버전 관리하고 지원을 상위 법원으로 뭉개지 않는다. 결측 날짜는 추측하거나 미래 날짜로 채우지 않는다.

## 연결과 정정의 provenance

source record를 합쳐 덮어쓰지 않는다. canonical은 versioned link를 모으며 각 필드의 origin을 유지한다. 서로 다른 source의 요지·이유를 사용하면 각각의 artifact·field를 명시하고 연결 결정 revision을 고정한다. 이미지 누락을 다른 source의 이미지로 보충하는 경우에도 같은 canonical이라는 이유만으로 위치를 추정하지 않는다.

merge/split/relink는 이전 결정을 보존하는 새 revision으로 남긴다. 이전 dataset과 검토 기록의 source/identity snapshot을 바꾸지 않는다. Phase 1은 결과·사유 조회, 사람의 연결 수정은 Phase 1.5의 별도 기록 작업이다. PostgreSQL에는 source key의 유일성, 유효한 연결 revision과 동시 생성 방지 제약을 구현한다.
