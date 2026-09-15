"""Admin-only read-only audit and explicit bounded remediation commands."""

import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.fields.contract import VERSION
from klegal_gold.jobs.queue import Queue
from klegal_gold.quality.service import execution, latest, save
from klegal_gold.sources.scourt import validate_window
from klegal_gold.storage.files import FileStore
from klegal_gold.web.auth import require_admin, same_origin

router = APIRouter(prefix="/api/admin/quality", dependencies=[Depends(require_admin)])


def records() -> Records:
    settings = load_settings()
    return Records(Database.from_settings(settings), FileStore(settings.data_dir))


class AuditRequest(BaseModel):
    request_id: UUID
    date_from: str | None = None
    date_to: str | None = None


class ReprocessRequest(BaseModel):
    request_id: UUID
    audit_job_id: UUID
    action: Literal["FIELDS", "LAWGO_TRANSIENT", "IMAGES_TRANSIENT"]
    document_ids: list[Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]] = Field(
        min_length=1, max_length=20
    )


@router.post("/audits", dependencies=[Depends(same_origin)])
def submit_audit(body: AuditRequest, store: Annotated[Records, Depends(records)]) -> dict[str, Any]:
    try:
        validate_window(body.date_from, body.date_to)
        params = body.model_dump(mode="json")
        key = "quality-scope:" + str(body.request_id)
        try:
            scope = json.loads(store.read(key))
            if scope["request"] != params:
                raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
        except ValueError as exc:
            if str(exc) != "ARTIFACT_NOT_FOUND":
                raise
            documents = list(latest(store).values())
            if len(documents) > 10000:
                raise ValueError("QUALITY_SCOPE_TOO_LARGE") from None
            if body.date_from:
                selected = []
                for document in documents:
                    day = str(
                        ReaderStore(store).read(document)["provenance"].get("decision_date", "")
                    ).replace("-", "")
                    if body.date_from.replace("-", "") <= day <= str(body.date_to).replace("-", ""):
                        selected.append(document)
                documents = selected
            scope = {
                "request": params,
                "document_ids": documents,
                "origin": "CURRENT_SOURCE",
                "note": "source별 최신 reader. 기존 Parquet 및 reader 미등록 자료 제외.",
            }
            save(store, key, scope)
        job = Queue(store.db)._submit(
            "quality-audit:" + str(body.request_id),
            "AUDIT_CURRENT_QUALITY",
            {"scope_artifact_id": key, "field_rule": VERSION},
            3,
        )
        return {"job_id": str(job.job_id), "status": job.status}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/jobs")
def history(store: Annotated[Records, Depends(records)]) -> dict[str, Any]:
    with store.db.connect() as conn:
        rows = conn.execute(
            "SELECT job_id,kind,status,created_at FROM jobs WHERE kind IN "
            "('AUDIT_CURRENT_QUALITY','REPROCESS_QUALITY') ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return {"items": rows}


@router.get("/jobs/{job_id}")
def status(
    job_id: UUID,
    store: Annotated[Records, Depends(records)],
    offset: int = Query(0, ge=0),
    category: str = Query("", pattern=r"^(RETRYABLE|LOGIC_REQUIRED|REVIEW|NOT_PROVIDED|PENDING)?$"),
) -> dict[str, Any]:
    queue = Queue(store.db)
    try:
        job = queue.get(job_id)
    except ValueError:
        raise HTTPException(404, "QUALITY_JOB_NOT_FOUND") from None
    if job.kind not in {"AUDIT_CURRENT_QUALITY", "REPROCESS_QUALITY"}:
        raise HTTPException(404, "QUALITY_JOB_NOT_FOUND")
    result = execution(queue, job)
    if job.checkpoint.get("report_artifact_id"):
        report = json.loads(store.read(job.checkpoint["report_artifact_id"]))
        rows = [r for r in report["items"] if not category or r["counts"].get(category)]
        if category:
            rows = [
                {
                    **row,
                    "issues": [issue for issue in row["issues"] if issue["category"] == category],
                }
                for row in rows
            ]
        result["report"] = {
            **report,
            "scope": {k: v for k, v in report["scope"].items() if k != "document_ids"},
            "items": rows[offset : offset + 25],
            "filtered_count": len(rows),
            "offset": offset,
        }
    return result


@router.post("/reprocess", dependencies=[Depends(same_origin)])
def reprocess(
    body: ReprocessRequest, store: Annotated[Records, Depends(records)]
) -> dict[str, Any]:
    queue = Queue(store.db)
    try:
        original = queue.get(body.audit_job_id)
    except ValueError:
        raise HTTPException(404, "QUALITY_JOB_NOT_FOUND") from None
    if original.kind != "AUDIT_CURRENT_QUALITY" or not original.checkpoint.get(
        "report_artifact_id"
    ):
        raise HTTPException(409, "QUALITY_REPORT_REQUIRED")
    report = json.loads(store.read(original.checkpoint["report_artifact_id"]))
    allowed = {r["document_id"] for r in report["items"]}
    if (
        len(set(body.document_ids)) != len(body.document_ids)
        or not set(body.document_ids) <= allowed
    ):
        raise HTTPException(400, "QUALITY_SELECTION_INVALID")
    try:
        job = queue._submit(
            "quality-reprocess:" + str(body.request_id),
            "REPROCESS_QUALITY",
            {
                "audit_job_id": str(body.audit_job_id),
                "action": body.action,
                "document_ids": sorted(body.document_ids),
                "field_rule": VERSION,
            },
            3,
        )
        return {"job_id": str(job.job_id), "status": job.status}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
