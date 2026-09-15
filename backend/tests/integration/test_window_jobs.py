import json
from datetime import UTC, datetime

import pytest

from klegal_gold.db.records import Records
from klegal_gold.domain.inventory import InventorySnapshot
from klegal_gold.ingestion.delta import compare_inventory, detail_fetch_candidates
from klegal_gold.ingestion.window import window_candidates
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.sources.law_api import Response
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def test_window_queue_scope_order_and_partial_guard(db, tmp_path, monkeypatch):
    q = Queue(db)
    r = Records(db, FileStore(tmp_path))
    requests = []

    def post(self, params, progress):
        requests.append(params)
        p = int(params["dma_searchParam"]["pageNo"])
        return Response(
            json.dumps(
                {
                    "status": 200,
                    "data": {
                        "status": 200,
                        "totalCount": 2,
                        "dlt_jdcpctRslt": [
                            {
                                "jisCntntsSrno": str(p),
                                "prnjdgYmd": "20240920" if p == 1 else "20240901",
                            }
                        ],
                    },
                }
            ).encode(),
            200,
            "application/json",
            "https://portal.scourt.go.kr/",
            datetime.now(UTC),
        )

    monkeypatch.setattr("klegal_gold.sources.scourt.PortalTransport.post_window_listing", post)
    job = q.submit_scourt_inventory(
        "window", max_pages=2, display=1, date_from="2024-09-01", date_to="2024-09-30"
    )
    assert (
        q.submit_scourt_inventory(
            "window", max_pages=2, display=1, date_from="2024-09-01", date_to="2024-09-30"
        ).job_id
        == job.job_id
    )
    assert Worker(q, r).run_once()
    done = q.get(job.job_id)
    assert done.status == "SUCCEEDED"
    snapshot = InventorySnapshot.model_validate_json(r.read(done.checkpoint["snapshot_artifact"]))
    delta = compare_inventory(snapshot, None)
    assert window_candidates(r, delta, detail_fetch_candidates(delta)) == (("2", "1"), True)
    partial = q.submit_scourt_inventory(
        "partial", max_pages=1, display=1, date_from="2024-09-01", date_to="2024-09-30"
    )
    assert Worker(q, r).run_once()
    sp = InventorySnapshot.model_validate_json(
        r.read(q.get(partial.job_id).checkpoint["snapshot_artifact"])
    )
    with pytest.raises(ValueError, match="WINDOW_INVENTORY_INCOMPLETE"):
        window_candidates(r, compare_inventory(sp, None), ("1",))
    assert requests[1]["dma_searchParam"]["prnjdgYmdTo"] == "20240930"

    # One observation's earlier page is not a previous inventory baseline.
    from importlib import import_module
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from klegal_gold.config import Settings
    from klegal_gold.ingestion.legacy_catalog import LegacySourceCatalog
    from klegal_gold.web.auth import require_admin

    web = import_module("klegal_gold.web.app")
    settings = Settings(data_dir=tmp_path, database_url="postgresql://unused")
    monkeypatch.setattr(web, "load_settings", lambda: settings)
    monkeypatch.setattr(web.Database, "from_settings", lambda _: db)
    r.put_artifact(
        "legacy-source-catalog:test",
        LegacySourceCatalog("scourt", "a" * 64, (), 0, 0).encoded(),
        origin="DERIVED",
        metadata={},
    )
    app = web.create_app()
    app.dependency_overrides[require_admin] = lambda: object()
    client = TestClient(app)
    headers = {"Origin": settings.web_origin}
    delta_response = client.post(f"/api/admin/jobs/{job.job_id}/delta", headers=headers)
    assert delta_response.status_code == 200
    assert delta_response.json()["counts"] == {"NEW": 2}
    url = "/api/admin/deltas/" + delta_response.json()["artifact_id"] + "/scourt-details"
    first = client.post(url, params={"max_details": 1}, headers=headers).json()
    assert first["source_ids"] == ["2"]
    assert first["next_offset"] == 1
    assert not first["exhausted"]
    repeated = client.post(
        url, params={"max_details": 1, "request_id": str(uuid4())}, headers=headers
    ).json()
    assert repeated["job_ids"] == first["job_ids"]

    # Recalculating candidates during ingestion must reuse the same observation's jobs.
    from dataclasses import replace

    from klegal_gold.ingestion.delta import InventoryDeltaKind

    recalculated = replace(
        delta,
        entries=tuple(replace(e, kind=InventoryDeltaKind.UNPRESERVED) for e in delta.entries),
    )
    recalc_id = r.save_inventory_delta(recalculated)
    again = client.post(
        "/api/admin/deltas/" + recalc_id + "/scourt-details",
        params={"max_details": 1},
        headers=headers,
    ).json()
    assert again["job_ids"] == first["job_ids"]
    second = client.post(url, params={"max_details": 1, "offset": 1}, headers=headers).json()
    assert second["source_ids"] == ["1"]
    assert second["exhausted"]
    partial_delta = client.post(f"/api/admin/jobs/{partial.job_id}/delta", headers=headers).json()
    blocked = client.post(
        "/api/admin/deltas/" + partial_delta["artifact_id"] + "/scourt-details", headers=headers
    )
    assert blocked.status_code == 400
    assert "WINDOW_INVENTORY_INCOMPLETE" in blocked.text

    for body in [
        {"date_from": "2024-09-01"},
        {"date_from": "2024-09-30", "date_to": "2024-09-01"},
        {"date_from": "2024-09-01", "date_to": "2025-09-01"},
        {"date_from": "2024-02-30", "date_to": "2024-03-01"},
    ]:
        assert (
            client.post("/api/admin/scourt-inventory", json=body, headers=headers).status_code
            == 422
        )
