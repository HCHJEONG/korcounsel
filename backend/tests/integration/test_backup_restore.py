"""Real pg_dump/pg_restore drill in a disposable DB, never an operational restore."""

import json
import os
import re
import secrets
import shutil
import subprocess
from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
from klegal_gold.db.accounts import Accounts
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.backup import create_backup, verify_backup
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


def table_rows(db):
    with db.connect() as conn:
        tables = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (db.schema,)
        ).fetchall()
        return {
            row["tablename"]: conn.execute(
                sql.SQL("SELECT to_jsonb(t) AS row FROM {} t ORDER BY to_jsonb(t)::text").format(
                    sql.Identifier(db.schema, row["tablename"])
                )
            ).fetchall()
            for row in tables
        }


def test_postgres_dump_and_files_restore_reader_accounts_and_pending_jobs(
    db, tmp_path, monkeypatch
):
    container = os.environ.get("KLEGAL_TEST_PG_CONTAINER")
    if not container:
        pytest.skip("Set KLEGAL_TEST_PG_CONTAINER for the explicit local restore drill")
    assert re.fullmatch(r"[a-zA-Z0-9_.-]+", container)
    info = conninfo_to_dict(os.environ["KLEGAL_TEST_DATABASE_URL"])
    assert info["dbname"] == "korcounsel_test"
    env = os.environ.copy()
    env["PGUSER"], env["PGPASSWORD"] = info["user"], info.get("password", "")

    def pgtool(tool, args, *, output=None, input_file=None):
        cmd = ["docker", "exec", "-i", "-e", "PGUSER", "-e", "PGPASSWORD", container, tool, *args]
        result = subprocess.run(
            cmd,
            env=env,
            stdout=output or subprocess.PIPE,
            stdin=input_file,
            stderr=subprocess.PIPE,
            timeout=90,
        )
        assert result.returncode == 0, f"{tool} failed; diagnostic suppressed to protect DB data"
        return result.stdout

    # Verify the CLI targets the same PostgreSQL cluster as the fixture connection.
    with db.connect() as conn:
        cluster = conn.execute(
            "SELECT system_identifier::text AS id FROM pg_control_system()"
        ).fetchone()["id"]
    assert (
        pgtool(
            "psql",
            ["-d", "korcounsel_test", "-Atc", "SELECT system_identifier FROM pg_control_system()"],
        )
        .decode()
        .strip()
        == cluster
    )
    records = Records(db, FileStore(tmp_path / "source"))
    account = Accounts(db)
    password = secrets.token_urlsafe(24)
    account.create("restore-fixture", password)
    token = account.issue_session("restore-fixture", password)
    users = account.session_user(token)
    reader = ReaderStore(records)
    doc = reader.preserve(
        '<input class="contImagePath" name="a" value="a.gif">'
        '<input class="contImagePath" name="b" value="b.gif">'
        '<p>복원 판례<img name="a"><img name="a"><img name="b"><img name="unknown"></p>'
        '<a name="linkPrvs" jtable="&lt;table&gt;&lt;tr&gt;&lt;td&gt;보존 조문'
        '&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;">시험법 제1조</a>'
        '<a name="linkPrvs">미연결 조문</a>',
        title="복원 검증 판례",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    refs = [
        {**ref, "source_system": "scourt", "source_id": "123", "reader_document_id": doc}
        for ref in reader.read(doc)["images"]
    ]
    records.put_artifact(
        "images:restore", json.dumps({"references": refs}).encode(), origin="MANIFEST", metadata={}
    )
    queue = Queue(db)
    image = queue.submit_image_batch("restore-images", "images:restore")
    claim = queue.claim("before-backup")

    def fetch(url, max_bytes):
        if "b.gif" in url:
            raise ValueError("IMAGE_NETWORK_ERROR")
        return DownloadedImage(GIF, "image/gif", {})

    ImageAcquirer(records, fetcher=fetch).run(claim)
    queue.finish(claim, outcome="SUCCEEDED")
    revision = reader.refresh_current_images(doc)
    pending = queue.submit("verify-after-restore", "reader:" + revision)
    expected = table_rows(db)
    rendered = reader.html(revision)
    bundle = tmp_path / "backup"

    def dump(snapshot, output):
        # Independent committed write after export proves files and DB use one snapshot.
        records.put_artifact(
            "after-snapshot", b"excluded from backup", origin="DERIVED", metadata={}
        )
        with output.open("xb") as stream:
            pgtool(
                "pg_dump",
                [
                    "-d",
                    "korcounsel_test",
                    "-Fc",
                    "--no-owner",
                    "--no-privileges",
                    "--schema=" + db.schema,
                    "--snapshot=" + snapshot,
                ],
                output=stream,
            )

    manifest = create_backup(db, records.store, bundle, dump)
    assert verify_backup(bundle) == manifest
    assert records.blob("after-snapshot").sha256 not in {b["sha256"] for b in manifest["blobs"]}
    target_name = "korcounsel_restore_" + uuid4().hex
    target_dsn = make_conninfo(**{**info, "dbname": target_name})
    created = False
    try:
        with psycopg.connect(os.environ["KLEGAL_TEST_DATABASE_URL"], autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
            created = True
        with psycopg.connect(target_dsn) as conn:
            conn.execute("CREATE EXTENSION pg_trgm WITH SCHEMA public")
        with (bundle / "database.dump").open("rb") as stream:
            pgtool(
                "pg_restore",
                ["-d", target_name, "--no-owner", "--no-privileges", "--exit-on-error"],
                input_file=stream,
            )
        restored_db = Database(target_dsn, schema=db.schema)
        assert table_rows(restored_db) == expected
        restored_files = tmp_path / "restored-files"
        shutil.copytree(bundle / "files", restored_files)
        restored = ReaderStore(Records(restored_db, FileStore(restored_files)))
        assert [r["document_id"] for r in restored.search("복원")] == [revision]
        assert restored.html(revision) == rendered
        assert (
            "보존 조문" in rendered
            and "조문 내용 미연결" in rendered
            and "이미지 미확보" in rendered
        )
        assert restored.image(revision, 0)[0] == restored.image(revision, 1)[0] == GIF
        assert Accounts(restored_db).session_user(token) == users
        restored_queue = Queue(restored_db)
        assert (
            restored_queue.submit("verify-after-restore", "reader:" + revision).job_id
            == pending.job_id
        )
        assert Worker(restored_queue, restored.records).run_once()
        assert restored_queue.get(pending.job_id).status == "SUCCEEDED"
        assert queue.get(pending.job_id).status == "QUEUED"
        assert restored_queue.get(image.job_id).status == "SUCCEEDED"
        from importlib import import_module

        from fastapi.testclient import TestClient

        from klegal_gold.config import Settings
        from klegal_gold.web.auth import accounts
        from klegal_gold.web.reader import reader_store

        web = import_module("klegal_gold.web.app")
        settings = Settings(data_dir=restored_files, database_url=target_dsn)
        monkeypatch.setattr(web, "load_settings", lambda: settings)
        monkeypatch.setattr(web.Database, "from_settings", lambda settings: restored_db)
        app = web.create_app()
        app.dependency_overrides[accounts] = lambda: Accounts(restored_db)
        app.dependency_overrides[reader_store] = lambda: restored
        with TestClient(app) as client:
            prefix = "/api/reader/" + revision
            assert client.get("/api/cases/search?q=복원").status_code == 401
            assert (
                client.post(
                    "/api/auth/login",
                    headers={"origin": settings.web_origin},
                    json={"username": "restore-fixture", "password": password},
                ).status_code
                == 200
            )
            response = client.get("/api/cases/search?q=복원")
            assert response.status_code == 200
            assert revision in response.text
            assert client.get(prefix + "/html").text == rendered
            assert client.get(prefix + "/images/0").content == GIF
            assert client.get(prefix + "/images/1").content == GIF
            assert client.get(prefix + "/images/2").status_code == 404
            assert (
                client.post("/api/auth/logout", headers={"origin": settings.web_origin}).status_code
                == 200
            )
            assert client.get(prefix + "/html").status_code == 401
            assert client.get(prefix + "/images/0").status_code == 401

        # Corrupt a COPY, never the source or completed bundle.
        digest = sha256(GIF).hexdigest()
        restored.records.store.path(f"blobs/{digest[:2]}/{digest}").write_bytes(b"corrupt")
        with pytest.raises(ValueError):
            restored.image(revision, 0)
        assert reader.image(revision, 0)[0] == GIF
        assert verify_backup(bundle) == manifest
    finally:
        if created:
            assert re.fullmatch(r"korcounsel_restore_[0-9a-f]{32}", target_name)
            with psycopg.connect(os.environ["KLEGAL_TEST_DATABASE_URL"], autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target_name)))


@pytest.mark.parametrize("failure", ["missing_blob", "corrupt_blob", "dump_failed"])
def test_incomplete_backup_has_no_completion_manifest(db, tmp_path, failure):
    records = Records(db, FileStore(tmp_path / "source"))
    blob = records.put_artifact("a", b"original", origin="DERIVED", metadata={})
    path = records.store.path(blob.storage_key)
    if failure == "missing_blob":
        path.unlink()
    if failure == "corrupt_blob":
        path.write_bytes(b"corrupt")

    def dump(snapshot, output):
        output.write_bytes(b"PGDMPpartial")
        raise OSError("synthetic failed dump")

    target = tmp_path / "backup"
    with pytest.raises((OSError, ValueError)):
        create_backup(db, records.store, target, dump)
    assert not (target / "manifest.json").exists()
    with pytest.raises(FileExistsError):
        create_backup(db, records.store, target, dump)


@pytest.mark.parametrize("damage", ["dump", "blob", "symlink"])
def test_backup_verification_rejects_damage(db, tmp_path, damage):
    records = Records(db, FileStore(tmp_path / "source"))
    blob = records.put_artifact("a", b"original", origin="DERIVED", metadata={})
    target = tmp_path / "backup"
    # Synthetic dump bytes test integrity only; the real pg_restore test is above.
    create_backup(
        db, records.store, target, lambda snapshot, path: path.write_bytes(b"PGDMPfixture")
    )
    assert verify_backup(target)["blobs"][0]["sha256"] == blob.sha256
    if damage == "dump":
        (target / "database.dump").write_bytes(b"PGDMPchanged")
    else:
        path = target / "files" / blob.storage_key
        if damage == "blob":
            path.write_bytes(b"changed")
        else:
            path.unlink()
            path.symlink_to(records.store.path(blob.storage_key))
    with pytest.raises(ValueError):
        verify_backup(target)
