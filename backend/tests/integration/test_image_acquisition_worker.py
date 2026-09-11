import json

import pytest

from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
from klegal_gold.db.records import Records
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def _gif(width=1, height=1):
    return (
        b"GIF89a"
        + width.to_bytes(2, "little")
        + height.to_bytes(2, "little")
        + b"\x80\0\0\0\0\0\xff\xff\xff,\0\0\0\0\x01\0\x01\0\0\x02\x02D\x01\0;"
    )


def test_image_batch_worker_persists_refs_attempts_and_blobs(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    queue = Queue(db, lease_seconds=5)
    manifest = {
        "image_references": [
            {
                "source_system": "scourt",
                "source_id": "100",
                "row_position": 3,
                "name": "ok.gif",
                "resolved_url": "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=ok.gif",
            },
            {"source_system": "scourt", "source_id": "100", "name": "name-only.gif"},
            {
                "source_system": "scourt",
                "source_id": "old",
                "name": "mismatch.gif",
                "resolved_url": "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=mismatch.gif",
                "id_mismatch": True,
            },
        ]
    }
    records.put_artifact(
        "image-manifest:test",
        json.dumps(manifest).encode(),
        origin="MANIFEST",
        metadata={"kind": "IMAGE_REFERENCE_MANIFEST"},
    )

    def fake_fetch(url, max_bytes):
        assert max_bytes > 0
        return DownloadedImage(_gif(), "image/gif", {"format": "GIF", "width": 1, "height": 1})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda records: ImageAcquirer(records, fetcher=fake_fetch),
    )
    job = queue.submit_image_batch(
        "images", "image-manifest:test", max_urls=2, max_total_bytes=1024
    )
    assert Worker(queue, records).run_once()
    assert queue.get(job.job_id).status == "SUCCEEDED"
    with db.connect() as conn:
        statuses = conn.execute(
            "SELECT reference_status,count(*) AS n FROM image_references GROUP BY reference_status"
        ).fetchall()
        acquisition = conn.execute(
            "SELECT status,size_bytes,image_metadata FROM image_acquisitions"
        ).fetchall()
        attempts = conn.execute(
            "SELECT outcome,count(*) AS n FROM image_acquisition_attempts GROUP BY outcome"
        ).fetchall()
    assert {row["reference_status"]: row["n"] for row in statuses} == {
        "RESOLVED": 1,
        "NAME_ONLY": 1,
        "ID_MISMATCH": 1,
    }
    assert {row["status"] for row in acquisition} == {"ACQUIRED"}
    assert acquisition[0]["size_bytes"] > 0
    assert acquisition[0]["image_metadata"] == {"format": "GIF", "width": 1, "height": 1}
    assert {row["outcome"]: row["n"] for row in attempts} == {"ACQUIRED": 1}


def test_image_batch_reuses_acquired_url_on_retry_job(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    queue = Queue(db, lease_seconds=5)
    url = "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?name=ok.gif"
    records.put_artifact(
        "image-manifest:test",
        json.dumps({"image_references": [{"source_id": "100", "resolved_url": url}]}).encode(),
        origin="MANIFEST",
        metadata={"kind": "IMAGE_REFERENCE_MANIFEST"},
    )
    calls = 0

    def fake_fetch(url, max_bytes):
        nonlocal calls
        calls += 1
        return DownloadedImage(_gif(), "image/gif", {"format": "GIF", "width": 1, "height": 1})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda records: ImageAcquirer(records, fetcher=fake_fetch),
    )
    first = queue.submit_image_batch(
        "images-1", "image-manifest:test", max_urls=1, max_total_bytes=1024
    )
    assert Worker(queue, records).run_once()
    second = queue.submit_image_batch(
        "images-2", "image-manifest:test", max_urls=1, max_total_bytes=1024
    )
    assert Worker(queue, records).run_once()
    assert queue.get(first.job_id).status == "SUCCEEDED"
    assert queue.get(second.job_id).status == "SUCCEEDED"
    with db.connect() as conn:
        attempts = conn.execute(
            "SELECT outcome,count(*) AS n FROM image_acquisition_attempts GROUP BY outcome"
        ).fetchall()
    assert calls == 1
    assert {row["outcome"]: row["n"] for row in attempts} == {"ACQUIRED": 1, "SKIPPED": 1}
