"""Synthetic export round-trip; analysis dependencies stay outside runtime."""

import hashlib
import json
import pickle
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from export_legacy_rows import export

from klegal_gold.domain.legacy import LegacyRow
from klegal_gold.ingestion.legacy_bundle import LegacyBundle
from klegal_gold.storage.files import FileStore


class ExportTests(unittest.TestCase):
    def test_existing_dataframe_cells_and_duplicate_index_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = pd.DataFrame(
                {
                    "text": ["原文😀\n", "empty"],
                    "numeric": np.array([0, 2], dtype=np.int64),
                    "nested": [{"x": (1, False)}, None],
                },
                index=[7, 7],
            )
            path = root / "frame.pickle"
            raw = pickle.dumps(frame, protocol=4)
            path.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            result = export(path, root / "data", digest, None)
            store = FileStore(root / "data")
            key = result["manifest_hash"]
            bundle = LegacyBundle.model_validate_json(
                store.path(f"blobs/{key[:2]}/{key}").read_bytes()
            )
            self.assertEqual(bundle.scope, "FULL")
            rows = [
                LegacyRow.model_validate_json(
                    store.path(f"blobs/{entry.sha256[:2]}/{entry.sha256}").read_bytes()
                )
                for entry in bundle.entries
            ]
            self.assertEqual([row.locator.original_index for row in rows], ["7", "7"])
            self.assertEqual([row.locator.position for row in rows], [0, 1])
            self.assertEqual(rows[0].fields[0].value, frame["text"].iloc[0])
            self.assertEqual(rows[0].fields[1].value, 0)
            self.assertEqual(rows[0].fields[1].original_type, "numpy.int64")
            self.assertEqual(json.loads(rows[0].fields[2].value)["type"], "builtins.dict")
            repeat = export(path, root / "data", digest, None)
            self.assertEqual(result["manifest_hash"], repeat["manifest_hash"])
            with self.assertRaisesRegex(ValueError, "ARCHIVE_HASH_MISMATCH"):
                export(path, root / "data", "0" * 64, None)


if __name__ == "__main__":
    unittest.main()
