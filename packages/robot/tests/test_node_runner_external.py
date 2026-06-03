from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

FORGE_ROBOT_ROOT = Path(__file__).parents[1]
FRAMEWORK_ROOT = FORGE_ROBOT_ROOT.parents[2]
MSGS_SRC = FRAMEWORK_ROOT / "forge" / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_ROBOT_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

fake_dora = types.ModuleType("dora")
fake_dora.Node = object
sys.modules.setdefault("dora", fake_dora)

from forge_msgs import JointCommand, JointState, LocomotionCommand  # noqa: E402
from forge_robot.node_runner import run_dora_robot_node  # noqa: E402


class FakeNode:
    events: list[dict[str, Any]] = []
    merged: list[Any] = []
    sent: list[tuple[str, Any]] = []

    def __init__(self) -> None:
        self._events = list(type(self).events)

    def __iter__(self):
        return iter(self._events)

    def merge_external_events(self, subscription: Any) -> None:
        type(self).merged.append(subscription)

    def send_output(self, output_id: str, value: Any) -> None:
        type(self).sent.append((output_id, value))

    @classmethod
    def reset(cls, events: list[dict[str, Any]]) -> None:
        cls.events = events
        cls.merged = []
        cls.sent = []


class FakeDriver:
    joint_order = ["joint1"]

    def __init__(self) -> None:
        self.external_payloads: list[Any] = []
        self.commands: list[JointCommand] = []
        self.locomotion_commands: list[LocomotionCommand] = []
        self.disconnected = False

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnected = True

    def get_state(self) -> JointState:
        return JointState(name=["joint1"], position=[1.0])

    def set_command(self, command: JointCommand) -> None:
        self.commands.append(command)

    def set_locomotion_command(self, command: LocomotionCommand) -> None:
        self.locomotion_commands.append(command)

    def ingest_external_payload(self, payload: Any) -> None:
        self.external_payloads.append(payload)


class FakeJointOnlyDriver:
    joint_order = ["joint1"]

    def __init__(self) -> None:
        self.commands: list[JointCommand] = []
        self.disconnected = False

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnected = True

    def get_state(self) -> JointState:
        return JointState(name=["joint1"], position=[1.0])

    def set_command(self, command: JointCommand) -> None:
        self.commands.append(command)


class FakeLocomotionOnlyDriver:
    def __init__(self) -> None:
        self.locomotion_commands: list[LocomotionCommand] = []
        self.disconnected = False

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnected = True

    def get_state(self) -> JointState:
        return JointState(name=["base"], position=[0.0])

    def set_locomotion_command(self, command: LocomotionCommand) -> None:
        self.locomotion_commands.append(command)


def test_runner_ignores_external_path_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    FakeNode.reset([{"type": "STOP"}])
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert FakeNode.merged == []
    assert driver.disconnected is True


def test_runner_merges_and_ingests_external_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    FakeNode.reset(
        [
            {"kind": "external", "value": {"joint1": 0.25}},
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert (
        run_dora_robot_node(
            driver,
            joint_order=driver.joint_order,
            external_subscriptions=["ros2-joint-state"],
            on_external_event=driver.ingest_external_payload,
        )
        == 0
    )

    assert FakeNode.merged == ["ros2-joint-state"]
    assert driver.external_payloads == [{"joint1": 0.25}]
    assert driver.disconnected is True


def test_runner_tick_sends_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge_robot.node_runner as node_runner

    FakeNode.reset(
        [
            {"kind": "dora", "type": "INPUT", "id": "tick"},
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert [output_id for output_id, _ in FakeNode.sent] == ["state"]
    state = JointState.from_arrow(FakeNode.sent[0][1])
    assert state.position == [1.0]


def test_runner_parses_command_arrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    command = JointCommand(name=["joint1"], position=[0.5])
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "action",
                "value": command.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert len(driver.commands) == 1
    assert driver.commands[0].position == [0.5]


def test_runner_maps_master_state_to_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    state = JointState(name=["joint1"], position=[0.75])
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "master_state",
                "value": state.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert len(driver.commands) == 1
    assert driver.commands[0].position == [0.75]
    assert driver.commands[0].velocity == []


@pytest.mark.parametrize("input_id", ["command", "master_joint_state", "cmd_vel", "locomotion"])
def test_runner_ignores_non_standard_control_aliases(
    monkeypatch: pytest.MonkeyPatch,
    input_id: str,
) -> None:
    import forge_robot.node_runner as node_runner

    command = JointCommand(name=["joint1"], position=[0.5])
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": input_id,
                "value": command.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert driver.commands == []
    assert driver.locomotion_commands == []


def test_runner_parses_locomotion_command_arrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    command = LocomotionCommand(vx=0.5, vy=0.1, wz=0.2)
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "locomotion_command",
                "value": command.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert driver.locomotion_commands == [command]


def test_runner_ignores_locomotion_command_for_joint_only_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    command = LocomotionCommand(vx=0.5, vy=0.1, wz=0.2)
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "locomotion_command",
                "value": command.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeJointOnlyDriver()
    assert run_dora_robot_node(driver, joint_order=driver.joint_order) == 0

    assert driver.commands == []


def test_runner_accepts_locomotion_without_joint_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    command = LocomotionCommand(vx=0.5, vy=0.1, wz=0.2)
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "locomotion_command",
                "value": command.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeLocomotionOnlyDriver()
    assert run_dora_robot_node(driver) == 0

    assert driver.locomotion_commands == [command]


def test_runner_ignores_action_without_joint_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    command = JointCommand(name=["joint1"], position=[0.5])
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "action",
                "value": command.to_arrow(),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, joint_order=[]) == 0

    assert driver.commands == []


def test_runner_requires_external_handler() -> None:
    driver = FakeDriver()
    with pytest.raises(ValueError, match="on_external_event"):
        run_dora_robot_node(
            driver,
            joint_order=driver.joint_order,
            external_subscriptions=["ros2-joint-state"],
        )
