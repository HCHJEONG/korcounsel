"""Exercise real staging/reader code against a file-backed in-memory artifact registry."""

from contextlib import contextmanager
from hashlib import sha256
from html import escape

from klegal_gold.documents.legacy_batch import LegacyReaderBatch
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.storage.files import FileStore

GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
LAW_URL = "https://www.law.go.kr/flDownload.do?flSeq=6238586"
SC_URL = (
    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on"
    "?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=a.gif"
)
TITLE = "대법원 사건 판결"
BEFORE, AFTER = "앞문맥내용" * 40, "뒷문맥내용" * 40


class Query:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class MemoryRecords:
    def __init__(self, root):
        self.store = FileStore(root)
        self.db = self
        self.artifacts = {}
        self.acquired = {}

    @contextmanager
    def connect(self):
        yield self

    def execute(self, sql, values):
        if "SELECT artifact_id FROM artifacts" in sql:
            body_hash, position, snapshot = values
            found = [
                {"artifact_id": key}
                for key, entry in reversed(list(self.artifacts.items()))
                if entry["metadata"].get("legacy_body_hash") == body_hash
                and str(entry["metadata"].get("legacy_position")) == str(position)
                and entry["metadata"].get("legacy_snapshot") == snapshot
            ]
            return Query(found[:1])
        if "FROM image_acquisitions" in sql:
            return Query([self.acquired[url] for url in values[0] if url in self.acquired])
        if "FROM image_acquisition_attempts" in sql:
            return Query([])
        raise AssertionError(sql)

    def put_artifact(self, artifact_id, raw, *, origin, metadata):
        self.put_artifacts(
            [
                {
                    "artifact_id": artifact_id,
                    "raw": raw,
                    "origin": origin,
                    "metadata": metadata,
                }
            ]
        )

    def put_artifacts(self, entries):
        for entry in entries:
            artifact = entry["artifact_id"]
            if artifact in self.artifacts:
                assert self.artifacts[artifact]["raw"] == entry["raw"]
                assert self.artifacts[artifact]["metadata"] == entry["metadata"]
            else:
                self.store.put(entry["raw"])
                self.artifacts[artifact] = entry

    def read(self, artifact_id):
        return self.artifacts[artifact_id]["raw"]


def make_row():
    payload = '<table><tr><td><img src="/flDownload.do?flSeq=6238586" alt="수식"></td></tr></table>'
    article = '<a jtable="' + escape(payload, quote=True) + '">법 제1조</a>'
    body = (
        BEFORE
        + '<img name="img1" src="https://glaw.scourt.go.kr/img?contId=123&attachImgNm=a.gif">'
        + AFTER
        + article
        + article
    )
    return {
        "__legacy_position": 0,
        "__legacy_index": "0",
        "case_full_no": TITLE,
        "case_txt_scraped_with_tags": body,
        "gmeta_contId": "123",
        "lmeta_serialno": "456",
    }


def test_statute_staging_preserves_body_and_repeats_then_body_keeps_statutes(tmp_path):
    records = MemoryRecords(tmp_path)
    reader = ReaderStore(records)
    digest = sha256(GIF).hexdigest()
    records.put_artifact(
        "reader-image:" + digest,
        GIF,
        origin="DERIVED",
        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
    )
    current = reader.preserve(
        '<input class="contImagePath" name="img1" value="a.gif">'
        + BEFORE
        + '<img name="img1">'
        + AFTER,
        title=TITLE,
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={SC_URL: {"status": "ACQUIRED", "sha256": digest}},
    )
    batch = LegacyReaderBatch(records)
    row = make_row()
    old, _ = batch.stage_row(row, "a" * 64, current)
    old_manifest = reader.read(old["document_id"])
    assert old["linked"] == 1 and "statute_images" not in old_manifest
    first, pending = batch.stage_row(row, "a" * 64, None, include_statute_images=True)
    assert first["linked"] == 1 and first["statute_images_linked"] == 0
    assert [r["article_order"] for r in pending] == [0, 1]
    assert all(r["source_system"] == "law_go_kr" for r in pending)
    assert all(r["resolved_url"] == LAW_URL for r in pending)
    assert all(r["row_position"] == 0 for r in pending)
    records.acquired[LAW_URL] = {
        "url": LAW_URL,
        "status": "ACQUIRED",
        "blob_hash": digest,
        "last_error_code": None,
    }
    updated, pending = batch.stage_row(row, "a" * 64, None, include_statute_images=True)
    assert updated["linked"] == 1 and updated["statute_images_linked"] == 2
    assert not pending
    assert updated["document_id"] != first["document_id"]
    rendered = reader.html(updated["document_id"])
    assert f"/api/reader/{updated['document_id']}/statutes/0/images/0" in rendered
    assert f"/api/reader/{updated['document_id']}/statutes/1/images/0" in rendered
    assert "flDownload.do" not in rendered
    again, _ = batch.stage_row(row, "a" * 64, current)
    assert again["linked"] == 1 and again["statute_images_linked"] == 2
    assert reader.read(again["document_id"])["version"] == "enriched-reader-3"
    assert reader.read(old["document_id"]) == old_manifest
    repeat, _ = batch.stage_row(row, "a" * 64, None, include_statute_images=True)
    assert repeat["document_id"] == again["document_id"]


def test_unsafe_statute_urls_remain_observed_but_not_fetchable(tmp_path):
    records = MemoryRecords(tmp_path)
    row = make_row()
    row["case_txt_scraped_with_tags"] = row["case_txt_scraped_with_tags"].replace(
        "/flDownload.do?flSeq=6238586", "http://www.law.go.kr/flDownload.do?flSeq=6238586"
    )
    batch = LegacyReaderBatch(records)
    result, pending = batch.stage_row(row, "a" * 64, None, include_statute_images=True)
    assert result["statute_images"] == 2 and result["statute_images_linked"] == 0
    assert len(pending) == 2
    assert all(r["reference_status"] == "UNRESOLVED" for r in pending)
    assert all(r["original_src"].startswith("http:") for r in pending)
