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
    ToolEventEmitter,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolOperationDescriptor,
    ToolProtocolError,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
    invoke_response_from_payload,
    make_invoke_request_envelope,
    make_status_request_envelope,
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


def test_query_first_handler_defers_action_invocation() -> None:
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

    with pytest.raises(NotImplementedError, match="action operation 'move'"):
        asyncio.run(handler.handle_invoke(request))


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
