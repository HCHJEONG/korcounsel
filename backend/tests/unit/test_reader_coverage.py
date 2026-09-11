import json
import sys
from hashlib import sha256
from html import escape
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from klegal_gold.documents.reader_store import ReaderStore
from klegal_gold.enrichment.corpus_inventory import run_inventory
from klegal_gold.storage.files import FileStore

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from verify_legacy_reader_coverage import load_inventory, verify_coverage  # noqa: E402


class FixtureRecords:
    def __init__(self, directory):
        self.store = FileStore(directory)
        self.registry = {}

    def read(self, artifact_id):
        entry = self.registry[artifact_id]
        return self.store.path(entry["storage_key"]).read_bytes()

    def put_artifacts(self, entries):
        for entry in entries:
            blob = self.store.put(entry["raw"])
            if entry["artifact_id"] not in self.registry:
                self.registry[entry["artifact_id"]] = {
                    "artifact_id": entry["artifact_id"],
                    "blob_hash": blob.sha256,
                    "storage_key": blob.storage_key,
                    "size_bytes": blob.size_bytes,
                    "parent_id": entry.get("parent_id"),
                    "metadata": entry["metadata"],
                    "created_at": f"2026-09-11T00:00:{len(self.registry):06d}",
                }


def fixture(tmp_path, statute_html=None):
    table = statute_html or "<table><tr><td>보존한 법률 내용</td></tr></table>"
    html = (
        '😀\r\n<p>본문<img src="/image.gif"></p><a jtable="'
        + escape(table, quote=True)
        + '">제1조</a>'
    )
    rows = [
        {
            "__legacy_position": n,
            "__legacy_index": str(n),
            "case_txt_scraped_with_tags": body,
            "case_full_no": "법원 사건 판결",
            "gmeta_contId": "123",
            "lmeta_serialno": "456",
        }
        for n, body in enumerate((html, "<p>둘째 본문</p>"))
    ]
    source = tmp_path / "legacy.parquet"
    arrow = pa.Table.from_pylist(rows).replace_schema_metadata(
        {
            b"legacy": json.dumps({"snapshot_sha256": "a" * 64}).encode(),
        }
    )
    pq.write_table(arrow, source)
    inventory = tmp_path / "inventory"
    run_inventory(source, inventory)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    records = FixtureRecords(data_dir)
    original_import = [
        {
            "row_position": n,
            "status": "PRESERVED",
            "snapshot_hash": "a" * 64,
            "input_artifact": f"input:{n}",
            "record_artifact": f"record:{n}",
        }
        for n in range(2)
    ]
    return rows, inventory, records, original_import


def preserve(records, row, note="initial", statute_refs=None):
    return ReaderStore(records).preserve(
        row["case_txt_scraped_with_tags"],
        title=row["case_full_no"],
        source_id=row["gmeta_contId"],
        origin="LEGACY_CORPUS",
        acquisitions={},
        statute_images=statute_refs,
        provenance={
            "snapshot_sha256": "a" * 64,
            "row_position": row["__legacy_position"],
            "original_index": row["__legacy_index"],
            "field": "case_txt_scraped_with_tags",
            "note": note,
        },
    )


def test_coverage_sidecar_latest_history_missing_and_acquisition_separation(tmp_path):
    rows, inventory, records, imported = fixture(tmp_path)
    preserve(records, rows[0])
    latest = preserve(records, rows[0], "second")
    output = tmp_path / "partial-coverage"
    result = verify_coverage(inventory, output, records.store.root, records.registry, imported)
    assert result["totals"]["rows_staged_verified"] == 1
    assert result["totals"]["rows_missing"] == 1
    assert result["totals"]["historical_revisions"] == 1
    assert result["totals"]["acquired_images"] == 0
    assert result["totals"]["unacquired_images"] == 1
    assert not result["complete_reader_registration"]
    sidecar = pq.read_table(output / "reader-coverage.parquet").to_pylist()
    assert sidecar[0]["reader_revision"] == latest
    assert sidecar[1]["reader_revision"] is None
    assert result["source_parquet_unchanged"] and result["import_unchanged"]
    preserve(records, rows[1])
    full = verify_coverage(
        inventory,
        tmp_path / "full-coverage",
        records.store.root,
        records.registry,
        imported,
        verify_blobs=True,
    )
    assert full["complete_reader_registration"]
    assert not full["all_observed_images_acquired"]
    assert full["totals"]["preserved_statutes"] == 1
    assert full["unique_blobs_hashed"] > 2


def test_coverage_rejects_tampered_inventory_and_changed_import(tmp_path):
    rows, inventory, records, imported = fixture(tmp_path)
    for row in rows:
        preserve(records, row)
    changed_import = [{**record, "status": "QUARANTINED"} for record in imported]
    result = verify_coverage(
        inventory,
        tmp_path / "changed-import",
        records.store.root,
        records.registry,
        imported,
        import_after=lambda: changed_import,
    )
    assert not result["import_unchanged"]
    assert not result["complete_reader_registration"]
    with (inventory / "rows.jsonl").open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="INVENTORY_ROWS_HASH"):
        load_inventory(inventory)


def test_coverage_verifies_blob_bytes_when_requested_and_keeps_row_errors(tmp_path):
    rows, inventory, records, imported = fixture(tmp_path)
    for row in rows:
        preserve(records, row)
    payload = next(
        r for r in records.registry.values() if r["metadata"]["kind"] == "LEGACY_LAWGO_PAYLOAD"
    )
    path = records.store.path(payload["storage_key"])
    original = path.read_bytes()
    path.write_bytes(b"x" * len(original))
    result = verify_coverage(
        inventory,
        tmp_path / "corrupt",
        records.store.root,
        records.registry,
        imported,
        verify_blobs=True,
    )
    assert not result["complete_reader_registration"]
    assert result["totals"]["rows_error"] == 1
    assert result["totals"]["rows_staged_verified"] == 1
    assert result["error_codes"] == {"REFERENCED_FILE_HASH_MISMATCH": 1}


def test_coverage_detects_manifest_counts_and_tracks_other_body_revisions(tmp_path):
    rows, inventory, records, imported = fixture(tmp_path)
    first = preserve(records, rows[0])
    second = preserve(records, rows[1])
    entry = records.registry["reader:" + first]
    content = json.loads(records.store.path(entry["storage_key"]).read_bytes())
    content["statutes"] = []
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True).encode()
    revision = sha256(raw).hexdigest()
    records.put_artifacts(
        [
            {
                "artifact_id": "reader:" + revision,
                "raw": raw,
                "parent_id": entry["parent_id"],
                "metadata": entry["metadata"],
            }
        ]
    )
    records.registry["reader:" + second]["metadata"]["legacy_body_hash"] = "b" * 64
    result = verify_coverage(
        inventory,
        tmp_path / "bad-counts",
        records.store.root,
        records.registry,
        imported,
    )
    assert result["error_codes"] == {"OCCURRENCE_COUNT_MISMATCH": 1}
    sidecar = pq.read_table(tmp_path / "bad-counts" / "reader-coverage.parquet").to_pylist()
    assert sidecar[1]["status"] == "MISSING"
    assert sidecar[1]["other_body_revision_count"] == 1


GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)


def statute_fixture(tmp_path):
    from audit_legacy_statute_images import inspect_batch

    payload = '<table><tr><td><img src="/flDownload.do?flSeq=1" alt="수식"></td></tr></table>'
    rows, inventory, records, imported = fixture(tmp_path, statute_html=payload)
    summary = json.loads((inventory / "summary.json").read_text())
    observed = inspect_batch(rows)
    result = {
        "version": "legacy-statute-image-audit-1",
        "input": {
            "parquet_sha256": summary["input"]["parquet_sha256"],
            "parquet_after_sha256": summary["input"]["parquet_sha256"],
            "snapshot_sha256": "a" * 64,
            "unchanged": True,
        },
        "totals": {
            "rows": 2,
            "unique_visual_payloads": len(observed["payloads"]),
            "unique_payload_img_tags": sum(len(x["images"]) for x in observed["payloads"].values()),
            "payload_parent_locations": len(observed["locations"]),
            "img_parent_occurrences": sum(
                len(observed["payloads"][x["payload_sha256"]]["images"])
                for x in observed["locations"]
            ),
        },
        "payloads": list(observed["payloads"].values()),
        "parent_locations": observed["locations"],
    }
    audit = tmp_path / "statute-images.json"
    audit.write_text(json.dumps(result, ensure_ascii=False))
    return rows, inventory, records, imported, audit


def statute_revision(records, row, *, acquired=False):
    from klegal_gold.documents.reader import statute_image_occurrences

    refs = statute_image_occurrences(row["case_txt_scraped_with_tags"])
    for ref in refs:
        ref["status"] = "PENDING"
        if acquired:
            digest = sha256(GIF).hexdigest()
            records.put_artifacts(
                [
                    {
                        "artifact_id": "reader-image:" + digest,
                        "raw": GIF,
                        "metadata": {"kind": "PRESERVED_IMAGE_BYTES"},
                    }
                ]
            )
            ref.update(
                blob_hash=digest,
                status="ACQUIRED",
                acquisition={
                    "status": "ACQUIRED",
                    "sha256": digest,
                    "url": ref["resolved_url"],
                },
            )
    return preserve(records, row, statute_refs=refs)


def rewrite_manifest(records, revision, mutate):
    entry = records.registry["reader:" + revision]
    value = json.loads(records.store.path(entry["storage_key"]).read_bytes())
    mutate(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    new_revision = sha256(raw).hexdigest()
    records.put_artifacts(
        [
            {
                "artifact_id": "reader:" + new_revision,
                "raw": raw,
                "parent_id": entry["parent_id"],
                "metadata": dict(entry["metadata"]),
            }
        ]
    )
    return new_revision


def test_v2_registration_keeps_missing_statute_images_separate(tmp_path):
    rows, inventory, records, imported, audit = statute_fixture(tmp_path)
    for row in rows:
        preserve(records, row)
    output = tmp_path / "v2-coverage"
    report = verify_coverage(
        inventory,
        output,
        records.store.root,
        records.registry,
        imported,
        statute_image_audit=audit,
    )
    assert report["complete_reader_registration"]
    assert not report["complete_statute_image_reference_coverage"]
    assert not report["all_observed_images_acquired"]
    assert report["totals"]["statute_image_occurrences"] == 1
    assert report["totals"]["missing_statute_image_references"] == 1
    assert report["totals"]["unacquired_statute_images"] == 1
    sidecar = pq.read_table(output / "reader-coverage.parquet").to_pylist()
    assert sidecar[0]["status"] == "STAGED_VERIFIED"
    assert sidecar[0]["statute_image_coverage_status"] == "MISSING_REFERENCES"
    assert sidecar[1]["statute_image_coverage_status"] == "NO_IMAGES"


def test_v3_statute_images_audit_blob_decode_and_counts(tmp_path):
    rows, inventory, records, imported, audit = statute_fixture(tmp_path)
    statute_revision(records, rows[0], acquired=True)
    preserve(records, rows[1])
    result = verify_coverage(
        inventory,
        tmp_path / "v3-coverage",
        records.store.root,
        records.registry,
        imported,
        statute_image_audit=audit,
        verify_blobs=True,
    )
    assert result["complete_reader_registration"]
    assert result["complete_statute_image_reference_coverage"]
    assert result["totals"]["acquired_statute_images"] == 1
    assert result["totals"]["unacquired_statute_images"] == 0
    assert result["totals"]["missing_statute_image_references"] == 0
    assert result["unique_images_decoded"] == 1
    assert result["statute_image_audit"]["rows_with_images"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("article_order", 77),
        ("payload_sha256", "f" * 64),
        ("html_start", 0),
    ],
)
def test_v3_statute_image_cross_article_payload_or_position_is_rejected(tmp_path, field, value):
    rows, inventory, records, imported, audit = statute_fixture(tmp_path)
    revision = statute_revision(records, rows[0])
    preserve(records, rows[1])
    rewrite_manifest(records, revision, lambda m: m["statute_images"][0].update({field: value}))
    report = verify_coverage(
        inventory,
        tmp_path / "bad-position",
        records.store.root,
        records.registry,
        imported,
        statute_image_audit=audit,
    )
    assert report["totals"]["rows_error"] == 1
    assert report["error_codes"] == {"STATUTE_IMAGE_POSITION_MISMATCH": 1}


def test_v3_statute_image_corrupt_bytes_and_acquisition_hash_are_rejected(tmp_path):
    rows, inventory, records, imported, audit = statute_fixture(tmp_path)
    revision = statute_revision(records, rows[0], acquired=True)
    preserve(records, rows[1])
    digest = sha256(GIF).hexdigest()
    path = records.store.path(f"blobs/{digest[:2]}/{digest}")
    path.write_bytes(b"x" * len(GIF))
    report = verify_coverage(
        inventory,
        tmp_path / "bad-image",
        records.store.root,
        records.registry,
        imported,
        statute_image_audit=audit,
        verify_blobs=True,
    )
    assert report["error_codes"] == {"REFERENCED_FILE_HASH_MISMATCH": 1}
    path.write_bytes(GIF)
    rewrite_manifest(
        records,
        revision,
        lambda m: m["statute_images"][0]["acquisition"].update(sha256="f" * 64),
    )
    report = verify_coverage(
        inventory,
        tmp_path / "bad-acquisition",
        records.store.root,
        records.registry,
        imported,
        statute_image_audit=audit,
    )
    assert report["error_codes"] == {"INVALID_STATUTE_IMAGE_ACQUISITION": 1}


def test_audit_source_mismatch_and_omitted_image_parent_are_rejected(tmp_path):
    rows, inventory, records, imported, audit = statute_fixture(tmp_path)
    for row in rows:
        preserve(records, row)
    value = json.loads(audit.read_text())
    wrong = value | {"input": value["input"] | {"parquet_sha256": "f" * 64}}
    audit.write_text(json.dumps(wrong))
    with pytest.raises(ValueError, match="STATUTE_IMAGE_AUDIT_INPUT_MISMATCH"):
        verify_coverage(
            inventory,
            tmp_path / "bad-source",
            records.store.root,
            records.registry,
            imported,
            statute_image_audit=audit,
        )
    value["parent_locations"] = []
    value["totals"].update(payload_parent_locations=0, img_parent_occurrences=0)
    audit.write_text(json.dumps(value))
    report = verify_coverage(
        inventory,
        tmp_path / "missing-parent",
        records.store.root,
        records.registry,
        imported,
        statute_image_audit=audit,
    )
    assert report["error_codes"] == {"STATUTE_IMAGE_AUDIT_MANIFEST_MISMATCH": 1}
