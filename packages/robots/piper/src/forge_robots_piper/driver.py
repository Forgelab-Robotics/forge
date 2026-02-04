from __future__ import annotations

import math
import time

from forge_robots_core.base import BaseActuator, BaseJoint, BaseRobotDriver
from forge_robots_core.value import JointValue, ActuatorValue
from piper_sdk import C_PiperInterface_V2

from forge_common import get_logger

logger = get_logger(__name__)


class PiperDriver(BaseRobotDriver):
    ANGLE_SCALE = 1000.0
    GRIPPER_SCALE = 1000.0

    def __init__(
        self,
        joints: list[BaseJoint],
        actuators: list[BaseActuator],
        port: str = "can0",
        is_follower: bool = True,
        auto_connect: bool = True,
    ):
        super().__init__(type="piper", joints=joints, actuators=actuators)
        self.is_follower = is_follower
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

        if self.is_follower:
            self._connect_follower_mode()
        else:
            self._connect_master_mode()

        logger.info("Successfully connected and enabled the robot.")

    def _connect_follower_mode(self) -> None:
        time.sleep(1)
        logger.info("Enabling the robot in follower mode...")

        while not self.bus.EnablePiper():
            time.sleep(0.01)

        self.bus.EnableArm(7)

        logger.info("Moving robot to safe position...")
        self.bus.GripperCtrl(0, 1000, 0x01, 0)
        time.sleep(2)

    def _connect_master_mode(self) -> None:
        time.sleep(1)
        logger.info("Robot configured in master mode.")

    def disconnect(self) -> None:
        if self.bus is None:
            logger.warning("Robot is not connected.")
            return

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

    def get_joint_positions(self) -> list[JointValue]:
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")

        if self.is_follower:
            joints = self.bus.GetArmJointMsgs().joint_state
            gripper = self.bus.GetArmGripperMsgs().gripper_state
        else:
            joints = self.bus.GetArmJointCtrl().joint_ctrl
            gripper = self.bus.GetArmGripperCtrl().gripper_ctrl

        joint_positions = [
            JointValue(
                name="joint1",
                value=math.radians(joints.joint_1 / self.ANGLE_SCALE),
                type="radians",
            ),
            JointValue(
                name="joint2",
                value=math.radians(joints.joint_2 / self.ANGLE_SCALE),
                type="radians",
            ),
            JointValue(
                name="joint3",
                value=math.radians(joints.joint_3 / self.ANGLE_SCALE),
                type="radians",
            ),
            JointValue(
                name="joint4",
                value=math.radians(joints.joint_4 / self.ANGLE_SCALE),
                type="radians",
            ),
            JointValue(
                name="joint5",
                value=math.radians(joints.joint_5 / self.ANGLE_SCALE),
                type="radians",
            ),
            JointValue(
                name="joint6",
                value=math.radians(joints.joint_6 / self.ANGLE_SCALE),
                type="radians",
            ),
            JointValue(
                name="gripper",
                value=gripper.grippers_angle / self.GRIPPER_SCALE / 1000.0,
                type="meters",
            ),
        ]

        return joint_positions

    def set_actuators(self, action: list[ActuatorValue]) -> None:
        if self.bus is None:
            raise RuntimeError("Robot is not connected. Call connect() first.")

        safe_action = self.get_safe_actuator_values(action)

        action_dict = {act.name: act.value for act in safe_action}

        joint_1 = int(math.degrees(action_dict.get("joint1", 0.0)) * self.ANGLE_SCALE)
        joint_2 = int(math.degrees(action_dict.get("joint2", 0.0)) * self.ANGLE_SCALE)
        joint_3 = int(math.degrees(action_dict.get("joint3", 0.0)) * self.ANGLE_SCALE)
        joint_4 = int(math.degrees(action_dict.get("joint4", 0.0)) * self.ANGLE_SCALE)
        joint_5 = int(math.degrees(action_dict.get("joint5", 0.0)) * self.ANGLE_SCALE)
        joint_6 = int(math.degrees(action_dict.get("joint6", 0.0)) * self.ANGLE_SCALE)
        gripper = int(action_dict.get("gripper", 0.0) * 1000.0 * self.GRIPPER_SCALE)

        self.bus.MotionCtrl_2(0x01, 0x01, 100, 0x00)
        self.bus.JointCtrl(joint_1, joint_2, joint_3, joint_4, joint_5, joint_6)
        self.bus.GripperCtrl(abs(gripper), 1000, 0x01, 0)
