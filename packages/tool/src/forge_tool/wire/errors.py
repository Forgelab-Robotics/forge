"""Errors raised while validating or decoding the ToolEndpoint Wire Protocol."""

from __future__ import annotations


class ToolProtocolError(ValueError):
    """A stable protocol error with an optional document path."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        self.code = code
        self.message = message
        self.path = path
        location = f" at {path}" if path is not None else ""
        super().__init__(f"{code}{location}: {message}")
