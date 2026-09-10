"""Inputs and versioned transformations required to reproduce a record."""

from pydantic import Field

from .common import DomainModel, SourceURL, Text, UTCDateTime
from .identity import SourceCaseVersion


class Provenance(DomainModel):
    source_version: SourceCaseVersion
    raw_artifact_id: Text
    source_url: SourceURL
    retrieved_at: UTCDateTime
    decoder_version: Text
    text_extractor_version: Text
    parser_version: Text
    normalizer_version: Text
    dataset_version: Text
    run_id: Text
    transformation_rules: tuple[Text, ...] = Field(default_factory=tuple)
    exclusion_reasons: tuple[Text, ...] = Field(default_factory=tuple)
