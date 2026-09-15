from __future__ import annotations

from datetime import UTC, datetime

import pytest

from klegal_gold.domain.identity import SourceSystem
from klegal_gold.domain.inventory import InventoryEntry, InventorySnapshot
from klegal_gold.ingestion.delta import (
    InventoryDeltaKind,
    compare_inventory,
    detail_fetch_candidates,
)


def snapshot(
    snapshot_id: str,
    entries: dict[str, str],
    completeness: str = "COMPLETE",
) -> InventorySnapshot:
    now = datetime.now(UTC)
    return InventorySnapshot(
        snapshot_id=snapshot_id,
        source=SourceSystem.SCOURT,
        retrieved_at=now,
        started_at=now,
        finished_at=now,
        total_count=len(entries),
        entries=tuple(
            InventoryEntry(source_id=source_id, metadata_hash=metadata_hash)
            for source_id, metadata_hash in sorted(entries.items())
        ),
        observed_unique_count=len(entries),
        metadata_hash="0" * 64,
        scope='{"court":"all"}',
        scope_hash="1" * 64,
        collector_version="test",
        hash_rules_version="test",
        completeness=completeness,
        completeness_basis="test complete" if completeness == "COMPLETE" else "test partial",
    )


def digest(character: str) -> str:
    return character * 64


def test_delta_distinguishes_new_changed_legacy_and_unconfirmed_absence() -> None:
    baseline = snapshot("old", {"same": digest("a"), "changed": digest("b"), "gone": digest("c")})
    current = snapshot(
        "new",
        {"same": digest("a"), "changed": digest("d"), "legacy": digest("e"), "fresh": digest("f")},
        "PARTIAL",
    )

    delta = compare_inventory(current, baseline, legacy_source_ids={"legacy"})

    assert {entry.source_id: entry.kind for entry in delta.entries} == {
        "changed": InventoryDeltaKind.CHANGED,
        "fresh": InventoryDeltaKind.NEW,
        "gone": InventoryDeltaKind.ABSENCE_UNCONFIRMED,
        "legacy": InventoryDeltaKind.LEGACY_KNOWN,
        "same": InventoryDeltaKind.UNCHANGED,
    }
    assert not delta.absence_is_confirmed
    assert detail_fetch_candidates(delta, incomplete_source_ids={"retry"}) == (
        "changed",
        "fresh",
        "retry",
    )


def test_complete_equal_scope_snapshots_can_mark_missing() -> None:
    baseline = snapshot("old", {"gone": digest("c")})
    current = snapshot("new", {})

    delta = compare_inventory(current, baseline)

    assert delta.absence_is_confirmed
    assert delta.entries[0].kind is InventoryDeltaKind.MISSING
    assert detail_fetch_candidates(delta) == ()


def test_delta_rejects_a_different_scope() -> None:
    baseline = snapshot("old", {"case": digest("a")})
    current = snapshot("new", {"case": digest("a")}).model_copy(update={"scope_hash": digest("9")})

    with pytest.raises(ValueError, match="scopes"):
        compare_inventory(current, baseline)


def test_baseline_free_delta_keeps_known_legacy_ids_out_of_new_work() -> None:
    current = snapshot("new", {"legacy": digest("a"), "fresh": digest("b")})

    delta = compare_inventory(current, None, legacy_source_ids={"legacy"})

    assert {entry.source_id: entry.kind for entry in delta.entries} == {
        "fresh": InventoryDeltaKind.NEW,
        "legacy": InventoryDeltaKind.LEGACY_KNOWN,
    }


def test_delta_payload_round_trip_preserves_sorted_candidates() -> None:
    current = snapshot("new", {"fresh": digest("a")})

    delta = compare_inventory(current, None)

    assert type(delta).from_payload(delta.payload()) == delta


def test_collected_ids_are_not_new_without_baseline():
    current = snapshot("new", {"123": digest("a"), "456": digest("b")})
    delta = compare_inventory(current, None, collected_source_ids=["123"])
    assert delta.entries[0].kind == InventoryDeltaKind.CURRENT_KNOWN
    assert detail_fetch_candidates(delta) == ("456",)
    changed = compare_inventory(
        current, snapshot("old", {"123": digest("c")}), collected_source_ids=["123"]
    )
    assert changed.entries[0].kind == InventoryDeltaKind.CHANGED
