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
    <a onclick="javascript:fncLawPop('형법','JO','024600','prec20160101');">형법 제246조</a>
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
        if params["joNo"] == "024600":
            assert params["lsId"] == "prec20160101"
            assert params["efYd"] == "20160101"
        if params["joNo"] == "035500":
            raise ValueError("LAWGO_TRANSPORT_FAILED")
        table = (
            '<table summary="조문정보"><tbody id="lsLinkTable">'
            '<tr><td>제246조 보존 내용<img src="/flDownload.do?flSeq=123">'
            '<img src="/flDownload.do?flSeq=123"><img src="/flDownload.do?flSeq=456">'
            '<img src="https://example.invalid/missing.png"></td></tr></tbody></table>'
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
    from uuid import UUID

    from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
    from klegal_gold.jobs.queue import Queue
    from klegal_gold.jobs.worker import Worker

    gif = bytes.fromhex(
        "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
    )
    queue = Queue(db)
    retry = queue.submit_current_image_retry("statute-retry", revision)

    def fetch(url, limit):
        if url.endswith("456"):
            raise ValueError("IMAGE_NETWORK_ERROR")
        return DownloadedImage(gif, "image/gif", {})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda records: ImageAcquirer(records, fetcher=fetch),
    )
    worker = Worker(queue, records)
    for _ in range(3):
        worker.run_once()
    refresh = queue.get(UUID(queue.get(retry.job_id).checkpoint["follow_up_job_id"]))
    assert refresh.status == "SUCCEEDED"
    final = refresh.checkpoint["reader_document_id"]
    assert [r["status"] for r in store.read(final)["statute_images"]] == [
        "ACQUIRED",
        "ACQUIRED",
        "FAILED",
        "PENDING",
    ]
    assert store.statute_image(final, 0, 0)[0] == gif
    assert store.statute_image(final, 0, 1)[0] == gif
    assert store.read(final)["html_sha256"] == store.read(doc)["html_sha256"]
    assert store.read(revision)["statute_images"][0]["status"] == "PENDING"
    assert "/statutes/0/images/0" in store.html(final)


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


def test_admin_explicit_refresh_is_limited_to_observed_ids(db, tmp_path, monkeypatch):
    from importlib import import_module

    from fastapi.testclient import TestClient

    from klegal_gold.config import Settings
    from klegal_gold.web.auth import require_admin

    web = import_module("klegal_gold.web.app")
    settings = Settings(data_dir=tmp_path, database_url="postgresql://unused")
    monkeypatch.setattr(web, "load_settings", lambda: settings)
    monkeypatch.setattr(web.Database, "from_settings", lambda _: db)
    records = Records(db, FileStore(tmp_path))
    records.put_artifact(
        "inventory:sample",
        json.dumps(
            {
                "snapshot_id": "sample",
                "source": "scourt",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:00Z",
                "total_count": 1,
                "entries": [{"source_id": "123", "metadata_hash": "a" * 64}],
                "observed_unique_count": 1,
                "metadata_hash": "a" * 64,
                "scope": "{}",
                "scope_hash": "a" * 64,
                "collector_version": "test",
                "hash_rules_version": "test",
                "completeness": "UNKNOWN",
            }
        ).encode(),
        origin="DERIVED",
        metadata={},
    )
    records.put_artifact(
        "observed-delta",
        json.dumps(
            {
                "version": "inventory-delta-1",
                "current_snapshot_id": "sample",
                "source": "scourt",
                "scope_hash": "a" * 64,
                "absence_is_confirmed": False,
                "entries": [{"source_id": "123", "kind": "LEGACY_KNOWN"}],
            }
        ).encode(),
        origin="DERIVED",
        metadata={},
    )
    app = web.create_app()
    app.dependency_overrides[require_admin] = lambda: object()
    client = TestClient(app)
    headers = {"Origin": settings.web_origin}
    url = "/api/admin/deltas/observed-delta/scourt-details"
    assert client.post(url, headers=headers).json()["registered"] == 0
    assert client.post(url + "?refresh_source_id=456", headers=headers).status_code == 400
    assert client.post(url + "?refresh_source_id=123", headers=headers).json()["registered"] == 1


def test_same_article_with_different_provider_dates_is_ambiguous(db, tmp_path, monkeypatch):
    from klegal_gold.enrichment.current_lawgo import provider_links

    records = Records(db, FileStore(tmp_path))
    store = ReaderStore(records)
    doc = store.preserve(
        '<a name="linkPrvs">법 제1조</a>',
        title="date conflict",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    frame = '<input id="precYd" value="20110310">' + "".join(
        f"""<a onclick="fncLawPop('법','JO','000100','prec{day}');">법 제1조</a>"""
        for day in ["20100101", "20110101"]
    )
    _, links = provider_links(frame)
    records.put_artifact(
        "current-lawgo:date-conflict:plan",
        json.dumps({"status": "EXACT", "day": "20110310", "links": links}).encode(),
        origin="DERIVED",
        metadata={},
    )

    def no_request(*args):
        raise AssertionError("ambiguous versions must not be fetched")

    monkeypatch.setattr(CurrentLawgo, "_request", no_request)
    revision = CurrentLawgo(records).run(doc, "date-conflict", lambda: None)
    assert store.read(revision)["statutes"][0]["provider_status"] == "AMBIGUOUS"
    assert store.read(revision)["html_sha256"] == store.read(doc)["html_sha256"]
