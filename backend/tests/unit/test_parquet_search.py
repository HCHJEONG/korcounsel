import json
from hashlib import sha256
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


def _reference_rows(path, query, limit=30):
    """Original full Python scan as an independent compatibility oracle."""
    normalized = query.strip().casefold()
    if not normalized:
        return []

    def text(value):
        if isinstance(value, dict):
            if value.get("text") is not None:
                value = value["text"]
            elif value.get("integer") is not None:
                value = value["integer"]
            elif "value" in value:
                value = value["value"]
        return "" if value is None else str(value)

    results = []
    for row in pq.read_table(path).to_pylist():
        matched = tuple(name for name, value in row.items() if normalized in text(value).casefold())
        if matched:
            results.append(
                (
                    row.get("__legacy_position", len(results)),
                    matched[:8],
                    sha256(text(row.get("case_txt_scraped_with_tags")).encode()).hexdigest(),
                )
            )
            if len(results) >= max(1, min(limit, 100)):
                break
    return results


def test_search_preserves_unicode_cell_precedence_and_every_column(tmp_path):
    path = tmp_path / "heterogeneous.parquet"
    schema = pa.schema(
        [
            ("case_txt_scraped_with_tags", pa.large_string()),
            ("tagged", CELL),
            ("value_only", pa.struct([("value", pa.int64())])),
            ("list_column", pa.list_(pa.string())),
            ("null_column", pa.null()),
            ("number", pa.int64()),
            ("boolean", pa.bool_()),
            ("__legacy_position", pa.int64()),
        ]
    )
    rows = [
        {
            "case_txt_scraped_with_tags": "Straße Σςσ İ ﬃ KELVIN K 소송 2006후4086",
            "tagged": {"text": "precedence", "integer": 998},
            "value_only": {"value": 77},
            "list_column": ["목록", "2010다33"],
            "number": -123,
            "boolean": True,
            "__legacy_position": 17,
        },
        {
            "case_txt_scraped_with_tags": "본문",
            "tagged": {"text": None, "integer": 998},
            "value_only": {"value": None},
            "__legacy_position": 8,
        },
        {
            "tagged": {"original_type": "복합원문", "text": None, "integer": None},
            "__legacy_position": 3,
        },
        {"__legacy_position": 4},
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=2)
    queries = [
        "STRASSE",
        "σ",
        "SS",
        "i̇",
        "FFI",
        "kelvin",
        "소송",
        "2006후4086",
        "precedence",
        "998",
        "77",
        "2010다33",
        "목록",
        "-123",
        "true",
        "복합원문",
        "None",
        "없는말",
        "  ",
        "  본문  ",
    ]
    for query in queries:
        actual = search_legacy_parquet(path, query)
        assert [
            (r.row_position, r.matched_columns, r.body_hash) for r in actual
        ] == _reference_rows(path, query), query


def test_search_preserves_column_order_limits_and_missing_locator(tmp_path):
    path = tmp_path / "many.parquet"
    rows = [{f"column_{index}": "반복" for index in range(12)} for _ in range(270)]
    pq.write_table(pa.Table.from_pylist(rows), path, row_group_size=17)
    for limit in [-1, 0, 1, 30, 1000]:
        results = search_legacy_parquet(path, "반복", limit=limit)
        assert [
            (r.row_position, r.matched_columns, r.body_hash) for r in results
        ] == _reference_rows(path, "반복", limit)
        assert all(r.matched_columns == tuple(f"column_{i}" for i in range(8)) for r in results)


def test_search_fast_path_treats_regex_symbols_as_literal_text(tmp_path):
    path = tmp_path / "literal.parquet"
    rows = [
        {"case_txt_scraped_with_tags": text, "__legacy_position": index}
        for index, text in enumerate(
            ["가.나", "가*나", "가[나]", "가\\나", "가(나)", "가 나", "가?나"]
        )
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)
    for query in [".", "*", "[", "\\", "(", "가 나", "?"]:
        results = search_legacy_parquet(path, query)
        assert [
            (r.row_position, r.matched_columns, r.body_hash) for r in results
        ] == _reference_rows(path, query)
