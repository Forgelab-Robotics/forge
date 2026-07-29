"""Solver protocol for backend-independent inverse kinematics."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import KinematicGroup
from .request import IKRequest
from .types import IKResult


@runtime_checkable
class KinematicsSolver(Protocol):
    """Narrow public contract implemented by kinematics solvers."""

    @property
    def group(self) -> KinematicGroup:
        """The kinematic group solved by this instance."""
        ...

    def solve(self, request: IKRequest) -> IKResult:
        """Solve one validated inverse-kinematics request."""
        ...
