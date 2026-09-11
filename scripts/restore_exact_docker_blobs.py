"""Restore fixed registered blobs from a stopped Docker volume or a pinned bundle root."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import IO, Any

from klegal_gold.storage.files import Blob, FileStore

VERSION = "exact-docker-blob-restore-1"
AUDIT_VERSION = "registered-blob-host-path-audit-1"


class RestorationStopped(RuntimeError):
    """A first observed defect stops a CLI run without replacing any evidence."""


def now() -> str:
    return datetime.now(UTC).isoformat()


def load_targets(path: Path, expected_hash: str) -> tuple[dict[str, Any], list[Blob]]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None or path.is_symlink():
        raise ValueError("INVALID_AUDIT_INPUT")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_hash:
        raise ValueError("AUDIT_HASH_MISMATCH")
    audit = json.loads(raw)
    if audit.get("version") != AUDIT_VERSION:
        raise ValueError("AUDIT_VERSION_MISMATCH")
    targets = []
    seen = set()
    for row in audit["issues"]:
        digest, key, size = row["sha256"], row["storage_key"], row["size_bytes"]
        if (
            row.get("issue") != "FILE_MISSING"
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or key != f"blobs/{digest[:2]}/{digest}"
            or type(size) is not int
            or size < 0
            or digest in seen
        ):
            raise ValueError("INVALID_AUDIT_TARGET")
        seen.add(digest)
        targets.append(Blob(digest, key, size))
    if len(targets) != audit["summary"]["problem_blobs"]:
        raise ValueError("AUDIT_TARGET_COUNT_MISMATCH")
    return audit, sorted(targets, key=lambda item: item.sha256)


def limit_source_targets(
    targets: list[Blob],
    path: Path,
    expected_hash: str,
    audit_hash: str,
) -> tuple[dict[str, Any], list[Blob]]:
    if re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None or path.is_symlink():
        raise ValueError("INVALID_SOURCE_TARGET_INPUT")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_hash:
        raise ValueError("SOURCE_TARGET_HASH_MISMATCH")
    manifest = json.loads(raw)
    if (
        manifest.get("version") != "source-present-blob-targets-1"
        or manifest.get("audit_sha256") != audit_hash
    ):
        raise ValueError("SOURCE_TARGET_AUDIT_MISMATCH")
    indexed = {b.sha256: b for b in targets}
    chosen = []
    seen = set()
    for item in manifest["blobs"]:
        candidate = Blob(item["sha256"], item["storage_key"], item["size_bytes"])
        if (
            type(candidate.size_bytes) is not int
            or indexed.get(candidate.sha256) != candidate
            or candidate.sha256 in seen
        ):
            raise ValueError("SOURCE_TARGET_NOT_IN_AUDIT")
        seen.add(candidate.sha256)
        chosen.append(candidate)
    if manifest["target_count"] != len(chosen) or manifest["target_bytes"] != sum(
        b.size_bytes for b in chosen
    ):
        raise ValueError("SOURCE_TARGET_COUNT_MISMATCH")
    return manifest, sorted(chosen, key=lambda b: b.sha256)


def select_targets(targets: list[Blob], offset: int, max_files: int, max_bytes: int) -> list[Blob]:
    if offset < 0 or max_files < 1 or max_bytes < 1:
        raise ValueError("INVALID_RESTORE_BOUND")
    chosen = targets[offset : offset + max_files]
    if not chosen or sum(item.size_bytes for item in chosen) > max_bytes:
        raise ValueError("RESTORE_BOUND_EXCEEDED")
    return chosen


def inspect_source(container: str, volume: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", container + ""):
        raise ValueError("INVALID_CONTAINER")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", volume + ""):
        raise ValueError("INVALID_VOLUME")
    result = subprocess.run(["docker", "inspect", container], capture_output=True, check=True)
    inspected = json.loads(result.stdout)[0]
    state = inspected["State"]
    mounts = [m for m in inspected["Mounts"] if m["Destination"] == "/data"]
    if state["Status"] not in {"exited", "created"} or state["Running"]:
        raise ValueError("SOURCE_CONTAINER_NOT_STOPPED")
    if len(mounts) != 1 or mounts[0].get("Type") != "volume" or mounts[0].get("Name") != volume:
        raise ValueError("SOURCE_VOLUME_MISMATCH")
    active = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"volume={volume}"], capture_output=True, check=True
    )
    if active.stdout.strip():
        raise ValueError("SOURCE_VOLUME_HAS_RUNNING_CONTAINER")
    return {
        "container": container,
        "container_id": inspected["Id"],
        "state": state["Status"],
        "volume": volume,
        "path": "/data/blobs",
    }


@contextmanager
def docker_stream(container_id: str) -> Iterator[IO[bytes]]:
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            ["docker", "cp", f"{container_id}:/data/blobs", "-"],
            stdout=subprocess.PIPE,
            stderr=errors,
        )
        assert process.stdout is not None
        try:
            yield process.stdout
            if process.wait() != 0:
                raise ValueError("DOCKER_COPY_STREAM_FAILED")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def process_archive(
    stream: IO[bytes],
    targets: list[Blob],
    files: FileStore | None,
    emit: Callable[[dict[str, Any]], None],
    stop_on_error: bool = False,
) -> dict[str, Any]:
    """Do not extract tar paths. Only exact fixed targets may become FileStore bytes."""
    pending = {blob.storage_key: blob for blob in targets}
    finished: set[str] = set()
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    stored = reused = 0
    interrupted: BaseException | None = None

    def record(blob: Blob, status: str, **extra: Any) -> None:
        counts[status] += 1
        finished.add(blob.storage_key)
        emit(
            {
                "at": now(),
                "sha256": blob.sha256,
                "storage_key": blob.storage_key,
                "size_bytes": blob.size_bytes,
                "status": status,
                **extra,
            }
        )

        if stop_on_error and status not in {
            "RESTORED_VERIFIED",
            "REUSED_VERIFIED",
            "SOURCE_PRESENT_SIZE_MATCH",
            "NOT_PROCESSED_INTERRUPTED",
        }:
            raise RestorationStopped(status)

    try:
        if files is not None:
            for blob in targets:
                try:
                    destination = files.path(blob.storage_key)
                    try:
                        existing = destination.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(existing.st_mode):
                        raise ValueError("HOST_NOT_REGULAR_FILE")
                    files.verify(blob)
                    record(blob, "REUSED_VERIFIED")
                    reused += blob.size_bytes
                except (OSError, ValueError) as error:
                    record(blob, "HOST_INTEGRITY_FAILED", error_type=type(error).__name__)
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for member in archive:
                candidate = pending.get(member.name)
                if candidate is None:
                    continue
                blob = candidate
                if member.name in seen:
                    # Preserve earlier valid bytes, but report that the stream is not clean.
                    emit(
                        {"at": now(), "storage_key": member.name, "status": "DUPLICATE_TAR_MEMBER"}
                    )
                    counts["DUPLICATE_TAR_MEMBER"] += 1
                    if stop_on_error:
                        raise RestorationStopped("DUPLICATE_TAR_MEMBER")
                    continue
                seen.add(member.name)
                if member.name in finished:
                    continue
                if not member.isfile():
                    record(blob, "SOURCE_NOT_REGULAR_FILE", tar_type=repr(member.type))
                    continue
                if member.size != blob.size_bytes:
                    record(blob, "SOURCE_SIZE_MISMATCH", source_size_bytes=member.size)
                    continue
                if files is None:
                    record(blob, "SOURCE_PRESENT_SIZE_MATCH", source_member=member.name)
                    continue
                try:
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError("SOURCE_MEMBER_UNREADABLE")
                    with source:
                        raw = source.read(blob.size_bytes + 1)
                    if len(raw) != blob.size_bytes or sha256(raw).hexdigest() != blob.sha256:
                        record(blob, "SOURCE_CONTENT_MISMATCH")
                        continue
                    installed = files.put(raw)
                    if installed != blob:
                        raise ValueError("INSTALLED_BLOB_MISMATCH")
                    # FileStore.put verifies the installed bytes, including racing existing files.
                    record(blob, "RESTORED_VERIFIED", source_member=member.name)
                    stored += blob.size_bytes
                except (OSError, ValueError) as error:
                    record(blob, "RESTORE_FAILED", error_type=type(error).__name__)
    except BaseException as error:
        interrupted = error
    for blob in targets:
        if blob.storage_key not in finished:
            record(blob, "NOT_PROCESSED_INTERRUPTED" if interrupted else "SOURCE_NOT_PRESENT")
    summary = {
        "counts": dict(counts),
        "restored_bytes": stored,
        "reused_bytes": reused,
        "target_count": len(targets),
        "target_bytes": sum(b.size_bytes for b in targets),
        "completed_stream": interrupted is None,
    }
    if interrupted is not None:
        summary["interrupted_error_type"] = type(interrupted).__name__
        emit({"at": now(), "status": "INTERRUPTED", "summary": summary})
        raise interrupted
    return summary


def inspect_directory(root: Path) -> dict[str, str]:
    if not root.is_absolute() or root.is_symlink() or root.resolve() != root or not root.is_dir():
        raise ValueError("REGULAR_ABSOLUTE_SOURCE_DIRECTORY_REQUIRED")
    return {"directory": str(root)}


def source_path(root: Path, blob: Blob) -> Path:
    if blob.storage_key != f"blobs/{blob.sha256[:2]}/{blob.sha256}":
        raise ValueError("INVALID_SOURCE_KEY")
    path = root / blob.storage_key
    if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
        raise ValueError("SOURCE_SYMLINK")
    return path


def process_directory(
    root: Path,
    targets: list[Blob],
    files: FileStore | None,
    emit: Callable[[dict[str, Any]], None],
    stop_on_error: bool = False,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    stored = reused = 0
    finished: set[str] = set()

    def record(blob: Blob, status: str, **extra: Any) -> None:
        finished.add(blob.sha256)
        counts[status] += 1
        emit(
            {
                "at": now(),
                "sha256": blob.sha256,
                "storage_key": blob.storage_key,
                "size_bytes": blob.size_bytes,
                "status": status,
                **extra,
            }
        )

        if stop_on_error and status not in {
            "RESTORED_VERIFIED",
            "REUSED_VERIFIED",
            "SOURCE_PRESENT_SIZE_MATCH",
            "NOT_PROCESSED_INTERRUPTED",
        }:
            raise RestorationStopped(status)

    try:
        for blob in targets:
            if files is not None:
                try:
                    destination = files.path(blob.storage_key)
                    if destination.exists():
                        if not stat.S_ISREG(destination.stat(follow_symlinks=False).st_mode):
                            raise ValueError("HOST_NOT_REGULAR_FILE")
                        files.verify(blob)
                        record(blob, "REUSED_VERIFIED")
                        reused += blob.size_bytes
                        continue
                except (OSError, ValueError) as error:
                    record(blob, "HOST_INTEGRITY_FAILED", error_type=type(error).__name__)
                    continue
            try:
                path = source_path(root, blob)
                before = path.stat(follow_symlinks=False)
                if not stat.S_ISREG(before.st_mode):
                    record(blob, "SOURCE_NOT_REGULAR_FILE")
                    continue
                if before.st_size != blob.size_bytes:
                    record(blob, "SOURCE_SIZE_MISMATCH", source_size_bytes=before.st_size)
                    continue
                if files is None:
                    record(blob, "SOURCE_PRESENT_SIZE_MATCH", source_path=str(path))
                    continue
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if not stat.S_ISREG(opened.st_mode) or opened.st_size != blob.size_bytes:
                        raise ValueError("SOURCE_CHANGED_DURING_READ")
                    raw = stream.read(blob.size_bytes + 1)
                    after = os.fstat(stream.fileno())
                if (opened.st_ino, opened.st_dev, opened.st_size, opened.st_mtime_ns) != (
                    after.st_ino,
                    after.st_dev,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError("SOURCE_CHANGED_DURING_READ")
                if len(raw) != blob.size_bytes or sha256(raw).hexdigest() != blob.sha256:
                    record(blob, "SOURCE_CONTENT_MISMATCH")
                    continue
                installed = files.put(raw)
                if installed != blob:
                    raise ValueError("INSTALLED_BLOB_MISMATCH")
                record(blob, "RESTORED_VERIFIED", source_path=str(path))
                stored += blob.size_bytes
            except FileNotFoundError:
                record(blob, "SOURCE_NOT_PRESENT")
            except (OSError, ValueError) as error:
                record(blob, "RESTORE_FAILED", error_type=type(error).__name__)
    except BaseException:
        for blob in targets:
            if blob.sha256 not in finished:
                record(blob, "NOT_PROCESSED_INTERRUPTED")
        raise
    return {
        "counts": dict(counts),
        "restored_bytes": stored,
        "reused_bytes": reused,
        "target_count": len(targets),
        "target_bytes": sum(b.size_bytes for b in targets),
        "completed_stream": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--audit-sha256", required=True)
    parser.add_argument("--source-targets", type=Path, required=True)
    parser.add_argument("--source-targets-sha256", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-directory", type=Path)
    parser.add_argument("--container", default="korcounsel-api-1")
    parser.add_argument("--volume", default="korcounsel_case_data")
    parser.add_argument("--mode", choices=("preflight", "restore"), default="preflight")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-files", type=int, default=100)
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    args = parser.parse_args()
    audit, all_targets = load_targets(args.audit, args.audit_sha256)
    source_targets, selected = limit_source_targets(
        all_targets, args.source_targets, args.source_targets_sha256, args.audit_sha256
    )
    targets = select_targets(selected, args.offset, args.max_files, args.max_bytes)
    data = args.data_dir
    if (
        not data.is_absolute()
        or data.is_symlink()
        or data.resolve() != Path(audit["host_data_dir"])
    ):
        raise ValueError("AUDITED_HOST_DATA_DIR_REQUIRED")
    if args.source_directory is not None:
        source = inspect_directory(args.source_directory)
        if source["directory"] != source_targets.get("source_directory"):
            raise ValueError("SOURCE_TARGET_DIRECTORY_MISMATCH")
        if args.source_directory == data or args.source_directory.is_relative_to(data / "blobs"):
            raise ValueError("SOURCE_AND_DESTINATION_OVERLAP")
    else:
        source = inspect_source(args.container, args.volume)
        if any(
            source[key] != source_targets.get("source_" + key)
            for key in ("container", "container_id", "volume", "path")
        ):
            raise ValueError("SOURCE_TARGET_CONTAINER_MISMATCH")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    journal_path = args.output_dir / f"{run_id}.jsonl"
    summary_path = args.output_dir / f"{run_id}.json"
    header = {
        "version": VERSION,
        "run_id": run_id,
        "started_at": now(),
        "audit_path": str(args.audit.resolve()),
        "audit_sha256": args.audit_sha256,
        "source_targets_path": str(args.source_targets.resolve()),
        "source_targets_sha256": args.source_targets_sha256,
        "audit_snapshot": audit.get("database", {}),
        "source": source,
        "host_data_dir": str(data),
        "mode": args.mode,
        "offset": args.offset,
        "max_files": args.max_files,
        "max_bytes": args.max_bytes,
        "selected_target_sha256": sha256(
            "".join(f"{b.sha256} {b.size_bytes}\n" for b in targets).encode()
        ).hexdigest(),
        "selected_count": len(targets),
        "selected_bytes": sum(b.size_bytes for b in targets),
        "db_access": False,
        "network_requests": False,
        "resume_contract": (
            "Rerun identical audit/range; verify every existing destination; "
            "never trust prior ledger status."
        ),
    }
    count = 0
    with journal_path.open("x", encoding="utf-8") as journal:

        def emit(event: dict[str, Any]) -> None:
            nonlocal count
            journal.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            journal.flush()
            count += 1
            if count % 100 == 0:
                os.fsync(journal.fileno())
            if count % 1000 == 0:
                print(
                    json.dumps(
                        {
                            "phase": args.mode,
                            "events": count - 1,
                            "selected": len(targets),
                            "run_id": run_id,
                        }
                    ),
                    flush=True,
                )

        emit({"status": "STARTED", **header})
        try:
            files = FileStore(data) if args.mode == "restore" else None
            if args.source_directory is not None:
                result = process_directory(
                    args.source_directory, targets, files, emit, stop_on_error=True
                )
                after_source = inspect_directory(args.source_directory)
            else:
                with docker_stream(source["container_id"]) as stream:
                    result = process_archive(stream, targets, files, emit, stop_on_error=True)
                after_source = inspect_source(args.container, args.volume)
            header.update(result)
            header["source_after"] = after_source
            if header["source_after"] != source:
                raise ValueError("SOURCE_CONTAINER_CHANGED")
            header["status"] = "COMPLETED"
        except BaseException as error:
            header["status"] = "INTERRUPTED"
            header["error_type"] = type(error).__name__
            raise
        finally:
            header["finished_at"] = now()
            emit({"status": "RUN_FINISHED", **header})
            os.fsync(journal.fileno())
            with summary_path.open("x", encoding="utf-8") as summary:
                summary.write(json.dumps(header, ensure_ascii=False, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "summary": str(summary_path),
                        "journal": str(journal_path),
                        "status": header["status"],
                        "counts": header.get("counts"),
                    }
                ),
                flush=True,
            )
    allowed = {"RESTORED_VERIFIED", "REUSED_VERIFIED", "SOURCE_PRESENT_SIZE_MATCH"}
    return 0 if all(key in allowed for key in header["counts"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
