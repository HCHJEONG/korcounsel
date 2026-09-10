"""Shared scalar contracts. Validation errors use stable project reason codes."""

from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
)

Text = Annotated[
    StrictStr,
    Field(min_length=1),
    AfterValidator(lambda value: value if value.strip() else _empty_text()),
]
Digest = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[StrictInt, Field(ge=0)]
Revision = Annotated[StrictInt, Field(ge=1)]


def _empty_text() -> str:
    raise ValueError("EMPTY_TEXT")


def _time_input(value: object) -> object:
    if not isinstance(value, (str, datetime)):
        raise ValueError("INVALID_TIMESTAMP_TYPE")
    return value


def _date_input(value: object) -> object:
    if isinstance(value, datetime) or not isinstance(value, (str, date)):
        raise ValueError("INVALID_DATE_TYPE")
    if isinstance(value, str) and (len(value) != 10 or value[4] != "-" or value[7] != "-"):
        raise ValueError("INVALID_DATE_FORMAT")
    return value


UTCDateTime = Annotated[
    AwareDatetime,
    BeforeValidator(_time_input),
    AfterValidator(lambda value: value.astimezone(UTC)),
]
DecisionDate = Annotated[date, BeforeValidator(_date_input)]


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    sensitive = {
        "oc",
        "key",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "signature",
        "password",
        "credential",
        "authorization",
    }
    keys = {key.lower() for key, _ in parse_qsl(parsed.query)}
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or sensitive & keys
        or any(key.startswith("x-amz-") for key in keys)
    ):
        raise ValueError("UNSAFE_SOURCE_URL")
    return value


SourceURL = Annotated[Text, AfterValidator(_safe_url)]


def content_hash(raw: bytes) -> str:
    """Hash response bytes; decoding/normalization must happen afterwards."""
    return sha256(raw).hexdigest()


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True, hide_input_in_errors=True
    )
    schema_version: Literal["0.1.0"] = "0.1.0"
