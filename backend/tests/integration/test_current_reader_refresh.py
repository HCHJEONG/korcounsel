import json
from uuid import UUID

import pytest

from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


def stage(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    readers = ReaderStore(records)
    html = (
        '<input class="contImagePath" name="a" value="a.gif">'
        '<input class="contImagePath" name="b" value="b.gif">'
        '<p>앞<img name="a"></p><table><tr><td><img name="a"></td></tr></table>'
        '<img name="b"><img name="unknown">'
    )
    document = readers.preserve(
        html,
        title="old title",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    refs = [
        {**ref, "source_system": "scourt", "source_id": "123", "reader_document_id": document}
        for ref in readers.read(document)["images"]
    ]
    records.put_artifact(
        "images:test", json.dumps({"references": refs}).encode(), origin="MANIFEST", metadata={}
    )
    queue = Queue(db)
    image = queue.submit_image_batch("images", "images:test")
    refresh = queue.submit_current_reader_refresh(document, image.job_id)
    return records, readers, queue, image, refresh, document


def test_dependency_partial_failure_and_immutable_revision(db, tmp_path, monkeypatch):
    records, readers, queue, image, refresh, original = stage(db, tmp_path)
    before = records.read("reader:" + original)
    # A queued refresh must not consume attempts while acquisition is delayed.
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp()+interval '1 hour' WHERE job_id=%s",
            (image.job_id,),
        )
    assert queue.claim("test") is None
    assert queue.get(refresh.job_id).attempts == 0
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (image.job_id,)
        )

    def fetch(url, max_bytes):
        if "b.gif" in url:
            raise ValueError("IMAGE_NETWORK_ERROR")
        return DownloadedImage(GIF, "image/gif", {})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda records: ImageAcquirer(records, fetcher=fetch),
    )
    worker = Worker(queue, records)
    assert worker.run_once()
    assert queue.get(image.job_id).status == "SUCCEEDED"
    assert readers.search()[0]["document_id"] == original
    assert worker.run_once()
    done = queue.get(refresh.job_id)
    assert done.status == "SUCCEEDED"
    revision = done.checkpoint["reader_document_id"]
    manifest = readers.read(revision)
    assert [ref["status"] for ref in manifest["images"]] == [
        "ACQUIRED",
        "ACQUIRED",
        "FAILED",
        "PENDING",
    ]
    assert records.read("reader:" + original) == before
    assert manifest["html_sha256"] == readers.read(original)["html_sha256"]
    assert readers.refresh_current_images(original) == revision
    assert queue.submit_current_reader_refresh(original, image.job_id).job_id == refresh.job_id
    assert readers.search()[0]["document_id"] == revision
    assert len(readers.search()) == 1
    assert readers.image(revision, 0)[0] == GIF == readers.image(revision, 1)[0]
    rendered = readers.html(revision)
    assert f"/api/reader/{revision}/images/0" in rendered
    assert f"/api/reader/{revision}/images/1" in rendered
    assert "이미지 미확보" in rendered


def test_terminal_dependency_failure_still_publishes_pending(db, tmp_path):
    records, readers, queue, image, refresh, original = stage(db, tmp_path)
    for _ in range(3):
        claimed = queue.claim("test")
        assert claimed.job_id == image.job_id
        queue.finish(claimed, outcome="FAILED", error_code="HANDLER_FAILED")
        with db.connect() as conn:
            conn.execute(
                "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (image.job_id,)
            )
    assert Worker(queue, records).run_once()
    done = queue.get(refresh.job_id)
    assert done.status == "SUCCEEDED"
    assert done.checkpoint["image_job_status"] == "FAILED"
    assert len(readers.read(done.checkpoint["reader_document_id"])["images"]) == 4


def test_late_old_refresh_cannot_hide_new_body_or_match_old_title(db, tmp_path):
    records, readers, queue, image, refresh, original = stage(db, tmp_path)
    current = readers.preserve(
        "<p>new body</p>",
        title="new title",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    readers.refresh_current_images(original)
    assert readers.search()[0]["document_id"] == current
    assert readers.search("old title") == []
    assert len(readers.search("new title")) == 1


def test_detail_resume_only_submits_followups(db, tmp_path, monkeypatch):
    records, readers, queue, image, refresh, original = stage(db, tmp_path)
    detail = queue.submit_scourt_detail("detail", "123")
    from psycopg.types.json import Jsonb

    for expected in (image, refresh):
        claimed = queue.claim("test")
        assert claimed.job_id == expected.job_id
        queue.finish(claimed, outcome="SUCCEEDED")
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET checkpoint=%s WHERE job_id=%s",
            (
                Jsonb({"reader_document_id": original, "image_manifest_id": "images:test"}),
                detail.job_id,
            ),
        )

    def forbidden(*args, **kwargs):
        pytest.fail("Resumed detail must not fetch mutable source again")

    monkeypatch.setattr("klegal_gold.jobs.worker.ScourtPortalSource", forbidden)
    assert Worker(queue, records).run_once()
    done = queue.get(detail.job_id)
    assert done.status == "SUCCEEDED"
    assert queue.get(UUID(done.checkpoint["reader_refresh_job_id"])).status == "QUEUED"


def test_title_search_does_not_scan_unrelated_reader_bodies(db, tmp_path, monkeypatch):
    records, readers, queue, image, refresh, original = stage(db, tmp_path)
    other = readers.preserve(
        "<p>unrelated</p>",
        title="unrelated",
        source_id="456",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    read = readers.read

    def guarded(document_id):
        assert document_id != other
        return read(document_id)

    monkeypatch.setattr(readers, "read", guarded)
    from klegal_gold.web.app import _current_reader_matches

    result = _current_reader_matches(readers, "old title", limit=30)
    assert len(result) == 1 and result[0].reader_document_id == original


def test_admin_reader_retry_reuses_request_and_reports_origin(db, tmp_path, monkeypatch):
    from importlib import import_module
    from uuid import uuid4

    from fastapi.testclient import TestClient

    from klegal_gold.config import Settings
    from klegal_gold.web.auth import require_admin, require_user
    from klegal_gold.web.reader import reader_store

    web = import_module("klegal_gold.web.app")
    settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr(web, "load_settings", lambda: settings)
    monkeypatch.setattr(web.Database, "from_settings", lambda _: db)
    records = Records(db, FileStore(tmp_path))
    store = ReaderStore(records)
    queue = Queue(db)
    parent = queue.submit_scourt_detail("retry-parent", "123")
    document = store.preserve(
        "<p>본문</p>",
        title="case",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={"job_id": str(parent.job_id)},
        acquisitions={},
    )
    app = web.create_app()
    app.dependency_overrides[require_admin] = lambda: object()
    app.dependency_overrides[require_user] = lambda: object()
    app.dependency_overrides[reader_store] = lambda: store
    client = TestClient(app)
    assert client.get(f"/api/reader/{document}/html").headers["X-Reader-Origin"] == "CURRENT_SOURCE"
    body = {"request_id": str(uuid4())}
    path = f"/api/admin/readers/{document}/lawgo"
    first = client.post(path, json=body, headers={"Origin": settings.web_origin})
    assert first.status_code == 200
    assert (
        client.post(path, json=body, headers={"Origin": settings.web_origin}).json() == first.json()
    )
    assert queue.get(UUID(first.json()["job_id"])).attempts == 0
    assert (
        client.post(path, json=body, headers={"Origin": "https://untrusted.invalid"}).status_code
        == 403
    )
    from klegal_gold.db.accounts import Accounts
    from klegal_gold.web.auth import accounts

    app.dependency_overrides.pop(require_admin)
    app.dependency_overrides.pop(require_user)
    app.dependency_overrides[accounts] = lambda: Accounts(db)
    assert client.post(path, json=body, headers={"Origin": settings.web_origin}).status_code == 401


def test_image_retry_coordinator_preserves_positions_and_replays(db, tmp_path, monkeypatch):
    records, readers, queue, _, _, original = stage(db, tmp_path)
    # The retry is a separate persistent command bound to the selected revision.
    retry = queue.submit_current_image_retry("explicit-retry", original)
    worker = Worker(queue, records)
    attempts = {}

    def fetch(url, limit):
        attempts[url] = attempts.get(url, 0) + 1
        if "b.gif" in url and attempts[url] == 1:
            raise ValueError("IMAGE_NETWORK_ERROR")
        return DownloadedImage(GIF, "image/gif", {})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda records: ImageAcquirer(records, fetcher=fetch),
    )
    for _ in range(8):
        worker.run_once()
    done = queue.get(retry.job_id)
    assert done.status == "SUCCEEDED"
    refresh = queue.get(UUID(done.checkpoint["follow_up_job_id"]))
    assert refresh.status == "SUCCEEDED"
    manifest = readers.read(refresh.checkpoint["reader_document_id"])
    assert [im["status"] for im in manifest["images"]] == [
        "ACQUIRED",
        "ACQUIRED",
        "ACQUIRED",
        "PENDING",
    ]
    assert readers.read(original)["images"][0]["status"] == "PENDING"
    assert any("b.gif" in url and count == 2 for url, count in attempts.items())
    assert queue.submit_current_image_retry("explicit-retry", original).job_id == retry.job_id
