import json
from uuid import uuid4

import pytest

from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.fields.store import FieldStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def make_reader(records):
    metadata = {
        "data": {
            "dma_jdcpctDtl": {
                "jisCntntsSrno": 123,
                "prnjdgYmd": "20260625",
                "csNoLstCtt": "2026두30340",
                "cortNm": "대법원",
            }
        }
    }
    records.put_artifact(
        "http:" + "a" * 64, json.dumps(metadata).encode(), origin="HTTP_RESPONSE", metadata={}
    )
    return ReaderStore(records).preserve(
        "<p>【주문】기각</p><p>【이유】이유</p>",
        title="대법원 2026두30340 판결",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={"metadata_response_hash": "a" * 64, "source_artifact_id": "http:" + "a" * 64},
        acquisitions={},
    )


def test_fields_worker_reuses_immutable_publication(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    document = make_reader(records)
    queue = Queue(db)
    job = queue.submit_case_fields(document)
    assert queue.submit_case_fields(document).job_id == job.job_id
    worker = Worker(queue, records)
    assert worker.run_once()
    done = queue.get(job.job_id)
    assert done.status == "SUCCEEDED"
    original = FieldStore(records).read(document)
    assert len(original["fields"]) == 60
    assert original["state"] == "INCOMPLETE"  # lawgo has not run
    assert FieldStore(records).build(document, "different timestamp") == original
    replay = queue.submit_case_fields(document, request_key=str(uuid4()))
    assert worker.run_once() and queue.get(replay.job_id).status == "SUCCEEDED"
    assert FieldStore(records).read(document) == original


def test_fields_wait_for_failed_lawgo_descendant(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    document = make_reader(records)
    q = Queue(db)
    detail = q.submit_scourt_detail("detail", "123")
    d = q.claim("w")
    q.finish(d, outcome="SUCCEEDED")
    lawgo = q.submit_current_lawgo(document, detail.job_id)
    fields = q.submit_case_fields(document, lawgo.job_id)
    dependency = q.claim("w")
    assert dependency.job_id == lawgo.job_id
    # A descendant registered by lawgo must finish even when fields was queued first.
    child = q.submit_case_fields(document, request_key="child")
    q.heartbeat(dependency, {"follow_up_job_id": str(child.job_id)})
    q.finish(dependency, outcome="SUCCEEDED")
    claimed = q.claim("w")
    assert claimed.job_id == child.job_id
    q.finish(claimed, outcome="SUCCEEDED")
    assert q.claim("w").job_id == fields.job_id


def test_field_endpoints_require_auth_and_preserve_values(db, tmp_path):
    from importlib import import_module

    from fastapi.testclient import TestClient

    from klegal_gold.db.accounts import Accounts
    from klegal_gold.web.auth import accounts, require_user
    from klegal_gold.web.reader import reader_store

    records = Records(db, FileStore(tmp_path))
    document = make_reader(records)
    expected = FieldStore(records).build(document, "2026-09-15T00:00:00Z")
    app = import_module("klegal_gold.web.app").create_app()
    app.dependency_overrides[reader_store] = lambda: ReaderStore(records)
    app.dependency_overrides[accounts] = lambda: Accounts(db)
    client = TestClient(app)
    assert client.get(f"/api/reader/{document}/fields").status_code == 401
    assert client.get("/api/cases/0/fields?body_hash=" + "a" * 64).status_code == 401
    app.dependency_overrides[require_user] = lambda: {"role": "admin"}
    response = client.get(f"/api/reader/{document}/fields")
    assert response.status_code == 200 and response.json() == expected
    app.dependency_overrides.clear()


def test_fields_resume_after_publication_before_checkpoint(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    document = make_reader(records)
    queue = Queue(db)
    job = queue.submit_case_fields(document)
    original = FieldStore.build
    published = []

    def crash_once(self, document_id, processed_at):
        result = original(self, document_id, processed_at)
        if not published:
            published.append(result)
            raise ValueError("TEST_AFTER_PUBLICATION")
        return result

    monkeypatch.setattr(FieldStore, "build", crash_once)
    worker = Worker(queue, records)
    assert worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (job.job_id,)
        )
    assert worker.run_once()
    assert queue.get(job.job_id).status == "SUCCEEDED"
    assert FieldStore(records).read(document) == published[0]
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM artifacts WHERE metadata->>'kind'='CASE_FIELDS'"
            ).fetchone()["n"]
            == 1
        )
