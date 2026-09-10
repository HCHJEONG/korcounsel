"""Explicit local Compose smoke; persists only clearly labelled synthetic data."""

import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.jobs.queue import Queue
from klegal_gold.storage.files import FileStore


def main() -> None:
    settings = load_settings()
    if settings.database_url is None:
        raise ValueError("LOCAL_DATABASE_REQUIRED")
    info = conninfo_to_dict(settings.database_url.get_secret_value())
    if info.get("host") not in {"postgres", "127.0.0.1", "localhost"} or info.get("dbname") not in {
        "korcounsel_dev",
        "korcounsel_test",
    }:
        raise ValueError("LOCAL_DEV_DATABASE_REQUIRED")
    db = Database.from_settings(settings)
    records = Records(db, FileStore(settings.data_dir))
    queue = Queue(db)
    artifact = "synthetic:step2a-compose-smoke-v1"
    blob = records.put_artifact(
        artifact,
        b"KorCounsel synthetic Step 2A smoke; not source corpus.",
        origin="DERIVED",
        metadata={"fixture_kind": "SYNTHETIC"},
    )
    was_draining = queue.drain_status()["draining"]
    if was_draining:
        raise ValueError("LOCAL_RUNTIME_ALREADY_DRAINING")
    request_key = "synthetic:step2a-compose-smoke:" + str(uuid4())
    job = queue.submit(request_key, artifact)
    duplicate = queue.submit(request_key, artifact)
    assert duplicate.job_id == job.job_id
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and queue.get(job.job_id).status not in {
        "SUCCEEDED",
        "FAILED",
    }:
        time.sleep(0.1)
    result = queue.get(job.job_id)
    assert result.status == "SUCCEEDED"
    assert result.checkpoint["verified_hash"] == blob.sha256
    try:
        queue.set_draining(True)
        assert queue.drain_status()["ready_to_stop"]
        try:
            queue.submit("synthetic:must-not-be-enqueued", artifact)
        except ValueError as exc:
            assert str(exc) == "RUNTIME_DRAINING"
        else:
            raise AssertionError("DRAIN_DID_NOT_BLOCK")
    finally:
        queue.set_draining(was_draining)
    with db.connect() as conn:
        migrations = [
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    print(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "scope": "LOCAL_COMPOSE_SYNTHETIC",
                "migrations": migrations,
                "job_id": str(result.job_id),
                "job_status": result.status,
                "attempts": result.attempts,
                "artifact_sha256": blob.sha256,
                "idempotent_submission": "PASS",
                "drain_admission": "PASS",
                "worker_heartbeat_current": queue.worker_available(),
                "not_performed": ["AWS changes", "legacy corpus import", "live source fetch"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
