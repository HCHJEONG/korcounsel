"""Drive bounded source, reader, image and reader-refresh waves using existing jobs."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from prepare_legacy_image_sources import prepare
from run_legacy_reader_batches import encoded, make_plan, run_owned_job, run_plan

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

INVENTORY_SHA256 = "d5effca374825cf877b8710e35442b7105439bf83424d7005dfcc3855e79e990"
VERSION = "legacy-image-waves-1"


class WaveStopped(ValueError):
    """A preserved partial wave must not start its next phase."""


def stop_code(exc):
    if isinstance(exc, WaveStopped) or str(exc) in {
        "ANOTHER_WORKER_JOB_ACTIVE",
        "RUNTIME_DRAINING",
    }:
        return str(exc)
    return "WAVE_PHASE_FAILED"


def load_targets(targets, inventory, *, expected_hash=INVENTORY_SHA256):
    raw = inventory.read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != expected_hash:
        raise ValueError("IMAGE_INVENTORY_HASH_MISMATCH")
    all_rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    indexed = {row["position"]: row for row in all_rows}
    if len(indexed) != len(all_rows):
        raise ValueError("DUPLICATE_INVENTORY_POSITION")
    target_raw = targets.read_bytes()
    selected = json.loads(target_raw)["rows"]
    positions = [row["position"] for row in selected]
    if (
        not positions
        or any(type(p) is not int or p < 0 for p in positions)
        or len(set(positions)) != len(positions)
    ):
        raise ValueError("INVALID_IMAGE_TARGET_POSITIONS")
    fields = ("position", "source_id", "source_id_usable", "body_hash", "snapshot_sha256")
    for row in selected:
        original = indexed.get(row["position"])
        if original is None or any(row.get(k) != original.get(k) for k in fields):
            raise ValueError("IMAGE_TARGET_INVENTORY_MISMATCH")
    return selected, {"inventory_sha256": digest, "targets_sha256": sha256(target_raw).hexdigest()}


def source_waves(rows, *, sources_per_wave=100):
    if type(sources_per_wave) is not int or not 1 <= sources_per_wave <= 100:
        raise ValueError("INVALID_WAVE_SIZE")
    grouped = {}
    for row in sorted(rows, key=lambda row: row["position"]):
        if row.get("source_id_usable"):
            source = row["source_id"]
            if not isinstance(source, str) or not source:
                raise ValueError("INVALID_USABLE_SOURCE_ID")
            grouped.setdefault(source, []).append(row)
    groups = list(grouped.values())
    return [
        groups[offset : offset + sources_per_wave]
        for offset in range(0, len(groups), sources_per_wave)
    ]


def split_download_references(refs, *, max_urls=500):
    """Partition by URL, retaining every repeated occurrence and unresolved ref."""
    if type(max_urls) is not int or not 1 <= max_urls <= 500:
        raise ValueError("INVALID_DOWNLOAD_URL_LIMIT")
    groups = {}
    for index, ref in enumerate(refs):
        url = ref.get("resolved_url")
        key = url if isinstance(url, str) and url else (None, index)
        groups.setdefault(key, []).append(ref)
    chunks, current, urls = [], [], 0
    for key, group in groups.items():
        if isinstance(key, str) and urls == max_urls:
            chunks.append(current)
            current, urls = [], 0
        current.extend(group)
        urls += int(isinstance(key, str))
    if current:
        chunks.append(current)
    return chunks


def save_phase(records, directory, label, value):
    """An existing local receipt is never a skip marker."""
    raw = encoded(value)
    digest = sha256(raw).hexdigest()
    artifact = "legacy-image-wave:" + digest
    records.put_artifact(
        artifact, raw, origin="MANIFEST", metadata={"kind": "LEGACY_IMAGE_WAVE_RECEIPT"}
    )
    if records.read(artifact) != raw:
        raise ValueError("WAVE_RECEIPT_MISMATCH")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (label + "-" + digest + ".json")
    output = encoded({"artifact_id": artifact, **value}) + b"\n"
    try:
        with target.open("xb") as stream:
            stream.write(output)
    except FileExistsError:
        if target.read_bytes() != output:
            raise ValueError("LOCAL_WAVE_RECEIPT_MISMATCH") from None
    return artifact


def checkpoint(records, directory, wave):
    wave["receipt_artifact"] = save_phase(records, directory, "wave", wave)


def ensure_ready(records, queue, *, owned_keys=()):
    if queue.drain_status()["draining"]:
        raise WaveStopped("RUNTIME_DRAINING")
    with records.db.connect() as conn:
        foreign = conn.execute(
            "SELECT 1 FROM jobs WHERE status IN ('QUEUED','RUNNING') "
            "AND NOT (request_key=ANY(%s)) LIMIT 1",
            (list(owned_keys),),
        ).fetchone()
    if foreign:
        raise WaveStopped("ANOTHER_WORKER_JOB_ACTIVE")


def stage_details(records, queue, pointer, report):
    """Read actual job/result artifacts again, including reused successful jobs."""
    plan = json.loads(records.read(pointer["plan_artifact_id"]))
    if report["plan_artifact_id"] != pointer["plan_artifact_id"]:
        raise ValueError("WAVE_PLAN_MISMATCH")
    rows, pending, stop = [], [], None
    if len(report["results"]) != len(plan["batches"]):
        stop = "STAGE_INCOMPLETE"
    for batch, receipt in zip(plan["batches"], report["results"], strict=False):
        job = queue.get(receipt["job_id"])
        if (
            receipt["positions"] != batch["positions"]
            or job.payload.get("manifest_artifact_id") != batch["manifest_artifact_id"]
            or job.status != receipt["status"]
        ):
            raise ValueError("WAVE_JOB_MISMATCH")
        if job.status != "SUCCEEDED":
            stop = "STAGE_JOB_" + job.status
            continue
        result = json.loads(records.read(job.checkpoint["result_manifest"]))
        if (
            result["input_manifest"] != batch["manifest_artifact_id"]
            or result["parquet_sha256"] != plan["parquet_sha256"]
            or result["snapshot_sha256"] != plan["snapshot_sha256"]
            or sorted(row["position"] for row in result["rows"]) != sorted(batch["positions"])
        ):
            raise ValueError("WAVE_RESULT_MISMATCH")
        rows.extend(result["rows"])
        pending.extend(json.loads(records.read(result["download_manifest"]))["references"])
    return {"rows": rows, "pending": pending, "stop_reason": stop}


def run_stage(records, queue, path, mapping, retry_generation, directory, label, wave):
    saved = wave.get(label)
    if saved and saved.get("run"):
        details = stage_details(records, queue, saved["plan"], saved["run"])
        if details["stop_reason"] is None:
            saved.update(details)
            return details
    pointer = (
        saved["plan"]
        if saved
        else make_plan(
            path,
            records,
            positions=sorted(int(p) for p in mapping),
            current_readers=mapping,
            batch_size=100,
            retry_generation=retry_generation,
        )
    )
    wave[label] = {"plan": pointer}
    checkpoint(records, directory, wave)
    plan = json.loads(records.read(pointer["plan_artifact_id"]))
    keys = ["reader-stage:" + b["manifest_artifact_id"].split(":", 1)[1] for b in plan["batches"]]
    ensure_ready(records, queue, owned_keys=keys)
    report = run_plan(records, pointer, max_batches=len(plan["batches"]))
    wave[label]["run"] = report
    details = stage_details(records, queue, pointer, report)
    wave[label].update(details)
    checkpoint(records, directory, wave)
    if details["stop_reason"]:
        raise WaveStopped(details["stop_reason"])
    return details


def run_downloads(records, queue, refs, directory, wave, retry_generation):
    worker = Worker(queue, records)
    try:
        for index, chunk in enumerate(split_download_references(refs)):
            payload = {"references": chunk, "retry_generation": retry_generation}
            raw = encoded(payload)
            digest = sha256(raw).hexdigest()
            artifact = "image-manifest:legacy-wave-" + digest
            key = "legacy-wave-image:" + digest
            records.put_artifact(
                artifact, raw, origin="MANIFEST", metadata={"kind": "IMAGE_REFERENCE_MANIFEST"}
            )
            existing = wave["downloads"][index] if index < len(wave["downloads"]) else None
            if existing and existing["manifest_artifact_id"] != artifact:
                raise ValueError("WAVE_DOWNLOAD_MISMATCH")
            job = queue.get(existing["job_id"]) if existing else None
            if job is None or job.status != "SUCCEEDED":
                ensure_ready(records, queue, owned_keys=[key])
            job = queue.submit_image_batch(key, artifact, max_urls=500)
            receipt = {
                "manifest_artifact_id": artifact,
                "job_id": str(job.job_id),
                "references": len(chunk),
                "unique_urls": len({r["resolved_url"] for r in chunk if r.get("resolved_url")}),
                "status": job.status,
            }
            if existing:
                wave["downloads"][index] = receipt
            else:
                wave["downloads"].append(receipt)
            checkpoint(records, directory, wave)
            job = run_owned_job(records, queue, worker, job)
            receipt.update(status=job.status, checkpoint=job.checkpoint)
            checkpoint(records, directory, wave)
            if job.status != "SUCCEEDED":
                raise WaveStopped("DOWNLOAD_JOB_" + job.status)
    finally:
        queue.worker_heartbeat(worker.worker_id, stopped=True)


def run_waves(
    records,
    path,
    rows,
    input_hashes,
    output_dir,
    *,
    max_waves=1,
    start_wave=1,
    sources_per_wave=100,
    retry_generation=0,
    resume_wave=None,
):
    if (
        type(max_waves) is not int
        or max_waves < 1
        or type(start_wave) is not int
        or start_wave < 1
        or type(retry_generation) is not int
        or retry_generation < 0
    ):
        raise ValueError("INVALID_WAVE_LIMIT")
    waves = source_waves(rows, sources_per_wave=sources_per_wave)
    resumed = json.loads(records.read(resume_wave)) if resume_wave else None
    contract = {
        "version": VERSION,
        **input_hashes,
        "sources_per_wave": sources_per_wave,
        "retry_generation": retry_generation,
    }
    if resumed:
        if any(resumed.get(k) != v for k, v in contract.items()):
            raise ValueError("WAVE_RESUME_INPUT_MISMATCH")
        if start_wave not in {1, resumed["wave"]}:
            raise ValueError("WAVE_RESUME_POSITION_MISMATCH")
        start_wave = resumed["wave"]
    if start_wave > len(waves):
        raise ValueError("WAVE_START_OUTSIDE_TARGETS")
    report = {
        **contract,
        "start_wave": start_wave,
        "max_waves": max_waves,
        "total_waves": len(waves),
        "unusable_rows": [
            {"position": r["position"], "source_id": r["source_id"], "status": "SOURCE_ID_UNUSABLE"}
            for r in rows
            if not r.get("source_id_usable")
        ],
        "waves": [],
        "status": "RUNNING",
    }
    queue = Queue(records.db, lease_seconds=300)
    consecutive = 0
    try:
        for number in range(start_wave, min(len(waves), start_wave + max_waves - 1) + 1):
            groups = waves[number - 1]
            directory = output_dir / f"wave-{number:03d}"
            sources = [group[0]["source_id"] for group in groups]
            positions = [row["position"] for group in groups for row in group]
            wave = (
                resumed
                if resumed and number == start_wave
                else {
                    **contract,
                    "wave": number,
                    "sources": sources,
                    "positions": positions,
                    "source_results": [],
                    "current_readers": {},
                    "downloads": [],
                }
            )
            if wave["sources"] != sources or wave["positions"] != positions:
                raise ValueError("WAVE_RESUME_SELECTION_MISMATCH")
            wave["status"] = "RUNNING"
            wave.pop("stop_reason", None)
            report["waves"].append(wave)
            try:
                saved_sources = {r["source_id"]: r for r in wave["source_results"]}
                for source_index, group in enumerate(groups, start=1):
                    source = group[0]["source_id"]
                    if source in saved_sources:
                        item = saved_sources[source]
                        prepared = json.loads(records.read(item["receipt_artifact"]))
                        original = prepared["results"][0]
                        if any(item[k] != v for k, v in original.items()):
                            raise ValueError("WAVE_SOURCE_RECEIPT_MISMATCH")
                        if original.get("current_reader"):
                            ReaderStore(records).read(original["current_reader"])
                    else:
                        key = (
                            "legacy-image-source:" + input_hashes["inventory_sha256"] + ":" + source
                        )
                        ensure_ready(records, queue, owned_keys=[key])
                        prepared = prepare(
                            records,
                            group,
                            inventory_hash=input_hashes["inventory_sha256"],
                            max_sources=1,
                        )
                        source_artifact = save_phase(records, directory, "source", prepared)
                        for item in prepared["results"]:
                            wave["source_results"].append(
                                {**item, "receipt_artifact": source_artifact}
                            )
                        wave["current_readers"].update(prepared["current_readers"])
                        checkpoint(records, directory, wave)
                    print(
                        json.dumps(
                            {
                                "phase": "SOURCE",
                                "wave": number,
                                "source_in_wave": source_index,
                                "sources_in_wave_total": len(groups),
                                "global_source_done": sum(len(w) for w in waves[: number - 1])
                                + source_index,
                                "global_source_total": sum(len(w) for w in waves),
                                "waves_total": len(waves),
                            }
                        ),
                        flush=True,
                    )
                    if len(prepared["results"]) != 1:
                        raise WaveStopped("SOURCE_PREPARATION_INCOMPLETE")
                    item = prepared["results"][0]
                    if (
                        item["source_id"] != source
                        or sorted(item["positions"]) != sorted(r["position"] for r in group)
                        or not set(prepared["current_readers"])
                        <= {str(r["position"]) for r in group}
                    ):
                        raise ValueError("WAVE_SOURCE_SELECTION_MISMATCH")
                    status = item["status"]
                    consecutive = (
                        consecutive + 1
                        if status in {"SOURCE_FETCH_FAILED", "CURRENT_STRUCTURE_UNCONFIRMED"}
                        else 0
                    )
                    if consecutive >= 3:
                        raise WaveStopped("CONSECUTIVE_SOURCE_STRUCTURE_FAILURES")
                mapping = wave["current_readers"]
                if mapping:
                    staged = run_stage(
                        records, queue, path, mapping, retry_generation, directory, "stage", wave
                    )
                    run_downloads(
                        records, queue, staged["pending"], directory, wave, retry_generation
                    )
                    run_stage(
                        records, queue, path, mapping, retry_generation, directory, "restage", wave
                    )
                wave["status"] = "COMPLETED"
            except WaveStopped as exc:
                wave.update(status="INCOMPLETE", stop_reason=str(exc))
                raise
            finally:
                final_rows = {
                    row["position"]: row
                    for row in wave.get("restage", wave.get("stage", {})).get("rows", [])
                }
                source_rows = {
                    p: item["status"] for item in wave["source_results"] for p in item["positions"]
                }
                wave["row_results"] = [
                    final_rows.get(
                        p, {"position": p, "status": source_rows.get(p, "NOT_PROCESSED")}
                    )
                    for p in wave["positions"]
                ]
                if wave["status"] == "RUNNING":
                    wave["status"] = "INCOMPLETE"
                checkpoint(records, directory, wave)
            print(json.dumps({"wave": number, "status": wave["status"]}), flush=True)
        report["status"] = "COMPLETED" if start_wave + max_waves > len(waves) else "BOUNDED"
    except (ValueError, OSError, KeyError) as exc:
        report["status"] = "PAUSED"
        report["stop_reason"] = stop_code(exc)
    finally:
        report["report_artifact_id"] = save_phase(records, output_dir, "run", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-waves", type=int, default=1)
    parser.add_argument("--start-wave", type=int, default=1)
    parser.add_argument("--sources-per-wave", type=int, default=100)
    parser.add_argument("--retry-generation", type=int, default=0)
    parser.add_argument(
        "--resume-wave", help="Immutable wave receipt artifact ID, not a local file"
    )
    args = parser.parse_args()
    rows, hashes = load_targets(args.targets, args.inventory)
    settings = load_settings()
    if settings.legacy_parquet_path is None:
        parser.error("LEGACY_PARQUET_PATH is required")
    records = Records(Database.from_settings(settings), FileStore(settings.data_dir))
    result = run_waves(
        records,
        settings.legacy_parquet_path,
        rows,
        hashes,
        args.output_dir,
        max_waves=args.max_waves,
        start_wave=args.start_wave,
        sources_per_wave=args.sources_per_wave,
        retry_generation=args.retry_generation,
        resume_wave=args.resume_wave,
    )
    print(json.dumps({k: v for k, v in result.items() if k not in {"waves", "unusable_rows"}}))
    return 2 if result["status"] == "PAUSED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
