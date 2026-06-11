"""High-level teleop action payload and safety filtering."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pyarrow as pa
from forge_msgs.arrow import ensure_record_batch

from .safety_controller import TeleopSafetyContext, TeleopSafetyStatus
from .state import TeleopState, TeleopStateMachine

HighLevelTeleopSide = Literal["left", "right"]


def _float_list(values: list[float]) -> pa.Array:
    return pa.array([values], type=pa.list_(pa.float64()))


def _read_float_list(batch: pa.RecordBatch, field: str) -> list[float]:
    values = batch[field][0].as_py()
    return [float(value) for value in (values or [])]


def _read_float(batch: pa.RecordBatch, field: str, default: float = 0.0) -> float:
    if field not in batch.schema.names:
        return default
    value = batch[field][0].as_py()
    return default if value is None else float(value)


def _read_str(batch: pa.RecordBatch, field: str, default: str = "") -> str:
    if field not in batch.schema.names:
        return default
    value = batch[field][0].as_py()
    return default if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_float_list(value: Any, *, length: int) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"expected float list with length {length}")
    return [float(v) for v in value]


def _normalize_quaternion(quaternion: list[float]) -> tuple[list[float], bool]:
    if len(quaternion) != 4:
        raise ValueError("quaternion must have 4 values")
    norm = float(np.linalg.norm(quaternion))
    if not math.isfinite(norm) or norm < 1e-9:
        raise ValueError("quaternion norm is invalid")
    normalized = [float(v / norm) for v in quaternion]
    return normalized, abs(norm - 1.0) > 1e-4


def _quat_angle_delta(a: list[float], b: list[float]) -> float:
    qa, _ = _normalize_quaternion(a)
    qb, _ = _normalize_quaternion(b)
    dot = abs(float(np.dot(qa, qb)))
    dot = max(-1.0, min(1.0, dot))
    return 2.0 * math.acos(dot)


@dataclass(frozen=True)
class HighLevelArmTarget:
    """End-effector target in robot torso frame."""

    position: list[float]
    quaternion: list[float]

    def __post_init__(self) -> None:
        if len(self.position) != 3:
            raise ValueError("position must have 3 values")
        if len(self.quaternion) != 4:
            raise ValueError("quaternion must have 4 values")
        if not np.all(np.isfinite(self.position)):
            raise ValueError("position must be finite")
        _normalize_quaternion(self.quaternion)

    def normalized(self) -> "HighLevelArmTarget":
        quaternion, _ = _normalize_quaternion(self.quaternion)
        return HighLevelArmTarget(
            position=[float(v) for v in self.position],
            quaternion=quaternion,
        )

    def to_dict(self) -> dict[str, list[float]]:
        return {
            "position": [float(v) for v in self.position],
            "quaternion": [float(v) for v in self.quaternion],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HighLevelArmTarget":
        return cls(
            position=[float(v) for v in raw.get("position", [])],
            quaternion=[float(v) for v in raw.get("quaternion", [])],
        )


@dataclass(frozen=True)
class HighLevelTeleopAction:
    """High-level teleop command for robot drivers with internal IK/trajectory."""

    left_arm: HighLevelArmTarget
    right_arm: HighLevelArmTarget
    waist_pitch: float = 0.0
    waist_yaw: float = 0.0
    left_gripper: float = 0.08
    right_gripper: float = 0.08
    robot_id: str = "robot_0"
    source: str = "teleop"

    action_type: str = "high_level_teleop"
    schema_version: int = 1

    def normalized(self) -> "HighLevelTeleopAction":
        return HighLevelTeleopAction(
            left_arm=self.left_arm.normalized(),
            right_arm=self.right_arm.normalized(),
            waist_pitch=float(self.waist_pitch),
            waist_yaw=float(self.waist_yaw),
            left_gripper=float(self.left_gripper),
            right_gripper=float(self.right_gripper),
            robot_id=self.robot_id,
            source=self.source,
        )

    def to_arrow(self) -> pa.RecordBatch:
        action = self.normalized()
        return pa.RecordBatch.from_pydict(
            {
                "action_type": pa.array([action.action_type], type=pa.string()),
                "schema_version": pa.array([action.schema_version], type=pa.int32()),
                "robot_id": pa.array([action.robot_id], type=pa.string()),
                "source": pa.array([action.source], type=pa.string()),
                "waist_pitch": pa.array([action.waist_pitch], type=pa.float64()),
                "waist_yaw": pa.array([action.waist_yaw], type=pa.float64()),
                "left_position": _float_list(action.left_arm.position),
                "left_quaternion": _float_list(action.left_arm.quaternion),
                "right_position": _float_list(action.right_arm.position),
                "right_quaternion": _float_list(action.right_arm.quaternion),
                "left_gripper": pa.array([action.left_gripper], type=pa.float64()),
                "right_gripper": pa.array([action.right_gripper], type=pa.float64()),
            }
        )

    @classmethod
    def from_arrow(
        cls, data: pa.RecordBatch | pa.Table | pa.StructArray | bytes
    ) -> "HighLevelTeleopAction":
        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("HighLevelTeleopAction RecordBatch must contain one row")
        if _read_str(batch, "action_type") != "high_level_teleop":
            raise ValueError("not a high_level_teleop action")
        return cls(
            robot_id=_read_str(batch, "robot_id", "robot_0"),
            source=_read_str(batch, "source", "teleop"),
            waist_pitch=_read_float(batch, "waist_pitch"),
            waist_yaw=_read_float(batch, "waist_yaw"),
            left_arm=HighLevelArmTarget(
                position=_read_float_list(batch, "left_position"),
                quaternion=_read_float_list(batch, "left_quaternion"),
            ),
            right_arm=HighLevelArmTarget(
                position=_read_float_list(batch, "right_position"),
                quaternion=_read_float_list(batch, "right_quaternion"),
            ),
            left_gripper=_read_float(batch, "left_gripper", 0.08),
            right_gripper=_read_float(batch, "right_gripper", 0.08),
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        action = self.normalized()
        return {
            "action_type": action.action_type,
            "schema_version": action.schema_version,
            "robot_id": action.robot_id,
            "source": action.source,
            "waist_pitch": action.waist_pitch,
            "waist_yaw": action.waist_yaw,
            "left_arm": action.left_arm.to_dict(),
            "right_arm": action.right_arm.to_dict(),
            "left_gripper": action.left_gripper,
            "right_gripper": action.right_gripper,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "HighLevelTeleopAction":
        if raw.get("action_type") != "high_level_teleop":
            raise ValueError("not a high_level_teleop action")
        return cls(
            robot_id=str(raw.get("robot_id", "robot_0")),
            source=str(raw.get("source", "teleop")),
            waist_pitch=float(raw.get("waist_pitch", 0.0)),
            waist_yaw=float(raw.get("waist_yaw", 0.0)),
            left_arm=HighLevelArmTarget.from_dict(raw.get("left_arm", {})),
            right_arm=HighLevelArmTarget.from_dict(raw.get("right_arm", {})),
            left_gripper=float(raw.get("left_gripper", 0.08)),
            right_gripper=float(raw.get("right_gripper", 0.08)),
        ).normalized()


@dataclass(frozen=True)
class HighLevelArmSafetyConfig:
    """Workspace and step limits for one high-level arm target."""

    min_position: list[float] | None = None
    max_position: list[float] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "HighLevelArmSafetyConfig":
        raw = raw or {}
        return cls(
            min_position=_optional_float_list(raw.get("min_position"), length=3),
            max_position=_optional_float_list(raw.get("max_position"), length=3),
        )


@dataclass
class HighLevelTeleopSafetyConfig:
    """Safety config for end-effector high-level teleop actions."""

    enabled: bool = True
    feedback_timeout_seconds: float = 0.2
    teleop_timeout_seconds: float = 0.2
    hold_last_on_failure: bool = True
    fault_after_failures: int = 10
    enable_pose_step_limit: bool = True
    max_eef_position_delta_m: float = 0.08
    max_eef_angular_delta_rad: float = 0.5
    left_arm: HighLevelArmSafetyConfig = field(default_factory=HighLevelArmSafetyConfig)
    right_arm: HighLevelArmSafetyConfig = field(default_factory=HighLevelArmSafetyConfig)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "HighLevelTeleopSafetyConfig":
        if raw is None:
            return cls()
        if isinstance(raw, bool):
            return cls(enabled=raw)
        return cls(
            enabled=bool(raw.get("enabled", True)),
            feedback_timeout_seconds=float(raw.get("feedback_timeout_seconds", 0.2)),
            teleop_timeout_seconds=float(raw.get("teleop_timeout_seconds", 0.2)),
            hold_last_on_failure=bool(raw.get("hold_last_on_failure", True)),
            fault_after_failures=int(raw.get("fault_after_failures", 10)),
            enable_pose_step_limit=bool(raw.get("enable_pose_step_limit", True)),
            max_eef_position_delta_m=float(raw.get("max_eef_position_delta_m", 0.08)),
            max_eef_angular_delta_rad=float(raw.get("max_eef_angular_delta_rad", 0.5)),
            left_arm=HighLevelArmSafetyConfig.from_dict(raw.get("left_arm")),
            right_arm=HighLevelArmSafetyConfig.from_dict(raw.get("right_arm")),
        )


@dataclass(frozen=True)
class HighLevelTeleopSafetyResult:
    action: HighLevelTeleopAction | None
    status: TeleopSafetyStatus
    detail: str = ""


@dataclass
class HighLevelTeleopSafetyController:
    """Safety filter for high-level end-effector teleop actions."""

    config: HighLevelTeleopSafetyConfig
    state_machine: TeleopStateMachine = field(default_factory=TeleopStateMachine)
    _last_safe_action: HighLevelTeleopAction | None = None

    def __post_init__(self) -> None:
        self.state_machine.fault_after_failures = self.config.fault_after_failures

    def reset(self) -> None:
        self._last_safe_action = None
        self.state_machine.deactivate("reset")

    def seed(self, action: HighLevelTeleopAction) -> None:
        self._last_safe_action = action.normalized()
        if self.state_machine.state == TeleopState.INACTIVE:
            self.state_machine.activate()

    def filter_action(
        self,
        action: HighLevelTeleopAction | None,
        *,
        context: TeleopSafetyContext,
    ) -> HighLevelTeleopSafetyResult:
        if not self.config.enabled:
            if action is None:
                return HighLevelTeleopSafetyResult(None, "drop", "disabled_no_action")
            safe = action.normalized()
            self._accept(safe)
            return HighLevelTeleopSafetyResult(safe, "pass")

        if self.state_machine.faulted:
            return self._hold_or_drop("faulted")

        stale_reason = self._check_input_freshness(context)
        if stale_reason:
            self.state_machine.hold(stale_reason)
            return self._hold_or_drop(stale_reason)

        if context.generation_failed or action is None:
            reason = context.failure_reason or "generation_failed"
            self.state_machine.failure(reason)
            status: TeleopSafetyStatus = (
                "fault" if self.state_machine.faulted else "hold"
            )
            return self._hold_or_drop(reason, status=status)

        try:
            safe, limited, detail = self._apply_safety(action.normalized())
        except ValueError as exc:
            self.state_machine.failure(str(exc))
            status = "fault" if self.state_machine.faulted else "hold"
            return self._hold_or_drop(str(exc), status=status)

        self._accept(safe)
        self.state_machine.tracking()
        return HighLevelTeleopSafetyResult(
            safe,
            "limited" if limited else "pass",
            detail,
        )

    def _accept(self, action: HighLevelTeleopAction) -> None:
        self._last_safe_action = action.normalized()

    def _hold_or_drop(
        self,
        detail: str,
        *,
        status: TeleopSafetyStatus = "hold",
    ) -> HighLevelTeleopSafetyResult:
        if self.config.hold_last_on_failure and self._last_safe_action is not None:
            return HighLevelTeleopSafetyResult(self._last_safe_action, status, detail)
        return HighLevelTeleopSafetyResult(None, "drop" if status != "fault" else status, detail)

    def _check_input_freshness(self, context: TeleopSafetyContext) -> str:
        if context.joint_state_time is None:
            return "joint_state_missing"
        joint_age = context.now - context.joint_state_time
        if joint_age > self.config.feedback_timeout_seconds:
            return f"joint_state_timeout age={joint_age:.3f}s"
        if context.teleop_observation_time is None:
            return "teleop_observation_missing"
        teleop_age = context.now - context.teleop_observation_time
        if teleop_age > self.config.teleop_timeout_seconds:
            return f"teleop_timeout age={teleop_age:.3f}s"
        return ""

    def _apply_safety(
        self,
        action: HighLevelTeleopAction,
    ) -> tuple[HighLevelTeleopAction, bool, str]:
        details: list[str] = []
        left, left_limited, left_detail = self._process_arm(
            "left", action.left_arm, self.config.left_arm
        )
        right, right_limited, right_detail = self._process_arm(
            "right", action.right_arm, self.config.right_arm
        )
        if left_limited:
            details.append(left_detail)
        if right_limited:
            details.append(right_detail)
        return (
            HighLevelTeleopAction(
                left_arm=left,
                right_arm=right,
                waist_pitch=action.waist_pitch,
                waist_yaw=action.waist_yaw,
                left_gripper=action.left_gripper,
                right_gripper=action.right_gripper,
                robot_id=action.robot_id,
                source=action.source,
            ),
            left_limited or right_limited,
            ",".join(part for part in details if part),
        )

    def _process_arm(
        self,
        side: HighLevelTeleopSide,
        target: HighLevelArmTarget,
        cfg: HighLevelArmSafetyConfig,
    ) -> tuple[HighLevelArmTarget, bool, str]:
        limited = False
        details: list[str] = []
        position = np.array(target.position, dtype=float)

        if cfg.min_position is not None:
            clipped = np.maximum(position, np.array(cfg.min_position, dtype=float))
            if not np.allclose(clipped, position):
                limited = True
                details.append(f"{side}_workspace_min")
                position = clipped
        if cfg.max_position is not None:
            clipped = np.minimum(position, np.array(cfg.max_position, dtype=float))
            if not np.allclose(clipped, position):
                limited = True
                details.append(f"{side}_workspace_max")
                position = clipped

        previous = getattr(self._last_safe_action, f"{side}_arm", None)
        quaternion = list(target.quaternion)
        if self.config.enable_pose_step_limit and previous is not None:
            prev_pos = np.array(previous.position, dtype=float)
            delta = position - prev_pos
            norm = float(np.linalg.norm(delta))
            if norm > self.config.max_eef_position_delta_m > 0.0:
                position = prev_pos + delta * (self.config.max_eef_position_delta_m / norm)
                limited = True
                details.append(f"{side}_position_step")

            angle_delta = _quat_angle_delta(quaternion, previous.quaternion)
            if angle_delta > self.config.max_eef_angular_delta_rad > 0.0:
                # Keep orientation at last safe target on excessive angular jumps.
                quaternion = list(previous.quaternion)
                limited = True
                details.append(f"{side}_angular_step")

        return (
            HighLevelArmTarget(
                position=[float(v) for v in position.tolist()],
                quaternion=quaternion,
            ).normalized(),
            limited,
            "|".join(details),
        )
