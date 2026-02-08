from __future__ import annotations
import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge_msgs import RobotCommand, RobotFeedback


class BaseJoint(abc.ABC):
    def __init__(self, name: str, mode: str):
        self.name = name
        self.mode = mode


class BaseActuator(abc.ABC):
    def __init__(
        self,
        name: str,
        id: int,
        control_mode: str,
        min_value: float,
        max_value: float,
        unit: str = "radians",
    ):
        self.name = name
        self.id = id
        self.control_mode = control_mode
        self.min_value = min_value
        self.max_value = max_value
        self.unit = unit


class BaseSensor(abc.ABC):
    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def read(self) -> object:
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
    def get_feedback(self, timestamp: float = 0.0) -> "RobotFeedback":
        """Return robot feedback (actuator state) in msgs format."""
        pass

    @abc.abstractmethod
    def set_actuators(self, command: "RobotCommand") -> None:
        """Set actuator values from command in msgs format."""
        pass

    def get_safe_command(self, command: "RobotCommand") -> "RobotCommand":
        """Return command with values clipped to actuator limits."""
        from forge_msgs import ActuatorValue, RobotCommand

        safe_actuators = {}
        for name, act_val in command.actuators.items():
            actuator = self._actuator_map.get(name)
            if not actuator:
                continue
            clipped_val = max(
                min(act_val.value, actuator.max_value), actuator.min_value
            )
            safe_actuators[name] = ActuatorValue(
                value=clipped_val,
                mode=act_val.mode,
                unit=act_val.unit,
            )
        return RobotCommand(timestamp=command.timestamp, actuators=safe_actuators)


class BaseRobot(abc.ABC):
    """
    Base class for robot models.

    Robot layer represents the robot model and its behaviors (reset strategy,
    kinematics, trajectory planning, etc.), while Driver layer handles hardware
    communication. Communication uses forge_msgs format (RobotFeedback, RobotCommand).
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

    def set_actuators(self, command: "RobotCommand") -> None:
        """Set actuator values via driver."""
        self.driver.set_actuators(command)

    def get_feedback(self, timestamp: float = 0.0) -> "RobotFeedback":
        """Get robot feedback (actuator state) from driver."""
        return self.driver.get_feedback(timestamp)

    def get_safe_command(self, command: "RobotCommand") -> "RobotCommand":
        """Get safe command (clipped to limits) via driver."""
        return self.driver.get_safe_command(command)

    @abc.abstractmethod
    def reset(self) -> None:
        """
        Reset robot to a safe state.

        This is robot model logic, not driver logic. Different robots
        may have different reset strategies.
        """
        pass


class BaseTaskRobot(abc.ABC):
    def __init__(self, robots: list[BaseRobot]):
        self.robots = robots
