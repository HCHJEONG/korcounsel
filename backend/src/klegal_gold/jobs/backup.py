"""Explicit administrator backup; partial attempts never masquerade as complete bundles."""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from psycopg.conninfo import conninfo_to_dict

from klegal_gold.config import load_settings
from klegal_gold.storage.backup import create_backup, verify_backup

if TYPE_CHECKING:
    from klegal_gold.jobs.queue import Job
    from klegal_gold.jobs.worker import Worker


def dump_snapshot(worker: "Worker", snapshot: str, path: Path, progress: Any) -> None:
    # Password stays in the child environment, never argv or captured diagnostics.
    with worker.queue.db.connect() as conn:
        info = conninfo_to_dict(conn.info.dsn)
        # Psycopg deliberately strips the password from ConnectionInfo.dsn.
        # Use the established libpq connection, and pass it only in the child environment.
        password = conn.pgconn.password.decode("utf-8")
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    env["PGDATABASE"] = str(info.pop("dbname"))
    for key, value in info.items():
        if key != "options" and value is not None:
            env["PG" + key.upper()] = str(value)
    env.pop("PGOPTIONS", None)
    cmd = [
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-privileges",
        "--no-password",
        "--schema=" + worker.queue.db.schema,
        "--snapshot=" + snapshot,
    ]
    with path.open("xb") as saved:
        with subprocess.Popen(cmd, env=env, stdout=saved, stderr=subprocess.DEVNULL) as process:
            try:
                started = time.monotonic()
                while process.poll() is None:
                    progress({"phase": "DUMPING"})
                    if time.monotonic() - started > 12 * 3600:
                        raise ValueError("BACKUP_DUMP_TIMEOUT")
                    time.sleep(1)
                if process.returncode:
                    raise ValueError("BACKUP_DUMP_FAILED")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


def run_backup(worker: "Worker", job: "Job") -> None:
    from klegal_gold.jobs.worker import CheckpointRequested

    settings = load_settings()
    root = settings.backup_dir
    if root is None or not root.is_absolute() or root.is_symlink():
        raise ValueError("BACKUP_NOT_CONFIGURED")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.resolve().is_relative_to(worker.records.store.root):
        raise ValueError("BACKUP_INSIDE_SOURCE_STORE")
    checkpoint: dict[str, Any] = {"phase": "PREPARING", "restore_verified": False}
    last_beat = 0.0

    def progress(update: dict[str, Any]) -> None:
        nonlocal last_beat
        checkpoint.update(update)
        now = time.monotonic()
        if now - last_beat >= min(5, worker.queue.lease_seconds / 3) or worker.stop.is_set():
            worker.queue.worker_heartbeat(worker.worker_id)
            worker.queue.heartbeat(job, checkpoint)
            last_beat = now
            if worker.stop.is_set() or worker.queue.drain_status()["draining"]:
                raise CheckpointRequested

    # Each lease has its own directory; a lost snapshot is never resumed from file counts.
    previous = sorted(root.glob(str(job.job_id) + "-*/manifest.json"))
    if previous:
        manifest = verify_backup(previous[-1].parent, progress=progress)
        backup_id = previous[-1].parent.name
    else:
        with worker.queue.db.connect() as conn:
            size = conn.execute("SELECT COALESCE(sum(size_bytes),0) AS n FROM blobs").fetchone()
            db_size = conn.execute("SELECT pg_database_size(current_database()) AS n").fetchone()
        assert size is not None and db_size is not None
        # Preflight is conservative, but allocation failure is still handled as partial failure.
        extra = (
            {"legacy.parquet": settings.legacy_parquet_path} if settings.legacy_parquet_path else {}
        )
        required = (
            int(size["n"]) + int(db_size["n"]) + sum(p.stat().st_size for p in extra.values())
        )
        if shutil.disk_usage(root).free < required + 1024**3:
            raise ValueError("BACKUP_INSUFFICIENT_SPACE")
        backup_id = f"{job.job_id}-{job.lease_token}"
        progress({"backup_id": backup_id})
        manifest = create_backup(
            worker.queue.db,
            worker.records.store,
            root / backup_id,
            lambda snapshot, path: dump_snapshot(worker, snapshot, path, progress),
            progress=progress,
            extra_files=extra,
        )
    worker.queue.heartbeat(
        job,
        {
            "phase": "COMPLETE",
            "backup_id": backup_id,
            "files_done": len(manifest["blobs"]),
            "files_total": len(manifest["blobs"]),
            "bytes_done": sum(b["size_bytes"] for b in manifest["blobs"]),
            "dump_bytes": manifest["dump"]["size_bytes"],
            "parquet_included": "legacy.parquet" in manifest.get("extra_files", {}),
            "external_archive_included": False,
            "restore_verified": False,
        },
    )
