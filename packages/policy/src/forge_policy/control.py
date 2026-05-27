"""Lifecycle command handling for policy nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from forge_msgs import PolicyCommand, PolicyCommandStatus

PolicyPhase = Literal["idle", "running", "paused"]


@dataclass
class PolicyRuntimeState:
    """Mutable runtime state owned by a policy runner."""

    policy_id: str = "default"
    phase: PolicyPhase = "idle"
    last_command: str = ""
    last_error: str = ""
    command_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return self.phase == "running"


@dataclass(frozen=True)
class CommandResult:
    """Result of applying a policy command."""

    command: PolicyCommand
    status: Literal["accepted", "rejected", "running", "done", "error"]
    message: str = ""
    outputs: dict[str, Any] = field(default_factory=dict)
    reset_observation_cache: bool = False

    def to_status(self, policy_id: str) -> PolicyCommandStatus:
        return PolicyCommandStatus.from_outputs(
            policy_id=policy_id,
            command=self.command.command,
            request_id=self.command.request_id,
            status=self.status,
            message=self.message,
            outputs=self.outputs,
        )


def _call_optional(policy: Any, method_name: str) -> None:
    method = getattr(policy, method_name, None)
    if callable(method):
        method()


def apply_policy_command(
    *,
    state: PolicyRuntimeState,
    policy: Any,
    command: PolicyCommand,
    call_lifecycle_hooks: bool = False,
) -> CommandResult | None:
    """Apply a gateway PolicyCommand to the local runtime state.

    Returns None when the command targets a different policy_id.
    """
    if command.policy_id != state.policy_id:
        return None

    state.command_count += 1
    state.last_command = command.command
    inputs = command.inputs()

    try:
        match command.command:
            case "start" | "resume":
                state.phase = "running"
                if call_lifecycle_hooks:
                    _call_optional(policy, "start")
                return CommandResult(command, "done", outputs={"phase": state.phase})
            case "pause":
                state.phase = "paused"
                if call_lifecycle_hooks:
                    _call_optional(policy, "pause")
                return CommandResult(command, "done", outputs={"phase": state.phase})
            case "stop":
                state.phase = "idle"
                if call_lifecycle_hooks:
                    _call_optional(policy, "stop")
                return CommandResult(command, "done", outputs={"phase": state.phase})
            case "reset":
                state.phase = "idle"
                _call_optional(policy, "reset")
                return CommandResult(
                    command,
                    "done",
                    outputs={"phase": state.phase},
                    reset_observation_cache=True,
                )
            case "set_instruction":
                instruction = inputs.get("instruction")
                if not isinstance(instruction, str):
                    return CommandResult(
                        command,
                        "rejected",
                        message="set_instruction requires inputs.instruction string",
                    )
                setattr(policy, "instruction", instruction)
                return CommandResult(command, "done")
            case _:
                handler = getattr(policy, "handle_command", None)
                if not callable(handler):
                    return CommandResult(
                        command,
                        "rejected",
                        message=f"unsupported command: {command.command}",
                    )
                outputs = handler(command.command, inputs)
                if outputs is None:
                    outputs = {}
                if not isinstance(outputs, dict):
                    outputs = {"result": outputs}
                return CommandResult(command, "done", outputs=outputs)
    except Exception as exc:
        state.last_error = str(exc)
        return CommandResult(command, "error", message=str(exc))
