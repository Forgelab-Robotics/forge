from __future__ import annotations

import sys
from pathlib import Path

FORGE_ROBOT_ROOT = Path(__file__).parents[1]
FRAMEWORK_ROOT = FORGE_ROBOT_ROOT.parents[2]
MSGS_SRC = FRAMEWORK_ROOT / "forge" / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_ROBOT_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

from forge_msgs import JointCommand
from forge_robot.actuator_spec import (
    ActuatorSpec,
    clip_and_validate_command,
    clip_and_validate_position_command,
)


def test_default_unit_deduction() -> None:
    spec_revolute = ActuatorSpec(name="joint_rev", kind="revolute")
    assert spec_revolute.position_unit == "radians"
    assert spec_revolute.velocity_unit == "radians/s"
    assert spec_revolute.acceleration_unit == "radians/s^2"
    assert spec_revolute.effort_unit == "Nm"

    spec_prismatic = ActuatorSpec(name="joint_prism", kind="prismatic")
    assert spec_prismatic.position_unit == "meters"
    assert spec_prismatic.velocity_unit == "meters/s"
    assert spec_prismatic.acceleration_unit == "meters/s^2"


def test_clip_and_validate_command_position() -> None:
    specs = {
        "joint_rev": ActuatorSpec(
            name="joint_rev",
            kind="revolute",
            min_position=-1.0,
            max_position=1.0,
        ),
        "joint_cont": ActuatorSpec(
            name="joint_cont",
            kind="continuous",
            min_position=-1.0,
            max_position=1.0,
        ),
    }
    command = JointCommand(
        name=["joint_rev", "joint_cont"],
        position=[1.5, 5.0],
    )
    result = clip_and_validate_command(command, specs)
    assert result.name == ["joint_rev", "joint_cont"]
    assert result.position == [1.0, 5.0]


def test_clip_and_validate_command_velocity_and_effort() -> None:
    specs = {
        "joint_rev": ActuatorSpec(
            name="joint_rev",
            kind="revolute",
            max_velocity=2.0,
            max_effort=10.0,
        ),
    }
    command = JointCommand(
        name=["joint_rev"],
        velocity=[-3.0],
        effort=[15.0],
    )
    result = clip_and_validate_command(command, specs)
    assert result.velocity == [-2.0]
    assert result.effort == [10.0]


def test_clip_and_validate_command_preserves_gains() -> None:
    specs = {
        "joint_rev": ActuatorSpec(name="joint_rev", kind="revolute"),
    }
    command = JointCommand(
        name=["joint_rev"],
        position=[0.1],
        kp=[20.0],
        kd=[1.0],
    )
    result = clip_and_validate_command(command, specs)
    assert result.kp == [20.0]
    assert result.kd == [1.0]


def test_clip_and_validate_position_command_wrapper() -> None:
    specs = {
        "joint_prism": ActuatorSpec(
            name="joint_prism",
            kind="prismatic",
            min_position=-0.5,
            max_position=0.5,
        ),
    }
    command = JointCommand(name=["joint_prism"], position=[0.8])
    result = clip_and_validate_position_command(command, specs)
    assert result.position == [0.5]
