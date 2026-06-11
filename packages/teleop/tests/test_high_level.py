from forge_teleop import (
    HighLevelArmTarget,
    HighLevelTeleopAction,
    HighLevelTeleopSafetyConfig,
    HighLevelTeleopSafetyController,
    TeleopSafetyContext,
)


def _action(left_x: float = 0.2) -> HighLevelTeleopAction:
    return HighLevelTeleopAction(
        left_arm=HighLevelArmTarget(
            position=[left_x, 0.1, 0.3],
            quaternion=[0.0, 0.0, 0.0, 1.0],
        ),
        right_arm=HighLevelArmTarget(
            position=[0.2, -0.1, 0.3],
            quaternion=[0.0, 0.0, 0.0, 2.0],
        ),
    )


def test_high_level_action_arrow_roundtrip_normalizes_quaternion() -> None:
    back = HighLevelTeleopAction.from_arrow(_action().to_arrow())

    assert back.right_arm.quaternion == [0.0, 0.0, 0.0, 1.0]
    assert back.left_arm.position == [0.2, 0.1, 0.3]


def test_high_level_safety_limits_position_step() -> None:
    controller = HighLevelTeleopSafetyController(
        HighLevelTeleopSafetyConfig(max_eef_position_delta_m=0.01)
    )
    controller.seed(_action(left_x=0.2))

    result = controller.filter_action(
        _action(left_x=0.4),
        context=TeleopSafetyContext(
            now=1.0,
            joint_state_time=1.0,
            teleop_observation_time=1.0,
        ),
    )

    assert result.status == "limited"
    assert result.action is not None
    assert result.action.left_arm.position[0] == 0.21000000000000002
