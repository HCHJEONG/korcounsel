"""Bounded artifact verification handler and restartable worker loop."""

import json
import logging
import signal
import threading
import time
from uuid import UUID, uuid4

from klegal_gold.assets.images import ImageAcquirer, valid_scourt_image_url
from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.documents.legacy_batch import LegacyReaderBatch
from klegal_gold.documents.observe import observe_html
from klegal_gold.documents.reader_store import ReaderStore
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
        self.readers = ReaderStore(records)

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

    def _retry_current_images(self, job: Job) -> None:
        self._submit_reader_images(job, job.payload["document_id"])

    def _submit_reader_images(self, job: Job, document_id: str) -> None:
        from klegal_gold.assets.images import valid_lawgo_image_url

        manifest = self.readers.read(document_id)
        if manifest["origin"] != "CURRENT_SOURCE" or not (
            manifest["images"] or manifest.get("statute_images")
        ):
            raise ValueError("CURRENT_READER_IMAGES_REQUIRED")
        references = []
        for ref in manifest["images"] + manifest.get("statute_images", []):
            if job.payload.get("transient_only"):
                from klegal_gold.quality.checks import transient

                if ref["status"] == "ACQUIRED" or not transient(
                    str(ref.get("acquisition", {}).get("error", ""))
                ):
                    continue
            url = ref.get("resolved_url")
            statute = "article_reference_id" in ref
            resolved = isinstance(url, str) and (
                valid_lawgo_image_url(url) if statute else valid_scourt_image_url(url)
            )
            references.append(
                {
                    **ref,
                    "source_system": "law_go_kr" if statute else "scourt",
                    "source_id": ref.get("source_id", "") if statute else manifest["source_id"],
                    "reader_document_id": document_id,
                    "image_name": ref.get("name"),
                    "resolved_url": url if resolved else None,
                    "reference_status": "RESOLVED" if resolved else "UNRESOLVED",
                    "reason": "explicit retry of preserved provider mapping",
                }
            )
        artifact_id = (
            "image-manifest:reader-retry:"
            + document_id
            + (":transient" if job.payload.get("transient_only") else "")
        )
        self.records.put_artifact(
            artifact_id,
            json.dumps({"references": references}, sort_keys=True).encode(),
            origin="MANIFEST",
            metadata={},
        )
        image_job = self.queue.submit_image_batch(
            "image-retry:" + str(job.job_id), artifact_id, all_urls=True
        )
        refresh = self.queue.submit_current_reader_refresh(document_id, image_job.job_id)
        if job.payload.get("transient_only"):
            fields = self.queue.submit_case_fields(document_id, refresh.job_id)
            self.queue.heartbeat(
                job, {**self.queue.get(job.job_id).checkpoint, "fields_job_id": str(fields.job_id)}
            )
        self.queue.heartbeat(
            job,
            {
                **self.queue.get(job.job_id).checkpoint,
                "image_job_id": str(image_job.job_id),
                "follow_up_job_id": str(refresh.job_id),
            },
        )

    def _build_legacy_search(self, job: Job) -> None:
        from klegal_gold.search.index import LegacySearchIndex

        path = load_settings().legacy_parquet_path
        if path is None:
            raise ValueError("LEGACY_PARQUET_UNAVAILABLE")
        last_beat = 0.0

        def progress(checkpoint: dict[str, object]) -> None:
            nonlocal last_beat
            now = time.monotonic()
            if now - last_beat > 5 or checkpoint.get("phase") == "READY":
                self.queue.worker_heartbeat(self.worker_id)
                self.queue.heartbeat(job, checkpoint)
                last_beat = now
                if self.stop.is_set() or self.queue.drain_status()["draining"]:
                    raise CheckpointRequested

        self.readers.rebuild_current_search(progress)
        LegacySearchIndex(self.queue.db).build(path, job.payload["snapshot_key"], progress)

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
        if job.checkpoint.get("reader_document_id"):
            self._submit_current_images(job, job.checkpoint)
            return

        def progress() -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        def preserve(response: Response) -> None:
            preserve_response(self.records, response, str(job.job_id), SourceSystem.SCOURT)

        if job.payload.get("preserved_job_id"):
            from klegal_gold.sources.scourt_replay import PreservedScourtTransport

            original = self.queue.get(UUID(job.payload["preserved_job_id"]))
            if (
                original.kind != "FETCH_SCOURT_DETAIL"
                or original.payload["source_id"] != job.payload["source_id"]
            ):
                raise ValueError("SCOURT_REPLAY_SOURCE_MISMATCH")
            source = ScourtPortalSource(
                transport=PreservedScourtTransport(self.records, original),
                preserve=preserve,
                progress=progress,
            )
        else:
            source = ScourtPortalSource(preserve=preserve, progress=progress)
        detail = source.fetch_detail(job.payload["source_id"])
        progress()
        artifact_id = save_detail(self.records, detail, str(job.job_id), SourceSystem.SCOURT)
        body_html = detail.fields["body"]["orgdocXmlCtt"]
        metadata = detail.fields
        title = (
            " ".join(
                value
                for value in (
                    metadata.get("cortNm"),
                    metadata.get("prnjdgYmd"),
                    metadata.get("csNoLstCtt"),
                    metadata.get("adjdTypNm"),
                )
                if isinstance(value, str) and value.strip()
            )
            or f"scourt {detail.source_id}"
        )
        reader_document_id = self.readers.preserve(
            body_html,
            title=title,
            source_id=detail.source_id,
            origin="CURRENT_SOURCE",
            provenance={
                "source_artifact_id": artifact_id,
                "metadata_response_hash": metadata["metadata_response_hash"],
                "job_id": str(job.job_id),
                "court": metadata.get("cortNm"),
                "case_number": metadata.get("csNoLstCtt"),
                "full_case_number": metadata.get("mrgCsNoCtt"),
                "decision_date": metadata.get("prnjdgYmd"),
                "decision_type": metadata.get("adjdTypNm"),
            },
            acquisitions={},
        )
        observation = observe_html(
            body_html, "https://portal.scourt.go.kr/", scourt_id=detail.source_id
        )
        self.records.save_manifest(
            "scourt-document:" + artifact_id + ":reader:" + reader_document_id,
            "DOCUMENT_OBSERVATION",
            {
                "parent_artifact_id": artifact_id,
                "reader_document_id": reader_document_id,
                "observation": observation,
            },
        )
        references = []
        for reference in observation["images"]:
            url = reference.get("resolved_url")
            resolved = isinstance(url, str) and valid_scourt_image_url(url)
            references.append(
                {
                    **reference,
                    "source_system": "scourt",
                    "source_id": detail.source_id,
                    "reference_status": "RESOLVED" if resolved else "UNRESOLVED",
                    "reason": "Observed current scourt image URL"
                    if resolved
                    else "No validated current scourt image URL",
                    "reader_document_id": reader_document_id,
                }
            )
        image_manifest_id = None
        if references:
            from hashlib import sha256

            raw = json.dumps({"references": references}, sort_keys=True).encode()
            image_manifest_id = "image-manifest:current-reader-" + sha256(raw).hexdigest()
            self.records.put_artifact(
                image_manifest_id,
                raw,
                origin="MANIFEST",
                metadata={
                    "kind": "IMAGE_REFERENCE_MANIFEST",
                    "reader_document_id": reader_document_id,
                },
                parent_id=artifact_id,
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
        checkpoint: dict[str, object] = {
            "artifact_id": artifact_id,
            "reader_document_id": reader_document_id,
            "image_manifest_id": image_manifest_id,
        }
        self.queue.heartbeat(job, checkpoint)
        self._submit_current_images(job, checkpoint)

    def _submit_current_images(self, job: Job, checkpoint: dict[str, object]) -> None:
        checkpoint = dict(checkpoint)
        if checkpoint.get("image_manifest_id"):
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested
            image_job = self.queue.submit_image_batch(
                "current-reader-images:" + str(job.job_id),
                str(checkpoint["image_manifest_id"]),
                all_urls=True,
            )
            refresh_job = self.queue.submit_current_reader_refresh(
                str(checkpoint["reader_document_id"]), image_job.job_id
            )
            checkpoint.update(
                image_job_id=str(image_job.job_id), reader_refresh_job_id=str(refresh_job.job_id)
            )
        dependency_id = (
            UUID(str(checkpoint["reader_refresh_job_id"]))
            if checkpoint.get("reader_refresh_job_id")
            else job.job_id
        )
        lawgo = self.queue.submit_current_lawgo(
            str(checkpoint["reader_document_id"]), dependency_id
        )
        checkpoint["lawgo_job_id"] = str(lawgo.job_id)
        fields = self.queue.submit_case_fields(str(checkpoint["reader_document_id"]), lawgo.job_id)
        checkpoint["fields_job_id"] = str(fields.job_id)
        self.queue.heartbeat(job, checkpoint)

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
        from klegal_gold.sources.scourt import window_params

        date_from, date_to = job.payload.get("date_from"), job.payload.get("date_to")
        source = ScourtPortalSource(
            preserve=preserve, progress=progress, date_from=date_from, date_to=date_to
        )
        scope = (
            window_params(query, 1, display, date_from, date_to)
            if date_from and date_to
            else listing_params(query, 1, display)
        )
        # Every completed page is persisted. After interruption a new bounded observation
        # starts from page 1; a mutable provider result must not be spliced into an old snapshot.
        capture = collect_inventory(
            source,
            system=SourceSystem.SCOURT,
            scope=scope,
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
        if job.payload.get("all_urls"):
            saved = self.queue.get(job.job_id).checkpoint
            if saved.get("image_next_url", 0) < saved.get("image_urls_total", 0):
                raise CheckpointRequested
        self.queue.heartbeat(
            job,
            {
                **self.queue.get(job.job_id).checkpoint,
                "image_references": result.references,
                "image_urls_considered": result.urls_considered,
                "image_acquired": result.acquired,
                "image_skipped": result.skipped,
                "image_failed": result.failed,
                "image_bytes_stored": result.bytes_stored,
            },
        )

    def _enrich_current_lawgo(self, job: Job) -> None:
        from klegal_gold.enrichment.current_lawgo import CurrentLawgo

        dependency = self.queue.get(UUID(job.payload["dependency_id"]))
        if dependency.status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("LAWGO_DEPENDENCY_NOT_TERMINAL")
        expected = dependency.payload.get("document_id") or dependency.checkpoint.get(
            "reader_document_id"
        )
        requested = self.readers.read(job.payload["document_id"])
        root = requested["provenance"].get("current_root_document_id", job.payload["document_id"])
        if expected != root:
            raise ValueError("LAWGO_DEPENDENCY_MISMATCH")
        document_id = (
            dependency.checkpoint.get("reader_document_id")
            if dependency.status == "SUCCEEDED"
            else None
        )
        document_id = document_id or job.payload["document_id"]
        if job.payload["document_id"] != root:
            document_id = job.payload["document_id"]

        def progress() -> None:
            self.queue.worker_heartbeat(self.worker_id)
            self.queue.heartbeat(job)
            if self.stop.is_set() or self.queue.drain_status()["draining"]:
                raise CheckpointRequested

        revision = job.checkpoint.get("reader_document_id")
        if not revision:
            if job.payload.get("transient_only"):
                revision = CurrentLawgo(self.records).run(
                    document_id, str(job.job_id), progress, transient_only=True
                )
            else:
                revision = CurrentLawgo(self.records).run(document_id, str(job.job_id), progress)
            self.queue.heartbeat(job, {"reader_document_id": revision})
        if self.readers.read(revision).get("statute_images"):
            self._submit_reader_images(job, revision)
        self.queue.heartbeat(
            job,
            {
                **self.queue.get(job.job_id).checkpoint,
                "reader_document_id": revision,
                "lawgo_status": self.readers.read(revision)["provenance"]["lawgo_status"],
            },
        )

    def _build_case_fields(self, job: Job) -> None:
        from klegal_gold.fields.store import FieldStore

        document_id = job.payload["document_id"]
        if job.payload.get("dependency_id"):
            dependency = self.queue.get(UUID(job.payload["dependency_id"]))
            if dependency.status not in {"SUCCEEDED", "FAILED"}:
                raise ValueError("FIELDS_DEPENDENCY_NOT_TERMINAL")
            requested = self.readers.read(document_id)
            expected = self.readers.read(dependency.payload["document_id"])
            if requested["provenance"].get("current_root_document_id", document_id) != expected[
                "provenance"
            ].get("current_root_document_id", dependency.payload["document_id"]):
                raise ValueError("FIELDS_DEPENDENCY_MISMATCH")
            document_id = dependency.checkpoint.get("reader_document_id", document_id)
            if dependency.checkpoint.get("follow_up_job_id"):
                follow = self.queue.get(UUID(dependency.checkpoint["follow_up_job_id"]))
                if follow.status not in {"SUCCEEDED", "FAILED"}:
                    raise ValueError("FIELDS_DEPENDENCY_NOT_TERMINAL")
                document_id = follow.checkpoint.get("reader_document_id", document_id)
        with self.records.db.connect() as conn:
            row = conn.execute(
                "SELECT created_at FROM jobs WHERE job_id=%s", (job.job_id,)
            ).fetchone()
        assert row is not None
        payload = FieldStore(self.records).build(document_id, row["created_at"].isoformat())
        self.queue.heartbeat(
            job,
            {
                "reader_document_id": document_id,
                "fields_revision": payload["revision"],
                "fields_state": payload["state"],
                "field_counts": payload["counts"],
            },
        )

    def _refresh_current_reader_images(self, job: Job) -> None:
        dependency = self.queue.get(UUID(job.payload["image_job_id"]))
        if dependency.kind != "ACQUIRE_IMAGE_BATCH" or dependency.status not in {
            "SUCCEEDED",
            "FAILED",
        }:
            raise ValueError("READER_DEPENDENCY_NOT_TERMINAL")
        document_id = job.payload["document_id"]
        payload = json.loads(self.records.read(dependency.payload["manifest_artifact_id"]))
        if not any(
            isinstance(ref, dict) and ref.get("reader_document_id") == document_id
            for ref in payload.get("references", [])
        ):
            raise ValueError("READER_DEPENDENCY_MISMATCH")
        self.queue.heartbeat(job, {"phase": "REFRESHING", "image_job_status": dependency.status})
        revision = self.readers.refresh_current_images(document_id)
        self.queue.heartbeat(
            job,
            {
                "phase": "PUBLISHED",
                "image_job_status": dependency.status,
                "reader_document_id": revision,
                "previous_reader_document_id": document_id,
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
            if job.kind == "AUDIT_CURRENT_QUALITY":
                from klegal_gold.quality.service import audit

                audit(self, job)
            elif job.kind == "REPROCESS_QUALITY":
                from klegal_gold.quality.service import dispatch

                dispatch(self, job)
            elif job.kind == "STAGE_LEGACY_READER_BATCH":
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
            elif job.kind == "BUILD_CASE_FIELDS":
                self._build_case_fields(job)
            elif job.kind == "ENRICH_CURRENT_LAWGO":
                self._enrich_current_lawgo(job)
            elif job.kind == "REFRESH_CURRENT_READER_IMAGES":
                self._refresh_current_reader_images(job)
            elif job.kind == "RETRY_CURRENT_IMAGES":
                self._retry_current_images(job)
            elif job.kind == "CREATE_BACKUP":
                from klegal_gold.jobs.backup import run_backup

                run_backup(self, job)
            elif job.kind == "BUILD_LEGACY_SEARCH":
                self._build_legacy_search(job)
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
