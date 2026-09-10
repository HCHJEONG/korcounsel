"""Synthetic domain contract tests; no live source, matching, OCR or export claims."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from klegal_gold.domain.artifacts import (
    DocumentBlock,
    EvidenceSpan,
    FidelityAssessment,
    SourceArtifact,
    SourceText,
    TextSpan,
    VisualAssetReference,
)
from klegal_gold.domain.cases import LegalCase, RawLegalCase
from klegal_gold.domain.common import content_hash
from klegal_gold.domain.identity import (
    CanonicalCaseIdentity,
    CaseMetadata,
    CourtCaseKey,
    IdentityLinkEvent,
    IdentityResolution,
    SourceCaseIdentifier,
    SourceCaseVersion,
)
from klegal_gold.domain.inventory import InventorySnapshot
from klegal_gold.domain.issues import GoldAssessment, LegalIssueUnit, validate_issue_evidence
from klegal_gold.domain.provenance import Provenance

NOW = "2026-09-10T10:00:00+09:00"
HASH = content_hash("합성 원본".encode())
SOURCE = {"source": "scourt", "source_id": "s1"}
VERSION = {"identifier": SOURCE, "raw_content_hash": HASH}
CANONICAL = "f2a1edab-7f67-4485-b6ba-69c837a3b7e5"


def artifact(**changes):
    return (
        dict(
            artifact_id="raw-1",
            source_version=VERSION,
            artifact_type="HTML",
            representation="RESPONSE_BYTES",
            source_url="https://example.invalid/cases/s1",
            retrieved_at=NOW,
            mime_type="text/html",
            sha256=HASH,
            file_size=13,
            storage_path="raw/s1.html",
        )
        | changes
    )


def provenance(**changes):
    return (
        dict(
            source_version=VERSION,
            raw_artifact_id="raw-1",
            source_url="https://example.invalid/cases/s1",
            retrieved_at=NOW,
            decoder_version="utf8-v1",
            text_extractor_version="fields-v1",
            parser_version="parse-v1",
            normalizer_version="normalize-v1",
            dataset_version="test-release",
            run_id="test-run",
        )
        | changes
    )


def identity(**changes):
    return (
        dict(canonical_id=CANONICAL, link_revision=1, metadata={}, source_identifiers=[SOURCE])
        | changes
    )


def case(**changes):
    return (
        dict(
            identity=identity(),
            source_versions=[VERSION],
            metadata={},
            artifacts=[artifact()],
            provenance=[provenance()],
        )
        | changes
    )


def span(**changes):
    return dict(artifact_id="raw-1", field="reasoning", text="근거", start=2, end=4) | changes


def issue(**changes):
    return (
        dict(
            canonical_id=CANONICAL,
            identity_link_revision=1,
            source_versions=[VERSION],
            issue_original="합성 쟁점",
            answer_original="합성 답변",
            evidence=[span(kind="REASONING")],
            alignment_status="aligned",
            identity_status="UNMATCHED",
            rules_version="alignment-v1",
            provenance=[provenance()],
        )
        | changes
    )


def snapshot(**changes):
    return (
        dict(
            snapshot_id="inventory-1",
            source="scourt",
            retrieved_at=NOW,
            started_at=NOW,
            finished_at=NOW,
            total_count=1,
            entries=[{"source_id": "s1", "metadata_hash": HASH}],
            observed_unique_count=1,
            metadata_hash=HASH,
            scope="supreme-only",
            scope_hash=HASH,
            collector_version="collector-v1",
            hash_rules_version="json-v1",
            completeness="COMPLETE",
            completeness_basis="all pages validated in this scope",
        )
        | changes
    )


def metadata(source=SOURCE):
    return dict(identifier=source, metadata_hash=HASH, normalized={}, normalizer_version="v1")


@pytest.mark.parametrize(
    "model,data",
    [
        (LegalCase, case()),
        (LegalIssueUnit, issue()),
        (InventorySnapshot, snapshot()),
        (SourceArtifact, artifact()),
        (Provenance, provenance()),
        (CanonicalCaseIdentity, identity()),
        (
            RawLegalCase,
            dict(source_version=VERSION, raw_artifact=artifact(), provenance=provenance()),
        ),
    ],
)
def test_json_roundtrip_and_schema(model, data):
    record = model.model_validate(data)
    assert model.model_validate_json(record.model_dump_json()) == record
    schema = model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "0.1.0"


def test_source_namespace_and_content_versions_are_distinct():
    left = SourceCaseIdentifier.model_validate(SOURCE)
    right = SourceCaseIdentifier(source="law_go_kr", source_id="s1")
    assert left != right
    assert SourceCaseVersion.model_validate(VERSION) != SourceCaseVersion(
        identifier=left, raw_content_hash=content_hash(b"changed")
    )
    assert content_hash(b"a\r\nb") != content_hash(b"a\nb")


@pytest.mark.parametrize(
    "model,data",
    [
        (SourceCaseIdentifier, SOURCE | {"source_id": 123}),
        (SourceCaseIdentifier, SOURCE | {"source_id": " "}),
        (SourceCaseIdentifier, SOURCE | {"source": "unknown-source"}),
        (SourceCaseVersion, VERSION | {"raw_content_hash": "bad"}),
        (SourceCaseVersion, VERSION | {"raw_content_hash": "A" * 64}),
        (CaseMetadata, {"decision_date": 20240101}),
        (CaseMetadata, {"decision_date": "2024-01-01T00:00:00"}),
        (CaseMetadata, {"decision_date": "2024-02-30"}),
        (CaseMetadata, {"case_numbers": [123]}),
        (Provenance, provenance(retrieved_at="2026-09-10T10:00:00")),
        (Provenance, provenance(retrieved_at=1234567890)),
        (LegalCase, case(unknown_field=True)),
        (LegalCase, case(schema_version="future")),
        (LegalCase, case(reasoning=123)),
        (LegalCase, case(reasoning="")),
        (LegalCase, case(reasoning="내용")),
        (LegalCase, case(field_availability={"issues": "PRESENT"})),
        (LegalCase, case(artifacts=[artifact(sha256="0" * 64)])),
        (LegalCase, case(provenance=[provenance(raw_artifact_id="missing")])),
        (LegalCase, case(source_versions=[VERSION, VERSION])),
    ],
)
def test_invalid_contracts_are_not_missing_values(model, data):
    with pytest.raises(ValidationError):
        model.model_validate(data)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.invalid/a",
        "https://example.invalid/a?OC=secret",
        "https://example.invalid/a?api_key=secret",
        "https://example.invalid/a?X-Amz-Signature=secret",
        "file:///tmp/a",
        "javascript:alert(1)",
    ],
)
def test_provenance_rejects_known_credential_urls(url):
    with pytest.raises(ValidationError, match="UNSAFE_SOURCE_URL"):
        Provenance.model_validate(provenance(source_url=url))


def test_times_normalize_to_utc_and_collections_are_immutable():
    record = LegalCase.model_validate(case())
    assert record.provenance[0].retrieved_at == datetime(2026, 9, 10, 1, tzinfo=UTC)
    assert record.issues == () and record.reasoning is None
    assert record.fidelity.has_visual_assets is None
    with pytest.raises(ValidationError, match="frozen"):
        record.metadata.court = "다른 법원"


@pytest.mark.parametrize(
    "fixture_id", ["no-editorial-data", "full-text-only", "source-only-summary"]
)
def test_existing_legacy_optional_editorial_contracts(fixture_id):
    path = Path(__file__).parents[1] / "fixtures/legacy/identity-fidelity-cases.json"
    fixtures = json.loads(path.read_text())
    source = next(c["input"] for c in fixtures["cases"] if c["id"] == fixture_id)
    values = {
        key: source[key]
        for key in ("issues", "summaries", "reasoning", "full_text")
        if key in source
    }
    for key in ("issues", "summaries"):
        if key in values:
            values[key] = [{"text": text} for text in values[key]]
    states = {key: "PRESENT" if value else "ABSENT_IN_SOURCE" for key, value in values.items()}
    record = LegalCase.model_validate(case(**values, field_availability=states))
    assert record.issues == ()
    if fixture_id == "source-only-summary":
        assert record.summaries[0].text == "합성 요지"


def test_merged_dockets_and_missing_date_survive():
    value = CaseMetadata(court="수원지방법원 성남지원", case_numbers=["2020다1", "2020다2"])
    assert value.case_numbers == ("2020다1", "2020다2")
    assert value.decision_date is None


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"start": -1}, "greater_than_equal"),
        ({"start": True}, "int_type"),
        ({"end": 2}, "INVALID_TEXT_SPAN"),
        ({"end": 5}, "INVALID_TEXT_SPAN"),
    ],
)
def test_bad_span_shape(changes, error):
    with pytest.raises(ValidationError, match=error):
        TextSpan.model_validate(span(**changes))


def source_text(text, **changes):
    return SourceText.model_validate(
        dict(
            artifact_id="raw-1",
            field="reasoning",
            source_version=VERSION,
            text_extractor_version="fields-v1",
            text=text,
        )
        | changes
    )


def test_exact_unicode_span_and_repeated_occurrences():
    source = "😀 근거 그리고 근거"
    evidence = EvidenceSpan.model_validate(span(kind="REASONING"))
    evidence.verify(source)
    with pytest.raises(ValueError, match="EVIDENCE_TEXT_MISMATCH"):
        TextSpan.model_validate(span(start=3, end=5)).verify(source)  # JS UTF-16 offset
    TextSpan.model_validate(span(start=9, end=11)).verify(source)
    with pytest.raises(ValueError, match="EVIDENCE_OUT_OF_RANGE"):
        evidence.verify("짧음")
    record = LegalIssueUnit.model_validate(issue())
    assert validate_issue_evidence(record, {("raw-1", "reasoning"): source_text(source)}) == ()
    assert validate_issue_evidence(record, {}) == ("EVIDENCE_SOURCE_NOT_LOADED",)
    assert validate_issue_evidence(record, {("raw-1", "reasoning"): source_text("다른 문장")}) == (
        "EVIDENCE_TEXT_MISMATCH",
    )


def test_asset_reference_does_not_claim_download_or_ocr():
    reference = VisualAssetReference(
        reference_id="img1",
        kind="PDF",
        original_src="../a.pdf",
        parent_artifact_id="raw-1",
        source_page="https://example.invalid/case/1",
        locator="a[1]",
        document_order=0,
    )
    assert reference.acquired_artifact_id is None
    assert FidelityAssessment().requires_ocr is None
    with pytest.raises(ValidationError, match="INVALID_ASSET_ACQUISITION"):
        VisualAssetReference.model_validate(
            reference.model_dump() | {"acquisition_state": "ACQUIRED"}
        )
    with pytest.raises(ValidationError):
        VisualAssetReference.model_validate(reference.model_dump() | {"sha256": HASH})


@pytest.mark.parametrize(
    "data,error",
    [
        ({"has_visual_assets": False}, "MISSING_DETECTION_SCOPE"),
        ({"has_visual_assets": False, "detection_scope": "api"}, "INCOMPLETE_NEGATIVE_DETECTION"),
        (
            {"has_visual_assets": True, "visual_asset_count": 0, "detection_scope": "api"},
            "CONFLICTING_VISUAL_COUNT",
        ),
        ({"tier": "SCAN"}, "SCAN_REQUIRES_OCR"),
        ({"requires_ocr": True, "ocr_status": "NOT_REQUIRED"}, "CONFLICTING_OCR_STATUS"),
    ],
)
def test_unknown_and_inconsistent_fidelity(data, error):
    with pytest.raises(ValidationError, match=error):
        FidelityAssessment.model_validate(data)


def test_scan_case_and_failed_asset_are_preservable():
    scan = artifact(
        artifact_type="PDF_SCAN",
        mime_type="application/pdf",
        classification_basis="synthetic text layer inspection",
    )
    reference = dict(
        reference_id="img1",
        kind="IMAGE",
        original_src="/a.png",
        parent_artifact_id="raw-1",
        source_page="https://example.invalid/case",
        locator="img[1]",
        document_order=1,
        acquisition_state="FAILED",
        failure_reason="TIMEOUT",
    )
    record = LegalCase.model_validate(
        case(
            artifacts=[scan],
            visual_assets=[reference],
            fidelity={"tier": "SCAN", "requires_ocr": True, "asset_status": "PARTIAL_FAILURE"},
        )
    )
    assert record.full_text is None and record.visual_assets[0].acquisition_state == "FAILED"
    with pytest.raises(ValidationError, match="MISSING_PDF_CLASSIFICATION_BASIS"):
        SourceArtifact.model_validate(scan | {"classification_basis": None})


def test_asset_bytes_and_block_placeholder_link_to_parent():
    image = artifact(
        artifact_id="image-1",
        representation="ASSET_BYTES",
        sha256="1" * 64,
        parent_artifact_id="raw-1",
        artifact_type="EMBEDDED_IMAGE",
    )
    ref = dict(
        reference_id="img1",
        kind="IMAGE",
        original_src="/a.png",
        parent_artifact_id="raw-1",
        source_page="https://example.invalid/case",
        locator="img[1]",
        document_order=1,
        acquisition_state="ACQUIRED",
        acquired_artifact_id="image-1",
    )
    block = dict(
        block_id="b1",
        parent_artifact_id="raw-1",
        document_order=1,
        kind="image",
        asset_reference_id="img1",
        numbering_path=["1", "가"],
    )
    record = LegalCase.model_validate(
        case(artifacts=[artifact(), image], visual_assets=[ref], blocks=[block])
    )
    assert record.blocks[0].numbering_path == ("1", "가")
    with pytest.raises(ValidationError, match="UNKNOWN_BLOCK_ASSET"):
        LegalCase.model_validate(case(blocks=[block]))
    with pytest.raises(ValidationError, match="BLOCK_ARTIFACT_MISMATCH"):
        DocumentBlock.model_validate(block | {"text_span": span(artifact_id="other")})


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"failed_pages": ["2"]}, "UNPROVEN_COMPLETE_INVENTORY"),
        ({"completeness_basis": None}, "UNPROVEN_COMPLETE_INVENTORY"),
        ({"total_count": 2}, "INCOMPLETE_INVENTORY_COUNT"),
        ({"observed_unique_count": 2}, "INVENTORY_COUNT_MISMATCH"),
        ({"entries": [{"source_id": "s1", "metadata_hash": HASH}] * 2}, "UNSORTED_OR_DUPLICATE"),
        (
            {
                "entries": [
                    {"source_id": "b", "metadata_hash": HASH},
                    {"source_id": "a", "metadata_hash": HASH},
                ]
            },
            "UNSORTED_OR_DUPLICATE",
        ),
        ({"started_at": "2027-01-01T00:00:00Z"}, "INVALID_INVENTORY_TIMES"),
    ],
)
def test_inventory_completeness_contract(changes, error):
    with pytest.raises(ValidationError, match=error):
        InventorySnapshot.model_validate(snapshot(**changes))


def test_partial_snapshot_preserves_failed_scope():
    record = InventorySnapshot.model_validate(
        snapshot(completeness="PARTIAL", failed_pages=["2"], total_count=2)
    )
    assert record.source_ids == ("s1",) and record.total_count == 2


def test_identity_resolution_rejects_unconfirmed_selection_and_conflict():
    other = {"source": "law_go_kr", "source_id": "l1"}
    candidate = dict(
        metadata=metadata(other),
        score=0.8,
        signals=[{"field": "court", "outcome": "MISMATCH", "reason": "different branch"}],
        reasons=["BRANCH_CONFLICT"],
    )
    data = dict(
        left=metadata(),
        candidates=[candidate],
        status="CONFLICT",
        reasons=["BRANCH_CONFLICT"],
        resolver_version="synthetic-v1",
        run_id="test-run",
    )
    assert IdentityResolution.model_validate(data).selected is None
    with pytest.raises(ValidationError, match="INVALID_IDENTITY_SELECTION"):
        IdentityResolution.model_validate(data | {"selected": other})
    with pytest.raises(ValidationError, match="CONFLICTING_IDENTITY_SELECTION"):
        IdentityResolution.model_validate(data | {"status": "EXACT", "selected": other})
    assert IdentityResolution.model_validate(data | {"status": "UNMATCHED", "candidates": []}).left


def test_existing_canonical_id_and_history_replay():
    allocated = uuid4()
    old = CanonicalCaseIdentity.model_validate(identity())
    new = identity(link_revision=2, metadata={"court": "대법원"})
    event = IdentityLinkEvent.model_validate(
        dict(
            event_id=allocated,
            operation="RELINK",
            previous=[old],
            resulting=[new],
            recorded_at=NOW,
            actor="synthetic-operator",
            reason="metadata correction",
        )
    )
    assert event.previous[0].metadata.court is None
    assert event.resulting[0].canonical_id == CANONICAL
    assert IdentityLinkEvent.model_validate_json(event.model_dump_json()) == event
    with pytest.raises(ValidationError, match="NON_INCREASING_LINK_REVISION"):
        IdentityLinkEvent.model_validate(event.model_dump() | {"resulting": [identity()]})


def test_issue_revision_content_change_relink_and_stale_review():
    original = LegalIssueUnit.model_validate(issue())
    changed = LegalIssueUnit.model_validate(issue(answer_original="수정된 답변"))
    assert original.issue_revision != changed.issue_revision
    assert (
        original.issue_revision
        == LegalIssueUnit.model_validate(issue(identity_link_revision=2)).issue_revision
    )
    assert (
        original.issue_revision
        == LegalIssueUnit.model_validate(
            issue(provenance=[provenance(run_id="rerun", dataset_version="next")])
        ).issue_revision
    )
    review = dict(
        issue_revision=original.issue_revision,
        identity_link_revision=1,
        source_versions=[VERSION],
        status="approved",
        reviewer="operator",
        recorded_at=NOW,
        reason="synthetic approval",
    )
    reviewed = LegalIssueUnit.model_validate(issue(review=review))
    assert reviewed.quality_status == "needs_review" and reviewed.gold is None
    with pytest.raises(ValidationError, match="STALE_REVIEW"):
        LegalIssueUnit.model_validate(issue(answer_original="다른 답변", review=review))
    with pytest.raises(ValidationError, match="STALE_REVIEW"):
        LegalIssueUnit.model_validate(issue(identity_link_revision=2, review=review))
    with pytest.raises(ValidationError, match="ISSUE_REVISION_MISMATCH"):
        LegalIssueUnit.model_validate(original.model_dump() | {"issue_revision": "0" * 64})


def test_ambiguous_issue_is_preserved_but_not_gold():
    record = LegalIssueUnit.model_validate(
        issue(
            answer_original=None, alignment_status="unmatched", reason_codes=["NO_MATCHING_SUMMARY"]
        )
    )
    assert record.answer_original is None and record.gold is None
    with pytest.raises(ValidationError, match="INCOMPLETE_GOLD_ASSESSMENT"):
        GoldAssessment(
            issue_revision=record.issue_revision,
            identity_link_revision=1,
            policy_version="gold-v1",
            status="ELIGIBLE",
        )
    with pytest.raises(ValidationError, match="MISSING_ALIGNED_TEXT"):
        LegalIssueUnit.model_validate(issue(answer_original=None))


@pytest.mark.parametrize("path", ["../raw/a", "/tmp/a", "C:/data/a", "raw\\a"])
def test_storage_keys_cannot_escape_data_root(path):
    with pytest.raises(ValidationError, match="INVALID_STORAGE_KEY"):
        SourceArtifact.model_validate(artifact(storage_path=path))


def test_evidence_must_use_pinned_source_version_and_field():
    record = LegalIssueUnit.model_validate(issue())
    wrong = source_text("😀 근거", source_version=VERSION | {"raw_content_hash": "0" * 64})
    assert validate_issue_evidence(record, {("raw-1", "reasoning"): wrong}) == (
        "EVIDENCE_SOURCE_VERSION_MISMATCH",
    )
    wrong = source_text("😀 근거", field="summary")
    assert validate_issue_evidence(record, {("raw-1", "reasoning"): wrong}) == (
        "EVIDENCE_FIELD_MISMATCH",
    )


def test_exact_requires_complete_unique_metadata():
    other = {"source": "law_go_kr", "source_id": "l1"}
    candidate = dict(
        metadata=metadata(other),
        score=1.0,
        signals=[{"field": "court", "outcome": "MATCH", "reason": "synthetic"}],
        reasons=["EXACT_RULE"],
    )
    data = dict(
        left=metadata(),
        candidates=[candidate],
        status="EXACT",
        selected=other,
        reasons=["EXACT_RULE"],
        resolver_version="synthetic-v1",
        run_id="test-run",
    )
    with pytest.raises(ValidationError, match="INSUFFICIENT_EXACT_METADATA"):
        IdentityResolution.model_validate(data)
    complete = dict(
        court="대법원",
        decision_date="2020-01-01",
        case_numbers=["2020다1", "2020다2"],
        disposition="판결",
    )
    data["left"]["normalized"] = complete
    candidate["metadata"]["normalized"] = complete
    assert IdentityResolution.model_validate(data).selected.source_id == "l1"
    duplicate = candidate | {
        "metadata": metadata(other | {"source_id": "l2"}) | {"normalized": complete}
    }
    with pytest.raises(ValidationError, match="NON_UNIQUE_EXACT_CANDIDATE"):
        IdentityResolution.model_validate(data | {"candidates": [candidate, duplicate]})


def test_cyclic_artifact_history_is_rejected():
    first = artifact(artifact_id="a", representation="DERIVED", parent_artifact_id="b")
    second = artifact(artifact_id="b", representation="DERIVED", parent_artifact_id="a")
    with pytest.raises(ValidationError, match="CYCLIC_DOCUMENT_REFERENCE"):
        LegalCase.model_validate(case(artifacts=[artifact(), first, second]))


def test_published_schema_matches_domain_contract():
    from klegal_gold.domain.schema import domain_json_schema

    path = Path(__file__).resolve().parents[3] / "docs/schemas/domain-0.1.0.json"
    assert json.loads(path.read_text()) == domain_json_schema()
    issue_schema = domain_json_schema()["$defs"]["LegalIssueUnit"]
    assert "issue_revision" in issue_schema["properties"]


def test_business_key_works_without_government_identifier():
    key = CourtCaseKey(court="서울중앙지방법원", case_number="2020가단12345")
    vendor = SourceCaseIdentifier(source="lawnb", source_id="existing-vendor-id")
    record = CanonicalCaseIdentity(
        canonical_id="existing-local-key",
        link_revision=1,
        metadata=CaseMetadata(),
        source_identifiers=[vendor],
        court_case_keys=[key],
    )
    assert record.court_case_keys == (key,)
    assert record.canonical_id == "existing-local-key"
    assert key != CourtCaseKey(court="서울동부지방법원", case_number="2020가단12345")
    assert CanonicalCaseIdentity.model_validate_json(record.model_dump_json()) == record


def test_government_based_canonical_id_is_not_forced_to_uuid():
    record = CanonicalCaseIdentity.model_validate(identity(canonical_id="scourt:123456"))
    assert record.canonical_id == "scourt:123456"
