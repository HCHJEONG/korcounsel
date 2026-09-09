"""Scaffold API: public health only, no legal data endpoints yet."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from klegal_gold import __version__
from klegal_gold.config import configure_logging, load_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(load_settings())
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="KorCounsel", version=__version__, lifespan=lifespan)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "korcounsel-api", "version": __version__}

    return application


app = create_app()
