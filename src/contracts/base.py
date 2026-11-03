"""Shared strict JSON primitives and protocol identifiers."""

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^\s/\\]+$")]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Ratio = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Count = Annotated[int, Field(ge=0)]


def _utc(value: object) -> datetime:
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", value):
            raise ValueError("timestamp must be UTC RFC3339 with millisecond precision")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware UTC timestamp required")
    if value.utcoffset().total_seconds() != 0 or value.microsecond % 1000:
        raise ValueError("UTC with millisecond precision required")
    return value.astimezone(timezone.utc)


Timestamp = Annotated[
    datetime,
    BeforeValidator(_utc),
    PlainSerializer(
        lambda t: t.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]


def _relative(value: str) -> str:
    if (
        value.startswith(("/", "\\"))
        or "\\" in value
        or any(part in ("", ".", "..") for part in value.split("/"))
        or ":" in value
    ):
        raise ValueError("safe relative POSIX path required")
    return value


RelativePath = Annotated[str, Field(min_length=1), AfterValidator(_relative)]


class Contract(BaseModel):
    """No coercion, extra properties, infinities or mutable assignment."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        allow_inf_nan=False,
        validate_default=True,
        hide_input_in_errors=True,
    )


def strict_json_loads(data: str | bytes) -> object:
    """Reject duplicate keys and non-JSON numeric constants before model validation."""

    def pairs(items: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)


def parse_contract(model: type[BaseModel], data: str | bytes) -> BaseModel:
    """Use this boundary instead of model_validate_json (which accepts duplicate keys)."""
    return model.model_validate(strict_json_loads(data))


class TimeRange(Contract):
    start_at: Timestamp
    end_at: Timestamp

    def model_post_init(self, context: object) -> None:
        if self.start_at >= self.end_at:
            raise ValueError("range must be nonempty and half-open")


def content_hash(value: Contract | dict | list) -> str:
    """Canonical digest of a contract or an explicit JSON manifest/collection.

    Existing contract bytes remain unchanged; lifecycle manifests and ordered
    replay references use the same canonical encoding instead of ad hoc hashes.
    """
    document = value.model_dump(mode="json") if isinstance(value, Contract) else value
    if not isinstance(document, (dict, list)):
        raise TypeError("contract or JSON manifest required")
    raw = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()
