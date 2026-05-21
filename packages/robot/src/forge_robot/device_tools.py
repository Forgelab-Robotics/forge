"""Shared helpers for robot device discovery CLI commands."""

from __future__ import annotations

import json
from typing import Any, Literal


DeviceCapability = Literal[
    "list_devices",
    "activate_devices",
    "check_devices",
    "test",
]

STANDARD_DEVICE_COMMANDS = (
    "list-devices",
    "activate-devices",
    "check-devices",
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
    capability: DeviceCapability,
    *,
    message: str = "",
    devices: list[dict[str, Any]] | None = None,
    supported: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "capability": capability,
        "supported": supported,
        "message": message,
    }
    if devices is not None:
        result["devices"] = devices
    result.update(extra)
    return result


def error_result(
    capability: DeviceCapability,
    message: str,
    *,
    devices: list[dict[str, Any]] | None = None,
    supported: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "capability": capability,
        "supported": supported,
        "message": message,
    }
    if devices is not None:
        result["devices"] = devices
    result.update(extra)
    return result


def unsupported_ok(
    capability: DeviceCapability,
    message: str | None = None,
    *,
    devices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return ok_result(
        capability,
        message=message or f"{capability} is not applicable for this robot",
        devices=(
            []
            if devices is None and capability in {"list_devices", "check_devices"}
            else devices
        ),
        supported=False,
    )


def print_json_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))
