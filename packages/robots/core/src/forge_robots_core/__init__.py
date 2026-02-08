"""Forge robots core module - base classes and utilities for robot control."""

from forge_robots_core.base import (
    BaseActuator,
    BaseJoint,
    BaseRobot,
    BaseRobotDriver,
    BaseSensor,
    BaseTaskRobot,
)
from forge_robots_core.config import ActuatorConfig, JointConfig, SensorConfig

# Re-export msgs types for convenience
from forge_msgs import ActuatorValue, JointValue, RobotCommand, RobotFeedback

__all__ = [
    # Base classes
    "BaseJoint",
    "BaseActuator",
    "BaseSensor",
    "BaseRobotDriver",
    "BaseRobot",
    "BaseTaskRobot",
    # Value types (from forge_msgs)
    "JointValue",
    "ActuatorValue",
    "RobotCommand",
    "RobotFeedback",
    # Config types
    "JointConfig",
    "ActuatorConfig",
    "SensorConfig",
]
