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

    Units (msgs interface):
    - Angles: radians
    - Distances: millimeters (prismatic)
    - Velocities: radians/s (revolute) or millimeters/s (prismatic)

    MuJoCo uses radians/meters internally; conversion to/from millimeters at boundary.
    """

    def __init__(
        self,
        model: Any,
        data: Any,
        joints: list[BaseJoint] | None = None,
        actuators: list[BaseActuator] | None = None,
        derived_state_cfg: dict[str, dict[str, Any]] | None = None,
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

        # 逻辑关节名 -> qpos 索引（由 joints 列表构建，保持向后兼容）
        self._qpos_addrs: dict[str, int] = {}
        # 物理 joint 名 -> qpos 索引（供派生状态使用，如 joint7/joint8）
        self._joint_qpos_addrs: dict[str, int] = {}
        # 逻辑 actuator 名 -> ctrl 索引
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
                self._joint_qpos_addrs[logical_name] = qpos_addr
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

        # 解析派生 actuator 状态配置（例如 gripper 由 joint7/joint8 合成）
        # 结构：{ actuator_name: { "joint_qpos_addrs": [int, ...], "expr": str|None, "scale": float } }
        self._derived_state_cfg: dict[str, dict[str, Any]] = {}
        if derived_state_cfg:
            for act_name, cfg in derived_state_cfg.items():
                joint_names = cfg.get("joint_names") or []
                expr = cfg.get("expr")
                scale = cfg.get("scale", 1.0)

                if not joint_names:
                    continue

                joint_qpos_addrs: list[int] = []
                for j_name in joint_names:
                    # 先看是否已有缓存
                    if j_name in self._joint_qpos_addrs:
                        joint_qpos_addrs.append(self._joint_qpos_addrs[j_name])
                        continue

                    prefixed_joint_name = prefix + j_name
                    try:
                        joint_id = mujoco.mj_name2id(
                            model, mujoco.mjtObj.mjOBJ_JOINT, prefixed_joint_name
                        )
                        qpos_addr = model.jnt_qposadr[joint_id]
                        self._joint_qpos_addrs[j_name] = qpos_addr
                        joint_qpos_addrs.append(qpos_addr)
                        logger.info(
                            "  - DerivedState: joint '%s' -> '%s' at qpos_addr: %d",
                            j_name,
                            prefixed_joint_name,
                            qpos_addr,
                        )
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "  - WARNING: DerivedState joint '%s' (prefixed '%s') "
                            "not found in mjModel.",
                            j_name,
                            prefixed_joint_name,
                        )

                if not joint_qpos_addrs:
                    continue

                self._derived_state_cfg[act_name] = {
                    "joint_qpos_addrs": joint_qpos_addrs,
                    "expr": expr,
                    "scale": float(scale),
                }

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

        Returns RobotState in msgs format (radians/millimeters).
        Prismatic joint values are converted from MuJoCo meters to millimeters.
        """
        qpos = self._data.qpos
        actuator_values: dict[str, ActuatorValue] = {}

        # 基础关节：按 joints 列表中的逻辑名直接读取 qpos
        for logical_name, addr in self._qpos_addrs.items():
            actuator = self._actuator_map.get(logical_name)
            joint = self._joint_map.get(logical_name)
            if actuator:
                unit = actuator.unit
            elif joint:
                unit = "radians" if joint.mode == "position" else "millimeters"
            else:
                logger.warning(f"Joint/actuator '{logical_name}' not found.")
                continue

            qpos_value = qpos[addr]
            if unit in ("millimeters", "millimeters/s"):
                value = float(qpos_value) * 1000.0
            else:
                value = float(qpos_value)
            actuator_values[logical_name] = ActuatorValue(
                value=value,
                mode="position",
                unit=unit,
            )

        # 派生 actuator（例如 gripper 由 joint7/joint8 合成）
        for act_name, cfg in self._derived_state_cfg.items():
            joint_qpos_addrs: list[int] = cfg.get("joint_qpos_addrs", [])
            if not joint_qpos_addrs:
                continue

            expr = cfg.get("expr")
            scale = float(cfg.get("scale", 1.0))

            values = [float(qpos[addr]) for addr in joint_qpos_addrs]
            if not values:
                continue

            if expr == "diff" and len(values) >= 2:
                raw = values[0] - values[1]
            elif expr == "sum":
                raw = sum(values)
            else:
                raw = values[0]

            value = raw * scale

            actuator = self._actuator_map.get(act_name)
            if actuator:
                mode = actuator.control_mode
                unit = actuator.unit
            else:
                mode = "position"
                unit = "radians"

            actuator_values[act_name] = ActuatorValue(
                value=value,
                mode=mode,
                unit=unit,
            )

        return RobotState(actuators=actuator_values)

    def set_action(self, action: RobotAction) -> None:
        """
        Set actuator values in MuJoCo simulator.

        Input: RobotAction in msgs format (radians/millimeters).
        Prismatic values are converted from millimeters to meters for MuJoCo.
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
            if act_val.unit in ("millimeters", "millimeters/s"):
                ctrl[ctrl_index] = act_val.value / 1000.0
            else:
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
