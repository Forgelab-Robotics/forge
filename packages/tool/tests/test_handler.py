from __future__ import annotations

import asyncio

import pytest

from forge_tool import (
    TOOL_ENDPOINT_PROTOCOL,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEndpointDescriptor,
    ToolEndpointError,
    ToolEndpointHandler,
    ToolEnvelope,
    ToolError,
    ToolEvent,
    ToolEventEmitter,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolOperationDescriptor,
    ToolProtocolError,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
    control_response_from_payload,
    error_from_payload,
    event_from_payload,
    invoke_response_from_payload,
    make_control_request_envelope,
    make_invoke_request_envelope,
    make_result_request_envelope,
    make_status_request_envelope,
    result_response_from_payload,
    status_response_from_payload,
    validate_response_correlation,
)


class FakeQuery:
    def __init__(self, result: ToolResult | None = None) -> None:
        self.result = result or ToolResult(status="succeeded", outputs={"ok": True})
        self.calls: list[tuple[ToolRequest, ToolContext]] = []

    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        self.calls.append((request, context))
        return self.result


class RejectingQuery:
    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        raise ToolEndpointError(
            ToolError(
                code="FORGE_ENDPOINT_BUSY",
                message="query capacity is exhausted",
                retryable=True,
            )
        )


class InvalidQuery:
    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> object:
        return {"not": "a ToolResult"}


class FakeAction:
    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
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


class FakeSession:
    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
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


class MissingControlMethod:
    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        return ToolAccepted()

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return ToolExecutionStatus(phase="running")

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        return ToolResultResponse(status="pending")


def _descriptor(
    *operations: ToolOperationDescriptor,
    endpoint_id: str = "vision.yolo",
    protocol_version: str = TOOL_ENDPOINT_PROTOCOL,
) -> ToolEndpointDescriptor:
    return ToolEndpointDescriptor(
        protocol_version=protocol_version,
        endpoint_id=endpoint_id,
        operations=operations
        or (ToolOperationDescriptor(name="detect", semantics="query"),),
    )


def _context(
    *,
    endpoint_id: str = "vision.yolo",
    operation: str = "detect",
) -> ToolContext:
    return ToolContext(
        execution_key=ToolExecutionKey(
            invocation_id="invocation-1",
            attempt_id="attempt-1",
        ),
        tool_id="forge.tool.detect",
        implementation_id="yolo",
        endpoint_id=endpoint_id,
        operation=operation,
    )


def _invoke_request(
    *,
    endpoint_id: str = "vision.yolo",
    endpoint_instance_id: str | None = "instance-1",
    operation: str = "detect",
) -> ToolEnvelope:
    return make_invoke_request_envelope(
        ToolRequest(arguments={"class": "cube"}),
        _context(endpoint_id=endpoint_id, operation=operation),
        request_id="request-1",
        endpoint_instance_id=endpoint_instance_id,
    )


def test_handler_binds_all_declared_operation_semantics() -> None:
    descriptor = _descriptor(
        ToolOperationDescriptor(name="detect", semantics="query"),
        ToolOperationDescriptor(
            name="move",
            semantics="action",
            cancellable=True,
            status_supported=True,
        ),
        ToolOperationDescriptor(
            name="execute",
            semantics="session",
            stoppable=True,
            status_supported=True,
        ),
    )

    handler = ToolEndpointHandler(
        descriptor,
        endpoint_instance_id="instance-1",
        operations={
            "detect": FakeQuery(),
            "move": FakeAction(),
            "execute": FakeSession(),
        },
    )

    assert handler.descriptor is descriptor
    assert handler.endpoint_instance_id == "instance-1"
    assert handler.operation_names == ("detect", "move", "execute")


@pytest.mark.parametrize(
    ("operations", "message"),
    [
        ({}, "missing implementations: detect"),
        (
            {"detect": FakeQuery(), "other": FakeQuery()},
            "undeclared implementations: other",
        ),
    ],
)
def test_handler_requires_exact_descriptor_operation_mapping(
    operations: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ToolEndpointHandler(
            _descriptor(),
            endpoint_instance_id="instance-1",
            operations=operations,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("operation", "missing_method"),
    [
        (ToolOperationDescriptor(name="detect", semantics="query"), "query"),
        (
            ToolOperationDescriptor(
                name="move", semantics="action", status_supported=True
            ),
            "cancel",
        ),
        (
            ToolOperationDescriptor(
                name="execute", semantics="session", status_supported=True
            ),
            "stop",
        ),
    ],
)
def test_handler_validates_required_endpoint_methods(
    operation: ToolOperationDescriptor,
    missing_method: str,
) -> None:
    implementation: object
    if operation.semantics == "query":
        implementation = object()
    else:
        implementation = MissingControlMethod()

    with pytest.raises(TypeError, match=missing_method):
        ToolEndpointHandler(
            _descriptor(operation),
            endpoint_instance_id="instance-1",
            operations={operation.name: implementation},  # type: ignore[dict-item]
        )


def test_handler_rejects_an_unsupported_descriptor_protocol() -> None:
    with pytest.raises(ValueError, match="descriptor.protocol_version"):
        ToolEndpointHandler(
            _descriptor(protocol_version="forge.tool.endpoint/v2"),
            endpoint_instance_id="instance-1",
            operations={"detect": FakeQuery()},
        )


@pytest.mark.parametrize("endpoint_instance_id", ["", " \t", "\ud800"])
def test_handler_rejects_an_invalid_endpoint_instance_id(
    endpoint_instance_id: str,
) -> None:
    with pytest.raises(ValueError, match="endpoint_instance_id"):
        ToolEndpointHandler(
            _descriptor(),
            endpoint_instance_id=endpoint_instance_id,
            operations={"detect": FakeQuery()},
        )


def test_handler_requires_a_string_keyed_operation_mapping() -> None:
    with pytest.raises(TypeError, match="operations must be a mapping"):
        ToolEndpointHandler(
            _descriptor(),
            endpoint_instance_id="instance-1",
            operations=[],  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError, match="names must be strings"):
        ToolEndpointHandler(
            _descriptor(),
            endpoint_instance_id="instance-1",
            operations={1: FakeQuery()},  # type: ignore[dict-item]
        )


def test_handler_copies_the_operation_mapping() -> None:
    query = FakeQuery()
    operations = {"detect": query}
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations=operations,
    )
    operations["detect"] = FakeQuery(
        ToolResult(status="failed", error=ToolError(code="CHANGED", message="changed"))
    )

    response = asyncio.run(handler.handle_invoke(_invoke_request()))

    assert invoke_response_from_payload(response.payload) == query.result


def test_query_handler_returns_a_correlated_terminal_result() -> None:
    query = FakeQuery(
        ToolResult(status="succeeded", outputs={"objects": [{"class": "cube"}]})
    )
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations={"detect": query},
    )
    request = _invoke_request()

    response = asyncio.run(handler.handle_invoke(request))

    validate_response_correlation(request, response)
    assert invoke_response_from_payload(response.payload) == query.result
    assert len(query.calls) == 1
    endpoint_request, context = query.calls[0]
    assert endpoint_request.arguments == {"class": "cube"}
    assert context.execution_key == ToolExecutionKey("invocation-1", "attempt-1")
    assert context.operation == "detect"


def test_query_handler_converts_structured_endpoint_rejection() -> None:
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations={"detect": RejectingQuery()},
    )
    request = _invoke_request()

    response = asyncio.run(handler.handle_invoke(request))

    validate_response_correlation(request, response)
    rejection = invoke_response_from_payload(response.payload)
    assert isinstance(rejection, ToolError)
    assert rejection.code == "FORGE_ENDPOINT_BUSY"
    assert rejection.retryable is True


def test_query_handler_rejects_an_invalid_endpoint_result() -> None:
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations={"detect": InvalidQuery()},  # type: ignore[dict-item]
    )

    with pytest.raises(TypeError, match="must return a ToolResult"):
        asyncio.run(handler.handle_invoke(_invoke_request()))


@pytest.mark.parametrize(
    ("envelope", "path"),
    [
        (_invoke_request(endpoint_id="vision.other"), "endpoint_id"),
        (_invoke_request(endpoint_instance_id="instance-old"), "endpoint_instance_id"),
        (_invoke_request(endpoint_instance_id=None), "endpoint_instance_id"),
    ],
)
def test_query_handler_rejects_retargeted_requests(envelope: object, path: str) -> None:
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations={"detect": FakeQuery()},
    )

    with pytest.raises(ToolProtocolError) as captured:
        asyncio.run(handler.handle_invoke(envelope))  # type: ignore[arg-type]

    assert captured.value.code == "FORGE_PROTOCOL_ROUTE_MISMATCH"
    assert captured.value.path == path


def test_query_handler_rejects_an_unknown_operation() -> None:
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations={"detect": FakeQuery()},
    )

    with pytest.raises(ToolProtocolError) as captured:
        asyncio.run(handler.handle_invoke(_invoke_request(operation="classify")))

    assert captured.value.code == "FORGE_PROTOCOL_UNKNOWN_OPERATION"
    assert captured.value.path == "operation"


def test_legacy_handle_invoke_remains_query_only() -> None:
    descriptor = _descriptor(
        ToolOperationDescriptor(name="move", semantics="action", status_supported=True),
        endpoint_id="motion.arm",
    )
    handler = ToolEndpointHandler(
        descriptor,
        endpoint_instance_id="instance-1",
        operations={"move": FakeAction()},
    )
    request = make_invoke_request_envelope(
        ToolRequest(arguments={}),
        _context(endpoint_id="motion.arm", operation="move"),
        request_id="request-1",
        endpoint_instance_id="instance-1",
    )

    with pytest.raises(NotImplementedError, match="Query-only"):
        asyncio.run(handler.handle_invoke(request))


class RecordingAction(FakeAction):
    def __init__(
        self,
        *,
        events: tuple[ToolEvent, ...] = (),
        status: ToolExecutionStatus | None = None,
        result: ToolResultResponse | None = None,
    ) -> None:
        self.events = events
        self.current_status = status or ToolExecutionStatus(phase="running")
        self.current_result = result or ToolResultResponse(status="pending")
        self.start_calls = 0
        self.cancel_calls = 0
        self.emitter: ToolEventEmitter | None = None

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        self.start_calls += 1
        self.emitter = events
        for event in self.events:
            await events.emit(event)
        return ToolAccepted(details={"executor": "arm"})

    async def cancel(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        self.cancel_calls += 1
        return ToolControlResponse(
            command="cancel",
            status="accepted",
            details={"reason": reason},
        )

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return self.current_status

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        return self.current_result


def _action_handler(
    action: RecordingAction,
    *,
    max_early_events: int = 32,
    max_concurrency: int = 1,
    max_retained_executions: int = 1_024,
) -> ToolEndpointHandler:
    return ToolEndpointHandler(
        _descriptor(
            ToolOperationDescriptor(
                name="move",
                semantics="action",
                cancellable=True,
                status_supported=True,
                max_concurrency=max_concurrency,
            ),
            endpoint_id="motion.arm",
        ),
        endpoint_instance_id="instance-1",
        operations={"move": action},
        max_early_events=max_early_events,
        max_retained_executions=max_retained_executions,
    )


def _action_context(
    *,
    invocation_id: str = "invocation-1",
    attempt_id: str = "attempt-1",
) -> ToolContext:
    context = _context(endpoint_id="motion.arm", operation="move")
    return ToolContext(
        execution_key=ToolExecutionKey(invocation_id, attempt_id),
        tool_id=context.tool_id,
        implementation_id=context.implementation_id,
        endpoint_id=context.endpoint_id,
        operation=context.operation,
    )


def _action_request(
    *,
    request_id: str = "request-1",
    invocation_id: str = "invocation-1",
) -> ToolEnvelope:
    return make_invoke_request_envelope(
        ToolRequest(arguments={"target": "home"}),
        _action_context(invocation_id=invocation_id),
        request_id=request_id,
        endpoint_instance_id="instance-1",
    )


def test_action_dispatch_orders_accepted_before_buffered_events() -> None:
    action = RecordingAction(
        events=(
            ToolEvent(type="progress", data={"fraction": 0.25}),
            ToolEvent(type="heartbeat"),
        )
    )
    handler = _action_handler(action)
    request = _action_request()

    messages = asyncio.run(handler.dispatch(request))

    assert [message.message_type for message in messages] == [
        "tool.invoke.response",
        "tool.event",
        "tool.event",
    ]
    assert invoke_response_from_payload(messages[0].payload) == ToolAccepted(
        details={"executor": "arm"}
    )
    assert [message.sequence for message in messages[1:]] == [0, 1]
    assert [event_from_payload(message.payload) for message in messages[1:]] == [
        ToolEvent(type="progress", data={"fraction": 0.25}),
        ToolEvent(type="heartbeat"),
    ]


def test_duplicate_action_execution_key_does_not_restart_provider() -> None:
    action = RecordingAction()
    handler = _action_handler(action)
    first = _action_request(request_id="request-1")
    duplicate = _action_request(request_id="request-2")

    first_response = asyncio.run(handler.dispatch(first))[0]
    duplicate_response = asyncio.run(handler.dispatch(duplicate))[0]

    assert action.start_calls == 1
    assert invoke_response_from_payload(first_response.payload) == ToolAccepted(
        details={"executor": "arm"}
    )
    assert invoke_response_from_payload(duplicate_response.payload) == ToolAccepted(
        details={"executor": "arm"}
    )
    validate_response_correlation(duplicate, duplicate_response)


def test_concurrent_duplicate_action_waits_without_restarting_provider() -> None:
    class DelayedAction(RecordingAction):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            self.started.set()
            await self.release.wait()
            return ToolAccepted(details={"executor": "arm"})

    async def scenario() -> tuple[ToolEnvelope, ToolEnvelope, int]:
        action = DelayedAction()
        handler = _action_handler(action)
        first = asyncio.create_task(
            handler.dispatch(_action_request(request_id="request-1"))
        )
        await action.started.wait()
        duplicate = asyncio.create_task(
            handler.dispatch(_action_request(request_id="request-2"))
        )
        await asyncio.sleep(0)
        action.release.set()
        return (await first)[0], (await duplicate)[0], action.start_calls

    first, duplicate, start_calls = asyncio.run(scenario())

    assert start_calls == 1
    assert invoke_response_from_payload(first.payload) == invoke_response_from_payload(
        duplicate.payload
    )


def test_action_early_event_buffer_overflow_becomes_unknown_without_retry() -> None:
    action = RecordingAction(
        events=(
            ToolEvent(type="heartbeat"),
            ToolEvent(type="heartbeat"),
        )
    )
    handler = _action_handler(action, max_early_events=1)

    first = asyncio.run(handler.dispatch(_action_request(request_id="request-1")))[0]
    duplicate = asyncio.run(
        handler.dispatch(_action_request(request_id="request-2"))
    )[0]

    outcome = invoke_response_from_payload(first.payload)
    assert isinstance(outcome, ToolResult)
    assert outcome.status == "unknown"
    assert outcome.error is not None
    assert outcome.error.code == "FORGE_ENDPOINT_OUTCOME_UNKNOWN"
    assert invoke_response_from_payload(duplicate.payload) == outcome
    assert action.start_calls == 1


def test_action_terminal_event_requires_and_retains_matching_result() -> None:
    result = ToolResult(status="succeeded", outputs={"position": "home"})
    action = RecordingAction(
        events=(ToolEvent(type="executor_completed"),),
        status=ToolExecutionStatus(phase="completed"),
        result=ToolResultResponse(status="available", result=result),
    )
    handler = _action_handler(action)

    messages = asyncio.run(handler.dispatch(_action_request()))
    result_request = make_result_request_envelope(
        _action_context(),
        request_id="result-1",
        endpoint_instance_id="instance-1",
    )
    result_response = asyncio.run(handler.handle_result(result_request))

    assert messages[1].message_type == "tool.event"
    assert result_response_from_payload(result_response.payload) == ToolResultResponse(
        status="available",
        result=result,
    )
    assert action.emitter is not None
    with pytest.raises(ToolProtocolError, match="after terminal"):
        asyncio.run(action.emitter.emit(ToolEvent(type="heartbeat")))


@pytest.mark.parametrize(
    "failure",
    (
        pytest.param(
            RuntimeError("start failed after terminal result was established"),
            id="runtime-error",
        ),
        pytest.param(
            ToolEndpointError(
                ToolError(
                    code="FORGE_ENDPOINT_REJECTED",
                    message="structured failure after terminal result was established",
                )
            ),
            id="structured-endpoint-error",
        ),
    ),
)
def test_action_start_failure_preserves_an_established_terminal_result(
    failure: Exception,
) -> None:
    result = ToolResult(status="succeeded", outputs={"position": "home"})

    class TerminalThenFailingAction(RecordingAction):
        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            self.emitter = events
            await events.emit(ToolEvent(type="executor_completed"))
            raise failure

    action = TerminalThenFailingAction(
        status=ToolExecutionStatus(phase="completed"),
        result=ToolResultResponse(status="available", result=result),
    )
    handler = _action_handler(action)

    first = asyncio.run(handler.dispatch(_action_request(request_id="request-1")))[0]
    duplicate = asyncio.run(
        handler.dispatch(_action_request(request_id="request-2"))
    )[0]

    assert invoke_response_from_payload(first.payload) == result
    assert invoke_response_from_payload(duplicate.payload) == result
    assert action.start_calls == 1


def test_action_status_result_and_control_dispatch_provider_models() -> None:
    result = ToolResult(status="succeeded", outputs={"position": "home"})
    action = RecordingAction()
    handler = _action_handler(action)
    asyncio.run(handler.dispatch(_action_request()))

    status_request = make_status_request_envelope(
        _action_context(),
        request_id="status-1",
        endpoint_instance_id="instance-1",
    )
    result_request = make_result_request_envelope(
        _action_context(),
        request_id="result-1",
        endpoint_instance_id="instance-1",
    )
    control_request = make_control_request_envelope(
        "cancel",
        _action_context(),
        request_id="control-1",
        endpoint_instance_id="instance-1",
        reason="operator request",
    )

    status_response = asyncio.run(handler.handle_status(status_request))
    result_response = asyncio.run(handler.handle_result(result_request))
    control_response = asyncio.run(handler.handle_control(control_request))

    assert status_response_from_payload(status_response.payload) == ToolExecutionStatus(
        phase="running"
    )
    assert result_response_from_payload(result_response.payload) == ToolResultResponse(
        status="pending"
    )
    assert control_response_from_payload(control_response.payload) == ToolControlResponse(
        command="cancel",
        status="accepted",
        details={"reason": "operator request"},
    )
    assert action.cancel_calls == 1

    action.current_status = ToolExecutionStatus(phase="completed")
    action.current_result = ToolResultResponse(status="available", result=result)
    terminal_status = asyncio.run(handler.handle_status(status_request))
    assert status_response_from_payload(terminal_status.payload).phase == "completed"
    assert action.emitter is not None
    with pytest.raises(ToolProtocolError, match="after terminal"):
        asyncio.run(action.emitter.emit(ToolEvent(type="progress")))


def test_cancelled_action_start_converges_unknown_and_wakes_duplicate() -> None:
    class CancelledStartAction(RecordingAction):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.never = asyncio.Event()

        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            self.emitter = events
            self.started.set()
            await self.never.wait()
            return ToolAccepted()

    async def scenario() -> tuple[ToolEnvelope, int]:
        action = CancelledStartAction()
        handler = _action_handler(action)
        first = asyncio.create_task(
            handler.dispatch(_action_request(request_id="request-1"))
        )
        await action.started.wait()
        duplicate = asyncio.create_task(
            handler.dispatch(_action_request(request_id="request-2"))
        )
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return (await asyncio.wait_for(duplicate, timeout=1))[0], action.start_calls

    duplicate, start_calls = asyncio.run(scenario())

    outcome = invoke_response_from_payload(duplicate.payload)
    assert isinstance(outcome, ToolResult)
    assert outcome.status == "unknown"
    assert start_calls == 1


def test_action_max_concurrency_rejects_then_terminal_releases_once() -> None:
    action = RecordingAction()
    handler = _action_handler(action, max_concurrency=1)

    first = asyncio.run(
        handler.dispatch(_action_request(request_id="first", invocation_id="first"))
    )[0]
    blocked = asyncio.run(
        handler.dispatch(_action_request(request_id="blocked", invocation_id="second"))
    )[0]

    assert isinstance(invoke_response_from_payload(first.payload), ToolAccepted)
    capacity = invoke_response_from_payload(blocked.payload)
    assert isinstance(capacity, ToolError)
    assert capacity.code == "FORGE_ENDPOINT_CAPACITY"
    assert action.start_calls == 1

    action.current_status = ToolExecutionStatus(phase="completed")
    action.current_result = ToolResultResponse(
        status="available",
        result=ToolResult(status="succeeded"),
    )
    terminal_request = make_status_request_envelope(
        _action_context(invocation_id="first"),
        request_id="terminal",
        endpoint_instance_id="instance-1",
    )
    asyncio.run(handler.handle_status(terminal_request))
    # Repeating terminal observation must not release a second permit.
    asyncio.run(handler.handle_status(terminal_request))

    action.current_status = ToolExecutionStatus(phase="running")
    action.current_result = ToolResultResponse(status="pending")
    admitted = asyncio.run(
        handler.dispatch(_action_request(request_id="retry", invocation_id="second"))
    )[0]
    assert isinstance(invoke_response_from_payload(admitted.payload), ToolAccepted)
    assert action.start_calls == 2


def test_action_execution_retention_is_bounded_and_evicts_completed_records() -> None:
    class RejectingAction(RecordingAction):
        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            raise ToolEndpointError(
                ToolError(code="BUSY", message="not admitted", retryable=True)
            )

    action = RejectingAction()
    handler = _action_handler(action, max_retained_executions=2)

    for index in range(3):
        response = asyncio.run(
            handler.dispatch(
                _action_request(
                    request_id=f"request-{index}",
                    invocation_id=f"invocation-{index}",
                )
            )
        )[0]
        assert isinstance(invoke_response_from_payload(response.payload), ToolError)

    asyncio.run(
        handler.dispatch(
            _action_request(request_id="request-retry", invocation_id="invocation-0")
        )
    )
    assert action.start_calls == 4


def test_action_status_rejects_backward_phase_transition() -> None:
    action = RecordingAction()
    handler = _action_handler(action)
    asyncio.run(handler.dispatch(_action_request()))
    status_request = make_status_request_envelope(
        _action_context(),
        request_id="status",
        endpoint_instance_id="instance-1",
    )

    asyncio.run(handler.handle_status(status_request))
    action.current_status = ToolExecutionStatus(phase="accepted")
    response = asyncio.run(handler.handle_status(status_request))

    assert response.message_type == "tool.error"
    assert error_from_payload(response.payload).code == "FORGE_ENDPOINT_INVALID_TRANSITION"


class RecordingSession(FakeSession):
    def __init__(
        self,
        *,
        events: tuple[ToolEvent, ...] = (),
        status: ToolExecutionStatus | None = None,
        result: ToolResultResponse | None = None,
    ) -> None:
        self.events = events
        self.current_status = status or ToolExecutionStatus(phase="running")
        self.current_result = result or ToolResultResponse(status="pending")
        self.start_calls = 0
        self.stop_calls = 0
        self.emitter: ToolEventEmitter | None = None

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        self.start_calls += 1
        self.emitter = events
        for event in self.events:
            await events.emit(event)
        return ToolAccepted(details={"service": "policy"})

    async def stop(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        self.stop_calls += 1
        return ToolControlResponse(
            command="stop",
            status="accepted",
            details={"reason": reason},
        )

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return self.current_status

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        return self.current_result


def _session_handler(
    session: RecordingSession,
    *,
    max_early_events: int = 32,
    max_concurrency: int = 1,
    max_retained_executions: int = 1_024,
) -> ToolEndpointHandler:
    return ToolEndpointHandler(
        _descriptor(
            ToolOperationDescriptor(
                name="serve",
                semantics="session",
                stoppable=True,
                status_supported=True,
                max_concurrency=max_concurrency,
            ),
            endpoint_id="policy.runner",
        ),
        endpoint_instance_id="instance-1",
        operations={"serve": session},
        max_early_events=max_early_events,
        max_retained_executions=max_retained_executions,
    )


def _session_context(
    *,
    invocation_id: str = "invocation-1",
    attempt_id: str = "attempt-1",
) -> ToolContext:
    context = _context(endpoint_id="policy.runner", operation="serve")
    return ToolContext(
        execution_key=ToolExecutionKey(invocation_id, attempt_id),
        tool_id=context.tool_id,
        implementation_id=context.implementation_id,
        endpoint_id=context.endpoint_id,
        operation=context.operation,
    )


def _session_request(
    *,
    request_id: str = "request-1",
    invocation_id: str = "invocation-1",
) -> ToolEnvelope:
    return make_invoke_request_envelope(
        ToolRequest(arguments={}),
        _session_context(invocation_id=invocation_id),
        request_id=request_id,
        endpoint_instance_id="instance-1",
    )


def test_session_dispatch_orders_accepted_before_buffered_events() -> None:
    session = RecordingSession(
        events=(
            ToolEvent(type="progress", data={"fraction": 0.25}),
            ToolEvent(type="heartbeat"),
        )
    )
    handler = _session_handler(session)
    request = _session_request()

    messages = asyncio.run(handler.dispatch(request))

    assert [message.message_type for message in messages] == [
        "tool.invoke.response",
        "tool.event",
        "tool.event",
    ]
    assert invoke_response_from_payload(messages[0].payload) == ToolAccepted(
        details={"service": "policy"}
    )
    assert [message.sequence for message in messages[1:]] == [0, 1]
    assert [event_from_payload(message.payload) for message in messages[1:]] == [
        ToolEvent(type="progress", data={"fraction": 0.25}),
        ToolEvent(type="heartbeat"),
    ]


def test_duplicate_session_execution_key_does_not_restart_provider() -> None:
    session = RecordingSession()
    handler = _session_handler(session)
    first = _session_request(request_id="request-1")
    duplicate = _session_request(request_id="request-2")

    first_response = asyncio.run(handler.dispatch(first))[0]
    duplicate_response = asyncio.run(handler.dispatch(duplicate))[0]

    assert session.start_calls == 1
    assert invoke_response_from_payload(first_response.payload) == ToolAccepted(
        details={"service": "policy"}
    )
    assert invoke_response_from_payload(duplicate_response.payload) == ToolAccepted(
        details={"service": "policy"}
    )
    validate_response_correlation(duplicate, duplicate_response)


def test_concurrent_duplicate_session_waits_without_restarting_provider() -> None:
    class DelayedSession(RecordingSession):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            self.started.set()
            await self.release.wait()
            return ToolAccepted(details={"service": "policy"})

    async def scenario() -> tuple[ToolEnvelope, ToolEnvelope, int]:
        session = DelayedSession()
        handler = _session_handler(session)
        first = asyncio.create_task(
            handler.dispatch(_session_request(request_id="request-1"))
        )
        await session.started.wait()
        duplicate = asyncio.create_task(
            handler.dispatch(_session_request(request_id="request-2"))
        )
        await asyncio.sleep(0)
        session.release.set()
        return (await first)[0], (await duplicate)[0], session.start_calls

    first, duplicate, start_calls = asyncio.run(scenario())

    assert start_calls == 1
    assert invoke_response_from_payload(first.payload) == invoke_response_from_payload(
        duplicate.payload
    )


def test_session_early_event_buffer_overflow_becomes_unknown_without_retry() -> None:
    session = RecordingSession(
        events=(
            ToolEvent(type="heartbeat"),
            ToolEvent(type="heartbeat"),
        )
    )
    handler = _session_handler(session, max_early_events=1)

    first = asyncio.run(handler.dispatch(_session_request(request_id="request-1")))[0]
    duplicate = asyncio.run(
        handler.dispatch(_session_request(request_id="request-2"))
    )[0]

    outcome = invoke_response_from_payload(first.payload)
    assert isinstance(outcome, ToolResult)
    assert outcome.status == "unknown"
    assert outcome.error is not None
    assert outcome.error.code == "FORGE_ENDPOINT_OUTCOME_UNKNOWN"
    assert invoke_response_from_payload(duplicate.payload) == outcome
    assert session.start_calls == 1


def test_session_terminal_event_requires_and_retains_matching_result() -> None:
    result = ToolResult(status="stopped", outputs={"uptime_s": 12.5})
    session = RecordingSession(
        events=(ToolEvent(type="stopped"),),
        status=ToolExecutionStatus(phase="stopped"),
        result=ToolResultResponse(status="available", result=result),
    )
    handler = _session_handler(session)

    messages = asyncio.run(handler.dispatch(_session_request()))
    result_request = make_result_request_envelope(
        _session_context(),
        request_id="result-1",
        endpoint_instance_id="instance-1",
    )
    result_response = asyncio.run(handler.handle_result(result_request))

    assert messages[1].message_type == "tool.event"
    assert result_response_from_payload(result_response.payload) == ToolResultResponse(
        status="available",
        result=result,
    )
    assert session.emitter is not None
    with pytest.raises(ToolProtocolError, match="after terminal"):
        asyncio.run(session.emitter.emit(ToolEvent(type="heartbeat")))


def test_session_status_result_and_stop_dispatch_provider_models() -> None:
    result = ToolResult(status="stopped", outputs={"uptime_s": 12.5})
    session = RecordingSession()
    handler = _session_handler(session)
    asyncio.run(handler.dispatch(_session_request()))

    status_request = make_status_request_envelope(
        _session_context(),
        request_id="status-1",
        endpoint_instance_id="instance-1",
    )
    result_request = make_result_request_envelope(
        _session_context(),
        request_id="result-1",
        endpoint_instance_id="instance-1",
    )
    control_request = make_control_request_envelope(
        "stop",
        _session_context(),
        request_id="control-1",
        endpoint_instance_id="instance-1",
        reason="operator request",
    )

    status_response = asyncio.run(handler.handle_status(status_request))
    result_response = asyncio.run(handler.handle_result(result_request))
    control_response = asyncio.run(handler.handle_control(control_request))

    assert status_response_from_payload(status_response.payload) == ToolExecutionStatus(
        phase="running"
    )
    assert result_response_from_payload(result_response.payload) == ToolResultResponse(
        status="pending"
    )
    assert control_response_from_payload(control_response.payload) == ToolControlResponse(
        command="stop",
        status="accepted",
        details={"reason": "operator request"},
    )
    assert session.stop_calls == 1

    session.current_status = ToolExecutionStatus(phase="stopped")
    session.current_result = ToolResultResponse(status="available", result=result)
    terminal_status = asyncio.run(handler.handle_status(status_request))
    assert status_response_from_payload(terminal_status.payload).phase == "stopped"
    assert session.emitter is not None
    with pytest.raises(ToolProtocolError, match="after terminal"):
        asyncio.run(session.emitter.emit(ToolEvent(type="progress")))


def test_stopped_session_start_converges_unknown_and_wakes_duplicate() -> None:
    class StoppedStartSession(RecordingSession):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()
            self.never = asyncio.Event()

        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            self.emitter = events
            self.started.set()
            await self.never.wait()
            return ToolAccepted()

    async def scenario() -> tuple[ToolEnvelope, int]:
        session = StoppedStartSession()
        handler = _session_handler(session)
        first = asyncio.create_task(
            handler.dispatch(_session_request(request_id="request-1"))
        )
        await session.started.wait()
        duplicate = asyncio.create_task(
            handler.dispatch(_session_request(request_id="request-2"))
        )
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        return (await asyncio.wait_for(duplicate, timeout=1))[0], session.start_calls

    duplicate, start_calls = asyncio.run(scenario())

    outcome = invoke_response_from_payload(duplicate.payload)
    assert isinstance(outcome, ToolResult)
    assert outcome.status == "unknown"
    assert start_calls == 1


def test_session_max_concurrency_rejects_then_terminal_releases_once() -> None:
    session = RecordingSession()
    handler = _session_handler(session, max_concurrency=1)

    first = asyncio.run(
        handler.dispatch(_session_request(request_id="first", invocation_id="first"))
    )[0]
    blocked = asyncio.run(
        handler.dispatch(_session_request(request_id="blocked", invocation_id="second"))
    )[0]

    assert isinstance(invoke_response_from_payload(first.payload), ToolAccepted)
    capacity = invoke_response_from_payload(blocked.payload)
    assert isinstance(capacity, ToolError)
    assert capacity.code == "FORGE_ENDPOINT_CAPACITY"
    assert session.start_calls == 1

    session.current_status = ToolExecutionStatus(phase="stopped")
    session.current_result = ToolResultResponse(
        status="available",
        result=ToolResult(status="stopped"),
    )
    terminal_request = make_status_request_envelope(
        _session_context(invocation_id="first"),
        request_id="terminal",
        endpoint_instance_id="instance-1",
    )
    asyncio.run(handler.handle_status(terminal_request))
    # Repeating terminal observation must not release a second permit.
    asyncio.run(handler.handle_status(terminal_request))

    session.current_status = ToolExecutionStatus(phase="running")
    session.current_result = ToolResultResponse(status="pending")
    admitted = asyncio.run(
        handler.dispatch(_session_request(request_id="retry", invocation_id="second"))
    )[0]
    assert isinstance(invoke_response_from_payload(admitted.payload), ToolAccepted)
    assert session.start_calls == 2


def test_session_execution_retention_is_bounded_and_evicts_completed_records() -> None:
    class RejectingSession(RecordingSession):
        async def start(
            self,
            request: ToolRequest,
            context: ToolContext,
            events: ToolEventEmitter,
        ) -> ToolAccepted:
            self.start_calls += 1
            raise ToolEndpointError(
                ToolError(code="BUSY", message="not admitted", retryable=True)
            )

    session = RejectingSession()
    handler = _session_handler(session, max_retained_executions=2)

    for index in range(3):
        response = asyncio.run(
            handler.dispatch(
                _session_request(
                    request_id=f"request-{index}",
                    invocation_id=f"invocation-{index}",
                )
            )
        )[0]
        assert isinstance(invoke_response_from_payload(response.payload), ToolError)

    asyncio.run(
        handler.dispatch(
            _session_request(request_id="request-retry", invocation_id="invocation-0")
        )
    )
    assert session.start_calls == 4


def test_session_status_rejects_backward_phase_transition() -> None:
    session = RecordingSession()
    handler = _session_handler(session)
    asyncio.run(handler.dispatch(_session_request()))
    status_request = make_status_request_envelope(
        _session_context(),
        request_id="status",
        endpoint_instance_id="instance-1",
    )

    asyncio.run(handler.handle_status(status_request))
    session.current_status = ToolExecutionStatus(phase="accepted")
    response = asyncio.run(handler.handle_status(status_request))

    assert response.message_type == "tool.error"
    assert error_from_payload(response.payload).code == "FORGE_ENDPOINT_INVALID_TRANSITION"


def test_control_commands_are_semantics_scoped() -> None:
    action = RecordingAction()
    action_handler = _action_handler(action)
    asyncio.run(action_handler.dispatch(_action_request()))
    stop_request = make_control_request_envelope(
        "stop",
        _action_context(),
        request_id="stop-1",
        endpoint_instance_id="instance-1",
    )
    response = asyncio.run(action_handler.handle_control(stop_request))
    assert control_response_from_payload(response.payload) == ToolControlResponse(
        command="stop",
        status="unsupported",
    )
    assert action.cancel_calls == 0

    session = RecordingSession()
    session_handler = _session_handler(session)
    asyncio.run(session_handler.dispatch(_session_request()))
    cancel_request = make_control_request_envelope(
        "cancel",
        _session_context(),
        request_id="cancel-1",
        endpoint_instance_id="instance-1",
    )
    response = asyncio.run(session_handler.handle_control(cancel_request))
    assert control_response_from_payload(response.payload) == ToolControlResponse(
        command="cancel",
        status="unsupported",
    )
    assert session.stop_calls == 0


def test_query_handler_requires_an_invoke_request() -> None:
    handler = ToolEndpointHandler(
        _descriptor(),
        endpoint_instance_id="instance-1",
        operations={"detect": FakeQuery()},
    )
    status_request = make_status_request_envelope(
        _context(),
        request_id="request-1",
        endpoint_instance_id="instance-1",
    )

    with pytest.raises(ValueError, match="tool.invoke.request"):
        asyncio.run(handler.handle_invoke(status_request))
