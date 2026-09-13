"""Build a conservative source-ID baseline from the corrected legacy Parquet."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from klegal_gold.domain.common import content_hash


@dataclass(frozen=True)
class LegacySourceCatalog:
    source: str
    parquet_sha256: str
    source_ids: tuple[str, ...]
    rows_scanned: int
    rejected_values: int
    version: str = "legacy-source-catalog-1"

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source": self.source,
            "parquet_sha256": self.parquet_sha256,
            "rows_scanned": self.rows_scanned,
            "rejected_values": self.rejected_values,
            "source_ids": list(self.source_ids),
        }

    @classmethod
    def from_payload(cls, value: object) -> LegacySourceCatalog:
        if not isinstance(value, dict) or value.get("version") != "legacy-source-catalog-1":
            raise ValueError("INVALID_LEGACY_SOURCE_CATALOG")
        ids = value.get("source_ids")
        if (
            not isinstance(ids, list)
            or any(not isinstance(source_id, str) for source_id in ids)
            or ids != sorted(set(ids))
        ):
            raise ValueError("INVALID_LEGACY_SOURCE_CATALOG")
        required = ("source", "parquet_sha256", "rows_scanned", "rejected_values")
        if any(name not in value for name in required):
            raise ValueError("INVALID_LEGACY_SOURCE_CATALOG")
        return cls(
            source=str(value["source"]),
            parquet_sha256=str(value["parquet_sha256"]),
            source_ids=tuple(ids),
            rows_scanned=int(value["rows_scanned"]),
            rejected_values=int(value["rejected_values"]),
        )

    def encoded(self) -> bytes:
        return json.dumps(
            self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()


def _valid_source_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value != value.strip() or value in {"", "0", "empty"}:
        return None
    return value


def scourt_catalog(path: Path, *, column: str = "gmeta_contId") -> LegacySourceCatalog:
    """Read only the chosen column; reject lossy/coerced legacy values rather than fixing them."""
    parquet = pq.ParquetFile(path)
    if column not in parquet.schema_arrow.names:
        raise ValueError("LEGACY_SOURCE_ID_COLUMN_NOT_FOUND")
    source_ids: set[str] = set()
    rows_scanned = 0
    rejected_values = 0
    for batch in parquet.iter_batches(columns=[column]):
        for value in batch.column(0).to_pylist():
            rows_scanned += 1
            source_id = _valid_source_id(value)
            if source_id is None:
                if value is not None:
                    rejected_values += 1
            else:
                source_ids.add(source_id)
    raw_hash = content_hash(path.read_bytes())
    return LegacySourceCatalog(
        source="scourt",
        parquet_sha256=raw_hash,
        source_ids=tuple(sorted(source_ids)),
        rows_scanned=rows_scanned,
        rejected_values=rejected_values,
    )


def source_ids(catalog: LegacySourceCatalog) -> Iterable[str]:
    """Expose an immutable catalog as the compare_inventory legacy baseline input."""
    return catalog.source_ids
