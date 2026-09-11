"""Scaffold API with health and legacy corpus search endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from klegal_gold import __version__
from klegal_gold.config import configure_logging, load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.storage.files import FileStore


class CaseSearchItem(BaseModel):
    preservation_id: str
    content_revision: str
    court: str | None
    case_numbers: list[str]
    decision_date: date | None
    body_state: str
    row_position: int
    original_index: str


class CaseSearchResponse(BaseModel):
    query: str
    count: int
    limit: int = Field(ge=1, le=100)
    results: list[CaseSearchItem]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(load_settings())
    yield


def _records() -> Records:
    settings = load_settings()
    return Records(Database.from_settings(settings), FileStore(settings.data_dir))


def create_app() -> FastAPI:
    application = FastAPI(title="KorCounsel", version=__version__, lifespan=lifespan)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "korcounsel-api", "version": __version__}

    @application.get("/api/cases/search", response_model=CaseSearchResponse)
    def search_cases(
        q: str = Query(min_length=1, max_length=200),
        limit: int = Query(default=30, ge=1, le=100),
    ) -> CaseSearchResponse:
        results = _records().search_cases(q, limit=limit)
        items = [
            CaseSearchItem(
                preservation_id=item.preservation_id,
                content_revision=item.content_revision,
                court=item.court,
                case_numbers=list(item.case_numbers),
                decision_date=item.decision_date,
                body_state=item.body_state,
                row_position=item.row_position,
                original_index=item.original_index,
            )
            for item in results
        ]
        return CaseSearchResponse(query=q, count=len(items), limit=limit, results=items)

    return application


app = create_app()
