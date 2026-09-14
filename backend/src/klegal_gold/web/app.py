"""Authenticated corpus search and version-bound document reading API."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
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
    query: str = Field(default="", max_length=200)
    max_pages: int = Field(default=1, ge=1, le=10)
    display: int = Field(default=20, ge=1, le=100)


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
        request_key = "web-scourt-inventory:" + uuid4().hex
        job = queue.submit_scourt_inventory(
            request_key, query=body.query, max_pages=body.max_pages, display=body.display
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
        delta = compare_inventory(current, None, legacy_source_ids=catalog.source_ids)
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
        candidates = detail_fetch_candidates(delta)
        if refresh_source_id is not None:
            if not any(
                entry.source_id == refresh_source_id
                and entry.kind in {"NEW", "LEGACY_KNOWN", "CHANGED", "UNCHANGED"}
                for entry in delta.entries
            ):
                raise HTTPException(status_code=400, detail="SOURCE_NOT_IN_OBSERVED_DELTA")
            candidates = (refresh_source_id,)
        queue = Queue(db, lease_seconds=300)
        request_key_prefix = "web-scourt-detail:" + uuid4().hex
        jobs = [
            queue.submit_scourt_detail(
                f"{request_key_prefix}:{delta.current_snapshot_id}:{source_id}", source_id
            )
            for source_id in candidates[:max_details]
        ]
        return {
            "delta_artifact_id": artifact_id,
            "candidate_count": len(candidates),
            "registered": len(jobs),
            "job_ids": [str(job.job_id) for job in jobs],
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
