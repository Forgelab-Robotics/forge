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

from forge_msgs import RobotAction, RobotState
from forge_msgs.value import ActuatorValue
from forge_robot.node_runner import run_dora_robot_node


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
    actuator_order = ["joint1"]

    def __init__(self) -> None:
        self.external_payloads: list[Any] = []
        self.actions: list[RobotAction] = []
        self.disconnected = False

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnected = True

    def get_state(self) -> RobotState:
        return RobotState(
            actuators={
                "joint1": ActuatorValue(value=1.0, mode="position", unit="radians"),
            },
        )

    def set_actuators(self, action: RobotAction) -> None:
        self.actions.append(action)

    def ingest_external_payload(self, payload: Any) -> None:
        self.external_payloads.append(payload)


def test_runner_ignores_external_path_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import forge_robot.node_runner as node_runner

    FakeNode.reset([{"type": "STOP"}])
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, actuator_order=driver.actuator_order) == 0

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
            actuator_order=driver.actuator_order,
            external_subscriptions=["ros2-joint-state"],
            on_external_event=driver.ingest_external_payload,
        )
        == 0
    )

    assert FakeNode.merged == ["ros2-joint-state"]
    assert driver.external_payloads == [{"joint1": 0.25}]
    assert driver.disconnected is True


def test_runner_tick_still_sends_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge_robot.node_runner as node_runner

    FakeNode.reset(
        [
            {"kind": "dora", "type": "INPUT", "id": "tick"},
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, actuator_order=driver.actuator_order) == 0

    assert [output_id for output_id, _ in FakeNode.sent] == ["state"]


def test_runner_parses_action_arrow(monkeypatch: pytest.MonkeyPatch) -> None:
    import forge_robot.node_runner as node_runner

    action = RobotAction(
        actuators={
            "joint1": ActuatorValue(value=0.5, mode="position", unit="radians"),
        },
    )
    FakeNode.reset(
        [
            {
                "kind": "dora",
                "type": "INPUT",
                "id": "action",
                "value": action.to_arrow(["joint1"]),
            },
            {"kind": "dora", "type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    driver = FakeDriver()
    assert run_dora_robot_node(driver, actuator_order=driver.actuator_order) == 0

    assert len(driver.actions) == 1
    assert driver.actions[0].actuators["joint1"].value == 0.5


def test_runner_requires_external_handler() -> None:
    driver = FakeDriver()
    with pytest.raises(ValueError, match="on_external_event"):
        run_dora_robot_node(
            driver,
            actuator_order=driver.actuator_order,
            external_subscriptions=["ros2-joint-state"],
        )
