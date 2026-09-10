"""Reproducible JSON Schema bundle for domain interchange, not the HTTP API."""

from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from .artifacts import (
    DocumentBlock,
    EvidenceSpan,
    FidelityAssessment,
    SourceArtifact,
    SourceText,
    VisualAssetReference,
    VisualEvidenceReference,
)
from .cases import CaseReference, LegalAuthority, LegalCase, RawLegalCase
from .identity import (
    CanonicalCaseIdentity,
    CourtCaseKey,
    IdentityLinkEvent,
    IdentityResolution,
    SourceCaseIdentifier,
    SourceCaseMetadata,
    SourceCaseVersion,
)
from .inventory import InventorySnapshot
from .issues import GoldAssessment, LegalIssueUnit, ReviewDecision
from .provenance import Provenance


def domain_json_schema() -> dict[str, Any]:
    models: list[type[BaseModel]] = [
        LegalCase,
        RawLegalCase,
        LegalIssueUnit,
        CaseReference,
        LegalAuthority,
        EvidenceSpan,
        Provenance,
        SourceCaseIdentifier,
        SourceCaseMetadata,
        SourceCaseVersion,
        CanonicalCaseIdentity,
        CourtCaseKey,
        IdentityResolution,
        IdentityLinkEvent,
        InventorySnapshot,
        SourceArtifact,
        VisualAssetReference,
        VisualEvidenceReference,
        DocumentBlock,
        FidelityAssessment,
        SourceText,
        ReviewDecision,
        GoldAssessment,
    ]
    refs, schema = models_json_schema(
        [(model, "validation") for model in models], title="KorCounsel domain contracts 0.1.0"
    )
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["anyOf"] = list(refs.values())
    return schema
