"""Synthetic OSError recovery: final worker counters are not cumulative job totals."""

import json
from hashlib import sha256

import pytest

from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
from klegal_gold.db.records import Records
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
URL = (
    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on"
    "?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm="
)


def test_same_image_job_resumes_partial_success_without_redownloading(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    queue = Queue(db)
    first_url, second_url = URL + "first.gif", URL + "second.gif"
    # A different palette preserves a valid single-frame GIF while giving a second hash.
    second_body = GIF[:13] + b"\x01" + GIF[14:]
    records.put_artifact(
        "image-manifest:partial-resume",
        json.dumps(
            {
                "references": [
                    {"source_id": "123", "resolved_url": u} for u in (first_url, second_url)
                ]
            }
        ).encode(),
        origin="MANIFEST",
        metadata={"kind": "IMAGE_REFERENCE_MANIFEST"},
    )
    calls = []

    def fetch(url, max_bytes):
        calls.append(url)
        if url == second_url and calls.count(second_url) == 1:
            # Synthetic interruption only; the live HANDLER_FAILED cause is not established.
            raise OSError("synthetic interruption after first image")
        body = GIF if url == first_url else second_body
        assert len(body) <= max_bytes
        return DownloadedImage(body, "image/gif", {})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda saved: ImageAcquirer(saved, fetcher=fetch),
    )
    job = queue.submit_image_batch(
        "partial-resume", "image-manifest:partial-resume", max_urls=2, max_total_bytes=1024
    )
    assert Worker(queue, records).run_once()
    partial = queue.get(job.job_id)
    assert partial.status == "QUEUED" and partial.attempts == 1
    assert partial.checkpoint["image_acquired"] == 1
    with db.connect() as conn:
        first_saved = conn.execute(
            "SELECT * FROM image_acquisitions WHERE url=%s", (first_url,)
        ).fetchone()
        first_attempt = conn.execute(
            "SELECT * FROM image_acquisition_attempts WHERE job_id=%s AND url=%s",
            (job.job_id, first_url),
        ).fetchone()
        assert (
            conn.execute("SELECT 1 FROM image_acquisitions WHERE url=%s", (second_url,)).fetchone()
            is None
        )
        # Advance only this isolated fixture's retry eligibility, without a sleep.
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (job.job_id,)
        )
    digest = sha256(GIF).hexdigest()
    assert first_saved["status"] == "ACQUIRED" and first_saved["blob_hash"] == digest
    first_path = records.store.path(f"blobs/{digest[:2]}/{digest}")
    assert first_path.read_bytes() == GIF
    same = queue.submit_image_batch(
        "partial-resume", "image-manifest:partial-resume", max_urls=2, max_total_bytes=1024
    )
    assert same.job_id == job.job_id
    assert Worker(queue, records).run_once()
    final = queue.get(job.job_id)
    assert final.status == "SUCCEEDED" and final.attempts == 2
    assert calls == [first_url, second_url, second_url]
    assert first_path.read_bytes() == GIF
    with db.connect() as conn:
        assert (
            conn.execute("SELECT * FROM image_acquisitions WHERE url=%s", (first_url,)).fetchone()
            == first_saved
        )
        assert (
            conn.execute(
                "SELECT * FROM image_acquisition_attempts WHERE attempt_id=%s",
                (first_attempt["attempt_id"],),
            ).fetchone()
            == first_attempt
        )
        claims = conn.execute(
            "SELECT outcome,error_code FROM job_attempts WHERE job_id=%s ORDER BY attempt",
            (job.job_id,),
        ).fetchall()
        totals = conn.execute(
            "SELECT count(*) n,sum(size_bytes) bytes FROM image_acquisition_attempts "
            "WHERE job_id=%s AND outcome='ACQUIRED'",
            (job.job_id,),
        ).fetchone()
        outcomes = conn.execute(
            "SELECT outcome,count(*) n FROM image_acquisition_attempts "
            "WHERE job_id=%s GROUP BY outcome",
            (job.job_id,),
        ).fetchall()
        assert conn.execute("SELECT count(*) n FROM jobs").fetchone()["n"] == 1
    assert claims == [
        {"outcome": "FAILED", "error_code": "HANDLER_FAILED"},
        {"outcome": "SUCCEEDED", "error_code": None},
    ]
    assert {r["outcome"]: r["n"] for r in outcomes} == {"ACQUIRED": 2, "SKIPPED": 1}
    assert totals == {"n": 2, "bytes": len(GIF) + len(second_body)}
    # The final checkpoint counts only the second execution, while the ledger covers the job.
    assert final.checkpoint["image_acquired"] == 1
    assert final.checkpoint["image_skipped"] == 1
    assert final.checkpoint["image_bytes_stored"] == len(second_body)
