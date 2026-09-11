from datetime import date

from fastapi.testclient import TestClient

from klegal_gold.db.records import CaseSearchResult
from klegal_gold.web import app as web_app
from klegal_gold.web.app import create_app


class StubRecords:
    def search_cases(self, query: str, *, limit: int = 50) -> list[CaseSearchResult]:
        assert query == "대법원"
        assert limit == 2
        return [
            CaseSearchResult(
                preservation_id="legacy:1",
                content_revision="a" * 64,
                court="대법원",
                case_numbers=("2020다1",),
                decision_date=date(2020, 1, 2),
                body_state="PRESENT",
                row_position=7,
                original_index="7",
            )
        ]


def test_case_search_endpoint_returns_projection_rows(monkeypatch):
    monkeypatch.setattr(web_app, "_records", lambda: StubRecords())
    with TestClient(create_app()) as client:
        result = client.get("/api/cases/search", params={"q": "대법원", "limit": "2"})
    assert result.status_code == 200
    assert result.json() == {
        "query": "대법원",
        "count": 1,
        "limit": 2,
        "results": [
            {
                "preservation_id": "legacy:1",
                "content_revision": "a" * 64,
                "court": "대법원",
                "case_numbers": ["2020다1"],
                "decision_date": "2020-01-02",
                "body_state": "PRESENT",
                "row_position": 7,
                "original_index": "7",
            }
        ],
    }


def test_case_search_requires_query():
    with TestClient(create_app()) as client:
        result = client.get("/api/cases/search", params={"q": "", "limit": "2"})
    assert result.status_code == 422
