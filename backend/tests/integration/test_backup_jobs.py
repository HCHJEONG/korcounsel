"""Backup admission, interruption/recovery and authenticated API on real PostgreSQL."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from klegal_gold.config import Settings
from klegal_gold.db.records import Records
from klegal_gold.db.site_accounts import SiteAccounts
from klegal_gold.jobs.backup import run_backup
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.backup import verify_backup
from klegal_gold.storage.files import FileStore
from klegal_gold.web import app as web
from klegal_gold.web.auth import accounts

pytestmark = pytest.mark.integration


@pytest.fixture
def backup_setup(db, tmp_path, monkeypatch):
    root = tmp_path / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(root))
    monkeypatch.delenv("LEGACY_PARQUET_PATH", raising=False)
    records = Records(db, FileStore(tmp_path / "source"))
    records.put_artifact(
        "backup-original", b"immutable-original", origin="HTTP_RESPONSE", metadata={}
    )
    queue = Queue(db)
    return root, records, queue


def test_backup_idempotency_drain_and_single_active(backup_setup):
    _, _, queue = backup_setup
    one = queue.submit_backup("one")
    assert queue.submit_backup("one").job_id == one.job_id
    with pytest.raises(ValueError, match="BACKUP_ALREADY_ACTIVE"):
        queue.submit_backup("two")
    queue.set_draining(True)
    assert queue.submit_backup("one").job_id == one.job_id
    with pytest.raises(ValueError, match="RUNTIME_DRAINING"):
        queue.submit_backup("three")


def test_completed_bundle_reused_after_lost_job_completion(backup_setup, monkeypatch, tmp_path):
    root, records, queue = backup_setup
    parquet = tmp_path / "fixture.parquet"
    parquet.write_bytes(b"fixed-parquet-fixture")
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(parquet))
    calls = []

    def dump(worker, snapshot, path, progress):
        calls.append(snapshot)
        path.write_bytes(b"PGDMPfixture")

    monkeypatch.setattr("klegal_gold.jobs.backup.dump_snapshot", dump)
    job = queue.submit_backup("recover")
    worker = Worker(queue, records)
    claimed = queue.claim(worker.worker_id)
    run_backup(worker, claimed)
    queue.finish(claimed, outcome="CHECKPOINTED")
    assert worker.run_once()
    done = queue.get(job.job_id)
    assert done.status == "SUCCEEDED"
    assert len(calls) == 1
    assert len(list(root.iterdir())) == 1
    assert done.checkpoint["parquet_included"]
    assert not done.checkpoint["restore_verified"]
    bundle = root / done.checkpoint["backup_id"]
    verify_backup(bundle)
    (bundle / "legacy.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match="BACKUP_EXTRA_INTEGRITY"):
        verify_backup(bundle)
    assert records.read("backup-original") == b"immutable-original"


def test_partial_attempt_gets_new_directory(backup_setup, monkeypatch):
    root, records, queue = backup_setup
    calls = []

    def dump(worker, snapshot, path, progress):
        from klegal_gold.jobs.worker import CheckpointRequested

        calls.append(snapshot)
        path.write_bytes(b"PGDMPfixture")
        if len(calls) == 1:
            raise CheckpointRequested

    monkeypatch.setattr("klegal_gold.jobs.backup.dump_snapshot", dump)
    job = queue.submit_backup("partial")
    worker = Worker(queue, records)
    assert worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    assert not list(root.glob("*/manifest.json"))
    assert worker.run_once()
    assert queue.get(job.job_id).status == "SUCCEEDED"
    assert len(list(root.iterdir())) == 2
    assert len(list(root.glob("*/manifest.json"))) == 1


def test_missing_source_never_publishes_backup(backup_setup):
    root, records, queue = backup_setup
    blob = records.blob("backup-original")
    records.store.path(blob.storage_key).unlink()
    job = queue.submit_backup("missing")
    assert Worker(queue, records).run_once()
    assert queue.get(job.job_id).status != "SUCCEEDED"
    assert not list(root.glob("*/manifest.json"))


def test_backup_api_roles_origin_history_and_lost_response(db, tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        korcounsel_admin_id="admin-fixture",
        korcounsel_admin_password=SecretStr("admin-fixture-password"),
        korcounsel_dev_editor_id="editor-fixture",
        korcounsel_dev_editor_password=SecretStr("editor-fixture-password"),
    )
    monkeypatch.setattr(web, "load_settings", lambda: settings)
    monkeypatch.setattr("klegal_gold.web.auth.load_settings", lambda: settings)
    monkeypatch.setattr(web.Database, "from_settings", lambda _: db)
    app = web.create_app()
    app.dependency_overrides[accounts] = lambda: SiteAccounts(db, settings)
    headers = {"Origin": settings.web_origin}
    body = {"request_id": str(uuid4())}
    with TestClient(app) as client:
        assert client.get("/api/admin/backups").status_code == 401
        assert client.post("/api/admin/backups", json=body, headers=headers).status_code == 401
        for role, expected in (("editor", 403), ("admin", 200)):
            assert (
                client.post(
                    "/api/auth/login",
                    json={"username": role + "-fixture", "password": role + "-fixture-password"},
                    headers=headers,
                ).status_code
                == 200
            )
            assert client.get("/api/admin/backups").status_code == expected
            assert client.post("/api/admin/backups", json=body).status_code == 403
            response = client.post("/api/admin/backups", json=body, headers=headers)
            assert response.status_code == expected
        assert (
            client.post("/api/admin/backups", json=body, headers=headers).json() == response.json()
        )
        assert len(client.get("/api/admin/backups").json()["items"]) == 1
        assert (
            client.post(
                "/api/admin/backups", json={"request_id": str(uuid4())}, headers=headers
            ).status_code
            == 409
        )
