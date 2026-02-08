from __future__ import annotations

from forge_robots_core import ActuatorValue, BaseRobot, BaseRobotDriver, RobotCommand

from forge_common import get_logger

logger = get_logger(__name__)


class PiperRobot(BaseRobot):
    """
    Piper robot model.

    This class represents the Piper robot model and its behaviors.
    It can work with any compatible driver (real hardware, simulator, etc.):

    Example:
        # Real hardware driver (same package)
        from forge_robots_piper import PiperDriver, PiperRobot
        driver = PiperDriver(port="can0")
        robot = PiperRobot(driver=driver)

        # Simulator driver (MuJoCo)
        from forge_robots_piper import PiperRobot
        from forge_robots_mujoco import MuJoCoDriver
        driver = MuJoCoDriver(model=model, data=data, joints=..., actuators=...)
        robot = PiperRobot(driver=driver)
    """

    def __init__(
        self,
        driver: BaseRobotDriver,
        name: str = "piper",
    ):
        """
        Initialize Piper robot with a driver.

        Args:
            driver: Robot driver (hardware, simulator, etc.)
            name: Robot name
        """
        super().__init__(
            name=name,
            joints=driver.joints,
            actuators=driver.actuators,
            driver=driver,
        )
        # Robot model can define model-specific attributes
        # (e.g., home position, workspace limits, etc.)
        self._home_command = RobotCommand(
            timestamp=0.0,
            actuators={
                "joint1": ActuatorValue(value=0.0, mode="position", unit="radians"),
                "joint2": ActuatorValue(value=0.0, mode="position", unit="radians"),
                "joint3": ActuatorValue(value=0.0, mode="position", unit="radians"),
                "joint4": ActuatorValue(value=0.0, mode="position", unit="radians"),
                "joint5": ActuatorValue(value=0.0, mode="position", unit="radians"),
                "joint6": ActuatorValue(value=0.0, mode="position", unit="radians"),
                "gripper": ActuatorValue(value=0.0, mode="position", unit="meters"),
            },
        )

    def reset(self) -> None:
        """
        Reset robot to home position.

        This is robot model logic - defines what "reset" means for Piper.
        The actual hardware control is handled by the driver.
        """
        self.set_actuators(self._home_command)
