from __future__ import annotations

import sys
from pathlib import Path

FORGE_TELEOP_ROOT = Path(__file__).parents[1]
FORGE_ROOT = FORGE_TELEOP_ROOT.parents[1]
MSGS_SRC = FORGE_ROOT / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_TELEOP_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

from forge_msgs import TeleopObservation
from forge_teleop import (
    ControllerButtonConfig,
    TeleopButtonStateMachine,
    TeleopHomeConfig,
    extract_bool_button,
    extract_controller_button_states,
)


def _observation(buttons: dict[str, bool | float]) -> TeleopObservation:
    poses = {
        "headset": (0.0, 0.0, 1.6, 0.0, 0.0, 0.0, 1.0),
        "left": (-0.2, 0.0, 1.2, 0.0, 0.0, 0.0, 1.0),
        "right": (0.2, 0.0, 1.2, 0.0, 0.0, 0.0, 1.0),
    }
    return TeleopObservation.from_device_poses(poses, buttons=buttons)


def test_extract_controller_buttons() -> None:
    obs = _observation({"X": True, "A": False})
    states = extract_controller_button_states(obs, ControllerButtonConfig())

    assert states == {"left": True, "right": False}
    assert extract_bool_button(obs, "X")


def test_short_press_activation_fires_on_release() -> None:
    state = TeleopButtonStateMachine()

    assert state.update(
        now=0.0,
        activation_states={"left": True, "right": False},
        deactivate_states={"left": False, "right": False},
    ) == []
    events = state.update(
        now=0.2,
        activation_states={"left": False, "right": False},
        deactivate_states={"left": False, "right": False},
    )

    assert len(events) == 1
    assert events[0].kind == "activate"
    assert events[0].side == "left"
    assert events[0].button == "X"


def test_long_press_home_suppresses_short_activation() -> None:
    state = TeleopButtonStateMachine(home=TeleopHomeConfig(hold_seconds=1.0))

    state.update(
        now=0.0,
        activation_states={"left": False, "right": True},
        deactivate_states={"left": False, "right": False},
    )
    events = state.update(
        now=1.1,
        activation_states={"left": False, "right": True},
        deactivate_states={"left": False, "right": False},
    )
    release_events = state.update(
        now=1.2,
        activation_states={"left": False, "right": False},
        deactivate_states={"left": False, "right": False},
    )

    assert len(events) == 1
    assert events[0].kind == "home"
    assert events[0].side == "right"
    assert release_events == []


def test_deactivate_fires_on_rising_edge() -> None:
    state = TeleopButtonStateMachine()

    events = state.update(
        now=0.0,
        activation_states={"left": False, "right": False},
        deactivate_states={"left": False, "right": True},
    )
    repeated = state.update(
        now=0.1,
        activation_states={"left": False, "right": False},
        deactivate_states={"left": False, "right": True},
    )

    assert len(events) == 1
    assert events[0].kind == "deactivate"
    assert events[0].side == "right"
    assert events[0].button == "B"
    assert repeated == []


def test_home_config_parses_move_seconds_and_targets() -> None:
    config = TeleopHomeConfig.from_any(
        {
            "move_seconds": 2.5,
            "targets": {
                "robot_0": {
                    "left_arm_4": -0.5,
                    "right_arm_4": -0.5,
                }
            },
        }
    )

    assert config.move_seconds == 2.5
    assert config.targets["robot_0"]["left_arm_4"] == -0.5
