"""Driver-facing locomotion command limits."""

from __future__ import annotations

from dataclasses import dataclass
import math

from forge_msgs import LocomotionCommand


@dataclass(frozen=True)
class LocomotionSpec:
    """Safety limits for planar body-frame locomotion commands.

    Limits are symmetric around zero. Direction signs follow LocomotionCommand:
    +vx forward, +vy left, and +wz counter-clockwise around body Z.
    """

    max_vx: float | None = None
    max_vy: float | None = None
    max_wz: float | None = None
    allow_lateral: bool = True

    def __post_init__(self) -> None:
        for field_name in ("max_vx", "max_vy", "max_wz"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{field_name} must be finite and non-negative")


def _clip_symmetric(value: float, limit: float | None) -> float:
    if limit is None:
        return value
    return max(min(value, limit), -limit)


def clip_and_validate_locomotion_command(
    command: LocomotionCommand,
    spec: LocomotionSpec,
) -> LocomotionCommand:
    """Apply driver-level locomotion limits without changing command semantics."""

    vy = command.vy if spec.allow_lateral else 0.0
    return LocomotionCommand(
        vx=_clip_symmetric(command.vx, spec.max_vx),
        vy=_clip_symmetric(vy, spec.max_vy),
        wz=_clip_symmetric(command.wz, spec.max_wz),
    )
