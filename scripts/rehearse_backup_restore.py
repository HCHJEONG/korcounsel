"""Run the isolated PostgreSQL/file restore drill; never restores operational data."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from klegal_gold.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--postgres-container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_absolute() or not args.env_file.is_file():
        parser.error("--env-file must be an existing absolute path")
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        parser.error("--output must be a new absolute directory")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.postgres_container):
        parser.error("invalid container name")
    os.environ["KLEGAL_ENV_FILE"] = str(args.env_file)
    settings = load_settings()
    if settings.database_url is None:
        raise ValueError("DATABASE_NOT_CONFIGURED")
    info = conninfo_to_dict(settings.database_url.get_secret_value())
    if info.get("host") not in {"127.0.0.1", "localhost"} or info.get("port") != "55432":
        raise ValueError("LOCAL_TEST_SERVER_REQUIRED")
    # Fixed separate DB, regardless of the environment file's operational DB name.
    info["dbname"] = "korcounsel_test"
    dsn = make_conninfo(**info)
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT 1")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    env = os.environ.copy()
    env.pop("KLEGAL_ENV_FILE", None)
    env["KLEGAL_TEST_DATABASE_URL"] = dsn
    env["KLEGAL_TEST_PG_CONTAINER"] = args.postgres_container
    root = Path(__file__).resolve().parents[1]
    started = datetime.now(UTC).isoformat()
    # The output parent is newly created; pytest never gets an existing data directory.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_backup_restore.py",
            "-q",
            "--basetemp=" + str(args.output / "pytest"),
            "--junitxml=" + str(args.output / "results.xml"),
        ],
        cwd=root / "backend",
        env=env,
        check=False,
    )
    report = {
        "kind": "ISOLATED_SYNTHETIC_RESTORE_DRILL",
        "started_at": started,
        "finished_at": datetime.now(UTC).isoformat(),
        "exit_code": result.returncode,
        "operational_corpus_backed_up": False,
        "operational_database_restored": False,
    }
    with (args.output / "report.json").open("x") as out:
        json.dump(report, out, indent=2)
    return result.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, psycopg.Error):
        print(
            "Restore drill failed. Check local test DB, paths and tools; secrets suppressed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
