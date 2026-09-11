"""Preserve current provider evidence for audited legacy image rows through source jobs."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from run_legacy_reader_batches import run_owned_job
from stage_reader_samples import title_of

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore


def latest_current(records, source_id):
    with records.db.connect() as conn:
        row = conn.execute(
            "SELECT artifact_id FROM artifacts WHERE metadata->>'kind'='READER_DOCUMENT' "
            "AND metadata->>'origin'='CURRENT_SOURCE' AND metadata->>'source_id'=%s "
            "ORDER BY created_at DESC,artifact_id DESC LIMIT 1",
            (source_id,),
        ).fetchone()
    return row["artifact_id"].removeprefix("reader:") if row else None


def latest_source(records, source_id):
    with records.db.connect() as conn:
        row = conn.execute(
            "SELECT sv.artifact_id FROM source_versions sv JOIN artifacts a USING(artifact_id) "
            "WHERE source='scourt' AND source_id=%s "
            "ORDER BY a.created_at DESC,sv.artifact_id DESC LIMIT 1",
            (source_id,),
        ).fetchone()
    return row["artifact_id"] if row else None


def publish_current(records, artifact_id, source_id):
    raw = records.read(artifact_id)
    body = json.loads(raw)["data"]["dma_jdcpctCtxt"]
    if str(body["jisCntntsSrno"]) != source_id:
        raise ValueError("SOURCE_ID_MISMATCH")
    html = body["orgdocXmlCtt"]
    title = title_of(html)
    if not title:
        raise ValueError("CURRENT_TITLE_UNAVAILABLE")
    return ReaderStore(records).preserve(
        html,
        title=title,
        source_id=source_id,
        origin="CURRENT_SOURCE",
        provenance={
            "source_artifact_id": artifact_id,
            "source_response_sha256": sha256(raw).hexdigest(),
        },
        acquisitions={},
    )


def preserve_source_result(records, result):
    raw = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
    artifact = "legacy-image-source-row:" + sha256(raw).hexdigest()
    records.put_artifact(
        artifact,
        raw,
        origin="MANIFEST",
        metadata={
            "kind": "LEGACY_IMAGE_SOURCE_ROW_RESULT",
            "source_id": result["source_id"],
            "job_id": result["job_id"],
            "status": result["status"],
        },
    )


def fetch_failure_kind(records, job_id, source_id):
    # A per-job result survives later requests; never rewrite historical receipts.
    with records.db.connect() as conn:
        cached = conn.execute(
            "SELECT artifact_id FROM artifacts "
            "WHERE metadata->>'kind'='LEGACY_IMAGE_SOURCE_ROW_RESULT' "
            "AND metadata->>'job_id'=%s AND metadata->>'source_id'=%s "
            "AND metadata->>'status' IN ('SOURCE_NOT_FOUND','SOURCE_FETCH_FAILED') "
            "ORDER BY created_at DESC,artifact_id DESC LIMIT 1",
            (str(job_id), source_id),
        ).fetchone()
        if cached:
            return json.loads(records.read(cached["artifact_id"]))["status"]
        # Older jobs have no row result. Search their immutable receipts without
        # a global newest-N cutoff that could misclassify historical NOT_FOUND.
        receipts = conn.execute(
            "SELECT artifact_id,parent_id FROM artifacts "
            "WHERE metadata->>'kind'='HTTP_ATTEMPT' ORDER BY created_at DESC"
        ).fetchall()
    for row in receipts:
        receipt = json.loads(records.read(row["artifact_id"]))
        if receipt.get("run_id") != str(job_id):
            continue
        try:
            response = json.loads(records.read(row["parent_id"]))
        except (ValueError, UnicodeDecodeError):
            continue
        if (
            isinstance(response, dict)
            and isinstance(response.get("data"), dict)
            and response["data"].get("result") == "notExtist"
        ):
            return "SOURCE_NOT_FOUND"
    return "SOURCE_FETCH_FAILED"


def prepare(records, targets, *, inventory_hash, max_sources):
    if not 1 <= max_sources <= 5000:
        raise ValueError("INVALID_SOURCE_LIMIT")
    grouped = {}
    for row in targets:
        source_id = row["source_id"]
        if row.get("source_id_usable"):
            grouped.setdefault(source_id, []).append(row["position"])
    queue = Queue(records.db, lease_seconds=300)
    worker = Worker(queue, records)
    mapping, results = {}, []
    attempted = 0
    structural_failures = 0
    try:
        for source_id, positions in grouped.items():
            if queue.drain_status()["draining"]:
                break
            current = latest_current(records, source_id)
            artifact = latest_source(records, source_id) if current is None else None
            job = None
            if current is None and artifact is None:
                key = "legacy-image-source:" + inventory_hash + ":" + source_id
                with records.db.connect() as conn:
                    existing = conn.execute(
                        "SELECT job_id FROM jobs WHERE request_key=%s", (key,)
                    ).fetchone()
                job = queue.get(existing["job_id"]) if existing else None
                if job is None or job.status not in {"SUCCEEDED", "FAILED"}:
                    if attempted >= max_sources:
                        break
                    if job is None:
                        with records.db.connect() as conn:
                            if conn.execute(
                                "SELECT 1 FROM jobs WHERE status IN ('RUNNING','QUEUED') LIMIT 1"
                            ).fetchone():
                                raise ValueError("ANOTHER_WORKER_JOB_ACTIVE")
                        job = queue.submit_scourt_detail(key, source_id)
                    attempts_before = job.attempts
                    job = run_owned_job(records, queue, worker, job)
                    attempted += int(job.attempts > attempts_before)
                if job.status == "SUCCEEDED":
                    artifact = latest_source(records, source_id)
                elif job.status != "FAILED":
                    break
            try:
                if current is None and artifact is not None:
                    current = publish_current(records, artifact, source_id)
                if current is None:
                    status = (
                        fetch_failure_kind(records, job.job_id, source_id)
                        if job
                        else "SOURCE_UNAVAILABLE"
                    )
                    if status != "SOURCE_NOT_FOUND":
                        structural_failures += 1
                else:
                    ReaderStore(records).read(current)
                    mapping.update({str(p): current for p in positions})
                    status = "CURRENT_EVIDENCE_PRESERVED"
                    structural_failures = 0
            except (ValueError, KeyError):
                status = "CURRENT_STRUCTURE_UNCONFIRMED"
                structural_failures += 1
            results.append(
                {
                    "source_id": source_id,
                    "positions": positions,
                    "status": status,
                    "current_reader": current,
                    "source_artifact": artifact,
                    "job_id": str(job.job_id) if job else None,
                }
            )
            preserve_source_result(records, results[-1])
            print(
                json.dumps(
                    {
                        "sources_done": len(results),
                        "sources_total": len(grouped),
                        "status": status,
                        "source_id": source_id,
                    }
                ),
                flush=True,
            )
            if structural_failures >= 3:
                break
    finally:
        queue.worker_heartbeat(worker.worker_id, stopped=True)
    return {
        "inventory_sha256": inventory_hash,
        "current_readers": mapping,
        "results": results,
        "sources_total": len(grouped),
        "sources_considered": len(results),
        "attempted": attempted,
        "paused_for_structure": structural_failures >= 3,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", required=True, type=Path)
    parser.add_argument("--max-sources", type=int, default=10)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    raw = args.targets.read_bytes()
    settings = load_settings()
    records = Records(Database.from_settings(settings), FileStore(settings.data_dir))
    report = prepare(
        records,
        [json.loads(line) for line in raw.splitlines()],
        inventory_hash=sha256(raw).hexdigest(),
        max_sources=args.max_sources,
    )
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True).encode()
    artifact = "legacy-image-source-plan:" + sha256(encoded).hexdigest()
    records.put_artifact(
        artifact, encoded, origin="MANIFEST", metadata={"kind": "LEGACY_IMAGE_SOURCE_RESULT"}
    )
    report["report_artifact_id"] = artifact
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"current_readers", "results"}}))


if __name__ == "__main__":
    main()
