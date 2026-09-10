"""Synthetic checks for the analysis-only runtime; no legacy files are required."""

import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from analyze_legacy_corpus import analyze, brief, missing, official_id
from analyze_legacy_identity import citation_date, normalized_date
from dateutil.parser._parser import parser
from inspect_legacy_pickle import load_data


class LegacyAuditTests(unittest.TestCase):
    def test_missing_sentinels_do_not_become_official_ids(self):
        for value in (None, "empty", "", "  ", 0, "0", float("nan")):
            with self.subTest(value=value):
                self.assertIsNotNone(missing(value))
                self.assertIsNone(official_id(value))
        self.assertEqual(official_id("00123"), "00123")
        self.assertEqual(official_id(123), "123")

    def test_parser_object_is_reported_without_runtime_address(self):
        self.assertEqual(brief(parser()), {"type": "parser", "value_not_serialized": True})

    def test_dates_are_diagnostic_not_source_mutations(self):
        self.assertEqual(citation_date("대법원 2011. 1. 20. 선고"), "20110120")
        self.assertIsNone(citation_date("날짜 없음"))
        self.assertEqual(normalized_date("2011.01.20"), "20110120")

    def test_restricted_reader_preserves_data_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.pickle"
            original = pd.DataFrame({"id": ["00123"], "date": [parser()], "text": ["합성"]})
            path.write_bytes(pickle.dumps(original, protocol=4))
            loaded = load_data(path)
            self.assertEqual(loaded.at[0, "id"], "00123")
            self.assertIsInstance(loaded.at[0, "date"], parser)

    def test_unapproved_pickle_global_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-data.pickle"
            path.write_bytes(pickle.dumps(eval))
            with self.assertRaisesRegex(pickle.UnpicklingError, "Unapproved"):
                load_data(path)

    def test_report_cannot_overwrite_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "outside"):
                analyze(root, root / "report.json")


if __name__ == "__main__":
    unittest.main()
