"""Small read-only database probe using the API/worker connection contract."""

import psycopg

from klegal_gold.config import ConfigurationError, Settings
from klegal_gold.db.session import Database


def database_available(settings: Settings) -> bool:
    if settings.database_url is None:
        return False
    try:
        with Database.from_settings(settings).connect() as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            row = connection.execute("SELECT 1 AS reachable").fetchone()
            return row is not None and row["reachable"] == 1
    except (psycopg.Error, ConfigurationError):
        return False
