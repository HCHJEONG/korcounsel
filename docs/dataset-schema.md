# 데이터 schema 설계 계약

2026-09-09 작성. Pydantic/DB schema 구현 전이며 구체적 serialization schema version은 Step 2에서 고정한다. 이 문서의 모델명은 계약 대상이다.

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

배열 기본값은 Pydantic 구현에서 default_factory를 사용한다. 빈 issues/summaries 및 null reasoning은 유효한 LegalCase다. 단, 잘못된 타입·깨진 provenance를 결측 허용으로 숨기지 않는다. 스캔은 text가 없어도 관찰된 artifact/identity/provenance를 가진 정상 record가 될 수 있다.

LegalCase 저장 검증과 LegalIssueUnit gold 검증을 분리한다. editorial 데이터가 없으면 0 issue units일 수 있다. 부분 요지만 있으면 보존하고 추측해서 issue를 만들지 않는다. 구조화 source는 seed/evaluation 후보이며 자동으로 gold는 아니다.

Source quality tier는 processing class, has_visual_assets/visual_asset_count/requires_ocr는 nullable 관찰값이다. detection scope/status와 결측 사유를 둔다. UNKNOWN을 false/0으로 바꾸지 않는다. PDF_TEXT/SCAN은 실제 분류 근거가 있을 때만 사용한다.

기본 gold는 명시적 issue-answer alignment, 유효 evidence/provenance, 중복·schema 검증 및 필요한 fidelity를 통과해야 한다. 불확실한 cross-source 링크에 의존한 조합은 gold 제외한다. cross-source UNMATCHED라도 한 source 안에서 근거가 완결된 issue는 그 사실을 명시해 별도로 평가할 수 있다. canonical 기준 중복 판정 때문에 출처가 다른 모든 issue를 무조건 한 건으로 줄이지 않는다.

JSONL/Parquet에 enum/null/중첩 배열을 일관되게 직렬화하고 round-trip을 검증한다. manifest에는 case/issue/asset 건수를 별도 표기하고 no-editorial-data·identity·fidelity·부분 실패 분포와 포함 정책을 기록한다. raw source URL의 비밀 parameter는 export하지 않는다.

PostgreSQL에는 source key unique, canonical registry/link revision, snapshot/ledger, artifact 참조·asset 상태, 사용자·작업·검토와 projection을 둔다. registry/link history는 단순 재수집으로 덮어쓸 수 없는 운영 기록이다. asset binary·raw·dataset은 파일로 유지하고 DB와 함께 복구 가능해야 한다.
