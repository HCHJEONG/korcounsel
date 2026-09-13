import json
from types import SimpleNamespace

import pytest

from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.enrichment.current_lawgo import CurrentLawgo
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration


def test_provider_enrichment_preserves_original_positions_and_restarts(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    store = ReaderStore(records)
    html = (
        '<p>앞<a name="linkPrvs">형법 제246조</a>뒤</p>'
        '<a name="linkPrvs">형법 제355조</a>'
        '<a name="linkPrvs">제공하지 않은 조문</a>'
    )
    provenance = {
        "court": "대법원",
        "case_number": "2017도953",
        "decision_type": "판결",
        "decision_date": "20170413",
    }
    doc = store.preserve(
        html,
        title="대법원 2017도953 판결",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance=provenance,
        acquisitions={},
    )
    before = records.read("reader:" + doc)
    frame = """<input id="precYd" value="20170413">
    <a onclick="javascript:fncLawPop('형법','JO','024600','prec');">형법 제246조</a>
    <a onclick="javascript:fncLawPop('형법','JO','035500','prec');">형법 제355조</a>"""
    records.put_artifact("frame", frame.encode(), origin="HTTP_RESPONSE", metadata={})
    from klegal_gold.enrichment.current_lawgo import provider_links

    _, links = provider_links(frame)
    plan = {
        "status": "EXACT",
        "source_id": "195490",
        "day": "20170413",
        "frame_artifact_id": "frame",
        "links": links,
    }
    records.put_artifact(
        "current-lawgo:test:plan", json.dumps(plan).encode(), origin="DERIVED", metadata={}
    )
    calls = []

    def request(self, endpoint, params, key):
        calls.append(params["joNo"])
        if params["joNo"] == "035500":
            raise ValueError("LAWGO_TRANSPORT_FAILED")
        table = (
            '<table summary="조문정보"><tbody id="lsLinkTable">'
            "<tr><td>제246조 보존 내용</td></tr></tbody></table>"
        )
        records.put_artifact(key, table.encode(), origin="HTTP_RESPONSE", metadata={})
        return table.encode()

    monkeypatch.setattr(CurrentLawgo, "_request", request)
    revision = CurrentLawgo(records).run(doc, "test", lambda: None)
    assert calls == ["024600", "035500"]
    manifest = store.read(revision)
    assert [a["provider_status"] for a in manifest["statutes"]] == [
        "PRESERVED",
        "FAILED",
        "UNLINKED",
    ]
    assert records.read("reader:" + doc) == before
    assert manifest["html_sha256"] == store.read(doc)["html_sha256"]
    rendered = store.html(revision)
    assert "제246조 보존 내용" in rendered and "제공 조문 취득 실패" in rendered
    assert "조문 내용 미연결" in rendered and "적용 버전 미확인" in rendered
    assert store.refresh_current_images(revision) != revision
    assert "제246조 보존 내용" in store.html(store.refresh_current_images(revision))
    assert CurrentLawgo(records).run(doc, "test", lambda: None) == revision


def test_unmatched_lawgo_is_not_case_failure(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    store = ReaderStore(records)
    doc = store.preserve(
        '<a name="linkPrvs">인용</a>',
        title="unmatched",
        source_id="1",
        origin="CURRENT_SOURCE",
        provenance={"case_number": "2017도953"},
        acquisitions={},
    )
    monkeypatch.setattr(
        "klegal_gold.enrichment.current_lawgo.load_settings",
        lambda: SimpleNamespace(law_api_credential=None),
    )
    revision = CurrentLawgo(records).run(doc, "no-credential", lambda: None)
    assert store.read(revision)["provenance"]["lawgo_status"] == "CREDENTIAL_UNAVAILABLE"
    assert "보강 대기" in store.html(revision)


def test_error_response_is_preserved_and_remains_failed_on_resume(db, tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from klegal_gold.sources.law_api import Response

    records = Records(db, FileStore(tmp_path))
    calls = []

    def fetch(endpoint, params):
        calls.append(endpoint)
        return Response(
            b"provider error",
            503,
            "text/html",
            "https://www.law.go.kr/LSW/lsLinkProc.do",
            datetime.now(UTC),
        )

    monkeypatch.setattr("klegal_gold.enrichment.current_lawgo.fetch_provider_html", fetch)
    for _ in range(2):
        with pytest.raises(ValueError, match="LAWGO_HTTP_ERROR"):
            CurrentLawgo(records)._request("lsLinkProc.do", {}, "response-test")
    assert records.read("response-test") == b"provider error"
    assert len(calls) == 1
