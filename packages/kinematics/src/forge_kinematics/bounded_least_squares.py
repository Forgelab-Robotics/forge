"""Box-constrained nonlinear least-squares inverse kinematics."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any

import numpy as np
import numpy.typing as npt

try:
    from scipy.optimize import least_squares as _scipy_least_squares
except ImportError:  # pragma: no cover - exercised only without the optional extra.
    _scipy_least_squares = None

from ._solver_math import (
    _IterationEvaluation,
    _evaluate_iteration,
    _minimum_joint_limit_margin,
    _minimum_singular_value,
)
from .model import KinematicGroup
from .request import IKRequest
from .types import IKResult, IKStatus, _finite_float

type FloatArray = npt.NDArray[np.float64]
_MAX_FINITE_FLOAT = float(np.finfo(np.float64).max)
_COLLAPSED_BOUND_EPSILON = 8.0 * float(np.finfo(np.float64).eps)


def _canonical_joint_bounds(value: object) -> Mapping[str, tuple[float, float]]:
    if not isinstance(value, Mapping):
        raise TypeError("joint_position_bounds must be a mapping")
    result: dict[str, tuple[float, float]] = {}
    for name, raw_bounds in value.items():
        if not isinstance(name, str):
            raise TypeError("joint_position_bounds names must be strings")
        if not name.strip():
            raise ValueError("joint_position_bounds names must not be empty")
        if isinstance(raw_bounds, (str, bytes)) or not isinstance(raw_bounds, Sequence):
            raise TypeError(f"joint_position_bounds[{name!r}] must be a sequence")
        if len(raw_bounds) != 2:
            raise ValueError(
                f"joint_position_bounds[{name!r}] must contain lower and upper"
            )
        lower = _finite_float(f"joint_position_bounds[{name!r}][0]", raw_bounds[0])
        upper = _finite_float(f"joint_position_bounds[{name!r}][1]", raw_bounds[1])
        if lower > upper:
            raise ValueError(
                f"joint_position_bounds[{name!r}] lower must not exceed upper"
            )
        result[name] = (lower, upper)
    return MappingProxyType(result)


def _canonical_joint_margins(value: object) -> Mapping[str, float]:
    if not isinstance(value, Mapping):
        raise TypeError("joint_limit_margins must be a mapping")
    result: dict[str, float] = {}
    for name, raw_margin in value.items():
        if not isinstance(name, str):
            raise TypeError("joint_limit_margins names must be strings")
        if not name.strip():
            raise ValueError("joint_limit_margins names must not be empty")
        result[name] = _finite_float(
            f"joint_limit_margins[{name!r}]", raw_margin, nonnegative=True
        )
    return MappingProxyType(result)


@dataclass(frozen=True)
class BoundedLeastSquaresConfig:
    """Construction-time controls for bounded nonlinear least-squares IK.

    ``joint_position_bounds`` define optional per-joint solve bounds in each
    joint's native unit. ``joint_limit_margins`` shrink the corresponding URDF
    limits from both finite sides. Both are interior box constraints for free
    joints; dynamic fixed joints remain validated against the URDF hard limits.
    """

    max_nfev: int = 20
    ftol: float = 1e-8
    xtol: float = 1e-8
    gtol: float = 1e-8
    regularization_weight: float = 0.0
    smooth_weight: float = 0.0
    joint_position_bounds: Mapping[str, tuple[float, float]] = field(
        default_factory=dict
    )
    joint_limit_margins: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.max_nfev, bool) or not isinstance(self.max_nfev, Integral):
            raise TypeError("max_nfev must be an integer")
        max_nfev = int(self.max_nfev)
        if max_nfev <= 0:
            raise ValueError("max_nfev must be greater than zero")

        tolerances: dict[str, float] = {}
        machine_epsilon = float(np.finfo(np.float64).eps)
        for name, raw_value in (
            ("ftol", self.ftol),
            ("xtol", self.xtol),
            ("gtol", self.gtol),
        ):
            value = _finite_float(name, raw_value, nonnegative=True)
            if value <= machine_epsilon:
                raise ValueError(f"{name} must be greater than float64 machine epsilon")
            tolerances[name] = value

        regularization_weight = _finite_float(
            "regularization_weight", self.regularization_weight, nonnegative=True
        )
        smooth_weight = _finite_float(
            "smooth_weight", self.smooth_weight, nonnegative=True
        )
        joint_position_bounds = _canonical_joint_bounds(self.joint_position_bounds)
        joint_limit_margins = _canonical_joint_margins(self.joint_limit_margins)
        overlap = set(joint_position_bounds).intersection(joint_limit_margins)
        if overlap:
            raise ValueError(
                "a joint cannot define both joint_position_bounds and "
                f"joint_limit_margins: {sorted(overlap)}"
            )

        object.__setattr__(self, "max_nfev", max_nfev)
        object.__setattr__(self, "ftol", tolerances["ftol"])
        object.__setattr__(self, "xtol", tolerances["xtol"])
        object.__setattr__(self, "gtol", tolerances["gtol"])
        object.__setattr__(self, "regularization_weight", regularization_weight)
        object.__setattr__(self, "smooth_weight", smooth_weight)
        object.__setattr__(self, "joint_position_bounds", joint_position_bounds)
        object.__setattr__(self, "joint_limit_margins", joint_limit_margins)

    __hash__ = None  # type: ignore[assignment]

    def __deepcopy__(self, memo: dict[int, object]) -> BoundedLeastSquaresConfig:
        return self

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        return (
            type(self),
            (
                self.max_nfev,
                self.ftol,
                self.xtol,
                self.gtol,
                self.regularization_weight,
                self.smooth_weight,
                dict(self.joint_position_bounds),
                dict(self.joint_limit_margins),
            ),
        )


@dataclass(frozen=True)
class _CandidateEvaluation:
    positions: FloatArray
    pose: _IterationEvaluation
    residual: FloatArray
    jacobian: FloatArray
    minimum_singular_value: float
    minimum_joint_limit_margin: float | None
    total_residual: float


class _DeadlineExceeded(RuntimeError):
    pass


class _EvaluationBudgetExceeded(RuntimeError):
    pass


class _PoseToleranceReached(RuntimeError):
    def __init__(self, evaluation: _CandidateEvaluation) -> None:
        super().__init__("pose tolerance reached")
        self.evaluation = evaluation


class PinocchioBoundedLeastSquaresSolver:
    """Multi-target Pinocchio IK with SciPy trust-region box constraints."""

    __slots__ = (
        "_config",
        "_continuous_mask",
        "_effective_lower_bounds",
        "_effective_upper_bounds",
        "_group",
    )

    def __init__(
        self,
        group: KinematicGroup,
        config: BoundedLeastSquaresConfig | None = None,
    ) -> None:
        if not isinstance(group, KinematicGroup):
            raise TypeError("group must be a KinematicGroup")
        if config is None:
            config = BoundedLeastSquaresConfig()
        elif not isinstance(config, BoundedLeastSquaresConfig):
            raise TypeError("config must be a BoundedLeastSquaresConfig or None")
        if _scipy_least_squares is None:
            raise ImportError(
                "PinocchioBoundedLeastSquaresSolver requires SciPy; install "
                "forge-kinematics[least-squares]"
            )

        joint_names = group.joint_names
        joint_indices = {name: index for index, name in enumerate(joint_names)}
        configured_names = set(config.joint_position_bounds) | set(
            config.joint_limit_margins
        )
        unknown_names = sorted(configured_names - set(joint_names))
        if unknown_names:
            raise ValueError(
                f"bounded least-squares config contains unknown group joints: "
                f"{unknown_names}"
            )

        hard_lower = group.lower_limits
        hard_upper = group.upper_limits
        effective_lower = hard_lower.copy()
        effective_upper = hard_upper.copy()
        continuous_mask = np.array(
            [joint.joint_type == "continuous" for joint in group._active_joints],
            dtype=np.bool_,
        )
        for name, (lower, upper) in config.joint_position_bounds.items():
            index = joint_indices[name]
            if continuous_mask[index]:
                raise ValueError(
                    f"joint_position_bounds[{name!r}] is ambiguous for a continuous "
                    "joint; use max_solution_joint_displacement for a seed-relative "
                    "manifold bound"
                )
            if lower < hard_lower[index] or upper > hard_upper[index]:
                raise ValueError(
                    f"joint_position_bounds[{name!r}] [{lower}, {upper}] must be "
                    f"inside URDF limits [{hard_lower[index]}, {hard_upper[index]}]"
                )
            effective_lower[index] = lower
            effective_upper[index] = upper

        for name, margin in config.joint_limit_margins.items():
            index = joint_indices[name]
            has_lower = math.isfinite(hard_lower[index])
            has_upper = math.isfinite(hard_upper[index])
            if margin > 0.0 and not has_lower and not has_upper:
                raise ValueError(
                    f"joint_limit_margins[{name!r}] cannot shrink an unbounded joint"
                )
            if has_lower:
                effective_lower[index] = hard_lower[index] + margin
            if has_upper:
                effective_upper[index] = hard_upper[index] - margin

        invalid = np.flatnonzero(effective_lower > effective_upper)
        if invalid.size:
            names = [joint_names[int(index)] for index in invalid]
            raise ValueError(f"configured joint bounds are empty for joints: {names}")

        self._group = group
        self._config = config
        self._continuous_mask = continuous_mask
        self._effective_lower_bounds = effective_lower
        self._effective_upper_bounds = effective_upper

    @property
    def group(self) -> KinematicGroup:
        """The kinematic group solved by this instance."""

        return self._group

    @property
    def config(self) -> BoundedLeastSquaresConfig:
        """The immutable algorithm configuration used by this solver."""

        return self._config

    @property
    def effective_lower_bounds(self) -> FloatArray:
        """Configured free-joint lower solve bounds in group order."""

        return self._effective_lower_bounds.copy()

    @property
    def effective_upper_bounds(self) -> FloatArray:
        """Configured free-joint upper solve bounds in group order."""

        return self._effective_upper_bounds.copy()

    def solve(self, request: IKRequest) -> IKResult:
        """Minimize weighted pose error within the configured joint box."""

        if not isinstance(request, IKRequest):
            raise TypeError("request must be an IKRequest")

        solve_options = request.options
        config = self._config
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
        joint_names = self._group.joint_names
        joint_count = len(joint_names)
        current = np.array(request.seed, dtype=np.float64, copy=True)
        if current.shape != (joint_count,):
            raise ValueError(f"seed must have shape ({joint_count},)")

        seed_was_projected = False
        iterations = 0

        def early_result(status: IKStatus, message: str) -> IKResult:
            return IKResult(
                status=status,
                joint_names=joint_names,
                solution=None,
                approximate_solution=None,
                iterations=iterations,
                elapsed_s=max(0.0, time.perf_counter() - start),
                raw_position_error_m=_MAX_FINITE_FLOAT,
                raw_orientation_error_rad=_MAX_FINITE_FLOAT,
                active_position_error_m=_MAX_FINITE_FLOAT,
                active_orientation_error_rad=_MAX_FINITE_FLOAT,
                minimum_singular_value=None,
                message=message,
                seed_was_projected=seed_was_projected,
            )

        if request.fixed_joint_positions is None:
            raw_fixed_positions: dict[str, float] = {}
        elif isinstance(request.fixed_joint_positions, Mapping):
            raw_fixed_positions = dict(request.fixed_joint_positions)
        else:  # Defensive: IKRequest validates this at construction time.
            raise TypeError("fixed_joint_positions must be a mapping or None")

        hard_lower = self._group.lower_limits
        hard_upper = self._group.upper_limits
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
            if position < hard_lower[index] or position > hard_upper[index]:
                raise ValueError(
                    f"fixed joint {name!r} position {position} is outside "
                    f"[{hard_lower[index]}, {hard_upper[index]}]"
                )
            fixed_indices_list.append(index)
            current[index] = position

        fixed_indices = np.array(fixed_indices_list, dtype=np.int64)
        fixed_mask = np.zeros(joint_count, dtype=np.bool_)
        fixed_mask[fixed_indices] = True
        free_from_request = ~fixed_mask

        clipped_to_hard = np.clip(current, hard_lower, hard_upper)
        if np.any(clipped_to_hard[free_from_request] != current[free_from_request]):
            seed_was_projected = True
        current[free_from_request] = clipped_to_hard[free_from_request]

        if time.perf_counter() >= deadline:
            return early_result(
                IKStatus.TIMED_OUT,
                "IK timed out before canonicalizing the bounded seed",
            )
        try:
            current = self._group.integrate(
                current, np.zeros(joint_count, dtype=np.float64)
            )
        except (ArithmeticError, FloatingPointError, RuntimeError) as exc:
            return early_result(
                IKStatus.NUMERICAL_FAILURE,
                f"failed to canonicalize the bounded IK seed: {exc}",
            )
        if time.perf_counter() >= deadline:
            return early_result(
                IKStatus.TIMED_OUT,
                "IK timed out while canonicalizing the bounded seed",
            )

        fixed_values = current[fixed_indices].copy()
        solve_lower = self._effective_lower_bounds.copy()
        solve_upper = self._effective_upper_bounds.copy()
        solve_lower[fixed_indices] = fixed_values
        solve_upper[fixed_indices] = fixed_values

        projected = np.clip(current, solve_lower, solve_upper)
        if np.any(projected[free_from_request] != current[free_from_request]):
            seed_was_projected = True
        current = projected
        current[fixed_indices] = fixed_values
        effective_seed = current.copy()

        if solve_options.max_solution_joint_displacement is not None:
            displacement = solve_options.max_solution_joint_displacement
            solve_lower[free_from_request] = np.maximum(
                solve_lower[free_from_request],
                effective_seed[free_from_request] - displacement,
            )
            solve_upper[free_from_request] = np.minimum(
                solve_upper[free_from_request],
                effective_seed[free_from_request] + displacement,
            )

        widths = solve_upper - solve_lower
        scales = np.maximum.reduce(
            (
                np.ones(joint_count, dtype=np.float64),
                np.abs(solve_lower),
                np.abs(solve_upper),
            )
        )
        collapsed = np.isfinite(widths) & (widths <= _COLLAPSED_BOUND_EPSILON * scales)
        variable_mask = free_from_request & ~collapsed
        variable_indices = np.flatnonzero(variable_mask)
        constant_positions = effective_seed.copy()

        if time.perf_counter() >= deadline:
            return early_result(
                IKStatus.TIMED_OUT,
                "IK timed out before creating the bounded evaluation context",
            )
        try:
            context = self._group.robot_model.create_context()
        except (ArithmeticError, FloatingPointError, RuntimeError) as exc:
            return early_result(
                IKStatus.NUMERICAL_FAILURE,
                f"failed to create the bounded IK evaluation context: {exc}",
            )

        best_evaluation: _CandidateEvaluation | None = None
        best_pose_residual = math.inf
        best_total_residual = math.inf
        last_evaluation: _CandidateEvaluation | None = None
        cached_variables: FloatArray | None = None
        cached_evaluation: _CandidateEvaluation | None = None
        function_evaluations = 0
        kinematics_evaluations = 0
        zero_delta = np.zeros(joint_count, dtype=np.float64)
        identity = np.eye(variable_indices.size, dtype=np.float64)
        neutral_positions = self._group.neutral_positions
        sqrt_regularization = math.sqrt(config.regularization_weight)
        sqrt_smooth = math.sqrt(config.smooth_weight)

        def pose_is_satisfied(evaluation: _CandidateEvaluation) -> bool:
            return (
                evaluation.pose.active_position_error_m
                <= solve_options.position_tolerance_m
                and evaluation.pose.active_orientation_error_rad
                <= solve_options.orientation_tolerance_rad
            )

        def evaluate_variables(variables: FloatArray) -> _CandidateEvaluation:
            nonlocal best_evaluation
            nonlocal best_pose_residual
            nonlocal best_total_residual
            nonlocal cached_evaluation
            nonlocal cached_variables
            nonlocal kinematics_evaluations
            nonlocal last_evaluation

            if time.perf_counter() >= deadline:
                raise _DeadlineExceeded
            variable_array = np.asarray(variables, dtype=np.float64)
            if variable_array.shape != (variable_indices.size,):
                raise FloatingPointError(
                    "optimizer variable vector has an invalid shape"
                )
            if not np.all(np.isfinite(variable_array)):
                raise FloatingPointError("optimizer variable vector is non-finite")
            if cached_variables is not None and np.array_equal(
                variable_array, cached_variables
            ):
                assert cached_evaluation is not None
                return cached_evaluation

            positions = constant_positions.copy()
            positions[variable_indices] = variable_array
            positions = self._group.integrate(positions, zero_delta)
            positions[fixed_indices] = fixed_values
            feasibility_tolerance = (
                64.0
                * float(np.finfo(np.float64).eps)
                * np.maximum(1.0, np.abs(positions))
            )
            bounded_free = free_from_request & ~self._continuous_mask
            if np.any(
                positions[bounded_free]
                < self._effective_lower_bounds[bounded_free]
                - feasibility_tolerance[bounded_free]
            ) or np.any(
                positions[bounded_free]
                > self._effective_upper_bounds[bounded_free]
                + feasibility_tolerance[bounded_free]
            ):
                raise FloatingPointError(
                    "bounded optimizer produced a joint outside the effective box"
                )
            if solve_options.max_solution_joint_displacement is not None:
                tangent_displacement = self._group.difference(effective_seed, positions)
                displacement_tolerance = (
                    64.0
                    * float(np.finfo(np.float64).eps)
                    * max(1.0, solve_options.max_solution_joint_displacement)
                )
                if np.any(
                    np.abs(tangent_displacement[free_from_request])
                    > solve_options.max_solution_joint_displacement
                    + displacement_tolerance
                ):
                    raise FloatingPointError(
                        "bounded optimizer exceeded max_solution_joint_displacement"
                    )
            if time.perf_counter() >= deadline:
                raise _DeadlineExceeded
            if kinematics_evaluations >= config.max_nfev:
                raise _EvaluationBudgetExceeded
            kinematics_evaluations += 1
            group_evaluation = self._group._evaluate(
                positions,
                target_tips,
                state=request.context_state,
                context=context,
            )
            pose_evaluation = _evaluate_iteration(group_evaluation, ordered_targets)

            residual_blocks = [-pose_evaluation.weighted_error]
            jacobian_blocks = [pose_evaluation.weighted_jacobian[:, variable_indices]]
            if sqrt_regularization > 0.0:
                neutral_delta = self._group.difference(neutral_positions, positions)[
                    variable_indices
                ]
                residual_blocks.append(sqrt_regularization * neutral_delta)
                jacobian_blocks.append(sqrt_regularization * identity)
            if sqrt_smooth > 0.0:
                smooth_delta = self._group.difference(effective_seed, positions)[
                    variable_indices
                ]
                residual_blocks.append(sqrt_smooth * smooth_delta)
                jacobian_blocks.append(sqrt_smooth * identity)

            residual = np.concatenate(residual_blocks)
            jacobian = np.vstack(jacobian_blocks)
            if not np.all(np.isfinite(residual)) or not np.all(np.isfinite(jacobian)):
                raise FloatingPointError(
                    "bounded least-squares residual or Jacobian was non-finite"
                )
            total_residual = float(residual @ residual)
            if not math.isfinite(total_residual) or total_residual < 0.0:
                raise FloatingPointError(
                    "bounded least-squares objective was non-finite"
                )
            minimum_singular_value = _minimum_singular_value(
                pose_evaluation.weighted_jacobian[:, variable_indices]
            )
            joint_limit_margin = _minimum_joint_limit_margin(
                positions, hard_lower, hard_upper
            )
            candidate_evaluation = _CandidateEvaluation(
                positions=positions.copy(),
                pose=pose_evaluation,
                residual=residual,
                jacobian=jacobian,
                minimum_singular_value=minimum_singular_value,
                minimum_joint_limit_margin=joint_limit_margin,
                total_residual=total_residual,
            )
            cached_variables = variable_array.copy()
            cached_evaluation = candidate_evaluation
            last_evaluation = candidate_evaluation

            pose_residual = pose_evaluation.weighted_residual
            if pose_residual < best_pose_residual or (
                pose_residual == best_pose_residual
                and total_residual < best_total_residual
            ):
                best_pose_residual = pose_residual
                best_total_residual = total_residual
                best_evaluation = candidate_evaluation
            if time.perf_counter() >= deadline:
                raise _DeadlineExceeded
            return candidate_evaluation

        def result(
            status: IKStatus,
            message: str,
            *,
            exact_evaluation: _CandidateEvaluation | None = None,
            include_approximate: bool = True,
        ) -> IKResult:
            selected = (
                exact_evaluation if exact_evaluation is not None else last_evaluation
            )
            approximate: FloatArray | None = None
            if (
                include_approximate
                and status is not IKStatus.SUCCESS
                and solve_options.allow_approximate_solution
                and best_evaluation is not None
            ):
                accepted = request.state_validator is None
                if request.state_validator is not None:
                    if time.perf_counter() >= deadline:
                        accepted = False
                        status = IKStatus.TIMED_OUT
                        message = "IK timed out before validating an approximate state"
                    else:
                        candidate_state = self._group.to_robot_state(
                            best_evaluation.positions, request.context_state
                        )
                        if time.perf_counter() >= deadline:
                            accepted = False
                            status = IKStatus.TIMED_OUT
                            message = (
                                "IK timed out before validating an approximate state"
                            )
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
                    approximate = best_evaluation.positions
                    selected = best_evaluation

            if selected is None:
                raw_position_error = _MAX_FINITE_FLOAT
                raw_orientation_error = _MAX_FINITE_FLOAT
                active_position_error = _MAX_FINITE_FLOAT
                active_orientation_error = _MAX_FINITE_FLOAT
                singular_value = None
                joint_limit_margin = None
            else:
                raw_position_error = selected.pose.raw_position_error_m
                raw_orientation_error = selected.pose.raw_orientation_error_rad
                active_position_error = selected.pose.active_position_error_m
                active_orientation_error = selected.pose.active_orientation_error_rad
                singular_value = selected.minimum_singular_value
                joint_limit_margin = selected.minimum_joint_limit_margin

            return IKResult(
                status=status,
                joint_names=joint_names,
                solution=(
                    None
                    if exact_evaluation is None
                    else exact_evaluation.positions.copy()
                ),
                approximate_solution=approximate,
                iterations=iterations,
                elapsed_s=max(0.0, time.perf_counter() - start),
                raw_position_error_m=raw_position_error,
                raw_orientation_error_rad=raw_orientation_error,
                active_position_error_m=active_position_error,
                active_orientation_error_rad=active_orientation_error,
                minimum_singular_value=singular_value,
                message=message,
                minimum_joint_limit_margin=joint_limit_margin,
                seed_was_projected=seed_was_projected,
            )

        def converged_result(evaluation: _CandidateEvaluation) -> IKResult:
            if time.perf_counter() >= deadline:
                return result(
                    IKStatus.TIMED_OUT,
                    "IK timed out before validating the converged state",
                    include_approximate=False,
                )
            if request.state_validator is not None:
                candidate_state = self._group.to_robot_state(
                    evaluation.positions, request.context_state
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
                exact_evaluation=evaluation,
            )

        initial_variables = effective_seed[variable_indices]
        try:
            initial_evaluation = evaluate_variables(initial_variables)
        except _DeadlineExceeded:
            return result(
                IKStatus.TIMED_OUT,
                "IK timed out while evaluating the bounded seed",
            )
        except _EvaluationBudgetExceeded:
            iterations = kinematics_evaluations
            return result(
                IKStatus.MAX_ITERATIONS,
                f"bounded IK reached max_nfev={config.max_nfev}",
            )
        except (ArithmeticError, FloatingPointError, np.linalg.LinAlgError) as exc:
            return result(
                IKStatus.NUMERICAL_FAILURE,
                f"numerical failure while evaluating bounded IK: {exc}",
            )
        except RuntimeError as exc:
            return result(
                IKStatus.NUMERICAL_FAILURE,
                f"Pinocchio failed while evaluating bounded IK: {exc}",
            )

        if pose_is_satisfied(initial_evaluation):
            return converged_result(initial_evaluation)
        if variable_indices.size == 0:
            return result(
                IKStatus.NO_SOLUTION,
                "all bounded group joints are fixed and the target is not satisfied",
            )
        if kinematics_evaluations >= config.max_nfev:
            iterations = kinematics_evaluations
            return result(
                IKStatus.MAX_ITERATIONS,
                f"bounded IK reached max_nfev={config.max_nfev}",
            )

        stop_reason: str | None = None
        least_squares = _scipy_least_squares
        assert least_squares is not None

        def residual(variables: FloatArray) -> FloatArray:
            nonlocal function_evaluations
            function_evaluations += 1
            evaluation = evaluate_variables(variables)
            if pose_is_satisfied(evaluation):
                raise _PoseToleranceReached(evaluation)
            return evaluation.residual

        def jacobian(variables: FloatArray) -> FloatArray:
            if time.perf_counter() >= deadline:
                raise _DeadlineExceeded
            return evaluate_variables(variables).jacobian

        def callback(variables: FloatArray) -> None:
            nonlocal stop_reason
            if time.perf_counter() >= deadline:
                stop_reason = "deadline"
                raise StopIteration

        try:
            optimizer_result: Any = least_squares(
                residual,
                initial_variables,
                jac=jacobian,
                bounds=(
                    solve_lower[variable_indices],
                    solve_upper[variable_indices],
                ),
                method="trf",
                ftol=config.ftol,
                xtol=config.xtol,
                gtol=config.gtol,
                x_scale="jac",
                max_nfev=config.max_nfev,
                callback=callback,
            )
        except _PoseToleranceReached as reached:
            iterations = kinematics_evaluations
            return converged_result(reached.evaluation)
        except _DeadlineExceeded:
            iterations = kinematics_evaluations
            return result(
                IKStatus.TIMED_OUT,
                f"IK timed out after {kinematics_evaluations} kinematics evaluations",
            )
        except _EvaluationBudgetExceeded:
            iterations = kinematics_evaluations
            return result(
                IKStatus.MAX_ITERATIONS,
                f"bounded IK reached max_nfev={config.max_nfev}",
            )
        except StopIteration:
            iterations = kinematics_evaluations
            if stop_reason == "deadline":
                return result(
                    IKStatus.TIMED_OUT,
                    f"IK timed out after {kinematics_evaluations} kinematics evaluations",
                )
            return result(
                IKStatus.NUMERICAL_FAILURE,
                "bounded optimizer stopped without a recognized reason",
            )
        except (ArithmeticError, FloatingPointError, np.linalg.LinAlgError) as exc:
            iterations = kinematics_evaluations
            return result(
                IKStatus.NUMERICAL_FAILURE,
                f"numerical failure in bounded least-squares IK: {exc}",
            )
        except (RuntimeError, ValueError) as exc:
            iterations = kinematics_evaluations
            return result(
                IKStatus.NUMERICAL_FAILURE,
                f"bounded least-squares optimizer failed: {exc}",
            )

        optimizer_nfev = int(getattr(optimizer_result, "nfev", function_evaluations))
        iterations = kinematics_evaluations
        optimizer_status = int(getattr(optimizer_result, "status", -1))
        optimizer_message = str(getattr(optimizer_result, "message", "")).strip()
        if time.perf_counter() >= deadline or (
            optimizer_status == -2 and stop_reason == "deadline"
        ):
            return result(
                IKStatus.TIMED_OUT,
                f"IK timed out after {iterations} kinematics evaluations "
                f"(optimizer nfev={optimizer_nfev})",
            )

        try:
            final_evaluation = evaluate_variables(
                np.asarray(optimizer_result.x, dtype=np.float64)
            )
        except _DeadlineExceeded:
            return result(
                IKStatus.TIMED_OUT,
                f"IK timed out after {iterations} kinematics evaluations "
                f"(optimizer nfev={optimizer_nfev})",
            )
        except _EvaluationBudgetExceeded:
            iterations = kinematics_evaluations
            return result(
                IKStatus.MAX_ITERATIONS,
                f"bounded IK reached max_nfev={config.max_nfev}",
            )
        except (ArithmeticError, FloatingPointError, np.linalg.LinAlgError) as exc:
            return result(
                IKStatus.NUMERICAL_FAILURE,
                f"failed to evaluate the bounded optimizer result: {exc}",
            )
        except RuntimeError as exc:
            return result(
                IKStatus.NUMERICAL_FAILURE,
                f"Pinocchio failed while evaluating the optimizer result: {exc}",
            )

        iterations = kinematics_evaluations
        if pose_is_satisfied(final_evaluation):
            return converged_result(final_evaluation)
        if optimizer_status == 0:
            return result(
                IKStatus.MAX_ITERATIONS,
                f"bounded optimizer reached max_nfev={config.max_nfev}; "
                f"kinematics evaluations={iterations}",
            )
        if optimizer_status in {1, 2, 3, 4}:
            detail = f": {optimizer_message}" if optimizer_message else ""
            return result(
                IKStatus.NO_SOLUTION,
                "bounded optimizer terminated outside the configured pose "
                f"tolerances{detail}",
            )
        return result(
            IKStatus.NUMERICAL_FAILURE,
            f"bounded optimizer returned unexpected status {optimizer_status}: "
            f"{optimizer_message}",
        )
