from __future__ import annotations

from dataclasses import replace

import pytest

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    EndpointRegistryResponse,
    EndpointStatus,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEndpointDescriptor,
    ToolEnvelope,
    ToolError,
    ToolEvent,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolOperationDescriptor,
    ToolProtocolError,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
    make_control_request_envelope,
    make_control_response_envelope,
    make_endpoint_registry_response_envelope,
    make_endpoint_status_envelope,
    make_error_envelope,
    make_error_response_envelope,
    make_event_envelope,
    make_invoke_request_envelope,
    make_invoke_response_envelope,
    make_registration_envelope,
    make_result_request_envelope,
    make_result_response_envelope,
    make_status_request_envelope,
    make_status_response_envelope,
    make_unregister_envelope,
    validate_management_response_correlation,
    validate_response_correlation,
)


def _context(attempt_id: str = "attempt-1") -> ToolContext:
    return ToolContext(
        execution_key=ToolExecutionKey(
            invocation_id="invocation-1",
            attempt_id=attempt_id,
        ),
        tool_id="forge.tool.detect",
        implementation_id="yolo",
        endpoint_id="vision.yolo",
        operation="detect",
        metadata={},
    )


def test_invoke_factory_derives_all_execution_identity_from_context() -> None:
    envelope = make_invoke_request_envelope(
        ToolRequest(arguments={"class": "cube"}),
        _context(),
        request_id="request-1",
        endpoint_instance_id="instance-1",
    )

    assert envelope.invocation_id == "invocation-1"
    assert envelope.attempt_id == "attempt-1"
    assert envelope.endpoint_id == "vision.yolo"
    assert envelope.operation == "detect"
    assert "invocation_id" not in envelope.payload["context"]


def test_unresolved_invoke_response_and_error_preserve_none_correlation() -> None:
    request = make_invoke_request_envelope(
        ToolRequest(arguments={}),
        _context(),
        request_id="request-1",
        endpoint_instance_id=None,
    )
    response = make_invoke_response_envelope(ToolAccepted(), request)
    error = make_error_response_envelope(
        ToolError(code="GATEWAY_RESOLUTION_FAILED", message="no provider available"),
        request,
    )

    assert request.endpoint_instance_id is None
    assert response.endpoint_instance_id is None
    assert error.endpoint_instance_id is None
    validate_response_correlation(request, response)
    validate_response_correlation(request, error)

    with pytest.raises(ToolProtocolError) as captured:
        validate_response_correlation(
            request,
            replace(response, endpoint_instance_id="instance-1"),
        )
    assert captured.value.path == "endpoint_instance_id"


def test_request_response_factories_preserve_correlation() -> None:
    context = _context()
    invoke_request = make_invoke_request_envelope(
        ToolRequest(arguments={}),
        context,
        request_id="invoke-1",
        endpoint_instance_id="instance-1",
    )
    status_request = make_status_request_envelope(
        context,
        request_id="status-1",
        endpoint_instance_id="instance-1",
    )
    result_request = make_result_request_envelope(
        context,
        request_id="result-1",
        endpoint_instance_id="instance-1",
    )
    control_request = make_control_request_envelope(
        "cancel",
        context,
        request_id="control-1",
        endpoint_instance_id="instance-1",
    )
    cases = [
        (
            invoke_request,
            make_invoke_response_envelope(ToolAccepted(), invoke_request),
        ),
        (
            status_request,
            make_status_response_envelope(
                ToolExecutionStatus(phase="running"), status_request
            ),
        ),
        (
            result_request,
            make_result_response_envelope(
                ToolResultResponse(
                    status="available",
                    result=ToolResult(status="succeeded"),
                ),
                result_request,
            ),
        ),
        (
            control_request,
            make_control_response_envelope(
                ToolControlResponse(command="cancel", status="accepted"),
                control_request,
            ),
        ),
    ]

    for request, response in cases:
        validate_response_correlation(request, response)


def test_correlation_rejects_retargeted_attempt_and_control_command() -> None:
    request = make_control_request_envelope(
        "cancel",
        _context(),
        request_id="control-1",
        endpoint_instance_id="instance-1",
    )
    response = make_control_response_envelope(
        ToolControlResponse(command="cancel", status="accepted"),
        request,
    )
    wrong_attempt = replace(response, attempt_id="attempt-2")
    wrong_command = make_control_response_envelope(
        ToolControlResponse(command="stop", status="accepted"),
        request,
    )

    with pytest.raises(ToolProtocolError) as attempt_error:
        validate_response_correlation(request, wrong_attempt)
    assert attempt_error.value.path == "attempt_id"

    with pytest.raises(ToolProtocolError) as command_error:
        validate_response_correlation(request, wrong_command)
    assert command_error.value.path == "payload.response.command"


def test_response_factory_rejects_the_wrong_request_type() -> None:
    invoke_request = make_invoke_request_envelope(
        ToolRequest(arguments={}),
        _context(),
        request_id="invoke-1",
        endpoint_instance_id="instance-1",
    )

    with pytest.raises(ValueError, match="tool.status.request"):
        make_status_response_envelope(
            ToolExecutionStatus(phase="running"), invoke_request
        )


def test_event_error_and_management_factories_are_complete() -> None:
    context = _context()
    event = make_event_envelope(
        ToolEvent(type="progress", data={"fraction": 0.5}),
        context,
        endpoint_instance_id="instance-1",
        sequence=0,
    )
    error = make_error_envelope(
        ToolError(code="TRANSPORT_FAILED", message="lost", retryable=True),
        context,
        request_id="request-1",
        endpoint_instance_id="instance-1",
    )
    unregister = make_unregister_envelope(
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        request_id="unregister-1",
    )
    endpoint_status = make_endpoint_status_envelope(
        EndpointStatus(endpoint_id="vision.yolo", state="ready"),
        endpoint_instance_id="instance-1",
    )
    registration = make_registration_envelope(
        ToolEndpointDescriptor(
            protocol_version=TOOL_ENDPOINT_PROTOCOL,
            endpoint_id="vision.yolo",
            operations=(ToolOperationDescriptor(name="detect", semantics="query"),),
        ),
        endpoint_instance_id="instance-1",
        request_id="register-1",
    )

    assert event.sequence == 0
    assert error.request_id == "request-1"
    assert unregister.request_id == "unregister-1"
    assert endpoint_status.request_id is None
    assert registration.message_type == "endpoint.register"
    assert registration.request_id == "register-1"


def test_registry_response_factory_copies_request_identity_and_correlates_operation() -> (
    None
):
    registration = make_registration_envelope(
        ToolEndpointDescriptor(
            protocol_version=TOOL_ENDPOINT_PROTOCOL,
            endpoint_id="vision.yolo",
            operations=(ToolOperationDescriptor(name="detect", semantics="query"),),
        ),
        endpoint_instance_id="instance-1",
        request_id="register-1",
    )
    unregister = make_unregister_envelope(
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        request_id="unregister-1",
    )
    cases = [
        (
            registration,
            EndpointRegistryResponse(
                operation="register",
                status="accepted",
                registry_revision=7,
                lease_ttl_ms=30_000,
            ),
        ),
        (
            unregister,
            EndpointRegistryResponse(
                operation="unregister",
                status="accepted",
                registry_revision=9,
            ),
        ),
    ]

    for request, registry_response in cases:
        response = make_endpoint_registry_response_envelope(
            registry_response,
            request,
        )

        validate_management_response_correlation(request, response)
        assert response.message_type == "endpoint.registry.response"
        assert response.request_id == request.request_id
        assert response.endpoint_id == request.endpoint_id
        assert response.endpoint_instance_id == request.endpoint_instance_id


def test_registry_response_correlation_rejects_retargeting_and_wrong_operation() -> (
    None
):
    request = make_unregister_envelope(
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        request_id="unregister-1",
    )
    response = make_endpoint_registry_response_envelope(
        EndpointRegistryResponse(
            operation="unregister",
            status="accepted",
            registry_revision=8,
        ),
        request,
    )

    with pytest.raises(ToolProtocolError) as identity_error:
        validate_management_response_correlation(
            request,
            replace(response, endpoint_instance_id="instance-2"),
        )
    assert identity_error.value.path == "endpoint_instance_id"

    wrong_operation = replace(
        response,
        payload={
            "operation": "register",
            "status": "accepted",
            "registry_revision": 8,
            "lease_ttl_ms": 30_000,
        },
    )
    with pytest.raises(ToolProtocolError) as operation_error:
        validate_management_response_correlation(request, wrong_operation)
    assert operation_error.value.path == "payload.operation"

    with pytest.raises(ValueError, match="operation 'unregister'"):
        make_endpoint_registry_response_envelope(
            EndpointRegistryResponse(
                operation="register",
                status="accepted",
                registry_revision=8,
                lease_ttl_ms=30_000,
            ),
            request,
        )


def test_error_response_factory_uses_request_route_without_typed_context() -> None:
    request = ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type="tool.invoke.request",
        request_id="request-1",
        invocation_id="invocation-1",
        attempt_id="attempt-1",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        operation="detect",
        payload={},
    )

    response = make_error_response_envelope(
        ToolError(code="FORGE_PROTOCOL_INVALID_PAYLOAD", message="invalid invoke"),
        request,
    )

    validate_response_correlation(request, response)
    assert response.request_id == request.request_id
    assert response.invocation_id == request.invocation_id
    assert response.endpoint_instance_id == request.endpoint_instance_id
