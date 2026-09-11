"""Isolated authentication fixture for real local reader browser tests."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
import uvicorn
from psycopg import sql

from klegal_gold.config import Settings
from klegal_gold.db.accounts import Accounts
from klegal_gold.db.migrate import migrate
from klegal_gold.db.session import Database
from klegal_gold.db.site_accounts import SiteAccounts
from klegal_gold.web.app import create_app
from klegal_gold.web.auth import accounts

if __name__ == "__main__":
    dsn = os.environ["KLEGAL_TEST_DATABASE_URL"]
    from psycopg.conninfo import conninfo_to_dict

    info = conninfo_to_dict(dsn)
    if (
        info.get("host") != "127.0.0.1"
        or info.get("port") != "55432"
        or info.get("dbname") != "korcounsel_dev"
    ):
        raise ValueError("LOCAL_TEST_DATABASE_REQUIRED")
    schema = "klegal_test_" + uuid4().hex
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        db = Database(dsn, schema=schema)
        migrate(db)
        settings = Settings(
            korcounsel_admin_id="reader-browser-test",
            korcounsel_admin_password=os.environ["KLEGAL_E2E_PASSWORD"],
            korcounsel_dev_editor_id="editor-browser-test",
            korcounsel_dev_editor_password=os.environ["KLEGAL_E2E_EDITOR_PASSWORD"],
        )
        service = SiteAccounts(db, settings)
        Accounts(db).create("unlisted-browser-test", os.environ["KLEGAL_E2E_PASSWORD"])
        os.environ["DATABASE_URL"] = dsn
        os.environ["DATA_DIR"] = str(Path("data").resolve())
        os.environ["LEGACY_PARQUET_PATH"] = str(
            Path("data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet").resolve()
        )
        app = create_app()
        app.dependency_overrides[accounts] = lambda: service
        uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
