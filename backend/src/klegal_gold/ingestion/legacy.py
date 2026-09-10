"""Deterministic legacy staging mapper; no pickle, network, DB, or identity merging."""

import json
import re
from datetime import date, datetime
from typing import Literal

from klegal_gold.domain.common import content_hash
from klegal_gold.domain.identity import (
    CaseMetadata,
    CourtCaseKey,
    SourceCaseIdentifier,
    SourceSystem,
)
from klegal_gold.domain.legacy import (
    LegacyCaseRecord,
    LegacyField,
    LegacyImportProvenance,
    LegacyRow,
)
from klegal_gold.identity.allocation import canonical_id_for_request
from klegal_gold.normalize.decision import decision_kind, docket_aliases

IMPORT_RULES_VERSION = "legacy-staging-0.2.0"


def _text(field: LegacyField | None) -> str | None:
    if field is None or field.encoding != "STRING":
        return None
    assert isinstance(field.value, str)
    value = field.value.strip()
    return value if value and value != "empty" else None


def _date(value: str) -> date:
    if re.fullmatch(r"\d{8}", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", value):
        return date.fromisoformat(value.replace(".", "-"))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    raise ValueError("UNSUPPORTED_LEGACY_DATE")


def map_legacy_row(row: LegacyRow, *, imported_at: datetime) -> LegacyCaseRecord:
    """Preserve every input value and propose a source-independent registration ID."""
    fields = {field.name: field for field in row.fields}
    reasons = ["LEGACY_LINK_NOT_REVALIDATED"]
    ids: list[SourceCaseIdentifier] = []
    for name, source in (
        ("gmeta_contId", SourceSystem.SCOURT),
        ("lmeta_serialno", SourceSystem.LAW_GO_KR),
    ):
        value = _text(fields.get(name))
        if value is not None and value != "0":
            # IDs are opaque, but surrounding whitespace is not silently normalized.
            original = fields[name].value
            if original != value:
                reasons.append(f"NONCANONICAL_SOURCE_ID:{name}")
            else:
                ids.append(SourceCaseIdentifier(source=source, source_id=value))
        elif name in fields:
            reasons.append(f"MISSING_OR_INVALID_SOURCE_ID:{name}")
    court, docket = _text(fields.get("court_name")), _text(fields.get("case_no"))
    key = CourtCaseKey(court=court, case_number=docket) if court and docket else None
    if key is None:
        reasons.append("MISSING_BUSINESS_KEY")
    dates: dict[str, date] = {}
    invalid_date = False
    for name in ("gmeta_sngoDay", "lmeta_sngoDay", "decision_date"):
        field = fields.get(name)
        value = _text(field)
        if value is not None:
            try:
                dates[name] = _date(value)
            except ValueError:
                reasons.append(f"INVALID_DATE:{name}")
                invalid_date = True
        elif field is not None and field.encoding == "OPAQUE":
            reasons.append(f"OPAQUE_VALUE_PRESERVED:{name}")
    citation = _text(fields.get("case_full_no"))
    if citation:
        matches = re.findall(r"(?<!\d)(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.", citation)
        if len(matches) == 1:
            try:
                dates["case_full_no"] = date(*(int(v) for v in matches[0]))
            except ValueError:
                invalid_date = True
                reasons.append("INVALID_DATE:case_full_no")
        elif len(matches) > 1:
            invalid_date = True
            reasons.append("AMBIGUOUS_CITATION_DATE")
    agreed = set(dates.values())
    decision_date = next(iter(agreed)) if len(agreed) == 1 and not invalid_date else None
    if len(agreed) > 1:
        reasons.append("CONFLICTING_DECISION_DATES")
    if decision_date is None:
        reasons.append("DECISION_DATE_UNRESOLVED")
    disposition = None
    if citation:
        match = re.search(r"(중간판결|판결|결정|명령)\s*[★☆]*\s*$", citation)
        if match:
            disposition = match[1]
    kind = decision_kind(disposition)
    if kind is None:
        reasons.append("DECISION_KIND_UNRESOLVED")
    if docket and not docket_aliases(docket):
        reasons.append("DECISION_DOCKET_UNRESOLVED")
    for name in ("decision_items", "decision_gists", "reasoning"):
        field = fields.get(name)
        if field is not None and _text(field) is None:
            reasons.append(f"LEGACY_FIELD_AVAILABILITY_UNKNOWN:{name}")
    locator = row.locator
    preserved_id = f"legacy-row:{locator.snapshot_sha256}:{locator.position}"
    # The locator is a registration request, not a claim that two rows are different decisions.
    proposal = canonical_id_for_request(preserved_id)
    body = bool(row.stored_texts) or any(
        f.name in {"case_txt_scraped_with_tags", "case_txt_in_file"}
        and f.encoding == "STRING"
        and bool(f.value)
        for f in row.fields
    )
    return LegacyCaseRecord(
        original=row,
        provenance=LegacyImportProvenance(
            locator=locator, imported_at=imported_at, import_rules_version=IMPORT_RULES_VERSION
        ),
        preservation_id=preserved_id,
        document_id_proposal=proposal,
        observed_source_ids=tuple(ids),
        business_key=key,
        metadata=CaseMetadata(
            court=court,
            case_numbers=(docket,) if docket else (),
            decision_date=decision_date,
            disposition=disposition,
        ),
        reasons=tuple(reasons),
        date_source_fields=tuple(dates),
        body_state="PRESERVED" if body else "NOT_INCLUDED",
        enrichment_state=(
            "PRESERVED_UNVERIFIED"
            if any(t.role == "ENRICHED_HTML" for t in row.stored_texts)
            else "UNKNOWN"
        ),
    )


def legacy_content_revision(record: LegacyCaseRecord) -> str:
    """Import execution time is not content; original values and mapper results are."""
    value = record.model_dump(mode="json")
    del value["provenance"]["imported_at"]
    return content_hash(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def identity_conflicts(records: tuple[LegacyCaseRecord, ...]) -> tuple[str, ...]:
    """Flag contradictory reuse of any official alias without deleting or merging rows."""
    seen: dict[SourceCaseIdentifier, list[LegacyCaseRecord]] = {}
    conflicts: set[str] = set()
    for record in records:
        for identifier in record.observed_source_ids:
            for previous in seen.get(identifier, []):
                pairs = (
                    (record.business_key, previous.business_key),
                    (record.metadata.decision_date, previous.metadata.decision_date),
                    (record.metadata.disposition, previous.metadata.disposition),
                )
                if any(a is not None and b is not None and a != b for a, b in pairs):
                    conflicts.update((record.preservation_id, previous.preservation_id))
            seen.setdefault(identifier, []).append(record)
    return tuple(sorted(conflicts))


def row_from_metadata_projection(value: dict[str, object]) -> LegacyRow:
    """Adapt the existing audit projection without reconstructing missing source values."""
    from klegal_gold.domain.legacy import LegacyRowLocator

    snapshot, position, index = (
        value.get(k) for k in ("snapshot_sha256", "position", "legacy_index")
    )
    if not isinstance(snapshot, str) or type(position) is not int or not isinstance(index, str):
        raise ValueError("INVALID_PROJECTION_LOCATOR")
    fields: list[LegacyField] = []
    for name, item in value.items():
        if name in {"snapshot_sha256", "position", "legacy_index"}:
            continue
        original_type = value.get(name + "_type", "projection:" + type(item).__name__)
        if not isinstance(original_type, str):
            raise ValueError("INVALID_PROJECTION_TYPE")
        if item is None:
            encoding: Literal["OPAQUE", "NULL"] = "OPAQUE" if original_type == "parser" else "NULL"
            field = LegacyField(
                name=name, original_type=original_type, encoding=encoding, value=None
            )
        elif isinstance(item, str):
            field = LegacyField(
                name=name, original_type=original_type, encoding="STRING", value=item
            )
        elif type(item) is int:
            field = LegacyField(
                name=name, original_type=original_type, encoding="INTEGER", value=item
            )
        else:
            raise ValueError("UNSUPPORTED_PROJECTION_VALUE")
        fields.append(field)
    return LegacyRow(
        locator=LegacyRowLocator(snapshot_sha256=snapshot, position=position, original_index=index),
        fields=tuple(fields),
        coverage="METADATA_PROJECTION",
    )
