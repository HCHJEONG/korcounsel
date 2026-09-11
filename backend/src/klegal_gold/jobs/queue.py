"""Single-worker queue with transactional admission and fenced lease ownership."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from klegal_gold.db.session import Connection, Database


@dataclass(frozen=True)
class Job:
    job_id: UUID
    kind: str
    handler_version: str
    payload: dict[str, Any]
    status: str
    attempts: int
    lease_token: UUID | None
    checkpoint: dict[str, Any]
    lease_until: datetime | None


def _job(row: dict[str, Any]) -> Job:
    return Job(**{name: row[name] for name in Job.__dataclass_fields__})


def _event(conn: Connection, job_id: UUID, event: str) -> None:
    conn.execute("INSERT INTO job_events(job_id,event) VALUES(%s,%s)", (job_id, event))


class Queue:
    def __init__(self, db: Database, *, lease_seconds: int = 60) -> None:
        if not 5 <= lease_seconds <= 3600:
            raise ValueError("INVALID_LEASE_SECONDS")
        self.db, self.lease_seconds = db, lease_seconds

    def submit(self, request_key: str, artifact_id: str, *, max_attempts: int = 3) -> Job:
        if not artifact_id.strip():
            raise ValueError("INVALID_JOB_REQUEST")
        return self._submit(
            request_key, "VERIFY_ARTIFACT", {"artifact_id": artifact_id}, max_attempts
        )

    def submit_law_detail(self, request_key: str, source_id: str) -> Job:
        from klegal_gold.sources.law_api import identifier

        return self._submit(
            request_key, "FETCH_LAW_DETAIL", {"source_id": identifier(source_id)}, 3
        )

    def submit_scourt_detail(self, request_key: str, source_id: str) -> Job:
        from klegal_gold.sources.law_api import identifier

        return self._submit(
            request_key, "FETCH_SCOURT_DETAIL", {"source_id": identifier(source_id)}, 3
        )

    def submit_scourt_inventory(
        self, request_key: str, *, query: str = "", max_pages: int = 2, display: int = 20
    ) -> Job:
        if (
            not isinstance(query, str)
            or len(query) > 200
            or type(max_pages) is not int
            or not 1 <= max_pages <= 10
            or type(display) is not int
            or not 1 <= display <= 100
        ):
            raise ValueError("INVALID_INVENTORY_REQUEST")
        return self._submit(
            request_key,
            "FETCH_SCOURT_INVENTORY",
            {
                "query": query,
                "max_pages": max_pages,
                "display": display,
            },
            3,
        )

    def submit_legacy_import(self, request_key: str, manifest_hash: str) -> Job:
        from pydantic import TypeAdapter

        from klegal_gold.domain.common import Digest

        TypeAdapter(Digest).validate_python(manifest_hash)
        return self._submit(
            request_key, "IMPORT_LEGACY_BUNDLE", {"manifest_hash": manifest_hash}, 3
        )

    def submit_image_batch(
        self,
        request_key: str,
        manifest_artifact_id: str,
        *,
        max_urls: int = 50,
        max_total_bytes: int = 512 * 1024 * 1024,
    ) -> Job:
        if (
            not manifest_artifact_id.strip()
            or type(max_urls) is not int
            or not 1 <= max_urls <= 500
            or type(max_total_bytes) is not int
            or not 1 <= max_total_bytes <= 5 * 1024 * 1024 * 1024
        ):
            raise ValueError("INVALID_IMAGE_BATCH_REQUEST")
        return self._submit(
            request_key,
            "ACQUIRE_IMAGE_BATCH",
            {
                "manifest_artifact_id": manifest_artifact_id,
                "max_urls": max_urls,
                "max_total_bytes": max_total_bytes,
            },
            3,
        )

    def submit_rebuild(self, request_key: str, *, max_attempts: int = 3) -> Job:
        return self._submit(request_key, "REBUILD_PROJECTION", {}, max_attempts)

    def _submit(
        self, request_key: str, kind: str, payload: dict[str, Any], max_attempts: int
    ) -> Job:
        if not request_key.strip() or not 1 <= max_attempts <= 10:
            raise ValueError("INVALID_JOB_REQUEST")
        with self.db.connect() as conn:
            control = conn.execute("SELECT draining FROM runtime_control FOR UPDATE").fetchone()
            if control is None:
                raise ValueError("DATABASE_NOT_MIGRATED")
            existing = conn.execute(
                "SELECT * FROM jobs WHERE request_key=%s", (request_key,)
            ).fetchone()
            if existing:
                if (
                    existing["payload"] != payload
                    or existing["max_attempts"] != max_attempts
                    or existing["kind"] != kind
                ):
                    raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
                return _job(existing)  # A lost response remains queryable during drain.
            if control["draining"]:
                raise ValueError("RUNTIME_DRAINING")
            artifact_payload_key = (
                "artifact_id" if kind == "VERIFY_ARTIFACT" else "manifest_artifact_id"
            )
            if (
                kind in {"VERIFY_ARTIFACT", "ACQUIRE_IMAGE_BATCH"}
                and not conn.execute(
                    "SELECT 1 FROM artifacts WHERE artifact_id=%s", (payload[artifact_payload_key],)
                ).fetchone()
            ):
                raise ValueError("ARTIFACT_NOT_FOUND")
            result = conn.execute(
                """INSERT INTO jobs(job_id,request_key,kind,payload,max_attempts,handler_version)
                   VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    uuid4(),
                    request_key,
                    kind,
                    Jsonb(payload),
                    max_attempts,
                    "legacy-import-1"
                    if kind == "IMPORT_LEGACY_BUNDLE"
                    else (
                        "asset-1"
                        if kind == "ACQUIRE_IMAGE_BATCH"
                        else ("source-1" if kind.startswith("FETCH_") else "persistence-1")
                    ),
                ),
            ).fetchone()
            assert result is not None
            if kind == "REBUILD_PROJECTION":
                conn.execute(
                    """INSERT INTO projection_rebuild_inputs(job_id,artifact_id,content_revision)
                       SELECT %s,artifact_id,content_revision FROM legacy_records""",
                    (result["job_id"],),
                )
            _event(conn, result["job_id"], "QUEUED")
            return _job(result)

    def _expire(self, conn: Connection) -> None:
        expired = conn.execute(
            "SELECT * FROM jobs WHERE status='RUNNING' AND lease_until<=clock_timestamp()"
            " FOR UPDATE"
        ).fetchall()
        for row in expired:
            conn.execute(
                """UPDATE job_attempts SET finished_at=clock_timestamp(),
                   outcome='LEASE_EXPIRED',error_code='LEASE_EXPIRED'
                   WHERE lease_token=%s AND finished_at IS NULL""",
                (row["lease_token"],),
            )
            conn.execute(
                """UPDATE jobs SET status=CASE WHEN failures+1>=max_attempts
                   THEN 'FAILED' ELSE 'QUEUED' END, failures=failures+1,
                   lease_token=NULL,lease_until=NULL,worker_id=NULL,error_code='LEASE_EXPIRED',
                   updated_at=clock_timestamp(),available_at=clock_timestamp()
                   WHERE job_id=%s""",
                (row["job_id"],),
            )
            _event(conn, row["job_id"], "LEASE_EXPIRED")

    def claim(self, worker_id: str) -> Job | None:
        if not worker_id.strip():
            raise ValueError("INVALID_WORKER_ID")
        with self.db.connect() as conn:
            control = conn.execute("SELECT draining FROM runtime_control FOR UPDATE").fetchone()
            if control is None:
                raise ValueError("DATABASE_NOT_MIGRATED")
            self._expire(conn)
            if (
                control["draining"]
                or conn.execute("SELECT 1 FROM jobs WHERE status='RUNNING'").fetchone()
            ):
                return None
            row = conn.execute(
                """SELECT * FROM jobs WHERE status='QUEUED' AND available_at<=clock_timestamp()
                   ORDER BY created_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            token = uuid4()
            result = conn.execute(
                """UPDATE jobs SET status='RUNNING',attempts=attempts+1,lease_token=%s,
                   worker_id=%s,lease_until=clock_timestamp()+%s*interval '1 second',
                   updated_at=clock_timestamp() WHERE job_id=%s RETURNING *""",
                (token, worker_id, self.lease_seconds, row["job_id"]),
            ).fetchone()
            assert result is not None
            conn.execute(
                """INSERT INTO job_attempts(job_id,attempt,lease_token,worker_id)
                   VALUES(%s,%s,%s,%s)""",
                (row["job_id"], result["attempts"], token, worker_id),
            )
            _event(conn, row["job_id"], "RUNNING")
            return _job(result)

    def heartbeat(self, job: Job, checkpoint: dict[str, Any] | None = None) -> None:
        if checkpoint is not None and len(json.dumps(checkpoint).encode()) > 65536:
            raise ValueError("CHECKPOINT_TOO_LARGE")
        with self.db.connect() as conn:
            row = conn.execute(
                """UPDATE jobs SET lease_until=LEAST(clock_timestamp()+%s*interval '1 second',
                   COALESCE((SELECT drain_started_at+interval '120 seconds'
                   FROM runtime_control), 'infinity'::timestamptz)),
                   checkpoint=COALESCE(%s,checkpoint),updated_at=clock_timestamp()
                   WHERE job_id=%s AND lease_token=%s AND status='RUNNING'
                     AND lease_until>clock_timestamp() RETURNING job_id""",
                (
                    self.lease_seconds,
                    Jsonb(checkpoint) if checkpoint is not None else None,
                    job.job_id,
                    job.lease_token,
                ),
            ).fetchone()
            if row is None:
                raise ValueError("LEASE_LOST")

    def finish(self, job: Job, *, outcome: str, error_code: str | None = None) -> None:
        if outcome not in {"SUCCEEDED", "FAILED", "CHECKPOINTED"}:
            raise ValueError("INVALID_JOB_OUTCOME")
        # Only stable codes; no exception messages, paths, DSNs, or source response content.
        if error_code not in {None, "ARTIFACT_INTEGRITY_FAILED", "HANDLER_FAILED"}:
            raise ValueError("INVALID_JOB_ERROR_CODE")
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT * FROM jobs WHERE job_id=%s AND lease_token=%s
                   AND status='RUNNING' AND lease_until>clock_timestamp() FOR UPDATE""",
                (job.job_id, job.lease_token),
            ).fetchone()
            if row is None:
                raise ValueError("LEASE_LOST")
            failures = row["failures"] + int(outcome == "FAILED")
            status = outcome
            if outcome == "CHECKPOINTED" or (
                outcome == "FAILED" and failures < row["max_attempts"]
            ):
                status = "QUEUED"
            delay = min(2**failures, 60) if outcome == "FAILED" else 0
            conn.execute(
                """UPDATE jobs SET status=%s,failures=%s,error_code=%s,
                   lease_token=NULL,lease_until=NULL,worker_id=NULL,
                   available_at=clock_timestamp()+%s*interval '1 second',
                   updated_at=clock_timestamp() WHERE job_id=%s""",
                (status, failures, error_code, delay, job.job_id),
            )
            conn.execute(
                """UPDATE job_attempts SET finished_at=clock_timestamp(),outcome=%s,error_code=%s
                   WHERE lease_token=%s AND finished_at IS NULL""",
                (outcome, error_code, job.lease_token),
            )
            _event(conn, job.job_id, outcome)

    def get(self, job_id: UUID) -> Job:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=%s", (job_id,)).fetchone()
        if row is None:
            raise ValueError("JOB_NOT_FOUND")
        return _job(row)

    def set_draining(self, draining: bool) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE runtime_control SET draining=%s,
                   drain_started_at=CASE WHEN %s THEN COALESCE(drain_started_at,clock_timestamp())
                   ELSE NULL END""",
                (draining, draining),
            )
            if draining:
                conn.execute(
                    """UPDATE jobs SET lease_until=LEAST(lease_until,
                       (SELECT drain_started_at+interval '120 seconds' FROM runtime_control))
                       WHERE status='RUNNING'"""
                )

    def drain_status(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            control = conn.execute("SELECT * FROM runtime_control FOR UPDATE").fetchone()
            assert control is not None
            self._expire(conn)
            running = conn.execute(
                "SELECT count(*) AS n FROM jobs WHERE status='RUNNING'"
            ).fetchone()
            assert running is not None
            return {
                "draining": control["draining"],
                "running": running["n"],
                "ready_to_stop": bool(control["draining"] and running["n"] == 0),
            }

    def worker_heartbeat(self, worker_id: str, *, stopped: bool = False) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO worker_instances(worker_id,stopped_at)
                   VALUES(%s,CASE WHEN %s THEN clock_timestamp() ELSE NULL END)
                   ON CONFLICT(worker_id) DO UPDATE SET heartbeat_at=clock_timestamp(),
                   stopped_at=EXCLUDED.stopped_at""",
                (worker_id, stopped),
            )

    def worker_available(self) -> bool:
        with self.db.connect() as conn:
            return (
                conn.execute(
                    """SELECT 1 FROM worker_instances WHERE stopped_at IS NULL
                   AND heartbeat_at>clock_timestamp()-interval '60 seconds' LIMIT 1"""
                ).fetchone()
                is not None
            )
