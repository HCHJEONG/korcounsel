"""Corrected Parquet can be staged as the existing legacy full-row bundle."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from export_corrected_parquet_bundle import export
from klegal_gold.domain.legacy import LegacyRow
from klegal_gold.ingestion.legacy_bundle import LegacyBundle
from klegal_gold.storage.files import FileStore

CELL = pa.struct(
    [
        ("original_type", pa.string()),
        ("encoding", pa.string()),
        ("text", pa.large_string()),
        ("integer", pa.int64()),
    ]
)


def write_parquet(path: Path) -> str:
    metadata = {
        "format": "legacy-corrected-full-parquet-1",
        "scope": "FULL",
        "snapshot_sha256": "a" * 64,
        "snapshot_size": 123,
        "archive_locator": "/archive/source.pickle",
        "overlay_sha256": "b" * 64,
        "total_rows": 2,
        "columns": ["case_full_no", "decision_date", "native_int", "mixed"],
        "contracts": {
            "case_full_no": {"mode": "string", "types": {"builtins.str": 2}},
            "decision_date": {"mode": "cell"},
            "native_int": {"mode": "int64", "types": {"builtins.int": 2}},
            "mixed": {"mode": "cell"},
        },
    }
    rows = [
        {
            "case_full_no": "사건 A",
            "decision_date": {
                "original_type": "datetime.date",
                "encoding": "JSON",
                "text": '{"type":"datetime.date","value":"2020-01-02"}',
                "integer": None,
            },
            "native_int": 1,
            "mixed": {
                "original_type": "builtins.int",
                "encoding": "INTEGER",
                "text": None,
                "integer": 0,
            },
            "__legacy_position": 0,
            "__legacy_index": '{"schema_version":"legacy-field-1","name":"index","original_type":"builtins.int","encoding":"INTEGER","value":7}',
        },
        {
            "case_full_no": "사건 B",
            "decision_date": {
                "original_type": "datetime.date",
                "encoding": "JSON",
                "text": '{"type":"datetime.date","value":"2020-01-03"}',
                "integer": None,
            },
            "native_int": 2,
            "mixed": {
                "original_type": "builtins.str",
                "encoding": "STRING",
                "text": "0",
                "integer": None,
            },
            "__legacy_position": 1,
            "__legacy_index": '{"schema_version":"legacy-field-1","name":"index","original_type":"builtins.int","encoding":"INTEGER","value":8}',
        },
    ]
    schema = pa.schema(
        [
            pa.field("case_full_no", pa.large_string()),
            pa.field("decision_date", CELL),
            pa.field("native_int", pa.int64()),
            pa.field("mixed", CELL),
            pa.field("__legacy_position", pa.int64()),
            pa.field("__legacy_index", pa.large_string()),
        ],
        metadata={
            b"legacy": json.dumps(
                metadata, ensure_ascii=False, separators=(",", ":")
            ).encode()
        },
    )
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=1)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CorrectedParquetBundleExportTests(unittest.TestCase):
    def test_exports_existing_bundle_contract_from_corrected_parquet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parquet = root / "corrected.parquet"
            parquet_hash = write_parquet(parquet)
            report = root / "report.json"
            result = export(parquet, parquet_hash, root / "data", report)
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["columns"], 4)
            store = FileStore(root / "data")
            raw_manifest = store.path(
                f"blobs/{result['manifest_hash'][:2]}/{result['manifest_hash']}"
            ).read_bytes()
            bundle = LegacyBundle.model_validate_json(raw_manifest)
            self.assertEqual(bundle.scope, "FULL")
            self.assertEqual(bundle.exporter_version, "legacy-export-1")
            first = bundle.entries[0]
            raw_row = store.path(
                f"blobs/{first.sha256[:2]}/{first.sha256}"
            ).read_bytes()
            row = LegacyRow.model_validate_json(raw_row)
            self.assertEqual(row.locator.snapshot_sha256, "a" * 64)
            self.assertEqual(row.locator.position, 0)
            self.assertEqual(row.locator.original_index, "7")
            self.assertEqual(
                tuple(field.name for field in row.fields), tuple(bundle.columns)
            )
            by_name = {field.name: field for field in row.fields}
            self.assertEqual(by_name["case_full_no"].value, "사건 A")
            self.assertEqual(by_name["decision_date"].encoding, "JSON")
            self.assertIn("2020-01-02", by_name["decision_date"].value)
            self.assertEqual(by_name["native_int"].original_type, "builtins.int")
            self.assertEqual(by_name["mixed"].encoding, "INTEGER")

    def test_hash_mismatch_rejects_before_writing_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parquet = root / "corrected.parquet"
            write_parquet(parquet)
            with self.assertRaisesRegex(ValueError, "PARQUET_HASH_MISMATCH"):
                export(parquet, "0" * 64, root / "data", root / "report.json")
            self.assertFalse((root / "report.json").exists())


if __name__ == "__main__":
    unittest.main()
