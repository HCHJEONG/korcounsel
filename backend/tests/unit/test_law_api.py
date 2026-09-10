"""Synthetic protocol regressions; these are not live provider behavior evidence."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from klegal_gold.sources.law_api import (
    LawOpenApiCaseSource,
    Response,
    SourceError,
    list_sample,
)

SECRET = "synthetic-credential-never-persist"


def response(data, status=200):
    body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
    return Response(body, status, "application/json", "https://www.law.go.kr/", datetime.now(UTC))


class FakeTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = 0

    def get(self, endpoint, params, progress):
        self.calls += 1
        assert params["OC"] == SECRET
        progress()
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result


def source(replies, **kwargs):
    preserved, waits = [], []
    transport = FakeTransport(replies)
    client = LawOpenApiCaseSource(
        SecretStr(SECRET),
        transport=transport,
        preserve=preserved.append,
        sleep=waits.append,
        **kwargs,
    )
    return client, preserved, transport, waits


def listing(page=1, total=1, rows=None):
    return {
        "PrecSearch": {
            "page": str(page),
            "totalCnt": str(total),
            "prec": {"판례일련번호": "195490"} if rows is None else rows,
        }
    }


def test_singleton_and_empty_page():
    client, saved, _, _ = source([response(listing()), response(listing(2, 1, []))])
    assert client.list_page(page=1, display=1).ids == ("195490",)
    assert client.list_page(page=2, display=1).ids == ()
    assert len(saved) == 2
    assert all("OC=" not in r.safe_url for r in saved)


@pytest.mark.parametrize(
    "data,code",
    [
        (b"<html>error</html>", "RESPONSE_PARSE_FAILED"),
        ({"error": "bad OC"}, "UNEXPECTED_RESPONSE_SCHEMA"),
        ({"PrecSearch": {}}, "INVALID_COUNT"),
        (listing(2), "PAGE_MISMATCH"),
        (listing(total=2, rows=[]), "PARTIAL_PAGE"),
        (
            listing(total=2, rows=[{"판례일련번호": "1"}, {"판례일련번호": "1"}]),
            "DUPLICATE_SOURCE_ID",
        ),
        (listing(rows={"판례일련번호": True}), "INVALID_SOURCE_ID"),
        (listing(rows={"판례일련번호": "1x"}), "INVALID_SOURCE_ID"),
        (b'{"PrecSearch":{},"PrecSearch":{}}', "DUPLICATE_RESPONSE_FIELD"),
        (b"\xff", "RESPONSE_PARSE_FAILED"),
    ],
)
def test_bad_responses_are_preserved_before_rejected(data, code):
    client, saved, _, _ = source([response(data)])
    with pytest.raises(SourceError, match=code):
        client.list_page(page=1)
    assert len(saved) == 1


def test_retry_and_preserve_every_response():
    client, saved, transport, waits = source(
        [
            response(b"temporarily unavailable", 503),
            SourceError("TRANSPORT_FAILED"),
            response({"PrecService": {"판례정보일련번호": "195490", "판결요지": ""}}),
        ]
    )
    result = client.fetch_detail("195490")
    assert result.fields["판결요지"] == ""
    assert transport.calls == 3 and waits == [1, 2, 4]
    assert [r.status for r in saved] == [503, 200]


@pytest.mark.parametrize("status", [301, 302, 400, 401, 403, 404])
def test_no_retry_or_redirect_on_rejected_status(status):
    client, saved, transport, _ = source([response(b"error", status)])
    with pytest.raises(SourceError, match="HTTP_REJECTED"):
        client.fetch_detail("1")
    assert transport.calls == 1 and len(saved) == 1


def test_bounded_retry_exhaustion():
    client, saved, transport, _ = source([response(b"busy", 429)] * 3)
    with pytest.raises(SourceError, match="HTTP_RETRIES_EXHAUSTED"):
        client.fetch_detail("1")
    assert len(saved) == transport.calls == 3


def test_oc_echo_is_preserved_exactly(caplog):
    data = listing()
    data["PrecSearch"]["OC"] = SECRET
    raw = response(data)
    client, saved, _, _ = source([raw])
    assert client.list_page(page=1, display=1).ids == ("195490",)
    assert saved[0].body == raw.body
    assert SECRET not in caplog.text


def test_detail_identity_mismatch():
    client, saved, _, _ = source([response({"PrecService": {"판례정보일련번호": "2"}})])
    with pytest.raises(SourceError, match="DETAIL_ID_MISMATCH"):
        client.fetch_detail("1")
    assert len(saved) == 1


@pytest.mark.parametrize("page,display", [(0, 20), (True, 20), (1, 101), (1, 0)])
def test_invalid_page_makes_no_request(page, display):
    client, _, transport, _ = source([])
    with pytest.raises(SourceError, match="INVALID_PAGINATION"):
        client.list_page(page=page, display=display)
    assert transport.calls == 0


def test_xml_cdata_is_preserved():
    raw = (
        "<PrecService><판례정보일련번호>1</판례정보일련번호>"
        "<판례내용><![CDATA[<p>원문</p>]]></판례내용><판결요지/></PrecService>"
    ).encode()
    client, saved, _, _ = source([response(raw)], format="XML")
    assert client.fetch_detail("1").fields["판례내용"] == "<p>원문</p>"
    assert saved[0].body == raw


def test_xml_entities_rejected():
    client, saved, _, _ = source([response(b"<!DOCTYPE x><PrecService/>")], format="XML")
    with pytest.raises(SourceError, match="UNSAFE_XML"):
        client.fetch_detail("1")
    assert saved


@pytest.mark.parametrize(
    "second,reason",
    [
        (listing(2, 3, [{"판례일련번호": "2"}]), "TOTAL_CHANGED"),
        (listing(2, 2, [{"판례일련번호": "195490"}]), "REPEATED_PAGE_IDS"),
    ],
)
def test_unstable_pagination(second, reason):
    client, saved, _, _ = source([response(listing(1, 2)), response(second)])
    with pytest.raises(SourceError, match=reason):
        list_sample(client, max_pages=2, display=1)
    assert len(saved) == 2


def test_bounded_sample_does_not_claim_full_inventory():
    client, _, transport, _ = source([response(listing(1, 100))])
    pages = list_sample(client, max_pages=1, display=1)
    assert pages[0].total == 100 and transport.calls == 1
