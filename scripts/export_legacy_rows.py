"""Analysis-only export of existing DataFrame cells; no text-based reconstruction or DB writes."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from inspect_legacy_pickle import load_data

from klegal_gold.domain.legacy import LegacyRow, LegacyRowLocator
from klegal_gold.ingestion.legacy_bundle import (
    MAX_ROW_BYTES,
    BundleEntry,
    LegacyBundle,
    preserve_field,
)
from klegal_gold.storage.files import FileStore


def export(snapshot: Path, data_dir: Path, expected_hash: str, positions: list[int] | None):
    before = snapshot.stat()
    with snapshot.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected_hash:
        raise ValueError("ARCHIVE_HASH_MISMATCH")
    print("Archive hash verified; loading existing DataFrame", flush=True)
    frame = load_data(snapshot)
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique:
        raise ValueError("INVALID_LEGACY_FRAME")
    columns = tuple(frame.columns)
    if any(type(name) is not str for name in columns):
        raise ValueError("UNSUPPORTED_COLUMN_NAME")
    selected = sorted(set(positions)) if positions is not None else list(range(len(frame)))
    if not selected or selected[0] < 0 or selected[-1] >= len(frame):
        raise ValueError("INVALID_EXPORT_POSITIONS")
    store = FileStore(data_dir.resolve())
    entries = []
    for position in selected:
        index = frame.index[position]
        if not isinstance(index, (str, int, np.integer)):
            raise ValueError("UNSUPPORTED_ROW_INDEX")
        fields = []
        # Column-wise access avoids iterrows/Series dtype coercion of cell values.
        for column in columns:
            value = frame[column].iloc[position]
            original_type = type(value).__module__ + "." + type(value).__qualname__
            if isinstance(value, (np.integer, np.floating, np.bool_, np.str_)):
                value = value.item()
            fields.append(preserve_field(column, value, original_type=original_type))
        row = LegacyRow(
            locator=LegacyRowLocator(
                snapshot_sha256=digest, position=position, original_index=str(index)
            ),
            fields=tuple(fields),
            coverage="FULL_ROW",
        )
        raw = row.model_dump_json().encode()
        if len(raw) > MAX_ROW_BYTES:
            raise ValueError("ROW_SIZE_LIMIT")
        blob = store.put(raw)
        entries.append(
            BundleEntry(position=position, sha256=blob.sha256, size_bytes=blob.size_bytes)
        )
        if len(entries) % 1000 == 0:
            print(f"Exported {len(entries)} rows", flush=True)
    after = snapshot.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise ValueError("ARCHIVE_CHANGED_DURING_EXPORT")
    bundle = LegacyBundle(
        snapshot_sha256=digest,
        snapshot_size=before.st_size,
        archive_locator=str(snapshot.resolve()),
        total_rows=len(frame),
        columns=columns,
        scope="FULL" if positions is None else "SAMPLE",
        entries=tuple(entries),
    )
    manifest = store.put(bundle.model_dump_json().encode())
    result = {
        "manifest_hash": manifest.sha256,
        "rows": len(entries),
        "columns": len(columns),
        "scope": bundle.scope,
        "snapshot_sha256": digest,
    }
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--positions", help="Explicit comma-separated original row positions")
    selection.add_argument("--all", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = export(
        args.snapshot,
        args.data_dir,
        args.expected_sha256,
        [int(v) for v in args.positions.split(",")] if args.positions else None,
    )
    # Report is an operator pointer; immutable manifest and rows live in the CAS.
    args.report.write_text(json.dumps(result, indent=2) + "\n")
