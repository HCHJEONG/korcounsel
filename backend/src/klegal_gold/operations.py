"""Local operator commands. Private web routes remain unavailable until authentication."""

import json
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import typer

from klegal_gold.config import load_settings
from klegal_gold.db.migrate import migrate
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.domain.inventory import InventorySnapshot
from klegal_gold.ingestion.delta import InventoryDelta, compare_inventory, detail_fetch_candidates
from klegal_gold.ingestion.document_images import image_manifest_from_observation
from klegal_gold.ingestion.legacy_catalog import LegacySourceCatalog, scourt_catalog
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

operations = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


def _services() -> tuple[Database, Records, Queue]:
    settings = load_settings()
    db = Database.from_settings(settings)
    return db, Records(db, FileStore(settings.data_dir)), Queue(db, lease_seconds=300)


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


@operations.command("submit-law-detail")
@_safe
def submit_law_detail(request_key: str, source_id: str) -> None:
    """Queue one official lawgo detail; the worker reads its own explicit credential."""
    _, _, queue = _services()
    job = queue.submit_law_detail(request_key, source_id)
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("plan-inventory-delta")
@_safe
def plan_inventory_delta(
    current_snapshot_id: str,
    legacy_catalog_artifact_id: str,
    baseline_snapshot_id: str | None = None,
) -> None:
    """Compare preserved inventory snapshots before any detail jobs are submitted."""
    _, records, _ = _services()
    current = InventorySnapshot.model_validate_json(
        records.read("inventory:" + current_snapshot_id)
    )
    baseline = (
        InventorySnapshot.model_validate_json(records.read("inventory:" + baseline_snapshot_id))
        if baseline_snapshot_id is not None
        else None
    )
    catalog = LegacySourceCatalog.from_payload(json.loads(records.read(legacy_catalog_artifact_id)))
    if current.source.value != catalog.source:
        raise ValueError("LEGACY_CATALOG_SOURCE_MISMATCH")
    delta = compare_inventory(current, baseline, legacy_source_ids=catalog.source_ids)
    artifact_id = records.save_inventory_delta(delta)
    candidates = detail_fetch_candidates(delta)
    counts: dict[str, int] = {}
    for entry in delta.entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
    typer.echo(
        json.dumps(
            {
                "artifact_id": artifact_id,
                "counts": counts,
                "detail_candidate_count": len(candidates),
                "absence_is_confirmed": delta.absence_is_confirmed,
            }
        )
    )


@operations.command("submit-scourt-detail")
@_safe
def submit_scourt_detail(request_key: str, source_id: str) -> None:
    """Queue one current portal jisCntntsSrno; no automatic legacy ID relinking."""
    _, _, queue = _services()
    job = queue.submit_scourt_detail(request_key, source_id)
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("submit-delta-scourt-details")
@_safe
def submit_delta_scourt_details(
    request_key_prefix: str,
    delta_artifact_id: str,
    max_details: int = 50,
) -> None:
    """Register a bounded, idempotent subset of NEW/CHANGED scourt detail work."""
    if not 1 <= max_details <= 50:
        raise ValueError("INVALID_DETAIL_BATCH_LIMIT")
    _, records, queue = _services()
    delta = InventoryDelta.from_payload(json.loads(records.read(delta_artifact_id)))
    if delta.source != "scourt":
        raise ValueError("NOT_SCOURT_INVENTORY_DELTA")
    candidates = detail_fetch_candidates(delta)[:max_details]
    jobs = [
        queue.submit_scourt_detail(
            f"{request_key_prefix}:{delta.current_snapshot_id}:{source_id}", source_id
        )
        for source_id in candidates
    ]
    typer.echo(
        json.dumps(
            {
                "delta_artifact_id": delta_artifact_id,
                "registered": len(jobs),
                "candidate_count": len(detail_fetch_candidates(delta)),
                "job_ids": [str(job.job_id) for job in jobs],
            }
        )
    )


@operations.command("submit-scourt-inventory")
@_safe
def submit_scourt_inventory(
    request_key: str, query: str = "", max_pages: int = 2, display: int = 20
) -> None:
    """Register a bounded portal inventory observation, never an implicit full crawl."""
    _, _, queue = _services()
    job = queue.submit_scourt_inventory(
        request_key, query=query, max_pages=max_pages, display=display
    )
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("submit-legacy-import")
@_safe
def submit_legacy_import(request_key: str, manifest_hash: str) -> None:
    """Queue a FULL_ROW bundle already staged in the shared DATA_DIR CAS."""
    _, _, queue = _services()
    job = queue.submit_legacy_import(request_key, manifest_hash)
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("preserve-legacy-scourt-catalog")
@_safe
def preserve_legacy_scourt_catalog(path: Path) -> None:
    """Preserve verified legacy contId baseline; does not run a source inventory."""
    _, records, _ = _services()
    catalog = scourt_catalog(path)
    artifact_id = "legacy-source-catalog:" + catalog.parquet_sha256
    blob = records.put_artifact(
        artifact_id,
        catalog.encoded(),
        origin="MANIFEST",
        metadata={
            "kind": "LEGACY_SCOURT_SOURCE_CATALOG",
            "parquet_sha256": catalog.parquet_sha256,
            "rows_scanned": catalog.rows_scanned,
            "source_id_count": len(catalog.source_ids),
            "rejected_values": catalog.rejected_values,
        },
    )
    typer.echo(
        json.dumps(
            {
                "artifact_id": artifact_id,
                "sha256": blob.sha256,
                "rows_scanned": catalog.rows_scanned,
                "source_id_count": len(catalog.source_ids),
                "rejected_values": catalog.rejected_values,
            }
        )
    )


@operations.command("preserve-document-image-manifest")
@_safe
def preserve_document_image_manifest(source_id: str, observation_artifact_id: str) -> None:
    """Derive image references from one preserved scourt document observation."""
    _, records, _ = _services()
    payload = json.loads(records.read(observation_artifact_id))
    observation = payload.get("observation") if isinstance(payload, dict) else None
    if not isinstance(observation, dict):
        raise ValueError("INVALID_DOCUMENT_OBSERVATION")
    manifest = image_manifest_from_observation(
        observation, source_id=source_id, parent_artifact_id=observation_artifact_id
    )
    manifest_id = "image-manifest:document:" + observation_artifact_id.rsplit(":", 1)[-1]
    references = manifest["image_references"]
    assert isinstance(references, list)
    blob = records.put_artifact(
        manifest_id,
        json.dumps(manifest, sort_keys=True).encode(),
        origin="MANIFEST",
        metadata={"kind": "DOCUMENT_IMAGE_REFERENCE_MANIFEST"},
    )
    typer.echo(
        json.dumps(
            {"artifact_id": manifest_id, "sha256": blob.sha256, "references": len(references)}
        )
    )


@operations.command("preserve-image-manifest")
@_safe
def preserve_image_manifest(manifest_id: str, path: Path) -> None:
    """Store a local image reference manifest as an immutable artifact."""
    _, records, _ = _services()
    raw = path.read_bytes()
    artifact_id = "image-manifest:" + manifest_id
    blob = records.put_artifact(
        artifact_id,
        raw,
        origin="MANIFEST",
        metadata={"kind": "IMAGE_REFERENCE_MANIFEST"},
    )
    typer.echo(
        json.dumps(
            {"artifact_id": artifact_id, "sha256": blob.sha256, "size_bytes": blob.size_bytes}
        )
    )


@operations.command("submit-image-batch")
@_safe
def submit_image_batch(
    request_key: str,
    manifest_artifact_id: str,
    max_urls: int = 50,
    max_total_bytes: int = 512 * 1024 * 1024,
) -> None:
    """Queue a bounded scourt image acquisition batch from a preserved manifest artifact."""
    _, _, queue = _services()
    job = queue.submit_image_batch(
        request_key,
        manifest_artifact_id,
        max_urls=max_urls,
        max_total_bytes=max_total_bytes,
    )
    typer.echo(json.dumps({"job_id": str(job.job_id), "status": job.status}))


@operations.command("image-batch-status")
@_safe
def image_batch_status(job_id: UUID) -> None:
    """Report image acquisition counts without exposing response bodies."""
    db, _, queue = _services()
    job = queue.get(job_id)
    if job.kind != "ACQUIRE_IMAGE_BATCH":
        raise ValueError("NOT_IMAGE_BATCH_JOB")
    with db.connect() as conn:
        attempts = conn.execute(
            """SELECT outcome,count(*) AS n FROM image_acquisition_attempts
               WHERE job_id=%s GROUP BY outcome""",
            (job_id,),
        ).fetchall()
    typer.echo(
        json.dumps(
            {
                "job_id": str(job_id),
                "status": job.status,
                "attempts": {row["outcome"]: row["n"] for row in attempts},
                "checkpoint": job.checkpoint,
            }
        )
    )


@operations.command("legacy-import-status")
@_safe
def legacy_import_status(job_id: UUID) -> None:
    """Report committed row counts, including after interruption or partial failure."""
    db, _, queue = _services()
    job = queue.get(job_id)
    if job.kind != "IMPORT_LEGACY_BUNDLE":
        raise ValueError("NOT_LEGACY_IMPORT_JOB")
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT status,count(*) AS n FROM legacy_bundle_rows WHERE job_id=%s GROUP BY status",
            (job_id,),
        ).fetchall()
    typer.echo(
        json.dumps(
            {
                "job_id": str(job_id),
                "status": job.status,
                "committed_rows": {row["status"]: row["n"] for row in rows},
                "result_manifest": job.checkpoint.get("result_manifest"),
            }
        )
    )


@operations.command("create-account")
@_safe
def create_account(username: str) -> None:
    """Explicit local account creation; no automatic seed or password in arguments."""
    from klegal_gold.db.accounts import Accounts

    password = typer.prompt("Password (12+ characters)", hide_input=True, confirmation_prompt=True)
    db, _, _ = _services()
    user_id = Accounts(db).create(username, password)
    typer.echo(json.dumps({"user_id": str(user_id)}))
