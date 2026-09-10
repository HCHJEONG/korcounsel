"""Acquired artifacts and unacquired visual references are different contracts."""

from enum import StrEnum
from pathlib import PurePosixPath
from typing import Self

from pydantic import Field, StrictBool, StrictStr, model_validator

from .common import Count, Digest, DomainModel, SourceURL, Text, UTCDateTime
from .identity import SourceCaseVersion


class ArtifactType(StrEnum):
    JSON = "JSON"
    XML = "XML"
    HTML = "HTML"
    PDF_TEXT = "PDF_TEXT"
    PDF_SCAN = "PDF_SCAN"
    PAGE_IMAGE = "PAGE_IMAGE"
    EMBEDDED_IMAGE = "EMBEDDED_IMAGE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class SourceArtifact(DomainModel):
    artifact_id: Text
    source_version: SourceCaseVersion
    artifact_type: ArtifactType
    representation: str = Field(
        pattern="^(RESPONSE_BYTES|ASSET_BYTES|DOM_SNAPSHOT|EXTRACTED_TEXT|DERIVED)$"
    )
    parent_artifact_id: Text | None = None
    source_url: SourceURL
    retrieved_at: UTCDateTime
    mime_type: Text
    sha256: Digest
    file_size: Count
    storage_path: Text
    document_order: Count | None = None
    classification_basis: Text | None = None

    @model_validator(mode="after")
    def representation_contract(self) -> Self:
        key = PurePosixPath(self.storage_path)
        if (
            key.is_absolute()
            or ".." in key.parts
            or "\\" in self.storage_path
            or ":" in self.storage_path
        ):
            raise ValueError("INVALID_STORAGE_KEY")
        if self.parent_artifact_id == self.artifact_id:
            raise ValueError("SELF_PARENT_ARTIFACT")
        if self.representation == "RESPONSE_BYTES":
            if self.sha256 != self.source_version.raw_content_hash:
                raise ValueError("RAW_HASH_MISMATCH")
        elif self.parent_artifact_id is None:
            raise ValueError("MISSING_PARENT_ARTIFACT")
        if self.artifact_type in {ArtifactType.PDF_TEXT, ArtifactType.PDF_SCAN}:
            if self.classification_basis is None:
                raise ValueError("MISSING_PDF_CLASSIFICATION_BASIS")
        return self


class VisualAssetReference(DomainModel):
    reference_id: Text
    kind: str = Field(pattern="^(IMAGE|PDF|TABLE|OTHER|UNKNOWN)$")
    parent_artifact_id: Text
    original_src: Text
    source_page: SourceURL
    locator: Text
    document_order: Count
    resolved_url: SourceURL | None = None
    alt: StrictStr | None = None
    before_text: StrictStr | None = None
    after_text: StrictStr | None = None
    acquisition_state: str = Field(
        default="NOT_REQUESTED", pattern="^(NOT_REQUESTED|PENDING|ACQUIRED|FAILED)$"
    )
    acquired_artifact_id: Text | None = None
    failure_reason: Text | None = None

    @model_validator(mode="after")
    def acquisition(self) -> Self:
        if (self.acquisition_state == "ACQUIRED") != (self.acquired_artifact_id is not None):
            raise ValueError("INVALID_ASSET_ACQUISITION")
        if (self.acquisition_state == "FAILED") != (self.failure_reason is not None):
            raise ValueError("INVALID_ASSET_FAILURE")
        return self


class TextSpan(DomainModel):
    artifact_id: Text
    field: Text
    text: Text
    start: Count
    end: Count

    @model_validator(mode="after")
    def offsets(self) -> Self:
        if self.end <= self.start or self.end - self.start != len(self.text):
            raise ValueError("INVALID_TEXT_SPAN")
        return self

    def verify(self, source_text: str) -> None:
        """Validate against the exact artifact field, not a normalized/reconstructed guess."""
        if self.end > len(source_text):
            raise ValueError("EVIDENCE_OUT_OF_RANGE")
        if source_text[self.start : self.end] != self.text:
            raise ValueError("EVIDENCE_TEXT_MISMATCH")


class EvidenceSpan(TextSpan):
    kind: str = Field(pattern="^(ISSUE|SUMMARY|REASONING|FULL_TEXT|AUTHORITY)$")


class VisualEvidenceReference(DomainModel):
    reference_id: Text
    artifact_id: Text | None = None
    block_id: Text | None = None
    page: Count | None = None


class DocumentBlock(DomainModel):
    block_id: Text
    parent_artifact_id: Text
    document_order: Count
    kind: str = Field(pattern="^(heading|paragraph|image|table|page_image|unknown)$")
    parent_block_id: Text | None = None
    label_original: Text | None = None
    numbering_path: tuple[Text, ...] = Field(default_factory=tuple)
    text_span: TextSpan | None = None
    asset_reference_id: Text | None = None
    locator: Text | None = None

    @model_validator(mode="after")
    def location(self) -> Self:
        if self.parent_block_id == self.block_id:
            raise ValueError("SELF_PARENT_BLOCK")
        if self.text_span is not None and self.text_span.artifact_id != self.parent_artifact_id:
            raise ValueError("BLOCK_ARTIFACT_MISMATCH")
        if self.kind in {"image", "page_image"} and self.asset_reference_id is None:
            raise ValueError("MISSING_ASSET_REFERENCE")
        return self


class FidelityAssessment(DomainModel):
    tier: str = Field(default="UNKNOWN", pattern="^(STRUCTURED|FULL_TEXT|SCAN|UNKNOWN)$")
    has_visual_assets: StrictBool | None = None
    visual_asset_count: Count | None = None
    requires_ocr: StrictBool | None = None
    detection_status: str = Field(default="UNKNOWN", pattern="^(COMPLETE|PARTIAL|UNKNOWN|FAILED)$")
    detection_scope: Text | None = None
    reasons: tuple[Text, ...] = Field(default_factory=tuple)
    asset_status: str = Field(
        default="NOT_REQUESTED", pattern="^(NOT_REQUESTED|COMPLETE|PARTIAL_FAILURE|FAILED)$"
    )
    ocr_status: str = Field(
        default="NOT_YET_PROCESSED", pattern="^(NOT_YET_PROCESSED|NOT_REQUIRED|PROCESSED|FAILED)$"
    )

    @model_validator(mode="after")
    def observation(self) -> Self:
        if (
            self.has_visual_assets is not None
            or self.visual_asset_count is not None
            or self.detection_status != "UNKNOWN"
        ) and self.detection_scope is None:
            raise ValueError("MISSING_DETECTION_SCOPE")
        if self.visual_asset_count is not None:
            if self.has_visual_assets != (self.visual_asset_count > 0):
                raise ValueError("CONFLICTING_VISUAL_COUNT")
        if self.has_visual_assets is False and self.detection_status != "COMPLETE":
            raise ValueError("INCOMPLETE_NEGATIVE_DETECTION")
        if self.tier == "SCAN" and self.requires_ocr is not True:
            raise ValueError("SCAN_REQUIRES_OCR")
        if self.requires_ocr is True and self.ocr_status == "NOT_REQUIRED":
            raise ValueError("CONFLICTING_OCR_STATUS")
        return self


class SourceText(DomainModel):
    """Exact decoded/extracted artifact field, loaded by a trusted storage adapter."""

    artifact_id: Text
    field: Text
    source_version: SourceCaseVersion
    text_extractor_version: Text
    text: StrictStr
