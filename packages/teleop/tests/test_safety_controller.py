from __future__ import annotations

import sys
from pathlib import Path

import pytest

FORGE_TELEOP_ROOT = Path(__file__).parents[1]
FORGE_ROOT = FORGE_TELEOP_ROOT.parents[1]
MSGS_SRC = FORGE_ROOT / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_TELEOP_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

from forge_msgs import JointCommand, JointState
from forge_teleop import (
    TeleopSafetyConfig,
    TeleopSafetyContext,
    TeleopSafetyController,
    TeleopState,
)
from forge_teleop.config import JointSafetyConfig


def _command(positions: list[float], names: list[str] | None = None) -> JointCommand:
    joint_names = names or [f"joint_{i}" for i in range(len(positions))]
    return JointCommand(name=joint_names, mode="position", position=positions)


def _state(positions: list[float], names: list[str] | None = None) -> JointState:
    joint_names = names or [f"joint_{i}" for i in range(len(positions))]
    return JointState(name=joint_names, position=positions)


def _ctx(now: float = 0.02) -> TeleopSafetyContext:
    return TeleopSafetyContext(
        now=now,
        joint_state_time=0.0,
        teleop_observation_time=0.0,
    )


def test_pass_through_when_disabled() -> None:
    controller = TeleopSafetyController(TeleopSafetyConfig(enabled=False))
    cmd = _command([0.1, 0.2])
    result = controller.filter_joint_command(cmd, None, context=TeleopSafetyContext(now=0.0))
    assert result.status == "pass"
    assert result.command is not None
    assert result.command.position == pytest.approx([0.1, 0.2])


def test_joint_limit_clamp() -> None:
    config = TeleopSafetyConfig(
        enabled=True,
        enable_soft_limits=False,
        joint_limits={
            "joint_0": JointSafetyConfig(min_position=-0.5, max_position=0.5),
        },
    )
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)

    result = controller.filter_joint_command(_command([1.5]), _state([0.0]), context=_ctx())
    assert result.status == "limited"
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.5)


def test_step_limit() -> None:
    config = TeleopSafetyConfig(
        enabled=True,
        enable_soft_limits=True,
        enable_step_limit=True,
        enable_velocity_limit=False,
        enable_low_pass=False,
        low_pass_alpha=1.0,
        max_joint_delta_per_tick=0.05,
    )
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)

    result = controller.filter_joint_command(_command([1.0]), _state([0.0]), context=_ctx())
    assert result.status == "limited"
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.05)


def test_non_finite_rejected_and_hold() -> None:
    config = TeleopSafetyConfig(enabled=True, hold_last_on_failure=True, fault_after_failures=100)
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.2]), now=0.0)

    bad = _command([float("nan")])
    result = controller.filter_joint_command(bad, _state([0.0]), context=_ctx())
    assert result.status == "hold"
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.2)


def test_input_timeout_holds_last() -> None:
    config = TeleopSafetyConfig(
        enabled=True,
        teleop_timeout_seconds=0.1,
        feedback_timeout_seconds=0.1,
        hold_last_on_failure=True,
    )
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.3]), now=0.0)

    result = controller.filter_joint_command(
        _command([0.4]),
        _state([0.3]),
        context=TeleopSafetyContext(now=0.5, joint_state_time=0.0, teleop_observation_time=0.0),
    )
    assert result.status == "hold"
    assert "timeout" in result.detail
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.3)


def test_vr_pose_jump_detection() -> None:
    config = TeleopSafetyConfig(max_vr_position_jump_m=0.05, max_vr_angular_jump_rad=0.5)
    controller = TeleopSafetyController(config)

    ok, _ = controller.observe_vr_pose("head", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    assert ok

    ok, reason = controller.observe_vr_pose("head", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    assert not ok
    assert "position_jump" in reason


def test_fault_after_repeated_failures() -> None:
    config = TeleopSafetyConfig(
        enabled=True,
        hold_last_on_failure=True,
        fault_after_failures=2,
    )
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)
    controller.state_machine.activate()

    ctx = TeleopSafetyContext(
        now=0.02,
        joint_state_time=0.0,
        teleop_observation_time=0.0,
        generation_failed=True,
        failure_reason="ik_failed",
    )
    controller.filter_joint_command(None, _state([0.0]), context=ctx)
    assert controller.state_machine.state == TeleopState.HOLDING

    result = controller.filter_joint_command(None, _state([0.0]), context=ctx)
    assert controller.state_machine.state == TeleopState.FAULTED
    assert result.status == "fault"


def test_low_pass_smooths_target() -> None:
    config = TeleopSafetyConfig(
        enabled=True,
        enable_soft_limits=True,
        enable_low_pass=True,
        enable_step_limit=False,
        enable_velocity_limit=False,
        low_pass_alpha=0.2,
    )
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)

    result = controller.filter_joint_command(_command([1.0]), _state([0.0]), context=_ctx())
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.2)


def test_balanced_mode_uses_velocity_not_step() -> None:
    config = TeleopSafetyConfig.from_dict({"safety_mode": "balanced"})
    assert config.enable_velocity_limit is True
    assert config.enable_step_limit is False
    assert config.enable_low_pass is False

    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)
    result = controller.filter_joint_command(_command([1.0]), _state([0.0]), context=_ctx())
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.05)


def test_strict_mode_is_more_conservative() -> None:
    config = TeleopSafetyConfig.from_dict({"safety_mode": "strict"})
    assert config.enable_step_limit is True
    assert config.enable_low_pass is True
    assert config.max_joint_velocity_rad_s == pytest.approx(0.8)

    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)
    result = controller.filter_joint_command(_command([1.0]), _state([0.0]), context=_ctx())
    assert result.command is not None
    assert result.command.position[0] < 0.02


def test_responsive_mode_passes_small_motion() -> None:
    config = TeleopSafetyConfig.from_dict({"safety_mode": "responsive"})
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)

    result = controller.filter_joint_command(_command([0.05]), _state([0.0]), context=_ctx())
    assert result.status == "pass"
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.05)


def test_disable_soft_limits_keeps_hard_limits() -> None:
    config = TeleopSafetyConfig(
        enabled=True,
        enable_soft_limits=False,
        joint_limits={"joint_0": JointSafetyConfig(max_position=0.4)},
    )
    controller = TeleopSafetyController(config)
    controller.seed(_command([0.0]), now=0.0)

    result = controller.filter_joint_command(_command([1.0]), _state([0.0]), context=_ctx())
    assert result.command is not None
    assert result.command.position[0] == pytest.approx(0.4)
