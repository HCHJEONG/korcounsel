"""Bounded requests for the observed lawgo precedent frame and provider article layer."""

from datetime import UTC, datetime
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from klegal_gold.sources.law_api import Response, _NoRedirect


def fetch_provider_html(endpoint: str, params: dict[str, str]) -> Response:
    if endpoint not in {"precInfoP.do", "lsLinkProc.do"}:
        raise ValueError("INVALID_LAWGO_ENDPOINT")
    url = "https://www.law.go.kr/LSW/" + endpoint
    data = urlencode(params).encode()
    request = Request(
        url + "?" + data.decode() if endpoint == "precInfoP.do" else url,
        data=None if endpoint == "precInfoP.do" else data,
        headers={"Accept-Encoding": "identity", "User-Agent": "KorCounsel/0.1"},
    )
    try:
        try:
            reply = build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=20)
        except HTTPError as exc:
            reply = exc
        with reply:
            raw: bytes = reply.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError("LAWGO_RESPONSE_TOO_LARGE")
            return Response(
                raw,
                reply.code,
                reply.headers.get_content_type(),
                request.full_url,
                datetime.now(UTC),
            )
    except OSError:
        raise ValueError("LAWGO_TRANSPORT_FAILED") from None
