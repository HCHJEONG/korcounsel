"""Preservable source cases, including records without editorial text."""

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from .artifacts import (
    DocumentBlock,
    FidelityAssessment,
    SourceArtifact,
    TextSpan,
    VisualAssetReference,
)
from .common import DomainModel, Text
from .identity import CanonicalCaseIdentity, CaseMetadata, FieldOrigin, SourceCaseVersion
from .provenance import Provenance


class FieldAvailability(StrEnum):
    PRESENT = "PRESENT"
    ABSENT_IN_SOURCE = "ABSENT_IN_SOURCE"
    NOT_FETCHED = "NOT_FETCHED"
    PARSE_FAILED = "PARSE_FAILED"
    UNKNOWN = "UNKNOWN"


class EditorialAvailability(DomainModel):
    issues: FieldAvailability = FieldAvailability.UNKNOWN
    summaries: FieldAvailability = FieldAvailability.UNKNOWN
    reasoning: FieldAvailability = FieldAvailability.UNKNOWN
    full_text: FieldAvailability = FieldAvailability.UNKNOWN


class CaseReference(DomainModel):
    citation_original: Text
    metadata: CaseMetadata = Field(default_factory=CaseMetadata)
    location: TextSpan | None = None


class LegalAuthority(DomainModel):
    kind: str = Field(pattern="^(STATUTE|CASE|OTHER)$")
    citation_original: Text
    scope: str = Field(pattern="^(CASE|ISSUE)$")
    source_span: TextSpan
    case_reference: CaseReference | None = None
    statute_name: Text | None = None
    article: Text | None = None


class StructuredText(DomainModel):
    text: Text
    label_original: Text | None = None
    numbering_path: tuple[Text, ...] = Field(default_factory=tuple)
    source_span: TextSpan | None = None

    @model_validator(mode="after")
    def original_text(self) -> Self:
        if self.source_span is not None and self.text != self.source_span.text:
            raise ValueError("STRUCTURED_TEXT_MISMATCH")
        return self


class RawLegalCase(DomainModel):
    source_version: SourceCaseVersion
    raw_artifact: SourceArtifact
    provenance: Provenance

    @model_validator(mode="after")
    def raw_contract(self) -> Self:
        if (
            self.raw_artifact.representation != "RESPONSE_BYTES"
            or self.raw_artifact.source_version != self.source_version
            or self.provenance.source_version != self.source_version
            or self.provenance.raw_artifact_id != self.raw_artifact.artifact_id
        ):
            raise ValueError("RAW_PROVENANCE_MISMATCH")
        return self


class LegalCase(DomainModel):
    identity: CanonicalCaseIdentity
    source_versions: tuple[SourceCaseVersion, ...] = Field(min_length=1)
    metadata: CaseMetadata
    issues: tuple[StructuredText, ...] = Field(default_factory=tuple)
    summaries: tuple[StructuredText, ...] = Field(default_factory=tuple)
    reasoning: Text | None = None
    full_text: Text | None = None
    field_availability: EditorialAvailability = Field(default_factory=EditorialAvailability)
    field_origins: tuple[FieldOrigin, ...] = Field(default_factory=tuple)
    authorities: tuple[LegalAuthority, ...] = Field(default_factory=tuple)
    artifacts: tuple[SourceArtifact, ...] = Field(min_length=1)
    visual_assets: tuple[VisualAssetReference, ...] = Field(default_factory=tuple)
    blocks: tuple[DocumentBlock, ...] = Field(default_factory=tuple)
    fidelity: FidelityAssessment = Field(default_factory=FidelityAssessment)
    provenance: tuple[Provenance, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_contract(self) -> Self:
        if len(set(self.source_versions)) != len(self.source_versions):
            raise ValueError("DUPLICATE_SOURCE_VERSION")
        if any(v.identifier not in self.identity.source_identifiers for v in self.source_versions):
            raise ValueError("UNLINKED_SOURCE_VERSION")
        artifacts = {item.artifact_id: item for item in self.artifacts}
        assets = {item.reference_id: item for item in self.visual_assets}
        blocks = {item.block_id: item for item in self.blocks}
        if len(artifacts) != len(self.artifacts) or len(assets) != len(self.visual_assets):
            raise ValueError("DUPLICATE_ARTIFACT_OR_REFERENCE")
        if len(blocks) != len(self.blocks):
            raise ValueError("DUPLICATE_BLOCK")
        for artifact in self.artifacts:
            if artifact.source_version not in self.source_versions:
                raise ValueError("UNKNOWN_ARTIFACT_SOURCE")
            if (
                artifact.parent_artifact_id is not None
                and artifact.parent_artifact_id not in artifacts
            ):
                raise ValueError("UNKNOWN_PARENT_ARTIFACT")
        for parents in (
            {key: item.parent_artifact_id for key, item in artifacts.items()},
            {key: item.parent_block_id for key, item in blocks.items()},
        ):
            for start in parents:
                seen: set[str] = set()
                cursor: str | None = start
                while cursor is not None:
                    if cursor in seen:
                        raise ValueError("CYCLIC_DOCUMENT_REFERENCE")
                    seen.add(cursor)
                    cursor = parents.get(cursor)
        for provenance in self.provenance:
            raw = artifacts.get(provenance.raw_artifact_id)
            if (
                raw is None
                or raw.representation != "RESPONSE_BYTES"
                or raw.source_version != provenance.source_version
            ):
                raise ValueError("RAW_PROVENANCE_MISMATCH")
        if {p.source_version for p in self.provenance} != set(self.source_versions):
            raise ValueError("MISSING_SOURCE_PROVENANCE")
        for field in ("issues", "summaries", "reasoning", "full_text"):
            present = bool(getattr(self, field))
            if present != (getattr(self.field_availability, field) == FieldAvailability.PRESENT):
                raise ValueError("FIELD_AVAILABILITY_MISMATCH")
        for origin in self.field_origins:
            origin_artifact = artifacts.get(origin.artifact_id)
            if origin_artifact is None or origin_artifact.source_version != origin.source_version:
                raise ValueError("UNKNOWN_FIELD_SOURCE")
        if len(self.source_versions) > 1:
            needed = {"metadata"} | {
                field
                for field in ("issues", "summaries", "reasoning", "full_text")
                if bool(getattr(self, field))
            }
            if not needed.issubset({origin.field for origin in self.field_origins}):
                raise ValueError("MISSING_CROSS_SOURCE_ORIGIN")
        for asset in self.visual_assets:
            if asset.parent_artifact_id not in artifacts:
                raise ValueError("UNKNOWN_PARENT_ARTIFACT")
            if (
                asset.acquired_artifact_id is not None
                and asset.acquired_artifact_id not in artifacts
            ):
                raise ValueError("UNKNOWN_ACQUIRED_ARTIFACT")
        for block in self.blocks:
            if block.parent_artifact_id not in artifacts:
                raise ValueError("UNKNOWN_PARENT_ARTIFACT")
            if block.parent_block_id is not None and block.parent_block_id not in blocks:
                raise ValueError("UNKNOWN_PARENT_BLOCK")
            if block.asset_reference_id is not None:
                block_asset = assets.get(block.asset_reference_id)
                if (
                    block_asset is None
                    or block_asset.parent_artifact_id != block.parent_artifact_id
                ):
                    raise ValueError("UNKNOWN_BLOCK_ASSET")
        spans = [
            item.source_span
            for item in (*self.issues, *self.summaries)
            if item.source_span is not None
        ]
        spans.extend(authority.source_span for authority in self.authorities)
        if any(span.artifact_id not in artifacts for span in spans):
            raise ValueError("UNKNOWN_TEXT_ARTIFACT")
        return self
