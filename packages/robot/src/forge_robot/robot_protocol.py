"""机器人驱动协议与抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from forge_msgs import RobotAction, RobotState


@runtime_checkable
class RobotDriver(Protocol):
    """
    机器人驱动协议：所有 forge_robots 机器人驱动应实现此接口。

    用于与 task_robot、通用节点循环等统一对接；消息格式使用 forge_msgs 的
    RobotState / RobotAction（含 to_arrow/from_arrow）。
    """

    def connect(self) -> None:
        """建立与硬件的连接并完成使能等初始化。"""
        ...

    def disconnect(self) -> None:
        """断开连接并释放资源。"""
        ...

    def get_state(self) -> RobotState:
        """从硬件读取当前状态，转为 RobotState（单位与 forge_msgs 约定一致）。"""
        ...

    def set_actuators(self, action: RobotAction) -> None:
        """下发动作到硬件；实现方应做限位等安全处理。"""
        ...


class BaseRobotDriver(ABC):
    """
    机器人驱动抽象基类，实现 RobotDriver 协议。

    子类需实现 connect、disconnect、get_state、set_actuators，
    并可选择实现 actuator_order 以在节点侧统一获取顺序。
    """

    @property
    def actuator_order(self) -> list[str]:
        """该机器人执行器名称的固定顺序，用于 Arrow 序列化与 task_robot 配置。"""
        return []

    @abstractmethod
    def connect(self) -> None:
        """建立与硬件的连接并完成使能等初始化。"""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接并释放资源。"""
        ...

    @abstractmethod
    def get_state(self) -> RobotState:
        """从硬件读取当前状态，转为 RobotState。"""
        ...

    @abstractmethod
    def set_actuators(self, action: RobotAction) -> None:
        """下发动作到硬件。"""
        ...
