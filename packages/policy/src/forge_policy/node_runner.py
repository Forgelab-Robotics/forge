"""Standard Dora policy node loop."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from dora import Node
from forge_msgs import JointCommand, PolicyCommand

from .control import CommandResult, PolicyRuntimeState, apply_policy_command
from .observation import build_policy_observation
from .policy_protocol import PolicyAdapter

logger = logging.getLogger(__name__)

ActionBuilder = Callable[[Any], JointCommand]


def _send_command_status(
    *,
    node: Node,
    state: PolicyRuntimeState,
    result: CommandResult,
) -> None:
    try:
        node.send_output(
            "policy_command_status", result.to_status(state.policy_id).to_arrow()
        )
    except Exception:
        logger.exception("failed to send policy_command_status")


def run_dora_policy_node(
    policy: PolicyAdapter,
    *,
    joint_order: list[str],
    image_input_id_to_alias: dict[str, str],
    build_action: ActionBuilder,
    policy_id: str = "default",
    alias_for_cameras: list[str] | None = None,
    auto_start: bool = False,
    emit_command_status: bool = True,
    call_lifecycle_hooks: bool = False,
) -> int:
    """
    Run a standard Dora policy node.

    The runner handles gateway PolicyCommand input, observation caching, tick-gated
    inference, action output, and optional PolicyCommandStatus output.
    """
    if not joint_order:
        raise ValueError("joint_order must not be empty")

    camera_aliases = alias_for_cameras or list(image_input_id_to_alias.values())
    state = PolicyRuntimeState(
        policy_id=policy_id,
        phase="running" if auto_start else "idle",
    )
    cached_proprio: Any | None = None
    cached_images: dict[str, Any] = {}

    node = Node()

    for event in node:
        kind = event.get("kind")
        if kind not in (None, "dora"):
            continue

        match event.get("type"):
            case "INPUT":
                input_id = event["id"]
                value = event.get("value")

                if input_id == "policy_command" and value is not None:
                    command = PolicyCommand.from_arrow(value)
                    result = apply_policy_command(
                        state=state,
                        policy=policy,
                        command=command,
                        call_lifecycle_hooks=call_lifecycle_hooks,
                    )
                    if result is None:
                        continue
                    if result.reset_observation_cache:
                        cached_proprio = None
                        cached_images.clear()
                    if emit_command_status:
                        _send_command_status(node=node, state=state, result=result)
                    continue

                if input_id == "proprio_state" and value is not None:
                    cached_proprio = value
                    continue

                if input_id in image_input_id_to_alias and value is not None:
                    cached_images[input_id] = value
                    continue

                if input_id != "tick":
                    continue

                if not state.is_running:
                    continue

                if policy.is_observation_needed():
                    observation = build_policy_observation(
                        proprio_payload=cached_proprio,
                        image_payloads=cached_images,
                        joint_order=joint_order,
                        image_input_id_to_alias=image_input_id_to_alias,
                    )
                    if observation is None:
                        continue
                else:
                    observation = {}

                try:
                    action_payload = policy.generate_action(observation, camera_aliases)
                    if action_payload is None:
                        continue
                    action = build_action(action_payload)
                    node.send_output("action", action.to_arrow())
                except Exception:
                    logger.exception("policy tick failed")

            case "STOP":
                break

            case "ERROR":
                logger.error(
                    "policy node received ERROR: %s", event.get("error", "unknown")
                )
                break

            case _:
                pass

    return 0
