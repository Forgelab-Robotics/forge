"""Behavioral contract tests for the public Pinocchio kinematics API."""

from __future__ import annotations

from collections.abc import Callable
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


def _rp_jacobian(shoulder: float, extension: float) -> np.ndarray:
    reach = 1.0 + extension
    return np.array(
        [
            [-reach * np.sin(shoulder), np.cos(shoulder)],
            [reach * np.cos(shoulder), np.sin(shoulder)],
            [0.0, 0.0],
            [0.0, 0.0],
            [0.0, 0.0],
            [1.0, 0.0],
        ]
    )


def _solution(result) -> np.ndarray:
    assert result.solution is not None
    q = np.asarray(result.solution, dtype=float)
    assert q.ndim == 1
    return q


def _approximate_solution(result) -> np.ndarray:
    assert result.approximate_solution is not None
    q = np.asarray(result.approximate_solution, dtype=float)
    assert q.ndim == 1
    return q


def _pose_target(pose: np.ndarray) -> PoseTarget:
    return PoseTarget(tip_frame="tool", reference_frame="base", pose=pose)


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


def test_rp_chain_fk_matches_exact_analytic_transform(rp_group) -> None:
    q = np.array([np.pi / 3.0, 0.25])
    expected = _rp_pose(q[0], q[1])

    np.testing.assert_allclose(rp_group.forward(q), expected, atol=1e-12)
    np.testing.assert_allclose(
        rp_group.forward(q, tip_frame="tool"), expected, atol=1e-12
    )


def test_caller_joint_order_controls_inputs_outputs_and_jacobian_columns(
    robot_model,
) -> None:
    group = robot_model.create_group(
        name="rp_reordered",
        joint_names=["extension", "shoulder"],
        base_frame="base",
        tip_frames=("tool",),
    )
    extension = 0.15
    shoulder = -0.4
    q_caller_order = np.array([extension, shoulder])

    np.testing.assert_allclose(
        group.forward(q_caller_order),
        _rp_pose(shoulder, extension),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        group.jacobian(q_caller_order),
        _rp_jacobian(shoulder, extension)[:, [1, 0]],
        atol=1e-11,
    )
    np.testing.assert_allclose(
        group.integrate(q_caller_order, np.array([0.02, -0.03])),
        [extension + 0.02, shoulder - 0.03],
        atol=1e-12,
    )


def test_rp_jacobian_is_exact_linear_angular_geometric_jacobian(rp_group) -> None:
    shoulder = 0.7
    extension = 0.3

    np.testing.assert_allclose(
        rp_group.jacobian([shoulder, extension], tip_frame="tool"),
        _rp_jacobian(shoulder, extension),
        atol=1e-11,
    )


def test_non_root_base_excludes_upstream_pose_from_fk_and_jacobian(rp_group) -> None:
    q = np.array([-0.55, 0.4])

    # The URDF places base under world with a large translation and yaw. Neither
    # may leak into a transform or Jacobian explicitly requested in base.
    np.testing.assert_allclose(rp_group.forward(q), _rp_pose(*q), atol=1e-12)
    np.testing.assert_allclose(rp_group.jacobian(q), _rp_jacobian(*q), atol=1e-11)


def test_continuous_joint_is_one_public_scalar_and_integrates_across_pi(
    robot_model,
) -> None:
    group = robot_model.create_group(
        name="continuous",
        joint_names=["spin"],
        base_frame="base",
        tip_frames=("spin_tip",),
    )
    q_next = group.integrate([np.pi - 0.05], [0.1])
    expected_angle = -np.pi + 0.05
    expected_pose = np.eye(4)
    expected_pose[:3, :3] = _rotation_z(expected_angle)
    expected_pose[:3, 3] = [
        0.4 * np.cos(expected_angle),
        0.4 * np.sin(expected_angle),
        0.2,
    ]

    assert np.asarray(q_next).shape == (1,)
    assert -np.pi <= q_next[0] < np.pi
    assert np.isclose(q_next[0], expected_angle, atol=1e-12)
    np.testing.assert_allclose(group.forward(q_next), expected_pose, atol=1e-12)


def test_create_group_rejects_invalid_joint_selections(robot_model) -> None:
    invalid_selections = [
        (["shoulder", "does_not_exist"], "tool", "does_not_exist"),
        (["shoulder", "shoulder", "extension"], "tool", "shoulder"),
        (["mimic_joint"], "mimic_tip", "mimic_joint"),
        (["side_joint"], "tool", "side_joint"),
    ]

    for joint_names, tip_frame, bad_name in invalid_selections:
        with pytest.raises(ValueError, match=bad_name):
            robot_model.create_group(
                name=f"invalid_{bad_name}",
                joint_names=joint_names,
                base_frame="base",
                tip_frames=(tip_frame,),
            )


def test_single_dof_model_fk_jacobian_and_bounded_neutral(tmp_path: Path) -> None:
    path = tmp_path / "single_dof.urdf"
    path.write_text(
        """<robot name="single_dof">
  <link name="base"/>
  <link name="slider"/>
  <link name="tip"/>
  <joint name="slide" type="prismatic">
    <parent link="base"/>
    <child link="slider"/>
    <axis xyz="1 0 0"/>
    <limit lower="1.0" upper="2.0" effort="1" velocity="1"/>
  </joint>
  <joint name="tool" type="fixed">
    <parent link="slider"/>
    <child link="tip"/>
    <origin xyz="0.2 0 0"/>
  </joint>
</robot>
""",
        encoding="utf-8",
    )
    group = RobotModel.from_urdf(path).create_group(
        name="single_dof",
        joint_names=("slide",),
        base_frame="base",
        tip_frames=("tip",),
    )

    np.testing.assert_allclose(group.neutral_positions, [1.0])
    np.testing.assert_allclose(
        group.forward(group.neutral_positions)[:3, 3], [1.2, 0.0, 0.0]
    )
    np.testing.assert_allclose(
        group.jacobian(group.neutral_positions),
        [[1.0], [0.0], [0.0], [0.0], [0.0], [0.0]],
    )


def test_group_requires_active_joints_and_explicit_tip_for_multi_tip(
    robot_model,
) -> None:
    with pytest.raises(ValueError, match="joint_names"):
        robot_model.create_group(
            name="empty",
            joint_names=[],
            base_frame="base",
            tip_frames=("tool",),
        )

    group = robot_model.create_group(
        name="multi_tip",
        joint_names=["shoulder", "extension", "spin"],
        base_frame="base",
        tip_frames=("tool", "spin_tip"),
    )
    with pytest.raises(ValueError, match="tip_frame"):
        group.forward([0.0, 0.1, 0.0])
    assert group.forward([0.0, 0.1, 0.0], tip_frame="tool").shape == (4, 4)


def test_group_requires_every_path_joint_to_be_active_or_locked(robot_model) -> None:
    with pytest.raises(ValueError, match="shoulder"):
        robot_model.create_group(
            name="implicit_neutral_lock",
            joint_names=("extension",),
            base_frame="base",
            tip_frames=("tool",),
        )
    with pytest.raises(ValueError, match="mimic_joint"):
        robot_model.create_group(
            name="mimic_path",
            joint_names=("shoulder", "extension"),
            base_frame="base",
            tip_frames=("tool", "mimic_tip"),
        )
    with pytest.raises(ValueError, match="side_joint"):
        robot_model.create_group(
            name="unrelated_lock",
            joint_names=("shoulder", "extension"),
            base_frame="base",
            tip_frames=("tool",),
            locked_joint_positions={"side_joint": 0.0},
        )


def test_public_operations_reject_wrong_length_and_nonfinite_vectors(rp_group) -> None:
    invalid_calls: list[Callable[[], object]] = [
        lambda: rp_group.forward([0.0]),
        lambda: rp_group.forward([0.0, np.nan]),
        lambda: rp_group.jacobian([0.0, 0.1, 0.2]),
        lambda: rp_group.jacobian([np.inf, 0.1]),
        lambda: rp_group.integrate([0.0], [0.1, 0.1]),
        lambda: rp_group.integrate([0.0, 0.1], [np.nan, 0.1]),
    ]

    for invalid_call in invalid_calls:
        with pytest.raises(ValueError):
            invalid_call()


def test_locked_joint_position_affects_fk(robot_model) -> None:
    locked_zero = robot_model.create_group(
        name="locked_zero",
        joint_names=["shoulder"],
        base_frame="base",
        tip_frames=("tool",),
        locked_joint_positions={"extension": 0.0},
    )
    locked_offset = robot_model.create_group(
        name="locked_offset",
        joint_names=["shoulder"],
        base_frame="base",
        tip_frames=("tool",),
        locked_joint_positions={"extension": 0.35},
    )
    shoulder = 0.25

    np.testing.assert_allclose(
        locked_zero.forward([shoulder]), _rp_pose(shoulder, 0.0), atol=1e-12
    )
    np.testing.assert_allclose(
        locked_offset.forward([shoulder]), _rp_pose(shoulder, 0.35), atol=1e-12
    )
    assert not np.allclose(
        locked_zero.forward([shoulder]), locked_offset.forward([shoulder])
    )


def test_locked_joint_outside_urdf_limit_is_rejected(robot_model) -> None:
    with pytest.raises(ValueError, match="extension"):
        robot_model.create_group(
            name="invalid_lock",
            joint_names=["shoulder"],
            base_frame="base",
            tip_frames=("tool",),
            locked_joint_positions={"extension": 0.5001},
        )


def test_dls_configuration_is_owned_by_solver_not_request(rp_group) -> None:
    config = DlsConfig(max_iterations=17, damping=0.02)
    solver = PinocchioDlsSolver(rp_group, config=config)

    assert solver.config is config
    assert PinocchioDlsSolver(rp_group).config == DlsConfig()
    assert not hasattr(IKOptions(), "damping")
    assert not hasattr(IKOptions(), "max_iterations")
    with pytest.raises(TypeError, match="DlsConfig"):
        PinocchioDlsSolver(rp_group, config=IKOptions())  # type: ignore[arg-type]


def test_ik_seed_already_satisfying_target_takes_zero_iterations(rp_group) -> None:
    seed = np.array([0.35, 0.2])
    solver = PinocchioDlsSolver(rp_group)

    result = solver.solve(_request(seed, [_pose_target(rp_group.forward(seed))]))

    assert result.status is IKStatus.SUCCESS
    assert result.iterations == 0
    np.testing.assert_allclose(_solution(result), seed, atol=1e-12)


def test_ik_timeout_is_enforced_before_reporting_success(rp_group) -> None:
    seed = np.array([0.35, 0.2])
    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            seed,
            [_pose_target(rp_group.forward(seed))],
            options=IKOptions(timeout_s=1e-12),
        )
    )

    assert result.status is IKStatus.TIMED_OUT
    assert result.solution is None


def test_reachable_ik_solution_reproduces_target_pose(rp_group) -> None:
    seed = np.array([-0.7, 0.05])
    target_pose = rp_group.forward([0.65, 0.32])
    solver = PinocchioDlsSolver(rp_group, config=DlsConfig(max_iterations=200))
    options = IKOptions(
        timeout_s=1.0,
        position_tolerance_m=1e-7,
        orientation_tolerance_rad=1e-7,
    )

    result = solver.solve(_request(seed, [_pose_target(target_pose)], options=options))

    assert result.status is IKStatus.SUCCESS
    np.testing.assert_allclose(
        rp_group.forward(_solution(result)), target_pose, atol=2e-7
    )


def test_position_only_ik_ignores_orientation_error(rp_group) -> None:
    seed = np.array([0.3, 0.2])
    target_pose = rp_group.forward(seed)
    target_pose[:3, :3] = _rotation_z(-1.2)

    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            seed,
            [
                PoseTarget(
                    tip_frame="tool",
                    reference_frame="base",
                    pose=target_pose,
                    position_weight=1.0,
                    orientation_weight=0.0,
                )
            ],
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.iterations == 0
    assert result.raw_position_error_m == pytest.approx(0.0, abs=1e-12)
    assert result.active_position_error_m == pytest.approx(0.0, abs=1e-12)
    assert result.raw_orientation_error_rad > 1.0
    assert result.active_orientation_error_rad == pytest.approx(0.0, abs=1e-12)
    assert result.minimum_singular_value is not None
    assert result.minimum_singular_value > 0.0


def test_ik_is_deterministic_for_identical_inputs(rp_group) -> None:
    seed = np.array([-0.2, 0.1])
    target = _pose_target(rp_group.forward([0.8, 0.4]))
    options = IKOptions(timeout_s=1.0)
    solver = PinocchioDlsSolver(rp_group, config=DlsConfig(max_iterations=150))

    first = solver.solve(_request(seed, [target], options=options))
    second = solver.solve(_request(seed, [target], options=options))

    assert first.status is second.status
    assert first.iterations == second.iterations
    np.testing.assert_allclose(_solution(first), _solution(second), atol=1e-13)


def test_ik_rejects_seed_outside_joint_limits(rp_group) -> None:
    with pytest.raises(ValueError, match="joint limits"):
        PinocchioDlsSolver(rp_group).solve(
            _request(
                [2.1, 0.2],
                [_pose_target(rp_group.forward([0.0, 0.2]))],
            )
        )


def test_unreachable_joint_limit_target_returns_failure_without_raising(
    rp_group,
) -> None:
    solver = PinocchioDlsSolver(rp_group)
    beyond_extension_limit = _rp_pose(0.0, 0.8)

    result = solver.solve(
        _request(
            [0.0, 0.2],
            [_pose_target(beyond_extension_limit)],
            options=IKOptions(timeout_s=1.0),
        )
    )

    assert result.status is not IKStatus.SUCCESS


def test_allow_approximate_solution_controls_best_effort_result(rp_group) -> None:
    solver = PinocchioDlsSolver(rp_group, config=DlsConfig(max_iterations=100))
    seed = np.array([0.0, 0.1])
    target_pose = _rp_pose(0.0, 0.65)
    target = _pose_target(target_pose)

    strict = solver.solve(
        _request(
            seed,
            [target],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=False,
            ),
        )
    )
    approximate = solver.solve(
        _request(
            seed,
            [target],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=True,
            ),
        )
    )

    assert strict.status is not IKStatus.SUCCESS
    assert approximate.status is not IKStatus.SUCCESS
    assert strict.solution is None
    assert strict.approximate_solution is None
    assert approximate.solution is None
    seed_error = np.linalg.norm(rp_group.forward(seed)[:3, 3] - target_pose[:3, 3])
    approximate_error = np.linalg.norm(
        rp_group.forward(_approximate_solution(approximate))[:3, 3] - target_pose[:3, 3]
    )
    assert 0.0 < approximate_error < seed_error


def test_pose_target_rejects_invalid_homogeneous_matrices() -> None:
    bad_poses = [
        np.eye(3),
        np.full((4, 4), np.nan),
        np.diag([1.0, 1.0, 1.0, 2.0]),
        np.array(
            [
                [2.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
    ]

    for bad_pose in bad_poses:
        with pytest.raises(ValueError):
            PoseTarget(tip_frame="tool", reference_frame="base", pose=bad_pose)
    with pytest.raises(ValueError, match="weight"):
        PoseTarget(
            tip_frame="tool",
            reference_frame="base",
            pose=np.eye(4),
            position_weight=0.0,
            orientation_weight=0.0,
        )


def test_ik_options_and_dls_config_reject_invalid_parameters() -> None:
    invalid_options = [
        {"position_tolerance_m": -1e-6},
        {"orientation_tolerance_rad": -1e-6},
        {"allow_approximate_solution": "yes"},
    ]
    invalid_configs = [
        {"max_iterations": -1},
        {"damping": 0.0},
    ]

    for kwargs in invalid_options:
        with pytest.raises((TypeError, ValueError)):
            IKOptions(**kwargs)
    for kwargs in invalid_configs:
        with pytest.raises((TypeError, ValueError)):
            DlsConfig(**kwargs)
