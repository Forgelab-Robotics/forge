from __future__ import annotations

from typing import Any, Protocol

from forge_robots_core.base import BaseActuator, BaseJoint, BaseRobotDriver
from forge_robots_core.value import ActuatorValue, JointValue

from forge_common import get_logger

logger = get_logger(__name__)


class MuJoCoEnv(Protocol):
    """Protocol for MuJoCo environment interface."""

    model: Any  # mjModel

    def name2id(self, obj_type: str, name: str) -> int:
        """Get ID by name and type."""
        ...

    def get_data(self) -> Any:
        """Get MuJoCo data (with qpos and ctrl)."""
        ...


class MuJoCoDriver(BaseRobotDriver):
    """
    MuJoCo simulator driver.

    This driver interfaces with MuJoCo physics simulator through a DmControlEnv-like
    interface. It maps logical joint/actuator names to MuJoCo model names using
    an optional prefix.

    Units:
    - Angles: radians
    - Distances: meters
    - Velocities: radians/s (for revolute joints) or meters/s (for prismatic joints)

    MuJoCo uses radians for angles and meters for distances, so no conversion is needed.
    """

    def __init__(
        self,
        env: MuJoCoEnv,
        joints: list[BaseJoint] | None = None,
        actuators: list[BaseActuator] | None = None,
        prefix: str = "",
    ):
        """
        Initialize MuJoCo driver.

        Args:
            env: MuJoCo environment with model, name2id, and get_data methods
            joints: List of joints (if None, will be set by caller)
            actuators: List of actuators (if None, will be set by caller)
            prefix: Prefix for joint/actuator names in MuJoCo model
                   (e.g., "robot1/" for "robot1/joint1")
        """
        # Initialize with empty lists if not provided (will be set later)
        super().__init__(
            type="mujoco",
            joints=joints or [],
            actuators=actuators or [],
        )
        self.env = env

        if prefix and not prefix.endswith("/"):
            prefix += "/"

        logger.info(f"[MuJoCoDriver] Initializing with prefix: '{prefix}'")

        self._qpos_addrs: dict[str, int] = {}
        self._ctrl_indices: dict[str, int] = {}

        model = self.env.model

        # Cache joint indices
        for joint in self.joints:
            logical_name = joint.name
            prefixed_phys_joint_name = prefix + logical_name

            try:
                joint_id = self.env.name2id("JOINT", prefixed_phys_joint_name)
                qpos_addr = model.jnt_qposadr[joint_id]
                self._qpos_addrs[logical_name] = qpos_addr
                logger.info(
                    f"  - Mapped Joint '{logical_name}' -> '{prefixed_phys_joint_name}' "
                    f"at qpos_addr: {qpos_addr}"
                )
            except (KeyError, ValueError):
                logger.warning(
                    f"  - WARNING: Joint '{prefixed_phys_joint_name}' not found in mjModel. "
                    f"Cannot get its position."
                )

        # Cache actuator indices
        for actuator in self.actuators:
            logical_name = actuator.name
            prefixed_actuator_name = prefix + logical_name

            try:
                actuator_id = self.env.name2id("ACTUATOR", prefixed_actuator_name)
                self._ctrl_indices[logical_name] = actuator_id
                logger.info(
                    f"  - Mapped Actuator '{logical_name}' -> '{prefixed_actuator_name}' "
                    f"with ctrl_idx: {actuator_id}"
                )
            except (KeyError, ValueError):
                logger.warning(
                    f"  - WARNING: Actuator '{prefixed_actuator_name}' not found in mjModel. "
                    f"Cannot set its position."
                )

    def connect(self) -> None:
        """MuJoCo driver doesn't need explicit connection."""
        pass

    def disconnect(self) -> None:
        """MuJoCo driver doesn't need explicit disconnection."""
        pass

    def get_joint_positions(self) -> list[JointValue]:
        """
        Get joint positions from MuJoCo simulator.

        MuJoCo units: angles in radians, distances in meters.
        Returns values in unified units: angles in radians, distances in meters.

        Returns list of JointValue with logical names (without prefix).
        """
        qpos = self.env.get_data().qpos
        joint_positions = []

        for logical_name, addr in self._qpos_addrs.items():
            joint = self._joint_map.get(logical_name)
            if not joint:
                logger.warning(f"Joint '{logical_name}' not found in joint_map.")
                continue

            qpos_value = qpos[addr]

            if joint.mode == "position":
                # MuJoCo qpos for revolute joints is already in radians
                joint_positions.append(
                    JointValue(name=logical_name, value=qpos_value, type="radians")
                )
            elif joint.mode == "prismatic":
                # MuJoCo qpos for prismatic joints is already in meters
                joint_positions.append(
                    JointValue(name=logical_name, value=qpos_value, type="meters")
                )
            else:
                logger.warning(
                    f"Unsupported joint mode '{joint.mode}' for joint '{logical_name}'"
                )

        return joint_positions

    def set_actuators(self, action: list[ActuatorValue]) -> None:
        """
        Set actuator values in MuJoCo simulator.

        Input values should be in unified units:
        - Position control: radians (revolute) or meters (prismatic)
        - Velocity control: radians/s (revolute) or meters/s (prismatic)

        Args:
            action: List of ActuatorValue with logical names (without prefix)
        """
        # Get safe values (clipped to limits)
        safe_action = self.get_safe_actuator_values(action)

        # Execute control
        ctrl = self.env.get_data().ctrl

        for act_val in safe_action:
            logical_name = act_val.name
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

            # Convert value based on control mode
            # All values should be in unified units: angles in radians, distances in meters, velocities in rad/s or m/s
            # MuJoCo ctrl units match qpos units: radians for revolute, meters for prismatic
            if actuator.control_mode == "position":
                # Position control: radians for revolute joints, meters for prismatic joints
                # Input value is already in correct unit (radians or meters)
                ctrl_value = act_val.value
            elif actuator.control_mode == "prismatic":
                # Prismatic control: input value should be in meters
                ctrl_value = act_val.value
            elif actuator.control_mode == "velocity":
                # Velocity control: radians/s for revolute joints, meters/s for prismatic joints
                # Input value is already in correct unit
                ctrl_value = act_val.value
            else:
                logger.warning(
                    f"Unsupported control mode '{actuator.control_mode}' "
                    f"for actuator '{logical_name}'. Skipping."
                )
                continue

            ctrl_index = self._ctrl_indices[logical_name]
            ctrl[ctrl_index] = ctrl_value
