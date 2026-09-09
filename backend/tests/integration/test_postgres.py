import os

import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr

from klegal_gold.config import Settings
from klegal_gold.db.connection import database_available


@pytest.mark.integration
def test_read_only_postgres_connection():
    url = os.environ.get("KLEGAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set KLEGAL_TEST_DATABASE_URL for a local development database")
    info = conninfo_to_dict(url)
    if info.get("host") not in {"127.0.0.1", "localhost"} or info.get("dbname") not in {
        "korcounsel_dev",
        "korcounsel_test",
    }:
        pytest.fail("Integration test requires an explicitly named local development DB")
    assert database_available(Settings(database_url=SecretStr(url)))
