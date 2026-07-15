# forge_msgs Interface Schemas

This directory is the language-neutral contract for `forge_msgs`.

Python (`packages/msgs`), Rust (`crates/forge_msgs`), and C++
(`cpp/forge_msgs`) implementations should treat `forge_msgs.v1.yaml` and its
referenced domain schemas as the source of truth. The implementations are
handwritten, but their Arrow schemas and validation rules should conform to
these interfaces.

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

## Implementation Coverage

- Python implements the full v1 schema, including `TeleopObservation`.
- Rust implements the shared message set used across domains, excluding the
  Python-only `TeleopObservation`.
- C++ implements the same shared message set as Rust in `cpp/forge_msgs`, with
  `ToRecordBatch` / `FromRecordBatch` APIs and Arrow IPC stream helpers for
  Python/C++ compatibility tests.

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

### AudioChunk

Uncompressed audio buffer payload for streaming microphone or audio sources.

Fields:

- `sample_rate: uint32`
- `channels: uint32`
- `sample_format: utf8`
- `frame_count: uint32`
- `data: large_binary`

Rules:

- `sample_rate` and `channels` must be greater than zero.
- `sample_format` must be one of `f32le` or `s16le`.
- `frame_count` is the number of audio frames per channel, not the total sample count.
- `data` is interleaved PCM bytes. Multi-channel data is ordered by frame, e.g. `frame0_ch0`, `frame0_ch1`, `frame1_ch0`.
- `data` length must equal `frame_count * channels * bytes_per_sample`.
- Multi-byte sample formats are little-endian.
- `f32le` is little-endian float32 PCM. Producers should use normalized sample values in `[-1.0, 1.0]`.
- `s16le` is little-endian signed int16 PCM.
- Timing comes from the Dora event context. Source id, microphone placement, and calibration should live in Dora metadata, topic naming, node configuration, or adapter layers.

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
configuration. High-level constructors may infer unorganized clouds from
`x/y/z` by setting `height=1`, `width=len(x)`, and `is_dense` from finite XYZ
values.

### Perception result sets

`perception.v1.yaml` defines:

- `Detection2DSet`: oriented pixel-space boxes and flattened classification
  hypotheses. Axis-aligned boxes use `rotation=0`, and high-level
  constructors may fill that default automatically while serialized Arrow
  payloads still include the `rotation` column.
- `Detection3DSet`: oriented metric boxes and flattened classification
  hypotheses. Axis-aligned boxes use identity orientation (`qx=0`, `qy=0`,
  `qz=0`, `qw=1`), and high-level constructors may fill that default
  automatically while serialized Arrow payloads still include quaternion
  columns.
- `SegmentationMaskSet`: cropped binary instance masks positioned in a source
  image. Standalone masks can omit detection and track associations, and
  high-level constructors may fill empty associations and zero offsets while
  serialized Arrow payloads still include those columns.

Empty detections use empty per-detection lists and
`hypothesis_offset=[0]`. Detection class display names remain model
configuration rather than per-frame payload data.
OpenCV-style local features such as ORB, SIFT, or SuperPoint descriptors are
not part of the core streaming schema; keep them inside a node unless a future
pipeline needs cross-node feature reuse.

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

- `device: list<utf8>`: XR source ids; recommended ids are `left`, `right`,
  and `headset`.
- `x/y/z: list<float64>`: positions in meters.
- `qx/qy/qz/qw: list<float64>`: quaternion components in `xyzw` order.
- `confidence: list<float64>`: producer-defined per-device confidence in
  `[0, 1]`; it need not come directly from the XR SDK.
- `buttons_json: utf8`: JSON object whose digital values are booleans and
  analog trigger/grip values are finite numbers.
- `axes_json: utf8`: JSON object whose values are finite numbers or numeric
  arrays such as `[x, y]` joystick pairs.

Rules:

- `device` must be non-empty and unique.
- Consumers must match entries by device id and must not rely on list order.
- Pose and confidence lists must have the same length as `device`.
- Every pose and confidence value must be finite.
- Confidence values must be in the inclusive range `[0, 1]`.
- Each quaternion must not be all zero.
- `buttons_json` and `axes_json` must contain JSON objects.
- A producer may represent an unavailable pose with zero position, identity
  quaternion, and confidence `0`; consumers must not use a zero-confidence pose
  for control.
- Poses are expressed in the producer-configured XR tracking frame. The
  tracking-frame origin, handedness, and axis directions must be documented in
  producer configuration because they are not carried in this payload.
- Recommended button ids are `A`, `B`, `X`, `Y`, `left_trigger`,
  `right_trigger`, `left_grip`, `right_grip`, `left_joystick_click`, and
  `right_joystick_click`. Recommended axis ids are `left_axis` and `right_axis`;
  documented producer-specific derived-control ids are allowed.
- Timing comes from the Dora event context or an adapter layer; v1 has no
  timestamp field.
- The current implementation is Python-only.

### Text

Single UTF-8 text payload for ASR transcripts, LLM responses, TTS input, and
other text streams.

Fields:

- `text: utf8`

Rules:

- `text` must be a valid UTF-8 string.
- Producers should omit empty outputs when there is no meaningful text.

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
- `discard_recording`
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
