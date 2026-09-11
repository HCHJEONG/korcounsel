"""Bounded artifact verification handler and restartable worker loop."""

import json
import logging
import signal
import threading
import time
from uuid import uuid4

from klegal_gold.assets.images import ImageAcquirer
from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.documents.legacy_batch import LegacyReaderBatch
from klegal_gold.documents.observe import observe_html
from klegal_gold.domain.identity import SourceSystem
from klegal_gold.ingestion.inventory import InventoryCapture, collect_inventory
from klegal_gold.sources.law_api import LawOpenApiCaseSource, Response
from klegal_gold.sources.persistence import preserve_response, save_detail
from klegal_gold.sources.scourt import ScourtPortalSource, listing_params

from .queue import Job, Queue

logger = logging.getLogger(__name__)


class CheckpointRequested(Exception):
    pass


class Worker:
    def __init__(self, queue: Queue, records: Records) -> None:
        self.queue, self.records = queue, records
        self.stop = threading.Event()
        self.worker_id = str(uuid4())
        self.legacy_readers = LegacyReaderBatch(records)

    def _verify(self, job: Job) -> None:
        blob = self.records.blob(job.payload["artifact_id"])
        last_beat = 0.0

        def progress(size: int) -> None:
            nonlocal last_beat
            now = time.monotonic()
            if now - last_beat >= self.queue.lease_seconds / 3 or self.stop.is_set():
                self.queue.worker_heartbeat(self.worker_id)
                self.queue.heartbeat(job, {"bytes_checked": size, "artifact_hash": blob.sha256})
                last_beat = now
                if self.stop.is_set() or self.queue.drain_status()["draining"]:
                    raise CheckpointRequested

        # A hash digest is not resumed from an unverified byte count; safely recheck from byte 0.
        self.records.store.verify(blob, progress)
        self.queue.heartbeat(job, {"verified_hash": blob.sha256, "bytes_checked": blob.size_bytes})

    def _rebuild(self, job: Job) -> None:
        def progress(last: str, count: int) -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job, {"last_artifact": last, "rows_in_attempt": count})
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        self.records.rebuild_projection(
            job_id=job.job_id,
            after_key=str(job.checkpoint.get("last_artifact", "")),
            progress=progress,
        )

    def _fetch_law(self, job: Job) -> None:
        settings = load_settings()
        credential = settings.law_api_credential
        if credential is None:
            raise ValueError("SOURCE_CREDENTIAL_UNAVAILABLE")

        def progress() -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        # No credential or arbitrary URL is accepted in the persistent job payload.
        def preserve(response: Response) -> None:
            preserve_response(self.records, response, str(job.job_id))

        source = LawOpenApiCaseSource(
            credential,
            preserve=preserve,
            progress=progress,
        )
        progress()
        detail = source.fetch_detail(job.payload["source_id"])
        progress()
        artifact_id = save_detail(self.records, detail, str(job.job_id))
        self.queue.heartbeat(job, {"artifact_id": artifact_id})

    def _fetch_scourt(self, job: Job) -> None:
        def progress() -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        def preserve(response: Response) -> None:
            preserve_response(self.records, response, str(job.job_id), SourceSystem.SCOURT)

        source = ScourtPortalSource(preserve=preserve, progress=progress)
        detail = source.fetch_detail(job.payload["source_id"])
        progress()
        artifact_id = save_detail(self.records, detail, str(job.job_id), SourceSystem.SCOURT)
        self.records.save_manifest(
            "scourt-document:" + artifact_id,
            "DOCUMENT_OBSERVATION",
            {
                "parent_artifact_id": artifact_id,
                "observation": observe_html(
                    detail.fields["body"]["orgdocXmlCtt"],
                    "https://portal.scourt.go.kr/",
                    scourt_id=detail.source_id,
                ),
            },
        )
        self.records.put_artifact(
            "scourt-acquisition:" + str(uuid4()),
            json.dumps(
                {
                    "run_id": str(job.job_id),
                    "source_id": detail.source_id,
                    "body_artifact": artifact_id,
                    "metadata_artifact": "http:" + detail.fields["metadata_response_hash"],
                    "collector_version": "scourt-portal-2",
                },
                sort_keys=True,
            ).encode(),
            origin="DERIVED",
            metadata={"kind": "SCOURT_ACQUISITION"},
            parent_id=artifact_id,
        )
        self.queue.heartbeat(job, {"artifact_id": artifact_id})

    def _inventory(self, job: Job) -> None:
        def progress() -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        def preserve(response: Response) -> None:
            preserve_response(self.records, response, str(job.job_id), SourceSystem.SCOURT)

        def save(capture: InventoryCapture) -> None:
            artifact_id = self.records.save_inventory(capture.snapshot)
            self.records.save_manifest(
                "inventory-pages:" + capture.snapshot.snapshot_id,
                "INVENTORY_PAGES",
                {
                    "job_id": str(job.job_id),
                    "snapshot_artifact": artifact_id,
                    "pages": capture.pages,
                },
            )
            self.queue.heartbeat(
                job,
                {
                    "snapshot_artifact": artifact_id,
                    "observed": capture.snapshot.observed_unique_count,
                },
            )

        query = job.payload["query"]
        display = job.payload["display"]
        source = ScourtPortalSource(preserve=preserve, progress=progress)
        # Every completed page is persisted. After interruption a new bounded observation
        # starts from page 1; a mutable provider result must not be spliced into an old snapshot.
        capture = collect_inventory(
            source,
            system=SourceSystem.SCOURT,
            scope=listing_params(query, 1, display),
            max_pages=job.payload["max_pages"],
            display=display,
            query=query,
            on_page=save,
        )
        save(capture)
        if capture.snapshot.failed_pages:
            raise ValueError("INVENTORY_PARTIAL_FAILURE")

    def _import_legacy(self, job: Job) -> None:
        from klegal_gold.ingestion.legacy_import import LegacyImporter

        def progress() -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        result = LegacyImporter(self.records).run(job, progress)
        self.queue.heartbeat(job, {"result_manifest": result})

    def _acquire_images(self, job: Job) -> None:
        def progress(checkpoint: dict[str, object]) -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job, checkpoint)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        result = ImageAcquirer(self.records).run(
            job,
            max_urls=job.payload["max_urls"],
            max_total_bytes=job.payload["max_total_bytes"],
            progress=progress,
        )
        self.queue.heartbeat(
            job,
            {
                "image_references": result.references,
                "image_urls_considered": result.urls_considered,
                "image_acquired": result.acquired,
                "image_skipped": result.skipped,
                "image_failed": result.failed,
                "image_bytes_stored": result.bytes_stored,
            },
        )

    def _stage_legacy_reader(self, job: Job) -> None:
        settings = load_settings()
        if settings.legacy_parquet_path is None:
            raise ValueError("LEGACY_PARQUET_UNAVAILABLE")
        last_beat = 0.0
        last_drain_check = 0.0

        def progress(checkpoint: dict[str, object]) -> None:
            nonlocal last_beat, last_drain_check
            now = time.monotonic()
            if self.stop.is_set():
                raise CheckpointRequested
            if now - last_beat >= min(10, self.queue.lease_seconds / 3):
                self.queue.worker_heartbeat(self.worker_id)
                self.queue.heartbeat(job, checkpoint)
                last_beat = now
            if now - last_drain_check >= 1:
                if self.queue.drain_status()["draining"]:
                    raise CheckpointRequested
                last_drain_check = now

        with self.queue.db.reuse_connections(), self.records.db.reuse_connections():
            result = self.legacy_readers.run(job, settings.legacy_parquet_path, progress)
            self.queue.heartbeat(job, {"result_manifest": result})

    def run_once(self) -> bool:
        if self.stop.is_set():
            return False
        job = self.queue.claim(self.worker_id)
        if job is None:
            return False
        try:
            if job.handler_version != (
                "legacy-reader-batch-1"
                if job.kind == "STAGE_LEGACY_READER_BATCH"
                else "legacy-import-1"
                if job.kind == "IMPORT_LEGACY_BUNDLE"
                else (
                    "asset-1"
                    if job.kind == "ACQUIRE_IMAGE_BATCH"
                    else ("source-1" if job.kind.startswith("FETCH_") else "persistence-1")
                )
            ):
                raise ValueError("UNSUPPORTED_HANDLER_VERSION")
            if job.kind == "STAGE_LEGACY_READER_BATCH":
                self._stage_legacy_reader(job)
            elif job.kind == "IMPORT_LEGACY_BUNDLE":
                self._import_legacy(job)
            elif job.kind == "VERIFY_ARTIFACT":
                self._verify(job)
            elif job.kind == "REBUILD_PROJECTION":
                self._rebuild(job)
            elif job.kind == "FETCH_LAW_DETAIL":
                self._fetch_law(job)
            elif job.kind == "FETCH_SCOURT_DETAIL":
                self._fetch_scourt(job)
            elif job.kind == "FETCH_SCOURT_INVENTORY":
                self._inventory(job)
            elif job.kind == "ACQUIRE_IMAGE_BATCH":
                self._acquire_images(job)
            else:
                raise ValueError("UNKNOWN_JOB_KIND")
            self.queue.finish(job, outcome="SUCCEEDED")
        except CheckpointRequested:
            self.queue.finish(job, outcome="CHECKPOINTED")
        except (OSError, ValueError):
            # A stale worker must never mark another owner's attempt failed.
            try:
                self.queue.finish(
                    job,
                    outcome="FAILED",
                    error_code=(
                        "HANDLER_FAILED"
                        if job.kind.startswith("FETCH_") or job.kind == "ACQUIRE_IMAGE_BATCH"
                        else "ARTIFACT_INTEGRITY_FAILED"
                    ),
                )
            except ValueError:
                logger.warning("Worker lease lost; result not committed")
        return True

    def run(self) -> None:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
            signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        try:
            while not self.stop.is_set():
                self.queue.worker_heartbeat(self.worker_id)
                if not self.run_once():
                    self.stop.wait(1)
        finally:
            self.queue.worker_heartbeat(self.worker_id, stopped=True)
