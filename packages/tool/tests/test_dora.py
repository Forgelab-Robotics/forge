from __future__ import annotations

import asyncio
import json
from typing import cast

import pyarrow as pa
import pytest
from forge_msgs import ToolMessage
from forge_msgs.tool import TOOL_MESSAGE_SCHEMA

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEndpointDescriptor,
    ToolEndpointHandler,
    ToolEnvelope,
    ToolEvent,
    ToolEventEmitter,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolOperationDescriptor,
    ToolProtocolError,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
    encode_envelope,
    error_from_payload,
    event_from_payload,
    invoke_response_from_payload,
    make_event_envelope,
    make_invoke_request_envelope,
    validate_response_correlation,
)
from forge_tool.dora import (
    DoraToolEndpointBinding,
    tool_envelope_to_message,
    tool_message_to_envelope,
)


class OversizedQuery:
    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        return ToolResult(status="succeeded", outputs={"text": "x" * 2_048})


class RaisingQuery:
    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        raise RuntimeError("endpoint bug")


class InvalidResponseHandler(ToolEndpointHandler):
    async def handle_invoke(self, request: ToolEnvelope) -> ToolEnvelope:
        return ToolEnvelope(
            protocol=request.protocol,
            message_type="tool.invoke.response",
            request_id=request.request_id,
            invocation_id=request.invocation_id,
            attempt_id=request.attempt_id,
            endpoint_id=request.endpoint_id,
            endpoint_instance_id=request.endpoint_instance_id,
            operation=request.operation,
            payload={"x" * 5_000: True},
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


class DoraAction:
    def __init__(self, *, emit_early: bool = False) -> None:
        self.emit_early = emit_early
        self.emitter: ToolEventEmitter | None = None
        self.start_calls = 0

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        self.start_calls += 1
        self.emitter = events
        if self.emit_early:
            await events.emit(ToolEvent(type="progress", data={"fraction": 0.5}))
        return ToolAccepted()

    async def cancel(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        return ToolControlResponse(command="cancel", status="accepted")

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return ToolExecutionStatus(phase="running")

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        return ToolResultResponse(status="pending")


class DoraSession:
    def __init__(self, *, emit_early: bool = False) -> None:
        self.emit_early = emit_early
        self.emitter: ToolEventEmitter | None = None
        self.start_calls = 0

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        self.start_calls += 1
        self.emitter = events
        if self.emit_early:
            await events.emit(ToolEvent(type="progress", data={"fraction": 0.5}))
        return ToolAccepted()

    async def stop(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        return ToolControlResponse(command="stop", status="accepted")

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return ToolExecutionStatus(phase="running")

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        return ToolResultResponse(status="pending")


def _ipc_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


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


def _handler(query: object | None = None) -> ToolEndpointHandler:
    return ToolEndpointHandler(
        ToolEndpointDescriptor(
            protocol_version=TOOL_ENDPOINT_PROTOCOL,
            endpoint_id="vision.yolo",
            operations=(ToolOperationDescriptor(name="detect", semantics="query"),),
        ),
        endpoint_instance_id="instance-1",
        operations={"detect": query or FakeQuery()},  # type: ignore[dict-item]
    )


def _action_context() -> ToolContext:
    return ToolContext(
        execution_key=ToolExecutionKey("action-invocation-1", "attempt-1"),
        tool_id="forge.tool.move",
        implementation_id="arm",
        endpoint_id="motion.arm",
        operation="move",
    )


def _action_request() -> ToolEnvelope:
    return make_invoke_request_envelope(
        ToolRequest(arguments={"target": "home"}),
        _action_context(),
        request_id="action-request-1",
        endpoint_instance_id="instance-1",
    )


def _action_handler(action: DoraAction) -> ToolEndpointHandler:
    return ToolEndpointHandler(
        ToolEndpointDescriptor(
            protocol_version=TOOL_ENDPOINT_PROTOCOL,
            endpoint_id="motion.arm",
            operations=(
                ToolOperationDescriptor(
                    name="move",
                    semantics="action",
                    cancellable=True,
                    status_supported=True,
                ),
            ),
        ),
        endpoint_instance_id="instance-1",
        operations={"move": action},
    )


def _session_context() -> ToolContext:
    return ToolContext(
        execution_key=ToolExecutionKey("session-invocation-1", "attempt-1"),
        tool_id="forge.tool.policy",
        implementation_id="policy",
        endpoint_id="policy.runner",
        operation="serve",
    )


def _session_request() -> ToolEnvelope:
    return make_invoke_request_envelope(
        ToolRequest(arguments={}),
        _session_context(),
        request_id="session-request-1",
        endpoint_instance_id="instance-1",
    )


def _session_handler(session: DoraSession) -> ToolEndpointHandler:
    return ToolEndpointHandler(
        ToolEndpointDescriptor(
            protocol_version=TOOL_ENDPOINT_PROTOCOL,
            endpoint_id="policy.runner",
            operations=(
                ToolOperationDescriptor(
                    name="serve",
                    semantics="session",
                    stoppable=True,
                    status_supported=True,
                ),
            ),
        ),
        endpoint_instance_id="instance-1",
        operations={"serve": session},
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
        make_invoke_request_envelope(
            ToolRequest(arguments={}),
            _context(),
            request_id="unresolved-1",
            endpoint_instance_id=None,
        ),
    ],
)
def test_tool_message_and_envelope_conversion_round_trip(envelope: object) -> None:
    message = tool_envelope_to_message(envelope)  # type: ignore[arg-type]

    assert isinstance(message, ToolMessage)
    assert tool_message_to_envelope(message) == envelope


def test_dora_binding_rejects_ipc_bytes_for_bounded_upstream_decode() -> None:
    binding = DoraToolEndpointBinding(_handler())
    value = _ipc_bytes(tool_envelope_to_message(_request()).to_arrow())

    with pytest.raises(TypeError, match="does not accept IPC bytes"):
        asyncio.run(binding.handle_input(value))  # type: ignore[arg-type]


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


def test_dora_dispatch_returns_accepted_before_early_action_event() -> None:
    action = DoraAction(emit_early=True)
    published: list[pa.RecordBatch] = []

    async def publish(batch: pa.RecordBatch) -> None:
        published.append(batch)

    binding = DoraToolEndpointBinding(_action_handler(action), event_sink=publish)
    request = _action_request()

    outputs = asyncio.run(
        binding.dispatch_input(tool_envelope_to_message(request).to_arrow())
    )
    messages = [
        tool_message_to_envelope(ToolMessage.from_arrow(output)) for output in published
    ]

    assert outputs == ()
    assert [message.message_type for message in messages] == [
        "tool.invoke.response",
        "tool.event",
    ]
    assert isinstance(invoke_response_from_payload(messages[0].payload), ToolAccepted)
    assert event_from_payload(messages[1].payload) == ToolEvent(
        type="progress",
        data={"fraction": 0.5},
    )
    assert messages[1].sequence == 0


def test_dora_dispatch_returns_accepted_before_early_session_event() -> None:
    session = DoraSession(emit_early=True)
    published: list[pa.RecordBatch] = []

    async def publish(batch: pa.RecordBatch) -> None:
        published.append(batch)

    binding = DoraToolEndpointBinding(_session_handler(session), event_sink=publish)
    request = _session_request()

    outputs = asyncio.run(
        binding.dispatch_input(tool_envelope_to_message(request).to_arrow())
    )
    messages = [
        tool_message_to_envelope(ToolMessage.from_arrow(output)) for output in published
    ]

    assert outputs == ()
    assert [message.message_type for message in messages] == [
        "tool.invoke.response",
        "tool.event",
    ]
    assert isinstance(invoke_response_from_payload(messages[0].payload), ToolAccepted)
    assert event_from_payload(messages[1].payload) == ToolEvent(
        type="progress",
        data={"fraction": 0.5},
    )
    assert messages[1].sequence == 0


def test_dora_async_event_sink_receives_late_action_events() -> None:
    action = DoraAction()
    received: list[pa.RecordBatch] = []

    async def scenario() -> tuple[pa.RecordBatch, ...]:
        async def event_sink(value: pa.RecordBatch) -> None:
            received.append(value)

        binding = DoraToolEndpointBinding(
            _action_handler(action),
            event_sink=event_sink,
        )
        outputs = await binding.dispatch_input(
            tool_envelope_to_message(_action_request()).to_arrow()
        )
        assert action.emitter is not None
        await action.emitter.emit(ToolEvent(type="heartbeat"))
        return outputs

    outputs = asyncio.run(scenario())

    assert outputs == ()
    assert len(received) == 2
    accepted = tool_message_to_envelope(ToolMessage.from_arrow(received[0]))
    assert accepted.message_type == "tool.invoke.response"
    event = tool_message_to_envelope(ToolMessage.from_arrow(received[1]))
    assert event.message_type == "tool.event"
    assert event.sequence == 0
    assert event_from_payload(event.payload) == ToolEvent(type="heartbeat")


def test_dora_action_publish_barrier_blocks_event_until_accepted_is_published() -> None:
    action = DoraAction()

    async def scenario() -> list[str]:
        publish_started = asyncio.Event()
        release_publish = asyncio.Event()
        order: list[str] = []

        async def publish(value: pa.RecordBatch) -> None:
            message = tool_message_to_envelope(ToolMessage.from_arrow(value))
            if message.message_type == "tool.invoke.response":
                publish_started.set()
                await release_publish.wait()
                order.append("accepted")
            else:
                order.append(f"event-{message.sequence}")

        binding = DoraToolEndpointBinding(
            _action_handler(action),
            event_sink=publish,
        )
        dispatch = asyncio.create_task(
            binding.dispatch_input(
                tool_envelope_to_message(_action_request()).to_arrow()
            )
        )
        await publish_started.wait()
        assert action.emitter is not None
        event = asyncio.create_task(action.emitter.emit(ToolEvent(type="heartbeat")))
        await asyncio.sleep(0)
        assert order == []
        release_publish.set()
        assert await dispatch == ()
        await event
        return order

    assert asyncio.run(scenario()) == ["accepted", "event-0"]


def test_dora_event_sink_serializes_concurrent_event_sequences() -> None:
    action = DoraAction()

    async def scenario() -> list[int]:
        sequence_zero_started = asyncio.Event()
        release_sequence_zero = asyncio.Event()
        published: list[int] = []

        async def publish(value: pa.RecordBatch) -> None:
            message = tool_message_to_envelope(ToolMessage.from_arrow(value))
            if message.message_type != "tool.event":
                return
            if message.sequence == 0:
                sequence_zero_started.set()
                await release_sequence_zero.wait()
            published.append(cast(int, message.sequence))

        binding = DoraToolEndpointBinding(
            _action_handler(action),
            event_sink=publish,
        )
        await binding.dispatch_input(
            tool_envelope_to_message(_action_request()).to_arrow()
        )
        assert action.emitter is not None
        first = asyncio.create_task(action.emitter.emit(ToolEvent(type="heartbeat")))
        await sequence_zero_started.wait()
        second = asyncio.create_task(action.emitter.emit(ToolEvent(type="progress")))
        await asyncio.sleep(0)
        assert published == []
        release_sequence_zero.set()
        await asyncio.gather(first, second)
        return published

    assert asyncio.run(scenario()) == [0, 1]


def test_dora_event_encoding_failure_does_not_publish_correlated_error() -> None:
    action = DoraAction()
    published: list[ToolEnvelope] = []

    async def scenario() -> None:
        async def publish(value: pa.RecordBatch) -> None:
            published.append(tool_message_to_envelope(ToolMessage.from_arrow(value)))

        binding = DoraToolEndpointBinding(
            _action_handler(action),
            max_message_bytes=1_024,
            event_sink=publish,
        )
        await binding.dispatch_input(
            tool_envelope_to_message(_action_request()).to_arrow()
        )
        assert action.emitter is not None
        with pytest.raises(ToolProtocolError, match="exceeds limit"):
            await action.emitter.emit(
                ToolEvent(type="progress", data={"payload": "x" * 2_000})
            )

    asyncio.run(scenario())

    assert [message.message_type for message in published] == ["tool.invoke.response"]


def test_dora_early_event_encoding_failure_still_publishes_accepted_first() -> None:
    class OversizedEarlyEventAction(DoraAction):
        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            self.emitter = events
            await events.emit(
                ToolEvent(type="progress", data={"payload": "x" * 2_000})
            )
            return ToolAccepted()

    action = OversizedEarlyEventAction()
    published: list[ToolEnvelope] = []

    async def scenario() -> None:
        async def publish(value: pa.RecordBatch) -> None:
            published.append(tool_message_to_envelope(ToolMessage.from_arrow(value)))

        binding = DoraToolEndpointBinding(
            _action_handler(action),
            max_message_bytes=1_024,
            event_sink=publish,
        )
        with pytest.raises(ToolProtocolError, match="exceeds limit"):
            await binding.dispatch_input(
                tool_envelope_to_message(_action_request()).to_arrow()
            )

    asyncio.run(scenario())

    assert [message.message_type for message in published] == ["tool.invoke.response"]
    assert isinstance(invoke_response_from_payload(published[0].payload), ToolAccepted)


def test_dora_legacy_handle_input_rejects_action_without_starting_it() -> None:
    action = DoraAction()
    binding = DoraToolEndpointBinding(_action_handler(action))

    with pytest.raises(NotImplementedError, match="Query-only"):
        asyncio.run(
            binding.handle_input(
                tool_envelope_to_message(_action_request()).to_arrow()
            )
        )

    assert action.start_calls == 0


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


def test_dora_binding_returns_correlated_error_for_oversized_input() -> None:
    query = FakeQuery()
    binding = DoraToolEndpointBinding(_handler(query), max_message_bytes=1_024)
    request = _request()
    message = ToolMessage.from_payload(
        message_type="tool.invoke.request",
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        attempt_id=request.attempt_id,
        endpoint_id=request.endpoint_id,
        endpoint_instance_id=request.endpoint_instance_id,
        operation=request.operation,
        payload={
            "arguments": {"text": "x" * 300},
            "context": request.payload["context"],
        },
    )

    output_value = asyncio.run(binding.handle_input(message.to_arrow()))
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))

    validate_response_correlation(request, response)
    assert response.message_type == "tool.error"
    error = error_from_payload(response.payload)
    assert error.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"
    assert error.details == {
        "max_message_bytes": 1_024,
        "max_request_bytes": 512,
    }
    assert query.calls == 0


def test_dora_binding_rejects_raw_payload_expansion_before_execution() -> None:
    query = FakeQuery()
    binding = DoraToolEndpointBinding(
        _handler(query),
        max_message_bytes=1_024,
        max_carrier_bytes=10_000,
    )
    request = _request()
    message = ToolMessage(
        message_type="tool.invoke.request",
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        attempt_id=request.attempt_id,
        endpoint_id=request.endpoint_id,
        endpoint_instance_id=request.endpoint_instance_id,
        operation=request.operation,
        payload_json=(
            json.dumps(request.payload, separators=(",", ":"), sort_keys=True)
            + " " * 2_048
        ),
    )

    with pytest.raises(ToolProtocolError) as captured:
        asyncio.run(binding.handle_input(message.to_arrow()))

    assert captured.value.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"
    assert query.calls == 0


def test_dora_binding_rejects_oversized_carrier_before_execution() -> None:
    query = FakeQuery()
    binding = DoraToolEndpointBinding(
        _handler(query),
        max_message_bytes=1_024,
        max_carrier_bytes=1_024,
    )
    request = _request()
    message = ToolMessage(
        message_type="tool.invoke.request",
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        attempt_id=request.attempt_id,
        endpoint_id=request.endpoint_id,
        endpoint_instance_id=request.endpoint_instance_id,
        operation=request.operation,
        payload_json=(
            json.dumps(request.payload, separators=(",", ":"), sort_keys=True)
            + " " * 2_048
        ),
    )
    value = message.to_arrow()
    assert value.nbytes > binding.max_carrier_bytes

    with pytest.raises(ToolProtocolError) as captured:
        asyncio.run(binding.handle_input(value))

    assert captured.value.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"
    assert query.calls == 0


def test_oversized_request_for_another_route_remains_uncorrelated() -> None:
    query = FakeQuery()
    binding = DoraToolEndpointBinding(_handler(query), max_message_bytes=1_024)
    request = _request()
    message = ToolMessage.from_payload(
        message_type="tool.invoke.request",
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        attempt_id=request.attempt_id,
        endpoint_id="vision.other",
        endpoint_instance_id=request.endpoint_instance_id,
        operation=request.operation,
        payload={
            "arguments": {"text": "x" * 300},
            "context": request.payload["context"],
        },
    )

    with pytest.raises(ToolProtocolError) as captured:
        asyncio.run(binding.handle_input(message.to_arrow()))

    assert captured.value.code == "FORGE_PROTOCOL_ROUTE_MISMATCH"
    assert query.calls == 0


def test_dora_binding_returns_correlated_error_for_oversized_output() -> None:
    binding = DoraToolEndpointBinding(
        _handler(OversizedQuery()),
        max_message_bytes=1_024,
    )
    request = _request()

    output_value = asyncio.run(
        binding.handle_input(tool_envelope_to_message(request).to_arrow())
    )
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))

    validate_response_correlation(request, response)
    assert response.message_type == "tool.error"
    error = error_from_payload(response.payload)
    assert error.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"
    assert error.details == {"max_message_bytes": 1_024}


def test_accepted_request_reserves_headroom_for_oversized_output_error() -> None:
    binding = DoraToolEndpointBinding(
        _handler(OversizedQuery()),
        max_message_bytes=1_024,
    )
    base = _context()
    context = ToolContext(
        execution_key=base.execution_key,
        tool_id=base.tool_id,
        implementation_id=base.implementation_id,
        endpoint_id=base.endpoint_id,
        operation=base.operation,
        caller_id="c" * 100,
    )
    request = make_invoke_request_envelope(
        ToolRequest(arguments={"class": "cube"}),
        context,
        request_id="request-1",
        endpoint_instance_id="instance-1",
    )
    assert 400 < len(encode_envelope(request)) <= binding.max_request_bytes

    output_value = asyncio.run(
        binding.handle_input(tool_envelope_to_message(request).to_arrow())
    )
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))

    validate_response_correlation(request, response)
    assert len(encode_envelope(response)) <= binding.max_message_bytes
    assert (
        error_from_payload(response.payload).code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"
    )


def test_invalid_response_uses_bounded_protocol_error_message() -> None:
    base = _handler()
    handler = InvalidResponseHandler(
        base.descriptor,
        endpoint_instance_id=base.endpoint_instance_id,
        operations={"detect": FakeQuery()},
    )
    binding = DoraToolEndpointBinding(handler, max_message_bytes=1_024)
    request = _request()

    output_value = asyncio.run(
        binding.handle_input(tool_envelope_to_message(request).to_arrow())
    )
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))

    validate_response_correlation(request, response)
    assert len(encode_envelope(response)) <= binding.max_message_bytes
    error = error_from_payload(response.payload)
    assert error.code == "FORGE_PROTOCOL_INVALID_PAYLOAD"
    assert error.message == "ToolEndpoint response violates the Wire protocol"


def test_dora_binding_returns_correlated_error_for_endpoint_exception() -> None:
    binding = DoraToolEndpointBinding(_handler(RaisingQuery()))
    request = _request()

    output_value = asyncio.run(
        binding.handle_input(tool_envelope_to_message(request).to_arrow())
    )
    response = tool_message_to_envelope(ToolMessage.from_arrow(output_value))

    validate_response_correlation(request, response)
    assert response.message_type == "tool.error"
    error = error_from_payload(response.payload)
    assert error.code == "FORGE_ENDPOINT_INTERNAL"
    assert error.retryable is False


def test_conversion_and_binding_validate_max_message_bytes() -> None:
    request = _request()
    message = ToolMessage.from_payload(
        message_type="tool.invoke.request",
        request_id=request.request_id,
        invocation_id=request.invocation_id,
        attempt_id=request.attempt_id,
        endpoint_id=request.endpoint_id,
        endpoint_instance_id=request.endpoint_instance_id,
        operation=request.operation,
        payload=request.payload,
    )

    with pytest.raises(ToolProtocolError) as outbound:
        tool_envelope_to_message(request, max_message_bytes=1)
    assert outbound.value.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"

    with pytest.raises(ToolProtocolError) as inbound:
        tool_message_to_envelope(message, max_message_bytes=1)
    assert inbound.value.code == "FORGE_PROTOCOL_MESSAGE_TOO_LARGE"

    for invalid in (0, -1, True, 1_023):
        with pytest.raises(ValueError, match="max_message_bytes"):
            DoraToolEndpointBinding(_handler(), max_message_bytes=invalid)

    with pytest.raises(ValueError, match="max_carrier_bytes"):
        DoraToolEndpointBinding(
            _handler(),
            max_message_bytes=1_024,
            max_carrier_bytes=1_023,
        )

    binding = DoraToolEndpointBinding(_handler(), max_message_bytes=1_024)
    assert binding.max_request_bytes == 512
    assert binding.max_carrier_bytes > binding.max_message_bytes


def test_dora_binding_rejects_a_non_handler() -> None:
    with pytest.raises(TypeError, match="ToolEndpointHandler"):
        DoraToolEndpointBinding(object())  # type: ignore[arg-type]


def test_conversion_rejects_the_wrong_model_type() -> None:
    with pytest.raises(TypeError, match="ToolMessage"):
        tool_message_to_envelope(object())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ToolEnvelope"):
        tool_envelope_to_message(object())  # type: ignore[arg-type]
