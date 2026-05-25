"""Common actuator metadata used by robot drivers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge_msgs import JointCommand

ActuatorKind = Literal["revolute", "continuous", "prismatic", "other"]
ControlMode = Literal["position", "velocity", "torque"]


@dataclass(frozen=True)
class ActuatorSpec:
    """Driver-facing actuator metadata.

    The fields describe the semantic contract of a robot actuator. Hardware
    specific SDK addresses or protocol IDs should stay in the concrete driver.
    """

    name: str
    kind: ActuatorKind
    mode: ControlMode = "position"
    position_unit: str | None = None
    velocity_unit: str | None = None
    acceleration_unit: str | None = None
    effort_unit: str | None = None
    min_position: float | None = None
    max_position: float | None = None
    max_velocity: float | None = None
    max_acceleration: float | None = None
    max_effort: float | None = None

    def __post_init__(self) -> None:
        # 基于 kind 智能推推导默认物理单位
        if self.position_unit is None:
            if self.kind in ("revolute", "continuous"):
                p_unit = "radians"
            elif self.kind == "prismatic":
                p_unit = "meters"
            else:
                p_unit = "unitless"
            object.__setattr__(self, "position_unit", p_unit)

        if self.velocity_unit is None:
            if self.kind in ("revolute", "continuous"):
                v_unit = "radians/s"
            elif self.kind == "prismatic":
                v_unit = "meters/s"
            else:
                v_unit = "unitless"
            object.__setattr__(self, "velocity_unit", v_unit)

        if self.acceleration_unit is None:
            if self.kind in ("revolute", "continuous"):
                a_unit = "radians/s^2"
            elif self.kind == "prismatic":
                a_unit = "meters/s^2"
            else:
                a_unit = "unitless"
            object.__setattr__(self, "acceleration_unit", a_unit)

        if self.effort_unit is None:
            if self.kind in ("revolute", "continuous"):
                e_unit = "Nm"
            else:
                e_unit = "unitless"
            object.__setattr__(self, "effort_unit", e_unit)


def joint_order(specs: tuple[ActuatorSpec, ...]) -> list[str]:
    return [spec.name for spec in specs]


def specs_by_name(specs: tuple[ActuatorSpec, ...]) -> dict[str, ActuatorSpec]:
    return {spec.name: spec for spec in specs}


def _clip_symmetric(value: float, limit: float | None) -> float:
    if limit is None:
        return value
    return max(min(value, limit), -limit)


def _field_by_name(names: list[str], values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    return dict(zip(names, values, strict=False))


def _ordered_field(names: list[str], values_by_name: dict[str, float]) -> list[float]:
    if not values_by_name:
        return []
    return [values_by_name[name] for name in names]


def clip_and_validate_command(
    command: JointCommand,
    specs: dict[str, ActuatorSpec],
) -> JointCommand:
    """根据执行器规格限制命令值。

    新消息不在 payload 中携带 unit/mode；单位约定来自 forge_msgs interface。
    对 continuous 类型的关节，位置字段不做位置裁剪。
    """
    names: list[str] = []
    position = _field_by_name(command.name, command.position)
    velocity = _field_by_name(command.name, command.velocity)
    effort = _field_by_name(command.name, command.effort)
    kp = _field_by_name(command.name, command.kp)
    kd = _field_by_name(command.name, command.kd)

    for name in command.name:
        spec = specs.get(name)
        if spec is None:
            continue
        names.append(name)

        if name in position:
            if spec.kind != "continuous":
                if spec.min_position is not None:
                    position[name] = max(position[name], spec.min_position)
                if spec.max_position is not None:
                    position[name] = min(position[name], spec.max_position)

        if name in velocity:
            velocity[name] = _clip_symmetric(velocity[name], spec.max_velocity)

        if name in effort:
            effort[name] = _clip_symmetric(effort[name], spec.max_effort)

    return JointCommand(
        name=names,
        position=_ordered_field(names, position),
        velocity=_ordered_field(names, velocity),
        effort=_ordered_field(names, effort),
        kp=_ordered_field(names, kp),
        kd=_ordered_field(names, kd),
    )


def clip_and_validate_position_command(
    command: JointCommand,
    specs: dict[str, ActuatorSpec],
) -> JointCommand:
    """位置命令裁剪包装。"""
    return clip_and_validate_command(command, specs)

