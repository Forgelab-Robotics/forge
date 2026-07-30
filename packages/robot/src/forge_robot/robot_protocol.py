"""机器人驱动协议与抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from forge_msgs import JointCommand, JointState, LocomotionCommand


@runtime_checkable
class RobotDriver(Protocol):
    """
    机器人驱动协议：所有 forge_robots 机器人驱动应实现此接口。

    用于与 task_robot、通用节点循环等统一对接；消息格式使用 forge_msgs 的
    JointState / JointCommand（含 to_arrow/from_arrow）。
    """

    def connect(self) -> None:
        """建立与硬件的连接并完成使能等初始化。"""
        ...

    def disconnect(self) -> None:
        """断开连接并释放资源。"""
        ...

    def get_state(self) -> JointState:
        """从硬件读取当前状态，转为 JointState（单位与 forge_msgs 约定一致）。"""
        ...

    def set_command(self, command: JointCommand) -> None:
        """下发 sparse 关节命令；只更新 name 中列出的执行器并做安全限位。"""
        ...


@runtime_checkable
class LocomotionRobotDriver(Protocol):
    """可选移动控制能力：支持平面机体系速度命令的 driver 实现此协议。"""

    def set_locomotion_command(self, command: LocomotionCommand) -> None:
        """下发平面移动速度命令到硬件；实现方应做限速和安全处理。"""
        ...


class BaseRobotDriver(ABC):
    """
    机器人驱动抽象基类，实现 RobotDriver 协议。

    子类需实现 connect、disconnect、get_state、set_command，
    并可选择实现 joint_order 以在节点侧统一获取顺序。
    """

    @property
    def joint_order(self) -> list[str]:
        """该机器人关节名称的固定顺序，用于校验和数组辅助转换。"""
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
    def get_state(self) -> JointState:
        """从硬件读取当前状态，转为 JointState。"""
        ...

    @abstractmethod
    def set_command(self, command: JointCommand) -> None:
        """下发 sparse 关节命令，未列出的执行器必须保持原目标。"""
        ...
