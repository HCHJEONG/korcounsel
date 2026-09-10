"""Small regression checks for audit classifications; no source mutation or pickle loading."""

import unittest
from pathlib import Path

from audit_legacy_text_coverage import classify, legacy_newlines, source_ids


class CoverageTests(unittest.TestCase):
    def test_text_mode_newlines_preserve_other_whitespace(self):
        original = " a\r\nb\rc\n "
        self.assertEqual(legacy_newlines(original), " a\nb\nc\n ")
        self.assertEqual(original, " a\r\nb\rc\n ")

    def test_scourt_filename(self):
        self.assertEqual(
            source_ids(Path("glaw_updated_panre_txt/123.txt")), ({"scourt": "123"}, None)
        )

    def test_enriched_filename_keeps_namespaces_and_row_hint(self):
        self.assertEqual(
            source_ids(Path("lawgo_jomunupdated_panre_txt/45-123-456.txt")),
            ({"scourt": "123", "law_go_kr": "456"}, 45),
        )

    def test_empty_is_not_source_id(self):
        self.assertEqual(
            source_ids(Path("lawgo_jomunupdated_panre_txt/45-empty-456.txt")),
            ({"law_go_kr": "456"}, 45),
        )

    def test_numeric_unrelated_filename_is_not_assumed_scourt(self):
        self.assertEqual(source_ids(Path("other/123.txt")), ({}, None))

    def test_exact_content_matches_even_if_filename_id_is_unknown(self):
        self.assertEqual(
            classify({3}, {"scourt": "new"}, {"scourt": {}}), ("EXACT_STORED_FIELD_MATCH", [3])
        )

    def test_pair_conflict_is_not_a_confirmed_new_case(self):
        self.assertEqual(
            classify(
                set(),
                {"scourt": "1", "law_go_kr": "2"},
                {"scourt": {"1": [1]}, "law_go_kr": {"2": [2]}},
            ),
            ("SOURCE_ID_PARTIAL_OR_PAIR_CONFLICT", [1, 2]),
        )

    def test_same_pair_with_changed_body_is_not_absent_id(self):
        self.assertEqual(
            classify(
                set(),
                {"scourt": "1", "law_go_kr": "2"},
                {"scourt": {"1": [1, 2]}, "law_go_kr": {"2": [2]}},
            ),
            ("SOURCE_ID_LINK_CONTENT_DIFFERS", [2]),
        )

    def test_unmatched_ids_and_no_id_are_separate(self):
        self.assertEqual(
            classify(set(), {"scourt": "1"}, {"scourt": {}}), ("SOURCE_IDS_NOT_IN_CORPUS", [])
        )
        self.assertEqual(classify(set(), {}, {}), ("NO_USABLE_FILENAME_SOURCE_ID", []))


if __name__ == "__main__":
    unittest.main()
