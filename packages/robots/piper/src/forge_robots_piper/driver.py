from __future__ import annotations
import math
import time

from forge_robots_core.base import BaseActuator, BaseJoint, BaseRobotDriver
from forge_robots_core.value import JointValue, ActuatorValue
from piper_sdk import C_PiperInterface_V2

from forge_common import get_logger

logger = get_logger(__name__)


class PiperDriver(BaseRobotDriver):
    def __init__(
        self,
        joints: list[BaseJoint],
        actuators: list[BaseActuator],
        port: str = "can0",
        is_follower: bool = True,
    ):
        super().__init__(type="piper", joints=joints, actuators=actuators)
        self.is_follower = is_follower
        self.port = port
        self.bus = None  # 用于 Piper SDK 的通信实例
        self._is_connected = False

        self.connect()

    def connect(self):
        """
        连接到 Piper 机器人并使其上电。

        Args:
            calibrate(bool): 是否在连接后执行归位程序。
        """
        if self._is_connected:
            logger.info("Robot is already connected.")
            return

        self.bus = C_PiperInterface_V2(self.port)

        logger.info(f"Connecting to Piper robot at port {self.port}...")
        self.bus.ConnectPort()

        if self.is_follower:
            # logger.info("Setting Piper to follower mode...")
            # self.bus.MasterSlaveConfig(0xFC, 0, 0, 0)
            time.sleep(1)
            logger.info("Enabling the robot...")
            while not self.bus.EnablePiper():
                time.sleep(0.01)
            self.bus.EnableArm(7)

            # set safe position
            logger.info("Moving robot to safe position...")
            self.bus.GripperCtrl(0, 1000, 0x01, 0)
            self.set_safety_position()
            time.sleep(2)
        else:
            # logger.info("Setting Piper to master mode...")
            # self.bus.MasterSlaveConfig(0xFA, 0, 0, 0)
            # not sure if need sleep here
            time.sleep(1)

        self._is_connected = True
        logger.info("Successfully connected and enabled the robot.")

    def disconnect(self):
        """
        使机器人下电并断开串口连接。
        """
        if self.bus and self._is_connected:
            logger.info("Disabling and disconnecting from the robot...")
            self.bus.DisablePiper()
            self.bus.DisconnectPort()
            self._is_connected = False
            logger.info("Disconnected from the robot.")

    def reset(self):
        """
        执行 Piper 机器人的自动归位（Homing）程序。
        """
        time.sleep(3)
        self.bus.MotionCtrl_1(0x02, 0, 0)  # 恢复
        self.bus.MotionCtrl_2(0, 0, 0, 0x00)  # 位置速度模式
        logger.info(
            "Homing command sent. The robot will now move to its home position."
        )
        time.sleep(1)
        logger.info("Homing sequence should be completed.")

    def get_joint_positions(self) -> dict[str, JointValue]:
        if self.is_follower:
            # read from state msgs
            # piper 读取的是角度，单位是0.001度
            joints = self.bus.GetArmJointMsgs().joint_state
            # piper 读取的是长度，单位是0.001mm
            gripper = self.bus.GetArmGripperMsgs().gripper_state
            return {
                "joint1": JointValue(math.radians(joints.joint_1 / 1000.0), "radians"),
                "joint2": JointValue(math.radians(joints.joint_2 / 1000.0), "radians"),
                "joint3": JointValue(math.radians(joints.joint_3 / 1000.0), "radians"),
                "joint4": JointValue(math.radians(joints.joint_4 / 1000.0), "radians"),
                "joint5": JointValue(math.radians(joints.joint_5 / 1000.0), "radians"),
                "joint6": JointValue(math.radians(joints.joint_6 / 1000.0), "radians"),
                "gripper": JointValue(gripper.grippers_angle / 1000.0, "millimeters"),
            }
        else:
            # read from ctrl msgs
            # piper 读取的是角度，单位是0.001度
            joints = self.bus.GetArmJointCtrl().joint_ctrl
            # piper 读取的是长度，单位是0.001mm
            gripper = self.bus.GetArmGripperCtrl().gripper_ctrl
            return {
                "joint1": JointValue(math.radians(joints.joint_1 / 1000.0), "radians"),
                "joint2": JointValue(math.radians(joints.joint_2 / 1000.0), "radians"),
                "joint3": JointValue(math.radians(joints.joint_3 / 1000.0), "radians"),
                "joint4": JointValue(math.radians(joints.joint_4 / 1000.0), "radians"),
                "joint5": JointValue(math.radians(joints.joint_5 / 1000.0), "radians"),
                "joint6": JointValue(math.radians(joints.joint_6 / 1000.0), "radians"),
                "gripper": JointValue(gripper.grippers_angle / 1000.0, "millimeters"),
            }

    def set_actuators(self, action: dict[str, float]):
        # piper 写入的是角度，单位是0.001度
        # 夹爪单位为 1mm

        # 检查是否超过定义范围, 超过告警并设置为边界值
        safe_action = self.get_safe_actuator_values(action)
        # 执行控制
        joint_1 = int(math.degrees(safe_action["joint1"]) * 1000)
        joint_2 = int(math.degrees(safe_action["joint2"]) * 1000)
        joint_3 = int(math.degrees(safe_action["joint3"]) * 1000)
        joint_4 = int(math.degrees(safe_action["joint4"]) * 1000)
        joint_5 = int(math.degrees(safe_action["joint5"]) * 1000)
        joint_6 = int(math.degrees(safe_action["joint6"]) * 1000)
        joint_7 = int(safe_action["gripper"] * 1000)
        self.bus.MotionCtrl_2(0x01, 0x01, 100, 0x00)
        self.bus.JointCtrl(joint_1, joint_2, joint_3, joint_4, joint_5, joint_6)
        self.bus.GripperCtrl(abs(joint_7), 1000, 0x01, 0)

    def set_safety_position(self):
        """
        将piper移动到安全位置。
        """
        safe_pos = {
            "joint1": 0,
            "joint2": 0,
            "joint3": 0,
            "joint4": 0,
            "joint5": 0.48,
            "joint6": 0,
            "gripper": 0,
        }
        self.set_actuators(safe_pos)
