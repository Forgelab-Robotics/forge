"""Behavioral contracts for bounded nonlinear least-squares IK."""

from __future__ import annotations

import copy
import pickle
import time
from pathlib import Path

import numpy as np
import pytest

from forge_kinematics import (
    BoundedLeastSquaresConfig,
    IKOptions,
    IKRequest,
    IKStatus,
    KinematicsSolver,
    PinocchioBoundedLeastSquaresSolver,
    PoseTarget,
    RobotModel,
    RobotState,
)


def _rotation_z(angle: float) -> np.ndarray:
    cosine = np.cos(angle)
    sine = np.sin(angle)
    return np.array(
        [
            [cosine, -sine, 0.0],
            [sine, cosine, 0.0],
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


def _target(group, positions: object, *, tip_frame: str = "tool") -> PoseTarget:
    return PoseTarget(
        tip_frame=tip_frame,
        reference_frame=group.base_frame,
        pose=group.forward(positions, tip_frame=tip_frame),
    )


def _request(
    seed: object,
    targets: object,
    *,
    options: IKOptions | None = None,
    context_state: RobotState | None = None,
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
    return np.asarray(positions, dtype=np.float64)


def _redundant_slides(tmp_path: Path):
    path = tmp_path / "bounded_redundant_slides.urdf"
    path.write_text(
        """<robot name="bounded_redundant_slides">
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
    return RobotModel.from_urdf(path).create_group(
        name="bounded_redundant_slides",
        joint_names=("slide1", "slide2"),
        base_frame="base",
        tip_frames=("tip",),
    )


def test_missing_scipy_extra_fails_only_when_constructing_bounded_solver(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_kinematics.bounded_least_squares as bounded_module

    monkeypatch.setattr(bounded_module, "_scipy_least_squares", None)
    with pytest.raises(ImportError, match="least-squares"):
        PinocchioBoundedLeastSquaresSolver(rp_group)


def test_bounded_solver_implements_protocol_and_solves_reachable_pose(rp_group) -> None:
    desired = np.array([0.65, 0.32])
    solver = PinocchioBoundedLeastSquaresSolver(
        rp_group,
        BoundedLeastSquaresConfig(max_nfev=100),
    )
    request = _request(
        seed=[-0.7, 0.05],
        targets=[_target(rp_group, desired)],
        options=IKOptions(
            timeout_s=1.0,
            position_tolerance_m=1e-7,
            orientation_tolerance_rad=1e-7,
        ),
    )

    result = solver.solve(request)

    assert isinstance(solver, KinematicsSolver)
    assert result.status is IKStatus.SUCCESS
    assert result.solution is not None
    assert result.seed_was_projected is False
    np.testing.assert_allclose(
        rp_group.forward(result.solution), rp_group.forward(desired), atol=2e-7
    )


def test_bounded_solver_returns_stable_constrained_optimum_for_unreachable_target(
    rp_group,
) -> None:
    solver = PinocchioBoundedLeastSquaresSolver(
        rp_group,
        BoundedLeastSquaresConfig(
            max_nfev=100,
            joint_limit_margins={"extension": 0.05},
        ),
    )
    target = PoseTarget(
        tip_frame="tool",
        reference_frame="base",
        pose=_rp_pose(0.0, 0.8),
    )

    result = solver.solve(
        _request(
            seed=[0.0, 0.2],
            targets=[target],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=True,
            ),
        )
    )

    assert result.status is IKStatus.NO_SOLUTION
    approximate = _returned_positions(result)
    assert approximate[0] == pytest.approx(0.0, abs=1e-8)
    assert approximate[1] == pytest.approx(0.45, abs=1e-8)
    assert result.active_position_error_m == pytest.approx(0.35, abs=1e-8)
    assert result.minimum_joint_limit_margin == pytest.approx(0.2, abs=1e-8)


def test_seed_is_projected_to_configured_box_before_zero_iteration_success(
    rp_group,
) -> None:
    mutable_bounds = {"shoulder": [-1.0, 1.0], "extension": [0.1, 0.4]}
    config = BoundedLeastSquaresConfig(joint_position_bounds=mutable_bounds)
    mutable_bounds["shoulder"][0] = -2.0
    solver = PinocchioBoundedLeastSquaresSolver(rp_group, config)
    projected = np.array([1.0, 0.1])
    request = _request(
        seed=[1.5, -0.2],
        targets=[_target(rp_group, projected)],
    )

    result = solver.solve(request)

    assert config.joint_position_bounds["shoulder"] == (-1.0, 1.0)
    assert result.status is IKStatus.SUCCESS
    assert result.iterations == 0
    assert result.seed_was_projected is True
    np.testing.assert_allclose(result.solution, projected, atol=1e-12)
    np.testing.assert_array_equal(request.seed, [1.5, -0.2])


def test_displacement_box_is_measured_from_projected_effective_seed(rp_group) -> None:
    solver = PinocchioBoundedLeastSquaresSolver(
        rp_group,
        BoundedLeastSquaresConfig(
            max_nfev=100,
            joint_position_bounds={"shoulder": (-1.5, 1.5)},
        ),
    )
    effective_seed = np.array([1.5, 0.2])
    displacement_limit = 0.1

    result = solver.solve(
        _request(
            seed=[2.2, 0.2],
            targets=[_target(rp_group, [0.0, 0.4])],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=True,
                max_solution_joint_displacement=displacement_limit,
            ),
        )
    )

    assert result.status is not IKStatus.SUCCESS
    assert result.seed_was_projected is True
    displacement = rp_group.difference(effective_seed, _returned_positions(result))
    assert np.max(np.abs(displacement)) <= displacement_limit + 1e-12


def test_dynamic_fixed_joint_uses_hard_limit_even_outside_interior_solve_box(
    rp_group,
) -> None:
    desired = np.array([0.4, 0.5])
    solver = PinocchioBoundedLeastSquaresSolver(
        rp_group,
        BoundedLeastSquaresConfig(
            max_nfev=100,
            joint_position_bounds={"extension": (0.1, 0.4)},
        ),
    )

    result = solver.solve(
        _request(
            seed=[-0.5, 0.1],
            targets=[_target(rp_group, desired)],
            options=IKOptions(
                timeout_s=1.0,
                position_tolerance_m=1e-7,
                orientation_tolerance_rad=1e-7,
            ),
            fixed_joint_positions={"extension": 0.5},
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.solution is not None
    assert result.solution[1] == pytest.approx(0.5, abs=1e-12)
    np.testing.assert_allclose(
        rp_group.forward(result.solution), rp_group.forward(desired), atol=2e-7
    )


def test_multi_tip_solver_preserves_order_and_shared_fixed_joint(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bounded_bimanual.urdf"
    path.write_text(
        """<robot name="bounded_bimanual">
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
        name="bounded_bimanual",
        joint_names=("right_slide", "torso_yaw", "left_slide"),
        base_frame="base",
        tip_frames=("left_tip", "right_tip"),
    )
    desired = np.array([0.3, 0.4, 0.2])
    desired_poses = group.forward_all(desired)
    targets = tuple(
        PoseTarget(
            tip_frame=tip,
            reference_frame="base",
            pose=desired_poses[tip],
        )
        for tip in group.tip_frames
    )

    result = PinocchioBoundedLeastSquaresSolver(
        group,
        BoundedLeastSquaresConfig(max_nfev=100),
    ).solve(
        _request(
            seed=[0.05, -0.2, 0.05],
            targets=targets,
            options=IKOptions(
                timeout_s=1.0,
                position_tolerance_m=1e-7,
                orientation_tolerance_rad=1e-7,
            ),
            fixed_joint_positions={"torso_yaw": desired[1]},
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.joint_names == ("right_slide", "torso_yaw", "left_slide")
    np.testing.assert_allclose(result.solution, desired, atol=2e-7)


def test_continuous_joint_uses_short_path_across_pi(robot_model) -> None:
    group = robot_model.create_group(
        name="bounded_continuous",
        joint_names=("spin",),
        base_frame="base",
        tip_frames=("spin_tip",),
    )
    seed = np.array([np.pi - 0.05])
    desired = np.array([-np.pi + 0.05])
    target = PoseTarget(
        tip_frame="spin_tip",
        reference_frame="base",
        pose=group.forward(desired),
    )

    result = PinocchioBoundedLeastSquaresSolver(
        group,
        BoundedLeastSquaresConfig(max_nfev=50),
    ).solve(
        _request(
            seed,
            [target],
            options=IKOptions(
                timeout_s=1.0,
                orientation_tolerance_rad=1e-7,
                max_solution_joint_displacement=0.2,
            ),
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.solution is not None
    assert group.difference(seed, result.solution)[0] == pytest.approx(0.1, abs=2e-6)
    assert -np.pi <= result.solution[0] < np.pi


def test_neutral_and_seed_regularizers_select_different_redundant_postures(
    tmp_path: Path,
) -> None:
    group = _redundant_slides(tmp_path)
    seed = np.array([0.9, 0.1])
    target_pose = group.forward([0.6, 0.6])
    target = PoseTarget(
        tip_frame="tip",
        reference_frame="base",
        pose=target_pose,
        task_weights=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    options = IKOptions(
        timeout_s=1.0,
        position_tolerance_m=1e-8,
        allow_approximate_solution=True,
    )

    neutral_result = PinocchioBoundedLeastSquaresSolver(
        group,
        BoundedLeastSquaresConfig(
            max_nfev=100,
            regularization_weight=0.02,
        ),
    ).solve(_request(seed, [target], options=options))
    smooth_result = PinocchioBoundedLeastSquaresSolver(
        group,
        BoundedLeastSquaresConfig(
            max_nfev=100,
            smooth_weight=0.02,
        ),
    ).solve(_request(seed, [target], options=options))

    neutral_positions = _returned_positions(neutral_result)
    smooth_positions = _returned_positions(smooth_result)
    assert neutral_result.status is IKStatus.NO_SOLUTION
    assert smooth_result.status is IKStatus.NO_SOLUTION
    assert np.linalg.norm(neutral_positions) < np.linalg.norm(smooth_positions)
    assert neutral_positions[1] > smooth_positions[1] + 0.05
    assert abs(neutral_positions[0] - neutral_positions[1]) < abs(
        smooth_positions[0] - smooth_positions[1]
    )
    assert neutral_result.active_position_error_m < 0.02
    assert smooth_result.active_position_error_m < 0.01


def test_collapsed_bounds_bypass_optimizer_and_return_projected_best(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_kinematics.bounded_least_squares as bounded_module

    solver = PinocchioBoundedLeastSquaresSolver(
        rp_group,
        BoundedLeastSquaresConfig(
            joint_position_bounds={
                "shoulder": (0.2, 0.2),
                "extension": (0.1, 0.1),
            }
        ),
    )

    def unexpected_optimizer(*args: object, **kwargs: object) -> object:
        raise AssertionError("least_squares must not run for collapsed bounds")

    monkeypatch.setattr(bounded_module, "_scipy_least_squares", unexpected_optimizer)
    result = solver.solve(
        _request(
            seed=[-0.8, 0.4],
            targets=[_target(rp_group, [0.8, 0.4])],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=True,
            ),
        )
    )

    assert result.status is IKStatus.NO_SOLUTION
    assert result.iterations == 0
    assert result.seed_was_projected is True
    np.testing.assert_allclose(result.approximate_solution, [0.2, 0.1], atol=0.0)


def test_max_nfev_is_a_strict_kinematics_evaluation_budget(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = np.array([-0.5, 0.0])
    target = _target(rp_group, [0.8, 0.4])
    group_type = type(rp_group)
    original_evaluate = group_type._evaluate
    evaluation_calls = 0

    def counted_evaluate(self, *args: object, **kwargs: object):
        nonlocal evaluation_calls
        evaluation_calls += 1
        return original_evaluate(self, *args, **kwargs)

    monkeypatch.setattr(group_type, "_evaluate", counted_evaluate)
    result = PinocchioBoundedLeastSquaresSolver(
        rp_group,
        BoundedLeastSquaresConfig(max_nfev=1),
    ).solve(
        _request(
            seed,
            [target],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=True,
            ),
        )
    )

    assert result.status is IKStatus.MAX_ITERATIONS
    assert result.iterations == 1
    assert evaluation_calls == 1
    np.testing.assert_allclose(result.approximate_solution, seed, atol=0.0)


def test_numerical_failure_never_exposes_an_unevaluated_candidate(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_type = type(rp_group)

    def failed_evaluate(self, *args: object, **kwargs: object):
        raise FloatingPointError("invalid backend state")

    monkeypatch.setattr(group_type, "_evaluate", failed_evaluate)
    result = PinocchioBoundedLeastSquaresSolver(rp_group).solve(
        _request(
            [0.0, 0.1],
            [
                PoseTarget(
                    tip_frame="tool",
                    reference_frame="base",
                    pose=_rp_pose(0.8, 0.4),
                )
            ],
            options=IKOptions(
                timeout_s=1.0,
                allow_approximate_solution=True,
            ),
        )
    )

    assert result.status is IKStatus.NUMERICAL_FAILURE
    assert result.solution is None
    assert result.approximate_solution is None


def test_timeout_during_pinocchio_evaluation_returns_timed_out(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group_type = type(rp_group)
    original_evaluate = group_type._evaluate

    def slow_evaluate(self, *args: object, **kwargs: object):
        evaluation = original_evaluate(self, *args, **kwargs)
        time.sleep(0.02)
        return evaluation

    monkeypatch.setattr(group_type, "_evaluate", slow_evaluate)
    result = PinocchioBoundedLeastSquaresSolver(rp_group).solve(
        _request(
            [0.0, 0.1],
            [_target(rp_group, [0.8, 0.4])],
            options=IKOptions(timeout_s=0.005),
        )
    )

    assert result.status is IKStatus.TIMED_OUT
    assert result.solution is None


def test_validator_receives_complete_state_and_can_reject_exact_solution(
    robot_model,
    rp_group,
) -> None:
    seed = np.array([0.3, 0.2])
    context_state = robot_model.create_state({"spin": 1.1, "side_joint": -0.4})
    received: list[RobotState] = []

    def reject(candidate: RobotState) -> bool:
        received.append(candidate)
        assert candidate.joint_positions["spin"] == pytest.approx(1.1, abs=1e-12)
        assert candidate.joint_positions["side_joint"] == pytest.approx(-0.4, abs=1e-12)
        return False

    result = PinocchioBoundedLeastSquaresSolver(rp_group).solve(
        _request(
            seed,
            [_target(rp_group, seed)],
            context_state=context_state,
            state_validator=reject,
        )
    )

    assert result.status is IKStatus.REJECTED_BY_VALIDATOR
    assert result.solution is None
    assert result.approximate_solution is None
    assert len(received) == 1


def test_bounded_config_rejects_invalid_joint_boxes_and_weights(rp_group) -> None:
    invalid_configs = [
        {"max_nfev": 0},
        {"regularization_weight": -1.0},
        {"smooth_weight": np.inf},
        {"ftol": np.finfo(np.float64).eps},
        {"joint_position_bounds": {"shoulder": (1.0, -1.0)}},
        {"joint_limit_margins": {"extension": -0.1}},
        {
            "joint_position_bounds": {"extension": (0.1, 0.4)},
            "joint_limit_margins": {"extension": 0.01},
        },
    ]
    for kwargs in invalid_configs:
        with pytest.raises((TypeError, ValueError)):
            BoundedLeastSquaresConfig(**kwargs)

    invalid_solver_configs = [
        BoundedLeastSquaresConfig(joint_position_bounds={"unknown": (0.0, 1.0)}),
        BoundedLeastSquaresConfig(joint_position_bounds={"extension": (-0.1, 0.4)}),
        BoundedLeastSquaresConfig(joint_limit_margins={"extension": 0.3}),
    ]
    for config in invalid_solver_configs:
        with pytest.raises(ValueError):
            PinocchioBoundedLeastSquaresSolver(rp_group, config)


def test_continuous_joint_rejects_ambiguous_absolute_position_box(robot_model) -> None:
    group = robot_model.create_group(
        name="continuous_absolute_box",
        joint_names=("spin",),
        base_frame="base",
        tip_frames=("spin_tip",),
    )
    config = BoundedLeastSquaresConfig(joint_position_bounds={"spin": (-1.0, 1.0)})

    with pytest.raises(ValueError, match="continuous"):
        PinocchioBoundedLeastSquaresSolver(group, config)


def test_bounded_config_is_immutable_deepcopy_and_pickle_safe() -> None:
    config = BoundedLeastSquaresConfig(
        max_nfev=37,
        regularization_weight=0.02,
        smooth_weight=0.1,
        joint_position_bounds={"joint1": (-1.0, 1.0)},
        joint_limit_margins={"joint2": 0.05},
    )

    assert copy.deepcopy(config) is config
    restored = pickle.loads(pickle.dumps(config))
    assert restored == config
    assert restored.joint_position_bounds == {"joint1": (-1.0, 1.0)}
    assert restored.joint_limit_margins == {"joint2": 0.05}
    with pytest.raises(TypeError):
        hash(config)
