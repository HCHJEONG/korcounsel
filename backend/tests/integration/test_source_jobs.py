"""Actual PostgreSQL, synthetic HTTP responses; no external requests."""

import json
from datetime import UTC, datetime

import pytest

from klegal_gold.db.records import Records
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.sources.law_api import Response, UrllibTransport
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def test_source_job_preserves_raw_and_reuses_versions(db, tmp_path, monkeypatch):
    monkeypatch.setenv("LAW_OPEN_API_OC", "test-source-job-secret")
    monkeypatch.delenv("LAW_GO_KR_OC", raising=False)
    monkeypatch.delenv("KLEGAL_ENV_FILE", raising=False)
    raw = json.dumps(
        {"PrecService": {"판례정보일련번호": "195490", "판례내용": "<p>표본</p>"}}
    ).encode()
    monkeypatch.setattr("klegal_gold.sources.law_api.time.sleep", lambda _: None)

    def get(self, endpoint, params, progress):
        progress()
        return Response(raw, 200, "application/json", "https://www.law.go.kr/", datetime.now(UTC))

    monkeypatch.setattr(UrllibTransport, "get", get)
    records, queue = Records(db, FileStore(tmp_path)), Queue(db)
    for key in ("first", "refresh"):
        job = queue.submit_law_detail(key, "195490")
        assert queue.submit_law_detail(key, "195490").job_id == job.job_id
        assert Worker(queue, records).run_once()
        done = queue.get(job.job_id)
        assert done.status == "SUCCEEDED"
        assert records.read(done.checkpoint["artifact_id"]) == raw
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM source_versions").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) n FROM source_receipts").fetchone()["n"] == 2
        assert "test-source-job-secret" not in str(conn.execute("SELECT * FROM jobs").fetchall())


def test_source_failure_keeps_response_without_creating_case(db, tmp_path, monkeypatch):
    monkeypatch.setenv("LAW_OPEN_API_OC", "test-source-job-secret")
    monkeypatch.delenv("LAW_GO_KR_OC", raising=False)
    monkeypatch.delenv("KLEGAL_ENV_FILE", raising=False)

    def get(self, endpoint, params, progress):
        return Response(
            b"<html>error</html>", 200, "text/html", "https://www.law.go.kr/", datetime.now(UTC)
        )

    monkeypatch.setattr(UrllibTransport, "get", get)
    records, queue = Records(db, FileStore(tmp_path)), Queue(db)
    job = queue.submit_law_detail("bad-schema", "195490")
    Worker(queue, records).run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM source_versions").fetchone()["n"] == 0
        assert (
            conn.execute(
                "SELECT count(*) n FROM artifacts WHERE origin='HTTP_RESPONSE'"
            ).fetchone()["n"]
            == 1
        )


def test_source_admission_obeys_drain(db):
    queue = Queue(db)
    job = queue.submit_law_detail("one", "195490")
    queue.set_draining(True)
    assert queue.submit_law_detail("one", "195490").job_id == job.job_id
    with pytest.raises(ValueError, match="RUNTIME_DRAINING"):
        queue.submit_law_detail("two", "240889")


def test_scourt_worker_keeps_both_metadata_and_body(db, tmp_path, monkeypatch):
    from pathlib import Path

    from klegal_gold.sources.scourt import PortalTransport

    fixture = Path(__file__).parents[1] / "fixtures/sources"

    def post(self, endpoint, source_id, progress):
        index = 0 if endpoint == "selectJdcpctDtl.on" else 1
        progress()
        return Response(
            (fixture / f"scourt-{index}.json").read_bytes(),
            200,
            "application/json",
            "https://portal.scourt.go.kr/pgp/pgp1011/" + endpoint,
            datetime.now(UTC),
        )

    monkeypatch.setattr(PortalTransport, "post", post)
    records, queue = Records(db, FileStore(tmp_path)), Queue(db)
    job = queue.submit_scourt_detail("scourt-observed", "2252318")
    assert job.handler_version == "source-1"
    Worker(queue, records).run_once()
    done = queue.get(job.job_id)
    assert done.status == "SUCCEEDED"
    assert records.read(done.checkpoint["artifact_id"]) == (fixture / "scourt-1.json").read_bytes()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM source_versions").fetchone()
        assert row["source"] == "scourt"
        assert (
            conn.execute(
                "SELECT count(*) n FROM artifacts WHERE metadata->>'kind'='SCOURT_ACQUISITION'"
            ).fetchone()["n"]
            == 1
        )


def test_inventory_worker_persists_last_page_without_conflict(db, tmp_path, monkeypatch):
    from klegal_gold.sources.scourt import PortalTransport

    def post_listing(self, query, page, display, progress):
        progress()
        return Response(
            json.dumps(
                {
                    "status": 200,
                    "data": {
                        "status": "200",
                        "totalCount": "100",
                        "dlt_jdcpctRslt": [{"jisCntntsSrno": str(page)}],
                    },
                }
            ).encode(),
            200,
            "application/json",
            "https://portal.scourt.go.kr/",
            datetime.now(UTC),
        )

    monkeypatch.setattr(PortalTransport, "post_listing", post_listing)
    records, queue = Records(db, FileStore(tmp_path)), Queue(db)
    job = queue.submit_scourt_inventory("inventory", display=1, max_pages=2)
    Worker(queue, records).run_once()
    done = queue.get(job.job_id)
    assert done.status == "SUCCEEDED"
    snapshot = json.loads(records.read(done.checkpoint["snapshot_artifact"]))
    assert snapshot["completeness"] == "PARTIAL"
    assert snapshot["observed_unique_count"] == 2
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM inventories").fetchone()["n"] == 2
