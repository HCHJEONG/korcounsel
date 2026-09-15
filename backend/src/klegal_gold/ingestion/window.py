"""Order a frozen window delta by its preserved provider dates, never live responses."""

import json

from klegal_gold.db.records import Records
from klegal_gold.domain.inventory import InventorySnapshot
from klegal_gold.ingestion.delta import InventoryDelta


def window_candidates(
    records: Records, delta: InventoryDelta, candidates: tuple[str, ...]
) -> tuple[tuple[str, ...], bool]:
    snapshot = InventorySnapshot.model_validate_json(
        records.read("inventory:" + delta.current_snapshot_id)
    )
    scope = json.loads(snapshot.scope).get("dma_searchParam", {})
    if not scope.get("prnjdgYmdFrom"):
        return candidates, False
    if snapshot.failed_pages or snapshot.observed_unique_count != snapshot.total_count:
        raise ValueError("WINDOW_INVENTORY_INCOMPLETE")
    pages = json.loads(records.read("manifest:inventory-pages:" + delta.current_snapshot_id))[
        "pages"
    ]
    dates = {}
    for page in pages:
        raw = json.loads(records.read("http:" + page["raw_content_hash"]))
        for row in raw["data"]["dlt_jdcpctRslt"]:
            dates[str(row["jisCntntsSrno"])] = str(row["prnjdgYmd"])
    if any(sid not in dates for sid in candidates):
        raise ValueError("WINDOW_CANDIDATE_NOT_OBSERVED")
    return tuple(sorted(candidates, key=lambda sid: (dates[sid], sid))), True
