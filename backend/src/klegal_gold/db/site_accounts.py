"""Exactly two environment-selected accounts; existing records remain intact."""

from __future__ import annotations

from functools import lru_cache
from uuid import UUID, uuid4

from klegal_gold.config import ConfigurationError, Settings
from klegal_gold.db.accounts import Accounts, hash_password, verify_password
from klegal_gold.db.session import Database


@lru_cache(maxsize=16)
def _matches(password: str, encoded: str) -> bool:
    # Bounded process memory only; no plaintext credentials persisted or logged.
    return verify_password(password, encoded)


class SiteAccounts(Accounts):
    def __init__(self, db: Database, settings: Settings) -> None:
        super().__init__(db)
        entries = [
            ("admin", settings.korcounsel_admin_id, settings.korcounsel_admin_password),
            ("editor", settings.korcounsel_dev_editor_id, settings.korcounsel_dev_editor_password),
        ]
        self.allowed: dict[str, tuple[str, str]] = {}
        for role, username, secret in entries:
            if (
                not username
                or username != username.strip()
                or len(username) > 100
                or secret is None
                or not 12 <= len(secret.get_secret_value()) <= 1024
            ):
                raise ConfigurationError(
                    "Configure both site account IDs and passwords (12+ characters)"
                )
            if username in self.allowed:
                raise ConfigurationError("Administrator and editor IDs must differ")
            self.allowed[username] = (role, secret.get_secret_value())

    def issue_session(self, username: str, password: str) -> str | None:
        import hmac

        configured = self.allowed.get(username)
        if configured is None or not hmac.compare_digest(password.encode(), configured[1].encode()):
            return None
        # Provision only after the configured credentials have been verified.
        # Advisory locking covers concurrent first login, without replacing user IDs/history.
        with self.db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                ("site-account:" + username,),
            )
            row = conn.execute(
                "SELECT * FROM app_users WHERE username=%s FOR UPDATE", (username,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO app_users(user_id,username,password_hash) VALUES(%s,%s,%s)",
                    (uuid4(), username, hash_password(password)),
                )
            elif not row["enabled"]:
                return None
            elif not _matches(password, row["password_hash"]):
                conn.execute("DELETE FROM app_sessions WHERE user_id=%s", (row["user_id"],))
                conn.execute(
                    "UPDATE app_users SET password_hash=%s WHERE user_id=%s",
                    (hash_password(password), row["user_id"]),
                )
        return super().issue_session(username, password)

    def session_user(self, token: str) -> UUID | None:
        user_id = super().session_user(token)
        if user_id is None:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT username,password_hash FROM app_users WHERE user_id=%s", (user_id,)
            ).fetchone()
        configured = self.allowed.get(row["username"]) if row else None
        if row is None or configured is None or not _matches(configured[1], row["password_hash"]):
            return None
        return user_id

    def role_for(self, user_id: UUID) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT username FROM app_users WHERE user_id=%s", (user_id,)
            ).fetchone()
        configured = self.allowed.get(row["username"]) if row else None
        return configured[0] if configured else None
