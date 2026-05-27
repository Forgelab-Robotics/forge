"""Observation helpers shared by policy nodes."""

from __future__ import annotations

from typing import Any

from forge_msgs import CompressedImage, Image, JointState


def decode_policy_image(payload: Any):
    """Decode forge_msgs image payloads to RGB HWC arrays for policy inputs."""
    try:
        img = Image.from_arrow(payload)
    except Exception:
        return CompressedImage.from_arrow(payload).to_numpy()

    frame = img.to_numpy()
    if img.encoding == "bgr8":
        return frame[..., ::-1].copy()
    if img.encoding == "rgb8":
        return frame
    raise ValueError(f"unsupported image encoding: {img.encoding}")


def build_policy_observation(
    *,
    proprio_payload: Any | None,
    image_payloads: dict[str, Any],
    joint_order: list[str],
    image_input_id_to_alias: dict[str, str],
) -> dict[str, Any] | None:
    """Build the observation dict expected by policy implementations."""
    if proprio_payload is None:
        return None
    missing_images = [
        input_id
        for input_id in image_input_id_to_alias
        if input_id not in image_payloads
    ]
    if missing_images:
        return None

    proprio = JointState.from_arrow(proprio_payload)
    observation: dict[str, Any] = {
        "observation.state": proprio.to_np(joint_order),
    }
    for input_id, alias in image_input_id_to_alias.items():
        observation[f"observation.images.{alias}"] = decode_policy_image(
            image_payloads[input_id]
        )
    return observation
