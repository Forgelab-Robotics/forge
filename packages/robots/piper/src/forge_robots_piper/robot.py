from __future__ import annotations

from forge_robots_core.base import BaseActuator, BaseJoint, BaseRobot
from forge_robots_core.value import ActuatorValue

from forge_robots_piper.driver import PiperDriver

from forge_common import get_logger

logger = get_logger(__name__)


class PiperRobot(BaseRobot):
    def __init__(
        self,
        name: str = "piper",
        port: str = "can0",
        is_follower: bool = True,
        auto_connect: bool = True,
    ):
        joints = self._create_joints()
        actuators = self._create_actuators()
        driver = PiperDriver(
            joints=joints,
            actuators=actuators,
            port=port,
            is_follower=is_follower,
            auto_connect=auto_connect,
        )
        super().__init__(name=name, joints=joints, actuators=actuators, driver=driver)

    @staticmethod
    def _create_joints() -> list[BaseJoint]:
        return [
            BaseJoint(name="joint1", mode="position"),
            BaseJoint(name="joint2", mode="position"),
            BaseJoint(name="joint3", mode="position"),
            BaseJoint(name="joint4", mode="position"),
            BaseJoint(name="joint5", mode="position"),
            BaseJoint(name="joint6", mode="position"),
            BaseJoint(name="gripper", mode="position"),
        ]

    @staticmethod
    def _create_actuators() -> list[BaseActuator]:
        return [
            BaseActuator(
                name="joint1",
                id=1,
                control_mode="position",
                min_value=-3.14159,
                max_value=3.14159,
            ),
            BaseActuator(
                name="joint2",
                id=2,
                control_mode="position",
                min_value=-3.14159,
                max_value=3.14159,
            ),
            BaseActuator(
                name="joint3",
                id=3,
                control_mode="position",
                min_value=-3.14159,
                max_value=3.14159,
            ),
            BaseActuator(
                name="joint4",
                id=4,
                control_mode="position",
                min_value=-3.14159,
                max_value=3.14159,
            ),
            BaseActuator(
                name="joint5",
                id=5,
                control_mode="position",
                min_value=-3.14159,
                max_value=3.14159,
            ),
            BaseActuator(
                name="joint6",
                id=6,
                control_mode="position",
                min_value=-3.14159,
                max_value=3.14159,
            ),
            BaseActuator(
                name="gripper",
                id=7,
                control_mode="position",
                min_value=0.0,
                max_value=0.1,
            ),
        ]

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
