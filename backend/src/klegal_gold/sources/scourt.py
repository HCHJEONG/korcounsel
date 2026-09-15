"""Current public portal detail adapter, based on observed September 2026 requests.

jisCntntsSrno is recorded as the observed portal identifier; this module does not
automatically equate every portal identifier with every legacy contId.
"""

import json
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from http.client import HTTPException
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from klegal_gold.sources.law_api import (
    MAX_BYTES,
    Detail,
    Listing,
    Progress,
    Response,
    SourceError,
    _count,
    _NoRedirect,
    _object_pairs,
    identifier,
)

BASE = "https://portal.scourt.go.kr/pgp/pgp1011/"
VERSION = "scourt-portal-2"


def validate_window(date_from: str | None, date_to: str | None) -> None:
    if date_from is None and date_to is None:
        return
    if not date_from or not date_to:
        raise SourceError("INCOMPLETE_DATE_WINDOW")
    try:
        first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError:
        raise SourceError("INVALID_DATE_WINDOW") from None
    if (
        first.isoformat() != date_from
        or last.isoformat() != date_to
        or not 0 <= (last - first).days <= 92
    ):
        raise SourceError("INVALID_DATE_WINDOW")


def window_params(
    query: str, page: int, display: int, date_from: str, date_to: str
) -> dict[str, Any]:
    validate_window(date_from, date_to)
    return {
        "dma_searchParam": {
            "srchwd": query,
            "sort": (
                "jis_jdcpc_instn_dvs_cd_s asc, $relevance desc, "
                "prnjdg_ymd_o desc, jdcpct_gr_cd_s asc"
            ),
            "sortType": "정확도",
            "searchRange": "",
            "tpcJdcpctCsAlsYn": "",
            "csNoLstCtt": "",
            "csNmLstCtt": "",
            "prvsRefcCtt": "",
            "searchScope": "",
            "jisJdcpcInstnDvsCd": "",
            "jdcpctCdcsCd": "",
            "prnjdgYmdFrom": date_from.replace("-", ""),
            "prnjdgYmdTo": date_to.replace("-", ""),
            "grpJdcpctGrCd": "",
            "cortNm": "",
            "pageNo": str(page),
            "jisJdcpcInstnDvsCdGrp": "",
            "grpJdcpctGrCdGrp": "",
            "jdcpctCdcsCdGrp": "",
            "adjdTypCdGrp": "",
            "pageSize": str(display),
            "reSrchFlag": "",
            "befSrchwd": "",
            "preSrchConditions": "",
            "initYn": "N",
            "jdcpctGrCd": "111|112|130|141|180|182|232|235",
            "category": "jdcpct",
            "isKwdSearch": "N",
        }
    }


def listing_params(query: str, page: int, display: int) -> dict[str, Any]:
    return {
        "dma_searchParam": {
            "category": "jdcpct",
            "srchwd": query,
            "pageSize": str(display),
            "pageNo": str(page),
            "jdcpctGrCd": "111|112|130|141|180|182|232|235",
            "crntLawDvsCd": "02",
            "chnchrYn": "N",
            "gb": "lst",
            "isKwdSearch": "N",
            "crntClCd": "01",
            "sort": (
                "jis_jdcpc_instn_dvs_cd_s asc, $relevance desc, "
                "prnjdg_ymd_o desc, jdcpct_gr_cd_s asc"
            ),
            "sortType": "정확도",
        }
    }


class PortalTransportProtocol(Protocol):
    def post(self, endpoint: str, source_id: str, progress: Progress) -> Response: ...

    def post_listing(self, query: str, page: int, display: int, progress: Progress) -> Response: ...

    def post_window_listing(self, params: dict[str, Any], progress: Progress) -> Response: ...


class PortalTransport:
    def post(self, endpoint: str, source_id: str, progress: Progress) -> Response:
        if endpoint not in {"selectJdcpctDtl.on", "selectJdcpctCtxt.on"}:
            raise SourceError("INVALID_ENDPOINT")
        source_id = identifier(source_id)
        params = {
            "dma_searchParam": {
                "jisCntntsSrno": source_id,
                "srchwd": "",
                "csNoLstCtt": "",
                "cortNm": "",
                "adjdTypNm": "",
                "jdcpctBrncNo": "",
                "jdcpctGrCd": "A1|A2|C|D3|H|H2|W2|W5",
                "chnchrYn": "N",
                "systmNm": "PGP",
            }
        }
        return self._send(BASE + endpoint, params, progress)

    def post_listing(self, query: str, page: int, display: int, progress: Progress) -> Response:
        params = listing_params(query, page, display)
        return self._send(
            "https://portal.scourt.go.kr/pgp/pgp1001/selectTotalSrchLst.on", params, progress
        )

    def post_window_listing(self, params: dict[str, Any], progress: Progress) -> Response:
        return self._send(BASE + "selectJdcpctSrchRsltLst.on", params, progress)

    def _send(self, url: str, params: dict[str, Any], progress: Progress) -> Response:
        request = Request(
            url,
            data=json.dumps(params).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "KorCounsel/0.1",
            },
        )
        started = time.monotonic()
        try:
            try:
                reply = build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=15)
            except HTTPError as exc:
                reply = exc
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
                    url,
                    datetime.now(UTC),
                )
        except (URLError, OSError, HTTPException):
            raise SourceError("TRANSPORT_FAILED") from None


def portal_data(response: Response, key: str, source_id: str) -> dict[str, Any]:
    try:
        value = json.loads(response.body.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise SourceError("RESPONSE_PARSE_FAILED") from None
    if not isinstance(value, dict) or value.get("status") != 200 or value.get("errors"):
        raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
    data = value.get("data")
    if isinstance(data, dict) and data.get("result") == "notExtist":
        raise SourceError("SOURCE_NOT_FOUND")
    result = data.get(key) if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
    if identifier(result.get("jisCntntsSrno")) != source_id:
        raise SourceError("DETAIL_ID_MISMATCH")
    return dict(result)


class ScourtPortalSource:
    def __init__(
        self,
        *,
        preserve: Callable[[Response], None],
        transport: PortalTransportProtocol | None = None,
        progress: Progress = lambda: None,
        sleep: Callable[[float], None] = time.sleep,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> None:
        validate_window(date_from, date_to)
        self.date_from, self.date_to = date_from, date_to
        self.transport = transport or PortalTransport()
        self.preserve, self.progress, self.sleep = preserve, progress, sleep

    def _request(self, endpoint: str, source_id: str) -> Response:
        self.progress()
        self.sleep(1)
        self.progress()
        response = self.transport.post(endpoint, source_id, self.progress)
        self._preserve(response)
        return response

    def _preserve(self, response: Response) -> None:
        # Public endpoints currently return token:null. Quarantine, never persist a token
        # if that changes. A failed JSON parse still remains available for diagnosis.
        try:
            parsed = json.loads(response.body)
        except (ValueError, UnicodeError):
            parsed = None
        if isinstance(parsed, dict) and parsed.get("token") is not None:
            raise SourceError("SENSITIVE_RESPONSE_NOT_PRESERVED")
        self.preserve(response)
        self.progress()
        if response.status != 200:
            raise SourceError("HTTP_REJECTED")

    def list_page(self, *, page: int, display: int = 20, docket: str = "") -> Listing:
        if type(page) is not int or page < 1 or type(display) is not int or not 1 <= display <= 100:
            raise SourceError("INVALID_PAGINATION")
        if len(docket) > 200:
            raise SourceError("INVALID_QUERY")
        self.progress()
        self.sleep(1)
        self.progress()
        if self.date_from and self.date_to:
            response = self.transport.post_window_listing(
                window_params(docket, page, display, self.date_from, self.date_to), self.progress
            )
        else:
            response = self.transport.post_listing(docket, page, display, self.progress)
        self._preserve(response)
        try:
            value = json.loads(response.body.decode("utf-8-sig"), object_pairs_hook=_object_pairs)
        except (UnicodeError, json.JSONDecodeError):
            raise SourceError("RESPONSE_PARSE_FAILED") from None
        if not isinstance(value, dict) or value.get("status") != 200 or value.get("errors"):
            raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
        data = value.get("data")
        if not isinstance(data, dict) or str(data.get("status")) != "200":
            raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
        total = _count(data.get("totalCount"))
        rows = data.get("dlt_jdcpctRslt")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SourceError("UNEXPECTED_RESPONSE_SCHEMA")
        if len(rows) != min(display, max(0, total - (page - 1) * display)):
            raise SourceError("PARTIAL_PAGE")
        ids = [identifier(row.get("jisCntntsSrno")) for row in rows]
        if len(ids) != len(set(ids)):
            raise SourceError("DUPLICATE_SOURCE_ID")
        if self.date_from and self.date_to:
            for row in rows:
                day = str(row.get("prnjdgYmd", ""))
                if len(day) != 8 or not day.isdigit():
                    raise SourceError("INVALID_LISTING_DATE")
                try:
                    date(int(day[:4]), int(day[4:6]), int(day[6:]))
                except ValueError:
                    raise SourceError("INVALID_LISTING_DATE") from None
                if not self.date_from.replace("-", "") <= day <= self.date_to.replace("-", ""):
                    raise SourceError("LISTING_OUTSIDE_DATE_WINDOW")
        return Listing(response, page, total, tuple(rows), "jisCntntsSrno")

    def fetch_detail(self, source_id: str) -> Detail:
        source_id = identifier(source_id)
        metadata = self._request("selectJdcpctDtl.on", source_id)
        fields = portal_data(metadata, "dma_jdcpctDtl", source_id)
        response = self._request("selectJdcpctCtxt.on", source_id)
        body = portal_data(response, "dma_jdcpctCtxt", source_id)
        html = body.get("orgdocXmlCtt")
        if not isinstance(html, str) or not html.strip():
            raise SourceError("BODY_STRUCTURE_MISSING")
        # Preserve original markup; do not synthesize missing editorial fields or offsets.
        fields["body"] = body
        fields["metadata_response_hash"] = metadata.sha256
        return Detail(response, source_id, fields)
