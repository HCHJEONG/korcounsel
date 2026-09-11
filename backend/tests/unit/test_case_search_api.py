import json

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from klegal_gold.web.app import create_app


def write_parquet(path):
    schema = pa.schema(
        [
            pa.field("court_name", pa.large_string()),
            pa.field("case_no", pa.large_string()),
            pa.field("decision_date", pa.large_string()),
            pa.field("case_txt_scraped_with_tags", pa.large_string()),
            pa.field("__legacy_position", pa.int64()),
            pa.field("__legacy_index", pa.large_string()),
        ],
        metadata={b"legacy": json.dumps({"format": "test"}).encode()},
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "court_name": "대법원",
                    "case_no": "2020다123",
                    "decision_date": "2020-01-02",
                    "case_txt_scraped_with_tags": "본문 고유문구",
                    "__legacy_position": 7,
                    "__legacy_index": "7",
                }
            ],
            schema=schema,
        ),
        path,
    )


def test_case_search_endpoint_reads_configured_parquet(monkeypatch, tmp_path):
    parquet = tmp_path / "legacy.parquet"
    write_parquet(parquet)
    monkeypatch.setenv("LEGACY_PARQUET_PATH", str(parquet))
    with TestClient(create_app()) as client:
        result = client.get("/api/cases/search", params={"q": "고유문구", "limit": "2"})
    assert result.status_code == 200
    assert result.json()["source"] == "LEGACY_PARQUET"
    assert result.json()["results"][0]["row_position"] == 7
    assert result.json()["results"][0]["matched_columns"] == ["case_txt_scraped_with_tags"]


def test_case_search_requires_query():
    with TestClient(create_app()) as client:
        result = client.get("/api/cases/search", params={"q": "", "limit": "2"})
    assert result.status_code == 422
