"""forge_robots 通用驱动协议与基类。"""

from .device_tools import (
    STANDARD_DEVICE_COMMANDS,
    address_info,
    error_result,
    ok_result,
    print_json_result,
    unsupported_ok,
)

__all__ = [
    "ActuatorSpec",
    "BaseRobotDriver",
    "LocomotionRobotDriver",
    "LocomotionSpec",
    "RobotArrowSchemaError",
    "RobotDriver",
    "STANDARD_DEVICE_COMMANDS",
    "address_info",
    "clip_and_validate_command",
    "clip_and_validate_locomotion_command",
    "clip_and_validate_position_command",
    "joint_order",
    "error_result",
    "ok_result",
    "print_json_result",
    "run_dora_robot_node",
    "specs_by_name",
    "unsupported_ok",
    "validate_robot_control_arrow",
    "validate_robot_state_arrow",
]


def __getattr__(name: str):
    if name in {
        "ActuatorSpec",
        "clip_and_validate_command",
        "clip_and_validate_position_command",
        "joint_order",
        "specs_by_name",
    }:
        from . import actuator_spec

        return getattr(actuator_spec, name)
    if name in {
        "LocomotionSpec",
        "clip_and_validate_locomotion_command",
    }:
        from . import locomotion_spec

        return getattr(locomotion_spec, name)
    if name in {
        "RobotArrowSchemaError",
        "validate_robot_control_arrow",
        "validate_robot_state_arrow",
    }:
        from . import arrow_validation

        return getattr(arrow_validation, name)
    if name == "run_dora_robot_node":
        from .node_runner import run_dora_robot_node

        return run_dora_robot_node
    if name in {"BaseRobotDriver", "LocomotionRobotDriver", "RobotDriver"}:
        from . import robot_protocol

        return getattr(robot_protocol, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
