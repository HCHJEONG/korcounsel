"""Immutable staging contracts for archived rows, not historical HTTP responses."""

import json
from typing import Literal, Self

from pydantic import Field, StrictInt, StrictStr, model_validator

from .common import Count, Digest, DomainModel, Text, UTCDateTime, content_hash
from .identity import CaseMetadata, CourtCaseKey, SourceCaseIdentifier


class LegacyRowLocator(DomainModel):
    snapshot_sha256: Digest
    position: Count
    original_index: Text


class LegacyField(DomainModel):
    """Opaque values remain in the snapshot; JSON is an explicit serialized value."""

    name: Text
    original_type: Text
    encoding: Literal["STRING", "INTEGER", "NULL", "JSON", "OPAQUE"]
    value: StrictStr | StrictInt | None = None

    @model_validator(mode="after")
    def value_contract(self) -> Self:
        valid = {
            "STRING": isinstance(self.value, str),
            "INTEGER": type(self.value) is int,
            "NULL": self.value is None,
            "JSON": isinstance(self.value, str),
            "OPAQUE": self.value is None,
        }
        if not valid[self.encoding]:
            raise ValueError("LEGACY_FIELD_ENCODING_MISMATCH")
        if self.encoding == "JSON":
            assert isinstance(self.value, str)
            json.loads(self.value, parse_constant=_invalid_constant)
        return self


def _invalid_constant(value: str) -> None:
    raise ValueError("NON_FINITE_LEGACY_JSON")


class LegacyStoredText(DomainModel):
    """Exact decoded UTF-8 file text, or a stored string field; never RESPONSE_BYTES."""

    role: Literal["SAVED_HTML", "ENRICHED_HTML", "EXTRACTED_TEXT"]
    original_locator: Text
    text: StrictStr
    utf8_sha256: Digest
    # Present only when actual file bytes were read and UTF-8 decoded without replacement.
    file_sha256: Digest | None = None
    historical_retrieved_at: None = None
    historical_http_hash: None = None

    @model_validator(mode="after")
    def text_integrity(self) -> Self:
        actual = content_hash(self.text.encode("utf-8"))
        if self.utf8_sha256 != actual:
            raise ValueError("LEGACY_TEXT_HASH_MISMATCH")
        if self.file_sha256 is not None and self.file_sha256 != actual:
            raise ValueError("LEGACY_UTF8_FILE_HASH_MISMATCH")
        return self


class LegacyRow(DomainModel):
    locator: LegacyRowLocator
    fields: tuple[LegacyField, ...] = Field(min_length=1)
    # METADATA_PROJECTION must not be counted as full corpus preservation/import.
    coverage: Literal["METADATA_PROJECTION", "FULL_ROW"]
    stored_texts: tuple[LegacyStoredText, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def unique_fields(self) -> Self:
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError("DUPLICATE_LEGACY_FIELD")
        return self


class LegacyImportProvenance(DomainModel):
    origin: Literal["LEGACY_ARCHIVE"] = "LEGACY_ARCHIVE"
    locator: LegacyRowLocator
    imported_at: UTCDateTime
    import_rules_version: Text
    historical_retrieved_at: None = None
    historical_raw_content_hash: None = None
    historical_source_url: None = None
    missing_reasons: tuple[Text, ...] = (
        "HISTORICAL_ACQUISITION_NOT_RECORDED",
        "HTTP_RESPONSE_BYTES_NOT_AVAILABLE",
        "HISTORICAL_SOURCE_URL_NOT_VERIFIED",
    )


class LegacyCaseRecord(DomainModel):
    """Preserved row with a document identity proposal, pending registry validation."""

    original: LegacyRow
    provenance: LegacyImportProvenance
    preservation_id: Text
    document_id_proposal: Text
    identity_state: Literal["LEGACY_OBSERVED"] = "LEGACY_OBSERVED"
    observed_source_ids: tuple[SourceCaseIdentifier, ...] = Field(default_factory=tuple)
    # Complete legacy docket spelling remains here; splitting aliases is a later explicit rule.
    business_key: CourtCaseKey | None = None
    metadata: CaseMetadata
    reasons: tuple[Text, ...] = Field(min_length=1)
    date_source_fields: tuple[Text, ...] = Field(default_factory=tuple)
    body_state: Literal["PRESERVED", "NOT_INCLUDED"]
    enrichment_state: Literal["PRESERVED_UNVERIFIED", "UNKNOWN"]
    asset_acquisition_state: Literal["UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def preservation_contract(self) -> Self:
        locator = self.original.locator
        expected_id = f"legacy-row:{locator.snapshot_sha256}:{locator.position}"
        if self.preservation_id != expected_id:
            raise ValueError("LEGACY_PRESERVATION_ID_MISMATCH")
        if self.original.locator != self.provenance.locator:
            raise ValueError("LEGACY_LOCATOR_MISMATCH")
        if len(set(self.observed_source_ids)) != len(self.observed_source_ids):
            raise ValueError("DUPLICATE_SOURCE_KEY")
        body = bool(self.original.stored_texts) or any(
            field.name in {"case_txt_scraped_with_tags", "case_txt_in_file"}
            and field.encoding == "STRING"
            and bool(field.value)
            for field in self.original.fields
        )
        if body != (self.body_state == "PRESERVED"):
            raise ValueError("LEGACY_BODY_STATE_MISMATCH")
        enriched = any(t.role == "ENRICHED_HTML" for t in self.original.stored_texts)
        if enriched != (self.enrichment_state == "PRESERVED_UNVERIFIED"):
            raise ValueError("LEGACY_ENRICHMENT_STATE_MISMATCH")
        return self
