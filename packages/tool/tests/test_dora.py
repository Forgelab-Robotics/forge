from __future__ import annotations

import asyncio

import pyarrow as pa
import pytest
from forge_msgs import ToolMessage
from forge_msgs.tool import TOOL_MESSAGE_SCHEMA

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolContext,
    ToolEndpointDescriptor,
    ToolEndpointHandler,
    ToolEvent,
    ToolExecutionKey,
    ToolOperationDescriptor,
    ToolRequest,
    ToolResult,
    error_from_payload,
    invoke_response_from_payload,
    make_event_envelope,
    make_heartbeat_envelope,
    make_invoke_request_envelope,
    validate_response_correlation,
)
from forge_tool.dora import (
    DoraToolEndpointBinding,
    tool_envelope_to_message,
    tool_message_to_envelope,
)


class FakeQuery:
    def __init__(self) -> None:
        self.calls = 0

    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        self.calls += 1
        return ToolResult(
            status="succeeded",
            outputs={"arguments": dict(request.arguments)},
        )


def _context() -> ToolContext:
    return ToolContext(
        execution_key=ToolExecutionKey(
            invocation_id="invocation-1",
            attempt_id="attempt-1",
        ),
        tool_id="forge.tool.detect",
        implementation_id="yolo",
        endpoint_id="vision.yolo",
        operation="detect",
    )


def _request():
    return make_invoke_request_envelope(
        ToolRequest(arguments={"class": "cube"}),
        _context(),
        request_id="request-1",
        endpoint_instance_id="instance-1",
    )


def _handler(query: FakeQuery | None = None) -> ToolEndpointHandler:
    return ToolEndpointHandler(
        ToolEndpointDescriptor(
            protocol_version=TOOL_ENDPOINT_PROTOCOL,
            endpoint_id="vision.yolo",
            operations=(ToolOperationDescriptor(name="detect", semantics="query"),),
        ),
        endpoint_instance_id="instance-1",
        operations={"detect": query or FakeQuery()},
    )


@pytest.mark.parametrize(
    "envelope",
    [
        _request(),
        make_event_envelope(
            ToolEvent(type="progress", data={"fraction": 0.5}),
            _context(),
            endpoint_instance_id="instance-1",
            sequence=0,
        ),
        make_heartbeat_envelope(
            endpoint_id="vision.yolo",
            endpoint_instance_id="instance-1",
            request_id="heartbeat-1",
        ),
    ],
)
def test_tool_message_and_envelope_conversion_round_trip(envelope: object) -> None:
    message = tool_envelope_to_message(envelope)  # type: ignore[arg-type]

    assert isinstance(message, ToolMessage)
    assert tool_message_to_envelope(message) == envelope


def test_dora_binding_handles_one_query_record_batch() -> None:
    query = FakeQuery()
    binding = DoraToolEndpointBinding(_handler(query))
    request = _request()
    input_value = tool_envelope_to_message(request).to_arrow()

    output_value = asyncio.run(binding.handle_input(input_value))

    assert output_value.schema.equals(TOOL_MESSAGE_SCHEMA, check_metadata=False)
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))
    validate_response_correlation(request, response)
    assert invoke_response_from_payload(response.payload) == ToolResult(
        status="succeeded",
        outputs={"arguments": {"class": "cube"}},
    )
    assert query.calls == 1


def test_dora_binding_accepts_a_single_batch_table() -> None:
    binding = DoraToolEndpointBinding(_handler())
    request = _request()
    batch = tool_envelope_to_message(request).to_arrow()

    output_value = asyncio.run(binding.handle_input(pa.Table.from_batches([batch])))

    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))
    validate_response_correlation(request, response)


def test_dora_binding_returns_a_correlated_error_for_invalid_typed_payload() -> None:
    query = FakeQuery()
    binding = DoraToolEndpointBinding(_handler(query))
    message = ToolMessage.from_payload(
        message_type="tool.invoke.request",
        request_id="request-1",
        invocation_id="invocation-1",
        attempt_id="attempt-1",
        endpoint_id="vision.yolo",
        endpoint_instance_id="instance-1",
        operation="detect",
        payload={},
    )

    request = tool_message_to_envelope(message)
    output_value = asyncio.run(binding.handle_input(message.to_arrow()))
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))

    validate_response_correlation(request, response)
    assert response.message_type == "tool.error"
    error = error_from_payload(response.payload)
    assert error.code == "FORGE_PROTOCOL_INVALID_PAYLOAD"
    assert error.retryable is False
    assert query.calls == 0


def test_dora_binding_rejects_a_non_handler() -> None:
    with pytest.raises(TypeError, match="ToolEndpointHandler"):
        DoraToolEndpointBinding(object())  # type: ignore[arg-type]


def test_conversion_rejects_the_wrong_model_type() -> None:
    with pytest.raises(TypeError, match="ToolMessage"):
        tool_message_to_envelope(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ToolEnvelope"):
        tool_envelope_to_message(object())  # type: ignore[arg-type]
