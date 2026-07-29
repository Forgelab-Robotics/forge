"""State, context, request, and validation contracts for kinematics v2."""

from __future__ import annotations

import copy
import pickle
import time

import numpy as np
import pytest

from forge_kinematics import (
    DlsConfig,
    IKOptions,
    IKRequest,
    IKStatus,
    KinematicsContext,
    KinematicsSolver,
    PinocchioDlsSolver,
    PoseTarget,
    RobotModel,
    RobotState,
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


def _target(
    pose: np.ndarray,
    *,
    reference_frame: str = "base",
    task_weights: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
) -> PoseTarget:
    return PoseTarget(
        tip_frame="tool",
        reference_frame=reference_frame,
        pose=pose,
        task_weights=task_weights,
    )


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


def test_robot_state_keeps_full_model_positions_and_updates_immutably(
    robot_model: RobotModel,
) -> None:
    continuous_input = 3.0 * np.pi + 0.2
    state = robot_model.create_state(
        {
            "shoulder": 0.3,
            "extension": 0.25,
            "spin": continuous_input,
            "side_joint": -0.4,
        }
    )

    assert isinstance(state, RobotState)
    assert {"shoulder", "extension", "spin", "side_joint"} <= set(state.joint_positions)
    assert state.joint_positions["shoulder"] == pytest.approx(0.3)
    assert state.joint_positions["extension"] == pytest.approx(0.25)
    assert state.joint_positions["side_joint"] == pytest.approx(-0.4)
    assert np.cos(state.joint_positions["spin"]) == pytest.approx(
        np.cos(continuous_input), abs=1e-12
    )
    assert np.sin(state.joint_positions["spin"]) == pytest.approx(
        np.sin(continuous_input), abs=1e-12
    )

    updated = state.with_joint_positions({"shoulder": -0.6, "side_joint": 0.7})

    assert updated is not state
    assert state.joint_positions["shoulder"] == pytest.approx(0.3)
    assert state.joint_positions["side_joint"] == pytest.approx(-0.4)
    assert updated.joint_positions["shoulder"] == pytest.approx(-0.6)
    assert updated.joint_positions["side_joint"] == pytest.approx(0.7)
    assert updated.joint_positions["extension"] == pytest.approx(0.25)

    invalid_updates = [
        ({"extension": 0.5001}, "extension"),
        ({"does_not_exist": 0.0}, "does_not_exist"),
        ({"spin": np.nan}, "spin"),
    ]
    for positions, bad_name in invalid_updates:
        with pytest.raises(ValueError, match=bad_name):
            state.with_joint_positions(positions)


def test_context_state_respects_base_relative_fk_and_permanent_locks(
    robot_model: RobotModel,
) -> None:
    extension_group = robot_model.create_group(
        name="extension_from_shoulder",
        joint_names=("extension",),
        base_frame="shoulder_link",
        tip_frames=("tool",),
    )
    state_a = robot_model.create_state({"shoulder": -1.1, "extension": 0.05})
    state_b = robot_model.create_state({"shoulder": 1.3, "extension": 0.45})
    context_a = robot_model.create_context()
    context_b = robot_model.create_context()
    active_positions = np.array([0.25])
    expected = np.eye(4)
    expected[:3, 3] = [1.25, 0.0, 0.1]

    np.testing.assert_allclose(
        extension_group.forward(active_positions, state=state_a, context=context_a),
        expected,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        extension_group.forward(active_positions, state=state_b, context=context_b),
        expected,
        atol=1e-12,
    )

    locked_group = robot_model.create_group(
        name="locked_extension_context_override",
        joint_names=("shoulder",),
        base_frame="base",
        tip_frames=("tool",),
        locked_joint_positions={"extension": 0.35},
    )
    conflicting_state = robot_model.create_state({"extension": 0.05})
    np.testing.assert_allclose(
        locked_group.forward(
            [0.4],
            state=conflicting_state,
            context=robot_model.create_context(),
        ),
        _rp_pose(0.4, 0.35),
        atol=1e-12,
    )


def test_state_and_context_from_another_model_are_rejected(
    robot_model: RobotModel,
    rp_group,
    urdf_path,
) -> None:
    other_model = RobotModel.from_urdf(urdf_path)
    foreign_state = other_model.create_state({"shoulder": 0.2})
    foreign_context = other_model.create_context()

    with pytest.raises(ValueError, match="RobotModel"):
        rp_group.forward([0.2, 0.1], state=foreign_state)
    with pytest.raises(ValueError, match="RobotModel"):
        rp_group.forward([0.2, 0.1], context=foreign_context)
    with pytest.raises(ValueError, match="RobotModel"):
        rp_group.jacobian([0.2, 0.1], context=foreign_context)


def test_context_is_reusable_across_forward_and_jacobian_calls(
    robot_model: RobotModel,
    rp_group,
) -> None:
    state = robot_model.create_state({"spin": 1.4, "side_joint": -0.8})
    context = robot_model.create_context()
    assert isinstance(context, KinematicsContext)

    first = np.array([-0.3, 0.1])
    second = np.array([0.8, 0.4])
    np.testing.assert_allclose(
        rp_group.forward(first, state=state, context=context),
        _rp_pose(*first),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        rp_group.jacobian(first, state=state, context=context),
        _rp_jacobian(*first),
        atol=1e-11,
    )
    np.testing.assert_allclose(
        rp_group.forward(second, state=state, context=context),
        _rp_pose(*second),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        rp_group.jacobian(second, state=state, context=context),
        _rp_jacobian(*second),
        atol=1e-11,
    )
    np.testing.assert_allclose(
        rp_group.forward(first, state=state, context=context),
        _rp_pose(*first),
        atol=1e-12,
    )


def test_ik_request_defensively_copies_mutable_inputs(robot_model: RobotModel) -> None:
    seed = np.array([0.1, 0.2])
    pose = _rp_pose(0.4, 0.3)
    expected_pose = pose.copy()
    target = _target(pose)
    targets = [target]
    fixed_positions = {"extension": 0.3}
    state = robot_model.create_state({"spin": 0.9})
    options = IKOptions(timeout_s=1.0)

    def validator(candidate: RobotState) -> bool:
        return True

    request = _request(
        seed,
        targets,
        options=options,
        context_state=state,
        fixed_joint_positions=fixed_positions,
        state_validator=validator,
    )
    seed[:] = [-1.0, -1.0]
    pose[0, 3] = 999.0
    targets.clear()
    fixed_positions["extension"] = 0.05

    np.testing.assert_array_equal(request.seed, [0.1, 0.2])
    assert isinstance(request.targets, tuple)
    assert len(request.targets) == 1
    np.testing.assert_allclose(request.targets[0].pose, expected_pose, atol=0.0)
    assert request.targets[0] is not target
    with pytest.raises(ValueError, match="read-only"):
        request.seed[0] = 0.0
    with pytest.raises(ValueError):
        request.seed.setflags(write=True)
    with pytest.raises(ValueError, match="read-only"):
        request.targets[0].pose[0, 3] = 0.0
    with pytest.raises(ValueError):
        request.targets[0].pose.setflags(write=True)
    assert request.fixed_joint_positions == {"extension": 0.3}
    assert request.options is options
    assert request.context_state is state
    assert request.state_validator is validator


def test_immutable_values_survive_deepcopy_and_pickle(rp_group) -> None:
    seed = np.array([0.1, 0.2])
    target = _target(rp_group.forward(seed))
    request = _request(
        seed,
        [target],
        fixed_joint_positions={"extension": 0.2},
    )

    assert copy.deepcopy(request) is request
    restored_request = pickle.loads(pickle.dumps(request))
    with pytest.raises(ValueError, match="read-only"):
        restored_request.seed[0] = 0.0
    with pytest.raises(ValueError, match="read-only"):
        restored_request.targets[0].pose[0, 3] = 0.0
    assert restored_request.fixed_joint_positions == {"extension": 0.2}

    result = PinocchioDlsSolver(rp_group).solve(request)
    assert result.status is IKStatus.SUCCESS
    assert copy.deepcopy(result) is result
    restored_result = pickle.loads(pickle.dumps(result))
    with pytest.raises(ValueError, match="read-only"):
        restored_result.solution[0] = 0.0


def test_ik_request_rejects_invalid_field_types(robot_model: RobotModel) -> None:
    state = robot_model.create_state()
    target = _target(np.eye(4))
    valid = {
        "seed": [0.0, 0.1],
        "targets": [target],
        "options": IKOptions(),
        "context_state": state,
        "fixed_joint_positions": {"extension": 0.1},
        "state_validator": lambda candidate: True,
    }
    invalid_fields = [
        ("seed", object(), "seed"),
        ("targets", [object()], "target"),
        ("options", object(), "options"),
        ("context_state", object(), "context_state"),
        ("fixed_joint_positions", [], "fixed_joint_positions"),
        ("state_validator", True, "state_validator"),
    ]

    for field, invalid_value, expected_message in invalid_fields:
        kwargs = dict(valid)
        kwargs[field] = invalid_value
        with pytest.raises((TypeError, ValueError), match=expected_message):
            IKRequest(**kwargs)


def test_solver_implements_runtime_protocol_and_accepts_only_requests(rp_group) -> None:
    solver = PinocchioDlsSolver(rp_group)

    assert isinstance(solver, KinematicsSolver)
    with pytest.raises(TypeError, match="IKRequest"):
        solver.solve([0.0, 0.1])


def test_target_reference_frame_must_match_group_and_fails_before_workspace(
    robot_model: RobotModel,
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = np.array([0.2, 0.15])
    target_pose = rp_group.forward(seed)
    solver = PinocchioDlsSolver(rp_group)
    matching = solver.solve(_request(seed, [_target(target_pose)]))
    assert matching.status is IKStatus.SUCCESS

    calls = 0
    original_create_context = RobotModel.create_context

    def counted_create_context(
        self: RobotModel, *args: object, **kwargs: object
    ) -> KinematicsContext:
        nonlocal calls
        calls += 1
        return original_create_context(self, *args, **kwargs)

    monkeypatch.setattr(RobotModel, "create_context", counted_create_context)
    mismatched = _target(target_pose, reference_frame="world")
    with pytest.raises(ValueError, match="reference_frame"):
        solver.solve(_request(seed, [mismatched]))
    assert calls == 0


def test_validator_receives_complete_solved_state_and_controls_success(
    robot_model: RobotModel,
    rp_group,
) -> None:
    desired = np.array([0.55, 0.3])
    context_state = robot_model.create_state({"spin": 1.2, "side_joint": -0.65})
    received: list[RobotState] = []

    def accept(candidate: RobotState) -> bool:
        received.append(candidate)
        positions = candidate.joint_positions
        assert {"shoulder", "extension", "spin", "side_joint"} <= set(positions)
        assert positions["shoulder"] == pytest.approx(desired[0], abs=2e-7)
        assert positions["extension"] == pytest.approx(desired[1], abs=1e-12)
        assert positions["spin"] == pytest.approx(1.2, abs=1e-12)
        assert positions["side_joint"] == pytest.approx(-0.65, abs=1e-12)
        return True

    options = IKOptions(
        allow_approximate_solution=True,
        position_tolerance_m=1e-7,
        orientation_tolerance_rad=1e-7,
        timeout_s=1.0,
    )
    config = DlsConfig(
        max_iterations=200,
        joint_limit_avoidance_weight=0.0,
    )
    accepted = PinocchioDlsSolver(rp_group, config=config).solve(
        _request(
            seed=[-0.4, 0.05],
            targets=[_target(rp_group.forward(desired))],
            options=options,
            context_state=context_state,
            fixed_joint_positions={"extension": desired[1]},
            state_validator=accept,
        )
    )

    assert accepted.status is IKStatus.SUCCESS
    assert len(received) == 1
    assert received[0] is not context_state
    assert accepted.solution is not None
    np.testing.assert_allclose(accepted.solution, desired, atol=2e-7)

    rejected = PinocchioDlsSolver(rp_group, config=config).solve(
        _request(
            seed=desired,
            targets=[_target(rp_group.forward(desired))],
            options=options,
            context_state=context_state,
            fixed_joint_positions={"extension": desired[1]},
            state_validator=lambda candidate: False,
        )
    )
    assert rejected.status is IKStatus.REJECTED_BY_VALIDATOR
    assert rejected.solution is None
    assert rejected.approximate_solution is None


def test_seed_canonicalization_is_timed_and_backend_failures_are_structured(
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = np.array([0.1, 0.2])
    target = _target(rp_group.forward(seed))
    group_type = type(rp_group)
    original_integrate = group_type.integrate

    def slow_integrate(self, positions: object, delta: object) -> np.ndarray:
        time.sleep(0.02)
        return original_integrate(self, positions, delta)

    monkeypatch.setattr(group_type, "integrate", slow_integrate)
    timed_out = PinocchioDlsSolver(rp_group).solve(
        _request(seed, [target], options=IKOptions(timeout_s=0.005))
    )
    assert timed_out.status is IKStatus.TIMED_OUT
    assert timed_out.elapsed_s > 0.005

    def failed_integrate(self, positions: object, delta: object) -> np.ndarray:
        raise RuntimeError("backend failed")

    monkeypatch.setattr(group_type, "integrate", failed_integrate)
    failed = PinocchioDlsSolver(rp_group).solve(_request(seed, [target]))
    assert failed.status is IKStatus.NUMERICAL_FAILURE
    assert "canonicalize" in failed.message


def test_validator_time_is_included_in_soft_deadline(rp_group) -> None:
    seed = np.array([0.1, 0.2])
    timeout_s = 0.005

    def slow_validator(candidate: RobotState) -> bool:
        time.sleep(0.02)
        return True

    result = PinocchioDlsSolver(rp_group).solve(
        _request(
            seed,
            [_target(rp_group.forward(seed))],
            options=IKOptions(timeout_s=timeout_s),
            state_validator=slow_validator,
        )
    )

    assert result.status is IKStatus.TIMED_OUT
    assert result.elapsed_s > timeout_s
    assert result.solution is None


def test_continuous_seed_and_dynamic_fixed_results_are_canonical(
    robot_model: RobotModel,
) -> None:
    group = robot_model.create_group(
        name="canonical_continuous",
        joint_names=("spin",),
        base_frame="base",
        tip_frames=("spin_tip",),
    )
    seed = np.array([3.0 * np.pi])
    target = PoseTarget(
        tip_frame="spin_tip",
        reference_frame="base",
        pose=group.forward(seed),
    )

    result = PinocchioDlsSolver(group).solve(_request(seed, [target]))
    fixed_result = PinocchioDlsSolver(group).solve(
        _request(seed, [target], fixed_joint_positions={"spin": 3.0 * np.pi})
    )

    assert result.status is IKStatus.SUCCESS
    assert fixed_result.status is IKStatus.SUCCESS
    expected = group.integrate(seed, [0.0])
    np.testing.assert_allclose(result.solution, expected, atol=1e-12)
    np.testing.assert_allclose(fixed_result.solution, expected, atol=1e-12)


def test_validator_exceptions_propagate_and_rejected_approximate_is_hidden(
    robot_model: RobotModel,
    rp_group,
) -> None:
    class ValidationFailure(RuntimeError):
        pass

    seed = np.array([0.1, 0.2])

    def raise_from_validator(candidate: RobotState) -> bool:
        raise ValidationFailure("validator failed")

    with pytest.raises(ValidationFailure, match="validator failed"):
        PinocchioDlsSolver(rp_group).solve(
            _request(
                seed,
                [_target(rp_group.forward(seed))],
                state_validator=raise_from_validator,
            )
        )

    validation_calls: list[RobotState] = []

    def reject(candidate: RobotState) -> bool:
        validation_calls.append(candidate)
        return False

    unreachable = _rp_pose(0.0, 0.8)
    result = PinocchioDlsSolver(
        rp_group,
        config=DlsConfig(
            max_iterations=50,
            joint_limit_avoidance_weight=0.0,
        ),
    ).solve(
        _request(
            seed=[0.0, 0.1],
            targets=[_target(unreachable)],
            options=IKOptions(
                allow_approximate_solution=True,
                timeout_s=1.0,
            ),
            context_state=robot_model.create_state({"side_joint": 0.4}),
            state_validator=reject,
        )
    )

    assert result.status is not IKStatus.SUCCESS
    assert validation_calls
    assert result.solution is None
    assert result.approximate_solution is None


def test_one_solve_creates_one_reused_context_workspace(
    robot_model: RobotModel,
    rp_group,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    desired = np.array([0.7, 0.35])
    target_pose = rp_group.forward(desired)
    calls = 0
    original_create_context = RobotModel.create_context

    def counted_create_context(
        self: RobotModel, *args: object, **kwargs: object
    ) -> KinematicsContext:
        nonlocal calls
        calls += 1
        return original_create_context(self, *args, **kwargs)

    monkeypatch.setattr(RobotModel, "create_context", counted_create_context)
    result = PinocchioDlsSolver(
        rp_group,
        config=DlsConfig(
            max_iterations=200,
            joint_limit_avoidance_weight=0.0,
        ),
    ).solve(
        _request(
            seed=[-0.5, 0.05],
            targets=[_target(target_pose)],
            options=IKOptions(
                position_tolerance_m=1e-7,
                orientation_tolerance_rad=1e-7,
                timeout_s=1.0,
            ),
            context_state=robot_model.create_state({"spin": -0.9}),
        )
    )

    assert result.status is IKStatus.SUCCESS
    assert result.iterations > 1
    assert calls == 1
