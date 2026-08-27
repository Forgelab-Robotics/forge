from __future__ import annotations

import asyncio

import pytest

from forge_tool import ToolEndpointError, ToolError


async def _reject_start() -> None:
    raise ToolEndpointError(
        ToolError(
            code="FORGE_ENDPOINT_BUSY",
            message="endpoint concurrency limit reached",
            retryable=True,
            details={"operation": "execute"},
        )
    )


def test_endpoint_error_preserves_structured_failure() -> None:
    with pytest.raises(ToolEndpointError) as captured:
        asyncio.run(_reject_start())

    error = captured.value.error
    assert error.code == "FORGE_ENDPOINT_BUSY"
    assert error.retryable is True
    assert error.details == {"operation": "execute"}
    assert str(captured.value) == (
        "FORGE_ENDPOINT_BUSY: endpoint concurrency limit reached"
    )


def test_endpoint_error_requires_tool_error() -> None:
    with pytest.raises(TypeError, match="ToolError"):
        ToolEndpointError(ValueError("invalid"))  # type: ignore[arg-type]
