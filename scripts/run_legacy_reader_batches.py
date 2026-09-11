"""Plan and drive bounded reader jobs; all row mutations run through the single worker."""

import argparse
import json
import time
from hashlib import file_digest, sha256
from pathlib import Path

import pyarrow.parquet as pq

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.search.parquet import legacy_snapshot
from klegal_gold.storage.files import FileStore


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


def make_plan(
    path,
    records,
    *,
    positions=None,
    current_readers=None,
    batch_size=100,
    include_statute_images=False,
    retry_generation=0,
):
    if type(retry_generation) is not int or retry_generation < 0:
        raise ValueError("INVALID_RETRY_GENERATION")
    if not 1 <= batch_size <= 100:
        raise ValueError("INVALID_BATCH_SIZE")
    parquet = pq.ParquetFile(path)
    available = parquet.read(columns=["__legacy_position"]).column(0).to_pylist()
    if any(type(p) is not int or p < 0 for p in available) or len(set(available)) != len(available):
        raise ValueError("INVALID_CORPUS_LOCATORS")
    selected = sorted(available if positions is None else positions)
    if not selected or len(set(selected)) != len(selected) or not set(selected) <= set(available):
        raise ValueError("INVALID_SELECTED_POSITIONS")
    mapping = current_readers or {}
    if not {int(p) for p in mapping} <= set(selected):
        raise ValueError("CURRENT_MAPPING_OUTSIDE_SELECTION")
    with path.open("rb") as stream:
        digest = file_digest(stream, "sha256").hexdigest()
    snapshot = legacy_snapshot(path)
    acquisition_revision = None
    if mapping or include_statute_images:
        urls = set()
        readers = ReaderStore(records)
        for reader_id in set(mapping.values()):
            manifest = readers.read(reader_id)
            urls.update(
                ref["resolved_url"] for ref in manifest["images"] if ref.get("resolved_url")
            )
        with records.db.connect() as conn:
            states = conn.execute(
                "SELECT url,status,blob_hash,attempts,updated_at,last_error_code "
                "FROM image_acquisitions WHERE url=ANY(%s) OR (%s AND ("
                "url LIKE 'https://www.law.go.kr/flDownload.do?%%' OR "
                "url LIKE 'https://law.go.kr/flDownload.do?%%')) ORDER BY url",
                (sorted(urls), include_statute_images),
            ).fetchall()
        acquisition_revision = sha256(
            json.dumps(states, sort_keys=True, default=str).encode()
        ).hexdigest()
    batches = []
    for offset in range(0, len(selected), batch_size):
        batch_positions = selected[offset : offset + batch_size]
        payload = {
            "version": "legacy-reader-batch-1",
            "parquet_sha256": digest,
            "snapshot_sha256": snapshot,
            "positions": batch_positions,
            "current_readers": {
                str(p): mapping[str(p)] for p in batch_positions if str(p) in mapping
            },
        }
        if include_statute_images:
            payload["include_statute_images"] = True
        if retry_generation:
            payload["retry_generation"] = retry_generation
        if acquisition_revision is not None:
            payload["acquisition_revision"] = acquisition_revision
        raw = encoded(payload)
        artifact = "legacy-reader-batch:" + sha256(raw).hexdigest()
        records.put_artifact(
            artifact, raw, origin="MANIFEST", metadata={"kind": "LEGACY_READER_BATCH_INPUT"}
        )
        batches.append({"manifest_artifact_id": artifact, "positions": batch_positions})
    plan = {
        "version": "legacy-reader-plan-1",
        "parquet_sha256": digest,
        "snapshot_sha256": snapshot,
        "corpus_rows": len(available),
        "selected_rows": len(selected),
        "batch_size": batch_size,
        "batches": batches,
    }
    raw = encoded(plan)
    artifact = "legacy-reader-plan:" + sha256(raw).hexdigest()
    records.put_artifact(
        artifact, raw, origin="MANIFEST", metadata={"kind": "LEGACY_READER_BATCH_PLAN"}
    )
    return {"plan_artifact_id": artifact, "rows": len(selected), "batches": len(batches)}


def run_owned_job(records, queue, worker, job):
    """Resume this job, letting Queue.claim recover its expired fenced lease."""
    while job.status not in {"SUCCEEDED", "FAILED"}:
        if queue.drain_status()["draining"]:
            break
        with records.db.connect() as conn:
            foreign = conn.execute(
                "SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING') AND job_id<>%s LIMIT 1",
                (job.job_id,),
            ).fetchone()
            owner = conn.execute(
                "SELECT status,lease_until>clock_timestamp() AS live FROM jobs WHERE job_id=%s",
                (job.job_id,),
            ).fetchone()
        if foreign or (owner["status"] == "RUNNING" and owner["live"]):
            raise ValueError("ANOTHER_WORKER_JOB_ACTIVE")
        if not worker.run_once():
            time.sleep(1)
        job = queue.get(job.job_id)
    return job


def run_plan(records, pointer, *, max_batches):
    if max_batches < 1:
        raise ValueError("INVALID_BATCH_LIMIT")
    plan = json.loads(records.read(pointer["plan_artifact_id"]))
    queue = Queue(records.db, lease_seconds=300)
    worker = Worker(queue, records)
    results = []
    executed = 0
    try:
        for batch in plan["batches"]:
            if executed >= max_batches:
                break
            if queue.drain_status()["draining"]:
                break
            key = "reader-stage:" + batch["manifest_artifact_id"].split(":", 1)[1]
            job = queue.submit_legacy_reader_batch(key, batch["manifest_artifact_id"])
            if job.status not in {"SUCCEEDED", "FAILED"}:
                attempts_before = job.attempts
                job = run_owned_job(records, queue, worker, job)
                executed += int(job.attempts > attempts_before)
            result = {
                "job_id": str(job.job_id),
                "status": job.status,
                "positions": batch["positions"],
                "checkpoint": job.checkpoint,
            }
            results.append(result)
            print(
                json.dumps(
                    {
                        "batch": len(results),
                        "batches": len(plan["batches"]),
                        "rows": len(batch["positions"]),
                        "status": job.status,
                        "checkpoint": job.checkpoint,
                    }
                ),
                flush=True,
            )
            if job.status != "SUCCEEDED":
                break
    finally:
        queue.worker_heartbeat(worker.worker_id, stopped=True)
    report = {
        "plan_artifact_id": pointer["plan_artifact_id"],
        "batches_considered": len(results),
        "total_batches": len(plan["batches"]),
        "executed": executed,
        "results": results,
    }
    raw = encoded(report)
    artifact = "legacy-reader-run:" + sha256(raw).hexdigest()
    records.put_artifact(
        artifact, raw, origin="MANIFEST", metadata={"kind": "LEGACY_READER_BATCH_RUN"}
    )
    return {"report_artifact_id": artifact, **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("plan")
    create.add_argument("--output", required=True, type=Path)
    create.add_argument(
        "--positions", type=Path, help="JSON array of exact row positions; omit for all rows"
    )
    create.add_argument(
        "--current-readers",
        type=Path,
        help="JSON mapping row position to preserved current reader ID",
    )
    create.add_argument("--batch-size", type=int, default=100)
    create.add_argument("--include-statute-images", action="store_true")
    create.add_argument("--retry-generation", type=int, default=0)
    run = commands.add_parser("run")
    run.add_argument("--plan", required=True, type=Path)
    run.add_argument("--max-batches", type=int, default=1)
    run.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    settings = load_settings()
    records = Records(Database.from_settings(settings), FileStore(settings.data_dir))
    if args.command == "plan":
        if settings.legacy_parquet_path is None:
            parser.error("LEGACY_PARQUET_PATH is required")
        result = make_plan(
            settings.legacy_parquet_path,
            records,
            positions=json.loads(args.positions.read_text()) if args.positions else None,
            current_readers=json.loads(args.current_readers.read_text())
            if args.current_readers
            else None,
            batch_size=args.batch_size,
            include_statute_images=args.include_statute_images,
            retry_generation=args.retry_generation,
        )
        target = args.output
    else:
        result = run_plan(records, json.loads(args.plan.read_text()), max_batches=args.max_batches)
        target = args.report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "results"}))


if __name__ == "__main__":
    main()
