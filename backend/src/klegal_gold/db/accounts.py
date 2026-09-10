"""Account/session persistence primitives; no HTTP login or automatic seeded users."""

import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from .session import Database


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError("PASSWORD_LENGTH")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024
    )
    return "scrypt$32768$8$1$" + salt.hex() + "$" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, n, r, p, salt, expected = encoded.split("$")
        if (kind, n, r, p) != ("scrypt", "32768", "8", "1") or len(password) > 1024:
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024
        )
        return hmac.compare_digest(digest.hex(), expected)
    except ValueError:
        return False


class Accounts:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, username: str, password: str) -> UUID:
        password_hash, user_id = hash_password(password), uuid4()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO app_users(user_id,username,password_hash) VALUES(%s,%s,%s)",
                (user_id, username, password_hash),
            )
        return user_id

    def issue_session(self, username: str, password: str) -> str | None:
        with self.db.connect() as conn:
            user = conn.execute(
                "SELECT * FROM app_users WHERE username=%s AND enabled", (username,)
            ).fetchone()
            if user is None or not verify_password(password, user["password_hash"]):
                return None
            token = secrets.token_urlsafe(32)
            conn.execute(
                """INSERT INTO app_sessions(token_hash,user_id,expires_at)
                   VALUES(%s,%s,clock_timestamp()+%s)""",
                (hashlib.sha256(token.encode()).hexdigest(), user["user_id"], timedelta(hours=8)),
            )
        return token

    def session_user(self, token: str) -> UUID | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT s.user_id FROM app_sessions s JOIN app_users u USING(user_id)
                   WHERE s.token_hash=%s AND s.expires_at>clock_timestamp() AND u.enabled""",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        return None if row is None else UUID(str(row["user_id"]))

    def revoke(self, token: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM app_sessions WHERE token_hash=%s",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
