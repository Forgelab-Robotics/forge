from __future__ import annotations

"""机器人与关节配置，mode/unit 与 forge_msgs 的 ActuatorValue 对齐。"""

from typing import List, Literal

from pydantic import BaseModel, field_validator

# 与 forge_msgs.value 保持一致，便于配置与消息互通
MODE_LITERAL = Literal["position", "velocity", "torque", "prismatic"]
UNIT_LITERAL = Literal[
    "radians",
    "millimeters",
    "meters",
    "radians/s",
    "millimeters/s",
    "meters/s",
    "Nm",
    "A",
    "unitless",
]


class JointConfig(BaseModel):
    """单个关节配置：名称、控制模式、单位。"""

    name: str
    mode: MODE_LITERAL = "position"
    unit: UNIT_LITERAL = "radians"


class ActuatorConfig(BaseModel):
    """单个执行器配置：名称、控制模式、单位。与 forge_msgs.ActuatorValue 的 mode/unit 对齐。"""

    name: str
    mode: MODE_LITERAL = "position"
    unit: UNIT_LITERAL = "radians"


class RobotConfig(BaseModel):
    """高层次机器人配置（场景级）。

    - id: 逻辑机器人 ID（如 robot_0）
    - prefix: 在仿真模型中的前缀（如 item_1/），由各 simulator 自行解释
    - joints: 该机器人的关节名（不含 prefix），如 joint1..gripper
    """

    id: str
    prefix: str = ""
    joints: List[str]

    @field_validator("joints")
    @classmethod
    def _non_empty_joints(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("RobotConfig.joints 不能为空")
        return v
