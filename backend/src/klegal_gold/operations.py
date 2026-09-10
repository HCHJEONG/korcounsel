"""Local operator commands. Private web routes remain unavailable until authentication."""

import json
from collections.abc import Callable
from functools import wraps
from typing import Any
from uuid import UUID

import psycopg
import typer

from klegal_gold.config import load_settings
from klegal_gold.db.migrate import migrate
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

operations = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


def _services() -> tuple[Database, Records, Queue]:
    settings = load_settings()
    db = Database.from_settings(settings)
    return db, Records(db, FileStore(settings.data_dir)), Queue(db)


def _safe(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (OSError, ValueError, psycopg.Error):
            typer.echo(
                "Operation failed; check database readiness, input and local configuration.",
                err=True,
            )
            raise typer.Exit(1) from None

    return wrapped


@operations.command("migrate")
@_safe
def migrate_command() -> None:
    """Apply checked SQL migrations to the explicitly configured database."""
    versions = migrate(Database.from_settings(load_settings()))
    typer.echo(json.dumps({"applied": versions}))


@operations.command("submit-verify")
@_safe
def submit_verify(request_key: str, artifact_id: str) -> None:
    """Register an idempotent artifact integrity check; keep request_key on retry."""
    _, _, queue = _services()
    job = queue.submit(request_key, artifact_id)
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("job")
@_safe
def job_status(job_id: UUID) -> None:
    """Read job status without exposing payload or raw errors."""
    _, _, queue = _services()
    job = queue.get(job_id)
    typer.echo(
        json.dumps({"job_id": str(job.job_id), "status": job.status, "attempts": job.attempts})
    )


@operations.command("drain")
@_safe
def drain() -> None:
    """Block new jobs and claims. Does not stop EC2 or kill the worker."""
    _, _, queue = _services()
    queue.set_draining(True)
    typer.echo(json.dumps(queue.drain_status()))


@operations.command("resume")
@_safe
def resume() -> None:
    """Explicitly allow new jobs and claims after startup/maintenance."""
    _, _, queue = _services()
    queue.set_draining(False)
    typer.echo(json.dumps(queue.drain_status()))


@operations.command("status")
@_safe
def status() -> None:
    """Show drain readiness; recover expired leases into retry/failed state."""
    _, _, queue = _services()
    typer.echo(json.dumps(queue.drain_status()))


@operations.command("worker")
@_safe
def worker(once: bool = False) -> None:
    """Run the single processing worker, optionally handling at most one job."""
    _, records, queue = _services()
    service = Worker(queue, records)
    if once:
        typer.echo(json.dumps({"processed": service.run_once()}))
    else:
        service.run()


@operations.command("rebuild-projection")
@_safe
def rebuild_projection(request_key: str) -> None:
    """Rebuild case listings without changing users, jobs, or identity history."""
    _, _, queue = _services()
    job = queue.submit_rebuild(request_key)
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("worker-health")
@_safe
def worker_health() -> None:
    """Check the persisted worker heartbeat; not an API health proxy."""
    _, _, queue = _services()
    if not queue.worker_available():
        raise ValueError("WORKER_UNAVAILABLE")
    typer.echo("Worker heartbeat current")
