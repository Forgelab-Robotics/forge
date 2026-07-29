"""Regression tests for findings from the kinematics v2 review."""

from __future__ import annotations

import math
import pickle
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from forge_kinematics import (
    DlsConfig,
    IKOptions,
    IKRequest,
    IKResult,
    IKStatus,
    PinocchioDlsSolver,
    PoseTarget,
    RobotModel,
)
from forge_kinematics.dls import _evaluate_iteration, _so3_log


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


def _rotation_vector(rotation: np.ndarray) -> np.ndarray:
    cosine = float(np.clip((np.trace(rotation) - 1.0) * 0.5, -1.0, 1.0))
    angle = math.acos(cosine)
    if angle < 1e-10:
        return (
            np.array(
                [
                    rotation[2, 1] - rotation[1, 2],
                    rotation[0, 2] - rotation[2, 0],
                    rotation[1, 0] - rotation[0, 1],
                ]
            )
            * 0.5
        )
    return (
        angle
        / (2.0 * math.sin(angle))
        * np.array(
            [
                rotation[2, 1] - rotation[1, 2],
                rotation[0, 2] - rotation[2, 0],
                rotation[1, 0] - rotation[0, 1],
            ]
        )
    )


def _target(group, positions: object, **kwargs: object) -> PoseTarget:
    return PoseTarget(
        tip_frame=group.tip_frames[0],
        reference_frame=group.base_frame,
        pose=group.forward(positions),
        **kwargs,
    )


def _request(
    seed: object,
    target: PoseTarget,
    *,
    options: IKOptions | None = None,
    context_state: object = None,
    fixed_joint_positions: object = None,
    state_validator: object = None,
) -> IKRequest:
    return IKRequest(
        seed=seed,
        targets=(target,),
        options=IKOptions() if options is None else options,
        context_state=context_state,
        fixed_joint_positions=fixed_joint_positions,
        state_validator=state_validator,
    )


def _result(
    status: IKStatus,
    *,
    solution: object = None,
    approximate_solution: object = None,
) -> IKResult:
    return IKResult(
        status=status,
        joint_names=("joint",),
        solution=solution,
        approximate_solution=approximate_solution,
        iterations=1,
        elapsed_s=0.01,
        raw_position_error_m=0.0,
        raw_orientation_error_rad=0.0,
        active_position_error_m=0.0,
        active_orientation_error_rad=0.0,
        minimum_singular_value=1.0,
        message="test result",
    )


def _assert_array_metadata_isolated(
    array_getter: Callable[[], np.ndarray], expected_shape: tuple[int, ...]
) -> None:
    shape_view = array_getter()
    dtype_view = array_getter()

    shape_view.shape = (1, shape_view.size)
    dtype_view.dtype = np.uint8

    current = array_getter()
    assert current.shape == expected_shape
    assert current.dtype == np.dtype(np.float64)
    with pytest.raises(ValueError, match="read-only"):
        current.flat[0] = 0.0


def _single_axis_wrist(tmp_path: Path):
    path = tmp_path / "single_axis_wrist.urdf"
    path.write_text(
        """<robot name="single_axis_wrist">
  <link name="base"/><link name="tip"/>
  <joint name="wrist_z" type="revolute">
    <parent link="base"/><child link="tip"/><axis xyz="0 0 1"/>
    <limit lower="-2.8" upper="2.8" effort="1" velocity="1"/>
  </joint>
</robot>
""",
        encoding="utf-8",
    )
    return RobotModel.from_urdf(path).create_group(
        name="single_axis_wrist",
        joint_names=("wrist_z",),
        base_frame="base",
        tip_frames=("tip",),
    )


def _redundant_slides(tmp_path: Path):
    path = tmp_path / "redundant_slides_review.urdf"
    path.write_text(
        """<robot name="redundant_slides_review">
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
        name="redundant_slides_review",
        joint_names=("slide1", "slide2"),
        base_frame="base",
        tip_frames=("tip",),
    )


def _three_axis_wrist(tmp_path: Path):
    path = tmp_path / "three_axis_wrist.urdf"
    path.write_text(
        """<robot name="three_axis_wrist">
  <link name="base"/><link name="link_x"/><link name="link_y"/><link name="tip"/>
  <joint name="wrist_x" type="continuous">
    <parent link="base"/><child link="link_x"/><axis xyz="1 0 0"/>
  </joint>
  <joint name="wrist_y" type="continuous">
    <parent link="link_x"/><child link="link_y"/><axis xyz="0 1 0"/>
  </joint>
  <joint name="wrist_z" type="continuous">
    <parent link="link_y"/><child link="tip"/><axis xyz="0 0 1"/>
  </joint>
</robot>
""",
        encoding="utf-8",
    )
    return RobotModel.from_urdf(path).create_group(
        name="three_axis_wrist",
        joint_names=("wrist_x", "wrist_y", "wrist_z"),
        base_frame="base",
        tip_frames=("tip",),
    )


def test_large_noncommuting_rotation_uses_effective_single_axis_jacobian(
    tmp_path: Path,
) -> None:
    group = _single_axis_wrist(tmp_path)
    satisfying_position = np.array([1.1])
    seed = np.array([-0.9])
    target_pose = group.forward(satisfying_position)
    target_pose[:3, :3] = _rotation_x(1.8) @ target_pose[:3, :3]
    target = PoseTarget(
        tip_frame="tip",
        reference_frame="base",
        pose=target_pose,
        task_weights=(0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
    )

    def active_residual(position: np.ndarray) -> float:
        current_rotation = group.forward(position)[:3, :3]
        return float(_rotation_vector(target.pose[:3, :3] @ current_rotation.T)[1])

    epsilon = 1e-6
    effective_jacobian = -(
        active_residual(group.integrate(seed, [epsilon]))
        - active_residual(group.integrate(seed, [-epsilon]))
    ) / (2.0 * epsilon)
    geometric_selected_row = group.jacobian(seed)[4, 0]

    analytic_jacobian = _evaluate_iteration(
        group._evaluate(seed, ("tip",)), (target,)
    ).weighted_jacobian[0, 0]

    assert abs(effective_jacobian) > 0.1
    assert geometric_selected_row == pytest.approx(0.0, abs=1e-12)
    assert analytic_jacobian == pytest.approx(effective_jacobian, abs=1e-8)

    result = PinocchioDlsSolver(
        group,
        config=DlsConfig(damping=0.01, max_iterations=200),
    ).solve(
        _request(
            seed,
            target,
            options=IKOptions(
                orientation_tolerance_rad=1e-7,
                timeout_s=1.0,
            ),
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.solution is not None
    assert active_residual(result.solution) == pytest.approx(0.0, abs=1e-7)
    np.testing.assert_allclose(result.solution, satisfying_position, atol=2e-6)


def test_so3_log_stays_principal_and_accurate_near_pi() -> None:
    axis = np.array([0.3, -0.4, 0.5], dtype=np.float64)
    axis /= np.linalg.norm(axis)
    axis_skew = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )

    for gap in (5e-4, 2e-6, 1.1e-6):
        angle = math.pi - gap
        rotation = (
            np.eye(3)
            + math.sin(angle) * axis_skew
            + (1.0 - math.cos(angle)) * (axis_skew @ axis_skew)
        )
        rotation_vector = _so3_log(rotation)

        assert np.linalg.norm(rotation_vector) <= math.pi
        np.testing.assert_allclose(rotation_vector, angle * axis, atol=5e-9)


def test_near_pi_multi_axis_target_converges_with_default_step_cap(
    tmp_path: Path,
) -> None:
    group = _three_axis_wrist(tmp_path)
    satisfying = np.array([2.686, -0.767, -1.044])
    target = _target(
        group,
        satisfying,
        task_weights=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
    )

    result = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iterations=300,
            joint_limit_avoidance_weight=0.0,
        ),
    ).solve(
        _request(
            np.zeros(3),
            target,
            options=IKOptions(
                allow_approximate_solution=True,
                orientation_tolerance_rad=1e-9,
                timeout_s=2.0,
            ),
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.solution is not None
    solved_rotation = group.forward(result.solution)[:3, :3]
    target_rotation = target.pose[:3, :3]
    assert np.linalg.norm(_so3_log(target_rotation @ solved_rotation.T)) <= 1e-9


def test_default_avoidance_converges_redundant_primary_task_at_strict_tolerance(
    tmp_path: Path,
) -> None:
    group = _redundant_slides(tmp_path)
    desired = np.array([0.6, 0.6])
    target = _target(
        group,
        desired,
        task_weights=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    options = IKOptions(
        position_tolerance_m=1e-7,
        timeout_s=1.0,
    )
    config = DlsConfig(max_iterations=300)

    result = PinocchioDlsSolver(group, config=config).solve(
        _request([0.95, 0.15], target, options=options)
    )

    assert config.joint_limit_avoidance_weight > 0.0
    assert result.status is IKStatus.SUCCESS
    assert result.solution is not None
    primary_error = target.pose[0, 3] - group.forward(result.solution)[0, 3]
    assert primary_error == pytest.approx(0.0, abs=1e-7)


def test_default_avoidance_secondary_step_has_no_primary_jacobian_component(
    tmp_path: Path,
) -> None:
    group = _redundant_slides(tmp_path)
    seed = np.array([0.95, 0.15])
    target = _target(
        group,
        [0.6, 0.6],
        task_weights=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    options = IKOptions(
        allow_approximate_solution=True,
        position_tolerance_m=1e-12,
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
        ),
    )
    disabled = disabled_solver.solve(_request(seed, target, options=options))
    enabled = enabled_solver.solve(_request(seed, target, options=options))

    assert disabled.approximate_solution is not None
    assert enabled.approximate_solution is not None
    disabled_delta = group.difference(seed, disabled.approximate_solution)
    enabled_delta = group.difference(seed, enabled.approximate_solution)
    secondary_delta = enabled_delta - disabled_delta
    primary_jacobian = group.jacobian(seed)[0]

    assert np.linalg.norm(secondary_delta) > 0.0
    assert float(np.dot(primary_jacobian, secondary_delta)) == pytest.approx(
        0.0, abs=1e-12
    )


def test_clipped_secondary_step_has_no_primary_jacobian_component(
    tmp_path: Path,
) -> None:
    group = _redundant_slides(tmp_path)
    seed = np.array([0.95, 0.15])
    target = _target(
        group,
        [0.6, 0.6],
        task_weights=(1.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    options = IKOptions(
        allow_approximate_solution=True,
        position_tolerance_m=1e-12,
        timeout_s=1.0,
    )
    max_iteration_joint_step = 0.05
    primary_only_solver = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iteration_joint_step=max_iteration_joint_step,
            max_iterations=1,
            joint_limit_avoidance_weight=0.0,
        ),
    )
    with_secondary_solver = PinocchioDlsSolver(
        group,
        config=DlsConfig(
            max_iteration_joint_step=max_iteration_joint_step,
            max_iterations=1,
        ),
    )
    primary_only = primary_only_solver.solve(_request(seed, target, options=options))
    with_secondary = with_secondary_solver.solve(
        _request(seed, target, options=options)
    )

    assert primary_only.approximate_solution is not None
    assert with_secondary.approximate_solution is not None
    primary_delta = group.difference(seed, primary_only.approximate_solution)
    combined_delta = group.difference(seed, with_secondary.approximate_solution)
    realized_secondary_delta = combined_delta - primary_delta
    primary_jacobian = group.jacobian(seed)[0]

    assert primary_delta[1] < max_iteration_joint_step
    assert combined_delta[1] == pytest.approx(max_iteration_joint_step, abs=1e-12)
    assert np.linalg.norm(realized_secondary_delta) > 0.0
    assert float(np.dot(primary_jacobian, realized_secondary_delta)) == pytest.approx(
        0.0, abs=1e-12
    )
    assert np.all(np.abs(combined_delta) <= max_iteration_joint_step + 1e-12)
    assert np.all(with_secondary.approximate_solution >= group.lower_limits - 1e-12)
    assert np.all(with_secondary.approximate_solution <= group.upper_limits + 1e-12)


def test_expired_solve_does_not_start_approximate_validator(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(rp_group, [0.8, 0.4])
    group_type = type(rp_group)
    original_evaluate = group_type._evaluate

    def slow_evaluate(self, *args: object, **kwargs: object):
        evaluation = original_evaluate(self, *args, **kwargs)
        time.sleep(0.02)
        return evaluation

    monkeypatch.setattr(group_type, "_evaluate", slow_evaluate)
    validator_calls = 0

    def validator(candidate: object) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return True

    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            [0.0, 0.1],
            target,
            options=IKOptions(
                allow_approximate_solution=True,
                timeout_s=0.005,
            ),
            state_validator=validator,
        )
    )

    assert result.status is IKStatus.TIMED_OUT
    assert validator_calls == 0
    assert result.approximate_solution is None


def test_expired_line_search_does_not_start_candidate_evaluation(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(rp_group, [0.8, 0.4])
    group_type = type(rp_group)
    original_integrate = group_type.integrate
    original_evaluate = group_type._evaluate
    integrate_calls = 0
    evaluation_calls = 0

    def slow_candidate_integrate(self, *args: object, **kwargs: object):
        nonlocal integrate_calls
        integrate_calls += 1
        positions = original_integrate(self, *args, **kwargs)
        if integrate_calls == 2:
            time.sleep(0.02)
        return positions

    def tracked_evaluate(self, *args: object, **kwargs: object):
        nonlocal evaluation_calls
        evaluation_calls += 1
        return original_evaluate(self, *args, **kwargs)

    monkeypatch.setattr(group_type, "integrate", slow_candidate_integrate)
    monkeypatch.setattr(group_type, "_evaluate", tracked_evaluate)
    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            [0.0, 0.1],
            target,
            options=IKOptions(timeout_s=0.005),
        )
    )

    assert result.status is IKStatus.TIMED_OUT
    assert integrate_calls == 2
    assert evaluation_calls == 1


def test_expired_solve_does_not_start_converged_validator(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = np.array([0.3, 0.2])
    target = _target(rp_group, seed)
    group_type = type(rp_group)
    original_to_robot_state = group_type.to_robot_state

    def slow_to_robot_state(self, *args: object, **kwargs: object):
        state = original_to_robot_state(self, *args, **kwargs)
        time.sleep(0.02)
        return state

    monkeypatch.setattr(group_type, "to_robot_state", slow_to_robot_state)
    validator_calls = 0

    def validator(candidate: object) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return True

    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            seed,
            target,
            options=IKOptions(timeout_s=0.005),
            state_validator=validator,
        )
    )

    assert result.status is IKStatus.TIMED_OUT
    assert validator_calls == 0


def test_expired_solve_does_not_allocate_context_after_seed_canonicalization(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = np.array([0.3, 0.2])
    target = _target(rp_group, seed)
    group_type = type(rp_group)
    original_integrate = group_type.integrate
    original_create_context = RobotModel.create_context

    def slow_integrate(self, *args: object, **kwargs: object):
        positions = original_integrate(self, *args, **kwargs)
        time.sleep(0.02)
        return positions

    context_calls = 0

    def tracked_create_context(self: RobotModel):
        nonlocal context_calls
        context_calls += 1
        return original_create_context(self)

    monkeypatch.setattr(group_type, "integrate", slow_integrate)
    monkeypatch.setattr(RobotModel, "create_context", tracked_create_context)
    result = PinocchioDlsSolver(rp_group).solve(
        _request(seed, target, options=IKOptions(timeout_s=0.005))
    )

    assert result.status is IKStatus.TIMED_OUT
    assert context_calls == 0


def test_create_context_runtime_error_returns_numerical_failure(
    robot_model: RobotModel,
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = np.array([0.2, 0.1])
    target = _target(rp_group, seed)

    def failed_create_context(self: RobotModel):
        raise RuntimeError("backend context allocation failed")

    monkeypatch.setattr(RobotModel, "create_context", failed_create_context)
    result = PinocchioDlsSolver(rp_group).solve(_request(seed, target))

    assert result.status is IKStatus.NUMERICAL_FAILURE
    assert result.solution is None
    assert "context" in result.message


def test_pose_target_array_view_metadata_cannot_corrupt_target_or_solve(
    rp_group,
) -> None:
    seed = np.array([0.3, 0.2])
    target = _target(rp_group, seed)

    _assert_array_metadata_isolated(lambda: target.pose, (4, 4))
    result = PinocchioDlsSolver(rp_group).solve(_request(seed, target))

    assert result.status is IKStatus.SUCCESS
    np.testing.assert_allclose(target.pose, rp_group.forward(seed), atol=0.0)


def test_request_array_view_metadata_cannot_corrupt_request_or_solve(rp_group) -> None:
    seed = np.array([0.3, 0.2])
    request = _request(seed, _target(rp_group, seed))

    _assert_array_metadata_isolated(lambda: request.seed, (2,))
    result = PinocchioDlsSolver(rp_group).solve(request)

    assert result.status is IKStatus.SUCCESS
    np.testing.assert_array_equal(request.seed, seed)


def test_result_array_view_metadata_cannot_corrupt_result_arrays(rp_group) -> None:
    seed = np.array([0.3, 0.2])
    successful = PinocchioDlsSolver(rp_group).solve(
        _request(seed, _target(rp_group, seed))
    )
    approximate = _result(
        IKStatus.MAX_ITERATIONS,
        approximate_solution=[0.25],
    )

    assert successful.solution is not None
    assert approximate.approximate_solution is not None
    _assert_array_metadata_isolated(lambda: successful.solution, (2,))
    _assert_array_metadata_isolated(lambda: approximate.approximate_solution, (1,))
    np.testing.assert_array_equal(successful.solution, seed)
    np.testing.assert_array_equal(approximate.approximate_solution, [0.25])


def test_result_rejects_approximate_values_for_success_and_validator_rejection() -> (
    None
):
    invalid_results = [
        (IKStatus.SUCCESS, [0.1]),
        (IKStatus.REJECTED_BY_VALIDATOR, None),
    ]

    failures: list[str] = []
    for status, solution in invalid_results:
        try:
            _result(
                status,
                solution=solution,
                approximate_solution=[0.2],
            )
        except ValueError as exc:
            if "approximate" not in str(exc):
                failures.append(f"{status.value}: unexpected message {exc!s}")
        else:
            failures.append(f"{status.value}: accepted approximate_solution")

    assert not failures, "; ".join(failures)


def test_request_pickle_requires_no_context_state_or_validator(
    robot_model: RobotModel,
    rp_group,
) -> None:
    seed = np.array([0.2, 0.1])
    target = _target(rp_group, seed)
    portable = _request(seed, target, fixed_joint_positions={"extension": 0.1})

    restored = pickle.loads(pickle.dumps(portable))
    np.testing.assert_array_equal(restored.seed, seed)
    np.testing.assert_array_equal(restored.targets[0].pose, target.pose)
    assert restored.fixed_joint_positions == {"extension": 0.1}

    nonportable_requests = [
        (
            "context_state",
            _request(
                seed,
                target,
                context_state=robot_model.create_state(),
            ),
        ),
        ("state_validator", _request(seed, target, state_validator=bool)),
    ]
    failures: list[str] = []
    for field, request in nonportable_requests:
        try:
            pickle.dumps(request)
        except TypeError as exc:
            if field not in str(exc):
                failures.append(f"{field}: unexpected message {exc!s}")
        except Exception as exc:  # noqa: BLE001 - report the public exception contract.
            failures.append(f"{field}: raised {type(exc).__name__}, not TypeError")
        else:
            failures.append(f"{field}: request was unexpectedly pickleable")

    assert not failures, "; ".join(failures)


def test_array_backed_value_equality_returns_bools_without_raising(rp_group) -> None:
    seed = np.array([0.2, 0.1])
    pose = rp_group.forward(seed)
    target_a = PoseTarget("tool", pose, "base")
    target_b = PoseTarget("tool", pose.copy(), "base")
    request_a = _request(seed, target_a)
    request_b = _request(seed.copy(), target_b)
    result_a = _result(IKStatus.SUCCESS, solution=[0.2])
    result_b = _result(IKStatus.SUCCESS, solution=np.array([0.2]))

    equal_pairs = [
        ("PoseTarget", target_a, target_b),
        ("IKRequest", request_a, request_b),
        ("IKResult", result_a, result_b),
    ]
    failures: list[str] = []
    for name, left, right in equal_pairs:
        try:
            equal = left == right
            unequal = left != right
        except Exception as exc:  # noqa: BLE001 - equality must never raise.
            failures.append(f"{name}: raised {type(exc).__name__}")
            continue
        if equal is not True or unequal is not False:
            failures.append(f"{name}: equality did not return consistent bools")

    different_pose = pose.copy()
    different_pose[0, 3] += 0.1
    try:
        different = target_a != PoseTarget("tool", different_pose, "base")
    except Exception as exc:  # noqa: BLE001 - equality must never raise.
        failures.append(f"different PoseTarget: raised {type(exc).__name__}")
    else:
        if different is not True:
            failures.append("different PoseTarget values compared equal")

    assert not failures, "; ".join(failures)


def test_extreme_integer_inputs_are_value_errors_not_overflow_errors(
    robot_model: RobotModel,
    rp_group,
) -> None:
    huge = 10**10_000
    target = _target(rp_group, [0.2, 0.1])
    solver = PinocchioDlsSolver(rp_group)
    invalid_calls: list[tuple[str, Callable[[], object]]] = [
        (
            "PoseTarget.position_weight",
            lambda: PoseTarget("tool", np.eye(4), "base", position_weight=huge),
        ),
        ("IKOptions.timeout_s", lambda: IKOptions(timeout_s=huge)),
        ("DlsConfig.damping", lambda: DlsConfig(damping=huge)),
        ("IKRequest.seed", lambda: IKRequest(seed=[huge, huge], targets=(target,))),
        (
            "IKResult.solution",
            lambda: _result(IKStatus.SUCCESS, solution=[huge]),
        ),
        ("KinematicGroup.forward", lambda: rp_group.forward([huge, huge])),
        (
            "RobotModel.create_state",
            lambda: robot_model.create_state({"shoulder": huge}),
        ),
        (
            "IKRequest.fixed_joint_positions",
            lambda: solver.solve(
                _request(
                    [0.2, 0.1],
                    target,
                    fixed_joint_positions={"extension": huge},
                )
            ),
        ),
    ]

    failures: list[str] = []
    for name, invalid_call in invalid_calls:
        try:
            invalid_call()
        except ValueError:
            pass
        except Exception as exc:  # noqa: BLE001 - report the public exception contract.
            failures.append(f"{name}: raised {type(exc).__name__}, not ValueError")
        else:
            failures.append(f"{name}: unexpectedly accepted the extreme integer")

    assert not failures, "; ".join(failures)
