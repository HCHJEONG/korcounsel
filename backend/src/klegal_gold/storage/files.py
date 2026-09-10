"""Atomic no-overwrite file installation. DB failures leave reusable orphan blobs."""

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


@dataclass(frozen=True)
class Blob:
    sha256: str
    storage_key: str
    size_bytes: int


class FileStore:
    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("ABSOLUTE_DATA_DIR_REQUIRED")
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        # Keys are produced by this store, never raw source filenames or URLs.
        import re

        if not re.fullmatch(r"blobs/[0-9a-f]{2}/[0-9a-f]{64}", key):
            raise ValueError("INVALID_STORAGE_KEY")
        if key[6:8] != key.rsplit("/", 1)[1][:2]:
            raise ValueError("INVALID_STORAGE_KEY")
        result = self.root / key
        if not result.resolve().is_relative_to(self.root):
            raise ValueError("STORAGE_PATH_ESCAPE")
        if any(p.is_symlink() for p in (result, result.parent, result.parent.parent)):
            raise ValueError("STORAGE_SYMLINK")
        return result

    def verify(self, blob: Blob, progress: Callable[[int], None] | None = None) -> None:
        path = self.path(blob.storage_key)
        digest, size = sha256(), 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if progress is not None:
                    progress(size)
        if size != blob.size_bytes or digest.hexdigest() != blob.sha256:
            raise ValueError("BLOB_INTEGRITY_FAILED")

    def put(self, raw: bytes) -> Blob:
        digest = sha256(raw).hexdigest()
        blob = Blob(digest, f"blobs/{digest[:2]}/{digest}", len(raw))
        path = self.path(blob.storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path(blob.storage_key)
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            self.verify(blob)
        finally:
            os.unlink(temporary)
        return blob
