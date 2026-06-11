"""JointCommand 层遥操作安全过滤。"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from forge_msgs import JointCommand, JointState

from .config import JointSafetyConfig, TeleopSafetyConfig
from .state import TeleopState, TeleopStateMachine

TeleopSafetyStatus = Literal["pass", "limited", "hold", "fault", "drop"]


@dataclass(frozen=True)
class TeleopSafetyContext:
    """单次 filter 调用的运行时上下文。"""

    now: float
    joint_state_time: float | None = None
    teleop_observation_time: float | None = None
    generation_failed: bool = False
    failure_reason: str = ""


@dataclass(frozen=True)
class TeleopSafetyResult:
    """安全过滤结果。"""

    command: JointCommand | None
    status: TeleopSafetyStatus
    detail: str = ""


@dataclass
class TeleopSafetyController:
    """对 raw JointCommand 做通用安全过滤。"""

    config: TeleopSafetyConfig
    state_machine: TeleopStateMachine = field(default_factory=TeleopStateMachine)
    _last_safe_command: JointCommand | None = None
    _last_command_time: float | None = None
    _last_vr_poses: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state_machine.fault_after_failures = self.config.fault_after_failures

    def reset(self) -> None:
        self._last_safe_command = None
        self._last_command_time = None
        self._last_vr_poses.clear()
        self.state_machine.deactivate("reset")

    def seed(self, command: JointCommand, *, now: float | None = None) -> None:
        """记录初始安全命令，用于 hold-last 与步长限制基准。"""
        self._last_safe_command = command.model_copy(deep=True)
        self._last_command_time = now if now is not None else time.monotonic()
        if self.state_machine.state == TeleopState.INACTIVE:
            self.state_machine.activate()

    def observe_vr_pose(self, device_id: str, pose7: list[float]) -> tuple[bool, str]:
        """检测 VR 位姿跳变；通过时更新缓存。"""
        if not self.config.enabled:
            self._last_vr_poses[device_id] = list(pose7)
            return True, "ok"

        prev = self._last_vr_poses.get(device_id)
        ok, reason = self._check_pose_jump(prev, pose7)
        if ok:
            self._last_vr_poses[device_id] = list(pose7)
        return ok, reason

    def observe_vr_poses(self, poses: dict[str, list[float]]) -> tuple[bool, str]:
        """批量检测 VR 位姿跳变。"""
        for device_id, pose7 in poses.items():
            ok, reason = self.observe_vr_pose(device_id, pose7)
            if not ok:
                return False, f"{device_id}:{reason}"
        return True, "ok"

    def filter_joint_command(
        self,
        command: JointCommand | None,
        current_state: JointState | None,
        *,
        context: TeleopSafetyContext,
    ) -> TeleopSafetyResult:
        if not self.config.enabled:
            if command is None:
                return TeleopSafetyResult(None, "drop", "disabled_no_command")
            self._accept(command, context.now)
            self.state_machine.tracking()
            return TeleopSafetyResult(command, "pass")

        if self.state_machine.faulted:
            return self._hold_or_drop("faulted", self.state_machine.reason)

        stale_reason = self._check_input_freshness(context)
        if stale_reason:
            self.state_machine.hold(stale_reason)
            return self._hold_or_drop("hold", stale_reason)

        if context.generation_failed or command is None:
            reason = context.failure_reason or "generation_failed"
            self.state_machine.failure(reason)
            status: TeleopSafetyStatus = (
                "fault" if self.state_machine.faulted else "hold"
            )
            return self._hold_or_drop(status, reason)

        if not self._is_finite_command(command):
            self.state_machine.failure("non_finite_command")
            status = "fault" if self.state_machine.faulted else "hold"
            return self._hold_or_drop(status, "non_finite_command")

        safe_command, limited, detail = self._apply_safety(
            command,
            current_state,
            context.now,
        )
        self._accept(safe_command, context.now)
        self.state_machine.tracking()

        if limited:
            return TeleopSafetyResult(safe_command, "limited", detail)
        return TeleopSafetyResult(safe_command, "pass", detail)

    def _check_input_freshness(self, context: TeleopSafetyContext) -> str:
        if context.joint_state_time is None:
            return "joint_state_missing"
        age = context.now - context.joint_state_time
        if age > self.config.feedback_timeout_seconds:
            return f"joint_state_timeout age={age:.3f}s"

        if context.teleop_observation_time is None:
            return "teleop_observation_missing"
        teleop_age = context.now - context.teleop_observation_time
        if teleop_age > self.config.teleop_timeout_seconds:
            return f"teleop_timeout age={teleop_age:.3f}s"
        return ""

    def _hold_or_drop(self, status: TeleopSafetyStatus, detail: str) -> TeleopSafetyResult:
        if self.config.hold_last_on_failure and self._last_safe_command is not None:
            return TeleopSafetyResult(
                self._last_safe_command.model_copy(deep=True),
                status,
                detail,
            )
        return TeleopSafetyResult(None, "drop" if status != "fault" else status, detail)

    def _is_finite_command(self, command: JointCommand) -> bool:
        for values in (command.position, command.velocity, command.effort):
            if values and not np.all(np.isfinite(values)):
                return False
        return True

    def _apply_safety(
        self,
        command: JointCommand,
        current_state: JointState | None,
        now: float,
    ) -> tuple[JointCommand, bool, str]:
        current_by_name = _positions_by_name(current_state)
        last_by_name = _positions_by_name_from_command(self._last_safe_command)

        dt = self.config.tick_seconds
        if self._last_command_time is not None:
            dt = max(self.config.tick_seconds, now - self._last_command_time)

        limited = False
        details: list[str] = []
        names: list[str] = []
        positions: list[float] = []

        raw_by_name = dict(zip(command.name, command.position, strict=False))
        for name in command.name:
            if name not in raw_by_name:
                continue
            target = float(raw_by_name[name])
            joint_cfg = self.config.joint_limits.get(name, JointSafetyConfig())

            value, joint_limited, joint_detail = self._process_joint(
                name=name,
                target=target,
                current=current_by_name.get(name),
                last=last_by_name.get(name),
                joint_cfg=joint_cfg,
                dt=dt,
            )
            if joint_limited:
                limited = True
                if joint_detail:
                    details.append(joint_detail)
            names.append(name)
            positions.append(value)

        safe = JointCommand(
            name=names,
            mode=command.mode,
            position=positions,
            velocity=command.velocity,
            effort=command.effort,
            kp=command.kp,
            kd=command.kd,
        )
        return safe, limited, ",".join(details)

    def _process_joint(
        self,
        *,
        name: str,
        target: float,
        current: float | None,
        last: float | None,
        joint_cfg: JointSafetyConfig,
        dt: float,
    ) -> tuple[float, bool, str]:
        value = target
        limited = False
        details: list[str] = []

        value, hard_limited, hard_detail = self._apply_hard_joint_limits(
            name=name,
            value=value,
            joint_cfg=joint_cfg,
        )
        if hard_limited:
            limited = True
            if hard_detail:
                details.append(hard_detail)

        if not self.config.enable_soft_limits:
            return value, limited, ",".join(details)

        value, soft_limited, soft_detail = self._apply_soft_joint_shaping(
            name=name,
            value=value,
            current=current,
            last=last,
            joint_cfg=joint_cfg,
            dt=dt,
        )
        if soft_limited:
            limited = True
            if soft_detail:
                details.append(soft_detail)

        return value, limited, ",".join(details)

    def _apply_hard_joint_limits(
        self,
        *,
        name: str,
        value: float,
        joint_cfg: JointSafetyConfig,
    ) -> tuple[float, bool, str]:
        limited = False
        details: list[str] = []

        if joint_cfg.min_position is not None and value < joint_cfg.min_position:
            value = joint_cfg.min_position
            limited = True
            details.append(f"{name}=min_clamp")
        if joint_cfg.max_position is not None and value > joint_cfg.max_position:
            value = joint_cfg.max_position
            limited = True
            details.append(f"{name}=max_clamp")

        return value, limited, ",".join(details)

    def _apply_soft_joint_shaping(
        self,
        *,
        name: str,
        value: float,
        current: float | None,
        last: float | None,
        joint_cfg: JointSafetyConfig,
        dt: float,
    ) -> tuple[float, bool, str]:
        limited = False
        details: list[str] = []
        reference = last if last is not None else current

        if reference is not None and (
            self.config.enable_step_limit or self.config.enable_velocity_limit
        ):
            max_delta_candidates: list[float] = []

            if self.config.enable_step_limit:
                step_limit = self.config.max_joint_delta_per_tick
                if joint_cfg.max_delta_per_tick is not None:
                    step_limit = min(step_limit, joint_cfg.max_delta_per_tick)
                max_delta_candidates.append(step_limit)

            if self.config.enable_velocity_limit:
                velocity_limit = self.config.max_joint_velocity_rad_s * dt
                if joint_cfg.max_velocity_rad_s is not None:
                    velocity_limit = min(velocity_limit, joint_cfg.max_velocity_rad_s * dt)
                max_delta_candidates.append(velocity_limit)

            if max_delta_candidates:
                max_delta = min(max_delta_candidates)
                delta = value - reference
                clipped = max(-max_delta, min(max_delta, delta))
                if abs(clipped - delta) > 1e-9:
                    limited = True
                    details.append(f"{name}=soft_limited")
                value = reference + clipped

        if self.config.enable_low_pass and last is not None:
            alpha = float(max(0.0, min(1.0, self.config.low_pass_alpha)))
            if alpha < 1.0:
                blended = last + alpha * (value - last)
                if abs(blended - value) > 1e-9:
                    limited = True
                    details.append(f"{name}=low_pass")
                value = blended

        return value, limited, ",".join(details)

    def _accept(self, command: JointCommand, now: float) -> None:
        self._last_safe_command = command.model_copy(deep=True)
        self._last_command_time = now

    def _check_pose_jump(
        self,
        prev: list[float] | None,
        current: list[float],
    ) -> tuple[bool, str]:
        if prev is None or len(prev) != 7 or len(current) != 7:
            return True, "ok"

        pos_delta = math.dist(prev[:3], current[:3])
        if pos_delta > self.config.max_vr_position_jump_m:
            return False, f"position_jump={pos_delta:.4f}m"

        dot = abs(
            prev[3] * current[3]
            + prev[4] * current[4]
            + prev[5] * current[5]
            + prev[6] * current[6]
        )
        dot = min(1.0, max(-1.0, dot))
        angle = 2.0 * math.acos(dot)
        if angle > self.config.max_vr_angular_jump_rad:
            return False, f"angular_jump={angle:.4f}rad"
        return True, "ok"


def _positions_by_name(state: JointState | None) -> dict[str, float]:
    if state is None:
        return {}
    return {
        name: float(pos)
        for name, pos in zip(state.name, state.position, strict=False)
    }


def _positions_by_name_from_command(command: JointCommand | None) -> dict[str, float]:
    if command is None:
        return {}
    return {
        name: float(pos)
        for name, pos in zip(command.name, command.position, strict=False)
    }
