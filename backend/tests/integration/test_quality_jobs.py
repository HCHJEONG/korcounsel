import json
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from klegal_gold.db.records import Records
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.fields.contract import VERSION
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.quality.service import execution, save
from klegal_gold.storage.files import FileStore
from klegal_gold.web.auth import require_admin, same_origin
from klegal_gold.web.quality import records as dependency

pytestmark = pytest.mark.integration


def reader(records, source="123"):
    metadata_id = "http:" + source
    records.put_artifact(
        metadata_id,
        json.dumps(
            {
                "data": {
                    "dma_jdcpctDtl": {
                        "jisCntntsSrno": source,
                        "prnjdgYmd": "20241001",
                        "csNoLstCtt": "2024다123",
                    }
                }
            }
        ).encode(),
        origin="HTTP_RESPONSE",
        metadata={},
    )
    return ReaderStore(records).preserve(
        "<p>【주문】기각</p><p>【이유】이유</p>",
        title="2024다123",
        source_id=source,
        origin="CURRENT_SOURCE",
        provenance={
            "metadata_response_hash": source,
            "source_artifact_id": metadata_id,
            "decision_date": "2024-10-01",
        },
        acquisitions={},
    )


def client_for(records):
    app = import_module("klegal_gold.web.app").create_app()
    app.dependency_overrides[dependency] = lambda: records
    app.dependency_overrides[require_admin] = lambda: uuid4()
    app.dependency_overrides[same_origin] = lambda: None
    return TestClient(app)


def test_audit_reprocess_auth_scope_and_immutable_results(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    document = reader(records)
    client = client_for(records)
    req = {"request_id": str(uuid4()), "date_from": "2024-10-01", "date_to": "2024-12-31"}
    result = client.post("/api/admin/quality/audits", json=req)
    assert result.status_code == 200
    assert client.post("/api/admin/quality/audits", json=req).json() == result.json()
    assert (
        client.post(
            "/api/admin/quality/audits", json={**req, "date_from": "2024-09-30"}
        ).status_code
        == 409
    )
    queue = Queue(db)
    worker = Worker(queue, records)
    assert worker.run_once()
    job = result.json()["job_id"]
    report = client.get("/api/admin/quality/jobs/" + job).json()["report"]
    assert report["count"] == 1 and report["summary"]["PENDING"]["cases"] == 1
    raw = records.read("quality:" + job + ":report")
    action = {
        "request_id": str(uuid4()),
        "audit_job_id": job,
        "action": "FIELDS",
        "document_ids": [document],
    }
    res = client.post("/api/admin/quality/reprocess", json=action)
    assert res.status_code == 200
    assert client.post("/api/admin/quality/reprocess", json=action).json() == res.json()
    assert (
        client.post(
            "/api/admin/quality/reprocess", json={**action, "document_ids": ["f" * 64]}
        ).status_code
        == 400
    )
    assert worker.run_once()  # dispatch only
    from uuid import UUID

    run = queue.get(UUID(res.json()["job_id"]))
    assert not execution(queue, run)["terminal"]  # parent SUCCEEDED is not whole-chain completion
    assert worker.run_once()  # fields
    assert execution(queue, queue.get(run.job_id))["terminal"]
    assert records.read("quality:" + job + ":report") == raw
    # UI filters use the whole report's counts, not the current page.
    assert (
        client.get("/api/admin/quality/jobs/" + job + "?category=PENDING").json()["report"][
            "filtered_count"
        ]
        == 1
    )
    filtered = client.get("/api/admin/quality/jobs/" + job + "?category=PENDING").json()["report"]
    assert {issue["category"] for issue in filtered["items"][0]["issues"]} == {"PENDING"}
    missing = str(uuid4())
    assert client.get("/api/admin/quality/jobs/" + missing).status_code == 404
    assert (
        client.post(
            "/api/admin/quality/reprocess",
            json={**action, "request_id": str(uuid4()), "audit_job_id": missing},
        ).status_code
        == 404
    )
    client.app.dependency_overrides.pop(require_admin)
    assert client.get("/api/admin/quality/jobs").status_code in {401, 503}


def test_dispatch_recovers_after_child_registration_before_checkpoint(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    doc = reader(records)
    q = Queue(db)
    batch = q._submit(
        "batch",
        "REPROCESS_QUALITY",
        {"action": "FIELDS", "document_ids": [doc], "field_rule": VERSION},
        3,
    )
    worker = Worker(q, records)
    original = q.heartbeat
    failed = False

    def crash(job, checkpoint=None):
        nonlocal failed
        if checkpoint and "results" in checkpoint and not failed:
            failed = True
            raise ValueError("AFTER_CHILD_SUBMIT")
        original(job, checkpoint)

    monkeypatch.setattr(q, "heartbeat", crash)
    assert worker.run_once()
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (batch.job_id,)
        )
    assert worker.run_once()
    assert q.get(batch.job_id).status == "SUCCEEDED"
    with db.connect() as conn:
        assert (
            conn.execute("SELECT count(*) n FROM jobs WHERE kind='BUILD_CASE_FIELDS'").fetchone()[
                "n"
            ]
            == 1
        )


def test_nontransient_and_stale_are_skipped(db, tmp_path):
    records = Records(db, FileStore(tmp_path))
    doc = reader(records)
    q = Queue(db)
    worker = Worker(q, records)
    job = q._submit(
        "batch",
        "REPROCESS_QUALITY",
        {"action": "LAWGO_TRANSIENT", "document_ids": [doc], "field_rule": VERSION},
        3,
    )
    assert worker.run_once()
    assert q.get(job.job_id).checkpoint["results"][doc]["reason"] == "NO_RETRYABLE_FAILURE"
    old = ReaderStore(records).read(doc)
    ReaderStore(records).preserve(
        "<p>新</p>",
        title=old["title"],
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance=old["provenance"],
        acquisitions={},
    )
    second = q._submit(
        "batch2",
        "REPROCESS_QUALITY",
        {"action": "FIELDS", "document_ids": [doc], "field_rule": VERSION},
        3,
    )
    assert worker.run_once()
    assert q.get(second.job_id).checkpoint["results"][doc]["reason"] == "STALE"


def test_audit_resume_preserves_completed_item(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path))
    documents = [reader(records, "123"), reader(records, "456")]
    save(records, "scope", {"document_ids": documents})
    q = Queue(db)
    job = q._submit(
        "audit", "AUDIT_CURRENT_QUALITY", {"scope_artifact_id": "scope", "field_rule": VERSION}, 3
    )
    worker = Worker(q, records)
    original = q.heartbeat

    def stop_after_one(job, checkpoint=None):
        original(job, checkpoint)
        if checkpoint and checkpoint.get("checked") == 1:
            worker.stop.set()

    monkeypatch.setattr(q, "heartbeat", stop_after_one)
    assert worker.run_once()
    original_bytes = records.read(f"quality:{job.job_id}:item:0")
    worker.stop.clear()
    monkeypatch.setattr(q, "heartbeat", original)
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (job.job_id,)
        )
    assert worker.run_once()
    assert q.get(job.job_id).status == "SUCCEEDED"
    assert records.read(f"quality:{job.job_id}:item:0") == original_bytes


def test_transient_lawgo_only_retries_failed_location_without_new_mapping(
    db, tmp_path, monkeypatch
):
    from klegal_gold.enrichment.current_lawgo import CurrentLawgo, provider_links

    records = Records(db, FileStore(tmp_path))
    store = ReaderStore(records)
    html = '<p><a name="linkPrvs">형법 제1조</a><a name="linkPrvs">형법 제2조</a></p>'
    doc = store.preserve(
        html, title="표본", source_id="123", origin="CURRENT_SOURCE", provenance={}, acquisitions={}
    )
    original = store.read(doc)
    frame = (
        '<input id="precYd" value="20241001">'
        "<a onclick=\"javascript:fncLawPop('형법','JO','000100','prec');\">형법 제1조</a>"
        "<a onclick=\"javascript:fncLawPop('형법','JO','000200','prec');\">형법 제2조</a>"
    )
    _, links = provider_links(frame)
    records.put_artifact("frame", frame.encode(), origin="HTTP_RESPONSE", metadata={})
    save(
        records,
        "plan",
        {
            "status": "EXACT",
            "source_id": "1",
            "day": "20241001",
            "links": links,
            "frame_artifact_id": "frame",
        },
    )
    refs = original["statutes"]
    for ref, error in zip(
        refs, ["LAWGO_TRANSPORT_FAILED", "LAWGO_ARTICLE_STRUCTURE_CHANGED"], strict=True
    ):
        ref.update(provider_status="FAILED", provider_error=error)
    failed = store.preserve(
        html,
        title="표본",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={"lawgo_plan_artifact_id": "plan"},
        acquisitions={},
        linked_statutes=refs,
    )
    before = records.read("reader:" + failed)
    calls = []

    def request(self, endpoint, params, key):
        calls.append((endpoint, params["joNo"]))
        raw = (
            '<table summary="조문정보"><tbody id="lsLinkTable">'
            "<tr><td>제1조 보존</td></tr></tbody></table>"
        ).encode()
        records.put_artifact(key, raw, origin="HTTP_RESPONSE", metadata={})
        return raw

    monkeypatch.setattr(CurrentLawgo, "_request", request)
    result = CurrentLawgo(records).run(failed, "retry", lambda: None, transient_only=True)
    assert calls == [("lsLinkProc.do", "000100")]
    assert [x["provider_status"] for x in store.read(result)["statutes"]] == ["PRESERVED", "FAILED"]
    assert records.read("reader:" + failed) == before
    assert store.read(result)["html_sha256"] == original["html_sha256"]


def test_transient_images_keep_other_locations_and_build_final_fields(db, tmp_path, monkeypatch):
    from uuid import UUID

    from klegal_gold.assets.images import DownloadedImage, ImageAcquirer
    from klegal_gold.fields.store import FieldStore

    records = Records(db, FileStore(tmp_path))
    template = ReaderStore(records).read(reader(records))
    store = ReaderStore(records)
    html = (
        '<input class="contImagePath" name="a" value="a.gif">'
        '<input class="contImagePath" name="b" value="b.gif">'
        '<p><img name="a"><img name="b"></p>'
    )
    base = store.preserve(
        html,
        title="표본",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance=template["provenance"],
        acquisitions={},
    )
    urls = [r["resolved_url"] for r in store.read(base)["images"]]
    doc = store.preserve(
        html,
        title="표본",
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance=template["provenance"],
        acquisitions={
            urls[0]: {"status": "FAILED", "error": "IMAGE_NETWORK_ERROR"},
            urls[1]: {"status": "FAILED", "error": "HTTP_404"},
        },
    )
    q = Queue(db)
    job = q._submit(
        "retry", "RETRY_CURRENT_IMAGES", {"document_id": doc, "transient_only": True}, 3
    )
    calls = []
    gif = bytes.fromhex(
        "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
    )

    def fetch(url, limit):
        calls.append(url)
        return DownloadedImage(gif, "image/gif", {})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer", lambda r: ImageAcquirer(r, fetcher=fetch)
    )
    w = Worker(q, records)
    for _ in range(6):
        w.run_once()
    done = q.get(job.job_id)
    refresh = q.get(UUID(done.checkpoint["follow_up_job_id"]))
    final = refresh.checkpoint["reader_document_id"]
    assert calls == [urls[0]]
    assert store.read(final)["images"][0]["status"] == "ACQUIRED"
    assert store.read(final)["images"][1]["status"] != "ACQUIRED"
    assert FieldStore(records).read(final)["revision"]
    assert q.get(UUID(done.checkpoint["fields_job_id"])).status == "SUCCEEDED"
