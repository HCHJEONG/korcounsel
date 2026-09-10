import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from klegal_gold.db.accounts import Accounts
from klegal_gold.db.ledger import Ledger
from klegal_gold.db.migrate import MIGRATIONS, migrate
from klegal_gold.db.records import Records
from klegal_gold.db.registry import Registry
from klegal_gold.domain.identity import (
    CanonicalCaseIdentity,
    IdentityLinkEvent,
    SourceCaseIdentifier,
)
from klegal_gold.domain.legacy import LegacyCaseRecord
from klegal_gold.ingestion.legacy import map_legacy_row, row_from_metadata_projection
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def records(db, tmp_path):
    return Records(db, FileStore(tmp_path))


def identity(name="scourt:1", source_id="1", revision=1):
    return CanonicalCaseIdentity(
        canonical_id=name,
        link_revision=revision,
        metadata={},
        court_case_keys=[{"court": "대법원", "case_number": "2008재도11"}],
        source_identifiers=[{"source": "scourt", "source_id": source_id}],
    )


def event(result, previous=(), operation="CREATE"):
    return IdentityLinkEvent(
        event_id=uuid4(),
        operation=operation,
        previous=previous,
        resulting=result,
        recorded_at=datetime.now(UTC),
        actor="synthetic-test",
        reason="contract regression",
    )


def test_migrations_upgrade_reapply_and_checksum(empty_db, tmp_path):
    assert migrate(empty_db, target=1) == ["0001_records.sql"]
    with empty_db.connect() as conn:
        conn.execute("INSERT INTO case_keys(court,case_number) VALUES('test','1')")
    assert migrate(empty_db) == [
        "0002_jobs.sql",
        "0003_processing_integrity.sql",
        "0004_job_inputs.sql",
        "0005_source_jobs.sql",
        "0006_inventory_jobs.sql",
        "0007_decision_keys.sql",
        "0008_legacy_import.sql",
    ]
    assert migrate(empty_db) == []
    with empty_db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM case_keys").fetchone()["n"] == 1
    for file in MIGRATIONS.glob("*.sql"):
        shutil.copy(file, tmp_path)
    path = tmp_path / "0001_records.sql"
    path.write_text(path.read_text() + "\n-- changed applied version")
    with pytest.raises(ValueError, match="APPLIED_MIGRATION_CHANGED"):
        migrate(empty_db, tmp_path)
    with pytest.raises(ValueError, match="DOWNGRADE"):
        migrate(empty_db, target=1)


def test_migration_failure_rolls_back_whole_batch(empty_db, tmp_path):
    (tmp_path / "0001_bad.sql").write_text("CREATE TABLE rollback_probe(id int); SELECT 1/0;")
    with pytest.raises(psycopg.Error):
        migrate(empty_db, tmp_path)
    with empty_db.connect() as conn:
        assert conn.execute("SELECT to_regclass('rollback_probe') AS t").fetchone()["t"] is None
    assert len(migrate(empty_db)) == 8


def test_concurrent_migration(empty_db):
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: migrate(empty_db), range(2)))
    assert sorted(map(len, results)) == [0, 8]


def test_artifacts_idempotent_immutable_and_db_rollback(db, tmp_path):
    repo = records(db, tmp_path)
    blob = repo.put_artifact("a", b"original", origin="LEGACY_ARCHIVE", metadata={})
    assert repo.put_artifact("a", b"original", origin="LEGACY_ARCHIVE", metadata={}) == blob
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT"):
        repo.put_artifact("a", b"changed", origin="LEGACY_ARCHIVE", metadata={})
    assert repo.read("a") == b"original"
    # File install succeeds; invalid parent rolls the DB transaction back.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repo.put_artifact("b", b"recoverable", origin="DERIVED", metadata={}, parent_id="missing")
    assert len(list(tmp_path.glob("blobs/*/*"))) == 3
    repo.put_artifact("b", b"recoverable", origin="DERIVED", metadata={}, parent_id="a")
    assert repo.read("b") == b"recoverable"
    with pytest.raises(psycopg.Error, match="IMMUTABLE_HISTORY"):
        with db.connect() as conn:
            conn.execute("DELETE FROM artifacts WHERE artifact_id='a'")
    repo.store.path(blob.storage_key).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="INTEGRITY"):
        repo.read("a")


def test_legacy_samples_save_load_rebuild_without_auto_registry(db, tmp_path):
    repo = records(db, tmp_path)
    fixture = Path(__file__).parents[1] / "fixtures/legacy/bootstrap-metadata.json"
    samples = json.loads(fixture.read_text())["rows"]
    for value in samples:
        model = map_legacy_row(row_from_metadata_projection(value), imported_at=datetime.now(UTC))
        artifact_id = repo.save_legacy(model, run_id="first")
        again = map_legacy_row(model.original, imported_at=datetime.now(UTC))
        assert repo.save_legacy(again, run_id="second") == artifact_id
        restored = LegacyCaseRecord.model_validate_json(repo.read(artifact_id))
        assert restored == model
        assert restored.provenance.historical_raw_content_hash is None
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_records").fetchone()["n"] == 15
        assert (
            conn.execute("SELECT count(*) AS n FROM legacy_import_attempts").fetchone()["n"] == 30
        )
        assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 0
        conn.execute("DELETE FROM case_projection")
    assert repo.rebuild_projection() == 15
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM case_projection").fetchone()["n"] == 15
        assert (
            conn.execute("SELECT count(*) AS n FROM legacy_import_attempts").fetchone()["n"] == 30
        )


def test_registry_same_case_multiple_documents_and_stale_revision(db):
    registry = Registry(db)
    a, b = identity(), identity("scourt:2", "2")
    create = event([a, b])
    registry.apply(create)
    registry.apply(create)
    assert registry.get(a.canonical_id) == a
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM case_keys").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 2
    newer = identity(revision=2)
    registry.apply(event([newer], [a], "RELINK"))
    assert registry.get(a.canonical_id, 1) == a
    with pytest.raises(ValueError, match="STALE"):
        registry.apply(event([newer], [a], "RELINK"))


def test_registry_source_unique_and_atomic_rollback(db):
    registry = Registry(db)
    registry.apply(event([identity()]))
    with pytest.raises(psycopg.errors.UniqueViolation):
        registry.apply(event([identity("other", "1")]))
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM documents").fetchone()["n"] == 1
        assert conn.execute("SELECT count(*) AS n FROM identity_events").fetchone()["n"] == 1


def test_registry_merge_split_and_snapshot_restore(db, empty_db):
    # db and empty_db are the same fixture; restore to a second generated schema via SQL.
    from psycopg import sql

    from klegal_gold.db.session import Database

    registry = Registry(db)
    a, b = identity(), identity("scourt:2", "2")
    registry.apply(event([a, b]))
    merged = CanonicalCaseIdentity.model_validate(
        a.model_dump()
        | {
            "link_revision": 2,
            "source_identifiers": [*a.source_identifiers, *b.source_identifiers],
        }
    )
    registry.apply(event([merged], [a, b], "MERGE"))
    split_a = identity(revision=3)
    split_b = identity("split:2", "2")
    registry.apply(event([split_a, split_b], [merged], "SPLIT"))
    snapshot = registry.snapshot()
    other_schema = db.schema + "_restore"
    with db.connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(other_schema)))
    try:
        other = Database(db._dsn, schema=other_schema)
        migrate(other)
        Registry(other).restore(snapshot)
        Registry(other).restore(snapshot)
        assert Registry(other).snapshot() == snapshot
        assert Registry(other).get(a.canonical_id, 1) == a
        assert Registry(other).get("split:2") == split_b
    finally:
        with db.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(other_schema)))


def test_accounts_store_only_hashes_and_expire_revoke(db):
    accounts = Accounts(db)
    password = "synthetic-password-for-test"
    user = accounts.create("synthetic-user", password)
    assert accounts.issue_session("synthetic-user", "wrong") is None
    token = accounts.issue_session("synthetic-user", password)
    assert token and accounts.session_user(token) == user
    with db.connect() as conn:
        row = conn.execute("SELECT password_hash FROM app_users").fetchone()
        assert password not in row["password_hash"]
        assert conn.execute("SELECT token_hash FROM app_sessions").fetchone()["token_hash"] != token
        conn.execute("UPDATE app_sessions SET expires_at=clock_timestamp()-interval '1 second'")
    assert accounts.session_user(token) is None
    token = accounts.issue_session("synthetic-user", password)
    accounts.revoke(token)
    assert accounts.session_user(token) is None


def test_item_ledger_versioning_and_failure_history(db, tmp_path):
    repo = records(db, tmp_path)
    repo.put_artifact("result", b"x", origin="DERIVED", metadata={})
    ledger = Ledger(db, repo)
    source = SourceCaseIdentifier(source="scourt", source_id="1")
    key = ledger.register("ENRICHMENT", source, "input1", "rules1", "provided-link")
    assert key == ledger.register("ENRICHMENT", source, "input1", "rules1", "provided-link")
    assert key != ledger.register("ENRICHMENT", source, "input2", "rules1", "provided-link")
    failed = uuid4()
    ledger.record_attempt(key, failed, "FAILED", error_code="SOURCE_TIMEOUT")
    ledger.record_attempt(key, failed, "FAILED", error_code="SOURCE_TIMEOUT")
    ledger.record_attempt(key, uuid4(), "SUCCEEDED", artifact_id="result")
    with pytest.raises(ValueError, match="CONFLICT"):
        ledger.record_attempt(key, failed, "PARTIAL")
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM work_item_attempts").fetchone()["n"] == 2


def raw_model(raw, artifact_id, at):
    from klegal_gold.domain.cases import RawLegalCase
    from klegal_gold.domain.common import content_hash

    digest = content_hash(raw)
    version = {
        "identifier": {"source": "scourt", "source_id": "synthetic-1"},
        "raw_content_hash": digest,
    }
    return RawLegalCase(
        source_version=version,
        raw_artifact={
            "artifact_id": artifact_id,
            "source_version": version,
            "artifact_type": "HTML",
            "representation": "RESPONSE_BYTES",
            "source_url": "https://example.org/synthetic",
            "retrieved_at": at,
            "mime_type": "text/html",
            "sha256": digest,
            "file_size": len(raw),
            "storage_path": f"blobs/{digest[:2]}/{digest}",
        },
        provenance={
            "source_version": version,
            "raw_artifact_id": artifact_id,
            "source_url": "https://example.org/synthetic",
            "retrieved_at": at,
            "decoder_version": "utf8-1",
            "text_extractor_version": "test-1",
            "parser_version": "test-1",
            "normalizer_version": "test-1",
            "dataset_version": "synthetic",
            "run_id": str(uuid4()),
        },
    )


def test_raw_versions_reuse_bytes_but_preserve_acquisition_receipts(db, tmp_path):
    from datetime import timedelta

    from klegal_gold.domain.cases import RawLegalCase

    repo = records(db, tmp_path)
    raw = b"<p>unchanged</p>"
    now = datetime.now(UTC)
    first = raw_model(raw, "raw-1", now)
    second = raw_model(raw, "raw-1", now + timedelta(days=1))
    a = repo.save_raw(first, raw, receipt_id=uuid4())
    b = repo.save_raw(second, raw, receipt_id=uuid4())
    assert RawLegalCase.model_validate_json(repo.read(a)) == first
    assert RawLegalCase.model_validate_json(repo.read(b)) == second
    changed = b"<p>changed</p>"
    repo.save_raw(raw_model(changed, "raw-2", now), changed, receipt_id=uuid4())
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_versions").fetchone()["n"] == 2
        assert conn.execute("SELECT count(*) AS n FROM source_receipts").fetchone()["n"] == 3
    with pytest.raises(ValueError, match="RAW_BYTES_MISMATCH"):
        repo.save_raw(first, b"wrong", receipt_id=uuid4())


def test_missing_reused_legacy_artifact_does_not_record_success(db, tmp_path):
    fixture = Path(__file__).parents[1] / "fixtures/legacy/bootstrap-metadata.json"
    sample = json.loads(fixture.read_text())["rows"][0]
    model = map_legacy_row(row_from_metadata_projection(sample), imported_at=datetime.now(UTC))
    repo = records(db, tmp_path)
    artifact = repo.save_legacy(model, run_id="first")
    repo.store.path(repo.blob(artifact).storage_key).unlink()
    with pytest.raises(FileNotFoundError):
        repo.save_legacy(model, run_id="second")
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM legacy_import_attempts").fetchone()["n"] == 1


def test_registry_restore_rejects_unrelated_history(db):
    registry = Registry(db)
    registry.apply(event([identity()]))
    with pytest.raises(ValueError, match="RESTORE_PREFIX"):
        registry.restore({"format": "registry-events-1", "events": []})


def test_inventory_and_manifest_conflicts_are_immutable(db, tmp_path):
    from klegal_gold.domain.inventory import InventorySnapshot

    repo = records(db, tmp_path)
    at = datetime.now(UTC)
    snapshot = InventorySnapshot(
        snapshot_id="test-inventory",
        source="scourt",
        retrieved_at=at,
        started_at=at,
        finished_at=at,
        total_count=0,
        entries=[],
        observed_unique_count=0,
        metadata_hash="a" * 64,
        scope="sample",
        scope_hash="b" * 64,
        collector_version="test",
        hash_rules_version="test",
        completeness="PARTIAL",
    )
    artifact = repo.save_inventory(snapshot)
    assert InventorySnapshot.model_validate_json(repo.read(artifact)) == snapshot
    assert repo.save_inventory(snapshot) == artifact
    manifest = repo.save_manifest("r1", "REGISTRY", Registry(db).snapshot())
    assert json.loads(repo.read(manifest))["events"] == []
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT"):
        repo.save_manifest("r1", "REGISTRY", {"different": "payload"})
