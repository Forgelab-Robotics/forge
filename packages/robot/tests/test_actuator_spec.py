from __future__ import annotations

import math
import sys
from pathlib import Path

import pyarrow as pa
import pytest

FORGE_ROBOT_ROOT = Path(__file__).parents[1]
REPO_ROOT = FORGE_ROBOT_ROOT.parents[2]
MSGS_SRC = REPO_ROOT / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_ROBOT_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

from forge_msgs import JointCommand, LocomotionCommand
from forge_robot.actuator_spec import (
    ActuatorSpec,
    clip_and_validate_command,
    clip_and_validate_position_command,
)
from forge_robot.arrow_validation import (
    RobotArrowSchemaError,
    validate_robot_control_arrow,
)
from forge_robot.locomotion_spec import (
    LocomotionSpec,
    clip_and_validate_locomotion_command,
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
        mode="hybrid",
        position=[0.1],
        kp=[20.0],
        kd=[1.0],
    )
    result = clip_and_validate_command(command, specs)
    assert result.mode == "hybrid"
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


def test_validate_robot_control_arrow_accepts_legacy_command_without_mode() -> None:
    batch = pa.RecordBatch.from_pydict(
        {
            "name": pa.array([["joint_rev"]], type=pa.list_(pa.string())),
            "position": pa.array([[0.1]], type=pa.list_(pa.float64())),
            "velocity": pa.array([[]], type=pa.list_(pa.float64())),
            "effort": pa.array([[]], type=pa.list_(pa.float64())),
            "kp": pa.array([[]], type=pa.list_(pa.float64())),
            "kd": pa.array([[]], type=pa.list_(pa.float64())),
        }
    )

    assert validate_robot_control_arrow(batch, ["joint_rev"]) is batch


def test_validate_robot_control_arrow_accepts_sparse_joint_subset() -> None:
    batch = JointCommand(name=["joint_rev"], position=[0.1]).to_arrow()

    assert validate_robot_control_arrow(
        batch,
        ["joint_rev", "joint_prism"],
        strict_extra_columns=True,
    ) is batch


def test_validate_robot_control_arrow_rejects_invalid_mode() -> None:
    batch = JointCommand(name=["joint_rev"], mode="hybrid").to_arrow()
    mode_index = batch.schema.names.index("mode")
    bad_batch = batch.set_column(
        mode_index,
        pa.field("mode", pa.string()),
        pa.array(["invalid"], type=pa.string()),
    )

    with pytest.raises(RobotArrowSchemaError, match="mode"):
        validate_robot_control_arrow(bad_batch, ["joint_rev"])


def test_clip_and_validate_locomotion_command_limits_and_lateral() -> None:
    command = LocomotionCommand(vx=2.0, vy=1.0, wz=-3.0)
    spec = LocomotionSpec(
        max_vx=1.0,
        max_vy=0.5,
        max_wz=2.0,
        allow_lateral=False,
    )

    result = clip_and_validate_locomotion_command(command, spec)

    assert result == LocomotionCommand(vx=1.0, vy=0.0, wz=-2.0)


@pytest.mark.parametrize("limit", [-1.0, math.inf, math.nan])
def test_locomotion_spec_rejects_invalid_limits(limit: float) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        LocomotionSpec(max_vx=limit)
