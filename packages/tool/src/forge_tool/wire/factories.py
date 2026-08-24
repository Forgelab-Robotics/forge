"""Complete ToolEnvelope factories and paired-exchange validation."""

from __future__ import annotations

from typing import Any

from ..endpoint import (
    EndpointRegistryResponse,
    EndpointStatus,
    ToolAccepted,
    ToolContext,
    ToolControlCommand,
    ToolControlResponse,
    ToolEndpointDescriptor,
    ToolError,
    ToolEvent,
    ToolExecutionStatus,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
)
from .descriptor import endpoint_descriptor_to_payload
from .envelope import TOOL_ENDPOINT_PROTOCOL, ToolEnvelope, ToolMessageType
from .errors import ToolProtocolError
from .messages import (
    control_request_from_payload,
    control_request_to_payload,
    control_response_from_payload,
    control_response_to_payload,
    endpoint_registry_response_from_payload,
    endpoint_registry_response_to_payload,
    endpoint_status_to_payload,
    error_to_payload,
    event_to_payload,
    invoke_request_to_payload,
    invoke_response_to_payload,
    result_response_to_payload,
    status_response_to_payload,
    validate_message_envelope,
)


_REGISTRY_REQUEST_OPERATIONS = {
    "endpoint.register": "register",
    "endpoint.unregister": "unregister",
}


def _validated(envelope: ToolEnvelope) -> ToolEnvelope:
    validate_message_envelope(envelope)
    return envelope


def _execution_envelope(
    message_type: ToolMessageType,
    *,
    context: ToolContext,
    endpoint_instance_id: str | None,
    payload: dict[str, Any],
    request_id: str | None,
    sequence: int | None = None,
) -> ToolEnvelope:
    if not isinstance(context, ToolContext):
        raise TypeError("context must be a ToolContext")
    return _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type=message_type,
            request_id=request_id,
            invocation_id=context.invocation_id,
            attempt_id=context.attempt_id,
            endpoint_id=context.endpoint_id,
            endpoint_instance_id=endpoint_instance_id,
            operation=context.operation,
            sequence=sequence,
            payload=payload,
        )
    )


def make_invoke_request_envelope(
    request: ToolRequest,
    context: ToolContext,
    *,
    request_id: str,
    endpoint_instance_id: str | None,
) -> ToolEnvelope:
    """Construct an invoke request, optionally leaving instance resolution to Gateway."""
    return _execution_envelope(
        "tool.invoke.request",
        context=context,
        endpoint_instance_id=endpoint_instance_id,
        request_id=request_id,
        payload=invoke_request_to_payload(request, context),
    )


def _response_envelope(
    message_type: ToolMessageType,
    *,
    request: ToolEnvelope,
    payload: dict[str, Any],
) -> ToolEnvelope:
    if not isinstance(request, ToolEnvelope):
        raise TypeError("request must be a ToolEnvelope")
    expected_request_type = {
        "tool.invoke.response": "tool.invoke.request",
        "tool.status.response": "tool.status.request",
        "tool.result.response": "tool.result.request",
        "tool.control.response": "tool.control.request",
    }.get(message_type)
    if request.message_type != expected_request_type:
        raise ValueError(f"{message_type} requires a {expected_request_type} envelope")
    return _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type=message_type,
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            attempt_id=request.attempt_id,
            endpoint_id=request.endpoint_id,
            endpoint_instance_id=request.endpoint_instance_id,
            operation=request.operation,
            payload=payload,
        )
    )


def make_invoke_response_envelope(
    response: ToolResult | ToolAccepted | ToolError,
    request: ToolEnvelope,
) -> ToolEnvelope:
    """Construct an invoke response correlated to its request envelope."""
    return _response_envelope(
        "tool.invoke.response",
        request=request,
        payload=invoke_response_to_payload(response),
    )


def make_status_request_envelope(
    context: ToolContext,
    *,
    request_id: str,
    endpoint_instance_id: str,
) -> ToolEnvelope:
    """Construct a complete execution-status request."""
    return _execution_envelope(
        "tool.status.request",
        context=context,
        endpoint_instance_id=endpoint_instance_id,
        request_id=request_id,
        payload={},
    )


def make_status_response_envelope(
    status: ToolExecutionStatus,
    request: ToolEnvelope,
) -> ToolEnvelope:
    """Construct a status response correlated to its request envelope."""
    return _response_envelope(
        "tool.status.response",
        request=request,
        payload=status_response_to_payload(status),
    )


def make_result_request_envelope(
    context: ToolContext,
    *,
    request_id: str,
    endpoint_instance_id: str,
) -> ToolEnvelope:
    """Construct a complete terminal-result lookup request."""
    return _execution_envelope(
        "tool.result.request",
        context=context,
        endpoint_instance_id=endpoint_instance_id,
        request_id=request_id,
        payload={},
    )


def make_result_response_envelope(
    response: ToolResultResponse,
    request: ToolEnvelope,
) -> ToolEnvelope:
    """Construct a result response correlated to its request envelope."""
    return _response_envelope(
        "tool.result.response",
        request=request,
        payload=result_response_to_payload(response),
    )


def make_control_request_envelope(
    command: ToolControlCommand,
    context: ToolContext,
    *,
    request_id: str,
    endpoint_instance_id: str,
    reason: str | None = None,
) -> ToolEnvelope:
    """Construct a complete cancel or stop request."""
    return _execution_envelope(
        "tool.control.request",
        context=context,
        endpoint_instance_id=endpoint_instance_id,
        request_id=request_id,
        payload=control_request_to_payload(command, reason),
    )


def make_control_response_envelope(
    response: ToolControlResponse,
    request: ToolEnvelope,
) -> ToolEnvelope:
    """Construct a control response correlated to its request envelope."""
    return _response_envelope(
        "tool.control.response",
        request=request,
        payload=control_response_to_payload(response),
    )


def make_event_envelope(
    event: ToolEvent,
    context: ToolContext,
    *,
    endpoint_instance_id: str,
    sequence: int,
) -> ToolEnvelope:
    """Construct a complete attempt-scoped executor event."""
    return _execution_envelope(
        "tool.event",
        context=context,
        endpoint_instance_id=endpoint_instance_id,
        request_id=None,
        sequence=sequence,
        payload=event_to_payload(event),
    )


def make_error_envelope(
    error: ToolError,
    context: ToolContext,
    *,
    request_id: str,
    endpoint_instance_id: str,
) -> ToolEnvelope:
    """Construct an execution error when a complete ToolContext is available."""
    return _execution_envelope(
        "tool.error",
        context=context,
        endpoint_instance_id=endpoint_instance_id,
        request_id=request_id,
        payload=error_to_payload(error),
    )


def make_error_response_envelope(
    error: ToolError,
    request: ToolEnvelope,
) -> ToolEnvelope:
    """Construct a correlated error from an execution request's route identity."""
    if request.message_type not in {
        "tool.invoke.request",
        "tool.status.request",
        "tool.result.request",
        "tool.control.request",
    }:
        raise ValueError("request envelope has no paired error response")
    return _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type="tool.error",
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            attempt_id=request.attempt_id,
            endpoint_id=request.endpoint_id,
            endpoint_instance_id=request.endpoint_instance_id,
            operation=request.operation,
            payload=error_to_payload(error),
        )
    )


def make_registration_envelope(
    descriptor: ToolEndpointDescriptor,
    *,
    endpoint_instance_id: str,
    request_id: str,
) -> ToolEnvelope:
    """Construct an idempotent endpoint announce/upsert/lease-renewal message."""
    if not isinstance(descriptor, ToolEndpointDescriptor):
        raise TypeError("descriptor must be a ToolEndpointDescriptor")
    return _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type="endpoint.register",
            request_id=request_id,
            endpoint_id=descriptor.endpoint_id,
            endpoint_instance_id=endpoint_instance_id,
            payload=endpoint_descriptor_to_payload(descriptor),
        )
    )


def make_unregister_envelope(
    *,
    endpoint_id: str,
    endpoint_instance_id: str,
    request_id: str,
) -> ToolEnvelope:
    """Construct a complete endpoint unregister message."""
    return _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type="endpoint.unregister",
            request_id=request_id,
            endpoint_id=endpoint_id,
            endpoint_instance_id=endpoint_instance_id,
            payload={},
        )
    )


def make_endpoint_registry_response_envelope(
    response: EndpointRegistryResponse,
    request: ToolEnvelope,
) -> ToolEnvelope:
    """Construct a Registry response correlated to its management request."""
    if not isinstance(response, EndpointRegistryResponse):
        raise TypeError("response must be an EndpointRegistryResponse")
    if not isinstance(request, ToolEnvelope):
        raise TypeError("request must be a ToolEnvelope")
    expected_operation = _REGISTRY_REQUEST_OPERATIONS.get(request.message_type)
    if expected_operation is None:
        raise ValueError("request envelope has no paired Registry response")
    if response.operation != expected_operation:
        raise ValueError(
            f"{request.message_type} requires Registry operation {expected_operation!r}"
        )
    envelope = _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type="endpoint.registry.response",
            request_id=request.request_id,
            endpoint_id=request.endpoint_id,
            endpoint_instance_id=request.endpoint_instance_id,
            payload=endpoint_registry_response_to_payload(response),
        )
    )
    validate_management_response_correlation(request, envelope)
    return envelope


def make_endpoint_status_envelope(
    status: EndpointStatus,
    *,
    endpoint_instance_id: str,
) -> ToolEnvelope:
    """Construct a complete endpoint-status message without identity duplication."""
    if not isinstance(status, EndpointStatus):
        raise TypeError("status must be an EndpointStatus")
    return _validated(
        ToolEnvelope(
            protocol=TOOL_ENDPOINT_PROTOCOL,
            message_type="endpoint.status",
            endpoint_id=status.endpoint_id,
            endpoint_instance_id=endpoint_instance_id,
            payload=endpoint_status_to_payload(status),
        )
    )


def _correlation_error(field_name: str) -> ToolProtocolError:
    return ToolProtocolError(
        "FORGE_PROTOCOL_CORRELATION_MISMATCH",
        "response does not match request",
        path=field_name,
    )


def validate_management_response_correlation(
    request: ToolEnvelope,
    response: ToolEnvelope,
) -> None:
    """Validate a Registry response against its originating management request."""
    if not isinstance(request, ToolEnvelope):
        raise TypeError("request must be a ToolEnvelope")
    if not isinstance(response, ToolEnvelope):
        raise TypeError("response must be a ToolEnvelope")
    expected_operation = _REGISTRY_REQUEST_OPERATIONS.get(request.message_type)
    if expected_operation is None:
        raise ValueError("request envelope has no paired Registry response type")
    if response.message_type != "endpoint.registry.response":
        raise _correlation_error("message_type")
    for field_name in ("request_id", "endpoint_id", "endpoint_instance_id"):
        if getattr(request, field_name) != getattr(response, field_name):
            raise _correlation_error(field_name)
    response_operation = endpoint_registry_response_from_payload(
        response.payload
    ).operation
    if response_operation != expected_operation:
        raise _correlation_error("payload.operation")


def validate_response_correlation(
    request: ToolEnvelope,
    response: ToolEnvelope,
) -> None:
    """Validate one response against its originating execution request."""
    pairs = {
        "tool.invoke.request": "tool.invoke.response",
        "tool.status.request": "tool.status.response",
        "tool.result.request": "tool.result.response",
        "tool.control.request": "tool.control.response",
    }
    expected = pairs.get(request.message_type)
    if expected is None:
        raise ValueError("request envelope has no paired response type")
    if response.message_type not in (expected, "tool.error"):
        raise _correlation_error("message_type")
    for field_name in (
        "request_id",
        "invocation_id",
        "attempt_id",
        "endpoint_id",
        "endpoint_instance_id",
        "operation",
    ):
        if getattr(request, field_name) != getattr(response, field_name):
            raise _correlation_error(field_name)
    if (
        request.message_type == "tool.control.request"
        and response.message_type == expected
    ):
        request_command, _ = control_request_from_payload(request.payload)
        response_command = control_response_from_payload(response.payload).command
        if request_command != response_command:
            raise _correlation_error("payload.response.command")
