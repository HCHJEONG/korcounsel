"""Direct string search over the corrected legacy Parquet snapshot."""

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

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
    for batch in parquet.iter_batches(batch_size=256):
        for row in batch.to_pylist():
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
