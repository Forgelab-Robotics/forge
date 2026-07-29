from __future__ import annotations

import math

import pyarrow as pa
import pytest
from pydantic import ValidationError

from forge_msgs import (
    FollowJointTrajectoryFeedback,
    FollowJointTrajectoryGoal,
    FollowJointTrajectoryResult,
    JointTolerance,
    JointTrajectory,
    JointTrajectoryPoint,
)


def _to_ipc_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


def _point(time_ns: int, offset: float = 0.0) -> JointTrajectoryPoint:
    return JointTrajectoryPoint(
        positions=[offset, offset + 1.0],
        velocities=[0.1, 0.2],
        accelerations=[],
        effort=[],
        time_from_start_ns=time_ns,
    )


def test_joint_trajectory_point_arrow_schema_and_roundtrip() -> None:
    point = _point(10)
    batch = point.to_arrow()

    assert batch.num_rows == 1
    assert batch.schema.names == [
        "positions",
        "velocities",
        "accelerations",
        "effort",
        "time_from_start_ns",
    ]
    assert [field.type for field in batch.schema] == [
        pa.list_(pa.float64()),
        pa.list_(pa.float64()),
        pa.list_(pa.float64()),
        pa.list_(pa.float64()),
        pa.int64(),
    ]
    assert all(not field.nullable for field in batch.schema)
    assert JointTrajectoryPoint.from_arrow(batch) == point
    assert JointTrajectoryPoint.from_arrow(pa.Table.from_batches([batch])) == point
    assert JointTrajectoryPoint.from_arrow(_to_ipc_bytes(batch)) == point


def test_joint_trajectory_nested_list_struct_roundtrip() -> None:
    trajectory = JointTrajectory(
        joint_names=["shoulder", "elbow"],
        points=[_point(0), _point(1_000_000, 0.5)],
    )
    batch = trajectory.to_arrow()

    assert batch.schema.names == ["joint_names", "points"]
    assert pa.types.is_list(batch.schema.field("points").type)
    point_type = batch.schema.field("points").type.value_type
    assert pa.types.is_struct(point_type)
    assert [field.name for field in point_type] == [
        "positions",
        "velocities",
        "accelerations",
        "effort",
        "time_from_start_ns",
    ]
    assert JointTrajectory.from_arrow(batch) == trajectory


def test_joint_tolerance_nullable_scalars_roundtrip() -> None:
    tolerance = JointTolerance(joint_name="shoulder", position=0.01)
    batch = tolerance.to_arrow()

    assert batch.schema.names == [
        "joint_name",
        "position",
        "velocity",
        "acceleration",
    ]
    assert not batch.schema.field("joint_name").nullable
    assert batch.schema.field("position").nullable
    assert batch.schema.field("velocity").nullable
    assert batch["velocity"][0].as_py() is None
    assert JointTolerance.from_arrow(batch) == tolerance


def test_follow_joint_trajectory_goal_nested_roundtrip_and_metadata_omission() -> None:
    goal = FollowJointTrajectoryGoal(
        trajectory=JointTrajectory(
            joint_names=["shoulder", "elbow"],
            points=[_point(0), _point(100)],
        ),
        path_tolerance=[JointTolerance(joint_name="shoulder", position=0.1)],
        goal_tolerance=[JointTolerance(joint_name="elbow", velocity=0.2)],
        goal_time_tolerance_ns=None,
    )
    batch = goal.to_arrow()

    assert batch.schema.names == [
        "trajectory",
        "path_tolerance",
        "goal_tolerance",
        "goal_time_tolerance_ns",
    ]
    assert "goal_id" not in batch.schema.names
    assert "goal_status" not in batch.schema.names
    assert batch.schema.field("goal_time_tolerance_ns").nullable
    assert FollowJointTrajectoryGoal.from_arrow(_to_ipc_bytes(batch)) == goal


def test_follow_joint_trajectory_feedback_nested_struct_roundtrip() -> None:
    feedback = FollowJointTrajectoryFeedback(
        sequence=4,
        point_index=1,
        elapsed_ns=50,
        duration_ns=100,
        desired=_point(50),
        actual=_point(50, -0.1),
        error=_point(50, 0.1),
    )
    batch = feedback.to_arrow()

    assert batch.schema.names == [
        "sequence",
        "point_index",
        "elapsed_ns",
        "duration_ns",
        "desired",
        "actual",
        "error",
    ]
    assert batch.schema.field("sequence").type == pa.uint64()
    assert batch.schema.field("point_index").type == pa.uint32()
    assert FollowJointTrajectoryFeedback.from_arrow(batch) == feedback


def test_follow_joint_trajectory_result_roundtrip_and_enum() -> None:
    result = FollowJointTrajectoryResult(
        error_code="SUCCESS",
        message="",
        elapsed_ns=1_000,
        joint_names=["shoulder", "elbow"],
        final_position_error=[0.0, 0.0],
        final_velocity_error=[],
    )

    assert FollowJointTrajectoryResult.from_arrow(result.to_arrow()) == result
    with pytest.raises(ValidationError):
        FollowJointTrajectoryResult(
            error_code="succeeded",  # type: ignore[arg-type]
            message="",
            elapsed_ns=0,
            joint_names=[],
            final_position_error=[],
            final_velocity_error=[],
        )


def test_trajectory_validation_contract() -> None:
    with pytest.raises(ValidationError, match="positions"):
        JointTrajectoryPoint(
            positions=[],
            velocities=[],
            accelerations=[],
            effort=[],
            time_from_start_ns=0,
        )
    with pytest.raises(ValidationError, match="finite"):
        JointTrajectoryPoint(
            positions=[math.inf],
            velocities=[],
            accelerations=[],
            effort=[],
            time_from_start_ns=0,
        )
    with pytest.raises(ValidationError, match="strictly increasing"):
        JointTrajectory(joint_names=["a", "b"], points=[_point(10), _point(10)])
    with pytest.raises(ValidationError, match="at least one"):
        JointTolerance(joint_name="a")
    with pytest.raises(ValidationError, match="belong"):
        FollowJointTrajectoryGoal(
            trajectory=JointTrajectory(joint_names=["a", "b"], points=[_point(0)]),
            path_tolerance=[JointTolerance(joint_name="other", position=0.1)],
            goal_tolerance=[],
        )


def test_trajectory_from_arrow_rejects_noncanonical_order_and_row_count() -> None:
    point_batch = _point(0).to_arrow()
    reordered = pa.RecordBatch.from_arrays(
        list(reversed(point_batch.columns)),
        schema=pa.schema(list(reversed(point_batch.schema))),
    )
    with pytest.raises(ValueError, match="ordered"):
        JointTrajectoryPoint.from_arrow(reordered)

    two_rows = pa.Table.from_batches([point_batch, point_batch])
    with pytest.raises(ValueError, match="exactly one row"):
        JointTrajectoryPoint.from_arrow(two_rows)
