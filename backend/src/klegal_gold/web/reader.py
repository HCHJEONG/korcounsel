"""Authenticated immutable document and image delivery."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from klegal_gold.config import load_settings
from klegal_gold.db.records import Records
from klegal_gold.db.session import Database
from klegal_gold.documents.reader import image_occurrences, render_document
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.search.parquet import legacy_snapshot, read_legacy_body
from klegal_gold.storage.files import FileStore
from klegal_gold.web.auth import require_user

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
CSP = (
    "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'self'; sandbox allow-same-origin"
)


def reader_store() -> ReaderStore:
    settings = load_settings()
    return ReaderStore(Records(Database.from_settings(settings), FileStore(settings.data_dir)))


class ReaderItem(BaseModel):
    document_id: str
    title: str
    source_id: str
    origin: str
    image_count: int
    acquired_count: int


@router.get("/reader", response_model=list[ReaderItem])
def reader_list(
    store: Annotated[ReaderStore, Depends(reader_store)], q: str = Query(default="", max_length=200)
) -> list[ReaderItem]:
    return [ReaderItem(**item) for item in store.search(q)]


@router.get("/reader/{document_id}/html", response_class=HTMLResponse)
def document_html(
    document_id: str, store: Annotated[ReaderStore, Depends(reader_store)]
) -> HTMLResponse:
    try:
        html = store.html(document_id)
    except (ValueError, OSError):
        raise HTTPException(404, "본문이 없거나 보존본 검증에 실패했습니다.") from None
    return HTMLResponse(
        html, headers={"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff"}
    )


@router.get("/reader/{document_id}/images/{order}")
def document_image(
    document_id: str, order: int, store: Annotated[ReaderStore, Depends(reader_store)]
) -> Response:
    try:
        raw, media = store.image(document_id, order)
    except (ValueError, OSError):
        raise HTTPException(404, "이미지를 사용할 수 없습니다.") from None
    return Response(raw, media_type=media, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/cases/{position}/body", response_class=HTMLResponse)
def legacy_body(
    position: int,
    store: Annotated[ReaderStore, Depends(reader_store)],
    body_hash: str = Query(pattern="^[0-9a-f]{64}$"),
    reader_revision: str | None = Query(default=None, pattern="^[0-9a-f]{64}$"),
) -> HTMLResponse:
    settings = load_settings()
    if settings.legacy_parquet_path is None:
        raise HTTPException(503, "본문 저장소가 설정되지 않았습니다.")
    try:
        body, source_id = read_legacy_body(settings.legacy_parquet_path, position, body_hash)
        snapshot = legacy_snapshot(settings.legacy_parquet_path)
        revision = reader_revision or store.find_legacy(body_hash, position, snapshot)
        if revision:
            manifest = store.read(revision)
            provenance = manifest["provenance"]
            if (
                manifest["origin"] != "LEGACY_CORPUS"
                or manifest["html_sha256"] != body_hash
                or provenance.get("row_position") != position
                or provenance.get("snapshot_sha256") != snapshot
            ):
                raise ValueError("READER_VERSION_MISMATCH")
            html = store.html(revision)
        else:
            refs = image_occurrences(
                body, source_id=source_id, base_url="https://glaw.scourt.go.kr/"
            )
            html = render_document(body, refs, body_hash)
    except (ValueError, OSError):
        raise HTTPException(
            409, "본문 버전이 변경되었거나 사용할 수 없습니다. 다시 검색하세요."
        ) from None
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": CSP,
            "X-Content-Type-Options": "nosniff",
            **({"X-Reader-Revision": revision} if revision else {}),
        },
    )
