"""Report every durable descendant, independently of the detail job outcome."""

from typing import Any
from uuid import UUID

from klegal_gold.jobs.queue import Queue

LINKS = ("image_job_id", "reader_refresh_job_id", "lawgo_job_id", "follow_up_job_id")


def ingestion_status(queue: Queue, job_id: UUID) -> dict[str, Any]:
    root = queue.get(job_id)
    stages = []
    pending = [root]
    seen = set()
    attention = False
    active = False
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
        for key in LINKS:
            if job.checkpoint.get(key):
                pending.append(queue.get(UUID(job.checkpoint[key])))
    if root.status == "SUCCEEDED" and (
        not root.checkpoint.get("reader_document_id") or not root.checkpoint.get("lawgo_job_id")
    ):
        attention = True
    return {
        "job_id": str(root.job_id),
        "source_id": root.payload["source_id"],
        "reader_document_id": reader_id,
        "stages": stages,
        "state": "NEEDS_ATTENTION" if attention else "PROCESSING" if active else "FINISHED",
    }
