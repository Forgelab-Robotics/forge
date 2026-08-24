"""Structured exceptions raised while processing ToolEndpoint operations."""

from __future__ import annotations

from .models import ToolError


class ToolEndpointError(RuntimeError):
    """A structured invoke rejection raised before execution is accepted.

    Endpoint implementations must not use this exception after execution or side
    effects begin. Query execution failures are terminal ``ToolResult`` values; protocol
    and transport failures use ``tool.error``.
    """

    def __init__(self, error: ToolError) -> None:
        if not isinstance(error, ToolError):
            raise TypeError("error must be a ToolError")
        self.error = error
        super().__init__(f"{error.code}: {error.message}")
