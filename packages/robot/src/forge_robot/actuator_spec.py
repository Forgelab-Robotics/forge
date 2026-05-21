"""Common actuator metadata used by robot drivers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge_msgs import RobotAction
from forge_msgs.value import ActuatorValue

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


def actuator_order(specs: tuple[ActuatorSpec, ...]) -> list[str]:
    return [spec.name for spec in specs]


def specs_by_name(specs: tuple[ActuatorSpec, ...]) -> dict[str, ActuatorSpec]:
    return {spec.name: spec for spec in specs}


def clip_and_validate_action(
    action: RobotAction,
    specs: dict[str, ActuatorSpec],
) -> RobotAction:
    """根据执行器规格校验并限制动作值。

    支持不同控制模式（position、velocity、torque 等）的单位校验与数值限位。
    对 continuous 类型的关节，位置控制模式下自动免除位置裁剪。
    内部自动将历史不标准动作模式（prismatic）映射归一化为标准的 position 进行校验，确保健壮性。
    """
    actuators: dict[str, ActuatorValue] = {}
    for name, actuator in action.actuators.items():
        spec = specs.get(name)
        if spec is None:
            continue

        value = actuator.value
        raw_mode = actuator.mode

        # 兼容性语义映射：将历史不标准的 prismatic 模式归一化为标准的 position
        norm_mode = "position" if raw_mode == "prismatic" else raw_mode

        # 1. 位置控制模式
        if norm_mode == "position":
            if actuator.unit != spec.position_unit:
                raise ValueError(
                    f"actuator '{name}' 期望单位 {spec.position_unit}，收到 {actuator.unit}"
                )
            # 对 continuous 种类关节不进行位置裁剪
            if spec.kind != "continuous":
                if spec.min_position is not None:
                    value = max(value, spec.min_position)
                if spec.max_position is not None:
                    value = min(value, spec.max_position)

        # 2. 速度控制模式
        elif norm_mode == "velocity":
            if actuator.unit != spec.velocity_unit:
                raise ValueError(
                    f"actuator '{name}' 期望单位 {spec.velocity_unit}，收到 {actuator.unit}"
                )
            if spec.max_velocity is not None:
                value = max(min(value, spec.max_velocity), -spec.max_velocity)

        # 3. 力矩/电流控制模式
        elif norm_mode == "torque":
            if actuator.unit != spec.effort_unit:
                raise ValueError(
                    f"actuator '{name}' 期望单位 {spec.effort_unit}，收到 {actuator.unit}"
                )
            if spec.max_effort is not None:
                value = max(min(value, spec.max_effort), -spec.max_effort)

        actuators[name] = ActuatorValue(
            value=value,
            mode=actuator.mode,  # 保持其原始输入 mode 发出，确保不影响下游解析
            unit=actuator.unit,
        )
    return RobotAction(actuators=actuators)


def clip_and_validate_position_action(
    action: RobotAction,
    specs: dict[str, ActuatorSpec],
) -> RobotAction:
    """旧版位置裁剪校验的包装层，确保完美向前兼容。"""
    return clip_and_validate_action(action, specs)

