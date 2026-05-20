"""Common actuator metadata used by robot drivers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge_msgs import RobotAction
from forge_msgs.value import ActuatorValue

ActuatorKind = Literal["revolute", "prismatic", "gripper", "other"]
ControlMode = Literal["position", "velocity", "torque", "prismatic"]


@dataclass(frozen=True)
class ActuatorSpec:
    """Driver-facing actuator metadata.

    The fields describe the semantic contract of a robot actuator. Hardware
    specific SDK addresses or protocol IDs should stay in the concrete driver.
    """

    name: str
    kind: ActuatorKind
    mode: ControlMode = "position"
    position_unit: str = "radians"
    velocity_unit: str = "radians/s"
    acceleration_unit: str = "radians/s^2"
    effort_unit: str = "Nm"
    min_position: float | None = None
    max_position: float | None = None


def actuator_order(specs: tuple[ActuatorSpec, ...]) -> list[str]:
    return [spec.name for spec in specs]


def specs_by_name(specs: tuple[ActuatorSpec, ...]) -> dict[str, ActuatorSpec]:
    return {spec.name: spec for spec in specs}


def clip_and_validate_position_action(
    action: RobotAction,
    specs: dict[str, ActuatorSpec],
) -> RobotAction:
    """Keep known actuators, validate position units, and clip position limits."""
    actuators: dict[str, ActuatorValue] = {}
    for name, actuator in action.actuators.items():
        spec = specs.get(name)
        if spec is None:
            continue
        if actuator.unit != spec.position_unit:
            raise ValueError(
                f"actuator '{name}' 期望单位 {spec.position_unit}，收到 {actuator.unit}"
            )
        value = actuator.value
        if spec.min_position is not None:
            value = max(value, spec.min_position)
        if spec.max_position is not None:
            value = min(value, spec.max_position)
        actuators[name] = ActuatorValue(
            value=value,
            mode=actuator.mode,
            unit=actuator.unit,
        )
    return RobotAction(actuators=actuators)
