"""Bounded image acquisition with per-reference and per-URL ledger rows."""

from __future__ import annotations

import io
import json
import struct
import warnings
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, build_opener
from uuid import NAMESPACE_URL, UUID, uuid5

from PIL import Image

from klegal_gold.sources.law_api import _NoRedirect

if TYPE_CHECKING:
    from klegal_gold.db.records import Records
    from klegal_gold.jobs.queue import Job
    from klegal_gold.storage.files import Blob

ReferenceStatus = Literal["RESOLVED", "NAME_ONLY", "ID_MISMATCH", "UNRESOLVED"]
AttemptOutcome = Literal["ACQUIRED", "FAILED", "SKIPPED"]

MAX_IMAGE_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_URLS = 50
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024
ALLOWED_SOURCE_SYSTEMS = {"scourt", "law_go_kr", "lawnb", "legacy_import"}


@dataclass(frozen=True)
class ImageReference:
    reference_id: str
    manifest_hash: str
    source_system: str
    source_id: str
    row_position: int | None
    occurrence_order: int
    original_src: str | None
    image_name: str | None
    resolved_url: str | None
    reference_status: ReferenceStatus
    reason: str
    context: dict[str, Any]


@dataclass(frozen=True)
class AcquisitionResult:
    references: int
    urls_considered: int
    acquired: int
    skipped: int
    failed: int
    bytes_stored: int


@dataclass(frozen=True)
class DownloadedImage:
    body: bytes
    content_type: str | None
    metadata: dict[str, Any]


Fetcher = Callable[[str, int], DownloadedImage]
Progress = Callable[[dict[str, Any]], None]


def valid_scourt_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    query = parse_qs(parsed.query)
    return (
        parsed.netloc == "portal.scourt.go.kr"
        and parsed.path == "/pgp/pgp003/downloadImgFile.on"
        and query.get("pgmId") == ["PGP1011M04"]
        and len(query.get("jisCntntsSrno", [])) == 1
        and query["jisCntntsSrno"][0].isascii()
        and query["jisCntntsSrno"][0].isdigit()
        and len(query.get("atchImgFileNm", [])) == 1
        and bool(query["atchImgFileNm"][0].strip())
    )


def image_metadata(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        width, height = struct.unpack(">II", raw[16:24])
        return {"format": "PNG", "width": width, "height": height}
    if raw.startswith((b"GIF87a", b"GIF89a")) and len(raw) >= 10:
        width, height = struct.unpack("<HH", raw[6:10])
        return {"format": "GIF", "width": width, "height": height}
    if raw.startswith(b"\xff\xd8\xff"):
        return {"format": "JPEG"}
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return {"format": "WEBP"}
    if raw.startswith(b"BM"):
        return {"format": "BMP"}
    raise ValueError("UNSUPPORTED_IMAGE_BYTES")


def validate_image(raw: bytes) -> dict[str, Any]:
    """Verify the container and decode every frame within a fixed pixel budget."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=["GIF", "PNG", "JPEG", "WEBP", "BMP"]) as img:
                width, height = img.size
                frames = getattr(img, "n_frames", 1)
                if width * height * frames > 25_000_000 or frames > 200:
                    raise ValueError("IMAGE_PIXEL_LIMIT")
                result = {
                    "format": img.format,
                    "width": width,
                    "height": height,
                    "frames": frames,
                    "decode_verified": True,
                }
                img.verify()
            with Image.open(io.BytesIO(raw), formats=["GIF", "PNG", "JPEG", "WEBP", "BMP"]) as img:
                for frame in range(frames):
                    img.seek(frame)
                    img.load()
        return result
    except (
        OSError,
        SyntaxError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("IMAGE_DECODE_FAILED") from exc


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise ValueError("INVALID_IMAGE_MANIFEST")
    for key in ("image_references", "references", "images", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    groups = payload.get("groups")
    if isinstance(groups, list):
        result: list[dict[str, Any]] = []
        for group in groups:
            if isinstance(group, dict):
                nested = group.get("items") or group.get("images") or group.get("references")
                if isinstance(nested, list):
                    result.extend(item for item in nested if isinstance(item, dict))
        return result
    raise ValueError("INVALID_IMAGE_MANIFEST")


def _status(
    item: dict[str, Any], resolved_url: str | None, image_name: str | None
) -> ReferenceStatus:
    raw_status = _scalar(item.get("reference_status") or item.get("status"))
    if raw_status in {"RESOLVED", "NAME_ONLY", "ID_MISMATCH", "UNRESOLVED"}:
        return raw_status  # type: ignore[return-value]
    if _scalar(item.get("id_mismatch_reason")) or item.get("id_mismatch") is True:
        return "ID_MISMATCH"
    if resolved_url is None and image_name is not None:
        return "NAME_ONLY"
    if resolved_url is not None:
        return "RESOLVED"
    return "UNRESOLVED"


def references_from_manifest(raw: bytes) -> list[ImageReference]:
    manifest_hash = sha256(raw).hexdigest()
    payload = json.loads(raw.decode("utf-8"))
    refs: list[ImageReference] = []
    for order, item in enumerate(_items(payload)):
        resolved_url = _scalar(
            item.get("resolved_url") or item.get("url") or item.get("image_url") or item.get("href")
        )
        image_name = _scalar(
            item.get("image_name") or item.get("name") or item.get("cont_image_name")
        )
        source_system = _scalar(item.get("source_system")) or "scourt"
        if source_system not in ALLOWED_SOURCE_SYSTEMS:
            source_system = "scourt"
        source_id = (
            _scalar(
                item.get("source_id")
                or item.get("cont_id")
                or item.get("contId")
                or item.get("serialno")
                or item.get("legacy_source_id")
            )
            or "UNKNOWN"
        )
        status = _status(item, resolved_url, image_name)
        reason = (
            _scalar(item.get("reason") or item.get("status_reason"))
            or {
                "RESOLVED": "resolved image URL observed",
                "NAME_ONLY": "image reference has provider name but no safe resolved URL",
                "ID_MISMATCH": (
                    "provider image identifier does not match the expected document identifier"
                ),
                "UNRESOLVED": "image reference could not be resolved to a fetchable URL",
            }[status]
        )
        reference_id = _scalar(item.get("reference_id"))
        if reference_id is None:
            key = json.dumps(
                [manifest_hash, source_id, order, image_name, resolved_url], sort_keys=True
            )
            reference_id = "image-ref:" + str(uuid5(NAMESPACE_URL, key))
        refs.append(
            ImageReference(
                reference_id=reference_id,
                manifest_hash=manifest_hash,
                source_system=source_system,
                source_id=source_id,
                row_position=_int_or_none(item.get("row_position", item.get("position"))),
                occurrence_order=(
                    order if item.get("occurrence_order") is None else int(item["occurrence_order"])
                ),
                original_src=_scalar(item.get("original_src") or item.get("src")),
                image_name=image_name,
                resolved_url=resolved_url,
                reference_status=status,
                reason=reason,
                context=dict(item),
            )
        )
    return refs


def fetch_image(url: str, max_bytes: int = MAX_IMAGE_BYTES) -> DownloadedImage:
    if not valid_scourt_image_url(url):
        raise ValueError("UNSAFE_IMAGE_URL")
    request = Request(url, headers={"User-Agent": "KorCounsel/0.1 image-ledger"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("IMAGE_TOO_LARGE")
                chunks.append(chunk)
    except HTTPError as exc:
        raise ValueError(f"HTTP_{exc.code}") from exc
    except URLError as exc:
        raise ValueError("IMAGE_NETWORK_ERROR") from exc
    raw = b"".join(chunks)
    return DownloadedImage(raw, content_type, {**validate_image(raw), "final_url": url})


class ImageAcquirer:
    def __init__(self, records: Records, *, fetcher: Fetcher = fetch_image) -> None:
        self.records = records
        self.fetcher = fetcher

    def run(
        self,
        job: Job,
        *,
        max_urls: int = DEFAULT_MAX_URLS,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        progress: Progress | None = None,
    ) -> AcquisitionResult:
        raw = self.records.read(job.payload["manifest_artifact_id"])
        refs = references_from_manifest(raw)
        self._save_references(refs)
        urls: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if (
                ref.reference_status == "RESOLVED"
                and ref.resolved_url
                and ref.resolved_url not in seen
            ):
                seen.add(ref.resolved_url)
                urls.append(ref.resolved_url)
        selected = urls[: max(0, max_urls)]
        acquired = skipped = failed = total_bytes = 0
        for index, url in enumerate(selected, start=1):
            status = self._current_status(url)
            if status == "ACQUIRED":
                self._record_attempt(job.job_id, url, "SKIPPED", None, None, "ALREADY_ACQUIRED")
                skipped += 1
            elif total_bytes >= max_total_bytes:
                self._record_attempt(job.job_id, url, "SKIPPED", None, None, "BATCH_BYTE_LIMIT")
                skipped += 1
            else:
                try:
                    downloaded = self.fetcher(
                        url, min(MAX_IMAGE_BYTES, max_total_bytes - total_bytes)
                    )
                    verified = validate_image(downloaded.body)
                    blob = self._put_blob(downloaded.body)
                    self._save_acquired(
                        url, blob, downloaded.content_type, {**downloaded.metadata, **verified}
                    )
                    self._record_attempt(job.job_id, url, "ACQUIRED", blob, blob.size_bytes, None)
                    acquired += 1
                    total_bytes += blob.size_bytes
                except ValueError as exc:
                    self._save_failed(url, str(exc))
                    self._record_attempt(job.job_id, url, "FAILED", None, None, str(exc))
                    failed += 1
            if progress is not None:
                progress(
                    {
                        "image_urls_done": index,
                        "image_urls_total": len(selected),
                        "image_acquired": acquired,
                        "image_skipped": skipped,
                        "image_failed": failed,
                        "image_bytes_stored": total_bytes,
                    }
                )
        return AcquisitionResult(len(refs), len(selected), acquired, skipped, failed, total_bytes)

    def _put_blob(self, raw: bytes) -> Blob:
        blob = self.records.store.put(raw)
        with self.records.db.connect() as conn:
            conn.execute(
                """INSERT INTO blobs(sha256,storage_key,size_bytes) VALUES(%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (blob.sha256, blob.storage_key, blob.size_bytes),
            )
        return blob

    def _save_references(self, refs: Iterable[ImageReference]) -> None:
        from psycopg.types.json import Jsonb

        with self.records.db.connect() as conn:
            for ref in refs:
                conn.execute(
                    """INSERT INTO image_references
                       (reference_id,manifest_hash,source_system,source_id,row_position,
                        occurrence_order,original_src,image_name,resolved_url,reference_status,
                        reason,context)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT DO NOTHING""",
                    (
                        ref.reference_id,
                        ref.manifest_hash,
                        ref.source_system,
                        ref.source_id,
                        ref.row_position,
                        ref.occurrence_order,
                        ref.original_src,
                        ref.image_name,
                        ref.resolved_url,
                        ref.reference_status,
                        ref.reason,
                        Jsonb(ref.context),
                    ),
                )

    def _current_status(self, url: str) -> str | None:
        with self.records.db.connect() as conn:
            row = conn.execute(
                "SELECT status FROM image_acquisitions WHERE url=%s", (url,)
            ).fetchone()
        return row["status"] if row else None

    def _save_acquired(
        self, url: str, blob: Blob, content_type: str | None, metadata: dict[str, Any]
    ) -> None:
        from psycopg.types.json import Jsonb

        with self.records.db.connect() as conn:
            conn.execute(
                """INSERT INTO image_acquisitions
                   (url,status,blob_hash,size_bytes,content_type,image_metadata,attempts,last_error_code)
                   VALUES(%s,'ACQUIRED',%s,%s,%s,%s,1,NULL)
                   ON CONFLICT(url) DO UPDATE SET
                   status='ACQUIRED', blob_hash=EXCLUDED.blob_hash,
                   size_bytes=EXCLUDED.size_bytes, content_type=EXCLUDED.content_type,
                   image_metadata=EXCLUDED.image_metadata, attempts=image_acquisitions.attempts+1,
                   last_error_code=NULL, updated_at=clock_timestamp()""",
                (url, blob.sha256, blob.size_bytes, content_type, Jsonb(metadata)),
            )

    def _save_failed(self, url: str, error_code: str) -> None:
        with self.records.db.connect() as conn:
            conn.execute(
                """INSERT INTO image_acquisitions(url,status,attempts,last_error_code)
                   VALUES(%s,'FAILED',1,%s)
                   ON CONFLICT(url) DO UPDATE SET status='FAILED', blob_hash=NULL,
                   size_bytes=NULL, content_type=NULL, image_metadata='{}'::jsonb,
                   attempts=image_acquisitions.attempts+1, last_error_code=EXCLUDED.last_error_code,
                   updated_at=clock_timestamp()""",
                (url, error_code),
            )

    def _record_attempt(
        self,
        job_id: UUID,
        url: str,
        outcome: AttemptOutcome,
        blob: Blob | None,
        size_bytes: int | None,
        error_code: str | None,
    ) -> None:
        if outcome == "SKIPPED" and self._current_status(url) is None:
            with self.records.db.connect() as conn:
                conn.execute(
                    """INSERT INTO image_acquisitions(url,status,attempts,last_error_code)
                       VALUES(%s,'SKIPPED',0,%s)""",
                    (url, error_code),
                )
        attempt_id = uuid5(
            NAMESPACE_URL, json.dumps([str(job_id), url, outcome, error_code], sort_keys=True)
        )
        with self.records.db.connect() as conn:
            conn.execute(
                """INSERT INTO image_acquisition_attempts
                   (attempt_id,job_id,url,outcome,blob_hash,size_bytes,error_code)
                   VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    attempt_id,
                    job_id,
                    url,
                    outcome,
                    blob.sha256 if blob else None,
                    size_bytes,
                    error_code,
                ),
            )
