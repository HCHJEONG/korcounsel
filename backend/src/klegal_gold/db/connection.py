"""Small read-only database probe; no schema changes at import or startup."""

import psycopg
from psycopg.conninfo import make_conninfo

from klegal_gold.config import Settings


def database_available(settings: Settings) -> bool:
    if settings.database_url is None:
        return False
    try:
        conninfo = make_conninfo(
            settings.database_url.get_secret_value(),
            connect_timeout=3,
            options="-c statement_timeout=3000",
        )
        with psycopg.connect(conninfo) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                return cursor.fetchone() == (1,)
    except psycopg.Error:
        return False
