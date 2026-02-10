"""MuJoCo simulator - receives RobotAction, produces RobotState."""

from __future__ import annotations

from typing import Any

import mujoco
from forge_msgs import ActuatorValue, RobotAction, RobotState
from forge_robots_core import BaseActuator, BaseJoint

from forge_common import get_logger

logger = get_logger(__name__)


class MuJoCoSimulator:
    """
    MuJoCo simulator node logic.

    Interfaces directly with MuJoCo model and data. Maps logical joint/actuator
    names to MuJoCo model names using an optional prefix.

    Use as a standalone Dora node: receives RobotAction from TaskRobot,
    runs physics step, sends RobotState to TaskRobot.

    Units:
    - Angles: radians
    - Distances: meters
    - Velocities: radians/s (for revolute joints) or meters/s (for prismatic)

    MuJoCo uses radians/meters natively, no conversion needed.
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
        Initialize MuJoCo simulator.

        Args:
            model: MuJoCo MjModel
            data: MuJoCo MjData (caller keeps this updated)
            joints: List of joints (if None, will be set by caller)
            actuators: List of actuators (if None, will be set by caller)
            prefix: Prefix for joint/actuator names in MuJoCo model
                   (e.g., "robot1/" for "robot1/joint1")
        """
        self._model = model
        self._data = data
        self._joints = joints or []
        self._actuators = actuators or []
        self._joint_map = {j.name: j for j in self._joints}
        self._actuator_map = {a.name: a for a in self._actuators}

        if prefix and not prefix.endswith("/"):
            prefix += "/"
        self._prefix = prefix

        logger.info(f"[MuJoCoSimulator] Initializing with prefix: '{prefix}'")

        self._qpos_addrs: dict[str, int] = {}
        self._ctrl_indices: dict[str, int] = {}

        for joint in self._joints:
            logical_name = joint.name
            prefixed_name = prefix + logical_name
            try:
                joint_id = mujoco.mj_name2id(
                    model, mujoco.mjtObj.mjOBJ_JOINT, prefixed_name
                )
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

        for actuator in self._actuators:
            logical_name = actuator.name
            prefixed_name = prefix + logical_name
            try:
                act_id = mujoco.mj_name2id(
                    model, mujoco.mjtObj.mjOBJ_ACTUATOR, prefixed_name
                )
                self._ctrl_indices[logical_name] = act_id
                logger.info(
                    f"  - Mapped Actuator '{logical_name}' -> '{prefixed_name}' "
                    f"with ctrl_idx: {act_id}"
                )
            except Exception:
                logger.warning(
                    f"  - WARNING: Actuator '{prefixed_name}' not found in mjModel."
                )

    @property
    def actuator_order(self) -> list[str]:
        """Actuator names in order (for RobotState / RobotAction)."""
        return [a.name for a in self._actuators]

    def reset(self) -> None:
        """
        Reset simulation state to model initial (qpos0, zero velocity).
        """
        for logical_name, addr in self._qpos_addrs.items():
            self._data.qpos[addr] = self._model.qpos0[addr]
        self._data.qvel[:] = 0
        logger.debug("[MuJoCoSimulator] Reset to initial state")

    def get_state(self) -> RobotState:
        """
        Get robot state from MuJoCo simulator.

        Returns RobotState in msgs format (radians/meters).
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

        return RobotState(actuators=actuator_values)

    def set_action(self, action: RobotAction) -> None:
        """
        Set actuator values in MuJoCo simulator.

        Input: RobotAction in msgs format (radians/meters).
        Values are clipped to actuator limits before applying.
        """
        safe_action = self._get_safe_action(action)
        ctrl = self._data.ctrl

        for logical_name, act_val in safe_action.actuators.items():
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

            if actuator.control_mode not in ("position", "prismatic", "velocity"):
                logger.warning(
                    f"Unsupported control mode '{actuator.control_mode}' "
                    f"for actuator '{logical_name}'. Skipping."
                )
                continue

            ctrl_index = self._ctrl_indices[logical_name]
            ctrl[ctrl_index] = act_val.value

    def _get_safe_action(self, action: RobotAction) -> RobotAction:
        """Clip action values to actuator limits."""
        safe_actuators = {}
        for name, act_val in action.actuators.items():
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
        return RobotAction(actuators=safe_actuators)
