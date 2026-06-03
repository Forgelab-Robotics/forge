"""Shared helpers for robot device discovery CLI commands."""

from __future__ import annotations

import json
from typing import Any


STANDARD_DEVICE_COMMANDS = (
    "list-devices",
    "activate-devices",
    "test",
)


def address_info(
    *,
    name: str,
    address: str = "",
    status: bool = False,
    role: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a standard robot address object, preserving optional extras."""
    info: dict[str, Any] = {
        "name": name,
        "address": address,
        "status": bool(status),
    }
    if role is not None:
        info["role"] = role
    info.update({key: value for key, value in extra.items() if value is not None})
    return info


def ok_result(
    *,
    message: str = "",
    devices: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a standard successful JSON envelope."""
    result: dict[str, Any] = {
        "ok": True,
        "message": message,
    }
    if devices is not None:
        result["devices"] = devices
    result.update(extra)
    return result


def error_result(
    message: str,
    *,
    devices: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Create a standard error JSON envelope."""
    result: dict[str, Any] = {
        "ok": False,
        "message": message,
    }
    if devices is not None:
        result["devices"] = devices
    result.update(extra)
    return result


def unsupported_ok(
    message: str = "This command is not applicable for this robot",
    *,
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a successful response for unsupported/not applicable commands."""
    return ok_result(
        message=message,
        devices=[] if devices is None else devices,
    )


def print_json_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))
