# forge-msgs

Forge message definitions for Dora dataflow.

The canonical cross-language contract starts at
`interfaces/forge_msgs/forge_msgs.v1.yaml`. That manifest references the
versioned domain schemas that Python, Rust, and future C++ implementations
should follow.

## Core Messages

### `JointState`

Robot or simulator joint observation payload.

- `name: list[str]`
- `position: list[float]`
- `velocity: list[float]`
- `effort: list[float]`

`name` must be non-empty and unique. Numeric lists must either be empty or have the same length as `name`.

### `JointCommand`

Command payload for robot drivers and controllers.

- `name: list[str]`
- `mode: "position" | "velocity" | "effort" | "hybrid"`
- `position: list[float]`
- `velocity: list[float]`
- `effort: list[float]`
- `kp: list[float]`
- `kd: list[float]`

`mode` describes the command semantics. `position`, `velocity`, and `effort` match the common ROS2 command interfaces; `hybrid` is for low-level position/velocity/effort commands with optional `kp`/`kd` gains. Payloads written before `mode` existed are read as `mode="position"`.

For Unitree-style low-level control, map `position -> q`, `velocity -> dq`, `effort -> tau`, `kp -> kp`, and `kd -> kd`.

### `LocomotionCommand`

Planar body-frame locomotion velocity command for ground robots.

- `vx: float`
- `vy: float`
- `wz: float`

`vx` and `vy` are body-frame linear velocities in m/s, with positive X forward and positive Y left. `wz` is angular velocity about the body-frame Z axis in rad/s, positive counter-clockwise, corresponding to ROS2 `Twist.angular.z` / yaw rate. Stop is represented by all zeros. This message intentionally omits `mode`, `duration`, `gait`, `body_height`, timestamp/frame fields, and full 6D Twist fields.

### `Image`

Uncompressed image payload.

- `height: int`
- `width: int`
- `encoding: str`
- `step: int`
- `data: bytes`

Supported encodings are `rgb8`, `bgr8`, `mono8`, `16UC1`, and `32FC1`. Multi-byte pixels are little-endian. Compressed images use `CompressedImage`.

### `CompressedImage`

Compressed image bitstream payload.

- `format: str`
- `data: bytes`

Recommended formats are `jpeg`, `png`, and `webp`.

### `TeleopObservation`

XR device raw teleop observation for embodiment-specific teleop policies.

- `device: list[str]` — tracked device ids such as `left`, `right`, `headset`
- `x/y/z/qx/qy/qz/qw: list[float]` — pose fields aligned with `device`
- `confidence: list[float]` — per-device tracking confidence in `[0, 1]`
- `buttons_json: str` — JSON object of button bool/float values
- `axes_json: str` — JSON object of trigger/grip/joystick axis values

Timing and frame metadata are intentionally not part of the core schema. Carry them in Dora topic naming, node configuration, or adapter layers.

## Arrow Format

All core messages encode to a single-row `pyarrow.RecordBatch`.

```python
from forge_msgs import JointCommand, JointState

state = JointState(
    name=["joint1", "joint2"],
    position=[0.1, 0.2],
    velocity=[0.0, 0.0],
    effort=[],
)
batch = state.to_arrow()
back = JointState.from_arrow(batch)

command = JointCommand.from_np(
    values=[0.3, 0.4],
    order=["joint1", "joint2"],
    field="position",
)
```

Timing and frame data are intentionally not part of the core schema. Carry them in Dora event context, topic naming, node configuration, or adapter layers.
