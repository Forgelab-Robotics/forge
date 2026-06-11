"""通用遥操作按键解析与状态机。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from numbers import Real
from typing import Any, Literal

from forge_msgs import TeleopObservation

ControllerSide = Literal["left", "right"]
TeleopButtonEventKind = Literal["activate", "deactivate", "home"]

_HEAD_ALIASES = ("headset", "head", "hmd")
_LEFT_ALIASES = ("left", "left_controller", "left_hand")
_RIGHT_ALIASES = ("right", "right_controller", "right_hand")

_BOOL_BUTTON_ALIASES: dict[str, tuple[str, ...]] = {
    "A": ("A", "a", "button_a", "right_a"),
    "X": ("X", "x", "button_x", "left_x"),
    "B": ("B", "b", "button_b", "right_b"),
    "Y": ("Y", "y", "button_y", "left_y"),
}

_ANALOG_BUTTON_ALIASES: dict[str, tuple[str, ...]] = {
    "left_grip": (
        "left_grip",
        "left_gripper",
        "left_squeeze",
        "grip_left",
        "left_grip_value",
    ),
    "right_grip": (
        "right_grip",
        "right_gripper",
        "right_squeeze",
        "grip_right",
        "right_grip_value",
    ),
}


@dataclass(frozen=True)
class ControllerButtonConfig:
    """左右手柄按键配置，与 vr_device 默认语义保持一致。"""

    left: str = "X"
    right: str = "A"

    @classmethod
    def from_any(
        cls,
        raw: Any,
        *,
        default_left: str,
        default_right: str,
    ) -> "ControllerButtonConfig":
        if raw is None:
            return cls(left=default_left, right=default_right)
        if isinstance(raw, str):
            return cls(left=default_left, right=raw.strip().upper())
        if not isinstance(raw, dict):
            raise ValueError("手柄按键配置必须是对象或字符串")
        return cls(
            left=str(raw.get("left", default_left)).strip().upper(),
            right=str(raw.get("right", default_right)).strip().upper(),
        )

    def button_for(self, side: ControllerSide) -> str:
        return self.left if side == "left" else self.right

    def label(self) -> str:
        return f"left={self.left}, right={self.right}"


@dataclass(frozen=True)
class TeleopHomeConfig:
    """长按激活键触发 home/reset 的通用配置。"""

    enabled: bool = True
    hold_seconds: float = 1.0
    deactivate_teleop: bool = True
    move_seconds: float = 2.0
    targets: dict[str, dict[str, float]] = field(default_factory=dict)

    @classmethod
    def from_any(cls, raw: Any) -> "TeleopHomeConfig":
        if raw is None:
            return cls()
        if raw is False:
            return cls(enabled=False)
        if raw is True:
            return cls()
        if not isinstance(raw, dict):
            raise ValueError("home 必须是对象或布尔值")
        hold_seconds = float(raw.get("hold_seconds", 1.0))
        if hold_seconds <= 0.0:
            raise ValueError("home.hold_seconds 必须大于 0")
        targets_raw = raw.get("targets", {}) or {}
        targets: dict[str, dict[str, float]] = {}
        if isinstance(targets_raw, dict):
            for group, values in targets_raw.items():
                if isinstance(values, dict):
                    targets[str(group)] = {
                        str(name): float(value) for name, value in values.items()
                    }

        move_seconds = float(raw.get("move_seconds", 2.0))
        if move_seconds <= 0.0:
            raise ValueError("home.move_seconds 必须大于 0")

        return cls(
            enabled=bool(raw.get("enabled", True)),
            hold_seconds=hold_seconds,
            deactivate_teleop=bool(raw.get("deactivate_teleop", True)),
            move_seconds=move_seconds,
            targets=targets,
        )


@dataclass(frozen=True)
class TeleopButtonEvent:
    kind: TeleopButtonEventKind
    side: ControllerSide
    button: str
    held_seconds: float = 0.0


@dataclass
class TeleopButtonStateMachine:
    """复用 vr_device 的按键语义：短按激活、长按 home、解除键上升沿解除。"""

    activation_buttons: ControllerButtonConfig = field(
        default_factory=ControllerButtonConfig
    )
    deactivate_buttons: ControllerButtonConfig = field(
        default_factory=lambda: ControllerButtonConfig(left="Y", right="B")
    )
    home: TeleopHomeConfig = field(default_factory=TeleopHomeConfig)
    _activation_pressed_since: dict[ControllerSide, float | None] = field(
        default_factory=lambda: {"left": None, "right": None}
    )
    _activation_home_fired: dict[ControllerSide, bool] = field(
        default_factory=lambda: {"left": False, "right": False}
    )
    _last_deactivate_pressed: dict[ControllerSide, bool] = field(
        default_factory=lambda: {"left": False, "right": False}
    )

    def update(
        self,
        *,
        now: float,
        activation_states: dict[str, bool],
        deactivate_states: dict[str, bool],
    ) -> list[TeleopButtonEvent]:
        events: list[TeleopButtonEvent] = []

        for side in ("left", "right"):
            pressed = bool(deactivate_states.get(side, False))
            if pressed and not self._last_deactivate_pressed.get(side, False):
                events.append(
                    TeleopButtonEvent(
                        kind="deactivate",
                        side=side,
                        button=self.deactivate_buttons.button_for(side),
                    )
                )
            self._last_deactivate_pressed[side] = pressed

        for side in ("left", "right"):
            pressed = bool(activation_states.get(side, False))
            pressed_since = self._activation_pressed_since.get(side)

            if pressed:
                if pressed_since is None:
                    self._activation_pressed_since[side] = now
                    self._activation_home_fired[side] = False
                    continue

                held_seconds = now - pressed_since
                home_fired = self._activation_home_fired.get(side, False)
                if self.home.enabled and not home_fired and held_seconds >= self.home.hold_seconds:
                    self._activation_home_fired[side] = True
                    events.append(
                        TeleopButtonEvent(
                            kind="home",
                            side=side,
                            button=self.activation_buttons.button_for(side),
                            held_seconds=held_seconds,
                        )
                    )
                continue

            if pressed_since is not None:
                if not self._activation_home_fired.get(side, False):
                    events.append(
                        TeleopButtonEvent(
                            kind="activate",
                            side=side,
                            button=self.activation_buttons.button_for(side),
                            held_seconds=now - pressed_since,
                        )
                    )
                self._activation_pressed_since[side] = None
                self._activation_home_fired[side] = False

        return events


def extract_bool_button(observation: TeleopObservation, button_name: str) -> bool:
    """从 TeleopObservation 解析布尔按键。"""
    aliases = _BOOL_BUTTON_ALIASES.get(button_name.upper(), (button_name,))

    for container in _button_containers(observation):
        value = _lookup_named_value(container, aliases)
        if value is not None:
            return _to_bool(value)

    devices = _observation_device_map(observation)
    if devices:
        search_entries: list[Any] = []
        if button_name.upper() == "A":
            search_entries.extend(
                devices.get(key)
                for key in ("right", *_RIGHT_ALIASES)
                if key in devices
            )
        elif button_name.upper() == "X":
            search_entries.extend(
                devices.get(key)
                for key in ("left", *_LEFT_ALIASES)
                if key in devices
            )
        else:
            search_entries.extend(devices.values())

        for entry in search_entries:
            buttons = _device_buttons(entry)
            if buttons is None:
                continue
            value = _lookup_named_value(buttons, aliases)
            if value is not None:
                return _to_bool(value)

    return False


def extract_controller_button_states(
    observation: TeleopObservation,
    buttons: ControllerButtonConfig,
) -> dict[str, bool]:
    """按左右手柄解析按键状态。"""
    return {
        "left": extract_bool_button(observation, buttons.left),
        "right": extract_bool_button(observation, buttons.right),
    }


def extract_grip_value(observation: TeleopObservation, side: ControllerSide) -> float:
    """解析 grip 模拟量，side 为 left 或 right。"""
    key = f"{side}_grip"
    aliases = _ANALOG_BUTTON_ALIASES[key]

    for container in _button_containers(observation):
        value = _lookup_named_value(container, aliases)
        if value is not None:
            return _to_float(value)

    devices = _observation_device_map(observation)
    if devices:
        entry_aliases = _LEFT_ALIASES if side == "left" else _RIGHT_ALIASES
        for device_id in (side, *entry_aliases):
            if device_id not in devices:
                continue
            buttons = _device_buttons(devices[device_id])
            if buttons is None:
                continue
            value = _lookup_named_value(buttons, aliases)
            if value is not None:
                return _to_float(value)

    return 0.0


def _to_bool(value: Any, threshold: float = 0.5) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, Real):
        return float(value) >= threshold
    if hasattr(value, "pressed"):
        return bool(value.pressed)
    if hasattr(value, "value"):
        return _to_bool(value.value, threshold)
    return False


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, Real):
        return float(value)
    if hasattr(value, "value"):
        return _to_float(value.value, default)
    return default


def _lookup_named_value(container: Any, aliases: tuple[str, ...]) -> Any | None:
    if not isinstance(container, dict):
        return None
    for key in aliases:
        if key in container:
            return container[key]
    return None


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _call_json_object_method(
    observation: TeleopObservation,
    method_name: str,
) -> dict[str, Any] | None:
    method = getattr(observation, method_name, None)
    if not callable(method):
        return None
    try:
        value = method()
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _button_containers(observation: TeleopObservation) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = []
    for parsed in (
        _json_object(getattr(observation, "buttons_json", None)),
        _call_json_object_method(observation, "buttons"),
    ):
        if parsed is not None:
            containers.append(parsed)

    for attr in ("buttons", "button", "inputs", "controls"):
        value = getattr(observation, attr, None)
        if isinstance(value, dict):
            containers.append(value)
    return containers


def _device_buttons(entry: Any) -> dict[str, Any] | None:
    if entry is None:
        return None
    if isinstance(entry, dict):
        buttons = entry.get("buttons")
        if not isinstance(buttons, dict):
            buttons = _json_object(entry.get("buttons_json"))
        return buttons if isinstance(buttons, dict) else entry
    buttons = getattr(entry, "buttons", None)
    if isinstance(buttons, dict):
        return buttons
    buttons_json = _json_object(getattr(entry, "buttons_json", None))
    if buttons_json is not None:
        return buttons_json
    return None


def _observation_device_map(observation: TeleopObservation) -> dict[str, Any]:
    devices = getattr(observation, "device", None)
    if isinstance(devices, dict):
        return devices
    if not isinstance(devices, list):
        return {}

    pose_fields = ("x", "y", "z", "qx", "qy", "qz", "qw")
    values_by_field = {
        field: getattr(observation, field, None)
        for field in pose_fields
    }
    if not all(isinstance(values, list) for values in values_by_field.values()):
        return {}

    result: dict[str, list[float]] = {}
    for index, device_id in enumerate(devices):
        try:
            result[str(device_id)] = [
                float(values_by_field[field][index])
                for field in pose_fields
            ]
        except (IndexError, TypeError, ValueError):
            continue
    return result
