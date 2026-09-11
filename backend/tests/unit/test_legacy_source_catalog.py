from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from klegal_gold.ingestion.legacy_catalog import scourt_catalog


def test_scourt_catalog_preserves_only_verbatim_usable_source_ids(tmp_path: Path) -> None:
    path = tmp_path / "legacy.parquet"
    table = pa.table({"gmeta_contId": ["101", "101", " 102", "0", "empty", None, "103"]})
    pq.write_table(table, path)

    catalog = scourt_catalog(path)

    assert catalog.source == "scourt"
    assert catalog.rows_scanned == 7
    assert catalog.rejected_values == 3
    assert catalog.source_ids == ("101", "103")
    assert len(catalog.parquet_sha256) == 64
