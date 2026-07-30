"""Shared pose-error linearization and solver diagnostics."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from .model import _GroupEvaluation
from .types import PoseTarget

type FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True)
class _IterationEvaluation:
    weighted_error: FloatArray
    weighted_jacobian: FloatArray
    raw_position_error_m: float
    raw_orientation_error_rad: float
    active_position_error_m: float
    active_orientation_error_rad: float
    weighted_residual: float


def _skew(vector: FloatArray) -> FloatArray:
    """Return the skew-symmetric matrix representing a three-vector."""

    return np.array(
        [
            [0.0, -vector[2], vector[1]],
            [vector[2], 0.0, -vector[0]],
            [-vector[1], vector[0], 0.0],
        ],
        dtype=np.float64,
    )


def _so3_log(rotation: FloatArray) -> FloatArray:
    """Return the principal SO(3) logarithm as a base-aligned rotation vector."""

    cosine = float(np.clip((np.trace(rotation) - 1.0) * 0.5, -1.0, 1.0))
    angle = math.acos(cosine)
    skew_vector = np.array(
        [
            rotation[2, 1] - rotation[1, 2],
            rotation[0, 2] - rotation[2, 0],
            rotation[1, 0] - rotation[0, 1],
        ],
        dtype=np.float64,
    )
    if angle < 1e-8:
        return 0.5 * skew_vector
    # The skew formula loses precision as sin(angle) approaches zero. Switch
    # early enough that the returned vector remains principal and well scaled.
    if math.pi - angle < 1e-3:
        symmetric = 0.5 * (rotation + rotation.T)
        eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
        axis = np.array(
            eigenvectors[:, int(np.argmax(eigenvalues))],
            dtype=np.float64,
            copy=True,
        )
        norm = float(np.linalg.norm(axis))
        if not math.isfinite(norm) or norm < 1e-12:
            raise FloatingPointError("could not determine SO(3) log axis")
        axis /= norm
        alignment = float(axis @ skew_vector)
        if abs(alignment) > 1e-12:
            if alignment < 0.0:
                axis = -axis
        else:
            significant = np.flatnonzero(np.abs(axis) > 1e-12)
            if significant.size and axis[int(significant[0])] < 0.0:
                axis = -axis
        return angle * axis
    return (angle / (2.0 * math.sin(angle))) * skew_vector


def _so3_right_jacobian_inverse(rotation_vector: FloatArray) -> FloatArray:
    """Return the inverse SO(3) right Jacobian for a rotation vector."""

    angle_squared = float(rotation_vector @ rotation_vector)
    rotation_skew = _skew(rotation_vector)
    if angle_squared < 1e-8:
        coefficient = (
            1.0 / 12.0 + angle_squared / 720.0 + angle_squared * angle_squared / 30240.0
        )
    else:
        angle = math.sqrt(angle_squared)
        half_angle = 0.5 * angle
        coefficient = (1.0 - half_angle / math.tan(half_angle)) / angle_squared
    return (
        np.eye(3, dtype=np.float64)
        + 0.5 * rotation_skew
        + coefficient * (rotation_skew @ rotation_skew)
    )


def _evaluate_iteration(
    evaluation: _GroupEvaluation,
    targets: tuple[PoseTarget, ...],
) -> _IterationEvaluation:
    """Linearize all active pose-target axes at one group configuration."""

    error_blocks: list[FloatArray] = []
    jacobian_blocks: list[FloatArray] = []
    position_errors: list[float] = []
    orientation_errors: list[float] = []
    active_position_errors: list[float] = []
    active_orientation_errors: list[float] = []

    for target in targets:
        current_pose = evaluation.poses[target.tip_frame]
        jacobian = evaluation.jacobians[target.tip_frame]
        position_error = target.pose[:3, 3] - current_pose[:3, 3]
        orientation_error = _so3_log(target.pose[:3, :3] @ current_pose[:3, :3].T)
        task_error = np.concatenate((position_error, orientation_error))
        task_jacobian = np.array(jacobian, dtype=np.float64, copy=True)
        task_jacobian[3:, :] = (
            _so3_right_jacobian_inverse(orientation_error) @ jacobian[3:, :]
        )
        effective_weights = np.asarray(target.effective_task_weights, dtype=np.float64)
        enabled_rows = effective_weights > 0.0
        scales = np.sqrt(effective_weights)

        position_errors.append(float(np.linalg.norm(position_error)))
        orientation_errors.append(float(np.linalg.norm(orientation_error)))
        active_position_errors.append(
            float(np.linalg.norm(position_error[enabled_rows[:3]]))
        )
        active_orientation_errors.append(
            float(np.linalg.norm(orientation_error[enabled_rows[3:]]))
        )
        error_blocks.append((scales * task_error)[enabled_rows])
        jacobian_blocks.append((scales[:, np.newaxis] * task_jacobian)[enabled_rows, :])

    weighted_error = np.concatenate(error_blocks)
    weighted_jacobian = np.vstack(jacobian_blocks)
    if not np.all(np.isfinite(weighted_error)) or not np.all(
        np.isfinite(weighted_jacobian)
    ):
        raise FloatingPointError("IK evaluation produced non-finite values")

    raw_position_error_m = max(position_errors)
    raw_orientation_error_rad = max(orientation_errors)
    active_position_error_m = max(active_position_errors)
    active_orientation_error_rad = max(active_orientation_errors)
    weighted_residual = float(weighted_error @ weighted_error)
    values = (
        raw_position_error_m,
        raw_orientation_error_rad,
        active_position_error_m,
        active_orientation_error_rad,
        weighted_residual,
    )
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise FloatingPointError("IK error metrics were non-finite")

    return _IterationEvaluation(
        weighted_error=weighted_error,
        weighted_jacobian=weighted_jacobian,
        raw_position_error_m=raw_position_error_m,
        raw_orientation_error_rad=raw_orientation_error_rad,
        active_position_error_m=active_position_error_m,
        active_orientation_error_rad=active_orientation_error_rad,
        weighted_residual=weighted_residual,
    )


def _minimum_singular_value(jacobian: FloatArray) -> float:
    """Return the smallest represented singular value for a task Jacobian."""

    if jacobian.shape[1] == 0:
        return 0.0
    singular_values = np.linalg.svd(jacobian, compute_uv=False)
    value = 0.0 if singular_values.size == 0 else float(np.min(singular_values))
    if not math.isfinite(value) or value < 0.0:
        raise FloatingPointError("IK singular value was non-finite")
    return value


def _minimum_joint_limit_margin(
    positions: FloatArray,
    lower_limits: FloatArray,
    upper_limits: FloatArray,
) -> float | None:
    """Return the minimum normalized margin from finite two-sided limits."""

    bounded = np.isfinite(lower_limits) & np.isfinite(upper_limits)
    if not np.any(bounded):
        return None

    ranges = upper_limits[bounded] - lower_limits[bounded]
    margins = np.zeros(ranges.shape, dtype=np.float64)
    positive_ranges = ranges > 0.0
    bounded_positions = positions[bounded]
    if np.any(positive_ranges):
        lower_distances = (
            bounded_positions[positive_ranges] - lower_limits[bounded][positive_ranges]
        )
        upper_distances = (
            upper_limits[bounded][positive_ranges] - bounded_positions[positive_ranges]
        )
        margins[positive_ranges] = np.clip(
            2.0
            * np.minimum(lower_distances, upper_distances)
            / ranges[positive_ranges],
            0.0,
            1.0,
        )
    margin = float(np.min(margins))
    if not math.isfinite(margin) or margin < 0.0:
        raise FloatingPointError("joint-limit margin was non-finite")
    return margin
