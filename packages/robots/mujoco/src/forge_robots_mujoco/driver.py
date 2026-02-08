from __future__ import annotations

from typing import Any

from forge_robots_core import (
    ActuatorValue,
    BaseActuator,
    BaseJoint,
    BaseRobotDriver,
    RobotCommand,
    RobotFeedback,
)

from forge_common import get_logger

logger = get_logger(__name__)


class MuJoCoDriver(BaseRobotDriver):
    """
    MuJoCo simulator driver (local/in-process).

    Interfaces directly with MuJoCo model and data. Maps logical joint/actuator
    names to MuJoCo model names using an optional prefix.

    Units:
    - Angles: radians
    - Distances: meters
    - Velocities: radians/s (for revolute joints) or meters/s (for prismatic joints)

    MuJoCo uses radians for angles and meters for distances, so no conversion is needed.
    """

    def __init__(
        self,
        model: Any,
        data: Any,
        joints: list[BaseJoint] | None = None,
        actuators: list[BaseActuator] | None = None,
        prefix: str = "",
    ):
        """
        Initialize MuJoCo driver.

        Args:
            model: MuJoCo MjModel
            data: MuJoCo MjData (caller keeps this updated)
            joints: List of joints (if None, will be set by caller)
            actuators: List of actuators (if None, will be set by caller)
            prefix: Prefix for joint/actuator names in MuJoCo model
                   (e.g., "robot1/" for "robot1/joint1")
        """
        super().__init__(
            type="mujoco",
            joints=joints or [],
            actuators=actuators or [],
        )
        self._model = model
        self._data = data

        if prefix and not prefix.endswith("/"):
            prefix += "/"

        logger.info(f"[MuJoCoDriver] Initializing with prefix: '{prefix}'")

        self._qpos_addrs: dict[str, int] = {}
        self._ctrl_indices: dict[str, int] = {}

        # Cache joint indices (use mujoco name2id)
        for joint in self.joints:
            logical_name = joint.name
            prefixed_name = prefix + logical_name
            try:
                joint_id = model.joint_name2id(prefixed_name)
                qpos_addr = model.jnt_qposadr[joint_id]
                self._qpos_addrs[logical_name] = qpos_addr
                logger.info(
                    f"  - Mapped Joint '{logical_name}' -> '{prefixed_name}' "
                    f"at qpos_addr: {qpos_addr}"
                )
            except Exception:
                logger.warning(
                    f"  - WARNING: Joint '{prefixed_name}' not found in mjModel."
                )

        # Cache actuator indices
        for actuator in self.actuators:
            logical_name = actuator.name
            prefixed_name = prefix + logical_name
            try:
                act_id = model.actuator_name2id(prefixed_name)
                self._ctrl_indices[logical_name] = act_id
                logger.info(
                    f"  - Mapped Actuator '{logical_name}' -> '{prefixed_name}' "
                    f"with ctrl_idx: {act_id}"
                )
            except Exception:
                logger.warning(
                    f"  - WARNING: Actuator '{prefixed_name}' not found in mjModel."
                )

    def connect(self) -> None:
        """MuJoCo driver doesn't need explicit connection."""
        pass

    def disconnect(self) -> None:
        """MuJoCo driver doesn't need explicit disconnection."""
        pass

    def reset(self) -> None:
        """
        Reset simulation state to model initial (qpos0, zero velocity).

        Resets qpos for controlled joints to model defaults, zeros all qvel.
        """
        for logical_name, addr in self._qpos_addrs.items():
            self._data.qpos[addr] = self._model.qpos0[addr]
        self._data.qvel[:] = 0
        logger.debug("[MuJoCoDriver] Reset to initial state")

    def get_feedback(self, timestamp: float = 0.0) -> RobotFeedback:
        """
        Get actuator feedback from MuJoCo simulator.

        Returns RobotFeedback in msgs format (radians/meters).
        """
        qpos = self._data.qpos
        actuator_values: dict[str, ActuatorValue] = {}

        for logical_name, addr in self._qpos_addrs.items():
            actuator = self._actuator_map.get(logical_name)
            joint = self._joint_map.get(logical_name)
            if actuator:
                unit = actuator.unit
            elif joint:
                unit = "radians" if joint.mode == "position" else "meters"
            else:
                logger.warning(f"Joint/actuator '{logical_name}' not found.")
                continue

            qpos_value = qpos[addr]
            actuator_values[logical_name] = ActuatorValue(
                value=float(qpos_value),
                mode="position",
                unit=unit,
            )

        return RobotFeedback(timestamp=timestamp, actuators=actuator_values)

    def set_actuators(self, command: RobotCommand) -> None:
        """
        Set actuator values in MuJoCo simulator.

        Input: RobotCommand in msgs format (radians/meters).
        """
        safe_cmd = self.get_safe_command(command)
        ctrl = self._data.ctrl

        for logical_name, act_val in safe_cmd.actuators.items():
            actuator = self._actuator_map.get(logical_name)
            if not actuator:
                logger.warning(
                    f"Actuator '{logical_name}' not found in actuator_map. Skipping."
                )
                continue

            if logical_name not in self._ctrl_indices:
                logger.warning(
                    f"Actuator '{logical_name}' not found in ctrl_indices. Skipping."
                )
                continue

            ctrl_value = act_val.value
            if actuator.control_mode not in ("position", "prismatic", "velocity"):
                logger.warning(
                    f"Unsupported control mode '{actuator.control_mode}' "
                    f"for actuator '{logical_name}'. Skipping."
                )
                continue

            ctrl_index = self._ctrl_indices[logical_name]
            ctrl[ctrl_index] = ctrl_value
