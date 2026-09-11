"""Current-source candidates retain immutable provenance without approving legacy links."""

import importlib.util
import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from klegal_gold.assets.images import references_from_manifest
from klegal_gold.documents.reader import VERSION, image_occurrences
from klegal_gold.storage.files import FileStore


@pytest.fixture
def module(monkeypatch):
    scripts = Path(__file__).resolve().parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "current_image_audit", scripts / "audit_current_provider_images.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def reader_fixture(module):
    html = (
        '<input class="contImagePath" name="img1" value="a.gif">'
        '<p>원문<img name="img1">반복<img name="img1"></p>'
        '<img name="unresolved">'
    )
    raw = html.encode()
    digest = sha256(raw).hexdigest()
    images = json.loads(
        module.encoded(
            image_occurrences(html, source_id="123", base_url="https://portal.scourt.go.kr/")
        )
    )
    manifest = {
        "version": VERSION,
        "title": "원문",
        "source_id": "123",
        "origin": "CURRENT_SOURCE",
        "provenance": {"fixture": True},
        "html_artifact_id": "reader-html:" + digest,
        "html_sha256": digest,
        "images": images,
        "statutes": [],
    }
    return raw, manifest


def saved_reader(module, raw, manifest):
    body = module.encoded(manifest)
    reader = sha256(body).hexdigest()
    values = {"reader:" + reader: body, manifest["html_artifact_id"]: raw}
    return reader, SimpleNamespace(read=lambda artifact: values[artifact]), values


def test_reader_dedup_retains_repeated_locations_and_legacy_failures(module):
    raw, manifest = reader_fixture(module)
    reader, records, values = saved_reader(module, raw, manifest)
    wave = {
        "wave": 1,
        "artifact_id": "receipt",
        "positions": [10, 11],
        "sources": ["123"],
        "source_results": [{"source_id": "123", "positions": [10, 11], "current_reader": reader}],
        "row_results": [{"position": 10, "status": "FAILED"}, {"position": 11, "status": "STAGED"}],
        "current_readers": {"10": reader, "11": reader},
    }
    bindings = module.reader_bindings([wave])
    assert len(bindings) == 1
    parent, refs = module.inspect_reader(records, reader, bindings[reader])
    assert len(parent["legacy_bindings"]) == 2
    assert [r["order"] for r in refs] == [0, 1, 2]
    assert refs[0]["resolved_url"] == refs[1]["resolved_url"]
    assert refs[2]["eligibility_reason"] == "NO_RESOLVED_URL"
    assert not any(r["legacy_link_approved"] for r in refs)
    assert values[manifest["html_artifact_id"]] == raw


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("body", "CURRENT_HTML_HASH_MISMATCH"),
        ("order", "CURRENT_IMAGE_POSITION_OR_MAPPING_MISMATCH"),
        ("tag", "CURRENT_IMAGE_POSITION_OR_MAPPING_MISMATCH"),
        ("mapping", "CURRENT_IMAGE_POSITION_OR_MAPPING_MISMATCH"),
        ("missing", "CURRENT_IMAGE_COUNT_MISMATCH"),
        ("origin", "CURRENT_READER_SOURCE_MISMATCH"),
    ],
)
def test_corrupt_parent_or_image_metadata_rejected(module, mutation, error):
    raw, manifest = reader_fixture(module)
    if mutation == "body":
        raw += b"changed"
    elif mutation == "order":
        manifest["images"][1]["order"] = 0
    elif mutation == "tag":
        manifest["images"][0]["html_tag"] = "<img>"
    elif mutation == "mapping":
        manifest["images"][0]["provider_mapping_values"] = ["wrong.gif"]
    elif mutation == "missing":
        manifest["images"].pop()
    else:
        manifest["origin"] = "LEGACY_CORPUS"
    reader, records, _ = saved_reader(module, raw, manifest)
    with pytest.raises(ValueError, match=error):
        module.inspect_reader(records, reader, [{"source_id": "123"}])


def test_corrupt_reader_hash_is_rejected(module):
    raw, manifest = reader_fixture(module)
    reader, records, values = saved_reader(module, raw, manifest)
    values["reader:" + reader] += b" "
    with pytest.raises(ValueError, match="READER_HASH_MISMATCH"):
        module.inspect_reader(records, reader, [{"source_id": "123"}])


def receipt_fixture(module, tmp_path, *, status="COMPLETED", created="1"):
    directory = tmp_path / "waves" / "wave-001"
    directory.mkdir(parents=True, exist_ok=True)
    value = {
        "version": "legacy-image-waves-1",
        "wave": 1,
        "status": status,
        "positions": [0],
        "inventory_sha256": "a" * 64,
        "targets_sha256": "b" * 64,
    }
    raw = module.encoded(value)
    digest = sha256(raw).hexdigest()
    artifact = "legacy-image-wave:" + digest
    path = directory / ("wave-" + digest + ".json")
    path.write_bytes(module.encoded({"artifact_id": artifact, **value}))
    registered = {
        "artifact_id": artifact,
        "blob_hash": digest,
        "metadata": {"kind": "LEGACY_IMAGE_WAVE_RECEIPT"},
        "created_at": created,
    }
    return path, registered, raw


def test_receipt_selection_uses_registered_latest_and_rejects_incomplete(module, tmp_path):
    _, old, old_raw = receipt_fixture(module, tmp_path)
    _, newer, newer_raw = receipt_fixture(module, tmp_path, status="INCOMPLETE", created="2")
    values = {old["artifact_id"]: old_raw, newer["artifact_id"]: newer_raw}
    records = SimpleNamespace(read=lambda artifact: values[artifact])
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [newer, old]))
    with pytest.raises(ValueError, match="WAVE_NOT_COMPLETED"):
        module.select_receipts(conn, records, tmp_path / "waves", 1, 1)


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("local", "LOCAL_WAVE_RECEIPT_MISMATCH"),
        ("hash", "WAVE_RECEIPT_HASH_MISMATCH"),
        ("missing", "WAVE_RECEIPT_NOT_REGISTERED"),
    ],
)
def test_receipt_requires_local_and_immutable_agreement(module, tmp_path, mutation, error):
    path, row, raw = receipt_fixture(module, tmp_path)
    if mutation == "local":
        path.write_text("{}")
    if mutation == "hash":
        raw += b" "
    registered = [] if mutation == "missing" else [row]
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: registered))
    records = SimpleNamespace(read=lambda artifact: raw)
    with pytest.raises(ValueError, match=error):
        module.select_receipts(conn, records, tmp_path / "waves", 1, 1)


def test_range_completion_and_source_mapping_fail_closed(module, tmp_path):
    for start, end in [(0, 1), (2, 1), (1, 20)]:
        with pytest.raises(ValueError, match="INVALID_WAVE_RANGE"):
            module.select_receipts(None, None, tmp_path, start, end)
    path, row, raw = receipt_fixture(module, tmp_path)
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [row]))
    records = SimpleNamespace(read=lambda artifact: raw)
    assert (
        module.select_receipts(conn, records, tmp_path / "waves", 1, 1)[0]["status"] == "COMPLETED"
    )
    with pytest.raises(ValueError, match="WAVE_RECEIPT_MISSING"):
        module.select_receipts(conn, records, tmp_path / "waves", 2, 2)


def test_url_exact_source_filename_and_query_contract(module):
    _, manifest = reader_fixture(module)
    ref = manifest["images"][0]
    assert module.mapping_validation(ref, "123") == (True, None)
    for url in [
        ref["resolved_url"].replace("123", "999"),
        ref["resolved_url"].replace("a.gif", "b.gif"),
        ref["resolved_url"] + "&extra=1",
        ref["resolved_url"] + "&jisCntntsSrno=123",
        ref["resolved_url"] + "#fragment",
    ]:
        assert module.mapping_validation({**ref, "resolved_url": url}, "123")[0] is False
    assert module.mapping_validation({**ref, "provider_mapping_values": []}, "123")[0] is False


def test_never_attempted_is_distinct_from_failed_skipped_and_orphan_attempt(module):
    ref = {"resolved_url": "https://fixture", "provider_mapping_exact": True}
    assert module.classify(ref, None, 0)["eligible_never_attempted"]
    assert module.classify(ref, None, 1)["acquisition_state"] == "OTHER"
    for state in ("ACQUIRED", "FAILED", "SKIPPED"):
        result = module.classify(ref, {"status": state}, 1)
        assert result["acquisition_state"] == (state if state != "SKIPPED" else "OTHER")
        assert not result["eligible_never_attempted"]
    assert not module.classify({**ref, "provider_mapping_exact": False}, None, 0)[
        "eligible_never_attempted"
    ]


def test_acquired_blobs_verified_once_by_hash_and_failure_is_not_hidden(
    module, tmp_path, monkeypatch
):
    store = FileStore(tmp_path)
    raw = bytes.fromhex(
        "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
    )
    blob = store.put(raw)
    row = {"sha256": blob.sha256, "storage_key": blob.storage_key, "size_bytes": blob.size_bytes}
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [row]))
    acquisition = {"status": "ACQUIRED", "blob_hash": blob.sha256, "size_bytes": blob.size_bytes}
    calls = []
    validate = module.validate_image
    monkeypatch.setattr(module, "validate_image", lambda b: calls.append(b) or validate(b))
    result = module.verify_acquired_blobs(conn, store, {"a": acquisition, "b": acquisition})
    assert len(result) == len(calls) == 1
    assert result[0]["decode_verified"]
    store.path(blob.storage_key).write_bytes(raw[:-1])
    with pytest.raises(ValueError, match="BLOB_INTEGRITY_FAILED"):
        module.verify_acquired_blobs(conn, store, {"a": acquisition})


def test_candidate_manifest_is_worker_readable_without_legacy_approval(module, tmp_path):
    raw, manifest = reader_fixture(module)
    reader, records, _ = saved_reader(module, raw, manifest)
    parent, refs = module.inspect_reader(
        records, reader, [{"source_id": "123", "legacy_row_position": 7}]
    )
    refs = [module.classify(ref, None, 0) for ref in refs]
    audit = {
        "snapshot_at": "fixture",
        "receipts": [],
        "parents": [parent],
        "references": refs,
        "verified_blobs": [],
        "summary": {},
    }
    output = tmp_path / "audit"
    summary = module.write_audit(audit, output, write_manifests=True)
    assert len(summary["candidate_manifests"]) == 1
    candidate = (output / "never-attempted-001.json").read_bytes()
    parsed = references_from_manifest(candidate)
    assert len(parsed) == 2
    assert len({r.reference_id for r in parsed}) == 2
    assert len({r.resolved_url for r in parsed}) == 1
    assert all(r.row_position is None and r.reference_status == "RESOLVED" for r in parsed)
    assert all(r.context["scope"] == "CURRENT_SOURCE_ONLY" for r in parsed)
    assert all(r.context["current_html_sha256"] == manifest["html_sha256"] for r in parsed)
    assert all(r.context["legacy_link_approved"] is False for r in parsed)
    assert len((output / "references.jsonl").read_text().splitlines()) == 3
    before = (output / "summary.json").read_bytes()
    with pytest.raises(FileExistsError):
        module.write_audit(audit, output)
    assert (output / "summary.json").read_bytes() == before


def test_legacy_reader_v1_uses_same_verified_image_contract(module):
    raw, manifest = reader_fixture(module)
    manifest["version"] = "image-reader-1"
    manifest.pop("statutes")
    reader, records, _ = saved_reader(module, raw, manifest)
    parent, refs = module.inspect_reader(records, reader, [{"source_id": "123"}])
    assert parent["reader_version"] == "image-reader-1"
    assert len(refs) == 3


def test_candidate_reference_ledger_identity_is_manifest_specific(module):
    raw, manifest = reader_fixture(module)
    reader, records, _ = saved_reader(module, raw, manifest)
    _, refs = module.inspect_reader(records, reader, [{"source_id": "123"}])
    ref = module.manifest_reference(module.classify(refs[0], None, 0))
    first = references_from_manifest(module.encoded({"snapshot_at": "one", "references": [ref]}))[0]
    second = references_from_manifest(module.encoded({"snapshot_at": "two", "references": [ref]}))[
        0
    ]
    assert first.reference_id != second.reference_id
    assert first.context["original_reference_id"] == second.context["original_reference_id"]
    assert first.context["current_reader_id"] == second.context["current_reader_id"]


def test_hash_valid_nonimage_blob_still_fails_decode(module, tmp_path):
    store = FileStore(tmp_path)
    blob = store.put(b"not an image")
    row = {"sha256": blob.sha256, "storage_key": blob.storage_key, "size_bytes": blob.size_bytes}
    conn = SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchall=lambda: [row]))
    acquisition = {"status": "ACQUIRED", "blob_hash": blob.sha256, "size_bytes": blob.size_bytes}
    with pytest.raises(ValueError, match="IMAGE_DECODE_FAILED"):
        module.verify_acquired_blobs(conn, store, {"url": acquisition})


def test_snapshot_is_read_only_before_any_query(module, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from datetime import UTC, datetime

    queries = []

    class Connection:
        def execute(self, sql, params=None):
            queries.append(sql)
            if sql.startswith("SELECT transaction_timestamp"):
                return SimpleNamespace(fetchone=lambda: {"observed_at": datetime.now(UTC)})
            return SimpleNamespace(fetchall=lambda: [])

    connection = Connection()

    class DB:
        @contextmanager
        def connect(self):
            yield connection

    def select(conn, records, *args):
        assert conn is connection
        with records.db.connect() as borrowed:
            assert borrowed is connection
        return []

    monkeypatch.setattr(module, "select_receipts", select)
    result = module.collect_audit(DB(), tmp_path, tmp_path, 1, 1)
    assert queries[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
    assert all(q.startswith("SELECT ") for q in queries[1:])
    assert result["summary"]["current_readers"] == 0
