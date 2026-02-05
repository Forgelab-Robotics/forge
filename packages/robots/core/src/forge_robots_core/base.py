from __future__ import annotations
import abc
from typing import Any

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


class BaseRobotDriver(abc.ABC):
    def __init__(
        self,
        joints: list[BaseJoint],
        actuators: list[BaseActuator],
        type: str,
    ):
        self.type = type
        self.joints = joints
        self.actuators = actuators
        self._joint_map = {j.name: j for j in joints}
        self._actuator_map = {a.name: a for a in actuators}

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    @abc.abstractmethod
    def get_joint_positions(self) -> list[JointValue]:
        pass

    @abc.abstractmethod
    def set_actuators(self, action: list[ActuatorValue]) -> None:
        pass

    def get_safe_actuator_values(
        self, action: list[ActuatorValue]
    ) -> list[ActuatorValue]:
        safe_action = []
        for val in action:
            actuator = self._actuator_map.get(val.name)
            if not actuator:
                continue
            clipped_val = max(min(val.value, actuator.max_value), actuator.min_value)
            safe_action.append(
                ActuatorValue(name=val.name, value=clipped_val, type=val.type)
            )
        return safe_action


class BaseRobot(abc.ABC):
    """
    Base class for robot models.

    Robot layer represents the robot model and its behaviors (reset strategy,
    kinematics, trajectory planning, etc.), while Driver layer handles hardware
    communication. This separation allows:

    - Driver switching: Same robot model can work with different drivers
      (real hardware, simulator, mock, etc.)
    - Model logic: Robot-specific behaviors stay in Robot layer, independent
      of hardware implementation
    - Future extension: Easy to add kinematics, trajectory planning, etc.
      without touching driver code
    """

    def __init__(
        self,
        name: str,
        joints: list[BaseJoint],
        actuators: list[BaseActuator],
        driver: BaseRobotDriver,
    ):
        self.name: str = name
        self.joints: list[BaseJoint] = joints
        self.actuators: list[BaseActuator] = actuators
        self.driver: BaseRobotDriver = driver

    def set_actuators(self, action: list[ActuatorValue]):
        """Set actuator values via driver."""
        self.driver.set_actuators(action)

    def get_joint_positions(self) -> list[JointValue]:
        """Get joint positions from driver."""
        return self.driver.get_joint_positions()

    def get_safe_action(self, action: list[ActuatorValue]) -> list[ActuatorValue]:
        """Get safe actuator values (clipped to limits) via driver."""
        return self.driver.get_safe_actuator_values(action)

    @abc.abstractmethod
    def reset(self):
        """
        Reset robot to a safe state.

        This is robot model logic, not driver logic. Different robots
        may have different reset strategies.
        """
        pass


class BaseTaskRobot(abc.ABC):
    def __init__(self, robots: list[BaseRobot]):
        self.robots = robots
