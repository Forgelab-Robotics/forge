from __future__ import annotations

from typing import Any

from forge_robots_core import BaseActuator, BaseJoint, BaseRobot

from forge_robots_mujoco.driver import MuJoCoDriver


class MuJoCoRobot(BaseRobot):
    """
    MuJoCo scene robot (Robot + Driver merged).

    Represents the robot in a MuJoCo simulation scene. Use this for simulator
    nodes where the robot structure is defined by the scene XML.

    Example:
        import mujoco
        from forge_robots_mujoco import MuJoCoRobot

        model = mujoco.MjModel.from_xml_path("scene.xml")
        data = mujoco.MjData(model)

        joints = [...]
        actuators = [...]
        robot = MuJoCoRobot(
            model=model,
            data=data,
            joints=joints,
            actuators=actuators,
            prefix="robot1/",
        )

        robot.reset()
        state = robot.get_state(timestamp=0.0)
        robot.set_actuators(action)
    """

    def __init__(
        self,
        model: Any,
        data: Any,
        joints: list[BaseJoint],
        actuators: list[BaseActuator],
        prefix: str = "",
        name: str = "mujoco",
    ):
        """
        Initialize MuJoCo robot.

        Args:
            model: MuJoCo MjModel
            data: MuJoCo MjData (caller keeps this updated)
            joints: List of joints (from scene)
            actuators: List of actuators (from scene)
            prefix: Prefix for joint/actuator names in MuJoCo model
            name: Robot name
        """
        driver = MuJoCoDriver(
            model=model,
            data=data,
            joints=joints,
            actuators=actuators,
            prefix=prefix,
        )
        super().__init__(
            name=name,
            joints=joints,
            actuators=actuators,
            driver=driver,
        )
        self._model = model
        self._data = data

    def reset(self) -> None:
        """
        Reset robot to initial state (model qpos0, zero velocity).
        """
        self.driver.reset()
