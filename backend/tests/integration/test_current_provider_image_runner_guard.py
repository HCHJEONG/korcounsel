"""Actual isolated Queue/Worker: decode failure plus later exception leaves a guarded job."""

import importlib.util
import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def test_failed_image_then_worker_exception_is_paused_without_retry(db, tmp_path, monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "current_image_runner_integration", scripts / "run_current_provider_images.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    import audit_current_provider_images as audit

    records = Records(db, FileStore(tmp_path / "blobs"))
    html = "".join(
        f'<input class="contImagePath" name="{n}" value="{n}.gif"><img name="{n}">'
        for n in ("first", "second", "third")
    )
    reader_id = ReaderStore(records).preserve(
        html,
        title="Synthetic current source",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={"fixture": True},
        acquisitions={},
    )
    parent, refs = audit.inspect_reader(records, reader_id, [])
    refs = [audit.classify(ref, None, 0) for ref in refs]
    audit_value = {
        "version": audit.VERSION,
        "scope": audit.SCOPE,
        "notice": audit.NOTICE,
        "legacy_link_approved": False,
        "snapshot_at": "fixture",
        "receipts": [],
        "parents": [parent],
        "references": refs,
        "verified_blobs": [],
        "verification": {
            "receipt_reader_and_html_hashes": True,
            "all_image_occurrences_reparsed_and_matched": True,
            "unique_parent_and_order": True,
        },
        "summary": {"eligible_never_attempted": audit.count_refs(refs)},
    }
    audit_dir = tmp_path / "audit"
    audit.write_audit(audit_value, audit_dir, write_manifests=True)
    digest = sha256((audit_dir / "summary.json").read_bytes()).hexdigest()
    input_value = runner.load_audit(audit_dir, digest)
    first, second, third = [ref["resolved_url"] for ref in refs]
    calls = []

    def fetch(url, limit):
        calls.append(url)
        if url == first:
            return DownloadedImage(b"not an image", "text/plain", {})
        raise OSError("synthetic worker-level interruption")

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer", lambda saved: ImageAcquirer(saved, fetcher=fetch)
    )
    output = tmp_path / "run"
    report = runner.run(input_value, records, output)
    assert report["status"] == "PAUSED"
    assert report["stop_reason"] == "CURRENT_ONLY_PRIOR_ATTEMPT_REQUIRES_REVIEW"
    assert report["results"][0]["status"] == "QUEUED"
    job_id = UUID(report["results"][0]["job_id"])
    job = Queue(db).get(job_id)
    assert job.status == "QUEUED" and job.attempts == 1
    assert job.checkpoint["image_failed"] == 1
    assert calls == [first, second] and third not in calls
    with db.connect() as conn:
        acquisition_before = conn.execute("SELECT * FROM image_acquisitions").fetchall()
        attempts_before = conn.execute("SELECT * FROM image_acquisition_attempts").fetchall()
        rejected = conn.execute(
            "SELECT artifact_id,parent_id,metadata FROM artifacts "
            "WHERE metadata->>'kind'='IMAGE_DECODE_FAILURE_RESPONSE'"
        ).fetchall()
        jobs_before = conn.execute("SELECT * FROM jobs").fetchall()
        claims_before = conn.execute("SELECT * FROM job_attempts").fetchall()
        contexts = conn.execute("SELECT row_position,context FROM image_references").fetchall()
    assert len(acquisition_before) == len(attempts_before) == len(rejected) == 1
    assert acquisition_before[0]["url"] == first and acquisition_before[0]["status"] == "FAILED"
    assert attempts_before[0]["outcome"] == "FAILED"
    assert rejected[0]["parent_id"] == report["results"][0]["manifest_artifact_id"]
    assert records.read(rejected[0]["artifact_id"]) == b"not an image"
    assert len(claims_before) == 1 and claims_before[0]["outcome"] == "FAILED"
    assert claims_before[0]["error_code"] == "HANDLER_FAILED"
    assert all(
        row["row_position"] is None and row["context"]["legacy_link_approved"] is False
        for row in contexts
    )
    same = runner.run(input_value, records, output)
    assert same["status"] == "PAUSED" and same["stop_reason"] == report["stop_reason"]
    assert same["executed_batches"] == 0
    assert calls == [first, second]
    with db.connect() as conn:
        assert conn.execute("SELECT * FROM image_acquisitions").fetchall() == acquisition_before
        assert (
            conn.execute("SELECT * FROM image_acquisition_attempts").fetchall() == attempts_before
        )
        assert conn.execute("SELECT * FROM jobs").fetchall() == jobs_before
        assert conn.execute("SELECT * FROM job_attempts").fetchall() == claims_before
        assert (
            conn.execute(
                "SELECT count(*) n FROM image_acquisitions WHERE url=ANY(%s)", ([second, third],)
            ).fetchone()["n"]
            == 0
        )
    assert json.loads(records.read(same["artifact_id"]))["status"] == "PAUSED"
