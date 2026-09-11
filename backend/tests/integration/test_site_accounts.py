import secrets
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from klegal_gold.config import ConfigurationError, Settings
from klegal_gold.db.accounts import Accounts
from klegal_gold.db.site_accounts import SiteAccounts
from klegal_gold.web.app import create_app
from klegal_gold.web.auth import accounts

ORIGIN = {"origin": "http://127.0.0.1:5173"}


def policy(db):
    admin, editor = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    settings = Settings(
        korcounsel_admin_id="admin-fixture",
        korcounsel_admin_password=SecretStr(admin),
        korcounsel_dev_editor_id="editor-fixture",
        korcounsel_dev_editor_password=SecretStr(editor),
    )
    return settings, SiteAccounts(db, settings), admin, editor


def test_only_two_configured_accounts_and_old_sessions(db):
    settings, service, admin, editor = policy(db)
    old = Accounts(db)
    password = secrets.token_urlsafe(24)
    old.create("other-user", password)
    old_token = old.issue_session("other-user", password)
    assert service.issue_session("other-user", password) is None
    assert service.session_user(old_token) is None
    for name, pw, role in [("admin-fixture", admin, "admin"), ("editor-fixture", editor, "editor")]:
        assert service.issue_session(name, pw + "wrong") is None
        token = service.issue_session(name, pw)
        user_id = service.session_user(token)
        assert user_id is not None
        assert service.role_for(user_id) == role
    with db.connect() as conn:
        rows = conn.execute("SELECT password_hash FROM app_users").fetchall()
        assert all(r["password_hash"].startswith("scrypt$") for r in rows)
        assert len(rows) == 3  # Historical account is retained, but excluded from HTTP access.


def test_password_rotation_and_id_removal_revoke_access(db):
    settings, service, admin, editor = policy(db)
    token = service.issue_session("admin-fixture", admin)
    user_id = service.session_user(token)
    replacement = secrets.token_urlsafe(24)
    settings.korcounsel_admin_password = SecretStr(replacement)
    changed = SiteAccounts(db, settings)
    assert changed.session_user(token) is None
    new_token = changed.issue_session("admin-fixture", replacement)
    assert changed.session_user(new_token) == user_id
    assert Accounts(db).session_user(token) is None
    settings.korcounsel_admin_id = "replacement-admin"
    assert SiteAccounts(db, settings).session_user(new_token) is None


def test_concurrent_first_login_preserves_one_account(db):
    _, service, admin, _ = policy(db)
    with ThreadPoolExecutor(2) as pool:
        tokens = list(pool.map(lambda _: service.issue_session("admin-fixture", admin), range(2)))
    assert all(tokens)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM app_users").fetchone()["n"] == 1


def test_missing_duplicate_and_disabled_accounts_fail_closed(db):
    settings, service, admin, _ = policy(db)
    with pytest.raises(ConfigurationError):
        SiteAccounts(db, Settings())
    settings.korcounsel_dev_editor_id = settings.korcounsel_admin_id
    with pytest.raises(ConfigurationError):
        SiteAccounts(db, settings)
    service.issue_session("admin-fixture", admin)
    with db.connect() as conn:
        conn.execute("UPDATE app_users SET enabled=false")
    assert service.issue_session("admin-fixture", admin) is None


def test_api_exposes_role_only_after_login(db):
    _, service, admin, editor = policy(db)
    app = create_app()
    app.dependency_overrides[accounts] = lambda: service
    with TestClient(app) as client:
        assert client.get("/api/auth/session").status_code == 401
        for name, pw, role in [
            ("admin-fixture", admin, "admin"),
            ("editor-fixture", editor, "editor"),
        ]:
            result = client.post(
                "/api/auth/login", headers=ORIGIN, json={"username": name, "password": pw}
            )
            assert result.status_code == 200
            assert client.get("/api/auth/session").json()["role"] == role
            client.post("/api/auth/logout", headers=ORIGIN, json={})


def test_driver_qualified_environment_url(db):
    from klegal_gold.db.session import Database

    qualified = db._dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    with Database(qualified, schema=db.schema).connect() as conn:
        assert conn.execute("SELECT 1 AS n").fetchone()["n"] == 1


def test_read_only_cli_probe_uses_same_driver_qualified_url(db):
    from pydantic import SecretStr

    from klegal_gold.config import Settings
    from klegal_gold.db.connection import database_available

    qualified = db._dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    assert database_available(Settings(database_url=SecretStr(qualified)))
