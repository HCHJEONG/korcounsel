"""Lawgo image jobs preserve repeats, v2 history and both directions of enrichment."""

import json
from hashlib import sha256
from html import escape

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.assets.images import DownloadedImage, ImageAcquirer, references_from_manifest
from klegal_gold.db.records import Records
from klegal_gold.documents.legacy_batch import VERSION, validate_input
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
LAW_URL = "https://www.law.go.kr/flDownload.do?flSeq=6238586"
SCOURT_URL = (
    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on"
    "?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=a.gif"
)
TITLE = "대법원 2020다1 판결"
BEFORE, AFTER = "앞문맥내용" * 40, "뒷문맥내용" * 40


def submit(records, queue, payload, key):
    raw = json.dumps(payload, sort_keys=True).encode()
    artifact = "legacy-reader-batch:" + sha256(raw).hexdigest()
    records.put_artifact(
        artifact,
        raw,
        origin="MANIFEST",
        metadata={"kind": "LEGACY_READER_BATCH_INPUT"},
    )
    return queue.submit_legacy_reader_batch(key, artifact)


def report(records, queue, job):
    job = queue.get(job.job_id)
    assert job.status == "SUCCEEDED", job
    return json.loads(records.read(job.checkpoint["result_manifest"]))


def test_lawgo_images_acquire_once_and_survive_body_revision(db, tmp_path, monkeypatch):
    records = Records(db, FileStore(tmp_path / "store"))
    queue = Queue(db)
    reader = ReaderStore(records)
    file_hash = sha256(GIF).hexdigest()
    records.put_artifact(
        "reader-image:" + file_hash,
        GIF,
        origin="DERIVED",
        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
    )
    current_html = (
        '<input class="contImagePath" name="img1" value="a.gif">'
        + BEFORE
        + '<img name="img1">'
        + AFTER
    )
    current = reader.preserve(
        current_html,
        title=TITLE,
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={SCOURT_URL: {"status": "ACQUIRED", "sha256": file_hash}},
    )
    payload_html = (
        '<table><tr><td><img src="/flDownload.do?flSeq=6238586" alt="공식 수식"></td></tr></table>'
    )
    article = '<a jtable="' + escape(payload_html, quote=True) + '">제1조</a>'
    html = (
        BEFORE
        + '<img name="img1" src="https://glaw.scourt.go.kr/img?contId=123&attachImgNm=a.gif">'
        + AFTER
        + article
        + article
    )
    path = tmp_path / "input.parquet"
    table = pa.Table.from_pylist(
        [
            {
                "__legacy_position": 0,
                "__legacy_index": "0",
                "case_txt_scraped_with_tags": html,
                "case_full_no": TITLE,
                "gmeta_contId": "123",
                "lmeta_serialno": "456",
            }
        ]
    ).replace_schema_metadata({b"legacy": json.dumps({"snapshot_sha256": "a" * 64}).encode()})
    pq.write_table(table, path)
    original = path.read_bytes()
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(path))
    worker = Worker(queue, records)
    base = {
        "version": VERSION,
        "positions": [0],
        "current_readers": {},
        "snapshot_sha256": "a" * 64,
        "parquet_sha256": sha256(original).hexdigest(),
    }
    old_job = submit(records, queue, base | {"current_readers": {"0": current}}, "body-first")
    worker.run_once()
    old = report(records, queue, old_job)["rows"][0]
    assert old["linked"] == 1
    assert "statute_images" not in reader.read(old["document_id"])

    initial_job = submit(records, queue, base | {"include_statute_images": True}, "statute-pending")
    worker.run_once()
    initial = report(records, queue, initial_job)
    first = initial["rows"][0]
    assert first["linked"] == 1 and first["statute_images"] == 2
    assert first["statute_images_linked"] == 0
    refs = references_from_manifest(records.read(initial["download_manifest"]))
    assert len(refs) == 2 and len({r.reference_id for r in refs}) == 2
    assert {r.source_system for r in refs} == {"law_go_kr"}
    assert {r.source_id for r in refs} == {"456"}
    assert {r.resolved_url for r in refs} == {LAW_URL}
    assert [r.context["article_order"] for r in refs] == [0, 1]
    assert all(r.context["parent_body_sha256"] == sha256(html.encode()).hexdigest() for r in refs)
    fetched = []

    def fetch(url, limit):
        fetched.append(url)
        return DownloadedImage(GIF, "image/gif", {})

    monkeypatch.setattr(
        "klegal_gold.jobs.worker.ImageAcquirer",
        lambda records: ImageAcquirer(records, fetcher=fetch),
    )
    download = queue.submit_image_batch("lawgo-download", initial["download_manifest"])
    worker.run_once()
    assert queue.get(download.job_id).status == "SUCCEEDED"
    assert fetched == [LAW_URL]

    updated_job = submit(
        records,
        queue,
        base | {"include_statute_images": True, "acquisition_revision": "b" * 64},
        "statute-acquired",
    )
    worker.run_once()
    updated = report(records, queue, updated_job)["rows"][0]
    assert updated["linked"] == 1 and updated["statute_images_linked"] == 2
    assert updated["document_id"] != first["document_id"]
    manifest = reader.read(updated["document_id"])
    assert manifest["version"] == "enriched-reader-3"
    assert all(r["blob_hash"] == file_hash for r in manifest["statute_images"])
    assert all(r["acquisition"]["status"] == "ACQUIRED" for r in manifest["statute_images"])
    rendered = reader.html(updated["document_id"])
    assert f"/api/reader/{updated['document_id']}/statutes/0/images/0" in rendered
    assert f"/api/reader/{updated['document_id']}/statutes/1/images/0" in rendered
    assert "/flDownload.do" not in rendered
    assert reader.read(old["document_id"])["version"] == "enriched-reader-2"

    body_job = submit(
        records, queue, base | {"current_readers": {"0": current}}, "body-after-statute"
    )
    worker.run_once()
    last = report(records, queue, body_job)["rows"][0]
    assert last["linked"] == 1 and last["statute_images_linked"] == 2
    assert reader.read(last["document_id"])["version"] == "enriched-reader-3"
    assert path.read_bytes() == original


def test_statute_image_opt_in_requires_boolean():
    base = {
        "version": VERSION,
        "positions": [0],
        "snapshot_sha256": "a" * 64,
        "parquet_sha256": "b" * 64,
    }
    validate_input(base | {"include_statute_images": True})
    for value in (1, "true", None, []):
        with pytest.raises(ValueError, match="INVALID"):
            validate_input(base | {"include_statute_images": value})
