from __future__ import annotations
import abc
from typing import Any, Protocol

from forge_robots_core.value import ActuatorValue, JointValue


class BaseJoint(abc.ABC):
    def __init__(self, name: str, mode: str):
        self.name = name
        self.mode = mode


class BaseActuator(abc.ABC):
    def __init__(
        self, name: str, id: int, control_mode: str, min_value: float, max_value: float
    ):
        self.name = name
        self.id = id
        self.control_mode = control_mode
        self.min_value = min_value
        self.max_value = max_value


class BaseSensor(abc.ABC):
    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def read(self) -> Any:
        pass


class RobotDriverProtocol(Protocol):
    """Protocol defining the driver interface. BaseRobot uses this to avoid depending on forge_robots_drivers_core."""

    joints: list[BaseJoint]
    actuators: list[BaseActuator]

    def get_joint_positions(self) -> list[JointValue]: ...
    def set_actuators(self, action: list[ActuatorValue]) -> None: ...
    def get_safe_actuator_values(
        self, action: list[ActuatorValue]
    ) -> list[ActuatorValue]: ...


class BaseRobot(abc.ABC):
    def __init__(
        self,
        name: str,
        joints: list[BaseJoint],
        actuators: list[BaseActuator],
        driver: RobotDriverProtocol,
    ):
        self.name: str = name
        self.joints: list[BaseJoint] = joints
        self.actuators: list[BaseActuator] = actuators
        self.driver: RobotDriverProtocol = driver

    def set_actuators(self, action: list[ActuatorValue]):
        self.driver.set_actuators(action)

    def get_joint_positions(self) -> list[JointValue]:
        return self.driver.get_joint_positions()

    def get_safe_action(self, action: list[ActuatorValue]) -> list[ActuatorValue]:
        return self.driver.get_safe_actuator_values(action)

    @abc.abstractmethod
    def reset(self):
        pass


class BaseTaskRobot(abc.ABC):
    def __init__(self, robots: list[BaseRobot]):
        self.robots = robots
