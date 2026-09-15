"""Historical successful raw-only jobs must resume without fresh source requests."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from klegal_gold.db.records import Records
from klegal_gold.domain.identity import SourceSystem
from klegal_gold.jobs.ingestion_status import ingestion_status
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.sources.law_api import Response
from klegal_gold.sources.persistence import preserve_response, save_detail
from klegal_gold.sources.scourt import ScourtPortalSource
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def test_replay_raw_only_job_and_report_descendants(db, tmp_path, monkeypatch):
    fixture = Path(__file__).parents[1] / "fixtures/sources"
    records, queue = Records(db, FileStore(tmp_path)), Queue(db)
    original = queue.submit_scourt_detail("historical", "2252318")
    claimed = queue.claim("historical-worker")
    assert claimed is not None

    class Transport:
        def post(self, endpoint, source_id, progress):
            index = 0 if endpoint == "selectJdcpctDtl.on" else 1
            return Response(
                (fixture / f"scourt-{index}.json").read_bytes(),
                200,
                "application/json",
                "https://portal.scourt.go.kr/pgp/pgp1011/" + endpoint,
                datetime.now(UTC),
            )

    source = ScourtPortalSource(
        transport=Transport(),
        preserve=lambda response: preserve_response(
            records, response, str(original.job_id), SourceSystem.SCOURT
        ),
    )
    detail = source.fetch_detail("2252318")
    artifact = save_detail(records, detail, str(original.job_id), SourceSystem.SCOURT)
    records.save_manifest(
        "scourt-document:" + artifact, "DOCUMENT_OBSERVATION", {"historical": True}
    )
    queue.heartbeat(claimed, {"artifact_id": artifact})
    queue.finish(claimed, outcome="SUCCEEDED")
    assert ingestion_status(queue, original.job_id)["state"] == "NEEDS_ATTENTION"

    def forbidden(*args, **kwargs):
        raise AssertionError("Replay must not fetch scourt")

    monkeypatch.setattr("klegal_gold.sources.scourt.PortalTransport.post", forbidden)
    replay = queue.submit_scourt_replay(original.job_id)
    assert queue.submit_scourt_replay(original.job_id).job_id == replay.job_id
    worker = Worker(queue, records)
    assert worker.run_once()
    done = queue.get(replay.job_id)
    assert done.status == "SUCCEEDED"
    assert done.checkpoint["reader_document_id"]
    assert records.read(artifact) == detail.response.body
    assert queue.get(original.job_id).checkpoint == {"artifact_id": artifact}
    status = ingestion_status(queue, replay.job_id)
    assert status["state"] == "PROCESSING"
    assert any(stage["kind"] == "ENRICH_CURRENT_LAWGO" for stage in status["stages"])
    # No credential: lawgo completes with an explicit unavailable state, not a lost reader.
    for _ in range(10):
        if not worker.run_once():
            break
    status = ingestion_status(queue, replay.job_id)
    assert status["state"] == "NEEDS_ATTENTION"
    assert status["fields_state"] == "REVIEW"
    assert any(stage["kind"] == "BUILD_CASE_FIELDS" for stage in status["stages"])
    assert status["reader_document_id"]


def test_ingestion_history_requires_admin_and_survives_reload(db, tmp_path, monkeypatch):
    from importlib import import_module

    from fastapi.testclient import TestClient

    from klegal_gold.config import Settings
    from klegal_gold.db.accounts import Accounts
    from klegal_gold.web.auth import accounts, require_admin

    web = import_module("klegal_gold.web.app")
    monkeypatch.setattr(web, "load_settings", lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr(web.Database, "from_settings", lambda _: db)
    q = Queue(db)
    job = q.submit_scourt_detail("pending", "123")
    app = web.create_app()
    app.dependency_overrides[accounts] = lambda: Accounts(db)
    client = TestClient(app)
    assert client.get("/api/admin/ingestions").status_code == 401
    app.dependency_overrides[require_admin] = lambda: object()
    first = client.get("/api/admin/ingestions")
    assert first.status_code == 200
    assert first.json()["items"][0]["state"] == "PROCESSING"
    assert TestClient(app).get("/api/admin/ingestions").json() == first.json()
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET max_attempts=1 WHERE job_id=%s", (job.job_id,))
    claimed = q.claim("fixture")
    assert claimed is not None
    q.finish(claimed, outcome="FAILED", error_code="HANDLER_FAILED")
    # Exhaustion is an explicit attention state.
    assert client.get("/api/admin/ingestions").json()["items"][0]["state"] == "NEEDS_ATTENTION"
