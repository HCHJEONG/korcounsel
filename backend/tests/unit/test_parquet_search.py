import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from klegal_gold.search.parquet import search_legacy_parquet

CELL = pa.struct(
    [
        ("original_type", pa.string()),
        ("encoding", pa.string()),
        ("text", pa.large_string()),
        ("integer", pa.int64()),
    ]
)


def write_parquet(path: Path) -> None:
    schema = pa.schema(
        [
            pa.field("court_name", pa.large_string()),
            pa.field("case_no", pa.large_string()),
            pa.field("decision_date", CELL),
            pa.field("case_txt_scraped_with_tags", pa.large_string()),
            pa.field("__legacy_position", pa.int64()),
            pa.field("__legacy_index", pa.large_string()),
        ],
        metadata={b"legacy": json.dumps({"format": "test"}).encode()},
    )
    rows = [
        {
            "court_name": "대법원",
            "case_no": "2020다123",
            "decision_date": {
                "original_type": "datetime.date",
                "encoding": "JSON",
                "text": '{"type":"datetime.date","value":"2020-01-02"}',
                "integer": None,
            },
            "case_txt_scraped_with_tags": "임대차 고유문구",
            "__legacy_position": 7,
            "__legacy_index": "7",
        },
        {
            "court_name": "서울고등법원",
            "case_no": "2019나456",
            "decision_date": {
                "original_type": "datetime.date",
                "encoding": "JSON",
                "text": '{"type":"datetime.date","value":"2019-03-04"}',
                "integer": None,
            },
            "case_txt_scraped_with_tags": "다른 본문",
            "__legacy_position": 8,
            "__legacy_index": "8",
        },
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)


def test_search_legacy_parquet_matches_any_string_column(tmp_path):
    parquet = tmp_path / "legacy.parquet"
    write_parquet(parquet)

    by_body = search_legacy_parquet(parquet, "고유문구", limit=10)
    assert [item.row_position for item in by_body] == [7]
    assert by_body[0].court == "대법원"
    assert by_body[0].case_numbers == ("2020다123",)
    assert by_body[0].decision_date.isoformat() == "2020-01-02"
    assert "case_txt_scraped_with_tags" in by_body[0].matched_columns

    by_court = search_legacy_parquet(parquet, "서울", limit=10)
    assert [item.row_position for item in by_court] == [8]

    assert search_legacy_parquet(parquet, "없음", limit=10) == []
