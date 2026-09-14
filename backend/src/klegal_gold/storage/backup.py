"""Consistent PostgreSQL snapshot plus immutable blobs; no implicit restore or deletion."""

import json
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from klegal_gold.db.session import Database
from klegal_gold.storage.files import Blob, FileStore

DumpSnapshot = Callable[[str, Path], None]


def file_digest(
    path: Path, progress: Callable[[dict[str, Any]], None] | None = None
) -> tuple[str, int]:
    digest, size = sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if progress:
                progress({})
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def create_backup(
    db: Database,
    store: FileStore,
    destination: Path,
    dump_snapshot: DumpSnapshot,
    *,
    extra_files: dict[str, Path] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """dump_snapshot must use pg_dump --snapshot with this same database and schema.

    The callback runs while the exporting transaction is alive. A failed backup
    retains partial files for diagnosis but never receives a completion manifest.
    """
    if not destination.is_absolute() or destination.is_symlink():
        raise ValueError("INVALID_BACKUP_PATH")
    if destination.resolve().is_relative_to(store.root):
        raise ValueError("BACKUP_INSIDE_SOURCE_STORE")
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    target = FileStore(destination / "files")
    with db.connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        snapshot = conn.execute("SELECT pg_export_snapshot() AS snapshot").fetchone()
        assert snapshot is not None
        blobs = conn.execute(
            "SELECT sha256,storage_key,size_bytes FROM blobs ORDER BY sha256"
        ).fetchall()
        # Files committed after this snapshot are intentionally excluded, even if
        # present on disk by the time copying finishes. Unregistered orphans too.
        total = sum(row["size_bytes"] for row in blobs)
        copied = 0
        for index, row in enumerate(blobs):
            if progress:
                progress(
                    {
                        "phase": "COPYING",
                        "files_done": index,
                        "files_total": len(blobs),
                        "bytes_done": copied,
                        "bytes_total": total,
                    }
                )
            blob = Blob(**row)
            store.verify(blob)
            path = target.path(blob.storage_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            with store.path(blob.storage_key).open("rb") as source_stream, path.open("xb") as saved:
                shutil.copyfileobj(source_stream, saved, length=1024 * 1024)
                saved.flush()
                os.fsync(saved.fileno())
            target.verify(blob)
            copied += blob.size_bytes
        if progress:
            progress(
                {
                    "phase": "DUMPING",
                    "files_done": len(blobs),
                    "files_total": len(blobs),
                    "bytes_done": copied,
                    "bytes_total": total,
                }
            )
        dump = destination / "database.dump"
        dump_snapshot(snapshot["snapshot"], dump)
        if dump.is_symlink() or not dump.is_file():
            raise ValueError("BACKUP_DUMP_MISSING")
        with dump.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise ValueError("BACKUP_DUMP_FORMAT")
            os.fsync(stream.fileno())
        extras = {}
        for name, source in (extra_files or {}).items():
            if name != "legacy.parquet" or source.is_symlink():
                raise ValueError("INVALID_BACKUP_EXTRA")
            if progress:
                progress({"phase": "PARQUET"})
            before = file_digest(source, progress)
            saved_path = destination / name
            with source.open("rb") as src, saved_path.open("xb") as saved:
                while chunk := src.read(1024 * 1024):
                    saved.write(chunk)
                    if progress:
                        progress({"phase": "PARQUET"})
                saved.flush()
                os.fsync(saved.fileno())
            if (
                file_digest(saved_path, progress) != before
                or file_digest(source, progress) != before
            ):
                raise ValueError("BACKUP_EXTRA_CHANGED")
            extras[name] = {"sha256": before[0], "size_bytes": before[1]}
        digest, size = file_digest(dump, progress)
        manifest = {
            "version": "postgres-blob-backup-1",
            "created_at": datetime.now(UTC).isoformat(),
            "schema": db.schema,
            "dump": {"sha256": digest, "size_bytes": size},
            "blobs": blobs,
            "extra_files": extras,
        }
    # Persist nested directory entries before publishing the completion marker.
    for parent, _, _ in os.walk(target.root, topdown=False):
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
    pending = destination / ".manifest.pending"
    with pending.open("xb") as out:
        out.write(encoded)
        out.flush()
        os.fsync(out.fileno())
    os.link(pending, destination / "manifest.json")
    pending.unlink()
    directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return manifest


def verify_backup(
    directory: Path, *, progress: Callable[[dict[str, Any]], None] | None = None
) -> dict[str, Any]:
    """Verify local bundle integrity; this alone is not a database restore test."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("INVALID_BACKUP_PATH")
    manifest_path, dump = directory / "manifest.json", directory / "database.dump"
    if manifest_path.is_symlink() or dump.is_symlink():
        raise ValueError("BACKUP_SYMLINK")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != "postgres-blob-backup-1":
        raise ValueError("BACKUP_VERSION")
    expected = manifest["dump"]
    if file_digest(dump, progress) != (expected["sha256"], expected["size_bytes"]):
        raise ValueError("BACKUP_DUMP_INTEGRITY")
    for name, expected_file in manifest.get("extra_files", {}).items():
        if name != "legacy.parquet" or (directory / name).is_symlink():
            raise ValueError("INVALID_BACKUP_EXTRA")
        if file_digest(directory / name, progress) != (
            expected_file["sha256"],
            expected_file["size_bytes"],
        ):
            raise ValueError("BACKUP_EXTRA_INTEGRITY")
    files = directory / "files"
    if files.is_symlink() or not files.is_dir():
        raise ValueError("BACKUP_FILES_MISSING")
    store = FileStore(files)
    seen = set()
    for row in manifest["blobs"]:
        if progress:
            progress({"phase": "VERIFYING"})
        blob = Blob(**row)
        if blob.sha256 in seen:
            raise ValueError("BACKUP_DUPLICATE_BLOB")
        seen.add(blob.sha256)
        if blob.storage_key != f"blobs/{blob.sha256[:2]}/{blob.sha256}":
            raise ValueError("INVALID_STORAGE_KEY")
        store.verify(blob)
    return manifest
