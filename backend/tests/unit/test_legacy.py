"""Observed metadata and synthetic edge cases; no live calls or pickle loading."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from klegal_gold.domain.common import content_hash
from klegal_gold.domain.legacy import LegacyCaseRecord, LegacyField, LegacyRow, LegacyStoredText
from klegal_gold.identity.allocation import canonical_id_for_request
from klegal_gold.ingestion.legacy import identity_conflicts, legacy_content_revision, map_legacy_row

NOW = datetime(2026, 9, 10, tzinfo=UTC)
FIXTURE = Path(__file__).parents[1] / "fixtures/legacy/bootstrap-metadata.json"


def row(**changes):
    values = {
        "court_name": "대법원",
        "case_no": "2008재도11",
        "gmeta_contId": "2064767",
        "lmeta_serialno": "166330",
        "gmeta_sngoDay": "20110120",
        "lmeta_sngoDay": "2011.01.20",
        "case_full_no": "대법원 2011. 1. 20. 선고 2008재도11 판결",
        "reasoning": 0,
        "decision_items": "empty",
        "decision_gists": "",
    } | changes
    return LegacyRow(
        locator={"snapshot_sha256": "a" * 64, "position": 0, "original_index": "0"},
        coverage="FULL_ROW",
        fields=[
            LegacyField(
                name=name,
                original_type=type(value).__name__,
                encoding="STRING"
                if isinstance(value, str)
                else "INTEGER"
                if value is not None
                else "NULL",
                value=value,
            )
            for name, value in values.items()
        ],
    )


def test_preservation_and_unknown_history():
    original = row()
    result = map_legacy_row(original, imported_at=NOW)
    assert result.original == original
    assert result.document_id_proposal == canonical_id_for_request(result.preservation_id)
    assert result.provenance.historical_raw_content_hash is None
    assert result.provenance.historical_retrieved_at is None
    assert result.identity_state == "LEGACY_OBSERVED"
    assert result.asset_acquisition_state == "UNKNOWN"
    assert result.body_state == "NOT_INCLUDED"
    assert "LEGACY_FIELD_AVAILABILITY_UNKNOWN:reasoning" in result.reasons
    assert LegacyCaseRecord.model_validate_json(result.model_dump_json()) == result


def test_import_time_is_not_content_revision():
    a = map_legacy_row(row(), imported_at=NOW)
    b = map_legacy_row(row(), imported_at=NOW.replace(day=11))
    assert legacy_content_revision(a) == legacy_content_revision(b)
    c = map_legacy_row(row(reasoning="새 저장 문자열"), imported_at=NOW)
    assert legacy_content_revision(a) != legacy_content_revision(c)


@pytest.mark.parametrize(
    "changes",
    [
        {"lmeta_sngoDay": "2010.10.29"},
        {"gmeta_sngoDay": "20110230"},
        {"case_full_no": "대법원 2010. 10. 29.자 2008재도11 결정"},
    ],
)
def test_conflicting_or_invalid_date_is_not_silently_repaired(changes):
    result = map_legacy_row(row(**changes), imported_at=NOW)
    assert result.metadata.decision_date is None
    assert "DECISION_DATE_UNRESOLVED" in result.reasons


@pytest.mark.parametrize("missing_id", [0, "0", "empty", None])
def test_missing_ids_use_local_proposal_and_preserve_business_key(missing_id):
    result = map_legacy_row(row(gmeta_contId="empty", lmeta_serialno=missing_id), imported_at=NOW)
    assert result.observed_source_ids == ()
    assert result.document_id_proposal == canonical_id_for_request(result.preservation_id)
    assert result.business_key.case_number == "2008재도11"
    assert result.original.fields[2].value == "empty"


def test_namespaces_and_whitespace_ids():
    result = map_legacy_row(row(gmeta_contId="123", lmeta_serialno="123"), imported_at=NOW)
    assert len(set(result.observed_source_ids)) == 2
    dirty = map_legacy_row(row(gmeta_contId=" 123 "), imported_at=NOW)
    assert "NONCANONICAL_SOURCE_ID:gmeta_contId" in dirty.reasons
    assert dirty.document_id_proposal == result.document_id_proposal


def test_opaque_date_and_merged_docket_remain_preserved():
    original = row(case_no="2008재도11, 2008재도12")
    original = LegacyRow.model_validate(
        original.model_dump()
        | {
            "fields": [
                *original.fields,
                LegacyField(
                    name="decision_date",
                    original_type="parser",
                    encoding="OPAQUE",
                ),
            ],
        }
    )
    result = map_legacy_row(original, imported_at=NOW)
    assert result.business_key.case_number == "2008재도11, 2008재도12"
    assert str(result.metadata.decision_date) == "2011-01-20"
    assert "OPAQUE_VALUE_PRESERVED:decision_date" in result.reasons


def test_enriched_html_remains_exact_and_unverified():
    text = '<a jtable="<table><tr><td>조문</td></tr></table>">제1조</a>😀'
    saved = LegacyStoredText(
        role="ENRICHED_HTML",
        original_locator="sample.txt",
        text=text,
        utf8_sha256=content_hash(text.encode()),
    )
    original = row()
    original = LegacyRow.model_validate(original.model_dump() | {"stored_texts": [saved]})
    result = map_legacy_row(original, imported_at=NOW)
    assert result.body_state == "PRESERVED"
    assert result.enrichment_state == "PRESERVED_UNVERIFIED"
    assert result.original.stored_texts[0].text == text
    assert LegacyCaseRecord.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError, match="LEGACY_TEXT_HASH_MISMATCH"):
        LegacyStoredText.model_validate(saved.model_dump() | {"text": text + " "})


@pytest.mark.parametrize(
    "encoding,value",
    [
        ("INTEGER", "0"),
        ("INTEGER", True),
        ("STRING", 0),
        ("OPAQUE", "parser"),
        ("NULL", ""),
        ("JSON", "NaN"),
    ],
)
def test_invalid_field_encodings(encoding, value):
    with pytest.raises(ValidationError):
        LegacyField(name="test", original_type="test", encoding=encoding, value=value)


def test_fabricated_history_is_rejected():
    record = map_legacy_row(row(), imported_at=NOW)
    value = record.model_dump()
    value["provenance"]["historical_raw_content_hash"] = "b" * 64
    with pytest.raises(ValidationError):
        LegacyCaseRecord.model_validate(value)


def test_duplicate_and_conflicting_source_reuse_preserves_both_rows():
    first = map_legacy_row(row(), imported_at=NOW)
    duplicate = map_legacy_row(row(), imported_at=NOW)
    assert identity_conflicts((first, duplicate)) == ()
    other = row(court_name="서울고등법원")
    other = LegacyRow.model_validate(
        other.model_dump()
        | {
            "locator": other.locator.model_dump() | {"position": 1, "original_index": "1"},
        }
    )
    second = map_legacy_row(other, imported_at=NOW)
    assert set(identity_conflicts((first, second))) == {
        first.preservation_id,
        second.preservation_id,
    }


def test_observed_metadata_projection_is_preserved_and_not_full_import():
    from klegal_gold.ingestion.legacy import row_from_metadata_projection

    observed = json.loads(FIXTURE.read_text())["rows"]
    records = [map_legacy_row(row_from_metadata_projection(v), imported_at=NOW) for v in observed]
    by_position = {r.original.locator.position: r for r in records}
    assert len(records) == 15
    assert by_position[190].document_id_proposal != by_position[232].document_id_proposal
    # Separate row proposals do not resolve duplicate legal identity.
    assert by_position[190].business_key == by_position[232].business_key
    assert by_position[190].preservation_id != by_position[232].preservation_id
    assert by_position[325].business_key == by_position[952].business_key
    assert by_position[325].document_id_proposal != by_position[952].document_id_proposal
    assert by_position[325].metadata.disposition == "판결"
    assert by_position[952].metadata.disposition == "결정"
    assert by_position[421].observed_source_ids == ()
    for record, value in zip(records, observed, strict=True):
        assert record.original.coverage == "METADATA_PROJECTION"
        assert record.body_state == "NOT_INCLUDED"
        assert LegacyCaseRecord.model_validate_json(record.model_dump_json()) == record
        fields = {f.name: f for f in record.original.fields}
        for name, original in value.items():
            if name not in {"snapshot_sha256", "position", "legacy_index"}:
                assert fields[name].value == original
