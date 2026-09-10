"""Bounded artifact verification handler and restartable worker loop."""

import logging
import signal
import threading
import time
from uuid import uuid4

from klegal_gold.db.records import Records

from .queue import Job, Queue

logger = logging.getLogger(__name__)


class CheckpointRequested(Exception):
    pass


class Worker:
    def __init__(self, queue: Queue, records: Records) -> None:
        self.queue, self.records = queue, records
        self.stop = threading.Event()
        self.worker_id = str(uuid4())

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

    def run_once(self) -> bool:
        if self.stop.is_set():
            return False
        job = self.queue.claim(self.worker_id)
        if job is None:
            return False
        try:
            if job.handler_version != "persistence-1":
                raise ValueError("UNSUPPORTED_HANDLER_VERSION")
            if job.kind == "VERIFY_ARTIFACT":
                self._verify(job)
            elif job.kind == "REBUILD_PROJECTION":
                self._rebuild(job)
            else:
                raise ValueError("UNKNOWN_JOB_KIND")
            self.queue.finish(job, outcome="SUCCEEDED")
        except CheckpointRequested:
            self.queue.finish(job, outcome="CHECKPOINTED")
        except (OSError, ValueError):
            # A stale worker must never mark another owner's attempt failed.
            try:
                self.queue.finish(job, outcome="FAILED", error_code="ARTIFACT_INTEGRITY_FAILED")
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
