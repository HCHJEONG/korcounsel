"""Full-row value preservation and explicit sample/full coverage."""

import json
from datetime import date, datetime

import pytest

from klegal_gold.ingestion.legacy_bundle import LegacyBundle, preserve_field


@pytest.mark.parametrize(
    "value",
    [
        "",
        "empty",
        "본문😀\n<table>원문</table>",
        0,
        123,
        None,
        False,
        True,
        -0.0,
        1.25,
        float("nan"),
        float("inf"),
        date(2020, 1, 2),
        datetime(2020, 1, 2, 3, 4),
        [1, "a", None],
        (1, False),
        {1: "a", "1": (2,)},
    ],
)
def test_scalar_and_nested_value_preservation(value):
    field = preserve_field("field", value)
    assert field.encoding != "OPAQUE"
    if type(value) in (str, int) or value is None:
        assert field.value == value
    else:
        tree = json.loads(field.value)
        assert tree["type"] == type(value).__module__ + "." + type(value).__qualname__
    assert field.original_type == type(value).__module__ + "." + type(value).__qualname__


def test_opaque_does_not_execute_repr_or_string():
    class Opaque:
        def __repr__(self):
            raise AssertionError("must not execute")

        def __str__(self):
            raise AssertionError("must not execute")

    for value in (Opaque(), [Opaque()]):
        field = preserve_field("parser", value)
        assert field.encoding == "OPAQUE"
        assert field.value is None


def bundle(**changes):
    return LegacyBundle.model_validate(
        {
            "snapshot_sha256": "a" * 64,
            "snapshot_size": 100,
            "archive_locator": "synthetic.pickle",
            "total_rows": 2,
            "columns": ["field"],
            "scope": "FULL",
            "entries": [{"position": n, "sha256": str(n) * 64, "size_bytes": 10} for n in range(2)],
        }
        | changes
    )


def test_full_and_sample_coverage_is_explicit():
    value = bundle()
    assert len(value.entries) == 2
    with pytest.raises(ValueError, match="INCOMPLETE_FULL_BUNDLE"):
        bundle(entries=[value.entries[0]])
    assert bundle(entries=[value.entries[0]], scope="SAMPLE").scope == "SAMPLE"
    for entries in ([value.entries[1], value.entries[0]], [value.entries[0]] * 2):
        with pytest.raises(ValueError, match="INVALID_BUNDLE_POSITIONS"):
            bundle(entries=entries)


def test_duplicate_columns_are_not_silent_full_row_coverage():
    with pytest.raises(ValueError, match="DUPLICATE_BUNDLE_COLUMNS"):
        bundle(columns=["field", "field"])
