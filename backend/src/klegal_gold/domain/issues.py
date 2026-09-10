"""Issue content revisions and separate alignment, automatic quality and human review."""

import json
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import Field, model_validator

from .artifacts import EvidenceSpan, SourceText, VisualEvidenceReference
from .cases import LegalAuthority
from .common import Digest, DomainModel, Revision, Text, UTCDateTime, content_hash
from .identity import IdentityStatus, SourceCaseVersion
from .provenance import Provenance


class ReviewDecision(DomainModel):
    issue_revision: Digest
    identity_link_revision: Revision
    source_versions: tuple[SourceCaseVersion, ...] = Field(min_length=1)
    status: Literal["approved", "rejected", "deferred"]
    reviewer: Text
    recorded_at: UTCDateTime
    reason: Text


class GoldAssessment(DomainModel):
    issue_revision: Digest
    identity_link_revision: Revision
    policy_version: Text
    status: Literal["NOT_EVALUATED", "INELIGIBLE", "ELIGIBLE"] = "NOT_EVALUATED"
    passed_checks: tuple[Text, ...] = Field(default_factory=tuple)
    blockers: tuple[Text, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def completeness(self) -> Self:
        required = {
            "schema",
            "alignment",
            "evidence",
            "provenance",
            "duplicate",
            "identity",
            "fidelity",
        }
        if self.status == "ELIGIBLE" and (
            self.blockers or not required.issubset(self.passed_checks)
        ):
            raise ValueError("INCOMPLETE_GOLD_ASSESSMENT")
        if self.status == "INELIGIBLE" and not self.blockers:
            raise ValueError("MISSING_GOLD_BLOCKER")
        return self


class LegalIssueUnit(DomainModel):
    canonical_id: Text
    identity_link_revision: Revision
    source_versions: tuple[SourceCaseVersion, ...] = Field(min_length=1)
    issue_original: Text | None = None
    answer_original: Text | None = None
    issue_normalized: Text | None = None
    answer_normalized: Text | None = None
    evidence: tuple[EvidenceSpan, ...] = Field(default_factory=tuple)
    visual_evidence: tuple[VisualEvidenceReference, ...] = Field(default_factory=tuple)
    authorities: tuple[LegalAuthority, ...] = Field(default_factory=tuple)
    alignment_status: Literal["aligned", "ambiguous", "unmatched"]
    quality_status: Literal["passed", "needs_review", "failed"] = "needs_review"
    identity_status: IdentityStatus
    reason_codes: tuple[Text, ...] = Field(default_factory=tuple)
    rules_version: Text
    provenance: tuple[Provenance, ...] = Field(min_length=1)
    review: ReviewDecision | None = None
    gold: GoldAssessment | None = None

    issue_revision: Digest | None = None

    def calculate_revision(self) -> str:
        """Content address, independent of canonical relinking, runs, review and release time."""
        source_versions = sorted(
            (v.model_dump(mode="json") for v in self.source_versions),
            key=lambda v: json.dumps(v, sort_keys=True),
        )
        versions = sorted(
            {
                (
                    p.decoder_version,
                    p.text_extractor_version,
                    p.parser_version,
                    p.normalizer_version,
                )
                for p in self.provenance
            }
        )
        payload = {
            "schema_version": self.schema_version,
            "sources": source_versions,
            "issue_original": self.issue_original,
            "answer_original": self.answer_original,
            "issue_normalized": self.issue_normalized,
            "answer_normalized": self.answer_normalized,
            "evidence": [e.model_dump(mode="json") for e in self.evidence],
            "visual_evidence": [e.model_dump(mode="json") for e in self.visual_evidence],
            "authorities": [a.model_dump(mode="json") for a in self.authorities],
            "rules_version": self.rules_version,
            "transform_versions": versions,
        }
        return content_hash(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )

    @model_validator(mode="after")
    def issue_contract(self) -> Self:
        calculated = self.calculate_revision()
        if self.issue_revision is not None and self.issue_revision != calculated:
            raise ValueError("ISSUE_REVISION_MISMATCH")
        object.__setattr__(self, "issue_revision", calculated)
        if len(set(self.source_versions)) != len(self.source_versions):
            raise ValueError("DUPLICATE_SOURCE_VERSION")
        if {p.source_version for p in self.provenance} != set(self.source_versions):
            raise ValueError("MISSING_SOURCE_PROVENANCE")
        if self.alignment_status == "aligned" and (
            not self.issue_original or not self.answer_original
        ):
            raise ValueError("MISSING_ALIGNED_TEXT")
        if self.issue_normalized is not None and self.issue_original is None:
            raise ValueError("NORMALIZED_WITHOUT_ORIGINAL")
        if self.answer_normalized is not None and self.answer_original is None:
            raise ValueError("NORMALIZED_WITHOUT_ORIGINAL")
        if self.alignment_status != "aligned" and not self.reason_codes:
            raise ValueError("MISSING_ALIGNMENT_REASON")
        if self.review is not None:
            if (
                self.review.issue_revision != self.issue_revision
                or self.review.identity_link_revision != self.identity_link_revision
                or set(self.review.source_versions) != set(self.source_versions)
            ):
                raise ValueError("STALE_REVIEW")
        if self.gold is not None:
            if (
                self.gold.issue_revision != self.issue_revision
                or self.gold.identity_link_revision != self.identity_link_revision
            ):
                raise ValueError("STALE_GOLD_ASSESSMENT")
            if self.gold.status == "ELIGIBLE":
                if (
                    self.alignment_status != "aligned"
                    or self.quality_status != "passed"
                    or not self.evidence
                ):
                    raise ValueError("INELIGIBLE_ISSUE")
                if len({v.identifier.source for v in self.source_versions}) > 1:
                    if self.identity_status not in {
                        IdentityStatus.EXACT,
                        IdentityStatus.HIGH_CONFIDENCE,
                    }:
                        raise ValueError("UNCERTAIN_CROSS_SOURCE_GOLD")
        return self


def validate_issue_evidence(
    issue: LegalIssueUnit,
    source_fields: Mapping[tuple[str, str], SourceText],
) -> tuple[str, ...]:
    """Check supplied artifact fields exactly. This is not a full gold/fidelity assessment."""
    errors: list[str] = []
    if not issue.evidence:
        errors.append("MISSING_TEXT_EVIDENCE")
    for evidence in issue.evidence:
        text = source_fields.get((evidence.artifact_id, evidence.field))
        if text is None:
            errors.append("EVIDENCE_SOURCE_NOT_LOADED")
            continue
        if (text.artifact_id, text.field) != (evidence.artifact_id, evidence.field):
            errors.append("EVIDENCE_FIELD_MISMATCH")
            continue
        if text.source_version not in issue.source_versions or not any(
            p.source_version == text.source_version
            and p.text_extractor_version == text.text_extractor_version
            for p in issue.provenance
        ):
            errors.append("EVIDENCE_SOURCE_VERSION_MISMATCH")
            continue
        try:
            evidence.verify(text.text)
        except ValueError as exc:
            errors.append(str(exc))
    return tuple(errors)
