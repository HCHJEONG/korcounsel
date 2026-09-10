"""Regression cases for date repair decisions, without legacy imports."""

import unittest
from datetime import date

from legacy_repair_rules import candidates, metadata_date, propose_closing, propose_decision


class DateRepairTests(unittest.TestCase):
    def test_military_title_and_no_spaces(self):
        for title in [
            "제26사단보통군사법원 2002. 10. 24. 선고 2002고26 판결",
            "대법원 2020.1.2. 선고 2019다12345 판결",
        ]:
            result = propose_decision(title, title, {})
            self.assertEqual(result["status"], "READY")
        self.assertEqual(result["candidate"], "2020-01-02")

    def test_metadata_conflict_and_invalid(self):
        title = "대법원 2020. 1. 2. 선고 2019다12345 판결"
        self.assertEqual(
            propose_decision(title, title, {"x": "20200103"})["status"], "METADATA_CONFLICT"
        )
        self.assertEqual(
            propose_decision(title, title, {"x": "20201340"})["status"], "INVALID_METADATA"
        )
        self.assertEqual(propose_decision(title, title, {"x": "20200102"})["status"], "READY")

    def test_title_must_be_in_preserved_html(self):
        title = "대법원 2020. 1. 2. 선고 2019다12345 판결"
        self.assertEqual(
            propose_decision(title, "다른 본문", {})["status"], "TITLE_NOT_CONFIRMED_IN_HTML"
        )

    def test_invalid_ambiguous_and_sentinel_dates(self):
        for text, status in [
            ("2020. 13. 40.", "INVALID_TITLE_DATE"),
            ("2020. 1. 2. 및 2020. 1. 3.", "AMBIGUOUS_TITLE"),
            ("2072. 1. 1.", "SENTINEL_DATE"),
            ("", "MISSING_TITLE_DATE"),
        ]:
            self.assertEqual(propose_decision(text, text, {})["status"], status)

    def test_closing_missing_is_not_a_date(self):
        self.assertEqual(propose_closing("【주문】기각", "", "no_info")["status"], "NOT_FOUND")
        self.assertEqual(
            propose_closing("", "", date(2020, 1, 2))["status"], "EXISTING_DATE_NOT_REPRODUCED"
        )

    def test_closing_multiple_keeps_candidates(self):
        text = "【변론종결】2010. 7. 9. 및 2010. 8. 10. 【주문】"
        result = propose_closing(text, text, date(2010, 8, 10))
        self.assertEqual(result["status"], "REVIEW_MULTIPLE")
        self.assertEqual(result["candidate"], "2010-08-10")
        self.assertEqual(len(result["evidence"]), 2)

    def test_closing_agreement_and_conflict(self):
        text = "【변론종결】lnfd 2010. 7. 9. 【주문】"
        self.assertEqual(propose_closing(text, text, date(2010, 7, 9))["status"], "READY")
        self.assertEqual(
            propose_closing(text, text, date(2010, 7, 8))["status"], "EXISTING_DATE_CONFLICT"
        )

    def test_evidence_unicode_offsets(self):
        text = "😀【변론종결】2010. 7. 9. 【주문】"
        result = propose_closing(text, text, "no_info")
        for item in result["evidence"]:
            self.assertEqual(text[item["start"] : item["end"]], item["text"])

    def test_metadata_formats(self):
        for text in ["20200102", "2020-01-02", "2020.01.02", "2020. 1. 2."]:
            self.assertEqual(metadata_date(text)["value"], "2020-01-02")

    def test_closing_trailing_period_optional_and_party_context_retained(self):
        text = "【변론종결】2010. 12. 15lnfd【주문】"
        result = propose_closing(text, text, date(2010, 12, 15))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["candidate"], "2010-12-15")
        text = "【변론종결】2010. 10. 27.(피고 1) 2010. 12. 15(피고 2)【주문】"
        result = propose_closing(text, text, date(2010, 12, 15))
        self.assertEqual(result["status"], "REVIEW_MULTIPLE")
        self.assertIn("피고 2", result["sections"][0]["text"])

    def test_closing_day_heading(self):
        text = "【변론종결일】lnfd2013. 3. 28.lnfd【주문】"
        result = propose_closing(text, text, date(2013, 3, 28))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["candidate"], "2013-03-28")

    def test_invalid_calendar_date_preserved(self):
        result = candidates("2019. 2. 29.")
        self.assertIsNone(result[0]["date"])
        self.assertEqual(result[0]["text"], "2019. 2. 29.")


if __name__ == "__main__":
    unittest.main()
