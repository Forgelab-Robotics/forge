from __future__ import annotations

import math
from typing import Literal, Self

import pyarrow as pa
from pydantic import model_validator

from forge_msgs.pose import Pose
from forge_msgs.trajectory import (
    _ArrowMessage,
    _FLOAT_LIST_TYPE,
    _schema,
    _STRING_LIST_TYPE,
    _validate_non_negative,
    _validate_unique,
)

MotionPhase = Literal[
    "VALIDATING",
    "PLANNING",
    "WAITING_FOR_CONTROLLER",
    "EXECUTING",
    "SETTLING",
]

MotionErrorCode = Literal[
    "SUCCESS",
    "INVALID_GOAL",
    "BUSY",
    "INVALID_GROUP",
    "INVALID_JOINTS",
    "INVALID_FRAME",
    "NO_FRESH_ROBOT_STATE",
    "IK_FAILED",
    "IK_TIMED_OUT",
    "JOINT_LIMIT_VIOLATION",
    "PLANNING_FAILED",
    "TRAJECTORY_GENERATION_FAILED",
    "TRAJECTORY_REJECTED",
    "TRAJECTORY_EXECUTION_FAILED",
    "FINAL_JOINT_TOLERANCE_VIOLATED",
    "FINAL_POSE_TOLERANCE_VIOLATED",
    "CANCELED",
    "INTERNAL_ERROR",
]

_POSE_TYPE = pa.struct(
    [
        pa.field("x", pa.float64(), nullable=False),
        pa.field("y", pa.float64(), nullable=False),
        pa.field("z", pa.float64(), nullable=False),
        pa.field("qx", pa.float64(), nullable=False),
        pa.field("qy", pa.float64(), nullable=False),
        pa.field("qz", pa.float64(), nullable=False),
        pa.field("qw", pa.float64(), nullable=False),
    ]
)


def _validate_scale(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"{name} must be finite and in the interval (0, 1]")


def _validate_progress(progress: float | None) -> None:
    if progress is not None and (
        not math.isfinite(progress) or not 0.0 <= progress <= 1.0
    ):
        raise ValueError("progress must be finite and in the interval [0, 1]")


def _validate_optional_finite_non_negative(
    name: str, value: float | None
) -> None:
    if value is not None and (not math.isfinite(value) or value < 0.0):
        raise ValueError(f"{name} must be finite and non-negative")


def _validate_joint_names(joint_names: list[str], *, empty_allowed: bool) -> None:
    if not empty_allowed and not joint_names:
        raise ValueError("joint_names must contain at least one name")
    if any(not name for name in joint_names):
        raise ValueError("joint_names items must be non-empty")
    _validate_unique("joint_names", joint_names)


def _validate_optional_joint_vector(
    name: str, values: list[float], joint_names: list[str]
) -> None:
    if values and len(values) != len(joint_names):
        raise ValueError(f"{name} must be empty or have the same length as joint_names")


class MoveJointsGoal(_ArrowMessage):
    """Joint target goal for a configured kinematic group motion server."""

    group_name: str
    joint_names: list[str]
    positions: list[float]
    velocity_scale: float
    acceleration_scale: float
    requested_duration_ns: int | None = None

    _ARROW_SCHEMA = _schema(
        ("group_name", pa.string(), False),
        ("joint_names", _STRING_LIST_TYPE, False),
        ("positions", _FLOAT_LIST_TYPE, False),
        ("velocity_scale", pa.float64(), False),
        ("acceleration_scale", pa.float64(), False),
        ("requested_duration_ns", pa.int64(), True),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not self.group_name:
            raise ValueError("group_name must be non-empty")
        _validate_joint_names(self.joint_names, empty_allowed=False)
        if len(self.positions) != len(self.joint_names):
            raise ValueError("positions must contain one value per joint name")
        if any(not math.isfinite(value) for value in self.positions):
            raise ValueError("positions values must be finite")
        _validate_scale("velocity_scale", self.velocity_scale)
        _validate_scale("acceleration_scale", self.acceleration_scale)
        _validate_non_negative("requested_duration_ns", self.requested_duration_ns)
        return self


class MoveJointsFeedback(_ArrowMessage):
    """Planning and execution feedback for a MoveJoints action."""

    phase: MotionPhase
    progress: float | None = None
    elapsed_ns: int
    estimated_duration_ns: int | None = None
    joint_names: list[str]
    actual_positions: list[float]
    target_positions: list[float]
    position_errors: list[float]
    message: str

    _ARROW_SCHEMA = _schema(
        ("phase", pa.string(), False),
        ("progress", pa.float64(), True),
        ("elapsed_ns", pa.int64(), False),
        ("estimated_duration_ns", pa.int64(), True),
        ("joint_names", _STRING_LIST_TYPE, False),
        ("actual_positions", _FLOAT_LIST_TYPE, False),
        ("target_positions", _FLOAT_LIST_TYPE, False),
        ("position_errors", _FLOAT_LIST_TYPE, False),
        ("message", pa.string(), False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_progress(self.progress)
        _validate_non_negative("elapsed_ns", self.elapsed_ns)
        _validate_non_negative(
            "estimated_duration_ns", self.estimated_duration_ns
        )
        _validate_joint_names(self.joint_names, empty_allowed=False)
        if len(self.target_positions) != len(self.joint_names):
            raise ValueError(
                "target_positions must have the same length as joint_names"
            )
        _validate_optional_joint_vector(
            "actual_positions", self.actual_positions, self.joint_names
        )
        _validate_optional_joint_vector(
            "position_errors", self.position_errors, self.joint_names
        )
        return self


class MoveJointsResult(_ArrowMessage):
    """Terminal domain result for a MoveJoints action."""

    error_code: MotionErrorCode
    message: str
    elapsed_ns: int
    joint_names: list[str]
    final_positions: list[float]
    final_position_errors: list[float]

    _ARROW_SCHEMA = _schema(
        ("error_code", pa.string(), False),
        ("message", pa.string(), False),
        ("elapsed_ns", pa.int64(), False),
        ("joint_names", _STRING_LIST_TYPE, False),
        ("final_positions", _FLOAT_LIST_TYPE, False),
        ("final_position_errors", _FLOAT_LIST_TYPE, False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_non_negative("elapsed_ns", self.elapsed_ns)
        _validate_joint_names(self.joint_names, empty_allowed=True)
        _validate_optional_joint_vector(
            "final_positions", self.final_positions, self.joint_names
        )
        _validate_optional_joint_vector(
            "final_position_errors", self.final_position_errors, self.joint_names
        )
        return self


class MovePoseGoal(_ArrowMessage):
    """Cartesian pose target goal for a configured motion server."""

    group_name: str
    reference_frame: str
    target_frame: str
    target_pose: Pose
    velocity_scale: float
    acceleration_scale: float
    requested_duration_ns: int | None = None
    position_tolerance_m: float | None = None
    orientation_tolerance_rad: float | None = None

    _ARROW_SCHEMA = _schema(
        ("group_name", pa.string(), False),
        ("reference_frame", pa.string(), False),
        ("target_frame", pa.string(), False),
        ("target_pose", _POSE_TYPE, False),
        ("velocity_scale", pa.float64(), False),
        ("acceleration_scale", pa.float64(), False),
        ("requested_duration_ns", pa.int64(), True),
        ("position_tolerance_m", pa.float64(), True),
        ("orientation_tolerance_rad", pa.float64(), True),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        for name in ("group_name", "reference_frame", "target_frame"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        _validate_scale("velocity_scale", self.velocity_scale)
        _validate_scale("acceleration_scale", self.acceleration_scale)
        _validate_non_negative("requested_duration_ns", self.requested_duration_ns)
        _validate_optional_finite_non_negative(
            "position_tolerance_m", self.position_tolerance_m
        )
        _validate_optional_finite_non_negative(
            "orientation_tolerance_rad", self.orientation_tolerance_rad
        )
        return self


class MovePoseFeedback(_ArrowMessage):
    """Planning and execution feedback for a MovePose action."""

    phase: MotionPhase
    progress: float | None = None
    elapsed_ns: int
    estimated_duration_ns: int | None = None
    actual_pose: Pose | None = None
    position_error_m: float | None = None
    orientation_error_rad: float | None = None
    message: str

    _ARROW_SCHEMA = _schema(
        ("phase", pa.string(), False),
        ("progress", pa.float64(), True),
        ("elapsed_ns", pa.int64(), False),
        ("estimated_duration_ns", pa.int64(), True),
        ("actual_pose", _POSE_TYPE, True),
        ("position_error_m", pa.float64(), True),
        ("orientation_error_rad", pa.float64(), True),
        ("message", pa.string(), False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_progress(self.progress)
        _validate_non_negative("elapsed_ns", self.elapsed_ns)
        _validate_non_negative(
            "estimated_duration_ns", self.estimated_duration_ns
        )
        _validate_optional_finite_non_negative(
            "position_error_m", self.position_error_m
        )
        _validate_optional_finite_non_negative(
            "orientation_error_rad", self.orientation_error_rad
        )
        return self


class MovePoseResult(_ArrowMessage):
    """Terminal domain result for a MovePose action."""

    error_code: MotionErrorCode
    message: str
    elapsed_ns: int
    final_pose: Pose | None = None
    final_position_error_m: float | None = None
    final_orientation_error_rad: float | None = None
    joint_names: list[str]
    final_joint_positions: list[float]

    _ARROW_SCHEMA = _schema(
        ("error_code", pa.string(), False),
        ("message", pa.string(), False),
        ("elapsed_ns", pa.int64(), False),
        ("final_pose", _POSE_TYPE, True),
        ("final_position_error_m", pa.float64(), True),
        ("final_orientation_error_rad", pa.float64(), True),
        ("joint_names", _STRING_LIST_TYPE, False),
        ("final_joint_positions", _FLOAT_LIST_TYPE, False),
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_non_negative("elapsed_ns", self.elapsed_ns)
        _validate_optional_finite_non_negative(
            "final_position_error_m", self.final_position_error_m
        )
        _validate_optional_finite_non_negative(
            "final_orientation_error_rad", self.final_orientation_error_rad
        )
        _validate_joint_names(self.joint_names, empty_allowed=True)
        _validate_optional_joint_vector(
            "final_joint_positions", self.final_joint_positions, self.joint_names
        )
        return self
