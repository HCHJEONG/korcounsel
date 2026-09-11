"""Bounded, short-lived PostgreSQL connections; no implicit migrations."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import local
from typing import Any, cast

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from klegal_gold.config import ConfigurationError, Settings

Connection = psycopg.Connection[dict[str, Any]]


class Database:
    def __init__(self, dsn: str, *, schema: str = "public") -> None:
        import re

        if not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
            raise ValueError("INVALID_DATABASE_SCHEMA")
        # Accept the driver-qualified URL already used by the project's environment file.
        self._dsn = (
            "postgresql://" + dsn.removeprefix("postgresql+psycopg://")
            if dsn.startswith("postgresql+psycopg://")
            else dsn
        )
        self.schema = schema
        self._sessions = local()

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        if settings.database_url is None:
            raise ConfigurationError("DATABASE_URL is required")
        return cls(settings.database_url.get_secret_value())

    def _connection_info(self) -> str:
        return make_conninfo(
            self._dsn,
            connect_timeout=5,
            options=f"-c search_path={self.schema} -c statement_timeout=30000 -c lock_timeout=5000",
        )

    @contextmanager
    def reuse_connections(self) -> Iterator[None]:
        """Reuse one thread-local connection during a bounded worker operation.

        Every connect() call still commits or rolls back its own transaction.
        Nested borrowing opens a separate connection to retain that independence.
        """
        if getattr(self._sessions, "connection", None) is not None:
            yield
            return
        with psycopg.connect(
            self._connection_info(), row_factory=dict_row, autocommit=True
        ) as conn:
            self._sessions.connection = conn
            self._sessions.borrowed = False
            try:
                yield
            finally:
                self._sessions.connection = None
                self._sessions.borrowed = False

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        cached = cast(Connection | None, getattr(self._sessions, "connection", None))
        if cached is not None and not getattr(self._sessions, "borrowed", False):
            self._sessions.borrowed = True
            try:
                with cached.transaction():
                    yield cached
            finally:
                self._sessions.borrowed = False
            return
        with psycopg.connect(self._connection_info(), row_factory=dict_row) as conn:
            yield conn
