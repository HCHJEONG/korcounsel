"""Immutable quality reports and bounded durable dispatch to existing stage jobs."""

import json
from collections import Counter
from typing import Any
from uuid import UUID

from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.fields.contract import VERSION as FIELD_VERSION
from klegal_gold.fields.store import FieldStore
from klegal_gold.jobs.queue import Job, Queue
from klegal_gold.quality.checks import CATEGORIES, VERSION, inspect


def latest(records: Records) -> dict[str, str]:
    # Same root/version ordering as ordinary search, frozen in one SQL statement.
    with records.db.connect() as conn:
        rows = conn.execute("""SELECT DISTINCT ON(a.metadata->>'source_id')
          a.metadata->>'source_id' AS source_id, a.artifact_id
          FROM artifacts a LEFT JOIN artifacts root ON root.artifact_id=
          'reader:' || (a.metadata->>'current_root_document_id')
          WHERE a.metadata->>'kind'='READER_DOCUMENT' AND a.metadata->>'origin'='CURRENT_SOURCE'
          ORDER BY a.metadata->>'source_id', COALESCE(root.created_at,a.created_at) DESC,
          a.created_at DESC,a.artifact_id DESC""").fetchall()
    return {r["source_id"]: r["artifact_id"].removeprefix("reader:") for r in rows}


def audit_one(records: Records, document: str) -> dict[str, Any]:
    reader = ReaderStore(records).read(document)
    fields = FieldStore(records).read(document)
    return {
        "document_id": document,
        **inspect(reader, fields, records.read(reader["html_artifact_id"]).decode()),
    }


def save(records: Records, key: str, value: Any) -> None:
    records.put_artifact(
        key,
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
        origin="MANIFEST",
        metadata={"kind": "QUALITY_REPORT"},
    )


def audit(worker: Any, job: Job) -> None:
    if job.payload["field_rule"] != FIELD_VERSION:
        raise ValueError("QUALITY_RULE_CHANGED")
    scope = json.loads(worker.records.read(job.payload["scope_artifact_id"]))
    rows = []
    for i, document in enumerate(scope["document_ids"]):
        key = f"quality:{job.job_id}:item:{i}"
        try:
            row = json.loads(worker.records.read(key))
        except ValueError as exc:
            if str(exc) != "ARTIFACT_NOT_FOUND":
                raise
            try:
                row = audit_one(worker.records, document)
            except (ValueError, KeyError, UnicodeError):
                row = {
                    "document_id": document,
                    "source_id": "",
                    "title": "reader 입력 확인 필요",
                    "field_state": "NOT_PROCESSED",
                    "counts": {"LOGIC_REQUIRED": 1},
                    "issues": [
                        {
                            "category": "LOGIC_REQUIRED",
                            "code": "AUDIT_INPUT_INVALID",
                            "location": "reader",
                            "detail": "저장 입력·근거 확인 필요",
                        }
                    ],
                }
            save(worker.records, key, row)
        rows.append(row)
        worker.queue.worker_heartbeat(worker.worker_id)
        worker.queue.heartbeat(job, {"checked": i + 1, "total": len(scope["document_ids"])})
        if worker.stop.is_set() or worker.queue.drain_status()["draining"]:
            from klegal_gold.jobs.worker import CheckpointRequested

            raise CheckpointRequested
    summary = {
        c: {
            "cases": sum(bool(r["counts"].get(c)) for r in rows),
            "locations": sum(r["counts"].get(c, 0) for r in rows),
        }
        for c in CATEGORIES
    }
    key = f"quality:{job.job_id}:report"
    save(
        worker.records,
        key,
        {
            "version": VERSION,
            "field_rule": FIELD_VERSION,
            "scope": scope,
            "summary": summary,
            "count": len(rows),
            "items": rows,
            "field_states": dict(Counter(r["field_state"] for r in rows)),
        },
    )
    worker.queue.heartbeat(
        job, {"checked": len(rows), "total": len(rows), "report_artifact_id": key}
    )


def dispatch(worker: Any, job: Job) -> None:
    if job.payload["field_rule"] != FIELD_VERSION:
        raise ValueError("QUALITY_RULE_CHANGED")
    results = dict(job.checkpoint.get("results", {}))
    current = latest(worker.records)
    for document in job.payload["document_ids"]:
        if document in results:
            continue
        key = f"quality-action:{job.job_id}:{document}"
        # Recover a child registered immediately before a crash; never skip that child as busy.
        with worker.queue.db.connect() as conn:
            existing = conn.execute(
                "SELECT job_id FROM jobs WHERE request_key=%s", (key,)
            ).fetchone()
        if existing:
            child = worker.queue.get(existing["job_id"])
        else:
            try:
                row = audit_one(worker.records, document)
            except (ValueError, KeyError, UnicodeError):
                results[document] = {"state": "SKIPPED", "reason": "INPUT_INVALID"}
                worker.queue.heartbeat(job, {"results": results})
                continue
            action = job.payload["action"]
            eligible = action == "FIELDS" or any(
                x["category"] == "RETRYABLE"
                and x["location"].startswith(
                    "statute:" if action == "LAWGO_TRANSIENT" else ("image:", "statute_image:")
                )
                for x in row["issues"]
            )
            with worker.queue.db.connect() as conn:
                busy = conn.execute(
                    "SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING') "
                    "AND (payload->>'source_id'=%s OR payload->>'document_id' IN "
                    "(SELECT replace(artifact_id,'reader:','') FROM artifacts "
                    "WHERE metadata->>'kind'='READER_DOCUMENT' AND metadata->>'source_id'=%s))",
                    (row["source_id"], row["source_id"]),
                ).fetchone()
            if current.get(row["source_id"]) != document or busy or not eligible:
                results[document] = {
                    "state": "SKIPPED",
                    "reason": "STALE"
                    if current.get(row["source_id"]) != document
                    else "BUSY"
                    if busy
                    else "NO_RETRYABLE_FAILURE",
                }
                worker.queue.heartbeat(job, {"results": results})
                continue
            if action == "FIELDS":
                child = worker.queue.submit_case_fields(document, request_key=key)
            elif action == "IMAGES_TRANSIENT":
                child = worker.queue._submit(
                    key,
                    "RETRY_CURRENT_IMAGES",
                    {"document_id": document, "transient_only": True},
                    3,
                )
            else:
                reader = worker.readers.read(document)
                root_job_id = reader["provenance"].get("job_id")
                if not root_job_id:
                    results[document] = {"state": "SKIPPED", "reason": "DEPENDENCY_MISSING"}
                    worker.queue.heartbeat(job, {"results": results})
                    continue
                try:
                    parent = worker.queue.get(UUID(root_job_id))
                except ValueError:
                    results[document] = {"state": "SKIPPED", "reason": "DEPENDENCY_MISSING"}
                    worker.queue.heartbeat(job, {"results": results})
                    continue
                dependency = parent.checkpoint.get("reader_refresh_job_id", str(parent.job_id))
                child = worker.queue._submit(
                    key,
                    "ENRICH_CURRENT_LAWGO",
                    {"document_id": document, "dependency_id": dependency, "transient_only": True},
                    3,
                )
        if child.kind == "ENRICH_CURRENT_LAWGO":
            fields = worker.queue.submit_case_fields(
                document, child.job_id, request_key=key + ":fields"
            )
            results[document] = {
                "state": "REGISTERED",
                "job_id": str(child.job_id),
                "fields_job_id": str(fields.job_id),
            }
        else:
            results[document] = {"state": "REGISTERED", "job_id": str(child.job_id)}
        worker.queue.heartbeat(job, {"results": results})


def execution(queue: Queue, job: Job) -> dict[str, Any]:
    pending = [job.job_id]
    seen = set()
    stages = []
    while pending:
        key = pending.pop(0)
        if key in seen:
            continue
        seen.add(key)
        item = queue.get(key)
        stages.append(
            {
                "job_id": str(key),
                "kind": item.kind,
                "status": item.status,
                "checkpoint": item.checkpoint,
            }
        )
        for result in item.checkpoint.get("results", {}).values():
            for name in ("job_id", "fields_job_id"):
                if result.get(name):
                    pending.append(UUID(result[name]))
        for name in ("image_job_id", "follow_up_job_id", "fields_job_id"):
            if item.checkpoint.get(name):
                pending.append(UUID(item.checkpoint[name]))
        if len(seen) > 200:
            raise ValueError("QUALITY_CHAIN_TOO_LONG")
    counts = dict(Counter(s["status"] for s in stages))
    return {
        "job_id": str(job.job_id),
        "status": job.status,
        "checkpoint": job.checkpoint,
        "stages": stages,
        "stage_counts": counts,
        "terminal": not any(counts.get(s) for s in ("QUEUED", "RUNNING")),
    }
