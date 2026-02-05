from __future__ import annotations

from forge_robots_core import ActuatorValue, BaseRobot, BaseRobotDriver

from forge_common import get_logger

logger = get_logger(__name__)


class PiperRobot(BaseRobot):
    """
    Piper robot model.

    This class represents the Piper robot model and its behaviors.
    It can work with any compatible driver (real hardware, simulator, etc.):

    Example:
        # Real hardware driver
        from forge_robots_drivers_piper import PiperDriver
        real_driver = PiperDriver(port="can0")
        robot = PiperRobot(driver=real_driver)

        # Simulator driver (when available)
        # from forge_robots_drivers_piper_sim import PiperSimDriver
        # sim_driver = PiperSimDriver()
        # robot = PiperRobot(driver=sim_driver)
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
        self._home_position = [
            ActuatorValue(name="joint1", value=0.0, type="radians"),
            ActuatorValue(name="joint2", value=0.0, type="radians"),
            ActuatorValue(name="joint3", value=0.0, type="radians"),
            ActuatorValue(name="joint4", value=0.0, type="radians"),
            ActuatorValue(name="joint5", value=0.0, type="radians"),
            ActuatorValue(name="joint6", value=0.0, type="radians"),
            ActuatorValue(name="gripper", value=0.0, type="meters"),
        ]

    def reset(self) -> None:
        """
        Reset robot to home position.

        This is robot model logic - defines what "reset" means for Piper.
        The actual hardware control is handled by the driver.
        """
        self.set_actuators(self._home_position)
