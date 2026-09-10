"""Versioned SQL, transactional DDL, checksums, and one migration lock."""

import re
from hashlib import sha256
from pathlib import Path

from .session import Database

MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"
if not MIGRATIONS.is_dir():
    MIGRATIONS = Path(__file__).resolve().parents[1] / "_migrations"
MIGRATION_LOCK = 72834001


def migrate(db: Database, directory: Path = MIGRATIONS, *, target: int | None = None) -> list[str]:
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise ValueError("MIGRATIONS_NOT_FOUND")
    for index, path in enumerate(files, 1):
        if not re.fullmatch(rf"{index:04d}_[a-z0-9_]+\.sql", path.name):
            raise ValueError("INVALID_MIGRATION_SEQUENCE")
    if target is not None and not 0 <= target <= len(files):
        raise ValueError("INVALID_MIGRATION_TARGET")
    applied = []
    with db.connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
        history = {
            r["version"]: r["checksum"]
            for r in conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")
        }
        if list(history) != [p.name for p in files[: len(history)]]:
            raise ValueError("UNKNOWN_OR_NONCONTIGUOUS_MIGRATION")
        if target is not None and target < len(history):
            raise ValueError("MIGRATION_DOWNGRADE_NOT_SUPPORTED")
        for index, path in enumerate(files, 1):
            raw = path.read_bytes()
            digest = sha256(raw).hexdigest()
            if path.name in history:
                if history[path.name] != digest:
                    raise ValueError("APPLIED_MIGRATION_CHANGED")
                continue
            if target is not None and index > target:
                break
            conn.execute(raw.decode("utf-8"), prepare=False)
            conn.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES(%s,%s)", (path.name, digest)
            )
            applied.append(path.name)
    return applied
