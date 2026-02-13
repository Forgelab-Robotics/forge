from __future__ import annotations

from typing import Literal

from forge_robots_core import BaseRobot

from forge_common import get_logger

from forge_robots_piper.driver import PiperDriver

logger = get_logger(__name__)


class PiperRobot(BaseRobot):
    """
    Piper robot model.

    Robot 层封装 Piper 模型与行为，内部使用 PiperDriver 进行硬件通信。
    **主从（master/slave）**：默认 role="slave"（从站），连接时使能机械臂，可读状态与下发控制；
    role="master"（主站）则仅连接不使能。
    TaskRobot → Robot → Driver

    Example:
        from forge_robots_piper import PiperRobot
        robot = PiperRobot(port="can0")
        state = robot.get_state()
        robot.set_actuators(action)
    """

    def __init__(
        self,
        port: str = "can0",
        role: Literal["master", "slave"] = "slave",
        is_follower: bool | None = None,
        auto_connect: bool = True,
        name: str = "piper",
    ):
        """
        Initialize Piper robot.

        Args:
            port: CAN port (e.g. "can0")
            role: 主从设置，默认 "slave"（从站，连接时使能）；"master"（主站）仅连接不使能。
            is_follower: 与 role 等价，保留兼容：True 等价 "slave"，False 等价 "master"。
            auto_connect: Connect on init
            name: Robot name
        """
        driver = PiperDriver(
            port=port,
            role=role,
            is_follower=is_follower,
            auto_connect=auto_connect,
        )
        super().__init__(
            name=name,
            joints=driver.joints,
            actuators=driver.actuators,
            driver=driver,
        )

    def reset(self) -> None:
        """
        Reset robot to safe position.

        Delegates to driver.move_to_safe_position() so safe position is implemented in one place.
        """
        self.driver.move_to_safe_position()
