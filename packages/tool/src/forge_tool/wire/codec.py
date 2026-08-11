"""Strict UTF-8 JSON codec for ToolEndpoint envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .envelope import MAX_SAFE_JSON_INTEGER, ToolEnvelope
from .errors import ToolProtocolError
from .messages import validate_message_envelope

DEFAULT_MAX_MESSAGE_BYTES = 1_048_576
_ENVELOPE_FIELDS = frozenset(
    (
        "protocol",
        "message_type",
        "request_id",
        "invocation_id",
        "attempt_id",
        "endpoint_id",
        "endpoint_instance_id",
        "operation",
        "sequence",
        "payload",
    )
)
_REQUIRED_FIELDS = frozenset(
    (
        "protocol",
        "message_type",
        "endpoint_id",
        "payload",
    )
)
_OPTIONAL_FIELDS = frozenset(
    (
        "request_id",
        "invocation_id",
        "attempt_id",
        "endpoint_instance_id",
        "operation",
        "sequence",
    )
)


def _duplicate_checked_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_DUPLICATE_KEY",
                f"duplicate JSON object key: {key!r}",
            )
        value[key] = item
    return value


def _invalid_constant(value: str) -> None:
    raise ToolProtocolError(
        "FORGE_PROTOCOL_INVALID_JSON",
        f"non-finite JSON number is not allowed: {value}",
    )


def _safe_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_JSON",
            "integer cannot be parsed safely",
        ) from error
    if abs(parsed) > MAX_SAFE_JSON_INTEGER:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_JSON",
            f"integer exceeds interoperable range ±{MAX_SAFE_JSON_INTEGER}",
        )
    return parsed


def _validate_max_size(size: int, maximum: int) -> None:
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise ValueError("max_message_bytes must be a positive integer")
    if size > maximum:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_MESSAGE_TOO_LARGE",
            f"message size {size} exceeds limit {maximum}",
        )


def _validated_envelope(envelope: ToolEnvelope) -> ToolEnvelope:
    if not isinstance(envelope, ToolEnvelope):
        raise TypeError("envelope must be a ToolEnvelope")
    return ToolEnvelope(
        protocol=envelope.protocol,
        message_type=envelope.message_type,
        request_id=envelope.request_id,
        invocation_id=envelope.invocation_id,
        attempt_id=envelope.attempt_id,
        endpoint_id=envelope.endpoint_id,
        endpoint_instance_id=envelope.endpoint_instance_id,
        operation=envelope.operation,
        sequence=envelope.sequence,
        payload=envelope.payload,
    )


def _encoded_envelope(envelope: ToolEnvelope) -> bytes:
    try:
        text = json.dumps(
            envelope.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        encoded = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            str(error),
            path="payload",
        ) from error
    return encoded


def encoded_envelope_size(envelope: ToolEnvelope) -> int:
    """Return deterministic encoded size without typed message-payload validation."""
    return len(_encoded_envelope(_validated_envelope(envelope)))


def encode_envelope(
    envelope: ToolEnvelope,
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> bytes:
    """Encode one envelope as deterministic compact UTF-8 JSON bytes."""
    validated = _validated_envelope(envelope)
    validate_message_envelope(validated)
    encoded = _encoded_envelope(validated)
    _validate_max_size(len(encoded), max_message_bytes)
    return encoded


def decode_envelope(
    data: bytes | bytearray | memoryview | str,
    *,
    max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
) -> ToolEnvelope:
    """Decode and strictly validate one UTF-8 JSON envelope."""
    if isinstance(data, str):
        try:
            encoded = data.encode("utf-8")
        except UnicodeEncodeError as error:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_INVALID_JSON",
                "message contains an invalid Unicode scalar value",
            ) from error
        _validate_max_size(len(encoded), max_message_bytes)
        text = data
    elif isinstance(data, (bytes, bytearray, memoryview)):
        encoded = bytes(data)
        _validate_max_size(len(encoded), max_message_bytes)
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_INVALID_JSON",
                "message is not valid UTF-8",
            ) from error
    else:
        raise TypeError("data must be UTF-8 bytes or a string")

    try:
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_checked_object,
            parse_constant=_invalid_constant,
            parse_int=_safe_integer,
        )
    except ToolProtocolError:
        raise
    except json.JSONDecodeError as error:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_JSON",
            error.msg,
            path=f"line {error.lineno} column {error.colno}",
        ) from error
    except (RecursionError, ValueError) as error:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_JSON",
            str(error),
        ) from error

    if not isinstance(value, Mapping):
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_MESSAGE",
            "top-level JSON value must be an object",
        )
    unknown = sorted(set(value) - _ENVELOPE_FIELDS)
    if unknown:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_MESSAGE",
            f"unknown envelope fields: {', '.join(unknown)}",
        )
    required_fields = _REQUIRED_FIELDS
    message_type = value.get("message_type")
    if not isinstance(message_type, str) or not message_type.startswith("tool."):
        required_fields = required_fields | {"endpoint_instance_id"}
    missing = sorted(required_fields - set(value))
    if missing:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_MESSAGE",
            f"missing envelope fields: {', '.join(missing)}",
        )
    explicit_nulls = sorted(
        field for field in _OPTIONAL_FIELDS if value.get(field, ...) is None
    )
    if explicit_nulls:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_MESSAGE",
            f"optional fields must be omitted rather than null: {', '.join(explicit_nulls)}",
        )

    try:
        envelope = ToolEnvelope(
            protocol=value["protocol"],
            message_type=value["message_type"],
            request_id=value.get("request_id"),
            invocation_id=value.get("invocation_id"),
            attempt_id=value.get("attempt_id"),
            endpoint_id=value["endpoint_id"],
            endpoint_instance_id=value.get("endpoint_instance_id"),
            operation=value.get("operation"),
            sequence=value.get("sequence"),
            payload=value["payload"],
        )
    except RecursionError as error:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "JSON payload nesting is too deep",
            path="payload",
        ) from error
    validate_message_envelope(envelope)
    return envelope
