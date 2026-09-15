"""Report every durable descendant, independently of the detail job outcome."""

from typing import Any
from uuid import UUID

from klegal_gold.jobs.queue import Queue

LINKS = (
    "image_job_id",
    "reader_refresh_job_id",
    "lawgo_job_id",
    "follow_up_job_id",
    "fields_job_id",
)


def ingestion_status(queue: Queue, job_id: UUID) -> dict[str, Any]:
    root = queue.get(job_id)
    stages = []
    pending = [root]
    seen = set()
    attention = False
    active = False
    fields_state = "NOT_PROCESSED"
    reader_id = root.checkpoint.get("reader_document_id")
    while pending:
        job = pending.pop(0)
        if job.job_id in seen:
            continue
        seen.add(job.job_id)
        if len(seen) > 20:
            raise ValueError("INGESTION_CHAIN_TOO_LONG")
        active |= job.status in {"QUEUED", "RUNNING"}
        attention |= job.status == "FAILED"
        if job.checkpoint.get("reader_document_id"):
            reader_id = job.checkpoint["reader_document_id"]
        stages.append(
            {
                "job_id": str(job.job_id),
                "kind": job.kind,
                "status": job.status,
                "checkpoint": job.checkpoint,
            }
        )
        if job.kind == "BUILD_CASE_FIELDS":
            fields_state = job.checkpoint.get("fields_state", "NOT_PROCESSED")
            attention |= fields_state in {"INCOMPLETE", "REVIEW"}
        if (
            not pending
            and not any(stage["kind"] == "BUILD_CASE_FIELDS" for stage in stages)
            and reader_id
        ):
            with queue.db.connect() as conn:
                extra = conn.execute(
                    "SELECT job_id FROM jobs WHERE kind='BUILD_CASE_FIELDS' "
                    "AND payload->>'document_id'=%s ORDER BY created_at DESC LIMIT 1",
                    (reader_id,),
                ).fetchone()
            if extra:
                pending.append(queue.get(extra["job_id"]))
        for key in LINKS:
            if job.checkpoint.get(key):
                pending.append(queue.get(UUID(job.checkpoint[key])))
    if root.status == "SUCCEEDED" and (
        not root.checkpoint.get("reader_document_id")
        or not root.checkpoint.get("lawgo_job_id")
        or (not active and fields_state == "NOT_PROCESSED")
    ):
        attention = True
    return {
        "job_id": str(root.job_id),
        "source_id": root.payload["source_id"],
        "reader_document_id": reader_id,
        "stages": stages,
        "fields_state": fields_state,
        "state": "NEEDS_ATTENTION" if attention else "PROCESSING" if active else "FINISHED",
    }
