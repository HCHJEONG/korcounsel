"""Observed September 2026 fixtures plus explicitly synthetic failure variants."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

from klegal_gold.sources.law_api import LawOpenApiCaseSource, Response, SourceError
from klegal_gold.sources.scourt import ScourtPortalSource

FIXTURES = Path(__file__).parents[1] / "fixtures/sources"


class PortalFake:
    def __init__(self, raws):
        self.raws = iter(raws)

    def post(self, endpoint, source_id, progress):
        progress()
        return Response(
            next(self.raws),
            200,
            "application/json",
            "https://portal.scourt.go.kr/pgp/pgp1011/" + endpoint,
            datetime.now(UTC),
        )


@pytest.mark.parametrize("source_id,start", [("2252318", 0), ("3328392", 2)])
def test_observed_portal_details(source_id, start):
    raws = [(FIXTURES / f"scourt-{i}.json").read_bytes() for i in (start, start + 1)]
    saved = []
    source = ScourtPortalSource(
        transport=PortalFake(raws), preserve=saved.append, sleep=lambda _: None
    )
    detail = source.fetch_detail(source_id)
    assert str(detail.fields["jisCntntsSrno"]) == source_id
    assert detail.fields["body"]["orgdocXmlCtt"].strip()
    assert saved[1].body == raws[1]
    assert len(saved) == 2


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("empty", "BODY_STRUCTURE_MISSING"),
        ("id", "DETAIL_ID_MISMATCH"),
        ("token", "SENSITIVE_RESPONSE_NOT_PRESERVED"),
        ("error", "UNEXPECTED_RESPONSE_SCHEMA"),
    ],
)
def test_portal_failure_never_becomes_empty_case(mutation, code):
    meta = (FIXTURES / "scourt-0.json").read_bytes()
    body = json.loads((FIXTURES / "scourt-1.json").read_bytes())
    if mutation == "empty":
        body["data"]["dma_jdcpctCtxt"]["orgdocXmlCtt"] = ""
    elif mutation == "id":
        body["data"]["dma_jdcpctCtxt"]["jisCntntsSrno"] = 999
    elif mutation == "token":
        body["token"] = "synthetic-sensitive-token"
    else:
        body["status"] = 500
    saved = []
    source = ScourtPortalSource(
        transport=PortalFake([meta, json.dumps(body).encode()]),
        preserve=saved.append,
        sleep=lambda _: None,
    )
    with pytest.raises(SourceError, match=code):
        source.fetch_detail("2252318")
    assert len(saved) == (1 if mutation == "token" else 2)


def test_fixture_hashes_match_observed_manifest():
    for record in json.loads((FIXTURES / "manifest.json").read_text()):
        assert (
            hashlib.sha256((FIXTURES / record["file"]).read_bytes()).hexdigest() == record["sha256"]
        )


@pytest.mark.parametrize(
    "index,format,source_id",
    [
        (0, "JSON", "195490"),
        (1, "JSON", "240889"),
        (2, "XML", "195490"),
        (3, "XML", "240889"),
    ],
)
def test_observed_law_api_details(index, format, source_id):
    suffix = format.lower()
    raw = (FIXTURES / f"law-{index}.{suffix}").read_bytes()

    class Transport:
        def get(self, endpoint, params, progress):
            return Response(
                raw, 200, "application/" + suffix, "https://www.law.go.kr/", datetime.now(UTC)
            )

    client = LawOpenApiCaseSource(
        SecretStr("test-fixture-secret"),
        transport=Transport(),
        preserve=lambda r: None,
        sleep=lambda _: None,
        format=format,
    )
    assert client.fetch_detail(source_id).fields["판결요지"] == ""
