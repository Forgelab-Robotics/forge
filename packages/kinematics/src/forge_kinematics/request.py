"""Validated request values for inverse-kinematics solvers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from numbers import Real
from types import MappingProxyType

import numpy as np
import numpy.typing as npt

from .model import RobotState
from .types import (
    IKOptions,
    PoseTarget,
    _array_bytes,
    _array_from_bytes,
    _finite_float,
)

type FloatArray = npt.NDArray[np.float64]
type StateValidator = Callable[[RobotState], bool]
_DEFAULT_OPTIONS = IKOptions()


@dataclass(frozen=True, eq=False, init=False)
class IKRequest:
    """One immutable, solver-independent inverse-kinematics request.

    Requests containing a model-bound ``context_state`` or an executable
    ``state_validator`` are intentionally not pickleable. Portable requests are
    reconstructed through this validated constructor.
    """

    targets: tuple[PoseTarget, ...]
    options: IKOptions
    context_state: RobotState | None
    fixed_joint_positions: Mapping[str, float] | None
    state_validator: StateValidator | None
    _seed_data: bytes = field(repr=False)

    __hash__ = None  # type: ignore[assignment]

    def __init__(
        self,
        seed: object,
        targets: object,
        options: IKOptions = _DEFAULT_OPTIONS,
        context_state: RobotState | None = None,
        fixed_joint_positions: Mapping[str, float] | None = None,
        state_validator: StateValidator | None = None,
    ) -> None:
        try:
            seed_array = np.array(seed, dtype=np.float64, copy=True)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("seed must be a numeric vector") from exc
        if seed_array.ndim != 1:
            raise ValueError("seed must be one-dimensional")
        if not np.all(np.isfinite(seed_array)):
            raise ValueError("seed must contain only finite values")

        if isinstance(targets, (str, bytes)) or not isinstance(targets, Iterable):
            raise TypeError("targets must be an iterable of PoseTarget values")
        supplied_targets = tuple(targets)
        if not supplied_targets:
            raise ValueError("targets must not be empty")
        if any(not isinstance(target, PoseTarget) for target in supplied_targets):
            raise TypeError("targets must contain only PoseTarget values")
        canonical_targets = tuple(
            PoseTarget(
                target.tip_frame,
                target.pose,
                target.reference_frame,
                target.position_weight,
                target.orientation_weight,
                target.task_weights,
            )
            for target in supplied_targets
        )
        tip_frames = tuple(target.tip_frame for target in canonical_targets)
        if len(set(tip_frames)) != len(tip_frames):
            raise ValueError("targets must not contain duplicate tip frames")

        if not isinstance(options, IKOptions):
            raise TypeError("options must be an IKOptions")
        if context_state is not None and not isinstance(context_state, RobotState):
            raise TypeError("context_state must be a RobotState or None")

        canonical_fixed_positions = None
        if fixed_joint_positions is not None:
            if not isinstance(fixed_joint_positions, Mapping):
                raise TypeError("fixed_joint_positions must be a mapping or None")
            snapshot: dict[str, float] = {}
            for name, raw_position in fixed_joint_positions.items():
                if not isinstance(name, str):
                    raise TypeError("fixed joint names must be strings")
                if not name.strip():
                    raise ValueError("fixed joint names must not be empty")
                if isinstance(raw_position, bool) or not isinstance(raw_position, Real):
                    raise TypeError(f"fixed joint {name!r} position must be real")
                snapshot[name] = _finite_float(
                    f"fixed joint {name!r} position", raw_position
                )
            canonical_fixed_positions = MappingProxyType(snapshot)

        if state_validator is not None and not callable(state_validator):
            raise TypeError("state_validator must be callable or None")

        object.__setattr__(self, "targets", canonical_targets)
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "context_state", context_state)
        object.__setattr__(self, "fixed_joint_positions", canonical_fixed_positions)
        object.__setattr__(self, "state_validator", state_validator)
        object.__setattr__(self, "_seed_data", _array_bytes(seed_array))

    @property
    def seed(self) -> FloatArray:
        """An independent read-only one-dimensional seed view."""

        return _array_from_bytes(self._seed_data, (len(self._seed_data) // 8,))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IKRequest):
            return NotImplemented
        return (
            bool(np.array_equal(self.seed, other.seed))
            and self.targets == other.targets
            and self.options == other.options
            and self.context_state is other.context_state
            and (
                None
                if self.fixed_joint_positions is None
                else dict(self.fixed_joint_positions)
            )
            == (
                None
                if other.fixed_joint_positions is None
                else dict(other.fixed_joint_positions)
            )
            and self.state_validator is other.state_validator
        )

    def __deepcopy__(self, memo: dict[int, object]) -> IKRequest:
        return self

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        if self.context_state is not None:
            raise TypeError("cannot pickle IKRequest with context_state")
        if self.state_validator is not None:
            raise TypeError("cannot pickle IKRequest with state_validator")
        return (
            type(self),
            (
                self.seed,
                self.targets,
                self.options,
                None,
                (
                    None
                    if self.fixed_joint_positions is None
                    else dict(self.fixed_joint_positions)
                ),
                None,
            ),
        )
