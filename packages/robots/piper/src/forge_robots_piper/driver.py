from __future__ import annotations

import math
import time
from typing import Literal

from forge_robots_core import (
    ActuatorValue,
    BaseActuator,
    BaseJoint,
    BaseRobotDriver,
    RobotAction,
    RobotState,
)
from piper_sdk import C_PiperInterface_V2

from forge_common import get_logger

logger = get_logger(__name__)


def _default_joints() -> list[BaseJoint]:
    return [
        BaseJoint(name="joint1", mode="position"),
        BaseJoint(name="joint2", mode="position"),
        BaseJoint(name="joint3", mode="position"),
        BaseJoint(name="joint4", mode="position"),
        BaseJoint(name="joint5", mode="position"),
        BaseJoint(name="joint6", mode="position"),
        BaseJoint(name="gripper", mode="position"),
    ]


def _default_actuators() -> list[BaseActuator]:
    return [
        BaseActuator(
            name="joint1",
            id=1,
            control_mode="position",
            min_value=-2.618,
            max_value=2.618,
            unit="radians",
        ),
        BaseActuator(
            name="joint2",
            id=2,
            control_mode="position",
            min_value=0,
            max_value=3.140,
            unit="radians",
        ),
        BaseActuator(
            name="joint3",
            id=3,
            control_mode="position",
            min_value=-2.967,
            max_value=0,
            unit="radians",
        ),
        BaseActuator(
            name="joint4",
            id=4,
            control_mode="position",
            min_value=-1.745,
            max_value=1.745,
            unit="radians",
        ),
        BaseActuator(
            name="joint5",
            id=5,
            control_mode="position",
            min_value=-1.320,
            max_value=1.320,
            unit="radians",
        ),
        BaseActuator(
            name="joint6",
            id=6,
            control_mode="position",
            min_value=-2.094,
            max_value=2.094,
            unit="radians",
        ),
        BaseActuator(
            name="gripper",
            id=7,
            control_mode="position",
            min_value=0.0,
            max_value=105.0,
            unit="millimeters",
        ),
    ]


class PiperDriver(BaseRobotDriver):
    """
    Piper robot hardware driver.

    This driver interfaces with Piper robot hardware via CAN bus using piper-sdk.
    **主从（master/slave）**：通过 role 设置。默认 role="slave"（从站），连接后使能机械臂（EnablePiper），可正常读状态与下发控制；
    role="master"（主站）则仅连接、不使能，机械臂不会动，通常仅用于端口探测等场景。

    It converts between hardware-specific units and unified units.

    Units:
    - Angles: radians (converted from hardware units: degrees * 1000)
    - Distances: millimeters (prismatic / gripper, same as hardware scale)
    - Velocities: radians/s (for revolute joints) or millimeters/s (for prismatic joints)

    Hardware units:
    - Joint angles: degrees * ANGLE_SCALE (where ANGLE_SCALE = 1000.0)
    - Gripper: millimeters * GRIPPER_SCALE (where GRIPPER_SCALE = 1000.0)
    """

    ANGLE_SCALE = 1000.0
    GRIPPER_SCALE = 1000.0

    # MasterSlaveConfig linkage_config: 0x00 无效, 0xFA 示教输入臂(主), 0xFC 运动输出臂(从)
    _LINKAGE_MASTER = 0xFA
    _LINKAGE_SLAVE = 0xFC

    def __init__(
        self,
        joints: list[BaseJoint] | None = None,
        actuators: list[BaseActuator] | None = None,
        port: str = "can0",
        role: Literal["master", "slave"] = "slave",
        is_follower: bool | None = None,
        auto_connect: bool = True,
    ):
        """
        Args:
            role: 主从设置。"slave"（从站）默认，连接后使能机械臂，可读状态与控制；
                "master"（主站）仅连接不使能，机械臂不会动。
            is_follower: 与 role 等价，保留兼容：True 等价 role="slave"，False 等价 role="master"。
                若同时传入，以 role 为准。
        """
        joints = joints or _default_joints()
        actuators = actuators or _default_actuators()
        super().__init__(type="piper", joints=joints, actuators=actuators)
        if role == "master":
            self.is_follower = False
        elif is_follower is not None:
            self.is_follower = is_follower
        else:
            self.is_follower = True
        self.role: Literal["master", "slave"] = (
            "slave" if self.is_follower else "master"
        )
        self.port = port
        self.bus: C_PiperInterface_V2 | None = None

        if auto_connect:
            self.connect()

    def connect(self) -> None:
        if self.bus is not None:
            logger.warning("Robot is already connected.")
            return

        self.bus = C_PiperInterface_V2(self.port)
        logger.info(f"Connecting to Piper robot at port {self.port}...")
        self.bus.ConnectPort()

        # 随动主从模式：主臂 0xFA(示教输入臂)，从臂 0xFC(运动输出臂)；偏移 0 表示单臂/默认
        linkage = self._LINKAGE_SLAVE if self.is_follower else self._LINKAGE_MASTER
        self.bus.MasterSlaveConfig(linkage, 0, 0, 0)

        if self.is_follower:
            self._connect_follower_mode()
            logger.info("Successfully connected and enabled the robot (slave).")
        else:
            self._connect_master_mode()
            logger.info("Successfully connected (master, not enabled).")

    def _connect_follower_mode(self) -> None:
        time.sleep(0.5)
        self.bus.ModeCtrl(0x01, 0x01, 30, 0x00)
        time.sleep(0.5)
        logger.info("Enabling the robot in follower mode...")

        while not self.bus.EnablePiper():
            time.sleep(0.01)

        self.bus.EnableArm(7)

        self.move_to_home_position()
        time.sleep(2)

    def move_to_home_position(self) -> None:
        """
        将关节与夹爪移动到 Home 位（全 0）。
        用于连接后的初始化。
        """
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")
        logger.info("Moving robot to home position (all 0)...")
        self.bus.MotionCtrl_2(0x01, 0x01, 30, 0x00)
        self.bus.JointCtrl(0, 0, 0, 0, 0, 0)
        self.bus.GripperCtrl(0, 1000, 0x01, 0)

    def move_to_rest_position(self) -> None:
        """
        将关节与夹爪移动到休息位（防摔姿态）。
        joint5 设置为 0.48 弧度。
        """
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")
        logger.info("Moving robot to rest position (j5=0.48 rad)...")
        self.bus.MotionCtrl_2(0x01, 0x01, 30, 0x00)
        # 0.48 rad 约等于 27.5 度
        j5_hardware = int(math.degrees(0.4) * self.ANGLE_SCALE)
        self.bus.JointCtrl(0, 0, 0, 0, j5_hardware, 0)
        self.bus.GripperCtrl(0, 1000, 0x01, 0)

    def _connect_master_mode(self) -> None:
        time.sleep(1)
        logger.info("Robot configured in master mode.")

    def disconnect(self) -> None:
        if self.bus is None:
            logger.warning("Robot is not connected.")
            return

        if self.is_follower:
            logger.info("Safety sequence: Moving to rest position before disable...")
            try:
                self.move_to_rest_position()
                time.sleep(2)  # 等待回位动作完成
            except Exception as e:
                logger.error(f"Failed to move to rest position: {e}")

        logger.info("Disabling and disconnecting from the robot...")
        self.bus.DisablePiper()
        self.bus.DisconnectPort()
        self.bus = None
        logger.info("Disconnected from the robot.")

    def reset(self) -> None:
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")

        logger.info("Starting homing sequence...")
        time.sleep(3)

        self.bus.MotionCtrl_1(0x02, 0, 0)
        self.bus.MotionCtrl_2(0, 0, 0, 0x00)

        logger.info(
            "Homing command sent. The robot will now move to its home position."
        )
        time.sleep(1)
        logger.info("Homing sequence should be completed.")

    def get_state(self) -> RobotState:
        """
        Get robot state from Piper hardware.

        Converts hardware units to unified units (radians/millimeters).
        Returns RobotState in msgs format.
        """
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")

        if self.is_follower:
            joints = self.bus.GetArmJointMsgs().joint_state
            gripper = self.bus.GetArmGripperMsgs().gripper_state
        else:
            joints = self.bus.GetArmJointCtrl().joint_ctrl
            gripper = self.bus.GetArmGripperCtrl().gripper_ctrl

        actuator_values = {
            "joint1": ActuatorValue(
                value=math.radians(joints.joint_1 / self.ANGLE_SCALE),
                mode="position",
                unit="radians",
            ),
            "joint2": ActuatorValue(
                value=math.radians(joints.joint_2 / self.ANGLE_SCALE),
                mode="position",
                unit="radians",
            ),
            "joint3": ActuatorValue(
                value=math.radians(joints.joint_3 / self.ANGLE_SCALE),
                mode="position",
                unit="radians",
            ),
            "joint4": ActuatorValue(
                value=math.radians(joints.joint_4 / self.ANGLE_SCALE),
                mode="position",
                unit="radians",
            ),
            "joint5": ActuatorValue(
                value=math.radians(joints.joint_5 / self.ANGLE_SCALE),
                mode="position",
                unit="radians",
            ),
            "joint6": ActuatorValue(
                value=math.radians(joints.joint_6 / self.ANGLE_SCALE),
                mode="position",
                unit="radians",
            ),
            "gripper": ActuatorValue(
                value=gripper.grippers_angle / self.GRIPPER_SCALE,
                mode="position",
                unit="millimeters",
            ),
        }
        return RobotState(actuators=actuator_values)

    def set_actuators(self, action: RobotAction) -> None:
        """
        Set actuator values on Piper hardware.

        Input: RobotAction in msgs format (radians/millimeters).
        Converts to hardware units for CAN bus.
        """
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")

        safe_action = self.get_safe_action(action)
        action_dict = {name: act.value for name, act in safe_action.actuators.items()}

        joint_1 = int(math.degrees(action_dict.get("joint1", 0.0)) * self.ANGLE_SCALE)
        joint_2 = int(math.degrees(action_dict.get("joint2", 0.0)) * self.ANGLE_SCALE)
        joint_3 = int(math.degrees(action_dict.get("joint3", 0.0)) * self.ANGLE_SCALE)
        joint_4 = int(math.degrees(action_dict.get("joint4", 0.0)) * self.ANGLE_SCALE)
        joint_5 = int(math.degrees(action_dict.get("joint5", 0.0)) * self.ANGLE_SCALE)
        joint_6 = int(math.degrees(action_dict.get("joint6", 0.0)) * self.ANGLE_SCALE)
        gripper = int(action_dict.get("gripper", 0.0) * self.GRIPPER_SCALE)

        self.bus.MotionCtrl_2(0x01, 0x01, 100, 0x00)
        self.bus.JointCtrl(joint_1, joint_2, joint_3, joint_4, joint_5, joint_6)
        self.bus.GripperCtrl(abs(gripper), 1000, 0x01, 0)
