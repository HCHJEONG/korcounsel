"""Versioned SQL, transactional DDL, checksums, and one migration lock."""

import re
from hashlib import sha256
from pathlib import Path

from psycopg import sql

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
        # Extension operator classes live in public. Keep the target schema first
        # while replaying original, checksum-pinned SQL in isolated test schemas.
        conn.execute(
            sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(db.schema))
        )
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
        history_table = sql.Identifier(db.schema, "schema_migrations")
        conn.execute(
            sql.SQL("""CREATE TABLE IF NOT EXISTS {} (
            version text PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT clock_timestamp())""").format(history_table)
        )
        history = {
            r["version"]: r["checksum"]
            for r in conn.execute(
                sql.SQL("SELECT version,checksum FROM {} ORDER BY version").format(history_table)
            )
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
            if path.name == "0009_case_search_text.sql":
                # Install once in the shared extension schema before the unchanged
                # migration runs; a temporary target schema must never own pg_trgm.
                conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
            conn.execute(raw.decode("utf-8"), prepare=False)
            conn.execute(
                sql.SQL("INSERT INTO {}(version,checksum) VALUES(%s,%s)").format(history_table),
                (path.name, digest),
            )
            applied.append(path.name)
    return applied
