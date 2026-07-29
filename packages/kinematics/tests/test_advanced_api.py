"""Advanced behavioral contracts for the public kinematics API."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from forge_kinematics import (
    DlsConfig,
    IKOptions,
    IKRequest,
    IKStatus,
    PinocchioDlsSolver,
    PoseTarget,
    RobotModel,
)


def _rotation_x(angle: float) -> np.ndarray:
    c = np.cos(angle)
    s = np.sin(angle)
    return np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, c, -s],
            [0.0, s, c],
        ]
    )


def _rotation_z(angle: float) -> np.ndarray:
    c = np.cos(angle)
    s = np.sin(angle)
    return np.array(
        [
            [c, -s, 0.0],
            [s, c, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )


def _rp_pose(shoulder: float, extension: float) -> np.ndarray:
    reach = 1.0 + extension
    pose = np.eye(4)
    pose[:3, :3] = _rotation_z(shoulder)
    pose[:3, 3] = [
        0.5 + reach * np.cos(shoulder),
        -0.2 + reach * np.sin(shoulder),
        0.4,
    ]
    return pose


def _target(pose: np.ndarray, **kwargs: object) -> PoseTarget:
    return PoseTarget(tip_frame="tool", reference_frame="base", pose=pose, **kwargs)


def _request(
    seed: object,
    targets: object,
    *,
    options: object = None,
    context_state: object = None,
    fixed_joint_positions: object = None,
    state_validator: object = None,
) -> IKRequest:
    return IKRequest(
        seed=seed,
        targets=targets,
        options=IKOptions() if options is None else options,
        context_state=context_state,
        fixed_joint_positions=fixed_joint_positions,
        state_validator=state_validator,
    )


def _returned_positions(result) -> np.ndarray:
    positions = result.solution
    if positions is None:
        positions = result.approximate_solution
    assert positions is not None
    return np.asarray(positions, dtype=float)


def test_pose_target_rejects_invalid_or_effectively_empty_task_weights() -> None:
    invalid_kwargs = [
        {"task_weights": (1.0, 1.0, 1.0, 1.0, 1.0)},
        {"task_weights": (1.0, 1.0, 1.0, 1.0, 1.0, -0.1)},
        {"task_weights": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)},
        {
            "task_weights": (1.0, 1.0, 1.0, 0.0, 0.0, 0.0),
            "position_weight": 0.0,
            "orientation_weight": 2.0,
        },
    ]

    for kwargs in invalid_kwargs:
        with pytest.raises(ValueError):
            _target(np.eye(4), **kwargs)

    from_list = _target(np.eye(4), task_weights=[1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
    assert from_list.task_weights == (1.0, 1.0, 1.0, 0.0, 0.0, 0.0)


def test_single_axis_orientation_mask_ignores_only_disabled_rotation_error(
    rp_group,
) -> None:
    seed = np.array([0.25, 0.2])
    seed_pose = rp_group.forward(seed)
    orientation_z_only = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0)

    disabled_axis_pose = seed_pose.copy()
    disabled_axis_pose[:3, :3] = _rotation_x(0.4) @ seed_pose[:3, :3]
    disabled_result = PinocchioDlsSolver(rp_group).solve(
        _request(
            seed,
            [_target(disabled_axis_pose, task_weights=orientation_z_only)],
        )
    )

    assert disabled_result.status is IKStatus.SUCCESS
    assert disabled_result.iterations == 0
    assert disabled_result.raw_orientation_error_rad > 0.3
    assert disabled_result.active_orientation_error_rad == pytest.approx(0.0, abs=1e-12)

    enabled_axis_pose = seed_pose.copy()
    enabled_axis_pose[:3, :3] = _rotation_z(0.4) @ seed_pose[:3, :3]
    enabled_result = PinocchioDlsSolver(
        rp_group, config=DlsConfig(max_iterations=1)
    ).solve(
        _request(
            seed,
            [_target(enabled_axis_pose, task_weights=orientation_z_only)],
            options=IKOptions(
                orientation_tolerance_rad=1e-12,
                timeout_s=1.0,
            ),
        )
    )

    assert enabled_result.status is not IKStatus.SUCCESS
    assert enabled_result.iterations > 0


def test_scalar_pose_weights_multiply_per_axis_task_weights(rp_group) -> None:
    seed = np.array([-0.25, 0.1])
    desired_pose = rp_group.forward([0.6, 0.35])
    options = IKOptions(
        allow_approximate_solution=True,
        timeout_s=1.0,
    )
    scalar_and_axis_weights = _target(
        desired_pose,
        task_weights=(1.0, 4.0, 0.0, 0.0, 0.0, 0.5),
        position_weight=0.25,
        orientation_weight=2.0,
    )
    multiplied_weights = _target(
        desired_pose,
        task_weights=(0.25, 1.0, 0.0, 0.0, 0.0, 1.0),
    )
    solver = PinocchioDlsSolver(
        rp_group,
        config=DlsConfig(max_iterations=1, max_iteration_joint_step=1.0),
    )

    combined_result = solver.solve(
        _request(seed, [scalar_and_axis_weights], options=options)
    )
    explicit_result = solver.solve(
        _request(seed, [multiplied_weights], options=options)
    )

    assert combined_result.status is explicit_result.status
    np.testing.assert_allclose(
        _returned_positions(combined_result),
        _returned_positions(explicit_result),
        atol=1e-12,
    )


def test_dynamic_fixed_joint_overrides_seed_and_preserves_caller_order(
    robot_model,
) -> None:
    group = robot_model.create_group(
        name="reordered_dynamic_fixed",
        joint_names=("extension", "shoulder"),
        base_frame="base",
        tip_frames=("tool",),
    )
    seed = np.array([0.05, -0.4])
    original_seed = seed.copy()
    desired_positions = np.array([0.3, 0.55])

    result = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iterations=200,
            joint_limit_avoidance_weight=0.0,
        ),
    ).solve(
        _request(
            seed,
            [_target(group.forward(desired_positions))],
            options=IKOptions(
                position_tolerance_m=1e-7,
                orientation_tolerance_rad=1e-7,
                timeout_s=1.0,
            ),
            fixed_joint_positions={"extension": desired_positions[0]},
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.joint_names == ("extension", "shoulder")
    solution = _returned_positions(result)
    assert solution.shape == (2,)
    assert solution[0] == pytest.approx(desired_positions[0], abs=1e-12)
    np.testing.assert_allclose(
        group.forward(solution), group.forward(desired_positions), atol=2e-7
    )
    np.testing.assert_array_equal(seed, original_seed)


def test_multi_tip_solve_keeps_shared_torso_dynamically_fixed(tmp_path: Path) -> None:
    path = tmp_path / "bimanual.urdf"
    path.write_text(
        """<robot name="bimanual">
  <link name="base"/><link name="torso"/>
  <joint name="torso_yaw" type="revolute">
    <parent link="base"/><child link="torso"/><axis xyz="0 0 1"/>
    <limit lower="-1" upper="1" effort="1" velocity="1"/>
  </joint>
  <link name="left_tip"/>
  <joint name="left_slide" type="prismatic">
    <parent link="torso"/><child link="left_tip"/>
    <origin xyz="0 0.5 0"/><axis xyz="1 0 0"/>
    <limit lower="0" upper="0.5" effort="1" velocity="1"/>
  </joint>
  <link name="right_tip"/>
  <joint name="right_slide" type="prismatic">
    <parent link="torso"/><child link="right_tip"/>
    <origin xyz="0 -0.5 0"/><axis xyz="1 0 0"/>
    <limit lower="0" upper="0.5" effort="1" velocity="1"/>
  </joint>
</robot>
""",
        encoding="utf-8",
    )
    group = RobotModel.from_urdf(path).create_group(
        name="bimanual",
        joint_names=("right_slide", "torso_yaw", "left_slide"),
        base_frame="base",
        tip_frames=("left_tip", "right_tip"),
    )
    desired = np.array([0.3, 0.4, 0.2])
    desired_poses = group.forward_all(desired)

    result = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iterations=200,
            joint_limit_avoidance_weight=0.0,
        ),
    ).solve(
        _request(
            seed=[0.05, -0.2, 0.05],
            targets=[
                PoseTarget(
                    tip_frame="left_tip",
                    reference_frame="base",
                    pose=desired_poses["left_tip"],
                ),
                PoseTarget(
                    tip_frame="right_tip",
                    reference_frame="base",
                    pose=desired_poses["right_tip"],
                ),
            ],
            options=IKOptions(
                position_tolerance_m=1e-7,
                orientation_tolerance_rad=1e-7,
                timeout_s=1.0,
            ),
            fixed_joint_positions={"torso_yaw": desired[1]},
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.joint_names == ("right_slide", "torso_yaw", "left_slide")
    solution = _returned_positions(result)
    assert solution[1] == pytest.approx(desired[1], abs=1e-12)
    solved_poses = group.forward_all(solution)
    for tip_frame in group.tip_frames:
        np.testing.assert_allclose(
            solved_poses[tip_frame], desired_poses[tip_frame], atol=2e-7
        )


def test_dynamic_fixed_joints_reject_unknown_names_and_limit_violations(
    rp_group,
) -> None:
    solver = PinocchioDlsSolver(rp_group)
    target = _target(rp_group.forward([0.0, 0.2]))
    invalid_fixed_positions = [
        ({"does_not_exist": 0.0}, "does_not_exist"),
        ({"extension": 0.5001}, "extension"),
    ]

    for fixed_positions, bad_name in invalid_fixed_positions:
        with pytest.raises(ValueError, match=bad_name):
            solver.solve(
                _request(
                    [0.0, 0.2],
                    [target],
                    fixed_joint_positions=fixed_positions,
                )
            )


def test_all_joints_fixed_with_unsatisfied_target_returns_no_solution(
    rp_group,
) -> None:
    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            seed=[-0.5, 0.4],
            targets=[_target(rp_group.forward([0.8, 0.4]))],
            fixed_joint_positions={"shoulder": 0.0, "extension": 0.1},
        )
    )

    assert result.status is IKStatus.NO_SOLUTION
    assert result.solution is None
    assert result.joint_names == ("shoulder", "extension")


def test_continuous_group_difference_uses_shortest_angle_across_pi(
    robot_model,
) -> None:
    group = robot_model.create_group(
        name="continuous_difference",
        joint_names=("spin",),
        base_frame="base",
        tip_frames=("spin_tip",),
    )
    start = np.array([np.pi - 0.05])
    end = np.array([-np.pi + 0.05])

    forward_delta = group.difference(start, end)
    reverse_delta = group.difference(end, start)

    np.testing.assert_allclose(forward_delta, [0.1], atol=1e-12)
    np.testing.assert_allclose(reverse_delta, [-0.1], atol=1e-12)
    np.testing.assert_allclose(group.integrate(start, forward_delta), end, atol=1e-12)


def test_adaptive_damping_increases_above_base_below_singularity_threshold(
    rp_group,
) -> None:
    seed = np.array([0.0, 0.1])
    known_minimum_singular_value = float(
        np.min(np.linalg.svd(rp_group.jacobian(seed), compute_uv=False))
    )
    options = IKOptions(
        allow_approximate_solution=True,
        timeout_s=1.0,
    )
    config = DlsConfig(
        damping=0.01,
        max_iterations=1,
        singularity_damping=0.25,
        singularity_threshold=known_minimum_singular_value + 1.0,
    )

    result = PinocchioDlsSolver(rp_group, config=config).solve(
        _request(
            seed,
            [_target(rp_group.forward([0.4, 0.3]))],
            options=options,
        )
    )

    assert result.minimum_singular_value == pytest.approx(
        known_minimum_singular_value, abs=1e-12
    )
    assert result.effective_damping > config.damping


def test_max_solution_joint_displacement_is_applied_per_joint(rp_group) -> None:
    displacement_limit = 0.08
    effective_seed = np.array([0.0, 0.05])
    result = PinocchioDlsSolver(
        rp_group,
        config=DlsConfig(
            max_iterations=100,
            max_iteration_joint_step=0.05,
            joint_limit_avoidance_weight=0.0,
        ),
    ).solve(
        _request(
            seed=effective_seed,
            targets=[_target(rp_group.forward([1.0, 0.4]))],
            options=IKOptions(
                allow_approximate_solution=True,
                max_solution_joint_displacement=displacement_limit,
                timeout_s=1.0,
            ),
        )
    )

    assert result.status is not IKStatus.SUCCESS
    approximate = _returned_positions(result)
    displacement = rp_group.difference(effective_seed, approximate)
    assert np.max(np.abs(displacement)) <= displacement_limit + 1e-12
    assert np.linalg.norm(displacement) > displacement_limit


def test_joint_limit_avoidance_reports_only_real_redundant_activity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "redundant_slides.urdf"
    path.write_text(
        """<robot name="redundant_slides">
  <link name="base"/><link name="middle"/><link name="tip"/>
  <joint name="slide1" type="prismatic">
    <parent link="base"/><child link="middle"/><axis xyz="1 0 0"/>
    <limit lower="0" upper="1" effort="1" velocity="1"/>
  </joint>
  <joint name="slide2" type="prismatic">
    <parent link="middle"/><child link="tip"/><axis xyz="1 0 0"/>
    <limit lower="0" upper="1" effort="1" velocity="1"/>
  </joint>
</robot>
""",
        encoding="utf-8",
    )
    group = RobotModel.from_urdf(path).create_group(
        name="redundant",
        joint_names=("slide1", "slide2"),
        base_frame="base",
        tip_frames=("tip",),
    )
    seed = np.array([0.95, 0.05])
    target = PoseTarget(
        tip_frame="tip",
        reference_frame="base",
        pose=group.forward([0.95, 0.15]),
        task_weights=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    options = IKOptions(
        allow_approximate_solution=True,
        timeout_s=1.0,
    )
    disabled_solver = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iteration_joint_step=1.0,
            max_iterations=1,
            joint_limit_avoidance_weight=0.0,
        ),
    )
    enabled_solver = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iteration_joint_step=1.0,
            max_iterations=1,
            joint_limit_avoidance_weight=0.2,
        ),
    )
    disabled = disabled_solver.solve(_request(seed, [target], options=options))
    enabled = enabled_solver.solve(_request(seed, [target], options=options))

    disabled_q = _returned_positions(disabled)
    enabled_q = _returned_positions(enabled)
    assert disabled.joint_limit_avoidance_activity == 0.0
    assert enabled.joint_limit_avoidance_activity > 0.0
    assert enabled_q[0] < disabled_q[0]
    assert enabled_q[1] > disabled_q[1]
    assert 0.0 <= enabled.minimum_joint_limit_margin <= 1.0

    satisfied = PinocchioDlsSolver(
        group,
        config=DlsConfig(joint_limit_avoidance_weight=0.2),
    ).solve(
        _request(
            seed,
            [
                PoseTarget(
                    tip_frame="tip",
                    reference_frame="base",
                    pose=group.forward(seed),
                )
            ],
        )
    )
    assert satisfied.status is IKStatus.SUCCESS
    assert satisfied.iterations == 0
    assert satisfied.joint_limit_avoidance_activity == 0.0
    np.testing.assert_allclose(_returned_positions(satisfied), seed)


def test_new_ik_options_and_dls_config_reject_invalid_parameters() -> None:
    invalid_options = [
        {"max_solution_joint_displacement": -1.0},
    ]
    invalid_configs = [
        {"max_iteration_joint_step": 0.0},
        {"singularity_threshold": -1.0},
        {"singularity_damping": -1.0},
        {"joint_limit_avoidance_weight": -1.0},
        {"singularity_threshold": np.inf},
    ]

    for kwargs in invalid_options:
        with pytest.raises((TypeError, ValueError)):
            IKOptions(**kwargs)
    for kwargs in invalid_configs:
        with pytest.raises((TypeError, ValueError)):
            DlsConfig(**kwargs)
