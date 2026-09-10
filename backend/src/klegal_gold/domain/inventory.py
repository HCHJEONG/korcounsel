"""Inventory observations; no body freshness or disappearance inference here."""

from typing import Self

from pydantic import Field, model_validator

from .common import Count, Digest, DomainModel, Text, UTCDateTime
from .identity import SourceSystem


class InventoryEntry(DomainModel):
    source_id: Text
    metadata_hash: Digest


class InventorySnapshot(DomainModel):
    snapshot_id: Text
    source: SourceSystem
    retrieved_at: UTCDateTime
    started_at: UTCDateTime
    finished_at: UTCDateTime
    total_count: Count | None
    entries: tuple[InventoryEntry, ...] = Field(default_factory=tuple)
    observed_unique_count: Count
    metadata_hash: Digest
    scope: Text
    scope_hash: Digest
    collector_version: Text
    hash_rules_version: Text
    completeness: str = Field(pattern="^(COMPLETE|PARTIAL|UNKNOWN)$")
    failed_pages: tuple[Text, ...] = Field(default_factory=tuple)
    completeness_basis: Text | None = None

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.entries)

    @model_validator(mode="after")
    def observed_scope(self) -> Self:
        if self.source_ids != tuple(sorted(set(self.source_ids))):
            raise ValueError("UNSORTED_OR_DUPLICATE_INVENTORY_IDS")
        if self.observed_unique_count != len(self.entries):
            raise ValueError("INVENTORY_COUNT_MISMATCH")
        if self.started_at > self.finished_at or self.retrieved_at < self.finished_at:
            raise ValueError("INVALID_INVENTORY_TIMES")
        if self.completeness == "COMPLETE":
            if self.failed_pages or self.completeness_basis is None:
                raise ValueError("UNPROVEN_COMPLETE_INVENTORY")
            if self.total_count is not None and self.total_count != len(self.entries):
                raise ValueError("INCOMPLETE_INVENTORY_COUNT")
        return self
