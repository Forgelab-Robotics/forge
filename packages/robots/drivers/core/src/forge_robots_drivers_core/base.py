from __future__ import annotations

import abc

from forge_robots_core.base import BaseActuator, BaseJoint
from forge_robots_core.utils import ensure_safe_actuator_values
from forge_robots_core.value import ActuatorValue, JointValue


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
        return ensure_safe_actuator_values(action, self._actuator_map)
