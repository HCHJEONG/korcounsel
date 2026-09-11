"""Direct string search over the corrected legacy Parquet snapshot."""

import json
import re
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


@dataclass(frozen=True)
class ParquetCaseSearchResult:
    court: str | None
    case_numbers: tuple[str, ...]
    decision_date: date | None
    row_position: int
    original_index: str
    matched_columns: tuple[str, ...]
    body_hash: str


def _cell_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "text" in value and value["text"] is not None:
            return value["text"]
        if "integer" in value and value["integer"] is not None:
            return value["integer"]
        if "value" in value:
            return value["value"]
    return value


def _text(value: Any) -> str:
    cell = _cell_value(value)
    if cell is None:
        return ""
    return str(cell)


def _date(value: Any) -> date | None:
    text = _text(value)
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("value") is not None:
            text = str(parsed["value"])
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def _case_numbers(row: dict[str, Any]) -> tuple[str, ...]:
    values = []
    for name in ("case_no", "case_number", "case_full_no"):
        text = _text(row.get(name)).strip()
        if text and text not in values:
            values.append(text)
    return tuple(values)


def _original_index(value: Any) -> str:
    text = _text(value)
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("value") is not None:
            return str(parsed["value"])
    return text if text else ""


def _literal_query(query: str) -> bool:
    """These characters cannot be introduced or changed by Unicode casefold.

    Hangul/digit case identifiers avoid decoding every corpus cell in Python.
    Other alphabets still use Python casefold, including multi-character folds
    such as sharp s; Arrow's ignore_case is not an equivalent contract.
    """
    return all("가" <= char <= "힣" or (char.isascii() and not char.isalpha()) for char in query)


def _string_matches(column: Any, query: str, *, literal: bool) -> Any:
    if literal:
        return pc.fill_null(pc.match_substring_regex(column, re.escape(query)), False)
    return pa.array(
        [value is not None and query in value.casefold() for value in column.to_pylist()]
    )


def _column_matches(column: Any, query: str, *, literal: bool) -> Any:
    """Match all types with the existing _text precedence, without row decoding."""
    if pa.types.is_string(column.type) or pa.types.is_large_string(column.type):
        return _string_matches(column, query, literal=literal)
    if pa.types.is_integer(column.type):
        return _string_matches(pc.cast(column, pa.large_string()), query, literal=literal)
    if pa.types.is_struct(column.type) and "text" in [field.name for field in column.type]:
        text = pc.struct_field(column, "text")
        if pa.types.is_string(text.type) or pa.types.is_large_string(text.type):
            matched = _string_matches(text, query, literal=literal)
            # Most legacy tagged cells carry text. Decode only the exceptions:
            # integer/value precedence and dictionaries without any payload.
            remaining = pc.indices_nonzero(pc.and_(pc.is_valid(column), pc.is_null(text)))
            if len(remaining):
                fallback = [False] * len(column)
                for index in remaining.to_pylist():
                    fallback[index] = query in _text(column[index].as_py()).casefold()
                matched = pc.or_(matched, pa.array(fallback))
            return matched
    return pa.array([query in _text(value).casefold() for value in column.to_pylist()])


def search_legacy_parquet(
    path: Path, query: str, *, limit: int = 30
) -> list[ParquetCaseSearchResult]:
    normalized = query.strip().casefold()
    if not normalized:
        return []
    safe_limit = max(1, min(limit, 100))
    parquet = pq.ParquetFile(path)
    results: list[ParquetCaseSearchResult] = []
    column_names = parquet.schema_arrow.names
    literal = _literal_query(normalized)
    for batch in parquet.iter_batches(batch_size=256):
        candidates = pa.array([False] * len(batch))
        for column in batch.columns:
            candidates = pc.or_(candidates, _column_matches(column, normalized, literal=literal))
        for row in batch.filter(candidates).to_pylist():
            matched = tuple(
                name for name in column_names if normalized in _text(row.get(name)).casefold()
            )
            if not matched:
                continue
            position = row.get("__legacy_position")
            if not isinstance(position, int):
                position = len(results)
            results.append(
                ParquetCaseSearchResult(
                    court=_text(row.get("court_name") or row.get("court")).strip() or None,
                    case_numbers=_case_numbers(row),
                    decision_date=_date(row.get("decision_date")),
                    row_position=position,
                    original_index=_original_index(row.get("__legacy_index")),
                    matched_columns=matched[:8],
                    body_hash=sha256(
                        _text(row.get("case_txt_scraped_with_tags")).encode()
                    ).hexdigest(),
                )
            )
            if len(results) >= safe_limit:
                return results
    return results


def read_legacy_body(path: Path, position: int, expected_hash: str) -> tuple[str, str]:
    """Locate the stored row position and pin the body version selected at search time."""
    parquet = pq.ParquetFile(path)
    if position < 0:
        raise ValueError("INVALID_POSITION")
    columns = ["__legacy_position", "case_txt_scraped_with_tags", "gmeta_contId"]
    columns = [c for c in columns if c in parquet.schema_arrow.names]
    locator_index = parquet.schema.names.index("__legacy_position")
    for group in range(parquet.num_row_groups):
        stats = parquet.metadata.row_group(group).column(locator_index).statistics
        if stats and stats.has_min_max and not stats.min <= position <= stats.max:
            continue
        for row in parquet.read_row_group(group, columns=columns).to_pylist():
            if row["__legacy_position"] == position:
                html = _text(row.get("case_txt_scraped_with_tags"))
                if sha256(html.encode()).hexdigest() != expected_hash:
                    raise ValueError("BODY_VERSION_CHANGED")
                return html, _text(row.get("gmeta_contId"))
    raise ValueError("ROW_NOT_FOUND")


def legacy_snapshot(path: Path) -> str:
    metadata = pq.ParquetFile(path).schema_arrow.metadata or {}
    return str(json.loads(metadata.get(b"legacy", b"{}")).get("snapshot_sha256", ""))
