"""The corpus command honors its bound and resumes existing worker jobs."""

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.db.records import Records
from klegal_gold.jobs.queue import Queue
from klegal_gold.storage.files import FileStore


def load_tools():
    path = Path(__file__).resolve().parents[3] / "scripts" / "run_legacy_reader_batches.py"
    spec = importlib.util.spec_from_file_location("reader_batch_tools", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bounded_command_resumes_without_extra_queued_job(db, tmp_path, monkeypatch):
    tools = load_tools()
    path = tmp_path / "corpus.parquet"
    table = pa.Table.from_pylist(
        [
            {
                "__legacy_position": i,
                "__legacy_index": str(i),
                "case_txt_scraped_with_tags": "<p>원문</p>",
                "case_full_no": "사건",
                "gmeta_contId": "123",
                "lmeta_serialno": "456",
            }
            for i in range(3)
        ]
    ).replace_schema_metadata({b"legacy": json.dumps({"snapshot_sha256": "a" * 64}).encode()})
    pq.write_table(table, path)
    records = Records(db, FileStore(tmp_path / "data"))
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(path))
    plan = tools.make_plan(path, records, batch_size=1)
    first = tools.run_plan(records, plan, max_batches=1)
    assert first["executed"] == 1
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) n FROM legacy_reader_batch_rows").fetchone()["n"] == 1
    resumed = tools.run_plan(records, plan, max_batches=3)
    assert resumed["executed"] == 2
    assert all(row["status"] == "SUCCEEDED" for row in resumed["results"])
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 3
        assert conn.execute("SELECT count(*) n FROM legacy_reader_batch_rows").fetchone()["n"] == 3
    assert tools.make_plan(path, records, batch_size=1) == plan
    with pytest.raises(ValueError, match="INVALID_SELECTED_POSITIONS"):
        tools.make_plan(path, records, positions=[0, 0])


def small_plan(tools, records, tmp_path, monkeypatch):
    path = tmp_path / "restart.parquet"
    table = pa.Table.from_pylist(
        [
            {
                "__legacy_position": i,
                "__legacy_index": str(i),
                "case_txt_scraped_with_tags": "<p>원문</p>",
                "case_full_no": "사건",
                "gmeta_contId": "123",
                "lmeta_serialno": "456",
            }
            for i in range(2)
        ]
    ).replace_schema_metadata({b"legacy": json.dumps({"snapshot_sha256": "b" * 64}).encode()})
    pq.write_table(table, path)
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(path))
    pointer = tools.make_plan(path, records, batch_size=1)
    manifest = json.loads(records.read(pointer["plan_artifact_id"]))["batches"][0][
        "manifest_artifact_id"
    ]
    job = Queue(records.db).submit_legacy_reader_batch(
        "reader-stage:" + manifest.split(":", 1)[1], manifest
    )
    return pointer, job


def test_batch_command_recovers_its_expired_lease(db, tmp_path, monkeypatch):
    tools = load_tools()
    records = Records(db, FileStore(tmp_path / "data"))
    plan, submitted = small_plan(tools, records, tmp_path, monkeypatch)
    queue = Queue(db)
    claimed = queue.claim("interrupted-worker")
    assert claimed.job_id == submitted.job_id
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (claimed.job_id,),
        )
    report = tools.run_plan(records, plan, max_batches=1)
    assert report["executed"] == 1
    assert report["results"][0]["status"] == "SUCCEEDED"
    assert queue.get(claimed.job_id).attempts == 2
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) n FROM legacy_reader_batch_rows").fetchone()["n"] == 1


def test_batch_command_stops_at_terminal_failure(db, tmp_path, monkeypatch):
    tools = load_tools()
    records = Records(db, FileStore(tmp_path / "data"))
    plan, submitted = small_plan(tools, records, tmp_path, monkeypatch)
    queue = Queue(db)
    for _ in range(3):
        claimed = queue.claim("failing-worker")
        queue.finish(claimed, outcome="FAILED", error_code="HANDLER_FAILED")
        with db.connect() as conn:
            conn.execute(
                "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s",
                (submitted.job_id,),
            )
    assert queue.get(submitted.job_id).status == "FAILED"
    report = tools.run_plan(records, plan, max_batches=10)
    assert report["executed"] == 0
    assert [row["status"] for row in report["results"]] == ["FAILED"]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) n FROM legacy_reader_batch_rows").fetchone()["n"] == 0


def test_batch_command_does_not_claim_foreign_queued_work(db, tmp_path, monkeypatch):
    tools = load_tools()
    records = Records(db, FileStore(tmp_path / "data"))
    plan, own = small_plan(tools, records, tmp_path, monkeypatch)
    foreign = Queue(db).submit_rebuild("foreign")
    with pytest.raises(ValueError, match="ANOTHER_WORKER_JOB_ACTIVE"):
        tools.run_plan(records, plan, max_batches=1)
    assert Queue(db).get(own.job_id).status == "QUEUED"
    assert Queue(db).get(foreign.job_id).status == "QUEUED"


def load_source_tools(monkeypatch):
    directory = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(directory))
    path = directory / "prepare_legacy_image_sources.py"
    spec = importlib.util.spec_from_file_location("source_batch_tools", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preserve_receipt(records, job_id, *, not_found=True, indexed=True):
    response_id = "test-response:" + uuid4().hex
    records.put_artifact(
        response_id,
        json.dumps({"data": {"result": "notExtist" if not_found else "unexpected"}}).encode(),
        origin="HTTP_RESPONSE",
        metadata={"kind": "SYNTHETIC_HTTP_RESPONSE"},
    )
    receipt_id = "test-receipt:" + uuid4().hex
    records.put_artifact(
        receipt_id,
        json.dumps({"run_id": str(job_id)}).encode(),
        origin="DERIVED",
        metadata={"kind": "HTTP_ATTEMPT", **({"run_id": str(job_id)} if indexed else {})},
        parent_id=response_id,
    )
    return receipt_id, response_id


def instant_source_failures(tools, monkeypatch, *, not_found=True):
    original_finish = Queue.finish

    def finish_without_backoff(self, job, **kwargs):
        original_finish(self, job, **kwargs)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (job.job_id,)
            )

    def failed_fetch(self, job):
        preserve_receipt(self.records, job.job_id, not_found=not_found)
        raise ValueError("SYNTHETIC_SOURCE_FAILURE")

    monkeypatch.setattr(Queue, "finish", finish_without_backoff)
    monkeypatch.setattr(tools.Worker, "_fetch_scourt", failed_fetch)


def test_source_command_resumes_queued_job_and_skips_prior_failure_budget(
    db, tmp_path, monkeypatch
):
    tools = load_source_tools(monkeypatch)
    instant_source_failures(tools, monkeypatch)
    records = Records(db, FileStore(tmp_path / "data"))
    targets = [
        {"position": i, "source_id": str(100 + i), "source_id_usable": True} for i in range(3)
    ]
    queued = Queue(db).submit_scourt_detail("legacy-image-source:inventory:100", "100")
    first = tools.prepare(records, targets, inventory_hash="inventory", max_sources=1)
    assert first["attempted"] == 1
    assert first["sources_considered"] == 1
    assert first["results"][0]["status"] == "SOURCE_NOT_FOUND"
    assert Queue(db).get(queued.job_id).attempts == 3
    second = tools.prepare(records, targets, inventory_hash="inventory", max_sources=1)
    assert second["attempted"] == 1
    assert second["sources_considered"] == 2
    assert all(row["status"] == "SOURCE_NOT_FOUND" for row in second["results"])
    assert not second["paused_for_structure"]
    assert Queue(db).get(queued.job_id).attempts == 3
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 2


def test_old_source_failure_receipt_is_found_and_cached(db, tmp_path, monkeypatch):
    tools = load_source_tools(monkeypatch)
    records = Records(db, FileStore(tmp_path / "data"))
    job_id = uuid4()
    preserve_receipt(records, job_id)
    for _ in range(14):
        preserve_receipt(records, uuid4(), not_found=False)
    assert tools.fetch_failure_kind(records, job_id, "100") == "SOURCE_NOT_FOUND"
    tools.preserve_source_result(
        records, {"job_id": str(job_id), "source_id": "100", "status": "SOURCE_NOT_FOUND"}
    )
    original_read = records.read

    def read_without_receipts(artifact_id):
        assert not artifact_id.startswith("test-receipt:")
        return original_read(artifact_id)

    monkeypatch.setattr(records, "read", read_without_receipts)
    assert tools.fetch_failure_kind(records, job_id, "100") == "SOURCE_NOT_FOUND"


def test_source_command_stops_after_three_structure_failures(db, tmp_path, monkeypatch):
    tools = load_source_tools(monkeypatch)
    instant_source_failures(tools, monkeypatch, not_found=False)
    records = Records(db, FileStore(tmp_path / "data"))
    targets = [
        {"position": i, "source_id": str(100 + i), "source_id_usable": True} for i in range(5)
    ]
    report = tools.prepare(records, targets, inventory_hash="inventory", max_sources=5)
    assert report["attempted"] == 3
    assert report["sources_considered"] == 3
    assert report["paused_for_structure"]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 3


def test_new_http_receipt_has_queryable_job_key(db, tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from klegal_gold.domain.identity import SourceSystem
    from klegal_gold.sources.law_api import Response
    from klegal_gold.sources.persistence import preserve_response

    tools = load_source_tools(monkeypatch)
    records = Records(db, FileStore(tmp_path / "data"))
    job_id = uuid4()
    response = Response(
        b'{"data":{"result":"notExtist"}}',
        200,
        "application/json",
        "https://portal.scourt.go.kr/pgp/pgp1011/selectJdcpctDtl.on",
        datetime.now(UTC),
    )
    preserve_response(records, response, str(job_id), SourceSystem.SCOURT)
    with db.connect() as conn:
        receipt = conn.execute(
            "SELECT metadata FROM artifacts WHERE metadata->>'kind'='HTTP_ATTEMPT'"
        ).fetchone()
    assert receipt["metadata"]["run_id"] == str(job_id)
    # Indexed receipts do not require a job_attempt interval to be discoverable.
    assert tools.fetch_failure_kind(records, job_id, "100") == "SOURCE_NOT_FOUND"


def test_legacy_job_intervals_exclude_unrelated_missing_historical_receipts(
    db, tmp_path, monkeypatch
):
    tools = load_source_tools(monkeypatch)
    records = Records(db, FileStore(tmp_path / "data"))
    unrelated, _ = preserve_receipt(records, uuid4(), indexed=False)
    records.store.path(records.blob(unrelated).storage_key).unlink()
    queue = Queue(db)
    submitted = queue.submit_scourt_detail("current-source", "100")
    job = queue.claim("receipt-fixture")
    assert job.job_id == submitted.job_id
    current, _ = preserve_receipt(records, job.job_id, indexed=False)
    # A new indexed receipt for another job is excluded even within this interval.
    overlapping, _ = preserve_receipt(records, uuid4(), indexed=True)
    records.store.path(records.blob(overlapping).storage_key).unlink()
    queue.finish(job, outcome="FAILED", error_code="HANDLER_FAILED")
    original_read = records.read
    read_ids = []

    def tracked(artifact_id):
        read_ids.append(artifact_id)
        return original_read(artifact_id)

    monkeypatch.setattr(records, "read", tracked)
    assert tools.fetch_failure_kind(records, job.job_id, "100") == "SOURCE_NOT_FOUND"
    assert current in read_ids
    assert unrelated not in read_ids and overlapping not in read_ids


@pytest.mark.parametrize("damage", ["missing_receipt", "missing_response", "corrupt_response"])
@pytest.mark.parametrize("indexed", [True, False])
def test_related_receipt_damage_is_not_hidden_by_another_not_found_response(
    db, tmp_path, monkeypatch, damage, indexed
):
    tools = load_source_tools(monkeypatch)
    records = Records(db, FileStore(tmp_path / "data"))
    queue = Queue(db)
    queue.submit_scourt_detail("damaged-source", "100")
    job = queue.claim("receipt-fixture")
    receipt, response = preserve_receipt(records, job.job_id, not_found=False, indexed=indexed)
    # This newer valid NOT_FOUND must not short-circuit the older damaged evidence.
    preserve_receipt(records, job.job_id, not_found=True, indexed=indexed)
    queue.finish(job, outcome="FAILED", error_code="HANDLER_FAILED")
    damaged_id = receipt if damage == "missing_receipt" else response
    path = records.store.path(records.blob(damaged_id).storage_key)
    if damage == "corrupt_response":
        path.write_bytes(b"corrupt")
        expected = ValueError
    else:
        path.unlink()
        expected = FileNotFoundError
    with pytest.raises(expected):
        tools.fetch_failure_kind(records, job.job_id, "100")


@pytest.mark.parametrize("latest_has_response", [True, False])
def test_latest_source_attempt_does_not_inherit_old_not_found(
    db, tmp_path, monkeypatch, latest_has_response
):
    tools = load_source_tools(monkeypatch)
    records = Records(db, FileStore(tmp_path / "data"))
    queue = Queue(db)
    queue.submit_scourt_detail("changed-source", "100")
    first = queue.claim("receipt-fixture")
    preserve_receipt(records, first.job_id, not_found=True, indexed=False)
    queue.finish(first, outcome="FAILED", error_code="HANDLER_FAILED")
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (first.job_id,)
        )
    latest = queue.claim("receipt-fixture")
    assert latest.attempts == 2
    if latest_has_response:
        preserve_receipt(records, latest.job_id, not_found=False, indexed=False)
        response_id = "test-empty-body:" + uuid4().hex
        records.put_artifact(
            response_id,
            json.dumps(
                {"data": {"dma_jdcpctCtxt": {"jisCntntsSrno": "100", "orgdocXmlCtt": ""}}}
            ).encode(),
            origin="HTTP_RESPONSE",
            metadata={"kind": "SYNTHETIC_HTTP_RESPONSE"},
        )
        records.put_artifact(
            "test-receipt:" + uuid4().hex,
            json.dumps({"run_id": str(latest.job_id)}).encode(),
            origin="DERIVED",
            metadata={"kind": "HTTP_ATTEMPT", "run_id": str(latest.job_id)},
            parent_id=response_id,
        )
    queue.finish(latest, outcome="FAILED", error_code="HANDLER_FAILED")
    assert tools.fetch_failure_kind(records, latest.job_id, "100") == "SOURCE_FETCH_FAILED"
