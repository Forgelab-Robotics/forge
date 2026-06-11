"""遥操作安全配置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SafetyMode = Literal["strict", "balanced", "responsive"]

_MODE_PRESETS: dict[SafetyMode, dict[str, Any]] = {
    "strict": {
        "enable_soft_limits": True,
        "enable_low_pass": True,
        "enable_step_limit": True,
        "enable_velocity_limit": True,
        "low_pass_alpha": 0.2,
        "max_joint_delta_per_tick": 0.03,
        "max_joint_velocity_rad_s": 0.8,
        "max_vr_position_jump_m": 0.08,
        "max_vr_angular_jump_rad": 0.5,
    },
    "balanced": {
        "enable_soft_limits": True,
        "enable_low_pass": False,
        "enable_step_limit": False,
        "enable_velocity_limit": True,
        "low_pass_alpha": 0.8,
        "max_joint_delta_per_tick": 0.08,
        "max_joint_velocity_rad_s": 2.5,
        "max_vr_position_jump_m": 0.12,
        "max_vr_angular_jump_rad": 0.8,
    },
    "responsive": {
        "enable_soft_limits": True,
        "enable_low_pass": False,
        "enable_step_limit": True,
        "enable_velocity_limit": False,
        "low_pass_alpha": 1.0,
        "max_joint_delta_per_tick": 0.2,
        "max_joint_velocity_rad_s": 10.0,
        "max_vr_position_jump_m": 0.2,
        "max_vr_angular_jump_rad": 1.2,
    },
}


@dataclass
class JointSafetyConfig:
    """单关节安全限制。"""

    min_position: float | None = None
    max_position: float | None = None
    max_velocity_rad_s: float | None = None
    max_delta_per_tick: float | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> JointSafetyConfig:
        return cls(
            min_position=_optional_float(raw.get("min_position")),
            max_position=_optional_float(raw.get("max_position")),
            max_velocity_rad_s=_optional_float(raw.get("max_velocity_rad_s")),
            max_delta_per_tick=_optional_float(raw.get("max_delta_per_tick")),
        )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _resolve_mode_value(
    raw: dict[str, Any],
    key: str,
    mode: SafetyMode,
    fallback: Any,
) -> Any:
    if key in raw:
        return raw[key]
    return _MODE_PRESETS[mode].get(key, fallback)


@dataclass
class TeleopSafetyConfig:
    """遥操作输出安全全局配置。"""

    enabled: bool = True
    safety_mode: SafetyMode = "balanced"
    enable_soft_limits: bool = True
    enable_low_pass: bool = False
    enable_step_limit: bool = False
    enable_velocity_limit: bool = True
    tick_seconds: float = 0.02
    low_pass_alpha: float = 0.8
    max_joint_delta_per_tick: float = 0.08
    max_joint_velocity_rad_s: float = 2.5
    feedback_timeout_seconds: float = 0.2
    teleop_timeout_seconds: float = 0.2
    max_vr_position_jump_m: float = 0.12
    max_vr_angular_jump_rad: float = 0.8
    hold_last_on_failure: bool = True
    fault_after_failures: int = 10
    joint_limits: dict[str, JointSafetyConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> TeleopSafetyConfig:
        if raw is None:
            return cls()
        if isinstance(raw, bool):
            return cls(enabled=raw)

        mode_raw = str(raw.get("safety_mode", "balanced")).strip().lower()
        if mode_raw not in _MODE_PRESETS:
            raise ValueError("safety_mode 仅支持 strict / balanced / responsive")
        mode: SafetyMode = mode_raw  # type: ignore[assignment]

        joint_limits_raw = raw.get("joint_limits", {}) or {}
        joint_limits: dict[str, JointSafetyConfig] = {}
        if isinstance(joint_limits_raw, dict):
            for name, limit_raw in joint_limits_raw.items():
                if isinstance(limit_raw, dict):
                    joint_limits[str(name)] = JointSafetyConfig.from_dict(limit_raw)

        return cls(
            enabled=bool(raw.get("enabled", True)),
            safety_mode=mode,
            enable_soft_limits=bool(
                _resolve_mode_value(raw, "enable_soft_limits", mode, True)
            ),
            enable_low_pass=bool(
                _resolve_mode_value(raw, "enable_low_pass", mode, False)
            ),
            enable_step_limit=bool(
                _resolve_mode_value(raw, "enable_step_limit", mode, False)
            ),
            enable_velocity_limit=bool(
                _resolve_mode_value(raw, "enable_velocity_limit", mode, True)
            ),
            tick_seconds=float(raw.get("tick_seconds", 0.02)),
            low_pass_alpha=float(
                _resolve_mode_value(raw, "low_pass_alpha", mode, 0.8)
            ),
            max_joint_delta_per_tick=float(
                _resolve_mode_value(raw, "max_joint_delta_per_tick", mode, 0.08)
            ),
            max_joint_velocity_rad_s=float(
                _resolve_mode_value(raw, "max_joint_velocity_rad_s", mode, 2.5)
            ),
            feedback_timeout_seconds=float(raw.get("feedback_timeout_seconds", 0.2)),
            teleop_timeout_seconds=float(raw.get("teleop_timeout_seconds", 0.2)),
            max_vr_position_jump_m=float(
                _resolve_mode_value(raw, "max_vr_position_jump_m", mode, 0.12)
            ),
            max_vr_angular_jump_rad=float(
                _resolve_mode_value(raw, "max_vr_angular_jump_rad", mode, 0.8)
            ),
            hold_last_on_failure=bool(raw.get("hold_last_on_failure", True)),
            fault_after_failures=int(raw.get("fault_after_failures", 10)),
            joint_limits=joint_limits,
        )
