"""Policy adapter protocol used by the generic Dora runner."""

from __future__ import annotations

from typing import Any, Protocol


class PolicyAdapter(Protocol):
    """Minimal interface implemented by algorithm-specific policy classes."""

    def is_observation_needed(self) -> bool:
        """Return True when the next action requires a fresh observation."""

    def generate_action(
        self,
        observation: dict[str, Any],
        alias_for_cameras: list[str] | None = None,
    ) -> Any:
        """Generate one action payload from the current observation."""
