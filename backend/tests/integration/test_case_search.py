from datetime import UTC, datetime

from klegal_gold.db.records import Records
from klegal_gold.domain.identity import CaseMetadata
from klegal_gold.domain.legacy import LegacyCaseRecord, LegacyImportProvenance, LegacyRow
from klegal_gold.ingestion.legacy_bundle import preserve_field
from klegal_gold.storage.files import FileStore


def record(position: int, court: str, case_no: str) -> LegacyCaseRecord:
    locator = {
        "snapshot_sha256": "a" * 64,
        "position": position,
        "original_index": str(position),
    }
    row = LegacyRow(
        locator=locator,
        fields=(
            preserve_field("court_name", court),
            preserve_field("case_no", case_no),
            preserve_field("case_full_no", f"{court} 2020. 1. 2. 선고 {case_no} 판결"),
            preserve_field("case_txt_scraped_with_tags", f"본문 고유문구{position}"),
        ),
        coverage="FULL_ROW",
    )
    preservation_id = f"legacy-row:{locator['snapshot_sha256']}:{position}"
    return LegacyCaseRecord(
        preservation_id=preservation_id,
        document_id_proposal=f"legacy-proposal:{position}",
        original=row,
        provenance=LegacyImportProvenance(
            locator=locator,
            imported_at=datetime(2026, 9, 11, tzinfo=UTC),
            import_rules_version="test-search-1",
        ),
        metadata=CaseMetadata(
            court=court,
            case_numbers=(case_no,),
            decision_date="2020-01-02",
        ),
        body_state="PRESERVED",
        enrichment_state="UNKNOWN",
        reasons=("TEST_FIXTURE",),
    )


def test_search_cases_matches_court_case_number_and_body_text(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    records.save_legacy(record(1, "대법원", "2020다123"), run_id="search")
    records.save_legacy(record(2, "서울고등법원", "2019나456"), run_id="search")
    records.save_legacy(record(3, "부산지방법원", "2018고789"), run_id="search")

    by_court = records.search_cases("서울", limit=10)
    assert [item.row_position for item in by_court] == [2]
    assert by_court[0].case_numbers == ("2019나456",)

    by_number = records.search_cases("2020다", limit=10)
    assert [item.row_position for item in by_number] == [1]

    by_body = records.search_cases("고유문구3", limit=10)
    assert [item.row_position for item in by_body] == [3]

    assert records.search_cases("없는문자열", limit=10) == []
