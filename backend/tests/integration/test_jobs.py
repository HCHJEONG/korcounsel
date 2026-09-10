import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from klegal_gold.db.records import Records
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


@pytest.fixture
def services(db, tmp_path):
    repo = Records(db, FileStore(tmp_path))
    repo.put_artifact("a", b"synthetic original" * 100, origin="LEGACY_ARCHIVE", metadata={})
    return Queue(db, lease_seconds=5), repo


def expire(db):
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET lease_until=clock_timestamp()-interval '1 second'"
            " WHERE status='RUNNING'"
        )


def ready(db):
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET available_at=clock_timestamp() WHERE status='QUEUED'")


def test_duplicate_submit_and_concurrent_single_claim(db, services):
    queue, _ = services
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: queue.submit("request", "a"), range(4)))
    assert len({j.job_id for j in jobs}) == 1
    queue.submit("other", "a")
    with ThreadPoolExecutor(4) as pool:
        claims = list(pool.map(lambda i: queue.claim(str(i)), range(4)))
    assert sum(j is not None for j in claims) == 1
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_CONFLICT"):
        queue.submit("request", "other-artifact")
    claim = next(j for j in claims if j)
    queue.finish(claim, outcome="SUCCEEDED")
    assert queue.claim("next") is not None


def test_lease_expiry_fences_old_worker_and_keeps_checkpoint(db, services):
    queue, _ = services
    queued = queue.submit("r", "a")
    old = queue.claim("old")
    queue.heartbeat(old, {"page": 2})
    expire(db)
    new = queue.claim("new")
    assert new.job_id == queued.job_id
    assert new.lease_token != old.lease_token
    assert new.checkpoint == {"page": 2}
    with pytest.raises(ValueError, match="LEASE_LOST"):
        queue.heartbeat(old, {"page": 1})
    with pytest.raises(ValueError, match="LEASE_LOST"):
        queue.finish(old, outcome="SUCCEEDED")
    queue.finish(new, outcome="SUCCEEDED")
    with db.connect() as conn:
        assert [
            r["outcome"] for r in conn.execute("SELECT outcome FROM job_attempts ORDER BY attempt")
        ] == ["LEASE_EXPIRED", "SUCCEEDED"]


def test_failure_retry_exhaustion_and_terminal_no_claim(db, services):
    queue, _ = services
    queued = queue.submit("r", "a", max_attempts=2)
    first = queue.claim("w")
    queue.finish(first, outcome="FAILED", error_code="HANDLER_FAILED")
    assert queue.get(queued.job_id).status == "QUEUED"
    assert queue.claim("w") is None
    ready(db)
    second = queue.claim("w")
    queue.finish(second, outcome="FAILED", error_code="HANDLER_FAILED")
    assert queue.get(queued.job_id).status == "FAILED"
    assert queue.claim("w") is None
    with pytest.raises(ValueError, match="LEASE_LOST"):
        queue.finish(second, outcome="SUCCEEDED")


def test_expired_last_attempt_fails_even_during_drain(db, services):
    queue, _ = services
    job = queue.submit("r", "a", max_attempts=1)
    queue.claim("w")
    queue.set_draining(True)
    expire(db)
    assert queue.drain_status() == {"draining": True, "running": 0, "ready_to_stop": True}
    assert queue.get(job.job_id).status == "FAILED"


def test_drain_blocks_new_work_but_lost_response_can_be_queried(services):
    queue, _ = services
    job = queue.submit("r", "a")
    queue.set_draining(True)
    assert queue.submit("r", "a").job_id == job.job_id
    assert queue.claim("w") is None
    with pytest.raises(ValueError, match="RUNTIME_DRAINING"):
        queue.submit("new", "a")
    queue.set_draining(False)
    assert queue.claim("w") is not None
    queue.set_draining(True)
    assert queue.drain_status()["ready_to_stop"] is False


def test_drain_and_claim_race_has_serial_order(services):
    queue, _ = services
    queue.submit("r", "a")
    barrier = Barrier(2)

    def claim():
        barrier.wait()
        return queue.claim("w")

    def drain():
        barrier.wait()
        queue.set_draining(True)

    with ThreadPoolExecutor(2) as pool:
        claim_future = pool.submit(claim)
        drain_future = pool.submit(drain)
        result = claim_future.result()
        drain_future.result()
    status = queue.drain_status()
    assert status["draining"]
    assert status["running"] == int(result is not None)
    assert queue.claim("second") is None


def test_checkpoint_does_not_consume_failure_budget(db, services):
    queue, _ = services
    job = queue.submit("r", "a", max_attempts=1)
    for _ in range(3):
        claim = queue.claim("w")
        queue.heartbeat(claim, {"part": 3})
        queue.finish(claim, outcome="CHECKPOINTED")
    final = queue.claim("w")
    queue.finish(final, outcome="SUCCEEDED")
    assert queue.get(job.job_id).attempts == 4


def test_real_worker_verifies_blob_and_detects_corruption(db, services):
    queue, repo = services
    worker = Worker(queue, repo)
    job = queue.submit("valid", "a")
    assert worker.run_once()
    assert queue.get(job.job_id).status == "SUCCEEDED"
    assert queue.get(job.job_id).checkpoint["verified_hash"] == repo.blob("a").sha256
    repo.store.path(repo.blob("a").storage_key).write_bytes(b"corrupt")
    failed = queue.submit("corrupt", "a", max_attempts=1)
    assert worker.run_once()
    assert queue.get(failed.job_id).status == "FAILED"


def _claim_then_wait(db, connection):
    queue = Queue(db, lease_seconds=5)
    job = queue.claim("terminated-process")
    queue.heartbeat(job, {"durable_checkpoint": 7})
    connection.send(str(job.job_id))
    connection.recv()


def test_real_process_termination_recovered_with_fresh_owner(db, services):
    queue, _ = services
    job = queue.submit("process-crash", "a")
    context = multiprocessing.get_context("fork")
    parent, child = context.Pipe()
    process = context.Process(target=_claim_then_wait, args=(db, child))
    process.start()
    try:
        assert parent.poll(10)
        assert parent.recv() == str(job.job_id)
        old = queue.get(job.job_id)
        process.terminate()
        process.join(5)
        assert not process.is_alive()
        expire(
            db
        )  # Advance DB lease for deterministic fault injection; no production timeout change.
        fresh = queue.claim("replacement")
        assert fresh.checkpoint == {"durable_checkpoint": 7}
        with pytest.raises(ValueError, match="LEASE_LOST"):
            queue.finish(old, outcome="SUCCEEDED")
        queue.finish(fresh, outcome="SUCCEEDED")
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        parent.close()
        child.close()


def test_worker_checkpoint_on_drain_observed_between_chunks(services, monkeypatch):
    queue, repo = services
    job = queue.submit("drain-during-work", "a")
    real_verify = repo.store.verify

    def verify(blob, progress=None):
        if progress is not None:
            queue.set_draining(True)
        return real_verify(blob, progress)

    monkeypatch.setattr(repo.store, "verify", verify)
    worker = Worker(queue, repo)
    assert worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    assert queue.drain_status()["ready_to_stop"]
    queue.set_draining(False)
    monkeypatch.setattr(repo.store, "verify", real_verify)
    assert worker.run_once()
    assert queue.get(job.job_id).status == "SUCCEEDED"


def test_drain_caps_long_lease_and_finished_attempts_are_immutable(db, services):
    import psycopg

    queue, _ = services
    queue = Queue(db, lease_seconds=3600)
    job = queue.submit("long", "a")
    claimed = queue.claim("w")
    queue.set_draining(True)
    queue.heartbeat(claimed)
    with db.connect() as conn:
        seconds = conn.execute(
            "SELECT extract(epoch FROM (lease_until-clock_timestamp())) AS n FROM jobs"
        ).fetchone()["n"]
        assert 0 < seconds <= 120
    queue.finish(claimed, outcome="SUCCEEDED")
    with pytest.raises(psycopg.Error, match="INVALID_JOB_TRANSITION"):
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET status='QUEUED' WHERE job_id=%s", (job.job_id,))
    with pytest.raises(psycopg.Error, match="IMMUTABLE_FINISHED_ATTEMPT"):
        with db.connect() as conn:
            conn.execute("UPDATE job_attempts SET outcome='FAILED'")


def _run_real_worker(queue, repo):
    Worker(queue, repo).run()


def test_daemon_heartbeat_and_sigterm_shutdown(services):
    import time

    queue, repo = services
    context = multiprocessing.get_context("fork")
    process = context.Process(target=_run_real_worker, args=(queue, repo))
    job = queue.submit("daemon", "a")
    process.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if queue.get(job.job_id).status == "SUCCEEDED" and queue.worker_available():
                break
            time.sleep(0.05)
        assert queue.get(job.job_id).status == "SUCCEEDED"
        assert queue.worker_available()
        process.terminate()
        process.join(5)
        assert process.exitcode == 0
        assert not queue.worker_available()
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)


def test_operator_cli_uses_shared_queue(services, monkeypatch):
    from typer.testing import CliRunner

    from klegal_gold.cli import app

    queue, repo = services
    monkeypatch.setattr("klegal_gold.operations._services", lambda: (queue.db, repo, queue))
    runner = CliRunner()
    submitted = runner.invoke(app, ["ops", "submit-verify", "cli-request", "a"])
    assert submitted.exit_code == 0, submitted.output
    assert runner.invoke(app, ["ops", "worker", "--once"]).exit_code == 0
    assert runner.invoke(app, ["ops", "drain"]).exit_code == 0
    blocked = runner.invoke(app, ["ops", "submit-verify", "another", "a"])
    assert blocked.exit_code == 1
    assert "postgresql://" not in blocked.output
    assert runner.invoke(app, ["ops", "resume"]).exit_code == 0


def test_projection_rebuild_is_queued_and_resumes_after_drain(db, services, monkeypatch):
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from klegal_gold.ingestion.legacy import map_legacy_row, row_from_metadata_projection

    queue, repo = services
    fixture = Path(__file__).parents[1] / "fixtures/legacy/bootstrap-metadata.json"
    for value in json.loads(fixture.read_text())["rows"][:3]:
        repo.save_legacy(
            map_legacy_row(row_from_metadata_projection(value), imported_at=datetime.now(UTC)),
            run_id="test",
        )
    with db.connect() as conn:
        conn.execute("DELETE FROM case_projection")
    job = queue.submit_rebuild("rebuild")
    assert queue.submit_rebuild("rebuild").job_id == job.job_id
    # A later import is outside this job's immutable input snapshot.
    later = json.loads(fixture.read_text())["rows"][3]
    repo.save_legacy(
        map_legacy_row(row_from_metadata_projection(later), imported_at=datetime.now(UTC)),
        run_id="later",
    )
    with db.connect() as conn:
        conn.execute("DELETE FROM case_projection")
        assert (
            conn.execute("SELECT count(*) AS n FROM projection_rebuild_inputs").fetchone()["n"] == 3
        )
    real_heartbeat = queue.heartbeat

    def heartbeat(claim, checkpoint=None):
        real_heartbeat(claim, checkpoint)
        if checkpoint and "last_artifact" in checkpoint:
            queue.set_draining(True)

    monkeypatch.setattr(queue, "heartbeat", heartbeat)
    worker = Worker(queue, repo)
    assert worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    assert queue.get(job.job_id).checkpoint["last_artifact"]
    with pytest.raises(ValueError, match="RUNTIME_DRAINING"):
        queue.submit_rebuild("blocked")
    queue.set_draining(False)
    monkeypatch.setattr(queue, "heartbeat", real_heartbeat)
    assert worker.run_once()
    assert queue.get(job.job_id).status == "SUCCEEDED"
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM case_projection").fetchone()["n"] == 3


def test_worker_health_expires_independently_from_api(db, services):
    queue, _ = services
    assert not queue.worker_available()
    queue.worker_heartbeat("test")
    assert queue.worker_available()
    with db.connect() as conn:
        conn.execute(
            "UPDATE worker_instances SET heartbeat_at=clock_timestamp()-interval '61 seconds'"
        )
    assert not queue.worker_available()
