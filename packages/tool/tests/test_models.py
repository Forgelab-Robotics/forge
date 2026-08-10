from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict

import pytest

from forge_tool import (
    MAX_SAFE_JSON_INTEGER,
    EndpointStatus,
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolError,
    ToolEvent,
    ToolEventType,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
    validate_execution_result,
)


def _key(attempt_id: str = "attempt-1") -> ToolExecutionKey:
    return ToolExecutionKey(invocation_id="invocation-1", attempt_id=attempt_id)


def _context(metadata: dict[str, object] | None = None) -> ToolContext:
    return ToolContext(
        execution_key=_key(),
        tool_id="forge.tool.detect_objects",
        implementation_id="yolo",
        endpoint_id="vision.yolo",
        operation="detect",
        caller_id="test-client",
        deadline_ms=1_800_000_000_000,
        metadata=metadata or {},
    )


def test_execution_key_is_attempt_scoped_hashable_identity() -> None:
    first = _key("attempt-1")
    second = _key("attempt-2")

    assert first != second
    assert {first, second} == {first, second}
    with pytest.raises(ValueError, match="invocation_id"):
        ToolExecutionKey(invocation_id="", attempt_id="attempt-1")
    with pytest.raises(ValueError, match="attempt_id"):
        ToolExecutionKey(invocation_id="invocation-1", attempt_id="")


def test_context_uses_execution_key_and_copies_metadata() -> None:
    metadata: dict[str, object] = {"trace": {"value": "before"}}
    context = _context(metadata)
    nested = metadata["trace"]
    assert isinstance(nested, dict)
    nested["value"] = "after"

    assert context.invocation_id == "invocation-1"
    assert context.attempt_id == "attempt-1"
    assert context.metadata["trace"] == {"value": "before"}
    assert "absolute Unix epoch" in (ToolContext.__doc__ or "")
    with pytest.raises(FrozenInstanceError):
        context.execution_key = _key("attempt-2")  # type: ignore[misc]


def test_context_deadline_uses_interoperable_json_integer_range() -> None:
    values = dict(
        execution_key=_key(),
        tool_id="forge.tool.test",
        implementation_id="fake",
        endpoint_id="fake.endpoint",
        operation="run",
    )
    assert ToolContext(**values, deadline_ms=MAX_SAFE_JSON_INTEGER).deadline_ms == (
        MAX_SAFE_JSON_INTEGER
    )
    with pytest.raises(ValueError, match="deadline_ms"):
        ToolContext(**values, deadline_ms=MAX_SAFE_JSON_INTEGER + 1)


def test_request_and_result_mapping_fields_are_defensive_copies() -> None:
    arguments: dict[str, object] = {"limits": {"maximum": 1.0}}
    outputs: dict[str, object] = {"objects": []}
    request = ToolRequest(arguments=arguments)
    result = ToolResult(status="succeeded", outputs=outputs)
    nested = arguments["limits"]
    assert isinstance(nested, dict)
    nested["maximum"] = 2.0
    outputs["objects"] = ["changed"]

    assert request.arguments["limits"] == {"maximum": 1.0}
    assert result.outputs["objects"] == []


def test_models_support_standard_dataclass_and_json_serialization() -> None:
    context = _context()

    serialized = asdict(context)

    assert serialized["execution_key"] == {
        "invocation_id": "invocation-1",
        "attempt_id": "attempt-1",
    }
    assert json.loads(json.dumps(serialized)) == serialized


def test_mapping_values_are_strict_bounded_json() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        ToolRequest(arguments={1: "invalid"})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="finite"):
        ToolResult(status="succeeded", outputs={"value": float("nan")})
    with pytest.raises(ValueError, match="interoperable range"):
        ToolRequest(arguments={"value": MAX_SAFE_JSON_INTEGER + 1})
    with pytest.raises(ValueError, match="Unicode scalar"):
        ToolRequest(arguments={"\ud800": "invalid"})
    with pytest.raises(TypeError, match="unsupported JSON value"):
        ToolEvent(type="progress", data={"value": object()})


def test_tool_result_terminal_error_invariants() -> None:
    error = ToolError(code="EXECUTOR_FAILED", message="executor failed")

    for status in ("succeeded", "cancelled", "stopped"):
        assert ToolResult(status=status).error is None  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="must not contain"):
            ToolResult(status=status, error=error)  # type: ignore[arg-type]

    for status in ("failed", "unknown"):
        with pytest.raises(ValueError, match="must contain"):
            ToolResult(status=status)  # type: ignore[arg-type]
        assert ToolResult(status=status, error=error).error is error  # type: ignore[arg-type]


def test_result_lookup_response_distinguishes_pending_available_and_not_found() -> None:
    result = ToolResult(status="succeeded", outputs={"value": 1})

    assert ToolResultResponse(status="pending").result is None
    assert ToolResultResponse(status="not_found").result is None
    assert ToolResultResponse(status="available", result=result).result is result

    with pytest.raises(ValueError, match="must contain"):
        ToolResultResponse(status="available")
    with pytest.raises(ValueError, match="only an available"):
        ToolResultResponse(status="pending", result=result)


def test_control_response_distinguishes_ack_from_terminal_state() -> None:
    accepted = ToolControlResponse(command="cancel", status="accepted")
    assert "means only" in (ToolControlResponse.__doc__ or "")
    assert accepted.status == "accepted"

    error = ToolError(code="CONTROL_REJECTED", message="cannot cancel")
    rejected = ToolControlResponse(
        command="cancel",
        status="rejected",
        error=error,
    )
    assert rejected.error is error

    with pytest.raises(ValueError, match="must contain"):
        ToolControlResponse(command="stop", status="rejected")
    with pytest.raises(ValueError, match="only a rejected"):
        ToolControlResponse(command="stop", status="unsupported", error=error)


def test_key_identifiers_and_active_invocations_are_validated() -> None:
    with pytest.raises(TypeError, match="execution_key"):
        ToolContext(
            execution_key="invocation-1",  # type: ignore[arg-type]
            tool_id="forge.tool.test",
            implementation_id="fake",
            endpoint_id="fake.endpoint",
            operation="run",
        )
    assert ToolAccepted(details={"queue": "default"}).details == {"queue": "default"}
    for active_invocations in (-1, MAX_SAFE_JSON_INTEGER + 1):
        with pytest.raises(ValueError, match="active_invocations"):
            EndpointStatus(
                endpoint_id="robot.arm",
                state="ready",
                active_invocations=active_invocations,
            )


@pytest.mark.parametrize(
    "event_type",
    [
        "progress",
        "heartbeat",
        "executor_completed",
        "executor_failed",
        "cancelled",
        "stopped",
    ],
)
def test_documented_event_types_are_accepted(event_type: ToolEventType) -> None:
    assert ToolEvent(type=event_type).type == event_type


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="event type"):
        ToolEvent(type="log")  # type: ignore[arg-type]


def test_execution_status_separates_executor_completion_from_runtime_success() -> None:
    status = ToolExecutionStatus(
        phase="completed",
        details={"executor_result": "completed"},
    )

    assert status.phase == "completed"
    assert "Runtime still owns" in (ToolExecutionStatus.__doc__ or "")


def test_terminal_execution_status_and_result_must_agree() -> None:
    error = ToolError(code="EXECUTOR_FAILED", message="failed")
    pairs = [
        (ToolExecutionStatus(phase="completed"), ToolResult(status="succeeded")),
        (
            ToolExecutionStatus(phase="failed", error=error),
            ToolResult(status="failed", error=error),
        ),
        (ToolExecutionStatus(phase="cancelled"), ToolResult(status="cancelled")),
        (ToolExecutionStatus(phase="stopped"), ToolResult(status="stopped")),
        (
            ToolExecutionStatus(phase="unknown", error=error),
            ToolResult(status="unknown", error=error),
        ),
    ]
    for status, result in pairs:
        validate_execution_result(status, result)

    with pytest.raises(ValueError, match="not terminal"):
        validate_execution_result(
            ToolExecutionStatus(phase="running"),
            ToolResult(status="succeeded"),
        )
    with pytest.raises(ValueError, match="requires result status"):
        validate_execution_result(
            ToolExecutionStatus(phase="completed"),
            ToolResult(status="stopped"),
        )


def test_failed_and_unknown_execution_status_require_structured_error() -> None:
    for phase in ("failed", "unknown"):
        with pytest.raises(ValueError, match=phase):
            ToolExecutionStatus(phase=phase)  # type: ignore[arg-type]

    error = ToolError(code="EXECUTOR_FAILED", message="Controller rejected goal")
    assert ToolExecutionStatus(phase="failed", error=error).error is error
    assert ToolExecutionStatus(phase="unknown", error=error).error is error
