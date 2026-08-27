"""EndpointDescriptor conversion for registration payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..endpoint import ToolEndpointDescriptor, ToolOperationDescriptor
from .envelope import TOOL_ENDPOINT_PROTOCOL, ToolEnvelope
from .errors import ToolProtocolError

_DESCRIPTOR_FIELDS = frozenset(("protocol_version", "endpoint_id", "operations"))
_OPERATION_FIELDS = frozenset(
    (
        "name",
        "semantics",
        "cancellable",
        "stoppable",
        "status_supported",
        "max_concurrency",
    )
)


def _validate_fields(
    value: Mapping[Any, Any],
    expected: frozenset[str],
    path: str,
) -> None:
    if not all(isinstance(key, str) for key in value):
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "object keys must be strings",
            path=path,
        )
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "; ".join(details),
            path=path,
        )


def endpoint_descriptor_to_payload(
    descriptor: ToolEndpointDescriptor,
) -> dict[str, Any]:
    """Convert a descriptor into an ``endpoint.register`` payload."""
    if not isinstance(descriptor, ToolEndpointDescriptor):
        raise TypeError("descriptor must be a ToolEndpointDescriptor")
    if descriptor.protocol_version != TOOL_ENDPOINT_PROTOCOL:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_UNSUPPORTED_VERSION",
            f"expected {TOOL_ENDPOINT_PROTOCOL!r}, found {descriptor.protocol_version!r}",
            path="payload.descriptor.protocol_version",
        )
    return {
        "descriptor": {
            "protocol_version": descriptor.protocol_version,
            "endpoint_id": descriptor.endpoint_id,
            "operations": [
                {
                    "name": operation.name,
                    "semantics": operation.semantics,
                    "cancellable": operation.cancellable,
                    "stoppable": operation.stoppable,
                    "status_supported": operation.status_supported,
                    "max_concurrency": operation.max_concurrency,
                }
                for operation in descriptor.operations
            ],
        }
    }


def endpoint_descriptor_from_payload(
    payload: Mapping[str, Any],
) -> ToolEndpointDescriptor:
    """Parse a strict ``endpoint.register`` descriptor payload."""
    if not isinstance(payload, Mapping):
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "registration payload must be an object",
            path="payload",
        )
    _validate_fields(payload, frozenset(("descriptor",)), "payload")
    value = payload["descriptor"]
    if not isinstance(value, Mapping):
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "must be an object",
            path="payload.descriptor",
        )
    _validate_fields(value, _DESCRIPTOR_FIELDS, "payload.descriptor")
    if value["protocol_version"] != TOOL_ENDPOINT_PROTOCOL:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_UNSUPPORTED_VERSION",
            f"expected {TOOL_ENDPOINT_PROTOCOL!r}, found {value['protocol_version']!r}",
            path="payload.descriptor.protocol_version",
        )
    raw_operations = value["operations"]
    if not isinstance(raw_operations, list):
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "must be an array",
            path="payload.descriptor.operations",
        )

    operations: list[ToolOperationDescriptor] = []
    for index, raw_operation in enumerate(raw_operations):
        path = f"payload.descriptor.operations[{index}]"
        if not isinstance(raw_operation, Mapping):
            raise ToolProtocolError(
                "FORGE_PROTOCOL_INVALID_PAYLOAD",
                "must be an object",
                path=path,
            )
        _validate_fields(raw_operation, _OPERATION_FIELDS, path)
        try:
            operations.append(
                ToolOperationDescriptor(
                    name=raw_operation["name"],
                    semantics=raw_operation["semantics"],
                    cancellable=raw_operation["cancellable"],
                    stoppable=raw_operation["stoppable"],
                    status_supported=raw_operation["status_supported"],
                    max_concurrency=raw_operation["max_concurrency"],
                )
            )
        except (TypeError, ValueError) as error:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_INVALID_PAYLOAD",
                str(error),
                path=path,
            ) from error

    try:
        return ToolEndpointDescriptor(
            protocol_version=value["protocol_version"],
            endpoint_id=value["endpoint_id"],
            operations=tuple(operations),
        )
    except (TypeError, ValueError) as error:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            str(error),
            path="payload.descriptor",
        ) from error


def validate_registration_envelope(envelope: ToolEnvelope) -> ToolEndpointDescriptor:
    """Validate a complete registration and return its descriptor."""
    if not isinstance(envelope, ToolEnvelope):
        raise TypeError("envelope must be a ToolEnvelope")
    if envelope.message_type != "endpoint.register":
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_MESSAGE",
            "expected endpoint.register",
            path="message_type",
        )
    descriptor = endpoint_descriptor_from_payload(envelope.payload)
    if descriptor.endpoint_id != envelope.endpoint_id:
        raise ToolProtocolError(
            "FORGE_PROTOCOL_INVALID_PAYLOAD",
            "descriptor endpoint_id must match envelope endpoint_id",
            path="payload.descriptor.endpoint_id",
        )
    return descriptor
