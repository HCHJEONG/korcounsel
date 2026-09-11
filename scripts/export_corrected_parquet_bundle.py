"""Export corrected legacy Parquet rows into the existing immutable bundle format."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from klegal_gold.domain.legacy import LegacyField, LegacyRow, LegacyRowLocator
from klegal_gold.ingestion.legacy_bundle import MAX_ROW_BYTES, BundleEntry, LegacyBundle
from klegal_gold.storage.files import FileStore

FORMAT_VERSION = "legacy-corrected-parquet-bundle-export-1"
PARQUET_FORMAT = "legacy-corrected-full-parquet-1"


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def load_metadata(parquet_file: pq.ParquetFile) -> dict[str, Any]:
    metadata = parquet_file.schema_arrow.metadata or {}
    raw = metadata.get(b"legacy")
    if raw is None:
        raise ValueError("MISSING_LEGACY_PARQUET_METADATA")
    parsed = json.loads(raw.decode())
    if parsed.get("format") != PARQUET_FORMAT or parsed.get("scope") != "FULL":
        raise ValueError("UNSUPPORTED_PARQUET_FORMAT")
    columns = parsed.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError("INVALID_PARQUET_COLUMNS")
    return parsed


def original_type_for_native(mode: str, contract: dict[str, Any]) -> str:
    if mode == "string":
        return "builtins.str"
    types = contract.get("types", {})
    if isinstance(types, dict) and len(types) == 1:
        return next(iter(types))
    return "builtins.int"


def original_index(value: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, dict) and "value" in parsed:
        return "" if parsed["value"] is None else str(parsed["value"])
    return value


def field_from_cell(name: str, value: Any, contract: dict[str, Any]) -> LegacyField:
    mode = contract["mode"]
    if mode in {"string", "int64"}:
        original_type = original_type_for_native(mode, contract)
        encoding = "STRING" if mode == "string" else "INTEGER"
        return LegacyField(
            name=name, original_type=original_type, encoding=encoding, value=value
        )
    if not isinstance(value, dict):
        raise TypeError("INVALID_CELL_VALUE")
    encoding = value["encoding"]
    if encoding == "BIG_INTEGER":
        raise ValueError("BIG_INTEGER_NOT_SUPPORTED_BY_LEGACY_BUNDLE")
    return LegacyField(
        name=name,
        original_type=value["original_type"],
        encoding=encoding,
        value=value["text"] if value["text"] is not None else value["integer"],
    )


def export(
    parquet: Path, expected_sha256: str, data_dir: Path, report: Path
) -> dict[str, Any]:
    parquet_sha = digest(parquet)
    if parquet_sha != expected_sha256:
        raise ValueError("PARQUET_HASH_MISMATCH")
    parquet_file = pq.ParquetFile(parquet)
    metadata = load_metadata(parquet_file)
    columns = tuple(metadata["columns"])
    contracts = metadata["contracts"]
    if parquet_file.metadata.num_rows != metadata["total_rows"]:
        raise ValueError("PARQUET_ROW_COUNT_MISMATCH")
    store = FileStore(data_dir.resolve())
    entries: list[BundleEntry] = []
    selected_columns = [*columns, "__legacy_position", "__legacy_index"]
    for group_index in range(parquet_file.num_row_groups):
        table = parquet_file.read_row_group(group_index, columns=selected_columns)
        for row in table.to_pylist():
            position = row["__legacy_position"]
            fields = tuple(
                field_from_cell(name, row[name], contracts[name]) for name in columns
            )
            legacy_row = LegacyRow(
                locator=LegacyRowLocator(
                    snapshot_sha256=metadata["snapshot_sha256"],
                    position=position,
                    original_index=original_index(row["__legacy_index"]),
                ),
                fields=fields,
                coverage="FULL_ROW",
            )
            raw = legacy_row.model_dump_json().encode()
            if len(raw) > MAX_ROW_BYTES:
                raise ValueError("ROW_SIZE_LIMIT")
            blob = store.put(raw)
            entries.append(
                BundleEntry(
                    position=position, sha256=blob.sha256, size_bytes=blob.size_bytes
                )
            )
        if entries and len(entries) % 5000 < table.num_rows:
            print(f"Exported {len(entries)}/{metadata['total_rows']} rows", flush=True)
    if [entry.position for entry in entries] != list(range(metadata["total_rows"])):
        raise ValueError("INCOMPLETE_OR_UNORDERED_PARQUET_ROWS")
    bundle = LegacyBundle(
        snapshot_sha256=metadata["snapshot_sha256"],
        snapshot_size=metadata["snapshot_size"],
        archive_locator=metadata["archive_locator"],
        total_rows=metadata["total_rows"],
        columns=columns,
        scope="FULL",
        entries=tuple(entries),
    )
    manifest_blob = store.put(bundle.model_dump_json().encode())
    result = {
        "scope": "FULL_CORRECTED_LEGACY_BUNDLE_FROM_PARQUET",
        "format": FORMAT_VERSION,
        "parquet_sha256": parquet_sha,
        "parquet_path": str(parquet.resolve()),
        "snapshot_sha256": metadata["snapshot_sha256"],
        "overlay_sha256": metadata.get("overlay_sha256"),
        "manifest_hash": manifest_blob.sha256,
        "rows": len(entries),
        "columns": len(columns),
        "data_dir": str(data_dir.resolve()),
        "bundle_format": bundle.format,
        "source_parquet_format": metadata["format"],
    }
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    export(args.parquet, args.expected_sha256, args.data_dir, args.report)
