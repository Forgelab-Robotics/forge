"""Structural async contracts implemented by Forge ToolEndpoints."""

from __future__ import annotations

from typing import Protocol

from .models import (
    ToolAccepted,
    ToolContext,
    ToolControlResponse,
    ToolEvent,
    ToolExecutionKey,
    ToolExecutionStatus,
    ToolRequest,
    ToolResult,
    ToolResultResponse,
)


class ToolEventEmitter(Protocol):
    """Receives low-rate events for one bound execution attempt."""

    async def emit(self, event: ToolEvent) -> None:
        """Collect one executor event for the emitter's execution key."""
        ...


class QueryToolEndpoint(Protocol):
    """Endpoint operation that directly returns a terminal result."""

    async def query(
        self,
        request: ToolRequest,
        context: ToolContext,
    ) -> ToolResult:
        """Execute a query and return its authoritative terminal result."""
        ...


class ActionToolEndpoint(Protocol):
    """Endpoint operation that runs an independently tracked action.

    Every action exposes ``cancel``. When its descriptor is not cancellable, the
    method returns a control response with status ``unsupported``.
    """

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        """Accept an action without waiting for physical completion."""
        ...

    async def cancel(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        """Request cancellation, or return unsupported when not cancellable."""
        ...

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        """Return executor-side status for one action attempt."""
        ...

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        """Return whether the terminal result is pending, available, or absent."""
        ...


class SessionToolEndpoint(Protocol):
    """Endpoint operation that runs a stateful continuous execution.

    Every session exposes ``stop``. When its descriptor is not stoppable, the
    method returns a control response with status ``unsupported``.
    """

    async def start(
        self,
        request: ToolRequest,
        context: ToolContext,
        events: ToolEventEmitter,
    ) -> ToolAccepted:
        """Accept a session without waiting for it to terminate."""
        ...

    async def stop(
        self,
        key: ToolExecutionKey,
        reason: str | None = None,
    ) -> ToolControlResponse:
        """Request a normal stop, or return unsupported when not stoppable."""
        ...

    async def status(self, key: ToolExecutionKey) -> ToolExecutionStatus:
        """Return executor-side status for one session attempt."""
        ...

    async def result(self, key: ToolExecutionKey) -> ToolResultResponse:
        """Return whether the terminal result is pending, available, or absent."""
        ...
