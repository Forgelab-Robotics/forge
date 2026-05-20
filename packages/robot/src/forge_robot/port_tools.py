"""Shared helpers for robot port discovery CLI commands."""

from __future__ import annotations

import json
from typing import Any, Literal


PortCapability = Literal[
    "list_ports",
    "activate_ports",
    "check_ports",
    "check_role",
    "set_role",
    "test",
    "cancel_test",
]

STANDARD_PORT_COMMANDS = (
    "list-ports",
    "activate-ports",
    "check-ports",
    "check-role",
    "set-role",
    "test",
    "cancel-test",
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


def role_info(name: str, role: str) -> dict[str, str]:
    return {"name": name, "role": role}


def ok_result(
    capability: PortCapability,
    *,
    message: str = "",
    ports: list[dict[str, Any]] | None = None,
    roles: list[dict[str, str]] | None = None,
    supported: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "capability": capability,
        "supported": supported,
        "message": message,
    }
    if ports is not None:
        result["ports"] = ports
    if roles is not None:
        result["roles"] = roles
    result.update(extra)
    return result


def error_result(
    capability: PortCapability,
    message: str,
    *,
    ports: list[dict[str, Any]] | None = None,
    roles: list[dict[str, str]] | None = None,
    supported: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "capability": capability,
        "supported": supported,
        "message": message,
    }
    if ports is not None:
        result["ports"] = ports
    if roles is not None:
        result["roles"] = roles
    result.update(extra)
    return result


def unsupported_ok(
    capability: PortCapability,
    message: str | None = None,
    *,
    ports: list[dict[str, Any]] | None = None,
    roles: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return ok_result(
        capability,
        message=message or f"{capability} is not applicable for this robot",
        ports=[] if ports is None and capability in {"list_ports", "check_ports"} else ports,
        roles=[] if roles is None and capability == "check_role" else roles,
        supported=False,
    )


def print_json_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))
