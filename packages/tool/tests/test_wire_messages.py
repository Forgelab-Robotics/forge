from __future__ import annotations

import pytest

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    EndpointStatus,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEnvelope,
    ToolError,
    ToolEvent,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolProtocolError,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
    control_request_from_payload,
    control_request_to_payload,
    control_response_from_payload,
    control_response_to_payload,
    decode_envelope,
    encode_envelope,
    endpoint_status_from_envelope,
    endpoint_status_to_payload,
    error_from_payload,
    error_to_payload,
    event_from_payload,
    event_to_payload,
    invoke_request_from_envelope,
    invoke_request_to_payload,
    invoke_response_from_payload,
    invoke_response_to_payload,
    result_response_from_payload,
    result_response_to_payload,
    status_response_from_payload,
    status_response_to_payload,
)


def _key() -> ToolExecutionKey:
    return ToolExecutionKey(invocation_id="invocation-1", attempt_id="attempt-1")


def _context() -> ToolContext:
    return ToolContext(
        execution_key=_key(),
        tool_id="forge.tool.detect",
        implementation_id="yolo",
        endpoint_id="vision.yolo",
        operation="detect",
        caller_id="test-client",
        deadline_ms=1_800_000_000_000,
        metadata={"trace_id": "trace-1"},
    )


def _envelope(message_type: str, payload: dict[str, object]) -> ToolEnvelope:
    return ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type=message_type,  # type: ignore[arg-type]
        request_id=None if message_type == "tool.event" else "request-1",
        invocation_id="invocation-1",
        attempt_id="attempt-1",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        operation="detect",
        sequence=0 if message_type == "tool.event" else None,
        payload=payload,
    )


def test_invoke_request_round_trip_combines_envelope_and_context_identity() -> None:
    request = ToolRequest(arguments={"class": "cube"})
    envelope = _envelope(
        "tool.invoke.request",
        invoke_request_to_payload(request, _context()),
    )

    decoded = decode_envelope(encode_envelope(envelope))
    decoded_request, decoded_context = invoke_request_from_envelope(decoded)

    assert decoded_request == request
    assert decoded_context == _context()
    assert "invocation_id" not in decoded.payload["context"]
    assert "attempt_id" not in decoded.payload["context"]


@pytest.mark.parametrize(
    "response",
    [
        ToolResult(status="succeeded", outputs={"objects": []}),
        ToolAccepted(details={"queue": "default"}),
        ToolError(code="ENDPOINT_BUSY", message="busy", retryable=True),
    ],
)
def test_invoke_response_round_trip(
    response: ToolResult | ToolAccepted | ToolError,
) -> None:
    payload = invoke_response_to_payload(response)
    envelope = _envelope("tool.invoke.response", payload)

    decoded = decode_envelope(encode_envelope(envelope))

    assert invoke_response_from_payload(decoded.payload) == response


def test_status_and_result_response_round_trip() -> None:
    status = ToolExecutionStatus(phase="running", details={"progress": 0.5})
    result = ToolResultResponse(
        status="available",
        result=ToolResult(status="succeeded", outputs={"done": True}),
    )

    status_envelope = _envelope(
        "tool.status.response",
        status_response_to_payload(status),
    )
    result_envelope = _envelope(
        "tool.result.response",
        result_response_to_payload(result),
    )

    decoded_status = decode_envelope(encode_envelope(status_envelope))
    decoded_result = decode_envelope(encode_envelope(result_envelope))
    assert status_response_from_payload(decoded_status.payload) == status
    assert result_response_from_payload(decoded_result.payload) == result


def test_control_request_and_response_round_trip() -> None:
    request_payload = control_request_to_payload("cancel", "operator request")
    response = ToolControlResponse(command="cancel", status="accepted")
    response_payload = control_response_to_payload(response)

    request_envelope = _envelope("tool.control.request", request_payload)
    response_envelope = _envelope("tool.control.response", response_payload)

    decoded_request = decode_envelope(encode_envelope(request_envelope))
    decoded_response = decode_envelope(encode_envelope(response_envelope))
    assert control_request_from_payload(decoded_request.payload) == (
        "cancel",
        "operator request",
    )
    assert control_response_from_payload(decoded_response.payload) == response


def test_event_and_error_round_trip() -> None:
    event = ToolEvent(type="progress", data={"fraction": 0.25})
    error = ToolError(
        code="TRANSPORT_FAILED", message="connection lost", retryable=True
    )

    event_envelope = _envelope("tool.event", event_to_payload(event))
    error_envelope = _envelope("tool.error", error_to_payload(error))

    decoded_event = decode_envelope(encode_envelope(event_envelope))
    decoded_error = decode_envelope(encode_envelope(error_envelope))
    assert event_from_payload(decoded_event.payload) == event
    assert error_from_payload(decoded_error.payload) == error


def test_endpoint_status_round_trip_uses_envelope_endpoint_identity() -> None:
    status = EndpointStatus(
        endpoint_id="vision.yolo",
        state="busy",
        active_invocations=2,
        details={"queue_depth": 1},
    )
    envelope = ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type="endpoint.status",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        payload=endpoint_status_to_payload(status),
    )

    decoded = decode_envelope(encode_envelope(envelope))

    assert endpoint_status_from_envelope(decoded) == status


@pytest.mark.parametrize(
    ("message_type", "payload", "match"),
    [
        ("tool.invoke.request", {"arguments": {}}, "missing fields"),
        ("tool.invoke.response", {"outcome": "unknown"}, "outcome"),
        ("tool.status.request", {"unexpected": True}, "unknown fields"),
        (
            "tool.result.response",
            {"status": "available", "result": {"status": "succeeded"}},
            "missing fields",
        ),
        ("tool.control.request", {"command": "pause"}, "cancel or stop"),
        ("tool.control.response", {"response": {}}, "missing fields"),
        ("tool.event", {"type": "progress"}, "missing fields"),
        ("tool.error", {"error": {"code": "X"}}, "missing fields"),
    ],
)
def test_codec_boundary_rejects_invalid_message_payloads(
    message_type: str,
    payload: dict[str, object],
    match: str,
) -> None:
    envelope = _envelope(message_type, payload)

    with pytest.raises(ToolProtocolError, match=match):
        encode_envelope(envelope)


@pytest.mark.parametrize("status", ["pending", "not_found"])
def test_result_response_without_terminal_result_round_trips(status: str) -> None:
    response = ToolResultResponse(status=status)  # type: ignore[arg-type]
    envelope = _envelope(
        "tool.result.response",
        result_response_to_payload(response),
    )

    decoded = decode_envelope(encode_envelope(envelope))

    assert result_response_from_payload(decoded.payload) == response


def test_raw_payload_adapters_reject_unbounded_json_values() -> None:
    with pytest.raises(ToolProtocolError, match="finite"):
        result_response_from_payload(
            {
                "status": "available",
                "result": {
                    "status": "succeeded",
                    "outputs": {"value": float("nan")},
                },
            }
        )


def test_empty_request_and_management_payloads_are_strict() -> None:
    for message_type in ("tool.status.request", "tool.result.request"):
        envelope = _envelope(message_type, {})
        assert decode_envelope(encode_envelope(envelope)) == envelope

    heartbeat = ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type="endpoint.heartbeat",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        payload={},
    )
    assert decode_envelope(encode_envelope(heartbeat)) == heartbeat

    invalid = ToolEnvelope(
        protocol=TOOL_ENDPOINT_PROTOCOL,
        message_type="endpoint.heartbeat",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        payload={"unexpected": True},
    )
    with pytest.raises(ToolProtocolError, match="unknown fields"):
        encode_envelope(invalid)
