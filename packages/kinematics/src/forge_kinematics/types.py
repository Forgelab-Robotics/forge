"""Public value types for Forge kinematics."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from numbers import Integral, Real
from typing import cast

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]


def _finite_float(name: str, value: object, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    if nonnegative and result < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return result


def _array_from_bytes(data: bytes, shape: tuple[int, ...]) -> FloatArray:
    """Create an independent read-only ndarray view over immutable storage."""

    return np.frombuffer(data, dtype=np.float64).reshape(shape)


def _array_bytes(array: FloatArray) -> bytes:
    """Snapshot an array into canonical immutable C-order storage."""

    return array.tobytes(order="C")


def _vector_data(name: str, value: object, size: int) -> bytes:
    try:
        array = np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a numeric vector") from exc
    if array.ndim != 1 or array.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},)")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return _array_bytes(array)


def _optional_arrays_equal(left: FloatArray | None, right: FloatArray | None) -> bool:
    if left is None or right is None:
        return left is right
    return bool(np.array_equal(left, right))


@dataclass(frozen=True, eq=False, init=False)
class PoseTarget:
    """A desired pose for one configured tip frame.

    Array accessors return independent read-only views so callers cannot mutate
    either the numeric contents or the stored shape/dtype metadata.
    """

    tip_frame: str
    reference_frame: str
    position_weight: float
    orientation_weight: float
    task_weights: tuple[float, float, float, float, float, float]
    _pose_data: bytes = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        tip_frame: str,
        pose: object,
        reference_frame: str,
        position_weight: float = 1.0,
        orientation_weight: float = 1.0,
        task_weights: Sequence[float] = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    ) -> None:
        if not isinstance(tip_frame, str):
            raise TypeError("tip_frame must be a string")
        if not tip_frame.strip():
            raise ValueError("tip_frame must not be empty")
        if not isinstance(reference_frame, str):
            raise TypeError("reference_frame must be a string")
        if not reference_frame.strip():
            raise ValueError("reference_frame must not be empty")

        try:
            pose_array = np.array(pose, dtype=np.float64, copy=True)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("pose must be a numeric 4x4 matrix") from exc
        if pose_array.shape != (4, 4):
            raise ValueError("pose must have shape (4, 4)")
        if not np.all(np.isfinite(pose_array)):
            raise ValueError("pose must contain only finite values")
        if not np.allclose(
            pose_array[3],
            np.array([0.0, 0.0, 0.0, 1.0]),
            rtol=0.0,
            atol=1e-9,
        ):
            raise ValueError("pose last row must be [0, 0, 0, 1]")

        rotation = pose_array[:3, :3]
        if not np.allclose(
            rotation.T @ rotation,
            np.eye(3),
            rtol=1e-6,
            atol=1e-6,
        ):
            raise ValueError("pose rotation must be approximately orthogonal")
        determinant = float(np.linalg.det(rotation))
        if not math.isclose(determinant, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("pose rotation determinant must be approximately 1")

        canonical_position_weight = _finite_float(
            "position_weight", position_weight, nonnegative=True
        )
        canonical_orientation_weight = _finite_float(
            "orientation_weight", orientation_weight, nonnegative=True
        )
        if isinstance(task_weights, (str, bytes)) or not isinstance(
            task_weights, Sequence
        ):
            raise TypeError("task_weights must be a sequence")
        if len(task_weights) != 6:
            raise ValueError("task_weights must contain exactly 6 values")
        canonical_task_weights = cast(
            tuple[float, float, float, float, float, float],
            tuple(
                _finite_float(f"task_weights[{index}]", value, nonnegative=True)
                for index, value in enumerate(task_weights)
            ),
        )
        effective_weights = tuple(
            _finite_float(
                f"effective_task_weights[{index}]",
                task_weight * overall_weight,
                nonnegative=True,
            )
            for index, (task_weight, overall_weight) in enumerate(
                zip(
                    canonical_task_weights,
                    (canonical_position_weight,) * 3
                    + (canonical_orientation_weight,) * 3,
                    strict=True,
                )
            )
        )
        if not any(weight > 0.0 for weight in effective_weights):
            raise ValueError(
                "at least one effective pose target weight must be greater than zero"
            )

        object.__setattr__(self, "tip_frame", tip_frame)
        object.__setattr__(self, "reference_frame", reference_frame)
        object.__setattr__(self, "position_weight", canonical_position_weight)
        object.__setattr__(self, "orientation_weight", canonical_orientation_weight)
        object.__setattr__(self, "task_weights", canonical_task_weights)
        object.__setattr__(self, "_pose_data", _array_bytes(pose_array))

    @property
    def pose(self) -> FloatArray:
        """An independent read-only ``(4, 4)`` target-pose view."""

        return _array_from_bytes(self._pose_data, (4, 4))

    @property
    def effective_task_weights(
        self,
    ) -> tuple[float, float, float, float, float, float]:
        """Per-axis task weights after applying compatibility scale factors."""

        return cast(
            tuple[float, float, float, float, float, float],
            tuple(
                task_weight * overall_weight
                for task_weight, overall_weight in zip(
                    self.task_weights,
                    (self.position_weight,) * 3 + (self.orientation_weight,) * 3,
                    strict=True,
                )
            ),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PoseTarget):
            return NotImplemented
        return (
            self.tip_frame == other.tip_frame
            and self.reference_frame == other.reference_frame
            and self.position_weight == other.position_weight
            and self.orientation_weight == other.orientation_weight
            and self.task_weights == other.task_weights
            and bool(np.array_equal(self.pose, other.pose))
        )

    def __deepcopy__(self, memo: dict[int, object]) -> PoseTarget:
        return self

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        return (
            type(self),
            (
                self.tip_frame,
                self.pose,
                self.reference_frame,
                self.position_weight,
                self.orientation_weight,
                self.task_weights,
            ),
        )


class IKStatus(str, Enum):
    """Terminal state of an inverse-kinematics solve."""

    SUCCESS = "SUCCESS"
    NO_SOLUTION = "NO_SOLUTION"
    TIMED_OUT = "TIMED_OUT"
    MAX_ITERATIONS = "MAX_ITERATIONS"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    REJECTED_BY_VALIDATOR = "REJECTED_BY_VALIDATOR"


@dataclass(frozen=True)
class IKOptions:
    """Backend-independent controls for one inverse-kinematics request."""

    timeout_s: float = 0.05
    position_tolerance_m: float = 1e-4
    orientation_tolerance_rad: float = 1e-3
    max_solution_joint_displacement: float | None = None
    allow_approximate_solution: bool = False

    def __post_init__(self) -> None:
        timeout_s = _finite_float("timeout_s", self.timeout_s, nonnegative=True)
        if timeout_s == 0.0:
            raise ValueError("timeout_s must be greater than zero")
        position_tolerance_m = _finite_float(
            "position_tolerance_m", self.position_tolerance_m, nonnegative=True
        )
        if position_tolerance_m == 0.0:
            raise ValueError("position_tolerance_m must be greater than zero")
        orientation_tolerance_rad = _finite_float(
            "orientation_tolerance_rad",
            self.orientation_tolerance_rad,
            nonnegative=True,
        )
        if orientation_tolerance_rad == 0.0:
            raise ValueError("orientation_tolerance_rad must be greater than zero")
        max_solution_joint_displacement = None
        if self.max_solution_joint_displacement is not None:
            max_solution_joint_displacement = _finite_float(
                "max_solution_joint_displacement",
                self.max_solution_joint_displacement,
                nonnegative=True,
            )
        if not isinstance(self.allow_approximate_solution, bool):
            raise TypeError("allow_approximate_solution must be a bool")

        object.__setattr__(self, "timeout_s", timeout_s)
        object.__setattr__(self, "position_tolerance_m", position_tolerance_m)
        object.__setattr__(self, "orientation_tolerance_rad", orientation_tolerance_rad)
        object.__setattr__(
            self,
            "max_solution_joint_displacement",
            max_solution_joint_displacement,
        )


@dataclass(frozen=True, eq=False, init=False)
class IKResult:
    """The outcome and diagnostics of an inverse-kinematics solve."""

    status: IKStatus
    joint_names: tuple[str, ...]
    iterations: int
    elapsed_s: float
    raw_position_error_m: float
    raw_orientation_error_rad: float
    active_position_error_m: float
    active_orientation_error_rad: float
    minimum_singular_value: float | None
    message: str
    effective_damping: float | None
    minimum_joint_limit_margin: float | None
    joint_limit_avoidance_activity: float
    seed_was_projected: bool
    _solution_data: bytes | None = field(repr=False)
    _approximate_solution_data: bytes | None = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        status: IKStatus,
        joint_names: tuple[str, ...],
        solution: object | None,
        approximate_solution: object | None,
        iterations: int,
        elapsed_s: float,
        raw_position_error_m: float,
        raw_orientation_error_rad: float,
        active_position_error_m: float,
        active_orientation_error_rad: float,
        minimum_singular_value: float | None,
        message: str,
        effective_damping: float | None = None,
        minimum_joint_limit_margin: float | None = None,
        joint_limit_avoidance_activity: float = 0.0,
        seed_was_projected: bool = False,
    ) -> None:
        if not isinstance(status, IKStatus):
            raise TypeError("status must be an IKStatus")
        if not isinstance(joint_names, tuple):
            raise TypeError("joint_names must be a tuple")
        if any(not isinstance(name, str) or not name.strip() for name in joint_names):
            raise ValueError("joint_names must contain only non-empty strings")
        if len(set(joint_names)) != len(joint_names):
            raise ValueError("joint_names must not contain duplicates")

        solution_data = (
            None
            if solution is None
            else _vector_data("solution", solution, len(joint_names))
        )
        approximate_solution_data = (
            None
            if approximate_solution is None
            else _vector_data(
                "approximate_solution", approximate_solution, len(joint_names)
            )
        )
        if status is IKStatus.SUCCESS and solution_data is None:
            raise ValueError("a successful result must contain solution")
        if status is not IKStatus.SUCCESS and solution_data is not None:
            raise ValueError("a failed result must not contain solution")
        if (
            status in {IKStatus.SUCCESS, IKStatus.REJECTED_BY_VALIDATOR}
            and approximate_solution_data is not None
        ):
            raise ValueError(
                f"a {status.value} result must not contain approximate_solution"
            )

        if isinstance(iterations, bool) or not isinstance(iterations, Integral):
            raise TypeError("iterations must be an integer")
        canonical_iterations = int(iterations)
        if canonical_iterations < 0:
            raise ValueError("iterations must be non-negative")

        canonical_elapsed_s = _finite_float("elapsed_s", elapsed_s, nonnegative=True)
        canonical_raw_position_error_m = _finite_float(
            "raw_position_error_m", raw_position_error_m, nonnegative=True
        )
        canonical_raw_orientation_error_rad = _finite_float(
            "raw_orientation_error_rad", raw_orientation_error_rad, nonnegative=True
        )
        canonical_active_position_error_m = _finite_float(
            "active_position_error_m", active_position_error_m, nonnegative=True
        )
        canonical_active_orientation_error_rad = _finite_float(
            "active_orientation_error_rad",
            active_orientation_error_rad,
            nonnegative=True,
        )
        canonical_minimum_singular_value = None
        if minimum_singular_value is not None:
            canonical_minimum_singular_value = _finite_float(
                "minimum_singular_value", minimum_singular_value, nonnegative=True
            )
        canonical_effective_damping = None
        if effective_damping is not None:
            canonical_effective_damping = _finite_float(
                "effective_damping", effective_damping, nonnegative=True
            )
        canonical_minimum_joint_limit_margin = None
        if minimum_joint_limit_margin is not None:
            canonical_minimum_joint_limit_margin = _finite_float(
                "minimum_joint_limit_margin",
                minimum_joint_limit_margin,
                nonnegative=True,
            )
        canonical_avoidance_activity = _finite_float(
            "joint_limit_avoidance_activity",
            joint_limit_avoidance_activity,
            nonnegative=True,
        )
        if not isinstance(seed_was_projected, bool):
            raise TypeError("seed_was_projected must be a bool")
        if not isinstance(message, str):
            raise TypeError("message must be a string")

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "joint_names", joint_names)
        object.__setattr__(self, "iterations", canonical_iterations)
        object.__setattr__(self, "elapsed_s", canonical_elapsed_s)
        object.__setattr__(self, "raw_position_error_m", canonical_raw_position_error_m)
        object.__setattr__(
            self, "raw_orientation_error_rad", canonical_raw_orientation_error_rad
        )
        object.__setattr__(
            self, "active_position_error_m", canonical_active_position_error_m
        )
        object.__setattr__(
            self,
            "active_orientation_error_rad",
            canonical_active_orientation_error_rad,
        )
        object.__setattr__(
            self, "minimum_singular_value", canonical_minimum_singular_value
        )
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "effective_damping", canonical_effective_damping)
        object.__setattr__(
            self,
            "minimum_joint_limit_margin",
            canonical_minimum_joint_limit_margin,
        )
        object.__setattr__(
            self, "joint_limit_avoidance_activity", canonical_avoidance_activity
        )
        object.__setattr__(self, "seed_was_projected", seed_was_projected)
        object.__setattr__(self, "_solution_data", solution_data)
        object.__setattr__(
            self, "_approximate_solution_data", approximate_solution_data
        )

    @property
    def solution(self) -> FloatArray | None:
        """An independent read-only exact-solution view, when successful."""

        if self._solution_data is None:
            return None
        return _array_from_bytes(self._solution_data, (len(self.joint_names),))

    @property
    def approximate_solution(self) -> FloatArray | None:
        """An independent read-only best-effort solution view, when requested."""

        if self._approximate_solution_data is None:
            return None
        return _array_from_bytes(
            self._approximate_solution_data, (len(self.joint_names),)
        )

    @property
    def success(self) -> bool:
        """Whether the solver met every configured pose tolerance."""

        return self.status is IKStatus.SUCCESS

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IKResult):
            return NotImplemented
        return (
            self.status is other.status
            and self.joint_names == other.joint_names
            and _optional_arrays_equal(self.solution, other.solution)
            and _optional_arrays_equal(
                self.approximate_solution, other.approximate_solution
            )
            and self.iterations == other.iterations
            and self.elapsed_s == other.elapsed_s
            and self.raw_position_error_m == other.raw_position_error_m
            and self.raw_orientation_error_rad == other.raw_orientation_error_rad
            and self.active_position_error_m == other.active_position_error_m
            and self.active_orientation_error_rad == other.active_orientation_error_rad
            and self.minimum_singular_value == other.minimum_singular_value
            and self.message == other.message
            and self.effective_damping == other.effective_damping
            and self.minimum_joint_limit_margin == other.minimum_joint_limit_margin
            and self.joint_limit_avoidance_activity
            == other.joint_limit_avoidance_activity
            and self.seed_was_projected == other.seed_was_projected
        )

    def __deepcopy__(self, memo: dict[int, object]) -> IKResult:
        return self

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        return (
            type(self),
            (
                self.status,
                self.joint_names,
                self.solution,
                self.approximate_solution,
                self.iterations,
                self.elapsed_s,
                self.raw_position_error_m,
                self.raw_orientation_error_rad,
                self.active_position_error_m,
                self.active_orientation_error_rad,
                self.minimum_singular_value,
                self.message,
                self.effective_damping,
                self.minimum_joint_limit_margin,
                self.joint_limit_avoidance_activity,
                self.seed_was_projected,
            ),
        )
