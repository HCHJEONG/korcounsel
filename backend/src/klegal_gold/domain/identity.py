"""Source namespaces, independent canonical registry records and resolver outcomes."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, StrictFloat, model_validator

from .common import DecisionDate, Digest, DomainModel, Revision, Text, UTCDateTime


class SourceSystem(StrEnum):
    SCOURT = "scourt"
    LAW_GO_KR = "law_go_kr"
    LAWNB = "lawnb"
    LEGACY_IMPORT = "legacy_import"


class SourceCaseIdentifier(DomainModel):
    source: SourceSystem
    source_id: Text


class SourceCaseVersion(DomainModel):
    identifier: SourceCaseIdentifier
    raw_content_hash: Digest


class CaseMetadata(DomainModel):
    court: Text | None = None
    decision_date: DecisionDate | None = None
    case_numbers: tuple[Text, ...] = Field(default_factory=tuple)
    disposition: Text | None = None
    title: Text | None = None


class SourceCaseMetadata(DomainModel):
    identifier: SourceCaseIdentifier
    metadata_hash: Digest
    raw_court: Text | None = None
    raw_date: Text | None = None
    raw_case_numbers: Text | None = None
    raw_disposition: Text | None = None
    raw_title: Text | None = None
    normalized: CaseMetadata
    normalizer_version: Text


class FieldOrigin(DomainModel):
    field: Text
    source_version: SourceCaseVersion
    artifact_id: Text
    source_field: Text


class CourtCaseKey(DomainModel):
    """User-confirmed business key. Preserve branch and every merged docket alias."""

    court: Text
    case_number: Text


class CanonicalCaseIdentity(DomainModel):
    # Opaque: existing government-derived IDs must remain usable; allocation is pending audit.
    canonical_id: Text
    link_revision: Revision
    court_case_keys: tuple[CourtCaseKey, ...] = Field(default_factory=tuple)
    metadata: CaseMetadata
    source_identifiers: tuple[SourceCaseIdentifier, ...] = Field(min_length=1)
    field_origins: tuple[FieldOrigin, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        if len(set(self.court_case_keys)) != len(self.court_case_keys):
            raise ValueError("DUPLICATE_COURT_CASE_KEY")
        if len(set(self.source_identifiers)) != len(self.source_identifiers):
            raise ValueError("DUPLICATE_SOURCE_KEY")
        for origin in self.field_origins:
            if origin.source_version.identifier not in self.source_identifiers:
                raise ValueError("UNKNOWN_FIELD_SOURCE")
        return self


class IdentityStatus(StrEnum):
    EXACT = "EXACT"
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"
    CONFLICT = "CONFLICT"


class IdentitySignal(DomainModel):
    field: Text
    outcome: str = Field(pattern="^(MATCH|MISMATCH|MISSING)$")
    reason: Text


class IdentityCandidate(DomainModel):
    metadata: SourceCaseMetadata
    score: StrictFloat = Field(ge=0, le=1)
    signals: tuple[IdentitySignal, ...] = Field(min_length=1)
    reasons: tuple[Text, ...] = Field(min_length=1)


class IdentityResolution(DomainModel):
    left: SourceCaseMetadata
    candidates: tuple[IdentityCandidate, ...] = Field(default_factory=tuple)
    status: IdentityStatus
    selected: SourceCaseIdentifier | None = None
    reasons: tuple[Text, ...] = Field(min_length=1)
    resolver_version: Text
    run_id: Text

    @model_validator(mode="after")
    def selection(self) -> Self:
        ids = tuple(item.metadata.identifier for item in self.candidates)
        if len(set(ids)) != len(ids) or self.left.identifier in ids:
            raise ValueError("DUPLICATE_IDENTITY_CANDIDATE")
        confirmed = self.status in {IdentityStatus.EXACT, IdentityStatus.HIGH_CONFIDENCE}
        if confirmed != (self.selected is not None) or (confirmed and self.selected not in ids):
            raise ValueError("INVALID_IDENTITY_SELECTION")
        if confirmed:
            candidate = next(
                item for item in self.candidates if item.metadata.identifier == self.selected
            )
            if any(signal.outcome == "MISMATCH" for signal in candidate.signals):
                raise ValueError("CONFLICTING_IDENTITY_SELECTION")
            left, right = self.left.normalized, candidate.metadata.normalized
            for field in ("court", "decision_date", "disposition"):
                a, b = getattr(left, field), getattr(right, field)
                if a is not None and b is not None and a != b:
                    raise ValueError("CONFLICTING_IDENTITY_METADATA")
            if self.status == IdentityStatus.EXACT:

                def exact_metadata(other: CaseMetadata) -> bool:
                    return bool(
                        left.court
                        and left.decision_date
                        and left.case_numbers
                        and left.disposition
                        and left.court == other.court
                        and left.decision_date == other.decision_date
                        and set(left.case_numbers) == set(other.case_numbers)
                        and left.disposition == other.disposition
                    )

                if not exact_metadata(right):
                    raise ValueError("INSUFFICIENT_EXACT_METADATA")
                if sum(exact_metadata(item.metadata.normalized) for item in self.candidates) != 1:
                    raise ValueError("NON_UNIQUE_EXACT_CANDIDATE")
        return self


class IdentityLinkEvent(DomainModel):
    event_id: UUID
    operation: str = Field(pattern="^(CREATE|MERGE|SPLIT|RELINK)$")
    previous: tuple[CanonicalCaseIdentity, ...] = Field(default_factory=tuple)
    resulting: tuple[CanonicalCaseIdentity, ...] = Field(min_length=1)
    recorded_at: UTCDateTime
    actor: Text
    reason: Text

    @model_validator(mode="after")
    def history(self) -> Self:
        if (self.operation == "CREATE") != (len(self.previous) == 0):
            raise ValueError("INVALID_IDENTITY_HISTORY")
        for records in (self.previous, self.resulting):
            if len({item.canonical_id for item in records}) != len(records):
                raise ValueError("DUPLICATE_CANONICAL_ID")
        prior = {item.canonical_id: item.link_revision for item in self.previous}
        if any(item.link_revision <= prior.get(item.canonical_id, 0) for item in self.resulting):
            raise ValueError("NON_INCREASING_LINK_REVISION")
        if self.operation == "MERGE" and (len(self.previous) < 2 or len(self.resulting) != 1):
            raise ValueError("INVALID_MERGE")
        if self.operation == "SPLIT" and (len(self.previous) != 1 or len(self.resulting) < 2):
            raise ValueError("INVALID_SPLIT")
        return self
