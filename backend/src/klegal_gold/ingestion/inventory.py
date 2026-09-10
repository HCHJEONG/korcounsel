"""Bounded inventory observations with explicit scope and conservative completeness."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from klegal_gold.domain.common import content_hash
from klegal_gold.domain.identity import SourceSystem
from klegal_gold.domain.inventory import InventoryEntry, InventorySnapshot
from klegal_gold.sources.law_api import CaseSource, SourceError

FIELDS = {
    SourceSystem.SCOURT: (
        "jisCntntsSrno",
        "cortNm",
        "csNoLstCtt",
        "prnjdgYmd",
        "adjdTypNm",
        "csNmLstCtt",
    ),
    SourceSystem.LAW_GO_KR: (
        "판례일련번호",
        "법원명",
        "사건번호",
        "선고일자",
        "판결유형",
        "사건명",
    ),
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


@dataclass(frozen=True)
class InventoryCapture:
    snapshot: InventorySnapshot
    pages: tuple[dict[str, Any], ...]


def collect_inventory(
    source: CaseSource,
    *,
    system: SourceSystem,
    scope: dict[str, Any],
    max_pages: int,
    display: int,
    query: str = "",
    on_page: Callable[[InventoryCapture], None] = lambda _: None,
) -> InventoryCapture:
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise SourceError("INVALID_SAMPLE_LIMIT")
    if system not in FIELDS:
        raise SourceError("UNSUPPORTED_INVENTORY_SOURCE")
    started = datetime.now(UTC)
    snapshot_id = str(uuid4())
    entries: dict[str, str] = {}
    pages: list[dict[str, Any]] = []
    failed: list[str] = []
    total: int | None = None

    def capture(exhausted: bool = False) -> InventoryCapture:
        finished = datetime.now(UTC)
        ordered = tuple(
            InventoryEntry(source_id=k, metadata_hash=v) for k, v in sorted(entries.items())
        )
        snapshot = InventorySnapshot(
            snapshot_id=snapshot_id + ":" + str(len(pages)) + ":" + str(len(failed)),
            source=system,
            retrieved_at=finished,
            started_at=started,
            finished_at=finished,
            total_count=total,
            entries=ordered,
            observed_unique_count=len(ordered),
            metadata_hash=content_hash(
                canonical_json([(e.source_id, e.metadata_hash) for e in ordered])
            ),
            scope=canonical_json(scope).decode(),
            scope_hash=content_hash(canonical_json(scope)),
            collector_version="bounded-inventory-1",
            hash_rules_version="selected-source-metadata-1",
            completeness="UNKNOWN" if exhausted and not failed else "PARTIAL",
            failed_pages=tuple(failed),
            completeness_basis=(
                "All reported rows observed; provider offers no frozen snapshot token"
                if exhausted and not failed
                else "Bounded or interrupted observation"
            ),
        )
        return InventoryCapture(snapshot, tuple(pages))

    current = capture()
    for page in range(1, max_pages + 1):
        try:
            result = source.list_page(page=page, display=display, docket=query)
            if total is not None and total != result.total:
                raise SourceError("TOTAL_CHANGED")
            if set(result.ids).intersection(entries):
                raise SourceError("REPEATED_PAGE_IDS")
            total = result.total
            additions = {
                key: content_hash(canonical_json({f: row.get(f) for f in FIELDS[system]}))
                for key, row in zip(result.ids, result.rows, strict=True)
            }
            entries.update(additions)
            pages.append(
                {
                    "page": page,
                    "raw_content_hash": result.response.sha256,
                    "source_ids": result.ids,
                    "reported_total": result.total,
                }
            )
            exhausted = page * display >= total
            current = capture(exhausted)
            on_page(current)
            if exhausted:
                return current
        except SourceError as exc:
            failed.append(f"{page}:{exc}")
            break
    return capture() if failed else current
