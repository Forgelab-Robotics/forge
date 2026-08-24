from __future__ import annotations

import asyncio

from forge_tool import (
    ActionToolEndpoint,
    QueryToolEndpoint,
    SessionToolEndpoint,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEvent,
    ToolEventEmitter,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
)


class CollectingEmitter:
    def __init__(self) -> None:
        self.events: list[ToolEvent] = []

    async def emit(self, event: ToolEvent) -> None:
        self.events.append(event)


class FakeQuery:
    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        assert context.execution_key == _key()
        return ToolResult(
            status="succeeded",
            outputs={"arguments": dict(request.arguments)},
        )


class FakeAction:
    def __init__(self) -> None:
        self.phases: dict[ToolExecutionKey, str] = {}

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        self.phases[context.execution_key] = "running"
        await events.emit(ToolEvent(type="progress", data={"fraction": 0.5}))
        return ToolAccepted()

    async def cancel(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        assert reason == "operator request"
        self.phases[key] = "cancelled"
        return ToolControlResponse(command="cancel", status="accepted")

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return ToolExecutionStatus(phase=self.phases[key])  # type: ignore[arg-type]

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        if self.phases[key] != "cancelled":
            return ToolResultResponse(status="pending")
        return ToolResultResponse(
            status="available",
            result=ToolResult(status="cancelled"),
        )


class FakeSession:
    def __init__(self) -> None:
        self.phases: dict[ToolExecutionKey, str] = {}

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        assert request.arguments["task"] == "pick cube"
        self.phases[context.execution_key] = "running"
        await events.emit(ToolEvent(type="heartbeat"))
        return ToolAccepted()

    async def stop(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        assert reason == "test complete"
        self.phases[key] = "stopped"
        return ToolControlResponse(command="stop", status="accepted")

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        return ToolExecutionStatus(phase=self.phases[key])  # type: ignore[arg-type]

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        if self.phases[key] != "stopped":
            return ToolResultResponse(status="pending")
        return ToolResultResponse(
            status="available",
            result=ToolResult(status="stopped"),
        )


def _key(attempt_id: str = "attempt-1") -> ToolExecutionKey:
    return ToolExecutionKey(invocation_id="invocation-1", attempt_id=attempt_id)


def _context(
    *, endpoint_id: str, operation: str, attempt_id: str = "attempt-1"
) -> ToolContext:
    return ToolContext(
        execution_key=_key(attempt_id),
        tool_id="forge.tool.test",
        implementation_id="fake",
        endpoint_id=endpoint_id,
        operation=operation,
    )


async def _exercise_contracts() -> None:
    query: QueryToolEndpoint = FakeQuery()
    action: ActionToolEndpoint = FakeAction()
    session: SessionToolEndpoint = FakeSession()
    emitter = CollectingEmitter()

    query_result = await query.query(
        ToolRequest(arguments={"value": 1}),
        _context(endpoint_id="fake.query", operation="query"),
    )
    action_context = _context(endpoint_id="motion.trajectory", operation="execute")
    await action.start(
        ToolRequest(arguments={"trajectory": []}),
        action_context,
        emitter,
    )
    action_status = await action.status(action_context.execution_key)
    action_control = await action.cancel(
        action_context.execution_key,
        reason="operator request",
    )
    action_result = await action.result(action_context.execution_key)

    session_context = _context(endpoint_id="policy.lerobot", operation="execute")
    await session.start(
        ToolRequest(arguments={"task": "pick cube"}),
        session_context,
        emitter,
    )
    session_status = await session.status(session_context.execution_key)
    session_control = await session.stop(
        session_context.execution_key,
        reason="test complete",
    )
    session_result = await session.result(session_context.execution_key)

    second_attempt = _context(
        endpoint_id="policy.lerobot",
        operation="execute",
        attempt_id="attempt-2",
    )
    await session.start(
        ToolRequest(arguments={"task": "pick cube"}),
        second_attempt,
        emitter,
    )

    assert query_result.outputs == {"arguments": {"value": 1}}
    assert action_status.phase == "running"
    assert action_control.status == "accepted"
    assert action_result == ToolResultResponse(
        status="available",
        result=ToolResult(status="cancelled"),
    )
    assert session_status.phase == "running"
    assert session_control.status == "accepted"
    assert session_result == ToolResultResponse(
        status="available",
        result=ToolResult(status="stopped"),
    )
    assert (await session.status(second_attempt.execution_key)).phase == "running"
    assert [event.type for event in emitter.events] == [
        "progress",
        "heartbeat",
        "heartbeat",
    ]


def test_async_query_action_and_session_contract_calls() -> None:
    asyncio.run(_exercise_contracts())
