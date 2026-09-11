"""Rejected image responses are immutable HTTP evidence, never acquired reader images."""

import json
from datetime import datetime
from hashlib import sha256

import pytest

from klegal_gold.assets.images import (
    DownloadedImage,
    ImageAcquirer,
    ImageResponseRejected,
)
from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
URL = (
    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on"
    "?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=bad.gif"
)
HTML = b"<html>\r\n<script>unsafe()</script><body>provider error</body>\r\n</html>"
BROKEN_GIF = b"GIF89a\x01\x00\x01\x00\x80"
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


def setup_job(db, tmp_path, *, urls=(URL,), budget=1024):
    records = Records(db, FileStore(tmp_path))
    records.put_artifact(
        "image-manifest:rejected",
        json.dumps(
            {"references": [{"source_id": "123", "resolved_url": u} for u in urls]}
        ).encode(),
        origin="MANIFEST",
        metadata={"kind": "IMAGE_REFERENCE_MANIFEST"},
    )
    queue = Queue(db)
    job = queue.submit_image_batch(
        "reject-1", "image-manifest:rejected", max_urls=len(urls), max_total_bytes=budget
    )
    return records, queue, job


def quarantined(db):
    with db.connect() as conn:
        return conn.execute(
            "SELECT artifact_id,blob_hash,origin,parent_id,metadata FROM artifacts "
            "WHERE metadata->>'kind'='IMAGE_DECODE_FAILURE_RESPONSE' ORDER BY artifact_id"
        ).fetchall()


@pytest.mark.parametrize("raw,content_type", [(HTML, "text/html"), (BROKEN_GIF, "image/gif")])
@pytest.mark.parametrize("raised", [False, True])
def test_failed_bytes_are_linked_to_attempt_without_becoming_image(
    db, tmp_path, monkeypatch, raw, content_type, raised
):
    records, queue, job = setup_job(db, tmp_path)
    response = DownloadedImage(
        raw, content_type, {"final_url": URL, "retrieved_at": "2026-09-11T10:20:30+00:00"}
    )

    def fetch(url, limit):
        if raised:
            raise ImageResponseRejected("IMAGE_DECODE_FAILED", response)
        return response

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda saved: ImageAcquirer(saved, fetcher=fetch),
    )
    assert Worker(queue, records).run_once()
    finished = queue.get(job.job_id)
    assert finished.status == "SUCCEEDED"
    assert finished.checkpoint["image_failed"] == 1
    assert finished.checkpoint["image_acquired"] == 0
    assert finished.checkpoint["image_bytes_stored"] == 0
    artifacts = quarantined(db)
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["origin"] == "HTTP_RESPONSE"
    assert artifact["parent_id"] == "image-manifest:rejected"
    assert records.read(artifact["artifact_id"]) == raw
    assert artifact["blob_hash"] == sha256(raw).hexdigest()
    meta = artifact["metadata"]
    assert meta["raw_content_hash"] == artifact["blob_hash"]
    assert meta["url"] == meta["final_url"] == URL
    assert meta["content_type"] == content_type
    assert meta["job_id"] == str(job.job_id)
    assert meta["error_code"] == "IMAGE_DECODE_FAILED"
    assert meta["decode_verified"] is False and meta["acquisition_status"] == "FAILED"
    assert datetime.fromisoformat(meta["retrieved_at"]).tzinfo is not None
    with db.connect() as conn:
        attempt = conn.execute("SELECT * FROM image_acquisition_attempts").fetchone()
        acquisition = conn.execute("SELECT * FROM image_acquisitions").fetchone()
        assert (
            conn.execute(
                "SELECT 1 FROM artifacts WHERE artifact_id=%s",
                ("reader-image:" + artifact["blob_hash"],),
            ).fetchone()
            is None
        )
    assert str(attempt["attempt_id"]) == meta["attempt_id"]
    assert attempt["outcome"] == acquisition["status"] == "FAILED"
    assert attempt["blob_hash"] is acquisition["blob_hash"] is None
    reader = ReaderStore(records)
    document = reader.preserve(
        '<input class="contImagePath" name="a" value="bad.gif"><p><img name="a"></p>',
        title="Quarantined response",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={URL: {"status": "FAILED"}},
    )
    assert reader.read(document)["images"][0].get("blob_hash") is None
    assert "unsafe()" not in reader.html(document)
    with pytest.raises(ValueError, match="READER_IMAGE_UNAVAILABLE"):
        reader.image(document, 0)
    with pytest.raises(ValueError, match="ARTIFACT_NOT_FOUND"):
        records.read("reader-image:" + artifact["blob_hash"])


def test_later_success_preserves_prior_rejection_and_attempt(db, tmp_path):
    records, queue, first = setup_job(db, tmp_path)
    invalid = DownloadedImage(HTML, "text/html", {})
    ImageAcquirer(records, fetcher=lambda *_: invalid).run(first)
    old = quarantined(db)[0]
    second = queue.submit_image_batch("reject-retry", "image-manifest:rejected", max_urls=1)
    result = ImageAcquirer(records, fetcher=lambda *_: DownloadedImage(GIF, "image/gif", {})).run(
        second
    )
    assert result.acquired == 1 and result.failed == 0
    assert records.read(old["artifact_id"]) == HTML
    assert quarantined(db) == [old]
    with db.connect() as conn:
        attempts = conn.execute(
            "SELECT outcome,blob_hash FROM image_acquisition_attempts"
        ).fetchall()
        acquired = conn.execute("SELECT status,blob_hash FROM image_acquisitions").fetchone()
    assert {a["outcome"] for a in attempts} == {"FAILED", "ACQUIRED"}
    assert next(a for a in attempts if a["outcome"] == "FAILED")["blob_hash"] is None
    assert acquired == {"status": "ACQUIRED", "blob_hash": sha256(GIF).hexdigest()}


def test_rejected_body_consumes_batch_storage_budget(db, tmp_path):
    second_url = URL.replace("bad.gif", "second.gif")
    records, _, job = setup_job(db, tmp_path, urls=(URL, second_url), budget=len(HTML))
    calls = []

    def fetch(url, limit):
        calls.append((url, limit))
        return DownloadedImage(HTML, "text/html", {})

    result = ImageAcquirer(records, fetcher=fetch).run(job, max_total_bytes=len(HTML))
    assert result.failed == result.skipped == 1 and result.acquired == 0
    assert result.bytes_stored == 0
    assert calls == [(URL, len(HTML))]
    assert len(quarantined(db)) == 1


def test_custom_fetcher_cannot_preserve_body_over_remaining_limit(db, tmp_path):
    records, _, job = setup_job(db, tmp_path, budget=4)
    result = ImageAcquirer(records, fetcher=lambda *_: DownloadedImage(HTML, "text/html", {})).run(
        job, max_total_bytes=4
    )
    assert result.failed == 1 and result.bytes_stored == 0
    assert quarantined(db) == []


def test_corrupt_quarantine_blob_blocks_new_failure_receipt(db, tmp_path):
    records, queue, job = setup_job(db, tmp_path)
    acquirer = ImageAcquirer(records, fetcher=lambda *_: DownloadedImage(HTML, "text/html", {}))
    acquirer.run(job)
    original = quarantined(db)[0]
    blob = records.blob(original["artifact_id"])
    records.store.path(blob.storage_key).write_bytes(b"x" * len(HTML))
    with pytest.raises(ValueError, match="BLOB_INTEGRITY_FAILED"):
        records.read(original["artifact_id"])
    retry = queue.submit_image_batch("retry-corrupt", "image-manifest:rejected", max_urls=1)
    with pytest.raises(ValueError, match="BLOB_INTEGRITY_FAILED"):
        acquirer.run(retry)
    assert quarantined(db) == [original]
    with db.connect() as conn:
        assert (
            conn.execute("SELECT count(*) n FROM image_acquisition_attempts").fetchone()["n"] == 1
        )
