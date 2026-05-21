from __future__ import annotations

import sys
from pathlib import Path

FORGE_ROBOT_ROOT = Path(__file__).parents[1]
FRAMEWORK_ROOT = FORGE_ROBOT_ROOT.parents[2]
MSGS_SRC = FRAMEWORK_ROOT / "forge" / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_ROBOT_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

import pytest
from forge_msgs import RobotAction
from forge_msgs.value import ActuatorValue
from forge_robot.actuator_spec import (
    ActuatorSpec,
    clip_and_validate_action,
    clip_and_validate_position_action,
)


def test_default_unit_deduction() -> None:
    # 1. revolute 关节默认单位推导
    spec_revolute = ActuatorSpec(name="joint_rev", kind="revolute")
    assert spec_revolute.position_unit == "radians"
    assert spec_revolute.velocity_unit == "radians/s"
    assert spec_revolute.acceleration_unit == "radians/s^2"
    assert spec_revolute.effort_unit == "Nm"

    # 2. continuous 关节默认单位推导
    spec_continuous = ActuatorSpec(name="joint_cont", kind="continuous")
    assert spec_continuous.position_unit == "radians"
    assert spec_continuous.velocity_unit == "radians/s"
    assert spec_continuous.acceleration_unit == "radians/s^2"
    assert spec_continuous.effort_unit == "Nm"

    # 3. prismatic 关节默认单位推导
    spec_prismatic = ActuatorSpec(name="joint_prism", kind="prismatic")
    assert spec_prismatic.position_unit == "meters"
    assert spec_prismatic.velocity_unit == "meters/s"
    assert spec_prismatic.acceleration_unit == "meters/s^2"
    assert spec_prismatic.effort_unit == "unitless"

    # 4. other 默认单位推导
    spec_other = ActuatorSpec(name="joint_other", kind="other")
    assert spec_other.position_unit == "unitless"
    assert spec_other.velocity_unit == "unitless"
    assert spec_other.acceleration_unit == "unitless"
    assert spec_other.effort_unit == "unitless"


def test_explicit_unit_override() -> None:
    # 手动覆盖部分或全部单位
    spec = ActuatorSpec(
        name="joint",
        kind="prismatic",
        position_unit="millimeters",
        velocity_unit="millimeters/s",
        acceleration_unit="millimeters/s^2",
        effort_unit="Nm",
    )
    assert spec.position_unit == "millimeters"
    assert spec.velocity_unit == "millimeters/s"
    assert spec.acceleration_unit == "millimeters/s^2"
    assert spec.effort_unit == "Nm"


def test_clip_and_validate_action_position() -> None:
    specs = {
        "joint_rev": ActuatorSpec(
            name="joint_rev",
            kind="revolute",
            min_position=-1.0,
            max_position=1.0,
        ),
        "joint_cont": ActuatorSpec(
            name="joint_cont",
            kind="continuous",
            min_position=-1.0,
            max_position=1.0,
        ),
    }

    # 1. revolute 正常裁剪
    action_ok = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=1.5, mode="position", unit="radians"),
        }
    )
    result = clip_and_validate_action(action_ok, specs)
    # 应被裁剪到 max_position=1.0
    assert result.actuators["joint_rev"].value == 1.0

    # 2. continuous 自动免除位置裁剪 (哪怕配置了 min/max_position)
    action_cont = RobotAction(
        actuators={
            "joint_cont": ActuatorValue(value=5.0, mode="position", unit="radians"),
        }
    )
    result_cont = clip_and_validate_action(action_cont, specs)
    # 不应被裁剪，保留 5.0
    assert result_cont.actuators["joint_cont"].value == 5.0

    # 3. 错误的位置单位应该抛出异常
    action_err = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=0.5, mode="position", unit="meters"),
        }
    )
    with pytest.raises(ValueError, match="期望单位 radians，收到 meters"):
        clip_and_validate_action(action_err, specs)


def test_clip_and_validate_action_velocity() -> None:
    specs = {
        "joint_rev": ActuatorSpec(
            name="joint_rev",
            kind="revolute",
            max_velocity=2.0,
        ),
    }

    # 1. 速度超出正向限位，裁剪为 max_velocity
    action_pos = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=3.0, mode="velocity", unit="radians/s"),
        }
    )
    result_pos = clip_and_validate_action(action_pos, specs)
    assert result_pos.actuators["joint_rev"].value == 2.0

    # 2. 速度超出负向限位，裁剪为 -max_velocity
    action_neg = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=-3.0, mode="velocity", unit="radians/s"),
        }
    )
    result_neg = clip_and_validate_action(action_neg, specs)
    assert result_neg.actuators["joint_rev"].value == -2.0

    # 3. 速度单位不匹配抛出异常
    action_err = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=1.0, mode="velocity", unit="meters/s"),
        }
    )
    with pytest.raises(ValueError, match="期望单位 radians/s，收到 meters/s"):
        clip_and_validate_action(action_err, specs)


def test_clip_and_validate_action_torque() -> None:
    specs = {
        "joint_rev": ActuatorSpec(
            name="joint_rev",
            kind="revolute",
            max_effort=10.0,
        ),
    }

    # 1. 力矩超出正向限位，裁剪
    action_pos = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=15.0, mode="torque", unit="Nm"),
        }
    )
    result_pos = clip_and_validate_action(action_pos, specs)
    assert result_pos.actuators["joint_rev"].value == 10.0

    # 2. 力矩超出负向限位，裁剪为 -max_effort
    action_neg = RobotAction(
        actuators={
            "joint_rev": ActuatorValue(value=-15.0, mode="torque", unit="Nm"),
        }
    )
    result_neg = clip_and_validate_action(action_neg, specs)
    assert result_neg.actuators["joint_rev"].value == -10.0


def test_backward_compatibility_and_normalization() -> None:
    specs = {
        "joint_prism": ActuatorSpec(
            name="joint_prism",
            kind="prismatic",
            min_position=-0.5,
            max_position=0.5,
        ),
    }

    # 1. 测试旧包装函数 clip_and_validate_position_action 运行正确
    action_pos = RobotAction(
        actuators={
            "joint_prism": ActuatorValue(value=0.8, mode="position", unit="meters"),
        }
    )
    res_compat = clip_and_validate_position_action(action_pos, specs)
    assert res_compat.actuators["joint_prism"].value == 0.5

    # 2. 测试输入模式为 legacy "prismatic" 时，自动归一化为 "position" 进行 meters 单位校验与限位裁剪
    action_legacy = RobotAction(
        actuators={
            "joint_prism": ActuatorValue(value=-0.8, mode="prismatic", unit="meters"),
        }
    )
    res_legacy = clip_and_validate_action(action_legacy, specs)
    # 应被正确归一化校验，并在 -0.5 处裁剪，但其原始 mode 依然保留
    assert res_legacy.actuators["joint_prism"].value == -0.5
    assert res_legacy.actuators["joint_prism"].mode == "prismatic"
