# forge_msgs Interface Schemas

This directory is the language-neutral contract for `forge_msgs`.

Python (`packages/msgs`), Rust (`crates/forge_msgs`), and future C++
implementations should treat `forge_msgs.v1.yaml` and its referenced domain
schemas as the source of truth. The implementations may be handwritten at
first, but their Arrow schemas and validation rules should conform to these
interfaces.

## Schema Layout

- `forge_msgs.v1.yaml` is the package manifest and transport contract.
- `common.v1.yaml` defines conventions shared across domains.
- `control.v1.yaml` defines robot and policy control messages.
- `geometry.v1.yaml` defines reusable geometry messages.
- `interaction.v1.yaml` defines human interaction and teleoperation messages.
- `perception.v1.yaml` defines perception result messages.
- `sensor.v1.yaml` defines raw sensor payloads.

Domain schemas evolve independently. Adding a new message to a domain does not
change the wire contract of existing messages.

## Transport Contract

- Payloads are single-row Apache Arrow `RecordBatch` values.
- The schema does not require Arrow metadata. Dora/IPC paths may drop metadata, so required semantics must be represented as real columns.
- Core messages do not contain ROS-style `Header`, timestamp, or `frame_id`.
- Timing comes from the Dora event context. Derived outputs should preserve the
  timestamp of the source event when they describe that source sample.
- Frame and fixed calibration information should live in Dora metadata, topic
  naming, node configuration, or adapter layers.

## Messages

### JointState

Robot or simulator joint observation payload.

Fields:

- `name: list<utf8>`
- `position: list<float64>`
- `velocity: list<float64>`
- `effort: list<float64>`

Rules:

- `name` must be non-empty.
- `name` items must be unique.
- `position`, `velocity`, and `effort` must either be empty or have the same length as `name`.
- Units follow common robotics convention: revolute position in radians, velocity in radians/s, effort in Nm; prismatic position in meters, velocity in meters/s, effort in N.

### JointCommand

Joint command payload for robot drivers and controllers.

Fields:

- `name: list<utf8>`
- `mode: utf8`
- `position: list<float64>`
- `velocity: list<float64>`
- `effort: list<float64>`
- `kp: list<float64>`
- `kd: list<float64>`

Rules:

- `name` must be non-empty.
- `name` items must be unique.
- `mode` must be one of `position`, `velocity`, `effort`, or `hybrid`. Payloads written before `mode` existed may omit it; readers treat missing or null `mode` as `position`.
- Each numeric list must either be empty or have the same length as `name`.
- `kp` and `kd` are optional low-level gains. For Unitree-style low-level control, map `position -> q`, `velocity -> dq`, `effort -> tau`, `kp -> kp`, and `kd -> kd`.

### LocomotionCommand

Planar body-frame locomotion velocity command for ground robots.

Fields:

- `vx: float64`
- `vy: float64`
- `wz: float64`

Rules:

- `vx` is body-frame X linear velocity in m/s; positive means forward.
- `vy` is body-frame Y linear velocity in m/s; positive means left. Differential-drive robots may require `vy == 0`.
- `wz` is angular velocity about the body-frame Z axis in rad/s; positive means counter-clockwise and corresponds to ROS2 `Twist.angular.z` / yaw rate.
- `vx`, `vy`, and `wz` must be finite values.
- Stop is represented by `vx=0`, `vy=0`, and `wz=0`.
- This message intentionally does not include `mode`, `duration`, `gait`, `body_height`, `frame_id`, timestamp, or full 6D `Twist` fields.

### Image

Uncompressed image payload.

Fields:

- `height: uint32`
- `width: uint32`
- `encoding: utf8`
- `step: uint32`
- `data: large_binary`

Rules:

- `step` is the full row length in bytes and may include row padding.
- `data` length must equal `step * height`.
- For known encodings, `step` must be at least `width * bytes_per_pixel`.
- Multi-byte pixel encodings are little-endian.
- Compressed `jpeg`, `png`, or `webp` payloads use `CompressedImage`.

Recommended encodings:

- `rgb8`
- `bgr8`
- `mono8`
- `16UC1`
- `32FC1`

### CompressedImage

Compressed image bitstream payload.

Fields:

- `format: utf8`
- `data: large_binary`

Recommended formats:

- `jpeg`
- `png`
- `webp`

### PointCloud

Organized or unorganized XYZ point cloud with common optional attributes.

Fields:

- `width/height: uint32`
- `is_dense: bool`
- `x/y/z: list<float32>`
- `intensity: list<float32>`
- `red/green/blue: list<uint8>`

XYZ coordinates use meters. Optional attribute columns are empty or match the
point count. The coordinate frame comes from Dora metadata or node
configuration.

### Perception result sets

`perception.v1.yaml` defines:

- `Detection2DSet`: oriented pixel-space boxes and flattened classification
  hypotheses.
- `Detection3DSet`: oriented metric boxes and flattened classification
  hypotheses.
- `SegmentationMaskSet`: cropped binary instance masks positioned in a source
  image.
- `Keypoint2DSet`: image keypoints and optional fixed-width descriptors.
- `KeypointMatchSet`: pairwise matches between named keypoint inputs.

Empty detections use empty per-detection lists and
`hypothesis_offset=[0]`. Detection class display names remain model
configuration rather than per-frame payload data.

### Pose

Header-less 3D pose payload with position and quaternion orientation.

Fields:

- `x: float64`
- `y: float64`
- `z: float64`
- `qx: float64`
- `qy: float64`
- `qz: float64`
- `qw: float64`

Rules:

- Quaternion `qx`, `qy`, `qz`, `qw` must not be all zero.
- Implementations should not silently normalize quaternion values.
- 2D pose should use helpers such as `Pose.from_xy_yaw(...)`, not a separate wire schema.

### PoseSet

Single-row named collection of poses.

Fields:

- `name: list<utf8>`
- `x: list<float64>`
- `y: list<float64>`
- `z: list<float64>`
- `qx: list<float64>`
- `qy: list<float64>`
- `qz: list<float64>`
- `qw: list<float64>`

Rules:

- `name` must be non-empty.
- `name` items must be unique.
- Every numeric list must have the same length as `name`.
- Each quaternion must not be all zero.

### TeleopObservation

XR device raw teleoperation observation.

Fields:

- `device: list<utf8>`
- `x/y/z/qx/qy/qz/qw: list<float64>`
- `confidence: list<float64>`
- `buttons_json: utf8`
- `axes_json: utf8`

Rules:

- `device` must be non-empty and unique.
- Pose and confidence lists must have the same length as `device`.
- Each quaternion must not be all zero.
- `buttons_json` and `axes_json` must contain JSON objects.
- The current implementation is Python-only.

### PolicyCommand

Command payload sent from gateway to policy through Dora.

Delivery topic:

- `policy_command`

Fields:

- `policy_id: utf8`
- `command: utf8`
- `request_id: utf8`
- `inputs_json: utf8`

Rules:

- `policy_id` must be non-empty. Use `default` for single-policy setups.
- `command` must be non-empty and use snake_case.
- `request_id` may be empty when no response is expected.
- `inputs_json` must parse as a JSON object. Use `{}` when there are no inputs.
- A `PolicyCommandStatus` response is optional.

Recommended commands:

- `load`
- `start`
- `stop`
- `pause`
- `resume`
- `reset`
- `start_recording`
- `stop_recording`
- `load_playback`
- `start_playback`
- `pause_playback`
- `resume_playback`
- `reset_playback`
- `seek_playback`
- `set_playback_rate`

### PolicyCommandStatus

Optional status payload sent from policy to gateway through Dora.

Delivery topic:

- `policy_command_status`

Fields:

- `policy_id: utf8`
- `command: utf8`
- `request_id: utf8`
- `status: utf8`
- `message: utf8`
- `outputs_json: utf8`

Rules:

- This message is optional. Policies may omit status output when no response is required.
- `policy_id` and `command` must be non-empty.
- `request_id` should match the originating `PolicyCommand` when present.
- `status` must be one of `accepted`, `rejected`, `running`, `done`, or `error`.
- `message` may be empty.
- `outputs_json` must parse as a JSON object. Use `{}` when there are no outputs.

## Cross-Language Implementation Notes

- Python, Rust, and C++ structs should use the same field names as the schema.
- Arrow field order should match the message's domain schema.
- Implementations should reject duplicate joint names and invalid list lengths.
- Implementations should not infer missing columns unless a field explicitly defines a compatibility default. Otherwise, a payload either conforms to the schema or fails validation.
- Helper methods may convert to fixed-order arrays, but fixed order is not part of the wire schema.
- Run `uv run python scripts/check_forge_msgs_schema.py` after changing schema
  files.
