"""Full-row export contract. Application runtime never loads pickle or pandas."""

import json
import math
from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from klegal_gold.domain.common import Count, Digest, DomainModel, Text
from klegal_gold.domain.legacy import LegacyField

MAX_ROW_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024 * 1024


class BundleEntry(DomainModel):
    position: Count
    sha256: Digest
    size_bytes: int = Field(strict=True, gt=0, le=MAX_ROW_BYTES)


class LegacyBundle(DomainModel):
    format: Literal["legacy-full-row-bundle-1"] = "legacy-full-row-bundle-1"
    snapshot_sha256: Digest
    snapshot_size: int = Field(strict=True, gt=0)
    archive_locator: Text
    total_rows: Count
    columns: tuple[Text, ...] = Field(min_length=1)
    scope: Literal["SAMPLE", "FULL"]
    entries: tuple[BundleEntry, ...] = Field(min_length=1)
    exporter_version: Literal["legacy-export-1"] = "legacy-export-1"

    @model_validator(mode="after")
    def coverage(self) -> Self:
        positions = [entry.position for entry in self.entries]
        if positions != sorted(set(positions)) or positions[-1] >= self.total_rows:
            raise ValueError("INVALID_BUNDLE_POSITIONS")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("DUPLICATE_BUNDLE_COLUMNS")
        if self.scope == "FULL" and positions != list(range(self.total_rows)):
            raise ValueError("INCOMPLETE_FULL_BUNDLE")
        return self


def _typed(value: object) -> dict[str, Any]:
    """Lossless built-in value tree; unknown nested objects stay in the source archive."""
    kind = type(value)
    label = kind.__module__ + "." + kind.__qualname__
    if kind in (str, int, bool, type(None)):
        payload: Any = value
    elif kind is float:
        assert isinstance(value, float)
        payload = (
            value.hex()
            if math.isfinite(value)
            else ("nan" if math.isnan(value) else "+inf" if value > 0 else "-inf")
        )
    elif kind in (date, datetime):
        assert isinstance(value, date)
        payload = value.isoformat()
    elif kind in (list, tuple):
        assert isinstance(value, (list, tuple))
        payload = [_typed(item) for item in value]
    elif kind is dict:
        assert isinstance(value, dict)
        payload = [[_typed(key), _typed(item)] for key, item in value.items()]
    else:
        raise ValueError("OPAQUE_LEGACY_VALUE")
    return {"type": label, "value": payload}


def preserve_field(name: str, value: object, *, original_type: str | None = None) -> LegacyField:
    label = original_type or type(value).__module__ + "." + type(value).__qualname__
    if type(value) is str:
        return LegacyField(name=name, original_type=label, encoding="STRING", value=value)
    if type(value) is int:
        return LegacyField(name=name, original_type=label, encoding="INTEGER", value=value)
    if value is None:
        return LegacyField(name=name, original_type=label, encoding="NULL")
    try:
        encoded = json.dumps(
            _typed(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except ValueError:
        return LegacyField(name=name, original_type=label, encoding="OPAQUE")
    return LegacyField(name=name, original_type=label, encoding="JSON", value=encoded)
