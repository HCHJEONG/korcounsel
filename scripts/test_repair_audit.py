"""End-to-end offline audit: provenance, image positions and quarantine."""

import hashlib
import json
import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from audit_legacy_repairs import run
from dateutil import parser


class AuditTests(unittest.TestCase):
    def test_archive_unchanged_overlay_and_image_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            title = "제26사단보통군사법원 2002. 10. 24. 선고 2002고26 판결"
            html = title + '<img src="/wsjo/cm/imgDownload.do?contId=1&amp;attachImgNm=a.gif">' * 2
            frame = pd.DataFrame(
                {
                    "case_full_no": [title, title],
                    "case_txt_scraped_with_tags": [html, None],
                    "case_txt_in_file": ["【변론종결】2002. 9. 1【주문】", ""],
                    "gmeta_sngoDay": ["20021024", ""],
                    "lmeta_sngoDay": ["2002-10-24", ""],
                    "gmeta_contId": ["1", "1"],
                    "lmeta_serialno": ["2", "2"],
                    "decision_date": [parser.parser("2002. 10. 24."), None],
                    "closing_argument": ["no_info", "no_info"],
                }
            )
            snapshot = root / "source.pickle"
            snapshot.write_bytes(pickle.dumps(frame, protocol=4))
            digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            run(snapshot, digest, root / "output", root / "report.json")
            report = json.loads((root / "report.json").read_text())
            self.assertEqual(
                report["counts"], {"dates.jsonl": 1, "images.jsonl": 1, "quarantine.jsonl": 1}
            )
            self.assertEqual(report["images"]["occurrences"], 2)
            self.assertEqual(report["unique_resolved_urls"], 1)
            self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), digest)
            row = pq.read_table(root / "output/repair-overlay.parquet").to_pylist()[0]
            self.assertEqual(row["decision_date"].isoformat(), "2002-10-24")
            self.assertTrue(row["decision_apply"])
            self.assertFalse(row["closing_apply"])  # absent from preserved HTML

    def test_hash_mismatch_prevents_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "source.pickle"
            snapshot.write_bytes(b"not pickle")
            with self.assertRaisesRegex(ValueError, "SNAPSHOT_HASH_MISMATCH"):
                run(snapshot, "0" * 64, root / "output", root / "report.json")
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
