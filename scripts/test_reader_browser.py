"""Run local browser checks with a fresh, undisclosed test-account password."""

import os
import secrets
import subprocess

env = {
    **os.environ,
    "KLEGAL_E2E_PASSWORD": secrets.token_urlsafe(32),
    "KLEGAL_E2E_EDITOR_PASSWORD": secrets.token_urlsafe(32),
}
raise SystemExit(
    subprocess.call(
        ["pnpm", "exec", "playwright", "test", "--config=playwright.reader.config.ts"], env=env
    )
)
