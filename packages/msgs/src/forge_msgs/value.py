from enum import IntEnum
from pydantic import BaseModel
from typing import Literal


class JointMode(IntEnum):
    """关节模式，用于 Arrow 列式格式的零拷贝序列化。"""

    position = 0
    velocity = 1
    torque = 2
    prismatic = 3


class JointUnit(IntEnum):
    """关节单位，用于 Arrow 列式格式的零拷贝序列化。"""

    radians = 0
    meters = 1
    radians_s = 2
    meters_s = 3
    Nm = 4
    A = 5


MODE_STR_TO_INT = {
    "position": JointMode.position,
    "velocity": JointMode.velocity,
    "torque": JointMode.torque,
    "prismatic": JointMode.prismatic,
}
MODE_INT_TO_STR = {v: k for k, v in MODE_STR_TO_INT.items()}

UNIT_STR_TO_INT = {
    "radians": JointUnit.radians,
    "meters": JointUnit.meters,
    "radians/s": JointUnit.radians_s,
    "meters/s": JointUnit.meters_s,
    "Nm": JointUnit.Nm,
    "A": JointUnit.A,
}
UNIT_INT_TO_STR = {v: k for k, v in UNIT_STR_TO_INT.items()}


class JointValue(BaseModel):
    value: float
    mode: Literal["position", "velocity", "torque", "prismatic"]
    unit: Literal["radians", "meters", "radians/s", "meters/s", "Nm", "A"]


class ActuatorValue(BaseModel):
    value: float
    mode: Literal["position", "velocity", "torque", "prismatic"]
    unit: Literal["radians", "meters", "radians/s", "meters/s", "Nm", "A"]
