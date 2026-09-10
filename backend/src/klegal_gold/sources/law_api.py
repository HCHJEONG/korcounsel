"""Bounded official precedent API acquisition with an injectable transport.

Response bytes are preserved by the caller BEFORE schema validation.
OC is a non-secret caller identifier under the user-confirmed project policy.
Its presence in a response must not block or alter RAW preservation.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.client import HTTPException
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import SecretStr

from klegal_gold.domain.common import content_hash

BASE = "https://www.law.go.kr/DRF/"
VERSION = "law-api-2"
MAX_BYTES = 16 * 1024 * 1024
Progress = Callable[[], None]


class SourceError(ValueError):
    """Only project-owned reason codes, never response text or request URLs."""


@dataclass(frozen=True)
class Response:
    body: bytes = field(repr=False)
    status: int
    mime_type: str
    safe_url: str
    retrieved_at: datetime
    attempts: int = 1

    @property
    def sha256(self) -> str:
        return content_hash(self.body)


class Transport(Protocol):
    def get(self, endpoint: str, params: Mapping[str, str], progress: Progress) -> Response: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class UrllibTransport:
    """No request logging, redirects, cookies, ambient proxy or unlimited reads."""

    def get(self, endpoint: str, params: Mapping[str, str], progress: Progress) -> Response:
        if endpoint not in {"lawSearch.do", "lawService.do"}:
            raise SourceError("INVALID_ENDPOINT")
        from urllib.request import ProxyHandler

        safe_url = BASE + endpoint + "?" + urlencode({k: v for k, v in params.items() if k != "OC"})
        request = Request(
            BASE + endpoint + "?" + urlencode(params),
            headers={"Accept-Encoding": "identity", "User-Agent": "KorCounsel/0.1"},
        )
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        started = time.monotonic()
        try:
            try:
                reply = opener.open(request, timeout=15)
            except HTTPError as exc:
                reply = exc  # Preserve bounded error responses too; never stringify exc.
            with reply:
                body = bytearray()
                while True:
                    progress()
                    if time.monotonic() - started > 30:
                        raise SourceError("RESPONSE_DEADLINE")
                    chunk = reply.read1(65536)
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise SourceError("RESPONSE_TOO_LARGE")
                return Response(
                    bytes(body),
                    reply.code,
                    reply.headers.get_content_type(),
                    safe_url,
                    datetime.now(UTC),
                )
        except (URLError, OSError, HTTPException):
            raise SourceError("TRANSPORT_FAILED") from None


@dataclass(frozen=True)
class Listing:
    response: Response
    page: int
    total: int
    rows: tuple[dict[str, Any], ...]
    id_field: str = "판례일련번호"

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(str(row[self.id_field]) for row in self.rows)


@dataclass(frozen=True)
class Detail:
    response: Response
    source_id: str
    fields: dict[str, Any] = field(repr=False)


class CaseSource(Protocol):
    def list_page(self, *, page: int, display: int = 20, docket: str = "") -> Listing: ...
    def fetch_detail(self, source_id: str) -> Detail: ...


def identifier(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SourceError("INVALID_SOURCE_ID")
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise SourceError("INVALID_SOURCE_ID")
    return text


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SourceError("INVALID_COUNT")
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise SourceError("INVALID_COUNT")
    return int(value)


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceError("DUPLICATE_RESPONSE_FIELD")
        result[key] = value
    return result


def decode(response: Response, root_name: str, format: str) -> dict[str, Any]:
    try:
        text = response.body.decode("utf-8-sig", errors="strict")
        if format == "JSON":
            document = json.loads(text, object_pairs_hook=_object_pairs)
            if (
                isinstance(document, dict)
                and root_name == "PrecService"
                and document.get("Law") == "일치하는 판례가 없습니다.  판례명을 확인하여 주십시오."
            ):
                raise SourceError("SOURCE_NOT_FOUND")
            if not isinstance(document, dict) or not isinstance(document.get(root_name), dict):
                raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
            return dict(document[root_name])
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise SourceError("UNSAFE_XML")
        root = ET.fromstring(text)
        if root.tag != root_name:
            raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
        result: dict[str, Any] = {}
        for child in root:
            if child.tag == "prec" and root_name == "PrecSearch":
                row = _object_pairs([(item.tag, item.text or "") for item in child])
                result.setdefault("prec", []).append(row)
            else:
                if child.tag in result or len(child):
                    raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
                result[child.tag] = child.text or ""
        return result
    except (UnicodeError, json.JSONDecodeError, ET.ParseError):
        raise SourceError("RESPONSE_PARSE_FAILED") from None


class LawOpenApiCaseSource:
    def __init__(
        self,
        credential: SecretStr,
        *,
        transport: Transport | None = None,
        preserve: Callable[[Response], None],
        progress: Progress = lambda: None,
        sleep: Callable[[float], None] = time.sleep,
        format: str = "JSON",
        max_attempts: int = 3,
    ) -> None:
        if not credential.get_secret_value() or format not in {"JSON", "XML"}:
            raise SourceError("INVALID_SOURCE_CONFIGURATION")
        if not 1 <= max_attempts <= 3:
            raise SourceError("INVALID_RETRY_LIMIT")
        self._credential = credential
        self.transport = transport or UrllibTransport()
        self.preserve, self.progress, self.sleep = preserve, progress, sleep
        self.format, self.max_attempts = format, max_attempts

    def _request(self, endpoint: str, query: dict[str, str]) -> Response:
        params = {
            "OC": self._credential.get_secret_value(),
            "target": "prec",
            "type": self.format,
            **query,
        }
        # One second before EVERY request, including first/retry. Conservative local policy,
        # not a provider quota. Single worker provides process-wide serialization.
        for attempt in range(1, self.max_attempts + 1):
            self.progress()
            self.sleep(float(2 ** (attempt - 1)))
            self.progress()
            try:
                response = self.transport.get(endpoint, params, self.progress)
            except SourceError as exc:
                if str(exc) not in {"TRANSPORT_FAILED", "RESPONSE_DEADLINE"}:
                    raise
                if attempt == self.max_attempts:
                    raise SourceError("TRANSPORT_RETRIES_EXHAUSTED") from None
                continue
            response = Response(
                response.body,
                response.status,
                response.mime_type,
                BASE + endpoint + "?" + urlencode({k: v for k, v in params.items() if k != "OC"}),
                response.retrieved_at,
                attempt,
            )
            # OC may be echoed by the provider. Preserve exact bytes without redaction.
            self.preserve(response)
            self.progress()
            if response.status == 200:
                return response
            if response.status not in {408, 429, 500, 502, 503, 504}:
                raise SourceError("HTTP_REJECTED")
            if attempt == self.max_attempts:
                raise SourceError("HTTP_RETRIES_EXHAUSTED")
        raise SourceError("TRANSPORT_RETRIES_EXHAUSTED")

    def list_page(self, *, page: int, display: int = 20, docket: str = "") -> Listing:
        if type(page) is not int or page < 1 or type(display) is not int or not 1 <= display <= 100:
            raise SourceError("INVALID_PAGINATION")
        if len(docket) > 200:
            raise SourceError("INVALID_QUERY")
        query = {"page": str(page), "display": str(display)}
        if docket:
            query["nb"] = docket
        response = self._request("lawSearch.do", query)
        data = decode(response, "PrecSearch", self.format)
        total = _count(data.get("totalCnt"))
        if _count(data.get("page")) != page:
            raise SourceError("PAGE_MISMATCH")
        rows = data.get("prec")
        if rows is None or rows == "":
            rows = []
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
        expected = min(display, max(0, total - (page - 1) * display))
        if len(rows) != expected:
            raise SourceError("PARTIAL_PAGE")
        ids = [identifier(row.get("판례일련번호")) for row in rows]
        if len(ids) != len(set(ids)):
            raise SourceError("DUPLICATE_SOURCE_ID")
        return Listing(response, page, total, tuple(rows))

    def fetch_detail(self, source_id: str) -> Detail:
        source_id = identifier(source_id)
        response = self._request("lawService.do", {"ID": source_id})
        data = decode(response, "PrecService", self.format)
        if identifier(data.get("판례정보일련번호")) != source_id:
            raise SourceError("DETAIL_ID_MISMATCH")
        # Empty editorial fields are valid; a missing/wrong identity or wrong root is not.
        for key in ("판시사항", "판결요지", "참조조문", "참조판례", "판례내용"):
            if key in data and data[key] is not None and not isinstance(data[key], str):
                raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
        return Detail(response, source_id, data)


def list_sample(
    source: CaseSource, *, max_pages: int, display: int = 20, docket: str = ""
) -> tuple[Listing, ...]:
    """Bounded sample, never an assertion of a stable complete source inventory."""
    if type(max_pages) is not int or not 1 <= max_pages <= 10:
        raise SourceError("INVALID_SAMPLE_LIMIT")
    pages: list[Listing] = []
    seen: set[str] = set()
    total: int | None = None
    for page in range(1, max_pages + 1):
        result = source.list_page(page=page, display=display, docket=docket)
        if total is not None and total != result.total:
            raise SourceError("TOTAL_CHANGED")
        if seen.intersection(result.ids):
            raise SourceError("REPEATED_PAGE_IDS")
        pages.append(result)
        total = result.total
        seen.update(result.ids)
        if page * display >= total:
            break
    return tuple(pages)
