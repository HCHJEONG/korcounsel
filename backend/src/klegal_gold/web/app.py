"""Scaffold API with health and direct Parquet corpus search endpoints."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field

from klegal_gold import __version__
from klegal_gold.config import configure_logging, load_settings
from klegal_gold.search.parquet import search_legacy_parquet


class CaseSearchItem(BaseModel):
    court: str | None
    case_numbers: list[str]
    decision_date: date | None
    row_position: int
    original_index: str
    matched_columns: list[str]


class CaseSearchResponse(BaseModel):
    query: str
    count: int
    limit: int = Field(ge=1, le=100)
    source: str
    results: list[CaseSearchItem]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(load_settings())
    yield


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
        settings = load_settings()
        if settings.legacy_parquet_path is None:
            results = []
        else:
            results = search_legacy_parquet(settings.legacy_parquet_path, q, limit=limit)
        items = [
            CaseSearchItem(
                court=item.court,
                case_numbers=list(item.case_numbers),
                decision_date=item.decision_date,
                row_position=item.row_position,
                original_index=item.original_index,
                matched_columns=list(item.matched_columns),
            )
            for item in results
        ]
        return CaseSearchResponse(
            query=q,
            count=len(items),
            limit=limit,
            source="LEGACY_PARQUET" if settings.legacy_parquet_path is not None else "UNCONFIGURED",
            results=items,
        )

    return application


app = create_app()
