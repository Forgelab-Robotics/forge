from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, Literal, Self

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, model_validator

from forge_msgs.arrow import ensure_record_batch

TOOL_ENDPOINT_PROTOCOL = "forge.tool.endpoint/v1alpha1"
MAX_SAFE_JSON_INTEGER = 9_007_199_254_740_991


class ToolMessageSizeError(ValueError):
    """A raw ToolMessage payload exceeds a caller-configured carrier limit."""

    def __init__(self, size: int, maximum: int) -> None:
        self.size = size
        self.maximum = maximum
        super().__init__(f"payload_json size {size} exceeds limit {maximum}")


ToolMessageType = Literal[
    "endpoint.register",
    "endpoint.unregister",
    "endpoint.heartbeat",
    "endpoint.registry.response",
    "endpoint.status",
    "tool.invoke.request",
    "tool.invoke.response",
    "tool.status.request",
    "tool.status.response",
    "tool.result.request",
    "tool.result.response",
    "tool.control.request",
    "tool.control.response",
    "tool.event",
    "tool.error",
]

_MANAGEMENT_MESSAGES = frozenset(
    (
        "endpoint.register",
        "endpoint.unregister",
        "endpoint.heartbeat",
        "endpoint.registry.response",
        "endpoint.status",
    )
)
_MANAGEMENT_MESSAGES_REQUIRING_REQUEST_ID = frozenset(
    (
        "endpoint.register",
        "endpoint.unregister",
        "endpoint.heartbeat",
        "endpoint.registry.response",
    )
)
_EVENT_MESSAGE = "tool.event"

TOOL_MESSAGE_SCHEMA = pa.schema(
    [
        pa.field("protocol", pa.string(), nullable=False),
        pa.field("message_type", pa.string(), nullable=False),
        pa.field("request_id", pa.string(), nullable=True),
        pa.field("invocation_id", pa.string(), nullable=True),
        pa.field("attempt_id", pa.string(), nullable=True),
        pa.field("endpoint_id", pa.string(), nullable=False),
        pa.field("endpoint_instance_id", pa.string(), nullable=False),
        pa.field("operation", pa.string(), nullable=True),
        pa.field("sequence", pa.int64(), nullable=True),
        pa.field("payload_json", pa.string(), nullable=False),
    ]
)


def _is_unicode_whitespace(character: str) -> bool:
    code_point = ord(character)
    return (
        0x09 <= code_point <= 0x0D
        or code_point
        in {0x20, 0x85, 0xA0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000}
        or 0x2000 <= code_point <= 0x200A
    )


def _is_blank(value: str) -> bool:
    return not value or all(_is_unicode_whitespace(character) for character in value)


def _require_nonempty(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if _is_blank(value):
        raise ValueError(f"{field_name} must be non-empty when present")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"{field_name} must contain valid Unicode scalar values")


def _duplicate_checked_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _safe_integer(value: str) -> int:
    parsed = int(value)
    if abs(parsed) > MAX_SAFE_JSON_INTEGER:
        raise ValueError(
            f"integer exceeds interoperable range ±{MAX_SAFE_JSON_INTEGER}"
        )
    return parsed


def _validate_json_value(value: Any, path: str, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError(f"{path} JSON nesting exceeds 64")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_JSON_INTEGER:
            raise ValueError(
                f"{path} integer exceeds interoperable range ±{MAX_SAFE_JSON_INTEGER}"
            )
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} floating-point values must be finite")
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError(f"{path} must contain valid Unicode scalar values")
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} JSON object keys must be strings")
            if any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                raise ValueError(
                    f"{path} JSON object keys must contain valid Unicode scalar values"
                )
            _validate_json_value(nested, f"{path}.{key}", depth + 1)
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_json_value(nested, f"{path}[{index}]", depth + 1)
        return
    raise ValueError(f"{path} contains unsupported JSON value")


def _parse_payload_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(
            value,
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=_invalid_constant,
            parse_int=_safe_integer,
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"payload_json must be valid strict JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("payload_json must be a JSON object")
    _validate_json_value(parsed, "payload_json")
    return parsed


def _read_scalar(batch: pa.RecordBatch, field_name: str) -> Any:
    return batch[field_name][0].as_py()


class ToolMessage(BaseModel):
    """Single-row Arrow carrier for one Forge ToolEndpoint logical message."""

    model_config = ConfigDict(strict=True, frozen=True)

    protocol: str = TOOL_ENDPOINT_PROTOCOL
    message_type: ToolMessageType
    request_id: str | None = None
    invocation_id: str | None = None
    attempt_id: str | None = None
    endpoint_id: str
    endpoint_instance_id: str
    operation: str | None = None
    sequence: int | None = None
    payload_json: str = "{}"

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.protocol != TOOL_ENDPOINT_PROTOCOL:
            raise ValueError(f"protocol must equal {TOOL_ENDPOINT_PROTOCOL!r}")
        for field_name in (
            "request_id",
            "invocation_id",
            "attempt_id",
            "endpoint_id",
            "endpoint_instance_id",
            "operation",
        ):
            _require_nonempty(getattr(self, field_name), field_name)
        if self.message_type in _MANAGEMENT_MESSAGES:
            if (
                self.message_type in _MANAGEMENT_MESSAGES_REQUIRING_REQUEST_ID
                and self.request_id is None
            ):
                raise ValueError(
                    "request_id must be non-null for endpoint management exchanges"
                )
            if self.message_type == "endpoint.status" and self.request_id is not None:
                raise ValueError(
                    "request_id must be null for unsolicited endpoint.status"
                )
            for field_name in ("invocation_id", "attempt_id", "operation", "sequence"):
                if getattr(self, field_name) is not None:
                    raise ValueError(
                        f"{field_name} must be null for endpoint management messages"
                    )
        else:
            for field_name in ("invocation_id", "attempt_id", "operation"):
                if getattr(self, field_name) is None:
                    raise ValueError(
                        f"{field_name} must be non-null for Tool execution messages"
                    )
            if self.message_type == _EVENT_MESSAGE:
                if self.request_id is not None:
                    raise ValueError("request_id must be null for tool.event")
            elif self.request_id is None:
                raise ValueError(
                    "request_id must be non-null for non-event Tool execution messages"
                )
        if self.message_type == _EVENT_MESSAGE:
            if self.sequence is None:
                raise ValueError("sequence must be non-null for tool.event")
            if (
                isinstance(self.sequence, bool)
                or not 0 <= self.sequence <= MAX_SAFE_JSON_INTEGER
            ):
                raise ValueError(f"sequence must be in [0, {MAX_SAFE_JSON_INTEGER}]")
        elif self.sequence is not None:
            raise ValueError("sequence must be null for non-event messages")
        _parse_payload_json(self.payload_json)
        return self

    @classmethod
    def from_payload(
        cls,
        *,
        message_type: ToolMessageType,
        endpoint_id: str,
        endpoint_instance_id: str,
        payload: Mapping[str, Any],
        request_id: str | None = None,
        invocation_id: str | None = None,
        attempt_id: str | None = None,
        operation: str | None = None,
        sequence: int | None = None,
    ) -> ToolMessage:
        """Construct a carrier with deterministic compact payload JSON."""
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        copied_payload = dict(payload)
        try:
            _validate_json_value(copied_payload, "payload")
            payload_json = json.dumps(
                copied_payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError, UnicodeEncodeError) as error:
            raise ValueError(f"payload must be strict JSON: {error}") from error
        return cls(
            message_type=message_type,
            request_id=request_id,
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            endpoint_id=endpoint_id,
            endpoint_instance_id=endpoint_instance_id,
            operation=operation,
            sequence=sequence,
            payload_json=payload_json,
        )

    def payload(self) -> dict[str, Any]:
        """Return a decoded copy of the strict JSON object payload."""
        return _parse_payload_json(self.payload_json)

    def to_arrow(self) -> pa.RecordBatch:
        """Encode this carrier as an exact-schema single-row RecordBatch."""
        return pa.RecordBatch.from_arrays(
            [
                pa.array([self.protocol], type=pa.string()),
                pa.array([self.message_type], type=pa.string()),
                pa.array([self.request_id], type=pa.string()),
                pa.array([self.invocation_id], type=pa.string()),
                pa.array([self.attempt_id], type=pa.string()),
                pa.array([self.endpoint_id], type=pa.string()),
                pa.array([self.endpoint_instance_id], type=pa.string()),
                pa.array([self.operation], type=pa.string()),
                pa.array([self.sequence], type=pa.int64()),
                pa.array([self.payload_json], type=pa.string()),
            ],
            schema=TOOL_MESSAGE_SCHEMA,
        )

    @classmethod
    def from_arrow(
        cls,
        data: pa.RecordBatch | pa.Table | pa.StructArray | bytes,
        *,
        max_payload_json_bytes: int | None = None,
    ) -> ToolMessage:
        """Decode an exact-schema single-row Arrow carrier."""
        if isinstance(data, bytes):
            batches = list(pa.ipc.open_stream(data))
            if len(batches) != 1:
                raise ValueError(
                    "ToolMessage IPC stream must contain exactly one RecordBatch"
                )
            batch = batches[0]
        elif isinstance(data, pa.Table):
            batches = data.to_batches()
            if len(batches) != 1:
                raise ValueError(
                    "ToolMessage Table must contain exactly one RecordBatch"
                )
            batch = batches[0]
        else:
            batch = ensure_record_batch(data)
        if batch.num_rows != 1:
            raise ValueError("ToolMessage RecordBatch must contain exactly one row")
        if not batch.schema.equals(TOOL_MESSAGE_SCHEMA, check_metadata=False):
            raise ValueError(
                "ToolMessage RecordBatch schema must exactly match TOOL_MESSAGE_SCHEMA"
            )
        payload_json = _read_scalar(batch, "payload_json")
        if max_payload_json_bytes is not None:
            if (
                isinstance(max_payload_json_bytes, bool)
                or not isinstance(max_payload_json_bytes, int)
                or max_payload_json_bytes <= 0
            ):
                raise ValueError("max_payload_json_bytes must be a positive integer")
            if isinstance(payload_json, str):
                try:
                    payload_size = len(payload_json.encode("utf-8"))
                except UnicodeEncodeError as error:
                    raise ValueError(
                        "payload_json must contain valid Unicode scalar values"
                    ) from error
                if payload_size > max_payload_json_bytes:
                    raise ToolMessageSizeError(
                        payload_size,
                        max_payload_json_bytes,
                    )
        return cls(
            protocol=_read_scalar(batch, "protocol"),
            message_type=_read_scalar(batch, "message_type"),
            request_id=_read_scalar(batch, "request_id"),
            invocation_id=_read_scalar(batch, "invocation_id"),
            attempt_id=_read_scalar(batch, "attempt_id"),
            endpoint_id=_read_scalar(batch, "endpoint_id"),
            endpoint_instance_id=_read_scalar(batch, "endpoint_instance_id"),
            operation=_read_scalar(batch, "operation"),
            sequence=_read_scalar(batch, "sequence"),
            payload_json=payload_json,
        )
