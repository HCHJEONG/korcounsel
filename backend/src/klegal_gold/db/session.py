"""Bounded, short-lived PostgreSQL connections; no implicit migrations."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

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
        self._dsn = dsn
        self.schema = schema

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        if settings.database_url is None:
            raise ConfigurationError("DATABASE_URL is required")
        return cls(settings.database_url.get_secret_value())

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        conninfo = make_conninfo(
            self._dsn,
            connect_timeout=5,
            options=f"-c search_path={self.schema} -c statement_timeout=30000 -c lock_timeout=5000",
        )
        with psycopg.connect(conninfo, row_factory=dict_row) as conn:
            yield conn
