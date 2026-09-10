"""Actual PG worker full-row preservation, quarantine, interruption and corrupt input."""

import json

import pytest

from klegal_gold.db.records import Records
from klegal_gold.domain.legacy import LegacyCaseRecord, LegacyRow
from klegal_gold.ingestion.legacy_bundle import BundleEntry, LegacyBundle, preserve_field
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
COLUMNS = ("court_name", "case_no", "case_full_no", "gmeta_contId", "case_txt_scraped_with_tags")
TEXT = "<table><tr><td>원본 😀</td></tr></table>\n"


def staged(records, count=3, invalid=None, scope="FULL"):
    entries = []
    for position in range(count):
        values = (
            "대법원",
            f"2020다{position + 1}",
            f"대법원 2020. 1. 1. 선고 2020다{position + 1} 판결",
            str(position),
            TEXT,
        )
        row = LegacyRow(
            locator={
                "snapshot_sha256": "a" * 64,
                "position": position,
                "original_index": "same-index",
            },
            fields=tuple(
                preserve_field(name, value) for name, value in zip(COLUMNS, values, strict=True)
            ),
            coverage="FULL_ROW",
        )
        raw = row.model_dump_json().encode()
        if position == invalid:
            raw = b'{"broken":true}'
        blob = records.store.put(raw)
        entries.append(
            BundleEntry(position=position, sha256=blob.sha256, size_bytes=blob.size_bytes)
        )
    bundle = LegacyBundle(
        snapshot_sha256="a" * 64,
        snapshot_size=100,
        archive_locator="synthetic.pickle",
        total_rows=count if scope == "FULL" else count + 1,
        columns=COLUMNS,
        scope=scope,
        entries=tuple(entries),
    )
    return records.store.put(bundle.model_dump_json().encode()).sha256, bundle


def services(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    queue = Queue(db)
    return records, queue, Worker(queue, records)


def result(records, queue, job):
    current = queue.get(job.job_id)
    assert current.status == "SUCCEEDED"
    return json.loads(records.read(current.checkpoint["result_manifest"]))


def test_full_row_worker_preserves_body_and_does_not_register_identity(db, tmp_path):
    records, queue, worker = services(db, tmp_path)
    digest, _ = staged(records)
    job = queue.submit_legacy_import("import1", digest)
    assert queue.submit_legacy_import("import1", digest).job_id == job.job_id
    assert worker.run_once()
    report = result(records, queue, job)
    assert (report["preserved"], report["quarantined"], report["pending"]) == (3, 0, 0)
    assert report["corpus_import_complete"]
    for entry in report["rows"]:
        row = LegacyCaseRecord.model_validate_json(records.read(entry["record_artifact"]))
        assert row.original.coverage == "FULL_ROW"
        assert row.original.fields[-1].value == TEXT
        assert row.provenance.historical_raw_content_hash is None
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0


def test_new_run_reuses_records_and_keeps_per_run_ledger(db, tmp_path):
    records, queue, worker = services(db, tmp_path)
    digest, _ = staged(records)
    jobs = []
    for request in ("first", "second"):
        job = queue.submit_legacy_import(request, digest)
        worker.run_once()
        jobs.append(result(records, queue, job))
    assert [r["record_artifact"] for r in jobs[0]["rows"]] == [
        r["record_artifact"] for r in jobs[1]["rows"]
    ]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_records").fetchone()["n"] == 3
        assert conn.execute("SELECT count(*) AS n FROM legacy_bundle_rows").fetchone()["n"] == 6


def test_invalid_row_preserved_in_quarantine_and_counts_reconcile(db, tmp_path):
    records, queue, worker = services(db, tmp_path)
    digest, _ = staged(records, invalid=1)
    job = queue.submit_legacy_import("quarantine", digest)
    worker.run_once()
    report = result(records, queue, job)
    assert (report["selected_rows"], report["preserved"], report["quarantined"]) == (3, 2, 1)
    assert not report["corpus_import_complete"]
    bad = report["rows"][1]
    assert bad["record_artifact"] is None
    assert records.read(bad["input_artifact"]) == b'{"broken":true}'


def test_interruption_after_save_before_checkpoint_recovers_idempotently(db, tmp_path, monkeypatch):
    records, queue, worker = services(db, tmp_path)
    digest, _ = staged(records)
    job = queue.submit_legacy_import("interrupted", digest)
    original = records.save_legacy
    calls = 0

    def stop_after_second(record, **kwargs):
        nonlocal calls
        saved = original(record, **kwargs)
        calls += 1
        if calls == 2:
            worker.stop.set()
        return saved

    monkeypatch.setattr(records, "save_legacy", stop_after_second)
    worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_bundle_rows").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM legacy_records").fetchone()["n"] == 2
    worker.stop.clear()
    worker.run_once()
    assert result(records, queue, job)["preserved"] == 3
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_import_attempts").fetchone()["n"] == 3


def test_corrupt_row_is_failure_not_successful_quarantine(db, tmp_path):
    records, queue, worker = services(db, tmp_path)
    digest, bundle = staged(records)
    records.store.path(
        f"blobs/{bundle.entries[0].sha256[:2]}/{bundle.entries[0].sha256}"
    ).write_bytes(b"bad")
    job = queue.submit_legacy_import("corrupt", digest)
    worker.run_once()
    assert queue.get(job.job_id).status != "SUCCEEDED"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_bundle_rows").fetchone()["n"] == 0


def test_sample_never_claims_whole_corpus_complete(db, tmp_path):
    records, queue, worker = services(db, tmp_path)
    digest, _ = staged(records, scope="SAMPLE")
    job = queue.submit_legacy_import("sample", digest)
    worker.run_once()
    assert not result(records, queue, job)["corpus_import_complete"]


def test_full_row_column_mismatch_quarantines_raw(db, tmp_path):
    records, queue, worker = services(db, tmp_path)
    _, bundle = staged(records, count=1)
    modified = LegacyBundle.model_validate(bundle.model_dump() | {"columns": ["wrong"]})
    digest = records.store.put(modified.model_dump_json().encode()).sha256
    job = queue.submit_legacy_import("columns", digest)
    worker.run_once()
    assert result(records, queue, job)["quarantined"] == 1


def test_drain_blocks_import_submission(db, tmp_path):
    records, queue, _ = services(db, tmp_path)
    digest, _ = staged(records)
    queue.set_draining(True)
    with pytest.raises(ValueError, match="RUNTIME_DRAINING"):
        queue.submit_legacy_import("drained", digest)


def test_lost_lease_does_not_commit_row_checkpoint(db, tmp_path):
    from klegal_gold.ingestion.legacy_import import LegacyImporter

    records, queue, _ = services(db, tmp_path)
    digest, _ = staged(records, count=1)
    job = queue.submit_legacy_import("lease", digest)
    claimed = queue.claim("synthetic")
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE job_id=%s",
            (job.job_id,),
        )
    with pytest.raises(ValueError, match="IMPORT_LEASE_LOST"):
        LegacyImporter(records).run(claimed, lambda: None)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_bundle_rows").fetchone()["n"] == 0
