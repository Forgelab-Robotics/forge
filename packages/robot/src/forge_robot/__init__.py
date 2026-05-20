"""forge_robots 通用驱动协议与基类。"""

from .port_tools import (
    STANDARD_PORT_COMMANDS,
    address_info,
    error_result,
    ok_result,
    print_json_result,
    role_info,
    unsupported_ok,
)

__all__ = [
    "ActuatorSpec",
    "BaseRobotDriver",
    "RobotArrowSchemaError",
    "RobotDriver",
    "STANDARD_PORT_COMMANDS",
    "address_info",
    "actuator_order",
    "clip_and_validate_position_action",
    "error_result",
    "ok_result",
    "print_json_result",
    "role_info",
    "run_dora_robot_node",
    "specs_by_name",
    "unsupported_ok",
    "validate_robot_control_arrow",
]


def __getattr__(name: str):
    if name in {
        "ActuatorSpec",
        "actuator_order",
        "clip_and_validate_position_action",
        "specs_by_name",
    }:
        from . import actuator_spec

        return getattr(actuator_spec, name)
    if name in {"RobotArrowSchemaError", "validate_robot_control_arrow"}:
        from . import arrow_validation

        return getattr(arrow_validation, name)
    if name == "run_dora_robot_node":
        from .node_runner import run_dora_robot_node

        return run_dora_robot_node
    if name in {"BaseRobotDriver", "RobotDriver"}:
        from . import robot_protocol

        return getattr(robot_protocol, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
