# 데이터 schema 설계 계약

> **재판결과 업무키 — 2026-09-10 사용자 규칙:** 법원 명칭 + 사건번호 + 재판 종류가 특정 재판결과를 식별한다. 기존 CourtCaseKey(court, case_number)는 사건 단위로 유지하고, 별도의 세 요소 키를 출처 독립 canonical에 연결한다. 재판 종류 결측·상충은 명시적으로 보존하며 날짜를 필수 키에 추가하지 않는다. [identity 계약](case-identity.md) 참조. 세 요소 모델·정규화·DB 제약은 후속 구현이며 아래 기존 모델 구현 기록과 구분한다.

2026-09-10: backend/src/klegal_gold/domain/에 Pydantic 2 모델 초안과 schema 0.1.0을 구현했다. DB·실제 import·resolver는 미구현이다. legacy provenance와 개별 결정 문서 대표 단위는 후속으로 확정했다. 개발 중 0.1.0 bundle에 LegacyRow/LegacyCaseRecord/LegacyImportProvenance를 추가했으며 별도 운영 릴리스를 만든 것은 아니다. DB·전체 corpus import 완료를 뜻하지 않는다.

| 모델 | 주요 필드·불변식 |
| --- | --- |
| SourceCaseIdentifier / SourceCaseMetadata | source, opaque source_id; 원/정규화 court·date·전체 case_numbers·disposition·metadata 상태 |
| CanonicalCaseIdentity | 독립 canonical_id, nullable court/date, case_numbers, source_identifiers, link revision |
| IdentityResolution | status EXACT/HIGH_CONFIDENCE/AMBIGUOUS/UNMATCHED/CONFLICT, score, signals, reasons, 후보 versions, resolver version |
| InventorySnapshot | source, retrieved_at, total_count, source_ids, metadata_hash, collector_version; per-ID metadata hash, scope, completeness, 실패 pages |
| SourceArtifact | artifact_id/type/source/parent, URL, 실제 취득 시각·MIME·sha256·size·path, order |
| VisualAssetReference | reference_id/type/original_src/source page/locator/order/alt/전후 문맥, resolved URL, acquisition state; 미취득 값은 null |
| DocumentBlock | block_id/order/kind, parent artifact, text span 또는 asset reference; 추정 layout 금지 |
| LegalCase | canonical 참조, source versions, metadata, full_text nullable, issues/summaries 배열, reasoning nullable, authorities, blocks/artifacts, fidelity·field availability, provenance |
| LegalIssueUnit | identity link revision 및 source versions, 원/정규화 issue/answer, evidence/authority, alignment·quality·review·eligibility |
| EvidenceSpan / VisualEvidenceReference | 텍스트 evidence는 artifact+field+code point [start,end)+text; 시각 evidence는 artifact/reference/block/page를 별도 참조 |

모델은 frozen이며 컬렉션은 tuple + default_factory로 보존한다. JSON에서는 배열로 직렬화한다. 빈 issues/summaries 및 null reasoning은 유효한 LegalCase다. 단, 잘못된 타입·깨진 provenance를 결측 허용으로 숨기지 않는다. 스캔은 text가 없어도 관찰된 artifact/identity/provenance를 가진 정상 record가 될 수 있다.

LegalCase 저장 검증과 LegalIssueUnit gold 검증을 분리한다. editorial 데이터가 없으면 0 issue units일 수 있다. 부분 요지만 있으면 보존하고 추측해서 issue를 만들지 않는다. 구조화 source는 seed/evaluation 후보이며 자동으로 gold는 아니다.

Source quality tier는 processing class, has_visual_assets/visual_asset_count/requires_ocr는 nullable 관찰값이다. detection scope/status와 결측 사유를 둔다. UNKNOWN을 false/0으로 바꾸지 않는다. PDF_TEXT/SCAN은 실제 분류 근거가 있을 때만 사용한다.

기본 gold는 명시적 issue-answer alignment, 유효 evidence/provenance, 중복·schema 검증 및 필요한 fidelity를 통과해야 한다. 불확실한 cross-source 링크에 의존한 조합은 gold 제외한다. cross-source UNMATCHED라도 한 source 안에서 근거가 완결된 issue는 그 사실을 명시해 별도로 평가할 수 있다. canonical 기준 중복 판정 때문에 출처가 다른 모든 issue를 무조건 한 건으로 줄이지 않는다.

JSONL/Parquet에 enum/null/중첩 배열을 일관되게 직렬화하고 round-trip을 검증한다. manifest에는 case/issue/asset 건수를 별도 표기하고 no-editorial-data·identity·fidelity·부분 실패 분포와 포함 정책을 기록한다. raw source URL의 비밀 parameter는 export하지 않는다.

PostgreSQL에는 source key unique, canonical registry/link revision, snapshot/ledger, artifact 참조·asset 상태, 사용자·작업·검토와 projection을 둔다. registry/link history는 단순 재수집으로 덮어쓸 수 없는 운영 기록이다. asset binary·raw·dataset은 파일로 유지하고 DB와 함께 복구 가능해야 한다.


## 구현된 계약과 적용 범위

- [JSON Schema 0.1.0](schemas/domain-0.1.0.json)은 HTTP OpenAPI와 별개다. backend에서 `uv run python scripts/export_domain_schema.py`로 재생성하며 snapshot 일치 테스트가 있다.
- SourceCaseIdentifier의 source namespace는 scourt/law_go_kr/lawnb/legacy_import다. 이는 수집 adapter 구현 여부를 뜻하지 않는다. 숫자 ID는 adapter가 의미를 확인한 후 명시적으로 문자열로 변환하며 domain은 숫자 타입을 암묵적으로 받지 않는다.
- Canonical ID는 opaque 문자열이다. UUID만 허용하지 않는다. **CourtCaseKey(court, case_number)**를 별도로 보존하며 업무키와 개별 판결/결정 문서의 관계는 [identity](case-identity.md)를 따른다.
- 날짜는 ISO 날짜, 취득 시각은 timezone-aware 입력을 UTC로 저장한다. 숫자 timestamp와 naive datetime, 숫자/blank 사건번호 및 알려지지 않은 필드는 거부한다. 기존 decision_date의 parser 객체는 날짜로 들어갈 수 없다.
- acquired artifact는 hash·MIME·크기·상대 storage key를 갖는다. RESPONSE_BYTES는 raw hash와 일치해야 한다. ASSET_BYTES/DOM_SNAPSHOT/EXTRACTED_TEXT/DERIVED는 부모 artifact를 참조한다. storage key는 DATA_DIR 아래 상대키이며 최종 경로·symlink·원자성 검증은 storage adapter 책임이다.
- reference는 acquired artifact ID가 없으면 취득 완료가 아니다. PDF_SCAN/PDF_TEXT에는 실제 분류 근거를 기록한다. nullable visual/ocr 상태를 0/false로 채우지 않는다.
- LegalCase는 field availability와 실제 필드의 유무, source provenance·artifact·block 참조 및 순환 여부를 검사한다. 본문 없는 scan 및 editorial 결측도 보존할 수 있다.
- TextSpan은 code point [start,end) 및 길이를 검사한다. `verify()`가 실제 source text 일치를 검사하며 `validate_issue_evidence()`는 SourceText의 artifact·field·source version·extractor version도 대조한다. 파일 내용 hash 검증과 법적 의미 판정은 별도다.
- issue_revision은 모델에서 재계산하며 제공된 값이 다르면 거부한다. 동일 입력 내용·evidence 순서·규칙에는 동일 SHA-256이다. canonical ID/link revision, run_id·dataset_version·취득 시각·검토 상태는 content revision 입력에서 제외한다.
- ReviewDecision과 GoldAssessment는 정확한 issue/link revision을 고정한다. 변경 후 과거 승인·평가를 자동 승계하지 않는다. 자동 quality passed와 human approved는 서로 다른 상태다.
- GoldAssessment는 schema/alignment/evidence/provenance/duplicate/identity/fidelity의 체크 이력을 요구하는 결과 저장 계약이다. 모델 생성이나 체크 이름 기입만으로 실제 검증을 수행한 것이 아니다. 운영에서는 Step 9 검증기만 결과를 생성해야 한다. 현재 gold export나 전체 적합성 판정은 구현하지 않았다.

주요 모델 오류 코드는 INVALID_TEXT_SPAN, EVIDENCE_OUT_OF_RANGE, EVIDENCE_TEXT_MISMATCH, EVIDENCE_SOURCE_VERSION_MISMATCH, RAW_PROVENANCE_MISMATCH, FIELD_AVAILABILITY_MISMATCH, INSUFFICIENT_EXACT_METADATA, NON_UNIQUE_EXACT_CANDIDATE, UNPROVEN_COMPLETE_INVENTORY, STALE_REVIEW, STALE_GOLD_ASSESSMENT다. Pydantic의 scalar type/enum 오류와 구분한다. 원자료를 삭제하지 않고 후속 validation report에 사유를 기록하는 계약이다.

JSON/model round-trip과 합성 회귀를 검증했다. Parquet·실제 import·full gold validation·DB unique/transaction은 후속 단계이며 현재 통과로 표시하지 않는다.

## Legacy staging 계약 추가

[legacy import 계약](legacy-import-contract.md)의 LegacyCaseRecord는 원래 필드·타입·snapshot 행 locator와 검증 전 문서 ID 후보를 보존한다. 역사적 HTTP hash/취득시각/URL은 null로 강제하고 결측 이유를 둔다. LegacyStoredText는 저장 문자열 UTF-8 hash와 실제 파일 hash를 구분한다. 일반 RawLegalCase/LegalCase의 실제 응답 provenance 제약은 유지한다. staging을 gold 또는 전체 구조화 완료로 사용하지 않는다. 실제 metadata 15행·저장 HTML 4개의 JSONL round-trip과 재실행 content revision을 검증했다.

## Step 2A 후속 구현

PostgreSQL 저장·migration·artifact/취득 이력·legacy 표본 저장·registry revision/snapshot·worker 복구를 구현했다. [현재 구현과 검증 범위](persistence-and-jobs.md) 참조. 위 Step 2 시점의 DB 미구현 기록을 보완하며 전체 corpus import 완료를 의미하지 않는다.
