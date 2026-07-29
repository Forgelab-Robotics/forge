"""Self-contained URDF fixtures for the public forge_kinematics API."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from forge_kinematics import RobotModel


TEST_ROBOT_URDF = textwrap.dedent(
    """\
    <?xml version="1.0"?>
    <robot name="kinematics_contract_robot">
      <link name="world"/>
      <link name="base"/>
      <joint name="world_to_base" type="fixed">
        <parent link="world"/>
        <child link="base"/>
        <origin xyz="3 -2 1" rpy="0 0 0.6"/>
      </joint>

      <link name="shoulder_link"/>
      <joint name="shoulder" type="revolute">
        <parent link="base"/>
        <child link="shoulder_link"/>
        <origin xyz="0.5 -0.2 0.3" rpy="0 0 0"/>
        <axis xyz="0 0 1"/>
        <limit lower="-2.0" upper="2.0" effort="10" velocity="5"/>
      </joint>

      <link name="slider_link"/>
      <joint name="extension" type="prismatic">
        <parent link="shoulder_link"/>
        <child link="slider_link"/>
        <origin xyz="0.8 0 0" rpy="0 0 0"/>
        <axis xyz="1 0 0"/>
        <limit lower="0.0" upper="0.5" effort="10" velocity="1"/>
      </joint>

      <link name="tool"/>
      <joint name="tool_fixed" type="fixed">
        <parent link="slider_link"/>
        <child link="tool"/>
        <origin xyz="0.2 0 0.1" rpy="0 0 0"/>
      </joint>

      <link name="spin_link"/>
      <joint name="spin" type="continuous">
        <parent link="base"/>
        <child link="spin_link"/>
        <origin xyz="0 0 0.2" rpy="0 0 0"/>
        <axis xyz="0 0 1"/>
      </joint>
      <link name="spin_tip"/>
      <joint name="spin_tip_fixed" type="fixed">
        <parent link="spin_link"/>
        <child link="spin_tip"/>
        <origin xyz="0.4 0 0" rpy="0 0 0"/>
      </joint>

      <link name="side_link"/>
      <joint name="side_joint" type="revolute">
        <parent link="base"/>
        <child link="side_link"/>
        <origin xyz="0 0.7 0" rpy="0 0 0"/>
        <axis xyz="0 1 0"/>
        <limit lower="-1" upper="1" effort="1" velocity="1"/>
      </joint>

      <link name="mimic_link"/>
      <joint name="mimic_joint" type="revolute">
        <parent link="base"/>
        <child link="mimic_link"/>
        <origin xyz="0 -0.7 0" rpy="0 0 0"/>
        <axis xyz="0 0 1"/>
        <limit lower="-2" upper="2" effort="1" velocity="1"/>
        <mimic joint="shoulder" multiplier="1" offset="0"/>
      </joint>
      <link name="mimic_tip"/>
      <joint name="mimic_tip_fixed" type="fixed">
        <parent link="mimic_link"/>
        <child link="mimic_tip"/>
        <origin xyz="0.2 0 0" rpy="0 0 0"/>
      </joint>
    </robot>
    """
)


@pytest.fixture()
def urdf_path(tmp_path: Path) -> Path:
    path = tmp_path / "kinematics_contract_robot.urdf"
    path.write_text(TEST_ROBOT_URDF, encoding="utf-8")
    return path


@pytest.fixture()
def robot_model(urdf_path: Path) -> RobotModel:
    return RobotModel.from_urdf(str(urdf_path))


@pytest.fixture()
def rp_group(robot_model: RobotModel):
    return robot_model.create_group(
        name="rp",
        joint_names=["shoulder", "extension"],
        base_frame="base",
        tip_frames=("tool",),
    )
