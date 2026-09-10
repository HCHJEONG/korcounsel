"""Analysis-only full type audit and bounded Parquet preservation experiment.

Run with pinned pandas/numpy/pyarrow; never imported by the application worker.
"""

import argparse
import hashlib
import json
import math
import resource
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from inspect_legacy_pickle import load_data

from klegal_gold.ingestion.legacy_bundle import preserve_field

CELL = pa.struct(
    [
        ("original_type", pa.string()),
        ("encoding", pa.string()),
        ("text", pa.large_string()),
        ("integer", pa.int64()),
    ]
)


def label(value: Any) -> str:
    return type(value).__module__ + "." + type(value).__qualname__


def preserved(name: str, value: Any) -> dict[str, Any]:
    original_type = label(value)
    if isinstance(value, (np.integer, np.floating, np.bool_, np.str_)):
        value = value.item()
    result = preserve_field(name, value, original_type=original_type).model_dump(mode="json")
    # Integers beyond signed int64 retain exact decimal digits, without float coercion.
    if result["encoding"] == "INTEGER" and not -(2**63) <= value < 2**63:
        result["encoding"] = "BIG_INTEGER"
        result["value"] = str(value)
    return result


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def node_value(value: Any) -> Any:
    if type(value) is int:
        return str(value)  # DuckDB BIGINT JSON API intentionally returns decimal strings.
    if isinstance(value, dict):
        return {key: node_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [node_value(item) for item in value]
    return value


def profile(frame: pd.DataFrame) -> tuple[dict[str, Any], list[int]]:
    result = {}
    selected = set(range(0, len(frame), max(1, len(frame) // 100))) | {len(frame) - 1}
    for name in frame.columns:
        values = frame[name]
        types: Counter[str] = Counter()
        categories: Counter[str] = Counter()
        first = {}
        longest = (-1, 0)
        int64 = True
        for position in range(len(values)):
            value = values.iloc[position]
            kind = label(value)
            types[kind] += 1
            category = kind
            if isinstance(value, str):
                category += ":empty" if value == "" else ":blank" if not value.strip() else ":text"
                if len(value) > longest[0]:
                    longest = (len(value), position)
            elif isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
                category += ":zero" if value == 0 else ":nonzero"
                int64 &= -(2**63) <= int(value) < 2**63
            elif isinstance(value, (float, np.floating)):
                category += (
                    ":nan" if math.isnan(value) else ":infinite" if math.isinf(value) else ":finite"
                )
            categories[category] += 1
            first.setdefault(category, position)
        selected.update(first.values())
        if longest[0] >= 0:
            selected.add(longest[1])
        native = "string" if set(types) == {"builtins.str"} else "cell"
        if len(types) == 1 and next(iter(types)) in {"builtins.int", "numpy.int64"} and int64:
            native = "int64"
        result[name] = {
            "dtype": str(values.dtype),
            "types": dict(types),
            "categories": dict(categories),
            "first_positions": first,
            "longest_string": longest,
            "representation": native,
        }
        print(f"Profiled {name}: {dict(types)}", flush=True)
    return result, sorted(selected)


def sample(
    frame: pd.DataFrame,
    profiles: dict[str, Any],
    positions: list[int],
    output: Path,
    source: dict[str, Any],
) -> dict[str, Any]:
    arrays = {}
    contracts = {}
    originals = {}
    for name in frame.columns:
        cells = [preserved(name, frame[name].iloc[p]) for p in positions]
        originals[name] = cells
        mode = profiles[name]["representation"]
        contracts[name] = {
            "mode": mode,
            "dtype": profiles[name]["dtype"],
            "types": profiles[name]["types"],
        }
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
                        "text": cell["value"] if isinstance(cell["value"], str) else None,
                        "integer": cell["value"] if type(cell["value"]) is int else None,
                    }
                    for cell in cells
                ],
                type=CELL,
            )
    if any(name.startswith("__legacy_") for name in frame.columns):
        raise ValueError("RESERVED_COLUMN_COLLISION")
    arrays["__legacy_position"] = pa.array(positions, type=pa.int64())
    arrays["__legacy_index"] = pa.array(
        [dumps(preserved("index", frame.index[p])) for p in positions], type=pa.large_string()
    )
    metadata = {
        **source,
        "scope": "SAMPLE",
        "columns": list(frame.columns),
        "contracts": contracts,
        "positions": positions,
        "index_class": label(frame.index),
        "index_dtype": str(frame.index.dtype),
        "index_names": list(frame.index.names),
        "format": "legacy-parquet-experiment-1",
    }
    table = pa.table(arrays).replace_schema_metadata({b"legacy": dumps(metadata).encode()})
    started = time.monotonic()
    path = output / "sample.parquet"
    pq.write_table(table, path, compression="zstd", row_group_size=32)
    write_seconds = time.monotonic() - started
    started = time.monotonic()
    restored = pq.read_table(path)
    assert restored.schema.equals(table.schema, check_metadata=True)
    assert restored.equals(table)
    restored_rows = restored.to_pylist()
    fingerprint = hashlib.sha256()
    opaque = 0
    for name in frame.columns:
        for row, original in zip(restored_rows, originals[name], strict=True):
            item = row[name]
            if contracts[name]["mode"] == "cell":
                recovered = {
                    "schema_version": original["schema_version"],
                    "name": name,
                    "original_type": item["original_type"],
                    "encoding": item["encoding"],
                    "value": item["text"] if item["text"] is not None else item["integer"],
                }
            else:
                recovered = {**original, "value": item}
            assert recovered == original, (name, row["__legacy_position"])
            opaque += original["encoding"] == "OPAQUE"
            encoded = dumps(original).encode()
            fingerprint.update(len(encoded).to_bytes(8, "big"))
            fingerprint.update(encoded)
    assert pq.read_table(path, columns=[frame.columns[0]]).equals(
        restored.select([frame.columns[0]])
    )
    read_verify_seconds = time.monotonic() - started
    expected = dumps(node_value(table.to_pylist())).encode()
    (output / "expected.json").write_bytes(expected)
    raw = path.read_bytes()
    result = {
        "rows": len(positions),
        "columns": len(frame.columns),
        "positions": positions,
        "opaque_cells": opaque,
        "value_cells": len(positions) * len(frame.columns) - opaque,
        "parquet_bytes": len(raw),
        "arrow_uncompressed_bytes": table.nbytes,
        "parquet_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_sha256": hashlib.sha256(expected).hexdigest(),
        "cell_fingerprint": fingerprint.hexdigest(),
        "python_roundtrip": True,
        "selected_column_read": True,
        "write_seconds": write_seconds,
        "read_verify_seconds": read_verify_seconds,
        "schema": metadata,
    }
    (output / "manifest.json").write_text(dumps(result) + "\n")
    return result


def run(snapshot: Path, expected_hash: str, output: Path, report: Path) -> None:
    started = time.monotonic()
    before = snapshot.stat()
    with snapshot.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected_hash:
        raise ValueError("ARCHIVE_HASH_MISMATCH")
    print("Source hash verified; loading DataFrame", flush=True)
    frame = load_data(snapshot)
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique or frame.empty:
        raise ValueError("INVALID_FRAME")
    output.mkdir(parents=True, exist_ok=False)
    profiles, positions = profile(frame)
    # Demonstrate whether naive pandas/Arrow inference works on the same sample.
    try:
        pa.Table.from_pandas(frame.iloc[positions], preserve_index=True)
        naive = {"success": True}
    except (pa.ArrowException, TypeError, ValueError) as exc:
        naive = {"success": False, "error_type": type(exc).__name__, "error": str(exc)[:500]}
    result = sample(
        frame,
        profiles,
        positions,
        output,
        {
            "snapshot_sha256": digest,
            "archive_locator": str(snapshot.resolve()),
            "snapshot_size": before.st_size,
            "total_rows": len(frame),
        },
    )
    after = snapshot.stat()
    assert (before.st_size, before.st_mtime_ns, before.st_ino) == (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    )
    report.write_text(
        json.dumps(
            {
                "scope": "FULL_TYPE_PROFILE_AND_SAMPLE_PARQUET",
                "runtime": {
                    "pandas": pd.__version__,
                    "numpy": np.__version__,
                    "pyarrow": pa.__version__,
                },
                "profile": profiles,
                "naive_conversion": naive,
                "sample": result,
                "elapsed_seconds": time.monotonic() - started,
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"Verified {result['rows']} rows, {result['columns']} columns", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    run(args.snapshot, args.expected_sha256, args.output, args.report)
