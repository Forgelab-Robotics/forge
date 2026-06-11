"""遥操控制器状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TeleopState(StrEnum):
    INACTIVE = "inactive"
    TRACKING = "tracking"
    HOLDING = "holding"
    FAULTED = "faulted"


@dataclass
class TeleopStateMachine:
    state: TeleopState = TeleopState.INACTIVE
    reason: str = "init"
    consecutive_failures: int = 0
    fault_after_failures: int = 10

    @property
    def active(self) -> bool:
        return self.state in {TeleopState.TRACKING, TeleopState.HOLDING}

    @property
    def faulted(self) -> bool:
        return self.state == TeleopState.FAULTED

    def can_activate(self) -> bool:
        return self.state in {TeleopState.INACTIVE, TeleopState.FAULTED}

    def activate(self) -> None:
        self.state = TeleopState.TRACKING
        self.reason = "activated"
        self.consecutive_failures = 0

    def deactivate(self, reason: str = "deactivated") -> None:
        self.state = TeleopState.INACTIVE
        self.reason = reason
        self.consecutive_failures = 0

    def hold(self, reason: str) -> None:
        if self.state != TeleopState.INACTIVE:
            self.state = TeleopState.HOLDING
            self.reason = reason

    def tracking(self) -> None:
        if self.state != TeleopState.INACTIVE:
            self.state = TeleopState.TRACKING
            self.reason = "tracking"
            self.consecutive_failures = 0

    def failure(self, reason: str) -> None:
        if self.state == TeleopState.INACTIVE:
            return
        self.consecutive_failures += 1
        self.reason = reason
        if self.consecutive_failures >= self.fault_after_failures:
            self.state = TeleopState.FAULTED
        else:
            self.state = TeleopState.HOLDING

    def reset_fault(self) -> None:
        if self.state == TeleopState.FAULTED:
            self.state = TeleopState.INACTIVE
            self.reason = "fault_reset"
            self.consecutive_failures = 0
