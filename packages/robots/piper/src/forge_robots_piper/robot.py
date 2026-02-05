from __future__ import annotations

from forge_robots_core.base import BaseRobot, RobotDriverProtocol
from forge_robots_core.value import ActuatorValue

from forge_common import get_logger

logger = get_logger(__name__)


class PiperRobot(BaseRobot):
    def __init__(
        self,
        driver: RobotDriverProtocol,
        name: str = "piper",
    ):
        super().__init__(
            name=name,
            joints=driver.joints,
            actuators=driver.actuators,
            driver=driver,
        )

    def reset(self) -> None:
        safe_positions = [
            ActuatorValue(name="joint1", value=0.0, type="radians"),
            ActuatorValue(name="joint2", value=0.0, type="radians"),
            ActuatorValue(name="joint3", value=0.0, type="radians"),
            ActuatorValue(name="joint4", value=0.0, type="radians"),
            ActuatorValue(name="joint5", value=0.0, type="radians"),
            ActuatorValue(name="joint6", value=0.0, type="radians"),
            ActuatorValue(name="gripper", value=0.0, type="meters"),
        ]
        self.set_actuators(safe_positions)
