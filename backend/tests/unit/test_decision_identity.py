"""Decision keys are business identity; source changes and dates are not allocation inputs."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_legacy import row

from klegal_gold.domain.identity import CaseMetadata, CourtCaseKey, DecisionKey
from klegal_gold.domain.legacy import LegacyCaseRecord
from klegal_gold.ingestion.legacy import map_legacy_row
from klegal_gold.normalize.decision import decision_keys, decision_kind, docket_aliases


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("판결", "판결"),
        ("전원합의체판결", "판결"),
        ("결정", "결정"),
        ("전원합의체결정", "결정"),
        ("중간판결", "중간판결"),
        ("명령", "명령"),
        ("재결", "재결"),
        (" 판결 ", "판결"),
        (None, None),
        ("", None),
        ("민사", None),
        ("기각", None),
        ("미상", None),
        ("판결/결정", None),
        ("전원합의체", None),
    ],
)
def test_kind_is_conservative(raw, expected):
    assert decision_kind(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("85후40, 41", ("85후40", "85후41")),
        ("2020다296741, 296758", ("2020다296741", "2020다296758")),
        ("2001나60578, 2002나1", ("2001나60578", "2002나1")),
        ("85후40", ("85후40",)),
        ("85후40 인용", ()),
        ("85후40/41", ()),
        ("85후40, ", ()),
        ("85후40, 40", ()),
    ],
)
def test_merged_aliases_preserve_all_or_remain_unresolved(raw, expected):
    assert docket_aliases(raw) == expected


def test_date_not_key_and_branch_and_kind_are_key():
    keys = (CourtCaseKey(court="서울지방법원 동부지원", case_number="85후40, 41"),)
    a = decision_keys(CaseMetadata(disposition="판결"), keys)
    b = decision_keys(CaseMetadata(disposition="판결", decision_date="1986-10-28"), keys)
    assert a == b
    assert len(a) == 2
    assert all(key.court == "서울지방법원 동부지원" for key in a)
    assert a != decision_keys(CaseMetadata(disposition="중간판결"), keys)
    assert decision_keys(CaseMetadata(), keys) == ()
    with pytest.raises(ValueError, match="CONFLICTING_DECISION_COURT"):
        decision_keys(CaseMetadata(court="다른법원", disposition="판결"), keys)
    with pytest.raises(ValidationError):
        DecisionKey(court="대법원", case_number="85후40, 41", decision_kind="판결")


def test_legacy_id_is_independent_of_source_and_content_but_stable_per_locator():
    now = datetime.now(UTC)
    first = map_legacy_row(row(), imported_at=now)
    changed = map_legacy_row(row(gmeta_contId="new", lmeta_serialno=None), imported_at=now)
    assert first.document_id_proposal == changed.document_id_proposal
    assert first.document_id_proposal.startswith("kc:")
    assert first.original != changed.original
    # Historical source-derived staging payload remains readable; not silently reissued.
    historical = first.model_dump()
    historical["document_id_proposal"] = "scourt:2064767"
    historical["provenance"]["import_rules_version"] = "legacy-staging-0.1.0"
    assert LegacyCaseRecord.model_validate(historical).document_id_proposal == "scourt:2064767"


def test_metadata_cannot_silently_drop_merged_aliases():
    keys = (CourtCaseKey(court="대법원", case_number="85후40"),)
    with pytest.raises(ValueError, match="CONFLICTING_DECISION_DOCKETS"):
        decision_keys(CaseMetadata(disposition="판결", case_numbers=("85후40, 41",)), keys)
    assert decision_keys(CaseMetadata(disposition="판결", case_numbers=("미상",)), keys) == ()


def test_missing_legacy_kind_preserves_original_and_reason():
    original = row(case_full_no="대법원 2011. 1. 20. 선고 2008재도11")
    result = map_legacy_row(original, imported_at=datetime.now(UTC))
    assert result.metadata.disposition is None
    assert "DECISION_KIND_UNRESOLVED" in result.reasons
    assert result.original == original
