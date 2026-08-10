from __future__ import annotations

import pytest

from forge_tool import (
    MAX_SAFE_JSON_INTEGER,
    ToolEndpointDescriptor,
    ToolOperationDescriptor,
)

PROTOCOL_VERSION = "forge.tool.endpoint/v1alpha1"


def test_valid_yolo_query_descriptor() -> None:
    descriptor = ToolEndpointDescriptor(
        protocol_version=PROTOCOL_VERSION,
        endpoint_id="vision.yolo",
        operations=(
            ToolOperationDescriptor(
                name="detect",
                semantics="query",
                max_concurrency=4,
            ),
        ),
    )

    assert descriptor.operations[0].semantics == "query"
    assert descriptor.operations[0].max_concurrency == 4


def test_valid_lerobot_session_descriptor() -> None:
    descriptor = ToolEndpointDescriptor(
        protocol_version=PROTOCOL_VERSION,
        endpoint_id="policy.lerobot",
        operations=(
            ToolOperationDescriptor(
                name="execute",
                semantics="session",
                stoppable=True,
                status_supported=True,
            ),
        ),
    )

    operation = descriptor.operations[0]
    assert operation.semantics == "session"
    assert operation.cancellable is False
    assert operation.stoppable is True
    assert operation.status_supported is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"protocol_version": ""}, "protocol_version"),
        ({"endpoint_id": ""}, "endpoint_id"),
        ({"operations": ()}, "must not be empty"),
    ],
)
def test_invalid_endpoint_descriptor(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "endpoint_id": "robot.arm",
        "operations": (
            ToolOperationDescriptor(
                name="move",
                semantics="action",
                status_supported=True,
            ),
        ),
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        ToolEndpointDescriptor(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_concurrency", [0, MAX_SAFE_JSON_INTEGER + 1])
def test_operation_descriptor_rejects_invalid_concurrency(
    max_concurrency: int,
) -> None:
    with pytest.raises(ValueError, match="max_concurrency"):
        ToolOperationDescriptor(
            name="move",
            semantics="action",
            status_supported=True,
            max_concurrency=max_concurrency,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"semantics": "query", "cancellable": True}, "query operations"),
        ({"semantics": "query", "stoppable": True}, "query operations"),
        ({"semantics": "query", "status_supported": True}, "query operations"),
        (
            {"semantics": "action", "stoppable": True, "status_supported": True},
            "must not be stoppable",
        ),
        ({"semantics": "action"}, "must support status"),
        (
            {"semantics": "session", "cancellable": True, "status_supported": True},
            "must not be cancellable",
        ),
        ({"semantics": "session"}, "must support status"),
    ],
)
def test_operation_descriptor_enforces_semantics_capability_matrix(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ToolOperationDescriptor(name="execute", **kwargs)  # type: ignore[arg-type]


def test_descriptor_rejects_duplicate_operation_names() -> None:
    with pytest.raises(ValueError, match="unique"):
        ToolEndpointDescriptor(
            protocol_version=PROTOCOL_VERSION,
            endpoint_id="vision.yolo",
            operations=(
                ToolOperationDescriptor(name="detect", semantics="query"),
                ToolOperationDescriptor(name="detect", semantics="query"),
            ),
        )
