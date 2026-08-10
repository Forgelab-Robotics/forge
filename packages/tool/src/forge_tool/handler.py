"""Transport-independent operation binding and Query-first request handling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .endpoint import (
    ActionToolEndpoint,
    QueryToolEndpoint,
    SessionToolEndpoint,
    ToolEndpointDescriptor,
    ToolEndpointError,
    ToolError,
    ToolResult,
)
from .wire import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolEnvelope,
    ToolProtocolError,
    invoke_request_from_envelope,
    make_error_response_envelope,
    make_invoke_response_envelope,
    validate_message_envelope,
)

_REQUIRED_METHODS = {
    "query": ("query",),
    "action": ("start", "cancel", "status", "result"),
    "session": ("start", "stop", "status", "result"),
}


def _validate_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.isspace():
        raise ValueError(f"{field_name} must be a non-empty string")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError(f"{field_name} must contain valid Unicode scalar values")
    return value


def _validate_implementation(
    operation_name: str,
    semantics: str,
    implementation: object,
) -> None:
    for method_name in _REQUIRED_METHODS[semantics]:
        if not callable(getattr(implementation, method_name, None)):
            raise TypeError(
                f"operation {operation_name!r} with {semantics} semantics requires "
                f"a callable {method_name}() method"
            )


class ToolEndpointHandler:
    """Bind descriptor operations to node implementations and handle Query invokes.

    The handler is transport-independent and owns no Dora node, execution state,
    deduplication cache, or endpoint-local executor handles. Action and Session request
    handling will be added after the Query vertical path is established.
    """

    __slots__ = (
        "_descriptor",
        "_endpoint_instance_id",
        "_implementations",
        "_operation_descriptors",
    )

    def __init__(
        self,
        descriptor: ToolEndpointDescriptor,
        *,
        endpoint_instance_id: str,
        operations: Mapping[
            str,
            QueryToolEndpoint | ActionToolEndpoint | SessionToolEndpoint,
        ],
    ) -> None:
        if not isinstance(descriptor, ToolEndpointDescriptor):
            raise TypeError("descriptor must be a ToolEndpointDescriptor")
        if descriptor.protocol_version != TOOL_ENDPOINT_PROTOCOL:
            raise ValueError(
                f"descriptor.protocol_version must equal {TOOL_ENDPOINT_PROTOCOL!r}"
            )
        if not isinstance(operations, Mapping):
            raise TypeError("operations must be a mapping")

        implementations: dict[str, object] = {}
        for operation_name, implementation in operations.items():
            if not isinstance(operation_name, str):
                raise TypeError("operation implementation names must be strings")
            implementations[operation_name] = implementation

        operation_descriptors = {
            operation.name: operation for operation in descriptor.operations
        }
        declared_names = set(operation_descriptors)
        implemented_names = set(implementations)
        missing = sorted(declared_names - implemented_names)
        unexpected = sorted(implemented_names - declared_names)
        if missing or unexpected:
            details: list[str] = []
            if missing:
                details.append(f"missing implementations: {', '.join(missing)}")
            if unexpected:
                details.append(f"undeclared implementations: {', '.join(unexpected)}")
            raise ValueError(
                "operation mapping does not match descriptor: " + "; ".join(details)
            )

        for operation_name, operation_descriptor in operation_descriptors.items():
            _validate_implementation(
                operation_name,
                operation_descriptor.semantics,
                implementations[operation_name],
            )

        self._descriptor = descriptor
        self._endpoint_instance_id = _validate_identifier(
            endpoint_instance_id,
            "endpoint_instance_id",
        )
        self._implementations = implementations
        self._operation_descriptors = operation_descriptors

    @property
    def descriptor(self) -> ToolEndpointDescriptor:
        """Return the immutable descriptor associated with this handler."""
        return self._descriptor

    @property
    def endpoint_instance_id(self) -> str:
        """Return the process-start identity accepted by this handler."""
        return self._endpoint_instance_id

    @property
    def operation_names(self) -> tuple[str, ...]:
        """Return bound operation names in descriptor order."""
        return tuple(operation.name for operation in self._descriptor.operations)

    async def handle_invoke(self, request: ToolEnvelope) -> ToolEnvelope:
        """Handle one Query invoke and return a completed, rejected, or error response."""
        if not isinstance(request, ToolEnvelope):
            raise TypeError("request must be a ToolEnvelope")
        if request.message_type != "tool.invoke.request":
            raise ValueError("request envelope must be tool.invoke.request")

        if request.endpoint_id != self._descriptor.endpoint_id:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_ROUTE_MISMATCH",
                (
                    f"request targets endpoint {request.endpoint_id!r}, expected "
                    f"{self._descriptor.endpoint_id!r}"
                ),
                path="endpoint_id",
            )
        if request.endpoint_instance_id != self._endpoint_instance_id:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_ROUTE_MISMATCH",
                (
                    "request targets endpoint instance "
                    f"{request.endpoint_instance_id!r}, expected "
                    f"{self._endpoint_instance_id!r}"
                ),
                path="endpoint_instance_id",
            )

        operation_name = cast(str, request.operation)
        operation_descriptor = self._operation_descriptors.get(operation_name)
        if operation_descriptor is None:
            raise ToolProtocolError(
                "FORGE_PROTOCOL_UNKNOWN_OPERATION",
                f"endpoint does not declare operation {operation_name!r}",
                path="operation",
            )
        if operation_descriptor.semantics != "query":
            raise NotImplementedError(
                "Query-first ToolEndpointHandler does not yet handle "
                f"{operation_descriptor.semantics} operation {operation_name!r}"
            )

        try:
            validate_message_envelope(request)
            endpoint_request, context = invoke_request_from_envelope(request)
        except ToolProtocolError as error:
            details = {"path": error.path} if error.path is not None else {}
            return make_error_response_envelope(
                ToolError(
                    code=error.code,
                    message=error.message,
                    details=details,
                ),
                request,
            )

        endpoint = cast(QueryToolEndpoint, self._implementations[operation_name])
        try:
            result = await endpoint.query(endpoint_request, context)
        except ToolEndpointError as error:
            return make_invoke_response_envelope(error.error, request)
        if not isinstance(result, ToolResult):
            raise TypeError("QueryToolEndpoint.query() must return a ToolResult")
        return make_invoke_response_envelope(result, request)
