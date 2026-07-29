from __future__ import annotations

import math

import pyarrow as pa
import pytest
from pydantic import ValidationError

from forge_msgs import (
    MoveJointsFeedback,
    MoveJointsGoal,
    MoveJointsResult,
    MovePoseFeedback,
    MovePoseGoal,
    MovePoseResult,
    Pose,
)


def _pose() -> Pose:
    return Pose(x=0.4, y=-0.2, z=0.8, qx=0.0, qy=0.0, qz=0.0, qw=1.0)


def test_move_joints_goal_schema_roundtrip_and_metadata_omission() -> None:
    goal = MoveJointsGoal(
        group_name="arm",
        joint_names=["shoulder", "elbow"],
        positions=[0.5, -0.25],
        velocity_scale=0.7,
        acceleration_scale=0.5,
        requested_duration_ns=None,
    )
    batch = goal.to_arrow()

    assert batch.num_rows == 1
    assert batch.schema.names == [
        "group_name",
        "joint_names",
        "positions",
        "velocity_scale",
        "acceleration_scale",
        "requested_duration_ns",
    ]
    assert "goal_id" not in batch.schema.names
    assert "goal_status" not in batch.schema.names
    assert batch.schema.field("requested_duration_ns").nullable
    assert batch.schema.field("requested_duration_ns").type == pa.int64()
    assert MoveJointsGoal.from_arrow(batch) == goal


def test_move_joints_feedback_nullable_scalars_roundtrip() -> None:
    feedback = MoveJointsFeedback(
        phase="PLANNING",
        progress=None,
        elapsed_ns=10,
        estimated_duration_ns=None,
        joint_names=["shoulder", "elbow"],
        actual_positions=[],
        target_positions=[0.5, -0.25],
        position_errors=[],
        message="planning",
    )
    batch = feedback.to_arrow()

    assert batch.schema.names == [
        "phase",
        "progress",
        "elapsed_ns",
        "estimated_duration_ns",
        "joint_names",
        "actual_positions",
        "target_positions",
        "position_errors",
        "message",
    ]
    assert batch["progress"][0].as_py() is None
    assert batch.schema.field("progress").nullable
    assert MoveJointsFeedback.from_arrow(pa.Table.from_batches([batch])) == feedback


def test_move_joints_result_roundtrip() -> None:
    result = MoveJointsResult(
        error_code="PLANNING_FAILED",
        message="no path",
        elapsed_ns=200,
        joint_names=[],
        final_positions=[],
        final_position_errors=[],
    )

    assert MoveJointsResult.from_arrow(result.to_arrow()) == result


def test_move_pose_goal_reuses_pose_as_nested_struct() -> None:
    goal = MovePoseGoal(
        group_name="arm",
        reference_frame="base",
        target_frame="tool",
        target_pose=_pose(),
        velocity_scale=1.0,
        acceleration_scale=0.8,
        requested_duration_ns=2_000_000,
        position_tolerance_m=0.002,
        orientation_tolerance_rad=None,
    )
    batch = goal.to_arrow()

    assert batch.schema.names == [
        "group_name",
        "reference_frame",
        "target_frame",
        "target_pose",
        "velocity_scale",
        "acceleration_scale",
        "requested_duration_ns",
        "position_tolerance_m",
        "orientation_tolerance_rad",
    ]
    pose_field = batch.schema.field("target_pose")
    assert not pose_field.nullable
    assert pa.types.is_struct(pose_field.type)
    assert [field.name for field in pose_field.type] == [
        "x",
        "y",
        "z",
        "qx",
        "qy",
        "qz",
        "qw",
    ]
    assert MovePoseGoal.from_arrow(batch) == goal


def test_move_pose_feedback_nullable_struct_roundtrip() -> None:
    without_pose = MovePoseFeedback(
        phase="VALIDATING",
        progress=0.0,
        elapsed_ns=0,
        estimated_duration_ns=None,
        actual_pose=None,
        position_error_m=None,
        orientation_error_rad=None,
        message="",
    )
    null_batch = without_pose.to_arrow()

    assert null_batch.schema.field("actual_pose").nullable
    assert null_batch["actual_pose"][0].as_py() is None
    assert MovePoseFeedback.from_arrow(null_batch) == without_pose

    with_pose = MovePoseFeedback(
        phase="EXECUTING",
        progress=0.5,
        elapsed_ns=50,
        estimated_duration_ns=100,
        actual_pose=_pose(),
        position_error_m=0.01,
        orientation_error_rad=0.02,
        message="moving",
    )
    assert MovePoseFeedback.from_arrow(with_pose.to_arrow()) == with_pose


def test_move_pose_result_nullable_struct_roundtrip() -> None:
    result = MovePoseResult(
        error_code="SUCCESS",
        message="done",
        elapsed_ns=100,
        final_pose=_pose(),
        final_position_error_m=0.0,
        final_orientation_error_rad=0.0,
        joint_names=["shoulder", "elbow"],
        final_joint_positions=[0.5, -0.25],
    )

    assert MovePoseResult.from_arrow(result.to_arrow()) == result

    empty_result = MovePoseResult(
        error_code="INVALID_GOAL",
        message="invalid",
        elapsed_ns=0,
        final_pose=None,
        final_position_error_m=None,
        final_orientation_error_rad=None,
        joint_names=[],
        final_joint_positions=[],
    )
    assert MovePoseResult.from_arrow(empty_result.to_arrow()) == empty_result


def test_motion_validation_contract() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        MoveJointsGoal(
            group_name="arm",
            joint_names=[""],
            positions=[0.0],
            velocity_scale=1.0,
            acceleration_scale=1.0,
        )
    with pytest.raises(ValidationError, match="positions"):
        MoveJointsGoal(
            group_name="arm",
            joint_names=["a", "b"],
            positions=[0.0],
            velocity_scale=1.0,
            acceleration_scale=1.0,
        )
    with pytest.raises(ValidationError, match="velocity_scale"):
        MoveJointsGoal(
            group_name="arm",
            joint_names=["a"],
            positions=[0.0],
            velocity_scale=0.0,
            acceleration_scale=1.0,
        )
    with pytest.raises(ValidationError, match="progress"):
        MoveJointsFeedback(
            phase="EXECUTING",
            progress=math.inf,
            elapsed_ns=0,
            joint_names=["a"],
            actual_positions=[],
            target_positions=[0.0],
            position_errors=[],
            message="",
        )
    with pytest.raises(ValidationError):
        MovePoseFeedback(
            phase="UNKNOWN",  # type: ignore[arg-type]
            elapsed_ns=0,
            actual_pose=None,
            message="",
        )
    with pytest.raises(ValidationError, match="orientation_tolerance_rad"):
        MovePoseGoal(
            group_name="arm",
            reference_frame="base",
            target_frame="tool",
            target_pose=_pose(),
            velocity_scale=1.0,
            acceleration_scale=1.0,
            orientation_tolerance_rad=-0.1,
        )
