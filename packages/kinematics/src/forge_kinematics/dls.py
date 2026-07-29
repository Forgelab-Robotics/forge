"""Deterministic damped-least-squares inverse kinematics."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np
import numpy.typing as npt

from .model import KinematicGroup, _GroupEvaluation
from .request import IKRequest
from .types import IKResult, IKStatus, PoseTarget, _finite_float

type FloatArray = npt.NDArray[np.float64]
_MAX_FINITE_FLOAT = float(np.finfo(np.float64).max)


@dataclass(frozen=True)
class DlsConfig:
    """Construction-time controls for the Pinocchio DLS algorithm."""

    max_iterations: int = 100
    damping: float = 0.05
    step_size: float = 1.0
    max_iteration_joint_step: float = 0.2
    singularity_threshold: float = 0.05
    singularity_damping: float = 0.2
    joint_limit_avoidance_weight: float = 0.05

    def __post_init__(self) -> None:
        if isinstance(self.max_iterations, bool) or not isinstance(
            self.max_iterations, Integral
        ):
            raise TypeError("max_iterations must be an integer")
        max_iterations = int(self.max_iterations)
        if max_iterations <= 0:
            raise ValueError("max_iterations must be greater than zero")
        damping = _finite_float("damping", self.damping, nonnegative=True)
        if damping == 0.0:
            raise ValueError("damping must be greater than zero")
        step_size = _finite_float("step_size", self.step_size, nonnegative=True)
        if step_size == 0.0:
            raise ValueError("step_size must be greater than zero")
        max_iteration_joint_step = _finite_float(
            "max_iteration_joint_step",
            self.max_iteration_joint_step,
            nonnegative=True,
        )
        if max_iteration_joint_step == 0.0:
            raise ValueError("max_iteration_joint_step must be greater than zero")
        singularity_threshold = _finite_float(
            "singularity_threshold", self.singularity_threshold, nonnegative=True
        )
        if singularity_threshold == 0.0:
            raise ValueError("singularity_threshold must be greater than zero")
        singularity_damping = _finite_float(
            "singularity_damping", self.singularity_damping, nonnegative=True
        )
        joint_limit_avoidance_weight = _finite_float(
            "joint_limit_avoidance_weight",
            self.joint_limit_avoidance_weight,
            nonnegative=True,
        )

        object.__setattr__(self, "max_iterations", max_iterations)
        object.__setattr__(self, "damping", damping)
        object.__setattr__(self, "step_size", step_size)
        object.__setattr__(self, "max_iteration_joint_step", max_iteration_joint_step)
        object.__setattr__(self, "singularity_threshold", singularity_threshold)
        object.__setattr__(self, "singularity_damping", singularity_damping)
        object.__setattr__(
            self, "joint_limit_avoidance_weight", joint_limit_avoidance_weight
        )


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


def _minimum_joint_limit_margin(
    positions: FloatArray,
    lower_limits: FloatArray,
    upper_limits: FloatArray,
) -> float | None:
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


def _joint_limit_gradient(
    positions: FloatArray,
    lower_limits: FloatArray,
    upper_limits: FloatArray,
) -> tuple[FloatArray, bool]:
    ranges = upper_limits - lower_limits
    avoidable = np.isfinite(lower_limits) & np.isfinite(upper_limits) & (ranges > 0.0)
    gradient = np.zeros(positions.shape, dtype=np.float64)
    if np.any(avoidable):
        centers = 0.5 * (lower_limits[avoidable] + upper_limits[avoidable])
        gradient[avoidable] = (centers - positions[avoidable]) / (
            0.5 * ranges[avoidable]
        )
    if not np.all(np.isfinite(gradient)):
        raise FloatingPointError("joint-limit avoidance gradient was non-finite")
    return gradient, bool(np.any(avoidable))


class PinocchioDlsSolver:
    """Deterministic multi-target damped-least-squares IK solver."""

    __slots__ = ("_config", "_group")

    def __init__(self, group: KinematicGroup, config: DlsConfig | None = None) -> None:
        if not isinstance(group, KinematicGroup):
            raise TypeError("group must be a KinematicGroup")
        if config is None:
            config = DlsConfig()
        elif not isinstance(config, DlsConfig):
            raise TypeError("config must be a DlsConfig or None")
        self._group = group
        self._config = config

    @property
    def group(self) -> KinematicGroup:
        """The kinematic group solved by this instance."""

        return self._group

    @property
    def config(self) -> DlsConfig:
        """The immutable algorithm configuration used by this solver."""

        return self._config

    def solve(self, request: IKRequest) -> IKResult:
        """Solve all requested targets simultaneously without random restarts."""

        if not isinstance(request, IKRequest):
            raise TypeError("request must be an IKRequest")
        solve_options = request.options
        dls_config = self._config
        ordered_targets = request.targets
        target_tips = tuple(target.tip_frame for target in ordered_targets)
        mismatched_references = [
            target.reference_frame
            for target in ordered_targets
            if target.reference_frame != self._group.base_frame
        ]
        if mismatched_references:
            raise ValueError(
                "target reference_frame must equal group.base_frame "
                f"{self._group.base_frame!r}; got {mismatched_references}"
            )
        unknown_tips = [tip for tip in target_tips if tip not in self._group.tip_frames]
        if unknown_tips:
            raise ValueError(
                f"target tip frames are not configured for this group: {unknown_tips}"
            )

        start = time.perf_counter()
        deadline = start + solve_options.timeout_s
        current = np.array(request.seed, dtype=np.float64, copy=True)
        joint_names = self._group.joint_names
        joint_count = len(joint_names)
        if current.shape != (joint_count,):
            raise ValueError(f"seed must have shape ({joint_count},)")

        def early_result(status: IKStatus, message: str) -> IKResult:
            return IKResult(
                status=status,
                joint_names=joint_names,
                solution=None,
                approximate_solution=None,
                iterations=0,
                elapsed_s=max(0.0, time.perf_counter() - start),
                raw_position_error_m=_MAX_FINITE_FLOAT,
                raw_orientation_error_rad=_MAX_FINITE_FLOAT,
                active_position_error_m=_MAX_FINITE_FLOAT,
                active_orientation_error_rad=_MAX_FINITE_FLOAT,
                minimum_singular_value=None,
                message=message,
            )

        if request.fixed_joint_positions is None:
            raw_fixed_positions: dict[str, float] = {}
        elif isinstance(request.fixed_joint_positions, Mapping):
            raw_fixed_positions = dict(request.fixed_joint_positions)
        else:  # Defensive: IKRequest validates this at construction time.
            raise TypeError("fixed_joint_positions must be a mapping or None")

        lower_limits = self._group.lower_limits
        upper_limits = self._group.upper_limits
        joint_indices = {name: index for index, name in enumerate(joint_names)}
        fixed_indices_list: list[int] = []
        for name, raw_position in raw_fixed_positions.items():
            if not isinstance(name, str):
                raise TypeError("fixed joint names must be strings")
            if name not in joint_indices:
                raise ValueError(f"fixed joint {name!r} is not a group joint")
            if isinstance(raw_position, bool) or not isinstance(raw_position, Real):
                raise TypeError(f"fixed joint {name!r} position must be real")
            try:
                position = float(raw_position)
            except OverflowError as exc:
                raise ValueError(
                    f"fixed joint {name!r} position must be finite"
                ) from exc
            if not math.isfinite(position):
                raise ValueError(f"fixed joint {name!r} position must be finite")
            index = joint_indices[name]
            if position < lower_limits[index] or position > upper_limits[index]:
                raise ValueError(
                    f"fixed joint {name!r} position {position} is outside "
                    f"[{lower_limits[index]}, {upper_limits[index]}]"
                )
            fixed_indices_list.append(index)
            current[index] = position

        if np.any(current < lower_limits) or np.any(current > upper_limits):
            raise ValueError("seed must satisfy the configured joint limits")
        try:
            current = self._group.integrate(
                current, np.zeros(joint_count, dtype=np.float64)
            )
        except (ArithmeticError, FloatingPointError, RuntimeError) as exc:
            return early_result(
                IKStatus.NUMERICAL_FAILURE,
                f"failed to canonicalize the IK seed: {exc}",
            )
        effective_seed = current.copy()
        fixed_indices = np.array(fixed_indices_list, dtype=np.int64)
        fixed_values = current[fixed_indices].copy()
        free_mask = np.ones(joint_count, dtype=np.bool_)
        free_mask[fixed_indices] = False
        free_indices = np.flatnonzero(free_mask)
        free_lower_limits = lower_limits[free_indices]
        free_upper_limits = upper_limits[free_indices]

        if time.perf_counter() >= deadline:
            return early_result(
                IKStatus.TIMED_OUT,
                "IK timed out before creating the evaluation context",
            )
        try:
            context = self._group.robot_model.create_context()
        except (ArithmeticError, FloatingPointError, RuntimeError) as exc:
            return early_result(
                IKStatus.NUMERICAL_FAILURE,
                f"failed to create the IK evaluation context: {exc}",
            )
        iterations = 0
        best_positions: FloatArray | None = None
        best_residual = math.inf
        best_raw_position_error = _MAX_FINITE_FLOAT
        best_raw_orientation_error = _MAX_FINITE_FLOAT
        best_active_position_error = _MAX_FINITE_FLOAT
        best_active_orientation_error = _MAX_FINITE_FLOAT
        best_singular_value: float | None = None
        best_effective_damping: float | None = None
        best_joint_limit_margin: float | None = None
        best_avoidance_activity = 0.0
        last_raw_position_error = _MAX_FINITE_FLOAT
        last_raw_orientation_error = _MAX_FINITE_FLOAT
        last_active_position_error = _MAX_FINITE_FLOAT
        last_active_orientation_error = _MAX_FINITE_FLOAT
        last_singular_value: float | None = None
        last_effective_damping: float | None = None
        last_joint_limit_margin = _minimum_joint_limit_margin(
            current, lower_limits, upper_limits
        )
        last_avoidance_activity = 0.0

        def result(
            status: IKStatus,
            message: str,
            *,
            solution: FloatArray | None = None,
            include_approximate: bool = True,
        ) -> IKResult:
            approximate = None
            raw_position_error = last_raw_position_error
            raw_orientation_error = last_raw_orientation_error
            active_position_error = last_active_position_error
            active_orientation_error = last_active_orientation_error
            singular_value = last_singular_value
            effective_damping = last_effective_damping
            joint_limit_margin = last_joint_limit_margin
            avoidance_activity = last_avoidance_activity
            if (
                include_approximate
                and status is not IKStatus.SUCCESS
                and solve_options.allow_approximate_solution
                and best_positions is not None
            ):
                if request.state_validator is None:
                    accepted = True
                elif time.perf_counter() >= deadline:
                    accepted = False
                    status = IKStatus.TIMED_OUT
                    message = "IK timed out before validating an approximate state"
                else:
                    candidate_state = self._group.to_robot_state(
                        best_positions, request.context_state
                    )
                    if time.perf_counter() >= deadline:
                        accepted = False
                        status = IKStatus.TIMED_OUT
                        message = "IK timed out before validating an approximate state"
                    else:
                        accepted = request.state_validator(candidate_state)
                        if not isinstance(accepted, bool):
                            raise TypeError("state_validator must return a bool")
                        if time.perf_counter() >= deadline:
                            status = IKStatus.TIMED_OUT
                            message = (
                                "IK timed out while validating an approximate state"
                            )
                if accepted:
                    approximate = best_positions
                    raw_position_error = best_raw_position_error
                    raw_orientation_error = best_raw_orientation_error
                    active_position_error = best_active_position_error
                    active_orientation_error = best_active_orientation_error
                    singular_value = best_singular_value
                    effective_damping = best_effective_damping
                    joint_limit_margin = best_joint_limit_margin
                    avoidance_activity = best_avoidance_activity
            elapsed = max(0.0, time.perf_counter() - start)
            return IKResult(
                status=status,
                joint_names=joint_names,
                solution=solution,
                approximate_solution=approximate,
                iterations=iterations,
                elapsed_s=elapsed,
                raw_position_error_m=raw_position_error,
                raw_orientation_error_rad=raw_orientation_error,
                active_position_error_m=active_position_error,
                active_orientation_error_rad=active_orientation_error,
                minimum_singular_value=singular_value,
                message=message,
                effective_damping=effective_damping,
                minimum_joint_limit_margin=joint_limit_margin,
                joint_limit_avoidance_activity=avoidance_activity,
            )

        while True:
            if time.perf_counter() >= deadline:
                return result(
                    IKStatus.TIMED_OUT,
                    f"IK timed out after {iterations} iterations",
                )
            try:
                group_evaluation = self._group._evaluate(
                    current,
                    target_tips,
                    state=request.context_state,
                    context=context,
                )
                iteration_evaluation = _evaluate_iteration(
                    group_evaluation, ordered_targets
                )
                free_jacobian = iteration_evaluation.weighted_jacobian[:, free_indices]
                if free_indices.size == 0:
                    minimum_singular_value = 0.0
                    jacobian_rank = 0
                    nullspace_basis = np.empty((0, 0), dtype=np.float64)
                else:
                    _, singular_values, right_singular_vectors_t = np.linalg.svd(
                        free_jacobian, full_matrices=True
                    )
                    minimum_singular_value = (
                        0.0
                        if singular_values.size == 0
                        else float(np.min(singular_values))
                    )
                    if singular_values.size == 0:
                        jacobian_rank = 0
                    else:
                        rank_tolerance = (
                            max(free_jacobian.shape)
                            * np.finfo(np.float64).eps
                            * float(singular_values[0])
                        )
                        jacobian_rank = int(
                            np.count_nonzero(singular_values > rank_tolerance)
                        )
                    nullspace_basis = right_singular_vectors_t[jacobian_rank:, :].T
                if not math.isfinite(minimum_singular_value) or (
                    minimum_singular_value < 0.0
                ):
                    raise FloatingPointError("IK singular value was non-finite")
                singularity_ratio = max(
                    (dls_config.singularity_threshold - minimum_singular_value)
                    / dls_config.singularity_threshold,
                    0.0,
                )
                effective_damping = (
                    dls_config.damping
                    + dls_config.singularity_damping * singularity_ratio**2
                )
                if not math.isfinite(effective_damping):
                    raise FloatingPointError("effective damping was non-finite")
                joint_limit_margin = _minimum_joint_limit_margin(
                    current, lower_limits, upper_limits
                )
                avoidance_gradient, has_avoidable_joint = _joint_limit_gradient(
                    current[free_indices], free_lower_limits, free_upper_limits
                )
                if (
                    dls_config.joint_limit_avoidance_weight > 0.0
                    and has_avoidable_joint
                    and jacobian_rank < free_indices.size
                ):
                    avoidance_activity = min(
                        float(np.linalg.norm(iteration_evaluation.weighted_error)),
                        1.0,
                    )
                else:
                    avoidance_activity = 0.0
                if not math.isfinite(avoidance_activity) or avoidance_activity < 0.0:
                    raise FloatingPointError(
                        "joint-limit avoidance activity was non-finite"
                    )
            except (ArithmeticError, FloatingPointError, np.linalg.LinAlgError) as exc:
                return result(
                    IKStatus.NUMERICAL_FAILURE,
                    f"numerical failure while evaluating IK: {exc}",
                )
            except RuntimeError as exc:
                return result(
                    IKStatus.NUMERICAL_FAILURE,
                    f"Pinocchio failed while evaluating IK: {exc}",
                )

            last_raw_position_error = iteration_evaluation.raw_position_error_m
            last_raw_orientation_error = iteration_evaluation.raw_orientation_error_rad
            last_active_position_error = iteration_evaluation.active_position_error_m
            last_active_orientation_error = (
                iteration_evaluation.active_orientation_error_rad
            )
            last_singular_value = minimum_singular_value
            last_effective_damping = effective_damping
            last_joint_limit_margin = joint_limit_margin
            last_avoidance_activity = avoidance_activity
            if iteration_evaluation.weighted_residual < best_residual:
                best_residual = iteration_evaluation.weighted_residual
                best_positions = current.copy()
                best_raw_position_error = iteration_evaluation.raw_position_error_m
                best_raw_orientation_error = (
                    iteration_evaluation.raw_orientation_error_rad
                )
                best_active_position_error = (
                    iteration_evaluation.active_position_error_m
                )
                best_active_orientation_error = (
                    iteration_evaluation.active_orientation_error_rad
                )
                best_singular_value = minimum_singular_value
                best_effective_damping = effective_damping
                best_joint_limit_margin = joint_limit_margin
                best_avoidance_activity = avoidance_activity

            if time.perf_counter() >= deadline:
                return result(
                    IKStatus.TIMED_OUT,
                    f"IK timed out after {iterations} iterations",
                )
            if (
                iteration_evaluation.active_position_error_m
                <= solve_options.position_tolerance_m
                and iteration_evaluation.active_orientation_error_rad
                <= solve_options.orientation_tolerance_rad
            ):
                if request.state_validator is not None:
                    if time.perf_counter() >= deadline:
                        return result(
                            IKStatus.TIMED_OUT,
                            "IK timed out before validating the converged state",
                            include_approximate=False,
                        )
                    candidate_state = self._group.to_robot_state(
                        current, request.context_state
                    )
                    if time.perf_counter() >= deadline:
                        return result(
                            IKStatus.TIMED_OUT,
                            "IK timed out before validating the converged state",
                            include_approximate=False,
                        )
                    accepted = request.state_validator(candidate_state)
                    if not isinstance(accepted, bool):
                        raise TypeError("state_validator must return a bool")
                    if time.perf_counter() >= deadline:
                        return result(
                            IKStatus.TIMED_OUT,
                            "IK timed out while validating the converged state",
                            include_approximate=False,
                        )
                    if not accepted:
                        return result(
                            IKStatus.REJECTED_BY_VALIDATOR,
                            "the converged robot state was rejected by the validator",
                            include_approximate=False,
                        )
                return result(
                    IKStatus.SUCCESS,
                    "all active pose target axes satisfy the configured tolerances",
                    solution=current.copy(),
                )
            if free_indices.size == 0:
                return result(
                    IKStatus.NO_SOLUTION,
                    "all group joints are fixed and the target is not satisfied",
                )
            if iterations >= dls_config.max_iterations:
                return result(
                    IKStatus.MAX_ITERATIONS,
                    f"IK reached the maximum of {dls_config.max_iterations} iterations",
                )

            error = iteration_evaluation.weighted_error
            system = free_jacobian @ free_jacobian.T
            system += (effective_damping**2) * np.eye(system.shape[0], dtype=np.float64)
            try:
                inverse_error = np.linalg.solve(system, error)
                primary_delta = dls_config.step_size * (free_jacobian.T @ inverse_error)

                step_lower = np.maximum(
                    -dls_config.max_iteration_joint_step,
                    free_lower_limits - current[free_indices],
                )
                step_upper = np.minimum(
                    dls_config.max_iteration_joint_step,
                    free_upper_limits - current[free_indices],
                )
                if solve_options.max_solution_joint_displacement is not None:
                    displacement_from_seed = self._group.difference(
                        effective_seed, current
                    )[free_indices]
                    step_lower = np.maximum(
                        step_lower,
                        -solve_options.max_solution_joint_displacement
                        - displacement_from_seed,
                    )
                    step_upper = np.minimum(
                        step_upper,
                        solve_options.max_solution_joint_displacement
                        - displacement_from_seed,
                    )
                if np.any(step_lower > step_upper):
                    raise FloatingPointError(
                        "IK step constraints produced an empty feasible interval"
                    )
                primary_delta = np.clip(primary_delta, step_lower, step_upper)
                free_delta = primary_delta

                if avoidance_activity > 0.0 and jacobian_rank < free_indices.size:
                    projected_gradient = nullspace_basis @ (
                        nullspace_basis.T @ avoidance_gradient
                    )
                    secondary_delta = (
                        dls_config.step_size
                        * avoidance_activity
                        * dls_config.joint_limit_avoidance_weight
                        * projected_gradient
                    )
                    secondary_scale = 1.0
                    for index, component in enumerate(secondary_delta):
                        if component > 0.0:
                            available = step_upper[index] - primary_delta[index]
                            secondary_scale = min(
                                secondary_scale, float(available / component)
                            )
                        elif component < 0.0:
                            available = step_lower[index] - primary_delta[index]
                            secondary_scale = min(
                                secondary_scale, float(available / component)
                            )
                    secondary_scale = float(np.clip(secondary_scale, 0.0, 1.0))
                    if secondary_scale < 1.0:
                        secondary_scale = float(np.nextafter(secondary_scale, 0.0))
                    free_delta = primary_delta + secondary_scale * secondary_delta
            except np.linalg.LinAlgError as exc:
                return result(
                    IKStatus.NUMERICAL_FAILURE,
                    f"DLS linear solve failed: {exc}",
                )
            except (ArithmeticError, FloatingPointError, RuntimeError) as exc:
                return result(
                    IKStatus.NUMERICAL_FAILURE,
                    f"failed to construct a feasible hierarchical IK step: {exc}",
                )
            if time.perf_counter() >= deadline:
                return result(
                    IKStatus.TIMED_OUT,
                    f"IK timed out after {iterations} iterations",
                )

            if not np.all(np.isfinite(free_delta)):
                return result(
                    IKStatus.NUMERICAL_FAILURE,
                    "DLS update contained non-finite values",
                )
            accepted_candidate: FloatArray | None = None
            trial_scale = 1.0
            for _ in range(21):
                delta = np.zeros(joint_count, dtype=np.float64)
                delta[free_indices] = trial_scale * free_delta
                try:
                    candidate = self._group.integrate(current, delta)
                    candidate[fixed_indices] = fixed_values
                    if time.perf_counter() >= deadline:
                        return result(
                            IKStatus.TIMED_OUT,
                            f"IK timed out after {iterations} iterations",
                        )
                    candidate_group_evaluation = self._group._evaluate(
                        candidate,
                        target_tips,
                        state=request.context_state,
                        context=context,
                    )
                    candidate_evaluation = _evaluate_iteration(
                        candidate_group_evaluation, ordered_targets
                    )
                except (ArithmeticError, FloatingPointError, RuntimeError) as exc:
                    return result(
                        IKStatus.NUMERICAL_FAILURE,
                        f"failed to evaluate an IK line-search candidate: {exc}",
                    )
                if time.perf_counter() >= deadline:
                    return result(
                        IKStatus.TIMED_OUT,
                        f"IK timed out after {iterations} iterations",
                    )
                if (
                    candidate_evaluation.weighted_residual
                    < iteration_evaluation.weighted_residual
                ):
                    accepted_candidate = candidate
                    break
                trial_scale *= 0.5

            if accepted_candidate is None:
                return result(
                    IKStatus.NO_SOLUTION,
                    "IK line search could not find a residual-reducing step",
                )
            current = accepted_candidate
            iterations += 1
