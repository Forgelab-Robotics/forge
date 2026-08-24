from __future__ import annotations

import math
from itertools import pairwise
from typing import ClassVar, Literal, Self

import pyarrow as pa
from pydantic import BaseModel, model_validator

from forge_msgs.arrow import ensure_record_batch

FollowJointTrajectoryErrorCode = Literal[
    "SUCCESS",
    "INVALID_GOAL",
    "INVALID_JOINTS",
    "BUSY",
    "NO_FRESH_ROBOT_STATE",
    "START_STATE_MISMATCH",
    "PATH_TOLERANCE_VIOLATED",
    "GOAL_TOLERANCE_VIOLATED",
    "FEEDBACK_STALE",
    "EXECUTION_TIMED_OUT",
    "HARDWARE_FAULT",
    "CANCELED",
    "INTERNAL_ERROR",
]

_INT64_MAX = 2**63 - 1
_UINT32_MAX = 2**32 - 1
_UINT64_MAX = 2**64 - 1

_FLOAT_LIST_TYPE = pa.list_(pa.float64())
_STRING_LIST_TYPE = pa.list_(pa.string())
_JOINT_TRAJECTORY_POINT_TYPE = pa.struct(
    [
        pa.field("positions", _FLOAT_LIST_TYPE, nullable=False),
        pa.field("velocities", _FLOAT_LIST_TYPE, nullable=False),
        pa.field("accelerations", _FLOAT_LIST_TYPE, nullable=False),
        pa.field("effort", _FLOAT_LIST_TYPE, nullable=False),
        pa.field("time_from_start_ns", pa.int64(), nullable=False),
    ]
)
_JOINT_TRAJECTORY_TYPE = pa.struct(
    [
        pa.field("joint_names", _STRING_LIST_TYPE, nullable=False),
        pa.field("points", pa.list_(_JOINT_TRAJECTORY_POINT_TYPE), nullable=False),
    ]
)
_JOINT_TOLERANCE_TYPE = pa.struct(
    [
        pa.field("joint_name", pa.string(), nullable=False),
        pa.field("position", pa.float64(), nullable=True),
        pa.field("velocity", pa.float64(), nullable=True),
        pa.field("acceleration", pa.float64(), nullable=True),
    ]
)


def _schema(*fields: tuple[str, pa.DataType, bool]) -> pa.Schema:
    return pa.schema(
        [
            pa.field(name, data_type, nullable=nullable)
            for name, data_type, nullable in fields
        ]
    )


def _single_row_batch(
    data: pa.RecordBatch | pa.Table | pa.StructArray | bytes,
    model_name: str,
) -> pa.RecordBatch:
    if isinstance(data, bytes):
        table = pa.ipc.open_stream(data).read_all()
        return _single_row_batch(table, model_name)
    if isinstance(data, pa.Table):
        if data.num_rows != 1:
            raise ValueError(f"{model_name} RecordBatch must contain exactly one row")
        return data.combine_chunks().to_batches()[0]
    if isinstance(data, pa.StructArray):
        if len(data) != 1:
            raise ValueError(f"{model_name} RecordBatch must contain exactly one row")
        schema = pa.schema(
            [data.type.field(index) for index in range(data.type.num_fields)]
        )
        return pa.RecordBatch.from_arrays(
            [data.field(index) for index in range(data.type.num_fields)],
            schema=schema,
        )
    batch = ensure_record_batch(data)
    if batch.num_rows != 1:
        raise ValueError(f"{model_name} RecordBatch must contain exactly one row")
    return batch


def _validate_arrow_schema(
    batch: pa.RecordBatch, expected: pa.Schema, model_name: str
) -> None:
    if len(batch.schema) != len(expected):
        raise ValueError(
            f"{model_name} Arrow fields must be {expected.names}, got {batch.schema.names}"
        )
    for actual_field, expected_field in zip(batch.schema, expected, strict=True):
        if actual_field.name != expected_field.name:
            raise ValueError(
                f"{model_name} Arrow fields must be ordered as {expected.names}, "
                f"got {batch.schema.names}"
            )
        if actual_field.type != expected_field.type:
            raise TypeError(
                f"{model_name} Arrow field {expected_field.name} must have type "
                f"{expected_field.type}, got {actual_field.type}"
            )
        if actual_field.nullable != expected_field.nullable:
            raise TypeError(
                f"{model_name} Arrow field {expected_field.name} nullable must be "
                f"{expected_field.nullable}, got {actual_field.nullable}"
            )


def _record_batch(values: dict[str, object], schema: pa.Schema) -> pa.RecordBatch:
    arrays = [pa.array([values[field.name]], type=field.type) for field in schema]
    return pa.RecordBatch.from_arrays(arrays, schema=schema)


def _read_record_batch(
    data: pa.RecordBatch | pa.Table | pa.StructArray | bytes,
    model_name: str,
    schema: pa.Schema,
) -> dict[str, object]:
    batch = _single_row_batch(data, model_name)
    _validate_arrow_schema(batch, schema, model_name)
    return {field.name: batch[field.name][0].as_py() for field in schema}


def _validate_finite(name: str, values: list[float]) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{name} values must be finite")


def _validate_optional_vector(
    name: str, values: list[float], expected_length: int
) -> None:
    if values and len(values) != expected_length:
        raise ValueError(
            f"{name} must be empty or have length {expected_length}, got {len(values)}"
        )
    _validate_finite(name, values)


def _validate_unique(name: str, values: list[str]) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{name} items must be unique")


def _validate_non_negative(name: str, value: int | None) -> None:
    if value is not None and not 0 <= value <= _INT64_MAX:
        raise ValueError(f"{name} must be non-negative and in the int64 range")


class _ArrowMessage(BaseModel):
    _ARROW_SCHEMA: ClassVar[pa.Schema]

    def to_arrow(self) -> pa.RecordBatch:
        validated = type(self).model_validate(self.model_dump(mode="python"))
        return _record_batch(validated.model_dump(mode="python"), self._ARROW_SCHEMA)

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> Self:
        values = _read_record_batch(data, cls.__name__, cls._ARROW_SCHEMA)
        return cls.model_validate(values)


class JointTrajectoryPoint(_ArrowMessage):
    """Joint-space trajectory sample relative to trajectory start."""

    positions: list[float]
    velocities: list[float]
    accelerations: list[float]
    effort: list[float]
    time_from_start_ns: int

    _ARROW_SCHEMA = _schema(
        ("positions", _FLOAT_LIST_TYPE, False),
        ("velocities", _FLOAT_LIST_TYPE, False),
        ("accelerations", _FLOAT_LIST_TYPE, False),
        ("effort", _FLOAT_LIST_TYPE, False),
        ("time_from_start_ns", pa.int64(), False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.positions:
            raise ValueError("positions must contain at least one value")
        _validate_finite("positions", self.positions)
        for name in ("velocities", "accelerations", "effort"):
            _validate_optional_vector(name, getattr(self, name), len(self.positions))
        _validate_non_negative("time_from_start_ns", self.time_from_start_ns)
        return self


class JointTrajectory(_ArrowMessage):
    """Time-ordered trajectory for a named joint group."""

    joint_names: list[str]
    points: list[JointTrajectoryPoint]

    _ARROW_SCHEMA = _schema(
        ("joint_names", _STRING_LIST_TYPE, False),
        ("points", pa.list_(_JOINT_TRAJECTORY_POINT_TYPE), False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.joint_names:
            raise ValueError("joint_names must contain at least one name")
        if any(not name for name in self.joint_names):
            raise ValueError("joint_names items must be non-empty")
        _validate_unique("joint_names", self.joint_names)
        if not self.points:
            raise ValueError("points must contain at least one trajectory point")
        joint_count = len(self.joint_names)
        for point in self.points:
            if len(point.positions) != joint_count:
                raise ValueError(
                    "point positions must have the same length as joint_names"
                )
            for name in ("velocities", "accelerations", "effort"):
                values = getattr(point, name)
                if values and len(values) != joint_count:
                    raise ValueError(
                        f"point {name} must be empty or have the same length as "
                        "joint_names"
                    )
        times = [point.time_from_start_ns for point in self.points]
        if any(left >= right for left, right in pairwise(times)):
            raise ValueError("time_from_start_ns values must be strictly increasing")
        return self


class JointTolerance(_ArrowMessage):
    """Optional error limits for one joint."""

    joint_name: str
    position: float | None = None
    velocity: float | None = None
    acceleration: float | None = None

    _ARROW_SCHEMA = _schema(
        ("joint_name", pa.string(), False),
        ("position", pa.float64(), True),
        ("velocity", pa.float64(), True),
        ("acceleration", pa.float64(), True),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.joint_name:
            raise ValueError("joint_name must be non-empty")
        tolerances = (self.position, self.velocity, self.acceleration)
        if all(value is None for value in tolerances):
            raise ValueError(
                "at least one of position, velocity, or acceleration must be specified"
            )
        if any(
            value is not None and (not math.isfinite(value) or value < 0.0)
            for value in tolerances
        ):
            raise ValueError("specified tolerances must be finite and non-negative")
        return self


class FollowJointTrajectoryGoal(_ArrowMessage):
    """Payload for a FollowJointTrajectory action goal."""

    trajectory: JointTrajectory
    path_tolerance: list[JointTolerance]
    goal_tolerance: list[JointTolerance]
    goal_time_tolerance_ns: int | None = None

    _ARROW_SCHEMA = _schema(
        ("trajectory", _JOINT_TRAJECTORY_TYPE, False),
        ("path_tolerance", pa.list_(_JOINT_TOLERANCE_TYPE), False),
        ("goal_tolerance", pa.list_(_JOINT_TOLERANCE_TYPE), False),
        ("goal_time_tolerance_ns", pa.int64(), True),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        trajectory_names = set(self.trajectory.joint_names)
        for field_name in ("path_tolerance", "goal_tolerance"):
            tolerances = getattr(self, field_name)
            names = [tolerance.joint_name for tolerance in tolerances]
            _validate_unique(field_name, names)
            if any(name not in trajectory_names for name in names):
                raise ValueError(
                    f"{field_name} joint names must belong to trajectory.joint_names"
                )
        _validate_non_negative("goal_time_tolerance_ns", self.goal_time_tolerance_ns)
        return self


class FollowJointTrajectoryFeedback(_ArrowMessage):
    """Desired, actual, and error samples for an executing trajectory goal."""

    sequence: int
    point_index: int
    elapsed_ns: int
    duration_ns: int
    desired: JointTrajectoryPoint
    actual: JointTrajectoryPoint
    error: JointTrajectoryPoint

    _ARROW_SCHEMA = _schema(
        ("sequence", pa.uint64(), False),
        ("point_index", pa.uint32(), False),
        ("elapsed_ns", pa.int64(), False),
        ("duration_ns", pa.int64(), False),
        ("desired", _JOINT_TRAJECTORY_POINT_TYPE, False),
        ("actual", _JOINT_TRAJECTORY_POINT_TYPE, False),
        ("error", _JOINT_TRAJECTORY_POINT_TYPE, False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not 0 <= self.sequence <= _UINT64_MAX:
            raise ValueError("sequence must be in the uint64 range")
        if not 0 <= self.point_index <= _UINT32_MAX:
            raise ValueError("point_index must be in the uint32 range")
        _validate_non_negative("elapsed_ns", self.elapsed_ns)
        _validate_non_negative("duration_ns", self.duration_ns)
        position_lengths = {
            len(self.desired.positions),
            len(self.actual.positions),
            len(self.error.positions),
        }
        if len(position_lengths) != 1:
            raise ValueError(
                "desired, actual, and error must have equal positions lengths"
            )
        return self


class FollowJointTrajectoryResult(_ArrowMessage):
    """Terminal domain result for a FollowJointTrajectory action."""

    error_code: FollowJointTrajectoryErrorCode
    message: str
    elapsed_ns: int
    joint_names: list[str]
    final_position_error: list[float]
    final_velocity_error: list[float]

    _ARROW_SCHEMA = _schema(
        ("error_code", pa.string(), False),
        ("message", pa.string(), False),
        ("elapsed_ns", pa.int64(), False),
        ("joint_names", _STRING_LIST_TYPE, False),
        ("final_position_error", _FLOAT_LIST_TYPE, False),
        ("final_velocity_error", _FLOAT_LIST_TYPE, False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_non_negative("elapsed_ns", self.elapsed_ns)
        if any(not name for name in self.joint_names):
            raise ValueError("joint_names items must be non-empty")
        _validate_unique("joint_names", self.joint_names)
        for name in ("final_position_error", "final_velocity_error"):
            values = getattr(self, name)
            if values and len(values) != len(self.joint_names):
                raise ValueError(
                    f"{name} must be empty or have the same length as joint_names"
                )
        return self
