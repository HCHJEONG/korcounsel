"""Deterministic comparison helpers for source inventory snapshots."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from klegal_gold.domain.inventory import InventorySnapshot


class InventoryDeltaKind(StrEnum):
    NEW = "NEW"
    CHANGED = "CHANGED"
    UNCHANGED = "UNCHANGED"
    LEGACY_KNOWN = "LEGACY_KNOWN"
    CURRENT_KNOWN = "CURRENT_KNOWN"
    UNPRESERVED = "UNPRESERVED"
    MISSING = "MISSING"
    ABSENCE_UNCONFIRMED = "ABSENCE_UNCONFIRMED"


@dataclass(frozen=True)
class InventoryDeltaEntry:
    source_id: str
    kind: InventoryDeltaKind
    previous_metadata_hash: str | None = None
    current_metadata_hash: str | None = None

    def payload(self) -> dict[str, str | None]:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "previous_metadata_hash": self.previous_metadata_hash,
            "current_metadata_hash": self.current_metadata_hash,
        }


@dataclass(frozen=True)
class InventoryDelta:
    baseline_snapshot_id: str | None
    current_snapshot_id: str
    source: str
    scope_hash: str
    absence_is_confirmed: bool
    entries: tuple[InventoryDeltaEntry, ...]
    version: str = "inventory-delta-1"

    @classmethod
    def from_payload(cls, value: object) -> InventoryDelta:
        if not isinstance(value, dict) or value.get("version") != "inventory-delta-1":
            raise ValueError("INVALID_INVENTORY_DELTA")
        entries = value.get("entries")
        required = (
            "current_snapshot_id",
            "source",
            "scope_hash",
            "absence_is_confirmed",
        )
        if not isinstance(entries, list) or any(name not in value for name in required):
            raise ValueError("INVALID_INVENTORY_DELTA")
        try:
            parsed = tuple(
                InventoryDeltaEntry(
                    source_id=str(item["source_id"]),
                    kind=InventoryDeltaKind(str(item["kind"])),
                    previous_metadata_hash=item.get("previous_metadata_hash"),
                    current_metadata_hash=item.get("current_metadata_hash"),
                )
                for item in entries
                if isinstance(item, dict)
            )
        except (KeyError, ValueError) as exc:
            raise ValueError("INVALID_INVENTORY_DELTA") from exc
        ordered = tuple(sorted(parsed, key=lambda item: item.source_id))
        if len(parsed) != len(entries) or ordered != parsed:
            raise ValueError("INVALID_INVENTORY_DELTA")
        baseline = value.get("baseline_snapshot_id")
        return cls(
            baseline_snapshot_id=str(baseline) if baseline is not None else None,
            current_snapshot_id=str(value["current_snapshot_id"]),
            source=str(value["source"]),
            scope_hash=str(value["scope_hash"]),
            absence_is_confirmed=bool(value["absence_is_confirmed"]),
            entries=parsed,
        )

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "baseline_snapshot_id": self.baseline_snapshot_id,
            "current_snapshot_id": self.current_snapshot_id,
            "source": self.source,
            "scope_hash": self.scope_hash,
            "absence_is_confirmed": self.absence_is_confirmed,
            "entries": [entry.payload() for entry in self.entries],
        }


def _indexed(snapshot: InventorySnapshot) -> dict[str, str]:
    return {entry.source_id: entry.metadata_hash for entry in snapshot.entries}


def _known_ids(source_ids: Iterable[str]) -> frozenset[str]:
    return frozenset(source_id for source_id in source_ids if source_id)


def compare_inventory(
    current: InventorySnapshot,
    baseline: InventorySnapshot | None,
    *,
    legacy_source_ids: Iterable[str] = (),
    collected_source_ids: Iterable[str] = (),
    preservation_checked: bool = False,
) -> InventoryDelta:
    """Compare equal-scope snapshots without treating incomplete listings as absence."""
    if baseline is not None and current.source != baseline.source:
        raise ValueError("inventory sources must match")
    if baseline is not None and current.scope_hash != baseline.scope_hash:
        raise ValueError("inventory scopes must match")

    current_entries = _indexed(current)
    baseline_entries = _indexed(baseline) if baseline is not None else {}
    known_ids = _known_ids(legacy_source_ids)
    collected_ids = _known_ids(collected_source_ids)
    entries: list[InventoryDeltaEntry] = []

    for source_id, current_hash in current_entries.items():
        previous_hash = baseline_entries.get(source_id)
        if previous_hash is None:
            kind = (
                InventoryDeltaKind.CURRENT_KNOWN
                if source_id in collected_ids
                else InventoryDeltaKind.LEGACY_KNOWN
                if source_id in known_ids
                else InventoryDeltaKind.NEW
            )
        elif previous_hash == current_hash:
            kind = (
                InventoryDeltaKind.UNPRESERVED
                if preservation_checked
                and source_id not in known_ids
                and source_id not in collected_ids
                else InventoryDeltaKind.UNCHANGED
            )
        else:
            kind = InventoryDeltaKind.CHANGED
        entries.append(InventoryDeltaEntry(source_id, kind, previous_hash, current_hash))

    absence_is_confirmed = (
        baseline is not None
        and baseline.completeness == "COMPLETE"
        and current.completeness == "COMPLETE"
    )
    for source_id, previous_hash in baseline_entries.items():
        if source_id not in current_entries:
            entries.append(
                InventoryDeltaEntry(
                    source_id,
                    InventoryDeltaKind.MISSING
                    if absence_is_confirmed
                    else InventoryDeltaKind.ABSENCE_UNCONFIRMED,
                    previous_hash,
                )
            )

    return InventoryDelta(
        baseline_snapshot_id=baseline.snapshot_id if baseline is not None else None,
        current_snapshot_id=current.snapshot_id,
        source=current.source.value,
        scope_hash=current.scope_hash,
        absence_is_confirmed=absence_is_confirmed,
        entries=tuple(sorted(entries, key=lambda entry: entry.source_id)),
    )


def detail_fetch_candidates(
    delta: InventoryDelta,
    *,
    incomplete_source_ids: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return newly observed or changed details plus prior incomplete details."""
    candidates = {
        entry.source_id
        for entry in delta.entries
        if entry.kind
        in {InventoryDeltaKind.NEW, InventoryDeltaKind.CHANGED, InventoryDeltaKind.UNPRESERVED}
    }
    candidates.update(_known_ids(incomplete_source_ids))
    return tuple(sorted(candidates))
