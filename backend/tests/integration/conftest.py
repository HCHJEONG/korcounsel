"""Every writable test gets a new explicitly local PostgreSQL schema."""

import os
import re
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from klegal_gold.db.migrate import migrate
from klegal_gold.db.session import Database


@pytest.fixture
def empty_db():
    dsn = os.environ.get("KLEGAL_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set KLEGAL_TEST_DATABASE_URL for an explicitly local database")
    info = conninfo_to_dict(dsn)
    if (
        info.get("host") not in {"127.0.0.1", "localhost"}
        or info.get("dbname") not in {"korcounsel_dev", "korcounsel_test"}
        or info.get("port") != "55432"
    ):
        pytest.fail("Writable tests require local dev/test DB on port 55432")
    schema = "klegal_test_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield Database(dsn, schema=schema)
    finally:
        assert re.fullmatch(r"klegal_test_[a-f0-9]{32}", schema)
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def db(empty_db):
    migrate(empty_db)
    return empty_db
