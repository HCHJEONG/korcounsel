"""Corrected full Parquet exporter keeps all legacy columns and applies only ready repairs."""

import hashlib
import json
import pickle
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from dateutil import parser
from export_corrected_legacy_parquet import FORMAT_VERSION, run

OVERLAY_SCHEMA = pa.schema(
    [
        ("position", pa.int64()),
        ("original_index", pa.string()),
        ("html_sha256", pa.string()),
        ("decision_apply", pa.bool_()),
        ("decision_date", pa.date32()),
        ("decision_status", pa.string()),
        ("closing_apply", pa.bool_()),
        ("closing_argument", pa.date32()),
        ("closing_status", pa.string()),
    ]
)


def write_overlay(path: Path, snapshot_hash: str) -> None:
    rows = [
        {
            "position": 0,
            "original_index": "100",
            "html_sha256": "a" * 64,
            "decision_apply": True,
            "decision_date": date(2002, 10, 24),
            "decision_status": "READY",
            "closing_apply": True,
            "closing_argument": date(2002, 9, 1),
            "closing_status": "READY",
        },
        {
            "position": 1,
            "original_index": "100",
            "html_sha256": "b" * 64,
            "decision_apply": True,
            "decision_date": date(2003, 1, 2),
            "decision_status": "READY",
            "closing_apply": False,
            "closing_argument": None,
            "closing_status": "REVIEW_MULTIPLE",
        },
    ]
    table = pa.Table.from_pylist(rows, schema=OVERLAY_SCHEMA).replace_schema_metadata(
        {b"snapshot_sha256": snapshot_hash.encode(), b"rules_version": b"test"}
    )
    pq.write_table(table, path, compression="zstd", row_group_size=1)


class CorrectedLegacyParquetTests(unittest.TestCase):
    def test_all_columns_and_only_ready_repairs_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame = pd.DataFrame(
                {
                    "case_full_no": ["case a", "case b"],
                    "decision_date": [parser.parser("2002. 10. 24."), None],
                    "closing_argument": ["no_info", date(2003, 1, 1)],
                    "native_text": ["원문", "본문"],
                    "native_int": [1, 2],
                    "mixed": [0, "0"],
                },
                index=pd.Index([100, 100], name="duplicate"),
            )
            snapshot = root / "source.pickle"
            snapshot.write_bytes(pickle.dumps(frame, protocol=4))
            snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            overlay = root / "overlay.parquet"
            write_overlay(overlay, snapshot_hash)

            result = run(
                snapshot,
                snapshot_hash,
                overlay,
                root / "out",
                root / "report.json",
                row_group_size=1,
            )

            self.assertEqual(result["format"], FORMAT_VERSION)
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["columns"], len(frame.columns))
            self.assertEqual(
                result["repairs_applied"], {"decision_date": 2, "closing_argument": 1}
            )
            self.assertTrue(result["python_roundtrip"])
            restored = pq.read_table(root / "out/legacy-corrected-full.parquet")
            self.assertEqual(
                restored.column_names,
                [*frame.columns, "__legacy_position", "__legacy_index"],
            )
            rows = restored.to_pylist()
            self.assertEqual(rows[0]["decision_date"]["encoding"], "JSON")
            self.assertIn("2002-10-24", rows[0]["decision_date"]["text"])
            self.assertIn("2002-09-01", rows[0]["closing_argument"]["text"])
            self.assertIn("2003-01-01", rows[1]["closing_argument"]["text"])
            self.assertEqual(rows[1]["mixed"]["encoding"], "STRING")
            self.assertEqual(rows[0]["__legacy_position"], 0)
            self.assertEqual(len({row["__legacy_index"] for row in rows}), 1)
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["parquet"]["sha256"], result["parquet"]["sha256"])

    def test_incomplete_overlay_is_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame = pd.DataFrame(
                {
                    "decision_date": [None, None],
                    "closing_argument": ["no_info", "no_info"],
                }
            )
            snapshot = root / "source.pickle"
            snapshot.write_bytes(pickle.dumps(frame, protocol=4))
            snapshot_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            table = pa.Table.from_pylist(
                [
                    {
                        "position": 0,
                        "original_index": "0",
                        "html_sha256": "a" * 64,
                        "decision_apply": False,
                        "decision_date": None,
                        "decision_status": "NOT_FOUND",
                        "closing_apply": False,
                        "closing_argument": None,
                        "closing_status": "NOT_FOUND",
                    }
                ],
                schema=OVERLAY_SCHEMA,
            ).replace_schema_metadata({b"snapshot_sha256": snapshot_hash.encode()})
            overlay = root / "overlay.parquet"
            pq.write_table(table, overlay)
            with self.assertRaisesRegex(ValueError, "INCOMPLETE_REPAIR_OVERLAY"):
                run(
                    snapshot,
                    snapshot_hash,
                    overlay,
                    root / "out",
                    root / "report.json",
                    1,
                )
            self.assertFalse((root / "out/legacy-corrected-full.parquet").exists())


if __name__ == "__main__":
    unittest.main()
