from dataclasses import dataclass
from typing import List, Literal


@dataclass
class JointConfig:
    name: str
    # 关节读取模式："position"（位置型）、"prismatic"（直线型）
    mode: Literal["position", "prismatic"] = "position"
    # 适用范围："all"（通用），"sim"（仅仿真），"real"（仅实物）
    scope: Literal["all", "sim", "real"] = "all"


@dataclass
class ActuatorConfig:
    id: int
    name: str
    # 控制器控制模式："position"（位置控制）或 "velocity"（速度控制）或 "prismatic" （直线控制）
    control_mode: Literal["position", "velocity", "prismatic"]
    min_value: float = -3.14
    max_value: float = 3.14
    # 适用范围："all"（通用），"sim"（仅仿真），"real"（仅实物）
    scope: Literal["all", "sim", "real"] = "all"


@dataclass
class SensorConfig:
    name: str
    # 传感器类型："camera"（摄像头）或 "speed"（速度传感器）
    type: Literal["camera", "speed", "position"]
    # 适用范围："all"（通用），"sim"（仅仿真），"real"（仅实物）
    scope: Literal["all", "sim", "real"] = "all"
