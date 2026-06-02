from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np

FORGE_POLICY_ROOT = Path(__file__).parents[1]
FORGE_ROOT = FORGE_POLICY_ROOT.parents[1]
MSGS_SRC = FORGE_ROOT / "packages" / "msgs" / "src"
sys.path.insert(0, str(FORGE_POLICY_ROOT / "src"))
sys.path.insert(0, str(MSGS_SRC))

fake_dora = types.ModuleType("dora")
fake_dora.Node = object
sys.modules.setdefault("dora", fake_dora)

from forge_msgs import Image, JointCommand, JointState, PolicyCommand, PolicyCommandStatus
from forge_policy.node_runner import run_dora_policy_node


class FakeNode:
    events: list[dict[str, Any]] = []
    sent: list[tuple[str, Any]] = []

    def __init__(self) -> None:
        self._events = list(type(self).events)

    def __iter__(self):
        return iter(self._events)

    def send_output(self, output_id: str, value: Any) -> None:
        type(self).sent.append((output_id, value))

    @classmethod
    def reset(cls, events: list[dict[str, Any]]) -> None:
        cls.events = events
        cls.sent = []


class FakePolicy:
    def __init__(self) -> None:
        self.generated: list[dict[str, Any]] = []
        self.reset_count = 0
        self.observation_needed = True

    def is_observation_needed(self) -> bool:
        return self.observation_needed

    def generate_action(
        self,
        observation: dict[str, Any],
        alias_for_cameras: list[str] | None = None,
    ) -> list[float]:
        self.generated.append(observation)
        return [0.25]

    def reset(self) -> None:
        self.reset_count += 1


def _state_payload() -> Any:
    return JointState(name=["joint1"], position=[1.0]).to_arrow()


def _image_payload() -> Any:
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    return Image.from_numpy(frame, encoding="rgb8").to_arrow()


def _command_payload(command: str, policy_id: str = "default") -> Any:
    return PolicyCommand.from_inputs(policy_id=policy_id, command=command).to_arrow()


def _build_action(action: list[float]) -> JointCommand:
    return JointCommand(name=["joint1"], position=action)


def test_runner_waits_for_start(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "tick"},
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={"image/top": "top"},
        build_action=_build_action,
    ) == 0

    assert policy.generated == []
    assert FakeNode.sent == []


def test_runner_starts_and_sends_action(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("start")},
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "tick"},
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={"image/top": "top"},
        build_action=_build_action,
    ) == 0

    assert [output_id for output_id, _ in FakeNode.sent] == [
        "policy_command_status",
        "action",
    ]
    status = PolicyCommandStatus.from_arrow(FakeNode.sent[0][1])
    assert status.command == "start"
    assert status.status == "done"
    action = JointCommand.from_arrow(FakeNode.sent[1][1])
    assert action.position == [0.25]
    assert "observation.state" in policy.generated[0]
    assert "observation.images.top" in policy.generated[0]


def test_runner_reset_clears_cached_observation(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("start")},
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("reset")},
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("start")},
            {"type": "INPUT", "id": "tick"},
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={"image/top": "top"},
        build_action=_build_action,
    ) == 0

    assert policy.reset_count == 1
    assert policy.generated == []
    assert [output_id for output_id, _ in FakeNode.sent] == [
        "policy_command_status",
        "policy_command_status",
        "policy_command_status",
    ]


def test_runner_reset_scene_clears_cache_and_preserves_running(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("start")},
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("reset_scene")},
            {"type": "INPUT", "id": "tick"},
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "tick"},
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={"image/top": "top"},
        build_action=_build_action,
    ) == 0

    assert policy.reset_count == 1
    assert len(policy.generated) == 1
    assert [output_id for output_id, _ in FakeNode.sent] == [
        "policy_command_status",
        "policy_command_status",
        "action",
    ]
    status = PolicyCommandStatus.from_arrow(FakeNode.sent[1][1])
    assert status.command == "reset_scene"
    assert status.status == "done"
    assert status.outputs()["phase"] == "running"


def test_runner_reset_scene_preserves_paused_phase(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("start")},
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("pause")},
            {"type": "INPUT", "id": "policy_command", "value": _command_payload("reset_scene")},
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "tick"},
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={"image/top": "top"},
        build_action=_build_action,
    ) == 0

    assert policy.reset_count == 1
    assert policy.generated == []
    assert [output_id for output_id, _ in FakeNode.sent] == [
        "policy_command_status",
        "policy_command_status",
        "policy_command_status",
    ]
    status = PolicyCommandStatus.from_arrow(FakeNode.sent[2][1])
    assert status.command == "reset_scene"
    assert status.status == "done"
    assert status.outputs()["phase"] == "paused"


def test_runner_ignores_other_policy_id(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {
                "type": "INPUT",
                "id": "policy_command",
                "value": _command_payload("start", policy_id="other"),
            },
            {"type": "INPUT", "id": "proprio_state", "value": _state_payload()},
            {"type": "INPUT", "id": "image/top", "value": _image_payload()},
            {"type": "INPUT", "id": "tick"},
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={"image/top": "top"},
        build_action=_build_action,
    ) == 0

    assert policy.generated == []
    assert FakeNode.sent == []


def test_runner_rejects_unsupported_command(monkeypatch) -> None:
    import forge_policy.node_runner as node_runner

    FakeNode.reset(
        [
            {
                "type": "INPUT",
                "id": "policy_command",
                "value": _command_payload("unknown_command"),
            },
            {"type": "STOP"},
        ]
    )
    monkeypatch.setattr(node_runner, "Node", FakeNode)

    policy = FakePolicy()
    assert run_dora_policy_node(
        policy,
        joint_order=["joint1"],
        image_input_id_to_alias={},
        build_action=_build_action,
    ) == 0

    assert [output_id for output_id, _ in FakeNode.sent] == ["policy_command_status"]
    status = PolicyCommandStatus.from_arrow(FakeNode.sent[0][1])
    assert status.status == "rejected"
    assert status.message == "unsupported command: unknown_command"
