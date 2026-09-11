"""Actual PostgreSQL batch publication, fencing and preservation of previous links."""

import json
from hashlib import sha256
from html import escape

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.db.records import Records
from klegal_gold.documents.legacy_batch import VERSION, validate_input
from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.jobs.queue import Queue
from klegal_gold.jobs.worker import Worker
from klegal_gold.storage.files import FileStore

pytestmark = pytest.mark.integration
SNAPSHOT = "a" * 64
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
BEFORE, AFTER = "가나다라마바사" * 20, "아자차카타파하" * 20
TITLE = "대법원 2020다1 판결"
LEGACY = (
    BEFORE
    + '<img name="img1" src="https://glaw.scourt.go.kr/img?contId=123&attachImgNm=a.gif">'
    + AFTER
)
CURRENT = BEFORE + '<img name="img1">' + AFTER
MAPPING = '<input class="contImagePath" name="img1" value="a.gif">'
URL = (
    "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on"
    "?pgmId=PGP1011M04&jisCntntsSrno=123&atchImgFileNm=a.gif"
)


def fixture(records, path, bodies=None):
    if bodies is None:
        article = escape("<table><tr><td>보존 조문</td></tr></table>", quote=True)
        bodies = [
            LEGACY + f'<a name="linkContJomun" jtable="{article}">제1조</a>',
            "<p>본문 😀</p>",
            "",
        ]
    table = pa.Table.from_pylist(
        [
            {
                "__legacy_position": n,
                "__legacy_index": str(n),
                "case_txt_scraped_with_tags": body,
                "case_full_no": TITLE,
                "gmeta_contId": "123",
                "lmeta_serialno": "456",
            }
            for n, body in enumerate(bodies)
        ]
    ).replace_schema_metadata({b"legacy": json.dumps({"snapshot_sha256": SNAPSHOT}).encode()})
    pq.write_table(table, path, row_group_size=2)
    return {
        "version": VERSION,
        "positions": list(range(len(bodies))),
        "current_readers": {},
        "parquet_sha256": sha256(path.read_bytes()).hexdigest(),
        "snapshot_sha256": SNAPSHOT,
    }


def submit(records, queue, payload, key):
    raw = json.dumps(payload, sort_keys=True).encode()
    artifact = "legacy-reader-batch:" + sha256(raw).hexdigest()
    records.put_artifact(
        artifact, raw, origin="MANIFEST", metadata={"kind": "LEGACY_READER_BATCH_INPUT"}
    )
    return queue.submit_legacy_reader_batch(key, artifact)


def result(records, queue, job):
    current = queue.get(job.job_id)
    assert current.status == "SUCCEEDED"
    return json.loads(records.read(current.checkpoint["result_manifest"]))


def setup(db, tmp_path, monkeypatch):
    path = tmp_path / "input.parquet"
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(path))
    records = Records(db, FileStore(tmp_path / "store"))
    queue = Queue(db)
    return path, records, queue, Worker(queue, records)


def test_worker_reconciles_failures_and_reuses_revisions(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path)
    first = submit(records, queue, payload, "first")
    assert submit(records, queue, payload, "first").job_id == first.job_id
    assert worker.run_once()
    report = result(records, queue, first)
    assert (report["staged"], report["failed"]) == (2, 1)
    assert report["rows"][0]["preserved_statutes"] == 1
    assert report["rows"][2]["error_code"] == "LEGACY_BODY_EMPTY"
    second = submit(records, queue, payload, "second")
    assert worker.run_once()
    assert result(records, queue, second)["rows"] == report["rows"]
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM legacy_reader_batch_rows").fetchone()["n"] == 6
        assert (
            conn.execute(
                "SELECT count(*) n FROM artifacts WHERE metadata->>'kind'='READER_DOCUMENT'"
            ).fetchone()["n"]
            == 2
        )
        assert conn.execute("SELECT count(*) n FROM documents").fetchone()["n"] == 0


def test_file_and_snapshot_hashes_checked_before_any_row(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path)
    batch = worker.legacy_readers
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        batch.verify_input(path, payload | {"parquet_sha256": "f" * 64}, lambda _: None)
    with pytest.raises(ValueError, match="SNAPSHOT_MISMATCH"):
        batch.verify_input(path, payload | {"snapshot_sha256": "f" * 64}, lambda _: None)
    batch.verify_input(path, payload, lambda _: None)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        batch.verify_input(path, payload, lambda _: None)
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) n FROM legacy_reader_batch_rows").fetchone()["n"] == 0


def test_checkpoint_after_publication_resumes_and_drain_blocks_claim(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path, ["<p>첫째</p>", "<p>둘째</p>", "<p>셋째</p>"])
    job = submit(records, queue, payload, "checkpoint")
    stage_row = worker.legacy_readers.stage_row
    calls = 0

    def stop_after_publish(*args, **kwargs):
        nonlocal calls
        saved = stage_row(*args, **kwargs)
        calls += 1
        if calls == 1:
            worker.stop.set()
        return saved

    monkeypatch.setattr(worker.legacy_readers, "stage_row", stop_after_publish)
    worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    queue.set_draining(True)
    worker.stop.clear()
    assert not worker.run_once()
    queue.set_draining(False)
    worker.run_once()
    assert result(records, queue, job)["staged"] == 3
    assert queue.get(job.job_id).attempts == 2


def test_stale_worker_cannot_commit_row_ledger(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path, ["<p>첫째</p>"])
    queued = submit(records, queue, payload, "stale")
    job = queue.claim("stale-worker")
    stage_row = worker.legacy_readers.stage_row

    def expire(*args, **kwargs):
        output = stage_row(*args, **kwargs)
        with db.connect() as conn:
            conn.execute("UPDATE jobs SET lease_until=clock_timestamp()-interval '1 second'")
        return output

    monkeypatch.setattr(worker.legacy_readers, "stage_row", expire)
    with pytest.raises(ValueError, match="LEASE_LOST"):
        worker.legacy_readers.run(job, path, lambda _: None)
    with db.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM legacy_reader_batch_rows WHERE job_id=%s", (queued.job_id,)
            ).fetchone()["n"]
            == 0
        )


def test_absent_or_changed_mapping_never_erases_acquired_occurrence(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path, [LEGACY])
    digest = sha256(GIF).hexdigest()
    records.put_artifact(
        "reader-image:" + digest,
        GIF,
        origin="DERIVED",
        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
    )
    store = ReaderStore(records)
    current = store.preserve(
        MAPPING + CURRENT,
        title=TITLE,
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={URL: {"status": "ACQUIRED", "sha256": digest}},
    )
    first = submit(records, queue, payload | {"current_readers": {"0": current}}, "images")
    worker.run_once()
    first_row = result(records, queue, first)["rows"][0]
    assert first_row["linked"] == 1
    second = submit(records, queue, payload, "no-mapping")
    worker.run_once()
    assert result(records, queue, second)["rows"][0] == first_row
    changed = store.preserve(
        MAPPING + CURRENT.replace(AFTER, "다른 본문" * 50),
        title=TITLE,
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    third = submit(records, queue, payload | {"current_readers": {"0": changed}}, "changed")
    worker.run_once()
    last_row = result(records, queue, third)["rows"][0]
    assert last_row["linked"] == 1
    assert store.image(last_row["document_id"], 0)[0] == GIF


def test_input_bounds_and_unknown_rows_are_explicit(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path)
    for invalid in ([], list(range(101)), [0, 0], [True], [-1]):
        with pytest.raises(ValueError, match="INVALID"):
            validate_input(payload | {"positions": invalid})
    job = submit(records, queue, payload | {"positions": [99]}, "missing")
    worker.run_once()
    report = result(records, queue, job)
    assert report["failed"] == 1
    assert report["rows"][0]["error_code"] == "LEGACY_ROW_MISSING"


def test_download_refs_keep_occurrence_and_new_manifest_namespace(db, tmp_path, monkeypatch):
    from klegal_gold.assets.images import references_from_manifest

    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload = fixture(records, path, [LEGACY, LEGACY])
    current = ReaderStore(records).preserve(
        MAPPING + CURRENT,
        title=TITLE,
        source_id="123",
        origin="CURRENT_SOURCE",
        provenance={},
        acquisitions={},
    )
    first = submit(
        records, queue, payload | {"positions": [0], "current_readers": {"0": current}}, "single"
    )
    worker.run_once()
    first_report = result(records, queue, first)
    second = submit(
        records, queue, payload | {"current_readers": {"0": current, "1": current}}, "joint"
    )
    worker.run_once()
    second_report = result(records, queue, second)
    a = references_from_manifest(records.read(first_report["download_manifest"]))
    b = references_from_manifest(records.read(second_report["download_manifest"]))
    assert len(a) == 1 and len(b) == 2
    assert a[0].occurrence_order == b[0].occurrence_order == b[1].occurrence_order == 0
    assert a[0].row_position == b[0].row_position == 0 and b[1].row_position == 1
    assert a[0].context["legacy_reader_reference_id"] == b[0].context["legacy_reader_reference_id"]
    assert a[0].reference_id != b[0].reference_id


def test_bulk_artifacts_conflict_is_atomic_and_existing_bytes_checked(db, tmp_path):
    records = Records(db, FileStore(tmp_path / "store"))
    entry = {"artifact_id": "test:one", "raw": b"one", "origin": "DERIVED", "metadata": {}}
    records.put_artifacts([entry])
    records.put_artifacts([entry])
    with pytest.raises(ValueError, match="IMMUTABLE_ARTIFACT_CONFLICT"):
        records.put_artifacts(
            [
                {"artifact_id": "test:two", "raw": b"two", "origin": "DERIVED", "metadata": {}},
                entry | {"raw": b"changed"},
            ]
        )
    with pytest.raises(ValueError, match="ARTIFACT_NOT_FOUND"):
        records.read("test:two")
    digest = sha256(b"one").hexdigest()
    records.store.path(f"blobs/{digest[:2]}/{digest}").write_bytes(b"bad")
    with pytest.raises(ValueError, match="BLOB_INTEGRITY_FAILED"):
        records.put_artifacts([entry])


def test_connection_reuse_keeps_transaction_thread_and_nested_boundaries(db):
    from concurrent.futures import ThreadPoolExecutor

    def pid():
        with db.connect() as conn:
            return conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]

    with db.connect() as conn:
        conn.execute("CREATE TABLE reuse_probe(value int)")
    with db.reuse_connections():
        first = pid()
        with db.reuse_connections():
            assert pid() == first
        with db.connect() as conn:
            conn.execute("INSERT INTO reuse_probe VALUES(1)")
        with pytest.raises(ValueError, match="rollback"):
            with db.connect() as conn:
                conn.execute("INSERT INTO reuse_probe VALUES(2)")
                raise ValueError("rollback")
        with db.connect() as conn:
            assert conn.execute("SELECT sum(value) AS n FROM reuse_probe").fetchone()["n"] == 1
            assert pid() != first
        assert pid() == first
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(pid).result() != first
    assert pid() != first


def preserve_v3_fixture(records, html):
    from klegal_gold.documents.reader import statute_image_occurrences

    digest = sha256(GIF).hexdigest()
    records.put_artifact(
        "reader-image:" + digest,
        GIF,
        origin="DERIVED",
        metadata={"kind": "PRESERVED_IMAGE_BYTES"},
    )
    refs = statute_image_occurrences(html)
    for ref in refs:
        ref.update(
            blob_hash=digest,
            status="ACQUIRED",
            acquisition={
                "status": "ACQUIRED",
                "sha256": digest,
                "url": ref["resolved_url"],
            },
        )
    return ReaderStore(records).preserve(
        html,
        title=TITLE,
        source_id="123",
        origin="LEGACY_CORPUS",
        provenance={
            "snapshot_sha256": SNAPSHOT,
            "row_position": 0,
            "original_index": "0",
            "field": "case_txt_scraped_with_tags",
            "lawgo_serialno": "456",
            "historical_binary_identity_verified": False,
        },
        acquisitions={},
        statute_images=refs,
    )


def test_checkpointed_v3_reader_rechecks_statute_bytes_before_resuming(db, tmp_path, monkeypatch):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload_html = '<table><tr><td><img src="/flDownload.do?flSeq=1"></td></tr></table>'
    html = '<a jtable="' + escape(payload_html, quote=True) + '">제1조</a>'
    payload = fixture(records, path, [html, "<p>두번째</p>"])
    revision = preserve_v3_fixture(records, html)
    assert worker.legacy_readers.verify_reader(revision)["version"] == "enriched-reader-3"
    stage_row = worker.legacy_readers.stage_row

    def stop_after_first(row, *args, **kwargs):
        result = stage_row(row, *args, **kwargs)
        if row["__legacy_position"] == 0:
            worker.stop.set()
        return result

    monkeypatch.setattr(worker.legacy_readers, "stage_row", stop_after_first)
    job = submit(records, queue, payload, "v3-checkpoint")
    worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    digest = sha256(GIF).hexdigest()
    file = records.store.path(f"blobs/{digest[:2]}/{digest}")
    file.write_bytes(b"x" * len(GIF))
    worker.stop.clear()
    worker.run_once()
    assert queue.get(job.job_id).status == "QUEUED"
    with db.connect() as conn:
        row = conn.execute(
            "SELECT count(*) AS n FROM legacy_reader_batch_rows WHERE job_id=%s", (job.job_id,)
        ).fetchone()
        assert row["n"] == 1
        failure = conn.execute(
            "SELECT failures FROM jobs WHERE job_id=%s", (job.job_id,)
        ).fetchone()
        assert failure["failures"] == 1
        conn.execute(
            "UPDATE jobs SET available_at=clock_timestamp() WHERE job_id=%s", (job.job_id,)
        )
    file.write_bytes(GIF)
    worker.run_once()
    assert result(records, queue, job)["staged"] == 2


@pytest.mark.parametrize(
    "change,code",
    [
        ("acquisition", "INVALID_STATUTE_IMAGE_ACQUISITION"),
        ("article", "STATUTE_IMAGE_POSITION_MISMATCH"),
        ("version", "INVALID_STATUTE_IMAGE_MANIFEST"),
    ],
)
def test_v3_reuse_rejects_invalid_statute_acquisition_position_or_version(
    db,
    tmp_path,
    monkeypatch,
    change,
    code,
):
    path, records, queue, worker = setup(db, tmp_path, monkeypatch)
    payload_html = '<table><tr><td><img src="/flDownload.do?flSeq=1"></td></tr></table>'
    html = '<a jtable="' + escape(payload_html, quote=True) + '">제1조</a>'
    revision = preserve_v3_fixture(records, html)
    stored = ReaderStore(records).read(revision)
    if change == "acquisition":
        stored["statute_images"][0]["acquisition"]["url"] = (
            "https://www.law.go.kr/flDownload.do?flSeq=2"
        )
    elif change == "article":
        stored["statute_images"][0]["article_order"] = 8
    else:
        stored["version"] = "enriched-reader-2"
    raw = json.dumps(stored, ensure_ascii=False, sort_keys=True).encode()
    altered = sha256(raw).hexdigest()
    records.put_artifact(
        "reader:" + altered,
        raw,
        origin="MANIFEST",
        parent_id=stored["html_artifact_id"],
        metadata={},
    )
    with pytest.raises(ValueError, match=code):
        worker.legacy_readers.verify_reader(altered)
