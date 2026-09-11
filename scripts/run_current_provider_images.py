"""Run audited current-only image candidates through the existing bounded worker queue."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from collections import Counter
from hashlib import sha256
from pathlib import Path

from audit_current_provider_images import (
    NOTICE,
    SCOPE,
    count_refs,
    encoded,
    inspect_reader,
    manifest_reference,
    mapping_validation,
)
from audit_current_provider_images import (
    VERSION as AUDIT_VERSION,
)
from run_legacy_image_waves import ensure_ready
from run_legacy_reader_batches import run_owned_job

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

VERSION = "current-provider-image-run-1"
PAUSE_CODES = {
    "RUNTIME_DRAINING",
    "ANOTHER_WORKER_JOB_ACTIVE",
    "CURRENT_ONLY_PRIOR_ATTEMPT_REQUIRES_REVIEW",
    "CURRENT_ONLY_TERMINAL_JOB_FAILED",
}


def checked_file(directory, name, metadata):
    if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
        raise ValueError("INVALID_AUDIT_FILENAME")
    path = directory / name
    if (
        path.is_symlink()
        or not path.is_file()
        or not path.resolve().is_relative_to(directory.resolve())
    ):
        raise ValueError("INVALID_AUDIT_FILE")
    raw = path.read_bytes()
    if len(raw) != metadata["size_bytes"] or sha256(raw).hexdigest() != metadata["sha256"]:
        raise ValueError("AUDIT_FILE_HASH_MISMATCH")
    return raw


def load_audit(directory, expected_summary_sha256):
    if re.fullmatch("[0-9a-f]{64}", expected_summary_sha256) is None:
        raise ValueError("INVALID_AUDIT_SUMMARY_HASH")
    path = directory / "summary.json"
    if path.is_symlink():
        raise ValueError("INVALID_AUDIT_FILE")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_summary_sha256:
        raise ValueError("AUDIT_SUMMARY_HASH_MISMATCH")
    summary = json.loads(raw)
    if (
        summary.get("version") != AUDIT_VERSION
        or summary.get("scope") != SCOPE
        or summary.get("legacy_link_approved") is not False
        or summary.get("notice") != NOTICE
        or not all(
            summary.get("verification", {}).get(k) is True
            for k in (
                "receipt_reader_and_html_hashes",
                "all_image_occurrences_reparsed_and_matched",
                "unique_parent_and_order",
            )
        )
    ):
        raise ValueError("AUDIT_CONTRACT_MISMATCH")
    files = {
        name: checked_file(directory, name, meta) for name, meta in summary["artifacts"].items()
    }
    references = [json.loads(line) for line in files["references.jsonl"].splitlines()]
    indexed = {(r["current_reader_id"], r["order"]): r for r in references}
    if len(indexed) != len(references):
        raise ValueError("DUPLICATE_AUDIT_REFERENCE")
    expected = {key: r for key, r in indexed.items() if r["eligible_never_attempted"]}
    seen, seen_urls, candidates = set(), set(), []
    for index, entry in enumerate(summary["candidate_manifests"], start=1):
        name = entry["file"]
        if name != f"never-attempted-{index:03d}.json":
            raise ValueError("INVALID_CANDIDATE_SEQUENCE")
        content = files[name]
        digest = sha256(content).hexdigest()
        artifact = "image-manifest:current-source-only-" + digest
        value = json.loads(content)
        if (
            entry["artifact_id_candidate"] != artifact
            or value.get("kind") != "IMAGE_REFERENCE_MANIFEST"
            or value.get("version") != AUDIT_VERSION
            or value.get("scope") != SCOPE
            or value.get("legacy_link_approved") is not False
            or value.get("notice") != NOTICE
            or value.get("selection") != "ELIGIBLE_NEVER_ATTEMPTED_ONLY"
            or value.get("snapshot_at") != summary["snapshot_at"]
            or value.get("receipts") != summary["receipts"]
        ):
            raise ValueError("CANDIDATE_CONTRACT_MISMATCH")
        refs = value["references"]
        urls = {r["resolved_url"] for r in refs}
        if not 1 <= len(urls) <= 500 or seen_urls.intersection(urls):
            raise ValueError("CANDIDATE_URL_LIMIT_OR_DUPLICATE")
        seen_urls.update(urls)
        if any(entry[k] != v for k, v in count_refs(refs).items()):
            raise ValueError("CANDIDATE_COUNT_MISMATCH")
        for ref in refs:
            key = (ref["current_reader_id"], ref["order"])
            original = expected.get(key)
            if (
                key in seen
                or original is None
                or ref != manifest_reference(original)
                or ref["acquisition_state"] != "NEVER_ATTEMPTED"
                or ref["acquisition"] is not None
                or ref["attempt_records"] != 0
                or ref["scope"] != SCOPE
                or ref["legacy_link_approved"] is not False
                or ref["row_position"] is not None
                or not mapping_validation(ref, ref["source_id"])[0]
            ):
                raise ValueError("CANDIDATE_REFERENCE_MISMATCH")
            seen.add(key)
        candidates.append(
            {
                "file": name,
                "artifact_id": artifact,
                "sha256": digest,
                "raw": content,
                "payload": value,
            }
        )
    if (
        seen != set(expected)
        or count_refs(list(expected.values())) != summary["summary"]["eligible_never_attempted"]
    ):
        raise ValueError("CANDIDATE_COVERAGE_MISMATCH")
    return {
        "summary": summary,
        "summary_raw": raw,
        "summary_sha256": expected_summary_sha256,
        "candidates": candidates,
    }


def verify_sources(records, audit):
    by_parent = {}
    for candidate in audit["candidates"]:
        for ref in candidate["payload"]["references"]:
            by_parent.setdefault(ref["current_reader_id"], []).append(ref)
    for reader_id, refs in by_parent.items():
        parent, current = inspect_reader(records, reader_id, refs[0]["legacy_bindings"])
        for ref in refs:
            if (
                ref["current_html_sha256"] != parent["html_sha256"]
                or ref["current_html_artifact_id"] != parent["html_artifact_id"]
                or any(
                    ref[key] != current[ref["order"]][key]
                    for key in (
                        "source_system",
                        "source_id",
                        "order",
                        "original_src",
                        "name",
                        "resolved_url",
                        "provider_mapping_values",
                        "image_reference",
                    )
                )
            ):
                raise ValueError("CANDIDATE_CURRENT_PARENT_MISMATCH")
    for receipt in audit["summary"]["receipts"]:
        raw = records.read(receipt["artifact_id"])
        value = json.loads(raw)
        if (
            receipt["artifact_id"] != "legacy-image-wave:" + sha256(raw).hexdigest()
            or value.get("status") != "COMPLETED"
            or any(
                value.get(k) != receipt[k] for k in ("wave", "inventory_sha256", "targets_sha256")
            )
        ):
            raise ValueError("CANDIDATE_WAVE_RECEIPT_MISMATCH")


def atomic_local(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ValueError("LOCAL_RUN_STATE_CONFLICT") from None
    finally:
        temporary.unlink(missing_ok=True)


def preserve(records, artifact, raw, *, kind, parent=None):
    if artifact.rsplit(":", 1)[-1].split("-")[-1] != sha256(raw).hexdigest():
        raise ValueError("RUN_ARTIFACT_HASH_MISMATCH")
    records.put_artifact(
        artifact, raw, origin="MANIFEST", parent_id=parent, metadata={"kind": kind}
    )
    if records.read(artifact) != raw:
        raise ValueError("RUN_ARTIFACT_READBACK_MISMATCH")


def prepare_plan(records, audit, output_dir):
    summary_id = "current-image-audit:" + audit["summary_sha256"]
    preserve(records, summary_id, audit["summary_raw"], kind="CURRENT_SOURCE_IMAGE_AUDIT")
    for candidate in audit["candidates"]:
        preserve(
            records,
            candidate["artifact_id"],
            candidate["raw"],
            kind="IMAGE_REFERENCE_MANIFEST",
            parent=summary_id,
        )
    plan = {
        "version": VERSION,
        "scope": SCOPE,
        "notice": NOTICE,
        "legacy_link_approved": False,
        "audit_summary_artifact": summary_id,
        "audit_summary_sha256": audit["summary_sha256"],
        "candidates": [
            {"artifact_id": c["artifact_id"], "sha256": c["sha256"]} for c in audit["candidates"]
        ],
    }
    raw = encoded(plan)
    artifact = "current-image-plan:" + sha256(raw).hexdigest()
    preserve(records, artifact, raw, kind="CURRENT_SOURCE_IMAGE_PLAN", parent=summary_id)
    atomic_local(output_dir / "plan.json", encoded({"artifact_id": artifact, **plan}) + b"\n")
    return artifact


def url_states(records, urls):
    with records.db.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        acquisitions = {
            r["url"]: dict(r)
            for r in conn.execute(
                "SELECT url,status,blob_hash,attempts,last_error_code FROM image_acquisitions "
                "WHERE url=ANY(%s)",
                (list(urls),),
            ).fetchall()
        }
        attempts = {
            r["url"]: r["records"]
            for r in conn.execute(
                "SELECT url,count(*) AS records FROM image_acquisition_attempts "
                "WHERE url=ANY(%s) GROUP BY url",
                (list(urls),),
            ).fetchall()
        }
    return {
        url: {"acquisition": acquisitions.get(url), "attempt_records": attempts.get(url, 0)}
        for url in urls
    }


def fresh(state):
    return state["acquisition"] is None and state["attempt_records"] == 0


def selection(records, audit, candidate, output_dir, index):
    path = output_dir / f"selection-{index:03d}.json"
    original = candidate["payload"]["references"]
    if path.exists():
        local = json.loads(path.read_bytes())
        artifact = local["artifact_id"]
        raw = records.read(artifact)
        payload = json.loads(raw)
        if artifact != "image-manifest:current-source-run-" + sha256(raw).hexdigest() or local != {
            "artifact_id": artifact,
            **payload,
        }:
            raise ValueError("SELECTION_RECEIPT_MISMATCH")
    else:
        states = url_states(records, sorted({r["resolved_url"] for r in original}))
        selected = {url for url, state in states.items() if fresh(state)}
        payload = {
            "kind": "IMAGE_REFERENCE_MANIFEST",
            "version": VERSION,
            "scope": SCOPE,
            "notice": NOTICE,
            "legacy_link_approved": False,
            "audit_summary_sha256": audit["summary_sha256"],
            "original_manifest_artifact": candidate["artifact_id"],
            "original_manifest_sha256": candidate["sha256"],
            "selection": "UNATTEMPTED_AT_EXECUTION_PREFLIGHT",
            "excluded_urls": [
                {"url": url, **state} for url, state in states.items() if url not in selected
            ],
            "references": [r for r in original if r["resolved_url"] in selected],
        }
        raw = encoded(payload)
        artifact = "image-manifest:current-source-run-" + sha256(raw).hexdigest()
        preserve(
            records, artifact, raw, kind="IMAGE_REFERENCE_MANIFEST", parent=candidate["artifact_id"]
        )
        atomic_local(path, encoded({"artifact_id": artifact, **payload}) + b"\n")
    selected = {r["resolved_url"] for r in payload["references"]}
    excluded = {r["url"] for r in payload["excluded_urls"]}
    if (
        payload.get("scope") != SCOPE
        or payload.get("legacy_link_approved") is not False
        or payload.get("version") != VERSION
        or payload.get("notice") != NOTICE
        or payload.get("audit_summary_sha256") != audit["summary_sha256"]
        or payload.get("original_manifest_artifact") != candidate["artifact_id"]
        or payload.get("original_manifest_sha256") != candidate["sha256"]
        or selected.intersection(excluded)
        or selected | excluded != {r["resolved_url"] for r in original}
        or payload["references"] != [r for r in original if r["resolved_url"] in selected]
    ):
        raise ValueError("SELECTION_INPUT_MISMATCH")
    return artifact, payload


def job_by_key(records, queue, key):
    with records.db.connect() as conn:
        row = conn.execute("SELECT job_id FROM jobs WHERE request_key=%s", (key,)).fetchone()
    return queue.get(row["job_id"]) if row else None


class AttemptGuard:
    """Reuse the worker; forbid its automatic retry from refetching a failed/attempted URL."""

    def __init__(self, records, queue, worker, key, urls):
        self.records, self.queue, self.worker = records, queue, worker
        self.key, self.urls = key, urls
        self.calls = 0

    def run_once(self):
        ensure_ready(self.records, self.queue, owned_keys=[self.key])
        states = url_states(self.records, self.urls)
        if any(
            not fresh(s) and (s["acquisition"] or {}).get("status") != "ACQUIRED"
            for s in states.values()
        ):
            raise ValueError("CURRENT_ONLY_PRIOR_ATTEMPT_REQUIRES_REVIEW")
        ran = self.worker.run_once()
        self.calls += int(ran)
        return ran


def run(audit, records, output_dir, *, max_batches=1):
    if type(max_batches) is not int or max_batches < 1:
        raise ValueError("INVALID_BATCH_LIMIT")
    # Verify before any durable registration. Local state cannot authorize different input.
    expected_summary = "current-image-audit:" + audit["summary_sha256"]
    existing_plan = output_dir / "plan.json"
    if existing_plan.exists():
        pointer = json.loads(existing_plan.read_bytes())
        raw = records.read(pointer["artifact_id"])
        if (
            pointer != {"artifact_id": pointer["artifact_id"], **json.loads(raw)}
            or pointer["artifact_id"] != "current-image-plan:" + sha256(raw).hexdigest()
            or pointer.get("audit_summary_artifact") != expected_summary
        ):
            raise ValueError("RUN_RESUME_INPUT_MISMATCH")
    verify_sources(records, audit)
    queue, worker = Queue(records.db, lease_seconds=300), None
    results, performed = [], 0
    report = {
        "version": VERSION,
        "scope": SCOPE,
        "notice": NOTICE,
        "legacy_link_approved": False,
        "audit_summary_sha256": audit["summary_sha256"],
        "status": "BOUNDED",
        "results": results,
        "total_candidate_batches": len(audit["candidates"]),
    }
    plan_id = None
    known_keys = []
    for index, candidate in enumerate(audit["candidates"], start=1):
        if (output_dir / f"selection-{index:03d}.json").exists():
            saved_artifact, _ = selection(records, audit, candidate, output_dir, index)
            known_keys.append("current-source-image:" + saved_artifact.split(":", 1)[1])
    try:
        for index, candidate in enumerate(audit["candidates"], start=1):
            if performed >= max_batches:
                break
            ensure_ready(records, queue, owned_keys=known_keys)
            if plan_id is None:
                plan_id = prepare_plan(records, audit, output_dir)
                report["plan_artifact_id"] = plan_id
            artifact, payload = selection(records, audit, candidate, output_dir, index)
            refs = payload["references"]
            item = {
                "batch": index,
                "manifest_artifact_id": artifact,
                "original_manifest_sha256": candidate["sha256"],
                "selected": count_refs(refs),
                "excluded_urls": len(payload["excluded_urls"]),
                "status": "SKIPPED_ALREADY_ATTEMPTED",
                "job_id": None,
            }
            results.append(item)
            if not refs:
                continue
            key = "current-source-image:" + artifact.split(":", 1)[1]
            job = job_by_key(records, queue, key)
            if job is not None and job.status == "FAILED":
                item.update(
                    job_id=str(job.job_id),
                    status=job.status,
                    last_attempt_checkpoint=job.checkpoint,
                )
                raise ValueError("CURRENT_ONLY_TERMINAL_JOB_FAILED")
            if job is None or job.status != "SUCCEEDED":
                ensure_ready(records, queue, owned_keys=[key])
                states = url_states(records, {r["resolved_url"] for r in refs})
                if any(
                    not fresh(s) and (s["acquisition"] or {}).get("status") != "ACQUIRED"
                    for s in states.values()
                ):
                    if job is not None:
                        item.update(job_id=str(job.job_id), status=job.status)
                    raise ValueError("CURRENT_ONLY_PRIOR_ATTEMPT_REQUIRES_REVIEW")
                job = queue.submit_image_batch(key, artifact, max_urls=500)
                if worker is None:
                    worker = Worker(queue, records)
                guarded = AttemptGuard(
                    records, queue, worker, key, {r["resolved_url"] for r in refs}
                )
                item.update(job_id=str(job.job_id), status=job.status)
                try:
                    job = run_owned_job(records, queue, guarded, job)
                finally:
                    performed += int(guarded.calls > 0)
                    latest = queue.get(job.job_id)
                    item.update(
                        job_id=str(latest.job_id),
                        status=latest.status,
                        last_attempt_checkpoint=latest.checkpoint,
                    )
            else:
                item.update(
                    job_id=str(job.job_id),
                    status=job.status,
                    last_attempt_checkpoint=job.checkpoint,
                )
            states = url_states(records, {r["resolved_url"] for r in refs})
            item["current_url_states"] = dict(
                Counter(
                    (s["acquisition"] or {}).get("status", "NO_ACQUISITION_ROW")
                    for s in states.values()
                )
            )
            if job.status == "FAILED":
                raise ValueError("CURRENT_ONLY_TERMINAL_JOB_FAILED")
            if job.status != "SUCCEEDED":
                report["stop_reason"] = "JOB_" + job.status
                break
        if len(results) == len(audit["candidates"]) and all(
            r["status"] in {"SUCCEEDED", "SKIPPED_ALREADY_ATTEMPTED"} for r in results
        ):
            report["status"] = "COMPLETED"
    except ValueError as exc:
        if str(exc) not in PAUSE_CODES:
            report.update(status="INTERRUPTED", stop_reason="RUN_INTEGRITY_ERROR")
            raise
        report.update(status="PAUSED", stop_reason=str(exc))
    except Exception:
        report.update(status="INTERRUPTED", stop_reason="RUN_ERROR")
        raise
    finally:
        if worker is not None:
            queue.worker_heartbeat(worker.worker_id, stopped=True)
        report["executed_batches"] = performed
        raw = encoded(report)
        artifact = "current-image-run:" + sha256(raw).hexdigest()
        # Even a blocked execution records its state, but never starts a foreign job.
        preserve(records, artifact, raw, kind="CURRENT_SOURCE_IMAGE_RUN", parent=plan_id)
        atomic_local(
            output_dir / ("run-" + sha256(raw).hexdigest() + ".json"),
            encoded({"artifact_id": artifact, **report}) + b"\n",
        )
    return {"artifact_id": artifact, **report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--verify-input-only", action="store_true")
    args = parser.parse_args()
    audit = load_audit(args.audit_dir, args.summary_sha256)
    if args.verify_input_only:
        print(
            json.dumps(
                {
                    "input_verified": True,
                    "candidate_batches": len(audit["candidates"]),
                    "scope": SCOPE,
                }
            )
        )
        return
    if args.output_dir is None:
        parser.error("--output-dir is required for execution")
    settings = load_settings()
    records = Records(
        Database.from_settings(settings),
        FileStore((args.data_dir or settings.data_dir).resolve(strict=True)),
    )
    result = run(audit, records, args.output_dir, max_batches=args.max_batches)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] == "PAUSED" or result.get("stop_reason"):
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) else "CURRENT_IMAGE_RUN_FAILED"
        if re.fullmatch("[A-Z_]+", code) is None:
            code = "CURRENT_IMAGE_RUN_FAILED"
        print(json.dumps({"error": code, "exception_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
