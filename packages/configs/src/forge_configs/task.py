from __future__ import annotations

"""Core task config schema for Forge.

目标：
- 提供一份“任务级”配置（机器人、关节、相机、数据流），从中生成各节点所需的 YAML。
- 先满足当前 test_action 场景，保持字段命名和含义通用，便于后续扩展。
"""

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator
import yaml

from forge_configs.robot import RobotConfig


class CameraConfig(BaseModel):
    """相机配置（场景级）。

    - name: 模型中相机的完整名称（如 item_1/hand）
    - output: 数据流中的输出 ID（如 image/hand）
    - hz: 输出频率；None 表示随 tick
    """

    name: str
    output: str
    hz: Optional[float] = None


class SimulatorConfig(BaseModel):
    """Simulator 相关配置（目前主要是 MuJoCo 节点所需信息）。"""

    model_path: str
    image_format: Literal["raw", "jpeg", "png"] = "raw"
    image_jpeg_quality: int = 90
    cameras: List[CameraConfig] = Field(default_factory=list)

    @field_validator("image_jpeg_quality")
    @classmethod
    def _jpeg_quality_range(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("image_jpeg_quality 必须在 [1, 100] 范围内")
        return v


class TaskRobotConfig(BaseModel):
    """TaskRobot 节点相关配置（目前主要是要暴露/转发的图片 topic）。"""

    expose_images: List[str] = Field(default_factory=list)


class TaskConfig(BaseModel):
    """任务级统一配置。

    一份 TaskConfig 应该能够唯一决定：
    - simulator.yaml
    - task_robot.yaml
    - dataflow.yaml
    等节点配置文件的生成。
    """

    version: int = 1
    name: str = "default_task"
    tick_period_ms: int = 50

    robots: List[RobotConfig]
    simulator: SimulatorConfig
    task_robot: TaskRobotConfig = Field(default_factory=TaskRobotConfig)

    @field_validator("tick_period_ms")
    @classmethod
    def _positive_tick(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("tick_period_ms 必须为正整数")
        return v

    @property
    def joint_order(self) -> List[str]:
        """默认 joint 顺序：当前简单聚合第一个机器人的 joints。"""
        if not self.robots:
            return []
        return list(self.robots[0].joints)


def load_task(path: str | Path) -> TaskConfig:
    """从 YAML 文件加载 TaskConfig。"""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"任务配置文件格式无效: {p}")
    return TaskConfig.model_validate(data)
