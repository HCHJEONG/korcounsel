"""Analysis-only full legacy DataFrame Parquet export with verified repairs applied."""

import argparse
import hashlib
import json
import resource
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from inspect_legacy_pickle import load_data
from klegal_gold.ingestion.legacy_bundle import preserve_field

FORMAT_VERSION = "legacy-corrected-full-parquet-1"
REPAIR_FIELDS = frozenset({"decision_date", "closing_argument"})

CELL = pa.struct(
    [
        ("original_type", pa.string()),
        ("encoding", pa.string()),
        ("text", pa.large_string()),
        ("integer", pa.int64()),
    ]
)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def label(value: Any) -> str:
    return type(value).__module__ + "." + type(value).__qualname__


def preserved(name: str, value: Any) -> dict[str, Any]:
    original_type = label(value)
    if isinstance(value, (np.integer, np.floating, np.bool_, np.str_)):
        value = value.item()
    result = preserve_field(name, value, original_type=original_type).model_dump(
        mode="json"
    )
    if result["encoding"] == "INTEGER" and not -(2**63) <= value < 2**63:
        result["encoding"] = "BIG_INTEGER"
        result["value"] = str(value)
    return result


def _is_int64(value: Any) -> bool:
    return isinstance(value, (int, np.integer)) and not isinstance(
        value, (bool, np.bool_)
    )


def profile(frame: pd.DataFrame) -> dict[str, Any]:
    result = {}
    for name in frame.columns:
        values = frame[name]
        types: Counter[str] = Counter()
        int64 = True
        for position in range(len(values)):
            value = values.iloc[position]
            types[label(value)] += 1
            if _is_int64(value):
                int64 &= -(2**63) <= int(value) < 2**63
        native = "string" if set(types) == {"builtins.str"} else "cell"
        if (
            len(types) == 1
            and next(iter(types)) in {"builtins.int", "numpy.int64"}
            and int64
        ):
            native = "int64"
        if name in REPAIR_FIELDS:
            native = "cell"
        result[name] = {
            "dtype": str(values.dtype),
            "types": dict(types),
            "representation": native,
        }
        print(f"Profiled {name}: {dict(types)}", flush=True)
    return result


def load_overlay(
    path: Path, expected_snapshot: str, total_rows: int
) -> dict[int, dict[str, Any]]:
    overlay_table = pq.read_table(path)
    metadata = overlay_table.schema.metadata or {}
    snapshot = metadata.get(b"snapshot_sha256", b"").decode()
    if snapshot and snapshot != expected_snapshot:
        raise ValueError("OVERLAY_SNAPSHOT_MISMATCH")
    rows = overlay_table.to_pylist()
    overlay: dict[int, dict[str, Any]] = {}
    for row in rows:
        position = row["position"]
        if type(position) is not int or not 0 <= position < total_rows:
            raise ValueError("INVALID_OVERLAY_POSITION")
        if position in overlay:
            raise ValueError("DUPLICATE_OVERLAY_POSITION")
        overlay[position] = row
    if len(overlay) != total_rows:
        raise ValueError("INCOMPLETE_REPAIR_OVERLAY")
    return overlay


def repaired_value(name: str, value: Any, overlay_row: dict[str, Any]) -> Any:
    if name == "decision_date" and overlay_row["decision_apply"]:
        candidate = overlay_row["decision_date"]
        return (
            candidate if isinstance(candidate, date) else date.fromisoformat(candidate)
        )
    if name == "closing_argument" and overlay_row["closing_apply"]:
        candidate = overlay_row["closing_argument"]
        return (
            candidate if isinstance(candidate, date) else date.fromisoformat(candidate)
        )
    return value


def make_batch(
    frame: pd.DataFrame,
    profiles: dict[str, Any],
    overlay: dict[int, dict[str, Any]],
    positions: range,
) -> tuple[pa.RecordBatch, dict[str, Any]]:
    arrays = {}
    expected_by_column = {name: [] for name in frame.columns}
    repair_counts = {"decision_date": 0, "closing_argument": 0}
    opaque_cells = 0
    fingerprint = hashlib.sha256()
    for name in frame.columns:
        cells = []
        for position in positions:
            original = frame[name].iloc[position]
            value = repaired_value(name, original, overlay[position])
            if name in REPAIR_FIELDS and value != original:
                repair_counts[name] += 1
            cell = preserved(name, value)
            cells.append(cell)
            expected_by_column[name].append(cell)
            opaque_cells += cell["encoding"] == "OPAQUE"
            encoded = dumps(cell).encode()
            fingerprint.update(len(encoded).to_bytes(8, "big"))
            fingerprint.update(encoded)
        mode = profiles[name]["representation"]
        if mode in {"string", "int64"}:
            arrays[name] = pa.array(
                [cell["value"] for cell in cells],
                type=pa.large_string() if mode == "string" else pa.int64(),
            )
        else:
            arrays[name] = pa.array(
                [
                    {
                        "original_type": cell["original_type"],
                        "encoding": cell["encoding"],
                        "text": cell["value"]
                        if isinstance(cell["value"], str)
                        else None,
                        "integer": cell["value"]
                        if type(cell["value"]) is int
                        else None,
                    }
                    for cell in cells
                ],
                type=CELL,
            )
    arrays["__legacy_position"] = pa.array(list(positions), type=pa.int64())
    arrays["__legacy_index"] = pa.array(
        [dumps(preserved("index", frame.index[position])) for position in positions],
        type=pa.large_string(),
    )
    batch = pa.record_batch(arrays)
    return batch, {
        "expected": expected_by_column,
        "repair_counts": repair_counts,
        "opaque_cells": opaque_cells,
        "fingerprint": fingerprint.digest(),
    }


def validate_batch(
    batch: pa.RecordBatch,
    frame: pd.DataFrame,
    profiles: dict[str, Any],
    expected: dict[str, list[dict[str, Any]]],
) -> None:
    rows = batch.to_pylist()
    for name in frame.columns:
        mode = profiles[name]["representation"]
        for row, original in zip(rows, expected[name], strict=True):
            item = row[name]
            if mode == "cell":
                recovered = {
                    "schema_version": original["schema_version"],
                    "name": name,
                    "original_type": item["original_type"],
                    "encoding": item["encoding"],
                    "value": item["text"]
                    if item["text"] is not None
                    else item["integer"],
                }
            else:
                recovered = {**original, "value": item}
            if recovered != original:
                raise ValueError(
                    f"PARQUET_ROUNDTRIP_MISMATCH:{name}:{row['__legacy_position']}"
                )


def parquet_field(name: str, mode: str) -> pa.Field:
    if mode == "string":
        return pa.field(name, pa.large_string())
    if mode == "int64":
        return pa.field(name, pa.int64())
    return pa.field(name, CELL)


def run(
    snapshot: Path,
    expected_hash: str,
    overlay_path: Path,
    output: Path,
    report: Path,
    row_group_size: int,
) -> dict[str, Any]:
    started = time.monotonic()
    before = snapshot.stat()
    snapshot_hash = digest(snapshot)
    if snapshot_hash != expected_hash:
        raise ValueError("ARCHIVE_HASH_MISMATCH")
    print("Source hash verified; loading existing DataFrame", flush=True)
    frame = load_data(snapshot)
    if (
        not isinstance(frame, pd.DataFrame)
        or not frame.columns.is_unique
        or frame.empty
    ):
        raise ValueError("INVALID_FRAME")
    if any(name.startswith("__legacy_") for name in frame.columns):
        raise ValueError("RESERVED_COLUMN_COLLISION")
    if not REPAIR_FIELDS.issubset(set(frame.columns)):
        raise ValueError("MISSING_REPAIR_FIELDS")
    output.mkdir(parents=True, exist_ok=False)
    overlay_hash = digest(overlay_path)
    overlay = load_overlay(overlay_path, snapshot_hash, len(frame))
    profiles = profile(frame)
    contracts = {
        name: {
            "mode": profiles[name]["representation"],
            "dtype": profiles[name]["dtype"],
            "types": profiles[name]["types"],
        }
        for name in frame.columns
    }
    metadata = {
        "format": FORMAT_VERSION,
        "scope": "FULL",
        "snapshot_sha256": snapshot_hash,
        "snapshot_size": before.st_size,
        "archive_locator": str(snapshot.resolve()),
        "overlay_sha256": overlay_hash,
        "overlay_locator": str(overlay_path.resolve()),
        "total_rows": len(frame),
        "columns": list(frame.columns),
        "contracts": contracts,
        "index_class": label(frame.index),
        "index_dtype": str(frame.index.dtype),
        "index_names": list(frame.index.names),
    }
    schema = pa.schema(
        [
            *[parquet_field(name, contracts[name]["mode"]) for name in frame.columns],
            pa.field("__legacy_position", pa.int64()),
            pa.field("__legacy_index", pa.large_string()),
        ],
        metadata={b"legacy": dumps(metadata).encode()},
    )
    parquet_path = output / "legacy-corrected-full.parquet"
    totals = {
        "decision_date": 0,
        "closing_argument": 0,
        "opaque_cells": 0,
        "cell_fingerprint": hashlib.sha256(),
    }
    row_groups = 0
    write_started = time.monotonic()
    with pq.ParquetWriter(parquet_path, schema=schema, compression="zstd") as writer:
        for start in range(0, len(frame), row_group_size):
            positions = range(start, min(start + row_group_size, len(frame)))
            batch, stats = make_batch(frame, profiles, overlay, positions)
            writer.write_batch(batch)
            row_groups += 1
            totals["decision_date"] += stats["repair_counts"]["decision_date"]
            totals["closing_argument"] += stats["repair_counts"]["closing_argument"]
            totals["opaque_cells"] += stats["opaque_cells"]
            totals["cell_fingerprint"].update(stats["fingerprint"])
            if start == 0 or (start + len(positions)) % 5000 == 0:
                print(f"Wrote {start + len(positions)}/{len(frame)} rows", flush=True)
    write_seconds = time.monotonic() - write_started
    verify_started = time.monotonic()
    parquet_file = pq.ParquetFile(parquet_path)
    if parquet_file.metadata.num_rows != len(frame):
        raise ValueError("PARQUET_ROW_COUNT_MISMATCH")
    if parquet_file.schema_arrow != schema:
        raise ValueError("PARQUET_SCHEMA_MISMATCH")
    for group_index in range(parquet_file.num_row_groups):
        start = group_index * row_group_size
        positions = range(start, min(start + row_group_size, len(frame)))
        batch, stats = make_batch(frame, profiles, overlay, positions)
        restored = parquet_file.read_row_group(group_index).to_batches()[0]
        if not restored.schema.equals(batch.schema, check_metadata=False):
            raise ValueError("PARQUET_ROW_GROUP_SCHEMA_MISMATCH")
        validate_batch(restored, frame, profiles, stats["expected"])
        if group_index == 0 or (start + len(positions)) % 5000 == 0:
            print(f"Verified {start + len(positions)}/{len(frame)} rows", flush=True)
    verify_seconds = time.monotonic() - verify_started
    after = snapshot.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise ValueError("ARCHIVE_CHANGED_DURING_EXPORT")
    parquet_sha = digest(parquet_path)
    result = {
        "scope": "FULL_CORRECTED_LEGACY_PARQUET",
        "format": FORMAT_VERSION,
        "snapshot_sha256": snapshot_hash,
        "overlay_sha256": overlay_hash,
        "rows": len(frame),
        "columns": len(frame.columns),
        "parquet": {
            "path": str(parquet_path.resolve()),
            "sha256": parquet_sha,
            "bytes": parquet_path.stat().st_size,
            "row_groups": row_groups,
            "row_group_size": row_group_size,
        },
        "repairs_applied": {
            "decision_date": totals["decision_date"],
            "closing_argument": totals["closing_argument"],
        },
        "opaque_cells": totals["opaque_cells"],
        "cell_fingerprint": totals["cell_fingerprint"].hexdigest(),
        "python_roundtrip": True,
        "source_stat_unchanged": True,
        "write_seconds": write_seconds,
        "read_verify_seconds": verify_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "schema": metadata,
    }
    (output / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--row-group-size", type=int, default=512)
    args = parser.parse_args()
    if args.row_group_size < 1:
        raise ValueError("INVALID_ROW_GROUP_SIZE")
    run(
        args.snapshot,
        args.expected_sha256,
        args.overlay,
        args.output,
        args.report,
        args.row_group_size,
    )
