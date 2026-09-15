"""Authenticated corpus search and version-bound document reading API."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any, Self
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from starlette.responses import Response

from klegal_gold import __version__
from klegal_gold.config import configure_logging, load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.domain.inventory import InventorySnapshot
from klegal_gold.ingestion.delta import InventoryDelta, compare_inventory, detail_fetch_candidates
from klegal_gold.ingestion.legacy_catalog import LegacySourceCatalog
from klegal_gold.jobs.queue import Queue
from klegal_gold.search.index import LegacySearchIndex, snapshot_key
from klegal_gold.search.parquet import search_legacy_parquet
from klegal_gold.storage.files import FileStore
from klegal_gold.web.auth import require_admin, require_user, same_origin
from klegal_gold.web.auth import router as auth_router
from klegal_gold.web.reader import router as reader_router


class AdminEnrichmentRequest(BaseModel):
    request_id: UUID


class AdminInventoryRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    query: str = Field(default="", max_length=200)
    date_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_pages: int = Field(default=1, ge=1, le=10)
    display: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        from klegal_gold.sources.scourt import validate_window

        validate_window(self.date_from, self.date_to)
        return self


class CaseSearchItem(BaseModel):
    source: str
    display_title: str
    court: str | None
    case_numbers: list[str]
    decision_date: date | None
    row_position: int | None = None
    original_index: str | None = None
    matched_columns: list[str]
    body_hash: str | None = None
    reader_document_id: str | None = None


class CaseSearchResponse(BaseModel):
    query: str
    count: int
    limit: int = Field(ge=1, le=100)
    source: str
    results: list[CaseSearchItem]


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _decision_date(value: object) -> date | None:
    text = _text(value)
    if text is None or len(text) != 8 or not text.isdecimal():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _current_reader_pages(store: ReaderStore) -> Iterator[dict[str, Any]]:
    offset = 0
    while True:
        page = store.search("", limit=100, offset=offset)
        yield from page
        if len(page) < 100:
            return
        offset += len(page)


def _current_reader_matches(store: ReaderStore, query: str, *, limit: int) -> list[CaseSearchItem]:
    needle = query.casefold()
    matches: list[CaseSearchItem] = []
    indexed = store.search_indexed(query, limit=limit)
    title_matches = store.search(query, limit=limit) if indexed is None else []
    candidates = (
        indexed
        if indexed is not None
        else (title_matches if title_matches else _current_reader_pages(store))
    )
    for item in candidates:
        manifest = store.read(item["document_id"])
        title = _text(manifest.get("title")) or "현재 제공 본문"
        html = store.records.read(manifest["html_artifact_id"]).decode() if indexed is None else ""
        if needle in title.casefold():
            matched_columns = ["current_reader_title"]
        elif item.get("indexed_column") == "html_text" or needle in html.casefold():
            matched_columns = ["current_reader_html"]
        else:
            continue
        provenance = manifest.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        case_number = _text(provenance.get("case_number"))
        matches.append(
            CaseSearchItem(
                source="CURRENT_SOURCE",
                display_title=title,
                court=_text(provenance.get("court")),
                case_numbers=[case_number] if case_number else [],
                decision_date=_decision_date(provenance.get("decision_date")),
                matched_columns=matched_columns,
                body_hash=_text(manifest.get("html_sha256")),
                reader_document_id=item["document_id"],
            )
        )
        if len(matches) >= limit:
            break
    return matches


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(load_settings())
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="KorCounsel", version=__version__, lifespan=lifespan)

    application.include_router(auth_router)
    application.include_router(reader_router)
    from klegal_gold.web.quality import router as quality_router

    application.include_router(quality_router)

    @application.middleware("http")
    async def private_cache(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.post(
        "/api/admin/readers/{document_id}/images", dependencies=[Depends(same_origin)]
    )
    def retry_reader_images(
        document_id: str, body: AdminEnrichmentRequest, _: object = Depends(require_admin)
    ) -> dict[str, str]:
        settings = load_settings()
        db = Database.from_settings(settings)
        manifest = ReaderStore(Records(db, FileStore(settings.data_dir))).read(document_id)
        if manifest["origin"] != "CURRENT_SOURCE" or not (
            manifest["images"] or manifest.get("statute_images")
        ):
            raise ValueError("CURRENT_READER_IMAGES_REQUIRED")
        job = Queue(db).submit_current_image_retry(
            "web-image-retry:" + str(body.request_id), document_id
        )
        return {"job_id": str(job.job_id), "status": job.status}

    @application.get("/api/admin/backups")
    def backup_history(_: object = Depends(require_admin)) -> dict[str, object]:
        settings = load_settings()
        with Database.from_settings(settings).connect() as conn:
            rows = conn.execute(
                "SELECT job_id,status,attempts,checkpoint,created_at,updated_at FROM jobs "
                "WHERE kind='CREATE_BACKUP' ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
        return {"enabled": settings.backup_dir is not None, "items": rows}

    @application.post("/api/admin/backups", dependencies=[Depends(same_origin)])
    def start_backup(
        body: AdminEnrichmentRequest, _: object = Depends(require_admin)
    ) -> dict[str, str]:
        settings = load_settings()
        if settings.backup_dir is None:
            raise HTTPException(409, "BACKUP_NOT_CONFIGURED")
        try:
            job = Queue(Database.from_settings(settings)).submit_backup(
                "web-backup:" + str(body.request_id)
            )
        except ValueError as exc:
            if str(exc) == "BACKUP_ALREADY_ACTIVE":
                raise HTTPException(409, "BACKUP_ALREADY_ACTIVE") from None
            raise
        return {"job_id": str(job.job_id), "status": job.status}

    @application.post("/api/admin/search-index", dependencies=[Depends(same_origin)])
    def build_search_index(
        body: AdminEnrichmentRequest, _: object = Depends(require_admin)
    ) -> dict[str, str]:
        settings = load_settings()
        if settings.legacy_parquet_path is None:
            raise ValueError("LEGACY_PARQUET_UNAVAILABLE")
        job = Queue(Database.from_settings(settings)).submit_legacy_search(
            "web-search-index:" + str(body.request_id), snapshot_key(settings.legacy_parquet_path)
        )
        return {"job_id": str(job.job_id), "status": job.status}

    @application.post("/api/admin/scourt-inventory", dependencies=[Depends(same_origin)])
    def submit_scourt_inventory(
        body: AdminInventoryRequest, _: object = Depends(require_admin)
    ) -> dict[str, str]:
        settings = load_settings()
        if settings.database_url is None:
            raise ValueError("DATABASE_NOT_CONFIGURED")
        db = Database.from_settings(settings)
        queue = Queue(db, lease_seconds=300)
        request_key = "web-scourt-inventory:" + str(body.request_id)
        job = queue.submit_scourt_inventory(
            request_key,
            query=body.query,
            max_pages=body.max_pages,
            display=body.display,
            date_from=body.date_from,
            date_to=body.date_to,
        )
        return {"job_id": str(job.job_id), "status": job.status}

    @application.post("/api/admin/readers/{document_id}/lawgo", dependencies=[Depends(same_origin)])
    def retry_reader_lawgo(
        document_id: str, body: AdminEnrichmentRequest, _: object = Depends(require_admin)
    ) -> dict[str, str]:
        settings = load_settings()
        db = Database.from_settings(settings)
        store = ReaderStore(Records(db, FileStore(settings.data_dir)))
        manifest = store.read(document_id)
        if manifest["origin"] != "CURRENT_SOURCE":
            raise ValueError("NOT_CURRENT_READER")
        queue = Queue(db, lease_seconds=300)
        parent = queue.get(UUID(manifest["provenance"]["job_id"]))
        dependency = (
            UUID(parent.checkpoint["reader_refresh_job_id"])
            if parent.checkpoint.get("reader_refresh_job_id")
            else parent.job_id
        )
        job = queue.submit_current_lawgo(
            document_id, dependency, request_key="web-lawgo:" + str(body.request_id)
        )
        return {"job_id": str(job.job_id), "status": job.status}

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "korcounsel-api", "version": __version__}

    @application.post("/api/admin/jobs/{job_id}/delta", dependencies=[Depends(same_origin)])
    def calculate_inventory_delta(
        job_id: str, _: object = Depends(require_admin)
    ) -> dict[str, object]:
        settings = load_settings()
        if settings.database_url is None:
            raise ValueError("DATABASE_NOT_CONFIGURED")
        db = Database.from_settings(settings)
        job = Queue(db, lease_seconds=300).get(UUID(job_id))
        snapshot_artifact = job.checkpoint.get("snapshot_artifact")
        if (
            job.kind != "FETCH_SCOURT_INVENTORY"
            or job.status != "SUCCEEDED"
            or not isinstance(snapshot_artifact, str)
        ):
            raise ValueError("INVENTORY_SNAPSHOT_NOT_READY")
        records = Records(db, FileStore(settings.data_dir))
        current = InventorySnapshot.model_validate_json(records.read(snapshot_artifact))
        with db.connect() as conn:
            row = conn.execute(
                "SELECT artifact_id FROM artifacts WHERE artifact_id LIKE %s "
                "ORDER BY artifact_id DESC LIMIT 1",
                ("legacy-source-catalog:%",),
            ).fetchone()
        if row is None:
            raise ValueError("LEGACY_SOURCE_CATALOG_NOT_FOUND")
        catalog = LegacySourceCatalog.from_payload(json.loads(records.read(row["artifact_id"])))
        if catalog.source != current.source.value:
            raise ValueError("LEGACY_CATALOG_SOURCE_MISMATCH")
        with db.connect() as conn:
            prior = conn.execute(
                "SELECT i.artifact_id FROM inventories i JOIN artifacts a USING(artifact_id) "
                "WHERE i.source=%s AND i.scope_hash=%s "
                "AND split_part(i.snapshot_id,':',1)<>split_part(%s,':',1) "
                "AND a.created_at < (SELECT created_at FROM artifacts WHERE artifact_id=%s) "
                "ORDER BY a.created_at DESC LIMIT 1",
                (current.source.value, current.scope_hash, current.snapshot_id, snapshot_artifact),
            ).fetchone()
            collected = conn.execute(
                "SELECT DISTINCT source_id FROM source_versions WHERE source='scourt'"
            ).fetchall()
        baseline = (
            InventorySnapshot.model_validate_json(records.read(prior["artifact_id"]))
            if prior
            else None
        )
        delta = compare_inventory(
            current,
            baseline,
            legacy_source_ids=catalog.source_ids,
            collected_source_ids=[item["source_id"] for item in collected],
            preservation_checked=True,
        )
        artifact_id = records.save_inventory_delta(delta)
        counts: dict[str, int] = {}
        for entry in delta.entries:
            counts[entry.kind] = counts.get(entry.kind, 0) + 1
        return {
            "artifact_id": artifact_id,
            "counts": counts,
            "snapshot_artifact": snapshot_artifact,
        }

    @application.post(
        "/api/admin/deltas/{artifact_id}/scourt-details",
        dependencies=[Depends(same_origin)],
    )
    def submit_scourt_delta_details(
        artifact_id: str,
        max_details: int = Query(default=10, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=1000),
        request_id: UUID | None = None,
        refresh_source_id: str | None = Query(default=None, pattern=r"^[0-9]{1,30}$"),
        _: object = Depends(require_admin),
    ) -> dict[str, object]:
        settings = load_settings()
        if settings.database_url is None:
            raise ValueError("DATABASE_NOT_CONFIGURED")
        db = Database.from_settings(settings)
        records = Records(db, FileStore(settings.data_dir))
        delta = InventoryDelta.from_payload(json.loads(records.read(artifact_id)))
        if delta.source != "scourt":
            raise ValueError("NOT_SCOURT_INVENTORY_DELTA")
        from klegal_gold.ingestion.window import window_candidates

        try:
            candidates, is_window = window_candidates(
                records, delta, detail_fetch_candidates(delta)
            )
        except ValueError as exc:
            if str(exc) == "WINDOW_INVENTORY_INCOMPLETE":
                raise HTTPException(400, "WINDOW_INVENTORY_INCOMPLETE") from None
            raise
        if refresh_source_id is not None:
            if not any(
                entry.source_id == refresh_source_id
                and entry.kind
                in {"NEW", "LEGACY_KNOWN", "CURRENT_KNOWN", "CHANGED", "UNCHANGED", "UNPRESERVED"}
                for entry in delta.entries
            ):
                raise HTTPException(status_code=400, detail="SOURCE_NOT_IN_OBSERVED_DELTA")
            candidates = (refresh_source_id,)
        queue = Queue(db, lease_seconds=300)
        request_key_prefix = (
            "web-scourt-window:" + delta.current_snapshot_id
            if is_window and refresh_source_id is None
            else "web-scourt-detail:" + str(request_id or artifact_id)
        )
        jobs = [
            queue.submit_scourt_detail(
                f"{request_key_prefix}:{delta.current_snapshot_id}:{source_id}", source_id
            )
            for source_id in candidates[offset : offset + max_details]
        ]
        return {
            "delta_artifact_id": artifact_id,
            "candidate_count": len(candidates),
            "registered": len(jobs),
            "next_offset": offset + len(jobs),
            "exhausted": offset + len(jobs) >= len(candidates),
            "source_ids": list(candidates[offset : offset + max_details]),
            "job_ids": [str(job.job_id) for job in jobs],
        }

    @application.post(
        "/api/admin/readers/{document_id}/fields", dependencies=[Depends(same_origin)]
    )
    def submit_fields(
        document_id: str, body: AdminEnrichmentRequest, _: object = Depends(require_admin)
    ) -> dict[str, object]:
        from klegal_gold.documents.reader_store import ReaderStore

        settings = load_settings()
        db = Database.from_settings(settings)
        records = Records(db, FileStore(settings.data_dir))
        reader = ReaderStore(records).read(document_id)
        if reader["origin"] != "CURRENT_SOURCE":
            raise HTTPException(400, "기존 필드는 보존 Parquet에서 조회합니다.")
        job = Queue(db).submit_case_fields(
            document_id, request_key=f"web-fields:{body.request_id}:{document_id}"
        )
        return {"job_id": str(job.job_id), "status": job.status}

    @application.get("/api/admin/ingestions")
    def recent_ingestions(_: object = Depends(require_admin)) -> dict[str, object]:
        from klegal_gold.jobs.ingestion_status import ingestion_status

        db = Database.from_settings(load_settings())
        queue = Queue(db, lease_seconds=300)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT job_id FROM (SELECT DISTINCT ON(payload->>'source_id') "
                "job_id,created_at FROM jobs WHERE kind='FETCH_SCOURT_DETAIL' "
                "ORDER BY payload->>'source_id',created_at DESC,job_id DESC) latest "
                "ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            missing = conn.execute(
                "SELECT count(DISTINCT s.source_id) AS n FROM source_versions s "
                "WHERE s.source='scourt' AND NOT EXISTS (SELECT 1 FROM artifacts a "
                "WHERE a.metadata->>'kind'='READER_DOCUMENT' "
                "AND a.metadata->>'origin'='CURRENT_SOURCE' "
                "AND a.metadata->>'source_id'=s.source_id)"
            ).fetchone()
        return {
            "items": [ingestion_status(queue, row["job_id"]) for row in rows],
            "missing_readers": missing["n"] if missing else 0,
        }

    @application.get("/api/admin/jobs")
    def admin_job_summary(
        job_id: Annotated[list[UUID], Query(min_length=1, max_length=50)],
        _: object = Depends(require_admin),
    ) -> dict[str, object]:
        settings = load_settings()
        if settings.database_url is None:
            raise ValueError("DATABASE_NOT_CONFIGURED")
        queue = Queue(Database.from_settings(settings), lease_seconds=300)
        statuses: dict[str, int] = {}
        for identifier in job_id:
            status = queue.get(identifier).status
            statuses[status] = statuses.get(status, 0) + 1
        completed = sum(statuses.get(status, 0) for status in ("SUCCEEDED", "FAILED"))
        return {"total": len(job_id), "completed": completed, "statuses": statuses}

    @application.get("/api/admin/jobs/{job_id}")
    def admin_job_status(job_id: str, _: object = Depends(require_admin)) -> dict[str, object]:
        settings = load_settings()
        if settings.database_url is None:
            raise ValueError("DATABASE_NOT_CONFIGURED")
        queue = Queue(Database.from_settings(settings), lease_seconds=300)
        job = queue.get(UUID(job_id))
        return {
            "job_id": str(job.job_id),
            "status": job.status,
            "attempts": job.attempts,
            "checkpoint": job.checkpoint,
        }

    @application.get(
        "/api/cases/search", response_model=CaseSearchResponse, dependencies=[Depends(require_user)]
    )
    def search_cases(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> CaseSearchResponse:
        settings = load_settings()
        current_items = (
            _current_reader_matches(
                ReaderStore(
                    Records(Database.from_settings(settings), FileStore(settings.data_dir))
                ),
                q,
                limit=limit,
            )
            if settings.database_url is not None
            else []
        )
        legacy_results = None
        if settings.legacy_parquet_path is not None and settings.database_url is not None:
            legacy_results = LegacySearchIndex(Database.from_settings(settings)).search(
                settings.legacy_parquet_path, q, limit
            )
        if legacy_results is None:
            legacy_results = (
                search_legacy_parquet(settings.legacy_parquet_path, q, limit=limit)
                if settings.legacy_parquet_path is not None
                else []
            )
        legacy_items = [
            CaseSearchItem(
                source="LEGACY_PARQUET",
                display_title=", ".join(item.case_numbers) or "과거 보존 판례",
                court=item.court,
                case_numbers=list(item.case_numbers),
                decision_date=item.decision_date,
                row_position=item.row_position,
                original_index=item.original_index,
                matched_columns=list(item.matched_columns),
                body_hash=item.body_hash,
            )
            for item in legacy_results
        ]
        items = (current_items + legacy_items)[:limit]
        source = (
            "COMBINED"
            if current_items and legacy_items
            else "CURRENT_SOURCE"
            if current_items
            else "LEGACY_PARQUET"
            if settings.legacy_parquet_path is not None
            else "UNCONFIGURED"
        )
        return CaseSearchResponse(
            query=q, count=len(items), limit=limit, source=source, results=items
        )

    return application


app = create_app()
