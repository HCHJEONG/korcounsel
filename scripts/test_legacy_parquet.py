"""Synthetic adversarial values complement the real corpus sample."""

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from verify_legacy_parquet import preserved, profile, sample


def synthetic(output: Path) -> dict:
    values = [
        "",
        0,
        "0",
        None,
        float("nan"),
        float("inf"),
        -0.0,
        False,
        True,
        [1, "a"],
        (1, "a"),
        {1: "int-key", "1": "str-key"},
        np.int64(7),
        2**60 + 1,
        2**80,
        datetime(2020, 1, 1, tzinfo=UTC),
        object(),
        [object()],
        "한글😀\r\n\x00끝",
    ]
    frame = pd.DataFrame(
        {
            "mixed": pd.Series(values, dtype=object),
            "native_text": ["한글😀"] * len(values),
            "native_int": np.arange(len(values), dtype=np.int64),
        }
    )
    frame.index = pd.Index([7] * len(values), name="duplicate_index")
    profiles, positions = profile(frame)
    output.mkdir(parents=True, exist_ok=False)
    result = sample(
        frame,
        profiles,
        positions,
        output,
        {
            "snapshot_sha256": "0" * 64,
            "archive_locator": "SYNTHETIC_NOT_REAL_ARCHIVE",
            "total_rows": len(frame),
            "synthetic": True,
        },
    )
    rows = pq.read_table(output / "sample.parquet").to_pylist()
    assert [rows[i]["mixed"]["encoding"] for i in range(4)] == [
        "STRING",
        "INTEGER",
        "STRING",
        "NULL",
    ]
    assert rows[4]["mixed"]["text"] == '{"type":"builtins.float","value":"nan"}'
    assert rows[6]["mixed"]["text"] == '{"type":"builtins.float","value":"-0x0.0p+0"}'
    assert json.loads(rows[9]["mixed"]["text"])["type"] == "builtins.list"
    assert json.loads(rows[10]["mixed"]["text"])["type"] == "builtins.tuple"
    assert rows[12]["mixed"]["original_type"] == "numpy.int64"
    assert rows[13]["mixed"]["integer"] == 2**60 + 1
    assert rows[14]["mixed"]["text"] == str(2**80)
    assert rows[16]["mixed"]["encoding"] == rows[17]["mixed"]["encoding"] == "OPAQUE"
    assert rows[18]["mixed"]["text"] == values[18]
    assert len({row["__legacy_index"] for row in rows}) == 1
    assert [row["__legacy_position"] for row in rows] == list(range(len(values)))
    return result


class ParquetTests(unittest.TestCase):
    def test_types_sentinels_unicode_duplicate_index_and_opaque(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = synthetic(Path(temp) / "sample")
            self.assertEqual(result["opaque_cells"], 2)
            self.assertTrue(result["python_roundtrip"])

    def test_integer_overflow_is_not_rounded(self) -> None:
        cell = preserved("large", 2**80 + 1)
        self.assertEqual(cell["encoding"], "BIG_INTEGER")
        self.assertEqual(cell["value"], str(2**80 + 1))


if __name__ == "__main__":
    if len(sys.argv) == 2:
        synthetic(Path(sys.argv[1]))
    else:
        unittest.main()
